"""Catalog-free orchestration for optional read-only listing previews."""

from __future__ import annotations

from typing import TYPE_CHECKING

from screenshot_crawler.discovery.listing import ListingPreview, blocked_listing_preview
from screenshot_crawler.discovery.registry import DiscoveryAdapterRegistry

if TYPE_CHECKING:
    from playwright.async_api import Page

    from screenshot_crawler.watchlist.models import WatchlistTarget


class ListingPreviewService:
    """Delegate a read-only listing preview without constructing Catalog state."""

    def __init__(self, registry: DiscoveryAdapterRegistry) -> None:
        self.registry = registry

    async def preview_complete_listing(
        self, page: Page, target: WatchlistTarget
    ) -> ListingPreview:
        from screenshot_crawler.discovery.service import DiscoveryIncompleteError

        try:
            adapter = self.registry.create(target.site)
        except KeyError:
            return blocked_listing_preview(
                site=target.site,
                target_key=target.key,
                target_url=target.url,
                reason=f"No Discovery adapter is registered for site {target.site!r}",
            )
        try:
            return await adapter.preview_complete_listing(page, target)
        except DiscoveryIncompleteError as exc:
            return blocked_listing_preview(
                site=target.site,
                target_key=target.key,
                target_url=target.url,
                reason=str(exc),
            )
