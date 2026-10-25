import asyncio
import hashlib
import os
import sqlite3
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from screenshot_crawler.batch import BatchPlanner
from screenshot_crawler.catalog import (
    ArtifactInput,
    CatalogService,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)
from screenshot_crawler.discovery import (
    DiscoveredItem,
    DiscoveredRecord,
    DiscoveredSource,
    DiscoveryAdapter,
    DiscoveryAdapterRegistry,
    DiscoveryService,
)
from screenshot_crawler.discovery.listing import ListingPreview, ListingRow, listing_digest
from screenshot_crawler.gui.watchlist_editor import WatchlistEditorPage
from screenshot_crawler.management.inventory import InventoryService
from screenshot_crawler.site_policies import MagapokeSitePolicy, SitePolicyRegistry
from screenshot_crawler.watchlist.models import DiscoveryScope, WatchlistTarget
from screenshot_crawler.watchlist.service import WatchlistService


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


@pytest.fixture(autouse=True)
def dispose_editors(qt_app):
    yield
    from PySide6.QtCore import QCoreApplication, QEvent
    for widget in QApplication.topLevelWidgets():
        if isinstance(widget, WatchlistEditorPage):
            widget.thread_pool.waitForDone(10000)
            QApplication.processEvents()
            widget._dirty = False
            widget.close()
            widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _wait(predicate, editor=None):
    end = time.monotonic() + 10
    while time.monotonic() < end:
        QApplication.processEvents()
        if predicate():
            return
        time.sleep(0.01)  # Give QRunnables the GIL; QTest.qWait can starve them.
    pytest.fail(editor.status.toPlainText() if editor else "Qt operation timed out")


def _catalog_editor(tmp_path):
    path = tmp_path / "watchlist.yaml"
    _watchlist(path)
    runtime = tmp_path / "runtime.yaml"
    runtime.write_text("sites: {}\n", encoding="utf-8")
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key="work", title="Work"))
    for number in (3, 2, 1):
        item = catalog.create_item(ItemInput(item_title=f"Episode {number}"), work_id=work.id)
        source = catalog.create_source(SourceInput(
            site="magapoke", external_id=f"episode-{number}", discovery_key="one",
            access_mode="free", available=True, display_position=number,
        ), item_id=item.id)
        catalog.create_source_target(SourceTargetInput(backend="web", locator=f"https://example.invalid/{number}"), source_id=source.id)
    snapshot = InventoryService().load(catalog.path, path, runtime_path=runtime)
    editor = WatchlistEditorPage(path, catalog_path=catalog.path, runtime_path=runtime, snapshot=snapshot)
    editor.set_listing(_listing(), checked=("episode-1", "episode-2", "episode-3"))
    return editor, catalog


