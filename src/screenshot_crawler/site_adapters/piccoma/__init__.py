"""Piccoma site-local Discovery support."""

from screenshot_crawler.site_adapters.piccoma.discovery import (
    PiccomaDiscoveryAdapter,
    PiccomaEpisodeIdentity,
    canonical_piccoma_viewer_url,
    classify_piccoma_access,
    parse_piccoma_listing_url,
    parse_piccoma_viewer_url,
)

__all__ = [
    "PiccomaDiscoveryAdapter",
    "PiccomaEpisodeIdentity",
    "canonical_piccoma_viewer_url",
    "classify_piccoma_access",
    "parse_piccoma_listing_url",
    "parse_piccoma_viewer_url",
]
