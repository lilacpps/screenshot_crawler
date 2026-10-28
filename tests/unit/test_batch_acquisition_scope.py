from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from screenshot_crawler import cli
from screenshot_crawler.archive_order import (
    ArchiveOrderPlanningError,
    build_work_archive_position_plan,
)
from screenshot_crawler.batch import (
    BatchExecutionError,
    BatchExecutor,
    BatchPlanner,
    BatchPlanningError,
)
from screenshot_crawler.catalog import (
    CatalogService,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)
from screenshot_crawler.catalog.models import DiscoveryInventoryPosition
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.site_adapters.registry import AdapterRegistry
from screenshot_crawler.site_policies import (
    BookWalkerSitePolicy,
    MagapokeSitePolicy,
    MangaOneSitePolicy,
    SitePolicyRegistry,
    ZeblackSitePolicy,
)
from screenshot_crawler.watchlist.fingerprints import target_scope_fingerprint
from screenshot_crawler.watchlist.models import ArchiveSegment, DiscoveryScope, WatchlistTarget
from screenshot_crawler.watchlist.reconcile import ScopeReconciler
from screenshot_crawler.watchlist.service import WatchlistService

NOW = datetime(2026, 9, 17, 15, 0, tzinfo=JST)


def test_batch_provisional_order_accepts_missing_duplicate_and_removed_key_positions(
    tmp_path: Path,
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key="series", title="Series"))
    watchlist = WatchlistService(tmp_path / "watchlist.yaml")
    target = watchlist.add(
        key="current", work_key=work.work_key, site="mangaone",
        url="https://example.invalid/list", label="Series", archive_order=1,
    )
    sources = []
    for key, position in (("current", None), ("current", 2), ("current", 2), ("removed", 1)):
        item = catalog.create_item(ItemInput(), work_id=work.id)
        source = catalog.create_source(
            SourceInput(
                site="mangaone", external_id=f"episode-{item.id}", discovery_key=key,
                access_mode="free", display_position=position,
            ),
            item_id=item.id,
        )
        catalog.create_source_target(
            SourceTargetInput(backend="web", locator=f"https://example.invalid/{item.id}"),
            source_id=source.id,
        )
        sources.append(source)
    policies = SitePolicyRegistry()
    policies.register("mangaone", MangaOneSitePolicy)
    planner = BatchPlanner(catalog, policies, watchlist=watchlist)
    before = catalog.path.read_bytes()
    plan = planner.plan(site="mangaone", now=NOW)
    assert {row.source_id: row.artifact_prefix for row in plan.candidates} == {
        sources[1].id: "001", sources[2].id: "002",
        sources[0].id: "003", sources[3].id: "004",
    }
    executor = BatchExecutor(catalog, policies, AdapterRegistry(), watchlist=watchlist)
    for candidate in plan.candidates:
        executor._require_candidate_scope(candidate, check_output_paths=False)
    assert catalog.path.read_bytes() == before
    with pytest.raises(ArchiveOrderPlanningError):
        build_work_archive_position_plan(work, [target], catalog.list_items(), sources)


def test_archive_segments_assign_oldest_first_positions_across_keys(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key="segments", title="Segments"))
    watchlist = WatchlistService(tmp_path / "watchlist.yaml")
    first = watchlist.add(
        key="first", work_key=work.work_key, site="mangaone",
        url="https://example.invalid/first", label="First",
        archive_segments=(ArchiveSegment(order=1, end_external_id="a2"),),
    )
    second = watchlist.add(
        key="second", work_key=work.work_key, site="zeblack",
        url="https://example.invalid/second", label="Second",
        archive_segments=(ArchiveSegment(order=2),),
    )
    sources = []
    for key, site, external_id, position in (
        ("first", "mangaone", "a1", 1),
        ("first", "mangaone", "a2", 2),
        ("second", "zeblack", "b1", 1),
    ):
        item = catalog.create_item(ItemInput(), work_id=work.id)
        sources.append(
            catalog.create_source(
                SourceInput(
                    site=site, external_id=external_id, discovery_key=key,
                    access_mode="free", display_position=position,
                ),
                item_id=item.id,
            )
        )
    plan = build_work_archive_position_plan(
        work, [first, second], catalog.list_items(work_id=work.id), sources
    )
    assert plan is not None
    assert plan.ordered_source_ids == tuple(source.id for source in sources)
    assert plan.positions_by_source_id == {
        sources[0].id: 1, sources[1].id: 2, sources[2].id: 3,
    }


