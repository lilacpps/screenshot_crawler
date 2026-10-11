"""Younganimal site-local Discovery and free-crawl support."""

from screenshot_crawler.site_adapters.younganimal.adapter import YounganimalAdapter
from screenshot_crawler.site_adapters.younganimal.discovery import YounganimalDiscoveryAdapter

__all__ = ["YounganimalAdapter", "YounganimalDiscoveryAdapter"]
