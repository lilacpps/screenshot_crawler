"""Capture-session persistence, interruption, admission and local completion contracts."""

import asyncio
import hashlib
import io
import json
import sqlite3
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from PIL import Image

from screenshot_crawler.batch import BatchExecutor, BatchPlanner
from screenshot_crawler.batch.models import (
    BatchExecutionError,
    BatchPlanningError,
    CandidateExecutionError,
)
from screenshot_crawler.catalog import (
    CatalogService,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.core.capture import CaptureResult
from screenshot_crawler.core.errors import MaxPagesExceededError
from screenshot_crawler.core.models import CapturedPage, ContentContext, ContentIdentity, RunConfig
from screenshot_crawler.core.packaging import package_crawl_output
from screenshot_crawler.core.resume import CaptureSession, ResumeError, read_session_manifest
from screenshot_crawler.core.runner import CrawlerRunner
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.base import SiteAdapter
from screenshot_crawler.site_adapters.bookwalker.adapter import BookWalkerAdapter
from screenshot_crawler.site_adapters.bookwalker.resume import BookWalkerResumeManager
from screenshot_crawler.site_adapters.registry import AdapterRegistry
from screenshot_crawler.site_policies import BookWalkerSitePolicy, SitePolicyRegistry
from tests.helpers.acquisition_scope import synchronized_legacy_watchlist

NOW = datetime(2026, 11, 19, 12, tzinfo=JST)


def png(color="red"):
    output = io.BytesIO()
    Image.new("RGB", (4, 3), color).save(output, "PNG")
    return output.getvalue()


def new_session(tmp_path, *, seconds=590):
    return CaptureSession(
        tmp_path / uuid4().hex,
        uuid4().hex,
        {"fixture": "isolated"},
        source_url="https://example.test/viewer",
        site="test",
        seconds=seconds,
    )


def seed(session, *, count=2):
    start = len(session.store.pages) + 1
    cid = session.binding.get("cid", "cid")
    identity = ContentIdentity(page_id="1/3", page_number=1, source_id=cid)
    pages, fingerprints = [], []
    for part in range(count):
        name = Path(f"page-{start + part:04d}.png")
        data = png("red" if part == 0 else "blue")
        (session.directory / name).write_bytes(data)
        pages.append(
            CapturedPage(
                start + part,
                name,
                identity,
                4,
                3,
                metadata={"part": part + 1, "parts": count} if count > 1 else {},
            )
        )
        fingerprints.append(hashlib.sha256(data).hexdigest())
    session.store.add_pages(
        pages,
        fingerprints,
        checkpoint={"cid": cid, "current": 1, "total": 3, "layout": [10, 10, 10, 10]},
    )


@pytest.mark.parametrize(
    "damage", ["missing", "changed", "orphan", "partial_spread", "wrong_group", "identity", "path"]
)
def test_session_rejects_corruption_without_deleting_files(tmp_path, damage):
    session = new_session(tmp_path)
    seed(session)
    data = session.store.manifest
    if damage == "missing":
        (session.directory / "page-0001.png").unlink()
    elif damage == "changed":
        (session.directory / "page-0001.png").write_bytes(b"changed")
    elif damage == "orphan":
        (session.directory / "page-0099.png").write_bytes(b"uncommitted")
    elif damage == "partial_spread":
        data["pages"][0]["metadata"]["parts"] = 3
    elif damage == "wrong_group":
        data["capture_groups"][0]["start"] = 2
    elif damage == "identity":
        data["pages"][1]["identity"]["page_number"] = 2
    else:
        data["pages"][0]["file"] = "../outside.png"
    session.store.flush()
    before = set(session.directory.iterdir())
    with pytest.raises(ResumeError):
        read_session_manifest(session.directory, session.id, session.binding)
    assert set(session.directory.iterdir()) == before


def test_manifest_is_authority_when_progress_is_stale(tmp_path):
    session = new_session(tmp_path)
    seed(session)
    (session.directory / "progress.json").write_text('{"last_saved_sequence": 0}')
    loaded = CaptureSession(
        session.directory,
        session.id,
        session.binding,
        source_url="https://example.test/viewer",
        site="test",
        existing=True,
    )
    assert len(loaded.saved_pages()) == 2
    assert loaded.checkpoint["current"] == 1
    loaded.attach_context(ContentContext(content_id="cid"))
    progress = json.loads((session.directory / "progress.json").read_text())
    assert progress["content_context"]["content_id"] == "cid"
    with pytest.raises(ResumeError, match="identity"):
        read_session_manifest(session.directory, session.id, {"fixture": "other Catalog"})


class Page:
    url = "https://example.test/viewer"

    def __init__(self):
        self.closed = False
        self.events = []

    async def goto(self, url, **kwargs):
        self.url = url

    async def wait_for_timeout(self, milliseconds):
        await asyncio.sleep(0)

    def is_closed(self):
        return self.closed

    async def close(self):
        self.closed = True
        self.events.append("close")


class Adapter(SiteAdapter):
    def __init__(self, *, hold=False):
        self.index = 1
        self.session = None
        self.hold = hold

    async def configure_run(self, page, access_strategy):
        pass

    async def configure_capture_session(self, page, session):
        self.session = session

    async def initialize(self, page):
        self.session.start()
        if self.session.checkpoint:
            self.index = self.session.checkpoint["current"]

    async def detect_state(self, page):
        return PageState.END if self.index >= 3 else PageState.CONTENT

    async def get_capture_target(self, page):
        raise AssertionError("direct capture is required")

    async def capture_page(self, page):
        return (CaptureResult(png("red" if self.index == 1 else "blue"), 4, 3),)

    async def get_content_identity(self, page):
        return ContentIdentity(page_id=f"{self.index}/3", page_number=self.index, source_id="cid")

    async def get_content_context(self, page):
        return ContentContext(content_id="cid")

    async def get_resume_checkpoint(self, page):
        return {"cid": "cid", "current": self.index, "total": 3, "layout": [10, 10, 10, 10]}

    async def go_next(self, page):
        self.index += 1

    async def wait_for_change(self, page, previous_identity):
        if self.hold:
            await asyncio.sleep(10)

    def get_output_metadata(self):
        return {"title": "Synthetic", "genre": "test"}


def config(session, **kwargs):
    return RunConfig(
        "test",
        "https://example.test/viewer",
        session.directory,
        session.directory / "diagnostics",
        capture_session=session,
        page_turn_delay_ms=0,
        **kwargs,
    )


async def test_deadline_preserves_committed_page_then_resumes_without_duplicate(tmp_path):
    session = new_session(tmp_path, seconds=0.05)
    page = Page()
    paused = await CrawlerRunner(config(session)).run(page, Adapter(hold=True))
    assert page.closed and paused.stop_reason == "quota_time_budget"
    assert len(paused.pages) == 1 and session.terminal is None
    original = (session.directory / "page-0001.png").read_bytes()
    loaded = CaptureSession(
        session.directory,
        session.id,
        session.binding,
        source_url="https://example.test/viewer",
        site="test",
        existing=True,
    )
    page2 = Page()
    delays = []

    async def pace(milliseconds):
        delays.append(milliseconds)

    completed = await CrawlerRunner(config(loaded), sleep=pace).run(page2, Adapter())
    assert page2.closed and completed.stop_state is PageState.END
    assert len(completed.pages) == 2 and loaded.terminal
    assert (session.directory / "page-0001.png").read_bytes() == original
    assert [p["sequence"] for p in loaded.store.pages] == [1, 2]
    assert delays == [0, 0]  # Saved-boundary advance and the newly committed page.


async def test_resume_max_pages_applies_to_cumulative_pages(tmp_path):
    session = new_session(tmp_path)
    seed(session, count=1)
    page = Page()
    with pytest.raises(MaxPagesExceededError):
        await CrawlerRunner(config(session, max_pages=1)).run(page, Adapter())
    assert page.closed and len(session.store.pages) == 1


def test_budget_starts_once_and_uses_monotonic_clock(tmp_path):
    session = new_session(tmp_path)
    clock = [1000.0]
    session.clock = lambda: clock[0]
    assert session.started_at is None and session.seconds == 590
    session.start()
    clock[0] += 60
    session.start()
    assert session.started_at == 1000


def catalog_fixture(tmp_path, *, two=False):
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key="book", title="Synthetic", genre="test"))
    rows = []
    for order in range(1, 3 if two else 2):
        item = catalog.create_item(
            ItemInput(order_key=str(order), order_label=str(order)), work_id=work.id
        )
        source = catalog.create_source(
            SourceInput(
                site="bookwalker",
                external_id=f"00000000-0000-4000-8000-{order:012d}",
                access_mode="quota",
                available=True,
            ),
            item_id=item.id,
        )
        target = catalog.create_source_target(
            SourceTargetInput(
                backend="web", locator=f"https://bookwalker.jp/de{source.external_id}/"
            ),
            source_id=source.id,
        )
        rows.append((item, source, target))
    watchlist = synchronized_legacy_watchlist(catalog)
    policies = SitePolicyRegistry()
    policies.register("bookwalker", BookWalkerSitePolicy)
    manager = BookWalkerResumeManager(catalog)
    planner = BatchPlanner(catalog, policies, watchlist=watchlist)
    return catalog, rows, watchlist, policies, manager, planner


