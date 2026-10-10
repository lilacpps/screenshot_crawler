"""Hanayume episode-list Discovery with complete range validation."""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

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
from screenshot_crawler.site_adapters.hanayume.access import hanayume_access_profile
from screenshot_crawler.watchlist.models import DiscoveryScope, WatchlistTarget

ALLOWED_HOSTS = frozenset({"hanayume.com", "www.hanayume.com"})
EPISODE_PATH = re.compile(r"^/episodes/(?P<episode_id>[0-9a-f]{13})/?$")
WORK_PATH = re.compile(r"^/series/(?P<work_id>[0-9a-f]{13})/?$")
RANGE_PATH = re.compile(
    r"^/episodes/(?P<seed_id>[0-9a-f]{13})(?:/(?P<page_number>[1-9][0-9]*))?/?$"
)
RANGE_LABEL = re.compile(r"^(?P<start>[1-9][0-9]*)-(?P<end>[1-9][0-9]*)$")

WORK_LINK_SELECTOR = "#xHeader a.ep-h-main-h-series"
LISTING_SELECTOR = ".series-eplist-wrap"
RANGE_LINK_SELECTOR = f"{LISTING_SELECTOR} a.series-sort-link"
ROW_SELECTOR = f'{LISTING_SELECTOR} .series-eplist-item[data-e2e="eli"]'

NAVIGATION_TIMEOUT_MS = 30_000
DOM_TIMEOUT_MS = 12_000
RANGE_PACING_MS = 350
RANGE_PAGE_SIZE = 30
MAX_RANGE_PAGES = 100
MAX_LISTING_ROWS = RANGE_PAGE_SIZE * MAX_RANGE_PAGES
OBSERVATION_TIMEOUT_SECONDS = 8


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


def classify_hanayume_access(raw_labels: Sequence[str]) -> HanayumeAccessObservation:
    """Classify only exact, unambiguous labels proven by the live listing.

    The raw label remains a helper/diagnostic value. The current Catalog schema
    stores only access_mode, so it is not copied into a title or other field.
    """

    labels = tuple(raw_labels)
    if labels == ("無料",):
        return HanayumeAccessObservation(labels, "free")
    # This label is deliberately retained as UNKNOWN until a user-authorized,
    # authenticated, non-consuming viewer check proves its access semantics.
    if labels == ("今なら無料",):
        return HanayumeAccessObservation(labels, "unknown")
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
              '.series-eplist-wrap .series-eplist-item[data-e2e="eli"]'
            ).length > 0""",
            timeout=DOM_TIMEOUT_MS,
        )
    except (PlaywrightError, TimeoutError) as exc:
        await _guard_checkpoint(guard, page)
        raise DiscoveryIncompleteError("Hanayume episode list did not become ready") from exc
    await _guard_checkpoint(guard, page)


async def _read_work_identity(page: Page) -> tuple[str, str]:
    data = await asyncio.wait_for(
        page.evaluate(
            """() => {
          const header = document.querySelector("#xHeader");
          const links = header
            ? [...header.querySelectorAll("a.ep-h-main-h-series")]
            : [];
          const list = document.querySelector(".series-eplist-wrap");
          const scope = document.querySelector("div.series.mode-ep");
          const link = links.length === 1 ? links[0] : null;
          return {
            link_count: links.length,
            href: link?.href || null,
            title: link?.innerText?.trim() || null,
            header_count: document.querySelectorAll("#xHeader").length,
            list_count: document.querySelectorAll(".series-eplist-wrap").length,
            scope_count: document.querySelectorAll("div.series.mode-ep").length,
            list_in_scope: Boolean(scope && list && scope.contains(list)),
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
        or data.get("list_in_scope") is not True
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
    return work_id, data["title"].strip()


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


async def _read_range_rows(
    page: Page,
    *,
    work_id: str,
    first_position: int,
) -> list[HanayumeListingRow]:
    rows = await asyncio.wait_for(
        page.locator(ROW_SELECTOR).evaluate_all(
            """rows => rows.map((row, index) => {
          const links = [...row.querySelectorAll("a.series-eplist-item-link")];
          const titles = [...row.querySelectorAll(".series-eplist-item-h-text")];
          const badges = [...row.querySelectorAll(".series-eplist-item-access-text")];
          return {
            index,
            link_count: links.length,
            href: links.length === 1 ? links[0].href : null,
            title_count: titles.length,
            title: titles.length === 1 ? titles[0].innerText?.trim() || null : null,
            labels: badges.map(node => node.innerText?.trim() || "")
          };
            })"""
        ),
        timeout=OBSERVATION_TIMEOUT_SECONDS,
    )
    if not isinstance(rows, list) or not rows:
        raise DiscoveryIncompleteError("Hanayume range contains no episode rows")

    parsed_rows: list[HanayumeListingRow] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(rows):
        if (
            not isinstance(raw, dict)
            or raw.get("index") != index
            or raw.get("link_count") != 1
            or raw.get("title_count") != 1
            or not isinstance(raw.get("href"), str)
            or not isinstance(raw.get("title"), str)
            or not raw["title"].strip()
            or not isinstance(raw.get("labels"), list)
            or not all(isinstance(label, str) for label in raw["labels"])
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
                access=classify_hanayume_access(labels),
                global_position=first_position + index,
            )
        )
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

    async def iter_records(
        self,
        page: Page,
        target: WatchlistTarget,
        mode: DiscoveryMode,
    ) -> AsyncIterator[DiscoveredRecord]:
        del mode  # Full and incremental both validate and buffer the whole range set first.
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
        try:
            await _navigation_response(page, canonical_url, guard)
            if page.url != canonical_url:
                raise DiscoveryIncompleteError(
                    "Hanayume seed episode navigation changed its canonical identity"
                )
            await _wait_for_listing(page, guard)
            work_id, work_title = await _read_work_identity(page)
            initial_entries = await _read_range_links(page)
            _validate_initial_latest_marker(initial_entries, seed_id=target_identity.episode_id)
            ranges = _parse_range_links(initial_entries, seed_id=target_identity.episode_id)

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
                current_work_id, current_work_title = await _read_work_identity(page)
                if current_work_id != work_id or current_work_title != work_title:
                    raise DiscoveryIncompleteError(
                        "Hanayume range page belongs to a different work context"
                    )
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
            records = _records_from_rows(
                rows_oldest_first=rows_oldest_first,
                work_title=work_title,
                seed_episode_id=target_identity.episode_id,
                scope=target.discovery_scope,
            )
        except DiscoveryIncompleteError:
            raise
        except AccessStopError as exc:
            raise DiscoveryIncompleteError(
                f"Hanayume Discovery stopped by the access guard: {exc.reason}"
            ) from exc
        except (PlaywrightError, TimeoutError) as exc:
            await _guard_checkpoint(guard, page)
            raise DiscoveryIncompleteError("Hanayume episode listing did not complete") from exc
        finally:
            await guard.close()

        for record in records:
            yield record


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
