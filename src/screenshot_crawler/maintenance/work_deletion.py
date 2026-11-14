"""Work deletion planning and the manifest-backed destructive operation.

Preview remains immutable and Qt-free. Apply/recovery are shared by the
explicit CLI and GUI surfaces; both require a fresh canonical preview and the
same fail-closed locks, fingerprints, and durable manifest checks.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import threading
import time
from collections.abc import Iterable
from contextlib import ExitStack
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from screenshot_crawler.catalog import schema as catalog_schema
from screenshot_crawler.catalog.backup import backup_catalog
from screenshot_crawler.catalog.job_lock import CatalogJobLock
from screenshot_crawler.catalog.service import CatalogError, CatalogService
from screenshot_crawler.management.jobs import TERMINAL_JOB_STATES
from screenshot_crawler.management.process_identity import process_is_alive, process_start_identity
from screenshot_crawler.watchlist.service import WatchlistService

_TABLES = (
    "works", "items", "sources", "source_targets", "crawl_runs", "artifacts",
    "quota_resource_states", "acquisition_scope_sync",
    "discovery_inventory_evidence", "discovery_inventory_positions",
)
_ACTIVE_JOB_STATES = {"queued", "planning", "running"}
_FINISHED_JOB_STATES = (TERMINAL_JOB_STATES - {"interrupted"}) | {"completed", "aborted"}
_REPARSE_POINT = 0x400


def _unknown_catalog_schema(connection: sqlite3.Connection) -> tuple[str, ...]:
    """Return extra user tables/columns outside the deletion authority schema."""

    expected_tables = set(_TABLES)
    actual_tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }
    blockers = [f"catalog_unknown_table:{name}" for name in sorted(actual_tables - expected_tables)]
    for table in sorted(actual_tables & expected_tables):
        actual_columns = {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
        expected_columns = set(catalog_schema._REQUIRED_COLUMNS[table])
        blockers.extend(f"catalog_unknown_column:{table}:{name}" for name in sorted(actual_columns - expected_columns))
        blockers.extend(f"catalog_missing_column:{table}:{name}" for name in sorted(expected_columns - actual_columns))
    return tuple(blockers)


@dataclass(frozen=True, slots=True)
class ArtifactPreview:
    artifact_id: int
    item_id: int
    crawl_run_id: int | None
    kind: str
    format: str
    state: str
    storage_backend: str
    locator: str | None
    source_path: str | None
    destination_path: str | None
    status_paths: tuple[str, ...]
    status_destination_paths: tuple[str, ...]
    status_facts: tuple[tuple[str, str, int, str, int, int], ...]
    source_device: int | None
    source_inode: int | None
    byte_size: int
    sha256: str
    actual_byte_size: int | None
    actual_sha256: str | None
    move_eligible: bool
    blockers: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "item_id": self.item_id,
            "crawl_run_id": self.crawl_run_id,
            "kind": self.kind,
            "format": self.format,
            "state": self.state,
            "storage_backend": self.storage_backend,
            "locator": self.locator,
            "source_path": self.source_path,
            "destination_path": self.destination_path,
            "status_paths": list(self.status_paths),
            "status_destination_paths": list(self.status_destination_paths),
            "status_facts": [list(fact) for fact in self.status_facts],
            "source_device": self.source_device,
            "source_inode": self.source_inode,
            "byte_size": self.byte_size,
            "sha256": self.sha256,
            "actual_byte_size": self.actual_byte_size,
            "actual_sha256": self.actual_sha256,
            "move_eligible": self.move_eligible,
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True, slots=True)
class WorkDeletionPlan:
    work_key: str
    work_id: int | None
    work_title: str | None
    site_keys: tuple[tuple[str, str], ...]
    catalog_path: str
    watchlist_path: str
    catalog_fingerprint: str
    watchlist_revision: str
    catalog_identity: str
    management_paths: tuple[str, ...]
    management_fingerprints: tuple[tuple[str, str], ...]
    job_states: tuple[tuple[str, str, str], ...]
    item_ids: tuple[int, ...]
    source_ids: tuple[int, ...]
    source_target_ids: tuple[int, ...]
    crawl_run_ids: tuple[int, ...]
    artifact_ids: tuple[int, ...]
    quota_resource_state_ids: tuple[int, ...]
    scope_sync_present: bool
    discovery_keys: tuple[str, ...]
    discovery_position_count: int
    watchlist_keys: tuple[str, ...]
    archived: bool
    artifacts: tuple[ArtifactPreview, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    plan_token: str
    operation_namespace: str
    root_identities: tuple[tuple[str, str, int | None], ...] = ()
    destination_fingerprint: str = "missing"
    deletion_gate_fingerprint: str = "none"

    @property
    def ready(self) -> bool:
        return not self.blockers and (self.work_id is not None or bool(self.watchlist_keys) or self.archived)

    @property
    def zip_count(self) -> int:
        return sum(1 for artifact in self.artifacts if artifact.move_eligible and artifact.format.casefold() == "zip")

    @property
    def byte_size(self) -> int:
        return sum(artifact.byte_size for artifact in self.artifacts if artifact.move_eligible)

    def as_dict(self) -> dict[str, Any]:
        return {
            "work_key": self.work_key,
            "work_id": self.work_id,
            "work_title": self.work_title,
            "site_keys": [list(pair) for pair in self.site_keys],
            "catalog_path": self.catalog_path,
            "watchlist_path": self.watchlist_path,
            "catalog_fingerprint": self.catalog_fingerprint,
            "watchlist_revision": self.watchlist_revision,
            "catalog_identity": self.catalog_identity,
            "management_paths": list(self.management_paths),
            "management_fingerprints": [list(pair) for pair in self.management_fingerprints],
            "job_states": [list(row) for row in self.job_states],
            "item_ids": list(self.item_ids),
            "source_ids": list(self.source_ids),
            "source_target_ids": list(self.source_target_ids),
            "crawl_run_ids": list(self.crawl_run_ids),
            "artifact_ids": list(self.artifact_ids),
            "quota_resource_state_ids": list(self.quota_resource_state_ids),
            "scope_sync_present": self.scope_sync_present,
            "discovery_keys": list(self.discovery_keys),
            "discovery_position_count": self.discovery_position_count,
            "watchlist_keys": list(self.watchlist_keys),
            "archived": self.archived,
            "artifacts": [artifact.as_dict() for artifact in self.artifacts],
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "plan_token": self.plan_token,
            "operation_namespace": self.operation_namespace,
            "root_identities": [list(row) for row in self.root_identities],
            "destination_fingerprint": self.destination_fingerprint,
            "deletion_gate_fingerprint": self.deletion_gate_fingerprint,
            "ready": self.ready,
            "zip_count": self.zip_count,
            "byte_size": self.byte_size,
        }


class WorkDeletionApplyError(RuntimeError):
    """Raised when an apply cannot safely complete."""


class WorkDeletionCancelled(RuntimeError):
    """Raised when a read-only preview cooperatively stops before publication."""


class WorkDeletionCancelToken:
    """Qt-independent cooperative cancellation for preview only."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()


def _preview_checkpoint(
    callback: Any | None,
    token: WorkDeletionCancelToken | Any | None,
    stage: str,
    completed: int,
    total: int,
    started: float,
) -> None:
    _raise_if_cancelled(token)
    if callback is not None:
        callback(stage, completed, total, max(0.0, time.monotonic() - started))
    # A callback may cancel synchronously (the GUI does this at a safe
    # checkpoint).  Recheck after notification so the final `complete` event
    # cannot publish a cached Plan after cancellation.
    _raise_if_cancelled(token)


def _raise_if_cancelled(token: WorkDeletionCancelToken | Any | None) -> None:
    cancelled = getattr(token, "is_cancelled", None)
    if callable(cancelled) and cancelled():
        raise WorkDeletionCancelled("work deletion preview cancelled")
    if token is not None and not callable(cancelled) and bool(getattr(token, "cancelled", False)):
        raise WorkDeletionCancelled("work deletion preview cancelled")


@dataclass(frozen=True, slots=True)
class WorkDeletionApplyResult:
    operation_id: str
    status: str
    manifest_path: str
    plan_token: str


@dataclass(frozen=True, slots=True)
class WorkDeletionRecoveryResult:
    """Durable recovery inspection or explicit recovery outcome."""

    operation_id: str
    status: str
    manifest_path: str | None
    details: tuple[str, ...] = ()


