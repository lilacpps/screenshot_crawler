"""Free-only Piccoma viewer adapter, bound to a freshly checked source."""

from __future__ import annotations

import asyncio
import math
import re
import time
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Locator, Page, Response
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from screenshot_crawler.core.access_guard import AccessProfile
from screenshot_crawler.core.capture import CaptureResult, capture_locator
from screenshot_crawler.core.errors import (
    AccessResourceUnavailableError,
    PageChangeTimeoutError,
    UnknownPageStateError,
    UnsupportedAccessStrategyError,
)
from screenshot_crawler.core.models import AccessStrategy, ContentContext, ContentIdentity
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.base import SiteAdapter
from screenshot_crawler.site_adapters.piccoma.access import piccoma_access_profile
from screenshot_crawler.site_adapters.piccoma.discovery import (
    PiccomaEpisodeIdentity,
    canonical_piccoma_viewer_url,
    classify_piccoma_access,
    parse_piccoma_listing_url,
    parse_piccoma_viewer_url,
)
from screenshot_crawler.site_adapters.piccoma.native_capture import (
    NativeCaptureUnavailable,
    capture_native_tile_replay,
    capture_result_format_is_valid,
    install_native_trace,
    retire_native_trace,
    snapshot_native_trace,
    target_generation_signature,
    validate_native_capture_still_current,
)

LISTING_SELECTOR = "#js_episodeList"
ROW_SELECTOR = "#js_episodeList a[data-product_id][data-episode_id]"
NEXT_SELECTOR = "button.PCM-viewer2_pagingBtn_next"
PREVIOUS_SELECTOR = "button.PCM-viewer2_pagingBtn_prev"
GUIDE_SELECTOR = "#js_scrollTypeSing"
RESUME_DIALOG_SELECTOR = ".jconfirm-open.PCM-pcmConfirm"

VIEWPORT_WIDTH = 1904
VIEWPORT_HEIGHT = 1200
# Chrome may expose a tiny floating-point DPR error around the observed 1x
# viewport. Keep the supported mode narrowly centered on 1x.
DEVICE_PIXEL_RATIO_TOLERANCE = 1e-7
MAX_BODY_PAGES = 2_000
MAX_NATIVE_RESPONSE_RECORDS = 512
MAX_NATIVE_EPISODE_BYTES = 64_000_000
PAGE_CHANGE_TIMEOUT_MS = 10_000
INITIALIZE_TIMEOUT_MS = 30_000
RESUME_DIALOG_GRACE_MS = 1_500
_BODY_PAGE_ID = re.compile(r"p([1-9][0-9]*)\Z")
_KNOWN_GUIDE_TREE = {
    "tag": "DIV",
    "classes": ["PCM-viewer2_scrollTypeSign"],
    "alt": None,
    "significantTextNodeCount": 0,
    "children": [
        {
            "tag": "DIV",
            "classes": ["PCM-viewer2_scrollTypeSign_v"],
            "alt": None,
            "significantTextNodeCount": 0,
            "children": [
                {
                    "tag": "IMG",
                    "classes": [],
                    "alt": "\u30bf\u30c6\u8aad\u307f",
                    "significantTextNodeCount": 0,
                    "children": [],
                }
            ],
        },
        {
            "tag": "DIV",
            "classes": ["PCM-viewer2_scrollTypeSign_h"],
            "alt": None,
            "significantTextNodeCount": 0,
            "children": [
                {
                    "tag": "IMG",
                    "classes": ["PCM-viewer2_scrollTypeSign_l"],
                    "alt": "\u30e8\u30b3\u8aad\u307f",
                    "significantTextNodeCount": 0,
                    "children": [],
                },
                {
                    "tag": "IMG",
                    "classes": ["PCM-viewer2_scrollTypeSign_r"],
                    "alt": "\u30e8\u30b3\u8aad\u307f",
                    "significantTextNodeCount": 0,
                    "children": [],
                },
            ],
        },
    ],
}
_KNOWN_GUIDE_INITIAL_TREE = {
    **_KNOWN_GUIDE_TREE,
    "classes": [
        "PCM-viewer2_scrollTypeSign",
        "PCM-viewer2_scrollTypeSign_sh",
        "PCM-viewer2_scrollTypeSign_show",
    ],
}
_KNOWN_GUIDE_TREES = (_KNOWN_GUIDE_TREE, _KNOWN_GUIDE_INITIAL_TREE)
_RESUME_TEXT = re.compile(
    r"(?:\u524d\u56de[0-9]+\u30da\u30fc\u30b8\u3092\u8aad\u3093\u3067\u3044\u307e\u3057\u305f\u3002 "
    r"[0-9]+\u30da\u30fc\u30b8\u306b\u79fb\u52d5\u3057\u307e\u3059\u304b\uff1f|"
    r"\u524d\u56de\u6700\u5f8c\u306e\u30da\u30fc\u30b8\u3092 \u8aad\u3093\u3067\u3044\u307e\u3057\u305f\u3002 "
    r"\u6700\u5f8c\u306e\u30da\u30fc\u30b8\u306b\u79fb\u52d5\u3057\u307e\u3059\u304b\uff1f) "
    r"\u79fb\u52d5\u3059\u308b \u30ad\u30e3\u30f3\u30bb\u30eb\Z"
)


def _png_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


