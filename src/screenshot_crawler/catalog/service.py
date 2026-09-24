"""Catalog v5 SQLite service."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Collection, Mapping
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from screenshot_crawler.catalog import schema
from screenshot_crawler.catalog.models import (
    Artifact,
    ArtifactInput,
    CatalogRecord,
    CrawlRun,
    Item,
    ItemInput,
    QuotaResourceState,
    Source,
    SourceInput,
    SourceTarget,
    SourceTargetInput,
    Work,
    WorkInput,
)

JST = timezone(timedelta(hours=9), name="JST")
_UNSET = object()
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


class CatalogError(RuntimeError):
    """Base error for Catalog operations."""


class CatalogValidationError(CatalogError, ValueError):
    """Raised when Catalog input is invalid."""


class CatalogNotFoundError(CatalogError):
    """Raised when a requested Catalog row does not exist."""


class UnsupportedSchemaVersionError(CatalogError):
    """Raised when a database uses a schema version this code cannot handle."""


def now_jst() -> datetime:
    return datetime.now(JST)


def format_timestamp(value: datetime | str | None) -> str | None:
    """Normalize an aware datetime or ISO timestamp to JST."""

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
    """Connection-per-operation Catalog service with foreign keys enabled."""

    def __init__(self, path: str | Path = "catalog.sqlite") -> None:
        self.path = Path(path)

    def initialize(self) -> None:
        with self._connection(initialize_schema=False) as connection:
            try:
                schema.initialize(connection)
            except schema.SchemaError as exc:
                raise self._schema_error(exc) from exc

    def schema_version(self) -> int:
        if not self.path.exists():
            return 0
        with self._connection(initialize_schema=False) as connection:
            return schema.user_version(connection)

    # Work API ---------------------------------------------------------

    def create_work(self, work: WorkInput | Mapping[str, Any] | None = None, **fields: Any) -> Work:
        work_input = self._coerce_work_input(work, fields)
        self._validate_work_input(work_input)
        timestamp = format_timestamp(now_jst())
        with self._connection() as connection:
            try:
                cursor = connection.execute(
                    "INSERT INTO works (work_key, title, author, genre, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (work_input.work_key, work_input.title, work_input.author, work_input.genre,
                     timestamp, timestamp),
                )
            except sqlite3.IntegrityError as exc:
                raise CatalogValidationError(f"Could not create work: {exc}") from exc
            row = connection.execute("SELECT * FROM works WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return self._work_from_row(row)

    def upsert_work(self, work: WorkInput | Mapping[str, Any], **fields: Any) -> Work:
        work_input = self._coerce_work_input(work, fields)
        self._validate_work_input(work_input)
        timestamp = format_timestamp(now_jst())
        with self._connection() as connection:
            existing = connection.execute(
                "SELECT id FROM works WHERE work_key = ?", (work_input.work_key,)
            ).fetchone()
            if existing is None:
                cursor = connection.execute(
                    "INSERT INTO works (work_key, title, author, genre, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (work_input.work_key, work_input.title, work_input.author, work_input.genre,
                     timestamp, timestamp),
                )
                work_id = cursor.lastrowid
            else:
                work_id = existing["id"]
                connection.execute(
                    "UPDATE works SET title = ?, author = ?, genre = ?, updated_at = ? WHERE id = ?",
                    (work_input.title, work_input.author, work_input.genre, timestamp, work_id),
                )
            row = connection.execute("SELECT * FROM works WHERE id = ?", (work_id,)).fetchone()
        return self._work_from_row(row)

    def get_work(self, work_id: int) -> Work:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM works WHERE id = ?", (work_id,)).fetchone()
        if row is None:
            raise CatalogNotFoundError(f"Catalog work not found: {work_id}")
        return self._work_from_row(row)

    def find_work(self, work_key: str) -> Work | None:
        self._validate_nonempty(work_key, "work_key")
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM works WHERE work_key = ?", (work_key,)).fetchone()
        return None if row is None else self._work_from_row(row)

    def list_works(self) -> list[Work]:
        with self._connection() as connection:
            rows = connection.execute("SELECT * FROM works ORDER BY id").fetchall()
        return [self._work_from_row(row) for row in rows]

    def fill_work_metadata(
        self,
        work_id: int,
        *,
        author: str | None = None,
        genre: str | None = None,
    ) -> Work:
        """Fill only currently-null Work metadata from non-null observations."""

        self._validate_optional_text(author, "author")
        self._validate_optional_text(genre, "genre")
        with self._connection() as connection:
            row = self._require_row(connection, "works", work_id, "work")
            assignments: list[str] = []
            values: list[Any] = []
            for column, incoming in (("author", author), ("genre", genre)):
                if incoming is not None and row[column] is None:
                    assignments.append(f"{column} = ?")
                    values.append(incoming)
            if assignments:
                assignments.append("updated_at = ?")
                values.extend([format_timestamp(now_jst()), work_id])
                connection.execute(
                    "UPDATE works SET " + ", ".join(assignments) + " WHERE id = ?", values
                )
            updated = connection.execute("SELECT * FROM works WHERE id = ?", (work_id,)).fetchone()
        return self._work_from_row(updated)

    # Item API ---------------------------------------------------------

    def create_item(
        self,
        item: ItemInput | Mapping[str, Any] | None = None,
        *,
        work_id: int | None = None,
        **fields: Any,
    ) -> Item:
        item_input = self._coerce_item_input(item, fields)
        self._validate_status(item_input.status)
        if work_id is None:
            raise CatalogValidationError("work_id is required")
        timestamp = format_timestamp(now_jst())
        with self._connection() as connection:
            self._require_row(connection, "works", work_id, "work")
            cursor = connection.execute(
                "INSERT INTO items (work_id, item_title, kind, order_key, order_label, status, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (work_id, item_input.item_title, item_input.kind, item_input.order_key,
                 item_input.order_label, item_input.status, timestamp, timestamp),
            )
            row = connection.execute("SELECT * FROM items WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return self._item_from_row(row)

    def get_item(self, item_id: int) -> Item:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise CatalogNotFoundError(f"Catalog item not found: {item_id}")
        return self._item_from_row(row)

    def list_items(self, *, work_id: int | None = None, status: str | None = None) -> list[Item]:
        if status is not None:
            self._validate_status(status)
        conditions: list[str] = []
        values: list[Any] = []
        if work_id is not None:
            conditions.append("work_id = ?")
            values.append(work_id)
        if status is not None:
            conditions.append("status = ?")
            values.append(status)
        query = "SELECT * FROM items"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY id"
        with self._connection() as connection:
            rows = connection.execute(query, values).fetchall()
        return [self._item_from_row(row) for row in rows]

    def mark_item_completed(
        self, item_id: int, *, completed_at: datetime | str | None = None
    ) -> Item:
        finished = format_timestamp(completed_at) or format_timestamp(now_jst())
        timestamp = format_timestamp(now_jst())
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE items SET status = 'completed', completed_at = ?, updated_at = ? WHERE id = ?",
                (finished, timestamp, item_id),
            )
            if cursor.rowcount == 0:
                raise CatalogNotFoundError(f"Catalog item not found: {item_id}")
            row = connection.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return self._item_from_row(row)

    def update_item_metadata(
        self,
        item_id: int,
        *,
        item_title: str | None = None,
        kind: str | None = None,
        order_key: str | None = None,
        order_label: str | None = None,
    ) -> Item:
        """Patch observed Item metadata without clearing values with NULL."""

        for field, value in (
            ("item_title", item_title),
            ("kind", kind),
            ("order_key", order_key),
            ("order_label", order_label),
        ):
            self._validate_optional_text(value, field)
        with self._connection() as connection:
            self._require_row(connection, "items", item_id, "item")
            assignments: list[str] = []
            values: list[Any] = []
            for column, incoming in (
                ("item_title", item_title),
                ("kind", kind),
                ("order_key", order_key),
                ("order_label", order_label),
            ):
                if incoming is not None:
                    assignments.append(f"{column} = ?")
                    values.append(incoming)
            if assignments:
                assignments.append("updated_at = ?")
                values.extend([format_timestamp(now_jst()), item_id])
                connection.execute(
                    "UPDATE items SET " + ", ".join(assignments) + " WHERE id = ?", values
                )
            updated = connection.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return self._item_from_row(updated)

    # Source API -------------------------------------------------------

    def create_source(
        self, source: SourceInput | Mapping[str, Any], *, item_id: int
    ) -> Source:
        source_input = self._coerce_source_input(source)
        self._validate_source_input(source_input)
        timestamp = format_timestamp(now_jst())
        last_seen = format_timestamp(source_input.last_seen_at) or timestamp
        with self._connection() as connection:
            self._require_row(connection, "items", item_id, "item")
            try:
                cursor = connection.execute(
                    "INSERT INTO sources (item_id, site, external_id, discovery_key, access_mode, "
                    "free_until, available, access_checked_at, last_seen_at, quota_started_at, "
                    "access_granted_until, published_at, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (item_id, source_input.site, source_input.external_id, source_input.discovery_key,
                     source_input.access_mode, format_timestamp(source_input.free_until),
                     1 if source_input.available is None else int(source_input.available),
                     format_timestamp(source_input.access_checked_at), last_seen,
                     format_timestamp(source_input.quota_started_at),
                     format_timestamp(source_input.access_granted_until),
                     format_timestamp(source_input.published_at), timestamp, timestamp),
                )
            except sqlite3.IntegrityError as exc:
                raise CatalogValidationError(f"Could not create source: {exc}") from exc
            row = connection.execute("SELECT * FROM sources WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return self._source_from_row(row)

    def find_source(self, site: str, external_id: str) -> Source | None:
        self._validate_nonempty(site, "site")
        self._validate_nonempty(external_id, "external_id")
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM sources WHERE site = ? AND external_id = ?", (site, external_id)
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
        self, *, item_id: int | None = None, site: str | None = None,
        discovery_key: str | None = None,
    ) -> list[Source]:
        conditions: list[str] = []
        values: list[Any] = []
        if item_id is not None:
            conditions.append("item_id = ?")
            values.append(item_id)
        if site is not None:
            self._validate_nonempty(site, "site")
            conditions.append("site = ?")
            values.append(site)
        if discovery_key is not None:
            conditions.append("discovery_key = ?")
            values.append(discovery_key)
        query = "SELECT * FROM sources"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY id"
        with self._connection() as connection:
            rows = connection.execute(query, values).fetchall()
        return [self._source_from_row(row) for row in rows]

    def update_source_external_state(
        self,
        site: str,
        external_id: str,
        *,
        discovery_key: str | None | object = _UNSET,
        access_mode: str | object = _UNSET,
        free_until: datetime | str | None | object = _UNSET,
        available: bool | object = _UNSET,
        access_checked_at: datetime | str | None | object = _UNSET,
        last_seen_at: datetime | str | None | object = _UNSET,
        published_at: datetime | str | None | object = _UNSET,
    ) -> Source:
        self._validate_nonempty(site, "site")
        self._validate_nonempty(external_id, "external_id")
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM sources WHERE site = ? AND external_id = ?", (site, external_id)
            ).fetchone()
            if row is None:
                raise CatalogNotFoundError(f"Catalog source not found: ({site}, {external_id})")
            assignments: list[str] = []
            values: list[Any] = []
            for column, value in (
                ("discovery_key", discovery_key), ("access_mode", access_mode),
                ("free_until", free_until), ("available", available),
                ("access_checked_at", access_checked_at), ("last_seen_at", last_seen_at),
                ("published_at", published_at),
            ):
                if value is _UNSET:
                    continue
                if column == "access_mode":
                    self._validate_access_mode(value)
                elif column == "available":
                    if not isinstance(value, bool):
                        raise CatalogValidationError("available must be a boolean")
                    value = int(value)
                elif column in {"free_until", "access_checked_at", "last_seen_at", "published_at"}:
                    value = format_timestamp(value)
                assignments.append(f"{column} = ?")
                values.append(value)
            if assignments:
                assignments.append("updated_at = ?")
                values.extend([format_timestamp(now_jst()), site, external_id])
                connection.execute(
                    "UPDATE sources SET " + ", ".join(assignments) +
                    " WHERE site = ? AND external_id = ?", values
                )
            updated = connection.execute(
                "SELECT * FROM sources WHERE site = ? AND external_id = ?", (site, external_id)
            ).fetchone()
        return self._source_from_row(updated)

    def record_quota_access(
        self,
        source_id: int,
        *,
        quota_started_at: datetime | str,
        access_granted_until: datetime | str | None,
    ) -> Source:
        started = format_timestamp(quota_started_at)
        if started is None:
            raise CatalogValidationError("quota_started_at is required")
        granted_until = format_timestamp(access_granted_until)
        with self._connection() as connection:
            self._require_row(connection, "sources", source_id, "source")
            connection.execute(
                "UPDATE sources SET quota_started_at = ?, access_granted_until = ?, updated_at = ? "
                "WHERE id = ?", (started, granted_until, format_timestamp(now_jst()), source_id)
            )
            row = connection.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        return self._source_from_row(row)

    def get_quota_resource_state(
        self, work_id: int, *, site: str, resource: str
    ) -> QuotaResourceState | None:
        """Return the last confirmed consumption for one Work/resource pair."""

        self._validate_nonempty(site, "site")
        self._validate_nonempty(resource, "resource")
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM quota_resource_states "
                "WHERE work_id = ? AND site = ? AND resource = ?",
                (work_id, site, resource),
            ).fetchone()
        return None if row is None else self._quota_resource_state_from_row(row)

    def record_quota_access_with_resource_state(
        self,
        source_id: int,
        *,
        work_id: int,
        site: str,
        resource: str,
        consumed_at: datetime | str,
        access_granted_until: datetime | str | None,
    ) -> tuple[Source, QuotaResourceState]:
        """Atomically persist source grant and confirmed Work resource use."""

        self._validate_nonempty(site, "site")
        self._validate_nonempty(resource, "resource")
        consumed = format_timestamp(consumed_at)
        if consumed is None:
            raise CatalogValidationError("consumed_at is required")
        granted_until = format_timestamp(access_granted_until)
        timestamp = format_timestamp(now_jst())
        with self._connection() as connection:
            source = self._require_row(connection, "sources", source_id, "source")
            item = self._require_row(connection, "items", source["item_id"], "item")
            if source["site"] != site:
                raise CatalogValidationError("source.site does not match site")
            if item["work_id"] != work_id:
                raise CatalogValidationError("source item does not belong to work_id")
            existing_state = connection.execute(
                "SELECT * FROM quota_resource_states "
                "WHERE work_id = ? AND site = ? AND resource = ?",
                (work_id, site, resource),
            ).fetchone()
            if existing_state is not None:
                existing_consumed = datetime.fromisoformat(
                    existing_state["last_consumed_at"]
                )
                observed_consumed = datetime.fromisoformat(consumed)
                if existing_consumed > observed_consumed:
                    source_row = connection.execute(
                        "SELECT * FROM sources WHERE id = ?", (source_id,)
                    ).fetchone()
                    return (
                        self._source_from_row(source_row),
                        self._quota_resource_state_from_row(existing_state),
                    )
            connection.execute(
                "UPDATE sources SET quota_started_at = ?, access_granted_until = ?, "
                "updated_at = ? WHERE id = ?",
                (consumed, granted_until, timestamp, source_id),
            )
            connection.execute(
                "INSERT INTO quota_resource_states "
                "(work_id, site, resource, last_consumed_at, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(work_id, site, resource) DO UPDATE SET "
                "last_consumed_at = excluded.last_consumed_at, updated_at = excluded.updated_at",
                (work_id, site, resource, consumed, timestamp, timestamp),
            )
            source_row = connection.execute(
                "SELECT * FROM sources WHERE id = ?", (source_id,)
            ).fetchone()
            state_row = connection.execute(
                "SELECT * FROM quota_resource_states "
                "WHERE work_id = ? AND site = ? AND resource = ?",
                (work_id, site, resource),
            ).fetchone()
        return self._source_from_row(source_row), self._quota_resource_state_from_row(state_row)

    def clear_quota_access(
        self,
        source_id: int,
        *,
        expected_quota_started_at: datetime | str,
    ) -> Source:
        """Clear one recorded quota reservation after an explicit repair.

        The expected timestamp makes the repair compare-and-set style: a
        concurrent or newer quota reservation is never silently cleared.
        ``access_mode`` and all crawl history remain unchanged.
        """

        expected = format_timestamp(expected_quota_started_at)
        if expected is None:
            raise CatalogValidationError("expected_quota_started_at is required")
        with self._connection() as connection:
            self._require_row(connection, "sources", source_id, "source")
            cursor = connection.execute(
                "UPDATE sources SET quota_started_at = NULL, access_granted_until = NULL, "
                "updated_at = ? WHERE id = ? AND quota_started_at = ?",
                (format_timestamp(now_jst()), source_id, expected),
            )
            if cursor.rowcount != 1:
                raise CatalogValidationError(
                    "Quota reservation changed or is already clear; refusing to overwrite it"
                )
            row = connection.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        return self._source_from_row(row)

    def mark_sources_unavailable_except(
        self, *, site: str, discovery_key: str, observed_external_ids: Collection[str]
    ) -> int:
        self._validate_nonempty(site, "site")
        self._validate_nonempty(discovery_key, "discovery_key")
        observed = tuple(dict.fromkeys(observed_external_ids))
        timestamp = format_timestamp(now_jst())
        with self._connection() as connection:
            where = "site = ? AND discovery_key = ? AND available = 1"
            values: list[Any] = [site, discovery_key]
            if observed:
                placeholders = ", ".join("?" for _ in observed)
                where += f" AND external_id NOT IN ({placeholders})"
                values.extend(observed)
            cursor = connection.execute(
                f"UPDATE sources SET available = 0, updated_at = ? WHERE {where}",
                [timestamp, *values],
            )
        return cursor.rowcount

    def create_discovered_item_source_target(
        self,
        *,
        work_id: int,
        item_input: ItemInput | Mapping[str, Any],
        source_input: SourceInput | Mapping[str, Any],
        web_target_input: SourceTargetInput | Mapping[str, Any],
    ) -> CatalogRecord:
        """Atomically create a new Discovery Item, Source, and Target graph."""

        item = self._coerce_item_input(item_input)
        source = self._coerce_source_input(source_input)
        target = self._coerce_source_target_input(web_target_input)
        self._validate_status(item.status)
        self._validate_source_input(source)
        self._validate_source_target_input(target)
        timestamp = format_timestamp(now_jst())
        last_seen = format_timestamp(source.last_seen_at) or timestamp
        with self._connection() as connection:
            self._require_row(connection, "works", work_id, "work")
            try:
                item_cursor = connection.execute(
                    "INSERT INTO items (work_id, item_title, kind, order_key, order_label, status, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (work_id, item.item_title, item.kind, item.order_key, item.order_label,
                     item.status, timestamp, timestamp),
                )
                item_id = item_cursor.lastrowid
                source_cursor = connection.execute(
                    "INSERT INTO sources (item_id, site, external_id, discovery_key, access_mode, "
                    "free_until, available, access_checked_at, last_seen_at, quota_started_at, "
                    "access_granted_until, published_at, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (item_id, source.site, source.external_id, source.discovery_key,
                     source.access_mode, format_timestamp(source.free_until),
                     1 if source.available is None else int(source.available),
                     format_timestamp(source.access_checked_at), last_seen, None,
                     format_timestamp(source.access_granted_until),
                     format_timestamp(source.published_at),
                     timestamp, timestamp),
                )
                source_id = source_cursor.lastrowid
                target_cursor = connection.execute(
                    "INSERT INTO source_targets (source_id, backend, target_key, locator, priority, "
                    "enabled, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (source_id, target.backend, target.target_key, target.locator, target.priority,
                     int(target.enabled), timestamp, timestamp),
                )
            except sqlite3.IntegrityError as exc:
                raise CatalogValidationError(
                    f"Could not create discovered item/source/target: {exc}"
                ) from exc
            item_row = connection.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
            source_row = connection.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
            target_row = connection.execute(
                "SELECT * FROM source_targets WHERE id = ?", (target_cursor.lastrowid,)
            ).fetchone()
        return CatalogRecord(
            item=self._item_from_row(item_row),
            source=self._source_from_row(source_row),
            target=self._source_target_from_row(target_row),
        )

    def refresh_discovered_source(
        self,
        *,
        work_id: int,
        source_id: int,
        item_input: ItemInput | Mapping[str, Any],
        source_input: SourceInput | Mapping[str, Any],
        web_target_input: SourceTargetInput | Mapping[str, Any],
        access_granted_until_observed: bool = False,
    ) -> CatalogRecord:
        """Atomically refresh an existing Discovery graph without local-state writes."""

        item = self._coerce_item_input(item_input)
        source = self._coerce_source_input(source_input)
        target = self._coerce_source_target_input(web_target_input)
        self._validate_status(item.status)
        self._validate_source_input(source)
        self._validate_source_target_input(target)
        timestamp = format_timestamp(now_jst())
        with self._connection() as connection:
            existing_source = self._require_row(connection, "sources", source_id, "source")
            existing_item = self._require_row(connection, "items", existing_source["item_id"], "item")
            if existing_item["work_id"] != work_id:
                raise CatalogValidationError("existing source belongs to a different work")
            if existing_source["site"] != source.site or existing_source["external_id"] != source.external_id:
                raise CatalogValidationError("source identity cannot be changed")
            existing_key = existing_source["discovery_key"]
            if existing_key is not None and existing_key != source.discovery_key:
                raise CatalogValidationError("source belongs to a different Discovery scope")
            assignments = [
                "discovery_key = ?",
                "access_mode = ?",
                "free_until = ?",
                "access_checked_at = ?",
                "last_seen_at = ?",
                "updated_at = ?",
            ]
            values: list[Any] = [
                source.discovery_key,
                source.access_mode,
                format_timestamp(source.free_until),
                format_timestamp(source.access_checked_at),
                format_timestamp(source.last_seen_at) or timestamp,
                timestamp,
                source_id,
            ]
            if source.available is not None:
                assignments.insert(3, "available = ?")
                values.insert(3, int(source.available))
            if source.access_granted_until is not None or access_granted_until_observed:
                assignments.insert(-1, "access_granted_until = ?")
                values.insert(-2, format_timestamp(source.access_granted_until))
            if source.published_at is not None:
                assignments.insert(-1, "published_at = ?")
                values.insert(-2, format_timestamp(source.published_at))
            connection.execute(
                "UPDATE sources SET " + ", ".join(assignments) + " WHERE id = ?", values
            )
            for column, incoming in (
                ("item_title", item.item_title),
                ("kind", item.kind),
                ("order_key", item.order_key),
                ("order_label", item.order_label),
            ):
                if incoming is not None:
                    connection.execute(
                        f"UPDATE items SET {column} = ?, updated_at = ? WHERE id = ?",
                        (incoming, timestamp, existing_item["id"]),
                    )
            existing_target = connection.execute(
                "SELECT id FROM source_targets WHERE source_id = ? AND backend = ? AND target_key = ?",
                (source_id, target.backend, target.target_key),
            ).fetchone()
            if existing_target is None:
                target_cursor = connection.execute(
                    "INSERT INTO source_targets (source_id, backend, target_key, locator, priority, "
                    "enabled, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (source_id, target.backend, target.target_key, target.locator, target.priority,
                     int(target.enabled), timestamp, timestamp),
                )
                target_id = target_cursor.lastrowid
            else:
                target_id = existing_target["id"]
                connection.execute(
                    "UPDATE source_targets SET locator = ?, priority = ?, enabled = ?, updated_at = ? "
                    "WHERE id = ?",
                    (target.locator, target.priority, int(target.enabled), timestamp, target_id),
                )
            item_row = connection.execute("SELECT * FROM items WHERE id = ?", (existing_item["id"],)).fetchone()
            source_row = connection.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
            target_row = connection.execute("SELECT * FROM source_targets WHERE id = ?", (target_id,)).fetchone()
        return CatalogRecord(
            item=self._item_from_row(item_row),
            source=self._source_from_row(source_row),
            target=self._source_target_from_row(target_row),
        )

    # SourceTarget API -------------------------------------------------

    def create_source_target(
        self, target: SourceTargetInput | Mapping[str, Any], *, source_id: int
    ) -> SourceTarget:
        target_input = self._coerce_source_target_input(target)
        self._validate_source_target_input(target_input)
        timestamp = format_timestamp(now_jst())
        with self._connection() as connection:
            self._require_row(connection, "sources", source_id, "source")
            try:
                cursor = connection.execute(
                    "INSERT INTO source_targets (source_id, backend, target_key, locator, priority, "
                    "enabled, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (source_id, target_input.backend, target_input.target_key, target_input.locator,
                     target_input.priority, int(target_input.enabled), timestamp, timestamp),
                )
            except sqlite3.IntegrityError as exc:
                raise CatalogValidationError(f"Could not create source target: {exc}") from exc
            row = connection.execute(
                "SELECT * FROM source_targets WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return self._source_target_from_row(row)

    def upsert_source_target(
        self, target: SourceTargetInput | Mapping[str, Any], *, source_id: int
    ) -> SourceTarget:
        target_input = self._coerce_source_target_input(target)
        self._validate_source_target_input(target_input)
        timestamp = format_timestamp(now_jst())
        with self._connection() as connection:
            self._require_row(connection, "sources", source_id, "source")
            existing = connection.execute(
                "SELECT id FROM source_targets WHERE source_id = ? AND backend = ? AND target_key = ?",
                (source_id, target_input.backend, target_input.target_key),
            ).fetchone()
            if existing is None:
                cursor = connection.execute(
                    "INSERT INTO source_targets (source_id, backend, target_key, locator, priority, "
                    "enabled, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (source_id, target_input.backend, target_input.target_key, target_input.locator,
                     target_input.priority, int(target_input.enabled), timestamp, timestamp),
                )
                target_id = cursor.lastrowid
            else:
                target_id = existing["id"]
                connection.execute(
                    "UPDATE source_targets SET locator = ?, priority = ?, enabled = ?, updated_at = ? "
                    "WHERE id = ?", (target_input.locator, target_input.priority,
                                      int(target_input.enabled), timestamp, target_id)
                )
            row = connection.execute(
                "SELECT * FROM source_targets WHERE id = ?", (target_id,)
            ).fetchone()
        return self._source_target_from_row(row)

    def find_source_target(
        self, source_id: int, backend: str, target_key: str = "default"
    ) -> SourceTarget | None:
        self._validate_nonempty(backend, "backend")
        self._validate_nonempty(target_key, "target_key")
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM source_targets WHERE source_id = ? AND backend = ? AND target_key = ?",
                (source_id, backend, target_key),
            ).fetchone()
        return None if row is None else self._source_target_from_row(row)

    def get_source_target(self, target_id: int) -> SourceTarget:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM source_targets WHERE id = ?", (target_id,)).fetchone()
        if row is None:
            raise CatalogNotFoundError(f"Catalog source target not found: {target_id}")
        return self._source_target_from_row(row)

    def list_source_targets(
        self, *, source_id: int | None = None, backend: str | None = None,
        target_key: str | None = None, enabled: bool | None = None,
    ) -> list[SourceTarget]:
        conditions: list[str] = []
        values: list[Any] = []
        if source_id is not None:
            conditions.append("source_id = ?")
            values.append(source_id)
        if backend is not None:
            self._validate_nonempty(backend, "backend")
            conditions.append("backend = ?")
            values.append(backend)
        if target_key is not None:
            self._validate_nonempty(target_key, "target_key")
            conditions.append("target_key = ?")
            values.append(target_key)
        if enabled is not None:
            if not isinstance(enabled, bool):
                raise CatalogValidationError("enabled must be a boolean")
            conditions.append("enabled = ?")
            values.append(int(enabled))
        query = "SELECT * FROM source_targets"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY id"
        with self._connection() as connection:
            rows = connection.execute(query, values).fetchall()
        return [self._source_target_from_row(row) for row in rows]

    # CrawlRun API -----------------------------------------------------

    def create_crawl_run(
        self,
        *,
        item_id: int,
        source_id: int,
        target_id: int,
        access_strategy: str,
        started_at: datetime | str | None = None,
    ) -> CrawlRun:
        self._validate_access_strategy(access_strategy)
        started = format_timestamp(started_at) or format_timestamp(now_jst())
        timestamp = format_timestamp(now_jst())
        with self._connection() as connection:
            self._require_row(connection, "items", item_id, "item")
            source = connection.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
            if source is None:
                raise CatalogNotFoundError(f"Catalog source not found: {source_id}")
            target = connection.execute(
                "SELECT * FROM source_targets WHERE id = ?", (target_id,)
            ).fetchone()
            if target is None:
                raise CatalogNotFoundError(f"Catalog source target not found: {target_id}")
            if source["item_id"] != item_id:
                raise CatalogValidationError("source.item_id does not match item_id")
            if target["source_id"] != source_id:
                raise CatalogValidationError("target.source_id does not match source_id")
            cursor = connection.execute(
                "INSERT INTO crawl_runs (item_id, source_id, target_id, site_snapshot, "
                "external_id_snapshot, backend_snapshot, target_key_snapshot, locator_snapshot, "
                "access_strategy, status, started_at, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, ?, ?)",
                (item_id, source_id, target_id, source["site"], source["external_id"],
                 target["backend"], target["target_key"], target["locator"], access_strategy,
                 started, timestamp, timestamp),
            )
            row = connection.execute("SELECT * FROM crawl_runs WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return self._crawl_run_from_row(row)

    def get_crawl_run(self, run_id: int) -> CrawlRun:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM crawl_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise CatalogNotFoundError(f"Catalog crawl run not found: {run_id}")
        return self._crawl_run_from_row(row)

    def list_crawl_runs(
        self, *, item_id: int | None = None, source_id: int | None = None,
        target_id: int | None = None, status: str | None = None,
    ) -> list[CrawlRun]:
        if status is not None:
            self._validate_run_status(status)
        conditions: list[str] = []
        values: list[Any] = []
        for column, value in (("item_id", item_id), ("source_id", source_id), ("target_id", target_id),
                              ("status", status)):
            if value is not None:
                conditions.append(f"{column} = ?")
                values.append(value)
        query = "SELECT * FROM crawl_runs"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY id"
        with self._connection() as connection:
            rows = connection.execute(query, values).fetchall()
        return [self._crawl_run_from_row(row) for row in rows]

    def mark_crawl_run_succeeded(
        self, run_id: int, *, page_count: int, stop_reason: str | None = None,
        finished_at: datetime | str | None = None,
    ) -> CrawlRun:
        self._validate_page_count(page_count, required=True)
        return self._finish_crawl_run(
            run_id, status="succeeded", page_count=page_count, stop_reason=stop_reason,
            finished_at=finished_at,
        )

    def mark_crawl_run_failed(
        self, run_id: int, *, error_type: str, error_message: str | None = None,
        page_count: int | None = None, stop_reason: str | None = None,
        finished_at: datetime | str | None = None,
    ) -> CrawlRun:
        self._validate_nonempty(error_type, "error_type")
        self._validate_page_count(page_count, required=False)
        return self._finish_crawl_run(
            run_id, status="failed", page_count=page_count, stop_reason=stop_reason,
            finished_at=finished_at, error_type=error_type, error_message=error_message,
        )

    def finalize_successful_crawl(
        self,
        run_id: int,
        *,
        artifact: ArtifactInput | Mapping[str, Any],
        page_count: int,
        stop_reason: str | None = None,
        finished_at: datetime | str | None = None,
    ) -> tuple[CrawlRun, Artifact, Item]:
        """Atomically persist the artifact, successful run, and completed item."""

        artifact_input = self._coerce_artifact_input(artifact)
        normalized_sha = self._validate_artifact_input(artifact_input)
        self._validate_page_count(page_count, required=True)
        completion = format_timestamp(finished_at) or format_timestamp(now_jst())
        timestamp = format_timestamp(now_jst())
        with self._connection() as connection:
            run = self._require_row(connection, "crawl_runs", run_id, "crawl run")
            if run["status"] != "running":
                raise CatalogValidationError(
                    f"CrawlRun {run_id} is terminal ({run['status']}) and cannot finalize"
                )
            self._require_row(connection, "items", run["item_id"], "item")
            cursor = connection.execute(
                "INSERT INTO artifacts (item_id, crawl_run_id, kind, format, sha256, byte_size, "
                "storage_backend, locator, state, last_verified_at, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run["item_id"],
                    run_id,
                    artifact_input.kind,
                    artifact_input.format,
                    normalized_sha,
                    artifact_input.byte_size,
                    artifact_input.storage_backend,
                    artifact_input.locator,
                    artifact_input.state,
                    completion,
                    timestamp,
                    timestamp,
                ),
            )
            artifact_row = connection.execute(
                "SELECT * FROM artifacts WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            connection.execute(
                "UPDATE crawl_runs SET status = 'succeeded', finished_at = ?, page_count = ?, "
                "stop_reason = ?, updated_at = ? WHERE id = ?",
                (completion, page_count, stop_reason, timestamp, run_id),
            )
            connection.execute(
                "UPDATE items SET status = 'completed', completed_at = ?, updated_at = ? "
                "WHERE id = ?",
                (completion, timestamp, run["item_id"]),
            )
            run_row = connection.execute(
                "SELECT * FROM crawl_runs WHERE id = ?", (run_id,)
            ).fetchone()
            item_row = connection.execute(
                "SELECT * FROM items WHERE id = ?", (run["item_id"],)
            ).fetchone()
        return (
            self._crawl_run_from_row(run_row),
            self._artifact_from_row(artifact_row),
            self._item_from_row(item_row),
        )

    # Artifact API -----------------------------------------------------

    def create_artifact(
        self,
        artifact: ArtifactInput | Mapping[str, Any] | None = None,
        *,
        item_id: int | None = None,
        crawl_run_id: int | None = None,
        **fields: Any,
    ) -> Artifact:
        artifact_input = self._coerce_artifact_input(artifact, fields)
        normalized_sha = self._validate_artifact_input(artifact_input)
        if item_id is None:
            raise CatalogValidationError("item_id is required")
        verified = format_timestamp(artifact_input.last_verified_at)
        timestamp = format_timestamp(now_jst())
        with self._connection() as connection:
            self._require_row(connection, "items", item_id, "item")
            if crawl_run_id is not None:
                run = connection.execute(
                    "SELECT item_id FROM crawl_runs WHERE id = ?", (crawl_run_id,)
                ).fetchone()
                if run is None:
                    raise CatalogNotFoundError(f"Catalog crawl run not found: {crawl_run_id}")
                if run["item_id"] != item_id:
                    raise CatalogValidationError("crawl_run.item_id does not match artifact item_id")
            cursor = connection.execute(
                "INSERT INTO artifacts (item_id, crawl_run_id, kind, format, sha256, byte_size, "
                "storage_backend, locator, state, last_verified_at, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (item_id, crawl_run_id, artifact_input.kind, artifact_input.format, normalized_sha,
                 artifact_input.byte_size, artifact_input.storage_backend, artifact_input.locator,
                 artifact_input.state, verified, timestamp, timestamp),
            )
            row = connection.execute("SELECT * FROM artifacts WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return self._artifact_from_row(row)

    def get_artifact(self, artifact_id: int) -> Artifact:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
        if row is None:
            raise CatalogNotFoundError(f"Catalog artifact not found: {artifact_id}")
        return self._artifact_from_row(row)

    def list_artifacts(
        self, *, item_id: int | None = None, crawl_run_id: int | None = None,
        state: str | None = None,
    ) -> list[Artifact]:
        if state is not None:
            self._validate_artifact_state(state)
        conditions: list[str] = []
        values: list[Any] = []
        for column, value in (("item_id", item_id), ("crawl_run_id", crawl_run_id), ("state", state)):
            if value is not None:
                conditions.append(f"{column} = ?")
                values.append(value)
        query = "SELECT * FROM artifacts"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY id"
        with self._connection() as connection:
            rows = connection.execute(query, values).fetchall()
        return [self._artifact_from_row(row) for row in rows]

    def update_artifact_storage(
        self,
        artifact_id: int,
        *,
        storage_backend: str | object = _UNSET,
        locator: str | None | object = _UNSET,
        state: str | object = _UNSET,
        last_verified_at: datetime | str | None | object = _UNSET,
    ) -> Artifact:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
            if row is None:
                raise CatalogNotFoundError(f"Catalog artifact not found: {artifact_id}")
            effective_backend = row["storage_backend"] if storage_backend is _UNSET else storage_backend
            effective_locator = row["locator"] if locator is _UNSET else locator
            effective_state = row["state"] if state is _UNSET else state
            self._validate_nonempty(effective_backend, "storage_backend")
            self._validate_artifact_state(effective_state)
            self._validate_locator(effective_locator, required=effective_state == "present")
            assignments: list[str] = []
            values: list[Any] = []
            if storage_backend is not _UNSET:
                assignments.append("storage_backend = ?")
                values.append(effective_backend)
            if locator is not _UNSET:
                assignments.append("locator = ?")
                values.append(effective_locator)
            if state is not _UNSET:
                assignments.append("state = ?")
                values.append(effective_state)
            if last_verified_at is not _UNSET:
                assignments.append("last_verified_at = ?")
                values.append(format_timestamp(last_verified_at))
            if assignments:
                assignments.append("updated_at = ?")
                values.extend([format_timestamp(now_jst()), artifact_id])
                connection.execute(
                    "UPDATE artifacts SET " + ", ".join(assignments) + " WHERE id = ?", values
                )
            updated = connection.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
        return self._artifact_from_row(updated)

    # Read helpers retained for callers that only inspect Catalog rows. ----

    def read_items_and_sources(self, *, site: str) -> tuple[list[Item], list[Source]]:
        self._validate_nonempty(site, "site")
        with self._read_only_connection() as connection:
            items = connection.execute("SELECT * FROM items ORDER BY id").fetchall()
            sources = connection.execute(
                "SELECT * FROM sources WHERE site = ? ORDER BY id", (site,)
            ).fetchall()
        return ([self._item_from_row(row) for row in items],
                [self._source_from_row(row) for row in sources])

    def read_items_sources_and_targets(
        self, *, site: str
    ) -> tuple[list[Item], list[Source], list[SourceTarget]]:
        self._validate_nonempty(site, "site")
        with self._read_only_connection() as connection:
            items = connection.execute("SELECT * FROM items ORDER BY id").fetchall()
            sources = connection.execute(
                "SELECT * FROM sources WHERE site = ? ORDER BY id", (site,)
            ).fetchall()
            targets = connection.execute(
                "SELECT st.* FROM source_targets st JOIN sources s ON s.id = st.source_id "
                "WHERE s.site = ? ORDER BY st.id", (site,)
            ).fetchall()
        return ([self._item_from_row(row) for row in items],
                [self._source_from_row(row) for row in sources],
                [self._source_target_from_row(row) for row in targets])

    def read_works_items_sources_and_targets(
        self, *, site: str
    ) -> tuple[list[Work], list[Item], list[Source], list[SourceTarget]]:
        """Read the Work-aware site snapshot used by the Batch Planner."""

        self._validate_nonempty(site, "site")
        with self._read_only_connection() as connection:
            works = connection.execute("SELECT * FROM works ORDER BY id").fetchall()
            items = connection.execute("SELECT * FROM items ORDER BY id").fetchall()
            sources = connection.execute(
                "SELECT * FROM sources WHERE site = ? ORDER BY id", (site,)
            ).fetchall()
            targets = connection.execute(
                "SELECT st.* FROM source_targets st JOIN sources s ON s.id = st.source_id "
                "WHERE s.site = ? ORDER BY st.id", (site,)
            ).fetchall()
        return (
            [self._work_from_row(row) for row in works],
            [self._item_from_row(row) for row in items],
            [self._source_from_row(row) for row in sources],
            [self._source_target_from_row(row) for row in targets],
        )

    # Validation and conversion ---------------------------------------

    def _finish_crawl_run(self, run_id: int, *, status: str, page_count: int | None,
                          stop_reason: str | None, finished_at: datetime | str | None,
                          error_type: str | None = None,
                          error_message: str | None = None) -> CrawlRun:
        finished = format_timestamp(finished_at) or format_timestamp(now_jst())
        timestamp = format_timestamp(now_jst())
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM crawl_runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                raise CatalogNotFoundError(f"Catalog crawl run not found: {run_id}")
            if row["status"] != "running":
                raise CatalogValidationError(
                    f"CrawlRun {run_id} is terminal ({row['status']}) and cannot transition"
                )
            connection.execute(
                "UPDATE crawl_runs SET status = ?, finished_at = ?, page_count = ?, stop_reason = ?, "
                "error_type = ?, error_message = ?, updated_at = ? WHERE id = ?",
                (status, finished, page_count, stop_reason, error_type, error_message, timestamp, run_id),
            )
            updated = connection.execute("SELECT * FROM crawl_runs WHERE id = ?", (run_id,)).fetchone()
        return self._crawl_run_from_row(updated)

    @staticmethod
    def _require_row(connection: sqlite3.Connection, table: str, row_id: int, label: str) -> sqlite3.Row:
        row = connection.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
        if row is None:
            raise CatalogNotFoundError(f"Catalog {label} not found: {row_id}")
        return row

    @staticmethod
    def _validate_nonempty(value: Any, field: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise CatalogValidationError(f"{field} must be a non-empty string")

    @staticmethod
    def _validate_optional_text(value: Any, field: str) -> None:
        if value is not None and not isinstance(value, str):
            raise CatalogValidationError(f"{field} must be a string or null")

    @classmethod
    def _validate_work_input(cls, work: WorkInput) -> None:
        cls._validate_nonempty(work.work_key, "work_key")
        cls._validate_nonempty(work.title, "title")
        for field, value in (("author", work.author), ("genre", work.genre)):
            if value is not None and not isinstance(value, str):
                raise CatalogValidationError(f"{field} must be a string or null")

    @staticmethod
    def _validate_status(value: Any) -> None:
        if value not in {"pending", "completed"}:
            raise CatalogValidationError("status must be 'pending' or 'completed'")

    @staticmethod
    def _validate_access_mode(value: Any) -> None:
        if value not in {"owned", "free", "quota", "paid", "unknown"}:
            raise CatalogValidationError(
                "access_mode must be one of owned, free, quota, paid, unknown"
            )

    @classmethod
    def _validate_source_input(cls, source: SourceInput) -> None:
        cls._validate_nonempty(source.site, "site")
        cls._validate_nonempty(source.external_id, "external_id")
        cls._validate_access_mode(source.access_mode)
        if source.available is not None and not isinstance(source.available, bool):
            raise CatalogValidationError("available must be a boolean")
        for value in (source.free_until, source.access_checked_at, source.last_seen_at,
                      source.quota_started_at, source.access_granted_until, source.published_at):
            format_timestamp(value)

    @classmethod
    def _validate_source_target_input(cls, target: SourceTargetInput) -> None:
        cls._validate_nonempty(target.backend, "backend")
        cls._validate_nonempty(target.target_key, "target_key")
        cls._validate_nonempty(target.locator, "locator")
        if isinstance(target.priority, bool) or not isinstance(target.priority, int):
            raise CatalogValidationError("priority must be an integer")
        if target.priority < 0:
            raise CatalogValidationError("priority must be >= 0")
        if not isinstance(target.enabled, bool):
            raise CatalogValidationError("enabled must be a boolean")

    @classmethod
    def _validate_artifact_input(cls, artifact: ArtifactInput) -> str:
        cls._validate_nonempty(artifact.kind, "kind")
        cls._validate_nonempty(artifact.format, "format")
        cls._validate_nonempty(artifact.storage_backend, "storage_backend")
        if not isinstance(artifact.sha256, str) or not _SHA256.fullmatch(artifact.sha256):
            raise CatalogValidationError("sha256 must be exactly 64 hexadecimal characters")
        if isinstance(artifact.byte_size, bool) or not isinstance(artifact.byte_size, int):
            raise CatalogValidationError("byte_size must be an integer")
        if artifact.byte_size < 0:
            raise CatalogValidationError("byte_size must be >= 0")
        cls._validate_artifact_state(artifact.state)
        cls._validate_locator(artifact.locator, required=artifact.state == "present")
        return artifact.sha256.lower()

    @classmethod
    def _validate_locator(cls, locator: Any, *, required: bool) -> None:
        if locator is None:
            if required:
                raise CatalogValidationError("locator is required when state is present")
            return
        cls._validate_nonempty(locator, "locator")

    @staticmethod
    def _validate_artifact_state(value: Any) -> None:
        if value not in {"present", "missing", "deleted", "unknown"}:
            raise CatalogValidationError(
                "state must be one of present, missing, deleted, unknown"
            )

    @staticmethod
    def _validate_access_strategy(value: Any) -> None:
        if value not in {"auto", "direct", "quota"}:
            raise CatalogValidationError("access_strategy must be one of auto, direct, quota")

    @staticmethod
    def _validate_run_status(value: Any) -> None:
        if value not in {"running", "succeeded", "failed"}:
            raise CatalogValidationError("status must be one of running, succeeded, failed")

    @staticmethod
    def _validate_page_count(value: Any, *, required: bool) -> None:
        if value is None and not required:
            return
        if isinstance(value, bool) or not isinstance(value, int):
            raise CatalogValidationError("page_count must be an integer")
        if value < 0:
            raise CatalogValidationError("page_count must be >= 0")

    @staticmethod
    def _coerce_mapping(value: Any, cls: type, label: str, fields: Mapping[str, Any] | None = None):
        values: dict[str, Any] = {}
        if value is not None:
            if isinstance(value, cls):
                values.update({name: getattr(value, name) for name in cls.__dataclass_fields__})
            elif isinstance(value, Mapping):
                values.update(value)
            else:
                raise CatalogValidationError(f"{label} must be {cls.__name__} or a mapping")
        if fields:
            values.update(fields)
        allowed = set(cls.__dataclass_fields__)
        unknown = set(values) - allowed
        if unknown:
            raise CatalogValidationError(f"Unknown {label} field(s): {', '.join(sorted(unknown))}")
        try:
            return cls(**values)
        except TypeError as exc:
            raise CatalogValidationError(str(exc)) from exc

    @classmethod
    def _coerce_work_input(cls, work: WorkInput | Mapping[str, Any] | None,
                           fields: Mapping[str, Any] | None = None) -> WorkInput:
        return cls._coerce_mapping(work, WorkInput, "work", fields)

    @classmethod
    def _coerce_item_input(cls, item: ItemInput | Mapping[str, Any] | None,
                           fields: Mapping[str, Any] | None = None) -> ItemInput:
        return cls._coerce_mapping(item, ItemInput, "item", fields)

    @classmethod
    def _coerce_source_input(cls, source: SourceInput | Mapping[str, Any]) -> SourceInput:
        return cls._coerce_mapping(source, SourceInput, "source")

    @classmethod
    def _coerce_source_target_input(cls, target: SourceTargetInput | Mapping[str, Any]) -> SourceTargetInput:
        return cls._coerce_mapping(target, SourceTargetInput, "source target")

    @classmethod
    def _coerce_artifact_input(cls, artifact: ArtifactInput | Mapping[str, Any] | None,
                               fields: Mapping[str, Any] | None = None) -> ArtifactInput:
        return cls._coerce_mapping(artifact, ArtifactInput, "artifact", fields)

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

    @contextmanager
    def _read_only_connection(self):
        if not self.path.exists() or not self.path.is_file():
            raise CatalogNotFoundError(f"Catalog database not found: {self.path}")
        try:
            connection = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
        except sqlite3.Error as exc:
            raise CatalogError(f"Could not open Catalog database '{self.path}': {exc}") from exc
        try:
            if schema.user_version(connection) == 0:
                tables = {
                    row[0] for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                    )
                }
                if not tables:
                    raise CatalogError("Catalog schema is not initialized")
            try:
                schema.initialize(connection)
            except schema.SchemaError as exc:
                raise self._schema_error(exc) from exc
            yield connection
        except sqlite3.DatabaseError as exc:
            raise CatalogError(f"Could not read Catalog database '{self.path}': {exc}") from exc
        finally:
            connection.close()

    @staticmethod
    def _schema_error(exc: schema.SchemaError) -> CatalogError:
        if "Unsupported Catalog schema version" in str(exc):
            return UnsupportedSchemaVersionError(str(exc))
        return CatalogError(str(exc))

    @staticmethod
    def _work_from_row(row: sqlite3.Row) -> Work:
        return Work(**dict(row))

    @staticmethod
    def _item_from_row(row: sqlite3.Row) -> Item:
        return Item(**dict(row))

    @staticmethod
    def _source_from_row(row: sqlite3.Row) -> Source:
        values = dict(row)
        values["available"] = bool(values["available"])
        return Source(**values)

    @staticmethod
    def _quota_resource_state_from_row(row: sqlite3.Row) -> QuotaResourceState:
        return QuotaResourceState(**dict(row))

    @staticmethod
    def _source_target_from_row(row: sqlite3.Row) -> SourceTarget:
        values = dict(row)
        values["enabled"] = bool(values["enabled"])
        return SourceTarget(**values)

    @staticmethod
    def _crawl_run_from_row(row: sqlite3.Row) -> CrawlRun:
        return CrawlRun(**dict(row))

    @staticmethod
    def _artifact_from_row(row: sqlite3.Row) -> Artifact:
        return Artifact(**dict(row))
