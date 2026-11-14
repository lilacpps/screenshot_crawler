"""Qt worker/dialog for the explicit Work deletion Stage 04 surface."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
)

from screenshot_crawler.maintenance.work_deletion import (
    WorkDeletionApplyError,
    WorkDeletionCancelled,
    WorkDeletionCancelToken,
    WorkDeletionPlan,
    WorkDeletionPreviewService,
)

_PROGRESS_LABELS = {
    "starting": "開始",
    "watchlist": "Watchlist照合",
    "management": "管理ジョブ照合",
    "catalog": "Catalog照合",
    "library_index": "library ZIP索引（候補数）",
    "status_index": "status JSON索引（候補数）",
    "status_read": "status JSON読取",
    "filesystem_index": "library/status索引",
    "artifacts": "ZIP/status確認（ファイル数）",
    "complete": "完了",
}


def _blocker_messages(blockers: tuple[str, ...]) -> str:
    """Explain write-conflict blockers without repeating historical log IDs."""

    counts: dict[str, int] = {}
    other: list[str] = []
    for reason in blockers:
        if reason.startswith("active_job:"):
            state = reason.rsplit(":", 1)[-1]
            counts[state] = counts.get(state, 0) + 1
        elif reason.startswith("management_worker_live:"):
            counts["live"] = counts.get("live", 0) + 1
        elif reason.startswith("management_worker_unverified:"):
            counts["unverified"] = counts.get("unverified", 0) + 1
        elif reason.startswith("management_catalog_unknown:"):
            counts["catalog_unknown"] = counts.get("catalog_unknown", 0) + 1
        else:
            other.append(reason)
    labels = {
        "queued": "待機中のジョブが{count}件あります。ジョブ一覧でキャンセルするか、完了を待ってください。",
        "planning": "準備中のジョブが{count}件あります。終了後に再度プレビューしてください。",
        "running": "実行中のジョブが{count}件あります。終了後に再度プレビューしてください。",
        "live": "中断扱いですがworkerが動いているジョブが{count}件あります。終了を確認してください。",
        "unverified": "workerの終了を確認できないジョブが{count}件あります。ジョブの状態確認が必要です。",
        "catalog_unknown": "対象Catalogを確認できない未完了ジョブが{count}件あります。",
    }
    messages = [labels.get(key, "未完了ジョブが{count}件あります。").format(count=count) for key, count in counts.items()]
    return "\n".join([*messages, *other]) or "なし"


class _DeletionSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    progress = Signal(str, int, int, float)


class WorkDeletionWorker(QRunnable):
    """Run preview/apply outside the Qt GUI thread using fixed absolute paths."""

    def __init__(
        self,
        service: WorkDeletionPreviewService,
        work_key: str,
        *,
        catalog_path: Path,
        watchlist_path: Path,
        library_root: Path,
        status_root: Path,
        trash_root: Path,
        management_paths: tuple[Path, ...],
        plan: WorkDeletionPlan | None = None,
        apply: bool = False,
        cancel_token: WorkDeletionCancelToken | None = None,
    ) -> None:
        super().__init__()
        self.service = service
        self.work_key = work_key
        self.catalog_path = catalog_path.resolve(strict=False)
        self.watchlist_path = watchlist_path.resolve(strict=False)
        self.library_root = library_root.resolve(strict=False)
        self.status_root = status_root.resolve(strict=False)
        self.trash_root = trash_root.resolve(strict=False)
        self.management_paths = tuple(path.resolve(strict=False) for path in management_paths)
        self.plan = plan
        self.apply_mode = apply
        self.cancel_token = cancel_token if cancel_token is not None else WorkDeletionCancelToken()
        self.signals = _DeletionSignals()
        self._last_progress_emit = 0.0
        self._last_progress_key: tuple[str, int, int] | None = None

    def cancel_preview(self) -> None:
        if not self.apply_mode:
            self.cancel_token.cancel()

    def _progress(self, stage: str, completed: int, total: int, elapsed: float) -> None:
        now = time.monotonic()
        key = (stage, completed, total)
        if key == self._last_progress_key:
            return
        same_stage = self._last_progress_key is not None and stage == self._last_progress_key[0]
        if same_stage and completed != total and now - self._last_progress_emit < 0.1:
            return
        self._last_progress_emit = now
        self._last_progress_key = key
        self.signals.progress.emit(stage, completed, total, elapsed)

    @Slot()
    def run(self) -> None:
        try:
            if self.apply_mode:
                if self.plan is None:
                    raise WorkDeletionApplyError("deletion preview is missing")
                result = self.service.apply(self.plan)
            else:
                result = self.service.preview(
                    self.work_key,
                    catalog_path=self.catalog_path,
                    watchlist_path=self.watchlist_path,
                    management_paths=self.management_paths,
                    library_root=self.library_root,
                    status_root=self.status_root,
                    trash_root=self.trash_root,
                    progress=self._progress,
                    cancel=self.cancel_token,
                )
                if self.cancel_token.is_cancelled():
                    self.signals.cancelled.emit()
                    return
        except WorkDeletionCancelled:
            self.signals.cancelled.emit()
        except Exception as exc:  # noqa: BLE001 - GUI worker boundary
            self.signals.failed.emit(str(exc) or type(exc).__name__)
        else:
            self.signals.succeeded.emit(result)


class WorkDeletionDialog(QDialog):
    """Two-step preview/confirmation dialog; destructive work stays in a worker."""

    completed = Signal(object)

    def __init__(
        self,
        work_key: str,
        *,
        catalog_path: str | Path,
        watchlist_path: str | Path,
        management_paths: tuple[str | Path, ...] = (),
        library_root: str | Path = "output/Books",
        status_root: str | Path = "output/crawl-status",
        trash_root: str | Path = "output/trash/work-deletion",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.work_key = work_key
        self.catalog_path = Path(catalog_path).resolve(strict=False)
        self.watchlist_path = Path(watchlist_path).resolve(strict=False)
        self.library_root = Path(library_root).resolve(strict=False)
        self.status_root = Path(status_root).resolve(strict=False)
        self.trash_root = Path(trash_root).resolve(strict=False)
        self.management_paths = tuple(Path(path).resolve(strict=False) for path in management_paths)
        self.service = WorkDeletionPreviewService()
        self.plan: WorkDeletionPlan | None = None
        self.worker: WorkDeletionWorker | None = None
        self.thread_pool = QThreadPool(self)
        self._closing_while_busy = False
        self._preview_started = 0.0
        self._last_preview_progress = ("starting", 0, 1)
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(250)
        self._elapsed_timer.timeout.connect(self._refresh_preview_progress)
        self.setWindowTitle(f"作品を削除: {work_key}")
        self.resize(720, 520)
        layout = QVBoxLayout(self)
        self.summary = QPlainTextEdit(self)
        self.summary.setReadOnly(True)
        layout.addWidget(self.summary, 1)
        self.confirm = QCheckBox("上記の作品を退避して完全削除することを確認しました", self)
        self.confirm.setEnabled(False)
        self.confirm.toggled.connect(self._update_buttons)
        layout.addWidget(self.confirm)
        self.status = QLabel("プレビュー中…", self)
        layout.addWidget(self.status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, self)
        self.apply_button = self.buttons.addButton("削除を実行", QDialogButtonBox.ButtonRole.AcceptRole)
        self.apply_button.setEnabled(False)
        self.buttons.rejected.connect(self._cancel_or_close)
        self.apply_button.clicked.connect(self.apply_plan)
        layout.addWidget(self.buttons)
        self.preview()

    @property
    def busy(self) -> bool:
        return self.worker is not None

    def _update_buttons(self) -> None:
        self.apply_button.setEnabled(self.plan is not None and self.plan.ready and self.confirm.isChecked() and not self.busy)

    def preview(self) -> None:
        if self.busy:
            return
        self.plan = None
        self.confirm.setChecked(False)
        self.confirm.setEnabled(False)
        self._start_worker(apply=False)

    def _start_worker(self, *, apply: bool) -> None:
        worker = WorkDeletionWorker(
            self.service,
            self.work_key,
            catalog_path=self.catalog_path,
            watchlist_path=self.watchlist_path,
            library_root=self.library_root,
            status_root=self.status_root,
            trash_root=self.trash_root,
            management_paths=self.management_paths,
            plan=self.plan,
            apply=apply,
        )
        self.worker = worker
        self._elapsed_timer.stop()
        if not apply:
            self._preview_started = time.monotonic()
            self._last_preview_progress = ("starting", 0, 1)
            self._elapsed_timer.start()
        worker.signals.succeeded.connect(self._worker_succeeded, Qt.ConnectionType.QueuedConnection)
        worker.signals.failed.connect(self._worker_failed, Qt.ConnectionType.QueuedConnection)
        worker.signals.cancelled.connect(self._worker_cancelled, Qt.ConnectionType.QueuedConnection)
        worker.signals.progress.connect(
            lambda stage, completed, total, elapsed, current=worker: self._worker_progress(
                current, stage, completed, total, elapsed
            ),
            Qt.ConnectionType.QueuedConnection,
        )
        self.thread_pool.start(worker)

    def _worker_progress(self, worker: WorkDeletionWorker, stage: str, completed: int, total: int, elapsed: float) -> None:
        if self.worker is not worker:
            return
        if worker.apply_mode:
            self.status.setText("削除実行中…閉じてもmanifestで復旧できます")
        else:
            self._last_preview_progress = (stage, completed, total)
            self._refresh_preview_progress()

    @Slot()
    def _refresh_preview_progress(self) -> None:
        if self.worker is None or self.worker.apply_mode or self.worker.cancel_token.is_cancelled():
            return
        stage, completed, total = self._last_preview_progress
        label = _PROGRESS_LABELS.get(stage, stage)
        count = f"{completed}件" if total == 0 else f"{completed}/{total}件"
        elapsed = max(0.0, time.monotonic() - self._preview_started)
        self.status.setText(f"プレビュー中… {label} {count}（経過 {elapsed:.1f}秒）")

    @Slot(object)
    def _worker_succeeded(self, result: object) -> None:
        self._elapsed_timer.stop()
        if self.worker is not None and not self.worker.apply_mode and self.worker.cancel_token.is_cancelled():
            self._worker_cancelled()
            return
        self.worker = None
        if isinstance(result, WorkDeletionPlan):
            self.plan = result
            self.confirm.setEnabled(result.ready)
            counts = f"Items {len(result.item_ids)} / Runs {len(result.crawl_run_ids)} / Artifacts {len(result.artifact_ids)} / ZIP {result.zip_count} ({result.byte_size} bytes)"
            site_keys = ", ".join(f"{site}:{external_id}" for site, external_id in result.site_keys) or "(none)"
            roots = "\n".join(f"{label}: {path}" for label, path, _device in result.root_identities)
            blockers = _blocker_messages(result.blockers)
            self.summary.setPlainText(
                f"Work key: {result.work_key}\nTitle: {result.work_title or '(unknown)'}\n"
                f"Site keys: {site_keys}\nWork ID: {result.work_id}\n{counts}\n"
                f"退避先: {self.trash_root}\n{roots}\n停止理由:\n{blockers}"
            )
            self.status.setText("確認後に削除を実行できます" if result.ready else "BLOCKED: 削除できません。停止理由を確認してください（まだ変更なし）")
            self._update_buttons()
            return
        self.status.setText(getattr(result, "status", "完了"))
        self.completed.emit(result)
        self.accept()

    @Slot(str)
    def _worker_failed(self, message: str) -> None:
        self._elapsed_timer.stop()
        self.worker = None
        self.status.setText("RECOVERY_REQUIRED / BLOCKED: " + message)
        self._update_buttons()
        if self._closing_while_busy:
            self._closing_while_busy = False
            super().reject()

    @Slot()
    def _worker_cancelled(self) -> None:
        self._elapsed_timer.stop()
        self.worker = None
        self.plan = None
        self.confirm.setChecked(False)
        self.confirm.setEnabled(False)
        self.status.setText("プレビューをキャンセルしました（変更なし）")
        self._update_buttons()
        if self._closing_while_busy:
            self._closing_while_busy = False
            super().reject()

    def _cancel_or_close(self) -> None:
        if self.busy:
            if self.worker is not None and self.worker.apply_mode:
                self._closing_while_busy = False
                self.status.setText("削除実行中は閉じられません。manifestで復旧できます")
            elif self.worker is not None:
                self.worker.cancel_preview()
                self.status.setText("プレビューをキャンセル中…")
            return
        self.reject()

    def reject(self) -> None:
        """Route Esc/reject through the same cooperative preview policy."""

        if self.busy:
            self._closing_while_busy = True
            self._cancel_or_close()
            return
        super().reject()

    def apply_plan(self) -> None:
        if self.busy or self.plan is None or not self.plan.ready or not self.confirm.isChecked():
            return
        self.apply_button.setEnabled(False)
        self.confirm.setEnabled(False)
        self.status.setText("削除実行中…閉じてもmanifestで復旧できます")
        self._start_worker(apply=True)

    def closeEvent(self, event) -> None:
        if self.busy:
            if self.worker is not None and self.worker.apply_mode:
                self._closing_while_busy = False
                self.status.setText("削除実行中は閉じられません。manifestで復旧できます")
            elif self.worker is not None:
                self._closing_while_busy = True
                self.worker.cancel_preview()
                self.status.setText("プレビューをキャンセル中…")
            event.ignore()
            return
        super().closeEvent(event)
