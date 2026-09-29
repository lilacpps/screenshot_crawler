#!/usr/bin/env python3
"""Benchmark lossless WebP encodes for PNGs already stored in ZIP archives.

The input archives are opened read-only and PNG members are decoded directly
from memory; no archive is rewritten and no PNG is extracted to disk.

Example::

    python scripts/benchmark_bookwalker_lossless_webp.py \
        "output/Books/ライトノベル/book-a/book-a.zip" \
        "output/Books/ライトノベル/book-b/book-b.zip" \
        --max-images 100

The script does not infer site provenance. Every ZIP explicitly supplied by
the user is treated as an input archive.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import zipfile
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageChops, features


@dataclass(frozen=True, slots=True)
class WebPSetting:
    """One Pillow WebP encoder configuration."""

    quality: int
    method: int

    @property
    def label(self) -> str:
        return f"q{self.quality}/m{self.method}"


DEFAULT_SETTINGS = (
    WebPSetting(quality=80, method=4),
    WebPSetting(quality=100, method=4),
    WebPSetting(quality=80, method=6),
    WebPSetting(quality=100, method=6),
)


@dataclass(frozen=True, slots=True)
class ArchiveInventory:
    path: Path
    png_members: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class SampledMember:
    archive_path: Path
    member_name: str
    archive_png_index: int
    archive_png_count: int
    original_png_bytes: int


@dataclass(frozen=True, slots=True)
class ImageResult:
    setting: str
    quality: int
    method: int
    archive: str
    member: str
    width: int
    height: int
    mode: str
    grayscale: bool
    original_png_bytes: int
    webp_bytes: int
    saved_bytes: int
    saved_percent: float
    encode_seconds: float
    pixel_equal: bool


@dataclass(slots=True)
class GroupSummary:
    images: int = 0
    png_total: int = 0
    webp_total: int = 0
    saved_bytes: int = 0
    encode_seconds: list[float] = field(default_factory=list)
    mismatch_count: int = 0
    saving_percents: list[float] = field(default_factory=list)

    def add(self, result: ImageResult) -> None:
        self.images += 1
        self.png_total += result.original_png_bytes
        self.webp_total += result.webp_bytes
        self.saved_bytes += result.saved_bytes
        self.encode_seconds.append(result.encode_seconds)
        self.saving_percents.append(result.saved_percent)
        if not result.pixel_equal:
            self.mismatch_count += 1

    def to_dict(self) -> dict[str, object]:
        return _summary_values(self)


@dataclass(slots=True)
class SettingSummary:
    setting: WebPSetting
    images: int = 0
    png_total: int = 0
    webp_total: int = 0
    saved_bytes: int = 0
    encode_seconds: list[float] = field(default_factory=list)
    mismatch_count: int = 0
    saving_percents: list[float] = field(default_factory=list)
    groups: dict[str, GroupSummary] = field(
        default_factory=lambda: {
            "grayscale": GroupSummary(),
            "color": GroupSummary(),
        }
    )

    def add(self, result: ImageResult) -> None:
        self.images += 1
        self.png_total += result.original_png_bytes
        self.webp_total += result.webp_bytes
        self.saved_bytes += result.saved_bytes
        self.encode_seconds.append(result.encode_seconds)
        self.saving_percents.append(result.saved_percent)
        if not result.pixel_equal:
            self.mismatch_count += 1
        self.groups["grayscale" if result.grayscale else "color"].add(result)

    def to_dict(self) -> dict[str, object]:
        values = _summary_values(self)
        values["quality"] = self.setting.quality
        values["method"] = self.setting.method
        values["groups"] = {name: group.to_dict() for name, group in self.groups.items()}
        return values


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    inventories: tuple[ArchiveInventory, ...]
    sampled_members: tuple[SampledMember, ...]
    image_results: tuple[ImageResult, ...]
    summaries: dict[str, SettingSummary]
    max_images: int

    @property
    def mismatch_count(self) -> int:
        return sum(summary.mismatch_count for summary in self.summaries.values())

    @property
    def sampled_png_total(self) -> int:
        return sum(result.original_png_bytes for result in self.image_results) // len(
            self.summaries
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "max_images": self.max_images,
            "archives": [
                {
                    "path": str(inventory.path),
                    "available_pngs": len(inventory.png_members),
                    "sampled_pngs": sum(
                        member.archive_path == inventory.path
                        for member in self.sampled_members
                    ),
                }
                for inventory in self.inventories
            ],
            "sampled_images": len(self.sampled_members),
            "sampled_png_total": self.sampled_png_total,
            "settings": {
                label: summary.to_dict() for label, summary in self.summaries.items()
            },
            "images": [
                {
                    "setting": result.setting,
                    "quality": result.quality,
                    "method": result.method,
                    "archive": result.archive,
                    "member": result.member,
                    "width": result.width,
                    "height": result.height,
                    "mode": result.mode,
                    "grayscale": result.grayscale,
                    "original_png_bytes": result.original_png_bytes,
                    "webp_bytes": result.webp_bytes,
                    "saved_bytes": result.saved_bytes,
                    "saved_percent": result.saved_percent,
                    "encode_seconds": result.encode_seconds,
                    "pixel_equal": result.pixel_equal,
                }
                for result in self.image_results
            ],
        }


def _summary_values(summary: GroupSummary | SettingSummary) -> dict[str, object]:
    encode_times = summary.encode_seconds
    saving_percents = summary.saving_percents
    return {
        "images": summary.images,
        "png_total": summary.png_total,
        "webp_total": summary.webp_total,
        "saved_bytes": summary.saved_bytes,
        "saved_percent": _saving_percent(summary.png_total, summary.webp_total),
        "average_encode_seconds": statistics.mean(encode_times) if encode_times else 0.0,
        "median_encode_seconds": statistics.median(encode_times) if encode_times else 0.0,
        "total_encode_seconds": sum(encode_times),
        "mismatch_count": summary.mismatch_count,
        "min_image_saving_percent": min(saving_percents) if saving_percents else None,
        "max_image_saving_percent": max(saving_percents) if saving_percents else None,
    }


def _saving_percent(png_total: int, webp_total: int) -> float:
    if png_total == 0:
        return 0.0
    return (png_total - webp_total) / png_total * 100


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def discover_zip_paths(inputs: Iterable[str | Path]) -> tuple[Path, ...]:
    """Resolve ZIP files and directories, deduplicating paths deterministically."""

    discovered: dict[str, Path] = {}
    for raw_input in inputs:
        path = Path(raw_input)
        if not path.exists():
            raise FileNotFoundError(f"input path not found: {path}")
        if path.is_file():
            if path.suffix.lower() != ".zip":
                raise ValueError(f"input file is not a ZIP: {path}")
            candidates = [path]
        elif path.is_dir():
            candidates = [
                candidate
                for candidate in path.rglob("*")
                if candidate.is_file() and candidate.suffix.lower() == ".zip"
            ]
        else:
            raise ValueError(f"input path is neither a file nor directory: {path}")
        for candidate in candidates:
            resolved = candidate.resolve()
            discovered[str(resolved).casefold()] = resolved
    if not discovered:
        raise ValueError("no ZIP files found in the supplied inputs")
    return tuple(sorted(discovered.values(), key=lambda path: path.as_posix().casefold()))


def inspect_archive(path: Path) -> ArchiveInventory:
    """List PNG members without extracting or modifying the archive."""

    with zipfile.ZipFile(path, "r") as archive:
        members = tuple(
            (info.filename, info.file_size)
            for info in archive.infolist()
            if not info.is_dir() and info.filename.lower().endswith(".png")
        )
    return ArchiveInventory(path=path, png_members=members)


def _evenly_spaced_indices(item_count: int, sample_count: int) -> tuple[int, ...]:
    if sample_count <= 0 or item_count <= 0:
        return ()
    if sample_count >= item_count:
        return tuple(range(item_count))
    if sample_count == 1:
        return (item_count // 2,)
    return tuple(
        int(index * (item_count - 1) / (sample_count - 1) + 0.5)
        for index in range(sample_count)
    )


def _allocate_sample_counts(
    available_counts: tuple[int, ...], max_images: int
) -> tuple[int, ...]:
    """Allocate a cap across archives as evenly as their sizes allow."""

    target = min(max_images, sum(available_counts))
    counts = [0] * len(available_counts)
    if target == 0:
        return tuple(counts)

    # With the normal default cap, give every non-empty archive a sample first.
    # If the cap is smaller than the number of archives, the first deterministic
    # archives receive the available slots because visiting every archive is
    # impossible under that cap.
    for index, available in enumerate(available_counts):
        if sum(counts) >= target:
            break
        if available:
            counts[index] = 1

    remaining = target - sum(counts)
    while remaining:
        made_progress = False
        for index, available in enumerate(available_counts):
            if counts[index] < available:
                counts[index] += 1
                remaining -= 1
                made_progress = True
                if remaining == 0:
                    break
        if not made_progress:
            break
    return tuple(counts)


def sample_members(
    inventories: tuple[ArchiveInventory, ...], max_images: int
) -> tuple[SampledMember, ...]:
    """Select a deterministic, evenly distributed subset of PNG members."""

    if max_images <= 0:
        raise ValueError("max_images must be positive")
    allocations = _allocate_sample_counts(
        tuple(len(inventory.png_members) for inventory in inventories), max_images
    )
    selected: list[SampledMember] = []
    for inventory, sample_count in zip(inventories, allocations, strict=True):
        indices = _evenly_spaced_indices(len(inventory.png_members), sample_count)
        for index in indices:
            name, original_bytes = inventory.png_members[index]
            selected.append(
                SampledMember(
                    archive_path=inventory.path,
                    member_name=name,
                    archive_png_index=index,
                    archive_png_count=len(inventory.png_members),
                    original_png_bytes=original_bytes,
                )
            )
    return tuple(selected)


def _is_grayscale(image: Image.Image) -> bool:
    """Return whether every visible RGB pixel has R == G == B."""

    rgb = image.convert("RGB")
    red, green, blue = rgb.split()
    try:
        return (
            ImageChops.difference(red, green).getbbox() is None
            and ImageChops.difference(red, blue).getbbox() is None
        )
    finally:
        red.close()
        green.close()
        blue.close()
        rgb.close()


def encode_lossless_webp(image: Image.Image, setting: WebPSetting) -> bytes:
    """Encode the supplied decoded pixels with one lossless WebP setting."""

    output = BytesIO()
    image.save(
        output,
        format="WEBP",
        lossless=True,
        quality=setting.quality,
        method=setting.method,
        # Keep hidden RGB values in fully transparent pixels for exact RGBA
        # round-trip verification.
        exact=True,
    )
    return output.getvalue()


def _pixel_equal(image: Image.Image, webp_bytes: bytes, original_rgba: bytes) -> bool:
    with Image.open(BytesIO(webp_bytes)) as decoded:
        decoded.load()
        return (
            decoded.size == image.size
            and decoded.convert("RGBA").tobytes() == original_rgba
        )


def benchmark_image(
    png_bytes: bytes,
    member: SampledMember,
    settings: Iterable[WebPSetting] = DEFAULT_SETTINGS,
) -> tuple[ImageResult, ...]:
    """Benchmark every setting for one PNG and verify decoded pixels."""

    with Image.open(BytesIO(png_bytes)) as image:
        image.load()
        original_rgba = image.convert("RGBA").tobytes()
        grayscale = _is_grayscale(image)
        results: list[ImageResult] = []
        for setting in settings:
            started = time.perf_counter()
            webp_bytes = encode_lossless_webp(image, setting)
            encode_seconds = time.perf_counter() - started
            saved_bytes = len(png_bytes) - len(webp_bytes)
            results.append(
                ImageResult(
                    setting=setting.label,
                    quality=setting.quality,
                    method=setting.method,
                    archive=str(member.archive_path),
                    member=member.member_name,
                    width=image.width,
                    height=image.height,
                    mode=image.mode,
                    grayscale=grayscale,
                    original_png_bytes=len(png_bytes),
                    webp_bytes=len(webp_bytes),
                    saved_bytes=saved_bytes,
                    saved_percent=saved_bytes / len(png_bytes) * 100
                    if png_bytes
                    else 0.0,
                    encode_seconds=encode_seconds,
                    pixel_equal=_pixel_equal(image, webp_bytes, original_rgba),
                )
            )
    return tuple(results)


def benchmark_paths(
    inputs: Iterable[str | Path],
    *,
    max_images: int = 100,
    settings: Iterable[WebPSetting] = DEFAULT_SETTINGS,
) -> BenchmarkReport:
    """Run the read-only benchmark for ZIP files and/or directories."""

    if not features.check("webp"):
        raise RuntimeError("the installed Pillow build does not provide WebP support")
    settings_tuple = tuple(settings)
    if not settings_tuple:
        raise ValueError("at least one WebP setting is required")
    paths = discover_zip_paths(inputs)
    inventories = tuple(inspect_archive(path) for path in paths)
    sampled_members = sample_members(inventories, max_images)
    if not sampled_members:
        raise ValueError("the supplied ZIP files contain no PNG members")

    summaries = {setting.label: SettingSummary(setting) for setting in settings_tuple}
    image_results: list[ImageResult] = []
    sampled_by_archive: dict[Path, list[SampledMember]] = defaultdict(list)
    for member in sampled_members:
        sampled_by_archive[member.archive_path].append(member)

    for path in paths:
        with zipfile.ZipFile(path, "r") as archive:
            for member in sampled_by_archive[path]:
                png_bytes = archive.read(member.member_name)
                results = benchmark_image(png_bytes, member, settings_tuple)
                image_results.extend(results)
                for result in results:
                    summaries[result.setting].add(result)

    return BenchmarkReport(
        inventories=inventories,
        sampled_members=sampled_members,
        image_results=tuple(image_results),
        summaries=summaries,
        max_images=max_images,
    )


def _format_bytes(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB")
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}" if unit != "B" else f"{value} B"
        amount /= 1024
    return f"{value} B"


def _format_seconds(value: float) -> str:
    if value < 1:
        return f"{value * 1000:.1f} ms"
    return f"{value:.2f} s"


def _display_archive_path(path: Path, *, max_length: int = 72) -> str:
    try:
        display = path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        display = path.as_posix()
    if len(display) <= max_length:
        return display
    prefix_length = (max_length - 3) // 2
    suffix_length = max_length - 3 - prefix_length
    return f"{display[:prefix_length]}...{display[-suffix_length:]}"


def _print_table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))
    print("  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))


def _print_report(report: BenchmarkReport) -> None:
    first_summary = next(iter(report.summaries.values()))
    grayscale_count = first_summary.groups["grayscale"].images
    color_count = first_summary.groups["color"].images
    print("BookWalker PNG -> lossless WebP benchmark (selected ZIPs, read-only)")
    print(f"ZIPs: {len(report.inventories)}")
    print(
        f"Sampled PNGs: {len(report.sampled_members)} / cap {report.max_images} "
        f"(grayscale: {grayscale_count}, color: {color_count})"
    )
    print(f"Sampled PNG total: {_format_bytes(report.sampled_png_total)}")
    print("Input archive sampling:")
    _print_table(
        ["Archive", "Available PNGs", "Sampled"],
        [
            [
                _display_archive_path(inventory.path),
                str(len(inventory.png_members)),
                str(
                    sum(
                        member.archive_path == inventory.path
                        for member in report.sampled_members
                    )
                ),
            ]
            for inventory in report.inventories
        ],
    )

    print("\nSetting totals:")
    rows = []
    for summary in report.summaries.values():
        values = _summary_values(summary)
        rows.append(
            [
                summary.setting.label,
                str(summary.images),
                _format_bytes(summary.png_total),
                _format_bytes(summary.webp_total),
                _format_bytes(summary.saved_bytes),
                f"{values['saved_percent']:.2f}%",
                _format_seconds(values["average_encode_seconds"]),
                _format_seconds(values["median_encode_seconds"]),
                _format_seconds(values["total_encode_seconds"]),
                str(summary.mismatch_count),
                f"{values['min_image_saving_percent']:.2f}%"
                if values["min_image_saving_percent"] is not None
                else "-",
                f"{values['max_image_saving_percent']:.2f}%"
                if values["max_image_saving_percent"] is not None
                else "-",
            ]
        )
    _print_table(
        [
            "Setting",
            "Images",
            "PNG total",
            "WebP total",
            "Saved",
            "Saved %",
            "Avg encode",
            "Median",
            "Total encode",
            "Mismatch",
            "Min/img",
            "Max/img",
        ],
        rows,
    )

    print("\nGrayscale / color totals:")
    group_rows = []
    for summary in report.summaries.values():
        for group_name in ("grayscale", "color"):
            group = summary.groups[group_name]
            if not group.images:
                continue
            values = _summary_values(group)
            group_rows.append(
                [
                    summary.setting.label,
                    group_name,
                    str(group.images),
                    _format_bytes(group.png_total),
                    _format_bytes(group.webp_total),
                    _format_bytes(group.saved_bytes),
                    f"{values['saved_percent']:.2f}%",
                    _format_seconds(values["average_encode_seconds"]),
                    _format_seconds(values["median_encode_seconds"]),
                    _format_seconds(values["total_encode_seconds"]),
                    str(group.mismatch_count),
                ]
            )
    _print_table(
        [
            "Setting",
            "Group",
            "Images",
            "PNG total",
            "WebP total",
            "Saved",
            "Saved %",
            "Avg encode",
            "Median",
            "Total encode",
            "Mismatch",
        ],
        group_rows,
    )

    mismatches = [result for result in report.image_results if not result.pixel_equal]
    if mismatches:
        print("\nPixel equality: FAIL")
        print("The following setting/image pairs did not match after RGBA normalization:")
        _print_table(
            ["Setting", "Archive", "Member", "Dimensions", "Mode"],
            [
                [
                    result.setting,
                    _display_archive_path(Path(result.archive)),
                    result.member,
                    f"{result.width}x{result.height}",
                    result.mode,
                ]
                for result in mismatches
            ],
        )
    else:
        print(
            f"\nPixel equality: PASS (0 mismatches across "
            f"{len(report.image_results)} setting/image pairs)"
        )
    print("Per-image measurements are included when --json-output is supplied.")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark Pillow lossless WebP settings for PNG members in user-selected ZIPs "
            "without extracting or modifying them."
        )
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        metavar="PATH",
        help="ZIP file(s) and/or directories searched recursively for ZIP files",
    )
    parser.add_argument(
        "--max-images",
        type=_positive_int,
        default=100,
        help="maximum PNGs sampled across all input ZIPs (default: 100)",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        help="write per-image and aggregate measurements to this JSON path",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        report = benchmark_paths(args.paths, max_images=args.max_images)
        if args.json_output is not None:
            args.json_output.parent.mkdir(parents=True, exist_ok=True)
            args.json_output.write_text(
                json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    _print_report(report)
    return 1 if report.mismatch_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
