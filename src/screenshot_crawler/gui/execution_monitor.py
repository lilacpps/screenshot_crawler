"""Small, read-only execution monitor embedded below the main inventory UI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFontMetrics, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from screenshot_crawler.management.log_tail import LogTailReader
from screenshot_crawler.management.result_presenter import JobResult, JobResultPresenter


class ExecutionMonitor(QWidget):
    """Display bounded raw logs and observed state for one management job.

    The monitor is intentionally a passive view.  It never starts, stops, or
    reconciles workers; the existing MainWindow supervisor remains the only
    owner of those operations.
    """

    def __init__(self, store: Any = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("execution_monitor")
        self.store = store
        self._presenter = JobResultPresenter(store) if store is not None else None
        self.job_id: str | None = None
        self._reader: LogTailReader | None = None
        self._manual_job_selection = False
        self._stream = "stdout"
        self._stream_buffers: dict[tuple[str, str], str] = {}
        self._collapsed = False
        self._expanded_splitter_sizes: tuple[int, int] | None = None
        self.max_blocks = 2_000
        self.max_chars = 250_000

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 0, 4, 0)
        header = QHBoxLayout()
        self.title_label = QLabel("Execution monitor")
        self.title_label.setObjectName("execution_monitor_title")
        header.addWidget(self.title_label)
        self.job_combo = QComboBox()
        self.job_combo.setObjectName("execution_monitor_job_combo")
        self.job_combo.currentIndexChanged.connect(self._job_combo_changed)
        header.addWidget(self.job_combo, 2)
        self.action_label = QLabel("action: —")
        self.state_label = QLabel("state: —")
        self.location_label = QLabel("site/key/item: —")
        for label in (self.action_label, self.state_label, self.location_label):
            label.setMinimumWidth(
                110 if label is self.action_label else
                180 if label is self.state_label else 160
            )
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.action_label.setMaximumWidth(180)
        self.state_label.setMaximumWidth(180)
        self.action_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.state_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.location_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.job_combo.setMinimumWidth(120)
        header.addWidget(self.action_label)
        header.addWidget(self.state_label)
        header.addWidget(self.location_label, 2)
        self.toggle_button = QPushButton("Collapse")
        self.toggle_button.setObjectName("execution_monitor_toggle")
        self.toggle_button.setToolTip("Collapse or expand the execution monitor")
        self.toggle_button.clicked.connect(lambda: self.set_collapsed(not self._collapsed))
        header.addWidget(self.toggle_button)
        root.addLayout(header)

        self.progress_label = QLabel("progress: —")
        self.progress_label.setObjectName("execution_monitor_progress")
        root.addWidget(self.progress_label)

        self.stream_combo = QComboBox()
        self.stream_combo.setObjectName("execution_monitor_stream_combo")
        self.stream_combo.addItem("stdout", "stdout")
        self.stream_combo.addItem("stderr", "stderr")
        self.stream_combo.currentIndexChanged.connect(self._stream_changed)
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("execution_monitor_log")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(self.max_blocks)
        self.log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.summary_view = QPlainTextEdit()
        self.summary_view.setObjectName("execution_monitor_summary")
        self.summary_view.setReadOnly(True)
        self.summary_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.problem_view = QPlainTextEdit()
        self.problem_view.setObjectName("execution_monitor_problems")
        self.problem_view.setReadOnly(True)
        self.problem_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        panes = QSplitter()
        panes.setOrientation(Qt.Orientation.Horizontal)
        log_pane = QWidget()
        log_layout = QVBoxLayout(log_pane)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_controls = QHBoxLayout()
        log_controls.addWidget(self.stream_combo)
        self.open_button = QPushButton("Open log")
        self.open_button.setObjectName("execution_monitor_open_log")
        self.open_button.clicked.connect(self.open_current_log)
        log_controls.addWidget(self.open_button)
        self.copy_button = QPushButton("Copy")
        self.copy_button.setObjectName("execution_monitor_copy_log")
        self.copy_button.clicked.connect(self.copy_current_log)
        log_controls.addWidget(self.copy_button)
        log_controls.addStretch(1)
        log_layout.addLayout(log_controls)
        self.log_metadata = QLabel("")
        self.log_metadata.setObjectName("execution_monitor_log_metadata")
        self.log_metadata.setWordWrap(False)
        self.log_metadata.setToolTip(
            "stdout and stderr are separate streams; chronological order across streams is unavailable"
        )
        log_layout.addWidget(self.log_metadata)
        log_layout.addWidget(self.log_view)
        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(2, 0, 0, 0)
        side_layout.addWidget(self.summary_view)
        side_layout.addWidget(self.problem_view)
        side_layout.addStretch(1)
        panes.addWidget(log_pane)
        panes.addWidget(side)
        panes.setStretchFactor(0, 3)
        panes.setStretchFactor(1, 1)
        root.addWidget(panes, 1)
        self._monitor_content = (self.progress_label, panes)
        self._last_summary_text = ""
        self._last_problem_text = ""

    def set_collapsed(self, collapsed: bool) -> None:
        """Keep the monitor heading while hiding or restoring its detail pane."""

        collapsed = bool(collapsed)
        state_changed = collapsed != self._collapsed
        self._collapsed = collapsed
        self.setMinimumHeight(26)
        for widget in self._monitor_content:
            widget.setVisible(not self._collapsed)
        self.toggle_button.setText("Expand" if self._collapsed else "Collapse")
        if self._collapsed:
            self.setMaximumHeight(max(26, self.layout().sizeHint().height()))
        else:
            self.setMaximumHeight(16777215)
        splitter = self.parentWidget()
        if state_changed and isinstance(splitter, QSplitter):
            index = splitter.indexOf(self)
            if index >= 0:
                if self._collapsed:
                    sizes = splitter.sizes()
                    if len(sizes) == 2 and sizes[1] > 26:
                        self._expanded_splitter_sizes = (sizes[0], sizes[1])
                    splitter.setSizes([max(0, splitter.height() - self.sizeHint().height()), self.sizeHint().height()])
                else:
                    if self._expanded_splitter_sizes is not None:
                        splitter.setSizes(list(self._expanded_splitter_sizes))
                    else:
                        available = max(0, splitter.height())
                        monitor_size = min(230, available)
                        splitter.setSizes([max(0, available - monitor_size), monitor_size])
        if not self._collapsed:
            self._update_log_metadata()
            self.refresh(read_log=True)

    def set_store(self, store: Any) -> None:
        self.store = store
        self._presenter = JobResultPresenter(store) if store is not None else None
        self._job_combo_signature = None
        self.refresh_jobs()

    def set_job(self, job_id: str | None, *, manual: bool = False) -> None:
        if manual:
            self._manual_job_selection = True
        if job_id == self.job_id and self._reader is not None:
            self._update_combo_selection()
            self.refresh()
            return
        if job_id != self.job_id:
            # A job switch starts a fresh reader/view/cache boundary. Keeping
            # prior jobs here would replay stale text on A->B->A and retain
            # memory for every job in the session.
            self._stream_buffers.clear()
            if self._presenter is not None:
                self._presenter.reset(job_id)
        self.job_id = job_id
        self._reader = (
            LogTailReader(self.store, job_id)
            if self.store is not None and job_id and hasattr(self.store, "job_dir")
            else None
        )
        self.log_view.setPlainText(
            self._stream_buffers.get((job_id, self._stream), "") if job_id else ""
        )
        self._update_combo_selection()
        self.refresh()

    def follow_job(self, job_id: str | None) -> None:
        if job_id is not None and not self._manual_job_selection:
            if job_id != self.job_id:
                self.set_collapsed(False)
            self.set_job(job_id)

    def clear_manual_selection(self) -> None:
        self._manual_job_selection = False

    def _update_combo_selection(self) -> None:
        self.job_combo.blockSignals(True)
        for index in range(self.job_combo.count()):
            if self.job_combo.itemData(index) == self.job_id:
                self.job_combo.setCurrentIndex(index)
                break
        self.job_combo.blockSignals(False)

    def refresh_jobs(self) -> None:
        if self.store is None:
            self.job_combo.clear()
            return
        try:
            rows = self.store.list_jobs(limit=100)
        except Exception as exc:  # noqa: BLE001 - monitor must never block supervisor
            self.title_label.setText(f"Execution monitor unavailable: {exc}")
            return
        current = self.job_id
        signature = tuple((row["job_id"], row["state"], row["action"]) for row in rows)
        if signature == getattr(self, "_job_combo_signature", None):
            if current is not None:
                self._update_combo_selection()
            return
        scroll = self.job_combo.view().verticalScrollBar().value()
        self.job_combo.blockSignals(True)
        self.job_combo.clear()
        for row in rows:
            self.job_combo.addItem(
                f"{row['state']} / {row['action']} / {str(row['job_id'])[:8]}",
                row["job_id"],
            )
        self.job_combo.blockSignals(False)
        self._job_combo_signature = signature
        if current is not None:
            self._update_combo_selection()
        elif rows and not self._manual_job_selection:
            self.set_job(rows[0]["job_id"])
        self.job_combo.view().verticalScrollBar().setValue(scroll)

    def _job_combo_changed(self, index: int) -> None:
        job_id = self.job_combo.itemData(index)
        if job_id:
            self.set_job(str(job_id), manual=True)

    def _stream_changed(self, _index: int) -> None:
        self._stream = str(self.stream_combo.currentData() or "stdout")
        self.log_view.setPlainText(
            self._stream_buffers.get((self.job_id, self._stream), "")
            if self.job_id else ""
        )
        self.refresh(read_log=True)

    def _update_log_metadata(self) -> None:
        base = "stdout/stderr are separate; cross-stream order unavailable"
        if self._reader is None:
            self.log_metadata.setText(base)
            return
        metadata = self._reader.metadata(self._stream)
        notes: list[str] = []
        if metadata["tail_omitted"] or metadata["history_omitted"]:
            notes.append("initial history omitted; bounded tail shown")
        if not metadata["file_present"]:
            notes.append("log file not present")
        self.log_metadata.setText("; ".join([base, *notes]))

    def _append_log(self, text: str) -> None:
        if not text:
            return
        bar = self.log_view.verticalScrollBar()
        follow = bar.value() >= bar.maximum() - 2
        old_value = bar.value()
        document = self.log_view.document()
        document.setMaximumBlockCount(0)
        cursor = QTextCursor(document)
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        if self.job_id is not None:
            key = (self.job_id, self._stream)
            buffered = self._stream_buffers.get(key, "") + text
            self._stream_buffers[key] = buffered[-self.max_chars:]
        before_char_trim_blocks = document.blockCount()
        if document.characterCount() > self.max_chars:
            cursor = QTextCursor(document)
            cursor.movePosition(cursor.MoveOperation.Start)
            cursor.movePosition(
                cursor.MoveOperation.Right,
                cursor.MoveMode.KeepAnchor,
                document.characterCount() - self.max_chars,
            )
            cursor.removeSelectedText()
        char_trimmed_blocks = max(0, before_char_trim_blocks - document.blockCount())
        before_trim_blocks = document.blockCount()
        document.setMaximumBlockCount(self.max_blocks)
        trimmed = char_trimmed_blocks + max(0, before_trim_blocks - document.blockCount())
        if follow:
            bar.setValue(bar.maximum())
        else:
            # QPlainTextEdit's vertical scrollbar advances in document-block
            # units; subtracting pixels breaks the viewport anchor on Qt/Windows.
            bar.setValue(max(0, old_value - trimmed))

    def _set_elided_label(self, label: QLabel, value: str) -> None:
        label.setToolTip(value)
        if label in (self.action_label, self.state_label) and len(value) <= 24:
            # Keep the common action/state values semantically searchable and
            # visible; QLabel clips at its own bounded rectangle.
            label.setText(value)
            return
        available = label.width()
        if available <= 0 and label.maximumWidth() < 1_000_000:
            available = label.maximumWidth()
        # Elide to the actual bounded label width.  A larger synthetic width
        # lets long event values paint over the adjacent state/location label.
        width = max(1, available)
        text = QFontMetrics(label.font()).elidedText(
            value, Qt.TextElideMode.ElideMiddle, width
        )
        label.setText(text)

    def _set_location(self, value: str) -> None:
        self._set_elided_label(self.location_label, value)

    def refresh(self, *, read_log: bool = True) -> None:
        if (
            not self.isVisible()
            or self.store is None
            or self.job_id is None
            or self._presenter is None
        ):
            return
        try:
            result = self._presenter.present(self.job_id)
        except Exception as exc:  # noqa: BLE001 - DB health must not stop polling
            self.title_label.setText(f"Execution monitor unavailable: {exc}")
            return
        self.title_label.setText("Execution monitor")
        self._set_elided_label(self.action_label, f"action: {result.action}")
        self._set_elided_label(self.state_label, f"state: {result.state}")
        context = result.current
        self._set_location(
            f"site/key/item: {context.site or '—'} / {context.key or '—'} / "
            f"{context.item_id if context.item_id is not None else '—'}"
        )
        attempts = sum(task.observed_attempts for task in result.tasks)
        success = sum(task.success_count for task in result.tasks)
        failed = sum(task.failed_count for task in result.tasks)
        skipped = sum(task.skipped_count for task in result.tasks)
        unknown = sum(task.unknown_count for task in result.tasks)
        self.progress_label.setText(
            f"progress: attempts={attempts} success={success} failed={failed} "
            f"skipped={skipped} unknown={unknown}"
        )
        summary_text = _summary_text(result)
        bounded_summary = _bounded_text(summary_text, 50_000)
        if bounded_summary != self._last_summary_text:
            self._last_summary_text = _set_bounded_text(self.summary_view, bounded_summary, 50_000)
        problem_text = _problem_text(result)
        bounded_problem = _bounded_text(problem_text, 50_000)
        if bounded_problem != self._last_problem_text:
            self._last_problem_text = _set_bounded_text(self.problem_view, bounded_problem, 50_000)
        if read_log and self._reader is not None and not self._collapsed:
            self._append_log(self._reader.read(self._stream))
        self._update_log_metadata()
    def _current_log_path(self) -> Path | None:
        if self._reader is None:
            return None
        return self._reader.job_dir / f"{self._stream}.log"

    def open_current_log(self) -> None:
        path = self._current_log_path()
        if path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def copy_current_log(self) -> None:
        QApplication.clipboard().setText(self.log_view.toPlainText())


def _summary_text(result: JobResult) -> str:
    elapsed = "unknown" if result.elapsed is None else f"{result.elapsed:.1f}s"
    lines = [
        f"action={result.action} mode={result.mode or 'unknown'} state={result.state}",
        f"elapsed={elapsed} events_cursor={result.event_cursor}",
        f"grant_facts_omitted={result.grant_facts_omitted}",
    ]
    for task in result.tasks:
        lines.append(
            f"task {task.site}: state={task.state} observed_attempts={task.observed_attempts} "
            f"success={task.success_count} failed={task.failed_count} "
            f"skipped={task.skipped_count} unknown={task.unknown_count}"
        )
    for item in result.discover:
        counts = f"observed={item.observed} new={item.new} known={item.known}"
        lines.append(
            f"discover {item.site}/{item.key}: {item.status} {counts} "
            f"complete={item.complete if item.complete is not None else 'unknown'} "
            f"reason={item.stopped_reason or 'none'} warnings={'; '.join(item.warnings) or 'none'} "
            f"error={item.error or 'none'}"
        )
    for batch in result.batches:
        lines.append(
            f"batch {batch.site}: {batch.status} metrics={batch.metrics_status} "
            f"metrics_path={batch.metrics_path or 'unknown'} "
            f"planned_skip={batch.planned_skips if batch.planned_skips is not None else 'unknown'} "
            f"execution_skip={batch.execution_skips if batch.execution_skips is not None else 'unknown'} "
            f"candidates_skipped={batch.candidates_skipped if batch.candidates_skipped is not None else 'unknown'} "
            f"started={batch.candidates_started if batch.candidates_started is not None else 'unknown'} "
            f"completed={batch.candidates_completed if batch.candidates_completed is not None else 'unknown'} "
            f"failed={batch.candidates_failed if batch.candidates_failed is not None else 'unknown'} "
            f"elapsed={batch.elapsed if batch.elapsed is not None else 'unknown'} "
            f"http={batch.http_requests if batch.http_requests is not None else 'unknown'} "
            f"retry={batch.retries if batch.retries is not None else 'unknown'} "
            f"challenge={batch.challenges if batch.challenges is not None else 'unknown'} "
            f"stop_reason={batch.stop_reason or 'none'} "
            f"metrics_omitted={batch.metrics_omitted}"
        )
    for grant in result.grants:
        lines.append(
            f"grant site={grant.site or 'unknown'} work_id={grant.work_id if grant.work_id is not None else 'unknown'} "
            f"label={grant.label or 'unknown'} item_id={grant.item_id if grant.item_id is not None else 'unknown'} "
            f"source_id={grant.source_id if grant.source_id is not None else 'unknown'} "
            f"resource={grant.resource or 'unknown'} status={grant.status} "
            f"consumed={grant.resource_consumed if grant.resource_consumed is not None else 'unknown'} "
            f"outcome={grant.outcome} reason={grant.reason or 'none'}"
        )
    return "\n".join(lines)


def _problem_text(result: JobResult) -> str:
    if not result.problems:
        return "Structured problems: none observed; raw diagnostics remain in stdout/stderr."
    lines = ["Structured problems:"]
    for problem in result.problems:
        context = problem.context
        where = "/".join(
            value for value in (
                context.site,
                context.key,
                str(context.item_id) if context.item_id is not None else None,
                str(context.source_id) if context.source_id is not None else None,
                context.resource,
            ) if value
        )
        lines.append(f"{problem.severity} {problem.event_type}: {problem.reason} ({where or 'context unknown'})")
    return "\n".join(lines)


def _set_bounded_text(view: QPlainTextEdit, text: str, limit: int) -> str:
    bounded = _bounded_text(text, limit)
    bar = view.verticalScrollBar()
    was_bottom = bar.value() >= bar.maximum() - 1
    old_value = bar.value()
    view.setPlainText(bounded)
    if was_bottom:
        bar.setValue(bar.maximum())
    else:
        bar.setValue(min(old_value, bar.maximum()))
    return bounded


def _bounded_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n[display truncated; {len(text) - limit} characters omitted]"


__all__ = ["ExecutionMonitor"]
