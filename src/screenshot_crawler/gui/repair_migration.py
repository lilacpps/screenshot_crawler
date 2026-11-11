"""Explicit Stage 02 report review, preview and backed-up Catalog apply."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import QThreadPool, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
)

from screenshot_crawler.maintenance.hanayume_migration import (
    apply_migration_plan,
    build_migration_plan,
    load_review_report,
    migration_preview_payload,
    report_groups,
)

from .catalog_repair import CatalogRepairDialog, _table, _Task

POLICIES = (("auto", "自動方針"), ("old", "旧取得を利用"), ("new", "新側を利用"),
            ("reacquire", "新側を再取得"), ("hold", "保留"), ("retire", "対応無し・履歴保管"))
ACTIONS = {"reuse_identity": "旧completedを現行IDへ継承・旧ZIP維持",
           "cover_old": "旧Artifact参照でカバー・新Itemはexternal",
           "use_new": "新側を維持・未取得は通常Batchへ", "reacquire": "新側をpendingへ・取得は別操作",
           "retire": "旧を現行対象から外して履歴保管", "hold": "保留", "blocked": "適用不可"}


class RepairMigrationDialog(QDialog):
    catalogChanged = Signal()

    def __init__(self, catalog, watchlist, *, report="output/hanayume-repair.json", parent=None, auto_load=True):
        super().__init__(parent)
        self.catalog, self.watchlist = Path(catalog), Path(watchlist)
        self.review = self.plan = self.task = None
        self.combos = {}
        self.setWindowTitle("花とゆめ＋ Catalog修復 — Stage 02 適用後・履歴ZIPの分離")
        self.resize(1500, 950)
        layout = QVBoxLayout(self)
        note = QLabel("プレビューでは変更しません。「バックアップして適用」だけがCatalogを更新します。"
                      "ZIP・Watchlist・取得履歴は保持。本文同一性の証明は行わず、人間が対応と採用方針を判断します。")
        note.setWordWrap(True)
        layout.addWidget(note)
        paths = QHBoxLayout()
        self.report_path = QLineEdit(str(report))
        self.report_path.textEdited.connect(self.input_changed)
        self.browse_button = QPushButton("報告JSONを選択")
        self.browse_button.clicked.connect(self.browse)
        self.load_button = QPushButton("報告を読み込む")
        self.load_button.clicked.connect(self.load_report)
        paths.addWidget(self.report_path, 1)
        paths.addWidget(self.browse_button)
        paths.addWidget(self.load_button)
        layout.addLayout(paths)
        self.accepted = QCheckBox("報告の対応関係と旧取得の利用を、人間の判断として採用する（本文同一性の証明とは別）")
        self.accepted.toggled.connect(self.invalidate)
        layout.addWidget(self.accepted)
        controls = QHBoxLayout()
        self.preview_button = QPushButton("移行プレビューを作成・再検証")
        self.preview_button.clicked.connect(self.preview)
        self.all_new_button = QPushButton("すべて新側を採用")
        self.all_new_button.clicked.connect(self.all_new)
        self.edit_button = QPushButton("対応関係をGUIで編集")
        self.edit_button.clicked.connect(self.edit_relations)
        self.save_button = QPushButton("プレビューを新規JSONへ保存")
        self.save_button.clicked.connect(self.save_preview)
        self.history_button = QPushButton("履歴ZIPの分離（Stage 03A）")
        self.history_button.clicked.connect(self.open_history)
        for widget in (self.preview_button, self.all_new_button, self.edit_button, self.save_button, self.history_button):
            controls.addWidget(widget)
        layout.addLayout(controls)
        self.summary = QLabel("報告を読み込んでください")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.after_summary = QLabel()
        self.after_summary.setWordWrap(True)
        layout.addWidget(self.after_summary)
        split = QSplitter()
        self.table = _table(("旧話 / Source", "新話 / Source", "適用前（旧 / 新）", "採用方針",
                             "適用後（予定）の現行話", "残す・削除するDB行", "ZIP・取得履歴", "根拠・fallback理由"))
        for column, width in enumerate((190, 190, 180, 150, 340, 350, 220, 500)):
            self.table.setColumnWidth(column, width)
        self.table.itemSelectionChanged.connect(self.show_details)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.explanation = QPlainTextEdit()
        self.explanation.setReadOnly(True)
        tabs = QTabWidget()
        tabs.addTab(self.explanation, "適用後・DB行の説明")
        tabs.addTab(self.details, "詳細JSON")
        split.addWidget(self.table)
        split.addWidget(tabs)
        split.setSizes([1050, 400])
        layout.addWidget(split, 1)
        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("backup先（既存ファイルは上書きしません）"))
        self.backup_dir = QLineEdit("output/hanayume-repair-backups")
        bottom.addWidget(self.backup_dir, 1)
        self.apply_button = QPushButton("バックアップして適用")
        self.apply_button.clicked.connect(self.apply)
        bottom.addWidget(self.apply_button)
        layout.addLayout(bottom)
        self.status = QLabel("Stage 02。Batch・Grant-only・採番・ZIP削除は実行しません。")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.set_busy(False)
        if auto_load:
            self.load_report()

    def set_busy(self, busy):
        for widget in (self.report_path, self.browse_button, self.load_button, self.accepted, self.backup_dir):
            widget.setEnabled(not busy)
        for widget in (self.preview_button, self.all_new_button, self.edit_button, self.history_button):
            widget.setEnabled(not busy and self.review is not None)
        self.save_button.setEnabled(not busy and self.plan is not None)
        self.apply_button.setEnabled(not busy and self.plan is not None and self.plan.ready)
        for combo in self.combos.values():
            combo.setEnabled(not busy)

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
        except Exception as exc:  # noqa: BLE001 - GUI result boundary
            self.failed(str(exc))
        self.set_busy(self.task is not None)

    def failed(self, message):
        self.task = None
        self.invalidate()
        self.status.setText(f"処理できませんでした（自動再試行なし）: {message}")
        self.set_busy(False)

    def invalidate(self, *args):
        self.plan = None
        self.after_summary.clear()
        self.explanation.setPlainText("方針変更後はプレビューを再作成してください。適用後の状態は未確定です。")
        self.details.clear()
        for row in range(self.table.rowCount()):
            for column in range(4, 8):
                self.table.setItem(row, column, QTableWidgetItem("再プレビュー待ち"))
        self.status.setText("方針を変更しました。適用前にプレビューを再生成してください。")
        self.set_busy(self.task is not None)

    def input_changed(self):
        self.review = None
        self.invalidate()
        self.status.setText("報告JSONのパスを変更しました。読み込み直してください。")

    def browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Stage 01の確認結果", self.report_path.text(), "JSON (*.json)")
        if path:
            self.report_path.setText(path)
            self.load_report()

    def load_report(self):
        path = self.report_path.text()
        self.plan = self.review = None
        self.combos.clear()
        self.table.setRowCount(0)
        self.details.clear()
        self.explanation.clear()
        self.after_summary.clear()
        self.summary.setText("報告を読み込み中…")
        self.status.setText("報告と現在の作品graphを読み取り専用で照合しています…")
        self.start(lambda: load_review_report(path, self.catalog, self.watchlist), self.loaded)

    def loaded(self, review):
        self.review = review
        self.combos.clear()
        self.groups = report_groups(review.analysis)
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.groups))
        by_id = {e.source.id: e for e in review.analysis.entries}
        for row, (group_id, link) in enumerate(self.groups):
            old, new = [by_id[s] for s in link.old_ids], [by_id[s] for s in link.new_ids]
            values = (" / ".join(f"{e.title} [{e.source.id}]" for e in old) or "（新側のみ）",
                      " / ".join(f"{e.title} [{e.source.id}]" for e in new) or "（対応無し）",
                      "旧 " + (",".join(e.item.status for e in old) or "なし")
                      + " / 新 " + (",".join(e.item.status for e in new) or "なし"))
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.table.setItem(row, column, item)
            combo = QComboBox()
            for key, label in POLICIES:
                if (key == "old" and not (old and new)) or (key == "retire" and (not old or new)):
                    continue
                if key in {"new", "reacquire"} and not new:
                    continue
                combo.addItem(label, key)
            combo.currentIndexChanged.connect(self.invalidate)
            self.table.setCellWidget(row, 3, combo)
            self.combos[group_id] = combo
        self.table.blockSignals(False)
        self.status.setText(f"{review.analysis.work.title}: 対応を確認しました。採用方針を指定してプレビューしてください。")
        self.preview()

    def preview(self):
        if self.review is None:
            return
        choices = tuple((key, combo.currentData()) for key, combo in self.combos.items()
                        if combo.currentData() != "auto")
        accepted = self.accepted.isChecked()
        path = self.review.path
        self.plan = None
        self.status.setText("ZIPの存在・サイズ・SHA-256、Catalog、方針を検証しています…")
        self.start(lambda: build_migration_plan(self.catalog, self.watchlist, path,
                                              accepted=accepted, choices=choices), self.previewed)

    def previewed(self, plan):
        if plan.report_digest != self.review.digest:
            raise ValueError("報告JSONが変わりました。読み込み直してプレビューしてください")
        self.plan = plan
        payload = migration_preview_payload(plan, self.review.analysis)
        for row, (entry, outcome) in enumerate(zip(plan.entries, payload["outcomes"], strict=True)):
            current = self.current_text(outcome)
            db = self.db_text(outcome)
            for column, text in ((4, current), (5, db), (6, "既存ZIP・全Run/Artifactを保持")):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.table.setItem(row, column, item)
            text = " / ".join(entry.reasons)
            item = QTableWidgetItem(text)
            item.setToolTip(text)
            self.table.setItem(row, 7, item)
        self.summary.setText(f"{plan.work_key} | " + " / ".join(f"{ACTIONS[k]}: {v}" for k, v in plan.to_dict()["summary"].items()))
        after = payload["after_summary"]
        states = " / ".join(f"{s} {n}話" for s, n in after["current_item_statuses"].items())
        deletions = after["delete"]
        self.after_summary.setText(
            f"適用後の予定: {states} ｜物理削除する履歴なしDB行: "
            f"Item {len(deletions['item_ids'])} / Source {len(deletions['source_ids'])} / Target {len(deletions['target_ids'])}"
            f"（旧pending {after['deleted_old_pending_source_count']} / 新側の空donor {after['deleted_new_donor_source_count']}）"
            f" ｜既存旧Sourceの履歴保管 {after['historical_source_count']} / 旧ID保管alias追加 {after['new_history_alias_count']}"
            + (" ｜保留・適用不可を解決するまで未確定" if not after["resolved"] else ""))
        self.status.setText("適用可能。内容とbackup先を確認してください。" if plan.ready else "適用不可: " + " / ".join(plan.blockers))
        self.show_details()

    def show_details(self):
        if self.plan is None:
            return
        rows = [index.row() for index in self.table.selectionModel().selectedRows()]
        payload = migration_preview_payload(self.plan, self.review.analysis)
        if rows:
            payload["entries"] = [asdict(self.plan.entries[i]) for i in rows]
            payload["outcomes"] = [payload["outcomes"][i] for i in rows]
            ids = {s for i in rows for s in self.plan.entries[i].old_ids + self.plan.entries[i].new_ids}
            payload["current_graph"] = [asdict(e) for e in self.review.analysis.entries if e.source.id in ids]
        if rows:
            sections = []
            for outcome in payload["outcomes"]:
                current = self.current_text(outcome)
                deleted = outcome["delete"]
                kept = outcome["keep"]
                text = [f"適用後の現行話（予定）\n{current}", self.db_text(outcome),
                    f"\n残すItem ID: {self.ids(kept['item_ids'])}",
                    f"残すSource ID: {self.ids(kept['source_ids'])}",
                    f"残すTarget ID: {self.ids(kept['target_ids'])}",
                    f"\n物理削除するItem ID: {self.ids(deleted['item_ids'])}",
                    f"物理削除するSource ID: {self.ids(deleted['source_ids'])}",
                    f"物理削除するTarget ID: {self.ids(deleted['target_ids'])}",
                    "※削除対象は履歴・手動編集・別Sourceのない旧pending、または旧取得継承時の新側の空エントリです。"]
                for current_row in outcome["current_after"]:
                    text.extend((f"\n現行episode ID: {current_row['external_id']}", f"現行URL: {current_row['url']}"))
                for historical in outcome["history_after"]:
                    text.append(f"履歴保管: Item #{historical['item_id']} / Source #{historical['source_id']}"
                                f"（{historical['status']}を保持、取得担当OFF）")
                for alias in outcome["add"]:
                    text.append(f"\n追加: 旧episode ID {alias['external_id']} の保管用Source/Target alias"
                                f"（同じ旧Item #{alias['item_id']}、IDは適用時採番、取得担当OFF）")
                text.append("\n既存ZIP・CrawlRun・Artifact・チケット履歴は保持します。ZIPの削除・上書き・採番変更はありません。")
                text.extend(f"採用ZIP: {p['path']}" for p in outcome["adopted_archives"])
                text.append("\n現行話がpendingなら取得は通常Batchで別途実行します。completed/externalは再取得対象になりません。")
                sections.append("\n".join(text))
            self.explanation.setPlainText("\n\n────────\n\n".join(sections))
        else:
            self.explanation.setPlainText(self.after_summary.text()
                + "\n\n一覧の行を選ぶと、適用後の状態、残るItem/Source ID、削除するDB行、旧ID保管alias、採用ZIPを表示します。"
                  "\n\n旧話のDB行を一律に削除する処理ではありません。旧取得を再利用するときは旧Item/Sourceを現行へ引き継ぎ、新側の空エントリだけを削除します。"
                  "\n新旧pendingでは、履歴・手動編集・別Sourceのない旧DB行を削除し新側だけを残します。保護対象のある旧DB行は理由を表示して履歴保管します。")
        self.details.setPlainText(json.dumps(payload, ensure_ascii=False, indent=2))

    @staticmethod
    def ids(values):
        return ", ".join(map(str, values)) or "なし"

    @staticmethod
    def current_text(outcome):
        if not outcome["resolved"]:
            return "未確定（保留・適用不可）"
        if not outcome["current_after"]:
            return "現行対象なし（旧DB行は履歴保管）"
        return " / ".join(f"{r['status']}（{'旧' if r['origin'] == 'old' else '新'}Item #{r['item_id']} / Source #{r['source_id']}）"
                          + (" 取得担当OFF" if not r["acquisition_enabled"] else "") for r in outcome["current_after"])

    @staticmethod
    def db_text(outcome):
        if not outcome["resolved"]:
            return "未確定・DB変更なし"
        if outcome["action"] == "reuse_identity":
            return "旧Item/Sourceを現行に維持。新側の空Item/Source/Targetを物理削除。旧ID保管aliasを追加。"
        if outcome["deleted_old_pending_source_ids"]:
            return ("旧pendingの空Item/Source/Targetを物理削除。新側pendingを維持。"
                    + ("履歴/編集等がある残りの旧DB行は履歴保管。" if outcome["history_after"] else ""))
        if outcome["history_after"]:
            return "旧DB行は履歴保管（取得担当OFF・物理削除なし）。新DB行も維持。"
        return "既存DB行を維持（物理削除なし）"

    def all_new(self):
        for combo in self.combos.values():
            index = combo.findData("new")
            if index >= 0:
                combo.setCurrentIndex(index)
        self.invalidate()

    def open_history(self):
        if self.review is None or self.task is not None:
            return
        from .repair_history import RepairHistoryDialog
        dialog = RepairHistoryDialog(self.catalog, self.review.analysis.work.work_key,
                                     migration=self.plan, parent=self)
        dialog.catalogChanged.connect(self.invalidate)
        dialog.catalogChanged.connect(self.catalogChanged.emit)
        dialog.exec()
        dialog.deleteLater()

    def edit_relations(self):
        if self.review is None:
            return
        dialog = CatalogRepairDialog(self.catalog, self.watchlist, parent=self, auto_load=False)
        a = self.review.analysis
        dialog.works.addItem(a.work.title, a.work.work_key)
        dialog.set_analysis(a)
        dialog.exec()
        dialog.deleteLater()
        self.status.setText("対応を編集した場合は新規JSONに保存し、そのファイルを読み込んでください。")
        self.invalidate()

    def save_preview(self):
        if self.plan is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "移行プレビューを新規保存", "hanayume-migration-preview.json", "JSON (*.json)")
        if not path:
            return
        plan = self.plan
        payload = migration_preview_payload(plan, self.review.analysis)
        def save():
            with Path(path).open("x", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
        self.start(save, lambda result: self.status.setText(f"プレビューを保存しました: {path}"))

    def apply(self):
        if self.plan is None or not self.plan.ready or self.task is not None:
            return
        plan, backup_dir = self.plan, self.backup_dir.text()
        if not backup_dir.strip():
            self.status.setText("backup先を指定してください")
            return
        if QMessageBox.question(self, "移行プレビューを適用", f"作品: {plan.work_key}\n"
                f"backup先: {backup_dir}\n新規backupを検証後、表示したCatalog変更を一括適用します。\n"
                "旧履歴/ZIPは保持し、Batchやチケット操作は実行しません。適用しますか？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self.start(lambda: apply_migration_plan(plan, expected_token=plan.token, backup_dir=backup_dir), self.applied)

    def applied(self, result):
        self.plan = None
        self.status.setText("適用済み（再実行no-op）" if result.already_applied else
                            f"移行完了。backup: {result.backup}。最新のCatalogを再読込してください。")
        self.catalogChanged.emit()

    def reject(self):
        if self.task is None:
            super().reject()
        else:
            self.status.setText("検証・backup・transaction処理の完了を待ってください。")

    def closeEvent(self, event):
        event.ignore() if self.task is not None else event.accept()
