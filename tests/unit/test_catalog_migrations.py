import sqlite3
from pathlib import Path

import pytest

from screenshot_crawler.catalog import CatalogService
from screenshot_crawler.catalog.backup import CatalogBackupError, backup_catalog
from screenshot_crawler.catalog.migrations import (
    CatalogMigrationError,
    _run_migrations,
    migrate_catalog,
)
from screenshot_crawler.catalog.schema import SCHEMA_SQL


def make_database(path: Path, *, version: int = 3, value: str = "before") -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE marker (value TEXT NOT NULL)")
        connection.execute("INSERT INTO marker VALUES (?)", (value,))
        connection.execute(f"PRAGMA user_version = {version}")


def test_current_v6_migration_is_noop_without_backup(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite"
    CatalogService(path).initialize()
    before = path.read_bytes()

    result = migrate_catalog(path, backup_dir=tmp_path / "backup")

    assert result.from_version == 6
    assert result.to_version == 6
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


def test_backup_is_taken_while_migration_writer_lock_is_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "catalog.sqlite"
    backup_dir = tmp_path / "backup"
    make_database(path)
    lock_observations: list[bool] = []

    import screenshot_crawler.catalog.migrations as migration_module

    def locked_backup(source: Path, destination: Path):
        contender = sqlite3.connect(source, timeout=0.05)
        try:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                contender.execute("BEGIN IMMEDIATE")
            return backup_catalog(source, destination)
        finally:
            contender.close()

    monkeypatch.setattr(migration_module, "backup_catalog", locked_backup)

    def migration(connection: sqlite3.Connection) -> None:
        lock_observations.append(connection.in_transaction)
        connection.execute("UPDATE marker SET value = 'after'")

    _run_migrations(
        path,
        target_version=4,
        migrations={3: migration},
        final_validator=lambda connection: None,
        backup_dir=backup_dir,
    )

    assert lock_observations == [True]


def test_backup_failure_rolls_back_lock_without_calling_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "catalog.sqlite"
    backup_dir = tmp_path / "backup"
    make_database(path)
    migration_calls = 0

    import screenshot_crawler.catalog.migrations as migration_module

    def fail_backup(source: Path, destination: Path):
        raise CatalogBackupError("simulated locked backup failure")

    monkeypatch.setattr(migration_module, "backup_catalog", fail_backup)

    def migration(connection: sqlite3.Connection) -> None:
        nonlocal migration_calls
        migration_calls += 1

    with pytest.raises(CatalogMigrationError, match="simulated locked backup failure"):
        _run_migrations(
            path,
            target_version=4,
            migrations={3: migration},
            final_validator=lambda connection: None,
            backup_dir=backup_dir,
        )

    assert migration_calls == 0
    assert not list(backup_dir.glob("*.sqlite"))
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
        assert connection.execute("SELECT value FROM marker").fetchone()[0] == "before"
        connection.execute("UPDATE marker SET value = 'after failure'")
        connection.commit()


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


@pytest.mark.parametrize("version", [0, 7])
def test_invalid_migration_version_is_rejected_without_backup(
    tmp_path: Path, version: int
) -> None:
    path = tmp_path / f"catalog-{version}.sqlite"
    make_database(path, version=version)

    expected = "version 0" if version == 0 else "newer than supported"
    with pytest.raises(CatalogMigrationError, match=expected):
        migrate_catalog(path, backup_dir=tmp_path / "backup")

    assert not (tmp_path / "backup").exists()


def test_production_v3_to_v6_migration_preserves_rows_and_creates_backup(
    tmp_path: Path,
) -> None:
    path = tmp_path / "catalog-v3.sqlite"
    backup_dir = tmp_path / "backup"
    old_schema_sql = SCHEMA_SQL.replace(
        "CHECK (status IN ('pending', 'completed', 'skipped', 'external'))",
        "CHECK (status IN ('pending', 'completed'))",
    )
    old_schema_sql = old_schema_sql.replace("    note TEXT NULL\n", "")
    old_schema_sql = old_schema_sql.replace(
        "    updated_at TEXT NOT NULL,\n);", "    updated_at TEXT NOT NULL\n);"
    )
    old_schema_sql = old_schema_sql.replace(
        "    display_position INTEGER NULL\n        CHECK(display_position IS NULL OR display_position >= 1),\n",
        "",
    )
    old_schema_sql = old_schema_sql.replace("    published_at TEXT,\n", "")
    old_schema_sql = old_schema_sql.replace(
        """CREATE TABLE quota_resource_states (
    id INTEGER PRIMARY KEY,
    work_id INTEGER NOT NULL REFERENCES works(id),
    site TEXT NOT NULL,
    resource TEXT NOT NULL,
    last_consumed_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(work_id, site, resource)
);

""",
        "",
    )
    old_schema_sql = old_schema_sql.replace(
        "CREATE INDEX idx_quota_resource_states_work_id ON quota_resource_states(work_id);\n",
        "",
    ).replace(
        "CREATE INDEX idx_quota_resource_states_site_resource\n    ON quota_resource_states(site, resource);\n",
        "",
    )
    with sqlite3.connect(path) as connection:
        connection.executescript(old_schema_sql)
        connection.execute(
            "INSERT INTO works (work_key, title, created_at, updated_at) "
            "VALUES ('w', 'Work', '2026-01-01T00:00:00+09:00', '2026-01-01T00:00:00+09:00')"
        )
        connection.execute(
            "INSERT INTO items (work_id, status, completed_at, created_at, updated_at) "
            "VALUES (1, 'completed', '2026-01-02T00:00:00+09:00', "
            "'2026-01-01T00:00:00+09:00', '2026-01-01T00:00:00+09:00')"
        )
        connection.execute(
            "INSERT INTO sources (item_id, site, external_id, created_at, updated_at) "
            "VALUES (1, 'magapoke', 'e1', '2026-01-01T00:00:00+09:00', '2026-01-01T00:00:00+09:00')"
        )
        connection.execute("PRAGMA user_version = 3")

    result = migrate_catalog(path, backup_dir=backup_dir)

    assert result.migrated is True
    assert result.from_version == 3 and result.to_version == 6
    assert result.backup_path is not None and result.backup_path.is_file()
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 6
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT count(*) FROM works").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM items").fetchone()[0] == 1
        item = connection.execute(
            "SELECT id, status, completed_at, note FROM items"
        ).fetchone()
        assert item == (1, "completed", "2026-01-02T00:00:00+09:00", None)
        assert connection.execute("SELECT published_at FROM sources").fetchone()[0] is None
        assert connection.execute("SELECT display_position FROM sources").fetchone()[0] is None
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name = 'quota_resource_states'"
        ).fetchone() is not None


