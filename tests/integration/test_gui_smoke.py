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


def test_main_window_monitor_is_below_existing_controls_and_preserves_selection(qt_app, tmp_path):
    from PySide6.QtWidgets import QSplitter

    window = MainWindow(
        "synthetic.sqlite", "synthetic.yaml", auto_load=False,
        management_path=tmp_path / "management.sqlite",
    )
    window.resize(980, 600)
    window.show()
    QApplication.processEvents()
    splitter = window.findChild(QSplitter, "execution_vertical_splitter")
    assert splitter is not None
    assert splitter.indexOf(window.execution_monitor) == 1
    assert window.findChild(type(window.reload_button), "discover_button") is window.discover_button
    assert window.findChild(type(window.reload_button), "batch_run_button") is window.batch_run_button
    assert window.findChild(type(window.reload_button), "grant-only_button") is window.grant_only_button
    assert window.height() >= 600
    upper_scroll = splitter.widget(0)
    assert upper_scroll.objectName() == "execution_upper_scroll"
    upper = upper_scroll.widget()
    assert upper is not None
    assert upper.height() >= upper.minimumSizeHint().height()
    assert upper_scroll.height() <= upper.height()
    assert window.detail.form_scroll.geometry().bottom() <= window.detail.height()
    assert window.execution_monitor.height() >= 26
    assert window.execution_monitor.action_label.width() >= window.execution_monitor.action_label.minimumWidth()
    assert window.execution_monitor.state_label.width() >= window.execution_monitor.state_label.minimumWidth()
    window.execution_monitor.set_collapsed(True)
    QApplication.processEvents()
    assert window.execution_monitor.height() < 140
    window.execution_monitor.set_collapsed(False)
    QApplication.processEvents()
    assert upper.height() >= upper.minimumSizeHint().height()
    assert window.execution_monitor.action_label.isVisible()
    window.resize(1400, 850)
    QApplication.processEvents()
    splitter.setSizes([max(upper.minimumSizeHint().height(), splitter.height() - 300), 300])
    QApplication.processEvents()
    manual_monitor_height = splitter.sizes()[1]
    window.resize(1380, 850)
    QApplication.processEvents()
    assert splitter.sizes()[1] >= manual_monitor_height - 8
    window.close()


def test_main_window_upper_scroll_and_real_splitter_drag_keep_controls_reachable(qt_app, tmp_path):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QSplitter

    from screenshot_crawler.management.inventory import InventoryService
    from tools.gui_sample import create_sample

    db, watchlist = create_sample(tmp_path / "inputs", key_count=2, sources_per_key=2)
    snapshot = InventoryService().load(db, watchlist, runtime_path=tmp_path / "runtime.yaml")
    window = MainWindow(db, watchlist, auto_load=False)
    window.set_snapshot(snapshot)
    focused = window.model.node_by_key_identity("sample-0000")
    assert focused is not None
    window.model.focus_node(focused)
    window.resize(1400, 850)
    window.show()
    QApplication.processEvents()
    splitter = window.findChild(QSplitter, "execution_vertical_splitter")
    upper_scroll = splitter.widget(0)
    upper = upper_scroll.widget()
    assert upper is not None
    handle = splitter.handle(1)
    center = handle.rect().center()
    target = QPoint(center.x(), center.y() - 170)
    QTest.mousePress(handle, Qt.MouseButton.LeftButton, pos=center)
    QTest.mouseMove(handle, target, delay=20)
    QTest.mouseRelease(handle, Qt.MouseButton.LeftButton, pos=target)
    QApplication.processEvents()
    assert window.execution_monitor.height() >= 380
    assert upper_scroll.height() + window.execution_monitor.height() <= splitter.height() + 2
    assert upper.height() >= upper.minimumSizeHint().height()
    for widget in (window.catalog_browse, window.discover_button):
        upper_scroll.ensureWidgetVisible(widget)
        QApplication.processEvents()
        widget_rect = widget.rect().translated(widget.mapTo(upper_scroll.viewport(), QPoint(0, 0)))
        assert upper_scroll.viewport().rect().contains(widget_rect)
    assert window.detail.form_scroll.geometry().bottom() <= window.detail.height()
    if window.detail.item_table.isVisible():
        assert window.detail.form_scroll.geometry().bottom() <= window.detail.item_table.geometry().top()
    monitor_splitter = window.execution_monitor.findChildren(QSplitter)[0]
    left_before = monitor_splitter.sizes()[0]
    monitor_handle = monitor_splitter.handle(1)
    monitor_center = monitor_handle.rect().center()
    monitor_target = QPoint(monitor_center.x() + 120, monitor_center.y())
    QTest.mousePress(monitor_handle, Qt.MouseButton.LeftButton, pos=monitor_center)
    QTest.mouseMove(monitor_handle, monitor_target, delay=20)
    QTest.mouseRelease(monitor_handle, Qt.MouseButton.LeftButton, pos=monitor_target)
    QApplication.processEvents()
    assert monitor_splitter.sizes()[0] >= left_before + 80
    dragged_height = window.execution_monitor.height()
    window.execution_monitor.follow_job("synthetic-next")
    window.resize(1400, 800)
    QApplication.processEvents()
    assert window.execution_monitor.height() >= dragged_height - 60
    window.resize(1400, 850)
    QApplication.processEvents()
    assert window.execution_monitor.height() >= dragged_height - 8
    window.execution_monitor.set_collapsed(True)
    QApplication.processEvents()
    window.execution_monitor.set_collapsed(False)
    QApplication.processEvents()
    assert window.execution_monitor.height() >= dragged_height - 8
    window.close()


