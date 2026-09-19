"""Read-only CSV snapshot export for the Schema v3 Catalog."""

from __future__ import annotations

import csv
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from screenshot_crawler.catalog import schema
from screenshot_crawler.catalog.service import CatalogError

EXPORT_COLUMNS = {
    "works": ("id", "work_key", "title", "author", "genre", "created_at", "updated_at"),
    "items": (
        "id", "work_id", "item_title", "kind", "order_key", "order_label", "status",
        "completed_at", "created_at", "updated_at",
    ),
    "sources": (
        "id", "item_id", "site", "external_id", "discovery_key", "access_mode",
        "free_until", "available", "access_checked_at", "last_seen_at", "quota_started_at",
        "access_granted_until", "created_at", "updated_at",
    ),
    "source_targets": (
        "id", "source_id", "backend", "target_key", "locator", "priority", "enabled",
        "created_at", "updated_at",
    ),
    "crawl_runs": (
        "id", "item_id", "source_id", "target_id", "site_snapshot", "external_id_snapshot",
        "backend_snapshot", "target_key_snapshot", "locator_snapshot", "access_strategy",
        "status", "started_at", "finished_at", "page_count", "stop_reason", "error_type",
        "error_message", "created_at", "updated_at",
    ),
    "artifacts": (
        "id", "item_id", "crawl_run_id", "kind", "format", "sha256", "byte_size",
        "storage_backend", "locator", "state", "last_verified_at", "created_at", "updated_at",
    ),
}

EXPORT_FILENAMES = tuple(f"{table}.csv" for table in EXPORT_COLUMNS)
_BOOLEAN_COLUMNS = {"available", "enabled"}


class CatalogExportError(CatalogError):
    """Raised when a Catalog cannot be exported."""


@dataclass(frozen=True, slots=True)
class ExportResult:
    """Summary of a completed six-table Catalog export."""

    output_dir: Path
    works: int
    items: int
    sources: int
    source_targets: int
    crawl_runs: int
    artifacts: int

    @property
    def total_rows(self) -> int:
        return (
            self.works + self.items + self.sources + self.source_targets
            + self.crawl_runs + self.artifacts
        )


def export_catalog_csv(catalog_path: str | Path, output_dir: str | Path) -> ExportResult:
    """Export all v3 Catalog tables to a read-only, six-CSV snapshot."""

    catalog_path = Path(catalog_path)
    output_dir = Path(output_dir)
    _validate_paths(catalog_path, output_dir)
    _reject_output_collisions(output_dir)

    try:
        connection = sqlite3.connect(_read_only_uri(catalog_path), uri=True)
        connection.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        raise CatalogExportError(
            f"Could not open Catalog database '{catalog_path}': {exc}"
        ) from exc

    staging_dir: Path | None = None
    counts: dict[str, int] = {}
    try:
        try:
            schema.validate_existing_schema(connection)
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("BEGIN")
            parent = output_dir.parent.resolve()
            parent.mkdir(parents=True, exist_ok=True)
            staging_dir = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=parent))
            for table, columns in EXPORT_COLUMNS.items():
                counts[table] = _write_table_csv(
                    connection, table, columns, staging_dir / f"{table}.csv"
                )
        except schema.SchemaError as exc:
            if staging_dir is not None:
                _cleanup_path(staging_dir)
            raise CatalogExportError(str(exc)) from exc
        except (sqlite3.DatabaseError, OSError, csv.Error) as exc:
            if staging_dir is not None:
                _cleanup_path(staging_dir)
            raise CatalogExportError(f"Could not export Catalog: {exc}") from exc
        finally:
            connection.rollback()
    finally:
        connection.close()

    assert staging_dir is not None
    try:
        _publish_staging(staging_dir, output_dir)
    except OSError as exc:
        _cleanup_path(staging_dir)
        raise CatalogExportError(
            f"Could not publish Catalog export '{output_dir}': {exc}"
        ) from exc

    return ExportResult(output_dir=output_dir, **counts)


def _validate_paths(catalog_path: Path, output_dir: Path) -> None:
    if not catalog_path.exists():
        raise CatalogExportError(f"Catalog path does not exist: {catalog_path}")
    if not catalog_path.is_file():
        raise CatalogExportError(f"Catalog path is not a file: {catalog_path}")
    if catalog_path.resolve() == output_dir.resolve():
        raise CatalogExportError("Catalog path and output directory must be different")
    if output_dir.exists() and not output_dir.is_dir():
        raise CatalogExportError(f"Output path is not a directory: {output_dir}")


def _reject_output_collisions(output_dir: Path) -> None:
    if output_dir.exists():
        collisions = [name for name in EXPORT_FILENAMES if (output_dir / name).exists()]
        if collisions:
            raise CatalogExportError(
                f"Catalog export output already contains: {', '.join(collisions)}"
            )


def _write_table_csv(
    connection: sqlite3.Connection,
    table: str,
    columns: tuple[str, ...],
    output_path: Path,
) -> int:
    quoted_columns = ", ".join(f'"{column}"' for column in columns)
    rows = connection.execute(
        f'SELECT {quoted_columns} FROM "{table}" ORDER BY "id" ASC'
    )
    count = 0
    with output_path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(columns)
        for row in rows:
            writer.writerow(_csv_value(column, row[column]) for column in columns)
            count += 1
    return count


def _publish_staging(staging_dir: Path, output_dir: Path) -> None:
    if not output_dir.exists():
        os.replace(staging_dir, output_dir)
        return

    published: list[Path] = []
    try:
        for filename in EXPORT_FILENAMES:
            destination = output_dir / filename
            os.replace(staging_dir / filename, destination)
            published.append(destination)
    except OSError:
        for path in published:
            _cleanup_path(path)
        raise
    finally:
        _cleanup_path(staging_dir)


def _cleanup_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists():
        try:
            path.unlink()
        except OSError:
            pass


def _read_only_uri(path: Path) -> str:
    return f"{path.resolve().as_uri()}?mode=ro"


def _csv_value(column: str, value: Any) -> str:
    if value is None:
        return ""
    if column in _BOOLEAN_COLUMNS:
        return "true" if value in (1, True) else "false"
    return str(value)
