"""Make one BookWalker local quota attempt available again.

Both a failed entry and an additional book use this same manual operation.
This does not change BookWalker's server-side remaining reading time.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from screenshot_crawler.catalog import CatalogError, CatalogJobLockError, CatalogService, now_jst
from screenshot_crawler.catalog.models import Source
from screenshot_crawler.site_policies.bookwalker import BookWalkerSitePolicy


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Make one BookWalker local quota attempt available again in the current "
            "05:00 JST window. Does not add server-side reading time or accumulate slots."
        )
    )
    parser.add_argument(
        "--catalog", type=Path, default=Path("catalog.sqlite"),
        help="Catalog SQLite path (default: catalog.sqlite)",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Clear the current local reservation without creating a backup",
    )
    return parser


def _current_window_sources(catalog: CatalogService, now: datetime) -> list[Source]:
    window_start, window_end = BookWalkerSitePolicy.quota_window(now)
    candidates = []
    for source in catalog.list_sources(site="bookwalker"):
        if source.quota_started_at is None:
            continue
        try:
            started = datetime.fromisoformat(source.quota_started_at)
        except ValueError as exc:
            raise CatalogError(f"Invalid quota_started_at for Source {source.id}") from exc
        if started.tzinfo is None or started.utcoffset() is None:
            raise CatalogError(f"Source {source.id}: quota_started_at must be timezone-aware")
        if window_start <= started < window_end:
            candidates.append(source)
    return candidates


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.catalog.is_file():
        raise CatalogError(f"Catalog does not exist: {args.catalog}")
    catalog = CatalogService(args.catalog)
    with catalog.job_lock():
        candidates = _current_window_sources(catalog, now_jst())
        if not candidates:
            print("BookWalker local quota is already available (1 slot); no changes.")
            return 0
        if len(candidates) != 1:
            raise CatalogError(
                "Multiple current-window BookWalker reservations found; "
                "expected at most one. No changes."
            )
        source = candidates[0]
        print(f"Catalog: {args.catalog}")
        print(f"Source: {source.id} ({source.external_id})")
        print(f"Local reservation: {source.quota_started_at}")
        print("Action: restore one local slot (0 -> 1); no server-side time is added.")
        if not args.apply:
            print("Dry run only. Re-run with --apply to restore the slot.")
            return 0
        catalog.clear_quota_access(
            source.id,
            expected_quota_started_at=source.quota_started_at,
        )
        print("Applied. One local slot is available. No backup created.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (CatalogError, CatalogJobLockError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
