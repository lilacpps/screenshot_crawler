"""Stage 02 Qt review/apply with synthetic Catalogs; no real-site calls."""

import json
from time import monotonic

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from screenshot_crawler.gui.repair_migration import RepairMigrationDialog
from screenshot_crawler.maintenance.hanayume_repair import export_report, load_analysis


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


def wait(app, predicate):
    deadline = monotonic() + 15
    while not predicate() and monotonic() < deadline:
        app.processEvents()
        QTest.qWait(10)
    assert predicate(), "migration worker did not finish"


@pytest.fixture
def view(hanayume_repair_inputs, qt_app, request):
    x = hanayume_repair_inputs
    if getattr(request, "param", None) == "pending":
        old, item, _ = x.add(2, "第2話", available=False)
        x.catalog.update_item_note(item.id, None)
        new, _, _ = x.add(102, "第2話", available=True)
        x.pending_old, x.pending_new = old, new
    path = x.catalog.path.with_name("review.json")
    export_report(load_analysis(x.catalog.path, x.watchlist, x.work.work_key), path)
    dialog = RepairMigrationDialog(x.catalog.path, x.watchlist, report=path)
    dialog.backup_dir.setText(str(x.catalog.path.parent / "backups"))
    dialog.show()
    wait(qt_app, lambda: dialog.task is None and dialog.plan is not None)
    yield dialog
    wait(qt_app, lambda: dialog.task is None)
    dialog.close()
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def ready(view, app):
    view.accepted.setChecked(True)
    assert view.plan is None and not view.apply_button.isEnabled()
    view.preview_button.click()
    wait(app, lambda: view.task is None)
    assert view.plan.ready and view.apply_button.isEnabled()


def test_read_only_preview_policy_change_export_and_input_invalidation(view, hanayume_repair_inputs, qt_app, monkeypatch, tmp_path):
    x = hanayume_repair_inputs
    before = x.catalog.path.read_bytes(), x.watchlist.read_bytes(), x.archive.read_bytes()
    assert not view.plan.ready and not view.apply_button.isEnabled()
    assert view.table.rowCount() == 1
    assert view.table.item(0, 2).text() == "旧 completed / 新 pending"
    assert f"completed（旧Item #{x.old.item_id} / Source #{x.old.id}）" in view.table.item(0, 4).text()
    assert "新側の空Item/Source/Targetを物理削除" in view.table.item(0, 5).text()
    view.table.selectRow(0)
    assert f"物理削除するItem ID: {x.new.item_id}" in view.explanation.toPlainText()
    assert f"残すSource ID: {x.old.id}" in view.explanation.toPlainText()
    assert "旧episode ID" in view.explanation.toPlainText()
    ready(view, qt_app)
    view.all_new_button.click()
    assert view.plan is None
    assert view.table.item(0, 4).text() == "再プレビュー待ち"
    view.preview_button.click()
    wait(qt_app, lambda: view.task is None)
    assert view.plan.entries[0].action == "use_new"
    assert f"pending（新Item #{x.new.item_id} / Source #{x.new.id}）" in view.table.item(0, 4).text()
    assert "物理削除なし" in view.table.item(0, 5).text()
    out = tmp_path / "preview.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: (str(out), "JSON"))
    view.save_button.click()
    wait(qt_app, lambda: view.task is None)
    saved = json.loads(out.read_text("utf-8"))
    assert saved["ready"] is True
    assert saved["after_summary"]["current_item_statuses"] == {"pending": 1}
    assert saved["outcomes"][0]["delete"]["item_ids"] == []
    assert saved["outcomes"][0]["history_after"][0]["source_id"] == x.old.id
    view.input_changed()
    assert view.review is None and view.plan is None and not view.apply_button.isEnabled()
    assert (x.catalog.path.read_bytes(), x.watchlist.read_bytes(), x.archive.read_bytes()) == before


