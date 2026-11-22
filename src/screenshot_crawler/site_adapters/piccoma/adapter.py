"""Piccoma direct viewer entry, bound to freshly checked access evidence."""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal
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
from screenshot_crawler.site_adapters.base import (
    AccessAttemptObservation,
    AccessConsumption,
    AccessResourceResolution,
    ConfirmedAccessGrant,
    SiteAdapter,
)
from screenshot_crawler.site_adapters.piccoma.access import piccoma_access_profile
from screenshot_crawler.site_adapters.piccoma.discovery import (
    PiccomaEpisodeIdentity,
    canonical_piccoma_viewer_url,
    classify_piccoma_access,
    parse_piccoma_listing_url,
    parse_piccoma_viewer_url,
    piccoma_manual_grant_until,
)
from screenshot_crawler.site_adapters.piccoma.live_access import (
    PICCOMA_TICKET_NO_ACTION_REASON,
    TICKET_BUTTON_CLASS,
    TICKET_BUTTON_LABEL,
    TICKET_ROW_MARKER,
    PiccomaTicketKind,
    PiccomaTicketNoActionError,
    binge_available_count,
    binge_modal_balances,
    is_known_nonfree_offer_status,
    observed_now,
    piccoma_access_endpoint_matches,
    piccoma_access_request_matches,
    piccoma_ticket_kind_from_status,
    ticket_modal_matches,
    waitfree_charge_ready,
    zero_plus_available_count,
    zero_plus_modal_balance,
)
from screenshot_crawler.site_adapters.piccoma.native_capture import (
    OVERSCAN_DISPLAY_SIZE,
    OVERSCAN_NATIVE_SIZE,
    SCALED_DISPLAY_PROFILES,
    SCALED_DISPLAY_WIDTH_TOLERANCE,
    SCALED_NATIVE_ONLY_SIZES,
    SCALED_NATIVE_SIZES,
    NativeCaptureUnavailable,
    capture_native_tile_replay,
    capture_result_format_is_valid,
    install_native_trace,
    is_additional_ordinary_size,
    is_additional_scaled_size,
    is_ordinary_native_presentation,
    retire_native_trace,
    scaled_display_profile,
    snapshot_native_trace,
    target_generation_signature,
    validate_native_capture_still_current,
)

_LOGGER = logging.getLogger(__name__)

_AUTO_TICKET_RESOURCE = "piccoma_ticket_auto"
_WORK_TICKET_RESOURCE = "work_ticket"
_BINGE_TICKET_RESOURCE = "binge_ticket"
_GRANT_ONLY_TICKET_RESOURCES = frozenset(
    {_WORK_TICKET_RESOURCE, _BINGE_TICKET_RESOURCE}
)
_TICKET_KINDS_BY_RESOURCE: dict[str, frozenset[PiccomaTicketKind]] = {
    _AUTO_TICKET_RESOURCE: frozenset({"waitfree", "zero_plus", "binge_free"}),
    _WORK_TICKET_RESOURCE: frozenset({"waitfree", "zero_plus"}),
    _BINGE_TICKET_RESOURCE: frozenset({"binge_free"}),
}

LISTING_SELECTOR = "#js_episodeList"
ROW_SELECTOR = "#js_episodeList a[data-product_id][data-episode_id]"
NEXT_SELECTOR = "button.PCM-viewer2_pagingBtn_next"
PREVIOUS_SELECTOR = "button.PCM-viewer2_pagingBtn_prev"
GUIDE_SELECTOR = "#js_scrollTypeSing"
RESUME_DIALOG_SELECTOR = ".jconfirm-open.PCM-pcmConfirm"
TICKET_ELIGIBILITY_TIMEOUT_MS = 12_000
TICKET_MODAL_TIMEOUT_MS = 7_000
TICKET_ACTION_TIMEOUT_MS = 15_000
TICKET_VIEWER_TIMEOUT_MS = 15_000
TICKET_VIEWER_DOM_TIMEOUT_MS = 10_000
TICKET_MODAL_EVIDENCE_JS = """dialog => {
  const visible = node => {
    const rect = node.getBoundingClientRect();
    const style = getComputedStyle(node);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' &&
      style.visibility === 'visible';
  };
  return {
    text: (dialog.innerText || '').replace(/\\s+/g, ' ').trim(),
    structure: dialog.classList.contains('PCM-pcmConfirm'),
    anchors: dialog.querySelectorAll('a[href]').length,
    buttons: [...dialog.querySelectorAll('button')].map(button => ({
      text: (button.innerText || '').replace(/\\s+/g, ' ').trim(),
      classes: [...button.classList], disabled: button.disabled,
      ariaDisabled: button.getAttribute('aria-disabled'), visible: visible(button)
    }))
  };
}"""


class _PiccomaTicketNavigationGuard:
    """Guard the owned page tree and its sole exact eligibility request."""

    def __init__(self, page: Page, identity: PiccomaEpisodeIdentity) -> None:
        self.page = page
        self.context = page.context
        self.identity = identity
        self.armed = False
        self.blocked_navigation_count = 0
        self.blocked_subframe_count = 0
        self.blocked_popup_count = 0
        self.access_request_count = 0
        self.blocked_access_request_count = 0
        self.blocked_mutating_request_count = 0
        self.blocked_external_mutating_request_count = 0
        self.blocked_external_subframe_navigation_count = 0
        self.eligibility_pending = False
        self.eligibility_invalid = False
        self._page_route_installed = False
        self._context_route_installed = False
        self._owned_popups: set[Page] = set()
        self._popup_block_key = f"__piccomaPopupBlock_{id(self):x}"

    async def install(self) -> None:
        try:
            await self.page.route("**/*", self._route_page)
            self._page_route_installed = True
            await self.context.route("**/*", self._route_context)
            self._context_route_installed = True
            await self.page.evaluate(
                """key => {
                  const state = {originalOpen: window.open, attempted: false, clickHandler: null};
                  state.clickHandler = event => {
                    const target = event.target instanceof Element ? event.target : null;
                    const anchor = target?.closest('a[target]');
                    if (!anchor || !anchor.target || anchor.target.toLowerCase() === '_self') return;
                    state.attempted = true;
                    event.preventDefault();
                    event.stopImmediatePropagation();
                  };
                  window[key] = state;
                  document.addEventListener('click', state.clickHandler, true);
                  window.open = function() { state.attempted = true; return null; };
                }""",
                self._popup_block_key,
            )
        except Exception:
            await self._remove_routes()
            raise
        self.page.on("close", self._on_owner_close)

    def arm_viewer(self) -> None:
        self.armed = True

    def begin_eligibility(self) -> None:
        self.eligibility_pending = True
        self.eligibility_invalid = False
        self.access_request_count = 0
        self.blocked_access_request_count = 0

    def end_eligibility(self) -> None:
        self.eligibility_pending = False

    async def _route_page(self, route: Any) -> None:
        request = route.request
        method = request.method.upper()
        if method not in {"GET", "HEAD", "OPTIONS"}:
            first_party = self._is_piccoma_first_party_url(request.url)
            access_endpoint = piccoma_access_endpoint_matches(
                method=method, url=request.url
            )
            exact_access = False
            if access_endpoint and self.eligibility_pending:
                try:
                    exact_access = piccoma_access_request_matches(
                        method=method,
                        url=request.url,
                        post_data=request.post_data,
                        product_id=self.identity.product_id,
                        episode_id=self.identity.episode_id,
                    )
                except Exception:  # noqa: BLE001 - malformed/binary bodies fail closed
                    exact_access = False
            if (
                method == "POST"
                and self.eligibility_pending
                and exact_access
                and self.access_request_count == 0
                and not self.eligibility_invalid
            ):
                self.access_request_count = 1
                await route.fallback()
                return
            self.blocked_mutating_request_count += 1
            if first_party:
                self.eligibility_invalid = True
                if method == "POST" and (
                    self.eligibility_pending or exact_access or access_endpoint
                ):
                    self.blocked_access_request_count += 1
            else:
                self.blocked_external_mutating_request_count += 1
            await route.abort("blockedbyclient")
            return
        try:
            is_target_navigation = (
                request.is_navigation_request()
                and request.resource_type == "document"
            )
            is_main_frame = request.frame.parent_frame is None
        except Exception:  # noqa: BLE001 - detached pages are never safe to navigate
            is_target_navigation = True
            is_main_frame = False
        if not is_target_navigation:
            await route.fallback()
            return
        if not is_main_frame and not self._is_piccoma_first_party_url(request.url):
            self.blocked_external_subframe_navigation_count += 1
            await route.abort("blockedbyclient")
            return
        allowed = (
            self.armed
            and is_main_frame
            and request.method.upper() == "GET"
            and PiccomaAdapter._viewer_identity_from_url(request.url) == self.identity
        )
        if allowed:
            await route.fallback()
            return
        self.blocked_navigation_count += 1
        if not is_main_frame:
            self.blocked_subframe_count += 1
        await route.abort("blockedbyclient")

    @staticmethod
    def _is_piccoma_first_party_url(url: str) -> bool:
        try:
            hostname = (urlparse(url).hostname or "").lower()
        except ValueError:
            return False
        return hostname in {"piccoma.com", "www.piccoma.com"}

    async def _route_context(self, route: Any) -> None:
        request = route.request
        try:
            owner_page = request.frame.page
        except Exception:  # noqa: BLE001 - cannot prove ownership; avoid cross-tab effects
            await route.fallback()
            return
        if owner_page == self.page:
            await route.fallback()
            return
        if not await self._is_owned_popup(owner_page):
            await route.fallback()
            return
        self._owned_popups.add(owner_page)
        if request.is_navigation_request() and request.resource_type == "document":
            self.blocked_popup_count += 1
            await route.abort("blockedbyclient")
            return
        method = request.method.upper()
        if method not in {"GET", "HEAD", "OPTIONS"}:
            self.blocked_mutating_request_count += 1
            self.eligibility_invalid = True
            if method == "POST":
                self.blocked_access_request_count += 1
            await route.abort("blockedbyclient")
            return
        await route.abort("blockedbyclient")

    async def _is_owned_popup(self, page: Page) -> bool:
        current: Page | None = page
        for _ in range(8):
            if current is None or current == self.page:
                return current == self.page
            try:
                current = await current.opener()
            except Exception:  # noqa: BLE001 - an unprovable popup is not ours
                return False
        return False

    @staticmethod
    def _is_access_endpoint(url: str) -> bool:
        return piccoma_access_endpoint_matches(method="POST", url=url)

    async def _on_owner_close(self, *_args: object) -> None:
        await self.remove_after_owner_close()

    async def remove_after_owner_close(self) -> None:
        await self._remove_routes()
        await self._restore_popup_blocker()
        for popup in tuple(self._owned_popups):
            if not popup.is_closed():
                try:
                    await popup.close()
                except Exception:
                    _LOGGER.debug("Could not close owned Piccoma popup", exc_info=True)
        self._owned_popups.clear()

    async def remove_after_verified_entry(self) -> None:
        await self._remove_routes()
        await self._restore_popup_blocker()
        for popup in tuple(self._owned_popups):
            if not popup.is_closed():
                try:
                    await popup.close()
                except Exception:
                    _LOGGER.debug("Could not close owned Piccoma popup", exc_info=True)
        self._owned_popups.clear()

    async def _remove_routes(self) -> None:
        if self._page_route_installed:
            try:
                await self.page.unroute("**/*", self._route_page)
                self._page_route_installed = False
            except Exception:  # noqa: BLE001 - leaving the guard installed is fail-closed
                # A closed Page owns no requests and Playwright may reject
                # unroute() for it. Still remove our Context handler below so
                # the shared Context does not accumulate stale callbacks.
                if self.page.is_closed():
                    self._page_route_installed = False
        if self._context_route_installed:
            try:
                await self.context.unroute("**/*", self._route_context)
                self._context_route_installed = False
            except Exception:  # noqa: BLE001 - leaving the guard installed is fail-closed
                self._context_route_installed = True

    async def popup_was_attempted(self) -> bool:
        try:
            return await self.page.evaluate(
                "key => window[key]?.attempted === true", self._popup_block_key
            )
        except Exception:  # noqa: BLE001 - lost page state is not safe to continue
            return True

    async def _restore_popup_blocker(self) -> None:
        try:
            await self.page.evaluate(
                """key => {
                  const state = window[key];
                  if (!state) return;
                  document.removeEventListener('click', state.clickHandler, true);
                  window.open = state.originalOpen;
                  delete window[key];
                }""",
                self._popup_block_key,
            )
        except Exception:  # noqa: BLE001 - closed pages no longer own a popup surface
            return

