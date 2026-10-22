from datetime import datetime, timedelta

import pytest

from screenshot_crawler.catalog import (
    CatalogService,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)
from screenshot_crawler.catalog.models import Source
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.site_policies import SitePolicyRegistry
from screenshot_crawler.site_policies.younganimal import YounganimalSitePolicy
from tests.helpers.acquisition_scope import synchronized_legacy_planner

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=JST)


def _source(
    access_mode: str,
    *,
    available: bool = True,
    quota_started_at: str | None = None,
    access_granted_until: str | None = None,
) -> Source:
    return Source(
        id=1,
        item_id=1,
        site="younganimal",
        external_id="aee4fa742b0fe:55889b8a851cb",
        discovery_key="younganimal-test",
        access_mode=access_mode,
        free_until=None,
        available=available,
        access_checked_at=None,
        last_seen_at=None,
        quota_started_at=quota_started_at,
        access_granted_until=access_granted_until,
        published_at=None,
        created_at="2026-10-10T12:00:00+09:00",
        updated_at="2026-10-10T12:00:00+09:00",
        display_position=4,
    )


def test_younganimal_policy_allows_only_available_free_directly() -> None:
    policy = YounganimalSitePolicy()
    source = _source("free")

    decision = policy.evaluate(source, now=NOW, quota_available=0)

    assert (decision.eligible, decision.access_strategy, decision.reason) == (
        True,
        "direct",
        "free",
    )
    assert decision.consumes_quota is False
    assert decision.quota_resource is None
    assert source.quota_started_at is None
    assert source.access_granted_until is None
    assert policy.available_quota((source,), NOW) is None
    assert policy.supported_access_resources() == ("work_ticket",)
    assert policy.ordered_access_resource_passes() == ("work_ticket",)
    assert policy.grant_only_supported_access_resources() == ("work_ticket",)
    assert policy.resource_state_scope("work_ticket") == "work"
    assert policy.access_grant_until(NOW) is None


@pytest.mark.parametrize(
    ("mode", "reason"),
    [
        ("unknown", "unknown"),
        ("owned", "owned_not_verified"),
        ("grant", "grant_not_supported"),
        ("rental", "rental_not_supported"),
    ],
)
def test_younganimal_policy_rejects_nonfree_modes_without_grant_shortcuts(
    mode: str, reason: str
) -> None:
    policy = YounganimalSitePolicy()
    source = _source(
        mode,
        quota_started_at="2026-10-10T12:00:00+09:00",
        access_granted_until="2099-10-11T12:00:00+09:00",
    )

    decision = policy.evaluate(source, now=NOW, quota_available=100)

    assert (decision.eligible, decision.access_strategy, decision.reason) == (
        False,
        None,
        reason,
    )
    assert decision.consumes_quota is False
    assert decision.quota_resource is None
    assert source.quota_started_at == "2026-10-10T12:00:00+09:00"
    assert source.access_granted_until == "2099-10-11T12:00:00+09:00"


def test_younganimal_policy_rejects_unavailable_free_and_accepts_work_ticket() -> None:
    policy = YounganimalSitePolicy()
    decision = policy.evaluate(_source("free", available=False), now=NOW, quota_available=None)

    assert (decision.eligible, decision.access_strategy, decision.reason) == (
        False,
        None,
        "unavailable",
    )
    policy.validate_access_resource("work_ticket")
    policy.validate_grant_only_resource("work_ticket")


def test_younganimal_quota_requires_exact_discovery_and_defers_commit_until_observed() -> None:
    policy = YounganimalSitePolicy()
    candidate = _source("quota", quota_started_at=None)

    decision = policy.evaluate(candidate, now=NOW, quota_available=0)

    assert (decision.eligible, decision.access_strategy, decision.reason) == (
        True,
        "quota",
        "work_ticket_candidate",
    )
    assert decision.consumes_quota is True
    assert decision.quota_resource == "work_ticket"
    assert decision.quota_scope == "work"
    assert decision.quota_limit == 1
    assert decision.quota_commit_mode == "after_observed_consumption"
    assert policy.evaluate(
        _source("quota", access_granted_until="2026-10-11T12:00:01+09:00"),
        now=NOW,
        quota_available=None,
    ).reason == "active_work_ticket_grant"


