"""Explicit repair transactions against isolated Catalogs and synthetic ZIPs."""

import json
import sqlite3
from dataclasses import replace

import pytest
import yaml

from screenshot_crawler.batch.planner import BatchPlanner
from screenshot_crawler.catalog import ArtifactInput, WorkInput
from screenshot_crawler.maintenance.hanayume_migration import (
    RepairMigrationError,
    apply_migration_plan,
    build_migration_plan,
    load_review_report,
    migration_preview_payload,
)
from screenshot_crawler.maintenance.hanayume_repair import (
    HISTORY_KEY_PREFIX,
    export_report,
    load_analysis,
)
from screenshot_crawler.management.inventory import default_policy_registry
from screenshot_crawler.watchlist.reconcile import ScopeReconciler
from screenshot_crawler.watchlist.service import WatchlistService


def report(x, path=None, analysis=None):
    path = path or x.catalog.path.with_name("review.json")
    export_report(analysis or load_analysis(x.catalog.path, x.watchlist, x.work.work_key), path)
    return path


def plan(x, path, **kwargs):
    return build_migration_plan(x.catalog.path, x.watchlist, path, accepted=True, **kwargs)


def apply(x, p):
    return apply_migration_plan(p, expected_token=p.token, backup_dir=x.catalog.path.parent / "backups")


def histories(x):
    with sqlite3.connect(x.catalog.path) as connection:
        return {table: connection.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
                for table in ("crawl_runs", "artifacts", "quota_resource_states")}


def pending_pair(x):
    old, item, target = x.add(2, "第2話", available=False)
    x.catalog.update_item_note(item.id, None)
    new, _, new_target = x.add(102, "第2話", available=True)
    return old, target, new, new_target


@pytest.mark.parametrize("shape,policy", [("one", "auto"), ("split", "auto"), ("merge", "auto"),
                                         ("one", "new"), ("one", "reacquire")])
def test_empty_old_pending_is_deleted_with_backup_preview_and_replay(hanayume_repair_inputs, shape, policy):
    x = hanayume_repair_inputs
    old, _, new, _ = pending_pair(x)
    old_ids, new_ids = [old.id], [new.id]
    if shape == "split":
        x.catalog.update_item_metadata(new.item_id, order_label="第2話①")
        extra, _, _ = x.add(103, "第2話②", available=True)
        new_ids.append(extra.id)
    elif shape == "merge":
        x.catalog.update_item_metadata(old.item_id, order_label="第2話①")
        extra, item, _ = x.add(3, "第2話②", available=False)
        x.catalog.update_item_note(item.id, None)
        old_ids.append(extra.id)
    path = report(x)
    original, watch, archive = x.catalog.path.read_bytes(), x.watchlist.read_bytes(), x.archive.read_bytes()
    history = histories(x)
    p = plan(x, path)
    entry = next(e for e in p.entries if old.id in e.old_ids)
    if policy != "auto":
        p = plan(x, path, choices=((entry.group_id, policy),))
        entry = next(e for e in p.entries if old.id in e.old_ids)
    assert p.ready and entry.action == ("reacquire" if policy == "reacquire" else "use_new")
    assert set(entry.delete_old_pending_ids) == set(old_ids)
    preview = migration_preview_payload(p, load_review_report(path, x.catalog.path, x.watchlist).analysis)
    outcome = next(o for o in preview["outcomes"] if o["group_id"] == entry.group_id)
    assert set(outcome["delete"]["source_ids"]) == set(old_ids)
    assert set(outcome["keep"]["source_ids"]) == set(new_ids)
    assert not outcome["history_after"] and not outcome["add"]
    assert all(r["status"] == "pending" for r in outcome["current_after"])
    assert x.catalog.path.read_bytes() == original
    result = apply(x, p)
    with sqlite3.connect(result.backup) as connection:
        assert connection.execute("SELECT id FROM sources WHERE id=?", (old.id,)).fetchone()
    with sqlite3.connect(x.catalog.path) as connection:
        for table, key in (("sources", "source_ids"), ("items", "item_ids"), ("source_targets", "target_ids")):
            assert all(connection.execute(f"SELECT id FROM {table} WHERE id=?", (id_,)).fetchone() is None
                       for id_ in outcome["delete"][key])
    assert all(x.catalog.get_item(x.catalog.get_source(id_).item_id).status == "pending" for id_ in new_ids)
    assert apply(x, p).already_applied
    assert histories(x) == history and x.watchlist.read_bytes() == watch and x.archive.read_bytes() == archive


