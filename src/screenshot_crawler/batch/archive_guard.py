"""Protect the exact ZIP/status paths about to be written by Batch."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from screenshot_crawler.catalog import (
    CatalogService,
    CrawlRun,
    Item,
    Source,
    SourceTarget,
    Work,
)


class ArchiveHistoryWarning(UserWarning):
    """The planned output reuses a proven stale same-Source status sidecar."""


class CandidateOutputPathError(ValueError):
    """A planned ZIP/status output is occupied by data without safe ownership proof."""


@dataclass(frozen=True, slots=True)
class _StatusFileFingerprint:
    sha256: str
    stat_signature: tuple[int, int, int, int, int, int]


@dataclass(frozen=True, slots=True)
class CandidateOutputPreflight:
    """Output-path state captured before site access for final package recheck."""

    archive_path: Path
    status_path: Path
    stale_status: _StatusFileFingerprint | None


_BATCH_OUTPUT_NAME = re.compile(
    r"^item-(?P<item_id>[0-9]+)-source-(?P<source_id>[0-9]+)-"
    r"(?P<started_at>[0-9]{8}T[0-9]{12}[+-][0-9]{4})-"
    r"(?P<run_nonce>[0-9a-f]{32})$"
)


def validate_candidate_output_paths(
    catalog: CatalogService,
    *,
    work: Work,
    item: Item,
    source: Source,
    target: SourceTarget,
    archive_path: Path,
    status_path: Path,
    baseline: CandidateOutputPreflight | None = None,
) -> CandidateOutputPreflight:
    """Check planned output paths, allowing only a proven stale same-source status.

    The ZIP path is always exclusive. A completed status can be replaced only
    when its embedded source-output identity and successful Catalog history (or
    unambiguous legacy Artifact locators) prove that it belongs to this Item and
    Source. The current target is checked separately. The returned fingerprint
    lets Executor reject a sidecar changed while the crawl was in progress.
    """

    archive_path = Path(archive_path)
    status_path = Path(status_path)
    if baseline is not None and (
        _normalized_path(archive_path) != _normalized_path(baseline.archive_path)
        or _normalized_path(status_path) != _normalized_path(baseline.status_path)
    ):
        raise CandidateOutputPathError(
            "Candidate output paths changed between preflight and packaging"
        )

    if item.work_id != work.id or source.item_id != item.id or target.source_id != source.id:
        raise CandidateOutputPathError(
            "Catalog Item/Source/Target identity is inconsistent for candidate output"
        )

    if _output_path_exists(archive_path):
        raise CandidateOutputPathError(
            f"Candidate output already exists at archive {archive_path}; "
            "Batch will not overwrite it"
        )
    if not _output_path_exists(status_path):
        return CandidateOutputPreflight(archive_path, status_path, None)

    status_bytes, fingerprint = _read_status_file(status_path)
    if baseline is not None:
        if baseline.stale_status is None:
            raise CandidateOutputPathError(
                f"Candidate output already exists as status at {status_path}; "
                "Batch will not overwrite it"
            )
        if fingerprint != baseline.stale_status:
            raise CandidateOutputPathError(
                f"Candidate output status changed during crawl at {status_path}; "
                "Batch will not overwrite it"
            )

    _validate_same_source_status(
        catalog,
        status_bytes,
        work=work,
        item=item,
        source=source,
        target=target,
        archive_path=archive_path,
    )
    return CandidateOutputPreflight(archive_path, status_path, fingerprint)


def _validate_same_source_status(
    catalog: CatalogService,
    payload_bytes: bytes,
    *,
    work: Work,
    item: Item,
    source: Source,
    target: SourceTarget,
    archive_path: Path,
) -> None:
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateOutputPathError(
            f"Candidate output already exists as unreadable status for {archive_path}; "
            "refusing overwrite"
        ) from exc
    if not isinstance(payload, dict):
        raise CandidateOutputPathError(
            "Candidate output status already exists but is not a JSON object"
        )
    if payload.get("status") != "completed" or not _same_path(
        payload.get("archive_path"), archive_path
    ):
        raise CandidateOutputPathError(
            f"Candidate output status already exists but does not identify the "
            f"missing planned archive {archive_path}"
        )
    page_count = payload.get("page_count")
    if isinstance(page_count, bool) or not isinstance(page_count, int) or page_count < 0:
        raise CandidateOutputPathError(
            "Candidate output status already exists with an invalid page_count"
        )

    source_output_dir = payload.get("source_output_dir")
    token = _parse_batch_output_identity(source_output_dir)

    if token is None:
        locator_references = _archive_references_at_path(catalog, archive_path)
        if not locator_references:
            raise CandidateOutputPathError(
                "Candidate status has no structured source identity or unique Catalog archive history"
            )
        _require_unambiguous_locator_ownership(
            catalog,
            locator_references,
            item=item,
            source=source,
        )
        return

    expected_site_component = _safe_site_component(source.site)
    if (
        token["item_id"] != item.id
        or token["source_id"] != source.id
        or token["site_component"] != expected_site_component
    ):
        raise CandidateOutputPathError(
            "Candidate status source-output identity belongs to a different Item/Source/site"
        )

    matching_runs = [
        run
        for run in catalog.list_crawl_runs(
            item_id=item.id,
            source_id=source.id,
            status="succeeded",
        )
        if _run_matches_source(run, item=item, source=source)
        and _run_output_timestamp(run.started_at) == token["started_at"]
    ]
    if not matching_runs:
        raise CandidateOutputPathError(
            "Candidate status source-output timestamp has no successful Catalog run"
        )
    has_zip_artifact_proof = any(
        any(
            artifact.item_id == item.id
            and artifact.kind == "archive"
            and artifact.format == "zip"
            for artifact in catalog.list_artifacts(crawl_run_id=run.id)
        )
        for run in matching_runs
    )
    if not has_zip_artifact_proof:
        raise CandidateOutputPathError(
            "Candidate status source-output identity has no ZIP Artifact history"
        )


def _parse_batch_output_identity(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise CandidateOutputPathError("Candidate status has an invalid source_output_dir")
    parts = Path(value).parts
    if not parts:
        raise CandidateOutputPathError("Candidate status has an invalid source_output_dir")
    basename = parts[-1]
    match = _BATCH_OUTPUT_NAME.fullmatch(basename)
    if match is None:
        if basename.startswith("item-") and "-source-" in basename:
            raise CandidateOutputPathError(
                "Candidate status has a malformed structured source-output identity"
            )
        return None
    if len(parts) < 2:
        raise CandidateOutputPathError(
            "Candidate status has a structured source-output identity without its site directory"
        )
    return {
        "site_component": parts[-2],
        "item_id": int(match.group("item_id")),
        "source_id": int(match.group("source_id")),
        "started_at": match.group("started_at"),
    }


def _run_output_timestamp(value: str) -> str | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.strftime("%Y%m%dT%H%M%S%f%z")


def _run_matches_source(
    run: CrawlRun,
    *,
    item: Item,
    source: Source,
) -> bool:
    # CrawlRun.external_id_snapshot is an immutable historical record.  Once
    # the Source identity is explicitly updated, source_id/item_id/site remain
    # the authoritative ownership proof for that historical run.
    return (
        run.status == "succeeded"
        and run.item_id == item.id
        and run.source_id == source.id
        and run.site_snapshot == source.site
    )


def _archive_references_at_path(catalog: CatalogService, archive_path: Path):
    return tuple(
        artifact
        for artifact in catalog.read_all_archive_references()
        if artifact.storage_backend == "filesystem"
        and artifact.locator is not None
        and _same_path(artifact.locator, archive_path)
    )


def _require_unambiguous_locator_ownership(
    catalog: CatalogService,
    references,
    *,
    item: Item,
    source: Source,
) -> None:
    runs = {run.id: run for run in catalog.list_crawl_runs()}
    for artifact in references:
        run = runs.get(artifact.crawl_run_id) if artifact.crawl_run_id is not None else None
        if (
            artifact.item_id != item.id
            or run is None
            or not _run_matches_source(run, item=item, source=source)
        ):
            raise CandidateOutputPathError(
                "Planned archive path is referenced by a different or ambiguous Catalog history"
            )


def _safe_site_component(site: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", site).strip(" .")
    return safe or "site"


def _normalized_path(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _read_status_file(path: Path) -> tuple[bytes, _StatusFileFingerprint]:
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode):
            raise CandidateOutputPathError(
                f"Candidate status path is not a regular file: {path}"
            )
        content = path.read_bytes()
        after = path.lstat()
    except CandidateOutputPathError:
        raise
    except OSError as exc:
        raise CandidateOutputPathError(
            f"Candidate status cannot be safely read at {path}: {type(exc).__name__}"
        ) from exc
    if _stat_signature(before) != _stat_signature(after):
        raise CandidateOutputPathError(
            f"Candidate status changed while being read at {path}"
        )
    return content, _StatusFileFingerprint(
        hashlib.sha256(content).hexdigest(), _stat_signature(after)
    )


def _output_path_exists(path: Path) -> bool:
    """Treat only a missing leaf as free; unknown output state fails closed."""

    try:
        path.lstat()
    except FileNotFoundError:
        parent = path.parent
        while True:
            try:
                parent_stat = parent.stat()
            except FileNotFoundError:
                if parent == parent.parent:
                    return False
                parent = parent.parent
                continue
            except OSError as exc:
                raise CandidateOutputPathError(
                    f"Candidate output state cannot be checked at {path}: "
                    f"{type(exc).__name__}"
                ) from exc
            if not stat.S_ISDIR(parent_stat.st_mode):
                raise CandidateOutputPathError(
                    f"Candidate output parent is not a directory: {parent}"
                )
            return False
    except OSError as exc:
        raise CandidateOutputPathError(
            f"Candidate output state cannot be checked at {path}: {type(exc).__name__}"
        ) from exc
    return True


def _stat_signature(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(stat.S_IFMT(value.st_mode)),
        int(value.st_size),
        int(value.st_mtime_ns),
        int(value.st_ctime_ns),
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
