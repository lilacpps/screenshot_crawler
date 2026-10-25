"""Watchlist editing page used by the local GUI.

The editor intentionally owns its checkbox state.  Inventory selection remains
the execution selection, so changing a scope proposal cannot silently change a
pending Batch or Grant-only request.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QRunnable,
    Qt,
    QThreadPool,
    Signal,
    Slot,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableView,
    QTextEdit,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from screenshot_crawler.archive_order import build_work_archive_position_plan
from screenshot_crawler.catalog.job_lock import CatalogJobLock
from screenshot_crawler.catalog.service import CatalogService
from screenshot_crawler.discovery.base import DiscoveryAdapter
from screenshot_crawler.discovery.listing import ListingPreview, ListingRow
from screenshot_crawler.gui.model import InventoryTreeModel, StatusFilter, ViewMode
from screenshot_crawler.management.catalog_reader import CatalogInventoryReader
from screenshot_crawler.management.inventory import InventoryService
from screenshot_crawler.management.models import InventorySnapshot
from screenshot_crawler.watchlist.models import DiscoveryScope, WatchlistTarget
from screenshot_crawler.watchlist.reconcile import ScopeReconciler, ScopeSyncPreview
from screenshot_crawler.watchlist.selection import (
    ArchiveArtifactFact,
    ArchiveFactsSnapshot,
    ScopeEditPreview,
    SelectionPlanner,
)
from screenshot_crawler.watchlist.service import WatchlistEditPreview, WatchlistService


def _catalog_snapshot_identity(data: Any) -> str:
    """Stable identity for the one transaction returned by CatalogInventoryReader."""

    payload = json.dumps(asdict(data), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class _ListingSignals(QObject):
    """QObject-like signal holder that remains owned by the GUI thread."""

    succeeded = Signal(object)
    failed = Signal(str)


class _ListingWorker(QRunnable):
    """Read-only CDP listing worker; it never constructs Catalog state."""

    def __init__(self, target: WatchlistTarget, generation: int = 0) -> None:
        super().__init__()
        self.target = target
        self.generation = generation
        self.signals = _ListingSignals()

    @Slot()
    def run(self) -> None:
        async def fetch() -> ListingPreview:
            from screenshot_crawler.cli import _discovery_registry
            from screenshot_crawler.core.browser import BrowserSession, resolve_cdp_endpoint
            from screenshot_crawler.discovery.listing_service import ListingPreviewService

            registry = _discovery_registry()
            if self.target.site not in registry.sites():
                raise RuntimeError(f"No Discovery adapter is registered for site {self.target.site!r}")
            adapter = registry.create(self.target.site)
            if type(adapter).preview_complete_listing is DiscoveryAdapter.preview_complete_listing:
                raise RuntimeError(f"Site {self.target.site!r} does not support a complete-listing preview")
            session = await BrowserSession.connect(resolve_cdp_endpoint(site=self.target.site))
            page = None
            try:
                page = await session.new_page()
                # Adapter-owned navigation is required.  The GUI never opens
                # the target URL before capability/identity checks.
                return await ListingPreviewService(registry).preview_complete_listing(page, self.target)
            finally:
                try:
                    if page is not None:
                        await session.close_page(page)
                finally:
                    await session.close()

        try:
            self.signals.succeeded.emit((self.generation, asyncio.run(fetch())))
        except Exception as exc:  # noqa: BLE001 - show unsupported/endpoint blockers
            self.signals.failed.emit(str(exc) or type(exc).__name__)


class _ScopeSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)


class _InventoryWorker(QRunnable):
    def __init__(self, catalog: Path, watchlist: Path, runtime: Path, generation: int) -> None:
        super().__init__()
        self.paths = catalog, watchlist, runtime
        self.generation = generation
        self.signals = _ScopeSignals()

    @Slot()
    def run(self) -> None:
        try:
            catalog, watchlist, runtime = self.paths
            snapshot = InventoryService().load(catalog, watchlist, runtime_path=runtime)
        except Exception as exc:  # noqa: BLE001 - read-only GUI reload boundary
            self.signals.failed.emit(str(exc) or type(exc).__name__)
        else:
            self.signals.succeeded.emit((self.generation, snapshot))



class _ScopeWorker(QRunnable):
    """Run Catalog scope preview/apply away from the Qt GUI thread."""

    def __init__(self, watchlist_path: Path, catalog_path: Path, work_key: str, preview: ScopeSyncPreview | None = None, generation: int = 0) -> None:
        super().__init__()
        self.watchlist_path = watchlist_path
        self.catalog_path = catalog_path
        self.work_key = work_key
        self.preview = preview
        self.generation = generation
        self.signals = _ScopeSignals()

    @Slot()
    def run(self) -> None:
        try:
            if not self.catalog_path.is_file():
                raise RuntimeError("Catalog path does not exist; scope operation is blocked")
            reconciler = ScopeReconciler(
                WatchlistService(self.watchlist_path), CatalogService(self.catalog_path)
            )
            result = reconciler.apply(self.preview) if self.preview is not None else reconciler.preview(self.work_key)
        except Exception as exc:  # noqa: BLE001 - user-visible worker boundary
            self.signals.failed.emit(str(exc) or type(exc).__name__)
        else:
            self.signals.succeeded.emit((self.generation, result))


class _EditorPreviewWorker(QRunnable):
    """Build the Stage 03 Catalog-bound scope preview from one read snapshot."""

    def __init__(
        self,
        *,
        target: WatchlistTarget,
        listing: ListingPreview,
        checked: Iterable[str],
        watchlist_revision: str,
        archive_targets: Iterable[WatchlistTarget],
        saved_archive_targets: Iterable[WatchlistTarget] = (),
        catalog_path: Path,
        generation: int,
        sibling_listings: dict[str, ListingPreview] | None = None,
        sibling_checked_external_ids: dict[str, frozenset[str]] | None = None,
    ) -> None:
        super().__init__()
        self.target = target
        self.listing = listing
        self.checked = frozenset(checked)
        self.watchlist_revision = watchlist_revision
        self.archive_targets = tuple(archive_targets)
        self.saved_archive_targets = tuple(saved_archive_targets)
        self.catalog_path = catalog_path
        self.sibling_listings = dict(sibling_listings or {})
        self.sibling_checked_external_ids = dict(sibling_checked_external_ids or {})
        self.generation = generation
        self.signals = _ScopeSignals()

    @Slot()
    def run(self) -> None:
        try:
            if not self.catalog_path.is_file():
                raise RuntimeError("Catalog snapshot is unavailable; scope preview is blocked")
            data = CatalogInventoryReader().read(self.catalog_path)
            work = next((row for row in data.works if row.work_key == self.target.work_key), None)
            items = tuple(row for row in data.items if work is not None and row.work_id == work.id)
            # Ownership is site-filtered inside SelectionPlanner, while archive
            # numbering needs every source in the Work across sites.
            sources = tuple(data.sources)
            targets = tuple(row for row in self.archive_targets if row.work_key == self.target.work_key)
            before_targets = tuple(row for row in (self.saved_archive_targets or self.archive_targets) if row.work_key == self.target.work_key)
            facts = None
            if work is not None:
                current_plan = build_work_archive_position_plan(
                    work, before_targets, items, tuple(row for row in data.sources if row.item_id in {item.id for item in items}),
                    provisional=True,
                )
                run_by_item = {run.item_id: run for run in data.latest_runs}
                item_by_id = {item.id: item for item in items}
                source_by_item = {
                    source.item_id: source
                    for source in data.sources
                    if source.item_id in item_by_id
                }
                archive_facts: list[ArchiveArtifactFact] = []
                ambiguous_sources: set[int] = set()
                for artifact in data.artifacts:
                    if artifact.kind != "archive" or artifact.item_id not in item_by_id:
                        continue
                    run = run_by_item.get(artifact.item_id)
                    source = source_by_item.get(artifact.item_id)
                    if run is None or source is None or artifact.crawl_run_id != run.id:
                        if source is not None:
                            ambiguous_sources.add(source.id)
                        continue
                    if run.source_id != source.id:
                        ambiguous_sources.add(source.id)
                        continue
                    archive_facts.append(
                        ArchiveArtifactFact(
                            source_id=source.id,
                            artifact_id=artifact.id,
                            locator=artifact.locator,
                            state=artifact.state,
                            run_source_id=run.source_id,
                        )
                    )
                facts = ArchiveFactsSnapshot(
                    snapshot_id=_catalog_snapshot_identity(data),
                    before_positions=tuple(sorted(current_plan.positions_by_source_id.items())) if current_plan else (),
                    artifacts=tuple(archive_facts),
                    collision_source_ids=tuple(sorted(ambiguous_sources)),
                )
            catalog_id = _catalog_snapshot_identity(data)
            result = SelectionPlanner().preview_edit(
                self.listing,
                self.checked,
                current_target=self.target,
                catalog_sources=sources,
                watchlist_revision=self.watchlist_revision,
                watchlist_content_sha=self.watchlist_revision,
                catalog_snapshot_id=catalog_id,
                archive_work=work,
                archive_items=items,
                archive_targets=targets,
                archive_facts=facts,
                sibling_listings=self.sibling_listings,
                sibling_checked_external_ids=self.sibling_checked_external_ids,
                sibling_targets=targets,
            )
        except Exception as exc:  # noqa: BLE001 - fail-closed preview worker
            self.signals.failed.emit(str(exc) or type(exc).__name__)
        else:
            self.signals.succeeded.emit((self.generation, result))


class _SaveWorker(QRunnable):
    def __init__(
        self,
        path: Path,
        proposed: tuple[WatchlistTarget, ...],
        revision: str,
        catalog_path: Path | None,
        catalog_guard: str | None,
        generation: int,
        scope_preview: ScopeEditPreview | None = None,
    ) -> None:
        super().__init__()
        self.path, self.proposed, self.revision = path, proposed, revision
        self.catalog_path, self.catalog_guard, self.generation = catalog_path, catalog_guard, generation
        self.scope_preview = scope_preview
        self.signals = _ScopeSignals()

    @staticmethod
    def _guard(path: Path | None) -> str | None:
        if path is None:
            return None
        try:
            stat = path.stat()
        except OSError:
            return None
        return f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}"

    @Slot()
    def run(self) -> None:
        try:
            service = WatchlistService(self.path)
            if self.catalog_path is not None:
                if self.catalog_guard is None or not self.catalog_path.is_file():
                    raise RuntimeError("Catalog path pair is unavailable for a scope-affecting edit")
                with CatalogJobLock(self.catalog_path):
                    if self._guard(self.catalog_path) != self.catalog_guard:
                        raise RuntimeError("Catalog path pair changed after preview")
                    if self.scope_preview is None or not self.scope_preview.ready or not self.scope_preview.is_fresh():
                        raise RuntimeError("Scope preview is missing or stale; rerun preview")
                    if self.scope_preview.proposed_target not in self.proposed:
                        raise RuntimeError("Scope preview draft no longer matches the save proposal")
                    data = CatalogInventoryReader().read(self.catalog_path)
                    if _catalog_snapshot_identity(data) != self.scope_preview.catalog_snapshot_id:
                        raise RuntimeError("Catalog changed since scope preview; reload and retry")
                    saved = service.apply_edit(self.proposed, expected_revision=self.revision)
            else:
                saved = service.apply_edit(self.proposed, expected_revision=self.revision)
        except Exception as exc:  # noqa: BLE001 - atomic save boundary
            self.signals.failed.emit(str(exc) or type(exc).__name__)
        else:
            self.signals.succeeded.emit((self.generation, saved))


class WatchlistEditorModel(QAbstractTableModel):
    """Virtual table model for Watchlist rows; edits stay in memory."""

    HEADERS = ("key", "work", "site", "enabled", "label", "url", "archive_order")

    def __init__(self, targets: Iterable[WatchlistTarget] = (), parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.targets = list(targets)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.targets)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not (0 <= index.row() < len(self.targets)):
            return None
        target = self.targets[index.row()]
        value = (target.key, target.work_key, target.site, target.enabled, target.label, target.url, target.archive_order)[index.column()]
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == 3:
            return Qt.CheckState.Checked if value else Qt.CheckState.Unchecked
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return value
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        # The table is a summary projection.  All edits go through the
        # selected-key form so URL/scope/order changes share one draft.
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:
        return False  # Summary is read-only; the form owns every edit.

    def set_targets(self, targets: Iterable[WatchlistTarget]) -> None:
        self.beginResetModel()
        self.targets = list(targets)
        self.endResetModel()

    def target_at(self, row: int) -> WatchlistTarget | None:
        return self.targets[row] if 0 <= row < len(self.targets) else None


class ScopeChecklistModel(QAbstractTableModel):
    """Independent, checkbox-driven complete listing projection."""

    HEADERS = ("select", "external_id", "position", "title", "URL", "access", "Catalog", "current-proposed", "delta")
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rows: list[ListingRow] = []
        self.checked: set[str] = set()
        self.catalog_labels: dict[str, str] = {}
        self.catalog_details: dict[str, tuple[str, str, str]] = {}
        self.editable = False

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not (0 <= index.row() < len(self.rows)):
            return None
        row = self.rows[index.row()]
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == 0:
            return Qt.CheckState.Checked if row.external_id in self.checked else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.DisplayRole:
            current, proposed, delta = self.catalog_details.get(row.external_id, ("-", "-", "-"))
            values = (None, row.external_id, row.site_position, row.display_title, row.url, row.access_observation, self.catalog_labels.get(row.external_id, "unregistered"), f"{current}->{proposed}", delta)
            return values[index.column()]
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == 0 and self.editable:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if not self.editable or not index.isValid() or index.column() != 0 or role != Qt.ItemDataRole.CheckStateRole:
            return False
        external_id = self.rows[index.row()].external_id
        if value == Qt.CheckState.Checked:
            self.checked.add(external_id)
        else:
            self.checked.discard(external_id)
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
        self.changed.emit()
        return True

    def set_listing(self, listing: ListingPreview, *, checked: Iterable[str] = (), catalog_labels: dict[str, str] | None = None, catalog_details: dict[str, tuple[str, str, str]] | None = None) -> None:
        self.beginResetModel()
        self.rows = list(listing.rows)
        self.editable = listing.ready
        ids = {row.external_id for row in self.rows}
        self.checked = set(checked) & ids
        self.catalog_labels = dict(catalog_labels or {})
        self.catalog_details = dict(catalog_details or {})
        self.endResetModel()

    def set_all_checked(self, checked: bool) -> None:
        if not self.editable:
            return
        ids = {row.external_id for row in self.rows}
        self.checked = ids if checked else set()
        if self.rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows) - 1, 0), [Qt.ItemDataRole.CheckStateRole])
            self.changed.emit()


class AddWatchlistKeyDialog(QDialog):
    """Explicit new-key form; stable identity fields are never cloned silently."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Watchlist key追加")
        form = QFormLayout(self)
        self.key_edit = QLineEdit()
        self.work_edit = QLineEdit()
        self.site_edit = QLineEdit()
        self.url_edit = QLineEdit()
        self.label_edit = QLineEdit()
        self.enabled_edit = QCheckBox("有効")
        self.enabled_edit.setChecked(True)
        for name, widget in (
            ("key", self.key_edit), ("work_key", self.work_edit),
            ("site", self.site_edit), ("url", self.url_edit),
            ("label", self.label_edit), ("enabled", self.enabled_edit),
        ):
            form.addRow(name, widget)
        buttons = QHBoxLayout()
        ok = QPushButton("追加")
        ok.clicked.connect(self.accept)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(ok)
        buttons.addWidget(cancel)
        form.addRow(buttons)

    def target(self) -> WatchlistTarget:
        values = {
            "key": self.key_edit.text().strip(),
            "work_key": self.work_edit.text().strip(),
            "site": self.site_edit.text().strip(),
            "url": self.url_edit.text().strip(),
            "label": self.label_edit.text(),
            "enabled": self.enabled_edit.isChecked(),
        }
        return WatchlistTarget(**values)


