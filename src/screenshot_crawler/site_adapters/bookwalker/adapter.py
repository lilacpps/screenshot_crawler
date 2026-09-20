"""Adapter for the BookWalker image/canvas browser viewer.

The viewer shell is a canvas renderer. This adapter intentionally uses only
stable DOM signals exposed by the viewer shell and stops on ambiguous states.
"""

from __future__ import annotations

import asyncio
import base64
import re
from binascii import Error as BinasciiError
from typing import Any
from urllib.parse import parse_qs, urlparse

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from screenshot_crawler.core.capture import CaptureResult, capture_png_bytes
from screenshot_crawler.core.errors import (
    CaptureUnavailableError,
    PageChangeTimeoutError,
    UnsupportedAccessStrategyError,
)
from screenshot_crawler.core.models import AccessStrategy, ContentContext, ContentIdentity
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.base import SiteAdapter
from screenshot_crawler.site_adapters.bookwalker.login import login_bookwalker
from screenshot_crawler.site_adapters.bookwalker.native_capture import (
    select_native_draw_calls,
)
from screenshot_crawler.site_adapters.bookwalker.original_capture import (
    MAX_RESPONSE_BODY_BYTES,
    OriginalJpegCache,
    candidate_capture,
    candidate_from_jpeg,
    image_signature,
)
from screenshot_crawler.site_adapters.bookwalker.reader_controls import (
    ReaderControlKind,
    classify_reader_control,
    is_reader_control_candidate,
)

_DRAW_TRACE_SCRIPT = """
(() => {
  if (window.__bookwalkerDrawTraceInstalled) return;
  window.__bookwalkerDrawTraceInstalled = true;
  window.__bookwalkerDrawCalls = [];
  window.__bookwalkerNativeCaptureEnabled = true;
  window.__bookwalkerNativeDrawCalls = [];
  window.__bookwalkerNativeSourceObjects = new Map();
  if (window.__bookwalkerNativeEagerCapture === undefined) {
    window.__bookwalkerNativeEagerCapture = false;
  }
  const original = CanvasRenderingContext2D.prototype.drawImage;
  let nextCanvasId = 1;
  let nextSourceId = 1;
  const canvasIds = new WeakMap();
  const sourceIds = new WeakMap();
  const getCanvasId = canvas => {
    let id = canvasIds.get(canvas);
    if (!id) {
      id = String(nextCanvasId++);
      canvasIds.set(canvas, id);
      canvas.dataset.bookwalkerTraceId = id;
    }
    return id;
  };
  const getSourceId = source => {
    let id = sourceIds.get(source);
    if (!id) {
      id = String(nextSourceId++);
      sourceIds.set(source, id);
    }
    window.__bookwalkerNativeSourceObjects.set(id, source);
    return id;
  };
  const sourceRectAndDestination = (source, values) => {
    const width = Number.isFinite(source?.width) ? Number(source.width) : null;
    const height = Number.isFinite(source?.height) ? Number(source.height) : null;
    if (values.length === 2 && width !== null && height !== null) {
      return {
        sourceRect: {x: 0, y: 0, width, height},
        destination: {x: values[0], y: values[1], width, height},
      };
    }
    if (values.length === 4) {
      return {
        sourceRect: width === null || height === null
          ? null : {x: 0, y: 0, width, height},
        destination: {
          x: values[0], y: values[1], width: values[2], height: values[3],
        },
      };
    }
    if (values.length === 8) {
      return {
        sourceRect: {
          x: values[0], y: values[1], width: values[2], height: values[3],
        },
        destination: {
          x: values[4], y: values[5], width: values[6], height: values[7],
        },
      };
    }
    return {sourceRect: null, destination: null};
  };
  const copySourceCrop = (source, sourceRect) => {
    if (!sourceRect || sourceRect.width <= 0 || sourceRect.height <= 0) {
      return {dataUrl: null, error: 'invalid source rectangle'};
    }
    const target = document.createElement('canvas');
    target.width = Math.round(sourceRect.width);
    target.height = Math.round(sourceRect.height);
    const context = target.getContext('2d');
    if (!context) return {dataUrl: null, error: '2d context unavailable'};
    try {
      original.call(
        context,
        source,
        sourceRect.x, sourceRect.y, sourceRect.width, sourceRect.height,
        0, 0, sourceRect.width, sourceRect.height,
      );
      return {dataUrl: target.toDataURL('image/png'), error: null};
    } catch (error) {
      return {dataUrl: null, error: String(error)};
    }
  };
  window.__bookwalkerMaterializeNativeSourceCrop = ({sourceId, sourceRect}) => (
    copySourceCrop(
      window.__bookwalkerNativeSourceObjects.get(String(sourceId)),
      sourceRect,
    )
  );
  CanvasRenderingContext2D.prototype.drawImage = function(...args) {
    try {
      const canvas = this.canvas;
      const values = args.slice(1).map(value => Number(value));
      const geometry = sourceRectAndDestination(args[0], values);
      if (canvas && canvas.width > 1000 && canvas.height > 500) {
        const destination = values.length >= 8
          ? values.slice(4, 8)
          : geometry.destination
            ? [
                geometry.destination.x, geometry.destination.y,
                geometry.destination.width, geometry.destination.height,
              ]
            : null;
        if (destination) {
          window.__bookwalkerDrawCalls.push({
            canvasId: getCanvasId(canvas),
            canvasWidth: canvas.width,
            canvasHeight: canvas.height,
            destination,
          });
          if (window.__bookwalkerDrawCalls.length > 500) {
            window.__bookwalkerDrawCalls.shift();
          }
        }
        if (window.__bookwalkerNativeCaptureEnabled && args[0] && geometry.destination) {
          const source = args[0];
          let transform = null;
          try {
            const matrix = this.getTransform();
            transform = {
              a: matrix.a, b: matrix.b, c: matrix.c,
              d: matrix.d, e: matrix.e, f: matrix.f,
            };
          } catch (error) {}
          const nativeCall = {
            timestamp: performance.now(),
            canvasId: getCanvasId(canvas),
            canvasWidth: canvas.width,
            canvasHeight: canvas.height,
            sourceId: getSourceId(source),
            source: {
              constructor: source?.constructor?.name || null,
              width: Number.isFinite(source?.width) ? Number(source.width) : null,
              height: Number.isFinite(source?.height) ? Number(source.height) : null,
            },
            sourceRect: geometry.sourceRect,
            destination: geometry.destination,
            argumentForm: values.length + 1,
            transform,
            globalCompositeOperation: this.globalCompositeOperation,
            filter: this.filter,
          };
          if (window.__bookwalkerNativeEagerCapture) {
            const copy = copySourceCrop(source, geometry.sourceRect);
            nativeCall.sourceCropPng = copy.dataUrl;
            nativeCall.sourceCropPngError = copy.error;
          }
          window.__bookwalkerNativeDrawCalls.push(nativeCall);
          if (window.__bookwalkerNativeDrawCalls.length > 100) {
            window.__bookwalkerNativeDrawCalls.shift();
          }
        }
      }
    } catch (error) {}
    return original.apply(this, args);
  };
})();
"""

_MATERIALIZE_NATIVE_SOURCE_SCRIPT = """
items => items.map(item => {
  try {
    const copy = window.__bookwalkerMaterializeNativeSourceCrop?.(item);
    return {
      dataUrl: copy?.dataUrl || null,
      error: copy ? copy.error : 'native source crop unavailable',
    };
  } catch (error) {
    return {dataUrl: null, error: String(error)};
  }
})
"""

_CAMPAIGN_TAG = re.compile(r"【[^】]*】")
_TRAILING_VOLUME = re.compile(r"^(?P<title>.+?)(?:\s*第\s*)?(?P<number>\d+)\s*巻?$")
_SERIES_COUNT = re.compile(r"[（(]\s*(\d+)\s*冊[）)]")


def clean_bookwalker_title(raw_title: str | None) -> str:
    """Remove BookWalker's campaign labels from a product title."""

    normalized = " ".join((raw_title or "").split())
    return _CAMPAIGN_TAG.sub("", normalized).strip()


