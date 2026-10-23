"""Immutable Inventory DTOs shared by readers and the optional GUI."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from screenshot_crawler.catalog.models import Artifact, CrawlRun, Item, Source, SourceTarget
from screenshot_crawler.watchlist.models import WatchlistTarget


@dataclass(frozen=True, slots=True)
class InventoryCounts:
    total_assigned: int = 0
    completed: int = 0
    external: int = 0
    skipped: int = 0
    direct: int = 0
    quota: int = 0
    paid: int = 0
    unavailable: int = 0
    unknown: int = 0
    out_of_scope: int = 0  # Source count; all other fields count unique Items.


@dataclass(frozen=True, slots=True)
class AccessClassification:
    category: str
    reason: str
    resources: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class InventorySummary:
    counts: InventoryCounts | None
    sync_status: str
    diagnostics: tuple[str, ...]
    last_access: str | None
    key_ids: tuple[str, ...]
    source_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class KeyInventory:
    identity: str  # Managed: key; unmanaged: reserved synthetic identity.
    target: WatchlistTarget | None
    work_key: str
    site: str
    title: str
    label: str
    summary: InventorySummary
    full_proof: str | None = None


@dataclass(frozen=True, slots=True)
class ResourceOverview:
    site: str
    available_quota: int | None
    supported_resources: tuple[str, ...]
    grant_resources: tuple[str, ...]
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GrantEstimate:
    work_key: str
    site: str
    resource: str
    last_consumed_at: str | None
    retry_at: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class InventorySnapshot:
    loaded_at: datetime
    catalog_path: str
    watchlist_path: str
    keys: tuple[KeyInventory, ...]
    summaries: Mapping[tuple[str, ...], InventorySummary]
    items: Mapping[int, Item]
    sources: Mapping[int, Source]
    source_targets: Mapping[int, tuple[SourceTarget, ...]]
    classifications: Mapping[int, AccessClassification]
    latest_runs: Mapping[int, CrawlRun]
    artifacts: Mapping[int, tuple[Artifact, ...]]
    archive_positions: Mapping[int, int]
    resources: Mapping[str, ResourceOverview]
    grants: tuple[GrantEstimate, ...]
    load_seconds: float
