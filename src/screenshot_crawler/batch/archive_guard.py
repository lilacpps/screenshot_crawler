"""Inspect historical archive naming/status state without blocking Batch output."""

from __future__ import annotations

import json
import os
import stat
from collections import defaultdict
from pathlib import Path

from screenshot_crawler.batch.naming import catalog_archive_stem, collision_source_ids
from screenshot_crawler.catalog import Artifact, CatalogService, CrawlRun, Item, Source, Work
from screenshot_crawler.core.packaging import safe_component


class ArchiveNameGuardError(ValueError):
    """Raised when current Catalog ownership is insufficient for safe inspection."""


class ArchiveHistoryWarning(UserWarning):
    """A historical archive name or sidecar needs separate maintenance review."""


def inspect_existing_archive_names(
    catalog: CatalogService,
    *,
    work: Work,
    items: list[Item],
    sources: list[Source],
    archive_positions_by_source: dict[int, int],
) -> list[str]:
    """Return maintenance warnings for existing artifacts in a work.

    Existing paths and sidecars are historical records. Their naming or status
    disagreement is reported for separate maintenance, while current ownership
    ambiguity remains an error. Planned output-path occupancy is checked by the
    Planner and Executor independently.
    """

    items_by_id = {item.id: item for item in items}
    rows_by_source: dict[int, list[tuple[CrawlRun, Artifact]]] = defaultdict(list)
    for run, artifact in catalog.read_work_archive_artifacts(work.work_key):
        rows_by_source[run.source_id].append((run, artifact))

    sources_by_site: dict[str, list[Source]] = defaultdict(list)
    warnings: list[str] = []
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
        source_context = f"work={work.work_key!r} source={source.id}"
        current, ambiguous = _latest_archive(rows_by_source.get(source.id, []))
        if ambiguous:
            warnings.append(
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
            warnings.append(
                f"{source_context}: current archive is marked present but has no "
                "filesystem locator; review archive history separately"
            )
            continue
        if artifact.storage_backend != "filesystem" or artifact.locator is None:
            if artifact.state == "present":
                warnings.append(
                    f"{source_context}: current archive is marked present but cannot be "
                    "checked as a filesystem path; review archive history separately"
                )
            continue
        try:
            old_path = Path(artifact.locator)
            old_stat = old_path.stat()
        except (FileNotFoundError, NotADirectoryError):
            # A missing file is a valid operator-controlled recrawl case.
            continue
        except (OSError, ValueError) as exc:
            warnings.append(
                f"{source_context}: existing archive locator cannot be inspected "
                f"({type(exc).__name__}); review archive history separately"
            )
            continue
        if not stat.S_ISREG(old_stat.st_mode):
            warnings.append(
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
            warnings.append(
                f"{source_context}: existing archive {old_path.name!r} differs from the "
                f"current expected name {expected_stem + '.zip'!r}; renumbering is "
                "separate maintenance and Batch may continue when its output path is free"
            )
        warnings.extend(_matching_status_warnings(old_path, work, source_context))

    return warnings


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
    warnings: list[str] = []
    for status_path in candidates:
        try:
            status_path.stat()
        except (FileNotFoundError, NotADirectoryError):
            continue
        except (OSError, ValueError) as exc:
            warnings.append(
                f"{source_context}: existing status path cannot be inspected "
                f"({type(exc).__name__}); status repair is separate maintenance"
            )
            continue
        try:
            payload = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            warnings.append(
                f"{source_context}: existing status {status_path} is unreadable; "
                "status repair is separate maintenance"
            )
            continue
        if not isinstance(payload, dict) or not _same_path(
            payload.get("archive_path"), archive_path
        ):
            warnings.append(
                f"{source_context}: existing status {status_path} does not match "
                f"archive {archive_path}; status repair is separate maintenance"
            )
    return warnings


def _same_path(value: object, expected: Path) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        actual = os.path.normcase(os.path.abspath(os.fspath(Path(value))))
        target = os.path.normcase(os.path.abspath(os.fspath(expected)))
    except (TypeError, ValueError, OSError):
        return False
    return actual == target
