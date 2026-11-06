"""Watchlist-only Work visibility save worker."""

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from screenshot_crawler.watchlist.service import WatchlistService


class _ArchiveSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)


class WorkArchiveSaveWorker(QRunnable):
    def __init__(self, path: str, work_key: str, archived: bool, revision: str):
        super().__init__()
        self.path, self.work_key, self.archived, self.revision = path, work_key, archived, revision
        self.signals = _ArchiveSignals()

    @Slot()
    def run(self):
        try:
            result = WatchlistService(self.path).set_work_archived(
                self.work_key, self.archived, expected_revision=self.revision,
            )
        except Exception as exc:  # noqa: BLE001 - user-facing bounded save failure
            self.signals.failed.emit(str(exc) or type(exc).__name__)
        else:
            self.signals.succeeded.emit(result)
