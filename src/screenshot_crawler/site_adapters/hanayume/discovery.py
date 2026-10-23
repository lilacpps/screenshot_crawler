"""Hanayume episode-list Discovery with complete range validation."""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page, Request, Response

from screenshot_crawler.core.access_guard import AccessGuard
from screenshot_crawler.core.errors import AccessStopError
from screenshot_crawler.discovery.base import DiscoveryAdapter
from screenshot_crawler.discovery.models import (
    DiscoveredItem,
    DiscoveredRecord,
    DiscoveredSource,
    DiscoveryMode,
    DiscoverySourceSnapshot,
    IncrementalStopDecision,
)
from screenshot_crawler.discovery.service import DiscoveryIncompleteError
from screenshot_crawler.site_adapters.hanayume.access import hanayume_access_profile
from screenshot_crawler.watchlist.models import DiscoveryScope, WatchlistTarget

ALLOWED_HOSTS = frozenset({"hanayume.com", "www.hanayume.com"})
EPISODE_PATH = re.compile(r"^/episodes/(?P<episode_id>[0-9a-f]{13})/?$")
WORK_PATH = re.compile(r"^/series/(?P<work_id>[0-9a-f]{13})/?$")
RANGE_PATH = re.compile(
    r"^/episodes/(?P<seed_id>[0-9a-f]{13})(?:/(?P<page_number>[1-9][0-9]*))?/?$"
)
RANGE_LABEL = re.compile(r"^(?P<start>[1-9][0-9]*)-(?P<end>[1-9][0-9]*)$")
SERIES_AUTH_HYDRATION_TIMEOUT_SECONDS = 5.0
SERIES_AUTH_POLL_INTERVAL_MS = 150
SERIES_HISTORY_HYDRATION_TIMEOUT_SECONDS = 5.0

WORK_LINK_SELECTOR = "#xHeader a.ep-h-main-h-series"
LISTING_SELECTOR = ".series-eplist-wrap"
RANGE_LINK_SELECTOR = f"{LISTING_SELECTOR} a.series-sort-link"
SERIES_AUTH_SNAPSHOT_SCRIPT = r"""(workId) => {
  const headerIds = [...document.querySelectorAll('#xHeader')];
  const headers = [...document.querySelectorAll('#xHeader.h')];
  const header = headers.length === 1 ? headers[0] : null;
  const all = selector => [...document.querySelectorAll(selector)];
  const inside = selector => header ? [...header.querySelectorAll(selector)] : [];
  const menu = inside('[data-e2e="hUserMenu"]');
  const icons = inside('[data-e2e="hUserIcon"]');
  const signouts = inside('[data-e2e="signoutBtn"]');
  const userMenus = inside('.h-usermenu');
  const loginAnchors = all('a').filter(anchor => {
    const href = anchor.getAttribute('href') || '';
    const label = (anchor.innerText || '').replace(/\s+/g, ' ').trim();
    return /login|signin|sign-in/i.test(href) ||
      /\u30ed\u30b0\u30a4\u30f3|\u30b5\u30a4\u30f3\u30a4\u30f3|login/i.test(label);
  });
  const wrappers = all('.series-eplist-wrap');
  const wrapper = wrappers.length === 1 ? wrappers[0] : null;
  const outer = wrapper?.parentElement ?? null;
  const mains = wrapper ? [...wrapper.children].filter(node =>
    node.classList.contains('series-eplist-main')) : [];
  const main = mains.length === 1 ? mains[0] : null;
  const roots = wrapper ? [...wrapper.querySelectorAll('.series-eplist')] : [];
  const allRoots = all('.series-eplist');
  const publicRoots = roots.filter(root => root.dataset.e2e === 'epList');
  const userRoots = roots.filter(root => root.dataset.e2e === 'epListUser');
  const outerIsObservedSeries = outer?.tagName === 'DIV' &&
    outer.classList.contains('series') && outer.classList.contains('mode-series-top') &&
    outer.classList.contains('series-safe-filter-target') && outer.dataset.e2e === 'pageSeries';
  const knownRoots = publicRoots.length === 1 && userRoots.length <= 1 &&
    roots.length === publicRoots.length + userRoots.length &&
    publicRoots[0].parentElement === main && userRoots.every(root =>
      root.parentElement === main && root.classList.contains('mode-user'));
  const listingReady = wrappers.length === 1 && outerIsObservedSeries &&
    mains.length === 1 && main?.parentElement === wrapper && knownRoots &&
    allRoots.length === roots.length &&
    [...document.querySelectorAll('.series-eplist-item[data-e2e="eli"]')]
      .every(row => publicRoots[0].contains(row) || userRoots.some(root => root.contains(row)));
  const positive = headerIds.length === 1 && headers.length === 1 &&
    menu.length === 1 && all('[data-e2e="hUserMenu"]').length === 1 &&
    icons.length === 1 && all('[data-e2e="hUserIcon"]').length === 1 &&
    menu[0].tagName === 'A' && menu[0].classList.contains('h-main-nav-link') &&
    menu[0].classList.contains('mode-user') && menu[0].contains(icons[0]) &&
    signouts.length === 1 && all('[data-e2e="signoutBtn"]').length === 1 &&
    signouts[0].tagName === 'BUTTON' && userMenus.length === 1 &&
    userMenus[0].contains(signouts[0]) && loginAnchors.length === 0;
  return {
    routeExact: location.origin === 'https://hanayume.com' &&
      location.pathname === `/series/${workId}` && !location.search && !location.hash,
    listingReady,
    authenticated: positive,
  };
}""";

RANGE_ROWS_SNAPSHOT_SCRIPT = r"""() => {
  const wrappers = [...document.querySelectorAll('.series-eplist-wrap')];
  const wrapper = wrappers.length === 1 ? wrappers[0] : null;
  const mode = wrapper?.parentElement ?? null;
  const episodeMarkers = [...document.querySelectorAll('[data-e2e="pageEpisode"]')];
  const episodePages = episodeMarkers.filter(node => node.tagName === 'DIV' &&
    node.classList.contains('ep-main') &&
    node.classList.contains('series-safe-filter-target'));
  const episodePage = episodePages.length === 1 ? episodePages[0] : null;
  const episodeModes = episodePage ? [...episodePage.children].filter(node =>
    node.tagName === 'DIV' && node.classList.contains('series') &&
    node.classList.contains('mode-ep') && !node.hasAttribute('data-e2e')) : [];
  const episodeMode = episodeModes.length === 1 ? episodeModes[0] : null;
  const mains = wrapper ? [...wrapper.children].filter(node =>
    node.classList.contains('series-eplist-main')) : [];
  const main = mains.length === 1 ? mains[0] : null;
  const roots = wrapper ? [...wrapper.querySelectorAll('.series-eplist')] : [];
  const allRoots = [...document.querySelectorAll('.series-eplist')];
  const publicRoots = roots.filter(root => root.dataset.e2e === 'epList');
  const userRoots = roots.filter(root => root.dataset.e2e === 'epListUser');
  const knownOuter = episodeMarkers.length === 1 && episodePages.length === 1 &&
    episodePage?.tagName === 'DIV' &&
    episodeModes.length === 1 && episodeMode?.parentElement === episodePage &&
    mode === episodeMode;
  const knownRoots = publicRoots.length === 1 && userRoots.length <= 1 &&
    roots.length === publicRoots.length + userRoots.length &&
    publicRoots[0].parentElement === main && userRoots.every(root =>
      root.parentElement === main && root.classList.contains('mode-user'));
  const readRows = root => [...root.querySelectorAll(
    '.series-eplist-item[data-e2e="eli"]')].map(row => {
      const links = [...row.querySelectorAll('a.series-eplist-item-link')];
      const titles = [...row.querySelectorAll('.series-eplist-item-h-text')];
      const badges = [...row.querySelectorAll('.series-eplist-item-access-text')];
      const rentalStats = [...row.querySelectorAll('[data-e2e="eliRentStat"]')];
      return {
        linkCount: links.length,
        href: links.length === 1 ? links[0].href : null,
        titleCount: titles.length,
        title: titles.length === 1 ? (titles[0].innerText || '').trim() : null,
        classNames: [...row.classList],
        rentalStatCount: rentalStats.length,
        rentalStatText: rentalStats.map(node =>
          (node.innerText || '').replace(/\s+/g, ' ').trim()),
        labels: badges.map(node => (node.innerText || '').replace(/\s+/g, ' ').trim())
      };
    });
  const rows = publicRoots.length === 1 ? readRows(publicRoots[0]) : [];
  const historyRows = userRoots.length === 1 ? readRows(userRoots[0]) : [];
  const allRows = [...document.querySelectorAll('.series-eplist-item[data-e2e="eli"]')];
  const scopedRows = wrapper ? [...wrapper.querySelectorAll(
    '.series-eplist-item[data-e2e="eli"]')] : [];
  const rowsKnown = allRows.length === scopedRows.length && allRows.every(row =>
    publicRoots[0]?.contains(row) || userRoots.some(root => root.contains(row)));
  return {
    structureReady: wrappers.length === 1 && allRoots.length === roots.length &&
      knownOuter && mains.length === 1 &&
      main?.parentElement === wrapper && knownRoots && rowsKnown,
    rows,
    historyRows
  };
}""";

