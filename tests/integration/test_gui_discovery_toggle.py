"""Synthetic Qt/Watchlist tests; never use an operational Catalog or browser."""

from dataclasses import replace
from time import monotonic
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from screenshot_crawler.gui.discovery_toggle import DiscoverySaveWorker, DiscoverySwitchDelegate
from screenshot_crawler.gui.main_window import MainWindow
from screenshot_crawler.gui.model import DISCOVERY_COLUMN, DISCOVERY_ROLE, ViewMode
from screenshot_crawler.management.execution import JobExecutionRequest
from screenshot_crawler.management.inventory import InventoryService
from screenshot_crawler.watchlist.service import WatchlistService
from tools.gui_sample import create_sample


@pytest.fixture(scope="session")
def qt_app():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


def wait_for(app, predicate):
    deadline = monotonic() + 10
    while not predicate() and monotonic() < deadline:
        app.processEvents()
        QTest.qWait(10)
    assert predicate(), "Qt worker did not complete within 10 seconds"


@pytest.fixture
def window(tmp_path, qt_app):
    db, watchlist = create_sample(tmp_path / "inputs", key_count=8, sources_per_key=8)
    runtime = tmp_path / "inputs" / "sample-runtime.yaml"
    view = MainWindow(db, watchlist, runtime, auto_load=False, management_path=tmp_path / "jobs.sqlite")
    view.set_snapshot(InventoryService().load(db, watchlist, runtime_path=runtime))
    view.show()
    view.tree.expandAll()
    qt_app.processEvents()
    yield view
    wait_for(qt_app, lambda: not view._discovery_busy() and not view._loading)
    view._work_editor = None
    view._watchlist_editor = None
    view.close()
    view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def switch_index(window, key="sample-0000"):
    node = window.model.node_by_key_identity(key)
    return window.model.index_for_node(node.node_id).siblingAtColumn(DISCOVERY_COLUMN)