def test_main_window_initial_tree_is_collapsed_and_reload_preserves_manual_expansion(qt_app, tmp_path):
    from screenshot_crawler.management.inventory import InventoryService
    from tools.gui_sample import create_sample

    db, watchlist = create_sample(tmp_path / "inputs", key_count=2, sources_per_key=2)
    snapshot = InventoryService().load(db, watchlist, runtime_path=tmp_path / "runtime.yaml")
    window = MainWindow(db, watchlist, auto_load=False)
    window.set_snapshot(snapshot)
    QApplication.processEvents()
    root = window.model.index(-1, -1)
    top_indices = [window.model.index(row, 0, root) for row in range(window.model.rowCount(root))]
    assert top_indices
    assert all(not window.tree.isExpanded(index) for index in top_indices)
    first = top_indices[0]
    first_node = window.model.node_for_index(first)
    assert first_node is not None
    window.tree.expand(first)
    QApplication.processEvents()
    window.set_snapshot(snapshot)
    QApplication.processEvents()
    restored = window.model.index_for_node(first_node.node_id)
    assert restored.isValid() and window.tree.isExpanded(restored)
    window.close()


def test_main_window_adds_splitter_children_before_set_collapsible(qt_app):
    from PySide6.QtCore import qInstallMessageHandler

    messages = []
    previous = qInstallMessageHandler(lambda _mode, _context, message: messages.append(str(message)))
    try:
        window = MainWindow("synthetic.sqlite", "synthetic.yaml", auto_load=False)
        window.close()
        QApplication.processEvents()
    finally:
        qInstallMessageHandler(previous)
    assert not any("QSplitter::setCollapsible" in message for message in messages)


