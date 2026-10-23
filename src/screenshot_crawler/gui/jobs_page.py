"""Compact Qt view for the persistent P3 job queue and history."""

from __future__ import annotations

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from screenshot_crawler.management.inventory import display_time
from screenshot_crawler.management.job_controller import JobController
from screenshot_crawler.management.jobs import TERMINAL_JOB_STATES, JobStore


def _format_limit(value: object) -> str:
    """Use the same visible convention as the execution controls."""

    if value in (None, 0):
        return "unlimited"
    return str(value)


def _format_consumed(value: object) -> str:
    """Keep the resource-consumption tri-state visible in history."""

    if value is None:
        return "unknown"
    return "yes" if bool(value) else "no"


def _format_resource_mapping(request: dict[str, object]) -> str:
    raw = request.get("resources_by_site")
    if isinstance(raw, dict) and raw:
        return ", ".join(f"{site}={resource}" for site, resource in sorted(raw.items()))
    resource = request.get("resource")
    return str(resource) if resource is not None else "—"


class JobsPage(QWidget):
    """Read-only job history plus explicit cooperative stop controls."""

    rerunRequested = Signal(str)

    def __init__(self, store: JobStore, controller: JobController, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.store = store
        self.controller = controller
        self.setWindowTitle("Screenshot Crawler — ジョブ履歴")
        root = QVBoxLayout(self)
        self.health_label = QLabel()
        root.addWidget(self.health_label)
        self.list_widget = QListWidget()
        self.list_widget.currentRowChanged.connect(self._show_selected)
        root.addWidget(self.list_widget, 2)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        root.addWidget(self.details, 2)
        controls = QHBoxLayout()
        self.refresh_button = QPushButton("更新")
        self.refresh_button.clicked.connect(self.refresh)
        controls.addWidget(self.refresh_button)
        self.stop_button = QPushButton("停止要求")
        self.stop_button.clicked.connect(self._request_stop)
        controls.addWidget(self.stop_button)
        self.force_button = QPushButton("強制終了（非常）")
        self.force_button.clicked.connect(self._force_stop)
        controls.addWidget(self.force_button)
        self.cancel_button = QPushButton("キュー取消")
        self.cancel_button.clicked.connect(self._request_stop)
        controls.addWidget(self.cancel_button)
        self.resume_button = QPushButton("選択ジョブを開始")
        self.resume_button.clicked.connect(self._resume_selected)
        controls.addWidget(self.resume_button)
        self.rerun_button = QPushButton("最新状態で再計画")
        self.rerun_button.clicked.connect(self._request_rerun)
        controls.addWidget(self.rerun_button)
        controls.addStretch(1)
        root.addLayout(controls)
        self.refresh()

    def refresh(self) -> None:
        try:
            rows = self.store.list_jobs()
        except Exception as exc:  # noqa: BLE001 - show management DB health
            self.health_label.setText(f"管理DB unavailable: {exc}")
            return
        active = sum(row["state"] in {"planning", "running"} for row in rows)
        queued = sum(row["state"] == "queued" for row in rows)
        failed = sum(row["state"] in {"failed", "partial", "interrupted"} for row in rows)
        if self.controller.supervision_error:
            health = "要確認: worker supervision failed"
        elif self.controller.orphaned_live_worker:
            health = "要確認: previous worker identity is still live"
        elif self.controller.worker_heartbeat_stale:
            health = "要確認: worker heartbeat stale"
        elif active:
            health = "worker healthy"
        else:
            health = "待機中"
        self.health_label.setText(
            f"{health} / active {active} / queued {queued} / recent failures {failed}"
        )
        current_job_id = None
        current = self.list_widget.currentRow()
        if 0 <= current < len(getattr(self, "_rows", ())):
            current_job_id = self._rows[current]["job_id"]
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for row in rows:
            self.list_widget.addItem(
                f"{row['state']}  {row['action']}  {display_time(row['requested_at'])}  "
                f"keys={len(json.loads(row['selected_keys_json']))}"
            )
        self.list_widget.blockSignals(False)
        self._rows = rows
        selected_index = next(
            (index for index, row in enumerate(rows) if row["job_id"] == current_job_id),
            0,
        )
        if rows:
            self.list_widget.setCurrentRow(selected_index)
        self._show_selected(self.list_widget.currentRow())

    def _show_selected(self, index: int) -> None:
        if index < 0 or index >= len(getattr(self, "_rows", ())):
            self.details.clear()
            return
        row = self._rows[index]
        tasks = self.store.list_tasks(row["job_id"])
        events = self.store.list_events(row["job_id"])
        request = json.loads(row["request_json"])
        lines = [
            f"Job: {row['job_id']}",
            f"Action: {row['action']}",
            f"Mode: {request.get('mode') or row['action']} / max count: {_format_limit(request.get('limit'))}",
            f"Resources: {_format_resource_mapping(request)}",
            f"State: {row['state']}",
            f"Requested: {display_time(row['requested_at'])} / started {display_time(row['started_at'])} / ended {display_time(row['ended_at'])}",
            f"Catalog: {request.get('catalog_path', '—')}",
            f"Watchlist: {request.get('watchlist_path', '—')}",
            f"Selected keys: {', '.join(json.loads(row['selected_keys_json']))}",
            f"Fingerprint: {row['planned_fingerprint'][:16]}",
            "Tasks:",
        ]
        for task in tasks:
            lines.append(
                f"  {task['site']}: {task['state']}  success={task['success_count']} "
                f"failed={task['failed_count']} skip={task['skipped_count']} "
                f"unknown={task['unknown_count']} attempts={task['observed_attempts']}"
            )
            lines.append(
                f"    mode={task['mode'] or row['action']} "
                f"max_count={_format_limit(task['limit_count'])} "
                f"resource={task['resource'] or '—'}"
            )
            lines.append(f"    metrics: {task['metrics_path'] or '—'}")
            lines.append(f"    stdout: {task['stdout_path'] or '—'}")
            lines.append(f"    stderr: {task['stderr_path'] or '—'}")
        lines.append(f"Events: {len(events)}")
        for event in events[-30:]:
            context = []
            for label, key in (
                ("site", "site"),
                ("key", "key_identity"),
                ("item", "item_id"),
                ("source", "source_id"),
            ):
                value = event[key]
                if value is not None:
                    context.append(f"{label}={value}")
            resource = event["resource"]
            consumed = event["resource_consumed"]
            if resource is not None or consumed is not None:
                context.append(f"resource={resource or '—'}")
                context.append(f"consumed={_format_consumed(consumed)}")
            suffix = " " + " ".join(context) if context else ""
            lines.append(
                f"  #{event['sequence']} {event['event_type']} "
                f"{event['result'] or ''} {event['reason'] or ''}{suffix}".rstrip()
            )
        if row["state"] == "interrupted":
            lines.append("消費状態不明の可能性があります。自動再試行は行いません。")
        self.details.setPlainText("\n".join(lines))
        active = row["state"] in {"planning", "running"}
        self.stop_button.setEnabled(active)
        self.force_button.setEnabled(active)
        self.cancel_button.setEnabled(row["state"] == "queued")
        self.resume_button.setEnabled(row["state"] == "queued" and self.controller.active_job_id is None)
        self.rerun_button.setEnabled(row["state"] in TERMINAL_JOB_STATES)

    def _selected_job_id(self) -> str | None:
        index = self.list_widget.currentRow()
        if index < 0 or index >= len(getattr(self, "_rows", ())):
            return None
        return self._rows[index]["job_id"]

    def _request_stop(self) -> None:
        job_id = self._selected_job_id()
        if job_id is not None:
            if self.controller.active_job_id == job_id:
                self.controller.request_stop()
            else:
                self.store.request_cancel(job_id)
            self.refresh()

    def _force_stop(self) -> None:
        job_id = self._selected_job_id()
        if job_id is None or self.controller.active_job_id != job_id:
            return
        answer = QMessageBox.warning(
            self,
            "強制終了の確認",
            "workerを強制終了します。Quota・チケット・成果物の消費状態が不明になる可能性があります。\n"
            "自動再試行は行われません。続行しますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.controller.force_stop()
            self.refresh()

    def _request_rerun(self) -> None:
        job_id = self._selected_job_id()
        if job_id is not None:
            self.rerunRequested.emit(job_id)

    def _resume_selected(self) -> None:
        job_id = self._selected_job_id()
        if job_id is None or self.controller.active_job_id is not None:
            return
        try:
            self.controller.start_job(job_id)
        except (KeyError, RuntimeError) as exc:
            self.health_label.setText(f"ジョブ開始不可: {exc}")
        self.refresh()


__all__ = ["JobsPage"]
