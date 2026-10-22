#!/usr/bin/env python3
"""Thin CLI wrapper for the existing-archive renumber maintenance operation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from screenshot_crawler.catalog import CatalogError, CatalogService
from screenshot_crawler.maintenance.archive_renumber import (
    ArchiveRenumberUsageError,
    apply_archive_renumber_plan,
    build_archive_renumber_plan,
)
from screenshot_crawler.watchlist.service import WatchlistService


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Safely renumber existing ZIP archive filenames from Catalog positions."
    )
    parser.add_argument("--work-key", help="Limit the scope to one Catalog Work key")
    parser.add_argument("--site", help="Limit the scope to one source site")
    parser.add_argument("--all", dest="all_sources", action="store_true", help="Process all Sources")
    parser.add_argument("--catalog", type=Path, default=Path("catalog.sqlite"))
    parser.add_argument(
        "--watchlist", type=Path, default=Path("watchlist.yaml"),
        help="Watchlist used to validate work-wide archive_order and scope",
    )
    parser.add_argument("--status-dir", type=Path, default=Path("output/crawl-status"))
    parser.add_argument(
        "--json", action="store_true", help="Print one machine-readable JSON result"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Apply the preflighted plan")
    mode.add_argument("--dry-run", action="store_true", help="Only print the plan (default)")
    return parser


def _print_plan(plan) -> None:
    for entry in plan.entries:
        label = f"{entry.status}"
        if entry.artifact is not None:
            label += f" artifact={entry.artifact.id}"
        label += f" source={entry.source.id}"
        print(label)
        if entry.old_path is not None:
            print(f"  old: {entry.old_path}")
        if entry.new_path is not None:
            print(f"  new: {entry.new_path}")
        if entry.status == "RENAME":
            print(f"  status: {_status_label(entry)}")
        if entry.detail:
            print(f"  detail: {entry.detail}")

    summary = plan.summary()
    print(
        "summary: "
        + " ".join(
            f"{key}={summary[key]}"
            for key in (
                "selected", "rename", "unchanged", "missing", "no_position", "no_artifact",
                "ambiguous", "unsupported", "collision", "status_missing",
                "status_mismatch", "errors", "excluded", "strict_blockers",
            )
        )
    )
    for blocker in plan.strict_blockers:
        print(f"BLOCKED: {blocker}")


def _status_label(entry) -> str:
    if entry.status_path is not None:
        return "MATCH"
    return entry.status_warning or "UNKNOWN"


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    mode = "apply" if args.apply else "dry-run"
    try:
        plan = build_archive_renumber_plan(
            CatalogService(args.catalog),
            work_key=args.work_key,
            site=args.site,
            all_sources=args.all_sources,
            status_dir=args.status_dir,
            watchlist=WatchlistService(args.watchlist),
        )
    except ArchiveRenumberUsageError as exc:
        _print_error(args.json, mode, str(exc))
        return 2
    except (CatalogError, OSError, ValueError) as exc:
        _print_error(args.json, mode, str(exc))
        return 1

    if args.json:
        result_payload = plan.to_dict(mode=mode)
    else:
        _print_plan(plan)
    if not args.apply:
        if args.json:
            _print_json(result_payload)
        else:
            print("mode: dry-run")
        return 1 if plan.strict_blockers else 0

    result = apply_archive_renumber_plan(plan)
    if result.error is not None:
        if args.json:
            result_payload["result"] = result.to_dict()
            _print_json(result_payload)
        else:
            print(result.error, file=sys.stderr)
            for detail in result.recovery_details:
                print(f"  {detail}", file=sys.stderr)
        return 1
    if args.json:
        result_payload["result"] = result.to_dict()
        _print_json(result_payload)
    else:
        print(f"applied: rename={result.renamed} status_updated={result.status_updated}")
    return 0


def _print_error(as_json: bool, mode: str, message: str) -> None:
    if as_json:
        _print_json({"mode": mode, "error": message, "entries": []})
    else:
        print(f"ERROR {message}", file=sys.stderr)


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
