from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile

import pytest

from screenshot_crawler.batch import (
    BatchCandidate,
    BatchExecutionError,
    BatchExecutor,
)
from screenshot_crawler.catalog import (
    CatalogService,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)
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
    missing_archive: bool = False,
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
        artifact_disambiguator: str | None = None,
    ) -> PackageResult:
        if fail_package:
            raise RuntimeError("packaging failed")
        suffix = f"-{artifact_disambiguator}" if artifact_disambiguator else ""
        archive_path = Path(library_dir) / "漫画" / "作品A" / f"archive{suffix}.zip"
        if not missing_archive:
            archive_path.parent.mkdir(parents=True, exist_ok=True)
            with ZipFile(archive_path, "w") as archive:
                archive.writestr("archive.txt", "test archive")
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
    work = service.create_work(WorkInput(work_key=f"work-{access_mode}", title="作品A"))
    item = service.create_item(
        ItemInput(order_label="第01話"), work_id=work.id
    )
    source = service.create_source(
        SourceInput(
            site="mangaone",
            external_id=f"chapter-{item.id}",
            access_mode=access_mode,
            available=True,
            access_granted_until=access_granted_until,
        ),
        item_id=item.id,
    )
    target = service.create_source_target(
        SourceTargetInput(
            backend="web", locator=f"https://example.invalid/chapter/{item.id}"
        ),
        source_id=source.id,
    )
    return BatchCandidate(
        item_id=item.id,
        source_id=source.id,
        target_id=target.id,
        site=source.site,
        backend=target.backend,
        target_key=target.target_key,
        locator=target.locator,
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
    assert configs[0].source_url == candidate.locator
    assert configs[0].output_metadata == candidate.metadata
    assert result.archive_path == tmp_path / "Books" / "漫画" / "作品A" / "archive.zip"
    item = service.get_item(candidate.item_id)
    assert item.status == "completed"
    artifact = service.list_artifacts(crawl_run_id=result.crawl_run_id)[0]
    assert artifact.id == result.artifact_id
    assert artifact.locator == result.archive_path.as_posix()
    assert artifact.state == "present"
    run = service.get_crawl_run(result.crawl_run_id)
    assert run.status == "succeeded"
    assert (run.item_id, run.source_id, run.target_id) == (
        candidate.item_id,
        candidate.source_id,
        candidate.target_id,
    )
    assert (run.site_snapshot, run.external_id_snapshot) == (
        candidate.site,
        f"chapter-{candidate.item_id}",
    )
    assert (run.backend_snapshot, run.target_key_snapshot, run.locator_snapshot) == (
        candidate.backend,
        candidate.target_key,
        candidate.locator,
    )
    assert artifact.sha256
    assert artifact.byte_size == result.archive_path.stat().st_size
    source = service.get_source(candidate.source_id)
    assert source.quota_started_at is None
    assert source.access_granted_until is None


async def test_artifact_disambiguator_is_forwarded_to_packaging(
    tmp_path: Path,
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = replace(
        add_candidate(service, access_mode="free"),
        metadata={"title": "作品A", "order": "おまけ"},
        artifact_disambiguator="mangaone-214131",
    )
    executor = make_executor(service)

    result = await executor.execute_candidate(
        object(),
        candidate,
        output_root=tmp_path / "batch",
        library_dir=tmp_path / "Books",
        now=NOW,
    )

    assert result.archive_path == (
        tmp_path / "Books" / "漫画" / "作品A" / "archive-mangaone-214131.zip"
    )


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
    assert result.archive_path.exists() is True


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


async def test_abnormal_stop_fails_run_without_artifact(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = add_candidate(service, access_mode="free")

    class AbnormalRunner(FakeRunner):
        def __init__(self, config: RunConfig) -> None:
            super().__init__(config, catalog=service)

        async def run(self, page: object, adapter: FakeAdapter) -> RunResult:
            del page, adapter
            return RunResult(pages=(), stop_state=PageState.UNKNOWN, stop_reason="unknown")

    executor = make_executor(service)
    executor.runner_factory = AbnormalRunner
    with pytest.raises(BatchExecutionError, match="did not stop normally"):
        await executor.execute_candidate(object(), candidate, now=NOW)

    run = service.list_crawl_runs()[0]
    assert run.status == "failed"
    assert run.page_count == 0
    assert run.stop_reason == "unknown"
    assert service.get_item(candidate.item_id).status == "pending"
    assert service.list_artifacts() == []


async def test_missing_archive_fails_run_without_artifact(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = add_candidate(service, access_mode="free")
    executor = make_executor(service, missing_archive=True)

    with pytest.raises(BatchExecutionError, match="archive"):
        await executor.execute_candidate(object(), candidate, now=NOW)

    assert service.list_crawl_runs()[0].status == "failed"
    assert service.list_artifacts() == []
    assert service.get_item(candidate.item_id).status == "pending"


async def test_archive_hash_failure_fails_run_without_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = add_candidate(service, access_mode="free")
    executor = make_executor(service)

    def fail_hash(path: Path) -> tuple[str, int]:
        raise OSError(f"hash failed: {path}")

    monkeypatch.setattr("screenshot_crawler.batch.executor._hash_archive", fail_hash)
    with pytest.raises(BatchExecutionError, match="hash failed"):
        await executor.execute_candidate(
            object(),
            candidate,
            output_root=tmp_path / "batch",
            library_dir=tmp_path / "Books",
            now=NOW,
        )

    assert service.list_crawl_runs()[0].status == "failed"
    assert service.list_artifacts() == []
    assert service.get_item(candidate.item_id).status == "pending"
    assert (tmp_path / "Books" / "漫画" / "作品A" / "archive.zip").exists()


async def test_success_finalize_failure_keeps_archive_and_fails_run(
    tmp_path: Path,
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = add_candidate(service, access_mode="free")
    executor = make_executor(service)

    def fail_finalize(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("finalize failed")

    executor.catalog.finalize_successful_crawl = fail_finalize  # type: ignore[method-assign]
    with pytest.raises(BatchExecutionError, match="finalize failed"):
        await executor.execute_candidate(
            object(),
            candidate,
            output_root=tmp_path / "batch",
            library_dir=tmp_path / "Books",
            now=NOW,
        )

    run = service.list_crawl_runs()[0]
    assert run.status == "failed"
    assert service.get_item(candidate.item_id).status == "pending"
    assert service.list_artifacts() == []
    assert (tmp_path / "Books" / "漫画" / "作品A" / "archive.zip").exists()


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


@pytest.mark.parametrize(
    "stale_state",
    ["completed", "unavailable", "locator", "disabled_target", "target_key", "access_mode"],
)
async def test_stale_candidate_does_not_start_crawler(
    tmp_path: Path, stale_state: str
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = add_candidate(service, access_mode="free")
    expected_status = "pending"
    if stale_state == "completed":
        service.mark_item_completed(candidate.item_id)
        expected_status = "completed"
    elif stale_state == "unavailable":
        service.update_source_external_state(
            "mangaone", f"chapter-{candidate.item_id}", available=False
        )
    elif stale_state == "locator":
        service.upsert_source_target(
            SourceTargetInput(backend="web", locator="https://example.invalid/changed"),
            source_id=candidate.source_id,
        )
    elif stale_state == "disabled_target":
        service.upsert_source_target(
            SourceTargetInput(backend="web", locator=candidate.locator, enabled=False),
            source_id=candidate.source_id,
        )
    elif stale_state == "target_key":
        with service._connection() as connection:
            connection.execute(
                "UPDATE source_targets SET target_key = 'direct' WHERE id = ?",
                (candidate.target_id,),
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
    assert service.list_crawl_runs() == []
    assert service.list_artifacts() == []


async def test_wrong_backend_is_rejected_before_web_runner(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = add_candidate(service, access_mode="free")
    executor = make_executor(service)

    with pytest.raises(BatchExecutionError, match="unsupported batch backend"):
        await executor.execute_candidate(
            object(), replace(candidate, backend="android"), now=NOW
        )

    assert service.get_item(candidate.item_id).status == "pending"
    assert service.list_crawl_runs() == []


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
