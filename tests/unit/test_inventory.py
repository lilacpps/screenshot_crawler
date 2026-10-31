"""Inventory invariants, existing-policy parity and non-mutating local reads."""

import hashlib
import sqlite3
from dataclasses import FrozenInstanceError, replace
from datetime import datetime

import pytest
import yaml

from screenshot_crawler.catalog.service import JST, CatalogService
from screenshot_crawler.management.catalog_reader import CatalogInventoryReader, InventoryLoadError
from screenshot_crawler.management.inventory import (
    InventoryService,
    _access,
    default_policy_registry,
    display_time,
)
from screenshot_crawler.watchlist.reconcile import ScopeReconciler
from screenshot_crawler.watchlist.service import WatchlistService
from tools.gui_sample import create_sample

NOW = datetime(2026, 10, 23, 12, tzinfo=JST)


@pytest.fixture
def inventory_inputs(tmp_path):
    db, watchlist = create_sample(tmp_path / "inputs")
    return db, watchlist


def load(inputs, **kwargs):
    return InventoryService().load(*inputs, now=NOW, runtime_path="missing-runtime", **kwargs)


def fingerprints(paths):
    return {str(path): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
            for path in paths}


def test_snapshot_invariants_scope_unmanaged_and_immutable(inventory_inputs):
    snapshot = load(inventory_inputs)
    assert snapshot.watchlist_revision == WatchlistService(inventory_inputs[1]).revision()
    assert len(snapshot.sources) == 96
    assert len(snapshot.keys) == 10
    keys = {key.identity: key for key in snapshot.keys}
    assert keys["not-discovered"].summary.counts is None
    assert keys["not-discovered"].summary.sync_status == "missing_work"
    assert keys["sample-0004"].summary.sync_status == "synced"
    assert keys["sample-0000"].summary.sync_status == "synced"
    assert keys["sample-0003"].target.enabled is False
    assert any(key.target is None and key.summary.sync_status == "unmanaged"
               for key in snapshot.keys)
    for summary in [key.summary for key in snapshot.keys] + list(snapshot.summaries.values()):
        c = summary.counts
        if c:
            assert c.total_assigned == sum((c.completed, c.external, c.skipped, c.direct,
                                            c.quota, c.paid, c.unavailable, c.unknown))
    c = keys["sample-0004"].summary.counts
    assert (c.total_assigned, c.completed, c.external, c.skipped, c.out_of_scope) == (11, 4, 2, 1, 1)
    assert (c.direct, c.quota, c.paid, c.unknown) == (1, 1, 1, 1)
    assert snapshot.latest_runs[2].status == "succeeded"
    assert snapshot.artifacts[2][0].locator.endswith("002-synthetic.zip")
    with pytest.raises(TypeError):
        snapshot.sources[1] = snapshot.sources[2]
    with pytest.raises(FrozenInstanceError):
        keys["sample-0004"].label = "changed"


def test_no_write_capability_and_one_read_transaction(inventory_inputs, tmp_path, monkeypatch):
    db, watchlist = inventory_inputs
    zip_path, status, metrics = (tmp_path / name for name in ("sentinel.zip", "status.json", "m.json"))
    for path in (zip_path, status, metrics):
        path.write_bytes(b"sentinel")
    before = fingerprints((db, watchlist, zip_path, status, metrics))
    statements, connections = [], []
    connect = sqlite3.connect

    def readonly_connect(path, **kwargs):
        assert str(path).endswith("?mode=ro") and kwargs["uri"] is True
        connection = connect(path, **kwargs)
        connection.set_trace_callback(statements.append)
        connections.append(connection)
        return connection

    def forbidden(*args, **kwargs):
        pytest.fail("write-capable Catalog/Scope API reached")

    monkeypatch.setattr(sqlite3, "connect", readonly_connect)
    monkeypatch.setattr(CatalogService, "__init__", forbidden)
    monkeypatch.setattr(ScopeReconciler, "apply", forbidden)
    snapshot = load(inventory_inputs)
    assert snapshot.archive_positions  # ordered scopes validated entirely in memory
    assert len(connections) == 1 and statements.count("BEGIN") == 1
    assert not any(statement.lstrip().upper().startswith(
        ("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP")) for statement in statements)
    assert fingerprints((db, watchlist, zip_path, status, metrics)) == before


