"""Initial SQLite schema and version guard."""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 1

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
    url TEXT NOT NULL,
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
"""


class SchemaError(RuntimeError):
    """Raised for an invalid or unsupported Catalog schema."""


def user_version(connection: sqlite3.Connection) -> int:
    return int(connection.execute("PRAGMA user_version").fetchone()[0])


def initialize(connection: sqlite3.Connection) -> None:
    """Create the initial schema, refusing unknown pre-existing versions."""

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
        if not {"items", "sources"}.issubset(tables):
            raise SchemaError("Catalog schema version 1 is missing items or sources table")
        return
    if tables:
        raise SchemaError("Catalog contains unversioned tables and cannot be initialized safely")

    connection.executescript(SCHEMA_SQL)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
