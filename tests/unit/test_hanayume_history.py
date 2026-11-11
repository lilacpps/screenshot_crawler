"""ZIP separation uses synthetic archives and Catalogs only."""

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from screenshot_crawler.maintenance.hanayume_history import (
    HistoryMoveError,
    apply_history_plan,
    build_history_plan,
)
from screenshot_crawler.maintenance.hanayume_migration import (
    apply_migration_plan,
    build_migration_plan,
)
from screenshot_crawler.maintenance.hanayume_repair import export_report, load_analysis


@pytest.fixture
def history_inputs(hanayume_repair_inputs):
    x = hanayume_repair_inputs
    x.history(x.new, x.new_target)
    x.catalog.set_item_status(x.new.item_id, "completed")
    x.library = x.catalog.path.parent / "Books"
    x.history_root = x.catalog.path.parent / "Books-history"
    x.library.mkdir()
    x.old_zip, x.new_zip = x.library / "001-old.zip", x.library / "001-new.zip"
    x.old_zip.write_bytes(x.archive.read_bytes())
    x.new_zip.write_bytes(x.archive.read_bytes())
    x.catalog.update_artifact_locators({a.id: (a.locator, str(x.old_zip if a.item_id == x.old.item_id else x.new_zip))
                                      for a in x.catalog.list_artifacts()})
    x.report = x.catalog.path.parent / "review.json"
    export_report(load_analysis(x.catalog.path, x.watchlist, x.work.work_key), x.report)
    x.migration = build_migration_plan(x.catalog.path, x.watchlist, x.report, accepted=True)
    return x


def migrate(x):
    apply_migration_plan(x.migration, expected_token=x.migration.token, backup_dir=x.catalog.path.parent / "migration-backups")


def plan(x, **kwargs):
    return build_history_plan(x.catalog.path, x.work.work_key, library_root=x.library, history_root=x.history_root, **kwargs)


def apply(x, p):
    return apply_history_plan(p, expected_token=p.token, backup_dir=x.catalog.path.parent / "history-backups")


def rows(x):
    with sqlite3.connect(x.catalog.path) as connection:
        return {t: connection.execute(f"SELECT * FROM {t} ORDER BY id").fetchall()
                for t in ("items", "sources", "source_targets", "crawl_runs", "quota_resource_states")}


def test_projection_is_read_only_and_never_applicable(history_inputs):
    x = history_inputs
    before = x.catalog.path.read_bytes(), x.old_zip.read_bytes(), x.watchlist.read_bytes()
    p = plan(x, migration=x.migration)
    assert not p.ready and not p.blockers and len(p.moves) == 1
    assert len(p.moves[0].artifact_ids) == 2
    assert x.catalog.path.read_bytes() == before[0] and not x.history_root.exists()
    with pytest.raises(HistoryMoveError, match="投影"):
        apply(x, p)
    assert before == (x.catalog.path.read_bytes(), x.old_zip.read_bytes(), x.watchlist.read_bytes())


def test_history_zip_moves_all_alias_locators_preserving_graph_bytes_and_replay(history_inputs):
    x = history_inputs
    migrate(x)
    before, watch, old, current = rows(x), x.watchlist.read_bytes(), x.old_zip.read_bytes(), x.new_zip.read_bytes()
    p = plan(x)
    assert p.ready and len(p.moves) == 1
    assert any(e.status == "keep_current" for e in p.entries)
    e = p.moves[0]
    assert Path(e.new_path).is_relative_to(x.history_root) and Path(e.new_path).name == x.old_zip.name
    result = apply(x, p)
    assert result.moved == 1 and not x.old_zip.exists()
    assert Path(e.new_path).read_bytes() == old and x.new_zip.read_bytes() == current
    assert rows(x) == before and x.watchlist.read_bytes() == watch
    assert all(x.catalog.get_artifact(id_).locator == e.new_path for id_ in e.artifact_ids)
    with sqlite3.connect(result.backup) as connection:
        assert connection.execute("SELECT locator FROM artifacts WHERE id=?", (e.artifact_ids[0],)).fetchone()[0] == str(x.old_zip)
    assert json.loads(Path(result.manifest).read_text("utf-8"))["state"] == "completed"
    assert apply(x, p).already_applied
    assert not plan(x).moves and any(e.status == "already_history" for e in plan(x).entries)
    assert not list(x.catalog.path.parent.glob("*.hanayume-history-recovery.json"))


@pytest.mark.parametrize("reuse", ["identity", "coverage"])
def test_current_reuse_or_coverage_zip_stays_in_library(hanayume_repair_inputs, reuse):
    x = hanayume_repair_inputs
    if reuse == "coverage":
        x.catalog.update_item_note(x.new.item_id, "新側手動note")
    report = x.catalog.path.parent / "review.json"
    export_report(load_analysis(x.catalog.path, x.watchlist, x.work.work_key), report)
    p = build_migration_plan(x.catalog.path, x.watchlist, report, accepted=True)
    if reuse == "coverage":
        p = build_migration_plan(x.catalog.path, x.watchlist, report, accepted=True, choices=((p.entries[0].group_id, "old"),))
    apply_migration_plan(p, expected_token=p.token, backup_dir=x.catalog.path.parent / "backups")
    h = build_history_plan(x.catalog.path, x.work.work_key, library_root=x.catalog.path.parent,
                           history_root=x.catalog.path.parent.parent / (x.catalog.path.parent.name + "-history"))
    assert h.ready and not h.moves and h.entries[0].status == "keep_current"
    assert x.archive.exists()


