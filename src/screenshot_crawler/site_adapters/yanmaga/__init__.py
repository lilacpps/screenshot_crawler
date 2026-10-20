"""YanmagaWeb free-only Discovery and rendered-page capture support."""

from screenshot_crawler.site_adapters.yanmaga.adapter import (
    YanmagaAdapter,
    parse_yanmaga_composite_id,
    parse_yanmaga_page_counter,
    parse_yanmaga_viewer_url,
)
from screenshot_crawler.site_adapters.yanmaga.discovery import (
    YanmagaDiscoveryAdapter,
    YanmagaEpisodeParts,
    YanmagaWorkParts,
    classify_yanmaga_free_marker,
    has_yanmaga_anonymous_proof,
    parse_yanmaga_episode_url,
    parse_yanmaga_work_url,
)

__all__ = [
    "YanmagaAdapter",
    "YanmagaDiscoveryAdapter",
    "YanmagaEpisodeParts",
    "YanmagaWorkParts",
    "classify_yanmaga_free_marker",
    "has_yanmaga_anonymous_proof",
    "parse_yanmaga_composite_id",
    "parse_yanmaga_episode_url",
    "parse_yanmaga_page_counter",
    "parse_yanmaga_viewer_url",
    "parse_yanmaga_work_url",
]
