"""Work-level Watchlist registration, interval editing and replacement UI."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QStringListModel, Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from screenshot_crawler.catalog.job_lock import CatalogJobLock
from screenshot_crawler.management.catalog_reader import CatalogInventoryReader
from screenshot_crawler.watchlist.service import WatchlistService
from screenshot_crawler.watchlist.work_edit import WorkDraft, full_changed_keys, selected_rows

from .watchlist_editor import AddWatchlistKeyDialog, _catalog_snapshot_identity, _ListingWorker


@dataclass(frozen=True)
class WorkEditPreview:
    targets: tuple
    revision: str
    catalog_identity: str
    work_key: str
    listings: tuple
    summary: str


def validate_work(draft: WorkDraft, path: Path, catalog: Path, revision: str) -> WorkEditPreview:
    """Read-only, complete-Work validation; new Catalog identities are optional."""
    draft.validate()
    preview = WatchlistService(path).preview_edit(draft.targets, expected_revision=revision)
    if not preview.ready:
        raise ValueError(" / ".join(preview.blockers))
    data = CatalogInventoryReader().read(catalog)
    work_by_id = {work.id: work for work in data.works}
    items = {item.id: item for item in data.items}
    known = {(source.site, source.external_id): source for source in data.sources}
    target_by_key = {target.key: target for target in draft.members}
    listing_ids = {key: {row.external_id for row in draft.listings[key].rows} for key in target_by_key}
    for source in data.sources:
        if work_by_id[items[source.item_id].work_id].work_key != draft.work_key:
            continue
        owner = target_by_key.get(source.discovery_key)
        if source.acquisition_enabled and owner is None:
            raise ValueError("作品に所有key不明の担当Sourceがあります。先にCatalogの所有関係を確認してください")
        if owner is not None and owner.site != source.site:
            raise ValueError("Sourceの所有keyとサイトが一致しません")
        if source.acquisition_enabled and owner is not None and source.external_id not in listing_ids[owner.key]:
            raise ValueError("担当中の既存Sourceが完全一覧にありません。欠落を確認してから再編集してください")
    chosen = {}
    summary = []
    for target in draft.members:
        rows = selected_rows(target, draft.listings[target.key])
        selected = {row.external_id for row in rows}
        current = [source for source in data.sources if source.site == target.site and source.discovery_key == target.key]
        new = 0
        for row in rows:
            identity = target.site, row.external_id
            if identity in chosen:
                raise ValueError(f"同一サイトの担当が重複しています: {chosen[identity]} / {target.key}")
            chosen[identity] = target.key
            source = known.get(identity)
            if source is None:
                new += 1
            elif (source.discovery_key != target.key
                  or work_by_id[items[source.item_id].work_id].work_key != target.work_key):
                raise ValueError(f"{target.key}: {row.external_id} は別key/作品のSourceです")
        excluded = sum(source.acquisition_enabled and source.external_id not in selected for source in current)
        retained = sum(source.acquisition_enabled and source.external_id in selected for source in current)
        summary.append(f"{target.site} / {target.key}: 担当 {len(rows)} / 維持 {retained} / 担当外 {excluded} / Catalog未登録 {new}")
    summary.append("\n完成後の並び（新規登録・担当範囲と番号の最終確定はFull後）")
    position = 1
    for block in draft.blocks():
        rows = draft.rows_for_block(block)
        if not rows:
            continue
        summary.append(f"{position:03}〜{position + len(rows) - 1:03} {block.key}: {rows[0].display_title} → {rows[-1].display_title}"
                       + (" [新着も含む]" if block.end_external_id is None else ""))
        position += len(rows)
    # Existing artifact records are references only: never inspect/rename files.
    own_item_ids = {source.item_id for source in data.sources if source.discovery_key in {target.key for target in draft.members}}
    artifact_count = sum(artifact.kind == "archive" and artifact.item_id in own_item_ids for artifact in data.artifacts)
    if artifact_count:
        summary.append(f"\n既存ZIP記録 {artifact_count}件。番号変更による改名・出力先衝突は別途audit/renumberで確認してください。既存ZIPは変更しません。")
    return WorkEditPreview(draft.targets, revision, _catalog_snapshot_identity(data), draft.work_key,
                           tuple(draft.listings.values()), "\n".join(summary))


class _Signals(QObject):
    success = Signal(object)
    failure = Signal(str)


class _WorkTask(QRunnable):
    def __init__(self, action):
        super().__init__()
        self.action = action
        self.signals = _Signals()

    def run(self):
        try:
            result = self.action()
        except Exception as exc:  # noqa: BLE001 - worker/UI boundary
            self.signals.failure.emit(str(exc))
        else:
            self.signals.success.emit(result)


class _SitePane(QWidget):
    def __init__(self, editor, target):
        super().__init__()
        self.editor, self.target = editor, target
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"{target.site} / {target.key}"))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(("話名", "取得状態", "現在担当", "変更後担当"))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setColumnWidth(0, 245)
        self.table.setMinimumWidth(340)
        layout.addWidget(self.table, 1)
        self.first, self.last = QComboBox(), QComboBox()
        self.oldest, self.latest = QCheckBox("最古から"), QCheckBox("新着も含める")
        form = QFormLayout()
        form.addRow("開始", self.first)
        form.addRow(self.oldest)
        form.addRow("終了", self.last)
        form.addRow(self.latest)
        self.oldest.toggled.connect(lambda checked: self.first.setEnabled(not checked))
        self.latest.toggled.connect(lambda checked: self.last.setEnabled(not checked))
        layout.addLayout(form)
        buttons = QHBoxLayout()
        for label, callback in (("担当範囲を設定", self.apply_range),
                                ("この話から", lambda: self.boundary(True)),
                                ("この話まで", lambda: self.boundary(False)),
                                ("別サイトの話に置換", self.replace_selection)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        listing = editor.draft.listings.get(target.key)
        self.rows = tuple(reversed(listing.rows)) if listing else ()
        if listing is None:
            layout.addWidget(QLabel("完全一覧未取得。「両サイトの全話一覧を取得」を押してください。"))
            self.setEnabled(False)
            return
        selected = {row.external_id for row in selected_rows(target, listing)}
        snapshot = editor.snapshot
        sources = {(source.site, source.discovery_key, source.external_id): source
                   for source in snapshot.sources.values()} if snapshot else {}
        self.table.setRowCount(len(self.rows))
        for index, row in enumerate(self.rows):
            text = f"{row.site_position}: {row.display_title or '話名未確認'}"
            self.first.addItem(text, row.external_id)
            self.last.addItem(text, row.external_id)
            source = sources.get((target.site, target.key, row.external_id))
            item = snapshot.items.get(source.item_id) if source and snapshot else None
            status = {"pending": "未取得", "completed": "取得済み", "skipped": "スキップ", "external": "外部取得"}
            values = (row.display_title or "話名未確認", status.get(item.status, item.status) if item else "Catalog未登録",
                      ("担当" if source.acquisition_enabled else "対象外") if source else "—", "担当" if row.external_id in selected else "対象外")
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                cell.setToolTip(f"{row.external_id}\n{row.url}")
                self.table.setItem(index, column, cell)
        self.last.setCurrentIndex(len(self.rows) - 1)
        scope = target.discovery_scope
        if selected:
            indices = [i for i, row in enumerate(self.rows) if row.external_id in selected]
            self.first.setCurrentIndex(min(indices))
            self.last.setCurrentIndex(max(indices))
        self.oldest.setChecked(scope is None or scope.through_url is None)
        self.latest.setChecked(scope is None or scope.from_url is None)

    def boundary(self, first):
        indices = sorted({index.row() for index in self.table.selectedIndexes()})
        if not indices:
            return
        combo, opened = (self.first, self.oldest) if first else (self.last, self.latest)
        combo.setCurrentIndex(indices[0] if first else indices[-1])
        opened.setChecked(False)
        self.apply_range()

    def apply_range(self):
        self.editor.change(lambda: self.editor.draft.set_range(self.target.key,
            None if self.oldest.isChecked() else self.first.currentData(),
            None if self.latest.isChecked() else self.last.currentData()))

    def replace_selection(self):
        indices = sorted({index.row() for index in self.table.selectedIndexes()})
        if not indices or indices != list(range(indices[0], indices[-1] + 1)):
            self.editor.status.setPlainText("置換元の連続する話を選択してください（Shiftで範囲選択）。")
            return
        self.editor.choose_replacement(self.target.key, self.rows[indices[0]].external_id,
                                       self.rows[indices[-1]].external_id)


class _WorkSearch(QLineEdit):
    def keyPressEvent(self, event):
        completing = self.completer() is not None and self.completer().popup().isVisible()
        super().keyPressEvent(event)
        # Enter without a completion must not trigger the dialog's Add button.
        if not completing and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            event.accept()


class WorkEditorDialog(QDialog):
    """One draft owns registration, selection, replacement and save."""

    fullRequested = Signal(object)  # (explicit key set, saved Watchlist revision)
    watchlistSaved = Signal()

    def __init__(self, watchlist_path, catalog_path, runtime_path, *, snapshot=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Watchlist：新規登録・担当範囲・部分置換")
        self.resize(1320, 900)
        self.path, self.catalog = Path(watchlist_path), Path(catalog_path)
        self.runtime_path, self.snapshot = runtime_path, snapshot
        self.service = WatchlistService(self.path)
        self.saved = tuple(self.service.list_targets())
        self.revision = self.service.revision()
        self.pool = QThreadPool(self)
        self.task = None
        self.dirty = False
        self.preview = None
        self.active_job = False
        self.fetch_queue = []
        self.pending_replacement = None
        self.draft = WorkDraft(self.saved, self.saved[0].work_key if self.saved else "")
        layout = QVBoxLayout(self)
        self.work_search = _WorkSearch()
        self.work_search.setPlaceholderText("作品を検索（作品名 / work_keyの一部）")
        self.work_search.setClearButtonEnabled(True)
        self.work_search_model = QStringListModel(self)
        self.work_completer = QCompleter(self.work_search_model, self)
        self.work_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.work_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.work_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.work_search.setCompleter(self.work_completer)
        self.work_completer.activated[str].connect(self._select_search_result)
        layout.addWidget(self.work_search)
        controls = QHBoxLayout()
        self.work_combo = QComboBox()
        self.work_combo.setMinimumWidth(260)
        self._fill_works()
        self.work_combo.currentIndexChanged.connect(self._switch_work)
        controls.addWidget(self.work_combo, 1)
        for label, callback in (("新しい作品", lambda: self.add_target(new_work=True)),
                                ("既存作品へサイト追加", self.add_target),
                                ("両サイトの全話一覧を取得", self.fetch_listings),
                                ("再読込", self.reload)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            controls.addWidget(button)
        layout.addLayout(controls)
        self.controls = QWidget()
        self.controls.setLayout(QVBoxLayout())
        self.panes = QSplitter(Qt.Orientation.Horizontal)
        self.controls.layout().addWidget(self.panes)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.controls)
        layout.addWidget(scroll, 3)
        layout.addWidget(QLabel("完成後の並び（ブロック単位。サイト間の話の同一性は利用者が確認）"))
        self.sequence = QListWidget()
        self.sequence.setMaximumHeight(155)
        layout.addWidget(self.sequence, 1)
        order_controls = QHBoxLayout()
        for label, callback in (("上へ", lambda: self.move_block(-1)),
                                ("下へ", lambda: self.move_block(1)),
                                ("区間を削除", self.delete_block),
                                ("区間の範囲を編集", self.edit_block)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            order_controls.addWidget(button)
        layout.addLayout(order_controls)
        self.status = QTextEdit()
        self.status.setReadOnly(True)
        self.status.setMaximumHeight(160)
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        self.preview_button, self.save_button = QPushButton("変更プレビュー"), QPushButton("Watchlistに保存")
        self.preview_button.clicked.connect(self.preview_edit)
        self.save_button.clicked.connect(self.save_edit)
        actions.addWidget(self.preview_button)
        actions.addWidget(self.save_button)
        layout.addLayout(actions)
        self._render()

    def _fill_works(self):
        self.work_combo.blockSignals(True)
        self.work_combo.clear()
        for key in dict.fromkeys(target.work_key for target in self.draft.targets):
            label = next(target.label for target in self.draft.targets if target.work_key == key)
            self.work_combo.addItem(f"{label} / {key}", key)
        self.work_combo.setCurrentIndex(self.work_combo.findData(self.draft.work_key))
        self.work_combo.blockSignals(False)
        self.work_search_model.setStringList([
            self.work_combo.itemText(index) for index in range(self.work_combo.count())
        ])

    def _select_search_result(self, text):
        if not self._guard():
            return
        index = self.work_combo.findText(text, Qt.MatchFlag.MatchExactly)
        if index >= 0:
            self.work_combo.setCurrentIndex(index)

    def _guard(self):
        if self.task is not None or self.active_job:
            self.status.setPlainText("処理またはJobの完了を待ってください。")
            return False
        return True

    def set_active_job(self, active):
        self.active_job = active
        self._enabled()

    def _enabled(self):
        enabled = self.task is None and not self.active_job
        self.controls.setEnabled(enabled)
        self.work_search.setEnabled(enabled)
        self.work_combo.setEnabled(enabled)
        self.preview_button.setEnabled(enabled)
        self.save_button.setEnabled(enabled and self.preview is not None)

    def _discard(self):
        return not self.dirty or QMessageBox.question(self, "未保存の変更", "未保存の変更を破棄しますか？",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Discard

    def _switch_work(self):
        key = self.work_combo.currentData()
        if key == self.draft.work_key:
            return
        if not self._guard() or not self._discard():
            self._fill_works()
            return
        self.draft = WorkDraft(self.saved, key)
        self.dirty, self.preview = False, None
        self._render()

    def reload(self):
        if not self._guard() or not self._discard():
            return
        key = self.draft.work_key
        self.saved = tuple(self.service.list_targets())
        self.revision = self.service.revision()
        self.draft = WorkDraft(self.saved, key if any(target.work_key == key for target in self.saved)
                               else self.saved[0].work_key if self.saved else "")
        self.dirty, self.preview = False, None
        self._fill_works()
        self._render()

    def add_target(self, _checked=False, *, new_work=False):
        if not self._guard():
            return False
        if new_work and not self._discard():
            return False
        dialog = AddWatchlistKeyDialog(self)
        if not new_work and self.draft.work_key:
            dialog.work_edit.setText(self.draft.work_key)
            dialog.work_edit.setReadOnly(True)
            if self.draft.members:
                dialog.label_edit.setText(self.draft.members[0].label)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        try:
            target = dialog.target()
            WatchlistService._validate_target(target, source="new target")
            if new_work:
                if any(old.work_key == target.work_key for old in self.saved):
                    raise ValueError("既存のwork_keyです。サイト追加を使用してください")
                self.draft = WorkDraft(self.saved, target.work_key)
            self.draft.add(target)
            self.dirty, self.preview = True, None
            self._fill_works()
            self._render()
            return True
        except ValueError as exc:
            self.status.setPlainText(str(exc))
            return False

    def change(self, action):
        if not self._guard():
            return
        try:
            result = action()
            self.dirty, self.preview = True, None
            self._render()
            counts = ""
            if isinstance(result, tuple) and len(result) == 2:
                counts = f" 置換元 {result[0]}話 → 置換先 {result[1]}話。"
                if result[0] != result[1]:
                    counts += "件数が異なるため後続の連番も変わります。"
            self.status.setPlainText("下書きを変更しました。保存はまだです。" + counts)
        except (ValueError, KeyError) as exc:
            self.status.setPlainText(str(exc))

    def _render(self):
        while self.panes.count():
            widget = self.panes.widget(0)
            widget.setParent(None)
            widget.deleteLater()
        self.sequence.clear()
        try:
            for target in self.draft.members:
                self.panes.addWidget(_SitePane(self, target))
            for block in self.draft.blocks():
                rows = self.draft.rows_for_block(block)
                self.sequence.addItem(f"{block.key}: {rows[0].display_title} → {rows[-1].display_title}"
                                      + (" [新着も含む]" if block.end_external_id is None else ""))
        except (KeyError, ValueError) as exc:
            self.status.setPlainText(f"完全一覧を取得してから範囲を編集してください。{exc}")
        self._enabled()

    def fetch_listings(self):
        if not self._guard():
            return
        self.preview = None
        self.fetch_queue = list(self.draft.members)
        self._next_listing()

    def _next_listing(self):
        if not self.fetch_queue:
            self._render()
            if self.pending_replacement:
                arguments, self.pending_replacement = self.pending_replacement, None
                self.choose_replacement(*arguments)
            return
        target = self.fetch_queue.pop(0)
        self.draft.listings.pop(target.key, None)
        self.status.setPlainText(f"読取専用一覧を取得中: {target.site} / {target.key}")
        task = _ListingWorker(target)
        task.signals.succeeded.connect(self._listing_ready)
        task.signals.failed.connect(self._failure)
        self.task = task
        self._enabled()
        self.pool.start(task)

    def _listing_ready(self, result):
        self.task = None
        try:
            self.draft.set_listing(result[1])
            self._next_listing()
        except ValueError as exc:
            self._failure(str(exc))

    def _failure(self, message):
        self.task = None
        self.fetch_queue = []
        self.pending_replacement = None
        self.preview = None
        self.status.setPlainText("停止: " + message)
        self._enabled()

    def _run(self, action, callback):
        task = _WorkTask(action)
        task.signals.success.connect(callback)
        task.signals.failure.connect(self._failure)
        self.task = task
        self._enabled()
        self.pool.start(task)

    def preview_edit(self):
        if not self._guard():
            return
        try:
            if any(target.archive_segments is not None for target in self.draft.members):
                self.draft.apply_blocks(self.draft.blocks())
            elif len(self.draft.members) > 1 and all(target.archive_order is None for target in self.draft.members):
                for order, target in enumerate(self.draft.members, 1):
                    self.draft.update(replace(target, archive_order=order))
                self.dirty = True
        except (KeyError, ValueError) as exc:
            self._failure(str(exc))
            return
        # Copy immutable inputs; UI cannot mutate the draft during this task.
        draft = WorkDraft(self.draft.targets, self.draft.work_key)
        draft.listings = dict(self.draft.listings)
        self._run(lambda: validate_work(draft, self.path, self.catalog, self.revision), self._preview_ready)

    def _preview_ready(self, result):
        self.task = None
        self.preview = result
        self.status.setPlainText(result.summary)
        self._enabled()

    def save_edit(self):
        if not self._guard() or self.preview is None:
            return
        preview = self.preview
        if preview.targets != self.draft.targets:
            self._failure("プレビュー後に下書きが変わりました")
            return
        before = self.saved

        def save():
            draft = WorkDraft(preview.targets, preview.work_key)
            draft.listings = {listing.target_key: listing for listing in preview.listings}
            with CatalogJobLock(self.catalog):
                current = validate_work(draft, self.path, self.catalog, preview.revision)
                if current.catalog_identity != preview.catalog_identity:
                    raise ValueError("Catalogが変更されました。再プレビューしてください")
                saved = self.service.apply_edit(preview.targets, expected_revision=preview.revision)
                revision = self.service.revision()
                if tuple(self.service.list_targets()) != saved:
                    raise ValueError("保存直後にWatchlistが変更されました。設定を再読込してください")
                return saved, revision, full_changed_keys(before, saved)
        self._run(save, self._saved)

    def _saved(self, result):
        self.task = None
        self.saved, self.revision, keys = result
        self.draft = WorkDraft(self.saved, self.draft.work_key)
        self.dirty, self.preview = False, None
        self._render()
        self.status.setPlainText("Watchlist保存済み。Catalogへの反映にはFull Discoveryが必要です。既存keyはそれまで以前の担当フラグが有効です。")
        self.watchlistSaved.emit()
        if keys:
            self.fullRequested.emit((keys, self.revision))

    def choose_replacement(self, source_key, first, last):
        if not self._guard():
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("置換先の話を選択")
        form = QFormLayout(dialog)
        destination, start, end = QComboBox(), QComboBox(), QComboBox()
        for target in self.draft.members:
            if target.key != source_key:
                destination.addItem(f"{target.site} / {target.key}", target.key)
        destination.addItem("新規サイトを追加…", None)
        def fill():
            start.clear()
            end.clear()
            listing = self.draft.listings.get(destination.currentData())
            if listing:
                for row in reversed(listing.rows):
                    start.addItem(row.display_title or row.external_id, row.external_id)
                    end.addItem(row.display_title or row.external_id, row.external_id)
        destination.currentIndexChanged.connect(fill)
        fill()
        form.addRow("置換先", destination)
        form.addRow("開始話", start)
        form.addRow("終了話", end)
        form.addRow(QLabel("話数の同一性・分割話の対応は自分で確認してください。件数が違っても置換できます。"))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        key = destination.currentData()
        if key is None:
            if self.add_target():
                self.pending_replacement = source_key, first, last
                self.fetch_listings()
            return
        if start.currentData() is None or end.currentData() is None:
            self.status.setPlainText("置換先の完全一覧を先に取得してください。")
            return
        self.change(lambda: self.draft.replace_range(source_key, first, last, key, start.currentData(), end.currentData()))

    def move_block(self, direction):
        index = self.sequence.currentRow()
        def move():
            blocks = self.draft.blocks()
            if not 0 <= index + direction < len(blocks) or index < 0:
                raise ValueError("移動する区間を選択してください")
            blocks[index], blocks[index + direction] = blocks[index + direction], blocks[index]
            self.draft.apply_blocks(blocks)
        self.change(move)
        self.sequence.setCurrentRow(index + direction)

    def delete_block(self):
        index = self.sequence.currentRow()
        def remove():
            blocks = self.draft.blocks()
            if not 0 <= index < len(blocks):
                raise ValueError("削除する区間を選択してください")
            blocks.pop(index)
            self.draft.apply_blocks(blocks)
        self.change(remove)

    def edit_block(self):
        index = self.sequence.currentRow()
        if index < 0 or not self._guard():
            return
        blocks = self.draft.blocks()
        block = blocks[index]
        dialog = QDialog(self)
        dialog.setWindowTitle("区間の範囲を編集")
        form = QFormLayout(dialog)
        start, end = QComboBox(), QComboBox()
        start.addItem("最古から", None)
        end.addItem("新着も含める", None)
        for row in reversed(self.draft.listings[block.key].rows):
            for combo in (start, end):
                combo.addItem(row.display_title or row.external_id, row.external_id)
        start.setCurrentIndex(start.findData(block.start_external_id))
        end.setCurrentIndex(end.findData(block.end_external_id))
        form.addRow("開始", start)
        form.addRow("終了", end)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            blocks[index] = replace(block, start_external_id=start.currentData(), end_external_id=end.currentData())
            self.change(lambda: self.draft.apply_blocks(blocks))

    def _close_guard(self):
        # MainWindow owns background jobs; only this dialog's task needs it open.
        if self.task is not None:
            self.status.setPlainText("この画面の処理が完了するまで待ってください。")
            return False
        return True

    def reject(self):
        if self._close_guard() and self._discard():
            super().reject()

    def closeEvent(self, event):
        if not self._close_guard() or not self._discard():
            event.ignore()
        else:
            event.accept()
