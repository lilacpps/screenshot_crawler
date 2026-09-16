"""Package completed crawl output according to the library naming rules."""

from __future__ import annotations

import json
import os
import re
import shutil
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from tempfile import NamedTemporaryFile

from screenshot_crawler.core.progress import atomic_write_json

_WINDOWS_FORBIDDEN = re.compile(r'[\\/:*?"<>|]')


@dataclass(frozen=True, slots=True)
class PackageResult:
    """Location of the archive created for one completed crawl."""

    archive_path: Path
    title: str
    genre: str
    # Kept as ``volume`` for API compatibility; the value is the generic
    # order component returned by ``archive_stem``.
    volume: str | None
    author: str | None
    status_path: Path


def safe_component(value: str | None, *, fallback: str) -> str:
    """Make a title/author safe for a Windows-compatible file name."""

    text = " ".join((value or "").split()).strip()
    text = _WINDOWS_FORBIDDEN.sub("", text)
    text = text.rstrip(" .")
    return text or fallback


def archive_stem(metadata: Mapping[str, str | None]) -> tuple[str, str, str, str | None, str | None]:
    """Return ``(stem, title, genre, order, author)`` from adapter metadata.

    ``volume`` remains accepted for adapters written before the generic
    ``order`` field was introduced.
    """

    title = safe_component(metadata.get("title"), fallback="unknown-title")
    genre = safe_component(metadata.get("genre"), fallback="小説")
    order_value = metadata.get("order")
    if order_value is None:
        order_value = metadata.get("volume")
    order = safe_component(order_value, fallback="") or None
    author = safe_component(metadata.get("author"), fallback="") or None
    components = [title]
    if order:
        components.append(order)
    if author:
        components.append(author)
    return "-".join(components), title, genre, order, author


def _manifest_page_files(source: Path) -> list[tuple[Path, PurePosixPath]]:
    """Resolve and validate the PNG files declared by ``manifest.json``."""

    manifest_path = source / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid manifest JSON: {manifest_path}") from exc

    pages = manifest.get("pages") if isinstance(manifest, dict) else None
    if not isinstance(pages, list) or not pages:
        raise ValueError("Manifest must contain a non-empty pages list")

    source_resolved = source.resolve()
    result: list[tuple[Path, PurePosixPath]] = []
    seen: set[str] = set()
    for index, page in enumerate(pages, start=1):
        file_name = page.get("file") if isinstance(page, dict) else None
        if not isinstance(file_name, str) or not file_name or "\\" in file_name:
            raise ValueError(f"Manifest page {index} has an invalid file path")
        relative = PurePosixPath(file_name)
        if (
            relative.is_absolute()
            or PureWindowsPath(file_name).is_absolute()
            or PureWindowsPath(file_name).root
            or PureWindowsPath(file_name).drive
            or any(part in {"", ".", ".."} for part in relative.parts)
            or relative.suffix.lower() != ".png"
        ):
            raise ValueError(f"Manifest page {index} has an unsafe PNG path: {file_name}")
        normalized_name = relative.as_posix()
        if normalized_name in seen:
            raise ValueError(f"Manifest contains duplicate page file: {file_name}")
        seen.add(normalized_name)

        candidate = (source / Path(*relative.parts)).resolve()
        try:
            candidate.relative_to(source_resolved)
        except ValueError as exc:
            raise ValueError(f"Manifest page escapes output directory: {file_name}") from exc
        if not candidate.is_file():
            raise FileNotFoundError(f"Manifest page file not found: {candidate}")
        result.append((candidate, relative))
    return result


def _source_contains_only_generated_files(
    source: Path, page_files: list[tuple[Path, PurePosixPath]]
) -> bool:
    """Allow cleanup only when every source entry is a known run artifact."""

    if source.name.lower() == "output":
        return False
    expected = {"manifest.json", "progress.json"}
    for _, relative_file in page_files:
        if len(relative_file.parts) != 1:
            return False
        expected.add(relative_file.name)
    entries = list(source.iterdir())
    return len(entries) == len(expected) and all(
        entry.is_file() and entry.name in expected for entry in entries
    )


def package_crawl_output(
    output_dir: str | Path,
    metadata: Mapping[str, str | None],
    *,
    library_dir: str | Path = "output/Books",
) -> PackageResult:
    """Zip a completed crawl and move it into the configured library tree.

    The ZIP contains only captured PNG pages under a top-level folder whose
    name matches the archive stem. The source crawl directory is removed only
    when it contains generated run files and the archive and completion
    status have been written successfully.
    """

    source = Path(output_dir)
    if not source.is_dir():
        raise FileNotFoundError(f"Crawl output directory not found: {source}")

    page_files = _manifest_page_files(source)
    stem, title, genre, order, author = archive_stem(metadata)
    destination_dir = Path(library_dir) / genre / title
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / f"{stem}.zip"
    if destination.exists():
        raise FileExistsError(f"Archive already exists: {destination}")

    # Keep the temporary archive outside the source tree so it cannot be added
    # to itself while the source is being walked.
    with NamedTemporaryFile(
        mode="wb",
        prefix=f".{source.name}-",
        suffix=".zip.tmp",
        dir=source.parent,
        delete=False,
    ) as temporary:
        temporary_path = Path(temporary.name)

    try:
        with zipfile.ZipFile(temporary_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive_root = Path(stem)
            for file_path, relative_file in page_files:
                archive.write(file_path, (archive_root / relative_file).as_posix())
        os.replace(temporary_path, destination)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise

    status_dir = Path(library_dir).parent / "crawl-status"
    status_path = status_dir / f"{stem}.json"
    status = {
        "status": "completed",
        "archive_path": destination.as_posix(),
        "page_count": len(page_files),
        "source_output_dir": source.as_posix(),
        "source_removed": False,
    }
    atomic_write_json(status_path, status)

    # Keep failed runs and directories containing user files available. Only
    # remove a source directory whose complete contents are generated files.
    removable = _source_contains_only_generated_files(source, page_files)
    cleanup_error: str | None = None
    if removable:
        try:
            shutil.rmtree(source)
        except OSError as exc:
            cleanup_error = str(exc)

    status["source_removed"] = not source.exists()
    if cleanup_error:
        status["cleanup_error"] = cleanup_error
    atomic_write_json(status_path, status)

    return PackageResult(
        archive_path=destination,
        title=title,
        genre=genre,
        volume=order,
        author=author,
        status_path=status_path,
    )
