from datetime import datetime
from pathlib import Path

import scripts.restore_bookwalker_quota as repair
from screenshot_crawler.catalog import (
    CatalogService,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)

NOW = datetime.fromisoformat("2026-09-20T08:30:00+09:00")


def make_failed_quota_run(path: Path) -> tuple[CatalogService, int, int]:
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
    service.mark_crawl_run_failed(run.id, error_type="CancelledError")
    return service, source.id, run.id


def test_restore_script_is_dry_run_by_default(tmp_path: Path, monkeypatch) -> None:
    service, source_id, run_id = make_failed_quota_run(tmp_path / "catalog.sqlite")
    monkeypatch.setattr(repair, "now_jst", lambda: NOW)

    assert repair.main(["--catalog", str(service.path), "--crawl-run-id", str(run_id)]) == 0
    assert service.get_source(source_id).quota_started_at == NOW.isoformat()
    assert list((tmp_path / "backup").glob("*.sqlite")) == []


def test_restore_script_backs_up_and_clears_only_local_quota_state(
    tmp_path: Path, monkeypatch
) -> None:
    service, source_id, run_id = make_failed_quota_run(tmp_path / "catalog.sqlite")
    monkeypatch.setattr(repair, "now_jst", lambda: NOW)
    backup_dir = tmp_path / "backup"

    assert repair.main(
        [
            "--catalog",
            str(service.path),
            "--crawl-run-id",
            str(run_id),
            "--backup-dir",
            str(backup_dir),
            "--apply",
        ]
    ) == 0

    source = service.get_source(source_id)
    assert source.quota_started_at is None
    assert source.access_granted_until is None
    assert service.get_crawl_run(run_id).status == "failed"
    assert len(list(backup_dir.glob("*.sqlite"))) == 1
