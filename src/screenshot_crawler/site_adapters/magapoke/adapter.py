"""Site adapter for the Magapoke canvas viewer."""

from __future__ import annotations

import asyncio

from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from screenshot_crawler.core.capture import CaptureResult, capture_locator
from screenshot_crawler.core.errors import PageChangeTimeoutError
from screenshot_crawler.core.models import ContentContext, ContentIdentity
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.base import SiteAdapter
from screenshot_crawler.site_adapters.magapoke.native_capture import (
    MagapokeUrlParts,
    is_magapoke_jpeg_response,
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


class MagapokeAdapter(SiteAdapter):
    """Capture one Magapoke episode from its shared browser page."""

    page_change_timeout_ms = 10_000
    render_stable_checks = 3
    advance_retry_count = 2
    source_response_wait_timeout_ms = 2_000
    source_response_retry_count = 2
    source_response_retry_interval_ms = 100
    max_source_responses = 128
    rewind_max_steps = 32

    viewer_selector = ".c-viewer"
    content_canvas_selector = ".c-viewer__comic canvas"
    next_selector = ".c-viewer__pager-next"

    def __init__(self) -> None:
        self._initial_url: str | None = None
        self._initial_parts: MagapokeUrlParts | None = None
        self._source_episode: MagapokeUrlParts | None = None
        self._advance_pending = False
        self._source_responses: dict[str, object] = {}
        self._source_response_tasks: dict[str, asyncio.Task[bytes | None]] = {}
        self._output_title: str | None = None
        self._output_order: str | None = None

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

    async def initialize(self, page: Page) -> None:
        self._initial_url = page.url
        self._initial_parts = parse_magapoke_url(page.url)
        self._source_episode = self._initial_parts
        self._advance_pending = False
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
        locator = page.locator(self.content_canvas_selector)
        return tuple(locator.nth(int(row["index"])) for row in rows)

    async def capture_page(self, page: Page) -> tuple[CaptureResult, ...] | None:
        rows = await self._canvas_rows(page)
        if not rows:
            return None
        targets = await self.get_capture_targets(page)
        paths_to_release: set[str] = set()
        records: list[dict[str, object]] = []
        try:
            for row in rows:
                path = str(row.get("sourcePath") or "")
                paths_to_release.add(path)
                mappings = row.get("mapping")
                base = row.get("base")
                visible_draw = row.get("visibleDraw")
                width = int(row.get("canvasWidth") or 0)
                height = int(row.get("canvasHeight") or 0)
                body = None
                if (
                    path
                    and self._source_episode is not None
                    and source_matches_episode(path, self._source_episode)
                    and isinstance(mappings, list)
                    and isinstance(base, dict)
                    and isinstance(visible_draw, dict)
                    and width > 0
                    and height > 0
                ):
                    body = await self._source_bytes_for(path)
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

            lossless_captures: list[CaptureResult] = []
            lossless_ok = True
            for record in records:
                body = record["body"]
                result = (
                    reconstruct_jpeg_lossless(
                        body,
                        base=record["base"],
                        mappings=record["mappings"],
                        visible_draw=record["visible_draw"],
                        source_path=str(record["path"]),
                        canvas_size=record["canvas_size"],
                    )
                    if isinstance(body, bytes)
                    and isinstance(record["base"], dict)
                    and isinstance(record["mappings"], list)
                    and isinstance(record["visible_draw"], dict)
                    else None
                )
                if result is None:
                    lossless_ok = False
                else:
                    lossless_captures.append(result)
            if lossless_ok:
                return tuple(lossless_captures)

            png_captures: list[CaptureResult] = []
            png_ok = True
            for record in records:
                body = record["body"]
                result = (
                    reconstruct_jpeg_png(
                        body,
                        base=record["base"],
                        mappings=record["mappings"],
                        visible_draw=record["visible_draw"],
                        source_path=str(record["path"]),
                        canvas_size=record["canvas_size"],
                    )
                    if isinstance(body, bytes)
                    and isinstance(record["base"], dict)
                    and isinstance(record["mappings"], list)
                    and isinstance(record["visible_draw"], dict)
                    else None
                )
                if result is None:
                    png_ok = False
                else:
                    png_captures.append(result)
            if png_ok:
                return tuple(png_captures)
        finally:
            for path in paths_to_release:
                if path:
                    await self._discard_source(path)
        # A visible spread is all-native or all-fallback; never mix provenance.
        return tuple([await capture_locator(target) for target in targets])

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
