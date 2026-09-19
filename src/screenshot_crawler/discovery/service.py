"""Catalog orchestration for site-neutral Discovery results."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from screenshot_crawler.catalog import (
    CatalogService,
    ItemInput,
    SourceInput,
    SourceTargetInput,
)
from screenshot_crawler.catalog.models import CatalogRecord, Item
from screenshot_crawler.discovery.models import (
    DiscoveryMode,
    DiscoveryResult,
    DiscoverySourceSnapshot,
    IncrementalStopDecision,
)
from screenshot_crawler.discovery.registry import DiscoveryAdapterRegistry

if TYPE_CHECKING:
    from playwright.async_api import Page

    from screenshot_crawler.watchlist.models import WatchlistTarget

_VALID_MODES = frozenset({"full", "incremental"})
_KNOWN_STREAK_LIMIT = 2
_WHITESPACE = re.compile(r"\s+")


class DiscoveryIncompleteError(RuntimeError):
    """Raised by an adapter when a full traversal cannot be trusted complete."""


class DiscoveryService:
    """Run a Discovery adapter and synchronize its results into Catalog."""

    def __init__(
        self,
        catalog: CatalogService,
        registry: DiscoveryAdapterRegistry,
    ) -> None:
        self.catalog = catalog
        self.registry = registry

    async def discover(
        self,
        page: Page,
        target: WatchlistTarget,
        mode: DiscoveryMode | str,
    ) -> DiscoveryResult:
        """Discover one enabled Watchlist target using a caller-owned Page."""

        mode = self._validate_mode(mode)
        if not target.enabled:
            return DiscoveryResult(
                mode=mode,
                target_key=target.key,
                observed_count=0,
                new_count=0,
                known_count=0,
                complete=None,
                stopped_reason="disabled",
                warnings=(),
            )

        adapter = self.registry.create(target.site)
        initial_sources = {
            source.external_id: DiscoverySourceSnapshot(
                external_id=source.external_id,
                discovery_key=source.discovery_key,
                access_mode=source.access_mode,
                available=source.available,
            )
            for source in self.catalog.list_sources(site=target.site)
        }
        observed_external_ids: set[str] = set()
        warnings: list[str] = []
        warning_keys: set[tuple[int, str]] = set()
        observed_count = 0
        new_count = 0
        known_count = 0
        known_streak = 0
        previous_known_identity: tuple[str, str] | None = None

        try:
            async for record in adapter.iter_records(page, target, mode):
                existing = self.catalog.find_source(
                    target.site, record.source.external_id
                )
                previous = initial_sources.get(record.source.external_id)
                if existing is None:
                    new_count += 1
                    known_streak = 0
                    previous_known_identity = None
                else:
                    known_count += 1
                    known_identity = (target.site, record.source.external_id)
                    if known_identity != previous_known_identity:
                        known_streak += 1
                    previous_known_identity = known_identity

                access_mode = adapter.reconcile_access_mode(
                    record.source.access_mode,
                    previous,
                    target,
                )
                catalog_record = self.catalog.upsert_item_source(
                    ItemInput(
                        canonical_title=record.item.canonical_title,
                        author=record.item.author,
                        genre=record.item.genre,
                        kind=record.item.kind,
                        order_key=record.item.order_key,
                        order_label=record.item.order_label,
                    ),
                    SourceInput(
                        site=target.site,
                        external_id=record.source.external_id,
                        discovery_key=target.key,
                        access_mode=access_mode,
                        free_until=record.source.free_until,
                        available=record.source.available,
                        access_checked_at=record.source.access_checked_at,
                        last_seen_at=record.source.last_seen_at,
                    ),
                )
                self.catalog.upsert_source_target(
                    SourceTargetInput(
                        backend="web",
                        locator=record.source.url,
                        priority=100,
                        enabled=True,
                    ),
                    source_id=catalog_record.source.id,
                )
                observed_external_ids.add(record.source.external_id)
                observed_count += 1
                self._append_duplicate_warnings(
                    target,
                    catalog_record,
                    warnings,
                    warning_keys,
                )

                if mode == "incremental":
                    stop_decision = adapter.incremental_stop_decision(
                        record,
                        previous,
                        target,
                    )
                    if stop_decision is IncrementalStopDecision.STOP:
                        return DiscoveryResult(
                            mode=mode,
                            target_key=target.key,
                            observed_count=observed_count,
                            new_count=new_count,
                            known_count=known_count,
                            complete=None,
                            stopped_reason="stable_boundary",
                            warnings=tuple(warnings),
                        )
                    if stop_decision is IncrementalStopDecision.CONTINUE:
                        continue
                if mode == "incremental" and known_streak >= _KNOWN_STREAK_LIMIT:
                    return DiscoveryResult(
                        mode=mode,
                        target_key=target.key,
                        observed_count=observed_count,
                        new_count=new_count,
                        known_count=known_count,
                        complete=None,
                        stopped_reason="known_streak",
                        warnings=tuple(warnings),
                    )
        except DiscoveryIncompleteError:
            return DiscoveryResult(
                mode=mode,
                target_key=target.key,
                observed_count=observed_count,
                new_count=new_count,
                known_count=known_count,
                complete=False if mode == "full" else None,
                stopped_reason="incomplete",
                warnings=tuple(warnings),
            )

        if mode == "full":
            self.catalog.mark_sources_unavailable_except(
                site=target.site,
                discovery_key=target.key,
                observed_external_ids=observed_external_ids,
            )
            complete: bool | None = True
        else:
            complete = None
        return DiscoveryResult(
            mode=mode,
            target_key=target.key,
            observed_count=observed_count,
            new_count=new_count,
            known_count=known_count,
            complete=complete,
            stopped_reason="exhausted",
            warnings=tuple(warnings),
        )

    @staticmethod
    def _validate_mode(mode: DiscoveryMode | str) -> DiscoveryMode:
        if mode not in _VALID_MODES:
            raise ValueError("Discovery mode must be one of: full, incremental")
        return mode  # type: ignore[return-value]

    def _append_duplicate_warnings(
        self,
        target: WatchlistTarget,
        current: CatalogRecord,
        warnings: list[str],
        warning_keys: set[tuple[int, str]],
    ) -> None:
        current_item = current.item
        current_title = self._normalize(current_item.canonical_title)
        if current_title is None:
            return
        current_order = self._item_order(current_item)
        for candidate in self.catalog.list_items():
            if candidate.id == current_item.id:
                continue
            if self._normalize(candidate.canonical_title) != current_title:
                continue
            if not self._optional_equal(current_item.kind, candidate.kind):
                continue
            if not self._optional_equal(current_order, self._item_order(candidate)):
                continue
            for candidate_source in self.catalog.list_sources(item_id=candidate.id):
                if candidate_source.site == target.site:
                    continue
                warning_key = (candidate.id, candidate_source.site)
                if warning_key in warning_keys:
                    continue
                warning_keys.add(warning_key)
                current_label = current_item.order_label or current_order or ""
                candidate_label = candidate.order_label or self._item_order(candidate) or ""
                warnings.append(
                    "Possible duplicate on another site:\n"
                    f"  current:  {target.site} / "
                    f"{current_item.canonical_title} / {current_label}\n"
                    f"  existing: {candidate_source.site} / "
                    f"{candidate.canonical_title} / {candidate_label}"
                )

    @staticmethod
    def _normalize(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = _WHITESPACE.sub(" ", value.strip()).casefold()
        return normalized or None

    @classmethod
    def _optional_equal(cls, left: str | None, right: str | None) -> bool:
        left_normalized = cls._normalize(left)
        right_normalized = cls._normalize(right)
        return (
            left_normalized is None
            or right_normalized is None
            or left_normalized == right_normalized
        )

    @staticmethod
    def _item_order(item: Item) -> str | None:
        return item.order_key or item.order_label