NAVIGATION_TIMEOUT_MS = 30_000
DOM_TIMEOUT_MS = 12_000
RANGE_PACING_MS = 2_500
RANGE_PAGE_SIZE = 30
MAX_RANGE_PAGES = 100
MAX_LISTING_ROWS = RANGE_PAGE_SIZE * MAX_RANGE_PAGES
OBSERVATION_TIMEOUT_SECONDS = 8
NATIVE_ACCESS_OBSERVATION_TIMEOUT_SECONDS = 2.0
MAX_NATIVE_ACCESS_REQUESTS = MAX_RANGE_PAGES * 2 + 8
MAX_EPISODE_ACCESS_SECONDS = 72 * 60 * 60
ACCESS_EXPIRY_SAFETY_SECONDS = 1
SERIES_ACCESS_PATH = "/api/series/access"
FREE_LABEL = "\u7121\u6599"
NOW_FREE_LABEL = "\u4eca\u306a\u3089\u7121\u6599"
WAIT_AND_FREE_ACCESS_TYPE = "waitAndFree"
PREMIUM_RENTAL_ACCESS_TYPE = "purchased"
RENTAL_HISTORY_PREFIX = "レンタル中 閲覧期限 "


@dataclass(frozen=True, slots=True)
class HanayumeEpisodeIdentity:
    """A work-scoped Hanayume episode identity."""

    work_id: str
    episode_id: str

    @property
    def external_id(self) -> str:
        return f"{self.work_id}:{self.episode_id}"


@dataclass(frozen=True, slots=True)
class HanayumeEpisodeUrl:
    """Strictly parsed episode URL identity before work context is observed."""

    episode_id: str


@dataclass(frozen=True, slots=True)
class HanayumeAccessObservation:
    """Exact row badge text plus its conservative Catalog classification."""

    raw_labels: tuple[str, ...]
    access_mode: str


@dataclass(frozen=True, slots=True)
class HanayumeRange:
    """One declared page of the native episode-range navigation."""

    page_number: int
    start_position: int
    end_position: int
    url: str
    path: str

    @property
    def label(self) -> str:
        return f"{self.start_position}-{self.end_position}"


@dataclass(frozen=True, slots=True)
class HanayumeListingRow:
    identity: HanayumeEpisodeIdentity
    title: str
    access: HanayumeAccessObservation
    global_position: int
    manual_rental_history: bool = False
    manual_rental_history_present: bool = False
    history_label_conflict: bool = False
    access_granted_until: datetime | None = None
    access_granted_until_observed: bool = False
    rental_history_until: datetime | None = None


@dataclass(frozen=True, slots=True)
class HanayumeNativeEpisodeAccess:
    """Reduced exact-identity access state from a naturally loaded response."""

    episode_id: str
    access_type: str | None
    has_access: bool | None
    remaining_seconds: int | None
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class HanayumeSeriesAccessSnapshot:
    work_id: str
    rows: tuple[HanayumeNativeEpisodeAccess, ...]


def _parse_series_access_snapshot(
    payload: object, *, requested_at: datetime
) -> HanayumeSeriesAccessSnapshot | None:
    if not isinstance(payload, dict):
        return None
    access = payload.get("seriesAccess")
    if not isinstance(access, dict):
        return None
    work_id = access.get("seriesId")
    raw_rows = access.get("episodeAccesses")
    if (
        not isinstance(work_id, str)
        or re.fullmatch(r"[0-9a-f]{13}", work_id) is None
        or not isinstance(raw_rows, list)
    ):
        return None
    rows: list[HanayumeNativeEpisodeAccess] = []
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        episode_id = raw.get("episodeId")
        if (
            not isinstance(episode_id, str)
            or re.fullmatch(r"[0-9a-f]{13}", episode_id) is None
        ):
            continue
        access_type = raw.get("accessType")
        has_access = raw.get("hasAccess")
        remaining = raw.get("timeRemainingInSeconds")
        rows.append(
            HanayumeNativeEpisodeAccess(
                episode_id=episode_id,
                access_type=access_type if isinstance(access_type, str) else None,
                has_access=has_access if type(has_access) is bool else None,
                remaining_seconds=(
                    remaining
                    if type(remaining) is int
                    and 0 <= remaining <= MAX_EPISODE_ACCESS_SECONDS
                    else None
                ),
                requested_at=requested_at,
            )
        )
    return HanayumeSeriesAccessSnapshot(work_id=work_id, rows=tuple(rows))


def _is_series_access_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme.lower() == "https"
        and (parsed.hostname or "").lower() in ALLOWED_HOSTS
        and parsed.username is None
        and parsed.password is None
        and port in (None, 443)
        and parsed.path == SERIES_ACCESS_PATH
    )


