"""Explicit history-only ZIP separation; projected previews can never apply."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QThreadPool, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidgetItem,
    QVBoxLayout,
)

from screenshot_crawler.maintenance.hanayume_history import apply_history_plan, build_history_plan

from .catalog_repair import _table, _Task

STATUSES = {"move": "履歴先へ移動", "keep_current": "現役として維持", "keep_shared": "共有参照のため維持",
            "already_history": "分離済み", "blocked": "適用不可"}


class RepairHistoryDialog(QDialog):
    catalogChanged = Signal()

    def __init__(self, catalog, work_key, *, migration=None, parent=None,
                 library_root="output/Books", history_root="output/Books-history"):
        super().__init__(parent)
        self.catalog, self.work_key, self.migration = Path(catalog), work_key, migration
        self.plan = self.task = None
        self.setWindowTitle("花とゆめ＋ 履歴専用ZIPの分離 — Stage 03A")
        self.resize(1450, 900)
        layout = QVBoxLayout(self)
        note = QLabel("旧SourceはDBに取得担当OFFの履歴として残ります。現役として再利用するZIPは維持し、"
                      "履歴専用のZIPだけを別フォルダへ移動します。Artifactの保存先参照を更新し、"
                      "ZIPの内容・名前・取得履歴・チケット状態を維持します。採番・不要ZIP削除は行いません。")
        note.setWordWrap(True)
        layout.addWidget(note)
        paths = QHBoxLayout()
        paths.addWidget(QLabel("現役library"))
        self.library_root = QLineEdit(str(library_root))
        paths.addWidget(self.library_root)
        paths.addWidget(QLabel("履歴先"))
        self.history_root = QLineEdit(str(history_root))
        paths.addWidget(self.history_root)
        layout.addLayout(paths)
        self.library_root.textChanged.connect(self.invalidate)
        self.history_root.textChanged.connect(self.invalidate)
        controls = QHBoxLayout()
        self.preview_button = QPushButton("分離プレビューを作成")
        self.preview_button.clicked.connect(self.preview)
        self.actual_button = QPushButton("移行後の実Catalogから再検証")
        self.actual_button.clicked.connect(self.actual)
        self.save_button = QPushButton("プレビューを新規JSONへ保存")
        self.save_button.clicked.connect(self.save)
        for widget in (self.preview_button, self.actual_button, self.save_button):
            controls.addWidget(widget)
        layout.addLayout(controls)
        self.summary = QLabel("解析中…")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.table = _table(("予定", "話数", "Artifact ID", "Item ID", "現在のZIP", "履歴先ZIP", "理由"))
        for i, width in enumerate((135, 120, 110, 100, 430, 430, 380)):
            self.table.setColumnWidth(i, width)
        self.table.itemSelectionChanged.connect(self.details_changed)
        layout.addWidget(self.table, 3)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        layout.addWidget(self.details, 2)
        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("backup/manifest先"))
        self.backup_dir = QLineEdit("output/hanayume-history-backups")
        bottom.addWidget(self.backup_dir)
        self.apply_button = QPushButton("バックアップして履歴ZIPを分離")
        self.apply_button.clicked.connect(self.apply)
        bottom.addWidget(self.apply_button)
        layout.addLayout(bottom)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.preview()

    def set_busy(self, busy):
        for widget in (self.library_root, self.history_root, self.preview_button, self.actual_button, self.backup_dir):
            widget.setEnabled(not busy)
        self.save_button.setEnabled(not busy and self.plan is not None)
        self.apply_button.setEnabled(not busy and self.plan is not None and self.plan.ready and bool(self.plan.moves))

    def invalidate(self, *args):
        self.plan = None
        self.table.setRowCount(0)
        self.details.clear()
        self.summary.setText("再プレビュー待ち")
        self.set_busy(self.task is not None)

    def start(self, action, done):
        if self.task is not None:
            return
        self.task = _Task(lambda progress: action())
        self.task.signals.success.connect(lambda value: self.finished(value, done))
        self.task.signals.failure.connect(self.failed)
        self.set_busy(True)
        QThreadPool.globalInstance().start(self.task)

    def finished(self, value, done):
        self.task = None
        try:
            done(value)
        except Exception as exc:  # noqa: BLE001 - GUI boundary
            self.failed(str(exc))
        self.set_busy(False)

    def failed(self, message):
        self.task = None
        self.invalidate()
        self.status.setText(f"処理を停止しました（自動再試行なし）: {message}")

    def preview(self):
        self.invalidate()
        library, history, migration = self.library_root.text(), self.history_root.text(), self.migration
        self.status.setText("全Artifact参照とZIPの存在・サイズ・SHA-256を読み取り専用で検証しています…")
        self.start(lambda: build_history_plan(self.catalog, self.work_key, library_root=library,
                                              history_root=history, migration=migration), self.previewed)

    def actual(self):
        self.migration = None
        self.preview()

    def previewed(self, plan):
        self.plan = plan
        self.table.setRowCount(len(plan.entries))
        for row, e in enumerate(plan.entries):
            values = (STATUSES[e.status], e.title, ", ".join(map(str, e.artifact_ids)),
                      ", ".join(map(str, e.item_ids)), e.old_path, e.new_path or "移動なし", e.reason)
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.table.setItem(row, column, item)
        self.summary.setText(self.work_key + " | " + " / ".join(f"{STATUSES[s]} {n}件" for s, n in plan.to_dict()["summary"].items()))
        self.status.setText("Stage 02移行後の投影予定です。この状態では適用できません。移行後に実Catalogから再検証してください。"
            if plan.projected_migration_token else "適用不可: " + " / ".join(plan.blockers) if plan.blockers
            else "移動先を確認して明示適用してください。既存の移動先を上書きしません。")
        selected = next((i for i, e in enumerate(plan.entries) if e.status == "move"), None)
        if selected is not None:
            self.table.selectRow(selected)
        self.details_changed()

    def details_changed(self):
        if self.plan is None:
            return
        rows = [i.row() for i in self.table.selectionModel().selectedRows()]
        entries = [self.plan.entries[i] for i in rows]
        self.details.setPlainText("\n\n".join(f"{e.title}: {STATUSES[e.status]}\n{e.reason}\n"
            f"Artifact ID: {', '.join(map(str, e.artifact_ids))}\nItem ID: {', '.join(map(str, e.item_ids))}\n"
            f"現在: {e.old_path}\n移動先: {e.new_path or '移動なし'}\n"
            f"SHA-256: {e.sha256}\nbytes: {e.size}\n"
            "Item/Source/Run/チケット履歴は維持。移動する全Artifactのlocatorだけを新pathへ更新します。"
            for e in entries) or "行を選択すると現在と移動先のpath・DB参照を確認できます。")

    def save(self):
        if self.plan is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "履歴分離プレビューを新規保存", "hanayume-history-preview.json", "JSON (*.json)")
        if path:
            payload = self.plan.to_dict()
            def save():
                with Path(path).open("x", encoding="utf-8") as stream:
                    json.dump(payload, stream, ensure_ascii=False, indent=2)
            self.start(save, lambda _: self.status.setText(f"保存しました: {path}"))

    def apply(self):
        if self.plan is None or not self.plan.ready or not self.plan.moves or self.task is not None:
            return
        plan, backup_dir = self.plan, self.backup_dir.text()
        if not backup_dir.strip():
            self.status.setText("backup先を指定してください")
            return
        if QMessageBox.question(self, "履歴専用ZIPの分離を適用", f"作品: {plan.work_key}\n"
                f"ZIP {len(plan.moves)}件を {plan.history_root} へ移動します。\n"
                "Catalog backupと復旧manifestを作り、全Artifact参照を更新します。\n"
                "同一filesystemでhardlink可能な保存先に限ります。Stage 02のCatalog移行とは別操作です。適用しますか？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self.start(lambda: apply_history_plan(plan, expected_token=plan.token, backup_dir=backup_dir), self.applied)

    def applied(self, result):
        self.invalidate()
        self.status.setText("分離済み（再実行no-op）" if result.already_applied else
                            f"履歴ZIP {result.moved}件を分離しました。backup: {result.backup} / manifest: {result.manifest}")
        self.catalogChanged.emit()

    def reject(self):
        if self.task is None:
            super().reject()

    def closeEvent(self, event):
        event.ignore() if self.task is not None else event.accept()
