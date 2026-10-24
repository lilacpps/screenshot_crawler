import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from screenshot_crawler.catalog import (
    ArtifactInput,
    CatalogNotFoundError,
    CatalogService,
    DiscoveryInventoryPosition,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)
from screenshot_crawler.maintenance.source_identity import (
    SourceIdentityError,
    SourceIdentityMaintenance,
)


def _graph(path: Path, *, new: bool = False):
    catalog = CatalogService(path)
    work = catalog.create_work(WorkInput(work_key="ng-life", title="NG LIFE"))
    old_item = catalog.create_item(ItemInput(item_title="scene 1"), work_id=work.id)
    old = catalog.create_source(
        SourceInput(site="hanayume", external_id="old", discovery_key="ng-life"),
        item_id=old_item.id,
    )
    catalog.create_source_target(
        SourceTargetInput(backend="web", locator="https://hanayume.com/episodes/old"),
        source_id=old.id,
    )
    donor = None
    if new:
        donor_item = catalog.create_item(ItemInput(), work_id=work.id)
        donor = catalog.create_source(
            SourceInput(site="hanayume", external_id="new", discovery_key="ng-life"),
            item_id=donor_item.id,
        )
        catalog.create_source_target(
            SourceTargetInput(backend="web", locator="https://hanayume.com/episodes/new"),
            source_id=donor.id,
        )
    return catalog, work, old, donor


def _plan(service: SourceIdentityMaintenance, *, token: str | None = None):
    return service.plan(
        site="hanayume", work_key="ng-life", old_external_id="old",
        new_external_id="new", new_locator="https://hanayume.com/episodes/new",
        reason="stable native API identity proof",
    )


def test_dry_run_is_read_only_and_apply_retains_source_item(tmp_path: Path):
    catalog, _work, old, _ = _graph(tmp_path / "catalog.sqlite")
    maintenance = SourceIdentityMaintenance(catalog)
    before = catalog.path.read_bytes()
    plan = _plan(maintenance)
    assert plan.donor_source_id is None
    assert catalog.path.read_bytes() == before
    maintenance.apply(plan, expected_token=plan.token)
    source = catalog.get_source(old.id)
    assert source.external_id == "new"
    assert catalog.get_item(old.item_id).status == "pending"
    assert catalog.find_source("hanayume", "old") is None


def test_dry_run_rejects_wal_header_after_empty_checkpoint(tmp_path: Path):
    catalog, _work, _old, _ = _graph(tmp_path / "catalog.sqlite")
    with sqlite3.connect(catalog.path) as connection:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    with pytest.raises(SourceIdentityError, match="rollback-journal"):
        _plan(SourceIdentityMaintenance(catalog))


def test_pristine_donor_is_removed_without_touching_retained_item(tmp_path: Path):
    catalog, _work, old, donor = _graph(tmp_path / "catalog.sqlite", new=True)
    assert donor is not None
    maintenance = SourceIdentityMaintenance(catalog)
    plan = _plan(maintenance)
    assert plan.donor_source_id == donor.id and plan.donor_pristine
    maintenance.apply(plan)
    assert catalog.get_source(old.id).external_id == "new"
    with pytest.raises(CatalogNotFoundError):
        catalog.get_source(donor.id)
    assert catalog.get_item(old.item_id).id == old.item_id


def test_donor_with_history_is_rejected(tmp_path: Path):
    catalog, _work, _old, donor = _graph(tmp_path / "catalog.sqlite", new=True)
    assert donor is not None
    catalog.set_item_status(donor.item_id, "completed")
    with pytest.raises(SourceIdentityError, match="not pristine"):
        _plan(SourceIdentityMaintenance(catalog))


