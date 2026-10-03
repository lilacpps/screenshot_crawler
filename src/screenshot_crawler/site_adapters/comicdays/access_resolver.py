"""Comic DAYS site-owned, read-only Work Ticket candidate resolver."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from screenshot_crawler.batch.models import BatchCandidate
from screenshot_crawler.site_adapters.base import AccessResourceResolution
from screenshot_crawler.site_adapters.comicdays.discovery import (
    _series_id_from_page,
    canonical_comicdays_episode_url,
    comicdays_access_observation,
    parse_comicdays_episode_url,
)
from screenshot_crawler.site_adapters.comicdays.live_access import (
    COMICDAYS_LIVE_ACCESS_TIMEOUT_MS,
    ComicDaysLiveAccessError,
    observe_comicdays_listing,
)


def _supported_ticket_rental_term(row: dict[str, object]) -> bool:
    """Accept only the observed 72-hour Comic DAYS ticket contract."""

    status = row.get("status")
    term = status.get("rental_term") if isinstance(status, dict) else None
    return isinstance(term, int) and not isinstance(term, bool) and term == 72


def _candidate_episode(candidate: BatchCandidate) -> str | None:
    external_id = str(getattr(candidate, "external_id", "") or "")
    locator = str(getattr(candidate, "locator", "") or "")
    parsed = parse_comicdays_episode_url(locator)
    if not external_id or parsed != external_id:
        return None
    return parsed


async def resolve_comicdays_work_ticket_candidates(
    page: Page,
    candidates: Sequence[BatchCandidate],
    *,
    timeout_ms: int = COMICDAYS_LIVE_ACCESS_TIMEOUT_MS,
) -> AccessResourceResolution:
    """Choose at most one current ticket candidate per Catalog work.

    Catalog order is retained inside each group.  The function only navigates
    and reads first-party state; it never exposes or clicks an access control.
    """

    groups: dict[int | str, list[BatchCandidate]] = defaultdict(list)
    skipped: list[tuple[int, str]] = []
    for candidate in candidates:
        source_id = int(candidate.source_id)
        if candidate.site != "comicdays" or candidate.quota_resource != "work_ticket":
            skipped.append((source_id, "unsupported_access_resource"))
            continue
        if candidate.access_strategy != "quota":
            skipped.append((source_id, "not_quota_candidate"))
            continue
        episode = _candidate_episode(candidate)
        if episode is None or candidate.work_id is None:
            skipped.append((source_id, "work_ticket_target_not_in_catalog"))
            continue
        group_key = candidate.work_id
        groups[group_key].append(candidate)

    selected: list[int] = []
    deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
    observed_native_series: set[str] = set()
    for group in groups.values():
        remaining = int((deadline - asyncio.get_running_loop().time()) * 1000)
        if remaining <= 0:
            skipped.extend((int(candidate.source_id), "work_ticket_observation_timeout") for candidate in group)
            continue
        representative = group[0]
        try:
            await page.goto(
                canonical_comicdays_episode_url(representative.locator),
                wait_until="domcontentloaded",
                timeout=remaining,
            )
            series_id = await _series_id_from_page(page)
            if series_id in observed_native_series:
                skipped.extend(
                    (int(candidate.source_id), "work_ticket_native_work_already_observed")
                    for candidate in group
                )
                continue
            observed_native_series.add(series_id)
            listing_remaining = int((deadline - asyncio.get_running_loop().time()) * 1000)
            if listing_remaining <= 0:
                raise TimeoutError("Comic DAYS resolver listing observation exceeded its time bound")
            listing = await asyncio.wait_for(
                observe_comicdays_listing(
                    page, series_id=series_id, episode_id=_candidate_episode(representative) or "",
                    timeout_ms=listing_remaining,
                ),
                timeout=listing_remaining / 1000,
            )
        except (PlaywrightTimeoutError, TimeoutError, ComicDaysLiveAccessError, ValueError) as exc:
            reason = "work_ticket_unavailable" if isinstance(exc, ComicDaysLiveAccessError) else "work_ticket_observation_failed"
            skipped.extend((int(candidate.source_id), reason) for candidate in group)
            continue
        if not listing.ticket.is_charged:
            skipped.extend((int(candidate.source_id), "work_ticket_cooldown") for candidate in group)
            continue
        chosen: BatchCandidate | None = None
        for candidate in group:
            episode = _candidate_episode(candidate)
            if episode is None:
                continue
            row = next((row for row in listing.rows if str(row.get("readable_product_id")) == episode), None)
            if row is None:
                continue
            mode = None
            expiry = None
            try:
                mode, expiry, _observed = comicdays_access_observation(
                    row, free=episode in listing.free_ids, now=datetime.now(UTC)
                )
            except Exception:  # noqa: BLE001 - malformed native state skips safely
                mode = None
            if mode == "quota" and expiry is None:
                if not _supported_ticket_rental_term(row):
                    skipped.append((int(candidate.source_id), "work_ticket_unsupported_rental_term"))
                    continue
                chosen = candidate
                break
        if chosen is None:
            already_skipped = {source_id for source_id, _reason in skipped}
            skipped.extend(
                (int(candidate.source_id), "work_ticket_target_not_in_catalog")
                for candidate in group
                if int(candidate.source_id) not in already_skipped
            )
            continue
        selected.append(int(chosen.source_id))
        skipped.extend(
            (int(candidate.source_id), "work_ticket_candidate_not_selected")
            for candidate in group
            if candidate.source_id != chosen.source_id
        )
    return AccessResourceResolution(tuple(selected), tuple(skipped))


__all__ = ["resolve_comicdays_work_ticket_candidates"]
