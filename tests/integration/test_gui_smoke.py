"""Local offscreen smoke checks for the P1 window (no browser or writes)."""

from datetime import UTC, datetime

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication

from screenshot_crawler.gui.main_window import MainWindow
from screenshot_crawler.management.models import InventorySnapshot


@pytest.fixture(scope="session")
def qt_app():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


@pytest.fixture(autouse=True)
def dispose_qt_windows_on_gui_thread(qt_app):
    """Destroy widgets on their owning thread before the next worker starts."""
    import gc

    from PySide6.QtCore import QCoreApplication, QEvent
    yield
    for window in qt_app.topLevelWidgets():
        window.close()
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()


def test_main_window_can_receive_snapshot_without_loading_or_execution(qt_app):
    snapshot = InventorySnapshot(
        loaded_at=datetime.now(UTC),
        catalog_path="synthetic.sqlite",
        watchlist_path="synthetic.yaml",
        keys=(),
        summaries={},
        items={},
        sources={},
        source_targets={},
        classifications={},
        latest_runs={},
        artifacts={},
        archive_positions={},
        resources={},
        grants=(),
        load_seconds=0.0,
    )
    window = MainWindow("synthetic.sqlite", "synthetic.yaml", auto_load=False)
    window.set_snapshot(snapshot)
    assert window.model.snapshot is snapshot
    assert not window.findChild(type(window.reload_button), "discover_button").isEnabled()
    assert not window.findChild(type(window.reload_button), "batch_run_button").isEnabled()
    window.close()


def test_reload_error_keeps_snapshot_marked_stale(qt_app):
    snapshot = InventorySnapshot(
        loaded_at=datetime.now(UTC), catalog_path="synthetic.sqlite", watchlist_path="synthetic.yaml",
        keys=(), summaries={}, items={}, sources={}, source_targets={}, classifications={},
        latest_runs={}, artifacts={}, archive_positions={}, resources={}, grants=(), load_seconds=0.0,
    )
    window = MainWindow("synthetic.sqlite", "synthetic.yaml", auto_load=False)
    window.set_snapshot(snapshot)
    window._load_failed("Catalog is locked")
    assert "前回の表示は古い" in window.error_label.text()
    assert window.model.snapshot is snapshot
    window.close()


def test_closed_window_ignores_queued_worker_result(qt_app):
    snapshot = InventorySnapshot(
        loaded_at=datetime.now(UTC), catalog_path="synthetic.sqlite", watchlist_path="synthetic.yaml",
        keys=(), summaries={}, items={}, sources={}, source_targets={}, classifications={},
        latest_runs={}, artifacts={}, archive_positions={}, resources={}, grants=(), load_seconds=0.0,
    )
    window = MainWindow("synthetic.sqlite", "synthetic.yaml", auto_load=False)
    window.close()
    window._load_succeeded(snapshot)
    assert window.model.snapshot is None


def _wait_until(predicate, timeout=15000):
    from PySide6.QtCore import QEventLoop, QTimer
    if predicate():
        return
    loop = QEventLoop()
    poll, deadline = QTimer(), QTimer()
    poll.setInterval(10)
    poll.timeout.connect(lambda: loop.quit() if predicate() else None)
    deadline.setSingleShot(True)
    deadline.timeout.connect(loop.quit)
    poll.start()
    deadline.start(timeout)
    loop.exec()
    poll.stop()
    deadline.stop()
    assert predicate(), "Qt worker did not finish within bounded timeout"


def test_real_sqlite_async_load_detail_switch_reload_is_read_only(qt_app, tmp_path):
    import hashlib

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QPushButton

    from tools.gui_sample import create_sample

    db, watchlist = create_sample(tmp_path / "inputs")
    sentinel = tmp_path / "sentinel.zip"
    sentinel.write_bytes(b"preserve me")
    def facts():
        return {path: (hashlib.sha256(path.read_bytes()).digest(), path.stat().st_mtime_ns)
                for path in (db, watchlist, sentinel)}
    before = facts()
    window = MainWindow(db, watchlist, tmp_path / "missing-runtime")
    window.show()
    _wait_until(lambda: not window._loading)
    assert window.model.snapshot is not None, window.error_label.text()
    model = window.model
    for name in ("discover_button", "batch_run_button", "grant-only_button"):
        assert not window.findChild(QPushButton, name).isEnabled()
    key_node = model.node_by_key_identity("sample-0004")
    model.focus_node(key_node)
    assert window.detail.item_model.rowCount() == 12
    model.setData(model.index_for_node(key_node.node_id), Qt.CheckState.Checked,
                  Qt.ItemDataRole.CheckStateRole)
    window.detail.set_item(2, 2)
    assert "succeeded" in window.detail._field_labels["直近 CrawlRun"].text()
    assert "002-synthetic.zip" in window.detail._field_labels["保存先"].text()
    window.mode_combo.setCurrentIndex(1)
    window.search_edit.setText("sample-0007")
    assert model.checked_keys == {"sample-0004"}
    window.search_edit.clear()
    window.reload()
    _wait_until(lambda: not window._loading)
    assert model.checked_keys == {"sample-0004"}
    successful = model.snapshot
    window.catalog_path = str(tmp_path / "absent.sqlite")
    window.reload()
    _wait_until(lambda: not window._loading)
    assert model.snapshot is successful and "古い" in window.error_label.text()
    assert not (tmp_path / "absent.sqlite").exists()
    assert facts() == before
    window.close()


