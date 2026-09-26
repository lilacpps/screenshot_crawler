#!/usr/bin/env python3
"""Read-only diagnostics for a Magapoke episode viewer initialization."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from playwright.async_api import Page, async_playwright

from screenshot_crawler.site_adapters.magapoke.adapter import MagapokeAdapter

DEFAULT_URL = "https://pocket.shonenmagazine.com/title/00030/episode/944"
DEFAULT_ENDPOINT = "http://127.0.0.1:9222"


async def snapshot(page: Page, adapter: MagapokeAdapter, label: str) -> dict[str, Any]:
    rows = await adapter._canvas_rows(page)
    controls = await page.locator(
        ".c-viewer__pager-prev, .c-viewer__pager-next"
    ).evaluate_all(
        """elements => elements.map(element => {
          const rect = element.getBoundingClientRect();
          const style = getComputedStyle(element);
          return {
            className: element.className,
            tagName: element.tagName,
            text: (element.innerText || '').trim(),
            visible: style.display !== 'none' && style.visibility !== 'hidden' &&
              rect.width > 0 && rect.height > 0,
            disabled: Boolean(element.disabled) || element.getAttribute('aria-disabled'),
            rect: {x: rect.x, y: rect.y, width: rect.width, height: rect.height},
          };
        })"""
    )
    canvases = await page.locator(".c-viewer__comic canvas").evaluate_all(
        """elements => elements.map(element => {
          const rect = element.getBoundingClientRect();
          const style = getComputedStyle(element);
          return {
            width: element.width,
            height: element.height,
            visible: style.display !== 'none' && style.visibility !== 'hidden' &&
              rect.width > 0 && rect.height > 0,
            rect: {x: rect.x, y: rect.y, width: rect.width, height: rect.height},
          };
        })"""
    )
    return {
        "label": label,
        "timestamp": datetime.now(UTC).isoformat(),
        "url": page.url,
        "title": await page.title(),
        "first_content_page_index": await adapter._first_content_page_index(page),
        "canvas_rows": rows,
        "canvas_count": len(canvases),
        "canvases": canvases,
        "controls": controls,
        "control_details": await page.locator(
            ".c-viewer__pager-prev, .c-viewer__pager-next"
        ).evaluate_all(
            """elements => elements.map(element => ({
              className: element.className,
              href: element.getAttribute('href'),
              ariaLabel: element.getAttribute('aria-label'),
              title: element.getAttribute('title'),
              rel: element.getAttribute('rel'),
              outerHTML: element.outerHTML.slice(0, 1200),
            }))"""
        ),
        "page_items": await page.locator(".c-viewer__pages-item").evaluate_all(
            """elements => elements.slice(0, 8).map((element, index) => {
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return {
                index,
                className: element.className,
                visible: style.display !== 'none' && style.visibility !== 'hidden',
                rect: {x: rect.x, y: rect.y, width: rect.width, height: rect.height},
                childCanvasCount: element.querySelectorAll('canvas').length,
                childImageCount: element.querySelectorAll('img').length,
                html: element.outerHTML.slice(0, 700),
              };
            })"""
        ),
        "interactive_elements": await page.locator(
            "a, button, [role='button'], input"
        ).evaluate_all(
            """elements => elements.map(element => {
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              return {
                tagName: element.tagName,
                className: element.className,
                text: (element.innerText || element.value || '').trim().slice(0, 80),
                href: element.getAttribute('href'),
                visible: style.display !== 'none' && style.visibility !== 'hidden' &&
                  rect.width > 0 && rect.height > 0,
                rect: {x: rect.x, y: rect.y, width: rect.width, height: rect.height},
              };
            }).filter(item => item.visible)"""
        ),
        "viewer_layout": await page.evaluate(
            """() => {
              const viewer = document.querySelector('.c-viewer');
              const pages = document.querySelector('.c-viewer__pages');
              const rect = pages?.getBoundingClientRect();
              return {
                viewerClass: viewer?.className || null,
                pagesClass: pages?.className || null,
                pagesScrollLeft: pages?.scrollLeft ?? null,
                pagesScrollWidth: pages?.scrollWidth ?? null,
                pagesClientWidth: pages?.clientWidth ?? null,
                pagesTransform: pages ? getComputedStyle(pages).transform : null,
                pagesRect: rect ? {x: rect.x, y: rect.y, width: rect.width, height: rect.height} : null,
              };
            }"""
        ),
        "viewer_count": await page.locator(".c-viewer").count(),
        "page_item_count": await page.locator(".c-viewer__pages-item").count(),
        "viewer_observation": dict(adapter._last_viewer_observation),
        "probe_error": adapter._last_canvas_probe_error,
        "capture_state_type": await page.evaluate(
            "() => typeof window.__magapokeCaptureState"
        ),
        "diagnostic_globals": await page.evaluate(
            "() => ({clicks: typeof window.__magapokeDiagnosticClicks, draws: typeof window.__magapokeDiagnosticDraws})"
        ),
        "draw_trace_tail": await page.evaluate(
            "() => (window.__magapokeDiagnosticDraws || []).slice(-12)"
        ),
    }


async def diagnose(
    endpoint: str, url: str, *, initialize_immediately: bool = False
) -> dict[str, Any]:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(endpoint)
        context = browser.contexts[0]
        page = await context.new_page()
        adapter = MagapokeAdapter()
        click_log: list[dict[str, Any]] = []
        await page.add_init_script(
            """(() => {
              window.__magapokeDiagnosticClicks = [];
              window.__magapokeDiagnosticDraws = [];
              const recordDraw = (kind, canvas, args) => {
                const source = args[0];
                window.__magapokeDiagnosticDraws.push({
                  kind,
                  sourceConstructor: source?.constructor?.name || null,
                  sourcePath: source?.currentSrc || source?.src || null,
                  sourceWidth: source?.naturalWidth || source?.width || 0,
                  sourceHeight: source?.naturalHeight || source?.height || 0,
                  canvasWidth: canvas?.width || 0,
                  canvasHeight: canvas?.height || 0,
                  args: args.slice(1).map(value => Number(value)),
                });
                if (window.__magapokeDiagnosticDraws.length > 500) {
                  window.__magapokeDiagnosticDraws.shift();
                }
              };
              const canvasProto = CanvasRenderingContext2D.prototype;
              if (canvasProto.drawImage) {
                const originalCanvasDrawImage = canvasProto.drawImage;
                canvasProto.drawImage = function(...args) {
                  try { recordDraw('canvas', this.canvas, args); } catch (_) {}
                  return originalCanvasDrawImage.apply(this, args);
                };
              }
              const offscreenProto = globalThis.OffscreenCanvasRenderingContext2D?.prototype;
              if (offscreenProto?.drawImage) {
                const originalOffscreenDrawImage = offscreenProto.drawImage;
                offscreenProto.drawImage = function(...args) {
                  try { recordDraw('offscreen', this.canvas, args); } catch (_) {}
                  return originalOffscreenDrawImage.apply(this, args);
                };
              }
              document.addEventListener('click', event => {
                const element = event.target.closest(
                  '.c-viewer__pager-prev, .c-viewer__pager-next'
                );
                if (element) {
                  window.__magapokeDiagnosticClicks.push({
                    timestamp: Date.now(),
                    className: element.className,
                    text: (element.innerText || '').trim(),
                  });
                }
              }, true);
            })()"""
        )
        await adapter.prepare_page(page)
        await adapter.configure_run(page, "direct")
        try:
            await page.goto(
                url,
                wait_until="commit" if initialize_immediately else "domcontentloaded",
                timeout=60_000,
            )
            observations = [await snapshot(page, adapter, "domcontentloaded")]
            if not initialize_immediately:
                for delay_ms in (500, 1_500, 3_000):
                    await page.wait_for_timeout(delay_ms)
                    observations.append(await snapshot(page, adapter, f"after_{delay_ms}ms"))

            initialize_error: str | None = None
            try:
                await adapter.initialize(page)
            except Exception as exc:  # noqa: BLE001 - diagnostic must preserve final state
                initialize_error = f"{type(exc).__name__}: {exc}"
            observations.append(await snapshot(page, adapter, "after_initialize"))

            capture_error: str | None = None
            captures = None
            if initialize_error is None:
                try:
                    captures = await adapter.capture_page(page)
                except Exception as exc:  # noqa: BLE001 - diagnostic result
                    capture_error = f"{type(exc).__name__}: {exc}"

            next_error: str | None = None
            previous_identity: dict[str, Any] | None = None
            try:
                identity = await adapter.get_content_identity(page)
                previous_identity = {
                    "page_id": identity.page_id,
                    "page_number": identity.page_number,
                    "source_id": identity.source_id,
                }
                await adapter.go_next(page)
                await adapter.wait_for_change(page, identity)
            except Exception as exc:  # noqa: BLE001 - diagnostic result
                next_error = f"{type(exc).__name__}: {exc}"
            observations.append(await snapshot(page, adapter, "after_next_attempt"))
            click_log = await page.evaluate(
                "() => window.__magapokeDiagnosticClicks || []"
            )
            return {
                "url": url,
                "endpoint": endpoint,
                "initial_url": adapter._initial_url,
                "observations": observations,
                "initialize_error": initialize_error,
                "capture_error": capture_error,
                "capture_count": len(captures or ()),
                "capture_formats": [
                    {
                        "mime_type": capture.mime_type,
                        "file_extension": capture.file_extension,
                        "width": capture.width,
                        "height": capture.height,
                    }
                    for capture in captures or ()
                ],
                "previous_identity": previous_identity,
                "next_error": next_error,
                "clicks": click_log,
            }
        finally:
            await page.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--initialize-immediately",
        action="store_true",
        help="Call adapter.initialize immediately after DOMContentLoaded",
    )
    args = parser.parse_args()
    result = asyncio.run(
        diagnose(
            args.endpoint,
            args.url,
            initialize_immediately=args.initialize_immediately,
        )
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
