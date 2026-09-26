#!/usr/bin/env python3
"""Remove one common top-level directory from image-only ZIP archives."""

from __future__ import annotations

import argparse
import copy
import os
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from tempfile import NamedTemporaryFile
from zipfile import BadZipFile, ZipFile, ZipInfo

IMAGE_SUFFIXES = {
    ".avif",
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}


class UnsafeEntryNameError(ValueError):
    """Raised when a ZIP entry is not safe to process as a relative path."""


@dataclass(frozen=True, slots=True)
class ArchiveResult:
    action: str
    path: Path
    reason: str


@dataclass(frozen=True, slots=True)
class _ArchivePlan:
    root_name: str
    entries: tuple[tuple[int, str], ...]


def _entry_parts(info: ZipInfo) -> tuple[str, ...]:
    name = info.filename
    if not name or "\x00" in name or "\\" in name:
        raise UnsafeEntryNameError(name or "<empty>")

    windows_path = PureWindowsPath(name)
    if name.startswith("/") or windows_path.is_absolute() or windows_path.drive:
        raise UnsafeEntryNameError(name)

    parts = name.split("/")
    if info.is_dir() and parts[-1] == "":
        parts.pop()
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise UnsafeEntryNameError(name)
    return tuple(parts)


def _is_image_name(name: str) -> bool:
    return PurePosixPath(name.rstrip("/")).suffix.lower() in IMAGE_SUFFIXES


def _inspect_archive(archive: ZipFile) -> tuple[_ArchivePlan | None, str]:
    bad_entry = archive.testzip()
    if bad_entry is not None:
        raise BadZipFile(f"corrupt entry: {bad_entry}")

    infos = archive.infolist()
    if not infos:
        return None, "empty archive"

    parts_by_index = {index: _entry_parts(info) for index, info in enumerate(infos)}
    file_indices = [index for index, info in enumerate(infos) if not info.is_dir()]
    if not file_indices:
        return None, "no files"

    if all(
        len(parts_by_index[index]) == 1 and _is_image_name(infos[index].filename)
        for index in file_indices
    ):
        return None, "already flat"

    if any(len(parts_by_index[index]) < 2 for index in file_indices):
        return None, "ambiguous structure"

    top_levels = {parts[0] for parts in parts_by_index.values()}
    if len(top_levels) != 1:
        return None, "ambiguous structure"
    root_name = next(iter(top_levels))
    root_prefix = f"{root_name}/"

    output_names: set[str] = set()
    flattened_entries: list[tuple[int, str]] = []
    for index, info in enumerate(infos):
        if not info.filename.startswith(root_prefix):
            return None, "ambiguous structure"
        output_name = info.filename[len(root_prefix) :]
        if info.is_dir() and not output_name:
            continue
        if not output_name or output_name in output_names:
            return None, "entry name collision"
        if not info.is_dir() and not _is_image_name(output_name):
            return None, "non-image entry"
        output_names.add(output_name)
        flattened_entries.append((index, output_name))

    if not flattened_entries:
        return None, "no files"
    return _ArchivePlan(root_name=root_name, entries=tuple(flattened_entries)), ""


def _rewrite_archive(path: Path, plan: _ArchivePlan) -> None:
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}-",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)

        with ZipFile(path, "r") as source, ZipFile(temporary_path, "w") as destination:
            destination.comment = source.comment
            infos = source.infolist()
            for index, output_name in plan.entries:
                source_info = infos[index]
                output_info = copy.copy(source_info)
                output_info.filename = output_name
                output_info.orig_filename = output_name
                data = b"" if source_info.is_dir() else source.read(source_info)
                destination.writestr(output_info, data)

        with ZipFile(temporary_path, "r") as verification:
            bad_entry = verification.testzip()
            if bad_entry is not None:
                raise BadZipFile(f"corrupt rewritten entry: {bad_entry}")
            expected_names = [output_name for _, output_name in plan.entries]
            if verification.namelist() != expected_names:
                raise BadZipFile("rewritten entry names do not match the migration plan")

        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def process_archive(path: Path, *, dry_run: bool = False) -> ArchiveResult:
    """Inspect and, unless dry-running, safely flatten one ZIP archive."""

    try:
        with ZipFile(path, "r") as archive:
            plan, reason = _inspect_archive(archive)
        if plan is None:
            return ArchiveResult("SKIP", path, reason)
        if dry_run:
            return ArchiveResult("FIX", path, f"{plan.root_name}/ -> archive root")
        _rewrite_archive(path, plan)
        return ArchiveResult("FIX", path, f"{plan.root_name}/ -> archive root")
    except UnsafeEntryNameError:
        return ArchiveResult("SKIP", path, "unsafe entry name")
    except BadZipFile as exc:
        detail = str(exc) or "invalid ZIP"
        return ArchiveResult("ERROR", path, f"BadZipFile: {detail}")
    except (OSError, RuntimeError, ValueError) as exc:
        detail = str(exc) or exc.__class__.__name__
        return ArchiveResult("ERROR", path, detail)


def _zip_paths(root: Path) -> list[Path]:
    return sorted(
        (path for path in root.rglob("*") if path.is_file() and path.suffix.lower() == ".zip"),
        key=lambda path: path.as_posix().casefold(),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Flatten image-only ZIP archives by removing one common top-level folder."
    )
    parser.add_argument("directory", type=Path, help="Directory to search recursively for ZIPs")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report FIX/SKIP/ERROR results without changing any ZIP files",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    root = args.directory
    if not root.is_dir():
        print(f"ERROR {root} : directory not found", file=sys.stderr)
        return 2

    results = []
    for path in _zip_paths(root):
        result = process_archive(path, dry_run=args.dry_run)
        results.append(result)
        print(f"{result.action:<5} {result.path} : {result.reason}")

    counts = {action: sum(result.action == action for result in results) for action in ("FIX", "SKIP", "ERROR")}
    print(f"Processed: {len(results)}")
    print(f"Fixed:     {counts['FIX']}")
    print(f"Skipped:   {counts['SKIP']}")
    print(f"Errors:    {counts['ERROR']}")
    return 1 if counts["ERROR"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