@pytest.mark.parametrize("protected", ["run", "artifact", "quota", "grant", "title", "note", "sibling", "target"])
def test_old_pending_with_history_or_operator_state_is_preserved(hanayume_repair_inputs, protected):
    x = hanayume_repair_inputs
    old, target, new, _ = pending_pair(x)
    if protected == "run":
        run = x.catalog.create_crawl_run(item_id=old.item_id, source_id=old.id, target_id=target.id, access_strategy="direct")
        x.catalog.mark_crawl_run_failed(run.id, error_type="FixtureError", error_message="synthetic")
    elif protected == "artifact":
        x.catalog.create_artifact(ArtifactInput(kind="archive", format="zip", sha256="0" * 64, byte_size=1,
            storage_backend="filesystem", locator=str(x.archive), state="missing"), item_id=old.item_id)
    elif protected in {"quota", "grant"}:
        with x.catalog._connection() as connection:
            column = "quota_started_at" if protected == "quota" else "access_granted_until"
            connection.execute(f"UPDATE sources SET {column}='2026-11-01T10:00:00+09:00' WHERE id=?", (old.id,))
    elif protected == "title":
        x.catalog.update_item_metadata(old.item_id, item_title="手動タイトル")
    elif protected == "note":
        x.catalog.update_item_note(old.item_id, "手動note")
    elif protected == "sibling":
        x.add(3, "第2話", available=False, item=x.catalog.get_item(old.item_id))
    else:
        with x.catalog._connection() as connection:
            connection.execute("UPDATE source_targets SET priority=200 WHERE id=?", (target.id,))
    path = report(x)
    p = plan(x, path)
    entry = next(e for e in p.entries if old.id in e.old_ids)
    assert p.ready and not entry.delete_old_pending_ids
    assert "履歴保管" in " ".join(entry.reasons)
    history = histories(x)
    apply(x, p)
    assert x.catalog.get_source(old.id).discovery_key == HISTORY_KEY_PREFIX + "repair-test"
    assert x.catalog.get_item(old.item_id).status == x.catalog.get_item(new.item_id).status == "pending"
    assert histories(x) == history


def test_reuse_identity_backup_atomic_history_preservation_and_replay(hanayume_repair_inputs):
    x = hanayume_repair_inputs
    path = report(x)
    original, watch, archive = x.catalog.path.read_bytes(), x.watchlist.read_bytes(), x.archive.read_bytes()
    history = histories(x)
    p = plan(x, path)
    assert p.ready and p.entries[0].action == "reuse_identity"
    preview = migration_preview_payload(p, load_review_report(path, x.catalog.path, x.watchlist).analysis)
    outcome = preview["outcomes"][0]
    assert preview["after_summary"]["current_item_statuses"] == {"completed": 1}
    assert outcome["current_after"][0]["item_id"] == x.old.item_id
    assert outcome["current_after"][0]["source_id"] == x.old.id
    assert outcome["current_after"][0]["external_id"] == x.new.external_id
    assert outcome["delete"] == {"item_ids": [x.new.item_id], "source_ids": [x.new.id], "target_ids": [x.new_target.id]}
    assert outcome["keep"]["item_ids"] == [x.old.item_id]
    assert not outcome["history_after"] and outcome["add"][0]["source_id"] is None
    assert x.catalog.path.read_bytes() == original
    result = apply(x, p)
    assert result.backup and not result.already_applied
    with sqlite3.connect(result.backup) as connection:
        assert connection.execute("SELECT external_id FROM sources WHERE id=?", (x.old.id,)).fetchone()[0] == x.old.external_id
    retained = x.catalog.get_source(x.old.id)
    assert retained.external_id == x.new.external_id and retained.available
    assert retained.display_position == x.new.display_position
    assert retained.quota_started_at is not None
    alias = x.catalog.find_source("hanayume", x.old.external_id)
    assert alias.id not in (x.old.id, x.new.id)
    assert alias.item_id == x.old.item_id and not alias.acquisition_enabled
    assert alias.discovery_key == HISTORY_KEY_PREFIX + "repair-test"
    assert alias.quota_started_at is None and alias.access_granted_until is None
    item = x.catalog.get_item(x.old.item_id)
    assert item.status == "completed" and item.item_title == "手動タイトル"
    assert item.note.startswith("手動note\n")
    assert histories(x) == history
    with sqlite3.connect(x.catalog.path) as connection:
        for table, key in (("items", "item_ids"), ("sources", "source_ids"), ("source_targets", "target_ids")):
            assert all(connection.execute(f"SELECT id FROM {table} WHERE id=?", (id_,)).fetchone() is None
                       for id_ in outcome["delete"][key])
    assert x.watchlist.read_bytes() == watch and x.archive.read_bytes() == archive
    after = x.catalog.path.read_bytes()
    assert apply(x, p).already_applied
    assert x.catalog.path.read_bytes() == after
    reconciler = ScopeReconciler(WatchlistService(x.watchlist), x.catalog)
    preview = reconciler.preview(x.work.work_key)
    assert preview.ready, preview.blockers
    reconciler.apply(preview)
    assert not x.catalog.get_source(alias.id).acquisition_enabled
    batch = BatchPlanner(x.catalog, default_policy_registry(), watchlist=WatchlistService(x.watchlist)).plan(site="hanayume")
    assert not batch.candidates
    analysis = load_analysis(x.catalog.path, x.watchlist, x.work.work_key)
    assert not analysis.old and len(analysis.current) == 1
    assert analysis.summary()["履歴保管Source"] == 1


