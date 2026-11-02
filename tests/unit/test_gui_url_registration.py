import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from screenshot_crawler.catalog import CatalogService
from screenshot_crawler.cli import _discovery_registry
from screenshot_crawler.gui.url_registration import UrlRegistrationDialog
from screenshot_crawler.registration.draft import BatchRegistrationDraft
from screenshot_crawler.registration.resolver import UrlResolver

SHOW_PREVIEW = UrlRegistrationDialog._show_preview
A = "https://shonenjumpplus.com/episode/123"
B = "https://comic-days.com/episode/456"
K = "https://comic-walker.com/detail/KC_004915_S"


def wait_for(predicate):
    deadline = time.monotonic() + 15
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)
    assert predicate()


@pytest.fixture
def gui(tmp_path, monkeypatch):
    from screenshot_crawler.core.browser import BrowserSession
    async def no_cdp(*args, **kwargs):
        raise RuntimeError("synthetic CDP unavailable")
    monkeypatch.setattr(BrowserSession, "connect", no_cdp)
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    path, runtime = tmp_path / "watchlist.yaml", tmp_path / "runtime.yaml"
    path.write_text("targets: []\n", encoding="utf-8")
    runtime.write_text("{}\n", encoding="utf-8")
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    catalog.initialize()
    from screenshot_crawler.management.catalog_reader import CatalogInventoryReader
    from screenshot_crawler.watchlist.service import WatchlistService
    base, revision = WatchlistService(path).read_snapshot()
    draft = BatchRegistrationDraft(base, revision, UrlResolver(_discovery_registry()),
        catalog_snapshot=CatalogInventoryReader().read(catalog.path))
    monkeypatch.setattr(UrlRegistrationDialog, "_show_preview", lambda self, summary: None)
    dialog = UrlRegistrationDialog(path, catalog.path, runtime, draft=draft)
    dialog.metadata.setChecked(False)
    dialog.show()
    app.processEvents()
    yield dialog, app
    dialog.pool.waitForDone(15000)
    app.processEvents()
    dialog.dirty = False
    dialog.close()
    dialog.deleteLater()


def populate(dialog, text):
    dialog.input.setPlainText(text)
    dialog.analyze()
    wait_for(lambda: dialog.task is None)


def confirm(dialog, label="人工作品", work="test_work"):
    dialog.label_edit.setText(label)
    dialog.work_edit.setText(work)
    dialog.confirm()


def test_paste_partial_failure_manual_confirmation_and_no_write(gui):
    dialog, _app = gui
    before = dialog.path.read_bytes(), dialog.catalog.read_bytes()
    populate(dialog, f"{A}\n\n{B}\n{A}\nhttps://evil.test/\n")
    assert len(dialog.draft.candidates) == 3
    assert dialog.table.rowCount() == 3
    dialog.table.setCurrentCell(0, 0)
    confirm(dialog)
    assert dialog.draft.readiness("1").status == "ready"
    assert "identity: unknown" in dialog.evidence.toPlainText()
    assert dialog.draft.candidates["1"].resolution.title is None
    dialog.table.setCurrentCell(2, 0)
    assert not dialog.confirm_button.isEnabled()
    reasons = dialog.draft.readiness("3").reasons
    assert reasons and reasons[0] in dialog.table.item(2, 6).text()
    assert dialog.evidence.toPlainText().startswith("登録準備: blocked\n理由・必要な操作: " + reasons[0])
    assert not dialog.save_button.isEnabled()
    assert before == (dialog.path.read_bytes(), dialog.catalog.read_bytes())


