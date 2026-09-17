"""Site-neutral Discovery framework."""

from screenshot_crawler.discovery.base import DiscoveryAdapter
from screenshot_crawler.discovery.models import (
    DiscoveredItem,
    DiscoveredRecord,
    DiscoveredSource,
    DiscoveryMode,
    DiscoveryResult,
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
]
