"""Measure BookWalker's canvas and source image resolution under two Chrome sizes.

This is a diagnostic-only script. It connects to externally started Chrome
instances over CDP and does not change crawler production configuration.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import struct
from pathlib import Path
from typing import Any

from playwright.async_api import Response, async_playwright

from screenshot_crawler.core.capture import capture_locator
from screenshot_crawler.site_adapters.bookwalker.adapter import BookWalkerAdapter

DEFAULT_URL = (
    "https://viewer-trial.bookwalker.jp/03/21/viewer.html?"
    "cid=3e1a3eff-5dd5-46b5-8403-b37ed6a46166&cty=0"
)

SOURCE_TRACE_SCRIPT = """
(() => {
  if (window.__diagnosticDrawTraceInstalled) return;
  window.__diagnosticDrawTraceInstalled = true;
  window.__diagnosticDrawCalls = [];
  const original = CanvasRenderingContext2D.prototype.drawImage;
  CanvasRenderingContext2D.prototype.drawImage = function(...args) {
    try {
      const source = args[0];
      const canvas = this.canvas;
      if (canvas && canvas.width > 500 && canvas.height > 500) {
        const sourceInfo = {
          constructor: source?.constructor?.name || null,
          src: typeof source?.currentSrc === 'string'
            ? source.currentSrc
            : (typeof source?.src === 'string' ? source.src : null),
          naturalWidth: Number.isFinite(source?.naturalWidth)
            ? source.naturalWidth : null,
          naturalHeight: Number.isFinite(source?.naturalHeight)
            ? source.naturalHeight : null,
          sourceWidth: Number.isFinite(source?.width) ? source.width : null,
          sourceHeight: Number.isFinite(source?.height) ? source.height : null,
        };
        const numbers = args.slice(1).map(value => Number(value));
        const destination = numbers.length >= 8
          ? numbers.slice(4, 8)
          : (numbers.length === 4 ? numbers.slice(0, 4) : null);
        window.__diagnosticDrawCalls.push({
          canvasWidth: canvas.width,
          canvasHeight: canvas.height,
          destination,
          source: sourceInfo,
        });
        if (window.__diagnosticDrawCalls.length > 2000) {
          window.__diagnosticDrawCalls.shift();
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


def jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    if not data.startswith(b"\xff\xd8"):
        return None
    offset = 2
    while offset + 9 <= len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        marker = data[offset + 1]
        offset += 2
        if marker in {0xD8, 0xD9}:
            continue
        if offset + 2 > len(data):
            return None
        length = int.from_bytes(data[offset:offset + 2], "big")
        if length < 2 or offset + length > len(data):
            return None
        if marker in set(range(0xC0, 0xC4)) | set(range(0xC5, 0xC8)) | set(
            range(0xC9, 0xCC)
        ) | set(range(0xCD, 0xD0)):
            return (
                int.from_bytes(data[offset + 5:offset + 7], "big"),
                int.from_bytes(data[offset + 3:offset + 5], "big"),
            )
        offset += length
    return None


def image_dimensions(data: bytes) -> tuple[int, int] | None:
    return png_dimensions(data) or jpeg_dimensions(data)


async def response_record(response: Response) -> dict[str, Any] | None:
    if response.request.resource_type != "image":
        return None
    try:
        body = await response.body()
    except Exception as exc:  # noqa: BLE001
        return {"url": response.url, "body_error": str(exc)}
    return {
        "url": response.url,
        "status": response.status,
        "content_type": response.headers.get("content-type"),
        "content_length_header": response.headers.get("content-length"),
        "body_bytes": len(body),
        "pixel_dimensions": image_dimensions(body),
    }


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
        image_tasks: list[asyncio.Task[dict[str, Any] | None]] = []

        def on_response(response: Response) -> None:
            image_tasks.append(asyncio.create_task(response_record(response)))

        page.on("response", on_response)
        adapter = BookWalkerAdapter()
        await adapter.prepare_page(page)
        await page.add_init_script(SOURCE_TRACE_SCRIPT)
        await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        await adapter._wait_for_render_ready(page)
        for _ in range(advance_pages):
            await page.evaluate(
                "window.__diagnosticDrawCalls = []; window.__bookwalkerDrawCalls = []"
            )
            previous_identity = await adapter.get_content_identity(page)
            await adapter.go_next(page)
            await adapter.wait_for_change(page, previous_identity)
            await adapter._wait_for_render_ready(page)
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
              screenWidth: screen.width,
              screenHeight: screen.height,
              screenAvailWidth: screen.availWidth,
              screenAvailHeight: screen.availHeight,
            })
            """
        )
        canvas_info = await canvas.evaluate(
            """
            element => {
              const rect = element.getBoundingClientRect();
              return {
                canvasWidth: element.width,
                canvasHeight: element.height,
                cssWidth: rect.width,
                cssHeight: rect.height,
              };
            }
            """
        )
        capture = await capture_locator(canvas)
        png_path = output_dir / "canvas.png"
        png_path.write_bytes(capture.data)
        canvas_info.update(
            {
                "pngWidth": capture.width,
                "pngHeight": capture.height,
                "pngBytes": len(capture.data),
                "pngSha256": hashlib.sha256(capture.data).hexdigest(),
                "pngPath": str(png_path),
            }
        )
        draw_calls = await page.evaluate(
            "() => window.__diagnosticDrawCalls || []"
        )
        page_captures: list[dict[str, Any]] = []
        capture_targets = await adapter.get_capture_targets(page)
        try:
            for index, target in enumerate(capture_targets, start=1):
                page_capture = await capture_locator(target)
                page_path = output_dir / f"page-{index}.png"
                page_path.write_bytes(page_capture.data)
                page_captures.append(
                    {
                        "index": index,
                        "width": page_capture.width,
                        "height": page_capture.height,
                        "bytes": len(page_capture.data),
                        "sha256": hashlib.sha256(page_capture.data).hexdigest(),
                        "path": str(page_path),
                    }
                )
        finally:
            await adapter.cleanup_capture_targets(page)
        counter = page.locator("#pageSliderCounter")
        page_counter = await counter.inner_text() if await counter.count() else None
        await page.wait_for_timeout(500)
        network_images = [record for task in image_tasks if (record := await task)]
        return {
            "url": page.url,
            "page_counter": page_counter,
            "title": await page.title(),
            "browser": await page.evaluate("() => navigator.userAgent"),
            "browser_info": browser_info,
            "canvas": canvas_info,
            "capture_targets": page_captures,
            "draw_calls": draw_calls,
            "network_images": network_images,
        }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--url", default=DEFAULT_URL)
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
    metadata_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
