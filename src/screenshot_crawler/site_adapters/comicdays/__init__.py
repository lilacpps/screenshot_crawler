"""Comic DAYS site-local adapters."""

from screenshot_crawler.site_adapters.comicdays.adapter import ComicDaysAdapter
from screenshot_crawler.site_adapters.comicdays.discovery import (
    ComicDaysDiscoveryAdapter,
    canonical_comicdays_episode_url,
    parse_comicdays_episode_url,
)

__all__ = [
    "ComicDaysAdapter",
    "ComicDaysDiscoveryAdapter",
    "canonical_comicdays_episode_url",
    "parse_comicdays_episode_url",
]