class PiccomaAdapter(SiteAdapter):
    """Capture only exact-free episodes through the observed horizontal reader."""

    page_change_timeout_ms = PAGE_CHANGE_TIMEOUT_MS
    _reader_snapshot_js = r"""() => {
      const root = document.querySelectorAll('#react_ViewerApp');
      const pageList = document.querySelectorAll('#react_PageListApp');
      const frame = document.querySelectorAll('#js_frame.PCM-viewer2_frame');
      const pages = [...document.querySelectorAll('#react_PageListApp .PCM-viewer2_pageWrapper')];
      const pageRows = pages.map(node => {
        const canvasWrappers = [...node.querySelectorAll('.PCM-viewer2_canvasWrapper')];
        const canvases = [...node.querySelectorAll('canvas')];
        const canvas = canvases.length === 1 ? canvases[0] : null;
        const r = canvas?.getBoundingClientRect();
        const f = frame[0]?.getBoundingClientRect();
        const s = canvas ? getComputedStyle(canvas) : null;
        const renderability = element => {
          const ancestors = [];
          for (let node = element; node; node = node.parentElement) {
            const style = getComputedStyle(node);
            ancestors.push({
              display: style.display,
              visibility: style.visibility,
              opacity: Number(style.opacity),
              contentVisibility: style.contentVisibility
            });
          }
          return {
            visible: ancestors.length > 0 && ancestors.every(item =>
              item.display !== 'none' && item.visibility === 'visible' &&
              item.opacity === 1 && item.contentVisibility !== 'hidden'
            ),
            ancestors
          };
        };
        return {
          id: node.id || '',
          classes: [...node.classList],
          hasEnd: !!node.querySelector('#js_viewerEnd.PCM-viewer2_endPage'),
          canvasCount: canvases.length,
          loadedCount: canvasWrappers.filter(item => item.classList.contains('loaded')).length,
          canvas: canvas && r && s ? {
            width: canvas.width,
            height: canvas.height,
            rect: [r.x, r.y, r.width, r.height],
            css: [s.width, s.height, s.display, s.visibility],
            renderability: renderability(canvas),
            inFrame: !!f && r.x >= f.x - 0.5 && r.y >= f.y - 0.5 &&
              r.right <= f.right + 0.5 && r.bottom <= f.bottom + 0.5,
            loaded: canvasWrappers.length === 1 && canvasWrappers[0].classList.contains('loaded')
          } : null
        };
      });
      const visible = element => {
        const r = element.getBoundingClientRect();
        const s = getComputedStyle(element);
        return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
      };
      const guides = [...document.querySelectorAll('#js_scrollTypeSing')];
      const guide = guides.length === 1 ? guides[0] : null;
      const guideTree = node => ({
        tag: node.tagName,
        classes: [...node.classList].sort(),
        alt: node.tagName === 'IMG' ? node.alt : null,
        significantTextNodeCount: [...node.childNodes].filter(
          child => child.nodeType === Node.TEXT_NODE && child.textContent.trim()
        ).length,
        children: [...node.children].map(guideTree)
      });
      const guideParts = guide ? {
        tag: guide.tagName,
        sign: guide.classList.contains('PCM-viewer2_scrollTypeSign'),
        vertical: guide.querySelectorAll(':scope > .PCM-viewer2_scrollTypeSign_v').length,
        horizontal: guide.querySelectorAll(':scope > .PCM-viewer2_scrollTypeSign_h').length,
        verticalLabels: [...guide.querySelectorAll(':scope > .PCM-viewer2_scrollTypeSign_v img')].map(n => n.alt),
        horizontalLabels: [...guide.querySelectorAll(':scope > .PCM-viewer2_scrollTypeSign_h img')].map(n => n.alt),
        interactiveCount: guide.querySelectorAll('a,button,input,[role=button]').length,
        tree: guideTree(guide),
        pseudoBefore: getComputedStyle(guide, '::before').content,
        pseudoAfter: getComputedStyle(guide, '::after').content,
        visible: visible(guide)
      } : null;
      const active = pageRows.filter(item => item.classes.includes('current'));
      const next = [...document.querySelectorAll('button.PCM-viewer2_pagingBtn_next')];
      const previous = [...document.querySelectorAll('button.PCM-viewer2_pagingBtn_prev')];
      const frameRect = frame[0]?.getBoundingClientRect();
      const canvasRect = (active.length === 1 ? active[0].canvas?.rect : null);
      return {
        rootCount: root.length,
        pageListCount: pageList.length,
        frameCount: frame.length,
        bodyClasses: [...document.body.classList],
        horizontal: document.body.classList.contains('PCM-stt_horizontal'),
        leftToRight: document.body.classList.contains('PCM-prop_scroll_l'),
        pageIds: pageRows.map(item => item.id),
        pages: pageRows,
        activeIds: active.map(item => item.id),
        activeHasEnd: active.length === 1 && active[0].hasEnd,
        nextCount: next.length,
        nextDisabled: next.length === 1 && (next[0].disabled || next[0].getAttribute('aria-disabled') === 'true'),
        nextVisible: next.length === 1 && visible(next[0]),
        previousCount: previous.length,
        previousDisabled: previous.length === 1 && (previous[0].disabled || previous[0].getAttribute('aria-disabled') === 'true'),
        previousVisible: previous.length === 1 && visible(previous[0]),
        dialogCount: document.querySelectorAll('.jconfirm-open').length,
        guideCount: guides.length,
        guide: guideParts,
        viewport: [innerWidth, innerHeight, devicePixelRatio],
        frameRect: frameRect ? [frameRect.x, frameRect.y, frameRect.width, frameRect.height] : null,
        activeCanvasRect: canvasRect
      };
    }"""

    def __init__(self) -> None:
        self._access_strategy: AccessStrategy = "direct"
        self._source_identity: PiccomaEpisodeIdentity | None = None
        self._configured_external_id: str | None = None
        self._work_key: str | None = None
        self._title: str | None = None
        self._page_count: int | None = None
        self._expected_page_id: str | None = None
        self._terminal = False
        self._advance_from: int | None = None
        self._capture_method = "not_captured"
        self._capture_source_native = False
        self._capture_source_mime: str | None = None
        self._capture_backdrop: str | None = None
        self._capture_fallback_reason: str | None = None
        self._capture_encoding_fallback_reason: str | None = None
        self._capture_output_format: str | None = None
        self._capture_output_lossless: bool | None = None
        self._capture_page: Page | None = None
        self._response_listener: Any = None
        self._native_responses: dict[str, list[Response]] = {}
        self._native_response_counts: dict[str, int] = {}
        self._native_response_count = 0
        self._native_response_overflow = False
        self._native_response_event = asyncio.Event()
        self._native_bytes_read = 0

    def get_access_profile(self) -> AccessProfile:
        return piccoma_access_profile()

    def get_initialize_timeout_ms(self, default_ms: int) -> int:
        return max(default_ms, INITIALIZE_TIMEOUT_MS)

    async def prepare_page(self, page: Page) -> None:
        # The observed desktop horizontal reader renders native 1200px canvas
        # height only when its owned Page starts at this viewport.
        await page.set_viewport_size({"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT})
        await install_native_trace(page)
        self._capture_page = page
        self._native_responses = {}
        self._native_response_counts = {}
        self._native_response_count = 0
        self._native_response_overflow = False
        self._native_bytes_read = 0
        self._native_response_event = asyncio.Event()
        self._response_listener = self._on_native_response
        page.on("response", self._response_listener)
        page.on("close", self._clear_native_response_state)

    def _on_native_response(self, response: Response) -> None:
        """Retain only bounded first-party CDN image responses, without reading bodies."""

        try:
            parsed = urlparse(response.url)
            if (
                parsed.scheme != "https"
                or parsed.hostname != "pcm.kakaocdn.net"
                or response.request.resource_type != "image"
            ):
                return
            if self._native_response_count >= MAX_NATIVE_RESPONSE_RECORDS:
                self._native_response_overflow = True
                return
            self._native_response_count += 1
            if response.url not in self._native_response_counts:
                if len(self._native_response_counts) >= MAX_NATIVE_RESPONSE_RECORDS:
                    self._native_response_overflow = True
                    return
                self._native_response_counts[response.url] = 1
            else:
                self._native_response_counts[response.url] = min(
                    2, self._native_response_counts[response.url] + 1
                )
            rows = self._native_responses.setdefault(response.url, [])
            if len(rows) < 2:
                rows.append(response)
            self._native_response_event.set()
        except Exception:  # noqa: BLE001 - response observation never blocks the reader
            return

    def _clear_native_response_state(self, *_args: object) -> None:
        self._native_responses.clear()
        self._native_response_counts.clear()
        self._native_response_event.set()

    def _native_response_count_for_url(self, source_url: str) -> int:
        return self._native_response_counts.get(source_url, 0)

    async def _responses_for_native_url(self, source_url: str) -> list[Response]:
        deadline = time.monotonic() + 1.5
        while True:
            rows = self._native_responses.pop(source_url, None)
            if rows:
                return rows
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return []
            self._native_response_event.clear()
            # Recheck after clearing so a response cannot be lost between the
            # map lookup and event reset.
            rows = self._native_responses.pop(source_url, None)
            if rows:
                return rows
            try:
                await asyncio.wait_for(self._native_response_event.wait(), timeout=remaining)
            except TimeoutError:
                return []

    async def configure_run(self, page: Page, access_strategy: AccessStrategy) -> None:
        del page
        if access_strategy not in {"auto", "direct"}:
            raise UnsupportedAccessStrategyError(
                "Piccoma supports only auto/direct for freshly verified free episodes"
            )
        self._access_strategy = access_strategy
        self._source_identity = None
        self._title = None
        self._page_count = None
        self._expected_page_id = None
        self._terminal = False
        self._advance_from = None
        self._capture_method = "not_captured"
        self._capture_source_native = False
        self._capture_source_mime = None
        self._capture_backdrop = None
        self._capture_fallback_reason = None
        self._capture_encoding_fallback_reason = None
        self._capture_output_format = None
        self._capture_output_lossless = None

    async def configure_target_identity(self, external_id: str, work_key: str) -> None:
        match = re.fullmatch(r"([0-9]+):([0-9]+)", external_id)
        if match is None or not isinstance(work_key, str):
            raise ValueError("Piccoma batch identity must be a product:episode ID")
        self._configured_external_id = external_id
        self._expected_page_id = None
        # Work keys are caller-owned metadata; they do not encode site identity.
        self._work_key = work_key

    def resolve_initial_navigation_url(self, source_url: str) -> str:
        identity = parse_piccoma_viewer_url(source_url)
        if identity is None:
            raise ValueError("Piccoma source URL is not a supported viewer identity")
        if (
            self._configured_external_id is not None
            and self._configured_external_id != identity.external_id
        ):
            raise ValueError("Piccoma Catalog identity does not match its viewer URL")
        self._source_identity = identity
        return f"https://piccoma.com/web/product/{identity.product_id}/episodes"

    async def initialize(self, page: Page) -> None:
        identity = self._require_identity()
        if parse_piccoma_listing_url(page.url) != identity.product_id:
            raise UnknownPageStateError("Piccoma listing redirected outside the target product")
        await page.locator("#js_contentBody").wait_for(state="visible", timeout=15_000)
        await page.locator(LISTING_SELECTOR).wait_for(state="visible", timeout=15_000)
        access_mode, title = await self._current_listing_access(page, identity)
        if access_mode in {"paid", "quota"}:
            raise AccessResourceUnavailableError(
                "Piccoma target is no longer unconditionally free"
            )
        if access_mode != "free":
            raise UnknownPageStateError("Piccoma target access state is ambiguous")
        self._title = title

        response = await page.goto(
            canonical_piccoma_viewer_url(
                f"https://piccoma.com/web/viewer/{identity.product_id}/{identity.episode_id}"
            ),
            wait_until="domcontentloaded",
            timeout=15_000,
        )
        if parse_piccoma_viewer_url(page.url) != identity:
            raise UnknownPageStateError("Piccoma viewer redirected outside the target episode")
        if response is None or response.status != 200:
            raise UnknownPageStateError("Piccoma viewer did not return HTTP 200")
        await page.wait_for_function(
            """() => !!document.querySelector('#react_ViewerApp') &&
              (!!document.querySelector('.jconfirm-open.PCM-pcmConfirm') ||
               !!document.querySelector(
                 '#react_PageListApp .PCM-viewer2_pageWrapper.current'
               ) ||
               !!document.querySelector(
                 '#last.PCM-viewer2_pageWrapper.current #js_viewerEnd'
               ))""",
            timeout=self.page_change_timeout_ms,
        )
        if await page.locator(".jconfirm-open").count() == 0:
            try:
                await page.locator(".jconfirm-open").wait_for(
                    state="attached", timeout=RESUME_DIALOG_GRACE_MS
                )
            except PlaywrightTimeoutError:
                pass
        await self._dismiss_exact_resume_prompt(page)
        self._page_count = await self._validated_page_count(page)
        await self._normalize_first_page(page)

    async def _current_listing_access(
        self, page: Page, identity: PiccomaEpisodeIdentity
    ) -> tuple[str, str]:
        title_locator = page.locator("#js_contentBody .PCM-headTitle_name")
        if await title_locator.count() != 1:
            raise UnknownPageStateError("Piccoma product title is missing or ambiguous")
        title = " ".join((await title_locator.inner_text()).split())
        if not title:
            raise UnknownPageStateError("Piccoma product title is empty")
        rows = page.locator(ROW_SELECTOR)
        matches = await rows.evaluate_all(
            """(anchors, target) => anchors.filter(anchor =>
              anchor.getAttribute('data-product_id') === target.product &&
              anchor.getAttribute('data-episode_id') === target.episode).map(anchor => {
                const statuses = [...anchor.querySelectorAll('.PCM-epList_status')];
                const status = statuses.length === 1 ? statuses[0] : null;
                const markers = status
                  ? [status, ...status.querySelectorAll('[class]')]
                      .flatMap(node => [...node.classList])
                      .filter(name => name.startsWith('PCM-epList_status_'))
                  : [];
                return {statusCount: statuses.length, markers: [...new Set(markers)],
                  label: (status?.innerText || '').trim()};
              })""",
            {"product": identity.product_id, "episode": identity.episode_id},
        )
        if len(matches) != 1:
            raise UnknownPageStateError("Piccoma target is absent or duplicated in its listing")
        row = matches[0]
        if row.get("statusCount") != 1:
            return "unknown", title
        access_mode = classify_piccoma_access(row.get("markers", []), row.get("label", ""))
        return access_mode, title

    async def _dismiss_exact_resume_prompt(self, page: Page) -> None:
        dialogs = page.locator(RESUME_DIALOG_SELECTOR)
        dialog_count = await dialogs.count()
        if dialog_count == 0:
            if await page.locator(".jconfirm-open").count() != 0:
                raise UnknownPageStateError("Piccoma displayed an unrecognized viewer dialog")
            return
        if dialog_count != 1 or await page.locator(".jconfirm-open").count() != 1:
            raise UnknownPageStateError("Piccoma displayed ambiguous viewer dialogs")
        evidence = await dialogs.evaluate(
            """dialog => {
              const text = (dialog.innerText || '').replace(/\\s+/g, ' ').trim();
              const buttons = [...dialog.querySelectorAll('button')];
              const labels = buttons.map(button => (button.innerText || '').replace(/\\s+/g, ' ').trim());
              const visibleEnabled = buttons.length === 2 && buttons.every(button => {
                const rect = button.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0 && !button.disabled &&
                  button.getAttribute('aria-disabled') !== 'true';
              });
              return {text, labels, anchors: dialog.querySelectorAll('a[href]').length,
                visibleEnabled, structure: dialog.classList.contains('PCM-pcmConfirm')};
            }"""
        )
        if (
            not isinstance(evidence, dict)
            or not isinstance(evidence.get("text"), str)
            or _RESUME_TEXT.fullmatch(evidence["text"]) is None
            or evidence.get("labels") != ["\u79fb\u52d5\u3059\u308b", "\u30ad\u30e3\u30f3\u30bb\u30eb"]
            or evidence.get("anchors") != 0
            or evidence.get("visibleEnabled") is not True
            or evidence.get("structure") is not True
        ):
            raise UnknownPageStateError("Piccoma viewer dialog was not the observed resume prompt")
        await dialogs.locator("button").nth(1).click(timeout=3_000)
        try:
            await page.wait_for_function(
                "!document.querySelector('.jconfirm-open.PCM-pcmConfirm')",
                timeout=3_000,
            )
        except PlaywrightTimeoutError as exc:
            raise UnknownPageStateError("Piccoma resume prompt did not close") from exc
        if await page.locator(".jconfirm-open").count() != 0:
            raise UnknownPageStateError("Piccoma displayed another dialog after resume cancel")

    async def _reader_snapshot(self, page: Page) -> dict[str, Any]:
        result = await page.evaluate(self._reader_snapshot_js)
        if not isinstance(result, dict):
            raise UnknownPageStateError("Piccoma reader state could not be read")
        return result

    async def _validated_page_count(self, page: Page) -> int:
        snapshot = await self._reader_snapshot(page)
        if (
            snapshot.get("rootCount") != 1
            or snapshot.get("pageListCount") != 1
            or snapshot.get("frameCount") != 1
            or snapshot.get("horizontal") is not True
            or snapshot.get("leftToRight") is not True
            or snapshot.get("dialogCount") != 0
        ):
            raise UnknownPageStateError("Piccoma viewer layout is unsupported or ambiguous")
        ids = snapshot.get("pageIds")
        if not isinstance(ids, list):
            raise UnknownPageStateError("Piccoma body page IDs are unavailable")
        numbers: list[int] = []
        for page_id in ids:
            if page_id == "last":
                continue
            match = _BODY_PAGE_ID.fullmatch(page_id) if isinstance(page_id, str) else None
            if match is None:
                raise UnknownPageStateError("Piccoma viewer contains an unknown page ID")
            numbers.append(int(match.group(1)))
        if (
            not numbers
            or len(numbers) > MAX_BODY_PAGES
            or len(set(numbers)) != len(numbers)
            or sorted(numbers) != list(range(1, len(numbers) + 1))
            or ids.count("last") != 1
        ):
            raise UnknownPageStateError("Piccoma body page list is partial or duplicated")
        return len(numbers)

    async def _current_id(self, page: Page) -> str:
        snapshot = await self._reader_snapshot(page)
        active = snapshot.get("activeIds")
        if not isinstance(active, list) or len(active) != 1:
            return ""
        current = active[0]
        return current if isinstance(current, str) else ""

    async def _wait_for_body(self, page: Page, number: int) -> None:
        deadline = time.monotonic() + self.page_change_timeout_ms / 1000
        previous_signature: tuple[object, ...] | None = None
        stable_samples = 0
        last_row: dict[str, Any] | None = None
        last_snapshot: dict[str, Any] | None = None
        while time.monotonic() <= deadline:
            snapshot = await self._reader_snapshot(page)
            self._validate_reader_mode(snapshot)
            if snapshot.get("activeIds") == [f"p{number}"]:
                row = self._page_row(snapshot, f"p{number}")
                canvas = row.get("canvas")
                if (
                    row.get("canvasCount") == 1
                    and row.get("loadedCount") == 1
                    and isinstance(canvas, dict)
                    and canvas.get("loaded") is True
                    and isinstance(canvas.get("width"), int)
                    and canvas.get("width", 0) > 0
                    and isinstance(canvas.get("height"), int)
                    and canvas.get("height", 0) > 0
                    and self._canvas_renderability_is_valid(row)
                ):
                    renderability = canvas["renderability"]
                    signature = (
                        row["id"],
                        canvas.get("width"),
                        canvas.get("height"),
                        tuple(canvas.get("rect", [])),
                        tuple(snapshot.get("viewport", [])),
                        tuple(
                            tuple(sorted(item.items()))
                            for item in renderability["ancestors"]
                        ),
                    )
                    stable_samples = stable_samples + 1 if signature == previous_signature else 1
                    previous_signature = signature
                    last_row, last_snapshot = row, snapshot
                    if stable_samples >= 3:
                        self._validate_canvas_geometry(snapshot, row)
                        return
                else:
                    previous_signature = None
                    stable_samples = 0
            else:
                previous_signature = None
                stable_samples = 0
            await page.wait_for_timeout(100)
        if last_row is not None and last_snapshot is not None and stable_samples >= 1:
            self._validate_canvas_geometry(last_snapshot, last_row)
            raise UnknownPageStateError("Piccoma body canvas geometry did not stabilize")
        raise PageChangeTimeoutError(f"Piccoma body page p{number} did not become ready")

    async def _wait_for_end(self, page: Page) -> None:
        try:
            await page.wait_for_function(
                """() => {
                  const current = [...document.querySelectorAll(
                    '#react_PageListApp .PCM-viewer2_pageWrapper.current'
                  )];
                  return current.length === 1 && current[0].id === 'last' &&
                    !!current[0].querySelector('#js_viewerEnd.PCM-viewer2_endPage') &&
                    document.body.classList.contains('PCM-viewer2_last');
                }""",
                timeout=PAGE_CHANGE_TIMEOUT_MS,
            )
        except PlaywrightTimeoutError as exc:
            raise PageChangeTimeoutError("Piccoma explicit END state did not become active") from exc
        snapshot = await self._reader_snapshot(page)
        self._validate_reader_mode(snapshot)
        if snapshot.get("activeIds") != ["last"] or snapshot.get("activeHasEnd") is not True:
            raise UnknownPageStateError("Piccoma terminal page did not match the observed END")

    def _validate_reader_mode(self, snapshot: dict[str, Any]) -> None:
        if (
            snapshot.get("rootCount") != 1
            or snapshot.get("pageListCount") != 1
            or snapshot.get("frameCount") != 1
            or snapshot.get("horizontal") is not True
            or snapshot.get("leftToRight") is not True
            or snapshot.get("dialogCount") != 0
        ):
            raise UnknownPageStateError("Piccoma viewer left the supported reader mode")

    @staticmethod
    def _page_row(snapshot: dict[str, Any], page_id: str) -> dict[str, Any]:
        pages = snapshot.get("pages")
        if not isinstance(pages, list):
            raise UnknownPageStateError("Piccoma viewer page wrappers are unavailable")
        rows = [row for row in pages if isinstance(row, dict) and row.get("id") == page_id]
        if len(rows) != 1:
            raise UnknownPageStateError("Piccoma viewer page wrapper is missing or duplicated")
        return rows[0]

    def _validate_canvas_geometry(
        self, snapshot: dict[str, Any], row: dict[str, Any]
    ) -> tuple[int, int]:
        canvas = row.get("canvas")
        rect = canvas.get("rect") if isinstance(canvas, dict) else None
        viewport = snapshot.get("viewport")
        frame_rect = snapshot.get("frameRect")
        if (
            not isinstance(canvas, dict)
            or not isinstance(rect, list)
            or not isinstance(viewport, list)
            or not isinstance(frame_rect, list)
            or len(rect) != 4
            or len(viewport) != 3
            or len(frame_rect) != 4
        ):
            raise UnknownPageStateError("Piccoma canvas geometry is incomplete")
        if not self._canvas_renderability_is_valid(row):
            raise UnknownPageStateError("Piccoma active canvas is not visibly rendered")
        width, height = canvas.get("width"), canvas.get("height")
        if (
            not isinstance(width, int)
            or isinstance(width, bool)
            or not isinstance(height, int)
            or isinstance(height, bool)
            or width <= 0
            or height <= 0
            or abs(float(rect[2]) - width) > 0.5
            or abs(float(rect[3]) - height) > 0.5
            or not canvas.get("inFrame")
            or not self._viewport_is_supported(viewport)
            or float(rect[0]) < 0
            or float(rect[1]) < 0
            or float(rect[0]) + float(rect[2]) > viewport[0] + 0.5
            or float(rect[1]) + float(rect[3]) > viewport[1] + 0.5
            or any(not isinstance(value, (int, float)) for value in frame_rect)
            or abs(float(frame_rect[2]) - width) > 0.5
            or abs(float(frame_rect[3]) - height) > 0.5
        ):
            raise UnknownPageStateError("Piccoma canvas does not match the supported viewport")
        return width, height

    @staticmethod
    def _viewport_is_supported(viewport: Any) -> bool:
        if (
            not isinstance(viewport, list)
            or len(viewport) != 3
            or viewport[0] != VIEWPORT_WIDTH
            or viewport[1] != VIEWPORT_HEIGHT
        ):
            return False
        device_pixel_ratio = viewport[2]
        if type(device_pixel_ratio) not in {int, float}:
            return False
        if isinstance(device_pixel_ratio, float) and not math.isfinite(device_pixel_ratio):
            return False
        return abs(device_pixel_ratio - 1) <= DEVICE_PIXEL_RATIO_TOLERANCE

    @staticmethod
    def _canvas_renderability_is_valid(row: dict[str, Any]) -> bool:
        canvas = row.get("canvas")
        state = canvas.get("renderability") if isinstance(canvas, dict) else None
        ancestors = state.get("ancestors") if isinstance(state, dict) else None
        if not isinstance(state, dict) or not isinstance(ancestors, list) or not ancestors:
            return False
        return state.get("visible") is True and all(
            isinstance(style, dict)
            and style.get("display") != "none"
            and style.get("visibility") == "visible"
            and type(style.get("opacity")) in {int, float}
            and style.get("opacity") == 1
            and style.get("contentVisibility") == "visible"
            for style in ancestors
        )

    async def _normalize_first_page(self, page: Page) -> None:
        if self._page_count is None:
            raise UnknownPageStateError("Piccoma body page count was not established")
        current = await self._current_id(page)
        if current == "last":
            await self._step_previous(page, expected=f"p{self._page_count}")
            current = f"p{self._page_count}"
        match = _BODY_PAGE_ID.fullmatch(current)
        if match is None:
            raise UnknownPageStateError("Piccoma initial body page identity is ambiguous")
        number = int(match.group(1))
        while number > 1:
            await self._step_previous(page, expected=f"p{number - 1}")
            number -= 1
        if await self._current_id(page) != "p1":
            raise UnknownPageStateError("Piccoma reader could not be normalized to page one")
        await self._wait_for_body(page, 1)
        self._expected_page_id = "p1"

    async def _step_previous(self, page: Page, *, expected: str) -> None:
        snapshot = await self._reader_snapshot(page)
        self._validate_reader_mode(snapshot)
        if (
            snapshot.get("previousCount") != 1
            or snapshot.get("previousDisabled")
            or snapshot.get("previousVisible") is not True
        ):
            raise UnknownPageStateError("Piccoma previous-page control is unavailable")
        await page.locator(PREVIOUS_SELECTOR).click(timeout=3_000)
        if expected == "last":
            await self._wait_for_end(page)
        else:
            match = _BODY_PAGE_ID.fullmatch(expected)
            if match is None:
                raise UnknownPageStateError("Piccoma previous-page target is invalid")
            await self._wait_for_body(page, int(match.group(1)))

    async def initialize_entry_only(self, page: Page) -> None:
        # No entitlement or resource-grant action exists in this free-only adapter.
        await self.initialize(page)

    async def detect_state(self, page: Page) -> PageState:
        if self._source_identity is None or parse_piccoma_viewer_url(page.url) != self._source_identity:
            return PageState.UNKNOWN
        snapshot = await self._reader_snapshot(page)
        try:
            self._validate_reader_mode(snapshot)
            if self._page_count is None or await self._validated_page_count(page) != self._page_count:
                return PageState.UNKNOWN
        except UnknownPageStateError:
            return PageState.UNKNOWN
        active = snapshot.get("activeIds")
        if not isinstance(active, list) or len(active) != 1:
            return PageState.LOADING
        current = active[0]
        if current != self._expected_page_id:
            return PageState.UNKNOWN
        if current == "last":
            if (
                self._terminal
                and self._advance_from == self._page_count
                and snapshot.get("activeHasEnd") is True
            ):
                return PageState.END
            return PageState.UNKNOWN
        match = _BODY_PAGE_ID.fullmatch(current) if isinstance(current, str) else None
        if match is None:
            return PageState.UNKNOWN
        number = int(match.group(1))
        try:
            row = self._page_row(snapshot, current)
            if not self._canvas_renderability_is_valid(row):
                return PageState.UNKNOWN
            self._validate_canvas_geometry(snapshot, row)
        except UnknownPageStateError:
            return PageState.LOADING
        if (
            number < 1
            or number > (self._page_count or 0)
            or row.get("canvasCount") != 1
            or row.get("loadedCount") != 1
            or row.get("canvas", {}).get("loaded") is not True
        ):
            return PageState.LOADING
        return PageState.CONTENT

    async def get_capture_target(self, page: Page) -> Locator:
        current = await self._current_id(page)
        if (
            _BODY_PAGE_ID.fullmatch(current) is None
            or current != self._expected_page_id
        ):
            raise UnknownPageStateError("Piccoma does not have one active body page")
        return page.locator(
            f"#react_PageListApp .PCM-viewer2_pageWrapper.current#{current} canvas"
        )

    async def capture_page(self, page: Page) -> tuple[CaptureResult, ...] | None:
        self._capture_method = "not_captured"
        self._capture_source_native = False
        self._capture_source_mime = None
        self._capture_backdrop = None
        self._capture_fallback_reason = None
        self._capture_encoding_fallback_reason = None
        self._capture_output_format = None
        self._capture_output_lossless = None
        before = await self._reader_snapshot(page)
        self._validate_reader_mode(before)
        active = before.get("activeIds")
        if not isinstance(active, list) or len(active) != 1:
            raise UnknownPageStateError("Piccoma capture has no unique active page")
        current = active[0]
        match = _BODY_PAGE_ID.fullmatch(current) if isinstance(current, str) else None
        if match is None or current != self._expected_page_id:
            raise UnknownPageStateError("Piccoma capture target is not a body page")
        if await self.detect_state(page) is not PageState.CONTENT:
            raise UnknownPageStateError("Piccoma active page is not ready for capture")
        row = self._page_row(before, current)
        if not self._canvas_renderability_is_valid(row):
            raise UnknownPageStateError("Piccoma active canvas is not visibly rendered")
        expected_size = self._validate_canvas_geometry(before, row)
        if (
            row.get("canvasCount") != 1
            or row.get("loadedCount") != 1
            or row.get("canvas", {}).get("loaded") is not True
        ):
            raise UnknownPageStateError("Piccoma active canvas is incomplete")
        target = await self.get_capture_target(page)
        if await target.count() != 1:
            raise UnknownPageStateError("Piccoma active canvas is missing or duplicated")
        try:
            target_baseline = await snapshot_native_trace(page, target)
        except NativeCaptureUnavailable as exc:
            raise UnknownPageStateError(
                "Piccoma active canvas generation cannot be monitored"
            ) from exc
        target_baseline_signature = target_generation_signature(target_baseline)
        if target_baseline_signature is None:
            raise UnknownPageStateError("Piccoma active canvas generation cannot be monitored")
        guide_style = await self._hide_reading_guide(page, before)
        try:
            native_result = None
            try:
                native_result = await capture_native_tile_replay(
                    page,
                    canvas=target,
                    expected_width=expected_size[0],
                    expected_height=expected_size[1],
                    responses_for_url=self._responses_for_native_url,
                    response_count_for_url=self._native_response_count_for_url,
                    response_registry_overflowed=self._native_response_overflow,
                    bytes_already_read=self._native_bytes_read,
                    max_episode_bytes=MAX_NATIVE_EPISODE_BYTES,
                )
            except NativeCaptureUnavailable as exc:
                self._native_bytes_read += exc.bytes_read
                if exc.unsafe_live_change:
                    raise UnknownPageStateError(
                        "Piccoma active canvas changed during source-native capture"
                    ) from exc
                self._capture_fallback_reason = exc.reason
            if native_result is not None:
                result = native_result.result
                self._native_bytes_read += native_result.source_bytes
                if result.mime_type == "image/webp" and result.file_extension == ".webp":
                    self._capture_method = "native_tile_replay_lossless_webp"
                elif result.mime_type == "image/png" and result.file_extension == ".png":
                    self._capture_method = "native_tile_replay_png"
                else:
                    raise UnknownPageStateError(
                        "Piccoma native capture format is unsupported"
                    )
                self._capture_source_native = True
                self._capture_source_mime = native_result.source_mime
                self._capture_backdrop = native_result.backdrop
                self._capture_encoding_fallback_reason = (
                    native_result.encoding_fallback_reason
                )
            else:
                result = await capture_locator(target)
                self._capture_method = "core_canvas_or_locator_png"
                self._capture_source_native = False
                self._capture_source_mime = None
                self._capture_backdrop = None
                self._capture_encoding_fallback_reason = None
            after = await self._reader_snapshot(page)
            self._validate_capture_post_state(
                page, before, after, current, row, expected_size, result
            )
            await self._validate_target_generation_unchanged(
                page, target, target_baseline_signature
            )
            if native_result is not None:
                try:
                    fallback_reason = await validate_native_capture_still_current(
                        page, target, native_result
                    )
                except NativeCaptureUnavailable as exc:
                    self._native_bytes_read += exc.bytes_read
                    if exc.unsafe_live_change:
                        raise UnknownPageStateError(
                            "Piccoma active canvas changed during source-native capture"
                        ) from exc
                    fallback_reason = exc.reason
                if self._native_response_count_for_url(native_result.source_url) != 1:
                    fallback_reason = "source_response_became_ambiguous"
                if fallback_reason is not None:
                    self._capture_fallback_reason = fallback_reason
                    self._capture_encoding_fallback_reason = None
                    self._capture_method = "core_canvas_or_locator_png"
                    self._capture_source_native = False
                    self._capture_source_mime = None
                    self._capture_backdrop = None
                    result = await capture_locator(target)
                    after = await self._reader_snapshot(page)
                    self._validate_capture_post_state(
                        page, before, after, current, row, expected_size, result
                    )
                    await self._validate_target_generation_unchanged(
                        page, target, target_baseline_signature
                    )
                else:
                    self._capture_fallback_reason = None
            self._capture_output_format = result.mime_type
            self._capture_output_lossless = result.mime_type in {
                "image/png",
                "image/webp",
            }
            return (result,)
        finally:
            try:
                await self._restore_reading_guide(page, guide_style)
            finally:
                await retire_native_trace(page, target)

    async def _validate_target_generation_unchanged(
        self, page: Page, target: Locator, baseline: tuple[Any, ...]
    ) -> None:
        try:
            current = await snapshot_native_trace(page, target)
        except NativeCaptureUnavailable as exc:
            raise UnknownPageStateError(
                "Piccoma active canvas changed during capture"
            ) from exc
        if target_generation_signature(current) != baseline:
            raise UnknownPageStateError(
                "Piccoma active canvas changed during capture"
            )

    def _validate_capture_post_state(
        self,
        page: Page,
        before: dict[str, Any],
        after: dict[str, Any],
        current: str,
        before_row: dict[str, Any],
        expected_size: tuple[int, int],
        result: CaptureResult,
    ) -> None:
        self._validate_reader_mode(after)
        after_row = self._page_row(after, current)
        if (
            parse_piccoma_viewer_url(page.url) != self._require_identity()
            or after.get("activeIds") != [current]
            or after_row.get("canvasCount") != 1
            or after_row.get("loadedCount") != 1
            or after_row.get("canvas", {}).get("loaded") is not True
            or after_row.get("canvas", {}).get("width") != expected_size[0]
            or after_row.get("canvas", {}).get("height") != expected_size[1]
            or after_row.get("canvas", {}).get("rect")
            != before_row.get("canvas", {}).get("rect")
            or after_row.get("canvas", {}).get("renderability")
            != before_row.get("canvas", {}).get("renderability")
            or after.get("frameRect") != before.get("frameRect")
            or after.get("viewport") != before.get("viewport")
        ):
            raise UnknownPageStateError("Piccoma page changed during capture")
        self._validate_canvas_geometry(after, after_row)
        if not self._canvas_renderability_is_valid(after_row):
            raise UnknownPageStateError(
                "Piccoma active canvas stopped being visibly rendered during capture"
            )
        expected_format = {
            "native_tile_replay_lossless_webp": ("image/webp", ".webp"),
            "native_tile_replay_png": ("image/png", ".png"),
            "core_canvas_or_locator_png": ("image/png", ".png"),
        }.get(self._capture_method)
        if (
            expected_format is None
            or (result.mime_type, result.file_extension) != expected_format
            or (result.width, result.height) != expected_size
            or not capture_result_format_is_valid(
                result, width=expected_size[0], height=expected_size[1]
            )
        ):
            raise UnknownPageStateError(
                "Piccoma rendered image format or dimensions are unsupported"
            )

    async def _hide_reading_guide(
        self, page: Page, snapshot: dict[str, Any]
    ) -> tuple[bool, str | None]:
        count = snapshot.get("guideCount")
        if count == 0:
            return False, None
        guide = snapshot.get("guide")
        if (
            count != 1
            or not isinstance(guide, dict)
            or guide.get("tag") != "DIV"
            or guide.get("sign") is not True
            or guide.get("vertical") != 1
            or guide.get("horizontal") != 1
            or guide.get("verticalLabels") != ["\u30bf\u30c6\u8aad\u307f"]
            or guide.get("horizontalLabels") != ["\u30e8\u30b3\u8aad\u307f", "\u30e8\u30b3\u8aad\u307f"]
            or guide.get("interactiveCount") != 0
            or guide.get("tree") not in _KNOWN_GUIDE_TREES
            or guide.get("pseudoBefore") != "none"
            or guide.get("pseudoAfter") != "none"
        ):
            raise UnknownPageStateError("Piccoma reading-direction guide is unknown or duplicated")
        original_style = await page.locator(GUIDE_SELECTOR).evaluate(
            """node => {
              const style = node.getAttribute('style');
              node.style.setProperty('display', 'none', 'important');
              return style;
            }"""
        )
        return True, original_style

    async def _restore_reading_guide(
        self, page: Page, state: tuple[bool, str | None]
    ) -> None:
        present, original_style = state
        if not present:
            return
        if original_style is None:
            await page.locator(GUIDE_SELECTOR).evaluate("node => node.removeAttribute('style')")
        else:
            await page.locator(GUIDE_SELECTOR).evaluate(
                "(node, style) => node.setAttribute('style', style)", original_style
            )

    async def get_content_identity(self, page: Page) -> ContentIdentity:
        if await self.detect_state(page) is not PageState.CONTENT:
            raise UnknownPageStateError("Piccoma page identity is unavailable")
        current = await self._current_id(page)
        match = _BODY_PAGE_ID.fullmatch(current)
        if match is None:
            raise UnknownPageStateError("Piccoma active body page ID is invalid")
        number = int(match.group(1))
        identity = self._require_identity()
        return ContentIdentity(
            page_id=current,
            page_number=number,
            source_id=identity.external_id,
        )

    async def get_content_context(self, page: Page) -> ContentContext:
        if parse_piccoma_viewer_url(page.url) != self._require_identity():
            raise UnknownPageStateError("Piccoma content context left the requested viewer")
        identity = self._require_identity()
        return ContentContext(
            content_id=identity.episode_id,
            work_id=self._work_key,
            episode_id=identity.episode_id,
            title=self._title,
        )

    async def go_next(self, page: Page) -> None:
        if await self.detect_state(page) is not PageState.CONTENT:
            raise UnknownPageStateError("Piccoma cannot advance from an unknown reader state")
        current = await self._current_id(page)
        match = _BODY_PAGE_ID.fullmatch(current)
        if (
            match is None
            or self._page_count is None
            or current != self._expected_page_id
            or self._advance_from is not None
        ):
            raise UnknownPageStateError("Piccoma next-page source identity is invalid")
        number = int(match.group(1))
        snapshot = await self._reader_snapshot(page)
        if (
            snapshot.get("nextCount") != 1
            or snapshot.get("nextDisabled") is True
            or snapshot.get("nextVisible") is not True
        ):
            raise UnknownPageStateError("Piccoma in-episode next control is unavailable")
        await page.locator(NEXT_SELECTOR).click(timeout=3_000)
        self._advance_from = number
        self._terminal = False

    async def wait_for_change(
        self, page: Page, previous_identity: ContentIdentity | None
    ) -> None:
        if previous_identity is None or previous_identity.page_number is None:
            current = self._expected_page_id
            match = _BODY_PAGE_ID.fullmatch(current) if isinstance(current, str) else None
            if match is None or await self._current_id(page) != current:
                raise UnknownPageStateError(
                    "Piccoma page changed outside an approved transition"
                )
            await self._wait_for_body(page, int(match.group(1)))
            return
        if (
            self._advance_from != previous_identity.page_number
            or previous_identity.page_id != self._expected_page_id
            or self._page_count is None
        ):
            raise UnknownPageStateError("Piccoma page transition did not match its source")
        expected = self._advance_from + 1
        if expected <= self._page_count:
            await self._wait_for_body(page, expected)
            if parse_piccoma_viewer_url(page.url) != self._require_identity():
                raise UnknownPageStateError("Piccoma page transition changed the viewer URL")
            self._expected_page_id = f"p{expected}"
            self._advance_from = None
            return
        if self._advance_from != self._page_count:
            raise UnknownPageStateError("Piccoma END was requested before the final body page")
        await self._wait_for_end(page)
        if parse_piccoma_viewer_url(page.url) != self._require_identity():
            raise UnknownPageStateError("Piccoma END transition changed the viewer URL")
        self._expected_page_id = "last"
        self._terminal = True

    def _require_identity(self) -> PiccomaEpisodeIdentity:
        if self._source_identity is None:
            raise UnknownPageStateError("Piccoma target identity has not been configured")
        return self._source_identity

    async def collect_debug_metadata(self, page: Page) -> dict[str, Any]:
        del page
        return {
            "piccoma_capture": {
                "method": self._capture_method,
                "source_native": self._capture_source_native,
                "source_mime": self._capture_source_mime,
                "source_backdrop": self._capture_backdrop,
                "fallback_reason": self._capture_fallback_reason,
                "encoding_fallback_reason": self._capture_encoding_fallback_reason,
                "output_format": self._capture_output_format,
                "output_lossless": self._capture_output_lossless,
                "page_count": self._page_count,
                "access_strategy": self._access_strategy,
                "viewport": [VIEWPORT_WIDTH, VIEWPORT_HEIGHT],
            }
        }

    def get_output_metadata(self) -> dict[str, str | None]:
        return {"title": self._title}


__all__ = ["PiccomaAdapter"]
