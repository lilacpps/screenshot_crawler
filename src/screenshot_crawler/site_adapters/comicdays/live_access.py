"""Bounded, read-only Comic DAYS access observations.

This module owns the small amount of site-native state needed by the adapter
and resolver.  It deliberately contains no mutation request and never clicks
an access control.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from screenshot_crawler.discovery.service import DiscoveryIncompleteError
from screenshot_crawler.site_adapters.comicdays.discovery import (
    comicdays_access_observation,
    fetch_comicdays_atom,
    fetch_comicdays_listing_total,
    fetch_comicdays_readable_products,
    parse_comicdays_episode_url,
)

COMICDAYS_LIVE_ACCESS_TIMEOUT_MS = 15_000
MAX_GRAPHQL_BODY = 100_000
TICKET_QUERY = """
query Viewer_SeriesTicketQuery($id: String!) {
  userAccount { eventTicketCount }
  series(databaseId: $id) { ticket { isCharged chargedAt } }
}
"""


class ComicDaysLiveAccessError(RuntimeError):
    """Raised when a bounded live access observation is not authoritative."""


@dataclass(frozen=True, slots=True)
class ComicDaysTicketState:
    series_id: str
    is_charged: bool
    charged_at: datetime | None
    event_ticket_count: int | None = None


@dataclass(frozen=True, slots=True)
class ComicDaysLiveAccessState:
    series_id: str
    episode_id: str
    row: dict[str, object]
    access_mode: str
    grant_until: datetime | None
    grant_observed: bool
    ticket: ComicDaysTicketState


@dataclass(frozen=True, slots=True)
class ComicDaysListingState:
    """One complete Atom/readable-product observation for a series."""

    series_id: str
    rows: tuple[dict[str, object], ...]
    free_ids: frozenset[str]
    ticket: ComicDaysTicketState


async def observe_comicdays_ticket(
    page: Page,
    series_id: str,
    *,
    timeout_ms: int = COMICDAYS_LIVE_ACCESS_TIMEOUT_MS,
) -> ComicDaysTicketState:
    if not str(series_id).isdigit():
        raise ComicDaysLiveAccessError("Comic DAYS series identity is not numeric")
    if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or timeout_ms <= 0:
        raise ValueError("timeout_ms must be a positive integer")
    query_timeout = min(timeout_ms, 15_000)
    deadline = asyncio.get_running_loop().time() + query_timeout / 1000
    try:
        remaining = _remaining_ms(deadline)
        if remaining <= 0:
            raise ComicDaysLiveAccessError("Comic DAYS ticket query timed out")
        response = await page.request.post(
            "https://comic-days.com/graphql?opname=Viewer_SeriesTicketQuery",
            data={"query": TICKET_QUERY, "variables": {"id": str(series_id)}},
            headers={"Content-Type": "application/json"},
            timeout=remaining,
            fail_on_status_code=False,
        )
        if response.status != 200:
            raise ComicDaysLiveAccessError("Comic DAYS ticket query returned a non-200 status")
        remaining = _remaining_ms(deadline)
        if remaining <= 0:
            raise ComicDaysLiveAccessError("Comic DAYS ticket query timed out")
        body = await asyncio.wait_for(response.body(), timeout=remaining / 1000)
    except (PlaywrightTimeoutError, TimeoutError) as exc:
        raise ComicDaysLiveAccessError("Comic DAYS ticket query timed out") from exc
    if len(body) > MAX_GRAPHQL_BODY:
        raise ComicDaysLiveAccessError("Comic DAYS ticket query exceeded the body limit")
    try:
        payload = json.loads(body.decode("utf-8"))
        data = payload["data"]
        series = data["series"]
        ticket = series["ticket"]
        account = data["userAccount"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ComicDaysLiveAccessError("Comic DAYS ticket query had an invalid shape") from exc
    if not isinstance(ticket, dict) or not isinstance(account, dict):
        raise ComicDaysLiveAccessError("Comic DAYS ticket query omitted ticket state")
    is_charged = ticket.get("isCharged")
    if not isinstance(is_charged, bool):
        raise ComicDaysLiveAccessError("Comic DAYS ticket readiness was malformed")
    charged_at: datetime | None = None
    raw_charged_at = ticket.get("chargedAt")
    if raw_charged_at is not None:
        if not isinstance(raw_charged_at, str):
            raise ComicDaysLiveAccessError("Comic DAYS ticket chargedAt was malformed")
        try:
            charged_at = datetime.fromisoformat(raw_charged_at)
        except ValueError as exc:
            raise ComicDaysLiveAccessError("Comic DAYS ticket chargedAt was invalid") from exc
        if charged_at.tzinfo is None or charged_at.utcoffset() is None:
            raise ComicDaysLiveAccessError("Comic DAYS ticket chargedAt was timezone-naive")
        charged_at = charged_at.astimezone(UTC)
    count = account.get("eventTicketCount")
    if count is not None and (isinstance(count, bool) or not isinstance(count, int) or count < 0):
        raise ComicDaysLiveAccessError("Comic DAYS event ticket count was malformed")
    return ComicDaysTicketState(str(series_id), is_charged, charged_at, count)


async def observe_comicdays_live_access(
    page: Page,
    *,
    series_id: str,
    episode_id: str,
    timeout_ms: int = COMICDAYS_LIVE_ACCESS_TIMEOUT_MS,
) -> ComicDaysLiveAccessState:
    """Validate one complete listing and return the target's current state."""

    if not str(series_id).isdigit() or not str(episode_id).isdigit():
        raise ComicDaysLiveAccessError("Comic DAYS access identity is not numeric")
    current = parse_comicdays_episode_url(str(page.url))
    if current != str(episode_id):
        raise ComicDaysLiveAccessError("Comic DAYS page URL did not match the target episode")
    listing = await observe_comicdays_listing(page, series_id=series_id, episode_id=episode_id, timeout_ms=timeout_ms)
    try:
        row = next(row for row in listing.rows if str(row.get("readable_product_id")) == str(episode_id))
        mode, expiry, observed = comicdays_access_observation(
            row, free=str(episode_id) in listing.free_ids, now=datetime.now(UTC)
        )
    except (DiscoveryIncompleteError, StopIteration) as exc:
        raise ComicDaysLiveAccessError(str(exc)) from exc
    return ComicDaysLiveAccessState(str(series_id), str(episode_id), row, mode, expiry, observed, listing.ticket)


