"""Conservative Discovery for YanmagaWeb's public episode listing."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import quote, unquote_plus, unquote_to_bytes, urlsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from screenshot_crawler.discovery.base import DiscoveryAdapter
from screenshot_crawler.discovery.models import (
    DiscoveredItem,
    DiscoveredRecord,
    DiscoveredSource,
    DiscoveryMode,
)
from screenshot_crawler.discovery.service import DiscoveryIncompleteError
from screenshot_crawler.watchlist.models import WatchlistTarget

SITE_HOST = "yanmaga.jp"
LIST_SELECTOR = ".detailv2-episodes"
ROW_SELECTOR = ".mod-episode-item"
MORE_SELECTOR = ".mod-episode-more-button"
FREE_SELECTOR = ".mod-episode-point--free"
FREE_COLOR = "rgb(220, 0, 0)"
WAIT_TIMEOUT_MS = 15_000
STABILITY_TIMEOUT_MS = 5_000
STABILITY_POLL_MS = 100
STABLE_READS_REQUIRED = 2
MAX_EXPANSIONS = 100
MAX_ROWS = 5_000
MAX_PAGE_SIZE = 100
LOGIN_TELEMETRY_TIMEOUT_MS = 3_000
LOGIN_TELEMETRY_QUIET_MS = 300
MAX_LOGIN_TELEMETRY_EVENTS = 64

_EPISODE_ID = re.compile(r"^[0-9a-f]{32}$")
_WORK_PATH = re.compile(r"^/comics/(?P<slug>[^/]+)$")
_EPISODE_PATH = re.compile(r"^/comics/(?P<slug>[^/]+)/(?P<episode_id>[0-9a-f]{32})$")
_LIST_PATH = re.compile(r"^/comics/(?P<slug>[^/]+)/episodes$")
_POSITIVE_INTEGER = re.compile(r"^(?:0|[1-9][0-9]*)$")


@dataclass(frozen=True, slots=True)
class YanmagaWorkParts:
    slug: str


@dataclass(frozen=True, slots=True)
class YanmagaEpisodeParts:
    slug: str
    episode_id: str


@dataclass(frozen=True, slots=True)
class YanmagaListingRow:
    episode_id: str
    title: str
    url: str
    free_marker: bool
    red_marker_present: bool
    known_restricted: bool


@dataclass(frozen=True, slots=True)
class YanmagaContinuation:
    limit: int
    offset: int
    path: str


@dataclass(frozen=True, slots=True)
class YanmagaListingSnapshot:
    title: str
    anonymous: bool
    rows: tuple[YanmagaListingRow, ...]
    continuation: YanmagaContinuation | None


def _decoded_segment(value: str) -> str | None:
    if re.search(r"%(?![0-9a-fA-F]{2})", value):
        return None
    try:
        decoded = unquote_to_bytes(value).decode("utf-8", errors="strict")
    except (UnicodeDecodeError, ValueError):
        return None
    if (
        not decoded
        or decoded in {".", ".."}
        or "/" in decoded
        or "\\" in decoded
        or "\x00" in decoded
    ):
        return None
    return decoded


def _parse_yanmaga_url(url: str, pattern: re.Pattern[str]) -> re.Match[str] | None:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.lower() != "https"
        or (parsed.hostname or "").lower() != SITE_HOST
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path.endswith("/")
    ):
        return None
    return pattern.fullmatch(parsed.path)


def parse_yanmaga_work_url(url: str) -> YanmagaWorkParts | None:
    """Accept only an HTTPS Yanmaga work page with one encoded slug segment."""

    match = _parse_yanmaga_url(url, _WORK_PATH)
    slug = _decoded_segment(match.group("slug")) if match is not None else None
    return YanmagaWorkParts(slug) if slug is not None else None


def parse_yanmaga_episode_url(url: str) -> YanmagaEpisodeParts | None:
    """Parse the public episode route while preserving its work identity."""

    match = _parse_yanmaga_url(url, _EPISODE_PATH)
    if match is None:
        return None
    slug = _decoded_segment(match.group("slug"))
    episode_id = match.group("episode_id")
    if slug is None or _EPISODE_ID.fullmatch(episode_id) is None:
        return None
    return YanmagaEpisodeParts(slug, episode_id)


def classify_yanmaga_free_marker(
    *,
    marker_count: int,
    marker_visible: bool,
    marker_text: str | None,
    marker_class: str | None,
    marker_color: str | None,
    wait_marker: bool,
    modal_marker: bool,
    anonymous: bool,
    restricted_marker: bool = False,
) -> str:
    """Require the sampled red, non-wait row proof and anonymous page state."""

    if (
        marker_count == 1
        and marker_visible
        and marker_text == "無料"
        and marker_class == "mod-episode-point--free"
        and marker_color == FREE_COLOR
        and not wait_marker
        and not modal_marker
        and anonymous
        and not restricted_marker
    ):
        return "free"
    return "unknown"


def has_yanmaga_anonymous_proof(
    *,
    visible_sign_in_links: int,
    visible_sign_out_links: int,
    login_states: tuple[str, ...],
    current_work_document: bool,
    telemetry_overflow: bool = False,
) -> bool:
    """Require both the visible public sign-in affordance and explicit false telemetry."""

    return (
        visible_sign_in_links > 0
        and visible_sign_out_links == 0
        and current_work_document
        and not telemetry_overflow
        and bool(login_states)
        and all(state == "false" for state in login_states)
    )


class _LoginTelemetryObserver:
    """Read only the observed login-state field from first-party analytics requests."""

    _HOSTS = frozenset({"analytics.google.com", "www.google-analytics.com"})
    _KEY = "ep.is_logged_in"

    def __init__(self, expected_work: YanmagaWorkParts) -> None:
        self._expected_work = expected_work
        self._page: Page | None = None
        self.states: list[str] = []
        self.current_work_document = False
        self.overflow = False
        self._matching_event_count = 0
        self._request_listener = self._on_request
        self._navigation_listener = self._on_frame_navigated

    def attach(self, page: Page) -> None:
        self._page = page
        page.on("request", self._request_listener)
        page.on("framenavigated", self._navigation_listener)

    def _is_expected_work_url(self, url: str) -> bool:
        return parse_yanmaga_work_url(url) == self._expected_work

    def _on_frame_navigated(self, frame: object) -> None:
        page = self._page
        if page is None:
            return
        try:
            if frame != page.main_frame:
                return
            frame_url = frame.url
            page_url = page.url
        except (AttributeError, PlaywrightError):
            self.current_work_document = False
            self.states.clear()
            self.overflow = False
            self._matching_event_count = 0
            return
        self.states.clear()
        self.overflow = False
        self._matching_event_count = 0
        self.current_work_document = (
            self._is_expected_work_url(frame_url) and self._is_expected_work_url(page_url)
        )

    def _on_request(self, request: object) -> None:
        page = self._page
        if page is None:
            return
        try:
            parsed = urlsplit(request.url)
            frame = request.frame
            frame_url = frame.url
            page_url = page.url
        except (AttributeError, PlaywrightError, ValueError):
            return
        if (parsed.hostname or "").lower() not in self._HOSTS:
            return
        if (
            frame != page.main_frame
            or not self.current_work_document
            or not self._is_expected_work_url(frame_url)
            or not self._is_expected_work_url(page_url)
        ):
            return
        for field in parsed.query.split("&"):
            raw_key, separator, raw_value = field.partition("=")
            try:
                key = unquote_plus(raw_key, encoding="utf-8", errors="strict")
            except (UnicodeDecodeError, ValueError):
                continue
            if key != self._KEY:
                continue
            self._matching_event_count += 1
            if self._matching_event_count > MAX_LOGIN_TELEMETRY_EVENTS:
                self.overflow = True
                continue
            try:
                value = unquote_plus(raw_value if separator else "", encoding="utf-8", errors="strict")
            except (UnicodeDecodeError, ValueError):
                value = ""
            self.states.append(value if value in {"false", "true"} else "unknown")

    async def wait_for_state(self, page: Page) -> None:
        elapsed = 0
        quiet_elapsed = 0
        observed_count = len(self.states)
        while elapsed < LOGIN_TELEMETRY_TIMEOUT_MS:
            if self.overflow:
                return
            if any(state in {"false", "true"} for state in self.states):
                if len(self.states) == observed_count:
                    quiet_elapsed += STABILITY_POLL_MS
                    if quiet_elapsed >= LOGIN_TELEMETRY_QUIET_MS:
                        return
                else:
                    observed_count = len(self.states)
                    quiet_elapsed = 0
            await page.wait_for_timeout(STABILITY_POLL_MS)
            elapsed += STABILITY_POLL_MS

    def detach(self) -> None:
        if self._page is None:
            return
        try:
            self._page.remove_listener("request", self._request_listener)
            self._page.remove_listener("framenavigated", self._navigation_listener)
        except PlaywrightError:
            pass
        self._page = None


class YanmagaDiscoveryAdapter(DiscoveryAdapter):
    """Enumerate the complete currently served Yanmaga public listing."""

    supports_bounded_discovery = False
    allow_inferred_display_positions = False

    def __init__(self) -> None:
        self.last_snapshot: YanmagaListingSnapshot | None = None

    async def iter_records(
        self,
        page: Page,
        target: WatchlistTarget,
        mode: DiscoveryMode,
    ) -> AsyncIterator[DiscoveredRecord]:
        del mode  # DiscoveryService owns its shared latest-first known-streak rule.
        self.last_snapshot = None
        work = parse_yanmaga_work_url(target.url)
        if work is None:
            raise DiscoveryIncompleteError("Watchlist target must be a canonical Yanmaga work URL")
        if target.discovery_scope is not None:
            raise DiscoveryIncompleteError("Yanmaga does not support bounded Discovery")

        telemetry = _LoginTelemetryObserver(work)
        telemetry.attach(page)
        try:
            await page.goto(target.url, wait_until="domcontentloaded", timeout=WAIT_TIMEOUT_MS)
            await page.locator(f"{LIST_SELECTOR} {ROW_SELECTOR}").first.wait_for(
                state="visible", timeout=WAIT_TIMEOUT_MS
            )
            await telemetry.wait_for_state(page)
            snapshot = await self._wait_for_stable_snapshot(page, work, telemetry)
            expansions = 0
            while snapshot.continuation is not None:
                if expansions >= MAX_EXPANSIONS:
                    raise DiscoveryIncompleteError("Yanmaga listing exceeded the expansion bound")
                if len(snapshot.rows) >= MAX_ROWS:
                    raise DiscoveryIncompleteError("Yanmaga listing exceeded the row bound")
                continuation = snapshot.continuation
                if continuation.offset > len(snapshot.rows):
                    raise DiscoveryIncompleteError("Yanmaga continuation offset is out of range")

                await page.locator(MORE_SELECTOR).click(timeout=WAIT_TIMEOUT_MS)
                changed = await self._wait_for_snapshot_change(page, work, snapshot, telemetry)
                stable = await self._wait_for_stable_snapshot(page, work, telemetry)
                if stable != changed:
                    raise DiscoveryIncompleteError(
                        "Yanmaga listing changed again while the continuation settled"
                    )
                self._validate_expansion(snapshot, stable, continuation)
                snapshot = stable
                expansions += 1

            final_snapshot = await self._snapshot(page, work, telemetry)
            if final_snapshot != snapshot:
                raise DiscoveryIncompleteError(
                    "Yanmaga identity, access evidence or listing changed before emission"
                )
            self.last_snapshot = final_snapshot
            records = self._records_from_snapshot(snapshot, target, work)
            # DiscoveryService mutates Catalog as each item is yielded. All
            # paging, row identity, access evidence and stability checks have
            # completed before this point so a partial full run cannot reconcile.
        except DiscoveryIncompleteError:
            raise
        except (PlaywrightError, TimeoutError, ValueError, TypeError) as exc:
            raise DiscoveryIncompleteError("Yanmaga public episode listing did not validate") from exc
        finally:
            telemetry.detach()

        for record in records:
            yield record

    async def _wait_for_stable_snapshot(
        self,
        page: Page,
        work: YanmagaWorkParts,
        telemetry: _LoginTelemetryObserver,
    ) -> YanmagaListingSnapshot:
        elapsed = 0
        previous: YanmagaListingSnapshot | None = None
        stable_reads = 0
        while elapsed <= STABILITY_TIMEOUT_MS:
            current = await self._snapshot(page, work, telemetry)
            if current == previous:
                stable_reads += 1
                if stable_reads >= STABLE_READS_REQUIRED:
                    return current
            else:
                previous = current
                stable_reads = 0
            await page.wait_for_timeout(STABILITY_POLL_MS)
            elapsed += STABILITY_POLL_MS
        raise DiscoveryIncompleteError("Yanmaga episode listing did not stabilize")

    async def _wait_for_snapshot_change(
        self,
        page: Page,
        work: YanmagaWorkParts,
        before: YanmagaListingSnapshot,
        telemetry: _LoginTelemetryObserver,
    ) -> YanmagaListingSnapshot:
        elapsed = 0
        while elapsed <= WAIT_TIMEOUT_MS:
            current = await self._snapshot(page, work, telemetry)
            if current != before:
                return current
            await page.wait_for_timeout(STABILITY_POLL_MS)
            elapsed += STABILITY_POLL_MS
        raise DiscoveryIncompleteError("Yanmaga continuation did not change the listing")

    async def _snapshot(
        self,
        page: Page,
        work: YanmagaWorkParts,
        telemetry: _LoginTelemetryObserver,
    ) -> YanmagaListingSnapshot:
        identity = await page.evaluate(
            r"""() => {
              const visible = element => {
                if (!element || element.getClientRects().length === 0) return false;
                for (let node = element; node; node = node.parentElement) {
                  const style = getComputedStyle(node);
                  if (node.hidden || style.display === 'none' || style.visibility === 'hidden'
                      || style.visibility === 'collapse' || Number(style.opacity) === 0) return false;
                }
                return true;
              };
              const canonicals = [...document.querySelectorAll('link[rel="canonical"]')];
              const ogUrls = [...document.querySelectorAll('meta[property="og:url"]')];
              const signIns = [...document.querySelectorAll('a[href]')]
                .filter(a => new URL(a.href, location.href).pathname === '/customers/sign-up')
                .filter(a => /ログイン|会員登録|新規登録/.test(a.innerText || ''))
                .filter(visible);
              const signOuts = [...document.querySelectorAll('a[href],button')]
                .filter(element => {
                  const href = element instanceof HTMLAnchorElement ? element.href : '';
                  const path = href ? new URL(href, location.href).pathname : '';
                  return /(?:sign.?out|log.?out)/i.test(path) ||
                    /(?:sign.?out|log.?out)/i.test(element.className || '');
                }).filter(visible);
              const containers = [...document.querySelectorAll('.detailv2-episodes')];
              const container = containers.length === 1 ? containers[0] : null;
              const allRows = [...document.querySelectorAll('.mod-episode-item')];
              const rows = container ? [...container.querySelectorAll('.mod-episode-item')] : [];
              const rowSnapshot = rows.map((row, index) => {
                const anchors = [...row.querySelectorAll('a[href]')];
                const titleNodes = [...row.querySelectorAll('.mod-episode-title')];
                const markers = [...row.querySelectorAll('.mod-episode-point--free')];
                const marker = markers.length === 1 ? markers[0] : null;
                const href = anchors.length === 1 ? new URL(anchors[0].href, location.href) : null;
                return {
                  index,
                  tag: row.tagName,
                  visible: visible(row),
                  href: href?.href || null,
                  title: titleNodes.length === 1 ? (titleNodes[0].innerText || '').replace(/\s+/g, ' ').trim() : null,
                  markerCount: markers.length,
                  markerVisible: visible(marker),
                  markerText: marker ? (marker.innerText || '').trim() : null,
                  markerClass: marker ? marker.className : null,
                  markerColor: marker ? getComputedStyle(marker).color : null,
                  waitMarker: [...row.querySelectorAll('.by_wait')].length > 0,
                  modalMarker: row.classList.contains('js-modal') || row.querySelector('.js-modal') !== null,
                  restrictedMarker: [...row.querySelectorAll('*')].some(element => {
                    if (!visible(element) || element.matches('.mod-episode-point--free')) return false;
                    const text = (element.innerText || '').replace(/\s+/g, ' ').trim();
                    if (text === '\u521d\u56de\u7121\u6599') return true;
                    const pointBadge = element.classList.contains('mod-episode-point') ||
                      [...element.classList].some(name => name.startsWith('mod-episode-point--'));
                    return pointBadge && text === '\u7121\u6599';
                  }),
                  pointOnlyMarker: markers.length === 0 && [...row.querySelectorAll(
                    '.mod-episode-point,[class*="mod-episode-point--"]')]
                    .some(element => visible(element) && /^[0-9]+$/.test(
                      (element.innerText || '').replace(/\s+/g, ' ').trim())),
                };
              });
              const buttons = container ? [...container.querySelectorAll('button')]
                .filter(button => visible(button)) : [];
              const moreButtons = container ? [...container.querySelectorAll('.mod-episode-more-button')]
                .filter(button => visible(button)) : [];
              const semanticControls = container ? [...container.querySelectorAll(
                'button,[role="button"],a[rel="next"],input[type="button"],input[type="submit"]')]
                .filter(visible) : [];
              const unsupportedControls = semanticControls.filter(element =>
                !element.matches('.mod-episode-more-button'));
              const externalPagingControls = [...document.querySelectorAll('a[rel="next"],button[rel="next"]')]
                .filter(visible).filter(element => !container?.contains(element));
              const button = moreButtons.length === 1 ? moreButtons[0] : null;
              const continuation = button ? {
                text: (button.innerText || '').replace(/\s+/g, ' ').trim(),
                limit: button.getAttribute('data-limit'),
                offset: button.getAttribute('data-offset'),
                sort: button.getAttribute('data-sort'),
                path: button.getAttribute('data-path'),
              } : null;
              return {
                url: location.href,
                canonical: canonicals.length === 1 ? canonicals[0].href : null,
                ogUrl: ogUrls.length === 1 ? ogUrls[0].content : null,
                signIns: signIns.length,
                signOuts: signOuts.length,
                title: document.title,
                containerCount: containers.length,
                rowCount: rows.length,
                allRowCount: allRows.length,
                rows: rowSnapshot,
                buttonCount: buttons.length,
                moreCount: moreButtons.length,
                globalMoreCount: document.querySelectorAll('.mod-episode-more-button').length,
                unsupportedControlCount: unsupportedControls.length,
                externalPagingControlCount: externalPagingControls.length,
                continuation,
              };
            }"""
        )
        if not isinstance(identity, Mapping):
            raise DiscoveryIncompleteError("Yanmaga work identity is unavailable")
        self._validate_work_url(identity.get("url"), work)
        self._validate_work_url(identity.get("canonical"), work)
        self._validate_work_url(identity.get("ogUrl"), work)

        rows_value = identity.get("rows")
        if (
            identity.get("containerCount") != 1
            or identity.get("rowCount") != identity.get("allRowCount")
            or not isinstance(rows_value, list)
            or not rows_value
            or len(rows_value) > MAX_ROWS
        ):
            raise DiscoveryIncompleteError("Yanmaga episode list structure is incomplete")
        if (
            identity.get("buttonCount") != identity.get("moreCount")
            or identity.get("moreCount") != identity.get("globalMoreCount")
            or identity.get("unsupportedControlCount") != 0
            or identity.get("externalPagingControlCount") != 0
            or identity.get("moreCount") not in (0, 1)
        ):
            raise DiscoveryIncompleteError("Yanmaga episode list has unsupported controls")

        anonymous = has_yanmaga_anonymous_proof(
            visible_sign_in_links=identity.get("signIns", 0),
            visible_sign_out_links=identity.get("signOuts", 0),
            login_states=tuple(telemetry.states),
            current_work_document=telemetry.current_work_document,
            telemetry_overflow=telemetry.overflow,
        )
        rows: list[YanmagaListingRow] = []
        seen_ids: set[str] = set()
        for index, raw_row in enumerate(rows_value):
            if not isinstance(raw_row, Mapping) or raw_row.get("index") != index:
                raise DiscoveryIncompleteError("Yanmaga row order is invalid")
            if raw_row.get("tag") != "LI" or raw_row.get("visible") is not True:
                raise DiscoveryIncompleteError("Yanmaga episode row is hidden or malformed")
            href = raw_row.get("href")
            episode = parse_yanmaga_episode_url(href) if isinstance(href, str) else None
            if episode is None or episode.slug != work.slug:
                raise DiscoveryIncompleteError("Yanmaga episode URL does not match its work")
            if episode.episode_id in seen_ids:
                raise DiscoveryIncompleteError("Yanmaga listing contains a duplicate episode")
            seen_ids.add(episode.episode_id)
            title = " ".join(str(raw_row.get("title") or "").split())
            if not title:
                raise DiscoveryIncompleteError("Yanmaga episode title is unavailable")

            marker_class = raw_row.get("markerClass")
            marker_count = raw_row.get("markerCount", 0)
            marker_visible = raw_row.get("markerVisible") is True
            marker_text = raw_row.get("markerText") if isinstance(raw_row.get("markerText"), str) else None
            marker_color = raw_row.get("markerColor") if isinstance(raw_row.get("markerColor"), str) else None
            wait_marker = raw_row.get("waitMarker") is True
            modal_marker = raw_row.get("modalMarker") is True
            restricted_marker = raw_row.get("restrictedMarker") is True
            red_marker_present = (
                marker_count == 1
                and marker_visible
                and marker_text == "無料"
                and marker_class == "mod-episode-point--free"
                and marker_color == FREE_COLOR
            )
            free_marker = classify_yanmaga_free_marker(
                marker_count=marker_count,
                marker_visible=marker_visible,
                marker_text=marker_text,
                marker_class=marker_class if isinstance(marker_class, str) else None,
                marker_color=marker_color,
                wait_marker=wait_marker,
                modal_marker=modal_marker,
                anonymous=anonymous,
                restricted_marker=restricted_marker,
            ) == "free"
            point_only_marker = raw_row.get("pointOnlyMarker") is True
            rows.append(
                YanmagaListingRow(
                    episode_id=episode.episode_id,
                    title=title,
                    url=href,
                    free_marker=free_marker,
                    red_marker_present=red_marker_present,
                    known_restricted=anonymous
                    and not red_marker_present
                    and (wait_marker or modal_marker or restricted_marker or point_only_marker),
                )
            )

        continuation = self._parse_continuation(identity.get("continuation"), work)
        if identity.get("moreCount") == 0 and identity.get("continuation") is not None:
            raise DiscoveryIncompleteError("Yanmaga continuation state is ambiguous")
        if identity.get("moreCount") == 1 and continuation is None:
            raise DiscoveryIncompleteError("Yanmaga continuation attributes are invalid")
        return YanmagaListingSnapshot(
            title=" ".join(str(identity.get("title") or "").split()),
            anonymous=anonymous,
            rows=tuple(rows),
            continuation=continuation,
        )

    @staticmethod
    def _validate_work_url(value: object, expected: YanmagaWorkParts) -> None:
        if not isinstance(value, str):
            raise DiscoveryIncompleteError("Yanmaga canonical work URL is unavailable")
        parsed_work = parse_yanmaga_work_url(value)
        if parsed_work != expected:
            raise DiscoveryIncompleteError("Yanmaga redirected to a different work or route")

    @staticmethod
    def _parse_continuation(
        raw: object,
        work: YanmagaWorkParts,
    ) -> YanmagaContinuation | None:
        if raw is None:
            return None
        if not isinstance(raw, Mapping):
            raise DiscoveryIncompleteError("Yanmaga continuation control is malformed")
        try:
            limit_text = str(raw.get("limit"))
            offset_text = str(raw.get("offset"))
            limit = int(limit_text)
            offset = int(offset_text)
        except (TypeError, ValueError):
            raise DiscoveryIncompleteError("Yanmaga continuation range is invalid") from None
        expected_path = f"/comics/{_quote_slug(work.slug)}/episodes"
        path = raw.get("path")
        if (
            raw.get("text") != "もっと見る"
            or _POSITIVE_INTEGER.fullmatch(limit_text) is None
            or _POSITIVE_INTEGER.fullmatch(offset_text) is None
            or not 1 <= limit <= MAX_PAGE_SIZE
            or raw.get("sort") != "older"
            or not isinstance(path, str)
            or _normalize_path(path) != _normalize_path(expected_path)
        ):
            raise DiscoveryIncompleteError("Yanmaga continuation semantics are unsupported")
        return YanmagaContinuation(limit=limit, offset=offset, path=path)

    @staticmethod
    def _validate_expansion(
        before: YanmagaListingSnapshot,
        after: YanmagaListingSnapshot,
        continuation: YanmagaContinuation,
    ) -> None:
        before_ids = [row.episode_id for row in before.rows]
        after_ids = [row.episode_id for row in after.rows]
        before_set = set(before_ids)
        added = [episode_id for episode_id in after_ids if episode_id not in before_set]
        if (
            not added
            or len(added) > continuation.limit
            or len(after_ids) != len(before_ids) + len(added)
            or after_ids[: continuation.offset] != before_ids[: continuation.offset]
            or after_ids[continuation.offset : continuation.offset + len(added)] != added
            or after_ids[continuation.offset + len(added) :] != before_ids[continuation.offset :]
        ):
            raise DiscoveryIncompleteError("Yanmaga continuation did not preserve native row order")

    @staticmethod
    def _records_from_snapshot(
        snapshot: YanmagaListingSnapshot,
        target: WatchlistTarget,
        work: YanmagaWorkParts,
    ) -> list[DiscoveredRecord]:
        observed_at = datetime.now(UTC).isoformat()
        total = len(snapshot.rows)
        records: list[DiscoveredRecord] = []
        for index in reversed(range(total)):
            row = snapshot.rows[index]
            records.append(
                DiscoveredRecord(
                    item=DiscoveredItem(
                        canonical_title=target.label,
                        kind="episode",
                        order_key=None,
                        order_label=row.title,
                    ),
                    source=DiscoveredSource(
                        external_id=f"{work.slug}:{row.episode_id}",
                        url=row.url,
                        access_mode="free" if row.free_marker else "unknown",
                        free_until=None,
                        available=True,
                        access_checked_at=observed_at,
                        last_seen_at=observed_at,
                        global_display_position=index + 1,
                    ),
                )
            )
        return records


def _quote_slug(slug: str) -> str:
    return quote(slug, safe="")


def _normalize_path(path: str) -> str | None:
    parts = path.split("/")
    normalized = [_decoded_segment(part) if part else "" for part in parts]
    if any(value is None for value in normalized):
        return None
    return "/".join(value or "" for value in normalized)