def test_marker_deletion_starts_new_session_without_refund_or_old_output_deletion(tmp_path):
    catalog, rows, _, _, manager, _ = catalog_fixture(tmp_path)
    _, source, target = rows[0]
    session = manager.create(source, target, NOW)
    seed(session)
    catalog.record_quota_access(source.id, quota_started_at=NOW, access_granted_until=None)
    manager.marker(source).unlink()
    assert manager.load(source, target) is None
    with pytest.raises(ResumeError, match="canonical product"):
        manager.create(
            source,
            replace(
                target, locator="https://bookwalker.jp/de00000000-0000-4000-8000-000000000099/"
            ),
            NOW,
        )
    assert not manager.marker(source).exists()
    new = manager.create(source, target, NOW)
    assert new.id != session.id and session.directory.is_dir()
    assert catalog.get_source(source.id).quota_started_at is not None


def test_planner_prioritizes_partial_before_site_quota_allocation_and_is_readonly(tmp_path):
    catalog, rows, _, _, manager, planner = catalog_fixture(tmp_path, two=True)
    _, source, target = rows[1]
    session = manager.create(source, target, NOW)
    seed(session)
    before = manager.marker(source).read_bytes(), (session.directory / "manifest.json").read_bytes()
    plan = planner.plan(site="bookwalker", now=NOW)
    assert len(plan.candidates) == 1 and plan.candidates[0].source_id == source.id
    assert plan.candidates[0].capture_session_id == session.id
    assert before == (
        manager.marker(source).read_bytes(),
        (session.directory / "manifest.json").read_bytes(),
    )
    assert catalog.get_source(source.id).quota_started_at is None
    session.finish("end", "end", {"title": "Synthetic", "genre": "test"})
    terminal_plan = planner.plan(site="bookwalker", now=NOW)
    assert terminal_plan.candidates[0].source_id == source.id
    assert terminal_plan.candidates[0].local_completion
    assert terminal_plan.quota_count == 1