@pytest.mark.parametrize("query,expected", [
    ("星の冒険", "hoshi_adventure"),  # Catalog title survives a different Watchlist label.
    ("特装版", "hoshi_adventure"),  # Every label in a multi-key Work is searchable.
    ("ＨＯＳＨＩ ADVENTURE", "hoshi_adventure"),
    ("ALPHA_COMICDAYS", "hoshi_adventure"),
    ("別の物語", "other_work"),
    ("該当する作品なし", None),
])
def test_existing_work_search_is_read_only_and_matches_titles_and_ids(gui, query, expected):
    from screenshot_crawler.registration.service import draft_identity
    from screenshot_crawler.watchlist.models import WatchlistTarget
    dialog, _app = gui
    populate(dialog, A)
    confirm(dialog)
    batch = dialog.draft
    batch.catalog_works = (("hoshi_adventure", "星の冒険"), ("other_work", "別の物語")) + tuple(
        (f"work_{i}", f"既存作品{i}") for i in range(500))
    batch.base = (
        WatchlistTarget("alpha_comicdays", "hoshi_adventure", "comicdays", B, "星の冒険 特装版"),
        WatchlistTarget("alpha_jumpplus", "hoshi_adventure", "jumpplus", A, "ほしの冒険"),
    )
    dialog._render()
    before = draft_identity(batch), dialog.path.read_bytes(), dialog.catalog.read_bytes()
    marker = dialog.preview = object()
    dialog.dirty = False
    dialog.work_search.setText(query)
    visible = {dialog.work_combo.itemData(i) for i in range(dialog.work_combo.count())
               if dialog.work_combo.itemData(i).startswith("existing:")}
    assert visible == ({"existing:" + expected} if expected else set())
    assert dialog.work_combo.currentData() == "1"
    assert dialog.work_matches.text() == f"既存 {bool(expected):d} / 502件"
    assert not dialog._form_dirty and not dialog.dirty and dialog.preview is marker
    QTest.keyClick(dialog.work_search, Qt.Key.Key_Return)
    assert dialog.task is None and dialog.preview is marker
    assert before == (draft_identity(batch), dialog.path.read_bytes(), dialog.catalog.read_bytes())


def test_search_preserves_pending_and_current_work_choice_and_shows_collision_reason(gui):
    dialog, _app = gui
    dialog.draft.catalog_works = (("existing_work", "既存の作品"), ("other_work", "別作品"))
    populate(dialog, A + "\n" + B)
    dialog.table.setCurrentCell(0, 0)
    confirm(dialog, work="existing_work")
    assert dialog.table.item(0, 5).text() == "blocked"
    assert "work_keyが別Workと衝突" in dialog.table.item(0, 6).text()
    assert "work_keyが別Workと衝突" in dialog.evidence.toPlainText().split("元URL:")[0]
    dialog.work_search.setText("既存の作品")
    dialog.work_combo.setCurrentIndex(dialog.work_combo.findData("existing:existing_work"))
    assert dialog._form_dirty
    dialog.work_search.setText("一致なし")
    assert dialog.work_combo.currentData() == "existing:existing_work"
    assert dialog.draft.candidates["1"].group_id == "1"  # Search cannot apply a pending choice.
    dialog.apply_fields()
    assert dialog.draft.candidates["1"].group_id == "existing:existing_work"
    assert dialog.work_combo.currentData() == "existing:existing_work"
    assert dialog.work_edit.isReadOnly()
    dialog.table.setCurrentCell(1, 0)
    assert dialog.work_search.text() == "一致なし"
    assert dialog.work_combo.currentData() == "2"
    dialog.work_search.clear()
    assert dialog.work_matches.text() == "既存 2 / 2件"


