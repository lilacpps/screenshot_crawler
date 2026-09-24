"""Production adapter for the Shonen Jump+ horizontal viewer."""

from __future__ import annotations

import asyncio
import base64
import re
from typing import Any

from playwright.async_api import Locator, Page

from screenshot_crawler.core.access_guard import AccessProfile
from screenshot_crawler.core.capture import CaptureResult, capture_locator
from screenshot_crawler.core.errors import PageChangeTimeoutError, UnsupportedAccessStrategyError
from screenshot_crawler.core.models import AccessStrategy, ContentContext, ContentIdentity
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.base import SiteAdapter
from screenshot_crawler.site_adapters.jumpplus.access import jumpplus_access_profile
from screenshot_crawler.site_adapters.jumpplus.native_capture import (
    _dct_signature,
    decoded_pixel_sha256,
    is_jumpplus_jpeg_response,
    jpeg_dimensions,
    parse_jumpplus_url,
    reconstruct_jpeg_lossless,
    reconstruct_jpeg_png,
    select_transport_candidate,
)

_CANVAS_HOOK = r"""
(() => {
  if (window.__jumpplusProductionCapture) return;
  const state = {canvasIds: new WeakMap(), nextCanvasId: 1, imageIds: new WeakMap(),
    nextImageId: 1, images: new Map(), draws: [], mutations: [], sequence: 0};
  const maxRecords = 6000;
  const canvasInfo = (canvas) => {
    if (!canvas) return {id: null, width: 0, height: 0, selector: null};
    let id = state.canvasIds.get(canvas);
    if (!id) { id = state.nextCanvasId++; state.canvasIds.set(canvas, id); }
    return {id, width: Number(canvas.width) || 0, height: Number(canvas.height) || 0,
      selector: canvas.id ? `#${CSS.escape(canvas.id)}` : 'canvas'};
  };
  const sourceInfo = (source) => {
    if (!(source instanceof HTMLImageElement)) return null;
    let sourceId = state.imageIds.get(source);
    if (!sourceId) { sourceId = state.nextImageId++; state.imageIds.set(source, sourceId); state.images.set(sourceId, source); }
    return {sourceId, sourceUrl: source.currentSrc || source.src || '', type: 'HTMLImageElement',
      naturalWidth: Number(source.naturalWidth) || Number(source.width) || 0,
      naturalHeight: Number(source.naturalHeight) || Number(source.height) || 0};
  };
  const geometry = (args, source) => {
    const sw = Number(source?.naturalWidth || source?.width) || 0;
    const sh = Number(source?.naturalHeight || source?.height) || 0;
    if (args.length === 3) return {sx: 0, sy: 0, sw, sh, dx: Number(args[1]), dy: Number(args[2]), dw: sw, dh: sh};
    if (args.length === 5) return {sx: 0, sy: 0, sw, sh, dx: Number(args[1]), dy: Number(args[2]), dw: Number(args[3]), dh: Number(args[4])};
    if (args.length === 9) return {sx: Number(args[1]), sy: Number(args[2]), sw: Number(args[3]), sh: Number(args[4]), dx: Number(args[5]), dy: Number(args[6]), dw: Number(args[7]), dh: Number(args[8])};
    return null;
  };
  const trim = (items) => { if (items.length > maxRecords) items.splice(0, items.length - maxRecords); };
  const transform = (ctx) => { try { const m = ctx.getTransform(); return {a:m.a,b:m.b,c:m.c,d:m.d,e:m.e,f:m.f}; } catch (_) { return null; } };
  const record = (ctx, args) => {
    const source = args[0], sourceMeta = sourceInfo(source), rect = geometry(args, source);
    if (!sourceMeta || !rect) return null;
    const item = {sequence: state.sequence++, canvas: canvasInfo(ctx.canvas), source: sourceMeta,
      sourcePath: sourceMeta.sourceUrl, sourceWidth: sourceMeta.naturalWidth, sourceHeight: sourceMeta.naturalHeight,
      canvasWidth: Number(ctx.canvas.width) || 0, canvasHeight: Number(ctx.canvas.height) || 0,
      ...rect, transform: transform(ctx), globalCompositeOperation: ctx.globalCompositeOperation,
      filter: ctx.filter, globalAlpha: Number(ctx.globalAlpha)};
    state.draws.push(item); trim(state.draws); return item;
  };
  const proto = CanvasRenderingContext2D.prototype;
  if (proto.drawImage && !proto.drawImage.__jumpplusProduction) {
    const original = proto.drawImage;
    function drawImage(...args) { try { record(this, args); } catch (_) {} return original.apply(this, args); }
    drawImage.__jumpplusProduction = true; proto.drawImage = drawImage;
  }
  const mutationMethods = {clearRect:(a)=>({x:Number(a[0]),y:Number(a[1]),width:Number(a[2]),height:Number(a[3])}),
    fillRect:(a)=>({x:Number(a[0]),y:Number(a[1]),width:Number(a[2]),height:Number(a[3])}),
    putImageData:(a)=>({dx:Number(a[1]),dy:Number(a[2])}), strokeRect:(a)=>({x:Number(a[0]),y:Number(a[1]),width:Number(a[2]),height:Number(a[3])}),
    fillText:(a)=>({x:Number(a[1]),y:Number(a[2])}), strokeText:(a)=>({x:Number(a[1]),y:Number(a[2])}),
    fill:()=>null, stroke:()=>null};
  for (const [name, geometryFactory] of Object.entries(mutationMethods)) {
    const original = proto[name]; if (typeof original !== 'function' || original.__jumpplusProduction) continue;
    function mutation(...args) { try { state.mutations.push({sequence:state.sequence++,canvas:canvasInfo(this.canvas),operation:name,geometry:geometryFactory(args)}); trim(state.mutations); } catch (_) {} return original.apply(this,args); }
    mutation.__jumpplusProduction = true; proto[name] = mutation;
  }
  const visible = (rect) => { const iw = innerWidth, ih = innerHeight; const area = Math.max(0, Math.min(rect.right,iw)-Math.max(rect.left,0))*Math.max(0,Math.min(rect.bottom,ih)-Math.max(rect.top,0)); return rect.width > 0 && rect.height > 0 && area / (rect.width*rect.height) >= 0.5; };
  const mapping = (item) => ({sourcePath:item.sourcePath,sourceWidth:item.sourceWidth,sourceHeight:item.sourceHeight,canvasWidth:item.canvasWidth,canvasHeight:item.canvasHeight,
    sx:item.sx,sy:item.sy,sw:item.sw,sh:item.sh,dx:item.dx,dy:item.dy,dw:item.dw,dh:item.dh,transform:item.transform,
    globalCompositeOperation:item.globalCompositeOperation,filter:item.filter,globalAlpha:item.globalAlpha,sourceId:item.source.sourceId,sourceUrl:item.source.sourceUrl,sequence:item.sequence});
  window.__jumpplusProductionCapture = {
    getActiveRows: () => {
      const container = document.querySelector('section.viewer.js-viewer .image-container.js-viewer-content');
      if (!container) return [];
      const canvases = [...container.querySelectorAll('canvas.page-image.js-page-image')];
      const areas = [...container.querySelectorAll('.page-area.js-page-area')];
      return canvases.map((canvas,index) => { const rect = canvas.getBoundingClientRect(); if (!visible(rect)) return null; const info=canvasInfo(canvas);
        const all=state.draws.filter(item => item.canvas.id === info.id); const full=all.filter(item => item.sx===0&&item.sy===0&&item.sw===item.sourceWidth&&item.sh===item.sourceHeight&&item.dx===0&&item.dy===0&&item.dw===item.canvasWidth&&item.dh===item.canvasHeight); const base=full.length?full[full.length-1]:null; const generation=base?all.filter(item=>item.sequence>=base.sequence):all; const pageArea=canvas.closest('.page-area.js-page-area');
        return {index,canvasId:info.id,pageIndex:pageArea?areas.indexOf(pageArea):-1,x:rect.x,y:rect.y,width:rect.width,height:rect.height,canvasWidth:canvas.width,canvasHeight:canvas.height,
          source:base?base.source:null,base:base?mapping(base):null,visibleDraw:base?mapping(base):null,mapping:generation.filter(item=>item!==base).map(mapping),mutations:state.mutations.filter(item=>item.canvas.id===info.id&&item.sequence>= (base?base.sequence:0))};
      }).filter(Boolean).sort((a,b)=>b.x-a.x);
    },
    snapshotSources: async (wanted) => { const result=[]; for (const item of wanted || []) { const image=state.images.get(Number(item.sourceId)); if (!image) continue; const current=image.currentSrc||image.src||''; if (current !== item.sourceUrl) { result.push({sourceId:Number(item.sourceId),sourceUrl:current,drawUrl:item.sourceUrl,changed:true}); continue; }
        try { const canvas=document.createElement('canvas'); canvas.width=image.naturalWidth||image.width; canvas.height=image.naturalHeight||image.height; const ctx=canvas.getContext('2d'); ctx.drawImage(image,0,0); result.push({sourceId:Number(item.sourceId),sourceUrl:current,dataUrl:canvas.toDataURL('image/png')}); } catch (error) { result.push({sourceId:Number(item.sourceId),sourceUrl:current,error:String(error)}); }
      } return result; },
    debug: () => ({drawCount:state.draws.length,mutationCount:state.mutations.length,sourceCount:state.images.size})
  };
})();
"""

