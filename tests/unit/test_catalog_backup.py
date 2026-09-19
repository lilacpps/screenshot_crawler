import sqlite3
from pathlib import Path

import pytest

from screenshot_crawler.catalog.backup import (
    CatalogBackupError,
    backup_catalog,
)


def make_database(path: Path, *, version: int = 3, value: str = "before") -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE marker (value TEXT NOT NULL)")
        connection.execute("INSERT INTO marker VALUES (?)", (value,))
        connection.execute(f"PRAGMA user_version = {version}")


def test_backup_preserves_schema_data_and_quick_check(tmp_path: Path) -> None:
    source = tmp_path / "catalog.sqlite"
    destination = tmp_path / "backup" / "catalog.sqlite"
    make_database(source, version=2)

    result = backup_catalog(source, destination)

    assert result.schema_version == 2
    assert result.byte_size == destination.stat().st_size
    with sqlite3.connect(destination) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        assert connection.execute("SELECT value FROM marker").fetchone()[0] == "before"
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"


def test_backup_handles_wal_data_without_copying_wal_files(tmp_path: Path) -> None:
    source = tmp_path / "catalog.sqlite"
    destination = tmp_path / "catalog-backup.sqlite"
    connection = sqlite3.connect(source)
    try:
        assert connection.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
        connection.execute("CREATE TABLE marker (value TEXT NOT NULL)")
        connection.execute("INSERT INTO marker VALUES ('wal value')")
        connection.execute("PRAGMA user_version = 3")
        connection.commit()

        backup_catalog(source, destination)
    finally:
        connection.close()

    with sqlite3.connect(destination) as backup:
        assert backup.execute("SELECT value FROM marker").fetchone()[0] == "wal value"
        assert backup.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert not Path(f"{destination}-wal").exists()
    assert not Path(f"{destination}-shm").exists()


def test_backup_rejects_existing_destination_without_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "catalog.sqlite"
    destination = tmp_path / "backup.sqlite"
    make_database(source)
    destination.write_bytes(b"keep me")

    with pytest.raises(CatalogBackupError, match="already exists"):
        backup_catalog(source, destination)

    assert destination.read_bytes() == b"keep me"


def test_backup_rejects_missing_directory_and_non_sqlite(tmp_path: Path) -> None:
    with pytest.raises(CatalogBackupError, match="does not exist"):
        backup_catalog(tmp_path / "missing.sqlite", tmp_path / "backup.sqlite")

    source = tmp_path / "not.sqlite"
    source.write_text("not sqlite", encoding="utf-8")
    with pytest.raises(CatalogBackupError, match="valid SQLite"):
        backup_catalog(source, tmp_path / "backup.sqlite")


def test_backup_failure_cleans_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "catalog.sqlite"
    destination = tmp_path / "backup.sqlite"
    make_database(source)

    import screenshot_crawler.catalog.backup as backup_module

    def fail_verification(*args: object, **kwargs: object) -> None:
        raise CatalogBackupError("simulated verification failure")

    monkeypatch.setattr(backup_module, "_verify_backup", fail_verification)
    with pytest.raises(CatalogBackupError, match="simulated verification failure"):
        backup_catalog(source, destination)

    assert not destination.exists()
    assert not list(tmp_path.glob(".backup.sqlite.*.tmp"))
