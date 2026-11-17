"""Conservative Discovery for YanmagaWeb's public episode listing."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qsl, quote, unquote_plus, unquote_to_bytes, urlsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from screenshot_crawler.discovery.base import DiscoveryAdapter
from screenshot_crawler.discovery.models import (
    DiscoveredItem,
    DiscoveredRecord,
    DiscoveredSource,
    DiscoveryMode,
    DiscoverySourceSnapshot,
)
from screenshot_crawler.discovery.service import DiscoveryIncompleteError
from screenshot_crawler.registration.models import UrlResolution, resolved_url
from screenshot_crawler.site_adapters.yanmaga.rental_history import (
    MAX_WAIT_RENTAL_COUNTDOWN_HOURS,
    RentalCountdown,
    fetch_rental_history_countdowns,
)
from screenshot_crawler.watchlist.models import WatchlistTarget

SITE_HOST = "yanmaga.jp"
LIST_SELECTOR = ".detailv2-episodes"
ROW_SELECTOR = ".mod-episode-item"
MORE_SELECTOR = ".mod-episode-more-button"
SORT_SELECTOR = "a.ga-sort.nav-link"
FREE_SELECTOR = ".mod-episode-point--free"
FREE_COLOR = "rgb(220, 0, 0)"
WAIT_SELECTOR = "span.mod-episode-free_browse"
WAIT_BADGE_CLASS = "mod-episode-free_browse"
# The observed badge is image-only: both innerText and textContent are empty.
WAIT_BADGE_TEXT = ""
WAIT_ASSET_PATH = "/assets/logo_free_browse-96b8e1d8.svg"
WAIT_TIMEOUT_MS = 15_000
STABILITY_TIMEOUT_MS = 5_000
STABILITY_POLL_MS = 100
STABLE_READS_REQUIRED = 2
MAX_EXPANSIONS = 100
MAX_ROWS = 5_000
# Native More without data-limit requests the site's 150-row default page.
MAX_PAGE_SIZE = 150
LOGIN_TELEMETRY_TIMEOUT_MS = 3_000
LOGIN_TELEMETRY_QUIET_MS = 300
MAX_LOGIN_TELEMETRY_EVENTS = 64
MAX_POPUP_DISMISSALS = 3

_EPISODE_ID = re.compile(r"^[0-9a-f]{32}$")
_WORK_PATH = re.compile(r"^/comics/(?P<slug>[^/]+)$")
_EPISODE_PATH = re.compile(r"^/comics/(?P<slug>[^/]+)/(?P<episode_id>[0-9a-f]{32})$")
_LIST_PATH = re.compile(r"^/comics/(?P<slug>[^/]+)/episodes$")
_POSITIVE_INTEGER = re.compile(r"^(?:0|[1-9][0-9]*)$")
_SORT_NEWEST_LABEL = "\u65b0\u7740\u9806"
_SORT_OLDEST_LABEL = "\u6700\u521d\u304b\u3089"


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
    first_free_marker: bool = False
    wait_free_marker: bool = False
    paid_marker: bool = False


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
    authenticated: bool = False
    mypage_href: str | None = None


def _has_future_catalog_grant(
    snapshot: DiscoverySourceSnapshot, now: datetime
) -> bool:
    value = snapshot.access_granted_until
    try:
        grant_until = datetime.fromisoformat(value) if isinstance(value, str) else value
    except ValueError:
        return False
    return (
        isinstance(grant_until, datetime)
        and grant_until.tzinfo is not None
        and grant_until.utcoffset() is not None
        and grant_until.astimezone(UTC) > now.astimezone(UTC)
    )


def _parse_composite_id(value: str) -> tuple[str, str] | None:
    match = re.fullmatch(r"(?P<slug>.+):(?P<episode>[0-9a-f]{32})", value)
    if match is None:
        return None
    slug = match.group("slug")
    if parse_yanmaga_work_url(
        f"https://{SITE_HOST}/comics/{quote(slug, safe='')}"
    ) != YanmagaWorkParts(slug):
        return None
    return slug, match.group("episode")


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


def _parse_yanmaga_sorted_work_url(url: str, expected: YanmagaWorkParts) -> bool:
    """Accept only the observed in-page oldest-first work URL shape."""

    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme.lower() == "https"
        and (parsed.hostname or "").lower() == SITE_HOST
        and port in (None, 443)
        and parsed.username is None
        and parsed.password is None
        and parsed.path == f"/comics/{quote(expected.slug, safe='')}"
        and parsed.query == "sort=older"
        and not parsed.fragment
    )


def _validate_work_document_url(
    value: object,
    expected: YanmagaWorkParts,
    *,
    allow_sorted_document: bool,
) -> None:
    if isinstance(value, str) and parse_yanmaga_work_url(value) == expected:
        return
    if (
        allow_sorted_document
        and isinstance(value, str)
        and _parse_yanmaga_sorted_work_url(value, expected)
    ):
        return
    raise DiscoveryIncompleteError("Yanmaga current document is not the expected work page")


def _validate_work_identity_urls(
    document_url: object,
    canonical_url: object,
    og_url: object,
    expected: YanmagaWorkParts,
    *,
    allow_sorted_identity: bool,
) -> None:
    """Validate one document's canonical pair without relaxing public inputs."""

    document_is_base = isinstance(document_url, str) and parse_yanmaga_work_url(document_url) == expected
    document_is_sorted = isinstance(document_url, str) and _parse_yanmaga_sorted_work_url(
        document_url, expected
    )
    if not document_is_base and not (allow_sorted_identity and document_is_sorted):
        raise DiscoveryIncompleteError("Yanmaga current document is not the expected work page")

    canonical_is_base = isinstance(canonical_url, str) and parse_yanmaga_work_url(canonical_url) == expected
    og_is_base = isinstance(og_url, str) and parse_yanmaga_work_url(og_url) == expected
    canonical_is_sorted = isinstance(canonical_url, str) and _parse_yanmaga_sorted_work_url(
        canonical_url, expected
    )
    og_is_sorted = isinstance(og_url, str) and _parse_yanmaga_sorted_work_url(og_url, expected)
    if canonical_is_base and og_is_base:
        return
    if (
        allow_sorted_identity
        and document_is_sorted
        and canonical_is_sorted
        and og_is_sorted
    ):
        return
    raise DiscoveryIncompleteError("Yanmaga redirected to a different work or route")