def test_archive_segments_reject_unplaced_or_disabled_boundary_source(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key="segments", title="Segments"))
    target = WatchlistTarget(
        key="first", work_key=work.work_key, site="mangaone",
        url="https://example.invalid/first", label="First",
        archive_segments=(ArchiveSegment(order=1, start_external_id="a2"),),
    )
    other = WatchlistTarget(
        key="second", work_key=work.work_key, site="zeblack",
        url="https://example.invalid/second", label="Second",
        archive_segments=(ArchiveSegment(order=2),),
    )
    item = catalog.create_item(ItemInput(), work_id=work.id)
    source = catalog.create_source(
        SourceInput(
            site="mangaone", external_id="a1", discovery_key="first",
            access_mode="free", display_position=1,
        ), item_id=item.id,
    )
    with pytest.raises(ArchiveOrderPlanningError, match="boundary .* unknown"):
        build_work_archive_position_plan(
            work, [target, other], catalog.list_items(work_id=work.id), [source]
        )


def test_archive_segments_ignore_unpositioned_disabled_rows(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key="segments", title="Segments"))
    target = WatchlistTarget(
        key="first", work_key=work.work_key, site="mangaone",
        url="https://example.invalid/first", label="First",
        archive_segments=(ArchiveSegment(order=1),),
    )
    enabled_item = catalog.create_item(ItemInput(), work_id=work.id)
    enabled = catalog.create_source(
        SourceInput(
            site="mangaone", external_id="a1", discovery_key="first",
            access_mode="free", display_position=1,
        ), item_id=enabled_item.id,
    )
    disabled_item = catalog.create_item(ItemInput(), work_id=work.id)
    disabled = catalog.create_source(
        SourceInput(
            site="mangaone", external_id="replaced", discovery_key="first",
            access_mode="free", display_position=None,
        ), item_id=disabled_item.id,
    )
    disabled = replace(disabled, acquisition_enabled=False)

    plan = build_work_archive_position_plan(
        work, [target], catalog.list_items(work_id=work.id), [enabled, disabled]
    )

    assert plan is not None
    assert plan.ordered_source_ids == (enabled.id,)
    assert plan.positions_by_source_id == {enabled.id: 1}


def test_archive_segments_reject_unresolved_open_segment_without_sources(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key="segments", title="Segments"))
    unresolved = WatchlistTarget(
        key="new", work_key=work.work_key, site="mangaone",
        url="https://example.invalid/new", label="New",
        archive_segments=(ArchiveSegment(order=1),),
    )
    existing = WatchlistTarget(
        key="existing", work_key=work.work_key, site="zeblack",
        url="https://example.invalid/existing", label="Existing",
        archive_segments=(ArchiveSegment(order=2),),
    )
    item = catalog.create_item(ItemInput(), work_id=work.id)
    source = catalog.create_source(
        SourceInput(
            site="zeblack", external_id="existing-1", discovery_key="existing",
            access_mode="free", display_position=1,
        ), item_id=item.id,
    )

    with pytest.raises(ArchiveOrderPlanningError, match="no acquisition-enabled sources"):
        build_work_archive_position_plan(
            work, [unresolved, existing], catalog.list_items(work_id=work.id), [source]
        )