@pytest.mark.parametrize("input_method", ["mouse", "keyboard"])
def test_toggle_saves_only_enabled_and_keeps_execution_selection(window, qt_app, monkeypatch, input_method):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: pytest.fail("toggle asked for confirmation"))
    path = WatchlistService(window.watchlist_path).path
    original = path.read_bytes()
    # Preserve an unrelated extension, comments and CRLF while editing a scalar.
    path.write_bytes(b"# operator comment\r\ncustom: retained\r\n" + original.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    window.reload()
    wait_for(qt_app, lambda: not window._loading)
    before = path.read_bytes()
    catalog = WatchlistService(window.catalog_path).path
    db_before = catalog.read_bytes()
    model = window.model
    model.set_checked_keys({"sample-0000", "sample-0001"})
    model.focus_node(model.node_by_key_identity("sample-0001"))
    window.mode_combo.setCurrentIndex(1)
    window.tree.expandAll()
    window.search_edit.setText("sample-work-0000")
    window._on_sort_requested(2, Qt.SortOrder.DescendingOrder)
    index = switch_index(window)
    assert index.data(DISCOVERY_ROLE) is True
    if input_method == "mouse":
        window.tree.scrollTo(index)
        qt_app.processEvents()
        rect = DiscoverySwitchDelegate.switch_rect(window.tree.visualRect(index))
        QTest.mouseClick(window.tree.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    else:
        window.tree.setCurrentIndex(index)
        QTest.keyClick(window.tree, Qt.Key.Key_Space)
    wait_for(qt_app, lambda: not window._discovery_busy())
    assert WatchlistService(path).get("sample-0000").enabled is False
    assert path.read_bytes() == before.replace(b"enabled: true", b"enabled: false", 1)
    assert catalog.read_bytes() == db_before
    assert model.selected_keys == {"sample-0000", "sample-0001"}
    assert window.detail.current_key.identity == "sample-0001"
    assert model.view_mode == ViewMode.WORK and model.sort_column == 2
    assert window.search_edit.text() == "sample-work-0000"
    assert switch_index(window).data() == "OFF"
    assert model.snapshot.watchlist_revision == WatchlistService(path).revision()
    # Switching back is a second independent save, still without starting a job.
    window._toggle_discovery("sample-0000", True)
    wait_for(qt_app, lambda: not window._discovery_busy())
    assert path.read_bytes() == before
    assert window._job_controller is None


def test_parent_totals_include_hidden_keys_and_unmanaged_rows_are_read_only(window, qt_app):
    window.model.set_view_mode(ViewMode.WORK)
    node = window.model.node_by_id("work:sample-work-0000")
    index = window.model.index_for_node(node.node_id).siblingAtColumn(DISCOVERY_COLUMN)
    assert index.data() == "有効3／全4件"
    window.tree.expandAll()
    window.tree.scrollTo(index)
    qt_app.processEvents()
    clicked = QSignalSpy(window.tree.nodeClicked)
    QTest.mouseClick(window.tree.viewport(), Qt.MouseButton.LeftButton,
                     pos=window.tree.visualRect(index).center())
    assert clicked.count() == 1  # Read-only parent counts are ordinary focusable cells.
    window.model.set_search("sample-0000")
    index = window.model.index_for_node(node.node_id).siblingAtColumn(DISCOVERY_COLUMN)
    assert index.data() == "有効3／全4件"
    assert not window.model.setData(index, False)
    window.model.set_search("")
    unmanaged = next(key for key in window.model.snapshot.keys if key.target is None)
    index = switch_index(window, unmanaged.identity)
    assert index.data() == "—" and index.data(DISCOVERY_ROLE) is None
    assert not window.model.setData(index, True)
    window.model.sort(DISCOVERY_COLUMN)
    assert window.model.selected_keys == set()


@pytest.mark.parametrize("failure", ["external-edit", "deleted-key", "write-error"])
def test_save_failure_keeps_display_and_does_not_overwrite(window, qt_app, monkeypatch, failure):
    service = WatchlistService(window.watchlist_path)
    if failure == "external-edit":
        service.update_target("sample-0001", label="external operator")
    elif failure == "deleted-key":
        service.remove("sample-0000")
    else:
        def fail(*args, **kwargs):
            raise OSError("synthetic read-only filesystem")
        monkeypatch.setattr(WatchlistService, "update_target", fail)
    before = service.path.read_bytes()
    window._toggle_discovery("sample-0000", False)
    wait_for(qt_app, lambda: not window._discovery_busy())
    assert service.path.read_bytes() == before
    assert switch_index(window).data(DISCOVERY_ROLE) is True
    assert "保存できません" in window.error_label.text()
    assert window._discovery_block_reason()
    window.reload()
    wait_for(qt_app, lambda: not window._loading)
    assert window._discovery_block_reason() == ""


def test_successful_save_remains_saved_if_inventory_reload_fails(window, qt_app, monkeypatch):
    load = InventoryService.load
    def fail(*args, **kwargs):
        raise OSError("synthetic Inventory failure")
    monkeypatch.setattr(InventoryService, "load", fail)
    window._toggle_discovery("sample-0000", False)
    wait_for(qt_app, lambda: not window._discovery_busy())
    assert not WatchlistService(window.watchlist_path).get("sample-0000").enabled
    assert switch_index(window).data(DISCOVERY_ROLE) is False
    assert "保存済み・表示更新失敗" in window.error_label.text()
    assert window._discovery_block_reason()
    monkeypatch.setattr(InventoryService, "load", load)
    window.reload()
    wait_for(qt_app, lambda: not window._loading)
    assert window._discovery_block_reason() == ""


@pytest.mark.parametrize("editor_type", ["key", "work"])
def test_clean_editor_is_rebased_and_dirty_editor_blocks_toggle(window, qt_app, monkeypatch, editor_type):
    if editor_type == "key":
        window._open_watchlist_editor()
        editor = window._watchlist_editor
        assert not editor._busy()
    else:
        window._open_work_editor()
        editor = window._work_editor
    window._toggle_discovery("sample-0000", False)
    wait_for(qt_app, lambda: not window._discovery_busy())
    assert editor.revision == WatchlistService(window.watchlist_path).revision()
    targets = editor.targets if editor_type == "key" else editor.saved
    assert not next(target for target in targets if target.key == "sample-0000").enabled
    if editor_type == "key":
        editor._dirty = True
    else:
        editor.dirty = True
    before = WatchlistService(window.watchlist_path).path.read_bytes()
    window._toggle_discovery("sample-0000", True)
    assert "未保存" in window.error_label.text()
    assert WatchlistService(window.watchlist_path).path.read_bytes() == before
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k:
                        QMessageBox.StandardButton.Close if editor_type == "key"
                        else QMessageBox.StandardButton.Discard)
    assert editor.close()
    assert window._discovery_block_reason() == ""
    window._toggle_discovery("sample-0000", True)
    wait_for(qt_app, lambda: not window._discovery_busy())
    assert WatchlistService(window.watchlist_path).get("sample-0000").enabled


@pytest.mark.parametrize("blocker", ["active-job", "orphan", "key-busy", "work-busy", "stale", "missing-revision", "path-change"])
def test_unavailable_state_rejects_edits_at_the_handler(window, blocker):
    before = WatchlistService(window.watchlist_path).path.read_bytes()
    if blocker in {"active-job", "orphan"}:
        window._job_controller = SimpleNamespace(active_job_id="running" if blocker == "active-job" else None,
                                                orphaned_live_worker=blocker == "orphan")
    elif blocker == "key-busy":
        window._watchlist_editor = SimpleNamespace(_busy=lambda: True)
    elif blocker == "work-busy":
        window._work_editor = SimpleNamespace(task=object())
    elif blocker == "stale":
        window._inventory_stale = True
    elif blocker == "missing-revision":
        window.set_snapshot(replace(window.model.snapshot, watchlist_revision=None))
    else:
        window.watchlist_path += ".different"
    window._toggle_discovery("sample-0000", False)
    assert window._discovery_save_worker is None
    assert not switch_index(window).flags() & Qt.ItemFlag.ItemIsEditable
    if blocker != "path-change":
        assert WatchlistService(window.watchlist_path).path.read_bytes() == before
    window._job_controller = None


def test_pending_save_blocks_duplicate_writes_paths_close_and_job_launch(window, qt_app, monkeypatch):
    workers = []
    monkeypatch.setattr(window.thread_pool, "start", workers.append)
    controller = window._ensure_jobs()
    queued = controller.queue(JobExecutionRequest(
        action="batch", selected_keys=frozenset({"sample-0000"}), sites=("mangaone",),
        catalog_path=window.catalog_path, watchlist_path=window.watchlist_path,
    ))
    window._jobs_page.refresh()
    monkeypatch.setattr(controller, "start_job", lambda *a: pytest.fail("job started during save"))
    window._toggle_discovery("sample-0000", False)
    assert len(workers) == 1
    assert switch_index(window).data() == "保存中"
    window._toggle_discovery("sample-0001", False)
    assert len(workers) == 1
    assert not window._invalidate_watchlist_editor_for_path_change()
    assert not window.close()
    window.model.set_checked_keys({"sample-0000"})
    window._show_execution_preview("batch")
    assert controller.active_job_id is None
    assert not window.discover_button.isEnabled()
    assert window._jobs_page._start_blocked
    window._jobs_page._resume_selected()
    assert window._job_store.get_job(queued)["state"] == "queued"
    window.reload()  # Deferred until the save completes; no pre-save read runs.
    assert len(workers) == 1
    monkeypatch.undo()
    workers[0].run()
    wait_for(qt_app, lambda: not window._discovery_busy())
    assert switch_index(window).data() == "OFF"
    assert not window._jobs_page._start_blocked


def test_toggle_preserves_scroll_and_expanded_nodes(window, qt_app):
    window.resize(980, 700)
    window.tree.expandAll()
    qt_app.processEvents()
    horizontal, vertical = window.tree.horizontalScrollBar(), window.tree.verticalScrollBar()
    assert horizontal.maximum() > 0 and vertical.maximum() > 0
    horizontal.setValue(min(80, horizontal.maximum()))
    vertical.setValue(vertical.maximum() // 2)
    before = horizontal.value(), vertical.value()
    expanded = window._expanded_node_ids()
    window._toggle_discovery("sample-0000", False)
    wait_for(qt_app, lambda: not window._discovery_busy())
    qt_app.processEvents()
    assert (horizontal.value(), vertical.value()) == before
    assert window._expanded_node_ids() == expanded


def test_post_commit_read_failure_is_reported_as_saved(window, qt_app, monkeypatch):
    read = WatchlistService.read_snapshot
    calls = 0
    def fail_once(service):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("synthetic post-commit read failure")
        return read(service)
    monkeypatch.setattr(WatchlistService, "read_snapshot", fail_once)
    window._toggle_discovery("sample-0000", False)
    wait_for(qt_app, lambda: not window._discovery_busy())
    assert not WatchlistService(window.watchlist_path).get("sample-0000").enabled
    assert switch_index(window).data() == "OFF"
    assert "保存済み" in window.statusBar().currentMessage()
    assert "保存できません" not in window.error_label.text()


def test_save_worker_signals_failure_instead_of_raising(tmp_path):
    worker = DiscoverySaveWorker(str(tmp_path / "missing.yaml"), "missing", False, "wrong")
    failures = []
    worker.signals.failed.connect(failures.append)
    worker.run()
    assert len(failures) == 1
