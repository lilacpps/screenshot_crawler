"""Repeated Batch entry must stay cheap without accepting stale candidates."""

from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

import screenshot_crawler.batch.executor as executor_module
from screenshot_crawler.batch import BatchExecutionError, BatchExecutor, BatchPlanner
from screenshot_crawler.catalog import CatalogService, ItemInput, SourceInput, SourceTargetInput
from screenshot_crawler.maintenance.source_identity import SourceIdentityMaintenance
from screenshot_crawler.site_adapters.base import AccessResourceResolution
from screenshot_crawler.site_adapters.registry import AdapterRegistry
from screenshot_crawler.site_policies import MangaOneSitePolicy
from tests.unit.test_batch_executor import (
    NOW,
    FakeAdapter,
    ImmediateStopGuard,
    add_candidate,
    make_executor,
)


def _append_candidate(catalog, first, *, label="Second", position=None):
    item = catalog.create_item(ItemInput(order_label=label), work_id=first.work_id)
    source = catalog.create_source(
        SourceInput(site=first.site, external_id=f"chapter-{item.id}",
                    access_mode=first.access_mode, display_position=position),
        item_id=item.id,
    )
    target = catalog.create_source_target(
        SourceTargetInput(backend="web", locator=f"https://example.invalid/{item.id}"),
        source_id=source.id,
    )
    return replace(first, item_id=item.id, source_id=source.id, target_id=target.id,
                   locator=target.locator, external_id=source.external_id,
                   metadata={**first.metadata, "order": label},
                   artifact_prefix=f"{position:03d}" if position else None)


def _spy_naming(monkeypatch, catalog):
    naming = Mock(wraps=executor_module.build_work_archive_position_plan)
    monkeypatch.setattr(executor_module, "build_work_archive_position_plan", naming)
    read_work = Mock(wraps=catalog.read_work_items_and_sources)
    monkeypatch.setattr(catalog, "read_work_items_and_sources", read_work)
    monkeypatch.setattr(catalog, "read_works_items_sources_and_targets", Mock(
        side_effect=AssertionError("Executor must not reread the entire Catalog"),
    ))
    return naming, read_work


async def test_normal_batch_reuses_naming_after_previous_item_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    first = add_candidate(catalog, access_mode="free")
    second = _append_candidate(catalog, first)
    executor = make_executor(catalog)
    naming, read_work = _spy_naming(monkeypatch, catalog)
    for index, candidate in enumerate((first, second)):
        await executor.execute_candidate(
            object(), candidate, now=NOW, output_root=tmp_path / "batch",
            library_dir=tmp_path / f"Books-{index}",
        )
        assert catalog.get_item(candidate.item_id).status == "completed"
    assert naming.call_count == 1
    assert read_work.call_count == 2  # Fresh Work rows before each async entry.
    assert len(catalog.list_artifacts()) == 2


async def test_resolver_shares_one_work_read_for_the_candidate_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    first = replace(add_candidate(catalog, access_mode="quota"), quota_resource="work_ticket")
    candidates = [first, *(_append_candidate(catalog, first, label=str(i)) for i in range(20))]
    executor = make_executor(catalog)
    naming, read_work = _spy_naming(monkeypatch, catalog)

    resolver_calls = []

    class Adapter(FakeAdapter):
        def get_access_profile(self):
            return None

        async def resolve_access_resource_candidates(self, _page, pool, _resource, **_kwargs):
            resolver_calls.append(pool)
            assert tuple(candidates) == pool
            return AccessResourceResolution(selected_source_ids=(pool[0].source_id,))

    monkeypatch.setattr(executor.adapters, "create", lambda _site: Adapter())
    monkeypatch.setattr(executor_module.AccessGuard, "from_profile",
                        lambda **_kwargs: ImmediateStopGuard(None))
    for _ in range(2):
        async with executor.prepare_access_resource_candidates(
            object(), candidates, "work_ticket",
        ) as prepared:
            assert prepared.resolution.selected_source_ids == (first.source_id,)
    assert naming.call_count == 1
    assert read_work.call_count == 2  # A new snapshot on every public operation.
    with pytest.raises(BatchExecutionError, match="target.locator"):
        async with executor.prepare_access_resource_candidates(
            object(), [first, replace(candidates[1], locator="https://foreign.invalid/")],
            "work_ticket",
        ):
            pytest.fail("A forged candidate reached the resolver after cache reuse")
    assert len(resolver_calls) == 2
    assert catalog.list_crawl_runs() == []


