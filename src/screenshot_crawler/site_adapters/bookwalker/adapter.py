"""Adapter for the BookWalker image/canvas browser viewer.

The viewer shell is a canvas renderer. This adapter intentionally uses only
stable DOM signals exposed by the viewer shell and stops on ambiguous states.
"""

from __future__ import annotations

import asyncio
import re
from urllib.parse import parse_qs, urlparse

from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from screenshot_crawler.core.errors import PageChangeTimeoutError
from screenshot_crawler.core.models import ContentContext, ContentIdentity
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.base import SiteAdapter
from screenshot_crawler.site_adapters.bookwalker.login import login_bookwalker

_DRAW_TRACE_SCRIPT = """
(() => {
  if (window.__bookwalkerDrawTraceInstalled) return;
  window.__bookwalkerDrawTraceInstalled = true;
  window.__bookwalkerDrawCalls = [];
  const original = CanvasRenderingContext2D.prototype.drawImage;
  let nextCanvasId = 1;
  const canvasIds = new WeakMap();
  const getCanvasId = canvas => {
    let id = canvasIds.get(canvas);
    if (!id) {
      id = String(nextCanvasId++);
      canvasIds.set(canvas, id);
      canvas.dataset.bookwalkerTraceId = id;
    }
    return id;
  };
  CanvasRenderingContext2D.prototype.drawImage = function(...args) {
    try {
      const canvas = this.canvas;
      const values = args.slice(1).map(value => Number(value));
      if (canvas && canvas.width > 1000 && canvas.height > 500) {
        const destination = values.length >= 8
          ? values.slice(4, 8)
          : values.length === 4
            ? values.slice(0, 4)
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
      }
    } catch (error) {}
    return original.apply(this, args);
  };
})();
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


class BookWalkerAdapter(SiteAdapter):
    """Canvas viewer adapter for one BookWalker content ID."""

    page_change_timeout_ms = 10_000
    navigation_wait_timeout_ms = 5_000
    read_link_wait_timeout_ms = 5_000
    render_stable_checks = 4
    advance_retry_count = 2
    end_marker_grace_ms = 1_500
    spread_ratio = 1.25

    def __init__(self) -> None:
        self._initial_content_id: str | None = None
        self._capture_run = 0
        self._output_title: str | None = None
        self._output_author: str | None = None
        self._output_volume: str | None = None
        self._output_genre = "小説"
        self._series_count: int | None = None
        self._final_navigation_pending = False

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

        text = (candidate.get("text") or "").strip()
        action = (candidate.get("action") or "").strip().lower()
        href = (candidate.get("href") or "").lower()
        if action in {"cover", "check", "more_read", "author"}:
            return False
        if any(
            marker in text
            for marker in (
                "\u8aad\u3080",
                "\u8aad\u307f",
                "\u307e\u308b\u8aad\u307f",
                "10\u5206",
            )
        ):
            return True
        return bool(
            "viewer" in href
            or "read" in action
            or "reading" in action
            or "読む" in text
            or "読み" in text
            or "まる読み" in text
            or "10分" in text
        )

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
        if not await self._has_viewer_shell(page):
            parsed = urlparse(page.url)
            is_product_page = parsed.netloc.lower() in {
                "bookwalker.jp",
                "www.bookwalker.jp",
            } and bool(re.match(r"^/de[0-9a-f-]+/?$", parsed.path, re.IGNORECASE))
            if is_product_page:
                await self._collect_product_metadata(page)
                await self._open_reader_from_product(page)
                self._initial_content_id = self.content_id_from_url(page.url)

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

    async def get_capture_targets(self, page: Page) -> tuple[Locator, ...]:
        """Return one page target, or a right-to-left split of a spread.

        BookWalker renders a novel spread into one canvas when the browser
        window is wide enough. The viewer's reading order is right page then
        left page, so temporary canvases are created in that order. Raw
        canvas capture in Core then excludes the viewer toolbar and margins.
        """

        canvas = await self.get_capture_target(page)
        size = await canvas.evaluate(
            "element => ({width: element.width, height: element.height})"
        )
        width = int(size["width"])
        height = int(size["height"])
        boxes = await self._page_draw_rectangles(page, canvas)
        if not boxes:
            if height <= 0 or width <= height * self.spread_ratio:
                return (canvas,)
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
        # BookWalker advances on the left side of the viewer. The dedicated
        # tap-area div is normally hidden on desktop, so click the viewer's
        # left edge instead of relying on browser scroll behavior from a bare
        # ArrowLeft key event when a spread is wider than the viewport.
        viewport = page.locator("#viewport1")
        box = await viewport.bounding_box()
        if box and box["width"] > 0 and box["height"] > 0:
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
                return
            except PlaywrightTimeoutError:
                pass
        await page.keyboard.press("ArrowLeft")

    async def wait_for_change(
        self,
        page: Page,
        previous_identity: ContentIdentity | None,
    ) -> None:
        deadline_ms = self.page_change_timeout_ms
        elapsed_ms = 0
        retry_at_ms = deadline_ms // (self.advance_retry_count + 1)
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
                # Some initial image/cover transitions consume the first
                # input without changing the page counter. Retry the same
                # bounded left-side action instead of waiting forever.
                await self.go_next(page)
                retry_count += 1
                retry_at_ms = deadline_ms * (retry_count + 1) // (
                    self.advance_retry_count + 1
                )
            await page.wait_for_timeout(100)
            elapsed_ms += 100
        raise PageChangeTimeoutError("BookWalker page did not change within timeout")