def _sort_link_value(value: object, expected: YanmagaWorkParts) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
        query = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return None
    if (
        parsed.scheme.lower() != "https"
        or (parsed.hostname or "").lower() != SITE_HOST
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != f"/comics/{quote(expected.slug, safe='')}"
        or parsed.fragment
        or parsed.query not in {"sort=newer", "sort=older"}
        or len(query) != 1
        or query[0][0] != "sort"
        or not query[0][1]
    ):
        return None
    return query[0][1]


def _css_attribute_string(value: object) -> str | None:
    if not isinstance(value, str) or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        return None
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


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
    authenticated: bool = False,
    first_free_marker: bool = False,
) -> str:
    """Require the sampled red, non-wait row proof and verified page state."""

    if (
        marker_count == 1
        and marker_visible
        and marker_text == "無料"
        and marker_class == "mod-episode-point--free"
        and marker_color == FREE_COLOR
        and not wait_marker
        and not modal_marker
        and (anonymous or authenticated)
        and not restricted_marker
        and not first_free_marker
    ):
        return "free"
    return "unknown"


def classify_yanmaga_first_free_marker(
    *,
    marker_count: int,
    first_free_count: int,
    marker_visible: bool,
    marker_text: str | None,
    marker_classes: tuple[str, ...],
    wait_marker: bool,
    modal_marker: bool,
    authenticated: bool,
    red_marker_present: bool = False,
    conflicting_free_badge: bool = False,
) -> str:
    """Classify only the observed exact first-free badge on an authenticated row."""

    if (
        marker_count == 1
        and first_free_count == 1
        and marker_visible
        and marker_text == "初回無料"
        and set(marker_classes) == {"mod-episode-point--free", "by_first_time"}
        and not wait_marker
        and not modal_marker
        and authenticated
        and not red_marker_present
        and not conflicting_free_badge
    ):
        return "free"
    return "unknown"


def classify_yanmaga_wait_marker(
    *,
    marker_count: int,
    free_marker_count: int,
    marker_visible: bool,
    marker_classes: tuple[str, ...],
    marker_text: str | None,
    image_count: int,
    image_visible: bool,
    image_url: str | None,
    data_is_free: str | None,
    anchor_url: str | None,
    original_url: str | None,
    authenticated: bool,
    modal_marker: bool,
    restricted_marker: bool,
    red_marker_present: bool,
    first_free_count: int,
) -> str:
    """Classify only the authenticated, exact wait badge seen in the listing."""

    if (
        marker_count != 1
        or free_marker_count != 0
        or not marker_visible
        or marker_classes != (WAIT_BADGE_CLASS,)
        or marker_text != WAIT_BADGE_TEXT
        or image_count != 1
        or not image_visible
        or not _is_yanmaga_wait_asset(image_url)
        or data_is_free != "true"
        or not _same_yanmaga_episode(anchor_url, original_url)
        or not authenticated
        or modal_marker
        or restricted_marker
        or red_marker_present
        or first_free_count != 0
    ):
        return "unknown"
    return "quota"


def _same_yanmaga_episode(anchor_url: str | None, original_url: str | None) -> bool:
    if not isinstance(anchor_url, str) or not isinstance(original_url, str):
        return False
    anchor = parse_yanmaga_episode_url(anchor_url)
    original = parse_yanmaga_episode_url(original_url)
    return anchor is not None and anchor == original


def _is_yanmaga_wait_asset(value: str | None) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme.lower() == "https"
        and (parsed.hostname or "").lower() == SITE_HOST
        and port in (None, 443)
        and parsed.username is None
        and parsed.password is None
        and parsed.path == WAIT_ASSET_PATH
        and not parsed.query
        and not parsed.fragment
    )


def has_yanmaga_anonymous_proof(
    *,
    visible_sign_in_links: int,
    visible_sign_out_links: int,
    login_states: tuple[str, ...],
    current_work_document: bool,
    telemetry_overflow: bool = False,
    visible_mypage_links: int = 0,
) -> bool:
    """Require both the visible public sign-in affordance and explicit false telemetry."""

    return (
        visible_sign_in_links > 0
        and visible_sign_out_links == 0
        and visible_mypage_links == 0
        and current_work_document
        and not telemetry_overflow
        and bool(login_states)
        and all(state == "false" for state in login_states)
    )


def has_yanmaga_authenticated_proof(
    *,
    visible_sign_in_links: int,
    visible_mypage_links: int,
    login_states: tuple[str, ...],
    current_work_document: bool,
    telemetry_overflow: bool = False,
) -> bool:
    """Use the observed account-only My Page link as positive UI evidence.

    Analytics is supporting evidence only: it may be absent, but any observed
    value must agree with the authenticated page state.
    """

    return (
        visible_mypage_links > 0
        and visible_sign_in_links == 0
        and current_work_document
        and not telemetry_overflow
        and (not login_states or all(state == "true" for state in login_states))
    )


