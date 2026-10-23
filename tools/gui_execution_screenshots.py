"""Render native P2/P3 widgets using synthetic inputs and invented job history.

This QA tool never starts a worker, connects to a browser, or changes operational
inputs. --sample-output must name a new directory, as in gui_sample.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import replace
from pathlib import Path

from gui_sample import create_sample
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication

from screenshot_crawler.gui.execution_dialog import ExecutionPreviewDialog
from screenshot_crawler.gui.main_window import MainWindow
from screenshot_crawler.management.execution import ExecutionPlanService, ExecutionSelection
from screenshot_crawler.management.inventory import InventoryService, default_policy_registry
from screenshot_crawler.management.jobs import JobEvent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-output", required=True, type=Path)
    parser.add_argument("--screenshots", type=Path, default=Path("docs/gui-screenshots"))
    args = parser.parse_args()
    sample = args.sample_output.resolve()
    db, watchlist = create_sample(sample)
    runtime = sample / "sample-runtime.yaml"
    env_file = sample / "sample.env"
    env_file.write_text("CRAWLER_CDP_ENDPOINT=http://127.0.0.1:1\n", encoding="utf-8")
    settings = {
        "runtime_path": str(runtime), "env_file": str(env_file),
        "output_root": str(sample / "batch"), "library_dir": str(sample / "Books"),
        "metrics_root": str(sample / "metrics"), "limit": 3,
    }
    snapshot = InventoryService().load(db, watchlist, runtime_path=runtime)
    service = ExecutionPlanService()
    selected_keys = {"sample-0004", "sample-0005"}
    plans = [
        service.preview_batch(
            str(db), str(watchlist), default_policy_registry(),
            site=site, selected_keys=[key], **settings,
        )
        for site, key in (("magapoke", "sample-0005"), ("mangaone", "sample-0004"))
    ]
    preview = replace(
        plans[0], selection=ExecutionSelection.from_keys(selected_keys),
        sites=("magapoke", "mangaone"),
        candidate_count=sum(plan.candidate_count for plan in plans),
        skipped_count=sum(plan.skipped_count for plan in plans),
        skipped=tuple(value for plan in plans for value in plan.skipped),
        blockers=tuple(value for plan in plans for value in plan.blockers),
        warnings=tuple(value for plan in plans for value in plan.warnings),
        work_names=tuple(sorted({value for plan in plans for value in plan.work_names})),
        fingerprint=hashlib.sha256(json.dumps(
            [plan.fingerprint for plan in plans], separators=(",", ":"),
        ).encode()).hexdigest(),
    )
    assert preview.can_confirm, preview.blockers
    request = replace(
        preview.request(snapshot), runtime_path=str(runtime), env_file=str(env_file),
        output_root=settings["output_root"], library_dir=settings["library_dir"],
        metrics_root=settings["metrics_root"],
    )
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow(
        db, watchlist, runtime, management_path=sample / "management/management.sqlite",
        auto_load=False,
    )
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    window.set_snapshot(snapshot)
    window.model.set_checked_keys(selected_keys)
    window.execution_limit_spin.setValue(3)
    window.model.focus_node(window.model.node_by_key_identity("sample-0004"))
    window.catalog_edit.setText("sample.sqlite")
    window.watchlist_edit.setText("sample-watchlist.yaml")
    window.runtime_edit.setText("sample-runtime.yaml")
    window.setWindowTitle("Screenshot Crawler — 合成データ・実行なし")
    window.resize(1400, 850)
    window.show()
    args.screenshots.mkdir(parents=True, exist_ok=True)
    captured = []

    def save(widget, name: str) -> None:
        app.processEvents()
        if not widget.grab().save(str(args.screenshots / name)):
            raise RuntimeError(f"Could not save screenshot {name}")
        captured.append(name)

    save(window, "p2-execution.png")
    dialog = ExecutionPreviewDialog(preview, request, window)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    dialog.resize(900, 700)
    dialog.show()
    save(dialog, "p2-confirmation.png")
    dialog.reject()

    grant = service.preview_batch(
        str(db), str(watchlist), default_policy_registry(), site="magapoke",
        selected_keys=["sample-0005"], resource="all", **settings,
    )
    grant_dialog = ExecutionPreviewDialog(grant, grant.request(snapshot), window)
    grant_dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    grant_dialog.resize(900, 700)
    grant_dialog.show()
    save(grant_dialog, "p2-grant-confirmation.png")
    grant_dialog.reject()

    # Deliberately invented management history, never Catalog acquisition data.
    controller = window._ensure_jobs()
    store = controller.store
    job_id = controller.queue(request)
    store.set_state(job_id, "running")
    for site, key, source_id in (
        ("magapoke", "sample-0005", 65), ("mangaone", "sample-0004", 53),
    ):
        task = f"{job_id}:{site}"
        metrics = sample / "metrics" / site / "synthetic-metrics.json"
        metrics.parent.mkdir(parents=True, exist_ok=True)
        metrics.write_text('{"synthetic": true}\n', encoding="utf-8")
        for event in (
            JobEvent(job_id, "task_started", task_id=task, site=site),
            JobEvent(job_id, "metrics_started", task_id=task, site=site,
                     payload={"metrics_path": str(metrics)}),
            JobEvent(job_id, "candidate_started", task_id=task, site=site,
                     key=key, item_id=source_id, source_id=source_id),
            JobEvent(job_id, "candidate_finished", task_id=task, site=site,
                     key=key, item_id=source_id, source_id=source_id, result="succeeded"),
            JobEvent(job_id, "task_finished", task_id=task, site=site, result="succeeded"),
        ):
            store.append_event(event)
    store.set_state(job_id, "succeeded", summary={"synthetic": True})
    interrupted = controller.queue(request)
    store.mark_interrupted(interrupted, reason="合成履歴: worker異常終了・消費状態は要確認")
    controller.queue(request)
    page = window._jobs_page
    assert page is not None
    page.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    page.setWindowTitle("ジョブ履歴 — 合成データ・実行なし")
    page.resize(1150, 850)
    page.refresh()
    selected = next(i for i, row in enumerate(page._rows) if row["job_id"] == job_id)
    page.list_widget.setCurrentRow(selected)
    page.details.setPlainText(page.details.toPlainText().replace(str(sample), "SAMPLE"))
    page.show()
    save(page, "p3-jobs.png")
    selected = next(i for i, row in enumerate(page._rows) if row["job_id"] == interrupted)
    page.list_widget.setCurrentRow(selected)
    page.details.setPlainText(page.details.toPlainText().replace(str(sample), "SAMPLE"))
    save(page, "p3-interrupted.png")
    assert controller.process is None, "Screenshot generation must never start a worker"
    report = {
        "platform": app.platformName(), "screenshots": captured, "worker_started": False,
        "inventory_size": [window.width(), window.height()],
    }
    (args.screenshots / "p3-render.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    window._job_poll_timer.stop()
    for widget in (grant_dialog, dialog, page, window):
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    app.quit()
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
