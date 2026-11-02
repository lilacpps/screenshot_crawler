import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from screenshot_crawler.catalog import CatalogService
from screenshot_crawler.cli import _discovery_registry
from screenshot_crawler.gui.url_registration import UrlRegistrationDialog
from screenshot_crawler.registration.draft import BatchRegistrationDraft
from screenshot_crawler.registration.resolver import UrlResolver

A = "https://shonenjumpplus.com/episode/123"
B = "https://comic-days.com/episode/456"
K = "https://comic-walker.com/detail/KC_004915_S"


def wait_for(predicate):
    deadline = time.monotonic() + 15
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)
    assert predicate()


@pytest.fixture
def gui(tmp_path, monkeypatch):
    from screenshot_crawler.core.browser import BrowserSession
    async def no_cdp(*args, **kwargs):
        raise RuntimeError("synthetic CDP unavailable")
    monkeypatch.setattr(BrowserSession, "connect", no_cdp)
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    path, runtime = tmp_path / "watchlist.yaml", tmp_path / "runtime.yaml"
    path.write_text("targets: []\n", encoding="utf-8")
    runtime.write_text("{}\n", encoding="utf-8")
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    catalog.initialize()
    draft = BatchRegistrationDraft((), "revision", UrlResolver(_discovery_registry()))
    dialog = UrlRegistrationDialog(path, catalog.path, runtime, draft=draft)
    dialog.metadata.setChecked(False)
    dialog.show()
    app.processEvents()
    yield dialog, app
    dialog.pool.waitForDone(15000)
    app.processEvents()
    dialog.dirty = False
    dialog.close()
    dialog.deleteLater()


def populate(dialog, text):
    dialog.input.setPlainText(text)
    dialog.analyze()
    wait_for(lambda: dialog.task is None)


def confirm(dialog, label="人工作品", work="test_work"):
    dialog.label_edit.setText(label)
    dialog.work_edit.setText(work)
    dialog.confirm()


def test_paste_partial_failure_manual_confirmation_and_no_write(gui):
    dialog, _app = gui
    before = dialog.path.read_bytes(), dialog.catalog.read_bytes()
    populate(dialog, f"{A}\n\n{B}\n{A}\nhttps://evil.test/\n")
    assert len(dialog.draft.candidates) == 3
    assert dialog.table.rowCount() == 3
    dialog.table.setCurrentCell(0, 0)
    confirm(dialog)
    assert dialog.draft.readiness("1").status == "ready"
    assert "identity: unknown" in dialog.evidence.toPlainText()
    assert dialog.draft.candidates["1"].resolution.title is None
    dialog.table.setCurrentCell(2, 0)
    assert not dialog.confirm_button.isEnabled()
    assert "blocked" in dialog.evidence.toPlainText() or dialog.draft.readiness("3").status == "blocked"
    assert not dialog.save_button.isEnabled()
    assert before == (dialog.path.read_bytes(), dialog.catalog.read_bytes())


def test_edits_survive_row_switch_retry_and_group_selection(gui):
    dialog, _app = gui
    populate(dialog, A + "\n" + B)
    dialog.table.setCurrentCell(0, 0)
    dialog.label_edit.setText("手編集")
    dialog.key_edit.setText("manual_key")
    dialog.work_edit.setText("first_work")
    dialog.table.setCurrentCell(1, 0)
    assert dialog.draft.candidates["1"].label == "手編集"
    assert dialog.draft.candidates["1"].key == "manual_key"
    dialog.work_combo.setCurrentIndex(dialog.work_combo.findData("1"))
    dialog.apply_fields()
    assert len(dialog.draft.works) == 1
    dialog.table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    assert not dialog.draft.works["1"].selected
    assert dialog.table.item(1, 0).checkState() == Qt.CheckState.Unchecked
    dialog.table.setCurrentCell(0, 0)
    dialog.retry_selected()
    wait_for(lambda: dialog.task is None)
    assert dialog.draft.candidates["1"].key == "manual_key"
    assert dialog.draft.candidates["1"].label == "手編集"
    assert dialog.draft.candidates["2"].group_id == "1"


