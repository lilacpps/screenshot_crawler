import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from zipfile import ZipFile

import pytest

import screenshot_crawler.batch.executor as batch_executor_module
from screenshot_crawler.batch import (
    BatchCandidate,
    BatchExecutionError,
    BatchExecutor,
    BatchInterruptedError,
)
from screenshot_crawler.batch.executor import _cancel_task_bounded
from screenshot_crawler.catalog import (
    CatalogService,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.core.access_guard import AccessProfile
from screenshot_crawler.core.errors import AccessResourceUnavailableError, AccessStopError
from screenshot_crawler.core.models import RunConfig
from screenshot_crawler.core.packaging import PackageResult
from screenshot_crawler.core.runner import RunResult
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.base import AccessConsumption
from screenshot_crawler.site_adapters.registry import AdapterRegistry
from screenshot_crawler.site_policies import (
    ComicDaysSitePolicy,
    MagapokeSitePolicy,
    MangaOneSitePolicy,
    SitePolicyRegistry,
)

NOW = datetime(2026, 9, 17, 15, 0, tzinfo=JST)
COMPLETED_NOW = datetime(2026, 9, 17, 15, 30, tzinfo=JST)


class FakeAdapter:
    def get_output_metadata(self) -> dict[str, str]:
        return {"title": "Adapter title", "genre": "漫画"}


class CancellationResistantResolverAdapter:
    def get_access_profile(self) -> AccessProfile:
        return AccessProfile()

    async def resolve_access_resource_candidates(
        self, *_args: object, **_kwargs: object
    ) -> None:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            await asyncio.sleep(3600)


class ImmediateStopGuard:
    def __init__(self, error: AccessStopError) -> None:
        self.error = error

    def start(self, _page: object) -> None:
        return None

    async def wait_for_stop(self) -> AccessStopError:
        return self.error

    def raise_if_stopped(self) -> None:
        return None

    async def close(self) -> None:
        return None


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
    package_calls: list[
        tuple[dict[str, str], dict[str, str], str | None, str | None]
    ] | None = None,
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
        metadata: dict[str, str],
        *,
        library_dir: str | Path,
        explicit_metadata: dict[str, str],
        artifact_prefix: str | None = None,
        artifact_disambiguator: str | None = None,
    ) -> PackageResult:
        if fail_package:
            raise RuntimeError("packaging failed")
        if package_calls is not None:
            package_calls.append(
                (metadata, explicit_metadata, artifact_prefix, artifact_disambiguator)
            )
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
    package_calls: list[
        tuple[dict[str, str], dict[str, str], str | None, str | None]
    ] = []
    candidate = replace(
        add_candidate(service, access_mode="free"),
        metadata={"title": "作品A", "order": "番外編"},
        artifact_prefix="003",
        artifact_disambiguator="mangaone-214131",
    )
    executor = make_executor(service, package_calls=package_calls)

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
    assert package_calls == [
        (
            {"title": "Adapter title", "genre": "漫画"},
            {"title": "作品A", "order": "番外編"},
            "003",
            "mangaone-214131",
        )
    ]


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


def _add_magapoke_candidate(
    service: CatalogService, *, resource: str = "work_ticket", site: str = "magapoke"
) -> BatchCandidate:
    work = service.create_work(WorkInput(work_key="magapoke-work", title="Magapoke"))
    item = service.create_item(ItemInput(order_label="Episode 1"), work_id=work.id)
    source = service.create_source(
        SourceInput(site=site, external_id=f"{site}-1", access_mode="quota"),
        item_id=item.id,
    )
    target = service.create_source_target(
        SourceTargetInput(backend="web", locator="https://example.invalid/mp-1"),
        source_id=source.id,
    )
    return BatchCandidate(
        item_id=item.id, source_id=source.id, target_id=target.id,
        site=site, backend="web", target_key=target.target_key,
        locator=target.locator, access_strategy="quota", access_mode="quota",
        reason=f"{resource}_candidate", consumes_quota=True,
        quota_resource=resource, quota_scope="work",
        quota_limit=1 if resource == "work_ticket" and site != "comicdays" else None,
        quota_commit_mode="after_observed_consumption",
    )


