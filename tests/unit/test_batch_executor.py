from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pytest

from screenshot_crawler.batch import (
    BatchCandidate,
    BatchExecutionError,
    BatchExecutor,
)
from screenshot_crawler.catalog import CatalogService, ItemInput, SourceInput
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.core.models import RunConfig
from screenshot_crawler.core.packaging import PackageResult
from screenshot_crawler.core.runner import RunResult
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.registry import AdapterRegistry
from screenshot_crawler.site_policies import MangaOneSitePolicy, SitePolicyRegistry

NOW = datetime(2026, 9, 17, 15, 0, tzinfo=JST)
COMPLETED_NOW = datetime(2026, 9, 17, 15, 30, tzinfo=JST)


class FakeAdapter:
    def get_output_metadata(self) -> dict[str, str]:
        return {"title": "Adapter title", "genre": "漫画"}


class FakeRunner:
    def __init__(self, config: RunConfig, *, catalog: CatalogService, fail: bool = False) -> None:
        self.config = config
        self.catalog = catalog
        self.fail = fail

    async def run(self, _page: object, _adapter: FakeAdapter) -> RunResult:
        if self.fail:
            raise RuntimeError("crawler failed")
        return RunResult(pages=(), stop_state=PageState.END, stop_reason="end")


def make_executor(
    service: CatalogService,
    *,
    fail_crawl: bool = False,
    fail_package: bool = False,
    configs: list[RunConfig] | None = None,
    before_run: Callable[[RunConfig], None] | None = None,
) -> BatchExecutor:
    policies = SitePolicyRegistry()
    policies.register("mangaone", MangaOneSitePolicy)
    adapters = AdapterRegistry()
    adapters.register("mangaone", FakeAdapter)

    def runner_factory(config: RunConfig) -> FakeRunner:
        if configs is not None:
            configs.append(config)
        if before_run is not None:
            before_run(config)
        return FakeRunner(config, catalog=service, fail=fail_crawl)

    def package_function(
        output_dir: Path,
        _metadata: dict[str, str],
        *,
        library_dir: str | Path,
        explicit_metadata: dict[str, str],
    ) -> PackageResult:
        if fail_package:
            raise RuntimeError("packaging failed")
        archive_path = Path(library_dir) / "漫画" / "作品A" / "archive.zip"
        return PackageResult(
            archive_path=archive_path,
            title=explicit_metadata["title"],
            genre="漫画",
            volume=explicit_metadata["order"],
            author=None,
            status_path=output_dir / "status.json",
        )

    return BatchExecutor(
        service,
        policies,
        adapters,
        runner_factory=runner_factory,
        package_function=package_function,
    )


def add_candidate(
    service: CatalogService,
    *,
    access_mode: str,
    consumes_quota: bool = False,
    access_granted_until: str | None = None,
) -> BatchCandidate:
    item = service.create_item(
        ItemInput(canonical_title="作品A", order_label="第01話")
    )
    source = service.create_source(
        SourceInput(
            site="mangaone",
            external_id=f"chapter-{item.id}",
            url=f"https://example.invalid/chapter/{item.id}",
            access_mode=access_mode,
            available=True,
            access_granted_until=access_granted_until,
        ),
        item_id=item.id,
    )
    return BatchCandidate(
        item_id=item.id,
        source_id=source.id,
        site=source.site,
        url=source.url,
        access_strategy="quota" if consumes_quota else "direct",
        metadata={"title": "作品A", "order": "第01話"},
        access_mode=access_mode,
        consumes_quota=consumes_quota,
    )