@pytest.mark.parametrize("output_mode", ["capture", "grant_only"])
@pytest.mark.parametrize("change", ["position", "label", "collision", "watchlist", "work"])
def test_warm_naming_cache_rejects_changed_inputs(
    tmp_path: Path, output_mode: str, change: str,
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    first = add_candidate(catalog, access_mode="free")
    second = _append_candidate(catalog, first)
    executor = make_executor(catalog)
    policy = MangaOneSitePolicy()
    executor._validate_candidate(first, policy, NOW, output_mode=output_mode)
    if change == "position":
        with catalog._connection() as connection:
            connection.execute("UPDATE sources SET display_position=9 WHERE id=?", (first.source_id,))
    elif change == "label":
        catalog.update_item_metadata(first.item_id, order_label="Changed")
    elif change == "collision":
        catalog.update_item_metadata(second.item_id, order_label=first.metadata["order"])
    elif change == "watchlist":
        assert executor.watchlist is not None
        executor.watchlist.remove(executor.watchlist.list_targets()[0].key)
    else:
        with catalog._connection() as connection:
            connection.execute("UPDATE works SET title='Changed' WHERE id=?", (first.work_id,))
    with pytest.raises(BatchExecutionError):
        executor._validate_candidate(first, policy, NOW, output_mode=output_mode)


def test_work_numbering_refreshes_for_cross_site_sibling_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    first = add_candidate(catalog, access_mode="free", display_position=1)
    second = _append_candidate(catalog, first, position=2)
    executor = make_executor(catalog)
    watchlist = executor.watchlist
    assert watchlist is not None
    target = watchlist.list_targets()[0]
    watchlist.path.write_text(watchlist.path.read_text(encoding="utf-8").replace(
        "enabled: true", "enabled: true\n  archive_order: 2",
    ), encoding="utf-8")
    watchlist.add(key="other-site", work_key=target.work_key, site="bookwalker",
                  url="https://example.invalid/books", label="Books", archive_order=1)
    # All statuses/access modes reserve a number, including another site's paid row.
    sibling_item = catalog.create_item(ItemInput(status="completed"), work_id=first.work_id)
    sibling = catalog.create_source(
        SourceInput(site="bookwalker", external_id="book", discovery_key="other-site",
                    access_mode="paid", display_position=1), item_id=sibling_item.id,
    )
    plan = BatchPlanner(catalog, executor.policies, watchlist=watchlist).plan(site=first.site, now=NOW)
    candidates = {row.source_id: row for row in plan.candidates}
    executor = BatchExecutor(catalog, executor.policies, AdapterRegistry(), watchlist=watchlist)
    naming, _read_work = _spy_naming(monkeypatch, catalog)
    executor._require_candidate_scope(candidates[second.source_id], check_output_paths=False)
    assert candidates[second.source_id].artifact_prefix == "003"
    with catalog._connection() as connection:
        connection.execute("UPDATE sources SET acquisition_enabled=0 WHERE id=?", (sibling.id,))
    with pytest.raises(BatchExecutionError, match="archive prefix"):
        executor._require_candidate_scope(candidates[second.source_id], check_output_paths=False)
    assert naming.call_count == 2


def test_identity_change_rejects_batch_candidate_with_old_current_id(
    tmp_path: Path,
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    candidate = add_candidate(catalog, access_mode="free")
    executor = make_executor(catalog)
    maintenance = SourceIdentityMaintenance(catalog)
    plan = maintenance.plan(
        site=candidate.site,
        work_key="work-free",
        old_external_id=candidate.external_id,
        new_external_id="episode-renumbered",
        new_locator="https://example.invalid/episode-renumbered",
        reason="synthetic identity proof",
    )
    maintenance.apply(plan)

    with pytest.raises(BatchExecutionError, match="external_id"):
        executor._require_candidate_scope(candidate, check_output_paths=False)