def _make_magapoke_executor(
    service: CatalogService,
    consumption: AccessConsumption,
    *,
    failure: BaseException | None = None,
    site: str = "magapoke",
    policy: type[MagapokeSitePolicy] = MagapokeSitePolicy,
) -> BatchExecutor:
    class ConsumingAdapter(FakeAdapter):
        def get_access_consumption(self) -> AccessConsumption:
            return consumption

    class Runner:
        def __init__(self, _config: RunConfig) -> None:
            pass

        async def run(self, _page: object, _adapter: ConsumingAdapter) -> RunResult:
            if failure is not None:
                raise failure
            return RunResult(
                pages=(), stop_state=PageState.END, stop_reason="entry_confirmed",
                entry_confirmed=True,
            )

    def package(output_dir, _metadata, *, library_dir, explicit_metadata, **_kwargs):
        archive = Path(library_dir) / "magapoke.zip"
        archive.parent.mkdir(parents=True, exist_ok=True)
        with ZipFile(archive, "w") as stream:
            stream.writestr("page.txt", "fixture")
        return PackageResult(
            archive_path=archive,
            title=explicit_metadata.get("title", "Magapoke"),
            genre="manga", volume=explicit_metadata.get("order"), author=None,
            status_path=Path(output_dir) / "status.json",
        )

    policies = SitePolicyRegistry()
    policies.register(site, policy)
    adapters = AdapterRegistry()
    adapters.register(site, ConsumingAdapter)
    return BatchExecutor(
        service, policies, adapters,
        runner_factory=Runner,  # type: ignore[arg-type]
        package_function=package,
    )


async def test_comicdays_policy_boundary_records_observed_consumption_and_keeps_grant_only_pending(
    tmp_path: Path,
) -> None:
    service = CatalogService(tmp_path / "comicdays-boundary.sqlite")
    candidate = _add_magapoke_candidate(service, site="comicdays")
    consumed_at = datetime(2026, 9, 17, 15, 12, tzinfo=JST)
    executor = _make_magapoke_executor(
        service,
        AccessConsumption(True, "work_ticket", consumed_at),
        site="comicdays",
        policy=ComicDaysSitePolicy,
    )

    result = await executor.execute_grant_only_candidate(
        object(), candidate, output_root=tmp_path / "batch", now=NOW
    )

    source = service.get_source(candidate.source_id)
    assert result.resource_consumed is True
    assert source.quota_started_at == consumed_at.isoformat()
    assert source.access_granted_until == "2026-09-20T14:12:00+09:00"
    assert service.get_item(candidate.item_id).status == "pending"
    assert service.list_artifacts() == []
    state = service.get_quota_resource_state(
        service.get_item(candidate.item_id).work_id,
        site="comicdays", resource="work_ticket",
    )
    assert state is not None and state.last_consumed_at == consumed_at.isoformat()


async def test_comicdays_policy_boundary_entry_failure_after_consumption_persists_state(
    tmp_path: Path,
) -> None:
    service = CatalogService(tmp_path / "comicdays-boundary-failure.sqlite")
    candidate = _add_magapoke_candidate(service, site="comicdays")
    consumed_at = datetime(2026, 9, 17, 15, 12, tzinfo=JST)
    executor = _make_magapoke_executor(
        service,
        AccessConsumption(True, "work_ticket", consumed_at),
        failure=RuntimeError("Comic DAYS entry failed after observed debit"),
        site="comicdays",
        policy=ComicDaysSitePolicy,
    )

    with pytest.raises(BatchExecutionError, match="observed debit"):
        await executor.execute_grant_only_candidate(
            object(), candidate, output_root=tmp_path / "batch", now=NOW
        )
    source = service.get_source(candidate.source_id)
    assert source.access_granted_until == "2026-09-20T14:12:00+09:00"
    assert service.get_item(candidate.item_id).status == "pending"
    assert service.list_artifacts() == []


