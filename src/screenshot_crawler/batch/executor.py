"""Sequential execution of planned Catalog candidates."""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from playwright.async_api import Page

from screenshot_crawler.batch.models import (
    BatchCandidate,
    BatchExecutionError,
    BatchExecutionResult,
)
from screenshot_crawler.catalog import CatalogError, CatalogService
from screenshot_crawler.catalog.service import JST, now_jst
from screenshot_crawler.core.models import RunConfig
from screenshot_crawler.core.packaging import PackageResult, package_crawl_output
from screenshot_crawler.core.progress import normalize_path
from screenshot_crawler.core.runner import CrawlerRunner, RunResult
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.registry import AdapterRegistry
from screenshot_crawler.site_policies import SitePolicyError, SitePolicyRegistry
from screenshot_crawler.site_policies.base import SitePolicy

RunnerFactory = Callable[[RunConfig], CrawlerRunner]
PackageFunction = Callable[..., PackageResult]


class BatchExecutor:
    """Execute one planned candidate while keeping Catalog outside Core."""

    def __init__(
        self,
        catalog: CatalogService,
        policies: SitePolicyRegistry,
        adapters: AdapterRegistry,
        *,
        runner_factory: RunnerFactory = CrawlerRunner,
        package_function: PackageFunction = package_crawl_output,
    ) -> None:
        self.catalog = catalog
        self.policies = policies
        self.adapters = adapters
        self.runner_factory = runner_factory
        self.package_function = package_function

    async def execute_candidate(
        self,
        page: Page,
        candidate: BatchCandidate,
        *,
        output_root: str | Path = "output/batch",
        library_dir: str | Path = "output/Books",
        max_pages: int = 1000,
        max_same_content: int = 3,
        now: datetime | None = None,
    ) -> BatchExecutionResult:
        """Run, package, and complete one candidate, or raise clearly."""

        current = _normalize_now(now_jst() if now is None else now)
        try:
            policy = self.policies.create(candidate.site)
            self._validate_candidate(candidate, policy, current)
            output_dir = _new_output_dir(output_root, candidate, current)
            adapter = self.adapters.create(candidate.site)

            if candidate.consumes_quota:
                grant_until = policy.access_grant_until(current)
                if grant_until is None:
                    raise BatchExecutionError(
                        f"Site Policy did not provide a quota grant for {candidate.site}"
                    )
                self.catalog.record_quota_access(
                    candidate.source_id,
                    quota_started_at=current,
                    access_granted_until=grant_until,
                )

            config = RunConfig(
                site=candidate.site,
                source_url=candidate.url,
                output_dir=output_dir,
                diagnostics_dir=output_dir / "diagnostics",
                max_pages=max_pages,
                max_same_content=max_same_content,
                access_strategy=candidate.access_strategy,
                output_metadata=candidate.metadata,
            )
            crawl_result = await self.runner_factory(config).run(page, adapter)
            _require_normal_stop(crawl_result, candidate)
            package = self.package_function(
                output_dir,
                adapter.get_output_metadata(),
                library_dir=library_dir,
                explicit_metadata=candidate.metadata,
            )
            self.catalog.mark_item_completed(
                candidate.item_id,
                package.archive_path.as_posix(),
            )
            return BatchExecutionResult(
                item_id=candidate.item_id,
                source_id=candidate.source_id,
                archive_path=package.archive_path,
                status_path=package.status_path,
                page_count=len(crawl_result.pages),
                stop_reason=crawl_result.stop_reason,
            )
        except BatchExecutionError:
            raise
        except BaseException as exc:
            raise BatchExecutionError(
                f"Batch candidate failed (item={candidate.item_id}, "
                f"source={candidate.source_id}): {exc}"
            ) from exc

    def _validate_candidate(
        self, candidate: BatchCandidate, policy: SitePolicy, now: datetime
    ) -> None:
        """Reject a plan whose required Catalog identity/state is stale."""

        try:
            item = self.catalog.get_item(candidate.item_id)
            source = self.catalog.get_source(candidate.source_id)
        except CatalogError as exc:
            raise BatchExecutionError(f"stale batch candidate: {exc}") from exc

        mismatches: list[str] = []
        if item.status != "pending":
            mismatches.append(f"item.status={item.status!r}")
        if source.item_id != candidate.item_id:
            mismatches.append("source.item_id")
        if source.site != candidate.site:
            mismatches.append("source.site")
        if source.url != candidate.url:
            mismatches.append("source.url")
        if source.access_mode != candidate.access_mode:
            mismatches.append("source.access_mode")
        if not source.available:
            mismatches.append("source.available=false")

        try:
            decision = policy.evaluate(source, now=now, quota_available=1)
        except SitePolicyError as exc:
            raise BatchExecutionError(f"stale batch candidate: {exc}") from exc
        if (
            not decision.eligible
            or decision.access_strategy != candidate.access_strategy
            or decision.consumes_quota != candidate.consumes_quota
        ):
            mismatches.append("access decision")

        if mismatches:
            details = ", ".join(mismatches)
            raise BatchExecutionError(f"stale batch candidate: {details}")


def _require_normal_stop(result: RunResult, candidate: BatchCandidate) -> None:
    if result.stop_state not in {PageState.END, PageState.NEXT_CONTENT}:
        raise BatchExecutionError(
            f"Crawler did not stop normally for item={candidate.item_id}, "
            f"source={candidate.source_id}: {result.stop_reason}"
        )


def _normalize_now(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise BatchExecutionError("now must be a timezone-aware datetime")
    return value.astimezone(JST)


def _new_output_dir(
    output_root: str | Path, candidate: BatchCandidate, now: datetime
) -> Path:
    site = re.sub(r"[^A-Za-z0-9_.-]+", "_", candidate.site).strip(" .") or "site"
    run_id = f"item-{candidate.item_id}-source-{candidate.source_id}-{now:%Y%m%dT%H%M%S%f%z}-{uuid.uuid4().hex}"
    return normalize_path(Path(output_root) / site / run_id)
