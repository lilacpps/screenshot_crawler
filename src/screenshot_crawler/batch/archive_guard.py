"""Fail-closed checks for current work-wide archive names and status records."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path

from screenshot_crawler.batch.naming import catalog_archive_stem, collision_source_ids
from screenshot_crawler.catalog import Artifact, CatalogService, CrawlRun, Item, Source, Work
from screenshot_crawler.core.packaging import safe_component


class ArchiveNameGuardError(ValueError):
    """Raised when an existing current archive disagrees with its naming plan."""


def validate_existing_archive_names(
    catalog: CatalogService,
    *,
    work: Work,
    items: list[Item],
    sources: list[Source],
    archive_positions_by_source: dict[int, int],
) -> None:
    """Check every active Source in a Work across sites before site access."""

    items_by_id = {item.id: item for item in items}
    rows_by_source: dict[int, list[tuple[CrawlRun, Artifact]]] = defaultdict(list)
    for run, artifact in catalog.read_work_archive_artifacts(work.work_key):
        rows_by_source[run.source_id].append((run, artifact))

    sources_by_site: dict[str, list[Source]] = defaultdict(list)
    for source in sources:
        sources_by_site[source.site].append(source)
    collision_ids = set().union(
        *(
            collision_source_ids([work], items, site_sources)
            for site_sources in sources_by_site.values()
        )
    ) if sources_by_site else set()

    for source in sources:
        if not source.acquisition_enabled:
            continue
        item = items_by_id.get(source.item_id)
        if item is None or item.work_id != work.id:
            raise ArchiveNameGuardError(
                f"Source {source.id} has unknown Work/Item ownership"
            )
        current = _latest_archive(rows_by_source.get(source.id, []))
        if current is None:
            continue
        _run, artifact = current
        if (
            artifact.storage_backend == "filesystem"
            and artifact.state == "present"
            and artifact.locator is None
        ):
            raise ArchiveNameGuardError(
                f"Current archive for Source {source.id} is marked present but has no "
                "filesystem locator"
            )
        if artifact.storage_backend != "filesystem" or artifact.locator is None:
            continue
        old_path = Path(artifact.locator)
        if not old_path.is_file():
            # A missing file is a valid operator-controlled recrawl case.
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
            raise ArchiveNameGuardError(
                f"Source {source.id} has existing archive {old_path.name!r}, but the current "
                f"work-wide naming plan requires {expected_stem + '.zip'!r}; run a full "
                "work-wide renumber dry-run and resolve it before Batch"
            )
        _validate_matching_status(old_path, work)


def _latest_archive(
    rows: list[tuple[CrawlRun, Artifact]],
) -> tuple[CrawlRun, Artifact] | None:
    if not rows:
        return None
    latest_run_id = max(run.id for run, _artifact in rows)
    latest = [(run, artifact) for run, artifact in rows if run.id == latest_run_id]
    if len(latest) != 1:
        raise ArchiveNameGuardError(
            f"CrawlRun {latest_run_id} has multiple current ZIP Artifacts; resolve ambiguity"
        )
    return latest[0]


def _validate_matching_status(archive_path: Path, work: Work) -> None:
    if len(archive_path.parents) < 3:
        return
    library_root = archive_path.parents[2]
    status_root = library_root.parent / "crawl-status"
    genre = safe_component(work.genre, fallback="小説")
    title = safe_component(work.title, fallback="unknown-title")
    candidates = (
        status_root / genre / title / f"{archive_path.stem}.json",
        status_root / f"{archive_path.stem}.json",
    )
    for status_path in candidates:
        if not status_path.exists():
            continue
        try:
            payload = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ArchiveNameGuardError(
                f"Current archive status {status_path} is unreadable"
            ) from exc
        if not isinstance(payload, dict) or not _same_path(
            payload.get("archive_path"), archive_path
        ):
            raise ArchiveNameGuardError(
                f"Current archive status {status_path} does not match {archive_path}"
            )


def _same_path(value: object, expected: Path) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        actual = os.path.normcase(os.path.abspath(os.fspath(Path(value))))
        target = os.path.normcase(os.path.abspath(os.fspath(expected)))
    except (TypeError, ValueError, OSError):
        return False
    return actual == target
