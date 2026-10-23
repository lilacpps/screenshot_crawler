"""Small, testable confirmation dialog for P2 execution requests."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QTextEdit, QVBoxLayout

from screenshot_crawler.management.execution import ExecutionPlanPreview, JobExecutionRequest


class ExecutionPreviewDialog(QDialog):
    """Display the read-only preview and require an explicit confirmation."""

    requestConfirmed = Signal(object)

    def __init__(self, preview: ExecutionPlanPreview, request: JobExecutionRequest | None = None, parent=None):
        super().__init__(parent)
        self.preview = preview
        self.request = request
        self.setWindowTitle("実行前確認")
        self.setModal(True)
        layout = QVBoxLayout(self)
        title = QLabel(self)
        title.setText({
            "discover": "Discover 実行前確認",
            "batch": "Batch Run 実行前確認",
            "grant_only": "Grant-only 実行前確認",
        }[preview.action])
        layout.addWidget(title)
        details = QTextEdit(self)
        details.setReadOnly(True)
        lines = [
            f"対象サイト: {', '.join(preview.sites) or '—'}",
            f"対象作品: {', '.join(preview.work_names) or '—'}",
            f"対象key: {', '.join(sorted(preview.selection.selected_keys)) or 'なし'}",
            f"候補数: {preview.candidate_count}",
            f"スキップ: {preview.skipped_count}",
            f"実行モード: {preview.mode or ('Grant-only' if preview.action == 'grant_only' else 'Batch')}",
            f"最大試行数: {preview.limit if preview.action == 'grant_only' and preview.limit is not None else '無制限' if preview.action == 'grant_only' else '—'}",
            f"最大取得数: {preview.limit if preview.action == 'batch' and preview.limit is not None else '無制限' if preview.action == 'batch' else '—'}",
            f"Resource: {preview.resource or 'per-site selection' if preview.resources_by_site else '—'}",
            f"Plan fingerprint: {preview.fingerprint[:16]}",
        ]
        if preview.resources_by_site:
            lines.append(
                "Site Resource: "
                + ", ".join(
                    f"{site}={resource}" for site, resource in preview.resources_by_site
                )
            )
        if preview.action == "grant_only":
            lines.append("注意: Grant-only は権利・チケット・Quotaを消費する可能性があります。")
        if preview.skipped:
            lines.append("スキップ理由:")
            lines.extend(f"  {key}: {reason}" for key, reason in preview.skipped)
        if preview.blockers:
            lines.append("停止理由:")
            lines.extend(f"  {value}" for value in preview.blockers)
        if preview.warnings:
            lines.append("警告:")
            lines.extend(f"  {value}" for value in preview.warnings)
        details.setPlainText("\n".join(lines))
        layout.addWidget(details)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, parent=self)
        self.confirm_button = buttons.addButton(
            "実行開始", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.confirm_button.setEnabled(preview.can_confirm and request is not None)
        buttons.accepted.connect(self._confirm)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _confirm(self) -> None:
        if self.request is None or not self.preview.can_confirm:
            return
        self.requestConfirmed.emit(self.request)
        self.accept()


__all__ = ["ExecutionPreviewDialog"]
