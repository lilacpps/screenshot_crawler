"""Main window and optional GUI command for the local inventory viewer."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSplitter,
    QStyle,
    QStyleOptionViewItem,
    QToolBar,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from screenshot_crawler.management.inventory import InventoryService

from .details import DetailPane
from .model import InventoryTreeModel, StatusFilter, ViewMode


class _LoadSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)


class _LoadWorker(QRunnable):
    def __init__(self, catalog_path: str, watchlist_path: str, runtime_path: str) -> None:
        super().__init__()
        self.catalog_path = catalog_path
        self.watchlist_path = watchlist_path
        self.runtime_path = runtime_path
        self.signals = _LoadSignals()

    @Slot()
    def run(self) -> None:
        try:
            snapshot = InventoryService().load(
                self.catalog_path,
                self.watchlist_path,
                runtime_path=self.runtime_path,
            )
        except Exception as exc:  # noqa: BLE001 - user-facing load diagnostic
            self.signals.failed.emit(str(exc) or exc.__class__.__name__)
        else:
            self.signals.succeeded.emit(snapshot)


class InventoryTreeView(QTreeView):
    """Emit node activation separately from checkbox toggling."""

    nodeClicked = Signal(object)
    sortRequested = Signal(int, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._checkbox_press = False

    def mousePressEvent(self, event: Any) -> None:
        index = self.indexAt(event.position().toPoint())
        self._checkbox_press = self._in_checkbox(index, event.position().toPoint())
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:
        index = self.indexAt(event.position().toPoint())
        super().mouseReleaseEvent(event)
        if not self._checkbox_press and index.isValid():
            self.nodeClicked.emit(index)
        self._checkbox_press = False

    def _in_checkbox(self, index: Any, point: Any) -> bool:
        if not index.isValid() or index.column() != 0:
            return False
        option = QStyleOptionViewItem()
        # ``initStyleOption`` belongs to QStyledItemDelegate.  QTreeView has
        # no compatible two-argument overload on supported Qt versions, so
        # obtain the actual delegate option before asking the style for the
        # check-indicator hit rectangle.
        delegate = self.itemDelegateForIndex(index)
        delegate.initStyleOption(option, index)
        option.rect = self.visualRect(index)
        rect = self.style().subElementRect(QStyle.SubElement.SE_ItemViewItemCheckIndicator, option, self)
        return rect.contains(point)

    def sortByColumn(self, column: int, order: Qt.SortOrder) -> None:
        self.sortRequested.emit(column, order)


class MainWindow(QMainWindow):
    """Read-only inventory browser.

    ``auto_load=False`` is useful for tests and for callers that already have
    a snapshot.  ``set_snapshot`` never writes any of the input files.
    """

    def __init__(
        self,
        catalog_path: str | Path,
        watchlist_path: str | Path,
        runtime_path: str | Path = "crawler.yaml",
        *,
        auto_load: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.catalog_path = str(catalog_path)
        self.watchlist_path = str(watchlist_path)
        self.runtime_path = str(runtime_path)
        self._closed = False
        self._loading = False
        self._worker: _LoadWorker | None = None
        self._initial_expand_done = False
        self.thread_pool = QThreadPool.globalInstance()
        # Keep the model owned by the window.  This gives Qt a GUI-thread
        # lifetime for all model resets while a worker may still be delivering
        # its queued load result.
        self.model = InventoryTreeModel(parent=self)
        self.tree = InventoryTreeView()
        self.tree.setModel(self.model)
        self.tree.setAlternatingRowColors(True)
        # Route header sorting through MainWindow so reset notifications can
        # restore expansion and the stable focused node.  QTreeView's native
        # sorting path can call QAbstractItemModel.sort() directly, bypassing
        # that restoration logic.
        self.tree.setSortingEnabled(False)
        self.tree.header().setSectionsClickable(True)
        self.tree.header().setSortIndicatorShown(True)
        self.tree.header().sortIndicatorChanged.connect(self._on_sort_requested)
        self.tree.setUniformRowHeights(True)
        self.tree.setColumnWidth(0, 300)
        for column, width in ((1, 120), (2, 90), (3, 100), (4, 100), (5, 120), (6, 145), (7, 90), (8, 80), (9, 100)):
            self.tree.setColumnWidth(column, width)
        self.tree.nodeClicked.connect(self._on_tree_clicked)
        self.tree.sortRequested.connect(self._on_sort_requested)
        self.detail = DetailPane(self)
        self.detail_pane = self.detail
        self.model.focusNodeChanged.connect(self._on_focus_changed)
        self.model.checkedKeysChanged.connect(self._on_checked_changed)
        self.model.selectionRemoved.connect(self._on_selection_removed)
        self.detail.set_snapshot(None)
        self.detail.keySelected.connect(self._focus_key_from_detail)
        self._build_ui()
        self.resize(1400, 850)
        self.setMinimumSize(980, 600)
        if auto_load:
            self.reload()

    def _build_ui(self) -> None:
        self.setWindowTitle("Screenshot Crawler — 作品管理（閲覧専用）")
        root = QWidget(self)
        outer = QVBoxLayout(root)

        paths = QHBoxLayout()
        paths.addWidget(QLabel("Catalog"))
        self.catalog_edit = QLineEdit(self.catalog_path)
        self.catalog_edit.setReadOnly(True)
        paths.addWidget(self.catalog_edit, 2)
        self.catalog_browse = QPushButton("参照")
        self.catalog_browse.clicked.connect(self._choose_catalog)
        paths.addWidget(self.catalog_browse)
        paths.addWidget(QLabel("Watchlist"))
        self.watchlist_edit = QLineEdit(self.watchlist_path)
        self.watchlist_edit.setReadOnly(True)
        paths.addWidget(self.watchlist_edit, 2)
        self.watchlist_browse = QPushButton("参照")
        self.watchlist_browse.clicked.connect(self._choose_watchlist)
        paths.addWidget(self.watchlist_browse)
        paths.addWidget(QLabel("Runtime"))
        self.runtime_edit = QLineEdit(self.runtime_path)
        self.runtime_edit.setReadOnly(True)
        paths.addWidget(self.runtime_edit, 1)
        self.runtime_browse = QPushButton("参照")
        self.runtime_browse.clicked.connect(self._choose_runtime)
        paths.addWidget(self.runtime_browse)
        self._path_controls = (self.catalog_browse, self.watchlist_browse, self.runtime_browse)
        outer.addLayout(paths)

        toolbar = QToolBar()
        toolbar.setMovable(False)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("サイト別", ViewMode.SITE)
        self.mode_combo.addItem("作品別", ViewMode.WORK)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        toolbar.addWidget(QLabel("表示: "))
        toolbar.addWidget(self.mode_combo)
        toolbar.addSeparator()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("作品名 / label / key / site を検索")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._on_search_changed)
        toolbar.addWidget(self.search_edit)
        self.filter_combo = QComboBox()
        filters = (
            ("すべて", StatusFilter.ALL),
            ("直取候補あり", StatusFilter.DIRECT),
            ("Quota候補あり", StatusFilter.QUOTA),
            ("未取得あり", StatusFilter.UNFINISHED),
            ("要確認", StatusFilter.REVIEW),
            ("担当外あり", StatusFilter.OUT_OF_SCOPE),
        )
        for label, value in filters:
            self.filter_combo.addItem(label, value)
        self.filter_combo.currentIndexChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self.filter_combo)
        self.reload_button = QPushButton("再読込")
        self.reload_button.clicked.connect(self.reload)
        toolbar.addWidget(self.reload_button)
        self.expand_button = QPushButton("全展開")
        self.expand_button.clicked.connect(self.tree.expandAll)
        toolbar.addWidget(self.expand_button)
        self.collapse_button = QPushButton("全折畳")
        self.collapse_button.clicked.connect(self.tree.collapseAll)
        toolbar.addWidget(self.collapse_button)
        toolbar.addWidget(QLabel("  Catalog / Watchlist 読み取り専用"))
        outer.addWidget(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.tree)
        splitter.addWidget(self.detail)
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([960, 420])
        outer.addWidget(splitter, 1)

        bottom = QHBoxLayout()
        self.selection_label = QLabel("0 key選択中")
        bottom.addWidget(self.selection_label)
        self.clear_selection_button = QPushButton("選択解除")
        self.clear_selection_button.clicked.connect(self._clear_selection)
        bottom.addWidget(self.clear_selection_button)
        bottom.addStretch(1)
        for name in ("Discover", "Batch Run", "Grant-only"):
            button = QPushButton(name)
            button.setObjectName(name.lower().replace(" ", "_") + "_button")
            button.setEnabled(False)
            button.setToolTip("P1では実行できません（閲覧専用）")
            bottom.addWidget(button)
        outer.addLayout(bottom)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color:#a33; padding:3px;")
        outer.addWidget(self.error_label)
        self.setCentralWidget(root)
        self.statusBar().showMessage("読み込み待ち")

    # --- loading ---------------------------------------------------------------

    def _choose_catalog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Catalog v7を選択", self.catalog_path, "SQLite (*.sqlite *.db);;All files (*)")
        if path:
            self.catalog_path = path
            self.catalog_edit.setText(path)

    def _choose_watchlist(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Watchlistを選択", self.watchlist_path, "YAML (*.yaml *.yml);;All files (*)")
        if path:
            self.watchlist_path = path
            self.watchlist_edit.setText(path)

    def _choose_runtime(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Runtime設定を選択", self.runtime_path, "YAML (*.yaml *.yml);;All files (*)")
        if path:
            self.runtime_path = path
            self.runtime_edit.setText(path)

    def reload(self) -> None:
        if self._closed or self._loading:
            return
        self._loading = True
        self.reload_button.setEnabled(False)
        for control in self._path_controls:
            control.setEnabled(False)
        self.statusBar().showMessage("読み込み中…")
        worker = _LoadWorker(self.catalog_path, self.watchlist_path, self.runtime_path)
        self._worker = worker
        worker.signals.succeeded.connect(self._load_succeeded, Qt.ConnectionType.QueuedConnection)
        worker.signals.failed.connect(self._load_failed, Qt.ConnectionType.QueuedConnection)
        self.thread_pool.start(worker)

    @Slot(object)
    def _load_succeeded(self, snapshot: object) -> None:
        if self._closed:
            return
        self._loading = False
        self.reload_button.setEnabled(True)
        for control in self._path_controls:
            control.setEnabled(True)
        self.set_snapshot(snapshot)
        self.error_label.clear()
        self.statusBar().showMessage(f"読み込み完了: {snapshot.loaded_at.astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}")

    @Slot(str)
    def _load_failed(self, message: str) -> None:
        if self._closed:
            return
        self._loading = False
        self.reload_button.setEnabled(True)
        for control in self._path_controls:
            control.setEnabled(True)
        prefix = "読み込み失敗（前回の表示は古い可能性があります）: " if self.model.snapshot else "読み込み失敗: "
        self.error_label.setText(prefix + message)
        self.statusBar().showMessage("読み込みに失敗しました")

    def set_snapshot(self, snapshot: object) -> None:
        old_focus = self.model._nodes.get(self.model.focused_node_id or "")
        old_focus_key = old_focus.key_identity if old_focus and old_focus.kind == "key" else None
        old_focus_work = old_focus.work_key if old_focus and old_focus.kind == "work" else None
        expanded_ids = self._expanded_node_ids()
        self.model.set_snapshot(snapshot)
        self.detail.set_snapshot(snapshot)
        if not self._initial_expand_done:
            self.tree.expandToDepth(1)
            self._initial_expand_done = True
        else:
            self._restore_expanded(expanded_ids)
        focus = self.model.node_by_key_identity(old_focus_key) if old_focus_key else None
        if focus is None and old_focus_work:
            focus = next((node for node in self.model._nodes.values() if node.kind == "work" and node.work_key == old_focus_work), None)
        if focus is not None:
            self.model.focus_node(focus)
        self._on_checked_changed(self.model.checked_keys)

    def _expanded_node_ids(self) -> set[str]:
        expanded: set[str] = set()
        def walk(parent_index: Any) -> None:
            for row in range(self.model.rowCount(parent_index)):
                index = self.model.index(row, 0, parent_index)
                node = self.model.node_for_index(index)
                if node is not None and self.tree.isExpanded(index):
                    expanded.add(node.node_id)
                walk(index)
        walk(self.model.index(-1, -1))
        return expanded

    def _restore_expanded(self, node_ids: set[str]) -> None:
        for node_id in node_ids:
            index = self.model.index_for_node(node_id)
            if index.isValid():
                self.tree.expand(index)

    # --- interaction -----------------------------------------------------------

    def _on_mode_changed(self, index: int) -> None:
        self.model.set_view_mode(self.mode_combo.itemData(index))
        focused = self.model.focused_node_id
        if focused:
            current = self.model.index_for_node(focused)
            if current.isValid():
                parent = current.parent()
                while parent.isValid():
                    self.tree.expand(parent)
                    parent = parent.parent()
                self.tree.setCurrentIndex(current)

    def _on_filter_changed(self, index: int) -> None:
        focused = self.model.focused_node_id
        expanded = self._expanded_node_ids()
        self.model.set_status_filter(self.filter_combo.itemData(index))
        self._restore_expanded(expanded)
        if focused:
            current = self.model.index_for_node(focused)
            if current.isValid():
                self.tree.setCurrentIndex(current)

    def _on_search_changed(self, text: str) -> None:
        focused = self.model.focused_node_id
        expanded = self._expanded_node_ids()
        self.model.set_search(text)
        self._restore_expanded(expanded)
        if focused:
            current = self.model.index_for_node(focused)
            if current.isValid():
                self.tree.setCurrentIndex(current)

    def _on_sort_requested(self, column: int, order: Qt.SortOrder) -> None:
        focused = self.model.focused_node_id
        expanded = self._expanded_node_ids()
        self.model.sort(column, order)
        self._restore_expanded(expanded)
        if focused:
            current = self.model.index_for_node(focused)
            if current.isValid():
                self.tree.setCurrentIndex(current)

    def _on_tree_clicked(self, index: Any) -> None:
        node = self.model.node_for_index(index)
        if node is None:
            return
        self.model.focus_node(node)

    def _on_focus_changed(self, node: object) -> None:
        if node is None:
            return
        key = self.model.key_inventory(node.key_identity) if node.kind == "key" and node.key_identity else None
        self.detail.set_node(node, key, self.model.summary_for(node))

    def _focus_key_from_detail(self, identity: str) -> None:
        node = self.model.node_by_key_identity(identity)
        if node is not None:
            self.model.focus_node(node)
            index = self.model.index_for_node(node.node_id)
            if index.isValid():
                self.tree.setCurrentIndex(index)
                self.tree.scrollTo(index)

    def _on_checked_changed(self, checked: object) -> None:
        self.selection_label.setText(f"{len(checked)} key選択中")

    def _on_selection_removed(self, removed: object) -> None:
        self.statusBar().showMessage(f"再読込で {len(removed)} key の選択を解除しました")

    def _clear_selection(self) -> None:
        self.model.checked_keys.clear()
        self.model._emit_check_updates()

    def closeEvent(self, event: Any) -> None:
        self._closed = True
        # QThreadPool owns the runnable; waiting here would make closing a
        # large catalog block the GUI.  Its queued signals are ignored above.
        event.accept()


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Open the read-only Screenshot Crawler inventory GUI")
    parser.add_argument("--catalog", default="catalog.sqlite", help="Catalog v7 SQLite path")
    parser.add_argument("--watchlist", default="watchlist.yaml", help="Watchlist YAML path")
    parser.add_argument("--runtime", default="crawler.yaml", help="Runtime policy configuration path")
    args = parser.parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = MainWindow(args.catalog, args.watchlist, args.runtime)
    window.show()
    return app.exec()

