"""Catalog input and row models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class ItemInput:
    canonical_title: str | None = None
    author: str | None = None
    genre: str | None = None
    kind: str | None = None
    order_key: str | None = None
    order_label: str | None = None
    status: str = "pending"


@dataclass(frozen=True, slots=True)
class SourceInput:
    site: str
    external_id: str
    url: str
    discovery_key: str | None = None
    access_mode: str = "unknown"
    free_until: datetime | str | None = None
    available: bool | None = None
    access_checked_at: datetime | str | None = None
    last_seen_at: datetime | str | None = None
    quota_started_at: datetime | str | None = None
    access_granted_until: datetime | str | None = None


@dataclass(frozen=True, slots=True)
class Item:
    id: int
    canonical_title: str | None
    author: str | None
    genre: str | None
    kind: str | None
    order_key: str | None
    order_label: str | None
    status: str
    local_path: str | None
    completed_at: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class Source:
    id: int
    item_id: int
    site: str
    external_id: str
    discovery_key: str | None
    url: str
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
class CatalogRecord:
    item: Item
    source: Source


TimestampValue = datetime | str | None
CatalogMapping = dict[str, Any]