def test_archive_segments_empty_mode_allows_disabled_unpositioned_rows(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key="segments", title="Segments"))
    target = WatchlistTarget(
        key="replaced", work_key=work.work_key, site="mangaone",
        url="https://example.invalid/replaced", label="Replaced",
        archive_segments=(),
    )
    item = catalog.create_item(ItemInput(), work_id=work.id)
    source = catalog.create_source(
        SourceInput(
            site="mangaone", external_id="old", discovery_key="replaced",
            access_mode="free", display_position=None,
        ), item_id=item.id,
    )
    source = replace(source, acquisition_enabled=False)

    plan = build_work_archive_position_plan(
        work, [target], catalog.list_items(work_id=work.id), [source]
    )

    assert plan is not None
    assert plan.ordered_source_ids == ()
    assert plan.positions_by_source_id == {}


def test_cross_site_archive_order_assigns_zeblack_100_then_bookwalker_2(
    tmp_path: Path,
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key="crosssite", title="Cross Site"))
    watchlist = WatchlistService(tmp_path / "watchlist.yaml")
    zeblack_target = watchlist.add(
        key="zeblack-chapters",
        work_key=work.work_key,
        site="zeblack",
        url="https://example.invalid/zeblack/list",
        label="Zeblack chapters",
        archive_order=1,
    )
    bookwalker_target = watchlist.add(
        key="bookwalker-volumes",
        work_key=work.work_key,
        site="bookwalker",
        url="https://example.invalid/bookwalker/list",
        label="BookWalker volumes",
        archive_order=2,
    )

    zeblack_positions = []
    for position in range(1, 101):
        external_id = f"chapter-{position:03d}"
        item = catalog.create_item(ItemInput(item_title=external_id), work_id=work.id)
        source = catalog.create_source(
            SourceInput(
                site="zeblack",
                external_id=external_id,
                discovery_key=zeblack_target.key,
                access_mode="free",
                available=True,
                display_position=position,
            ),
            item_id=item.id,
        )
        catalog.create_source_target(
            SourceTargetInput(
                backend="web", locator=f"https://example.invalid/zeblack/{external_id}"
            ),
            source_id=source.id,
        )
        zeblack_positions.append(DiscoveryInventoryPosition(external_id, position))

    bookwalker_positions = []
    for position in range(1, 3):
        external_id = f"volume-{position:03d}"
        item = catalog.create_item(ItemInput(item_title=external_id), work_id=work.id)
        source = catalog.create_source(
            SourceInput(
                site="bookwalker",
                external_id=external_id,
                discovery_key=bookwalker_target.key,
                access_mode="owned",
                available=True,
                display_position=position,
            ),
            item_id=item.id,
        )
        catalog.create_source_target(
            SourceTargetInput(
                backend="web", locator=f"https://example.invalid/bookwalker/{external_id}"
            ),
            source_id=source.id,
        )
        bookwalker_positions.append(DiscoveryInventoryPosition(external_id, position))

    _record_inventory(catalog, zeblack_target, tuple(zeblack_positions))
    _record_inventory(catalog, bookwalker_target, tuple(bookwalker_positions))
    policies = SitePolicyRegistry()
    policies.register("zeblack", ZeblackSitePolicy)
    policies.register("bookwalker", BookWalkerSitePolicy)
    planner = BatchPlanner(catalog, policies, watchlist=watchlist)
    zeblack_plan = planner.plan(site="zeblack", now=NOW)
    bookwalker_plan = planner.plan(site="bookwalker", now=NOW)

    assert [candidate.artifact_prefix for candidate in zeblack_plan.candidates] == [
        f"{position:03d}" for position in range(1, 101)
    ]
    assert [candidate.artifact_prefix for candidate in bookwalker_plan.candidates] == [
        "101",
        "102",
    ]


