"""Contract for site-specific Discovery listing adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from screenshot_crawler.discovery.models import (
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