class WorkDeletionPreviewService:
    """Build immutable, no-write deletion previews from isolated inputs."""

    def __init__(self) -> None:
        self._plans: dict[str, WorkDeletionPlan] = {}

    def preview(
        self,
        work_key: str,
        *,
        catalog_path: str | Path = "catalog.sqlite",
        watchlist_path: str | Path = "watchlist.yaml",
        management_paths: Iterable[str | Path] = (),
        library_root: str | Path | None = None,
        status_root: str | Path | None = None,
        trash_root: str | Path | None = None,
        progress: Any | None = None,
        cancel: WorkDeletionCancelToken | Any | None = None,
    ) -> WorkDeletionPlan:
        if not isinstance(work_key, str) or not work_key or work_key != work_key.strip():
            raise ValueError("work_key must be a non-empty, trimmed string")
        started = time.monotonic()
        _preview_checkpoint(progress, cancel, "starting", 0, 1, started)
        catalog = Path(catalog_path)
        watchlist = Path(watchlist_path)
        catalog_resolved = catalog.resolve(strict=False)
        watchlist_resolved = watchlist.resolve(strict=False)
        watch_doc, watch_revision = self._read_watchlist(watchlist)
        _preview_checkpoint(progress, cancel, "watchlist", 1, 1, started)
        targets = tuple(target for target in watch_doc[0] if target.work_key == work_key)
        archived = work_key in watch_doc[1]
        blockers: list[str] = []
        warnings: list[str] = []
        # Match the established packaging layout and keep the default trash
        # outside both source roots.  These are captured below as absolute
        # paths, so an asynchronous caller cannot re-resolve them under a
        # different CWD.
        library_input = Path(library_root) if library_root is not None else Path("output/Books")
        status_input = Path(status_root) if status_root is not None else Path("output/crawl-status")
        trash_input = Path(trash_root) if trash_root is not None else Path("output/trash/work-deletion")
        for label, root in (("library", library_input), ("status", status_input), ("trash", trash_input)):
            if _raw_path_unsafe(str(root), catalog_resolved.parent):
                blockers.append(f"unsafe_{label}_root")
        management = tuple(sorted({str(Path(path).resolve(strict=False)) for path in management_paths}))
        namespace = _namespace(catalog_resolved)
        deletion_gate_fingerprint, gate_blockers = self._read_deletion_gate(catalog_resolved, namespace)
        blockers.extend(gate_blockers)
        registry_blockers, bound_management = self._check_management_registry(catalog, namespace, management)
        blockers.extend(registry_blockers)
        if bound_management:
            if management and set(management) != set(bound_management) and "management_store_binding_mismatch" not in blockers:
                blockers.append("management_store_binding_mismatch")
            management = bound_management
        management_rows, management_fingerprints, management_blockers = self._read_management(
            management if bound_management else (), work_key, catalog_resolved
        )
        blockers.extend(management_blockers)
        _preview_checkpoint(progress, cancel, "management", 1, 1, started)
        library_resolved = library_input.resolve(strict=False)
        status_resolved = status_input.resolve(strict=False)
        trash_resolved = trash_input.resolve(strict=False)
        root_identities = _root_identities(library_resolved, status_resolved, trash_resolved)
        if catalog.exists():
            _preview_checkpoint(progress, cancel, "catalog", 0, 1, started)
            graph = self._read_catalog(catalog, work_key)
            work_id = graph["work_id"]
            work_title = graph.get("work_title")
            site_keys = tuple(graph.get("site_keys", ()))
            catalog_fingerprint = graph["fingerprint"]
            catalog_identity = _path_identity(catalog_resolved)
            if work_id is not None:
                if not management and not registry_blockers:
                    blockers.append("management_store_unbound")
            else:
                pass
            item_ids = tuple(graph["item_ids"])
            source_ids = tuple(graph["source_ids"])
            source_target_ids = tuple(graph["source_target_ids"])
            crawl_run_ids = tuple(graph["crawl_run_ids"])
            artifact_ids = tuple(graph["artifact_ids"])
            quota_ids = tuple(graph["quota_ids"])
            scope_present = bool(graph["scope_present"])
            discovery_keys = tuple(graph["discovery_keys"])
            position_count = int(graph["position_count"])
            library_index, library_scan_failed = _build_library_index(
                library_resolved, progress=progress, cancel=cancel, started=started
            )
            status_index = _build_status_index(
                status_resolved, trash_resolved,
                library_root=library_resolved,
                archive_paths=tuple(
                    self._canonical_path(str(row["locator"]), catalog_resolved.parent)
                    for row in graph["artifacts"]
                    if row["locator"] and str(row["kind"]).casefold() == "archive"
                    and str(row["format"]).casefold() == "zip"
                    and str(row["storage_backend"]).casefold() == "filesystem"
                    and not _raw_path_unsafe(str(row["locator"]), catalog_resolved.parent)
                ),
                progress=progress, cancel=cancel, started=started,
            )
            _preview_checkpoint(progress, cancel, "filesystem_index", 1, 1, started)
            artifacts = self._inspect_artifacts(
                graph["artifacts"], graph["all_artifacts"],
                catalog_resolved.parent,
                library_resolved,
                status_resolved,
                trash_resolved,
                blockers, warnings, int(work_id) if work_id is not None else None,
                library_index=library_index,
                library_scan_failed=library_scan_failed,
                status_index=status_index,
                progress=progress,
                cancel=cancel,
                started=started,
            )
            blockers.extend(graph["graph_blockers"])
            _preview_checkpoint(progress, cancel, "catalog", 1, 1, started)
        else:
            work_id = None
            work_title = None
            site_keys = ()
            catalog_fingerprint = "missing"
            catalog_identity = _path_identity(catalog_resolved)
            namespace = _namespace(catalog_resolved)
            item_ids = source_ids = source_target_ids = crawl_run_ids = artifact_ids = quota_ids = ()
            scope_present = False
            discovery_keys = ()
            position_count = 0
            artifacts = ()
        if work_id is None and not targets and not archived:
            blockers.append("not_found")
        if watchlist.exists():
            try:
                raw = watchlist.read_bytes()
                if not raw:
                    warnings.append("watchlist_empty")
            except OSError as exc:
                blockers.append(f"watchlist_read_failed:{exc}")
        else:
            warnings.append("watchlist_missing")
        # Keep the token stable for identical read snapshots and inputs.
        token_payload = {
            "work_key": work_key,
            "work_id": work_id,
            "catalog": catalog_fingerprint,
            "catalog_path": str(catalog_resolved),
            "catalog_identity": catalog_identity,
            "watchlist_path": str(watchlist_resolved),
            "operation_namespace": namespace,
            "watchlist": watch_revision,
            "management": management_fingerprints,
            "roots": root_identities,
            "deletion_gate": deletion_gate_fingerprint,
            "artifacts": [artifact.as_dict() for artifact in artifacts],
        }
        token = _sha256_json(token_payload)
        destination_fingerprint, destination_blockers = _destination_snapshot(trash_resolved / token)
        blockers.extend(destination_blockers)
        artifacts = tuple(
            replace(
                artifact,
                destination_path=(artifact.destination_path.replace("<operation-id>", token)
                                  if artifact.destination_path else None),
                status_destination_paths=tuple(
                    path.replace("<operation-id>", token)
                    for path in artifact.status_destination_paths
                ),
                status_facts=tuple(
                    (source.replace("<operation-id>", token), destination.replace("<operation-id>", token), size, digest, device, inode)
                    for source, destination, size, digest, device, inode in artifact.status_facts
                ),
            )
            if artifact.destination_path or artifact.status_destination_paths or artifact.status_facts else artifact
            for artifact in artifacts
        )
        result = WorkDeletionPlan(
            work_key=work_key,
            work_id=work_id,
            work_title=work_title,
            site_keys=site_keys,
            catalog_path=str(catalog_resolved),
            watchlist_path=str(watchlist_resolved),
            catalog_fingerprint=catalog_fingerprint,
            watchlist_revision=watch_revision,
            catalog_identity=catalog_identity,
            management_paths=management,
            management_fingerprints=management_fingerprints,
            job_states=management_rows,
            item_ids=item_ids,
            source_ids=source_ids,
            source_target_ids=source_target_ids,
            crawl_run_ids=crawl_run_ids,
            artifact_ids=artifact_ids,
            quota_resource_state_ids=quota_ids,
            scope_sync_present=scope_present,
            discovery_keys=discovery_keys,
            discovery_position_count=position_count,
            watchlist_keys=tuple(target.key for target in targets),
            archived=archived,
            artifacts=artifacts,
            blockers=tuple(dict.fromkeys(blockers)),
            warnings=tuple(dict.fromkeys(warnings)),
            plan_token=token,
            operation_namespace=namespace,
            root_identities=root_identities,
            destination_fingerprint=destination_fingerprint,
            deletion_gate_fingerprint=deletion_gate_fingerprint,
        )
        _preview_checkpoint(progress, cancel, "complete", 1, 1, started)
        self._plans[token] = result
        return result

    def apply(
        self,
        plan: WorkDeletionPlan | str,
        *,
        failure_hook: Any | None = None,
    ) -> WorkDeletionApplyResult:
        """Apply one already-previewed plan under admission/Catalog/Watchlist locks.

        CLI and GUI callers still enter through this service so the canonical
        cached Plan, fresh locked preview, and recovery manifest remain the
        only operation authority.
        """

        if isinstance(plan, str):
            cached = self._plans.get(plan)
            if cached is None:
                raise WorkDeletionApplyError("unknown work deletion plan token")
            plan = cached
        elif isinstance(plan, WorkDeletionPlan):
            cached = self._plans.get(plan.plan_token)
            if cached is None or cached != plan:
                raise WorkDeletionApplyError("plan is not the canonical preview cached by this service")
            plan = cached
        if not isinstance(plan, WorkDeletionPlan) or not plan.ready:
            raise WorkDeletionApplyError("work deletion plan is not ready")
        catalog = Path(plan.catalog_path)
        watchlist = Path(plan.watchlist_path)
        library = Path(next(value for label, value, _device in plan.root_identities if label == "library"))
        status_root = Path(next(value for label, value, _device in plan.root_identities if label == "status"))
        trash_root = Path(next(value for label, value, _device in plan.root_identities if label == "trash"))
        namespace = _namespace(catalog)
        admission_path = catalog.parent / ".work-deletion" / namespace / "admission"
        moved: list[tuple[Path, Path]] = []
        operation_dir: Path | None = None
        manifest: Path | None = None
        operation_reserved = False
        active_marker = catalog.parent / ".work-deletion" / namespace / "active.json"
        active_reserved = False
        catalog_committed = False
        watchlist_committed = False

        with CatalogJobLock(admission_path), ExitStack() as locks:
            # The lock is Catalog-identity scoped and does not create the DB;
            # retain the same ordering for Watchlist-only works too.
            locks.enter_context(CatalogService(catalog).job_lock())
            locks.enter_context(WatchlistService(watchlist).edit_lock())
            fresh = self.preview(
                plan.work_key,
                catalog_path=catalog,
                watchlist_path=watchlist,
                management_paths=plan.management_paths,
                library_root=library,
                status_root=status_root,
                trash_root=trash_root,
            )
            if not fresh.ready or fresh.plan_token != plan.plan_token:
                raise WorkDeletionApplyError("work deletion plan is stale or blocked")
            # The fresh locked snapshot, not caller-controlled dataclass fields,
            # is the sole authority for every subsequent path/ID/move operation.
            plan = fresh
            catalog = Path(plan.catalog_path)
            watchlist = Path(plan.watchlist_path)
            library = Path(next(value for label, value, _device in plan.root_identities if label == "library"))
            status_root = Path(next(value for label, value, _device in plan.root_identities if label == "status"))
            trash_root = Path(next(value for label, value, _device in plan.root_identities if label == "trash"))
            manifest_binding = {
                "catalog_path": str(catalog.resolve(strict=False)),
                "watchlist_path": str(watchlist.resolve(strict=False)),
                "operation_namespace": namespace,
                "active_marker": str(active_marker),
            }
            operation_dir = trash_root / fresh.plan_token
            manifest = operation_dir / "manifest.json"
            try:
                trash_root.mkdir(parents=True, exist_ok=True)
                # Reserve the operation namespace before any snapshot or
                # marker write.  A pre-existing directory is an explicit
                # collision; never merge into or overwrite its contents.
                operation_dir.mkdir()
                operation_reserved = True
                catalog_before = _file_fact(catalog)
                catalog_backup: dict[str, Any] | None = None
                catalog_non_target_before = _catalog_non_target_fingerprint(catalog, fresh)
                before_watchlist = _watchlist_fact(watchlist)
                watchlist_before_path: str | None = None
                watchlist_after_path: str | None = None
                watchlist_after: dict[str, Any] | None = None
                watchlist_non_target_before = _watchlist_non_target_snapshot(watchlist, fresh.work_key)
                if watchlist.exists():
                    before_copy = operation_dir / "watchlist-before.yaml"
                    _write_snapshot(before_copy, watchlist.read_bytes())
                    watchlist_before_path = str(before_copy)
                intents = _move_intents(fresh)
                _reserve_active(active_marker, {
                    "phase": "active", "operation_id": fresh.plan_token,
                    "work_key": fresh.work_key, "work_id": fresh.work_id,
                    "manifest": str(manifest),
                })
                active_reserved = True
                _hook(failure_hook, "after_active_reservation")
                _fsync_directory(trash_root)
                _write_manifest(manifest, {
                    **manifest_binding,
                    "operation_id": fresh.plan_token,
                    "phase": "PREPARED",
                    "work_key": fresh.work_key,
                    "work_id": fresh.work_id,
                    "plan_token": fresh.plan_token,
                    "catalog_path": str(catalog.resolve(strict=False)),
                    "watchlist_path": str(watchlist.resolve(strict=False)),
                    "operation_namespace": namespace,
                    "active_marker": str(active_marker),
                    "catalog_before": catalog_before,
                    "catalog_backup": catalog_backup,
                    "catalog_non_target_before": catalog_non_target_before,
                    "catalog_expected_fingerprint": fresh.catalog_fingerprint,
                    "watchlist_before": before_watchlist,
                    "watchlist_before_path": watchlist_before_path,
                    "watchlist_expected_after": None,
                    "watchlist_expected_revision": fresh.watchlist_revision,
                    "watchlist_after": None,
                    "intents": intents,
                })
                _record_operation_ref(active_marker.parent, fresh.plan_token, manifest)
                _hook(failure_hook, "after_manifest")
                if catalog.exists():
                    backup_catalog(catalog, operation_dir / "catalog-before.sqlite")
                    catalog_backup = _file_fact(operation_dir / "catalog-before.sqlite")
                    _write_manifest(manifest, {
                        **manifest_binding,
                        "operation_id": fresh.plan_token, "phase": "BACKUP_READY",
                        "work_key": fresh.work_key, "work_id": fresh.work_id,
                        "plan_token": fresh.plan_token, "catalog_before": catalog_before,
                        "catalog_backup": catalog_backup,
                        "catalog_expected_fingerprint": fresh.catalog_fingerprint,
                        "watchlist_before": before_watchlist,
                        "watchlist_before_path": watchlist_before_path,
                        "watchlist_expected_after": None,
                        "watchlist_expected_revision": fresh.watchlist_revision,
                        "watchlist_after": None, "intents": intents,
                    })
                    _hook(failure_hook, "after_backup")
                for intent in intents:
                    source = Path(intent["source"])
                    destination = Path(intent["destination"])
                    intent["state"] = "INTENT"
                    _write_manifest(manifest, {
                        **manifest_binding,
                        "operation_id": fresh.plan_token, "phase": "FILE_INTENT",
                        "work_key": fresh.work_key, "work_id": fresh.work_id,
                        "plan_token": fresh.plan_token, "catalog_before": catalog_before,
                        "catalog_backup": catalog_backup,
                        "catalog_expected_fingerprint": fresh.catalog_fingerprint,
                        "watchlist_before": before_watchlist,
                        "watchlist_before_path": watchlist_before_path,
                        "watchlist_expected_revision": fresh.watchlist_revision,
                        "watchlist_expected_after": None, "watchlist_after": None,
                        "intents": intents,
                    })
                    _hook(failure_hook, "before_each_move")
                    try:
                        _move_no_clobber(source, destination, int(intent["size"]), str(intent["sha256"]), intent.get("device"), intent.get("inode"))
                    except BaseException:
                        intent["state"] = "MOVE_UNCERTAIN"
                        _write_manifest(manifest, {
                            **manifest_binding,
                            "operation_id": fresh.plan_token, "phase": "FILE_UNCERTAIN",
                            "work_key": fresh.work_key, "work_id": fresh.work_id,
                            "plan_token": fresh.plan_token, "catalog_before": catalog_before,
                            "catalog_backup": catalog_backup,
                            "catalog_expected_fingerprint": fresh.catalog_fingerprint,
                            "watchlist_before": before_watchlist,
                            "watchlist_before_path": watchlist_before_path,
                            "watchlist_expected_revision": fresh.watchlist_revision,
                            "watchlist_expected_after": None, "watchlist_after": None,
                            "intents": intents,
                        })
                        raise
                    _hook(failure_hook, "after_move_before_verified")
                    intent["state"] = "VERIFIED"
                    _write_manifest(manifest, {
                        **manifest_binding,
                        "operation_id": fresh.plan_token, "phase": "FILE_VERIFIED",
                        "work_key": fresh.work_key, "work_id": fresh.work_id,
                        "plan_token": fresh.plan_token, "catalog_before": catalog_before,
                        "catalog_backup": catalog_backup,
                        "catalog_expected_fingerprint": fresh.catalog_fingerprint,
                        "watchlist_before": before_watchlist,
                        "watchlist_before_path": watchlist_before_path,
                        "watchlist_expected_revision": fresh.watchlist_revision,
                        "watchlist_expected_after": None, "watchlist_after": None,
                        "intents": intents,
                    })
                    moved.append((source, destination))
                    _hook(failure_hook, "after_each_move")
                _write_manifest(manifest, {
                    **manifest_binding,
                    "operation_id": fresh.plan_token, "phase": "FILES_MOVED",
                    "work_key": fresh.work_key, "work_id": fresh.work_id,
                    "plan_token": fresh.plan_token, "catalog_before": catalog_before,
                    "catalog_backup": catalog_backup,
                    "catalog_expected_fingerprint": fresh.catalog_fingerprint,
                    "watchlist_before": before_watchlist,
                    "watchlist_before_path": watchlist_before_path,
                    "watchlist_expected_after": None,
                    "watchlist_expected_revision": fresh.watchlist_revision,
                    "watchlist_after": None, "intents": intents,
                })
                _hook(failure_hook, "after_files_moved")
                if fresh.work_id is not None:
                    _hook(failure_hook, "before_catalog_commit")
                    CatalogService(catalog).delete_work_records(
                        fresh.work_id,
                        expected_fingerprint=fresh.catalog_fingerprint,
                        expected_non_target_fingerprint=catalog_non_target_before,
                    )
                    _hook(failure_hook, "catalog_commit_returned")
                    catalog_committed = True
                    _write_manifest(manifest, {
                        **manifest_binding,
                        "operation_id": fresh.plan_token, "phase": "CATALOG_COMMITTED",
                        "work_key": fresh.work_key, "work_id": fresh.work_id,
                        "plan_token": fresh.plan_token, "catalog_before": catalog_before,
                        "catalog_backup": catalog_backup,
                        "catalog_expected_fingerprint": fresh.catalog_fingerprint,
                        "watchlist_before": before_watchlist,
                        "watchlist_expected_revision": fresh.watchlist_revision,
                        "watchlist_after": None, "intents": intents,
                    })
                    _hook(failure_hook, "after_catalog_commit")
                if watchlist.exists():
                    _hook(failure_hook, "before_watchlist_replace")
                    WatchlistService(watchlist).delete_work_targets_and_archive_state(
                        fresh.work_key, expected_revision=fresh.watchlist_revision
                    )
                    _hook(failure_hook, "watchlist_replace_returned")
                    watchlist_committed = True
                    watchlist_after = _watchlist_fact(watchlist)
                    after_copy = operation_dir / "watchlist-after.yaml"
                    _write_snapshot(after_copy, watchlist.read_bytes())
                    watchlist_after_path = str(after_copy)
                else:
                    watchlist_after = None
                _hook(failure_hook, "after_watchlist_replace")
                _write_manifest(manifest, {
                    **manifest_binding,
                    "operation_id": fresh.plan_token, "phase": "DONE",
                    "work_key": fresh.work_key, "work_id": fresh.work_id,
                    "plan_token": fresh.plan_token, "catalog_before": catalog_before,
                    "catalog_backup": catalog_backup,
                    "catalog_expected_fingerprint": fresh.catalog_fingerprint,
                    "watchlist_before": before_watchlist,
                    "watchlist_before_path": watchlist_before_path,
                    "watchlist_expected_revision": fresh.watchlist_revision,
                    "watchlist_after": watchlist_after,
                    "watchlist_after_path": watchlist_after_path,
                    "watchlist_expected_after": watchlist_after,
                    "watchlist_non_target_before": watchlist_non_target_before,
                    "watchlist_non_target_after": _watchlist_non_target_snapshot(watchlist, fresh.work_key),
                    "intents": intents,
                })
                _verify_final_state(fresh, intents, catalog, watchlist, watchlist_non_target_before, watchlist_after, catalog_non_target_before)
                if active_reserved:
                    _release_active(active_marker)
                    active_reserved = False
                return WorkDeletionApplyResult(fresh.plan_token, "DONE", str(manifest), fresh.plan_token)
            except BaseException as exc:
                if manifest is None or operation_dir is None:
                    raise
                if not operation_reserved:
                    if active_reserved:
                        _release_active(active_marker)
                        active_reserved = False
                    raise WorkDeletionApplyError("work deletion operation directory collision") from exc
                if not operation_dir.exists():
                    if active_reserved:
                        _release_active(active_marker)
                        active_reserved = False
                    raise WorkDeletionApplyError("work deletion operation directory could not be reserved") from exc
                catalog_state = _catalog_commit_state(catalog, fresh.work_id, fresh.catalog_fingerprint) if fresh.work_id is not None else "unchanged"
                commit_uncertain = catalog_state == "other"
                if catalog_state == "deleted":
                    catalog_committed = True
                watchlist_state = (
                    _watchlist_commit_state(watchlist, fresh.work_key, before_watchlist, watchlist_non_target_before)
                    if fresh.watchlist_keys or fresh.archived else "unchanged"
                )
                if watchlist_state == "other":
                    commit_uncertain = True
                elif watchlist_state == "deleted":
                    watchlist_committed = True
                if commit_uncertain or catalog_committed or watchlist_committed:
                    _write_manifest(manifest, {
                        "operation_id": fresh.plan_token, "phase": "RECOVERY_REQUIRED",
                        "work_key": fresh.work_key, "work_id": fresh.work_id,
                        "plan_token": fresh.plan_token, "error": repr(exc),
                        "catalog_path": str(catalog.resolve(strict=False)),
                        "watchlist_path": str(watchlist.resolve(strict=False)),
                        "operation_namespace": namespace, "active_marker": str(active_marker),
                        "catalog_before": catalog_before,
                        "catalog_backup": catalog_backup,
                        "catalog_expected_fingerprint": fresh.catalog_fingerprint,
                        "watchlist_before": before_watchlist,
                        "watchlist_before_path": watchlist_before_path,
                        "watchlist_expected_revision": fresh.watchlist_revision,
                        "watchlist_after": _watchlist_fact(watchlist),
                        "watchlist_after_path": watchlist_after_path,
                        "watchlist_expected_after": watchlist_after,
                        "intents": intents,
                    })
                    raise WorkDeletionApplyError("work deletion requires recovery") from exc
                try:
                    _restore_intents(intents)
                except BaseException as restore_error:
                    _write_manifest(manifest, {
                        "operation_id": fresh.plan_token, "phase": "RECOVERY_REQUIRED",
                        "work_key": fresh.work_key, "work_id": fresh.work_id,
                        "plan_token": fresh.plan_token, "error": repr(exc),
                        "catalog_path": str(catalog.resolve(strict=False)),
                        "watchlist_path": str(watchlist.resolve(strict=False)),
                        "operation_namespace": namespace, "active_marker": str(active_marker),
                        "restore_error": repr(restore_error), "catalog_before": catalog_before,
                        "catalog_backup": catalog_backup,
                        "catalog_expected_fingerprint": fresh.catalog_fingerprint,
                        "watchlist_before": before_watchlist,
                        "watchlist_before_path": watchlist_before_path,
                        "watchlist_expected_revision": fresh.watchlist_revision,
                        "watchlist_after": _watchlist_fact(watchlist),
                        "watchlist_after_path": watchlist_after_path,
                        "watchlist_expected_after": watchlist_after,
                        "intents": intents,
                    })
                    raise WorkDeletionApplyError("work deletion requires recovery") from restore_error
                _write_manifest(manifest, {
                    "operation_id": fresh.plan_token, "phase": "ROLLED_BACK",
                    "work_key": fresh.work_key, "work_id": fresh.work_id,
                    "plan_token": fresh.plan_token, "error": repr(exc),
                    "catalog_path": str(catalog.resolve(strict=False)),
                    "watchlist_path": str(watchlist.resolve(strict=False)),
                    "operation_namespace": namespace, "active_marker": str(active_marker),
                    "catalog_before": catalog_before,
                    "catalog_backup": catalog_backup,
                    "catalog_expected_fingerprint": fresh.catalog_fingerprint,
                    "watchlist_before": before_watchlist,
                    "watchlist_before_path": watchlist_before_path,
                    "watchlist_expected_revision": fresh.watchlist_revision,
                    "watchlist_after": _watchlist_fact(watchlist),
                    "watchlist_after_path": watchlist_after_path,
                    "watchlist_expected_after": watchlist_after,
                    "intents": intents,
                })
                if active_reserved:
                    _release_active(active_marker)
                    active_reserved = False
                raise WorkDeletionApplyError("work deletion rolled back") from exc

    def recover(
        self,
        catalog_path: str | Path,
        watchlist_path: str | Path,
        trash_root: str | Path,
        *,
        management_paths: Iterable[str | Path] | None = None,
        operation_id: str | None = None,
        dry_run: bool = False,
    ) -> WorkDeletionRecoveryResult:
        """Inspect or explicitly recover one durable deletion operation.

        Recovery never restores the Catalog wholesale. It classifies the
        durable Catalog/Watchlist/file state first, then either restores only
        verified pre-commit file moves or completes a verified post-commit
        Watchlist cutover. Ambiguous state remains gated.
        """

        catalog = Path(catalog_path)
        watchlist = Path(watchlist_path)
        trash = Path(trash_root)
        namespace = _namespace(catalog)
        gate_dir = catalog.resolve(strict=False).parent / ".work-deletion" / namespace
        active_marker = gate_dir / "active.json"
        manifest_path = _find_recovery_manifest(trash, active_marker, operation_id)
        if manifest_path is None:
            if active_marker.is_file():
                return WorkDeletionRecoveryResult(
                    operation_id=operation_id or "unknown",
                    status="RECOVERY_REQUIRED",
                    manifest_path=None,
                    details=("active reservation has no durable manifest; manual inspection required",),
                )
            raise WorkDeletionApplyError("no pending work deletion manifest")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError, TypeError) as exc:
            return WorkDeletionRecoveryResult(operation_id=operation_id or manifest_path.parent.name, status="RECOVERY_REQUIRED", manifest_path=str(manifest_path), details=(f"manifest unreadable: {exc}",))
        if not isinstance(manifest, dict):
            return WorkDeletionRecoveryResult(operation_id=operation_id or manifest_path.parent.name, status="RECOVERY_REQUIRED", manifest_path=str(manifest_path), details=("manifest is not an object",))
        missing_fields = _recovery_manifest_missing_fields(manifest)
        if missing_fields:
            return WorkDeletionRecoveryResult(
                operation_id=operation_id or manifest_path.parent.name,
                status="RECOVERY_REQUIRED", manifest_path=str(manifest_path),
                details=("manifest required fields missing: " + ", ".join(missing_fields),),
            )
        operation = str(manifest.get("operation_id") or manifest_path.parent.name)
        if operation_id is not None and operation != operation_id:
            raise WorkDeletionApplyError("requested recovery operation does not match manifest")
        if manifest_path.parent.resolve(strict=False).parent != trash.resolve(strict=False):
            raise WorkDeletionApplyError("recovery manifest is outside the supplied trash root")
        expected_catalog = str(catalog.resolve(strict=False))
        expected_watchlist = str(watchlist.resolve(strict=False))
        expected_active_marker = str(active_marker.resolve(strict=False))
        if (
            manifest.get("catalog_path") != expected_catalog
            or manifest.get("watchlist_path") != expected_watchlist
            or manifest.get("operation_namespace") != namespace
            or manifest.get("active_marker") != expected_active_marker
        ):
            raise WorkDeletionApplyError("recovery manifest is bound to another Catalog namespace")
        work_key = str(manifest.get("work_key", ""))
        work_id = None if manifest.get("work_id") is None else int(manifest["work_id"])
        management = tuple(Path(value) for value in (management_paths or ()))
        with ExitStack() as locks:
            # Dry-run is a read-only diagnosis and must not create admission,
            # Catalog, Watchlist, or namespace lock files. Apply acquires the
            # full ordered lock set and re-reads the manifest below.
            if not dry_run:
                locks.enter_context(CatalogJobLock(gate_dir / "admission"))
                locks.enter_context(CatalogService(catalog).job_lock())
                locks.enter_context(WatchlistService(watchlist).edit_lock())
            try:
                locked_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, ValueError, TypeError) as exc:
                raise WorkDeletionApplyError("manifest changed or became unreadable before recovery") from exc
            if not isinstance(locked_manifest, dict) or str(locked_manifest.get("operation_id", operation)) != operation:
                raise WorkDeletionApplyError("manifest operation identity changed before recovery")
            missing_fields = _recovery_manifest_missing_fields(locked_manifest)
            if missing_fields:
                return WorkDeletionRecoveryResult(
                    operation, "RECOVERY_REQUIRED", str(manifest_path),
                    ("manifest required fields missing: " + ", ".join(missing_fields),),
                )
            if (
                locked_manifest.get("catalog_path") != expected_catalog
                or locked_manifest.get("watchlist_path") != expected_watchlist
                or locked_manifest.get("operation_namespace") != namespace
                or locked_manifest.get("active_marker") != expected_active_marker
            ):
                raise WorkDeletionApplyError("manifest binding changed before recovery")
            manifest = locked_manifest
            work_key = str(manifest.get("work_key", ""))
            work_id = None if manifest.get("work_id") is None else int(manifest["work_id"])
            if active_marker.is_file():
                try:
                    marker = json.loads(active_marker.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, ValueError, TypeError) as exc:
                    raise WorkDeletionApplyError("active deletion marker is malformed") from exc
                marker_manifest = Path(str(marker.get("manifest", ""))) if isinstance(marker, dict) else Path()
                if not isinstance(marker, dict) or str(marker.get("operation_id", operation)) != operation or marker_manifest.resolve(strict=False) != manifest_path.resolve(strict=False):
                    raise WorkDeletionApplyError("active deletion marker does not match the recovery manifest")
            registry_blockers, bound = self._check_management_registry(catalog, namespace, tuple(str(path) for path in management))
            if registry_blockers:
                return WorkDeletionRecoveryResult(operation, "RECOVERY_REQUIRED", str(manifest_path), tuple(registry_blockers))
            _states, _fingerprints, management_blockers = self._read_management(bound, work_key, catalog)
            if management_blockers:
                return WorkDeletionRecoveryResult(operation, "RECOVERY_REQUIRED", str(manifest_path), tuple(management_blockers))
            operation_dir = manifest_path.parent
            intents = manifest.get("intents", [])
            if not isinstance(intents, list) or any(not isinstance(intent, dict) for intent in intents):
                return WorkDeletionRecoveryResult(operation, "RECOVERY_REQUIRED", str(manifest_path), ("manifest intents are malformed",))
            if not dry_run and _sqlite_hot_journal(catalog):
                try:
                    _recover_sqlite_hot_journal(catalog)
                except (OSError, sqlite3.Error) as exc:
                    return WorkDeletionRecoveryResult(
                        operation, "RECOVERY_REQUIRED", str(manifest_path),
                        (f"catalog hot-journal recovery failed: {exc}",),
                    )
            file_state = _recovery_file_state(intents)
            catalog_state = _recovery_catalog_state(catalog, manifest, operation_dir, work_id)
            watchlist_state = _recovery_watchlist_state(watchlist, manifest, operation_dir, work_key)
            states = (f"catalog={catalog_state}", f"watchlist={watchlist_state}", f"files={file_state}")
            phase = str(manifest.get("phase", "")).upper()
            if dry_run:
                if phase == "DONE" and catalog_state in {"deleted", "absent"} and watchlist_state in {"deleted", "absent"} and file_state == "staged":
                    status = "DONE"
                elif phase == "ROLLED_BACK" and catalog_state in {"before", "absent"} and watchlist_state in {"before", "absent"} and file_state == "before":
                    status = "ROLLED_BACK"
                elif catalog_state == "absent" and manifest.get("catalog_before") is None and watchlist_state == "before" and file_state in {"before", "staged", "mixed"}:
                    status = "ROLLBACK_READY"
                elif catalog_state in {"deleted", "absent"} and file_state == "staged" and watchlist_state in {"before", "deleted", "absent"}:
                    status = "ROLL_FORWARD_READY"
                elif catalog_state == "before" and file_state in {"before", "staged", "mixed"} and watchlist_state in {"before", "deleted", "absent"}:
                    status = "ROLLBACK_READY"
                else:
                    status = "RECOVERY_REQUIRED"
                return WorkDeletionRecoveryResult(operation, status, str(manifest_path), states)
            if phase == "DONE" and catalog_state in {"deleted", "absent"} and watchlist_state in {"deleted", "absent"} and file_state == "staged":
                _release_active(active_marker)
                return WorkDeletionRecoveryResult(operation, "DONE", str(manifest_path), states)
            if phase == "ROLLED_BACK" and catalog_state in {"before", "absent"} and watchlist_state in {"before", "absent"} and file_state == "before":
                _release_active(active_marker)
                return WorkDeletionRecoveryResult(operation, "ROLLED_BACK", str(manifest_path), states)
            if catalog_state == "before" and watchlist_state in {"before", "deleted", "absent"} and file_state in {"before", "staged", "mixed"}:
                if watchlist_state == "deleted":
                    _restore_watchlist_before(watchlist, manifest, operation_dir)
                if file_state in {"staged", "mixed"}:
                    _restore_intents(intents)
                if _recovery_file_state(intents) != "before" or _recovery_watchlist_state(watchlist, manifest, operation_dir, work_key) not in {"before", "absent"}:
                    raise WorkDeletionApplyError("recovery rollback could not verify the before state")
                manifest.update({"phase": "ROLLED_BACK", "recovery": {"action": "rollback", "states": states}})
                _write_manifest(manifest_path, manifest)
                _release_active(active_marker)
                return WorkDeletionRecoveryResult(operation, "ROLLED_BACK", str(manifest_path), states)
            if catalog_state == "absent" and manifest.get("catalog_before") is None:
                if watchlist_state == "before" and file_state in {"before", "staged", "mixed"}:
                    if file_state != "before":
                        _restore_intents(intents)
                    manifest.update({"phase": "ROLLED_BACK", "recovery": {"action": "rollback", "states": states}})
                    _write_manifest(manifest_path, manifest)
                    _release_active(active_marker)
                    return WorkDeletionRecoveryResult(operation, "ROLLED_BACK", str(manifest_path), states)
                if watchlist_state == "deleted" and file_state == "staged":
                    manifest.update({"phase": "DONE", "recovery": {"action": "roll-forward", "states": states}})
                    _write_manifest(manifest_path, manifest)
                    _release_active(active_marker)
                    return WorkDeletionRecoveryResult(operation, "DONE", str(manifest_path), states)
            if catalog_state == "deleted" and file_state == "staged" and watchlist_state in {"before", "deleted", "absent"}:
                if watchlist_state == "before":
                    expected_revision = str((manifest.get("watchlist_before") or {}).get("revision", ""))
                    if not expected_revision:
                        raise WorkDeletionApplyError("Watchlist before revision is missing")
                    WatchlistService(watchlist).delete_work_targets_and_archive_state(work_key, expected_revision=expected_revision)
                    if _recovery_watchlist_state(watchlist, manifest, operation_dir, work_key) != "deleted":
                        raise WorkDeletionApplyError("recovery Watchlist roll-forward verification failed")
                manifest.update({"phase": "DONE", "recovery": {"action": "roll-forward", "states": states}})
                _write_manifest(manifest_path, manifest)
                _release_active(active_marker)
                return WorkDeletionRecoveryResult(operation, "DONE", str(manifest_path), states)
            manifest.update({"phase": "RECOVERY_REQUIRED", "recovery": {"action": "manual", "states": states}})
            _write_manifest(manifest_path, manifest)
            return WorkDeletionRecoveryResult(operation, "RECOVERY_REQUIRED", str(manifest_path), states)

    def bind_management_stores(
        self,
        catalog_path: str | Path,
        management_paths: Iterable[str | Path],
        *,
        expected_revision: str | None = None,
    ) -> dict[str, Any]:
        """Explicitly seal the complete, operator-declared management set.

        This bootstrap only reads the declared SQLite stores and atomically
        writes the Catalog-specific registry. It never discovers or silently
        adds an unlisted store.
        """

        catalog = Path(catalog_path)
        namespace = _namespace(catalog)
        registry = catalog.resolve(strict=False).parent / ".work-deletion" / namespace / "management-bindings.json"
        paths = tuple(sorted({str(Path(value).resolve(strict=False)) for value in management_paths}))
        if not paths:
            raise WorkDeletionApplyError("at least one management store must be explicitly declared")
        for raw_path in paths:
            path = Path(raw_path)
            if not path.is_file() or _sqlite_wal_present(path):
                raise WorkDeletionApplyError(f"management store is missing or has SQLite sidecars: {path}")
            try:
                with sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True) as connection:
                    table = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone()
                    columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(jobs)")}
            except sqlite3.Error as exc:
                raise WorkDeletionApplyError(f"management store cannot be read: {path}") from exc
            if table is None or not {"job_id", "state", "selected_keys_json"}.issubset(columns):
                raise WorkDeletionApplyError(f"management schema is unknown: {path}")
        with CatalogJobLock(catalog.parent / ".work-deletion" / namespace / "admission"):
            current = registry.read_bytes() if registry.is_file() else b""
            current_revision = hashlib.sha256(current).hexdigest() if current else None
            if expected_revision is not None and expected_revision != current_revision:
                raise WorkDeletionApplyError("management registry changed during bootstrap")
            if current:
                try:
                    existing = json.loads(current.decode("utf-8"))
                except (UnicodeDecodeError, ValueError, TypeError) as exc:
                    raise WorkDeletionApplyError("management registry is malformed") from exc
                if existing.get("catalog_path") != str(catalog.resolve(strict=False)):
                    raise WorkDeletionApplyError("management registry belongs to another Catalog")
                existing_paths = tuple(sorted(str(Path(value).resolve(strict=False)) for value in existing.get("management_paths", ())))
                if existing.get("sealed") is True:
                    if existing_paths != paths:
                        raise WorkDeletionApplyError("sealed management registry cannot be narrowed or replaced")
                    return {"path": str(registry), "revision": current_revision, "management_paths": list(paths), "sealed": True}
                if not set(existing_paths).issubset(paths):
                    raise WorkDeletionApplyError("unsealed management registry cannot be narrowed")
            value = {"catalog_path": str(catalog.resolve(strict=False)), "sealed": True, "management_paths": list(paths)}
            _write_registry(registry, value)
            raw = registry.read_bytes()
            return {"path": str(registry), "revision": hashlib.sha256(raw).hexdigest(), "management_paths": list(paths), "sealed": True}

    @staticmethod
    def _read_watchlist(path: Path):
        service = WatchlistService(path)
        snapshot = service.read_document()
        return (snapshot.targets, snapshot.archived_work_keys), snapshot.revision

    @staticmethod
    def _read_catalog(path: Path, work_key: str) -> dict[str, Any]:
        catalog = CatalogService(path)
        # Opening a WAL database, even read-only, may update SQLite's shared
        # memory read marks.  Preview must be byte/mtime immutable, so an
        # uncheckpointed sidecar is an explicit fail-closed condition.
        if _sqlite_wal_present(path):
            return {
                "work_id": None, "work_title": None, "site_keys": (),
                "fingerprint": _sha256_json(_sqlite_file_snapshot(path)),
                "artifacts": (), "all_artifacts": (), "graph_blockers": ("catalog_wal_present",),
                "item_ids": (), "source_ids": (), "source_target_ids": (), "crawl_run_ids": (),
                "artifact_ids": (), "quota_ids": (), "scope_present": False, "discovery_keys": (),
                "position_count": 0,
            }
        with catalog._read_only_connection() as connection:  # read-only contract, no initialization/write
            connection.execute("BEGIN")
            schema_blockers = _unknown_catalog_schema(connection)
            if schema_blockers:
                return {
                    "work_id": None, "work_title": None, "site_keys": (),
                    "fingerprint": _sha256_json(_sqlite_file_snapshot(path)),
                    "artifacts": (), "all_artifacts": (), "graph_blockers": schema_blockers,
                    "item_ids": (), "source_ids": (), "source_target_ids": (), "crawl_run_ids": (),
                    "artifact_ids": (), "quota_ids": (), "scope_present": False,
                    "discovery_keys": (), "position_count": 0,
                }
            rows = {table: tuple(connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()) for table in _TABLES}
            fingerprint = _sha256_json({table: [dict(row) for row in values] for table, values in rows.items()})
            # Keep the complete ordered snapshot for the token, but use ID
            # maps for ownership joins.  The previous nested ``next`` scans
            # made a large all_artifacts table quadratic without adding any
            # proof: every row is still checked against its direct owner.
            graph_blockers: list[str] = []

            def unique_index(table: str) -> dict[int, Any]:
                indexed: dict[int, Any] = {}
                for row in rows[table]:
                    row_id = int(row["id"])
                    if row_id in indexed:
                        graph_blockers.append(f"catalog_duplicate_id:{table}:{row_id}")
                        continue
                    indexed[row_id] = row
                return indexed

            work_by_id = unique_index("works")
            item_by_id = unique_index("items")
            source_by_id = unique_index("sources")
            target_by_id = unique_index("source_targets")
            run_by_id = unique_index("crawl_runs")
            work_matches = tuple(row for row in rows["works"] if str(row["work_key"]) == work_key)
            if len(work_matches) > 1:
                graph_blockers.append(f"catalog_duplicate_work_key:{work_key}")
            work_row = work_matches[0] if work_matches else None
            if work_row is None:
                return {"work_id": None, "work_title": None, "site_keys": (), "fingerprint": fingerprint, "artifacts": (), "all_artifacts": (), "graph_blockers": (), "item_ids": (), "source_ids": (), "source_target_ids": (), "crawl_run_ids": (), "artifact_ids": (), "quota_ids": (), "scope_present": False, "discovery_keys": (), "position_count": 0}
            work_id = int(work_row["id"])
            items = tuple(row for row in rows["items"] if int(row["work_id"]) == work_id)
            item_ids = {int(row["id"]) for row in items}
            sources = tuple(row for row in rows["sources"] if int(row["item_id"]) in item_ids)
            source_ids = {int(row["id"]) for row in sources}
            targets = tuple(row for row in rows["source_targets"] if int(row["source_id"]) in source_ids)
            target_ids = {int(row["id"]) for row in targets}
            runs = tuple(row for row in rows["crawl_runs"] if int(row["item_id"]) in item_ids or int(row["source_id"]) in source_ids or int(row["target_id"]) in target_ids)
            run_ids = {int(row["id"]) for row in runs}
            artifacts = tuple(row for row in rows["artifacts"] if int(row["item_id"]) in item_ids or (row["crawl_run_id"] is not None and int(row["crawl_run_id"]) in run_ids))
            artifact_ids = {int(row["id"]) for row in artifacts}
            quotas = tuple(row for row in rows["quota_resource_states"] if int(row["work_id"]) == work_id)
            scope = tuple(row for row in rows["acquisition_scope_sync"] if int(row["work_id"]) == work_id)
            evidence = tuple(row for row in rows["discovery_inventory_evidence"] if int(row["work_id"]) == work_id)
            keys = {str(row["discovery_key"]) for row in evidence}
            positions = tuple(row for row in rows["discovery_inventory_positions"] if str(row["discovery_key"]) in keys)
            for row in runs:
                source = source_by_id.get(int(row["source_id"]))
                target = target_by_id.get(int(row["target_id"]))
                if source is None or target is None or int(row["item_id"]) != int(source["item_id"]) or int(target["source_id"]) != int(row["source_id"]):
                    graph_blockers.append(f"run_graph_mismatch:{row['id']}")
            for row in artifacts:
                if row["crawl_run_id"] is not None:
                    run = run_by_id.get(int(row["crawl_run_id"]))
                    if run is None or int(run["item_id"]) != int(row["item_id"]):
                        graph_blockers.append(f"artifact_graph_mismatch:{row['id']}")
            fk = connection.execute("PRAGMA foreign_key_check").fetchone()
            if fk is not None:
                graph_blockers.append("foreign_key_check_failed")
            all_artifacts = tuple(
                (
                    row,
                    item := item_by_id.get(int(row["item_id"])),
                    work_by_id.get(int(item["work_id"])) if item is not None else None,
                )
                for row in rows["artifacts"]
            )
        return {
            "work_id": work_id, "work_title": str(work_row["title"]) if work_row["title"] is not None else None,
            "site_keys": tuple(sorted((str(row["site"]), str(row["external_id"])) for row in sources)),
            "fingerprint": fingerprint, "artifacts": artifacts,
            "all_artifacts": all_artifacts, "graph_blockers": tuple(graph_blockers),
            "item_ids": tuple(sorted(item_ids)), "source_ids": tuple(sorted(source_ids)),
            "source_target_ids": tuple(sorted(target_ids)), "crawl_run_ids": tuple(sorted(run_ids)),
            "artifact_ids": tuple(sorted(artifact_ids)), "quota_ids": tuple(sorted(int(row["id"]) for row in quotas)),
            "scope_present": bool(scope), "discovery_keys": tuple(sorted(keys)), "position_count": len(positions),
        }

    @staticmethod
    def _read_deletion_gate(catalog: Path, namespace: str) -> tuple[str, tuple[str, ...]]:
        """Read recovery/admission markers without creating the namespace."""

        gate_dir = catalog.resolve(strict=False).parent / ".work-deletion" / namespace
        if not gate_dir.exists():
            return "none", ()
        fingerprints: list[tuple[str, str, int]] = []
        blockers: list[str] = []
        try:
            entries = sorted(
                path for path in gate_dir.iterdir()
                if path.is_file()
                and path.name != "management-bindings.json"
                and path.name != "operations.json"
                and not path.name.endswith(".job.lock")
            )
        except OSError:
            return "unreadable", ("deletion_gate_unreadable",)
        operations = gate_dir / "operations.json"
        if operations.is_file():
            try:
                raw_operations = operations.read_bytes()
                value = json.loads(raw_operations.decode("utf-8"))
                if not isinstance(value, dict) or any(
                    not isinstance(key, str) or not isinstance(ref, dict) or not isinstance(ref.get("manifest"), str)
                    for key, ref in value.items()
                ):
                    raise ValueError("invalid operation index")
                fingerprints.append((operations.name, hashlib.sha256(raw_operations).hexdigest(), operations.stat().st_mtime_ns))
            except (OSError, UnicodeDecodeError, ValueError, TypeError):
                blockers.append("deletion_gate_malformed")
        for entry in entries:
            try:
                raw = entry.read_bytes()
                fingerprints.append((entry.name, hashlib.sha256(raw).hexdigest(), entry.stat().st_mtime_ns))
                value = json.loads(raw.decode("utf-8"))
            except (OSError, UnicodeDecodeError, ValueError, TypeError):
                blockers.append("deletion_gate_malformed")
                continue
            if not isinstance(value, dict):
                blockers.append("deletion_gate_malformed")
                continue
            phase = str(value.get("phase", "")).casefold()
            if entry.name in {"active.json", "pending.json"}:
                # A marker is a live reservation until explicit recovery has
                # verified the terminal manifest and removed it.  Never trust
                # a forged/missing phase to clear the runtime gate.
                blockers.append("deletion_recovery_required" if phase in {"recovery", "recovering", "failed", "interrupted"} else "deletion_in_progress")
            elif entry.name == "manifest.json" or phase not in {"done", "rolled_back", "none"}:
                blockers.append("deletion_recovery_required" if phase in {"recovery", "recovering", "failed", "interrupted"} else "deletion_in_progress")
        return _sha256_json(fingerprints), tuple(dict.fromkeys(blockers))

    @staticmethod
    def _check_management_registry(catalog: Path, namespace: str, management: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
        registry = catalog.resolve(strict=False).parent / ".work-deletion" / namespace / "management-bindings.json"
        if not registry.is_file():
            return ("management_store_unbound",), ()
        try:
            value = json.loads(registry.read_text(encoding="utf-8"))
            if value.get("catalog_path") != str(catalog.resolve(strict=False)) or value.get("sealed") is not True:
                return ("management_store_unbound",), ()
            paths = tuple(sorted(str(Path(item).resolve(strict=False)) for item in value.get("management_paths", ())))
            if not paths or any(not Path(item).is_absolute() for item in paths):
                return ("management_store_unbound",), ()
        except (OSError, ValueError, TypeError):
            return ("management_store_unbound",), ()
        # A caller may not narrow a sealed registry: doing so would make a
        # queued job in another bound store invisible to the proof.
        if management and set(management) != set(paths):
            return ("management_store_binding_mismatch",), paths
        return (), paths

    @staticmethod
    def _read_management(paths: tuple[str, ...], work_key: str, catalog_path: Path):
        # Jobs can write anywhere in the same Catalog, so pending/live jobs
        # remain Catalog-wide blockers. Completed history is not write intent.
        del work_key
        states: list[tuple[str, str, str]] = []
        fingerprints: list[tuple[str, str]] = []
        blockers: list[str] = []
        expected_catalog = str(catalog_path.resolve(strict=False))
        for raw_path in paths:
            path = Path(raw_path)
            if not path.is_file():
                blockers.append(f"management_store_missing:{path}")
                continue
            if _sqlite_wal_present(path):
                blockers.append(f"management_wal_present:{path}")
                continue
            try:
                with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as connection:
                    connection.row_factory = sqlite3.Row
                    table = connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'"
                    ).fetchone()
                    if table is None:
                        blockers.append(f"management_schema_unknown:{path}")
                        continue
                    columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(jobs)")}
                    if not {"job_id", "state", "selected_keys_json"}.issubset(columns):
                        blockers.append(f"management_schema_unknown:{path}")
                        continue
                    selected = [name for name in (
                        "job_id", "state", "request_json", "worker_pid", "worker_start_token", "started_at",
                    ) if name in columns]
                    finished = sorted(_FINISHED_JOB_STATES)
                    placeholders = ",".join("?" for _ in finished)
                    rows = connection.execute(
                        "SELECT " + ", ".join(selected)
                        + f" FROM jobs WHERE state IS NULL OR lower(state) NOT IN ({placeholders}) ORDER BY job_id",
                        finished,
                    ).fetchall()
                logical_rows: list[dict[str, Any]] = []
                for row in rows:
                    data = dict(row)
                    job_id = str(data["job_id"])
                    state = str(data["state"]).casefold()
                    # Preserve the Python state authority even if a custom
                    # SQLite lower() does not implement full Unicode casefold.
                    if state in _FINISHED_JOB_STATES:
                        continue
                    startup_fields = ("worker_pid", "worker_start_token", "started_at")
                    if (state == "queued" and all(name in data for name in startup_fields)
                            and all(data[name] is None for name in startup_fields)):
                        # This is only a persisted, never-started reservation.
                        # It cannot write until worker admission/start gates
                        # and Catalog-lock checks allow execution. Do not
                        # cancel or mutate it, and do not stale the Plan.
                        continue
                    try:
                        request = json.loads(data.get("request_json") or "null")
                    except (TypeError, ValueError):
                        request = None
                    request_catalog = (
                        str(Path(str(request["catalog_path"])).resolve(strict=False))
                        if isinstance(request, dict) and request.get("catalog_path") else None
                    )
                    if request_catalog is not None and request_catalog != expected_catalog:
                        continue
                    if state == "interrupted":
                        worker_state, proof = _interrupted_worker_state(path.parent / "logs" / job_id, data)
                        if worker_state == "exited":
                            continue
                        data["worker_observation"] = proof
                        blockers.append(f"management_worker_{worker_state}:{job_id}")
                    elif state in _ACTIVE_JOB_STATES:
                        # Queued jobs do not have a worker identity yet.
                        blockers.append(f"active_job:{job_id}:{state}")
                    else:
                        blockers.append(f"management_state_unknown:{job_id}:{state}")
                    if request_catalog is None:
                        blockers.append(f"management_catalog_unknown:{job_id}")
                    logical_rows.append(data)
                    states.append((str(path), job_id, state))
                fingerprints.append((str(path), _sha256_json({"schema": sorted(columns), "jobs": logical_rows})))
            except (OSError, sqlite3.Error, ValueError) as exc:
                blockers.append(f"management_read_failed:{path}:{exc}")
        return tuple(sorted(states)), tuple(sorted(fingerprints)), tuple(blockers)

    @classmethod
    def _inspect_artifacts(
        cls,
        target_rows,
        all_rows,
        catalog_parent,
        library_root,
        status_root,
        trash_root,
        blockers,
        warnings,
        target_work_id,
        *,
        library_index=(),
        library_scan_failed=False,
        status_index=None,
        status_scan_failed=False,
        progress=None,
        cancel=None,
        started=None,
    ):
        for label, root in (("library", library_root), ("status", status_root), ("trash", trash_root)):
            if _raw_path_unsafe(str(root), catalog_parent):
                blockers.append(f"unsafe_{label}_root")
        if _paths_overlap(library_root, trash_root) or _paths_overlap(status_root, trash_root):
            blockers.append("unsafe_trash_root")
        if not _same_volume(library_root, trash_root) or not _same_volume(status_root, trash_root):
            blockers.append("cross_volume_root")
        if status_scan_failed:
            blockers.append("status_scan_failed")
        artifact_paths: dict[str, list[tuple[int, int]]] = {}
        file_facts: dict[str, dict[str, Any] | None] = {}
        status_facts_cache: dict[str, dict[str, Any] | None] = {}
        for row, _item, _work in all_rows:
            locator = row["locator"]
            if not locator:
                continue
            path = cls._canonical_path(locator, catalog_parent)
            artifact_paths.setdefault(os.path.normcase(str(path)), []).append((int(row["id"]), int(_work["id"]) if _work else -1))
        tracked_names = {Path(str(row["locator"])).name.casefold() for row in target_rows if row["locator"]}
        if library_index:
            tracked_paths = {
                os.path.normcase(str(cls._canonical_path(str(locator_row["locator"]), catalog_parent)))
                for locator_row, _locator_item, _locator_work in all_rows
                if locator_row["locator"]
            }
            for candidate in library_index:
                if candidate.name.casefold() in tracked_names and os.path.normcase(str(candidate.resolve(strict=False))) not in tracked_paths:
                    blockers.append(f"untracked_archive_collision:{candidate}")
        if library_scan_failed:
            blockers.append("library_scan_failed")
        result: list[ArtifactPreview] = []
        seen_target_paths: dict[str, tuple[int, str, int, int]] = {}
        total = len(target_rows)
        for completed, row in enumerate(target_rows, 1):
            if started is not None:
                _preview_checkpoint(progress, cancel, "artifacts", completed - 1, total, started)
            artifact_id = int(row["id"])
            kind = str(row["kind"])
            fmt = str(row["format"])
            state = str(row["state"])
            locator = row["locator"]
            row_blockers: list[str] = []
            source_path: Path | None = None
            destination: Path | None = None
            actual_size: int | None = None
            actual_hash: str | None = None
            statuses: tuple[str, ...] = ()
            status_facts: tuple[tuple[str, str, int, str, int, int], ...] = ()
            source_device: int | None = None
            source_inode: int | None = None
            duplicate_reference = False
            if state == "present":
                if not locator or str(row["storage_backend"]).casefold() != "filesystem" or fmt.casefold() != "zip" or kind.casefold() != "archive":
                    row_blockers.append(f"unsupported_present_artifact:{artifact_id}")
                else:
                    if _raw_path_unsafe(str(locator), catalog_parent):
                        row_blockers.append(f"unsafe_artifact_path:{artifact_id}")
                    source_path = cls._canonical_path(str(locator), catalog_parent)
                    path_key = os.path.normcase(str(source_path))
                    if path_key in seen_target_paths:
                        previous_size, previous_hash, previous_owner, previous_id = seen_target_paths[path_key]
                        exact_duplicate = (
                            previous_size == int(row["byte_size"])
                            and previous_hash.casefold() == str(row["sha256"]).casefold()
                            and previous_owner == target_work_id
                        )
                        duplicate_reference = True
                        if exact_duplicate:
                            warnings.append(f"artifact_duplicate_reference:{artifact_id}:primary:{previous_id}")
                        else:
                            blockers.append(f"artifact_duplicate_conflict:{artifact_id}:primary:{previous_id}")
                    else:
                        seen_target_paths[path_key] = (int(row["byte_size"]), str(row["sha256"]), target_work_id or -1, artifact_id)
                    if not _is_within(source_path, library_root) or source_path.is_symlink():
                        row_blockers.append(f"unsafe_artifact_path:{artifact_id}")
                    if not source_path.is_file():
                        row_blockers.append(f"artifact_present_missing:{artifact_id}")
                    else:
                        fact_key = os.path.normcase(str(source_path))
                        if fact_key not in file_facts:
                            file_facts[fact_key] = _stable_file_fact(source_path, cancel=cancel)
                        source_fact = file_facts[fact_key]
                        if source_fact is None or source_fact.get("error"):
                            row_blockers.append(f"artifact_unreadable:{artifact_id}")
                        else:
                            actual_size = int(source_fact["size"])
                            actual_hash = str(source_fact["sha256"])
                            source_device = source_fact.get("device")
                            source_inode = source_fact.get("inode")
                        if (source_fact is None or not source_fact.get("stable", False)
                                or not _fact_version_matches(source_path, source_fact)):
                            row_blockers.append(f"artifact_changed_during_hash:{artifact_id}")
                        if source_device is None or source_inode is None:
                            row_blockers.append(f"artifact_strong_id_unavailable:{artifact_id}")
                        if actual_size is not None and actual_size != int(row["byte_size"]):
                            row_blockers.append(f"artifact_size_mismatch:{artifact_id}")
                        if actual_hash is not None and actual_hash.casefold() != str(row["sha256"]).casefold():
                            row_blockers.append(f"artifact_hash_mismatch:{artifact_id}")
                        if _hardlink_or_reparse(source_path):
                            row_blockers.append(f"artifact_alias:{artifact_id}")
                        if artifact_paths.get(os.path.normcase(str(source_path)), []) and any(owner != target_work_id for _aid, owner in artifact_paths[os.path.normcase(str(source_path))]):
                            row_blockers.append(f"artifact_shared_path:{artifact_id}")
                        statuses, status_facts = cls._status_paths(
                            source_path, status_root, trash_root, artifact_id, row_blockers, warnings,
                            status_index=status_index, archive_hash=actual_hash, fact_cache=status_facts_cache,
                            cancel=cancel, library_root=library_root,
                        )
                    if (_paths_overlap(source_path, trash_root)
                            or _paths_overlap(library_root, trash_root)
                            or _paths_overlap(status_root, trash_root)):
                        row_blockers.append(f"unsafe_trash_root:{artifact_id}")
                    if not _same_volume(source_path, trash_root):
                        row_blockers.append(f"cross_volume_artifact:{artifact_id}")
                    try:
                        capacity_root = _existing_ancestor(trash_root)
                        if capacity_root is None:
                            raise OSError("trash root has no accessible existing ancestor")
                        if shutil.disk_usage(capacity_root).free < int(row["byte_size"]):
                            row_blockers.append(f"insufficient_trash_space:{artifact_id}")
                    except OSError:
                        row_blockers.append(f"trash_space_unavailable:{artifact_id}")
                    if not row_blockers and not duplicate_reference:
                        destination = trash_root / "<operation-id>" / library_root.name / source_path.relative_to(library_root)
            elif state in {"missing", "deleted"}:
                # A Catalog state is not authority to ignore a physical
                # locator.  An interrupted/manual cleanup can leave the ZIP
                # (or its sidecar status files) behind; treating that row as
                # already absent would allow a later Batch registration to
                # collide with an undeclared file.  Inspect only the durable
                # locator recorded by the row -- never infer a filename.
                if locator:
                    if _raw_path_unsafe(str(locator), catalog_parent):
                        row_blockers.append(f"unsafe_artifact_path:{artifact_id}")
                    else:
                        source_path = cls._canonical_path(str(locator), catalog_parent)
                        if not _is_within(source_path, library_root):
                            row_blockers.append(f"unsafe_artifact_path:{artifact_id}")
                        elif source_path.exists():
                            row_blockers.append(f"artifact_{state}_but_present:{artifact_id}")
                        else:
                            statuses, status_facts = cls._status_paths(
                                source_path, status_root, trash_root, artifact_id, row_blockers, warnings,
                                status_index=status_index, fact_cache=status_facts_cache, cancel=cancel,
                                library_root=library_root,
                            )
                            if statuses:
                                row_blockers.append(f"artifact_{state}_status_present:{artifact_id}")
            elif state not in {"missing", "deleted"}:
                row_blockers.append(f"artifact_state_unknown:{artifact_id}")
            blockers.extend(row_blockers)
            status_destinations = tuple(
                str(trash_root / "<operation-id>" / status_root.name / Path(path).relative_to(status_root))
                for path in statuses
            ) if not duplicate_reference else ()
            if statuses and not duplicate_reference:
                status_facts = tuple(
                    (source, str(trash_root / "<operation-id>" / status_root.name / Path(source).relative_to(status_root)), size, digest, device, inode)
                    for source, _destination, size, digest, device, inode in status_facts
                )
            result.append(ArtifactPreview(
                artifact_id=artifact_id, item_id=int(row["item_id"]), crawl_run_id=None if row["crawl_run_id"] is None else int(row["crawl_run_id"]),
                kind=kind, format=fmt, state=state, storage_backend=str(row["storage_backend"]), locator=None if locator is None else str(locator),
                source_path=None if source_path is None else str(source_path), destination_path=None if destination is None else str(destination),
                status_paths=statuses, status_destination_paths=status_destinations,
                status_facts=status_facts,
                source_device=source_device, source_inode=source_inode,
                byte_size=int(row["byte_size"]), sha256=str(row["sha256"]), actual_byte_size=actual_size,
                actual_sha256=actual_hash,
                move_eligible=not row_blockers and state == "present" and not duplicate_reference,
                blockers=tuple(row_blockers),
            ))
            if started is not None:
                _preview_checkpoint(progress, cancel, "artifacts", completed, total, started)
        return tuple(result)

    @staticmethod
    def _status_paths(
        archive: Path,
        root: Path,
        trash_root: Path,
        artifact_id: int,
        blockers: list[str],
        warnings: list[str],
        *,
        library_root: Path,
        status_index=None,
        archive_hash=None,
        fact_cache=None,
        cancel=None,
    ) -> tuple[tuple[str, ...], tuple[tuple[str, str, int, str, int, int], ...]]:
        if not root.exists() and not status_index:
            return (), ()
        matches: list[str] = []
        facts: list[tuple[str, str, int, str, int, int]] = []
        try:
            try:
                expected_path = root / archive.relative_to(library_root).with_suffix(".json")
            except ValueError:
                reason = f"unsafe_artifact_path:{artifact_id}"
                if reason not in blockers:
                    blockers.append(reason)
                return (), ()
            if status_index is None:
                status_index = _build_status_index(
                    root, trash_root, archive_paths=(archive,), library_root=library_root, cancel=cancel
                )
            for record in status_index:
                if record.get("scan_error"):
                    blockers.append(str(record["scan_error"]))
                    continue
                if os.path.normcase(record["candidate_path"]) != os.path.normcase(str(expected_path)):
                    continue
                candidate = Path(record["path"])
                same_stem = record["stem"] == archive.stem.casefold()
                if record.get("unsafe"):
                    if same_stem:
                        blockers.append("status_path_unsafe")
                    continue
                if not record.get("file", False):
                    continue
                if record.get("error"):
                    if same_stem:
                        blockers.append(str(record["error"]))
                    continue
                value = record["value"]
                candidate_path = record.get("archive_path")
                if candidate_path == archive:
                    matches.append(str(candidate.resolve()))
                    fact_key = os.path.normcase(str(candidate))
                    if fact_cache is not None and fact_key not in fact_cache:
                        fact_cache[fact_key] = _stable_file_fact(candidate, cancel=cancel)
                    candidate_fact = fact_cache.get(fact_key) if fact_cache is not None else _stable_file_fact(candidate, cancel=cancel)
                    if candidate_fact is None or candidate_fact.get("error"):
                        blockers.append("status_unreadable")
                        continue
                    candidate_size = int(candidate_fact["size"])
                    candidate_hash = str(candidate_fact["sha256"])
                    candidate_device, candidate_inode = candidate_fact.get("device"), candidate_fact.get("inode")
                    if (not candidate_fact.get("stable", False)
                            or not _fact_version_matches(candidate, candidate_fact)
                            or not record.get("read_stable", False)
                            or record.get("read_version") != _fact_version(candidate_fact)
                            or record.get("read_sha256") != candidate_hash):
                        blockers.append("status_changed_during_hash")
                    if candidate_device is None or candidate_inode is None:
                        blockers.append("status_strong_id_unavailable")
                    for key in ("sha256", "archive_sha256"):
                        if key in value:
                            compared_archive_hash = archive_hash
                            if compared_archive_hash is None:
                                # Preserve the established missing-archive
                                # behavior: attempting to prove a status hash
                                # against an absent ZIP is an unknown scan,
                                # not a successful status fact.
                                compared_archive_hash = _sha256_file(
                                    archive, check=lambda: _raise_if_cancelled(cancel)
                                )
                            if str(value[key]).casefold() != str(compared_archive_hash).casefold():
                                blockers.append("status_hash_mismatch")
                    for key in ("artifact_id", "artifactId", "status_artifact_id"):
                        if key in value and str(value[key]) != str(artifact_id):
                            blockers.append("status_identity_mismatch")
                    if candidate_device is not None and candidate_inode is not None:
                        facts.append((str(candidate.resolve()), str(trash_root / "<operation-id>" / root.name / candidate.relative_to(root)), candidate_size, candidate_hash, candidate_device, candidate_inode))
                elif same_stem:
                    blockers.append("status_mismatch")
        except OSError:
            blockers.append("status_scan_failed")
        if len(matches) > 1:
            blockers.append("status_alias")
        if not matches:
            # Stage 00 explicitly permits ZIP-only preservation when the
            # Catalog proof is complete; absence remains a visible warning.
            warnings.append("status_missing:" + str(archive))
            return (), ()
        return tuple(sorted(matches)), tuple(sorted(facts))

    @staticmethod
    def _canonical_path(raw: str, base: Path) -> Path:
        path = Path(raw)
        # Catalog and status writers persist `Path.as_posix()` without first
        # forcing an absolute path.  Existing archive maintenance resolves
        # those relative locators from the process CWD, so deletion must use
        # the same authority; rebasing them under the Catalog parent can point
        # at a different file for custom Catalog locations.
        del base
        return path.resolve(strict=False)


