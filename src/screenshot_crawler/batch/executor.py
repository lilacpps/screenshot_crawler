"""Sequential execution of planned Catalog candidates."""

from __future__ import annotations

import hashlib
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
    GrantOnlyExecutionResult,
)
from screenshot_crawler.catalog import ArtifactInput, CatalogError, CatalogService
from screenshot_crawler.catalog.service import JST, now_jst
from screenshot_crawler.core.access_guard import AccessEvent
from screenshot_crawler.core.errors import AccessResourceUnavailableError, AccessStopError
from screenshot_crawler.core.models import RunConfig
from screenshot_crawler.core.packaging import PackageResult, package_crawl_output
from screenshot_crawler.core.progress import normalize_path
from screenshot_crawler.core.runner import CrawlerRunner, RunResult
from screenshot_crawler.core.state import PageState
from screenshot_crawler.runtime_settings import (
    DEFAULT_PAGE_TURN_DELAY_MS,
    SiteRuntimeSettings,
)
from screenshot_crawler.site_adapters.base import SiteAdapter
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
        runtime_settings: SiteRuntimeSettings | None = None,
        access_event_sink: Callable[[AccessEvent], None] | None = None,
    ) -> None:
        self.catalog = catalog
        self.policies = policies
        self.adapters = adapters
        self.runner_factory = runner_factory
        self.package_function = package_function
        self.runtime_settings = runtime_settings
        self.access_event_sink = access_event_sink

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
        run_id: int | None = None
        crawl_result: RunResult | None = None
        adapter: SiteAdapter | None = None
        policy: SitePolicy | None = None
        try:
            if candidate.backend != "web":
                raise BatchExecutionError(
                    f"unsupported batch backend: {candidate.backend!r}"
                )
            policy = self.policies.create(candidate.site)
            self._validate_candidate(candidate, policy, current)
            run = self.catalog.create_crawl_run(
                item_id=candidate.item_id,
                source_id=candidate.source_id,
                target_id=candidate.target_id,
                access_strategy=candidate.access_strategy,
                started_at=current,
            )
            run_id = run.id
            output_dir = _new_output_dir(output_root, candidate, current)
            adapter = self.adapters.create(candidate.site)

            if candidate.consumes_quota and candidate.quota_commit_mode == "before_run":
                grant_until = policy.access_grant_until(current)
                self.catalog.record_quota_access(
                    candidate.source_id,
                    quota_started_at=current,
                    access_granted_until=grant_until,
                )

            config = RunConfig(
                site=candidate.site,
                source_url=candidate.locator,
                output_dir=output_dir,
                diagnostics_dir=output_dir / "diagnostics",
                max_pages=max_pages,
                max_same_content=max_same_content,
                page_turn_delay_ms=(
                    self.runtime_settings.page_turn_delay_ms
                    if self.runtime_settings is not None
                    else DEFAULT_PAGE_TURN_DELAY_MS
                ),
                stop_on_http_403=(
                    self.runtime_settings.stop_on_http_403
                    if self.runtime_settings is not None
                    else True
                ),
                stop_on_http_429=(
                    self.runtime_settings.stop_on_http_429
                    if self.runtime_settings is not None
                    else True
                ),
                stop_on_challenge=(
                    self.runtime_settings.stop_on_challenge
                    if self.runtime_settings is not None
                    else True
                ),
                stop_on_captcha=(
                    self.runtime_settings.stop_on_captcha
                    if self.runtime_settings is not None
                    else True
                ),
                access_event_sink=self.access_event_sink,
                diagnostics_metadata={
                    "item_id": candidate.item_id,
                    "source_id": candidate.source_id,
                    "target_id": candidate.target_id,
                    "site": candidate.site,
                },
                access_strategy=candidate.access_strategy,
                quota_resource=candidate.quota_resource,
                output_metadata=candidate.metadata,
            )
            crawl_result = await self.runner_factory(config).run(page, adapter)
            # A deferred commit is based on observed adapter state, never planning intent.
            _record_observed_consumption(self.catalog, candidate, policy, adapter)
            _require_normal_stop(crawl_result, candidate)
            package_kwargs = {
                "library_dir": library_dir,
                "explicit_metadata": candidate.metadata,
            }
            if candidate.artifact_disambiguator is not None:
                package_kwargs["artifact_disambiguator"] = candidate.artifact_disambiguator
            package = self.package_function(
                output_dir,
                adapter.get_output_metadata(),
                **package_kwargs,
            )
            archive_path = Path(package.archive_path)
            sha256, byte_size = _hash_archive(archive_path)
            _, artifact, _ = self.catalog.finalize_successful_crawl(
                run_id,
                artifact=ArtifactInput(
                    kind="archive",
                    format="zip",
                    sha256=sha256,
                    byte_size=byte_size,
                    storage_backend="filesystem",
                    locator=archive_path.as_posix(),
                    state="present",
                ),
                page_count=len(crawl_result.pages),
                stop_reason=crawl_result.stop_reason,
            )
            return BatchExecutionResult(
                item_id=candidate.item_id,
                source_id=candidate.source_id,
                target_id=candidate.target_id,
                crawl_run_id=run_id,
                artifact_id=artifact.id,
                archive_path=archive_path,
                status_path=package.status_path,
                page_count=len(crawl_result.pages),
                stop_reason=crawl_result.stop_reason,
            )
        except BaseException as exc:
            if adapter is not None and policy is not None:
                try:
                    _record_observed_consumption(self.catalog, candidate, policy, adapter)
                except Exception as recording_error:  # noqa: BLE001
                    exc.add_note(f"Could not record observed quota consumption: {recording_error}")
            if run_id is not None:
                _record_failed_run(self.catalog, run_id, exc, crawl_result)
            if isinstance(exc, AccessStopError):
                raise BatchExecutionError(
                    f"Fatal access stop for item={candidate.item_id}, "
                    f"source={candidate.source_id}: {exc.reason}",
                    access_stop=exc,
                ) from exc
            if isinstance(exc, BatchExecutionError):
                raise
            if isinstance(exc, AccessResourceUnavailableError):
                raise
            raise BatchExecutionError(
                f"Batch candidate failed (item={candidate.item_id}, "
                f"source={candidate.source_id}): {exc}"
            ) from exc

    def grant_only_skip_reason(
        self, candidate: BatchCandidate, *, now: datetime | None = None
    ) -> str | None:
        """Check local resource state before opening a browser page."""

        if candidate.quota_resource is None:
            raise BatchExecutionError("grant-only candidate has no access resource")
        current = _normalize_now(now_jst() if now is None else now)
        policy = self.policies.create(candidate.site)
        try:
            policy.validate_grant_only_resource(candidate.quota_resource)
            item = self.catalog.get_item(candidate.item_id)
            state = self.catalog.get_quota_resource_state(
                item.work_id,
                site=candidate.site,
                resource=candidate.quota_resource,
            )
            last_consumed_at = (
                datetime.fromisoformat(state.last_consumed_at) if state is not None else None
            )
            return policy.grant_only_skip_reason(
                resource=candidate.quota_resource,
                last_consumed_at=last_consumed_at,
                now=current,
                cooldown_hours=(
                    self.runtime_settings.work_ticket_cooldown_hours
                    if self.runtime_settings is not None
                    else None
                ),
            )
        except (CatalogError, SitePolicyError, ValueError) as exc:
            raise BatchExecutionError(f"Could not evaluate grant-only state: {exc}") from exc

    async def execute_grant_only_candidate(
        self,
        page: Page,
        candidate: BatchCandidate,
        *,
        output_root: str | Path = "output/batch",
        max_pages: int = 1000,
        max_same_content: int = 3,
        now: datetime | None = None,
    ) -> GrantOnlyExecutionResult:
        """Confirm one explicit access grant and leave the Item pending."""

        current = _normalize_now(now_jst() if now is None else now)
        run_id: int | None = None
        crawl_result: RunResult | None = None
        adapter: SiteAdapter | None = None
        policy: SitePolicy | None = None
        try:
            if candidate.quota_resource is None:
                raise BatchExecutionError("grant-only candidate has no access resource")
            policy = self.policies.create(candidate.site)
            policy.validate_grant_only_resource(candidate.quota_resource)
            self._validate_candidate(candidate, policy, current)
            run = self.catalog.create_crawl_run(
                item_id=candidate.item_id,
                source_id=candidate.source_id,
                target_id=candidate.target_id,
                access_strategy=candidate.access_strategy,
                started_at=current,
            )
            run_id = run.id
            output_dir = _new_output_dir(output_root, candidate, current)
            adapter = self.adapters.create(candidate.site)
            config = RunConfig(
                site=candidate.site,
                source_url=candidate.locator,
                output_dir=output_dir,
                diagnostics_dir=output_dir / "diagnostics",
                max_pages=max_pages,
                max_same_content=max_same_content,
                page_turn_delay_ms=(
                    self.runtime_settings.page_turn_delay_ms
                    if self.runtime_settings is not None
                    else DEFAULT_PAGE_TURN_DELAY_MS
                ),
                stop_on_http_403=(
                    self.runtime_settings.stop_on_http_403
                    if self.runtime_settings is not None else True
                ),
                stop_on_http_429=(
                    self.runtime_settings.stop_on_http_429
                    if self.runtime_settings is not None else True
                ),
                stop_on_challenge=(
                    self.runtime_settings.stop_on_challenge
                    if self.runtime_settings is not None else True
                ),
                stop_on_captcha=(
                    self.runtime_settings.stop_on_captcha
                    if self.runtime_settings is not None else True
                ),
                access_event_sink=self.access_event_sink,
                diagnostics_metadata={
                    "item_id": candidate.item_id,
                    "source_id": candidate.source_id,
                    "target_id": candidate.target_id,
                    "site": candidate.site,
                    "grant_only": True,
                },
                access_strategy=candidate.access_strategy,
                quota_resource=candidate.quota_resource,
                entry_only=True,
                output_metadata=candidate.metadata,
            )
            crawl_result = await self.runner_factory(config).run(page, adapter)
            if not crawl_result.entry_confirmed:
                raise BatchExecutionError("grant-only entry was not confirmed")
            consumption = adapter.get_access_consumption()
            if not consumption.consumed:
                reason = policy.grant_only_unavailable_reason(candidate.quota_resource)
                raise AccessResourceUnavailableError(reason)
            _record_observed_grant(
                self.catalog, candidate, policy, adapter
            )
            self.catalog.mark_crawl_run_succeeded(
                run_id,
                page_count=0,
                stop_reason=crawl_result.stop_reason,
            )
            return GrantOnlyExecutionResult(
                item_id=candidate.item_id,
                source_id=candidate.source_id,
                target_id=candidate.target_id,
                crawl_run_id=run_id,
                resource=candidate.quota_resource,
                resource_consumed=True,
                stop_reason=crawl_result.stop_reason,
            )
        except BaseException as exc:
            if run_id is not None:
                _record_failed_run(self.catalog, run_id, exc, crawl_result)
            if isinstance(exc, AccessStopError):
                raise BatchExecutionError(
                    f"Fatal access stop for item={candidate.item_id}, "
                    f"source={candidate.source_id}: {exc.reason}",
                    access_stop=exc,
                ) from exc
            if isinstance(exc, (BatchExecutionError, AccessResourceUnavailableError)):
                raise
            raise BatchExecutionError(
                f"Grant-only candidate failed (item={candidate.item_id}, "
                f"source={candidate.source_id}): {exc}"
            ) from exc

    def _validate_candidate(
        self, candidate: BatchCandidate, policy: SitePolicy, now: datetime
    ) -> None:
        """Reject a plan whose required Catalog identity/state is stale."""

        try:
            item = self.catalog.get_item(candidate.item_id)
            source = self.catalog.get_source(candidate.source_id)
            target = self.catalog.get_source_target(candidate.target_id)
        except CatalogError as exc:
            raise BatchExecutionError(f"stale batch candidate: {exc}") from exc

        mismatches: list[str] = []
        if candidate.quota_resource is not None:
            try:
                policy.validate_access_resource(candidate.quota_resource)
            except SitePolicyError as exc:
                raise BatchExecutionError(str(exc)) from exc
        if item.status != "pending":
            mismatches.append(f"item.status={item.status!r}")
        if source.item_id != candidate.item_id:
            mismatches.append("source.item_id")
        if source.site != candidate.site:
            mismatches.append("source.site")
        if source.access_mode != candidate.access_mode:
            mismatches.append("source.access_mode")
        if not source.available:
            mismatches.append("source.available=false")
        if target.source_id != candidate.source_id:
            mismatches.append("target.source_id")
        if target.backend != candidate.backend:
            mismatches.append("target.backend")
        if target.target_key != candidate.target_key:
            mismatches.append("target.target_key")
        if target.locator != candidate.locator:
            mismatches.append("target.locator")
        if not target.enabled:
            mismatches.append("target.enabled=false")

        try:
            site_sources = self.catalog.list_sources(site=candidate.site)
            actual_quota_available = policy.available_quota(site_sources, now)
            if candidate.consumes_quota and candidate.quota_resource is not None:
                decision = policy.evaluate_for_quota_resource(
                    source,
                    now=now,
                    quota_available=actual_quota_available,
                    quota_resource=candidate.quota_resource,
                )
            else:
                decision = policy.evaluate(
                    source,
                    now=now,
                    quota_available=actual_quota_available,
                )
        except SitePolicyError as exc:
            raise BatchExecutionError(f"stale batch candidate: {exc}") from exc
        if (
            not decision.eligible
            or decision.access_strategy != candidate.access_strategy
            or decision.consumes_quota != candidate.consumes_quota
            or decision.quota_resource != candidate.quota_resource
            or decision.quota_scope != candidate.quota_scope
            or decision.quota_limit != candidate.quota_limit
            or decision.quota_commit_mode != candidate.quota_commit_mode
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


def _hash_archive(path: Path, *, chunk_size: int = 1024 * 1024) -> tuple[str, int]:
    if not path.is_file():
        raise FileNotFoundError(f"Packaged archive not found: {path}")
    digest = hashlib.sha256()
    byte_size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
            byte_size += len(chunk)
    return digest.hexdigest(), byte_size


def _record_failed_run(
    catalog: CatalogService,
    run_id: int,
    error: BaseException,
    crawl_result: RunResult | None,
) -> None:
    page_count = len(crawl_result.pages) if crawl_result is not None else None
    stop_reason = (
        crawl_result.stop_reason
        if crawl_result is not None
        else getattr(error, "reason", None)
    )
    if stop_reason is None and getattr(error, "access_stop", None) is not None:
        stop_reason = getattr(error.access_stop, "reason", None)
    try:
        catalog.mark_crawl_run_failed(
            run_id,
            error_type=type(error).__name__,
            error_message=str(error)[:4000] or None,
            page_count=page_count,
            stop_reason=stop_reason,
        )
    except Exception as recording_error:  # noqa: BLE001
        error.add_note(f"Could not record failed CrawlRun {run_id}: {recording_error}")


def _record_observed_consumption(
    catalog: CatalogService,
    candidate: BatchCandidate,
    policy: SitePolicy,
    adapter: SiteAdapter,
) -> None:
    if candidate.quota_commit_mode != "after_observed_consumption":
        return
    consumption = adapter.get_access_consumption()
    if not consumption.consumed:
        return
    if candidate.quota_resource is None or consumption.resource != candidate.quota_resource:
        raise BatchExecutionError("adapter reported an unexpected quota resource")
    if consumption.consumed_at is None:
        raise BatchExecutionError("adapter reported resource consumption without a timestamp")
    if consumption.consumed_at.tzinfo is None or consumption.consumed_at.utcoffset() is None:
        raise BatchExecutionError("adapter consumption timestamp must be timezone-aware")
    catalog.record_quota_access(
        candidate.source_id,
        quota_started_at=consumption.consumed_at,
        access_granted_until=policy.access_grant_until(consumption.consumed_at),
    )


def _record_observed_grant(
    catalog: CatalogService,
    candidate: BatchCandidate,
    policy: SitePolicy,
    adapter: SiteAdapter,
) -> None:
    consumption = adapter.get_access_consumption()
    if not consumption.consumed:
        raise AccessResourceUnavailableError(
            policy.grant_only_unavailable_reason(candidate.quota_resource or "resource")
        )
    if candidate.quota_resource is None or consumption.resource != candidate.quota_resource:
        raise BatchExecutionError("adapter reported an unexpected grant-only resource")
    if consumption.consumed_at is None:
        raise BatchExecutionError("adapter reported resource consumption without a timestamp")
    if consumption.consumed_at.tzinfo is None or consumption.consumed_at.utcoffset() is None:
        raise BatchExecutionError("adapter consumption timestamp must be timezone-aware")
    item = catalog.get_item(candidate.item_id)
    catalog.record_quota_access_with_resource_state(
        candidate.source_id,
        work_id=item.work_id,
        site=candidate.site,
        resource=candidate.quota_resource,
        consumed_at=consumption.consumed_at,
        access_granted_until=policy.access_grant_until(consumption.consumed_at),
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
