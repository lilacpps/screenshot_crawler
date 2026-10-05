"""Inspect completed Catalog archives and optionally prepare safe re-crawls.

The scan is deliberately Catalog-driven: Discovery is never called, and the
selected current archive is the newest successful archive artifact for the
selected source.  Applying a result only moves an existing archive into the
backup tree, updates that artifact, and returns the Item to ``pending``.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import zipfile
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath

from screenshot_crawler.catalog import Artifact, CatalogService, CrawlRun, Item, Source, Work
from screenshot_crawler.catalog.service import now_jst


class ArchiveClassification(StrEnum):
    """Site-neutral archive health classifications."""

    PREFERRED_ONLY = "PREFERRED_ONLY"
    FALLBACK_INCLUDED = "FALLBACK_INCLUDED"
    UNEXPECTED_FORMAT = "UNEXPECTED_FORMAT"
    BROKEN = "BROKEN"
    MISSING = "MISSING"
    AMBIGUOUS_ARTIFACT = "AMBIGUOUS_ARTIFACT"


# Short aliases make the public constants convenient for callers and tests
# without introducing site-specific classification names.
PREFERRED_ONLY = ArchiveClassification.PREFERRED_ONLY
FALLBACK_INCLUDED = ArchiveClassification.FALLBACK_INCLUDED
UNEXPECTED_FORMAT = ArchiveClassification.UNEXPECTED_FORMAT
BROKEN = ArchiveClassification.BROKEN
MISSING = ArchiveClassification.MISSING
AMBIGUOUS_ARTIFACT = ArchiveClassification.AMBIGUOUS_ARTIFACT


def _normalize_extension(value: str) -> str:
    extension = value.lower().strip()
    return extension if extension.startswith(".") else f".{extension}"


@dataclass(frozen=True, slots=True)
class ArchivePolicy:
    """The preferred and known fallback page formats for one site."""

    preferred_extensions: frozenset[str]
    fallback_extensions: frozenset[str]

    def __post_init__(self) -> None:
        preferred = frozenset(_normalize_extension(value) for value in self.preferred_extensions)
        fallback = frozenset(_normalize_extension(value) for value in self.fallback_extensions)
        if preferred & fallback:
            raise ValueError("preferred and fallback extensions must be disjoint")
        object.__setattr__(self, "preferred_extensions", preferred)
        object.__setattr__(self, "fallback_extensions", fallback)


# These are the only policies backed by the current production capture
# implementations and their site notes.  New sites must be added explicitly;
# an unknown site is never treated as JPEG or any other guessed default.
SITE_ARCHIVE_POLICIES: dict[str, ArchivePolicy] = {
    "comicdays": ArchivePolicy(
        preferred_extensions=frozenset({".jpg", ".jpeg"}),
        fallback_extensions=frozenset({".png"}),
    ),
    "mangaone": ArchivePolicy(
        preferred_extensions=frozenset({".webp"}),
        fallback_extensions=frozenset({".png"}),
    ),
    "magapoke": ArchivePolicy(
        preferred_extensions=frozenset({".jpg", ".jpeg"}),
        fallback_extensions=frozenset({".png"}),
    ),
}

# Files with these extensions are treated as page candidates, even though
# they are not accepted by any current policy.  This lets a GIF/BMP/etc. be
# reported as UNEXPECTED_FORMAT instead of silently ignored.  Unknown root
# files are also conservative unexpected entries below.
_COMMON_IMAGE_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".avif", ".jxl", ".heic", ".heif"}
)
_IGNORED_METADATA_NAMES = frozenset({"__macosx", "thumbs.db", ".ds_store"})


class PrepareRecrawlError(RuntimeError):
    """Base error for scan/apply configuration and Catalog failures."""


class UnsupportedArchivePolicyError(PrepareRecrawlError):
    """Raised when an explicitly requested site has no capture policy."""


@dataclass(frozen=True, slots=True)
class ArchiveInspection:
    classification: ArchiveClassification
    preferred_count: int = 0
    fallback_count: int = 0
    unexpected_count: int = 0
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ScanResult:
    work: Work
    item: Item
    site: str | None
    classification: ArchiveClassification
    artifact: Artifact | None = None
    run: CrawlRun | None = None
    inspection: ArchiveInspection | None = None
    candidate_artifacts: tuple[Artifact, ...] = ()
    reason: str | None = None

    @property
    def archive_locator(self) -> str | None:
        if self.artifact is not None:
            return self.artifact.locator
        locators = [artifact.locator for artifact in self.candidate_artifacts if artifact.locator]
        return ", ".join(locators) if locators else None


@dataclass(frozen=True, slots=True)
class ScanReport:
    results: tuple[ScanResult, ...]
    scanned_completed_items: int
    unsupported_sources: int = 0

    def counts(self) -> Counter[str]:
        counts: Counter[str] = Counter(result.classification.value for result in self.results)
        for classification in ArchiveClassification:
            counts.setdefault(classification.value, 0)
        return counts

    def ignored_missing_count(self, *, ignore_missing: bool) -> int:
        return sum(
            result.classification is ArchiveClassification.MISSING for result in self.results
        ) if ignore_missing else 0

    def problem_results(self, *, ignore_missing: bool) -> tuple[ScanResult, ...]:
        return tuple(
            result
            for result in self.results
            if result.classification is not ArchiveClassification.PREFERRED_ONLY
            and not (
                ignore_missing
                and result.classification is ArchiveClassification.MISSING
            )
        )

    def recrawl_results(self, *, ignore_missing: bool) -> tuple[ScanResult, ...]:
        recrawl = {
            ArchiveClassification.FALLBACK_INCLUDED,
            ArchiveClassification.UNEXPECTED_FORMAT,
            ArchiveClassification.BROKEN,
            ArchiveClassification.MISSING,
        }
        return tuple(
            result
            for result in self.results
            if result.classification in recrawl
            and not (
                ignore_missing
                and result.classification is ArchiveClassification.MISSING
            )
        )

    def manual_review_results(self) -> tuple[ScanResult, ...]:
        return tuple(
            result
            for result in self.results
            if result.classification is ArchiveClassification.AMBIGUOUS_ARTIFACT
        )


@dataclass(slots=True)
class ApplyReport:
    archives_moved: int = 0
    artifacts_marked_missing: int = 0
    items_returned_pending: int = 0
    skipped_ambiguous: int = 0
    failed: int = 0
    details: list[str] | None = None

    def __post_init__(self) -> None:
        if self.details is None:
            self.details = []


def archive_policy_for_site(site: str) -> ArchivePolicy:
    try:
        return SITE_ARCHIVE_POLICIES[site]
    except KeyError as exc:
        raise UnsupportedArchivePolicyError(f"unsupported archive policy for site={site}") from exc


def _ignored_archive_member(name: str) -> bool:
    parts = [part for part in PurePosixPath(name).parts if part not in {"", "."}]
    if not parts:
        return True
    lowered = [part.lower() for part in parts]
    return "__macosx" in lowered or lowered[-1] in _IGNORED_METADATA_NAMES


def _unexpected_member(name: str) -> bool:
    """Return whether a non-metadata ZIP member violates the image-only root."""

    path = PurePosixPath(name)
    if len(path.parts) != 1:
        return True
    # A regular root file with an unknown suffix is conservatively treated as
    # an unexpected page artifact.  This keeps extra content fail-closed.
    return path.suffix.lower() not in _COMMON_IMAGE_EXTENSIONS


def inspect_archive(path: str | Path, policy: ArchivePolicy) -> ArchiveInspection:
    """Inspect a ZIP without extracting or modifying it."""

    archive_path = Path(path)
    if not archive_path.is_file():
        return ArchiveInspection(
            ArchiveClassification.MISSING,
            reason="archive file does not exist",
        )

    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            bad_member = archive.testzip()
            if bad_member is not None:
                raise zipfile.BadZipFile(f"CRC failure in {bad_member}")

            preferred = 0
            fallback = 0
            unexpected = 0
            for info in archive.infolist():
                if info.is_dir() or info.filename.endswith("/"):
                    continue
                if _ignored_archive_member(info.filename):
                    continue
                if _unexpected_member(info.filename):
                    unexpected += 1
                    continue
                extension = PurePosixPath(info.filename).suffix.lower()
                if extension in policy.preferred_extensions:
                    preferred += 1
                elif extension in policy.fallback_extensions:
                    fallback += 1
                else:
                    unexpected += 1

            if preferred + fallback == 0:
                return ArchiveInspection(
                    ArchiveClassification.UNEXPECTED_FORMAT,
                    preferred_count=preferred,
                    fallback_count=fallback,
                    unexpected_count=unexpected,
                    reason="archive contains no page images",
                )
            if unexpected:
                classification = ArchiveClassification.UNEXPECTED_FORMAT
            elif fallback:
                classification = ArchiveClassification.FALLBACK_INCLUDED
            else:
                classification = ArchiveClassification.PREFERRED_ONLY
            return ArchiveInspection(
                classification,
                preferred_count=preferred,
                fallback_count=fallback,
                unexpected_count=unexpected,
            )
    except (zipfile.BadZipFile, OSError, RuntimeError, EOFError, ValueError) as exc:
        return ArchiveInspection(
            ArchiveClassification.BROKEN,
            reason=f"{exc.__class__.__name__}: {exc}",
        )


def _select_current_archives(
    catalog: CatalogService,
    source_id: int,
    *,
    runs_by_source: dict[int, list[CrawlRun]] | None = None,
    artifacts_by_run: dict[int, list[Artifact]] | None = None,
) -> tuple[CrawlRun | None, tuple[Artifact, ...]]:
    runs = (
        runs_by_source[source_id]
        if runs_by_source is not None and source_id in runs_by_source
        else catalog.list_crawl_runs(source_id=source_id, status="succeeded")
    )
    for run in reversed(runs):
        artifacts = (
            artifacts_by_run.get(run.id, [])
            if artifacts_by_run is not None
            else catalog.list_artifacts(crawl_run_id=run.id)
        )
        archive_artifacts = tuple(
            artifact
            for artifact in artifacts
            if artifact.kind == "archive" and artifact.format.lower() == "zip"
        )
        if archive_artifacts:
            return run, archive_artifacts
    return None, ()


def _result_for_candidate(
    work: Work,
    item: Item,
    source: Source,
    run: CrawlRun,
    artifacts: tuple[Artifact, ...],
) -> ScanResult:
    if len(artifacts) != 1:
        return ScanResult(
            work=work,
            item=item,
            site=source.site,
            classification=ArchiveClassification.AMBIGUOUS_ARTIFACT,
            run=run,
            candidate_artifacts=artifacts,
            reason="multiple current archive artifacts",
        )

    artifact = artifacts[0]
    if artifact.state != "present":
        return ScanResult(
            work=work,
            item=item,
            site=source.site,
            classification=ArchiveClassification.MISSING,
            artifact=artifact,
            run=run,
            reason=f"artifact state={artifact.state}",
        )
    if artifact.storage_backend != "filesystem":
        return ScanResult(
            work=work,
            item=item,
            site=source.site,
            classification=ArchiveClassification.MISSING,
            artifact=artifact,
            run=run,
            reason=f"unsupported storage backend={artifact.storage_backend}",
        )
    if not artifact.locator:
        return ScanResult(
            work=work,
            item=item,
            site=source.site,
            classification=ArchiveClassification.MISSING,
            artifact=artifact,
            run=run,
            reason="artifact locator is empty",
        )

    inspection = inspect_archive(artifact.locator, archive_policy_for_site(source.site))
    return ScanResult(
        work=work,
        item=item,
        site=source.site,
        classification=inspection.classification,
        artifact=artifact,
        run=run,
        inspection=inspection,
        reason=inspection.reason,
    )


def scan_catalog(
    catalog: CatalogService,
    *,
    site: str | None = None,
    work: str | None = None,
) -> ScanReport:
    """Scan completed Items in an exact site/work scope without mutation."""

    if site is not None:
        site = site.strip()
        if not site:
            raise PrepareRecrawlError("site must be non-empty")
        archive_policy_for_site(site)
    if work is not None:
        work = work.strip()
        if not work:
            raise PrepareRecrawlError("work must be non-empty")

    works, items, sources, _targets = catalog.read_works_items_sources_and_targets(site=site)
    works_by_id = {value.id: value for value in works}
    items_by_id = {value.id: value for value in items}
    selected_sources_by_item: dict[int, list[Source]] = {}
    unsupported_sources = 0
    for source in sources:
        item = items_by_id.get(source.item_id)
        current_work = works_by_id.get(item.work_id) if item is not None else None
        if item is None or current_work is None or item.status != "completed":
            continue
        if work is not None and current_work.title != work:
            continue
        try:
            archive_policy_for_site(source.site)
        except UnsupportedArchivePolicyError:
            # Work-only scans are allowed to cross sites, but only known site
            # policies can be judged. An explicitly requested --site failed
            # above before reaching this point.
            unsupported_sources += 1
            continue
        selected_sources_by_item.setdefault(item.id, []).append(source)

    runs_by_source: dict[int, list[CrawlRun]] = {}
    artifacts_by_run: dict[int, list[Artifact]] = {}
    for source_list in selected_sources_by_item.values():
        for source in source_list:
            runs = catalog.list_crawl_runs(source_id=source.id, status="succeeded")
            runs_by_source[source.id] = runs
            for run in runs:
                artifacts_by_run[run.id] = catalog.list_artifacts(crawl_run_id=run.id)

    results: list[ScanResult] = []
    for item_id in sorted(selected_sources_by_item):
        item = items_by_id[item_id]
        current_work = works_by_id[item.work_id]
        candidates: list[tuple[Source, CrawlRun, tuple[Artifact, ...]]] = []
        for source in selected_sources_by_item[item_id]:
            run, artifacts = _select_current_archives(
                catalog,
                source.id,
                runs_by_source=runs_by_source,
                artifacts_by_run=artifacts_by_run,
            )
            if run is not None:
                candidates.append((source, run, artifacts))

        if len(candidates) > 1:
            candidate_artifacts = tuple(
                artifact for _source, _run, artifacts in candidates for artifact in artifacts
            )
            sites = ", ".join(sorted({source.site for source, _run, _artifacts in candidates}))
            results.append(
                ScanResult(
                    work=current_work,
                    item=item,
                    site=sites,
                    classification=ArchiveClassification.AMBIGUOUS_ARTIFACT,
                    candidate_artifacts=candidate_artifacts,
                    reason="multiple current archive candidates",
                )
            )
        elif len(candidates) == 1:
            source, run, artifacts = candidates[0]
            results.append(_result_for_candidate(current_work, item, source, run, artifacts))
        else:
            # A completed Item with a selected source but no successful archive
            # is still unsafe to leave completed. There is no Artifact to
            # update, so apply can only report the failure and leave it alone.
            source = selected_sources_by_item[item_id][0]
            results.append(
                ScanResult(
                    work=current_work,
                    item=item,
                    site=source.site,
                    classification=ArchiveClassification.MISSING,
                    reason="no successful archive artifact",
                )
            )

    return ScanReport(
        results=tuple(results),
        scanned_completed_items=len(results),
        unsupported_sources=unsupported_sources,
    )


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _backup_destination(path: Path, *, library_dir: Path, backup_root: Path) -> Path:
    try:
        relative = _absolute(path).relative_to(_absolute(library_dir))
    except ValueError:
        relative = Path(path.name)
    return backup_root / relative


def _backup_root(base: Path, timestamp: str | None = None) -> Path:
    value = timestamp or now_jst().strftime("%Y%m%d-%H%M%S%z")
    return base / value


def _recheck_candidate(result: ScanResult) -> ArchiveInspection | None:
    if result.artifact is None or not result.artifact.locator or result.site is None:
        return None
    if "," in result.site:
        return None
    try:
        policy = archive_policy_for_site(result.site)
    except UnsupportedArchivePolicyError:
        return None
    return inspect_archive(result.artifact.locator, policy)


def apply_scan_results(
    catalog: CatalogService,
    report: ScanReport,
    *,
    library_dir: str | Path = "output/Books",
    backup_root: str | Path = "output/reimport-backup",
    timestamp: str | None = None,
    ignore_missing: bool = False,
) -> ApplyReport:
    """Apply only safe recrawl candidates from a read-only scan report."""

    result = ApplyReport()
    destination_root = _backup_root(Path(backup_root), timestamp)
    for entry in report.results:
        classification = entry.classification
        if classification is ArchiveClassification.PREFERRED_ONLY:
            continue
        if classification is ArchiveClassification.AMBIGUOUS_ARTIFACT:
            result.skipped_ambiguous += 1
            result.details.append(
                f"SKIP APPLY item={entry.item.id} reason=ambiguous_artifact"
            )
            continue
        if classification is ArchiveClassification.MISSING:
            if ignore_missing:
                continue
            if entry.artifact is None:
                result.failed += 1
                result.details.append(
                    f"PARTIAL FAILURE item={entry.item.id} reason=no_artifact_to_mark_missing"
                )
                continue
            try:
                catalog.update_artifact_storage(entry.artifact.id, state="missing")
                result.artifacts_marked_missing += 1
            except Exception as exc:  # noqa: BLE001 - report partial failure and continue
                result.failed += 1
                result.details.append(
                    f"PARTIAL FAILURE item={entry.item.id} artifact={entry.artifact.id} "
                    f"reason=artifact_update_failed:{exc.__class__.__name__}: {exc}"
                )
                continue
            try:
                catalog.mark_item_pending(entry.item.id)
                result.items_returned_pending += 1
            except Exception as exc:  # noqa: BLE001 - report partial failure and continue
                result.failed += 1
                result.details.append(
                    f"PARTIAL FAILURE item={entry.item.id} artifact_state=missing "
                    f"reason=item_pending_failed:{exc.__class__.__name__}: {exc}"
                )
            continue

        if entry.artifact is None or not entry.artifact.locator:
            result.failed += 1
            result.details.append(
                f"PARTIAL FAILURE item={entry.item.id} reason=archive_locator_missing"
            )
            continue
        archive_path = Path(entry.artifact.locator)
        if not archive_path.is_file():
            result.failed += 1
            result.details.append(
                f"PARTIAL FAILURE item={entry.item.id} reason=archive_disappeared:{archive_path}"
            )
            continue
        inspection = _recheck_candidate(entry)
        if inspection is None or inspection.classification is not classification:
            result.failed += 1
            current = inspection.classification.value if inspection is not None else "UNKNOWN"
            result.details.append(
                f"PARTIAL FAILURE item={entry.item.id} reason=archive_changed:"
                f"expected={classification.value}, actual={current}"
            )
            continue

        destination = _backup_destination(
            archive_path,
            library_dir=Path(library_dir),
            backup_root=destination_root,
        )
        if os.path.lexists(destination):
            result.failed += 1
            result.details.append(
                f"PARTIAL FAILURE item={entry.item.id} reason=backup_collision:{destination}"
            )
            continue
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(os.fspath(archive_path), os.fspath(destination))
        except OSError as exc:
            result.failed += 1
            result.details.append(
                f"PARTIAL FAILURE item={entry.item.id} reason=move_failed:{exc}"
            )
            continue
        result.archives_moved += 1

        try:
            catalog.update_artifact_storage(
                entry.artifact.id,
                locator=destination.as_posix(),
                state="present",
            )
        except Exception as exc:  # noqa: BLE001 - filesystem move is intentionally not rolled back
            result.failed += 1
            result.details.append(
                f"PARTIAL FAILURE item={entry.item.id} backup={destination} "
                f"reason=artifact_update_failed:{exc.__class__.__name__}: {exc}"
            )
            continue
        try:
            catalog.mark_item_pending(entry.item.id)
            result.items_returned_pending += 1
        except Exception as exc:  # noqa: BLE001 - report partial failure and continue
            result.failed += 1
            result.details.append(
                f"PARTIAL FAILURE item={entry.item.id} backup={destination} "
                f"reason=item_pending_failed:{exc.__class__.__name__}: {exc}"
            )
    return result


def _quoted(value: str | None) -> str:
    return '""' if value is None else repr(value)


def _print_result(entry: ScanResult, *, ignored_missing: bool = False) -> None:
    label = entry.classification.value
    if ignored_missing:
        label += " (ignored)"
    print(label)
    title = entry.item.item_title or entry.item.order_label or entry.item.order_key
    print(f"  item={entry.item.id} order={entry.item.order_label or entry.item.order_key or '-'} title={_quoted(title)}")
    print(f"  archive={entry.archive_locator or '<none>'}")
    if entry.inspection is not None:
        print(
            f"  preferred={entry.inspection.preferred_count} "
            f"fallback={entry.inspection.fallback_count} "
            f"unexpected={entry.inspection.unexpected_count}"
        )
    if entry.reason:
        print(f"  reason={entry.reason}")


def _print_scan(report: ScanReport, *, site: str | None, work: str | None, show_all: bool, ignore_missing: bool) -> None:
    print("Scope:")
    print(f"  site: {site or '<all supported sites>'}")
    print(f"  work: {work or '<all works>'}")
    print()
    visible = (
        report.results
        if show_all
        else report.problem_results(ignore_missing=ignore_missing)
    )
    if visible:
        print("Items:" if show_all else "Problems:")
        for entry in visible:
            _print_result(
                entry,
                ignored_missing=(
                    show_all
                    and ignore_missing
                    and entry.classification is ArchiveClassification.MISSING
                ),
            )
            print()
    else:
        print("Problems:")
        print("  none")
        print()

    counts = report.counts()
    ignored = report.ignored_missing_count(ignore_missing=ignore_missing)
    problems = len(report.problem_results(ignore_missing=ignore_missing))
    candidates = len(report.recrawl_results(ignore_missing=ignore_missing))
    manual = len(report.manual_review_results())
    print("Summary:")
    print(f"  scanned completed items: {report.scanned_completed_items}")
    for classification in ArchiveClassification:
        print(f"  {classification.value}: {counts[classification.value]}")
    print(f"  ignored missing: {ignored}")
    print(f"  problems: {problems}")
    print(f"  recrawl candidates: {candidates}")
    print(f"  manual review required: {manual}")
    if report.unsupported_sources:
        print(f"  unsupported sources skipped: {report.unsupported_sources}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="prepare_recrawl.py",
        description="Inspect completed archive artifacts and prepare safe re-crawls.",
    )
    parser.add_argument("--site", help="Exact site scope")
    parser.add_argument("--work", help="Exact Work.title scope")
    parser.add_argument("--catalog", type=Path, default=Path("catalog.sqlite"))
    parser.add_argument("--library-dir", type=Path, default=Path("output/Books"))
    parser.add_argument(
        "--backup-root",
        type=Path,
        default=Path("output/reimport-backup"),
        help="Backup root (default: output/reimport-backup)",
    )
    parser.add_argument("--apply", action="store_true", help="Move/update recrawl candidates")
    parser.add_argument("--show-all", action="store_true", help="Show PREFERRED_ONLY items too")
    parser.add_argument(
        "--ignore-missing",
        action="store_true",
        help="Report MISSING only in --show-all; never recrawl or mutate it",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.site is None and args.work is None:
        print("ERROR one of --site or --work is required", file=sys.stderr)
        return 1
    try:
        catalog = CatalogService(args.catalog)
        report = scan_catalog(catalog, site=args.site, work=args.work)
        _print_scan(
            report,
            site=args.site,
            work=args.work,
            show_all=args.show_all,
            ignore_missing=args.ignore_missing,
        )
        if args.apply:
            applied = apply_scan_results(
                catalog,
                report,
                library_dir=args.library_dir,
                backup_root=args.backup_root,
                ignore_missing=args.ignore_missing,
            )
            print("Apply:")
            print(f"  archives moved: {applied.archives_moved}")
            print(f"  artifacts marked missing: {applied.artifacts_marked_missing}")
            print(f"  items returned to pending: {applied.items_returned_pending}")
            print(f"  skipped ambiguous: {applied.skipped_ambiguous}")
            print(f"  failed: {applied.failed}")
            for detail in applied.details:
                print(f"  {detail}")
        else:
            print("Dry-run only.")
        return 0
    except (PrepareRecrawlError, OSError, ValueError) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover - exercised through the CLI
    raise SystemExit(main())