def test_donor_manual_item_title_is_rejected_without_changes(tmp_path: Path):
    catalog, _work, old, donor = _graph(tmp_path / "catalog.sqlite", new=True)
    assert donor is not None
    catalog.update_item_metadata(donor.item_id, item_title="operator title")
    with pytest.raises(SourceIdentityError, match="not pristine"):
        _plan(SourceIdentityMaintenance(catalog))
    assert catalog.get_source(old.id).external_id == "old"
    assert catalog.get_source(donor.id).external_id == "new"


def test_wrong_work_is_rejected(tmp_path: Path):
    catalog, _work, _old, _ = _graph(tmp_path / "catalog.sqlite")
    maintenance = SourceIdentityMaintenance(catalog)
    with pytest.raises(SourceIdentityError, match="requested Work"):
        maintenance.plan(
            site="hanayume", work_key="other", old_external_id="old",
            new_external_id="new", new_locator="https://hanayume.com/episodes/new", reason="manual",
        )


def test_precondition_rejects_catalog_change(tmp_path: Path):
    catalog, _work, old, _ = _graph(tmp_path / "catalog.sqlite")
    maintenance = SourceIdentityMaintenance(catalog)
    plan = _plan(maintenance)
    catalog.update_source_external_state("hanayume", "old", available=False)
    with pytest.raises(SourceIdentityError, match="changed"):
        maintenance.apply(plan, expected_token=plan.token)
    assert catalog.find_source("hanayume", "old") is not None
    assert catalog.get_source(old.id).external_id == "old"


def test_forged_plan_ids_are_ignored_after_token_recheck(tmp_path: Path):
    catalog, _work, old, _ = _graph(tmp_path / "catalog.sqlite")
    maintenance = SourceIdentityMaintenance(catalog)
    plan = _plan(maintenance)
    forged = replace(plan, old_source_id=999999, old_item_id=999999)
    with pytest.raises(SourceIdentityError, match="changed"):
        maintenance.apply(forged, expected_token=plan.token)
    assert catalog.get_source(old.id).external_id == "old"


