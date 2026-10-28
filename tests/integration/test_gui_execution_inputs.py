"""GUI checks for lightweight execution requests and the post-save Full prompt."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QMessageBox

from screenshot_crawler.gui.main_window import MainWindow
from screenshot_crawler.management.execution import JobExecutionRequest
from screenshot_crawler.management.inventory import InventoryService
from screenshot_crawler.management.job_controller import JobController
from screenshot_crawler.management.jobs import JobStore

sys.path.insert(0, str(Path(__file__).parents[2]))
from tools.gui_sample import create_sample


@pytest.mark.parametrize("outcome", ["stopped", "failed", "orphaned", "broken_monitor"])
def test_emergency_stop_terminates_active_job_and_pauses_dispatch(
    tmp_path, qt_app, monkeypatch, outcome
):
    from types import SimpleNamespace

    window = _window(tmp_path, qt_app)
    store = JobStore(tmp_path / "management.sqlite")
    controller = JobController(store)
    request = JobExecutionRequest(
        action="batch", selected_keys=frozenset({"sample-0000"}),
        sites=("mangaone",), keys_by_site=(("mangaone", ("sample-0000",)),),
    )
    active = controller.queue(request)
    queued = controller.queue(request)
    store.set_state(active, "running")
    killed = []

    class Process:
        pid = 123456789
        returncode = None

        def poll(self):
            return self.returncode

        def kill(self):
            killed.append(active)
            if outcome == "failed":
                raise RuntimeError("synthetic stop failure")
            self.returncode = -9

        def wait(self, timeout=None):
            return self.returncode

    controller.process = Process()
    controller.active_job_id = active
    window._job_controller = controller
    window._job_store = store
    window._session_job_ids = [active, queued]
    window._pending_rerun = (queued, frozenset({"sample-0000"}), "batch")
    work_states, key_states = [], []
    window._work_editor = SimpleNamespace(set_active_job=work_states.append)
    window._watchlist_editor = SimpleNamespace(set_active_job=key_states.append)
    window.execution_monitor.set_store(store)
    if outcome == "broken_monitor":
        def fail_refresh():
            raise RuntimeError("synthetic monitor failure")

        monkeypatch.setattr(window.execution_monitor, "refresh_jobs", fail_refresh)
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda *a, **k: pytest.fail("emergency stop must not ask for confirmation"),
    )
    if outcome == "orphaned":
        monkeypatch.setattr(
            "screenshot_crawler.management.job_controller._verified_worker_pid",
            lambda *a, **k: 123456789,
        )
        monkeypatch.setattr(
            "screenshot_crawler.management.job_controller._terminate_pid",
            lambda *a, **k: False,
        )
    try:
        window._poll_jobs()
        assert window.emergency_stop_button.isEnabled()
        window.emergency_stop_button.click()
        assert killed == [active]
        assert window._session_job_ids == []
        assert window._pending_rerun is None
        assert store.get_job(queued)["state"] == "queued"
        assert "未確認" in window.error_label.text() or "確認できません" in window.error_label.text()
        if outcome == "failed":
            assert controller.active_job_id == active
            assert window.emergency_stop_button.isEnabled()
            assert work_states[-1] and key_states[-1]
            assert "失敗" in window.error_label.text()
        else:
            assert store.get_job(active)["state"] == "interrupted"
            assert json.loads(store.get_job(active)["summary_json"])["resource_consumed"] is None
            assert controller.active_job_id is None
            assert not window.emergency_stop_button.isEnabled()
            assert not work_states[-1] and not key_states[-1]
            if outcome == "orphaned":
                window._on_checked_changed(window.model.selected_keys)
                assert not window.batch_run_button.isEnabled()
                with pytest.raises(RuntimeError, match="unverified worker"):
                    controller.start_job(queued)
    finally:
        window._work_editor = None
        window._watchlist_editor = None
        window._job_controller = None
        controller.close()
        window.close()


def test_emergency_stop_is_disabled_without_an_active_worker(tmp_path, qt_app):
    window = _window(tmp_path, qt_app)
    try:
        assert not window.emergency_stop_button.isEnabled()
        window._emergency_stop()
        assert window._job_controller is None
        assert not window.emergency_stop_button.isEnabled()
    finally:
        window.close()


@pytest.fixture
def qt_app():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    yield app
    app.processEvents()


def _window(tmp_path, qt_app):
    db, watchlist = create_sample(tmp_path / "inputs")
    runtime = tmp_path / "inputs" / "sample-runtime.yaml"
    snapshot = InventoryService().load(db, watchlist, runtime_path=runtime)
    window = MainWindow(db, watchlist, runtime, auto_load=False)
    window.set_snapshot(snapshot)
    window.model.set_checked_keys({"sample-0000", "sample-0001"})
    return window


@pytest.mark.parametrize("action", ["discover", "batch", "grant_only"])
def test_normal_actions_queue_without_preview_or_confirmation(
    tmp_path, qt_app, monkeypatch, action
):
    window = _window(tmp_path, qt_app)
    captured = []
    monkeypatch.setattr(window, "_start_execution", captured.append)
    monkeypatch.setattr(
        "screenshot_crawler.gui.main_window.ExecutionPlanService.preview",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("preview called")),
    )
    monkeypatch.setattr(
        "screenshot_crawler.gui.main_window.ExecutionPlanService.preview_batch",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("preview_batch called")),
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("confirmation called")),
    )
    window._show_execution_preview(action)
    assert len(captured) == 1
    request = captured[0]
    assert request.action == action
    assert request.fingerprint_kind == "inputs-v1"
    assert request.plan_fingerprint.startswith("inputs-v1:")
    assert request.sites == ("magapoke", "mangaone")
    window.close()


def test_watchlist_full_asks_once_and_yes_queues_inputs_request(
    tmp_path, qt_app, monkeypatch
):
    window = _window(tmp_path, qt_app)
    captured = []
    questions = []
    monkeypatch.setattr(window, "_start_execution", captured.append)

    def ask(*args, **kwargs):
        questions.append((args, kwargs))
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", ask)
    window._show_execution_preview(
        "discover",
        force_full=True,
        after_watchlist_save=True,
    )
    assert len(questions) == 1
    assert len(captured) == 1
    assert captured[0].mode == "full"
    assert captured[0].fingerprint_kind == "inputs-v1"
    assert "Catalog" in questions[0][0][2]
    window.close()


def test_watchlist_full_no_does_not_queue(tmp_path, qt_app, monkeypatch):
    window = _window(tmp_path, qt_app)
    captured = []
    monkeypatch.setattr(window, "_start_execution", captured.append)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )
    window._show_execution_preview("discover", force_full=True, after_watchlist_save=True)
    assert captured == []
    window.close()


def test_legacy_editor_full_uses_the_same_single_confirmation_path(
    tmp_path, qt_app, monkeypatch
):
    window = _window(tmp_path, qt_app)
    calls = []
    monkeypatch.setattr(
        window,
        "_show_execution_preview",
        lambda action, **kwargs: calls.append((action, kwargs)),
    )
    window._pending_editor_full = "sample-0000"
    window._load_succeeded(window.model.snapshot)
    assert calls == [
        (
            "discover",
            {
                "selected_keys": {"sample-0000"},
                "force_full": True,
                "after_watchlist_save": True,
            },
        )
    ]
    window.close()
