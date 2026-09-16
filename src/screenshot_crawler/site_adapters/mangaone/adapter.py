"""Adapter for the Manga ONE image-based chapter viewer.

Manga ONE renders chapter pages as individual ``img`` elements in a
horizontal, right-to-left reader.  The viewer can show one page or a spread;
the adapter returns the currently visible images in reading order and never
captures the surrounding chapter page.
"""

from __future__ import annotations

import asyncio
import re
from urllib.parse import urlparse

from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from screenshot_crawler.core.errors import PageChangeTimeoutError
from screenshot_crawler.core.models import ContentContext, ContentIdentity
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.base import SiteAdapter
from screenshot_crawler.site_adapters.mangaone.login import login_mangaone

_PAGE_LABEL = re.compile(r"^page_(?P<number>\d+)$")
_CHAPTER_URL = re.compile(r"/manga/(?P<work_id>[^/]+)/chapter/(?P<chapter_id>[^/?#]+)")
_EPISODE_TITLE = re.compile(
    r"^(?P<title>.+?)\s*第\s*(?P<number>\d+)\s*話"
    r"(?:\s*[（(]\s*(?P<part>前編|後編)\s*[）)])?$"
)


def parse_mangaone_page_number(label: str | None) -> int | None:
    """Convert a Manga ONE page alt label to its zero-based page index."""

    match = _PAGE_LABEL.fullmatch((label or "").strip())
    return int(match.group("number")) if match else None


def order_mangaone_pages(pages: list[tuple[str, float]]) -> tuple[str, ...]:
    """Return visible page labels in Manga ONE's right-to-left order."""

    return tuple(label for label, _ in sorted(pages, key=lambda item: item[1], reverse=True))


def split_mangaone_episode_title(raw_title: str | None) -> tuple[str, str | None]:
    """Return ``(work_title, episode_label)`` from a Manga ONE page title."""

    normalized = " ".join((raw_title or "").split())
    normalized = normalized.split(" | ", 1)[0].strip()
    match = _EPISODE_TITLE.fullmatch(normalized)
    if not match:
        return normalized, None

    episode = f"第{int(match.group('number')):02d}話"
    if match.group("part"):
        episode += f"-{match.group('part')}"
    return match.group("title").strip(), episode


def mangaone_identity_from_pages(
    labels: tuple[str, ...],
    *,
    chapter_id: str | None = None,
) -> ContentIdentity:
    """Build a stable identity for one visible page or spread."""

    numbers = [
        number
        for number in (parse_mangaone_page_number(label) for label in labels)
        if number is not None
    ]
    page_id = "|".join(labels) or None
    return ContentIdentity(
        page_id=page_id,
        page_number=max(numbers) + 1 if numbers else None,
        source_id=chapter_id,
    )


