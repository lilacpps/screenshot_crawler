"""Small SQLite repository for Catalog state."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from screenshot_crawler.catalog import schema
from screenshot_crawler.catalog.models import (
    CatalogRecord,
    Item,
    ItemInput,
    Source,
    SourceInput,
)

# A fixed offset is intentional: this tool's persistence policy is JST, not
# the host machine's timezone database or UTC normalization.
JST = timezone(timedelta(hours=9), name="JST")
_UNSET = object()


class CatalogError(RuntimeError):
    """Base error for Catalog operations."""


class CatalogValidationError(CatalogError, ValueError):
    """Raised when Catalog input is invalid."""


class CatalogNotFoundError(CatalogError):
    """Raised when a requested Catalog row does not exist."""


class UnsupportedSchemaVersionError(CatalogError):
    """Raised when a database uses a schema version this code cannot handle."""


def now_jst() -> datetime:
    """Return an aware current timestamp in the fixed JST timezone."""

    return datetime.now(JST)


def format_timestamp(value: datetime | str | None) -> str | None:
    """Normalize an aware datetime or ISO timestamp to an offset-bearing JST string."""

    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise CatalogValidationError(f"Invalid ISO timestamp: {value!r}") from exc
    else:
        raise CatalogValidationError("Timestamp must be an aware datetime, ISO string, or null")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CatalogValidationError("Naive datetimes are not allowed in the Catalog")
    return parsed.astimezone(JST).isoformat()


class CatalogService:
    """Connection-per-operation SQLite Catalog service.

    The service owns connection setup, including foreign-key enforcement, so
    callers never need to manage SQLite connection lifecycle themselves.
    """

    def __init__(self, path: str | Path = "catalog.sqlite") -> None:
        self.path = Path(path)

    def initialize(self) -> None:
        """Create the initial two-table schema or validate the existing one."""

        with self._connection(initialize_schema=False) as connection:
            try:
                schema.initialize(connection)
            except schema.SchemaError as exc:
                raise self._schema_error(exc) from exc

    def schema_version(self) -> int:
        """Return ``PRAGMA user_version`` without silently migrating it."""

        if not self.path.exists():
            return 0
        with self._connection(initialize_schema=False) as connection:
            return schema.user_version(connection)

    def create_item(self, item: ItemInput | None = None, **fields: Any) -> Item:
        """Create an item independently of a source."""

        item_input = self._coerce_item_input(item, fields)
        self._validate_status(item_input.status)
        timestamp = format_timestamp(now_jst())
        with self._connection() as connection:
            cursor = connection.execute(
                "INSERT INTO items (canonical_title, author, genre, kind, order_key, order_label, "
                "status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    item_input.canonical_title,
                    item_input.author,
                    item_input.genre,
                    item_input.kind,
                    item_input.order_key,
                    item_input.order_label,
                    item_input.status,
                    timestamp,
                    timestamp,
                ),
            )
            row = connection.execute(
                "SELECT * FROM items WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return self._item_from_row(row)

    def get_item(self, item_id: int) -> Item:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise CatalogNotFoundError(f"Catalog item not found: {item_id}")
        return self._item_from_row(row)

    def list_items(self, *, status: str | None = None) -> list[Item]:
        if status is not None:
            self._validate_status(status)
        with self._connection() as connection:
            if status is None:
                rows = connection.execute("SELECT * FROM items ORDER BY id").fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM items WHERE status = ? ORDER BY id", (status,)
                ).fetchall()
        return [self._item_from_row(row) for row in rows]

    def create_source(
        self, source: SourceInput | Mapping[str, Any], *, item_id: int
    ) -> Source:
        """Create a source for an existing item."""

        source = self._coerce_source_input(source)
        self._validate_source_input(source)
        timestamp = format_timestamp(now_jst())
        last_seen = format_timestamp(source.last_seen_at) or timestamp
        with self._connection() as connection:
            try:
                cursor = connection.execute(
                    "INSERT INTO sources (item_id, site, external_id, discovery_key, url, access_mode, "
                    "free_until, available, access_checked_at, last_seen_at, quota_started_at, "
                    "access_granted_until, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        item_id,
                        source.site,
                        source.external_id,
                        source.discovery_key,
                        source.url,
                        source.access_mode,
                        format_timestamp(source.free_until),
                        1 if source.available is None else int(source.available),
                        format_timestamp(source.access_checked_at),
                        last_seen,
                        format_timestamp(source.quota_started_at),
                        format_timestamp(source.access_granted_until),
                        timestamp,
                        timestamp,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise CatalogValidationError(f"Could not create source: {exc}") from exc
            row = connection.execute(
                "SELECT * FROM sources WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return self._source_from_row(row)

    def find_source(self, site: str, external_id: str) -> Source | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM sources WHERE site = ? AND external_id = ?",
                (site, external_id),
            ).fetchone()
        return None if row is None else self._source_from_row(row)

    find_source_by_external_id = find_source
    find_source_by_identity = find_source

    def get_source_by_external_id(self, site: str, external_id: str) -> Source:
        source = self.find_source(site, external_id)
        if source is None:
            raise CatalogNotFoundError(f"Catalog source not found: ({site}, {external_id})")
        return source

    def get_source(self, source_id: int) -> Source:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        if row is None:
            raise CatalogNotFoundError(f"Catalog source not found: {source_id}")
        return self._source_from_row(row)

    def list_sources(
        self, *, item_id: int | None = None, site: str | None = None
    ) -> list[Source]:
        conditions: list[str] = []
        values: list[Any] = []
        if item_id is not None:
            conditions.append("item_id = ?")
            values.append(item_id)
        if site is not None:
            conditions.append("site = ?")
            values.append(site)
        query = "SELECT * FROM sources"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY id"
        with self._connection() as connection:
            rows = connection.execute(query, values).fetchall()
        return [self._source_from_row(row) for row in rows]

    def upsert_item_source(
        self,
        item: ItemInput | Mapping[str, Any],
        source: SourceInput | Mapping[str, Any],
    ) -> CatalogRecord:
        """Atomically create or refresh an item/source pair.

        Source identity is exclusively ``(site, external_id)``. On an existing
        source, only external state and observed item metadata are updated;
        local item state is deliberately left untouched.
        """

        item_input = self._coerce_item_input(item)
        source_input = self._coerce_source_input(source)
        self._validate_source_input(source_input)
        self._validate_status(item_input.status)
        timestamp = format_timestamp(now_jst())
        last_seen = format_timestamp(source_input.last_seen_at) or timestamp

        with self._connection() as connection:
            existing = connection.execute(
                "SELECT * FROM sources WHERE site = ? AND external_id = ?",
                (source_input.site, source_input.external_id),
            ).fetchone()
            if existing is None:
                item_cursor = connection.execute(
                    "INSERT INTO items (canonical_title, author, genre, kind, order_key, order_label, "
                    "status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        item_input.canonical_title,
                        item_input.author,
                        item_input.genre,
                        item_input.kind,
                        item_input.order_key,
                        item_input.order_label,
                        item_input.status,
                        timestamp,
                        timestamp,
                    ),
                )
                item_id = int(item_cursor.lastrowid)
                connection.execute(
                    "INSERT INTO sources (item_id, site, external_id, discovery_key, url, access_mode, "
                    "free_until, available, access_checked_at, last_seen_at, quota_started_at, "
                    "access_granted_until, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        item_id,
                        source_input.site,
                        source_input.external_id,
                        source_input.discovery_key,
                        source_input.url,
                        source_input.access_mode,
                        format_timestamp(source_input.free_until),
                        1 if source_input.available is None else int(source_input.available),
                        format_timestamp(source_input.access_checked_at),
                        last_seen,
                        None,
                        None,
                        timestamp,
                        timestamp,
                    ),
                )
                source_row = connection.execute(
                    "SELECT * FROM sources WHERE site = ? AND external_id = ?",
                    (source_input.site, source_input.external_id),
                ).fetchone()
            else:
                item_id = int(existing["item_id"])
                self._update_item_metadata(connection, item_id, item_input, timestamp)
                self._update_source_external_state(
                    connection,
                    existing,
                    source_input,
                    timestamp=timestamp,
                    default_last_seen=last_seen,
                )
                source_row = connection.execute(
                    "SELECT * FROM sources WHERE id = ?", (existing["id"],)
                ).fetchone()
            item_row = connection.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return CatalogRecord(
            item=self._item_from_row(item_row), source=self._source_from_row(source_row)
        )

    upsert = upsert_item_source
    upsert_item_and_source = upsert_item_source

    def update_source_external_state(
        self,
        site: str,
        external_id: str,
        *,
        url: str | object = _UNSET,
        discovery_key: str | None | object = _UNSET,
        access_mode: str | object = _UNSET,
        free_until: datetime | str | None | object = _UNSET,
        available: bool | object = _UNSET,
        access_checked_at: datetime | str | None | object = _UNSET,
        last_seen_at: datetime | str | None | object = _UNSET,
        metadata: Mapping[str, Any] | None = None,
    ) -> Source:
        """Patch external source state while preserving the associated item."""

        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM sources WHERE site = ? AND external_id = ?",
                (site, external_id),
            ).fetchone()
            if row is None:
                raise CatalogNotFoundError(f"Catalog source not found: ({site}, {external_id})")
            assignments: list[str] = []
            values: list[Any] = []
            for column, value in (
                ("url", url),
                ("discovery_key", discovery_key),
                ("access_mode", access_mode),
                ("free_until", free_until),
                ("available", available),
                ("access_checked_at", access_checked_at),
                ("last_seen_at", last_seen_at),
            ):
                if value is _UNSET:
                    continue
                if column == "available":
                    if not isinstance(value, bool):
                        raise CatalogValidationError("available must be a boolean")
                    value = int(value)
                elif column == "access_mode":
                    self._validate_access_mode(value)
                elif column == "url":
                    self._validate_nonempty(value, "url")
                elif column.endswith("_at") or column == "free_until":
                    value = format_timestamp(value)
                assignments.append(f"{column} = ?")
                values.append(value)
            if metadata:
                self._update_item_metadata_mapping(
                    connection, int(row["item_id"]), metadata, format_timestamp(now_jst())
                )
            if assignments:
                assignments.append("updated_at = ?")
                values.extend([format_timestamp(now_jst()), site, external_id])
                connection.execute(
                    "UPDATE sources SET "
                    + ", ".join(assignments)
                    + " WHERE site = ? AND external_id = ?",
                    values,
                )
            updated = connection.execute(
                "SELECT * FROM sources WHERE site = ? AND external_id = ?", (site, external_id)
            ).fetchone()
        return self._source_from_row(updated)

    def mark_item_completed(
        self, item_id: int, local_path: str, *, completed_at: datetime | str | None = None
    ) -> Item:
        self._validate_nonempty(local_path, "local_path")
        finished = format_timestamp(completed_at) or format_timestamp(now_jst())
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE items SET status = 'completed', local_path = ?, completed_at = ?, "
                "updated_at = ? WHERE id = ?",
                (local_path, finished, format_timestamp(now_jst()), item_id),
            )
            if cursor.rowcount == 0:
                raise CatalogNotFoundError(f"Catalog item not found: {item_id}")
            row = connection.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return self._item_from_row(row)

    @contextmanager
    def _connection(self, *, initialize_schema: bool = True):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            if initialize_schema:
                try:
                    schema.initialize(connection)
                except schema.SchemaError as exc:
                    raise self._schema_error(exc) from exc
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        finally:
            connection.close()

    @staticmethod
    def _schema_error(exc: schema.SchemaError) -> CatalogError:
        if "Unsupported Catalog schema version" in str(exc):
            return UnsupportedSchemaVersionError(str(exc))
        return CatalogError(str(exc))

    @staticmethod
    def _validate_nonempty(value: Any, field: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise CatalogValidationError(f"{field} must be a non-empty string")

    @classmethod
    def _validate_status(cls, value: Any) -> None:
        if value not in {"pending", "completed"}:
            raise CatalogValidationError("status must be 'pending' or 'completed'")

    @classmethod
    def _validate_access_mode(cls, value: Any) -> None:
        if value not in {"owned", "free", "quota", "paid", "unknown"}:
            raise CatalogValidationError(
                "access_mode must be one of owned, free, quota, paid, unknown"
            )

    @classmethod
    def _validate_source_input(cls, source: SourceInput) -> None:
        cls._validate_nonempty(source.site, "site")
        cls._validate_nonempty(source.external_id, "external_id")
        cls._validate_nonempty(source.url, "url")
        cls._validate_access_mode(source.access_mode)
        if source.available is not None and not isinstance(source.available, bool):
            raise CatalogValidationError("available must be a boolean")
        for value in (
            source.free_until,
            source.access_checked_at,
            source.last_seen_at,
            source.quota_started_at,
            source.access_granted_until,
        ):
            format_timestamp(value)

    @staticmethod
    def _coerce_item_input(
        item: ItemInput | Mapping[str, Any] | None,
        fields: Mapping[str, Any] | None = None,
    ) -> ItemInput:
        values: dict[str, Any] = {}
        if item is not None:
            if isinstance(item, ItemInput):
                values.update({name: getattr(item, name) for name in ItemInput.__dataclass_fields__})
            elif isinstance(item, Mapping):
                values.update(item)
            else:
                raise CatalogValidationError("item must be ItemInput or a mapping")
        if fields:
            values.update(fields)
        allowed = set(ItemInput.__dataclass_fields__)
        unknown = set(values) - allowed
        if unknown:
            raise CatalogValidationError(f"Unknown item field(s): {', '.join(sorted(unknown))}")
        return ItemInput(**values)

    @staticmethod
    def _coerce_source_input(source: SourceInput | Mapping[str, Any]) -> SourceInput:
        if isinstance(source, SourceInput):
            return source
        if not isinstance(source, Mapping):
            raise CatalogValidationError("source must be SourceInput or a mapping")
        allowed = set(SourceInput.__dataclass_fields__)
        unknown = set(source) - allowed
        if unknown:
            raise CatalogValidationError(f"Unknown source field(s): {', '.join(sorted(unknown))}")
        try:
            return SourceInput(**source)
        except TypeError as exc:
            raise CatalogValidationError(str(exc)) from exc

    @staticmethod
    def _update_item_metadata(
        connection: sqlite3.Connection, item_id: int, item: ItemInput, timestamp: str
    ) -> None:
        CatalogService._update_item_metadata_mapping(
            connection,
            item_id,
            {
                "canonical_title": item.canonical_title,
                "author": item.author,
                "genre": item.genre,
                "kind": item.kind,
                "order_key": item.order_key,
                "order_label": item.order_label,
            },
            timestamp,
        )

    @staticmethod
    def _update_item_metadata_mapping(
        connection: sqlite3.Connection,
        item_id: int,
        metadata: Mapping[str, Any],
        timestamp: str,
    ) -> None:
        allowed = {"canonical_title", "author", "genre", "kind", "order_key", "order_label"}
        changed = [field for field in metadata if field in allowed and metadata[field] is not None]
        if not changed:
            return
        assignments = [f"{field} = ?" for field in changed]
        values = [metadata[field] for field in changed]
        assignments.append("updated_at = ?")
        values.extend([timestamp, item_id])
        connection.execute(
            "UPDATE items SET " + ", ".join(assignments) + " WHERE id = ?", values
        )

    @staticmethod
    def _update_source_external_state(
        connection: sqlite3.Connection,
        existing: sqlite3.Row,
        source: SourceInput,
        *,
        timestamp: str,
        default_last_seen: str,
    ) -> None:
        connection.execute(
            "UPDATE sources SET discovery_key = ?, url = ?, access_mode = ?, free_until = ?, "
            "available = ?, access_checked_at = ?, last_seen_at = ?, updated_at = ? WHERE id = ?",
            (
                source.discovery_key,
                source.url,
                source.access_mode,
                format_timestamp(source.free_until),
                int(source.available) if source.available is not None else existing["available"],
                format_timestamp(source.access_checked_at),
                default_last_seen,
                timestamp,
                existing["id"],
            ),
        )

    @staticmethod
    def _item_from_row(row: sqlite3.Row) -> Item:
        return Item(**dict(row))

    @staticmethod
    def _source_from_row(row: sqlite3.Row) -> Source:
        values = dict(row)
        values["available"] = bool(values["available"])
        return Source(**values)
