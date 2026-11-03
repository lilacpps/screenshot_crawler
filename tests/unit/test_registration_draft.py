from dataclasses import replace

import pytest

from screenshot_crawler.cli import _discovery_registry
from screenshot_crawler.registration.draft import BatchRegistrationDraft
from screenshot_crawler.registration.naming import available_name, slug, suggest_name
from screenshot_crawler.registration.resolver import UrlResolver
from screenshot_crawler.watchlist.models import WatchlistTarget

A = "https://shonenjumpplus.com/episode/123"
B = "https://comic-days.com/episode/456"
K = "https://comic-walker.com/detail/KC_004915_S"


def draft(base=()):
    return BatchRegistrationDraft(tuple(base), "revision", UrlResolver(_discovery_registry()))


def add(batch, url, title=None):
    result = batch.resolver.resolve(url)
    if title:
        result = replace(result, title=title)
    return batch.add_resolution(len(batch.candidates) + 1, url, result)


def ready(batch, row_id, name="test_work"):
    batch.edit_candidate(row_id, label="人工作品")
    batch.name_work(batch.candidates[row_id].group_id, name)
    batch.confirm(row_id)


def test_unknown_identity_and_title_can_be_explicitly_confirmed():
    batch = draft()
    row = add(batch, A)
    assert batch.readiness(row).status == "needs_manual_confirmation"
    ready(batch, row)
    assert batch.readiness(row).status == "ready"
    assert batch.candidates[row].resolution.site_work_identity is None
    assert batch.candidates[row].resolution.title is None
    assert batch.targets_for(row)[0].discovery_scope is None


def test_blocked_url_never_bypassed():
    batch = draft()
    row = add(batch, "https://evil.test/123")
    batch.edit_candidate(row, label="Work", key="work_key")
    batch.name_work(row, "work")
    with pytest.raises(ValueError, match="URL"):
        batch.confirm(row)
    assert batch.readiness(row).status == "blocked"


def test_verified_identity_deduplicates_first_seed_and_preserves_inputs():
    batch = draft()
    url = "https://pocket.shonenmagazine.com/title/01539/episode/1"
    row = add(batch, url)
    assert add(batch, url[:-1] + "2") == row
    assert len(batch.candidates) == 1
    assert len(batch.candidates[row].origins) == 2
    assert batch.candidates[row].resolution.discovery_url == url


def test_unknown_identity_does_not_dedupe_episodes_or_cross_site_titles():
    batch = draft()
    a, b, c = add(batch, A, "Same"), add(batch, A[:-3] + "456", "Same"), add(batch, B, "Same")
    assert len({a, b, c}) == 3
    assert len(batch.works) == 3
    assert {work.work_key for work in batch.works.values()} == {"same", "same_2", "same_3"}
    batch.assign(c, group_id=a)
    assert batch.candidates[c].group_id == a
    assert batch.candidates[b].group_id == b


def test_manual_key_survives_work_rename_and_retry():
    batch = draft()
    a = add(batch, A, "First")
    b = add(batch, B, "Second")
    batch.edit_candidate(a, key="custom_key")
    batch.assign(b, group_id=a)
    batch.name_work(a, "renamed")
    assert batch.candidates[a].key == "custom_key"
    assert batch.candidates[b].key == "renamed_comicdays"
    batch.confirm(a)
    batch.works[a].detail = object()
    batch.retry(a, batch.resolver.resolve(A))
    assert batch.candidates[a].key == "custom_key" and not batch.candidates[a].confirmed
    assert batch.works[a].detail is None
    assert batch.candidates[b].group_id == a


def test_existing_work_inherits_stable_id_and_preserves_all_fields():
    from screenshot_crawler.watchlist.models import ArchiveSegment, DiscoveryScope
    old = WatchlistTarget("legacy-key", "legacy-work", "jumpplus", A, "Same", False,
        DiscoveryScope(A, A, ()), None, (ArchiveSegment(1),))
    batch = draft((old,))
    row = add(batch, B, "Same")
    assert batch.title_hints(row) == (("legacy-work", "Same"),)
    assert not batch.works[row].existing
    batch.assign(row, existing_work="legacy-work")
    group_id = batch.candidates[row].group_id
    with pytest.raises(ValueError, match="work_key"):
        batch.name_work(group_id, "renamed")
    batch.confirm(row)
    assert batch.targets_for(group_id)[0] == old
    assert batch.readiness(group_id).status == "needs_scope"
    assert batch.base == (old,)