def test_edits_survive_row_switch_retry_and_group_selection(gui):
    dialog, _app = gui
    populate(dialog, A + "\n" + B)
    dialog.table.setCurrentCell(0, 0)
    dialog.label_edit.setText("手編集")
    dialog.key_edit.setText("manual_key")
    dialog.work_edit.setText("first_work")
    dialog.table.setCurrentCell(1, 0)
    assert dialog.draft.candidates["1"].label == "手編集"
    assert dialog.draft.candidates["1"].key == "manual_key"
    dialog.work_combo.setCurrentIndex(dialog.work_combo.findData("1"))
    dialog.apply_fields()
    assert len(dialog.draft.works) == 1
    dialog.table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    assert not dialog.draft.works["1"].selected
    assert dialog.table.item(1, 0).checkState() == Qt.CheckState.Unchecked
    dialog.table.setCurrentCell(0, 0)
    dialog.retry_selected()
    wait_for(lambda: dialog.task is None)
    assert dialog.draft.candidates["1"].key == "manual_key"
    assert dialog.draft.candidates["1"].label == "手編集"
    assert dialog.draft.candidates["2"].group_id == "1"


def test_corrected_url_requires_reanalysis_and_retains_input(gui):
    dialog, _app = gui
    populate(dialog, "https://evil.test/old")
    dialog.label_edit.setText("人工作品")
    dialog.work_edit.setText("work")
    dialog.url_edit.setText(A)
    dialog.apply_fields()
    assert not dialog.confirm_button.isEnabled()
    dialog.retry_selected()
    wait_for(lambda: dialog.task is None)
    assert dialog.draft.candidates["1"].label == "人工作品"
    assert dialog.draft.candidates["1"].resolution.status == "valid"
    assert "https://evil.test/old" in dialog.draft.raw_input


def test_cdp_failure_leaves_safe_url_manual_candidate(gui):
    dialog, _app = gui
    dialog.metadata.setChecked(True)
    populate(dialog, K)
    row = dialog.draft.candidates["1"]
    assert row.resolution.status == "valid"
    assert any("synthetic CDP unavailable" in warning for warning in row.resolution.warnings)
    confirm(dialog)
    assert dialog.draft.readiness("1").status == "ready"


def test_cancel_and_busy_keep_draft(gui, monkeypatch):
    dialog, _app = gui
    populate(dialog, A)
    confirm(dialog)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Cancel)
    dialog.close()
    assert dialog.isVisible()
    dialog.task = object()
    dialog.reject()
    assert dialog.isVisible()
    dialog.task = None
    dialog.set_active_job(True)
    assert not dialog.analyze_button.isEnabled()
    assert not dialog.confirm_button.isEnabled()
    dialog.set_active_job(False)
    assert dialog.draft.candidates["1"].confirmed


def test_large_input_scroll_limits_and_stale_callbacks(gui):
    dialog, _app = gui
    urls = [f"https://shonenjumpplus.com/episode/{index}" for index in range(1, 101)]
    populate(dialog, "\n".join(urls))
    assert dialog.table.rowCount() == 100
    dialog.table.scrollToBottom()
    assert dialog.table.verticalScrollBar().maximum() > 0
    previous = len(dialog.draft.candidates)
    dialog._resolved((-1, None, 1, B, dialog.draft.resolver.resolve(B)))
    assert len(dialog.draft.candidates) == previous
    populate(dialog, "x\n" * 101)
    assert "100" in dialog.status.text()
    assert len(dialog.draft.candidates) == previous


def test_layout_captures_and_keyboard_no_accidental_action(gui):
    dialog, _app = gui
    populate(dialog, A + "\n" + K + "\nhttps://evil.test/")
    dialog.table.setCurrentCell(0, 0)
    confirm(dialog)
    output = Path(__file__).resolve().parents[2] / ".tmp" / "watchlist-registration"
    output.mkdir(parents=True, exist_ok=True)
    for width, height in ((1200, 880), (980, 760)):
        dialog.resize(width, height)
        _app.processEvents()
        assert dialog.grab().save(str(output / f"stage03-{width}.png"))
        assert dialog.rect().contains(dialog.close_button.geometry().bottomRight())
    dialog.label_edit.setFocus()
    QTest.keyClick(dialog.label_edit, Qt.Key.Key_Return)
    assert dialog.task is None