def _preview_hole(editor):
    editor.scope_model.setData(editor.scope_model.index(1, 0), Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    editor.preview_button.click()
    _wait(lambda: editor._preview_worker is None, editor)
    assert editor._pending_preview.ready, editor.status.toPlainText()


def _watchlist(path: Path) -> None:
    WatchlistService(path).add(
        key="one",
        work_key="work",
        site="magapoke",
        url="https://example.invalid/work",
        label="One",
        archive_order=1,
    )


def _listing() -> ListingPreview:
    rows = tuple(
        ListingRow(
            f"episode-{number}",
            f"https://example.invalid/{number}",
            number,
            f"Episode {number}",
            "free",
            "fixture",
        )
        for number in (3, 2, 1)
    )
    return ListingPreview(
        site="magapoke",
        target_key="one",
        target_url="https://example.invalid/work",
        listing_identity="fixture",
        rows=rows,
        complete=True,
        observed_at=datetime.now(UTC),
        digest=listing_digest("fixture", rows),
    )


def test_editor_preview_is_read_only_and_checkbox_state_is_independent(qt_app, tmp_path: Path) -> None:
    editor, catalog = _catalog_editor(tmp_path)
    before_yaml, before_catalog = editor.watchlist_path.read_bytes(), catalog.path.read_bytes()
    execution_selection = editor.inventory_model.selected_keys
    _preview_hole(editor)
    assert editor.watchlist_path.read_bytes() == before_yaml
    assert catalog.path.read_bytes() == before_catalog
    assert editor.inventory_model.selected_keys == execution_selection
    assert editor.targets[0].discovery_scope is None


def test_editor_save_requires_preview_and_combines_scope_edit(qt_app, tmp_path: Path) -> None:
    editor, _ = _catalog_editor(tmp_path)
    editor.label_edit.setText("Updated")
    assert editor.save_edit() is None
    _preview_hole(editor)
    editor.save_button.click()
    _wait(lambda: editor._save_worker is None, editor)
    saved = WatchlistService(editor.watchlist_path).get("one")
    assert saved.label == "Updated", editor.status.toPlainText()
    assert saved.discovery_scope.from_url.endswith("/3")
    assert saved.discovery_scope.through_url.endswith("/1")
    assert saved.discovery_scope.excluded_external_ids == ("episode-2",)
    assert not editor._dirty


def test_editor_full_signal_does_not_change_inventory_selection(qt_app, tmp_path: Path) -> None:
    path = tmp_path / "watchlist.yaml"
    _watchlist(path)
    editor = WatchlistEditorPage(path)
    received: list[str] = []
    editor.fullRequested.connect(received.append)
    editor.request_full()
    assert received == ["one"]
    editor.close()


def test_scope_table_renders_listing_dto_and_bulk_selection(qt_app, tmp_path: Path) -> None:
    path = tmp_path / "watchlist.yaml"
    _watchlist(path)
    editor = WatchlistEditorPage(path)
    editor.set_listing(_listing(), checked=("episode-3",))
    model = editor.scope_model
    values = [model.data(model.index(0, column), Qt.ItemDataRole.DisplayRole) for column in range(model.columnCount())]
    assert values[1] == "episode-3"
    assert values[3] == "Episode 3"
    assert values[5] == "free"
    editor.select_all_button.click()
    assert model.checked == {"episode-1", "episode-2", "episode-3"}
    editor.clear_all_button.click()
    assert model.checked == set()
    editor._dirty = False
    editor.close()


def test_manual_boundaries_use_complete_listing_for_scope_preview(qt_app, tmp_path: Path) -> None:
    path = tmp_path / "watchlist.yaml"
    _watchlist(path)
    editor = WatchlistEditorPage(path)
    editor.set_listing(_listing(), checked=("episode-3", "episode-2", "episode-1"))
    editor.from_edit.setText("https://example.invalid/3")
    editor.through_edit.setText("https://example.invalid/1")
    proposed = editor._collect_targets()
    assert proposed[0].discovery_scope is None
    assert editor._draft_checked_ids == {"episode-1", "episode-2", "episode-3"}
    editor._dirty = False
    editor.close()


def test_sibling_evidence_proves_unbounded_and_exclusion_only_scopes(qt_app, tmp_path: Path) -> None:
    path = tmp_path / "watchlist.yaml"
    _watchlist(path)
    editor = WatchlistEditorPage(path)
    editor.set_listing(_listing(), checked=("episode-1",))
    sibling = WatchlistTarget(
        key="sibling", work_key="work", site="magapoke",
        url="https://example.invalid/work", label="Sibling",
        discovery_scope=DiscoveryScope(excluded_external_ids=("episode-2",)),
    )
    listings, checked = editor._sibling_listing_evidence((editor._selected_target(), sibling))
    assert set(listings) == {"sibling"}
    assert checked["sibling"] == {"episode-1", "episode-3"}
    editor._dirty = False
    editor.close()


@pytest.mark.parametrize("scope,expected", [
    (None, {"episode-1", "episode-2", "episode-3"}),
    (DiscoveryScope(from_url="https://example.invalid/2"), {"episode-1", "episode-2"}),
    (DiscoveryScope(through_url="https://example.invalid/2"), {"episode-3", "episode-2"}),
    (DiscoveryScope(excluded_external_ids=("episode-2",)), {"episode-1", "episode-3"}),
])
def test_first_listing_callback_initializes_exact_saved_selection(qt_app, tmp_path, scope, expected):
    path = tmp_path / "watchlist.yaml"
    _watchlist(path)
    service = WatchlistService(path)
    service.update_target("one", discovery_scope=scope)
    editor = WatchlistEditorPage(path)
    editor._listing_succeeded((editor._generation, _listing()))
    assert editor.scope_model.checked == expected
    assert not editor._dirty


def test_manual_boundaries_reach_real_catalog_preview(qt_app, tmp_path):
    editor, catalog = _catalog_editor(tmp_path)
    before = catalog.path.read_bytes()
    editor.from_edit.setText("https://example.invalid/2")
    editor.through_edit.setText("https://example.invalid/1")
    editor.preview_button.click()
    _wait(lambda: editor._preview_worker is None, editor)
    assert editor.scope_edit_preview.ready, editor.status.toPlainText()
    assert editor.scope_edit_preview.selected_count == 2
    assert editor.scope_edit_preview.proposed_target.discovery_scope.from_url.endswith("/2")
    assert catalog.path.read_bytes() == before


@pytest.mark.parametrize("kind", ["watchlist", "catalog", "latest_run"])
def test_save_rejects_changed_inputs_even_when_catalog_stat_is_unchanged(qt_app, tmp_path, kind):
    editor, catalog = _catalog_editor(tmp_path)
    _preview_hole(editor)
    before = editor.watchlist_path.read_bytes()
    if kind == "watchlist":
        editor.watchlist_path.write_bytes(before + b"# external edit\n")
    else:
        stat = catalog.path.stat()
        if kind == "latest_run":
            source = catalog.find_source("magapoke", "episode-1")
            target = catalog.list_source_targets(source_id=source.id)[0]
            catalog.create_crawl_run(item_id=source.item_id, source_id=source.id, target_id=target.id, access_strategy="direct")
        else:
            with sqlite3.connect(catalog.path) as connection:
                connection.execute("UPDATE items SET item_title='Changed' WHERE id=1")
        os.utime(catalog.path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        assert catalog.path.stat().st_size == stat.st_size
    expected = editor.watchlist_path.read_bytes()
    editor.save_button.click()
    _wait(lambda: editor._save_worker is None, editor)
    assert editor.watchlist_path.read_bytes() == expected
    assert editor._dirty
    assert "changed" in editor.status.toPlainText().lower() or "revision" in editor.status.toPlainText().lower()


def test_archive_reorder_preserves_baseline_and_dirty_discard(qt_app, tmp_path, monkeypatch):
    editor, catalog = _catalog_editor(tmp_path)
    service = WatchlistService(editor.watchlist_path)
    service.add(key="two", work_key="work", site="mangaone", url="https://example.invalid/two", label="Two", archive_order=2)
    editor.reload()
    _wait(lambda: editor._reload_worker is None, editor)
    assert editor.inventory_model.snapshot is editor.snapshot
    assert "two" in {row.identity for row in editor.snapshot.keys}
    before = editor.targets
    editor.label_edit.setText("Draft")
    editor._move_archive_order(1)
    assert editor.targets == before
    assert editor.label_edit.text() == "Draft"
    assert editor.order_edit.text() == "2"
    assert editor._selection_affecting_change(editor._collect_targets())
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Cancel)
    editor.target_combo.setCurrentIndex(1)
    assert editor.target_combo.currentData() == "one"
    assert editor.label_edit.text() == "Draft"
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Discard)
    editor.target_combo.setCurrentIndex(1)
    assert editor.target_combo.currentData() == "two"
    assert tuple(editor.target_model.targets) == before
    assert not editor._dirty
    assert catalog.path.is_file()