def test_unmanaged_work_sources_are_skipped_without_losing_quota_history(
    tmp_path: Path,
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    managed_work = catalog.create_work(WorkInput(work_key="managed", title="Managed"))
    unmanaged_work = catalog.create_work(
        WorkInput(work_key="unmanaged", title="Unmanaged")
    )
    managed_item = catalog.create_item(ItemInput(), work_id=managed_work.id)
    managed_source = catalog.create_source(
        SourceInput(
            site="mangaone",
            external_id="managed-chapter",
            discovery_key="managed-key",
            access_mode="free",
            available=True,
            display_position=1,
        ),
        item_id=managed_item.id,
    )
    catalog.create_source_target(
        SourceTargetInput(
            backend="web", locator="https://example.invalid/managed-chapter"
        ),
        source_id=managed_source.id,
    )
    unmanaged_item = catalog.create_item(ItemInput(), work_id=unmanaged_work.id)
    unmanaged_source = catalog.create_source(
        SourceInput(
            site="mangaone",
            external_id="unmanaged-chapter",
            discovery_key="removed-key",
            access_mode="quota",
            available=True,
            quota_started_at=NOW,
            display_position=1,
        ),
        item_id=unmanaged_item.id,
    )
    catalog.create_source_target(
        SourceTargetInput(
            backend="web", locator="https://example.invalid/unmanaged-chapter"
        ),
        source_id=unmanaged_source.id,
    )

    watchlist = WatchlistService(tmp_path / "watchlist.yaml")
    watchlist.add(
        key="managed-key",
        work_key=managed_work.work_key,
        site="mangaone",
        url="https://example.invalid/managed-list",
        label="Managed",
    )
    reconciler = ScopeReconciler(watchlist, catalog)
    reconciler.apply(reconciler.preview(managed_work.work_key))
    policies = SitePolicyRegistry()
    policies.register("mangaone", MangaOneSitePolicy)

    plan = BatchPlanner(catalog, policies, watchlist=watchlist).plan(
        site="mangaone", now=NOW
    )

    assert [candidate.source_id for candidate in plan.candidates] == [managed_source.id]
    assert plan.quota_available == 3
    assert any(
        skip.source_id == unmanaged_source.id
        and skip.reason == "acquisition_unmanaged"
        for skip in plan.skipped
    )


def _write_target(path: Path, target: WatchlistTarget) -> None:
    scope = target.discovery_scope
    value = {
        "key": target.key,
        "work_key": target.work_key,
        "site": target.site,
        "url": target.url,
        "label": target.label,
    }
    if scope is not None:
        value["discovery_scope"] = {
            key: part
            for key, part in (
                ("from_url", scope.from_url),
                ("through_url", scope.through_url),
            )
            if part is not None
        }
    path.write_text(yaml.safe_dump({"targets": [value]}, sort_keys=False), encoding="utf-8")


def _record_inventory(
    catalog: CatalogService,
    target: WatchlistTarget,
    positions: tuple[DiscoveryInventoryPosition, ...],
) -> None:
    catalog.record_discovery_inventory_evidence(
        work_key=target.work_key,
        discovery_key=target.key,
        site=target.site,
        target_url=target.url,
        scope_fingerprint=target_scope_fingerprint(target),
        listing_identity=f"test:{target.site}:{target.key}",
        positions=positions,
    )


def test_batch_requires_watchlist_for_existing_sources(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key="series", title="Series"))
    item = catalog.create_item(ItemInput(), work_id=work.id)
    catalog.create_source(
        SourceInput(site="mangaone", external_id="chapter-1", access_mode="free"),
        item_id=item.id,
    )
    policies = SitePolicyRegistry()
    policies.register("mangaone", MangaOneSitePolicy)

    with pytest.raises(BatchPlanningError, match="explicit Watchlist"):
        BatchPlanner(catalog, policies).plan(site="mangaone", now=NOW)


