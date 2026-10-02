"""Bounded shared-CDP probe for Comic DAYS colophon resume behavior.

This observes the target's normal horizontal viewer controls only.  It does
not use the adapter, click episode links, or perform any access action.  The
report intentionally keeps only redacted control and counter metadata.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from screenshot_crawler.core.browser import BrowserSession, resolve_cdp_endpoint
from screenshot_crawler.site_adapters.comicdays.discovery import (
    _series_id_from_page,
    fetch_comicdays_atom,
)
from screenshot_crawler.site_adapters.comicdays.native_capture import COMICDAYS_CAPTURE_HOOK

TARGET = "https://comic-days.com/episode/2550689798754939004"
DEFAULT_OUTPUT = Path("output/comicdays_terminal_resume_probe")
EVAL_TIMEOUT = 5
STEP_TIMEOUT = 8
MAX_FORWARD = 20
MAX_BACKWARD = 20
TARGET_PATH = "/episode/2550689798754939004"


def operation_allowed(
    *,
    free_membership: bool,
    expected_path: str,
    actual_path: str,
    control_count: int,
    control: Any,
) -> bool:
    """Return whether a validated normal viewer control may be activated."""

    return bool(
        free_membership
        and actual_path == expected_path
        and control_count == 1
        and isinstance(control, dict)
        and control.get("visible") is True
        and control.get("href_is_episode") is False
        and control.get("forbidden_label") is False
    )


async def click_validated(
    page: Any,
    selector: str,
    control: dict[str, Any],
    *,
    free_membership: bool,
    expected_path: str = TARGET_PATH,
    dom_click: bool = False,
) -> bool:
    """Validate context and one control immediately before its activation."""

    locator = page.locator(selector)
    count = await locator.count()
    if not operation_allowed(
        free_membership=free_membership,
        expected_path=expected_path,
        actual_path=urlsplit(page.url).path,
        control_count=count,
        control=control,
    ):
        return False
    if not await locator.is_visible(timeout=1_000):
        return False
    if dom_click:
        await locator.evaluate("element => element.click()")
    else:
        await locator.click(timeout=2_000, no_wait_after=True)
    return True


async def evaluate(page: Any, expression: str) -> Any:
    return await asyncio.wait_for(page.evaluate(expression), timeout=EVAL_TIMEOUT)


STATE = """() => {
  const visible = e => {
    if (!e) return false;
    const s = getComputedStyle(e), r = e.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
  };
  const inViewport = e => {
    if (!e) return false;
    const r = e.getBoundingClientRect();
    return r.bottom > 0 && r.right > 0 && r.top < innerHeight && r.left < innerWidth;
  };
  const slider = document.querySelector('.js-viewer-slider-pagenum-now');
  const last = document.querySelector('.js-viewer-slider-pagenum-last');
  const root = document.querySelector('section.viewer.js-viewer');
  const areas = [...document.querySelectorAll('.page-area.js-page-area')];
  const canvases = [...document.querySelectorAll('canvas.page-image.js-page-image')];
  const backward = document.querySelector('.js-slide-backward');
  const forward = document.querySelector('.js-slide-forward');
  const control = e => ({
    visible: visible(e),
    href_is_episode: Boolean(e?.getAttribute('href')?.includes('/episode/')),
    forbidden_label: Boolean((e?.innerText || '').match(/購入|ポイント|チケット|レンタル|ログイン|会員登録|purchase|point|ticket|rental|login/i)),
  });
  const colophon = document.querySelector('#viewer-colophon');
  const capture = window.__comicDaysProductionCapture?.active?.() || null;
  const activeRows = Array.isArray(capture?.rows) ? capture.rows : [];
  return {
    path: location.pathname,
    slider_now: slider?.textContent?.trim() || null,
    slider_last: last?.textContent?.trim() || null,
    viewer_visible: visible(root),
    canvas_count: canvases.length,
    body_canvas_count: areas.filter(a => a.id !== 'viewer-colophon' && a.querySelectorAll('canvas.page-image.js-page-image').length === 1).length,
    colophon_visible: visible(colophon),
    colophon_in_viewport: inViewport(colophon),
    active_body_area_indices: activeRows.map(row => row.areaIndex).filter(Number.isInteger),
    active_body_ready: activeRows.length > 0 && activeRows.every(row => row.renderReady === true),
    backward: control(backward),
    forward: control(forward),
  };
}"""


def _int(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


async def wait_for_transition(page: Any, before: dict[str, Any]) -> dict[str, Any]:
    for _ in range(30):
        await page.wait_for_timeout(200)
        current = await evaluate(page, STATE)
        if (
            current.get("slider_now") != before.get("slider_now")
            or current.get("colophon_in_viewport") != before.get("colophon_in_viewport")
            or current.get("body_canvas_count") != before.get("body_canvas_count")
        ):
            return current
    return await evaluate(page, STATE)


async def run(output: Path, endpoint: str | None) -> None:
    output.mkdir(parents=True, exist_ok=True)
    session = await BrowserSession.connect(resolve_cdp_endpoint(cli_endpoint=endpoint))
    page = await session.new_page()
    result: dict[str, Any] = {"target": TARGET, "steps": [], "errors": []}
    try:
        await page.add_init_script(script=COMICDAYS_CAPTURE_HOOK)
        await page.goto(TARGET, wait_until="commit", timeout=30_000)
        await page.wait_for_timeout(5_000)
        if urlsplit(page.url).path != TARGET_PATH:
            result["stop_reason"] = "wrong_episode_context"
            return
        work_id = await asyncio.wait_for(_series_id_from_page(page), timeout=EVAL_TIMEOUT)
        free_entries = await asyncio.wait_for(
            fetch_comicdays_atom(page, work_id, free_only=True), timeout=EVAL_TIMEOUT * 2
        )
        result["free_membership"] = any(
            item.get("episode_id") == "2550689798754939004" for item in free_entries
        )
        result["free_entry_count"] = len(free_entries)
        if not result["free_membership"]:
            result["stop_reason"] = "target_not_in_free_feed"
            return
        state = await evaluate(page, STATE)
        result["start"] = state

        for index in range(MAX_FORWARD):
            if state.get("colophon_in_viewport"):
                break
            before = await evaluate(page, STATE)
            if before.get("path") != TARGET_PATH:
                result["stop_reason"] = "wrong_episode_context"
                break
            if not await click_validated(
                page,
                ".js-slide-forward",
                before.get("forward", {}),
                free_membership=True,
            ):
                result["stop_reason"] = "unsafe_forward_control"
                break
            state = await wait_for_transition(page, before)
            result["steps"].append({"direction": "forward", "index": index + 1, "state": state})
            if state.get("slider_now") == before.get("slider_now") and state.get("colophon_in_viewport") == before.get("colophon_in_viewport"):
                result["errors"].append("forward_did_not_progress")
                break

        terminal = await evaluate(page, STATE)
        result["terminal"] = terminal
        backward = page.locator(".js-slide-backward")
        backward_count = await backward.count()
        result["backward_control"] = {
            "count": backward_count,
            "visible": terminal.get("backward", {}).get("visible") is True,
            "href_is_episode": terminal.get("backward", {}).get("href_is_episode"),
            "forbidden_label": terminal.get("backward", {}).get("forbidden_label"),
        }
        if await click_validated(
            page,
            ".js-slide-backward",
            terminal.get("backward", {}),
            free_membership=True,
            dom_click=True,
        ):
            before_slider = _int(terminal.get("slider_now"))
            after = await wait_for_transition(page, terminal)
            result["first_backward"] = after
            after_slider = _int(after.get("slider_now"))
            result["backward_decreased"] = before_slider is not None and after_slider is not None and after_slider < before_slider

            for index in range(MAX_BACKWARD - 1):
                current = await evaluate(page, STATE)
                slider = _int(current.get("slider_now"))
                if slider is None or slider <= 1:
                    result["first_body_or_start"] = current
                    break
                if not await click_validated(
                    page,
                    ".js-slide-backward",
                    current.get("backward", {}),
                    free_membership=True,
                    dom_click=True,
                ):
                    result["stop_reason"] = "unsafe_backward_control"
                    break
                current = await wait_for_transition(page, current)
                if _int(current.get("slider_now")) == slider:
                    result["errors"].append("backward_did_not_progress")
                    break
                if index == MAX_BACKWARD - 2:
                    result["first_body_or_start"] = current
        else:
            result["stop_reason"] = "unsafe_backward_control"
    except Exception as exc:  # noqa: BLE001 - bounded probe report
        result["errors"].append({"type": type(exc).__name__, "message": str(exc)[:200]})
    finally:
        try:
            await session.close_page(page)
        finally:
            try:
                await session.close()
            finally:
                (output / "report.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cdp-endpoint")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    asyncio.run(run(args.output, args.cdp_endpoint))


if __name__ == "__main__":
    main()
