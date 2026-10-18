"""Younganimal work-scoped Discovery from the site's declared episode ranges."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, urlsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page, Request, Response
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from screenshot_crawler.catalog.service import JST
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
from screenshot_crawler.site_adapters.younganimal.access import younganimal_access_profile
from screenshot_crawler.watchlist.models import DiscoveryScope, WatchlistTarget

ALLOWED_HOSTS = frozenset({"younganimal.com"})
EPISODE_PATH = re.compile(r"^/episodes/(?P<episode_id>[0-9a-f]{13})/?$")
WORK_PATH = re.compile(r"^/series/(?P<work_id>[0-9a-f]{13})/?$")
RANGE_PATH = re.compile(
    r"^/series/(?P<work_id>[0-9a-f]{13})/(?P<page_number>[1-9][0-9]*)/?$"
)
RANGE_LABEL = re.compile(r"^(?P<start>[1-9][0-9]*)-(?P<end>[1-9][0-9]*)$")

LISTING_SELECTOR = ".series-eplist-main"
RANGE_LINK_SELECTOR = f"{LISTING_SELECTOR} a.series-sort-link"
RANGE_PAGE_SIZE = 30
MAX_RANGE_PAGES = 100
MAX_LISTING_ROWS = RANGE_PAGE_SIZE * MAX_RANGE_PAGES
NAVIGATION_TIMEOUT_MS = 20_000
NAVIGATION_RETRY_BACKOFF_MS = 2_000
MAX_NAVIGATION_RETRIES = 1
MAX_WORK_NAVIGATION_RETRIES = 2
MAX_NAVIGATION_EVIDENCE_REQUESTS = 8
DOM_TIMEOUT_MS = 12_000
OBSERVATION_TIMEOUT_SECONDS = 15
MAX_NATIVE_ACCESS_REQUESTS = 512
NATIVE_ACCESS_OBSERVATION_TIMEOUT_SECONDS = 8.0
MAX_NATIVE_RESPONSE_BYTES = 1_048_576
RANGE_PACING_MS = 3_000
GUARD_CLEANUP_TIMEOUT_SECONDS = 5
FREE_LABEL = "無料"
RENTAL_LABEL = re.compile(r"^レンタル中 閲覧期限 (?P<days>[0-9]{1,2})日\+(?P<hours>[0-9]{1,2})時間$")
LATEST_LABEL = "最新話から"
ELLIPSIS_LABEL = "..."


@dataclass(frozen=True, slots=True)
class YounganimalEpisodeIdentity:
    """An episode identity that remains scoped to its canonical work."""

    work_id: str
    episode_id: str

    @property
    def external_id(self) -> str:
        return f"{self.work_id}:{self.episode_id}"


@dataclass(frozen=True, slots=True)
class YounganimalEpisodeUrl:
    episode_id: str


@dataclass(frozen=True, slots=True)
class YounganimalAccessObservation:
    raw_labels: tuple[str, ...]
    access_mode: str
    access_granted_until: datetime | None = None
    access_granted_until_observed: bool = False


@dataclass(frozen=True, slots=True)
class YounganimalRange:
    page_number: int
    start_position: int
    end_position: int
    url: str
    path: str

    @property
    def label(self) -> str:
        return f"{self.start_position}-{self.end_position}"


@dataclass(frozen=True, slots=True)
class YounganimalListingRow:
    identity: YounganimalEpisodeIdentity
    title: str
    access: YounganimalAccessObservation
    global_position: int


@dataclass(frozen=True, slots=True)
class YounganimalNativeEpisodeAccess:
    """Reduced exact-identity access state from a natural series response."""

    episode_id: str
    access_type: str | None
    has_access: bool | None
    remaining_seconds: int | None
    requested_at: datetime
    remaining_seconds_state: str = "missing"


@dataclass(frozen=True, slots=True)
class YounganimalSeriesAccessSnapshot:
    work_id: str
    rows: tuple[YounganimalNativeEpisodeAccess, ...]


@dataclass(frozen=True, slots=True)
class _NavigationAttempt:
    response: Response | None
    timeout_error: PlaywrightTimeoutError | None
    exact_main_document_200: bool
    main_frame_document_requests: tuple[str, ...]
    matching_document_responses: tuple[tuple[str, int], ...]


def _strict_site_url(url: str, pattern: re.Pattern[str]) -> re.Match[str] | None:
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


def parse_younganimal_episode_url(url: str) -> YounganimalEpisodeUrl | None:
    match = _strict_site_url(url, EPISODE_PATH)
    return YounganimalEpisodeUrl(match.group("episode_id")) if match else None


def canonical_younganimal_episode_url(url: str) -> str:
    identity = parse_younganimal_episode_url(url)
    if identity is None:
        raise ValueError("Not a supported Younganimal episode URL")
    return f"https://younganimal.com/episodes/{identity.episode_id}"


def parse_younganimal_work_url(url: str) -> str | None:
    match = _strict_site_url(url, WORK_PATH)
    return match.group("work_id") if match else None


def classify_younganimal_access(
    raw_labels: Sequence[str],
    *,
    observed_at: datetime | None = None,
) -> YounganimalAccessObservation:
    """Recognize exact free labels and the observed rental countdown only."""

    labels = tuple(raw_labels)
    if labels == (FREE_LABEL,):
        return YounganimalAccessObservation(labels, "free", access_granted_until_observed=True)
    match = RENTAL_LABEL.fullmatch(labels[0]) if len(labels) == 1 else None
    if match is not None:
        days, hours = int(match["days"]), int(match["hours"])
        remaining = timedelta(days=days, hours=hours) - timedelta(hours=1)
        if days <= 14 and hours <= 23 and remaining > timedelta():
            current = observed_at if observed_at is not None else datetime.now(JST)
            if current.tzinfo is None or current.utcoffset() is None:
                raise ValueError("Younganimal rental observation requires an aware timestamp")
            return YounganimalAccessObservation(
                labels, "paid", current + remaining, access_granted_until_observed=True
            )
    return YounganimalAccessObservation(labels, "unknown")


def _parse_series_access_snapshot(
    payload: object, *, requested_at: datetime
) -> YounganimalSeriesAccessSnapshot | None:
    """Parse only the live-observed work-bound aggregate access shape."""

    if requested_at.tzinfo is None or requested_at.utcoffset() is None:
        return None
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
        or len(raw_rows) > MAX_LISTING_ROWS
    ):
        return None

    rows: list[YounganimalNativeEpisodeAccess] = []
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        episode_id = raw.get("episodeId")
        if not isinstance(episode_id, str) or re.fullmatch(r"[0-9a-f]{13}", episode_id) is None:
            continue
        access_type = raw.get("accessType")
        if not isinstance(access_type, str) or not access_type or len(access_type) > 64:
            access_type = None
        has_access = raw.get("hasAccess")
        if type(has_access) is not bool:
            has_access = None
        has_remaining = "timeRemainingInSeconds" in raw
        raw_remaining = raw.get("timeRemainingInSeconds")
        remaining_malformed = has_remaining and raw_remaining is not None and (
            type(raw_remaining) is not int
            or raw_remaining < 0
            or raw_remaining > 9_007_199_254_740_991
        )
        remaining = raw_remaining if type(raw_remaining) is int and not remaining_malformed else None
        if not has_remaining:
            remaining_state = "missing"
            remaining = None
        elif raw_remaining is None:
            remaining_state = "null"
            remaining = None
        elif remaining_malformed:
            remaining_state = "malformed"
            remaining = None
        else:
            remaining_state = "valid"
        if remaining_malformed:
            remaining = None
        rows.append(
            YounganimalNativeEpisodeAccess(
                episode_id=episode_id,
                access_type=access_type,
                has_access=has_access,
                remaining_seconds=remaining,
                remaining_seconds_state=remaining_state,
                requested_at=requested_at,
            )
        )
    return YounganimalSeriesAccessSnapshot(work_id=work_id, rows=tuple(rows))


def _native_endpoint_url(url: str, *, path: str) -> bool:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme.lower() == "https"
        and (parsed.hostname or "").lower() == "younganimal.com"
        and parsed.username is None
        and parsed.password is None
        and port in (None, 443)
        and parsed.path == path
    )


def _native_request_matches_work(url: str, *, work_id: str) -> bool:
    try:
        query = parse_qsl(urlsplit(url).query, keep_blank_values=True)
    except ValueError:
        return False
    work_keys = {"seriesid", "workid"}
    explicit_ids = [
        value
        for key, value in query
        if key.casefold().replace("_", "") in work_keys
    ]
    return all(value == work_id for value in explicit_ids)


class _YounganimalNativeAccessObserver:
    """Observe natural listing GETs without issuing any site request."""

    def __init__(self, *, expected_work_id: str) -> None:
        self._expected_work_id = expected_work_id
        self._page: Page | None = None
        self._request_starts: list[tuple[Request, str, datetime, bool]] = []
        self._tasks: list[asyncio.Task[None]] = []
        self.snapshots: list[YounganimalSeriesAccessSnapshot] = []
        self.auth_results: list[bool] = []
        self.complete = True
        self.overflow = False
        self._request_listener = self._on_request
        self._response_listener = self._on_response

    @property
    def listing_authenticated(self) -> bool:
        return bool(self.auth_results) and self.complete and all(self.auth_results)

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
        relevant = method == "GET" and (
            _native_endpoint_url(url, path="/api/series/access")
            or _native_endpoint_url(url, path="/api/auth/session")
        )
        if not relevant:
            return
        if len(self._request_starts) >= MAX_NATIVE_ACCESS_REQUESTS:
            self.overflow = True
            self.complete = False
            return
        self._request_starts.append((request, url, datetime.now(UTC), False))

    def _on_response(self, response: Response) -> None:
        try:
            url = response.url
            request = response.request
            method = request.method
        except (AttributeError, PlaywrightError):
            return
        if method != "GET" or not (
            _native_endpoint_url(url, path="/api/series/access")
            or _native_endpoint_url(url, path="/api/auth/session")
        ):
            return
        matching_index = next(
            (
                index
                for index in range(len(self._request_starts) - 1, -1, -1)
                if not self._request_starts[index][3]
                and self._request_starts[index][0] is request
            ),
            None,
        )
        if matching_index is None:
            self.complete = False
            return
        original, request_url, requested_at, _used = self._request_starts[matching_index]
        self._request_starts[matching_index] = (original, request_url, requested_at, True)
        if urlsplit(url).path == "/api/series/access" and not _native_request_matches_work(
            request_url, work_id=self._expected_work_id
        ):
            self.complete = False
            return
        self._tasks.append(
            asyncio.create_task(
                self._capture(response, requested_at=requested_at, path=urlsplit(url).path)
            )
        )

    async def _capture(self, response: Response, *, requested_at: datetime, path: str) -> None:
        try:
            if response.status != 200:
                self.complete = False
                return
            body = await asyncio.wait_for(
                response.body(), timeout=NATIVE_ACCESS_OBSERVATION_TIMEOUT_SECONDS
            )
            if len(body) > MAX_NATIVE_RESPONSE_BYTES:
                self.complete = False
                return
            payload = json.loads(body)
        except (PlaywrightError, TimeoutError, TypeError, ValueError):
            self.complete = False
            return
        if path == "/api/auth/session":
            if not isinstance(payload, dict):
                self.complete = False
                return
            user = payload.get("user")
            self.auth_results.append(type(user) is int and user > 0)
            return
        snapshot = _parse_series_access_snapshot(payload, requested_at=requested_at)
        if snapshot is None:
            self.complete = False
            return
        self.snapshots.append(snapshot)

    async def finish(self) -> tuple[YounganimalSeriesAccessSnapshot, ...]:
        self._detach()
        pending = [task for task in self._tasks if not task.done()]
        if pending:
            done, pending = await asyncio.wait(
                pending, timeout=NATIVE_ACCESS_OBSERVATION_TIMEOUT_SECONDS
            )
            if pending:
                self.complete = False
                for task in pending:
                    task.cancel()
                done_after_cancel, _still_pending = await asyncio.wait(pending, timeout=1.0)
                for task in done_after_cancel:
                    if not task.cancelled() and task.exception() is not None:
                        self.complete = False
                for task in _still_pending:
                    task.add_done_callback(_consume_task_result)
            for task in done:
                if task.exception() is not None:
                    self.complete = False
        for task in self._tasks:
            if task.cancelled():
                self.complete = False
            elif not task.done():
                self.complete = False
                task.add_done_callback(_consume_task_result)
            elif task.exception() is not None:
                self.complete = False
        if self.overflow or any(not used for _request, _url, _at, used in self._request_starts):
            self.complete = False
        return tuple(self.snapshots)

    async def close(self) -> None:
        self._detach()
        pending = [task for task in self._tasks if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            done, _still_pending = await asyncio.wait(pending, timeout=1.0)
            for task in done:
                if not task.cancelled() and task.exception() is not None:
                    self.complete = False
            for task in _still_pending:
                task.add_done_callback(_consume_task_result)

    def _detach(self) -> None:
        if self._page is None:
            return
        try:
            self._page.remove_listener("request", self._request_listener)
            self._page.remove_listener("response", self._response_listener)
        except PlaywrightError:
            pass
        self._page = None


def _consume_task_result(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    task.exception()


def _latest_native_access_by_episode(
    snapshots: Sequence[YounganimalSeriesAccessSnapshot], *, work_id: str
) -> dict[str, YounganimalNativeEpisodeAccess | None]:
    latest: dict[str, tuple[datetime, YounganimalNativeEpisodeAccess | None]] = {}
    for snapshot in snapshots:
        if snapshot.work_id != work_id:
            continue
        rows_by_episode: dict[str, list[YounganimalNativeEpisodeAccess]] = {}
        for row in snapshot.rows:
            rows_by_episode.setdefault(row.episode_id, []).append(row)
        for episode_id, rows in rows_by_episode.items():
            requested_at = rows[0].requested_at
            candidate = rows[0] if len(rows) == 1 else None
            previous = latest.get(episode_id)
            if previous is None or requested_at > previous[0]:
                latest[episode_id] = (requested_at, candidate)
            elif requested_at == previous[0] and candidate != previous[1]:
                latest[episode_id] = (requested_at, None)
    return {episode_id: row for episode_id, (_at, row) in latest.items()}


def _native_grant_until(
    native: YounganimalNativeEpisodeAccess, *, now: datetime
) -> datetime | None:
    seconds = native.remaining_seconds
    if type(seconds) is not int or seconds <= 0:
        return None
    try:
        expires_at = native.requested_at + timedelta(seconds=seconds - 1)
    except (OverflowError, ValueError):
        return None
    return expires_at if expires_at > now else None


def _apply_native_access(
    rows: Sequence[YounganimalListingRow],
    *,
    native_access: dict[str, YounganimalNativeEpisodeAccess | None],
    listing_authenticated: bool,
    now: datetime | None = None,
) -> list[YounganimalListingRow]:
    """Join exact work-bound native rows; unknown/ambiguous rows preserve grants."""

    current = now if now is not None else datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("Younganimal native access join requires an aware timestamp")
    updated: list[YounganimalListingRow] = []
    for row in rows:
        native = native_access.get(row.identity.episode_id)
        access = row.access
        if (
            listing_authenticated is not True
            or native is None
            or native.access_type != "waitAndFree"
            or native.has_access is None
        ):
            updated.append(row)
            continue

        if native.remaining_seconds_state == "malformed":
            updated.append(row)
            continue

        # Exact free and current rental labels keep their existing precedence.
        if access.access_mode == "free":
            if native.has_access is False:
                access = replace(access, access_granted_until=None, access_granted_until_observed=True)
            updated.append(replace(row, access=access))
            continue
        if access.access_mode == "paid" and access.access_granted_until is not None:
            if native.has_access is True:
                native_until = _native_grant_until(native, now=current)
                if native_until is not None:
                    access = replace(
                        access,
                        access_granted_until=min(access.access_granted_until, native_until),
                        access_granted_until_observed=True,
                    )
            updated.append(replace(row, access=access))
            continue

        if native.has_access is False:
            if native.remaining_seconds_state == "missing" or (
                native.remaining_seconds_state == "valid"
                and native.remaining_seconds == 0
            ):
                access = replace(
                    access,
                    access_mode="quota",
                    access_granted_until=None,
                    access_granted_until_observed=True,
                )
            else:
                access = replace(access, access_mode="unknown")
        elif native.remaining_seconds_state != "valid" or native.remaining_seconds == 0:
            # A true access flag with a zero timer is contradictory; preserve
            # prior grant metadata and do not treat it as a new ticket.
            access = replace(access, access_mode="unknown")
        else:
            native_until = _native_grant_until(native, now=current)
            if native_until is not None:
                access = replace(
                    access,
                    access_mode="quota",
                    access_granted_until=native_until,
                    access_granted_until_observed=True,
                )
            else:
                # Active access without a valid timer is not a spend candidate,
                # and does not clear an older observed grant timestamp.
                access = replace(access, access_mode="unknown")
        updated.append(replace(row, access=access))
    return updated


def _parse_range_route(url: str, *, expected_work_id: str) -> tuple[int, str] | None:
    match = _strict_site_url(url, RANGE_PATH)
    if match is None or match.group("work_id") != expected_work_id:
        return None
    return int(match.group("page_number")), urlsplit(url).path


def _parse_range_links(
    entries: Sequence[dict[str, object]], *, work_id: str
) -> tuple[YounganimalRange, ...]:
    """Validate observed controls and each first-party numeric route."""

    entries = _numeric_range_entries(entries, work_id=work_id)

    if not entries or len(entries) > MAX_RANGE_PAGES:
        raise DiscoveryIncompleteError("Younganimal declared range count is missing or excessive")
    parsed: list[tuple[int, int, int, str, str]] = []
    for index, entry in enumerate(entries):
        label = entry.get("label")
        href = entry.get("href")
        if not isinstance(label, str) or not isinstance(href, str):
            raise DiscoveryIncompleteError(f"Younganimal range link {index} is incomplete")
        match = RANGE_LABEL.fullmatch(label)
        if match is None:
            raise DiscoveryIncompleteError(
                f"Younganimal range selector has an unexpected control label at entry {index}: {label[:48]!r}"
            )
        route = _parse_range_route(href, expected_work_id=work_id)
        if route is None:
            parsed_url = urlsplit(href)
            raise DiscoveryIncompleteError(
                "Younganimal numeric range route is invalid "
                f"(host={parsed_url.hostname!r}, path={parsed_url.path!r}, "
                f"query={bool(parsed_url.query)}, fragment={bool(parsed_url.fragment)})"
            )
        parsed.append((route[0], int(match.group("start")), int(match.group("end")), label, route[1]))

    if len({entry[0] for entry in parsed}) != len(parsed):
        raise DiscoveryIncompleteError("Younganimal ranges repeat a route")
    if len({entry[3] for entry in parsed}) != len(parsed):
        raise DiscoveryIncompleteError("Younganimal ranges repeat a label")

    ranges: list[YounganimalRange] = []
    expected_start = 1
    for expected_page, (page_number, start, end, label, path) in enumerate(parsed, start=1):
        if (
            page_number != expected_page
            or start != expected_start
            or end < start
            or label != f"{start}-{end}"
        ):
            raise DiscoveryIncompleteError(
                "Younganimal ranges are not contiguous, oldest-first, and canonical"
            )
        row_count = end - start + 1
        if row_count > RANGE_PAGE_SIZE:
            raise DiscoveryIncompleteError("Younganimal range exceeds the observed page size")
        if expected_page < len(parsed) and row_count != RANGE_PAGE_SIZE:
            raise DiscoveryIncompleteError("Younganimal nonfinal range is not a full page")
        expected_path = f"/series/{work_id}/{expected_page}"
        if path != expected_path:
            raise DiscoveryIncompleteError("Younganimal range route does not match its label")
        ranges.append(
            YounganimalRange(
                page_number=expected_page,
                start_position=start,
                end_position=end,
                url=f"https://younganimal.com{path}",
                path=path,
            )
        )
        expected_start = end + 1
    if expected_start - 1 > MAX_LISTING_ROWS:
        raise DiscoveryIncompleteError("Younganimal listing exceeds the bounded row guard")
    return tuple(ranges)


def _numeric_range_entries(
    entries: Sequence[dict[str, object]], *, work_id: str
) -> list[dict[str, object]]:
    """Remove only the observed latest and optional href-less ellipsis controls."""

    numeric: list[dict[str, object]] = []
    latest_count = 0
    ellipsis_count = 0
    latest_href = f"https://younganimal.com/series/{work_id}/new"
    for index, entry in enumerate(entries):
        label = entry.get("label")
        href = entry.get("href")
        if not isinstance(label, str):
            raise DiscoveryIncompleteError(f"Younganimal range link {index} is incomplete")
        if label == LATEST_LABEL:
            if href != latest_href:
                raise DiscoveryIncompleteError("Younganimal latest control has an unknown route")
            latest_count += 1
            continue
        if label == ELLIPSIS_LABEL:
            if href != "" or entry.get("raw_href") is not None:
                raise DiscoveryIncompleteError("Younganimal ellipsis control has an unexpected route")
            ellipsis_count += 1
            continue
        numeric.append(entry)
    if latest_count != 1 or ellipsis_count > 1:
        raise DiscoveryIncompleteError("Younganimal listing controls are missing or ambiguous")
    return numeric


def _validate_page_ranges(
    entries: Sequence[dict[str, object]],
    *,
    work_id: str,
    ranges: tuple[YounganimalRange, ...],
    selected: YounganimalRange,
) -> None:
    """Require the complete same-work range map on every page.

    The observed UI rewrites the currently open page's range link to the
    canonical series route. That single alias is allowed only for the current
    range; all remaining links must keep their declared routes.
    """

    numeric_entries = _numeric_range_entries(entries, work_id=work_id)
    if len(numeric_entries) != len(ranges):
        raise DiscoveryIncompleteError("Younganimal range set changed during traversal")
    normalized: list[dict[str, object]] = []
    aliases = 0
    for index, (entry, expected) in enumerate(zip(numeric_entries, ranges, strict=True), start=1):
        label = entry.get("label")
        href = entry.get("href")
        if label != expected.label or not isinstance(href, str):
            raise DiscoveryIncompleteError("Younganimal range label/order changed during traversal")
        route = _parse_range_route(href, expected_work_id=work_id)
        if route is None:
            canonical_work_url = f"https://younganimal.com/series/{work_id}"
            if href == canonical_work_url and index == selected.page_number:
                aliases += 1
                normalized.append({"label": label, "href": expected.url})
                continue
            raise DiscoveryIncompleteError("Younganimal range route changed work or page scope")
        if route[0] != expected.page_number or route[1] != expected.path:
            raise DiscoveryIncompleteError("Younganimal range route no longer matches its label")
        normalized.append({"label": label, "href": href})
    if aliases > 1:
        raise DiscoveryIncompleteError("Younganimal selected range alias is ambiguous")
    latest_control = {
        "label": LATEST_LABEL,
        "href": f"https://younganimal.com/series/{work_id}/new",
    }
    if _parse_range_links([latest_control, *normalized], work_id=work_id) != ranges:
        raise DiscoveryIncompleteError("Younganimal range map changed during traversal")


async def _guard_checkpoint(guard: AccessGuard, page: Page) -> None:
    try:
        await asyncio.wait_for(guard.check_page(page), timeout=OBSERVATION_TIMEOUT_SECONDS)
    except AccessStopError as exc:
        raise DiscoveryIncompleteError(
            f"Younganimal Discovery stopped by the access guard: {exc.reason}"
        ) from exc
    except TimeoutError as exc:
        path = urlsplit(page.url).path
        raise DiscoveryIncompleteError(
            f"Younganimal access check exceeded its time limit at {path}"
        ) from exc


def _consume_cleanup_result(task: asyncio.Task[None]) -> None:
    try:
        task.exception()
    except asyncio.CancelledError:
        pass


async def _close_guard_bounded(guard: AccessGuard) -> None:
    """Keep site-owned AccessGuard cleanup finite, including during cancellation."""

    task = asyncio.create_task(guard.close())
    try:
        done, _pending = await asyncio.wait(
            {task}, timeout=GUARD_CLEANUP_TIMEOUT_SECONDS
        )
    except asyncio.CancelledError:
        task.cancel()
        task.add_done_callback(_consume_cleanup_result)
        raise
    if not done:
        task.cancel()
        task.add_done_callback(_consume_cleanup_result)
        return
    _consume_cleanup_result(task)


async def _goto_once(page: Page, url: str) -> _NavigationAttempt:
    """Capture bounded, attempt-local proof for a possible DCL timeout retry."""

    main_frame = page.main_frame
    navigation_requests: list[Request] = []
    navigation_responses: list[tuple[Request, str, int]] = []
    observation_failed = False
    overflow = False

    def on_request(request: Request) -> None:
        nonlocal observation_failed, overflow
        try:
            if (
                request.resource_type != "document"
                or not request.is_navigation_request()
                or request.frame is not main_frame
            ):
                return
            if len(navigation_requests) >= MAX_NAVIGATION_EVIDENCE_REQUESTS:
                overflow = True
                return
            navigation_requests.append(request)
        except PlaywrightError:
            observation_failed = True

    def on_response(response: Response) -> None:
        nonlocal observation_failed, overflow
        try:
            request = response.request
            if any(request is candidate for candidate in navigation_requests):
                if len(navigation_responses) >= MAX_NAVIGATION_EVIDENCE_REQUESTS:
                    overflow = True
                    return
                navigation_responses.append((request, response.url, response.status))
        except PlaywrightError:
            observation_failed = True

    page.on("request", on_request)
    page.on("response", on_response)
    response: Response | None = None
    timeout_error: PlaywrightTimeoutError | None = None
    try:
        response = await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=NAVIGATION_TIMEOUT_MS,
        )
    except PlaywrightTimeoutError as exc:
        timeout_error = exc
    finally:
        page.remove_listener("request", on_request)
        page.remove_listener("response", on_response)

    exact_main_document_200 = False
    if (
        timeout_error is not None
        and not observation_failed
        and not overflow
        and len(navigation_requests) == 1
    ):
        request = navigation_requests[0]
        matching_responses = [
            (response_url, status)
            for observed_request, response_url, status in navigation_responses
            if observed_request is request
        ]
        exact_main_document_200 = (
            request.url == url
            and len(matching_responses) == 1
            and matching_responses[0] == (url, 200)
        )

    main_frame_document_requests = tuple(request.url for request in navigation_requests)
    matching_document_responses = tuple(
        (response_url, status)
        for request, response_url, status in navigation_responses
        if any(request is candidate for candidate in navigation_requests)
    )
    return _NavigationAttempt(
        response,
        timeout_error,
        exact_main_document_200,
        main_frame_document_requests,
        matching_document_responses,
    )


async def _navigate(
    page: Page,
    url: str,
    guard: AccessGuard,
    *,
    retry_budget_remaining: int,
) -> int:
    """Navigate with at most one retry for a proven current-attempt DCL timeout.

    Return the number of retries used so the whole-work caller can enforce its
    separate two-retry budget.
    """

    if not 0 <= retry_budget_remaining <= MAX_WORK_NAVIGATION_RETRIES:
        raise ValueError("Younganimal navigation retry budget is out of range")

    retries_used = 0
    attempt = await _goto_once(page, url)
    while attempt.timeout_error is not None:
        # A timeout is only retryable after the ordinary guard checkpoint and
        # positive evidence tied to this exact Page.goto attempt.
        await _guard_checkpoint(guard, page)
        retryable = (
            attempt.exact_main_document_200
            and page.url == url
            and retries_used < MAX_NAVIGATION_RETRIES
            and retries_used < retry_budget_remaining
        )
        if not retryable:
            raise DiscoveryIncompleteError(
                "Younganimal page navigation timed out without retry-eligible HTTP 200 proof"
            ) from attempt.timeout_error

        await page.wait_for_timeout(NAVIGATION_RETRY_BACKOFF_MS)
        await _guard_checkpoint(guard, page)
        if page.url != url:
            raise DiscoveryIncompleteError(
                "Younganimal navigation route changed before its bounded retry"
            ) from attempt.timeout_error
        retries_used += 1
        attempt = await _goto_once(page, url)

    await _guard_checkpoint(guard, page)
    if attempt.response is None or attempt.response.status != 200:
        raise DiscoveryIncompleteError("Younganimal page did not return HTTP 200")
    return retries_used


async def _pace_before_range_navigation(page: Page, guard: AccessGuard) -> None:
    """Wait between listing requests, including canonical root -> first range."""

    await page.wait_for_timeout(RANGE_PACING_MS)
    await _guard_checkpoint(guard, page)


async def _wait_for_series_listing(page: Page, guard: AccessGuard) -> None:
    try:
        await page.locator(LISTING_SELECTOR).wait_for(state="visible", timeout=DOM_TIMEOUT_MS)
        await page.wait_for_function(
            """() => {
              const mains = [...document.querySelectorAll('.series-eplist-main')];
              const headings = [...document.querySelectorAll('h1')].filter(node =>
                (node.innerText || '').trim());
              const rangeAnchors = mains.length === 1
                ? [...mains[0].querySelectorAll('a.series-sort-link')]
                : [];
              return mains.length === 1 && headings.length === 1 && rangeAnchors.length > 0;
            }""",
            timeout=DOM_TIMEOUT_MS,
        )
    except (PlaywrightError, TimeoutError) as exc:
        await _guard_checkpoint(guard, page)
        raise DiscoveryIncompleteError("Younganimal public work listing did not become ready") from exc
    await _guard_checkpoint(guard, page)


async def _read_series_title(page: Page) -> str:
    try:
        titles = await asyncio.wait_for(
            page.locator("h1").evaluate_all(
                "nodes => nodes.map(node => (node.innerText || '').replace(/\\s+/g, ' ').trim()).filter(Boolean)"
            ),
            timeout=OBSERVATION_TIMEOUT_SECONDS,
        )
    except (PlaywrightError, TimeoutError) as exc:
        raise DiscoveryIncompleteError("Younganimal work title could not be read") from exc
    if not isinstance(titles, list) or len(titles) != 1 or not isinstance(titles[0], str):
        raise DiscoveryIncompleteError("Younganimal work title is missing or ambiguous")
    return titles[0]


async def _read_range_entries(page: Page) -> list[dict[str, object]]:
    try:
        entries = await asyncio.wait_for(
            page.locator(RANGE_LINK_SELECTOR).evaluate_all(
                """anchors => anchors.map(anchor => ({
                  label: (anchor.innerText || '').replace(/\\s+/g, ' ').trim(),
                  href: anchor.href,
                  raw_href: anchor.getAttribute('href')
                }))"""
            ),
            timeout=OBSERVATION_TIMEOUT_SECONDS,
        )
    except (PlaywrightError, TimeoutError) as exc:
        raise DiscoveryIncompleteError("Younganimal range links could not be read") from exc
    if not isinstance(entries, list) or not entries:
        raise DiscoveryIncompleteError("Younganimal declared range links are missing")
    return entries


async def _read_range_rows(
    page: Page, *, work_id: str, first_position: int
) -> list[YounganimalListingRow]:
    # Account rows mount asynchronously, after the public list is ready.
    try:
        await page.wait_for_function(
            """() => [...document.querySelectorAll('.series-eplist[data-e2e="epListUser"]')]
              .every(root => !root.classList.contains('mode-loading'))""",
            timeout=DOM_TIMEOUT_MS,
        )
    except (PlaywrightError, TimeoutError) as exc:
        raise DiscoveryIncompleteError("Younganimal user listing did not settle") from exc
    observed_at = datetime.now(JST)
    script = r"""() => {
      const mains = [...document.querySelectorAll('.series-eplist-main')];
      const main = mains.length === 1 ? mains[0] : null;
      const roots = main ? [...main.querySelectorAll('.series-eplist')] : [];
      const pub = roots.filter(node => node.dataset.e2e === 'epList');
      const user = roots.filter(node => node.dataset.e2e === 'epListUser');
      const allRoots = [...document.querySelectorAll('.series-eplist')];
      const publicRoot = pub.length === 1 ? pub[0] : null;
      const publicRows = publicRoot ? [...publicRoot.querySelectorAll('.series-eplist-item')] : [];
      const userRows = user.flatMap(node => [...node.querySelectorAll('.series-eplist-item')]);
      const allRows = [...document.querySelectorAll('.series-eplist-item')];
      const knownRows = allRows.length === publicRows.length + userRows.length &&
        allRows.every(row => publicRows.some(item => item === row) || userRows.some(item => item === row));
      const structureReady = mains.length === 1 && roots.length > 0 && pub.length === 1 &&
        publicRoot.parentElement === main && user.length <= 1 && roots.length === pub.length + user.length &&
        allRoots.length === roots.length && user.every(node => node.parentElement === main && node.classList.contains('mode-user')) &&
        knownRows && user.every(root => !root.classList.contains('mode-loading'));
      const readRow = row => {
        const links = [...row.querySelectorAll('a[href*="/episodes/"]')];
        const titles = [...row.querySelectorAll('.series-eplist-item-h-text')];
        const labels = [...row.querySelectorAll('.series-eplist-item-access-text')];
        return {
          linkCount: links.length,
          href: links.length === 1 ? links[0].href : null,
          titleCount: titles.length,
          title: titles.length === 1 ? (titles[0].innerText || '').replace(/\s+/g, ' ').trim() : null,
          labels: labels.map(node => (node.innerText || '').replace(/\s+/g, ' ').trim())
        };
      };
      return {structureReady, historyRowCount: userRows.length,
        rows: publicRows.map(readRow), userRows: userRows.map(readRow)};
    }"""
    try:
        snapshot = await asyncio.wait_for(page.evaluate(script), timeout=OBSERVATION_TIMEOUT_SECONDS)
    except (PlaywrightError, TimeoutError) as exc:
        raise DiscoveryIncompleteError("Younganimal public episode rows could not be read") from exc
    if not isinstance(snapshot, dict):
        raise DiscoveryIncompleteError("Younganimal public/history listing scope is unknown")
    history_row_count = snapshot.get("historyRowCount")
    if not isinstance(history_row_count, int) or history_row_count < 0:
        raise DiscoveryIncompleteError("Younganimal history row count is unknown")
    if snapshot.get("structureReady") is not True:
        raise DiscoveryIncompleteError("Younganimal public/history listing scope is unknown")
    raw_rows = snapshot.get("rows")
    if not isinstance(raw_rows, list) or not raw_rows:
        raise DiscoveryIncompleteError("Younganimal declared range has no public episode rows")
    user_rows = snapshot.get("userRows")
    if not isinstance(user_rows, list) or len(user_rows) != history_row_count:
        raise DiscoveryIncompleteError("Younganimal user rows are incomplete")
    if len(user_rows) > MAX_LISTING_ROWS:
        raise DiscoveryIncompleteError("Younganimal user listing exceeds its row guard")

    rows: list[YounganimalListingRow] = []
    seen: set[str] = set()
    user_by_id: dict[str, dict[str, object]] = {}
    # Validate account identities before joining; user rows never add positions.
    for index, raw in enumerate(user_rows + raw_rows):
        if (
            not isinstance(raw, dict)
            or raw.get("linkCount") != 1
            or raw.get("titleCount") != 1
            or not isinstance(raw.get("href"), str)
            or not isinstance(raw.get("title"), str)
            or not raw["title"].strip()
            or not isinstance(raw.get("labels"), list)
            or not all(isinstance(label, str) for label in raw["labels"])
        ):
            raise DiscoveryIncompleteError("Younganimal public episode row is incomplete or ambiguous")
        identity = parse_younganimal_episode_url(raw["href"])
        if identity is None or raw["href"] != canonical_younganimal_episode_url(raw["href"]):
            raise DiscoveryIncompleteError("Younganimal public row has an invalid or noncanonical URL")
        if index < len(user_rows):
            if identity.episode_id in user_by_id:
                raise DiscoveryIncompleteError("Younganimal user listing repeats an episode ID")
            user_by_id[identity.episode_id] = raw
            continue
        if identity.episode_id in seen:
            raise DiscoveryIncompleteError("Younganimal range repeats an episode ID")
        seen.add(identity.episode_id)
        access = classify_younganimal_access(raw["labels"], observed_at=observed_at)
        account_row = user_by_id.get(identity.episode_id)
        if account_row is not None:
            if account_row["title"] != raw["title"]:
                raise DiscoveryIncompleteError("Younganimal user/history title conflicts with public identity")
            account_access = classify_younganimal_access(account_row["labels"], observed_at=observed_at)
            if access.access_mode != "free" and account_access.access_granted_until is not None:
                access = account_access
        rows.append(
            YounganimalListingRow(
                identity=YounganimalEpisodeIdentity(work_id, identity.episode_id),
                title=raw["title"].strip(),
                access=access,
                global_position=first_position + index - len(user_rows),
            )
        )
    return rows


def _records_from_rows(
    *,
    rows_oldest_first: Sequence[YounganimalListingRow],
    work_title: str,
    scope: DiscoveryScope | None,
) -> list[DiscoveredRecord]:
    if not rows_oldest_first or len(rows_oldest_first) > MAX_LISTING_ROWS:
        raise DiscoveryIncompleteError("Younganimal listing is empty or exceeds its row guard")
    work_ids = {row.identity.work_id for row in rows_oldest_first}
    ids = [row.identity.episode_id for row in rows_oldest_first]
    if len(work_ids) != 1 or len(set(ids)) != len(ids):
        raise DiscoveryIncompleteError("Younganimal listing has duplicate or mixed-work identities")
    records = [
        DiscoveredRecord(
            item=DiscoveredItem(
                canonical_title=work_title,
                kind="episode",
                order_label=row.title,
            ),
            source=DiscoveredSource(
                external_id=row.identity.external_id,
                url=f"https://younganimal.com/episodes/{row.identity.episode_id}",
                access_mode=row.access.access_mode,
                access_granted_until=row.access.access_granted_until,
                access_granted_until_observed=row.access.access_granted_until_observed,
                available=True,
                global_display_position=row.global_position,
            ),
        )
        for row in rows_oldest_first
    ]
    latest_first = list(reversed(records))
    return _apply_discovery_scope(latest_first, scope=scope, work_id=rows_oldest_first[0].identity.work_id)


def _apply_discovery_scope(
    records: list[DiscoveredRecord], *, scope: DiscoveryScope | None, work_id: str
) -> list[DiscoveredRecord]:
    if scope is None:
        return records
    if scope.from_url is None and scope.through_url is None:
        raise DiscoveryIncompleteError("Younganimal bounded scope has no episode boundary")
    index_by_id = {
        record.source.external_id.partition(":")[2]: index
        for index, record in enumerate(records)
    }
    boundaries: dict[str, int] = {}
    for name, value in (("from", scope.from_url), ("through", scope.through_url)):
        if value is None:
            continue
        identity = parse_younganimal_episode_url(value)
        if identity is None:
            raise DiscoveryIncompleteError(f"Younganimal bounded {name} URL is invalid")
        external_id = f"{work_id}:{identity.episode_id}"
        if not any(record.source.external_id == external_id for record in records):
            raise DiscoveryIncompleteError(f"Younganimal bounded {name} is outside the target work")
        boundaries[name] = index_by_id.get(identity.episode_id, -1)
    start = boundaries.get("from", 0)
    end = boundaries.get("through", len(records) - 1)
    if start < 0 or end < 0 or start > end:
        raise DiscoveryIncompleteError("Younganimal bounded boundaries are missing or reversed")
    return records[start : end + 1]


class YounganimalDiscoveryAdapter(DiscoveryAdapter):
    """Buffer and validate every declared range before yielding any record."""

    supports_bounded_discovery = True

    def incremental_stop_decision(
        self,
        record: DiscoveredRecord,
        previous: DiscoverySourceSnapshot | None,
        target: WatchlistTarget,
    ) -> IncrementalStopDecision:
        # Rental grants can change on old episodes. All ranges are already
        # validated and buffered, so continuing adds no browser navigation.
        return IncrementalStopDecision.CONTINUE

    async def iter_records(
        self, page: Page, target: WatchlistTarget, mode: DiscoveryMode
    ) -> AsyncIterator[DiscoveredRecord]:
        del mode  # Both modes refresh the same fully validated requested scope.
        work_id = parse_younganimal_work_url(target.url)
        work_url = f"https://younganimal.com/series/{work_id}" if work_id else None
        if target.site != "younganimal" or work_url is None or target.url != work_url:
            raise DiscoveryIncompleteError(
                "Younganimal Discovery currently requires the strict canonical series listing URL"
            )
        guard = AccessGuard.from_profile(
            site="younganimal",
            profile=younganimal_access_profile(),
            stop_on_http_403=True,
            stop_on_http_429=True,
            stop_on_challenge=True,
            stop_on_captcha=True,
        )
        guard.start(page)
        native_observer = _YounganimalNativeAccessObserver(expected_work_id=work_id)
        native_observer.attach(page)
        try:
            retry_budget_remaining = MAX_WORK_NAVIGATION_RETRIES
            retries_used = await _navigate(
                page,
                work_url,
                guard,
                retry_budget_remaining=retry_budget_remaining,
            )
            retry_budget_remaining -= retries_used
            if page.url != work_url:
                raise DiscoveryIncompleteError("Younganimal canonical work route changed during navigation")
            await _wait_for_series_listing(page, guard)
            work_title = await _read_series_title(page)
            range_entries = await _read_range_entries(page)
            ranges = _parse_range_links(range_entries, work_id=work_id)

            rows_oldest_first: list[YounganimalListingRow] = []
            all_episode_ids: set[str] = set()
            for episode_range in ranges:
                await _pace_before_range_navigation(page, guard)
                retries_used = await _navigate(
                    page,
                    episode_range.url,
                    guard,
                    retry_budget_remaining=retry_budget_remaining,
                )
                retry_budget_remaining -= retries_used
                expected_page_url = episode_range.url
                if page.url != expected_page_url and not (
                    episode_range.page_number == 1 and page.url == work_url
                ):
                    raise DiscoveryIncompleteError("Younganimal range route redirected unexpectedly")
                await _wait_for_series_listing(page, guard)
                current_work_title = await _read_series_title(page)
                if current_work_title != work_title:
                    raise DiscoveryIncompleteError("Younganimal range belongs to a different work title")
                entries = await _read_range_entries(page)
                _validate_page_ranges(entries, work_id=work_id, ranges=ranges, selected=episode_range)
                page_rows = await _read_range_rows(
                    page,
                    work_id=work_id,
                    first_position=episode_range.start_position,
                )
                expected_count = episode_range.end_position - episode_range.start_position + 1
                if len(page_rows) != expected_count:
                    raise DiscoveryIncompleteError("Younganimal row count disagrees with declared range")
                for row in page_rows:
                    if row.identity.episode_id in all_episode_ids:
                        raise DiscoveryIncompleteError("Younganimal ranges overlap or repeat episode IDs")
                    all_episode_ids.add(row.identity.episode_id)
                rows_oldest_first.extend(page_rows)
                await _guard_checkpoint(guard, page)

            if len(rows_oldest_first) != ranges[-1].end_position:
                raise DiscoveryIncompleteError("Younganimal ranges do not cover their declared total")
            native_snapshots = await native_observer.finish()
            # Native response bodies may settle after the last range checkpoint.
            # Check the guard again before treating the buffered listing as complete.
            await _guard_checkpoint(guard, page)
            if native_observer.complete and all(
                snapshot.work_id == work_id for snapshot in native_snapshots
            ):
                native_access = _latest_native_access_by_episode(
                    native_snapshots, work_id=work_id
                )
                rows_oldest_first = _apply_native_access(
                    rows_oldest_first,
                    native_access=native_access,
                    listing_authenticated=native_observer.listing_authenticated,
                )
            records = _records_from_rows(
                rows_oldest_first=rows_oldest_first,
                work_title=work_title,
                scope=target.discovery_scope,
            )
        except DiscoveryIncompleteError:
            raise
        except AccessStopError as exc:
            raise DiscoveryIncompleteError(
                f"Younganimal Discovery stopped by the access guard: {exc.reason}"
            ) from exc
        except (PlaywrightError, TimeoutError) as exc:
            await _guard_checkpoint(guard, page)
            raise DiscoveryIncompleteError("Younganimal full work listing did not complete") from exc
        finally:
            await native_observer.close()
            await _close_guard_bounded(guard)

        for record in records:
            yield record


__all__ = [
    "YounganimalAccessObservation",
    "YounganimalDiscoveryAdapter",
    "YounganimalEpisodeIdentity",
    "YounganimalEpisodeUrl",
    "YounganimalListingRow",
    "YounganimalRange",
    "_apply_discovery_scope",
    "_close_guard_bounded",
    "_parse_range_links",
    "_records_from_rows",
    "_validate_page_ranges",
    "canonical_younganimal_episode_url",
    "classify_younganimal_access",
    "parse_younganimal_episode_url",
    "parse_younganimal_work_url",
]