@pytest.mark.parametrize("case", ["missing_db", "old", "corrupt", "missing_watchlist", "bad_watchlist"])
def test_invalid_inputs_never_create_or_migrate(inventory_inputs, case):
    db, watchlist = inventory_inputs
    if case == "missing_db":
        db = db.with_name("does-not-exist.sqlite")
    elif case == "old":
        with sqlite3.connect(db) as connection:
            connection.execute("PRAGMA user_version=6")
    elif case == "corrupt":
        db.write_bytes(b"not SQLite")
    elif case == "missing_watchlist":
        watchlist = watchlist.with_name("absent.yaml")
    else:
        watchlist.write_text("targets: invalid", "utf-8")
    before = fingerprints([path for path in (db, watchlist) if path.exists()])
    with pytest.raises(InventoryLoadError):
        load((db, watchlist))
    assert fingerprints([path for path in (db, watchlist) if path.exists()]) == before


@pytest.mark.parametrize("site", default_policy_registry().sites())
def test_existing_policy_classification_matrix(inventory_inputs, site):
    source = CatalogInventoryReader().read(inventory_inputs[0]).sources[0]
    policy = default_policy_registry().create(site)
    base = replace(source, site=site, access_mode="quota", available=True,
                   access_granted_until=None,
                   external_id="KC_000001_S:KC_0000010000000001_E")
    for mode in ("free", "quota", "paid", "unknown", "owned"):
        for available in (True, False):
            for grant in (None, "2026-10-24T12:00:00+09:00", "2026-10-22T12:00:00+09:00"):
                candidate = replace(base, access_mode=mode, available=available,
                                    access_granted_until=grant)
                result = _access(policy, candidate, NOW)
                decision = policy.evaluate(candidate, now=NOW, quota_available=None)
                if decision.eligible:
                    assert result.category == decision.access_strategy
                elif decision.pending_quota:
                    assert result.category == "quota"
                elif decision.reason in {"paid", "expired_rental"}:
                    assert result.category == "paid"
                elif decision.reason in {"unavailable", "expired_free"}:
                    assert result.category == "unavailable"
                else:
                    assert result.category == "unknown"
                assert result.reason == decision.reason


def test_policy_registry_matches_cli_and_errors_stay_unknown(inventory_inputs):
    from screenshot_crawler.cli import _batch_policy_registry
    assert default_policy_registry().sites() == _batch_policy_registry().sites()
    data = CatalogInventoryReader().read(inventory_inputs[0])
    policy = default_policy_registry().create("mangaone")
    candidate = replace(data.sources[0], site="mangaone", access_mode="quota",
                        access_granted_until="invalid")
    result = _access(policy, candidate, NOW)
    assert result.category == "unknown" and "計算不能" in result.reason
    for value in (None, "invalid", "2026-10-23T00:00:00"):
        assert display_time(value) in {"—", "不明（日時不正）"}
    assert display_time("2026-10-23T00:00:00+00:00") == "2026-10-23 09:00 JST"


def test_expiry_paid_rental_multiple_resources_and_site_slots(inventory_inputs):
    source = CatalogInventoryReader().read(inventory_inputs[0]).sources[0]
    registry = default_policy_registry()
    candidate = replace(source, access_mode="paid", access_granted_until="2026-10-24T00:00:00+09:00")
    assert _access(registry.create("jumpplus"), candidate, NOW).category == "direct"
    candidate = replace(candidate, access_granted_until="2026-10-22T00:00:00+09:00")
    assert _access(registry.create("jumpplus"), candidate, NOW).category == "paid"
    candidate = replace(candidate, site="kadocomi", access_mode="free",
                        external_id="KC_000001_S:KC_0000010000000001_E",
                        free_until="2026-10-22T00:00:00+09:00")
    assert _access(registry.create("kadocomi"), candidate, NOW).category == "unavailable"
    candidate = replace(candidate, site="magapoke", access_mode="quota", free_until=None)
    classified = _access(registry.create("magapoke"), candidate, NOW)
    assert classified.category == "quota"
    assert classified.resources == ("work_ticket", "premium_ticket")
    db, _ = inventory_inputs
    with sqlite3.connect(db) as connection:
        connection.execute("UPDATE sources SET quota_started_at=? WHERE site='mangaone'", (NOW.isoformat(),))
    snapshot = load(inventory_inputs)
    assert snapshot.resources["mangaone"].available_quota == 0
    assert snapshot.summaries[("site", "mangaone")].counts.quota == 2


