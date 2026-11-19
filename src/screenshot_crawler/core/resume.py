"""Validated capture sessions and an entry-started, monotonic time budget.

The caller owns admission, Catalog binding and the session directory. Core never
discovers sessions or decides which access resource may be used.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import time
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from screenshot_crawler.core.models import CapturedPage, ContentContext, ContentIdentity
from screenshot_crawler.core.progress import ProgressStore


class ResumeError(ValueError):
    """A stored acquisition cannot be trusted or joined to this viewer."""


def plain_path(path: Path) -> Path:
    """Reject redirects through symlinks/junctions before resolving a path."""
    path = path.absolute()
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise ResumeError(f"Resume path redirects outside its namespace: {part}")
    return path.resolve()


def read_session_manifest(directory: Path, session_id: str, binding: dict) -> dict:
    directory = plain_path(directory)
    try:
        data = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        info = data["capture_session"]
        if info["version"] != 1 or info["id"] != session_id or info["binding"] != binding:
            raise ResumeError("Resume acquisition/Catalog identity does not match")
        if info.get("invalid"):
            raise ResumeError("Resume acquisition was invalidated")
        if (
            not isinstance(info.get("metadata"), dict)
            or not isinstance(info.get("attempts"), list)
            or any(type(run_id) is not int or run_id < 1 for run_id in info["attempts"])
        ):
            raise ResumeError("Invalid capture session metadata/attempt history")
        terminal = info.get("terminal")
        if terminal is not None and (
            not isinstance(terminal, dict)
            or terminal.get("state") not in {"end", "next_content"}
            or not isinstance(terminal.get("reason"), str)
            or not terminal["reason"]
        ):
            raise ResumeError("Invalid capture session terminal record")
        pages, groups = data["pages"], data["capture_groups"]
        if not isinstance(pages, list) or not isinstance(groups, list):
            raise ResumeError("Invalid resume pages/groups")
        expected = 1
        for group in groups:
            if group["start"] != expected or type(group["end"]) is not int:
                raise ResumeError("Non-contiguous resume groups")
            end = group["end"]
            if not expected <= end <= len(pages) or not isinstance(group["checkpoint"], dict):
                raise ResumeError("Incomplete resume group")
            identity = group["identity"]
            for index in range(expected - 1, end):
                if pages[index]["identity"] != identity:
                    raise ResumeError("Resume spread identity changed between parts")
                if end > expected:
                    metadata = pages[index].get("metadata", {})
                    if (
                        metadata.get("part") != index - expected + 2
                        or metadata.get("parts") != end - expected + 1
                    ):
                        raise ResumeError("Incomplete resume spread")
            expected = end + 1
        if expected != len(pages) + 1:
            raise ResumeError("Resume pages are not committed as complete groups")
        names = set()
        for sequence, page in enumerate(pages, 1):
            name = page["file"]
            if (
                page["sequence"] != sequence
                or not isinstance(name, str)
                or not re.fullmatch(r"page-[0-9]+\.(?:png|jpg|jpeg|webp)", name)
                or name in names
            ):
                raise ResumeError("Unsafe/duplicate resume artifact path or sequence")
            names.add(name)
            artifact = plain_path(directory / name)
            if (
                not artifact.is_file()
                or hashlib.sha256(artifact.read_bytes()).hexdigest() != page["fingerprint"]
            ):
                raise ResumeError(f"Resume artifact missing or changed: {artifact}")
        for entry in directory.iterdir():
            plain_path(entry)
            if entry.name not in names | {
                "manifest.json",
                "progress.json",
                "capture-session.keep",
                "diagnostics",
            }:
                raise ResumeError(f"Uncommitted/unrecognized resume artifact: {entry}")
        if info.get("terminal") and not pages:
            raise ResumeError("Terminal resume session has no captured pages")
        return data
    except (AttributeError, KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
        raise ResumeError(f"Invalid resume manifest in {directory}: {type(exc).__name__}") from exc


class CaptureSession:
    """One logical acquisition shared by separate attempts, never a resource grant."""

    def __init__(
        self,
        directory: Path,
        session_id: str,
        binding: dict,
        *,
        source_url: str,
        site: str,
        existing: bool = False,
        seconds: float | None = None,
        owned_test: bool = False,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if seconds is not None and (
            isinstance(seconds, bool)
            or not isinstance(seconds, (int, float))
            or not math.isfinite(seconds)
            or seconds <= 0
        ):
            raise ValueError("Capture budget must be positive finite seconds or None")
        self.directory = plain_path(directory)
        self.id = session_id
        self.binding = binding
        self.seconds = seconds
        self.owned_test = owned_test
        self.clock = clock
        self.started_at: float | None = None
        self._started = asyncio.Event()
        manifest = read_session_manifest(self.directory, session_id, binding) if existing else None
        if manifest is not None and (
            manifest.get("source_url") != source_url or manifest.get("site") != site
        ):
            raise ResumeError("Resume source URL/site changed")
        self.store = ProgressStore(
            manifest_path=self.directory / "manifest.json",
            progress_path=self.directory / "progress.json",
            source_url=source_url,
            site=site,
            content_context=ContentContext(),
            existing_manifest=manifest,
        )
        if manifest is None:
            self.store.manifest.update(
                capture_groups=[],
                capture_session={
                    "version": 1,
                    "id": session_id,
                    "binding": binding,
                    "attempts": [],
                    "terminal": None,
                    "metadata": {},
                    "package": None,
                },
            )
            self.store.flush()
            # Preserve manifest/images until the Catalog commit, even if packaging succeeds.
            (self.directory / "capture-session.keep").write_text(session_id, encoding="ascii")

    @property
    def info(self) -> dict[str, Any]:
        return self.store.manifest["capture_session"]

    @property
    def checkpoint(self) -> dict | None:
        groups = self.store.manifest["capture_groups"]
        return groups[-1]["checkpoint"] if groups else None

    @property
    def revision(self) -> str:
        payload = json.dumps(
            self.store.manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @property
    def terminal(self) -> dict | None:
        return self.info.get("terminal")

    def start(self) -> None:
        if self.started_at is None:
            self.started_at = self.clock()
            self._started.set()

    async def wait_for_budget(self) -> None:
        await self._started.wait()
        if self.seconds is None:
            await asyncio.Event().wait()
            return
        while True:
            remaining = self.seconds - (self.clock() - self.started_at)
            if remaining <= 0:
                return
            await asyncio.sleep(remaining)

    def saved_pages(self) -> list[CapturedPage]:
        return [
            CapturedPage(
                sequence=p["sequence"],
                file=Path(p["file"]),
                identity=ContentIdentity(**p["identity"]),
                width=p.get("width"),
                height=p.get("height"),
                mime_type=p.get("mime_type", "image/png"),
                file_extension=p.get("file_extension", ".png"),
                metadata=p.get("metadata", {}),
            )
            for p in self.store.pages
        ]

    def attach_context(self, context: ContentContext) -> None:
        prior = self.store.manifest.get("content_context", {})
        for key in ("content_id", "work_id", "episode_id", "chapter_id"):
            if prior.get(key) is not None and getattr(context, key) != prior[key]:
                raise ResumeError("Resume content context changed")
        self.store.manifest["content_context"] = asdict(context)
        self.store.flush()

    def record_attempt(self, run_id: int) -> None:
        self.info["attempts"].append(run_id)
        self.store.flush()

    def finish(self, state: str, reason: str, metadata: dict) -> None:
        if not self.store.pages:
            raise ResumeError("Cannot complete an empty acquisition")
        self.info.update(terminal={"state": state, "reason": reason}, metadata=metadata)
        self.store.flush()

    def invalidate(self, reason: str) -> None:
        self.info["invalid"] = reason
        self.store.flush()

    def save_info(self) -> None:
        self.store.flush()