def test_corrected_url_requires_reanalysis_and_retains_input(gui):
    dialog, _app = gui
    populate(dialog, "https://evil.test/old")
    dialog.label_edit.setText("人工作品")
    dialog.work_edit.setText("work")
    dialog.url_edit.setText(A)
    dialog.apply_fields()
    assert not dialog.confirm_button.isEnabled()
    dialog.retry_selected()
    wait_for(lambda: dialog.task is None)
    assert dialog.draft.candidates["1"].label == "人工作品"
    assert dialog.draft.candidates["1"].resolution.status == "valid"
    assert "https://evil.test/old" in dialog.draft.raw_input


def test_cdp_failure_leaves_safe_url_manual_candidate(gui):
    dialog, _app = gui
    dialog.metadata.setChecked(True)
    populate(dialog, K)
    row = dialog.draft.candidates["1"]
    assert row.resolution.status == "valid"
    assert any("synthetic CDP unavailable" in warning for warning in row.resolution.warnings)
    confirm(dialog)
    assert dialog.draft.readiness("1").status == "ready"


def test_cancel_and_busy_keep_draft(gui, monkeypatch):
    dialog, _app = gui
    populate(dialog, A)
    confirm(dialog)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Cancel)
    dialog.close()
    assert dialog.isVisible()
    dialog.task = object()
    dialog.reject()
    assert dialog.isVisible()
    dialog.task = None
    dialog.set_active_job(True)
    assert not dialog.analyze_button.isEnabled()
    assert not dialog.confirm_button.isEnabled()
    dialog.set_active_job(False)
    assert dialog.draft.candidates["1"].confirmed


def test_large_input_scroll_limits_and_stale_callbacks(gui):
    dialog, _app = gui
    urls = [f"https://shonenjumpplus.com/episode/{index}" for index in range(1, 101)]
    populate(dialog, "\n".join(urls))
    assert dialog.table.rowCount() == 100
    dialog.table.scrollToBottom()
    assert dialog.table.verticalScrollBar().maximum() > 0
    previous = len(dialog.draft.candidates)
    dialog._resolved((-1, None, 1, B, dialog.draft.resolver.resolve(B)))
    assert len(dialog.draft.candidates) == previous
    populate(dialog, "x\n" * 101)
    assert "100" in dialog.status.text()
    assert len(dialog.draft.candidates) == previous


def test_layout_captures_and_keyboard_no_accidental_action(gui):
    dialog, _app = gui
    populate(dialog, A + "\n" + K + "\nhttps://evil.test/")
    dialog.table.setCurrentCell(0, 0)
    confirm(dialog)
    output = Path(__file__).resolve().parents[2] / ".tmp" / "watchlist-registration"
    output.mkdir(parents=True, exist_ok=True)
    for width, height in ((1200, 880), (980, 760)):
        dialog.resize(width, height)
        _app.processEvents()
        assert dialog.grab().save(str(output / f"stage03-{width}.png"))
        assert dialog.rect().contains(dialog.close_button.geometry().bottomRight())
    dialog.label_edit.setFocus()
    QTest.keyClick(dialog.label_edit, Qt.Key.Key_Return)
    assert dialog.task is None


def test_context_read_failure_no_fallback(gui):
    dialog, _app = gui
    dialog.dirty = False
    dialog.catalog = dialog.catalog.with_name("missing.sqlite")
    dialog.draft = None
    dialog.reload_context()
    wait_for(lambda: dialog.task is None)
    assert dialog.draft is None
    assert not dialog.analyze_button.isEnabled()
    assert not dialog.catalog.exists()


def test_main_window_entry_preserves_inventory_selection_and_blocks_other_actions(gui, tmp_path):
    from screenshot_crawler.gui.main_window import MainWindow
    from screenshot_crawler.management.inventory import InventoryService
    from screenshot_crawler.watchlist.service import WatchlistService
    dialog, _app = gui
    target = WatchlistService(dialog.path).add(key="existing", work_key="existing_work",
        site="jumpplus", url=A, label="Existing")
    window = MainWindow(dialog.catalog, dialog.path, dialog.runtime_path,
        management_path=tmp_path / "management.sqlite", auto_load=False)
    window.set_snapshot(InventoryService().load(dialog.catalog, dialog.path, runtime_path=dialog.runtime_path))
    window.model.set_checked_keys({target.key})
    window._open_url_registration()
    editor = window._registration_editor
    wait_for(lambda: editor.task is None)
    assert editor.isVisible() and window.model.selected_keys == {"existing"}
    assert window._discovery_block_reason()
    window._show_execution_preview("discover")
    assert window._job_controller is None
    editor.dirty = False
    editor.close()
    window.close()
