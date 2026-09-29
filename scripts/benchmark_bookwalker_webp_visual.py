#!/usr/bin/env python3
"""Create human-inspectable lossy WebP comparisons for selected PNG pages.

The source PNGs are read-only.  A page can be supplied as an extracted PNG
path or as ``ZIP::member.png``.  This benchmark intentionally does not infer
production policy from image heuristics; page categories are user labels only.

Example::

    python scripts/benchmark_bookwalker_webp_visual.py \
        --text-page "output/book/page-0151.png" \
        --text-page "output/book/page-0152.png" \
        --text-page "output/book/page-0153.png" \
        --illustration-page "output/book/page-0079.png" \
        --illustration-page "output/book/page-0130.png" \
        --illustration-page "output/book/page-0159.png" \
        --output-dir output/diagnostics/bookwalker-webp-visual

Near-lossless is reported as unavailable when the installed Pillow WebP
encoder does not expose that option.  The script never silently treats an
unknown ``near_lossless`` keyword as supported.
"""

from __future__ import annotations

import argparse
import inspect
import json
import math
import shutil
import sys
import time
import zipfile
from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageChops, ImageStat, WebPImagePlugin


@dataclass(frozen=True, slots=True)
class PageSpec:
    source: str
    kind: str
    label: str


@dataclass(frozen=True, slots=True)
class Variant:
    label: str
    quality: int
    lossless: bool
    method: int = 2


VARIANTS = (
    Variant("lossless-q40-m2", quality=40, lossless=True),
    Variant("lossy-q95-m2", quality=95, lossless=False),
    Variant("lossy-q90-m2", quality=90, lossless=False),
    Variant("lossy-q85-m2", quality=85, lossless=False),
    Variant("lossy-q80-m2", quality=80, lossless=False),
    Variant("lossy-q70-m2", quality=70, lossless=False),
)


@dataclass(frozen=True, slots=True)
class PageInput:
    spec: PageSpec
    source_label: str
    png_bytes: bytes


@dataclass(frozen=True, slots=True)
class VariantResult:
    page: str
    kind: str
    source: str
    variant: str
    width: int
    height: int
    mode: str
    original_png_bytes: int
    webp_bytes: int
    saved_bytes: int
    saved_percent: float
    encode_seconds: float
    decode_seconds: float
    psnr_db: float | None
    global_ssim: float | None
    mean_absolute_error: float
    max_absolute_difference: int
    changed_pixel_count: int
    pixel_exact: bool
    alpha_exact: bool
    webp_path: str


def _format_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if amount < 1024 or unit == "GiB":
            return f"{amount:.1f} {unit}" if unit != "B" else f"{value} B"
        amount /= 1024
    return f"{value} B"


def _format_seconds(value: float) -> str:
    return f"{value * 1000:.1f} ms" if value < 1 else f"{value:.2f} s"


