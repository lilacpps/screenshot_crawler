"""Comic DAYS Atom Discovery with a full listing and free-subset authority."""

from __future__ import annotations

import asyncio
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlparse

from playwright.async_api import Page
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

ALLOWED_HOSTS = frozenset({"comic-days.com", "www.comic-days.com"})
ATOM_NS = "http://www.w3.org/2005/Atom"
JST = timezone(timedelta(hours=9), name="JST")
MAX_ATOM_BODY = 2_000_000
EPISODE_PATH = re.compile(r"^/episode/(?P<episode_id>[0-9]+)/?$")
SERIES_ID = re.compile(r"(?:series[/:])(?P<id>[0-9]+)")
ORDER_LABEL = re.compile(r"^第\s*(?P<number>[0-9]+)\s*話(?:\s|$)")


def parse_comicdays_episode_url(url: str) -> str | None:
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if (parsed.hostname or "").lower() not in ALLOWED_HOSTS:
        return None
    match = EPISODE_PATH.fullmatch(parsed.path)
    if match is None or parsed.query or parsed.fragment:
        return None
    return match.group("episode_id")


def canonical_comicdays_episode_url(url: str) -> str:
    episode_id = parse_comicdays_episode_url(url)
    if episode_id is None:
        raise ValueError("Not a Comic DAYS episode URL")
    return f"https://comic-days.com/episode/{episode_id}"


def _text(parent: ET.Element, name: str) -> str | None:
    value = parent.findtext(f"{{{ATOM_NS}}}{name}")
    value = " ".join((value or "").split())
    return value or None


def parse_atom_entries(body: bytes, *, expected_series_id: str) -> list[dict[str, str | None]]:
    """Parse and validate the first-party feed without retaining raw payloads."""
    if len(body) > MAX_ATOM_BODY:
        raise DiscoveryIncompleteError("Comic DAYS Atom feed exceeded the body limit")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise DiscoveryIncompleteError("Comic DAYS Atom feed was not valid XML") from exc
    feed_id = _text(root, "id") or ""
    feed_series_ids = set(re.findall(r"(?:series[/_:-])([0-9]+)(?:$|[^0-9])", feed_id))
    if feed_series_ids and expected_series_id not in feed_series_ids:
        raise DiscoveryIncompleteError("Comic DAYS Atom feed belongs to a different series")
    if any(link.get("rel") == "next" for link in root.findall(f"{{{ATOM_NS}}}link")):
        raise DiscoveryIncompleteError("Comic DAYS Atom feed was truncated")
    entries = root.findall(f"{{{ATOM_NS}}}entry")
    if not entries:
        raise DiscoveryIncompleteError("Comic DAYS Atom feed contained no entries")
    result: list[dict[str, str | None]] = []
    seen: set[str] = set()
    for entry in entries:
        raw_id = _text(entry, "id") or ""
        match = re.search(r"(?:episode:|/episode/)([0-9]+)$", raw_id)
        if match is None:
            raise DiscoveryIncompleteError("Comic DAYS feed entry had no numeric episode id")
        episode_id = match.group(1)
        links = entry.findall(f"{{{ATOM_NS}}}link")
        candidates = [link.get("href") for link in links if link.get("href")]
        canonical = None
        for href in candidates:
            parsed = urlparse(href or "")
            if (parsed.hostname or "").lower() in ALLOWED_HOSTS and EPISODE_PATH.fullmatch(parsed.path or ""):
                candidate_id = parse_comicdays_episode_url(href or "")
                if candidate_id == episode_id:
                    canonical = canonical_comicdays_episode_url(href or "")
                    break
        if canonical is None:
            raise DiscoveryIncompleteError(f"Comic DAYS entry {episode_id} lacked a matching canonical URL")
        if episode_id in seen:
            raise DiscoveryIncompleteError(f"Comic DAYS feed duplicated episode {episode_id}")
        seen.add(episode_id)
        result.append({"episode_id": episode_id, "url": canonical, "title": _text(entry, "title"), "updated": _text(entry, "updated")})
    return result


async def _series_id_from_page(page: Page) -> str:
    value = await asyncio.wait_for(page.evaluate(
        r"""() => {
          const values = new Set();
          const linked = new Set();
          for (const link of document.querySelectorAll('link[href*="/atom/series/"],link[href*="/rss/series/"]')) {
            const m = link.href.match(/\/(?:atom|rss)\/series\/([0-9]+)/); if (m) linked.add(m[1]);
          }
          if (linked.size) return [...linked];
          for (const root of [document.documentElement, document.body]) {
            if (!root) continue;
            for (const attr of ['data-giga_series','data-series-id','data-series_id']) {
              const v = root.getAttribute(attr); if (v) values.add(v);
            }
          }
          for (const element of document.querySelectorAll('[data-giga_series],[data-series-id],[data-series_id]'))
            for (const attr of ['data-giga_series','data-series-id','data-series_id']) { const v=element.getAttribute(attr); if(v) values.add(v); }
          return [...values].filter(v => /^\d+$/.test(String(v)));
        }"""
    ), timeout=3)
    ids = {str(value) for value in value if str(value).isdigit()}
    if len(ids) != 1:
        raise DiscoveryIncompleteError("Comic DAYS series identity was missing or ambiguous")
    return ids.pop()


