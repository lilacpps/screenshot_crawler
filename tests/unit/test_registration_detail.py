from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from screenshot_crawler.catalog import CatalogService
from screenshot_crawler.cli import _discovery_registry
from screenshot_crawler.discovery.listing import ListingPreview, ListingRow, listing_digest
from screenshot_crawler.management.catalog_reader import CatalogInventoryReader
from screenshot_crawler.registration.detail import (
    accept_detail,
    detail_draft,
    member_patch,
    validate_detail,
)
from screenshot_crawler.registration.draft import BatchRegistrationDraft
from screenshot_crawler.registration.resolver import UrlResolver
from screenshot_crawler.watchlist.service import WatchlistService
from screenshot_crawler.watchlist.work_edit import validate_work_snapshot

URLS = {
    "jumpplus": "https://shonenjumpplus.com/episode/4",
    "comicdays": "https://comic-days.com/episode/4",
    "magapoke": "https://pocket.shonenmagazine.com/title/123/episode/4",
    "zeblack": "https://zebrack-comic.shueisha.co.jp/title/123/chapter/list",
    "piccoma": "https://piccoma.com/web/viewer/123/4",
}


def listing(target):
    identity = f"synthetic:{target.site}"
    rows = tuple(ListingRow(str(i), f"https://example.invalid/{target.site}/{i}", i,
        f"人工第{i}話", "unknown", identity) for i in range(4, 0, -1))
    return ListingPreview(target.site, target.key, target.url, identity, rows, True,
        datetime.now(UTC), listing_digest(identity, rows))


def setup_batch(tmp_path):
    path = tmp_path / "watchlist.yaml"
    path.write_text("targets: []\n", encoding="utf-8")
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    catalog.initialize()
    data = CatalogInventoryReader().read(catalog.path)
    base, revision = WatchlistService(path).read_snapshot()
    batch = BatchRegistrationDraft(base, revision, UrlResolver(_discovery_registry()), catalog_snapshot=data)
    return batch, path, catalog


def add(batch, site, name):
    url = URLS[site]
    row = batch.add_resolution(len(batch.candidates) + 1, url, batch.resolver.resolve(url))
    batch.edit_candidate(row, label="人工作品")
    batch.name_work(row, name)
    batch.confirm(row)
    return row


def detail(batch, group):
    request, draft = detail_draft(batch, group)
    for target in draft.members:
        draft.set_listing(listing(target))
    if len(draft.members) > 1:
        for order, target in enumerate(draft.members, 1):
            draft.update(replace(target, archive_order=order))
    result = validate_work_snapshot(draft, batch.catalog_snapshot, batch.revision)
    return request, draft, result


@pytest.mark.parametrize("site", URLS)
def test_supported_site_detail_is_immutable_no_write_and_one_work_only(tmp_path, site):
    batch, path, catalog = setup_batch(tmp_path)
    a = add(batch, site, "first")
    other = "comicdays" if site != "comicdays" else "jumpplus"
    b = add(batch, other, "second")
    before_row = batch.candidates[b]
    before = path.read_bytes(), catalog.path.read_bytes()
    request, draft, result = detail(batch, a)
    with pytest.raises(ValueError, match="全key"):
        accept_detail(batch, request, result, ())
    proof = accept_detail(batch, request, result, {target.key for target in draft.members})
    assert proof.members == draft.members
    assert batch.candidates[b] == before_row
    assert batch.works[b].detail is None
    assert before == (path.read_bytes(), catalog.path.read_bytes())
    assert validate_detail(batch, proof, batch.catalog_snapshot).work_key == "first"


def test_multiple_keys_require_detail_and_work_patch_preserves_other_draft(tmp_path):
    batch, _path, _catalog = setup_batch(tmp_path)
    a, b = add(batch, "jumpplus", "first"), add(batch, "comicdays", "second")
    batch.assign(b, group_id=a)
    batch.confirm(b)
    assert batch.readiness(a).status == "needs_scope"
    request, draft, result = detail(batch, a)
    proof = accept_detail(batch, request, result, {t.key for t in draft.members})
    assert batch.readiness(a).status == "ready"
    assert len(proof.members) == 2
    # Re-edit gets its own dictionaries/sets, not a shared mutable WorkDraft.
    _, child = detail_draft(batch, a)
    child.listings.clear()
    assert len(proof.listings) == 2


