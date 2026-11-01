from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import pytest

import scripts.restore_bookwalker_quota as repair
from screenshot_crawler.catalog import (
    CatalogError,
    CatalogJobLockError,
    CatalogService,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)
from screenshot_crawler.site_policies.bookwalker import BookWalkerSitePolicy

NOW = datetime.fromisoformat("2026-09-20T08:30:00+09:00")


def make_quota_run(path: Path, *, succeeded: bool = False) -> tuple[CatalogService, int, int]:
    service = CatalogService(path)
    work = service.create_work(WorkInput(work_key="bookwalker-series", title="作品"))
    item = service.create_item(ItemInput(order_label="第1巻"), work_id=work.id)
    source = service.create_source(
        SourceInput(
            site="bookwalker",
            external_id="book-1",
            access_mode="quota",
            quota_started_at=NOW,
        ),
        item_id=item.id,
    )
    target = service.create_source_target(
        SourceTargetInput(backend="web", locator="https://bookwalker.example/debook-1/"),
        source_id=source.id,
    )
    run = service.create_crawl_run(
        item_id=item.id,
        source_id=source.id,
        target_id=target.id,
        access_strategy="quota",
        started_at=NOW,
    )
    if succeeded:
        service.mark_crawl_run_succeeded(run.id, page_count=1, stop_reason="end")
        service.mark_item_completed(item.id)
    else:
        service.mark_crawl_run_failed(run.id, error_type="CancelledError")
    return service, source.id, run.id


def test_restore_script_is_dry_run_by_default(tmp_path: Path, monkeypatch) -> None:
    service, source_id, _ = make_quota_run(tmp_path / "catalog.sqlite")
    monkeypatch.setattr(repair, "now_jst", lambda: NOW)

    assert repair.main(["--catalog", str(service.path)]) == 0
    assert service.get_source(source_id).quota_started_at == NOW.isoformat()
    assert list((tmp_path / "backup").glob("*.sqlite")) == []


@pytest.mark.parametrize("succeeded", [False, True])
def test_restore_script_restores_one_slot_without_backup_or_history_changes(
    tmp_path: Path, monkeypatch, succeeded: bool
) -> None:
    service, source_id, run_id = make_quota_run(
        tmp_path / "catalog.sqlite", succeeded=succeeded
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(repair, "now_jst", lambda: NOW)
    original_run = service.get_crawl_run(run_id)
    original_item = service.get_item(original_run.item_id)
    policy = BookWalkerSitePolicy()
    assert policy.available_quota(service.list_sources(site="bookwalker"), NOW) == 0

    assert repair.main(
        [
            "--catalog",
            str(service.path),
            "--apply",
        ]
    ) == 0

    source = service.get_source(source_id)
    assert source.quota_started_at is None
    assert source.access_granted_until is None
    assert service.get_crawl_run(run_id) == original_run
    assert service.get_item(original_run.item_id) == original_item
    assert source.access_mode == "quota"
    assert not (tmp_path / "backup").exists()
    assert policy.available_quota(service.list_sources(site="bookwalker"), NOW) == 1
    # Repeating the command never accumulates extra permission.
    assert repair.main(["--catalog", str(service.path), "--apply"]) == 0
    assert policy.available_quota(service.list_sources(site="bookwalker"), NOW) == 1


@pytest.mark.parametrize("started_at", [
    "2026-09-20T04:59:59+09:00",  # Previous window at NOW.
    "2026-09-21T05:00:00+09:00",  # Future window at NOW.
])
def test_restore_script_preserves_other_windows(tmp_path: Path, monkeypatch, started_at: str) -> None:
    service, source_id, _ = make_quota_run(tmp_path / "catalog.sqlite")
    service.record_quota_access(source_id, quota_started_at=started_at, access_granted_until=None)
    monkeypatch.setattr(repair, "now_jst", lambda: NOW)
    before = service.get_source(source_id)

    assert repair.main(["--catalog", str(service.path), "--apply"]) == 0
    assert service.get_source(source_id) == before


def test_restore_script_accepts_equivalent_utc_timestamp(tmp_path: Path, monkeypatch) -> None:
    service, source_id, _ = make_quota_run(tmp_path / "catalog.sqlite")
    # The lower bound is included; the preceding test covers the instant before it.
    service.record_quota_access(
        source_id, quota_started_at="2026-09-19T20:00:00+00:00", access_granted_until=None
    )
    monkeypatch.setattr(repair, "now_jst", lambda: NOW)

    assert repair.main(["--catalog", str(service.path), "--apply"]) == 0
    assert service.get_source(source_id).quota_started_at is None


def test_restore_script_rejects_multiple_reservations_without_changes(
    tmp_path: Path, monkeypatch,
) -> None:
    service, _, run_id = make_quota_run(tmp_path / "catalog.sqlite")
    service.create_source(
        SourceInput(site="bookwalker", external_id="book-2", access_mode="quota", quota_started_at=NOW),
        item_id=service.get_crawl_run(run_id).item_id,
    )
    monkeypatch.setattr(repair, "now_jst", lambda: NOW)
    before = service.list_sources(site="bookwalker")

    with pytest.raises(CatalogError, match="Multiple current-window"):
        repair.main(["--catalog", str(service.path), "--apply"])
    assert service.list_sources(site="bookwalker") == before


def test_restore_script_preserves_other_sites(tmp_path: Path, monkeypatch) -> None:
    service, source_id, run_id = make_quota_run(tmp_path / "catalog.sqlite")
    other = service.create_source(
        SourceInput(site="mangaone", external_id="chapter-1", access_mode="quota", quota_started_at=NOW),
        item_id=service.get_crawl_run(run_id).item_id,
    )
    monkeypatch.setattr(repair, "now_jst", lambda: NOW)

    assert repair.main(["--catalog", str(service.path), "--apply"]) == 0
    assert service.get_source(source_id).quota_started_at is None
    assert service.get_source(other.id) == other


def test_restore_script_does_not_create_missing_catalog(tmp_path: Path) -> None:
    missing = tmp_path / "missing.sqlite"
    with pytest.raises(CatalogError, match="does not exist"):
        repair.main(["--catalog", str(missing), "--apply"])
    assert not missing.exists()


def test_restore_script_refuses_an_active_catalog_job(tmp_path: Path, monkeypatch) -> None:
    service, source_id, _ = make_quota_run(tmp_path / "catalog.sqlite")
    monkeypatch.setattr(repair, "now_jst", lambda: NOW)
    before = service.get_source(source_id)
    with service.job_lock(), ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(repair.main, ["--catalog", str(service.path), "--apply"])
        with pytest.raises(CatalogJobLockError, match="Another job"):
            result.result(timeout=5)
    assert service.get_source(source_id) == before