async def fetch_comicdays_atom(page: Page, series_id: str, *, free_only: bool) -> list[dict[str, str | None]]:
    url = f"https://comic-days.com/atom/series/{series_id}"
    if free_only:
        url += "?free_only=1"
    try:
        response = await page.request.get(url, timeout=15_000, fail_on_status_code=False)
        if response.status != 200:
            raise DiscoveryIncompleteError(f"Comic DAYS Atom returned HTTP {response.status}")
        body = await asyncio.wait_for(response.body(), timeout=5)
    except (PlaywrightTimeoutError, TimeoutError) as exc:
        raise DiscoveryIncompleteError("Comic DAYS Atom request timed out") from exc
    return parse_atom_entries(body, expected_series_id=series_id)


async def fetch_comicdays_listing_total(page: Page, series_id: str, episode_id: str) -> int:
    """Validate Atom completeness against the site's bounded pagination count."""
    query = urlencode({"type": "episode", "aggregate_id": series_id, "readable_product_id": episode_id})
    try:
        response = await page.request.get(f"https://comic-days.com/api/viewer/readable_product_pagination_information?{query}", timeout=10_000, fail_on_status_code=False)
        if response.status != 200:
            raise DiscoveryIncompleteError("Comic DAYS pagination total was unavailable")
        body = await asyncio.wait_for(response.body(), timeout=5)
    except (PlaywrightTimeoutError, TimeoutError) as exc:
        raise DiscoveryIncompleteError("Comic DAYS pagination request timed out") from exc
    if len(body) > 100_000:
        raise DiscoveryIncompleteError("Comic DAYS pagination response exceeded the body limit")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DiscoveryIncompleteError("Comic DAYS pagination response was invalid") from exc
    values: set[int] = set()
    def visit(value: object) -> None:
        if isinstance(value, dict):
            for key in ("readable_products_count", "total", "total_count"):
                candidate = value.get(key)
                if isinstance(candidate, int) and candidate >= 0: values.add(candidate)
            for child in value.values(): visit(child)
        elif isinstance(value, list):
            for child in value: visit(child)
    visit(payload)
    if len(values) != 1:
        raise DiscoveryIncompleteError("Comic DAYS pagination total was missing or ambiguous")
    return values.pop()


class ComicDaysDiscoveryAdapter(DiscoveryAdapter):
    """Yield the full official listing while marking only free entries eligible."""

    async def iter_records(self, page: Page, target: WatchlistTarget, mode: DiscoveryMode) -> AsyncIterator[DiscoveredRecord]:
        del mode
        target_id = parse_comicdays_episode_url(target.url)
        if target_id is None or target.discovery_scope is not None:
            raise DiscoveryIncompleteError("Comic DAYS requires an unbounded canonical episode target")
        try:
            await page.goto(canonical_comicdays_episode_url(target.url), wait_until="domcontentloaded", timeout=15_000)
        except (PlaywrightTimeoutError, TimeoutError) as exc:
            raise DiscoveryIncompleteError("Comic DAYS episode page did not load") from exc
        series_id = await _series_id_from_page(page)
        full_entries = await fetch_comicdays_atom(page, series_id, free_only=False)
        free_entries = await fetch_comicdays_atom(page, series_id, free_only=True)
        expected_total = await fetch_comicdays_listing_total(page, series_id, target_id)
        if len(full_entries) != expected_total:
            raise DiscoveryIncompleteError(f"Comic DAYS Atom count {len(full_entries)} disagreed with pagination total {expected_total}")
        full_ids = [str(entry["episode_id"]) for entry in full_entries]
        free_ids = {str(entry["episode_id"]) for entry in free_entries}
        if not free_ids.issubset(set(full_ids)):
            raise DiscoveryIncompleteError("Comic DAYS free feed contained an unknown episode")
        if [item_id for item_id in full_ids if item_id in free_ids] != [str(entry["episode_id"]) for entry in free_entries]:
            raise DiscoveryIncompleteError("Comic DAYS free feed order disagreed with the full feed")
        if not any(entry["episode_id"] == target_id for entry in free_entries):
            raise DiscoveryIncompleteError("Target episode is not currently in the official free feed")
        now = datetime.now(JST)
        title_locator = page.locator(".series-header-title,[class*='series-header-title']")
        author_locator = page.locator(".series-header-author,[class*='series-header-author']")
        title = None
        author = None
        if await title_locator.count() == 1:
            title = " ".join((await title_locator.inner_text(timeout=2_000)).split()) or None
        if await author_locator.count() == 1:
            author = " ".join((await author_locator.inner_text(timeout=2_000)).split()) or None
        for entry in full_entries:
            label = entry.get("title")
            order = None
            if label:
                normalized_label = unicodedata.normalize("NFKC", label)
                match = ORDER_LABEL.match(normalized_label)
                order = str(int(match["number"])) if match else None
            yield DiscoveredRecord(
                item=DiscoveredItem(canonical_title=title, author=author, kind="episode", order_key=order, order_label=label),
                source=DiscoveredSource(
                    external_id=str(entry["episode_id"]), url=str(entry["url"]),
                    access_mode="free" if str(entry["episode_id"]) in free_ids else "unknown",
                    available=True, access_checked_at=now, last_seen_at=now, published_at=None,
                ),
            )
