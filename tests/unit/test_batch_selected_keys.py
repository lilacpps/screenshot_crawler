from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from screenshot_crawler import cli
from screenshot_crawler.batch import BatchPlanner, BatchPlanningError
from screenshot_crawler.catalog import (
    CatalogService,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.site_policies import MangaOneSitePolicy, SitePolicyRegistry
from screenshot_crawler.watchlist.service import WatchlistService
from tests.helpers.acquisition_scope import synchronized_legacy_watchlist

NOW = datetime(2026, 9, 17, 15, 0, tzinfo=JST)


def _fixture(tmp_path: Path):
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work_a = catalog.create_work(WorkInput(work_key="work-a", title="A"))
    work_b = catalog.create_work(WorkInput(work_key="work-b", title="B"))
    sources = []
    for work, external in ((work_a, "a"), (work_b, "b")):
        item = catalog.create_item(ItemInput(item_title=external, order_label=external), work_id=work.id)
        source = catalog.create_source(
            SourceInput(site="mangaone", external_id=external, access_mode="free"),
            item_id=item.id,
        )
        catalog.create_source_target(
            SourceTargetInput(backend="web", locator=f"https://example.invalid/{external}"),
            source_id=source.id,
        )
        sources.append(source)
    watchlist = synchronized_legacy_watchlist(catalog)
    policies = SitePolicyRegistry()
    policies.register("mangaone", MangaOneSitePolicy)
    return catalog, watchlist, policies, [catalog.get_source(source.id) for source in sources]


def test_selected_keys_are_applied_before_candidate_selection(tmp_path: Path) -> None:
    catalog, watchlist, policies, sources = _fixture(tmp_path)
    planner = BatchPlanner(
        catalog, policies, watchlist=watchlist, library_dir=tmp_path / "Books"
    )
    all_plan = planner.plan(site="mangaone", now=NOW)
    selected = sources[0].discovery_key
    assert selected is not None
    selected_plan = planner.plan(site="mangaone", selected_keys=[selected], now=NOW)
    assert {candidate.source_id for candidate in selected_plan.candidates} == {sources[0].id}
    assert selected_plan.candidates[0].artifact_prefix == all_plan.candidates[0].artifact_prefix


def test_selected_quota_uses_unselected_site_state_but_allocates_selected_pool(
    tmp_path: Path,
) -> None:
    catalog, watchlist, _policies, sources = _fixture(tmp_path)
    for source in sources:
        catalog.update_source_external_state(
            "mangaone", source.external_id, access_mode="quota"
        )

    class OneSlotMangaOnePolicy(MangaOneSitePolicy):
        def available_quota(self, all_sources, now):
            base_available = super().available_quota(all_sources, now)
            used = MangaOneSitePolicy.quota_capacity - base_available
            return max(0, 1 - used)

    policies = SitePolicyRegistry()
    policies.register("mangaone", OneSlotMangaOnePolicy)
    planner = BatchPlanner(catalog, policies, watchlist=watchlist, library_dir=tmp_path / "Books")
    first_key = catalog.get_source(sources[0].id).discovery_key
    second_key = catalog.get_source(sources[1].id).discovery_key
    assert first_key is not None and second_key is not None

    selected_later = planner.plan(
        site="mangaone", selected_keys=[second_key], now=NOW
    )
    assert selected_later.quota_available == 1
    assert [candidate.source_id for candidate in selected_later.candidates] == [
        sources[1].id
    ]

    catalog.record_quota_access(
        sources[0].id,
        quota_started_at=NOW,
        access_granted_until=None,
    )
    quota_consumed_elsewhere = planner.plan(
        site="mangaone", selected_keys=[second_key], now=NOW
    )
    assert quota_consumed_elsewhere.quota_available == 0
    assert quota_consumed_elsewhere.candidates == []
    assert first_key != second_key


def test_subset_keeps_work_wide_archive_prefix_for_same_work_keys(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key="ordered-work", title="Ordered"))
    sources = []
    for order, key in (("01", "ordered-first"), ("02", "ordered-second")):
        item = catalog.create_item(
            ItemInput(item_title=f"Episode {order}", order_key=order), work_id=work.id
        )
        source = catalog.create_source(
            SourceInput(
                site="mangaone",
                external_id=f"ordered-{order}",
                discovery_key=key,
                access_mode="free",
                display_position=int(order),
            ),
            item_id=item.id,
        )
        catalog.create_source_target(
            SourceTargetInput(
                backend="web", locator=f"https://example.invalid/ordered/{order}"
            ),
            source_id=source.id,
        )
        sources.append(source)
    watchlist = WatchlistService(tmp_path / "watchlist.yaml")
    watchlist.add(
        key="ordered-first",
        work_key=work.work_key,
        site="mangaone",
        url="https://example.invalid/ordered/first",
        label="First",
        archive_order=1,
    )
    watchlist.add(
        key="ordered-second",
        work_key=work.work_key,
        site="mangaone",
        url="https://example.invalid/ordered/second",
        label="Second",
        archive_order=2,
    )
    policies = SitePolicyRegistry()
    policies.register("mangaone", MangaOneSitePolicy)
    planner = BatchPlanner(
        catalog, policies, watchlist=watchlist, library_dir=tmp_path / "Books"
    )
    full = planner.plan(site="mangaone", now=NOW)
    subset = planner.plan(
        site="mangaone", selected_keys=["ordered-second"], now=NOW
    )
    full_candidate = next(
        candidate for candidate in full.candidates if candidate.source_id == sources[1].id
    )
    subset_candidate = subset.candidates[0]
    assert subset_candidate.source_id == sources[1].id
    assert subset_candidate.artifact_prefix == full_candidate.artifact_prefix


def test_explicit_empty_selection_never_means_whole_site(tmp_path: Path) -> None:
    catalog, watchlist, policies, _sources = _fixture(tmp_path)
    planner = BatchPlanner(catalog, policies, watchlist=watchlist, library_dir=tmp_path / "Books")
    plan = planner.plan(site="mangaone", selected_keys=[], now=NOW)
    assert plan.candidates == []


def test_selector_unknown_and_wrong_site_are_rejected(tmp_path: Path) -> None:
    catalog, watchlist, policies, sources = _fixture(tmp_path)
    planner = BatchPlanner(catalog, policies, watchlist=watchlist, library_dir=tmp_path / "Books")
    try:
        planner.plan(site="mangaone", selected_keys=["unknown"], now=NOW)
    except BatchPlanningError as exc:
        assert "Unknown Watchlist key" in str(exc)
    else:
        raise AssertionError("unknown selector was accepted")
    assert sources[0].discovery_key is not None


def test_resolver_cannot_select_a_source_outside_selected_keys() -> None:
    candidates = [
        SimpleNamespace(source_id=1, discovery_key="selected", item_id=1),
        SimpleNamespace(source_id=2, discovery_key="other", item_id=2),
    ]
    resolution = SimpleNamespace(selected_source_ids=(2,), skipped_source_reasons=())
    with pytest.raises(BatchPlanningError, match="outside the selected keys"):
        cli._apply_access_resolution(
            candidates,
            resolution,
            metrics=None,
            selected_keys=frozenset({"selected"}),
        )
