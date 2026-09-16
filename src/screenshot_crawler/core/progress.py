"""Atomic manifest and progress persistence."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from screenshot_crawler.core.errors import RunAlreadyExistsError
from screenshot_crawler.core.models import CapturedPage, ContentContext, ContentIdentity


def normalize_path(path: str | Path) -> Path:
    """Normalize path components that Windows cannot address literally.

    PowerShell can pass a trailing space through when a line-continuation
    backtick is copied with surrounding whitespace. Windows strips that
    whitespace when creating a directory, but Python keeps it in later
    ``open`` calls, producing a misleading ``FileNotFoundError``.
    """

    destination = Path(path)
    if os.name != "nt":
        return destination

    anchor = destination.anchor
    parts = destination.parts
    relative_parts = parts[1:] if anchor else parts
    cleaned_parts = [part.rstrip(" .") or part for part in relative_parts]
    return Path(anchor, *cleaned_parts) if anchor else Path(*cleaned_parts)


def atomic_write_json(path: str | Path, payload: dict[str, Any]) -> None:
    """Write JSON through a sibling temporary file and replace atomically."""

    destination = normalize_path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    # Windows file scanners and editors can briefly hold the destination after
    # it was written. Retry the atomic replacement for that transient case,
    # while still surfacing a persistent lock to the caller.
    for attempt in range(5):
        try:
            os.replace(temporary, destination)
            return
        except PermissionError:
            if attempt == 4:
                temporary.unlink(missing_ok=True)
                raise
            time.sleep(0.1 * (attempt + 1))


def _identity_dict(identity: ContentIdentity | None) -> dict[str, Any] | None:
    return asdict(identity) if identity is not None else None


def _context_dict(context: ContentContext | None) -> dict[str, Any]:
    return asdict(context) if context is not None else {}


def ensure_new_run(output_dir: str | Path) -> Path:
    """Reject a directory that contains recognizable artifacts from a run.

    Resume is deliberately not implemented yet. Refusing these directories
    keeps a new manifest/progress pair from being associated with old PNGs.
    An empty, pre-created directory remains usable.
    """

    destination = normalize_path(output_dir)
    if destination.exists() and not destination.is_dir():
        raise RunAlreadyExistsError(
            f"Run output path is not a directory: {destination}"
        )
    if not destination.exists():
        return destination

    artifacts = [
        path
        for path in (
            destination / "manifest.json",
            destination / "progress.json",
            destination / ".manifest.json.tmp",
            destination / ".progress.json.tmp",
        )
        if path.exists()
    ]
    artifacts.extend(path for path in destination.glob("page-*.png") if path.is_file())
    if artifacts:
        names = ", ".join(path.name for path in artifacts[:3])
        if len(artifacts) > 3:
            names += ", ..."
        raise RunAlreadyExistsError(
            f"Output directory already contains a crawl run ({names}). "
            "Resume is not implemented; choose a new output directory."
        )
    return destination


class ProgressStore:
    """Keep manifest and progress information synchronized on every capture."""

    def __init__(
        self,
        *,
        manifest_path: str | Path,
        progress_path: str | Path,
        source_url: str,
        site: str,
        content_context: ContentContext,
    ) -> None:
        self.manifest_path = normalize_path(manifest_path)
        self.progress_path = normalize_path(progress_path)
        ensure_new_run(self.manifest_path.parent)
        if self.manifest_path.exists() or self.progress_path.exists():
            raise RunAlreadyExistsError(
                "Manifest or progress already exists. Resume is not implemented; "
                "choose a new output directory."
            )
        self._manifest: dict[str, Any] = {
            "source_url": source_url,
            "site": site,
            "content_context": _context_dict(content_context),
            "pages": [],
        }
        self._progress: dict[str, Any] = {
            "last_saved_sequence": 0,
            "last_identity": None,
            "last_fingerprint": None,
            "content_context": _context_dict(content_context),
        }
        self.flush()

    @property
    def pages(self) -> list[dict[str, Any]]:
        return self._manifest["pages"]

    def add_page(self, page: CapturedPage, *, fingerprint: str) -> None:
        relative_file = page.file.as_posix()
        self.pages.append(
            {
                "sequence": page.sequence,
                "page_number": page.identity.page_number,
                "file": relative_file,
                "width": page.width,
                "height": page.height,
                "fingerprint": fingerprint,
                "identity": _identity_dict(page.identity),
                "metadata": page.metadata,
            }
        )
        self._progress.update(
            {
                "last_saved_sequence": page.sequence,
                "last_identity": _identity_dict(page.identity),
                "last_fingerprint": fingerprint,
            }
        )
        self.flush()

    def flush(self) -> None:
        atomic_write_json(self.manifest_path, self._manifest)
        atomic_write_json(self.progress_path, self._progress)
