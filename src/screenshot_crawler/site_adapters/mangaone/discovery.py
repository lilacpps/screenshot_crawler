"""Manga ONE Discovery adapter.

The Manga ONE chapter page exposes the work's chapter listing in the DOM.
This adapter deliberately knows nothing about Catalog or crawler execution;
it only turns that listing into site-neutral Discovery records.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from urllib.parse import urlparse

from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from screenshot_crawler.discovery.base import DiscoveryAdapter
from screenshot_crawler.discovery.models import (
    DiscoveredItem,
    DiscoveredRecord,
    DiscoveredSource,
    DiscoveryMode,
)
from screenshot_crawler.discovery.service import DiscoveryIncompleteError
from screenshot_crawler.watchlist.models import WatchlistTarget

LISTING_SELECTOR = "#chapterList"
CARD_SELECTOR = "div.cursor-pointer.block.border-b-1.border-primary.p-3"
WAIT_TIMEOUT_MS = 10_000
POLL_INTERVAL_MS = 100
MAX_PAGES = 200

_CHAPTER_PATH = re.compile(
    r"^/manga/(?P<work_id>[^/]+)/chapter/(?P<chapter_id>[^/?#]+)$"
)
_CHAPTER_IMAGE = re.compile(r"/(?:chapter)/(?P<chapter_id>[^/?#]+)\.webp(?:$|[?#])")
_EPISODE_LABEL = re.compile(
    r"^第\s*(?P<number>\d+)\s*話\s*"
    r"(?:[（(]\s*(?P<part>前編|後編)\s*[）)])?\s*$"
)
_TITLE_EPISODE = re.compile(
    r"^(?P<title>.+?)\s+第\s*\d+\s*話(?:\s*[（(](?:前編|後編)[）)])?\s*$"
)


@dataclass(frozen=True, slots=True)
class MangaOneChapterParts:
    work_id: str
    chapter_id: str


def parse_mangaone_chapter_url(url: str) -> MangaOneChapterParts | None:
    """Parse only the canonical Manga ONE chapter path shape."""

    match = _CHAPTER_PATH.fullmatch(urlparse(url).path)
    if match is None:
        return None
    return MangaOneChapterParts(match.group("work_id"), match.group("chapter_id"))


def chapter_id_from_image_url(url: str) -> str | None:
    """Extract a chapter id from the observed chapter image URL pattern."""

    match = _CHAPTER_IMAGE.search(urlparse(url).path)
    return match.group("chapter_id") if match else None


def parse_mangaone_episode_label(
    label: str | None,
) -> tuple[str | None, str | None]:
    """Return ``(order_key, order_label)`` without guessing PR episode order."""

    normalized = " ".join((label or "").split())
    match = _EPISODE_LABEL.fullmatch(normalized)
    if match is None:
        return None, normalized or None
    number = str(int(match.group("number")))
    part = match.group("part")
    suffix = f"-{part}" if part else ""
    return f"{number}{suffix}", f"第{int(number):02d}話{suffix}"


def map_mangaone_access_mode(text: str) -> str:
    """Map the visible Manga ONE badges to Catalog access modes."""

    normalized = " ".join(text.split())
    is_free = "FREE" in normalized.upper() or "無料" in normalized
    is_paid = "先読み" in normalized or "先読" in normalized
    if is_free and is_paid:
        raise DiscoveryIncompleteError(
            "Manga ONE chapter card has conflicting free and paid badges"
        )
    if is_free:
        return "free"
    if is_paid:
        return "paid"
    return "quota"


def mangaone_title_from_page_title(raw_title: str | None) -> str | None:
    """Extract the work title from a Manga ONE document title."""

    normalized = " ".join((raw_title or "").split())
    normalized = normalized.split(" | ", 1)[0].strip()
    match = _TITLE_EPISODE.fullmatch(normalized)
    if match:
        normalized = match.group("title").strip()
    return normalized or None


class MangaOneDiscoveryAdapter(DiscoveryAdapter):
    """Enumerate Manga ONE chapters from the chapter listing."""

    async def iter_records(
        self,
        page: Page,
        target: WatchlistTarget,
        mode: DiscoveryMode,
    ) -> AsyncIterator[DiscoveredRecord]:
        target_parts = parse_mangaone_chapter_url(target.url)
        if target_parts is None:
            raise DiscoveryIncompleteError(
                "Watchlist target must be a Manga ONE chapter URL"
            )

        try:
            await page.goto(target.url, wait_until="domcontentloaded", timeout=WAIT_TIMEOUT_MS)
            await self._wait_for_listing(page)
            canonical_title = mangaone_title_from_page_title(await page.title())
        except (PlaywrightTimeoutError, TimeoutError) as exc:
            raise DiscoveryIncompleteError("Manga ONE chapter listing did not load") from exc

        seen_ids: set[str] = set()
        previous_signature: tuple[str, ...] | None = None
        page_number = 0

        while page_number < MAX_PAGES:
            page_number += 1
            cards = page.locator(f"{LISTING_SELECTOR} {CARD_SELECTOR}")
            if await cards.count() == 0:
                raise DiscoveryIncompleteError("Manga ONE chapter listing has no cards")

            signature = await self._card_signature(cards)
            if not signature or signature == previous_signature:
                raise DiscoveryIncompleteError("Manga ONE chapter listing did not advance")
            previous_signature = signature

            for index in range(await cards.count()):
                card = cards.nth(index)
                parts = await self._card_chapter_parts(card, target_parts.work_id)
                if parts is None:
                    raise DiscoveryIncompleteError(
                        "Manga ONE chapter listing contains a card without a valid identity"
                    )
                if parts.work_id != target_parts.work_id:
                    continue
                if parts.chapter_id in seen_ids:
                    continue
                seen_ids.add(parts.chapter_id)
                label = await self._card_episode_label(card)
                order_key, order_label = parse_mangaone_episode_label(label)
                text = await card.inner_text()
                yield DiscoveredRecord(
                    item=DiscoveredItem(
                        canonical_title=canonical_title,
                        author=None,
                        genre="漫画",
                        kind="episode",
                        order_key=order_key,
                        order_label=order_label,
                    ),
                    source=DiscoveredSource(
                        external_id=parts.chapter_id,
                        url=(
                            "https://manga-one.com/manga/"
                            f"{parts.work_id}/chapter/{parts.chapter_id}"
                        ),
                        access_mode=map_mangaone_access_mode(text),
                        free_until=None,
                        available=True,
                    ),
                )

            next_button = await self._next_button(page)
            if next_button is None:
                raise DiscoveryIncompleteError(
                    "Manga ONE chapter listing has no unambiguous next button"
                )
            if await self._is_disabled(next_button):
                return

            try:
                await next_button.click(timeout=WAIT_TIMEOUT_MS)
                await self._wait_for_new_signature(page, previous_signature)
            except (PlaywrightTimeoutError, TimeoutError) as exc:
                raise DiscoveryIncompleteError(
                    "Manga ONE chapter pagination did not advance"
                ) from exc

        raise DiscoveryIncompleteError("Manga ONE chapter listing exceeded page limit")

    async def _wait_for_listing(self, page: Page) -> None:
        listing = page.locator(LISTING_SELECTOR)
        await listing.wait_for(state="visible", timeout=WAIT_TIMEOUT_MS)

    async def _next_button(self, page: Page):
        buttons = page.locator(f"{LISTING_SELECTOR} button")
        matches = []
        for index in range(await buttons.count()):
            button = buttons.nth(index)
            if (await button.inner_text()).strip() == "次へ":
                matches.append(button)
        return matches[0] if len(matches) == 1 else None

    async def _card_signature(self, cards: Locator) -> tuple[str, ...]:
        count = await cards.count()
        signature: list[str] = []
        for index in range(count):
            card = cards.nth(index)
            parts = await self._card_chapter_parts(card, None)
            if parts is None:
                signature.append(f"invalid:{index}")
            else:
                signature.append(f"{parts.work_id}:{parts.chapter_id}")
        return tuple(signature)

    async def _wait_for_new_signature(
        self,
        page: Page,
        previous: tuple[str, ...],
    ) -> None:
        elapsed = 0
        cards = page.locator(f"{LISTING_SELECTOR} {CARD_SELECTOR}")
        while elapsed < WAIT_TIMEOUT_MS:
            signature = await self._card_signature(cards)
            if signature and signature != previous:
                return
            await page.wait_for_timeout(POLL_INTERVAL_MS)
            elapsed += POLL_INTERVAL_MS
        raise PlaywrightTimeoutError("Manga ONE chapter listing did not change")

    async def _card_chapter_parts(
        self,
        card: Locator,
        expected_work_id: str | None,
    ) -> MangaOneChapterParts | None:
        anchors = card.locator("a")
        if await anchors.count():
            href = await anchors.first.get_attribute("href")
            if href:
                parts = parse_mangaone_chapter_url(href)
                if parts is None:
                    return None
                return parts

        images = card.locator("img")
        for index in range(await images.count()):
            src = await images.nth(index).get_attribute("src")
            if src:
                chapter_id = chapter_id_from_image_url(src)
                if chapter_id:
                    if expected_work_id is None:
                        return MangaOneChapterParts("", chapter_id)
                    return MangaOneChapterParts(expected_work_id, chapter_id)
        return None

    async def _card_episode_label(self, card: Locator) -> str | None:
        images = card.locator("img")
        for index in range(await images.count()):
            label = await images.nth(index).get_attribute("alt")
            if label and label.strip():
                return label.strip()
        return None

    @staticmethod
    async def _is_disabled(button: Locator) -> bool:
        if await button.is_disabled():
            return True
        return (await button.get_attribute("aria-disabled")) == "true"
