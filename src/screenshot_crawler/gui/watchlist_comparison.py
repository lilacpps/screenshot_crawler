"""Read-only Work comparison surrounding the active key's checkbox model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from screenshot_crawler.discovery.listing import ListingRow
from screenshot_crawler.watchlist.models import WatchlistTarget

if TYPE_CHECKING:
    from .watchlist_editor import ScopeChecklistModel


@dataclass(frozen=True, slots=True)
class WorkEpisodeRow:
    target: WatchlistTarget
    episode: ListingRow
    status: str
    acquisition_enabled: bool | None
    title_origin: str
    active_row: int | None = None


class WorkEpisodeModel(QAbstractTableModel):
    """Preserve site/key identity; only active-key rows delegate editing."""

    HEADERS = ("select", "site", "key", "external_id", "position", "title", "URL",
               "access", "Catalog / status", "current-proposed", "delta", "title source")
    ACTIVE_COLUMNS: ClassVar[dict[int, int]] = {0: 0, 3: 1, 4: 2, 5: 3, 6: 4, 7: 5, 8: 6, 9: 7, 10: 8}

    def __init__(self, active: ScopeChecklistModel, parent=None) -> None:
        super().__init__(parent)
        self.active = active
        self.rows: tuple[WorkEpisodeRow, ...] = ()

    def set_rows(self, rows: list[WorkEpisodeRow]) -> bool:
        def identity(row):
            return row.target.site, row.target.key, row.episode.external_id, row.episode.url, row.active_row

        if tuple(map(identity, self.rows)) == tuple(map(identity, rows)):
            self.rows = tuple(rows)
            if rows:
                self.dataChanged.emit(self.index(0, 0), self.index(len(rows) - 1, len(self.HEADERS) - 1))
            return False
        self.beginResetModel()
        self.rows = tuple(rows)
        self.endResetModel()
        return True

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def entry(self, index: QModelIndex) -> WorkEpisodeRow | None:
        return self.rows[index.row()] if index.isValid() and 0 <= index.row() < len(self.rows) else None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole) -> Any:
        entry = self.entry(index)
        if entry is None:
            return None
        if role == Qt.ItemDataRole.ToolTipRole:
            return (f"{entry.target.work_key} / {entry.target.site} / {entry.target.key}\n"
                    f"{entry.episode.display_title}\n{entry.episode.url}\n"
                    "チェック・境界指定は編集中のkeyのみ。別keyは右クリックから切替。")
        if entry.active_row is not None and index.column() in self.ACTIVE_COLUMNS:
            column = self.ACTIVE_COLUMNS[index.column()]
            details = self.active.catalog_details.get(entry.episode.external_id)
            if column in (7, 8) and role == Qt.ItemDataRole.DisplayRole:
                if details:
                    return f"{details[0]} -> {details[1]}" if column == 7 else details[2]
                selected = entry.episode.external_id in self.active.checked if self.active.editable else "—"
                if column == 7:
                    return f"{entry.acquisition_enabled} -> {selected}"
                return "未preview" if self.active.editable else "参照"
            # Status comes from Catalog even if the complete listing has no Item.
            if column != 6:
                return self.active.data(self.active.index(entry.active_row, column), role)
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == 0:
            return None
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        row = entry.episode
        return (None, entry.target.site, entry.target.key, row.external_id,
                row.site_position or "unknown", row.display_title or "未確認", row.url,
                row.access_observation, entry.status,
                f"{entry.acquisition_enabled} -> —", "参照", entry.title_origin)[index.column()]

    def flags(self, index):
        entry = self.entry(index)
        if entry is None:
            return Qt.ItemFlag.NoItemFlags
        if entry.active_row is not None and index.column() == 0:
            return self.active.flags(self.active.index(entry.active_row, 0))
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        entry = self.entry(index)
        if entry is None or entry.active_row is None or index.column() != 0:
            return False
        return self.active.setData(self.active.index(entry.active_row, 0), value, role)
