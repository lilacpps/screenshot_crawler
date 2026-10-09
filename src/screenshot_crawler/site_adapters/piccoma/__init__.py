"""Piccoma site-local free-only crawler and Discovery adapters."""

from screenshot_crawler.site_adapters.piccoma.adapter import PiccomaAdapter
from screenshot_crawler.site_adapters.piccoma.discovery import (
    PiccomaDiscoveryAdapter,
    PiccomaEpisodeIdentity,
    canonical_piccoma_viewer_url,
    classify_piccoma_access,
    parse_piccoma_listing_url,
    parse_piccoma_viewer_url,
)

__all__ = [
    "PiccomaAdapter",
    "PiccomaDiscoveryAdapter",
    "PiccomaEpisodeIdentity",
    "canonical_piccoma_viewer_url",
    "classify_piccoma_access",
    "parse_piccoma_listing_url",
    "parse_piccoma_viewer_url",
]
