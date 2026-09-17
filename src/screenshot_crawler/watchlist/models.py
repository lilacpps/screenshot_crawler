"""Data model for a watchlist target."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WatchlistTarget:
    """One human-managed Discovery starting point."""

    key: str
    site: str
    url: str
    enabled: bool = True
    label: str | None = None
