"""Qt-independent planning DTOs for the Windows execution controls.

The inventory GUI uses this module for the confirmation boundary.  It only
reads the immutable P1 snapshot; browser sessions and Catalog mutations stay
outside the preview path.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from screenshot_crawler.auth.env import read_env_file
from screenshot_crawler.batch import BatchPlanner
from screenshot_crawler.catalog import CatalogError, CatalogService
from screenshot_crawler.catalog.schema import validate_existing_schema
from screenshot_crawler.core.browser import resolve_cdp_endpoint
from screenshot_crawler.management.inventory import InventoryService
from screenshot_crawler.management.models import InventorySnapshot, KeyInventory
from screenshot_crawler.site_policies import SitePolicyRegistry
from screenshot_crawler.watchlist.service import WatchlistService

ExecutionAction = Literal["discover", "batch", "grant_only"]


def _file_fingerprint(path: str | Path | None) -> tuple[str, str]:
    if path is None:
        return "", "missing"
    resolved = str(Path(path).resolve())
    try:
        digest = hashlib.sha256(Path(resolved).read_bytes()).hexdigest()
    except OSError:
        digest = "missing"
    return resolved, digest


def _effective_endpoint_hash(
    site: str, *, env_file: str | None, cdp_endpoint: str | None
) -> str:
    values = {}
    if env_file is not None and Path(env_file).is_file():
        values = read_env_file(env_file)
    endpoint = resolve_cdp_endpoint(site=site, cli_endpoint=cdp_endpoint, values=values)
    return hashlib.sha256(endpoint.encode("utf-8")).hexdigest()


class ReadOnlyCatalogService(CatalogService):
    """CatalogService facade that cannot initialize or mutate a database."""

    @contextmanager
    def _connection(self, *, initialize_schema: bool = True):
        if not self.path.is_file():
            raise CatalogError(f"Catalog database not found: {self.path}")
        try:
            with self.path.open("rb") as stream:
                header = stream.read(20)
            if header.startswith(b"SQLite format 3\x00") and 2 in header[18:20]:
                raise CatalogError("WAL Catalog cannot be used for a read-only preview")
            connection = sqlite3.connect(
                f"{self.path.resolve().as_uri()}?mode=ro", uri=True, timeout=2
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA query_only = ON")
            validate_existing_schema(connection)
        except (sqlite3.Error, ValueError) as exc:
            raise CatalogError(f"Could not read Catalog database '{self.path}': {exc}") from exc
        try:
            yield connection
        finally:
            connection.close()

    _read_only_connection = _connection


@dataclass(frozen=True, slots=True)
class ExecutionSelection:
    """An explicit, immutable Watchlist-key selection.

    ``None`` is intentionally never used here: an empty ``frozenset`` means
    no work and cannot be interpreted as a whole-site request.
    """

    selected_keys: frozenset[str]

    @classmethod
    def from_keys(cls, keys: Iterable[str]) -> ExecutionSelection:
        values = tuple(keys)
        if any(not isinstance(value, str) or not value for value in values):
            raise ValueError("selected keys must be non-empty strings")
        if len(values) != len(set(values)):
            raise ValueError("selected keys must be unique")
        return cls(frozenset(values))


@dataclass(frozen=True, slots=True)
class JobExecutionRequest:
    """Stable request passed from GUI to a future worker/job queue."""

    action: ExecutionAction
    selected_keys: frozenset[str]
    sites: tuple[str, ...]
    keys_by_site: tuple[tuple[str, tuple[str, ...]], ...] = ()
    mode: str | None = None
    resource: str | None = None
    resources_by_site: tuple[tuple[str, str], ...] = ()
    limit: int | None = None
    catalog_path: str | None = None
    watchlist_path: str | None = None
    runtime_path: str | None = None
    env_file: str | None = None
    cdp_endpoint: str | None = None
    output_root: str | None = None
    library_dir: str | None = None
    metrics_root: str | None = None
    plan_fingerprint: str = ""


def execution_request_payload(request: JobExecutionRequest) -> dict[str, object]:
    """Return the JSON-safe worker payload for one confirmed request."""

    payload = asdict(request)
    payload["selected_keys"] = sorted(request.selected_keys)
    payload["sites"] = list(request.sites)
    payload["keys_by_site"] = {
        site: list(keys) for site, keys in request.keys_by_site
    }
    payload["resources_by_site"] = {
        site: resource for site, resource in request.resources_by_site
    }
    return payload


@dataclass(frozen=True, slots=True)
class ExecutionPlanPreview:
    action: ExecutionAction
    selection: ExecutionSelection
    sites: tuple[str, ...]
    mode: str | None
    resource: str | None
    limit: int | None
    candidate_count: int
    skipped_count: int
    skipped: tuple[tuple[str, str], ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    fingerprint: str
    resources_by_site: tuple[tuple[str, str], ...] = ()
    work_names: tuple[str, ...] = ()

    @property
    def can_confirm(self) -> bool:
        return bool(self.selection.selected_keys) and not self.blockers

    def request(self, snapshot: InventorySnapshot) -> JobExecutionRequest:
        if not self.can_confirm:
            raise ValueError("execution preview is blocked")
        return JobExecutionRequest(
            action=self.action,
            selected_keys=self.selection.selected_keys,
            sites=self.sites,
            keys_by_site=tuple(
                (site, tuple(sorted(identity for identity in self.selection.selected_keys
                                   if next((key.site for key in snapshot.keys if key.identity == identity), None) == site)))
                for site in self.sites
            ),
            mode=self.mode,
            resource=self.resource,
            resources_by_site=self.resources_by_site,
            limit=self.limit,
            catalog_path=snapshot.catalog_path,
            watchlist_path=snapshot.watchlist_path,
            plan_fingerprint=self.fingerprint,
        )


class ExecutionPlanService:
    """Build a read-only preview from a loaded InventorySnapshot."""

    def preview(
        self,
        snapshot: InventorySnapshot,
        selection: ExecutionSelection | Iterable[str],
        *,
        action: ExecutionAction,
        mode: str | None = None,
        resource: str | None = None,
        limit: int | None = None,
        runtime_path: str | None = None,
        env_file: str | None = None,
        cdp_endpoint: str | None = None,
        output_root: str | None = None,
        library_dir: str | None = None,
        metrics_root: str | None = None,
    ) -> ExecutionPlanPreview:
        selected = (
            selection
            if isinstance(selection, ExecutionSelection)
            else ExecutionSelection.from_keys(selection)
        )
        input_paths_before = {
            "catalog": _file_fingerprint(snapshot.catalog_path),
            "watchlist": _file_fingerprint(snapshot.watchlist_path),
            "runtime": _file_fingerprint(runtime_path or "crawler.yaml"),
            "env": _file_fingerprint(env_file),
        }
        key_by_identity = {key.identity: key for key in snapshot.keys}
        blockers: list[str] = []
        warnings: list[str] = []
        skipped: list[tuple[str, str]] = []
        selected_records: list[KeyInventory] = []
        for identity in sorted(selected.selected_keys):
            key = key_by_identity.get(identity)
            if key is None:
                blockers.append(f"unknown Watchlist key: {identity}")
                continue
            selected_records.append(key)
            if key.target is None:
                skipped.append((identity, "unmanaged"))
                continue
            if not key.target.enabled:
                skipped.append((identity, "disabled"))
            if action != "discover" and key.summary.sync_status in {"binding_mismatch", "error"}:
                blockers.append(
                    f"{identity}: Scope/Watchlist state is {key.summary.sync_status}"
                )
            if key.summary.diagnostics:
                warnings.extend(f"{identity}: {value}" for value in key.summary.diagnostics)

        sites = tuple(sorted({key.site for key in selected_records if key.target is not None}))
        candidate_count = 0
        for key in selected_records:
            counts = key.summary.counts
            if counts is None:
                continue
            if action == "discover":
                candidate_count += 1 if key.target is not None and key.target.enabled else 0
            else:
                candidate_count += counts.direct + counts.quota
        if not selected.selected_keys:
            blockers.append("no Watchlist keys selected")
        if action == "discover" and not any(
            key.target is not None and key.target.enabled for key in selected_records
        ):
            blockers.append("Discover requires at least one enabled Watchlist key")
        if limit is not None and limit < 1:
            blockers.append("limit must be at least 1")
        if action == "grant_only" and resource is None:
            blockers.append("Grant-only requires an explicit resource or all")
        if action == "grant_only":
            warnings.append("Grant-only may consume a site entitlement or quota")
        input_paths_after = {
            "catalog": _file_fingerprint(snapshot.catalog_path),
            "watchlist": _file_fingerprint(snapshot.watchlist_path),
            "runtime": _file_fingerprint(runtime_path or "crawler.yaml"),
            "env": _file_fingerprint(env_file),
        }
        if input_paths_before != input_paths_after:
            blockers.append("Catalog/Watchlist/runtime changed while building preview")

        payload = {
            "action": action,
            "keys": sorted(selected.selected_keys),
            "catalog_path": snapshot.catalog_path,
            "watchlist_path": snapshot.watchlist_path,
            "runtime_path": str(runtime_path or "crawler.yaml"),
            "output_root": str(output_root or "output/batch"),
            "library_dir": str(library_dir or "output/Books"),
            "metrics_root": str(metrics_root or "output/metrics"),
            "endpoint_identities": {
                site: _effective_endpoint_hash(
                    site, env_file=env_file, cdp_endpoint=cdp_endpoint
                )
                for site in sites
            },
            "input_paths": {
                **input_paths_before,
            },
            "input_paths_after": input_paths_after,
            "targets": [
                {
                    "identity": key.identity,
                    "site": key.site,
                    "work_key": key.work_key,
                    "url": key.target.url if key.target is not None else None,
                    "enabled": key.target.enabled if key.target is not None else None,
                    "sync_status": key.summary.sync_status,
                }
                for key in selected_records
            ],
            "sites": sites,
            "mode": mode,
            "resource": resource,
            "limit": limit,
            "candidates": candidate_count,
            "skipped": skipped,
            "blockers": blockers,
        }
        fingerprint = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return ExecutionPlanPreview(
            action=action,
            selection=selected,
            sites=sites,
            mode=mode,
            resource=resource,
            limit=limit,
            candidate_count=candidate_count,
            skipped_count=len(skipped),
            skipped=tuple(skipped),
            blockers=tuple(dict.fromkeys(blockers)),
            warnings=tuple(dict.fromkeys(warnings)),
            fingerprint=fingerprint,
            work_names=tuple(sorted({key.title or key.work_key for key in selected_records})),
        )

    def preview_batch(
        self,
        catalog_path: str,
        watchlist_path: str,
        policies: SitePolicyRegistry,
        *,
        site: str,
        selected_keys: Iterable[str],
        resource: str | None = None,
        limit: int | None = None,
        runtime_path: str | None = None,
        library_dir: str | None = None,
        output_root: str | None = None,
        metrics_root: str | None = None,
        env_file: str | None = None,
        cdp_endpoint: str | None = None,
    ) -> ExecutionPlanPreview:
        """Build an actual BatchPlanner plan through a read-only Catalog facade."""

        selection = ExecutionSelection.from_keys(selected_keys)
        input_paths = {
            "catalog": _file_fingerprint(catalog_path),
            "watchlist": _file_fingerprint(watchlist_path),
            "runtime": _file_fingerprint(runtime_path or "crawler.yaml"),
            "env": _file_fingerprint(env_file),
        }
        catalog = ReadOnlyCatalogService(catalog_path)
        inventory = InventoryService().load(
            catalog_path,
            watchlist_path,
            runtime_path=runtime_path or "crawler.yaml",
        )
        sync_blockers = []
        key_map = {key.identity: key for key in inventory.keys}
        for identity in selection.selected_keys:
            key = key_map.get(identity)
            if key is None:
                sync_blockers.append(f"unknown Watchlist key: {identity}")
            elif key.summary.sync_status in {"binding_mismatch", "error"}:
                sync_blockers.append(
                    f"{identity}: Scope/Watchlist state is {key.summary.sync_status}"
                )
        planner = BatchPlanner(
            catalog,
            policies,
            watchlist=WatchlistService(watchlist_path),
            library_dir=library_dir or catalog.path.parent / "Books",
        )
        resources = (
            tuple(policies.create(site).grant_only_supported_access_resources())
            if resource == "all"
            else (resource,)
        )
        if resource == "all" and not resources:
            raise ValueError(f"Site {site!r} does not support Grant-only")
        plans = [
            planner.plan(
                site=site,
                selected_keys=selection.selected_keys,
                quota_resource=current_resource,
                output_mode="grant_only" if current_resource is not None else "capture",
            )
            for current_resource in resources or (None,)
        ]
        blockers = list(sync_blockers)
        if not selection.selected_keys:
            blockers.append("no Watchlist keys selected")
        warnings = [warning for item in plans for warning in item.warnings]
        warnings.extend(
            f"{identity}: {note}; using saved acquisition flags"
            for identity in selection.selected_keys if identity in key_map
            for note in key_map[identity].summary.diagnostics
        )
        for current_resource, plan in zip(resources or (None,), plans):
            if plan.quota_available is not None:
                resource_label = current_resource or "default"
                warnings.append(
                    f"site={site} resource={resource_label} "
                    f"quota available={plan.quota_available}"
                )
        if resource is not None:
            warnings.append("Grant-only may consume a site entitlement or quota")
        if limit is not None and limit < 1:
            blockers.append("limit must be at least 1")
        after_paths = {
            "catalog": _file_fingerprint(catalog_path),
            "watchlist": _file_fingerprint(watchlist_path),
            "runtime": _file_fingerprint(runtime_path or "crawler.yaml"),
            "env": _file_fingerprint(env_file),
        }
        if input_paths != after_paths:
            blockers.append("Catalog/Watchlist/runtime changed while building preview")
        all_candidates = [candidate for item in plans for candidate in item.candidates]
        candidates = all_candidates if limit is None else all_candidates[:limit]
        payload = {
            "action": "grant_only" if resource is not None else "batch",
            "keys": sorted(selection.selected_keys),
            "site": site,
            "resource": resource,
            "limit": limit,
            "catalog_path": str(catalog_path),
            "watchlist_path": str(watchlist_path),
            "runtime_path": str(runtime_path or "crawler.yaml"),
            "library_dir": str(library_dir or catalog.path.parent / "Books"),
            "output_root": str(output_root or catalog.path.parent / "output" / "batch"),
            "metrics_root": str(metrics_root or catalog.path.parent / "output" / "metrics"),
            "cdp_endpoint": cdp_endpoint,
            "endpoint_identity": _effective_endpoint_hash(
                site, env_file=env_file, cdp_endpoint=cdp_endpoint
            ),
            "input_paths": input_paths,
            "input_paths_after": after_paths,
            "candidates": [
                {
                    "item_id": candidate.item_id,
                    "source_id": candidate.source_id,
                    "target_id": candidate.target_id,
                    "discovery_key": candidate.discovery_key,
                    "locator": candidate.locator,
                    "artifact_prefix": candidate.artifact_prefix,
                    "artifact_disambiguator": candidate.artifact_disambiguator,
                    "access_strategy": candidate.access_strategy,
                    "access_mode": candidate.access_mode,
                    "consumes_quota": candidate.consumes_quota,
                    "quota_resource": candidate.quota_resource,
                    "quota_scope": candidate.quota_scope,
                    "quota_limit": candidate.quota_limit,
                    "quota_commit_mode": candidate.quota_commit_mode,
                    "external_id": candidate.external_id,
                    "work_id": candidate.work_id,
                    "metadata": candidate.metadata,
                }
                for candidate in candidates
            ],
            "skips": [
                (skip.item_id, skip.source_id, skip.reason)
                for item in plans
                for skip in item.skipped
            ],
            "warnings": warnings,
        }
        fingerprint = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return ExecutionPlanPreview(
            action="grant_only" if resource is not None else "batch",
            selection=selection,
            sites=(site,),
            mode=None,
            resource=resource,
            limit=limit,
            candidate_count=len(candidates),
            skipped_count=sum(len(item.skipped) for item in plans),
            skipped=tuple(
                (str(skip.source_id or skip.item_id), skip.reason)
                for item in plans
                for skip in item.skipped
            ),
            blockers=tuple(blockers),
            warnings=tuple(dict.fromkeys(warnings)),
            fingerprint=fingerprint,
            resources_by_site=((site, resource),) if resource is not None else (),
            work_names=tuple(
                sorted({key.title or key.work_key for key in key_map.values()
                        if key.identity in selection.selected_keys})
            ),
        )


__all__ = [
    "ExecutionAction",
    "ExecutionPlanPreview",
    "ExecutionPlanService",
    "ExecutionSelection",
    "JobExecutionRequest",
    "execution_request_payload",
]