def test_snapshot_refresh_drops_inflight_preview(qt_app, tmp_path, monkeypatch):
    editor, catalog = _catalog_editor(tmp_path)
    workers = []
    monkeypatch.setattr(editor.thread_pool, "start", workers.append)
    editor.scope_model.setData(editor.scope_model.index(1, 0), Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    editor.preview_edit()
    assert editor._preview_worker is workers[0]
    editor.receive_snapshot(editor.snapshot)
    workers[0].run()
    QApplication.processEvents()
    assert editor._preview_worker is None
    assert editor.scope_edit_preview is None
    assert editor._pending_preview is None
    assert catalog.path.is_file()


def test_snapshot_refresh_drops_inflight_scope_preview(qt_app, tmp_path, monkeypatch):
    editor, _ = _catalog_editor(tmp_path)
    workers = []
    monkeypatch.setattr(editor.thread_pool, "start", workers.append)
    editor.preview_scope_sync()
    editor.receive_snapshot(editor.snapshot)
    workers[0].run()
    QApplication.processEvents()
    assert editor._scope_worker is None
    assert editor._last_scope_preview is None
    assert editor._scope_preview_revision is None
    assert not editor.apply_scope_sync(confirm=True)


def test_active_job_blocks_edits_and_dirty_full(qt_app, tmp_path):
    editor, _ = _catalog_editor(tmp_path)
    received = []
    editor.fullRequested.connect(received.append)
    editor.label_edit.setText("Draft")
    editor.request_full()
    assert received == []
    before = editor.watchlist_path.read_bytes()
    editor.set_active_job(True)
    assert not editor.label_edit.isEnabled()
    assert not editor.save_button.isEnabled()
    editor.save_edit()
    assert editor.watchlist_path.read_bytes() == before
    editor.set_active_job(False)
    assert editor.label_edit.isEnabled()


def test_unsupported_listing_never_connects_to_browser(qt_app, tmp_path, monkeypatch):
    from screenshot_crawler.core.browser import BrowserSession
    from screenshot_crawler.gui.watchlist_editor import _ListingWorker
    called = []

    async def forbidden(*args, **kwargs):
        called.append(True)
        raise AssertionError("Unsupported listing must not connect")

    monkeypatch.setattr(BrowserSession, "connect", forbidden)
    target = WatchlistTarget("unsupported", "work", "bookwalker", "https://example.invalid/reader", "Unsupported")
    worker = _ListingWorker(target)
    errors = []
    worker.signals.failed.connect(errors.append)
    worker.run()
    assert called == []
    assert errors and "does not support" in errors[0]


@pytest.mark.parametrize("page_failure", [False, True])
def test_supported_listing_worker_connects_closes_and_delivers_dto(qt_app, tmp_path, monkeypatch, page_failure):
    from screenshot_crawler import cli
    from screenshot_crawler.core.browser import BrowserSession
    from screenshot_crawler.gui.watchlist_editor import _ListingWorker
    events = []

    class Adapter(_SyntheticFullAdapter):
        async def preview_complete_listing(self, page, target):
            events.append("listing")
            return _listing()

    class Session:
        async def new_page(self):
            events.append("page")
            if page_failure:
                raise RuntimeError("synthetic new-page failure")
            return object()

        async def close_page(self, page):
            events.append("close_page")

        async def close(self):
            events.append("close")

    async def connect(*args, **kwargs):
        events.append("connect")
        return Session()

    registry = DiscoveryAdapterRegistry()
    registry.register("magapoke", Adapter)
    monkeypatch.setattr(cli, "_discovery_registry", lambda: registry)
    monkeypatch.setattr(BrowserSession, "connect", connect)
    path = tmp_path / "watchlist.yaml"
    _watchlist(path)
    worker = _ListingWorker(WatchlistService(path).get("one"), 7)
    received, errors = [], []
    worker.signals.succeeded.connect(received.append)
    worker.signals.failed.connect(errors.append)
    worker.run()
    if page_failure:
        assert errors == ["synthetic new-page failure"]
        assert events == ["connect", "page", "close"]
        return
    assert not errors
    assert received[0][0] == 7
    assert received[0][1].ready
    assert events == ["connect", "page", "listing", "close_page", "close"]


def test_gui_blocks_overlapping_sibling_before_catalog_sources_exist(qt_app, tmp_path):
    path = tmp_path / "watchlist.yaml"
    _watchlist(path)
    service = WatchlistService(path)
    service.add(key="sibling", work_key="work", site="magapoke", url="https://example.invalid/work", label="Sibling", archive_order=2)
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    catalog.create_work(WorkInput(work_key="work", title="Work"))
    editor = WatchlistEditorPage(path, catalog_path=catalog.path)
    editor.set_listing(_listing(), checked=("episode-1", "episode-2", "episode-3"))
    editor.scope_model.setData(editor.scope_model.index(1, 0), Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    before = path.read_bytes(), catalog.path.read_bytes()
    editor.preview_edit()
    _wait(lambda: editor._preview_worker is None, editor)
    assert any("overlap" in value for value in editor.scope_edit_preview.blockers)
    assert not editor._pending_preview.ready
    editor.save_edit()
    assert (path.read_bytes(), catalog.path.read_bytes()) == before


def test_main_window_new_key_full_and_reopen_preserve_execution_checks(qt_app, tmp_path, monkeypatch):
    from screenshot_crawler.gui.main_window import MainWindow
    editor, catalog = _catalog_editor(tmp_path)
    editor._dirty = False
    editor.close()
    window = MainWindow(catalog.path, editor.watchlist_path, editor.runtime_path,
                        management_path=tmp_path / "management.sqlite", auto_load=False)
    window.set_snapshot(editor.snapshot)
    window.model.set_checked_keys({"one"})
    window._open_watchlist_editor()
    original = window._watchlist_editor
    original.close()
    window._open_watchlist_editor()
    assert window._watchlist_editor is not original
    assert not window._watchlist_editor._closed
    target = WatchlistService(editor.watchlist_path).add(key="new", work_key="new", site="magapoke", url="https://example.invalid/new", label="New")
    calls = []
    monkeypatch.setattr(window, "_show_execution_preview", lambda action, **kwargs: calls.append((action, kwargs)))
    window._run_editor_full(target.key)
    _wait(lambda: bool(calls))
    assert calls == [("discover", {"selected_keys": {"new"}, "force_full": True})]
    assert window.model.selected_keys == {"one"}
    window.close()


class _SyntheticFullAdapter(DiscoveryAdapter):
    supports_bounded_discovery = True
    supports_exclusion_replay = True

    async def prepare_exclusion_preview(self, page, target):
        return _listing()

    async def iter_records(self, page, target, mode):
        records = [DiscoveredRecord(
            item=DiscoveredItem(canonical_title=row.display_title),
            source=DiscoveredSource(external_id=row.external_id, url=row.url,
                                    access_mode="free", available=True, global_display_position=row.site_position),
        ) for row in _listing().rows]
        excluded = set(target.discovery_scope.excluded_external_ids) if target.discovery_scope else set()
        selected = [row for row in records if row.source.external_id not in excluded]
        self.capture_complete_listing_inventory(target=target, all_records=records, selected_records=selected, listing_identity="fixture")
        for row in selected:
            yield row


def test_gui_save_full_scope_apply_and_batch_end_to_end(qt_app, tmp_path):
    editor, catalog = _catalog_editor(tmp_path)
    source = catalog.find_source("magapoke", "episode-3")
    target = catalog.list_source_targets(source_id=source.id)[0]
    run = catalog.create_crawl_run(item_id=source.item_id, source_id=source.id, target_id=target.id, access_strategy="direct")
    archive = tmp_path / "003-existing.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("synthetic.txt", "synthetic test fixture")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    catalog.finalize_successful_crawl(run.id, artifact=ArtifactInput(kind="archive", format="zip", sha256=digest,
        byte_size=archive.stat().st_size, storage_backend="filesystem", locator=str(archive)), page_count=1)
    editor.reload()
    _wait(lambda: editor._reload_worker is None, editor)
    editor.set_listing(_listing(), checked=("episode-1", "episode-2", "episode-3"))
    before_catalog, before_yaml = catalog.path.read_bytes(), editor.watchlist_path.read_bytes()
    _preview_hole(editor)
    assert catalog.path.read_bytes() == before_catalog
    assert editor.watchlist_path.read_bytes() == before_yaml
    assert editor.scope_edit_preview.archive_order_preview["number_changes"]
    assert "003-existing" in editor.status.toPlainText()
    editor.save_button.click()
    _wait(lambda: editor._save_worker is None, editor)
    assert WatchlistService(editor.watchlist_path).get("one").discovery_scope.excluded_external_ids == ("episode-2",)
    assert catalog.path.read_bytes() == before_catalog
    requested = []
    editor.fullRequested.connect(requested.append)
    editor.full_button.click()
    assert requested == ["one"]
    registry = DiscoveryAdapterRegistry()
    registry.register("magapoke", _SyntheticFullAdapter)
    result = asyncio.run(DiscoveryService(catalog, registry).discover(object(), WatchlistService(editor.watchlist_path).get(requested[0]), "full"))
    assert result.complete is True, result
    editor.preview_scope_sync()
    _wait(lambda: editor._scope_worker is None, editor)
    assert editor._last_scope_preview.ready, editor.status.toPlainText()
    with sqlite3.connect(catalog.path) as connection:
        connection.execute("UPDATE sources SET acquisition_enabled=1 WHERE external_id='episode-2'")
    concurrent_catalog = catalog.path.read_bytes()
    assert editor.apply_scope_sync(confirm=True)
    _wait(lambda: editor._scope_worker is None, editor)
    assert "停止" in editor.status.toPlainText()
    assert catalog.path.read_bytes() == concurrent_catalog
    editor.preview_scope_sync()
    _wait(lambda: editor._scope_worker is None, editor)
    assert editor._last_scope_preview.ready
    assert editor.apply_scope_sync(confirm=True)
    _wait(lambda: editor._scope_worker is None, editor)
    policy = SitePolicyRegistry()
    policy.register("magapoke", MagapokeSitePolicy)
    plan = BatchPlanner(catalog, policy, watchlist=WatchlistService(editor.watchlist_path)).plan(site="magapoke")
    assert {row.external_id for row in plan.candidates} == {"episode-1"}
    assert not catalog.find_source("magapoke", "episode-2").acquisition_enabled
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == digest


def test_snapshot_refresh_during_apply_rereads_committed_state(qt_app, tmp_path, monkeypatch):
    editor, catalog = _catalog_editor(tmp_path)
    registry = DiscoveryAdapterRegistry()
    registry.register("magapoke", _SyntheticFullAdapter)
    asyncio.run(DiscoveryService(catalog, registry).discover(object(), editor.targets[0], "full"))
    editor.preview_scope_sync()
    _wait(lambda: editor._scope_worker is None, editor)
    assert editor._last_scope_preview.ready
    workers, applied, refreshed = [], [], []
    editor.scopeApplied.connect(applied.append)
    editor.catalogReloadRequested.connect(lambda: refreshed.append(True))
    monkeypatch.setattr(editor.thread_pool, "start", workers.append)
    assert editor.apply_scope_sync(confirm=True)
    editor.receive_snapshot(editor.snapshot)
    workers[0].run()
    QApplication.processEvents()
    assert not applied  # The obsolete snapshot never receives a success label.
    assert editor._scope_worker is None
    assert editor._reload_worker is workers[1]
    workers[1].run()
    QApplication.processEvents()
    assert editor._reload_worker is None
    assert refreshed == [True]
    assert editor.snapshot.keys[0].summary.sync_status == "synced"