class _SeriesAccessObserver:
    """Observe only natural series-access requests on the current Page."""

    def __init__(self) -> None:
        self._page: Page | None = None
        self._request_starts: list[tuple[object, str, str, datetime, bool]] = []
        self._tasks: list[asyncio.Task[None]] = []
        self.snapshots: list[HanayumeSeriesAccessSnapshot] = []
        self.overflow = False
        self._request_listener = self._on_request
        self._response_listener = self._on_response

    def attach(self, page: Page) -> None:
        self._page = page
        page.on("request", self._request_listener)
        page.on("response", self._response_listener)

    def _on_request(self, request: Request) -> None:
        try:
            url = request.url
            method = request.method
        except (AttributeError, PlaywrightError):
            return
        if method != "GET" or not _is_series_access_url(url):
            return
        if len(self._request_starts) >= MAX_NATIVE_ACCESS_REQUESTS:
            self.overflow = True
            return
        self._request_starts.append(
            (request, url, method, datetime.now(UTC), False)
        )

    def _on_response(self, response: Response) -> None:
        try:
            url = response.url
            request = response.request
            method = request.method
        except (AttributeError, PlaywrightError):
            return
        if method != "GET" or not _is_series_access_url(url):
            return
        matching_index = next(
            (
                index
                for index in range(len(self._request_starts) - 1, -1, -1)
                if not self._request_starts[index][4]
                and self._request_starts[index][0] is request
            ),
            None,
        )
        if matching_index is None:
            matching_index = next(
                (
                    index
                    for index, (_request, request_url, request_method, _at, used)
                    in enumerate(self._request_starts)
                    if not used and request_url == url and request_method == method
                ),
                None,
            )
        if matching_index is None:
            return
        original, request_url, request_method, requested_at, _used = self._request_starts[
            matching_index
        ]
        self._request_starts[matching_index] = (
            original,
            request_url,
            request_method,
            requested_at,
            True,
        )
        self._tasks.append(
            asyncio.create_task(self._capture(response, requested_at=requested_at))
        )

    async def _capture(self, response: Response, *, requested_at: datetime) -> None:
        try:
            status = response.status
            if status != 200:
                return
            payload = await asyncio.wait_for(
                response.json(),
                timeout=NATIVE_ACCESS_OBSERVATION_TIMEOUT_SECONDS,
            )
            snapshot = _parse_series_access_snapshot(payload, requested_at=requested_at)
            if snapshot is not None:
                self.snapshots.append(snapshot)
        except (PlaywrightError, TimeoutError, TypeError, ValueError):
            return

    async def wait_for_pending(self, timeout_seconds: float) -> bool:
        """Wait only for already-observed native responses; never create requests."""

        deadline = time.monotonic() + max(0.0, timeout_seconds)
        while True:
            pending = [task for task in self._tasks if not task.done()]
            if not pending:
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                # A poll timeout is non-terminal: keep the response-body task
                # alive for a later poll until finish()/close() owns cleanup.
                return False
            await asyncio.wait(pending, timeout=remaining)
        return True

    async def finish(self) -> tuple[HanayumeSeriesAccessSnapshot, ...]:
        self._detach()
        drained = await self.wait_for_pending(NATIVE_ACCESS_OBSERVATION_TIMEOUT_SECONDS)
        if not drained:
            pending = [task for task in self._tasks if not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        return tuple(self.snapshots)

    async def close(self) -> None:
        self._detach()
        pending = [task for task in self._tasks if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    def _detach(self) -> None:
        if self._page is None:
            return
        try:
            self._page.remove_listener("request", self._request_listener)
            self._page.remove_listener("response", self._response_listener)
        except PlaywrightError:
            pass
        self._page = None


def _latest_native_access_by_episode(
    snapshots: Sequence[HanayumeSeriesAccessSnapshot], *, work_id: str
) -> dict[str, HanayumeNativeEpisodeAccess]:
    latest: dict[str, tuple[datetime, HanayumeNativeEpisodeAccess | None]] = {}
    for snapshot in snapshots:
        if snapshot.work_id != work_id:
            continue
        rows_by_episode: dict[str, list[HanayumeNativeEpisodeAccess]] = {}
        for row in snapshot.rows:
            rows_by_episode.setdefault(row.episode_id, []).append(row)
        for episode_id, rows in rows_by_episode.items():
            candidate = rows[0] if len(rows) == 1 else None
            previous = latest.get(episode_id)
            if previous is None or rows[0].requested_at > previous[0]:
                latest[episode_id] = (rows[0].requested_at, candidate)
            elif rows[0].requested_at == previous[0]:
                previous_row = previous[1]
                if candidate is None or previous_row != candidate:
                    latest[episode_id] = (rows[0].requested_at, None)
    return {
        episode_id: row
        for episode_id, (_requested_at, row) in latest.items()
        if row is not None
    }


def _apply_native_access(
    rows: Sequence[HanayumeListingRow],
    *,
    native_access: dict[str, HanayumeNativeEpisodeAccess],
    listing_authenticated: bool,
) -> list[HanayumeListingRow]:
    updated: list[HanayumeListingRow] = []
    for row in rows:
        native = native_access.get(row.identity.episode_id)
        access_mode = row.access.access_mode
        if (
            access_mode == "unknown"
            and native is not None
            and native.access_type == WAIT_AND_FREE_ACCESS_TYPE
        ):
            access_mode = "quota"
        native_manual_grant = (
            listing_authenticated is True
            and native is not None
            and native.access_type == WAIT_AND_FREE_ACCESS_TYPE
            and native.has_access is True
            and native.remaining_seconds is not None
            and 0 < native.remaining_seconds <= MAX_EPISODE_ACCESS_SECONDS
            and (
                row.manual_rental_history is True
                or row.manual_rental_history_present is False
            )
        )
        premium_rental_grant = (
            listing_authenticated is True
            and native is not None
            and native.access_type == PREMIUM_RENTAL_ACCESS_TYPE
            and native.has_access is True
            and native.remaining_seconds != 0
            and row.rental_history_until is not None
        )
        if row.history_label_conflict and not (native_manual_grant or premium_rental_grant):
            raise DiscoveryIncompleteError(
                "Hanayume public/history access-label conflict lacks an exact active grant"
            )
        grant_until: datetime | None = None
        grant_observed = False
        if (
            listing_authenticated is True
            and native is not None
            and native.access_type == WAIT_AND_FREE_ACCESS_TYPE
            and native.has_access is not None
            and native.remaining_seconds is not None
        ):
            if native.remaining_seconds == 0:
                grant_observed = True
            elif (
                native.has_access is True
                and native.remaining_seconds > 0
                and (
                    row.manual_rental_history is True
                    or row.manual_rental_history_present is False
                )
            ):
                grant_until = native.requested_at + timedelta(
                    seconds=max(0, native.remaining_seconds - ACCESS_EXPIRY_SAFETY_SECONDS)
                )
                grant_observed = True
        if premium_rental_grant:
            if access_mode != "free":
                access_mode = "paid"
            grant_until = row.rental_history_until
            grant_observed = True
        updated.append(
            replace(
                row,
                access=HanayumeAccessObservation(row.access.raw_labels, access_mode),
                access_granted_until=grant_until,
                access_granted_until_observed=grant_observed,
            )
        )
    return updated


def _parse_https_site_url(url: str, pattern: re.Pattern[str]) -> re.Match[str] | None:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.lower() != "https"
        or (parsed.hostname or "").lower() not in ALLOWED_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.query
        or parsed.fragment
    ):
        return None
    return pattern.fullmatch(parsed.path)


def parse_hanayume_episode_url(url: str) -> HanayumeEpisodeUrl | None:
    """Accept only the observed canonical Hanayume episode URL shape."""

    match = _parse_https_site_url(url, EPISODE_PATH)
    if match is None:
        return None
    return HanayumeEpisodeUrl(match.group("episode_id"))


def canonical_hanayume_episode_url(url: str) -> str:
    identity = parse_hanayume_episode_url(url)
    if identity is None:
        raise ValueError("Not a supported Hanayume episode URL")
    return f"https://hanayume.com/episodes/{identity.episode_id}"


def parse_hanayume_work_url(url: str) -> str | None:
    """Return the work ID from a strict first-party series URL."""

    match = _parse_https_site_url(url, WORK_PATH)
    return match.group("work_id") if match is not None else None


def classify_hanayume_access(
    raw_labels: Sequence[str], *, listing_authenticated: bool = False
) -> HanayumeAccessObservation:
    """Classify only exact, unambiguous labels proven by the live listing.

    The raw label remains a helper/diagnostic value. The current Catalog schema
    stores only access_mode, so it is not copied into a title or other field.
    """

    labels = tuple(raw_labels)
    if labels == (FREE_LABEL,):
        return HanayumeAccessObservation(labels, "free")
    if labels == (NOW_FREE_LABEL,) and listing_authenticated is True:
        return HanayumeAccessObservation(labels, "free")
    return HanayumeAccessObservation(labels, "unknown")

def _parse_range_route(
    url: str, *, expected_seed_id: str
) -> tuple[int, str] | None:
    """Return (page number, path); the seed route is the observed page-1 alias."""

    match = _parse_https_site_url(url, RANGE_PATH)
    if match is None or match.group("seed_id") != expected_seed_id:
        return None
    page_number = int(match.group("page_number") or "1")
    return page_number, urlsplit(url).path


def _parse_range_links(
    entries: Sequence[dict[str, object]],
    *,
    seed_id: str,
) -> tuple[HanayumeRange, ...]:
    """Validate the entire declared range set before navigating any range."""

    numeric: list[tuple[int, int, int, str, str]] = []
    for entry in entries:
        label = entry.get("label")
        href = entry.get("href")
        if not isinstance(label, str) or not isinstance(href, str):
            raise DiscoveryIncompleteError("Hanayume range navigation has an invalid link")
        match = RANGE_LABEL.fullmatch(label)
        if match is None:
            continue
        start, end = int(match.group("start")), int(match.group("end"))
        route = _parse_range_route(href, expected_seed_id=seed_id)
        if route is None:
            raise DiscoveryIncompleteError("Hanayume range link targets a foreign or invalid URL")
        page_number, path = route
        numeric.append((page_number, start, end, label, path))

    if not numeric or len(numeric) > MAX_RANGE_PAGES:
        raise DiscoveryIncompleteError("Hanayume range count is missing or exceeds the guard")
    if len({page_number for page_number, *_ in numeric}) != len(numeric):
        raise DiscoveryIncompleteError("Hanayume range navigation repeats a page number")
    if len({label for *_, label, _ in numeric}) != len(numeric):
        raise DiscoveryIncompleteError("Hanayume range navigation repeats a label")
    numeric.sort(key=lambda entry: entry[0])

    ranges: list[HanayumeRange] = []
    expected_start = 1
    for expected_page, (page_number, start, end, label, path) in enumerate(numeric, start=1):
        if page_number != expected_page or start != expected_start or end < start:
            raise DiscoveryIncompleteError(
                "Hanayume range labels are not a contiguous oldest-first sequence"
            )
        if end - start + 1 > RANGE_PAGE_SIZE:
            raise DiscoveryIncompleteError("Hanayume range exceeds the observed page size")
        if expected_page < len(numeric) and end - start + 1 != RANGE_PAGE_SIZE:
            raise DiscoveryIncompleteError("Hanayume non-final range is not a full page")
        if label != f"{start}-{end}":
            raise DiscoveryIncompleteError("Hanayume range label is not canonical")
        expected_path = f"/episodes/{seed_id}/{expected_page}"
        if path != expected_path:
            raise DiscoveryIncompleteError("Hanayume range URL does not match its declared page")
        ranges.append(
            HanayumeRange(
                page_number=expected_page,
                start_position=start,
                end_position=end,
                url=f"https://hanayume.com{path}",
                path=path,
            )
        )
        expected_start = end + 1

    if expected_start - 1 > MAX_LISTING_ROWS:
        raise DiscoveryIncompleteError("Hanayume listing exceeds the row-count guard")
    return tuple(ranges)


def _validate_range_navigation(
    entries: Sequence[dict[str, object]],
    *,
    seed_id: str,
    ranges: tuple[HanayumeRange, ...],
    selected: HanayumeRange,
    actual_page_url: str,
) -> None:
    """Require exact page navigation and the same complete range set."""

    if actual_page_url != selected.url:
        raise DiscoveryIncompleteError(
            "Hanayume range page URL differs from its declared route"
        )

    current = [
        entry
        for entry in entries
        if isinstance(entry.get("current"), bool) and entry.get("current") is True
    ]
    if len(current) != 1 or current[0].get("label") != selected.label:
        raise DiscoveryIncompleteError(
            "Hanayume selected range marker is missing, duplicated, or mismatched"
        )

    current_href = current[0].get("href")
    if not isinstance(current_href, str):
        raise DiscoveryIncompleteError("Hanayume selected range has no URL")
    selected_alias = f"https://hanayume.com/episodes/{seed_id}"
    if current_href not in (selected.url, selected_alias):
        raise DiscoveryIncompleteError(
            "Hanayume selected range link is neither its declared route nor the observed seed alias"
        )
    current_route = _parse_range_route(current_href, expected_seed_id=seed_id)
    if current_route is None:
        raise DiscoveryIncompleteError("Hanayume selected range URL is invalid")

    # Every observed selected anchor points back to the seed episode, regardless
    # of which numbered range is open. Accept that alias only for this unique
    # selected anchor after the actual browser URL and exact label were checked.
    normalized_entries = [
        {
            **entry,
            "href": f"https://hanayume.com{selected.path}",
        }
        if entry is current[0] and current_route[1] == f"/episodes/{seed_id}"
        else entry
        for entry in entries
    ]
    current_range_set = _parse_range_links(normalized_entries, seed_id=seed_id)
    if tuple(
        (item.page_number, item.start_position, item.end_position)
        for item in current_range_set
    ) != tuple(
        (item.page_number, item.start_position, item.end_position)
        for item in ranges
    ):
        raise DiscoveryIncompleteError("Hanayume range set changed during enumeration")

    for entry in normalized_entries:
        label = entry.get("label")
        href = entry.get("href")
        if not isinstance(label, str) or not isinstance(href, str):
            raise DiscoveryIncompleteError("Hanayume range navigation has an invalid link")
        match = RANGE_LABEL.fullmatch(label)
        if match is None:
            continue
        route = _parse_range_route(href, expected_seed_id=seed_id)
        if route is None:
            raise DiscoveryIncompleteError("Hanayume range navigation changed work context")
        start, end = int(match.group("start")), int(match.group("end"))
        descriptor = next(
            (
                item
                for item in ranges
                if item.start_position == start and item.end_position == end
            ),
            None,
        )
        if descriptor is None or route[0] != descriptor.page_number:
            raise DiscoveryIncompleteError("Hanayume range link does not match its label")
        if route[1] != descriptor.path:
            raise DiscoveryIncompleteError("Hanayume range URL changed during enumeration")


async def _guard_checkpoint(guard: AccessGuard, page: Page) -> None:
    try:
        await asyncio.wait_for(
            guard.check_page(page), timeout=OBSERVATION_TIMEOUT_SECONDS
        )
    except AccessStopError as exc:
        raise DiscoveryIncompleteError(
            f"Hanayume Discovery stopped by the access guard: {exc.reason}"
        ) from exc
    except TimeoutError as exc:
        raise DiscoveryIncompleteError(
            "Hanayume access-state observation exceeded its timeout"
        ) from exc


async def _navigation_response(page: Page, url: str, guard: AccessGuard) -> None:
    try:
        response = await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=NAVIGATION_TIMEOUT_MS,
        )
    except (PlaywrightError, TimeoutError) as exc:
        await _guard_checkpoint(guard, page)
        raise DiscoveryIncompleteError("Hanayume page navigation did not complete") from exc
    await _guard_checkpoint(guard, page)
    if response is None or response.status != 200:
        raise DiscoveryIncompleteError("Hanayume page did not return HTTP 200")