def test_corrupt_reference_is_a_planning_error_before_reader_access(tmp_path):
    _, rows, _, _, manager, planner = catalog_fixture(tmp_path)
    _, source, target = rows[0]
    manager.create(source, target, NOW)
    manager.marker(source).write_text("{broken")
    with pytest.raises(BatchPlanningError, match="resume reference"):
        planner.plan(site="bookwalker", now=NOW)


async def test_local_completion_retries_without_quota_or_reader_after_catalog_failure(
    tmp_path, monkeypatch
):
    catalog, rows, watchlist, policies, manager, planner = catalog_fixture(tmp_path)
    _, source, target = rows[0]
    session = manager.create(source, target, NOW)
    seed(session)
    session.finish(PageState.END.value, "end", {"title": "Synthetic", "genre": "test"})
    catalog.record_quota_access(source.id, quota_started_at=NOW, access_granted_until=None)
    adapters = AdapterRegistry()
    # Local completion must not even instantiate an adapter or runner.
    executor = BatchExecutor(
        catalog, policies, adapters, watchlist=watchlist, library_dir=tmp_path / "Books"
    )
    candidate = planner.plan(site="bookwalker", now=NOW).candidates[0]
    assert candidate.local_completion and not candidate.consumes_quota
    finalize = catalog.finalize_successful_crawl
    monkeypatch.setattr(
        catalog,
        "finalize_successful_crawl",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("DB failed")),
    )
    with pytest.raises(CandidateExecutionError, match="DB failed"):
        await executor.execute_candidate(Page(), candidate, now=NOW)
    loaded = manager.load(source, target)
    archive = Path(loaded.info["package_intent"]["archive"])
    original = archive.read_bytes()
    monkeypatch.setattr(catalog, "finalize_successful_crawl", finalize)
    candidate2 = planner.plan(site="bookwalker", now=NOW).candidates[0]
    result = await executor.execute_candidate(Page(), candidate2, now=NOW)
    assert result.archive_path.read_bytes() == original
    assert catalog.get_item(source.item_id).status == "completed"
    assert catalog.get_source(source.id).quota_started_at == NOW.isoformat()
    assert not manager.marker(source).exists()


