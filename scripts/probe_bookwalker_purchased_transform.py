"""Diagnose BookWalker's purchased JPEG-to-canvas transformation.

This is a diagnostic-only probe. It follows the normal BookWalker adapter
entry/navigation flow, but never calls production capture_page() and never
changes production JPEG/PNG selection. It stores bounded raw JPEG/native
artifacts locally so that decoded pixels, canvas operations, reload stability,
and metadata markers can be inspected together.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import math
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from probe_bookwalker_jpeg_delivery import (
    BODY_READ_TIMEOUT_MS,
    DEFAULT_MAX_BODY_READS,
    DEFAULT_MAX_CONCURRENT_BODY_READS,
    DEFAULT_MAX_RESPONSE_BODY_BYTES,
    DEFAULT_MAX_RESPONSES,
    MagicJpegCandidate,
    ResponseCollector,
    _counter_dict,
    _decode_png_data_url,
    _identity_dict,
    _unique_candidates,
    classify_page,
    collect_native_parts,
    image_signature,
    redact_url,
)

from screenshot_crawler.core.browser import BrowserSession, resolve_cdp_endpoint
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.bookwalker.adapter import BookWalkerAdapter

DEFAULT_MAX_PAGES = 2
DEFAULT_RUNS = 2
PAGE_SETTLE_MS = 350
MAX_OPERATION_RECORDS = 3_000
MAX_SOURCE_SNAPSHOT_DATA_URL_LENGTH = 40 * 1024 * 1024
MAX_CROP_OFFSETS = 4_096
TILE_GRIDS = (2, 4, 8, 16)


_TRANSFORM_TRACE_SCRIPT = r"""
(() => {
  if (window.__bookwalkerTransformTraceInstalled) return;
  window.__bookwalkerTransformTraceInstalled = true;
  const state = {
    operations: [],
    canvases: {},
    sources: {},
    snapshotSources: new WeakSet(),
    canvasIds: new WeakMap(),
    sourceIds: new WeakMap(),
    nextCanvasId: 1,
    nextSourceId: 1,
  };
  const maxOperations = 3000;
  const maxSnapshotLength = 40 * 1024 * 1024;

  const constructorName = value => value?.constructor?.name || null;
  const numberOrNull = value => Number.isFinite(value) ? Number(value) : null;
  const canvasInfo = canvas => {
    if (!canvas) return null;
    let id = state.canvasIds.get(canvas);
    if (!id) {
      id = String(state.nextCanvasId++);
      state.canvasIds.set(canvas, id);
      state.canvases[id] = {
        canvasId: id,
        constructor: constructorName(canvas),
        width: numberOrNull(canvas.width),
        height: numberOrNull(canvas.height),
      };
    }
    return state.canvases[id];
  };
  const sourceInfo = source => {
    if (!source) return null;
    let id = state.sourceIds.get(source);
    if (!id) {
      id = String(state.nextSourceId++);
      state.sourceIds.set(source, id);
    }
    const info = {
      sourceId: id,
      constructor: constructorName(source),
      width: numberOrNull(source.width),
      height: numberOrNull(source.height),
    };
    state.sources[id] = state.sources[id] || info;
    return {...state.sources[id]};
  };
  const sourceSnapshot = source => {
    const constructor = constructorName(source);
    if (constructor === 'HTMLCanvasElement'
        && typeof source.toDataURL === 'function') {
      try {
        const dataUrl = source.toDataURL('image/png');
        return dataUrl.length <= maxSnapshotLength ? dataUrl : null;
      } catch (error) {
        return null;
      }
    }
    if (constructor !== 'ImageBitmap'
        || state.snapshotSources.has(source)
        || !Number.isFinite(source?.width)
        || !Number.isFinite(source?.height)) {
      return null;
    }
    state.snapshotSources.add(source);
    try {
      const target = document.createElement('canvas');
      target.width = Math.round(source.width);
      target.height = Math.round(source.height);
      const context = target.getContext('2d');
      if (!context) return null;
      originalDrawImage.call(context, source, 0, 0);
      const dataUrl = target.toDataURL('image/png');
      return dataUrl.length <= maxSnapshotLength ? dataUrl : null;
    } catch (error) {
      return null;
    }
  };
  const geometry = (source, values) => {
    const width = numberOrNull(source?.width);
    const height = numberOrNull(source?.height);
    if (values.length === 2 && width !== null && height !== null) {
      return {
        sourceRect: {x: 0, y: 0, width, height},
        destination: {x: values[0], y: values[1], width, height},
      };
    }
    if (values.length === 4) {
      return {
        sourceRect: width === null || height === null
          ? null : {x: 0, y: 0, width, height},
        destination: {
          x: values[0], y: values[1], width: values[2], height: values[3],
        },
      };
    }
    if (values.length === 8) {
      return {
        sourceRect: {
          x: values[0], y: values[1], width: values[2], height: values[3],
        },
        destination: {
          x: values[4], y: values[5], width: values[6], height: values[7],
        },
      };
    }
    return {sourceRect: null, destination: null};
  };
  const record = (operation, context, details) => {
    if (state.operations.length >= maxOperations) return;
    const canvas = canvasInfo(context?.canvas);
    if (!canvas) return;
    if (canvas.width < 500 && canvas.height < 500) return;
    let transform = null;
    try {
      const matrix = context.getTransform();
      transform = {
        a: matrix.a, b: matrix.b, c: matrix.c,
        d: matrix.d, e: matrix.e, f: matrix.f,
      };
    } catch (error) {}
    state.operations.push({
      index: state.operations.length + 1,
      timestamp: performance.now(),
      operation,
      target: canvas,
      transform,
      globalCompositeOperation: context.globalCompositeOperation || null,
      globalAlpha: Number.isFinite(context.globalAlpha) ? context.globalAlpha : null,
      filter: context.filter || null,
      imageSmoothingEnabled: Boolean(context.imageSmoothingEnabled),
      ...details,
    });
  };
  const proto = window.CanvasRenderingContext2D?.prototype;
  if (!proto) return;

  const originalDrawImage = proto.drawImage;
  if (typeof originalDrawImage === 'function') {
    const wrappedDrawImage = function(...args) {
      try {
        const values = args.slice(1).map(value => Number(value));
        const source = sourceInfo(args[0]);
        const parsed = geometry(args[0], values);
        record('drawImage', this, {
          source,
          sourceSnapshotDataUrl: sourceSnapshot(args[0]),
          sourceRect: parsed.sourceRect,
          destination: parsed.destination,
          argumentForm: values.length + 1,
        });
      } catch (error) {}
      return originalDrawImage.apply(this, args);
    };
    wrappedDrawImage.__bookwalkerTransformProbeWrapped = true;
    proto.drawImage = wrappedDrawImage;
  }

  const wrappers = {
    clearRect: args => ({arguments: args.slice(0, 4).map(Number)}),
    fillRect: args => ({arguments: args.slice(0, 4).map(Number)}),
    strokeRect: args => ({arguments: args.slice(0, 4).map(Number)}),
    putImageData: args => ({
      source: sourceInfo(args[0]),
      arguments: args.slice(1).map(Number),
    }),
    getImageData: args => ({
      arguments: args.slice(0, 4).map(Number),
    }),
  };
  for (const [name, detailsFor] of Object.entries(wrappers)) {
    const original = proto[name];
    if (typeof original !== 'function') continue;
    const wrapped = function(...args) {
      try {
        record(name, this, detailsFor(args));
      } catch (error) {}
      return original.apply(this, args);
    };
    wrapped.__bookwalkerTransformProbeWrapped = true;
    proto[name] = wrapped;
  }

  window.__bookwalkerTakeTransformTrace = () => {
    const result = {
      operations: state.operations.slice(),
      canvases: {...state.canvases},
      sources: {...state.sources},
    };
    state.operations = [];
    state.canvases = {};
    state.sources = {};
    return result;
  };
})();
"""


def _decode_png_data_url_local(value: object) -> bytes | None:
    return _decode_png_data_url(value)


def _decode_image(data: bytes) -> Image.Image:
    with Image.open(io.BytesIO(data)) as image:
        return image.convert("RGB").copy()


def _finite_or_none(value: float) -> float | None:
    return float(value) if math.isfinite(value) else None


def _ssim_channel(first: np.ndarray, second: np.ndarray) -> float:
    first_float = first.astype(np.float64)
    second_float = second.astype(np.float64)
    mean_first = float(first_float.mean())
    mean_second = float(second_float.mean())
    variance_first = float(first_float.var())
    variance_second = float(second_float.var())
    covariance = float(
        ((first_float - mean_first) * (second_float - mean_second)).mean()
    )
    c1 = (0.01 * 255.0) ** 2
    c2 = (0.03 * 255.0) ** 2
    numerator = (2 * mean_first * mean_second + c1) * (2 * covariance + c2)
    denominator = (
        (mean_first * mean_first + mean_second * mean_second + c1)
        * (variance_first + variance_second + c2)
    )
    return float(numerator / denominator) if denominator else 1.0


def _nonzero_histogram(values: np.ndarray) -> dict[str, int]:
    counts = Counter(int(value) for value in values.tolist() if int(value) != 0)
    return {str(key): int(counts[key]) for key in sorted(counts)}


def _spatial_histogram(mask: np.ndarray, *, axis: int) -> dict[str, int]:
    values = mask.sum(axis=axis)
    return {
        str(index): int(value)
        for index, value in enumerate(values.tolist())
        if int(value) != 0
    }


def _block_histogram(mask: np.ndarray, block_size: int) -> dict[str, int]:
    height, width = mask.shape
    result: dict[str, int] = {}
    for top in range(0, height, block_size):
        for left in range(0, width, block_size):
            count = int(mask[top : top + block_size, left : left + block_size].sum())
            if count:
                result[f"{left // block_size},{top // block_size}"] = count
    return result


def pixel_diff_statistics(
    first: Image.Image,
    second: Image.Image,
) -> dict[str, Any]:
    """Compare two equal-sized RGB images and retain spatial/channel detail."""

    first_rgb = np.asarray(first.convert("RGB"), dtype=np.int16)
    second_rgb = np.asarray(second.convert("RGB"), dtype=np.int16)
    if first_rgb.shape != second_rgb.shape:
        raise ValueError("pixel diff requires equal RGB dimensions")
    delta = second_rgb - first_rgb
    absolute = np.abs(delta)
    different = np.any(delta != 0, axis=2)
    pixel_count = int(different.size)
    differing_count = int(different.sum())
    squared_mean = float(np.square(delta.astype(np.float64)).mean())
    rmse = math.sqrt(squared_mean)
    psnr = None if rmse == 0 else 20 * math.log10(255.0 / rmse)
    if differing_count:
        rows, columns = np.nonzero(different)
        bbox: dict[str, int] | None = {
            "left": int(columns.min()),
            "top": int(rows.min()),
            "right": int(columns.max()) + 1,
            "bottom": int(rows.max()) + 1,
        }
    else:
        bbox = None
    channel_differences: dict[str, Any] = {}
    for index, channel in enumerate(("r", "g", "b")):
        channel_delta = delta[:, :, index]
        channel_abs = absolute[:, :, index]
        channel_differences[channel] = {
            "min": int(channel_delta.min()),
            "max": int(channel_delta.max()),
            "mean": float(channel_delta.mean()),
            "mean_absolute": float(channel_abs.mean()),
            "histogram": _nonzero_histogram(channel_delta.ravel()),
        }
    ssim_values = [
        _ssim_channel(first_rgb[:, :, index], second_rgb[:, :, index])
        for index in range(3)
    ]
    return {
        "width": int(first_rgb.shape[1]),
        "height": int(first_rgb.shape[0]),
        "exact_pixel_equality": differing_count == 0,
        "differing_pixel_count": differing_count,
        "differing_pixel_ratio": differing_count / pixel_count if pixel_count else 0.0,
        "max_absolute_channel_difference": int(absolute.max()),
        "mean_absolute_channel_difference": float(absolute.mean()),
        "rmse": rmse,
        "psnr_db": _finite_or_none(psnr) if psnr is not None else None,
        "psnr_infinite": psnr is None,
        "ssim_per_channel": ssim_values,
        "ssim": float(sum(ssim_values) / len(ssim_values)),
        "diff_bounding_box": bbox,
        "row_histogram": _spatial_histogram(different, axis=1),
        "column_histogram": _spatial_histogram(different, axis=0),
        "block_histogram": {
            str(size): _block_histogram(different, size)
            for size in (8, 16, 32, 64)
        },
        "channel_differences": channel_differences,
    }


def _metric_rank(metrics: dict[str, Any]) -> tuple[int, float, float, float]:
    return (
        int(bool(metrics.get("exact_pixel_equality"))),
        float(metrics.get("psnr_db") or -1.0),
        float(metrics.get("ssim") or -1.0),
        -float(metrics.get("mean_absolute_channel_difference") or 0.0),
    )


def _compare_variant(
    raw: Image.Image,
    native: Image.Image,
    *,
    transform: str,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if raw.size != native.size:
        raise ValueError("variant must be resized/cropped to native dimensions")
    result = pixel_diff_statistics(raw, native)
    result["transform"] = transform
    if parameters:
        result["parameters"] = parameters
    return result


def _crop_variants(
    raw: Image.Image,
    native: Image.Image,
) -> list[tuple[dict[str, Any], Image.Image]]:
    target_width, target_height = native.size
    if raw.width < target_width or raw.height < target_height:
        return []
    x_count = raw.width - target_width + 1
    y_count = raw.height - target_height + 1
    if x_count * y_count > MAX_CROP_OFFSETS:
        return []
    variants: list[tuple[dict[str, Any], Image.Image]] = []
    for top in range(y_count):
        for left in range(x_count):
            variants.append(
                (
                    {"left": left, "top": top, "right": left + target_width, "bottom": top + target_height},
                    raw.crop((left, top, left + target_width, top + target_height)),
                )
            )
    return variants


def _aspect_crop_variants(
    raw: Image.Image,
    native: Image.Image,
) -> list[tuple[dict[str, Any], Image.Image]]:
    target_ratio = native.width / native.height
    raw_ratio = raw.width / raw.height
    if abs(target_ratio - raw_ratio) < 1e-12:
        return [({"mode": "full"}, raw.copy())]
    if raw_ratio > target_ratio:
        crop_height = raw.height
        crop_width = max(1, round(crop_height * target_ratio))
    else:
        crop_width = raw.width
        crop_height = max(1, round(crop_width / target_ratio))
    x_count = raw.width - crop_width + 1
    y_count = raw.height - crop_height + 1
    if x_count * y_count > MAX_CROP_OFFSETS:
        return []
    variants: list[tuple[dict[str, Any], Image.Image]] = []
    for top in range(y_count):
        for left in range(x_count):
            variants.append(
                (
                    {
                        "left": left,
                        "top": top,
                        "right": left + crop_width,
                        "bottom": top + crop_height,
                    },
                    raw.crop((left, top, left + crop_width, top + crop_height)),
                )
            )
    return variants


def _resize_variants(
    raw: Image.Image,
    native: Image.Image,
) -> list[tuple[dict[str, Any], Image.Image]]:
    filters = {
        "nearest": Image.Resampling.NEAREST,
        "bilinear": Image.Resampling.BILINEAR,
        "bicubic": Image.Resampling.BICUBIC,
        "lanczos": Image.Resampling.LANCZOS,
    }
    return [
        ({"filter": name}, raw.resize(native.size, resample=resampling))
        for name, resampling in filters.items()
    ]


def _best_variant(
    variants: list[tuple[dict[str, Any], Image.Image]],
    native: Image.Image,
    *,
    transform: str,
) -> tuple[dict[str, Any] | None, Image.Image | None]:
    if not variants:
        return None, None
    scored: list[tuple[dict[str, Any], Image.Image, dict[str, Any]]] = []
    for parameters, image in variants:
        metrics = _compare_variant(
            image,
            native,
            transform=transform,
            parameters=parameters,
        )
        scored.append((metrics, image, parameters))
    metrics, image, _ = max(scored, key=lambda item: _metric_rank(item[0]))
    return metrics, image


def tile_permutation_report(
    raw: Image.Image,
    native: Image.Image,
) -> dict[str, Any]:
    """Check small tile grids for exact/near-exact tile movement only."""

    if raw.size != native.size:
        return {"eligible": False, "reason": "dimensions differ", "grids": {}}
    raw_array = np.asarray(raw.convert("RGB"), dtype=np.int16)
    native_array = np.asarray(native.convert("RGB"), dtype=np.int16)
    height, width = raw_array.shape[:2]
    grids: dict[str, Any] = {}
    any_permutation = False
    for grid in TILE_GRIDS:
        if width % grid or height % grid:
            grids[str(grid)] = {"eligible": False, "reason": "not divisible"}
            continue
        tile_width = width // grid
        tile_height = height // grid
        raw_tiles: list[np.ndarray] = []
        native_tiles: list[np.ndarray] = []
        positions: list[dict[str, int]] = []
        for row in range(grid):
            for column in range(grid):
                top = row * tile_height
                left = column * tile_width
                raw_tiles.append(raw_array[top : top + tile_height, left : left + tile_width])
                native_tiles.append(native_array[top : top + tile_height, left : left + tile_width])
                positions.append({"row": row, "column": column})
        mapping: list[dict[str, Any]] = []
        matched = 0
        used: set[int] = set()
        for native_index, native_tile in enumerate(native_tiles):
            errors = [
                float(np.abs(native_tile.astype(np.int32) - raw_tile.astype(np.int32)).mean())
                for raw_tile in raw_tiles
            ]
            best_index = min(range(len(errors)), key=errors.__getitem__)
            if errors[best_index] == 0 and best_index not in used:
                matched += 1
                used.add(best_index)
            mapping.append(
                {
                    "native": positions[native_index],
                    "best_raw": positions[best_index],
                    "mean_absolute_error": errors[best_index],
                }
            )
        total = grid * grid
        permutation = matched == total and any(
            item["native"] != item["best_raw"] for item in mapping
        )
        any_permutation = any_permutation or permutation
        grids[str(grid)] = {
            "eligible": True,
            "tile_width": tile_width,
            "tile_height": tile_height,
            "matched_exact_tiles": matched,
            "total_tiles": total,
            "permutation_detected": permutation,
            "mapping": mapping,
        }
    return {
        "eligible": True,
        "permutation_detected": any_permutation,
        "grids": grids,
    }


def analyze_image_pair(
    raw: Image.Image,
    native: Image.Image,
) -> tuple[dict[str, Any], Image.Image]:
    """Run crop, resize, crop+resize, and bounded tile diagnostics."""

    direct: dict[str, Any] | None = None
    if raw.size == native.size:
        direct = _compare_variant(raw, native, transform="direct_decode")

    crop_variants = _crop_variants(raw, native)
    crop_metrics, crop_image = _best_variant(
        crop_variants,
        native,
        transform="crop",
    )
    resize_metrics, resize_image = _best_variant(
        _resize_variants(raw, native),
        native,
        transform="resize",
    )
    crop_resize_sources = _aspect_crop_variants(raw, native)
    crop_resize_variants = [
        (
            parameters,
            cropped.resize(native.size, resample=Image.Resampling.LANCZOS),
        )
        for parameters, cropped in crop_resize_sources
    ]
    crop_resize_metrics, crop_resize_image = _best_variant(
        crop_resize_variants,
        native,
        transform="crop_and_resize",
    )

    exact_transform = None
    exact_image = raw
    for metrics, image in (
        (direct, raw),
        (crop_metrics, crop_image),
        (resize_metrics, resize_image),
        (crop_resize_metrics, crop_resize_image),
    ):
        if metrics and metrics.get("exact_pixel_equality"):
            exact_transform = str(metrics["transform"])
            exact_image = image if image is not None else raw
            break

    tile_report = {"eligible": False, "reason": "exact transform found", "grids": {}}
    if exact_transform is None:
        tile_report = tile_permutation_report(raw, native)

    if exact_transform == "direct_decode":
        classification = "DIRECT_DECODE"
    elif exact_transform == "crop":
        classification = "SIMPLE_CROP"
    elif exact_transform == "resize":
        classification = "RESIZE"
    elif exact_transform == "crop_and_resize":
        classification = "CROP_AND_RESIZE"
    elif tile_report.get("permutation_detected"):
        classification = "TILE_REARRANGEMENT"
        exact_image = raw
    elif direct is not None:
        classification = "PIXEL_LEVEL_MODIFICATION"
        exact_image = raw
    else:
        classification = "UNKNOWN"
        exact_image = (
            crop_image
            or resize_image
            or crop_resize_image
            or raw
        )

    result = {
        "raw_dimensions": {"width": raw.width, "height": raw.height},
        "native_dimensions": {"width": native.width, "height": native.height},
        "direct_pixel_diff": direct,
        "crop_candidates_tested": len(crop_variants),
        "best_crop": crop_metrics,
        "resize_candidates": {
            str(metrics.get("parameters", {}).get("filter")): metrics
            for metrics in [
                _compare_variant(image, native, transform="resize", parameters=params)
                for params, image in _resize_variants(raw, native)
            ]
        },
        "best_resize": resize_metrics,
        "crop_resize_candidates_tested": len(crop_resize_variants),
        "best_crop_and_resize": crop_resize_metrics,
        "tile_permutation": tile_report,
        "classification": classification,
        "classification_note": (
            "PIXEL_LEVEL_MODIFICATION means decoded same-dimension pixels differ; "
            "it does not by itself prove a watermark or identify the browser operation."
            if classification == "PIXEL_LEVEL_MODIFICATION"
            else None
        ),
    }
    return result, exact_image


def jpeg_marker_metadata(data: bytes) -> list[dict[str, Any]]:
    """Return marker facts without retaining printable metadata values."""

    if not data.startswith(b"\xff\xd8"):
        return []
    markers: list[dict[str, Any]] = []
    offset = 2
    standalone = {0x01, 0xD8, 0xD9, *range(0xD0, 0xD8)}
    while offset + 1 < len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            break
        marker = data[offset]
        offset += 1
        if marker == 0xDA:
            break
        if marker in standalone:
            continue
        if offset + 2 > len(data):
            break
        segment_length = int.from_bytes(data[offset : offset + 2], "big")
        if segment_length < 2 or offset + segment_length > len(data):
            break
        payload = data[offset + 2 : offset + segment_length]
        if marker == 0xFE or 0xE0 <= marker <= 0xEF:
            if marker == 0xFE:
                marker_type = "COM"
            else:
                marker_type = f"APP{marker - 0xE0}"
            lower = payload.lower()
            if payload.startswith(b"Exif\x00\x00"):
                semantic = "EXIF"
            elif b"http://ns.adobe.com/xap/1.0/" in payload:
                semantic = "XMP"
            elif payload.startswith(b"JFIF"):
                semantic = "JFIF"
            else:
                semantic = None
            printable_count = sum(32 <= byte <= 126 for byte in payload)
            markers.append(
                {
                    "marker": marker_type,
                    "semantic": semantic,
                    "byte_length": segment_length,
                    "printable_string_present": printable_count >= 4,
                    "printable_byte_count": printable_count,
                    "payload_sha256": hashlib.sha256(payload).hexdigest(),
                    "payload_prefix_class": (
                        "exif" if b"exif" in lower
                        else "xmp" if b"xmp" in lower
                        else "other"
                    ),
                }
            )
        offset += segment_length
    return markers


def classify_reload(
    raw_hashes_a: list[str | None],
    native_hashes_a: list[str | None],
    raw_hashes_b: list[str | None],
    native_hashes_b: list[str | None],
) -> list[str]:
    classifications: list[str] = []
    size = max(len(raw_hashes_a), len(raw_hashes_b), len(native_hashes_a), len(native_hashes_b))
    for index in range(size):
        raw_same = (
            index < len(raw_hashes_a)
            and index < len(raw_hashes_b)
            and raw_hashes_a[index] is not None
            and raw_hashes_a[index] == raw_hashes_b[index]
        )
        native_same = (
            index < len(native_hashes_a)
            and index < len(native_hashes_b)
            and native_hashes_a[index] is not None
            and native_hashes_a[index] == native_hashes_b[index]
        )
        if raw_same and native_same:
            label = "RAW_SAME_NATIVE_SAME"
        elif raw_same and not native_same:
            label = "RAW_SAME_NATIVE_DIFFERENT"
        elif not raw_same and native_same:
            label = "RAW_DIFFERENT_NATIVE_SAME"
        else:
            label = "RAW_DIFFERENT_NATIVE_DIFFERENT"
        classifications.append(label)
    return classifications


def _reload_label(
    raw_a: str | None,
    native_a: str | None,
    raw_b: str | None,
    native_b: str | None,
) -> str:
    raw_same = raw_a is not None and raw_a == raw_b
    native_same = native_a is not None and native_a == native_b
    if raw_same and native_same:
        return "RAW_SAME_NATIVE_SAME"
    if raw_same and not native_same:
        return "RAW_SAME_NATIVE_DIFFERENT"
    if not raw_same and native_same:
        return "RAW_DIFFERENT_NATIVE_SAME"
    return "RAW_DIFFERENT_NATIVE_DIFFERENT"


def _reload_page_key(page: dict[str, Any]) -> str:
    return str(
        page.get("page_counter")
        or (page.get("identity") or {}).get("page_id")
        or page.get("page_index")
    )


def aggregate_reload_comparison(
    runs: list[dict[str, Any]],
) -> dict[str, Any]:
    if len(runs) < 2:
        return {
            "runs_observed": len(runs),
            "classification": [],
            "classification_counts": {},
            "note": "at least two runs are required for reload comparison",
        }
    first_pages = runs[0].get("pages", [])
    second_pages = runs[1].get("pages", [])
    first_by_key = {
        (_reload_page_key(page), int(part.get("part", index))): (
            part.get("raw", {}).get("sha256"),
            part.get("native", {}).get("sha256"),
        )
        for page in first_pages
        for index, part in enumerate(page.get("parts", []), start=1)
    }
    second_by_key = {
        (_reload_page_key(page), int(part.get("part", index))): (
            part.get("raw", {}).get("sha256"),
            part.get("native", {}).get("sha256"),
        )
        for page in second_pages
        for index, part in enumerate(page.get("parts", []), start=1)
    }
    common_keys = [
        key for key in first_by_key
        if key in second_by_key
    ]
    classifications = [
        _reload_label(
            first_by_key[key][0],
            first_by_key[key][1],
            second_by_key[key][0],
            second_by_key[key][1],
        )
        for key in common_keys
    ]
    return {
        "runs_observed": len(runs),
        "classification": classifications,
        "classification_counts": dict(sorted(Counter(classifications).items())),
        "compared_page_parts": [
            {
                "page_key": key[0],
                "part": key[1],
                "run_a_raw_sha256": first_by_key[key][0],
                "run_b_raw_sha256": second_by_key[key][0],
                "run_a_native_sha256": first_by_key[key][1],
                "run_b_native_sha256": second_by_key[key][1],
                "classification": _reload_label(
                    first_by_key[key][0],
                    first_by_key[key][1],
                    second_by_key[key][0],
                    second_by_key[key][1],
                ),
            }
            for key in common_keys
        ],
        "unmatched_run_a_page_parts": [
            {"page_key": key[0], "part": key[1]}
            for key in first_by_key
            if key not in second_by_key
        ],
        "unmatched_run_b_page_parts": [
            {"page_key": key[0], "part": key[1]}
            for key in second_by_key
            if key not in first_by_key
        ],
    }


def _same_dict_geometry(first: object, second: object) -> bool:
    if not isinstance(first, dict) or not isinstance(second, dict):
        return False
    keys = ("x", "y", "width", "height")
    return all(
        key in first
        and key in second
        and round(float(first[key])) == round(float(second[key]))
        for key in keys
    )


def _public_trace_operation(operation: dict[str, Any]) -> dict[str, Any]:
    public = dict(operation)
    source = public.get("source")
    if isinstance(source, dict):
        public["source"] = {
            key: value
            for key, value in source.items()
            if key not in {"snapshotDataUrl", "sourceSnapshotDataUrl"}
        }
    if "sourceSnapshotDataUrl" in public:
        public["source_snapshot_available"] = bool(public.pop("sourceSnapshotDataUrl"))
    return public


def trace_tile_rearrangement_report(trace: dict[str, Any]) -> dict[str, Any]:
    groups: dict[tuple[str, str, int, int, int, int], list[dict[str, Any]]] = {}
    for operation in trace.get("operations", []):
        if operation.get("operation") != "drawImage":
            continue
        target = operation.get("target") or {}
        source = operation.get("source") or {}
        source_rect = operation.get("sourceRect") or {}
        destination = operation.get("destination") or {}
        if source.get("constructor") != "ImageBitmap":
            continue
        try:
            target_width = int(target["width"])
            target_height = int(target["height"])
            source_width = int(source["width"])
            source_height = int(source["height"])
            tile_width = int(source_rect["width"])
            tile_height = int(source_rect["height"])
            if (
                target_width != source_width
                or target_height != source_height
                or tile_width <= 0
                or tile_height <= 0
                or tile_width != int(destination["width"])
                or tile_height != int(destination["height"])
                or target_width % tile_width
                or target_height % tile_height
                or tile_width > 128
                or tile_height > 128
            ):
                continue
            int(source_rect["x"])
            int(source_rect["y"])
            int(destination["x"])
            int(destination["y"])
        except (KeyError, TypeError, ValueError):
            continue
        key = (
            str(target.get("canvasId")),
            str(source.get("sourceId")),
            target_width,
            target_height,
            tile_width,
            tile_height,
        )
        groups.setdefault(key, []).append(operation)

    public_groups: list[dict[str, Any]] = []
    detected = False
    for key, operations in groups.items():
        _, _, target_width, target_height, tile_width, tile_height = key
        expected = (target_width // tile_width) * (target_height // tile_height)
        source_positions = {
            (int(op["sourceRect"]["x"]), int(op["sourceRect"]["y"]))
            for op in operations
        }
        destination_positions = {
            (int(op["destination"]["x"]), int(op["destination"]["y"]))
            for op in operations
        }
        moved = sum(
            int(op["sourceRect"]["x"]) != int(op["destination"]["x"])
            or int(op["sourceRect"]["y"]) != int(op["destination"]["y"])
            for op in operations
        )
        complete = (
            len(operations) >= expected
            and len(source_positions) == expected
            and len(destination_positions) == expected
        )
        group_detected = complete and moved > 0
        detected = detected or group_detected
        public_groups.append(
            {
                "target_canvas_id": key[0],
                "source_id": key[1],
                "target_dimensions": {"width": target_width, "height": target_height},
                "tile_dimensions": {"width": tile_width, "height": tile_height},
                "operations": len(operations),
                "expected_tile_count": expected,
                "unique_source_tiles": len(source_positions),
                "unique_destination_tiles": len(destination_positions),
                "moved_tile_count": moved,
                "complete_permutation": complete,
                "permutation_detected": group_detected,
                "mapping_sample": [
                    {
                        "source": {
                            "x": int(op["sourceRect"]["x"]),
                            "y": int(op["sourceRect"]["y"]),
                        },
                        "destination": {
                            "x": int(op["destination"]["x"]),
                            "y": int(op["destination"]["y"]),
                        },
                    }
                    for op in operations[:16]
                ],
            }
        )
    return {
        "detected": detected,
        "groups": public_groups,
    }


def _trace_source_for_part(
    trace: dict[str, Any],
    part: dict[str, Any],
) -> tuple[dict[str, Any] | None, bytes | None]:
    source = part
    for operation in reversed(trace.get("operations", [])):
        if operation.get("operation") != "drawImage":
            continue
        op_source = operation.get("source") or {}
        if op_source.get("constructor") != source.get("source_constructor"):
            continue
        if op_source.get("width") != source.get("source_width"):
            continue
        if op_source.get("height") != source.get("source_height"):
            continue
        if not _same_dict_geometry(operation.get("sourceRect"), source.get("source_rect")):
            continue
        if not _same_dict_geometry(operation.get("destination"), source.get("destination")):
            continue
        snapshot = _decode_png_data_url_local(operation.get("sourceSnapshotDataUrl"))
        return _public_trace_operation(operation), snapshot
    return None, None


def _operation_summary(
    trace: dict[str, Any],
    *,
    visible_width: int | None,
    visible_height: int | None,
) -> dict[str, Any]:
    operations = trace.get("operations", [])
    source_canvas_draws = [
        op for op in operations
        if op.get("operation") == "drawImage"
        and (op.get("target") or {}).get("constructor") == "HTMLCanvasElement"
    ]
    renderer_draws = [
        op for op in operations
        if op.get("operation") == "drawImage"
        and (op.get("target") or {}).get("width") == visible_width
        and (op.get("target") or {}).get("height") == visible_height
    ]
    by_target: dict[str, set[str]] = {}
    for operation in operations:
        if operation.get("operation") != "drawImage":
            continue
        target_id = str((operation.get("target") or {}).get("canvasId") or "")
        source_id = str((operation.get("source") or {}).get("sourceId") or "")
        by_target.setdefault(target_id, set()).add(source_id)
    return {
        "operation_count": len(operations),
        "operation_counts": dict(sorted(Counter(
            str(operation.get("operation")) for operation in operations
        ).items())),
        "source_constructor_counts": dict(sorted(Counter(
            str((operation.get("source") or {}).get("constructor"))
            for operation in operations
            if operation.get("operation") == "drawImage"
            and (operation.get("source") or {}).get("constructor")
        ).items())),
        "source_canvas_draw_count": len(source_canvas_draws),
        "renderer_draw_count": len(renderer_draws),
        "multi_source_targets": {
            target_id: sorted(source_ids)
            for target_id, source_ids in by_target.items()
            if len(source_ids) > 1
        },
        "source_snapshot_count": sum(
            1 for operation in operations
            if operation.get("sourceSnapshotDataUrl")
        ),
        "tile_rearrangement": trace_tile_rearrangement_report(trace),
        "bounded": len(operations) >= MAX_OPERATION_RECORDS,
    }


async def _candidate_signature(
    page: Page,
    candidate: MagicJpegCandidate,
    cache: dict[str, str | None],
) -> str | None:
    sha256 = str(candidate.metadata["sha256"])
    if sha256 not in cache:
        cache[sha256] = await image_signature(page, candidate.body, "image/jpeg")
    return cache[sha256]


async def _select_candidate(
    page: Page,
    candidates: list[MagicJpegCandidate],
    native: dict[str, Any],
    *,
    page_index: int,
    signature_cache: dict[str, str | None],
    excluded_hashes: set[str] | None = None,
) -> tuple[MagicJpegCandidate | None, list[dict[str, Any]]]:
    pool = _unique_candidates([candidate for candidate in candidates if candidate.page_index <= page_index])
    excluded_hashes = excluded_hashes or set()
    ranked: list[tuple[tuple[int, ...], MagicJpegCandidate, dict[str, Any]]] = []
    for candidate in pool:
        dimensions_match = (
            candidate.metadata.get("width"),
            candidate.metadata.get("height"),
        ) == (native.get("width"), native.get("height"))
        signature_match = False
        if dimensions_match:
            signature_match = await _candidate_signature(page, candidate, signature_cache) == native.get("signature")
        reasons = {
            "same_page_index": candidate.page_index == page_index,
            "route_match": candidate.route_match,
            "filter_match": candidate.filter_match,
            "dimensions_match": dimensions_match,
            "signature_match": signature_match,
        }
        rank = (
            int(signature_match),
            int(candidate.filter_match),
            int(candidate.route_match),
            int(candidate.page_index == page_index),
            int(dimensions_match),
            int(str(candidate.metadata["sha256"]) not in excluded_hashes),
            int(candidate.record_index),
        )
        ranked.append((rank, candidate, reasons))
    ranked.sort(key=lambda item: item[0], reverse=True)
    public_pool = []
    for rank, candidate, reasons in ranked:
        public_pool.append({
            **candidate.public(),
            "selection_rank": list(rank),
            "selection_reasons": reasons,
        })
    if not ranked:
        return None, public_pool
    return ranked[0][1], public_pool


def _compact_candidate(candidate: MagicJpegCandidate) -> dict[str, Any]:
    return {
        "record_index": candidate.record_index,
        "page_index": candidate.page_index,
        "sha256": candidate.metadata.get("sha256"),
        "hostname": candidate.hostname,
        "path": candidate.path,
        "dimensions": {
            "width": candidate.metadata.get("width"),
            "height": candidate.metadata.get("height"),
        },
        "route_match": candidate.route_match,
        "filter_match": candidate.filter_match,
        "estimated_quality": candidate.metadata.get("estimated_quality"),
        "subsampling": candidate.metadata.get("subsampling"),
    }


def match_imagebitmap_sources(
    trace: dict[str, Any],
    candidates: list[MagicJpegCandidate],
    *,
    page_index: int,
) -> list[dict[str, Any]]:
    """Compare all bounded JPEG candidates with captured ImageBitmap pixels."""

    sources: dict[str, bytes] = {}
    for operation in trace.get("operations", []):
        source = operation.get("source") or {}
        source_id = str(source.get("sourceId") or "")
        data = _decode_png_data_url_local(operation.get("sourceSnapshotDataUrl"))
        if source.get("constructor") == "ImageBitmap" and source_id and data:
            sources.setdefault(source_id, data)
    result: list[dict[str, Any]] = []
    pool = _unique_candidates(
        [candidate for candidate in candidates if candidate.page_index <= page_index]
    )
    for source_id, data in sources.items():
        source_image = _decode_image(data)
        matches: list[dict[str, Any]] = []
        for candidate in pool:
            dimensions = (
                candidate.metadata.get("width"),
                candidate.metadata.get("height"),
            )
            if dimensions != source_image.size:
                continue
            metrics = pixel_diff_statistics(
                _decode_image(candidate.body),
                source_image,
            )
            matches.append({
                **_compact_candidate(candidate),
                "pixel_metrics": {
                    key: metrics[key]
                    for key in (
                        "exact_pixel_equality",
                        "differing_pixel_ratio",
                        "max_absolute_channel_difference",
                        "mean_absolute_channel_difference",
                        "rmse",
                        "psnr_db",
                        "ssim",
                    )
                },
            })
        matches.sort(
            key=lambda item: (
                int(item["pixel_metrics"]["exact_pixel_equality"]),
                float(item["pixel_metrics"]["psnr_db"] or -1.0),
                float(item["pixel_metrics"]["ssim"]),
            ),
            reverse=True,
        )
        result.append({
            "source_id": source_id,
            "source_dimensions": {
                "width": source_image.width,
                "height": source_image.height,
            },
            "candidate_count_compared": len(matches),
            "best_candidates": matches[:5],
        })
    return result


def _write_diff_images(
    output_dir: Path,
    aligned_raw: Image.Image,
    native: Image.Image,
    *,
    stem: str,
) -> dict[str, str]:
    raw_array = np.asarray(aligned_raw.convert("RGB"), dtype=np.int16)
    native_array = np.asarray(native.convert("RGB"), dtype=np.int16)
    diff = np.abs(native_array - raw_array).clip(0, 255).astype(np.uint8)
    diff_image = Image.fromarray(diff, mode="RGB")
    enhanced = np.minimum(diff.astype(np.uint16) * 8, 255).astype(np.uint8)
    enhanced_image = Image.fromarray(enhanced, mode="RGB")
    diff_path = output_dir / f"{stem}.png"
    enhanced_path = output_dir / f"{stem}-enhanced.png"
    diff_image.save(diff_path, format="PNG")
    enhanced_image.save(enhanced_path, format="PNG")
    return {
        "diff": diff_path.name,
        "diff_enhanced": enhanced_path.name,
    }


def _public_native_part(part: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in part.items()
        if key != "_data"
    }


async def _take_transform_trace(page: Page) -> dict[str, Any]:
    trace = await page.evaluate(
        "() => window.__bookwalkerTakeTransformTrace"
        " ? window.__bookwalkerTakeTransformTrace() : null"
    )
    return trace if isinstance(trace, dict) else {}


async def _run_once(
    *,
    session: BrowserSession,
    url: str,
    access_strategy: str,
    run_dir: Path,
    max_pages: int,
    max_response_body_bytes: int,
    max_responses: int,
    max_body_reads: int,
    max_concurrent_body_reads: int,
) -> dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=True)
    collector = ResponseCollector(
        max_body_bytes=max_response_body_bytes,
        max_responses=max_responses,
        max_body_reads=max_body_reads,
        max_concurrent_body_reads=max_concurrent_body_reads,
    )
    page_records: list[dict[str, Any]] = []
    signature_cache: dict[tuple[str, str], str | None] = {}
    candidate_signature_cache: dict[str, str | None] = {}
    final_url = url
    page = await session.new_page()
    adapter = BookWalkerAdapter(
        auto_login_email=os.environ.get("BOOKWALKER_EMAIL"),
        auto_login_password=os.environ.get("BOOKWALKER_PASSWORD"),
    )
    cdp = await session.context.new_cdp_session(page)
    request_methods: dict[str, str] = {}
    record_by_request_id: dict[str, dict[str, Any]] = {}

    def on_request(params: dict[str, Any]) -> None:
        request_id = str(params.get("requestId") or "")
        request = params.get("request") or {}
        if request_id:
            request_methods[request_id] = str(request.get("method") or "GET")

    def on_response(params: dict[str, Any]) -> None:
        record = collector.on_cdp_response_received(
            params,
            request_methods=request_methods,
        )
        if record is not None:
            record_by_request_id[str(params.get("requestId") or "")] = record

    def on_loading_finished(params: dict[str, Any]) -> None:
        collector.on_cdp_loading_finished(cdp, params, record_by_request_id)

    cdp.on("Network.requestWillBeSent", on_request)
    cdp.on("Network.responseReceived", on_response)
    cdp.on("Network.loadingFinished", on_loading_finished)
    try:
        await cdp.send("Network.enable")
        await adapter.prepare_page(page)
        await page.add_init_script(_TRANSFORM_TRACE_SCRIPT)
        for pattern in BookWalkerAdapter.original_response_route_patterns:
            await page.route(pattern, collector.on_route)
        await adapter.configure_run(page, access_strategy)  # type: ignore[arg-type]
        collector.set_page(1)
        await page.goto(url, wait_until="commit", timeout=60_000)
        await adapter.initialize(page)
        await page.wait_for_timeout(PAGE_SETTLE_MS)
        await collector.drain()

        for page_index in range(1, max_pages + 1):
            collector.set_page(page_index)
            state = await adapter.detect_state(page)
            if state is not PageState.CONTENT:
                break
            identity = await adapter.get_content_identity(page)
            raw_draw_calls, native_parts, native_error = await collect_native_parts(page, adapter)
            trace = await _take_transform_trace(page)
            visible_canvas = await adapter._visible_canvas(page)
            visible_size = None
            if visible_canvas is not None:
                visible_size = await visible_canvas.evaluate(
                    "element => ({width: element.width, height: element.height})"
                )
            visible_width = int(visible_size["width"]) if visible_size else None
            visible_height = int(visible_size["height"]) if visible_size else None
            page_candidates = [
                candidate
                for candidate in collector.candidates
                if candidate.page_index <= page_index
            ]
            imagebitmap_matches = match_imagebitmap_sources(
                trace,
                page_candidates,
                page_index=page_index,
            )
            tile_trace_report = trace_tile_rearrangement_report(trace)
            complete_tile_source_ids = [
                str(group["source_id"])
                for group in tile_trace_report.get("groups", [])
                if group.get("complete_permutation")
            ]
            imagebitmap_best_hash = {
                str(item["source_id"]): (
                    item.get("best_candidates") or [{}]
                )[0].get("sha256")
                for item in imagebitmap_matches
                if item.get("best_candidates")
            }
            classification, matching = await classify_page(
                page,
                native_parts,
                page_candidates,
                signature_cache,
            )
            counter = page.locator("#pageSliderCounter")
            page_counter = await counter.inner_text() if await counter.count() else None
            page_dir = run_dir / f"page-{page_index:04d}"
            page_dir.mkdir(parents=True, exist_ok=True)
            image_source_files: list[dict[str, Any]] = []
            saved_image_source_ids: set[str] = set()
            for operation in trace.get("operations", []):
                source = operation.get("source") or {}
                source_id = str(source.get("sourceId") or "")
                data = _decode_png_data_url_local(operation.get("sourceSnapshotDataUrl"))
                if (
                    source.get("constructor") == "ImageBitmap"
                    and source_id
                    and data
                    and source_id not in saved_image_source_ids
                ):
                    image_source_name = f"imagebitmap-source-{len(saved_image_source_ids) + 1:02d}.png"
                    (page_dir / image_source_name).write_bytes(data)
                    saved_image_source_ids.add(source_id)
                    image_source_files.append(
                        {
                            "source_id": source_id,
                            "constructor": source.get("constructor"),
                            "dimensions": {
                                "width": source.get("width"),
                                "height": source.get("height"),
                            },
                            "file": image_source_name,
                        }
                    )
            part_records: list[dict[str, Any]] = []
            selected_candidate_hashes: set[str] = set()
            for part_index, native_part in enumerate(native_parts, start=1):
                native_data = native_part["_data"]
                native_image = _decode_image(native_data)
                native_name = "native.png" if part_index == 1 else f"native-{part_index:02d}.png"
                (page_dir / native_name).write_bytes(native_data)
                candidate, candidate_pool = await _select_candidate(
                    page,
                    page_candidates,
                    native_part,
                    page_index=page_index,
                    signature_cache=candidate_signature_cache,
                    excluded_hashes=selected_candidate_hashes,
                )
                selection_strategy = "bounded_route_filter_dimension_rank"
                source_index = part_index - 1
                if source_index < len(complete_tile_source_ids):
                    source_id = complete_tile_source_ids[source_index]
                    preferred_hash = imagebitmap_best_hash.get(source_id)
                    preferred = next(
                        (
                            item
                            for item in page_candidates
                            if str(item.metadata.get("sha256")) == str(preferred_hash)
                            and str(item.metadata.get("sha256")) not in selected_candidate_hashes
                        ),
                        None,
                    )
                    if preferred is not None:
                        candidate = preferred
                        selection_strategy = "imagebitmap_exact_decoded_match"
                raw_record: dict[str, Any] = {
                    "sha256": None,
                    "dimensions": None,
                    "hostname": None,
                    "url": None,
                    "selection_pool": candidate_pool,
                    "selection_strategy": selection_strategy,
                }
                analysis: dict[str, Any] | None = None
                diff_files: dict[str, str] = {}
                marker_metadata: list[dict[str, Any]] = []
                if candidate is not None:
                    selected_candidate_hashes.add(str(candidate.metadata["sha256"]))
                    raw_data = candidate.body
                    raw_image = _decode_image(raw_data)
                    raw_name = f"raw-candidate-{part_index:02d}.jpg"
                    (page_dir / raw_name).write_bytes(raw_data)
                    analysis, aligned_raw = analyze_image_pair(raw_image, native_image)
                    diff_files = _write_diff_images(
                        page_dir,
                        aligned_raw,
                        native_image,
                        stem=f"diff-part-{part_index:02d}",
                    )
                    marker_metadata = jpeg_marker_metadata(raw_data)
                    raw_record.update({
                        "sha256": candidate.metadata.get("sha256"),
                        "dimensions": {
                            "width": candidate.metadata.get("width"),
                            "height": candidate.metadata.get("height"),
                        },
                        "hostname": candidate.hostname,
                        "url": candidate.url,
                        "page_index": candidate.page_index,
                        "record_index": candidate.record_index,
                        "route_match": candidate.route_match,
                        "filter_match": candidate.filter_match,
                        "content_type": candidate.content_type,
                        "estimated_quality": candidate.metadata.get("estimated_quality"),
                        "subsampling": candidate.metadata.get("subsampling"),
                        "file": raw_name,
                        "jpeg_marker_metadata": marker_metadata,
                    })
                selected_operation, full_source_png = _trace_source_for_part(trace, native_part)
                source_name = None
                if full_source_png:
                    source_name = "source-canvas.png" if part_index == 1 else f"source-canvas-{part_index:02d}.png"
                    (page_dir / source_name).write_bytes(full_source_png)
                elif native_part.get("source_constructor") == "HTMLCanvasElement":
                    source_name = native_name
                part_records.append({
                    "part": part_index,
                    "raw": raw_record,
                    "native": {
                        **_public_native_part(native_part),
                        "sha256": hashlib.sha256(native_data).hexdigest(),
                        "file": native_name,
                    },
                    "source_canvas": {
                        "file": source_name,
                        "snapshot_available": bool(full_source_png),
                        "selected_draw_operation": selected_operation,
                    },
                    "analysis": analysis,
                    "diff_files": diff_files,
                })
            operation_summary = _operation_summary(
                trace,
                visible_width=visible_width,
                visible_height=visible_height,
            )
            if operation_summary["tile_rearrangement"]["detected"]:
                for part in part_records:
                    if part.get("analysis"):
                        part["analysis"]["classification"] = "TILE_REARRANGEMENT"
                        part["analysis"]["classification_note"] = (
                            "The canvas trace observed a complete tile permutation "
                            "from an ImageBitmap into an HTMLCanvasElement."
                        )
            page_metadata = {
                "page_index": page_index,
                "page_counter": page_counter,
                "url": redact_url(page.url),
                "identity": _identity_dict(identity),
                "classification_from_existing_probe": classification,
                "existing_probe_matching": matching,
                "native_error": native_error,
                "parts": part_records,
                "draw_calls": raw_draw_calls,
                "canvas_operations": [
                    _public_trace_operation(operation)
                    for operation in trace.get("operations", [])
                ],
                "canvas_inventory": trace.get("canvases", {}),
                "source_inventory": {
                    source_id: {
                        key: value
                        for key, value in source.items()
                        if key != "snapshotDataUrl"
                    }
                    for source_id, source in (trace.get("sources") or {}).items()
                    if isinstance(source, dict)
                },
                "imagebitmap_source_snapshots": image_source_files,
                "imagebitmap_candidate_matches": imagebitmap_matches,
                "canvas_operation_summary": operation_summary,
            }
            (page_dir / "metadata.json").write_text(
                json.dumps(page_metadata, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            page_records.append(page_metadata)
            if page_index >= max_pages:
                break
            await page.evaluate(
                "window.__bookwalkerNativeDrawCalls = []; "
                "window.__bookwalkerDrawCalls = [];"
            )
            previous_identity = identity
            collector.set_page(page_index + 1)
            await adapter.go_next(page)
            await adapter.wait_for_change(page, previous_identity)
            await adapter._wait_for_render_ready(page)
            await page.wait_for_timeout(PAGE_SETTLE_MS)
            await collector.drain()
        final_url = page.url
    finally:
        await collector.drain()
        final_url = page.url
        try:
            await cdp.detach()
        except PlaywrightError:
            pass
        await session.close_page(page)

    summary = {
        "run_dir": str(run_dir),
        "input_url": redact_url(url),
        "final_url": redact_url(final_url),
        "pages_observed": len(page_records),
        "classifications": dict(sorted(Counter(
            str(part.get("analysis", {}).get("classification"))
            for page_record in page_records
            for part in page_record.get("parts", [])
            if part.get("analysis")
        ).items())),
        "source_constructors": _counter_dict([
            str(part.get("native", {}).get("source_constructor"))
            for page_record in page_records
            for part in page_record.get("parts", [])
            if part.get("native", {}).get("source_constructor")
        ]),
        "canvas_operation_counts": dict(sorted(Counter(
            operation
            for page_record in page_records
            for operation, count in page_record.get("canvas_operation_summary", {}).get(
                "operation_counts", {}
            ).items()
            for _ in range(int(count))
        ).items())),
        "response_summary": {
            "responses_observed": len(collector.records),
            "jpeg_candidates": len(_unique_candidates(collector.candidates)),
            "body_reads_completed": collector.body_reads_completed,
            "body_reads_skipped_after_limit": collector.body_reads_skipped_after_limit,
            "body_bytes_read": collector.body_bytes_read,
            "max_response_body_bytes": collector.max_body_bytes,
            "max_responses": collector.max_responses,
            "max_body_reads": collector.max_body_reads,
            "body_read_timeout_ms": BODY_READ_TIMEOUT_MS,
        },
        "pages": [
            {
                "page_index": page_record.get("page_index"),
                "page_counter": page_record.get("page_counter"),
                "parts": [
                    {
                        "classification": part.get("analysis", {}).get("classification"),
                        "raw_sha256": part.get("raw", {}).get("sha256"),
                        "native_sha256": part.get("native", {}).get("sha256"),
                        "raw_dimensions": part.get("analysis", {}).get("raw_dimensions"),
                        "native_dimensions": part.get("analysis", {}).get("native_dimensions"),
                    }
                    for part in page_record.get("parts", [])
                ],
            }
            for page_record in page_records
        ],
    }
    (run_dir / "responses.jsonl").write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in collector.records),
        encoding="utf-8",
    )
    (run_dir / "jpeg_candidates.json").write_text(
        json.dumps(
            [candidate.public() for candidate in _unique_candidates(collector.candidates)],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary["pages"] = page_records
    return summary


async def run_probe(
    *,
    url: str,
    access_strategy: str,
    output_dir: Path,
    max_pages: int = DEFAULT_MAX_PAGES,
    runs: int = DEFAULT_RUNS,
    cdp_endpoint: str | None = None,
    max_response_body_bytes: int = DEFAULT_MAX_RESPONSE_BODY_BYTES,
    max_responses: int = DEFAULT_MAX_RESPONSES,
    max_body_reads: int = DEFAULT_MAX_BODY_READS,
    max_concurrent_body_reads: int = DEFAULT_MAX_CONCURRENT_BODY_READS,
) -> dict[str, Any]:
    if max_pages <= 0 or runs <= 0:
        raise ValueError("max_pages and runs must be positive")
    output_dir.mkdir(parents=True, exist_ok=True)
    endpoint = resolve_cdp_endpoint(site="bookwalker", cli_endpoint=cdp_endpoint)
    session = await BrowserSession.connect(endpoint)
    runs_summary: list[dict[str, Any]] = []
    try:
        for index in range(1, runs + 1):
            run_dir = output_dir / f"run-{chr(96 + index)}"
            run_summary = await _run_once(
                session=session,
                url=url,
                access_strategy=access_strategy,
                run_dir=run_dir,
                max_pages=max_pages,
                max_response_body_bytes=max_response_body_bytes,
                max_responses=max_responses,
                max_body_reads=max_body_reads,
                max_concurrent_body_reads=max_concurrent_body_reads,
            )
            runs_summary.append(run_summary)
    finally:
        await session.close()

    comparison = aggregate_reload_comparison(runs_summary)
    concise_runs = [
        {
            key: value
            for key, value in run.items()
            if key != "pages"
        }
        for run in runs_summary
    ]
    summary = {
        "input_url": redact_url(url),
        "access_strategy": access_strategy,
        "max_pages": max_pages,
        "runs": concise_runs,
        "reload_comparison": comparison,
        "watermark_interpretation": {
            "confirmed": [
                "The captured JPEG and native PNG artifacts can be compared at decoded-pixel level.",
                "The viewer canvas operation trace is bounded and records source/target geometry, transform, filter, and composition.",
            ],
            "consistent_with": [
                "A deterministic user/session-specific modification is possible if both reloads are identical.",
                "A reload-varying native image would be consistent with session/randomized modification.",
            ],
            "not_established": [
                "A single account/session cannot prove or disprove purchaser identification.",
                "A pixel mismatch alone cannot identify watermarking without a stable spatial/byte pattern.",
            ],
        },
    }
    (output_dir / "comparison.json").write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument(
        "--access-strategy",
        choices=("auto", "direct", "quota"),
        default="direct",
    )
    parser.add_argument("--max-pages", type=_positive_int, default=DEFAULT_MAX_PAGES)
    parser.add_argument("--runs", type=_positive_int, default=DEFAULT_RUNS)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cdp-endpoint")
    parser.add_argument(
        "--max-response-body-bytes",
        type=_positive_int,
        default=DEFAULT_MAX_RESPONSE_BODY_BYTES,
    )
    parser.add_argument("--max-responses", type=_positive_int, default=DEFAULT_MAX_RESPONSES)
    parser.add_argument("--max-body-reads", type=_positive_int, default=DEFAULT_MAX_BODY_READS)
    parser.add_argument(
        "--max-concurrent-body-reads",
        type=_positive_int,
        default=DEFAULT_MAX_CONCURRENT_BODY_READS,
    )
    args = parser.parse_args()
    summary = asyncio.run(
        run_probe(
            url=args.url,
            access_strategy=args.access_strategy,
            output_dir=args.output_dir,
            max_pages=args.max_pages,
            runs=args.runs,
            cdp_endpoint=args.cdp_endpoint,
            max_response_body_bytes=args.max_response_body_bytes,
            max_responses=args.max_responses,
            max_body_reads=args.max_body_reads,
            max_concurrent_body_reads=args.max_concurrent_body_reads,
        )
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
