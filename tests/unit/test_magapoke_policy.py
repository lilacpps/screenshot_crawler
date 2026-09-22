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
        ("quota", True, "quota", "work_ticket_candidate", True),
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
        ("2026-09-22T15:00:00+09:00", True, "work_ticket_candidate"),
        (None, True, "work_ticket_candidate"),
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
    expected_strategy = "direct" if reason == "active_rental" else "quota"
    assert decision.access_strategy == expected_strategy
    assert decision.consumes_quota is (grant in {"2026-09-22T15:00:00+09:00", None})


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


def test_magapoke_batch_plan_contains_direct_then_work_ticket_candidates(tmp_path: Path) -> None:
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
        ("quota", "quota", "work_ticket_candidate", True),
    ]
    assert {skipped.reason for skipped in plan.skipped} == {
        "paid",
        "unknown",
    }


def test_work_ticket_plan_limits_each_work_to_oldest_published_source(
    tmp_path: Path,
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work_items: dict[str, list[tuple[int, str]]] = {}
    for work_key, entries in (
        ("A", [("2026-09-10", "A old"), ("2026-09-20", "A newer"), ("2026-09-30", "A newest")]),
        ("B", [("2026-09-11", "B old"), ("2026-09-21", "B newer")]),
        ("C", [("2026-09-12", "C old"), ("2026-09-22", "C newer")]),
    ):
        work = catalog.create_work(WorkInput(work_key=f"work-{work_key}", title=work_key))
        work_items[work_key] = []
        for index, (published, label) in enumerate(entries):
            item = catalog.create_item(ItemInput(order_label=label), work_id=work.id)
            work_items[work_key].append((item.id, label))
            source = catalog.create_source(
                SourceInput(
                    site="magapoke",
                    external_id=f"{work_key}-{index}",
                    access_mode="quota",
                    published_at=f"{published}T00:00:00+09:00",
                    access_granted_until=(
                        "2026-09-23T00:00:00+09:00"
                        if work_key == "C" and label == "C newer"
                        else None
                    ),
                ),
                item_id=item.id,
            )
            catalog.create_source_target(
                SourceTargetInput(
                    backend="web",
                    locator=f"https://pocket.shonenmagazine.com/title/00695/episode/{source.external_id}",
                ),
                source_id=source.id,
            )

    policies = SitePolicyRegistry()
    policies.register("magapoke", MagapokeSitePolicy)
    plan = BatchPlanner(catalog, policies).plan(site="magapoke", now=NOW)

    direct = [candidate for candidate in plan.candidates if candidate.access_strategy == "direct"]
    quota = [candidate for candidate in plan.candidates if candidate.access_strategy == "quota"]
    labels_by_id = {item_id: label for entries in work_items.values() for item_id, label in entries}
    assert [labels_by_id[candidate.item_id] for candidate in direct] == ["C newer"]
    assert [labels_by_id[candidate.item_id] for candidate in quota] == [
        "A old", "B old", "C old"
    ]
    assert all(candidate.quota_resource == "work_ticket" for candidate in quota)
    assert all(candidate.quota_scope == "work" and candidate.quota_limit == 1 for candidate in quota)
    assert all(
        candidate.quota_commit_mode == "after_observed_consumption" for candidate in quota
    )
    assert sum(skip.reason == "quota_work_limit" for skip in plan.skipped) == 3


def test_premium_ticket_pass_groups_all_pending_episodes_by_oldest_work(
    tmp_path: Path,
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    for work_key, dates in (
        ("old-work", ["2026-09-10", "2026-09-12", "2026-09-15"]),
        ("new-work", ["2026-09-11", "2026-09-13"]),
    ):
        work = catalog.create_work(WorkInput(work_key=work_key, title=work_key))
        for index, published in enumerate(dates):
            source_id = f"{work_key}-{index}"
            item = catalog.create_item(
                ItemInput(order_label=source_id), work_id=work.id
            )
            source = catalog.create_source(
                SourceInput(
                    site="magapoke",
                    external_id=source_id,
                    access_mode="quota",
                    published_at=f"{published}T00:00:00+09:00",
                ),
                item_id=item.id,
            )
            catalog.create_source_target(
                SourceTargetInput(
                    backend="web",
                    locator=f"https://example.invalid/{source_id}",
                ),
                source_id=source.id,
            )
    policies = SitePolicyRegistry()
    policies.register("magapoke", MagapokeSitePolicy)
    plan = BatchPlanner(catalog, policies).plan(
        site="magapoke", now=NOW, quota_resource="premium_ticket"
    )

    assert [candidate.target_key for candidate in plan.candidates] == ["default"] * 5
    assert [candidate.locator.rsplit("/", 1)[-1] for candidate in plan.candidates] == [
        "old-work-0",
        "old-work-1",
        "old-work-2",
        "new-work-0",
        "new-work-1",
    ]
    assert all(candidate.quota_resource == "premium_ticket" for candidate in plan.candidates)
    assert all(candidate.quota_scope == "work" for candidate in plan.candidates)
    assert all(candidate.quota_limit is None for candidate in plan.candidates)
    assert all(candidate.reason == "premium_ticket_candidate" for candidate in plan.candidates)


def test_magapoke_policy_declares_premium_as_following_resource_pass() -> None:
    assert MagapokeSitePolicy().additional_quota_resources() == ("premium_ticket",)


def test_missing_published_at_sorts_after_dated_sources(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key="work", title="Work"))
    ordered_ids = []
    for index, published in enumerate((None, "2026-09-12T00:00:00+09:00")):
        item = catalog.create_item(ItemInput(order_label=f"Episode {index}"), work_id=work.id)
        ordered_ids.append(item.id)
        source = catalog.create_source(
            SourceInput(
                site="magapoke", external_id=str(index), access_mode="quota",
                published_at=published,
            ), item_id=item.id,
        )
        catalog.create_source_target(
            SourceTargetInput(backend="web", locator=f"https://example.invalid/{index}"),
            source_id=source.id,
        )
    policies = SitePolicyRegistry()
    policies.register("magapoke", MagapokeSitePolicy)
    plan = BatchPlanner(catalog, policies).plan(site="magapoke", now=NOW)
    assert len(plan.candidates) == 1
    assert plan.candidates[0].item_id == ordered_ids[1]
