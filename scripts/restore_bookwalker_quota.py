"""Safely clear an accidental BookWalker quota reservation in the Catalog.

This repairs the local Catalog reservation only. It cannot reverse time
already consumed on BookWalker's servers.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from screenshot_crawler.catalog import (
    CatalogError,
    CatalogService,
    backup_catalog,
    default_backup_path,
    now_jst,
)
from screenshot_crawler.site_policies.bookwalker import BookWalkerSitePolicy


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Clear one accidental BookWalker quota reservation from the local Catalog. "
            "--apply creates a verified backup before changing it."
        )
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=Path("catalog.sqlite"),
        help="Catalog SQLite path (default: catalog.sqlite)",
    )
    selector = parser.add_mutually_exclusive_group()
    selector.add_argument("--crawl-run-id", type=_positive_int, help="Failed quota CrawlRun id")
    selector.add_argument("--source-id", type=_positive_int, help="BookWalker Source id")
    selector.add_argument("--external-id", help="BookWalker external_id")
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=Path("backup"),
        help="Directory for the automatic pre-repair backup (default: backup)",
    )
    parser.add_argument(
        "--allow-expired",
        action="store_true",
        help="Allow clearing a reservation outside the current 05:00 JST window",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Create a backup and clear the selected local reservation",
    )
    return parser


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return parsed


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise CatalogError(f"Invalid quota_started_at timestamp: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CatalogError("quota_started_at must be timezone-aware")
    return parsed


def _select_source(args: argparse.Namespace, catalog: CatalogService):
    if args.crawl_run_id is not None:
        run = catalog.get_crawl_run(args.crawl_run_id)
        if run.site_snapshot != "bookwalker":
            raise CatalogError(f"CrawlRun {run.id} is not a BookWalker run")
        if run.access_strategy != "quota":
            raise CatalogError(f"CrawlRun {run.id} is not a quota run")
        if run.status != "failed":
            raise CatalogError(
                f"CrawlRun {run.id} has status {run.status!r}; only failed runs are eligible"
            )
        return catalog.get_source(run.source_id), run

    if args.source_id is not None:
        source = catalog.get_source(args.source_id)
    elif args.external_id is not None:
        source = catalog.get_source_by_external_id("bookwalker", args.external_id)
    else:
        candidates = _current_window_sources(catalog, now_jst())
        if not candidates:
            raise CatalogError("No current-window BookWalker quota reservations found")
        if len(candidates) > 1:
            ids = ", ".join(str(source.id) for source in candidates)
            raise CatalogError(
                f"Multiple current-window reservations found ({ids}); specify --source-id "
                "or --crawl-run-id"
            )
        source = candidates[0]
    return source, None


def _current_window_sources(catalog: CatalogService, now: datetime):
    window_start, window_end = BookWalkerSitePolicy.quota_window(now)
    candidates = []
    for source in catalog.list_sources(site="bookwalker"):
        if source.quota_started_at is None:
            continue
        started = _parse_timestamp(source.quota_started_at).astimezone(now.tzinfo)
        if window_start <= started < window_end:
            candidates.append(source)
    return candidates


def _validate_source(source, *, now: datetime, allow_expired: bool) -> None:
    if source.site != "bookwalker":
        raise CatalogError(f"Source {source.id} is not a BookWalker source")
    if source.access_mode != "quota":
        raise CatalogError(
            f"Source {source.id} has access_mode={source.access_mode!r}; expected 'quota'"
        )
    if source.quota_started_at is None:
        raise CatalogError(f"Source {source.id} has no local quota reservation")
    if not allow_expired:
        started = _parse_timestamp(source.quota_started_at).astimezone(now.tzinfo)
        window_start, window_end = BookWalkerSitePolicy.quota_window(now)
        if not window_start <= started < window_end:
            raise CatalogError(
                f"Source {source.id} reservation is outside the current 05:00 JST window; "
                "use --allow-expired only for an intentional historical repair"
            )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    catalog = CatalogService(args.catalog)
    source, run = _select_source(args, catalog)
    now = now_jst()
    _validate_source(source, now=now, allow_expired=args.allow_expired)

    print("BookWalker local quota reservation:")
    print(f"  catalog: {args.catalog}")
    print(f"  source_id: {source.id}")
    print(f"  external_id: {source.external_id}")
    print(f"  quota_started_at: {source.quota_started_at}")
    if run is not None:
        print(f"  crawl_run_id: {run.id} (failed)")
    print("  action: clear quota_started_at/access_granted_until only")
    print("  site-side BookWalker usage cannot be reversed by this script")

    if not args.apply:
        print("Dry run only. Re-run with --apply to create a backup and apply the repair.")
        return 0

    backup_path = default_backup_path(args.catalog, args.backup_dir)
    backup = backup_catalog(args.catalog, backup_path)
    try:
        cleared = catalog.clear_quota_access(
            source.id,
            expected_quota_started_at=source.quota_started_at,
        )
    except Exception:
        print(f"Backup retained: {backup.backup_path}", file=sys.stderr)
        raise
    print(f"Applied. Backup: {backup.backup_path}")
    print(
        f"  quota_started_at: {cleared.quota_started_at}; "
        f"access_granted_until: {cleared.access_granted_until}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CatalogError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
