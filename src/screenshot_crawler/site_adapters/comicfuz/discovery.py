"""Public-list Discovery for ComicFUZ, independent of login state.

The adapter cross-checks public chapter metadata against the row DOM and emits
access only from complete row-local evidence: exact visible ``無料`` is free,
recognized visible S/G price icons are paid, and a fully joined row with a
confirmed empty price/access region is quota. Hidden, incomplete, conflicting,
or unfamiliar evidence remains unknown. Discovery never opens a chapter.
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
from screenshot_crawler.registration.models import UrlResolution, resolved_url
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


@dataclass(frozen=True, slots=True)
class ComicFuzTargetRowObservation:
    chapter_id: str
    label: str
    access_mode: str
    index: int


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

    registration_hosts = ('comic-fuz.com',)

    def resolve_registration_url(self, url: str) -> UrlResolution:
        from urllib.parse import urlsplit
        if urlsplit(url).query not in ("", "position=thumbnail"):
            return UrlResolution(input_url=url, blockers=("Unsupported metadata or URL; use the canonical Discovery entry and confirm manually",))
        parts = parse_comicfuz_work_url(url)
        if parts is None:
            return UrlResolution(input_url=url, blockers=("Unsupported metadata or URL; use the canonical Discovery entry and confirm manually",))
        return resolved_url(url, f"https://comic-fuz.com/manga/{parts.work_id}", f"comicfuz-work:{parts.work_id}")

    supports_bounded_discovery = True

    async def observe_registration_metadata(self, page, resolution):
        from screenshot_crawler.registration.observation import (
            ObservationUnavailable,
            observation_failure,
            observed_title,
            registration_document,
            require_canonical,
        )
        try:
            async with registration_document(page, resolution.discovery_url):
                await require_canonical(page, resolution.discovery_url)
                data = page.locator("#__NEXT_DATA__")
                if await data.count() != 1:
                    raise ObservationUnavailable("作品ページのnative情報がありません（手動確認可）")
                binding = await data.evaluate("e => {const d=JSON.parse(e.textContent); return [d.page, d.query?.mangaId]}")
                expected = parse_comicfuz_work_url(resolution.discovery_url)
                if binding != ["/manga/[mangaId]", expected.work_id]:
                    from screenshot_crawler.registration.observation import ObservationRejected
                    raise ObservationRejected("作品ページのnative IDが対象作品と一致しません")
                titles = await page.locator('meta[property="og:title"]').evaluate_all("els => els.map(e => e.content)")
                if len(titles) != 1 or titles[0] != await page.title():
                    raise ObservationUnavailable("作品名metadataが一意に一致しません（手動確認可）")
                result = observed_title(resolution, titles[0], resolution.discovery_url)
            return result
        except ObservationUnavailable as exc:
            return observation_failure(resolution, exc)

    async def iter_records(
        self,
        page: Page,
        target: WatchlistTarget,
        mode: DiscoveryMode,
    ) -> AsyncIterator[DiscoveredRecord]:
        self.reset_complete_listing_inventory()
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
            all_records = self._records_from_snapshot(initial, target_parts)
            records = all_records
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
        if mode == "full":
            self.capture_complete_listing_inventory(
                target=target,
                all_records=all_records,
                selected_records=records,
                listing_identity=f"comicfuz-work:{target_parts.work_id}",
            )

    async def _validate_page_identity(
        self,
        page: Page,
        target_parts: ComicFuzWorkParts,
    ) -> None:
        # Header account links change after hydration and do not prove episode
        # access. Row-local UI evidence below classifies each access state.
        identity = await page.evaluate(
            r"""() => {
              const canonical = document.querySelector('link[rel="canonical"]')?.href || null;
              return {url: location.href, canonical};
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
        *,
        only_chapter_id: str | None = None,
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
        selected_indices: list[int] | None = None
        if only_chapter_id is not None:
            selected_indices = [
                index for index, (chapter_id, _label) in enumerate(chapters)
                if chapter_id == only_chapter_id
            ]
            if len(selected_indices) != 1:
                raise DiscoveryIncompleteError(
                    "ComicFUZ target chapter is missing or duplicated in native listing"
                )

        dom = await listing.evaluate(
            """(container, selectedIndex) => {
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
              const knownClass = token => {
                const patterns = [
                  /^Chapter_chapter__row(?:__[A-Za-z0-9_-]+)?$/,
                  /^Chapter_chapter__thumbnail_wrapper__[A-Za-z0-9_-]+$/,
                  /^Chapter_chapter__thumbnail__[A-Za-z0-9_-]+$/,
                  /^Chapter_chapter__thumbnail_overlay__[A-Za-z0-9_-]+$/,
                  /^Chapter_chapter__label__[A-Za-z0-9_-]+$/,
                  /^Chapter_chapter__label_(advance|update)__[A-Za-z0-9_-]+$/,
                  /^Chapter_chapter__detail__[A-Za-z0-9_-]+$/,
                  /^Chapter_chapter__name__[A-Za-z0-9_-]+$/,
                  /^Chapter_chapter__subName__[A-Za-z0-9_-]+$/,
                  /^Chapter_chapter__updateDate__[A-Za-z0-9_-]+$/,
                  /^Chapter_chapter__bottom__[A-Za-z0-9_-]+$/,
                  /^Chapter_chapter__userAction__[A-Za-z0-9_-]+$/,
                  /^Chapter_chapter__userAction_item__[A-Za-z0-9_-]+$/,
                  /^Chapter_chapter__userAction_icon__[A-Za-z0-9_-]+$/,
                  /^Chapter_chapter__userAction_text__[A-Za-z0-9_-]+$/,
                  /^Chapter_chapter__price_free__[A-Za-z0-9_-]+$/,
                  /^Chapter_chapter__price__[A-Za-z0-9_-]+$/,
                  /^Chapter_chapter__price_gold__[A-Za-z0-9_-]+$/
                ];
                return patterns.some(pattern => pattern.test(token));
              };
              const indices = selectedIndex === null
                ? headings.map((_, index) => index) : [selectedIndex];
              const rows = indices.map(index => {
                const heading = headings[index];
                const detail = heading.parentElement;
                const row = detail?.parentElement;
                const classes = row ? [...row.classList] : [];
                const chapterRowClass = classes.some(name => /^Chapter_chapter__(?!detail__)[A-Za-z0-9_-]+$/.test(name));
                const headingCount = row?.querySelectorAll('h3[class*="Chapter_chapter__name__"]').length ?? 0;
                const duplicateRow = row ? seenRows.has(row) : true;
                if (row) seenRows.add(row);
                const markers = row ? [...row.querySelectorAll('p[class*="Chapter_chapter__price_free__"]')]
                  .map(marker => ({text: marker.innerText.trim(), visible: isVisible(marker, container)})) : [];
                const priceNodes = row ? [...row.querySelectorAll('[class*="Chapter_chapter__price"]')] : [];
                const priceSlots = priceNodes.filter(node => node.matches('i[class*="Chapter_chapter__price__"]'));
                const priceEvidence = priceSlots.map(slot => {
                  const images = [...slot.querySelectorAll('img')].map(image => {
                    let path = null;
                    try { path = new URL(image.currentSrc || image.src, location.href).pathname; }
                    catch (_) { /* malformed/unknown price image remains unclassified */ }
                    const kind = image.alt === 'ゴールドメダル' && path === '/assets/manga_detail/gold.svg'
                      ? 'gold'
                      : image.alt === 'シルバーメダル' && path === '/assets/manga_detail/silver.svg'
                        ? 'silver' : 'unknown';
                    return {kind, visible: isVisible(image, container), loaded: image.complete && image.naturalWidth > 0};
                  });
                  return {visible: isVisible(slot, container), images};
                });
                const slotNodes = new Set(priceSlots);
                const unknownPriceNodes = priceNodes.filter(node =>
                  !node.matches('p[class*="Chapter_chapter__price_free__"]')
                  && !slotNodes.has(node)
                  && !priceSlots.some(slot => slot.contains(node))
                ).length;
                const thumbnail = row?.querySelector('div[class*="Chapter_chapter__thumbnail_wrapper__"]');
                const unknownAccessMarkers = row ? [...row.querySelectorAll('*')].filter(node => {
                  if (node.hasAttribute('aria-label') || node.hasAttribute('title') || node.hasAttribute('role')) return true;
                  const style = getComputedStyle(node);
                  if (style.backgroundImage !== 'none'
                      || getComputedStyle(node, '::before').backgroundImage !== 'none'
                      || getComputedStyle(node, '::after').backgroundImage !== 'none') return true;
                  const tokens = [...node.classList];
                  const chapterTokens = tokens.filter(token => token.startsWith('Chapter_chapter__'));
                  if (chapterTokens.some(token => !knownClass(token))) return true;
                  if (node.tagName === 'IMG') {
                    if (thumbnail?.contains(node) && node.matches('img[class*="Chapter_chapter__thumbnail__"]')) return false;
                    if (node.matches('img[class*="Chapter_chapter__userAction_icon__"]')) {
                      let path = null;
                      try { path = new URL(node.currentSrc || node.src, location.href).pathname; } catch (_) {}
                      return !['/assets/manga_detail/comment.svg', '/assets/manga_detail/like.svg'].includes(path);
                    }
                    return !priceSlots.some(slot => slot.contains(node));
                  }
                  if (node.tagName.toLowerCase() === 'svg') return true;
                  if (node.tagName === 'DIV') {
                    return chapterTokens.length === 0;
                  }
                  if (node.tagName === 'P') {
                    return !node.matches('p[class*="Chapter_chapter__subName__"], p[class*="Chapter_chapter__updateDate__"], p[class*="Chapter_chapter__userAction_text__"], p[class*="Chapter_chapter__price_free__"]');
                  }
                  if (node.tagName === 'H3') return !node.matches('h3[class*="Chapter_chapter__name__"]');
                  if (node.tagName === 'I') return !node.matches('i[class*="Chapter_chapter__label__"], i[class*="Chapter_chapter__price__"]');
                  return !['IMG'].includes(node.tagName);
                }).length : 1;
                return {
                  index,
                  label: heading.innerText.trim().replace(/\\s+/g, ' '),
                  chapterRowClass,
                  headingCount,
                  duplicateRow,
                  visible: isVisible(row, container),
                  markers,
                  priceSlotCount: priceSlots.length,
                  priceEvidence,
                  unknownPriceNodes,
                  unknownAccessMarkers
                };
              });
              const controls = container.querySelectorAll('button,a[href],[role="button"],input[type="button"],input[type="submit"]').length;
              return {rows, controls, title: document.title, headingCount: headings.length};
            }""",
            selected_indices[0] if selected_indices is not None else None,
        )
        if not isinstance(dom, Mapping) or not isinstance(dom.get("rows"), list):
            raise DiscoveryIncompleteError("ComicFUZ chapter rows are unavailable")
        rows = dom["rows"]
        expected_rows = 1 if selected_indices is not None else len(chapters)
        if not rows or len(rows) != expected_rows or dom.get("headingCount") != len(chapters):
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
        row_indices = selected_indices if selected_indices is not None else list(range(len(chapters)))
        for row_offset, index in enumerate(row_indices):
            chapter_id, label = chapters[index]
            row = rows[row_offset]
            if not isinstance(row, Mapping):
                raise DiscoveryIncompleteError("ComicFUZ DOM chapter row is invalid")
            row_label = row.get("label")
            markers = row.get("markers")
            price_evidence = row.get("priceEvidence")
            price_slot_count = row.get("priceSlotCount")
            unknown_price_nodes = row.get("unknownPriceNodes")
            unknown_access_markers = row.get("unknownAccessMarkers")
            if (
                row.get("index") != index
                or row.get("chapterRowClass") is not True
                or row.get("headingCount") != 1
                or row.get("duplicateRow") is not False
                or row.get("visible") is not True
                or not isinstance(row_label, str)
                or " ".join(row_label.split()) != label
                or not isinstance(markers, list)
                or not isinstance(price_evidence, list)
                or type(price_slot_count) is not int
                or price_slot_count != len(price_evidence)
                or type(unknown_price_nodes) is not int
                or type(unknown_access_markers) is not int
            ):
                raise DiscoveryIncompleteError(
                    "ComicFUZ chapter identity or row-local access evidence is inconsistent"
                )
            if any(not isinstance(marker, Mapping) for marker in markers):
                raise DiscoveryIncompleteError("ComicFUZ free marker structure is invalid")
            visible_markers = [marker for marker in markers if marker.get("visible") is True]
            if len(markers) > 1 or len(visible_markers) > 1:
                raise DiscoveryIncompleteError("ComicFUZ has multiple visible free markers")
            if visible_markers and visible_markers[0].get("text") != "無料":
                raise DiscoveryIncompleteError("ComicFUZ free marker is ambiguous")
            access_mode = "unknown"
            if unknown_access_markers > 0:
                access_mode = "unknown"
            elif (
                unknown_price_nodes == 0
                and not any(marker.get("visible") is not True for marker in markers)
                and len(visible_markers) == 1
                and price_slot_count == 0
            ):
                access_mode = "free"
            elif (
                not markers
                and price_slot_count == 1
                and unknown_price_nodes == 0
            ):
                slot = price_evidence[0]
                images = slot.get("images") if isinstance(slot, Mapping) else None
                kinds = [image.get("kind") for image in images if isinstance(image, Mapping)] if isinstance(images, list) else []
                if (
                    isinstance(slot, Mapping)
                    and slot.get("visible") is True
                    and isinstance(images, list)
                    and len(images) == len(kinds)
                    and all(image.get("visible") is True and image.get("loaded") is True
                            for image in images if isinstance(image, Mapping))
                    and kinds.count("gold") == 1
                    and kinds.count("silver") <= 1
                    and len(kinds) == kinds.count("gold") + kinds.count("silver")
                ):
                    access_mode = "paid"
            elif (
                not markers
                and price_slot_count == 0
                and unknown_price_nodes == 0
            ):
                access_mode = "quota"
            normalized_rows.append((chapter_id, label))
            access.append(access_mode)

        return (
            target_parts.work_id,
            title,
            tuple(normalized_rows),
            tuple(access),
        )

    async def observe_target_row(
        self,
        page: Page,
        *,
        work_id: str,
        chapter_id: str,
    ) -> ComicFuzTargetRowObservation:
        """Read only the Catalog-selected row from an already-open work listing."""

        if not re.fullmatch(r"[0-9]+", work_id) or not re.fullmatch(r"[0-9]+", chapter_id):
            raise DiscoveryIncompleteError("ComicFUZ target identity is malformed")
        snapshot = await self._snapshot(
            page,
            ComicFuzWorkParts(work_id),
            only_chapter_id=chapter_id,
        )
        found_work, _title, rows, access = snapshot
        if (
            found_work != work_id
            or not isinstance(rows, tuple)
            or len(rows) != 1
            or not isinstance(access, tuple)
            or len(access) != 1
        ):
            raise DiscoveryIncompleteError("ComicFUZ target row snapshot is incomplete")
        row_chapter_id, label = rows[0]
        if row_chapter_id != chapter_id or not isinstance(label, str):
            raise DiscoveryIncompleteError("ComicFUZ target row identity changed")
        native_text = await page.locator("#__NEXT_DATA__").text_content()
        try:
            native_data = json.loads(native_text or "null")
        except json.JSONDecodeError as exc:
            raise DiscoveryIncompleteError("ComicFUZ target native listing is invalid") from exc
        native_props = native_data.get("props") if isinstance(native_data, Mapping) else None
        native_page_props = native_props.get("pageProps") if isinstance(native_props, Mapping) else None
        if not isinstance(native_page_props, Mapping):
            raise DiscoveryIncompleteError("ComicFUZ target native listing is unavailable")
        native_chapters = _flatten_chapters(native_page_props)
        matching_indices = [
            index for index, (native_id, _native_label) in enumerate(native_chapters)
            if native_id == chapter_id
        ]
        if len(matching_indices) != 1:
            raise DiscoveryIncompleteError("ComicFUZ target row position is not unique")
        return ComicFuzTargetRowObservation(
            chapter_id,
            label,
            access[0],
            matching_indices[0],
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
