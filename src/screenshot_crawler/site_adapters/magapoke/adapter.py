"""Site adapter for the Magapoke canvas viewer."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from screenshot_crawler.core.capture import CaptureResult, capture_locator
from screenshot_crawler.core.errors import (
    AccessResourceUnavailableError,
    PageChangeTimeoutError,
    UnsupportedAccessStrategyError,
)
from screenshot_crawler.core.models import AccessStrategy, ContentContext, ContentIdentity
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.base import AccessConsumption, SiteAdapter
from screenshot_crawler.site_adapters.magapoke.native_capture import (
    MagapokeUrlParts,
    is_magapoke_jpeg_response,
    jpeg_dimensions,
    normalize_source_path,
    parse_magapoke_url,
    reconstruct_jpeg_lossless,
    reconstruct_jpeg_png,
    source_matches_episode,
)

_CANVAS_HOOK = r"""
(() => {
  if (window.__magapokeCaptureState) return;
  const state = {
    offscreenSources: new WeakMap(),
    visibleSources: new WeakMap(),
    sequence: 0,
  };
  const sourcePattern = /^\/static\/web_titles\/[^/]+\/episodes\/[^/]+\/[^/]+\.jpg$/i;
  function imageSource(source) {
    if (!(source instanceof HTMLImageElement)) return null;
    const raw = source.currentSrc || source.src || '';
    try {
      const parsed = new URL(raw, location.href);
      if (parsed.hostname !== 'mgpk-cdn.magazinepocket.com' ||
          !sourcePattern.test(parsed.pathname)) return null;
      return {
        sourcePath: parsed.pathname,
        sourceWidth: source.naturalWidth || source.width || 0,
        sourceHeight: source.naturalHeight || source.height || 0,
        sequence: ++state.sequence,
      };
    } catch (_) { return null; }
  }
  function sourceMeta(source) {
    const image = imageSource(source);
    if (image) return { ...image, sourceType: 'HTMLImageElement' };
    return null;
  }
  function offscreenMeta(source, meta) {
    if (!globalThis.OffscreenCanvas || !(source instanceof globalThis.OffscreenCanvas) || !meta) {
      return null;
    }
    return {
      sourcePath: meta.sourcePath,
      sourceWidth: source.width,
      sourceHeight: source.height,
      sourceType: 'OffscreenCanvas',
    };
  }
  function geometry(args, source) {
    const sourceWidth = source && (source.naturalWidth || source.width || 0) || 0;
    const sourceHeight = source && (source.naturalHeight || source.height || 0) || 0;
    if (args.length === 3) {
      return { sx: 0, sy: 0, sw: sourceWidth, sh: sourceHeight,
        dx: Number(args[1]), dy: Number(args[2]), dw: sourceWidth, dh: sourceHeight };
    }
    if (args.length === 5) {
      return { sx: 0, sy: 0, sw: sourceWidth, sh: sourceHeight,
        dx: Number(args[1]), dy: Number(args[2]), dw: Number(args[3]), dh: Number(args[4]) };
    }
    if (args.length === 9) {
      return { sx: Number(args[1]), sy: Number(args[2]), sw: Number(args[3]), sh: Number(args[4]),
        dx: Number(args[5]), dy: Number(args[6]), dw: Number(args[7]), dh: Number(args[8]) };
    }
    return null;
  }
  function drawRecord(ctx, args, sourceInfo) {
    const rect = geometry(args, args[0]);
    if (!sourceInfo || !rect || Object.values(rect).some(value => !Number.isFinite(value))) {
      return null;
    }
    const transform = ctx.getTransform();
    return {
      ...sourceInfo,
      ...rect,
      canvasWidth: ctx.canvas.width,
      canvasHeight: ctx.canvas.height,
      transform: [transform.a, transform.b, transform.c, transform.d, transform.e, transform.f],
      compositeOperation: ctx.globalCompositeOperation,
      filter: ctx.filter,
      imageSmoothingEnabled: ctx.imageSmoothingEnabled,
      sequence: ++state.sequence,
    };
  }
  function isFullCanvasDraw(record) {
    return record && record.sx === 0 && record.sy === 0 &&
      record.sw === record.sourceWidth && record.sh === record.sourceHeight &&
      record.dx === 0 && record.dy === 0 &&
      record.dw === record.canvasWidth && record.dh === record.canvasHeight;
  }
  function copyState(meta) {
    if (!meta) return null;
    return {
      sourcePath: meta.sourcePath,
      sourceWidth: meta.sourceWidth,
      sourceHeight: meta.sourceHeight,
      canvasWidth: meta.canvasWidth,
      canvasHeight: meta.canvasHeight,
      sequence: meta.sequence,
      base: meta.base ? { ...meta.base, transform: [...meta.base.transform] } : null,
      mapping: meta.mapping.map(item => ({ ...item, transform: [...item.transform] })),
      visibleDraw: meta.visibleDraw
        ? { ...meta.visibleDraw, transform: [...meta.visibleDraw.transform] }
        : null,
    };
  }
  const offscreenProto = globalThis.OffscreenCanvasRenderingContext2D &&
    globalThis.OffscreenCanvasRenderingContext2D.prototype;
  if (offscreenProto && offscreenProto.drawImage && !offscreenProto.drawImage.__magapoke) {
    const original = offscreenProto.drawImage;
    function hookedOffscreenDrawImage(...args) {
      const sourceInfo = sourceMeta(args[0]);
      const record = drawRecord(this, args, sourceInfo);
      if (record && this.canvas) {
        let meta = state.offscreenSources.get(this.canvas);
        if (!meta || meta.sourcePath !== record.sourcePath || isFullCanvasDraw(record)) {
          meta = { ...record, base: null, mapping: [] };
          state.offscreenSources.set(this.canvas, meta);
        }
        if (isFullCanvasDraw(record)) meta.base = record;
        else if (meta.mapping.length < 128) meta.mapping.push(record);
      }
      return original.apply(this, args);
    }
    hookedOffscreenDrawImage.__magapoke = true;
    offscreenProto.drawImage = hookedOffscreenDrawImage;
  }
  const canvasProto = CanvasRenderingContext2D.prototype;
  if (canvasProto.drawImage && !canvasProto.drawImage.__magapoke) {
    const original = canvasProto.drawImage;
    function hookedCanvasDrawImage(...args) {
      const source = args[0];
      const meta = source && state.offscreenSources.get(source);
      if (this.canvas) {
        if (meta) {
          const visibleDraw = drawRecord(this, args, offscreenMeta(source, meta));
          const snapshot = copyState(meta);
          snapshot.visibleDraw = visibleDraw;
          state.visibleSources.set(this.canvas, snapshot);
        } else {
          state.visibleSources.delete(this.canvas);
        }
      }
      return original.apply(this, args);
    }
    hookedCanvasDrawImage.__magapoke = true;
    canvasProto.drawImage = hookedCanvasDrawImage;
  }
  window.__magapokeCaptureState = {
    getCanvasSources() {
      return [...document.querySelectorAll('.c-viewer__comic canvas')].map((canvas, index) => {
        const rect = canvas.getBoundingClientRect();
        const item = canvas.closest('.c-viewer__pages-item');
        const pageItems = [...document.querySelectorAll('.c-viewer__pages-item')];
        const meta = state.visibleSources.get(canvas) || null;
        const visible = rect.width > 0 && rect.height > 0 && rect.right > 0 &&
          rect.left < window.innerWidth && rect.bottom > 0 && rect.top < window.innerHeight;
        return {
          index, pageIndex: item ? pageItems.indexOf(item) : -1,
          x: rect.x, y: rect.y, width: rect.width, height: rect.height, visible,
          sourcePath: meta && meta.sourcePath || null,
          sourceWidth: meta && meta.sourceWidth || 0,
          sourceHeight: meta && meta.sourceHeight || 0,
          canvasWidth: meta && meta.visibleDraw && meta.visibleDraw.canvasWidth || canvas.width,
          canvasHeight: meta && meta.visibleDraw && meta.visibleDraw.canvasHeight || canvas.height,
          base: meta && meta.base || null,
          mapping: meta && meta.mapping || null,
          visibleDraw: meta && meta.visibleDraw || null,
          sequence: meta && meta.sequence || 0,
        };
      }).filter(row => row.visible);
    }
  };
})();
"""

_PREMIUM_TICKET_COUNT = re.compile(r"^\s*(\d+)\s*枚\s*$")
_WORK_TICKET_TEXT = "作品チケットで読む"
_PREMIUM_TICKET_TEXT = "プレミアムチケットで読む"
_WORK_TICKET_CLASS = "c-btn-icon-primary--ticket"
_PREMIUM_TICKET_CLASS = "c-btn-icon-primary--premium-ticket"
_PREMIUM_TICKET_LABEL = "プレミアムチケット"


def parse_premium_ticket_count(value: str | None) -> int | None:
    """Parse the exact live `N枚` Premium Ticket value format."""

    if value is None:
        return None
    match = _PREMIUM_TICKET_COUNT.fullmatch(value)
    return int(match.group(1)) if match is not None else None


class MagapokeAdapter(SiteAdapter):
    """Capture one Magapoke episode from its shared browser page."""

    page_change_timeout_ms = 10_000
    render_stable_checks = 3
    advance_retry_count = 2
    source_response_wait_timeout_ms = 2_000
    source_response_retry_count = 2
    source_response_retry_interval_ms = 100
    capture_retry_count = 2
    capture_retry_interval_ms = 100
    max_source_responses = 128
    rewind_max_steps = 32

    viewer_selector = ".c-viewer"
    content_canvas_selector = ".c-viewer__comic canvas"
    next_selector = ".c-viewer__pager-next"

    def __init__(self) -> None:
        self._access_strategy: AccessStrategy = "auto"
        self._quota_resource: str | None = None
        self._access_consumption = AccessConsumption()
        self._initial_url: str | None = None
        self._initial_parts: MagapokeUrlParts | None = None
        self._source_episode: MagapokeUrlParts | None = None
        self._advance_pending = False
        self._source_responses: dict[str, object] = {}
        self._source_response_tasks: dict[str, asyncio.Task[bytes | None]] = {}
        self._output_title: str | None = None
        self._output_order: str | None = None

    def get_initialize_timeout_ms(self, default_ms: int) -> int:
        # Initialization can sequence readiness, click confirmation, viewer
        # setup, and render stabilization. Keep each phase bounded without
        # cancelling the overall operation at the single-phase deadline.
        return max(default_ms, 5 * self.page_change_timeout_ms)

    async def configure_run(
        self, page: Page, access_strategy: AccessStrategy
    ) -> None:
        """Allow direct navigation and defer quota resource validation to its hook."""

        del page
        if access_strategy not in {"auto", "direct", "quota"}:
            raise UnsupportedAccessStrategyError(
                f"MagapokeAdapter does not support access_strategy={access_strategy!r}"
            )
        self._access_strategy = access_strategy
        self._access_consumption = AccessConsumption()

    async def configure_quota_resource(
        self, page: Page, quota_resource: str | None
    ) -> None:
        del page
        if quota_resource not in {None, "work_ticket", "premium_ticket"}:
            raise UnsupportedAccessStrategyError(
                f"MagapokeAdapter does not support quota_resource={quota_resource!r}"
            )
        if quota_resource is not None and self._access_strategy != "quota":
            raise UnsupportedAccessStrategyError(
                "Magapoke quota_resource requires access_strategy='quota'"
            )
        if self._access_strategy == "quota" and quota_resource not in {
            "work_ticket",
            "premium_ticket",
        }:
            raise UnsupportedAccessStrategyError(
                "Magapoke quota access requires a supported ticket resource"
            )
        self._quota_resource = quota_resource

    def get_access_consumption(self) -> AccessConsumption:
        return self._access_consumption

    async def prepare_page(self, page: Page) -> None:
        for task in self._source_response_tasks.values():
            task.cancel()
        if self._source_response_tasks:
            await asyncio.gather(*self._source_response_tasks.values(), return_exceptions=True)
        self._source_responses.clear()
        self._source_response_tasks.clear()
        await page.add_init_script(_CANVAS_HOOK)
        page.on("response", self._handle_source_response)

    def _handle_source_response(self, response: object) -> None:
        if not is_magapoke_jpeg_response(response):
            return
        path = normalize_source_path(str(getattr(response, "url", "")))
        if path is None or path in self._source_responses:
            return
        if len(self._source_responses) >= self.max_source_responses:
            return
        self._source_responses[path] = response
        self._source_response_tasks[path] = asyncio.create_task(
            self._read_source_response(response)
        )

    @staticmethod
    async def _read_source_response(response: object) -> bytes | None:
        try:
            body = await response.body()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - one image may safely fallback
            return None
        return body if isinstance(body, bytes) else None

    async def _source_bytes_for(self, source_path: str) -> bytes | None:
        for attempt in range(self.source_response_retry_count + 1):
            task = self._source_response_tasks.get(source_path)
            response = self._source_responses.get(source_path)
            if task is None and response is not None:
                task = asyncio.create_task(self._read_source_response(response))
                self._source_response_tasks[source_path] = task
            if task is not None:
                try:
                    body = await asyncio.wait_for(
                        asyncio.shield(task),
                        timeout=self.source_response_wait_timeout_ms / 1000,
                    )
                except Exception:  # noqa: BLE001 - fallback is per canvas
                    body = None
                if body is not None:
                    return body
            if attempt < self.source_response_retry_count:
                await asyncio.sleep(self.source_response_retry_interval_ms / 1000)
                task = self._source_response_tasks.get(source_path)
                if task is not None and task.done() and response is not None:
                    self._source_response_tasks[source_path] = asyncio.create_task(
                        self._read_source_response(response)
                    )
        task = self._source_response_tasks.get(source_path)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return None

    async def _discard_source(self, source_path: str) -> None:
        """Release a source after the current canvas has been resolved."""

        self._source_responses.pop(source_path, None)
        task = self._source_response_tasks.pop(source_path, None)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _canvas_rows(self, page: Page) -> list[dict[str, object]]:
        try:
            rows = await asyncio.wait_for(
                page.evaluate(
                    """() => window.__magapokeCaptureState
                    ? window.__magapokeCaptureState.getCanvasSources() : []"""
                ),
                timeout=2,
            )
        except Exception:  # noqa: BLE001 - state is classified as loading/unknown
            return []
        if not isinstance(rows, list):
            return []
        return sorted(
            [row for row in rows if isinstance(row, dict)],
            key=lambda row: float(row.get("x", 0)),
            reverse=True,
        )

    async def _wait_for_render_ready(self, page: Page) -> None:
        previous: tuple[object, ...] | None = None
        stable = 0
        elapsed = 0
        while elapsed < self.page_change_timeout_ms:
            if self._initial_url is not None and page.url != self._initial_url:
                return
            rows = await self._canvas_rows(page)
            signature = tuple(
                (
                    row.get("pageIndex"), row.get("sourcePath"),
                    round(float(row.get("x", 0))), round(float(row.get("y", 0))),
                )
                for row in rows
            )
            if signature and signature == previous:
                stable += 1
                if stable >= self.render_stable_checks:
                    return
            else:
                stable = 0
            previous = signature
            await page.wait_for_timeout(100)
            elapsed += 100
        raise PageChangeTimeoutError("Magapoke viewer did not finish loading within the timeout")

    @staticmethod
    def _normalized_access_text(value: str) -> str:
        return " ".join(value.split())

    async def _visible_access_controls(self, page: Page) -> list[tuple[Locator, str, set[str]]]:
        controls = page.locator(
            ".p-episode-purchase a, .p-episode-purchase button, "
            ".p-episode-purchase [role='button'], "
            ".p-episode-purchase input[type='button'], "
            ".p-episode-purchase input[type='submit']"
        )
        visible: list[tuple[Locator, str, set[str]]] = []
        for index in range(await controls.count()):
            control = controls.nth(index)
            if not await control.is_visible():
                continue
            classes = set((await control.get_attribute("class") or "").split())
            tag_name = await control.evaluate("element => element.tagName.toLowerCase()")
            href = await control.get_attribute("href")
            known_comment_navigation = (
                tag_name == "a"
                and "p-episode-comment-btn" in classes
                and (
                    ("p-episode-comment-btn--pc" in classes and href == "#comment")
                    or (
                        "p-episode-comment-btn--sp" in classes
                        and href == "javascript:void(0);"
                    )
                )
            )
            if known_comment_navigation:
                continue
            text = self._normalized_access_text(await control.inner_text())
            visible.append((control, text, classes))
        return visible

    async def _wait_for_quota_entry_state(
        self, page: Page
    ) -> tuple[list[dict[str, object]], list[tuple[Locator, str, set[str]]], bool]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.page_change_timeout_ms / 1000
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise PageChangeTimeoutError(
                    "Magapoke viewer content or access controls did not load"
                )
            try:
                rows = await asyncio.wait_for(self._canvas_rows(page), timeout=remaining)
                if rows:
                    return rows, [], True

                remaining = deadline - loop.time()
                if remaining <= 0:
                    continue
                if await asyncio.wait_for(
                    self._viewer_canvas_visible(page), timeout=remaining
                ):
                    return rows, [], True

                remaining = deadline - loop.time()
                if remaining <= 0:
                    continue
                controls = await asyncio.wait_for(
                    self._visible_access_controls(page), timeout=remaining
                )
            except TimeoutError as exc:
                raise PageChangeTimeoutError(
                    "Magapoke viewer content or access controls did not load"
                ) from exc
            if controls:
                return rows, controls, False

            remaining_ms = int((deadline - loop.time()) * 1000)
            if remaining_ms <= 0:
                continue
            await page.wait_for_timeout(min(100, remaining_ms))

    async def _enter_with_work_ticket(self, page: Page) -> None:
        rows, controls, already_accessible = await self._wait_for_quota_entry_state(page)
        if already_accessible:
            return
        work = [
            entry for entry in controls
            if entry[1] == _WORK_TICKET_TEXT and _WORK_TICKET_CLASS in entry[2]
        ]
        premium = [
            entry for entry in controls
            if entry[1] == _PREMIUM_TICKET_TEXT and _PREMIUM_TICKET_CLASS in entry[2]
        ]
        if any(
            (_WORK_TICKET_CLASS in classes)
            and (_PREMIUM_TICKET_CLASS in classes)
            for _, _, classes in controls
        ):
            raise UnsupportedAccessStrategyError(
                "Magapoke access control has conflicting Work/Premium Ticket classes"
            )
        if len(work) > 1 or len(premium) > 1:
            raise UnsupportedAccessStrategyError("Magapoke ticket controls are ambiguous")
        # A Premium-only screen is normal for a charging Work Ticket; never fallback to it.
        if len(controls) == 1 and len(premium) == 1 and not work:
            raise AccessResourceUnavailableError("work_ticket_unavailable")
        if len(controls) != 1 or len(work) != 1 or premium:
            raise UnsupportedAccessStrategyError(
                "Magapoke Work Ticket entry UI is unknown or ambiguous"
            )

        rows = await self._canvas_rows(page)
        if rows or await self._viewer_canvas_visible(page):
            return

        control = work[0][0]
        await control.click(timeout=self.page_change_timeout_ms)
        await self._confirm_ticket_consumption(page, resource="work_ticket")

    async def _enter_with_premium_ticket(self, page: Page) -> None:
        _, controls, already_accessible = await self._wait_for_quota_entry_state(page)
        if already_accessible:
            return
        work = [
            entry for entry in controls
            if entry[1] == _WORK_TICKET_TEXT and _WORK_TICKET_CLASS in entry[2]
        ]
        premium = [
            entry for entry in controls
            if entry[1] == _PREMIUM_TICKET_TEXT and _PREMIUM_TICKET_CLASS in entry[2]
        ]
        if any(
            (_WORK_TICKET_CLASS in classes)
            and (_PREMIUM_TICKET_CLASS in classes)
            for _, _, classes in controls
        ):
            raise UnsupportedAccessStrategyError(
                "Magapoke access control has conflicting Work/Premium Ticket classes"
            )
        if len(work) > 1 or len(premium) > 1:
            raise UnsupportedAccessStrategyError("Magapoke ticket controls are ambiguous")
        if len(work) + len(premium) != len(controls):
            raise UnsupportedAccessStrategyError(
                "Magapoke Premium Ticket entry UI is unknown or ambiguous"
            )
        if not premium:
            if len(controls) == 1 and len(work) == 1:
                raise AccessResourceUnavailableError("premium_ticket_unavailable")
            raise UnsupportedAccessStrategyError(
                "Magapoke Premium Ticket entry UI is unknown or ambiguous"
            )

        count = await self._read_premium_ticket_count(page)
        if count == 0:
            raise AccessResourceUnavailableError(
                "premium_ticket_exhausted", stop_resource_pass=True
            )

        await premium[0][0].click(timeout=self.page_change_timeout_ms)
        await self._confirm_ticket_consumption(page, resource="premium_ticket")

    async def _read_premium_ticket_count(self, page: Page) -> int:
        panels = page.locator("dl.p-episode-purchase__point")
        matches: list[Locator] = []
        for index in range(await panels.count()):
            panel = panels.nth(index)
            labels = panel.locator("dt.p-episode-purchase__point-ttl")
            matching_labels = []
            for label_index in range(await labels.count()):
                label = labels.nth(label_index)
                text = self._normalized_access_text(await label.inner_text())
                if text == _PREMIUM_TICKET_LABEL:
                    matching_labels.append(label)
            if matching_labels:
                if len(matching_labels) != 1:
                    raise UnsupportedAccessStrategyError(
                        "Magapoke Premium Ticket balance label is duplicated"
                    )
                matches.append(panel)

        if len(matches) != 1:
            raise UnsupportedAccessStrategyError(
                "Magapoke Premium Ticket balance is missing or ambiguous"
            )
        label = matches[0].locator("dt.p-episode-purchase__point-ttl")
        value = matches[0].locator("dd.p-episode-purchase__point-data")
        if await label.count() != 1 or await value.count() != 1:
            raise UnsupportedAccessStrategyError(
                "Magapoke Premium Ticket balance structure is unexpected"
            )
        label_text = self._normalized_access_text(await label.inner_text())
        count = parse_premium_ticket_count(await value.inner_text())
        if label_text != _PREMIUM_TICKET_LABEL or count is None:
            raise UnsupportedAccessStrategyError(
                "Magapoke Premium Ticket balance value is malformed"
            )
        return count

    async def _confirm_ticket_consumption(
        self, page: Page, *, resource: str
    ) -> None:
        resource_label = "Work Ticket" if resource == "work_ticket" else "Premium Ticket"
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.page_change_timeout_ms / 1000
        while True:
            remaining_ms = int((deadline - loop.time()) * 1000)
            if remaining_ms <= 0:
                raise PageChangeTimeoutError(
                    f"Magapoke {resource_label} click did not reach confirmed viewer content"
                )
            try:
                rows = await asyncio.wait_for(
                    self._canvas_rows(page), timeout=remaining_ms / 1000
                )
                remaining_ms = int((deadline - loop.time()) * 1000)
                if remaining_ms <= 0:
                    continue
                controls = await asyncio.wait_for(
                    self._visible_access_controls(page), timeout=remaining_ms / 1000
                )
            except TimeoutError as exc:
                raise PageChangeTimeoutError(
                    f"Magapoke {resource_label} click did not reach confirmed viewer content"
                ) from exc
            remaining_ms = int((deadline - loop.time()) * 1000)
            if resource == "work_ticket":
                still_visible = any(
                    text == _WORK_TICKET_TEXT and _WORK_TICKET_CLASS in classes
                    for _, text, classes in controls
                )
            else:
                still_visible = any(
                    text == _PREMIUM_TICKET_TEXT and _PREMIUM_TICKET_CLASS in classes
                    for _, text, classes in controls
                )
            if rows and not still_visible:
                self._access_consumption = AccessConsumption(
                    consumed=True,
                    resource=resource,
                    consumed_at=datetime.now(UTC),
                )
                return
            if remaining_ms <= 0:
                continue
            await page.wait_for_timeout(min(100, remaining_ms))

    async def _viewer_canvas_visible(self, page: Page) -> bool:
        canvases = page.locator(self.content_canvas_selector)
        for index in range(await canvases.count()):
            canvas = canvases.nth(index)
            if not await canvas.is_visible():
                continue
            try:
                has_pixels = await canvas.evaluate(
                    "element => element.width > 0 && element.height > 0"
                )
            except PlaywrightError:
                continue
            if has_pixels:
                return True
        return False

    async def initialize(self, page: Page) -> None:
        self._initial_url = page.url
        self._initial_parts = parse_magapoke_url(page.url)
        self._source_episode = self._initial_parts
        self._advance_pending = False
        rows = await self._canvas_rows(page)
        already_accessible = bool(rows) or await self._viewer_canvas_visible(page)
        if (
            self._access_strategy == "quota"
            and not already_accessible
        ):
            if self._quota_resource == "work_ticket":
                await self._enter_with_work_ticket(page)
            elif self._quota_resource == "premium_ticket":
                await self._enter_with_premium_ticket(page)
            rows = await self._canvas_rows(page)
        page_indices = [
            int(row["pageIndex"])
            for row in rows
            if int(row.get("pageIndex", -1)) >= 0
        ]
        needs_rewind = not rows or (page_indices and min(page_indices) > 1)
        if needs_rewind:
            previous_button = page.locator(".c-viewer__pager-prev")
            elapsed = 0
            while await previous_button.count() == 0 and elapsed < 3_000:
                await page.wait_for_timeout(100)
                elapsed += 100
            if await previous_button.count() == 1:
                try:
                    await previous_button.wait_for(
                        state="visible", timeout=self.page_change_timeout_ms
                    )
                except PlaywrightTimeoutError as exc:
                    raise PageChangeTimeoutError(
                        "Magapoke viewer controls did not finish loading"
                    ) from exc
                await self._rewind_to_first_content(page)
            elif not rows:
                raise PageChangeTimeoutError(
                    "Magapoke viewer content and navigation controls did not load"
                )
        await self._wait_for_render_ready(page)
        context = await self.get_content_context(page)
        self._output_title, self._output_order = self._split_title(context.title)

    async def _rewind_to_first_content(self, page: Page) -> None:
        """Clear a persisted viewer position without assuming episode length."""

        previous_signature: tuple[object, ...] | None = None
        for _ in range(self.rewind_max_steps):
            rows = await self._canvas_rows(page)
            page_indices = [
                int(row["pageIndex"])
                for row in rows
                if int(row.get("pageIndex", -1)) >= 0
            ]
            if page_indices and min(page_indices) <= 1:
                return
            signature = tuple(
                (row.get("pageIndex"), row.get("sourcePath"), row.get("sequence"))
                for row in rows
            )
            previous_signature = signature
            previous_button = page.locator(".c-viewer__pager-prev")
            if await previous_button.count() != 1:
                return
            try:
                await previous_button.click(timeout=1_000, force=True, no_wait_after=True)
            except PlaywrightTimeoutError:
                return
            await page.wait_for_timeout(150)
            next_rows = await self._canvas_rows(page)
            next_signature = tuple(
                (row.get("pageIndex"), row.get("sourcePath"), row.get("sequence"))
                for row in next_rows
            )
            if previous_signature == next_signature and next_signature:
                return

    @staticmethod
    def _split_title(raw_title: str | None) -> tuple[str | None, str | None]:
        parts = [part.strip() for part in (raw_title or "").split(" | ") if part.strip()]
        title = parts[0] if parts else None
        order = parts[1].split(" / ", 1)[0].strip() if len(parts) > 1 else None
        return title, order or None

    def get_output_metadata(self) -> dict[str, str | None]:
        return {
            "title": self._output_title,
            "order": self._output_order,
            "author": None,
            "genre": "漫画",
        }

    async def detect_state(self, page: Page) -> PageState:
        if self._initial_parts is not None:
            current = parse_magapoke_url(page.url)
            if current is not None and current != self._initial_parts:
                return PageState.NEXT_CONTENT
        if await self._canvas_rows(page):
            return PageState.CONTENT
        if await page.locator(self.content_canvas_selector).count():
            return PageState.LOADING
        try:
            visible = await page.locator(self.viewer_selector).is_visible(timeout=500)
        except (PlaywrightTimeoutError, TimeoutError):
            visible = False
        return PageState.LOADING if visible and self._advance_pending else PageState.UNKNOWN

    async def get_capture_target(self, page: Page) -> Locator:
        targets = await self.get_capture_targets(page)
        return targets[0]

    async def get_capture_targets(self, page: Page) -> tuple[Locator, ...]:
        rows = await self._canvas_rows(page)
        if not rows:
            raise LookupError("Magapoke content canvas is not visible")
        return self._targets_for_rows(page, rows)

    def _targets_for_rows(self, page: Page, rows: list[dict[str, object]]) -> tuple[Locator, ...]:
        locator = page.locator(self.content_canvas_selector)
        return tuple(locator.nth(int(row["index"])) for row in rows)

    async def _capture_native_attempt(
        self,
        page: Page,
        rows: list[dict[str, object]],
        paths_to_release: set[str],
    ) -> tuple[tuple[CaptureResult, ...] | None, tuple[Locator, ...], bool]:
        targets = self._targets_for_rows(page, rows)
        records: list[dict[str, object]] = []
        observation_retryable = False
        deterministic_source_failure = False
        for row in rows:
            path = str(row.get("sourcePath") or "")
            paths_to_release.add(path)
            mappings = row.get("mapping")
            base = row.get("base")
            visible_draw = row.get("visibleDraw")
            width = int(row.get("canvasWidth") or 0)
            height = int(row.get("canvasHeight") or 0)
            body = None
            if not path or self._source_episode is None:
                observation_retryable = True
            elif not source_matches_episode(path, self._source_episode):
                deterministic_source_failure = True
            elif not (
                isinstance(mappings, list)
                and mappings
                and isinstance(base, dict)
                and isinstance(visible_draw, dict)
                and width > 0
                and height > 0
            ):
                observation_retryable = True
            else:
                body = await self._source_bytes_for(path)
                if (
                    body is None
                    or body[:3] != b"\xff\xd8\xff"
                    or jpeg_dimensions(body) is None
                ):
                    observation_retryable = True
            records.append(
                {
                    "path": path,
                    "body": body,
                    "base": base,
                    "mappings": mappings,
                    "visible_draw": visible_draw,
                    "canvas_size": (width, height),
                }
            )

        if deterministic_source_failure:
            return None, targets, False
        if observation_retryable:
            return None, targets, True

        lossless_captures: list[CaptureResult] = []
        for record in records:
            body = record["body"]
            result = reconstruct_jpeg_lossless(
                body,
                base=record["base"],
                mappings=record["mappings"],
                visible_draw=record["visible_draw"],
                source_path=str(record["path"]),
                canvas_size=record["canvas_size"],
            )
            if result is None:
                break
            lossless_captures.append(result)
        else:
            return tuple(lossless_captures), targets, False

        png_captures: list[CaptureResult] = []
        for record in records:
            body = record["body"]
            result = reconstruct_jpeg_png(
                body,
                base=record["base"],
                mappings=record["mappings"],
                visible_draw=record["visible_draw"],
                source_path=str(record["path"]),
                canvas_size=record["canvas_size"],
            )
            if result is None:
                return None, targets, False
            png_captures.append(result)
        return tuple(png_captures), targets, False

    async def capture_page(self, page: Page) -> tuple[CaptureResult, ...] | None:
        paths_to_release: set[str] = set()
        fallback_targets: tuple[Locator, ...] = ()
        try:
            for attempt in range(self.capture_retry_count + 1):
                rows = await self._canvas_rows(page)
                if rows:
                    captures, targets, retryable = await self._capture_native_attempt(
                        page, rows, paths_to_release
                    )
                    fallback_targets = targets
                    if captures is not None:
                        return captures
                else:
                    retryable = True
                if not retryable or attempt >= self.capture_retry_count:
                    break
                await page.wait_for_timeout(self.capture_retry_interval_ms)
        finally:
            for path in paths_to_release:
                if path:
                    await self._discard_source(path)
        if not fallback_targets:
            return None
        # A visible spread is all-native or all-fallback; never mix provenance.
        return tuple([await capture_locator(target) for target in fallback_targets])

    async def get_content_identity(self, page: Page) -> ContentIdentity:
        rows = await self._canvas_rows(page)
        page_id = "|".join(
            f"{row.get('pageIndex', -1)}:{row.get('sourcePath') or 'draw-' + str(row.get('sequence', 0))}"
            for row in rows
        ) or None
        page_number = None
        page_indices = [int(row["pageIndex"]) for row in rows if int(row.get("pageIndex", -1)) >= 0]
        if page_indices:
            page_number = min(page_indices) + 1
        current = parse_magapoke_url(page.url)
        return ContentIdentity(
            page_id=page_id,
            page_number=page_number,
            source_id=current.episode_id if current else None,
        )

    async def get_content_context(self, page: Page) -> ContentContext:
        parts = parse_magapoke_url(page.url)
        title: str | None = None
        try:
            raw_title = (await page.title()).strip()
            title = raw_title.split(" | ", 1)[0].strip() or None
        except (PlaywrightTimeoutError, TimeoutError):
            pass
        return ContentContext(
            content_id=parts.content_id if parts else None,
            work_id=parts.work_id if parts else None,
            episode_id=parts.episode_id if parts else None,
            chapter_id=None,
            title=title,
        )

    async def go_next(self, page: Page) -> None:
        button = page.locator(self.next_selector)
        if await button.count() != 1:
            raise PageChangeTimeoutError("Magapoke next control was not uniquely identified")
        self._advance_pending = True
        try:
            await button.click(timeout=1_000, no_wait_after=True)
        except PlaywrightTimeoutError as exc:
            raise PageChangeTimeoutError("Magapoke next control could not be clicked") from exc

    async def wait_for_change(
        self, page: Page, previous_identity: ContentIdentity | None
    ) -> None:
        if previous_identity is None:
            await self._wait_for_render_ready(page)
            return
        elapsed = 0
        retries = 0
        retry_at = self.page_change_timeout_ms // (self.advance_retry_count + 1)
        while elapsed < self.page_change_timeout_ms:
            current_parts = parse_magapoke_url(page.url)
            if self._initial_url is not None and page.url != self._initial_url:
                self._advance_pending = False
                return
            if self._initial_parts is not None and current_parts != self._initial_parts:
                self._advance_pending = False
                return
            current = await self.get_content_identity(page)
            if current.page_id is not None and current != previous_identity:
                await self._wait_for_render_ready(page)
                self._advance_pending = False
                return
            if retries < self.advance_retry_count and elapsed >= retry_at * (retries + 1):
                retries += 1
                await self.go_next(page)
            await page.wait_for_timeout(100)
            elapsed += 100
        raise PageChangeTimeoutError("Magapoke viewer page did not change within the timeout")
