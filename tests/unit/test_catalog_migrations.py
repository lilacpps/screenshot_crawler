import sqlite3
from pathlib import Path

import pytest

from screenshot_crawler.catalog import CatalogService
from screenshot_crawler.catalog.migrations import (
    CatalogMigrationError,
    _run_migrations,
    migrate_catalog,
)


def make_database(path: Path, *, version: int = 3, value: str = "before") -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE marker (value TEXT NOT NULL)")
        connection.execute("INSERT INTO marker VALUES (?)", (value,))
        connection.execute(f"PRAGMA user_version = {version}")


def test_production_v3_migration_is_noop_without_backup(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite"
    CatalogService(path).initialize()
    before = path.read_bytes()

    result = migrate_catalog(path, backup_dir=tmp_path / "backup")

    assert result.from_version == 3
    assert result.to_version == 3
    assert result.migrated is False
    assert result.backup_path is None
    assert path.read_bytes() == before
    assert not (tmp_path / "backup").exists()


def test_injected_migration_creates_backup_before_update(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite"
    backup_dir = tmp_path / "backup"
    make_database(path)
    observed: list[bool] = []

    def migration(connection: sqlite3.Connection) -> None:
        observed.append(any(backup_dir.glob("*.sqlite")))
        connection.execute("UPDATE marker SET value = 'after'")

    def validate(connection: sqlite3.Connection) -> None:
        assert connection.execute("SELECT value FROM marker").fetchone()[0] == "after"

    result = _run_migrations(
        path,
        target_version=4,
        migrations={3: migration},
        final_validator=validate,
        backup_dir=backup_dir,
    )

    assert observed == [True]
    assert result.migrated is True
    assert result.backup_path is not None
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
        assert connection.execute("SELECT value FROM marker").fetchone()[0] == "after"
    with sqlite3.connect(result.backup_path) as backup:
        assert backup.execute("PRAGMA user_version").fetchone()[0] == 3
        assert backup.execute("SELECT value FROM marker").fetchone()[0] == "before"


def test_injected_migration_rolls_back_but_keeps_backup(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite"
    backup_dir = tmp_path / "backup"
    make_database(path)

    def migration(connection: sqlite3.Connection) -> None:
        connection.execute("UPDATE marker SET value = 'partial'")
        raise RuntimeError("migration failed")

    with pytest.raises(CatalogMigrationError, match="migration failed"):
        _run_migrations(
            path,
            target_version=4,
            migrations={3: migration},
            final_validator=lambda connection: None,
            backup_dir=backup_dir,
        )

    backups = list(backup_dir.glob("*.sqlite"))
    assert len(backups) == 1
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
        assert connection.execute("SELECT value FROM marker").fetchone()[0] == "before"


def test_missing_migration_step_rejects_before_backup_or_mutation(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite"
    backup_dir = tmp_path / "backup"
    make_database(path)
    before = path.read_bytes()

    with pytest.raises(CatalogMigrationError, match="No migration path"):
        _run_migrations(
            path,
            target_version=5,
            migrations={3: lambda connection: None},
            final_validator=lambda connection: None,
            backup_dir=backup_dir,
        )

    assert path.read_bytes() == before
    assert not backup_dir.exists()


@pytest.mark.parametrize("version", [0, 4])
def test_invalid_migration_version_is_rejected_without_backup(
    tmp_path: Path, version: int
) -> None:
    path = tmp_path / f"catalog-{version}.sqlite"
    make_database(path, version=version)

    expected = "version 0" if version == 0 else "newer than supported"
    with pytest.raises(CatalogMigrationError, match=expected):
        migrate_catalog(path, backup_dir=tmp_path / "backup")

    assert not (tmp_path / "backup").exists()
