"""Comic DAYS account stock preselection; no episode-by-episode probing or use."""

import asyncio

from playwright.async_api import Page

from screenshot_crawler.core.errors import (
    AccessResourceUnavailableError,
    UnknownPageStateError,
    UnsupportedAccessStrategyError,
)
from screenshot_crawler.site_adapters.base import AccessResourceResolution
from screenshot_crawler.site_adapters.comicdays.discovery import (
    _series_id_from_page,
    canonical_comicdays_episode_url,
    fetch_comicdays_atom,
    parse_comicdays_episode_url,
)
from screenshot_crawler.site_adapters.comicdays.live_access import observe_comicdays_ticket

HOME_URL = "https://comic-days.com/"
HOME_SETTLE_MS = 3_000


class ComicDaysAlreadyAccessibleError(AccessResourceUnavailableError):
    """A selected Premium target became readable without any resource use."""

    def __init__(self) -> None:
        super().__init__("already_accessible")
        self.stop_work = False


async def resolve_ticket_candidates(
    page: Page, candidates: tuple[object, ...], resource: str, *, timeout_ms: int,
) -> AccessResourceResolution:
    if resource not in {"work_ticket", "premium_ticket"}:
        raise UnsupportedAccessStrategyError("Unsupported Comic DAYS ticket resource")
    if not candidates:
        return AccessResourceResolution()
    if (
        len({c.work_id for c in candidates}) != 1 or candidates[0].work_id is None
        or len({c.source_id for c in candidates}) != len(candidates)
        or any(
            c.site != "comicdays" or c.quota_resource != resource
            or c.access_strategy != "quota" or not c.consumes_quota
            or parse_comicdays_episode_url(c.locator) != c.external_id
            or canonical_comicdays_episode_url(c.locator) != c.locator
            for c in candidates
        )
    ):
        raise UnknownPageStateError("Comic DAYS stock selection requires one bound Work")
    # Work Ticket keeps its existing local cooldown and exact target entry.
    # It does not visit home, inspect Premium stock, or consume another resource.
    if resource == "work_ticket":
        return AccessResourceResolution(tuple(c.source_id for c in candidates))
    async with asyncio.timeout(timeout_ms / 1000):
        response = await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=timeout_ms)
        if response is None or response.status != 200 or page.url != HOME_URL:
            raise UnknownPageStateError("Comic DAYS daily ticket home was unavailable")
        await page.wait_for_timeout(HOME_SETTLE_MS)
        first = candidates[0]
        response = await page.goto(first.locator, wait_until="domcontentloaded", timeout=timeout_ms)
        if response is None or response.status != 200 or page.url != first.locator:
            raise UnknownPageStateError("Comic DAYS stock page identity changed")
        series = await _series_id_from_page(page)
        ticket = await observe_comicdays_ticket(page, series, timeout_ms=timeout_ms)
        count = ticket.event_ticket_count
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise UnknownPageStateError("Comic DAYS Premium balance is unknown")
        reason = "premium_ticket_stock_limit"
        limit = count
        if count == 0:
            reason = "premium_ticket_exhausted"
        elif not ticket.ticket_present or ticket.is_charged is not False:
            # Never force Premium ahead of the native Work Ticket path.
            if ticket.is_charged is not True:
                raise UnknownPageStateError("Comic DAYS Work Ticket readiness is unknown")
            reason, limit = "work_ticket_priority", 0
        if limit:
            feed = await fetch_comicdays_atom(page, series, free_only=False)
            ids = {entry["episode_id"] for entry in feed}
            if any(c.external_id not in ids for c in candidates):
                raise UnknownPageStateError("Comic DAYS stock pool crosses native series")
        return AccessResourceResolution(
            selected_source_ids=tuple(c.source_id for c in candidates[:limit]),
            skipped_source_reasons=tuple((c.source_id, reason) for c in candidates[limit:]),
            stop_resource_pass=count == 0,
        )