def test_context_read_failure_no_fallback(gui):
    dialog, _app = gui
    dialog.dirty = False
    dialog.catalog = dialog.catalog.with_name("missing.sqlite")
    dialog.draft = None
    dialog.reload_context()
    wait_for(lambda: dialog.task is None)
    assert dialog.draft is None
    assert not dialog.analyze_button.isEnabled()
    assert not dialog.catalog.exists()


def test_main_window_entry_preserves_inventory_selection_and_blocks_other_actions(gui, tmp_path):
    from screenshot_crawler.gui.main_window import MainWindow
    from screenshot_crawler.management.inventory import InventoryService
    from screenshot_crawler.watchlist.service import WatchlistService
    dialog, _app = gui
    target = WatchlistService(dialog.path).add(key="existing", work_key="existing_work",
        site="jumpplus", url=A, label="Existing")
    window = MainWindow(dialog.catalog, dialog.path, dialog.runtime_path,
        management_path=tmp_path / "management.sqlite", auto_load=False)
    window.set_snapshot(InventoryService().load(dialog.catalog, dialog.path, runtime_path=dialog.runtime_path))
    window.model.set_checked_keys({target.key})
    window._open_url_registration()
    editor = window._registration_editor
    wait_for(lambda: editor.task is None)
    assert editor.isVisible() and window.model.selected_keys == {"existing"}
    assert window._discovery_block_reason()
    window._show_execution_preview("discover")
    assert window._job_controller is None
    editor.dirty = False
    editor.close()
    window.close()


def test_draft_only_work_editor_never_saves_or_requests_full(gui, tmp_path, monkeypatch):
    from screenshot_crawler.gui.work_editor import WorkEditorDialog
    from screenshot_crawler.registration.detail import accept_detail, detail_draft
    from screenshot_crawler.watchlist.service import WatchlistService
    from tests.unit.test_registration_detail import add, listing, setup_batch
    dialog, _app = gui
    batch, path, catalog = setup_batch(tmp_path)
    a, b = add(batch, "jumpplus", "first"), add(batch, "comicdays", "second")
    batch.assign(b, group_id=a)
    batch.confirm(b)
    request, draft = detail_draft(batch, a)
    before = path.read_bytes(), catalog.path.read_bytes()
    editor = WorkEditorDialog(path, catalog.path, dialog.runtime_path, draft=draft,
        revision=request.revision, catalog_identity=request.catalog_identity)
    saved, full = [], []
    editor.watchlistSaved.connect(lambda: saved.append(True))
    editor.fullRequested.connect(full.append)
    def no_save(*args, **kwargs):
        raise AssertionError("draft-only must not persist")
    monkeypatch.setattr(WatchlistService, "apply_edit", no_save)
    assert not editor.work_combo.isEnabled() and not editor.work_search.isEnabled()
    assert editor.add_target(new_work=True) is False
    for target in editor.draft.members:
        editor.draft.set_listing(listing(target))
    editor.preview_edit()
    assert editor.preview is None  # Fetching alone is not scope confirmation.
    for target in editor.draft.members:
        editor.confirm_scope(target.key)
    editor.preview_edit()
    wait_for(lambda: editor.task is None)
    assert editor.preview is not None
    assert "archive_order" in editor.preview.summary
    editor.save_edit()
    wait_for(lambda: editor.task is None)
    result, configured = editor.draft_result
    accept_detail(batch, request, result, configured)
    assert batch.readiness(a).status == "ready"
    assert not saved and not full
    assert before == (path.read_bytes(), catalog.path.read_bytes())
    assert not draft.listings and not draft.configured_keys
    editor.deleteLater()


