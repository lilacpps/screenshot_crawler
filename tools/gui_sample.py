"""Generate ONLY synthetic GUI inputs in an explicitly new output directory.

This developer tool is never imported or invoked by the GUI application.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

import yaml

from screenshot_crawler.catalog.schema import SCHEMA_SQL
from screenshot_crawler.watchlist.fingerprints import (
    configuration_json,
    target_scope_fingerprint,
    work_definition_fingerprint,
    work_scope_fingerprint,
)
from screenshot_crawler.watchlist.service import WatchlistService

STAMP = "2026-10-23T10:00:00+09:00"


def create_sample(directory: Path, *, key_count=8, sources_per_key=12):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    db, watchlist = directory / "sample.sqlite", directory / "sample-watchlist.yaml"
    sites = ("mangaone", "magapoke", "jumpplus", "zeblack")
    targets = []
    for index in range(key_count):
        targets.append({
            "key": f"sample-{index:04d}", "work_key": f"sample-work-{index // 4:04d}",
            "site": sites[index % 4], "url": f"https://example.invalid/list/{index}",
            "label": f"範囲 {index % 4 + 1} ・ 合成データ", "enabled": index != 3,
            "archive_order": index % 4 + 1,
        })
    targets.append({
        "key": "not-discovered", "work_key": "new-work", "site": "comicdays",
        "url": "https://example.invalid/undiscovered", "label": "未Discoverの作品",
    })
    watchlist.write_text(yaml.safe_dump({"targets": targets}, allow_unicode=True), "utf-8")
    parsed = WatchlistService(watchlist).list_targets()
    with sqlite3.connect(db) as connection:
        connection.executescript(SCHEMA_SQL)
        connection.execute("PRAGMA user_version=7")
        work_ids = {}
        for target in parsed[:-1]:
            if target.work_key not in work_ids:
                work_id = len(work_ids) + 1
                work_ids[target.work_key] = work_id
                connection.execute(
                    "INSERT INTO works VALUES(?,?,?,?,?,?,?)",
                    (work_id, target.work_key, f"星をめぐる図書館 {work_id} ― サンプル作品",
                     "架空の著者", "合成データ", STAMP, STAMP),
                )
        source_id = 0
        for target in parsed[:-1]:
            work_id = work_ids[target.work_key]
            positions = []
            for position in range(1, sources_per_key + 1):
                source_id += 1
                status = ("completed", "completed", "external", "skipped",
                          "pending", "pending", "pending", "pending")[
                    (position - 1) % 8
                ]
                mode = ("free", "quota", "paid", "unknown")[position % 4]
                if position == 5:
                    mode = "free"
                elif position == 6:
                    mode = "quota"
                elif position == 7:
                    mode = "paid"
                elif position == 8:
                    mode = "unknown"
                external_id = str(source_id)
                assigned = position != sources_per_key
                positions.append((external_id, position, assigned))
                connection.execute(
                    "INSERT INTO items VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (source_id, work_id, f"第{position}話 小さな旅の記録", "episode", None,
                     f"第{position}話", status, STAMP if status == "completed" else None,
                     STAMP, STAMP, None),
                )
                grant = "2026-10-24T10:00:00+09:00" if position == 9 else None
                connection.execute(
                    "INSERT INTO sources VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (source_id, source_id, target.site, external_id, target.key, mode,
                     None, 1, STAMP, STAMP, None, grant, None, STAMP, STAMP,
                     position, int(assigned)),
                )
                connection.execute(
                    "INSERT INTO source_targets VALUES(?,?,?,?,?,?,?,?,?)",
                    (source_id, source_id, "web", "default",
                     f"https://example.invalid/episode/{source_id}", 100, 1, STAMP, STAMP),
                )
            digest = hashlib.sha256(json.dumps(
                positions, ensure_ascii=False, separators=(",", ":")
            ).encode()).hexdigest()
            connection.execute(
                "INSERT INTO discovery_inventory_evidence VALUES(?,?,?,?,?,?,?,?,?)",
                (target.key, work_id, target.site, target.url, target_scope_fingerprint(target),
                 "synthetic-list", digest, len(positions), STAMP),
            )
            connection.executemany(
                "INSERT INTO discovery_inventory_positions VALUES(?,?,?,?,?)",
                [(target.key, target.site, ext, pos, int(assigned))
                 for ext, pos, assigned in positions],
            )
        for work_key, work_id in work_ids.items():
            work_targets = [target for target in parsed if target.work_key == work_key]
            connection.execute(
                "INSERT INTO acquisition_scope_sync VALUES(?,?,?,?,?,?)",
                (work_id, work_scope_fingerprint(work_targets),
                 work_definition_fingerprint(work_targets), configuration_json(work_targets),
                 "synced", STAMP),
            )
        # Explicit unmanaged history, not reassigned to a current Watchlist key.
        connection.execute("UPDATE sources SET discovery_key='removed-key' WHERE id=1")
        connection.execute("UPDATE acquisition_scope_sync SET status='stale' WHERE work_id=1")
        connection.execute(
            "INSERT INTO crawl_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (1, 2, 2, 2, sites[0], "2", "web", "default", "https://example.invalid/episode/2",
             "direct", "succeeded", STAMP, STAMP, 18, "end", None, None, STAMP, STAMP),
        )
        # The locator is illustrative. The GUI never creates, opens or stats this ZIP.
        connection.execute(
            "INSERT INTO artifacts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (1, 2, 1, "archive", "zip", "0" * 64, 12345, "filesystem",
             "C:/SampleLibrary/002-synthetic.zip", "present", STAMP, STAMP, STAMP),
        )
        if key_count >= 4:
            connection.execute(
                "INSERT INTO quota_resource_states VALUES(?,?,?,?,?,?,?)",
                (1, 1, "zeblack", "work_ticket", STAMP, STAMP, STAMP),
            )
    (directory / "sample-runtime.yaml").write_text("sites: {}\n", "utf-8")
    return db, watchlist


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--keys", type=int, default=8)
    parser.add_argument("--sources-per-key", type=int, default=12)
    args = parser.parse_args()
    if args.keys < 1 or args.sources_per_key < 2:
        parser.error("keys >= 1 and sources-per-key >= 2 are required")
    db, watchlist = create_sample(
        args.output, key_count=args.keys, sources_per_key=args.sources_per_key
    )
    print(f"Synthetic inputs: {db} / {watchlist}")


if __name__ == "__main__":
    main()
