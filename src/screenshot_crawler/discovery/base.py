"""Contract for site-specific Discovery listing adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, ClassVar

from screenshot_crawler.discovery.listing import ListingPreview, blocked_listing_preview
from screenshot_crawler.discovery.models import (
    CompleteListingInventory,
    CompleteListingPosition,
    DiscoveredRecord,
    DiscoveryMode,
    DiscoverySourceSnapshot,
    IncrementalStopDecision,
)

if TYPE_CHECKING:
    from playwright.async_api import Page

    from screenshot_crawler.watchlist.models import WatchlistTarget


class DiscoveryAdapter(ABC):
    """Enumerate site-specific listing results without knowing Catalog."""

    supports_bounded_discovery: ClassVar[bool] = False
    supports_exclusion_only_scope: ClassVar[bool] = False
    # Exclusion discovery must process the exact complete listing that was
    # validated before Catalog writes. Adapters supporting that path must
    # replay their validated read, rather than silently re-reading a live page.
    supports_exclusion_replay: ClassVar[bool] = False
    allow_inferred_display_positions: ClassVar[bool] = True

    @property
    def complete_listing_inventory(self) -> CompleteListingInventory | None:
        return getattr(self, "_complete_listing_inventory", None)

    def reset_complete_listing_inventory(self) -> None:
        """Clear proof from a previous use of this adapter instance."""

        self._complete_listing_inventory = None

    def capture_complete_listing_inventory(
        self,
        *,
        target: WatchlistTarget,
        all_records: list[DiscoveredRecord],
        selected_records: list[DiscoveredRecord],
        listing_identity: str | None = None,
    ) -> None:
        """Publish a validated, complete full-list inventory when positions are authoritative."""

        if not all_records:
            return
        all_ids = [record.source.external_id for record in all_records]
        selected_ids = {record.source.external_id for record in selected_records}
        if len(all_ids) != len(set(all_ids)) or not selected_ids.issubset(set(all_ids)):
            return
        hints = [record.source.global_display_position for record in all_records]
        if all(isinstance(value, int) and not isinstance(value, bool) for value in hints):
            positions = [int(value) for value in hints]
        elif any(value is not None for value in hints) or not self.allow_inferred_display_positions:
            return
        else:
            positions = list(range(len(all_records), 0, -1))
        if (
            any(position < 1 for position in positions)
            or len(set(positions)) != len(positions)
        ):
            return
        self.capture_listing_identity_inventory(
            target=target,
            external_ids=all_ids,
            selected_external_ids=selected_ids,
            positions=positions,
            listing_identity=listing_identity,
        )

    def capture_listing_identity_inventory(
        self,
        *,
        target: WatchlistTarget,
        external_ids: list[str],
        selected_external_ids: set[str],
        positions: list[int],
        listing_identity: str | None = None,
    ) -> None:
        if (
            not external_ids
            or len(external_ids) != len(set(external_ids))
            or not selected_external_ids.issubset(set(external_ids))
            or len(positions) != len(external_ids)
            or any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in positions)
            or len(set(positions)) != len(positions)
        ):
            return
        self._complete_listing_inventory = CompleteListingInventory(
            listing_identity=listing_identity or f"url:{target.url}",
            positions=tuple(
                CompleteListingPosition(
                    external_id=external_id,
                    display_position=position,
                    in_scope=external_id in selected_external_ids,
                )
                for external_id, position in zip(external_ids, positions, strict=True)
            ),
        )

    # Site adapters may disable inferred positions when a current listing does
    # not establish a stable lifetime order. Complete explicit global hints
    # remain authoritative regardless of this setting.

    @abstractmethod
    def iter_records(
        self,
        page: Page,
        target: WatchlistTarget,
        mode: DiscoveryMode,
    ) -> AsyncIterator[DiscoveredRecord]:
        """Yield records in the traversal order required by ``mode``.

        ``incremental`` adapters must yield latest-first. A full traversal
        must yield every source it can safely enumerate and exhaust normally
        only after reaching the end of the target scope.
        """

        raise NotImplementedError

    def reconcile_access_mode(
        self,
        observed_access_mode: str,
        previous: DiscoverySourceSnapshot | None,
        target: WatchlistTarget,
    ) -> str:
        """Return the access mode to persist for an observed source.

        ``previous`` is a read-only snapshot from before this Discovery run,
        not a Catalog object and not the source state after an earlier record
        was upserted. The default preserves the existing observed-value
        behavior.
        """

        del previous, target
        return observed_access_mode

    def incremental_stop_decision(
        self,
        record: DiscoveredRecord,
        previous: DiscoverySourceSnapshot | None,
        target: WatchlistTarget,
    ) -> IncrementalStopDecision:
        """Choose whether this record overrides incremental stopping."""

        del record, previous, target
        return IncrementalStopDecision.DEFAULT

    async def resolve_identity_changes(
        self,
        page: Page,
        target: WatchlistTarget,
        missing_external_ids: tuple[str, ...],
        observed_records: tuple[DiscoveredRecord, ...],
    ) -> object:
        """Optionally prove site-native identity replacements after Full listing.

        The default is deliberately empty. Site-specific adapters may return
        an object with ``changes`` and ``diagnostics`` attributes; Core never
        derives equivalence from titles or display order.
        """

        del page, target, missing_external_ids, observed_records
        return ()

    async def preview_complete_listing(
        self, page: Page, target: WatchlistTarget
    ) -> ListingPreview:
        """Optionally enumerate a complete listing without Catalog writes."""

        del page
        return blocked_listing_preview(
            site=target.site,
            target_key=target.key,
            target_url=target.url,
            reason=f"Site {target.site!r} does not support read-only complete listing preview",
        )

    async def prepare_exclusion_preview(
        self, page: Page, target: WatchlistTarget
    ) -> ListingPreview:
        """Return the proof used immediately by an exclusion Discovery run."""

        return await self.preview_complete_listing(page, target)
