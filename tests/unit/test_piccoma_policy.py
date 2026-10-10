from datetime import datetime, timedelta
from pathlib import Path

import pytest

from screenshot_crawler.batch import BatchPlanner, BatchPlanningError
from screenshot_crawler.catalog import (
    CatalogService,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)
from screenshot_crawler.catalog.models import Source
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.site_policies import PiccomaSitePolicy, SitePolicyError, SitePolicyRegistry

NOW = datetime(2026, 10, 9, 12, tzinfo=JST)


def _source(
    access_mode: str = "free",
    *,
    available: bool = True,
    access_granted_until: str | None = None,
) -> Source:
    return Source(
        id=1,
        item_id=1,
        site="piccoma",
        external_id="900:101",
        discovery_key="900",
        access_mode=access_mode,
        free_until=None,
        available=available,
        access_checked_at=None,
        last_seen_at=None,
        quota_started_at=None,
        access_granted_until=access_granted_until,
        published_at=None,
        created_at="2026-10-09T00:00:00+09:00",
        updated_at="2026-10-09T00:00:00+09:00",
        display_position=432,
    )


def _registry() -> SitePolicyRegistry:
    registry = SitePolicyRegistry()
    registry.register("piccoma", PiccomaSitePolicy)
    return registry


def test_piccoma_policy_allows_only_available_free_as_direct() -> None:
    decision = PiccomaSitePolicy().evaluate(
        _source(), now=NOW, quota_available=0
    )

    assert decision.eligible is True
    assert decision.access_strategy == "direct"
    assert decision.reason == "free"
    assert decision.consumes_quota is False
    assert decision.quota_resource is None


@pytest.mark.parametrize(
    ("mode", "grant_until"),
    [
        ("quota", None),
        ("quota", NOW.isoformat()),
        ("quota", (NOW - timedelta(hours=1)).isoformat()),
        ("paid", (NOW + timedelta(hours=1)).isoformat()),
        ("owned", None),
        ("grant", (NOW + timedelta(hours=1)).isoformat()),
        ("rental", (NOW + timedelta(hours=1)).isoformat()),
        ("unknown", None),
        ("unrecognized", None),
    ],
)
def test_piccoma_policy_rejects_unsupported_modes_and_inactive_grants(
    mode: str, grant_until: str | None
) -> None:
    decision = PiccomaSitePolicy().evaluate(
        _source(mode, access_granted_until=grant_until),
        now=NOW,
        quota_available=10,
    )

    assert decision.eligible is False
    assert decision.access_strategy is None
    assert decision.consumes_quota is False
    assert decision.quota_resource is None


@pytest.mark.parametrize("available", [True, False])
def test_piccoma_policy_allows_only_available_active_manual_grant(available: bool) -> None:
    decision = PiccomaSitePolicy().evaluate(
        _source("quota", available=available,
                access_granted_until=(NOW + timedelta(hours=1)).isoformat()),
        now=NOW, quota_available=0,
    )
    assert decision.eligible is available
    assert decision.access_strategy == ("direct" if available else None)
    assert decision.consumes_quota is False
    assert decision.quota_resource is None


@pytest.mark.parametrize("value", ["bad", "2026-10-10T12:00:00"])
def test_piccoma_policy_rejects_invalid_grant_timestamp(value: str) -> None:
    with pytest.raises(SitePolicyError):
        PiccomaSitePolicy().evaluate(
            _source("quota", access_granted_until=value), now=NOW, quota_available=0
        )


def test_piccoma_policy_rejects_unavailable_free_and_exposes_no_resource_paths() -> None:
    policy = PiccomaSitePolicy()
    decision = policy.evaluate(_source(available=False), now=NOW, quota_available=1)
    assert decision.eligible is False
    assert decision.reason == "unavailable"
    assert policy.supported_access_resources() == ()
    assert policy.ordered_access_resource_passes() == ()
    assert policy.additional_access_resource_passes() == ()
    assert policy.grant_only_supported_access_resources() == ()
    assert policy.resource_state_scope("work_ticket") is None
    with pytest.raises(SitePolicyError, match="Unsupported access resource"):
        policy.validate_access_resource("work_ticket")
    with pytest.raises(SitePolicyError, match="Grant-only access resource is not implemented"):
        policy.validate_grant_only_resource("work_ticket")


def test_piccoma_planner_keeps_free_and_active_grants_with_catalog_positions(
    tmp_path: Path,
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(
        WorkInput(
            work_key="caller-owned-opaque-work-key",
            title="Piccoma Series",
            author="Artist",
            genre="Manga",
        )
    )
    rows = [
        ("900:101", "free", True, 432, None),
        ("900:102", "free", True, 431, None),
        ("900:103", "free", False, 430, None),
        ("900:104", "quota", True, 429, (NOW + timedelta(hours=1)).isoformat()),
        ("900:105", "paid", True, 428, None),
        ("900:106", "owned", True, 427, None),
        ("900:107", "unknown", True, 426, None),
        ("900:108", "quota", True, 425, NOW.isoformat()),
        ("900:109", "quota", True, 424, None),
    ]
    for index, (external_id, mode, available, position, grant_until) in enumerate(rows):
        item = catalog.create_item(
            ItemInput(order_label=f"Episode {index + 1}"), work_id=work.id
        )
        source = catalog.create_source(
            SourceInput(
                site="piccoma",
                external_id=external_id,
                discovery_key="900",
                access_mode=mode,
                available=available,
                access_granted_until=grant_until,
                display_position=position,
            ),
            item_id=item.id,
        )
        catalog.create_source_target(
            SourceTargetInput(
                backend="web",
                locator=f"https://piccoma.com/web/viewer/900/{external_id.split(':')[1]}",
            ),
            source_id=source.id,
        )

    plan = BatchPlanner(catalog, _registry()).plan(site="piccoma", now=NOW)

    assert [candidate.external_id for candidate in plan.candidates] == [
        "900:101",
        "900:102",
        "900:104",
    ]
    assert [candidate.artifact_prefix for candidate in plan.candidates] == ["432", "431", "429"]
    assert [candidate.access_strategy for candidate in plan.candidates] == [
        "direct",
        "direct",
        "direct",
    ]
    assert [candidate.reason for candidate in plan.candidates] == [
        "free", "free", "active_manual_grant"
    ]
    assert all(candidate.consumes_quota is False for candidate in plan.candidates)
    assert all(candidate.quota_resource is None for candidate in plan.candidates)
    assert all(candidate.metadata == {
        "title": "Piccoma Series",
        "author": "Artist",
        "order": catalog.get_item(candidate.item_id).order_label,
        "genre": "Manga",
    } for candidate in plan.candidates)
    assert {skip.reason for skip in plan.skipped} >= {
        "unavailable",
        "unsupported_access_mode",
        "unknown",
        "no_active_manual_grant",
    }


def test_piccoma_planner_rejects_explicit_quota_resource(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    with pytest.raises(BatchPlanningError, match="Unsupported access resource"):
        BatchPlanner(catalog, _registry()).plan(
            site="piccoma", now=NOW, quota_resource="work_ticket"
        )