@pytest.mark.parametrize("fault", ["missing", "hash", "destination", "outside", "link", "network", "stale", "forged"])
def test_unsafe_or_stale_move_never_mutates_files_or_catalog(history_inputs, fault, monkeypatch):
    x = history_inputs
    migrate(x)
    p = plan(x)
    if fault == "missing":
        x.old_zip.unlink()
    elif fault == "hash":
        x.old_zip.write_bytes(x.old_zip.read_bytes() + b"modified")
    elif fault == "destination":
        dst = Path(p.moves[0].new_path)
        dst.parent.mkdir(parents=True)
        dst.write_bytes(b"existing user file")
    elif fault == "outside":
        x.library = x.library / "wrong"
        p = plan(x)
    elif fault == "link":
        original = Path.is_symlink
        monkeypatch.setattr(Path, "is_symlink", lambda self: self == x.old_zip or original(self))
        p = plan(x)
    elif fault == "network":
        for a in x.catalog.list_artifacts(item_id=x.old.item_id):
            x.catalog.update_artifact_locators({a.id: (a.locator, "\\\\nonexistent-server\\share\\old.zip")})
        p = plan(x)
    elif fault == "stale":
        x.catalog.update_item_note(x.old.item_id, "concurrent edit")
    else:
        p = replace(p, history_root=str(x.catalog.path.parent))
    before, content = x.catalog.path.read_bytes(), x.old_zip.read_bytes() if x.old_zip.exists() else None
    with pytest.raises((HistoryMoveError, ValueError)):
        apply(x, p)
    assert x.catalog.path.read_bytes() == before
    assert (x.old_zip.read_bytes() if x.old_zip.exists() else None) == content
    if fault == "destination":
        assert dst.read_bytes() == b"existing user file"


def test_shared_active_artifact_path_is_not_moved(history_inputs):
    x = history_inputs
    migrate(x)
    artifact = x.catalog.list_artifacts(item_id=x.new.item_id)[0]
    x.catalog.update_artifact_locators({artifact.id: (artifact.locator, str(x.old_zip))})
    p = plan(x)
    assert p.ready and not p.moves and any(e.status == "keep_shared" for e in p.entries)


def test_later_file_failure_restores_earlier_moved_zip(history_inputs, monkeypatch):
    import screenshot_crawler.maintenance.hanayume_history as history

    x = history_inputs
    migrate(x)
    artifact = x.catalog.list_artifacts(item_id=x.old.item_id)[0]
    older = x.library / "older.zip"
    older.write_bytes(x.old_zip.read_bytes())
    x.catalog.update_artifact_locators({artifact.id: (artifact.locator, str(older))})
    p = plan(x)
    assert len(p.moves) == 2
    before = x.catalog.path.read_bytes()
    original = history._transfer
    calls = []
    def transfer(old, new):
        calls.append((old, new))
        if len(calls) == 2:
            raise OSError("fixture second file failure")
        original(old, new)
    monkeypatch.setattr(history, "_transfer", transfer)
    with pytest.raises(HistoryMoveError, match="復元しました"):
        apply(x, p)
    assert len(calls) == 3 and x.catalog.path.read_bytes() == before
    assert older.read_bytes() == x.old_zip.read_bytes()
    assert all(not Path(e.new_path).exists() for e in p.moves)


@pytest.mark.parametrize("fault", ["link", "after_link", "db", "restore"])
def test_move_failure_restores_or_leaves_explicit_recovery_journal(history_inputs, fault, monkeypatch):
    import screenshot_crawler.maintenance.hanayume_history as history

    x = history_inputs
    migrate(x)
    p = plan(x)
    before, content = x.catalog.path.read_bytes(), x.old_zip.read_bytes()
    if fault == "db":
        with x.catalog._connection() as connection:
            connection.execute("CREATE TRIGGER fail_locator BEFORE UPDATE OF locator ON artifacts BEGIN SELECT RAISE(ABORT,'fixture DB failure'); END")
        p, before = plan(x), x.catalog.path.read_bytes()
    else:
        original_link = history.os.link
        def link(old, new, **kwargs):
            if fault == "link":
                raise OSError("fixture link failure")
            original_link(old, new, **kwargs)
            raise OSError("fixture interruption after link")
        monkeypatch.setattr(history.os, "link", link)
        if fault == "restore":
            monkeypatch.setattr(history, "_restore_files", lambda entries: (_ for _ in ()).throw(OSError("fixture restoration failed")))
    with pytest.raises(HistoryMoveError, match="RECOVERY_REQUIRED" if fault == "restore" else "復元しました"):
        apply(x, p)
    assert x.catalog.path.read_bytes() == before and x.old_zip.read_bytes() == content
    journal = Path(str(x.catalog.path) + ".hanayume-history-recovery.json")
    if fault == "restore":
        assert journal.is_file()
        with pytest.raises(HistoryMoveError, match="RECOVERY_REQUIRED"):
            apply(x, p)
    else:
        assert not journal.exists() and not Path(p.moves[0].new_path).exists()