def test_worker_does_not_block_event_loop_and_closed_window_receives_no_result(qt_app, monkeypatch):
    import threading

    from PySide6.QtCore import QTimer

    from screenshot_crawler.management.inventory import InventoryService

    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    def slow_load(*args, **kwargs):
        entered.set()
        assert release.wait(5), "test did not release synthetic worker"
        finished.set()
        raise ValueError("synthetic failure after close")
    monkeypatch.setattr(InventoryService, "load", slow_load)
    window = MainWindow("unused.sqlite", "unused.yaml")
    window.show()
    heartbeats = []
    QTimer.singleShot(10, lambda: heartbeats.append(True))
    try:
        _wait_until(lambda: entered.is_set() and bool(heartbeats))
        assert window._loading and not window.reload_button.isEnabled()
        window.close()
        old_error = window.error_label.text()
    finally:
        release.set()
    _wait_until(finished.is_set)
    assert window.thread_pool.waitForDone(1000)
    qt_app.processEvents()
    assert window.model.snapshot is None
    assert window.error_label.text() == old_error


def test_selected_multi_site_preview_keeps_hidden_key_and_serializes_resources(
    qt_app, monkeypatch, tmp_path
):
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QDialog, QTextEdit

    from screenshot_crawler.gui.execution_dialog import ExecutionPreviewDialog
    from screenshot_crawler.management.execution import (
        ExecutionPlanPreview,
        ExecutionSelection,
        execution_request_payload,
    )
    from screenshot_crawler.management.inventory import InventoryService
    from tools.gui_sample import create_sample

    db, watchlist = create_sample(tmp_path / "inputs")
    runtime = tmp_path / "inputs" / "sample-runtime.yaml"
    snapshot = InventoryService().load(db, watchlist, runtime_path=runtime)
    window = MainWindow(db, watchlist, runtime, auto_load=False)
    window.set_snapshot(snapshot)
    window.model.set_checked_keys({"sample-0000", "sample-0001"})
    window.model.set_search("sample-0001")
    assert window.model.checked_keys == {"sample-0000", "sample-0001"}

    def fake_preview(self, catalog_path, watchlist_path, policies, *, site,
                     selected_keys, resource, **kwargs):
        return ExecutionPlanPreview(
            action="grant_only",
            selection=ExecutionSelection.from_keys(selected_keys),
            sites=(site,),
            mode=None,
            resource=resource,
            limit=None,
            candidate_count=1,
            skipped_count=0,
            skipped=(),
            blockers=(),
            warnings=(),
            fingerprint=site,
            resources_by_site=((site, resource or "all"),),
            work_names=(site,),
        )

    captured = []

    class FakeDialog(QObject):
        requestConfirmed = Signal(object)

        def __init__(self, preview, request, parent=None):
            super().__init__(parent)
            captured.append((preview, request))

        def exec(self):
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(
        "screenshot_crawler.management.execution.ExecutionPlanService.preview_batch",
        fake_preview,
    )
    monkeypatch.setattr("screenshot_crawler.gui.main_window.ExecutionPreviewDialog", FakeDialog)
    window._show_execution_preview("grant_only")
    assert len(captured) == 1
    preview, request = captured[0]
    assert preview.sites == ("magapoke", "mangaone")
    assert set(request.selected_keys) == {"sample-0000", "sample-0001"}
    assert dict(request.resources_by_site) == {"magapoke": "all", "mangaone": "all"}
    dialog = ExecutionPreviewDialog(preview, request, window)
    assert "Site Resource: magapoke=all, mangaone=all" in dialog.findChild(QTextEdit).toPlainText()
    dialog.close()
    payload = execution_request_payload(request)
    assert payload["keys_by_site"] == {
        "magapoke": ["sample-0001"],
        "mangaone": ["sample-0000"],
    }
    window.close()