def test_cancelled_child_keeps_parent_and_other_work(gui, tmp_path, monkeypatch):
    from screenshot_crawler.gui.work_editor import WorkEditorDialog
    from screenshot_crawler.registration.detail import detail_draft
    from tests.unit.test_registration_detail import add, listing, setup_batch
    dialog, _app = gui
    batch, path, catalog = setup_batch(tmp_path)
    a, b = add(batch, "jumpplus", "first"), add(batch, "comicdays", "second")
    other = batch.candidates[b]
    request, draft = detail_draft(batch, a)
    editor = WorkEditorDialog(path, catalog.path, dialog.runtime_path, draft=draft,
        revision=request.revision, catalog_identity=request.catalog_identity)
    target = editor.draft.members[0]
    editor.draft.set_listing(listing(target))
    editor.change(lambda: editor.draft.set_range(target.key, "2", "3"))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Discard)
    editor.reject()
    assert editor.draft_result is None
    assert draft.target(target.key).discovery_scope is None
    assert batch.candidates[b] == other and batch.works[a].detail is None
    editor.deleteLater()


def test_draft_preview_keeps_existing_open_segment_scope(gui, tmp_path):
    from screenshot_crawler.gui.work_editor import WorkEditorDialog
    from screenshot_crawler.registration.detail import detail_draft
    from screenshot_crawler.watchlist.models import ArchiveSegment, WatchlistTarget
    from screenshot_crawler.watchlist.service import WatchlistService
    from tests.unit.test_registration_detail import URLS, add, listing, setup_batch
    dialog, _app = gui
    batch, path, catalog = setup_batch(tmp_path)
    old = WatchlistTarget("old", "work", "jumpplus", URLS["jumpplus"], "既存", False,
        archive_segments=(ArchiveSegment(1, "1", "4"),))
    service = WatchlistService(path)
    service.apply_edit((old,))
    batch.base, batch.revision = service.read_snapshot()
    row = add(batch, "comicdays", "new")
    batch.assign(row, existing_work="work")
    batch.confirm(row)
    request, draft = detail_draft(batch, batch.candidates[row].group_id)
    editor = WorkEditorDialog(path, catalog.path, dialog.runtime_path, draft=draft,
        revision=request.revision, catalog_identity=request.catalog_identity)
    for target in editor.draft.members:
        editor.draft.set_listing(listing(target))
        editor.confirm_scope(target.key)
    editor.preview_edit()
    wait_for(lambda: editor.task is None)
    assert editor.preview is not None
    assert editor.draft.target("old") == old
    assert editor.draft.members[1].archive_segments is not None
    assert service.list_targets() == [old]
    editor.dirty = False
    editor.close()
    editor.deleteLater()


def preview_and_save(dialog):
    dialog.preview_edit()
    wait_for(lambda: dialog.task is None)
    assert dialog.preview is not None, dialog.status.text()
    dialog.save_edit()
    wait_for(lambda: dialog.task is None)