def split_bookwalker_title(
    raw_title: str | None,
    *,
    series_count: int | None = None,
) -> tuple[str, str | None]:
    """Return a clean title and a BOOK_NAMING_RULES-compatible volume label."""

    cleaned = clean_bookwalker_title(raw_title)
    match = _TRAILING_VOLUME.match(cleaned)
    if not match or not match.group("title").strip():
        return cleaned, None
    title = match.group("title").strip()
    number = int(match.group("number"))
    width = 3 if number >= 100 or (series_count is not None and series_count >= 100) else 2
    return title, f"第{number:0{width}d}巻"


def is_last_page_counter(text: str) -> bool:
    """Return whether a viewer counter has reached its final page."""

    match = re.search(r"(\d+)\s*/\s*(\d+)", " ".join(text.split()))
    return bool(match and match.group(1) == match.group(2))


def _capture_from_data_url(value: object) -> CaptureResult:
    if not isinstance(value, str) or not value.startswith("data:image/png;base64,"):
        raise CaptureUnavailableError("BookWalker native source PNG is unavailable")
    try:
        data = base64.b64decode(value.split(",", 1)[1], validate=True)
        return capture_png_bytes(data)
    except (ValueError, TypeError, BinasciiError) as exc:
        raise CaptureUnavailableError(
            "BookWalker native source PNG could not be decoded"
        ) from exc


def _native_call_is_safe(call: dict[str, Any]) -> bool:
    source = call.get("source")
    if not isinstance(source, dict) or source.get("constructor") not in {
        "ImageBitmap",
        # The purchased full viewer decodes its JPEG tiles into a canvas
        # before drawing them to the renderer canvas. The same geometry,
        # transform, composition, and exact JPEG signature checks still apply.
        "HTMLCanvasElement",
    }:
        return False
    if (
        source.get("constructor") == "HTMLCanvasElement"
        and "sourceCropPng" not in call
    ):
        return False
    transform = call.get("transform")
    if not isinstance(transform, dict):
        return False
    if any(
        transform.get(key) != expected
        for key, expected in {
            "a": 1,
            "b": 0,
            "c": 0,
            "d": 1,
            "e": 0,
            "f": 0,
        }.items()
    ):
        return False
    return (
        call.get("globalCompositeOperation") == "source-over"
        and call.get("filter") == "none"
        and call.get("sourceCropPngError") in (None, "")
    )


class BookWalkerStrictEntryError(RuntimeError):
    """Raised when a strict BookWalker entry cannot be proved safe."""

    def __init__(
        self,
        *,
        strategy: AccessStrategy,
        expected_kind: ReaderControlKind,
        observed_kinds: list[ReaderControlKind],
        reason: str,
    ) -> None:
        self.strategy = strategy
        self.expected_kind = expected_kind
        self.observed_kinds = tuple(observed_kinds)
        self.reason = reason
        observed = ", ".join(
            dict.fromkeys(kind.value for kind in observed_kinds)
        ) or "none"
        super().__init__(
            "BookWalker strict entry failed: "
            f"strategy={strategy!r}, expected kind={expected_kind.value!r}, "
            f"observed kinds={observed}; reason={reason}"
        )


