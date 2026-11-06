"""Work archive interactions with synthetic Catalog and Watchlist inputs only."""

from time import monotonic
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from screenshot_crawler.gui.main_window import MainWindow
from screenshot_crawler.gui.model import ArchiveFilter
from screenshot_crawler.management.inventory import InventoryService
from screenshot_crawler.watchlist.service import WatchlistError, WatchlistService
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
    assert predicate(), "Qt save/reload did not finish"


@pytest.fixture
def window(tmp_path, qt_app):
    db, watchlist = create_sample(tmp_path / "inputs", key_count=8, sources_per_key=8)
    runtime = tmp_path / "inputs" / "sample-runtime.yaml"
    view = MainWindow(db, watchlist, runtime, auto_load=False, management_path=tmp_path / "jobs.sqlite")
    view.set_snapshot(InventoryService().load(db, watchlist, runtime_path=runtime))
    view.show()
    yield view
    view._job_controller = None
    wait_for(qt_app, lambda: not view._discovery_busy() and not view._loading)
    view.close()
    view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def work_index(view, work_key="sample-work-0000"):
    node = next(node for node in view.model._nodes.values()
                if node.kind == "work" and node.work_key == work_key)
    return view.model.index_for_node(node.node_id)


def test_archive_menu_cross_site_restore_restart_and_no_confirmation(window, qt_app, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: pytest.fail("unexpected confirmation"))
    watch = WatchlistService(window.watchlist_path)
    targets = watch.list_targets()
    catalog_bytes = watch.path.with_name("sample.sqlite").read_bytes()
    window.model.set_checked_keys({"sample-0000", "sample-0001", "sample-0004"})
    menu = window._archive_context_menu(work_index(window))
    assert menu.actions()[0].objectName() == "archive_work_action"
    menu.actions()[0].trigger()
    menu.deleteLater()
    wait_for(qt_app, lambda: not window._discovery_busy() and not window._loading)
    assert watch.read_document().archived_work_keys == ("sample-work-0000",)
    assert watch.list_targets() == targets
    assert watch.path.with_name("sample.sqlite").read_bytes() == catalog_bytes
    assert window.model.selected_keys == {"sample-0004"}
    assert not work_index(window).isValid()
    for number in range(4):
        node = window.model.node_by_key_identity(f"sample-{number:04d}")
        assert not window.model.index_for_node(node.node_id).isValid()
    assert "アーカイブしました" in window.statusBar().currentMessage()
    # A fresh window starts in Normal while retaining the saved archive state.
    restarted = MainWindow(window.catalog_path, window.watchlist_path, window.runtime_path, auto_load=False)
    restarted.set_snapshot(InventoryService().load(window.catalog_path, window.watchlist_path,
                                                  runtime_path=window.runtime_path))
    assert restarted.archive_combo.currentData() == ArchiveFilter.NORMAL
    assert not work_index(restarted).isValid()
    restarted.close()
    restarted.deleteLater()
    window.archive_combo.setCurrentIndex(window.archive_combo.findData(ArchiveFilter.ARCHIVED))
    index = work_index(window)
    assert index.isValid() and "アーカイブ済み" in index.data()
    window.model.set_checked_keys({"sample-0000"})
    assert window.model.selected_keys == {"sample-0000"}
    menu = window._archive_context_menu(index)
    assert menu.actions()[0].objectName() == "restore_work_action"
    menu.actions()[0].trigger()
    menu.deleteLater()
    wait_for(qt_app, lambda: not window._discovery_busy() and not window._loading)
    assert not watch.read_document().archived_work_keys
    assert not window.model.selected_keys
    assert not work_index(window).isValid()
    window.archive_combo.setCurrentIndex(0)
    assert work_index(window).isValid()


@pytest.mark.parametrize("failure", ["cas", "write"])
def test_archive_failure_keeps_visible_rows_and_selection(window, qt_app, monkeypatch, failure):
    watch = WatchlistService(window.watchlist_path)
    if failure == "cas":
        watch.update_target("sample-0000", label="External edit")
    else:
        def reject(*args, **kwargs):
            raise WatchlistError("disk failure")
        monkeypatch.setattr(WatchlistService, "_atomic_write", reject)
    before = watch.path.read_bytes()
    window.model.set_checked_keys({"sample-0000"})
    window._set_work_archived("sample-work-0000", True)
    wait_for(qt_app, lambda: not window._discovery_busy())
    assert watch.path.read_bytes() == before
    assert work_index(window).isValid()
    assert window.model.selected_keys == {"sample-0000"}
    assert "保存できませんでした" in window.error_label.text()


def test_archive_blocks_other_saves_jobs_paths_close_and_active_worker(window, qt_app, monkeypatch):
    controller = SimpleNamespace(active_job_id="active")
    window._job_controller = controller
    menu = window._archive_context_menu(work_index(window))
    assert not menu.actions()[0].isEnabled()
    menu.deleteLater()
    window._set_work_archived("sample-work-0000", True)
    assert window._archive_save_worker is None
    window._job_controller = None
    workers = []
    monkeypatch.setattr(window.thread_pool, "start", workers.append)
    window._set_work_archived("sample-work-0000", True)
    assert len(workers) == 1
    window._toggle_discovery("sample-0001", False)
    window._set_work_archived("sample-work-0001", True)
    assert len(workers) == 1
    assert not window._invalidate_watchlist_editor_for_path_change()
    assert not window.close()
    window.model.set_checked_keys({"sample-0001"})
    window._show_execution_preview("batch")
    assert not window.batch_run_button.isEnabled()
    assert "保存・再読込" in window.error_label.text()
    # Release the paused worker through the ordinary failure path for fixture cleanup.
    window._archive_save_failed("test cancellation")


def test_saved_archive_survives_inventory_refresh_failure(window, qt_app, monkeypatch):
    def fail_load(*args, **kwargs):
        raise ValueError("reload failed")
    monkeypatch.setattr(InventoryService, "load", fail_load)
    window._set_work_archived("sample-work-0000", True)
    wait_for(qt_app, lambda: not window._discovery_busy() and not window._loading)
    assert "sample-work-0000" in WatchlistService(window.watchlist_path).read_document().archived_work_keys
    assert not work_index(window).isValid()
    assert "保存済み・表示更新失敗" in window.error_label.text()
    assert window._inventory_stale


def test_archive_view_allows_newly_archived_work_only_after_explicit_reselection(window, qt_app):
    window.archive_combo.setCurrentIndex(window.archive_combo.findData(ArchiveFilter.ALL))
    window.model.set_checked_keys({"sample-0000", "sample-0001"})
    window._set_work_archived("sample-work-0000", True)
    wait_for(qt_app, lambda: not window._discovery_busy() and not window._loading)
    assert not window.model.selected_keys
    assert "アーカイブ済み" in work_index(window).data()
    window.model.set_checked_keys({"sample-0000"})
    assert window.model.selected_keys == {"sample-0000"}
