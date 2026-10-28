import asyncio
import hashlib
import sqlite3
import time
import zipfile

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from screenshot_crawler.archive_order import build_work_archive_position_plan
from screenshot_crawler.batch import BatchPlanner
from screenshot_crawler.catalog import CatalogService
from screenshot_crawler.discovery import (
    DiscoveredItem,
    DiscoveredRecord,
    DiscoveredSource,
    DiscoveryAdapter,
    DiscoveryAdapterRegistry,
    DiscoveryService,
)
from screenshot_crawler.gui.execution_dialog import ExecutionPreviewDialog
from screenshot_crawler.gui.main_window import MainWindow
from screenshot_crawler.gui.work_editor import WorkEditorDialog
from screenshot_crawler.management.execution import ExecutionPlanService, ExecutionSelection
from screenshot_crawler.management.inventory import InventoryService, default_policy_registry
from screenshot_crawler.watchlist.models import WatchlistTarget
from screenshot_crawler.watchlist.service import WatchlistService
from screenshot_crawler.watchlist.work_edit import WorkDraft, selected_rows
from tests.unit.test_work_edit import listing


@pytest.fixture
def app(monkeypatch):
    from screenshot_crawler.core.browser import BrowserSession

    async def no_cdp(*args, **kwargs):
        raise AssertionError("Synthetic GUI tests never connect to live Chrome")
    monkeypatch.setattr(BrowserSession, "connect", no_cdp)
    instance = QApplication.instance() or QApplication([])
    instance.setQuitOnLastWindowClosed(False)
    yield instance
    for widget in QApplication.topLevelWidgets():
        if isinstance(widget, WorkEditorDialog):
            widget.pool.waitForDone(10000)
            instance.processEvents()
            widget.dirty = False
            widget.set_active_job(False)
            widget.close()
            widget.deleteLater()


def wait_for(predicate):
    deadline = time.monotonic() + 10
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)
    assert predicate()


class SyntheticFull(DiscoveryAdapter):
    supports_bounded_discovery = True
    supports_exclusion_only_scope = True
    supports_exclusion_replay = True

    async def prepare_exclusion_preview(self, page, target):
        return listing(target)

    async def iter_records(self, page, target, mode):
        rows = listing(target)
        selected = {row.external_id for row in selected_rows(target, rows)}
        records = [DiscoveredRecord(DiscoveredItem(canonical_title="Work", order_label=row.display_title),
                    DiscoveredSource(row.external_id, row.url, access_mode="free", available=True,
                                     global_display_position=row.site_position)) for row in rows.rows]
        self.capture_complete_listing_inventory(target=target, all_records=records,
            selected_records=[record for record in records if record.source.external_id in selected],
            listing_identity=rows.listing_identity)
        for record in records:
            if record.source.external_id in selected:
                yield record


def setup(tmp_path, existing):
    path, runtime = tmp_path / "watchlist.yaml", tmp_path / "runtime.yaml"
    path.write_text("targets: []\n", encoding="utf-8")
    runtime.write_text("{}\n", encoding="utf-8")
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    catalog.initialize()
    a = WatchlistTarget("a", "work", "zeblack", "https://example.invalid/a", "Work")
    b = WatchlistTarget("b", "work", "jumpplus", "https://example.invalid/b", "Work")
    registry = DiscoveryAdapterRegistry()
    for site in ("zeblack", "jumpplus"):
        registry.register(site, SyntheticFull)
    service = DiscoveryService(catalog, registry)
    initial = (a, b)[:existing]
    WatchlistService(path).apply_edit(initial)
    for target in initial:
        assert asyncio.run(service.discover(object(), target, "full")).complete
    editor = WorkEditorDialog(path, catalog.path, runtime)
    editor.draft = WorkDraft(initial, "work")
    for target in (a, b):
        if target not in initial:
            editor.draft.add(target)
        editor.draft.set_listing(listing(target))
    editor._fill_works()
    return editor, catalog, service


@pytest.fixture
def search_editor(app, tmp_path):
    path = tmp_path / "watchlist.yaml"
    targets = [
        WatchlistTarget("one", "youchien-wars", "jumpplus", "https://example.invalid/one", "幼稚園WARS"),
        WatchlistTarget("two", "dandadan", "zeblack", "https://example.invalid/two", "ダンダダン"),
    ]
    WatchlistService(path).apply_edit(targets)
    editor = WorkEditorDialog(path, tmp_path / "catalog.sqlite", tmp_path / "runtime.yaml")
    editor.show()
    app.processEvents()
    return editor


@pytest.mark.parametrize("query,expected", [("稚園", ["幼稚園WARS / youchien-wars"]),
                                           ("DANDA", ["ダンダダン / dandadan"]), ("no-match", [])])
