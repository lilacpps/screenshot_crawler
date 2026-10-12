"""Fail-closed native WebP capture for Kadocomi's observed WEB reader."""

from __future__ import annotations

import asyncio
import base64
import re
from datetime import datetime
from typing import Any

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page, Response

from screenshot_crawler.catalog.service import now_jst
from screenshot_crawler.core.access_guard import AccessProfile
from screenshot_crawler.core.capture import CaptureResult
from screenshot_crawler.core.errors import (
    PageChangeTimeoutError,
    UnknownPageStateError,
    UnsupportedAccessStrategyError,
)
from screenshot_crawler.core.models import AccessStrategy, ContentContext, ContentIdentity
from screenshot_crawler.core.state import PageState
from screenshot_crawler.discovery.models import DiscoveredRecord
from screenshot_crawler.site_adapters.base import SiteAdapter
from screenshot_crawler.site_adapters.kadocomi.access import kadocomi_access_profile
from screenshot_crawler.site_adapters.kadocomi.discovery import (
    KadocomiDiscoveryAdapter,
    canonical_kadocomi_episode_url,
    canonical_kadocomi_work_url,
    parse_kadocomi_episode_url,
)
from screenshot_crawler.site_adapters.kadocomi.native_capture import (
    MAX_NATIVE_BLOB_BYTES,
    MAX_NATIVE_PIXEL_COUNT,
    MAX_NATIVE_TOTAL_PIXEL_COUNT,
    NATIVE_CAPTURE_SCRIPT,
    NATIVE_OBSERVER_INIT_SCRIPT,
    capture_kadocomi_webp,
)
from screenshot_crawler.watchlist.models import WatchlistTarget

SITE_HOST = "comic-walker.com"
INITIALIZE_TIMEOUT_MS = 90_000
NAVIGATION_TIMEOUT_MS = 20_000
VIEWER_READY_TIMEOUT_SECONDS = 35.0
VIEWER_POLL_MS = 150
PAGE_CHANGE_TIMEOUT_SECONDS = 12.0
MAX_CANVAS_SLOTS = 500
_EXTERNAL_ID = re.compile(r"^(?P<work>KC_[0-9]{6}_S):(?P<episode>KC_[0-9]{16}_E)$")
_OG_TITLE_SUFFIX = "\uFF5C\u30AB\u30C9\u30B3\u30DF (\u30B3\u30DF\u30C3\u30AF\u30A6\u30A9\u30FC\u30AB\u30FC)"

_READ_EPISODE_METADATA_SCRIPT = r"""() => {
  const normalize = value => (value || '').replace(/\s+/g, ' ').trim();
  const headings = [...document.querySelectorAll('h1')].filter(node =>
    node.getClientRects().length > 0 && getComputedStyle(node).visibility !== 'hidden');
  const titles = [...document.querySelectorAll('meta[property="og:title"]')]
    .map(node => node.content || '');
  const dialogs = [...document.querySelectorAll('[role="dialog"], dialog')]
    .filter(node => node.getClientRects().length > 0 &&
      getComputedStyle(node).visibility !== 'hidden' && getComputedStyle(node).display !== 'none');
  return {
    headingCount: headings.length,
    heading: headings.length === 1 ? normalize(headings[0].innerText) : null,
    titleCount: titles.length,
    ogTitle: titles.length === 1 ? normalize(titles[0]) : null,
    documentTitle: normalize(document.title),
    visibleDialogCount: dialogs.length
  };
}"""

