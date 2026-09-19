"""SQLite Catalog schema and version guard."""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 2

SCHEMA_SQL = """
CREATE TABLE items (
    id INTEGER PRIMARY KEY,
    canonical_title TEXT,
    author TEXT,
    genre TEXT,
    kind TEXT,
    order_key TEXT,
    order_label TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'completed')),
    local_path TEXT,
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
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (site, external_id)
);

CREATE TABLE source_targets (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    backend TEXT NOT NULL,
    locator TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 100
        CHECK (priority >= 0),
    enabled INTEGER NOT NULL DEFAULT 1
        CHECK (enabled IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (source_id, backend)
);
"""

_REQUIRED_COLUMNS = {
    "items": {
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
    },
    "sources": {
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
    },
    "source_targets": {
        "id",
        "source_id",
        "backend",
        "locator",
        "priority",
        "enabled",
        "created_at",
        "updated_at",
    },
}
_FORBIDDEN_COLUMNS = {"sources": {"url"}}


class SchemaError(RuntimeError):
    """Raised for an invalid or unsupported Catalog schema."""


def user_version(connection: sqlite3.Connection) -> int:
    return int(connection.execute("PRAGMA user_version").fetchone()[0])


def initialize(connection: sqlite3.Connection) -> None:
    """Create the schema or validate an existing Catalog without migrating it."""

    version = user_version(connection)
    if version not in (0, SCHEMA_VERSION):
        raise SchemaError(
            f"Unsupported Catalog schema version {version}; supported version is {SCHEMA_VERSION}"
        )

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    if version == SCHEMA_VERSION:
        missing_tables = set(_REQUIRED_COLUMNS) - tables
        if missing_tables:
            names = ", ".join(sorted(missing_tables))
            raise SchemaError(f"Catalog schema version 2 is missing table(s): {names}")
        for table, required_columns in _REQUIRED_COLUMNS.items():
            columns = {
                row[1] for row in connection.execute(f"PRAGMA table_info({table})")
            }
            missing_columns = required_columns - columns
            if missing_columns:
                names = ", ".join(sorted(missing_columns))
                raise SchemaError(
                    f"Catalog schema version 2 is missing {table} column(s): {names}"
                )
            forbidden_columns = _FORBIDDEN_COLUMNS.get(table, set()) & columns
            if forbidden_columns:
                names = ", ".join(sorted(forbidden_columns))
                raise SchemaError(
                    f"Catalog schema version 2 has removed {table} column(s): {names}"
                )
        return
    if tables:
        raise SchemaError("Catalog contains unversioned tables and cannot be initialized safely")

    connection.executescript(SCHEMA_SQL)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