def test_confirmed_apply_creates_backup_keeps_old_history_and_disables_repeat(view, hanayume_repair_inputs, qt_app, monkeypatch):
    x = hanayume_repair_inputs
    ready(view, qt_app)
    before = x.catalog.path.read_bytes()
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.No)
    view.apply_button.click()
    assert x.catalog.path.read_bytes() == before and view.plan is not None
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    emitted = []
    view.catalogChanged.connect(lambda: emitted.append(True))
    view.apply_button.click()
    wait(qt_app, lambda: view.task is None)
    assert emitted and "移行完了" in view.status.text()
    assert view.plan is None and not view.apply_button.isEnabled()
    assert list((x.catalog.path.parent / "backups").glob("*.sqlite"))
    assert x.catalog.get_source(x.old.id).external_id == x.new.external_id
    assert x.catalog.get_item(x.old.item_id).status == "completed"


@pytest.mark.parametrize("view", ["pending"], indirect=True)
def test_pending_cleanup_preview_and_confirmed_apply(view, hanayume_repair_inputs, qt_app, monkeypatch):
    x = hanayume_repair_inputs
    row = next(i for i, e in enumerate(view.plan.entries) if x.pending_old.id in e.old_ids)
    before = x.catalog.path.read_bytes()
    view.table.selectRow(row)
    assert view.table.item(row, 2).text() == "旧 pending / 新 pending"
    assert f"pending（新Item #{x.pending_new.item_id}" in view.table.item(row, 4).text()
    assert "旧pendingの空Item/Source/Targetを物理削除" in view.table.item(row, 5).text()
    assert f"物理削除するItem ID: {x.pending_old.item_id}" in view.explanation.toPlainText()
    assert f"残すItem ID: {x.pending_new.item_id}" in view.explanation.toPlainText()
    assert "旧pending 1" in view.after_summary.text()
    assert x.catalog.path.read_bytes() == before and not view.apply_button.isEnabled()
    ready(view, qt_app)
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    view.apply_button.click()
    wait(qt_app, lambda: view.task is None)
    assert "移行完了" in view.status.text()
    assert x.catalog.find_source("hanayume", x.pending_old.external_id) is None
    assert x.catalog.get_source(x.pending_new.id).item_id == x.pending_new.item_id
    assert x.catalog.get_item(x.pending_new.item_id).status == "pending"


def test_hold_blocks_apply_and_failure_never_claims_success(view, hanayume_repair_inputs, qt_app, monkeypatch):
    ready(view, qt_app)
    combo = next(iter(view.combos.values()))
    combo.setCurrentIndex(combo.findData("hold"))
    view.preview_button.click()
    wait(qt_app, lambda: view.task is None)
    assert not view.plan.ready and not view.apply_button.isEnabled()
    combo.setCurrentIndex(combo.findData("auto"))
    view.preview_button.click()
    wait(qt_app, lambda: view.task is None)
    before = hanayume_repair_inputs.catalog.path.read_bytes()
    def fail(*args, **kwargs):
        raise RuntimeError("fixture precondition failure")
    monkeypatch.setattr("screenshot_crawler.gui.repair_migration.apply_migration_plan", fail)
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    view.apply_button.click()
    wait(qt_app, lambda: view.task is None)
    assert "fixture precondition failure" in view.status.text()
    assert view.plan is None and hanayume_repair_inputs.catalog.path.read_bytes() == before


def test_busy_close_and_bad_reload_preserve_original_data(view, hanayume_repair_inputs, qt_app, monkeypatch):
    tasks = []
    monkeypatch.setattr(QThreadPool, "start", lambda self, task: tasks.append(task))
    view.preview_button.click()
    assert tasks and not view.close()
    view.failed("fixture cancelled")
    monkeypatch.undo()
    view.report_path.setText(str(hanayume_repair_inputs.catalog.path.parent / "missing.json"))
    view.load_button.click()
    wait(qt_app, lambda: view.task is None)
    assert view.review is None and view.plan is None
    assert not view.preview_button.isEnabled() and not view.apply_button.isEnabled()
