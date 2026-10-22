"""SQLite Catalog v7 schema and version guard."""

from __future__ import annotations

import re
import sqlite3

SCHEMA_VERSION = 7

SCHEMA_SQL = """
CREATE TABLE works (
    id INTEGER PRIMARY KEY,
    work_key TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    author TEXT,
    genre TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE items (
    id INTEGER PRIMARY KEY,
    work_id INTEGER NOT NULL REFERENCES works(id),
    item_title TEXT,
    kind TEXT,
    order_key TEXT,
    order_label TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'completed', 'skipped', 'external')),
    completed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    note TEXT NULL
);

CREATE TABLE sources (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES items(id),
    site TEXT NOT NULL,
    external_id TEXT NOT NULL,
    discovery_key TEXT,
    access_mode TEXT NOT NULL DEFAULT 'unknown'
        CHECK (access_mode IN ('owned', 'free', 'quota', 'paid', 'unknown')),
    free_until TEXT,
    available INTEGER NOT NULL DEFAULT 1
        CHECK (available IN (0, 1)),
    access_checked_at TEXT,
    last_seen_at TEXT,
    quota_started_at TEXT,
    access_granted_until TEXT,
    published_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    display_position INTEGER NULL
        CHECK(display_position IS NULL OR display_position >= 1),
    acquisition_enabled INTEGER NOT NULL DEFAULT 1
        CHECK(acquisition_enabled IN (0, 1)),
    UNIQUE(site, external_id)
);

CREATE TABLE source_targets (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    backend TEXT NOT NULL,
    target_key TEXT NOT NULL DEFAULT 'default',
    locator TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 100
        CHECK(priority >= 0),
    enabled INTEGER NOT NULL DEFAULT 1
        CHECK(enabled IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(source_id, backend, target_key)
);

CREATE TABLE crawl_runs (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES items(id),
    source_id INTEGER NOT NULL REFERENCES sources(id),
    target_id INTEGER NOT NULL REFERENCES source_targets(id),
    site_snapshot TEXT NOT NULL,
    external_id_snapshot TEXT NOT NULL,
    backend_snapshot TEXT NOT NULL,
    target_key_snapshot TEXT NOT NULL,
    locator_snapshot TEXT NOT NULL,
    access_strategy TEXT NOT NULL
        CHECK(access_strategy IN ('auto', 'direct', 'quota')),
    status TEXT NOT NULL
        CHECK(status IN ('running', 'succeeded', 'failed')),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    page_count INTEGER CHECK(page_count IS NULL OR page_count >= 0),
    stop_reason TEXT,
    error_type TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE artifacts (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES items(id),
    crawl_run_id INTEGER REFERENCES crawl_runs(id),
    kind TEXT NOT NULL,
    format TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL CHECK(byte_size >= 0),
    storage_backend TEXT NOT NULL,
    locator TEXT,
    state TEXT NOT NULL
        CHECK(state IN ('present', 'missing', 'deleted', 'unknown')),
    last_verified_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE quota_resource_states (
    id INTEGER PRIMARY KEY,
    work_id INTEGER NOT NULL REFERENCES works(id),
    site TEXT NOT NULL,
    resource TEXT NOT NULL,
    last_consumed_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(work_id, site, resource)
);

CREATE TABLE acquisition_scope_sync (
    work_id INTEGER PRIMARY KEY REFERENCES works(id),
    fingerprint TEXT NOT NULL,
    definition_fingerprint TEXT NOT NULL,
    configuration_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('synced', 'stale')),
    synced_at TEXT NOT NULL
);

CREATE TABLE discovery_inventory_evidence (
    discovery_key TEXT PRIMARY KEY,
    work_id INTEGER NOT NULL REFERENCES works(id),
    site TEXT NOT NULL,
    target_url TEXT NOT NULL,
    scope_fingerprint TEXT NOT NULL,
    listing_identity TEXT NOT NULL,
    inventory_digest TEXT NOT NULL,
    source_count INTEGER NOT NULL CHECK(source_count >= 0),
    completed_at TEXT NOT NULL
);

CREATE TABLE discovery_inventory_positions (
    discovery_key TEXT NOT NULL REFERENCES discovery_inventory_evidence(discovery_key)
        ON DELETE CASCADE,
    site TEXT NOT NULL,
    external_id TEXT NOT NULL,
    display_position INTEGER NOT NULL CHECK(display_position >= 1),
    in_scope INTEGER NOT NULL CHECK(in_scope IN (0, 1)),
    PRIMARY KEY(discovery_key, site, external_id),
    UNIQUE(discovery_key, display_position)
);

CREATE INDEX idx_items_work_id ON items(work_id);
CREATE INDEX idx_sources_item_id ON sources(item_id);
CREATE INDEX idx_sources_site ON sources(site);
CREATE INDEX idx_sources_discovery_key ON sources(discovery_key);
CREATE INDEX idx_sources_acquisition_enabled ON sources(acquisition_enabled);
CREATE INDEX idx_source_targets_source_id ON source_targets(source_id);
CREATE INDEX idx_crawl_runs_item_id ON crawl_runs(item_id);
CREATE INDEX idx_crawl_runs_source_id ON crawl_runs(source_id);
CREATE INDEX idx_crawl_runs_target_id ON crawl_runs(target_id);
CREATE INDEX idx_artifacts_item_id ON artifacts(item_id);
CREATE INDEX idx_artifacts_crawl_run_id ON artifacts(crawl_run_id);
CREATE INDEX idx_quota_resource_states_work_id ON quota_resource_states(work_id);
CREATE INDEX idx_quota_resource_states_site_resource
    ON quota_resource_states(site, resource);
CREATE INDEX idx_discovery_inventory_work_key
    ON discovery_inventory_evidence(work_id, discovery_key);
CREATE INDEX idx_discovery_inventory_positions_position
    ON discovery_inventory_positions(discovery_key, display_position);
"""

