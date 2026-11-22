"""Sequential execution of planned Catalog candidates."""

from __future__ import annotations

import asyncio
import hashlib
import re
import uuid
import warnings
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, replace
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from screenshot_crawler.archive_order import (
    ArchiveOrderPlanningError,
    build_work_archive_position_plan,
)
from screenshot_crawler.batch.archive_guard import (
    ArchiveHistoryWarning,
    CandidateOutputPathError,
    CandidateOutputPreflight,
    validate_candidate_output_paths,
)
from screenshot_crawler.batch.exclusions import unproven_target_exclusions
from screenshot_crawler.batch.models import (
    BatchCandidate,
    BatchExecutionError,
    BatchExecutionResult,
    BatchInterruptedError,
    CandidateExecutionError,
    GrantOnlyExecutionResult,
)
from screenshot_crawler.batch.naming import (
    archive_metadata_for_catalog,
    archive_position_prefix,
)
from screenshot_crawler.batch.naming import (
    collision_source_ids as shared_collision_source_ids,
)
from screenshot_crawler.catalog import ArtifactInput, CatalogError, CatalogService
from screenshot_crawler.catalog.models import Item, Source, Work
from screenshot_crawler.catalog.service import JST, now_jst
from screenshot_crawler.core.access_guard import AccessEvent, AccessGuard
from screenshot_crawler.core.errors import (
    AccessEntryNotAttemptedError,
    AccessResourceUnavailableError,
    AccessStopError,
    PageChangeTimeoutError,
)
from screenshot_crawler.core.models import RunConfig
from screenshot_crawler.core.packaging import PackageResult, archive_stem, package_crawl_output
from screenshot_crawler.core.progress import atomic_write_json, normalize_path
from screenshot_crawler.core.resume import ResumeError
from screenshot_crawler.core.runner import CrawlerRunner, RunResult
from screenshot_crawler.core.state import PageState
from screenshot_crawler.maintenance.work_deletion_gate import assert_work_deletion_gate_clear
from screenshot_crawler.runtime_settings import (
    DEFAULT_PAGE_TURN_DELAY_MS,
    SiteRuntimeSettings,
)
from screenshot_crawler.site_adapters.base import (
    AccessAttemptObservation,
    AccessResourceResolution,
    ConfirmedAccessGrant,
    SiteAdapter,
)
from screenshot_crawler.site_adapters.registry import AdapterRegistry
from screenshot_crawler.site_policies import SitePolicyError, SitePolicyRegistry
from screenshot_crawler.site_policies.base import PolicyDecision, SitePolicy
from screenshot_crawler.watchlist.models import WatchlistTarget
from screenshot_crawler.watchlist.service import WatchlistService

RunnerFactory = Callable[[RunConfig], CrawlerRunner]
PackageFunction = Callable[..., PackageResult]


def _catalog_job_locked(method):
    """Hold the shared Catalog lock across one public async operation."""

    @wraps(method)
    async def wrapped(self, *args, **kwargs):
        assert_work_deletion_gate_clear(self.catalog.path)
        with self.catalog.job_lock():
            assert_work_deletion_gate_clear(self.catalog.path)
            return await method(self, *args, **kwargs)

    return wrapped
_RESOLVER_CLEANUP_TIMEOUT_SECONDS = 5


@dataclass
class PreparedAccessResource:
    """One resolver's live Page, adapter and guard, valid for one selected entry."""

    page: Page
    adapter: SiteAdapter
    guard: AccessGuard
    resolution: AccessResourceResolution
    candidates: tuple[BatchCandidate, ...]
    resource: str
    used: bool = False
    active: bool = True
    resource_resolutions: dict[str, AccessResourceResolution] | None = None

    def take(self, page: Page, candidate: BatchCandidate) -> None:
        if (
            not self.active or self.used or page is not self.page
            or candidate not in self.candidates
            or candidate.source_id not in self.resolution.selected_source_ids
            or candidate.quota_resource != self.resource
        ):
            raise BatchExecutionError("Prepared access entry identity changed or was already used")
        self.guard.raise_if_stopped()
        self.used = True


async def _write_success_entry_trace(
    page: Page,
    adapter: SiteAdapter,
    candidate: BatchCandidate,
    output_dir: Path,
    crawl_result: RunResult,
) -> None:
    """Persist metadata-only entry evidence without affecting Batch success."""

    adapter_debug: dict[str, Any] = {}
    collect_debug = getattr(adapter, "collect_debug_metadata", None)
    if callable(collect_debug):
        try:
            value = await asyncio.wait_for(collect_debug(page), timeout=2)
            if isinstance(value, dict):
                adapter_debug = value
        except (KeyboardInterrupt, asyncio.CancelledError):
            raise
        except Exception as exc:  # noqa: BLE001 - evidence must not mask success
            adapter_debug = {"collection_error_type": type(exc).__name__}
    payload: dict[str, Any] = {
        "item_id": candidate.item_id,
        "source_id": candidate.source_id,
        "target_id": candidate.target_id,
        "site": candidate.site,
        "resource": candidate.quota_resource,
        "grant_only": True,
        "entry_confirmed": crawl_result.entry_confirmed,
        "stop_reason": crawl_result.stop_reason,
        "adapter_debug": adapter_debug,
    }
    try:
        atomic_write_json(output_dir / "diagnostics" / "entry_trace.json", payload)
    except (KeyboardInterrupt, asyncio.CancelledError):
        raise
    except Exception:  # noqa: BLE001 - evidence must not mask success
        return


def _consume_finished_task(task: asyncio.Task[object]) -> None:
    """Retrieve a detached task result so cleanup cannot leak warnings."""

    try:
        task.exception()
    except BaseException:  # noqa: BLE001 - cancellation/failure is already handled
        return