def test_younganimal_work_ticket_cooldown_is_at_least_23_hours() -> None:
    policy = YounganimalSitePolicy()
    consumed = NOW

    assert policy.grant_only_skip_reason(
        resource="work_ticket",
        last_consumed_at=consumed,
        now=consumed + timedelta(hours=22, minutes=59, seconds=59),
        cooldown_hours=None,
    ) == "work_ticket_cooldown"
    boundary = consumed + timedelta(hours=23)
    assert policy.grant_only_skip_reason(
        resource="work_ticket",
        last_consumed_at=consumed,
        now=boundary,
        cooldown_hours=0,
    ) is None
    assert policy.grant_only_retry_at(
        resource="work_ticket",
        last_consumed_at=consumed,
        cooldown_hours=24,
    ) == consumed + timedelta(hours=24)


def test_younganimal_planner_applies_one_ticket_per_work_in_catalog_order(
    tmp_path,
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    works = []
    for work_suffix in ("a", "b"):
        work = catalog.create_work(
            WorkInput(work_key=f"younganimal-{work_suffix}", title=f"Work {work_suffix}")
        )
        works.append(work)
        for position in (2, 1):
            episode_id = f"{position:013x}"
            item = catalog.create_item(
                ItemInput(item_title=f"Episode {position}", order_key=str(position)),
                work_id=work.id,
            )
            source = catalog.create_source(
                SourceInput(
                    site="younganimal",
                    external_id=f"{work_suffix * 13}:{episode_id}",
                    access_mode="quota",
                    available=True,
                    display_position=position,
                ),
                item_id=item.id,
            )
            catalog.create_source_target(
                SourceTargetInput(
                    backend="web",
                    locator=f"https://younganimal.com/episodes/{episode_id}",
                ),
                source_id=source.id,
            )

    policies = SitePolicyRegistry()
    policies.register("younganimal", YounganimalSitePolicy)
    plan = synchronized_legacy_planner(catalog, policies).plan(
        site="younganimal", now=NOW, quota_resource="work_ticket"
    )

    assert len(plan.candidates) == 2
    assert [candidate.work_id for candidate in plan.candidates] == [
        work.id for work in works
    ]
    assert [candidate.external_id.split(":", 1)[1] for candidate in plan.candidates] == [
        f"{1:013x}",
        f"{1:013x}",
    ]
    assert all(candidate.access_strategy == "quota" for candidate in plan.candidates)
    assert all(candidate.quota_resource == "work_ticket" for candidate in plan.candidates)
    assert all(candidate.quota_scope == "work" for candidate in plan.candidates)
    assert all(candidate.quota_limit == 1 for candidate in plan.candidates)
    assert len([row for row in plan.skipped if row.reason == "quota_work_limit"]) == 2


@pytest.mark.parametrize(
    ("grant", "available", "eligible", "reason"),
    [
        ("2026-10-11T12:00:01+09:00", True, True, "active_rental"),
        ("2026-10-11T12:00:00+09:00", True, False, "expired_rental"),
        ("2026-10-10T12:00:00+09:00", True, False, "expired_rental"),
        (None, True, False, "paid"),
        ("invalid", True, False, "invalid_rental"),
        ("2099-10-11T12:00:00", True, False, "invalid_rental"),
        ("2099-10-11T12:00:00+09:00", False, False, "unavailable"),
    ],
)
def test_younganimal_policy_selects_only_available_unexpired_rentals(
    grant, available, eligible, reason
) -> None:
    source = _source("paid", available=available, access_granted_until=grant)
    decision = YounganimalSitePolicy().evaluate(source, now=NOW, quota_available=0)
    assert (decision.eligible, decision.reason) == (eligible, reason)
    assert decision.access_strategy == ("direct" if eligible else None)
    assert not decision.consumes_quota
    assert decision.quota_resource is None
    assert source.quota_started_at is None