def test_registered_match_is_unselected_and_requires_explicit_additional_key():
    old = WatchlistTarget("old", "work", "kadocomi", K, "Work")
    batch = draft((old,))
    row = add(batch, K, "Work")
    assert batch.candidates[row].existing_keys == ("old",)
    assert not batch.works[row].selected
    with pytest.raises(ValueError, match="登録済み"):
        batch.confirm(row)
    batch.assign(row, existing_work="work")
    batch.confirm(row, additional=True)
    group = batch.candidates[row].group_id
    assert batch.readiness(group).status == "needs_scope"  # Supported; explicit detail proof is still required.


@pytest.mark.parametrize("url", [A, B])
def test_edit_invalidates_human_confirmation(url):
    batch = draft()
    row = add(batch, url)
    ready(batch, row)
    batch.edit_candidate(row, label="Changed")
    assert batch.readiness(row).status == "needs_manual_confirmation"
    batch.select(row, False)
    assert batch.candidates[row].label == "Changed"
    batch.select(row, True)
    assert batch.candidates[row].label == "Changed"


def test_new_group_slug_collision_is_not_merge():
    batch = draft()
    a, b = add(batch, A), add(batch, B)
    ready(batch, a)
    ready(batch, b)
    assert len(batch.works) == 2
    assert batch.readiness(a).status == "blocked"
    batch.name_work(b, "other")
    batch.confirm(b)
    assert batch.readiness(a).status == batch.readiness(b).status == "ready"


def test_names_are_suggestions_with_no_hash_fallback():
    assert slug(" Foo　BAR! 12 ") == "foo_bar_12"
    assert slug("漢字ABC") == ""
    assert suggest_name("Hello World").work_key == "hello_world"
    pytest.importorskip("pykakasi")
    suggestion = suggest_name("かな漢字")
    assert suggestion.work_key == "kana_kanji"
    assert suggestion.reading == "かなかんじ"
    assert "human confirmation" in suggestion.evidence
    assert available_name("work_jumpplus", {"work_jumpplus", "work_jumpplus_2"}) == "work_jumpplus_3"


@pytest.mark.parametrize("change", ["retry", "edit", "rename", "assign"])
def test_all_confirmation_evidence_invalidates(change):
    batch = draft()
    row = add(batch, A, "Work")
    batch.confirm(row, additional=True)
    assert batch.candidates[row].additional
    if change == "retry":
        batch.retry(row, batch.resolver.resolve(B))
        assert batch.candidates[row].key == "work_comicdays"
    elif change == "edit":
        batch.edit_candidate(row, label="Changed")
    elif change == "rename":
        batch.name_work(row, "changed")
    else:
        other = add(batch, B, "Other")
        batch.assign(row, group_id=other)
    assert not batch.candidates[row].additional
    assert not batch.candidates[row].confirmed


@pytest.mark.parametrize("source_url,owner_key", [("https://legacy.invalid/source", None),
    ("https://shonenjumpplus.com/episode/123?legacy=1", "removed_key"), (A, None)])
def test_unresolved_catalog_owner_blocks_without_write(source_url, owner_key):
    from types import SimpleNamespace as NS
    batch = draft()
    row = add(batch, A)
    ready(batch, row)
    batch.catalog_snapshot = NS(works=(NS(id=1, work_key="other"),), items=(NS(id=1, work_id=1),),
        sources=(NS(id=1, item_id=1, site="jumpplus", discovery_key=owner_key,
            acquisition_enabled=True),), targets=(NS(source_id=1, backend="web", locator=source_url),))
    assert batch.readiness(row).status == "blocked"
