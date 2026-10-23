#!/usr/bin/env python3
"""Read-only audit for existing archive names and crawl-status sidecars."""

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
from screenshot_crawler.maintenance.archive_audit import (
    ArchiveAuditUsageError,
    audit_existing_archives,
)
from screenshot_crawler.watchlist.service import WatchlistService


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit existing ZIP archive names and status sidecars (read-only)."
    )
    parser.add_argument("--catalog", type=Path, default=Path("catalog.sqlite"))
    parser.add_argument("--watchlist", type=Path, default=Path("watchlist.yaml"))
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--work-key", help="Audit one complete Catalog Work")
    scope.add_argument(
        "--site",
        help="Audit complete Works containing this site, including their other sites",
    )
    scope.add_argument("--all", dest="all_sources", action="store_true", help="Audit all Works")
    parser.add_argument("--json", action="store_true", help="Print one JSON document")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if not args.watchlist.exists():
            raise CatalogError(f"Watchlist file not found: {args.watchlist}")
        watchlist = WatchlistService(args.watchlist)
        report = audit_existing_archives(
            CatalogService(args.catalog),
            work_key=args.work_key,
            site=args.site,
            all_sources=args.all_sources,
            watchlist=watchlist,
        )
    except ArchiveAuditUsageError as exc:
        payload = {"work_keys": [], "findings": [], "errors": [str(exc)]}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        else:
            print(f"ERROR {exc}", file=sys.stderr)
        return 2
    except (CatalogError, OSError, ValueError) as exc:
        payload = {"work_keys": [], "findings": [], "errors": [str(exc)]}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        else:
            print(f"ERROR {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True))
    else:
        for finding in report.findings:
            print(f"FINDING {finding}")
        for error in report.errors:
            print(f"ERROR {error}", file=sys.stderr)
        print(
            f"summary: works={len(report.work_keys)} findings={len(report.findings)} "
            f"errors={len(report.errors)}"
        )
    return 1 if report.findings or report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
