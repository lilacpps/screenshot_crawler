from __future__ import annotations

import pytest

from screenshot_crawler.batch import BatchCandidate
from screenshot_crawler.site_adapters.base import AccessResourceResolution
from screenshot_crawler.site_adapters.zeblack.access_resolver import (
    resolve_zeblack_work_ticket_candidates,
)
from screenshot_crawler.site_adapters.zeblack.discovery_protobuf import (
    ConsumptionStatus,
    ZeblackChapterV3,
)
from screenshot_crawler.site_adapters.zeblack.live_access import ZeblackChapterListSnapshot


def _candidate(source_id: int, chapter_id: str, *, work_id: int = 1) -> BatchCandidate:
    return BatchCandidate(
        item_id=source_id,
        source_id=source_id,
        target_id=source_id,
        site="zeblack",
        backend="web",
        target_key="default",
        locator=(
            "https://zebrack-comic.shueisha.co.jp/title/5123/"
            f"chapter/{chapter_id}/viewer"
        ),
        access_strategy="quota",
        access_mode="quota",
        consumes_quota=True,
        quota_resource="work_ticket",
        external_id=chapter_id,
        work_id=work_id,
    )


def _chapter(chapter_id: str, status: int) -> ZeblackChapterV3:
    return ZeblackChapterV3(
        chapter_id=chapter_id,
        title_id="5123",
        main_name=f"#{chapter_id}",
        remaining_rental_time=None,
        status_value=status,
        price=None,
    )


@pytest.mark.asyncio
async def test_resolver_uses_one_snapshot_and_selects_only_exact_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def observe(_page: object, *, title_id: str, timeout_ms: int) -> ZeblackChapterListSnapshot:
        nonlocal calls
        calls += 1
        assert (title_id, timeout_ms) == ("5123", 1234)
        return ZeblackChapterListSnapshot(
            title_id="5123",
            chapters=(_chapter("77", int(ConsumptionStatus.TICKET_AVAILABLE)),),
        )

    monkeypatch.setattr(
        "screenshot_crawler.site_adapters.zeblack.access_resolver.observe_zeblack_chapter_list",
        observe,
    )
    candidates = [_candidate(index, str(index)) for index in range(1, 101)]
    candidates[-1] = _candidate(100, "77")

    result = await resolve_zeblack_work_ticket_candidates(
        object(), candidates, timeout_ms=1234
    )

    assert isinstance(result, AccessResourceResolution)
    assert calls == 1
    assert result.selected_source_ids == (100,)
    assert 99 == len(result.skipped_source_reasons)
    assert all(source_id != 100 for source_id, _reason in result.skipped_source_reasons)


@pytest.mark.asyncio
async def test_resolver_does_not_select_completed_or_missing_catalog_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def observe(_page: object, **_kwargs: object) -> ZeblackChapterListSnapshot:
        return ZeblackChapterListSnapshot(
            title_id="5123",
            chapters=(_chapter("900", int(ConsumptionStatus.TICKET_AVAILABLE)),),
        )

    monkeypatch.setattr(
        "screenshot_crawler.site_adapters.zeblack.access_resolver.observe_zeblack_chapter_list",
        observe,
    )
    result = await resolve_zeblack_work_ticket_candidates(
        object(), [_candidate(1, "901")]
    )
    assert result.selected_source_ids == ()
    assert result.skipped_source_reasons == ((1, "work_ticket_target_not_in_catalog"),)


@pytest.mark.asyncio
async def test_resolver_skips_live_completed_target_but_selects_pending_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def observe(_page: object, **_kwargs: object) -> ZeblackChapterListSnapshot:
        return ZeblackChapterListSnapshot(
            title_id="5123",
            chapters=(
                _chapter("900", int(ConsumptionStatus.TICKET_AVAILABLE)),
                _chapter("901", int(ConsumptionStatus.TICKET_AVAILABLE)),
            ),
        )

    monkeypatch.setattr(
        "screenshot_crawler.site_adapters.zeblack.access_resolver.observe_zeblack_chapter_list",
        observe,
    )
    result = await resolve_zeblack_work_ticket_candidates(
        object(), [_candidate(2, "901")]
    )
    assert result.selected_source_ids == (2,)


@pytest.mark.asyncio
async def test_resolver_returns_expected_unavailable_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def observe(_page: object, **_kwargs: object) -> ZeblackChapterListSnapshot:
        return ZeblackChapterListSnapshot(title_id="5123", chapters=())

    monkeypatch.setattr(
        "screenshot_crawler.site_adapters.zeblack.access_resolver.observe_zeblack_chapter_list",
        observe,
    )
    result = await resolve_zeblack_work_ticket_candidates(
        object(), [_candidate(1, "901"), _candidate(2, "902")]
    )
    assert result.selected_source_ids == ()
    assert result.skipped_source_reasons == (
        (1, "work_ticket_unavailable"),
        (2, "work_ticket_unavailable"),
    )

