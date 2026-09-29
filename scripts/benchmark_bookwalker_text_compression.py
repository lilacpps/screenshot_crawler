#!/usr/bin/env python3
"""Compare WebP and low-bit-depth grayscale PNGs for selected BookWalker pages.

The source PNGs are read-only.  Each selected page is written to a separate
output directory with the original, lossless WebP q40/m2, lossy WebP q70/m2,
and 4/2/1-bit grayscale PNG variants.  Crops use the same coordinates for all
variants of a page so that visual inspection is straightforward.

Example::

    python scripts/benchmark_bookwalker_text_compression.py \
        --page "output/book/page-0151.png" \
        --page "output/book/page-0152.png" \
        --page "output/book/page-0153.png" \
        --output-dir output/diagnostics/bookwalker-text-compression
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import zipfile
from collections import defaultdict
from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageChops

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from benchmark_bookwalker_webp_visual import (
    _crop_boxes,
    _format_bytes,
    _format_seconds,
    _global_ssim,
    _print_table,
)


@dataclass(frozen=True, slots=True)
class PageSpec:
    source: str
    label: str


@dataclass(frozen=True, slots=True)
class VariantResult:
    page: str
    source: str
    variant: str
    original_png_bytes: int
    encoded_bytes: int
    saved_bytes: int
    saved_percent: float
    encode_seconds: float
    decode_seconds: float
    mode: str
    actual_bit_depth: int | None
    unique_grayscale_values: int
    unique_color_values: int
    alpha_present: bool
    pixel_exact: bool
    psnr_db: float | None
    global_ssim: float
    max_absolute_difference: int
    output_path: str
    alpha_fallback: str | None = None


VARIANT_NAMES = (
    "original-png",
    "lossless-webp-q40-m2",
    "lossy-webp-q70-m2",
    "gray-4bit",
    "gray-2bit",
    "gray-1bit",
)


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


def _read_source(source: str) -> bytes:
    if "::" in source:
        archive_name, member_name = source.split("::", 1)
        with zipfile.ZipFile(archive_name, "r") as archive:
            try:
                return archive.read(member_name)
            except KeyError as exc:
                raise ValueError(f"ZIP member not found: {source}") from exc
    path = Path(source)
    if path.suffix.lower() != ".png":
        raise ValueError(f"input is not a PNG: {path}")
    return path.read_bytes()


def _unique_grayscale_values(image: Image.Image) -> int:
    grayscale = image.convert("L")
    try:
        colors = grayscale.getcolors(maxcolors=image.width * image.height + 1)
        return len(colors) if colors is not None else -1
    finally:
        grayscale.close()


def _unique_color_values(image: Image.Image) -> int:
    rgb = image.convert("RGB")
    try:
        colors = rgb.getcolors(maxcolors=image.width * image.height + 1)
        return len(colors) if colors is not None else -1
    finally:
        rgb.close()


def _alpha_present(image: Image.Image) -> bool:
    alpha = image.convert("RGBA").getchannel("A")
    try:
        return alpha.getextrema() != (255, 255)
    finally:
        alpha.close()


def _save_png(image: Image.Image, *, bits: int | None = None) -> bytes:
    output = BytesIO()
    if bits is None:
        image.save(output, format="PNG")
    else:
        image.save(output, format="PNG", bits=bits)
    return output.getvalue()


def _pixel_data(image: Image.Image):
    get_flattened_data = getattr(image, "get_flattened_data", None)
    return get_flattened_data() if get_flattened_data is not None else image.getdata()


def _quantized_palette_png(image: Image.Image, bits: int) -> tuple[bytes, str | None]:
    levels = 1 << bits
    luminance = image.convert("L")
    alpha = image.convert("RGBA").getchannel("A")
    try:
        lookup = [round(value * (levels - 1) / 255) for value in range(256)]
        indices = luminance.point(lookup)
        alpha_is_opaque = alpha.getextrema() == (255, 255)

        if alpha_is_opaque:
            palette_image = Image.new("P", image.size)
            palette_image.putdata(_pixel_data(indices))
            palette = []
            for level in range(levels):
                value = round(level * 255 / (levels - 1))
                palette.extend((value, value, value))
            palette_image.putpalette(palette + [0] * (768 - len(palette)))
            try:
                return _save_png(palette_image, bits=bits), None
            finally:
                palette_image.close()

        # A palette+tRNS PNG can preserve alpha if each quantized gray/alpha
        # pair fits in the requested palette.  This keeps alpha explicit.
        pairs: dict[tuple[int, int], int] = {}
        mapped: list[int] = []
        for gray_index, alpha_value in zip(
            _pixel_data(indices), _pixel_data(alpha), strict=True
        ):
            key = (int(gray_index), int(alpha_value))
            if key not in pairs:
                pairs[key] = len(pairs)
            mapped.append(pairs[key])
        if len(pairs) <= levels:
            palette_image = Image.new("P", image.size)
            palette_image.putdata(mapped)
            palette: list[int] = []
            transparency: list[int] = []
            for (gray_index, alpha_value), _index in sorted(
                pairs.items(), key=lambda item: item[1]
            ):
                value = round(gray_index * 255 / (levels - 1))
                palette.extend((value, value, value))
                transparency.append(alpha_value)
            palette_image.putpalette(palette + [0] * (768 - len(palette)))
            palette_image.info["transparency"] = bytes(transparency)
            try:
                return _save_png(palette_image, bits=bits), None
            finally:
                palette_image.close()

        # PNG grayscale+alpha only supports 8/16-bit samples.  Preserve alpha
        # rather than silently dropping it, and report that the requested
        # low-bit representation was not possible for this input.
        quantized_l = luminance.point(
            [round(value * (levels - 1) / 255) * 255 // (levels - 1) for value in range(256)]
        )
        la = Image.merge("LA", (quantized_l, alpha.copy()))
        try:
            return _save_png(la), "alpha combinations exceed palette capacity; used 8-bit LA"
        finally:
            la.close()
            quantized_l.close()
    finally:
        luminance.close()
        alpha.close()


def _encode_webp(image: Image.Image, *, lossless: bool, quality: int) -> bytes:
    output = BytesIO()
    image.save(
        output,
        format="WEBP",
        lossless=lossless,
        quality=quality,
        method=2,
        exact=True,
    )
    return output.getvalue()


def _png_bit_depth(encoded: bytes) -> tuple[str, int | None]:
    with Image.open(BytesIO(encoded)) as image:
        mode = image.mode
    if encoded[:8] == b"\x89PNG\r\n\x1a\n" and encoded[12:16] == b"IHDR":
        return mode, encoded[24]
    return mode, None


def _quality_metrics(original: Image.Image, decoded: Image.Image) -> dict[str, object]:
    original_rgb = original.convert("RGB")
    decoded_rgb = decoded.convert("RGB")
    difference = ImageChops.difference(original_rgb, decoded_rgb)
    red, green, blue = difference.split()
    changed_mask = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    try:
        histogram = difference.histogram()
        pixel_count = original.width * original.height
        channel_count = pixel_count * 3
        squared = sum((index % 256) ** 2 * count for index, count in enumerate(histogram))
        mse = squared / channel_count if channel_count else 0.0
        psnr = None if mse == 0 else 10 * math.log10((255**2) / mse)
        original_rgba = original.convert("RGBA")
        decoded_rgba = decoded.convert("RGBA")
        try:
            pixel_exact = original_rgba.tobytes() == decoded_rgba.tobytes()
        finally:
            original_rgba.close()
            decoded_rgba.close()
        return {
            "pixel_exact": pixel_exact,
            "psnr_db": psnr,
            "global_ssim": 1.0 if pixel_exact else _global_ssim(original, decoded),
            "max_absolute_difference": max(
                (index % 256 for index, count in enumerate(histogram) if count), default=0
            ),
            "changed_pixel_count": pixel_count - changed_mask.histogram()[0],
        }
    finally:
        original_rgb.close()
        decoded_rgb.close()
        difference.close()
        red.close()
        green.close()
        blue.close()
        changed_mask.close()


def _make_result(
    page: PageSpec,
    source: str,
    original: Image.Image,
    original_bytes: bytes,
    variant: str,
    encoded: bytes,
    output_path: Path,
    encode_seconds: float,
    decode_seconds: float,
    decoded: Image.Image,
    alpha_fallback: str | None = None,
) -> VariantResult:
    metrics = _quality_metrics(original, decoded)
    mode, bit_depth = _png_bit_depth(encoded) if variant.startswith(("original", "gray-")) else ("WEBP", None)
    saved_bytes = len(original_bytes) - len(encoded)
    return VariantResult(
        page=page.label,
        source=source,
        variant=variant,
        original_png_bytes=len(original_bytes),
        encoded_bytes=len(encoded),
        saved_bytes=saved_bytes,
        saved_percent=saved_bytes / len(original_bytes) * 100 if original_bytes else 0.0,
        encode_seconds=encode_seconds,
        decode_seconds=decode_seconds,
        mode=mode,
        actual_bit_depth=bit_depth,
        unique_grayscale_values=_unique_grayscale_values(decoded),
        unique_color_values=_unique_color_values(decoded),
        alpha_present=_alpha_present(decoded),
        pixel_exact=metrics["pixel_exact"],
        psnr_db=metrics["psnr_db"],
        global_ssim=metrics["global_ssim"],
        max_absolute_difference=metrics["max_absolute_difference"],
        output_path=str(output_path),
        alpha_fallback=alpha_fallback,
    )


def _write_crops(
    crops_dir: Path,
    boxes: dict[str, tuple[int, int, int, int]],
    name: str,
    image: Image.Image,
) -> None:
    for crop_name, box in boxes.items():
        with image.crop(box) as crop:
            crop.save(crops_dir / f"{name}-{crop_name}.png", format="PNG")


def benchmark_pages(
    pages: list[PageSpec], output_dir: Path
) -> tuple[list[VariantResult], dict[str, object]]:
    if not pages:
        raise ValueError("at least one --page is required")
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[VariantResult] = []
    page_metadata: list[dict[str, object]] = []

    for page in pages:
        original_bytes = _read_source(page.source)
        with Image.open(BytesIO(original_bytes)) as original:
            original.load()
            page_dir = output_dir / page.label
            page_dir.mkdir(parents=True, exist_ok=True)
            crops_dir = page_dir / "crops"
            crops_dir.mkdir(exist_ok=True)
            (page_dir / "original.png").write_bytes(original_bytes)
            boxes = _crop_boxes(original.size)
            _write_crops(crops_dir, boxes, "original", original)

            records: list[VariantResult] = []
            source_variants = (
                "original-png",
                "lossless-webp-q40-m2",
                "lossy-webp-q70-m2",
            )
            for variant in source_variants:
                if variant == "original-png":
                    encoded = original_bytes
                    encode_seconds = 0.0
                else:
                    started = time.perf_counter()
                    encoded = _encode_webp(
                        original,
                        lossless=variant == "lossless-webp-q40-m2",
                        quality=40 if variant == "lossless-webp-q40-m2" else 70,
                    )
                    encode_seconds = time.perf_counter() - started
                output_name = "original.png" if variant == "original-png" else f"{variant}.webp"
                output_path = page_dir / output_name
                if variant != "original-png":
                    output_path.write_bytes(encoded)
                decode_started = time.perf_counter()
                decoded = original.copy() if variant == "original-png" else Image.open(BytesIO(encoded))
                decoded.load()
                decode_seconds = time.perf_counter() - decode_started
                try:
                    if variant != "original-png":
                        _write_crops(crops_dir, boxes, variant, decoded)
                    records.append(
                        _make_result(
                            page,
                            page.source,
                            original,
                            original_bytes,
                            variant,
                            encoded,
                            output_path,
                            encode_seconds,
                            decode_seconds,
                            decoded,
                            None,
                        )
                    )
                finally:
                    decoded.close()

            for bits in (4, 2, 1):
                variant = f"gray-{bits}bit"
                started = time.perf_counter()
                encoded, alpha_fallback = _quantized_palette_png(original, bits)
                encode_seconds = time.perf_counter() - started
                output_path = page_dir / f"{variant}.png"
                output_path.write_bytes(encoded)
                decode_started = time.perf_counter()
                decoded = Image.open(BytesIO(encoded))
                decoded.load()
                decode_seconds = time.perf_counter() - decode_started
                try:
                    _write_crops(crops_dir, boxes, variant, decoded)
                    records.append(
                        _make_result(
                            page,
                            page.source,
                            original,
                            original_bytes,
                            variant,
                            encoded,
                            output_path,
                            encode_seconds,
                            decode_seconds,
                            decoded,
                            alpha_fallback,
                        )
                    )
                finally:
                    decoded.close()
            results.extend(records)
            page_metadata.append(
                {
                    "page": page.label,
                    "source": page.source,
                    "output_dir": str(page_dir),
                    "crop_boxes": {name: list(box) for name, box in boxes.items()},
                    "variants": VARIANT_NAMES,
                }
            )

    return results, {"pages": page_metadata, "variants": VARIANT_NAMES}


def _write_summary(
    results: list[VariantResult], metadata: dict[str, object], output_dir: Path
) -> Path:
    by_page: dict[str, dict[str, VariantResult]] = defaultdict(dict)
    for result in results:
        by_page[result.page][result.variant] = result
    comparisons = []
    for page, variants in by_page.items():
        lossless = variants["lossless-webp-q40-m2"]
        q70 = variants["lossy-webp-q70-m2"]
        comparisons.append(
            {
                "page": page,
                "lossless_webp_bytes": lossless.encoded_bytes,
                "q70_webp_bytes": q70.encoded_bytes,
                "q70_vs_lossless_bytes": q70.encoded_bytes - lossless.encoded_bytes,
                "q70_vs_lossless_saved_percent_points": q70.saved_percent
                - lossless.saved_percent,
            }
        )
    payload = {
        **metadata,
        "comparisons": comparisons,
        "results": [asdict(result) for result in results],
    }
    path = output_dir / "summary.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return path


def _print_report(results: list[VariantResult]) -> None:
    print("BookWalker text-page PNG/WebP compression benchmark (read-only inputs)")
    print(f"Pages: {len({result.page for result in results})}")
    rows = []
    for result in results:
        rows.append(
            [
                result.page,
                result.variant,
                _format_bytes(result.encoded_bytes),
                f"{result.saved_percent:.2f}%",
                _format_seconds(result.encode_seconds),
                str(result.actual_bit_depth or "-"),
                str(result.unique_grayscale_values),
                str(result.unique_color_values),
                "yes" if result.pixel_exact else "no",
            ]
        )
    _print_table(
        ["Page", "Variant", "Bytes", "Saved vs PNG", "Encode", "Bits", "Gray values", "Colors", "Exact"],
        rows,
    )
    print("\nq70 vs lossless WebP:")
    delta_rows = []
    for page in sorted({result.page for result in results}):
        variants = {result.variant: result for result in results if result.page == page}
        lossless = variants["lossless-webp-q40-m2"]
        q70 = variants["lossy-webp-q70-m2"]
        delta_rows.append(
            [
                page,
                _format_bytes(q70.encoded_bytes - lossless.encoded_bytes),
                f"{q70.saved_percent - lossless.saved_percent:+.2f} pt",
                _format_seconds(q70.encode_seconds - lossless.encode_seconds),
            ]
        )
    _print_table(["Page", "q70 size Δ", "Saved Δ", "Encode Δ"], delta_rows)
    print("\nExact pixel equality is expected only for original/lossless variants.")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare lossless/lossy WebP and 1/2/4-bit grayscale PNG variants."
    )
    parser.add_argument(
        "--page",
        action="append",
        default=[],
        metavar="PNG_OR_ZIP::MEMBER",
        help="selected PNG path or ZIP::member; repeat for each page",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/diagnostics/bookwalker-text-compression"),
        help="output directory for variants, crops, and summary.json",
    )
    parser.add_argument(
        "--max-pages",
        type=_positive_int,
        help="optional cap after deterministic argument-order deduplication",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    sources = list(dict.fromkeys(args.page))
    if args.max_pages is not None:
        sources = sources[: args.max_pages]
    pages = [PageSpec(source=source, label=_page_label(source)) for source in sources]
    try:
        results, metadata = benchmark_pages(pages, args.output_dir)
        summary_path = _write_summary(results, metadata, args.output_dir)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    _print_report(results)
    print(f"Summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