def _interrupted_worker_state(job_dir: Path, data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Read-only proof for unverified exits; never signal or reattach a PID."""

    proof: dict[str, Any] = {}
    try:
        job_id = data.get("job_id")
        if (not isinstance(job_id, str) or not job_id or job_id in {".", ".."}
                or any(character in job_id for character in ("/", "\\", ":"))):
            return "unverified", proof
        raw = (job_dir / "worker.identity").read_bytes()
        proof["identity_sha256"] = hashlib.sha256(raw).hexdigest()
        identity = json.loads(raw)
        if not isinstance(identity, dict):
            return "unverified", proof
        token = data.get("worker_start_token")
        if not isinstance(token, str) or not token or identity.get("token") != token:
            return "unverified", proof
        child_pid = identity.get("pid")
        launcher_pid = data.get("worker_pid")
        if any(type(pid) is not int or pid <= 0 for pid in (child_pid, launcher_pid)):
            return "unverified", proof
        proof["pid"] = child_pid
        child_alive = process_is_alive(child_pid)
        proof["alive"] = child_alive
        if child_alive:
            expected = identity.get("start_identity")
            observed = process_start_identity(child_pid)
            proof["start_identity"] = observed
            if not isinstance(expected, str) or not expected or observed is None:
                return "unverified", proof
            if observed == expected:
                return "live", proof
            # Same numeric PID now belongs to a different OS process.
        # On Windows the Popen launcher and child PID may differ. A dead
        # launcher alone never proves child exit; both observations are used.
        if launcher_pid != child_pid and process_is_alive(launcher_pid):
            return "unverified", proof
        return "exited", proof
    except (OSError, ValueError, TypeError, OverflowError):
        return "unverified", proof


def _namespace(catalog: Path) -> str:
    return "catalog-" + hashlib.sha256(str(catalog.resolve(strict=False)).casefold().encode("utf-8")).hexdigest()[:24]


def _path_identity(path: Path) -> str:
    return str(path.resolve(strict=False))


def _root_identities(*roots: Path) -> tuple[tuple[str, str, int | None], ...]:
    labels = ("library", "status", "trash")
    result: list[tuple[str, str, int | None]] = []
    for label, root in zip(labels, roots, strict=True):
        device: int | None = None
        current = root
        while True:
            try:
                device = int(current.stat().st_dev)
                break
            except OSError:
                parent = current.parent
                if parent == current:
                    break
                current = parent
        result.append((label, str(root.resolve(strict=False)), device))
    return tuple(result)


def _destination_snapshot(path: Path) -> tuple[str, tuple[str, ...]]:
    """Fingerprint an existing operation directory; never creates it."""

    if not path.exists():
        return "missing", ()
    if not path.is_dir() or path.is_symlink() or _hardlink_or_reparse(path):
        return "unsafe", ("destination_collision",)
    entries: list[tuple[str, int, str]] = []
    try:
        for child in sorted(path.rglob("*")):
            relative = str(child.relative_to(path))
            if child.is_symlink() or _hardlink_or_reparse(child):
                return "unsafe", ("destination_collision", "destination_alias")
            if child.is_file():
                entries.append((relative, child.stat().st_size, _sha256_file(child)))
            elif not child.is_dir():
                return "unsafe", ("destination_collision",)
    except OSError:
        return "unreadable", ("destination_collision",)
    return _sha256_json(entries), ("destination_collision",)


def _hook(callback: Any | None, checkpoint: str) -> None:
    if callback is not None:
        callback(checkpoint)


def _file_fact(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        stat_result = path.stat()
        return {
            "path": str(path.resolve(strict=False)), "size": stat_result.st_size,
            "sha256": _sha256_file(path), "device": getattr(stat_result, "st_dev", None),
            "inode": getattr(stat_result, "st_ino", None),
        }
    except OSError:
        return {"path": str(path.resolve(strict=False)), "error": "unreadable"}


def _stat_version(info: os.stat_result) -> tuple[Any, ...]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _fact_version(fact: dict[str, Any]) -> tuple[Any, ...]:
    return (fact.get("device"), fact.get("inode"), fact.get("size"), fact.get("mtime_ns"))


def _fact_version_matches(path: Path, fact: dict[str, Any]) -> bool:
    try:
        return _stat_version(path.stat()) == _fact_version(fact)
    except OSError:
        return False


def _stable_file_fact(path: Path, *, cancel: WorkDeletionCancelToken | Any | None = None) -> dict[str, Any] | None:
    """Hash once and reject a file that changes while it is being read."""

    try:
        before = path.stat()
        digest = _sha256_file(path, check=lambda: _raise_if_cancelled(cancel))
        after = path.stat()
    except OSError:
        return {"path": str(path.resolve(strict=False)), "error": "unreadable"}
    before_identity = (getattr(before, "st_dev", None), getattr(before, "st_ino", None))
    after_identity = (getattr(after, "st_dev", None), getattr(after, "st_ino", None))
    stable = (
        before_identity == after_identity
        and before.st_size == after.st_size
        and before.st_mtime_ns == after.st_mtime_ns
    )
    return {
        "path": str(path.resolve(strict=False)),
        "size": int(after.st_size),
        "sha256": digest,
        "device": getattr(after, "st_dev", None),
        "inode": getattr(after, "st_ino", None),
        "mtime_ns": int(after.st_mtime_ns),
        "stable": stable,
    }


def _build_library_index(root: Path, *, progress=None, cancel=None, started=None) -> tuple[tuple[Path, ...], bool]:
    if not root.is_dir():
        return (), False
    candidates: list[Path] = []
    failed = False
    try:
        for count, path in enumerate(root.rglob("*.zip"), 1):
            if started is not None:
                _preview_checkpoint(progress, cancel, "library_index", count, 0, started)
            if path.is_file():
                candidates.append(path)
    except OSError:
        failed = True
    if started is not None:
        _preview_checkpoint(progress, cancel, "library_index", len(candidates), len(candidates), started)
    return tuple(candidates), failed


def _build_status_index(
    root: Path, trash_root: Path, *, archive_paths: Iterable[Path], library_root: Path,
    progress=None, cancel=None, started=None,
) -> tuple[dict[str, Any], ...]:
    """Read only packaging-derived sidecars; never walk the status tree."""

    candidates: dict[str, Path] = {}
    for archive in archive_paths:
        _raise_if_cancelled(cancel)
        try:
            relative = archive.relative_to(library_root)
        except ValueError:
            # The Artifact inspector rejects out-of-library locators. Never
            # turn them into status paths outside the configured root.
            continue
        candidate = root / relative.with_suffix(".json")
        candidates.setdefault(os.path.normcase(str(candidate)), candidate)
    if not candidates:
        return ()
    try:
        if not stat.S_ISDIR(root.stat().st_mode):
            return ({"scan_error": "status_root_invalid"},)
    except FileNotFoundError:
        return ()
    except OSError:
        return ({"scan_error": "status_unreadable"},)
    records: list[dict[str, Any]] = []
    for completed, candidate in enumerate(candidates.values(), 1):
        if started is not None:
            _preview_checkpoint(progress, cancel, "status_read", completed - 1, len(candidates), started)
        else:
            _raise_if_cancelled(cancel)
        try:
            record = _read_status_record(candidate, root, trash_root)
        except OSError:
            record = {"candidate_path": str(candidate), "path": str(candidate),
                      "stem": candidate.stem.casefold(), "file": True, "error": "status_unreadable"}
        records.append(record)
        if started is not None:
            _preview_checkpoint(progress, cancel, "status_read", completed, len(candidates), started)
        else:
            _raise_if_cancelled(cancel)
    return tuple(records)


def _read_status_record(candidate: Path, root: Path, trash_root: Path) -> dict[str, Any]:
    record: dict[str, Any] = {
        "candidate_path": str(candidate),
        "path": str(candidate.resolve(strict=False)),
        "stem": candidate.stem.casefold(),
        "file": candidate.is_file(),
    }
    try:
        candidate.lstat()
    except FileNotFoundError:
        if record["file"]:
            record["error"] = "status_unreadable"
        return record
    if candidate.is_symlink() or _hardlink_or_reparse(candidate) or _raw_path_unsafe(str(candidate), root.parent) or not _same_volume(candidate, trash_root):
        record["unsafe"] = True
        return record
    if not record["file"]:
        record["unsafe"] = True
        return record
    try:
        before = candidate.stat()
        raw = candidate.read_bytes()
        after = candidate.stat()
        record["read_version"] = _stat_version(before)
        record["read_stable"] = _stat_version(before) == _stat_version(after)
        record["read_sha256"] = hashlib.sha256(raw).hexdigest()
        value = json.loads(raw.decode("utf-8"))
    except OSError:
        record["error"] = "status_unreadable"
        return record
    except (ValueError, UnicodeDecodeError):
        record["error"] = "status_malformed"
        return record
    if not isinstance(value, dict):
        record["error"] = "status_malformed"
        return record
    if "archive_path" not in value:
        record["error"] = "status_missing_archive_path"
        return record
    raw_archive_path = str(value["archive_path"])
    if _raw_path_unsafe(raw_archive_path, root.parent):
        record["unsafe"] = True
        return record
    record["value"] = value
    record["archive_path"] = WorkDeletionPreviewService._canonical_path(raw_archive_path, root.parent)
    return record

def _watchlist_fact(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    fact = _file_fact(path)
    if fact is not None:
        fact["revision"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return fact


def _fact_matches(path: Path, expected: Any) -> bool:
    if not isinstance(expected, dict):
        return False
    actual = _file_fact(path)
    if actual is None:
        return False
    for key in ("path", "size", "sha256", "device", "inode"):
        if key in expected and actual.get(key) != expected.get(key):
            return False
    return True


def _write_manifest(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    with temporary.open("wb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def _write_registry(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    with temporary.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def _record_operation_ref(namespace_dir: Path, operation_id: str, manifest: Path) -> None:
    path = namespace_dir / "operations.json"
    current: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                current = loaded
        except (OSError, UnicodeDecodeError, ValueError, TypeError) as exc:
            raise WorkDeletionApplyError("deletion operation registry is malformed") from exc
    current[operation_id] = {"manifest": str(manifest.resolve(strict=False))}
    _write_registry(path, current)


def register_management_store(catalog_path: str | Path, management_path: str | Path) -> dict[str, Any]:
    """Add one effective JobStore to the durable binding set under admission."""

    catalog = Path(catalog_path)
    store = str(Path(management_path).resolve(strict=False))
    namespace = _namespace(catalog)
    namespace_dir = catalog.resolve(strict=False).parent / ".work-deletion" / namespace
    registry = namespace_dir / "management-bindings.json"
    with CatalogJobLock(namespace_dir / "admission"):
        current: dict[str, Any] = {}
        if registry.is_file():
            try:
                loaded = json.loads(registry.read_text(encoding="utf-8"))
                if not isinstance(loaded, dict):
                    raise TypeError("registry is not an object")
                current = loaded
            except (OSError, UnicodeDecodeError, ValueError, TypeError) as exc:
                raise WorkDeletionApplyError("management registry is malformed") from exc
        if current and current.get("catalog_path") not in {None, str(catalog.resolve(strict=False))}:
            raise WorkDeletionApplyError("management registry belongs to another Catalog")
        paths = {str(Path(value).resolve(strict=False)) for value in current.get("management_paths", ())}
        was_sealed = current.get("sealed") is True and store in paths
        paths.add(store)
        # Runtime enqueue/start registration is additive and intentionally
        # unsealed when it discovers a new store.  Only the explicit bind API
        # can seal a complete declared set; a sealed registry remains sealed
        # only when this is an idempotent registration of an existing path.
        value = {
            "catalog_path": str(catalog.resolve(strict=False)),
            "sealed": was_sealed,
            "management_paths": sorted(paths),
        }
        if current != value:
            _write_registry(registry, value)
        return value


def _fsync_directory(path: Path) -> None:
    """Best-effort durability barrier for directory entries.

    POSIX permits fsync on a directory.  Windows and some filesystems reject
    opening a directory as a file; those platforms are intentionally treated
    as an unavailable durability primitive rather than as proof of power-loss
    safety.  Stage 03 must still exercise process-kill recovery separately.
    """

    try:
        directory = path.open("rb")
    except OSError:
        return
    with directory:
        try:
            os.fsync(directory.fileno())
        except OSError:
            pass


def _write_snapshot(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    _fsync_directory(path.parent)


def _reserve_active(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise WorkDeletionApplyError("deletion admission marker already exists")
    _write_snapshot(path, json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8"))


def _release_active(path: Path) -> None:
    if not path.exists():
        return
    path.unlink()
    _fsync_directory(path.parent)


def _restore_intents(intents: list[dict[str, Any]]) -> None:
    for intent in reversed(intents):
        source = Path(intent["source"])
        destination = Path(intent["destination"])
        source_exists = source.is_file()
        destination_exists = destination.is_file()
        if source_exists and not destination_exists:
            if source.stat().st_size != int(intent["size"]) or _sha256_file(source).casefold() != str(intent["sha256"]).casefold():
                raise WorkDeletionApplyError(f"rollback source mismatch: {source}")
            if intent.get("device") is not None and _file_identity(source) != (intent["device"], intent["inode"]):
                raise WorkDeletionApplyError(f"rollback source identity mismatch: {source}")
            continue
        if not source_exists and destination_exists:
            _move_no_clobber(destination, source, int(intent["size"]), str(intent["sha256"]), intent.get("device"), intent.get("inode"))
            intent["state"] = "RESTORED"
            continue
        if source_exists and destination_exists:
            raise WorkDeletionApplyError(f"rollback has both source and destination: {source}")
        if not source_exists and not destination_exists and intent.get("state") in {"VERIFIED", "MOVE_UNCERTAIN"}:
            raise WorkDeletionApplyError(f"rollback lost both source and destination: {source}")


def _watchlist_non_target_snapshot(path: Path, work_key: str) -> tuple[Any, ...] | None:
    if not path.is_file():
        return None
    try:
        document = WatchlistService(path).read_document()
    except (OSError, TypeError, ValueError):
        return ("unreadable",)
    return tuple(
        (
            target.key, target.work_key, target.site, target.url, target.label,
            target.enabled, repr(target.discovery_scope), target.archive_order,
            repr(target.archive_segments),
        )
        for target in document.targets if target.work_key != work_key
    ) + (tuple(key for key in document.archived_work_keys if key != work_key),)


def _catalog_non_target_fingerprint(path: Path, plan: WorkDeletionPlan) -> str | None:
    if plan.work_id is None or not path.is_file():
        return None
    target_ids = {
        "items": set(plan.item_ids), "sources": set(plan.source_ids),
        "source_targets": set(plan.source_target_ids), "crawl_runs": set(plan.crawl_run_ids),
        "artifacts": set(plan.artifact_ids), "quota_resource_states": set(plan.quota_resource_state_ids),
    }
    try:
        with CatalogService(path)._read_only_connection() as connection:
            payload: dict[str, list[dict[str, Any]]] = {}
            for table in _TABLES:
                rows = [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()]
                filtered: list[dict[str, Any]] = []
                for row in rows:
                    if table == "works" and int(row["id"]) == plan.work_id:
                        continue
                    if table in target_ids and int(row["id"]) in target_ids[table]:
                        continue
                    if table in {"acquisition_scope_sync", "discovery_inventory_evidence"} and int(row["work_id"]) == plan.work_id:
                        continue
                    if table == "discovery_inventory_positions" and str(row["discovery_key"]) in set(plan.discovery_keys):
                        continue
                    filtered.append(row)
                payload[table] = filtered
            return _sha256_json(payload)
    except (OSError, sqlite3.Error, KeyError, TypeError, ValueError):
        return "unreadable"


def _verify_final_state(
    plan: WorkDeletionPlan,
    intents: list[dict[str, Any]],
    catalog: Path,
    watchlist: Path,
    watchlist_non_target_before: tuple[Any, ...] | None,
    watchlist_after: dict[str, Any] | None,
    catalog_non_target_before: str | None,
) -> None:
    for intent in intents:
        source = Path(intent["source"])
        destination = Path(intent["destination"])
        if source.exists() or not destination.is_file():
            raise WorkDeletionApplyError(f"final move state is incomplete: {source}")
        if destination.stat().st_size != int(intent["size"]) or _sha256_file(destination).casefold() != str(intent["sha256"]).casefold():
            raise WorkDeletionApplyError(f"final move hash mismatch: {destination}")
        if intent.get("device") is None or _file_identity(destination) != (intent["device"], intent["inode"]):
            raise WorkDeletionApplyError(f"final move strong identity mismatch: {destination}")
    if plan.work_id is not None and _catalog_commit_state(catalog, plan.work_id, plan.catalog_fingerprint) != "deleted":
        raise WorkDeletionApplyError("final Catalog deletion verification failed")
    if catalog_non_target_before is not None and _catalog_non_target_fingerprint(catalog, plan) != catalog_non_target_before:
        raise WorkDeletionApplyError("non-target Catalog rows changed during deletion")
    # A Watchlist that existed before the cutover, or contained any target or
    # archived state for this work, is required to remain present after the
    # atomic replace.  Missing/unknown is not equivalent to an empty file.
    watchlist_required = (
        watchlist_non_target_before is not None
        or bool(plan.watchlist_keys)
        or plan.archived
    )
    if watchlist_required and not watchlist.exists():
        raise WorkDeletionApplyError("final Watchlist is missing")
    if watchlist.exists():
        document = WatchlistService(watchlist).read_document()
        if any(target.work_key == plan.work_key for target in document.targets) or plan.work_key in document.archived_work_keys:
            raise WorkDeletionApplyError("final Watchlist deletion verification failed")
        if _watchlist_non_target_snapshot(watchlist, plan.work_key) != watchlist_non_target_before:
            raise WorkDeletionApplyError("non-target Watchlist changed during deletion")
        if watchlist_after is None or _watchlist_fact(watchlist) != watchlist_after:
            raise WorkDeletionApplyError("final Watchlist bytes changed after verification")


def _move_intents(plan: WorkDeletionPlan) -> list[dict[str, Any]]:
    intents: list[dict[str, Any]] = []
    for artifact in plan.artifacts:
        if not artifact.move_eligible or artifact.source_path is None or artifact.destination_path is None:
            continue
        intents.append({
            "kind": "artifact", "artifact_id": artifact.artifact_id,
            "source": artifact.source_path, "destination": artifact.destination_path,
            "size": artifact.byte_size, "sha256": artifact.sha256,
            "device": artifact.source_device, "inode": artifact.source_inode,
        })
        for source, destination, size, digest, device, inode in artifact.status_facts:
            intents.append({
                "kind": "status", "artifact_id": artifact.artifact_id,
                "source": source, "destination": destination,
                "size": size, "sha256": digest, "device": device, "inode": inode,
            })
    return intents


def _move_no_clobber(source: Path, destination: Path, size: int | None, digest: str | None, device: int | None = None, inode: int | None = None) -> None:
    if os.name != "nt":
        raise WorkDeletionApplyError(
            "no-replace rename is not proven on this platform; deletion is Windows-only in this stage"
        )
    if not source.is_file() or source.is_symlink():
        raise WorkDeletionApplyError(f"move source is missing or unsafe: {source}")
    if destination.exists():
        raise WorkDeletionApplyError(f"move destination already exists: {destination}")
    if not _same_volume(source, destination):
        raise WorkDeletionApplyError(f"cross-volume move is forbidden: {source} -> {destination}")
    if size is not None and source.stat().st_size != size:
        raise WorkDeletionApplyError(f"move source size changed: {source}")
    if digest is not None and _sha256_file(source).casefold() != digest.casefold():
        raise WorkDeletionApplyError(f"move source hash changed: {source}")
    actual_device, actual_inode = _file_identity(source)
    if device is not None and inode is not None and (actual_device, actual_inode) != (device, inode):
        raise WorkDeletionApplyError(f"move source strong identity changed: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise WorkDeletionApplyError(f"move destination appeared: {destination}")
    os.rename(source, destination)
    _fsync_directory(source.parent)
    _fsync_directory(destination.parent)
    if not destination.is_file():
        raise WorkDeletionApplyError(f"move destination missing after rename: {destination}")
    if size is not None and destination.stat().st_size != size:
        raise WorkDeletionApplyError(f"move destination size mismatch: {destination}")
    if digest is not None and _sha256_file(destination).casefold() != digest.casefold():
        raise WorkDeletionApplyError(f"move destination hash mismatch: {destination}")
    if device is not None and inode is not None and _file_identity(destination) != (device, inode):
        raise WorkDeletionApplyError(f"move destination strong identity mismatch: {destination}")


def _catalog_commit_state(path: Path, work_id: int, before_fingerprint: str) -> str:
    if not path.is_file():
        return "other"
    try:
        with CatalogService(path)._read_only_connection() as connection:
            row = connection.execute("SELECT 1 FROM works WHERE id = ?", (work_id,)).fetchone()
            if row is None:
                return "deleted"
            tables = (
                "works", "items", "sources", "source_targets", "crawl_runs", "artifacts",
                "quota_resource_states", "acquisition_scope_sync",
                "discovery_inventory_evidence", "discovery_inventory_positions",
            )
            payload = {
                table: [dict(value) for value in connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()]
                for table in tables
            }
            current = _sha256_json(payload)
            return "before" if current == before_fingerprint else "other"
    except (OSError, sqlite3.Error):
        return "other"


def _find_recovery_manifest(trash: Path, active_marker: Path, operation_id: str | None) -> Path | None:
    candidates: list[Path] = []
    if operation_id:
        operations = active_marker.parent / "operations.json"
        if operations.is_file():
            try:
                value = json.loads(operations.read_text(encoding="utf-8"))
                reference = value.get(operation_id, {}) if isinstance(value, dict) else {}
                if isinstance(reference, dict) and reference.get("manifest"):
                    candidates.append(Path(str(reference["manifest"])))
            except (OSError, UnicodeDecodeError, ValueError, TypeError):
                return None
    if active_marker.is_file():
        try:
            value = json.loads(active_marker.read_text(encoding="utf-8"))
            referenced = Path(str(value.get("manifest", ""))) if isinstance(value, dict) else Path()
            if referenced:
                candidates.append(referenced)
        except (OSError, UnicodeDecodeError, ValueError, TypeError):
            return None
    for candidate in candidates:
        try:
            if candidate.resolve(strict=False).parent.parent != trash.resolve(strict=False):
                continue
        except OSError:
            continue
        if candidate.is_file():
            return candidate
    return None


def _intent_path_matches(path: Path, intent: dict[str, Any]) -> bool:
    if not path.is_file() or path.is_symlink():
        return False
    try:
        if path.stat().st_size != int(intent["size"]):
            return False
        if _sha256_file(path).casefold() != str(intent["sha256"]).casefold():
            return False
        device, inode = intent.get("device"), intent.get("inode")
        return device is None or _file_identity(path) == (int(device), int(inode))
    except (OSError, KeyError, TypeError, ValueError):
        return False


def _recovery_file_state(intents: list[dict[str, Any]]) -> str:
    if not intents:
        return "staged"
    states: list[str] = []
    for intent in intents:
        source = Path(str(intent.get("source", "")))
        destination = Path(str(intent.get("destination", "")))
        source_ok = _intent_path_matches(source, intent)
        destination_ok = _intent_path_matches(destination, intent)
        if source_ok and not destination.exists():
            states.append("before")
        elif destination_ok and not source.exists():
            states.append("staged")
        else:
            states.append("other")
    if all(state == "before" for state in states):
        return "before"
    if all(state == "staged" for state in states):
        return "staged"
    if all(state in {"before", "staged"} for state in states):
        return "mixed"
    return "other"


def _catalog_payload(path: Path) -> dict[str, list[dict[str, Any]]] | None:
    if not path.is_file():
        return None
    try:
        with CatalogService(path)._read_only_connection() as connection:
            if _unknown_catalog_schema(connection):
                return None
            return {
                table: [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()]
                for table in _TABLES
            }
    except (OSError, sqlite3.Error, CatalogError):
        return None


def _catalog_after_payload(payload: dict[str, list[dict[str, Any]]], work_id: int) -> dict[str, list[dict[str, Any]]]:
    work_ids = {work_id}
    item_ids = {int(row["id"]) for row in payload["items"] if int(row["work_id"]) in work_ids}
    source_ids = {int(row["id"]) for row in payload["sources"] if int(row["item_id"]) in item_ids}
    target_ids = {int(row["id"]) for row in payload["source_targets"] if int(row["source_id"]) in source_ids}
    run_ids = {
        int(row["id"]) for row in payload["crawl_runs"]
        if int(row["item_id"]) in item_ids or int(row["source_id"]) in source_ids or int(row["target_id"]) in target_ids
    }
    artifact_ids = {
        int(row["id"]) for row in payload["artifacts"]
        if int(row["item_id"]) in item_ids or (row["crawl_run_id"] is not None and int(row["crawl_run_id"]) in run_ids)
    }
    discovery_keys = {str(row["discovery_key"]) for row in payload["discovery_inventory_evidence"] if int(row["work_id"]) in work_ids}
    id_sets = {
        "items": item_ids, "sources": source_ids, "source_targets": target_ids,
        "crawl_runs": run_ids, "artifacts": artifact_ids,
    }
    result: dict[str, list[dict[str, Any]]] = {}
    for table, rows in payload.items():
        kept: list[dict[str, Any]] = []
        for row in rows:
            if table == "works" and int(row["id"]) in work_ids:
                continue
            if table in id_sets and int(row["id"]) in id_sets[table]:
                continue
            if table in {"quota_resource_states", "acquisition_scope_sync", "discovery_inventory_evidence"} and int(row["work_id"]) in work_ids:
                continue
            if table == "discovery_inventory_positions" and str(row["discovery_key"]) in discovery_keys:
                continue
            kept.append(row)
        result[table] = kept
    return result


def _recovery_catalog_state(catalog: Path, manifest: dict[str, Any], operation_dir: Path, work_id: int | None) -> str:
    before = manifest.get("catalog_before")
    if work_id is None:
        return "absent" if before is None and not catalog.exists() else ("before" if before == _file_fact(catalog) else "other")
    backup = operation_dir / "catalog-before.sqlite"
    backup_fact = manifest.get("catalog_backup")
    if backup.is_file() and not isinstance(backup_fact, dict):
        return "other"
    if backup_fact is not None and not _fact_matches(backup, backup_fact):
        return "other"
    if backup_fact is not None and not backup.is_file():
        return "other"
    before_payload = _catalog_payload(backup)
    current_payload = _catalog_payload(catalog)
    if before_payload is not None and current_payload is not None:
        if current_payload == before_payload:
            return "before"
        if current_payload == _catalog_after_payload(before_payload, work_id):
            return "deleted"
        return "other"
    if before is not None and _file_fact(catalog) == before:
        return "before"
    if not catalog.exists() and before is None:
        return "absent"
    return "other"


def _safe_operation_child(operation_dir: Path, raw: Any, fallback: str) -> Path:
    candidate = operation_dir / fallback if not raw else Path(str(raw))
    if candidate.resolve(strict=False).parent != operation_dir.resolve(strict=False):
        raise WorkDeletionApplyError("manifest snapshot path escapes operation directory")
    return candidate


def _recovery_manifest_missing_fields(manifest: dict[str, Any]) -> tuple[str, ...]:
    required = (
        "operation_id", "phase", "work_key", "work_id", "plan_token",
        "catalog_path", "watchlist_path", "operation_namespace", "active_marker",
        "intents",
    )
    missing = [name for name in required if name not in manifest]
    for name in ("operation_id", "phase", "work_key", "plan_token", "catalog_path", "watchlist_path", "operation_namespace", "active_marker"):
        if name in manifest and not isinstance(manifest[name], str):
            missing.append(name)
    if "intents" in manifest and not isinstance(manifest["intents"], list):
        missing.append("intents")
    return tuple(dict.fromkeys(missing))


def _expected_watchlist_bytes(before_path: Path, work_key: str) -> bytes | None:
    if not before_path.is_file():
        return None
    try:
        original = before_path.read_bytes()
        fact = _file_fact(before_path)
        if fact is None:
            return None
        service = WatchlistService(before_path)
        content = original.decode("utf-8")
        targets = service._load_content(content)
        archived = service._cached_document[2] if service._cached_document else ()
        desired_targets = [target for target in targets if target.work_key != work_key]
        desired_archived = tuple(key for key in archived if key != work_key)
        patched = content
        if desired_targets != targets:
            patched = service._patch_existing_yaml(patched, targets, desired_targets)
            if patched is None:
                return None
        if desired_archived != archived:
            patched = service._patch_archived_work_keys(patched, desired_archived)
        service._validate_written_content(patched, desired_targets, archived_work_keys=desired_archived)
        return service._preserve_eol(patched, content).encode("utf-8")
    except (OSError, UnicodeDecodeError, TypeError, ValueError):
        return None


def _recovery_watchlist_state(path: Path, manifest: dict[str, Any], operation_dir: Path, work_key: str) -> str:
    before = manifest.get("watchlist_before")
    if before is None:
        return "absent" if not path.exists() else "other"
    if not path.is_file():
        return "other"
    current_fact = _watchlist_fact(path)
    if current_fact == before:
        return "before"
    before_path = _safe_operation_child(operation_dir, manifest.get("watchlist_before_path"), "watchlist-before.yaml")
    before_snapshot_fact = _file_fact(before_path)
    if before_snapshot_fact is None or before_snapshot_fact.get("size") != before.get("size") or before_snapshot_fact.get("sha256") != before.get("sha256"):
        raise WorkDeletionApplyError("Watchlist before snapshot does not match the manifest")
    after_path = _safe_operation_child(operation_dir, manifest.get("watchlist_after_path"), "watchlist-after.yaml")
    after_fact = manifest.get("watchlist_after")
    if after_path.is_file() and isinstance(after_fact, dict):
        snapshot_fact = _file_fact(after_path)
        if snapshot_fact is None or any(snapshot_fact.get(key) != after_fact.get(key) for key in ("size", "sha256")):
            return "other"
    expected = after_path.read_bytes() if after_path.is_file() else _expected_watchlist_bytes(before_path, work_key)
    return "deleted" if expected is not None and path.read_bytes() == expected else "other"


def _restore_watchlist_before(path: Path, manifest: dict[str, Any], operation_dir: Path) -> None:
    before_path = _safe_operation_child(operation_dir, manifest.get("watchlist_before_path"), "watchlist-before.yaml")
    if not before_path.is_file():
        raise WorkDeletionApplyError("Watchlist before snapshot is missing")
    try:
        content = before_path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise WorkDeletionApplyError("Watchlist before snapshot is unreadable") from exc
    WatchlistService(path)._atomic_write(content)


def _watchlist_commit_state(path: Path, work_key: str, before: dict[str, Any] | None, before_non_target: tuple[Any, ...] | None) -> str:
    if not path.is_file():
        return "unchanged" if before is None else "other"
    try:
        current = _watchlist_fact(path)
        if current == before:
            return "unchanged"
        document = WatchlistService(path).read_document()
        if any(target.work_key == work_key for target in document.targets) or work_key in document.archived_work_keys:
            return "unchanged"
        return "deleted" if _watchlist_non_target_snapshot(path, work_key) == before_non_target else "other"
    except (OSError, TypeError, ValueError):
        return "other"


def _sha256_file(path: Path, *, check: Any | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            if check is not None:
                check()
            digest.update(chunk)
    return digest.hexdigest()


def _file_identity(path: Path) -> tuple[int | None, int | None]:
    try:
        info = path.stat()
        device = getattr(info, "st_dev", None)
        inode = getattr(info, "st_ino", None)
        if device is None or inode is None or int(inode) == 0:
            return None, None
        return int(device), int(inode)
    except OSError:
        return None, None


def _sqlite_file_snapshot(path: Path) -> tuple[tuple[str, int, int, str], ...]:
    result: list[tuple[str, int, int, str]] = []
    for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
        if not candidate.is_file():
            continue
        try:
            stat_result = candidate.stat()
            result.append((candidate.name, stat_result.st_size, stat_result.st_mtime_ns, _sha256_file(candidate)))
        except OSError:
            result.append((candidate.name, -1, -1, "unreadable"))
    return tuple(result)


def _sqlite_wal_present(path: Path) -> bool:
    """Detect WAL mode from SQLite's header before opening a read-only URI."""

    if Path(str(path) + "-wal").exists() or Path(str(path) + "-shm").exists():
        return True
    try:
        with path.open("rb") as stream:
            header = stream.read(20)
    except OSError:
        return True
    return len(header) < 20 or header[18] == 2 or header[19] == 2


def _sqlite_hot_journal(path: Path) -> bool:
    return path.is_file() and Path(str(path) + "-journal").is_file() and not _sqlite_wal_present(path)


def _recover_sqlite_hot_journal(path: Path) -> None:
    """Let SQLite roll back a hot rollback journal during explicit recovery."""

    if not _sqlite_hot_journal(path):
        return
    with sqlite3.connect(path, timeout=5) as connection:
        connection.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _paths_overlap(first: Path, second: Path) -> bool:
    return _is_within(first, second) or _is_within(second, first)


def _hardlink_or_reparse(path: Path) -> bool:
    try:
        info = path.stat()
        hardlink = path.is_file() and int(getattr(info, "st_nlink", 1)) != 1
        return hardlink or bool(int(getattr(info, "st_file_attributes", 0)) & _REPARSE_POINT) or stat.S_ISLNK(path.lstat().st_mode)
    except OSError:
        return True


def _raw_path_unsafe(raw: str, base: Path) -> bool:
    """Reject traversal and symlink/reparse parents before resolving."""

    candidate = Path(raw)
    if any(part == ".." for part in candidate.parts):
        return True
    # Match the established Path(locator).resolve() semantics for relative
    # Catalog/status values.  `base` is retained for the caller contract but
    # must not silently change the meaning of an existing relative locator.
    del base
    current = candidate
    for parent in (current, *current.parents):
        try:
            info = parent.lstat()
        except OSError:
            continue
        if stat.S_ISLNK(info.st_mode) or bool(int(getattr(info, "st_file_attributes", 0)) & _REPARSE_POINT):
            return True
    return False


def _same_volume(first: Path, second: Path) -> bool:
    """Compare devices without creating a missing trash directory."""

    def device(path: Path) -> int | None:
        current = path
        while True:
            try:
                return int(current.stat().st_dev)
            except OSError:
                parent = current.parent
                if parent == current:
                    return None
                current = parent

    left, right = device(first), device(second)
    return left is not None and right is not None and left == right


def _existing_ancestor(path: Path) -> Path | None:
    current = path
    while True:
        try:
            if current.exists() and current.is_dir() and not current.is_symlink():
                return current
        except OSError:
            return None
        parent = current.parent
        if parent == current:
            return None
        current = parent


__all__ = [
    "ArtifactPreview",
    "WorkDeletionApplyError",
    "WorkDeletionApplyResult",
    "WorkDeletionCancelToken",
    "WorkDeletionCancelled",
    "WorkDeletionPlan",
    "WorkDeletionPreviewService",
    "WorkDeletionRecoveryResult",
    "register_management_store",
]