VIEWPORT_WIDTH = 1904
VIEWPORT_HEIGHT = 1200
# Chrome may expose a tiny floating-point DPR error around the observed 1x
# viewport. Keep the supported mode narrowly centered on 1x.
DEVICE_PIXEL_RATIO_TOLERANCE = 1e-7
MAX_BODY_PAGES = 2_000
MAX_NATIVE_RESPONSE_RECORDS = 512
MAX_NATIVE_EPISODE_BYTES = 64_000_000
# The observed 42-page 1350x1920 episode exceeds the ordinary source-read budget.
# Keep this larger, still finite budget specific to the validated scaled profile.
MAX_SCALED_NATIVE_EPISODE_BYTES = 128_000_000
PAGE_CHANGE_TIMEOUT_MS = 10_000
INITIALIZE_TIMEOUT_MS = 30_000
RESUME_DIALOG_GRACE_MS = 1_500
MAX_BODY_WAIT_DIAGNOSTIC_SAMPLES = 8
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
    """Capture exact-free or manually unlocked episodes through the horizontal reader."""

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
        self._viewer_url: str | None = None
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
        self._capture_interruption: dict[str, Any] | None = None
        self._capture_timing: dict[str, Any] | None = None
        self._capture_started = 0.0
        self._capture_stage_started = 0.0
        self._capture_page: Page | None = None
        self._response_listener: Any = None
        self._native_responses: dict[str, list[Response]] = {}
        self._native_response_counts: dict[str, int] = {}
        self._native_response_count = 0
        self._native_response_overflow = False
        self._native_response_event = asyncio.Event()
        self._native_bytes_read = 0
        self._body_wait_failure: dict[str, Any] | None = None
        self._scaled_frame_rect: tuple[float, ...] | None = None
        self._quota_resource: str | None = None
        self._ticket_kind: PiccomaTicketKind | None = None
        self._ticket_attempt_started = False
        self._ticket_navigation_guard: _PiccomaTicketNavigationGuard | None = None
        self._access_consumption = AccessConsumption()

    def get_access_profile(self) -> AccessProfile:
        return piccoma_access_profile()

    def get_initialize_timeout_ms(self, default_ms: int) -> int:
        return max(default_ms, INITIALIZE_TIMEOUT_MS)

    async def prepare_page(self, page: Page) -> None:
        # Observed 1:1 and high-resolution scaled readers use this viewport.
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
        if access_strategy not in {"auto", "direct", "quota"}:
            raise UnsupportedAccessStrategyError(
                "Piccoma supports direct access or a policy-selected ticket attempt"
            )
        self._access_strategy = access_strategy
        self._quota_resource = None
        self._ticket_kind = None
        self._ticket_attempt_started = False
        self._ticket_navigation_guard = None
        self._access_consumption = AccessConsumption()
        self._source_identity = None
        self._viewer_url = None
        self._title = None
        self._page_count = None
        self._scaled_frame_rect = None
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
        self._capture_interruption = None
        self._capture_timing = None

    async def configure_quota_resource(self, page: Page, quota_resource: str | None) -> None:
        del page
        if quota_resource is None:
            self._quota_resource = None
            return
        if quota_resource not in _TICKET_KINDS_BY_RESOURCE or self._access_strategy != "quota":
            raise UnsupportedAccessStrategyError(
                "Piccoma ticket entry requires a supported explicit ticket resource"
            )
        self._quota_resource = quota_resource

    def get_access_consumption(self) -> AccessConsumption:
        return self._access_consumption

    async def resolve_access_resource_candidates(
        self, page: Page, candidates: tuple[object, ...], quota_resource: str,
        *, timeout_ms: int = 15_000,
    ) -> AccessResourceResolution:
        """Read one product's stock before selecting ticket-backed episodes."""

        resolutions = await self.resolve_access_resource_pools(
            page, {quota_resource: candidates}, timeout_ms=timeout_ms,
        )
        return resolutions[quota_resource]

    async def resolve_access_resource_pools(
        self, page: Page, pools: dict[str, tuple[object, ...]],
        *, timeout_ms: int = 15_000,
    ) -> dict[str, AccessResourceResolution]:
        """Read listing/home once for all requested resources of one product."""

        if not pools or any(
            resource not in _TICKET_KINDS_BY_RESOURCE or not pool
            for resource, pool in pools.items()
        ):
            raise UnsupportedAccessStrategyError("Piccoma stock resolver requires a supported resource")
        candidates = tuple(candidate for pool in pools.values() for candidate in pool)
        identities = [parse_piccoma_viewer_url(candidate.locator) for candidate in candidates]
        if (
            any(identity is None for identity in identities)
            or len({identity.product_id for identity in identities if identity is not None}) != 1
            or len({candidate.work_id for candidate in candidates}) != 1
            or candidates[0].work_id is None
            or any(len({candidate.source_id for candidate in pool}) != len(pool)
                   for pool in pools.values())
            or any(
                candidate.site != "piccoma"
                or candidate.external_id != identity.external_id
                for candidate, identity in zip(candidates, identities, strict=True)
            )
            or any(candidate.quota_resource != resource
                   for resource, pool in pools.items() for candidate in pool)
            or len({(candidate.source_id, candidate.external_id, candidate.locator)
                    for candidate in candidates}) != len({candidate.source_id for candidate in candidates})
        ):
            raise UnknownPageStateError("Piccoma grant resolver requires one bound product/work")
        identity = identities[0]
        response = await page.goto(
            f"https://piccoma.com/web/product/{identity.product_id}/episodes",
            wait_until="domcontentloaded", timeout=timeout_ms,
        )
        if (
            response is None or response.status != 200
            or parse_piccoma_listing_url(page.url) != identity.product_id
        ):
            raise UnknownPageStateError("Piccoma grant snapshot redirected outside its product")
        await page.locator(LISTING_SELECTOR).wait_for(state="visible", timeout=timeout_ms)
        unique_candidates = tuple({candidate.source_id: candidate for candidate in candidates}.values())
        rows = await self._read_ticket_states(
            page, [parse_piccoma_viewer_url(candidate.locator) for candidate in unique_candidates],
        )
        # Rows already come from this freshly loaded full listing. Only home
        # stock needs another GET; entry and debit proof still fetch both pages.
        snapshot = await self._fetch_ticket_state_snapshot(page, identity, include_listing=False)
        home = snapshot["home"]
        rows_by_source = dict(zip((candidate.source_id for candidate in unique_candidates), rows, strict=True))
        return {
            resource: self._select_ticket_pool(
                pool, [rows_by_source[candidate.source_id] for candidate in pool], home, resource,
            )
            for resource, pool in pools.items()
        }

    def _select_ticket_pool(
        self, candidates: tuple[object, ...], rows: list[dict[str, Any]],
        home: dict[str, Any], quota_resource: str,
    ) -> AccessResourceResolution:
        daily = waitfree_charge_ready(home.get("charge"))
        if daily is None:
            raise UnknownPageStateError("Piccoma work charge is missing or malformed")
        zero = zero_plus_available_count(home.get("zeroPlus") or "")
        binge = binge_available_count(home.get("binge") or "")
        daily_left = int(daily)
        selected: list[int] = []
        skipped: list[tuple[int, str]] = []
        unavailable_reason = (
            PICCOMA_TICKET_NO_ACTION_REASON if quota_resource == _AUTO_TICKET_RESOURCE
            else f"{quota_resource}_unavailable"
        )
        for candidate, row in zip(candidates, rows, strict=True):
            mode = classify_piccoma_access(
                row["markers"], row["label"], point_prices=row.get("pointPrices")
            )
            active_grant = piccoma_manual_grant_until(
                row["markers"], row["label"], datetime.now(UTC)
            )
            # Keep fresh grant/free races on the existing durable no-action path.
            if mode == "free" or active_grant is not None:
                selected.append(candidate.source_id)
                continue
            if mode == "paid":
                skipped.append((candidate.source_id, "paid"))
                continue
            if mode != "quota" or row.get("userAccess") != "require":
                raise UnknownPageStateError("Piccoma work grant row has ambiguous access")
            markers = set(row["markers"])
            if quota_resource in {_WORK_TICKET_RESOURCE, _AUTO_TICKET_RESOURCE}:
                if daily_left:
                    daily_left -= 1
                elif TICKET_ROW_MARKER["zero_plus"] in markers:
                    if zero is None:
                        raise UnknownPageStateError("Piccoma work ¥0+ balance is missing or ambiguous")
                    if zero <= 0:
                        skipped.append((candidate.source_id, unavailable_reason))
                        continue
                    zero -= 1
                elif (
                    quota_resource == _AUTO_TICKET_RESOURCE
                    and TICKET_ROW_MARKER["binge_free"] in markers
                ):
                    if binge is None:
                        raise UnknownPageStateError("Piccoma work binge balance is missing or ambiguous")
                    if binge <= 0:
                        skipped.append((candidate.source_id, unavailable_reason))
                        continue
                    binge -= 1
                else:
                    skipped.append((candidate.source_id, unavailable_reason))
                    continue
            else:
                # A charged daily ticket takes precedence in the native UI.
                # Binge never spends that other resource implicitly.
                if daily or TICKET_ROW_MARKER["binge_free"] not in markers:
                    skipped.append((candidate.source_id, unavailable_reason))
                    continue
                if binge is None:
                    raise UnknownPageStateError("Piccoma work binge balance is missing or ambiguous")
                if binge <= 0:
                    skipped.append((candidate.source_id, unavailable_reason))
                    continue
                binge -= 1
            selected.append(candidate.source_id)
        return AccessResourceResolution(tuple(selected), tuple(skipped))

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
        access_mode, title, grant_until = await self._current_listing_access(page, identity)
        active_grant = grant_until is not None and grant_until > datetime.now(UTC)
        if access_mode == "paid":
            raise AccessResourceUnavailableError(
                "Piccoma target is paid and has no verified free access"
            )
        if access_mode == "quota" and not active_grant:
            if self._access_strategy != "quota":
                raise AccessResourceUnavailableError(
                    "Piccoma target has no verified free access or active manual unlock"
                )
            if self._quota_resource not in _TICKET_KINDS_BY_RESOURCE:
                raise UnsupportedAccessStrategyError(
                    "Piccoma ticket entry requires an explicit ticket resource"
                )
            response, title = await self._redeem_one_ticket(page, identity)
            self._title = title
            await self._prepare_reader_after_entry(
                page, identity, active_grant=True, response=response
            )
            return
        if access_mode != "free" and not (access_mode == "quota" and active_grant):
            raise UnknownPageStateError("Piccoma target access state is ambiguous")
        self._title = title
        if self._access_strategy == "quota" and active_grant and grant_until is not None:
            # A planned quota candidate may become freshly granted before entry.
            # Persist this positive observation before direct capture; it does not
            # represent a new ticket debit or update the daily quota timestamp.
            self.report_confirmed_access_grant(
                ConfirmedAccessGrant(
                    site="piccoma",
                    external_id=identity.external_id,
                    observed_at=observed_now(),
                    access_granted_until=grant_until,
                    expiry_evidence="site_countdown_lower_bound",
                )
            )

        if self._quota_resource in _GRANT_ONLY_TICKET_RESOURCES and (
            access_mode == "free" or (access_mode == "quota" and active_grant)
        ):
            # A stale grant-only plan must not turn an already-accessible target
            # into a new grant or enter the content reader.
            raise PiccomaTicketNoActionError(stop_work=False)

        response = await page.goto(
            canonical_piccoma_viewer_url(
                f"https://piccoma.com/web/viewer/{identity.product_id}/{identity.episode_id}"
            ),
            wait_until="domcontentloaded",
            timeout=15_000,
        )
        final_identity = parse_piccoma_viewer_url(page.url)
        if final_identity is None and active_grant:
            # The live manually unlocked reader redirects to /viewer/s/.
            # Keep Catalog/source URLs canonical and allow this route only
            # after fresh manual-grant evidence for the same composite ID.
            parsed = urlparse(page.url)
            if parsed.path.startswith("/web/viewer/s/"):
                final_identity = parse_piccoma_viewer_url(
                    parsed._replace(path=parsed.path.replace("/viewer/s/", "/viewer/", 1)).geturl()
                )
        if final_identity != identity:
            raise UnknownPageStateError("Piccoma viewer redirected outside the target episode")
        await self._prepare_reader_after_entry(
            page, identity, active_grant=active_grant, response=response
        )

    async def _prepare_reader_after_entry(
        self,
        page: Page,
        identity: PiccomaEpisodeIdentity,
        *,
        active_grant: bool,
        response: Response | None,
    ) -> None:
        final_identity = parse_piccoma_viewer_url(page.url)
        if final_identity is None and active_grant:
            parsed = urlparse(page.url)
            if parsed.path.startswith("/web/viewer/s/"):
                final_identity = parse_piccoma_viewer_url(
                    parsed._replace(
                        path=parsed.path.replace("/viewer/s/", "/viewer/", 1)
                    ).geturl()
                )
        if final_identity != identity:
            raise UnknownPageStateError("Piccoma viewer redirected outside the target episode")
        if response is None or response.status != 200:
            raise UnknownPageStateError("Piccoma viewer did not return HTTP 200")
        self._viewer_url = page.url
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
        snapshot = await self._reader_snapshot(page)
        row = self._page_row(snapshot, "p1")
        if self._uses_additional_scaled_layout(snapshot, row):
            self._validate_canvas_geometry(snapshot, row)
            self._scaled_frame_rect = tuple(snapshot["frameRect"])

    async def _current_listing_access(
        self, page: Page, identity: PiccomaEpisodeIdentity
    ) -> tuple[str, str, datetime | None]:
        observed_at = datetime.now(UTC)
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
                  pointPrices: status ? [
                    ...(status.matches('.PCM-epList_status_point.js_point') ? [status] : []),
                    ...status.querySelectorAll(
                      '.PCM-epList_status_point.js_point, .PCM-epList_status_point .js_point'
                    ),
                  ].map(node => node.innerText.trim()) : [],
                  label: (status?.innerText || '').trim()};
              })""",
            {"product": identity.product_id, "episode": identity.episode_id},
        )
        if len(matches) != 1:
            raise UnknownPageStateError("Piccoma target is absent or duplicated in its listing")
        row = matches[0]
        if row.get("statusCount") != 1:
            return "unknown", title, None
        access_mode = classify_piccoma_access(
            row.get("markers", []), row.get("label", ""),
            point_prices=row.get("pointPrices"),
        )
        grant_until = piccoma_manual_grant_until(
            row.get("markers", []), row.get("label", ""), observed_at
        )
        return access_mode, title, grant_until

    async def _read_ticket_state(
        self, page: Page, identity: PiccomaEpisodeIdentity
    ) -> dict[str, Any]:
        return (await self._read_ticket_states(page, [identity]))[0]

    async def _read_ticket_states(
        self, page: Page, identities: list[PiccomaEpisodeIdentity]
    ) -> list[dict[str, Any]]:
        values = await page.evaluate(
            r"""targets => {
              const text = selector => {
                const nodes = [...document.querySelectorAll(selector)];
                return nodes.length === 1
                  ? (nodes[0].innerText || '').replace(/\s+/g, ' ').trim()
                  : null;
              };
              const allRows = [...document.querySelectorAll(
                '#js_episodeList a[data-product_id][data-episode_id]')];
              return targets.map(target => {
              const rows = allRows
                .filter(anchor => anchor.getAttribute('data-product_id') === target.product &&
                  anchor.getAttribute('data-episode_id') === target.episode);
              const anchor = rows.length === 1 ? rows[0] : null;
              const statuses = anchor
                ? [...anchor.querySelectorAll('.PCM-epList_status')] : [];
              const status = statuses.length === 1 ? statuses[0] : null;
              const markers = status
                ? [status, ...status.querySelectorAll('[class]')]
                    .flatMap(node => [...node.classList])
                    .filter(name => name.startsWith('PCM-epList_status_'))
                : [];
              const titleNodes = [...document.querySelectorAll(
                '#js_contentBody .PCM-headTitle_name')];
              return {
                productId: anchor?.getAttribute('data-product_id') || null,
                episodeId: anchor?.getAttribute('data-episode_id') || null,
                userAccess: anchor?.getAttribute('data-user_access') || null,
                loggedIn: window._init_?.login === true,
                rowCount: rows.length,
                statusCount: statuses.length,
                markers: [...new Set(markers)],
                pointPrices: status ? [
                  ...(status.matches('.PCM-epList_status_point.js_point') ? [status] : []),
                  ...status.querySelectorAll(
                    '.PCM-epList_status_point.js_point, .PCM-epList_status_point .js_point'
                  ),
                ].map(node => node.innerText.trim()) : [],
                label: (status?.innerText || '').replace(/\s+/g, ' ').trim(),
                title: titleNodes.length === 1
                  ? (titleNodes[0].innerText || '').replace(/\s+/g, ' ').trim()
                  : null,
                charge: (() => {
                  const bars = [...document.querySelectorAll('#js_freeChargeBar')];
                  if (bars.length !== 1) return null;
                  const bar = bars[0];
                  return {className: bar.className,
                    serverTime: bar.dataset.server_time || null,
                    chargeTime: bar.dataset.charge_time || null,
                    chargeDuration: bar.dataset.charge_duration || null};
                })(),
                zeroPlus: text('.PCM-freeplusStatusBar'),
                binge: text('.PCM-bingefreeStatusBar')
              };
              });
            }""",
            [{"product": identity.product_id, "episode": identity.episode_id} for identity in identities],
        )
        if not isinstance(values, list) or len(values) != len(identities):
            raise UnknownPageStateError("Piccoma ticket state is malformed")
        for value, identity in zip(values, identities, strict=True):
            if not isinstance(value, dict):
                raise UnknownPageStateError("Piccoma ticket state is malformed")
            if (
                value.get("productId") != identity.product_id
                or value.get("episodeId") != identity.episode_id
                or value.get("rowCount") != 1
                or value.get("statusCount") != 1
                or value.get("loggedIn") is not True
                or not isinstance(value.get("markers"), list)
                or not all(isinstance(marker, str) for marker in value["markers"])
                or not isinstance(value.get("title"), str)
                or not value["title"].strip()
            ):
                raise UnknownPageStateError(
                    "Piccoma target row is absent, duplicated, or incomplete"
                )
        return values

    async def _fetch_ticket_state_snapshot(
        self, page: Page, identity: PiccomaEpisodeIdentity, *, include_listing: bool = True,
    ) -> dict[str, Any]:
        value = await page.evaluate(
            r"""async target => {
              const origin = window.location.origin;
              if (!['https://piccoma.com', 'https://www.piccoma.com'].includes(origin))
                return null;
              const read = async (path, includeEpisodeRow) => {
                const requested = new URL(path, origin);
                if (requested.origin !== origin || requested.search || requested.hash)
                  return null;
                const controller = new AbortController();
                const timer = setTimeout(() => controller.abort(), 8000);
                let html;
                try {
                  const response = await fetch(requested.href, {
                    method: 'GET', credentials: 'same-origin', cache: 'no-store',
                    redirect: 'error', signal: controller.signal
                  });
                  const finalUrl = new URL(response.url);
                  if (!response.ok || finalUrl.origin !== origin ||
                      finalUrl.pathname !== requested.pathname || finalUrl.search ||
                      finalUrl.hash || !/^text\/html(?:;|$)/i.test(
                        response.headers.get('content-type') || '')) return null;
                  const length = Number(response.headers.get('content-length'));
                  if (Number.isFinite(length) && length > 1500000) return null;
                  const reader = response.body?.getReader();
                  if (!reader) return null;
                  const chunks = [];
                  let size = 0;
                  while (true) {
                    const part = await reader.read();
                    if (part.done) break;
                    size += part.value.byteLength;
                    if (size > 1500000) {
                      await reader.cancel();
                      return null;
                    }
                    chunks.push(part.value);
                  }
                  const bytes = new Uint8Array(size);
                  let offset = 0;
                  for (const chunk of chunks) {
                    bytes.set(chunk, offset);
                    offset += chunk.byteLength;
                  }
                  html = new TextDecoder('utf-8', {fatal: true}).decode(bytes);
                } finally {
                  clearTimeout(timer);
                }
                const doc = new DOMParser().parseFromString(html, 'text/html');
                const text = selector => {
                  const nodes = [...doc.querySelectorAll(selector)];
                  return nodes.length === 1
                    ? (nodes[0].innerText || '').replace(/\s+/g, ' ').trim()
                    : null;
                };
                const rows = includeEpisodeRow ? [...doc.querySelectorAll(
                  '#js_episodeList a[data-product_id][data-episode_id]')]
                  .filter(anchor => anchor.getAttribute('data-product_id') === target.product &&
                    anchor.getAttribute('data-episode_id') === target.episode) : [];
                const anchor = rows.length === 1 ? rows[0] : null;
                const statuses = anchor
                  ? [...anchor.querySelectorAll('.PCM-epList_status')] : [];
                const status = statuses.length === 1 ? statuses[0] : null;
                const markers = status
                  ? [status, ...status.querySelectorAll('[class]')]
                      .flatMap(node => [...node.classList])
                      .filter(name => name.startsWith('PCM-epList_status_'))
                  : [];
                const titleNodes = [...doc.querySelectorAll(
                  '#js_contentBody .PCM-headTitle_name')];
                const chargeBars = [...doc.querySelectorAll('#js_freeChargeBar')];
                const chargeBar = chargeBars.length === 1 ? chargeBars[0] : null;
                return {
                  productId: includeEpisodeRow
                    ? (anchor?.getAttribute('data-product_id') || null) : target.product,
                  episodeId: includeEpisodeRow
                    ? (anchor?.getAttribute('data-episode_id') || null) : null,
                  userAccess: anchor?.getAttribute('data-user_access') || null,
                  rowCount: includeEpisodeRow ? rows.length : 0,
                  statusCount: statuses.length,
                  markers: [...new Set(markers)],
                  label: (status?.innerText || '').replace(/\s+/g, ' ').trim(),
                  title: titleNodes.length === 1
                    ? (titleNodes[0].innerText || '').replace(/\s+/g, ' ').trim()
                    : null,
                  charge: chargeBar ? {className: chargeBar.className,
                    serverTime: chargeBar.getAttribute('data-server_time'),
                    chargeTime: chargeBar.getAttribute('data-charge_time'),
                    chargeDuration: chargeBar.getAttribute('data-charge_duration')} : null,
                  zeroPlus: text('.PCM-freeplusStatusBar'),
                  binge: text('.PCM-bingefreeStatusBar')
                };
              };
              const [listing, home] = await Promise.all([
                target.includeListing
                  ? read(`/web/product/${target.product}/episodes`, true) : Promise.resolve({}),
                read(`/web/product/${target.product}`, false)
              ]);
              return listing && home ? {listing, home} : null;
            }""",
            {"product": identity.product_id, "episode": identity.episode_id,
             "includeListing": include_listing},
        )
        if not isinstance(value, dict):
            raise UnknownPageStateError("Piccoma fresh post-entry state was unavailable")
        listing = value.get("listing")
        home = value.get("home")
        if not isinstance(listing, dict) or not isinstance(home, dict):
            raise UnknownPageStateError("Piccoma fresh post-entry state was incomplete")
        return {"listing": listing, "home": home}

    async def _redeem_one_ticket(
        self, page: Page, identity: PiccomaEpisodeIdentity
    ) -> tuple[Response, str]:
        state = await self._read_ticket_state(page, identity)
        if state.get("userAccess") != "require":
            raise UnknownPageStateError("Piccoma ticket target is not freshly locked")
        observed_markers = set(state["markers"])
        if classify_piccoma_access(observed_markers, state["label"]) != "quota":
            raise UnknownPageStateError("Piccoma ticket row has an unsupported access state")
        before = await self._fetch_ticket_state_snapshot(page, identity)
        listing_before = before["listing"]
        home_before = before["home"]
        if (
            listing_before.get("productId") != identity.product_id
            or listing_before.get("episodeId") != identity.episode_id
            or listing_before.get("rowCount") != 1
            or listing_before.get("statusCount") != 1
            or listing_before.get("userAccess") != "require"
            or listing_before.get("markers") != state.get("markers")
            or listing_before.get("label") != state.get("label")
            or listing_before.get("title") != state.get("title")
        ):
            raise UnknownPageStateError(
                "Piccoma freshly fetched product state does not match the target listing"
            )
        for key in ("charge", "zeroPlus", "binge"):
            state[key] = home_before.get(key)
        daily_ready = waitfree_charge_ready(state.get("charge"))
        if daily_ready is None:
            raise UnknownPageStateError(
                "Piccoma charge attributes are missing or malformed"
            )
        zero_before = zero_plus_available_count(state.get("zeroPlus") or "")
        binge_before = binge_available_count(state.get("binge") or "")
        allowed_kinds = _TICKET_KINDS_BY_RESOURCE[self._required_ticket_resource()]
        row_secondary: list[tuple[PiccomaTicketKind, int | None]] = []
        if TICKET_ROW_MARKER["zero_plus"] in observed_markers:
            row_secondary.append(("zero_plus", zero_before))
        if TICKET_ROW_MARKER["binge_free"] in observed_markers:
            row_secondary.append(("binge_free", binge_before))
        secondary_availability: list[tuple[PiccomaTicketKind, int | None]] = []
        if (
            "zero_plus" in allowed_kinds
            and TICKET_ROW_MARKER["zero_plus"] in observed_markers
        ):
            secondary_availability.append(("zero_plus", zero_before))
        if (
            "binge_free" in allowed_kinds
            and TICKET_ROW_MARKER["binge_free"] in observed_markers
        ):
            secondary_availability.append(("binge_free", binge_before))
        if not daily_ready and (
            not secondary_availability
            or all(balance == 0 for _, balance in secondary_availability)
        ):
            unavailable = secondary_availability or row_secondary or [("waitfree", None)]
            for unavailable_kind, _ in unavailable:
                self._report_ticket_attempt(
                    unavailable_kind,
                    "not_attempted",
                    PICCOMA_TICKET_NO_ACTION_REASON,
                )
            raise PiccomaTicketNoActionError()

        row = page.locator(
            f'{ROW_SELECTOR}[data-product_id="{identity.product_id}"]'
            f'[data-episode_id="{identity.episode_id}"]'
        )
        navigation_guard = _PiccomaTicketNavigationGuard(page, identity)
        await navigation_guard.install()
        self._ticket_navigation_guard = navigation_guard
        navigation_guard.begin_eligibility()
        try:
            async with page.expect_response(
                lambda response: self._is_target_access_response(response, identity),
                timeout=TICKET_ELIGIBILITY_TIMEOUT_MS,
            ) as response_info:
                await row.click(timeout=5_000)
            eligibility_response = await response_info.value
        except Exception as exc:
            raise UnknownPageStateError(
                "Piccoma ticket eligibility exchange was not bound to the target"
            ) from exc
        navigation_guard.end_eligibility()
        if navigation_guard.eligibility_invalid or navigation_guard.access_request_count != 1:
            raise UnknownPageStateError(
                "Piccoma ticket eligibility was not a single exact target request"
            )
        try:
            status_code = await self._access_response_status(eligibility_response)
        except UnknownPageStateError:
            if navigation_guard.blocked_navigation_count:
                for offered_kind, marker in TICKET_ROW_MARKER.items():
                    if marker in observed_markers:
                        self._report_ticket_attempt(
                            offered_kind,
                            "not_attempted",
                            "eligibility_navigation_blocked_before_affirmative",
                        )
            raise
        kind = piccoma_ticket_kind_from_status(status_code)
        if kind is None:
            if is_known_nonfree_offer_status(status_code):
                for offered_kind, marker in TICKET_ROW_MARKER.items():
                    if marker in observed_markers:
                        self._report_ticket_attempt(
                            offered_kind,
                            "not_attempted",
                            f"{PICCOMA_TICKET_NO_ACTION_REASON}:status_{status_code}",
                        )
                raise PiccomaTicketNoActionError()
            raise UnknownPageStateError("Piccoma ticket eligibility returned an unknown status")
        self._ticket_kind = kind
        if TICKET_ROW_MARKER[kind] not in observed_markers:
            raise UnknownPageStateError(
                "Piccoma eligibility response does not match the target ticket icon"
            )
        if daily_ready and kind != "waitfree":
            raise UnknownPageStateError(
                "Piccoma selected a secondary ticket while the daily ticket is charged"
            )
        if kind == "waitfree" and not daily_ready:
            raise UnknownPageStateError(
                "Piccoma daily ticket status does not confirm a completed charge"
            )
        if not self._ticket_kind_allowed(kind):
            self._report_ticket_attempt(
                kind, "not_attempted", "ticket_kind_not_allowed_for_resource"
            )
            raise PiccomaTicketNoActionError()
        if kind == "zero_plus" and zero_before is None:
            raise UnknownPageStateError("Piccoma ¥0+ balance is missing or ambiguous")
        if kind == "binge_free" and binge_before is None:
            raise UnknownPageStateError("Piccoma binge balance is missing or ambiguous")
        if kind == "zero_plus" and zero_before == 0:
            self._report_ticket_attempt(kind, "not_attempted", PICCOMA_TICKET_NO_ACTION_REASON)
            raise PiccomaTicketNoActionError()
        if kind == "binge_free" and binge_before == 0:
            self._report_ticket_attempt(kind, "not_attempted", PICCOMA_TICKET_NO_ACTION_REASON)
            raise PiccomaTicketNoActionError()

        modal = page.locator(RESUME_DIALOG_SELECTOR)
        try:
            await modal.wait_for(state="visible", timeout=TICKET_MODAL_TIMEOUT_MS)
        except Exception as exc:
            raise UnknownPageStateError("Piccoma ticket confirmation modal was not observed") from exc
        if await modal.count() != 1 or await page.locator(".jconfirm-open").count() != 1:
            raise UnknownPageStateError("Piccoma ticket confirmation modal is ambiguous")
        evidence = await modal.evaluate(TICKET_MODAL_EVIDENCE_JS)
        if not isinstance(evidence, dict):
            raise UnknownPageStateError("Piccoma ticket modal evidence is malformed")
        text = evidence.get("text")
        buttons = evidence.get("buttons")
        if (
            evidence.get("structure") is not True
            or evidence.get("anchors") != 0
            or not isinstance(text, str)
            or not isinstance(buttons, list)
            or len(buttons) != 2
        ):
            raise UnknownPageStateError("Piccoma ticket modal structure is not supported")
        affirmative_matches = [
            index for index, button in enumerate(buttons)
            if isinstance(button, dict)
            and TICKET_BUTTON_CLASS[kind] in button.get("classes", [])
            and button.get("text") == TICKET_BUTTON_LABEL[kind]
        ]
        affirmative_index = affirmative_matches[0] if len(affirmative_matches) == 1 else None
        cancel_indices = [
            index for index, button in enumerate(buttons)
            if isinstance(button, dict) and button.get("text") == "キャンセル"
        ]
        if affirmative_index is None or len(cancel_indices) != 1 or affirmative_index == cancel_indices[0]:
            raise UnknownPageStateError("Piccoma ticket modal buttons are not uniquely identified")
        affirmative = buttons[affirmative_index]
        cancel = buttons[cancel_indices[0]]
        if (
            affirmative.get("visible") is not True
            or affirmative.get("disabled") is not False
            or affirmative.get("ariaDisabled") == "true"
            or cancel.get("visible") is not True
            or cancel.get("disabled") is not False
            or cancel.get("ariaDisabled") == "true"
            or any(
                "btn-gift-ticket" in button.get("classes", [])
                for button in buttons if isinstance(button, dict)
            )
        ):
            raise UnknownPageStateError("Piccoma ticket modal has no safe enabled option")

        zero_modal_balance: int | None = None
        binge_modal_balance: tuple[int, int] | None = None
        if kind == "waitfree":
            if not ticket_modal_matches(kind, text):
                raise UnknownPageStateError("Piccoma waitfree modal text is not recognized")
        elif kind == "zero_plus":
            zero_modal_balance = zero_plus_modal_balance(text)
            if zero_modal_balance is None or not ticket_modal_matches(kind, text):
                raise UnknownPageStateError("Piccoma ¥0+ modal balance is missing")
            if zero_modal_balance <= 0:
                self._report_ticket_attempt(kind, "not_attempted", PICCOMA_TICKET_NO_ACTION_REASON)
                raise PiccomaTicketNoActionError()
            if zero_modal_balance != zero_before:
                raise UnknownPageStateError(
                    "Piccoma ¥0+ modal balance does not match fresh product state"
                )
        else:
            binge_modal_balance = binge_modal_balances(text)
            if binge_modal_balance is None or not ticket_modal_matches(kind, text):
                raise UnknownPageStateError("Piccoma binge modal balances are missing")
            if binge_modal_balance[0] <= 0 or binge_modal_balance[1] <= 0:
                self._report_ticket_attempt(kind, "not_attempted", PICCOMA_TICKET_NO_ACTION_REASON)
                raise PiccomaTicketNoActionError()
            if binge_modal_balance[1] != binge_before:
                raise UnknownPageStateError(
                    "Piccoma binge work balance does not match fresh product state"
                )

        if (
            navigation_guard.eligibility_invalid
            or navigation_guard.blocked_access_request_count
            or navigation_guard.blocked_navigation_count
            or navigation_guard.blocked_popup_count
        ):
            raise UnknownPageStateError(
                "Piccoma ticket entry attempted an unexpected request or navigation"
            )

        observed_at = observed_now()
        try:
            try:
                async with page.expect_response(
                    lambda response: (
                        response.request.resource_type == "document"
                        and response.request.method.upper() == "GET"
                        and self._viewer_identity_from_url(response.url) == identity
                    ),
                    timeout=TICKET_ACTION_TIMEOUT_MS,
                ) as viewer_info:
                    await self._click_verified_ticket_button(
                        page,
                        modal,
                        kind,
                        evidence,
                        navigation_guard,
                        record_attempt=lambda: self.report_access_attempt(
                            AccessAttemptObservation(
                                site="piccoma",
                                external_id=identity.external_id,
                                resource=self._quota_resource or "piccoma_ticket_auto",
                                resource_kind=kind,
                                status="attempting",
                                observed_at=observed_now(),
                            )
                        ),
                    )
                viewer_response = await viewer_info.value
            except Exception as exc:
                if not self._ticket_attempt_started:
                    raise
                self._report_ticket_attempt(kind, "unknown", "viewer_navigation_unconfirmed")
                raise UnknownPageStateError(
                    "Piccoma ticket action may have been dispatched; viewer navigation is unknown"
                ) from exc
            if viewer_response.status != 200:
                self._report_ticket_attempt(kind, "unknown", "viewer_response_unconfirmed")
                raise UnknownPageStateError("Piccoma target viewer document was not HTTP 200")

            try:
                await page.wait_for_url(
                    lambda url: self._viewer_identity_from_url(str(url)) == identity,
                    timeout=TICKET_VIEWER_TIMEOUT_MS,
                    wait_until="domcontentloaded",
                )
                await page.wait_for_load_state(
                    "domcontentloaded", timeout=TICKET_VIEWER_DOM_TIMEOUT_MS
                )
            except Exception as exc:
                self._report_ticket_attempt(kind, "unknown", "viewer_navigation_unconfirmed")
                raise UnknownPageStateError(
                    "Piccoma ticket action did not reach the target viewer"
                ) from exc
            fresh = await self._fetch_ticket_state_snapshot(page, identity)
            listing = fresh["listing"]
            home = fresh["home"]
            post_markers = listing.get("markers")
            if (
                listing.get("productId") != identity.product_id
                or listing.get("episodeId") != identity.episode_id
                or listing.get("rowCount") != 1
                or listing.get("statusCount") != 1
                or not isinstance(post_markers, list)
                or "PCM-epList_status_waitfreeRead" not in post_markers
            ):
                self._report_ticket_attempt(kind, "unknown", "target_grant_unconfirmed")
                raise UnknownPageStateError("Piccoma ticket target grant was not confirmed")
            grant_until = piccoma_manual_grant_until(
                post_markers, str(listing.get("label") or ""), observed_at
            )
            if grant_until is None or grant_until <= observed_at:
                self._report_ticket_attempt(kind, "unknown", "target_grant_expiry_unconfirmed")
                raise UnknownPageStateError("Piccoma ticket grant expiry was not confirmed")

            grant_observed_at = observed_now()
            self.report_confirmed_access_grant(
                ConfirmedAccessGrant(
                    site="piccoma",
                    external_id=identity.external_id,
                    observed_at=grant_observed_at,
                    access_granted_until=grant_until,
                    expiry_evidence="site_countdown_lower_bound",
                )
            )

            before_charge = state.get("charge")
            after_charge = home.get("charge")
            charge_shape_matches = (
                isinstance(before_charge, dict)
                and isinstance(after_charge, dict)
                and before_charge.get("className") == after_charge.get("className")
                and before_charge.get("chargeDuration") == after_charge.get("chargeDuration")
            )
            nonselected_balances_match = (
                (kind == "zero_plus" or home.get("zeroPlus") == state.get("zeroPlus"))
                and (kind == "binge_free" or home.get("binge") == state.get("binge"))
            )

            if kind == "waitfree":
                changed = (
                    charge_shape_matches
                    and waitfree_charge_ready(before_charge) is True
                    and waitfree_charge_ready(after_charge) is False
                    and before_charge.get("chargeTime") != after_charge.get("chargeTime")
                    and nonselected_balances_match
                )
            elif kind == "zero_plus":
                after_balance = zero_plus_available_count(str(home.get("zeroPlus") or ""))
                changed = (
                    after_balance == int(zero_before) - 1
                    and charge_shape_matches
                    and waitfree_charge_ready(before_charge) is False
                    and waitfree_charge_ready(after_charge) is False
                    and before_charge.get("chargeTime") == after_charge.get("chargeTime")
                    and nonselected_balances_match
                )
            else:
                after_balance = binge_available_count(str(home.get("binge") or ""))
                changed = (
                    after_balance == int(binge_before) - 1
                    and charge_shape_matches
                    and waitfree_charge_ready(before_charge) is False
                    and waitfree_charge_ready(after_charge) is False
                    and before_charge.get("chargeTime") == after_charge.get("chargeTime")
                    and nonselected_balances_match
                )
            if not changed:
                self._report_ticket_attempt(kind, "unknown", "ticket_balance_change_unconfirmed")
                raise UnknownPageStateError(
                    "Piccoma ticket balance change was not confirmed"
                )

            confirmed_at = observed_now()
            self._access_consumption = AccessConsumption(
                consumed=True,
                resource=self._required_ticket_resource(),
                consumed_at=confirmed_at,
                access_granted_until=grant_until,
            )
            self._report_ticket_attempt(kind, "confirmed", None)
            self._ticket_attempt_started = False
            await navigation_guard.remove_after_verified_entry()
            self._ticket_navigation_guard = None
            return viewer_response, str(listing.get("title") or state["title"])
        except BaseException:
            if self._ticket_attempt_started:
                self._report_ticket_attempt(kind, "unknown", "post_action_proof_incomplete")
            raise
    async def _click_verified_ticket_button(
        self,
        page: Page,
        modal: Locator,
        kind: PiccomaTicketKind,
        original_evidence: dict[str, Any],
        navigation_guard: _PiccomaTicketNavigationGuard,
        *,
        record_attempt: Callable[[], None],
    ) -> None:
        if not self._ticket_kind_allowed(kind):
            raise UnknownPageStateError(
                "Piccoma ticket kind is not allowed for the selected resource"
            )
        button = modal.locator(f"button.{TICKET_BUTTON_CLASS[kind]}").and_(
            modal.get_by_role("button", name=TICKET_BUTTON_LABEL[kind], exact=True)
        )

        async def exact_control_is_current() -> bool:
            if (
                not self._ticket_kind_allowed(kind)
                or
                await modal.count() != 1
                or await page.locator(".jconfirm-open").count() != 1
                or navigation_guard.eligibility_invalid
                or navigation_guard.blocked_access_request_count
                or navigation_guard.blocked_navigation_count
                or navigation_guard.blocked_popup_count
                or await navigation_guard.popup_was_attempted()
            ):
                return False
            return (
                await modal.evaluate(TICKET_MODAL_EVIDENCE_JS) == original_evidence
                and await button.count() == 1
            )

        if not await exact_control_is_current():
            raise UnknownPageStateError(
                "Piccoma ticket confirmation changed before the authorized action"
            )
        record_attempt()
        if not await exact_control_is_current():
            self._report_ticket_attempt(
                kind, "not_attempted", "confirmation_changed_before_dispatch"
            )
            raise UnknownPageStateError(
                "Piccoma ticket confirmation changed before the authorized action"
            )
        self._ticket_attempt_started = True
        navigation_guard.arm_viewer()
        await button.click(timeout=3_000)

    @staticmethod
    def _is_target_access_response(
        response: Response, identity: PiccomaEpisodeIdentity
    ) -> bool:
        request = response.request
        if not piccoma_access_endpoint_matches(
            method=request.method, url=request.url
        ):
            return False
        try:
            post_data = request.post_data
        except Exception:  # noqa: BLE001 - malformed/binary bodies are not a match
            return False
        return piccoma_access_request_matches(
            method=request.method,
            url=request.url,
            post_data=post_data,
            product_id=identity.product_id,
            episode_id=identity.episode_id,
        )

    async def _access_response_status(self, response: Response) -> object:
        if (
            response.status != 200
            or "application/json" not in (response.headers.get("content-type") or "").lower()
        ):
            raise UnknownPageStateError("Piccoma ticket eligibility response is not JSON HTTP 200")
        try:
            body = await response.json()
        except Exception as exc:
            raise UnknownPageStateError("Piccoma ticket eligibility JSON is malformed") from exc
        if not isinstance(body, dict):
            raise UnknownPageStateError("Piccoma ticket eligibility payload is malformed")
        return body.get("status")

    def _report_ticket_attempt(
        self,
        kind: PiccomaTicketKind,
        status: Literal["attempting", "confirmed", "unknown", "not_attempted"],
        reason: str | None,
    ) -> None:
        if status in {"confirmed", "unknown", "not_attempted"}:
            self._ticket_attempt_started = False
        identity = self._require_identity()
        self.report_access_attempt(
            AccessAttemptObservation(
                site="piccoma",
                external_id=identity.external_id,
                resource=self._required_ticket_resource(),
                resource_kind=kind,
                status=status,
                observed_at=observed_now(),
                reason=reason,
            )
        )

    def _ticket_kind_allowed(self, kind: PiccomaTicketKind) -> bool:
        resource = self._quota_resource
        return resource in _TICKET_KINDS_BY_RESOURCE and kind in _TICKET_KINDS_BY_RESOURCE[resource]

    def _required_ticket_resource(self) -> str:
        resource = self._quota_resource
        if resource not in _TICKET_KINDS_BY_RESOURCE:
            raise UnsupportedAccessStrategyError(
                "Piccoma ticket attempt has no configured logical resource"
            )
        return resource

    @staticmethod
    def _viewer_identity_from_url(url: str) -> PiccomaEpisodeIdentity | None:
        identity = parse_piccoma_viewer_url(url)
        if identity is not None:
            return identity
        parsed = urlparse(url)
        if parsed.path.startswith("/web/viewer/s/"):
            return parse_piccoma_viewer_url(
                parsed._replace(path=parsed.path.replace("/viewer/s/", "/viewer/", 1)).geturl()
            )
        return None

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
        started = time.monotonic()
        samples: deque[dict[str, Any]] = deque(maxlen=MAX_BODY_WAIT_DIAGNOSTIC_SAMPLES)
        diagnostics: dict[str, Any] = {
            "requested_page_id": f"p{number}",
            "expected_page_id_at_start": self._expected_page_id,
            "advance_from": self._advance_from,
            "sample_count": 0,
        }
        self._body_wait_failure = None
        try:
            await self._wait_for_body_ready(page, number, started, samples, diagnostics)
        except Exception as exc:
            # Keep the actual wait-time samples: a fresh diagnostics snapshot
            # can already show settled geometry and hide a transient failure.
            diagnostics.update(
                error_type=type(exc).__name__,
                error_message=str(exc),
                elapsed_ms=round((time.monotonic() - started) * 1000, 3),
                samples=list(samples),
            )
            self._body_wait_failure = diagnostics
            raise

    async def _wait_for_body_ready(
        self,
        page: Page,
        number: int,
        started: float,
        samples: deque[dict[str, Any]],
        diagnostics: dict[str, Any],
    ) -> None:
        deadline = time.monotonic() + self.page_change_timeout_ms / 1000
        previous_signature: tuple[object, ...] | None = None
        stable_samples = 0
        last_row: dict[str, Any] | None = None
        last_snapshot: dict[str, Any] | None = None
        while time.monotonic() <= deadline:
            snapshot = await self._reader_snapshot(page)
            active = snapshot.get("activeIds", [])
            observed_ids = [f"p{number}", *(active if isinstance(active, list) else [])]
            rows = snapshot.get("pages")
            sample = {
                "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
                "stable_samples": 0,
                "active_ids": active,
                "viewport": snapshot.get("viewport"),
                "frame_rect": snapshot.get("frameRect"),
                "reader_mode": {key: snapshot.get(key) for key in (
                    "rootCount", "pageListCount", "frameCount", "horizontal",
                    "leftToRight", "dialogCount",
                )},
                "pages": [row for row in (rows if isinstance(rows, list) else [])
                          if isinstance(row, dict) and row.get("id") in observed_ids],
            }
            diagnostics["sample_count"] += 1
            if diagnostics["sample_count"] == 1:
                diagnostics["first_sample"] = sample
            samples.append(sample)
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
                    and not (
                        self._advance_from == number - 1
                        and canvas.get("inFrame") is not True
                        and not self._overscan_geometry_is_valid(snapshot, row)
                    )
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
                    sample["stable_samples"] = stable_samples
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

    @staticmethod
    def _uses_additional_scaled_layout(snapshot: dict[str, Any], row: dict[str, Any]) -> bool:
        """Bind native scaling to the actual full-height reader, not source size.

        A small legacy 1:1 canvas/frame keeps its existing Locator fallback.
        Full-height readers require native proof for additional scaled sources,
        including low-resolution originals enlarged by the viewer.
        """
        canvas, frame = row.get("canvas"), snapshot.get("frameRect")
        eligible = (
            isinstance(canvas, dict)
            and is_additional_scaled_size(canvas.get("width"), canvas.get("height"))
            and isinstance(frame, list) and len(frame) == 4
            and type(frame[3]) in {int, float} and math.isfinite(frame[3])
            and abs(frame[3] - VIEWPORT_HEIGHT) <= 0.01
        )
        if not eligible:
            return False
        width, height = canvas.get("width"), canvas.get("height")
        observed = SCALED_DISPLAY_PROFILES.get((width, height))
        if (observed is not None and type(frame[2]) in {int, float}
                and math.isfinite(frame[2]) and abs(frame[2] - observed.frame_width) <= 0.01):
            return False
        return not is_ordinary_native_presentation(width, height, frame[2], canvas.get("rect"))

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
        additional_scaled = self._uses_additional_scaled_layout(snapshot, row)
        scaled_profile = (scaled_display_profile(width, height, frame_rect[2])
                          if additional_scaled or (width, height) in SCALED_NATIVE_SIZES else None)
        if additional_scaled and scaled_profile is None:
            raise UnknownPageStateError("Piccoma canvas does not match the supported viewport")
        overscan = self._overscan_geometry_is_valid(snapshot, row)
        legacy_overscan = overscan and (width, height) == OVERSCAN_NATIVE_SIZE
        display_width, display_height = (OVERSCAN_DISPLAY_SIZE if legacy_overscan else
                                        scaled_profile.display_size if scaled_profile else (width, height))
        frame_width = (764 if legacy_overscan else
                       scaled_profile.frame_width if scaled_profile else width)
        if (
            not isinstance(width, int)
            or isinstance(width, bool)
            or not isinstance(height, int)
            or isinstance(height, bool)
            or width <= 0
            or height <= 0
            or any(type(value) not in {int, float} or not math.isfinite(value) for value in [*rect, *frame_rect])
            or abs(float(rect[2]) - display_width) > 0.5
            or abs(float(rect[3]) - display_height) > 0.5
            or (not canvas.get("inFrame") and not overscan)
            or not self._viewport_is_supported(viewport)
            or float(rect[0]) < 0
            or (float(rect[1]) < 0 and not overscan)
            or float(rect[0]) + float(rect[2]) > viewport[0] + 0.5
            or (float(rect[1]) + float(rect[3]) > viewport[1] + 0.5 and not overscan)
            or abs(float(frame_rect[2]) - frame_width) > 0.5
            or abs(float(frame_rect[3]) - (1200 if scaled_profile else height)) > 0.5
            or (additional_scaled and (
                abs(frame_rect[0] - (VIEWPORT_WIDTH - scaled_profile.frame_width) / 2) > 0.01
                or abs(frame_rect[1]) > 0.01
                or (self._scaled_frame_rect is not None
                    and tuple(frame_rect) != self._scaled_frame_rect)
            ))
            or (scaled_profile and (
                abs(rect[2] - display_width) > SCALED_DISPLAY_WIDTH_TOLERANCE
                or abs(rect[3] - display_height) > 0.01
                or abs(frame_rect[2] - frame_width) > 0.01 or abs(frame_rect[3] - 1200) > 0.01
                # Live scaled pages use either aligned left edges or a -1/3
                # CSS-pixel offset (13565:664249). Keep both discrete profiles;
                # raw geometry must still remain identical across capture.
                or not any(
                    abs(rect[0] - frame_rect[0] - offset) <= 0.01
                    for offset in (0, -1 / 3)
                )
                or abs(rect[1] - frame_rect[1] - scaled_profile.top_offset) > 0.01
            ))
        ):
            raise UnknownPageStateError("Piccoma canvas does not match the supported viewport")
        return width, height

    @staticmethod
    def _overscan_geometry_is_valid(snapshot: dict[str, Any], row: dict[str, Any]) -> bool:
        """Recognize live-proven centered overscan; native capture is mandatory."""
        canvas = row.get("canvas")
        if not isinstance(canvas, dict):
            return False
        size = (canvas.get("width"), canvas.get("height"))
        rect, frame = canvas.get("rect"), snapshot.get("frameRect")
        if (not isinstance(rect, list) or not isinstance(frame, list)
                or len(rect) != 4 or len(frame) != 4
                or any(type(v) not in {int, float} or not math.isfinite(v) for v in [*rect, *frame])):
            return False
        profile = scaled_display_profile(*size, frame[2])
        if profile is not None and (
            profile.display_size[1] > VIEWPORT_HEIGHT
            or profile.display_size[0] > profile.frame_width + 0.5
        ):
            return (
                # The reader snapshot includes a 0.5px tolerance per edge;
                # centered 1201px content therefore still reports inFrame.
                canvas.get("inFrame") is (
                    profile.display_size[1] <= VIEWPORT_HEIGHT + 1
                    and profile.display_size[0] <= profile.frame_width + 0.5
                )
                and abs(rect[2] - profile.display_size[0]) <= SCALED_DISPLAY_WIDTH_TOLERANCE
                and abs(rect[3] - profile.display_size[1]) <= 0.01
                and abs(frame[2] - profile.frame_width) <= 0.01
                and abs(frame[3] - VIEWPORT_HEIGHT) <= 0.01
                and abs(frame[0] - (VIEWPORT_WIDTH - profile.frame_width) / 2) <= 0.01
                and abs(frame[1]) <= 0.01
                # General scaled overscan shares the ordinary scaled offsets.
                # Keep the legacy overscan profile's aligned-only contract.
                and any(
                    abs(rect[0] - frame[0] - offset) <= 0.01
                    for offset in ((0,) if size == OVERSCAN_NATIVE_SIZE else (0, -1 / 3))
                )
                and abs(rect[1] - frame[1] - profile.top_offset) <= 0.01
            )
        if size != OVERSCAN_NATIVE_SIZE:
            return False
        return (
            canvas.get("inFrame") is False
            and abs(rect[2] - OVERSCAN_DISPLAY_SIZE[0]) <= 0.01
            and abs(rect[3] - OVERSCAN_DISPLAY_SIZE[1]) <= 0.01
            and abs(frame[2] - 764) <= 0.01 and abs(frame[3] - 1200) <= 0.01
            and abs(rect[0] - frame[0]) <= 0.01
            and abs(rect[1] - frame[1] + 1) <= 0.01
            and 0 <= frame[0] and frame[0] + frame[2] <= VIEWPORT_WIDTH + 0.01
            and abs(frame[1]) <= 0.01
        )

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
        # Grant-only uses the same exact access checks as Batch. If live state
        # became free or already granted after planning, initialize records any
        # fresh grant and returns a no-action skip before opening the viewer.
        await self.initialize(page)

    async def detect_state(self, page: Page) -> PageState:
        if not self._matches_viewer_url(page):
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

    async def get_capture_targets(self, page: Page) -> tuple[Locator, ...]:
        # Core may request fallback targets after an adapter timeout. Native-only
        # scaled/overscan profiles and additional ordinary widths still need proof.
        snapshot = await self._reader_snapshot(page)
        if self._capture_interruption is not None:
            self._validate_reader_mode(snapshot)
            if not self._matches_viewer_url(page):
                raise UnknownPageStateError("Piccoma fallback reader identity changed after capture interruption")
        active = snapshot.get("activeIds")
        if active != [self._expected_page_id] or self._expected_page_id is None:
            raise UnknownPageStateError("Piccoma fallback target is not the expected body page")
        row = self._page_row(snapshot, self._expected_page_id)
        canvas = row.get("canvas")
        if isinstance(canvas, dict) and (
            (canvas.get("width"), canvas.get("height")) in SCALED_NATIVE_ONLY_SIZES
            or self._uses_additional_scaled_layout(snapshot, row)
        ):
            self._validate_canvas_geometry(snapshot, row)
            self._raise_native_fallback_error("scaled")
        if isinstance(canvas, dict) and (canvas.get("width"), canvas.get("height")) == OVERSCAN_NATIVE_SIZE:
            self._validate_canvas_geometry(snapshot, row)
            if self._overscan_geometry_is_valid(snapshot, row):
                self._raise_native_fallback_error("overscan")
        if isinstance(canvas, dict) and is_additional_ordinary_size(canvas.get("width"), canvas.get("height")):
            self._validate_canvas_geometry(snapshot, row)
            self._raise_native_fallback_error("ordinary-width")
        return await super().get_capture_targets(page)

    def _raise_native_fallback_error(self, profile: str) -> None:
        interruption = self._capture_interruption
        if interruption is not None and interruption["page_id"] == self._expected_page_id:
            # Core reaches fallback after cancelling an expired capture hook.
            # Keep that timeout retryable; never offer a display screenshot.
            raise PageChangeTimeoutError(
                "Piccoma native capture timed out "
                f"(page={interruption['page_id']}, stage={interruption['stage']}, "
                f"elapsed_ms={interruption['elapsed_ms']})"
            )
        raise UnknownPageStateError(f"Piccoma {profile} page requires verified native capture")

    async def capture_page(self, page: Page) -> tuple[CaptureResult, ...] | None:
        self._capture_interruption = None
        self._capture_started = self._capture_stage_started = time.monotonic()
        self._capture_timing = {
            "page_id": self._expected_page_id, "stage": "reader_validation",
            "stages_ms": {}, "outcome": "running",
        }
        outcome = "failed"
        try:
            result = await self._capture_verified_page(page)
            outcome = "succeeded"
            return result
        except asyncio.CancelledError:
            # Cancellation itself still propagates. Only a later Core fallback
            # request may interpret this as its own expired capture deadline.
            self._capture_interruption = {
                "page_id": self._expected_page_id,
                "stage": self._capture_timing.get("failure_stage", self._capture_timing["stage"]),
                "elapsed_ms": round((time.monotonic() - self._capture_started) * 1000, 3),
            }
            outcome = "cancelled"
            raise
        finally:
            self._mark_capture_stage(self._capture_timing["stage"])
            self._capture_timing["outcome"] = outcome
            self._capture_timing["elapsed_ms"] = round(
                (time.monotonic() - self._capture_started) * 1000, 3
            )
            if outcome != "succeeded":
                self._capture_timing.setdefault("failure_stage", self._capture_timing["stage"])

    def _mark_capture_stage(self, stage: str) -> None:
        timing = self._capture_timing
        if timing is None:
            return
        now = time.monotonic()
        previous = timing["stage"]
        spans = timing["stages_ms"]
        spans[previous] = round(spans.get(previous, 0) + (now - self._capture_stage_started) * 1000, 3)
        timing["stage"] = stage
        self._capture_stage_started = now

    async def _capture_verified_page(self, page: Page) -> tuple[CaptureResult, ...] | None:
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
        if self._capture_timing is not None:
            self._capture_timing["native_size"] = list(expected_size)
        overscan = self._overscan_geometry_is_valid(before, row)
        native_only_scaled = (expected_size in SCALED_NATIVE_ONLY_SIZES
                              or self._uses_additional_scaled_layout(before, row))
        requires_native = overscan or native_only_scaled or is_additional_ordinary_size(*expected_size)
        native_profile = "overscan" if overscan else "scaled" if native_only_scaled else "ordinary-width"
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
            self._mark_capture_stage("native_capture")
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
                    max_episode_bytes=(
                        MAX_SCALED_NATIVE_EPISODE_BYTES
                        if (expected_size in SCALED_NATIVE_SIZES
                            or (expected_size != OVERSCAN_NATIVE_SIZE
                                and self._uses_additional_scaled_layout(before, row)))
                        else MAX_NATIVE_EPISODE_BYTES
                    ),
                    report_stage=self._mark_capture_stage,
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
                if requires_native:
                    raise UnknownPageStateError(
                        f"Piccoma {native_profile} page requires verified native capture"
                        f" (native_fallback={self._capture_fallback_reason}, "
                        f"expected={expected_size[0]}x{expected_size[1]})"
                    )
                self._mark_capture_stage("rendered_capture")
                result = await capture_locator(target)
                self._capture_method = "core_canvas_or_locator_png"
                self._capture_source_native = False
                self._capture_source_mime = None
                self._capture_backdrop = None
                self._capture_encoding_fallback_reason = None
            self._mark_capture_stage("post_capture_validation")
            after = await self._reader_snapshot(page)
            self._validate_capture_post_state(
                page, before, after, current, row, expected_size, result
            )
            await self._validate_target_generation_unchanged(
                page, target, target_baseline_signature
            )
            if native_result is not None:
                self._mark_capture_stage("source_revalidation")
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
                    if requires_native:
                        raise UnknownPageStateError(
                            f"Piccoma {native_profile} page requires verified native capture"
                            f" (native_fallback={fallback_reason}, "
                            f"expected={expected_size[0]}x{expected_size[1]})"
                        )
                    self._capture_encoding_fallback_reason = None
                    self._capture_method = "core_canvas_or_locator_png"
                    self._capture_source_native = False
                    self._capture_source_mime = None
                    self._capture_backdrop = None
                    self._mark_capture_stage("rendered_capture")
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
        except BaseException:
            if self._capture_timing is not None:
                self._capture_timing["failure_stage"] = self._capture_timing["stage"]
            raise
        finally:
            self._mark_capture_stage("cleanup")
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
            not self._matches_viewer_url(page)
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
                f" (method={self._capture_method}, "
                f"native_fallback={self._capture_fallback_reason}, "
                f"expected={expected_size[0]}x{expected_size[1]}, "
                f"actual={result.width}x{result.height} {result.mime_type})"
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
        if not self._matches_viewer_url(page):
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
            if not self._matches_viewer_url(page):
                raise UnknownPageStateError("Piccoma page transition changed the viewer URL")
            self._expected_page_id = f"p{expected}"
            self._advance_from = None
            return
        if self._advance_from != self._page_count:
            raise UnknownPageStateError("Piccoma END was requested before the final body page")
        await self._wait_for_end(page)
        if not self._matches_viewer_url(page):
            raise UnknownPageStateError("Piccoma END transition changed the viewer URL")
        self._expected_page_id = "last"
        self._terminal = True

    def _matches_viewer_url(self, page: Page) -> bool:
        return (
            self._source_identity is not None
            and self._viewer_url is not None
            and page.url == self._viewer_url
        )

    def _require_identity(self) -> PiccomaEpisodeIdentity:
        if self._source_identity is None:
            raise UnknownPageStateError("Piccoma target identity has not been configured")
        return self._source_identity

    async def collect_debug_metadata(self, page: Page) -> dict[str, Any]:
        del page
        metadata = {
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
        if self._body_wait_failure is not None:
            metadata["piccoma_body_wait_failure"] = self._body_wait_failure
        if self._capture_interruption is not None:
            metadata["piccoma_capture_interruption"] = dict(self._capture_interruption)
        if self._capture_timing is not None and self._capture_timing["outcome"] != "succeeded":
            metadata["piccoma_capture_timing"] = {
                **self._capture_timing, "stages_ms": dict(self._capture_timing["stages_ms"]),
            }
        return metadata

    def get_output_metadata(self) -> dict[str, str | None]:
        return {"title": self._title}


__all__ = ["PiccomaAdapter"]
