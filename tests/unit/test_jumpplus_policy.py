from datetime import datetime

import pytest

from screenshot_crawler.batch import BatchPlanner
from screenshot_crawler.catalog import (
    CatalogService,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)
from screenshot_crawler.catalog.models import Source
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.site_policies.base import SitePolicyError
from screenshot_crawler.site_policies.jumpplus import JumpPlusSitePolicy
from screenshot_crawler.site_policies.registry import SitePolicyRegistry

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=JST)


def source(
    *,
    access_mode: str,
    available: bool = True,
    access_granted_until: str | None = None,
) -> Source:
    return Source(
        id=1,
        item_id=1,
        site="jumpplus",
        external_id="episode-1",
        discovery_key="target",
        access_mode=access_mode,
        free_until=None,
        available=available,
        access_checked_at=None,
        last_seen_at=None,
        quota_started_at=None,
        access_granted_until=access_granted_until,
        published_at=None,
        created_at="2026-09-24T00:00:00+09:00",
        updated_at="2026-09-24T00:00:00+09:00",
    )


@pytest.mark.parametrize(
    ("access_mode", "reason"),
    [
        ("unknown", "unknown"),
        ("quota", "quota_not_supported"),
        ("owned", "owned_not_verified"),
    ],
)
def test_unsupported_access_modes_fail_closed(access_mode: str, reason: str) -> None:
    decision = JumpPlusSitePolicy().evaluate(source(access_mode=access_mode), now=NOW, quota_available=None)

    assert decision.eligible is False
    assert decision.access_strategy is None
    assert decision.reason == reason


def test_free_is_direct_without_quota() -> None:
    decision = JumpPlusSitePolicy().evaluate(source(access_mode="free"), now=NOW, quota_available=None)

    assert decision.eligible is True
    assert decision.access_strategy == "direct"
    assert decision.reason == "free"
    assert decision.consumes_quota is False


def test_active_manual_rental_is_direct_without_quota() -> None:
    decision = JumpPlusSitePolicy().evaluate(
        source(
            access_mode="paid",
            access_granted_until="2026-09-24T12:00:01+00:00",
        ),
        now=NOW,
        quota_available=None,
    )

    assert decision.eligible is True
    assert decision.access_strategy == "direct"
    assert decision.reason == "active_rental"
    assert decision.consumes_quota is False
    assert decision.quota_resource is None


@pytest.mark.parametrize(
    ("grant", "reason"),
    [
        (None, "paid"),
        ("2026-09-24T11:59:59+09:00", "expired_rental"),
        ("2026-09-24T12:00:00+09:00", "expired_rental"),
    ],
)
def test_paid_without_active_grant_is_skipped(grant: str | None, reason: str) -> None:
    decision = JumpPlusSitePolicy().evaluate(
        source(access_mode="paid", access_granted_until=grant),
        now=NOW,
        quota_available=None,
    )

    assert decision.eligible is False
    assert decision.reason == reason


def test_unavailable_wins_over_access_state() -> None:
    decision = JumpPlusSitePolicy().evaluate(
        source(access_mode="free", available=False),
        now=NOW,
        quota_available=None,
    )

    assert decision == decision.__class__(False, None, "unavailable")


@pytest.mark.parametrize(
    ("now", "message"),
    [
        (datetime(2026, 9, 24, 12, 0), "now must be timezone-aware"),  # noqa: DTZ001
    ],
)
def test_naive_now_is_rejected(now: datetime, message: str) -> None:
    with pytest.raises(SitePolicyError, match=message):
        JumpPlusSitePolicy().evaluate(source(access_mode="free"), now=now, quota_available=None)


def test_naive_grant_is_rejected() -> None:
    with pytest.raises(SitePolicyError, match="access_granted_until must be timezone-aware"):
        JumpPlusSitePolicy().evaluate(
            source(access_mode="paid", access_granted_until="2026-09-24T12:00:01"),
            now=NOW,
            quota_available=None,
        )


def test_invalid_grant_is_rejected() -> None:
    with pytest.raises(SitePolicyError, match="Invalid access_granted_until timestamp"):
        JumpPlusSitePolicy().evaluate(
            source(access_mode="paid", access_granted_until="not-a-timestamp"),
            now=NOW,
            quota_available=None,
        )


def test_batch_planner_selects_free_and_active_rental_only(tmp_path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    states = [
        ("free", "free", None),
        ("active", "paid", "2026-09-24T12:00:01+09:00"),
        ("paid", "paid", None),
        ("expired", "paid", "2026-09-24T11:59:59+09:00"),
        ("unknown", "unknown", None),
    ]
    for key, access_mode, grant in states:
        work = catalog.create_work(WorkInput(work_key=f"work-{key}", title=key))
        item = catalog.create_item(ItemInput(item_title=key), work_id=work.id)
        source_record = catalog.create_source(
            SourceInput(
                site="jumpplus",
                external_id=key,
                access_mode=access_mode,
                access_granted_until=grant,
            ),
            item_id=item.id,
        )
        catalog.create_source_target(
            SourceTargetInput(
                backend="web",
                locator=f"https://shonenjumpplus.com/episode/{key}",
            ),
            source_id=source_record.id,
        )

    registry = SitePolicyRegistry()
    registry.register("jumpplus", JumpPlusSitePolicy)
    plan = BatchPlanner(catalog, registry).plan(site="jumpplus", now=NOW)

    assert [candidate.reason for candidate in plan.candidates] == ["free", "active_rental"]
    assert all(candidate.access_strategy == "direct" for candidate in plan.candidates)
    assert {
        (skipped.source_id, skipped.reason)
        for skipped in plan.skipped
    } == {
        (3, "paid"),
        (4, "expired_rental"),
        (5, "unknown"),
    }
