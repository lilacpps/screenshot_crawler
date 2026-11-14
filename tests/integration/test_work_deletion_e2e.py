import hashlib
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile

import pytest

from screenshot_crawler.batch import BatchPlanner
from screenshot_crawler.batch.naming import archive_metadata_for_catalog, archive_stem
from screenshot_crawler.catalog import ArtifactInput, CatalogService
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.core.packaging import package_crawl_output
from screenshot_crawler.discovery import DiscoveryAdapterRegistry, DiscoveryService
from screenshot_crawler.maintenance.work_deletion import WorkDeletionPreviewService
from screenshot_crawler.site_policies import MangaOneSitePolicy, SitePolicyRegistry
from screenshot_crawler.watchlist import WatchlistTarget
from screenshot_crawler.watchlist.service import WatchlistService
from tests.unit.test_batch_executor import EmptyManifestRunner, make_executor
from tests.unit.test_discovery import FakeDiscoveryAdapter, FakePage, record


@pytest.mark.asyncio
async def test_delete_reregister_full_and_batch_reuse_exact_archive_path(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.sqlite"
    watchlist_path = tmp_path / "watchlist.yaml"
    management_path = tmp_path / "management.sqlite"
    library_dir = tmp_path / "Books"
    status_root = tmp_path / "crawl-status"
    trash_root = tmp_path / "trash"
    catalog = CatalogService(catalog_path)
    watchlist = WatchlistService(watchlist_path)
    watchlist.add(
        key="recycle-scope", work_key="recycled", site="mangaone",
        url="https://example.test/recycle", label="Recycled",
    )
    adapter = FakeDiscoveryAdapter([record("episode-1", title="Recycled", genre="manga", order_key="1")])
    registry = DiscoveryAdapterRegistry()
    registry.register("mangaone", lambda: adapter)
    discovery = DiscoveryService(catalog, registry)
    target = WatchlistTarget(
        key="recycle-scope", work_key="recycled", site="mangaone",
        url="https://example.test/recycle", label="Recycled",
    )
    first = await discovery.discover(FakePage(), target, "full")
    assert first.complete
    old_work = catalog.find_work("recycled")
    assert old_work is not None
    old_item = catalog.list_items()[0]
    old_source = catalog.list_sources()[0]
    metadata = archive_metadata_for_catalog(old_work, old_item, old_source)
    stem, title, genre, _order, _author = archive_stem(metadata)
    # Match the production package naming emitted by Batch for order 1.
    old_archive = library_dir / genre / title / f"001-{stem}.zip"
    old_archive.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(old_archive, "w") as archive:
        archive.writestr("page-0001.png", b"old synthetic page")
    old_bytes = old_archive.read_bytes()
    run = catalog.create_crawl_run(
        item_id=old_item.id, source_id=old_source.id,
        target_id=catalog.list_source_targets()[0].id,
        access_strategy="direct", started_at=datetime(2026, 11, 14, tzinfo=JST),
    )
    catalog.finalize_successful_crawl(
        run.id,
        artifact=ArtifactInput(
            kind="archive", format="zip", sha256=hashlib.sha256(old_bytes).hexdigest(),
            byte_size=len(old_bytes), storage_backend="filesystem",
            locator=old_archive.as_posix(), state="present",
        ),
        page_count=1, stop_reason="end", finished_at=datetime(2026, 11, 14, tzinfo=JST),
    )
    status_path = status_root / genre / title / f"{old_archive.stem}.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text('{"status":"completed","archive_path":"' + old_archive.as_posix() + '"}', encoding="utf-8")
    with management_path.open("wb") as handle:
        handle.write(b"")
    import sqlite3
    with sqlite3.connect(management_path) as connection:
        connection.execute("CREATE TABLE jobs(job_id TEXT, state TEXT, selected_keys_json TEXT)")
    service = WorkDeletionPreviewService()
    service.bind_management_stores(catalog_path, [management_path])
    plan = service.preview(
        "recycled", catalog_path=catalog_path, watchlist_path=watchlist_path,
        management_paths=(management_path,), library_root=library_dir,
        status_root=status_root, trash_root=trash_root,
    )
    assert plan.ready and plan.zip_count == 1
    deleted = service.apply(plan)
    assert deleted.status == "DONE"
    assert not old_archive.exists() and not status_path.exists()
    assert (trash_root / deleted.operation_id).exists()
    assert catalog.find_work("recycled") is None

    adapter.records = [record("episode-2", title="Recycled", genre="manga", order_key="1")]
    watchlist.add(
        key="recycle-scope-2", work_key="recycled", site="mangaone",
        url="https://example.test/recycle-2", label="Recycled",
    )
    target2 = WatchlistTarget(
        key="recycle-scope-2", work_key="recycled", site="mangaone",
        url="https://example.test/recycle-2", label="Recycled",
    )
    second = await discovery.discover(FakePage(), target2, "full")
    assert second.complete
    policies = SitePolicyRegistry()
    policies.register("mangaone", MangaOneSitePolicy)
    batch = BatchPlanner(catalog, policies, watchlist=watchlist, library_dir=library_dir).plan(
        site="mangaone", selected_keys=("recycle-scope-2",)
    )
    assert len(batch.candidates) == 1
    executor = make_executor(catalog)
    executor.watchlist = watchlist
    executor.library_dir = library_dir
    executor.package_function = package_crawl_output
    executor.runner_factory = EmptyManifestRunner  # type: ignore[assignment]
    result = await executor.execute_candidate(
        object(), batch.candidates[0], output_root=tmp_path / "second-run",
        library_dir=library_dir, now=datetime(2026, 11, 14, 1, 0, tzinfo=JST),
    )
    assert result.archive_path == old_archive
    assert old_archive.read_bytes() != old_bytes
    assert old_archive.is_file()
    assert catalog.find_work("recycled") is not None