def test_unrelated_existing_archive_never_adopted_for_local_completion(tmp_path):
    _, rows, _, _, manager, planner = catalog_fixture(tmp_path)
    _, source, target = rows[0]
    session = manager.create(source, target, NOW)
    seed(session)
    session.finish(PageState.END.value, "end", {"title": "Synthetic", "genre": "test"})
    candidate = planner.plan(site="bookwalker", now=NOW).candidates[0]
    archive, _, _ = manager.package_paths(session, candidate, tmp_path / "Books")
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(b"user archive")
    with pytest.raises(BatchPlanningError, match="Unowned archive"):
        planner.plan(site="bookwalker", now=NOW)
    assert archive.read_bytes() == b"user archive"


@pytest.mark.parametrize("change", ["path", "catalog", "source"])
def test_reference_path_and_binding_cannot_redirect_acquisition(tmp_path, change):
    _, rows, _, _, manager, planner = catalog_fixture(tmp_path)
    _, source, target = rows[0]
    manager.create(source, target, NOW)
    marker = manager.marker(source)
    record = json.loads(marker.read_text())
    if change == "path":
        record["directory"] = "../../other-run"
    else:
        record["binding"]["catalog" if change == "catalog" else "source_id"] = "other"
    marker.write_text(json.dumps(record))
    with pytest.raises(BatchPlanningError):
        planner.plan(site="bookwalker", now=NOW)


def test_known_uncommitted_session_is_abandoned_but_old_data_and_quota_are_kept(tmp_path):
    catalog, rows, _, _, manager, _ = catalog_fixture(tmp_path)
    _, source, target = rows[0]
    session = manager.create(source, target, NOW)
    seed(session)
    catalog.record_quota_access(source.id, quota_started_at=NOW, access_granted_until=None)
    orphan = session.directory / "page-0003.png"
    orphan.write_bytes(b"unfinished spread")
    manager.abandon_if_unsafe(session)
    assert not manager.marker(source).exists()
    assert session.info["invalid"] and orphan.read_bytes() == b"unfinished spread"
    assert catalog.get_source(source.id).quota_started_at is not None


def test_disabled_partial_does_not_take_quota_from_selected_enabled_source(tmp_path):
    catalog, rows, _, _, manager, planner = catalog_fixture(tmp_path, two=True)
    _, source, target = rows[1]
    session = manager.create(source, target, NOW)
    seed(session)
    with sqlite3.connect(catalog.path) as connection:
        connection.execute("UPDATE sources SET acquisition_enabled=0 WHERE id=?", (source.id,))
    plan = planner.plan(site="bookwalker", now=NOW)
    assert [c.source_id for c in plan.candidates] == [rows[0][1].id]


