"""Production Zeblack viewer and Discovery adapters."""

from screenshot_crawler.site_adapters.zeblack.adapter import (
    ZeblackAdapter,
    ZeblackViewerIdentity,
    parse_zeblack_page_alt,
    parse_zeblack_viewer_url,
)
from screenshot_crawler.site_adapters.zeblack.discovery import (
    ZeblackDiscoveryAdapter,
    ZeblackListIdentity,
    canonical_zeblack_viewer_url,
    parse_zeblack_chapter_list_url,
    parse_zeblack_order_label,
)

__all__ = [
    "ZeblackAdapter",
    "ZeblackDiscoveryAdapter",
    "ZeblackListIdentity",
    "ZeblackViewerIdentity",
    "canonical_zeblack_viewer_url",
    "parse_zeblack_chapter_list_url",
    "parse_zeblack_order_label",
    "parse_zeblack_page_alt",
    "parse_zeblack_viewer_url",
]