async def _cancel_task_bounded(
    task: asyncio.Task[object],
    *,
    timeout_seconds: float = _RESOLVER_CLEANUP_TIMEOUT_SECONDS,
) -> None:
    """Cancel and join a task without allowing unbounded Playwright cleanup."""

    if not task.done():
        task.cancel()
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=timeout_seconds)
    except TimeoutError:
        if not task.done():
            task.cancel()
        task.add_done_callback(_consume_finished_task)
    except asyncio.CancelledError:
        if task.done():
            return
        task.cancel()
        task.add_done_callback(_consume_finished_task)
        raise
    except BaseException:  # noqa: BLE001 - failed cleanup must not replace the cause
        return


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
        access_attempt_sink: Callable[[AccessAttemptObservation], None] | None = None,
        watchlist: WatchlistService | None = None,
        library_dir: str | Path | None = None,
    ) -> None:
        self.catalog = catalog
        self.policies = policies
        self.adapters = adapters
        self.runner_factory = runner_factory
        self.package_function = package_function
        self.runtime_settings = runtime_settings
        self.access_event_sink = access_event_sink
        self.access_attempt_sink = access_attempt_sink
        self.library_dir = Path(library_dir) if library_dir is not None else Path("output/Books")
        self.watchlist = watchlist
        self._reported_archive_warnings: set[str] = set()
        self._naming_signature: tuple[object, ...] | None = None
        self._naming_prefixes: dict[int, str | None] = {}
        self._naming_collisions: set[int] = set()

    def _candidate_error_context(self, candidate: BatchCandidate) -> str:
        """Add operator-facing Discovery identity without masking the failure."""
        fields = [f"item={candidate.item_id}", f"source={candidate.source_id}"]
        try:
            source = self.catalog.get_source(candidate.source_id)
            work = self.catalog.get_work(self.catalog.get_item(candidate.item_id).work_id)
            if source.discovery_key is not None:
                fields.append(f"key={source.discovery_key!r}")
            fields.append(f"work_key={work.work_key!r}")
            label = f"{work.title} [Catalog名]"
            fields.append(f"label={label!r}")
            if self.watchlist is not None:
                target = next((
                    row for row in self.watchlist.list_targets()
                    if row.key == source.discovery_key
                    and row.site == candidate.site == source.site
                    and row.work_key == work.work_key
                ), None)
                if target is not None:
                    fields[-1] = f"label={target.label!r}"
        except Exception:  # noqa: BLE001 - display lookup must not replace the original error
            return ", ".join(fields)
        return ", ".join(fields)

    def _bind_candidate_access_observers(
        self,
        adapter: SiteAdapter,
        candidate: BatchCandidate,
        source: Source,
    ) -> Callable[[], None]:
        """Bind grant and attempt callbacks to one candidate until cleanup."""

        grant_active = True
        attempt_active = True
        set_grant_observer = getattr(
            adapter, "set_confirmed_access_grant_observer", None
        )
        set_attempt_observer = getattr(adapter, "set_access_attempt_observer", None)
        if callable(set_grant_observer):
            set_grant_observer(None)
        if callable(set_attempt_observer):
            set_attempt_observer(None)

        def persist_confirmed_grant(grant: ConfirmedAccessGrant) -> None:
            if not grant_active:
                raise BatchExecutionError(
                    "confirmed grant observer is outside its candidate execution"
                )
            if not isinstance(grant, ConfirmedAccessGrant):
                raise BatchExecutionError(
                    "adapter reported an unvalidated confirmed grant value"
                )
            if (
                source.site != candidate.site
                or grant.site != source.site
                or grant.external_id != source.external_id
            ):
                raise BatchExecutionError(
                    "adapter reported a confirmed grant for a different candidate"
                )
            self.catalog.record_confirmed_access_grant(
                candidate.source_id,
                site=source.site,
                external_id=source.external_id,
                observed_at=grant.observed_at,
                access_granted_until=grant.access_granted_until,
            )

        def persist_access_attempt(observation: AccessAttemptObservation) -> None:
            if not attempt_active:
                raise BatchExecutionError(
                    "access attempt observer is outside its candidate execution"
                )
            if not isinstance(observation, AccessAttemptObservation):
                raise BatchExecutionError(
                    "adapter reported an invalid access attempt observation"
                )
            if (
                source.site != candidate.site
                or observation.site != source.site
                or observation.external_id != source.external_id
                or observation.resource != candidate.quota_resource
            ):
                raise BatchExecutionError(
                    "adapter reported an access attempt for a different candidate"
                )
            if self.access_attempt_sink is None:
                raise BatchExecutionError(
                    "durable access attempt evidence is required before quota entry"
                )
            self.access_attempt_sink(observation)

        grant_installed = False
        attempt_installed = False
        try:
            if callable(set_grant_observer):
                set_grant_observer(persist_confirmed_grant)
                grant_installed = True
            if callable(set_attempt_observer):
                set_attempt_observer(persist_access_attempt)
                attempt_installed = True
        except BaseException:
            grant_active = False
            attempt_active = False
            if grant_installed:
                with suppress(Exception):
                    set_grant_observer(None)
            if attempt_installed:
                with suppress(Exception):
                    set_attempt_observer(None)
            raise

        cleaned = False

        def cleanup() -> None:
            nonlocal grant_active, attempt_active, cleaned
            if cleaned:
                return
            cleaned = True
            grant_active = False
            attempt_active = False
            if callable(set_grant_observer):
                with suppress(Exception):
                    set_grant_observer(None)
            if callable(set_attempt_observer):
                with suppress(Exception):
                    set_attempt_observer(None)

        return cleanup

    @_catalog_job_locked
    async def execute_candidate(
        self,
        page: Page | None,
        candidate: BatchCandidate,
        *,
        output_root: str | Path = "output/batch",
        library_dir: str | Path | None = None,
        max_pages: int = 1000,
        max_same_content: int = 3,
        now: datetime | None = None,
        allow_quota_access: bool = False,
    ) -> BatchExecutionResult:
        """Run, package, and complete one candidate, or raise clearly."""

        if type(allow_quota_access) is not bool:
            raise BatchExecutionError("allow_quota_access must be a boolean")
        current = _normalize_now(now_jst() if now is None else now)
        effective_library_dir = (
            Path(library_dir) if library_dir is not None else self.library_dir
        )
        run_id: int | None = None
        crawl_result: RunResult | None = None
        adapter: SiteAdapter | None = None
        policy: SitePolicy | None = None
        consumption_checked = False
        capture_manager = None
        session = None
        observer_cleanup: Callable[[], None] = lambda: None
        speculative_grant: tuple[str | None, str | None] | None = None
        output_dir: Path | None = None
        crawling = False
        try:
            if candidate.backend != "web":
                raise BatchExecutionError(
                    f"unsupported batch backend: {candidate.backend!r}"
                )
            policy = self.policies.create(candidate.site)
            manager_factory = getattr(policy, "capture_session_manager", None)
            capture_manager = manager_factory(self.catalog) if callable(manager_factory) else None
            source = self.catalog.get_source(candidate.source_id)
            target = self.catalog.get_source_target(candidate.target_id)
            if capture_manager is not None and candidate.access_strategy == "quota":
                session = capture_manager.load(source, target)
            output_preflight = self._validate_candidate(
                candidate,
                policy,
                current,
                library_dir=effective_library_dir,
                allow_quota_access=allow_quota_access,
                capture_session=session, capture_manager=capture_manager,
            )
            local_skip_reason = self.resource_state_skip_reason(
                candidate, policy=policy, now=current
            )
            if local_skip_reason is not None:
                raise AccessResourceUnavailableError(local_skip_reason)
            if candidate.consumes_quota and policy.guards_unresolved_quota_attempts():
                unresolved = policy.unresolved_quota_attempt_source_ids(
                    self.catalog.list_crawl_runs(source_id=candidate.source_id)
                )
                if candidate.source_id in unresolved:
                    raise AccessResourceUnavailableError(
                        "prior_quota_attempt_unresolved"
                    )
            local_completion = bool(session and session.terminal)
            if page is None and not local_completion:
                raise BatchExecutionError("Capture requires an active browser Page")
            if local_completion and self.catalog.get_item(candidate.item_id).status == "completed":
                artifact = capture_manager.completed_artifact(session)
                package = capture_manager.owned_package(session, candidate, effective_library_dir, write_status=True)
                if package is None:
                    raise ResumeError("Completed capture archive is missing")
                capture_manager.clear(session)
                capture_manager.cleanup(session)
                return BatchExecutionResult(candidate.item_id, candidate.source_id, candidate.target_id,
                                            artifact.crawl_run_id, artifact.id, package.archive_path,
                                            package.status_path, len(session.store.pages), "completion_cleanup")
            if not local_completion:
                adapter = self.adapters.create(candidate.site)
            configure_existing_grant = getattr(
                adapter, "configure_existing_access_grant", None
            )
            if callable(configure_existing_grant):
                configure_existing_grant(None)
            source = self.catalog.get_source(candidate.source_id)
            work = self.catalog.get_work(self.catalog.get_item(candidate.item_id).work_id)
            configure_identity = getattr(adapter, "configure_target_identity", None)
            if configure_identity is not None:
                await configure_identity(source.external_id, work.work_key)
            if callable(configure_existing_grant):
                configure_existing_grant(_parse_access_grant(source.access_granted_until))
            if adapter is not None:
                observer_cleanup = self._bind_candidate_access_observers(
                    adapter, candidate, source
                )
            run = self.catalog.create_crawl_run(
                item_id=candidate.item_id,
                source_id=candidate.source_id,
                target_id=candidate.target_id,
                access_strategy=candidate.access_strategy,
                started_at=current,
            )
            run_id = run.id
            output_dir = _new_output_dir(output_root, candidate, current)
            if (capture_manager is not None and candidate.access_strategy == "quota"
                and (local_completion or callable(getattr(adapter, "configure_capture_session", None)))):
                if session is None:
                    session = capture_manager.create(source, target, current)
                session.record_attempt(run_id)
                output_dir = session.directory
                print(f"  capture={'local completion' if local_completion else 'resume' if session.checkpoint else 'new'} "
                      f"saved={len(session.store.pages)} resume_file={capture_manager.marker(source)}", flush=True)

            if candidate.consumes_quota and candidate.quota_commit_mode == "before_run":
                grant_until = policy.access_grant_until_for_resource(current, candidate.quota_resource)
                reservation = self.catalog.record_quota_access(
                    candidate.source_id,
                    quota_started_at=current,
                    access_granted_until=grant_until,
                )
                speculative_grant = (
                    reservation.quota_started_at, reservation.access_granted_until
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
                capture_session=session,
            )
            if local_completion:
                crawl_result = RunResult(tuple(session.saved_pages()), PageState(session.terminal["state"]),
                                         session.terminal["reason"])
            else:
                runner = self.runner_factory(config)
                crawling = True
                crawl_result = await runner.run(page, adapter)
                crawling = False
            # A deferred commit is based on observed adapter state, never planning intent.
            if adapter is not None:
                _record_observed_resource_consumption(self.catalog, candidate, policy, adapter)
            consumption_checked = True
            if crawl_result.stop_reason == "quota_time_budget":
                error = CandidateExecutionError("Reader time budget reached; committed pages retained for resume")
                error.reason = "quota_time_budget"
                raise error
            _require_normal_stop(crawl_result, candidate)
            # The output directory is selected before site access. Recheck the
            # final ZIP/status path immediately before packaging so a file that
            # appeared during the crawl is preserved rather than replaced.
            try:
                if session is None or not session.info.get("package_intent"):
                    _validate_candidate_output_path(
                    self.catalog,
                    candidate,
                    library_dir=effective_library_dir,
                    baseline=output_preflight,
                )
            except CandidateOutputPathError as exc:
                raise BatchExecutionError(str(exc)) from exc
            package_kwargs = {
                "library_dir": effective_library_dir,
                "explicit_metadata": candidate.metadata,
            }
            if candidate.artifact_prefix is not None:
                package_kwargs["artifact_prefix"] = candidate.artifact_prefix
            if candidate.artifact_disambiguator is not None:
                package_kwargs["artifact_disambiguator"] = candidate.artifact_disambiguator
            if session is not None:
                package = capture_manager.package(session, candidate, effective_library_dir, self.package_function)
            else:
                package = self.package_function(
                    output_dir, adapter.get_output_metadata(), **package_kwargs,
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
            if session is not None:
                try:
                    capture_manager.clear(session)
                    capture_manager.cleanup(session)
                except (OSError, ResumeError) as cleanup_error:
                    warnings.warn(f"Completed capture retained for cleanup: {cleanup_error}", RuntimeWarning, stacklevel=2)
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
                stop_resource_pass=_stop_after_resource_consumption(candidate, adapter),
            )
        except BaseException as exc:
            if session is not None and capture_manager is not None and (not session.terminal or session.info.get("invalid")):
                try:
                    capture_manager.abandon_if_unsafe(session)
                except Exception as cleanup_error:  # noqa: BLE001 - keep the original failure
                    exc.add_note(f"Could not release unsafe capture session: {cleanup_error}")
            if isinstance(exc, AccessEntryNotAttemptedError) and speculative_grant is not None:
                # Only this explicit adapter proof permits withdrawing an assumed
                # grant. Keep the local slot and never overwrite later evidence.
                try:
                    latest = self.catalog.get_source(candidate.source_id)
                    if (latest.quota_started_at, latest.access_granted_until) == speculative_grant:
                        self.catalog.record_quota_access(
                            candidate.source_id,
                            quota_started_at=current,
                            access_granted_until=source.access_granted_until,
                        )
                except Exception as recording_error:  # noqa: BLE001
                    exc.add_note(f"Could not discard unattempted access grant: {recording_error}")
            resource_consumed = _confirmed_grant_consumption(candidate, adapter)
            if isinstance(exc, (KeyboardInterrupt, asyncio.CancelledError)):
                interrupted = BatchInterruptedError(
                    f"Batch interrupted while executing item={candidate.item_id}, "
                    f"source={candidate.source_id}",
                    resource_consumed=resource_consumed,
                )
                if not consumption_checked and adapter is not None and policy is not None:
                    try:
                        _record_observed_resource_consumption(
                            self.catalog, candidate, policy, adapter
                        )
                    except Exception as recording_error:  # noqa: BLE001
                        interrupted.add_note(
                            f"Could not record observed quota consumption: {recording_error}"
                        )
                if run_id is not None:
                    _record_failed_run(self.catalog, run_id, interrupted, crawl_result)
                raise interrupted from exc
            if not consumption_checked and adapter is not None and policy is not None:
                try:
                    _record_observed_resource_consumption(
                        self.catalog, candidate, policy, adapter
                    )
                except Exception as recording_error:  # noqa: BLE001
                    exc.add_note(f"Could not record observed quota consumption: {recording_error}")
            if run_id is not None:
                _record_failed_run(self.catalog, run_id, exc, crawl_result)
            if isinstance(exc, AccessStopError):
                raise BatchExecutionError(
                    f"Fatal access stop for item={candidate.item_id}, "
                    f"source={candidate.source_id}: {exc.reason}",
                    access_stop=exc,
                    resource_consumed=resource_consumed,
                ) from exc
            if isinstance(exc, BatchExecutionError):
                exc.resource_consumed = resource_consumed
                raise
            if isinstance(exc, AccessResourceUnavailableError):
                raise
            raise CandidateExecutionError(
                f"Batch candidate failed ({self._candidate_error_context(candidate)}): {exc}",
                resource_consumed=resource_consumed,
                retryable=(
                    crawling
                    and type(exc) in {PageChangeTimeoutError, PlaywrightTimeoutError, TimeoutError}
                    and not getattr(exc, "__notes__", ())
                ),
                crawl_run_id=run_id,
                diagnostics_dir=output_dir / "diagnostics" if output_dir is not None else None,
                stop_resource_pass=(
                    _stop_after_resource_consumption(candidate, adapter)
                    if resource_consumed is True else False
                ),
            ) from exc
        finally:
            observer_cleanup()
            if adapter is not None:
                configure_existing_grant = getattr(
                    adapter, "configure_existing_access_grant", None
                )
                if callable(configure_existing_grant):
                    with suppress(Exception):
                        configure_existing_grant(None)

    def prepare_retry_candidate(
        self, candidate: BatchCandidate, error: CandidateExecutionError, *,
        library_dir: str | Path | None = None, now: datetime | None = None,
    ) -> BatchCandidate | None:
        """Revalidate this exact target for a non-consuming, fresh-page retry.

        Never reuse a quota intent or infer a grant from a speculative local
        reservation. The caller owns the single-retry budget and Page cleanup.
        """

        if not error.retryable or candidate.capture_session_id or candidate.local_completion:
            return None
        if candidate.consumes_quota and (
            candidate.quota_commit_mode != "after_observed_consumption"
            or error.resource_consumed is not True
        ):
            return None
        current = _normalize_now(now_jst() if now is None else now)
        policy = self.policies.create(candidate.site)
        if not policy.allows_automatic_candidate_retry():
            return None
        source = self.catalog.get_source(candidate.source_id)
        decision = policy.evaluate(
            source, now=current,
            quota_available=policy.available_quota(
                self.catalog.list_sources(site=candidate.site), current,
            ),
        )
        if not decision.eligible or decision.access_strategy != "direct" or decision.consumes_quota:
            return None
        retry = replace(
            candidate, access_strategy="direct", reason=decision.reason,
            consumes_quota=False, quota_resource=decision.quota_resource,
            quota_scope=decision.quota_scope, quota_limit=decision.quota_limit,
            quota_commit_mode=decision.quota_commit_mode,
        )
        self._validate_candidate(
            retry, policy, current,
            library_dir=Path(library_dir) if library_dir is not None else self.library_dir,
        )
        return retry

    def grant_only_skip_reason(
        self, candidate: BatchCandidate, *, now: datetime | None = None
    ) -> str | None:
        """Check local resource state before opening a browser page."""

        try:
            if candidate.quota_resource is None:
                raise BatchExecutionError("grant-only candidate has no access resource")
            current = _normalize_now(now_jst() if now is None else now)
            policy = self.policies.create(candidate.site)
            policy.validate_grant_only_resource(candidate.quota_resource)
            return self.resource_state_skip_reason(candidate, policy=policy, now=current)
        except BatchExecutionError:
            raise
        except (CatalogError, SitePolicyError, ValueError, TypeError) as exc:
            raise BatchExecutionError(f"Could not evaluate grant-only state: {exc}") from exc

    def resource_state_skip_reason(
        self,
        candidate: BatchCandidate,
        *,
        policy: SitePolicy | None = None,
        now: datetime | None = None,
    ) -> str | None:
        """Check a work-scoped resource state without site access."""

        if candidate.quota_resource is None or not candidate.consumes_quota:
            return None
        try:
            current = _normalize_now(now_jst() if now is None else now)
            selected_policy = policy or self.policies.create(candidate.site)
            if selected_policy.resource_state_scope(candidate.quota_resource) != "work":
                return None
            item = self.catalog.get_item(candidate.item_id)
            state = self.catalog.get_quota_resource_state(
                item.work_id,
                site=candidate.site,
                resource=candidate.quota_resource,
            )
            last_consumed_at = (
                datetime.fromisoformat(state.last_consumed_at)
                if state is not None
                else None
            )
            return selected_policy.grant_only_skip_reason(
                resource=candidate.quota_resource,
                last_consumed_at=last_consumed_at,
                now=current,
                cooldown_hours=(
                    getattr(self.runtime_settings, "work_ticket_cooldown_hours", None)
                    if self.runtime_settings is not None
                    else None
                ),
            )
        except (CatalogError, SitePolicyError, ValueError, TypeError) as exc:
            raise BatchExecutionError(f"Could not evaluate resource state: {exc}") from exc

    def grant_only_retry_at(self, candidate: BatchCandidate) -> datetime | None:
        """Read a policy-owned local retry deadline without contacting the site."""

        policy = self.policies.create(candidate.site)
        if candidate.quota_resource is None:
            return None
        item = self.catalog.get_item(candidate.item_id)
        state = self.catalog.get_quota_resource_state(
            item.work_id, site=candidate.site, resource=candidate.quota_resource
        )
        return policy.grant_only_retry_at(
            resource=candidate.quota_resource,
            last_consumed_at=datetime.fromisoformat(state.last_consumed_at) if state else None,
            cooldown_hours=getattr(self.runtime_settings, "work_ticket_cooldown_hours", None),
        )

    async def resolve_access_resource_candidates(
        self,
        page: Page,
        candidates: list[BatchCandidate] | tuple[BatchCandidate, ...],
        quota_resource: str,
        *,
        timeout_ms: int = 15_000,
    ) -> AccessResourceResolution:
        """Run one site-owned non-consuming resolver under the shared AccessGuard."""

        if not candidates:
            return AccessResourceResolution()
        async with self.prepare_access_resource_candidates(
            page, candidates, quota_resource, timeout_ms=timeout_ms
        ) as prepared:
            return prepared.resolution

    async def resolve_access_resource_pools(
        self, page: Page, pools: dict[str, list[BatchCandidate]],
        *, timeout_ms: int = 15_000,
    ) -> dict[str, AccessResourceResolution]:
        """Resolve one Work's explicit resource pools under one bounded guard."""

        if not pools or any(not pool for pool in pools.values()):
            raise BatchExecutionError("Combined resource resolution requires nonempty pools")
        resource = next(iter(pools))
        async with self.prepare_access_resource_candidates(
            page, pools[resource], resource, timeout_ms=timeout_ms,
            resource_pools=pools,
        ) as prepared:
            assert prepared.resource_resolutions is not None
            return prepared.resource_resolutions

    @asynccontextmanager
    async def prepare_access_resource_candidates(
        self,
        page: Page,
        candidates: list[BatchCandidate] | tuple[BatchCandidate, ...],
        quota_resource: str,
        *,
        timeout_ms: int = 15_000,
        resource_pools: dict[str, list[BatchCandidate]] | None = None,
    ) -> AsyncIterator[PreparedAccessResource]:
        """Lock the Catalog before any access-resource adapter is prepared."""
        with self.catalog.job_lock():
            async with self._prepare_access_resource_candidates(
                page, candidates, quota_resource, timeout_ms=timeout_ms,
                resource_pools=resource_pools,
            ) as prepared:
                yield prepared

    @asynccontextmanager
    async def _prepare_access_resource_candidates(
        self,
        page: Page,
        candidates: list[BatchCandidate] | tuple[BatchCandidate, ...],
        quota_resource: str,
        *,
        timeout_ms: int = 15_000,
        resource_pools: dict[str, list[BatchCandidate]] | None = None,
    ) -> AsyncIterator[PreparedAccessResource]:
        """Keep the resolver guard active through a same-page selected grant."""

        pending_candidates = tuple(candidates)
        if not pending_candidates:
            raise BatchExecutionError("Prepared access requires candidates")
        pools = resource_pools if resource_pools is not None else {quota_resource: candidates}
        all_candidates = tuple(candidate for pool in pools.values() for candidate in pool)
        if resource_pools is not None and (
            quota_resource not in pools or tuple(pools[quota_resource]) != pending_candidates
            or any(not pool for pool in pools.values())
            or len({candidate.work_id for candidate in all_candidates}) != 1
            or any(candidate.work_id is None for candidate in all_candidates)
        ):
            raise BatchExecutionError("Combined resource resolution requires one bound Work")
        sites = {candidate.site for candidate in all_candidates}
        if len(sites) != 1:
            raise BatchExecutionError("access-resource resolution requires one site")
        # This loop has no await: one current Work snapshot can validate the
        # whole pool before any adapter or network operation is started.
        work_snapshots: dict[int, tuple[list[Item], list[Source]]] = {}
        for resource, pool in pools.items():
            for candidate in pool:
                if candidate.quota_resource != resource:
                    raise BatchExecutionError(
                        "stale grant candidate: quota_resource does not match resolver pass"
                    )
                self._require_candidate_scope(
                    candidate,
                    expected_quota_resource=resource,
                    library_dir=self.library_dir,
                    check_output_paths=False,
                    work_snapshots=work_snapshots,
                )
        # Entry after an await must read fresh rows, including newly observed grants.
        work_snapshots.clear()
        adapter = self.adapters.create(next(iter(sites)))
        if resource_pools is not None:
            resolver = getattr(adapter, "resolve_access_resource_pools", None)
            if not callable(resolver):
                raise BatchExecutionError("Site adapter does not support combined resource resolution")
        resolution_timeout_ms = timeout_ms
        configure_resolution = getattr(adapter, "configure_access_resource_resolution", None)
        if callable(configure_resolution):
            blocked_ids: set[str] = set()
            if self.watchlist is not None:
                work_keys = {
                    self.catalog.get_work(work_id).work_key
                    for work_id in {
                        candidate.work_id for candidate in all_candidates
                        if candidate.work_id is not None
                    }
                }
                for target in self.watchlist.list_targets():
                    if (
                        target.site in sites and target.work_key in work_keys
                        and target.discovery_scope is not None
                    ):
                        blocked_ids.update(target.discovery_scope.excluded_external_ids)
            resolution_timeout_ms = configure_resolution(
                timeout_ms=timeout_ms,
                page_turn_delay_ms=(
                    self.runtime_settings.page_turn_delay_ms
                    if self.runtime_settings is not None else DEFAULT_PAGE_TURN_DELAY_MS
                ),
                blocked_external_ids=frozenset(blocked_ids),
            )
            if (
                isinstance(resolution_timeout_ms, bool)
                or not isinstance(resolution_timeout_ms, int)
                or resolution_timeout_ms <= 0
            ):
                raise BatchExecutionError("Invalid access-resource resolver time budget")
        guard = AccessGuard.from_profile(
            site=next(iter(sites)),
            profile=adapter.get_access_profile(),
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
            event_sink=self.access_event_sink,
        )
        guard.start(page)
        operation = asyncio.create_task(
            resolver(page, {key: tuple(pool) for key, pool in pools.items()}, timeout_ms=timeout_ms)
            if resource_pools is not None else adapter.resolve_access_resource_candidates(
                page,
                pending_candidates,
                quota_resource,
                timeout_ms=timeout_ms,
            )
        )
        stop = asyncio.create_task(guard.wait_for_stop())
        prepared: PreparedAccessResource | None = None
        primary_error: BaseException | None = None
        try:
            done, _pending = await asyncio.wait(
                {operation, stop},
                timeout=(resolution_timeout_ms + 2_000) / 1000,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if stop in done:
                error = stop.result()
                if error is not None:
                    await _cancel_task_bounded(operation)
                    raise error
            if operation not in done:
                await _cancel_task_bounded(operation)
                raise BatchExecutionError(
                    f"Access-resource resolver timed out for {next(iter(sites))}"
                )
            try:
                result = operation.result()
            except (KeyboardInterrupt, asyncio.CancelledError):
                raise
            except (AccessStopError, BatchExecutionError):
                raise
            except BaseException as exc:
                raise BatchExecutionError(
                    f"Access-resource resolver failed for {next(iter(sites))}: {exc}"
                ) from exc
            guard.raise_if_stopped()
            if result is None:
                raise BatchExecutionError(
                    f"Site adapter {type(adapter).__name__} does not provide "
                    "an access-resource resolver"
                )
            resource_resolutions = None
            if resource_pools is not None:
                if not isinstance(result, dict) or result.keys() != pools.keys():
                    raise BatchExecutionError("Combined resource resolver returned incomplete resources")
                for resource, resolution in result.items():
                    if not isinstance(resolution, AccessResourceResolution):
                        raise BatchExecutionError("Invalid combined resource resolution")
                    allowed_ids = {candidate.source_id for candidate in pools[resource]}
                    selected = set(resolution.selected_source_ids)
                    skipped = {source_id for source_id, _reason in resolution.skipped_source_reasons}
                    if (
                        selected & skipped or selected | skipped != allowed_ids
                        or len(selected) != len(resolution.selected_source_ids)
                        or len(skipped) != len(resolution.skipped_source_reasons)
                    ):
                        raise BatchExecutionError("Combined resource resolver returned invalid source coverage")
                resource_resolutions = result
                result = resource_resolutions[quota_resource]
            prepared = PreparedAccessResource(
                page, adapter, guard, result, pending_candidates, quota_resource,
                resource_resolutions=resource_resolutions,
            )
            yield prepared
            guard.raise_if_stopped()
        except BaseException as exc:
            primary_error = exc
            raise
        finally:
            if prepared is not None:
                prepared.active = False
            await _cancel_task_bounded(operation)
            await _cancel_task_bounded(stop)
            guard_close = asyncio.create_task(guard.close())
            try:
                await asyncio.wait_for(
                    asyncio.shield(guard_close), timeout=_RESOLVER_CLEANUP_TIMEOUT_SECONDS
                )
            except (KeyboardInterrupt, asyncio.CancelledError):
                await _cancel_task_bounded(guard_close)
                if primary_error is None:
                    raise
            except BaseException:  # noqa: BLE001 - cleanup must preserve the active failure
                await _cancel_task_bounded(guard_close)

    @_catalog_job_locked
    async def execute_grant_only_candidate(
        self,
        page: Page,
        candidate: BatchCandidate,
        *,
        output_root: str | Path = "output/batch",
        max_pages: int = 1000,
        max_same_content: int = 3,
        now: datetime | None = None,
        prepared_access: PreparedAccessResource | None = None,
    ) -> GrantOnlyExecutionResult:
        """Confirm one explicit access grant and leave the Item pending."""

        current = _normalize_now(now_jst() if now is None else now)
        run_id: int | None = None
        crawl_result: RunResult | None = None
        adapter: SiteAdapter | None = None
        policy: SitePolicy | None = None
        consumption_checked = False
        observer_cleanup: Callable[[], None] = lambda: None
        try:
            if candidate.quota_resource is None:
                raise BatchExecutionError("grant-only candidate has no access resource")
            policy = self.policies.create(candidate.site)
            policy.validate_grant_only_resource(candidate.quota_resource)
            self._validate_candidate(
                candidate, policy, current, output_mode="grant_only"
            )
            local_skip_reason = self.resource_state_skip_reason(
                candidate, policy=policy, now=current
            )
            if local_skip_reason is not None:
                raise AccessResourceUnavailableError(local_skip_reason)
            if candidate.consumes_quota and policy.guards_unresolved_quota_attempts():
                unresolved = policy.unresolved_quota_attempt_source_ids(
                    self.catalog.list_crawl_runs(source_id=candidate.source_id)
                )
                if candidate.source_id in unresolved:
                    raise AccessResourceUnavailableError(
                        "prior_quota_attempt_unresolved"
                    )
            if prepared_access is None:
                adapter = self.adapters.create(candidate.site)
            else:
                prepared_access.take(page, candidate)
                adapter = prepared_access.adapter
            source = self.catalog.get_source(candidate.source_id)
            work = self.catalog.get_work(self.catalog.get_item(candidate.item_id).work_id)
            configure_existing_grant = getattr(
                adapter, "configure_existing_access_grant", None
            )
            if callable(configure_existing_grant):
                configure_existing_grant(None)
                configure_existing_grant(_parse_access_grant(source.access_granted_until))
            configure_identity = getattr(adapter, "configure_target_identity", None)
            if configure_identity is not None:
                await configure_identity(source.external_id, work.work_key)
            observer_cleanup = self._bind_candidate_access_observers(
                adapter, candidate, source
            )
            run = self.catalog.create_crawl_run(
                item_id=candidate.item_id,
                source_id=candidate.source_id,
                target_id=candidate.target_id,
                access_strategy=candidate.access_strategy,
                started_at=current,
            )
            run_id = run.id
            output_dir = _new_output_dir(output_root, candidate, current)
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
            runner = self.runner_factory(config)
            if prepared_access is None:
                crawl_result = await runner.run(page, adapter)
            else:
                crawl_result = await runner.run(
                    page, adapter, prepared_entry=True, access_guard=prepared_access.guard
                )
            if not crawl_result.entry_confirmed:
                raise CandidateExecutionError("grant-only entry was not confirmed")
            observed = _record_observed_resource_consumption(
                self.catalog, candidate, policy, adapter
            )
            consumption_checked = True
            if not observed:
                reason = policy.grant_only_unavailable_reason(candidate.quota_resource)
                raise AccessResourceUnavailableError(reason)
            await _write_success_entry_trace(
                page, adapter, candidate, output_dir, crawl_result
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
                stop_resource_pass=_stop_after_resource_consumption(candidate, adapter),
            )
        except BaseException as exc:
            # Preserve current-attempt proof independently of finalization. A
            # later failure must not tell the operator to spend another ticket.
            resource_consumed = _confirmed_grant_consumption(candidate, adapter)
            if isinstance(exc, (KeyboardInterrupt, asyncio.CancelledError)):
                interrupted = BatchInterruptedError(
                    f"Batch interrupted while executing item={candidate.item_id}, "
                    f"source={candidate.source_id}",
                    resource_consumed=resource_consumed,
                )
                if not consumption_checked and adapter is not None and policy is not None:
                    try:
                        _record_observed_resource_consumption(
                            self.catalog, candidate, policy, adapter
                        )
                    except Exception as recording_error:  # noqa: BLE001
                        interrupted.add_note(
                            f"Could not record observed quota consumption: {recording_error}"
                        )
                if run_id is not None:
                    _record_failed_run(self.catalog, run_id, interrupted, crawl_result)
                raise interrupted from exc
            if not consumption_checked and adapter is not None and policy is not None:
                try:
                    _record_observed_resource_consumption(
                        self.catalog, candidate, policy, adapter
                    )
                except Exception as recording_error:  # noqa: BLE001
                    exc.add_note(f"Could not record observed quota consumption: {recording_error}")
            if run_id is not None:
                _record_failed_run(self.catalog, run_id, exc, crawl_result)
            if isinstance(exc, AccessStopError):
                raise BatchExecutionError(
                    f"Fatal access stop for item={candidate.item_id}, "
                    f"source={candidate.source_id}: {exc.reason}",
                    access_stop=exc,
                    resource_consumed=resource_consumed,
                ) from exc
            if isinstance(exc, BatchExecutionError):
                exc.resource_consumed = resource_consumed
                raise
            if isinstance(exc, AccessResourceUnavailableError):
                raise
            raise CandidateExecutionError(
                f"Grant-only candidate failed ({self._candidate_error_context(candidate)}): {exc}",
                resource_consumed=resource_consumed,
            ) from exc
        finally:
            observer_cleanup()
            if adapter is not None:
                configure_existing_grant = getattr(
                    adapter, "configure_existing_access_grant", None
                )
                if callable(configure_existing_grant):
                    with suppress(Exception):
                        configure_existing_grant(None)

    def _current_work_naming(
        self, work: Work, items: list[Item], sources: list[Source],
        targets: list[WatchlistTarget],
    ) -> tuple[dict[int, str | None], set[int]]:
        """Reuse pure naming only while all of its current inputs match.

        Status, availability and grant timestamps do not affect naming. They
        remain fresh per-candidate checks, including after earlier successes.
        Keep only the latest Work to bound the cache for long-lived executors.
        """
        signature = (
            work, tuple(targets),
            tuple((row.id, row.work_id, row.order_label) for row in items),
            tuple((row.id, row.item_id, row.site, row.external_id, row.discovery_key,
                   row.display_position, row.acquisition_enabled) for row in sources),
        )
        if signature != self._naming_signature:
            plan = build_work_archive_position_plan(
                work, targets, items, sources, provisional=True,
            )
            prefixes = {
                row.id: archive_position_prefix(
                    plan.positions_by_source_id.get(row.id) if plan else row.display_position
                )
                for row in sources
            }
            collisions: set[int] = set()
            for site in {row.site for row in sources}:
                collisions.update(shared_collision_source_ids(
                    [work], items, [row for row in sources if row.site == site],
                ))
            self._naming_signature = signature
            self._naming_prefixes = prefixes
            self._naming_collisions = collisions
        return self._naming_prefixes, self._naming_collisions

    def _require_candidate_scope(
        self,
        candidate: BatchCandidate,
        *,
        item=None,
        source=None,
        target=None,
        expected_quota_resource: str | None = None,
        library_dir: Path | None = None,
        check_output_paths: bool = True,
        allow_completed_capture: bool = False,
        work_snapshots: dict[int, tuple[list[Item], list[Source]]] | None = None,
    ) -> CandidateOutputPreflight | None:
        """Validate Catalog identity and current flags before policy or site access."""
        if self.watchlist is None:
            raise BatchExecutionError(
                "Batch execution requires an explicit Watchlist for managed Work selection"
            )
        try:
            item = item or self.catalog.get_item(candidate.item_id)
            source = source or self.catalog.get_source(candidate.source_id)
            target = target or self.catalog.get_source_target(candidate.target_id)
            if item.id != candidate.item_id or source.item_id != candidate.item_id:
                raise BatchExecutionError("stale batch candidate: item/source identity")
            work = self.catalog.get_work(item.work_id)
            if candidate.work_id is None or candidate.work_id != work.id:
                raise BatchExecutionError("stale batch candidate: work_id")
            if source.external_id != candidate.external_id:
                raise BatchExecutionError("stale batch candidate: external_id")
            if source.site != candidate.site:
                raise BatchExecutionError("stale batch candidate: source.site")
            if candidate.discovery_key is not None and source.discovery_key != candidate.discovery_key:
                raise BatchExecutionError("stale batch candidate: source.discovery_key")
            if target.source_id != source.id:
                raise BatchExecutionError("stale batch candidate: target.source_id")
            if target.backend != candidate.backend:
                raise BatchExecutionError("stale batch candidate: target.backend")
            if target.target_key != candidate.target_key:
                raise BatchExecutionError("stale batch candidate: target.target_key")
            if target.locator != candidate.locator:
                raise BatchExecutionError("stale batch candidate: target.locator")
            if not target.enabled:
                raise BatchExecutionError("stale batch candidate: target.enabled=false")
            if item.status != "pending" and not (allow_completed_capture and item.status == "completed"):
                raise BatchExecutionError(
                    f"stale batch candidate: item.status={item.status!r}"
                )
            if not source.available:
                raise BatchExecutionError("stale batch candidate: source.available=false")
            if source.access_mode != candidate.access_mode:
                raise BatchExecutionError("stale batch candidate: source.access_mode")
            if (
                expected_quota_resource is not None
                and candidate.quota_resource != expected_quota_resource
            ):
                raise BatchExecutionError("stale batch candidate: quota_resource")
        except CatalogError as exc:
            raise BatchExecutionError(f"stale batch candidate: {exc}") from exc
        if not source.acquisition_enabled:
            raise BatchExecutionError(
                f"Source {source.id} is acquisition_disabled"
            )
        try:
            snapshot = work_snapshots.get(work.id) if work_snapshots is not None else None
            if snapshot is None:
                snapshot = self.catalog.read_work_items_and_sources(work.id)
                if work_snapshots is not None:
                    work_snapshots[work.id] = snapshot
            work_items, work_sources = snapshot
            if source not in work_sources:
                raise BatchExecutionError(
                    "Catalog source changed while validating acquisition scope; retry Batch"
                )
            watchlist_targets = self.watchlist.list_targets()
            binding = next(
                (row for row in watchlist_targets if row.key == source.discovery_key), None
            )
            if binding is not None and (
                binding.work_key != work.work_key or binding.site != source.site
            ):
                raise BatchExecutionError("stale batch candidate: Watchlist Work/site identity")
            if binding is not None:
                unproven = unproven_target_exclusions(self.catalog, binding, work_sources)
                if unproven:
                    raise BatchExecutionError(
                        "stale batch candidate: Watchlist exclusions are unproven: "
                        + ", ".join(unproven[:5])
                    )
            if (
                binding is not None
                and binding.discovery_scope is not None
                and source.external_id in binding.discovery_scope.excluded_external_ids
            ):
                raise BatchExecutionError(
                    "stale batch candidate: source is excluded by the current Watchlist scope"
                )
            current_targets = [
                row
                for row in watchlist_targets
                if row.work_key == work.work_key
            ]
            if not current_targets:
                raise BatchExecutionError("stale batch candidate: acquisition_unmanaged")
            prefixes, disambiguated_ids = self._current_work_naming(
                work, work_items, work_sources, current_targets,
            )
            expected_prefix = prefixes[source.id]
            expected_disambiguator = (
                f"{source.site}-{source.external_id}"
                if source.id in disambiguated_ids
                else None
            )
            expected_metadata = archive_metadata_for_catalog(work, item, source)
        except (CatalogError, ArchiveOrderPlanningError, ValueError) as exc:
            raise BatchExecutionError(
                f"Cannot validate current archive numbering for Work {work.work_key!r}: {exc}"
            ) from exc
        if candidate.artifact_prefix != expected_prefix:
            raise BatchExecutionError(
                f"stale batch candidate: archive prefix {candidate.artifact_prefix!r} "
                f"does not match current {expected_prefix!r}"
            )
        if candidate.artifact_disambiguator != expected_disambiguator:
            raise BatchExecutionError(
                "stale batch candidate: archive disambiguator does not match current naming"
            )
        if candidate.metadata != expected_metadata:
            raise BatchExecutionError(
                "stale batch candidate: archive metadata no longer matches the Catalog"
            )
        output_preflight = None
        if check_output_paths:
            try:
                output_preflight = _validate_candidate_output_path(
                    self.catalog,
                    candidate,
                    library_dir=library_dir if library_dir is not None else self.library_dir,
                )
            except CandidateOutputPathError as exc:
                raise BatchExecutionError(str(exc)) from exc
        if output_preflight is not None and output_preflight.stale_status is not None:
            self._warn_archive_history(
                f"Candidate output for item={candidate.item_id}, source={candidate.source_id} "
                "has a completed status with proven same-Source history but no current ZIP; "
                "a successful capture will refresh it"
            )
        return output_preflight

    def _warn_archive_history(self, message: str) -> None:
        if message in self._reported_archive_warnings:
            return
        self._reported_archive_warnings.add(message)
        warnings.warn(message, ArchiveHistoryWarning, stacklevel=3)

    def _validate_candidate(
        self,
        candidate: BatchCandidate,
        policy: SitePolicy,
        now: datetime,
        *,
        library_dir: Path | None = None,
        output_mode: str = "capture",
        capture_session=None,
        capture_manager=None,
        allow_quota_access: bool = False,
    ) -> CandidateOutputPreflight | None:
        """Reject a plan whose required Catalog identity/state is stale."""

        if output_mode not in {"capture", "grant_only"}:
            raise BatchExecutionError(f"unsupported candidate output mode: {output_mode!r}")

        try:
            item = self.catalog.get_item(candidate.item_id)
            source = self.catalog.get_source(candidate.source_id)
            target = self.catalog.get_source_target(candidate.target_id)
        except CatalogError as exc:
            raise BatchExecutionError(f"stale batch candidate: {exc}") from exc

        output_preflight = self._require_candidate_scope(
            candidate,
            item=item,
            source=source,
            target=target,
            library_dir=library_dir,
            check_output_paths=output_mode == "capture" and not (capture_session and capture_session.terminal),
            allow_completed_capture=bool(
                capture_session and capture_session.terminal and item.status == "completed"
                and capture_manager.completed_artifact(capture_session)
            ),
        )
        if capture_session is not None and capture_session.terminal:
            capture_manager.owned_package(capture_session, candidate, library_dir or self.library_dir)
        mismatches: list[str] = []
        if candidate.quota_resource is not None:
            try:
                policy.validate_access_resource(candidate.quota_resource)
            except SitePolicyError as exc:
                raise BatchExecutionError(str(exc)) from exc
        local_completion = bool(capture_session and capture_session.terminal)
        if candidate.capture_session_id != (capture_session.id if capture_session else None):
            mismatches.append("capture session changed; replan")
        if candidate.capture_revision != (capture_session.revision if capture_session else None):
            mismatches.append("capture checkpoint changed; replan")
        if candidate.local_completion != local_completion:
            mismatches.append("capture completion phase changed; replan")
        if item.status != "pending" and not (local_completion and item.status == "completed"):
            mismatches.append(f"item.status={item.status!r}")
        if source.item_id != candidate.item_id:
            mismatches.append("source.item_id")
        if candidate.external_id and candidate.external_id != source.external_id:
            mismatches.append("external_id")
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
            if allow_quota_access and policy.requires_quota_access_opt_in():
                decision = policy.evaluate_with_quota_access(
                    source,
                    now=now,
                    quota_available=actual_quota_available,
                    allow_quota_access=True,
                )
            elif candidate.consumes_quota and candidate.quota_resource is not None:
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
            if local_completion and source.available:
                decision = PolicyDecision(True, "quota", "local_completion")
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
        return output_preflight


def _require_normal_stop(result: RunResult, candidate: BatchCandidate) -> None:
    if result.stop_state not in {PageState.END, PageState.NEXT_CONTENT}:
        raise CandidateExecutionError(
            f"Crawler did not stop normally for item={candidate.item_id}, "
            f"source={candidate.source_id}: {result.stop_reason}"
        )


def _validate_candidate_output_path(
    catalog: CatalogService,
    candidate: BatchCandidate,
    *,
    library_dir: Path,
    baseline: CandidateOutputPreflight | None = None,
) -> CandidateOutputPreflight:
    """Check planned outputs before access and again before packaging."""

    try:
        item = catalog.get_item(candidate.item_id)
        source = catalog.get_source(candidate.source_id)
        target = catalog.get_source_target(candidate.target_id)
        work = catalog.get_work(item.work_id)
    except CatalogError as exc:
        raise CandidateOutputPathError(
            f"Candidate identity changed before packaging: {exc}"
        ) from exc
    if (
        item.id != candidate.item_id
        or item.work_id != candidate.work_id
        or source.item_id != item.id
        or source.id != candidate.source_id
        or target.source_id != source.id
        or target.id != candidate.target_id
        or target.locator != candidate.locator
        or target.backend != candidate.backend
    ):
        raise CandidateOutputPathError(
            "Candidate Item/Source/Target changed before output packaging"
        )

    stem, title, genre, _order, _author = archive_stem(
        candidate.metadata,
        artifact_prefix=candidate.artifact_prefix,
        artifact_disambiguator=candidate.artifact_disambiguator,
    )
    archive_path = library_dir / genre / title / f"{stem}.zip"
    status_path = (
        library_dir.parent / "crawl-status" / genre / title / f"{stem}.json"
    )
    return validate_candidate_output_paths(
        catalog,
        work=work,
        item=item,
        source=source,
        target=target,
        archive_path=archive_path,
        status_path=status_path,
        baseline=baseline,
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
        else getattr(error, "stop_reason", None)
        or getattr(error, "reason", None)
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


def _confirmed_grant_consumption(
    candidate: BatchCandidate, adapter: SiteAdapter | None
) -> bool | None:
    """Expose positive current-attempt evidence; absence is not proof of no debit."""

    if adapter is None or candidate.quota_commit_mode != "after_observed_consumption":
        return None
    try:
        consumption = adapter.get_access_consumption()
        if (
            consumption.consumed
            and consumption.resource == candidate.quota_resource
            and consumption.consumed_at is not None
            and consumption.consumed_at.tzinfo is not None
            and consumption.consumed_at.utcoffset() is not None
        ):
            return True
    except Exception:  # noqa: BLE001 - reporting must preserve the original failure
        return None
    return None


def _stop_after_resource_consumption(candidate: BatchCandidate, adapter: SiteAdapter) -> bool:
    """Forward only a matching, confirmed consumption's pass-stop signal."""

    if _confirmed_grant_consumption(candidate, adapter) is not True:
        return False
    return adapter.get_access_consumption().stop_resource_pass


def _record_observed_resource_consumption(
    catalog: CatalogService,
    candidate: BatchCandidate,
    policy: SitePolicy,
    adapter: SiteAdapter,
) -> bool:
    if candidate.quota_commit_mode != "after_observed_consumption":
        return False
    consumption = adapter.get_access_consumption()
    if not consumption.consumed:
        return False
    if candidate.quota_resource is None or consumption.resource != candidate.quota_resource:
        raise BatchExecutionError("adapter reported an unexpected quota resource")
    if consumption.consumed_at is None:
        raise BatchExecutionError("adapter reported resource consumption without a timestamp")
    if consumption.consumed_at.tzinfo is None or consumption.consumed_at.utcoffset() is None:
        raise BatchExecutionError("adapter consumption timestamp must be timezone-aware")
    policy_grant_until = policy.access_grant_until_for_resource(
        consumption.consumed_at, candidate.quota_resource,
    )
    native_grant_until = consumption.access_granted_until
    metadata_error: str | None = None
    if native_grant_until is not None and (
        not isinstance(native_grant_until, datetime)
        or native_grant_until.tzinfo is None
        or native_grant_until.utcoffset() is None
    ):
        metadata_error = "adapter access-grant expiry must be a timezone-aware datetime"
        native_grant_until = None
    if policy_grant_until is not None and (
        not isinstance(policy_grant_until, datetime)
        or policy_grant_until.tzinfo is None
        or policy_grant_until.utcoffset() is None
    ):
        metadata_error = "policy access-grant expiry must be a timezone-aware datetime"
        policy_grant_until = None
    access_granted_until = (
        min(native_grant_until, policy_grant_until)
        if native_grant_until is not None and policy_grant_until is not None
        else native_grant_until or policy_grant_until
    )
    if policy.resource_state_scope(candidate.quota_resource) == "work":
        item = catalog.get_item(candidate.item_id)
        catalog.record_quota_access_with_resource_state(
            candidate.source_id,
            work_id=item.work_id,
            site=candidate.site,
            resource=candidate.quota_resource,
            consumed_at=consumption.consumed_at,
            access_granted_until=access_granted_until,
        )
    else:
        catalog.record_quota_access(
            candidate.source_id,
            quota_started_at=consumption.consumed_at,
            access_granted_until=access_granted_until,
        )
    if metadata_error is not None:
        raise BatchExecutionError(metadata_error)
    return True


def _normalize_now(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise BatchExecutionError("now must be a timezone-aware datetime")
    return value.astimezone(JST)


def _parse_access_grant(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _new_output_dir(
    output_root: str | Path, candidate: BatchCandidate, now: datetime
) -> Path:
    site = re.sub(r"[^A-Za-z0-9_.-]+", "_", candidate.site).strip(" .") or "site"
    run_id = f"item-{candidate.item_id}-source-{candidate.source_id}-{now:%Y%m%dT%H%M%S%f%z}-{uuid.uuid4().hex}"
    return normalize_path(Path(output_root) / site / run_id)
