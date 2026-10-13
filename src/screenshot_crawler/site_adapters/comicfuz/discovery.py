"""Anonymous public-list Discovery for ComicFUZ.

The adapter consumes the public chapter metadata rendered by the work page and
cross-checks it against the row DOM before returning any records. It never
opens a chapter and deliberately treats every row without an exact public
``無料`` badge as unknown.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlparse

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
from screenshot_crawler.watchlist.models import DiscoveryScope, WatchlistTarget

SITE_HOST = "comic-fuz.com"
LIST_SELECTOR = 'div[class*="title_detail_chapters__list__"]'
WAIT_TIMEOUT_MS = 15_000
STABILITY_TIMEOUT_MS = 5_000
STABILITY_POLL_MS = 100
STABLE_READS_REQUIRED = 2

_WORK_PATH = re.compile(r"^/manga/(?P<work_id>[0-9]+)$")
_EPISODE_PATH = re.compile(r"^/manga/viewer/(?P<chapter_id>[0-9]+)$")


@dataclass(frozen=True, slots=True)
class ComicFuzWorkParts:
    work_id: str


def _parse_url(url: str, path_pattern: re.Pattern[str]) -> re.Match[str] | None:
    try:
        parsed = urlparse(url)
        if (
            parsed.scheme.lower() != "https"
            or parsed.hostname != SITE_HOST
            or parsed.port is not None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or parsed.params
        ):
            return None
        return path_pattern.fullmatch(parsed.path)
    except ValueError:
        return None


def parse_comicfuz_work_url(url: str) -> ComicFuzWorkParts | None:
    """Parse a ComicFUZ work URL, allowing only the observed decorative hint."""

    match = _parse_url(url, _WORK_PATH)
    if match is None:
        return None
    try:
        query = parse_qsl(urlparse(url).query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return None
    if query and query != [("position", "thumbnail")]:
        return None
    return ComicFuzWorkParts(work_id=match.group("work_id"))


def parse_comicfuz_episode_url(url: str) -> str | None:
    """Parse the observed canonical reader route used for Discovery boundaries."""

    match = _parse_url(url, _EPISODE_PATH)
    if match is None or urlparse(url).query:
        return None
    return match.group("chapter_id")


def _flatten_chapters(page_props: Mapping[str, object]) -> list[tuple[str, str]]:
    groups = page_props.get("chapters")
    if not isinstance(groups, list) or not groups:
        raise DiscoveryIncompleteError("ComicFUZ listing has no chapter groups")

    chapters: list[tuple[str, str]] = []
    for group in groups:
        if not isinstance(group, Mapping):
            raise DiscoveryIncompleteError("ComicFUZ listing has an invalid chapter group")
        rows = group.get("chapters")
        if not isinstance(rows, list) or not rows:
            raise DiscoveryIncompleteError("ComicFUZ listing has an empty or invalid chapter group")
        for row in rows:
            if not isinstance(row, Mapping):
                raise DiscoveryIncompleteError("ComicFUZ listing has an invalid chapter record")
            chapter_id = row.get("chapterId")
            label = row.get("chapterMainName")
            if (
                isinstance(chapter_id, bool)
                or not isinstance(chapter_id, (str, int))
                or not re.fullmatch(r"[0-9]+", str(chapter_id))
                or not isinstance(label, str)
                or not " ".join(label.split())
            ):
                raise DiscoveryIncompleteError("ComicFUZ listing has a malformed chapter identity")
            chapters.append((str(chapter_id), " ".join(label.split())))

    chapter_ids = [chapter_id for chapter_id, _ in chapters]
    if len(chapter_ids) != len(set(chapter_ids)):
        raise DiscoveryIncompleteError("ComicFUZ listing contains duplicate chapter IDs")
    return chapters


class ComicFuzDiscoveryAdapter(DiscoveryAdapter):
    """Reconcile ComicFUZ's current public chapter list into Discovery records."""

    supports_bounded_discovery = True

    async def iter_records(
        self,
        page: Page,
        target: WatchlistTarget,
        mode: DiscoveryMode,
    ) -> AsyncIterator[DiscoveredRecord]:
        del mode  # The service applies its standard latest-first known-streak rule.
        target_parts = parse_comicfuz_work_url(target.url)
        if target_parts is None:
            raise DiscoveryIncompleteError("Watchlist target must be a canonical ComicFUZ work URL")

        try:
            await page.goto(
                target.url,
                wait_until="domcontentloaded",
                timeout=WAIT_TIMEOUT_MS,
            )
            await page.locator("#__NEXT_DATA__").wait_for(
                state="attached",
                timeout=WAIT_TIMEOUT_MS,
            )
            await page.locator(LIST_SELECTOR).wait_for(
                state="visible",
                timeout=WAIT_TIMEOUT_MS,
            )
            await self._validate_page_identity(page, target_parts)
            initial = await self._wait_for_stable_snapshot(page, target_parts)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(STABILITY_POLL_MS)
            after_scroll = await self._snapshot(page, target_parts)
            if after_scroll != initial:
                raise DiscoveryIncompleteError(
                    "ComicFUZ chapter listing changed after scrolling to the end"
                )
            settled = await self._wait_for_stable_snapshot(page, target_parts)
            if settled != initial:
                raise DiscoveryIncompleteError("ComicFUZ chapter listing changed while settling")
            records = self._records_from_snapshot(initial, target_parts)
            if target.discovery_scope is not None:
                records = self._apply_scope(records, target_parts, target.discovery_scope)
            before_emission = await self._snapshot(page, target_parts)
            if before_emission != initial:
                raise DiscoveryIncompleteError(
                    "ComicFUZ page identity or chapter listing changed before emission"
                )
        except DiscoveryIncompleteError:
            raise
        except (PlaywrightError, TimeoutError, ValueError) as exc:
            raise DiscoveryIncompleteError("ComicFUZ public chapter listing did not load") from exc

        # DiscoveryService writes each yielded item immediately. Do not yield
        # until the complete current listing and any requested range validated.
        for record in records:
            yield record

    async def _validate_page_identity(
        self,
        page: Page,
        target_parts: ComicFuzWorkParts,
    ) -> None:
        identity = await page.evaluate(
            r"""() => {
              const canonical = document.querySelector('link[rel="canonical"]')?.href || null;
              const signInLinks = [...document.querySelectorAll('a[href]')]
                .filter(a => {
                  const url = new URL(a.href, location.href);
                  return url.origin === location.origin && url.pathname === '/account/signin';
                })
                .filter(a => {
                  const style = getComputedStyle(a);
                  return style.display !== 'none' && style.visibility !== 'hidden'
                    && a.getClientRects().length > 0;
                }).length;
              const signedInLinks = [...document.querySelectorAll('a[href]')]
                .filter(a => /\/(?:account\/(?:signout|logout)|logout|signout)(?:\/|$)/i
                  .test(new URL(a.href, location.href).pathname))
                .filter(a => {
                  const style = getComputedStyle(a);
                  return style.display !== 'none' && style.visibility !== 'hidden'
                    && a.getClientRects().length > 0;
                }).length;
              return {url: location.href, canonical, signInLinks, signedInLinks};
            }"""
        )
        if not isinstance(identity, Mapping):
            raise DiscoveryIncompleteError("ComicFUZ page identity is unavailable")
        expected_path = f"/manga/{target_parts.work_id}"
        if self._same_work_page(str(identity.get("url") or ""), expected_path) is not True:
            raise DiscoveryIncompleteError("ComicFUZ redirected to a different work or route")
        if self._same_work_page(str(identity.get("canonical") or ""), expected_path) is not True:
            raise DiscoveryIncompleteError(
                "ComicFUZ canonical work identity does not match Watchlist"
            )
        if identity.get("signInLinks") != 1 or identity.get("signedInLinks") != 0:
            raise DiscoveryIncompleteError(
                "ComicFUZ anonymous state could not be positively confirmed"
            )

    @staticmethod
    def _same_work_page(url: str, expected_path: str) -> bool | None:
        try:
            parsed = urlparse(url)
            if (
                parsed.scheme.lower() != "https"
                or parsed.hostname != SITE_HOST
                or parsed.port is not None
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path != expected_path
                or parsed.fragment
                or parsed.params
            ):
                return False
            query = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
            return not query or query == [("position", "thumbnail")]
        except ValueError:
            return None

    async def _wait_for_stable_snapshot(
        self,
        page: Page,
        target_parts: ComicFuzWorkParts,
    ) -> tuple[object, ...]:
        elapsed = 0
        previous: tuple[object, ...] | None = None
        same_count = 0
        while elapsed < STABILITY_TIMEOUT_MS:
            snapshot = await self._snapshot(page, target_parts)
            if snapshot == previous:
                same_count += 1
                if same_count >= STABLE_READS_REQUIRED:
                    return snapshot
            else:
                previous = snapshot
                same_count = 0
            await page.wait_for_timeout(STABILITY_POLL_MS)
            elapsed += STABILITY_POLL_MS
        raise DiscoveryIncompleteError("ComicFUZ chapter listing did not stabilize")

    async def _snapshot(
        self,
        page: Page,
        target_parts: ComicFuzWorkParts,
    ) -> tuple[object, ...]:
        await self._validate_page_identity(page, target_parts)
        listing = page.locator(LIST_SELECTOR)
        if await listing.count() != 1:
            raise DiscoveryIncompleteError("ComicFUZ chapter list container is ambiguous")

        next_data_text = await page.locator("#__NEXT_DATA__").text_content()
        if not next_data_text:
            raise DiscoveryIncompleteError("ComicFUZ first-party chapter data is unavailable")
        try:
            next_data = json.loads(next_data_text)
        except json.JSONDecodeError as exc:
            raise DiscoveryIncompleteError("ComicFUZ first-party chapter data is invalid") from exc
        if not isinstance(next_data, Mapping) or next_data.get("page") != "/manga/[mangaId]":
            raise DiscoveryIncompleteError("ComicFUZ page is not the observed work listing route")
        props = next_data.get("props")
        page_props = props.get("pageProps") if isinstance(props, Mapping) else None
        if not isinstance(page_props, Mapping):
            raise DiscoveryIncompleteError("ComicFUZ first-party work metadata is unavailable")
        chapters = _flatten_chapters(page_props)

        dom = await listing.evaluate(
            """container => {
              const headings = [...container.querySelectorAll('h3[class*="Chapter_chapter__name__"]')];
              const isVisible = (element, stopAt) => {
                if (!element || element.getClientRects().length === 0) return false;
                let node = element;
                while (node) {
                  if (node.hidden) return false;
                  const style = getComputedStyle(node);
                  if (style.display === 'none' || style.visibility === 'hidden'
                      || style.visibility === 'collapse' || Number(style.opacity) === 0) return false;
                  if (node === stopAt) break;
                  node = node.parentElement;
                }
                return node === stopAt;
              };
              const seenRows = new Set();
              const rows = headings.map((heading, index) => {
                const detail = heading.parentElement;
                const row = detail?.parentElement;
                const classes = row ? [...row.classList] : [];
                const chapterRowClass = classes.some(name => /^Chapter_chapter__(?!detail__)[A-Za-z0-9_-]+$/.test(name));
                const headingCount = row?.querySelectorAll('h3[class*="Chapter_chapter__name__"]').length ?? 0;
                const duplicateRow = row ? seenRows.has(row) : true;
                if (row) seenRows.add(row);
                const markers = row ? [...row.querySelectorAll('p[class*="Chapter_chapter__price_free__"]')]
                  .map(marker => ({text: marker.innerText.trim(), visible: isVisible(marker, container)})) : [];
                return {
                  index,
                  label: heading.innerText.trim().replace(/\\s+/g, ' '),
                  chapterRowClass,
                  headingCount,
                  duplicateRow,
                  visible: isVisible(row, container),
                  markers
                };
              });
              const controls = container.querySelectorAll('button,a[href],[role="button"],input[type="button"],input[type="submit"]').length;
              return {rows, controls, title: document.title};
            }"""
        )
        if not isinstance(dom, Mapping) or not isinstance(dom.get("rows"), list):
            raise DiscoveryIncompleteError("ComicFUZ chapter rows are unavailable")
        rows = dom["rows"]
        if not rows or len(rows) != len(chapters):
            raise DiscoveryIncompleteError("ComicFUZ hydration and DOM chapter counts differ")
        if dom.get("controls") != 0:
            raise DiscoveryIncompleteError(
                "ComicFUZ chapter listing has unsupported pagination controls"
            )
        title = " ".join(str(dom.get("title") or "").split())
        if not title:
            raise DiscoveryIncompleteError("ComicFUZ work title is unavailable")

        normalized_rows: list[tuple[str, str]] = []
        access: list[str] = []
        for index, (chapter_id, label) in enumerate(chapters):
            row = rows[index]
            if not isinstance(row, Mapping):
                raise DiscoveryIncompleteError("ComicFUZ DOM chapter row is invalid")
            row_label = row.get("label")
            markers = row.get("markers")
            if (
                row.get("index") != index
                or row.get("chapterRowClass") is not True
                or row.get("headingCount") != 1
                or row.get("duplicateRow") is not False
                or row.get("visible") is not True
                or not isinstance(row_label, str)
                or " ".join(row_label.split()) != label
                or not isinstance(markers, list)
            ):
                raise DiscoveryIncompleteError(
                    "ComicFUZ chapter identity or row-local access evidence is inconsistent"
                )
            if any(not isinstance(marker, Mapping) for marker in markers):
                raise DiscoveryIncompleteError("ComicFUZ free marker structure is invalid")
            visible_markers = [marker for marker in markers if marker.get("visible") is True]
            if len(visible_markers) > 1:
                raise DiscoveryIncompleteError("ComicFUZ has multiple visible free markers")
            if visible_markers and visible_markers[0].get("text") != "無料":
                raise DiscoveryIncompleteError("ComicFUZ free marker is ambiguous")
            normalized_rows.append((chapter_id, label))
            access.append("free" if len(visible_markers) == 1 else "unknown")

        return (
            target_parts.work_id,
            title,
            tuple(normalized_rows),
            tuple(access),
        )

    def _records_from_snapshot(
        self,
        snapshot: tuple[object, ...],
        target_parts: ComicFuzWorkParts,
    ) -> list[DiscoveredRecord]:
        work_id, title, chapters, access = snapshot
        if work_id != target_parts.work_id or not isinstance(title, str):
            raise DiscoveryIncompleteError("ComicFUZ snapshot work identity changed")
        if not isinstance(chapters, tuple) or not isinstance(access, tuple) or not chapters:
            raise DiscoveryIncompleteError("ComicFUZ snapshot has no validated chapters")
        chapter_ids = [
            entry[0] for entry in chapters if isinstance(entry, tuple) and len(entry) == 2
        ]
        if len(chapter_ids) != len(chapters) or len(set(chapter_ids)) != len(chapter_ids):
            raise DiscoveryIncompleteError(
                "ComicFUZ snapshot contains duplicate chapter identities"
            )

        records: list[DiscoveredRecord] = []
        total = len(chapters)
        for index, ((chapter_id, label), observed_access) in enumerate(
            zip(chapters, access, strict=True)
        ):
            records.append(
                DiscoveredRecord(
                    item=DiscoveredItem(
                        canonical_title=title,
                        kind="episode",
                        order_key=None,
                        order_label=label,
                    ),
                    source=DiscoveredSource(
                        external_id=f"{target_parts.work_id}:{chapter_id}",
                        url=f"https://{SITE_HOST}/manga/viewer/{chapter_id}",
                        access_mode=observed_access,
                        free_until=None,
                        available=True,
                        global_display_position=total - index,
                    ),
                )
            )
        return records

    @staticmethod
    def _apply_scope(
        records: list[DiscoveredRecord],
        target_parts: ComicFuzWorkParts,
        scope: DiscoveryScope,
    ) -> list[DiscoveredRecord]:
        if scope.from_url is None and scope.through_url is None:
            raise DiscoveryIncompleteError("ComicFUZ bounded scope has no episode boundary")
        index_by_id = {record.source.external_id: index for index, record in enumerate(records)}
        boundary_indices: dict[str, int] = {}
        for boundary_name, boundary_url in (
            ("from", scope.from_url),
            ("through", scope.through_url),
        ):
            if boundary_url is None:
                continue
            chapter_id = parse_comicfuz_episode_url(boundary_url)
            if chapter_id is None:
                raise DiscoveryIncompleteError(
                    f"ComicFUZ bounded Discovery {boundary_name} URL is invalid"
                )
            external_id = f"{target_parts.work_id}:{chapter_id}"
            boundary_index = index_by_id.get(external_id)
            if boundary_index is None:
                raise DiscoveryIncompleteError(
                    f"ComicFUZ bounded Discovery {boundary_name} episode is not in the listing"
                )
            boundary_indices[boundary_name] = boundary_index

        from_index = boundary_indices.get("from", 0)
        through_index = boundary_indices.get("through", len(records) - 1)
        if from_index > through_index:
            raise DiscoveryIncompleteError("ComicFUZ bounded Discovery boundaries are reversed")
        return records[from_index : through_index + 1]