def test_work_search_filters_without_switching_or_writing(search_editor, monkeypatch, query, expected):
    editor = search_editor
    before = editor.path.read_bytes()
    draft = editor.draft
    editor.dirty = True
    monkeypatch.setattr(QMessageBox, "question", lambda *args: pytest.fail("Typing must not switch Works"))
    editor.work_search.setText(query + "x")
    QTest.keyClick(editor.work_search, Qt.Key.Key_Backspace)
    model = editor.work_completer.completionModel()
    assert [model.data(model.index(row, 0)) for row in range(model.rowCount())] == expected
    editor.work_search.clear()
    assert editor.draft is draft and editor.dirty
    assert editor.work_combo.currentData() == "youchien-wars"
    assert editor.path.read_bytes() == before


@pytest.mark.parametrize("discard", [False, True])
def test_work_search_selection_confirms_unsaved_changes(search_editor, monkeypatch, discard):
    editor = search_editor
    draft = editor.draft
    editor.dirty = True
    questions = []

    def confirm(*args):
        questions.append(args)
        return QMessageBox.StandardButton.Discard if discard else QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "question", confirm)
    editor.work_completer.activated[str].emit("ダンダダン / dandadan")
    assert len(questions) == 1
    assert editor.draft.work_key == ("dandadan" if discard else "youchien-wars")
    assert editor.work_combo.currentData() == editor.draft.work_key
    if not discard:
        assert editor.draft is draft and editor.dirty


def test_work_search_keyboard_selection_and_unmatched_enter(search_editor, monkeypatch):
    editor = search_editor
    additions = []
    monkeypatch.setattr(editor, "add_target", lambda *args, **kwargs: additions.append(True))
    editor.work_search.setFocus()
    QTest.keyClicks(editor.work_search, "danda")
    app = QApplication.instance()
    app.processEvents()
    QTest.keyClick(editor.work_completer.popup(), Qt.Key.Key_Down)
    QTest.keyClick(editor.work_completer.popup(), Qt.Key.Key_Return)
    assert editor.draft.work_key == "dandadan"
    editor.work_search.clear()
    QTest.keyClicks(editor.work_search, "no-match")
    QTest.keyClick(editor.work_search, Qt.Key.Key_Return)
    assert editor.draft.work_key == "dandadan"
    assert not additions


def test_work_search_includes_unsaved_new_work_and_obeys_busy_state(search_editor, monkeypatch):
    from screenshot_crawler.gui.watchlist_editor import AddWatchlistKeyDialog

    editor = search_editor

    def accept(dialog):
        dialog.key_edit.setText("new-key")
        dialog.work_edit.setText("new-work")
        dialog.label_edit.setText("新しい下書き")
        dialog.site_edit.setText("jumpplus")
        dialog.url_edit.setText("https://example.invalid/new")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(AddWatchlistKeyDialog, "exec", accept)
    assert editor.add_target(new_work=True)
    assert "新しい下書き / new-work" in editor.work_search_model.stringList()
    assert "new-work" not in {target.work_key for target in WatchlistService(editor.path).list_targets()}
    editor.set_active_job(True)
    assert not editor.work_search.isEnabled()
    editor.work_completer.activated[str].emit("ダンダダン / dandadan")
    assert editor.draft.work_key == "new-work"
    editor.set_active_job(False)
    assert editor.work_search.isEnabled()


@pytest.mark.parametrize("close_action", ["window", "escape"])
@pytest.mark.parametrize("dirty,discard,closed", [(False, None, True), (True, True, True), (True, False, False)])
def test_work_editor_can_close_during_background_job(app, tmp_path, monkeypatch, close_action, dirty, discard, closed):
    editor, catalog, _service = setup(tmp_path, 0)
    before = editor.path.read_bytes(), catalog.path.read_bytes()
    questions = []

    def confirm(*args):
        questions.append(args)
        return QMessageBox.StandardButton.Discard if discard else QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "question", confirm)
    editor.dirty = dirty
    editor.set_active_job(True)
    editor.show()
    app.processEvents()
    assert not editor.controls.isEnabled()
    if close_action == "window":
        assert editor.close() == closed
    else:
        QTest.keyClick(editor, Qt.Key.Key_Escape)
    assert editor.isVisible() == (not closed)
    assert len(questions) == int(dirty)
    assert editor.active_job  # Closing the editor never changes the background job state.
    assert not editor._guard()  # Editing remains blocked while the job runs.
    assert (editor.path.read_bytes(), catalog.path.read_bytes()) == before


