"""Data model for a watchlist target."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WatchlistTarget:
    """One human-managed Discovery starting point."""

    key: str
    work_key: str
    site: str
    url: str
    label: str
    enabled: bool = True
