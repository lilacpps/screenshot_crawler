"""Preflighted, reversible renaming of existing position-aware archives."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from screenshot_crawler.archive_order import (
    ArchiveOrderPlanningError,
    build_work_archive_position_plan,
)
from screenshot_crawler.batch.naming import catalog_archive_stem, collision_source_ids
from screenshot_crawler.catalog import (
    Artifact,
    CatalogService,
    CrawlRun,
    Item,
    Source,
    Work,
)
from screenshot_crawler.core.packaging import safe_component
from screenshot_crawler.core.progress import atomic_write_json
from screenshot_crawler.watchlist.reconcile import ScopeReconciliationError
from screenshot_crawler.watchlist.service import WatchlistService


class ArchiveRenumberUsageError(ValueError):
    """Raised when the requested archive-renumber scope is unsafe or invalid."""


class ArchiveRenumberPreflightError(RuntimeError):
    """Raised when the filesystem changed after preflight."""


@dataclass(slots=True)
class RenumberEntry:
    """One Source and its selected current archive decision."""

    work: Work
    item: Item
    source: Source
    status: str
    run: CrawlRun | None = None
    artifact: Artifact | None = None
    old_path: Path | None = None
    new_path: Path | None = None
    status_path: Path | None = None
    new_status_path: Path | None = None
    status_warning: str | None = None
    detail: str | None = None
    temporary_path: Path | None = None
    status_temporary_path: Path | None = None
    status_original_bytes: bytes | None = None
    status_payload: dict[str, Any] | None = None
    zip_stage1_done: bool = False
    zip_final_done: bool = False
    status_stage1_done: bool = False
    status_final_done: bool = False
    status_updated: bool = False
    expected_sha256: str | None = None
    expected_byte_size: int | None = None
    rollback_sha256: str | None = None
    rollback_byte_size: int | None = None
    zip_stage1_attempted: bool = False
    zip_final_attempted: bool = False
    status_stage1_attempted: bool = False
    status_final_attempted: bool = False


@dataclass(slots=True)
class ArchiveRenumberPlan:
    """Complete, already-preflighted plan for one explicit scope."""

    entries: list[RenumberEntry]
    catalog: CatalogService
    status_dir: Path
    work_key: str | None = None
    site: str | None = None
    all_sources: bool = False
    watchlist_path: Path | None = None
    strict_work_keys: tuple[str, ...] = ()
    strict_blockers: tuple[str, ...] = ()
    strict_revision: str | None = None

    @property
    def executable_entries(self) -> list[RenumberEntry]:
        return [entry for entry in self.entries if entry.status == "RENAME"]

    def summary(self) -> Counter[str]:
        counts = Counter(entry.status.lower() for entry in self.entries)
        counts["selected"] = len(self.entries)
        for entry in self.entries:
            if entry.status_warning is not None:
                counts[entry.status_warning.lower()] += 1
        counts.setdefault("rename", 0)
        counts.setdefault("unchanged", 0)
        counts.setdefault("missing", 0)
        counts.setdefault("no_position", 0)
        counts.setdefault("no_artifact", 0)
        counts.setdefault("ambiguous", 0)
        counts.setdefault("unsupported", 0)
        counts.setdefault("collision", 0)
        counts.setdefault("status_missing", 0)
        counts.setdefault("status_mismatch", 0)
        counts["errors"] = counts.get("error", 0)
        counts["strict_blockers"] = len(self.strict_blockers)
        return counts

    def to_dict(self, *, mode: str = "dry-run") -> dict[str, Any]:
        """Return a GUI/CLI-ready immutable summary of this preflight plan."""

        return {
            "mode": mode,
            "work_key": self.work_key,
            "site": self.site,
            "all_sources": self.all_sources,
            "watchlist": self.watchlist_path.as_posix()
            if self.watchlist_path is not None
            else None,
            "strict_work_keys": list(self.strict_work_keys),
            "strict_blockers": list(self.strict_blockers),
            "summary": dict(self.summary()),
            "entries": [
                {
                    "status": entry.status,
                    "work_key": entry.work.work_key,
                    "source_id": entry.source.id,
                    "site": entry.source.site,
                    "external_id": entry.source.external_id,
                    "acquisition_enabled": entry.source.acquisition_enabled,
                    "artifact_id": entry.artifact.id if entry.artifact is not None else None,
                    "old_path": entry.old_path.as_posix()
                    if entry.old_path is not None
                    else None,
                    "new_path": entry.new_path.as_posix()
                    if entry.new_path is not None
                    else None,
                    "status_path": entry.status_path.as_posix()
                    if entry.status_path is not None
                    else None,
                    "new_status_path": entry.new_status_path.as_posix()
                    if entry.new_status_path is not None
                    else None,
                    "status_warning": entry.status_warning,
                    "detail": entry.detail,
                }
                for entry in self.entries
            ],
        }


@dataclass(frozen=True, slots=True)
class ArchiveRenumberResult:
    """Mutation result.  Errors always imply a non-zero CLI exit code."""

    renamed: int = 0
    status_updated: int = 0
    error: str | None = None
    recovery_required: bool = False
    recovery_details: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "renamed": self.renamed,
            "status_updated": self.status_updated,
            "error": self.error,
            "recovery_required": self.recovery_required,
            "recovery_details": list(self.recovery_details),
        }


def build_archive_renumber_plan(
    catalog: CatalogService,
    *,
    work_key: str | None = None,
    site: str | None = None,
    all_sources: bool = False,
    status_dir: str | Path = "output/crawl-status",
    watchlist: WatchlistService | None = None,
) -> ArchiveRenumberPlan:
    """Build and fully preflight a renumber plan without mutating anything."""

    _validate_scope(work_key=work_key, site=site, all_sources=all_sources)
    status_root = Path(status_dir)
    works, items, sources, _ = catalog.read_works_items_sources_and_targets(site=site)
    works_by_id = {work.id: work for work in works}
    items_by_id = {item.id: item for item in items}
    selected_sources = []
    for source in sources:
        item = items_by_id.get(source.item_id)
        work = works_by_id.get(item.work_id) if item is not None else None
        if item is None or work is None:
            selected_sources.append(source)
            continue
        if work_key is not None and work.work_key != work_key:
            continue
        selected_sources.append(source)

    watchlist_targets = watchlist.list_targets() if watchlist is not None else []
    targets_by_work: dict[str, list] = {}
    for target in watchlist_targets:
        targets_by_work.setdefault(target.work_key, []).append(target)
    opted_work_keys = {
        current_work_key
        for current_work_key, targets in targets_by_work.items()
        if any(target.archive_order is not None for target in targets)
    }
    selected_work_keys = {
        work.work_key
        for source in selected_sources
        if (item := items_by_id.get(source.item_id)) is not None
        and (work := works_by_id.get(item.work_id)) is not None
    }
    current_managed_work_keys = {
        current_work_key
        for current_work_key, targets in targets_by_work.items()
        if any(
            target.archive_order is not None or target.discovery_scope is not None
            for target in targets
        )
    }
    catalog_managed_work_keys: set[str] = set()
    for current_work_key in selected_work_keys:
        snapshot = catalog.read_acquisition_scope_snapshot(current_work_key)
        if snapshot is not None and (
            snapshot.sync is not None
            or snapshot.inventory_evidence
            or any(not source.acquisition_enabled for source in snapshot.sources)
        ):
            catalog_managed_work_keys.add(current_work_key)
    managed_work_keys = (
        selected_work_keys
        & (opted_work_keys | current_managed_work_keys | catalog_managed_work_keys)
    )
    ordered_work_keys = selected_work_keys & opted_work_keys
    strict_work_keys = tuple(sorted(managed_work_keys))
    if managed_work_keys and site is not None:
        raise ArchiveRenumberUsageError(
            "Watchlist-managed Works require a full work-wide renumber; remove --site and "
            "select only --work-key or --all"
        )

    strict_positions_by_source: dict[int, int] = {}
    strict_blockers: list[str] = []
    strict_revision_parts: list[object] = []
    if strict_work_keys:
        if watchlist is None:
            strict_blockers.append(
                "Watchlist-managed Work requires --watchlist for current acquisition flags and numbering"
            )
        else:
            for ordered_work_key in strict_work_keys:
                current_targets = [
                    target for target in targets_by_work[ordered_work_key]
                ] if ordered_work_key in targets_by_work else []
                current_work = next(
                    (value for value in works if value.work_key == ordered_work_key), None
                )
                if current_work is None:
                    strict_blockers.append(
                        f"{ordered_work_key}: Catalog Work is missing"
                    )
                    continue
                try:
                    snapshot = catalog.read_acquisition_scope_snapshot(
                        ordered_work_key, discovery_keys=[target.key for target in current_targets],
                    )
                    if not current_targets:
                        raise ScopeReconciliationError("Watchlist has no targets for this work_key")
                    if snapshot is None:
                        raise ScopeReconciliationError("Catalog Work is missing")
                    target_by_key = {target.key: target for target in current_targets}
                    if any(
                        owned.work_key != ordered_work_key
                        or owned.source.site != target_by_key[owned.source.discovery_key].site
                        for owned in snapshot.key_sources
                    ):
                        raise ScopeReconciliationError("Discovery key has mismatched Work/site ownership")
                    catalog_work_sources = {
                        source.id: source
                        for source in sources
                        if (item := items_by_id.get(source.item_id)) is not None
                        and item.work_id == current_work.id
                    }
                    if {
                        source.id: source for source in snapshot.sources
                    } != catalog_work_sources:
                        raise ScopeReconciliationError(
                            "Catalog Sources changed while taking the work-wide renumber snapshot"
                        )
                    snapshot_target_keys = {target.key for target in current_targets}
                    if {
                        source.discovery_key for source in snapshot.sources
                        if source.acquisition_enabled
                    } - snapshot_target_keys:
                        raise ScopeReconciliationError(
                            "Watchlist does not cover every acquisition-enabled Source"
                        )
                    if ordered_work_key in ordered_work_keys:
                        position_plan = build_work_archive_position_plan(
                            current_work,
                            current_targets,
                            items,
                            snapshot.sources,
                            provisional=True,
                        )
                        if position_plan is None:
                            raise ArchiveOrderPlanningError(
                                "Watchlist archive_order is no longer enabled"
                            )
                        strict_positions_by_source.update(
                            position_plan.positions_by_source_id
                        )
                    else:
                        if any(
                            target.archive_order is not None for target in current_targets
                        ):
                            raise ArchiveOrderPlanningError(
                                "Watchlist archive_order changed; create a new complete preview"
                            )
                        strict_positions_by_source.update(
                            {
                                source.id: source.display_position
                                for source in snapshot.sources
                                if source.acquisition_enabled
                                and source.display_position is not None
                            }
                        )
                    strict_revision_parts.append(
                        (ordered_work_key, snapshot.revision_token)
                    )
                except (ScopeReconciliationError, ArchiveOrderPlanningError, ValueError) as exc:
                    strict_blockers.append(f"{ordered_work_key}: {exc}")

    sources_by_site: dict[str, list[Source]] = {}
    for source in sources:
        sources_by_site.setdefault(source.site, []).append(source)
    collision_ids_by_site = {
        source_site: collision_source_ids(works, items, site_sources)
        for source_site, site_sources in sources_by_site.items()
    }

    entries: list[RenumberEntry] = []
    for source in selected_sources:
        item = items_by_id.get(source.item_id)
        work = works_by_id.get(item.work_id) if item is not None else None
        if item is None or work is None:
            entries.append(
                RenumberEntry(
                    work=work or Work(0, "<missing>", "<missing>", None, None, "", ""),
                    item=item or Item(0, 0, None, None, None, None, "pending", None, "", ""),
                    source=source,
                    status="ERROR",
                    detail="Catalog source references a missing Work or Item",
                )
            )
            continue
        entry = _preflight_source(
            catalog,
            work=work,
            item=item,
            source=source,
            status_dir=status_root,
            collision_source_ids_for_site=collision_ids_by_site.get(source.site, set()),
            archive_position=strict_positions_by_source.get(
                source.id, source.display_position
            ),
            strict=work.work_key in strict_work_keys,
        )
        if work.work_key in strict_work_keys and not source.acquisition_enabled:
            entry = RenumberEntry(
                work=work,
                item=item,
                source=source,
                status="EXCLUDED",
                run=entry.run,
                artifact=entry.artifact,
                old_path=entry.old_path,
                detail="Source is outside acquisition scope; existing ZIP is preserved",
            )
        entries.append(entry)

    all_archive_references = catalog.read_all_archive_references() if strict_work_keys else ()
    for entry in entries:
        if (
            entry.work.work_key not in strict_work_keys
            or entry.status != "RENAME"
            or entry.artifact is None
            or entry.old_path is None
        ):
            continue
        aliases = [
            reference
            for reference in all_archive_references
            if reference.id != entry.artifact.id
            and reference.storage_backend == "filesystem"
            and reference.locator is not None
            and _path_key(Path(reference.locator)) == _path_key(entry.old_path)
        ]
        if aliases:
            entry.status = "ERROR"
            entry.detail = (
                "selected ZIP path is also referenced by another current or historical "
                f"Artifact ({', '.join(str(reference.id) for reference in aliases[:5])}); "
                "repair the duplicate locator before renumbering"
            )

    _preflight_collisions(entries)
    for entry in entries:
        if entry.work.work_key not in strict_work_keys or entry.status == "EXCLUDED":
            continue
        if entry.status in {
            "ERROR", "COLLISION", "AMBIGUOUS", "MISSING", "UNSUPPORTED", "NO_POSITION"
        }:
            strict_blockers.append(
                f"Source {entry.source.id}: {entry.status}"
                + (f" ({entry.detail})" if entry.detail else "")
            )
        if entry.status_warning is not None:
            strict_blockers.append(
                f"Source {entry.source.id}: {entry.status_warning}"
            )
    strict_revision_parts.extend(
        (
            entry.work.work_key,
            entry.source.id,
            entry.source.acquisition_enabled,
            entry.source.display_position,
            entry.artifact.id if entry.artifact else None,
            entry.artifact.sha256 if entry.artifact else None,
            entry.artifact.byte_size if entry.artifact else None,
            entry.artifact.locator if entry.artifact else None,
            entry.status,
            entry.old_path.as_posix() if entry.old_path else None,
            entry.new_path.as_posix() if entry.new_path else None,
            hashlib.sha256(entry.status_path.read_bytes()).hexdigest()
            if entry.status_path is not None and entry.status_path.is_file()
            else None,
        )
        for entry in entries
        if entry.work.work_key in strict_work_keys
    )
    strict_revision = (
        hashlib.sha256(
            json.dumps(strict_revision_parts, ensure_ascii=False, default=str).encode("utf-8")
        ).hexdigest()
        if strict_work_keys
        else None
    )
    return ArchiveRenumberPlan(
        entries=entries,
        catalog=catalog,
        status_dir=status_root,
        work_key=work_key,
        site=site,
        all_sources=all_sources,
        watchlist_path=watchlist.path if watchlist is not None else None,
        strict_work_keys=strict_work_keys,
        strict_blockers=tuple(strict_blockers),
        strict_revision=strict_revision,
    )


def apply_archive_renumber_plan(plan: ArchiveRenumberPlan) -> ArchiveRenumberResult:
    """Apply a plan after a final fail-closed filesystem recheck."""

    with plan.catalog.job_lock():
        if plan.strict_blockers:
            return ArchiveRenumberResult(
                error="ERROR strict whole-work preflight blocked: "
                + "; ".join(plan.strict_blockers)
            )
        try:
            fresh_plan = build_archive_renumber_plan(
                plan.catalog,
                work_key=plan.work_key,
                site=plan.site,
                all_sources=plan.all_sources,
                status_dir=plan.status_dir,
                watchlist=(
                    WatchlistService(plan.watchlist_path)
                    if plan.watchlist_path is not None
                    else None
                ),
            )
        except (ArchiveRenumberUsageError, OSError, ValueError) as exc:
            return ArchiveRenumberResult(error=f"ERROR {exc}")
        if fresh_plan.strict_blockers:
            return ArchiveRenumberResult(
                error="ERROR strict whole-work preflight blocked: "
                + "; ".join(fresh_plan.strict_blockers)
            )
        if fresh_plan.strict_work_keys != plan.strict_work_keys:
            return ArchiveRenumberResult(
                error="ERROR acquisition-scope mode changed after preview; "
                "create a new full work-wide dry-run"
            )
        if _archive_renumber_plan_revision(fresh_plan) != _archive_renumber_plan_revision(plan):
            return ArchiveRenumberResult(
                error="ERROR Catalog, Watchlist, archive, or status changed after preview; "
                "create a new dry-run"
            )
        return _apply_archive_renumber_plan_locked(fresh_plan)


def _archive_renumber_plan_revision(plan: ArchiveRenumberPlan) -> str:
    payload = {
        "scope": [plan.work_key, plan.site, plan.all_sources],
        "watchlist": plan.watchlist_path.as_posix() if plan.watchlist_path else None,
        "strict_work_keys": plan.strict_work_keys,
        "strict_revision": plan.strict_revision,
        "entries": [
            [
                entry.work.work_key,
                entry.item.id,
                entry.source.id,
                entry.source.site,
                entry.source.external_id,
                entry.source.acquisition_enabled,
                entry.source.display_position,
                entry.status,
                entry.status_warning,
                entry.artifact.id if entry.artifact else None,
                entry.artifact.locator if entry.artifact else None,
                entry.artifact.sha256 if entry.artifact else None,
                entry.artifact.byte_size if entry.artifact else None,
                entry.old_path.as_posix() if entry.old_path else None,
                entry.new_path.as_posix() if entry.new_path else None,
                entry.status_path.as_posix() if entry.status_path else None,
                entry.new_status_path.as_posix() if entry.new_status_path else None,
            ]
            for entry in plan.entries
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


def _apply_archive_renumber_plan_locked(
    plan: ArchiveRenumberPlan,
) -> ArchiveRenumberResult:
    entries = plan.executable_entries
    if plan.strict_blockers:
        return ArchiveRenumberResult(
            error="ERROR strict whole-work preflight blocked: "
            + "; ".join(plan.strict_blockers)
        )
    if not entries:
        return ArchiveRenumberResult()
    try:
        _recheck_before_mutation(entries)
    except ArchiveRenumberPreflightError as exc:
        return ArchiveRenumberResult(error=f"ERROR {exc}")

    catalog_update_attempted = False
    assignments = {
        entry.artifact.id: (entry.artifact.locator, entry.new_path.as_posix())
        for entry in entries
        if entry.artifact is not None
        and entry.old_path is not None
        and entry.new_path is not None
    }
    try:
        for entry in entries:
            assert entry.old_path is not None
            assert entry.temporary_path is not None
            entry.zip_stage1_attempted = True
            entry.old_path.rename(entry.temporary_path)
            entry.zip_stage1_done = True
        for entry in entries:
            assert entry.temporary_path is not None
            assert entry.new_path is not None
            entry.zip_final_attempted = True
            entry.temporary_path.rename(entry.new_path)
            entry.zip_final_done = True

        status_entries = [entry for entry in entries if entry.status_path is not None]
        for entry in status_entries:
            assert entry.status_path is not None
            assert entry.status_temporary_path is not None
            entry.status_original_bytes = entry.status_path.read_bytes()
            payload = _read_matching_status(entry.status_path, entry.old_path)
            if payload is None:
                raise ArchiveRenumberPreflightError(
                    f"matching status changed during mutation: {entry.status_path}"
                )
            entry.status_payload = payload
            entry.status_stage1_attempted = True
            entry.status_path.rename(entry.status_temporary_path)
            entry.status_stage1_done = True
        for entry in status_entries:
            assert entry.status_temporary_path is not None
            assert entry.new_status_path is not None
            entry.status_final_attempted = True
            entry.status_temporary_path.rename(entry.new_status_path)
            entry.status_final_done = True
            assert entry.status_payload is not None
            assert entry.new_path is not None
            entry.status_payload["archive_path"] = entry.new_path.as_posix()
            atomic_write_json(entry.new_status_path, entry.status_payload)
            entry.status_updated = True

        catalog_update_attempted = True
        plan.catalog.update_artifact_locators(assignments)
    except BaseException as exc:  # noqa: BLE001 - rollback also on interruption
        if catalog_update_attempted:
            catalog_safe_to_rollback, catalog_details = _restore_catalog_after_failure(
                plan.catalog, assignments, entries
            )
            if not catalog_safe_to_rollback:
                return ArchiveRenumberResult(
                    error="RECOVERY_REQUIRED",
                    recovery_required=True,
                    recovery_details=tuple(catalog_details),
                )
        rollback_ok, details = _rollback(entries)
        if rollback_ok:
            if catalog_update_attempted:
                return ArchiveRenumberResult(
                    error="ERROR Catalog update failed; filesystem rollback completed"
                )
            return ArchiveRenumberResult(
                error=f"ERROR {exc.__class__.__name__}: {exc}; filesystem rollback completed"
            )
        return ArchiveRenumberResult(
            error="RECOVERY_REQUIRED",
            recovery_required=True,
            recovery_details=tuple(details),
        )

    return ArchiveRenumberResult(
        renamed=len(entries),
        status_updated=sum(entry.status_updated for entry in entries),
    )


def _restore_catalog_after_failure(
    catalog: CatalogService,
    assignments: dict[int, tuple[str | None, str]],
    entries: list[RenumberEntry],
) -> tuple[bool, list[str]]:
    """Prove Catalog locators are old, compensating an all-new committed update if needed."""

    if not assignments:
        return True, []
    ids = tuple(assignments)
    old_values = {artifact_id: pair[0] for artifact_id, pair in assignments.items()}
    new_values = {artifact_id: pair[1] for artifact_id, pair in assignments.items()}
    try:
        current = catalog.read_artifact_locators(ids)
    except BaseException as exc:  # noqa: BLE001 - unknown state must preserve files for recovery
        return False, _catalog_recovery_details(
            entries,
            current=None,
            explanation=f"Catalog locator read failed: {exc.__class__.__name__}: {exc}",
        )

    if current == old_values:
        return True, []
    if current != new_values:
        return False, _catalog_recovery_details(
            entries,
            current=current,
            explanation="Catalog locators are mixed or differ from both planned states",
        )

    compensation_error: BaseException | None = None
    try:
        catalog.update_artifact_locators(
            {artifact_id: (new_values[artifact_id], old_values[artifact_id]) for artifact_id in ids}
        )
    except BaseException as exc:  # noqa: BLE001 - verify even if a wrapper raises after commit
        compensation_error = exc
    try:
        restored = catalog.read_artifact_locators(ids)
    except BaseException as exc:  # noqa: BLE001 - unknown state must preserve files for recovery
        detail = "Catalog compensation state read failed: " f"{exc.__class__.__name__}: {exc}"
        if compensation_error is not None:
            detail += (
                "; compensation raised "
                f"{compensation_error.__class__.__name__}: {compensation_error}"
            )
        return False, _catalog_recovery_details(entries, current=None, explanation=detail)
    if restored == old_values:
        return True, []
    detail = "Catalog locator compensation did not restore every old locator"
    if compensation_error is not None:
        detail += (
            f"; compensation raised {compensation_error.__class__.__name__}: "
            f"{compensation_error}"
        )
    return False, _catalog_recovery_details(entries, current=restored, explanation=detail)


def _catalog_recovery_details(
    entries: list[RenumberEntry],
    *,
    current: dict[int, str | None] | None,
    explanation: str,
) -> list[str]:
    details = [explanation]
    for entry in entries:
        if entry.artifact is None:
            continue
        details.append(
            "artifact={artifact} old_locator={old_locator} new_locator={new_locator} "
            "catalog_locator={catalog_locator} old_path={old_path} new_path={new_path} "
            "actual_path={actual_path}".format(
                artifact=entry.artifact.id,
                old_locator=entry.artifact.locator,
                new_locator=entry.new_path.as_posix() if entry.new_path is not None else None,
                catalog_locator=(
                    current.get(entry.artifact.id, "<unknown>") if current is not None else "<unknown>"
                ),
                old_path=entry.old_path,
                new_path=entry.new_path,
                actual_path=_current_path(entry),
            )
        )
    return details


def _validate_scope(*, work_key: str | None, site: str | None, all_sources: bool) -> None:
    if all_sources and (work_key is not None or site is not None):
        raise ArchiveRenumberUsageError("--all cannot be combined with --work-key or --site")
    if not all_sources and work_key is None and site is None:
        raise ArchiveRenumberUsageError(
            "one of --work-key, --site, --work-key + --site, or --all is required"
        )
    for value, name in ((work_key, "work_key"), (site, "site")):
        if value is not None and not value.strip():
            raise ArchiveRenumberUsageError(f"{name} must be non-empty")


def _preflight_source(
    catalog: CatalogService,
    *,
    work: Work,
    item: Item,
    source: Source,
    status_dir: Path,
    collision_source_ids_for_site: set[int],
    archive_position: int | None = None,
    strict: bool = False,
) -> RenumberEntry:
    if archive_position is None:
        return RenumberEntry(work=work, item=item, source=source, status="NO_POSITION")

    run, artifact, selection_status = _select_current_archive(catalog, source.id)
    if selection_status != "RENAME":
        return RenumberEntry(
            work=work,
            item=item,
            source=source,
            status=selection_status,
            run=run,
            artifact=artifact,
        )
    assert artifact is not None
    if artifact.storage_backend != "filesystem":
        return RenumberEntry(
            work=work, item=item, source=source, status="UNSUPPORTED", run=run, artifact=artifact
        )
    if artifact.locator is None:
        return RenumberEntry(
            work=work, item=item, source=source, status="MISSING", run=run, artifact=artifact
        )
    old_path = Path(artifact.locator)
    if not old_path.is_file():
        return RenumberEntry(
            work=work,
            item=item,
            source=source,
            status="MISSING",
            run=run,
            artifact=artifact,
            old_path=old_path,
            detail="Artifact.locator is not a file",
        )

    if strict:
        actual_sha256, actual_byte_size = _hash_file(old_path)
        if (
            not artifact.sha256
            or artifact.byte_size is None
            or artifact.sha256 != actual_sha256
            or artifact.byte_size != actual_byte_size
        ):
            return RenumberEntry(
                work=work,
                item=item,
                source=source,
                status="ERROR",
                run=run,
                artifact=artifact,
                old_path=old_path,
                detail=(
                    "Catalog Artifact SHA-256/byte_size does not match the current ZIP; "
                    "repair the source data before renumbering"
                ),
                expected_sha256=artifact.sha256,
                expected_byte_size=artifact.byte_size,
            )

    disambiguator = (
        f"{source.site}-{source.external_id}"
        if source.id in collision_source_ids_for_site
        else None
    )
    stem = catalog_archive_stem(
        work,
        item,
        source,
        artifact_disambiguator=disambiguator,
        archive_position=archive_position,
    )
    new_path = old_path.parent / f"{stem}.zip"
    entry = RenumberEntry(
        work=work,
        item=item,
        source=source,
        status="UNCHANGED" if _path_key(old_path) == _path_key(new_path) else "RENAME",
        run=run,
        artifact=artifact,
        old_path=old_path,
        new_path=new_path,
        expected_sha256=artifact.sha256 if strict else None,
        expected_byte_size=artifact.byte_size if strict else None,
    )
    if entry.status == "RENAME":
        entry.temporary_path = _temporary_sibling(old_path, artifact.id, "archive-renumber")
    if entry.status == "RENAME" or strict:
        _inspect_status_candidate(entry, status_dir, strict=strict)
    return entry


def _select_current_archive(
    catalog: CatalogService, source_id: int
) -> tuple[CrawlRun | None, Artifact | None, str]:
    successful_runs = catalog.list_crawl_runs(source_id=source_id, status="succeeded")
    for run in reversed(successful_runs):
        archive_artifacts = [
            artifact
            for artifact in catalog.list_artifacts(crawl_run_id=run.id)
            if artifact.kind == "archive" and artifact.format == "zip"
        ]
        if not archive_artifacts:
            continue
        if len(archive_artifacts) > 1:
            return run, None, "AMBIGUOUS"
        return run, archive_artifacts[0], "RENAME"
    return None, None, "NO_ARTIFACT"


def _inspect_status_candidate(
    entry: RenumberEntry, status_dir: Path, *, strict: bool = False
) -> None:
    assert entry.old_path is not None
    assert entry.new_path is not None
    namespaced_dir = status_dir / safe_component(
        entry.work.genre, fallback="小説"
    ) / safe_component(entry.work.title, fallback="unknown-title")
    candidates = (
        namespaced_dir / f"{entry.old_path.stem}.json",
        # Keep explicit renumber compatible with status JSON produced before
        # work-scoped status directories were introduced.
        status_dir / f"{entry.old_path.stem}.json",
    )
    existing = [candidate for candidate in candidates if candidate.is_file()]
    if strict and len(existing) > 1:
        entry.status_warning = "STATUS_AMBIGUOUS"
        entry.detail = (
            "multiple status files reference or may refer to the same ZIP: "
            + ", ".join(path.as_posix() for path in existing)
        )
        return
    for candidate in existing:
        payload = _read_matching_status(candidate, entry.old_path)
        if payload is None:
            entry.status_warning = "STATUS_MISMATCH"
            return
        entry.status_path = candidate
        entry.new_status_path = candidate.with_name(f"{entry.new_path.stem}.json")
        entry.status_payload = payload
        entry.status_temporary_path = _temporary_sibling(
            candidate, entry.artifact.id, "status-renumber"
        )  # type: ignore[union-attr]
        return

    entry.new_status_path = status_dir / f"{entry.new_path.stem}.json"
    entry.status_warning = "STATUS_MISSING"


def _read_matching_status(path: Path, old_path: Path | None) -> dict[str, Any] | None:
    if old_path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or not _same_file(payload.get("archive_path"), old_path):
        return None
    return payload


def _same_file(value: object, expected: Path) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        actual = os.path.normcase(os.path.abspath(os.fspath(Path(value))))
        target = os.path.normcase(os.path.abspath(os.fspath(expected)))
    except (TypeError, ValueError, OSError):
        return False
    return actual == target


def _preflight_collisions(entries: list[RenumberEntry]) -> None:
    candidates = [entry for entry in entries if entry.status == "RENAME"]
    _mark_duplicate_targets(candidates, lambda entry: entry.old_path, "old path")
    _mark_duplicate_targets(candidates, lambda entry: entry.new_path, "target path")
    _mark_duplicate_targets(
        candidates,
        lambda entry: entry.status_path,
        "status path",
        skip_missing=True,
    )
    _mark_duplicate_targets(
        candidates,
        lambda entry: entry.new_status_path if entry.status_path is not None else None,
        "status target",
        skip_missing=True,
    )

    for entry in candidates:
        if entry.temporary_path is None or entry.temporary_path.exists():
            _collision(entry, "temporary path already exists")
        if entry.status_path is not None and (
            entry.status_temporary_path is None or entry.status_temporary_path.exists()
        ):
            _collision(entry, "status temporary path already exists")
        if entry.temporary_path is not None and any(
            _path_key(entry.temporary_path) == _path_key(other.new_path)
            for other in candidates
            if other.new_path is not None
        ):
            _collision(entry, "temporary path conflicts with a final target")

    changed = True
    while changed:
        changed = False
        active = [entry for entry in candidates if entry.status == "RENAME"]
        active_old = {_path_key(entry.old_path) for entry in active if entry.old_path is not None}
        active_status_old = {
            _path_key(entry.status_path) for entry in active if entry.status_path is not None
        }
        for entry in active:
            if (
                entry.new_path is not None
                and entry.new_path.exists()
                and _path_key(entry.new_path) not in active_old
            ):
                _collision(entry, "non-participating target file exists")
                changed = True
                continue
            if (
                entry.status_path is not None
                and entry.new_status_path is not None
                and entry.new_status_path.exists()
                and _path_key(entry.new_status_path) not in active_status_old
            ):
                _collision(entry, "non-participating status target exists")
                changed = True


def _mark_duplicate_targets(
    entries: list[RenumberEntry],
    path_getter: Any,
    label: str,
    *,
    skip_missing: bool = False,
) -> None:
    grouped: dict[str, list[RenumberEntry]] = {}
    for entry in entries:
        path = path_getter(entry)
        if path is None and skip_missing:
            continue
        if path is None:
            _collision(entry, f"missing {label}")
            continue
        grouped.setdefault(_path_key(path), []).append(entry)
    for group in grouped.values():
        if len(group) > 1:
            for entry in group:
                _collision(entry, f"duplicate {label}")


def _collision(entry: RenumberEntry, detail: str) -> None:
    if entry.status == "RENAME":
        entry.status = "COLLISION"
        entry.detail = detail


def _recheck_before_mutation(entries: list[RenumberEntry]) -> None:
    active_old = {_path_key(entry.old_path) for entry in entries if entry.old_path is not None}
    active_status_old = {
        _path_key(entry.status_path) for entry in entries if entry.status_path is not None
    }
    for entry in entries:
        assert entry.old_path is not None
        assert entry.new_path is not None
        assert entry.temporary_path is not None
        if not entry.old_path.is_file():
            raise ArchiveRenumberPreflightError(f"old path changed: {entry.old_path}")
        entry.rollback_sha256, entry.rollback_byte_size = _hash_file(entry.old_path)
        if entry.expected_sha256 is not None and (
            entry.rollback_sha256 != entry.expected_sha256
            or entry.rollback_byte_size != entry.expected_byte_size
        ):
            raise ArchiveRenumberPreflightError(
                f"archive bytes changed after preview: {entry.old_path}"
            )
        if entry.temporary_path.exists():
            raise ArchiveRenumberPreflightError(f"temporary path appeared: {entry.temporary_path}")
        if entry.new_path.exists() and _path_key(entry.new_path) not in active_old:
            raise ArchiveRenumberPreflightError(f"target path appeared: {entry.new_path}")
        if entry.status_path is None:
            continue
        assert entry.new_status_path is not None
        assert entry.status_temporary_path is not None
        if not entry.status_path.is_file():
            raise ArchiveRenumberPreflightError(f"status path changed: {entry.status_path}")
        entry.status_original_bytes = entry.status_path.read_bytes()
        if entry.status_temporary_path.exists():
            raise ArchiveRenumberPreflightError(
                f"status temporary path appeared: {entry.status_temporary_path}"
            )
        if entry.new_status_path.exists() and _path_key(entry.new_status_path) not in active_status_old:
            raise ArchiveRenumberPreflightError(
                f"status target appeared: {entry.new_status_path}"
            )
        if _read_matching_status(entry.status_path, entry.old_path) is None:
            raise ArchiveRenumberPreflightError(
                f"status content changed: {entry.status_path}"
            )


def _rollback(entries: list[RenumberEntry]) -> tuple[bool, list[str]]:
    details: list[str] = []
    rollback_paths: list[Path] = []
    try:
        zip_states: list[tuple[RenumberEntry, Path, Path]] = []
        for entry in entries:
            if entry.old_path is None or entry.artifact is None:
                continue
            current: Path | None
            if entry.zip_final_attempted:
                if entry.temporary_path is not None and entry.temporary_path.exists():
                    current = entry.temporary_path
                elif entry.new_path is not None and entry.new_path.exists():
                    current = entry.new_path
                else:
                    raise OSError(f"archive location is unknown: {entry.old_path}")
            elif entry.zip_stage1_attempted:
                if entry.temporary_path is not None and entry.temporary_path.exists():
                    current = entry.temporary_path
                elif entry.old_path.exists():
                    current = None  # The attempted rename did not move this archive.
                else:
                    raise OSError(f"archive location is unknown: {entry.old_path}")
            else:
                current = None
                if not entry.old_path.exists():
                    raise OSError(f"untouched archive is missing: {entry.old_path}")
            rollback_path = _temporary_sibling(
                entry.old_path, entry.artifact.id, "archive-rollback"
            )
            if rollback_path.exists():
                raise OSError(f"rollback temporary path exists: {rollback_path}")
            zip_states.append((entry, current or entry.old_path, rollback_path))

        # Stage every selected ZIP first so partial cycles/swaps cannot block restoration.
        for _entry, current, rollback_path in zip_states:
            rollback_paths.append(rollback_path)
            current.rename(rollback_path)
        for entry, _current, rollback_path in zip_states:
            assert entry.old_path is not None
            rollback_path.rename(entry.old_path)

        status_states: list[tuple[RenumberEntry, Path, Path]] = []
        for entry in entries:
            if entry.status_path is None or entry.artifact is None:
                continue
            current: Path | None
            if entry.status_final_attempted:
                if (
                    entry.status_temporary_path is not None
                    and entry.status_temporary_path.exists()
                ):
                    current = entry.status_temporary_path
                elif entry.new_status_path is not None and entry.new_status_path.exists():
                    current = entry.new_status_path
                else:
                    raise OSError(f"status location is unknown: {entry.status_path}")
            elif entry.status_stage1_attempted:
                if (
                    entry.status_temporary_path is not None
                    and entry.status_temporary_path.exists()
                ):
                    current = entry.status_temporary_path
                elif entry.status_path.exists():
                    current = None
                else:
                    raise OSError(f"status location is unknown: {entry.status_path}")
            else:
                current = None
                if not entry.status_path.exists():
                    raise OSError(f"untouched status is missing: {entry.status_path}")
            rollback_path = _temporary_sibling(
                entry.status_path, entry.artifact.id, "status-rollback"
            )
            if rollback_path.exists():
                raise OSError(f"status rollback temporary path exists: {rollback_path}")
            status_states.append((entry, current or entry.status_path, rollback_path))

        for _entry, current, rollback_path in status_states:
            rollback_paths.append(rollback_path)
            current.rename(rollback_path)
        for entry, _current, rollback_path in status_states:
            assert entry.status_path is not None
            rollback_path.rename(entry.status_path)
            if entry.status_original_bytes is not None:
                entry.status_path.write_bytes(entry.status_original_bytes)

        # Rollback is complete only if original paths/content are restored and no generated
        # staging file remains. This check covers rename wrappers interrupted after success.
        for entry in entries:
            if entry.old_path is not None:
                if not entry.old_path.is_file():
                    raise OSError(f"original archive path was not restored: {entry.old_path}")
                if entry.rollback_sha256 is not None:
                    actual_sha256, actual_size = _hash_file(entry.old_path)
                    if (
                        actual_sha256 != entry.rollback_sha256
                        or actual_size != entry.rollback_byte_size
                    ):
                        raise OSError(f"original archive bytes were not restored: {entry.old_path}")
            if entry.status_path is not None:
                if not entry.status_path.is_file():
                    raise OSError(f"original status path was not restored: {entry.status_path}")
                if (
                    entry.status_original_bytes is not None
                    and entry.status_path.read_bytes() != entry.status_original_bytes
                ):
                    raise OSError(f"original status bytes were not restored: {entry.status_path}")
            for temporary in (
                entry.temporary_path,
                entry.status_temporary_path,
            ):
                if temporary is not None and temporary.exists():
                    raise OSError(f"renumber temporary path remains: {temporary}")
        remaining = [path for path in rollback_paths if path.exists()]
        if remaining:
            raise OSError(
                "rollback temporary paths remain: "
                + ", ".join(path.as_posix() for path in remaining)
            )
    except BaseException as exc:  # noqa: BLE001 - rollback must never overclaim recovery
        for entry in entries:
            details.append(
                "artifact={artifact} old={old} new={new} current={current} temporary={temporary} "
                "status_old={status_old} status_new={status_new} status_temp={status_temp}".format(
                    artifact=entry.artifact.id if entry.artifact else "<none>",
                    old=entry.old_path,
                    new=entry.new_path,
                    current=_current_path(entry),
                    temporary=entry.temporary_path,
                    status_old=entry.status_path,
                    status_new=entry.new_status_path,
                    status_temp=entry.status_temporary_path,
                )
            )
        details.append(f"rollback_error={exc.__class__.__name__}: {exc}")
        return False, details
    return True, details


def _current_path(entry: RenumberEntry) -> Path | None:
    candidates = (
        entry.new_path,
        entry.temporary_path,
        entry.new_status_path,
        entry.status_temporary_path,
    )
    for path in candidates:
        if path is not None and path.exists():
            return path
    for path in (entry.old_path, entry.status_path):
        if path is not None and path.exists():
            return path
    if entry.zip_final_done:
        return entry.new_path
    if entry.zip_stage1_done:
        return entry.temporary_path
    if entry.status_final_done:
        return entry.new_status_path
    if entry.status_stage1_done:
        return entry.status_temporary_path
    return None


def _temporary_sibling(path: Path, artifact_id: int, kind: str) -> Path:
    return path.with_name(f".{kind}-{artifact_id}.tmp")


def _path_key(path: Path | None) -> str:
    if path is None:
        return "<none>"
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    byte_size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            byte_size += len(chunk)
    return digest.hexdigest(), byte_size