class BookWalkerAdapter(SiteAdapter):
    """Canvas viewer adapter for one BookWalker content ID."""

    # Use deferred source-native PNG capture followed by conservative JPEG
    # matching in production. A failed match still returns the native PNG.
    enable_original_jpeg_capture = True
    # Test-only compatibility switch for reproducing the pre-optimization
    # behavior. Production keeps deferred source-native PNG materialization.
    eager_native_source_capture = False
    page_change_timeout_ms = 14_000
    navigation_wait_timeout_ms = 5_000
    read_link_wait_timeout_ms = 5_000
    strict_entry_initial_settle_ms = 250
    strict_candidate_poll_interval_ms = 100
    strict_candidate_stability_samples = 2
    render_stable_checks = 4
    advance_retry_count = 6
    advance_retry_interval_ms = 2_000
    end_marker_grace_ms = 1_500
    spread_ratio = 1.25
    original_capture_attempts = 3
    original_capture_retry_interval_ms = 150
    original_response_task_limit = 8
    original_response_route_patterns = (
        "**://viewer-epubs*.bookwalker.jp/**",
        "**://bw-bv-epubs.bookwalker.jp/**",
    )
    _strict_scope_selectors = (
        "#js-read-check-book-cover-main-button",
        "#js-read-check",
        "#js-subscription-check",
    )
    _strict_control_selector = (
        'a, button, [role="button"], [data-action-label]'
    )

    def __init__(self) -> None:
        self._access_strategy: AccessStrategy = "auto"
        self._initial_content_id: str | None = None
        self._capture_run = 0
        self._output_title: str | None = None
        self._output_author: str | None = None
        self._output_volume: str | None = None
        self._output_genre = "小説"
        self._series_count: int | None = None
        self._final_navigation_pending = False
        self._original_candidates = OriginalJpegCache()
        self._original_response_tasks: set[asyncio.Task[None]] = set()
        self._original_response_sequence = 0
        self._original_response_page: Page | None = None
        self._original_capture_decisions: dict[
            tuple[tuple[int | None, int | None, str], ...],
            tuple[str, ...] | None,
        ] = {}

    async def configure_run(
        self, page: Page, access_strategy: AccessStrategy
    ) -> None:
        """Store BookWalker's access intent before the runner navigates."""

        del page
        if access_strategy not in {"auto", "direct", "quota"}:
            raise UnsupportedAccessStrategyError(
                f"BookWalkerAdapter does not support "
                f"access_strategy={access_strategy!r}"
            )
        self._access_strategy = access_strategy

    async def login(
        self,
        page: Page,
        *,
        email: str,
        password: str,
        home_url: str = "https://bookwalker.jp/",
    ) -> None:
        """Run the site-specific login flow on an existing browser page."""

        await login_bookwalker(page, email=email, password=password, home_url=home_url)

    @staticmethod
    def content_id_from_url(url: str) -> str | None:
        parsed = urlparse(url)
        values = parse_qs(parsed.query).get("cid", [])
        if values:
            return values[0]

        # Product pages use /de<content-id>/ while the viewer uses ?cid=.
        match = re.search(
            r"/de([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:/|$)",
            parsed.path,
            re.IGNORECASE,
        )
        return match.group(1) if match else None

    @staticmethod
    def parse_page_counter(text: str) -> tuple[int | None, str | None]:
        normalized = " ".join(text.split())
        if not normalized:
            return None, None
        match = re.search(r"\d+", normalized)
        return (int(match.group(0)), normalized) if match else (None, normalized)

    @staticmethod
    def score_read_link(candidate: dict[str, str | None], content_id: str | None) -> int:
        """Rank product-page links that can enter a reader.

        BookWalker changes the action label depending on ownership and
        subscription status. The product content ID and reader URL are
        stronger signals than DOM order, which may put the trial link first.
        """

        text = (candidate.get("text") or "").strip()
        action = (candidate.get("action") or "").strip().lower()
        href = (candidate.get("href") or "").lower()
        uuid = candidate.get("uuid")
        score = 0

        if content_id and uuid == content_id:
            score += 100
        if "viewer" in href:
            score += 100
        if action and action != "trial_reading" and any(
            token in action for token in ("read", "reading", "subscription")
        ):
            score += 80
        if "10\u5206" in text or "\u307e\u308b\u8aad\u307f" in text:
            score += 80
        elif "\u8aad\u3080" in text or "\u8aad\u307f" in text:
            score += 50
        if "10分" in text or "まる読み" in text:
            score += 80
        elif "読む" in text or "読み" in text:
            score += 50
        if action == "trial_reading":
            score += 10
        if "sample=1" in href:
            score += 5
        if action == "more_read":
            score -= 100
        return score

    @staticmethod
    def is_read_link_candidate(candidate: dict[str, str | None]) -> bool:
        """Return whether a product-page anchor can enter a reader."""
        return is_reader_control_candidate(candidate)

    async def _visible(self, locator: Locator) -> bool:
        try:
            return await asyncio.wait_for(locator.is_visible(timeout=500), timeout=1)
        except PlaywrightTimeoutError:
            return False
        except TimeoutError:
            return False

    async def _renderer_ready(self, page: Page) -> bool:
        return await self._visible_canvas(page) is not None

    async def _visible_canvas(self, page: Page) -> Locator | None:
        renderer = page.locator("#renderer")
        if not await self._visible(renderer):
            return None

        current = page.locator("#renderer .currentScreen canvas:not(.dummy)")
        candidates = current if await current.count() else page.locator(
            "#renderer canvas:not(.dummy)"
        )
        for index in range(await candidates.count()):
            canvas = candidates.nth(index)
            try:
                box = await asyncio.wait_for(canvas.bounding_box(), timeout=1)
                size = await asyncio.wait_for(
                    canvas.evaluate("element => ({width: element.width, height: element.height})"),
                    timeout=1,
                )
            except (PlaywrightTimeoutError, TimeoutError):
                continue
            if (
                await self._visible(canvas)
                and box
                and box["width"] > 0
                and box["height"] > 0
                and size["width"] > 0
                and size["height"] > 0
            ):
                return canvas
        return None

    async def _canvas_signature(self, page: Page) -> tuple[int, int] | None:
        canvas = await self._visible_canvas(page)
        if canvas is None:
            return None
        try:
            return await asyncio.wait_for(
                canvas.evaluate(
                    """
                    element => {
                      const probe = document.createElement('canvas');
                      probe.width = 64;
                      probe.height = 64;
                      const probeContext = probe.getContext('2d');
                      if (!probeContext) return [0, 0];
                      probeContext.drawImage(element, 0, 0, 64, 64);
                      const sample = probeContext.getImageData(0, 0, 64, 64).data;
                      let nonWhite = 0;
                      let checksum = 0;
                      for (let offset = 0; offset < sample.length; offset += 4) {
                        checksum = (checksum * 31 + sample[offset]) >>> 0;
                        checksum = (checksum * 31 + sample[offset + 1]) >>> 0;
                        checksum = (checksum * 31 + sample[offset + 2]) >>> 0;
                        checksum = (checksum * 31 + sample[offset + 3]) >>> 0;
                        if (
                          sample[offset] < 245 ||
                          sample[offset + 1] < 245 ||
                          sample[offset + 2] < 245 ||
                          sample[offset + 3] < 245
                        ) {
                          nonWhite += 1;
                        }
                      }
                      return [checksum, nonWhite];
                    }
                    """
                ),
                timeout=2,
            )
        except (PlaywrightTimeoutError, TimeoutError):
            return None

    async def _has_viewer_shell(self, page: Page) -> bool:
        for selector in ("#viewer", "#renderer"):
            try:
                if await asyncio.wait_for(page.locator(selector).count(), timeout=1):
                    return True
            except TimeoutError:
                continue
        return False

    async def _wait_for_render_ready(self, page: Page) -> None:
        """Wait for the gray loading overlay to disappear and stay gone."""

        elapsed_ms = 0
        stable_checks = 0
        previous_signature: tuple[int, int] | None = None
        while elapsed_ms < self.page_change_timeout_ms:
            loading = await self._visible(page.locator("#loaderStatusDialog"))
            ready = await self._renderer_ready(page)
            if not loading and ready:
                signature = await self._canvas_signature(page)
                if (
                    signature is not None
                    and signature[1] > 0
                    and signature == previous_signature
                ):
                    stable_checks += 1
                else:
                    stable_checks = 0
                previous_signature = signature
                if stable_checks >= self.render_stable_checks:
                    return
            else:
                stable_checks = 0
                previous_signature = None
            await page.wait_for_timeout(100)
            elapsed_ms += 100
        raise PageChangeTimeoutError(
            "BookWalker viewer did not finish loading within the timeout"
        )

    async def _last_page_end_marker_visible(self, page: Page) -> bool:
        """Give the viewer time to expose END after rendering its logo screen."""

        counter = page.locator("#pageSliderCounter")
        if not await counter.count():
            return False
        try:
            raw_counter = await asyncio.wait_for(counter.inner_text(timeout=1000), timeout=1)
        except (PlaywrightTimeoutError, TimeoutError):
            return False
        if not is_last_page_counter(raw_counter):
            return False

        elapsed_ms = 0
        while elapsed_ms < self.end_marker_grace_ms:
            if await self._visible(page.locator("#endOfBook")):
                return True
            await page.wait_for_timeout(100)
            elapsed_ms += 100
        return await self._visible(page.locator("#endOfBook"))

    async def _is_last_page_counter(self, page: Page) -> bool:
        counter = page.locator("#pageSliderCounter")
        if not await counter.count():
            return False
        try:
            raw_counter = await asyncio.wait_for(counter.inner_text(timeout=1000), timeout=1)
        except (PlaywrightTimeoutError, TimeoutError):
            return False
        return is_last_page_counter(raw_counter)

    async def _find_read_link(self, page: Page) -> Locator | None:
        elapsed_ms = 0
        deferred_trial: Locator | None = None
        while elapsed_ms < self.read_link_wait_timeout_ms:
            best_link: Locator | None = None
            best_score = -1
            # These containers identify the product's own reading controls.
            # Some product variants render the control as a button, or attach
            # its destination through JavaScript instead of an href.
            for selector in (
                (
                    '#js-read-check a, #js-read-check button, '
                    '#js-read-check [role="button"], #js-read-check [data-action-label]'
                ),
                (
                    '#js-subscription-check a, #js-subscription-check button, '
                    '#js-subscription-check [role="button"], '
                    '#js-subscription-check [data-action-label]'
                ),
            ):
                locator = page.locator(selector)
                try:
                    count = await asyncio.wait_for(locator.count(), timeout=1)
                except TimeoutError:
                    continue
                for index in range(count):
                    candidate = locator.nth(index)
                    if not await self._visible(candidate):
                        continue
                    try:
                        metadata = await asyncio.wait_for(
                            candidate.evaluate(
                                """
                                element => ({
                                  text: element.innerText ||
                                    element.getAttribute('aria-label') ||
                                    element.getAttribute('title') || '',
                                  action: element.getAttribute('data-action-label'),
                                  href: element.href ||
                                    element.getAttribute('data-href') ||
                                    element.getAttribute('data-url') || '',
                                  uuid: element.getAttribute('data-uuid')
                                })
                                """
                            ),
                            timeout=1,
                        )
                    except (PlaywrightTimeoutError, TimeoutError):
                        continue
                    if not self.is_read_link_candidate(metadata):
                        continue
                    score = self.score_read_link(metadata, self._initial_content_id)
                    if score > best_score:
                        best_link = candidate
                        best_score = score
            if best_link is not None:
                # Give stronger owned/subscription links a short opportunity
                # to appear after the initial product-page DOM is rendered.
                # Trial is a safe fallback, but must not win merely by arriving
                # earlier than the real reading control.
                if best_score >= 180:
                    return best_link
                deferred_trial = best_link

            # Fallbacks cover product-page variants that omit the standard
            # containers or use a direct viewer URL.
            selectors = (
                'a[href*="viewer.bookwalker.jp"]',
                'a[data-action-label="reading"]',
                'a[data-action-label="read"]',
                'a[data-action-label="trial_reading"]',
                'a[data-action-label="read_maruyomi"]',
                'button[data-action-label="reading"]',
                'button[data-action-label="read"]',
                'button[data-action-label="trial_reading"]',
                'button[data-action-label="read_maruyomi"]',
            )
            for selector in selectors:
                locator = page.locator(selector)
                try:
                    count = await asyncio.wait_for(locator.count(), timeout=1)
                except TimeoutError:
                    continue
                for index in range(count):
                    candidate = locator.nth(index)
                    if await self._visible(candidate):
                        if selector.endswith('"trial_reading"]') and elapsed_ms < 800:
                            continue
                        return candidate
            await page.wait_for_timeout(100)
            elapsed_ms += 100
        return deferred_trial

    async def _reader_control_metadata(
        self, candidate: Locator
    ) -> dict[str, str | None]:
        return await asyncio.wait_for(
            candidate.evaluate(
                """
                element => ({
                  text: element.innerText ||
                    element.getAttribute('aria-label') ||
                    element.getAttribute('title') || '',
                  action: element.getAttribute('data-action-label'),
                  href: element.href ||
                    element.getAttribute('data-href') ||
                    element.getAttribute('data-url') || '',
                  uuid: element.getAttribute('data-uuid')
                })
                """
            ),
            timeout=1,
        )

    async def _dom_identity(self, candidate: Locator) -> str:
        """Return a non-mutating identity for one DOM element."""

        return await asyncio.wait_for(
            candidate.evaluate(
                """
                element => {
                  const parts = [];
                  let current = element;
                  while (current && current.nodeType === Node.ELEMENT_NODE) {
                    let index = 0;
                    for (let sibling = current; sibling; sibling = sibling.previousElementSibling) {
                      index += 1;
                    }
                    parts.unshift(`${current.tagName}:${index}`);
                    current = current.parentElement;
                  }
                  return parts.join('/');
                }
                """
            ),
            timeout=1,
        )

    async def _is_control_element(self, candidate: Locator) -> bool:
        return await asyncio.wait_for(
            candidate.evaluate(
                """
                element => element.matches(
                  'a, button, [role="button"], [data-action-label]'
                )
                """
            ),
            timeout=1,
        )

    async def _strict_control_candidates(
        self, page: Page, expected_kind: ReaderControlKind
    ) -> tuple[
        list[tuple[Locator, dict[str, str | None], str]],
        list[ReaderControlKind],
    ]:
        """Collect exact-kind controls from the product's own action scopes."""

        matches: list[tuple[Locator, dict[str, str | None], str]] = []
        observed: list[ReaderControlKind] = []
        seen_elements: set[str] = set()
        for scope_selector in self._strict_scope_selectors:
            scope = page.locator(scope_selector)
            try:
                scope_count = await asyncio.wait_for(scope.count(), timeout=1)
            except (PlaywrightTimeoutError, TimeoutError):
                continue
            for scope_index in range(scope_count):
                scope_element = scope.nth(scope_index)
                controls = scope_element.locator(self._strict_control_selector)
                candidates: list[Locator] = []
                try:
                    if await self._is_control_element(scope_element):
                        candidates.append(scope_element)
                except (PlaywrightTimeoutError, TimeoutError):
                    pass
                try:
                    control_count = await asyncio.wait_for(controls.count(), timeout=1)
                except (PlaywrightTimeoutError, TimeoutError):
                    control_count = 0
                candidates.extend(controls.nth(index) for index in range(control_count))
                for candidate in candidates:
                    try:
                        if not await self._visible(candidate):
                            continue
                        identity = await self._dom_identity(candidate)
                        if identity in seen_elements:
                            continue
                        seen_elements.add(identity)
                        metadata = await self._reader_control_metadata(candidate)
                    except (PlaywrightTimeoutError, TimeoutError):
                        continue

                    kind = classify_reader_control(metadata)
                    observed.append(kind)
                    uuid = (metadata.get("uuid") or "").strip()
                    if (
                        uuid
                        and (
                            self._initial_content_id is None
                            or uuid.casefold() != self._initial_content_id.casefold()
                        )
                    ):
                        continue
                    if kind is expected_kind:
                        matches.append((candidate, metadata, identity))
        return matches, observed

    @staticmethod
    def _strict_candidate_signature(
        metadata: dict[str, str | None], identity: str
    ) -> tuple[str, ...]:
        """Return the stable, in-browser identity used for strict entry."""

        return (
            identity,
            metadata.get("action") or "",
            metadata.get("text") or "",
            metadata.get("href") or "",
            metadata.get("uuid") or "",
        )

    def _strict_entry_error(
        self,
        *,
        expected_kind: ReaderControlKind,
        observed: list[ReaderControlKind],
        reason: str,
    ) -> BookWalkerStrictEntryError:
        return BookWalkerStrictEntryError(
            strategy=self._access_strategy,
            expected_kind=expected_kind,
            observed_kinds=observed,
            reason=reason,
        )

    def _strict_expected_kind(self) -> ReaderControlKind:
        return (
            ReaderControlKind.OWNED
            if self._access_strategy == "direct"
            else ReaderControlKind.MARUYOMI
        )

    async def _find_strict_read_link(
        self, page: Page, expected_kind: ReaderControlKind
    ) -> Locator:
        elapsed_ms = 0
        observed: list[ReaderControlKind] = []
        stable_signature: tuple[str, ...] | None = None
        stable_samples = 0
        last_matches: list[tuple[Locator, dict[str, str | None], str]] = []

        # The product page can briefly contain both the old and new control
        # while its access action scope is being replaced.  Keep this settle
        # bounded by the existing timeout and leave enough time for at least
        # one candidate observation in short unit-test timeouts.
        initial_settle_ms = min(
            self.strict_entry_initial_settle_ms,
            max(0, self.read_link_wait_timeout_ms - self.strict_candidate_poll_interval_ms),
        )
        if initial_settle_ms:
            await page.wait_for_timeout(initial_settle_ms)
            elapsed_ms += initial_settle_ms

        while elapsed_ms < self.read_link_wait_timeout_ms:
            matches, observed = await self._strict_control_candidates(page, expected_kind)
            if len(matches) == 1:
                candidate, metadata, identity = matches[0]
                signature = self._strict_candidate_signature(metadata, identity)
                if signature == stable_signature:
                    stable_samples += 1
                else:
                    stable_signature = signature
                    stable_samples = 1
                last_matches = matches
                if stable_samples >= self.strict_candidate_stability_samples:
                    return candidate
            else:
                # Zero candidates and transient ambiguity both invalidate the
                # previous sample.  A persistent ambiguity therefore remains
                # fail-safe, but no longer fails on the first DOM snapshot.
                stable_signature = None
                stable_samples = 0
                last_matches = matches

            remaining_ms = self.read_link_wait_timeout_ms - elapsed_ms
            if remaining_ms <= 0:
                break
            wait_ms = min(self.strict_candidate_poll_interval_ms, remaining_ms)
            await page.wait_for_timeout(wait_ms)
            elapsed_ms += wait_ms

        reason = "no matching control was observed before timeout"
        if len(last_matches) > 1 or any(
            kind is expected_kind for kind in observed
        ):
            reason = "matching control was not stably unique before timeout"
        elif observed and all(kind is ReaderControlKind.UNKNOWN for kind in observed):
            reason = "visible controls are unsupported or unknown"
        raise self._strict_entry_error(
            expected_kind=expected_kind,
            observed=observed,
            reason=reason,
        )

    async def _wait_for_url_change(self, page: Page, previous_url: str) -> None:
        elapsed_ms = 0
        while elapsed_ms < self.navigation_wait_timeout_ms:
            if page.url != previous_url:
                return
            await page.wait_for_timeout(100)
            elapsed_ms += 100
        raise PageChangeTimeoutError(
            "BookWalker read button did not navigate to a viewer"
        )

    async def _open_reader_from_product(self, page: Page) -> None:
        link = await self._find_read_link(page)
        if link is None:
            raise LookupError(
                "BookWalker read button was not found on the product page"
            )

        await self._activate_reader_control(page, link)

    async def _activate_reader_control(self, page: Page, link: Locator) -> None:
        previous_url = page.url
        # Product pages may mark the read link target=_blank. Remove only that
        # presentation detail so the existing Runner Page follows the click.
        # The click itself remains a normal user-facing link activation.
        try:
            await asyncio.wait_for(
                link.evaluate("element => element.removeAttribute('target')"),
                timeout=1,
            )
            # Some BookWalker links schedule navigation in a script and keep
            # the click promise pending while the new document is loading.
            # The adapter has its own bounded URL-change wait below, so do not
            # make Playwright wait for scheduled navigations here.
            await link.click(force=True, timeout=3_000, no_wait_after=True)
        except (PlaywrightTimeoutError, TimeoutError) as exc:
            raise PageChangeTimeoutError(
                "BookWalker read button could not be activated"
            ) from exc
        await self._wait_for_url_change(page, previous_url)

    async def _open_strict_reader_from_product(self, page: Page) -> None:
        expected_kind = self._strict_expected_kind()
        link = await self._find_strict_read_link(page, expected_kind)
        await self._activate_reader_control(page, link)
        viewer_content_id = self.content_id_from_url(page.url)
        if (
            self._initial_content_id is not None
            and viewer_content_id is not None
            and viewer_content_id.casefold() != self._initial_content_id.casefold()
        ):
            raise self._strict_entry_error(
                expected_kind=expected_kind,
                observed=[expected_kind],
                reason=(
                    "viewer content id does not match product content id "
                    f"({viewer_content_id!r})"
                ),
            )

    async def _collect_product_metadata(self, page: Page) -> None:
        """Read title/author/volume before the product page becomes the viewer."""

        current_id = self._initial_content_id
        data = await page.evaluate(
            r"""
            currentId => {
              const mainTitle = document.querySelector(
                'h1.t-c-product-main-data__title'
              );
              const authorBlock = document.querySelector(
                '.t-c-product-main-data__authors'
              );
              const authorLinks = authorBlock
                ? [...authorBlock.querySelectorAll('a')].map(a => (a.innerText || '').trim())
                : [];
              const category = [...document.querySelectorAll('dt')].find(dt =>
                (dt.innerText || '').trim() === 'カテゴリ'
              )?.nextElementSibling?.innerText || '';
              const seriesHeading = [...document.querySelectorAll('#js-scroll-series h2')]
                .map(element => element.innerText || '')
                .find(text => text.includes('シリーズ一覧')) || '';
              const seriesCountMatch = seriesHeading.match(/[（(]\s*(\d+)\s*冊[）)]/);
              let seriesTitle = '';
              for (const card of document.querySelectorAll('#js-series-list article')) {
                const hrefs = [...card.querySelectorAll('a[href]')].map(a => a.href);
                const productPath = currentId ? `/de${currentId}/` : '';
                if (productPath && hrefs.some(href => {
                  try {
                    const url = new URL(href);
                    return url.hostname === 'bookwalker.jp' &&
                      url.pathname.toLowerCase() === productPath.toLowerCase();
                  } catch (error) {
                    return false;
                  }
                })) {
                  seriesTitle = card.querySelector('h3')?.innerText || '';
                  break;
                }
              }
              return {
                main_title: mainTitle?.innerText || '',
                author_text: authorBlock?.innerText || '',
                author_links: authorLinks,
                category,
                series_title: seriesTitle,
                series_count: seriesCountMatch ? Number(seriesCountMatch[1]) : null,
              };
            }
            """,
            current_id,
        )
        raw_title = data.get("series_title") or data.get("main_title") or ""
        series_count = data.get("series_count")
        self._series_count = int(series_count) if series_count is not None else None
        self._output_title, self._output_volume = split_bookwalker_title(
            raw_title,
            series_count=self._series_count,
        )

        author_text = " ".join(str(data.get("author_text") or "").split())
        role_boundary = re.search(r"\s+(?:イラスト|原作|作画|漫画|訳|監修)", author_text)
        author_part = author_text[: role_boundary.start()] if role_boundary else author_text
        author_part = re.sub(r"^著\s*", "", author_part).strip()
        link_names = [
            "".join(str(name).split())
            for name in data.get("author_links", [])
            if str(name).strip() and str(name).replace(" ", "") in author_part.replace(" ", "")
        ]
        if link_names:
            self._output_author = "・".join(dict.fromkeys(link_names))
        else:
            self._output_author = author_part.replace(" ", "") or None

        category = str(data.get("category") or "")
        if "マンガ" in category:
            self._output_genre = "漫画"
        elif "技術" in category:
            self._output_genre = "技術書"
        elif "雑誌" in category:
            self._output_genre = "雑誌"
        else:
            self._output_genre = "小説"

    async def _remember_viewer_title(self, page: Page) -> None:
        if self._output_title:
            return
        title_locator = page.locator("#pagetitle")
        if await title_locator.count():
            try:
                raw_title = (
                    await asyncio.wait_for(title_locator.inner_text(timeout=1000), timeout=1)
                ).strip()
            except (PlaywrightTimeoutError, TimeoutError):
                raw_title = ""
            self._output_title, self._output_volume = split_bookwalker_title(
                raw_title,
                series_count=self._series_count,
            )

    async def initialize(self, page: Page) -> None:
        self._initial_content_id = self.content_id_from_url(page.url)
        has_viewer_shell = await self._has_viewer_shell(page)
        parsed = urlparse(page.url)
        is_product_page = parsed.netloc.lower() in {
            "bookwalker.jp",
            "www.bookwalker.jp",
        } and bool(re.match(r"^/de[0-9a-f-]+/?$", parsed.path, re.IGNORECASE))
        is_viewer_url = parsed.netloc.lower() == "viewer.bookwalker.jp"

        if self._access_strategy != "auto" and (has_viewer_shell or is_viewer_url):
            raise self._strict_entry_error(
                expected_kind=self._strict_expected_kind(),
                observed=[],
                reason="strict entry requires a product page, but the run is already in a viewer",
            )

        if (
            self._access_strategy != "auto"
            and is_product_page
            and self._initial_content_id is None
        ):
            raise self._strict_entry_error(
                expected_kind=self._strict_expected_kind(),
                observed=[],
                reason=(
                    "product identity/content UUID could not be determined "
                    "from the product URL"
                ),
            )

        if not has_viewer_shell and is_product_page:
            await self._collect_product_metadata(page)
            if self._access_strategy == "auto":
                await self._open_reader_from_product(page)
            else:
                await self._open_strict_reader_from_product(page)
            self._initial_content_id = self.content_id_from_url(page.url)
        elif self._access_strategy != "auto":
            raise self._strict_entry_error(
                expected_kind=self._strict_expected_kind(),
                observed=[],
                reason="strict entry requires a BookWalker product page",
            )

        await self._wait_for_render_ready(page)
        await self._remember_viewer_title(page)

    def get_output_metadata(self) -> dict[str, str | None]:
        return {
            "title": self._output_title,
            "author": self._output_author,
            "volume": self._output_volume,
            "genre": self._output_genre,
        }

    async def prepare_page(self, page: Page) -> None:
        await page.add_init_script(_DRAW_TRACE_SCRIPT)
        await page.add_init_script(
            "window.__bookwalkerNativeEagerCapture = "
            f"{str(self.eager_native_source_capture).lower()} || "
            "location.hostname === 'viewer.bookwalker.jp';"
        )
        if not self.enable_original_jpeg_capture:
            return
        for task in tuple(self._original_response_tasks):
            task.cancel()
        if self._original_response_tasks:
            await asyncio.gather(
                *self._original_response_tasks,
                return_exceptions=True,
            )
        self._original_response_tasks.clear()
        self._original_candidates.clear()
        self._original_response_sequence = 0
        self._original_capture_decisions.clear()
        if self._original_response_page is not None and self._original_response_page is not page:
            try:
                self._original_response_page.remove_listener(
                    "response", self._handle_original_response
                )
            except (PlaywrightError, AttributeError):
                pass
            try:
                for pattern in self.original_response_route_patterns:
                    await self._original_response_page.unroute(
                        pattern,
                        self._handle_original_route,
                    )
            except (PlaywrightError, AttributeError):
                pass
        if self._original_response_page is not page:
            page.on("response", self._handle_original_response)
            for pattern in self.original_response_route_patterns:
                await page.route(pattern, self._handle_original_route)
            self._original_response_page = page

    @staticmethod
    def _is_original_response(response: object) -> bool:
        """Limit body observation to BookWalker's page-image response host."""

        url = str(getattr(response, "url", ""))
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        is_trial_or_free_epub = (
            host.startswith("viewer-epubs") and host.endswith(".bookwalker.jp")
        )
        is_purchased_epub = host == "bw-bv-epubs.bookwalker.jp"
        if not (is_trial_or_free_epub or is_purchased_epub):
            return False
        request = getattr(response, "request", None)
        resource_type = getattr(request, "resource_type", None)
        if resource_type not in {None, "", "xhr", "fetch", "image"}:
            return False
        try:
            headers = getattr(response, "headers", {}) or {}
            content_type = str(headers.get("content-type", "")).split(";", 1)[0].lower()
        except Exception:  # noqa: BLE001 - a response without headers is ignorable
            content_type = ""
        path = parsed.path.lower()
        return content_type == "image/jpeg" or "jpeg" in path or path.endswith(
            (".jpg", ".jpe")
        )

    def _handle_original_response(self, response: object) -> None:
        if not self._is_original_response(response):
            return
        if len(self._original_response_tasks) >= self.original_response_task_limit:
            return
        task = asyncio.create_task(self._read_original_response(response))
        self._original_response_tasks.add(task)
        task.add_done_callback(self._original_response_tasks.discard)

    async def _handle_original_route(self, route: object) -> None:
        """Read eligible response bodies while fulfilling the same response."""

        try:
            response = await route.fetch()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - allow the browser's normal request path
            try:
                await route.continue_()  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                return
            return

        try:
            if self._is_original_response(response):
                body = await response.body()
                self._store_original_response_body(response, body)
            await route.fulfill(response=response)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - body capture must not break the viewer
            try:
                await route.fulfill(response=response)  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                try:
                    await route.continue_()  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001
                    return

    async def _read_original_response(self, response: object) -> None:
        try:
            status = int(getattr(response, "status", 200))
            if status < 200 or status >= 300:
                return
            headers = getattr(response, "headers", {}) or {}
            content_length = headers.get("content-length")
            if content_length is not None:
                try:
                    if int(content_length) > MAX_RESPONSE_BODY_BYTES:
                        return
                except (TypeError, ValueError):
                    pass
            body = await response.body()  # type: ignore[attr-defined]
            self._store_original_response_body(response, body)
        except Exception:  # noqa: BLE001 - body failure must use native fallback
            return

    def _store_original_response_body(self, response: object, body: object) -> None:
        if not isinstance(body, bytes) or len(body) > MAX_RESPONSE_BODY_BYTES:
            return
        self._original_response_sequence += 1
        candidate = candidate_from_jpeg(
            body,
            url=str(getattr(response, "url", "")),
            sequence=self._original_response_sequence,
        )
        if candidate is not None:
            self._original_candidates.add(candidate)

    async def _wait_for_original_retry(self, page: Page) -> None:
        try:
            await page.wait_for_timeout(self.original_capture_retry_interval_ms)
        except Exception:  # noqa: BLE001 - test doubles may not expose wait_for_timeout
            await asyncio.sleep(self.original_capture_retry_interval_ms / 1000)

    async def _capture_original_jpegs(
        self,
        page: Page,
        native_captures: tuple[CaptureResult, ...],
    ) -> tuple[CaptureResult, ...] | None:
        """Return JPEGs only when every visible native part matches uniquely."""

        try:
            native_signatures = tuple(
                [
                    await image_signature(page, capture.data, "image/png")
                    for capture in native_captures
                ]
            )
            if any(signature is None for signature in native_signatures):
                return None

            decision_key = tuple(
                (capture.width, capture.height, signature)
                for capture, signature in zip(
                    native_captures, native_signatures, strict=True
                )
                if signature is not None
            )
            if len(decision_key) != len(native_captures):
                return None
            if decision_key in self._original_capture_decisions:
                selected_hashes = self._original_capture_decisions[decision_key]
                if selected_hashes is None:
                    return None
                by_hash = {
                    candidate.sha256: candidate
                    for candidate in self._original_candidates.values()
                }
                selected = [by_hash.get(sha256) for sha256 in selected_hashes]
                if any(candidate is None for candidate in selected):
                    return None
                resolved = tuple(
                    candidate for candidate in selected if candidate is not None
                )
                if len(resolved) != len(selected):
                    return None
                return tuple(candidate_capture(candidate) for candidate in resolved)

            for attempt in range(self.original_capture_attempts):
                candidates = self._original_candidates.values()
                selected = []
                for capture, native_signature in zip(
                    native_captures, native_signatures, strict=True
                ):
                    matches = []
                    for candidate in candidates:
                        if (candidate.width, candidate.height) != (
                            capture.width,
                            capture.height,
                        ):
                            continue
                        if candidate.signature is None:
                            candidate.signature = await image_signature(
                                page, candidate.data, candidate.mime_type
                            )
                        if candidate.signature == native_signature:
                            matches.append(candidate)
                    if len(matches) != 1:
                        selected = []
                        break
                    selected.append(matches[0])

                if selected and len({candidate.sha256 for candidate in selected}) == len(
                    selected
                ):
                    self._original_capture_decisions[decision_key] = tuple(
                        candidate.sha256 for candidate in selected
                    )
                    return tuple(candidate_capture(candidate) for candidate in selected)
                if attempt < self.original_capture_attempts - 1:
                    await self._wait_for_original_retry(page)
            self._original_capture_decisions[decision_key] = None
        except Exception:  # noqa: BLE001 - original capture is an optimization
            return None
        return None

    async def _clear_native_capture(self, page: Page) -> None:
        try:
            await page.evaluate(
                """
                () => {
                  window.__bookwalkerNativeCaptureEnabled = false;
                  window.__bookwalkerNativeDrawCalls = [];
                  window.__bookwalkerNativeSourceObjects?.clear();
                }
                """
            )
        except (PlaywrightError, PlaywrightTimeoutError, TimeoutError):
            return

    async def _clear_geometry_trace(self, page: Page) -> None:
        try:
            await page.evaluate("window.__bookwalkerDrawCalls = []")
        except (PlaywrightError, PlaywrightTimeoutError, TimeoutError):
            return

    async def _arm_native_capture(self, page: Page) -> None:
        try:
            await page.evaluate(
                """
                () => {
                  window.__bookwalkerNativeDrawCalls = [];
                  window.__bookwalkerNativeSourceObjects?.clear();
                  window.__bookwalkerNativeCaptureEnabled = true;
                }
                """
            )
        except (PlaywrightError, PlaywrightTimeoutError, TimeoutError):
            return

    async def _materialize_native_source_crops(
        self,
        page: Page,
        selected: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        payload = [
            {
                "sourceId": call.get("sourceId"),
                "sourceRect": call.get("sourceRect"),
            }
            for call in selected
        ]
        results = await page.evaluate(
            _MATERIALIZE_NATIVE_SOURCE_SCRIPT,
            payload,
        )
        if not isinstance(results, list) or len(results) != len(selected):
            raise CaptureUnavailableError(
                "BookWalker native source crop materialization failed"
            )
        materialized: list[dict[str, Any]] = []
        for call, result in zip(selected, results, strict=True):
            if not isinstance(result, dict):
                raise CaptureUnavailableError(
                    "BookWalker native source crop result is invalid"
                )
            enriched = dict(call)
            enriched["sourceCropPng"] = result.get("dataUrl")
            enriched["sourceCropPngError"] = result.get("error")
            materialized.append(enriched)
        return materialized

    async def capture_page(self, page: Page) -> tuple[CaptureResult, ...] | None:
        """Prefer native source crops and return None for the legacy fallback."""

        try:
            canvas = await self.get_capture_target(page)
            trace_id = await canvas.get_attribute("data-bookwalker-trace-id")
            if not trace_id:
                raise CaptureUnavailableError("BookWalker canvas trace id is missing")
            size = await canvas.evaluate(
                "element => ({width: element.width, height: element.height})"
            )
            width = int(size["width"])
            height = int(size["height"])
            boxes = await self._page_draw_rectangles(page, canvas)
            if not boxes:
                raise CaptureUnavailableError(
                    "BookWalker native capture requires draw geometry"
                )
            if len(boxes) > 1 and await self._is_first_page(page):
                raise CaptureUnavailableError(
                    "BookWalker cover spread needs one fallback union crop"
                )
            draw_calls = await page.evaluate(
                """
                traceId => (window.__bookwalkerNativeDrawCalls || [])
                  .filter(call => call.canvasId === traceId)
                """,
                trace_id,
            )
            selected = select_native_draw_calls(
                draw_calls,
                canvas_id=trace_id,
                canvas_width=width,
                canvas_height=height,
                boxes=boxes,
            )
            if selected is None or len(selected) != len(boxes):
                raise CaptureUnavailableError(
                    "BookWalker native source calls did not match page geometry"
                )
            if any("sourceCropPng" not in call for call in selected):
                if any(
                    isinstance(call.get("source"), dict)
                    and call["source"].get("constructor") == "HTMLCanvasElement"
                    for call in selected
                ):
                    raise CaptureUnavailableError(
                        "BookWalker mutable canvas source requires eager crops"
                    )
                selected = await self._materialize_native_source_crops(page, selected)

            captures: list[CaptureResult] = []
            for call in selected:
                if not _native_call_is_safe(call):
                    raise CaptureUnavailableError(
                        "BookWalker native source uses unsupported composition"
                    )
                source_rect = call.get("sourceRect")
                if not isinstance(source_rect, dict):
                    raise CaptureUnavailableError(
                        "BookWalker native source rectangle is missing"
                    )
                try:
                    source = call["source"]
                    source_width = float(source["width"])
                    source_height = float(source["height"])
                    source_x = float(source_rect["x"])
                    source_y = float(source_rect["y"])
                    expected_width = round(float(source_rect["width"]))
                    expected_height = round(float(source_rect["height"]))
                except (KeyError, TypeError, ValueError) as exc:
                    raise CaptureUnavailableError(
                        "BookWalker native source rectangle is invalid"
                    ) from exc
                if (
                    source_width <= 0
                    or source_height <= 0
                    or source_x < 0
                    or source_y < 0
                    or expected_width <= 0
                    or expected_height <= 0
                    or source_x + expected_width > source_width
                    or source_y + expected_height > source_height
                ):
                    raise CaptureUnavailableError(
                        "BookWalker native source rectangle is out of bounds"
                    )
                capture = _capture_from_data_url(call.get("sourceCropPng"))
                if (capture.width, capture.height) != (expected_width, expected_height):
                    raise CaptureUnavailableError(
                        "BookWalker native PNG dimensions do not match source rectangle"
                    )
                captures.append(capture)
            if not self.enable_original_jpeg_capture:
                await self._clear_geometry_trace(page)
                return tuple(captures)
            native_captures = tuple(captures)
            original_captures = await self._capture_original_jpegs(
                page, native_captures
            )
            await self._clear_geometry_trace(page)
            return original_captures or native_captures
        except CaptureUnavailableError:
            return None
        except (
            BinasciiError,
            KeyError,
            LookupError,
            PlaywrightError,
            PlaywrightTimeoutError,
            TimeoutError,
            TypeError,
            ValueError,
        ):
            return None
        finally:
            await self._clear_native_capture(page)

    async def detect_state(self, page: Page) -> PageState:
        current_content_id = self.content_id_from_url(page.url)
        if (
            self._initial_content_id is not None
            and current_content_id is not None
            and current_content_id != self._initial_content_id
        ):
            return PageState.NEXT_CONTENT

        if await self._visible(page.locator("#eobNext")):
            return PageState.NEXT_CONTENT
        # Some readers render a BookWalker logo canvas after the final page
        # while keeping the page counter at N/N. Once the runner has already
        # sent the next-page action from N/N, that following screen must never
        # be captured as content, even when #endOfBook is absent.
        if self._final_navigation_pending and await self._is_last_page_counter(page):
            return PageState.END
        if await self._visible(page.locator("[data-ad], .ad, #ad, #advertisement")):
            return PageState.AD
        if await self._visible(page.locator("#endOfBook")):
            return PageState.END
        if await self._visible(page.locator("#loaderStatusDialog")):
            return PageState.LOADING
        if await self._renderer_ready(page):
            if await self._last_page_end_marker_visible(page):
                return PageState.END
            return PageState.CONTENT
        return PageState.UNKNOWN

    async def get_capture_target(self, page: Page) -> Locator:
        target = await self._visible_canvas(page)
        if target is None:
            raise LookupError("BookWalker content canvas is not visible")
        return target

    async def _page_draw_rectangles(
        self,
        page: Page,
        canvas: Locator,
    ) -> list[dict[str, int]]:
        trace_id = await canvas.get_attribute("data-bookwalker-trace-id")
        if not trace_id:
            return []
        size = await canvas.evaluate(
            "element => ({width: element.width, height: element.height})"
        )
        calls = await page.evaluate(
            """
            traceId => (window.__bookwalkerDrawCalls || [])
              .filter(call => call.canvasId === traceId)
              .map(call => call.destination)
            """,
            trace_id,
        )
        width = int(size["width"])
        height = int(size["height"])
        candidates: list[dict[str, int]] = []
        for values in calls:
            if not isinstance(values, list) or len(values) != 4:
                continue
            x, y, box_width, box_height = (round(float(value)) for value in values)
            left = max(0, x)
            top = max(0, y)
            right = min(width, x + box_width)
            bottom = min(height, y + box_height)
            if right - left < 100 or bottom - top < 100:
                continue
            candidates.append(
                {
                    "x": left,
                    "y": top,
                    "width": right - left,
                    "height": bottom - top,
                }
            )

        unique: list[dict[str, int]] = []
        for candidate in candidates:
            if candidate in unique:
                continue
            unique.append(candidate)

        # A transition can draw a previous page and then the current page on
        # the same canvas. Keep the largest containing rectangle and discard
        # the smaller one; side-by-side pages are not contained and survive.
        filtered: list[dict[str, int]] = []
        for candidate in sorted(
            unique,
            key=lambda box: box["width"] * box["height"],
            reverse=True,
        ):
            contained = any(
                other["x"] <= candidate["x"]
                and other["y"] <= candidate["y"]
                and other["x"] + other["width"]
                >= candidate["x"] + candidate["width"]
                and other["y"] + other["height"]
                >= candidate["y"] + candidate["height"]
                for other in filtered
            )
            if not contained:
                filtered.append(candidate)
        return sorted(filtered, key=lambda box: box["x"], reverse=True)

    async def _is_first_page(self, page: Page) -> bool:
        """Return whether the viewer is showing the first numbered page."""

        counter = page.locator("#pageSliderCounter")
        try:
            if not await counter.count():
                return False
            raw_counter = await asyncio.wait_for(
                counter.inner_text(timeout=1000), timeout=1
            )
        except (PlaywrightTimeoutError, TimeoutError):
            return False
        page_number, _page_id = self.parse_page_counter(raw_counter)
        return page_number == 1

    @staticmethod
    def _union_capture_box(boxes: list[dict[str, int]]) -> dict[str, int]:
        """Return one box covering multiple visual parts of the cover."""

        left = min(box["x"] for box in boxes)
        top = min(box["y"] for box in boxes)
        right = max(box["x"] + box["width"] for box in boxes)
        bottom = max(box["y"] + box["height"] for box in boxes)
        return {
            "x": left,
            "y": top,
            "width": right - left,
            "height": bottom - top,
        }

    async def _non_white_capture_box(
        self,
        canvas: Locator,
    ) -> dict[str, int] | None:
        """Find the visible cover bounds when draw tracing missed a frame."""

        try:
            result = await canvas.evaluate(
                """
                element => {
                  const width = element.width;
                  const height = element.height;
                  const context = element.getContext('2d', {
                    willReadFrequently: true,
                  });
                  if (!context || width <= 0 || height <= 0) return null;
                  let pixels;
                  try {
                    pixels = context.getImageData(0, 0, width, height).data;
                  } catch (error) {
                    return null;
                  }
                  let left = width;
                  let top = height;
                  let right = 0;
                  let bottom = 0;
                  for (let y = 0; y < height; y += 1) {
                    for (let x = 0; x < width; x += 1) {
                      const offset = (y * width + x) * 4;
                      const alpha = pixels[offset + 3];
                      const nonWhite = alpha > 0 && (
                        pixels[offset] < 250 ||
                        pixels[offset + 1] < 250 ||
                        pixels[offset + 2] < 250
                      );
                      if (!nonWhite) continue;
                      left = Math.min(left, x);
                      top = Math.min(top, y);
                      right = Math.max(right, x + 1);
                      bottom = Math.max(bottom, y + 1);
                    }
                  }
                  if (left >= right || top >= bottom) return null;
                  return {
                    x: left,
                    y: top,
                    width: right - left,
                    height: bottom - top,
                  };
                }
                """
            )
        except (PlaywrightError, PlaywrightTimeoutError, TimeoutError):
            return None
        if not isinstance(result, dict):
            return None
        try:
            box = {
                "x": int(result["x"]),
                "y": int(result["y"]),
                "width": int(result["width"]),
                "height": int(result["height"]),
            }
        except (KeyError, TypeError, ValueError):
            return None
        if box["width"] <= 0 or box["height"] <= 0:
            return None
        return box

    async def get_capture_targets(self, page: Page) -> tuple[Locator, ...]:
        """Return one page target, or a right-to-left split of a spread.

        BookWalker renders a novel spread into one canvas when the browser
        window is wide enough. The viewer's reading order is right page then
        left page, so temporary canvases are created in that order. Draw
        geometry is used to remove the viewer margins before Core captures.
        """

        canvas = await self.get_capture_target(page)
        size = await canvas.evaluate(
            "element => ({width: element.width, height: element.height})"
        )
        width = int(size["width"])
        height = int(size["height"])
        boxes = await self._page_draw_rectangles(page, canvas)
        first_page = await self._is_first_page(page)
        if len(boxes) > 1 and first_page:
            # A cover spread is one visual cover. Keep it as one artifact while
            # removing the outer viewer margins; regular spreads remain
            # separate right-to-left page captures.
            boxes = [self._union_capture_box(boxes)]
        if not boxes:
            if height <= 0 or width <= height * self.spread_ratio:
                return (canvas,)
            if first_page:
                # The initial cover frame can be painted before the draw hook
                # records its geometry. Use the rendered pixel bounds as a
                # last-resort crop instead of preserving the viewer margins.
                cover_box = await self._non_white_capture_box(canvas)
                if cover_box is None:
                    return (canvas,)
                boxes = [cover_box]
            else:
                boxes = [
                    {"x": 0, "y": 0, "width": width // 2, "height": height},
                    {
                        "x": width // 2,
                        "y": 0,
                        "width": width - width // 2,
                        "height": height,
                    },
                ]

        if len(boxes) == 1 and boxes[0] == {
            "x": 0,
            "y": 0,
            "width": width,
            "height": height,
        }:
            return (canvas,)

        self._capture_run += 1
        run = f"{id(self)}-{self._capture_run}"
        await canvas.evaluate(
            """
            (source, payload) => {
              const {run, boxes} = payload;
              document
                .querySelectorAll('canvas[data-bookwalker-capture-run]')
                .forEach(element => element.remove());
              for (const box of boxes) {
                const target = document.createElement('canvas');
                target.width = box.width;
                target.height = box.height;
                target.dataset.bookwalkerCaptureRun = run;
                const context = target.getContext('2d');
                if (!context) throw new Error('2D canvas context unavailable');
                context.drawImage(
                  source,
                  box.x, box.y, box.width, box.height,
                  0, 0, box.width, box.height,
                );
                document.body.appendChild(target);
              }
            }
            """,
            {"run": run, "boxes": boxes},
        )
        parts = page.locator(f'canvas[data-bookwalker-capture-run="{run}"]')
        if await parts.count() != len(boxes):
            raise LookupError("BookWalker page crop did not create expected canvases")
        return tuple(parts.nth(index) for index in range(len(boxes)))

    async def cleanup_capture_targets(self, page: Page) -> None:
        await page.locator("canvas[data-bookwalker-capture-run]").evaluate_all(
            "elements => elements.forEach(element => element.remove())"
        )
        await page.evaluate("window.__bookwalkerDrawCalls = []")

    async def get_content_identity(self, page: Page) -> ContentIdentity:
        counter = page.locator("#pageSliderCounter")
        raw_counter = ""
        if await counter.count():
            try:
                raw_counter = (
                    await asyncio.wait_for(counter.inner_text(timeout=1000), timeout=1)
                ).strip()
            except (PlaywrightTimeoutError, TimeoutError):
                raw_counter = ""
        page_number, page_id = self.parse_page_counter(raw_counter)
        content_id = self.content_id_from_url(page.url)
        return ContentIdentity(
            page_id=page_id or content_id,
            page_number=page_number,
            source_id=content_id,
        )

    async def get_content_context(self, page: Page) -> ContentContext:
        content_id = self.content_id_from_url(page.url)
        title = ""
        title_locator = page.locator("#pagetitle")
        if await title_locator.count():
            try:
                title = (
                    await asyncio.wait_for(title_locator.inner_text(timeout=1000), timeout=1)
                ).strip() or None
            except (PlaywrightTimeoutError, TimeoutError):
                title = None
        return ContentContext(content_id=content_id, work_id=content_id, title=title)

    async def go_next(self, page: Page) -> None:
        self._final_navigation_pending = await self._is_last_page_counter(page)
        # The viewer's keyboard handler advances reliably even when a
        # viewport click is accepted by Playwright but ignored by the viewer.
        await self._press_left_arrow(page)

    async def _press_left_arrow(self, page: Page) -> None:
        await self._arm_native_capture(page)
        await page.keyboard.press("ArrowLeft")

    async def _click_left_edge(self, page: Page) -> None:
        """Use the viewer click area only after keyboard navigation stalls."""

        await self._arm_native_capture(page)
        viewport = page.locator("#viewport1")
        box = await viewport.bounding_box()
        if not box or box["width"] <= 0 or box["height"] <= 0:
            return
        try:
            await viewport.click(
                position={
                    "x": min(50, box["width"] / 10),
                    "y": box["height"] / 2,
                },
                force=True,
                timeout=1_000,
                no_wait_after=True,
            )
        except PlaywrightTimeoutError:
            return

    async def wait_for_change(
        self,
        page: Page,
        previous_identity: ContentIdentity | None,
    ) -> None:
        deadline_ms = self.page_change_timeout_ms
        elapsed_ms = 0
        retry_at_ms = self.advance_retry_interval_ms
        retry_count = 0
        while elapsed_ms < deadline_ms:
            state = await self.detect_state(page)
            can_retry_advance = False
            if state in {PageState.AD, PageState.END, PageState.NEXT_CONTENT}:
                return
            if state is PageState.CONTENT:
                current = await self.get_content_identity(page)
                if previous_identity is None:
                    return
                if current != previous_identity:
                    await self._wait_for_render_ready(page)
                    return
                # Some BookWalker trial readers keep the final content canvas
                # at N/N after the last left-side action and never expose the
                # optional #endOfBook marker. The last page was already
                # captured before this wait, so an unchanged N/N is a safe
                # terminal condition and avoids retrying forever.
                if await self._is_last_page_counter(page):
                    return
                can_retry_advance = True
            if (
                can_retry_advance
                and retry_count < self.advance_retry_count
                and elapsed_ms >= retry_at_ms
            ):
                # Playwright can report a successful dispatch even when the
                # viewer ignores that action. Alternate the two known input
                # paths while the page identity remains authoritative.
                if retry_count % 2 == 0:
                    await self._click_left_edge(page)
                else:
                    await self._press_left_arrow(page)
                retry_count += 1
                retry_at_ms = self.advance_retry_interval_ms * (retry_count + 1)
            await page.wait_for_timeout(100)
            elapsed_ms += 100
        raise PageChangeTimeoutError("BookWalker page did not change within timeout")