@pytest.mark.parametrize("mutation", ["digest", "position", "flag", "binding", "proof", "sync"])
def test_scope_never_fakes_success(inventory_inputs, mutation):
    db, watchlist = inventory_inputs
    with sqlite3.connect(db) as connection:
        if mutation == "digest":
            connection.execute("UPDATE discovery_inventory_evidence SET inventory_digest='invalid' WHERE discovery_key='sample-0004'")
        elif mutation == "position":
            connection.execute("UPDATE sources SET display_position=999 WHERE id=49")
        elif mutation == "flag":
            connection.execute("UPDATE sources SET acquisition_enabled=0 WHERE id=49")
        elif mutation == "proof":
            connection.execute("DELETE FROM discovery_inventory_positions WHERE discovery_key='sample-0004'")
            connection.execute("DELETE FROM discovery_inventory_evidence WHERE discovery_key='sample-0004'")
        elif mutation == "sync":
            connection.execute("DELETE FROM acquisition_scope_sync WHERE work_id=2")
        else:
            connection.execute("UPDATE sources SET site='magapoke' WHERE id=49")
    snapshot = load((db, watchlist))
    key = next(k for k in snapshot.keys if k.identity == "sample-0004")
    if mutation in {"flag", "binding"}:
        assert key.summary.sync_status != "synced" and key.summary.diagnostics
    else:
        assert key.summary.sync_status == "synced"
    assert not any("削除した登録" in note for row in snapshot.keys for note in row.summary.diagnostics)


def test_ambiguous_sources_dedup_and_not_discovered(inventory_inputs):
    db, watchlist = inventory_inputs
    with sqlite3.connect(db) as connection:
        # Source 53 is a pending free Item. Add a second paid Source under another key.
        connection.execute(
            "INSERT INTO sources SELECT 999,item_id,'magapoke','999','sample-0005','paid',"
            "free_until,available,access_checked_at,last_seen_at,quota_started_at,"
            "NULL,published_at,created_at,updated_at,NULL,1 FROM sources WHERE id=53"
        )
    snapshot = load(inventory_inputs)
    parent = snapshot.summaries[("work", "sample-work-0001")]
    assert parent.counts.total_assigned == 44  # 4*11, not 45
    assert any("ambiguous" in note for note in parent.diagnostics)
    assert any("複数key" in note for note in parent.diagnostics)
    raw = yaml.safe_load(watchlist.read_text("utf-8"))
    raw["targets"].append({"key": "new-key", "work_key": "new-work", "site": "new-site",
                           "url": "https://example.invalid/new", "label": "new"})
    watchlist.write_text(yaml.safe_dump(raw), "utf-8")
    snapshot = load(inventory_inputs)
    assert snapshot.resources["new-site"].diagnostics


def test_retry_only_policy_evidence_and_configuration(inventory_inputs, tmp_path):
    db, watchlist = inventory_inputs
    config = tmp_path / "runtime.yaml"
    config.write_text("sites:\n  zeblack:\n    work_ticket_cooldown_hours: 30\n", "utf-8")
    snapshot = InventoryService().load(db, watchlist, now=NOW, runtime_path=config)
    grant = next(g for g in snapshot.grants if g.site == "zeblack" and g.work_key == "sample-work-0000")
    assert grant.retry_at == "2026-10-24T16:00:00+09:00"
    assert grant.reason == "work_ticket_cooldown"
    assert all(g.retry_at is None for g in snapshot.grants if g.site == "magapoke")


@pytest.mark.parametrize("proven_empty", [False, True])
def test_missing_sources_with_proof_are_unknown_unless_proven_empty(inventory_inputs, proven_empty):
    db, _ = inventory_inputs
    with sqlite3.connect(db) as connection:
        connection.execute("DELETE FROM source_targets WHERE source_id BETWEEN 49 AND 60")
        connection.execute("DELETE FROM sources WHERE id BETWEEN 49 AND 60")
        if proven_empty:
            connection.execute("DELETE FROM discovery_inventory_positions WHERE discovery_key='sample-0004'")
            connection.execute(
                "UPDATE discovery_inventory_evidence SET source_count=0,inventory_digest=? "
                "WHERE discovery_key='sample-0004'", (hashlib.sha256(b'[]').hexdigest(),),
            )
    key = next(k for k in load(inventory_inputs).keys if k.identity == "sample-0004")
    if proven_empty:
        assert key.summary.sync_status == "synced"
        assert key.summary.counts.total_assigned == 0
    else:
        assert key.summary.counts is None
        assert key.summary.diagnostics


