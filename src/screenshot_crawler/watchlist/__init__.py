"""Human-managed watchlist configuration."""

from screenshot_crawler.watchlist.models import ArchiveSegment, DiscoveryScope, WatchlistTarget
from screenshot_crawler.watchlist.service import (
    DuplicateWatchlistKeyError,
    InvalidWatchlistError,
    WatchlistEditPreview,
    WatchlistError,
    WatchlistService,
    WatchlistTargetNotFoundError,
)

__all__ = [
    "ArchiveArtifactFact",
    "ArchiveFactsSnapshot",
    "ArchiveSegment",
    "DiscoveryScope",
    "DuplicateWatchlistKeyError",
    "InvalidWatchlistError",
    "ScopeEditPreview",
    "ScopeSelectionPlan",
    "SelectionPlanner",
    "WatchlistEditPreview",
    "WatchlistError",
    "WatchlistService",
    "WatchlistTarget",
    "WatchlistTargetNotFoundError",
]


def __getattr__(name: str):
    # Selection planning imports the Discovery DTO package. Keep it lazy so
    # archive_order -> watchlist.models does not create a package-init cycle.
    if name in {
        "ArchiveArtifactFact",
        "ArchiveFactsSnapshot",
        "ScopeEditPreview",
        "ScopeSelectionPlan",
        "SelectionPlanner",
    }:
        from screenshot_crawler.watchlist.selection import (
            ArchiveArtifactFact,
            ArchiveFactsSnapshot,
            ScopeEditPreview,
            ScopeSelectionPlan,
            SelectionPlanner,
        )

        return {
            "ArchiveArtifactFact": ArchiveArtifactFact,
            "ArchiveFactsSnapshot": ArchiveFactsSnapshot,
            "ScopeEditPreview": ScopeEditPreview,
            "ScopeSelectionPlan": ScopeSelectionPlan,
            "SelectionPlanner": SelectionPlanner,
        }[name]
    raise AttributeError(name)
