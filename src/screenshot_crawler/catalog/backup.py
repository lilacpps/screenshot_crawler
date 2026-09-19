"""Schema-neutral SQLite online backups for Catalog databases."""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path

from screenshot_crawler.catalog.service import CatalogError, format_timestamp, now_jst


class CatalogBackupError(CatalogError):
    """Raised when a Catalog backup cannot be created or verified."""


@dataclass(frozen=True, slots=True)
class BackupResult:
    source_path: Path
    backup_path: Path
    schema_version: int
    byte_size: int


def default_backup_path(
    source_path: str | Path,
    backup_dir: str | Path = "backup",
) -> Path:
    """Return a collision-free automatic backup filename without creating it."""

    source_path = Path(source_path)
    timestamp = _safe_timestamp()
    base = Path(backup_dir) / f"{source_path.stem}-backup-{timestamp}.sqlite"
    candidate = base
    suffix = 1
    while candidate.exists():
        candidate = base.with_name(f"{base.stem}-{suffix}{base.suffix}")
        suffix += 1
    return candidate


def backup_catalog(
    source_path: str | Path,
    destination_path: str | Path,
) -> BackupResult:
    """Create a verified standalone SQLite backup without changing the source."""

    source_path = Path(source_path)
    destination_path = Path(destination_path)
    _validate_paths(source_path, destination_path)

    parent = destination_path.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise CatalogBackupError(
            f"Could not create backup directory '{parent}': {exc}"
        ) from exc

    temporary_path: Path | None = None
    source_connection: sqlite3.Connection | None = None
    destination_connection: sqlite3.Connection | None = None
    verified = False
    try:
        source_connection = sqlite3.connect(_read_only_uri(source_path), uri=True)
        source_version = _read_user_version(source_connection, source_path)
        temporary_path = _temporary_path(parent, destination_path.name)
        destination_connection = sqlite3.connect(temporary_path)
        source_connection.backup(destination_connection)
        destination_connection.commit()
        destination_connection.execute("PRAGMA journal_mode = DELETE")
        destination_connection.commit()
        _verify_backup(destination_connection, source_version, temporary_path)
        verified = True
    except CatalogBackupError:
        raise
    except (sqlite3.Error, OSError) as exc:
        raise CatalogBackupError(
            f"Could not backup Catalog '{source_path}' to '{destination_path}': {exc}"
        ) from exc
    finally:
        if destination_connection is not None:
            destination_connection.close()
        if source_connection is not None:
            source_connection.close()
        if not verified and temporary_path is not None:
            _cleanup(temporary_path)

    assert temporary_path is not None
    try:
        if destination_path.exists():
            raise CatalogBackupError(
                f"Backup destination already exists: {destination_path}"
            )
        os.replace(temporary_path, destination_path)
    except CatalogBackupError:
        _cleanup(temporary_path)
        raise
    except OSError as exc:
        _cleanup(temporary_path)
        raise CatalogBackupError(
            f"Could not publish Catalog backup '{destination_path}': {exc}"
        ) from exc

    return BackupResult(
        source_path=source_path,
        backup_path=destination_path,
        schema_version=source_version,
        byte_size=destination_path.stat().st_size,
    )


def _validate_paths(source_path: Path, destination_path: Path) -> None:
    if not source_path.exists():
        raise CatalogBackupError(f"Catalog path does not exist: {source_path}")
    if not source_path.is_file():
        raise CatalogBackupError(f"Catalog path is not a file: {source_path}")
    if source_path.resolve() == destination_path.resolve():
        raise CatalogBackupError("Catalog source and backup destination must be different")
    if destination_path.exists():
        raise CatalogBackupError(
            f"Backup destination already exists: {destination_path}"
        )


def _read_only_uri(path: Path) -> str:
    return f"{path.resolve().as_uri()}?mode=ro"


def _read_user_version(connection: sqlite3.Connection, path: Path) -> int:
    try:
        return int(connection.execute("PRAGMA user_version").fetchone()[0])
    except sqlite3.DatabaseError as exc:
        raise CatalogBackupError(f"Catalog is not a valid SQLite database: {path}") from exc


def _verify_backup(
    connection: sqlite3.Connection,
    source_version: int,
    backup_path: Path,
) -> None:
    try:
        quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
        backup_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    except sqlite3.DatabaseError as exc:
        raise CatalogBackupError(f"Could not verify backup '{backup_path}': {exc}") from exc
    if quick_check != "ok":
        raise CatalogBackupError(
            f"Catalog backup integrity check failed for '{backup_path}': {quick_check}"
        )
    if backup_version != source_version:
        raise CatalogBackupError(
            f"Catalog backup schema version changed from {source_version} to {backup_version}"
        )


def _temporary_path(parent: Path, name: str) -> Path:
    handle, raw_path = tempfile.mkstemp(prefix=f".{name}.", suffix=".tmp", dir=parent)
    os.close(handle)
    path = Path(raw_path)
    _cleanup(path)
    return path


def _safe_timestamp() -> str:
    timestamp = format_timestamp(now_jst()) or "unknown"
    return timestamp.replace("-", "").replace(":", "").replace(".", "")


def _cleanup(path: Path) -> None:
    paths = (path, Path(f"{path}-wal"), Path(f"{path}-shm"))
    for candidate in paths:
        if candidate.is_dir():
            shutil.rmtree(candidate, ignore_errors=True)
        elif candidate.exists():
            try:
                candidate.unlink()
            except OSError:
                pass
