"""SQLite Catalog schema and version guard."""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 4

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
        CHECK (status IN ('pending', 'completed')),
    completed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
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

CREATE INDEX idx_items_work_id ON items(work_id);
CREATE INDEX idx_sources_item_id ON sources(item_id);
CREATE INDEX idx_sources_site ON sources(site);
CREATE INDEX idx_sources_discovery_key ON sources(discovery_key);
CREATE INDEX idx_source_targets_source_id ON source_targets(source_id);
CREATE INDEX idx_crawl_runs_item_id ON crawl_runs(item_id);
CREATE INDEX idx_crawl_runs_source_id ON crawl_runs(source_id);
CREATE INDEX idx_crawl_runs_target_id ON crawl_runs(target_id);
CREATE INDEX idx_artifacts_item_id ON artifacts(item_id);
CREATE INDEX idx_artifacts_crawl_run_id ON artifacts(crawl_run_id);
"""

_REQUIRED_COLUMNS = {
    "works": {"id", "work_key", "title", "author", "genre", "created_at", "updated_at"},
    "items": {
        "id", "work_id", "item_title", "kind", "order_key", "order_label", "status",
        "completed_at", "created_at", "updated_at",
    },
    "sources": {
        "id", "item_id", "site", "external_id", "discovery_key", "access_mode",
        "free_until", "available", "access_checked_at", "last_seen_at", "quota_started_at",
        "access_granted_until", "published_at", "created_at", "updated_at",
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
}

_FORBIDDEN_COLUMNS = {
    "items": {"canonical_title", "author", "genre", "local_path"},
}


class SchemaError(RuntimeError):
    """Raised for an invalid or unsupported Catalog schema."""


def user_version(connection: sqlite3.Connection) -> int:
    return int(connection.execute("PRAGMA user_version").fetchone()[0])


def validate_existing_schema(connection: sqlite3.Connection) -> None:
    """Validate an existing v4 schema without creating or changing anything."""

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
            f"Catalog schema version 4 is missing table(s): {', '.join(sorted(missing_tables))}"
        )

    for table, required_columns in _REQUIRED_COLUMNS.items():
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        missing_columns = required_columns - columns
        if missing_columns:
            raise SchemaError(
                f"Catalog schema version 4 is missing {table} column(s): "
                f"{', '.join(sorted(missing_columns))}"
            )
        forbidden_columns = _FORBIDDEN_COLUMNS.get(table, set()) & columns
        if forbidden_columns:
            raise SchemaError(
                f"Catalog schema version 4 has removed {table} column(s): "
                f"{', '.join(sorted(forbidden_columns))}"
            )


def initialize(connection: sqlite3.Connection) -> None:
    """Create v4 or validate it; never migrate an existing schema."""

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
