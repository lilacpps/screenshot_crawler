from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from screenshot_crawler.discovery.listing import ListingPreview, ListingRow, listing_digest
from screenshot_crawler.watchlist.models import WatchlistTarget
from screenshot_crawler.watchlist.work_edit import (
    DraftBlock,
    WorkDraft,
    full_changed_keys,
    selected_rows,
)


def listing(target, count=10):
    identity = f"fixture:{target.site}"
    rows = tuple(ListingRow(str(number), f"https://example.invalid/{target.site}/{number}", number,
                            f"第{number}話", "free", identity)
                 for number in range(count, 0, -1))
    return ListingPreview(target.site, target.key, target.url, identity, rows, True,
                          datetime.now(UTC), listing_digest(identity, rows))


def draft_pair(*, existing_destination=False):
    a = WatchlistTarget("a", "work", "zeblack", "https://example.invalid/a", "Work")
    b = WatchlistTarget("b", "work", "jumpplus", "https://example.invalid/b", "Work")
    draft = WorkDraft((a, b) if existing_destination else (a,), "work")
    if not existing_destination:
        draft.add(b)
    for target in draft.members:
        draft.set_listing(listing(target))
    return draft


@pytest.mark.parametrize("first,last,dest_first,dest_last", [("5", "5", "5", "5"), ("5", "6", "5", "6"), ("5", "6", "4", "4")])
def test_replacement_inserts_into_original_position_and_preserves_open_tail(first, last, dest_first, dest_last):
    draft = draft_pair()
    assert draft.replace_range("a", first, last, "b", dest_first, dest_last) == (int(last) - int(first) + 1, int(dest_last) - int(dest_first) + 1)
    draft.validate()
    assert [block.key for block in draft.blocks()] == ["a", "b", "a"]
    assert draft.blocks()[-1].end_external_id is None
    assert set(draft.target("a").discovery_scope.excluded_external_ids) == {str(number) for number in range(int(first), int(last) + 1)}
    assert [row.external_id for row in selected_rows(draft.target("b"), draft.listings["b"])] == [str(number) for number in range(int(dest_first), int(dest_last) + 1)]
    assert draft.target("a").key == "a"


def test_repeated_replacements_and_all_replaced_key_keep_identity():
    draft = draft_pair()
    draft.replace_range("a", "3", "3", "b", "3", "3")
    draft.replace_range("a", "7", "8", "b", "7", "8")
    draft.validate()
    assert [block.key for block in draft.blocks()] == ["a", "b", "a", "b", "a"]
    assert draft.target("a").discovery_scope.excluded_external_ids == ("3", "7", "8")
    other = draft_pair()
    other.replace_range("a", "1", "10", "b", "1", "10")
    other.validate()
    assert other.target("a").archive_segments == ()
    assert selected_rows(other.target("a"), other.listings["a"]) == ()


def test_new_tail_inclusion_fixed_ranges_and_draft_rollback_on_invalid_change():
    draft = draft_pair()
    draft.set_range("a", None, "4")
    draft.set_range("b", "5", None)
    before = draft.targets
    with pytest.raises(ValueError, match="逆転"):
        draft.set_range("b", "8", "5")
    assert draft.targets == before
    draft.set_listing(listing(draft.target("b"), count=11))
    assert selected_rows(draft.target("b"), draft.listings["b"])[-1].external_id == "11"
    draft.set_range("b", "5", "10")
    assert selected_rows(draft.target("b"), draft.listings["b"])[-1].external_id == "10"


def test_overlap_missing_boundary_and_stale_proof_fail_without_mutation():
    draft = draft_pair()
    before = draft.targets
    with pytest.raises(ValueError, match="重複"):
        draft.apply_blocks([DraftBlock("a"), DraftBlock("a", "5", "6")])
    assert draft.targets == before
    with pytest.raises(ValueError, match="境界"):
        draft.set_range("a", "missing", None)
    draft.listings["a"] = replace(draft.listings["a"], observed_at=datetime.now(UTC) - timedelta(seconds=301))
    with pytest.raises(ValueError, match="古い"):
        draft.validate()


def test_full_targets_include_new_and_all_order_affected_siblings_but_not_label():
    draft = draft_pair()
    before = draft.targets[:1]
    assert full_changed_keys(before, draft.targets) == {"b"}
    assert not full_changed_keys(before, (replace(before[0], label="renamed"),))
    draft.replace_range("a", "5", "6", "b", "5", "6")
    assert full_changed_keys(before, draft.targets) == {"a", "b"}
