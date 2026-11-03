"""Small opt-in helpers for buffered, read-only site listing observations."""
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic

from screenshot_crawler.discovery.listing import ListingPreview, ListingRow, listing_digest
from screenshot_crawler.discovery.models import DiscoveredRecord


def record_listing_preview(target, identity: str, records: list[DiscoveredRecord]) -> ListingPreview:
    from screenshot_crawler.discovery.service import DiscoveryIncompleteError

    rows = tuple(ListingRow(r.source.external_id, r.source.url,
        r.source.global_display_position, r.item.order_label or '',
        r.source.access_mode, identity) for r in records)
    if (not identity or not rows or len({r.external_id for r in rows}) != len(rows)
            or len({r.url for r in rows}) != len(rows)
            or any(not r.external_id or not r.url for r in rows)
            or any(type(r.site_position) is not int for r in rows)
            or [r.site_position for r in rows] != list(range(len(rows), 0, -1))):
        raise DiscoveryIncompleteError('Complete listing IDs, URLs or native positions are invalid')
    return ListingPreview(target.site, target.key, target.url, identity, rows,
        True, datetime.now(UTC), listing_digest(identity, rows))


@dataclass(frozen=True)
class PreparedListingReplay:
    page_id: int
    target: object
    expires_at: float
    identity: str
    records: tuple[DiscoveredRecord, ...]

    @classmethod
    def create(cls, page, target, preview, records):
        expected = record_listing_preview(target, preview.listing_identity, records)
        if (expected.rows != preview.rows or expected.digest != preview.digest or not preview.ready
                or (expected.site, expected.target_key, expected.target_url) != (
                    preview.site, preview.target_key, preview.target_url)):
            raise ValueError('Replay records do not match the complete preview')
        return cls(id(page), target, monotonic() + 30, preview.listing_identity, tuple(records))


def take_exclusion_replay(adapter, page, target, mode):
    """Consume once before any IO; normal Discovery remains the site's own path."""
    from screenshot_crawler.discovery.service import DiscoveryIncompleteError

    cached = getattr(adapter, '_prepared_listing_replay', None)
    adapter._prepared_listing_replay = None
    scope = target.discovery_scope
    if scope is None or not scope.excluded_external_ids:
        return None
    if (not isinstance(cached, PreparedListingReplay) or cached.page_id != id(page)
            or cached.target != target or monotonic() >= cached.expires_at):
        raise DiscoveryIncompleteError('Exclusions require a fresh same-Page complete listing replay')
    records = list(cached.records)
    urls = {r.source.url: index for index, r in enumerate(records)}
    start = urls.get(scope.from_url, -1) if scope.from_url else 0
    end = urls.get(scope.through_url, -1) if scope.through_url else len(records) - 1
    if start < 0 or end < start:
        raise DiscoveryIncompleteError('Exclusion boundaries are missing or reversed')
    selected = records[start:end + 1]
    if not set(scope.excluded_external_ids).issubset({r.source.external_id for r in selected}):
        raise DiscoveryIncompleteError('Excluded IDs are absent from the bounded complete listing')
    selected = [r for r in selected if r.source.external_id not in scope.excluded_external_ids]
    if mode == 'full':
        adapter.capture_complete_listing_inventory(target=target, all_records=records,
            selected_records=selected, listing_identity=cached.identity)
    return selected
