"""Local offscreen smoke checks for the P1 window (no browser or writes)."""

from datetime import UTC, datetime
from pathlib import Path

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
    from dataclasses import replace

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
    dialog_text = dialog.findChild(QTextEdit).toPlainText()
    assert "Site Resource: magapoke=all, mangaone=all" in dialog_text
    assert "実行モード: Grant-only" in dialog_text
    assert "最大試行数: 無制限" in dialog_text
    dialog.close()
    payload = execution_request_payload(request)
    assert payload["keys_by_site"] == {
        "magapoke": ["sample-0001"],
        "mangaone": ["sample-0000"],
    }

    # Adding another Work/key and refreshing must not widen a specific grant
    # choice into all resources.
    combo = window._site_grant_resource_combos["magapoke"]
    assert combo.findData("work_ticket") >= 0
    combo.setCurrentIndex(combo.findData("work_ticket"))
    window.model.set_checked_keys({"sample-0000", "sample-0001", "sample-0005"})
    window.set_snapshot(snapshot)
    assert window._site_grant_resource_combos["magapoke"].currentData() == "work_ticket"
    window._show_execution_preview("grant_only")
    assert dict(captured[-1][1].resources_by_site) == {
        "magapoke": "work_ticket", "mangaone": "all",
    }

    # Losing support remains blocked across repeated widget rebuilds. The
    # user must explicitly choose a valid resource before it can run again.
    restricted = replace(snapshot, resources={
        **snapshot.resources,
        "magapoke": replace(snapshot.resources["magapoke"], grant_resources=("premium_ticket",)),
    })
    window.set_snapshot(restricted)
    window._refresh_site_resource_controls()
    window._refresh_site_resource_controls()
    assert window._site_grant_resource_combos["magapoke"].currentData() == "work_ticket"
    window._show_execution_preview("grant_only")
    assert captured[-1][1] is None
    assert any("no longer supported" in reason for reason in captured[-1][0].blockers)
    combo = window._site_grant_resource_combos["magapoke"]
    combo.setCurrentIndex(combo.findData("all"))
    window._show_execution_preview("grant_only")
    assert dict(captured[-1][1].resources_by_site)["magapoke"] == "all"

    missing = replace(restricted, resources={site: value for site, value in restricted.resources.items()
                                           if site != "magapoke"})
    window.set_snapshot(missing)
    window._show_execution_preview("grant_only")
    assert captured[-1][1] is None
    assert window.site_resource_scroll.maximumWidth() == 420
    assert window.minimumSizeHint().width() <= 1400
    window.close()


def test_jobs_page_shows_persistent_history_offscreen(qt_app, tmp_path):
    from screenshot_crawler.gui.jobs_page import JobsPage
    from screenshot_crawler.management.execution import JobExecutionRequest
    from screenshot_crawler.management.job_controller import JobController
    from screenshot_crawler.management.jobs import JobEvent, JobStore

    store = JobStore(tmp_path / "management.sqlite")
    controller = JobController(store, python_executable="python")
    request = JobExecutionRequest(
        action="grant_only",
        selected_keys=frozenset({"key-a"}),
        sites=("mangaone",),
        keys_by_site=(("mangaone", ("key-a",)),),
        resource="synthetic_resource",
        limit=2,
        plan_fingerprint="fingerprint",
    )
    job_id = controller.queue(request)
    store.append_event(JobEvent(
        job_id, "grant_unknown", task_id=f"{job_id}:mangaone", site="mangaone",
        key="key-a", work_key="work-a", item_id=11, source_id=12,
        resource="synthetic_resource", resource_consumed=None, result="unknown",
    ))
    page = JobsPage(store, controller)
    assert page.list_widget.count() == 1
    assert job_id in page.details.toPlainText()
    text = page.details.toPlainText()
    assert "synthetic_resource" in text
    assert "item=11" in text and "source=12" in text
    assert "consumed=unknown" in text
    controller.close()
    page.close()


