"""Explicit, transactional Catalog schema migration infrastructure."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from screenshot_crawler.catalog import schema
from screenshot_crawler.catalog.backup import backup_catalog
from screenshot_crawler.catalog.service import CatalogError, format_timestamp, now_jst

Migration = Callable[[sqlite3.Connection], None]

def migrate_v3_to_v4(connection: sqlite3.Connection) -> None:
    connection.execute("ALTER TABLE sources ADD COLUMN published_at TEXT")


MIGRATIONS: dict[int, Migration] = {3: migrate_v3_to_v4}


class CatalogMigrationError(CatalogError):
    """Raised when an explicit Catalog migration cannot be completed."""


@dataclass(frozen=True, slots=True)
class MigrationResult:
    database_path: Path
    from_version: int
    to_version: int
    migrated: bool
    backup_path: Path | None


def migrate_catalog(
    catalog_path: str | Path,
    *,
    backup_dir: str | Path = "backup",
) -> MigrationResult:
    """Migrate explicitly to the current code schema, if a path exists."""

    catalog_path = Path(catalog_path)
    _validate_catalog_path(catalog_path)
    current_version = _read_version(catalog_path)
    target_version = schema.SCHEMA_VERSION
    return _run_migrations(
        catalog_path,
        target_version=target_version,
        migrations=MIGRATIONS,
        final_validator=schema.validate_existing_schema,
        backup_dir=backup_dir,
        current_version=current_version,
    )


def _run_migrations(
    catalog_path: str | Path,
    *,
    target_version: int,
    migrations: Mapping[int, Migration],
    final_validator: Callable[[sqlite3.Connection], None],
    backup_dir: str | Path,
    current_version: int | None = None,
) -> MigrationResult:
    """Run a validated migration chain; the injectable boundary is test-friendly."""

    catalog_path = Path(catalog_path)
    _validate_catalog_path(catalog_path)
    if current_version is None:
        current_version = _read_version(catalog_path)
    _validate_migration_versions(current_version, target_version)
    if current_version == target_version:
        _validate_current_database(catalog_path, final_validator)
        return MigrationResult(catalog_path, current_version, target_version, False, None)

    _validate_path_exists(current_version, target_version, migrations)
    backup_path = _automatic_backup_path(catalog_path, backup_dir, current_version, target_version)
    connection: sqlite3.Connection | None = None
    backup_result = None
    try:
        connection = sqlite3.connect(catalog_path)
        connection.execute("BEGIN IMMEDIATE")
        try:
            backup_result = backup_catalog(catalog_path, backup_path)
        except Exception as exc:
            raise CatalogMigrationError(
                f"Could not create pre-migration backup for schema {current_version} -> "
                f"{target_version}: {exc}"
            ) from exc
        version = current_version
        while version < target_version:
            migration = migrations[version]
            migration(connection)
            version += 1
            connection.execute(f"PRAGMA user_version = {version}")
        _quick_check(connection, catalog_path)
        final_validator(connection)
        connection.commit()
    except Exception as exc:
        if connection is not None:
            try:
                connection.rollback()
            except sqlite3.Error:
                pass
        if isinstance(exc, CatalogMigrationError):
            raise
        raise CatalogMigrationError(
            f"Catalog migration {current_version} -> {target_version} failed; "
            f"backup: {backup_result.backup_path}; error: {exc}"
        ) from exc
    finally:
        if connection is not None:
            connection.close()

    return MigrationResult(
        database_path=catalog_path,
        from_version=current_version,
        to_version=target_version,
        migrated=True,
        backup_path=backup_result.backup_path,
    )


def _validate_catalog_path(catalog_path: Path) -> None:
    if not catalog_path.exists():
        raise CatalogMigrationError(f"Catalog path does not exist: {catalog_path}")
    if not catalog_path.is_file():
        raise CatalogMigrationError(f"Catalog path is not a file: {catalog_path}")


def _read_version(catalog_path: Path) -> int:
    try:
        connection = sqlite3.connect(
            f"{catalog_path.resolve().as_uri()}?mode=ro", uri=True
        )
        try:
            return int(connection.execute("PRAGMA user_version").fetchone()[0])
        finally:
            connection.close()
    except sqlite3.DatabaseError as exc:
        raise CatalogMigrationError(
            f"Catalog is not a valid SQLite database: {catalog_path}"
        ) from exc


def _validate_migration_versions(current_version: int, target_version: int) -> None:
    if current_version == 0:
        raise CatalogMigrationError("Schema version 0 is not a migration candidate")
    if current_version > target_version:
        raise CatalogMigrationError(
            f"Database schema version {current_version} is newer than supported version "
            f"{target_version}"
        )


def _validate_path_exists(
    current_version: int,
    target_version: int,
    migrations: Mapping[int, Migration],
) -> None:
    version = current_version
    while version < target_version:
        if version not in migrations:
            raise CatalogMigrationError(
                f"No migration path from schema version {current_version} to {target_version}"
            )
        version += 1


def _validate_current_database(
    catalog_path: Path,
    final_validator: Callable[[sqlite3.Connection], None],
) -> None:
    try:
        connection = sqlite3.connect(
            f"{catalog_path.resolve().as_uri()}?mode=ro", uri=True
        )
        try:
            _quick_check(connection, catalog_path)
            final_validator(connection)
        finally:
            connection.close()
    except CatalogMigrationError:
        raise
    except (sqlite3.DatabaseError, schema.SchemaError) as exc:
        raise CatalogMigrationError(
            f"Current Catalog schema validation failed: {exc}"
        ) from exc


def _quick_check(connection: sqlite3.Connection, catalog_path: Path) -> None:
    try:
        result = connection.execute("PRAGMA quick_check").fetchone()[0]
    except sqlite3.DatabaseError as exc:
        raise CatalogMigrationError(f"Catalog quick_check failed: {exc}") from exc
    if result != "ok":
        raise CatalogMigrationError(
            f"Catalog quick_check failed for '{catalog_path}': {result}"
        )


def _automatic_backup_path(
    catalog_path: Path,
    backup_dir: str | Path,
    current_version: int,
    target_version: int,
) -> Path:
    directory = Path(backup_dir)
    timestamp = format_timestamp(now_jst()) or "unknown"
    safe_timestamp = timestamp.replace(":", "").replace("-", "").replace(".", "")
    safe_timestamp = safe_timestamp.replace("+", "+")
    base = directory / (
        f"{catalog_path.stem}-v{current_version}-before-v{target_version}-"
        f"{safe_timestamp}.sqlite"
    )
    candidate = base
    suffix = 1
    while candidate.exists():
        candidate = base.with_name(f"{base.stem}-{suffix}{base.suffix}")
        suffix += 1
    return candidate
