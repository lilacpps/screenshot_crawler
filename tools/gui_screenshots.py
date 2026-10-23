"""Render synthetic P1 screens with the native Qt platform; no operational inputs."""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from gui_sample import create_sample
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from screenshot_crawler.catalog.service import JST
from screenshot_crawler.gui.main_window import MainWindow
from screenshot_crawler.management.inventory import InventoryService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-output", type=Path, required=True)
    parser.add_argument("--screenshots", type=Path, default=Path("docs/gui-screenshots"))
    args = parser.parse_args()
    db, watchlist = create_sample(args.sample_output)
    snapshot = InventoryService().load(
        db, watchlist, runtime_path=args.sample_output / "sample-runtime.yaml",
        now=datetime(2026, 10, 23, 12, tzinfo=JST),
    )
    # Screenshots are sample presentations; do not expose the local home path.
    snapshot = replace(snapshot, catalog_path="sample.sqlite", watchlist_path="sample-watchlist.yaml")
    app = QApplication([])
    window = MainWindow(db, watchlist, auto_load=False)
    window._load_succeeded(snapshot)
    window.resize(1400, 850)
    window.show()
    args.screenshots.mkdir(parents=True, exist_ok=True)

    def focus(node):
        window.model.focus_node(node)
        index = window.model.index_for_node(node.node_id)
        window.tree.setCurrentIndex(index)
        window.tree.scrollTo(index)

    def save(name):
        window.grab().save(str(args.screenshots / name))

    def site():
        window.model.set_checked_keys({"sample-0004", "sample-0005"})
        focus(window.model.node_by_id("site:mangaone"))
        window.tree.expandAll()
        QTimer.singleShot(200, lambda: save("site.png"))

    def work():
        window.mode_combo.setCurrentIndex(1)
        window.tree.expandAll()
        focus(window.model.node_by_id("work:sample-work-0001"))
        QTimer.singleShot(200, lambda: save("work.png"))

    def work_detail():
        splitter = window.tree.parentWidget()
        splitter.setSizes([800, 580])
        focus(window.model.node_by_id("work:sample-work-0001"))
        QTimer.singleShot(200, lambda: save("work-detail.png"))

    def item_detail():
        node = window.model.node_by_key_identity("sample-0000")
        focus(node)
        window.detail.set_item(2, 2)
        QTimer.singleShot(200, lambda: save("item-detail.png"))

    QTimer.singleShot(200, site)
    QTimer.singleShot(700, work)
    QTimer.singleShot(1200, work_detail)
    QTimer.singleShot(1700, item_detail)
    QTimer.singleShot(2300, app.quit)
    result = app.exec()
    print(f"Qt platform={app.platformName()}, size={window.width()}x{window.height()}")
    print(f"Screenshots: {args.screenshots}")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