async def test_changed_checkpoint_is_rejected_before_quota_and_adapter_creation(tmp_path):
    catalog, rows, watchlist, policies, manager, planner = catalog_fixture(tmp_path)
    _, source, target = rows[0]
    session = manager.create(source, target, NOW)
    seed(session)
    candidate = planner.plan(site="bookwalker", now=NOW).candidates[0]
    session.info["metadata"]["changed"] = "after preview"
    session.save_info()
    executor = BatchExecutor(catalog, policies, AdapterRegistry(), watchlist=watchlist)
    with pytest.raises(BatchExecutionError, match="checkpoint changed"):
        await executor.execute_candidate(None, candidate, now=NOW)
    assert catalog.get_source(source.id).quota_started_at is None
    assert catalog.list_crawl_runs() == []


async def test_catalog_success_with_marker_release_failure_is_not_rewritten_as_failed(
    tmp_path, monkeypatch
):
    catalog, rows, watchlist, policies, manager, planner = catalog_fixture(tmp_path)
    _, source, target = rows[0]
    session = manager.create(source, target, NOW)
    seed(session)
    session.finish("end", "end", {"title": "Synthetic", "genre": "test"})
    executor = BatchExecutor(
        catalog, policies, AdapterRegistry(), watchlist=watchlist, library_dir=tmp_path / "Books"
    )
    original = BookWalkerResumeManager.clear

    def fail_release(*args):
        raise OSError("temporary file lock")

    monkeypatch.setattr(BookWalkerResumeManager, "clear", fail_release)
    with pytest.warns(RuntimeWarning, match="retained for cleanup"):
        first = await executor.execute_candidate(
            None, planner.plan(site="bookwalker", now=NOW).candidates[0], now=NOW
        )
    assert catalog.get_crawl_run(first.crawl_run_id).status == "succeeded"
    monkeypatch.setattr(BookWalkerResumeManager, "clear", original)
    second = await executor.execute_candidate(
        None, planner.plan(site="bookwalker", now=NOW).candidates[0], now=NOW
    )
    assert second.artifact_id == first.artifact_id and second.stop_reason == "completion_cleanup"
    assert len(catalog.list_crawl_runs()) == 1


async def test_existing_zip_after_package_exception_is_verified_and_reused(tmp_path):
    catalog, rows, watchlist, policies, manager, planner = catalog_fixture(tmp_path)
    _, source, target = rows[0]
    session = manager.create(source, target, NOW)
    seed(session)
    session.finish("end", "end", {"title": "Synthetic", "genre": "test"})

    def fail_after_zip(*args, **kwargs):
        package_crawl_output(*args, **kwargs)
        raise OSError("failure after ZIP/status creation")

    executor = BatchExecutor(
        catalog,
        policies,
        AdapterRegistry(),
        watchlist=watchlist,
        library_dir=tmp_path / "Books",
        package_function=fail_after_zip,
    )
    with pytest.raises(CandidateExecutionError, match="failure after ZIP"):
        await executor.execute_candidate(
            None, planner.plan(site="bookwalker", now=NOW).candidates[0], now=NOW
        )
    assert catalog.get_item(source.item_id).status == "pending"
    executor.package_function = lambda *a, **k: pytest.fail("existing ZIP must be reused")
    result = await executor.execute_candidate(
        None, planner.plan(site="bookwalker", now=NOW).candidates[0], now=NOW
    )
    assert result.archive_path.is_file()
    assert catalog.get_source(source.id).quota_started_at is None


async def test_bookwalker_ordinary_direct_cannot_enable_resume_or_timer(tmp_path):
    adapter = BookWalkerAdapter()
    await adapter.configure_run(None, "direct")
    session = new_session(tmp_path)
    with pytest.raises(ResumeError, match="quota intent"):
        await adapter.configure_capture_session(None, session)
    session.owned_test = True
    await adapter.configure_capture_session(None, session)
    await adapter.configure_run(None, "direct")
    assert adapter._capture_session is None
    await adapter.configure_run(None, "quota")
    session.owned_test = False
    await adapter.configure_capture_session(None, session)
    assert adapter._capture_session is session


