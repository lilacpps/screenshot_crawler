#!/usr/bin/env python3
"""Relocate Catalog-tracked ZIP archives after a wrong `--library-dir`.

Run from the screenshot_crawler repository root using its Python environment.
Dry-run is the default. `--apply` backs up the Catalog and performs changes.

Only Catalog-tracked, present filesystem ZIP archives under --before are
relocated. Other files and Catalog items are not modified.

Example:
    python scripts/repair_library_dir.py --before library --after output/Books
    python scripts/repair_library_dir.py --before library --after output/Books --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from screenshot_crawler.catalog.service import CatalogService


@dataclass(frozen=True)
class Entry:
    artifact_id: int
    old_locator: str
    old_zip: Path
    new_zip: Path
    old_status: Path
    new_status: Path
    original_status_bytes: bytes
    status_content: dict


def tracked_entries(
    catalog: CatalogService, *, before: Path, after: Path
) -> tuple[list[Entry], list[str]]:
    entries: list[Entry] = []
    problems: list[str] = []
    before_abs = before.resolve()

    for artifact in catalog.list_artifacts():
        locator = artifact.locator
        if not locator or artifact.storage_backend != "filesystem":
            continue
        locator_path = Path(locator)
        # A locator outside the requested source root is unrelated and untouched.
        try:
            relative = locator_path.resolve().relative_to(before_abs)
        except ValueError:
            continue

        if (artifact.kind, artifact.format, artifact.state) != ("archive", "zip", "present"):
            problems.append(f"artifact={artifact.id}: unexpected type/state for {locator}")
            continue
        # Do not rewrite a suspicious traversal or a root-level ZIP.
        if (not relative.parts or len(relative.parts) < 3
                or ".." in locator_path.parts or relative.suffix.lower() != ".zip"):
            problems.append(f"artifact={artifact.id}: unsafe/unexpected ZIP locator {locator}")
            continue

        old_zip = before / relative
        new_zip = after / relative
        # The packaging implementation stores JSON beside the library root,
        # under <library-root-parent>/crawl-status/<genre>/<work>/<stem>.json.
        old_status = before.parent / "crawl-status" / relative.with_suffix(".json")
        new_status = after.parent / "crawl-status" / relative.with_suffix(".json")

        if not old_zip.is_file():
            problems.append(f"artifact={artifact.id}: missing source ZIP: {old_zip}")
            continue
        if new_zip.exists():
            problems.append(f"artifact={artifact.id}: ZIP destination already exists: {new_zip}")
            continue
        if not old_status.is_file():
            problems.append(f"artifact={artifact.id}: missing status JSON: {old_status}")
            continue
        # If before and after have the same parent, the status filename is the
        # same: it must be updated in place instead of treated as a collision.
        if old_status.resolve() != new_status.resolve() and new_status.exists():
            problems.append(f"artifact={artifact.id}: status JSON destination exists: {new_status}")
            continue

        try:
            original_bytes = old_status.read_bytes()
            content = json.loads(original_bytes.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            problems.append(f"artifact={artifact.id}: unreadable status JSON {old_status}: {exc}")
            continue
        if not isinstance(content, dict) or content.get("archive_path") != locator:
            problems.append(
                f"artifact={artifact.id}: status archive_path does not match Catalog: {old_status}"
            )
            continue

        entries.append(Entry(
            artifact.id, locator, old_zip, new_zip, old_status, new_status,
            original_bytes, content,
        ))

    for description, paths in (
        ("source ZIP", [entry.old_zip.resolve() for entry in entries]),
        ("destination ZIP", [entry.new_zip.resolve() for entry in entries]),
        ("source status JSON", [entry.old_status.resolve() for entry in entries]),
        ("destination status JSON", [entry.new_status.resolve() for entry in entries]),
    ):
        if len(set(paths)) != len(paths):
            problems.append(f"duplicate {description} detected among selected Catalog artifacts")
    return entries, problems


def backup_database(path: Path) -> Path:
    folder = Path("backup")
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    backup = folder / f"{path.stem}-before-library-repair-{stamp}.sqlite"
    with sqlite3.connect(path) as source, sqlite3.connect(backup) as destination:
        source.backup(destination)
    return backup


def write_bytes_atomic(path: Path, contents: bytes, *, overwrite: bool) -> None:
    """Write JSON in one replace step. Caller must have preflighted conflicts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not overwrite and path.exists():
        raise FileExistsError(path)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=".library-repair-",
            suffix=".tmp", delete=False,
        ) as tmp:
            temp_path = Path(tmp.name)
            tmp.write(contents)
        if not overwrite and path.exists():
            raise FileExistsError(path)
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def run() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--before", "--before-library-dir", type=Path, default=Path("library"),
        help="Incorrect original --library-dir (default: library)",
    )
    parser.add_argument(
        "--after", "--after-library-dir", type=Path, default=Path("output/Books"),
        help="Desired --library-dir (default: output/Books)",
    )
    parser.add_argument("--catalog", type=Path, default=Path("catalog.sqlite"))
    parser.add_argument("--apply", action="store_true", help="Apply after preflight and DB backup")
    args = parser.parse_args()

    if not Path("pyproject.toml").is_file() or not Path("src/screenshot_crawler").is_dir():
        parser.error("Run from the screenshot_crawler repository root")
    if not args.catalog.is_file():
        parser.error(f"Catalog DB not found: {args.catalog}")
    before_abs, after_abs = args.before.resolve(), args.after.resolve()
    if before_abs == after_abs:
        parser.error("--before and --after resolve to the same directory")
    if before_abs in after_abs.parents or after_abs in before_abs.parents:
        parser.error("--before and --after must not be nested within each other")
    if not args.before.is_dir():
        parser.error(f"Source library directory not found: {args.before}")

    catalog = CatalogService(args.catalog)
    entries, problems = tracked_entries(catalog, before=args.before, after=args.after)
    print(f"Catalog: {args.catalog}")
    print(f"Before (--library-dir): {args.before}")
    print(f"After  (--library-dir): {args.after}")
    print(f"Tracked ZIPs eligible for relocation: {len(entries)}")
    for entry in entries[:15]:
        suffix = " (JSON updated in place)" if entry.old_status.resolve() == entry.new_status.resolve() else ""
        print(f"  artifact={entry.artifact_id}: {entry.old_zip} -> {entry.new_zip}{suffix}")
    if len(entries) > 15:
        print(f"  ...and {len(entries) - 15} more")
    if problems:
        print("\nPREFLIGHT FAILED; nothing changed:")
        for problem in problems:
            print("  - " + problem)
        return 1
    if not entries:
        print("Nothing to relocate. (Untracked ZIPs are not touched.)")
        return 0
    if not args.apply:
        print("\nDry-run only. Repeat with --apply to back up the DB and perform relocation.")
        return 0

    backup = backup_database(args.catalog)
    print(f"Database backup created: {backup}")
    moved_zips: list[Entry] = []
    new_statuses: list[Entry] = []
    rewritten_statuses: list[Entry] = []
    try:
        for entry in entries:
            entry.new_zip.parent.mkdir(parents=True, exist_ok=True)
            if entry.new_zip.exists():
                raise FileExistsError(entry.new_zip)
            entry.old_zip.rename(entry.new_zip)
            moved_zips.append(entry)
            content = dict(entry.status_content, archive_path=entry.new_zip.as_posix())
            new_bytes = (json.dumps(content, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            same_status = entry.old_status.resolve() == entry.new_status.resolve()
            write_bytes_atomic(entry.new_status, new_bytes, overwrite=same_status)
            (rewritten_statuses if same_status else new_statuses).append(entry)

        # Update Catalog paths together with compare-and-set; keep Item statuses unchanged.
        catalog.update_artifact_locators({
            entry.artifact_id: (entry.old_locator, entry.new_zip.as_posix())
            for entry in entries
        })
    except Exception as exc:
        print(f"ERROR during relocation: {exc}")
        # If a DB commit somehow succeeded before reporting an error, do NOT
        # move files back while the Catalog refers to the new paths.
        try:
            catalog_changed = any(
                catalog.get_artifact(entry.artifact_id).locator != entry.old_locator
                for entry in entries
            )
        except Exception:
            catalog_changed = True
        if catalog_changed:
            print("Catalog may have changed. Manual recovery required; DB backup retained.")
            return 1
        print("Rolling back file changes (DB backup retained)...")
        rollback_errors: list[str] = []
        for entry in reversed(new_statuses):
            try:
                entry.new_status.unlink(missing_ok=True)
            except OSError as rollback_exc:
                rollback_errors.append(str(rollback_exc))
        for entry in reversed(rewritten_statuses):
            try:
                write_bytes_atomic(entry.old_status, entry.original_status_bytes, overwrite=True)
            except OSError as rollback_exc:
                rollback_errors.append(str(rollback_exc))
        for entry in reversed(moved_zips):
            try:
                entry.new_zip.rename(entry.old_zip)
            except OSError as rollback_exc:
                rollback_errors.append(str(rollback_exc))
        for message in rollback_errors:
            print("  ROLLBACK ERROR: " + message)
        if rollback_errors:
            print("Manual recovery required; do not run Batch before reconciliation.")
        return 1

    cleanup_errors: list[str] = []
    for entry in entries:
        if entry.old_status.resolve() == entry.new_status.resolve():
            continue
        try:
            entry.old_status.unlink()
        except OSError as exc:
            cleanup_errors.append(f"{entry.old_status}: {exc}")

    confirmed = 0
    for entry in entries:
        try:
            status = json.loads(entry.new_status.read_text(encoding="utf-8"))
            if (catalog.get_artifact(entry.artifact_id).locator == entry.new_zip.as_posix()
                    and entry.new_zip.is_file()
                    and status.get("archive_path") == entry.new_zip.as_posix()):
                confirmed += 1
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass
    print(f"DONE: relocated={len(entries)}, verified={confirmed}, Catalog item status unchanged")
    print(f"Database backup: {backup}")
    if cleanup_errors:
        print("Old status JSON cleanup warnings:")
        for message in cleanup_errors:
            print("  " + message)
    return 0 if confirmed == len(entries) else 1


if __name__ == "__main__":
    raise SystemExit(run())