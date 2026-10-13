from __future__ import annotations

from datetime import datetime
from pathlib import Path

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
from screenshot_crawler.site_policies import (
    ComicFuzSitePolicy,
    SitePolicyError,
    SitePolicyRegistry,
)

NOW = datetime(2026, 10, 13, 12, tzinfo=JST)


def _source(
    access_mode: str = "free",
    *,
    available: bool = True,
    site: str = "comicfuz",
    free_until: str | None = None,
) -> Source:
    return Source(
        id=1,
        item_id=1,
        site=site,
        external_id="1970:80641",
        discovery_key="comicfuz-test",
        access_mode=access_mode,
        free_until=free_until,
        available=available,
        access_checked_at=None,
        last_seen_at=None,
        quota_started_at=None,
        access_granted_until=None,
        published_at=None,
        created_at="2026-10-13T12:00:00+09:00",
        updated_at="2026-10-13T12:00:00+09:00",
        display_position=3,
    )


def test_comicfuz_policy_selects_only_available_free_direct() -> None:
    decision = ComicFuzSitePolicy().evaluate(
        _source(), now=NOW, quota_available=0
    )

    assert (decision.eligible, decision.access_strategy, decision.reason) == (
        True,
        "direct",
        "free",
    )
    assert decision.consumes_quota is False
    assert decision.quota_resource is None


@pytest.mark.parametrize(
    ("source", "reason"),
    [
        (_source(available=False), "unavailable"),
        (_source("unknown"), "unknown"),
        (_source("quota"), "quota_not_supported"),
        (_source("paid"), "paid"),
        (_source("owned"), "owned_not_verified"),
        (_source("grant"), "grant_not_supported"),
        (_source("rental"), "rental_not_supported"),
        (_source("unexpected"), "unknown"),
        (_source(site="mangaone"), "wrong_site"),
    ],
)
def test_comicfuz_policy_rejects_unsupported_catalog_states(
    source: Source, reason: str
) -> None:
    decision = ComicFuzSitePolicy().evaluate(source, now=NOW, quota_available=100)

    assert (decision.eligible, decision.access_strategy, decision.reason) == (
        False,
        None,
        reason,
    )
    assert decision.consumes_quota is False
    assert decision.quota_resource is None


def test_comicfuz_policy_has_no_resource_or_grant_only_path() -> None:
    policy = ComicFuzSitePolicy()
    assert policy.supported_access_resources() == ()
    assert policy.ordered_access_resource_passes() == ()
    assert policy.additional_access_resource_passes() == ()
    assert policy.grant_only_supported_access_resources() == ()

    with pytest.raises(SitePolicyError, match="Unsupported access resource"):
        policy.validate_access_resource("ticket")
    with pytest.raises(SitePolicyError, match="Grant-only access resource is not implemented"):
        policy.validate_grant_only_resource("ticket")


def test_comicfuz_policy_requires_timezone_aware_now() -> None:
    with pytest.raises(SitePolicyError, match="now must be timezone-aware"):
        ComicFuzSitePolicy().evaluate(
            _source(), now=datetime(2026, 10, 13, 12),  # noqa: DTZ001 - test rejected naive clock
            quota_available=None,
        )


def test_comicfuz_planner_keeps_only_free_and_preserves_global_archive_positions(
    tmp_path: Path,
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(
        WorkInput(work_key="comicfuz:1970", title="Verified ComicFUZ Work")
    )
    rows = [
        ("80641", "第31話", "free", True, 3),
        ("80640", "第30話", "unknown", True, 2),
        ("80639", "第29話", "free", True, 1),
        ("80638", "第28話", "free", False, 4),
        ("80637", "第27話", "quota", True, 5),
        ("80636", "第26話", "paid", True, 6),
        ("80635", "第25話", "owned", True, 7),
    ]
    for chapter, label, mode, available, position in rows:
        item = catalog.create_item(
            ItemInput(kind="episode", order_label=label), work_id=work.id
        )
        source = catalog.create_source(
            SourceInput(
                site="comicfuz",
                external_id=f"1970:{chapter}",
                discovery_key="comicfuz-test",
                access_mode=mode,
                available=available,
                display_position=position,
            ),
            item_id=item.id,
        )
        catalog.create_source_target(
            SourceTargetInput(
                backend="web",
                locator=f"https://comic-fuz.com/manga/viewer/{chapter}",
            ),
            source_id=source.id,
        )

    policies = SitePolicyRegistry()
    policies.register("comicfuz", ComicFuzSitePolicy)
    plan = BatchPlanner(catalog, policies).plan(site="comicfuz", now=NOW)

    assert [candidate.external_id for candidate in plan.candidates] == [
        "1970:80641",
        "1970:80639",
    ]
    assert [candidate.access_strategy for candidate in plan.candidates] == [
        "direct",
        "direct",
    ]
    assert [candidate.artifact_prefix for candidate in plan.candidates] == ["003", "001"]
    assert [candidate.metadata for candidate in plan.candidates] == [
        {"title": "Verified ComicFUZ Work", "order": "第31話"},
        {"title": "Verified ComicFUZ Work", "order": "第29話"},
    ]
    skipped_reasons = {entry.reason for entry in plan.skipped}
    assert skipped_reasons >= {
        "unknown",
        "unavailable",
        "quota_not_supported",
        "paid",
        "owned_not_verified",
    }