_NAVIGATION_TARGET_SCRIPT = r"""() => {
  const screens = [...document.querySelectorAll('._mainScreen_191o7_1')];
  if (screens.length !== 1) return {ok: false, reason: 'main_screen_count'};
  const roots = [...screens[0].querySelectorAll('.splide._root_1542n_1')];
  if (roots.length !== 1) return {ok: false, reason: 'reader_root_count'};
  const root = roots[0];
  const slides = [...root.querySelectorAll('.splide__slide')];
  const active = slides.filter(slide => slide.classList.contains('is-active'));
  if (active.length !== 1 || active[0].classList.contains('splide__slide--clone'))
    return {ok: false, reason: 'active_slide'};
  const typedContent = [...active[0].querySelectorAll('[data-type="contents"]')];
  const wrappers = typedContent.filter(node => node.tagName === 'DIV' &&
    [...node.classList].some(name => name.startsWith('_pageCanvasWrapper_')));
  if (wrappers.length !== typedContent.length ||
      wrappers.some(wrapper => {
        const canvases = [...wrapper.querySelectorAll('canvas')];
        return canvases.length !== 1 ||
          ![...canvases[0].classList].some(name => name.startsWith('_root_bx4cr_'));
      }))
    return {ok: false, reason: 'content_wrapper_shape'};
  const rootRect = root.getBoundingClientRect();
  if (rootRect.width <= 0 || rootRect.height <= 0) return {ok: false, reason: 'root_geometry'};
  const covers = [...active[0].querySelectorAll('._cover_bx4cr_11')]
    .filter(node => {
      const rect = node.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0 &&
        getComputedStyle(node).visibility !== 'hidden' &&
        getComputedStyle(node).display !== 'none';
    }).map(node => ({node, rect: node.getBoundingClientRect()}))
    .sort((left, right) => left.rect.left - right.rect.left);
  if (!covers.length) return {ok: false, reason: 'left_overlay_missing'};
  const viewportLeft = Math.max(0, rootRect.left);
  const viewportRight = Math.min(innerWidth, rootRect.right);
  const viewportTop = Math.max(0, rootRect.top);
  const viewportBottom = Math.min(innerHeight, rootRect.bottom);
  const targetY = (viewportTop + viewportBottom) / 2;
  for (const candidate of covers) {
    const left = Math.max(candidate.rect.left, viewportLeft);
    const right = Math.min(candidate.rect.right, viewportRight);
    const top = Math.max(candidate.rect.top, viewportTop);
    const bottom = Math.min(candidate.rect.bottom, viewportBottom);
    if (right <= left || bottom <= top || targetY < top || targetY > bottom) continue;
    const x = left + Math.min(2, (right - left) / 4);
    const y = targetY;
    const hit = document.elementFromPoint(x, y);
    const hitCover = hit && (hit === candidate.node || candidate.node.contains(hit));
    const hitActive = hit && hit.closest('.splide__slide') === active[0];
    if (hitCover && hitActive) return {
      ok: true, x, y, activeIndex: slides.indexOf(active[0]),
      slotCount: wrappers.length
    };
  }
  return {ok: false, reason: 'left_overlay_hit_test_failed'};
}"""


def _snapshot_signature(snapshot: dict[str, Any]) -> tuple[object, ...]:
    rows = snapshot.get("slideRows")
    if not isinstance(rows, list):
        return ()
    signature: list[object] = [snapshot.get("rootId"), snapshot.get("activeIndex")]
    for row in rows:
        if not isinstance(row, dict):
            return ()
        canvases = row.get("contentCanvases")
        if not isinstance(canvases, list):
            return ()
        signature.append(
            (
                row.get("id"),
                row.get("index"),
                row.get("contentSlots"),
                tuple(
                    (
                        canvas.get("slot"),
                        canvas.get("width"),
                        canvas.get("height"),
                        tuple(sorted((canvas.get("box") or {}).items())),
                        canvas.get("drawCount"),
                        canvas.get("mutationCount"),
                        tuple(sorted((canvas.get("last") or {}).items()))
                        if isinstance(canvas.get("last"), dict)
                        else None,
                    )
                    for canvas in canvases
                    if isinstance(canvas, dict)
                ),
            )
        )
    return tuple(signature)