def test_planner_resolves_source_work_via_item_without_scope_sync(
    tmp_path: Path,
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    decoy = catalog.create_work(WorkInput(work_key="decoy", title="Decoy"))
    actual = catalog.create_work(WorkInput(work_key="actual", title="Actual"))
    # Item IDs and Work IDs are separate namespaces; this item is ID 1 but
    # belongs to Work ID 2. The old bug silently gated the decoy Work instead.
    item = catalog.create_item(ItemInput(), work_id=actual.id)
    assert item.id != actual.id
    source = catalog.create_source(
        SourceInput(
            site="mangaone", external_id="chapter-1", discovery_key="actual-key",
            access_mode="free",
        ),
        item_id=item.id,
    )
    catalog.create_source_target(
        SourceTargetInput(backend="web", locator="https://example.invalid/chapter-1"),
        source_id=source.id,
    )
    watchlist = WatchlistService(tmp_path / "watchlist.yaml")
    watchlist.add(
        key="decoy-key", work_key=decoy.work_key, site="mangaone",
        url="https://example.invalid/decoy", label="Decoy",
    )
    watchlist.add(
        key="actual-key", work_key=actual.work_key, site="mangaone",
        url="https://example.invalid/actual", label="Actual",
    )
    reconciler = ScopeReconciler(watchlist, catalog)
    reconciler.apply(reconciler.preview(decoy.work_key))

    policies = SitePolicyRegistry()
    policies.register("mangaone", MangaOneSitePolicy)
    plan = BatchPlanner(catalog, policies, watchlist=watchlist).plan(
        site="mangaone", now=NOW
    )
    assert [candidate.source_id for candidate in plan.candidates] == [source.id]
    assert plan.candidates[0].work_id == actual.id


def test_acquisition_exclusion_precedes_policy_but_keeps_quota_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key="series", title="Series"))
    rows = []
    for external_id, position, consumed_at in (
        ("chapter-1", 1, "2026-09-17T14:00:00+09:00"),
        ("chapter-2", 2, None),
    ):
        item = catalog.create_item(ItemInput(), work_id=work.id)
        source = catalog.create_source(
            SourceInput(
                site="mangaone", external_id=external_id, discovery_key="chapters",
                access_mode="quota", quota_started_at=consumed_at,
                display_position=position,
            ),
            item_id=item.id,
        )
        catalog.create_source_target(
            SourceTargetInput(
                backend="web", locator=f"https://example.invalid/{external_id}"
            ),
            source_id=source.id,
        )
        rows.append(source)
    target = WatchlistTarget(
        key="chapters",
        work_key=work.work_key,
        site="mangaone",
        url="https://example.invalid/list",
        label="Series",
        discovery_scope=DiscoveryScope(through_url="https://example.invalid/chapter-2"),
    )
    watchlist_path = tmp_path / "watchlist.yaml"
    _write_target(watchlist_path, target)
    watchlist = WatchlistService(watchlist_path)
    _record_inventory(
        catalog,
        target,
        (
            DiscoveryInventoryPosition("chapter-1", 1, in_scope=False),
            DiscoveryInventoryPosition("chapter-2", 2, in_scope=True),
        ),
    )
    reconciler = ScopeReconciler(watchlist, catalog)
    reconciler.apply(reconciler.preview(work.work_key))

    evaluated: list[int] = []
    original_evaluate = MangaOneSitePolicy.evaluate

    def record_evaluation(self, source, *, now, quota_available):
        evaluated.append(source.id)
        return original_evaluate(
            self, source, now=now, quota_available=quota_available
        )

    monkeypatch.setattr(MangaOneSitePolicy, "evaluate", record_evaluation)
    policies = SitePolicyRegistry()
    policies.register("mangaone", MangaOneSitePolicy)
    plan = BatchPlanner(catalog, policies, watchlist=watchlist).plan(
        site="mangaone", now=NOW
    )

    assert [candidate.source_id for candidate in plan.candidates] == [rows[1].id]
    assert evaluated == [rows[1].id]
    assert plan.quota_available == 3  # The disabled source's historical debit still counts.
    assert any(
        skipped.source_id == rows[0].id and skipped.reason == "acquisition_disabled"
        for skipped in plan.skipped
    )


