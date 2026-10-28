"""Data model for a watchlist target."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DiscoveryScope:
    """Optional site-native boundaries for a bounded Discovery target."""

    from_url: str | None = None
    through_url: str | None = None
    excluded_external_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ArchiveSegment:
    """An oldest-first interval placed in a Work's explicit archive sequence."""

    order: int
    start_external_id: str | None = None
    end_external_id: str | None = None


@dataclass(frozen=True, slots=True)
class WatchlistTarget:
    """One human-managed Discovery starting point."""

    key: str
    work_key: str
    site: str
    url: str
    label: str
    enabled: bool = True
    discovery_scope: DiscoveryScope | None = None
    archive_order: int | None = None
    archive_segments: tuple[ArchiveSegment, ...] | None = None