def test_completed_new_wins_without_rebinding_any_history(hanayume_repair_inputs):
    x = hanayume_repair_inputs
    x.history(x.new, x.new_target)
    x.catalog.set_item_status(x.new.item_id, "completed")
    p = plan(x, report(x))
    assert p.entries[0].action == "use_new"
    outcome = migration_preview_payload(p, load_review_report(p.report, x.catalog.path, x.watchlist).analysis)["outcomes"][0]
    assert outcome["current_after"][0]["item_id"] == x.new.item_id
    assert outcome["current_after"][0]["status"] == "completed"
    assert outcome["history_after"][0]["source_id"] == x.old.id
    assert not outcome["history_after"][0]["acquisition_enabled"]
    assert not any(outcome["delete"].values()) and not outcome["add"]
    history = histories(x)
    apply(x, p)
    assert x.catalog.get_source(x.new.id).item_id == x.new.item_id
    assert x.catalog.get_item(x.old.item_id).status == x.catalog.get_item(x.new.item_id).status == "completed"
    assert histories(x) == history
    assert not x.catalog.get_source(x.old.id).acquisition_enabled


@pytest.mark.parametrize("shape", ["split", "merge", "siblings"])
def test_split_merge_and_multiple_sources_can_reference_old_without_fake_completed(hanayume_repair_inputs, shape):
    x = hanayume_repair_inputs
    if shape == "split":
        x.catalog.update_item_metadata(x.new.item_id, order_label="第1話①")
        x.add(102, "第1話②", available=True)
    elif shape == "merge":
        x.catalog.update_item_metadata(x.old.item_id, order_label="第1話①")
        old, _, target = x.add(2, "第1話②", available=False, status="completed")
        x.history(old, target)
    else:
        old, _, target = x.add(2, "第1話", available=False, item=x.catalog.get_item(x.old.item_id))
        x.history(old, target)
    p = plan(x, report(x))
    assert p.ready and p.entries[0].action == "cover_old"
    outcome = migration_preview_payload(p, load_review_report(p.report, x.catalog.path, x.watchlist).analysis)["outcomes"][0]
    assert all(e["status"] == "external" for e in outcome["current_after"])
    assert all(e["status"] == "completed" and not e["acquisition_enabled"] for e in outcome["history_after"])
    assert not any(outcome["delete"].values())
    history = histories(x)
    apply(x, p)
    a = load_analysis(x.catalog.path, x.watchlist, x.work.work_key)
    assert all(e.item.status == "external" and "old Artifact coverage" in e.item.note for e in a.current)
    assert all(e.item.status == "completed" for e in a.entries if e.retired)
    assert histories(x) == history
    assert not BatchPlanner(x.catalog, default_policy_registry(), watchlist=WatchlistService(x.watchlist)).plan(site="hanayume").candidates


@pytest.mark.parametrize("operator_state", ["history", "title", "note"])
def test_donor_history_auto_uses_new_but_explicit_old_keeps_donor_graph(hanayume_repair_inputs, operator_state):
    x = hanayume_repair_inputs
    if operator_state == "history":
        run = x.catalog.create_crawl_run(item_id=x.new.item_id, source_id=x.new.id,
                                        target_id=x.new_target.id, access_strategy="direct")
        x.catalog.mark_crawl_run_failed(run.id, error_type="FixtureError", error_message="synthetic")
    elif operator_state == "title":
        x.catalog.update_item_metadata(x.new.item_id, item_title="新側の手動タイトル")
    else:
        x.catalog.update_item_note(x.new.item_id, "新側の手動note")
    path = report(x)
    p = plan(x, path)
    assert p.ready and p.entries[0].action == "use_new"
    explicit = plan(x, path, choices=((p.entries[0].group_id, "old"),))
    assert explicit.entries[0].action == "cover_old"
    history = histories(x)
    apply(x, explicit)
    assert histories(x) == history and x.catalog.get_source(x.new.id).item_id == x.new.item_id