class _LoginTelemetryObserver:
    """Read only the observed login-state field from first-party analytics requests."""

    _HOSTS = frozenset({"analytics.google.com", "www.google-analytics.com"})
    _KEY = "ep.is_logged_in"

    def __init__(self, expected_work: YanmagaWorkParts) -> None:
        self._expected_work = expected_work
        self._sort_ui_mode: str | None = None
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
        return (
            parse_yanmaga_work_url(url) == self._expected_work
            or (
                self.sorted_work_document_allowed
                and _parse_yanmaga_sorted_work_url(url, self._expected_work)
            )
        )

    def allow_sorted_work_document(self) -> None:
        """Allow only the one observed in-page sort navigation shape."""

        self._sort_ui_mode = "oldest"

    def require_absent_sort_controls(self) -> None:
        self._sort_ui_mode = "absent"

    @property
    def sorted_work_document_allowed(self) -> bool:
        return self._sort_ui_mode == "oldest"

    @property
    def sort_ui_mode(self) -> str | None:
        return self._sort_ui_mode

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

    registration_hosts = (SITE_HOST,)
    supports_bounded_discovery = False
    allow_inferred_display_positions = False

    def resolve_registration_url(self, url: str) -> UrlResolution:
        work = parse_yanmaga_work_url(url)
        if work is None:
            return UrlResolution(
                input_url=url,
                blockers=("ヤンマガWebは https://yanmaga.jp/comics/作品名 の作品URLを指定してください",),
            )
        return resolved_url(
            url, f"https://{SITE_HOST}/comics/{work.slug}", f"yanmaga-work:{work.slug}"
        )

    def __init__(self) -> None:
        self.last_snapshot: YanmagaListingSnapshot | None = None
        self._grant_candidates: dict[str, DiscoverySourceSnapshot] = {}
        self._source_snapshots: dict[str, DiscoverySourceSnapshot] = {}
        self._fresh_active_grants: set[str] = set()
        self._fresh_history_grants: dict[str, datetime] = {}
        self._grant_work_slug: str | None = None

    def configure_source_snapshots(
        self,
        target: WatchlistTarget,
        snapshots: tuple[DiscoverySourceSnapshot, ...],
    ) -> None:
        self._grant_candidates = {}
        self._source_snapshots = {}
        self._fresh_active_grants = set()
        self._fresh_history_grants = {}
        work = parse_yanmaga_work_url(target.url)
        self._grant_work_slug = work.slug if work is not None else None
        if target.site != "yanmaga" or work is None:
            return
        now = datetime.now(UTC)
        for snapshot in snapshots:
            parsed_id = _parse_composite_id(snapshot.external_id)
            if (
                snapshot.discovery_key != target.key
                or parsed_id is None
                or parsed_id[0] != work.slug
            ):
                continue
            self._source_snapshots[snapshot.external_id] = snapshot
            if (
                snapshot.access_mode in {"free", "quota", "paid"}
                and _has_future_catalog_grant(snapshot, now)
            ):
                self._grant_candidates[snapshot.external_id] = snapshot

    def reconcile_access_mode(
        self,
        observed_access_mode: str,
        previous: DiscoverySourceSnapshot | None,
        target: WatchlistTarget,
    ) -> str:
        if observed_access_mode != "unknown" or previous is None:
            return observed_access_mode
        previous_parts = _parse_composite_id(previous.external_id)
        if (
            target.site != "yanmaga"
            or self._grant_work_slug is None
            or previous_parts is None
            or previous_parts[0] != self._grant_work_slug
            or previous.discovery_key != target.key
            or previous.access_mode not in {"free", "quota", "paid"}
            or not _has_future_catalog_grant(previous, datetime.now(UTC))
            or previous.external_id not in self._grant_candidates
            or previous.external_id not in self._fresh_active_grants
        ):
            return observed_access_mode
        return previous.access_mode

    async def iter_records(
        self,
        page: Page,
        target: WatchlistTarget,
        mode: DiscoveryMode,
    ) -> AsyncIterator[DiscoveredRecord]:
        del mode  # DiscoveryService owns its shared latest-first known-streak rule.
        self.last_snapshot = None
        self._fresh_active_grants = set()
        self._fresh_history_grants = {}
        work = parse_yanmaga_work_url(target.url)
        if work is None:
            raise DiscoveryIncompleteError("Watchlist target must be a canonical Yanmaga work URL")
        if target.discovery_scope is not None:
            raise DiscoveryIncompleteError("Yanmaga does not support bounded Discovery")

        telemetry = _LoginTelemetryObserver(work)
        telemetry.attach(page)
        # The site's popup uses a separate open state and close controls from
        # registration/rental modals. A handler also catches a popup appearing
        # while Playwright is waiting to click Sort or More.
        popup = page.locator("body.is-open-popup:has(.js-popup-close:visible)")
        popup_dismissals = 0
        popup_error: Exception | None = None

        async def dismiss_popup() -> None:
            nonlocal popup_dismissals
            if popup_dismissals >= MAX_POPUP_DISMISSALS:
                raise DiscoveryIncompleteError("Yanmaga promotional popup repeatedly reappeared")
            if not (
                parse_yanmaga_work_url(page.url) == work
                or _parse_yanmaga_sorted_work_url(page.url, work)
            ):
                raise DiscoveryIncompleteError("Yanmaga popup is outside the expected work")
            # The backdrop may share js-popup-close. Select the innermost
            # visible close control, never the backdrop or a promotional link.
            close = page.locator(
                "body.is-open-popup .js-popup-close:not(:has(.js-popup-close)):visible"
            )
            if await close.count() != 1:
                raise DiscoveryIncompleteError("Yanmaga popup close control is ambiguous")
            popup_dismissals += 1
            before_url = page.url
            close_timeout = min(2_000, WAIT_TIMEOUT_MS // 2)
            await close.click(timeout=close_timeout)
            await popup.wait_for(state="hidden", timeout=close_timeout)
            if page.url != before_url:
                raise DiscoveryIncompleteError("Yanmaga popup close navigated away from the work")

        async def handle_popup() -> None:
            nonlocal popup_error
            if popup_error is not None or not await popup.is_visible():
                return
            try:
                await dismiss_popup()
            except (DiscoveryIncompleteError, PlaywrightError, TimeoutError) as exc:
                # Locator callbacks run in an event task. Propagate their failure
                # through Discovery instead of leaking it into the next Page API.
                popup_error = exc

        async def clear_popup() -> None:
            await handle_popup()
            if popup_error is not None:
                raise DiscoveryIncompleteError("Yanmaga promotional popup did not close") from popup_error

        popup_handler_installed = False
        try:
            await page.add_locator_handler(popup, handle_popup, no_wait_after=True)
            popup_handler_installed = True
            await page.goto(target.url, wait_until="domcontentloaded", timeout=WAIT_TIMEOUT_MS)
            await page.locator(f"{LIST_SELECTOR} {ROW_SELECTOR}").first.wait_for(
                state="visible", timeout=WAIT_TIMEOUT_MS
            )
            await telemetry.wait_for_state(page)
            await clear_popup()
            sort_selected = await self._select_oldest_sort(page, work, telemetry)
            if sort_selected:
                await page.locator(f"{LIST_SELECTOR} {ROW_SELECTOR}").first.wait_for(
                    state="visible", timeout=WAIT_TIMEOUT_MS
                )
                await telemetry.wait_for_state(page)
                await clear_popup()
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

            await clear_popup()
            final_snapshot = await self._snapshot(page, work, telemetry)
            if final_snapshot != snapshot:
                raise DiscoveryIncompleteError(
                    "Yanmaga identity, access evidence or listing changed before emission"
                )
            history_targets = self._history_targets(
                final_snapshot, work, self._grant_candidates
            )
            if history_targets and final_snapshot.authenticated and final_snapshot.mypage_href:
                fresh = await fetch_rental_history_countdowns(
                    page,
                    observed_mypage_href=final_snapshot.mypage_href,
                    targets=history_targets,
                    max_countdown_hours=MAX_WAIT_RENTAL_COUNTDOWN_HOURS,
                )
                self._apply_history_countdowns(final_snapshot, work, fresh)
                post_history_snapshot = await self._snapshot(page, work, telemetry)
                if post_history_snapshot != final_snapshot:
                    raise DiscoveryIncompleteError(
                        "Yanmaga identity, access evidence or listing changed during grant verification"
                    )
                final_snapshot = post_history_snapshot
            if popup_error is not None:
                raise DiscoveryIncompleteError("Yanmaga promotional popup did not close") from popup_error
            self.last_snapshot = final_snapshot
            records = self._records_from_snapshot(
                final_snapshot, target, work, self._fresh_history_grants
            )
            # DiscoveryService mutates Catalog as each item is yielded. All
            # paging, row identity, access evidence and stability checks have
            # completed before this point so a partial full run cannot reconcile.
        except DiscoveryIncompleteError:
            raise
        except (PlaywrightError, TimeoutError, ValueError, TypeError) as exc:
            if popup_error is not None:
                raise DiscoveryIncompleteError("Yanmaga promotional popup did not close") from popup_error
            raise DiscoveryIncompleteError("Yanmaga public episode listing did not validate") from exc
        finally:
            telemetry.detach()
            if popup_handler_installed:
                await page.remove_locator_handler(popup)

        for record in records:
            yield record

    async def _select_oldest_sort(
        self,
        page: Page,
        work: YanmagaWorkParts,
        telemetry: _LoginTelemetryObserver,
    ) -> bool:
        state = await self._sort_control_state(page)
        controls = state.get("controls")
        if not isinstance(controls, list):
            raise DiscoveryIncompleteError("Yanmaga sort controls are malformed")
        if not controls:
            _validate_work_identity_urls(
                state.get("url"),
                state.get("canonical"),
                state.get("ogUrl"),
                work,
                allow_sorted_identity=False,
            )
            telemetry.require_absent_sort_controls()
            return False
        active_labels = [
            control.get("text")
            for control in controls
            if isinstance(control, Mapping)
            and isinstance(control.get("classes"), list)
            and "active" in control["classes"]
        ]
        if len(active_labels) != 1 or active_labels[0] not in {
            _SORT_NEWEST_LABEL,
            _SORT_OLDEST_LABEL,
        }:
            raise DiscoveryIncompleteError("Yanmaga sort selected state is ambiguous")
        active_label = active_labels[0]
        oldest_index = self._validate_sort_controls(
            controls,
            work,
            expected_active_label=active_label,
        )
        _validate_work_identity_urls(
            state.get("url"),
            state.get("canonical"),
            state.get("ogUrl"),
            work,
            allow_sorted_identity=(
                active_label == _SORT_OLDEST_LABEL
                and _parse_yanmaga_sorted_work_url(state.get("url", ""), work)
            ),
        )
        if active_label == _SORT_OLDEST_LABEL:
            telemetry.allow_sorted_work_document()
            return True

        observed_oldest = controls[oldest_index]
        if not isinstance(observed_oldest, Mapping):
            raise DiscoveryIncompleteError("Yanmaga oldest-first sort control is malformed")
        raw_href = observed_oldest.get("hrefAttribute")
        href_selector = _css_attribute_string(raw_href)
        observed_href = observed_oldest.get("href")
        if href_selector is None or not isinstance(observed_href, str):
            raise DiscoveryIncompleteError("Yanmaga oldest-first href is unavailable")
        href_locator = page.locator(f"{SORT_SELECTOR}[href={href_selector}]")
        locator = href_locator.and_(
            page.get_by_role("link", name=_SORT_OLDEST_LABEL, exact=True)
        )
        if await locator.count() != 1:
            raise DiscoveryIncompleteError(
                "Yanmaga oldest-first control changed before selection"
            )
        final_control = await locator.evaluate(
            r"""element => {
              const style = getComputedStyle(element);
              const rect = element.getBoundingClientRect();
              return {
                tag: element.tagName,
                visible: element.getClientRects().length > 0
                  && !element.hidden && style.display !== 'none'
                  && style.visibility !== 'hidden' && style.visibility !== 'collapse'
                  && Number(style.opacity) !== 0 && rect.width > 0 && rect.height > 0,
                text: (element.innerText || '').replace(/\s+/g, ' ').trim(),
                classes: [...element.classList],
                href: element.href,
                hrefAttribute: element.getAttribute('href'),
                ariaCurrent: element.getAttribute('aria-current'),
                ariaPressed: element.getAttribute('aria-pressed'),
                ariaSelected: element.getAttribute('aria-selected')
              };
            }"""
        )
        if (
            not isinstance(final_control, Mapping)
            or final_control.get("tag") != "A"
            or final_control.get("visible") is not True
            or final_control.get("text") != _SORT_OLDEST_LABEL
            or set(final_control.get("classes", [])) != {"ga-sort", "nav-link"}
            or _sort_link_value(final_control.get("href"), work) != "older"
            or final_control.get("href") != observed_href
            or final_control.get("hrefAttribute") != raw_href
            or final_control.get("ariaCurrent") is not None
            or final_control.get("ariaPressed") is not None
            or final_control.get("ariaSelected") is not None
        ):
            raise DiscoveryIncompleteError("Yanmaga oldest-first sort changed before selection")

        fresh_state = await self._sort_control_state(page)
        fresh_controls = fresh_state.get("controls")
        if not isinstance(fresh_controls, list):
            raise DiscoveryIncompleteError("Yanmaga sort controls changed before selection")
        fresh_oldest_index = self._validate_sort_controls(
            fresh_controls,
            work,
            expected_active_label=_SORT_NEWEST_LABEL,
        )
        fresh_oldest = fresh_controls[fresh_oldest_index]
        if (
            not isinstance(fresh_oldest, Mapping)
            or fresh_oldest.get("href") != observed_href
            or fresh_oldest.get("hrefAttribute") != raw_href
        ):
            raise DiscoveryIncompleteError("Yanmaga oldest-first href changed before selection")
        _validate_work_identity_urls(
            fresh_state.get("url"),
            fresh_state.get("canonical"),
            fresh_state.get("ogUrl"),
            work,
            allow_sorted_identity=False,
        )
        if await locator.count() != 1:
            raise DiscoveryIncompleteError("Yanmaga oldest-first locator changed before selection")
        telemetry.allow_sorted_work_document()
        try:
            async with page.expect_navigation(
                wait_until="domcontentloaded", timeout=WAIT_TIMEOUT_MS
            ):
                await locator.click(timeout=WAIT_TIMEOUT_MS)
        except (PlaywrightError, TimeoutError) as exc:
            raise DiscoveryIncompleteError(
                "Yanmaga oldest-first sort navigation did not complete"
            ) from exc

        if not _parse_yanmaga_sorted_work_url(page.url, work):
            raise DiscoveryIncompleteError("Yanmaga sort did not open the observed oldest-first URL")
        sorted_state = await self._sort_control_state(page)
        sorted_controls = sorted_state.get("controls")
        if not isinstance(sorted_controls, list):
            raise DiscoveryIncompleteError("Yanmaga sorted controls are malformed")
        self._validate_sort_controls(
            sorted_controls,
            work,
            expected_active_label=_SORT_OLDEST_LABEL,
        )
        _validate_work_identity_urls(
            sorted_state.get("url"),
            sorted_state.get("canonical"),
            sorted_state.get("ogUrl"),
            work,
            allow_sorted_identity=True,
        )
        return True

    async def _sort_control_state(self, page: Page) -> Mapping[str, object]:
        state = await page.evaluate(
            r"""() => {
              const visible = element => {
                if (!element || element.getClientRects().length === 0) return false;
                for (let node = element; node; node = node.parentElement) {
                  const style = getComputedStyle(node);
                  if (node.hidden || style.display === 'none' || style.visibility === 'hidden'
                      || style.visibility === 'collapse' || Number(style.opacity) === 0) return false;
                }
                const rect = element.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
              };
              const canonical = [...document.querySelectorAll('link[rel="canonical"]')];
              const ogUrls = [...document.querySelectorAll('meta[property="og:url"]')];
              const controls = [...document.querySelectorAll('a.ga-sort.nav-link')].map((element, index) => ({
                index,
                tag: element.tagName,
                visible: visible(element),
                text: (element.innerText || '').replace(/\s+/g, ' ').trim(),
                classes: [...element.classList],
                href: element.href,
                hrefAttribute: element.getAttribute('href'),
                ariaCurrent: element.getAttribute('aria-current'),
                ariaPressed: element.getAttribute('aria-pressed'),
                ariaSelected: element.getAttribute('aria-selected')
              }));
              return {
                url: location.href,
                canonical: canonical.length === 1 ? canonical[0].href : null,
                ogUrl: ogUrls.length === 1 ? ogUrls[0].content : null,
                controls
              };
            }"""
        )
        if not isinstance(state, Mapping):
            raise DiscoveryIncompleteError("Yanmaga work sort state is unavailable")
        return state

    @staticmethod
    def _validate_sort_controls(
        controls: list[object],
        work: YanmagaWorkParts,
        *,
        expected_active_label: str,
    ) -> int:
        if len(controls) != 2:
            raise DiscoveryIncompleteError("Yanmaga sort controls are duplicated or incomplete")
        normalized: dict[str, tuple[int, Mapping[str, object], str | None]] = {}
        for index, control in enumerate(controls):
            if not isinstance(control, Mapping):
                raise DiscoveryIncompleteError("Yanmaga sort control is malformed")
            label = control.get("text")
            classes = control.get("classes")
            if (
                control.get("index") != index
                or control.get("tag") != "A"
                or control.get("visible") is not True
                or not isinstance(label, str)
                or label not in {_SORT_NEWEST_LABEL, _SORT_OLDEST_LABEL}
                or not isinstance(classes, list)
                or set(classes) - {"ga-sort", "nav-link", "active"}
                or not {"ga-sort", "nav-link"}.issubset(set(classes))
                or label in normalized
            ):
                raise DiscoveryIncompleteError("Yanmaga sort UI is unknown or contradictory")
            sort_value = _sort_link_value(control.get("href"), work)
            if sort_value is None:
                raise DiscoveryIncompleteError("Yanmaga sort link is not bound to this work")
            active = "active" in classes
            expected_active = label == expected_active_label
            if active is not expected_active:
                raise DiscoveryIncompleteError("Yanmaga sort label conflicts with selected state")
            if label == _SORT_OLDEST_LABEL and sort_value != "older":
                raise DiscoveryIncompleteError("Yanmaga oldest-first link has an unknown sort query")
            if label == _SORT_NEWEST_LABEL and sort_value != "newer":
                raise DiscoveryIncompleteError("Yanmaga newest link has an unknown sort query")
            for aria_name in ("ariaCurrent", "ariaPressed", "ariaSelected"):
                aria_value = control.get(aria_name)
                if aria_value is not None:
                    raise DiscoveryIncompleteError("Yanmaga sort UI has an unobserved selected-state attribute")
            normalized[label] = (index, control, sort_value)
        if set(normalized) != {_SORT_NEWEST_LABEL, _SORT_OLDEST_LABEL}:
            raise DiscoveryIncompleteError("Yanmaga sort labels are incomplete")
        return normalized[_SORT_OLDEST_LABEL][0]

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
              const myPages = [...document.querySelectorAll('a[href]')]
                .filter(anchor => {
                  const href = new URL(anchor.href, location.href);
                  return href.origin === location.origin
                    && href.pathname === '/mypage'
                    && href.username === ''
                    && href.password === ''
                    && href.search === ''
                    && href.hash === '';
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
                const firstFreeMarkers = markers.filter(element =>
                  element.classList.contains('by_first_time'));
                const firstFreeMarker = firstFreeMarkers.length === 1
                  ? firstFreeMarkers[0] : null;
                const waitBadges = [...row.querySelectorAll('span.mod-episode-free_browse')];
                const waitBadge = waitBadges.length === 1 ? waitBadges[0] : null;
                const waitImages = waitBadge ? [...waitBadge.querySelectorAll('img')] : [];
                const waitImage = waitImages.length === 1 ? waitImages[0] : null;
                const href = anchors.length === 1 ? new URL(anchors[0].href, location.href) : null;
                const pointBadges = [...row.querySelectorAll(
                  '.mod-episode-point,[class*="mod-episode-point--"]')];
                // The native icon wrapper repeats its child price's text.
                const priceBadges = pointBadges.filter(element =>
                  !pointBadges.some(other => other !== element && element.contains(other)));
                const price = priceBadges.length === 1 ? priceBadges[0] : null;
                const paidPointMarker = visible(price)
                  && ['mod-episode-point', 'mod-episode-point--normal'].includes(price.className)
                  && /^[1-9][0-9]*$/.test((price.innerText || '').trim());
                let originalURL = null;
                try {
                  const rawOriginal = row.getAttribute('data-original-url');
                  originalURL = rawOriginal ? new URL(rawOriginal, location.href).href : null;
                } catch (_) {}
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
                  firstFreeCount: firstFreeMarkers.length,
                  firstFreeVisible: visible(firstFreeMarker),
                  firstFreeText: firstFreeMarker ? (firstFreeMarker.innerText || '').trim() : null,
                  firstFreeClasses: firstFreeMarker ? [...firstFreeMarker.classList] : [],
                  waitBadgeCount: waitBadges.length,
                  waitBadgeVisible: visible(waitBadge),
                  waitBadgeText: waitBadge ? (waitBadge.innerText || '').replace(/\s+/g, ' ').trim() : null,
                  waitBadgeClasses: waitBadge ? [...waitBadge.classList] : [],
                  waitImageCount: waitImages.length,
                  waitImageVisible: visible(waitImage),
                  waitImageUrl: waitImage ? waitImage.src : null,
                  dataIsFree: row.getAttribute('data-is-free'),
                  paidPointMarker,
                  originalUrl: originalURL,
                  anchorUrl: href?.href || null,
                  conflictingFreeBadge: [...row.querySelectorAll(
                    '.mod-episode-point,[class*="mod-episode-point--"]')].some(element => {
                      if (!visible(element) || element === marker || element === firstFreeMarker) return false;
                      return (element.innerText || '').replace(/\s+/g, ' ').trim() === '\u7121\u6599';
                    }),
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
              const sortControls = [...document.querySelectorAll('a.ga-sort.nav-link')].map((element, index) => ({
                index,
                tag: element.tagName,
                visible: visible(element),
                text: (element.innerText || '').replace(/\s+/g, ' ').trim(),
                classes: [...element.classList],
                href: element.href,
                ariaCurrent: element.getAttribute('aria-current'),
                ariaPressed: element.getAttribute('aria-pressed'),
                ariaSelected: element.getAttribute('aria-selected')
              }));
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
                myPages: myPages.length,
                myPageHrefs: myPages.map(anchor => anchor.href),
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
                sortControls,
                continuation,
              };
            }"""
        )
        if not isinstance(identity, Mapping):
            raise DiscoveryIncompleteError("Yanmaga work identity is unavailable")
        _validate_work_document_url(
            identity.get("url"),
            work,
            allow_sorted_document=telemetry.sorted_work_document_allowed,
        )
        sort_controls = identity.get("sortControls")
        if not isinstance(sort_controls, list):
            raise DiscoveryIncompleteError("Yanmaga sort state is unavailable")
        if telemetry.sort_ui_mode == "oldest":
            self._validate_sort_controls(
                sort_controls,
                work,
                expected_active_label=_SORT_OLDEST_LABEL,
            )
        elif telemetry.sort_ui_mode == "absent" and sort_controls:
            raise DiscoveryIncompleteError("Yanmaga sort controls appeared after initial inspection")
        elif telemetry.sort_ui_mode is None:
            raise DiscoveryIncompleteError("Yanmaga sort controls were not initialized")
        _validate_work_identity_urls(
            identity.get("url"),
            identity.get("canonical"),
            identity.get("ogUrl"),
            work,
            allow_sorted_identity=(
                telemetry.sort_ui_mode == "oldest"
                and isinstance(identity.get("url"), str)
                and _parse_yanmaga_sorted_work_url(identity["url"], work)
            ),
        )

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
            visible_mypage_links=identity.get("myPages", 0),
        )
        authenticated = has_yanmaga_authenticated_proof(
            visible_sign_in_links=identity.get("signIns", 0),
            visible_mypage_links=identity.get("myPages", 0),
            login_states=tuple(telemetry.states),
            current_work_document=telemetry.current_work_document,
            telemetry_overflow=telemetry.overflow,
        )
        mypage_hrefs = identity.get("myPageHrefs")
        mypage_href: str | None = None
        if authenticated and isinstance(mypage_hrefs, list):
            exact_hrefs = {value for value in mypage_hrefs if isinstance(value, str)}
            if len(exact_hrefs) == 1:
                candidate_href = next(iter(exact_hrefs))
                try:
                    parsed_href = urlsplit(candidate_href)
                    if (
                        parsed_href.scheme == "https"
                        and (parsed_href.hostname or "").lower() == SITE_HOST
                        and parsed_href.port in (None, 443)
                        and parsed_href.path == "/mypage"
                        and not parsed_href.username
                        and not parsed_href.password
                        and not parsed_href.query
                        and not parsed_href.fragment
                    ):
                        mypage_href = candidate_href
                except ValueError:
                    mypage_href = None
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
            wait_badge_count = raw_row.get("waitBadgeCount", 0)
            wait_marker = raw_row.get("waitMarker") is True or (
                isinstance(wait_badge_count, int) and wait_badge_count > 0
            )
            modal_marker = raw_row.get("modalMarker") is True
            restricted_marker = raw_row.get("restrictedMarker") is True
            conflicting_free_badge = raw_row.get("conflictingFreeBadge") is True
            first_free_count = raw_row.get("firstFreeCount", 0)
            red_marker_present = (
                marker_count == 1
                and marker_visible
                and marker_text == "無料"
                and marker_class == "mod-episode-point--free"
                and marker_color == FREE_COLOR
            )
            wait_free_marker = classify_yanmaga_wait_marker(
                marker_count=wait_badge_count,
                free_marker_count=marker_count,
                marker_visible=raw_row.get("waitBadgeVisible") is True,
                marker_classes=tuple(
                    class_name
                    for class_name in raw_row.get("waitBadgeClasses", [])
                    if isinstance(class_name, str)
                ),
                marker_text=(
                    raw_row.get("waitBadgeText")
                    if isinstance(raw_row.get("waitBadgeText"), str)
                    else None
                ),
                image_count=raw_row.get("waitImageCount", 0),
                image_visible=raw_row.get("waitImageVisible") is True,
                image_url=(
                    raw_row.get("waitImageUrl")
                    if isinstance(raw_row.get("waitImageUrl"), str)
                    else None
                ),
                data_is_free=(
                    raw_row.get("dataIsFree")
                    if isinstance(raw_row.get("dataIsFree"), str)
                    else None
                ),
                anchor_url=raw_row.get("anchorUrl")
                if isinstance(raw_row.get("anchorUrl"), str)
                else None,
                original_url=raw_row.get("originalUrl")
                if isinstance(raw_row.get("originalUrl"), str)
                else None,
                authenticated=authenticated,
                modal_marker=modal_marker,
                restricted_marker=restricted_marker or conflicting_free_badge,
                red_marker_present=red_marker_present,
                first_free_count=first_free_count,
            ) == "quota"
            first_free_marker = classify_yanmaga_first_free_marker(
                marker_count=marker_count,
                first_free_count=first_free_count,
                marker_visible=raw_row.get("firstFreeVisible") is True,
                marker_text=(
                    raw_row.get("firstFreeText")
                    if isinstance(raw_row.get("firstFreeText"), str)
                    else None
                ),
                marker_classes=tuple(
                    class_name
                    for class_name in raw_row.get("firstFreeClasses", [])
                    if isinstance(class_name, str)
                ),
                wait_marker=wait_marker,
                modal_marker=modal_marker,
                authenticated=authenticated,
                red_marker_present=red_marker_present,
                conflicting_free_badge=conflicting_free_badge,
            ) == "free"
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
                authenticated=authenticated,
                first_free_marker=first_free_count > 0,
            ) == "free"
            point_only_marker = raw_row.get("pointOnlyMarker") is True
            rows.append(
                YanmagaListingRow(
                    episode_id=episode.episode_id,
                    title=title,
                    url=href,
                    free_marker=free_marker,
                    first_free_marker=first_free_marker,
                    wait_free_marker=wait_free_marker,
                    paid_marker=(anonymous or authenticated)
                    and raw_row.get("paidPointMarker") is True
                    and raw_row.get("dataIsFree") == "false"
                    and marker_count == 0
                    and not wait_marker
                    and not restricted_marker
                    and not conflicting_free_badge,
                    red_marker_present=red_marker_present,
                    known_restricted=anonymous
                    and not red_marker_present
                    and (
                        wait_marker
                        or modal_marker
                        or restricted_marker
                        or point_only_marker
                    ),
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
            authenticated=authenticated,
            mypage_href=mypage_href,
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
            limit_text = str(MAX_PAGE_SIZE) if raw.get("limit") is None else str(raw["limit"])
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
            or (
                after.continuation is not None
                and after.continuation.offset != continuation.offset + len(added)
            )
        ):
            raise DiscoveryIncompleteError("Yanmaga continuation did not preserve native row order")

    @staticmethod
    def _history_targets(
        snapshot: YanmagaListingSnapshot,
        work: YanmagaWorkParts,
        previous_grants: Mapping[str, DiscoverySourceSnapshot] | None = None,
    ) -> tuple[YanmagaEpisodeParts, ...]:
        """Select unknown/point-only rows plus previously trusted grant targets."""

        episode_ids: list[str] = []
        seen: set[str] = set()
        for row in snapshot.rows:
            if row.free_marker or row.first_free_marker or row.wait_free_marker:
                continue
            if row.episode_id not in seen:
                seen.add(row.episode_id)
                episode_ids.append(row.episode_id)
        for external_id in (previous_grants or {}):
            parsed = _parse_composite_id(external_id)
            if parsed is not None and parsed[0] == work.slug and parsed[1] not in seen:
                seen.add(parsed[1])
                episode_ids.append(parsed[1])
        return tuple(YanmagaEpisodeParts(work.slug, episode_id) for episode_id in episode_ids)

    def _apply_history_countdowns(
        self,
        snapshot: YanmagaListingSnapshot,
        work: YanmagaWorkParts,
        countdowns: tuple[tuple[str, RentalCountdown], ...],
    ) -> None:
        expected_ids = {
            f"{target.slug}:{target.episode_id}"
            for target in self._history_targets(snapshot, work, self._grant_candidates)
        }
        by_external_id = dict(countdowns)
        if len(by_external_id) != len(countdowns) or not set(by_external_id) <= expected_ids:
            return

        now = datetime.now(UTC)
        for external_id, countdown in by_external_id.items():
            if not isinstance(countdown, RentalCountdown) or not countdown.active:
                continue
            if external_id in self._grant_candidates:
                self._fresh_active_grants.add(external_id)
                continue
            previous = self._source_snapshots.get(external_id)
            if previous is not None and previous.access_mode == "owned":
                continue
            expiry = countdown.access_granted_until
            if (
                isinstance(expiry, datetime)
                and expiry.tzinfo is not None
                and expiry.utcoffset() is not None
                and expiry.astimezone(UTC) > now
                and countdown.expiry_evidence
                in {"site_countdown_lower_bound", "site_day_countdown_lower_bound"}
            ):
                episode_id = external_id.rsplit(":", 1)[-1]
                self._fresh_history_grants[episode_id] = expiry

    @staticmethod
    def _records_from_snapshot(
        snapshot: YanmagaListingSnapshot,
        target: WatchlistTarget,
        work: YanmagaWorkParts,
        history_grants: Mapping[str, datetime] | None = None,
    ) -> list[DiscoveredRecord]:
        observed_at = datetime.now(UTC).isoformat()
        total = len(snapshot.rows)
        records: list[DiscoveredRecord] = []
        for index in reversed(range(total)):
            row = snapshot.rows[index]
            external_id = f"{work.slug}:{row.episode_id}"
            history_grant = (history_grants or {}).get(row.episode_id)
            access_mode = (
                "free"
                if row.free_marker or row.first_free_marker
                else "quota"
                if row.wait_free_marker or history_grant is not None
                else "paid"
                if row.paid_marker
                else "unknown"
            )
            records.append(
                DiscoveredRecord(
                    item=DiscoveredItem(
                        canonical_title=target.label,
                        kind="episode",
                        order_key=None,
                        order_label=row.title,
                    ),
                    source=DiscoveredSource(
                        external_id=external_id,
                        url=row.url,
                        access_mode=access_mode,
                        free_until=None,
                        access_granted_until=history_grant,
                        access_granted_until_observed=history_grant is not None,
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
