from dataclasses import replace

import pytest

from screenshot_crawler.catalog import CatalogService
from screenshot_crawler.gui.watchlist_editor import WatchlistEditorPage
from screenshot_crawler.gui.work_editor import WorkEditorDialog
from screenshot_crawler.management.catalog_reader import (
    CatalogInventoryReader,
    catalog_snapshot_identity,
)
from screenshot_crawler.management.inventory import InventoryService
from screenshot_crawler.watchlist.models import DiscoveryScope, WatchlistTarget
from screenshot_crawler.watchlist.service import WatchlistService
from screenshot_crawler.watchlist.work_edit import DraftBlock, WorkDraft
from tests.unit import test_gui_work_editor as gui_helpers
from tests.unit.test_listing_preview import sparse_listing

app = gui_helpers.app
wait_for = gui_helpers.wait_for


def setup(tmp_path):
    path, runtime = tmp_path / "watchlist.yaml", tmp_path / "runtime.yaml"
    runtime.write_text("{}\n", encoding="utf-8")
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    catalog.initialize()
    target = WatchlistTarget("native", "native-work", "kadocomi",
        "https://comic-walker.com/detail/KC_002911_S", "Synthetic")
    other = replace(target, key="other", work_key="other", label="Unchanged",
        site="mangaone", url="https://manga-one.com/manga/123/chapter/1")
    service = WatchlistService(path)
    service.apply_edit((target, other))
    listing = replace(sparse_listing(), site=target.site, target_key=target.key, target_url=target.url)
    snapshot = InventoryService().load(catalog.path, path, runtime_path=runtime)
    return path, runtime, catalog, target, other, listing, snapshot


@pytest.mark.parametrize("draft_only", [False, True])
def test_sparse_work_gui_saves_open_latest_scope_without_renumber_or_other_work_edit(app, tmp_path, draft_only):
    path, runtime, catalog, target, other, listing, snapshot = setup(tmp_path)
    service = WatchlistService(path)
    draft = WorkDraft(service.list_targets(), target.work_key)
    draft.set_listing(listing)
    options = {"draft": draft, "revision": service.revision(),
        "catalog_identity": catalog_snapshot_identity(CatalogInventoryReader().read(catalog.path))} if draft_only else {}
    editor = WorkEditorDialog(path, catalog.path, runtime, snapshot=snapshot, **options)
    if not draft_only:
        editor.draft = draft
        editor._render()
    before = path.read_bytes(), catalog.path.read_bytes()
    pane = editor.panes.widget(0)
    pane.oldest.setChecked(False)
    pane.first.setCurrentIndex(pane.first.findData("episode-3"))
    pane.latest.setChecked(True)
    pane.apply_range()
    expected = DiscoveryScope(through_url=listing.rows[1].url)
    assert editor.draft.target(target.key).discovery_scope == expected
    assert (path.read_bytes(), catalog.path.read_bytes()) == before
    old = editor.draft.targets
    with pytest.raises(ValueError, match="除外"):
        editor.draft.apply_blocks((DraftBlock(target.key, "episode-1", "episode-1"),
            DraftBlock(target.key, "episode-4", "episode-4")))
    assert editor.draft.targets == old
    if draft_only:
        editor.confirm_scope(target.key)
    editor.preview_edit()
    wait_for(lambda: editor.task is None)
    assert editor.preview is not None, editor.status.toPlainText()
    editor.save_edit()
    wait_for(lambda: editor.task is None)
    if draft_only:
        assert editor.draft_result[0].targets[0].discovery_scope == expected
        assert path.read_bytes() == before[0]
    else:
        assert service.get(target.key).discovery_scope == expected
    assert service.get(other.key) == other
    assert catalog.path.read_bytes() == before[1]
    assert [row.site_position for row in listing.rows] == [122, 121, 3, 1]


def test_legacy_key_editor_preserves_manual_through_only_on_sparse_listing(app, tmp_path):
    path, runtime, catalog, target, other, listing, snapshot = setup(tmp_path)
    editor = WatchlistEditorPage(path, catalog_path=catalog.path, runtime_path=runtime, snapshot=snapshot)
    editor.set_listing(listing, checked=tuple(row.external_id for row in listing.rows))
    editor.from_edit.clear()
    editor.through_edit.setText(listing.rows[1].url)
    # Read-only collection must preserve the user's open latest boundary.
    collected = editor._collect_targets()
    assert collected[0].discovery_scope == DiscoveryScope(through_url=listing.rows[1].url)
    assert collected[1] == other
    editor.preview_edit()
    wait_for(lambda: editor._preview_worker is None)
    assert editor._pending_preview.ready, editor.status.toPlainText()
    editor.save_edit()
    wait_for(lambda: editor._save_worker is None)
    assert WatchlistService(path).get(target.key).discovery_scope == DiscoveryScope(through_url=listing.rows[1].url)
    editor._dirty = False
    editor.close()
