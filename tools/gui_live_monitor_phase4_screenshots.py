"""Capture native Phase04 monitor states from synthetic management jobs.

The helper creates all inputs below the requested sample directory, never
starts a worker, and never connects to a browser or an operational database.
It intentionally uses the production MainWindow/JobsPage/ExecutionMonitor
widgets so the images are suitable for layout review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from gui_sample import create_sample
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QSplitter

from screenshot_crawler.gui.main_window import MainWindow
from screenshot_crawler.management.execution import JobExecutionRequest
from screenshot_crawler.management.inventory import InventoryService
from screenshot_crawler.management.jobs import JobEvent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-output", required=True, type=Path)
    parser.add_argument("--screenshots", required=True, type=Path)
    args = parser.parse_args()
    sample = args.sample_output.resolve()
    screenshots = args.screenshots.resolve()
    db, watchlist = create_sample(sample, key_count=4, sources_per_key=4)
    runtime = sample / "sample-runtime.yaml"
    snapshot = InventoryService().load(db, watchlist, runtime_path=runtime)
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow(
        db, watchlist, runtime, management_path=sample / "management/management.sqlite",
        auto_load=False,
    )
    window.set_snapshot(snapshot)
    window.model.set_checked_keys({"sample-0000"})
    window.model.focus_node(window.model.node_by_key_identity("sample-0000"))
    window.show()
    app.processEvents()
    controller = window._ensure_jobs()
    store = controller.store
    jobs: list[tuple[str, str]] = []
    for action, state in (("discover", "failed"), ("batch", "succeeded"), ("grant_only", "failed")):
        request = JobExecutionRequest(
            action=action,
            selected_keys=frozenset({"sample-0000"}),
            sites=("mangaone",),
            keys_by_site=(("mangaone", ("sample-0000",)),),
            resource="synthetic_ticket" if action == "grant_only" else None,
            metrics_root=str(sample / "metrics"),
            plan_fingerprint=hashlib.sha256(action.encode()).hexdigest(),
        )
        job_id = controller.queue(request)
        store.set_state(job_id, state, summary={"synthetic": True, "reason": "isolated QA"})
        task_id = f"{job_id}:mangaone"
        store.append_event(JobEvent(
            job_id, "task_started", task_id=task_id, site="mangaone",
            event_id=f"{job_id}:started",
        ))
        store.append_event(JobEvent(
            job_id, "candidate_finished", task_id=task_id, site="mangaone",
            key="sample-0000", item_id=17, source_id=23,
            result="failed" if state == "failed" else "succeeded",
            reason="synthetic postprocess warning" if state == "failed" else None,
            event_id=f"{job_id}:candidate",
        ))
        if action == "discover":
            store.append_event(JobEvent(
                job_id, "discovery_result", task_id=task_id, site="mangaone",
                key="sample-0000", result="succeeded",
                payload={"target": "sample-0000", "observed": 4, "new": 2,
                         "known": 2, "complete": True,
                         "stopped_reason": "exhausted",
                         "warnings": ["synthetic discovery warning"]},
                event_id=f"{job_id}:discovery",
            ))
        else:
            metrics_path = sample / "metrics" / "mangaone" / f"{job_id}.jsonl"
            metrics_path.parent.mkdir(parents=True, exist_ok=True)
            candidate_result = "failed" if action == "grant_only" else "completed"
            metrics_path.write_text("".join(json.dumps(record) + "\n" for record in (
                {"type": "batch", "event": "start", "site": "mangaone", "run_id": job_id},
                {"type": "candidate", "event": "result", "site": "mangaone",
                 "item_id": 17, "source_id": 23, "resource": "synthetic_ticket",
                 "result": candidate_result},
                {"type": "grant_result", "site": "mangaone", "work_id": 7,
                 "label": "synthetic work", "item_id": 17, "source_id": 23,
                 "resource": "synthetic_ticket", "status": "OK",
                 "reason": "postprocess failed" if action == "grant_only" else "done",
                 "resource_consumed": True},
                {"type": "batch_summary", "candidates_started": 1,
                 "candidates_completed": 0 if action == "grant_only" else 1,
                 "candidates_failed": 1 if action == "grant_only" else 0,
                 "candidates_skipped": 0, "elapsed": 0.1,
                 "stop_reason": None},
            )), encoding="utf-8")
            store.append_event(JobEvent(
                job_id, "metrics_started", task_id=task_id, site="mangaone",
                payload={"metrics_path": str(metrics_path)},
                event_id=f"{job_id}:metrics-started",
            ))
            store.append_event(JobEvent(
                job_id, "batch_finished", task_id=task_id, site="mangaone",
                payload={"metrics_path": str(metrics_path), "run_id": job_id},
                result="succeeded", event_id=f"{job_id}:batch-finished",
            ))
        store.append_event(JobEvent(
            job_id, "task_finished", task_id=task_id, site="mangaone",
            result="failed" if state == "failed" else "succeeded",
            event_id=f"{job_id}:finished",
        ))
        job_dir = store.job_dir(job_id)
        (job_dir / "stdout.log").write_text(
            f"{action} stdout — 日本語 😀\nsynthetic result={state}\n", encoding="utf-8"
        )
        (job_dir / "stderr.log").write_text(
            f"{action} stderr — 警告\n", encoding="utf-8"
        )
        jobs.append((action, job_id))

    screenshots.mkdir(parents=True, exist_ok=True)
    captured: list[str] = []

    def save(widget, name: str) -> None:
        app.processEvents()
        if not widget.grab().save(str(screenshots / name)):
            raise RuntimeError(f"could not save {name}")
        captured.append(name)

    def select(job_id: str) -> None:
        window.execution_monitor.set_job(job_id)
        window.execution_monitor.refresh()
        window.execution_monitor.summary_view.verticalScrollBar().setValue(0)
        window.execution_monitor.problem_view.verticalScrollBar().setValue(0)
        app.processEvents()

    select(jobs[2][1])
    window.resize(980, 600)
    app.processEvents()
    save(window, "phase4-live-monitor-980-failed.png")
    splitter = window.findChild(QSplitter, "execution_vertical_splitter")
    assert splitter is not None
    upper = splitter.widget(0)
    monitor = splitter.widget(1)
    assert upper is not None and monitor is not None
    assert upper.height() >= upper.minimumHeight()
    geometry = {
        "logical_size": [window.width(), window.height()],
        "window_minimum_height": window.minimumHeight(),
        "upper_height": upper.height(),
        "upper_minimum_hint": upper.minimumSizeHint().height(),
        "upper_minimum_height": upper.minimumHeight(),
        "monitor_height": monitor.height(),
        "monitor_collapsed": bool(window.execution_monitor._collapsed),
        "action_width": window.execution_monitor.action_label.width(),
        "state_width": window.execution_monitor.state_label.width(),
        "location_width": window.execution_monitor.location_label.width(),
        "device_pixel_ratio": window.devicePixelRatioF(),
    }
    select(jobs[0][1])
    window.resize(1400, 850)
    app.processEvents()
    window.execution_monitor.set_collapsed(False)
    app.processEvents()
    splitter.setSizes([max(upper.minimumHeight(), splitter.height() - 180), 180])
    app.processEvents()
    manual_monitor_height = splitter.sizes()[1]
    window.resize(1380, 850)
    app.processEvents()
    assert upper.height() >= upper.minimumHeight()
    assert splitter.sizes()[1] >= manual_monitor_height - 8
    window.resize(1400, 850)
    app.processEvents()
    splitter.setSizes([max(upper.minimumHeight(), splitter.height() - 230), 230])
    app.processEvents()
    assert window.width() == 1400 and window.height() == 850
    save(window, "phase4-live-monitor-1400-discover.png")
    select(jobs[1][1])
    save(window, "phase4-live-monitor-1400-batch.png")
    select(jobs[2][1])
    save(window, "phase4-live-monitor-1400-grant-failed.png")
    page = window._jobs_page
    assert page is not None
    page.resize(1150, 850)
    page.refresh()
    page.show()
    app.processEvents()
    page.execution_monitor.set_job(jobs[2][1])
    page.execution_monitor.refresh()
    page.execution_monitor.summary_view.verticalScrollBar().setValue(0)
    page.execution_monitor.problem_view.verticalScrollBar().setValue(0)
    app.processEvents()
    save(page, "phase4-live-monitor-history.png")
    report = {
        "platform": app.platformName(),
        "device_pixel_ratio": app.primaryScreen().devicePixelRatio(),
        "logical_sizes": [[980, 600], [1400, 850], [1150, 850]],
        "capture_sizes": {
            "window_1400": [window.width(), window.height()],
            "history_1150": [page.width(), page.height()],
        },
        "geometry_980": geometry,
        "screenshots": captured,
        "actions": [action for action, _ in jobs],
        "worker_started": False,
        "browser_connected": False,
        "synthetic_input_sha256": hashlib.sha256(watchlist.read_bytes()).hexdigest(),
    }
    (screenshots / "phase4-live-monitor.actual.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    window._job_poll_timer.stop()
    page.close()
    window.close()
    controller.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