@pytest.mark.parametrize("fault", ["missing", "size", "hash", "format"])
def test_unusable_old_archive_falls_back_to_new_without_touching_files(hanayume_repair_inputs, fault):
    x = hanayume_repair_inputs
    if fault == "missing":
        x.archive.unlink()
    elif fault in ("size", "hash"):
        data = bytearray(x.archive.read_bytes())
        if fault == "size":
            data.append(0)
        else:
            data[0] ^= 1
        x.archive.write_bytes(data)
    else:
        with x.catalog._connection() as connection:
            connection.execute("UPDATE artifacts SET format='png'")
    path = report(x)
    before = x.archive.read_bytes() if x.archive.exists() else None
    p = plan(x, path)
    assert p.ready and p.entries[0].action == "use_new"
    assert plan(x, path, choices=((p.entries[0].group_id, "old"),)).blockers
    apply(x, p)
    assert x.catalog.get_item(x.new.item_id).status == "pending"
    assert (x.archive.read_bytes() if x.archive.exists() else None) == before


@pytest.mark.parametrize("fault", ["work", "key", "source", "duplicate", "side", "snapshot", "version"])
def test_report_tampering_or_foreign_bindings_are_rejected(hanayume_repair_inputs, fault):
    x = hanayume_repair_inputs
    path = report(x)
    value = json.loads(path.read_text("utf-8"))
    if fault == "work":
        value["analysis"]["work"]["id"] += 1
    elif fault == "key":
        value["analysis"]["entries"][0]["source"]["discovery_key"] = "foreign"
    elif fault == "source":
        value["analysis"]["links"][0]["old_ids"] = [99999]
    elif fault == "duplicate":
        value["analysis"]["links"] *= 2
    elif fault == "side":
        value["analysis"]["links"][0]["old_ids"] = [x.new.id]
    elif fault == "snapshot":
        x.catalog.update_item_note(x.old.item_id, "edited after report")
    else:
        value["version"] = True
    path.write_text(json.dumps(value), "utf-8")
    before = x.catalog.path.read_bytes()
    with pytest.raises(RepairMigrationError):
        plan(x, path)
    assert x.catalog.path.read_bytes() == before


def test_unrelated_work_change_can_rebase_but_apply_token_is_fresh(hanayume_repair_inputs):
    x = hanayume_repair_inputs
    path = report(x)
    p = plan(x, path)
    x.catalog.create_work(WorkInput(work_key="unrelated", title="Other"))
    assert load_review_report(path, x.catalog.path, x.watchlist)
    with pytest.raises(RepairMigrationError, match="変わりました"):
        apply(x, p)
    assert plan(x, path).token != p.token


@pytest.mark.parametrize("change", ["archive", "watchlist", "report", "pending_note", "pending_run"])
def test_preconditions_changed_after_preview_are_not_applied(hanayume_repair_inputs, change):
    x = hanayume_repair_inputs
    pending_old, pending_target, _, _ = pending_pair(x)
    path = report(x)
    p = plan(x, path)
    if change == "archive":
        x.archive.write_bytes(x.archive.read_bytes() + b"changed")
    elif change == "watchlist":
        x.watchlist.write_text(x.watchlist.read_text("utf-8") + "\n# revised\n", "utf-8")
    elif change == "report":
        path.write_text(path.read_text("utf-8") + "\n", "utf-8")
    elif change == "pending_note":
        x.catalog.update_item_note(pending_old.item_id, "concurrent operator note")
    else:
        run = x.catalog.create_crawl_run(item_id=pending_old.item_id, source_id=pending_old.id,
                                       target_id=pending_target.id, access_strategy="direct")
        x.catalog.mark_crawl_run_failed(run.id, error_type="FixtureError", error_message="synthetic")
    before = x.catalog.path.read_bytes()
    with pytest.raises(RepairMigrationError):
        apply(x, p)
    assert x.catalog.path.read_bytes() == before
    assert not (x.catalog.path.parent / "backups").exists()


