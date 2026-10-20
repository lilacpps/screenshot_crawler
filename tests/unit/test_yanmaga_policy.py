from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from screenshot_crawler.batch import BatchPlanner
from screenshot_crawler.batch.models import BatchPlanningError
from screenshot_crawler.catalog import (
    CatalogService,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)
from screenshot_crawler.catalog.models import Source
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.site_policies import SitePolicyError, SitePolicyRegistry
from screenshot_crawler.site_policies.yanmaga import YanmagaSitePolicy

NOW = datetime(2026, 10, 20, 12, tzinfo=JST)
EXTERNAL_ID = "usagi:2de76848d607c9920f18147b763a6aec"


def _source(
    access_mode: str = "free",
    *,
    available: bool = True,
    site: str = "yanmaga",
    external_id: str = EXTERNAL_ID,
    free_until: datetime | str | None = None,
) -> Source:
    return Source(
        id=1,
        item_id=1,
        site=site,
        external_id=external_id,
        discovery_key="yanmaga-test",
        access_mode=access_mode,
        free_until=free_until,
        available=available,
        access_checked_at=None,
        last_seen_at=None,
        quota_started_at=None,
        access_granted_until=None,
        published_at=None,
        created_at="2026-10-20T12:00:00+09:00",
        updated_at="2026-10-20T12:00:00+09:00",
        display_position=1,
    )


@pytest.mark.parametrize(
    "free_until",
    [None, NOW + timedelta(seconds=1), "2026-10-20T12:00:01+09:00"],
    ids=("no-observed-expiry", "future-datetime", "future-iso"),
)
def test_yanmaga_policy_allows_available_free_direct_without_resource(
    free_until: datetime | str | None,
) -> None:
    policy = YanmagaSitePolicy()
    decision = policy.evaluate(
        _source(free_until=free_until), now=NOW, quota_available=0
    )

    assert (decision.eligible, decision.access_strategy, decision.reason) == (
        True,
        "direct",
        "free",
    )
    assert decision.consumes_quota is False
    assert decision.quota_resource is None
    assert policy.supported_access_resources() == ()
    assert policy.additional_access_resource_passes() == ()
    assert policy.grant_only_supported_access_resources() == ()


@pytest.mark.parametrize(
    ("free_until", "reason"),
    [
        (NOW - timedelta(seconds=1), "expired_free"),
        (NOW, "expired_free"),
        ("not-a-timestamp", "invalid_free_until"),
        ("2026-10-20T12:00:01", "invalid_free_until"),
        (datetime(2026, 10, 20, 12, 0, 1), "invalid_free_until"),  # noqa: DTZ001 - test naive Catalog data
        ("2026-10-20", "invalid_free_until"),
    ],
    ids=("past", "equal-now", "malformed", "naive-iso", "naive-datetime", "date-only"),
)
def test_yanmaga_policy_rejects_expired_or_unverifiable_expiry(
    free_until: datetime | str, reason: str
) -> None:
    decision = YanmagaSitePolicy().evaluate(
        _source(free_until=free_until), now=NOW, quota_available=None
    )

    assert (decision.eligible, decision.access_strategy, decision.reason) == (
        False,
        None,
        reason,
    )


@pytest.mark.parametrize(
    ("source", "reason"),
    [
        (_source(available=False), "unavailable"),
        (_source(site="comicdays"), "wrong_site"),
        (_source("unknown"), "unknown"),
        (_source("quota"), "quota_not_supported"),
        (_source("paid"), "paid"),
        (_source("owned"), "owned_not_verified"),
        (_source("grant"), "grant_not_supported"),
        (_source("rental"), "rental_not_supported"),
        (_source("other"), "unknown"),
        (_source(external_id="episode-without-work-id"), "invalid_episode_identity"),
        (_source(external_id="../work:2de76848d607c9920f18147b763a6aec"), "invalid_episode_identity"),
        (_source(external_id=f"usagi:{'A' * 32}"), "invalid_episode_identity"),
    ],
)
def test_yanmaga_policy_rejects_unsupported_or_malformed_catalog_state(
    source: Source, reason: str
) -> None:
    decision = YanmagaSitePolicy().evaluate(source, now=NOW, quota_available=100)

    assert (decision.eligible, decision.access_strategy, decision.reason) == (
        False,
        None,
        reason,
    )
    assert decision.consumes_quota is False
    assert decision.quota_resource is None