def test_execution_monitor_streams_trim_scroll_and_job_selection(qt_app, tmp_path):
    from screenshot_crawler.gui.execution_monitor import ExecutionMonitor
    from screenshot_crawler.management.execution import JobExecutionRequest
    from screenshot_crawler.management.job_controller import JobController
    from screenshot_crawler.management.jobs import JobStore

    store = JobStore(tmp_path / "management.sqlite")
    controller = JobController(store, python_executable="python")
    request = JobExecutionRequest(
        action="batch", selected_keys=frozenset({"key-a"}), sites=("mangaone",),
        keys_by_site=(("mangaone", ("key-a",)),), plan_fingerprint="fingerprint",
    )
    first = controller.queue(request)
    second = controller.queue(request)
    (store.job_dir(first) / "stdout.log").write_text(
        "A-start\n" + "line\n" * 20000 + "A-marker\n", encoding="utf-8"
    )
    (store.job_dir(first) / "stderr.log").write_text("warning\r\n", encoding="utf-8", newline="")
    monitor = ExecutionMonitor(store)
    monitor.max_blocks = 10
    monitor.max_chars = 120
    monitor.show()
    monitor.set_job(first)
    monitor.refresh()
    assert monitor.log_view.document().blockCount() <= 11
    assert "line\n" in monitor.log_view.toPlainText()
    assert "initial history omitted" in monitor.log_metadata.text()
    monitor.log_view.verticalScrollBar().setValue(0)
    with (store.job_dir(first) / "stdout.log").open("a", encoding="utf-8") as stream:
        stream.write("tail\n")
    old_value = monitor.log_view.verticalScrollBar().value()
    monitor.refresh()
    assert monitor.log_view.verticalScrollBar().value() <= old_value + 2
    monitor.stream_combo.setCurrentIndex(1)
    assert "warning" in monitor.log_view.toPlainText()
    monitor.stream_combo.setCurrentIndex(0)
    assert "line" in monitor.log_view.toPlainText()
    monitor.set_collapsed(True)
    assert monitor._collapsed
    assert monitor.title_label.isVisible()
    assert not monitor.log_view.isVisible()
    assert monitor.height() < 140
    before = monitor.log_view.toPlainText()
    (store.job_dir(second) / "stdout.log").write_text("hidden while collapsed\n", encoding="utf-8")
    monitor.refresh()
    assert monitor.log_view.toPlainText() == before
    monitor.clear_manual_selection()
    monitor.follow_job(second)
    assert not monitor._collapsed
    assert monitor.log_view.isVisible()
    assert "hidden while collapsed" in monitor.log_view.toPlainText()
    monitor.set_job(first, manual=True)
    assert monitor.log_view.toPlainText().count("A-marker") == 1
    monitor.follow_job(second)
    assert monitor.job_id == first
    monitor.clear_manual_selection()
    monitor.follow_job(second)
    assert monitor.job_id == second
    controller.close()
    monitor.close()