class MangaOneAdapter(SiteAdapter):
    """Image viewer adapter for one Manga ONE chapter."""

    page_change_timeout_ms = 10_000
    render_stable_checks = 3
    advance_retry_count = 2

    viewer_selector = ".viewer-container"
    page_selector = '.viewer-container img[alt^="page_"]'
    fullscreen_label = "全画面"
    end_selectors = (
        "#endOfChapter",
        "#chapterEnd",
        "#end-of-chapter",
        '[data-viewer-state="end"]',
        '[data-viewer-state="ended"]',
        '[data-state="end"]',
        '[data-state="ended"]',
        '[data-end-of-chapter="true"]',
    )

    def __init__(self) -> None:
        self._initial_url: str | None = None
        self._initial_context: ContentContext | None = None
        self._advance_pending = False
        self._output_title: str | None = None
        self._output_order: str | None = None

    async def login(
        self,
        page: Page,
        *,
        email: str,
        password: str,
        home_url: str = "https://manga-one.com/login",
    ) -> None:
        """Run the site-specific login flow on an existing browser page."""

        await login_mangaone(page, email=email, password=password, home_url=home_url)

    @staticmethod
    def chapter_parts_from_url(url: str) -> tuple[str | None, str | None]:
        """Return ``(work_id, chapter_id)`` from a Manga ONE chapter URL."""

        match = _CHAPTER_URL.search(urlparse(url).path)
        return (
            (match.group("work_id"), match.group("chapter_id"))
            if match
            else (None, None)
        )

    async def _visible(self, locator: Locator) -> bool:
        try:
            return await asyncio.wait_for(locator.is_visible(timeout=500), timeout=1)
        except (PlaywrightTimeoutError, TimeoutError):
            return False

    async def _page_image_rows(self, page: Page) -> list[dict[str, object]]:
        """Return ready page images that overlap the current viewport."""

        locator = page.locator(self.page_selector)
        try:
            return await asyncio.wait_for(
                locator.evaluate_all(
                    """
                    (elements) => elements.map((element, index) => {
                      const rect = element.getBoundingClientRect();
                      const visible = rect.width > 0 && rect.height > 0 &&
                        rect.right > 0 && rect.left < window.innerWidth &&
                        rect.bottom > 0 && rect.top < window.innerHeight &&
                        element.complete && element.naturalWidth > 0;
                      return {
                        index,
                        alt: element.alt || '',
                        src: element.currentSrc || element.src || '',
                        x: rect.x,
                        y: rect.y,
                        width: rect.width,
                        height: rect.height,
                        visible,
                      };
                    }).filter(item => item.visible)
                    """
                ),
                timeout=2,
            )
        except (PlaywrightTimeoutError, TimeoutError):
            return []

    async def _visible_page_images(
        self, page: Page
    ) -> list[tuple[Locator, dict[str, object]]]:
        locator = page.locator(self.page_selector)
        rows = await self._page_image_rows(page)
        result = [(locator.nth(int(row["index"])), row) for row in rows]
        result.sort(key=lambda item: float(item[1]["x"]), reverse=True)
        return result

    async def _page_signature(
        self, page: Page
    ) -> tuple[tuple[str, int, int, int, int], ...]:
        rows = await self._page_image_rows(page)
        ordered = sorted(rows, key=lambda row: float(row["x"]), reverse=True)
        return tuple(
            (
                str(row["alt"]),
                round(float(row["x"])),
                round(float(row["y"])),
                round(float(row["width"])),
                round(float(row["height"])),
            )
            for row in ordered
        )

    async def _wait_for_render_ready(self, page: Page) -> None:
        elapsed_ms = 0
        stable_checks = 0
        previous: tuple[tuple[str, int, int, int, int], ...] | None = None
        while elapsed_ms < self.page_change_timeout_ms:
            signature = await self._page_signature(page)
            if signature and signature == previous:
                stable_checks += 1
                if stable_checks >= self.render_stable_checks:
                    return
            else:
                stable_checks = 0
            previous = signature
            await page.wait_for_timeout(100)
            elapsed_ms += 100
        raise PageChangeTimeoutError(
            "Manga ONE viewer did not finish loading within the timeout"
        )

    async def _enter_fullscreen_reader(self, page: Page) -> None:
        """Use Manga ONE's own Full Screen control to obtain a Full HD page."""

        button = page.get_by_role("button", name=self.fullscreen_label, exact=True)
        if not await self._visible(button):
            return
        try:
            await button.click(timeout=1_000, no_wait_after=True)
        except PlaywrightTimeoutError:
            return
        await page.wait_for_timeout(200)

    async def initialize(self, page: Page) -> None:
        self._initial_url = page.url
        self._advance_pending = False
        # The chapter page mounts the reader controls asynchronously. Wait for
        # the first image before looking for the Full Screen control, then wait
        # again because entering Full Screen changes the image geometry.
        await self._wait_for_render_ready(page)
        await self._enter_fullscreen_reader(page)
        await self._wait_for_render_ready(page)
        self._initial_context = await self.get_content_context(page)
        self._output_title, self._output_order = split_mangaone_episode_title(
            self._initial_context.title
        )

    def get_output_metadata(self) -> dict[str, str | None]:
        return {
            "title": self._output_title,
            "order": self._output_order,
            "author": None,
            "genre": "漫画",
        }

    async def detect_state(self, page: Page) -> PageState:
        if self._initial_url is not None:
            initial_work, initial_chapter = self.chapter_parts_from_url(self._initial_url)
            current_work, current_chapter = self.chapter_parts_from_url(page.url)
            if (
                initial_chapter is not None
                and current_chapter is not None
                and (initial_work, initial_chapter) != (current_work, current_chapter)
            ):
                return PageState.NEXT_CONTENT

        if await self._explicit_end_visible(page):
            return PageState.END

        if await self._page_image_rows(page):
            return PageState.CONTENT
        if await page.locator(self.page_selector).count():
            return PageState.LOADING
        if await self._visible(page.locator(self.viewer_selector)):
            return PageState.LOADING if self._advance_pending else PageState.UNKNOWN
        return PageState.UNKNOWN

    async def _explicit_end_visible(self, page: Page) -> bool:
        """Return only for a viewer-provided, explicit end marker/state."""

        for selector in self.end_selectors:
            if await self._visible(page.locator(selector)):
                return True
        return False

    async def get_capture_target(self, page: Page) -> Locator:
        targets = await self._visible_page_images(page)
        if not targets:
            raise LookupError("Manga ONE content image is not visible")
        return targets[0][0]

    async def get_capture_targets(self, page: Page) -> tuple[Locator, ...]:
        """Return one or two page images, ordered right-to-left."""

        targets = await self._visible_page_images(page)
        if not targets:
            raise LookupError("Manga ONE content image is not visible")
        return tuple(locator for locator, _ in targets)

    async def get_content_identity(self, page: Page) -> ContentIdentity:
        labels = tuple(
            str(row["alt"])
            for row in sorted(
                await self._page_image_rows(page),
                key=lambda row: float(row["x"]),
                reverse=True,
            )
        )
        _, chapter_id = self.chapter_parts_from_url(page.url)
        return mangaone_identity_from_pages(labels, chapter_id=chapter_id)

    async def get_content_context(self, page: Page) -> ContentContext:
        work_id, chapter_id = self.chapter_parts_from_url(page.url)
        title: str | None = None
        try:
            raw_title = (await page.title()).strip()
            title = raw_title.split(" | ", 1)[0].strip() or None
        except (PlaywrightTimeoutError, TimeoutError):
            pass
        return ContentContext(
            content_id=chapter_id,
            work_id=work_id,
            episode_id=chapter_id,
            chapter_id=chapter_id,
            title=title,
        )

    async def go_next(self, page: Page) -> None:
        self._advance_pending = True
        viewer = page.locator(self.viewer_selector)
        box = await viewer.bounding_box()
        if box and box["width"] > 0 and box["height"] > 0:
            try:
                await viewer.click(
                    position={"x": min(80, box["width"] / 10), "y": box["height"] / 2},
                    force=True,
                    timeout=1_000,
                    no_wait_after=True,
                )
                return
            except PlaywrightTimeoutError:
                pass
        await page.mouse.click(50, await page.evaluate("window.innerHeight / 2"))

    async def wait_for_change(
        self,
        page: Page,
        previous_identity: ContentIdentity | None,
    ) -> None:
        if previous_identity is None:
            await self._wait_for_render_ready(page)
            return

        elapsed_ms = 0
        retry_count = 0
        retry_at_ms = self.page_change_timeout_ms // (self.advance_retry_count + 1)
        while elapsed_ms < self.page_change_timeout_ms:
            state = await self.detect_state(page)
            if state in {PageState.END, PageState.NEXT_CONTENT}:
                self._advance_pending = False
                return

            rows = await self._page_image_rows(page)
            if rows:
                current = await self.get_content_identity(page)
                if current != previous_identity:
                    await self._wait_for_render_ready(page)
                    self._advance_pending = False
                    return
                if retry_count < self.advance_retry_count and elapsed_ms >= retry_at_ms:
                    await self.go_next(page)
                    retry_count += 1
                    retry_at_ms = self.page_change_timeout_ms * (retry_count + 1) // (
                        self.advance_retry_count + 1
                    )

            await page.wait_for_timeout(100)
            elapsed_ms += 100
        raise PageChangeTimeoutError("Manga ONE page did not change within the timeout")
