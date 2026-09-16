"""Best-effort diagnostics writer for UNKNOWN and unexpected failures."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from playwright.async_api import Page

from screenshot_crawler.core.progress import atomic_write_json


async def write_diagnostics(
    page: Page,
    directory: str | Path,
    *,
    metadata: dict[str, Any] | None = None,
    error: BaseException | None = None,
) -> Path:
    """Write diagnostics without masking the original crawler exception."""

    output_dir = Path(directory)
    output_dir.mkdir(parents=True, exist_ok=True)
    details: dict[str, Any] = {"url": page.url, **(metadata or {})}
    try:
        details["title"] = await asyncio.wait_for(page.title(), timeout=5)
    except BaseException as exc:  # noqa: BLE001
        details["title_error"] = str(exc)
    try:
        details["viewport"] = await asyncio.wait_for(
            page.evaluate("({width: innerWidth, height: innerHeight})"), timeout=5
        )
    except BaseException as exc:  # noqa: BLE001
        details["viewport_error"] = str(exc)
    if error is not None:
        details["error_type"] = type(error).__name__

    try:
            await asyncio.wait_for(
                page.screenshot(path=str(output_dir / "screenshot.png"), full_page=False),
                timeout=5,
            )
    except BaseException as exc:  # noqa: BLE001  # diagnostics must not mask original
        details["screenshot_error"] = str(exc)
    try:
        html = await asyncio.wait_for(page.content(), timeout=5)
        (output_dir / "page.html").write_text(html, encoding="utf-8")
    except BaseException as exc:  # noqa: BLE001
        details["html_error"] = str(exc)
    try:
        atomic_write_json(output_dir / "metadata.json", details)
    except BaseException as exc:  # noqa: BLE001
        details["metadata_error"] = str(exc)
    if error is not None:
        try:
            (output_dir / "error.txt").write_text(str(error), encoding="utf-8")
        except BaseException:  # noqa: BLE001, S110
            pass
    return output_dir