@pytest.mark.parametrize("close_action", ["window", "escape"])
def test_work_editor_cannot_close_during_own_task(app, tmp_path, monkeypatch, close_action):
    editor, _catalog, _service = setup(tmp_path, 0)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: pytest.fail("Task must finish before discard confirmation"))
    editor.task = object()
    editor.dirty = True
    editor.show()
    app.processEvents()
    try:
        if close_action == "window":
            assert not editor.close()
        else:
            QTest.keyClick(editor, Qt.Key.Key_Escape)
        assert editor.isVisible()
    finally:
        editor.task = None


@pytest.mark.parametrize("existing", [0, 1, 2])
def test_work_registration_or_existing_replacement_save_full_and_batch(app, tmp_path, existing):
    editor, catalog, service = setup(tmp_path, existing)
    archive = None
    archive_bytes = None
    if existing:
        from screenshot_crawler.catalog import ArtifactInput

        source = catalog.find_source("zeblack", "5")
        target = catalog.list_source_targets(source_id=source.id)[0]
        run = catalog.create_crawl_run(item_id=source.item_id, source_id=source.id,
                                       target_id=target.id, access_strategy="direct")
        archive = tmp_path / "existing.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("synthetic.txt", "synthetic content, no real-site images")
        archive_bytes = archive.read_bytes()
        catalog.finalize_successful_crawl(run.id, artifact=ArtifactInput(kind="archive", format="zip",
            sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
            byte_size=archive.stat().st_size, storage_backend="filesystem", locator=str(archive)), page_count=1)
    before_ids = {(source.site, source.external_id): source.id for source in catalog.list_sources()}
    before = catalog.path.read_bytes()
    if existing == 2:
        editor.draft.configured_keys.add("b")
        editor.draft.set_range("b", "5", "6")
    editor.change(lambda: editor.draft.replace_range("a", "5", "6", "b", "5", "6"))
    editor.preview_edit()
    wait_for(lambda: editor.task is None)
    assert editor.preview is not None, editor.status.toPlainText()
    requested = []
    editor.fullRequested.connect(requested.append)
    editor.save_edit()
    wait_for(lambda: editor.task is None)
    assert requested and requested[0][0] == {"a", "b"}, editor.status.toPlainText()
    assert catalog.path.read_bytes() == before
    saved = WatchlistService(editor.path).list_targets()
    for target in saved:
        result = asyncio.run(service.discover(object(), target, "full"))
        assert result.complete is True, result
    sources = catalog.list_sources()
    assert all(catalog.find_source(site, external_id).id == source_id
               for (site, external_id), source_id in before_ids.items())
    assert not catalog.find_source("zeblack", "5").acquisition_enabled if existing else catalog.find_source("zeblack", "5") is None
    work = catalog.find_work("work")
    plan = build_work_archive_position_plan(work, saved, catalog.list_items(work_id=work.id), sources, provisional=True)
    assert [(catalog.get_source(source_id).site, catalog.get_source(source_id).external_id) for source_id in plan.ordered_source_ids] == [
        *(('zeblack', str(number)) for number in range(1, 5)),
        ('jumpplus', '5'), ('jumpplus', '6'),
        *(('zeblack', str(number)) for number in range(7, 11)),
    ]
    policies = default_policy_registry()
    planner = BatchPlanner(catalog, policies, watchlist=WatchlistService(editor.path))
    assert len(planner.plan(site="zeblack").candidates) == 8
    assert len(planner.plan(site="jumpplus").candidates) == 2
    assert {candidate.external_id: candidate.artifact_prefix for candidate in planner.plan(site="jumpplus").candidates} == {"5": "005", "6": "006"}
    if existing:
        assert catalog.get_item(catalog.find_source("zeblack", "5").item_id).status == "completed"
        assert catalog.get_item(catalog.find_source("jumpplus", "5").item_id).status == "pending"
        assert archive.read_bytes() == archive_bytes


def test_save_rejects_changed_catalog_and_watchlist(app, tmp_path):
    editor, catalog, _service = setup(tmp_path, 1)
    editor.change(lambda: editor.draft.replace_range("a", "5", "6", "b", "5", "6"))
    editor.preview_edit()
    wait_for(lambda: editor.task is None)
    assert editor.preview is not None
    before = editor.path.read_bytes()
    from screenshot_crawler.catalog import WorkInput

    catalog.create_work(WorkInput(work_key="unrelated", title="New"))
    editor.save_edit()
    wait_for(lambda: editor.task is None)
    assert editor.path.read_bytes() == before
    assert "Catalogが変更" in editor.status.toPlainText()
    editor.preview_edit()
    wait_for(lambda: editor.task is None)
    WatchlistService(editor.path).update_target("a", label="external")
    external = editor.path.read_bytes()
    editor.save_edit()
    wait_for(lambda: editor.task is None)
    assert editor.path.read_bytes() == external


