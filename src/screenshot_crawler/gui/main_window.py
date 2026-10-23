"""Main window and optional GUI command for the local inventory viewer."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStyle,
    QStyleOptionViewItem,
    QToolBar,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from screenshot_crawler.management.execution import (
    ExecutionPlanService,
    ExecutionSelection,
    JobExecutionRequest,
    execution_request_payload,
)
from screenshot_crawler.management.inventory import InventoryService, default_policy_registry

from .details import DetailPane
from .execution_dialog import ExecutionPreviewDialog
from .jobs_page import JobsPage
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


class _ExecutionSignals(QObject):
    succeeded = Signal(str)
    failed = Signal(str)


class _ExecutionWorker(QRunnable):
    """Run the existing CLI in a worker thread after GUI confirmation."""

    def __init__(self, request: JobExecutionRequest) -> None:
        super().__init__()
        self.request = request
        self.signals = _ExecutionSignals()

    @Slot()
    def run(self) -> None:
        try:
            if not self.request.selected_keys:
                raise ValueError("no Watchlist keys selected")
            command = [
                sys.executable,
                "-m",
                "screenshot_crawler.execution_worker",
                "--request-json",
                json.dumps(execution_request_payload(self.request), ensure_ascii=False),
            ]
            completed = subprocess.run(
                command, capture_output=True, text=True, check=False
            )
            output = completed.stdout + completed.stderr
            if completed.returncode != 0:
                raise RuntimeError(
                    f"execution failed (exit={completed.returncode}): {output.strip()}"
                )
            self.signals.succeeded.emit(output)
        except Exception as exc:  # noqa: BLE001 - user-facing worker boundary
            self.signals.failed.emit(str(exc) or type(exc).__name__)



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
        management_path: str | Path = "output/management/management.sqlite",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.catalog_path = str(catalog_path)
        self.watchlist_path = str(watchlist_path)
        self.runtime_path = str(runtime_path)
        self.management_path = str(management_path)
        self._closed = False
        self._loading = False
        self._worker: _LoadWorker | None = None
        self._job_store = None
        self._job_controller = None
        self._jobs_page: JobsPage | None = None
        self._rerun_original_id: str | None = None
        self._pending_rerun: tuple[str, frozenset[str], str] | None = None
        self._session_job_ids: list[str] = []
        self._initial_expand_done = False
        self.thread_pool = QThreadPool.globalInstance()
        self._job_poll_timer = QTimer(self)
        self._job_poll_timer.setInterval(500)
        self._job_poll_timer.timeout.connect(self._poll_jobs)
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
        self.jobs_button = QPushButton("ジョブ")
        self.jobs_button.setObjectName("jobs_button")
        self.jobs_button.clicked.connect(self._open_jobs)
        toolbar.addWidget(self.jobs_button)
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
        self.discover_mode_combo = QComboBox()
        self.discover_mode_combo.setObjectName("discover_mode_combo")
        self.discover_mode_combo.addItem("Discover Full", "full")
        self.discover_mode_combo.addItem("Discover Incremental", "incremental")
        self.discover_mode_combo.setToolTip("Discoverのモード")
        bottom.addWidget(self.discover_mode_combo)
        bottom.addWidget(QLabel("最大件数:"))
        self.execution_limit_spin = QSpinBox()
        self.execution_limit_spin.setObjectName("execution_limit_spin")
        self.execution_limit_spin.setRange(0, 1_000_000)
        self.execution_limit_spin.setSpecialValueText("無制限")
        self.execution_limit_spin.setToolTip("Batch / Grant-only の最大候補数。0は無制限")
        bottom.addWidget(self.execution_limit_spin)
        self.site_resource_controls = QWidget()
        self.site_resource_layout = QHBoxLayout(self.site_resource_controls)
        self.site_resource_layout.setContentsMargins(0, 0, 0, 0)
        self.site_resource_scroll = QScrollArea()
        self.site_resource_scroll.setWidgetResizable(True)
        self.site_resource_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.site_resource_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.site_resource_scroll.setWidget(self.site_resource_controls)
        self.site_resource_scroll.setMinimumWidth(180)
        self.site_resource_scroll.setMaximumWidth(420)
        self.site_resource_scroll.setFixedHeight(42)
        self.site_resource_scroll.setToolTip("選択中サイトごとのGrant-only Resource（横スクロール可）")
        bottom.addWidget(self.site_resource_scroll, 1)
        self.discover_button = QPushButton("Discover")
        self.discover_button.setObjectName("discover_button")
        self.discover_button.setToolTip("選択keyをDiscover")
        self.discover_button.clicked.connect(lambda: self._show_execution_preview("discover"))
        bottom.addWidget(self.discover_button)
        self.batch_run_button = QPushButton("Batch Run")
        self.batch_run_button.setObjectName("batch_run_button")
        self.batch_run_button.setToolTip("選択keyをBatch実行")
        self.batch_run_button.clicked.connect(lambda: self._show_execution_preview("batch"))
        bottom.addWidget(self.batch_run_button)
        self.grant_only_button = QPushButton("Grant-only")
        self.grant_only_button.setObjectName("grant-only_button")
        self.grant_only_button.setToolTip("選択keyのGrant-only（権利消費の可能性あり）")
        self.grant_only_button.clicked.connect(lambda: self._show_execution_preview("grant_only"))
        bottom.addWidget(self.grant_only_button)
        for button in (self.discover_button, self.batch_run_button, self.grant_only_button):
            button.setEnabled(False)
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
        pending = self._pending_rerun
        self._pending_rerun = None
        if pending is not None:
            job_id, selected, action = pending
            available = {key.identity for key in snapshot.keys}
            if not selected.issubset(available):
                missing = ", ".join(sorted(selected - available))
                self.error_label.setText(f"再計画停止: keyが最新Watchlistにありません: {missing}")
                self.statusBar().showMessage("再計画を停止しました")
                return
            self.model.set_checked_keys(set(selected))
            self._rerun_original_id = job_id
            self._show_execution_preview(action)

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
        if self._pending_rerun is not None:
            self._pending_rerun = None
            self._rerun_original_id = None
            self.error_label.setText(self.error_label.text() + " / 再計画は停止しました")

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
        self._refresh_site_resource_controls()

    def _refresh_site_resource_controls(self) -> None:
        """Show resource selectors only for currently selected sites."""

        previous = {
            site: combo.currentData()
            for site, combo in getattr(self, "_site_grant_resource_combos", {}).items()
        }
        while self.site_resource_layout.count():
            child = self.site_resource_layout.takeAt(0)
            if child.widget() is not None:
                child.widget().deleteLater()
        self._site_grant_resource_combos: dict[str, QComboBox] = {}
        self._site_resource_invalid: dict[str, str] = {}
        snapshot = self.model.snapshot
        if snapshot is None:
            return
        selected_sites = sorted(
            {
                key.site
                for key in snapshot.keys
                if key.identity in self.model.selected_keys
            }
        )
        for site in selected_sites:
            overview = snapshot.resources.get(site)
            if overview is None:
                continue
            label = QLabel(f"{site}:")
            combo = QComboBox()
            combo.setObjectName(f"grant_resource_{site}")
            combo.addItem("all", "all")
            for resource in overview.grant_resources:
                combo.addItem(resource, resource)
            if site in previous:
                prior = previous[site]
                if combo.findData(prior) >= 0:
                    combo.setCurrentIndex(combo.findData(prior))
                elif prior:
                    combo.insertItem(0, f"{prior} (unsupported)", prior)
                    combo.setCurrentIndex(0)
                    self._site_resource_invalid[site] = str(prior)
            combo.currentIndexChanged.connect(
                lambda _index, selected_site=site: self._on_site_resource_changed(selected_site)
            )
            self.site_resource_layout.addWidget(label)
            self.site_resource_layout.addWidget(combo)
            self._site_grant_resource_combos[site] = combo

    def _on_site_resource_changed(self, site: str) -> None:
        """Clear a stale-resource blocker only after an explicit new choice."""

        combo = self._site_grant_resource_combos.get(site)
        if combo is None:
            return
        invalid = self._site_resource_invalid.get(site)
        if invalid is not None and combo.currentData() != invalid:
            self._site_resource_invalid.pop(site, None)

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
        if self.model.snapshot is not None:
            self._refresh_site_resource_controls()
        enabled = bool(checked) and self.model.snapshot is not None and not self._loading
        for button in (self.discover_button, self.batch_run_button, self.grant_only_button):
            button.setEnabled(enabled)

    def _show_execution_preview(self, action: str) -> None:
        snapshot = self.model.snapshot
        if snapshot is None or not self.model.selected_keys:
            return
        service = ExecutionPlanService()
        resource = None
        limit = self.execution_limit_spin.value() or None
        selection = ExecutionSelection(self.model.selected_keys)
        if action in {"batch", "grant_only"}:
            by_site: dict[str, list[str]] = {}
            for key in snapshot.keys:
                if key.identity in selection.selected_keys and key.target is not None:
                    by_site.setdefault(key.site, []).append(key.identity)
            previews = []
            resource_blockers = tuple(
                f"{site}: no supported Grant-only Resource selector"
                for site in sorted(by_site)
                if action == "grant_only" and site not in self._site_grant_resource_combos
            ) + tuple(
                f"{site}: selected Resource {value!r} is no longer supported"
                for site, value in self._site_resource_invalid.items()
                if site in by_site and action == "grant_only"
            )
            try:
                policies = default_policy_registry()
                for site, keys in sorted(by_site.items()):
                    site_resource = (
                        self._site_grant_resource_combos[site].currentData()
                        if action == "grant_only"
                        else None
                    )
                    previews.append(
                        service.preview_batch(
                            snapshot.catalog_path,
                            snapshot.watchlist_path,
                            policies,
                            site=site,
                            selected_keys=keys,
                            resource=site_resource,
                            runtime_path=self.runtime_path,
                            library_dir=str(Path("output/Books").resolve()),
                            limit=limit,
                            output_root=str(Path("output/batch").resolve()),
                            metrics_root=str(Path("output/metrics").resolve()),
                            env_file=str(Path(".env").resolve()),
                        )
                    )
            except Exception as exc:  # noqa: BLE001 - render a blocking preview
                preview = service.preview(
                    snapshot,
                    selection,
                    action=action,
                    resource=resource,
                    limit=limit,
                    runtime_path=self.runtime_path,
                    env_file=str(Path(".env").resolve()),
                    output_root=str(Path("output/batch").resolve()),
                    library_dir=str(Path("output/Books").resolve()),
                    metrics_root=str(Path("output/metrics").resolve()),
                )
                preview = replace(
                    preview,
                    blockers=(*preview.blockers, f"preflight failed: {exc}"),
                )
            else:
                base = previews[0] if previews else service.preview(
                    snapshot,
                    selection,
                    action=action,
                    resource=resource,
                    limit=limit,
                    runtime_path=self.runtime_path,
                    env_file=str(Path(".env").resolve()),
                    output_root=str(Path("output/batch").resolve()),
                    library_dir=str(Path("output/Books").resolve()),
                    metrics_root=str(Path("output/metrics").resolve()),
                )
                preview = replace(
                    base,
                    selection=selection,
                    sites=tuple(sorted(by_site)),
                    candidate_count=sum(item.candidate_count for item in previews),
                    skipped_count=sum(item.skipped_count for item in previews),
                    skipped=tuple(value for item in previews for value in item.skipped),
                    blockers=resource_blockers + tuple(
                        f"{site}: {value}"
                        for site, item in zip(sorted(by_site), previews)
                        for value in item.blockers
                    ),
                    warnings=tuple(
                        f"{site}: {value}"
                        for site, item in zip(sorted(by_site), previews)
                        for value in item.warnings
                    ),
                    resources_by_site=tuple(
                        (site, item.resource or "all")
                        for site, item in sorted(zip(sorted(by_site), previews))
                    )
                    if action == "grant_only"
                    else (),
                    work_names=tuple(
                        sorted({value for item in previews for value in item.work_names})
                    ),
                    fingerprint=(
                        previews[0].fingerprint
                        if len(previews) == 1
                        else hashlib.sha256(
                            json.dumps(
                                [item.fingerprint for item in previews],
                                separators=(",", ":"),
                            ).encode()
                        ).hexdigest()
                    ),
                )
        else:
            preview = service.preview(
                snapshot,
                selection,
                action="discover",
                mode=self.discover_mode_combo.currentData(),
                limit=limit,
                runtime_path=self.runtime_path,
                env_file=str(Path(".env").resolve()),
                output_root=str(Path("output/batch").resolve()),
                library_dir=str(Path("output/Books").resolve()),
                metrics_root=str(Path("output/metrics").resolve()),
            )
        request = (
            replace(
                preview.request(snapshot),
                runtime_path=self.runtime_path,
                env_file=str(Path(".env").resolve()),
                cdp_endpoint=None,
                output_root=str(Path("output/batch").resolve()),
                library_dir=str(Path("output/Books").resolve()),
                metrics_root=str(Path("output/metrics").resolve()),
            )
            if preview.can_confirm
            else None
        )
        dialog = ExecutionPreviewDialog(preview, request, self)
        dialog.requestConfirmed.connect(self._start_execution)
        if dialog.exec() == QDialog.DialogCode.Accepted and request is not None:
            self.statusBar().showMessage("実行を開始しました")

    @Slot(object)
    def _start_execution(self, request: object) -> None:
        if not isinstance(request, JobExecutionRequest):
            return
        controller = self._ensure_jobs()
        job_id = controller.queue(request, original_job_id=self._rerun_original_id)
        self._session_job_ids.append(job_id)
        self._rerun_original_id = None
        if controller.active_job_id is None:
            controller.start_job(job_id)
        self.statusBar().showMessage(f"ジョブをキューしました: {job_id}")

    @Slot(str)
    def _execution_succeeded(self, output: str) -> None:
        self._on_checked_changed(self.model.selected_keys)
        self.statusBar().showMessage("実行完了")
        self.error_label.setText(output[-4000:] if output else "")

    @Slot(str)
    def _execution_failed(self, message: str) -> None:
        self._on_checked_changed(self.model.selected_keys)
        self.statusBar().showMessage("実行失敗")
        self.error_label.setText("実行失敗: " + message)

    def _ensure_jobs(self):
        if self._job_controller is None:
            from screenshot_crawler.management.job_controller import JobController
            from screenshot_crawler.management.jobs import JobStore

            self._job_store = JobStore(self.management_path)
            self._job_controller = JobController(self._job_store)
            self._job_controller.reconcile()
            self._jobs_page = JobsPage(self._job_store, self._job_controller, self)
            self._jobs_page.rerunRequested.connect(self._rerun_job)
            self._job_poll_timer.start()
        return self._job_controller

    def _open_jobs(self) -> None:
        self._ensure_jobs()
        assert self._jobs_page is not None
        self._jobs_page.refresh()
        self._jobs_page.resize(900, 650)
        self._jobs_page.show()
        self._jobs_page.raise_()
        self._jobs_page.activateWindow()

    def _poll_jobs(self) -> None:
        if self._job_controller is None:
            return
        state = self._job_controller.poll()
        if self._jobs_page is not None:
            self._jobs_page.refresh()
        if state is not None:
            self._on_checked_changed(self.model.selected_keys)
            self.statusBar().showMessage(f"ジョブ終了: {state}")
            self.reload()
            # A failed/partial/interrupted job may have an unknown resource
            # outcome. Never advance the session queue into an automatic retry;
            # the operator must explicitly review and re-plan it.
            if state != "succeeded":
                self.statusBar().showMessage(f"ジョブ停止: {state}（自動再試行なし）")
                return
            if self._job_controller.active_job_id is None:
                for queued_id in tuple(self._session_job_ids):
                    try:
                        if self._job_store is not None and self._job_store.get_job(queued_id)["state"] == "queued":
                            self._job_controller.start_job(queued_id)
                            break
                    except (KeyError, RuntimeError):
                        continue

    def _rerun_job(self, job_id: str) -> None:
        if self._job_store is None:
            return
        payload = self._job_store.request_for(job_id)
        selected = payload.get("selected_keys")
        action = payload.get("action")
        if not isinstance(selected, list) or not isinstance(action, str):
            self.error_label.setText("再実行できないジョブ要求です")
            return
        self._pending_rerun = (job_id, frozenset(selected), action)
        self.reload()

    def _on_selection_removed(self, removed: object) -> None:
        self.statusBar().showMessage(f"再読込で {len(removed)} key の選択を解除しました")

    def _clear_selection(self) -> None:
        self.model.checked_keys.clear()
        self.model._emit_check_updates()

    def closeEvent(self, event: Any) -> None:
        if self._job_controller is not None and self._job_controller.active_job_id is not None:
            answer = QMessageBox.warning(
                self,
                "実行中ジョブ",
                "実行中のworkerがあります。協調停止を要求してGUIを閉じますか？",
                QMessageBox.StandardButton.Close | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Close:
                event.ignore()
                return
            self._job_controller.request_stop()
            self._closed = True
            # Keep the OS lease while the child is draining.  A newly opened
            # GUI will inspect the persisted identity and refuse a second
            # worker, even if this window is already gone.
        elif self._job_controller is not None:
            self._closed = True
            self._job_controller.close()
        else:
            self._closed = True
        # QThreadPool owns the runnable; waiting here would make closing a
        # large catalog block the GUI.  Its queued signals are ignored above.
        event.accept()


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Open the Screenshot Crawler inventory, execution, and job-management GUI"
    )
    parser.add_argument("--catalog", default="catalog.sqlite", help="Catalog v7 SQLite path")
    parser.add_argument("--watchlist", default="watchlist.yaml", help="Watchlist YAML path")
    parser.add_argument("--runtime", default="crawler.yaml", help="Runtime policy configuration path")
    parser.add_argument(
        "--management",
        default="output/management/management.sqlite",
        help="Separate persistent GUI job database path",
    )
    args = parser.parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = MainWindow(args.catalog, args.watchlist, args.runtime, management_path=args.management)
    window.show()
    return app.exec()