@pytest.mark.parametrize("field,value", [("cid", "other"), ("total", 20), ("layout", [1, 2, 3, 4])])
async def test_bookwalker_resume_refuses_changed_book_or_layout_before_moving(field, value):
    adapter = BookWalkerAdapter()
    expected = {"cid": "cid", "current": 3, "total": 10, "layout": [100, 100, 100, 100]}
    actual = {**expected, field: value}
    adapter._capture_session = SimpleNamespace(checkpoint=expected)

    async def checkpoint(page):
        return actual

    adapter.get_resume_checkpoint = checkpoint
    with pytest.raises(ResumeError, match="book/total/layout"):
        await adapter._restore_capture_position(object())


async def test_cli_local_completion_does_not_connect_to_chrome(tmp_path, monkeypatch):
    from screenshot_crawler import cli

    catalog, rows, watchlist, _, manager, _ = catalog_fixture(tmp_path)
    _, source, target = rows[0]
    session = manager.create(source, target, NOW)
    seed(session)
    session.finish("end", "end", {"title": "Synthetic", "genre": "test"})

    async def no_connect(*args, **kwargs):
        pytest.fail("local completion must work without Chrome")

    monkeypatch.setattr(cli.BrowserSession, "connect", no_connect)
    args = cli._parser().parse_args(
        [
            "batch",
            "run",
            "--site",
            "bookwalker",
            "--catalog",
            str(catalog.path),
            "--watchlist",
            str(watchlist.path),
            "--output-root",
            str(tmp_path / "batch"),
            "--library-dir",
            str(tmp_path / "Books"),
            "--env-file",
            str(tmp_path / "missing.env"),
        ]
    )
    await cli._run_batch_run(args)
    assert catalog.get_item(source.item_id).status == "completed"


async def test_timer_cancels_inflight_adapter_operation_without_leaking_task(tmp_path):
    cancelled = asyncio.Event()

    class HoldingAdapter(Adapter):
        async def wait_for_change(self, page, previous_identity):
            try:
                await asyncio.sleep(10)
            finally:
                cancelled.set()

    session = new_session(tmp_path, seconds=0.05)
    page = Page()
    result = await CrawlerRunner(config(session)).run(page, HoldingAdapter())
    assert result.stop_reason == "quota_time_budget" and page.closed
    assert cancelled.is_set()


def test_package_rechecks_zip_against_committed_manifest_before_catalog_success(tmp_path):
    catalog, rows, _, _, manager, planner = catalog_fixture(tmp_path)
    _, source, target = rows[0]
    session = manager.create(source, target, NOW)
    seed(session)
    session.finish("end", "end", {"title": "Synthetic", "genre": "test"})
    candidate = planner.plan(site="bookwalker", now=NOW).candidates[0]

    def changed_during_package(*args, **kwargs):
        (session.directory / "page-0001.png").write_bytes(png("green"))
        return package_crawl_output(*args, **kwargs)

    with pytest.raises(ResumeError, match="ZIP content differs"):
        manager.package(session, candidate, tmp_path / "Books", changed_during_package)
    assert catalog.get_item(source.item_id).status == "pending"
    assert catalog.list_artifacts(item_id=source.item_id) == []


async def test_entry_clock_is_started_immediately_before_control_click(tmp_path):
    session = new_session(tmp_path)
    session.owned_test = True
    adapter = BookWalkerAdapter()
    await adapter.configure_run(None, "direct")
    await adapter.configure_capture_session(None, session)
    events = []

    class Link:
        async def evaluate(self, script):
            assert session.started_at is None
            events.append("target")

        async def click(self, **kwargs):
            assert session.started_at is not None
            events.append("click")

    async def navigation(page, previous_url):
        events.append("navigation")

    adapter._wait_for_url_change = navigation
    await adapter._activate_reader_control(
        SimpleNamespace(url="https://bookwalker.jp/product"), Link()
    )
    assert events == ["target", "click", "navigation"]
