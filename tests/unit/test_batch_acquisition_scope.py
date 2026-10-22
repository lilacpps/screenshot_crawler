from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from screenshot_crawler import cli
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
    MagapokeSitePolicy,
    MangaOneSitePolicy,
    SitePolicyRegistry,
)
from screenshot_crawler.watchlist.fingerprints import target_scope_fingerprint
from screenshot_crawler.watchlist.models import DiscoveryScope, WatchlistTarget
from screenshot_crawler.watchlist.reconcile import ScopeReconciler
from screenshot_crawler.watchlist.service import WatchlistService

NOW = datetime(2026, 9, 17, 15, 0, tzinfo=JST)


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


def test_planner_resolves_source_work_via_item_and_blocks_unsynced_actual_work(
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
    with pytest.raises(BatchPlanningError, match="missing or stale"):
        BatchPlanner(catalog, policies, watchlist=watchlist).plan(
            site="mangaone", now=NOW
        )


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


def test_planner_rejects_scope_change_between_source_read_and_validation(
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
    assert planner.scope_reconciler is not None
    original_snapshot = planner.scope_reconciler.require_synchronized_snapshot

    def apply_narrower_scope_during_validation(work_key: str):
        narrowed = replace(
            target,
            discovery_scope=DiscoveryScope(
                through_url="https://example.invalid/chapter-1"
            ),
        )
        _write_target(watchlist_path, narrowed)
        _record_inventory(
            catalog,
            narrowed,
            (
                DiscoveryInventoryPosition("chapter-1", 1, in_scope=True),
                DiscoveryInventoryPosition("chapter-2", 2, in_scope=False),
            ),
        )
        changed = planner.scope_reconciler.preview(work_key)
        assert changed.ready
        planner.scope_reconciler.apply(changed)
        return original_snapshot(work_key)

    monkeypatch.setattr(
        planner.scope_reconciler,
        "require_synchronized_snapshot",
        apply_narrower_scope_during_validation,
    )

    with pytest.raises(BatchPlanningError, match="changed while validating"):
        planner.plan(site="mangaone", now=NOW)

    assert catalog.get_source(sources[0].id).acquisition_enabled is True
    assert catalog.get_source(sources[1].id).acquisition_enabled is False


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
        catalog, policies, AdapterRegistry(), watchlist=watchlist
    )

    with pytest.raises(BatchExecutionError, match="target.locator"):
        async with executor.prepare_access_resource_candidates(
            object(), [forged], "work_ticket"
        ):
            pytest.fail("A forged candidate reached the access resolver")


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