def test_gui_confirm_to_real_worker_history_and_fresh_rerun_offscreen(qt_app, tmp_path, monkeypatch):
    """Real previews, two-site production worker, reload, and fresh rerun."""
    import hashlib
    import json
    import sqlite3
    import time

    import yaml
    from PySide6.QtWidgets import QApplication, QDialog

    from screenshot_crawler.gui.execution_dialog import ExecutionPreviewDialog
    from screenshot_crawler.management.inventory import InventoryService
    from screenshot_crawler.management.jobs import JobStore
    from tools.gui_sample import create_sample

    monkeypatch.chdir(tmp_path)
    db, watchlist = create_sample(tmp_path / "inputs")
    runtime = tmp_path / "inputs" / "sample-runtime.yaml"
    # The production worker must finish without any browser/site operation.
    with sqlite3.connect(db) as connection:
        connection.execute("UPDATE items SET status='completed'")
    catalog_before = hashlib.sha256(db.read_bytes()).hexdigest()
    snapshot = InventoryService().load(db, watchlist, runtime_path=runtime)
    selected = {"sample-0004", "sample-0005"}
    confirmed = []

    def confirm(dialog):
        assert dialog.preview.can_confirm, dialog.preview.blockers
        assert dialog.preview.candidate_count == 0
        assert set(dialog.request.selected_keys) == selected
        assert dialog.request.sites == ("magapoke", "mangaone")
        confirmed.append(dialog.request)
        dialog._confirm()
        return QDialog.DialogCode.Accepted

    # Only replace the human click. Planner, dialog, controller and worker are real.
    monkeypatch.setattr(ExecutionPreviewDialog, "exec", confirm)
    window = MainWindow(db, watchlist, runtime, auto_load=False,
                        management_path=tmp_path / "management.sqlite")
    window.set_snapshot(snapshot)
    window.model.set_checked_keys(selected)
    window.model.focus_node(window.model.node_by_key_identity("sample-0004"))
    window.model.set_search("sample-0004")

    def wait_until(predicate):
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            QApplication.processEvents()
            window._poll_jobs()
            if predicate():
                return
            time.sleep(0.02)
        pytest.fail("isolated GUI/worker lifecycle timed out")

    try:
        window.batch_run_button.click()
        controller, store = window._job_controller, window._job_store
        assert controller is not None and store is not None
        window._job_poll_timer.stop()
        first_id = window._session_job_ids[-1]
        wait_until(lambda: store.get_job(first_id)["state"] == "succeeded" and not window._loading)
        assert window.model.checked_keys == selected
        assert window.model.search_text == "sample-0004"
        assert window.model._nodes[window.model.focused_node_id].key_identity == "sample-0004"
        tasks = store.list_tasks(first_id)
        assert [task["site"] for task in tasks] == ["magapoke", "mangaone"]
        assert all(task["state"] == "succeeded" and task["observed_attempts"] == 0 for task in tasks)
        assert all(Path(task["metrics_path"]).is_file() for task in tasks)
        assert first_id in window._jobs_page.details.toPlainText()

        # Change only isolated inputs. The next preview must reload this label
        # and generate a new fingerprint, rather than recycling the old request.
        payload = yaml.safe_load(watchlist.read_text(encoding="utf-8"))
        for target in payload["targets"]:
            if target["key"] == "sample-0004":
                target["label"] = "updated isolated rerun label"
        watchlist.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
        window._rerun_job(first_id)
        wait_until(lambda: len(window._session_job_ids) == 2)
        second_id = window._session_job_ids[-1]
        assert second_id != first_id
        assert len(confirmed) == 2
        assert confirmed[0].plan_fingerprint != confirmed[1].plan_fingerprint
        assert window.model.key_inventory("sample-0004").target.label == "updated isolated rerun label"
        assert store.get_job(second_id)["original_job_id"] == first_id
        assert set(json.loads(store.get_job(second_id)["selected_keys_json"])) == selected
        wait_until(lambda: store.get_job(second_id)["state"] == "succeeded" and not window._loading)
        assert window.model.checked_keys == selected
        assert hashlib.sha256(db.read_bytes()).hexdigest() == catalog_before
        # Reopening the management store preserves both terminal histories.
        reopened = JobStore(store.path)
        reopened.initialize()
        assert {row["job_id"] for row in reopened.list_jobs()} == {first_id, second_id}
        assert all(row["state"] == "succeeded" for row in reopened.list_jobs())

        # A removed key cannot silently turn the retry into a smaller selection.
        payload["targets"] = [target for target in payload["targets"]
                              if target["key"] != "sample-0004"]
        watchlist.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
        window._rerun_job(first_id)
        wait_until(lambda: not window._loading)
        assert len(confirmed) == 2 and len(store.list_jobs()) == 2
        assert "sample-0004" in window.error_label.text()

        # Failed reload also leaves the historical request unexecuted.
        watchlist.write_text("targets: [", encoding="utf-8")
        window._rerun_job(first_id)
        wait_until(lambda: not window._loading)
        assert len(confirmed) == 2 and len(store.list_jobs()) == 2
        assert "再計画は停止" in window.error_label.text()
    finally:
        if window._job_controller is not None and window._job_controller.active_job_id is not None:
            window._job_controller.force_stop()
        window._job_poll_timer.stop()
        window.close()
        window.thread_pool.waitForDone(5000)
        QApplication.processEvents()