class WatchlistEditorPage(QWidget):
    """Safe Watchlist editor page with preview/save/Full/scope-sync actions."""

    fullRequested = Signal(str)
    scopePreviewRequested = Signal(str)
    scopeApplied = Signal(str)
    watchlistSaved = Signal()
    catalogReloadRequested = Signal()

    def __init__(
        self,
        watchlist_path: str | Path,
        *,
        catalog_path: str | Path | None = None,
        runtime_path: str | Path = "crawler.yaml",
        snapshot: InventorySnapshot | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.watchlist_path = Path(watchlist_path)
        self.catalog_path = Path(catalog_path) if catalog_path is not None else None
        self.runtime_path = Path(runtime_path)
        self.snapshot = snapshot
        self.service = WatchlistService(self.watchlist_path)
        self.targets = tuple(self.service.list_targets())
        self.revision = self.service.revision()
        self._active_job = False
        self._catalog_guard = self._path_guard(self.catalog_path)
        self._listing: ListingPreview | None = None
        self._last_scope_preview: ScopeSyncPreview | None = None
        self._listing_worker: _ListingWorker | None = None
        self._scope_worker: _ScopeWorker | None = None
        self._preview_worker: _EditorPreviewWorker | None = None
        self._save_worker: _SaveWorker | None = None
        self._reload_worker: _InventoryWorker | None = None
        self._pending_preview: WatchlistEditPreview | None = None
        self._scope_edit_preview: ScopeEditPreview | None = None
        self._scope_apply_confirmed = False
        self._scope_preview_revision: str | None = None
        self._scope_checkbox_dirty = False
        self._draft_checked_ids: frozenset[str] | None = None
        self._active_key: str | None = None
        self._dirty = False
        self._generation = 0
        self._closed = False
        self._preview_catalog_guard: str | None = None
        self.thread_pool = QThreadPool(self)
        self._build_ui()
        self._set_targets(self.targets)

    @staticmethod
    def _path_guard(path: Path | None) -> str | None:
        if path is None:
            return None
        try:
            # Warm pathlib's URI support on the GUI thread.  CatalogInventoryReader
            # uses the same URI form and must not pay the import cost while a
            # QRunnable is competing with Qt's event loop.
            path.resolve().as_uri()
            stat = path.stat()
        except OSError:
            return None
        return f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}"

    def _build_ui(self) -> None:
        self.setWindowTitle("Watchlist管理・編集")
        outer = QVBoxLayout(self)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        self.target_model = WatchlistEditorModel(parent=self)
        self.target_table = QTableView()
        self.target_table.setModel(self.target_model)
        self.target_table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.target_table.setAlternatingRowColors(True)
        self.target_table.setMinimumHeight(160)
        self.target_table.clicked.connect(self._select_target_row)
        self.inventory_model = InventoryTreeModel(self.snapshot, parent=self)
        self.inventory_model.set_view_mode(ViewMode.SITE)
        self.inventory_tree = QTreeView()
        self.inventory_tree.setModel(self.inventory_model)
        self.inventory_tree.setAlternatingRowColors(True)
        self.inventory_tree.setMinimumWidth(260)
        self.inventory_tree.expandToDepth(1)
        self.inventory_tree.clicked.connect(self._select_inventory_key)
        projection = QSplitter(Qt.Orientation.Horizontal)
        projection.addWidget(self.inventory_tree)
        projection.addWidget(self.target_table)
        projection.setStretchFactor(0, 1)
        projection.setStretchFactor(1, 3)
        layout.addWidget(projection)
        controls = QHBoxLayout()
        self.target_search = QLineEdit()
        self.target_search.setMinimumWidth(180)
        self.target_search.setPlaceholderText("site / work / key / label")
        self.target_search.textChanged.connect(self._filter_targets)
        controls.addWidget(self.target_search, 2)
        self.inventory_filter = QComboBox()
        for label, value in (("All", StatusFilter.ALL), ("Review", StatusFilter.REVIEW), ("Unfinished", StatusFilter.UNFINISHED), ("Out of scope", StatusFilter.OUT_OF_SCOPE)):
            self.inventory_filter.addItem(label, value)
        self.inventory_filter.currentIndexChanged.connect(
            lambda index: self.inventory_model.set_status_filter(self.inventory_filter.itemData(index))
        )
        controls.addWidget(self.inventory_filter)
        self.inventory_view_mode = QComboBox()
        self.inventory_view_mode.addItem("Site / Work / Key", ViewMode.SITE)
        self.inventory_view_mode.addItem("Work / Site / Key", ViewMode.WORK)
        self.inventory_view_mode.currentIndexChanged.connect(
            lambda index: self.inventory_model.set_view_mode(self.inventory_view_mode.itemData(index))
        )
        controls.addWidget(self.inventory_view_mode)
        self.inventory_search = QLineEdit()
        self.inventory_search.setMinimumWidth(180)
        self.inventory_search.setPlaceholderText("Catalog tree search")
        self.inventory_search.textChanged.connect(self.inventory_model.set_search)
        controls.addWidget(self.inventory_search, 2)
        layout.addLayout(controls)
        target_controls = QHBoxLayout()
        self.target_combo = QComboBox()
        self.target_combo.setMinimumWidth(220)
        self.target_combo.currentIndexChanged.connect(self._target_changed)
        target_controls.addWidget(self.target_combo, 2)
        self.reload_button = QPushButton("Reload")
        self.reload_button.clicked.connect(self.reload)
        target_controls.addWidget(self.reload_button)
        self.add_key_button = QPushButton("Add key")
        self.add_key_button.clicked.connect(self._add_key)
        target_controls.addWidget(self.add_key_button)
        self.move_up_button = QPushButton("Work up")
        self.move_up_button.clicked.connect(lambda: self._move_archive_order(-1))
        target_controls.addWidget(self.move_up_button)
        self.move_down_button = QPushButton("Work down")
        self.move_down_button.clicked.connect(lambda: self._move_archive_order(1))
        target_controls.addWidget(self.move_down_button)
        layout.addLayout(target_controls)
        form = QFormLayout()
        self.label_edit = QLineEdit()
        self.url_edit = QLineEdit()
        self.enabled_edit = QCheckBox("有効")
        self.from_edit = QLineEdit()
        self.through_edit = QLineEdit()
        self.order_edit = QLineEdit()
        for field in (self.label_edit, self.url_edit, self.from_edit, self.through_edit, self.order_edit):
            field.textChanged.connect(self._mark_dirty)
        self.enabled_edit.stateChanged.connect(self._mark_dirty)
        form.addRow("label", self.label_edit)
        form.addRow("url", self.url_edit)
        form.addRow("enabled", self.enabled_edit)
        form.addRow("scope from_url", self.from_edit)
        form.addRow("scope through_url", self.through_edit)
        form.addRow("archive_order", self.order_edit)
        layout.addLayout(form)
        self.listing_label = QLabel("Catalog参考一覧（scope対応adapterのみ）")
        layout.addWidget(self.listing_label)
        self.fetch_listing_button = QPushButton("全話一覧を取得（CDP読取専用）")
        self.fetch_listing_button.clicked.connect(self.fetch_listing)
        layout.addWidget(self.fetch_listing_button)
        scope_controls = QHBoxLayout()
        self.select_all_button = QPushButton("Select all")
        self.select_all_button.clicked.connect(lambda: self.scope_model.set_all_checked(True))
        self.clear_all_button = QPushButton("Clear all")
        self.clear_all_button.clicked.connect(lambda: self.scope_model.set_all_checked(False))
        scope_controls.addWidget(self.select_all_button)
        scope_controls.addWidget(self.clear_all_button)
        self.range_from = QSpinBox()
        self.range_through = QSpinBox()
        for spin in (self.range_from, self.range_through):
            spin.setRange(1, 999999)
        scope_controls.addWidget(QLabel("Position"))
        scope_controls.addWidget(self.range_from)
        scope_controls.addWidget(QLabel("to"))
        scope_controls.addWidget(self.range_through)
        self.range_select_button = QPushButton("Select range")
        self.range_select_button.clicked.connect(self._select_range)
        scope_controls.addWidget(self.range_select_button)
        scope_controls.addStretch(1)
        layout.addLayout(scope_controls)
        self.scope_model = ScopeChecklistModel(parent=self)
        self.scope_model.changed.connect(self._scope_check_changed)
        self.scope_table = QTableView()
        self.scope_table.setModel(self.scope_model)
        self.scope_table.setMinimumHeight(180)
        self.scope_table.setAlternatingRowColors(True)
        layout.addWidget(self.scope_table)
        buttons = QHBoxLayout()
        self.preview_button = QPushButton("変更プレビュー")
        self.preview_button.clicked.connect(self.preview_edit)
        self.save_button = QPushButton("保存")
        self.save_button.clicked.connect(self.save_edit)
        self.full_button = QPushButton("Full Discovery")
        self.full_button.clicked.connect(self.request_full)
        self.scope_preview_button = QPushButton("Scope preview")
        self.scope_preview_button.clicked.connect(self.preview_scope_sync)
        self.scope_apply_button = QPushButton("Scope apply")
        self.scope_apply_button.clicked.connect(lambda: self.apply_scope_sync(confirm=False))
        for button in (self.preview_button, self.save_button, self.full_button, self.scope_preview_button, self.scope_apply_button):
            buttons.addWidget(button)
        outer.addLayout(buttons)
        self.status = QTextEdit()
        self.status.setReadOnly(True)
        self.status.setMinimumHeight(90)
        self.status.setMaximumHeight(160)
        outer.addWidget(self.status)

    def _set_targets(self, targets: Iterable[WatchlistTarget]) -> None:
        rows = tuple(targets)
        self.target_model.set_targets(rows)
        self.target_combo.blockSignals(True)
        self.target_combo.clear()
        for target in rows:
            self.target_combo.addItem(f"{target.key} — {target.label}", target.key)
        if rows:
            preferred = self._active_key
            index = self.target_combo.findData(preferred) if preferred else -1
            self.target_combo.setCurrentIndex(max(index, 0))
        self.target_combo.blockSignals(False)
        if rows:
            self._target_changed(self.target_combo.currentIndex())
        else:
            self._active_key = None

    def _filter_targets(self, text: str) -> None:
        needle = text.strip().casefold()
        for row in range(self.target_model.rowCount()):
            target = self.target_model.target_at(row)
            visible = not needle or target is not None and needle in (
                f"{target.key} {target.work_key} {target.site} {target.label}"
            ).casefold()
            self.target_table.setRowHidden(row, not visible)

    def _add_key(self) -> None:
        if self._dirty or self._busy():
            self.status.setPlainText("Save or discard the current edit before adding a key")
            return
        dialog = AddWatchlistKeyDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            target = dialog.target()
        except Exception as exc:  # noqa: BLE001 - form validation remains visible
            self.status.setPlainText(f"key追加停止: {exc}")
            return
        key = target.key
        if any(target.key == key for target in self.target_model.targets):
            self.status.setPlainText(f"重複keyのため追加停止: {key}")
            return
        if not all((target.key, target.work_key, target.site, target.url, target.label)):
            self.status.setPlainText("key/work_key/site/url/labelは必須です")
            return
        self.target_model.set_targets((*self.target_model.targets, target))
        self._active_key = key
        self._set_targets(self.target_model.targets)
        self._mark_dirty()

    def _move_archive_order(self, direction: int) -> None:
        if self._busy():
            return
        selected = self._selected_target()
        if selected is None:
            return
        try:
            draft = self._collect_targets()
        except (TypeError, ValueError) as exc:
            self.status.setPlainText(str(exc))
            return
        members = [target for target in draft if target.work_key == selected.work_key]
        members.sort(key=lambda target: (target.archive_order or 10**9, target.key))
        index = next(index for index, target in enumerate(members) if target.key == selected.key)
        other_index = index + direction
        if not (0 <= other_index < len(members)):
            return
        members[index], members[other_index] = members[other_index], members[index]
        order = {target.key: position for position, target in enumerate(members, 1)}
        updated = tuple(replace(target, archive_order=order[target.key]) if target.work_key == selected.work_key else target for target in draft)
        self.target_model.set_targets(updated)
        self.order_edit.setText(str(order[selected.key]))
        self._mark_dirty()

    def _busy(self) -> bool:
        return any(worker is not None for worker in (
            self._listing_worker, self._scope_worker, self._preview_worker,
            self._save_worker, self._reload_worker,
        ))

    def _start_worker(self, worker: QRunnable) -> None:
        self.set_active_job(self._active_job)
        self.thread_pool.start(worker)

    def _finish_worker(self, name: str) -> None:
        setattr(self, name, None)
        self.set_active_job(self._active_job)

    def _select_inventory_key(self, index: QModelIndex) -> None:
        node = index.internalPointer()
        key = getattr(node, "key_identity", None)
        position = self.target_combo.findData(key)
        if position >= 0:
            self.target_combo.setCurrentIndex(position)

    def _select_range(self) -> None:
        if self._listing is None:
            return
        low, high = sorted((self.range_from.value(), self.range_through.value()))
        self.scope_model.checked = {
            row.external_id for row in self.scope_model.rows if low <= row.site_position <= high
        }
        self.scope_model.layoutChanged.emit()
        self._scope_check_changed()

    def _selected_target(self) -> WatchlistTarget | None:
        key = self.target_combo.currentData()
        return next((target for target in self.target_model.targets if target.key == key), None)

    def _confirm_discard_dirty(self, action: str) -> bool:
        if not self._dirty:
            return True
        answer = QMessageBox.question(
            self,
            "Unsaved Watchlist edit",
            f"Discard unsaved edits before {action}?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Discard:
            return False
        # Discard restores the complete baseline, including rows added or
        # reordered in the in-memory model.  Resetting only the dirty bit would
        # let a later save commit a draft that the user explicitly discarded.
        self._dirty = False
        self._scope_checkbox_dirty = False
        self._draft_checked_ids = None
        self.targets = tuple(self.service.list_targets())
        self._set_targets(self.targets)
        self._listing = None
        self.scope_model.set_listing(
            ListingPreview("", "", "", None, (), False, datetime.now(UTC), None,
                           ("Fetch a complete listing for this key",)), checked=(),
        )
        self._pending_preview = None
        self._scope_edit_preview = None
        self._last_scope_preview = None
        self._scope_preview_revision = None
        self.revision = self.service.revision()
        return True

    def _target_changed(self, index: int) -> None:
        requested_key = self.target_combo.itemData(index)
        if self._busy() and requested_key != self._active_key:
            self.status.setPlainText("An asynchronous Watchlist/Catalog operation is running; wait before switching keys")
            self.target_combo.blockSignals(True)
            rollback = self.target_combo.findData(self._active_key)
            if rollback >= 0:
                self.target_combo.setCurrentIndex(rollback)
            self.target_combo.blockSignals(False)
            return
        if self._dirty and requested_key != self._active_key:
            accepted = self._confirm_discard_dirty("switching keys")
            self.target_combo.blockSignals(True)
            position = self.target_combo.findData(requested_key if accepted else self._active_key)
            if position >= 0:
                self.target_combo.setCurrentIndex(position)
            self.target_combo.blockSignals(False)
            if not accepted:
                return
        target = self._selected_target()
        if target is None:
            return
        self._active_key = target.key
        if self._listing is not None and (
            self._listing.target_key != target.key
            or self._listing.target_url != target.url
            or self._listing.site != target.site
        ):
            self._listing = None
            self.scope_model.set_listing(
                ListingPreview(target.site, target.key, target.url, None, (), False,
                               datetime.now(UTC), None,
                               ("Select Fetch to load a complete listing",)),
                checked=(),
            )
            self._scope_checkbox_dirty = False
            self.listing_label.setText("Catalog参考一覧（key変更後は再取得してください）")
        self._last_scope_preview = None
        self._pending_preview = None
        self._scope_edit_preview = None
        self._scope_preview_revision = None
        scope = target.discovery_scope
        for widget, value in (
            (self.label_edit, target.label), (self.url_edit, target.url),
            (self.from_edit, scope.from_url if scope else ""),
            (self.through_edit, scope.through_url if scope else ""),
            (self.order_edit, "" if target.archive_order is None else str(target.archive_order)),
        ):
            widget.blockSignals(True)
            widget.setText(value)
            widget.blockSignals(False)
        self.enabled_edit.blockSignals(True)
        self.enabled_edit.setChecked(target.enabled)
        self.enabled_edit.blockSignals(False)
        if self._listing is None:
            self._show_catalog_reference(target)

    def _select_target_row(self, index: QModelIndex) -> None:
        target = self.target_model.target_at(index.row())
        if target is not None:
            self.target_combo.setCurrentText(f"{target.key} — {target.label}")

    @Slot()
    def _mark_dirty(self) -> None:
        self._dirty = True
        self._pending_preview = None
        self._last_scope_preview = None
        self._scope_preview_revision = None
        self.status.setPlainText("未保存の変更があります")

    @Slot()
    def _scope_check_changed(self) -> None:
        self._scope_checkbox_dirty = True
        self._mark_dirty()

    def _show_catalog_reference(self, target: WatchlistTarget) -> None:
        rows = []
        labels = {}
        if self.snapshot is not None:
            for source in self.snapshot.sources.values():
                if source.site != target.site or source.discovery_key != target.key:
                    continue
                item = self.snapshot.items.get(source.item_id)
                locators = self.snapshot.source_targets.get(source.id, ())
                rows.append(ListingRow(
                    source.external_id, locators[0].locator if locators else "",
                    source.display_position or 0, (item.item_title or "") if item else "",
                    source.access_mode, "catalog-reference",
                ))
                labels[source.external_id] = item.status if item else "unknown"
        rows.sort(key=lambda row: row.site_position, reverse=True)
        self.scope_model.set_listing(
            ListingPreview(target.site, target.key, target.url, "catalog-reference", tuple(rows),
                           False, datetime.now(UTC), None, ("Catalog reference only",)),
            catalog_labels=labels,
        )

    def _selection_affecting_change(self, proposed: Iterable[WatchlistTarget]) -> bool:
        """Return whether this draft changes discovery membership or numbering."""

        current = {target.key: target for target in self.targets}
        for target in proposed:
            old = current.get(target.key)
            if old is None:
                continue
            if (
                old.url != target.url
                or old.discovery_scope != target.discovery_scope
                or old.archive_order != target.archive_order
            ):
                return True
        return self._scope_checkbox_dirty

    def _sibling_listing_evidence(
        self,
        proposed: Iterable[WatchlistTarget],
    ) -> tuple[dict[str, ListingPreview], dict[str, frozenset[str]]]:
        """Reuse one listing only when a sibling has the same proven page identity."""

        if self._listing is None:
            return {}, {}
        listings: dict[str, ListingPreview] = {}
        checked: dict[str, frozenset[str]] = {}
        for sibling in proposed:
            if sibling.key == self._listing.target_key:
                continue
            if sibling.site != self._listing.site or sibling.url != self._listing.target_url:
                continue
            selected = frozenset(self._checked_for_target(sibling))
            listings[sibling.key] = replace(
                self._listing,
                target_key=sibling.key,
                target_url=sibling.url,
            )
            checked[sibling.key] = selected
        return listings, checked

    def _collect_targets(self) -> tuple[WatchlistTarget, ...]:
        """Collect one immutable draft, including manual boundary edits."""
        self._draft_checked_ids = None
        selected = self._selected_target()
        if selected is None:
            return tuple(self.target_model.targets)
        saved_scope = selected.discovery_scope
        draft_url = self.url_edit.text().strip()
        from_url, through_url = self.from_edit.text().strip(), self.through_edit.text().strip()
        saved_from = saved_scope.from_url if saved_scope else ""
        saved_through = saved_scope.through_url if saved_scope else ""
        manual_scope_changed = (from_url, through_url) != (saved_from or "", saved_through or "")
        url_changed = draft_url != selected.url
        listing_scope_edit = (
            self._listing is not None
            and bool(self.scope_model.rows)
            and (self._scope_checkbox_dirty or manual_scope_changed or url_changed)
        )
        scope = saved_scope
        if listing_scope_edit:
            if draft_url != self._listing.target_url:
                raise ValueError("Complete listing belongs to a different URL; fetch the draft URL first")
            rows_by_url = {row.url: row for row in self._listing.rows}
            if self._scope_checkbox_dirty:
                checked_ids = set(self.scope_model.checked)
            elif manual_scope_changed:
                boundaries = [value for value in (from_url, through_url) if value]
                if any(value not in rows_by_url for value in boundaries):
                    raise ValueError("Manual scope boundaries must match complete-listing URLs")
                positions = [rows_by_url[value].site_position for value in boundaries]
                if positions:
                    low, high = min(positions), max(positions)
                    checked_ids = {
                        row.external_id for row in self._listing.rows
                        if low <= row.site_position <= high
                    }
                else:
                    checked_ids = {row.external_id for row in self._listing.rows}
                if saved_scope is not None:
                    checked_ids.difference_update(saved_scope.excluded_external_ids)
            else:
                # The URL changed and the newly fetched listing is authoritative;
                # map the saved range onto it before constructing the new scope.
                boundaries = [value for value in (saved_from, saved_through) if value]
                if any(value not in rows_by_url for value in boundaries):
                    raise ValueError("Saved scope boundaries are absent from the complete listing")
                positions = [rows_by_url[value].site_position for value in boundaries]
                if positions:
                    low, high = min(positions), max(positions)
                    checked_ids = {
                        row.external_id for row in self._listing.rows
                        if low <= row.site_position <= high
                    }
                else:
                    checked_ids = {row.external_id for row in self._listing.rows}
                if saved_scope is not None:
                    checked_ids.difference_update(saved_scope.excluded_external_ids)
            self._draft_checked_ids = frozenset(checked_ids)
            plan = SelectionPlanner().plan(self._listing, checked_ids)
            if not plan.ready:
                raise ValueError("Scope checkbox selection is blocked: " + "; ".join(plan.blockers))
            scope = plan.discovery_scope
        elif from_url or through_url or (saved_scope and saved_scope.excluded_external_ids):
            if selected.site != "magapoke" and saved_scope != DiscoveryScope(
                from_url=from_url or None,
                through_url=through_url or None,
                excluded_external_ids=saved_scope.excluded_external_ids if saved_scope else (),
            ):
                raise ValueError(f"Site {selected.site!r} has no verified GUI scope capability")
            scope = DiscoveryScope(
                from_url=from_url or None,
                through_url=through_url or None,
                excluded_external_ids=saved_scope.excluded_external_ids if saved_scope else (),
            )
        else:
            scope = None
        try:
            order = self.order_edit.text().strip()
            archive_order = None if not order else int(order)
        except ValueError as exc:
            raise ValueError("archive_order must be an integer") from exc
        updated = replace(
            selected,
            label=self.label_edit.text(),
            url=draft_url,
            enabled=self.enabled_edit.isChecked(),
            discovery_scope=scope,
            archive_order=archive_order,
        )
        return tuple(updated if target.key == selected.key else target for target in self.target_model.targets)

    def preview_edit(self) -> WatchlistEditPreview:
        if self._busy():
            return WatchlistEditPreview(self.revision, tuple(self.target_model.targets), (), ("Wait for the current operation",))
        try:
            proposed = self._collect_targets()
            preview = self.service.preview_edit(proposed, expected_revision=self.revision)
        except (TypeError, ValueError) as exc:
            self.status.setPlainText(f"プレビュー停止: {exc}")
            preview = WatchlistEditPreview(
                current_revision=self.revision,
                targets=tuple(self.target_model.targets),
                changed_keys=(),
                blockers=(str(exc),),
            )
        self._scope_edit_preview = None
        self._scope_preview_revision = None
        selected = self._selected_target()
        selection_affecting = preview.ready and self._selection_affecting_change(proposed)
        if selection_affecting and self._listing is None:
            preview = WatchlistEditPreview(
                current_revision=preview.current_revision,
                targets=preview.targets,
                changed_keys=preview.changed_keys,
                blockers=("Complete listing is required before saving a scope, URL, or archive-order edit",),
            )
        if self._listing is not None and selected is not None and selection_affecting and preview.ready:
            proposed_selected = next(target for target in proposed if target.key == selected.key)
            if self._preview_worker is not None:
                self.status.setPlainText("Catalog-bound scope preview is already running")
                return preview
            self._generation += 1
            if self.catalog_path is None or self._catalog_guard is None:
                preview = WatchlistEditPreview(
                    current_revision=preview.current_revision,
                    targets=preview.targets,
                    changed_keys=preview.changed_keys,
                    blockers=("Catalog snapshot is required for scope-affecting edits",),
                )
            else:
                sibling_listings, sibling_checked = self._sibling_listing_evidence(proposed)
                self._preview_worker = _EditorPreviewWorker(
                    target=proposed_selected,
                    listing=self._listing,
                    checked=self._draft_checked_ids or frozenset(self.scope_model.checked),
                    watchlist_revision=self.revision,
                    archive_targets=tuple(proposed),
                    saved_archive_targets=tuple(self.targets),
                    catalog_path=self.catalog_path,
                    generation=self._generation,
                    sibling_listings=sibling_listings,
                    sibling_checked_external_ids=sibling_checked,
                )
            if self._preview_worker is None:
                self._pending_preview = preview
                return preview
            self._preview_worker.signals.succeeded.connect(self._editor_preview_succeeded, Qt.ConnectionType.QueuedConnection)
            self._preview_worker.signals.failed.connect(self._editor_preview_failed, Qt.ConnectionType.QueuedConnection)
            self._start_worker(self._preview_worker)
            preview = WatchlistEditPreview(
                current_revision=preview.current_revision,
                targets=preview.targets,
                changed_keys=preview.changed_keys,
                blockers=("Catalog-bound scope preview is running",),
            )
        self._pending_preview = preview
        self._preview_catalog_guard = self._path_guard(self.catalog_path)
        changed = ", ".join(preview.changed_keys) or "変更なし"
        scope_text = ""
        if self._scope_edit_preview is not None:
            scope_text = (
                f"\n話数: add={self._scope_edit_preview.new_count} "
                f"keep={self._scope_edit_preview.retained_count} "
                f"remove={self._scope_edit_preview.removed_count} "
                f"unknown={self._scope_edit_preview.unknown_count}"
            )
        self.status.setPlainText(f"保存前プレビュー: {changed}{scope_text}\nCatalog・ZIP・権利・Watchlistは変更していません")
        return preview

    @Slot(object)
    def _editor_preview_succeeded(self, result: object) -> None:
        if self._closed or not isinstance(result, tuple) or len(result) != 2:
            return
        generation, preview = result
        if self._preview_worker is not None and self._preview_worker.generation == generation:
            self._finish_worker("_preview_worker")
        if generation != self._generation or not isinstance(preview, ScopeEditPreview):
            return
        self._scope_edit_preview = preview
        self.scope_model.catalog_details = {
            row.external_id: (
                "unknown" if row.current_acquisition_enabled is None else str(row.current_acquisition_enabled),
                "unknown" if row.proposed_acquisition_enabled is None else str(row.proposed_acquisition_enabled),
                row.change,
            )
            for row in preview.rows
        }
        self.scope_model.layoutChanged.emit()
        if self._pending_preview is not None:
            blockers = tuple(
                blocker
                for blocker in self._pending_preview.blockers
                if blocker != "Catalog-bound scope preview is running"
            )
            self._pending_preview = WatchlistEditPreview(
                current_revision=self._pending_preview.current_revision,
                targets=self._pending_preview.targets,
                changed_keys=self._pending_preview.changed_keys,
                blockers=tuple(dict.fromkeys((*blockers, *preview.blockers))),
            )
        archive = preview.archive_order_preview or {}
        archive_changes = archive.get("number_changes", ())
        renumber = archive.get("renumber_required_source_ids", ())
        details = [
            (f"Scope preview: selected={preview.selected_count} excluded={preview.excluded_count} "
             f"add={preview.new_count} keep={preview.retained_count} remove={preview.removed_count} "
             f"unknown={preview.unknown_count}"),
            f"archive number changes={len(archive_changes)} renumber_required={len(renumber)}",
        ]
        if preview.blockers:
            details.append("BLOCKED: " + " / ".join(preview.blockers[:6]))
        if preview.warnings:
            details.append("Warnings: " + " / ".join(preview.warnings[:6]))
        details.extend(
            f"Source {row['source_id']}: number {row['from']} -> {row['to']}"
            for row in archive_changes
        )
        details.extend(
            f"ZIP Source {row['source_id']}: {row['current_stem']} -> {row['expected_stem']} "
            f"(state={row['state']}, renumber={row['renumber_required']})"
            for row in archive.get("artifacts", ())
        )
        details.append("保存後、穴の除外は即時拒否。外側の範囲変更はFull/Scope適用待ち。既存ZIPの改名は別途必要です。")
        self.status.setPlainText("\n".join(details))

    @Slot(str)
    def _editor_preview_failed(self, message: str) -> None:
        self._finish_worker("_preview_worker")
        if self._closed:
            return
        self._scope_edit_preview = None
        self._pending_preview = WatchlistEditPreview(
            current_revision=self.revision,
            targets=tuple(self.target_model.targets),
            changed_keys=(),
            blockers=(message,),
        )
        self.status.setPlainText("Catalog-bound scope preview停止: " + message)

    @property
    def scope_edit_preview(self) -> ScopeEditPreview | None:
        """Latest immutable Stage 03 scope preview consumed by the editor."""

        return self._scope_edit_preview

    def save_edit(self) -> tuple[WatchlistTarget, ...] | None:
        if self._active_job or self._busy():
            self.status.setPlainText("実行中Jobがあるため保存を停止しました")
            return None
        try:
            proposed = self._collect_targets()
            if self._pending_preview is None or not self._pending_preview.ready:
                self.status.setPlainText("保存前に変更プレビューを確認してください")
                return None
            selection_affecting = self._selection_affecting_change(proposed)
            if selection_affecting:
                if self._scope_edit_preview is None or not self._scope_edit_preview.ready:
                    self.status.setPlainText("Scope previewが未確定のため保存を停止しました")
                    return None
                if not self._scope_edit_preview.is_fresh():
                    self.status.setPlainText("Scope previewが古いため再プレビューしてください")
                    return None
                if self._scope_edit_preview.proposed_target != next(
                    target for target in proposed if target.key == self._scope_edit_preview.proposed_target.key
                ):
                    self.status.setPlainText("Scope preview縺ｨ邱ｨ髮・螳ｹ縺悟､峨ｏ繧翫∪縺励◆")
                    return None
            if tuple(self._pending_preview.targets) != tuple(proposed):
                self.status.setPlainText("プレビュー後に編集内容が変わりました。再プレビューしてください")
                return None
            if self._catalog_guard != self._path_guard(self.catalog_path):
                self.status.setPlainText("Catalog path pairが変わったため再読込してください")
                return None
            if self._preview_catalog_guard != self._path_guard(self.catalog_path):
                self.status.setPlainText("プレビュー後にCatalog path pairが変わりました。再プレビューしてください")
                return None
            if self._save_worker is not None:
                self.status.setPlainText("保存中です")
                return None
            self._generation += 1
            if selection_affecting and (
                self.catalog_path is None
                or self._catalog_guard is None
                or not self.catalog_path.is_file()
            ):
                self.status.setPlainText("Catalog snapshot is required for scope-affecting edits")
                return None
            self._save_worker = _SaveWorker(
                self.watchlist_path,
                proposed,
                self.revision,
                self.catalog_path if selection_affecting else None,
                self._catalog_guard if selection_affecting else None,
                self._generation,
                self._scope_edit_preview if selection_affecting else None,
            )
            self._save_worker.signals.succeeded.connect(self._save_succeeded, Qt.ConnectionType.QueuedConnection)
            self._save_worker.signals.failed.connect(self._save_failed, Qt.ConnectionType.QueuedConnection)
            self.status.setPlainText("保存中（Watchlist lock/CAS）")
            self._start_worker(self._save_worker)
            return None
        except Exception as exc:  # noqa: BLE001 - user-visible editor boundary
            self.status.setPlainText(f"保存停止: {exc}")
            return None
    @Slot(object)
    def _save_succeeded(self, result: object) -> None:
        if self._closed or not isinstance(result, tuple) or len(result) != 2:
            return
        generation, saved = result
        if generation != self._generation:
            return
        self._finish_worker("_save_worker")
        self.targets = tuple(saved)
        self.revision = self.service.revision()
        self._dirty = False
        self._set_targets(self.targets)
        self._catalog_guard = self._path_guard(self.catalog_path)
        self._pending_preview = None
        self._scope_edit_preview = None
        self.status.setPlainText("保存済み。Full Discovery / scope-syncが必要な範囲変更は未反映です")

        self.watchlistSaved.emit()
    @Slot(str)

    def _save_failed(self, message: str) -> None:
        self._finish_worker("_save_worker")
        if self._closed:
            return
        self.status.setPlainText("保存停止: " + message)

    def set_listing(self, listing: ListingPreview, *, checked: Iterable[str] = ()) -> None:
        self._listing = listing
        labels = {}
        if self.snapshot is not None:
            for source in self.snapshot.sources.values():
                if source.discovery_key == listing.target_key and source.site == listing.site:
                    labels[source.external_id] = "Catalog登録済み"
        self.scope_model.set_listing(listing, checked=checked, catalog_labels=labels)
        self._scope_checkbox_dirty = False
        self.listing_label.setText(f"全話一覧: {len(listing.rows)}件（チェック状態は実行選択と独立）")

    def set_active_job(self, active: bool) -> None:
        self._active_job = active
        editable = not active and not self._busy()
        for widget in (
            self.save_button, self.full_button, self.scope_apply_button, self.scope_preview_button,
            self.preview_button, self.fetch_listing_button, self.add_key_button,
            self.move_up_button, self.move_down_button, self.label_edit, self.url_edit,
            self.enabled_edit, self.from_edit, self.through_edit, self.order_edit,
            self.scope_table, self.select_all_button, self.clear_all_button,
            self.range_from, self.range_through, self.range_select_button,
        ):
            widget.setEnabled(editable)
        self.target_combo.setEnabled(not self._busy())
        self.reload_button.setEnabled(not self._busy())

    def request_full(self) -> None:
        target = self._selected_target()
        if target is None or self._active_job or self._busy():
            return
        if self._dirty:
            self.status.setPlainText("Save or discard unsaved edits before Full Discovery")
            return
        self.fullRequested.emit(target.key)

    def preview_scope_sync(self) -> ScopeSyncPreview | None:
        if self._busy():
            return None
        target = self._selected_target()
        if target is None or self.catalog_path is None:
            self.status.setPlainText("Scope previewにはCatalogとkeyが必要です")
            return None
        if self._dirty:
            self.status.setPlainText("未保存の編集があります。保存後にScope previewしてください")
            return None
        if self._scope_worker is not None:
            self.status.setPlainText("Scope操作が実行中です")
            return None
        self._generation += 1
        self._scope_worker = _ScopeWorker(
            self.watchlist_path, self.catalog_path, target.work_key, generation=self._generation
        )
        self._scope_worker.signals.succeeded.connect(self._scope_preview_succeeded, Qt.ConnectionType.QueuedConnection)
        self._scope_worker.signals.failed.connect(self._scope_failed, Qt.ConnectionType.QueuedConnection)
        self.status.setPlainText("Scope preview中（Catalog読み取り専用）")
        self._start_worker(self._scope_worker)
        return None

    @Slot(object)
    def _scope_preview_succeeded(self, result: object) -> None:
        if self._closed:
            return
        if not isinstance(result, tuple) or len(result) != 2:
            self._scope_failed("Scope preview returned an invalid result")
            return
        generation, result = result
        if self._scope_worker is not None and self._scope_worker.generation == generation:
            self._finish_worker("_scope_worker")
        if generation != self._generation:
            return
        if not isinstance(result, ScopeSyncPreview):
            self._scope_failed("Scope preview returned an invalid result")
            return
        self._last_scope_preview = result
        self._scope_preview_revision = WatchlistService(self.watchlist_path).revision()
        self._scope_apply_confirmed = False
        self.scopePreviewRequested.emit(result.work_key)
        self.status.setPlainText(
            f"Scope preview: changes={len(result.changes)} blockers={len(result.blockers)}\n"
            + "\n".join(result.blockers[:8])
        )

    @Slot(str)
    def _scope_failed(self, message: str) -> None:
        if self._closed:
            return
        self._finish_worker("_scope_worker")
        self.status.setPlainText("Scope操作停止: " + message)

    def apply_scope_sync(self, *, confirm: bool = False) -> bool:
        if self._busy() or self._dirty:
            return False
        if self._active_job or self._last_scope_preview is None:
            self.status.setPlainText("新しいScope previewを確認してからapplyしてください")
            return False
        if not self._last_scope_preview.ready:
            self.status.setPlainText("Scope apply blocked: " + " / ".join(self._last_scope_preview.blockers))
            return False
        target = self._selected_target()
        if target is None or self.catalog_path is None:
            return False
        if target.work_key != self._last_scope_preview.work_key:
            self.status.setPlainText("Selected Work changed; rerun Scope preview")
            return False
        current_keys = tuple(sorted(
            row.key for row in self.target_model.targets if row.work_key == target.work_key
        ))
        if tuple(sorted(self._last_scope_preview.discovery_keys)) != current_keys:
            self.status.setPlainText("Watchlist keys changed; rerun Scope preview")
            return False
        if self._scope_preview_revision != WatchlistService(self.watchlist_path).revision():
            self.status.setPlainText("Watchlist changed since Scope preview; reload and retry")
            return False
        if not confirm:
            changes = self._last_scope_preview.changes
            blockers = self._last_scope_preview.blockers
            summary = (
                f"Work {target.work_key}: {len(changes)} Catalog flag changes\n"
                + "\n".join(
                    f"{change.site}/{change.external_id}: {change.before} -> {change.after}"
                    for change in changes[:12]
                )
            )
            if blockers:
                summary += "\nBLOCKED: " + " / ".join(blockers[:8])
            answer = QMessageBox.question(
                self,
                "Confirm Scope apply",
                summary + "\n\nApply this read-only preview to Catalog?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.status.setPlainText("Scope apply cancelled; Catalog unchanged")
                return False
            return self.apply_scope_sync(confirm=True)
        if self._scope_worker is not None:
            self.status.setPlainText("Scope操作が実行中です")
            return False
        self._scope_worker = _ScopeWorker(
            self.watchlist_path, self.catalog_path, target.work_key, self._last_scope_preview,
            generation=self._generation,
        )
        self._scope_worker.signals.succeeded.connect(self._scope_apply_succeeded, Qt.ConnectionType.QueuedConnection)
        self._scope_worker.signals.failed.connect(self._scope_failed, Qt.ConnectionType.QueuedConnection)
        self.status.setPlainText("Scope apply中（Catalog lock/CAS）")
        self._start_worker(self._scope_worker)
        return True

    @Slot(object)
    def _scope_apply_succeeded(self, result: object) -> None:
        if self._closed:
            return
        work_key = self._scope_worker.work_key if self._scope_worker is not None else ""
        self._finish_worker("_scope_worker")
        if not isinstance(result, tuple) or len(result) != 2:
            self._scope_failed("Scope apply returned an invalid result")
            return
        generation, _result = result
        if generation != self._generation:
            # Apply may already have committed. Never label the older snapshot
            # as current; read the committed state before showing it again.
            self.reload()
            return
        self._last_scope_preview = None
        self._scope_preview_revision = None
        self.scopeApplied.emit(work_key)
        self.status.setPlainText("Scope apply完了。Catalog flagsを反映しました")

    def reload(self) -> None:
        if self._busy():
            self.status.setPlainText("An asynchronous Watchlist/Catalog operation is running; wait before reload")
            return
        if not self._confirm_discard_dirty("reloading"):
            return
        self.targets = tuple(self.service.list_targets())
        self._listing = None
        self._set_targets(self.targets)
        self.revision = self.service.revision()
        self._catalog_guard = self._path_guard(self.catalog_path)
        self._dirty = False
        self._pending_preview = None
        self._scope_edit_preview = None
        self._scope_preview_revision = None
        self.status.setPlainText("再読込しました")
        if self.catalog_path is not None and self.catalog_path.is_file():
            self._generation += 1
            self._reload_worker = _InventoryWorker(
                self.catalog_path, self.watchlist_path, self.runtime_path, self._generation
            )
            self._reload_worker.signals.succeeded.connect(self._reload_succeeded, Qt.ConnectionType.QueuedConnection)
            self._reload_worker.signals.failed.connect(self._reload_failed, Qt.ConnectionType.QueuedConnection)
            self.set_active_job(self._active_job)
            self._start_worker(self._reload_worker)

    @Slot(object)
    def _reload_succeeded(self, result: object) -> None:
        generation, snapshot = result
        if self._closed or generation != self._generation:
            return
        self._reload_worker = None
        self.receive_snapshot(snapshot)
        self.set_active_job(self._active_job)
        self.catalogReloadRequested.emit()

    @Slot(str)
    def _reload_failed(self, message: str) -> None:
        self._reload_worker = None
        self.set_active_job(self._active_job)
        self.status.setPlainText("Catalog reload blocked: " + message)

    def receive_snapshot(self, snapshot: InventorySnapshot) -> None:
        if (self.catalog_path is None or Path(snapshot.catalog_path).resolve() != self.catalog_path.resolve()
                or Path(snapshot.watchlist_path).resolve() != self.watchlist_path.resolve()):
            self.status.setPlainText("Snapshot path pair differs; reload the editor")
            return
        if self._preview_worker is not None or self._scope_worker is not None:
            self._generation += 1  # An older result must not revive a cleared preview.
        self.snapshot = snapshot
        self.inventory_model.set_snapshot(snapshot)
        self.inventory_tree.expandToDepth(1)
        self._catalog_guard = self._path_guard(self.catalog_path)
        self._pending_preview = None
        self._scope_edit_preview = None
        self._last_scope_preview = None
        self._scope_preview_revision = None
        self.scope_model.catalog_details = {}
        self.scope_model.layoutChanged.emit()
        self.status.setPlainText("Catalog再読込: 以前のプレビューは無効です。再プレビューしてください。既存ZIPは改名していません。")
        if self._listing is None and (target := self._selected_target()) is not None:
            self._show_catalog_reference(target)

    def closeEvent(self, event: Any) -> None:
        if self._busy():
            self.status.setPlainText("An asynchronous Watchlist/Catalog operation is running; wait before closing")
            event.ignore()
            return
        if self._dirty:
            answer = QMessageBox.question(
                self,
                "未保存のWatchlist編集",
                "未保存の変更を破棄して閉じますか？",
                QMessageBox.StandardButton.Close | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Close:
                event.ignore()
                return
        self._closed = True
        self._generation += 1
        self._finish_worker("_listing_worker")
        self._finish_worker("_scope_worker")
        self._finish_worker("_preview_worker")
        self._finish_worker("_save_worker")
        event.accept()

    def fetch_listing(self) -> None:
        target = self._selected_target()
        if target is None or self._active_job or self._busy():
            self.status.setPlainText("keyを選択し、実行中Jobがない状態で一覧を取得してください")
            return
        self.fetch_listing_button.setEnabled(False)
        self.listing_label.setText("全話一覧を取得中（Catalog/Watchlist/権利は変更しません）")
        self._generation += 1
        draft_url = self.url_edit.text().strip()
        if draft_url != target.url:
            target = replace(target, url=draft_url)
        worker = _ListingWorker(target, self._generation)
        self._listing_worker = worker
        worker.signals.succeeded.connect(self._listing_succeeded, Qt.ConnectionType.QueuedConnection)
        worker.signals.failed.connect(self._listing_failed, Qt.ConnectionType.QueuedConnection)
        self._start_worker(worker)

    @Slot(object)
    def _listing_succeeded(self, listing: object) -> None:
        if self._closed:
            return
        if not isinstance(listing, tuple) or len(listing) != 2:
            self._listing_failed("Discovery adapter returned an invalid listing preview")
            return
        generation, listing = listing
        if generation != self._generation:
            return
        self._finish_worker("_listing_worker")
        self.fetch_listing_button.setEnabled(True)
        if not isinstance(listing, ListingPreview):
            self._listing_failed("Discovery adapter returned an invalid listing preview")
            return
        target = self._selected_target()
        draft_url = self.url_edit.text().strip() if target is not None else ""
        if target is None or listing.site != target.site or listing.target_key != target.key or listing.target_url != draft_url:
            self._listing_failed("Complete listing identity does not match the selected Watchlist key")
            return
        self.set_listing(listing, checked=self._checked_for_target(target, listing=listing))
        if listing.blockers:
            self.status.setPlainText("一覧取得は未確定です: " + " / ".join(listing.blockers))
        else:
            self.status.setPlainText(f"全話一覧を取得しました: {len(listing.rows)}件。チェック後にプレビューしてください")

    @Slot(str)
    def _listing_failed(self, message: str) -> None:
        if self._closed:
            return
        self._finish_worker("_listing_worker")
        self.fetch_listing_button.setEnabled(True)
        self.listing_label.setText("Catalog参考一覧（scope対応adapterのみ）")
        self.status.setPlainText("一覧取得停止: " + message)

    def _checked_for_target(
        self, target: WatchlistTarget, *, listing: ListingPreview | None = None
    ) -> tuple[str, ...]:
        current_listing = listing or self._listing
        if current_listing is None:
            return ()
        scope = target.discovery_scope
        excluded = set(scope.excluded_external_ids) if scope is not None else set()
        rows = tuple(current_listing.rows)
        if scope is None:
            return tuple(row.external_id for row in rows)
        by_url = {row.url: index for index, row in enumerate(rows)}
        boundaries = [value for value in (scope.from_url, scope.through_url) if value]
        if any(value not in by_url for value in boundaries):
            return ()
        start = by_url.get(scope.from_url, 0)
        end = by_url.get(scope.through_url, len(rows) - 1)
        if start > end:
            return ()
        return tuple(row.external_id for row in rows[start:end + 1] if row.external_id not in excluded)


__all__ = ["ScopeChecklistModel", "WatchlistEditorModel", "WatchlistEditorPage"]
