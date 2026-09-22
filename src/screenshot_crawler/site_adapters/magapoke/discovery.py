"""Magapoke episode-list Discovery adapter."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urljoin, urlparse

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page

from screenshot_crawler.discovery.base import DiscoveryAdapter
from screenshot_crawler.discovery.models import (
    DiscoveredItem,
    DiscoveredRecord,
    DiscoveredSource,
    DiscoveryMode,
)
from screenshot_crawler.discovery.service import DiscoveryIncompleteError
from screenshot_crawler.watchlist.models import WatchlistTarget

MAGAPOKE_HOST = "pocket.shonenmagazine.com"
EPISODE_SECTION_SELECTOR = "div.p-episode__sec"
EPISODE_LIST_SELECTOR = ".p-episode__list"
EPISODE_ITEMS_SELECTOR = "ul.c-episode-items"
EPISODE_ITEM_SELECTOR = (
    "ul.c-episode-items > li.c-episode-items__item > a.c-episode-item"
)
EPISODE_TITLE_SELECTOR = "h2.c-episode-item__ttl"
WORK_TITLE_SELECTOR = "h1.p-episode__comic-ttl"
MORE_BUTTON_SELECTOR = "button.p-episode__more-btn"
WAIT_TIMEOUT_MS = 10_000
POLL_INTERVAL_MS = 100
MAX_EXPAND_ATTEMPTS = 200
RENTING_TEXT_SELECTOR = ".c-episode-item__txt--renting"
RENTING_LABEL_SELECTOR = ".c-episode-item__label02-txt"
_RENTAL_REMAINING_HOURS = re.compile(r"^あと\s*(\d+)\s*時間$")

_EPISODE_PATH = re.compile(
    r"^/title/(?P<title_id>\d+)/episode/(?P<episode_id>\d+)/?$"
)
_ACCESS_CLASSES = {
    "c-episode-item__ico--free": "free",
    "c-episode-item__ico--ticket-free": "quota",
    "c-episode-item__ico--renting": "quota",
    "c-episode-item__ico--point": "paid",
}


@dataclass(frozen=True, slots=True)
class MagapokeEpisodeParts:
    """The stable identity components of a Magapoke episode URL."""

    title_id: str
    episode_id: str


def parse_magapoke_episode_url(url: str) -> MagapokeEpisodeParts | None:
    """Parse a canonical Magapoke episode URL and preserve leading zeroes."""

    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != MAGAPOKE_HOST:
        return None
    match = _EPISODE_PATH.fullmatch(parsed.path)
    if match is None:
        return None
    return MagapokeEpisodeParts(
        title_id=match.group("title_id"),
        episode_id=match.group("episode_id"),
    )


def canonical_magapoke_episode_url(parts: MagapokeEpisodeParts) -> str:
    """Build the query-free canonical URL for an episode identity."""

    return (
        f"https://{MAGAPOKE_HOST}/title/{parts.title_id}/episode/"
        f"{parts.episode_id}"
    )


def map_magapoke_access_mode(icon_classes: str | Iterable[str] | None) -> str:
    """Map observed row icon classes to site-neutral access modes."""

    values = [icon_classes] if isinstance(icon_classes, str) else (icon_classes or ())
    recognized_classes = {
        class_name
        for value in values
        for class_name in (value or "").split()
        if class_name in _ACCESS_CLASSES
    }
    if len(recognized_classes) > 1:
        raise DiscoveryIncompleteError("Magapoke episode row has conflicting access states")
    if not recognized_classes:
        return "unknown"
    return _ACCESS_CLASSES[next(iter(recognized_classes))]


def _clean_text(value: str) -> str:
    return " ".join(value.split()).strip()


def magapoke_rental_grant_until(
    text: str | None,
    *,
    observed_at: datetime,
) -> datetime | None:
    """Return a conservative grant lower bound from the displayed whole hours."""

    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must be a timezone-aware datetime")
    match = _RENTAL_REMAINING_HOURS.fullmatch(_clean_text(text or ""))
    if match is None:
        return None
    return observed_at + timedelta(hours=int(match.group(1)))


class MagapokeDiscoveryAdapter(DiscoveryAdapter):
    """Enumerate every episode from one Magapoke episode URL."""

    async def iter_records(
        self,
        page: Page,
        target: WatchlistTarget,
        mode: DiscoveryMode,
    ) -> AsyncIterator[DiscoveredRecord]:
        del mode
        target_parts = parse_magapoke_episode_url(target.url)
        if target_parts is None:
            raise DiscoveryIncompleteError(
                "Watchlist target must be an HTTPS Magapoke episode URL"
            )

        try:
            await page.goto(
                target.url,
                wait_until="domcontentloaded",
                timeout=WAIT_TIMEOUT_MS,
            )
            episode_list = await self._wait_for_episode_list(page)
            canonical_title = await self._work_title(page)
            await self._expand_episode_list(page, episode_list, target_parts)
            records = await self._parse_records(
                episode_list,
                page.url,
                target_parts,
                canonical_title,
            )
        except DiscoveryIncompleteError:
            raise
        except (PlaywrightError, TimeoutError) as exc:
            raise DiscoveryIncompleteError(
                "Magapoke episode listing did not load or advance"
            ) from exc

        for record in records:
            yield record

    async def _wait_for_episode_list(self, page: Page) -> Locator:
        elapsed = 0
        while elapsed < WAIT_TIMEOUT_MS:
            listing = await self._find_episode_list(page)
            if listing is not None:
                return listing
            await page.wait_for_timeout(POLL_INTERVAL_MS)
            elapsed += POLL_INTERVAL_MS
        raise DiscoveryIncompleteError("Magapoke episode-list scope was not found")

    async def _find_episode_list(self, page: Page) -> Locator | None:
        sections = page.locator(EPISODE_SECTION_SELECTOR)
        matches: list[Locator] = []
        for index in range(await sections.count()):
            section = sections.nth(index)
            if not await section.is_visible():
                continue
            item_lists = section.locator(
                f"{EPISODE_LIST_SELECTOR} {EPISODE_ITEMS_SELECTOR}"
            )
            if await item_lists.count():
                matches.append(section)

        if len(matches) > 1:
            raise DiscoveryIncompleteError(
                "Magapoke episode-list section is not unambiguous"
            )
        if not matches:
            return None

        listing = matches[0]
        list_containers = listing.locator(EPISODE_LIST_SELECTOR)
        item_lists = listing.locator(EPISODE_ITEMS_SELECTOR)
        if await list_containers.count() == 0:
            raise DiscoveryIncompleteError("Magapoke episode-list scope is not visible")
        for index in range(await list_containers.count()):
            if not await list_containers.nth(index).is_visible():
                raise DiscoveryIncompleteError("Magapoke episode-list scope is not visible")
        if await item_lists.count() == 0:
            raise DiscoveryIncompleteError("Magapoke episode items are not identifiable")
        return listing

    async def _work_title(self, page: Page) -> str:
        titles = page.locator(WORK_TITLE_SELECTOR)
        visible: list[str] = []
        for index in range(await titles.count()):
            title = titles.nth(index)
            if await title.is_visible():
                text = _clean_text(await title.inner_text())
                if text:
                    visible.append(text)
        if len(visible) != 1:
            raise DiscoveryIncompleteError("Magapoke work title is not unambiguous")
        return visible[0]

    async def _row_locators(self, listing: Locator) -> list[Locator]:
        item_lists = listing.locator(EPISODE_ITEMS_SELECTOR)
        items = item_lists.locator(":scope > li.c-episode-items__item")
        rows = listing.locator(EPISODE_ITEM_SELECTOR)
        item_count = await items.count()
        row_count = await rows.count()
        if item_count == 0 or item_count != row_count:
            raise DiscoveryIncompleteError(
                "Magapoke episode list contains an invalid row structure"
            )
        return [rows.nth(index) for index in range(row_count)]

    async def _row_parts(
        self,
        row: Locator,
        page_url: str,
        target_parts: MagapokeEpisodeParts,
    ) -> MagapokeEpisodeParts:
        href = await row.get_attribute("href")
        if not href:
            raise DiscoveryIncompleteError("Magapoke episode row has no href")
        parts = parse_magapoke_episode_url(urljoin(page_url, href))
        if parts is None:
            raise DiscoveryIncompleteError("Magapoke episode row has an invalid href")
        if parts.title_id != target_parts.title_id:
            raise DiscoveryIncompleteError(
                "Magapoke episode list contains a different title_id"
            )
        return parts

    async def _identity_signature(
        self,
        listing: Locator,
        page_url: str,
        target_parts: MagapokeEpisodeParts,
    ) -> tuple[str, ...]:
        rows = await self._row_locators(listing)
        identities: list[str] = []
        for row in rows:
            parts = await self._row_parts(row, page_url, target_parts)
            identities.append(parts.episode_id)
        if len(set(identities)) != len(identities):
            raise DiscoveryIncompleteError("Magapoke episode list contains duplicate episode_id")
        return tuple(identities)

    async def _visible_more_button(self, section: Locator) -> Locator | None:
        buttons = section.locator(MORE_BUTTON_SELECTOR)
        visible: list[Locator] = []
        for index in range(await buttons.count()):
            button = buttons.nth(index)
            if await button.is_visible():
                visible.append(button)
        if len(visible) > 1:
            raise DiscoveryIncompleteError(
                "Magapoke episode-list expand control is ambiguous"
            )
        if not visible:
            return None
        button = visible[0]
        if await button.is_disabled() or await button.get_attribute("aria-disabled") == "true":
            raise DiscoveryIncompleteError("Magapoke episode-list expand control is disabled")
        return button

    async def _wait_for_progress(
        self,
        page: Page,
        listing: Locator,
        page_url: str,
        target_parts: MagapokeEpisodeParts,
        previous: tuple[str, ...],
    ) -> tuple[str, ...]:
        elapsed = 0
        previous_set = set(previous)
        while elapsed < WAIT_TIMEOUT_MS:
            current = await self._identity_signature(listing, page_url, target_parts)
            if len(current) > len(previous) and previous_set.issubset(current):
                return current
            await page.wait_for_timeout(POLL_INTERVAL_MS)
            elapsed += POLL_INTERVAL_MS
        raise DiscoveryIncompleteError(
            "Magapoke episode-list expansion did not add new episode identities"
        )

    async def _expand_episode_list(
        self,
        page: Page,
        listing: Locator,
        target_parts: MagapokeEpisodeParts,
    ) -> None:
        section = listing
        page_url = page.url
        for attempt in range(MAX_EXPAND_ATTEMPTS):
            button = await self._visible_more_button(section)
            if button is None:
                return
            if attempt == MAX_EXPAND_ATTEMPTS - 1:
                raise DiscoveryIncompleteError(
                    "Magapoke episode-list expansion exceeded its attempt bound"
                )
            previous = await self._identity_signature(listing, page_url, target_parts)
            await button.click(timeout=WAIT_TIMEOUT_MS)
            await self._wait_for_progress(
                page,
                listing,
                page_url,
                target_parts,
                previous,
            )
        raise DiscoveryIncompleteError("Magapoke episode-list expansion did not terminate")

    async def _parse_records(
        self,
        listing: Locator,
        page_url: str,
        target_parts: MagapokeEpisodeParts,
        canonical_title: str,
    ) -> list[DiscoveredRecord]:
        rows = await self._row_locators(listing)
        records: list[DiscoveredRecord] = []
        seen_ids: set[str] = set()
        for row in rows:
            parts = await self._row_parts(row, page_url, target_parts)
            if parts.episode_id in seen_ids:
                raise DiscoveryIncompleteError(
                    "Magapoke episode list contains duplicate episode_id"
                )
            seen_ids.add(parts.episode_id)

            titles = row.locator(EPISODE_TITLE_SELECTOR)
            if await titles.count() != 1 or not await titles.first.is_visible():
                raise DiscoveryIncompleteError("Magapoke episode row title is missing")
            order_label = _clean_text(await titles.first.inner_text())
            if not order_label:
                raise DiscoveryIncompleteError("Magapoke episode row title is empty")

            icons = row.locator(".c-episode-item__ico")
            icon_classes = [
                await icons.nth(index).get_attribute("class")
                for index in range(await icons.count())
            ]
            access_mode = map_magapoke_access_mode(icon_classes)
            access_granted_until = None
            if any(
                "c-episode-item__ico--renting" in (classes or "").split()
                for classes in icon_classes
            ):
                rental_text = None
                renting_text = row.locator(RENTING_TEXT_SELECTOR)
                if await renting_text.count() == 1:
                    rental_text = await renting_text.first.inner_text()
                else:
                    label_text = row.locator(RENTING_LABEL_SELECTOR)
                    if await label_text.count() == 1:
                        rental_text = await label_text.first.inner_text()
                access_granted_until = magapoke_rental_grant_until(
                    rental_text,
                    observed_at=datetime.now(UTC),
                )
            records.append(
                DiscoveredRecord(
                    item=DiscoveredItem(
                        canonical_title=canonical_title,
                        author=None,
                        genre="漫画",
                        kind="episode",
                        order_key=None,
                        order_label=order_label,
                    ),
                    source=DiscoveredSource(
                        external_id=parts.episode_id,
                        url=canonical_magapoke_episode_url(parts),
                        access_mode=access_mode,
                        free_until=None,
                        access_granted_until=access_granted_until,
                        available=True,
                    ),
                )
            )
        if not records:
            raise DiscoveryIncompleteError("Magapoke episode list is empty")
        return records
