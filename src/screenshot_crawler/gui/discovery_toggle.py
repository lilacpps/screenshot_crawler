"""A painted per-key switch and a bounded Watchlist-only save worker."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QRect, QRunnable, Qt, Signal, Slot
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from screenshot_crawler.watchlist.models import WatchlistTarget
from screenshot_crawler.watchlist.service import WatchlistService

from .model import DISCOVERY_ROLE


@dataclass(frozen=True, slots=True)
class ToggleResult:
    path: str
    key: str
    targets: tuple[WatchlistTarget, ...]
    revision: str


class _SaveSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    savedButUnverified = Signal(str)


class DiscoverySaveWorker(QRunnable):
    def __init__(self, path: str, key: str, enabled: bool, revision: str):
        super().__init__()
        self.path, self.key, self.enabled, self.revision = path, key, enabled, revision
        self.signals = _SaveSignals()

    @Slot()
    def run(self):
        committed = False
        try:
            service = WatchlistService(self.path)
            # Same-owner nesting of update_target's lock is supported. Keep the
            # committed targets and revision together before another writer runs.
            with service.edit_lock():
                service.update_target(self.key, enabled=self.enabled, expected_revision=self.revision)
                committed = True
                targets, revision = service.read_snapshot()
            result = ToggleResult(str(Path(self.path).resolve()), self.key, targets, revision)
        except Exception as exc:  # noqa: BLE001 - preserve the old display on failure
            signal = self.signals.savedButUnverified if committed else self.signals.failed
            signal.emit(str(exc) or type(exc).__name__)
        else:
            self.signals.succeeded.emit(result)


class DiscoverySwitchDelegate(QStyledItemDelegate):
    """Paint switches without allocating a widget for every inventory row."""

    @staticmethod
    def switch_rect(rect: QRect) -> QRect:
        width, height = min(78, rect.width() - 6), min(24, rect.height() - 2)
        return QRect(rect.center().x() - width // 2, rect.center().y() - height // 2, width, height)

    def paint(self, painter, option, index):
        enabled = index.data(DISCOVERY_ROLE)
        if enabled is None:
            super().paint(painter, option, index)
            return
        background = QStyleOptionViewItem(option)
        self.initStyleOption(background, index)
        background.text = ""
        style = option.widget.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, background, painter, option.widget)
        editable = bool(index.flags() & Qt.ItemFlag.ItemIsEditable)
        saving = index.data() == "保存中"
        rect = self.switch_rect(option.rect)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#087f5b" if enabled else "#596579") if editable else QColor("#7b8490"))
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        painter.setPen(QColor("white"))
        if saving:
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "保存中")
        else:
            knob = rect.height() - 6
            x = rect.right() - knob - 3 if enabled else rect.left() + 3
            painter.setBrush(QColor("white"))
            painter.drawEllipse(x, rect.top() + 3, knob, knob)
            text_rect = rect.adjusted(4, 0, -knob - 5, 0) if enabled else rect.adjusted(knob + 5, 0, -4, 0)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, "ON" if enabled else "OFF")
        painter.restore()

    def createEditor(self, parent, option, index):
        return None  # All edits are explicit toggles, never a generic text editor.

    def editorEvent(self, event, model, option, index):
        value = index.data(DISCOVERY_ROLE)
        if value is None or not index.flags() & Qt.ItemFlag.ItemIsEditable:
            return False
        if event.type() == QEvent.Type.MouseButtonRelease:
            if event.button() != Qt.MouseButton.LeftButton or not self.switch_rect(option.rect).contains(event.position().toPoint()):
                return False
        elif event.type() == QEvent.Type.KeyPress:
            if event.key() not in (Qt.Key.Key_Space, Qt.Key.Key_Select) or event.isAutoRepeat():
                return False
        else:
            return False
        return model.setData(index, not value, Qt.ItemDataRole.EditRole)
