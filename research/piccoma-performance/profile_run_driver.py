"""Run the standard CrawlerRunner in an isolated, uncredentialed CDP context."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import profile_sitecustomize  # noqa: F401 - install research-only hooks before app imports
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

from screenshot_crawler.core import runner as runner_module
from screenshot_crawler.core.errors import MaxPagesExceededError
from screenshot_crawler.core.models import RunConfig
from screenshot_crawler.core.runner import CrawlerRunner
from screenshot_crawler.site_adapters.piccoma.adapter import PiccomaAdapter


async def run(
    endpoint: str, run_dir: Path, page_limit: int, page_turn_delay_ms: int
) -> int:
    if page_turn_delay_ms < 0:
        raise ValueError("page_turn_delay_ms must be non-negative")
    run_dir.mkdir(parents=True, exist_ok=True)
    playwright = await async_playwright().start()
    browser = await playwright.chromium.connect_over_cdp(endpoint)
    context = await browser.new_context(
        viewport={"width": 1904, "height": 1200}, device_scale_factor=1
    )
    result_row: dict[str, object] = {
        "browser_context": "isolated_uncredentialed",
        "viewport": [1904, 1200],
        "device_scale_factor": 1,
        "page_limit": page_limit,
        "page_turn_delay_ms": page_turn_delay_ms,
        "saved_pages": 0,
        "terminal": "not_verified",
    }
    async def discard_diagnostics(*_args: object, **_kwargs: object) -> None:
        return None

    # Viewer HTML/screenshots add no profiling evidence; keep only scalar output.
    runner_module.write_diagnostics = discard_diagnostics
    try:
        page = await context.new_page()
        config = RunConfig(
            site="piccoma",
            source_url="https://piccoma.com/web/viewer/28600/1910027",
            output_dir=run_dir / "crawl",
            diagnostics_dir=run_dir / "diagnostics",
            max_pages=page_limit,
            max_same_content=3,
            page_turn_delay_ms=page_turn_delay_ms,
            stop_on_http_403=True,
            stop_on_http_429=True,
            stop_on_challenge=True,
            stop_on_captcha=True,
            access_strategy="direct",
        )
        try:
            result = await CrawlerRunner(config).run(page, PiccomaAdapter())
            result_row.update({
                "saved_pages": len(result.pages),
                "terminal": result.stop_reason,
                "stop_state": result.stop_state.value,
            })
        except MaxPagesExceededError as exc:
            result_row.update({
                "terminal": "max_pages_exceeded_bounded_probe_not_end",
                "error_type": type(exc).__name__,
            })
        except Exception as exc:  # noqa: BLE001 - sanitized probe outcome is evidence
            result_row.update({
                "error_type": type(exc).__name__,
            })
            try:
                result_row["observed_geometry"] = await page.evaluate("""() => {
                  const canvas = document.querySelector(
                    '#react_PageListApp .PCM-viewer2_pageWrapper.current canvas'
                  );
                  const frame = document.querySelector('#js_frame.PCM-viewer2_frame');
                  const rect = node => {
                    const r = node?.getBoundingClientRect();
                    return r ? [r.x, r.y, r.width, r.height] : null;
                  };
                  const id = document.querySelector(
                    '#react_PageListApp .PCM-viewer2_pageWrapper.current'
                  )?.id || '';
                  return { inner: [innerWidth, innerHeight], dpr: devicePixelRatio,
                    screen: [screen.width, screen.height], activePage: id,
                    canvasPixels: canvas ? [canvas.width, canvas.height] : null,
                    canvasRect: rect(canvas), frameRect: rect(frame) };
                }""")
            except PlaywrightError:
                result_row["observed_geometry"] = "unavailable"
        finally:
            await context.close()
    finally:
        await playwright.stop()
    manifest_path = run_dir / "crawl" / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        pages = manifest.get("pages", [])
        methods = [
            page.get("metadata", {}).get("piccoma_capture", {})
            for page in pages if isinstance(page, dict)
        ]
        result_row.update({
            "saved_pages": len(pages),
            "sequences": [page.get("sequence") for page in pages],
            "page_numbers": [page.get("page_number") for page in pages],
            "webp_files": sum(page.get("file_extension") == ".webp" for page in pages),
            "native_webp_pages": sum(
                item.get("method") == "native_tile_replay_lossless_webp"
                and item.get("source_native") is True
                and item.get("output_format") == "image/webp"
                and item.get("output_lossless") is True
                for item in methods
            ),
            "fallback_pages": sum(
                item.get("source_native") is not True for item in methods
            ),
        })
    else:
        result_row["saved_pages"] = 0
    (run_dir / "run_result.json").write_text(
        json.dumps(result_row, indent=2), encoding="utf-8"
    )
    return 0 if (
        result_row["saved_pages"] == page_limit
        and result_row.get("native_webp_pages") == page_limit
    ) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(
        run(sys.argv[1], Path(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]))
    ))
