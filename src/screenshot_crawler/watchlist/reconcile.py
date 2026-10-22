"""Service layer for fail-closed Watchlist-to-Catalog acquisition scope sync."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from screenshot_crawler.archive_order import (
    ArchiveOrderPlanningError,
    build_work_archive_position_plan,
)
from screenshot_crawler.catalog import CatalogError, CatalogService
from screenshot_crawler.catalog.models import AcquisitionScopeSnapshot, Source
from screenshot_crawler.watchlist.fingerprints import (
    configuration_json,
    target_scope_definition,
    target_scope_fingerprint,
    work_definition_fingerprint,
    work_scope_fingerprint,
)
from screenshot_crawler.watchlist.models import DiscoveryScope, WatchlistTarget
from screenshot_crawler.watchlist.service import WatchlistService


@dataclass(frozen=True, slots=True)
class ScopeFlagChange:
    source_id: int
    site: str
    discovery_key: str
    external_id: str
    before: bool
    after: bool
    reason: str


@dataclass(frozen=True, slots=True)
class ScopeSyncPreview:
    work_key: str
    fingerprint: str
    definition_fingerprint: str
    configuration_json: str
    revision_token: str | None
    discovery_keys: tuple[str, ...]
    source_flags: tuple[tuple[int, bool], ...]
    changes: tuple[ScopeFlagChange, ...]
    blockers: tuple[str, ...]
    legacy_bootstrap: bool = False
    archive_order_preview: dict[str, Any] | None = None

    @property
    def ready(self) -> bool:
        return not self.blockers

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["ready"] = self.ready
        selected = sum(1 for _, enabled in self.source_flags if enabled)
        total = len(self.source_flags)
        result["selected_count"] = selected
        result["enabled_count"] = (
            selected
            - sum(1 for change in self.changes if change.after and not change.before)
            + sum(1 for change in self.changes if not change.after and change.before)
        )
        result["excluded_count"] = total - selected
        result["unresolved_count"] = len(self.blockers)
        return result


class ScopeReconciliationError(RuntimeError):
    """Raised when a preview is blocked or stale at apply time."""


class ScopeReconciler:
    """Preview or apply one Work's acquisition flags without accessing sites."""

    def __init__(self, watchlist: WatchlistService, catalog: CatalogService) -> None:
        self.watchlist = watchlist
        self.catalog = catalog

    def preview(self, work_key: str) -> ScopeSyncPreview:
        targets = [
            target for target in self.watchlist.list_targets() if target.work_key == work_key
        ]
        targets.sort(key=lambda target: target.key)
        if not targets:
            return self._blocked(work_key, "Watchlist has no targets for this work_key")

        fingerprint = work_scope_fingerprint(targets)
        definition = work_definition_fingerprint(targets)
        current_configuration = configuration_json(targets)
        try:
            snapshot = self.catalog.read_acquisition_scope_snapshot(
                work_key, discovery_keys=[target.key for target in targets]
            )
        except CatalogError as exc:
            return ScopeSyncPreview(
                work_key=work_key,
                fingerprint=fingerprint,
                definition_fingerprint=definition,
                configuration_json=current_configuration,
                revision_token=None,
                discovery_keys=tuple(target.key for target in targets),
                source_flags=(),
                changes=(),
                blockers=(f"Catalog read failed: {exc}",),
            )
        if snapshot is None:
            return ScopeSyncPreview(
                work_key=work_key,
                fingerprint=fingerprint,
                definition_fingerprint=definition,
                configuration_json=current_configuration,
                revision_token=None,
                discovery_keys=tuple(target.key for target in targets),
                source_flags=(),
                changes=(),
                blockers=("Catalog work does not exist; run Discovery first",),
            )
        return self._build_preview(
            work_key, targets, snapshot, fingerprint, definition, current_configuration
        )

    def apply(self, preview: ScopeSyncPreview) -> tuple[Source, ...]:
        if preview.blockers:
            raise ScopeReconciliationError(
                "Scope sync is blocked: " + "; ".join(preview.blockers)
            )
        with self.catalog.job_lock():
            current = self.preview(preview.work_key)
            if not current.ready:
                raise ScopeReconciliationError(
                    "Scope sync became blocked: " + "; ".join(current.blockers)
                )
            if (
                current.fingerprint != preview.fingerprint
                or current.definition_fingerprint != preview.definition_fingerprint
                or current.configuration_json != preview.configuration_json
                or current.revision_token != preview.revision_token
                or current.source_flags != preview.source_flags
            ):
                raise ScopeReconciliationError(
                    "Watchlist or Catalog changed after preview; create a new preview"
                )
            assert current.revision_token is not None
            return self.catalog.apply_acquisition_scope_sync(
                work_key=current.work_key,
                fingerprint=current.fingerprint,
                definition_fingerprint=current.definition_fingerprint,
                configuration_json=current.configuration_json,
                expected_revision_token=current.revision_token,
                discovery_keys=current.discovery_keys,
                source_flags=dict(current.source_flags),
            )

    def require_synchronized(self, work_key: str) -> ScopeSyncPreview:
        """Require current Watchlist binding and every Catalog flag to agree."""
        preview, _snapshot = self._require_synchronized_state(work_key)
        return preview

    def require_synchronized_snapshot(self, work_key: str) -> AcquisitionScopeSnapshot:
        """Return the exact Catalog snapshot validated against the current Watchlist."""
        _preview, snapshot = self._require_synchronized_state(work_key)
        return snapshot

    def _require_synchronized_state(
        self, work_key: str
    ) -> tuple[ScopeSyncPreview, AcquisitionScopeSnapshot]:
        preview = self.preview(work_key)
        if not preview.ready:
            raise ScopeReconciliationError(
                "Scope is unresolved for work_key "
                f"{work_key!r}: {'; '.join(preview.blockers)}. "
                "Run `watch scope-sync --work-key "
                f"{work_key} --dry-run`, resolve the reported issue, then "
                "apply only after reviewing the complete diff."
            )
        try:
            snapshot = self.catalog.read_acquisition_scope_snapshot(
                work_key, discovery_keys=preview.discovery_keys
            )
        except CatalogError as exc:
            raise ScopeReconciliationError(
                f"Cannot validate scope sync for work_key {work_key!r}: {exc}"
            ) from exc
        if snapshot is None or snapshot.revision_token != preview.revision_token:
            raise ScopeReconciliationError(
                f"Catalog changed while validating scope sync for {work_key!r}; retry Batch"
            )
        sync = snapshot.sync
        if sync is None or sync.status != "synced" or sync.fingerprint != preview.fingerprint:
            raise ScopeReconciliationError(
                f"Scope sync is missing or stale for work_key {work_key!r}; "
                "run `watch scope-sync --work-key "
                f"{work_key} --dry-run`, review the result, then apply"
            )
        actual_flags = {
            source.id: source.acquisition_enabled for source in snapshot.sources
        }
        if preview.changes or actual_flags != dict(preview.source_flags):
            raise ScopeReconciliationError(
                f"Catalog acquisition flags do not match the synced Watchlist for "
                f"work_key {work_key!r}; rerun `watch scope-sync --work-key "
                f"{work_key} --dry-run` and review/apply the difference"
            )
        return preview, snapshot

    def _build_preview(
        self,
        work_key: str,
        targets: list[WatchlistTarget],
        snapshot: AcquisitionScopeSnapshot,
        fingerprint: str,
        definition: str,
        current_configuration_json: str,
    ) -> ScopeSyncPreview:
        blockers: list[str] = []
        target_by_key = {target.key: target for target in targets}
        current_configuration = {
            target.key: target_scope_definition(target) for target in targets
        }
        prior_configuration = self._prior_configuration(snapshot, blockers)
        saved_configuration = self._merge_configuration_history(
            current_configuration_json, prior_configuration
        )
        prior_by_key = {
            str(value.get("key")): value
            for value in prior_configuration
            if isinstance(value, dict) and isinstance(value.get("key"), str)
        }
        prior_core_by_key = {
            key: {name: value for name, value in binding.items() if name != "archive_order"}
            for key, binding in prior_by_key.items()
        }
        source_by_key: dict[str, list[Source]] = {}
        for source in snapshot.sources:
            if source.discovery_key is None or source.discovery_key not in target_by_key:
                prior = prior_by_key.get(source.discovery_key or "")
                if prior is None:
                    blockers.append(
                        f"Source {source.id} has an unknown or unbound Discovery key"
                    )
                elif str(prior.get("site")) != source.site:
                    blockers.append(
                        f"Source {source.id} site does not match its last Watchlist binding"
                    )
                else:
                    source_by_key.setdefault(source.discovery_key or "", []).append(source)
                continue
            target = target_by_key[source.discovery_key]
            if source.site != target.site:
                blockers.append(
                    f"Source {source.id} site does not match Watchlist key {target.key!r}"
                )
                continue
            source_by_key.setdefault(target.key, []).append(source)

        for owned in snapshot.key_sources:
            target = target_by_key.get(owned.source.discovery_key or "")
            if target is None:
                continue
            if owned.work_key != work_key:
                blockers.append(
                    f"Discovery key {target.key!r} is already owned by work {owned.work_key!r}"
                )
            if owned.source.site != target.site:
                blockers.append(
                    f"Discovery key {target.key!r} is attached to unexpected site "
                    f"{owned.source.site!r}"
                )

        has_archive_order = any(target.archive_order is not None for target in targets)
        has_scope = any(target.discovery_scope is not None for target in targets)
        no_previous_binding = snapshot.sync is None
        legacy_bootstrap = (
            no_previous_binding and not has_archive_order and not has_scope
        )

        evidence_by_key = {
            evidence.discovery_key: evidence for evidence in snapshot.inventory_evidence
        }
        flags: dict[int, bool] = {}
        reasons: dict[int, str] = {}
        for key, target in target_by_key.items():
            target_sources = source_by_key.get(key, [])
            prior = prior_by_key.get(key)
            binding_changed = (
                prior is not None and prior_core_by_key.get(key) != current_configuration[key]
            )
            unbound_existing_sources = (
                snapshot.sync is not None and prior is None and bool(target_sources)
            )
            require_full_proof = (
                target.discovery_scope is not None
                or has_archive_order
                or binding_changed
                or unbound_existing_sources
            )
            evidence = evidence_by_key.get(key)
            if (
                not require_full_proof
                and target.discovery_scope is None
                and not has_archive_order
            ):
                for source in target_sources:
                    flags[source.id] = True
                    reasons[source.id] = (
                        "legacy unbounded key assigned as acquisition owner"
                    )
                continue
            if evidence is None:
                if require_full_proof:
                    blockers.append(
                        f"Discovery key {key!r} requires a fresh complete Full listing proof"
                    )
                continue
            expected_fingerprint = target_scope_fingerprint(target)
            if (
                evidence.site != target.site
                or evidence.target_url != target.url
                or evidence.scope_fingerprint != expected_fingerprint
                or not evidence.listing_identity
                or evidence.source_count != len(evidence.positions)
            ):
                blockers.append(
                    f"Discovery key {key!r} Full listing proof does not match current binding"
                )
                continue
            digest_rows = [
                (position.external_id, position.display_position, position.in_scope)
                for position in sorted(
                    evidence.positions,
                    key=lambda item: (item.display_position, item.external_id),
                )
            ]
            actual_digest = hashlib.sha256(
                json.dumps(
                    digest_rows, ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")
            ).hexdigest()
            if evidence.inventory_digest != actual_digest:
                blockers.append(f"Discovery key {key!r} Full listing proof digest is invalid")
                continue
            positions = {position.external_id: position for position in evidence.positions}
            if len(positions) != len(evidence.positions):
                blockers.append(f"Discovery key {key!r} Full listing proof has duplicate identities")
                continue
            catalog_sources = {source.external_id: source for source in target_sources}
            missing_listing = sorted(set(catalog_sources) - set(positions))
            if missing_listing:
                blockers.append(
                    f"Discovery key {key!r} has Catalog Sources missing from Full listing: "
                    + ", ".join(missing_listing[:5])
                )
            missing_catalog = sorted(
                external_id
                for external_id, position in positions.items()
                if position.in_scope and external_id not in catalog_sources
            )
            if missing_catalog:
                blockers.append(
                    f"Discovery key {key!r} has in-scope listing rows missing from Catalog: "
                    + ", ".join(missing_catalog[:5])
                )
            for external_id, source in catalog_sources.items():
                position = positions.get(external_id)
                if position is None:
                    continue
                if source.display_position != position.display_position:
                    blockers.append(
                        f"Source {source.id} position is unresolved or stale for key {key!r}"
                    )
                    continue
                flags[source.id] = position.in_scope
                reasons[source.id] = (
                    "inside Watchlist discovery_scope"
                    if position.in_scope
                    else "outside Watchlist discovery_scope"
                )

        current_keys = set(target_by_key)
        for source in snapshot.sources:
            if source.discovery_key in current_keys or source.id in flags:
                continue
            if source.discovery_key in prior_by_key:
                flags[source.id] = False
                reasons[source.id] = "Watchlist key removed; historical Source retained"
            elif source.id not in flags:
                blockers.append(
                    f"Source {source.id} cannot be assigned because its key is not in the saved binding"
                )

        if legacy_bootstrap and snapshot.sources:
            all_ids = {source.id for source in snapshot.sources}
            if set(flags) != all_ids:
                blockers.append("Legacy bootstrap cannot classify every existing Source")
            if any(not value for value in flags.values()):
                blockers.append("Legacy bootstrap would exclude an existing Source")

        if set(flags) != {source.id for source in snapshot.sources}:
            blockers.append("Scope preview cannot classify every current Catalog Source")

        changes: list[ScopeFlagChange] = []
        for source in snapshot.sources:
            if source.id not in flags:
                continue
            desired = flags[source.id]
            if source.acquisition_enabled != desired:
                changes.append(
                    ScopeFlagChange(
                        source_id=source.id,
                        site=source.site,
                        discovery_key=source.discovery_key or "",
                        external_id=source.external_id,
                        before=source.acquisition_enabled,
                        after=desired,
                        reason=reasons.get(source.id, "Watchlist scope"),
                    )
                )

        archive_order_preview = self._archive_order_preview(
            work_key=work_key,
            targets=targets,
            snapshot=snapshot,
            future_flags=flags,
            blockers=blockers,
        )
        return ScopeSyncPreview(
            work_key=work_key,
            fingerprint=fingerprint,
            definition_fingerprint=definition,
            configuration_json=saved_configuration,
            revision_token=snapshot.revision_token,
            discovery_keys=tuple(sorted(target_by_key)),
            source_flags=tuple(sorted(flags.items())),
            changes=tuple(changes),
            blockers=tuple(dict.fromkeys(blockers)),
            legacy_bootstrap=legacy_bootstrap,
            archive_order_preview=archive_order_preview,
        )

    def _archive_order_preview(
        self,
        *,
        work_key: str,
        targets: list[WatchlistTarget],
        snapshot: AcquisitionScopeSnapshot,
        future_flags: dict[int, bool],
        blockers: list[str],
    ) -> dict[str, Any] | None:
        if not any(target.archive_order is not None for target in targets):
            return None
        result: dict[str, Any] = {
            "ready": False,
            "positions": [],
            "number_changes": [],
            "previous_positions_status": "unknown",
            "existing_archives": [],
            "preserved_excluded_archives": [],
            "blockers": list(dict.fromkeys(blockers)),
        }
        if blockers:
            return result
        works, items, _sources, _source_targets = (
            self.catalog.read_works_items_sources_and_targets()
        )
        work = next((value for value in works if value.work_key == work_key), None)
        if work is None:
            result["blockers"] = ["Catalog Work disappeared while previewing archive order"]
            return result
        items_by_id = {item.id: item for item in items}
        try:
            future = build_work_archive_position_plan(
                work,
                targets,
                items,
                snapshot.sources,
                acquisition_flags=future_flags,
            )
        except ArchiveOrderPlanningError as exc:
            result["blockers"] = [str(exc)]
            return result
        if future is None:
            result["blockers"] = [
                "Archive-order preview could not prove a complete ordered work"
            ]
            return result
        previous_positions: dict[int, int] = {}
        previous_is_known = snapshot.sync is None or snapshot.sync.status == "synced"
        if previous_is_known:
            try:
                prior_targets = self._targets_from_saved_configuration(
                    snapshot.sync.configuration_json
                ) if snapshot.sync is not None else []
                previous = (
                    build_work_archive_position_plan(
                        work,
                        prior_targets,
                        items,
                        snapshot.sources,
                    )
                    if prior_targets
                    else None
                )
                if previous is not None:
                    previous_positions = dict(previous.positions_by_source_id)
                else:
                    previous_positions = {
                        source.id: source.display_position
                        for source in snapshot.sources
                        if source.acquisition_enabled
                        and source.display_position is not None
                    }
            except (ArchiveOrderPlanningError, ValueError):
                previous_is_known = False
                previous_positions = {}
        result["previous_positions_status"] = (
            "known" if previous_is_known else "unknown"
        )
        result["positions"] = [
            {
                "source_id": source_id,
                "archive_position": position,
            }
            for source_id, position in sorted(
                future.positions_by_source_id.items(), key=lambda pair: pair[1]
            )
        ]
        source_by_id = {source.id: source for source in snapshot.sources}
        for source in snapshot.sources:
            before = previous_positions.get(source.id) if previous_is_known else None
            after = future.positions_by_source_id.get(source.id)
            if before != after:
                result["number_changes"].append({
                    "source_id": source.id,
                    "from": before,
                    "to": after,
                    "before_known": previous_is_known,
                })

        archive_rows = self.catalog.read_work_archive_artifacts(work_key)
        by_source: dict[int, list[tuple[int, Any]]] = {}
        for run, artifact in archive_rows:
            by_source.setdefault(run.source_id, []).append((run.id, artifact))
        for source_id, rows in by_source.items():
            latest_run_id = max(run_id for run_id, _artifact in rows)
            latest = [artifact for run_id, artifact in rows if run_id == latest_run_id]
            if len(latest) != 1:
                result["blockers"].append(
                    f"Source {source_id} has ambiguous current ZIP Artifacts"
                )
                continue
            artifact = latest[0]
            source = source_by_id.get(source_id)
            if source is None:
                result["blockers"].append(
                    f"Archive Artifact for unknown Source {source_id} cannot be classified"
                )
                continue
            if not future_flags.get(source_id, False):
                result["preserved_excluded_archives"].append(
                    {
                        "source_id": source_id,
                        "artifact_id": artifact.id,
                        "locator": artifact.locator,
                        "state": artifact.state,
                    }
                )
                continue
            if (
                artifact.storage_backend == "filesystem"
                and artifact.state == "present"
                and artifact.locator is None
            ):
                result["blockers"].append(
                    f"Present filesystem Artifact for Source {source_id} has no locator"
                )
                continue
            path = Path(artifact.locator) if artifact.locator is not None else None
            if path is None or not path.is_file():
                continue
            item = items_by_id.get(source.item_id)
            if item is None:
                result["blockers"].append(
                    f"Source {source_id} has no Item while previewing its archive"
                )
                continue
            expected = future.positions_by_source_id.get(source_id)
            if expected is None:
                result["blockers"].append(
                    f"Enabled Source {source_id} has no work-wide archive position"
                )
                continue
            expected_prefix = f"{expected:03d}-"
            needs_renumber = not path.stem.startswith(expected_prefix)
            result["existing_archives"].append(
                {
                    "source_id": source_id,
                    "artifact_id": artifact.id,
                    "current_name": path.name,
                    "expected_prefix": f"{expected:03d}",
                    "renumber_required": needs_renumber,
                }
            )
        result["blockers"] = list(dict.fromkeys(result["blockers"]))
        result["ready"] = not result["blockers"]
        return result

    @staticmethod
    def _targets_from_saved_configuration(configuration_json: str) -> list[WatchlistTarget]:
        try:
            values = json.loads(configuration_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ArchiveOrderPlanningError(
                "Saved Watchlist configuration is malformed"
            ) from exc
        if not isinstance(values, list):
            raise ArchiveOrderPlanningError("Saved Watchlist configuration is malformed")
        targets: list[WatchlistTarget] = []
        for value in values:
            if not isinstance(value, dict):
                raise ArchiveOrderPlanningError("Saved Watchlist target is malformed")
            scope_value = value.get("discovery_scope")
            if scope_value is None:
                scope = None
            elif isinstance(scope_value, dict):
                scope = DiscoveryScope(
                    from_url=scope_value.get("from_url"),
                    through_url=scope_value.get("through_url"),
                )
            else:
                raise ArchiveOrderPlanningError("Saved Watchlist scope is malformed")
            try:
                targets.append(
                    WatchlistTarget(
                        key=str(value["key"]),
                        work_key=str(value["work_key"]),
                        site=str(value["site"]),
                        url=str(value["url"]),
                        label="",
                        discovery_scope=scope,
                        archive_order=value.get("archive_order"),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ArchiveOrderPlanningError(
                    "Saved Watchlist target is malformed"
                ) from exc
        return targets

    @staticmethod
    def _prior_configuration(
        snapshot: AcquisitionScopeSnapshot, blockers: list[str]
    ) -> list[dict[str, Any]]:
        if snapshot.sync is None:
            return []
        try:
            value = json.loads(snapshot.sync.configuration_json)
        except (TypeError, json.JSONDecodeError):
            blockers.append("Saved Watchlist binding metadata is malformed")
            return []
        if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
            blockers.append("Saved Watchlist binding metadata has an invalid shape")
            return []
        return value

    @staticmethod
    def _merge_configuration_history(
        current_configuration_json: str, prior: list[dict[str, Any]]
    ) -> str:
        """Retain removed key bindings so re-adding the same URL is identifiable.

        The work fingerprint still describes only the current Watchlist. This
        stored history is solely a safety binding: changing a removed key's URL
        later still requires fresh Full listing evidence.
        """
        try:
            current = json.loads(current_configuration_json)
        except json.JSONDecodeError:
            current = []
        by_key = {
            str(row.get("key")): row
            for row in prior
            if isinstance(row.get("key"), str)
        }
        for row in current:
            if isinstance(row, dict) and isinstance(row.get("key"), str):
                by_key[row["key"]] = row
        return json.dumps(
            [by_key[key] for key in sorted(by_key)],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _blocked(work_key: str, reason: str) -> ScopeSyncPreview:
        return ScopeSyncPreview(
            work_key=work_key,
            fingerprint="",
            definition_fingerprint="",
            configuration_json="[]",
            revision_token=None,
            discovery_keys=(),
            source_flags=(),
            changes=(),
            blockers=(reason,),
        )
