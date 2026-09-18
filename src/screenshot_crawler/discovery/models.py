"""Site-neutral models exchanged by Discovery adapters and the service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal

DiscoveryMode = Literal["full", "incremental"]
TimestampValue = datetime | str | None


@dataclass(frozen=True, slots=True)
class DiscoverySourceSnapshot:
    """Run-start source state exposed to site-specific Discovery hooks."""

    external_id: str
    discovery_key: str | None
    access_mode: str
    available: bool


class IncrementalStopDecision(StrEnum):
    """Whether an adapter overrides the service's generic known-streak rule."""

    DEFAULT = "default"
    CONTINUE = "continue"
    STOP = "stop"


@dataclass(frozen=True, slots=True)
class DiscoveredItem:
    canonical_title: str | None = None
    author: str | None = None
    genre: str | None = None
    kind: str | None = None
    order_key: str | None = None
    order_label: str | None = None


@dataclass(frozen=True, slots=True)
class DiscoveredSource:
    external_id: str
    url: str
    access_mode: str = "unknown"
    free_until: TimestampValue = None
    available: bool | None = None
    access_checked_at: TimestampValue = None
    last_seen_at: TimestampValue = None


@dataclass(frozen=True, slots=True)
class DiscoveredRecord:
    item: DiscoveredItem
    source: DiscoveredSource


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    mode: DiscoveryMode
    target_key: str
    observed_count: int
    new_count: int
    known_count: int
    complete: bool | None
    stopped_reason: str
    warnings: tuple[str, ...]
