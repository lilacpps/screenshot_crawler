"""Read-only inspection of existing archive names and status sidecars.

Batch only protects the output it is about to create.  Historical archive
inspection belongs to this maintenance module so it can be run explicitly
when an operator wants to review old names or sidecars.
"""

from __future__ import annotations

import json
import os
import stat
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from screenshot_crawler.archive_order import build_work_archive_position_plan
from screenshot_crawler.batch.naming import catalog_archive_stem, collision_source_ids
from screenshot_crawler.catalog import (
    Artifact,
    CatalogError,
    CatalogService,
    CrawlRun,
    Item,
    Source,
    Work,
)
from screenshot_crawler.core.packaging import safe_component
from screenshot_crawler.watchlist.reconcile import ScopeReconciler, ScopeReconciliationError
from screenshot_crawler.watchlist.service import WatchlistService


class ArchiveNameGuardError(ValueError):
    """Raised when current Catalog ownership is insufficient for an audit."""


class ArchiveAuditUsageError(ValueError):
    """Raised when an audit selector is missing, ambiguous, or unknown."""


@dataclass(frozen=True, slots=True)
class ArchiveAuditReport:
    """Machine-readable result of a read-only archive audit."""

    work_keys: tuple[str, ...]
    findings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "work_keys": list(self.work_keys),
            "findings": list(self.findings),
            "errors": list(self.errors),
            "summary": {
                "works": len(self.work_keys),
                "findings": len(self.findings),
                "errors": len(self.errors),
            },
        }


def inspect_existing_archive_names(
    catalog: CatalogService,
    *,
    work: Work,
    items: list[Item],
    sources: list[Source],
    archive_positions_by_source: dict[int, int],
) -> list[str]:
    """Return historical archive/status findings for one complete Work."""

    items_by_id = {item.id: item for item in items}
    rows_by_source: dict[int, list[tuple[CrawlRun, Artifact]]] = defaultdict(list)
    for run, artifact in catalog.read_work_archive_artifacts(work.work_key):
        rows_by_source[run.source_id].append((run, artifact))

    sources_by_site: dict[str, list[Source]] = defaultdict(list)
    for source in sources:
        sources_by_site[source.site].append(source)
    collision_ids: set[int] = set()
    for site_sources in sources_by_site.values():
        collision_ids.update(collision_source_ids([work], items, site_sources))

    findings: list[str] = []
    for source in sources:
        if not source.acquisition_enabled:
            continue
        item = items_by_id.get(source.item_id)
        if item is None or item.work_id != work.id:
            raise ArchiveNameGuardError(
                f"Source {source.id} has unknown Work/Item ownership"
            )
        source_context = f"work={work.work_key!r} source={source.id}"
        current, ambiguous = _latest_archive(rows_by_source.get(source.id, []))
        if ambiguous:
            findings.append(
                f"{source_context}: latest CrawlRun has multiple current ZIP Artifacts; "
                "review archive history separately"
            )
            continue
        if current is None:
            continue
        _run, artifact = current
        if (
            artifact.storage_backend == "filesystem"
            and artifact.state == "present"
            and artifact.locator is None
        ):
            findings.append(
                f"{source_context}: current archive is marked present but has no "
                "filesystem locator; review archive history separately"
            )
            continue
        if artifact.storage_backend != "filesystem" or artifact.locator is None:
            if artifact.state == "present":
                findings.append(
                    f"{source_context}: current archive is marked present but cannot be "
                    "checked as a filesystem path; review archive history separately"
                )
            continue
        try:
            old_path = Path(artifact.locator)
            old_stat = old_path.stat()
        except (FileNotFoundError, NotADirectoryError):
            continue
        except (OSError, ValueError) as exc:
            findings.append(
                f"{source_context}: existing archive locator cannot be inspected "
                f"({type(exc).__name__}); review archive history separately"
            )
            continue
        if not stat.S_ISREG(old_stat.st_mode):
            findings.append(
                f"{source_context}: current archive locator is not a regular file; "
                "review archive history separately"
            )
            continue
        expected_stem = catalog_archive_stem(
            work,
            item,
            source,
            archive_position=archive_positions_by_source.get(
                source.id, source.display_position
            ),
            artifact_disambiguator=(
                f"{source.site}-{source.external_id}"
                if source.id in collision_ids
                else None
            ),
        )
        if old_path.stem != expected_stem:
            findings.append(
                f"{source_context}: existing archive {old_path.name!r} differs from the "
                f"current expected name {expected_stem + '.zip'!r}; renumbering is "
                "separate maintenance"
            )
        findings.extend(_matching_status_warnings(old_path, work, source_context))
    return findings