async def test_work_ticket_consumption_is_recorded_at_observed_time(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = _add_magapoke_candidate(service)
    consumed_at = datetime(2026, 9, 17, 15, 12, tzinfo=JST)
    executor = _make_magapoke_executor(
        service, AccessConsumption(True, "work_ticket", consumed_at)
    )
    await executor.execute_candidate(
        object(), candidate, output_root=tmp_path / "batch",
        library_dir=tmp_path / "Books", now=NOW,
    )
    source = service.get_source(candidate.source_id)
    assert source.quota_started_at == consumed_at.isoformat()
    assert source.access_granted_until == "2026-09-20T14:12:00+09:00"
    assert service.get_item(candidate.item_id).status == "completed"
    state = service.get_quota_resource_state(
        service.get_item(candidate.item_id).work_id,
        site="magapoke",
        resource="work_ticket",
    )
    assert state is not None
    assert state.last_consumed_at == consumed_at.isoformat()

    assert executor.grant_only_skip_reason(
        candidate, now=consumed_at + timedelta(hours=1)
    ) == "work_ticket_cooldown"


async def test_mismatched_observed_resource_fails_closed_without_persistence(
    tmp_path: Path,
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = _add_magapoke_candidate(service)
    consumed_at = datetime(2026, 9, 17, 15, 12, tzinfo=JST)
    executor = _make_magapoke_executor(
        service, AccessConsumption(True, "premium_ticket", consumed_at)
    )

    with pytest.raises(BatchExecutionError, match="unexpected quota resource"):
        await executor.execute_candidate(object(), candidate, now=NOW)

    source = service.get_source(candidate.source_id)
    assert source.quota_started_at is None
    assert source.access_granted_until is None
    assert service.get_quota_resource_state(
        service.get_item(candidate.item_id).work_id,
        site="magapoke",
        resource="work_ticket",
    ) is None
    assert service.get_item(candidate.item_id).status == "pending"
    assert service.list_artifacts() == []


async def test_grant_only_work_ticket_persists_state_without_completion_or_artifact(
    tmp_path: Path,
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = _add_magapoke_candidate(service)
    consumed_at = datetime(2026, 9, 17, 15, 12, tzinfo=JST)
    executor = _make_magapoke_executor(
        service, AccessConsumption(True, "work_ticket", consumed_at)
    )

    result = await executor.execute_grant_only_candidate(
        object(), candidate, output_root=tmp_path / "batch", now=NOW
    )

    assert result.resource == "work_ticket"
    assert result.resource_consumed is True
    assert service.get_item(candidate.item_id).status == "pending"
    assert service.list_artifacts() == []
    state = service.get_quota_resource_state(
        service.get_item(candidate.item_id).work_id,
        site="magapoke",
        resource="work_ticket",
    )
    assert state is not None
    assert state.last_consumed_at == consumed_at.isoformat()
    run = service.get_crawl_run(result.crawl_run_id)
    assert run.status == "succeeded"
    assert run.page_count == 0


async def test_grant_only_premium_ticket_persists_source_only(
    tmp_path: Path,
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = _add_magapoke_candidate(service, resource="premium_ticket")
    consumed_at = datetime(2026, 9, 17, 15, 12, tzinfo=JST)
    executor = _make_magapoke_executor(
        service, AccessConsumption(True, "premium_ticket", consumed_at)
    )

    result = await executor.execute_grant_only_candidate(
        object(), candidate, output_root=tmp_path / "batch", now=NOW
    )

    source = service.get_source(candidate.source_id)
    assert result.resource == "premium_ticket"
    assert source.quota_started_at == consumed_at.isoformat()
    assert source.access_granted_until == "2026-09-20T14:12:00+09:00"
    assert service.get_quota_resource_state(
        service.get_item(candidate.item_id).work_id,
        site="magapoke",
        resource="premium_ticket",
    ) is None
    assert service.get_item(candidate.item_id).status == "pending"
    assert service.list_artifacts() == []
    run = service.get_crawl_run(result.crawl_run_id)
    assert run.status == "succeeded"
    assert run.page_count == 0


async def test_grant_only_premium_consumption_survives_later_failure(
    tmp_path: Path,
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = _add_magapoke_candidate(service, resource="premium_ticket")
    consumed_at = datetime(2026, 9, 17, 15, 12, tzinfo=JST)
    executor = _make_magapoke_executor(
        service,
        AccessConsumption(True, "premium_ticket", consumed_at),
        failure=RuntimeError("premium entry failed after consumption"),
    )

    with pytest.raises(BatchExecutionError, match="premium entry failed"):
        await executor.execute_grant_only_candidate(
            object(), candidate, output_root=tmp_path / "batch", now=NOW
        )

    source = service.get_source(candidate.source_id)
    assert source.quota_started_at == consumed_at.isoformat()
    assert source.access_granted_until == "2026-09-20T14:12:00+09:00"
    assert service.get_quota_resource_state(
        service.get_item(candidate.item_id).work_id,
        site="magapoke",
        resource="premium_ticket",
    ) is None
    assert service.get_item(candidate.item_id).status == "pending"
    assert service.list_artifacts() == []
    assert service.list_crawl_runs()[0].status == "failed"


async def test_grant_only_premium_mismatch_does_not_persist_work_consumption(
    tmp_path: Path,
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = _add_magapoke_candidate(service, resource="premium_ticket")
    consumed_at = datetime(2026, 9, 17, 15, 12, tzinfo=JST)
    executor = _make_magapoke_executor(
        service, AccessConsumption(True, "work_ticket", consumed_at)
    )

    with pytest.raises(BatchExecutionError, match="unexpected quota resource"):
        await executor.execute_grant_only_candidate(
            object(), candidate, output_root=tmp_path / "batch", now=NOW
        )

    source = service.get_source(candidate.source_id)
    assert source.quota_started_at is None
    assert source.access_granted_until is None
    assert service.get_quota_resource_state(
        service.get_item(candidate.item_id).work_id,
        site="magapoke",
        resource="work_ticket",
    ) is None
    assert service.get_quota_resource_state(
        service.get_item(candidate.item_id).work_id,
        site="magapoke",
        resource="premium_ticket",
    ) is None


async def test_grant_only_consumption_survives_later_failure(
    tmp_path: Path,
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = _add_magapoke_candidate(service)
    consumed_at = datetime(2026, 9, 17, 15, 12, tzinfo=JST)
    executor = _make_magapoke_executor(
        service,
        AccessConsumption(True, "work_ticket", consumed_at),
        failure=RuntimeError("entry flow failed after consumption"),
    )

    with pytest.raises(BatchExecutionError, match="entry flow failed"):
        await executor.execute_grant_only_candidate(
            object(), candidate, output_root=tmp_path / "batch", now=NOW
        )

    source = service.get_source(candidate.source_id)
    assert source.quota_started_at == consumed_at.isoformat()
    assert source.access_granted_until == "2026-09-20T14:12:00+09:00"
    state = service.get_quota_resource_state(
        service.get_item(candidate.item_id).work_id,
        site="magapoke",
        resource="work_ticket",
    )
    assert state is not None
    assert state.last_consumed_at == consumed_at.isoformat()
    assert service.get_item(candidate.item_id).status == "pending"
    assert service.list_artifacts() == []


async def test_premium_ticket_consumption_and_later_failure_are_persisted(
    tmp_path: Path,
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = _add_magapoke_candidate(service, resource="premium_ticket")
    consumed_at = datetime(2026, 9, 22, 22, 25, 33, tzinfo=JST)
    executor = _make_magapoke_executor(
        service,
        AccessConsumption(True, "premium_ticket", consumed_at),
        failure=RuntimeError("capture failed after Premium Ticket entry"),
    )

    with pytest.raises(BatchExecutionError, match="capture failed"):
        await executor.execute_candidate(object(), candidate, now=NOW)

    source = service.get_source(candidate.source_id)
    assert source.quota_started_at == consumed_at.isoformat()
    assert source.access_granted_until == "2026-09-25T21:25:33+09:00"
    assert service.get_item(candidate.item_id).status == "pending"
    assert service.list_artifacts() == []


async def test_successful_premium_ticket_candidate_completes_item(
    tmp_path: Path,
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = _add_magapoke_candidate(service, resource="premium_ticket")
    consumed_at = datetime(2026, 9, 22, 22, 25, 33, tzinfo=JST)
    executor = _make_magapoke_executor(
        service,
        AccessConsumption(True, "premium_ticket", consumed_at),
    )

    result = await executor.execute_candidate(
        object(), candidate, output_root=tmp_path / "batch",
        library_dir=tmp_path / "Books", now=NOW,
    )

    assert service.get_item(candidate.item_id).status == "completed"
    source = service.get_source(candidate.source_id)
    assert source.quota_started_at == consumed_at.isoformat()
    assert source.access_granted_until == "2026-09-25T21:25:33+09:00"
    assert service.get_crawl_run(result.crawl_run_id).status == "succeeded"


async def test_consumption_is_recorded_when_crawl_fails_after_entry(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = _add_magapoke_candidate(service)
    consumed_at = datetime(2026, 9, 17, 15, 12, tzinfo=JST)
    executor = _make_magapoke_executor(
        service, AccessConsumption(True, "work_ticket", consumed_at),
        failure=RuntimeError("crawl failed after entry"),
    )
    with pytest.raises(BatchExecutionError, match="crawl failed after entry"):
        await executor.execute_candidate(object(), candidate, now=NOW)
    assert service.get_source(candidate.source_id).quota_started_at == consumed_at.isoformat()
    state = service.get_quota_resource_state(
        service.get_item(candidate.item_id).work_id,
        site="magapoke",
        resource="work_ticket",
    )
    assert state is not None
    assert state.last_consumed_at == consumed_at.isoformat()
    assert service.get_item(candidate.item_id).status == "pending"
    assert service.list_artifacts() == []


async def test_grant_only_unconfirmed_failure_does_not_record_consumption(
    tmp_path: Path,
) -> None:
    service = CatalogService(tmp_path / "unconfirmed-grant.sqlite")
    candidate = _add_magapoke_candidate(service)
    executor = _make_magapoke_executor(
        service,
        AccessConsumption(),
        failure=RuntimeError("viewer confirmation failed"),
    )

    with pytest.raises(BatchExecutionError, match="viewer confirmation failed"):
        await executor.execute_grant_only_candidate(
            object(), candidate, output_root=tmp_path / "batch", now=NOW
        )

    source = service.get_source(candidate.source_id)
    assert source.quota_started_at is None
    assert source.access_granted_until is None
    assert service.get_quota_resource_state(
        service.get_item(candidate.item_id).work_id,
        site="magapoke",
        resource="work_ticket",
    ) is None
    assert service.get_item(candidate.item_id).status == "pending"


async def test_grant_only_cancellation_is_recorded_as_interrupted(
    tmp_path: Path,
) -> None:
    service = CatalogService(tmp_path / "interrupted.sqlite")
    candidate = _add_magapoke_candidate(service)
    executor = _make_magapoke_executor(
        service,
        AccessConsumption(),
        failure=asyncio.CancelledError(),
    )

    with pytest.raises(BatchInterruptedError):
        await executor.execute_grant_only_candidate(
            object(), candidate, output_root=tmp_path / "batch", now=NOW
        )

    run = service.list_crawl_runs()[0]
    assert run.status == "failed"
    assert run.error_type == "BatchInterruptedError"
    assert run.stop_reason == "interrupted"
    assert service.get_source(candidate.source_id).access_granted_until is None
    assert service.get_quota_resource_state(
        service.get_item(candidate.item_id).work_id,
        site="magapoke",
        resource="work_ticket",
    ) is None
    assert service.list_artifacts() == []


async def test_resolver_task_cleanup_is_bounded_when_cancellation_is_ignored() -> None:
    async def cancellation_resistant_operation() -> None:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            await asyncio.sleep(3600)

    operation = asyncio.create_task(cancellation_resistant_operation())
    await asyncio.sleep(0)

    await _cancel_task_bounded(operation, timeout_seconds=0.01)

    operation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await operation


async def test_resolver_timeout_is_bounded_for_cancellation_resistant_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = CatalogService(tmp_path / "resolver-timeout.sqlite")
    candidate = add_candidate(service, access_mode="quota", consumes_quota=True)
    executor = make_executor(service)
    monkeypatch.setattr(
        executor.adapters,
        "create",
        lambda _site: CancellationResistantResolverAdapter(),
    )

    async def immediate_timeout(
        tasks: set[asyncio.Task[object]], *, timeout: float, return_when: object
    ) -> tuple[set[asyncio.Task[object]], set[asyncio.Task[object]]]:
        del timeout, return_when
        await asyncio.sleep(0)
        return set(), set(tasks)

    monkeypatch.setattr(batch_executor_module.asyncio, "wait", immediate_timeout)
    original_cancel = batch_executor_module._cancel_task_bounded

    async def fast_cancel(task: asyncio.Task[object], **_kwargs: object) -> None:
        await original_cancel(task, timeout_seconds=0.01)

    monkeypatch.setattr(batch_executor_module, "_cancel_task_bounded", fast_cancel)

    with pytest.raises(BatchExecutionError, match="Access-resource resolver timed out"):
        await asyncio.wait_for(
            executor.resolve_access_resource_candidates(
                object(), [candidate], "work_ticket", timeout_ms=1
            ),
            timeout=0.5,
        )


async def test_resolver_access_guard_stop_is_bounded_for_cancellation_resistant_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = CatalogService(tmp_path / "resolver-stop.sqlite")
    candidate = add_candidate(service, access_mode="quota", consumes_quota=True)
    executor = make_executor(service)
    monkeypatch.setattr(
        executor.adapters,
        "create",
        lambda _site: CancellationResistantResolverAdapter(),
    )
    stop_error = AccessStopError(
        reason="http_403", site="mangaone", url="https://example.invalid"
    )
    stop_guard = ImmediateStopGuard(stop_error)
    monkeypatch.setattr(
        batch_executor_module.AccessGuard,
        "from_profile",
        staticmethod(lambda **_kwargs: stop_guard),
    )
    original_cancel = batch_executor_module._cancel_task_bounded

    async def fast_cancel(task: asyncio.Task[object], **_kwargs: object) -> None:
        await original_cancel(task, timeout_seconds=0.01)

    monkeypatch.setattr(batch_executor_module, "_cancel_task_bounded", fast_cancel)

    with pytest.raises(AccessStopError, match="access stop: http_403"):
        await asyncio.wait_for(
            executor.resolve_access_resource_candidates(
                object(), [candidate], "work_ticket", timeout_ms=1
            ),
            timeout=0.5,
        )


async def test_unavailable_and_already_accessible_do_not_record_consumption(
    tmp_path: Path,
) -> None:
    service = CatalogService(tmp_path / "unavailable.sqlite")
    candidate = _add_magapoke_candidate(service)
    executor = _make_magapoke_executor(
        service, AccessConsumption(),
        failure=AccessResourceUnavailableError("work_ticket_unavailable"),
    )
    with pytest.raises(AccessResourceUnavailableError):
        await executor.execute_candidate(object(), candidate, now=NOW)
    assert service.get_source(candidate.source_id).quota_started_at is None
    assert service.get_item(candidate.item_id).status == "pending"
    assert service.list_artifacts() == []
    assert service.list_crawl_runs()[0].status == "failed"

    service2 = CatalogService(tmp_path / "accessible.sqlite")
    candidate2 = _add_magapoke_candidate(service2)
    executor2 = _make_magapoke_executor(service2, AccessConsumption())
    await executor2.execute_candidate(
        object(), candidate2, output_root=tmp_path / "batch2",
        library_dir=tmp_path / "Books2", now=NOW,
    )
    assert service2.get_source(candidate2.source_id).quota_started_at is None
    assert service2.get_item(candidate2.item_id).status == "completed"