@pytest.mark.parametrize("access_mode", ["free", "owned"])
async def test_direct_candidate_runs_and_completes_without_quota_state(
    tmp_path: Path, access_mode: str
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = add_candidate(service, access_mode=access_mode)
    configs: list[RunConfig] = []
    executor = make_executor(service, configs=configs)

    result = await executor.execute_candidate(
        object(),
        candidate,
        output_root=tmp_path / "batch",
        library_dir=tmp_path / "Books",
        now=NOW,
    )

    assert configs[0].access_strategy == "direct"
    assert configs[0].output_metadata == candidate.metadata
    assert result.archive_path == tmp_path / "Books" / "漫画" / "作品A" / "archive.zip"
    item = service.get_item(candidate.item_id)
    assert item.status == "completed"
    assert item.local_path == result.archive_path.as_posix()
    source = service.get_source(candidate.source_id)
    assert source.quota_started_at is None
    assert source.access_granted_until is None


async def test_quota_state_is_persisted_before_crawl_and_granted_for_24_hours(
    tmp_path: Path,
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = add_candidate(service, access_mode="quota", consumes_quota=True)
    configs: list[RunConfig] = []
    observed_sources = []
    executor = make_executor(
        service,
        configs=configs,
        before_run=lambda _config: observed_sources.append(
            service.get_source(candidate.source_id)
        ),
    )

    result = await executor.execute_candidate(
        object(),
        candidate,
        output_root=tmp_path / "batch",
        library_dir=tmp_path / "Books",
        now=NOW,
    )

    source = service.get_source(candidate.source_id)
    assert source.quota_started_at == NOW.isoformat()
    assert source.access_granted_until == "2026-09-18T15:00:00+09:00"
    assert observed_sources[0].quota_started_at == NOW.isoformat()
    assert observed_sources[0].access_granted_until == "2026-09-18T15:00:00+09:00"
    assert configs[0].access_strategy == "quota"
    assert service.get_item(candidate.item_id).status == "completed"
    assert result.archive_path.exists() is False


async def test_completed_at_uses_completion_time_not_plan_start_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = add_candidate(service, access_mode="free")
    monkeypatch.setattr(
        "screenshot_crawler.catalog.service.now_jst", lambda: COMPLETED_NOW
    )
    executor = make_executor(service)

    await executor.execute_candidate(
        object(),
        candidate,
        output_root=tmp_path / "batch",
        library_dir=tmp_path / "Books",
        now=NOW,
    )

    item = service.get_item(candidate.item_id)
    assert item.completed_at == COMPLETED_NOW.isoformat()
    assert item.completed_at != NOW.isoformat()


async def test_active_grant_direct_candidate_does_not_change_quota_state(
    tmp_path: Path,
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = add_candidate(
        service,
        access_mode="quota",
        access_granted_until="2026-09-17T16:00:00+09:00",
    )
    executor = make_executor(service)

    await executor.execute_candidate(
        object(),
        candidate,
        output_root=tmp_path / "batch",
        library_dir=tmp_path / "Books",
        now=NOW,
    )

    source = service.get_source(candidate.source_id)
    assert source.quota_started_at is None
    assert source.access_granted_until == "2026-09-17T16:00:00+09:00"


async def test_quota_state_remains_when_crawl_fails(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = add_candidate(service, access_mode="quota", consumes_quota=True)
    executor = make_executor(service, fail_crawl=True)

    with pytest.raises(BatchExecutionError, match="crawler failed"):
        await executor.execute_candidate(object(), candidate, now=NOW)

    source = service.get_source(candidate.source_id)
    assert source.quota_started_at == NOW.isoformat()
    assert source.access_granted_until == "2026-09-18T15:00:00+09:00"
    assert service.get_item(candidate.item_id).status == "pending"


async def test_packaging_failure_does_not_complete_item(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = add_candidate(service, access_mode="quota", consumes_quota=True)
    executor = make_executor(service, fail_package=True)

    with pytest.raises(BatchExecutionError, match="packaging failed"):
        await executor.execute_candidate(object(), candidate, now=NOW)

    assert service.get_item(candidate.item_id).status == "pending"
    assert service.get_source(candidate.source_id).quota_started_at == NOW.isoformat()


async def test_direct_failure_does_not_complete_item_or_write_quota_state(
    tmp_path: Path,
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = add_candidate(service, access_mode="free")
    executor = make_executor(service, fail_crawl=True)

    with pytest.raises(BatchExecutionError, match="crawler failed"):
        await executor.execute_candidate(object(), candidate, now=NOW)

    assert service.get_item(candidate.item_id).status == "pending"
    source = service.get_source(candidate.source_id)
    assert source.quota_started_at is None
    assert source.access_granted_until is None


@pytest.mark.parametrize("stale_state", ["completed", "unavailable", "url", "access_mode"])
async def test_stale_candidate_does_not_start_crawler(
    tmp_path: Path, stale_state: str
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = add_candidate(service, access_mode="free")
    expected_status = "pending"
    if stale_state == "completed":
        service.mark_item_completed(candidate.item_id, "library/archive.zip")
        expected_status = "completed"
    elif stale_state == "unavailable":
        service.update_source_external_state(
            "mangaone", f"chapter-{candidate.item_id}", available=False
        )
    elif stale_state == "url":
        service.update_source_external_state(
            "mangaone",
            f"chapter-{candidate.item_id}",
            url="https://example.invalid/changed",
        )
    else:
        service.update_source_external_state(
            "mangaone",
            f"chapter-{candidate.item_id}",
            access_mode="owned",
        )
    configs: list[RunConfig] = []
    executor = make_executor(service, configs=configs)

    with pytest.raises(BatchExecutionError, match="stale batch candidate"):
        await executor.execute_candidate(object(), candidate, now=NOW)

    assert configs == []
    assert service.get_item(candidate.item_id).status == expected_status


def test_batch_output_directory_is_unique_and_windows_safe(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = add_candidate(service, access_mode="free")
    executor = make_executor(service)

    first = executor  # Keep construction covered without running a real crawl.
    del first
    from screenshot_crawler.batch.executor import _new_output_dir

    path_a = _new_output_dir(tmp_path / "batch", candidate, NOW)
    path_b = _new_output_dir(tmp_path / "batch", candidate, NOW)
    assert path_a != path_b
    assert path_a.parent == tmp_path / "batch" / "mangaone"
    assert all(part not in path_a.name for part in '<>:/\\|?*')
