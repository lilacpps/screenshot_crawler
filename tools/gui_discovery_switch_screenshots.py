"""Render main-window Discovery switches from isolated synthetic inputs only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch

from gui_sample import create_sample
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from screenshot_crawler.gui.discovery_toggle import ToggleResult
from screenshot_crawler.gui.main_window import MainWindow
from screenshot_crawler.management.inventory import InventoryService
from screenshot_crawler.watchlist.service import WatchlistService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-output", type=Path, required=True)
    parser.add_argument("--screenshots", type=Path, required=True)
    args = parser.parse_args()
    db, watchlist = create_sample(args.sample_output, key_count=8, sources_per_key=12)
    runtime = args.sample_output / "sample-runtime.yaml"
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow(db, watchlist, runtime, auto_load=False,
                        management_path=args.sample_output / "management.sqlite")
    window.set_snapshot(InventoryService().load(db, watchlist, runtime_path=runtime))
    window.catalog_edit.setText("sample.sqlite")
    window.watchlist_edit.setText("sample-watchlist.yaml")
    window.runtime_edit.setText("sample-runtime.yaml")
    window.mode_combo.setCurrentIndex(1)
    window.tree.expandAll()
    window.model.set_checked_keys({"sample-0000", "sample-0003"})
    window.model.focus_node(window.model.node_by_key_identity("sample-0003"))
    window.execution_monitor.set_collapsed(True)
    window.show()
    args.screenshots.mkdir(parents=True, exist_ok=True)
    captures = []
    failure_patch = None

    def capture(width, height, name=None):
        window.resize(width, height)
        def save():
            filename = name or f"discovery-switches-{width}.png"
            if not window.grab().save(str(args.screenshots / filename)):
                raise RuntimeError("Screenshot save failed")
            captures.append({"file": filename, "width": window.width(), "height": window.height(),
                             "dpr": window.devicePixelRatioF(), "platform": app.platformName()})
        QTimer.singleShot(200, save)

    def saving():
        window._discovery_refresh = True
        window.model.discovery_pending_key = "sample-0000"
        window._refresh_discovery_controls()
        window.statusBar().showMessage("合成データ：Discovery設定を保存中…")
        capture(1400, 850, "discovery-switches-saving.png")

    def refresh_failure():
        nonlocal failure_patch
        service = WatchlistService(watchlist)
        service.update_target("sample-0000", enabled=False, expected_revision=service.revision())
        targets, revision = service.read_snapshot()
        failure_patch = patch.object(InventoryService, "load", side_effect=OSError("合成データによる表示更新失敗"))
        failure_patch.start()
        window._discovery_saved(ToggleResult(str(watchlist.resolve()), "sample-0000", targets, revision))
        capture(1400, 850, "discovery-switches-saved-refresh-failed.png")

    def finish():
        if failure_patch is not None:
            failure_patch.stop()
        (args.screenshots / "discovery-switches.actual.json").write_text(
            json.dumps(captures, ensure_ascii=False, indent=2), encoding="utf-8")
        window.close()
        app.quit()

    QTimer.singleShot(150, lambda: capture(1400, 850))
    QTimer.singleShot(650, lambda: capture(980, 700))
    QTimer.singleShot(1150, saving)
    QTimer.singleShot(1650, refresh_failure)
    QTimer.singleShot(2200, finish)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