def _print_table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))
    print("  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _page_label(source: str) -> str:
    if "::" in source:
        return Path(source.split("::", 1)[1]).stem
    return Path(source).stem


def _read_page(spec: PageSpec) -> PageInput:
    if "::" in spec.source:
        archive_path, member_name = spec.source.split("::", 1)
        archive = Path(archive_path)
        with zipfile.ZipFile(archive, "r") as handle:
            try:
                png_bytes = handle.read(member_name)
            except KeyError as exc:
                raise ValueError(f"ZIP member not found: {spec.source}") from exc
        return PageInput(spec, spec.source, png_bytes)

    path = Path(spec.source)
    if path.suffix.lower() != ".png":
        raise ValueError(f"page input is not a PNG: {path}")
    return PageInput(spec, str(path), path.read_bytes())


def _encode_webp(image: Image.Image, variant: Variant) -> bytes:
    output = BytesIO()
    image.save(
        output,
        format="WEBP",
        lossless=variant.lossless,
        quality=variant.quality,
        method=variant.method,
        exact=True,
    )
    return output.getvalue()


def _decoded_image(webp_bytes: bytes) -> Image.Image:
    decoded = Image.open(BytesIO(webp_bytes))
    decoded.load()
    return decoded


def _global_ssim(original: Image.Image, decoded: Image.Image) -> float:
    original_l = original.convert("L")
    decoded_l = decoded.convert("L")
    try:
        original_stat = ImageStat.Stat(original_l)
        decoded_stat = ImageStat.Stat(decoded_l)
        original_mean = original_stat.mean[0]
        decoded_mean = decoded_stat.mean[0]
        original_var = original_stat.var[0]
        decoded_var = decoded_stat.var[0]
        product = ImageChops.multiply(original_l, decoded_l)
        product_mean = ImageStat.Stat(product).mean[0] * 255
        covariance = product_mean - original_mean * decoded_mean
        c1 = 6.5025
        c2 = 58.5225
        numerator = (2 * original_mean * decoded_mean + c1) * (2 * covariance + c2)
        denominator = (
            (original_mean**2 + decoded_mean**2 + c1)
            * (original_var + decoded_var + c2)
        )
        return numerator / denominator if denominator else 1.0
    finally:
        original_l.close()
        decoded_l.close()


def _image_metrics(original: Image.Image, decoded: Image.Image) -> dict[str, object]:
    original_rgb = original.convert("RGB")
    decoded_rgb = decoded.convert("RGB")
    difference = ImageChops.difference(original_rgb, decoded_rgb)
    try:
        histogram = difference.histogram()
        pixel_count = original.width * original.height
        channel_count = pixel_count * 3
        squared_error = sum((index % 256) ** 2 * count for index, count in enumerate(histogram))
        absolute_error = sum((index % 256) * count for index, count in enumerate(histogram))
        mse = squared_error / channel_count if channel_count else 0.0
        mae = absolute_error / channel_count if channel_count else 0.0
        psnr = None if mse == 0 else 10 * math.log10((255**2) / mse)
        nonzero = [index % 256 for index, count in enumerate(histogram) if count]
        max_difference = max(nonzero, default=0)
        red, green, blue = difference.split()
        changed_mask = ImageChops.lighter(ImageChops.lighter(red, green), blue)
        try:
            changed_pixels = pixel_count - changed_mask.histogram()[0]
        finally:
            red.close()
            green.close()
            blue.close()
            changed_mask.close()
        original_rgba = original.convert("RGBA")
        decoded_rgba = decoded.convert("RGBA")
        try:
            pixel_exact = original_rgba.tobytes() == decoded_rgba.tobytes()
            alpha_exact = original_rgba.getchannel("A").tobytes() == decoded_rgba.getchannel(
                "A"
            ).tobytes()
        finally:
            original_rgba.close()
            decoded_rgba.close()
        return {
            "psnr_db": psnr,
            "global_ssim": 1.0 if pixel_exact else _global_ssim(original, decoded),
            "mean_absolute_error": mae,
            "max_absolute_difference": max_difference,
            "changed_pixel_count": changed_pixels,
            "pixel_exact": pixel_exact,
            "alpha_exact": alpha_exact,
        }
    finally:
        original_rgb.close()
        decoded_rgb.close()
        difference.close()


def _crop_boxes(size: tuple[int, int]) -> dict[str, tuple[int, int, int, int]]:
    width, height = size
    return {
        "center": (int(width * 0.20), int(height * 0.30), int(width * 0.80), int(height * 0.70)),
        "upper": (int(width * 0.20), int(height * 0.08), int(width * 0.80), int(height * 0.30)),
        "lower": (int(width * 0.20), int(height * 0.70), int(width * 0.80), int(height * 0.92)),
    }


def _near_lossless_status() -> dict[str, object]:
    pillow_source = inspect.getsource(WebPImagePlugin._save)
    pillow_support = "near_lossless" in pillow_source
    cwebp = shutil.which("cwebp")
    if pillow_support:
        return {
            "supported": True,
            "path": "Pillow WebP encoder",
            "reason": "Pillow WebP encoder source exposes near_lossless",
        }
    return {
        "supported": False,
        "path": None,
        "reason": (
            "Pillow WebP encoder does not expose near_lossless"
            + ("; cwebp is available but not invoked by this Pillow-only benchmark" if cwebp else "; cwebp was not found")
        ),
    }


def _variant_result(
    page: PageInput,
    variant: Variant,
    image: Image.Image,
    webp_bytes: bytes,
    decoded: Image.Image,
    encode_seconds: float,
    decode_seconds: float,
    webp_path: Path,
) -> VariantResult:
    saved_bytes = len(page.png_bytes) - len(webp_bytes)
    metrics = _image_metrics(image, decoded)
    return VariantResult(
        page=page.spec.label,
        kind=page.spec.kind,
        source=page.source_label,
        variant=variant.label,
        width=image.width,
        height=image.height,
        mode=image.mode,
        original_png_bytes=len(page.png_bytes),
        webp_bytes=len(webp_bytes),
        saved_bytes=saved_bytes,
        saved_percent=saved_bytes / len(page.png_bytes) * 100 if page.png_bytes else 0.0,
        encode_seconds=encode_seconds,
        decode_seconds=decode_seconds,
        psnr_db=metrics["psnr_db"],
        global_ssim=metrics["global_ssim"],
        mean_absolute_error=metrics["mean_absolute_error"],
        max_absolute_difference=metrics["max_absolute_difference"],
        changed_pixel_count=metrics["changed_pixel_count"],
        pixel_exact=metrics["pixel_exact"],
        alpha_exact=metrics["alpha_exact"],
        webp_path=str(webp_path),
    )


def benchmark_pages(
    specs: list[PageSpec],
    output_dir: Path,
    variants: tuple[Variant, ...] = VARIANTS,
) -> tuple[list[VariantResult], dict[str, object]]:
    if not specs:
        raise ValueError("at least one page must be supplied")
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[VariantResult] = []
    page_outputs: list[dict[str, object]] = []

    for page in (_read_page(spec) for spec in specs):
        with Image.open(BytesIO(page.png_bytes)) as image:
            image.load()
            page_dir = output_dir / f"{page.spec.label}-{page.spec.kind}"
            page_dir.mkdir(parents=True, exist_ok=True)
            (page_dir / "original.png").write_bytes(page.png_bytes)
            crops_dir = page_dir / "crops"
            crops_dir.mkdir(exist_ok=True)
            boxes = _crop_boxes(image.size)
            for name, box in boxes.items():
                with image.crop(box) as crop:
                    crop.save(crops_dir / f"original-{name}.png", format="PNG")

            variant_outputs: list[str] = []
            for variant in variants:
                started = time.perf_counter()
                webp_bytes = _encode_webp(image, variant)
                encode_seconds = time.perf_counter() - started
                webp_path = page_dir / f"{variant.label}.webp"
                webp_path.write_bytes(webp_bytes)
                variant_outputs.append(str(webp_path))

                decode_started = time.perf_counter()
                decoded = _decoded_image(webp_bytes)
                decode_seconds = time.perf_counter() - decode_started
                try:
                    for name, box in boxes.items():
                        with decoded.crop(box) as crop:
                            crop.save(crops_dir / f"{variant.label}-{name}.png", format="PNG")
                    results.append(
                        _variant_result(
                            page,
                            variant,
                            image,
                            webp_bytes,
                            decoded,
                            encode_seconds,
                            decode_seconds,
                            webp_path,
                        )
                    )
                finally:
                    decoded.close()
            page_outputs.append(
                {
                    "page": page.spec.label,
                    "kind": page.spec.kind,
                    "source": page.source_label,
                    "output_dir": str(page_dir),
                    "crop_boxes": {name: list(box) for name, box in boxes.items()},
                    "variants": variant_outputs,
                }
            )

    metadata = {
        "near_lossless": _near_lossless_status(),
        "variants": [asdict(variant) for variant in variants],
        "pages": page_outputs,
    }
    return results, metadata


def _write_summary(
    results: list[VariantResult], metadata: dict[str, object], output_dir: Path
) -> Path:
    payload = {
        **metadata,
        "results": [asdict(result) for result in results],
    }
    summary_path = output_dir / "summary.json"
    summary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return summary_path


def _print_report(results: list[VariantResult], metadata: dict[str, object]) -> None:
    print("BookWalker PNG -> visual WebP comparison (read-only inputs)")
    print(f"Pages: {len({result.page for result in results})}")
    print(
        "Near-lossless: "
        + ("available" if metadata["near_lossless"]["supported"] else "NOT RUN")
        + f" ({metadata['near_lossless']['reason']})"
    )
    _print_table(
        [
            "Page",
            "Kind",
            "Variant",
            "PNG",
            "WebP",
            "Saved",
            "Encode",
            "PSNR dB",
            "SSIM",
            "Changed px",
            "Exact",
        ],
        [
            [
                result.page,
                result.kind,
                result.variant,
                _format_bytes(result.original_png_bytes),
                _format_bytes(result.webp_bytes),
                f"{result.saved_percent:.2f}%",
                _format_seconds(result.encode_seconds),
                f"{result.psnr_db:.2f}" if result.psnr_db is not None else "inf",
                f"{result.global_ssim:.6f}" if result.global_ssim is not None else "-",
                str(result.changed_pixel_count),
                "yes" if result.pixel_exact else "no",
            ]
            for result in results
        ],
    )
    print("\nResults and crops are stored under the requested output directory.")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create lossy/near-lossless WebP visual comparison artifacts for selected PNGs."
    )
    parser.add_argument(
        "--page",
        action="append",
        default=[],
        metavar="PATH_OR_ZIP::MEMBER",
        help="selected PNG path or ZIP::member; category remains unspecified",
    )
    parser.add_argument(
        "--text-page",
        action="append",
        default=[],
        metavar="PATH_OR_ZIP::MEMBER",
        help="selected page labeled text-heavy",
    )
    parser.add_argument(
        "--illustration-page",
        action="append",
        default=[],
        metavar="PATH_OR_ZIP::MEMBER",
        help="selected page labeled illustration",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/diagnostics/bookwalker-webp-visual"),
        help="directory for original/variant/crop artifacts and summary.json",
    )
    parser.add_argument(
        "--max-pages",
        type=_positive_int,
        help="optional cap after deterministic argument-order deduplication",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    raw_specs = (
        [(source, "unspecified") for source in args.page]
        + [(source, "text-heavy") for source in args.text_page]
        + [(source, "illustration") for source in args.illustration_page]
    )
    seen: set[tuple[str, str]] = set()
    specs: list[PageSpec] = []
    for source, kind in raw_specs:
        key = (source, kind)
        if key in seen:
            continue
        seen.add(key)
        specs.append(PageSpec(source=source, kind=kind, label=_page_label(source)))
    if args.max_pages is not None:
        specs = specs[: args.max_pages]

    try:
        results, metadata = benchmark_pages(specs, args.output_dir)
        summary_path = _write_summary(results, metadata, args.output_dir)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    _print_report(results, metadata)
    print(f"Summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