def audit_existing_archives(
    catalog: CatalogService,
    *,
    work_key: str | None = None,
    site: str | None = None,
    all_sources: bool = False,
    watchlist: WatchlistService,
) -> ArchiveAuditReport:
    """Audit an explicit scope, including all sites for selected Works."""

    if sum((work_key is not None, site is not None, all_sources)) != 1:
        raise ArchiveAuditUsageError(
            "select exactly one scope with --work-key, --site, or --all"
        )
    if not catalog.path.is_file():
        raise CatalogError(f"Catalog file not found: {catalog.path}")
    if not watchlist.path.is_file():
        raise CatalogError(f"Watchlist file not found: {watchlist.path}")
    works, items, sources, _targets = catalog.read_works_items_sources_and_targets()
    targets_by_work = defaultdict(list)
    for target in watchlist.list_targets():
        targets_by_work[target.work_key].append(target)
    items_by_id = {item.id: item for item in items}
    items_by_work: dict[int, list[Item]] = defaultdict(list)
    for item in items:
        items_by_work[item.work_id].append(item)
    sources_by_work: dict[int, list[Source]] = defaultdict(list)
    for source in sources:
        item = items_by_id.get(source.item_id)
        if item is not None:
            sources_by_work[item.work_id].append(source)

    if work_key is not None and not any(work.work_key == work_key for work in works):
        raise ArchiveAuditUsageError(f"unknown work key: {work_key!r}")
    site_values = {source.site for source in sources}
    if site is not None and site not in site_values:
        raise ArchiveAuditUsageError(f"unknown site: {site!r}")

    selected: list[Work] = []
    for work in works:
        work_sources = sources_by_work.get(work.id, [])
        if all_sources or (
            (work_key is None or work.work_key == work_key)
            and (site is None or any(source.site == site for source in work_sources))
        ):
            selected.append(work)
    findings: list[str] = []
    errors: list[str] = []
    for work in selected:
        work_items = items_by_work.get(work.id, [])
        work_sources = sources_by_work.get(work.id, [])
        positions: dict[int, int] = {
            source.id: source.display_position
            for source in work_sources
            if source.display_position is not None
        }
        try:
            targets = targets_by_work.get(work.work_key, [])
            snapshot = catalog.read_acquisition_scope_snapshot(work.work_key)
            managed = any(
                target.archive_order is not None or target.discovery_scope is not None
                for target in targets
            ) or (snapshot is not None and (
                snapshot.sync is not None or bool(snapshot.inventory_evidence)
                or any(not source.acquisition_enabled for source in snapshot.sources)
            ))
            if managed:
                validated = ScopeReconciler(watchlist, catalog).require_synchronized_snapshot(
                    work.work_key
                )
                if {row.id: row for row in validated.sources} != {
                    row.id: row for row in work_sources
                }:
                    raise ArchiveNameGuardError("Catalog Sources changed during audit; retry")
            if targets:
                position_plan = build_work_archive_position_plan(
                    work, targets, work_items, work_sources
                )
                if position_plan is not None:
                    positions.update(position_plan.positions_by_source_id)
            findings.extend(
                inspect_existing_archive_names(
                    catalog,
                    work=work,
                    items=work_items,
                    sources=work_sources,
                    archive_positions_by_source=positions,
                )
            )
        except (CatalogError, ScopeReconciliationError, OSError, ValueError) as exc:
            errors.append(f"work={work.work_key!r}: {exc}")
    return ArchiveAuditReport(tuple(work.work_key for work in selected), tuple(findings), tuple(errors))


def _latest_archive(
    rows: list[tuple[CrawlRun, Artifact]],
) -> tuple[tuple[CrawlRun, Artifact] | None, bool]:
    if not rows:
        return None, False
    latest_run_id = max(run.id for run, _artifact in rows)
    latest = [(run, artifact) for run, artifact in rows if run.id == latest_run_id]
    if len(latest) != 1:
        return None, True
    return latest[0], False


def _matching_status_warnings(
    archive_path: Path, work: Work, source_context: str
) -> list[str]:
    if len(archive_path.parents) < 3:
        return []
    library_root = archive_path.parents[2]
    status_root = library_root.parent / "crawl-status"
    genre = safe_component(work.genre, fallback="小説")
    title = safe_component(work.title, fallback="unknown-title")
    candidates = (
        status_root / genre / title / f"{archive_path.stem}.json",
        status_root / f"{archive_path.stem}.json",
    )
    findings: list[str] = []
    for status_path in candidates:
        try:
            status_path.stat()
        except (FileNotFoundError, NotADirectoryError):
            continue
        except (OSError, ValueError) as exc:
            findings.append(
                f"{source_context}: existing status path cannot be inspected "
                f"({type(exc).__name__}); status repair is separate maintenance"
            )
            continue
        try:
            payload = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            findings.append(
                f"{source_context}: existing status {status_path} is unreadable; "
                "status repair is separate maintenance"
            )
            continue
        if not isinstance(payload, dict) or not _same_path(
            payload.get("archive_path"), archive_path
        ):
            findings.append(
                f"{source_context}: existing status {status_path} does not match "
                f"archive {archive_path}; status repair is separate maintenance"
            )
    return findings


def _same_path(value: object, expected: Path) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        actual = os.path.normcase(os.path.abspath(os.fspath(Path(value))))
        target = os.path.normcase(os.path.abspath(os.fspath(expected)))
    except (TypeError, ValueError, OSError):
        return False
    return actual == target