def test_edit_version_catalog_and_stale_listing_reject_without_mutation(tmp_path):
    batch, path, catalog = setup_batch(tmp_path)
    a = add(batch, "jumpplus", "work")
    request, draft, result = detail(batch, a)
    original = path.read_bytes(), catalog.path.read_bytes()
    stale = replace(result, listings=tuple(replace(x, observed_at=datetime.now(UTC) - timedelta(seconds=301))
        for x in result.listings))
    with pytest.raises(ValueError, match="古い"):
        accept_detail(batch, request, stale, {t.key for t in draft.members})
    batch.edit_candidate(a, label="Changed")
    with pytest.raises(ValueError, match="版"):
        accept_detail(batch, request, result, {t.key for t in draft.members})
    assert batch.works[a].detail is None
    assert original == (path.read_bytes(), catalog.path.read_bytes())


def test_member_patch_cannot_overwrite_another_work(tmp_path):
    batch, _path, _catalog = setup_batch(tmp_path)
    a, b = add(batch, "jumpplus", "first"), add(batch, "comicdays", "second")
    first, second = batch.targets_for(a)[0], batch.targets_for(b)[0]
    with pytest.raises(ValueError):
        member_patch((second,), first.work_key, (replace(first, key=second.key),))
    with pytest.raises(ValueError):
        member_patch((first,), first.work_key, ())


def test_existing_segment_layout_is_loaded_losslessly_and_remains_segment_mode(tmp_path):
    from screenshot_crawler.watchlist.models import ArchiveSegment, WatchlistTarget
    batch, path, _catalog = setup_batch(tmp_path)
    from screenshot_crawler.watchlist.models import DiscoveryScope
    old_a = WatchlistTarget("legacy_a", "work", "jumpplus", URLS["jumpplus"], "既存A", False,
        discovery_scope=DiscoveryScope("https://example.invalid/jumpplus/4", "https://example.invalid/jumpplus/1"),
        archive_segments=(ArchiveSegment(1, "1", "2"), ArchiveSegment(3, "3", "4")))
    old_b = WatchlistTarget("legacy_b", "work", "comicdays", URLS["comicdays"], "既存B",
        archive_segments=(ArchiveSegment(2),))
    service = WatchlistService(path)
    service.apply_edit((old_a, old_b))
    batch.base, batch.revision = service.read_snapshot()
    row = add(batch, "magapoke", "new")
    batch.assign(row, existing_work="work")
    batch.confirm(row)
    request, draft = detail_draft(batch, batch.candidates[row].group_id)
    assert draft.members[:2] == (old_a, old_b)
    for target in draft.members:
        draft.set_listing(listing(target))
    draft.apply_blocks(draft.blocks())
    result = validate_work_snapshot(draft, batch.catalog_snapshot, batch.revision)
    proof = accept_detail(batch, request, result, {target.key for target in draft.members})
    assert proof.members[0] == old_a
    assert proof.members[1] == old_b
    assert all(target.archive_order is None and target.archive_segments is not None for target in proof.members)
    assert service.list_targets() == [old_a, old_b]


def test_catalog_identity_and_changed_listing_proof_are_rejected(tmp_path):
    batch, _path, catalog = setup_batch(tmp_path)
    row = add(batch, "jumpplus", "work")
    request, draft, result = detail(batch, row)
    changed = replace(result, listings=(replace(result.listings[0], target_url="https://evil.test"),))
    with pytest.raises(ValueError, match="URL"):
        accept_detail(batch, request, changed, {target.key for target in draft.members})
    proof = accept_detail(batch, request, result, {target.key for target in draft.members})
    catalog.create_work(work_key="external_change", title="人工作品")
    with pytest.raises(ValueError, match="Catalog"):
        validate_detail(batch, proof, CatalogInventoryReader().read(catalog.path))
