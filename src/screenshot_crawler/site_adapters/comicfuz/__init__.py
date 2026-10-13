"""ComicFUZ anonymous Discovery and viewer support."""

from screenshot_crawler.site_adapters.comicfuz.adapter import ComicFuzAdapter
from screenshot_crawler.site_adapters.comicfuz.discovery import (
    ComicFuzDiscoveryAdapter,
    ComicFuzWorkParts,
    parse_comicfuz_episode_url,
    parse_comicfuz_work_url,
)

__all__ = [
    "ComicFuzAdapter",
    "ComicFuzDiscoveryAdapter",
    "ComicFuzWorkParts",
    "parse_comicfuz_episode_url",
    "parse_comicfuz_work_url",
]