_FORBIDDEN = re.compile(r"(?:購入|ポイント|レンタル|次の話|次話|next\s+episode|/episode/)", re.IGNORECASE)


class JumpPlusAdapter(SiteAdapter):
    page_change_timeout_ms = 10_000
    render_stable_checks = 3
    capture_retry_count = 2
    capture_retry_interval_ms = 100
    source_response_wait_timeout_ms = 2_000
    max_source_responses = 128
    rewind_max_steps = 32
    forward_interceptor_wait_ms = 5_000
    viewer_selector = "section.viewer.js-viewer"
    canvas_selector = "section.viewer.js-viewer .image-container.js-viewer-content canvas.page-image.js-page-image"
    forward_selector = "section.viewer.js-viewer .page-navigation-forward.js-slide-forward"

    def __init__(self) -> None:
        self._access_strategy: AccessStrategy = "auto"
        self._initial_url: str | None = None
        self._initial_parts = None
        self._advance_pending = False
        self._terminal_reached = False
        self._content_page_count: int | None = None
        self._first_content_page_index: int | None = None
        self._captured_content_page_count = 0
        self._last_active_max_page_index: int | None = None
        self._source_responses: dict[str, object] = {}
        self._source_tasks: dict[str, asyncio.Task[bytes | None]] = {}
        self._capture_debug: dict[str, Any] = {}
        self._output_title: str | None = None
        self._output_order: str | None = None
        self._output_author: str | None = None

    def get_access_profile(self) -> AccessProfile:
        return jumpplus_access_profile()

    async def configure_run(self, page: Page, access_strategy: AccessStrategy) -> None:
        del page
        if access_strategy not in {"auto", "direct"}:
            raise UnsupportedAccessStrategyError(
                f"JumpPlusAdapter does not support access_strategy={access_strategy!r}"
            )
        self._access_strategy = access_strategy

    async def configure_quota_resource(self, page: Page, quota_resource: str | None) -> None:
        del page
        if quota_resource is not None:
            raise UnsupportedAccessStrategyError("JumpPlusAdapter does not support quota_resource")

    async def prepare_page(self, page: Page) -> None:
        await self._discard_sources()
        await page.add_init_script(script=_CANVAS_HOOK)
        page.on("response", self._handle_response)

    def _handle_response(self, response: object) -> None:
        if not is_jumpplus_jpeg_response(response):
            return
        url = str(getattr(response, "url", ""))
        if url in self._source_responses or len(self._source_responses) >= self.max_source_responses:
            return
        self._source_responses[url] = response
        self._source_tasks[url] = asyncio.create_task(self._read_response(response))

    @staticmethod
    async def _read_response(response: object) -> bytes | None:
        try:
            body = await response.body()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - one response must only cause fallback
            return None
        return body if isinstance(body, bytes) and body[:3] == b"\xff\xd8\xff" else None

    async def _discard_sources(self) -> None:
        for url in tuple(self._source_tasks):
            await self._discard_source(url)

    async def _discard_source(self, url: str) -> None:
        task = self._source_tasks.pop(url, None)
        self._source_responses.pop(url, None)
        if task is not None:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _rows(self, page: Page) -> list[dict[str, object]]:
        try:
            rows = await asyncio.wait_for(page.evaluate("() => window.__jumpplusProductionCapture ? window.__jumpplusProductionCapture.getActiveRows() : []"), timeout=2)
        except Exception:  # noqa: BLE001 - transient render state
            return []
        result = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
        if self._first_content_page_index is not None:
            content_end_index = self._content_end_index()
            result = [
                row
                for row in result
                if int(row.get("pageIndex", -1)) >= self._first_content_page_index
                and (content_end_index is None or int(row.get("pageIndex", -1)) <= content_end_index)
            ]
        page_indices = [int(row.get("pageIndex", -1)) for row in result]
        if page_indices:
            self._last_active_max_page_index = max(page_indices)
        return result

    def _content_end_index(self) -> int | None:
        if self._first_content_page_index is None or self._content_page_count is None:
            return None
        return self._first_content_page_index + self._content_page_count - 1

    def _all_main_content_captured(self) -> bool:
        content_end_index = self._content_end_index()
        return (
            self._content_page_count is not None
            and self._first_content_page_index is not None
            and self._captured_content_page_count >= self._content_page_count
            and self._last_active_max_page_index is not None
            and content_end_index is not None
            and self._last_active_max_page_index >= content_end_index
        )

    @staticmethod
    def _page_index(rows: list[dict[str, object]]) -> int | None:
        indices = [int(row.get("pageIndex", -1)) for row in rows if int(row.get("pageIndex", -1)) >= 0]
        return min(indices) if indices else None

    async def _read_content_page_count(self, page: Page) -> None:
        try:
            count = await page.evaluate(
                """() => {
                    const element = document.querySelector('#episode-json');
                    if (!element) return null;
                    const raw = element.dataset.value || element.getAttribute('data-value');
                    if (!raw) return null;
                    const value = JSON.parse(raw);
                    const pages = value?.readableProduct?.pageStructure?.pages;
                    return Array.isArray(pages) ? pages.filter(item => item?.type === 'main').length : null;
                }"""
            )
        except Exception:  # noqa: BLE001 - total is an optional end signal
            count = None
        if isinstance(count, int) and count > 0:
            self._content_page_count = count

    @staticmethod
    def _signature(rows: list[dict[str, object]]) -> tuple[object, ...]:
        return tuple((row.get("canvasId"), (row.get("source") or {}).get("sourceId") if isinstance(row.get("source"), dict) else None,
                      (row.get("source") or {}).get("sourceUrl") if isinstance(row.get("source"), dict) else None,
                      tuple((item.get("sequence"), item.get("sourceUrl")) for item in row.get("mapping", []) if isinstance(item, dict))) for row in rows)

    async def _wait_for_render_ready(self, page: Page) -> list[dict[str, object]]:
        previous: tuple[object, ...] | None = None
        stable = 0
        elapsed = 0
        while elapsed < self.page_change_timeout_ms:
            rows = await self._rows(page)
            signature = self._signature(rows)
            if rows and signature == previous:
                stable += 1
                if stable >= self.render_stable_checks:
                    return rows
            else:
                stable = 0
            previous = signature
            await page.wait_for_timeout(100)
            elapsed += 100
        raise PageChangeTimeoutError("Jump+ viewer did not finish loading within the timeout")

    async def _initial_viewer_state(self, page: Page) -> str:
        try:
            state = await asyncio.wait_for(
                page.evaluate(
                    """() => {
                        const visible = (element) => {
                            if (!element) return false;
                            const rect = element.getBoundingClientRect();
                            return rect.width > 0 && rect.height > 0 &&
                                rect.bottom > 0 && rect.right > 0 &&
                                rect.left < innerWidth && rect.top < innerHeight;
                        };
                        const viewer = document.querySelector('section.viewer.js-viewer');
                        const container = viewer?.querySelector('.image-container.js-viewer-content');
                        const areas = container ? [...container.querySelectorAll('.page-area.js-page-area')] : [];
                        const visibleIndex = areas.findIndex(visible);
                        const forward = [...document.querySelectorAll('.page-navigation-forward.js-slide-forward')]
                            .filter(visible);
                        const backward = [...document.querySelectorAll('.page-navigation-backward.js-slide-backward')];
                        const backwardDisabled = backward.length === 1 && (
                            !visible(backward[0]) ||
                            backward[0].getAttribute('aria-disabled') === 'true' ||
                            backward[0].hasAttribute('disabled') ||
                            backward[0].classList.contains('disabled') ||
                            backward[0].classList.contains('is-disabled') ||
                            backward[0].classList.contains('hidden') ||
                            getComputedStyle(backward[0]).display === 'none'
                        );
                        return {
                            viewerVisible: visible(viewer),
                            visibleIndex,
                            forwardCount: forward.length,
                            backwardCount: backward.length,
                            backwardDisabled,
                            url: location.href,
                        };
                    }"""
                ),
                timeout=2,
            )
        except Exception:  # noqa: BLE001 - render race remains unknown
            return "unknown"
        if not isinstance(state, dict):
            return "unknown"
        if self._initial_url is not None and state.get("url") != self._initial_url:
            return "unsupported"
        if (
            state.get("viewerVisible") is True
            and state.get("forwardCount") == 1
            and state.get("backwardCount") == 1
            and state.get("backwardDisabled") is True
        ):
            return "start"
        return "unknown"

    async def _wait_for_initial_viewer_state(
        self, page: Page
    ) -> tuple[str, list[dict[str, object]]]:
        elapsed = 0
        while elapsed < self.page_change_timeout_ms:
            rows = await self._rows(page)
            if rows:
                return "content", rows
            state = await self._initial_viewer_state(page)
            if state == "start":
                return state, []
            if state == "unsupported":
                raise PageChangeTimeoutError("Jump+ initial viewer state changed or is unsupported")
            await page.wait_for_timeout(100)
            elapsed += 100
        raise PageChangeTimeoutError("Jump+ initial viewer state was not ready within the timeout")

    async def _control_available(self, button: Locator) -> bool:
        if await button.count() != 1 or not await button.is_visible():
            return False
        aria_disabled = await button.get_attribute("aria-disabled")
        if aria_disabled == "true" or await button.get_attribute("disabled") is not None:
            return False
        classes = set((await button.get_attribute("class") or "").split())
        return not classes & {"disabled", "is-disabled", "hidden"}

    async def _click_forward(self, page: Page) -> None:
        button = page.locator(self.forward_selector)
        if not await self._control_available(button):
            raise PageChangeTimeoutError("Jump+ forward control was not uniquely visible")
        values = [
            await button.inner_text(),
            await button.get_attribute("aria-label"),
            await button.get_attribute("title"),
            await button.get_attribute("class"),
            await button.get_attribute("href"),
        ]
        if _FORBIDDEN.search(" ".join(str(value or "") for value in values)) or values[-1] and "/episode/" in values[-1]:
            raise PageChangeTimeoutError("Jump+ forward control failed navigation safety validation")
        interceptor = page.locator(".js-slide-to-transit-guide")
        elapsed = 0
        while await interceptor.count() and await interceptor.is_visible():
            if elapsed >= self.forward_interceptor_wait_ms:
                raise PageChangeTimeoutError("Jump+ forward control was covered by a transit guide")
            await page.wait_for_timeout(100)
            elapsed += 100
        self._advance_pending = True
        await button.click(timeout=1_000, no_wait_after=True)

    async def _has_preceding_page_areas(
        self, page: Page, rows: list[dict[str, object]]
    ) -> bool | None:
        page_index = self._page_index(rows)
        if page_index is None:
            return None
        try:
            result = await page.evaluate(
                """(index) => {
                    const container = document.querySelector(
                        'section.viewer.js-viewer .image-container.js-viewer-content'
                    );
                    const areas = container
                        ? [...container.querySelectorAll('.page-area.js-page-area')]
                        : [];
                    return areas.length > 0 && index > 0;
                }""",
                page_index,
            )
        except Exception:  # noqa: BLE001 - structure is only a rewind hint
            return None
        return result if isinstance(result, bool) else None

    async def _rewind_to_first(self, page: Page) -> bool:
        previous_rows = await self._rows(page)
        for _ in range(self.rewind_max_steps):
            if not previous_rows:
                return False
            preceding_areas = await self._has_preceding_page_areas(page, previous_rows)
            if preceding_areas is False:
                self._first_content_page_index = self._page_index(previous_rows)
                return self._first_content_page_index is not None
            backward = page.locator("section.viewer.js-viewer .page-navigation-backward.js-slide-backward")
            backward_available = await self._control_available(backward)
            if not backward_available:
                self._first_content_page_index = self._page_index(previous_rows)
                return self._first_content_page_index is not None

            previous = self._signature(previous_rows)
            previous_position = tuple(int(row.get("pageIndex", -1)) for row in previous_rows)
            before_url = page.url
            await backward.click(timeout=1_000, no_wait_after=True)
            current_rows: list[dict[str, object]] | None = None
            unchanged_checks = 0
            elapsed = 0
            while elapsed < self.page_change_timeout_ms:
                if page.url != before_url:
                    raise PageChangeTimeoutError("Jump+ rewind changed the episode URL")
                candidate = await self._rows(page)
                if candidate:
                    candidate_signature = self._signature(candidate)
                    candidate_position = tuple(int(row.get("pageIndex", -1)) for row in candidate)
                    if (candidate_signature, candidate_position) != (previous, previous_position):
                        current_rows = candidate
                        break
                    unchanged_checks += 1
                    if unchanged_checks >= self.render_stable_checks:
                        self._first_content_page_index = self._page_index(previous_rows)
                        return self._first_content_page_index is not None
                if not candidate and await self._initial_viewer_state(page) == "start":
                    break
                await page.wait_for_timeout(100)
                elapsed += 100

            if current_rows:
                previous_rows = current_rows
                continue

            # The first content page may be preceded by a non-content area.
            # Preserve the rows from before the backward click, restore them
            # through the validated viewer-forward control, and derive the
            # runtime index from the restored content rather than a threshold.
            if await self._initial_viewer_state(page) != "start":
                return False
            await self._click_forward(page)
            self._advance_pending = False
            restored_rows = await self._wait_for_render_ready(page)
            if not restored_rows:
                return False
            self._first_content_page_index = self._page_index(restored_rows)
            return self._first_content_page_index is not None

        return False

    async def initialize(self, page: Page) -> None:
        self._initial_url = page.url
        self._initial_parts = parse_jumpplus_url(page.url)
        if self._initial_parts is None:
            raise ValueError("Jump+ page URL is not an episode URL")
        self._advance_pending = False
        self._terminal_reached = False
        self._captured_content_page_count = 0
        self._first_content_page_index = None
        self._last_active_max_page_index = None
        await self._read_content_page_count(page)
        initial_state, _initial_rows = await self._wait_for_initial_viewer_state(page)
        if initial_state == "content":
            if not await self._rewind_to_first(page):
                raise PageChangeTimeoutError("Jump+ could not rewind to the first content page")
        else:
            # The live target exposes a distinct pre-content page-area state:
            # the first non-content area is visible, the unique backward
            # control is hidden/disabled, and the unique viewer-forward control
            # is visible.  Only this state
            # permits one startup forward action.
            await self.go_next(page)
            self._advance_pending = False
        rows = await self._wait_for_render_ready(page)
        if not rows:
            raise PageChangeTimeoutError("Jump+ active content was not found")
        if self._first_content_page_index is None:
            self._first_content_page_index = self._page_index(rows)
        if self._first_content_page_index is None:
            raise PageChangeTimeoutError("Jump+ first content page index was not observable")
        await self._read_output_metadata(page)

    async def _read_output_metadata(self, page: Page) -> None:
        async def text(selector: str) -> str | None:
            locator = page.locator(selector)
            if await locator.count() != 1:
                return None
            value = " ".join((await locator.inner_text()).split()).strip()
            return value or None
        self._output_title = await text(".series-header-title")
        self._output_author = await text(".series-header-author")
        self._output_order = await text(".episode-header-title")
        if self._output_order and self._output_title and self._output_order == self._output_title:
            self._output_order = None

    def get_output_metadata(self) -> dict[str, str | None]:
        return {"title": self._output_title, "author": self._output_author, "order": self._output_order, "genre": "漫画"}

    async def _terminal_signature(self, page: Page) -> tuple[object, ...] | None:
        button = page.locator(self.forward_selector)
        if await button.count() != 1 or not await button.is_visible():
            return None
        aria_disabled = await button.get_attribute("aria-disabled")
        disabled = await button.get_attribute("disabled")
        classes = (await button.get_attribute("class") or "").split()
        if aria_disabled != "true" and disabled is None and not ({"disabled", "is-disabled"} & set(classes)):
            return None
        return (aria_disabled, disabled, tuple(sorted(classes)))

    async def detect_state(self, page: Page) -> PageState:
        current = parse_jumpplus_url(page.url)
        if self._initial_parts is not None and current is not None and current != self._initial_parts:
            return PageState.NEXT_CONTENT
        if self._terminal_reached:
            return PageState.END
        rows = await self._rows(page)
        if rows:
            return PageState.CONTENT
        if self._all_main_content_captured():
            return PageState.END
        viewer = page.locator(self.viewer_selector)
        if await viewer.count() and await viewer.is_visible(timeout=500):
            return PageState.LOADING
        return PageState.UNKNOWN

    async def get_capture_target(self, page: Page) -> Locator:
        targets = await self.get_capture_targets(page)
        return targets[0]

    async def get_capture_targets(self, page: Page) -> tuple[Locator, ...]:
        rows = await self._rows(page)
        if not rows:
            raise LookupError("Jump+ active canvas is not visible")
        locator = page.locator(self.canvas_selector)
        return tuple(locator.nth(int(row["index"])) for row in rows)

    async def _source_candidates(self) -> list[dict[str, object]]:
        tasks = list(self._source_tasks.values())
        if tasks:
            await asyncio.wait(tasks, timeout=self.source_response_wait_timeout_ms / 1000)
        candidates: list[dict[str, object]] = []
        for url, task in list(self._source_tasks.items()):
            if not task.done() or task.cancelled():
                continue
            try:
                data = task.result()
                if data is None or jpeg_dimensions(data) is None:
                    continue
                candidates.append({"url": url, "data": data, "pixel_sha256": decoded_pixel_sha256(data)})
            except Exception:  # noqa: BLE001, S112 - invalid candidate is ignored
                continue
        return candidates

    async def _snapshot_sources(self, page: Page, wanted: list[dict[str, object]]) -> dict[tuple[object, str], bytes]:
        if not wanted:
            return {}
        payload = await page.evaluate("wanted => window.__jumpplusProductionCapture.snapshotSources(wanted)", wanted)
        result: dict[tuple[object, str], bytes] = {}
        for item in payload if isinstance(payload, list) else []:
            if not isinstance(item, dict) or item.get("error") or item.get("changed"):
                continue
            data_url = item.get("dataUrl")
            if not isinstance(data_url, str) or not data_url.startswith("data:image/png;base64,"):
                continue
            try:
                result[(item.get("sourceId"), str(item.get("sourceUrl") or ""))] = base64.b64decode(data_url.split(",", 1)[1])
            except (ValueError, TypeError):
                continue
        return result

    @staticmethod
    def _native_candidate_status(status: object) -> bool:
        return status in {"unique", "equivalent_multiple"}

    async def _native_attempt(
        self,
        page: Page,
        rows: list[dict[str, object]],
        candidates: list[dict[str, object]],
    ) -> tuple[tuple[CaptureResult, ...] | None, str | None, list[str], set[str]]:
        wanted: list[dict[str, object]] = []
        for row in rows:
            source = row.get("source")
            if isinstance(source, dict):
                wanted.append({"sourceId": source.get("sourceId"), "sourceUrl": source.get("sourceUrl")})
        snapshots = await self._snapshot_sources(page, wanted)
        records: list[tuple[dict[str, object], dict[str, object], bytes]] = []
        selections: list[str] = []
        used_source_urls: set[str] = set()
        for row in rows:
            source = row.get("source")
            base, mapping, visible = row.get("base"), row.get("mapping"), row.get("visibleDraw")
            if not isinstance(source, dict) or not isinstance(base, dict) or not isinstance(visible, dict) or not isinstance(mapping, list):
                return None, "draw_mapping_unavailable", selections, used_source_urls
            if any(isinstance(item, dict) and item.get("operation") in {"clearRect","fillRect","putImageData","strokeRect","fillText","strokeText","fill","stroke"} for item in row.get("mutations", [])):
                return None, "unsupported_canvas_mutation", selections, used_source_urls
            source_key = (source.get("sourceId"), str(source.get("sourceUrl") or ""))
            snapshot = snapshots.get(source_key)
            if snapshot is None:
                return None, "source_snapshot_unavailable_or_changed", selections, used_source_urls
            selection = select_transport_candidate(decoded_pixel_sha256(snapshot), candidates, load_bytes=lambda item: item["data"], analyze_candidate=_dct_signature)
            status = str(selection["selection_status"])
            selections.append(status)
            candidate = selection.get("selected_candidate") or selection.get("pixel_fallback_candidate")
            if not isinstance(candidate, dict):
                return None, "unmatched_transport_candidate", selections, used_source_urls
            candidate_url = candidate.get("url")
            if isinstance(candidate_url, str):
                used_source_urls.add(candidate_url)
            records.append((row, selection, candidate["data"]))
        dct_results: list[CaptureResult] = []
        if all(self._native_candidate_status(status) for status in selections):
            for row, _selection, data in records:
                result = reconstruct_jpeg_lossless(data, base=row["base"], mappings=row["mapping"], visible_draw=row["visibleDraw"], source_path=str(row["source"]["sourceUrl"]), canvas_size=(int(row["canvasWidth"]), int(row["canvasHeight"])))
                if result is None:
                    break
                dct_results.append(result)
            else:
                return tuple(dct_results), None, selections, used_source_urls
        png_results: list[CaptureResult] = []
        for row, _selection, data in records:
            result = reconstruct_jpeg_png(data, base=row["base"], mappings=row["mapping"], visible_draw=row["visibleDraw"], source_path=str(row["source"]["sourceUrl"]), canvas_size=(int(row["canvasWidth"]), int(row["canvasHeight"])))
            if result is None:
                return None, "safe_pixel_reconstruction_unavailable", selections, used_source_urls
            png_results.append(result)
        return tuple(png_results), None, selections, used_source_urls

    async def capture_page(self, page: Page) -> tuple[CaptureResult, ...] | None:
        fallback_targets: tuple[Locator, ...] = ()
        last_reason = "no_active_canvas"
        selections: list[str] = []
        used_source_urls: set[str] = set()
        try:
            for attempt in range(self.capture_retry_count + 1):
                rows = await self._rows(page)
                page_indices = [int(row.get("pageIndex", -1)) for row in rows]
                if page_indices:
                    self._last_active_max_page_index = max(page_indices)
                if rows:
                    fallback_targets = tuple(page.locator(self.canvas_selector).nth(int(row["index"])) for row in rows)
                    candidates = await self._source_candidates()
                    try:
                        captures, reason, current_selections, current_used_urls = await self._native_attempt(page, rows, candidates)
                    except Exception:  # noqa: BLE001 - native capture is a safe fallback boundary
                        captures, reason, current_selections, current_used_urls = None, "native_capture_error", [], set()
                    selections = current_selections
                    used_source_urls.update(current_used_urls)
                    if captures is not None:
                        self._captured_content_page_count += len(rows)
                        self._capture_debug = {"capture_method": "jpeg_dct" if all(c.mime_type == "image/jpeg" for c in captures) else "png_reconstruction", "candidate_selection": selections, "canvas_count": len(rows), "source_count": len({(row.get("source") or {}).get("sourceId") for row in rows if isinstance(row.get("source"), dict)}), "fallback_reason": None}
                        return captures
                    last_reason = reason or last_reason
                if attempt < self.capture_retry_count and last_reason in {"no_active_canvas", "draw_mapping_unavailable", "source_snapshot_unavailable_or_changed", "unmatched_transport_candidate"}:
                    await page.wait_for_timeout(self.capture_retry_interval_ms)
                    continue
                break
        finally:
            for url in used_source_urls:
                await self._discard_source(url)
        if not fallback_targets:
            self._capture_debug = {"capture_method": "screenshot", "candidate_selection": selections or ["unmatched"], "canvas_count": 0, "source_count": 0, "fallback_reason": last_reason}
            return None
        self._capture_debug = {"capture_method": "screenshot", "candidate_selection": selections or ["unmatched"], "canvas_count": len(fallback_targets), "source_count": len(fallback_targets), "fallback_reason": last_reason}
        # A spread is intentionally all-fallback; native/screenshot provenance is never mixed.
        self._captured_content_page_count += len(fallback_targets)
        return tuple([await capture_locator(target) for target in fallback_targets])

    async def get_content_identity(self, page: Page) -> ContentIdentity:
        rows = await self._rows(page)
        page_indices = [int(row.get("pageIndex", -1)) for row in rows]
        if page_indices:
            self._last_active_max_page_index = max(page_indices)
        page_id = "|".join(f"{row.get('canvasId')}:{(row.get('source') or {}).get('sourceId') if isinstance(row.get('source'), dict) else None}:{(row.get('source') or {}).get('sourceUrl') if isinstance(row.get('source'), dict) else None}:{tuple(item.get('sequence') for item in row.get('mapping', []) if isinstance(item, dict))}" for row in rows) or None
        source_id = self._initial_parts.episode_id if self._initial_parts else None
        return ContentIdentity(page_id=page_id, page_number=None, source_id=source_id)

    async def get_content_context(self, page: Page) -> ContentContext:
        parts = parse_jumpplus_url(page.url)
        title = self._output_title
        if title is None:
            try:
                title = (await page.title()).split(" - ", 1)[0].strip() or None
            except Exception:  # noqa: BLE001
                title = None
        return ContentContext(content_id=parts.episode_id if parts else None, episode_id=parts.episode_id if parts else None, title=title)

    async def go_next(self, page: Page) -> None:
        if self._all_main_content_captured():
            self._terminal_reached = True
            self._advance_pending = False
            return
        await self._click_forward(page)

    async def wait_for_change(self, page: Page, previous_identity: ContentIdentity | None) -> None:
        if self._terminal_reached:
            return
        if previous_identity is None:
            await self._wait_for_render_ready(page)
            return
        elapsed = 0
        last_identity: ContentIdentity | None = None
        stable = 0
        terminal_previous = None
        terminal_stable = 0
        while elapsed < self.page_change_timeout_ms:
            current_parts = parse_jumpplus_url(page.url)
            if self._initial_parts is not None and current_parts is not None and current_parts != self._initial_parts:
                return
            current = await self.get_content_identity(page)
            current_rows = await self._rows(page)
            if (
                self._advance_pending
                and self._all_main_content_captured()
                and (not current_rows or current == previous_identity)
            ):
                self._terminal_reached = True
                self._advance_pending = False
                return
            if current.page_id and current != previous_identity:
                if current == last_identity:
                    stable += 1
                    if stable >= self.render_stable_checks and current_rows:
                        self._advance_pending = False
                        return
                else:
                    last_identity, stable = current, 0
            terminal = await self._terminal_signature(page)
            if terminal is not None and terminal == terminal_previous:
                terminal_stable += 1
                if terminal_stable >= self.render_stable_checks and self._advance_pending and self._all_main_content_captured():
                    self._terminal_reached = True
                    self._advance_pending = False
                    return
            else:
                terminal_previous, terminal_stable = terminal, 0
            await page.wait_for_timeout(100)
            elapsed += 100
        raise PageChangeTimeoutError("Jump+ viewer page did not become different and stable")

    async def collect_debug_metadata(self, page: Page) -> dict[str, Any]:
        debug = dict(self._capture_debug)
        try:
            debug["renderer"] = await page.evaluate("() => window.__jumpplusProductionCapture ? window.__jumpplusProductionCapture.debug() : {}")
        except Exception:  # noqa: BLE001
            debug["renderer"] = {}
        return {"jumpplus_capture": debug}
