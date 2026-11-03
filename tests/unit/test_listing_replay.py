from dataclasses import replace
from types import SimpleNamespace

import pytest

from screenshot_crawler.discovery.listing_replay import (
    PreparedListingReplay,
    record_listing_preview,
    take_exclusion_replay,
)
from screenshot_crawler.discovery.models import DiscoveredItem, DiscoveredRecord, DiscoveredSource
from screenshot_crawler.discovery.service import DiscoveryIncompleteError
from screenshot_crawler.watchlist.models import DiscoveryScope, WatchlistTarget


def observation():
    target = WatchlistTarget('key', 'work', 'fixture', 'https://example.invalid/work', 'Fixture',
        discovery_scope=DiscoveryScope(excluded_external_ids=('3',)))
    records = [DiscoveredRecord(DiscoveredItem('Fixture', kind='episode', order_label=str(i)),
        DiscoveredSource(str(i), f'https://example.invalid/{i}', 'unknown', global_display_position=i))
        for i in range(4, 0, -1)]
    return target, records


@pytest.mark.parametrize('fault', ['duplicate_id', 'duplicate_url', 'gap', 'reverse', 'bool', 'empty'])
def test_preview_projection_rejects_ambiguous_native_inventory(fault):
    target, records = observation()
    if fault == 'empty':
        records = []
    elif fault == 'reverse':
        records.reverse()
    else:
        values = {'duplicate_id': {'external_id': '4'}, 'duplicate_url': {'url': records[0].source.url},
                  'gap': {'global_display_position': 8}, 'bool': {'global_display_position': True}}[fault]
        records[-1] = replace(records[-1], source=replace(records[-1].source, **values))
    with pytest.raises(DiscoveryIncompleteError):
        record_listing_preview(target, 'native-work:1', records)


@pytest.mark.parametrize('field,value', [('site', 'foreign'), ('target_key', 'other'),
    ('target_url', 'https://foreign.invalid/'), ('digest', 'bad'), ('complete', False)])
def test_replay_preparation_binds_the_preview_target_and_digest(field, value):
    target, records = observation()
    preview = record_listing_preview(target, 'native-work:1', records)
    with pytest.raises(ValueError):
        PreparedListingReplay.create(object(), target, replace(preview, **{field: value}), records)


def test_exclusion_replay_is_one_shot_and_preserves_inventory_positions():
    target, records = observation()
    page = object()
    preview = record_listing_preview(target, 'native-work:1', records)
    calls = []
    adapter = SimpleNamespace(_prepared_listing_replay=PreparedListingReplay.create(page, target, preview, records),
        capture_complete_listing_inventory=lambda **kwargs: calls.append(kwargs))
    selected = take_exclusion_replay(adapter, page, target, 'full')
    assert [r.source.external_id for r in selected] == ['4', '2', '1']
    assert calls[0]['all_records'] == records and calls[0]['selected_records'] == selected
    assert [r.source.global_display_position for r in selected] == [4, 2, 1]
    with pytest.raises(DiscoveryIncompleteError, match='fresh same-Page'):
        take_exclusion_replay(adapter, page, target, 'full')


@pytest.mark.parametrize('fault', ['page', 'stale', 'key', 'work_key', 'url', 'scope'])
def test_replay_identity_ttl_and_scope_cannot_be_substituted(fault, monkeypatch):
    target, records = observation()
    page = object()
    preview = record_listing_preview(target, 'native-work:1', records)
    cached = PreparedListingReplay.create(page, target, preview, records)
    adapter = SimpleNamespace(_prepared_listing_replay=cached)
    if fault == 'page':
        page = object()
    elif fault == 'stale':
        monkeypatch.setattr('screenshot_crawler.discovery.listing_replay.monotonic', lambda: cached.expires_at)
    else:
        value = DiscoveryScope(excluded_external_ids=('2',)) if fault == 'scope' else 'changed'
        target = replace(target, **{'discovery_scope' if fault == 'scope' else fault: value})
    with pytest.raises(DiscoveryIncompleteError, match='fresh same-Page'):
        take_exclusion_replay(adapter, page, target, 'full')
    assert adapter._prepared_listing_replay is None


@pytest.mark.parametrize('scope', [
    DiscoveryScope(excluded_external_ids=('missing',)),
    DiscoveryScope('https://example.invalid/3', 'https://example.invalid/2', ('1',)),
    DiscoveryScope('https://example.invalid/1', 'https://example.invalid/4', ('2',)),
    DiscoveryScope('https://foreign.invalid/3', None, ('2',)),
])
def test_replay_rechecks_range_and_excluded_identity(scope):
    target, records = observation()
    target = replace(target, discovery_scope=scope)
    page = object()
    preview = record_listing_preview(target, 'native-work:1', records)
    adapter = SimpleNamespace(_prepared_listing_replay=PreparedListingReplay.create(page, target, preview, records))
    with pytest.raises(DiscoveryIncompleteError):
        take_exclusion_replay(adapter, page, target, 'full')
