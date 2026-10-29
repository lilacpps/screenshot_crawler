from __future__ import annotations

from dataclasses import replace

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


@pytest.mark.asyncio
@pytest.mark.parametrize("older_available", [False, True])
@pytest.mark.parametrize("restored", [False, True])
async def test_resolver_recovers_only_pending_pool_and_hands_off_final_snapshot(
    monkeypatch, older_available, restored,
) -> None:
    older = _chapter("1", int(ConsumptionStatus.TICKET_AVAILABLE if older_available
                               else ConsumptionStatus.FREE))
    initial = ZeblackChapterListSnapshot("5123", (
        older, _chapter("2", int(ConsumptionStatus.POINT)),
    ))
    final = ZeblackChapterListSnapshot("5123", (
        older, _chapter("2", int(ConsumptionStatus.TICKET_AVAILABLE if restored
                               else ConsumptionStatus.POINT)),
    ))
    calls = []

    async def observe(*_args, **_kwargs):
        return initial

    async def recover(page, snapshot, candidate_ids, **kwargs):
        calls.append((snapshot, candidate_ids, kwargs))
        return final, "work_ticket_unavailable_after_reread"

    monkeypatch.setattr(
        "screenshot_crawler.site_adapters.zeblack.access_resolver.observe_zeblack_chapter_list",
        observe,
    )
    monkeypatch.setattr(
        "screenshot_crawler.site_adapters.zeblack.recovery.recover_work_ticket", recover,
    )
    snapshots = {}
    result = await resolve_zeblack_work_ticket_candidates(
        object(), [_candidate(22, "2")], selected_snapshots=snapshots,
        page_turn_delay_ms=234, blocked_external_ids=frozenset({"7"}),
    )
    assert len(calls) == 1
    assert calls[0][0] is initial
    assert calls[0][1] == frozenset({"2"})
    assert calls[0][2]["page_turn_delay_ms"] == 234
    assert calls[0][2]["blocked_external_ids"] == frozenset({"7"})
    assert result.selected_source_ids == ((22,) if restored else ())
    if restored:
        assert snapshots[22] is final
    else:
        assert snapshots == {}
        assert result.skipped_source_reasons == ((22, "work_ticket_unavailable_after_reread"),)


@pytest.mark.parametrize("status,remaining,allowed,reason", [
    (ConsumptionStatus.FREE, None, True, None),
    (ConsumptionStatus.RENTAL, 10000, True, None),
    (ConsumptionStatus.RENTAL, 0, False, "requires_access"),
    (ConsumptionStatus.RENTAL, None, False, "requires_access"),
    (ConsumptionStatus.RENTAL, 185, False, "requires_access"),
    (ConsumptionStatus.POINT, None, False, "requires_access"),
    (ConsumptionStatus.TICKET_AVAILABLE, None, False, "requires_access"),
    (ConsumptionStatus.TICKET_UNAVAILABLE, None, False, "requires_access"),
    (ConsumptionStatus.COIN, None, False, "paid"),
    (ConsumptionStatus.TICKET_UNAVAILABLE_COIN_ONLY, None, False, "paid"),
    (99, None, False, "requires_access"),
])
def test_prerequisite_never_acquires_expired_or_paid_access(status, remaining, allowed, reason):
    from screenshot_crawler.site_adapters.zeblack.recovery import predecessor_skip_reason

    chapter = replace(_chapter("1", int(status)), remaining_rental_time=remaining)
    result = predecessor_skip_reason(chapter, safe_seconds=185)
    assert (result is None) is allowed
    if reason:
        assert reason in result


def test_predecessor_uses_site_adjacency_and_excludes_active_rental_candidates():
    from screenshot_crawler.site_adapters.zeblack.recovery import predecessor_for_candidates

    chapters = (
        _chapter("500", int(ConsumptionStatus.FREE)),
        replace(_chapter("90", int(ConsumptionStatus.RENTAL)), remaining_rental_time=1000),
        _chapter("7", int(ConsumptionStatus.COIN)),
        _chapter("2", int(ConsumptionStatus.POINT)),
    )
    assert predecessor_for_candidates(chapters, frozenset({"90", "2"})) is chapters[2]
    assert predecessor_for_candidates(chapters, frozenset({"90"})) is None
    assert predecessor_for_candidates(chapters[3:], frozenset({"2"})) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [ConsumptionStatus.FREE, ConsumptionStatus.RENTAL,
                                  ConsumptionStatus.COIN, ConsumptionStatus.TICKET_UNAVAILABLE_COIN_ONLY])
async def test_resolver_does_not_prepare_when_candidates_are_already_accessible_or_paid(
    monkeypatch, status,
):
    async def observe(*_args, **_kwargs):
        return ZeblackChapterListSnapshot("5123", (
            replace(_chapter("2", int(status)), remaining_rental_time=10000),
        ))

    async def forbidden(*_args, **_kwargs):
        pytest.fail("Paid/active rental/free candidates must not start prerequisite recovery")

    monkeypatch.setattr(
        "screenshot_crawler.site_adapters.zeblack.access_resolver.observe_zeblack_chapter_list",
        observe,
    )
    monkeypatch.setattr(
        "screenshot_crawler.site_adapters.zeblack.recovery.recover_work_ticket", forbidden,
    )
    result = await resolve_zeblack_work_ticket_candidates(object(), [_candidate(2, "2")])
    assert result.selected_source_ids == ()

