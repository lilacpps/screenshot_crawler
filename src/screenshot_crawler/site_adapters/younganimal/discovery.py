"""Younganimal work-scoped Discovery from the site's declared episode ranges."""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page, Request, Response
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from screenshot_crawler.core.access_guard import AccessGuard
from screenshot_crawler.core.errors import AccessStopError
from screenshot_crawler.discovery.base import DiscoveryAdapter
from screenshot_crawler.discovery.models import (
    DiscoveredItem,
    DiscoveredRecord,
    DiscoveredSource,
    DiscoveryMode,
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
RANGE_PACING_MS = 1_000
GUARD_CLEANUP_TIMEOUT_SECONDS = 5
FREE_LABEL = "無料"
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
) -> YounganimalAccessObservation:
    """Only one exact row-scoped `無料` label is a positive free signal."""

    labels = tuple(raw_labels)
    return YounganimalAccessObservation(
        raw_labels=labels,
        access_mode="free" if labels == (FREE_LABEL,) else "unknown",
    )


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
        knownRows;
      const rows = publicRows.map(row => {
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
      });
      return {structureReady, historyRowCount: userRows.length, rows};
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
    if history_row_count:
        raise DiscoveryIncompleteError(
            "Younganimal nonempty user/history rows are unsupported because duplicate identity labels are unverified"
        )
    if snapshot.get("structureReady") is not True:
        raise DiscoveryIncompleteError("Younganimal public/history listing scope is unknown")
    raw_rows = snapshot.get("rows")
    if not isinstance(raw_rows, list) or not raw_rows:
        raise DiscoveryIncompleteError("Younganimal declared range has no public episode rows")

    rows: list[YounganimalListingRow] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_rows):
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
        if identity.episode_id in seen:
            raise DiscoveryIncompleteError("Younganimal range repeats an episode ID")
        seen.add(identity.episode_id)
        rows.append(
            YounganimalListingRow(
                identity=YounganimalEpisodeIdentity(work_id, identity.episode_id),
                title=raw["title"].strip(),
                access=classify_younganimal_access(raw["labels"]),
                global_position=first_position + index,
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

    async def iter_records(
        self, page: Page, target: WatchlistTarget, mode: DiscoveryMode
    ) -> AsyncIterator[DiscoveredRecord]:
        del mode  # Both modes use the same complete-work proof; Service orders incremental stops.
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