def test_watchlist_exclusion_overlay_denies_before_policy_and_preserves_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key="series", title="Series"))
    sources = []
    for index in (1, 2, 3):
        item = catalog.create_item(ItemInput(), work_id=work.id)
        source = catalog.create_source(
            SourceInput(
                site="mangaone", external_id=f"chapter-{index}",
                discovery_key="chapters", access_mode="free",
                display_position=index,
            ),
            item_id=item.id,
        )
        catalog.create_source_target(
            SourceTargetInput(backend="web", locator=f"https://example.invalid/chapter-{index}"),
            source_id=source.id,
        )
        sources.append(source)
    catalog.apply_discovery_acquisition_flags(
        work_id=work.id,
        site="mangaone",
        discovery_key="chapters",
        flags_by_external_id={"chapter-2": False},
    )
    watchlist = WatchlistService(tmp_path / "watchlist.yaml")
    watchlist.add(
        key="chapters", work_key=work.work_key, site="mangaone",
        url="https://example.invalid/list", label="Series", archive_order=1,
        discovery_scope=DiscoveryScope(
            from_url="https://example.invalid/chapter-1",
            through_url="https://example.invalid/chapter-3",
            excluded_external_ids=("chapter-1",),
        ),
    )
    evaluated: list[int] = []
    original_evaluate = MangaOneSitePolicy.evaluate

    def record_evaluation(self, source, *, now, quota_available):
        evaluated.append(source.id)
        return original_evaluate(self, source, now=now, quota_available=quota_available)

    monkeypatch.setattr(MangaOneSitePolicy, "evaluate", record_evaluation)
    policies = SitePolicyRegistry()
    policies.register("mangaone", MangaOneSitePolicy)
    plan = BatchPlanner(catalog, policies, watchlist=watchlist).plan(
        site="mangaone", now=NOW
    )

    # The exclusion is an immediate acquisition deny, but naming still uses
    # the last reflected Catalog flags until Full/apply.  The remaining
    # candidate therefore keeps the prefix for the excluded row.
    assert [candidate.source_id for candidate in plan.candidates] == [sources[2].id]
    assert plan.candidates[0].artifact_prefix == "002"
    assert evaluated == [sources[2].id]
    assert any(
        skipped.source_id == sources[0].id and skipped.reason == "acquisition_excluded"
        for skipped in plan.skipped
    )
    assert any(
        skipped.source_id == sources[1].id and skipped.reason == "acquisition_disabled"
        for skipped in plan.skipped
    )
    assert catalog.get_source(sources[0].id).acquisition_enabled is True
    watchlist.update_target(
        "chapters",
        discovery_scope=DiscoveryScope(
            from_url="https://example.invalid/chapter-1",
            through_url="https://example.invalid/chapter-3",
            excluded_external_ids=("missing-episode",),
        ),
    )
    unknown_plan = BatchPlanner(catalog, policies, watchlist=watchlist).plan(
        site="mangaone", now=NOW
    )
    assert unknown_plan.candidates == []
    assert evaluated == [sources[2].id]
    assert any(
        skipped.source_id == sources[0].id
        and skipped.reason == "acquisition_exclusion_unproven"
        for skipped in unknown_plan.skipped
    )


def test_planner_uses_last_flags_after_watchlist_edit_without_reading_scope_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key="race-series", title="Series"))
    sources = []
    positions = []
    for index in (1, 2):
        external_id = f"chapter-{index}"
        item = catalog.create_item(ItemInput(), work_id=work.id)
        source = catalog.create_source(
            SourceInput(
                site="mangaone", external_id=external_id,
                discovery_key="chapters", access_mode="free",
                display_position=index,
            ),
            item_id=item.id,
        )
        catalog.create_source_target(
            SourceTargetInput(
                backend="web", locator=f"https://example.invalid/{external_id}"
            ),
            source_id=source.id,
        )
        sources.append(source)
        positions.append(DiscoveryInventoryPosition(external_id, index, in_scope=True))

    target = WatchlistTarget(
        key="chapters",
        work_key=work.work_key,
        site="mangaone",
        url="https://example.invalid/list",
        label="Series",
    )
    watchlist_path = tmp_path / "watchlist.yaml"
    _write_target(watchlist_path, target)
    watchlist = WatchlistService(watchlist_path)
    _record_inventory(catalog, target, tuple(positions))
    reconciler = ScopeReconciler(watchlist, catalog)
    reconciler.apply(reconciler.preview(work.work_key))

    policies = SitePolicyRegistry()
    policies.register("mangaone", MangaOneSitePolicy)
    planner = BatchPlanner(catalog, policies, watchlist=watchlist)
    narrowed = replace(
        target,
        discovery_scope=DiscoveryScope(through_url="https://example.invalid/chapter-1"),
    )
    _write_target(watchlist_path, narrowed)
    catalog.invalidate_discovery_inventory_evidence(target.key)

    def unexpected_proof_read(*_args, **_kwargs):
        pytest.fail("Batch must not read scope proofs or require a synced marker")

    monkeypatch.setattr(
        catalog,
        "read_acquisition_scope_snapshot",
        unexpected_proof_read,
    )

    plan = planner.plan(site="mangaone", now=NOW)
    assert {candidate.source_id for candidate in plan.candidates} == {
        row.id for row in sources
    }

    assert catalog.get_source(sources[0].id).acquisition_enabled is True
    assert catalog.get_source(sources[1].id).acquisition_enabled is True