_REQUIRED_COLUMNS = {
    "works": {"id", "work_key", "title", "author", "genre", "created_at", "updated_at"},
    "items": {
        "id", "work_id", "item_title", "kind", "order_key", "order_label", "status",
        "completed_at", "created_at", "updated_at", "note",
    },
    "sources": {
        "id", "item_id", "site", "external_id", "discovery_key", "access_mode",
        "free_until", "available", "access_checked_at", "last_seen_at", "quota_started_at",
        "access_granted_until", "published_at", "created_at", "updated_at", "display_position",
        "acquisition_enabled",
    },
    "source_targets": {
        "id", "source_id", "backend", "target_key", "locator", "priority", "enabled",
        "created_at", "updated_at",
    },
    "crawl_runs": {
        "id", "item_id", "source_id", "target_id", "site_snapshot", "external_id_snapshot",
        "backend_snapshot", "target_key_snapshot", "locator_snapshot", "access_strategy",
        "status", "started_at", "finished_at", "page_count", "stop_reason", "error_type",
        "error_message", "created_at", "updated_at",
    },
    "artifacts": {
        "id", "item_id", "crawl_run_id", "kind", "format", "sha256", "byte_size",
        "storage_backend", "locator", "state", "last_verified_at", "created_at", "updated_at",
    },
    "quota_resource_states": {
        "id", "work_id", "site", "resource", "last_consumed_at", "created_at", "updated_at",
    },
    "acquisition_scope_sync": {
        "work_id", "fingerprint", "definition_fingerprint", "configuration_json", "status", "synced_at",
    },
    "discovery_inventory_evidence": {
        "discovery_key", "work_id", "site", "target_url", "scope_fingerprint", "listing_identity",
        "inventory_digest", "source_count", "completed_at",
    },
    "discovery_inventory_positions": {
        "discovery_key", "site", "external_id", "display_position", "in_scope",
    },
}

_FORBIDDEN_COLUMNS = {
    "items": {"canonical_title", "author", "genre", "local_path"},
}


class SchemaError(RuntimeError):
    """Raised for an invalid or unsupported Catalog schema."""


def user_version(connection: sqlite3.Connection) -> int:
    return int(connection.execute("PRAGMA user_version").fetchone()[0])


def validate_existing_schema(connection: sqlite3.Connection) -> None:
    """Validate an existing v7 schema without creating or changing anything."""

    version = user_version(connection)
    if version != SCHEMA_VERSION:
        raise SchemaError(
            f"Unsupported Catalog schema version {version}; supported version is {SCHEMA_VERSION}"
        )

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    missing_tables = set(_REQUIRED_COLUMNS) - tables
    if missing_tables:
        raise SchemaError(
            f"Catalog schema version 7 is missing table(s): {', '.join(sorted(missing_tables))}"
        )

    for table, required_columns in _REQUIRED_COLUMNS.items():
        column_rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
        columns = {row[1] for row in column_rows}
        missing_columns = required_columns - columns
        if missing_columns:
            raise SchemaError(
                f"Catalog schema version 7 is missing {table} column(s): "
                f"{', '.join(sorted(missing_columns))}"
            )
        forbidden_columns = _FORBIDDEN_COLUMNS.get(table, set()) & columns
        if forbidden_columns:
            raise SchemaError(
                f"Catalog schema version 7 has removed {table} column(s): "
                f"{', '.join(sorted(forbidden_columns))}"
            )
        if table == "sources":
            acquisition = next(row for row in column_rows if row[1] == "acquisition_enabled")
            if acquisition[3] != 1 or str(acquisition[4]).strip("'\"") != "1":
                raise SchemaError(
                    "Catalog schema version 7 requires sources.acquisition_enabled "
                    "to be NOT NULL with DEFAULT 1"
                )

    _require_check_constraint(
        connection,
        "items",
        "check(statusin('pending','completed','skipped','external'))",
        "items.status",
    )
    _require_check_constraint(
        connection,
        "sources",
        "check(display_positionisnullordisplay_position>=1)",
        "sources.display_position",
    )
    _require_check_constraint(
        connection,
        "acquisition_scope_sync",
        "check(statusin('synced','stale'))",
        "acquisition_scope_sync.status",
    )
    _require_check_constraint(
        connection,
        "sources",
        "check(acquisition_enabledin(0,1))",
        "sources.acquisition_enabled",
    )
    _require_check_constraint(
        connection,
        "discovery_inventory_evidence",
        "check(source_count>=0)",
        "discovery_inventory_evidence.source_count",
    )
    _require_check_constraint(
        connection,
        "discovery_inventory_positions",
        "check(display_position>=1)",
        "discovery_inventory_positions.display_position",
    )
    _require_check_constraint(
        connection,
        "discovery_inventory_positions",
        "check(in_scopein(0,1))",
        "discovery_inventory_positions.in_scope",
    )
    _require_primary_key(connection, "acquisition_scope_sync", ("work_id",))
    _require_primary_key(connection, "discovery_inventory_evidence", ("discovery_key",))
    _require_primary_key(
        connection, "discovery_inventory_positions", ("discovery_key", "site", "external_id")
    )
    _require_unique(
        connection,
        "discovery_inventory_positions",
        ("discovery_key", "display_position"),
    )
    _require_foreign_key(
        connection, "acquisition_scope_sync", "work_id", "works", "id", "NO ACTION"
    )
    _require_foreign_key(
        connection, "discovery_inventory_evidence", "work_id", "works", "id", "NO ACTION"
    )
    _require_foreign_key(
        connection,
        "discovery_inventory_positions",
        "discovery_key",
        "discovery_inventory_evidence",
        "discovery_key",
        "CASCADE",
    )
    for name, table, columns in (
        ("idx_sources_acquisition_enabled", "sources", ("acquisition_enabled",)),
        ("idx_discovery_inventory_work_key", "discovery_inventory_evidence", ("work_id", "discovery_key")),
        ("idx_discovery_inventory_positions_position", "discovery_inventory_positions", ("discovery_key", "display_position")),
    ):
        _require_index(connection, name, table, columns)


