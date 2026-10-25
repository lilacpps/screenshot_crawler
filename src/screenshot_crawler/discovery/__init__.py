"""Site-neutral Discovery framework."""

from screenshot_crawler.discovery.base import DiscoveryAdapter
from screenshot_crawler.discovery.listing import (
    ListingPreview,
    ListingRow,
    blocked_listing_preview,
    listing_digest,
)
from screenshot_crawler.discovery.listing_service import ListingPreviewService
from screenshot_crawler.discovery.models import (
    DiscoveredItem,
    DiscoveredRecord,
    DiscoveredSource,
    DiscoveryMode,
    DiscoveryResult,
    DiscoverySourceSnapshot,
    IncrementalStopDecision,
)
from screenshot_crawler.discovery.registry import DiscoveryAdapterRegistry
from screenshot_crawler.discovery.service import (
    DiscoveryIncompleteError,
    DiscoveryService,
)

__all__ = [
    "DiscoveredItem",
    "DiscoveredRecord",
    "DiscoveredSource",
    "DiscoveryAdapter",
    "DiscoveryAdapterRegistry",
    "DiscoveryIncompleteError",
    "DiscoveryMode",
    "DiscoveryResult",
    "DiscoveryService",
    "DiscoverySourceSnapshot",
    "IncrementalStopDecision",
    "ListingPreview",
    "ListingPreviewService",
    "ListingRow",
    "blocked_listing_preview",
    "listing_digest",
]
