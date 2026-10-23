"""Measure the P1 background load and UI with previously generated sample inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from time import perf_counter

import PySide6
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from screenshot_crawler.gui.main_window import MainWindow


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    paths = [args.sample / name for name in
             ("sample.sqlite", "sample-watchlist.yaml", "sample-runtime.yaml")]
    before = [(hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
              for path in paths]
    app = QApplication([])
    start, last_tick, gaps = perf_counter(), perf_counter(), []
    window = MainWindow(*paths)
    window.show()
    heartbeat, poll, deadline = QTimer(), QTimer(), QTimer()
    report = {}

    def tick():
        nonlocal last_tick
        current = perf_counter()
        gaps.append(current - last_tick)
        last_tick = current

    def ready():
        if window._loading:
            return
        poll.stop()
        snapshot = window.model.snapshot
        if snapshot is None:
            report["error"] = window.error_label.text()
        else:
            report.update({
                "python": sys.version.split()[0], "pyside6": PySide6.__version__,
                "qt_platform": app.platformName(), "source_count": len(snapshot.sources),
                "key_groups": len(snapshot.keys), "inventory_seconds": snapshot.load_seconds,
                "load_to_window_seconds": perf_counter() - start,
                "heartbeat_count": len(gaps), "maximum_heartbeat_gap_seconds": max(gaps),
            })
            for label, operation in (
                ("switch", lambda: window.mode_combo.setCurrentIndex(1)),
                ("search", lambda: window.search_edit.setText("sample-0999")),
                ("expand", window.tree.expandAll),
            ):
                action_start = perf_counter()
                operation()
                app.processEvents()
                report[label + "_seconds"] = perf_counter() - action_start
        after = [(hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
                 for path in paths]
        report["input_hash_and_mtime_unchanged"] = before == after
        window.close()
        app.quit()

    heartbeat.timeout.connect(tick)
    heartbeat.start(50)
    poll.timeout.connect(ready)
    poll.start(50)
    deadline.setSingleShot(True)
    deadline.timeout.connect(app.quit)
    deadline.start(60000)
    app.exec()
    if not report:
        raise RuntimeError("Benchmark timed out")
    args.report.write_text(json.dumps(report, indent=2) + "\n", "utf-8")
    print(json.dumps(report))
    return 0 if not report.get("error") and report["input_hash_and_mtime_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
