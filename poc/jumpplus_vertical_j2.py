"""Live validation for Jump+ viewer-mode detection and production capture flow.

This probe uses the shared crawler Chrome over CDP, performs one fresh load per
URL, and calls the production adapter directly.  It never scrolls or invokes
viewer navigation for either target.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

try:
    from screenshot_crawler.core.browser import BrowserSession, resolve_cdp_endpoint
    from screenshot_crawler.site_adapters.jumpplus.adapter import JumpPlusAdapter
except ModuleNotFoundError:  # direct ``python poc/jumpplus_vertical_j2.py`` invocation
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from screenshot_crawler.core.browser import BrowserSession, resolve_cdp_endpoint
    from screenshot_crawler.site_adapters.jumpplus.adapter import JumpPlusAdapter


VERTICAL_URL = "https://shonenjumpplus.com/episode/10834108156642491399"
PAGED_URL = "https://shonenjumpplus.com/episode/13932016480029111789"


async def run_one(session: BrowserSession, url: str, output_dir: Path) -> dict[str, Any]:
    page = await session.new_page()
    adapter = JumpPlusAdapter()
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        await adapter.prepare_page(page)
        await page.goto(url, wait_until="commit", timeout=30_000)
        await adapter.initialize(page)
        initial_state = (await adapter.detect_state(page)).value
        rows = await adapter._capture_rows(page)
        captures = await adapter.capture_page(page)
        after_capture_state = (await adapter.detect_state(page)).value
        capture_files: list[str] = []
        if captures is not None:
            for index, capture in enumerate(captures, start=1):
                path = output_dir / f"page-{index:04d}{capture.file_extension}"
                path.write_bytes(capture.data)
                capture_files.append(str(path.relative_to(output_dir)))
        return {
            "url": url,
            "viewer_mode": adapter._viewer_mode,
            "initial_state": initial_state,
            "after_capture_state": after_capture_state,
            "row_count": len(rows),
            "row_page_indices": [row.get("pageIndex") for row in rows],
            "capture_count": len(captures or ()),
            "capture_methods": sorted({capture.mime_type for capture in captures or ()}),
            "capture_files": capture_files,
            "scroll_performed": False,
            "navigation_performed": False,
            "debug": await adapter.collect_debug_metadata(page),
        }
    finally:
        await session.close_page(page)


async def run_probe(output_dir: Path, cdp_endpoint: str | None) -> dict[str, Any]:
    session = await BrowserSession.connect(resolve_cdp_endpoint(cli_endpoint=cdp_endpoint))
    try:
        vertical = await run_one(session, VERTICAL_URL, output_dir / "vertical")
        paged = await run_one(session, PAGED_URL, output_dir / "paged")
        return {"vertical": vertical, "paged": paged}
    finally:
        await session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Jump+ Vertical J2 production integration")
    parser.add_argument("--output-dir", type=Path, default=Path("output/jumpplus_vertical_j2"))
    parser.add_argument("--cdp-endpoint")
    args = parser.parse_args()
    report = asyncio.run(run_probe(args.output_dir, args.cdp_endpoint))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
