from __future__ import annotations

from datetime import UTC, datetime

import pytest

from screenshot_crawler.batch.models import BatchCandidate
from screenshot_crawler.site_adapters.comicdays import access_resolver
from screenshot_crawler.site_adapters.comicdays.live_access import (
    ComicDaysListingState,
    ComicDaysTicketState,
)


class _Page:
    url = "about:blank"

    def __init__(self) -> None:
        self.goto_count = 0

    async def goto(self, url: str, **_kwargs: object) -> None:
        self.goto_count += 1
        self.url = url


def _row(episode_id: str) -> dict[str, object]:
    return {
        "readable_product_id": episode_id,
        "viewer_uri": f"https://comic-days.com/episode/{episode_id}",
        "rental_term": 72,
        "purchase_info": {
            "can_read": False,
            "is_free": False,
            "has_rented_via_ticket": False,
            "rentable_via_ticket": True,
            "unavailable": False,
            "has_purchased": False,
            "has_rented_via_point": False,
        },
        "status": {
            "is_support_ticket": True,
            "rental_price": 0,
            "rental_term": 72,
            "rental_end_at": None,
            "buy_price": None,
        },
    }


def _candidate(source_id: int, episode_id: str, *, work_id: int = 77) -> BatchCandidate:
    return BatchCandidate(
        item_id=source_id,
        source_id=source_id,
        target_id=source_id,
        site="comicdays",
        backend="comicdays",
        target_key=f"comicdays-{source_id}",
        locator=f"https://comic-days.com/episode/{episode_id}",
        access_strategy="quota",
        access_mode="quota",
        consumes_quota=True,
        quota_resource="work_ticket",
        quota_scope="work",
        quota_commit_mode="after_observed_consumption",
        external_id=episode_id,
        work_id=work_id,
    )


@pytest.mark.asyncio
async def test_resolver_validates_one_listing_and_keeps_catalog_order(monkeypatch: pytest.MonkeyPatch) -> None:
    page = _Page()
    listing = ComicDaysListingState(
        series_id="900",
        rows=(_row("2"), _row("1")),
        free_ids=frozenset(),
        ticket=ComicDaysTicketState("900", True, datetime(1999, 1, 1, tzinfo=UTC)),
    )
    calls = 0

    async def observe(*_args: object, **_kwargs: object) -> ComicDaysListingState:
        nonlocal calls
        calls += 1
        return listing

    async def series(*_args: object, **_kwargs: object) -> str:
        return "900"

    monkeypatch.setattr(access_resolver, "observe_comicdays_listing", observe)
    monkeypatch.setattr(access_resolver, "_series_id_from_page", series)
    result = await access_resolver.resolve_comicdays_work_ticket_candidates(
        page, (_candidate(10, "1"), _candidate(11, "2"))
    )
    assert result.selected_source_ids == (10,)
    assert (11, "work_ticket_candidate_not_selected") in result.skipped_source_reasons
    assert calls == 1
    assert page.goto_count == 1


@pytest.mark.asyncio
async def test_resolver_skips_work_ticket_cooldown_without_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _Page()
    listing = ComicDaysListingState(
        series_id="900", rows=(_row("1"),), free_ids=frozenset(),
        ticket=ComicDaysTicketState("900", False, datetime(2026, 10, 4, tzinfo=UTC)),
    )
    monkeypatch.setattr(access_resolver, "observe_comicdays_listing", lambda *_a, **_k: _completed(listing))
    monkeypatch.setattr(access_resolver, "_series_id_from_page", lambda *_a, **_k: _completed("900"))
    result = await access_resolver.resolve_comicdays_work_ticket_candidates(page, (_candidate(10, "1"),))
    assert result.selected_source_ids == ()
    assert result.skipped_source_reasons == ((10, "work_ticket_cooldown"),)


@pytest.mark.asyncio
async def test_resolver_deduplicates_same_native_work_across_catalog_work_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _Page()
    listing = ComicDaysListingState(
        series_id="900", rows=(_row("1"),), free_ids=frozenset(),
        ticket=ComicDaysTicketState("900", True, datetime(1999, 1, 1, tzinfo=UTC)),
    )
    monkeypatch.setattr(access_resolver, "observe_comicdays_listing", lambda *_a, **_k: _completed(listing))
    monkeypatch.setattr(access_resolver, "_series_id_from_page", lambda *_a, **_k: _completed("900"))
    result = await access_resolver.resolve_comicdays_work_ticket_candidates(
        page, (_candidate(10, "1", work_id=77), _candidate(11, "1", work_id=78))
    )
    assert result.selected_source_ids == (10,)
    assert (11, "work_ticket_native_work_already_observed") in result.skipped_source_reasons


@pytest.mark.asyncio
@pytest.mark.parametrize("term", [None, True, 71, "72"])
async def test_resolver_rejects_unverified_ticket_rental_term(
    monkeypatch: pytest.MonkeyPatch, term: object
) -> None:
    page = _Page()
    row = _row("1")
    status = row["status"]
    assert isinstance(status, dict)
    status["rental_term"] = term
    listing = ComicDaysListingState(
        series_id="900", rows=(row,), free_ids=frozenset(),
        ticket=ComicDaysTicketState("900", True, datetime(1999, 1, 1, tzinfo=UTC)),
    )
    monkeypatch.setattr(access_resolver, "observe_comicdays_listing", lambda *_a, **_k: _completed(listing))
    monkeypatch.setattr(access_resolver, "_series_id_from_page", lambda *_a, **_k: _completed("900"))
    result = await access_resolver.resolve_comicdays_work_ticket_candidates(page, (_candidate(10, "1"),))
    assert result.selected_source_ids == ()
    assert result.skipped_source_reasons == ((10, "work_ticket_unsupported_rental_term"),)


async def _completed(value):
    return value
