"""Package completed crawl output according to the library naming rules."""

from __future__ import annotations

import os
import re
import shutil
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
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


def package_crawl_output(
    output_dir: str | Path,
    metadata: Mapping[str, str | None],
    *,
    library_dir: str | Path = "output/Books",
) -> PackageResult:
    """Zip a completed crawl and move it into the configured library tree.

    The ZIP contains only captured PNG pages under a top-level folder whose
    name matches the archive stem. The source crawl directory is removed only
    after the archive and completion status have been written successfully.
    """

    source = Path(output_dir)
    if not source.is_dir():
        raise FileNotFoundError(f"Crawl output directory not found: {source}")

    stem, title, genre, order, author = archive_stem(metadata)
    destination_dir = Path(library_dir) / genre / title
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / f"{stem}.zip"
    if destination.exists():
        raise FileExistsError(f"Archive already exists: {destination}")

    page_files = sorted(source.glob("page-*.png"))
    if not page_files:
        raise FileNotFoundError(f"No captured PNG pages found in: {source}")

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
            for file_path in page_files:
                archive.write(file_path, archive_root / file_path.name)
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

    # Keep failed runs available for diagnostics, but remove the intermediate
    # crawl directory after a successfully archived run. Require the files
    # produced by ProgressStore before deleting anything as a safety guard.
    removable = (
        source.name.lower() != "output"
        and (source / "manifest.json").is_file()
        and (source / "progress.json").is_file()
    )
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
