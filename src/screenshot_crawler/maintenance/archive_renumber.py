"""Preflighted, reversible renaming of existing position-aware archives."""

from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from screenshot_crawler.batch.naming import catalog_archive_stem, collision_source_ids
from screenshot_crawler.catalog import (
    Artifact,
    CatalogService,
    CrawlRun,
    Item,
    Source,
    Work,
)
from screenshot_crawler.core.progress import atomic_write_json


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


@dataclass(slots=True)
class ArchiveRenumberPlan:
    """Complete, already-preflighted plan for one explicit scope."""

    entries: list[RenumberEntry]
    catalog: CatalogService
    status_dir: Path
    work_key: str | None = None
    site: str | None = None
    all_sources: bool = False

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
        counts.setdefault("errors", 0)
        return counts


@dataclass(frozen=True, slots=True)
class ArchiveRenumberResult:
    """Mutation result.  Errors always imply a non-zero CLI exit code."""

    renamed: int = 0
    status_updated: int = 0
    error: str | None = None
    recovery_required: bool = False
    recovery_details: tuple[str, ...] = ()


def build_archive_renumber_plan(
    catalog: CatalogService,
    *,
    work_key: str | None = None,
    site: str | None = None,
    all_sources: bool = False,
    status_dir: str | Path = "output/crawl-status",
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
        )
        entries.append(entry)

    _preflight_collisions(entries)
    return ArchiveRenumberPlan(
        entries=entries,
        catalog=catalog,
        status_dir=status_root,
        work_key=work_key,
        site=site,
        all_sources=all_sources,
    )


def apply_archive_renumber_plan(plan: ArchiveRenumberPlan) -> ArchiveRenumberResult:
    """Apply a plan after a final fail-closed filesystem recheck."""

    entries = plan.executable_entries
    if not entries:
        return ArchiveRenumberResult()
    try:
        _recheck_before_mutation(entries)
    except ArchiveRenumberPreflightError as exc:
        return ArchiveRenumberResult(error=f"ERROR {exc}")

    catalog_update_attempted = False
    try:
        for entry in entries:
            assert entry.old_path is not None
            assert entry.temporary_path is not None
            entry.old_path.rename(entry.temporary_path)
            entry.zip_stage1_done = True
        for entry in entries:
            assert entry.temporary_path is not None
            assert entry.new_path is not None
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
            entry.status_path.rename(entry.status_temporary_path)
            entry.status_stage1_done = True
        for entry in status_entries:
            assert entry.status_temporary_path is not None
            assert entry.new_status_path is not None
            entry.status_temporary_path.rename(entry.new_status_path)
            entry.status_final_done = True
            assert entry.status_payload is not None
            assert entry.new_path is not None
            entry.status_payload["archive_path"] = entry.new_path.as_posix()
            atomic_write_json(entry.new_status_path, entry.status_payload)
            entry.status_updated = True

        assignments = {
            entry.artifact.id: (entry.artifact.locator, entry.new_path.as_posix())
            for entry in entries
            if entry.artifact is not None
            and entry.old_path is not None
            and entry.new_path is not None
        }
        catalog_update_attempted = True
        plan.catalog.update_artifact_locators(assignments)
    except Exception as exc:  # noqa: BLE001 - fail-safe rollback for mutation errors
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
) -> RenumberEntry:
    if source.display_position is None:
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
    )
    if entry.status == "RENAME":
        entry.temporary_path = _temporary_sibling(old_path, artifact.id, "renumber")
        _inspect_status_candidate(entry, status_dir)
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


def _inspect_status_candidate(entry: RenumberEntry, status_dir: Path) -> None:
    assert entry.old_path is not None
    assert entry.new_path is not None
    candidate = status_dir / f"{entry.old_path.stem}.json"
    new_candidate = status_dir / f"{entry.new_path.stem}.json"
    entry.new_status_path = new_candidate
    if not candidate.is_file():
        entry.status_warning = "STATUS_MISSING"
        return
    payload = _read_matching_status(candidate, entry.old_path)
    if payload is None:
        entry.status_warning = "STATUS_MISMATCH"
        return
    entry.status_path = candidate
    entry.status_payload = payload
    entry.status_temporary_path = _temporary_sibling(candidate, entry.artifact.id, "renumber")  # type: ignore[union-attr]


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
    try:
        zip_states = [entry for entry in entries if entry.zip_stage1_done or entry.zip_final_done]
        for entry in zip_states:
            current = entry.new_path if entry.zip_final_done else entry.temporary_path
            assert current is not None
            rollback_path = _temporary_sibling(current, entry.artifact.id, "rollback")  # type: ignore[union-attr]
            if rollback_path.exists():
                raise OSError(f"rollback temporary path exists: {rollback_path}")
            if not current.exists():
                raise OSError(f"rollback current path is missing: {current}")
            current.rename(rollback_path)
            entry.temporary_path = rollback_path
        for entry in zip_states:
            assert entry.old_path is not None
            assert entry.temporary_path is not None
            entry.temporary_path.rename(entry.old_path)

        status_states = [
            entry
            for entry in entries
            if entry.status_stage1_done or entry.status_final_done
        ]
        for entry in status_states:
            current = entry.new_status_path if entry.status_final_done else entry.status_temporary_path
            assert current is not None
            rollback_path = _temporary_sibling(current, entry.artifact.id, "status-rollback")  # type: ignore[union-attr]
            if rollback_path.exists():
                raise OSError(f"status rollback temporary path exists: {rollback_path}")
            if not current.exists():
                raise OSError(f"status rollback current path is missing: {current}")
            current.rename(rollback_path)
            entry.status_temporary_path = rollback_path
        for entry in status_states:
            assert entry.status_path is not None
            assert entry.status_temporary_path is not None
            entry.status_temporary_path.rename(entry.status_path)
            if entry.status_original_bytes is not None:
                entry.status_path.write_bytes(entry.status_original_bytes)
    except (AssertionError, OSError, RuntimeError, TypeError, ValueError) as exc:
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
    return path.with_name(f".{path.name}.{kind}-{artifact_id}.tmp")


def _path_key(path: Path | None) -> str:
    if path is None:
        return "<none>"
    return os.path.normcase(os.path.abspath(os.fspath(path)))
