"""Investigate BookWalker's source-native PNG feasibility.

This diagnostic-only script connects to an externally started, disposable
Chrome instance over CDP. It copies drawImage sources synchronously at draw
time, saves both the full source and source-rectangle crop, and compares them
with the existing BookWalker canvas capture. Production capture behavior is
not changed.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import struct
from pathlib import Path
from typing import Any

from playwright.async_api import Locator, async_playwright

from screenshot_crawler.core.capture import capture_locator
from screenshot_crawler.site_adapters.bookwalker.adapter import BookWalkerAdapter

DEFAULT_URL_960 = (
    "https://viewer-trial.bookwalker.jp/03/21/viewer.html?"
    "cid=3e1a3eff-5dd5-46b5-8403-b37ed6a46166&cty=0"
)


SOURCE_NATIVE_TRACE_SCRIPT = r"""
(() => {
  if (window.__bookwalkerNativeTraceInstalled) return;
  window.__bookwalkerNativeTraceInstalled = true;
  window.__bookwalkerNativeDrawCalls = [];

  const original = CanvasRenderingContext2D.prototype.drawImage;
  let nextCanvasId = 1;
  const canvasIds = new WeakMap();

  const getCanvasId = (canvas) => {
    let id = canvasIds.get(canvas);
    if (!id) {
      id = String(nextCanvasId++);
      canvasIds.set(canvas, id);
      canvas.dataset.bookwalkerNativeTraceId = id;
    }
    return id;
  };

  const finite = (value) => Number.isFinite(value) ? Number(value) : null;

  const sourceInfo = (source) => ({
    constructor: source?.constructor?.name || null,
    width: finite(source?.width),
    height: finite(source?.height),
    naturalWidth: finite(source?.naturalWidth),
    naturalHeight: finite(source?.naturalHeight),
    videoWidth: finite(source?.videoWidth),
    videoHeight: finite(source?.videoHeight),
    currentSrc: typeof source?.currentSrc === 'string' ? source.currentSrc : null,
    src: typeof source?.src === 'string' ? source.src : null,
  });

  const geometry = (source, args) => {
    const values = args.slice(1).map(Number);
    const width = finite(source?.width);
    const height = finite(source?.height);
    if (values.length === 2 && width !== null && height !== null) {
      return {
        form: 3,
        sourceRect: {x: 0, y: 0, width, height},
        destination: {x: values[0], y: values[1], width, height},
      };
    }
    if (values.length === 4) {
      return {
        form: 5,
        sourceRect: {x: 0, y: 0, width, height},
        destination: {
          x: values[0], y: values[1], width: values[2], height: values[3],
        },
      };
    }
    if (values.length === 8) {
      return {
        form: 9,
        sourceRect: {
          x: values[0], y: values[1], width: values[2], height: values[3],
        },
        destination: {
          x: values[4], y: values[5], width: values[6], height: values[7],
        },
      };
    }
    return {form: values.length + 1, sourceRect: null, destination: null};
  };

  const pngCopy = (source, rect, fullSource) => {
    if (!source || !rect || rect.width <= 0 || rect.height <= 0) {
      return {dataUrl: null, error: 'invalid source rectangle'};
    }
    const target = document.createElement('canvas');
    const width = Math.round(fullSource ? source.width : rect.width);
    const height = Math.round(fullSource ? source.height : rect.height);
    if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
      return {dataUrl: null, error: 'invalid source dimensions'};
    }
    target.width = width;
    target.height = height;
    const context = target.getContext('2d');
    if (!context) return {dataUrl: null, error: '2d context unavailable'};
    try {
      if (fullSource) {
        original.call(context, source, 0, 0, source.width, source.height);
      } else {
        original.call(
          context,
          source,
          rect.x, rect.y, rect.width, rect.height,
          0, 0, rect.width, rect.height,
        );
      }
      return {dataUrl: target.toDataURL('image/png'), error: null};
    } catch (error) {
      return {dataUrl: null, error: String(error)};
    }
  };

  CanvasRenderingContext2D.prototype.drawImage = function(...args) {
    try {
      const canvas = this.canvas;
      const source = args[0];
      if (canvas && canvas.width > 500 && canvas.height > 500 && source) {
        const sourceDetails = sourceInfo(source);
        const geometryDetails = geometry(source, args);
        const sourceWidth = sourceDetails.width || 0;
        const sourceHeight = sourceDetails.height || 0;
        const sourceRect = geometryDetails.sourceRect;
        const fullCopy = pngCopy(source, sourceRect, true);
        const cropCopy = pngCopy(source, sourceRect, false);
        let transform = null;
        try {
          const matrix = this.getTransform();
          transform = {
            a: matrix.a, b: matrix.b, c: matrix.c,
            d: matrix.d, e: matrix.e, f: matrix.f,
          };
        } catch (error) {}
        window.__bookwalkerNativeDrawCalls.push({
          timestamp: performance.now(),
          canvasId: getCanvasId(canvas),
          canvasWidth: canvas.width,
          canvasHeight: canvas.height,
          source: sourceDetails,
          sourceRect,
          destination: geometryDetails.destination,
          argumentForm: geometryDetails.form,
          transform,
          globalCompositeOperation: this.globalCompositeOperation,
          filter: this.filter,
          fullSourcePng: fullCopy.dataUrl,
          fullSourcePngError: fullCopy.error,
          sourceCropPng: cropCopy.dataUrl,
          sourceCropPngError: cropCopy.error,
          sourceWidth,
          sourceHeight,
        });
        if (window.__bookwalkerNativeDrawCalls.length > 100) {
          window.__bookwalkerNativeDrawCalls.shift();
        }
      }
    } catch (error) {}
    return original.apply(this, args);
  };
})();
"""


def png_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    return None


def decode_data_url(data_url: str | None) -> bytes | None:
    if not isinstance(data_url, str) or not data_url.startswith("data:image/png;base64,"):
        return None
    return base64.b64decode(data_url.split(",", 1)[1])


def image_metadata(data: bytes) -> dict[str, Any]:
    dimensions = png_dimensions(data)
    return {
        "width": dimensions[0] if dimensions else None,
        "height": dimensions[1] if dimensions else None,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def compare_pngs(current: bytes, native: bytes) -> dict[str, float | int | None]:
    """Compare after resizing native to current dimensions, for diagnostics only."""

    try:
        from PIL import Image, ImageChops, ImageStat
    except ImportError:
        return {"available": 0, "mean_abs_difference": None, "rms_difference": None}

    with Image.open(io.BytesIO(current)) as current_image:
        current_rgb = current_image.convert("RGB")
    with Image.open(io.BytesIO(native)) as native_image:
        native_rgb = native_image.convert("RGB")
    resized = native_rgb.resize(current_rgb.size, Image.Resampling.LANCZOS)
    difference = ImageChops.difference(current_rgb, resized)
    stats = ImageStat.Stat(difference)
    rms = ImageStat.Stat(difference).rms
    return {
        "available": 1,
        "mean_abs_difference": round(sum(stats.mean) / len(stats.mean), 4),
        "rms_difference": round(sum(rms) / len(rms), 4),
        "current_width": current_rgb.width,
        "current_height": current_rgb.height,
        "native_width": native_rgb.width,
        "native_height": native_rgb.height,
    }


def _box_from_call(call: dict[str, Any]) -> dict[str, int] | None:
    destination = call.get("destination")
    if not isinstance(destination, dict):
        return None
    try:
        x = round(float(destination["x"]))
        y = round(float(destination["y"]))
        width = round(float(destination["width"]))
        height = round(float(destination["height"]))
    except (KeyError, TypeError, ValueError):
        return None
    if width < 100 or height < 100:
        return None
    return {"x": x, "y": y, "width": width, "height": height}


def select_final_draw_calls(
    draw_calls: list[dict[str, Any]],
    canvas_id: str | None,
) -> list[dict[str, Any]]:
    """Select last calls for the final visible rectangles, right-to-left."""

    filtered = [
        call for call in draw_calls
        if canvas_id is None or call.get("canvasId") == canvas_id
    ]
    by_box: dict[tuple[int, int, int, int], dict[str, Any]] = {}
    for call in filtered:
        box = _box_from_call(call)
        if box is None:
            continue
        key = (box["x"], box["y"], box["width"], box["height"])
        by_box[key] = call
    candidates = [(call, _box_from_call(call)) for call in by_box.values()]
    candidates = [(call, box) for call, box in candidates if box is not None]
    selected: list[tuple[dict[str, Any], dict[str, int]]] = []
    for call, box in sorted(
        candidates,
        key=lambda item: item[1]["width"] * item[1]["height"],
        reverse=True,
    ):
        contained = any(
            other["x"] <= box["x"]
            and other["y"] <= box["y"]
            and other["x"] + other["width"] >= box["x"] + box["width"]
            and other["y"] + other["height"] >= box["y"] + box["height"]
            for _, other in selected
        )
        if not contained:
            selected.append((call, box))
    selected.sort(key=lambda item: item[1]["x"], reverse=True)
    return [call for call, _ in selected]


def sanitized_call(call: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in call.items()
        if key not in {"fullSourcePng", "sourceCropPng"}
    }


async def locator_metadata(locator: Locator) -> dict[str, Any]:
    return await locator.evaluate(
        """
        element => {
          const rect = element.getBoundingClientRect();
          return {
            canvasWidth: element.width,
            canvasHeight: element.height,
            cssWidth: rect.width,
            cssHeight: rect.height,
            traceId: element.dataset.bookwalkerNativeTraceId || null,
          };
        }
        """
    )


async def save_target_pair(
    output_dir: Path,
    index: int,
    current_data: bytes,
    call: dict[str, Any] | None,
) -> dict[str, Any]:
    current_path = output_dir / f"target-{index}-current.png"
    current_path.write_bytes(current_data)
    result: dict[str, Any] = {
        "index": index,
        "current_path": str(current_path),
        "current": image_metadata(current_data),
        "source_native": None,
        "source_crop_native": None,
        "comparison": None,
    }
    if call is None:
        result["error"] = "no matching final drawImage call"
        return result

    full_data = decode_data_url(call.get("fullSourcePng"))
    crop_data = decode_data_url(call.get("sourceCropPng"))
    if full_data is not None:
        full_path = output_dir / f"target-{index}-source-native.png"
        full_path.write_bytes(full_data)
        result["source_native"] = {
            "path": str(full_path),
            **image_metadata(full_data),
        }
    if crop_data is not None:
        crop_path = output_dir / f"target-{index}-source-crop-native.png"
        crop_path.write_bytes(crop_data)
        result["source_crop_native"] = {
            "path": str(crop_path),
            **image_metadata(crop_data),
        }
        result["comparison"] = compare_pngs(current_data, crop_data)
    return result


async def measure(
    endpoint: str,
    output_dir: Path,
    url: str,
    *,
    advance_pages: int = 0,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(endpoint)
        context = browser.contexts[0]
        page = await context.new_page()
        adapter = BookWalkerAdapter()
        try:
            await adapter.prepare_page(page)
            await page.add_init_script(SOURCE_NATIVE_TRACE_SCRIPT)
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            await adapter._wait_for_render_ready(page)
            for _ in range(advance_pages):
                await page.evaluate(
                    "window.__bookwalkerNativeDrawCalls = []; "
                    "window.__diagnosticDrawCalls = []; "
                    "window.__bookwalkerDrawCalls = [];"
                )
                previous_identity = await adapter.get_content_identity(page)
                await adapter.go_next(page)
                await adapter.wait_for_change(page, previous_identity)
                await adapter._wait_for_render_ready(page)

            await page.wait_for_timeout(500)
            canvas = await adapter._visible_canvas(page)
            if canvas is None:
                raise RuntimeError("BookWalker content canvas was not visible")
            browser_info = await page.evaluate(
                """
                () => ({
                  innerWidth: window.innerWidth,
                  innerHeight: window.innerHeight,
                  outerWidth: window.outerWidth,
                  outerHeight: window.outerHeight,
                  devicePixelRatio: window.devicePixelRatio,
                  userAgent: navigator.userAgent,
                })
                """
            )
            canvas_info = await locator_metadata(canvas)
            current_canvas = await capture_locator(canvas)
            current_canvas_path = output_dir / "current-canvas.png"
            current_canvas_path.write_bytes(current_canvas.data)
            canvas_info["current_capture"] = {
                "path": str(current_canvas_path),
                **image_metadata(current_canvas.data),
            }

            trace_id = canvas_info.get("traceId")
            raw_calls = await page.evaluate(
                "() => window.__bookwalkerNativeDrawCalls || []"
            )
            selected_calls = select_final_draw_calls(raw_calls, trace_id)
            calls_path = output_dir / "draw-calls.json"
            calls_path.write_text(
                json.dumps(
                    {
                        "all_call_count": len(raw_calls),
                        "selected_call_count": len(selected_calls),
                        "selected": [sanitized_call(call) for call in selected_calls],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            targets = await adapter.get_capture_targets(page)
            target_results: list[dict[str, Any]] = []
            try:
                for index, target in enumerate(targets, start=1):
                    capture = await capture_locator(target)
                    target_results.append(
                        await save_target_pair(
                            output_dir,
                            index,
                            capture.data,
                            selected_calls[index - 1]
                            if index <= len(selected_calls)
                            else None,
                        )
                    )
            finally:
                await adapter.cleanup_capture_targets(page)

            counter = page.locator("#pageSliderCounter")
            page_counter = await counter.inner_text() if await counter.count() else None
            return {
                "url": page.url,
                "page_counter": page_counter,
                "advance_pages": advance_pages,
                "browser": browser_info,
                "canvas": canvas_info,
                "draw_calls": {
                    "all_count": len(raw_calls),
                    "selected_count": len(selected_calls),
                    "path": str(calls_path),
                    "selected": [sanitized_call(call) for call in selected_calls],
                },
                "targets": target_results,
                "production_capture_unchanged": True,
            }
        finally:
            await page.close()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--url", default=DEFAULT_URL_960)
    parser.add_argument("--advance-pages", type=int, default=0)
    args = parser.parse_args()
    result = await measure(
        args.endpoint,
        args.output_dir,
        args.url,
        advance_pages=args.advance_pages,
    )
    result["label"] = args.label
    metadata_path = args.output_dir / "metadata.json"
    metadata_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