async def test_resolver_rejects_forged_target_before_adapter_creation(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key="series", title="Series"))
    item = catalog.create_item(ItemInput(), work_id=work.id)
    source = catalog.create_source(
        SourceInput(
            site="magapoke", external_id="episode-1", discovery_key="chapters",
            access_mode="quota",
        ),
        item_id=item.id,
    )
    catalog.create_source_target(
        SourceTargetInput(backend="web", locator="https://example.invalid/episode-1"),
        source_id=source.id,
    )
    watchlist = WatchlistService(tmp_path / "watchlist.yaml")
    watchlist.add(
        key="chapters", work_key=work.work_key, site="magapoke",
        url="https://example.invalid/list", label="Series",
    )
    reconciler = ScopeReconciler(watchlist, catalog)
    reconciler.apply(reconciler.preview(work.work_key))
    policies = SitePolicyRegistry()
    policies.register("magapoke", MagapokeSitePolicy)
    candidate = BatchPlanner(catalog, policies, watchlist=watchlist).plan(
        site="magapoke", now=NOW, quota_resource="work_ticket"
    ).candidates[0]
    forged = replace(candidate, locator="https://outside.invalid/other")
    executor = BatchExecutor(
        catalog,
        policies,
        AdapterRegistry(),
        watchlist=watchlist,
        library_dir=tmp_path / "Books",
    )

    with pytest.raises(BatchExecutionError, match="target.locator"):
        async with executor.prepare_access_resource_candidates(
            object(), [forged], "work_ticket"
        ):
            pytest.fail("A forged candidate reached the access resolver")


async def test_resolver_rejects_candidate_newly_excluded_by_watchlist(
    tmp_path: Path,
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key="series", title="Series"))
    item = catalog.create_item(ItemInput(), work_id=work.id)
    source = catalog.create_source(
        SourceInput(
            site="magapoke", external_id="episode-1", discovery_key="chapters",
            access_mode="quota",
        ),
        item_id=item.id,
    )
    catalog.create_source_target(
        SourceTargetInput(backend="web", locator="https://example.invalid/episode-1"),
        source_id=source.id,
    )
    watchlist = WatchlistService(tmp_path / "watchlist.yaml")
    watchlist.add(
        key="chapters", work_key=work.work_key, site="magapoke",
        url="https://example.invalid/list", label="Series",
    )
    policies = SitePolicyRegistry()
    policies.register("magapoke", MagapokeSitePolicy)
    candidate = BatchPlanner(catalog, policies, watchlist=watchlist).plan(
        site="magapoke", now=NOW, quota_resource="work_ticket"
    ).candidates[0]
    watchlist.update_target(
        "chapters",
        discovery_scope=DiscoveryScope(
            from_url="https://example.invalid/episode-1",
            through_url="https://example.invalid/episode-1",
            excluded_external_ids=("episode-1",),
        ),
    )
    executor = BatchExecutor(
        catalog,
        policies,
        AdapterRegistry(),
        watchlist=watchlist,
        library_dir=tmp_path / "Books",
    )
    with pytest.raises(BatchExecutionError, match="excluded"):
        async with executor.prepare_access_resource_candidates(
            object(), [candidate], "work_ticket"
        ):
            pytest.fail("A newly excluded candidate reached the access resolver")