@pytest.mark.parametrize("fault", ["transaction", "backup", "running", "locked"])
def test_failure_and_lock_do_not_partially_apply(hanayume_repair_inputs, fault, monkeypatch):
    x = hanayume_repair_inputs
    pending_pair(x)
    if fault == "running":
        x.catalog.create_crawl_run(item_id=x.new.item_id, source_id=x.new.id,
                                  target_id=x.new_target.id, access_strategy="direct")
    if fault == "transaction":
        with x.catalog._connection() as connection:
            connection.execute("CREATE TRIGGER fail_receipt BEFORE UPDATE OF note ON items BEGIN SELECT RAISE(ABORT,'fixture rollback'); END")
    p = plan(x, report(x))
    if fault == "running":
        assert not p.ready
    if fault == "backup":
        def fail_backup(*args):
            raise OSError("fixture backup failed")
        monkeypatch.setattr("screenshot_crawler.maintenance.hanayume_migration.backup_catalog", fail_backup)
    before, history = x.catalog.path.read_bytes(), histories(x)
    if fault == "locked":
        import threading

        from screenshot_crawler.catalog.job_lock import CatalogJobLock
        entered, release = threading.Event(), threading.Event()
        def hold():
            with CatalogJobLock(x.catalog.path):
                entered.set()
                release.wait(10)
        thread = threading.Thread(target=hold)
        thread.start()
        assert entered.wait(3)
        try:
            with pytest.raises(RuntimeError, match="Another job"):
                apply(x, p)
        finally:
            release.set()
            thread.join()
    else:
        with pytest.raises((RepairMigrationError, sqlite3.Error, OSError)):
            apply(x, p)
    assert histories(x) == history and x.catalog.path.read_bytes() == before


@pytest.mark.parametrize("config", ["scope", "order", "segments", "old_anchor"])
def test_scope_order_segments_are_preserved_and_old_anchors_block(hanayume_repair_inputs, config):
    x = hanayume_repair_inputs
    target = dict(x.target)
    if config in ("scope", "old_anchor"):
        target["discovery_scope"] = {"from_url": f"https://hanayume.com/episodes/{1 if config == 'old_anchor' else 101:013x}"}
    elif config == "order":
        target["archive_order"] = 1
    else:
        target["archive_segments"] = [{"order": 1, "start_external_id": x.new.external_id}]
    x.watchlist.write_text(yaml.safe_dump({"targets": [target]}), "utf-8")
    before = x.watchlist.read_bytes()
    p = plan(x, report(x))
    assert p.ready == (config != "old_anchor")
    if p.ready:
        apply(x, p)
    assert x.watchlist.read_bytes() == before


def test_unmatched_requires_retirement_and_new_only_remains_pending(hanayume_repair_inputs):
    x = hanayume_repair_inputs
    a = replace(load_analysis(x.catalog.path, x.watchlist, x.work.work_key), links=())
    path = report(x, analysis=a)
    p = plan(x, path)
    assert not p.ready
    old_row = next(e for e in p.entries if e.old_ids)
    p = plan(x, path, choices=((old_row.group_id, "retire"),))
    assert p.ready
    apply(x, p)
    assert x.catalog.get_item(x.new.item_id).status == "pending"