def test_production_v5_to_v6_migration_preserves_ids_and_foreign_keys(
    tmp_path: Path,
) -> None:
    path = tmp_path / "catalog-v5.sqlite"
    backup_dir = tmp_path / "backup"
    old_schema_sql = SCHEMA_SQL.replace(
        "CHECK (status IN ('pending', 'completed', 'skipped', 'external'))",
        "CHECK (status IN ('pending', 'completed'))",
    )
    old_schema_sql = old_schema_sql.replace("    note TEXT NULL\n", "")
    old_schema_sql = old_schema_sql.replace(
        "    updated_at TEXT NOT NULL,\n);", "    updated_at TEXT NOT NULL\n);"
    )
    old_schema_sql = old_schema_sql.replace(
        "    display_position INTEGER NULL\n        CHECK(display_position IS NULL OR display_position >= 1),\n",
        "",
    )
    with sqlite3.connect(path) as connection:
        connection.executescript(old_schema_sql)
        connection.execute(
            "INSERT INTO works (work_key, title, created_at, updated_at) "
            "VALUES ('w', 'Work', '2026-01-01T00:00:00+09:00', '2026-01-01T00:00:00+09:00')"
        )
        connection.execute(
            "INSERT INTO items (work_id, item_title, status, completed_at, created_at, updated_at) "
            "VALUES (1, 'Episode', 'completed', '2026-01-02T00:00:00+09:00', "
            "'2026-01-01T00:00:00+09:00', '2026-01-01T00:00:00+09:00')"
        )
        connection.execute(
            "INSERT INTO sources (item_id, site, external_id, created_at, updated_at) "
            "VALUES (1, 'magapoke', 'episode-1', '2026-01-01T00:00:00+09:00', "
            "'2026-01-01T00:00:00+09:00')"
        )
        connection.execute(
            "INSERT INTO source_targets (source_id, backend, locator, created_at, updated_at) "
            "VALUES (1, 'web', 'https://example.invalid/1', "
            "'2026-01-01T00:00:00+09:00', '2026-01-01T00:00:00+09:00')"
        )
        connection.execute(
            "INSERT INTO crawl_runs ("
            "item_id, source_id, target_id, site_snapshot, external_id_snapshot, "
            "backend_snapshot, target_key_snapshot, locator_snapshot, access_strategy, "
            "status, started_at, finished_at, page_count, stop_reason, error_type, "
            "error_message, created_at, updated_at"
            ") VALUES (1, 1, 1, 'magapoke', 'episode-1', 'web', 'default', "
            "'https://example.invalid/1', 'direct', 'succeeded', "
            "'2026-01-02T00:00:00+09:00', '2026-01-02T00:05:00+09:00', 3, "
            "'normal', NULL, NULL, '2026-01-02T00:00:00+09:00', "
            "'2026-01-02T00:05:00+09:00')"
        )
        connection.execute(
            "INSERT INTO artifacts ("
            "item_id, crawl_run_id, kind, format, sha256, byte_size, storage_backend, "
            "locator, state, last_verified_at, created_at, updated_at"
            ") VALUES (1, 1, 'archive', 'zip', "
            "'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 123, "
            "'filesystem', 'archives/work/episode-1.zip', 'present', "
            "'2026-01-02T00:05:00+09:00', '2026-01-02T00:05:00+09:00', "
            "'2026-01-02T00:05:00+09:00')"
        )
        connection.execute("PRAGMA user_version = 5")

    result = migrate_catalog(path, backup_dir=backup_dir)

    assert result.from_version == 5
    assert result.to_version == 6
    assert result.backup_path is not None and result.backup_path.is_file()
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 6
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT id FROM works").fetchone()[0] == 1
        assert connection.execute(
            "SELECT id, status, completed_at, note FROM items"
        ).fetchone() == (1, "completed", "2026-01-02T00:00:00+09:00", None)
        assert connection.execute("SELECT id FROM sources").fetchone()[0] == 1
        assert connection.execute("SELECT display_position FROM sources").fetchone()[0] is None
        assert connection.execute("SELECT id FROM source_targets").fetchone()[0] == 1
        assert connection.execute(
            "SELECT id, item_id, source_id, target_id FROM crawl_runs"
        ).fetchone() == (1, 1, 1, 1)
        assert connection.execute(
            "SELECT id, item_id, crawl_run_id FROM artifacts"
        ).fetchone() == (1, 1, 1)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    service = CatalogService(path)
    with service._connection() as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
