"""Production adapters for Shonen Jump+."""

from screenshot_crawler.site_adapters.jumpplus.adapter import JumpPlusAdapter
from screenshot_crawler.site_adapters.jumpplus.discovery import (
    JumpPlusDiscoveryAdapter,
    canonical_jumpplus_episode_url,
    parse_jumpplus_episode_url,
    parse_jumpplus_range_label,
)

__all__ = [
    "JumpPlusAdapter",
    "JumpPlusDiscoveryAdapter",
    "canonical_jumpplus_episode_url",
    "parse_jumpplus_episode_url",
    "parse_jumpplus_range_label",
]
