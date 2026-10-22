"""Prepare legacy-scope fixtures without weakening production Batch gates."""

from __future__ import annotations

import sqlite3
import uuid

from screenshot_crawler.batch import BatchPlanner
from screenshot_crawler.catalog import CatalogService
from screenshot_crawler.watchlist.reconcile import ScopeReconciler
from screenshot_crawler.watchlist.service import WatchlistService


def synchronized_legacy_watchlist(catalog: CatalogService) -> WatchlistService:
    """Bind every isolated fixture Source to an unbounded test Watchlist target.

    The helper is intentionally test-only. It writes only the Catalog path passed
    by the test, assigns deterministic test Discovery keys, and applies the
    explicit legacy bootstrap contract before a Batch planner is constructed.
    """

    works, items, sources, _targets = catalog.read_works_items_sources_and_targets()
    items_by_id = {item.id: item for item in items}
    works_by_id = {work.id: work for work in works}
    work_by_source: dict[int, tuple[int, str]] = {}
    for source in sources:
        item = items_by_id[source.item_id]
        work = works_by_id[item.work_id]
        work_by_source[source.id] = (work.id, work.work_key)

    assigned: dict[int, str] = {}
    key_owners: dict[str, tuple[int, str]] = {}
    for source in sources:
        owner = (work_by_source[source.id][0], source.site)
        key = source.discovery_key
        if key is None or (key in key_owners and key_owners[key] != owner):
            key = f"test_legacy_work_{owner[0]}_{source.site}"
            if key in key_owners and key_owners[key] != owner:
                key = f"{key}_source_{source.id}"
        key_owners[key] = owner
        assigned[source.id] = key

    if sources:
        source_by_id = {source.id: source for source in sources}
        with sqlite3.connect(catalog.path) as connection:
            connection.executemany(
                "UPDATE sources SET discovery_key = ? WHERE id = ?",
                [
                    (key, source_id)
                    for source_id, key in assigned.items()
                    if source_by_id[source_id].discovery_key != key
                ],
            )

    watchlist = WatchlistService(
        catalog.path.parent / f"test-watchlist-{uuid.uuid4().hex}.yaml"
    )
    targets: dict[str, tuple[int, str, str]] = {}
    for source in sources:
        work_id, work_key = work_by_source[source.id]
        key = assigned[source.id]
        owner = (work_id, source.site, work_key)
        existing = targets.get(key)
        if existing is not None and existing != owner:
            raise AssertionError(f"Test fixture Watchlist key collision: {key}")
        targets[key] = owner

    for key, (work_id, site, work_key) in targets.items():
        watchlist.add(
            key=key,
            work_key=work_key,
            site=site,
            url=f"https://example.invalid/test/{work_id}/{site}",
            label=f"Test Work {work_id}",
        )
    if sources:
        reconciler = ScopeReconciler(watchlist, catalog)
        for work_key in sorted({value[1] for value in work_by_source.values()}):
            reconciler.apply(reconciler.preview(work_key))
    return watchlist


def synchronized_legacy_planner(catalog: CatalogService, policies) -> BatchPlanner:
    """Construct a planner after explicit test-only legacy scope bootstrap."""

    return BatchPlanner(
        catalog, policies, watchlist=synchronized_legacy_watchlist(catalog)
    )