async def _wait_for_listing(page: Page, guard: AccessGuard) -> None:
    try:
        await page.locator(WORK_LINK_SELECTOR).wait_for(
            state="visible", timeout=DOM_TIMEOUT_MS
        )
        await page.locator(LISTING_SELECTOR).wait_for(
            state="visible", timeout=DOM_TIMEOUT_MS
        )
        await page.wait_for_function(
            """() => document.querySelectorAll(
              '[data-e2e="pageEpisode"]'
            ).length === 1 && (() => {
              const episodeMarkers = [...document.querySelectorAll('[data-e2e="pageEpisode"]')];
              const pageRoots = episodeMarkers.filter(node => node.tagName === 'DIV' &&
                node.classList.contains('ep-main') &&
                node.classList.contains('series-safe-filter-target'));
              const pageRoot = pageRoots.length === 1 ? pageRoots[0] : null;
              if (!pageRoot) return false;
              const modes = [...pageRoot.children].filter(node =>
                node.tagName === 'DIV' && node.classList.contains('series') &&
                node.classList.contains('mode-ep') && !node.hasAttribute('data-e2e'));
              const wrappers = [...document.querySelectorAll('.series-eplist-wrap')];
              const wrap = wrappers.length === 1 ? wrappers[0] : null;
              const mains = wrap ? [...wrap.children].filter(node =>
                node.classList.contains('series-eplist-main')) : [];
              const roots = wrap ? [...wrap.querySelectorAll('.series-eplist')] : [];
              const publicRoots = roots.filter(root => root.dataset.e2e === 'epList');
              const userRoots = roots.filter(root => root.dataset.e2e === 'epListUser');
              const allRoots = [...document.querySelectorAll('.series-eplist')];
              const publicRoot = publicRoots.length === 1 ? publicRoots[0] : null;
              const main = mains.length === 1 ? mains[0] : null;
              const rowsKnown = [...document.querySelectorAll(
                '.series-eplist-item[data-e2e="eli"]')].every(row =>
                  publicRoot?.contains(row) || userRoots.some(root => root.contains(row)));
              return episodeMarkers.length === 1 && pageRoots.length === 1 &&
                modes.length === 1 && wrap?.parentElement === modes[0] &&
                wrappers.length === 1 && mains.length === 1 && main?.parentElement === wrap &&
                publicRoots.length === 1 && publicRoot.parentElement === main &&
                userRoots.length <= 1 && roots.length === publicRoots.length + userRoots.length &&
                allRoots.length === roots.length && userRoots.every(root =>
                  root.parentElement === main && root.classList.contains('mode-user')) &&
                rowsKnown && publicRoot.querySelectorAll(
                  '.series-eplist-item[data-e2e="eli"]').length > 0;
            })()""",
            timeout=DOM_TIMEOUT_MS,
        )
    except (PlaywrightError, TimeoutError) as exc:
        await _guard_checkpoint(guard, page)
        raise DiscoveryIncompleteError("Hanayume episode list did not become ready") from exc
    await _guard_checkpoint(guard, page)


