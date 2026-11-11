"""Read-only Hanayume comparison UI. No Catalog mutation controls exist here."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from screenshot_crawler.maintenance.hanayume_repair import (
    annotate,
    export_report,
    list_repair_works,
    load_analysis,
    unlink,
    with_observations,
)
from screenshot_crawler.site_adapters.hanayume.repair_probe import ProbeLimits, probe_identities


class _Signals(QObject):
    success = Signal(object)
    failure = Signal(str)
    progress = Signal(str)


class _Task(QRunnable):
    def __init__(self, action):
        super().__init__()
        self.action = action
        self.signals = _Signals()

    def run(self):
        try:
            value = self.action(self.signals.progress.emit)
        except Exception as exc:  # noqa: BLE001 - Qt worker boundary
            self.signals.failure.emit(str(exc) or type(exc).__name__)
        else:
            self.signals.success.emit(value)


async def _probe(analysis, limits, cancelled, progress):
    from screenshot_crawler.core.browser import BrowserSession, resolve_cdp_endpoint

    session = await asyncio.wait_for(
        BrowserSession.connect(resolve_cdp_endpoint(site="hanayume")), timeout=15)
    page = None
    try:
        page = await session.new_page()
        return await probe_identities(page, analysis, limits,
                                      cancelled=cancelled, progress=progress)
    finally:
        try:
            if page is not None:
                await session.close_page(page)
        finally:
            await session.close()


def _table(headers):
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    table.setWordWrap(False)
    table.setAlternatingRowColors(True)
    return table


class CatalogRepairDialog(QDialog):
    catalogChanged = Signal()

    def __init__(self, catalog, watchlist, *, parent=None, work_key=None, auto_load=True):
        super().__init__(parent)
        self.catalog, self.watchlist = Path(catalog), Path(watchlist)
        self.initial_work = work_key
        self.analysis = None
        self.task = None
        self.cancelled = Event()
        self.setWindowTitle("花とゆめ＋ Catalog修復 — 話数ラベル優先・読み取り専用")
        self.resize(1500, 1000)
        layout = QVBoxLayout(self)
        note = QLabel("Catalog・Watchlist・ZIP・チケットは変更しません。"
                      "対応指定は確認用メモです。APIのID一致も本文同一性を証明しません。")
        note.setWordWrap(True)
        layout.addWidget(note)
        row = QHBoxLayout()
        self.works = QComboBox()
        self.works.setMinimumWidth(360)
        self.load_button = QPushButton("作品を解析（ローカル）")
        self.load_button.clicked.connect(self.load_work)
        self.search = QLineEdit()
        self.search.setPlaceholderText("左右一覧を絞り込み：話名・ID・key")
        self.search.textChanged.connect(self.render_sources)
        row.addWidget(self.works, 2)
        row.addWidget(self.load_button)
        self.migration_button = QPushButton("Stage 02 移行プレビュー")
        self.migration_button.clicked.connect(self.open_migration)
        row.addWidget(self.migration_button)
        row.addWidget(self.search, 2)
        layout.addLayout(row)
        limits = QHBoxLayout()
        self.offset, self.old_limit, self.request_limit, self.seconds = (
            QSpinBox(), QSpinBox(), QSpinBox(), QSpinBox())
        self.offset.setRange(0, 1000000)
        for widget, maximum, default in ((self.old_limit, 500, 100),
                                          (self.request_limit, 1000, 200), (self.seconds, 600, 180)):
            widget.setRange(1, maximum)
            widget.setValue(default)
        self.interval = QDoubleSpinBox()
        self.interval.setRange(0.5, 30)
        self.interval.setValue(2)
        self.interval.setSuffix(" 秒")
        for label, widget in (("開始offset", self.offset), ("旧ID上限", self.old_limit),
                               ("GET上限", self.request_limit), ("総時間(秒)", self.seconds),
                               ("GET開始間隔", self.interval)):
            limits.addWidget(QLabel(label))
            limits.addWidget(widget)
        self.api_button = QPushButton("API対応解析（読取のみ）")
        self.api_button.clicked.connect(self.start_probe)
        self.stop_button = QPushButton("解析を停止")
        self.stop_button.clicked.connect(self.cancelled.set)
        limits.addWidget(self.api_button)
        limits.addWidget(self.stop_button)
        layout.addLayout(limits)
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)
        vertical = QSplitter(Qt.Orientation.Vertical)
        sides = QSplitter(Qt.Orientation.Horizontal)
        headers = ("話数・タイトル", "Source / Item", "key / 表示位置", "状態", "取得状態",
                   "ZIP記録 / Run", "取得担当", "external_id", "URL")
        self.old_table, self.new_table = _table(headers), _table(headers)
        for title, table in (("旧候補（unavailable）", self.old_table),
                              ("現行候補（available・pending/completed両方）", self.new_table)):
            pane = QWidget()
            box = QVBoxLayout(pane)
            box.addWidget(QLabel(title))
            box.addWidget(table)
            table.setColumnWidth(0, 215)
            table.setColumnWidth(1, 110)
            table.setColumnWidth(7, 230)
            table.setColumnWidth(8, 300)
            table.itemSelectionChanged.connect(self.show_details)
            sides.addWidget(pane)
        vertical.addWidget(sides)
        lower = QWidget()
        lower_layout = QVBoxLayout(lower)
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("手動判断の理由（必須）。左右の複数行をCtrl/Shiftで選択できます")
        lower_layout.addWidget(self.reason)
        actions = QHBoxLayout()
        self.edit_buttons = []
        for label, decision in (("選択した左右を対応指定", "mapped"), ("保留", "hold"),
                                 ("新側を再取得対象に指定", "reacquire"),
                                 ("旧側は対応無し・履歴保管", "retire")):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, d=decision: self.edit_link(d))
            self.edit_buttons.append(button)
            actions.addWidget(button)
        self.unlink_button = QPushButton("選択グループを解除")
        self.unlink_button.clicked.connect(self.remove_links)
        actions.addWidget(self.unlink_button)
        self.save_button = QPushButton("確認結果を新規JSONに保存")
        self.save_button.clicked.connect(self.save_report)
        actions.addWidget(self.save_button)
        lower_layout.addLayout(actions)
        self.links = _table(("対応形状", "証拠 / 判断", "旧Source", "新Source", "判定根拠"))
        self.links.setColumnWidth(1, 230)
        self.links.setColumnWidth(2, 180)
        self.links.setColumnWidth(3, 180)
        self.links.setColumnWidth(4, 800)
        self.links.itemSelectionChanged.connect(self.select_link)
        lower_layout.addWidget(self.links)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        lower_layout.addWidget(self.details)
        vertical.addWidget(lower)
        vertical.setSizes([440, 420])
        layout.addWidget(vertical, 1)
        self.status = QLabel("Catalogを読み込みます。解析は取得処理を実行しません。")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.set_busy(False)
        if auto_load:
            self.start_task(lambda progress: list_repair_works(self.catalog), self.loaded_works)

    def set_busy(self, busy):
        for widget in (self.works, self.load_button, self.api_button, self.save_button,
                       self.migration_button,
                       self.unlink_button, *self.edit_buttons, self.reason,
                       self.offset, self.old_limit, self.request_limit, self.seconds, self.interval):
            widget.setEnabled(not busy and (widget in (self.works, self.load_button, self.migration_button)
                                           or self.analysis is not None))
        self.stop_button.setEnabled(busy)

    def start_task(self, action, callback):
        if self.task is not None:
            return
        self.cancelled.clear()
        self.task = _Task(action)
        self.task.signals.progress.connect(self.status.setText)
        self.task.signals.failure.connect(self.failed)
        self.task.signals.success.connect(lambda result: self.finished(result, callback))
        self.set_busy(True)
        QThreadPool.globalInstance().start(self.task)

    def finished(self, result, callback):
        self.task = None
        try:
            callback(result)
        except Exception as exc:  # noqa: BLE001 - result validation belongs on GUI thread
            self.status.setText(f"結果の表示に失敗しました: {exc}")
        self.set_busy(self.task is not None)

    def failed(self, message):
        self.task = None
        self.status.setText(f"解析できませんでした: {message}")
        self.set_busy(False)

    def loaded_works(self, works):
        self.works.clear()
        for work in works:
            self.works.addItem(f"{work.title} / {work.work_key}", work.work_key)
        if self.initial_work:
            index = self.works.findData(self.initial_work)
            if index >= 0:
                self.works.setCurrentIndex(index)
        if works:
            self.load_work()
        else:
            self.status.setText("hanayume作品がCatalogにありません")

    def load_work(self):
        key = self.works.currentData()
        if key and self.task is None:
            self.status.setText("全履歴を読み取り、候補を作成しています…")
            self.start_task(lambda progress: load_analysis(self.catalog, self.watchlist, key),
                            self.set_analysis)

    def set_analysis(self, analysis):
        self.analysis = analysis
        self.offset.setValue(0)
        self.render()
        self.set_busy(False)
        self.status.setText("ローカル解析完了。必要ならAPI対応解析を実行してください。"
                            "作品の再解析で手動メモとAPI結果はリセットされます。")

    def render(self):
        self.render_sources()
        self.links.blockSignals(True)
        self.links.setRowCount(len(self.analysis.links))
        evidence = {"api_identity": "API ID対応（本文未証明）", "heuristic": "推測候補", "manual": "手動指定"}
        decisions = {"review": "要確認", "mapped": "対応メモ", "hold": "保留", "reacquire": "再取得メモ",
                     "retire": "対応無し・履歴保管メモ"}
        for row, link in enumerate(self.analysis.links):
            label = ("ラベル一致で1対1推測" if link.match_rule == "label_number_unique"
                     else evidence[link.evidence])
            values = (link.shape + (" 候補複数" if link.evidence == "heuristic" and link.shape != "1対1" else ""),
                      label + " / " + decisions[link.decision],
                      ", ".join(map(str, link.old_ids)), ", ".join(map(str, link.new_ids)),
                      " / ".join(link.reasons))
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.links.setItem(row, col, item)
        self.links.blockSignals(False)
        self.summary_label.setText("　|　".join(f"{k}: {v}" for k, v in self.analysis.summary().items()))
        self.show_details()

    def render_sources(self):
        if self.analysis is None:
            return
        query = self.search.text().casefold()
        for table, entries in ((self.old_table, self.analysis.old),
                                (self.new_table, self.analysis.current)):
            entries = [e for e in entries if query in
                       f"{e.title} {e.source.external_id} {e.source.discovery_key} {e.source.id}".casefold()]
            table.blockSignals(True)
            table.setRowCount(len(entries))
            for row, e in enumerate(entries):
                values = (e.title, f"{e.source.id} / {e.item.id}",
                          f"{e.source.discovery_key} / {e.source.display_position}",
                          "available" if e.source.available else "unavailable", e.item.status,
                          f"{e.zip_count} ZIP / {len(e.runs)} Run", "ON" if e.source.acquisition_enabled else "OFF",
                          e.source.external_id, e.url)
                for col, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setData(Qt.ItemDataRole.UserRole, e.source.id)
                    item.setToolTip(value)
                    table.setItem(row, col, item)
            table.blockSignals(False)

    @staticmethod
    def selected_ids(table):
        return tuple(table.item(index.row(), 0).data(Qt.ItemDataRole.UserRole)
                     for index in table.selectionModel().selectedRows())

    def show_details(self):
        if self.analysis is None:
            return
        selected = set(self.selected_ids(self.old_table) + self.selected_ids(self.new_table))
        details = {"注意": self.analysis.diagnostics, "snapshot_token": self.analysis.token,
                   "設定": [asdict(t) for t in self.analysis.targets],
                   "選択Sourceの全履歴（最大20Source）": [asdict(e) for e in self.analysis.entries
                                                          if e.source.id in selected][:20],
                   "選択Sourceの候補と根拠": [asdict(l) for l in self.analysis.links
                                              if selected.intersection(l.old_ids + l.new_ids)],
                   "API観測": [asdict(o) for o in self.analysis.observations
                                if not selected or o.old_source_id in selected]}
        self.details.setPlainText(json.dumps(details, ensure_ascii=False, indent=2))

    def select_link(self):
        indexes = self.links.selectionModel().selectedRows()
        if not indexes or self.analysis is None:
            return
        links = [self.analysis.links[i.row()] for i in indexes]
        for table, ids in ((self.old_table, {s for l in links for s in l.old_ids}),
                            (self.new_table, {s for l in links for s in l.new_ids})):
            table.blockSignals(True)
            table.clearSelection()
            for row in range(table.rowCount()):
                if table.item(row, 0).data(Qt.ItemDataRole.UserRole) in ids:
                    table.selectRow(row) if len(ids) == 1 else self._select_row(table, row)
            table.blockSignals(False)
        self.show_details()

    @staticmethod
    def _select_row(table, row):
        from PySide6.QtCore import QItemSelectionModel
        table.selectionModel().select(table.model().index(row, 0),
            QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)

    def edit_link(self, decision):
        if self.task is not None or self.analysis is None:
            return
        try:
            self.analysis = annotate(self.analysis, self.selected_ids(self.old_table),
                                     () if decision == "retire" else self.selected_ids(self.new_table),
                                     decision, self.reason.text())
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self.render()
        self.status.setText("確認用メモを変更しました。Catalog/Batchへの適用効果はありません。")

    def remove_links(self):
        if self.task is None and self.analysis is not None:
            self.analysis = unlink(self.analysis, tuple(i.row() for i in
                                                       self.links.selectionModel().selectedRows()))
            self.render()

    def start_probe(self):
        if self.analysis is None or self.task is not None:
            return
        analysis = self.analysis
        limits = ProbeLimits(self.old_limit.value(), self.request_limit.value(),
                             self.seconds.value(), self.interval.value(), self.offset.value())
        def action(progress):
            result = asyncio.run(_probe(analysis, limits, self.cancelled.is_set, progress))
            return result, with_observations(analysis, result.observations)
        self.start_task(action, self.probed)

    def probed(self, payload):
        result, self.analysis = payload
        self.offset.setValue(result.next_offset)
        self.render()
        self.status.setText(f"{result.stop_reason} / GET {result.requests} / "
                            f"次offset {result.next_offset}/{result.total_old}。部分結果も表示しています。")

    def save_report(self):
        if self.analysis is None or self.task is not None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "確認結果を新規保存", "hanayume-repair.json", "JSON (*.json)")
        if not path:
            return
        analysis = self.analysis
        self.start_task(lambda progress: export_report(analysis, path),
                        lambda result: self.status.setText(f"確認結果を保存しました: {path}"))

    def open_migration(self):
        if self.task is not None:
            return
        from .repair_migration import RepairMigrationDialog
        dialog = RepairMigrationDialog(self.catalog, self.watchlist, parent=self)
        dialog.catalogChanged.connect(self.catalogChanged.emit)
        dialog.catalogChanged.connect(self.load_work)
        dialog.exec()
        dialog.deleteLater()

    def reject(self):
        if self.task is not None:
            self.cancelled.set()
            self.status.setText("停止処理中です。処理終了後に閉じてください。")
            return
        super().reject()

    def closeEvent(self, event):
        if self.task is not None:
            self.cancelled.set()
            event.ignore()
        else:
            event.accept()
