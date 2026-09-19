"""Catalog v3 input and row models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class WorkInput:
    work_key: str
    title: str
    author: str | None = None
    genre: str | None = None


@dataclass(frozen=True, slots=True)
class Work:
    id: int
    work_key: str
    title: str
    author: str | None
    genre: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ItemInput:
    item_title: str | None = None
    kind: str | None = None
    order_key: str | None = None
    order_label: str | None = None
    status: str = "pending"


@dataclass(frozen=True, slots=True)
class Item:
    id: int
    work_id: int
    item_title: str | None
    kind: str | None
    order_key: str | None
    order_label: str | None
    status: str
    completed_at: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class SourceInput:
    site: str
    external_id: str
    discovery_key: str | None = None
    access_mode: str = "unknown"
    free_until: datetime | str | None = None
    available: bool | None = None
    access_checked_at: datetime | str | None = None
    last_seen_at: datetime | str | None = None
    quota_started_at: datetime | str | None = None
    access_granted_until: datetime | str | None = None


@dataclass(frozen=True, slots=True)
class Source:
    id: int
    item_id: int
    site: str
    external_id: str
    discovery_key: str | None
    access_mode: str
    free_until: str | None
    available: bool
    access_checked_at: str | None
    last_seen_at: str | None
    quota_started_at: str | None
    access_granted_until: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class SourceTargetInput:
    backend: str
    locator: str
    target_key: str = "default"
    priority: int = 100
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class SourceTarget:
    id: int
    source_id: int
    backend: str
    target_key: str
    locator: str
    priority: int
    enabled: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class CrawlRun:
    id: int
    item_id: int
    source_id: int
    target_id: int
    site_snapshot: str
    external_id_snapshot: str
    backend_snapshot: str
    target_key_snapshot: str
    locator_snapshot: str
    access_strategy: str
    status: str
    started_at: str
    finished_at: str | None
    page_count: int | None
    stop_reason: str | None
    error_type: str | None
    error_message: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ArtifactInput:
    kind: str
    format: str
    sha256: str
    byte_size: int
    storage_backend: str
    locator: str | None = None
    state: str = "unknown"
    last_verified_at: datetime | str | None = None


@dataclass(frozen=True, slots=True)
class Artifact:
    id: int
    item_id: int
    crawl_run_id: int | None
    kind: str
    format: str
    sha256: str
    byte_size: int
    storage_backend: str
    locator: str | None
    state: str
    last_verified_at: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class CatalogRecord:
    """Catalog graph returned by discovery-oriented service helpers."""

    item: Item
    source: Source
    target: SourceTarget | None = None


TimestampValue = datetime | str | None
CatalogMapping = dict[str, Any]