@pytest.mark.parametrize("layout", [None, "order", "segments"])
@pytest.mark.parametrize("cleanup", [False, True])
async def test_full_discovery_after_apply_keeps_history_out_of_batch(hanayume_repair_inputs, layout, cleanup):
    from screenshot_crawler.discovery.base import DiscoveryAdapter
    from screenshot_crawler.discovery.models import (
        DiscoveredItem,
        DiscoveredRecord,
        DiscoveredSource,
    )
    from screenshot_crawler.discovery.registry import DiscoveryAdapterRegistry
    from screenshot_crawler.discovery.service import DiscoveryService

    x = hanayume_repair_inputs
    obsolete, pending_new = None, None
    if cleanup:
        obsolete, _, pending_new, _ = pending_pair(x)
    if layout:
        target_config = dict(x.target)
        if layout == "order":
            target_config["archive_order"] = 1
        else:
            target_config["archive_segments"] = [{"order": 1, "start_external_id": x.new.external_id}]
        x.watchlist.write_text(yaml.safe_dump({"targets": [target_config]}), "utf-8")
    apply(x, plan(x, report(x)))
    class CurrentListing(DiscoveryAdapter):
        site = "hanayume"
        async def iter_records(self, page, target, mode):
            sources = [x.new] + ([pending_new] if cleanup else [])
            ids = [s.external_id for s in sources]
            self.capture_listing_identity_inventory(target=target, external_ids=ids,
                selected_external_ids=set(ids), positions=list(range(1, len(ids) + 1)))
            for position, source in enumerate(sources, 1):
                url = "https://hanayume.com/episodes/" + source.external_id.split(":")[1]
                yield DiscoveredRecord(DiscoveredItem(canonical_title="架空作品", order_label=f"第{position}話"),
                    DiscoveredSource(source.external_id, url, "free", available=True, global_display_position=position))
    registry = DiscoveryAdapterRegistry()
    registry.register("hanayume", CurrentListing)
    target = WatchlistService(x.watchlist).list_targets()[0]
    history = histories(x)
    # Discovery matches the adopted native ID, not the deleted donor's DB ID.
    # Repeated Full listings must keep the acquired graph and never recreate
    # a pending Item for the same current episode.
    for _ in range(2):
        result = await DiscoveryService(x.catalog, registry).discover(object(), target, "full")
        assert result.complete, result.error
        current = x.catalog.find_source("hanayume", x.new.external_id)
        assert current.id == x.old.id and current.item_id == x.old.item_id
        assert x.catalog.get_item(current.item_id).status == "completed"
        with sqlite3.connect(x.catalog.path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM sources WHERE site='hanayume' AND external_id=?",
                                      (x.new.external_id,)).fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM items WHERE work_id=?", (x.work.id,)).fetchone()[0] == (2 if cleanup else 1)
            assert connection.execute("SELECT id FROM sources WHERE id=?", (x.new.id,)).fetchone() is None
            if cleanup:
                assert connection.execute("SELECT id FROM sources WHERE id=?", (obsolete.id,)).fetchone() is None
                assert connection.execute("SELECT id FROM items WHERE id=?", (obsolete.item_id,)).fetchone() is None
                assert x.catalog.find_source("hanayume", pending_new.external_id).id == pending_new.id
        assert histories(x) == history
    alias = x.catalog.find_source("hanayume", x.old.external_id)
    assert not alias.acquisition_enabled
    scope = ScopeReconciler(WatchlistService(x.watchlist), x.catalog)
    preview = scope.preview(x.work.work_key)
    assert preview.ready, preview.blockers
    scope.apply(preview)
    assert not x.catalog.get_source(alias.id).acquisition_enabled
    batch = BatchPlanner(x.catalog, default_policy_registry(), watchlist=WatchlistService(x.watchlist)).plan(site="hanayume")
    assert len(batch.candidates) == (1 if cleanup else 0)
    if cleanup:
        assert batch.candidates[0].item_id == pending_new.item_id


def test_latest_bad_zip_is_not_silently_replaced_by_older_artifact(hanayume_repair_inputs):
    x = hanayume_repair_inputs
    with x.catalog._connection() as connection:
        connection.execute("UPDATE artifacts SET state='missing' WHERE id=(SELECT MAX(id) FROM artifacts)")
    p = plan(x, report(x))
    assert p.ready and p.entries[0].action == "use_new"
    assert "最新ZIP" in " ".join(p.entries[0].reasons)


def test_file_change_after_mutation_rolls_back_every_catalog_change(hanayume_repair_inputs, monkeypatch):
    import screenshot_crawler.maintenance.hanayume_migration as migration
    x = hanayume_repair_inputs
    p = plan(x, report(x))
    before, history = x.catalog.path.read_bytes(), histories(x)
    original = migration._apply_entry
    def inject_change(*args):
        original(*args)
        x.archive.write_bytes(x.archive.read_bytes() + b"external concurrent change")
    monkeypatch.setattr(migration, "_apply_entry", inject_change)
    with pytest.raises(RepairMigrationError, match="ZIP"):
        apply(x, p)
    assert x.catalog.path.read_bytes() == before and histories(x) == history
    assert list((x.catalog.path.parent / "backups").glob("*.sqlite"))


def test_report_duplicate_keys_and_forged_plan_are_rejected(hanayume_repair_inputs):
    x = hanayume_repair_inputs
    path = report(x)
    p = plan(x, path)
    forged = replace(p, entries=(replace(p.entries[0], action="retire"),))
    with pytest.raises(RepairMigrationError, match="plan"):
        apply(x, forged)
    value = path.read_text("utf-8")
    path.write_text(value.replace('"version": 1', '"version": 1, "version": 1', 1), "utf-8")
    with pytest.raises(RepairMigrationError, match="重複key"):
        plan(x, path)