async def test_resolver_rejects_candidate_when_new_exclusion_is_unproven(
    tmp_path: Path,
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key="series", title="Series"))
    item = catalog.create_item(ItemInput(), work_id=work.id)
    source = catalog.create_source(
        SourceInput(
            site="magapoke", external_id="episode-1", discovery_key="chapters",
            access_mode="quota",
        ),
        item_id=item.id,
    )
    catalog.create_source_target(
        SourceTargetInput(backend="web", locator="https://example.invalid/episode-1"),
        source_id=source.id,
    )
    watchlist = WatchlistService(tmp_path / "watchlist.yaml")
    watchlist.add(
        key="chapters", work_key=work.work_key, site="magapoke",
        url="https://example.invalid/list", label="Series",
    )
    policies = SitePolicyRegistry()
    policies.register("magapoke", MagapokeSitePolicy)
    candidate = BatchPlanner(catalog, policies, watchlist=watchlist).plan(
        site="magapoke", now=NOW, quota_resource="work_ticket"
    ).candidates[0]
    watchlist.update_target(
        "chapters",
        discovery_scope=DiscoveryScope(
            from_url="https://example.invalid/episode-1",
            through_url="https://example.invalid/episode-1",
            excluded_external_ids=("unknown-episode",),
        ),
    )
    executor = BatchExecutor(
        catalog,
        policies,
        AdapterRegistry(),
        watchlist=watchlist,
        library_dir=tmp_path / "Books",
    )
    with pytest.raises(BatchExecutionError, match="unproven"):
        async with executor.prepare_access_resource_candidates(
            object(), [candidate], "work_ticket"
        ):
            pytest.fail("An unproven exclusion reached the access resolver")


async def test_grant_only_all_skips_browser_when_every_source_is_out_of_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    catalog_path = tmp_path / "catalog.sqlite"
    catalog = CatalogService(catalog_path)
    work = catalog.create_work(WorkInput(work_key="series", title="Series"))
    item = catalog.create_item(ItemInput(), work_id=work.id)
    source = catalog.create_source(
        SourceInput(
            site="magapoke", external_id="episode-1", discovery_key="chapters",
            access_mode="quota", display_position=1,
        ),
        item_id=item.id,
    )
    catalog.create_source_target(
        SourceTargetInput(
            backend="web", locator="https://example.invalid/episode-1"
        ),
        source_id=source.id,
    )
    target = WatchlistTarget(
        key="chapters",
        work_key=work.work_key,
        site="magapoke",
        url="https://example.invalid/list",
        label="Series",
        discovery_scope=DiscoveryScope(through_url="https://example.invalid/before-episode-1"),
    )
    watchlist_path = tmp_path / "watchlist.yaml"
    _write_target(watchlist_path, target)
    _record_inventory(
        catalog, target,
        (DiscoveryInventoryPosition("episode-1", 1, in_scope=False),),
    )
    watchlist = WatchlistService(watchlist_path)
    reconciler = ScopeReconciler(watchlist, catalog)
    reconciler.apply(reconciler.preview(work.work_key))

    async def unexpected_browser_connect(_endpoint: str):
        pytest.fail("grant-only all connected to a browser with no eligible sources")

    monkeypatch.setattr(
        cli.BrowserSession,
        "connect",
        classmethod(lambda _cls, endpoint: unexpected_browser_connect(endpoint)),
    )
    monkeypatch.setattr(
        cli,
        "load_runtime_settings",
        lambda *_args: SimpleNamespace(
            for_site=lambda _site: SimpleNamespace(inter_candidate_delay_ms=0)
        ),
    )
    args = cli._parser().parse_args(
        [
            "batch", "run", "--site", "magapoke", "--grant-only", "all",
            "--catalog", str(catalog_path), "--watchlist", str(watchlist_path),
            "--env-file", str(tmp_path / "missing.env"),
        ]
    )

    await cli._run_batch_run(args)

    assert catalog.get_source(source.id).quota_started_at is None
    assert catalog.get_quota_resource_state(
        work.id, site="magapoke", resource="work_ticket"
    ) is None

