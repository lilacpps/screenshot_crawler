import sqlite3
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication

from screenshot_crawler.catalog import CatalogService, WorkInput
from screenshot_crawler.gui.work_deletion import WorkDeletionDialog, _blocker_messages
from screenshot_crawler.maintenance.work_deletion import (
    WorkDeletionApplyError,
    WorkDeletionPreviewService,
    _namespace,
)


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


def _wait(predicate, app: QApplication) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Qt work-deletion operation timed out")


def test_management_blockers_explain_pending_jobs_and_next_action() -> None:
    text = _blocker_messages(("active_job:first:queued", "active_job:second:queued",
                              "management_worker_unverified:old"))
    assert "待機中のジョブが2件" in text
    assert "ジョブ一覧でキャンセル" in text
    assert "workerの終了を確認できないジョブが1件" in text
    assert "active_job:" not in text


def test_work_deletion_dialog_preview_is_unchecked_and_read_only(
    qt_app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    catalog_path = tmp_path / "catalog.sqlite"
    watchlist_path = tmp_path / "watchlist.yaml"
    management_path = tmp_path / "management.sqlite"
    CatalogService(catalog_path).create_work(WorkInput(work_key="gui-work", title="GUI title"))
    watchlist_path.write_text("targets: []\narchived_work_keys: []\n", encoding="utf-8")
    with sqlite3.connect(management_path) as connection:
        connection.execute("CREATE TABLE jobs(job_id TEXT, state TEXT, selected_keys_json TEXT)")
    WorkDeletionPreviewService().bind_management_stores(catalog_path, [management_path])
    namespace_dir = catalog_path.parent / ".work-deletion" / _namespace(catalog_path)
    namespace_before = {path.name: path.read_bytes() for path in namespace_dir.iterdir()}
    dialog = WorkDeletionDialog(
        "gui-work",
        catalog_path=catalog_path,
        watchlist_path=watchlist_path,
        management_paths=(management_path,),
        library_root=tmp_path / "Books",
        status_root=tmp_path / "crawl-status",
        trash_root=tmp_path / "trash",
    )
    dialog.show()
    _wait(lambda: dialog.worker is None, qt_app)
    assert dialog.plan is not None and dialog.plan.ready
    assert "GUI title" in dialog.summary.toPlainText()
    assert "gui-work" in dialog.summary.toPlainText()
    assert not dialog.confirm.isChecked()
    assert not dialog.apply_button.isEnabled()
    assert {path.name: path.read_bytes() for path in namespace_dir.iterdir()} == namespace_before
    dialog.close()
    dialog.thread_pool.waitForDone(10000)
    dialog.deleteLater()
    qt_app.processEvents()
    assert {path.name: path.read_bytes() for path in namespace_dir.iterdir()} == namespace_before


def test_work_deletion_dialog_blocked_and_recovery_statuses(
    qt_app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    catalog_path = tmp_path / "catalog.sqlite"
    watchlist_path = tmp_path / "watchlist.yaml"
    management_path = tmp_path / "management.sqlite"
    CatalogService(catalog_path).initialize()
    watchlist_path.write_text("targets: []\narchived_work_keys: []\n", encoding="utf-8")
    with sqlite3.connect(management_path) as connection:
        connection.execute("CREATE TABLE jobs(job_id TEXT, state TEXT, selected_keys_json TEXT)")
    WorkDeletionPreviewService().bind_management_stores(catalog_path, [management_path])
    blocked = WorkDeletionDialog(
        "missing-work", catalog_path=catalog_path, watchlist_path=watchlist_path,
        management_paths=(management_path,), library_root=tmp_path / "Books",
        status_root=tmp_path / "status", trash_root=tmp_path / "trash",
    )
    blocked.show()
    _wait(lambda: blocked.worker is None, qt_app)
    assert blocked.plan is not None and not blocked.plan.ready
    assert "BLOCKED" in blocked.status.text()
    assert not blocked.apply_button.isEnabled()
    blocked.close()

    def fail_preview(*_args, **_kwargs):
        raise WorkDeletionApplyError("recovery required: synthetic fault")

    monkeypatch.setattr(WorkDeletionPreviewService, "preview", fail_preview)
    recovery = WorkDeletionDialog(
        "missing-work", catalog_path=catalog_path, watchlist_path=watchlist_path,
        management_paths=(management_path,), library_root=tmp_path / "Books",
        status_root=tmp_path / "status", trash_root=tmp_path / "trash",
    )
    recovery.show()
    _wait(lambda: recovery.worker is None, qt_app)
    assert "RECOVERY_REQUIRED" in recovery.status.text()
    recovery.close()
    assert not (tmp_path / "trash").exists()


@pytest.mark.parametrize("cancel_action", ["callback", "reject", "close"])
def test_work_deletion_preview_cancel_is_cooperative_and_does_not_publish_plan(
    qt_app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cancel_action: str
) -> None:
    monkeypatch.chdir(tmp_path)
    catalog_path = tmp_path / "catalog.sqlite"
    watchlist_path = tmp_path / "watchlist.yaml"
    management_path = tmp_path / "management.sqlite"
    CatalogService(catalog_path).create_work(WorkInput(work_key="cancel-work", title="Cancel title"))
    watchlist_path.write_text("targets: []\narchived_work_keys: []\n", encoding="utf-8")
    with sqlite3.connect(management_path) as connection:
        connection.execute("CREATE TABLE jobs(job_id TEXT, state TEXT, selected_keys_json TEXT)")
    WorkDeletionPreviewService().bind_management_stores(catalog_path, [management_path])
    original_preview = WorkDeletionPreviewService.preview
    seen = threading.Event()
    release = threading.Event()

    def cancel_at_index(self, *args, **kwargs):
        original_progress = kwargs["progress"]
        token = kwargs["cancel"]

        def progress(stage, completed, total, elapsed):
            original_progress(stage, completed, total, elapsed)
            if stage == "filesystem_index":
                if cancel_action == "callback":
                    token.cancel()
                else:
                    seen.set()
                    release.wait(5)

        kwargs["progress"] = progress
        return original_preview(self, *args, **kwargs)

    monkeypatch.setattr(WorkDeletionPreviewService, "preview", cancel_at_index)
    dialog = WorkDeletionDialog(
        "cancel-work", catalog_path=catalog_path, watchlist_path=watchlist_path,
        management_paths=(management_path,), library_root=tmp_path / "Books",
        status_root=tmp_path / "status", trash_root=tmp_path / "trash",
    )
    dialog.show()
    if cancel_action != "callback":
        _wait(seen.is_set, qt_app)
        getattr(dialog, cancel_action)()
        release.set()
    _wait(lambda: dialog.worker is None, qt_app)
    assert dialog.plan is None
    assert "キャンセル" in dialog.status.text()
    assert not (tmp_path / "trash").exists()
    if cancel_action != "callback":
        assert not dialog.isVisible()
    dialog.reject()
    dialog.thread_pool.waitForDone(10000)
    dialog.deleteLater()
    qt_app.processEvents()


def test_work_deletion_dialog_renders_queued_progress_label(
    qt_app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    catalog_path = tmp_path / "catalog.sqlite"
    watchlist_path = tmp_path / "watchlist.yaml"
    management_path = tmp_path / "management.sqlite"
    CatalogService(catalog_path).create_work(WorkInput(work_key="progress-work", title="Progress title"))
    watchlist_path.write_text("targets: []\narchived_work_keys: []\n", encoding="utf-8")
    with sqlite3.connect(management_path) as connection:
        connection.execute("CREATE TABLE jobs(job_id TEXT, state TEXT, selected_keys_json TEXT)")
    WorkDeletionPreviewService().bind_management_stores(catalog_path, [management_path])
    original_preview = WorkDeletionPreviewService.preview
    seen = threading.Event()
    release = threading.Event()

    def paused_preview(self, *args, **kwargs):
        original_progress = kwargs["progress"]

        def progress(stage, completed, total, elapsed):
            original_progress(stage, completed, total, elapsed)
            if stage == "filesystem_index":
                seen.set()
                release.wait(5)

        kwargs["progress"] = progress
        return original_preview(self, *args, **kwargs)

    monkeypatch.setattr(WorkDeletionPreviewService, "preview", paused_preview)
    dialog = WorkDeletionDialog(
        "progress-work", catalog_path=catalog_path, watchlist_path=watchlist_path,
        management_paths=(management_path,), library_root=tmp_path / "Books",
        status_root=tmp_path / "status", trash_root=tmp_path / "trash",
    )
    dialog.show()
    deadline = time.monotonic() + 5
    while not seen.is_set() and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.01)
    assert seen.is_set()
    qt_app.processEvents()
    assert "library/status索引" in dialog.status.text()
    previous = dialog.status.text()
    _wait(lambda: dialog.status.text() != previous, qt_app)
    assert "library/status索引" in dialog.status.text()
    release.set()
    _wait(lambda: dialog.worker is None, qt_app)
    dialog.close()
    dialog.thread_pool.waitForDone(10000)
    dialog.deleteLater()
    qt_app.processEvents()