def initialize(connection: sqlite3.Connection) -> None:
    """Create v7 or validate it; never migrate an existing schema."""

    version = user_version(connection)
    if version not in (0, SCHEMA_VERSION):
        raise SchemaError(
            f"Unsupported Catalog schema version {version}; supported version is {SCHEMA_VERSION}"
        )

    if version == SCHEMA_VERSION:
        validate_existing_schema(connection)
        return

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    if tables:
        raise SchemaError("Catalog contains unversioned tables and cannot be initialized safely")

    connection.executescript(SCHEMA_SQL)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def _require_check_constraint(
    connection: sqlite3.Connection,
    table: str,
    expected: str,
    field: str,
) -> None:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    sql = "" if row is None or row[0] is None else row[0]
    normalized = re.sub(r"\s+", "", sql).casefold()
    if expected not in normalized:
        raise SchemaError(
            f"Catalog schema version 7 has an invalid {field} CHECK constraint"
        )


def _require_primary_key(
    connection: sqlite3.Connection, table: str, expected_columns: tuple[str, ...]
) -> None:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    actual = tuple(row[1] for row in sorted((row for row in rows if row[5]), key=lambda row: row[5]))
    if actual != expected_columns:
        raise SchemaError(
            f"Catalog schema version 7 has an invalid {table} primary key"
        )


def _require_unique(
    connection: sqlite3.Connection, table: str, expected_columns: tuple[str, ...]
) -> None:
    indexes = connection.execute(f"PRAGMA index_list({table})").fetchall()
    for index in indexes:
        if not index[2]:
            continue
        escaped = str(index[1]).replace('"', '""')
        columns = tuple(
            row[2] for row in connection.execute(f'PRAGMA index_info("{escaped}")')
        )
        if columns == expected_columns:
            return
    raise SchemaError(
        f"Catalog schema version 7 is missing a unique constraint on "
        f"{table}({', '.join(expected_columns)})"
    )


def _require_foreign_key(
    connection: sqlite3.Connection,
    table: str,
    from_column: str,
    target_table: str,
    target_column: str,
    on_delete: str,
) -> None:
    rows = connection.execute(f"PRAGMA foreign_key_list({table})").fetchall()
    if not any(
        row[2] == target_table
        and row[3] == from_column
        and row[4] == target_column
        and str(row[6]).upper() == on_delete
        for row in rows
    ):
        raise SchemaError(
            f"Catalog schema version 7 has an invalid {table}.{from_column} foreign key"
        )


def _require_index(
    connection: sqlite3.Connection,
    name: str,
    table: str,
    expected_columns: tuple[str, ...],
) -> None:
    row = connection.execute(
        "SELECT tbl_name FROM sqlite_master WHERE type = 'index' AND name = ?", (name,)
    ).fetchone()
    if row is None or row[0] != table:
        raise SchemaError(f"Catalog schema version 7 is missing required index {name}")
    escaped = name.replace('"', '""')
    columns = tuple(
        item[2] for item in connection.execute(f'PRAGMA index_info("{escaped}")')
    )
    if columns != expected_columns:
        raise SchemaError(f"Catalog schema version 7 has an invalid index {name}")
