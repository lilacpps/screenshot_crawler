"""Main window and optional GUI command for the local inventory viewer."""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
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
    JobExecutionRequest,
    execution_request_payload,
)
from screenshot_crawler.management.inventory import InventoryService

from .details import DetailPane
from .discovery_toggle import DiscoverySaveWorker, DiscoverySwitchDelegate, ToggleResult

# Kept as a module export for integrations that construct the legacy dialog;
# ordinary execution uses the compact QMessageBox confirmation below.
from .execution_dialog import ExecutionPreviewDialog  # noqa: F401
from .execution_monitor import ExecutionMonitor
from .jobs_page import JobsPage
from .model import (
    DISCOVERY_COLUMN,
    DISCOVERY_HELP,
    DISCOVERY_ROLE,
    InventoryTreeModel,
    StatusFilter,
    ViewMode,
)
from .watchlist_editor import WatchlistEditorPage

LOGGER = logging.getLogger(__name__)


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
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
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
        if not index.isValid():
            return False
        if index.column() == DISCOVERY_COLUMN:
            return (index.data(DISCOVERY_ROLE) is not None
                    and DiscoverySwitchDelegate.switch_rect(self.visualRect(index)).contains(point))
        if index.column() != 0:
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
    """Inventory browser with explicit Watchlist editing and selected execution.

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
        self._inventory_stale = False
        self._discovery_save_worker = None
        self._discovery_refresh = False
        self._discovery_notice = ""
        self._discovery_controls_state = None
        self._reload_again = False
        self._worker: _LoadWorker | None = None
        self._job_store = None
        self._job_controller = None
        self._jobs_page: JobsPage | None = None
        self._rerun_original_id: str | None = None
        self._pending_rerun: tuple[str, frozenset[str], str] | None = None
        self._pending_editor_full: str | None = None
        self._pending_work_full: tuple | None = None
        self._work_editor = None
        self._session_job_ids: list[str] = []
        self._monitor_followed_active_id: str | None = None
        self._initial_expand_done = False
        self.thread_pool = QThreadPool.globalInstance()
        self._job_poll_timer = QTimer(self)
        self._job_poll_timer.setInterval(500)
        self._job_poll_timer.timeout.connect(self._poll_jobs)
        # Keep the model owned by the window.  This gives Qt a GUI-thread
        # lifetime for all model resets while a worker may still be delivering
        # its queued load result.
        self.model = InventoryTreeModel(parent=self)
        self.model.discovery_guard = self._discovery_block_reason
        self.model.discoveryToggleRequested.connect(self._toggle_discovery)
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
        self.tree.setItemDelegateForColumn(DISCOVERY_COLUMN, DiscoverySwitchDelegate(self.tree))
        self.tree.setColumnWidth(DISCOVERY_COLUMN, 132)
        # Keep existing logical column identities for sort/count integrations.
        self.tree.header().moveSection(DISCOVERY_COLUMN, 1)
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
        self._discovery_controls_timer = QTimer(self)
        self._discovery_controls_timer.setInterval(250)
        self._discovery_controls_timer.timeout.connect(self._refresh_discovery_controls)
        self._discovery_controls_timer.start()
        self.resize(1400, 850)
        self.setMinimumSize(980, max(600, self.minimumHeight()))
        if auto_load:
            self.reload()

    def _build_ui(self) -> None:
        self.setWindowTitle("Screenshot Crawler — 作品管理")
        root = QWidget(self)
        root_layout = QVBoxLayout(root)
        emergency = QHBoxLayout()
        emergency.addStretch()
        self.emergency_stop_button = QPushButton("緊急停止")
        self.emergency_stop_button.setObjectName("emergency_stop_button")
        self.emergency_stop_button.setStyleSheet(
            "QPushButton { background:#b42318; color:white; font-weight:bold; padding:6px 18px; }"
            "QPushButton:disabled { background:#ddd; color:#777; }"
        )
        self.emergency_stop_button.setToolTip(
            "確認なしで実行中workerを強制停止。消費・出力状態は未確認となり、自動再試行しません。"
        )
        self.emergency_stop_button.setEnabled(False)
        self.emergency_stop_button.clicked.connect(self._emergency_stop)
        emergency.addWidget(self.emergency_stop_button)
        root_layout.addLayout(emergency)
        upper = QWidget(root)
        outer = QVBoxLayout(upper)
        outer.setContentsMargins(0, 0, 0, 0)

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
        self.watchlist_button = QPushButton("Watchlist管理")
        self.watchlist_button.setObjectName("watchlist_button")
        self.watchlist_button.setToolTip("Watchlistの基本項目・scope・archive_orderを編集")
        self.watchlist_button.clicked.connect(self._open_watchlist_editor)
        toolbar.addWidget(self.watchlist_button)
        self.work_editor_button = QPushButton("新規登録・範囲・置換")
        self.work_editor_button.clicked.connect(self._open_work_editor)
        toolbar.addWidget(self.work_editor_button)
        self.expand_button = QPushButton("全展開")
        self.expand_button.clicked.connect(self.tree.expandAll)
        toolbar.addWidget(self.expand_button)
        self.collapse_button = QPushButton("全折畳")
        self.collapse_button.clicked.connect(self.tree.collapseAll)
        toolbar.addWidget(self.collapse_button)
        toolbar.addWidget(QLabel("  Catalog 閲覧 / Watchlist 編集"))
        outer.addWidget(toolbar)
        self.discovery_help = QLabel(
            DISCOVERY_HELP + " 切り替えると即保存します。待機中ジョブは設定変更で停止する場合があります。"
        )
        self.discovery_help.setWordWrap(True)
        outer.addWidget(self.discovery_help)

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
        vertical = QSplitter(Qt.Orientation.Vertical)
        vertical.setObjectName("execution_vertical_splitter")
        # Keep the existing inventory/detail content intact while allowing its
        # viewport to shrink when the user gives the lower monitor more room.
        upper_scroll = QScrollArea()
        upper_scroll.setObjectName("execution_upper_scroll")
        upper_scroll.setFrameShape(QFrame.Shape.NoFrame)
        upper_scroll.setWidgetResizable(True)
        upper_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        upper_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        upper_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        upper_scroll.setMinimumSize(0, 0)
        upper.setMinimumHeight(upper.minimumSizeHint().height())
        upper_scroll.setWidget(upper)
        vertical.addWidget(upper_scroll)
        vertical.setCollapsible(0, False)
        # Keep the monitor heading reachable when the user drags the handle;
        # its own toggle hides the body while retaining the lower-pane header.
        self.execution_monitor = ExecutionMonitor(parent=self)
        self.execution_monitor.setMinimumHeight(26)
        vertical.addWidget(self.execution_monitor)
        vertical.setCollapsible(1, False)
        vertical.setStretchFactor(0, 1)
        vertical.setStretchFactor(1, 0)
        vertical.setSizes([620, 230])
        root_layout.addWidget(vertical)
        self.setCentralWidget(root)
        # The upper content keeps its existing minimum inside the scroll area;
        # only the viewport participates in the window minimum.
        self.setMinimumHeight(600)
        self.statusBar().showMessage("読み込み待ち")

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        splitter = self.findChild(QSplitter, "execution_vertical_splitter")
        if splitter is None:
            return
        upper_scroll = splitter.widget(0)
        monitor = splitter.widget(1)
        if upper_scroll is None or monitor is None:
            return
        # Do not reset a user's splitter ratio during ordinary resize/poll.
        # The content widget keeps its original minimum and QScrollArea makes
        # the upper controls reachable when its viewport is shorter.
        upper = upper_scroll.widget() if isinstance(upper_scroll, QScrollArea) else upper_scroll
        if upper is not None:
            hint = upper.minimumSizeHint().height()
            if upper.minimumHeight() < hint:
                upper.setMinimumHeight(hint)

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        # QScrollArea may recalculate the child geometry after the first
        # polish pass; apply the populated content minimum once that pass is
        # complete so the viewport scrolls instead of squeezing the content.
        QTimer.singleShot(0, self._sync_upper_geometry_minimum)

    # --- loading ---------------------------------------------------------------

    def _discovery_busy(self) -> bool:
        return self._discovery_save_worker is not None or self._discovery_refresh

    def _discovery_block_reason(self) -> str:
        if self._closed or self._discovery_busy():
            return "Watchlistを保存・再読込中です"
        if self._loading or self._inventory_stale:
            return "最新の一覧を再読込してから変更してください"
        snapshot = self.model.snapshot
        if (snapshot is None or not snapshot.watchlist_revision
                or Path(snapshot.watchlist_path).resolve() != Path(self.watchlist_path).resolve()
                or Path(snapshot.catalog_path).resolve() != Path(self.catalog_path).resolve()):
            return "現在の入力ファイルを再読込してから変更してください"
        controller = self._job_controller
        if controller is not None and (
            controller.active_job_id is not None
            or getattr(controller, "orphaned_live_worker", False)
            or getattr(controller, "supervision_error", False)
        ):
            return "実行中、または終了未確認のJobがあります"
        editor = getattr(self, "_watchlist_editor", None)
        if editor is not None and not getattr(editor, "_closed", False):
            if getattr(editor, "_dirty", False):
                return "Watchlist管理の未保存変更を保存または破棄してください"
            if getattr(editor, "_busy", lambda: False)():
                return "Watchlist管理の処理完了を待ってください"
        editor = self._work_editor
        if editor is not None:
            if getattr(editor, "dirty", False):
                return "作品編集の未保存変更を保存または破棄してください"
            if getattr(editor, "task", None) is not None:
                return "作品編集の処理完了を待ってください"
        return ""

    def _refresh_discovery_controls(self) -> None:
        if self._closed:
            return
        busy = self._discovery_busy()
        controller = self._job_controller
        active = controller is not None and controller.active_job_id is not None
        state = (busy, self._loading, active, self._discovery_block_reason(), self.model.discovery_pending_key)
        if state == self._discovery_controls_state:
            return
        self._discovery_controls_state = state
        for control in (*self._path_controls, self.reload_button):
            control.setEnabled(not busy and not self._loading)
        self.watchlist_button.setEnabled(not busy)
        self.work_editor_button.setEnabled(not busy)
        for editor in (getattr(self, "_watchlist_editor", None), self._work_editor):
            if editor is not None and not getattr(editor, "_closed", False):
                editor.set_active_job(active or busy)
        if self._jobs_page is not None:
            self._jobs_page.set_start_blocked(busy)
        self._on_checked_changed(self.model.selected_keys)
        self.tree.viewport().update()

    @Slot(str, bool)
    def _toggle_discovery(self, key: str, enabled: bool) -> None:
        reason = self._discovery_block_reason()
        target = self.model.key_inventory(key)
        if reason or target is None or target.target is None:
            self.error_label.setText(reason or "Watchlist項目が見つかりません。再読込してください")
            return
        if target.target.enabled == enabled:
            return
        snapshot = self.model.snapshot
        worker = DiscoverySaveWorker(snapshot.watchlist_path, key, enabled, snapshot.watchlist_revision)
        self._discovery_save_worker = worker
        self.model.discovery_pending_key = key
        self._discovery_notice = ""
        self.error_label.clear()
        worker.signals.succeeded.connect(self._discovery_saved, Qt.ConnectionType.QueuedConnection)
        worker.signals.failed.connect(self._discovery_save_failed, Qt.ConnectionType.QueuedConnection)
        worker.signals.savedButUnverified.connect(self._discovery_saved_unverified, Qt.ConnectionType.QueuedConnection)
        self._refresh_discovery_controls()
        self.statusBar().showMessage(f"{key}: Discovery設定を保存中…")
        self.thread_pool.start(worker)

    def _sync_discovery_editors(self, snapshot) -> None:
        targets = tuple(key.target for key in snapshot.keys if key.target is not None)
        for editor in (getattr(self, "_watchlist_editor", None), self._work_editor):
            if editor is not None and not getattr(editor, "_closed", False):
                editor.accept_watchlist_update(targets, snapshot.watchlist_revision, snapshot)

    @Slot(object)
    def _discovery_saved(self, result: ToggleResult) -> None:
        self._discovery_save_worker = None
        self._discovery_refresh = True
        self.model.discovery_pending_key = None
        saved = {target.key: target for target in result.targets}
        snapshot = replace(
            self.model.snapshot,
            keys=tuple(replace(key, target=saved[key.identity]) if key.identity in saved else key
                       for key in self.model.snapshot.keys),
            watchlist_revision=result.revision,
        )
        self.set_snapshot(snapshot)
        self._discovery_notice = f"{result.key}: Discovery設定を保存しました"
        try:
            self._sync_discovery_editors(snapshot)
        except Exception as exc:  # noqa: BLE001 - saving already committed
            self.error_label.setText(f"保存済み・編集画面の更新失敗: {exc}")
        self._reload_again = False
        self.reload()

    @Slot(str)
    def _discovery_saved_unverified(self, message: str) -> None:
        """The mutation committed but its subsequent read failed."""
        worker = self._discovery_save_worker
        key, enabled = worker.key, worker.enabled
        self._discovery_save_worker = None
        self._discovery_refresh = True
        self.model.discovery_pending_key = None
        snapshot = self.model.snapshot
        self.set_snapshot(replace(
            snapshot,
            keys=tuple(replace(row, target=replace(row.target, enabled=enabled))
                       if row.identity == key else row for row in snapshot.keys),
            watchlist_revision=None,
        ))
        self._discovery_notice = f"{key}: 保存済み。保存後の確認失敗から再読込しました"
        self.error_label.setText("Discovery設定は保存済み・保存後の確認失敗: " + message)
        self._reload_again = False
        self.reload()

    @Slot(str)
    def _discovery_save_failed(self, message: str) -> None:
        self._discovery_save_worker = None
        self.model.discovery_pending_key = None
        self._inventory_stale = True
        self._reload_again = False
        self.error_label.setText("保存できませんでした。再読込して確認してください: " + message)
        self.statusBar().showMessage("Discovery設定の保存失敗（自動再試行なし）")
        self._refresh_discovery_controls()

    def _invalidate_watchlist_editor_for_path_change(self) -> bool:
        if self._discovery_busy():
            self.statusBar().showMessage("Watchlistの保存・再読込完了を待ってください")
            return False
        work_editor = self._work_editor
        if work_editor is not None:
            if work_editor.task is not None or not work_editor._discard():
                return False
            work_editor.dirty = False
            work_editor.close()
            self._work_editor = None
        self._pending_work_full = None
        editor = getattr(self, "_watchlist_editor", None)
        if editor is None:
            return True
        if editor._busy():
            self.statusBar().showMessage("Watchlist editor operation is running; finish it before changing paths")
            return False
        if editor._dirty:
            answer = QMessageBox.question(
                self,
                "Close Watchlist editor",
                "Discard unsaved Watchlist edits before changing the active path pair?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Discard:
                return False
            editor._dirty = False
        editor.close()
        self._watchlist_editor = None
        return True

    def _choose_catalog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Catalog v7を選択", self.catalog_path, "SQLite (*.sqlite *.db);;All files (*)")
        if path:
            if not self._invalidate_watchlist_editor_for_path_change():
                return
            self.catalog_path = path
            self.catalog_edit.setText(path)

    def _choose_watchlist(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Watchlistを選択", self.watchlist_path, "YAML (*.yaml *.yml);;All files (*)")
        if path:
            if not self._invalidate_watchlist_editor_for_path_change():
                return
            self.watchlist_path = path
            self.watchlist_edit.setText(path)

    def _choose_runtime(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Runtime設定を選択", self.runtime_path, "YAML (*.yaml *.yml);;All files (*)")
        if path:
            if not self._invalidate_watchlist_editor_for_path_change():
                return
            self.runtime_path = path
            self.runtime_edit.setText(path)

    def reload(self) -> None:
        if self._closed:
            return
        if self._discovery_save_worker is not None:
            self._reload_again = True
            return
        if self._loading:
            self._reload_again = True
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
        if self._reload_again:
            self._reload_again = False
            self.reload()
            return  # Never consume pending Full against a pre-save snapshot.
        self.reload_button.setEnabled(True)
        for control in self._path_controls:
            control.setEnabled(True)
        self.set_snapshot(snapshot)
        if getattr(self, "_watchlist_editor", None) is not None:
            self._watchlist_editor.receive_snapshot(snapshot)
        if self._work_editor is not None:
            self._work_editor.snapshot = snapshot
            self._work_editor.preview = None
            self._work_editor._enabled()
        self.error_label.clear()
        self.statusBar().showMessage(f"読み込み完了: {snapshot.loaded_at.astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}")
        if self._discovery_refresh:
            try:
                self._sync_discovery_editors(snapshot)
            except Exception as exc:  # noqa: BLE001 - keep the committed state visible
                self.error_label.setText(f"保存済み・編集画面の更新失敗: {exc}")
            self._discovery_refresh = False
            self.statusBar().showMessage(self._discovery_notice)
        self._refresh_discovery_controls()
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
        editor_key = self._pending_editor_full
        self._pending_editor_full = None
        if editor_key is not None:
            self._show_execution_preview(
                "discover",
                selected_keys={editor_key},
                force_full=True,
                after_watchlist_save=True,
            )
        work_full, self._pending_work_full = self._pending_work_full, None
        if work_full is not None:
            from screenshot_crawler.watchlist.service import WatchlistService

            keys, revision = work_full
            if WatchlistService(self.watchlist_path).revision() != revision:
                self.error_label.setText("保存後にWatchlistが変わったためFull実行確認を停止しました")
            else:
                self._show_execution_preview("discover", selected_keys=set(keys), force_full=True,
                                             after_watchlist_save=True)

    @Slot(str)
    def _load_failed(self, message: str) -> None:
        if self._closed:
            return
        self._loading = False
        self._inventory_stale = True
        if self._reload_again:
            self._reload_again = False
            self.reload()
            return
        self.reload_button.setEnabled(True)
        for control in self._path_controls:
            control.setEnabled(True)
        prefix = "読み込み失敗（前回の表示は古い可能性があります）: " if self.model.snapshot else "読み込み失敗: "
        self.error_label.setText(prefix + message)
        self.statusBar().showMessage("読み込みに失敗しました")
        if self._discovery_refresh:
            self._discovery_refresh = False
            self.error_label.setText("Discovery設定は保存済み・表示更新失敗: " + message)
            self.statusBar().showMessage("保存済みです。一覧を再読込してください")
        self._refresh_discovery_controls()
        if self._pending_rerun is not None:
            self._pending_rerun = None
            self._rerun_original_id = None
            self.error_label.setText(self.error_label.text() + " / 再計画は停止しました")
        self._pending_editor_full = None
        self._pending_work_full = None

    def set_snapshot(self, snapshot: object) -> None:
        scroll = (self.tree.horizontalScrollBar().value(), self.tree.verticalScrollBar().value())
        self._inventory_stale = False
        old_focus = self.model._nodes.get(self.model.focused_node_id or "")
        old_focus_key = old_focus.key_identity if old_focus and old_focus.kind == "key" else None
        old_focus_work = old_focus.work_key if old_focus and old_focus.kind == "work" else None
        expanded_ids = self._expanded_node_ids()
        self.model.set_snapshot(snapshot)
        self.detail.set_snapshot(snapshot)
        if not self._initial_expand_done:
            self.tree.collapseAll()
            self._initial_expand_done = True
        else:
            self._restore_expanded(expanded_ids)
        focus = self.model.node_by_key_identity(old_focus_key) if old_focus_key else None
        if focus is None and old_focus_work:
            focus = next((node for node in self.model._nodes.values() if node.kind == "work" and node.work_key == old_focus_work), None)
        if focus is not None:
            self.model.focus_node(focus)
        self._sync_upper_geometry_minimum()
        QTimer.singleShot(0, self._sync_upper_geometry_minimum)
        self._on_checked_changed(self.model.checked_keys)
        self._refresh_site_resource_controls()
        self.tree.horizontalScrollBar().setValue(scroll[0])
        self.tree.verticalScrollBar().setValue(scroll[1])

    def _sync_upper_geometry_minimum(self) -> None:
        """Refresh the upper-pane clamp after detail content changes."""

        splitter = self.findChild(QSplitter, "execution_vertical_splitter")
        if splitter is None:
            return
        upper_scroll = splitter.widget(0)
        upper = upper_scroll.widget() if isinstance(upper_scroll, QScrollArea) else upper_scroll
        if upper is None:
            return
        hint = upper.minimumSizeHint().height()
        if upper.minimumHeight() < hint:
            upper.setMinimumHeight(hint)

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
        self._sync_upper_geometry_minimum()

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
        if self._discovery_busy():
            enabled = False
        if self._job_controller is not None and getattr(self._job_controller, "orphaned_live_worker", False):
            enabled = False
        for button in (self.discover_button, self.batch_run_button, self.grant_only_button):
            button.setEnabled(enabled)

    def _show_execution_preview(
        self,
        action: str,
        *,
        selected_keys: set[str] | frozenset[str] | None = None,
        force_full: bool = False,
        after_watchlist_save: bool = False,
    ) -> None:
        """Build a lightweight request and hand it to the durable job queue.

        The GUI signs only the already loaded selection and execution inputs;
        the worker performs the latest Catalog planning under its job lock.
        """
        if self._discovery_busy():
            self.error_label.setText("Watchlistの保存・再読込完了を待ってから実行してください")
            return
        snapshot = self.model.snapshot
        selected_identities = frozenset(
            self.model.selected_keys if selected_keys is None else selected_keys
        )
        if snapshot is None or not selected_identities:
            return
        limit = self.execution_limit_spin.value() or None
        key_map = {key.identity: key for key in snapshot.keys}
        by_site: dict[str, list[str]] = {}
        blockers: list[str] = []
        for identity in sorted(selected_identities):
            key = key_map.get(identity)
            if key is None or key.target is None:
                blockers.append(f"unknown Watchlist key: {identity}")
                continue
            by_site.setdefault(key.site, []).append(identity)
        if not by_site:
            blockers.append("no managed Watchlist keys selected")

        resources_by_site: tuple[tuple[str, str], ...] = ()
        if action == "grant_only":
            resources: list[tuple[str, str]] = []
            for site in sorted(by_site):
                combo = self._site_grant_resource_combos.get(site)
                if combo is None:
                    blockers.append(f"{site}: no supported Grant-only Resource selector")
                    continue
                if site in self._site_resource_invalid:
                    blockers.append(
                        f"{site}: selected Resource {self._site_resource_invalid[site]!r} is no longer supported"
                    )
                    continue
                value = combo.currentData()
                if not isinstance(value, str) or not value:
                    blockers.append(f"{site}: Grant-only Resource is not selected")
                    continue
                resources.append((site, value))
            resources_by_site = tuple(resources)
        if limit is not None and limit < 1:
            blockers.append("limit must be at least 1")
        if blockers:
            self.error_label.setText("; ".join(blockers))
            return

        mode = None
        if action == "discover":
            mode = "full" if force_full else self.discover_mode_combo.currentData()
        request = JobExecutionRequest(
            action=action,
            selected_keys=selected_identities,
            sites=tuple(sorted(by_site)),
            keys_by_site=tuple(
                (site, tuple(sorted(keys))) for site, keys in sorted(by_site.items())
            ),
            mode=mode,
            resources_by_site=resources_by_site,
            limit=limit,
            catalog_path=snapshot.catalog_path,
            watchlist_path=snapshot.watchlist_path,
            runtime_path=str(Path(self.runtime_path).resolve()),
            env_file=str(Path('.env').resolve()),
            output_root=str(Path('output/batch').resolve()),
            library_dir=str(Path('output/Books').resolve()),
            metrics_root=str(Path('output/metrics').resolve()),
            fingerprint_kind='inputs-v1',
        )
        request = replace(
            request,
            plan_fingerprint=ExecutionPlanService().input_fingerprint(request),
        )
        if not after_watchlist_save:
            self._start_execution(request)
            self.statusBar().showMessage('実行ジョブをキューに登録しました')
            return
        title = 'Full Discovery'
        selected = ', '.join(
            key_map[identity].label or key_map[identity].title or identity
            for identity in sorted(request.selected_keys)
        )
        disabled = [
            identity for identity in sorted(request.selected_keys)
            if not key_map[identity].target.enabled
        ]
        warning = (
            f"\n無効化されたkeyはスキップされます: {', '.join(disabled)}"
            if disabled else ""
        )
        message = (
            'Watchlistを保存しました。対象keyのFull Discoveryを実行しますか？\n'
            f"対象: {selected}{warning}\n\n"
            '実行時に最新Catalogから計画を作成します。'
        )
        answer = QMessageBox.question(
            self,
            title,
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._start_execution(request)
            self.statusBar().showMessage('Full Discoveryジョブをキューに登録しました')
    @Slot(object)
    def _start_execution(self, request: object) -> None:
        if self._discovery_busy():
            self.error_label.setText("Watchlistの保存・再読込完了を待ってから実行してください")
            return
        if not isinstance(request, JobExecutionRequest):
            return
        controller = self._ensure_jobs()
        job_id = controller.queue(request, original_job_id=self._rerun_original_id)
        self._session_job_ids.append(job_id)
        self._rerun_original_id = None
        # Queueing and worker start are the safety boundary.  A passive view
        # may be unavailable while the controller is still healthy; it must
        # never prevent the confirmed job from starting.
        try:
            self.execution_monitor.clear_manual_selection()
            self.execution_monitor.follow_job(job_id)
        except Exception:
            LOGGER.debug("execution monitor follow failed", exc_info=True)
        if controller.active_job_id is None:
            controller.start_job(job_id)
        self._monitor_followed_active_id = controller.active_job_id
        self._refresh_emergency_controls()
        self.statusBar().showMessage(f"ジョブをキューしました: {job_id}")

    def _refresh_emergency_controls(self) -> None:
        controller = self._job_controller
        self.emergency_stop_button.setEnabled(
            controller is not None and controller.active_job_id is not None
        )
        if controller is not None and getattr(controller, "orphaned_live_worker", False):
            for button in (self.discover_button, self.batch_run_button, self.grant_only_button):
                button.setEnabled(False)

    @Slot()
    def _emergency_stop(self) -> None:
        controller = self._job_controller
        if controller is None or controller.active_job_id is None:
            self._refresh_emergency_controls()
            return
        # Pause session dispatch even if termination fails or races with normal
        # completion. Persisted queued jobs remain available for explicit start.
        self._session_job_ids.clear()
        self._pending_rerun = None
        self._rerun_original_id = None
        self._pending_work_full = None
        self._pending_editor_full = None
        self.emergency_stop_button.setEnabled(False)
        try:
            controller.force_stop()
        except Exception as exc:
            LOGGER.exception("emergency worker stop failed")
            self.error_label.setText(f"緊急停止失敗（停止未確認）: {exc}")
            self.statusBar().showMessage("緊急停止失敗：workerの停止を確認できません")
        else:
            unverified = (
                controller.active_job_id is not None
                or getattr(controller, "orphaned_live_worker", False)
            )
            message = (
                "緊急停止：workerの終了を確認できません。ジョブ履歴を確認してください。"
                if unverified else "緊急停止しました。消費・出力状態は未確認です。自動再試行しません。"
            )
            self.error_label.setText(message)
            self.statusBar().showMessage(message)
        finally:
            # Supervision precedes passive views; a broken monitor must never
            # prevent termination or hide a still-active worker's stop button.
            self._refresh_emergency_controls()
            try:
                self._poll_jobs()
            except Exception:
                LOGGER.debug("post-emergency job refresh failed", exc_info=True)
            self._refresh_emergency_controls()

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
            try:
                self.execution_monitor.set_store(self._job_store)
            except Exception:
                LOGGER.debug("execution monitor initialization failed", exc_info=True)
            try:
                self._jobs_page = JobsPage(self._job_store, self._job_controller, self)
                self._jobs_page.set_start_blocked(self._discovery_busy())
                self._jobs_page.rerunRequested.connect(self._rerun_job)
            except Exception:
                self._jobs_page = None
                LOGGER.debug("jobs page initialization failed", exc_info=True)
            self._job_poll_timer.start()
        return self._job_controller

    def _open_jobs(self) -> None:
        self._ensure_jobs()
        if self._jobs_page is None:
            self.error_label.setText("Job history view unavailable; supervisor remains active")
            return
        self._jobs_page.refresh()
        self._jobs_page.resize(900, 650)
        self._jobs_page.show()
        self._jobs_page.raise_()
        self._jobs_page.activateWindow()

    def _open_watchlist_editor(self) -> None:
        """Open an independent editor page without changing Inventory checks."""

        if self._discovery_busy():
            return

        if getattr(self, "_watchlist_editor", None) is None or self._watchlist_editor._closed:
            self._watchlist_editor = WatchlistEditorPage(
                self.watchlist_path,
                catalog_path=self.catalog_path,
                runtime_path=self.runtime_path,
                snapshot=self.model.snapshot,
                parent=self,
            )
            self._watchlist_editor.fullRequested.connect(self._run_editor_full)
            self._watchlist_editor.scopeApplied.connect(lambda _work: self.reload())
            self._watchlist_editor.watchlistSaved.connect(self.reload)
            self._watchlist_editor.catalogReloadRequested.connect(self.reload)
        else:
            self._watchlist_editor.snapshot = self.model.snapshot
            self._watchlist_editor.inventory_model.set_snapshot(self.model.snapshot)
            self._watchlist_editor.reload()
        self._watchlist_editor.set_active_job(
            self._job_controller is not None and self._job_controller.active_job_id is not None
        )
        self._watchlist_editor.resize(1100, 720)
        self._watchlist_editor.show()
        self._watchlist_editor.raise_()
        self._watchlist_editor.activateWindow()

    def _open_work_editor(self) -> None:
        if self._discovery_busy():
            return
        from .work_editor import WorkEditorDialog

        if self._work_editor is None:
            self._work_editor = WorkEditorDialog(self.watchlist_path, self.catalog_path, self.runtime_path,
                                                  snapshot=self.model.snapshot, parent=self)
            self._work_editor.fullRequested.connect(self._run_work_full)
            self._work_editor.watchlistSaved.connect(self.reload)
        self._work_editor.set_active_job(self._job_controller is not None and self._job_controller.active_job_id is not None)
        self._work_editor.show()
        self._work_editor.raise_()
        self._work_editor.activateWindow()

    def _run_work_full(self, payload) -> None:
        if self._job_controller is not None and self._job_controller.active_job_id is not None:
            self.error_label.setText("保存済みですが実行中JobがあるためFullを開始できません")
            return
        self._pending_work_full = payload
        self.reload()

    def _run_editor_full(self, key: str) -> None:
        """Run Full for the editor's explicit key, independent of Inventory checks."""

        if self._job_controller is not None and self._job_controller.active_job_id is not None:
            self.error_label.setText("実行中JobがあるためFull Discoveryを開始できません")
            return
        self._pending_editor_full = key
        self.reload()

    def _poll_jobs(self) -> None:
        self._refresh_emergency_controls()
        if self._job_controller is None:
            return
        state = self._job_controller.poll()
        self._refresh_emergency_controls()
        if self._work_editor is not None:
            self._work_editor.set_active_job(self._job_controller.active_job_id is not None or self._discovery_busy())
        editor = getattr(self, "_watchlist_editor", None)
        if editor is not None:
            editor.set_active_job(self._job_controller.active_job_id is not None or self._discovery_busy())
        # Views are observers only.  A malformed event, missing log, or widget
        # failure must never prevent controller state handling or queue advance.
        try:
            self.execution_monitor.refresh_jobs()
            active_job_id = self._job_controller.active_job_id
            if active_job_id != self._monitor_followed_active_id:
                self._monitor_followed_active_id = active_job_id
                if active_job_id is not None:
                    self.execution_monitor.follow_job(active_job_id)
            self.execution_monitor.refresh()
        except Exception:
            LOGGER.debug("execution monitor refresh failed", exc_info=True)
        try:
            if self._jobs_page is not None:
                self._jobs_page.refresh()
        except Exception:
            LOGGER.debug("jobs page refresh failed", exc_info=True)
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
            if self._job_controller.active_job_id is None and not self._discovery_busy():
                for queued_id in tuple(self._session_job_ids):
                    try:
                        if self._job_store is not None and self._job_store.get_job(queued_id)["state"] == "queued":
                            self._job_controller.start_job(queued_id)
                            self._refresh_emergency_controls()
                            self._monitor_followed_active_id = queued_id
                            try:
                                self.execution_monitor.follow_job(queued_id)
                            except Exception:
                                LOGGER.debug("execution monitor follow failed", exc_info=True)
                            break
                    except (KeyError, RuntimeError):
                        continue

    def _rerun_job(self, job_id: str) -> None:
        if self._discovery_busy():
            return
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
        if self._discovery_busy():
            self.statusBar().showMessage("Watchlistの保存・再読込完了を待ってから閉じてください")
            event.ignore()
            return
        if self._work_editor is not None:
            if self._work_editor.task is not None or not self._work_editor._discard():
                event.ignore()
                return
            self._work_editor.dirty = False
        editor = getattr(self, "_watchlist_editor", None)
        if editor is not None and editor._busy():
            self.statusBar().showMessage("Watchlist operation is running; wait before closing")
            event.ignore()
            return
        if editor is not None and editor._dirty:
            answer = QMessageBox.question(
                self,
                "Close Watchlist editor",
                "Discard unsaved Watchlist edits before closing the GUI?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Discard:
                event.ignore()
                return
            editor._dirty = False
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

