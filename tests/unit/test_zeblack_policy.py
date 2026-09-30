from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from screenshot_crawler.batch import BatchPlanner
from screenshot_crawler.catalog import (
    CatalogService,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.site_policies import (
    SitePolicyRegistry,
    ZeblackSitePolicy,
)

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=JST)


@pytest.mark.parametrize(
    ("access_mode", "eligible", "strategy", "reason"),
    [
        ("free", True, "direct", "free"),
        ("quota", True, "quota", "work_ticket_candidate"),
        ("paid", False, None, "paid"),
        ("unknown", False, None, "unknown"),
        ("owned", False, None, "owned_not_verified"),
    ],
)
def test_zeblack_policy_access_mapping(
    access_mode: str,
    eligible: bool,
    strategy: str | None,
    reason: str,
) -> None:
    decision = ZeblackSitePolicy().evaluate(
        SimpleNamespace(access_mode=access_mode, available=True),
        now=NOW,
        quota_available=None,
    )
    assert (decision.eligible, decision.access_strategy, decision.reason) == (
        eligible,
        strategy,
        reason,
    )


def test_zeblack_policy_quota_is_work_ticket_without_local_cap_or_cooldown() -> None:
    policy = ZeblackSitePolicy()
    decision = policy.evaluate(
        SimpleNamespace(access_mode="quota", available=True, access_granted_until=None),
        now=NOW,
        quota_available=None,
    )

    assert decision.consumes_quota is True
    assert decision.quota_resource == "work_ticket"
    assert decision.quota_scope == "work"
    assert decision.quota_limit is None
    assert decision.quota_commit_mode == "after_observed_consumption"
    assert policy.available_quota((), NOW) is None
    assert policy.resource_state_scope("work_ticket") is None
    assert policy.access_grant_until(NOW) == NOW + timedelta(hours=71)
    assert policy.grant_only_skip_reason(
        resource="work_ticket",
        last_consumed_at=NOW,
        now=NOW,
        cooldown_hours=23,
    ) is None


def test_zeblack_policy_active_rental_is_direct() -> None:
    decision = ZeblackSitePolicy().evaluate(
        SimpleNamespace(
            access_mode="quota",
            available=True,
            access_granted_until=(NOW + timedelta(hours=1)).isoformat(),
        ),
        now=NOW,
        quota_available=None,
    )
    assert (decision.eligible, decision.access_strategy, decision.reason) == (
        True,
        "direct",
        "active_rental",
    )
    assert decision.consumes_quota is False
    assert ZeblackSitePolicy().defer_quota_access_to_grant_phase() is True


def test_zeblack_policy_supports_only_work_ticket() -> None:
    policy = ZeblackSitePolicy()
    assert policy.supported_access_resources() == ("work_ticket",)
    assert policy.ordered_access_resource_passes() == ("work_ticket",)
    assert policy.grant_only_supported_access_resources() == ("work_ticket",)
    policy.validate_access_resource("work_ticket")
    policy.validate_grant_only_resource("work_ticket")
    with pytest.raises(Exception, match="Unsupported access resource"):
        policy.validate_access_resource("point")
    with pytest.raises(Exception, match="Grant-only access resource"):
        policy.validate_grant_only_resource("coin")


def test_zeblack_planner_keeps_multiple_quota_candidates_oldest_first(
    tmp_path: Path,
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key="zeblack-work", title="Zeblack"))
    for order in ("30", "17", "27", "18"):
        item = catalog.create_item(
            ItemInput(order_key=order, order_label=f"#{order}"),
            work_id=work.id,
        )
        source = catalog.create_source(
            SourceInput(
                site="zeblack",
                external_id=order,
                access_mode="quota",
                available=True,
            ),
            item_id=item.id,
        )
        catalog.create_source_target(
            SourceTargetInput(
                backend="web",
                locator=(
                    "https://zebrack-comic.shueisha.co.jp/title/5123/"
                    f"chapter/{order}/viewer"
                ),
            ),
            source_id=source.id,
        )

    policies = SitePolicyRegistry()
    policies.register("zeblack", ZeblackSitePolicy)
    plan = BatchPlanner(catalog, policies).plan(site="zeblack", now=NOW)

    assert [candidate.metadata["order"] for candidate in plan.candidates] == [
        "#17",
        "#18",
        "#27",
        "#30",
    ]
    assert len(plan.candidates) == 4
    assert all(candidate.quota_limit is None for candidate in plan.candidates)
    assert all(candidate.quota_resource == "work_ticket" for candidate in plan.candidates)
    assert plan.skipped == []
