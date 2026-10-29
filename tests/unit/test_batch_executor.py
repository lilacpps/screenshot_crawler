import asyncio
import hashlib
import importlib.util
import json
import sys
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
    BatchPlanner,
)
from screenshot_crawler.batch.archive_guard import ArchiveHistoryWarning
from screenshot_crawler.batch.executor import (
    _cancel_task_bounded,
    _write_success_entry_trace,
)
from screenshot_crawler.batch.naming import archive_metadata_for_catalog
from screenshot_crawler.catalog import (
    ArtifactInput,
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
from screenshot_crawler.core.packaging import (
    PackageResult,
    archive_stem,
    package_crawl_output,
)
from screenshot_crawler.core.runner import RunResult
from screenshot_crawler.core.state import PageState
from screenshot_crawler.runtime_settings import SiteRuntimeSettings, load_runtime_settings
from screenshot_crawler.site_adapters.base import AccessConsumption, AccessResourceResolution
from screenshot_crawler.site_adapters.comicdays.adapter import ComicDaysAdapter
from screenshot_crawler.site_adapters.registry import AdapterRegistry
from screenshot_crawler.site_policies import (
    ComicDaysSitePolicy,
    HanayumeSitePolicy,
    MagapokeSitePolicy,
    MangaOneSitePolicy,
    PiccomaSitePolicy,
    SitePolicyRegistry,
    YounganimalSitePolicy,
)
from tests.helpers.acquisition_scope import synchronized_legacy_watchlist

NOW = datetime(2026, 9, 17, 15, 0, tzinfo=JST)
COMPLETED_NOW = datetime(2026, 9, 17, 15, 30, tzinfo=JST)


class FakeAdapter:
    def get_output_metadata(self) -> dict[str, str]:
        return {"title": "Adapter title", "genre": "漫画"}

    async def collect_debug_metadata(self, _page: object) -> dict[str, object]:
        return {"ticket_trace": [{"phase": "entry_success"}]}


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
    def __init__(
        self,
        config: RunConfig,
        *,
        catalog: CatalogService,
        fail: bool = False,
        during_run: Callable[[RunConfig], None] | None = None,
    ) -> None:
        self.config = config
        self.catalog = catalog
        self.fail = fail
        self.during_run = during_run

    async def run(self, _page: object, _adapter: FakeAdapter) -> RunResult:
        if self.during_run is not None:
            self.during_run(self.config)
        if self.fail:
            raise RuntimeError("crawler failed")
        return RunResult(pages=(), stop_state=PageState.END, stop_reason="end")


class EmptyManifestRunner:
    def __init__(self, config: RunConfig) -> None:
        self.config = config

    async def run(self, _page: object, _adapter: FakeAdapter) -> RunResult:
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        (self.config.output_dir / "page-0001.png").write_bytes(b"synthetic page")
        (self.config.output_dir / "manifest.json").write_text(
            json.dumps({"pages": [{"file": "page-0001.png"}]}), encoding="utf-8"
        )
        return RunResult(pages=(object(),), stop_state=PageState.END, stop_reason="end")  # type: ignore[arg-type]


def test_batch_executor_defaults_to_standard_books_directory(tmp_path: Path) -> None:
    executor = BatchExecutor(
        CatalogService(tmp_path / "catalog.sqlite"), SitePolicyRegistry(), AdapterRegistry()
    )

    assert executor.library_dir == Path("output/Books")


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
    during_run: Callable[[RunConfig], None] | None = None,
    runtime_settings: SiteRuntimeSettings | None = None,
) -> BatchExecutor:
    policies = SitePolicyRegistry()
    policies.register("mangaone", MangaOneSitePolicy)
    policies.register("piccoma", PiccomaSitePolicy)
    adapters = AdapterRegistry()
    adapters.register("mangaone", FakeAdapter)
    adapters.register("piccoma", FakeAdapter)

    def runner_factory(config: RunConfig) -> FakeRunner:
        if configs is not None:
            configs.append(config)
        if before_run is not None:
            before_run(config)
        return FakeRunner(
            config,
            catalog=service,
            fail=fail_crawl,
            during_run=during_run,
        )

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
        watchlist=synchronized_legacy_watchlist(service),
        runner_factory=runner_factory,
        package_function=package_function,
        runtime_settings=runtime_settings,
        library_dir=service.path.parent / "Books",
    )


def add_candidate(
    service: CatalogService,
    *,
    access_mode: str,
    consumes_quota: bool = False,
    access_granted_until: str | None = None,
    site: str = "mangaone",
    display_position: int | None = None,
    genre: str | None = None,
) -> BatchCandidate:
    work = service.create_work(
        WorkInput(work_key=f"work-{access_mode}", title="作品A", genre=genre)
    )
    item = service.create_item(
        ItemInput(order_label="第01話"), work_id=work.id
    )
    source = service.create_source(
        SourceInput(
            site=site,
            external_id=f"chapter-{item.id}",
            access_mode=access_mode,
            available=True,
            access_granted_until=access_granted_until,
            display_position=display_position,
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
        metadata=archive_metadata_for_catalog(work, item, source),
        access_mode=access_mode,
        consumes_quota=consumes_quota,
        external_id=source.external_id,
        work_id=work.id,
    )


def _seed_proven_stale_status(
    service: CatalogService,
    candidate: BatchCandidate,
    *,
    library_dir: Path,
    output_root: Path,
) -> tuple[Path, Path, bytes, Path]:
    stem, title, genre, _order, _author = archive_stem(
        candidate.metadata,
        artifact_prefix=candidate.artifact_prefix,
        artifact_disambiguator=candidate.artifact_disambiguator,
    )
    archive_path = library_dir / genre / title / f"{stem}.zip"
    status_path = library_dir.parent / "crawl-status" / genre / title / f"{stem}.json"
    backup_path = output_root / "prepare-recrawl-backup" / "old.zip"
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    backup_bytes = b"previous archive moved by prepare_recrawl"
    backup_path.write_bytes(backup_bytes)

    run = service.create_crawl_run(
        item_id=candidate.item_id,
        source_id=candidate.source_id,
        target_id=candidate.target_id,
        access_strategy=candidate.access_strategy,
        started_at=NOW,
    )
    service.finalize_successful_crawl(
        run.id,
        artifact=ArtifactInput(
            kind="archive",
            format="zip",
            sha256=hashlib.sha256(backup_bytes).hexdigest(),
            byte_size=len(backup_bytes),
            storage_backend="filesystem",
            locator=backup_path.as_posix(),
            state="present",
        ),
        page_count=1,
        stop_reason="end",
        finished_at=NOW,
    )
    service.mark_item_pending(candidate.item_id)
    source_output_dir = batch_executor_module._new_output_dir(
        output_root / "old-batch", candidate, NOW
    )
    status_payload = {
        "status": "completed",
        "archive_path": archive_path.as_posix(),
        "page_count": 1,
        "source_output_dir": source_output_dir.as_posix(),
        "source_removed": True,
    }
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(status_payload), encoding="utf-8")
    return archive_path, status_path, status_path.read_bytes(), backup_path


async def test_piccoma_batch_yaml_delay_reaches_runner_config(tmp_path: Path) -> None:
    crawler_config = tmp_path / "crawler.yaml"
    crawler_config.write_text(
        "sites:\n  piccoma:\n    page_turn_delay_ms: 200\n",
        encoding="utf-8",
    )
    runtime_settings = load_runtime_settings(crawler_config).for_site("piccoma")
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = add_candidate(service, access_mode="free", site="piccoma")
    configs: list[RunConfig] = []
    executor = make_executor(
        service,
        configs=configs,
        runtime_settings=runtime_settings,
    )

    await executor.execute_candidate(
        object(),
        candidate,
        output_root=tmp_path / "batch",
        library_dir=tmp_path / "Books",
        now=NOW,
    )

    assert configs[0].site == "piccoma"
    assert configs[0].page_turn_delay_ms == 200


