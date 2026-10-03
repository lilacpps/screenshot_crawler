"""Comic DAYS Atom Discovery with a full listing and free-subset authority."""

from __future__ import annotations

import asyncio
import json
import math
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta, timezone
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
MAX_LISTING_BODY = 500_000
MAX_LISTING_PAGES = 100


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


def _required_mapping(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise DiscoveryIncompleteError(f"Comic DAYS listing row missing {name} object")
    return value


def _finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _parse_observed_timestamp(value: object, *, name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise DiscoveryIncompleteError(f"Comic DAYS {name} was missing")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise DiscoveryIncompleteError(f"Comic DAYS {name} was invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DiscoveryIncompleteError(f"Comic DAYS {name} was timezone-naive")
    return parsed.astimezone(UTC)


def comicdays_access_observation(
    row: dict[str, object], *, free: bool, now: datetime
) -> tuple[str, datetime | None, bool]:
    """Classify one first-party readable-product row.

    The final boolean says whether this observation is authoritative enough
    to clear an older Catalog grant expiry.
    """
    product_id = row.get("readable_product_id")
    if not isinstance(product_id, (str, int)) or not str(product_id).isdigit():
        raise DiscoveryIncompleteError("Comic DAYS listing row had an invalid episode id")
    purchase = _required_mapping(row.get("purchase_info"), "purchase_info")
    status = _required_mapping(row.get("status"), "status")
    required_purchase = {
        "can_read", "is_free", "has_rented_via_ticket", "rentable_via_ticket",
        "unavailable", "has_purchased", "has_rented_via_point",
    }
    required_status = {"is_support_ticket", "rental_price", "rental_end_at", "buy_price", "rental_term"}
    if not required_purchase.issubset(purchase) or not required_status.issubset(status):
        raise DiscoveryIncompleteError("Comic DAYS listing row omitted a relevant access flag")
    can_read = purchase.get("can_read")
    is_free = purchase.get("is_free")
    has_rented = purchase.get("has_rented_via_ticket")
    rentable = purchase.get("rentable_via_ticket")
    is_support_ticket = status.get("is_support_ticket")
    rental_end = status.get("rental_end_at")
    if purchase.get("unavailable") is True:
        raise DiscoveryIncompleteError("Comic DAYS listing row was unavailable")
    if purchase.get("has_purchased") is True or purchase.get("has_rented_via_point") is True:
        raise DiscoveryIncompleteError("Comic DAYS listing row had a conflicting ownership state")
    boolean_values = (
        can_read, is_free, has_rented, rentable,
        purchase.get("unavailable"), purchase.get("has_purchased"),
        purchase.get("has_rented_via_point"), is_support_ticket,
    )
    if any(not isinstance(value, bool) for value in boolean_values):
        raise DiscoveryIncompleteError("Comic DAYS listing row had a malformed access flag")
    if free:
        free_ticket_metadata = (
            is_support_ticket is True
            and _finite_number(status.get("rental_price"))
            and float(status["rental_price"]) == 0
            and isinstance(status.get("rental_term"), int)
            and not isinstance(status.get("rental_term"), bool)
            and status.get("rental_term") == 72
        )
        plain_free_metadata = (
            is_support_ticket is False
            and status.get("rental_price") is None
            and status.get("rental_term") is None
        )
        if (
            can_read is not True or is_free is not True
            or has_rented is not False or rentable is not False
            or rental_end is not None or status.get("buy_price") is not None
            or not (plain_free_metadata or free_ticket_metadata)
        ):
            raise DiscoveryIncompleteError("Comic DAYS free feed disagreed with readable-product state")
        return "free", None, True
    if can_read is True and is_free is False and has_rented is True:
        if is_support_ticket is not True or rentable is True or rental_end is None:
            raise DiscoveryIncompleteError("Comic DAYS active rental state was contradictory")
        expiry = _parse_observed_timestamp(rental_end, name="rental_end_at")
        if expiry <= now.astimezone(UTC):
            return "unknown", None, False
        return "quota", expiry, True
    if (
        can_read is False and is_free is False and has_rented is False
        and rentable is True and is_support_ticket is True
    ):
        if rental_end is not None:
            raise DiscoveryIncompleteError("Comic DAYS locked ticket state had a rental expiry")
        if not _finite_number(status.get("rental_price")) or float(status["rental_price"]) != 0:
            raise DiscoveryIncompleteError("Comic DAYS ticket price was malformed")
        return "quota", None, True
    if (
        can_read is False and is_free is False and has_rented is False
        and rentable is False and is_support_ticket is False
    ):
        if rental_end is not None:
            raise DiscoveryIncompleteError("Comic DAYS paid state had a rental expiry")
        if not _finite_number(status.get("buy_price")) or float(status["buy_price"]) <= 0:
            raise DiscoveryIncompleteError("Comic DAYS paid price was malformed")
        return "paid", None, True
    return "unknown", None, False


async def fetch_comicdays_readable_products(
    page: Page, series_id: str, *, expected_total: int
) -> list[dict[str, object]]:
    """Fetch every first-party listing page and enforce completeness."""
    if expected_total < 1 or expected_total > MAX_LISTING_PAGES * 50:
        raise DiscoveryIncompleteError("Comic DAYS readable-product total was outside the supported bound")
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    page_count = (expected_total + 49) // 50
    for offset in range(0, page_count * 50, 50):
        query = urlencode({"type": "episode", "aggregate_id": series_id, "offset": offset, "limit": 50, "sort_order": "desc"})
        try:
            response = await page.request.get(
                f"https://comic-days.com/api/viewer/pagination_readable_products?{query}",
                timeout=15_000, fail_on_status_code=False,
            )
            if response.status != 200:
                raise DiscoveryIncompleteError("Comic DAYS readable-product page was unavailable")
            body = await asyncio.wait_for(response.body(), timeout=5)
        except (PlaywrightTimeoutError, TimeoutError) as exc:
            raise DiscoveryIncompleteError("Comic DAYS readable-product page timed out") from exc
        if len(body) > MAX_LISTING_BODY:
            raise DiscoveryIncompleteError("Comic DAYS readable-product page exceeded the body limit")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DiscoveryIncompleteError("Comic DAYS readable-product page was invalid") from exc
        page_rows = payload if isinstance(payload, list) else None
        if not isinstance(page_rows, list) or not page_rows or len(page_rows) > 50:
            raise DiscoveryIncompleteError("Comic DAYS readable-product page was invalid or empty")
        for row in page_rows:
            if not isinstance(row, dict):
                raise DiscoveryIncompleteError("Comic DAYS readable-product row was invalid")
            product_id = row.get("readable_product_id")
            key = str(product_id)
            if not key.isdigit() or key in seen:
                raise DiscoveryIncompleteError("Comic DAYS readable-product ids were invalid or duplicated")
            viewer_uri = row.get("viewer_uri")
            try:
                viewer_id = parse_comicdays_episode_url(viewer_uri) if isinstance(viewer_uri, str) else None
                canonical_viewer_uri = canonical_comicdays_episode_url(viewer_uri) if isinstance(viewer_uri, str) else None
            except ValueError as exc:
                raise DiscoveryIncompleteError("Comic DAYS readable-product viewer URI was invalid") from exc
            if canonical_viewer_uri != viewer_uri or viewer_id != key:
                raise DiscoveryIncompleteError("Comic DAYS readable-product viewer URI disagreed with its episode id")
            seen.add(key)
            rows.append(row)
        if len(rows) >= expected_total:
            break
    if len(rows) != expected_total:
        raise DiscoveryIncompleteError("Comic DAYS readable-product pages were incomplete")
    return rows


class ComicDaysDiscoveryAdapter(DiscoveryAdapter):
    """Yield a complete Atom listing classified by first-party access state."""

    async def iter_records(self, page: Page, target: WatchlistTarget, mode: DiscoveryMode) -> AsyncIterator[DiscoveredRecord]:
        del mode
        target_id = parse_comicdays_episode_url(target.url)
        if target_id is None or target.discovery_scope is not None:
            raise DiscoveryIncompleteError("Comic DAYS requires an unbounded canonical episode target")
        try:
            await page.goto(canonical_comicdays_episode_url(target.url), wait_until="domcontentloaded", timeout=15_000)
        except (PlaywrightTimeoutError, TimeoutError) as exc:
            raise DiscoveryIncompleteError("Comic DAYS episode page did not load") from exc
        if parse_comicdays_episode_url(page.url) != target_id:
            raise DiscoveryIncompleteError("Comic DAYS episode navigation changed the target identity")
        series_id = await _series_id_from_page(page)
        full_entries = await fetch_comicdays_atom(page, series_id, free_only=False)
        free_entries = await fetch_comicdays_atom(page, series_id, free_only=True)
        expected_total = await fetch_comicdays_listing_total(page, series_id, target_id)
        if len(full_entries) != expected_total:
            raise DiscoveryIncompleteError(f"Comic DAYS Atom count {len(full_entries)} disagreed with pagination total {expected_total}")
        full_ids = [str(entry["episode_id"]) for entry in full_entries]
        free_ids = {str(entry["episode_id"]) for entry in free_entries}
        if len(full_ids) != len(set(full_ids)):
            raise DiscoveryIncompleteError("Comic DAYS full Atom feed contained duplicate episodes")
        if not free_ids.issubset(set(full_ids)):
            raise DiscoveryIncompleteError("Comic DAYS free feed contained an unknown episode")
        if [item_id for item_id in full_ids if item_id in free_ids] != [str(entry["episode_id"]) for entry in free_entries]:
            raise DiscoveryIncompleteError("Comic DAYS free feed order disagreed with the full feed")
        if target_id not in set(full_ids):
            raise DiscoveryIncompleteError("Target episode was absent from the complete Comic DAYS listing")
        readable_rows = await fetch_comicdays_readable_products(
            page, series_id, expected_total=expected_total
        )
        readable_ids = [str(row.get("readable_product_id")) for row in readable_rows]
        if readable_ids != full_ids:
            raise DiscoveryIncompleteError("Comic DAYS readable-product order disagreed with Atom")
        if len(set(readable_ids)) != expected_total:
            raise DiscoveryIncompleteError("Comic DAYS readable-product ids were not unique")
        now = datetime.now(UTC)
        observations: dict[str, tuple[str, datetime | None, bool]] = {}
        for row in readable_rows:
            external_id = str(row["readable_product_id"])
            observations[external_id] = comicdays_access_observation(
                row, free=external_id in free_ids, now=now
            )
        now = datetime.now(JST)
        title_locator = page.locator(".series-header-title,[class*='series-header-title']")
        author_locator = page.locator(".series-header-author,[class*='series-header-author']")
        title = None
        author = None
        if await title_locator.count() == 1:
            title = " ".join((await title_locator.inner_text(timeout=2_000)).split()) or None
        if await author_locator.count() == 1:
            author = " ".join((await author_locator.inner_text(timeout=2_000)).split()) or None
        records: list[DiscoveredRecord] = []
        for entry in full_entries:
            label = entry.get("title")
            order = None
            if label:
                normalized_label = unicodedata.normalize("NFKC", label)
                match = ORDER_LABEL.match(normalized_label)
                order = str(int(match["number"])) if match else None
            access_mode, grant_until, grant_observed = observations[str(entry["episode_id"])]
            records.append(DiscoveredRecord(
                item=DiscoveredItem(canonical_title=title, author=author, kind="episode", order_key=order, order_label=label),
                source=DiscoveredSource(
                    external_id=str(entry["episode_id"]), url=str(entry["url"]),
                    access_mode=access_mode,
                    access_granted_until=grant_until,
                    access_granted_until_observed=grant_observed,
                    available=True, access_checked_at=now, last_seen_at=now, published_at=None,
                ),
            ))
        # Every network/listing invariant and every access classification must
        # pass before the first record is handed to the Catalog service.
        for record in records:
            yield record