class KadocomiAdapter(SiteAdapter):
    """Capture one exact, currently public Kadocomi WEB episode."""

    def __init__(self) -> None:
        self._source_url: str | None = None
        self._target_url: str | None = None
        self._work_id: str | None = None
        self._episode_id: str | None = None
        self._external_id: str | None = None
        self._opaque_work_key: str | None = None
        self._work_title: str | None = None
        self._order_label: str | None = None
        self._all_slots: tuple[str, ...] = ()
        self._slide_slots: tuple[tuple[str, ...], ...] = ()
        self._end_slide_index: int | None = None
        self._captured_slots: list[str] = []
        self._last_capture_slots: tuple[str, ...] = ()
        self._pending_next_index: int | None = None
        self._ended = False
        self._capture_diagnostics: dict[str, object] = {"mode": "not_started"}

    async def prepare_page(self, page: Page) -> None:
        try:
            await page.add_init_script(NATIVE_OBSERVER_INIT_SCRIPT)
        except PlaywrightError as exc:
            raise UnknownPageStateError("Kadocomi native image observer could not be installed") from exc

    def resolve_initial_navigation_url(self, source_url: str) -> str:
        identity = parse_kadocomi_episode_url(source_url)
        if identity is None:
            raise UnknownPageStateError("Kadocomi requires an exact absolute episode URL")
        external = f"{identity.work_id}:{identity.episode_id}"
        if self._external_id is not None and self._external_id != external:
            raise UnknownPageStateError("Kadocomi URL differs from the configured Catalog source")
        self._source_url = canonical_kadocomi_episode_url(source_url)
        self._target_url = self._source_url
        self._work_id = identity.work_id
        self._episode_id = identity.episode_id
        self._external_id = external
        return canonical_kadocomi_work_url(f"https://{SITE_HOST}/detail/{identity.work_id}")

    def get_access_profile(self) -> AccessProfile:
        return kadocomi_access_profile()

    async def configure_run(self, page: Page, access_strategy: AccessStrategy) -> None:
        del page
        if access_strategy != "direct":
            raise UnsupportedAccessStrategyError(
                "Kadocomi supports only the verified direct free WEB path"
            )

    async def configure_quota_resource(self, page: Page, quota_resource: str | None) -> None:
        del page
        if quota_resource is not None:
            raise UnsupportedAccessStrategyError("Kadocomi does not support access resources")

    async def configure_target_identity(self, external_id: str, work_key: str) -> None:
        match = _EXTERNAL_ID.fullmatch(external_id)
        if match is None or not isinstance(work_key, str) or not work_key.strip():
            raise UnknownPageStateError("Kadocomi Catalog target identity is malformed")
        if self._external_id is not None and self._external_id != external_id:
            raise UnknownPageStateError("Kadocomi Catalog identity was configured inconsistently")
        self._external_id = external_id
        self._work_id = match.group("work")
        self._episode_id = match.group("episode")
        self._opaque_work_key = work_key

    async def initialize_entry_only(self, page: Page) -> None:
        del page
        raise UnsupportedAccessStrategyError("Kadocomi does not support entry-only access")

    def get_initialize_timeout_ms(self, default_ms: int) -> int:
        return max(default_ms, INITIALIZE_TIMEOUT_MS)

    def get_page_change_timeout_ms(self, default_ms: int) -> int:
        return max(default_ms, int(PAGE_CHANGE_TIMEOUT_SECONDS * 1000))

    async def initialize(self, page: Page) -> None:
        if self._target_url is None or self._work_id is None or self._episode_id is None:
            raise UnknownPageStateError("Kadocomi exact episode target was not configured")
        if parse_kadocomi_episode_url(self._source_url or "") is None:
            raise UnknownPageStateError("Kadocomi canonical source URL is invalid")
        self._captured_slots = []
        self._last_capture_slots = ()
        self._pending_next_index = None
        self._ended = False
        records = await self._read_public_work_listing(page)
        record = self._find_target_record(records)
        self._validate_free_record(record)
        canonical_url = canonical_kadocomi_episode_url(record.source.url)
        if canonical_url != self._target_url:
            raise UnknownPageStateError("Kadocomi public row URL differs from the exact source")
        title = record.item.canonical_title
        order_label = record.item.order_label
        if not isinstance(title, str) or not title.strip() or not isinstance(order_label, str) or not order_label.strip():
            raise UnknownPageStateError("Kadocomi public row work or episode title is incomplete")
        self._work_title = title.strip()
        self._order_label = order_label.strip()

        try:
            response: Response | None = await page.goto(
                self._target_url,
                wait_until="domcontentloaded",
                timeout=NAVIGATION_TIMEOUT_MS,
            )
        except PlaywrightError as exc:
            raise UnknownPageStateError("Kadocomi exact episode navigation failed") from exc
        if response is None or response.status != 200:
            raise UnknownPageStateError("Kadocomi exact episode route did not return HTTP 200")
        self._validate_current_episode_url(page)
        await self._validate_episode_metadata(page)
        await self._wait_for_initial_reader(page)

    async def _read_public_work_listing(self, page: Page) -> list[DiscoveredRecord]:
        if self._work_id is None:
            raise UnknownPageStateError("Kadocomi target work identity is missing")
        target = WatchlistTarget(
            key="kadocomi-capture-preflight",
            work_key=self._opaque_work_key or f"kadocomi:{self._work_id}",
            site="kadocomi",
            url=canonical_kadocomi_work_url(f"https://{SITE_HOST}/detail/{self._work_id}"),
            label="Kadocomi capture preflight",
        )
        adapter = KadocomiDiscoveryAdapter()
        records: list[DiscoveredRecord] = []
        try:
            async for record in adapter.iter_records(page, target, "full"):
                records.append(record)
        except Exception as exc:
            if isinstance(exc, UnknownPageStateError):
                raise
            raise UnknownPageStateError("Kadocomi complete public episode list could not be verified") from exc
        if not records:
            raise UnknownPageStateError("Kadocomi public episode list is empty")
        return records

    def _find_target_record(self, records: list[DiscoveredRecord]) -> DiscoveredRecord:
        matches = [record for record in records if record.source.external_id == self._external_id]
        if len(matches) != 1:
            raise UnknownPageStateError("Kadocomi exact target is absent or duplicated in the public list")
        return matches[0]

    def _validate_free_record(self, record: DiscoveredRecord) -> None:
        source = record.source
        if source.available is not True or source.access_mode != "free":
            raise UnknownPageStateError("Kadocomi exact public row is not positively free")
        expiry = source.free_until
        if expiry is not None and (
            not isinstance(expiry, datetime)
            or expiry.tzinfo is None
            or expiry <= now_jst()
        ):
            raise UnknownPageStateError("Kadocomi exact public row is expired or has unknown expiry")

    def _validate_current_episode_url(self, page: Page) -> None:
        identity = parse_kadocomi_episode_url(page.url)
        if (
            identity is None
            or identity.work_id != self._work_id
            or identity.episode_id != self._episode_id
        ):
            raise UnknownPageStateError("Kadocomi navigation changed the exact work or episode")

    async def _validate_episode_metadata(self, page: Page) -> None:
        self._validate_current_episode_url(page)
        try:
            raw = await asyncio.wait_for(page.evaluate(_READ_EPISODE_METADATA_SCRIPT), timeout=4)
        except (PlaywrightError, TimeoutError) as exc:
            raise UnknownPageStateError("Kadocomi episode metadata could not be read") from exc
        expected_heading = f"\u3010{self._order_label}\u3011{self._work_title}"
        expected_title = f"{expected_heading}{_OG_TITLE_SUFFIX}"
        if (
            not isinstance(raw, dict)
            or raw.get("headingCount") != 1
            or raw.get("heading") != expected_heading
            or raw.get("titleCount") != 1
            or raw.get("ogTitle") != expected_title
            or raw.get("documentTitle") != expected_title
            or raw.get("visibleDialogCount") != 0
        ):
            raise UnknownPageStateError("Kadocomi episode identity or access surface is unknown")

    async def _snapshot(self, page: Page, *, include_nodes: bool = False) -> dict[str, Any]:
        try:
            value = await asyncio.wait_for(
                page.evaluate(
                    "includeNodes => window.__kadocomiNativeCaptureV1?.snapshot(includeNodes) ?? null",
                    include_nodes,
                ),
                timeout=3,
            )
        except (PlaywrightError, TimeoutError) as exc:
            raise UnknownPageStateError("Kadocomi viewer snapshot failed") from exc
        if not isinstance(value, dict):
            raise UnknownPageStateError("Kadocomi viewer observer is unavailable")
        return value

    def _validate_inventory(
        self, snapshot: dict[str, Any]
    ) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...], int]:
        if (
            snapshot.get("status") != "ok"
            or snapshot.get("contentOutsideSlides") != 0
            or snapshot.get("hooksInstalled") is not True
            or snapshot.get("direction") not in {"ltr", "rtl"}
            or snapshot.get("rtlClass") is not True
        ):
            raise UnknownPageStateError("Kadocomi reader structure or native observer is unknown")
        rows = snapshot.get("slideRows")
        if not isinstance(rows, list) or len(rows) < 2 or len(rows) > MAX_CANVAS_SLOTS:
            raise UnknownPageStateError("Kadocomi reader slide list is incomplete or too large")
        marker_count = snapshot.get("endMarkerCount")
        marker_indexes = snapshot.get("markerSlideIndexes")
        if (
            isinstance(marker_count, bool)
            or not isinstance(marker_count, int)
            or marker_count != 2
            or not isinstance(marker_indexes, list)
            or len(marker_indexes) != marker_count
            or any(isinstance(index, bool) or not isinstance(index, int) for index in marker_indexes)
            or len(set(marker_indexes)) != 1
            or snapshot.get("markerNumbers") != ["1", "2"]
            or snapshot.get("unclassifiedEndMarkerCount") != 0
        ):
            raise UnknownPageStateError("Kadocomi explicit end marker is missing or ambiguous")
        end_index = marker_indexes[0]
        trailing_count = len(rows) - end_index - 1
        if end_index < 1 or trailing_count not in (0, 1):
            raise UnknownPageStateError("Kadocomi explicit END boundary or trailing slide is unknown")
        secondary_markers = snapshot.get("secondaryEndMarkerSlideIndexes")
        if (
            not isinstance(secondary_markers, list)
            or secondary_markers != ([end_index + 1] if trailing_count == 1 else [])
        ):
            raise UnknownPageStateError("Kadocomi recommendation end marker is ambiguous")
        slide_slots: list[tuple[str, ...]] = []
        flattened: list[str] = []
        for index, row in enumerate(rows):
            if not isinstance(row, dict) or row.get("index") != index:
                raise UnknownPageStateError("Kadocomi slide order is malformed")
            slots = row.get("contentSlots")
            canvases = row.get("contentCanvases")
            if (
                not isinstance(slots, list)
                or not all(isinstance(slot, str) and slot for slot in slots)
                or not isinstance(canvases, list)
                or len(canvases) != len(slots)
            ):
                raise UnknownPageStateError("Kadocomi content slot identity is incomplete")
            if index < end_index and (len(slots) > 2 or (index == 0 and len(slots) != 1)):
                raise UnknownPageStateError("Kadocomi reader spread shape is unsupported")
            if 0 < index < end_index and len(slots) != 2:
                raise UnknownPageStateError("Kadocomi observed right-to-left spread shape changed")
            if index >= end_index and slots:
                raise UnknownPageStateError("Kadocomi found content at or after its explicit END")
            canvas_boxes: list[dict[str, object]] = []
            for slot, canvas in zip(slots, canvases, strict=True):
                if not isinstance(canvas, dict) or canvas.get("slot") != slot:
                    raise UnknownPageStateError("Kadocomi canvas identity is ambiguous")
                box = canvas.get("box")
                if not isinstance(box, dict):
                    raise UnknownPageStateError("Kadocomi canvas geometry is missing")
                canvas_boxes.append(box)
            if len(canvas_boxes) == 2:
                right_x = canvas_boxes[0].get("x")
                left_x = canvas_boxes[1].get("x")
                if not isinstance(right_x, (int, float)) or not isinstance(left_x, (int, float)) or right_x <= left_x:
                    raise UnknownPageStateError("Kadocomi RTL spread slot order is unknown")
            slide_slots.append(tuple(slots))
            flattened.extend(slots)
        if len(flattened) > MAX_CANVAS_SLOTS or len(flattened) != len(set(flattened)):
            raise UnknownPageStateError("Kadocomi content canvas inventory is duplicated or too large")
        if any(not slide_slots[index] for index in range(end_index)):
            raise UnknownPageStateError("Kadocomi content inventory has an unexplained empty slide")
        return tuple(flattened), tuple(slide_slots), end_index

    async def _wait_for_initial_reader(self, page: Page) -> None:
        deadline = asyncio.get_running_loop().time() + VIEWER_READY_TIMEOUT_SECONDS
        previous: tuple[object, ...] | None = None
        self._validate_current_episode_url(page)
        while asyncio.get_running_loop().time() < deadline:
            snapshot = await self._snapshot(page)
            if snapshot.get("status") in {
                "clones", "nested_carousel", "direction", "slides",
                "content_wrapper_shape", "end_marker_shape",
            }:
                raise UnknownPageStateError("Kadocomi initial viewer variant is unsupported")
            if snapshot.get("status") == "ok":
                rows = snapshot.get("slideRows")
                has_content_slots = isinstance(rows, list) and any(
                    isinstance(row, dict)
                    and isinstance(row.get("contentSlots"), list)
                    and bool(row["contentSlots"])
                    for row in rows
                )
                if snapshot.get("endMarkerCount") == 0 or not has_content_slots:
                    previous = None
                    await page.wait_for_timeout(VIEWER_POLL_MS)
                    continue
                slots, slide_slots, end_index = self._validate_inventory(snapshot)
                if snapshot.get("activeIndex") != 0:
                    raise UnknownPageStateError("Kadocomi episode did not open at its first reader slide")
                first_canvas = snapshot["slideRows"][0]["contentCanvases"][0]
                last = first_canvas.get("last") if isinstance(first_canvas, dict) else None
                ready = (
                    isinstance(last, dict)
                    and last.get("sourceTag") == "IMG"
                    and last.get("complete") is True
                    and last.get("blobAvailable") is True
                    and isinstance(first_canvas.get("width"), int)
                    and first_canvas["width"] > 0
                    and isinstance(first_canvas.get("height"), int)
                    and first_canvas["height"] > 0
                )
                signature = _snapshot_signature(snapshot)
                if ready and signature and signature == previous:
                    self._all_slots = slots
                    self._slide_slots = slide_slots
                    self._end_slide_index = end_index
                    return
                previous = signature if ready else None
            else:
                previous = None
            await page.wait_for_timeout(VIEWER_POLL_MS)
        raise PageChangeTimeoutError("Kadocomi first reader slide did not settle")

    async def detect_state(self, page: Page) -> PageState:
        self._validate_current_episode_url(page)
        snapshot = await self._snapshot(page)
        if snapshot.get("status") in {"content_wrapper_shape", "end_marker_shape"}:
            raise UnknownPageStateError("Kadocomi reader wrapper or END marker shape changed")
        if snapshot.get("status") != "ok":
            return PageState.LOADING
        slots, slide_slots, end_index = self._validate_inventory(snapshot)
        if (
            slots != self._all_slots
            or slide_slots != self._slide_slots
            or end_index != self._end_slide_index
        ):
            raise UnknownPageStateError("Kadocomi reader canvas inventory changed during capture")
        active_index = snapshot.get("activeIndex")
        if isinstance(active_index, bool) or not isinstance(active_index, int):
            raise UnknownPageStateError("Kadocomi active slide index is invalid")
        marker_indexes = snapshot.get("markerSlideIndexes")
        if active_index == self._end_slide_index:
            if (
                self._captured_slots != list(self._all_slots)
                or snapshot.get("endMarkerCount", 0) != 2
                or snapshot.get("markerNumbers") != ["1", "2"]
                or not isinstance(marker_indexes, list)
                or any(index != active_index for index in marker_indexes)
                or slide_slots[active_index]
            ):
                raise UnknownPageStateError("Kadocomi reached END before all exact content slots were captured")
            self._ended = True
            return PageState.END
        if active_index < 0 or active_index >= (self._end_slide_index or 0):
            raise UnknownPageStateError("Kadocomi active slide is outside the verified content sequence")
        current_slots = slide_slots[active_index]
        already_captured = (
            current_slots == self._last_capture_slots
            and bool(current_slots)
            and tuple(self._captured_slots[-len(current_slots) :]) == current_slots
        )
        expected_prefix = tuple(self._all_slots[: len(self._captured_slots)])
        next_slots = tuple(self._all_slots[len(self._captured_slots) : len(self._captured_slots) + len(current_slots)])
        if (
            tuple(self._captured_slots) != expected_prefix
            or not current_slots
            or (already_captured and tuple(self._captured_slots[-len(current_slots) :]) != current_slots)
            or (not already_captured and current_slots != next_slots)
        ):
            raise UnknownPageStateError("Kadocomi active canvas slots skipped or repeated content")
        row = snapshot["slideRows"][active_index]
        canvases = row.get("contentCanvases")
        if not isinstance(canvases, list) or len(canvases) != len(current_slots):
            return PageState.LOADING
        for canvas in canvases:
            last = canvas.get("last") if isinstance(canvas, dict) else None
            if (
                not isinstance(last, dict)
                or last.get("sourceTag") != "IMG"
                or last.get("complete") is not True
                or (last.get("blobAvailable") is not True and not already_captured)
                or not isinstance(canvas.get("width"), int)
                or canvas["width"] <= 0
                or not isinstance(canvas.get("height"), int)
                or canvas["height"] <= 0
            ):
                return PageState.LOADING
        return PageState.CONTENT

    async def get_capture_target(self, page: Page) -> Locator:
        del page
        raise UnknownPageStateError("Kadocomi requires proven native WebP capture")

    async def get_capture_targets(self, page: Page) -> tuple[Locator, ...]:
        del page
        raise UnknownPageStateError("Kadocomi does not permit locator or screenshot fallback")

    async def capture_page(self, page: Page) -> tuple[CaptureResult, ...] | None:
        if await self.detect_state(page) is not PageState.CONTENT:
            raise UnknownPageStateError("Kadocomi has no verified active content slide")
        snapshot = await self._snapshot(page)
        active_index = snapshot.get("activeIndex")
        if not isinstance(active_index, int) or isinstance(active_index, bool):
            raise UnknownPageStateError("Kadocomi active slide identity is missing")
        expected_slots = self._slide_slots[active_index]
        if expected_slots == self._last_capture_slots or any(
            slot in self._captured_slots for slot in expected_slots
        ):
            raise UnknownPageStateError("Kadocomi active slot set was already captured")
        try:
            raw = await asyncio.wait_for(
                page.evaluate(
                    NATIVE_CAPTURE_SCRIPT,
                    {
                        "expectedSlots": list(expected_slots),
                        "maxBytes": MAX_NATIVE_BLOB_BYTES,
                        "maxPixels": MAX_NATIVE_PIXEL_COUNT,
                        "maxTotalPixels": MAX_NATIVE_TOTAL_PIXEL_COUNT,
                    },
                ),
                timeout=10,
            )
        except (PlaywrightError, TimeoutError) as exc:
            self._capture_diagnostics = {"mode": "capture_failed", "reason": "native_proof_timeout"}
            raise UnknownPageStateError("Kadocomi native capture proof did not complete") from exc
        if not isinstance(raw, dict) or raw.get("ok") is not True:
            reason = raw.get("reason") if isinstance(raw, dict) else "malformed_result"
            self._capture_diagnostics = {"mode": "capture_failed", "reason": str(reason)}
            raise UnknownPageStateError("Kadocomi native source proof failed closed")
        captures_raw = raw.get("captures")
        if not isinstance(captures_raw, list) or len(captures_raw) != len(expected_slots):
            raise UnknownPageStateError("Kadocomi native capture set is incomplete")
        results: list[CaptureResult] = []
        for expected_slot, row in zip(expected_slots, captures_raw, strict=True):
            if (
                not isinstance(row, dict)
                or row.get("slot") != expected_slot
                or not isinstance(row.get("data"), str)
                or not isinstance(row.get("mimeType"), str)
                or isinstance(row.get("width"), bool)
                or not isinstance(row.get("width"), int)
                or isinstance(row.get("height"), bool)
                or not isinstance(row.get("height"), int)
            ):
                raise UnknownPageStateError("Kadocomi native capture result is malformed")
            try:
                data = base64.b64decode(row["data"], validate=True)
            except (ValueError, TypeError) as exc:
                raise UnknownPageStateError("Kadocomi native Blob bytes are malformed") from exc
            result = capture_kadocomi_webp(
                data,
                source_mime_type=row["mimeType"],
                width=row["width"],
                height=row["height"],
            )
            if result is None:
                raise UnknownPageStateError("Kadocomi original viewer Blob is not a supported WebP")
            results.append(result)
        self._validate_current_episode_url(page)
        after = await self._snapshot(page)
        after_slots, after_slides, after_end_index = self._validate_inventory(after)
        if (
            after_slots != self._all_slots
            or after_slides != self._slide_slots
            or after_end_index != self._end_slide_index
            or after.get("activeIndex") != active_index
        ):
            raise UnknownPageStateError("Kadocomi active slide changed after native byte transfer")
        self._captured_slots.extend(expected_slots)
        self._last_capture_slots = expected_slots
        self._capture_diagnostics = {
            "mode": "verified_viewer_source_webp",
            "slots": list(expected_slots),
            "output_dimensions": [[result.width, result.height] for result in results],
            "output_formats": [result.mime_type for result in results],
        }
        return tuple(results)

    async def get_content_identity(self, page: Page) -> ContentIdentity:
        if await self.detect_state(page) is not PageState.CONTENT:
            raise UnknownPageStateError("Kadocomi content identity is unavailable")
        snapshot = await self._snapshot(page)
        active_index = snapshot["activeIndex"]
        slots = self._slide_slots[active_index]
        return ContentIdentity(
            page_id=",".join(slots),
            page_number=len(self._captured_slots) + 1,
            source_id=self._external_id,
        )

    async def get_content_context(self, page: Page) -> ContentContext:
        self._validate_current_episode_url(page)
        if self._work_title is None or self._work_id is None or self._episode_id is None:
            raise UnknownPageStateError("Kadocomi work context has not been verified")
        return ContentContext(
            content_id=self._episode_id,
            work_id=self._work_id,
            episode_id=self._episode_id,
            title=self._work_title,
        )

    async def go_next(self, page: Page) -> None:
        if await self.detect_state(page) is not PageState.CONTENT:
            raise UnknownPageStateError("Kadocomi cannot advance from a non-content state")
        snapshot = await self._snapshot(page)
        active_index = snapshot.get("activeIndex")
        if (
            not isinstance(active_index, int)
            or isinstance(active_index, bool)
            or self._pending_next_index is not None
            or self._last_capture_slots != self._slide_slots[active_index]
            or tuple(self._captured_slots[-len(self._last_capture_slots) :]) != self._last_capture_slots
        ):
            raise UnknownPageStateError("Kadocomi page turn is not bound to the last native capture")
        try:
            target = await page.evaluate(_NAVIGATION_TARGET_SCRIPT)
        except PlaywrightError as exc:
            raise UnknownPageStateError("Kadocomi reader overlay hit test failed") from exc
        if (
            not isinstance(target, dict)
            or target.get("ok") is not True
            or target.get("activeIndex") != active_index
            or target.get("slotCount") != len(self._last_capture_slots)
            or not isinstance(target.get("x"), (int, float))
            or not isinstance(target.get("y"), (int, float))
        ):
            raise UnknownPageStateError("Kadocomi verified left reader overlay is unavailable")
        await page.mouse.click(target["x"], target["y"])
        self._pending_next_index = active_index

    async def wait_for_change(
        self,
        page: Page,
        previous_identity: ContentIdentity | None,
    ) -> None:
        del previous_identity
        if self._pending_next_index is None:
            raise PageChangeTimeoutError("Kadocomi has no verified page-turn action pending")
        previous_index = self._pending_next_index
        deadline = asyncio.get_running_loop().time() + PAGE_CHANGE_TIMEOUT_SECONDS
        previous_signature: tuple[object, ...] | None = None
        stable = 0
        try:
            while asyncio.get_running_loop().time() < deadline:
                self._validate_current_episode_url(page)
                snapshot = await self._snapshot(page)
                if snapshot.get("status") in {"content_wrapper_shape", "end_marker_shape"}:
                    raise UnknownPageStateError("Kadocomi reader wrapper or END marker shape changed")
                if snapshot.get("status") != "ok":
                    await page.wait_for_timeout(VIEWER_POLL_MS)
                    continue
                slots, slide_slots, end_index = self._validate_inventory(snapshot)
                if (
                    slots != self._all_slots
                    or slide_slots != self._slide_slots
                    or end_index != self._end_slide_index
                ):
                    raise UnknownPageStateError("Kadocomi page turn changed the content inventory")
                active_index = snapshot.get("activeIndex")
                if active_index == previous_index:
                    await page.wait_for_timeout(VIEWER_POLL_MS)
                    continue
                if active_index != previous_index + 1:
                    raise UnknownPageStateError("Kadocomi page turn skipped a reader slide")
                if active_index == self._end_slide_index:
                    if (
                        tuple(self._captured_slots) != self._all_slots
                        or slide_slots[active_index]
                        or not snapshot.get("markerSlideIndexes")
                        or snapshot.get("endMarkerCount") != 2
                        or snapshot.get("markerNumbers") != ["1", "2"]
                        or any(index != active_index for index in snapshot["markerSlideIndexes"])
                    ):
                        raise UnknownPageStateError("Kadocomi terminal slide is not a complete explicit END")
                    self._pending_next_index = None
                    return
                row = snapshot["slideRows"][active_index]
                canvases = row["contentCanvases"]
                ready = all(
                    isinstance(canvas.get("last"), dict)
                    and canvas["last"].get("sourceTag") == "IMG"
                    and canvas["last"].get("complete") is True
                    and canvas["last"].get("blobAvailable") is True
                    and isinstance(canvas.get("width"), int)
                    and canvas["width"] > 0
                    and isinstance(canvas.get("height"), int)
                    and canvas["height"] > 0
                    for canvas in canvases
                    if isinstance(canvas, dict)
                ) and len(canvases) == len(slide_slots[active_index])
                signature = _snapshot_signature(snapshot)
                if ready and signature and signature == previous_signature:
                    stable += 1
                    if stable >= 1:
                        self._pending_next_index = None
                        return
                else:
                    stable = 0
                previous_signature = signature if ready else None
                await page.wait_for_timeout(VIEWER_POLL_MS)
        except UnknownPageStateError as exc:
            self._capture_diagnostics = {
                "mode": "page_change_failed",
                "reason": str(exc),
            }
            raise
        raise PageChangeTimeoutError("Kadocomi next reader slide did not settle")

    async def collect_debug_metadata(self, page: Page) -> dict[str, object]:
        del page
        return {"kadocomi_capture": dict(self._capture_diagnostics)}

    def get_output_metadata(self) -> dict[str, str | None]:
        return {"title": self._work_title, "order": self._order_label}


__all__ = ["KadocomiAdapter"]