def test_post_save_full_uses_explicit_new_keys_and_yes_no_single_confirmation(app, tmp_path, monkeypatch):
    editor, catalog, _service = setup(tmp_path, 1)
    editor.change(lambda: editor.draft.set_range("b", "5", None))
    editor.preview_edit()
    wait_for(lambda: editor.task is None)
    editor.save_edit()
    wait_for(lambda: editor.task is None)
    window = MainWindow(catalog.path, editor.path, editor.runtime_path,
                        management_path=tmp_path / "management.sqlite", auto_load=False)
    snapshot = InventoryService().load(catalog.path, editor.path, runtime_path=editor.runtime_path)
    window.set_snapshot(snapshot)
    window.model.set_checked_keys({"a"})
    calls = []
    monkeypatch.setattr(window, "_show_execution_preview", lambda action, **kwargs: calls.append((action, kwargs)))
    window._run_work_full(({"b"}, WatchlistService(editor.path).revision()))
    wait_for(lambda: bool(calls))
    assert calls == [("discover", {"selected_keys": {"b"}, "force_full": True, "after_watchlist_save": True})]
    assert window.model.selected_keys == {"a"}
    preview = ExecutionPlanService().preview(window.model.snapshot, ExecutionSelection.from_keys(["b"]), action="discover", mode="full", runtime_path=editor.runtime_path)
    request = preview.request(window.model.snapshot)
    for yes in (False, True):
        dialog = ExecutionPreviewDialog(preview, request, after_watchlist_save=True)
        received = []
        dialog.requestConfirmed.connect(received.append)
        if yes:
            dialog._confirm()
        else:
            dialog.reject()
        assert received == ([request] if yes else [])
        assert dialog.result() == (QDialog.DialogCode.Accepted if yes else QDialog.DialogCode.Rejected)
    window.close()


def test_new_target_dialog_preserves_other_drafts(app, tmp_path, monkeypatch):
    from screenshot_crawler.gui.watchlist_editor import AddWatchlistKeyDialog

    editor, _catalog, _service = setup(tmp_path, 1)
    editor.draft.set_range("a", None, "4")
    editor.dirty = True
    # setup has b already as an unsaved draft; add a third site without discarding it.
    def accept(dialog):
        dialog.key_edit.setText("c")
        dialog.site_edit.setText("magapoke")
        dialog.url_edit.setText("https://example.invalid/c")
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(AddWatchlistKeyDialog, "exec", accept)
    assert editor.add_target()
    assert {target.key for target in editor.draft.members} == {"a", "b", "c"}
    assert editor.draft.target("a").discovery_scope is not None
    assert "c" not in {target.key for target in WatchlistService(editor.path).list_targets()}


def test_pending_full_waits_for_reload_requested_after_save(app, tmp_path, monkeypatch):
    editor, catalog, _service = setup(tmp_path, 1)
    window = MainWindow(catalog.path, editor.path, editor.runtime_path,
                        management_path=tmp_path / "management.sqlite", auto_load=False)
    stale = InventoryService().load(catalog.path, editor.path, runtime_path=editor.runtime_path)
    window.set_snapshot(stale)
    WatchlistService(editor.path).apply_edit(editor.draft.targets)
    window._loading = True  # Simulate an earlier Inventory read still running.
    workers, calls = [], []
    monkeypatch.setattr(window.thread_pool, "start", workers.append)
    monkeypatch.setattr(window, "_show_execution_preview", lambda action, **kwargs: calls.append(kwargs))
    window._run_work_full(({"b"}, WatchlistService(editor.path).revision()))
    window._load_succeeded(stale)
    assert not calls and window._pending_work_full is not None
    assert len(workers) == 1
    workers[0].run()
    wait_for(lambda: bool(calls))
    assert calls[0]["selected_keys"] == {"b"}
    assert window.model.selected_keys == set()
    window.close()


@pytest.mark.parametrize("missing_listing", [False, True])
def test_work_preview_rejects_unbound_active_source_without_writing(app, tmp_path, missing_listing):
    editor, catalog, _service = setup(tmp_path, 1)
    if missing_listing:
        editor.draft.set_listing(listing(editor.draft.target("a"), count=9))
    else:
        with sqlite3.connect(catalog.path) as connection:
            connection.execute("UPDATE sources SET discovery_key=NULL WHERE external_id='5'")
    before_catalog, before_watchlist = catalog.path.read_bytes(), editor.path.read_bytes()
    editor.preview_edit()
    wait_for(lambda: editor.task is None)
    assert editor.preview is None
    assert ("完全一覧にありません" if missing_listing else "所有key不明") in editor.status.toPlainText()
    assert catalog.path.read_bytes() == before_catalog
    assert editor.path.read_bytes() == before_watchlist
