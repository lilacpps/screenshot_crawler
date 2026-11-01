"""Diagnose BookWalker's purchased JPEG-to-canvas transformation.

This is a diagnostic-only probe. It follows the normal BookWalker adapter
entry/navigation flow, but never calls production capture_page() and never
changes production JPEG/PNG selection. It stores bounded raw JPEG/native
artifacts locally so that decoded pixels, canvas operations, reload stability,
and metadata markers can be inspected together. ``--metadata-only`` keeps the
same in-memory comparisons while writing no image bytes to the output.
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
# This is intentionally a probe-only retention bound. Production keeps its
# separate 5,000-operation fail-closed trace unchanged until this investigation
# establishes which retention policy is appropriate.
MAX_OPERATION_RECORDS = 10_000
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
    nextOperationIndex: 1,
    observedOperationCount: 0,
    traceOverflow: false,
    overflowOperationIndex: null,
    droppedOperationCount: 0,
    postOverflowOperationCounts: {},
    imageBitmapSnapshotCount: 0,
    imageBitmapSnapshotSkippedCount: 0,
    sourceInventoryCount: 0,
    canvasInventoryCount: 0,
    sourceInventoryTruncatedCount: 0,
    canvasInventoryTruncatedCount: 0,
  };
  // Diagnostic-only rolling retention. The absolute operation index continues
  // after the ring starts dropping old records, so overflow can be located
  // relative to a renderer draw instead of being mistaken for index reuse.
  const maxOperations = 10000;
  const maxSnapshotLength = 8 * 1024 * 1024;
  const maxImageBitmapSnapshots = 8;
  const maxSourceInventory = 2000;
  const maxCanvasInventory = 200;

  const constructorName = value => value?.constructor?.name || null;
  const numberOrNull = value => Number.isFinite(value) ? Number(value) : null;
  const canvasInfo = canvas => {
    if (!canvas) return null;
    let id = state.canvasIds.get(canvas);
    if (!id) {
      id = String(state.nextCanvasId++);
      state.canvasIds.set(canvas, id);
      if (state.canvasInventoryCount < maxCanvasInventory) {
        state.canvases[id] = {
          canvasId: id,
          constructor: constructorName(canvas),
          width: numberOrNull(canvas.width),
          height: numberOrNull(canvas.height),
        };
        state.canvasInventoryCount += 1;
      } else {
        state.canvasInventoryTruncatedCount += 1;
      }
    }
    return state.canvases[id] || {
      canvasId: id,
      constructor: constructorName(canvas),
      width: numberOrNull(canvas.width),
      height: numberOrNull(canvas.height),
      inventoryTruncated: true,
    };
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
    if (constructorName(source) === 'HTMLCanvasElement') {
      const canvas = canvasInfo(source);
      if (canvas) info.canvasId = canvas.canvasId;
    }
    if (!state.sources[id]) {
      if (state.sourceInventoryCount < maxSourceInventory) {
        state.sources[id] = info;
        state.sourceInventoryCount += 1;
      } else {
        state.sourceInventoryTruncatedCount += 1;
      }
    }
    return {...(state.sources[id] || {...info, inventoryTruncated: true})};
  };
  const traceContext = context => {
    const canvas = context?.canvas;
    return canvas && !(
      Number(canvas.width) < 500 && Number(canvas.height) < 500
    );
  };
  const sourceSnapshot = source => {
    const constructor = constructorName(source);
    // Native source-canvas pixels are already materialized by the existing
    // bounded probe. Avoid retaining a full PNG for every renderer draw here;
    // this trace is for object/geometry evidence, not image artifact output.
    if (constructor === 'HTMLCanvasElement'
        && typeof source.toDataURL === 'function') {
      return null;
    }
    if (constructor !== 'ImageBitmap'
        || state.snapshotSources.has(source)
        || !Number.isFinite(source?.width)
        || !Number.isFinite(source?.height)) {
      return null;
    }
    if (state.imageBitmapSnapshotCount >= maxImageBitmapSnapshots) {
      state.imageBitmapSnapshotSkippedCount += 1;
      return null;
    }
    state.snapshotSources.add(source);
    state.imageBitmapSnapshotCount += 1;
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
    const canvas = canvasInfo(context?.canvas);
    if (!canvas) return;
    if (canvas.width < 500 && canvas.height < 500) return;
    const operationIndex = state.nextOperationIndex++;
    state.observedOperationCount = operationIndex;
    if (operationIndex > maxOperations) {
      state.traceOverflow = true;
      if (state.overflowOperationIndex === null) {
        state.overflowOperationIndex = operationIndex;
      }
      state.postOverflowOperationCounts[operation] =
        (state.postOverflowOperationCounts[operation] || 0) + 1;
    }
    let transform = null;
    try {
      const matrix = context.getTransform();
      transform = {
        a: matrix.a, b: matrix.b, c: matrix.c,
        d: matrix.d, e: matrix.e, f: matrix.f,
      };
    } catch (error) {}
    state.operations.push({
      index: operationIndex,
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
    if (state.operations.length > maxOperations) {
      state.operations.shift();
      state.droppedOperationCount += 1;
    }
  };
  const proto = window.CanvasRenderingContext2D?.prototype;
  if (!proto) return;

  const originalDrawImage = proto.drawImage;
  if (typeof originalDrawImage === 'function') {
    const wrappedDrawImage = function(...args) {
      if (!traceContext(this)) return originalDrawImage.apply(this, args);
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
      if (!traceContext(this)) return original.apply(this, args);
      try {
        record(name, this, detailsFor(args));
      } catch (error) {}
      return original.apply(this, args);
    };
    wrapped.__bookwalkerTransformProbeWrapped = true;
    proto[name] = wrapped;
  }

  window.__bookwalkerTakeTransformTrace = () => {
    const firstRetained = state.operations[0]?.index ?? null;
    const lastRetained = state.operations[state.operations.length - 1]?.index ?? null;
    const result = {
      operations: state.operations.slice(),
      canvases: {...state.canvases},
      sources: {...state.sources},
      max_operations: maxOperations,
      trace_overflow: state.traceOverflow,
      overflow_operation_index: state.overflowOperationIndex,
      observed_operation_count: state.observedOperationCount,
      operations_before_overflow: state.overflowOperationIndex === null
        ? state.observedOperationCount
        : state.overflowOperationIndex - 1,
      retained_operation_count: state.operations.length,
      retained_first_operation_index: firstRetained,
      retained_last_operation_index: lastRetained,
      dropped_operation_count: state.droppedOperationCount,
      post_overflow_operation_counts: {...state.postOverflowOperationCounts},
      imagebitmap_snapshot_count: state.imageBitmapSnapshotCount,
      imagebitmap_snapshot_skipped_count: state.imageBitmapSnapshotSkippedCount,
      max_imagebitmap_snapshots: maxImageBitmapSnapshots,
      source_snapshot_policy: 'ImageBitmap_only_bounded',
      source_inventory_count: state.sourceInventoryCount,
      source_inventory_truncated_count: state.sourceInventoryTruncatedCount,
      canvas_inventory_count: state.canvasInventoryCount,
      canvas_inventory_truncated_count: state.canvasInventoryTruncatedCount,
      retention_policy: 'rolling_operation_window',
    };
    state.operations = [];
    state.canvases = {};
    state.sources = {};
    state.snapshotSources = new WeakSet();
    state.canvasIds = new WeakMap();
    state.sourceIds = new WeakMap();
    state.nextCanvasId = 1;
    state.nextSourceId = 1;
    state.nextOperationIndex = 1;
    state.observedOperationCount = 0;
    state.traceOverflow = false;
    state.overflowOperationIndex = null;
    state.droppedOperationCount = 0;
    state.postOverflowOperationCounts = {};
    state.imageBitmapSnapshotCount = 0;
    state.imageBitmapSnapshotSkippedCount = 0;
    state.sourceInventoryCount = 0;
    state.canvasInventoryCount = 0;
    state.sourceInventoryTruncatedCount = 0;
    state.canvasInventoryTruncatedCount = 0;
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


def _mapping_label(mapping_a: str | None, mapping_b: str | None) -> str:
    if mapping_a is None or mapping_b is None:
        return "MAPPING_UNAVAILABLE"
    if mapping_a == mapping_b:
        return "MAPPING_SAME"
    return "MAPPING_DIFFERENT"


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
            part.get("mapping_sha256"),
        )
        for page in first_pages
        for index, part in enumerate(page.get("parts", []), start=1)
    }
    second_by_key = {
        (_reload_page_key(page), int(part.get("part", index))): (
            part.get("raw", {}).get("sha256"),
            part.get("native", {}).get("sha256"),
            part.get("mapping_sha256"),
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
    mapping_comparison = [
        _mapping_label(first_by_key[key][2], second_by_key[key][2])
        for key in common_keys
    ]
    return {
        "runs_observed": len(runs),
        "classification": classifications,
        "classification_counts": dict(sorted(Counter(classifications).items())),
        "mapping_comparison": mapping_comparison,
        "mapping_comparison_counts": dict(sorted(Counter(mapping_comparison).items())),
        "compared_page_parts": [
            {
                "page_key": key[0],
                "part": key[1],
                "run_a_raw_sha256": first_by_key[key][0],
                "run_b_raw_sha256": second_by_key[key][0],
                "run_a_native_sha256": first_by_key[key][1],
                "run_b_native_sha256": second_by_key[key][1],
                "run_a_mapping_sha256": first_by_key[key][2],
                "run_b_mapping_sha256": second_by_key[key][2],
                "classification": _reload_label(
                    first_by_key[key][0],
                    first_by_key[key][1],
                    second_by_key[key][0],
                    second_by_key[key][1],
                ),
                "mapping_comparison": _mapping_label(
                    first_by_key[key][2],
                    second_by_key[key][2],
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
    groups: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    observed_groups: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    target_segments: dict[str, int] = {}
    for operation in trace.get("operations", []):
        target = operation.get("target") or {}
        target_id = str(target.get("canvasId"))
        if operation.get("operation") == "clearRect":
            target_segments[target_id] = target_segments.get(target_id, 0) + 1
        if operation.get("operation") != "drawImage":
            continue
        source = operation.get("source") or {}
        source_rect = operation.get("sourceRect") or {}
        destination = operation.get("destination") or {}
        if source.get("constructor") != "ImageBitmap":
            continue
        key = (
            target_id,
            str(source.get("sourceId")),
            target_segments.get(target_id, 0),
        )
        observed_groups.setdefault(key, []).append(operation)
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
        groups.setdefault(key, []).append(operation)

    public_groups: list[dict[str, Any]] = []
    detected = False
    for key, operations in groups.items():
        target_id, source_id, segment = key
        first_target = operations[0].get("target") or {}
        first_source = operations[0].get("source") or {}
        target_width = int(first_target["width"])
        target_height = int(first_target["height"])
        source_width = int(first_source["width"])
        source_height = int(first_source["height"])
        tile_shapes = Counter(
            (
                int((op.get("sourceRect") or {})["width"]),
                int((op.get("sourceRect") or {})["height"]),
            )
            for op in operations
        )
        tile_width, tile_height = tile_shapes.most_common(1)[0][0]
        expected_source_positions = {
            (left, top)
            for top in range(0, source_height, tile_height)
            for left in range(0, source_width, tile_width)
        }
        expected_destination_positions = {
            (left, top)
            for top in range(0, target_height, tile_height)
            for left in range(0, target_width, tile_width)
        }
        source_positions = [
            (int(op["sourceRect"]["x"]), int(op["sourceRect"]["y"]))
            for op in operations
        ]
        destination_positions = [
            (int(op["destination"]["x"]), int(op["destination"]["y"]))
            for op in operations
        ]
        source_counts = Counter(source_positions)
        destination_counts = Counter(destination_positions)
        source_unique = set(source_positions)
        destination_unique = set(destination_positions)
        source_out_of_bounds = sum(
            int(
                x < 0
                or y < 0
                or x + int(op["sourceRect"]["width"]) > source_width
                or y + int(op["sourceRect"]["height"]) > source_height
            )
            for op, (x, y) in zip(operations, source_positions, strict=True)
        )
        destination_out_of_bounds = sum(
            int(
                x < 0
                or y < 0
                or x + int(op["destination"]["width"]) > target_width
                or y + int(op["destination"]["height"]) > target_height
            )
            for op, (x, y) in zip(operations, destination_positions, strict=True)
        )
        source_duplicates = sum(max(0, count - 1) for count in source_counts.values())
        destination_duplicates = sum(
            max(0, count - 1) for count in destination_counts.values()
        )
        source_gaps = sorted(expected_source_positions - source_unique)
        destination_gaps = sorted(expected_destination_positions - destination_unique)
        source_extra = sorted(source_unique - expected_source_positions)
        destination_extra = sorted(destination_unique - expected_destination_positions)
        mapping = [
            {
                "source_x": int(op["sourceRect"]["x"]),
                "source_y": int(op["sourceRect"]["y"]),
                "destination_x": int(op["destination"]["x"]),
                "destination_y": int(op["destination"]["y"]),
                "width": int(op["sourceRect"]["width"]),
                "height": int(op["sourceRect"]["height"]),
            }
            for op in operations
        ]
        canonical_mapping = sorted(
            mapping,
            key=lambda item: (
                item["source_y"],
                item["source_x"],
                item["destination_y"],
                item["destination_x"],
                item["width"],
                item["height"],
            ),
        )
        mapping_sha256 = hashlib.sha256(
            json.dumps(canonical_mapping, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()
        partial_tile_count = sum(
            int(
                int((op.get("sourceRect") or {})["width"]) != tile_width
                or int((op.get("sourceRect") or {})["height"]) != tile_height
            )
            for op in operations
        )
        expected = len(expected_source_positions)
        complete_bijection = (
            len(operations) == expected
            and expected == len(expected_destination_positions)
            and source_duplicates == 0
            and destination_duplicates == 0
            and not source_gaps
            and not destination_gaps
            and not source_extra
            and not destination_extra
            and source_out_of_bounds == 0
            and destination_out_of_bounds == 0
        )
        moved = sum(
            int(op["sourceRect"]["x"]) != int(op["destination"]["x"])
            or int(op["sourceRect"]["y"]) != int(op["destination"]["y"])
            for op in operations
        )
        group_detected = complete_bijection and moved > 0
        detected = detected or group_detected
        public_groups.append(
            {
                "target_canvas_id": target_id,
                "source_id": source_id,
                "target_segment": segment,
                "target_dimensions": {"width": target_width, "height": target_height},
                "source_dimensions": {"width": source_width, "height": source_height},
                "tile_dimensions": {"width": tile_width, "height": tile_height},
                "operations": len(operations),
                "first_operation_index": min(
                    int(op.get("index", 0)) for op in operations
                ),
                "last_operation_index": max(
                    int(op.get("index", 0)) for op in operations
                ),
                "expected_tile_count": expected,
                "unique_source_tiles": len(source_unique),
                "unique_destination_tiles": len(destination_unique),
                "moved_tile_count": moved,
                "complete_permutation": complete_bijection,
                "complete_bijection": complete_bijection,
                "source_tile_overlap_count": source_duplicates,
                "destination_tile_overlap_count": destination_duplicates,
                "source_tile_gap_count": len(source_gaps),
                "destination_tile_gap_count": len(destination_gaps),
                "source_tile_gap_positions": [
                    {"x": x, "y": y} for x, y in source_gaps
                ],
                "destination_tile_gap_positions": [
                    {"x": x, "y": y} for x, y in destination_gaps
                ],
                "source_duplicate_tile_count": source_duplicates,
                "destination_duplicate_tile_count": destination_duplicates,
                "source_out_of_bounds_count": source_out_of_bounds,
                "destination_out_of_bounds_count": destination_out_of_bounds,
                "source_extra_positions": [
                    {"x": x, "y": y} for x, y in source_extra
                ],
                "destination_extra_positions": [
                    {"x": x, "y": y} for x, y in destination_extra
                ],
                "unique_source_x": sorted({x for x, _ in source_unique}),
                "unique_source_y": sorted({y for _, y in source_unique}),
                "unique_destination_x": sorted({x for x, _ in destination_unique}),
                "unique_destination_y": sorted({y for _, y in destination_unique}),
                "partial_tile_count": partial_tile_count,
                "edge_tile_count": sum(
                    int(
                        int(op["sourceRect"]["x"]) + int(op["sourceRect"]["width"])
                        == source_width
                        or int(op["sourceRect"]["y"]) + int(op["sourceRect"]["height"])
                        == source_height
                    )
                    for op in operations
                ),
                "mapping_sha256": mapping_sha256,
                "permutation_detected": group_detected,
                "mapping": canonical_mapping,
            }
        )
    rejected_groups: list[dict[str, Any]] = []
    accepted_keys = set(groups)
    for key, operations in observed_groups.items():
        if key in accepted_keys:
            continue
        target_id, source_id, segment = key
        first_target = operations[0].get("target") or {}
        first_source = operations[0].get("source") or {}
        source_rects = [operation.get("sourceRect") or {} for operation in operations]
        destinations = [operation.get("destination") or {} for operation in operations]
        target_width = target_height = source_width = source_height = None
        tile_width = tile_height = None
        source_columns = source_rows = target_columns = target_rows = None
        source_edge_width = source_edge_height = None
        target_edge_width = target_edge_height = None
        try:
            target_width = int(first_target.get("width"))
            target_height = int(first_target.get("height"))
            source_width = int(first_source.get("width"))
            source_height = int(first_source.get("height"))
            tile_shapes = Counter(
                (int(rect["width"]), int(rect["height"]))
                for rect in source_rects
                if "width" in rect and "height" in rect
            )
            tile_width, tile_height = tile_shapes.most_common(1)[0][0]
            source_columns = math.ceil(source_width / tile_width) if tile_width else None
            source_rows = math.ceil(source_height / tile_height) if tile_height else None
            target_columns = math.ceil(target_width / tile_width) if tile_width else None
            target_rows = math.ceil(target_height / tile_height) if tile_height else None
            source_edge_width = (
                source_width - (source_columns - 1) * tile_width
                if source_columns
                else None
            )
            target_edge_width = (
                target_width - (target_columns - 1) * tile_width
                if target_columns
                else None
            )
            source_edge_height = (
                source_height - (source_rows - 1) * tile_height
                if source_rows
                else None
            )
            target_edge_height = (
                target_height - (target_rows - 1) * tile_height
                if target_rows
                else None
            )
        except (IndexError, KeyError, TypeError, ValueError, ZeroDivisionError):
            pass
        reasons: list[str] = []
        if (
            isinstance(target_width, int)
            and isinstance(source_width, int)
            and (target_width != source_width or target_height != source_height)
        ):
            reasons.append("target_source_dimension_mismatch")
        if any(
            rect.get("width") != destination.get("width")
            or rect.get("height") != destination.get("height")
            for rect, destination in zip(source_rects, destinations, strict=True)
        ):
            reasons.append("source_destination_tile_size_mismatch")
        if tile_width is None or tile_height is None:
            reasons.append("tile_geometry_unavailable")
        else:
            if source_edge_width != tile_width or target_edge_width != tile_width:
                reasons.append("partial_horizontal_edge_tile")
            if source_edge_height != tile_height or target_edge_height != tile_height:
                reasons.append("partial_vertical_edge_tile")
        rejected_groups.append({
            "target_canvas_id": key[0],
            "source_id": key[1],
            "target_segment": segment,
            "target_dimensions": {
                "width": first_target.get("width"),
                "height": first_target.get("height"),
            },
            "source_dimensions": {
                "width": first_source.get("width"),
                "height": first_source.get("height"),
            },
            "tile_dimensions": {
                "width": tile_width,
                "height": tile_height,
            },
            "operations": len(operations),
            "first_operation_index": min(
                int(operation.get("index", 0)) for operation in operations
            ),
            "last_operation_index": max(
                int(operation.get("index", 0)) for operation in operations
            ),
            "expected_source_tile_count": (
                source_columns * source_rows
                if source_columns is not None and source_rows is not None
                else None
            ),
            "expected_destination_tile_count": (
                target_columns * target_rows
                if target_columns is not None and target_rows is not None
                else None
            ),
            "source_edge_dimensions": {
                "width": source_edge_width,
                "height": source_edge_height,
            },
            "destination_edge_dimensions": {
                "width": target_edge_width,
                "height": target_edge_height,
            },
            "rejection_reasons": reasons or ["strict_geometry_not_satisfied"],
        })
    return {
        "detected": detected,
        "groups": public_groups,
        "rejected_groups": rejected_groups,
    }


def _trace_source_operations_for_part(
    trace: dict[str, Any],
    part: dict[str, Any],
) -> list[tuple[dict[str, Any], bytes | None]]:
    matches: list[tuple[dict[str, Any], bytes | None]] = []
    for operation in trace.get("operations", []):
        if operation.get("operation") != "drawImage":
            continue
        op_source = operation.get("source") or {}
        if op_source.get("constructor") != part.get("source_constructor"):
            continue
        if op_source.get("width") != part.get("source_width"):
            continue
        if op_source.get("height") != part.get("source_height"):
            continue
        if not _same_dict_geometry(operation.get("sourceRect"), part.get("source_rect")):
            continue
        if not _same_dict_geometry(operation.get("destination"), part.get("destination")):
            continue
        matches.append(
            (
                _public_trace_operation(operation),
                _decode_png_data_url_local(operation.get("sourceSnapshotDataUrl")),
            )
        )
    return matches


def _trace_source_for_part(
    trace: dict[str, Any],
    part: dict[str, Any],
) -> tuple[dict[str, Any] | None, bytes | None]:
    matches = _trace_source_operations_for_part(trace, part)
    if matches:
        return matches[-1]
    return None, None


def _imagebitmap_match_by_id(
    matches: list[dict[str, Any]],
    source_id: str,
) -> dict[str, Any] | None:
    return next(
        (item for item in matches if str(item.get("source_id")) == source_id),
        None,
    )


def _mapping_status_for_part(
    *,
    source_operations: list[tuple[dict[str, Any], bytes | None]],
    group_candidates: list[dict[str, Any]],
    imagebitmap_match: dict[str, Any] | None,
) -> tuple[str, str]:
    if len(source_operations) != 1:
        return (
            "PART_MAPPING_AMBIGUOUS",
            "renderer-to-source draw operation is missing or not unique",
        )
    if len(group_candidates) != 1:
        return (
            "PART_MAPPING_AMBIGUOUS",
            "source canvas maps to zero or multiple permutation groups",
        )
    if imagebitmap_match is None:
        return "PART_MAPPING_AMBIGUOUS", "ImageBitmap source was not captured"
    exact_count = int(imagebitmap_match.get("exact_decoded_pixel_match_count", 0))
    if exact_count == 0:
        return "RAW_JPEG_NOT_IDENTIFIED", "ImageBitmap has no exact JPEG candidate"
    if exact_count > 1:
        return "RAW_JPEG_AMBIGUOUS", "ImageBitmap has multiple exact JPEG candidates"
    group = group_candidates[0]
    if not group.get("complete_bijection"):
        return "TILE_MAPPING_INCOMPLETE", "tile mapping is not a complete bijection"
    return "PART_MAPPING_PROVEN", "renderer/source/tile/ImageBitmap/raw chain is unique"


def _permutation_groups_for_part(
    trace: dict[str, Any],
    groups: list[dict[str, Any]],
    *,
    source_canvas_id: str,
    renderer_draw_index: int | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    history = [
        group
        for group in groups
        if str(group.get("target_canvas_id")) == source_canvas_id
    ]
    if renderer_draw_index is None:
        return [], history, []
    reset_indices = [
        int(operation.get("index", 0))
        for operation in trace.get("operations", [])
        if (
            operation.get("operation") == "clearRect"
            and str((operation.get("target") or {}).get("canvasId") or "")
            == source_canvas_id
            and int(operation.get("index", 0)) < renderer_draw_index
        )
    ]
    latest_reset_index = max(reset_indices, default=0)
    before_renderer = [
        group
        for group in history
        if (
            latest_reset_index < int(group.get("first_operation_index", 0))
            and int(group.get("last_operation_index", 0)) < renderer_draw_index
        )
    ]
    complete_before_renderer = [
        group for group in before_renderer if group.get("complete_bijection")
    ]
    if not complete_before_renderer:
        return [], history, []
    latest_index = max(
        int(group.get("last_operation_index", 0))
        for group in complete_before_renderer
    )
    selected = [
        group
        for group in complete_before_renderer
        if int(group.get("last_operation_index", 0)) == latest_index
    ]
    return selected, history, complete_before_renderer


def build_part_mapping_records(
    trace: dict[str, Any],
    native_parts: list[dict[str, Any]],
    tile_report: dict[str, Any],
    imagebitmap_matches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Join each native part to its object-identity-based transform chain."""

    groups = list(tile_report.get("groups", []))
    records: list[dict[str, Any]] = []
    for part_index, native_part in enumerate(native_parts, start=1):
        source_operations = _trace_source_operations_for_part(trace, native_part)
        selected_operation = source_operations[-1][0] if source_operations else None
        renderer = (selected_operation or {}).get("target") or {}
        source = (selected_operation or {}).get("source") or {}
        source_canvas_id = str(source.get("canvasId") or "")
        renderer_canvas_id = str(renderer.get("canvasId") or "")
        renderer_draw_index = (
            int(selected_operation.get("index"))
            if selected_operation and selected_operation.get("index") is not None
            else None
        )
        selected_group_candidates, permutation_history, window_groups = (
            _permutation_groups_for_part(
            trace,
            groups,
            source_canvas_id=source_canvas_id,
            renderer_draw_index=renderer_draw_index,
            )
        )
        group_candidates = window_groups
        group = (
            selected_group_candidates[0]
            if len(selected_group_candidates) == 1
            else None
        )
        imagebitmap_source_id = str(group.get("source_id") or "") if group else ""
        imagebitmap_match = _imagebitmap_match_by_id(
            imagebitmap_matches,
            imagebitmap_source_id,
        )
        status, reason = _mapping_status_for_part(
            source_operations=source_operations,
            group_candidates=group_candidates,
            imagebitmap_match=imagebitmap_match,
        )
        imagebitmap = None
        if imagebitmap_match is not None:
            imagebitmap = {
                "source_id": imagebitmap_match.get("source_id"),
                "dimensions": imagebitmap_match.get("source_dimensions"),
                "snapshot_sha256": imagebitmap_match.get("snapshot_sha256"),
                "candidate_count_compared": imagebitmap_match.get(
                    "candidate_count_compared"
                ),
                "exact_decoded_pixel_match_count": imagebitmap_match.get(
                    "exact_decoded_pixel_match_count", 0
                ),
                "exact_candidate_sha256": imagebitmap_match.get(
                    "exact_candidate_sha256", []
                ),
                "best_candidates": imagebitmap_match.get("best_candidates", [])[:5],
            }
        record = {
            "part": part_index,
            "renderer": {
                "canvas_id": renderer_canvas_id or None,
                "target_dimensions": {
                    "width": renderer.get("width"),
                    "height": renderer.get("height"),
                },
                "draw_operation_index": (
                    selected_operation.get("index") if selected_operation else None
                ),
                "source_canvas_id": source_canvas_id or None,
                "source_constructor": source.get("constructor"),
                "source_dimensions": {
                    "width": source.get("width"),
                    "height": source.get("height"),
                },
                "source_rect": (
                    selected_operation.get("sourceRect") if selected_operation else None
                ),
                "destination": (
                    selected_operation.get("destination") if selected_operation else None
                ),
                "transform": (
                    selected_operation.get("transform") if selected_operation else None
                ),
                "filter": (
                    selected_operation.get("filter") if selected_operation else None
                ),
                "global_alpha": (
                    selected_operation.get("globalAlpha")
                    if selected_operation else None
                ),
                "global_composite_operation": (
                    selected_operation.get("globalCompositeOperation")
                    if selected_operation else None
                ),
            },
            "source_canvas": {
                "canvas_id": source_canvas_id or None,
                "width": source.get("width"),
                "height": source.get("height"),
            },
            "permutation": group,
            "permutation_group_count": len(group_candidates),
            "multiple_imagebitmap_sources": len(group_candidates) > 1,
            "permutation_candidates": group_candidates,
            "permutation_history_count": len(permutation_history),
            "permutation_history": [
                {
                    "source_id": item.get("source_id"),
                    "first_operation_index": item.get("first_operation_index"),
                    "last_operation_index": item.get("last_operation_index"),
                    "complete_bijection": item.get("complete_bijection"),
                    "mapping_sha256": item.get("mapping_sha256"),
                }
                for item in permutation_history
            ],
            "imagebitmap": imagebitmap,
            "raw_jpeg": {},
            "mapping_status": status,
            "mapping_reason": reason,
        }
        record["trace_diagnostic"] = trace_mapping_window_diagnostic(
            trace,
            record,
            groups,
            list(tile_report.get("rejected_groups", [])),
        )
        record["renderer_geometry"] = renderer_geometry_report(
            record["renderer"],
        )
        records.append(record)
    return records


