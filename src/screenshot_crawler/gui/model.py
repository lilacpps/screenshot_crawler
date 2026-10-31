"""Qt models for the read-only inventory projection.

The model owns only a small tree of sites, works, and keys.  Item and crawl
history rows are kept out of the tree and are materialised by ``DetailPane``
when a key is focused.  This keeps a large catalog responsive and, more
importantly, keeps selection independent from filtering and projection mode.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from PySide6.QtCore import QAbstractItemModel, QModelIndex, QSortFilterProxyModel, Qt, Signal

from screenshot_crawler.management.inventory import aware_timestamp, display_time
from screenshot_crawler.management.models import (
    InventoryCounts,
    InventorySnapshot,
    InventorySummary,
    KeyInventory,
)

NODE_ROLE = Qt.ItemDataRole.UserRole + 1
IDENTITY_ROLE = Qt.ItemDataRole.UserRole + 2
DISCOVERY_COLUMN = 10
DISCOVERY_ROLE = Qt.ItemDataRole.UserRole + 3
DISCOVERY_HELP = "Discovery対象の設定です。Batchの取得対象には影響しません。"


class ViewMode(StrEnum):
    SITE = "site"
    WORK = "work"


class StatusFilter(StrEnum):
    ALL = "all"
    DIRECT = "direct"
    QUOTA = "quota"
    UNFINISHED = "unfinished"
    REVIEW = "review"
    OUT_OF_SCOPE = "out_of_scope"


@dataclass(slots=True)
class TreeNode:
    node_id: str
    kind: str
    label: str
    site: str | None = None
    work_key: str | None = None
    key_identity: str | None = None
    title: str = ""
    parent: TreeNode | None = None
    children: list[TreeNode] = field(default_factory=list)
    _visible_cache: bool | None = None

    def descendants(self) -> Iterable[TreeNode]:
        for child in self.children:
            yield child
            yield from child.descendants()

    def key_descendants(self) -> Iterable[TreeNode]:
        for node in self.descendants():
            if node.kind == "key" and node.key_identity is not None:
                yield node


def _count_text(value: int | None, *, stale: bool = False) -> str:
    if value is None:
        return "—"
    return f"~{value}" if stale else str(value)


def _summary_counts(summary: InventorySummary | None) -> InventoryCounts | None:
    return summary.counts if summary is not None else None


class InventoryTreeModel(QAbstractItemModel):
    """Site/work/key projection with stable Watchlist-key selection."""

    checkedKeysChanged = Signal(object)
    selectionRemoved = Signal(object)
    focusNodeChanged = Signal(object)
    discoveryToggleRequested = Signal(str, bool)

    HEADERS = (
        "実行対象", "取得済 / 対象", "直取候補", "Quota対象残", "有償未取得",
        "状態", "最終確認", "外部取得", "スキップ", "担当外Source", "Discovery",
    )

    def __init__(self, snapshot: InventorySnapshot | None = None, parent: Any = None) -> None:
        super().__init__(parent)
        self.snapshot: InventorySnapshot | None = None
        self.view_mode = ViewMode.SITE
        self.status_filter = StatusFilter.ALL
        self.search_text = ""
        self.sort_column = 0
        self.sort_order = Qt.SortOrder.AscendingOrder
        self.checked_keys: set[str] = set()
        self.focused_node_id: str | None = None
        self.root = TreeNode("root", "root", "")
        self._nodes: dict[str, TreeNode] = {"root": self.root}
        self._key_by_id: dict[str, KeyInventory] = {}
        self._key_by_identity: dict[str, KeyInventory] = {}
        self._key_order: dict[str, int] = {}
        # Only MainWindow opts into writes; editor Inventory trees stay read-only.
        self.discovery_guard: Callable[[], str] = lambda: "メイン画面から変更してください"
        self.discovery_pending_key: str | None = None
        if snapshot is not None:
            self.set_snapshot(snapshot)

    # --- snapshot / projection -------------------------------------------------

    def set_snapshot(self, snapshot: InventorySnapshot | None) -> None:
        old_checked = set(self.checked_keys)
        old_focus_id = self.focused_node_id
        removed: set[str] = set()
        self.beginResetModel()
        self.snapshot = snapshot
        self.root = TreeNode("root", "root", "")
        self._nodes = {"root": self.root}
        self._key_by_id = {}
        self._key_by_identity = {}
        self._key_order = {}
        if snapshot is not None:
            for position, key in enumerate(snapshot.keys):
                self._key_by_identity.setdefault(key.identity, key)
                self._key_order.setdefault(key.identity, position)
            available = {key.identity for key in snapshot.keys if key.target is not None}
            self.checked_keys = available & old_checked
            removed = old_checked - available
            self._build_projection()
        else:
            self.checked_keys = set()
        if self.focused_node_id not in self._nodes:
            self.focused_node_id = None
        self.endResetModel()
        self.checkedKeysChanged.emit(frozenset(self.checked_keys))
        if removed:
            self.selectionRemoved.emit(frozenset(removed))
        if old_focus_id and not self.focused_node_id:
            self.focusNodeChanged.emit(None)

    def set_view_mode(self, mode: ViewMode | str) -> None:
        mode = ViewMode(mode)
        if mode == self.view_mode:
            return
        old_focus = self._nodes.get(self.focused_node_id or "")
        focus_identity = old_focus.key_identity if old_focus and old_focus.kind == "key" else None
        focus_work = old_focus.work_key if old_focus else None
        self.beginResetModel()
        self.view_mode = mode
        self.root = TreeNode("root", "root", "")
        self._nodes = {"root": self.root}
        self._key_by_id = {}
        self._build_projection()
        self.endResetModel()
        self.focused_node_id = next(
            (node.node_id for node in self._nodes.values() if focus_identity and node.key_identity == focus_identity),
            next((node.node_id for node in self._nodes.values() if focus_work and node.work_key == focus_work and node.kind == "work"), None),
        )
        if self.focused_node_id is not None:
            self.focusNodeChanged.emit(self._nodes[self.focused_node_id])

    def set_search(self, text: str) -> None:
        self.search_text = text.strip().casefold()
        self.beginResetModel()
        self._invalidate_visibility()
        self.endResetModel()

    def set_status_filter(self, value: StatusFilter | str) -> None:
        self.status_filter = StatusFilter(value)
        self.beginResetModel()
        self._invalidate_visibility()
        self.endResetModel()

    def set_checked_keys(self, identities: Iterable[str]) -> None:
        """Replace selection using stable Watchlist identities."""
        self.checked_keys = set(identities) & self.all_key_identities()
        self._emit_check_updates()

    @property
    def selected_keys(self) -> frozenset[str]:
        return frozenset(self.checked_keys)

    def focus_node(self, node: TreeNode | QModelIndex | None) -> None:
        resolved = self._node(node) if isinstance(node, QModelIndex) else node
        self.focused_node_id = resolved.node_id if resolved is not None else None
        self.focusNodeChanged.emit(resolved)

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        self.sort_column = column
        self.sort_order = order
        self.beginResetModel()
        self._sort_children(self.root)
        self.endResetModel()

    def _build_projection(self) -> None:
        if self.snapshot is None:
            return
        keys = [key for key in self.snapshot.keys]
        groups: dict[str, TreeNode] = {}
        if self.view_mode is ViewMode.SITE:
            keys.sort(key=lambda key: (key.site.casefold(), key.work_key.casefold(), self._archive_sort(key)))
            for key in keys:
                site = groups.get(key.site)
                if site is None:
                    site = TreeNode(f"site:{key.site}", "site", key.site, site=key.site)
                    groups[key.site] = site
                    self._append(self.root, site)
                work_id = f"{site.node_id}/work:{key.work_key}"
                work = next((child for child in site.children if child.node_id == work_id), None)
                if work is None:
                    work = TreeNode(work_id, "work", key.title or key.work_key, site=key.site, work_key=key.work_key, title=key.title)
                    self._append(site, work)
                self._append_key(work, key)
        else:
            keys.sort(key=lambda key: (key.work_key.casefold(), key.site.casefold(), self._archive_sort(key)))
            for key in keys:
                work = groups.get(key.work_key)
                if work is None:
                    work = TreeNode(f"work:{key.work_key}", "work", key.title or key.work_key, work_key=key.work_key, title=key.title)
                    groups[key.work_key] = work
                    self._append(self.root, work)
                site_id = f"{work.node_id}/site:{key.site}"
                site = next((child for child in work.children if child.node_id == site_id), None)
                if site is None:
                    site = TreeNode(site_id, "site", key.site, site=key.site, work_key=key.work_key, title=key.title)
                    self._append(work, site)
                self._append_key(site, key)
        self._sort_children(self.root)

    def _append(self, parent: TreeNode, node: TreeNode) -> None:
        node.parent = parent
        parent.children.append(node)
        self._nodes[node.node_id] = node

    def _append_key(self, parent: TreeNode, key: KeyInventory) -> None:
        label = key.label or key.identity
        if key.target is not None and not key.target.enabled:
            label += " (Discovery無効)"
        node = TreeNode(
            f"{parent.node_id}/key:{key.identity}",
            "key",
            label,
            site=key.site,
            work_key=key.work_key,
            key_identity=key.identity,
            title=key.title,
        )
        self._append(parent, node)
        self._key_by_id[node.node_id] = key

    def _archive_sort(self, key: KeyInventory) -> tuple[int, int, str]:
        order = key.target.archive_order if key.target is not None and key.target.archive_order is not None else 10**9
        return order, self._key_order.get(key.identity, 10**9), key.identity.casefold()

    def _sort_children(self, parent: TreeNode) -> None:
        reverse = self.sort_order == Qt.SortOrder.DescendingOrder
        if self.sort_column == 0:
            def default_key(node: TreeNode) -> tuple[Any, ...]:
                if node.kind == "key":
                    key = self._key_by_id.get(node.node_id)
                    if key is not None and key.target is not None and key.target.archive_order is not None:
                        return (0, key.target.archive_order, node.label.casefold())
                    return (1, self._key_order.get(key.identity if key else "", 10**9), node.label.casefold())
                return (0, node.label.casefold())
            parent.children.sort(key=default_key, reverse=reverse)
        else:
            parent.children.sort(key=lambda node: self._sort_value(node, self.sort_column), reverse=reverse)
        for child in parent.children:
            self._sort_children(child)

    def _sort_value(self, node: TreeNode, column: int) -> int | float | str:
        if column == DISCOVERY_COLUMN:
            targets = self.discovery_targets(node)
            return sum(target.enabled for target in targets) / len(targets) if targets else -1
        summary = self.summary_for(node)
        counts = _summary_counts(summary)
        if counts is None:
            return -1 if column in (1, 2, 3, 4, 6, 7, 8, 9) else ""
        if column in (1, 2, 3, 4, 7, 8, 9):
            return {
                1: counts.completed, 2: counts.direct, 3: counts.quota, 4: counts.paid,
                7: counts.external, 8: counts.skipped, 9: counts.out_of_scope,
            }[column]
        if column == 6:
            try:
                value = aware_timestamp(summary.last_access if summary else None)
                return value.timestamp() if value else -1
            except (TypeError, ValueError, AttributeError):
                return -1
        return self._status_label(summary, counts).casefold()

    # --- filtering -------------------------------------------------------------

    def _invalidate_visibility(self) -> None:
        for node in self._nodes.values():
            node._visible_cache = None

    def _text_matches(self, node: TreeNode) -> bool:
        if not self.search_text:
            return True
        haystack = " ".join((node.label, node.title, node.site or "", node.work_key or "", node.key_identity or "")).casefold()
        return self.search_text in haystack

    def _status_matches(self, node: TreeNode) -> bool:
        if node.kind == "root":
            return True
        summary = self.summary_for(node)
        counts = _summary_counts(summary)
        if self.status_filter is StatusFilter.ALL:
            return True
        if counts is None:
            return self.status_filter is StatusFilter.REVIEW
        if self.status_filter is StatusFilter.DIRECT:
            return counts.direct > 0
        if self.status_filter is StatusFilter.QUOTA:
            return counts.quota > 0
        if self.status_filter is StatusFilter.UNFINISHED:
            terminal = counts.completed + counts.external + counts.skipped
            return counts.total_assigned > terminal
        if self.status_filter is StatusFilter.OUT_OF_SCOPE:
            return counts.out_of_scope > 0
        return bool(summary and (summary.sync_status not in ("synced", "ok") or summary.diagnostics or counts.unknown))

    def _matches(self, node: TreeNode) -> bool:
        return self._text_matches(node) and self._status_matches(node)

    def _status_visible_subtree(self, node: TreeNode) -> bool:
        return self._status_matches(node) or any(self._status_visible_subtree(child) for child in node.children)

    def _is_visible(self, node: TreeNode) -> bool:
        if node._visible_cache is not None:
            return node._visible_cache
        own = self._matches(node)
        child = any(self._is_visible(c) for c in node.children)
        node._visible_cache = own or child
        return node._visible_cache

    def visible_children(self, parent: TreeNode) -> list[TreeNode]:
        if parent.kind != "root" and self._text_matches(parent) and self.search_text:
            # A matching parent retains its complete context, while the status
            # filter still applies to descendants.
            return [child for child in parent.children if self._status_visible_subtree(child)]
        return [child for child in parent.children if self._is_visible(child)]

    # --- Qt model ---------------------------------------------------------------

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return len(self.HEADERS)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        if parent.isValid() and parent.column() != 0:
            return 0
        node = self._node(parent)
        return len(self.visible_children(node)) if node is not None else 0

    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:  # noqa: B008
        if parent.isValid() and parent.column() != 0:
            return QModelIndex()
        if column < 0 or column >= self.columnCount():
            return QModelIndex()
        node = self._node(parent)
        if node is None:
            return QModelIndex()
        children = self.visible_children(node)
        if 0 <= row < len(children):
            return self.createIndex(row, column, children[row])
        return QModelIndex()

    def parent(self, index: QModelIndex) -> QModelIndex:
        if not index.isValid():
            return QModelIndex()
        node = index.internalPointer()
        parent = node.parent
        if parent is None or parent is self.root:
            return QModelIndex()
        grandparent = parent.parent
        siblings = self.visible_children(grandparent if grandparent else self.root)
        try:
            row = siblings.index(parent)
        except ValueError:
            return QModelIndex()
        return self.createIndex(row, 0, parent)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if orientation is Qt.Orientation.Horizontal and role == Qt.ItemDataRole.ToolTipRole:
            if section == DISCOVERY_COLUMN:
                return DISCOVERY_HELP
            if section == 0:
                return "今回実行するkeyを選択します。WatchlistのON/OFFは変更しません。"
        if orientation is Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        node = index.internalPointer()
        if role == NODE_ROLE:
            return node
        if role == IDENTITY_ROLE:
            return node.key_identity or node.node_id
        if role == DISCOVERY_ROLE:
            key = self._key_by_id.get(node.node_id)
            return key.target.enabled if key is not None and key.target is not None else None
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == 0:
            return self.check_state(node)
        if role == Qt.ItemDataRole.DisplayRole:
            return self.display_value(node, index.column())
        if role == Qt.ItemDataRole.ToolTipRole:
            if index.column() == DISCOVERY_COLUMN:
                reason = self.discovery_guard()
                return DISCOVERY_HELP + (f"\n{reason}" if reason else "\n切り替えると即保存します。")
            return self.tooltip(node)
        if role == Qt.ItemDataRole.ForegroundRole and node.kind == "key" and self._key_by_id.get(node.node_id, None) is not None:
            key = self._key_by_id[node.node_id]
            if key.target is not None and not key.target.enabled:
                from PySide6.QtGui import QColor
                return QColor("#777777")
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        node = index.internalPointer()
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == DISCOVERY_COLUMN and self._managed(node):
            if (self.snapshot is None or not self.snapshot.watchlist_revision
                    or self.discovery_guard()):
                return Qt.ItemFlag.ItemIsSelectable
            return flags | Qt.ItemFlag.ItemIsEditable
        if index.column() == 0 and (node.kind in ("site", "work") and any(node.key_descendants()) or node.kind == "key" and self._managed(node)):
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if index.isValid() and index.column() == DISCOVERY_COLUMN:
            if (role != Qt.ItemDataRole.EditRole or not isinstance(value, bool)
                    or not self.flags(index) & Qt.ItemFlag.ItemIsEditable):
                return False
            key = self._key_by_id[index.internalPointer().node_id]
            if key.target.enabled == value:
                return False
            self.discoveryToggleRequested.emit(key.identity, value)
            return True
        if role != Qt.ItemDataRole.CheckStateRole or not index.isValid() or index.column() != 0:
            return False
        node = index.internalPointer()
        if node.kind == "key":
            identities = {node.key_identity} if self._managed(node) else set()
        else:
            identities = {child.key_identity for child in node.key_descendants() if self._managed(child)}
        if not identities:
            return False
        checked = value in (Qt.CheckState.Checked, Qt.CheckState.PartiallyChecked, 2, 1)
        if checked:
            self.checked_keys.update(identities)
        else:
            self.checked_keys.difference_update(identities)
        self._emit_check_updates()
        return True

    def _emit_check_updates(self) -> None:
        def emit_tree(parent: TreeNode) -> None:
            for row, child in enumerate(self.visible_children(parent)):
                index = self.createIndex(row, 0, child)
                self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
                emit_tree(child)
        emit_tree(self.root)
        self.checkedKeysChanged.emit(frozenset(self.checked_keys))

    def _node(self, index: QModelIndex) -> TreeNode | None:
        if not index.isValid():
            return self.root
        node = index.internalPointer()
        return node if isinstance(node, TreeNode) else None

    def _managed(self, node: TreeNode) -> bool:
        key = self._key_by_id.get(node.node_id)
        return bool(key is not None and key.target is not None)

    def check_state(self, node: TreeNode | QModelIndex) -> Qt.CheckState:
        if isinstance(node, QModelIndex):
            resolved = self._node(node)
            if resolved is None:
                return Qt.CheckState.Unchecked
            node = resolved
        identities = {child.key_identity for child in node.key_descendants() if self._managed(child)}
        if node.kind == "key" and self._managed(node):
            identities = {node.key_identity}
        if not identities:
            return Qt.CheckState.Unchecked
        selected = len(identities & self.checked_keys)
        if selected == 0:
            return Qt.CheckState.Unchecked
        if selected == len(identities):
            return Qt.CheckState.Checked
        return Qt.CheckState.PartiallyChecked

    def summary_for(self, node: TreeNode) -> InventorySummary | None:
        if self.snapshot is None:
            return None
        if node.kind == "key" and node.key_identity is not None:
            key = self._key_by_identity.get(node.key_identity)
            return key.summary if key is not None else None
        if node.kind == "site" and node.site is not None and node.parent is not None and node.parent.kind == "work" and node.work_key is not None:
            return self.snapshot.summaries.get(("pair", node.site, node.work_key))
        if node.kind == "site" and node.site is not None:
            return self.snapshot.summaries.get(("site", node.site))
        if node.kind == "work" and node.work_key is not None:
            if node.site is not None:
                return self.snapshot.summaries.get(("pair", node.site, node.work_key))
            return self.snapshot.summaries.get(("work", node.work_key))
        return None

    @staticmethod
    def status_text(node: TreeNode) -> str:
        return "未確認"

    def display_value(self, node: TreeNode, column: int) -> str:
        if column == 0:
            return node.label
        if column == DISCOVERY_COLUMN:
            if self.discovery_pending_key is not None and node.key_identity == self.discovery_pending_key:
                return "保存中"
            targets = self.discovery_targets(node)
            if node.kind == "key":
                return ("ON" if targets[0].enabled else "OFF") if targets else "—"
            return f"有効{sum(target.enabled for target in targets)}／全{len(targets)}件" if targets else "—"
        summary = self.summary_for(node)
        counts = _summary_counts(summary)
        stale = bool(summary and (summary.sync_status not in ("synced", "ok") or summary.diagnostics))
        if column == 1:
            return "—" if counts is None else f"{'~' if stale else ''}{counts.completed}/{counts.total_assigned}"
        if column == 2:
            return _count_text(counts.direct if counts else None, stale=stale)
        if column == 3:
            return _count_text(counts.quota if counts else None, stale=stale)
        if column == 4:
            return _count_text(counts.paid if counts else None, stale=stale)
        if column == 5:
            return self._status_label(summary, counts)
        if column == 6:
            return display_time(summary.last_access) if summary else "—"
        if column == 7:
            return _count_text(counts.external if counts else None, stale=stale)
        if column == 8:
            return _count_text(counts.skipped if counts else None, stale=stale)
        if column == 9:
            return _count_text(counts.out_of_scope if counts else None, stale=stale)
        return "—"

    def discovery_targets(self, node: TreeNode) -> tuple:
        nodes = (node,) if node.kind == "key" else node.key_descendants()
        return tuple(self._key_by_id[child.node_id].target for child in nodes if self._managed(child))

    @staticmethod
    def _status_label(summary: InventorySummary | None, counts: InventoryCounts | None) -> str:
        if summary is None:
            return "未確認"
        if summary.sync_status.startswith("stale"):
            reason = " / ".join(summary.diagnostics)
            if "削除した登録" in reason:
                return "削除反映待ち"
            if "取得範囲" in reason:
                return "取得範囲未反映"
        if counts is None:
            if summary.sync_status.startswith("stale"):
                return "要確認（stale）"
            return {
                "missing_work": "作品未登録",
                "not_discovered": "未Discover",
                "unmanaged": "未管理",
                "binding_mismatch": "紐付け不一致",
                "error": "エラー",
            }.get(summary.sync_status, "未確認")
        if summary.sync_status not in ("synced", "ok"):
            if summary.sync_status.startswith("stale"):
                return "要確認（stale）"
            if "not_discovered" in summary.sync_status:
                return "未Discover"
            if "unmanaged" in summary.sync_status:
                return "未管理"
            return {
                "stale": "要確認（stale）",
                "missing_work": "作品未登録",
                "not_discovered": "未Discover",
                "unmanaged": "未管理",
                "binding_mismatch": "紐付け不一致",
                "error": "エラー",
            }.get(summary.sync_status, summary.sync_status or "未確認")
        if counts.unknown:
            return "要確認"
        if counts.total_assigned and counts.completed >= counts.total_assigned:
            return "完了"
        if counts.direct or counts.quota:
            return "候補あり"
        return "確認済"

    def tooltip(self, node: TreeNode) -> str:
        summary = self.summary_for(node)
        lines = [node.label]
        if node.kind == "key" and node.key_identity:
            key = self._key_by_identity.get(node.key_identity)
            if key and key.target:
                lines.append(f"Watchlist key: {key.target.key}")
                lines.append(f"Discovery: {'有効' if key.target.enabled else '無効'}")
        if summary:
            lines.append(f"Scope: {summary.sync_status}")
            lines.extend(summary.diagnostics[:3])
        if node.kind == "key" and not self._managed(node):
            lines.append("未管理のCatalog Source（選択不可）")
        return "\n".join(lines)

    def node_for_index(self, index: QModelIndex) -> TreeNode | None:
        return self._node(index) if index.isValid() else None

    def node_by_id(self, node_id: str) -> TreeNode | None:
        return self._nodes.get(node_id)

    def node_by_key_identity(self, identity: str) -> TreeNode | None:
        return next((node for node in self._nodes.values() if node.kind == "key" and node.key_identity == identity), None)

    def index_for_node(self, node_id: str) -> QModelIndex:
        node = self._nodes.get(node_id)
        if node is None or node is self.root:
            return QModelIndex()
        parent = node.parent or self.root
        siblings = self.visible_children(parent)
        try:
            row = siblings.index(node)
        except ValueError:
            return QModelIndex()
        return self.createIndex(row, 0, node)

    def all_key_identities(self) -> set[str]:
        return {key.identity for key in self._key_by_identity.values() if key.target is not None}

    def key_inventory(self, identity: str) -> KeyInventory | None:
        return self._key_by_identity.get(identity)


class InventorySortFilterProxyModel(QSortFilterProxyModel):
    """Small compatibility wrapper for callers preferring a proxy model."""

    def __init__(self, source: InventoryTreeModel, parent: Any = None) -> None:
        super().__init__(parent)
        self.setSourceModel(source)
        self.setRecursiveFilteringEnabled(True)
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)


# Public aliases make the model easy to discover for small integrations while
# keeping the descriptive class name used by the application.
InventoryModel = InventoryTreeModel
TreeModel = InventoryTreeModel

