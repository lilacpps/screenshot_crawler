"""Fail-closed validation for Watchlist exclusion IDs used by Batch."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable

from screenshot_crawler.catalog import CatalogService
from screenshot_crawler.catalog.models import Source
from screenshot_crawler.watchlist.fingerprints import target_scope_fingerprint
from screenshot_crawler.watchlist.models import WatchlistTarget


def unproven_target_exclusions(
    catalog: CatalogService,
    target: WatchlistTarget,
    sources: Iterable[Source],
) -> tuple[str, ...]:
    """Return exclusions not proven by an exact Source or current Full proof."""

    scope = target.discovery_scope
    if scope is None or not scope.excluded_external_ids:
        return ()
    known = {
        source.external_id
        for source in sources
        if source.site == target.site and source.discovery_key == target.key
    }
    unresolved = set(scope.excluded_external_ids) - known
    if not unresolved:
        return ()
    try:
        evidence = catalog.get_discovery_inventory_evidence(target.key)
    except Exception:  # noqa: BLE001 - unknown proof must fail closed
        return tuple(sorted(unresolved))
    if (
        evidence is None
        or evidence.site != target.site
        or evidence.target_url != target.url
        or evidence.scope_fingerprint != target_scope_fingerprint(target)
        or evidence.source_count != len(evidence.positions)
    ):
        return tuple(sorted(unresolved))
    ids = [position.external_id for position in evidence.positions]
    positions = [position.display_position for position in evidence.positions]
    digest_rows = [
        (position.external_id, position.display_position, position.in_scope)
        for position in sorted(
            evidence.positions,
            key=lambda item: (item.display_position, item.external_id),
        )
    ]
    actual_digest = hashlib.sha256(
        json.dumps(digest_rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if (
        len(ids) != len(set(ids))
        or len(positions) != len(set(positions))
        or evidence.inventory_digest != actual_digest
    ):
        return tuple(sorted(unresolved))
    return tuple(sorted(unresolved - set(ids)))