def test_yanmaga_policy_rejects_naive_clock_and_has_no_resource_pass() -> None:
    policy = YanmagaSitePolicy()
    with pytest.raises(SitePolicyError, match="now must be timezone-aware"):
        policy.evaluate(
            _source(),
            now=datetime(2026, 10, 20, 12),  # noqa: DTZ001 - must reject a naive planning clock
            quota_available=None,
        )
    with pytest.raises(SitePolicyError, match="Unsupported access resource"):
        policy.validate_access_resource("ticket")
    with pytest.raises(SitePolicyError, match="Grant-only access resource is not implemented"):
        policy.validate_grant_only_resource("ticket")


def test_yanmaga_planner_keeps_only_free_direct_and_preserves_positions(
    tmp_path: Path,
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key="yanmaga-usagi", title="Usagi work"))
    rows = [
        ("2de76848d607c9920f18147b763a6aec", "第1話", "free", True, 13, None),
        ("3de76848d607c9920f18147b763a6aed", "第2話", "free", True, 2,
         "2099-10-20T12:00:00+09:00"),
        ("4de76848d607c9920f18147b763a6aee", "初回無料", "unknown", True, 3, None),
        ("5de76848d607c9920f18147b763a6aef", "チケット", "quota", True, 4, None),
        ("6de76848d607c9920f18147b763a6af0", "有料", "paid", True, 5, None),
        ("7de76848d607c9920f18147b763a6af1", "購入済み", "owned", True, 6, None),
        ("8de76848d607c9920f18147b763a6af2", "Unavailable", "free", False, 7, None),
    ]
    for episode_id, label, access_mode, available, position, free_until in rows:
        item = catalog.create_item(
            ItemInput(kind="episode", order_label=label), work_id=work.id
        )
        source = catalog.create_source(
            SourceInput(
                site="yanmaga",
                external_id=f"usagi:{episode_id}",
                discovery_key="isolated-yanmaga",
                access_mode=access_mode,
                available=available,
                free_until=free_until,
                display_position=position,
            ),
            item_id=item.id,
        )
        catalog.create_source_target(
            SourceTargetInput(
                backend="web",
                locator=f"https://yanmaga.jp/comics/usagi/{episode_id}",
            ),
            source_id=source.id,
        )

    policies = SitePolicyRegistry()
    policies.register("yanmaga", YanmagaSitePolicy)
    plan = BatchPlanner(catalog, policies).plan(site="yanmaga", now=NOW)

    assert [candidate.external_id for candidate in plan.candidates] == [
        "usagi:2de76848d607c9920f18147b763a6aec",
        "usagi:3de76848d607c9920f18147b763a6aed",
    ]
    assert [candidate.access_strategy for candidate in plan.candidates] == [
        "direct",
        "direct",
    ]
    assert [candidate.artifact_prefix for candidate in plan.candidates] == ["013", "002"]
    assert all(not candidate.consumes_quota for candidate in plan.candidates)
    assert {entry.reason for entry in plan.skipped} >= {
        "unknown",
        "quota_not_supported",
        "paid",
        "owned_not_verified",
        "unavailable",
    }


def test_yanmaga_planner_fails_closed_on_malformed_free_expiry(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key="yanmaga-usagi", title="Usagi work"))
    item = catalog.create_item(ItemInput(kind="episode", order_label="第1話"), work_id=work.id)
    source = catalog.create_source(
        SourceInput(
            site="yanmaga",
            external_id=EXTERNAL_ID,
            access_mode="free",
            display_position=1,
        ),
        item_id=item.id,
    )
    catalog.create_source_target(
        SourceTargetInput(backend="web", locator="https://yanmaga.jp/comics/usagi/episode"),
        source_id=source.id,
    )
    with catalog._connection() as connection:
        connection.execute("UPDATE sources SET free_until = ? WHERE id = ?", ("malformed", source.id))
    policies = SitePolicyRegistry()
    policies.register("yanmaga", YanmagaSitePolicy)

    with pytest.raises(BatchPlanningError, match="free_until"):
        BatchPlanner(catalog, policies).plan(site="yanmaga", now=NOW)
