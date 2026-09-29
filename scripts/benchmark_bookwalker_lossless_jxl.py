#!/usr/bin/env python3
"""Benchmark lossless JPEG XL encodes for PNGs already stored in ZIP archives.

This is an investigation-only benchmark.  The input archives are opened
read-only and PNG members are decoded directly from memory; no archive is
rewritten and no PNG is extracted to disk.

The optional ``pillow-jxl-plugin`` package provides Pillow's JXL encoder and
decoder.  Install it in the benchmark environment with::

    uv pip install --python .venv\\Scripts\\python.exe pillow-jxl-plugin

Example::

    python scripts/benchmark_bookwalker_lossless_jxl.py \\
        "output/Books/ライトノベル/わたし、二番目の彼女でいいから。/わたし、二番目の彼女でいいから。-第01巻-西 条陽.zip" \\
        "output/Books/ライトノベル/アクセル・ワールド/アクセル・ワールド-アクセル・ワールド21 -雪の妖精--川原礫.zip" \\
        "output/Books/ライトノベル/スパイ教室/スパイ教室-スパイ教室06 《百鬼》のジビア-竹町.zip" \\
        --max-images 100 \\
        --json-output output/diagnostics/bookwalker-lossless-jxl/comparison.json

The script does not infer site provenance.  Every ZIP explicitly supplied by
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

from PIL import Image, features

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from benchmark_bookwalker_lossless_webp import (
    ArchiveInventory,
    SampledMember,
    WebPSetting,
    _display_archive_path,
    _format_bytes,
    _format_seconds,
    _is_grayscale,
    _positive_int,
    _print_table,
    discover_zip_paths,
    encode_lossless_webp,
    inspect_archive,
    sample_members,
)


@dataclass(frozen=True, slots=True)
class JXLSetting:
    """One libjxl effort setting used by the Pillow plugin."""

    effort: int

    def __post_init__(self) -> None:
        if not 1 <= self.effort <= 10:
            raise ValueError("JPEG XL effort must be between 1 and 10")

    @property
    def label(self) -> str:
        return f"jxl/e{self.effort}"


@dataclass(frozen=True, slots=True)
class BenchmarkSetting:
    """One WebP baseline or JPEG XL comparison setting."""

    codec: str
    webp: WebPSetting | None = None
    jxl: JXLSetting | None = None

    @classmethod
    def webp_setting(cls, quality: int, method: int) -> BenchmarkSetting:
        return cls(codec="webp", webp=WebPSetting(quality=quality, method=method))

    @classmethod
    def jxl_setting(cls, effort: int) -> BenchmarkSetting:
        return cls(codec="jxl", jxl=JXLSetting(effort=effort))

    @property
    def label(self) -> str:
        if self.codec == "webp" and self.webp is not None:
            return f"webp {self.webp.label}"
        if self.codec == "jxl" and self.jxl is not None:
            return self.jxl.label
        raise ValueError("invalid benchmark setting")


DEFAULT_SETTINGS = (
    BenchmarkSetting.webp_setting(quality=40, method=2),
    BenchmarkSetting.webp_setting(quality=80, method=4),
    BenchmarkSetting.jxl_setting(effort=1),
    BenchmarkSetting.jxl_setting(effort=5),
    BenchmarkSetting.jxl_setting(effort=9),
)
BASELINE_LABEL = "webp q40/m2"
_JXL_MODES = {"RGB", "RGBA", "L", "LA", "I;16", "F"}


@dataclass(frozen=True, slots=True)
class ImageResult:
    setting: str
    codec: str
    archive: str
    member: str
    width: int
    height: int
    mode: str
    grayscale: bool
    original_png_bytes: int
    encoded_bytes: int
    saved_bytes: int
    saved_percent: float
    encode_seconds: float
    pixel_equal: bool


@dataclass(slots=True)
class GroupSummary:
    images: int = 0
    png_total: int = 0
    encoded_total: int = 0
    saved_bytes: int = 0
    encode_seconds: list[float] = field(default_factory=list)
    mismatch_count: int = 0
    saving_percents: list[float] = field(default_factory=list)
    png_larger_count: int = 0

    def add(self, result: ImageResult) -> None:
        self.images += 1
        self.png_total += result.original_png_bytes
        self.encoded_total += result.encoded_bytes
        self.saved_bytes += result.saved_bytes
        self.encode_seconds.append(result.encode_seconds)
        self.saving_percents.append(result.saved_percent)
        if not result.pixel_equal:
            self.mismatch_count += 1
        if result.saved_bytes < 0:
            self.png_larger_count += 1


@dataclass(slots=True)
class SettingSummary(GroupSummary):
    setting: BenchmarkSetting | None = None
    groups: dict[str, GroupSummary] = field(
        default_factory=lambda: {
            "grayscale": GroupSummary(),
            "color": GroupSummary(),
        }
    )

    def add(self, result: ImageResult) -> None:
        super().add(result)
        self.groups["grayscale" if result.grayscale else "color"].add(result)


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
        return sum(member.original_png_bytes for member in self.sampled_members)

    def to_dict(self) -> dict[str, object]:
        return {
            "max_images": self.max_images,
            "baseline_setting": BASELINE_LABEL,
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
                label: _setting_values(summary)
                for label, summary in self.summaries.items()
            },
            "images": [
                {
                    "setting": result.setting,
                    "codec": result.codec,
                    "archive": result.archive,
                    "member": result.member,
                    "width": result.width,
                    "height": result.height,
                    "mode": result.mode,
                    "grayscale": result.grayscale,
                    "original_png_bytes": result.original_png_bytes,
                    "encoded_bytes": result.encoded_bytes,
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
        "encoded_total": summary.encoded_total,
        "saved_bytes": summary.saved_bytes,
        "saved_percent": _saving_percent(summary.png_total, summary.encoded_total),
        "average_encode_seconds": statistics.mean(encode_times) if encode_times else 0.0,
        "median_encode_seconds": statistics.median(encode_times) if encode_times else 0.0,
        "total_encode_seconds": sum(encode_times),
        "mismatch_count": summary.mismatch_count,
        "min_image_saving_percent": min(saving_percents) if saving_percents else None,
        "max_image_saving_percent": max(saving_percents) if saving_percents else None,
        "png_larger_count": summary.png_larger_count,
    }


def _setting_values(summary: SettingSummary) -> dict[str, object]:
    values = _summary_values(summary)
    values["codec"] = summary.setting.codec if summary.setting else None
    values["groups"] = {
        name: _summary_values(group) for name, group in summary.groups.items()
    }
    return values


def _saving_percent(png_total: int, encoded_total: int) -> float:
    if png_total == 0:
        return 0.0
    return (png_total - encoded_total) / png_total * 100


def _load_jxl_support() -> None:
    """Import the optional Pillow plugin, which registers JXL with Pillow."""

    try:
        import pillow_jxl  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "JPEG XL benchmark requires the optional 'pillow-jxl-plugin' package; "
            "install it with 'uv pip install pillow-jxl-plugin'"
        ) from exc


def encode_lossless_jxl(image: Image.Image, setting: JXLSetting) -> bytes:
    """Encode decoded pixels as lossless JPEG XL at one libjxl effort."""

    _load_jxl_support()
    output = BytesIO()
    image.save(
        output,
        format="JXL",
        lossless=True,
        effort=setting.effort,
    )
    return output.getvalue()


def _jxl_source_image(image: Image.Image) -> Image.Image:
    """Return an encoder-compatible view without grayscale optimization."""

    if image.mode in _JXL_MODES:
        return image
    # Palette and other uncommon PNG modes are normalized to visible RGBA
    # pixels only because the Pillow JXL plugin has no encoder for those modes.
    return image.convert("RGBA")


def _pixel_equal(encoded_bytes: bytes, original_size: tuple[int, int], original_rgba: bytes) -> bool:
    with Image.open(BytesIO(encoded_bytes)) as decoded:
        decoded.load()
        return (
            decoded.size == original_size
            and decoded.convert("RGBA").tobytes() == original_rgba
        )


def _encode(setting: BenchmarkSetting, image: Image.Image) -> bytes:
    if setting.codec == "webp" and setting.webp is not None:
        return encode_lossless_webp(image, setting.webp)
    if setting.codec == "jxl" and setting.jxl is not None:
        return encode_lossless_jxl(image, setting.jxl)
    raise ValueError(f"invalid benchmark setting: {setting!r}")


def benchmark_image(
    png_bytes: bytes,
    member: SampledMember,
    settings: Iterable[BenchmarkSetting] = DEFAULT_SETTINGS,
) -> tuple[ImageResult, ...]:
    """Benchmark every setting for one PNG and verify decoded RGBA pixels."""

    settings_tuple = tuple(settings)
    with Image.open(BytesIO(png_bytes)) as image:
        image.load()
        original_rgba = image.convert("RGBA").tobytes()
        grayscale = _is_grayscale(image)
        jxl_image = _jxl_source_image(image)
        try:
            results: list[ImageResult] = []
            for setting in settings_tuple:
                started = time.perf_counter()
                encoded = _encode(setting, jxl_image if setting.codec == "jxl" else image)
                encode_seconds = time.perf_counter() - started
                saved_bytes = len(png_bytes) - len(encoded)
                results.append(
                    ImageResult(
                        setting=setting.label,
                        codec=setting.codec,
                        archive=str(member.archive_path),
                        member=member.member_name,
                        width=image.width,
                        height=image.height,
                        mode=image.mode,
                        grayscale=grayscale,
                        original_png_bytes=len(png_bytes),
                        encoded_bytes=len(encoded),
                        saved_bytes=saved_bytes,
                        saved_percent=saved_bytes / len(png_bytes) * 100
                        if png_bytes
                        else 0.0,
                        encode_seconds=encode_seconds,
                        pixel_equal=_pixel_equal(encoded, image.size, original_rgba),
                    )
                )
        finally:
            if jxl_image is not image:
                jxl_image.close()
    return tuple(results)


def benchmark_paths(
    inputs: Iterable[str | Path],
    *,
    max_images: int = 100,
    settings: Iterable[BenchmarkSetting] = DEFAULT_SETTINGS,
) -> BenchmarkReport:
    """Run the read-only benchmark for ZIP files and/or directories."""

    _load_jxl_support()
    if not features.check("webp"):
        raise RuntimeError("the installed Pillow build does not provide WebP support")
    settings_tuple = tuple(settings)
    if not settings_tuple:
        raise ValueError("at least one benchmark setting is required")
    paths = discover_zip_paths(inputs)
    inventories = tuple(inspect_archive(path) for path in paths)
    sampled_members = sample_members(inventories, max_images)
    if not sampled_members:
        raise ValueError("the supplied ZIP files contain no PNG members")

    summaries = {
        setting.label: SettingSummary(setting=setting) for setting in settings_tuple
    }
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


def _print_report(report: BenchmarkReport) -> None:
    first_summary = next(iter(report.summaries.values()))
    grayscale_count = first_summary.groups["grayscale"].images
    color_count = first_summary.groups["color"].images
    print("BookWalker PNG -> lossless JPEG XL benchmark (selected ZIPs, read-only)")
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
                summary.setting.label if summary.setting else "-",
                str(summary.images),
                _format_bytes(summary.png_total),
                _format_bytes(summary.encoded_total),
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
                str(summary.png_larger_count),
            ]
        )
    _print_table(
        [
            "Setting",
            "Images",
            "PNG total",
            "Encoded total",
            "Saved",
            "Saved %",
            "Avg encode",
            "Median",
            "Total encode",
            "Mismatch",
            "Min/img",
            "Max/img",
            "PNG larger",
        ],
        rows,
    )

    baseline = report.summaries.get(BASELINE_LABEL)
    if baseline is not None:
        baseline_values = _summary_values(baseline)
        print("\nDifference from WebP q40/m2 baseline:")
        delta_rows = []
        for summary in report.summaries.values():
            values = _summary_values(summary)
            total_seconds = values["total_encode_seconds"]
            baseline_seconds = baseline_values["total_encode_seconds"]
            ratio = total_seconds / baseline_seconds if baseline_seconds else 0.0
            delta_rows.append(
                [
                    summary.setting.label if summary.setting else "-",
                    _format_bytes(summary.encoded_total - baseline.encoded_total),
                    f"{values['saved_percent'] - baseline_values['saved_percent']:+.2f} pt",
                    _format_seconds(total_seconds - baseline_seconds),
                    f"{ratio:.2f}x",
                ]
            )
        _print_table(
            ["Setting", "Encoded Δ", "Saved Δ", "Total time Δ", "Time vs baseline"],
            delta_rows,
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
                    summary.setting.label if summary.setting else "-",
                    group_name,
                    str(group.images),
                    _format_bytes(group.png_total),
                    _format_bytes(group.encoded_total),
                    f"{values['saved_percent']:.2f}%",
                    _format_seconds(values["total_encode_seconds"]),
                    f"{values['min_image_saving_percent']:.2f}%",
                    str(group.png_larger_count),
                    str(group.mismatch_count),
                ]
            )
    _print_table(
        [
            "Setting",
            "Group",
            "Images",
            "PNG total",
            "Encoded total",
            "Saved %",
            "Total encode",
            "Min/img",
            "PNG larger",
            "Mismatch",
        ],
        group_rows,
    )

    outliers = sorted(
        (result for result in report.image_results if result.saved_bytes < 0),
        key=lambda result: result.saved_bytes,
    )
    if outliers:
        print("\nImages where encoded output is larger than PNG (up to 10 per worst overage):")
        _print_table(
            ["Setting", "Group", "Archive", "Member", "PNG", "Encoded", "Saved %"],
            [
                [
                    result.setting,
                    "grayscale" if result.grayscale else "color",
                    _display_archive_path(Path(result.archive)),
                    result.member,
                    _format_bytes(result.original_png_bytes),
                    _format_bytes(result.encoded_bytes),
                    f"{result.saved_percent:.2f}%",
                ]
                for result in outliers[:10]
            ],
        )
    else:
        print("\nPNG larger outliers: none")

    mismatches = [result for result in report.image_results if not result.pixel_equal]
    if mismatches:
        print("\nPixel equality: FAIL")
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
            "Benchmark lossless JPEG XL effort settings and WebP baselines for PNG "
            "members in user-selected ZIPs without extracting or modifying them."
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
    except (OSError, RuntimeError, ValueError, ImportError, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    _print_report(report)
    return 1 if report.mismatch_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
