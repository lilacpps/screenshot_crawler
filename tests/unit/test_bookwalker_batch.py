from datetime import datetime
from pathlib import Path
from zipfile import ZipFile

import pytest

from screenshot_crawler.batch import BatchCandidate, BatchExecutionError, BatchExecutor
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
from screenshot_crawler.site_policies import BookWalkerSitePolicy, SitePolicyRegistry

NOW = datetime(2026, 9, 19, 12, 0, tzinfo=JST)


class FakeAdapter:
    def get_output_metadata(self) -> dict[str, str]:
        return {"title": "BookWalker volume"}


class FakeRunner:
    calls = 0
    fail = False

    def __init__(self, _config: RunConfig) -> None:
        pass

    async def run(self, _page: object, _adapter: FakeAdapter) -> RunResult:
        type(self).calls += 1
        if self.fail:
            raise RuntimeError("crawler failed")
        return RunResult(pages=(), stop_state=PageState.END, stop_reason="end")


def make_candidate(service: CatalogService, *, order: str = "01") -> BatchCandidate:
    work = service.create_work(WorkInput(work_key=f"bookwalker-{order}", title="BookWalker volume"))
    item = service.create_item(ItemInput(order_key=order), work_id=work.id)
    source = service.create_source(
        SourceInput(
            site="bookwalker",
            external_id=f"book-{order}",
            access_mode="quota",
            available=True,
        ),
        item_id=item.id,
    )
    target = service.create_source_target(
        SourceTargetInput(backend="web", locator=f"https://bookwalker.example/de{order}/"),
        source_id=source.id,
    )
    return BatchCandidate(
        item_id=item.id,
        source_id=source.id,
        target_id=target.id,
        site="bookwalker",
        backend=target.backend,
        target_key=target.target_key,
        locator=target.locator,
        access_strategy="quota",
        metadata={"title": "BookWalker volume", "order": order},
        access_mode="quota",
        consumes_quota=True,
    )


def test_bookwalker_candidate_keeps_site_quota_defaults(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = make_candidate(service)
    assert candidate.consumes_quota is True
    assert candidate.quota_resource is None
    assert candidate.quota_scope == "site"
    assert candidate.quota_commit_mode == "before_run"


def make_executor(service: CatalogService, *, fail: bool = False) -> BatchExecutor:
    policies = SitePolicyRegistry()
    policies.register("bookwalker", BookWalkerSitePolicy)
    adapters = AdapterRegistry()
    adapters.register("bookwalker", FakeAdapter)
    FakeRunner.calls = 0
    FakeRunner.fail = fail

    def package_function(
        output_dir: Path,
        _metadata: dict[str, str],
        *,
        library_dir: str | Path,
        explicit_metadata: dict[str, str],
    ) -> PackageResult:
        archive_path = Path(library_dir) / "archive.zip"
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        with ZipFile(archive_path, "w") as archive:
            archive.writestr("archive.txt", "test archive")
        return PackageResult(
            archive_path=archive_path,
            title=explicit_metadata["title"],
            genre=None,
            volume=explicit_metadata["order"],
            author=None,
            status_path=output_dir / "status.json",
        )

    return BatchExecutor(
        service,
        policies,
        adapters,
        runner_factory=FakeRunner,
        package_function=package_function,
    )


async def test_bookwalker_quota_persists_grantless_state_before_crawl(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = make_candidate(service)
    observed: list[tuple[str | None, str | None]] = []

    class ObservingRunner(FakeRunner):
        async def run(self, page: object, adapter: FakeAdapter) -> RunResult:
            source = service.get_source(candidate.source_id)
            observed.append((source.quota_started_at, source.access_granted_until))
            return await super().run(page, adapter)

    executor = make_executor(service)
    executor.runner_factory = ObservingRunner
    result = await executor.execute_candidate(
        object(), candidate, output_root=tmp_path / "batch", library_dir=tmp_path / "Books", now=NOW
    )

    source = service.get_source(candidate.source_id)
    assert observed == [(NOW.isoformat(), None)]
    assert source.quota_started_at == NOW.isoformat()
    assert source.access_granted_until is None
    assert service.get_item(candidate.item_id).status == "completed"
    assert result.stop_reason == "end"


async def test_bookwalker_failure_does_not_refund_and_same_window_retry_is_rejected(
    tmp_path: Path,
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = make_candidate(service)
    executor = make_executor(service, fail=True)

    with pytest.raises(BatchExecutionError, match="crawler failed"):
        await executor.execute_candidate(object(), candidate, now=NOW)

    assert service.get_item(candidate.item_id).status == "pending"
    assert service.get_source(candidate.source_id).quota_started_at == NOW.isoformat()
    assert service.get_source(candidate.source_id).access_granted_until is None
    assert FakeRunner.calls == 1

    executor.runner_factory = FakeRunner
    FakeRunner.fail = False
    with pytest.raises(BatchExecutionError, match="stale batch candidate"):
        await executor.execute_candidate(object(), candidate, now=NOW)
    assert FakeRunner.calls == 1


async def test_bookwalker_quota_can_retry_after_next_window(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    candidate = make_candidate(service)
    executor = make_executor(service, fail=True)

    with pytest.raises(BatchExecutionError):
        await executor.execute_candidate(object(), candidate, now=NOW)

    FakeRunner.fail = False
    next_window = datetime(2026, 9, 20, 5, 0, tzinfo=JST)
    result = await executor.execute_candidate(
        object(), candidate, output_root=tmp_path / "batch", library_dir=tmp_path / "Books", now=next_window
    )

    assert result.stop_reason == "end"
    assert service.get_item(candidate.item_id).status == "completed"
    assert service.get_source(candidate.source_id).quota_started_at == next_window.isoformat()
