"""Magapoke browser viewer and Discovery adapters."""

from screenshot_crawler.site_adapters.magapoke.adapter import MagapokeAdapter
from screenshot_crawler.site_adapters.magapoke.discovery import (
    MagapokeDiscoveryAdapter,
)

__all__ = ["MagapokeAdapter", "MagapokeDiscoveryAdapter"]