@pytest.mark.parametrize("access_mode", ["free", "owned"])
async def test_direct_candidate_runs_and_completes_without_quota_state(
    tmp_path: Path, access_mode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = add_candidate(service, access_mode=access_mode)
    configs: list[RunConfig] = []
    executor = make_executor(service, configs=configs)
    source = service.get_source(candidate.source_id)
    service.invalidate_discovery_inventory_evidence(source.discovery_key)

    def unexpected_scope_read(*_args, **_kwargs):
        pytest.fail("Executor must not require scope-sync after Discovery")

    monkeypatch.setattr(service, "read_acquisition_scope_snapshot", unexpected_scope_read)

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


async def test_stale_archive_prefix_is_rejected_before_run_creation(
    tmp_path: Path,
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = replace(add_candidate(service, access_mode="free"), artifact_prefix="999")
    configs: list[RunConfig] = []
    executor = make_executor(service, configs=configs)
    executor._require_candidate_scope(replace(candidate, artifact_prefix=None))

    with pytest.raises(BatchExecutionError, match="archive prefix"):
        await executor.execute_candidate(
            object(),
            candidate,
            output_root=tmp_path / "batch",
            library_dir=tmp_path / "Books",
            now=NOW,
        )

    assert configs == []
    assert service.list_crawl_runs() == []
    assert service.get_item(candidate.item_id).status == "pending"


async def test_historical_archive_name_is_ignored_by_executor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = add_candidate(service, access_mode="free")
    old_archive = tmp_path / "Books" / "old-title" / "old-name.zip"
    old_archive.parent.mkdir(parents=True)
    old_bytes = b"historical archive"
    old_archive.write_bytes(old_bytes)
    target = service.get_source_target(candidate.target_id)
    previous_run = service.create_crawl_run(
        item_id=candidate.item_id,
        source_id=candidate.source_id,
        target_id=target.id,
        access_strategy="direct",
        started_at=NOW,
    )
    service.finalize_successful_crawl(
        previous_run.id,
        artifact=ArtifactInput(
            kind="archive",
            format="zip",
            sha256="0" * 64,
            byte_size=len(old_bytes),
            storage_backend="filesystem",
            locator=old_archive.as_posix(),
            state="present",
        ),
        page_count=1,
        stop_reason="end",
        finished_at=NOW,
    )
    service.mark_item_pending(candidate.item_id)
    executor = make_executor(service)

    def forbidden_history_scan(*_args, **_kwargs):
        pytest.fail("Batch must not inspect historical archives")

    monkeypatch.setattr(service, "read_work_archive_artifacts", forbidden_history_scan)

    result = await executor.execute_candidate(
        object(),
        candidate,
        output_root=tmp_path / "batch",
        library_dir=tmp_path / "Books",
        now=NOW,
    )

    assert result.archive_path.exists()
    assert old_archive.read_bytes() == old_bytes
    assert service.get_item(candidate.item_id).status == "completed"


def _record_historical_archive(
    service: CatalogService, candidate: BatchCandidate, archive_path: Path
) -> bytes:
    archive_bytes = b"historical archive"
    archive_path.parent.mkdir(parents=True)
    archive_path.write_bytes(archive_bytes)
    target = service.get_source_target(candidate.target_id)
    run = service.create_crawl_run(
        item_id=candidate.item_id,
        source_id=candidate.source_id,
        target_id=target.id,
        access_strategy=candidate.access_strategy,
        started_at=NOW,
    )
    service.finalize_successful_crawl(
        run.id,
        artifact=ArtifactInput(
            kind="archive",
            format="zip",
            sha256="0" * 64,
            byte_size=len(archive_bytes),
            storage_backend="filesystem",
            locator=archive_path.as_posix(),
            state="present",
        ),
        page_count=1,
        stop_reason="end",
        finished_at=NOW,
    )
    service.mark_item_pending(candidate.item_id)
    return archive_bytes


@pytest.mark.parametrize("entrypoint", ["grant_only", "resolver"])
async def test_historical_name_is_ignored_on_grant_and_resolver_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    entrypoint: str,
) -> None:
    service = CatalogService(tmp_path / f"history-{entrypoint}.sqlite")
    candidate = _add_magapoke_candidate(service)
    old_archive = tmp_path / "Books" / "old-title" / "old-name.zip"
    old_bytes = _record_historical_archive(service, candidate, old_archive)
    consumed_at = datetime(2026, 9, 17, 15, 12, tzinfo=JST)
    executor = _make_magapoke_executor(
        service,
        AccessConsumption(True, "work_ticket", consumed_at),
    )
    def forbidden_history_scan(*_args, **_kwargs):
        pytest.fail("Grant/resolver must not inspect historical archives")

    monkeypatch.setattr(service, "read_work_archive_artifacts", forbidden_history_scan)
    stem, title, genre, _order, _author = archive_stem(candidate.metadata)
    planned_archive = executor.library_dir / genre / title / f"{stem}.zip"
    planned_status = (
        executor.library_dir.parent / "crawl-status" / genre / title / f"{stem}.json"
    )
    planned_archive.parent.mkdir(parents=True, exist_ok=True)
    planned_status.parent.mkdir(parents=True, exist_ok=True)
    planned_archive.write_bytes(b"unrelated occupied archive")
    planned_status.write_bytes(b"unrelated occupied status")
    planned_archive_bytes = planned_archive.read_bytes()
    planned_status_bytes = planned_status.read_bytes()

    if entrypoint == "grant_only":
        result = await executor.execute_grant_only_candidate(
            object(), candidate, output_root=tmp_path / "batch", now=NOW
        )
        assert result.resource_consumed is True
        assert service.get_source(candidate.source_id).quota_started_at == consumed_at.isoformat()
        assert service.get_item(candidate.item_id).status == "pending"
    else:
        class ResolverAdapter:
            def get_access_profile(self) -> AccessProfile:
                return AccessProfile()

            async def resolve_access_resource_candidates(
                self, _page: object, candidates: tuple[object, ...], _resource: str,
                *, timeout_ms: int = 15_000,
            ) -> AccessResourceResolution:
                del timeout_ms
                return AccessResourceResolution(
                    selected_source_ids=(candidates[0].source_id,),
                )

        monkeypatch.setattr(
            executor.adapters, "create", lambda _site: ResolverAdapter()
        )
        monkeypatch.setattr(
            batch_executor_module.AccessGuard,
            "from_profile",
            staticmethod(lambda **_kwargs: ImmediateStopGuard(None)),
        )
        resolution = await executor.resolve_access_resource_candidates(
            object(), [candidate], "work_ticket"
        )
        assert resolution.selected_source_ids == (candidate.source_id,)
        assert service.get_source(candidate.source_id).quota_started_at is None
        assert service.get_item(candidate.item_id).status == "pending"

    assert old_archive.read_bytes() == old_bytes
    assert planned_archive.read_bytes() == planned_archive_bytes
    assert planned_status.read_bytes() == planned_status_bytes


@pytest.mark.parametrize("occupied_kind", ["archive", "status"])
async def test_output_collision_created_during_crawl_is_not_overwritten(
    tmp_path: Path, occupied_kind: str
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = add_candidate(service, access_mode="free")
    library_dir = tmp_path / "Books"
    stem, title, genre, _order, _author = archive_stem(candidate.metadata)
    archive_path = library_dir / genre / title / f"{stem}.zip"
    status_path = tmp_path / "crawl-status" / genre / title / f"{stem}.json"
    occupied_path = archive_path if occupied_kind == "archive" else status_path
    occupied_bytes = b"operator file appeared during crawl"
    package_calls: list[tuple[dict[str, str], dict[str, str], str | None, str | None]] = []
    capture_path: Path | None = None

    def create_racing_file(config: RunConfig) -> None:
        nonlocal capture_path
        capture_path = config.output_dir / "captured-page.bin"
        capture_path.parent.mkdir(parents=True, exist_ok=True)
        capture_path.write_bytes(b"captured output remains available")
        occupied_path.parent.mkdir(parents=True, exist_ok=True)
        occupied_path.write_bytes(occupied_bytes)

    executor = make_executor(
        service,
        during_run=create_racing_file,
        package_calls=package_calls,
    )

    with pytest.raises(BatchExecutionError, match="Candidate output already exists"):
        await executor.execute_candidate(
            object(),
            candidate,
            output_root=tmp_path / "batch",
            library_dir=library_dir,
            now=NOW,
        )

    assert occupied_path.read_bytes() == occupied_bytes
    assert capture_path is not None and capture_path.read_bytes() == b"captured output remains available"
    assert package_calls == []
    run = service.list_crawl_runs(source_id=candidate.source_id)[-1]
    assert run.status == "failed"
    assert service.list_artifacts(item_id=candidate.item_id) == []
    assert service.get_item(candidate.item_id).status == "pending"


@pytest.mark.parametrize("occupied_kind", ["archive", "status"])
async def test_occupied_candidate_archive_path_blocks_quota_access(
    tmp_path: Path, occupied_kind: str,
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = _add_magapoke_candidate(service)
    library_dir = tmp_path / "Books"
    stem, title, genre, _order, _author = archive_stem(candidate.metadata)
    archive_path = library_dir / genre / title / f"{stem}.zip"
    status_path = tmp_path / "crawl-status" / genre / title / f"{stem}.json"
    occupied_path = archive_path if occupied_kind == "archive" else status_path
    occupied_path.parent.mkdir(parents=True)
    occupied_path.write_bytes(b"existing archive or status")
    executor = _make_magapoke_executor(service, AccessConsumption())

    with pytest.raises(BatchExecutionError, match="Candidate output already exists"):
        await executor.execute_candidate(
            object(),
            candidate,
            output_root=tmp_path / "batch",
            library_dir=library_dir,
            now=NOW,
        )

    assert service.list_crawl_runs() == []
    assert service.get_item(candidate.item_id).status == "pending"
    assert service.get_source(candidate.source_id).quota_started_at is None
    assert service.get_quota_resource_state(
        candidate.work_id, site="magapoke", resource="work_ticket"
    ) is None


@pytest.mark.parametrize("fail_crawl", [False, True])
@pytest.mark.parametrize("duplicate_history_run", [False, True])
async def test_proven_stale_same_source_status_is_refreshed_only_after_success(
    tmp_path: Path, fail_crawl: bool, duplicate_history_run: bool
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = add_candidate(service, access_mode="free", genre="\u6f2b\u753b")
    library_dir = service.path.parent / "Books"
    archive_path, status_path, old_status, backup_path = _seed_proven_stale_status(
        service,
        candidate,
        library_dir=library_dir,
        output_root=tmp_path / "history",
    )
    if duplicate_history_run:
        duplicate = service.create_crawl_run(
            item_id=candidate.item_id,
            source_id=candidate.source_id,
            target_id=candidate.target_id,
            access_strategy=candidate.access_strategy,
            started_at=NOW,
        )
        service.mark_crawl_run_succeeded(
            duplicate.id, page_count=1, stop_reason="same timestamp, no ZIP"
        )
    executor = make_executor(service, fail_crawl=fail_crawl)
    if not fail_crawl:
        executor.package_function = package_crawl_output
        executor.runner_factory = EmptyManifestRunner  # type: ignore[assignment]

    if fail_crawl:
        with pytest.warns(ArchiveHistoryWarning, match="proven same-Source history"), pytest.raises(
            BatchExecutionError, match="crawler failed"
        ):
            await executor.execute_candidate(
                object(),
                candidate,
                output_root=tmp_path / "new-batch",
                library_dir=library_dir,
                now=NOW + timedelta(minutes=1),
            )
    else:
        with pytest.warns(ArchiveHistoryWarning, match="proven same-Source history"):
            result = await executor.execute_candidate(
                object(),
                candidate,
                output_root=tmp_path / "new-batch",
                library_dir=library_dir,
                now=NOW + timedelta(minutes=1),
            )

    assert backup_path.read_bytes() == b"previous archive moved by prepare_recrawl"
    if fail_crawl:
        assert status_path.read_bytes() == old_status
        assert not archive_path.exists()
        assert service.get_item(candidate.item_id).status == "pending"
        assert service.list_crawl_runs(source_id=candidate.source_id)[-1].status == "failed"
    else:
        assert result.archive_path.is_file()
        assert archive_path.is_file(), result.archive_path
        refreshed = json.loads(status_path.read_text(encoding="utf-8"))
        old = json.loads(old_status)
        assert refreshed["status"] == "completed"
        assert refreshed["archive_path"] == archive_path.as_posix()
        assert refreshed["source_output_dir"] != old["source_output_dir"]
        assert service.get_item(candidate.item_id).status == "completed"


async def test_prepare_recrawl_moved_archive_with_sidecar_can_batch_recrawl(
    tmp_path: Path,
) -> None:
    script_path = Path(__file__).parents[2] / "scripts" / "prepare_recrawl.py"
    spec = importlib.util.spec_from_file_location("prepare_recrawl_for_batch_test", script_path)
    assert spec is not None and spec.loader is not None
    prepare_recrawl = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = prepare_recrawl
    spec.loader.exec_module(prepare_recrawl)

    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = add_candidate(
        service, access_mode="free", genre="\u6f2b\u753b"
    )
    library_dir = tmp_path / "Books"
    archive_path = library_dir / archive_stem(candidate.metadata)[2] / archive_stem(
        candidate.metadata
    )[1] / f"{archive_stem(candidate.metadata)[0]}.zip"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("page-0001.png", b"synthetic old page")

    run = service.create_crawl_run(
        item_id=candidate.item_id,
        source_id=candidate.source_id,
        target_id=candidate.target_id,
        access_strategy=candidate.access_strategy,
        started_at=NOW,
    )
    old_bytes = archive_path.read_bytes()
    _, old_artifact, _ = service.finalize_successful_crawl(
        run.id,
        artifact=ArtifactInput(
            kind="archive",
            format="zip",
            sha256=hashlib.sha256(old_bytes).hexdigest(),
            byte_size=len(old_bytes),
            storage_backend="filesystem",
            locator=archive_path.as_posix(),
            state="present",
        ),
        page_count=1,
        stop_reason="end",
        finished_at=NOW,
    )
    old_source_output_dir = batch_executor_module._new_output_dir(
        tmp_path / "first-run", candidate, NOW
    )
    _stem, title, genre, _order, _author = archive_stem(candidate.metadata)
    status_path = tmp_path / "crawl-status" / genre / title / f"{archive_path.stem}.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    old_status = json.dumps(
        {
            "status": "completed",
            "archive_path": archive_path.as_posix(),
            "page_count": 1,
            "source_output_dir": old_source_output_dir.as_posix(),
            "source_removed": True,
        }
    ).encode()
    status_path.write_bytes(old_status)

    report = prepare_recrawl.scan_catalog(service, site="mangaone")
    assert len(report.results) == 1
    assert report.results[0].classification.value == "FALLBACK_INCLUDED"
    applied = prepare_recrawl.apply_scan_results(
        service,
        report,
        library_dir=library_dir,
        backup_root=tmp_path / "recrawl-backup",
        timestamp="fixture",
    )
    assert applied.failed == 0
    assert applied.archives_moved == 1
    assert applied.items_returned_pending == 1
    assert status_path.read_bytes() == old_status
    assert not archive_path.exists()
    moved_artifact = service.get_artifact(old_artifact.id)
    backup_path = Path(moved_artifact.locator)
    assert backup_path.is_file()
    assert backup_path.read_bytes() == old_bytes
    assert service.get_item(candidate.item_id).status == "pending"

    executor = make_executor(service)
    executor.package_function = package_crawl_output
    executor.runner_factory = EmptyManifestRunner  # type: ignore[assignment]
    with pytest.warns(ArchiveHistoryWarning, match="proven same-Source history"):
        result = await executor.execute_candidate(
            object(),
            candidate,
            output_root=tmp_path / "second-run",
            library_dir=library_dir,
            now=NOW + timedelta(minutes=1),
        )
    assert result.archive_path == archive_path
    assert archive_path.is_file()
    assert backup_path.read_bytes() == old_bytes
    assert service.get_artifact(old_artifact.id).locator == moved_artifact.locator
    assert service.get_item(candidate.item_id).status == "completed"
    refreshed = json.loads(status_path.read_text(encoding="utf-8"))
    assert refreshed["status"] == "completed"
    assert refreshed["archive_path"] == archive_path.as_posix()
    assert refreshed["source_output_dir"] != old_source_output_dir.as_posix()


async def test_proven_status_changed_during_crawl_is_preserved_and_not_replaced(
    tmp_path: Path,
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = add_candidate(service, access_mode="free")
    library_dir = tmp_path / "Books"
    archive_path, status_path, old_status, _backup_path = _seed_proven_stale_status(
        service,
        candidate,
        library_dir=library_dir,
        output_root=tmp_path / "history",
    )
    changed_status = old_status + b" \n"
    package_calls: list[tuple[dict[str, str], dict[str, str], str | None, str | None]] = []

    def update_status_during_crawl(_config: RunConfig) -> None:
        status_path.write_bytes(changed_status)

    executor = make_executor(
        service,
        during_run=update_status_during_crawl,
        package_calls=package_calls,
    )
    with pytest.warns(
        ArchiveHistoryWarning, match="proven same-Source history"
    ), pytest.raises(BatchExecutionError, match="status changed during crawl"):
        await executor.execute_candidate(
            object(), candidate, library_dir=library_dir, now=NOW + timedelta(minutes=1)
        )

    assert status_path.read_bytes() == changed_status
    assert not archive_path.exists()
    assert package_calls == []
    assert service.get_item(candidate.item_id).status == "pending"
    assert service.list_crawl_runs(source_id=candidate.source_id)[-1].status == "failed"


async def test_foreign_structured_status_never_falls_back_to_same_path_artifact(
    tmp_path: Path,
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = add_candidate(service, access_mode="free")
    library_dir = tmp_path / "Books"
    archive_path, status_path, old_status, _backup_path = _seed_proven_stale_status(
        service,
        candidate,
        library_dir=library_dir,
        output_root=tmp_path / "history",
    )
    same_path_artifact = service.list_artifacts(item_id=candidate.item_id)[0]
    service.update_artifact_storage(
        same_path_artifact.id, locator=archive_path.as_posix(), state="present"
    )
    payload = json.loads(old_status)
    foreign_candidate = replace(candidate, source_id=candidate.source_id + 100)
    payload["source_output_dir"] = batch_executor_module._new_output_dir(
        tmp_path / "foreign-run", foreign_candidate, NOW
    ).as_posix()
    status_path.write_text(json.dumps(payload), encoding="utf-8")
    old_runs = service.list_crawl_runs(source_id=candidate.source_id)
    executor = make_executor(service)

    with pytest.raises(BatchExecutionError, match="different Item/Source/site"):
        await executor.execute_candidate(
            object(), candidate, library_dir=library_dir, now=NOW + timedelta(minutes=1)
        )

    assert status_path.read_text(encoding="utf-8") == json.dumps(payload)
    assert not archive_path.exists()
    assert service.list_crawl_runs(source_id=candidate.source_id) == old_runs
    assert service.get_item(candidate.item_id).status == "pending"


@pytest.mark.parametrize(
    "reference_kind", ["same_source", "foreign_source", "no_run", "non_filesystem"]
)
async def test_legacy_status_requires_unambiguous_same_source_catalog_reference(
    tmp_path: Path, reference_kind: str
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = add_candidate(service, access_mode="free")
    library_dir = tmp_path / "Books"
    archive_path, status_path, old_status, _backup_path = _seed_proven_stale_status(
        service,
        candidate,
        library_dir=library_dir,
        output_root=tmp_path / "history",
    )
    original_artifact = service.list_artifacts(item_id=candidate.item_id)[0]
    if reference_kind != "non_filesystem":
        service.update_artifact_storage(
            original_artifact.id, locator=archive_path.as_posix(), state="present"
        )
    payload = json.loads(old_status)
    payload["source_output_dir"] = "legacy-output-directory"
    status_path.write_text(json.dumps(payload), encoding="utf-8")

    if reference_kind == "foreign_source":
        foreign = add_candidate(service, access_mode="paid")
        foreign_run = service.create_crawl_run(
            item_id=foreign.item_id,
            source_id=foreign.source_id,
            target_id=foreign.target_id,
            access_strategy=foreign.access_strategy,
            started_at=NOW + timedelta(minutes=2),
        )
        service.finalize_successful_crawl(
            foreign_run.id,
            artifact=ArtifactInput(
                kind="archive",
                format="zip",
                sha256=hashlib.sha256(b"foreign reference").hexdigest(),
                byte_size=len(b"foreign reference"),
                storage_backend="filesystem",
                locator=archive_path.as_posix(),
                state="present",
            ),
            page_count=1,
            stop_reason="foreign alias fixture",
            finished_at=NOW + timedelta(minutes=2),
        )
    elif reference_kind == "no_run":
        service.create_artifact(
            ArtifactInput(
                kind="archive",
                format="zip",
                sha256=hashlib.sha256(b"manual import").hexdigest(),
                byte_size=len(b"manual import"),
                storage_backend="filesystem",
                locator=archive_path.as_posix(),
                state="present",
            ),
            item_id=candidate.item_id,
        )
    elif reference_kind == "non_filesystem":
        service.create_artifact(
            ArtifactInput(
                kind="archive",
                format="zip",
                sha256=hashlib.sha256(b"remote key").hexdigest(),
                byte_size=len(b"remote key"),
                storage_backend="objectstore",
                locator=archive_path.as_posix(),
                state="present",
            ),
            item_id=candidate.item_id,
        )

    executor = make_executor(service, fail_crawl=True)
    run_count_before = len(service.list_crawl_runs(source_id=candidate.source_id))
    if reference_kind == "same_source":
        with pytest.warns(ArchiveHistoryWarning), pytest.raises(
            BatchExecutionError, match="crawler failed"
        ):
            await executor.execute_candidate(
                object(), candidate, library_dir=library_dir, now=NOW + timedelta(minutes=1)
            )
        assert len(service.list_crawl_runs(source_id=candidate.source_id)) == run_count_before + 1
    else:
        expected_error = (
            "no structured source identity or unique Catalog archive history"
            if reference_kind == "non_filesystem"
            else "different or ambiguous Catalog history"
        )
        with pytest.raises(BatchExecutionError, match=expected_error):
            await executor.execute_candidate(
                object(), candidate, library_dir=library_dir, now=NOW + timedelta(minutes=1)
            )
        assert len(service.list_crawl_runs(source_id=candidate.source_id)) == run_count_before
    assert status_path.exists()
    assert not archive_path.exists()


async def test_structured_status_proof_survives_current_target_url_refresh(
    tmp_path: Path,
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = add_candidate(service, access_mode="free")
    library_dir = tmp_path / "Books"
    archive_path, status_path, _old_status, _backup_path = _seed_proven_stale_status(
        service,
        candidate,
        library_dir=library_dir,
        output_root=tmp_path / "history",
    )
    refreshed_target = service.upsert_source_target(
        SourceTargetInput(
            backend=candidate.backend,
            target_key=candidate.target_key,
            locator="https://example.invalid/refreshed-target",
        ),
        source_id=candidate.source_id,
    )
    candidate = replace(candidate, locator=refreshed_target.locator)
    executor = make_executor(service, fail_crawl=True)

    with pytest.warns(
        ArchiveHistoryWarning, match="proven same-Source history"
    ), pytest.raises(BatchExecutionError, match="crawler failed"):
        await executor.execute_candidate(
            object(), candidate, library_dir=library_dir, now=NOW + timedelta(minutes=1)
        )

    assert status_path.exists()
    assert not archive_path.exists()


@pytest.mark.parametrize("failure", ["permission", "parent_file"])
async def test_unreadable_candidate_output_state_fails_before_site_or_quota(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = add_candidate(service, access_mode="free")
    library_dir = tmp_path / "Books"
    stem, title, genre, _order, _author = archive_stem(candidate.metadata)
    archive_path = library_dir / genre / title / f"{stem}.zip"
    if failure == "parent_file":
        archive_path.parent.parent.mkdir(parents=True, exist_ok=True)
        archive_path.parent.write_bytes(b"parent is not a directory")
    else:
        original_lstat = Path.lstat

        def inaccessible(path: Path, *args: object, **kwargs: object):
            if path == archive_path:
                raise PermissionError("output path cannot be inspected")
            return original_lstat(path, *args, **kwargs)

        monkeypatch.setattr(Path, "lstat", inaccessible)
    executor = make_executor(service)

    with pytest.raises(
        BatchExecutionError,
        match="output state cannot be checked|parent is not a directory",
    ):
        await executor.execute_candidate(
            object(),
            candidate,
            output_root=tmp_path / "batch",
            library_dir=library_dir,
            now=NOW,
        )

    assert service.list_crawl_runs() == []
    assert service.get_item(candidate.item_id).status == "pending"


async def test_artifact_disambiguator_is_forwarded_to_packaging(
    tmp_path: Path,
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    package_calls: list[
        tuple[dict[str, str], dict[str, str], str | None, str | None]
    ] = []
    candidate = replace(
        add_candidate(service, access_mode="free", display_position=3),
        metadata={"title": "作品A", "order": "番外編"},
        artifact_prefix="003",
        artifact_disambiguator="mangaone-chapter-1",
    )
    service.update_item_metadata(
        candidate.item_id, order_label=candidate.metadata["order"]
    )
    duplicate_item = service.create_item(
        ItemInput(order_label=service.get_item(candidate.item_id).order_label),
        work_id=candidate.work_id,
    )
    duplicate_source = service.create_source(
        SourceInput(
            site="mangaone",
            external_id="chapter-duplicate",
            display_position=3,
        ),
        item_id=duplicate_item.id,
    )
    service.create_source_target(
        SourceTargetInput(
            backend="web", locator="https://example.invalid/chapter/duplicate"
        ),
        source_id=duplicate_source.id,
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
        tmp_path / "Books" / "漫画" / "作品A" / "archive-mangaone-chapter-1.zip"
    )
    assert package_calls == [
        (
            {"title": "Adapter title", "genre": "漫画"},
            {"title": "作品A", "order": "番外編"},
            "003",
            "mangaone-chapter-1",
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
    configs: list[RunConfig] = []
    executor = make_executor(service, configs=configs)
    executor._require_candidate_scope(candidate)
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


async def test_populated_candidate_external_id_must_match_catalog_source(
    tmp_path: Path,
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = add_candidate(service, access_mode="free")
    executor = make_executor(service)

    with pytest.raises(BatchExecutionError, match="external_id"):
        await executor.execute_candidate(
            object(), replace(candidate, external_id="different-episode"), now=NOW
        )

    assert service.list_crawl_runs() == []
    assert service.list_artifacts() == []


async def test_comicdays_candidate_local_identity_skip_does_not_record_consumption(
    tmp_path: Path,
) -> None:
    service = CatalogService(tmp_path / "comicdays-identity-skip.sqlite")
    work = service.create_work(WorkInput(work_key="uchu-kyodai", title="Comic DAYS"))
    item = service.create_item(ItemInput(order_label="Episode 1"), work_id=work.id)
    source = service.create_source(
        SourceInput(site="comicdays", external_id="2", access_mode="quota"),
        item_id=item.id,
    )
    service.create_source_target(
        SourceTargetInput(
            backend="web", locator="https://comic-days.com/episode/1"
        ),
        source_id=source.id,
    )
    policies = SitePolicyRegistry()
    policies.register("comicdays", ComicDaysSitePolicy)
    adapters = AdapterRegistry()
    adapters.register("comicdays", ComicDaysAdapter)
    watchlist = synchronized_legacy_watchlist(service)
    candidate = BatchPlanner(service, policies, watchlist=watchlist).plan(
        site="comicdays", now=NOW
    ).candidates[0]

    class Runner:
        def __init__(self, config: RunConfig) -> None:
            self.config = config

        async def run(self, _page: object, adapter: ComicDaysAdapter) -> RunResult:
            await adapter.configure_run(_page, self.config.access_strategy)
            await adapter.configure_quota_resource(_page, self.config.quota_resource)
            adapter.resolve_initial_navigation_url(
                "https://comic-days.com/episode/1"
            )
            raise AssertionError("candidate-local identity mismatch should skip first")

    executor = BatchExecutor(
        service,
        policies,
        adapters,
        watchlist=watchlist,
        runner_factory=Runner,  # type: ignore[arg-type]
        library_dir=service.path.parent / "Books",
    )
    with pytest.raises(
        AccessResourceUnavailableError,
        match="comicdays_discovery_refresh_required",
    ) as error:
        await executor.execute_grant_only_candidate(
            object(), candidate, output_root=tmp_path / "batch", now=NOW
        )

    assert error.value.stop_resource_pass is False
    assert service.get_source(source.id).quota_started_at is None
    assert service.get_source(source.id).access_granted_until is None
    assert service.get_quota_resource_state(
        work.id, site="comicdays", resource="work_ticket"
    ) is None
    assert service.get_item(item.id).status == "pending"
    assert service.list_artifacts() == []


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
        metadata={"title": work.title, "order": item.order_label},
        reason=f"{resource}_candidate", consumes_quota=True,
        quota_resource=resource, quota_scope="work",
        quota_limit=1 if resource == "work_ticket" else None,
        quota_commit_mode="after_observed_consumption",
        external_id=source.external_id,
        work_id=work.id,
    )


def _make_magapoke_executor(
    service: CatalogService,
    consumption: AccessConsumption,
    *,
    failure: BaseException | None = None,
    during_run: Callable[[RunConfig], None] | None = None,
    site: str = "magapoke",
    policy: type[MagapokeSitePolicy] = MagapokeSitePolicy,
) -> BatchExecutor:
    class ConsumingAdapter(FakeAdapter):
        def get_access_consumption(self) -> AccessConsumption:
            return consumption

    class Runner:
        def __init__(self, config: RunConfig) -> None:
            self.config = config

        async def run(self, _page: object, _adapter: ConsumingAdapter) -> RunResult:
            if during_run is not None:
                during_run(self.config)
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
    watchlist = synchronized_legacy_watchlist(service)
    return BatchExecutor(
        service, policies, adapters,
        watchlist=watchlist,
        runner_factory=Runner,  # type: ignore[arg-type]
        package_function=package,
        library_dir=service.path.parent / "Books",
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


async def test_candidate_collision_after_observed_ticket_debit_preserves_history(
    tmp_path: Path,
) -> None:
    service = CatalogService(tmp_path / "comicdays-collision-after-debit.sqlite")
    candidate = _add_magapoke_candidate(service, site="comicdays")
    consumed_at = datetime(2026, 9, 17, 15, 12, tzinfo=JST)
    library_dir = service.path.parent / "Books"
    stem, title, genre, _order, _author = archive_stem(candidate.metadata)
    archive_path = library_dir / genre / title / f"{stem}.zip"
    occupied_bytes = b"operator file appeared during crawl"

    def create_collision(_config: RunConfig) -> None:
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        archive_path.write_bytes(occupied_bytes)

    executor = _make_magapoke_executor(
        service,
        AccessConsumption(True, "work_ticket", consumed_at),
        site="comicdays",
        policy=ComicDaysSitePolicy,
        during_run=create_collision,
    )

    with pytest.raises(
        BatchExecutionError, match="Candidate output already exists"
    ) as raised:
        await executor.execute_candidate(
            object(), candidate, output_root=tmp_path / "batch", now=NOW
        )

    assert raised.value.resource_consumed is True
    assert archive_path.read_bytes() == occupied_bytes
    source = service.get_source(candidate.source_id)
    assert source.quota_started_at == consumed_at.isoformat()
    state = service.get_quota_resource_state(
        service.get_item(candidate.item_id).work_id,
        site="comicdays",
        resource="work_ticket",
    )
    assert state is not None and state.last_consumed_at == consumed_at.isoformat()
    assert service.get_item(candidate.item_id).status == "pending"
    assert service.list_artifacts() == []
    assert service.list_crawl_runs(source_id=candidate.source_id)[-1].status == "failed"


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


@pytest.mark.parametrize(
    ("site", "policy"),
    [
        ("comicdays", ComicDaysSitePolicy),
        ("hanayume", HanayumeSitePolicy),
        ("younganimal", YounganimalSitePolicy),
    ],
)
@pytest.mark.parametrize("grant_only", [True, False])
async def test_comicdays_work_cooldown_blocks_both_executor_entrypoints(
    tmp_path: Path, grant_only: bool, site: str, policy
) -> None:
    database_path = tmp_path / f"{site}-cooldown-{grant_only}.sqlite"
    service = CatalogService(database_path)
    candidate = _add_magapoke_candidate(service, site=site)
    work = service.get_item(candidate.item_id).work_id
    second_item = service.create_item(ItemInput(order_label="Episode 2"), work_id=work)
    second_source = service.create_source(
        SourceInput(site=site, external_id=f"{site}-2", access_mode="quota"),
        item_id=second_item.id,
    )
    second_target = service.create_source_target(
        SourceTargetInput(backend="web", locator="https://example.invalid/mp-2"),
        source_id=second_source.id,
    )
    second_candidate = replace(
        candidate,
        item_id=second_item.id,
        source_id=second_source.id,
        target_id=second_target.id,
        locator=second_target.locator,
        external_id=second_source.external_id,
        metadata={
            **candidate.metadata,
            "order": second_item.order_label,
        },
    )
    consumed_at = datetime(2026, 9, 17, 15, 0, tzinfo=JST)
    service.record_quota_access_with_resource_state(
        candidate.source_id,
        work_id=work,
        site=site,
        resource="work_ticket",
        consumed_at=consumed_at,
        access_granted_until=consumed_at + timedelta(hours=71),
    )
    # Reopen the Catalog between recording the ticket and constructing the
    # Executor to verify the work cooldown survives a process restart.
    del service
    service = CatalogService(database_path)
    resource_state = service.get_quota_resource_state(
        work, site=site, resource="work_ticket"
    )
    assert resource_state is not None
    assert resource_state.last_consumed_at == consumed_at.isoformat()
    executor = _make_magapoke_executor(
        service,
        AccessConsumption(True, "work_ticket", consumed_at),
        site=site,
        policy=policy,
    )
    runner_calls: list[RunConfig] = []
    original_factory = executor.runner_factory

    def recording_factory(config: RunConfig):
        runner_calls.append(config)
        return original_factory(config)

    executor.runner_factory = recording_factory
    blocked_now = consumed_at + timedelta(hours=22, minutes=59, seconds=59)
    # The consumed source has a local active grant, while the second episode
    # remains a quota candidate in the same work. The work-scoped state must
    # block that second candidate before either Executor entrypoint reaches a
    # runner or browser page.
    for blocked_candidate in (second_candidate,):
        with pytest.raises(AccessResourceUnavailableError, match="work_ticket_cooldown"):
            if grant_only:
                await executor.execute_grant_only_candidate(
                    object(), blocked_candidate, output_root=tmp_path / "batch", now=blocked_now
                )
            else:
                await executor.execute_candidate(
                    object(), blocked_candidate, output_root=tmp_path / "batch", now=blocked_now
                )
    assert runner_calls == []
    assert service.list_crawl_runs() == []
    assert service.list_artifacts() == []
    boundary_now = consumed_at + timedelta(hours=23)
    assert executor.resource_state_skip_reason(
        second_candidate, now=boundary_now
    ) is None
    assert executor.grant_only_skip_reason(second_candidate, now=boundary_now) is None


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
    trace_files = list((tmp_path / "batch" / "magapoke").glob("*/diagnostics/entry_trace.json"))
    assert len(trace_files) == 1
    trace = json.loads(trace_files[0].read_text(encoding="utf-8"))
    assert {
        trace["item_id"], trace["source_id"], trace["target_id"],
        trace["site"], trace["resource"],
    } == {
        candidate.item_id, candidate.source_id, candidate.target_id,
        candidate.site, candidate.quota_resource,
    }
    assert trace["adapter_debug"]["ticket_trace"] == [{"phase": "entry_success"}]


async def test_success_entry_trace_ignores_collection_exception(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "trace-collection-error.sqlite")
    candidate = _add_magapoke_candidate(service)

    class FailingAdapter(FakeAdapter):
        async def collect_debug_metadata(self, _page: object) -> dict[str, object]:
            raise RuntimeError("diagnostics unavailable")

    await _write_success_entry_trace(
        object(),
        FailingAdapter(),
        candidate,
        tmp_path / "batch",
        RunResult(
            pages=(),
            stop_state=PageState.END,
            stop_reason="entry_confirmed",
            entry_confirmed=True,
        ),
    )

    trace = json.loads(
        (tmp_path / "batch" / "diagnostics" / "entry_trace.json").read_text(
            encoding="utf-8"
        )
    )
    assert trace["adapter_debug"] == {"collection_error_type": "RuntimeError"}


async def test_success_entry_trace_ignores_write_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = CatalogService(tmp_path / "trace-write-error.sqlite")
    candidate = _add_magapoke_candidate(service)

    def fail_write(*_args: object, **_kwargs: object) -> None:
        raise OSError("diagnostics filesystem unavailable")

    monkeypatch.setattr(batch_executor_module, "atomic_write_json", fail_write)
    await _write_success_entry_trace(
        object(),
        FakeAdapter(),
        candidate,
        tmp_path / "batch",
        RunResult(pages=(), stop_state=PageState.END, stop_reason="entry_confirmed"),
    )


@pytest.mark.parametrize("error_type", [asyncio.CancelledError, KeyboardInterrupt])
async def test_success_entry_trace_propagates_control_exception_from_collection(
    tmp_path: Path, error_type: type[BaseException]
) -> None:
    service = CatalogService(tmp_path / f"trace-collection-{error_type.__name__}.sqlite")
    candidate = _add_magapoke_candidate(service)

    class InterruptedAdapter(FakeAdapter):
        async def collect_debug_metadata(self, _page: object) -> dict[str, object]:
            raise error_type()

    with pytest.raises(error_type):
        await _write_success_entry_trace(
            object(),
            InterruptedAdapter(),
            candidate,
            tmp_path / "batch",
            RunResult(pages=(), stop_state=PageState.END, stop_reason="entry_confirmed"),
        )


@pytest.mark.parametrize("error_type", [asyncio.CancelledError, KeyboardInterrupt])
async def test_success_entry_trace_propagates_control_exception_from_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[BaseException],
) -> None:
    service = CatalogService(tmp_path / f"trace-write-{error_type.__name__}.sqlite")
    candidate = _add_magapoke_candidate(service)

    def fail_write(*_args: object, **_kwargs: object) -> None:
        raise error_type()

    monkeypatch.setattr(batch_executor_module, "atomic_write_json", fail_write)
    with pytest.raises(error_type):
        await _write_success_entry_trace(
            object(),
            FakeAdapter(),
            candidate,
            tmp_path / "batch",
            RunResult(pages=(), stop_state=PageState.END, stop_reason="entry_confirmed"),
        )


@pytest.mark.parametrize("stop_pass", [False, True])
async def test_grant_only_premium_ticket_persists_source_only(
    tmp_path: Path,
    stop_pass: bool,
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = _add_magapoke_candidate(service, resource="premium_ticket")
    consumed_at = datetime(2026, 9, 17, 15, 12, tzinfo=JST)
    executor = _make_magapoke_executor(
        service, AccessConsumption(
            True, "premium_ticket", consumed_at, stop_resource_pass=stop_pass
        )
    )

    result = await executor.execute_grant_only_candidate(
        object(), candidate, output_root=tmp_path / "batch", now=NOW
    )

    source = service.get_source(candidate.source_id)
    assert result.resource == "premium_ticket"
    assert result.stop_resource_pass is stop_pass
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

    with pytest.raises(BatchExecutionError, match="entry flow failed") as failure:
        await executor.execute_grant_only_candidate(
            object(), candidate, output_root=tmp_path / "batch", now=NOW
        )

    assert failure.value.resource_consumed is True

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


@pytest.mark.parametrize("stop_pass", [False, True])
async def test_successful_premium_ticket_candidate_completes_item(
    tmp_path: Path,
    stop_pass: bool,
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = _add_magapoke_candidate(service, resource="premium_ticket")
    consumed_at = datetime(2026, 9, 22, 22, 25, 33, tzinfo=JST)
    executor = _make_magapoke_executor(
        service,
        AccessConsumption(True, "premium_ticket", consumed_at, stop_resource_pass=stop_pass),
    )

    result = await executor.execute_candidate(
        object(), candidate, output_root=tmp_path / "batch",
        library_dir=tmp_path / "Books", now=NOW,
    )

    assert service.get_item(candidate.item_id).status == "completed"
    assert result.stop_resource_pass is stop_pass
    source = service.get_source(candidate.source_id)
    assert source.quota_started_at == consumed_at.isoformat()
    assert source.access_granted_until == "2026-09-25T21:25:33+09:00"
    assert service.get_crawl_run(result.crawl_run_id).status == "succeeded"


@pytest.mark.parametrize(
    ("native_expiry", "expected_expiry"),
    [
        (
            datetime(2026, 9, 19, 14, 59, tzinfo=JST),
            datetime(2026, 9, 19, 14, 59, tzinfo=JST),
        ),
        (
            datetime(2026, 9, 21, 15, 0, tzinfo=JST),
            datetime(2026, 9, 20, 15, 12, tzinfo=JST),
        ),
    ],
    ids=("native-expiry-before-policy", "policy-expiry-caps-native"),
)
async def test_observed_native_grant_expiry_is_capped_by_policy_fallback(
    tmp_path: Path, native_expiry: datetime, expected_expiry: datetime
) -> None:
    service = CatalogService(tmp_path / "native-grant-expiry.sqlite")
    candidate = _add_magapoke_candidate(service, site="hanayume")
    consumed_at = datetime(2026, 9, 17, 15, 12, tzinfo=JST)
    executor = _make_magapoke_executor(
        service,
        AccessConsumption(True, "work_ticket", consumed_at, native_expiry),
        site="hanayume",
        policy=HanayumeSitePolicy,
    )

    await executor.execute_candidate(
        object(), candidate, output_root=tmp_path / "batch", now=NOW
    )

    source = service.get_source(candidate.source_id)
    assert source.access_granted_until == expected_expiry.isoformat()
    state = service.get_quota_resource_state(
        service.get_item(candidate.item_id).work_id,
        site="hanayume",
        resource="work_ticket",
    )
    assert state is not None and state.last_consumed_at == consumed_at.isoformat()


@pytest.mark.parametrize(
    "invalid_expiry",
    [datetime(2026, 9, 19, 14, 59), "not-a-datetime"],  # noqa: DTZ001 - exercise naive metadata rejection
    ids=("naive", "wrong-type"),
)
async def test_invalid_native_grant_expiry_keeps_confirmed_debit_with_policy_fallback(
    tmp_path: Path, invalid_expiry: object
) -> None:
    service = CatalogService(tmp_path / "invalid-native-expiry.sqlite")
    candidate = _add_magapoke_candidate(service, site="hanayume")
    consumed_at = datetime(2026, 9, 17, 15, 12, tzinfo=JST)
    executor = _make_magapoke_executor(
        service,
        AccessConsumption(True, "work_ticket", consumed_at, invalid_expiry),  # type: ignore[arg-type]
        site="hanayume",
        policy=HanayumeSitePolicy,
    )

    with pytest.raises(BatchExecutionError, match="access-grant expiry") as raised:
        await executor.execute_candidate(
            object(), candidate, output_root=tmp_path / "batch", now=NOW
        )

    source = service.get_source(candidate.source_id)
    assert raised.value.resource_consumed is True
    assert source.quota_started_at == consumed_at.isoformat()
    assert source.access_granted_until == "2026-09-20T15:12:00+09:00"
    state = service.get_quota_resource_state(
        service.get_item(candidate.item_id).work_id,
        site="hanayume",
        resource="work_ticket",
    )
    assert state is not None and state.last_consumed_at == consumed_at.isoformat()
    assert service.get_item(candidate.item_id).status == "pending"
    assert service.list_artifacts() == []


@pytest.mark.parametrize(
    ("consumed", "failure", "expected_consumed"),
    [
        (True, RuntimeError("crawl failed after entry"), True),
        (False, RuntimeError("crawl failed before confirmation"), None),
        (True, asyncio.CancelledError(), True),
        (False, asyncio.CancelledError(), None),
    ],
)
async def test_consumption_is_recorded_when_crawl_fails_after_entry(
    tmp_path: Path,
    consumed: bool,
    failure: BaseException,
    expected_consumed: bool | None,
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = _add_magapoke_candidate(service)
    consumed_at = datetime(2026, 9, 17, 15, 12, tzinfo=JST)
    executor = _make_magapoke_executor(
        service,
        AccessConsumption(consumed, "work_ticket", consumed_at if consumed else None),
        failure=failure,
    )

    expected_error = BatchInterruptedError if isinstance(
        failure, asyncio.CancelledError
    ) else BatchExecutionError
    with pytest.raises(expected_error) as raised:
        await executor.execute_candidate(object(), candidate, now=NOW)
    assert raised.value.resource_consumed is expected_consumed
    assert service.get_source(candidate.source_id).quota_started_at == (
        consumed_at.isoformat() if consumed else None
    )
    state = service.get_quota_resource_state(
        service.get_item(candidate.item_id).work_id,
        site="magapoke",
        resource="work_ticket",
    )
    assert (state is not None) is consumed
    if state is not None:
        assert state.last_consumed_at == consumed_at.isoformat()
    assert service.get_item(candidate.item_id).status == "pending"
    assert service.list_artifacts() == []


async def test_normal_packaging_failure_preserves_confirmed_consumption(
    tmp_path: Path,
) -> None:
    service = CatalogService(tmp_path / "packaging-failure.sqlite")
    candidate = _add_magapoke_candidate(service)
    consumed_at = datetime(2026, 9, 17, 15, 12, tzinfo=JST)
    executor = _make_magapoke_executor(
        service, AccessConsumption(True, "work_ticket", consumed_at)
    )

    def fail_package(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("package failed after entry")

    executor.package_function = fail_package
    with pytest.raises(BatchExecutionError, match="package failed after entry") as raised:
        await executor.execute_candidate(object(), candidate, now=NOW)

    assert raised.value.resource_consumed is True
    assert service.get_source(candidate.source_id).quota_started_at == consumed_at.isoformat()
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

    with pytest.raises(BatchExecutionError, match="viewer confirmation failed") as failure:
        await executor.execute_grant_only_candidate(
            object(), candidate, output_root=tmp_path / "batch", now=NOW
        )

    assert failure.value.resource_consumed is None

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


@pytest.mark.parametrize("primary_failure", [False, True])
async def test_prepared_guard_cleanup_preserves_interruption_or_primary_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, primary_failure: bool,
) -> None:
    service = CatalogService(tmp_path / "cleanup.sqlite")
    candidate = replace(
        add_candidate(service, access_mode="quota", consumes_quota=True),
        quota_resource="work_ticket",
    )
    executor = make_executor(service)

    class Adapter:
        def get_access_profile(self):
            return None

        async def resolve_access_resource_candidates(self, *_args, **_kwargs):
            return AccessResourceResolution(selected_source_ids=(candidate.source_id,))

    class Guard:
        def start(self, _page):
            pass

        def raise_if_stopped(self):
            pass

        async def wait_for_stop(self):
            await asyncio.Event().wait()

        async def close(self):
            raise asyncio.CancelledError()

    monkeypatch.setattr(executor.adapters, "create", lambda _site: Adapter())
    monkeypatch.setattr(batch_executor_module.AccessGuard, "from_profile", lambda **_kwargs: Guard())
    expected = RuntimeError if primary_failure else asyncio.CancelledError
    with pytest.raises(expected):
        async with executor.prepare_access_resource_candidates(object(), [candidate], "work_ticket") as prepared:
            assert prepared.active
            if primary_failure:
                raise RuntimeError("primary entry failure")


async def test_resolver_timeout_is_bounded_for_cancellation_resistant_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = CatalogService(tmp_path / "resolver-timeout.sqlite")
    candidate = replace(
        add_candidate(service, access_mode="quota", consumes_quota=True),
        quota_resource="work_ticket",
    )
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


@pytest.mark.parametrize("budget", [25000, 0, -1, True, "25000"])
async def test_resolver_preparation_uses_validated_adapter_budget_and_runtime_pacing(
    tmp_path, monkeypatch, budget,
):
    service = CatalogService(tmp_path / "resolver-preparation.sqlite")
    candidate = replace(
        add_candidate(service, access_mode="quota", consumes_quota=True),
        quota_resource="work_ticket",
    )
    executor = make_executor(service)
    executor.runtime_settings = SiteRuntimeSettings(page_turn_delay_ms=321)
    configured = []
    waited = []
    original_wait = asyncio.wait

    class Adapter:
        def configure_access_resource_resolution(self, **kwargs):
            configured.append(kwargs)
            return budget

        def get_access_profile(self):
            return AccessProfile()

        async def resolve_access_resource_candidates(self, *_args, **kwargs):
            assert kwargs["timeout_ms"] == 1234
            return AccessResourceResolution(selected_source_ids=(candidate.source_id,))

    async def record_wait(tasks, **kwargs):
        waited.append(kwargs["timeout"])
        return await original_wait(tasks, **kwargs)

    monkeypatch.setattr(executor.adapters, "create", lambda _site: Adapter())
    monkeypatch.setattr(batch_executor_module.asyncio, "wait", record_wait)
    monkeypatch.setattr(batch_executor_module.AccessGuard, "from_profile",
                        lambda **_kwargs: ImmediateStopGuard(None))
    if budget != 25000 or isinstance(budget, bool):
        with pytest.raises(BatchExecutionError, match="Invalid access-resource resolver time budget"):
            await executor.resolve_access_resource_candidates(
                object(), [candidate], "work_ticket", timeout_ms=1234,
            )
        assert waited == []
    else:
        result = await executor.resolve_access_resource_candidates(
            object(), [candidate], "work_ticket", timeout_ms=1234,
        )
        assert result.selected_source_ids == (candidate.source_id,)
        assert waited == [27]
    assert configured == [{"timeout_ms": 1234, "page_turn_delay_ms": 321,
                           "blocked_external_ids": frozenset()}]
    assert service.get_source(candidate.source_id).quota_started_at is None


async def test_resolver_access_guard_stop_is_bounded_for_cancellation_resistant_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = CatalogService(tmp_path / "resolver-stop.sqlite")
    candidate = replace(
        add_candidate(service, access_mode="quota", consumes_quota=True),
        quota_resource="work_ticket",
    )
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


@pytest.mark.parametrize("grant_only", [False, True])
@pytest.mark.parametrize("reason", ["work_ticket_unavailable", "already_accessible"])
async def test_unavailable_and_already_accessible_do_not_record_consumption(
    tmp_path: Path, grant_only: bool, reason: str,
) -> None:
    service = CatalogService(tmp_path / "unavailable.sqlite")
    candidate = _add_magapoke_candidate(service)
    executor = _make_magapoke_executor(
        service, AccessConsumption(),
        failure=AccessResourceUnavailableError(reason),
    )
    with pytest.raises(AccessResourceUnavailableError, match=f"^{reason}$"):
        if grant_only:
            await executor.execute_grant_only_candidate(object(), candidate, now=NOW)
        else:
            await executor.execute_candidate(object(), candidate, now=NOW)
    source = service.get_source(candidate.source_id)
    assert source.quota_started_at is None
    assert source.access_granted_until is None
    assert service.get_quota_resource_state(
        service.get_item(candidate.item_id).work_id, site="magapoke", resource="work_ticket"
    ) is None
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
