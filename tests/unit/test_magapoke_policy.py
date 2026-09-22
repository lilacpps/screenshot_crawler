from datetime import datetime
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
    MagapokeSitePolicy,
    SitePolicyError,
    SitePolicyRegistry,
)

NOW = datetime(2026, 9, 22, 15, 0, tzinfo=JST)


@pytest.mark.parametrize(
    ("access_mode", "eligible", "strategy", "reason", "consumes_quota"),
    [
        ("free", True, "direct", "free", False),
        ("quota", False, None, "quota_not_supported", False),
        ("paid", False, None, "paid", False),
        ("unknown", False, None, "unknown", False),
        ("owned", False, None, "owned_not_verified", False),
        ("other", False, None, "unsupported_access_mode", False),
    ],
)
def test_magapoke_policy_is_free_only(
    access_mode: str,
    eligible: bool,
    strategy: str | None,
    reason: str,
    consumes_quota: bool,
) -> None:
    source = SimpleNamespace(
        access_mode=access_mode, available=True, access_granted_until=None
    )

    decision = MagapokeSitePolicy().evaluate(
        source, now=NOW, quota_available=None  # type: ignore[arg-type]
    )

    assert (decision.eligible, decision.access_strategy, decision.reason) == (
        eligible,
        strategy,
        reason,
    )
    assert decision.consumes_quota is consumes_quota


def test_magapoke_policy_skips_unavailable_before_access_mode() -> None:
    source = SimpleNamespace(access_mode="free", available=False)

    decision = MagapokeSitePolicy().evaluate(
        source, now=NOW, quota_available=None  # type: ignore[arg-type]
    )

    assert decision.eligible is False
    assert decision.reason == "unavailable"


def test_magapoke_policy_rejects_naive_now() -> None:
    source = SimpleNamespace(access_mode="free", available=True, access_granted_until=None)

    with pytest.raises(SitePolicyError, match="timezone-aware"):
        MagapokeSitePolicy().evaluate(
            source,
            now=datetime(2026, 9, 22, 15, 0),  # noqa: DTZ001
            quota_available=None,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("grant", "eligible", "reason"),
    [
        ("2026-09-22T16:00:00+09:00", True, "active_rental"),
        ("2026-09-22T15:00:00+09:00", False, "quota_not_supported"),
        (None, False, "quota_not_supported"),
    ],
)
def test_magapoke_active_rental_policy_uses_direct_without_quota(
    grant: str | None, eligible: bool, reason: str
) -> None:
    source = SimpleNamespace(
        access_mode="quota", available=True, access_granted_until=grant
    )
    decision = MagapokeSitePolicy().evaluate(
        source, now=NOW, quota_available=None  # type: ignore[arg-type]
    )
    assert decision.eligible is eligible
    assert decision.reason == reason
    assert decision.access_strategy == ("direct" if eligible else None)
    assert decision.consumes_quota is False


@pytest.mark.parametrize(
    "grant",
    ["not-a-date", "2026-09-22T16:00:00", 123],
)
def test_magapoke_policy_rejects_invalid_grant_timestamps(grant: object) -> None:
    source = SimpleNamespace(
        access_mode="quota", available=True, access_granted_until=grant
    )
    with pytest.raises(SitePolicyError, match="access_granted_until"):
        MagapokeSitePolicy().evaluate(
            source, now=NOW, quota_available=None  # type: ignore[arg-type]
        )


def test_magapoke_batch_plan_contains_free_candidates_only(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    for access_mode in ("free", "quota", "quota-active", "paid", "unknown"):
        catalog_mode = "quota" if access_mode == "quota-active" else access_mode
        work = catalog.create_work(
            WorkInput(work_key=f"work-{access_mode}", title=access_mode)
        )
        item = catalog.create_item(ItemInput(order_label=access_mode), work_id=work.id)
        source = catalog.create_source(
            SourceInput(
                site="magapoke",
                external_id=access_mode,
                access_mode=catalog_mode,
                available=True,
                access_granted_until=(
                    "2026-09-22T16:00:00+09:00"
                    if access_mode == "quota-active"
                    else None
                ),
            ),
            item_id=item.id,
        )
        catalog.create_source_target(
            SourceTargetInput(
                backend="web",
                locator=f"https://pocket.shonenmagazine.com/title/00695/episode/{access_mode}",
            ),
            source_id=source.id,
        )

    policies = SitePolicyRegistry()
    policies.register("magapoke", MagapokeSitePolicy)
    plan = BatchPlanner(catalog, policies).plan(site="magapoke", now=NOW)

    assert [
        (candidate.access_mode, candidate.access_strategy, candidate.reason, candidate.consumes_quota)
        for candidate in plan.candidates
    ] == [
        ("free", "direct", "free", False),
        ("quota", "direct", "active_rental", False),
    ]
    assert {skipped.reason for skipped in plan.skipped} == {
        "quota_not_supported",
        "paid",
        "unknown",
    }
