"""Read-only CSV export for human inspection of Catalog state."""

from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from screenshot_crawler.catalog import schema
from screenshot_crawler.catalog.service import CatalogError

EXPORT_COLUMNS = (
    "item_id",
    "source_id",
    "target_id",
    "canonical_title",
    "author",
    "genre",
    "kind",
    "order_key",
    "order_label",
    "status",
    "local_path",
    "completed_at",
    "site",
    "external_id",
    "discovery_key",
    "backend",
    "locator",
    "priority",
    "target_enabled",
    "access_mode",
    "free_until",
    "available",
    "access_checked_at",
    "last_seen_at",
    "quota_started_at",
    "access_granted_until",
    "item_created_at",
    "item_updated_at",
    "source_created_at",
    "source_updated_at",
)

_ITEM_COLUMNS = {
    "id",
    "canonical_title",
    "author",
    "genre",
    "kind",
    "order_key",
    "order_label",
    "status",
    "local_path",
    "completed_at",
    "created_at",
    "updated_at",
}
_SOURCE_COLUMNS = {
    "id",
    "item_id",
    "site",
    "external_id",
    "discovery_key",
    "access_mode",
    "free_until",
    "available",
    "access_checked_at",
    "last_seen_at",
    "quota_started_at",
    "access_granted_until",
    "created_at",
    "updated_at",
}
_TARGET_COLUMNS = {
    "id",
    "source_id",
    "backend",
    "locator",
    "priority",
    "enabled",
    "created_at",
    "updated_at",
}


class CatalogExportError(CatalogError):
    """Raised when a Catalog cannot be exported."""


@dataclass(frozen=True, slots=True)
class ExportResult:
    """Summary of a completed Catalog export."""

    rows: int
    output_path: Path


_EXPORT_QUERY = """
SELECT
    i.id AS item_id,
    s.id AS source_id,
    i.canonical_title AS canonical_title,
    i.author AS author,
    i.genre AS genre,
    i.kind AS kind,
    i.order_key AS order_key,
    i.order_label AS order_label,
    i.status AS status,
    i.local_path AS local_path,
    i.completed_at AS completed_at,
    s.site AS site,
    s.external_id AS external_id,
    s.discovery_key AS discovery_key,
    st.id AS target_id,
    st.backend AS backend,
    st.locator AS locator,
    st.priority AS priority,
    st.enabled AS target_enabled,
    s.access_mode AS access_mode,
    s.free_until AS free_until,
    s.available AS available,
    s.access_checked_at AS access_checked_at,
    s.last_seen_at AS last_seen_at,
    s.quota_started_at AS quota_started_at,
    s.access_granted_until AS access_granted_until,
    i.created_at AS item_created_at,
    i.updated_at AS item_updated_at,
    s.created_at AS source_created_at,
    s.updated_at AS source_updated_at
FROM items AS i
LEFT JOIN sources AS s
    ON s.item_id = i.id
LEFT JOIN source_targets AS st
    ON st.source_id = s.id
ORDER BY i.id ASC, s.id ASC, st.id ASC
"""


def export_catalog_csv(
    catalog_path: str | Path, output_path: str | Path
) -> ExportResult:
    """Export the Catalog to a UTF-8 BOM CSV without modifying the database."""

    catalog_path = Path(catalog_path)
    output_path = Path(output_path)
    if not catalog_path.exists():
        raise CatalogExportError(f"Catalog path does not exist: {catalog_path}")
    if not catalog_path.is_file():
        raise CatalogExportError(f"Catalog path is not a file: {catalog_path}")
    if catalog_path.resolve() == output_path.resolve():
        raise CatalogExportError("Catalog and CSV output paths must be different")

    try:
        connection = sqlite3.connect(_read_only_uri(catalog_path), uri=True)
        connection.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        raise CatalogExportError(f"Could not open Catalog database '{catalog_path}': {exc}") from exc

    try:
        _validate_schema(connection)
        try:
            rows = connection.execute(_EXPORT_QUERY).fetchall()
        except sqlite3.DatabaseError as exc:
            raise CatalogExportError(f"Could not read Catalog data: {exc}") from exc
    finally:
        connection.close()

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8-sig", newline="") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(EXPORT_COLUMNS)
            for row in rows:
                writer.writerow(
                    _csv_value(column, row[column]) for column in EXPORT_COLUMNS
                )
    except (OSError, csv.Error) as exc:
        raise CatalogExportError(f"Could not write Catalog CSV '{output_path}': {exc}") from exc

    return ExportResult(rows=len(rows), output_path=output_path)


def _read_only_uri(path: Path) -> str:
    return f"{path.resolve().as_uri()}?mode=ro"


def _validate_schema(connection: sqlite3.Connection) -> None:
    try:
        version = schema.user_version(connection)
        if version != schema.SCHEMA_VERSION:
            raise CatalogExportError(
                f"Unsupported or missing Catalog schema version {version}; "
                f"supported version is {schema.SCHEMA_VERSION}"
            )

        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        if not {"items", "sources", "source_targets"}.issubset(tables):
            raise CatalogExportError(
                "Catalog schema is missing items, sources, or source_targets table"
            )

        for table, required_columns in (
            ("items", _ITEM_COLUMNS),
            ("sources", _SOURCE_COLUMNS),
            ("source_targets", _TARGET_COLUMNS),
        ):
            columns = {
                row[1] for row in connection.execute(f"PRAGMA table_info({table})")
            }
            missing = required_columns - columns
            if missing:
                missing_columns = ", ".join(sorted(missing))
                raise CatalogExportError(
                    f"Catalog schema is missing {table} column(s): {missing_columns}"
                )
    except CatalogExportError:
        raise
    except sqlite3.DatabaseError as exc:
        raise CatalogExportError(f"Catalog is not a valid SQLite database: {exc}") from exc


def _csv_value(column: str, value: Any) -> str:
    if value is None:
        return ""
    if column in {"available", "target_enabled"}:
        if value in (0, False):
            return "false"
        if value in (1, True):
            return "true"
    return str(value)