def test_apply_rolls_back_identity_and_donor_on_catalog_failure(tmp_path: Path):
    catalog, _work, old, donor = _graph(tmp_path / "catalog.sqlite", new=True)
    assert donor is not None
    maintenance = SourceIdentityMaintenance(catalog)
    plan = _plan(maintenance)
    with catalog._connection() as connection:
        connection.execute(
            "CREATE TRIGGER force_identity_failure BEFORE UPDATE OF external_id ON sources "
            "BEGIN SELECT RAISE(ABORT, 'forced identity failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="forced identity failure"):
        maintenance.apply(plan)
    assert catalog.get_source(old.id).external_id == "old"
    assert catalog.get_source(donor.id).external_id == "new"


def test_completed_history_and_artifact_are_retained(tmp_path: Path):
    catalog, _work, old, _ = _graph(tmp_path / "catalog.sqlite")
    target = catalog.find_source_target(old.id, "web")
    assert target is not None
    run = catalog.create_crawl_run(
        item_id=old.item_id, source_id=old.id, target_id=target.id, access_strategy="direct"
    )
    run = catalog.mark_crawl_run_succeeded(run.id, page_count=2)
    artifact = catalog.create_artifact(
        ArtifactInput(
            kind="archive", format="zip", sha256="a" * 64, byte_size=12,
            storage_backend="filesystem", locator="C:/library/old.zip", state="present",
        ),
        item_id=old.item_id, crawl_run_id=run.id,
    )
    catalog.set_item_status(old.item_id, "completed")
    _quota_source, quota_state = catalog.record_quota_access_with_resource_state(
        old.id,
        work_id=1,
        site="hanayume",
        resource="episode-ticket",
        consumed_at="2026-10-24T10:00:00+09:00",
        access_granted_until="2026-10-25T10:00:00+09:00",
    )
    SourceIdentityMaintenance(catalog).apply(_plan(SourceIdentityMaintenance(catalog)))
    retained_run = catalog.get_crawl_run(run.id)
    retained_artifact = catalog.get_artifact(artifact.id)
    assert retained_run.external_id_snapshot == "old"
    assert retained_run.source_id == old.id
    assert retained_artifact.locator == "C:/library/old.zip"
    assert catalog.get_item(old.item_id).status == "completed"
    assert catalog.get_quota_resource_state(
        1, site="hanayume", resource="episode-ticket"
    ) == quota_state


def test_running_history_blocks_identity_change(tmp_path: Path):
    catalog, _work, old, _ = _graph(tmp_path / "catalog.sqlite")
    target = catalog.find_source_target(old.id, "web")
    assert target is not None
    catalog.create_crawl_run(
        item_id=old.item_id, source_id=old.id, target_id=target.id, access_strategy="direct"
    )
    with pytest.raises(SourceIdentityError, match="running CrawlRun"):
        _plan(SourceIdentityMaintenance(catalog))


def test_donor_from_another_discovery_key_is_rejected(tmp_path: Path):
    catalog, _work, _old, donor = _graph(tmp_path / "catalog.sqlite", new=True)
    assert donor is not None
    with catalog._connection() as connection:
        connection.execute(
            "UPDATE sources SET discovery_key = 'other-key' WHERE id = ?", (donor.id,)
        )
    with pytest.raises(SourceIdentityError, match="different Discovery keys"):
        _plan(SourceIdentityMaintenance(catalog))


def test_both_sources_with_history_are_never_consolidated(tmp_path: Path):
    catalog, _work, old, donor = _graph(tmp_path / "catalog.sqlite", new=True)
    assert donor is not None
    target = catalog.find_source_target(donor.id, "web")
    assert target is not None
    catalog.create_crawl_run(
        item_id=donor.item_id, source_id=donor.id, target_id=target.id, access_strategy="direct"
    )
    with pytest.raises(SourceIdentityError, match="not pristine"):
        _plan(SourceIdentityMaintenance(catalog))
    assert catalog.get_source(old.id).external_id == "old"
    assert catalog.get_source(donor.id).external_id == "new"


def test_scope_proof_recovers_after_identity_change(tmp_path: Path):
    catalog, work, old, _ = _graph(tmp_path / "catalog.sqlite")
    catalog.apply_acquisition_scope_sync(
        work_key=work.work_key, fingerprint="f" * 64, source_flags={old.id: True}
    )
    catalog.record_discovery_inventory_evidence(
        work_key=work.work_key, discovery_key="ng-life", site="hanayume",
        target_url="https://hanayume.com/series/ca6472995ecea",
        scope_fingerprint="a" * 64, listing_identity="listing-1",
        positions=[DiscoveryInventoryPosition("old", 1)],
    )
    catalog.apply_acquisition_scope_sync(
        work_key=work.work_key, fingerprint="f" * 64, source_flags={old.id: True}
    )
    synced_at = catalog.get_acquisition_scope_sync(work.work_key).synced_at
    SourceIdentityMaintenance(catalog).apply(_plan(SourceIdentityMaintenance(catalog)))
    stale = catalog.get_acquisition_scope_sync(work.work_key)
    assert stale is not None and stale.status == "stale" and stale.synced_at == synced_at
    assert catalog.get_discovery_inventory_evidence("ng-life") is None
    catalog.record_discovery_inventory_evidence(
        work_key=work.work_key, discovery_key="ng-life", site="hanayume",
        target_url="https://hanayume.com/series/ca6472995ecea",
        scope_fingerprint="b" * 64, listing_identity="listing-2",
        positions=[DiscoveryInventoryPosition("new", 1)],
    )
    catalog.apply_acquisition_scope_sync(
        work_key=work.work_key, fingerprint="f" * 64, source_flags={old.id: True}
    )
    recovered = catalog.get_acquisition_scope_sync(work.work_key)
    assert recovered is not None and recovered.status == "synced"
    assert catalog.get_discovery_inventory_evidence("ng-life").positions[0].external_id == "new"