async def observe_comicdays_listing(
    page: Page,
    *,
    series_id: str,
    episode_id: str,
    timeout_ms: int = COMICDAYS_LIVE_ACCESS_TIMEOUT_MS,
) -> ComicDaysListingState:
    """Validate one complete listing and one work-level ticket query."""

    if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or timeout_ms <= 0:
        raise ValueError("timeout_ms must be a positive integer")
    deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
    current = parse_comicdays_episode_url(str(page.url))
    if current != str(episode_id):
        raise ComicDaysLiveAccessError("Comic DAYS page URL did not match the target episode")
    try:
        full = await _bounded_call(
            fetch_comicdays_atom(page, str(series_id), free_only=False), deadline
        )
        free = await _bounded_call(
            fetch_comicdays_atom(page, str(series_id), free_only=True), deadline
        )
        total = await _bounded_call(
            fetch_comicdays_listing_total(page, str(series_id), str(episode_id)), deadline
        )
        rows = await _bounded_call(
            fetch_comicdays_readable_products(page, str(series_id), expected_total=total), deadline
        )
        full_ids = [str(item["episode_id"]) for item in full]
        if len(full_ids) != total or len(set(full_ids)) != total:
            raise DiscoveryIncompleteError("Comic DAYS listing identity/count mismatch")
        row_ids = [str(item.get("readable_product_id")) for item in rows]
        if row_ids != full_ids:
            raise DiscoveryIncompleteError("Comic DAYS listing order disagreed with Atom")
        if str(episode_id) not in full_ids:
            raise DiscoveryIncompleteError("Comic DAYS target was absent from the complete listing")
        free_ids = {str(item["episode_id"]) for item in free}
        if not free_ids.issubset(set(full_ids)):
            raise DiscoveryIncompleteError("Comic DAYS free listing contained an unknown episode")
        if [item_id for item_id in full_ids if item_id in free_ids] != [str(item["episode_id"]) for item in free]:
            raise DiscoveryIncompleteError("Comic DAYS free listing order disagreed with Atom")
    except (DiscoveryIncompleteError, StopIteration) as exc:
        raise ComicDaysLiveAccessError(str(exc)) from exc
    remaining = _remaining_ms(deadline)
    if remaining <= 0:
        raise ComicDaysLiveAccessError("Comic DAYS listing observation exceeded its time bound")
    ticket = await _bounded_call(
        observe_comicdays_ticket(page, str(series_id), timeout_ms=remaining), deadline
    )
    return ComicDaysListingState(str(series_id), tuple(rows), frozenset(free_ids), ticket)


def _remaining_ms(deadline: float) -> int:
    return max(0, int((deadline - asyncio.get_running_loop().time()) * 1000))


async def _bounded_call(awaitable: Awaitable[Any], deadline: float) -> Any:
    remaining = _remaining_ms(deadline)
    if remaining <= 0:
        close = getattr(awaitable, "close", None)
        if callable(close):
            close()
        raise ComicDaysLiveAccessError("Comic DAYS listing observation exceeded its time bound")
    try:
        return await asyncio.wait_for(awaitable, timeout=remaining / 1000)
    except TimeoutError as exc:
        raise ComicDaysLiveAccessError("Comic DAYS listing observation exceeded its time bound") from exc


__all__ = [
    "COMICDAYS_LIVE_ACCESS_TIMEOUT_MS",
    "ComicDaysListingState",
    "ComicDaysLiveAccessError",
    "ComicDaysLiveAccessState",
    "ComicDaysTicketState",
    "observe_comicdays_listing",
    "observe_comicdays_live_access",
    "observe_comicdays_ticket",
]