def classify_part_from_mapping(
    analysis: dict[str, Any] | None,
    mapping: dict[str, Any],
) -> str:
    """Classify a part only after its own mapping evidence is available."""

    if mapping.get("multiple_imagebitmap_sources"):
        return "MULTI_SOURCE_PERMUTATION"
    if mapping.get("mapping_status") == "PART_MAPPING_PROVEN":
        permutation = mapping.get("permutation") or {}
        if permutation.get("permutation_detected"):
            return "TILE_REARRANGEMENT"
        return "DIRECT_DECODE"
    return str((analysis or {}).get("classification") or "UNKNOWN")


def _trace_integer(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _trace_retention_metadata(trace: dict[str, Any]) -> dict[str, Any]:
    operations = trace.get("operations", [])
    observed = _trace_integer(trace.get("observed_operation_count"))
    if observed is None:
        observed = max(
            (_trace_integer(operation.get("index")) or 0 for operation in operations),
            default=len(operations),
        )
    overflow_index = _trace_integer(trace.get("overflow_operation_index"))
    retained_first = _trace_integer(trace.get("retained_first_operation_index"))
    retained_last = _trace_integer(trace.get("retained_last_operation_index"))
    if retained_first is None and operations:
        retained_first = min(
            (_trace_integer(operation.get("index")) or 0 for operation in operations),
        )
    if retained_last is None and operations:
        retained_last = max(
            (_trace_integer(operation.get("index")) or 0 for operation in operations),
        )
    return {
        "trace_overflow": bool(trace.get("trace_overflow")) or overflow_index is not None,
        "max_operations": _trace_integer(trace.get("max_operations"))
        or MAX_OPERATION_RECORDS,
        "observed_operation_count": observed,
        "overflow_operation_index": overflow_index,
        "operations_before_overflow": (
            max(0, overflow_index - 1)
            if overflow_index is not None
            else observed
        ),
        "retained_operation_count": len(operations),
        "retained_first_operation_index": retained_first,
        "retained_last_operation_index": retained_last,
        "dropped_operation_count": _trace_integer(
            trace.get("dropped_operation_count")
        ) or 0,
        "post_overflow_operation_counts": {
            str(key): int(value)
            for key, value in (trace.get("post_overflow_operation_counts") or {}).items()
            if isinstance(value, (int, float))
        },
        "imagebitmap_snapshot_count": _trace_integer(
            trace.get("imagebitmap_snapshot_count")
        ) or 0,
        "imagebitmap_snapshot_skipped_count": _trace_integer(
            trace.get("imagebitmap_snapshot_skipped_count")
        ) or 0,
        "max_imagebitmap_snapshots": _trace_integer(
            trace.get("max_imagebitmap_snapshots")
        ) or 32,
        "source_inventory_count": _trace_integer(
            trace.get("source_inventory_count")
        ) or 0,
        "source_inventory_truncated_count": _trace_integer(
            trace.get("source_inventory_truncated_count")
        ) or 0,
        "canvas_inventory_count": _trace_integer(
            trace.get("canvas_inventory_count")
        ) or 0,
        "canvas_inventory_truncated_count": _trace_integer(
            trace.get("canvas_inventory_truncated_count")
        ) or 0,
        "retention_policy": trace.get(
            "retention_policy", "rolling_operation_window"
        ),
    }


def renderer_geometry_report(renderer: dict[str, Any]) -> dict[str, Any]:
    """Classify renderer scaling/cropping without changing production policy."""

    source_dimensions = renderer.get("source_dimensions") or {}
    target_dimensions = renderer.get("target_dimensions") or {}
    source_rect = renderer.get("source_rect") or {}
    destination = renderer.get("destination") or {}
    source_width = _trace_integer(source_dimensions.get("width"))
    source_height = _trace_integer(source_dimensions.get("height"))
    source_full = (
        source_width is not None
        and source_height is not None
        and all(
            abs(float(source_rect.get(key, float("nan"))) - expected) < 1e-6
            for key, expected in {
                "x": 0,
                "y": 0,
                "width": source_width,
                "height": source_height,
            }.items()
        )
    )
    destination_width = _trace_integer(destination.get("width"))
    destination_height = _trace_integer(destination.get("height"))
    destination_matches_source = (
        source_width is not None
        and source_height is not None
        and destination_width == source_width
        and destination_height == source_height
    )
    transform = renderer.get("transform") or {}
    identity_transform = (
        transform in ({}, None)
        or all(
            float(transform.get(key, 0)) == expected
            for key, expected in {
                "a": 1,
                "b": 0,
                "c": 0,
                "d": 1,
                "e": 0,
                "f": 0,
            }.items()
        )
    )
    safe_settings = (
        identity_transform
        and renderer.get("global_alpha") in (None, 1, 1.0)
        and renderer.get("global_composite_operation") in (None, "source-over")
        and renderer.get("filter") in (None, "none")
    )
    target_width = _trace_integer(target_dimensions.get("width"))
    target_height = _trace_integer(target_dimensions.get("height"))
    destination_in_target = (
        target_width is not None
        and target_height is not None
        and _trace_integer(destination.get("x")) is not None
        and _trace_integer(destination.get("y")) is not None
        and destination_width is not None
        and destination_height is not None
        and int(destination["x"]) >= 0
        and int(destination["y"]) >= 0
        and int(destination["x"]) + destination_width <= target_width
        and int(destination["y"]) + destination_height <= target_height
    )
    if source_width is None or source_height is None or not destination:
        classification = "GEOMETRY_UNAVAILABLE"
    elif source_full and safe_settings and destination_matches_source:
        classification = "DIRECT_RENDERER_DRAW"
    elif source_full and safe_settings:
        classification = "PURE_RENDERER_SCALE"
    else:
        classification = "CROP_OR_PIXEL_PROCESSING"
    return {
        "classification": classification,
        "source_dimensions": {
            "width": source_width,
            "height": source_height,
        },
        "target_dimensions": {
            "width": target_width,
            "height": target_height,
        },
        "source_rect": source_rect or None,
        "destination": destination or None,
        "source_rect_is_full": source_full,
        "destination_matches_source_dimensions": destination_matches_source,
        "destination_differs_from_source_dimensions": (
            not destination_matches_source
            if destination_width is not None and destination_height is not None
            else None
        ),
        "destination_within_target": destination_in_target,
        "identity_transform": identity_transform,
        "safe_renderer_settings": safe_settings,
        "css_or_display_scaling_not_inferred": True,
    }


def trace_mapping_window_diagnostic(
    trace: dict[str, Any],
    mapping: dict[str, Any],
    groups: list[dict[str, Any]],
    rejected_groups: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Explain whether a retained mapping window crosses trace overflow."""

    retention = _trace_retention_metadata(trace)
    renderer = mapping.get("renderer") or {}
    renderer_index = _trace_integer(renderer.get("draw_operation_index"))
    source_canvas_id = str(renderer.get("source_canvas_id") or "")
    overflow_index = retention["overflow_operation_index"]
    retained_first = retention["retained_first_operation_index"]
    retained_last = retention["retained_last_operation_index"]
    reset_indices = [
        _trace_integer(operation.get("index"))
        for operation in trace.get("operations", [])
        if (
            operation.get("operation") == "clearRect"
            and str((operation.get("target") or {}).get("canvasId") or "")
            == source_canvas_id
            and renderer_index is not None
            and (_trace_integer(operation.get("index")) or 0) < renderer_index
        )
    ]
    reset_indices = [index for index in reset_indices if index is not None]
    latest_clear_index = max(reset_indices, default=0)
    source_groups = [
        group
        for group in groups
        if str(group.get("target_canvas_id") or "") == source_canvas_id
        and renderer_index is not None
        and (_trace_integer(group.get("last_operation_index")) or 0) < renderer_index
        and (_trace_integer(group.get("first_operation_index")) or 0) > latest_clear_index
    ]
    source_groups.sort(
        key=lambda group: _trace_integer(group.get("last_operation_index")) or 0,
    )
    current_group = source_groups[-1] if source_groups else mapping.get("permutation")
    rejected_source_groups = [
        group
        for group in rejected_groups or []
        if str(group.get("target_canvas_id") or "") == source_canvas_id
        and renderer_index is not None
        and (_trace_integer(group.get("last_operation_index")) or 0) < renderer_index
        and (_trace_integer(group.get("first_operation_index")) or 0) > latest_clear_index
    ]
    rejected_source_groups.sort(
        key=lambda group: _trace_integer(group.get("last_operation_index")) or 0,
    )
    observed_group = current_group or (
        rejected_source_groups[-1] if rejected_source_groups else None
    )
    mapping_first = (
        _trace_integer(observed_group.get("first_operation_index"))
        if observed_group
        else None
    )
    mapping_last = (
        _trace_integer(observed_group.get("last_operation_index"))
        if observed_group
        else None
    )
    mapping_complete = bool(current_group and current_group.get("complete_bijection"))
    mapping_geometry_rejected = bool(not current_group and rejected_source_groups)
    current_window_start = latest_clear_index + 1
    current_window_end = (renderer_index - 1) if renderer_index is not None else None
    window_fully_retained = bool(
        current_window_end is not None
        and retained_first is not None
        and retained_last is not None
        and current_window_start >= retained_first
        and current_window_end <= retained_last
    )
    mapping_fully_retained = bool(
        mapping_first is not None
        and mapping_last is not None
        and retained_first is not None
        and retained_last is not None
        and mapping_first >= retained_first
        and mapping_last <= retained_last
    )
    selected_before_overflow = bool(
        renderer_index is not None
        and overflow_index is not None
        and renderer_index < overflow_index
    )
    selected_after_overflow = bool(
        renderer_index is not None
        and overflow_index is not None
        and renderer_index >= overflow_index
    )
    overflow_after_mapping = bool(
        overflow_index is not None
        and mapping_last is not None
        and overflow_index > mapping_last
    )
    overflow_before_or_during_mapping = bool(
        overflow_index is not None
        and mapping_last is not None
        and overflow_index <= mapping_last
    )
    if overflow_index is None:
        category = "NO_TRACE_OVERFLOW"
    elif renderer_index is None:
        category = "TRACE_OVERFLOW_RENDERER_NOT_RETAINED"
    elif mapping_complete and window_fully_retained:
        if overflow_after_mapping:
            category = "OVERFLOW_AFTER_CURRENT_MAPPING"
        elif selected_after_overflow:
            category = "OVERFLOW_BEFORE_RENDERER_MAPPING_RETAINED"
        else:
            category = "MAPPING_COMPLETE_BEFORE_OVERFLOW"
    elif not window_fully_retained:
        category = "OVERFLOW_CURRENT_MAPPING_WINDOW_NOT_RETAINED"
    else:
        category = "OVERFLOW_CURRENT_MAPPING_INCOMPLETE"
    return {
        **retention,
        "renderer_draw_operation_index": renderer_index,
        "renderer_draw_before_overflow": selected_before_overflow,
        "renderer_draw_after_overflow": selected_after_overflow,
        "source_canvas_id": source_canvas_id or None,
        "latest_clear_operation_index": latest_clear_index or None,
        "current_mapping_first_operation_index": mapping_first,
        "current_mapping_last_operation_index": mapping_last,
        "current_mapping_expected_tile_count": (
            observed_group.get(
                "expected_tile_count",
                observed_group.get("expected_source_tile_count"),
            )
            if observed_group
            else None
        ),
        "current_mapping_operation_count": (
            observed_group.get("operations") if observed_group else 0
        ),
        "current_mapping_complete_bijection": mapping_complete,
        "current_mapping_geometry_rejected": mapping_geometry_rejected,
        "current_mapping_geometry_rejection_reasons": (
            list((observed_group or {}).get("rejection_reasons") or [])
            if mapping_geometry_rejected
            else []
        ),
        "current_mapping_category": (
            "GEOMETRY_REJECTED"
            if mapping_geometry_rejected
            else "COMPLETE_BIJECTION"
            if mapping_complete
            else "UNAVAILABLE"
        ),
        "current_mapping_window_start_index": current_window_start,
        "current_mapping_window_end_index": current_window_end,
        "current_mapping_window_fully_retained": window_fully_retained,
        "current_mapping_fully_retained": mapping_fully_retained,
        "overflow_after_current_mapping": overflow_after_mapping,
        "overflow_before_or_during_current_mapping": (
            overflow_before_or_during_mapping
        ),
        "overflow_category": category,
    }


def _jpeg_sof_marker(marker: int) -> bool:
    return marker in {
        0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
        0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
    }


def jpeg_mcu_geometry(data: bytes) -> dict[str, Any] | None:
    """Read JPEG SOF sampling factors and coded MCU dimensions."""

    if not data.startswith(b"\xff\xd8"):
        return None
    offset = 2
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
        if marker == 0x00:
            continue
        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        if offset + 2 > len(data):
            break
        segment_length = int.from_bytes(data[offset : offset + 2], "big")
        if segment_length < 2 or offset + segment_length > len(data):
            break
        if _jpeg_sof_marker(marker) and segment_length >= 8:
            height = int.from_bytes(data[offset + 3 : offset + 5], "big")
            width = int.from_bytes(data[offset + 5 : offset + 7], "big")
            component_count = data[offset + 7]
            components: list[dict[str, int]] = []
            component_offset = offset + 8
            for _ in range(component_count):
                if component_offset + 3 > offset + segment_length:
                    return None
                component_id = data[component_offset]
                sampling = data[component_offset + 1]
                components.append(
                    {
                        "id": component_id,
                        "horizontal_sampling_factor": sampling >> 4,
                        "vertical_sampling_factor": sampling & 0x0F,
                    }
                )
                component_offset += 3
            max_horizontal = max(
                (item["horizontal_sampling_factor"] for item in components),
                default=0,
            )
            max_vertical = max(
                (item["vertical_sampling_factor"] for item in components),
                default=0,
            )
            if not max_horizontal or not max_vertical:
                return None
            mcu_width = 8 * max_horizontal
            mcu_height = 8 * max_vertical
            coded_width = math.ceil(width / mcu_width) * mcu_width
            coded_height = math.ceil(height / mcu_height) * mcu_height
            return {
                "sof_marker": f"0x{marker:02X}",
                "visible_width": width,
                "visible_height": height,
                "component_count": component_count,
                "components": components,
                "max_horizontal_sampling_factor": max_horizontal,
                "max_vertical_sampling_factor": max_vertical,
                "mcu_width": mcu_width,
                "mcu_height": mcu_height,
                "coded_width": coded_width,
                "coded_height": coded_height,
                "right_edge_padding": coded_width - width,
                "bottom_edge_padding": coded_height - height,
            }
        offset += segment_length
        if marker == 0xDA:
            break
    return None


def _mcu_rect_aligned(
    rect: dict[str, Any],
    *,
    mcu_width: int,
    mcu_height: int,
    visible_width: int,
    visible_height: int,
) -> bool:
    try:
        x = int(rect["x"])
        y = int(rect["y"])
        width = int(rect["width"])
        height = int(rect["height"])
    except (KeyError, TypeError, ValueError):
        return False
    if x % mcu_width or y % mcu_height:
        return False
    right = x + width
    bottom = y + height
    width_ok = width % mcu_width == 0 or right == visible_width
    height_ok = height % mcu_height == 0 or bottom == visible_height
    return width_ok and height_ok


def mcu_alignment_report(
    raw_data: bytes,
    permutation: dict[str, Any] | None,
) -> dict[str, Any]:
    geometry = jpeg_mcu_geometry(raw_data)
    if geometry is None:
        return {"available": False, "reason": "JPEG SOF sampling factors unavailable"}
    if not permutation:
        return {
            "available": True,
            "geometry": geometry,
            "source_tile_mcu_aligned": False,
            "destination_tile_mcu_aligned": False,
            "all_mapping_mcu_aligned": False,
            "reason": "permutation group unavailable",
        }
    mapping = permutation.get("mapping") or []
    source_ok = all(
        _mcu_rect_aligned(
            {
                "x": item.get("source_x"),
                "y": item.get("source_y"),
                "width": item.get("width"),
                "height": item.get("height"),
            },
            mcu_width=int(geometry["mcu_width"]),
            mcu_height=int(geometry["mcu_height"]),
            visible_width=int(geometry["visible_width"]),
            visible_height=int(geometry["visible_height"]),
        )
        for item in mapping
    )
    destination_width = int((permutation.get("target_dimensions") or {}).get("width", 0))
    destination_height = int((permutation.get("target_dimensions") or {}).get("height", 0))
    destination_ok = all(
        _mcu_rect_aligned(
            {
                "x": item.get("destination_x"),
                "y": item.get("destination_y"),
                "width": item.get("width"),
                "height": item.get("height"),
            },
            mcu_width=int(geometry["mcu_width"]),
            mcu_height=int(geometry["mcu_height"]),
            visible_width=destination_width,
            visible_height=destination_height,
        )
        for item in mapping
    )
    strict_source_ok = all(
        int(item.get("source_x", -1)) % int(geometry["mcu_width"]) == 0
        and int(item.get("source_y", -1)) % int(geometry["mcu_height"]) == 0
        and int(item.get("width", 0)) % int(geometry["mcu_width"]) == 0
        and int(item.get("height", 0)) % int(geometry["mcu_height"]) == 0
        for item in mapping
    )
    strict_destination_ok = all(
        int(item.get("destination_x", -1)) % int(geometry["mcu_width"]) == 0
        and int(item.get("destination_y", -1)) % int(geometry["mcu_height"]) == 0
        and int(item.get("width", 0)) % int(geometry["mcu_width"]) == 0
        and int(item.get("height", 0)) % int(geometry["mcu_height"]) == 0
        for item in mapping
    )
    return {
        "available": True,
        "geometry": geometry,
        "source_tile_mcu_aligned": source_ok,
        "destination_tile_mcu_aligned": destination_ok,
        "all_mapping_mcu_aligned": source_ok and destination_ok,
        "strict_source_tile_mcu_aligned": strict_source_ok,
        "strict_destination_tile_mcu_aligned": strict_destination_ok,
        "strict_all_mapping_mcu_aligned": strict_source_ok and strict_destination_ok,
        "mapping_count": len(mapping),
        "edge_condition": {
            "coded_width": geometry["coded_width"],
            "coded_height": geometry["coded_height"],
            "visible_width": geometry["visible_width"],
            "visible_height": geometry["visible_height"],
            "right_edge_padding": geometry["right_edge_padding"],
            "bottom_edge_padding": geometry["bottom_edge_padding"],
            "partial_visible_edge_allowed": bool(
                geometry["right_edge_padding"] or geometry["bottom_edge_padding"]
            ),
        },
    }


def _operation_rect(operation: dict[str, Any]) -> dict[str, int] | None:
    arguments = operation.get("arguments")
    if not isinstance(arguments, list) or len(arguments) < 4:
        return None
    try:
        return {
            "x": int(arguments[0]),
            "y": int(arguments[1]),
            "width": int(arguments[2]),
            "height": int(arguments[3]),
        }
    except (TypeError, ValueError):
        return None


def _rect_intersects(first: dict[str, Any], second: dict[str, Any]) -> bool:
    try:
        return not (
            float(first["x"]) + float(first["width"]) <= float(second["x"])
            or float(second["x"]) + float(second["width"]) <= float(first["x"])
            or float(first["y"]) + float(first["height"]) <= float(second["y"])
            or float(second["y"]) + float(second["height"]) <= float(first["y"])
        )
    except (KeyError, TypeError, ValueError):
        return False


def _is_identity_transform(value: object) -> bool:
    if value is None:
        return True
    if not isinstance(value, dict):
        return False
    return all(
        round(float(value.get(key, math.nan)), 9) == expected
        for key, expected in {
            "a": 1,
            "b": 0,
            "c": 0,
            "d": 1,
            "e": 0,
            "f": 0,
        }.items()
    )


def transformation_safety_report(
    trace: dict[str, Any],
    mapping: dict[str, Any],
) -> dict[str, Any]:
    source_canvas_id = str((mapping.get("source_canvas") or {}).get("canvas_id") or "")
    renderer_canvas_id = str((mapping.get("renderer") or {}).get("canvas_id") or "")
    source_canvas = (mapping.get("source_canvas") or {})
    source_area = {
        "x": 0,
        "y": 0,
        "width": int(source_canvas.get("width") or 0),
        "height": int(source_canvas.get("height") or 0),
    }
    renderer_destination = (mapping.get("renderer") or {}).get("destination")
    source_operations = [
        operation
        for operation in trace.get("operations", [])
        if str((operation.get("target") or {}).get("canvasId") or "") == source_canvas_id
    ]
    renderer_operations = [
        operation
        for operation in trace.get("operations", [])
        if str((operation.get("target") or {}).get("canvasId") or "") == renderer_canvas_id
    ]
    renderer_draw_index = int(
        (mapping.get("renderer") or {}).get("draw_operation_index") or 0
    )
    permutation = mapping.get("permutation") or {}
    chain_start = int(permutation.get("first_operation_index") or 0)
    chain_end = renderer_draw_index or None
    reset_before_chain = [
        operation
        for operation in source_operations
        if (
            operation.get("operation") == "clearRect"
            and int(operation.get("index", 0)) < chain_start
        )
    ]
    latest_reset_before_chain = max(
        reset_before_chain,
        key=lambda operation: int(operation.get("index", 0)),
        default=None,
    )
    source_non_draw = [
        operation
        for operation in source_operations
        if (
            operation.get("operation") != "drawImage"
            and int(operation.get("index", 0)) >= chain_start
            and (chain_end is None or int(operation.get("index", 0)) < chain_end)
        )
    ]
    source_content_writes: list[dict[str, Any]] = []
    source_initialization_clears: list[dict[str, Any]] = []
    for operation in source_non_draw:
        name = str(operation.get("operation"))
        if name not in {"putImageData", "fillRect", "strokeRect", "clearRect"}:
            continue
        rect = _operation_rect(operation)
        public = {"index": operation.get("index"), "operation": name, "rect": rect}
        source_content_writes.append(public)
    source_initialization_clears = list(source_initialization_clears)
    if (
        latest_reset_before_chain is not None
        and _operation_rect(latest_reset_before_chain) == source_area
    ):
        source_initialization_clears.append(
            {
                "index": latest_reset_before_chain.get("index"),
                "operation": "clearRect",
                "rect": source_area,
            }
        )
    renderer_content_writes: list[dict[str, Any]] = []
    renderer_background_operations: list[dict[str, Any]] = []
    renderer_edge_operations: list[dict[str, Any]] = []
    for operation in renderer_operations:
        name = str(operation.get("operation"))
        if name not in {"putImageData", "fillRect", "strokeRect", "clearRect"}:
            continue
        rect = _operation_rect(operation)
        public = {"index": operation.get("index"), "operation": name, "rect": rect}
        index = int(operation.get("index", 0))
        is_edge = (
            name == "fillRect"
            and rect is not None
            and min(abs(rect["width"]), abs(rect["height"])) <= 2
        )
        if is_edge:
            renderer_edge_operations.append(public)
        elif renderer_draw_index and index < renderer_draw_index:
            renderer_background_operations.append(public)
        elif renderer_destination and rect and _rect_intersects(rect, renderer_destination):
            renderer_content_writes.append(public)
    relevant_draws = [
        operation
        for operation in trace.get("operations", [])
        if (
            operation.get("operation") == "drawImage"
            and str((operation.get("target") or {}).get("canvasId") or "")
            in {source_canvas_id, renderer_canvas_id}
        )
    ]
    unsafe_draw_settings = [
        {
            "index": operation.get("index"),
            "target_canvas_id": (operation.get("target") or {}).get("canvasId"),
            "global_alpha": operation.get("globalAlpha"),
            "global_composite_operation": operation.get("globalCompositeOperation"),
            "transform": operation.get("transform"),
            "filter": operation.get("filter"),
        }
        for operation in relevant_draws
        if operation.get("globalAlpha") not in {None, 1}
        or operation.get("globalCompositeOperation") not in {None, "source-over"}
        or operation.get("filter") not in {None, "", "none"}
        or not _is_identity_transform(operation.get("transform"))
    ]
    return {
        "source_canvas_id": source_canvas_id or None,
        "renderer_canvas_id": renderer_canvas_id or None,
        "source_canvas_non_draw_operations": [
            {"index": operation.get("index"), "operation": operation.get("operation")}
            for operation in source_non_draw
        ],
        "source_canvas_initialization_clears": source_initialization_clears,
        "source_canvas_content_writes": source_content_writes,
        "renderer_background_operations": renderer_background_operations,
        "renderer_edge_operations": renderer_edge_operations,
        "renderer_intersecting_content_writes": renderer_content_writes,
        "unsafe_draw_settings": unsafe_draw_settings,
        "additional_pixel_processing": bool(
            source_content_writes or renderer_content_writes or unsafe_draw_settings
        ),
        "source_canvas_tile_draw_count": sum(
            int(operation.get("operation") == "drawImage")
            for operation in source_operations
            if chain_start <= int(operation.get("index", 0))
            and (chain_end is None or int(operation.get("index", 0)) < chain_end)
        ),
    }


def part_readiness_classification(
    mapping: dict[str, Any],
    *,
    safety: dict[str, Any],
    mcu: dict[str, Any],
) -> str:
    status = mapping.get("mapping_status")
    if status == "PART_MAPPING_AMBIGUOUS":
        return "PART_MAPPING_AMBIGUOUS"
    if status == "RAW_JPEG_NOT_IDENTIFIED":
        return "RAW_JPEG_NOT_IDENTIFIED"
    if status == "RAW_JPEG_AMBIGUOUS":
        return "RAW_JPEG_AMBIGUOUS"
    if status == "TILE_MAPPING_INCOMPLETE":
        return "TILE_MAPPING_INCOMPLETE"
    if status != "PART_MAPPING_PROVEN":
        classification = mapping.get("classification")
        return str(classification or "UNKNOWN")
    if safety.get("additional_pixel_processing"):
        return "ADDITIONAL_PIXEL_PROCESSING"
    if not mcu.get("all_mapping_mcu_aligned"):
        return "MCU_ALIGNMENT_UNSAFE"
    return "LOSSLESS_JPEG_REARRANGEMENT_READY"


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
    retention = _trace_retention_metadata(trace)
    return {
        "operation_count": len(operations),
        **retention,
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
        "bounded": bool(retention["trace_overflow"])
        or len(operations) >= MAX_OPERATION_RECORDS,
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
            **_public_candidate(candidate),
            "selection_rank": list(rank),
            "selection_reasons": reasons,
        })
    if not ranked:
        return None, public_pool
    return ranked[0][1], public_pool


def _redacted_path(value: str | None) -> str:
    parts = str(value or "").split("/")
    return "/".join(
        "<redacted>" if len(part) > 96 else part
        for part in parts
    )


def _public_candidate(candidate: MagicJpegCandidate) -> dict[str, Any]:
    public = candidate.public()
    public["url"] = redact_url(str(public.get("url") or ""))
    public["path"] = _redacted_path(candidate.path)
    return public


def _redact_matching_details(details: dict[str, Any]) -> dict[str, Any]:
    public = dict(details)
    matched = []
    for item in details.get("matched_candidates", []) or []:
        if not isinstance(item, dict):
            continue
        redacted = dict(item)
        redacted["url"] = redact_url(str(redacted.get("url") or ""))
        redacted["path"] = _redacted_path(redacted.get("path"))
        matched.append(redacted)
    if "matched_candidates" in details:
        public["matched_candidates"] = matched
    return public


def _compact_candidate(candidate: MagicJpegCandidate) -> dict[str, Any]:
    return {
        "record_index": candidate.record_index,
        "page_index": candidate.page_index,
        "sha256": candidate.metadata.get("sha256"),
        "hostname": candidate.hostname,
        "path": _redacted_path(candidate.path),
        "dimensions": {
            "width": candidate.metadata.get("width"),
            "height": candidate.metadata.get("height"),
        },
        "route_match": candidate.route_match,
        "filter_match": candidate.filter_match,
        "estimated_quality": candidate.metadata.get("estimated_quality"),
        "subsampling": candidate.metadata.get("subsampling"),
    }


def candidate_matching_diagnostic(
    candidate_pool: list[dict[str, Any]],
    native: dict[str, Any],
    selected: MagicJpegCandidate | None,
    *,
    imagebitmap: dict[str, Any],
    selection_strategy: str,
) -> dict[str, Any]:
    dimensions = {
        "width": native.get("width"),
        "height": native.get("height"),
    }
    dimension_matches = [
        item for item in candidate_pool
        if item.get("selection_reasons", {}).get("dimensions_match")
    ]
    signature_matches = [
        item for item in candidate_pool
        if item.get("selection_reasons", {}).get("signature_match")
    ]
    selected_metadata = None
    if selected is not None:
        selected_metadata = {
            "record_index": selected.record_index,
            "page_index": selected.page_index,
            "sha256": selected.metadata.get("sha256"),
            "dimensions": {
                "width": selected.metadata.get("width"),
                "height": selected.metadata.get("height"),
            },
            "byte_size": selected.metadata.get("byte_size"),
            "hostname": selected.hostname,
            "path": _redacted_path(selected.path),
            "route_match": selected.route_match,
            "filter_match": selected.filter_match,
        }
    exact_count = int(imagebitmap.get("exact_decoded_pixel_match_count", 0) or 0)
    if selected is None:
        decision = "NO_CANDIDATE_SELECTED"
    elif exact_count == 1:
        decision = "IMAGEBITMAP_EXACT_CANDIDATE_SELECTED"
    elif len(signature_matches) == 1:
        decision = "SIGNATURE_CANDIDATE_SELECTED"
    elif len(dimension_matches) == 1:
        decision = "DIMENSION_CANDIDATE_SELECTED"
    else:
        decision = "RANKED_CANDIDATE_SELECTED"
    return {
        "production_original_path_invoked": False,
        "production_original_path_note": (
            "The diagnostic does not call capture_page(); this is bounded "
            "candidate evidence for the existing original-JPEG decision."
        ),
        "native_dimensions": dimensions,
        "candidate_count_total": len(candidate_pool),
        "candidate_count_dimension_match": len(dimension_matches),
        "candidate_count_signature_match": len(signature_matches),
        "imagebitmap_exact_decoded_match_count": exact_count,
        "selection_strategy": selection_strategy,
        "decision": decision,
        "selected": selected_metadata,
        "dimension_match_record_indices": [
            item.get("record_index") for item in dimension_matches
        ],
        "signature_match_record_indices": [
            item.get("record_index") for item in signature_matches
        ],
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
        exact_candidates = [
            item["sha256"]
            for item in matches
            if item["pixel_metrics"]["exact_pixel_equality"]
        ]
        result.append({
            "source_id": source_id,
            "source_dimensions": {
                "width": source_image.width,
                "height": source_image.height,
            },
            "snapshot_sha256": hashlib.sha256(data).hexdigest(),
            "candidate_count_compared": len(matches),
            "exact_decoded_pixel_match_count": len(exact_candidates),
            "exact_candidate_sha256": exact_candidates,
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


def part_mapping_summary(page_records: list[dict[str, Any]]) -> dict[str, Any]:
    mappings = [
        mapping
        for page in page_records
        for mapping in page.get("part_mappings", [])
    ]
    permutations = [
        mapping.get("permutation") or {}
        for mapping in mappings
        if mapping.get("permutation")
    ]
    mcu_reports = [
        mapping.get("mcu_alignment") or {}
        for mapping in mappings
        if mapping.get("mcu_alignment")
    ]
    return {
        "pages_observed": len(page_records),
        "parts_observed": len(mappings),
        "mapping_status_counts": dict(sorted(Counter(
            str(mapping.get("mapping_status")) for mapping in mappings
        ).items())),
        "readiness_counts": dict(sorted(Counter(
            str(mapping.get("readiness")) for mapping in mappings
        ).items())),
        "classification_counts": dict(sorted(Counter(
            str(mapping.get("classification")) for mapping in mappings
        ).items())),
        "tile_dimensions_distribution": dict(sorted(Counter(
            json.dumps(
                mapping.get("tile_dimensions"),
                sort_keys=True,
            )
            for mapping in permutations
            if mapping.get("tile_dimensions")
        ).items())),
        "mcu_dimensions_distribution": dict(sorted(Counter(
            json.dumps(
                {
                    "width": (report.get("geometry") or {}).get("mcu_width"),
                    "height": (report.get("geometry") or {}).get("mcu_height"),
                },
                sort_keys=True,
            )
            for report in mcu_reports
            if report.get("geometry")
        ).items())),
        "complete_bijection_count": sum(
            int(bool(mapping.get("complete_bijection")))
            for mapping in permutations
        ),
        "mcu_aligned_count": sum(
            int(bool(report.get("all_mapping_mcu_aligned")))
            for report in mcu_reports
        ),
        "single_source_permutation_count": sum(
            int(bool(mapping.get("imagebitmap", {}).get("source_id")))
            for mapping in mappings
            if mapping.get("imagebitmap")
        ),
        "multi_source_permutation_count": sum(
            int(bool(mapping.get("multiple_imagebitmap_sources")))
            for mapping in mappings
        ),
        "mapping_sha256_counts": dict(sorted(Counter(
            str(mapping.get("mapping_sha256"))
            for mapping in permutations
            if mapping.get("mapping_sha256")
        ).items())),
    }


async def _take_transform_trace(page: Page) -> dict[str, Any]:
    trace = await page.evaluate(
        "() => window.__bookwalkerTakeTransformTrace"
        " ? window.__bookwalkerTakeTransformTrace() : null"
    )
    return trace if isinstance(trace, dict) else {}


async def _visible_canvas_metrics(
    canvas: Any,
) -> dict[str, Any] | None:
    if canvas is None:
        return None
    try:
        metrics = await canvas.evaluate(
            """element => {
              const style = getComputedStyle(element);
              const rect = element.getBoundingClientRect();
              return {
                bitmap_width: element.width,
                bitmap_height: element.height,
                client_width: element.clientWidth,
                client_height: element.clientHeight,
                css_width: style.width,
                css_height: style.height,
                bounding_box: {
                  x: rect.x,
                  y: rect.y,
                  width: rect.width,
                  height: rect.height,
                },
                device_pixel_ratio: window.devicePixelRatio,
              };
            }"""
        )
    except Exception:  # noqa: BLE001 - diagnostic metadata is best effort
        return None
    return metrics if isinstance(metrics, dict) else None


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
    metadata_only: bool,
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
        # The init script also observes the product/entry page. Keep the
        # viewer trace window page-local and discard that unrelated activity.
        await _take_transform_trace(page)

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
            visible_canvas_metadata = await _visible_canvas_metrics(visible_canvas)
            visible_part_rectangles: list[dict[str, Any]] = []
            if visible_canvas is not None:
                try:
                    visible_part_rectangles = await adapter._page_draw_rectangles(
                        page,
                        visible_canvas,
                    )
                except Exception:  # noqa: BLE001 - diagnostic metadata is best effort
                    visible_part_rectangles = []
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
            part_mapping_records = build_part_mapping_records(
                trace,
                native_parts,
                tile_trace_report,
                imagebitmap_matches,
            )
            classification, matching = await classify_page(
                page,
                native_parts,
                page_candidates,
                signature_cache,
            )
            matching = _redact_matching_details(matching)
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
                    if not metadata_only:
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
                            "snapshot_sha256": hashlib.sha256(data).hexdigest(),
                            "file": None if metadata_only else image_source_name,
                        }
                    )
            part_records: list[dict[str, Any]] = []
            selected_candidate_hashes: set[str] = set()
            for part_index, native_part in enumerate(native_parts, start=1):
                part_mapping = part_mapping_records[part_index - 1]
                native_data = native_part["_data"]
                native_image = _decode_image(native_data)
                native_name = "native.png" if part_index == 1 else f"native-{part_index:02d}.png"
                if not metadata_only:
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
                imagebitmap = part_mapping.get("imagebitmap") or {}
                exact_hashes = imagebitmap.get("exact_candidate_sha256") or []
                preferred = next(
                    (
                        item
                        for item in page_candidates
                        if str(item.metadata.get("sha256")) in {str(value) for value in exact_hashes}
                    ),
                    None,
                )
                if preferred is not None and int(imagebitmap.get(
                    "exact_decoded_pixel_match_count", 0
                )) == 1:
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
                raw_record["matching_diagnostic"] = candidate_matching_diagnostic(
                    candidate_pool,
                    native_part,
                    candidate,
                    imagebitmap=imagebitmap,
                    selection_strategy=selection_strategy,
                )
                analysis: dict[str, Any] | None = None
                diff_files: dict[str, str] = {}
                marker_metadata: list[dict[str, Any]] = []
                if candidate is not None:
                    selected_candidate_hashes.add(str(candidate.metadata["sha256"]))
                    raw_data = candidate.body
                    raw_image = _decode_image(raw_data)
                    raw_name = f"raw-candidate-{part_index:02d}.jpg"
                    if not metadata_only:
                        (page_dir / raw_name).write_bytes(raw_data)
                    analysis, aligned_raw = analyze_image_pair(raw_image, native_image)
                    if not metadata_only:
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
                        "file": None if metadata_only else raw_name,
                        "jpeg_marker_metadata": marker_metadata,
                    })
                    part_mapping["raw_jpeg"] = {
                        "sha256": candidate.metadata.get("sha256"),
                        "width": candidate.metadata.get("width"),
                        "height": candidate.metadata.get("height"),
                        "decoded_pixel_exact_match": (
                            str(candidate.metadata.get("sha256")) in {
                                str(value) for value in (
                                    (part_mapping.get("imagebitmap") or {}).get(
                                        "exact_candidate_sha256", []
                                    )
                                )
                            }
                        ),
                        "mcu_geometry": jpeg_mcu_geometry(raw_data),
                    }
                selected_operation, full_source_png = _trace_source_for_part(trace, native_part)
                source_name = None
                if full_source_png:
                    source_name = "source-canvas.png" if part_index == 1 else f"source-canvas-{part_index:02d}.png"
                    if not metadata_only:
                        (page_dir / source_name).write_bytes(full_source_png)
                elif native_part.get("source_constructor") == "HTMLCanvasElement":
                    source_name = None if metadata_only else native_name
                part_mapping["source_canvas_snapshot_sha256"] = (
                    hashlib.sha256(full_source_png).hexdigest()
                    if full_source_png
                    else None
                )
                if part_mapping.get("raw_jpeg"):
                    part_mapping["mcu_alignment"] = mcu_alignment_report(
                        candidate.body if candidate is not None else b"",
                        part_mapping.get("permutation"),
                    )
                else:
                    part_mapping["mcu_alignment"] = {
                        "available": False,
                        "reason": "raw JPEG candidate unavailable",
                    }
                part_mapping["safety"] = transformation_safety_report(
                    trace,
                    part_mapping,
                )
                part_mapping["classification"] = classify_part_from_mapping(
                    analysis,
                    part_mapping,
                )
                part_mapping["readiness"] = part_readiness_classification(
                    part_mapping,
                    safety=part_mapping["safety"],
                    mcu=part_mapping["mcu_alignment"],
                )
                part_records.append({
                    "part": part_index,
                    "raw": raw_record,
                    "native": {
                        **_public_native_part(native_part),
                        "sha256": hashlib.sha256(native_data).hexdigest(),
                        "file": None if metadata_only else native_name,
                    },
                    "source_canvas": {
                        "file": source_name,
                        "snapshot_available": bool(full_source_png),
                        "selected_draw_operation": selected_operation,
                    },
                    "analysis": analysis,
                    "diff_files": diff_files,
                    "mapping_sha256": (part_mapping.get("permutation") or {}).get(
                        "mapping_sha256"
                    ),
                    "mapping_status": part_mapping.get("mapping_status"),
                    "readiness": part_mapping.get("readiness"),
                })
            operation_summary = _operation_summary(
                trace,
                visible_width=visible_width,
                visible_height=visible_height,
            )
            for part_record, part_mapping in zip(
                part_records,
                part_mapping_records,
                strict=True,
            ):
                if part_record.get("analysis") is not None:
                    part_record["analysis"]["classification"] = part_mapping.get(
                        "classification",
                        part_record["analysis"].get("classification"),
                    )
                    if part_mapping.get("classification") == "TILE_REARRANGEMENT":
                        part_record["analysis"]["classification_note"] = (
                            "This part has its own unique complete tile permutation "
                            "from the matched ImageBitmap into its source canvas."
                        )
            page_metadata = {
                "page_index": page_index,
                "page_counter": page_counter,
                "url": redact_url(page.url),
                "identity": _identity_dict(identity),
                "classification_from_existing_probe": classification,
                "existing_probe_matching": matching,
                "native_error": native_error,
                "visible_canvas": visible_canvas_metadata,
                "visible_part_count": len(visible_part_rectangles),
                "visible_part_rectangles": visible_part_rectangles,
                "metadata_only": metadata_only,
                "parts": part_records,
                "part_mappings": part_mapping_records,
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
            (page_dir / "part-mappings.json").write_text(
                json.dumps(part_mapping_records, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
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
        "part_mapping_summary": part_mapping_summary(page_records),
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
                "visible_canvas": page_record.get("visible_canvas"),
                "visible_part_count": page_record.get("visible_part_count"),
                "trace": {
                    key: page_record.get("canvas_operation_summary", {}).get(key)
                    for key in (
                        "operation_count",
                        "observed_operation_count",
                        "trace_overflow",
                        "overflow_operation_index",
                        "retained_first_operation_index",
                        "retained_last_operation_index",
                        "dropped_operation_count",
                    )
                },
                "parts": [
                    {
                        "classification": part.get("analysis", {}).get("classification"),
                        "raw_sha256": part.get("raw", {}).get("sha256"),
                        "native_sha256": part.get("native", {}).get("sha256"),
                        "mapping_sha256": part.get("mapping_sha256"),
                        "mapping_status": part.get("mapping_status"),
                        "readiness": part.get("readiness"),
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
            [_public_candidate(candidate) for candidate in _unique_candidates(collector.candidates)],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (run_dir / "part_mapping_summary.json").write_text(
        json.dumps(summary["part_mapping_summary"], ensure_ascii=False, indent=2),
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
    metadata_only: bool = False,
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
                metadata_only=metadata_only,
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
        "metadata_only": metadata_only,
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
        "--metadata-only",
        action="store_true",
        help="retain image bytes only in memory and write metadata files, not images",
    )
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
            metadata_only=args.metadata_only,
        )
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
