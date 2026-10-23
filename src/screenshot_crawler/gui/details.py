"""Read-only detail widgets for inventory nodes and items."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from screenshot_crawler.management.inventory import display_time
from screenshot_crawler.management.models import InventorySnapshot, KeyInventory

from .model import TreeNode


def _text(value: object | None) -> str:
    return "—" if value is None or value == "" else str(value)


def _short(value: object | None, limit: int = 300) -> str:
    text = _text(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _sync_label(value: str) -> str:
    if value.startswith("stale"):
        return "要確認（stale）"
    if "not_discovered" in value:
        return "未Discover"
    if "unmanaged" in value:
        return "未管理"
    return {
        "synced": "同期済み",
        "ok": "同期済み",
        "stale": "要確認（stale）",
        "missing_work": "作品未登録",
        "not_discovered": "未Discover",
        "unmanaged": "未管理",
        "binding_mismatch": "紐付け不一致",
        "error": "エラー",
    }.get(value, value or "未確認")


def _item_status_label(value: str) -> str:
    return {
        "completed": "取得済み",
        "external": "外部取得",
        "skipped": "スキップ",
        "pending": "未取得",
        "unsupported": "未対応",
    }.get(value, value or "未確認")


class ItemTableModel(QAbstractTableModel):
    HEADERS = ("表示位置", "Archive位置", "話数", "状態", "アクセス", "分類", "担当", "無料期限", "Grant期限", "Source")

    def __init__(self, snapshot: InventorySnapshot | None = None, key: KeyInventory | None = None, parent: Any = None) -> None:
        super().__init__(parent)
        self.snapshot = snapshot
        self.key = key
        self.rows: list[tuple[int, int]] = []  # (source_id, item_id)
        self.set_context(snapshot, key)

    def set_context(self, snapshot: InventorySnapshot | None, key: KeyInventory | None) -> None:
        self.beginResetModel()
        self.snapshot = snapshot
        self.key = key
        self.rows = []
        if snapshot is not None and key is not None:
            source_ids = set(key.summary.source_ids)
            self.rows = sorted(
                ((source.id, source.item_id) for source in snapshot.sources.values() if source.id in source_ids),
                key=lambda row: (snapshot.sources[row[0]].display_position if snapshot.sources[row[0]].display_position is not None else 10**9, row[0]),
            )
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if orientation is Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or self.snapshot is None or role != Qt.ItemDataRole.DisplayRole:
            return None
        source_id, item_id = self.rows[index.row()]
        item = self.snapshot.items[item_id]
        source = self.snapshot.sources[source_id]
        classification = self.snapshot.classifications.get(source.id)
        values = (
            source.display_position,
            self.snapshot.archive_positions.get(source.id),
            item.item_title or item.order_label or item.order_key,
            item.status,
            source.access_mode,
            f"{classification.category}: {classification.reason}" if classification else "未確認",
            "担当" if source.acquisition_enabled else "担当外",
            display_time(source.free_until),
            display_time(source.access_granted_until),
            f"{source.site}:{source.external_id}",
        )
        return _text(values[index.column()])

    def item_id_at(self, row: int) -> int | None:
        return self.rows[row][1] if 0 <= row < len(self.rows) else None

    def source_id_at(self, row: int) -> int | None:
        return self.rows[row][0] if 0 <= row < len(self.rows) else None


class MembershipTableModel(QAbstractTableModel):
    """Small Work/Site membership table; keys remain clickable and stable."""

    HEADERS = ("サイト", "Watchlist key", "ラベル", "archive_order", "進捗", "Scope", "from_url", "through_url")
    keySelected = Signal(str)

    def __init__(self, keys: tuple[KeyInventory, ...] = (), parent: Any = None) -> None:
        super().__init__(parent)
        self.keys = keys

    def set_keys(self, keys: tuple[KeyInventory, ...]) -> None:
        self.beginResetModel()
        self.keys = keys
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.keys)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if orientation is Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        key = self.keys[index.row()]
        target = key.target
        counts = key.summary.counts
        scope = target.discovery_scope if target is not None else None
        values = (
            key.site,
            key.identity if target is None else target.key,
            key.label,
            _text(target.archive_order if target else None),
            f"{counts.completed}/{counts.total_assigned}" if counts is not None else "—",
            _sync_label(key.summary.sync_status),
            _short(scope.from_url, 100) if scope else "—",
            _short(scope.through_url, 100) if scope else "—",
        )
        return values[index.column()]

    def key_at(self, row: int) -> str | None:
        return self.keys[row].identity if 0 <= row < len(self.keys) else None


class DetailPane(QWidget):
    """Context-sensitive, read-only summary and item details."""

    itemSelected = Signal(int)
    keySelected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.snapshot: InventorySnapshot | None = None
        self.current_node: TreeNode | None = None
        self.current_key: KeyInventory | None = None
        self._field_labels: dict[str, QLabel] = {}
        self.heading = QLabel("選択してください")
        self.heading.setObjectName("detailHeading")
        self.form = QFormLayout()
        self.form_widget = QWidget()
        self.form_widget.setLayout(self.form)
        self.form_scroll = QScrollArea()
        self.form_scroll.setWidgetResizable(True)
        self.form_scroll.setWidget(self.form_widget)
        self.form_scroll.setMinimumHeight(300)
        self.form_scroll.setMaximumHeight(400)
        self.membership_model = MembershipTableModel(parent=self)
        self.membership_table = QTableView()
        self.membership_table.setModel(self.membership_model)
        self.membership_table.setMaximumHeight(180)
        self.membership_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.membership_table.clicked.connect(self._on_membership_clicked)
        self.item_model = ItemTableModel(parent=self)
        self.item_table = QTableView()
        self.item_table.setModel(self.item_model)
        self.item_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.item_table.setAlternatingRowColors(True)
        self.item_table.clicked.connect(self._on_item_clicked)
        self.membership_table.setVisible(False)
        self.item_table.setVisible(False)
        layout = QVBoxLayout(self)
        layout.addWidget(self.heading)
        layout.addWidget(self.form_scroll, 1)
        layout.addWidget(self.membership_table)
        layout.addWidget(self.item_table, 1)
        self._set_fields({})

    def set_snapshot(self, snapshot: InventorySnapshot | None) -> None:
        self.snapshot = snapshot
        self.set_node(None, None)

    def set_node(self, node: TreeNode | None, key: KeyInventory | None, summary: Any = None) -> None:
        self.current_node = node
        self.current_key = key
        if node is None:
            self.heading.setText("選択してください")
            self._set_fields({})
            self.membership_model.set_keys(())
            self.item_model.set_context(self.snapshot, None)
            self.membership_table.setVisible(False)
            self.item_table.setVisible(False)
            return
        self.heading.setText(f"{node.kind}: {node.label}")
        fields: dict[str, str] = {"サイト": node.site or "—", "作品": node.work_key or "—"}
        summary = key.summary if key is not None else summary
        if summary is not None and summary.counts is not None:
            counts = summary.counts
            provisional = "暫定集計: " if summary.sync_status not in ("synced", "ok") or summary.diagnostics else ""
            fields.update({
                "取得済 / 対象": provisional + f"{counts.completed} / {counts.total_assigned}",
                "直取候補": str(counts.direct),
                "Quota対象残": str(counts.quota),
                "有償未取得": str(counts.paid),
                "外部取得": str(counts.external),
                "スキップ": str(counts.skipped),
                "利用不可": str(counts.unavailable),
                "要確認": str(counts.unknown),
                "担当外 Source": str(counts.out_of_scope),
            })
        else:
            fields.update({name: "—" for name in ("取得済 / 対象", "直取候補", "Quota対象残", "有償未取得", "外部取得", "スキップ", "利用不可", "要確認", "担当外 Source")})
        if summary is not None:
            fields["Scope同期"] = _sync_label(summary.sync_status)
            fields["最終確認"] = display_time(summary.last_access)
            if summary.diagnostics:
                fields["診断"] = " / ".join(item[:300] for item in summary.diagnostics[:5])
        if self.snapshot is not None and node.site is not None:
            resource = self.snapshot.resources.get(node.site) if node.kind == "site" else None
            if resource is not None:
                fields["Site Quota"] = _text(resource.available_quota)
                fields["対応Resource"] = ", ".join(resource.supported_resources) or "—"
                fields["Grant Resource"] = ", ".join(resource.grant_resources) or "—"
                if resource.diagnostics:
                    fields["Resource診断"] = " / ".join(resource.diagnostics)
            grants = [grant for grant in self.snapshot.grants if grant.site == node.site and (node.work_key is None or grant.work_key == node.work_key)] if node.kind in ("site", "work") else []
            if grants:
                grouped: dict[tuple[str, str], list] = {}
                for grant in grants:
                    grouped.setdefault((grant.work_key, grant.resource), []).append(grant)
                parts = []
                for (work_key, resource), rows in sorted(grouped.items()):
                    consumed = min((display_time(row.last_consumed_at) for row in rows), default="—")
                    retry = next((display_time(row.retry_at) for row in rows if row.retry_at), "未確認")
                    reasons = "; ".join(dict.fromkeys(row.reason for row in rows))
                    parts.append(f"{node.site}/{work_key}/{resource} consumed={consumed}, retry={retry} ({len(rows)}件): {reasons}")
                fields["Grant概要"] = " / ".join(parts[:20]) + (f" …他{len(parts)-20}件" if len(parts) > 20 else "")
        if self.snapshot is not None:
            if node.kind == "work":
                grants = [grant for grant in self.snapshot.grants if grant.work_key == node.work_key]
                if grants:
                    fields["Work Grant概要"] = ", ".join(f"{grant.site}/{grant.resource}: {display_time(grant.retry_at)} ({grant.reason})" for grant in grants[:20]) + (f" …他{len(grants)-20}件" if len(grants) > 20 else "")
            fields["Snapshot"] = f"loaded {display_time(self.snapshot.loaded_at)} / {self.snapshot.load_seconds:.2f}s / keys {len(self.snapshot.keys)}, items {len(self.snapshot.items)}, sources {len(self.snapshot.sources)}"
            fields["入力"] = f"Catalog: {_short(self.snapshot.catalog_path, 160)} / Watchlist: {_short(self.snapshot.watchlist_path, 160)}"
            fields["Archive"] = "Archiveの実在性は未検証（Catalog上の情報のみ）"
            fields["Local availability"] = "ローカルファイルの存在・ZIP内容は未確認"
        if key is not None and key.target is not None:
            fields.update({
                "Watchlist key": key.target.key,
                "ラベル": key.target.label,
                "Discovery": "有効" if key.target.enabled else "無効",
                "Scope URL": key.target.url,
                "archive_order": _text(key.target.archive_order),
            })
            if key.full_proof:
                fields["Last Full proof"] = display_time(key.full_proof)
            if key.target.discovery_scope is not None:
                fields["Discovery範囲"] = f"{_short(key.target.discovery_scope.from_url)} → {_short(key.target.discovery_scope.through_url)}"
            grants = [grant for grant in (self.snapshot.grants if self.snapshot is not None else ()) if grant.site == key.site and grant.work_key == key.work_key]
            if grants:
                fields["Grant"] = "; ".join(f"{grant.resource}: retry {display_time(grant.retry_at)} ({grant.reason})" for grant in grants[:10])
        members = ()
        if self.snapshot is not None:
            if node.kind == "work":
                members = tuple(item for item in self.snapshot.keys if item.work_key == node.work_key)
            elif node.kind == "site" and node.parent is not None and node.parent.kind == "work":
                members = tuple(item for item in self.snapshot.keys if item.site == node.site and item.work_key == node.work_key)
            elif node.kind == "site":
                members = tuple(item for item in self.snapshot.keys if item.site == node.site)
        if node.kind == "site":
            fields["Work数"] = str(len({item.work_key for item in members}))
            fields["key数"] = str(len(members))
            site_grants = [grant for grant in (self.snapshot.grants if self.snapshot is not None else ()) if grant.site == node.site]
            if site_grants:
                known = [grant for grant in site_grants if grant.retry_at]
                min_retry = min((grant.retry_at for grant in known), default=None)
                fields["Grant local概要"] = f"既知retry {len(known)}件 / retry不明 {len(site_grants)-len(known)}件 / 最短 {display_time(min_retry)}"
        self._set_fields(fields)
        self.membership_model.set_keys(members)
        self.membership_table.setVisible(bool(members) and node.kind != "key")
        self.item_model.set_context(self.snapshot, key if node.kind == "key" else None)
        self.item_table.setVisible(node.kind == "key")

    def set_item(self, item_id: int | None, source_id: int | None = None) -> None:
        if item_id is None or self.snapshot is None:
            return
        item = self.snapshot.items.get(item_id)
        if item is None:
            return
        run = self.snapshot.latest_runs.get(item_id)
        artifacts = self.snapshot.artifacts.get(item_id, ())
        source = self.snapshot.sources.get(source_id) if source_id is not None else None
        targets = self.snapshot.source_targets.get(source_id, ()) if source_id is not None else ()
        run_status = f"{run.status}（履歴）" if run and run.status == "running" else (run.status if run else "—")
        fields = {
            "Item": item.item_title or item.order_label or item.order_key or str(item.id),
            "Status": f"{item.status}（{_item_status_label(item.status)}）",
            "直近 CrawlRun": (f"{run_status} / {display_time(run.finished_at or run.started_at)}" if run else "—"),
            "Result": run.stop_reason if run else "—",
            "Error": run.error_message if run and run.error_message else "—",
            "Artifact": "; ".join(f"{a.kind}:{a.format} ({a.state})" for a in artifacts) or "—",
            "保存先": "; ".join(_text(a.locator) for a in artifacts) or "—",
        }
        if source is not None:
            classification = self.snapshot.classifications.get(source.id)
            fields.update({
                "Source": f"{source.site}:{source.external_id}",
                "Access": source.access_mode,
                "担当": "担当" if source.acquisition_enabled else "担当外",
                "分類": f"{classification.category}: {classification.reason}" if classification else "未確認",
                "Access確認": display_time(source.access_checked_at),
                "Free期限": display_time(source.free_until),
                "Grant期限": display_time(source.access_granted_until),
                "Target": "; ".join(f"{target.backend}/{target.target_key}: {target.locator}" for target in targets) or "—",
            })
        self.heading.setText(f"Item: {fields['Item']}")
        self._set_fields(fields)
        self.itemSelected.emit(item_id)

    def _set_fields(self, fields: dict[str, str]) -> None:
        while self.form.rowCount():
            self.form.removeRow(0)
        self._field_labels = {}
        for name, value in fields.items():
            label = QLabel(value)
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._field_labels[name] = label
            self.form.addRow(name, label)

    def _on_membership_clicked(self, index: QModelIndex) -> None:
        identity = self.membership_model.key_at(index.row())
        if identity:
            self.keySelected.emit(identity)

    def _on_item_clicked(self, index: QModelIndex) -> None:
        self.set_item(self.item_model.item_id_at(index.row()), self.item_model.source_id_at(index.row()))

