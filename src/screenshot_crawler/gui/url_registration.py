"""URL paste, evidence and explicit per-Work registration drafts."""

from __future__ import annotations

import asyncio
import copy
import time
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from screenshot_crawler.discovery.base import DiscoveryAdapter
from screenshot_crawler.management.catalog_reader import CatalogInventoryReader
from screenshot_crawler.registration.draft import BatchRegistrationDraft
from screenshot_crawler.registration.models import UrlResolution
from screenshot_crawler.registration.resolver import UrlResolver, split_inputs
from screenshot_crawler.watchlist.service import WatchlistService

from .work_editor import _WorkTask


class _ResolveSignals(QObject):
    row = Signal(object)
    finished = Signal()


class _ResolveWorker(QRunnable):
    """One sequential bounded worker; only optional safe metadata uses CDP."""

    def __init__(self, resolver, entries, generation, metadata):
        super().__init__()
        self.resolver, self.entries = resolver, tuple(entries)
        self.generation, self.metadata = generation, metadata
        self.signals = _ResolveSignals()

    def run(self):
        async def observe(result):
            from screenshot_crawler.core.browser import BrowserSession, resolve_cdp_endpoint
            session, page = None, None
            try:
                session = await BrowserSession.connect(resolve_cdp_endpoint(site=result.site))
                page = await session.new_page()
                return await self.resolver.observe(page, result)
            finally:
                try:
                    if page is not None:
                        await session.close_page(page)
                finally:
                    if session is not None:
                        await session.close()

        async def resolve_all():
            deadline = time.monotonic() + 600
            for candidate_id, line, raw in self.entries:
                try:
                    result = self.resolver.resolve(raw)
                except Exception as exc:  # noqa: BLE001 - isolate a failed input
                    result = UrlResolution(input_url=raw, blockers=(f"解析失敗: {exc}",))
                if time.monotonic() >= deadline:
                    result = result.blocked("解析上限10分に達しました。後で再試行してください")
                elif self.metadata and result.status != "blocked":
                    try:
                        adapter = self.resolver.registry.create(result.site)
                        if type(adapter).observe_registration_metadata is not DiscoveryAdapter.observe_registration_metadata:
                            result = await asyncio.wait_for(observe(result), timeout=60)
                    except Exception as exc:  # noqa: BLE001 - preserve pure URL evidence
                        result = replace(result, warnings=(*result.warnings,
                            f"作品名取得未確認（手動確認可）: {exc}"))
                self.signals.row.emit((self.generation, candidate_id, line, raw, result))
        try:
            asyncio.run(resolve_all())
        finally:
            self.signals.finished.emit()


