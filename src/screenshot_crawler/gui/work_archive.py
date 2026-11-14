"""Watchlist-only Work visibility save worker with deletion gate protection."""

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from screenshot_crawler.maintenance.work_deletion_gate import (
    assert_work_deletion_gate_clear,
    work_deletion_admission_lock,
)
from screenshot_crawler.watchlist.service import WatchlistService


class _ArchiveSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)


class WorkArchiveSaveWorker(QRunnable):
    def __init__(self, path: str, work_key: str, archived: bool, revision: str, catalog_path: str | Path):
        super().__init__()
        self.path = Path(path).resolve(strict=False)
        self.catalog_path = Path(catalog_path).resolve(strict=False)
        self.work_key, self.archived, self.revision = work_key, archived, revision
        self.signals = _ArchiveSignals()

    @Slot()
    def run(self):
        try:
            with work_deletion_admission_lock(self.catalog_path):
                assert_work_deletion_gate_clear(self.catalog_path)
                result = WatchlistService(self.path).set_work_archived(
                    self.work_key, self.archived, expected_revision=self.revision,
                )
        except Exception as exc:  # noqa: BLE001 - user-facing bounded save failure
            self.signals.failed.emit(str(exc) or type(exc).__name__)
        else:
            self.signals.succeeded.emit(result)