def test_cli_and_gui_missing_qt_dependency_in_subprocess():
    import subprocess
    import sys
    code = '''
import builtins
import sys
original = builtins.__import__
def guard(name, *args, **kwargs):
    if name.startswith(('PySide6', 'shiboken6')):
        raise ModuleNotFoundError('No module named PySide6')
    return original(name, *args, **kwargs)
builtins.__import__ = guard
from screenshot_crawler.cli import main
sys.argv = ['screenshot-crawler', '--help']
try:
    main()
except SystemExit as error:
    assert error.code == 0
from screenshot_crawler.gui import main as gui_main
assert gui_main([]) == 2
'''
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=30, check=False
    )
    assert result.returncode == 0, result.stderr
    assert "PySide6" in result.stderr and "gui" in result.stderr


def test_wal_is_rejected_without_mutating_shared_memory(inventory_inputs):
    db, watchlist = inventory_inputs
    with sqlite3.connect(db) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("UPDATE sources SET access_checked_at=? WHERE id=1", (NOW.isoformat(),))
        writer.commit()
        files = (db, watchlist, db.with_name(db.name + "-wal"), db.with_name(db.name + "-shm"))
        before = fingerprints(files)
        with pytest.raises(InventoryLoadError, match="WAL"):
            load(inventory_inputs)
        assert fingerprints(files) == before


@pytest.mark.parametrize("change", ["range", "order", "removed", "identity"])
def test_pending_range_is_key_local_and_numbering_never_requires_scope_sync(inventory_inputs, change):
    from screenshot_crawler.cli import _require_selected_scope_sync
    from screenshot_crawler.management.execution import ExecutionPlanService

    db, watchlist = inventory_inputs
    raw = yaml.safe_load(watchlist.read_text("utf-8"))
    if change == "range":
        raw["targets"][4]["discovery_scope"] = {"through_url": "https://example.invalid/new-end"}
    elif change == "order":
        raw["targets"][4]["archive_order"], raw["targets"][5]["archive_order"] = 2, 1
    elif change == "removed":
        raw["targets"] = [t for t in raw["targets"] if t["key"] != "sample-0004"]
    else:
        with sqlite3.connect(db) as connection:
            connection.execute("UPDATE sources SET site='magapoke' WHERE discovery_key='sample-0004'")
    watchlist.write_text(yaml.safe_dump(raw), "utf-8")
    before = fingerprints((db, watchlist))
    loaded = load(inventory_inputs)
    keys = {key.identity: key for key in loaded.keys}
    assert keys["sample-0005"].summary.sync_status == "synced"
    if change == "removed":
        removed = [key for key in loaded.keys if key.target is None and "scope-sync" in " ".join(key.summary.diagnostics)]
        assert len(removed) == 1 and removed[0].summary.sync_status == "stale"
        assert "削除した登録" in removed[0].summary.diagnostics[0]
    elif change == "identity":
        from screenshot_crawler.batch.models import BatchPlanningError

        assert keys["sample-0004"].summary.sync_status == "binding_mismatch"
        with pytest.raises(BatchPlanningError, match="Work/site identity"):
            _require_selected_scope_sync(
                CatalogService(db), WatchlistService(watchlist),
                site="mangaone", selected_keys=("sample-0004",),
            )
    else:
        assert keys["sample-0004"].summary.sync_status == ("stale" if change == "range" else "synced")
        if change == "range":
            assert "取得範囲" in keys["sample-0004"].summary.diagnostics[0]
        preview = ExecutionPlanService().preview(
            loaded, ["sample-0004"], action="batch", runtime_path="missing-runtime",
        )
        assert preview.can_confirm
        _require_selected_scope_sync(
            CatalogService(db), WatchlistService(watchlist),
            site="mangaone", selected_keys=("sample-0004",),
        )
    assert fingerprints((db, watchlist)) == before