class UrlRegistrationDialog(QDialog):
    fullRequested = Signal(object)
    watchlistSaved = Signal()

    def __init__(self, watchlist_path, catalog_path, runtime_path, *, draft=None,
                 snapshot=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Watchlist：URLから一括登録")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.resize(1200, 880)
        self.path, self.catalog, self.runtime_path = Path(watchlist_path), Path(catalog_path), runtime_path
        self.snapshot, self.draft = snapshot, draft
        self.pool = QThreadPool(self)
        self.task = None
        self.active_job = self.dirty = False
        self._generation = 0
        self._rendering = self._form_dirty = False
        self._selected_id = None
        self.preview = None
        self._save_frozen = False
        layout = QVBoxLayout(self)
        intro = QLabel("公式サイトの作品・話URLを改行で貼り付けてください。URL判定と作品の確認は別です。\n"
            "異サイトの同一作品は人が所属を指定します。登録解析は読取専用です。")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("https://…\nhttps://…（1回100行まで）")
        self.input.setMaximumHeight(110)
        self.input.textChanged.connect(self._input_changed)
        layout.addWidget(self.input)
        actions = QHBoxLayout()
        self.analyze_button = QPushButton("URLを解析・追加")
        self.retry_button = QPushButton("選択行を再解析")
        self.reload_button = QPushButton("基準を再読込")
        self.refresh_button = QPushButton("Catalogを再照合")
        self.metadata = QCheckBox("安全な作品名取得も試す（対応サイトのみ）")
        self.metadata.setChecked(True)
        self.analyze_button.clicked.connect(self.analyze)
        self.retry_button.clicked.connect(self.retry_selected)
        self.reload_button.clicked.connect(self.reload_context)
        self.refresh_button.clicked.connect(self.refresh_catalog)
        for button in (self.analyze_button, self.retry_button, self.reload_button, self.refresh_button, self.metadata):
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(("登録対象", "URL判定", "サイト", "作品名", "Work / key", "登録準備"))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setColumnWidth(0, 75)
        self.table.setColumnWidth(1, 90)
        self.table.setColumnWidth(2, 100)
        self.table.setColumnWidth(3, 190)
        self.table.setColumnWidth(4, 260)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.currentCellChanged.connect(self._selection_changed)
        self.table.itemChanged.connect(self._checked)
        layout.addWidget(self.table, 2)
        self.form_widget = QWidget()
        form = QFormLayout(self.form_widget)
        self.url_edit, self.label_edit, self.reading_edit = QLineEdit(), QLineEdit(), QLineEdit()
        self.work_combo, self.work_edit, self.key_edit = QComboBox(), QLineEdit(), QLineEdit()
        self.work_combo.setMinimumContentsLength(25)
        self.work_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        for label, control in (("元URL（修正後に再解析）", self.url_edit), ("作品名 label", self.label_edit),
                ("読み / ローマ字候補の入力", self.reading_edit), ("所属Work（明示選択）", self.work_combo),
                ("work_key", self.work_edit), ("key", self.key_edit)):
            form.addRow(label, control)
            if isinstance(control, QLineEdit):
                control.textChanged.connect(self._form_changed)
        self.work_combo.currentIndexChanged.connect(self._form_changed)
        layout.addWidget(self.form_widget)
        edits = QHBoxLayout()
        self.apply_button = QPushButton("編集を下書きへ反映")
        self.suggest_button = QPushButton("読みからID候補")
        self.suggest_button.setToolTip("機械変換の読み・ローマ字は候補です。読みとIDを確認してください。")
        self.confirm_button = QPushButton("作品名・所属・IDを確認")
        self.detail_button = QPushButton("範囲・完成順の詳細編集")
        self.additional = QCheckBox("登録済み作品へ別keyを追加する")
        for button, action in ((self.apply_button, self.apply_fields), (self.suggest_button, self.suggest),
                (self.confirm_button, self.confirm), (self.detail_button, self.edit_detail)):
            button.clicked.connect(action)
            edits.addWidget(button)
        layout.addLayout(edits)
        layout.addWidget(self.additional)
        self.evidence = QPlainTextEdit()
        self.evidence.setReadOnly(True)
        self.evidence.setMaximumHeight(100)
        layout.addWidget(self.evidence)
        self.status = QLabel("基準Watchlist/Catalogを読取中…")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.status)
        footer = QHBoxLayout()
        self.preview_button = QPushButton("選択Workの保存前プレビュー")
        self.save_button = QPushButton("選択Workを一括保存")
        self.close_button = QPushButton("閉じる")
        self.preview_button.clicked.connect(self.preview_edit)
        self.save_button.clicked.connect(self.save_edit)
        self.close_button.clicked.connect(self.close)
        for button in (self.preview_button, self.save_button, self.close_button):
            footer.addWidget(button)
        layout.addLayout(footer)
        # Dialog Enter must not invoke analyze/confirm/save unexpectedly.
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        if draft is None:
            self.reload_context()
        else:
            self.status.setText("下書きのみ。選択Workの保存前プレビューで内容を確認してください。")
            self._render()

    def _input_changed(self):
        if not self._rendering:
            self.dirty = True

    def _form_changed(self, *_args):
        if not self._rendering:
            self._form_dirty = self.dirty = True
            self.preview = None
            self._enabled()

    def _guard(self):
        if self.task is not None or self.active_job or self._save_frozen:
            self.status.setText("処理またはJobの完了を待ってください。下書きは保持しています。")
            return False
        return self.draft is not None

    def set_active_job(self, active):
        self.active_job = active
        self._enabled()

    def _enabled(self):
        enabled = self.task is None and not self.active_job and self.draft is not None and not self._save_frozen
        for widget in (self.input, self.analyze_button, self.retry_button, self.table,
                       self.form_widget, self.apply_button, self.suggest_button, self.metadata, self.additional):
            widget.setEnabled(enabled)
        row = self.draft.candidates.get(self._selected_id) if self.draft else None
        self.form_widget.setEnabled(enabled and row is not None)
        self.confirm_button.setEnabled(enabled and row is not None and row.resolution.status != "blocked")
        self.detail_button.setEnabled(enabled and row is not None and row.resolution.status != "blocked")
        self.detail_button.setToolTip("完全一覧preview対応4サイトで、範囲・担当と完成順を確認します。")
        self.preview_button.setEnabled(enabled and bool(self.draft.candidates))
        self.save_button.setEnabled(enabled and self.preview is not None and not self._form_dirty)
        self.refresh_button.setEnabled(enabled)
        self.reload_button.setEnabled(self.task is None and not self.active_job)
        self.close_button.setEnabled(self.task is None)

    def _run(self, action, callback):
        task = _WorkTask(action)
        task.signals.success.connect(callback)
        task.signals.failure.connect(self._failure)
        self.task = task
        self._enabled()
        self.pool.start(task)

    def reload_context(self):
        if self.task is not None or self.active_job or not self._discard():
            return
        def load():
            from screenshot_crawler.cli import _discovery_registry
            base, revision = WatchlistService(self.path).read_snapshot()
            data = CatalogInventoryReader().read(self.catalog)
            draft = BatchRegistrationDraft(base, revision, UrlResolver(_discovery_registry()),
                catalog_works=tuple((work.work_key, work.title) for work in data.works), catalog_snapshot=data)
            draft.prepare_ownership(data)
            return draft
        self._run(load, self._context_ready)

    def _context_ready(self, draft):
        self.task, self.draft, self.dirty = None, draft, False
        self.preview, self._save_frozen = None, False
        self._selected_id = None
        self.status.setText("URLを貼り付けて解析してください。登録までCatalog・ZIPは変更しません。")
        self._render()

    def analyze(self):
        if not self._guard():
            return
        self.apply_fields()
        try:
            entries = split_inputs(self.input.toPlainText())
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        known = {raw for row in self.draft.candidates.values() for _, raw in row.origins}
        self.draft.raw_input += "\n" + self.input.toPlainText()
        self._resolve(tuple((None, line, raw) for line, raw in entries if raw not in known))

    def retry_selected(self):
        if not self._guard():
            return
        self.apply_fields()
        if self._selected_id:
            row = self.draft.candidates[self._selected_id]
            self._resolve(((row.id, row.origins[0][0], row.resolution.input_url),))

    def _resolve(self, entries):
        if not entries:
            self.status.setText("新しい入力がありません。修正した行は選択して再解析してください。")
            return
        self._generation += 1
        task = _ResolveWorker(self.draft.resolver, entries, self._generation, self.metadata.isChecked())
        task.signals.row.connect(self._resolved)
        task.signals.finished.connect(self._resolve_finished)
        self.task = task
        self.status.setText(f"解析中 {len(entries)}件（順次処理・上限10分）…")
        self._enabled()
        self.pool.start(task)

    def _resolved(self, result):
        generation, row_id, line, raw, resolution = result
        if generation != self._generation:
            return
        if row_id is None:
            row_id = self.draft.add_resolution(line, raw, resolution)
        else:
            self.draft.retry(row_id, resolution)
        self.dirty, self.preview = True, None
        self._render(selected=row_id)

    def _resolve_finished(self):
        self.task = None
        self.status.setText("解析完了。作品名・Work所属・IDを確認してください。まだ保存していません。")
        self._enabled()

    def _failure(self, message):
        self.task = None
        self.preview = None
        self.status.setText("停止（下書き保持）: " + message)
        self._enabled()

    def _render(self, selected=None):
        self._rendering = True
        selected = selected or self._selected_id
        self.table.blockSignals(True)
        rows = tuple(self.draft.candidates.values()) if self.draft else ()
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            group = self.draft.works[row.group_id]
            state = self.draft.readiness(group.id)
            values = ("", row.resolution.status, row.resolution.site or "—", row.label or "作品名未確認",
                f"{group.work_key or '未確定'} / {row.key or '未確定'}", state.status)
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, row.id)
                item.setToolTip("\n".join(state.reasons))
                if column == 0:
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(Qt.CheckState.Checked if group.selected else Qt.CheckState.Unchecked)
                self.table.setItem(index, column, item)
        index = next((i for i, row in enumerate(rows) if row.id == selected), 0)
        if rows:
            self.table.setCurrentCell(index, 0)
            self._selected_id = rows[index].id
        else:
            self._selected_id = None
        self.table.blockSignals(False)
        self._fill_form()
        self._rendering = False
        self._enabled()

    def _fill_form(self):
        row = self.draft.candidates.get(self._selected_id) if self.draft else None
        if row is None:
            self.form_widget.setEnabled(False)
            return
        group = self.draft.works[row.group_id]
        for edit, value in ((self.url_edit, row.resolution.input_url), (self.label_edit, row.label),
                (self.reading_edit, row.reading), (self.work_edit, group.work_key), (self.key_edit, row.key)):
            edit.setText(value)
        self.work_combo.clear()
        for work in self.draft.works.values():
            if not work.existing:
                self.work_combo.addItem(f"新規: {work.work_key or 'Work ' + work.id}", work.id)
        for key, title in self.draft.existing_works.items():
            self.work_combo.addItem(f"既存: {title} / {key}", "existing:" + key)
        self.work_combo.addItem("この候補を別の新規Workへ分離", "detach")
        self.work_combo.setCurrentIndex(self.work_combo.findData(group.id))
        self.work_edit.setReadOnly(group.existing)
        self.additional.setChecked(row.additional)
        self.additional.setVisible(bool(row.existing_keys))
        state = self.draft.readiness(group.id)
        resolution = row.resolution
        self.evidence.setPlainText(f"元URL: {resolution.input_url}\n起点URL: {resolution.discovery_url or '未確定'}\n"
            f"native identity: {resolution.identity_status} {resolution.site_work_identity or ''} / "
            f"title: {resolution.title_status} / human confirmed: {row.confirmed}\n"
            + "\n".join((*resolution.evidence, *resolution.warnings, *resolution.blockers, *state.reasons)))
        if group.detail is not None:
            self.evidence.appendPlainText("\n詳細確認:\n" + group.detail.summary)
        hints = self.draft.title_hints(row.id)
        if hints:
            self.evidence.appendPlainText("\n同名の既存Work候補（所属は明示選択）: "
                + ", ".join(f"{title} / {key}" for key, title in hints))
        self._form_dirty = False

    def _selection_changed(self, *_args):
        if self._rendering or self.task is not None:
            return
        cell = self.table.item(self.table.currentRow(), 0)
        if cell is None:
            return
        selected = cell.data(Qt.ItemDataRole.UserRole)
        self.apply_fields(render=False)
        self._render(selected=selected)

    def _checked(self, item):
        if self._rendering or item.column() != 0:
            return
        self.apply_fields(render=False)
        row = self.draft.candidates[item.data(Qt.ItemDataRole.UserRole)]
        self.draft.select(row.group_id, item.checkState() == Qt.CheckState.Checked)
        self.dirty, self.preview = True, None
        self._render()

    def apply_fields(self, _checked=False, *, render=True):
        if not self._form_dirty or not self._selected_id or self.draft is None:
            return
        row_id = self._selected_id
        row = self.draft.candidates[row_id]
        choice = self.work_combo.currentData()
        try:
            if choice != row.group_id:
                if choice == "detach":
                    self.draft.assign(row_id)
                elif choice and choice.startswith("existing:"):
                    self.draft.assign(row_id, existing_work=choice.removeprefix("existing:"))
                else:
                    self.draft.assign(row_id, group_id=choice)
            group = self.draft.works[self.draft.candidates[row_id].group_id]
            if choice == row.group_id and self.work_edit.text() != group.work_key:
                self.draft.name_work(group.id, self.work_edit.text())
            edits = {}
            for name, edit in (("label", self.label_edit), ("reading", self.reading_edit), ("key", self.key_edit)):
                if edit.text() != getattr(row, name):
                    edits[name] = edit.text()
            if edits:
                self.draft.edit_candidate(row_id, **edits)
            if self.url_edit.text() != row.resolution.input_url:
                self.draft.retry(row_id, UrlResolution(input_url=self.url_edit.text(), blockers=("修正URLを再解析してください",)))
            self._form_dirty = False
            self.dirty, self.preview = True, None
            if render:
                self._render(selected=row_id)
        except ValueError as exc:
            self.status.setText(str(exc))

    def suggest(self):
        if self._guard() and self._selected_id:
            self.apply_fields()
            self.draft.suggest(self._selected_id)
            self._render()

    def confirm(self):
        if not self._guard() or not self._selected_id:
            return
        additional = self.additional.isChecked()
        self.apply_fields()
        try:
            self.draft.confirm(self._selected_id, additional=additional)
            self.dirty, self.preview = True, None
            self._render()
        except ValueError as exc:
            self.status.setText(str(exc))

    def edit_detail(self):
        if not self._guard() or not self._selected_id:
            return
        self.apply_fields()
        from screenshot_crawler.registration.detail import accept_detail, detail_draft

        from .work_editor import WorkEditorDialog
        try:
            row = self.draft.candidates[self._selected_id]
            request, draft = detail_draft(self.draft, row.group_id)
            editor = WorkEditorDialog(self.path, self.catalog, self.runtime_path,
                draft=draft, revision=request.revision, catalog_identity=request.catalog_identity,
                snapshot=self.snapshot, parent=self)
            if editor.exec() == QDialog.DialogCode.Accepted and editor.draft_result:
                result, configured = editor.draft_result
                proof = accept_detail(self.draft, request, result, configured)
                self.dirty, self.preview = True, None
                self.status.setText("このWorkの詳細を下書きへ反映しました。Watchlist未保存。")
                self.evidence.setPlainText(proof.summary)
                self._render()
            editor.deleteLater()
        except ValueError as exc:
            self.status.setText(str(exc))

    def preview_edit(self):
        if not self._guard():
            return
        self.apply_fields()
        from screenshot_crawler.registration.service import RegistrationService
        batch = copy.deepcopy(self.draft)
        self._run(lambda: RegistrationService(self.path, self.catalog).preview(batch), self._preview_ready)

    def _preview_ready(self, preview):
        from screenshot_crawler.registration.service import draft_identity
        self.task = None
        if draft_identity(self.draft) != preview.draft_identity:
            self._failure("プレビュー中に下書きが変わりました")
            return
        self.preview = preview
        self.evidence.setPlainText(preview.summary)
        self.status.setText("保存前プレビュー完了。内容を確認し、一括保存で明示確定してください。")
        self._enabled()
        self._show_preview(preview.summary)

    def _show_preview(self, summary):
        dialog = QDialog(self)
        dialog.setWindowTitle("URL登録：選択Workの保存前プレビュー")
        dialog.resize(1000, 760)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(summary)
        layout.addWidget(text)
        close = QPushButton("候補画面へ戻る（一括保存はまだです）")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()
        dialog.deleteLater()

    def save_edit(self):
        if not self._guard():
            return
        self.apply_fields()
        if self.preview is None:
            self.status.setText("選択Workの保存前プレビューを再実行してください。")
            return
        from screenshot_crawler.registration.service import RegistrationService
        batch, preview = copy.deepcopy(self.draft), self.preview
        self._run(lambda: RegistrationService(self.path, self.catalog).save(batch, preview), self._saved)

    def _saved(self, result):
        self.task, self.preview = None, None
        self.status.setText(result.message)
        if not result.verified:
            self._save_frozen = self.dirty = True
            self._enabled()
            self.watchlistSaved.emit()
            return
        from screenshot_crawler.registration.service import retain_unsaved
        retain_unsaved(self.draft, result)
        self._selected_id = None
        self.dirty = bool(self.draft.candidates)
        self._render()
        # Temporarily hide to let MainWindow present its one Full confirmation.
        # Unselected drafts remain in this dialog and can be reopened unchanged.
        self.hide()
        self.watchlistSaved.emit()
        if result.changed_keys:
            self.fullRequested.emit((result.changed_keys, result.revision))

    def refresh_catalog(self):
        if not self._guard():
            return
        self.apply_fields()
        def read():
            if WatchlistService(self.path).read_snapshot() != (self.draft.base, self.draft.revision):
                raise ValueError("Watchlistが変わっています。基準を再読込する前に下書きを確認してください")
            data = CatalogInventoryReader().read(self.catalog)
            self.draft.prepare_ownership(data)
            return data
        def loaded(data):
            self.task = None
            self.draft.catalog_snapshot = data
            self.draft.catalog_works = tuple((work.work_key, work.title) for work in data.works)
            for group in self.draft.works.values():
                group.version += 1
                group.detail = None
            self.draft.generation += 1
            self.dirty, self.preview = True, None
            self._render()
            self.status.setText("Catalogの所有関係を再照合しました。候補編集は保持、詳細一覧は再取得・再確認が必要です。")
        self._run(read, loaded)

    def _discard(self):
        return not self.dirty or QMessageBox.question(self, "未保存のURL登録",
            "未保存の入力・候補・詳細設定を破棄しますか？",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Discard

    def reject(self):
        if self.task is None and self._discard():
            self.dirty = False
            super().reject()

    def closeEvent(self, event):
        if self.task is not None or not self._discard():
            event.ignore()
        else:
            self.dirty = False
            event.accept()