@pytest.mark.parametrize("outcome", ["no", "yes", "failure"])
def test_url_to_atomic_save_main_reload_and_single_full_confirmation(gui, tmp_path, monkeypatch, outcome):
    import asyncio

    from screenshot_crawler.discovery import DiscoveryAdapterRegistry, DiscoveryService
    from screenshot_crawler.discovery.service import DiscoveryIncompleteError
    from screenshot_crawler.gui.main_window import MainWindow
    from screenshot_crawler.management.inventory import InventoryService
    from screenshot_crawler.watchlist.service import WatchlistService
    from tests.unit.test_gui_work_editor import SyntheticFull
    dialog, _app = gui
    window = MainWindow(dialog.catalog, dialog.path, dialog.runtime_path,
        management_path=tmp_path / "management.sqlite", auto_load=False)
    window.set_snapshot(InventoryService().load(dialog.catalog, dialog.path, runtime_path=dialog.runtime_path))
    window._registration_editor = dialog
    dialog.watchlistSaved.connect(window.reload)
    dialog.fullRequested.connect(window._run_work_full)
    requests, questions, full_signals = [], [], []
    dialog.fullRequested.connect(full_signals.append)
    def question(*args, **kwargs):
        questions.append(args[2])
        return QMessageBox.StandardButton.No if outcome == "no" else QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox, "question", question)
    monkeypatch.setattr(window, "_start_execution", requests.append)
    before = dialog.catalog.read_bytes()
    populate(dialog, A)
    confirm(dialog)
    preview_and_save(dialog)
    wait_for(lambda: bool(questions))
    assert len(questions) == len(full_signals) == 1
    assert window.model.selected_keys == set()
    target = WatchlistService(dialog.path).get("test_work_jumpplus")
    saved = dialog.path.read_bytes()
    assert dialog.catalog.read_bytes() == before
    assert len(requests) == (0 if outcome == "no" else 1)
    if outcome == "no":
        assert "未同期" in window.statusBar().currentMessage()
    else:
        assert set(requests[0].selected_keys) == {target.key}
        registry = DiscoveryAdapterRegistry()
        class FailingFull(SyntheticFull):
            async def iter_records(self, page, target, mode):
                raise DiscoveryIncompleteError("synthetic Full failure")
                yield
        registry.register(target.site, FailingFull if outcome == "failure" else SyntheticFull)
        catalog = CatalogService(dialog.catalog)
        result = asyncio.run(DiscoveryService(catalog, registry).discover(object(), target, "full"))
        if outcome == "failure":
            assert result.error and not result.complete
        else:
            assert result.complete
            assert catalog.find_work(target.work_key) is not None
            assert all(source.discovery_key == target.key for source in catalog.list_sources())
        assert dialog.path.read_bytes() == saved
    window.close()


def test_full_gui_workflow_multiple_site_detail_then_save(gui, monkeypatch):
    from PySide6.QtCore import QTimer

    from screenshot_crawler.gui.work_editor import WorkEditorDialog
    from screenshot_crawler.watchlist.service import WatchlistService
    from tests.unit.test_registration_detail import listing
    dialog, _app = gui
    populate(dialog, A + "\n" + B)
    dialog.table.setCurrentCell(0, 0)
    confirm(dialog, work="combined")
    dialog.table.setCurrentCell(1, 0)
    dialog.label_edit.setText("人工作品")
    dialog.work_combo.setCurrentIndex(dialog.work_combo.findData("1"))
    dialog.confirm()
    assert dialog.draft.readiness("1").status == "needs_scope"
    original_exec = WorkEditorDialog.exec
    def edit(editor):
        def start():
            for target in editor.draft.members:
                editor.draft.set_listing(listing(target))
            a, b = editor.draft.members
            editor.change(lambda: editor.draft.replace_range(a.key, "2", "2", b.key, "2", "2"))
            for target in editor.draft.members:
                editor.confirm_scope(target.key)
            editor.preview_edit()
            QTimer.singleShot(20, finish)
        def finish():
            if editor.task is not None:
                QTimer.singleShot(20, finish)
            elif editor.preview is None:
                editor.dirty = False
                editor.reject()
            else:
                editor.save_edit()
        QTimer.singleShot(0, start)
        return original_exec(editor)
    monkeypatch.setattr(WorkEditorDialog, "exec", edit)
    before = dialog.path.read_bytes(), dialog.catalog.read_bytes()
    dialog.edit_detail()
    assert dialog.draft.readiness("1").status == "ready", dialog.status.text()
    assert before == (dialog.path.read_bytes(), dialog.catalog.read_bytes())
    full = []
    dialog.fullRequested.connect(full.append)
    preview_and_save(dialog)
    targets = WatchlistService(dialog.path).list_targets()
    assert len(targets) == 2 and {target.work_key for target in targets} == {"combined"}
    assert all(target.archive_segments is not None for target in targets)
    assert len(full) == 1 and set(full[0][0]) == {target.key for target in targets}