def test_execution_monitor_real_qt_view_large_log_is_bounded_and_responsive(qt_app, tmp_path):
    """Drive the real reader/widget path with a multi-megabyte synthetic log."""
    import hashlib

    from PySide6.QtCore import QTimer

    from screenshot_crawler.gui.execution_monitor import ExecutionMonitor
    from screenshot_crawler.gui.jobs_page import JobsPage
    from screenshot_crawler.management.execution import JobExecutionRequest
    from screenshot_crawler.management.job_controller import JobController
    from screenshot_crawler.management.jobs import JobStore

    store = JobStore(tmp_path / "management.sqlite")
    controller = JobController(store, python_executable="python")
    request = JobExecutionRequest(
        action="batch", selected_keys=frozenset({"key-a"}), sites=("mangaone",),
        keys_by_site=(("mangaone", ("key-a",)),), plan_fingerprint="stress",
    )
    job_id = controller.queue(request)
    stdout = store.job_dir(job_id) / "stdout.log"
    stdout.parent.mkdir(parents=True, exist_ok=True)
    stdout.write_bytes(b"")
    (stdout.parent / "stderr.log").write_bytes(b"")
    payload = "X" * 300_000 + "\n"
    payload += "".join(
        f"line-{index:05d} — 日本語 😀 {index:04d}-padding-0123456789ABCDEFGHIJ"
        "-KLMNOPQRSTUVWXYZ-abcdefghijklmnopqrstuvwxyz-0123456789\n"
        for index in range(50_000)
    )
    payload += "final-marker\n"
    assert len(payload.encode("utf-8")) >= 5_000_000

    monitor = ExecutionMonitor(store)
    monitor.show()
    monitor.set_job(job_id)
    assert monitor._reader is not None
    stdout.write_text(payload, encoding="utf-8")
    expected_size = stdout.stat().st_size
    original_bytes = stdout.read_bytes()
    digest = hashlib.sha256(original_bytes).hexdigest()
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(True))
    timer.start(0)
    try:
        for _ in range(200):
            monitor.refresh()
            QApplication.processEvents()
            if monitor._reader.offsets()["stdout"] >= expected_size:
                break
        assert monitor._reader.offsets()["stdout"] >= expected_size
        assert ticks
        assert monitor.log_view.document().blockCount() <= monitor.max_blocks + 1
        assert monitor.log_view.document().characterCount() <= monitor.max_chars + 1
        assert "final-marker" in monitor.log_view.toPlainText()

        bar = monitor.log_view.verticalScrollBar()
        bar.setValue(max(0, bar.maximum() // 2))
        anchor = monitor.log_view.document().findBlockByNumber(bar.value()).text()
        with stdout.open("a", encoding="utf-8") as stream:
            stream.write("live-tail\n" * 20)
        monitor.refresh()
        assert anchor in monitor.log_view.toPlainText()
        bar.setValue(bar.maximum())
        monitor.refresh()
        assert bar.value() >= bar.maximum() - 1

        # History and monitor own independent viewports.
        page = JobsPage(store, controller)
        page.show()
        page.details.verticalScrollBar().setValue(0)
        monitor_value = monitor.log_view.verticalScrollBar().value()
        page.refresh()
        assert monitor.log_view.verticalScrollBar().value() == monitor_value
        page.close()
    finally:
        timer.stop()
        controller.close()
        monitor.close()
    # The append above is the synthetic worker input; the reader never
    # rewrites it, so the expected source hash is exactly payload+tail.
    after_bytes = stdout.read_bytes()
    assert after_bytes.startswith(original_bytes)
    assert after_bytes[len(original_bytes):].decode("utf-8").replace("\r\n", "\n") == "live-tail\n" * 20
    assert hashlib.sha256(after_bytes[:len(original_bytes)]).hexdigest() == digest


def test_execution_monitor_log_append_preserves_user_selection(qt_app):
    from PySide6.QtGui import QTextCursor

    from screenshot_crawler.gui.execution_monitor import ExecutionMonitor

    monitor = ExecutionMonitor()
    monitor.show()
    monitor.log_view.setPlainText("prefix selected suffix")
    cursor = monitor.log_view.textCursor()
    cursor.setPosition(7)
    cursor.setPosition(15, QTextCursor.MoveMode.KeepAnchor)
    monitor.log_view.setTextCursor(cursor)
    monitor._append_log("\nnew line")
    assert monitor.log_view.textCursor().selectedText() == "selected"
    monitor.close()


@pytest.mark.parametrize("action", ("discover", "batch", "grant_only"))
def test_gui_execution_worker_uses_child_only_utf8_boundary(qt_app, monkeypatch, action):
    import os
    from types import SimpleNamespace

    from screenshot_crawler.gui.main_window import _ExecutionWorker
    from screenshot_crawler.management.execution import JobExecutionRequest

    request = JobExecutionRequest(
        action=action,
        selected_keys=frozenset({"key-a"}),
        sites=("mangaone",),
        keys_by_site=(("mangaone", ("key-a",)),),
        plan_fingerprint="fingerprint",
    )
    observed = {}
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)

    def fake_run(command, **kwargs):
        observed.update(kwargs)
        return SimpleNamespace(stdout="stdout — 日本語 😀\n", stderr="stderr — 警告\n", returncode=0)

    monkeypatch.setattr("screenshot_crawler.gui.main_window.subprocess.run", fake_run)
    worker = _ExecutionWorker(request)
    outputs = []
    worker.signals.succeeded.connect(outputs.append)
    worker.run()
    assert outputs == ["stdout — 日本語 😀\nstderr — 警告\n"]
    assert observed["encoding"] == "utf-8"
    assert observed["errors"] == "replace"
    assert observed["env"]["PYTHONIOENCODING"] == "utf-8"
    assert "PYTHONIOENCODING" not in os.environ


def test_execution_monitor_keeps_queue_terminal_and_missing_db_nonfatal(qt_app, tmp_path):
    from screenshot_crawler.gui.execution_monitor import ExecutionMonitor
    from screenshot_crawler.management.execution import JobExecutionRequest
    from screenshot_crawler.management.job_controller import JobController
    from screenshot_crawler.management.jobs import JobStore

    store = JobStore(tmp_path / "management.sqlite")
    controller = JobController(store, python_executable="python")
    request = JobExecutionRequest(
        action="grant_only", selected_keys=frozenset({"key-a"}), sites=("mangaone",),
        keys_by_site=(("mangaone", ("key-a",)),), resource="synthetic",
        plan_fingerprint="fingerprint",
    )
    job_id = controller.queue(request)
    monitor = ExecutionMonitor(store)
    monitor.show()
    monitor.set_job(job_id)
    monitor.refresh()
    assert "queued" in monitor.state_label.text()
    store.set_state(job_id, "succeeded", summary={"success": True})
    monitor.refresh()
    assert "succeeded" in monitor.state_label.text()

    class MissingStore:
        def list_jobs(self, **kwargs):
            raise RuntimeError("management DB unavailable")

        def get_job(self, job_id):
            raise RuntimeError("management DB unavailable")

    monitor.set_store(MissingStore())
    monitor.set_job(job_id)
    monitor.refresh_jobs()
    monitor.refresh()
    assert "unavailable" in monitor.title_label.text()
    controller.close()
    monitor.close()


def test_monitor_failure_does_not_block_queue_advance(qt_app):
    class FailingMonitor:
        def refresh_jobs(self):
            raise RuntimeError("synthetic monitor failure")

        def follow_job(self, _job_id):
            raise RuntimeError("synthetic monitor failure")

        def refresh(self):
            raise RuntimeError("synthetic monitor failure")

    class FakeStore:
        def get_job(self, job_id):
            return {"job_id": job_id, "state": "queued"}

    class FakeController:
        active_job_id = None

        def __init__(self):
            self.started = []

        def poll(self):
            return "succeeded"

        def start_job(self, job_id):
            self.started.append(job_id)

        def close(self):
            return None

    window = MainWindow("synthetic.sqlite", "synthetic.yaml", auto_load=False)
    controller = FakeController()
    window._job_controller = controller
    window._job_store = FakeStore()
    window._session_job_ids = ["next-job"]
    window.execution_monitor = FailingMonitor()
    window.reload = lambda: None
    window._poll_jobs()
    assert controller.started == ["next-job"]
    window.close()


def test_start_execution_starts_after_monitor_follow_failure(qt_app):
    from screenshot_crawler.management.execution import JobExecutionRequest

    class FailingMonitor:
        def clear_manual_selection(self):
            raise RuntimeError("synthetic monitor failure")

        def follow_job(self, _job_id):
            raise RuntimeError("synthetic monitor failure")

    class FakeController:
        active_job_id = None

        def __init__(self):
            self.queued = []
            self.started = []

        def queue(self, request, *, original_job_id=None):
            self.queued.append((request, original_job_id))
            return "queued-job"

        def start_job(self, job_id):
            self.started.append(job_id)

        def close(self):
            return None

    window = MainWindow("synthetic.sqlite", "synthetic.yaml", auto_load=False)
    controller = FakeController()
    window._job_controller = controller
    window._session_job_ids = []
    window.execution_monitor = FailingMonitor()
    request = JobExecutionRequest(
        action="discover", selected_keys=frozenset({"key-a"}), sites=("mangaone",),
        keys_by_site=(("mangaone", ("key-a",)),), plan_fingerprint="synthetic",
    )
    window._start_execution(request)
    assert controller.started == ["queued-job"]
    assert window._session_job_ids == ["queued-job"]
    window.close()


def test_monitor_auto_follow_only_on_active_job_transition(qt_app):
    class Monitor:
        def __init__(self):
            self.followed = []

        def refresh_jobs(self):
            return None

        def follow_job(self, job_id):
            self.followed.append(job_id)

        def refresh(self):
            return None

    class Controller:
        def __init__(self):
            self.active_job_id = "old"

        def poll(self):
            return None

        def close(self):
            return None

    window = MainWindow("synthetic.sqlite", "synthetic.yaml", auto_load=False)
    monitor = Monitor()
    controller = Controller()
    window.execution_monitor = monitor
    window._job_controller = controller
    window._monitor_followed_active_id = "old"
    window._poll_jobs()
    assert monitor.followed == []
    controller.active_job_id = "new"
    window._poll_jobs()
    assert monitor.followed == ["new"]
    controller.active_job_id = None
    window.close()


def test_execution_monitor_long_event_values_are_elided(qt_app, tmp_path):
    from screenshot_crawler.gui.execution_monitor import ExecutionMonitor
    from screenshot_crawler.management.execution import JobExecutionRequest
    from screenshot_crawler.management.job_controller import JobController
    from screenshot_crawler.management.jobs import JobEvent, JobStore

    store = JobStore(tmp_path / "management.sqlite")
    controller = JobController(store, python_executable="python")
    request = JobExecutionRequest(
        action="discover", selected_keys=frozenset({"key-a"}), sites=("mangaone",),
        keys_by_site=(("mangaone", ("key-a",)),), plan_fingerprint="fingerprint",
    )
    job_id = controller.queue(request)
    task_id = f"{job_id}:mangaone"
    store.set_task_state(task_id, "running")
    store.append_event(JobEvent(
        job_id, "candidate_started", task_id=task_id, site="mangaone",
        key="k" * 10000, item_id=42,
    ))
    monitor = ExecutionMonitor(store)
    monitor.resize(980, 220)
    monitor.show()
    monitor.set_job(job_id)
    monitor.refresh()
    assert monitor.width() <= 980
    assert monitor.location_label.width() < 980
    assert len(monitor.location_label.text()) < 1000
    assert "kkkk" in monitor.location_label.toolTip()
    controller.close()
    monitor.close()


def test_execution_monitor_renders_structured_summary_and_problems(qt_app, tmp_path):
    import json

    from screenshot_crawler.gui.execution_monitor import ExecutionMonitor
    from screenshot_crawler.management.execution import JobExecutionRequest
    from screenshot_crawler.management.job_controller import JobController
    from screenshot_crawler.management.jobs import JobEvent, JobStore

    metrics_root = tmp_path / "metrics"
    metrics_root.mkdir()
    store = JobStore(tmp_path / "management.sqlite")
    controller = JobController(store, python_executable="python")
    request = JobExecutionRequest(
        action="batch", selected_keys=frozenset({"key-a"}), sites=("mangaone",),
        keys_by_site=(("mangaone", ("key-a",)),), metrics_root=str(metrics_root),
        plan_fingerprint="fingerprint",
    )
    job_id = controller.queue(request)
    task_id = f"{job_id}:mangaone"
    metrics_path = metrics_root / "mangaone.jsonl"
    metrics_path.write_text(
        json.dumps({"type": "batch", "event": "start", "site": "mangaone", "run_id": "r"}) + "\n"
        + json.dumps({"type": "grant_result", "work_id": 4, "label": "batch-grant", "resource": "ticket", "item_id": 4, "source_id": 8, "status": "OK", "resource_consumed": False}) + "\n"
        + json.dumps({"type": "batch_summary", "candidates_started": 1, "candidates_completed": 0, "candidates_failed": 1, "stop_reason": "failed"}) + "\n",
        encoding="utf-8",
    )
    store.append_event(JobEvent(job_id, "metrics_started", task_id=task_id, site="mangaone", payload={"metrics_path": str(metrics_path)}))
    store.append_event(JobEvent(job_id, "task_failed", task_id=task_id, site="mangaone", result="failed", reason="synthetic failure", key="key-a"))
    monitor = ExecutionMonitor(store)
    monitor.show()
    monitor.set_job(job_id)
    monitor.refresh()
    assert "batch mangaone: complete" in monitor.summary_view.toPlainText()
    assert "grant site=mangaone" in monitor.summary_view.toPlainText()
    assert "label=batch-grant" in monitor.summary_view.toPlainText()
    assert "task_failed: synthetic failure" in monitor.problem_view.toPlainText()
    assert monitor.summary_view.isReadOnly()
    assert monitor.problem_view.isReadOnly()
    controller.close()
    monitor.close()


def test_execution_monitor_summary_problem_display_is_bounded_and_scrollable(qt_app):
    from PySide6.QtWidgets import QPlainTextEdit

    from screenshot_crawler.gui.execution_monitor import _set_bounded_text

    summary = QPlainTextEdit()
    problems = QPlainTextEdit()
    summary.setReadOnly(True)
    problems.setReadOnly(True)
    first = _set_bounded_text(summary, "line\n" * 20_000, 1_000)
    assert "display truncated" in first
    assert summary.toPlainText() == first
    problems.setPlainText("problem\n" * 200)
    problems.verticalScrollBar().setValue(10)
    old_value = problems.verticalScrollBar().value()
    _set_bounded_text(problems, "problem\n" * 201, 10_000)
    assert problems.verticalScrollBar().value() <= old_value + 1
    assert summary.isReadOnly() and problems.isReadOnly()
    summary.deleteLater()
    problems.deleteLater()


def test_execution_monitor_char_trim_preserves_block_anchor(qt_app):
    from screenshot_crawler.gui.execution_monitor import ExecutionMonitor

    monitor = ExecutionMonitor()
    monitor.max_chars = 9_000
    monitor.max_blocks = 10_000
    monitor.show()
    lines = [f"line{i:04d} " + ("x" * 32) + "\n" for i in range(220)]
    monitor._append_log("".join(lines[:200]))
    monitor.log_view.verticalScrollBar().setValue(90)
    before = monitor.log_view.document().findBlockByNumber(
        monitor.log_view.verticalScrollBar().value()
    ).text()
    monitor._append_log("".join(lines[200:]))
    after = monitor.log_view.document().findBlockByNumber(
        monitor.log_view.verticalScrollBar().value()
    ).text()
    assert before == "line0090 " + ("x" * 32)
    assert after == before
    monitor.close()


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
    for index in range(600):
        store.append_event(JobEvent(
            job_id, "warning", task_id=f"{job_id}:mangaone", site="mangaone",
            key="key-a", reason=f"latest-{index}",
        ))
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
    assert "latest-599" in text
    assert "#1 grant_unknown" not in text
    controller.close()
    page.close()


@pytest.mark.parametrize(
    ("action", "selected_key"),
    (("discover", "sample-0000"), ("batch", "sample-0000"), ("grant_only", "sample-0001")),
)
def test_gui_real_controller_fake_child_covers_full_action_lifecycle(
    qt_app, tmp_path, monkeypatch, action, selected_key
):
    """Use a real controller/child/heartbeat with only site work faked."""
    import hashlib
    import sqlite3
    import sys
    import textwrap
    import time

    from PySide6.QtWidgets import QDialog

    from screenshot_crawler.gui.execution_dialog import ExecutionPreviewDialog
    from screenshot_crawler.management.inventory import InventoryService
    from screenshot_crawler.management.job_controller import JobController
    from tools.gui_sample import create_sample

    fake_worker = tmp_path / "fake_worker.py"
    fake_worker.write_text(textwrap.dedent('''
        import argparse, asyncio, json, os, sys
        from datetime import UTC, datetime
        from pathlib import Path
        from screenshot_crawler.management.jobs import JobEvent, JsonlEventSink
        from screenshot_crawler.management.process_identity import process_start_identity

        def main():
            parser = argparse.ArgumentParser()
            parser.add_argument("--job-id", required=True)
            parser.add_argument("--job-dir", required=True)
            parser.add_argument("--request-json", required=True)
            parser.add_argument("--worker-token", required=True)
            parser.add_argument("--start-gate", required=True)
            args = parser.parse_args()
            job_dir = Path(args.job_dir)
            request = json.loads(Path(args.request_json).read_text(encoding="utf-8"))
            identity = {"pid": os.getpid(), "token": args.worker_token,
                        "start_identity": process_start_identity(os.getpid())}
            (job_dir / "worker.identity").write_text(json.dumps(identity), encoding="utf-8")
            while Path(args.start_gate).read_text(encoding="utf-8").strip() != "go":
                asyncio.run(asyncio.sleep(0.01))
            heartbeat = {**identity, "job_id": args.job_id,
                         "observed_at": datetime.now(UTC).isoformat()}
            (job_dir / "worker.heartbeat.json").write_text(json.dumps(heartbeat), encoding="utf-8")
            sink = JsonlEventSink(job_dir / "events.jsonl", args.job_id)
            site = str(request["sites"][0])
            task_id = f"{args.job_id}:{site}"
            def emit(event_type, **fields):
                sink.emit(JobEvent(args.job_id, event_type, task_id=task_id, site=site, **fields))
            action = str(request["action"])
            print(f"{action} child stdout — 日本語 😀", flush=True)
            print(f"{action} child stderr — 警告", file=sys.stderr, flush=True)
            emit("job_started", phase="planning", payload={"pid": os.getpid()})
            emit("task_started", phase="running")
            if action == "discover":
                emit("discovery_result", key=str(request["selected_keys"][0]), result="succeeded",
                     payload={"target": str(request["selected_keys"][0]), "observed": 4,
                              "new": 2, "known": 2, "complete": True,
                              "stopped_reason": "exhausted", "warnings": ["synthetic warning"]})
            else:
                metrics = Path(str(request.get("metrics_root") or "output/metrics")) / site
                metrics.mkdir(parents=True, exist_ok=True)
                metrics_path = metrics / (args.job_id + ".jsonl")
                records = [
                    {"type": "batch", "event": "start", "site": site, "run_id": args.job_id},
                    {"type": "candidate", "event": "result", "site": site, "item_id": 17,
                     "source_id": 23, "resource": "synthetic_ticket", "result": "failed" if action == "grant_only" else "completed"},
                    {"type": "grant_result", "site": site, "work_id": 7, "label": "synthetic work",
                     "item_id": 17, "source_id": 23, "resource": "synthetic_ticket",
                     "status": "OK", "reason": "postprocess failed" if action == "grant_only" else "done",
                     "resource_consumed": True},
                    {"type": "batch_summary", "candidates_started": 1,
                     "candidates_completed": 0 if action == "grant_only" else 1,
                     "candidates_failed": 1 if action == "grant_only" else 0,
                     "candidates_skipped": 0, "elapsed": 0.1, "stop_reason": None},
                ]
                metrics_path.write_text("".join(json.dumps(value) + "\\n" for value in records), encoding="utf-8")
                emit("metrics_started", payload={"metrics_path": str(metrics_path)})
                emit("candidate_started", key=str(request["selected_keys"][0]), item_id=17, source_id=23,
                     resource="synthetic_ticket")
                emit("candidate_finished", key=str(request["selected_keys"][0]), item_id=17, source_id=23,
                     resource="synthetic_ticket", result="failed" if action == "grant_only" else "succeeded")
            emit("task_finished", result="succeeded")
            emit("job_finished", result="succeeded")
            emit("process_exited", result="succeeded")
            return 0

        raise SystemExit(main())
    '''), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parents[2]))
    db, watchlist = create_sample(tmp_path / "inputs")
    runtime = tmp_path / "inputs" / "sample-runtime.yaml"
    with sqlite3.connect(db) as connection:
        connection.execute("UPDATE items SET status='completed'")
    input_hashes = (hashlib.sha256(db.read_bytes()).hexdigest(), hashlib.sha256(watchlist.read_bytes()).hexdigest())
    snapshot = InventoryService().load(db, watchlist, runtime_path=runtime)

    class IsolatedController(JobController):
        def __init__(self, store):
            super().__init__(store, python_executable=sys.executable, worker_module="fake_worker")

    monkeypatch.setattr("screenshot_crawler.management.job_controller.JobController", IsolatedController)
    window = MainWindow(db, watchlist, runtime, auto_load=False, management_path=tmp_path / "management.sqlite")
    window.set_snapshot(snapshot)
    window.model.set_checked_keys({selected_key})
    window.show()
    QApplication.processEvents()
    confirmed = []

    def confirm(dialog):
        assert dialog.preview.can_confirm, dialog.preview.blockers
        assert dialog.request.action == action
        confirmed.append(dialog.request)
        dialog._confirm()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ExecutionPreviewDialog, "exec", confirm)
    controller = window._ensure_jobs()

    def wait_terminal(job_id):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            QApplication.processEvents()
            window._poll_jobs()
            if controller.active_job_id is None and window._job_store.get_job(job_id)["state"] in {"succeeded", "failed", "partial", "interrupted"}:
                return
            time.sleep(0.02)
        pytest.fail("isolated fake child lifecycle timed out")

    try:
        window._show_execution_preview(action)
        first_id = window._session_job_ids[-1]
        wait_terminal(first_id)
        assert window._job_store.get_job(first_id)["state"] == "succeeded"
        window.execution_monitor.set_job(first_id)
        window.execution_monitor.refresh()
        summary = window.execution_monitor.summary_view.toPlainText()
        log = window.execution_monitor.log_view.toPlainText()
        assert action in summary and "日本語" in log
        if action == "discover":
            assert "observed=4" in summary and "synthetic warning" in summary
        elif action == "batch":
            assert "batch mangaone" in summary and "started=1" in summary
        else:
            assert "grant site=magapoke" in summary and "consumed=True" in summary
            assert "postprocess" in summary or "postprocess" in window.execution_monitor.problem_view.toPlainText()
        window._jobs_page.refresh()
        assert action in window._jobs_page.details.toPlainText()
        window._rerun_job(first_id)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and len(window._session_job_ids) < 2:
            QApplication.processEvents()
            window._poll_jobs()
            time.sleep(0.02)
        assert len(confirmed) == 2
        second_id = window._session_job_ids[-1]
        wait_terminal(second_id)
        assert window._job_store.get_job(second_id)["original_job_id"] == first_id
        assert hashlib.sha256(db.read_bytes()).hexdigest() == input_hashes[0]
        assert hashlib.sha256(watchlist.read_bytes()).hexdigest() == input_hashes[1]
    finally:
        window._job_poll_timer.stop()
        if controller.active_job_id is not None:
            controller.force_stop()
        controller.close()
        window.close()
        window.thread_pool.waitForDone(5000)
        QApplication.processEvents()


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
        assert dialog.request.action == "batch"
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

