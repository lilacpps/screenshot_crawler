#!/usr/bin/env python3
"""Thin CLI wrapper for the existing-archive renumber maintenance operation."""

from __future__ import annotations

import argparse
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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Safely renumber existing ZIP archive filenames from Catalog positions."
    )
    parser.add_argument("--work-key", help="Limit the scope to one Catalog Work key")
    parser.add_argument("--site", help="Limit the scope to one source site")
    parser.add_argument("--all", dest="all_sources", action="store_true", help="Process all Sources")
    parser.add_argument("--catalog", type=Path, default=Path("catalog.sqlite"))
    parser.add_argument("--status-dir", type=Path, default=Path("output/crawl-status"))
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
                "status_mismatch", "errors",
            )
        )
    )


def _status_label(entry) -> str:
    if entry.status_path is not None:
        return "MATCH"
    return entry.status_warning or "UNKNOWN"


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        plan = build_archive_renumber_plan(
            CatalogService(args.catalog),
            work_key=args.work_key,
            site=args.site,
            all_sources=args.all_sources,
            status_dir=args.status_dir,
        )
    except ArchiveRenumberUsageError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 2
    except (CatalogError, OSError, ValueError) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1

    _print_plan(plan)
    if not args.apply:
        print("mode: dry-run")
        return 0

    result = apply_archive_renumber_plan(plan)
    if result.error is not None:
        print(result.error, file=sys.stderr)
        for detail in result.recovery_details:
            print(f"  {detail}", file=sys.stderr)
        return 1
    print(f"applied: rename={result.renamed} status_updated={result.status_updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