def test_partial_save_retains_unselected_edits_and_reopens_same_dialog(gui, tmp_path):
    from screenshot_crawler.gui.main_window import MainWindow
    from screenshot_crawler.management.inventory import InventoryService
    dialog, _app = gui
    populate(dialog, A + "\n" + B)
    dialog.table.setCurrentCell(0, 0)
    confirm(dialog, work="first")
    dialog.table.setCurrentCell(1, 0)
    confirm(dialog, label="保留中の人工作品", work="second")
    dialog.table.item(1, 0).setCheckState(Qt.CheckState.Unchecked)
    kept = dialog.draft.candidates["2"]
    preview_and_save(dialog)
    assert not dialog.isVisible() and dialog.dirty
    assert dialog.draft.candidates["2"] == kept
    window = MainWindow(dialog.catalog, dialog.path, dialog.runtime_path,
        management_path=tmp_path / "management.sqlite", auto_load=False)
    window.set_snapshot(InventoryService().load(dialog.catalog, dialog.path, runtime_path=dialog.runtime_path))
    window._registration_editor = dialog
    window._open_url_registration()
    assert window._registration_editor is dialog and dialog.isVisible()
    assert dialog.label_edit.text() == "保留中の人工作品"
    dialog.dirty = False
    window.close()


def test_saved_unverified_freezes_resave_and_does_not_emit_full(gui, monkeypatch):
    from screenshot_crawler.watchlist.service import WatchlistService
    dialog, _app = gui
    populate(dialog, A)
    confirm(dialog)
    dialog.preview_edit()
    wait_for(lambda: dialog.task is None)
    assert dialog.preview is not None
    original_apply, original_read = WatchlistService.apply_edit, WatchlistService.read_snapshot
    committed = False
    def apply(service, *args, **kwargs):
        nonlocal committed
        result = original_apply(service, *args, **kwargs)
        committed = True
        return result
    def read(service):
        if committed:
            raise OSError("synthetic readback failure")
        return original_read(service)
    monkeypatch.setattr(WatchlistService, "apply_edit", apply)
    monkeypatch.setattr(WatchlistService, "read_snapshot", read)
    full = []
    dialog.fullRequested.connect(full.append)
    dialog.save_edit()
    wait_for(lambda: dialog.task is None)
    assert dialog._save_frozen and "保存済み" in dialog.status.text()
    assert not dialog.save_button.isEnabled() and not dialog.preview_button.isEnabled()
    assert not full
    assert WatchlistService(dialog.path).get("test_work_jumpplus")


def test_catalog_refresh_preserves_manual_candidate_and_invalidates_detail(gui):
    dialog, _app = gui
    populate(dialog, A)
    confirm(dialog)
    row = dialog.draft.candidates["1"]
    catalog = CatalogService(dialog.catalog)
    catalog.create_work(work_key="external", title="人工作品")
    dialog.refresh_catalog()
    wait_for(lambda: dialog.task is None)
    assert dialog.draft.candidates["1"] == row
    assert "external" in dialog.draft.existing_works
    assert dialog.draft.works["1"].detail is None


def test_real_final_preview_modal_is_scrollable_and_can_return_before_save(gui, monkeypatch):
    from types import MethodType

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QDialog, QPlainTextEdit
    dialog, _app = gui
    populate(dialog, A)
    confirm(dialog)
    monkeypatch.setattr(dialog, "_show_preview", MethodType(SHOW_PREVIEW, dialog))
    shown, attempts = [], [0]
    def dismiss():
        attempts[0] += 1
        for child in dialog.findChildren(QDialog):
            if child.windowTitle() == "URL登録：選択Workの保存前プレビュー" and child.isVisible():
                shown.append(child.findChild(QPlainTextEdit).toPlainText())
                child.accept()
                return
        if attempts[0] < 500:
            QTimer.singleShot(20, dismiss)
    QTimer.singleShot(0, dismiss)
    before = dialog.path.read_bytes()
    dialog.preview_edit()
    wait_for(lambda: dialog.task is None)
    assert len(shown) == 1 and "test_work_jumpplus" in shown[0]
    assert "UNKNOWN" in shown[0]
    assert dialog.path.read_bytes() == before and dialog.save_button.isEnabled()