async def _wait_for_authenticated_episode_history(page: Page, guard: AccessGuard) -> None:
    """Wait for the observed account-history root before reading authenticated ranges."""

    deadline = time.monotonic() + SERIES_HISTORY_HYDRATION_TIMEOUT_SECONDS
    while True:
        try:
            state = await asyncio.wait_for(
                page.evaluate(
                    r"""() => {
                      const wrappers = [...document.querySelectorAll('.series-eplist-wrap')];
                      const wrapper = wrappers.length === 1 ? wrappers[0] : null;
                      const mains = wrapper ? [...wrapper.children].filter(node =>
                        node.classList.contains('series-eplist-main')) : [];
                      const main = mains.length === 1 ? mains[0] : null;
                      const roots = wrapper ? [...wrapper.querySelectorAll('.series-eplist')] : [];
                      const allRoots = [...document.querySelectorAll('.series-eplist')];
                      const users = roots.filter(root => root.dataset.e2e === 'epListUser');
                      const publicRoots = roots.filter(root => root.dataset.e2e === 'epList');
                      if (wrappers.length !== 1 || mains.length !== 1 ||
                          roots.length !== 2 || allRoots.length !== 2 || users.length !== 1 ||
                          publicRoots.length !== 1 ||
                          users[0].parentElement !== main || !users[0].classList.contains('mode-user')) {
                        return 'unknown';
                      }
                      const root = users[0];
                      const classes = [...root.classList].sort().join(' ');
                      if (classes === 'mode-loading mode-user series-eplist') return 'loading';
                      if (classes === 'mode-no-user mode-user series-eplist') return 'no-user';
                      if (classes !== 'mode-has-eps mode-user series-eplist') return 'unknown';
                      const defaults = [...root.children].filter(node =>
                        node.classList.contains('series-eplist-default'));
                      const rows = [...root.querySelectorAll(
                        '.series-eplist-item[data-e2e="eli"]')];
                      return defaults.length === 1 && defaults[0].parentElement === root &&
                        rows.length > 0 && publicRoots.length === 1 &&
                        [...document.querySelectorAll('.series-eplist-item[data-e2e="eli"]')]
                          .every(row => publicRoots[0].contains(row) || root.contains(row))
                        ? 'ready' : 'unknown';
                    }"""
                ),
                timeout=OBSERVATION_TIMEOUT_SECONDS,
            )
        except (PlaywrightError, TimeoutError) as exc:
            raise DiscoveryIncompleteError(
                "Hanayume authenticated account history could not be observed"
            ) from exc
        if state == "ready":
            await _guard_checkpoint(guard, page)
            return
        if state in {"no-user", "unknown"}:
            raise DiscoveryIncompleteError(
                "Hanayume authenticated account history has an unrecognized state"
            )
        if state != "loading":
            raise DiscoveryIncompleteError(
                "Hanayume authenticated account history state is malformed"
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise DiscoveryIncompleteError(
                "Hanayume authenticated account history did not finish loading"
            )
        await page.wait_for_timeout(
            min(SERIES_AUTH_POLL_INTERVAL_MS, max(1, int(remaining * 1000)))
        )
        await _guard_checkpoint(guard, page)


async def _wait_for_series_listing(page: Page, guard: AccessGuard) -> None:
    try:
        await page.locator(LISTING_SELECTOR).wait_for(
            state="visible", timeout=DOM_TIMEOUT_MS
        )
        await page.wait_for_function(
            """() => {
              const wrappers = [...document.querySelectorAll('.series-eplist-wrap')];
              if (wrappers.length !== 1) return false;
              const wrap = wrappers[0];
              const outer = wrap.parentElement;
              const mains = [...wrap.children].filter(node =>
                node.classList.contains('series-eplist-main'));
              const roots = [...wrap.querySelectorAll('.series-eplist')];
              const publicRoots = roots.filter(root => root.dataset.e2e === 'epList');
              const userRoots = roots.filter(root => root.dataset.e2e === 'epListUser');
              return outer?.dataset.e2e === 'pageSeries' &&
                outer.classList.contains('mode-series-top') && mains.length === 1 &&
                mains[0].parentElement === wrap && publicRoots.length === 1 &&
                publicRoots[0].parentElement === mains[0] && userRoots.length <= 1 &&
                roots.length === publicRoots.length + userRoots.length &&
                userRoots.every(root => root.parentElement === mains[0] &&
                  root.classList.contains('mode-user')) &&
                publicRoots[0].querySelectorAll('.series-eplist-item[data-e2e="eli"]').length > 0;
            }""",
            timeout=DOM_TIMEOUT_MS,
        )
    except (PlaywrightError, TimeoutError) as exc:
        await _guard_checkpoint(guard, page)
        raise DiscoveryIncompleteError(
            "Hanayume canonical work listing did not become ready"
        ) from exc
    await _guard_checkpoint(guard, page)


async def _read_work_identity(page: Page) -> tuple[str, str, str]:
    data = await asyncio.wait_for(
        page.evaluate(
            """() => {
          const header = document.querySelector("#xHeader");
          const links = header
            ? [...header.querySelectorAll("a.ep-h-main-h-series")]
            : [];
          const list = document.querySelector(".series-eplist-wrap");
          const episodeMarkers = [...document.querySelectorAll('[data-e2e="pageEpisode"]')];
          const episodePages = episodeMarkers.filter(node => node.tagName === 'DIV' &&
            node.classList.contains('ep-main') &&
            node.classList.contains('series-safe-filter-target'));
          const episodePage = episodePages.length === 1 ? episodePages[0] : null;
          const scopes = episodePage ? [...episodePage.children].filter(node =>
            node.tagName === 'DIV' && node.classList.contains('series') &&
            node.classList.contains('mode-ep') && !node.hasAttribute('data-e2e')) : [];
          const scope = scopes.length === 1 ? scopes[0] : null;
          const main = list ? [...list.children].filter(node =>
            node.classList.contains('series-eplist-main')) : [];
          const roots = list ? [...list.querySelectorAll('.series-eplist')] : [];
          const publicRoots = roots.filter(node => node.dataset.e2e === 'epList');
          const userRoots = roots.filter(node => node.dataset.e2e === 'epListUser');
          const link = links.length === 1 ? links[0] : null;
          return {
            link_count: links.length,
            href: link?.href || null,
            title: link?.innerText?.trim() || null,
            header_count: document.querySelectorAll("#xHeader").length,
            list_count: document.querySelectorAll(".series-eplist-wrap").length,
            scope_count: document.querySelectorAll("div.series.mode-ep").length,
            episode_page_count: episodeMarkers.length,
            episode_scope: episodePages.length === 1 &&
              episodePage?.classList.contains('ep-main') &&
              episodePage.classList.contains('series-safe-filter-target'),
            mode_scope: scopes.length === 1 && scope?.hasAttribute('data-e2e') === false,
            list_in_scope: Boolean(scope && list && scope.contains(list) &&
              list.parentElement === scope),
            main_count: main.length,
            main_direct: main.length === 1 && main[0].parentElement === list,
            known_roots: publicRoots.length === 1 && userRoots.length <= 1 &&
              roots.length === publicRoots.length + userRoots.length &&
              publicRoots[0].parentElement === main[0] && userRoots.every(node =>
                node.parentElement === main[0] && node.classList.contains('mode-user')),
            rows_known: [...document.querySelectorAll('.series-eplist-item[data-e2e="eli"]')]
              .every(row => publicRoots[0]?.contains(row) || userRoots.some(root => root.contains(row))),
          };
            }"""
        ),
        timeout=OBSERVATION_TIMEOUT_SECONDS,
    )
    if (
        not isinstance(data, dict)
        or data.get("link_count") != 1
        or data.get("header_count") != 1
        or data.get("list_count") != 1
        or data.get("scope_count") != 1
        or data.get("episode_page_count") != 1
        or data.get("episode_scope") is not True
        or data.get("mode_scope") is not True
        or data.get("list_in_scope") is not True
        or data.get("main_count") != 1
        or data.get("main_direct") is not True
        or data.get("known_roots") is not True
        or data.get("rows_known") is not True
        or not isinstance(data.get("href"), str)
        or not isinstance(data.get("title"), str)
        or not data["title"].strip()
    ):
        raise DiscoveryIncompleteError(
            "Hanayume target work link or its listing scope is missing or ambiguous"
        )
    work_id = parse_hanayume_work_url(data["href"])
    if work_id is None:
        raise DiscoveryIncompleteError("Hanayume target work link has an invalid identity")
    canonical_work_url = f"https://hanayume.com/series/{work_id}"
    if data["href"] != canonical_work_url:
        raise DiscoveryIncompleteError("Hanayume target work link is not its exact canonical URL")
    return work_id, data["title"].strip(), canonical_work_url


async def _read_series_authentication(page: Page, *, work_id: str) -> bool:
    expected_url = f"https://hanayume.com/series/{work_id}"
    deadline = time.monotonic() + SERIES_AUTH_HYDRATION_TIMEOUT_SECONDS
    while True:
        if page.url != expected_url:
            raise ValueError("Hanayume auth marker is outside its exact work route")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        try:
            value = await asyncio.wait_for(
                page.evaluate(SERIES_AUTH_SNAPSHOT_SCRIPT, work_id),
                timeout=min(OBSERVATION_TIMEOUT_SECONDS, remaining),
            )
        except TimeoutError as exc:
            # An observation that runs out the overall hydration budget means
            # authentication was not established, just like reaching the loop
            # boundary between observations. Preserve the route check before
            # accepting that negative result.
            if page.url != expected_url:
                raise ValueError("Hanayume authentication route identity changed") from exc
            if time.monotonic() >= deadline:
                return False
            raise ValueError(
                "Hanayume work-listing authentication markers could not be read"
            ) from exc
        except PlaywrightError as exc:
            raise ValueError(
                "Hanayume work-listing authentication markers could not be read"
            ) from exc
        if page.url != expected_url:
            raise ValueError("Hanayume authentication route identity changed")
        if not isinstance(value, dict) or value.get("routeExact") is not True:
            raise ValueError("Hanayume authentication route identity changed")
        if value.get("listingReady") is not True:
            raise ValueError("Hanayume authenticated work listing is missing or ambiguous")
        authenticated = value.get("authenticated")
        if not isinstance(authenticated, bool):
            raise TypeError("Hanayume authentication marker state is malformed")
        if authenticated:
            return True

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        await page.wait_for_timeout(
            min(SERIES_AUTH_POLL_INTERVAL_MS, max(1, int(remaining * 1000)))
        )


async def _read_range_links(page: Page) -> list[dict[str, object]]:
    entries = await asyncio.wait_for(
        page.locator(RANGE_LINK_SELECTOR).evaluate_all(
            """anchors => anchors.map(anchor => ({
          label: (anchor.innerText || "").replace(/\\s+/g, " ").trim(),
          href: anchor.href,
          current: anchor.classList.contains("mode-current")
            }))"""
        ),
        timeout=OBSERVATION_TIMEOUT_SECONDS,
    )
    if not isinstance(entries, list) or not entries:
        raise DiscoveryIncompleteError("Hanayume range navigation is missing")
    return entries


def _validate_initial_latest_marker(
    entries: Sequence[dict[str, object]], *, seed_id: str
) -> None:
    current = [
        entry
        for entry in entries
        if entry.get("current") is True
    ]
    if len(current) != 1 or current[0].get("label") != "最新話から":
        raise DiscoveryIncompleteError(
            "Hanayume initial episode-list navigation is not the observed latest-range state"
        )
    href = current[0].get("href")
    if not isinstance(href, str):
        raise DiscoveryIncompleteError("Hanayume initial selected range has no URL")
    match = _parse_https_site_url(
        href,
        re.compile(rf"^/episodes/{re.escape(seed_id)}(?:/old)?/?$"),
    )
    if match is None:
        raise DiscoveryIncompleteError("Hanayume initial latest-range URL is invalid")


def _rental_history_expiry(label: str, *, observed_at: datetime) -> datetime | None:
    """Use the displayed countdown's conservative lower bound, not ownership."""

    match = re.fullmatch(
        re.escape(RENTAL_HISTORY_PREFIX)
        + r"(?:(?P<days>[0-9]{1,2})日\+)?(?P<hours>[0-9]{1,2})時間",
        label,
    )
    if match is None:
        return None
    days, hours = int(match["days"] or 0), int(match["hours"])
    remaining = timedelta(days=days, hours=hours) - timedelta(hours=1)
    if days > 14 or hours > 23 or remaining <= timedelta():
        return None
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("Hanayume rental observation requires an aware timestamp")
    return observed_at + remaining


async def _read_range_rows(
    page: Page,
    *,
    work_id: str,
    first_position: int,
    listing_authenticated: bool,
) -> list[HanayumeListingRow]:
    observed_at = datetime.now(UTC)
    try:
        snapshot = await asyncio.wait_for(
            page.evaluate(RANGE_ROWS_SNAPSHOT_SCRIPT),
            timeout=OBSERVATION_TIMEOUT_SECONDS,
        )
    except (PlaywrightError, TimeoutError) as exc:
        raise DiscoveryIncompleteError(
            "Hanayume public episode rows could not be observed"
        ) from exc
    if not isinstance(snapshot, dict) or snapshot.get("structureReady") is not True:
        raise DiscoveryIncompleteError(
            "Hanayume episode list does not match its observed public/history structure"
        )
    rows = snapshot.get("rows")
    history_rows = snapshot.get("historyRows")
    if not isinstance(rows, list) or not rows:
        raise DiscoveryIncompleteError("Hanayume range contains no episode rows")
    if not isinstance(history_rows, list):
        raise DiscoveryIncompleteError("Hanayume history-copy observation is malformed")

    parsed_rows: list[HanayumeListingRow] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(rows):
        if (
            not isinstance(raw, dict)
            or raw.get("linkCount") != 1
            or raw.get("titleCount") != 1
            or not isinstance(raw.get("href"), str)
            or not isinstance(raw.get("title"), str)
            or not raw["title"].strip()
            or not isinstance(raw.get("labels"), list)
            or not all(isinstance(label, str) for label in raw["labels"])
            or not isinstance(raw.get("classNames"), list)
            or not all(isinstance(name, str) for name in raw["classNames"])
            or type(raw.get("rentalStatCount")) is not int
            or not isinstance(raw.get("rentalStatText"), list)
            or not all(isinstance(text, str) for text in raw["rentalStatText"])
        ):
            raise DiscoveryIncompleteError(
                "Hanayume episode row is incomplete or has ambiguous identity/badges"
            )
        parsed_url = parse_hanayume_episode_url(raw["href"])
        if parsed_url is None:
            raise DiscoveryIncompleteError("Hanayume episode row targets an invalid URL")
        if parsed_url.episode_id in seen_ids:
            raise DiscoveryIncompleteError("Hanayume listing contains duplicate episode IDs")
        seen_ids.add(parsed_url.episode_id)
        labels = tuple(raw["labels"])
        parsed_rows.append(
            HanayumeListingRow(
                identity=HanayumeEpisodeIdentity(work_id, parsed_url.episode_id),
                title=raw["title"].strip(),
                access=classify_hanayume_access(
                    labels, listing_authenticated=listing_authenticated
                ),
                global_position=first_position + index,
            )
        )
    public_labels = {
        row.identity.episode_id: row.access.raw_labels for row in parsed_rows
    }
    public_titles = {row.identity.episode_id: row.title for row in parsed_rows}
    rental_history_until: dict[str, datetime] = {}
    history_ids: set[str] = set()
    manual_rental_history_ids: set[str] = set()
    history_label_conflict_ids: set[str] = set()
    for raw in history_rows:
        if (
            not isinstance(raw, dict)
            or raw.get("linkCount") != 1
            or not isinstance(raw.get("href"), str)
            or not isinstance(raw.get("labels"), list)
            or not all(isinstance(label, str) for label in raw["labels"])
            or not isinstance(raw.get("classNames"), list)
            or not all(isinstance(name, str) for name in raw["classNames"])
            or type(raw.get("rentalStatCount")) is not int
            or not isinstance(raw.get("rentalStatText"), list)
            or not all(isinstance(text, str) for text in raw["rentalStatText"])
        ):
            raise DiscoveryIncompleteError("Hanayume history copy is incomplete or ambiguous")
        identity = parse_hanayume_episode_url(raw["href"])
        if identity is None or identity.episode_id in history_ids:
            raise DiscoveryIncompleteError("Hanayume history copy has an invalid or duplicate ID")
        history_ids.add(identity.episode_id)
        public_labels_for_copy = public_labels.get(identity.episode_id)
        if public_labels_for_copy is not None and tuple(raw["labels"]) != public_labels_for_copy:
            history_label_conflict_ids.add(identity.episode_id)
        rental_texts = raw["rentalStatText"]
        # Below one day/hour the site uses "7時間" / "7分" respectively.
        # This marker still requires the exact native active-grant proof later.
        if (
            "mode-read" in raw["classNames"]
            and raw["rentalStatCount"] == 1
            and len(rental_texts) == 1
            and rental_texts[0].startswith(RENTAL_HISTORY_PREFIX)
            and re.fullmatch(
                r"(?:(?:[0-9]+日\+)?[0-9]+時間|(?:[1-9]|[1-5][0-9])分)",
                rental_texts[0][len(RENTAL_HISTORY_PREFIX) :],
            )
        ):
            manual_rental_history_ids.add(identity.episode_id)
            if (
                raw.get("titleCount") == 1
                and raw.get("title") == public_titles.get(identity.episode_id)
                and raw["labels"] == rental_texts
            ):
                expires_at = _rental_history_expiry(rental_texts[0], observed_at=observed_at)
                if expires_at is not None:
                    rental_history_until[identity.episode_id] = expires_at
    parsed_rows = [
        replace(
            row,
            manual_rental_history=row.identity.episode_id in manual_rental_history_ids,
            manual_rental_history_present=row.identity.episode_id in history_ids,
            history_label_conflict=row.identity.episode_id in history_label_conflict_ids,
            rental_history_until=rental_history_until.get(row.identity.episode_id),
        )
        for row in parsed_rows
    ]
    return parsed_rows


def _records_from_rows(
    *,
    rows_oldest_first: Sequence[HanayumeListingRow],
    work_title: str,
    seed_episode_id: str,
    scope: DiscoveryScope | None,
) -> list[DiscoveredRecord]:
    if not rows_oldest_first or len(rows_oldest_first) > MAX_LISTING_ROWS:
        raise DiscoveryIncompleteError("Hanayume listing is empty or exceeds the row-count guard")
    ids = [row.identity.episode_id for row in rows_oldest_first]
    if len(set(ids)) != len(ids):
        raise DiscoveryIncompleteError("Hanayume listing contains duplicate episode IDs")
    if ids.count(seed_episode_id) != 1:
        raise DiscoveryIncompleteError("Hanayume seed episode is missing or duplicated in its work")

    records_oldest_first = [
        DiscoveredRecord(
            item=DiscoveredItem(
                canonical_title=work_title,
                kind="episode",
                order_label=row.title,
            ),
            source=DiscoveredSource(
                external_id=row.identity.external_id,
                url=f"https://hanayume.com/episodes/{row.identity.episode_id}",
                access_mode=row.access.access_mode,
                available=True,
                access_granted_until=row.access_granted_until,
                access_granted_until_observed=row.access_granted_until_observed,
                global_display_position=row.global_position,
            ),
        )
        for row in rows_oldest_first
    ]
    latest_first = list(reversed(records_oldest_first))
    if scope is None:
        return latest_first
    return _apply_discovery_scope(
        latest_first,
        scope=scope,
        work_id=rows_oldest_first[0].identity.work_id,
    )


def _apply_discovery_scope(
    records: list[DiscoveredRecord],
    *,
    scope: DiscoveryScope,
    work_id: str,
) -> list[DiscoveredRecord]:
    """Apply inclusive boundaries in latest-first order after full validation."""

    if scope.from_url is None and scope.through_url is None:
        raise DiscoveryIncompleteError("Hanayume bounded scope has no boundary")
    indices = {
        record.source.url.rsplit("/", 1)[-1]: index
        for index, record in enumerate(records)
    }
    boundaries: dict[str, int] = {}
    for name, value in (("from", scope.from_url), ("through", scope.through_url)):
        if value is None:
            continue
        identity = parse_hanayume_episode_url(value)
        if identity is None:
            raise DiscoveryIncompleteError(f"Hanayume bounded {name} URL is invalid")
        external_id = f"{work_id}:{identity.episode_id}"
        if not any(record.source.external_id == external_id for record in records):
            raise DiscoveryIncompleteError(
                f"Hanayume bounded {name} boundary is outside the target work listing"
            )
        boundaries[name] = indices.get(identity.episode_id, -1)
    start = boundaries.get("from", 0)
    end = boundaries.get("through", len(records) - 1)
    if start < 0 or end < 0 or start > end:
        raise DiscoveryIncompleteError("Hanayume bounded boundaries are missing or reversed")
    return records[start : end + 1]


class HanayumeDiscoveryAdapter(DiscoveryAdapter):
    """Enumerate a complete work listing through its observed range links."""

    supports_bounded_discovery = True

    def incremental_stop_decision(
        self,
        record: DiscoveredRecord,
        previous: DiscoverySourceSnapshot | None,
        target: WatchlistTarget,
    ) -> IncrementalStopDecision:
        del record, previous, target
        # Hanayume's complete episode range is already buffered before yielding;
        # old account grants must be refreshed even after known Catalog rows.
        return IncrementalStopDecision.CONTINUE

    async def iter_records(
        self,
        page: Page,
        target: WatchlistTarget,
        mode: DiscoveryMode,
    ) -> AsyncIterator[DiscoveredRecord]:
        self.reset_complete_listing_inventory()
        target_identity = parse_hanayume_episode_url(target.url)
        if target_identity is None:
            raise DiscoveryIncompleteError(
                "Hanayume Watchlist target must be a strict absolute episode URL"
            )
        canonical_url = canonical_hanayume_episode_url(target.url)
        guard = AccessGuard.from_profile(
            site="hanayume",
            profile=hanayume_access_profile(),
            stop_on_http_403=True,
            stop_on_http_429=True,
            stop_on_challenge=True,
            stop_on_captcha=True,
        )
        guard.start(page)
        access_observer = _SeriesAccessObserver()
        access_observer.attach(page)
        try:
            await _navigation_response(page, canonical_url, guard)
            if page.url != canonical_url:
                raise DiscoveryIncompleteError(
                    "Hanayume seed episode navigation changed its canonical identity"
                )
            await _wait_for_listing(page, guard)
            work_id, work_title, work_url = await _read_work_identity(page)
            initial_entries = await _read_range_links(page)
            _validate_initial_latest_marker(initial_entries, seed_id=target_identity.episode_id)
            ranges = _parse_range_links(initial_entries, seed_id=target_identity.episode_id)

            await _navigation_response(page, work_url, guard)
            if page.url != work_url:
                raise DiscoveryIncompleteError(
                    "Hanayume work-link navigation changed its exact canonical URL"
                )
            await _wait_for_series_listing(page, guard)
            listing_authenticated = await _read_series_authentication(page, work_id=work_id)
            await _guard_checkpoint(guard, page)

            await _navigation_response(page, canonical_url, guard)
            if page.url != canonical_url:
                raise DiscoveryIncompleteError(
                    "Hanayume return navigation changed its exact seed episode URL"
                )
            await _wait_for_listing(page, guard)
            returned_work_id, returned_work_title, returned_work_url = await _read_work_identity(page)
            returned_entries = await _read_range_links(page)
            _validate_initial_latest_marker(
                returned_entries, seed_id=target_identity.episode_id
            )
            returned_ranges = _parse_range_links(
                returned_entries, seed_id=target_identity.episode_id
            )
            if (
                returned_work_id != work_id
                or returned_work_title != work_title
                or returned_work_url != work_url
                or returned_ranges != ranges
            ):
                raise DiscoveryIncompleteError(
                    "Hanayume seed identity or range set changed after auth verification"
                )

            rows_oldest_first: list[HanayumeListingRow] = []
            all_ids: set[str] = set()
            for index, episode_range in enumerate(ranges):
                if index:
                    await page.wait_for_timeout(RANGE_PACING_MS)
                    await _guard_checkpoint(guard, page)
                await _navigation_response(page, episode_range.url, guard)
                if page.url != episode_range.url:
                    raise DiscoveryIncompleteError(
                        "Hanayume range navigation redirected from its declared URL"
                    )
                await _wait_for_listing(page, guard)
                current_work_id, current_work_title, current_work_url = await _read_work_identity(page)
                if (
                    current_work_id != work_id
                    or current_work_title != work_title
                    or current_work_url != work_url
                ):
                    raise DiscoveryIncompleteError(
                        "Hanayume range page belongs to a different work context"
                    )
                if listing_authenticated:
                    await _wait_for_authenticated_episode_history(page, guard)
                entries = await _read_range_links(page)
                _validate_range_navigation(
                    entries,
                    seed_id=target_identity.episode_id,
                    ranges=ranges,
                    selected=episode_range,
                    actual_page_url=page.url,
                )
                page_rows = await _read_range_rows(
                    page,
                    work_id=work_id,
                    first_position=episode_range.start_position,
                    listing_authenticated=listing_authenticated,
                )
                expected_count = episode_range.end_position - episode_range.start_position + 1
                if len(page_rows) != expected_count:
                    raise DiscoveryIncompleteError(
                        "Hanayume episode count did not match the declared range"
                    )
                for row in page_rows:
                    if row.identity.episode_id in all_ids:
                        raise DiscoveryIncompleteError(
                            "Hanayume range pages contain duplicate episode IDs"
                        )
                    all_ids.add(row.identity.episode_id)
                rows_oldest_first.extend(page_rows)
                await _guard_checkpoint(guard, page)

            if len(rows_oldest_first) != ranges[-1].end_position:
                raise DiscoveryIncompleteError(
                    "Hanayume range set did not cover its declared total"
                )
            native_snapshots = await access_observer.finish()
            if access_observer.overflow:
                raise DiscoveryIncompleteError(
                    "Hanayume native access observation exceeded its bounded response limit"
                )
            rows_oldest_first = _apply_native_access(
                rows_oldest_first,
                native_access=_latest_native_access_by_episode(
                    native_snapshots, work_id=work_id
                ),
                listing_authenticated=listing_authenticated,
            )
            all_records = _records_from_rows(
                rows_oldest_first=rows_oldest_first,
                work_title=work_title,
                seed_episode_id=target_identity.episode_id,
                scope=None,
            )
            records = (
                all_records
                if target.discovery_scope is None
                else _apply_discovery_scope(
                    all_records,
                    scope=target.discovery_scope,
                    work_id=work_id,
                )
            )
        except DiscoveryIncompleteError:
            raise
        except ValueError as exc:
            raise DiscoveryIncompleteError(
                "Hanayume work authentication or identity validation failed"
            ) from exc
        except AccessStopError as exc:
            raise DiscoveryIncompleteError(
                f"Hanayume Discovery stopped by the access guard: {exc.reason}"
            ) from exc
        except (PlaywrightError, TimeoutError) as exc:
            await _guard_checkpoint(guard, page)
            raise DiscoveryIncompleteError("Hanayume episode listing did not complete") from exc
        finally:
            await access_observer.close()
            await guard.close()

        for record in records:
            yield record
        if mode == "full":
            self.capture_complete_listing_inventory(
                target=target,
                all_records=all_records,
                selected_records=records,
                listing_identity=f"hanayume-work:{work_id}",
            )


__all__ = [
    "HanayumeAccessObservation",
    "HanayumeDiscoveryAdapter",
    "HanayumeEpisodeIdentity",
    "HanayumeEpisodeUrl",
    "HanayumeRange",
    "canonical_hanayume_episode_url",
    "classify_hanayume_access",
    "parse_hanayume_episode_url",
    "parse_hanayume_work_url",
]
