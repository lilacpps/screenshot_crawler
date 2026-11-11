"""History ZIP dialog with synthetic archives; no site or production writes."""

import json
from pathlib import Path
from time import monotonic

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from screenshot_crawler.gui.repair_history import RepairHistoryDialog
from screenshot_crawler.maintenance.hanayume_migration import (
    apply_migration_plan,
    build_migration_plan,
)
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
    assert predicate()


@pytest.mark.parametrize("projected", [False, True])
def test_history_preview_export_and_explicit_apply_or_projection_guard(hanayume_repair_inputs, qt_app, tmp_path, monkeypatch, projected):
    x = hanayume_repair_inputs
    # Make only the historical Item reference old.zip; new Item keeps its own file.
    x.history(x.new, x.new_target)
    x.catalog.set_item_status(x.new.item_id, "completed")
    new_zip = tmp_path / "new.zip"
    new_zip.write_bytes(x.archive.read_bytes())
    x.catalog.update_artifact_locators({a.id: (a.locator, str(new_zip)) for a in x.catalog.list_artifacts(item_id=x.new.item_id)})
    report = tmp_path / "review.json"
    export_report(load_analysis(x.catalog.path, x.watchlist, x.work.work_key), report)
    migration = build_migration_plan(x.catalog.path, x.watchlist, report, accepted=True)
    if not projected:
        apply_migration_plan(migration, expected_token=migration.token, backup_dir=tmp_path / "migration-backups")
    before, old_bytes = x.catalog.path.read_bytes(), x.archive.read_bytes()
    root = tmp_path.parent / (tmp_path.name + "-history")
    dialog = RepairHistoryDialog(x.catalog.path, x.work.work_key, migration=migration if projected else None,
                                 library_root=tmp_path, history_root=root)
    dialog.backup_dir.setText(str(tmp_path / "history-backups"))
    dialog.show()
    try:
        wait(qt_app, lambda: dialog.task is None and dialog.plan is not None)
        assert len(dialog.plan.moves) == 1
        assert "移動先:" in dialog.details.toPlainText()
        assert dialog.apply_button.isEnabled() is not projected
        assert x.catalog.path.read_bytes() == before and x.archive.read_bytes() == old_bytes
        out = tmp_path / "history-preview.json"
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(out), "JSON"))
        dialog.save_button.click()
        wait(qt_app, lambda: dialog.task is None)
        assert json.loads(out.read_text("utf-8"))["ready"] is not projected
        if projected:
            assert dialog.plan.projected_migration_token == migration.token
            dialog.apply()
            assert x.archive.exists() and x.catalog.path.read_bytes() == before
            dialog.actual_button.click()
            wait(qt_app, lambda: dialog.task is None)
            assert not dialog.plan.moves and not dialog.apply_button.isEnabled()
        else:
            destination = dialog.plan.moves[0].new_path
            monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
            dialog.apply_button.click()
            assert x.archive.exists()
            monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
            changed = []
            dialog.catalogChanged.connect(lambda: changed.append(True))
            dialog.apply_button.click()
            wait(qt_app, lambda: dialog.task is None)
            assert changed and "分離しました" in dialog.status.text()
            assert not x.archive.exists() and Path(destination).read_bytes() == old_bytes
            assert new_zip.read_bytes() == old_bytes and not dialog.apply_button.isEnabled()
    finally:
        wait(qt_app, lambda: dialog.task is None)
        dialog.close()
        dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
