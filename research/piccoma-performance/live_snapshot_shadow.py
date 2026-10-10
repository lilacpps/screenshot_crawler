"""Bounded live reader/native-snapshot full-vs-compact comparison.

The standard Runner/free-only preflight is attempted first with the normal
capture guards and a fail-closed native-only research gate. If the existing
strict geometry guard stops it before capture, this probe performs read-only
snapshot evaluations on that same owned page. It never reads response bodies,
replays tiles, changes navigation, or saves captures.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import statistics
import time
from pathlib import Path
from typing import Any

if not os.environ.get("PERF_TRACE_FILE"):
    raise RuntimeError("PERF_TRACE_FILE is required for the fail-closed research gate")

import profile_sitecustomize  # noqa: F401 - installs fail-closed native-only gate
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

from screenshot_crawler.core import runner as runner_module
from screenshot_crawler.core.errors import (
    CrawlerError,
    MaxPagesExceededError,
    UnknownPageStateError,
)
from screenshot_crawler.core.models import RunConfig
from screenshot_crawler.core.runner import CrawlerRunner
from screenshot_crawler.site_adapters.piccoma.adapter import (
    PiccomaAdapter,
    parse_piccoma_viewer_url,
)
from screenshot_crawler.site_adapters.piccoma.native_capture import (
    NativeCaptureUnavailable,
    _source_signature,
    _target_signature,
    retire_native_trace,
    validate_tile_trace,
    validate_white_paint_path,
)


def _finite_summary(value: dict[str, Any]) -> dict[str, Any]:
    pages = value.get("pages")
    page_rows = pages if isinstance(pages, list) else []
    active_rows = [
        row for row in page_rows
        if isinstance(row, dict) and "current" in row.get("classes", [])
    ]
    active = active_rows[0] if len(active_rows) == 1 else {}
    canvas = active.get("canvas") if isinstance(active.get("canvas"), dict) else {}
    renderability = canvas.get("renderability", {})
    active_id = active.get("id", "")
    number = int(active_id[1:]) if isinstance(active_id, str) and active_id.startswith("p") and active_id[1:].isdigit() else 0
    return {
        "root_count": value.get("rootCount"),
        "page_list_count": value.get("pageListCount"),
        "frame_count": value.get("frameCount"),
        "page_count": len(page_rows),
        "active_page_number": number,
        "active_is_last": active_id == "last",
        "active_canvas_count": active.get("canvasCount"),
        "active_loaded_count": active.get("loadedCount"),
        "canvas_loaded": canvas.get("loaded"),
        "canvas_pixels": [canvas.get("width"), canvas.get("height")],
        "canvas_rect": canvas.get("rect"),
        "canvas_ancestor_count": len(renderability.get("ancestors", [])),
        "canvas_visible": renderability.get("visible"),
        "viewport": value.get("viewport"),
        "frame_rect": value.get("frameRect"),
        "dialog_count": value.get("dialogCount"),
        "guide_count": value.get("guideCount"),
        "next_count": value.get("nextCount"),
        "next_disabled": value.get("nextDisabled"),
        "next_visible": value.get("nextVisible"),
    }


def _reader_script(source: str, *, compact: bool) -> str:
    text = source.strip()
    prefix = "() => {"
    if not text.startswith(prefix) or not text.endswith("}"):
        raise ValueError("Reader snapshot source shape changed")
    body = text[len(prefix):-1]
    index = body.rfind("return {")
    if index < 0:
        raise ValueError("Reader snapshot result object not found")
    declarations = body[:index]
    result = body[index + len("return "):].strip()
    compact_projection = r"""value => {
      const pages = Array.isArray(value.pages) ? value.pages : [];
      const activeRows = pages.filter(row => Array.isArray(row.classes) && row.classes.includes('current'));
      const active = activeRows.length === 1 ? activeRows[0] : {};
      const canvas = active.canvas && typeof active.canvas === 'object' ? active.canvas : {};
      const renderability = canvas.renderability || {};
      const id = typeof active.id === 'string' ? active.id : '';
      const match = /^p([0-9]+)$/.exec(id);
      return {
        root_count: value.rootCount, page_list_count: value.pageListCount,
        frame_count: value.frameCount, page_count: pages.length,
        active_page_number: match ? Number(match[1]) : 0,
        active_is_last: id === 'last', active_canvas_count: active.canvasCount,
        active_loaded_count: active.loadedCount, canvas_loaded: canvas.loaded,
        canvas_pixels: [canvas.width ?? null, canvas.height ?? null],
        canvas_rect: canvas.rect ?? null,
        canvas_ancestor_count: Array.isArray(renderability.ancestors) ? renderability.ancestors.length : 0,
        canvas_visible: renderability.visible ?? null, viewport: value.viewport,
        frame_rect: value.frameRect, dialog_count: value.dialogCount,
        guide_count: value.guideCount, next_count: value.nextCount,
        next_disabled: value.nextDisabled, next_visible: value.nextVisible
      };
    }"""
    if compact:
        ending = f"""const __value = {result}
      const __snapshot_ms = performance.now() - __started;
      const __summary_started = performance.now();
      const __summary = ({compact_projection})(__value);
      const __summary_ms = performance.now() - __summary_started;
      const __full_bytes = new TextEncoder().encode(JSON.stringify(__value)).length;
      const __compact_bytes = new TextEncoder().encode(JSON.stringify(__summary)).length;
      return {{summary: __summary, browser_exec_ms: __snapshot_ms, summary_exec_ms: __summary_ms,
        full_json_bytes: __full_bytes, compact_json_bytes: __compact_bytes}};"""
    else:
        ending = f"""const __value = {result}
      const __snapshot_ms = performance.now() - __started;
      const __summary_started = performance.now();
      const __summary = ({compact_projection})(__value);
      const __summary_ms = performance.now() - __summary_started;
      const __full_bytes = new TextEncoder().encode(JSON.stringify(__value)).length;
      const __compact_bytes = new TextEncoder().encode(JSON.stringify(__summary)).length;
      return {{payload: __value, browser_exec_ms: __snapshot_ms, summary_exec_ms: __summary_ms,
        full_json_bytes: __full_bytes, compact_json_bytes: __compact_bytes}};"""
    return f"""() => {{
      const __started = performance.now();
      {declarations}
      {ending}
    }}"""


def _json_bytes(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _trace_summary(trace: dict[str, Any]) -> dict[str, Any]:
    events = trace.get("events") if isinstance(trace.get("events"), list) else []
    draws = [event for event in events if isinstance(event, dict) and event.get("type") == "drawImage"]
    states = trace.get("sourceStates") if isinstance(trace.get("sourceStates"), list) else []
    state = states[0] if len(states) == 1 and isinstance(states[0], dict) else {}
    paint = trace.get("paint") if isinstance(trace.get("paint"), dict) else {}
    return {
        "target_id_present": isinstance(trace.get("id"), str) and bool(trace.get("id")),
        "dimensions": trace.get("dimensions"),
        "initial_dimensions": trace.get("initialDimensions"),
        "connected": trace.get("connected"),
        "generation": trace.get("generation"),
        "retired": trace.get("retired"),
        "overflow": trace.get("overflow"),
        "total_overflow": trace.get("totalOverflow"),
        "event_count": len(events),
        "draw_count": len(draws),
        "source_count": len(states),
        "source_complete": state.get("complete"),
        "source_dimensions": [state.get("naturalWidth"), state.get("naturalHeight")],
        "source_generation": [
            state.get("assignmentGeneration"), state.get("loadGeneration"),
            state.get("lastLoadedAssignmentGeneration"),
        ],
        "paint_ancestor_count": len(paint.get("ancestors", [])),
        "paint_overlap_count": len(paint.get("overlappingDescendants", [])),
        "paint_first_opaque_index": paint.get("firstOpaqueIndex"),
        "paint_covers_canvas": paint.get("firstOpaqueCoversCanvas"),
        "paint_canvas_rect": paint.get("canvasRect"),
        "hooks_intact": trace.get("hooksIntact"),
        "attribute_observer_ready": trace.get("attributeObserverReady"),
    }


def _browser_trace_script(*, compact: bool, json_string: bool = False) -> str:
    script = r"""node => {
      const start = performance.now();
      const value = window.__piccomaNativeCapture?.snapshot(node) ?? null;
      const snapshotMs = performance.now() - start;
      const paintTimes = window.__piccomaPerf?.paint?.splice(0) ?? [];
      if (!value || typeof value !== 'object') return {present: false, browser_exec_ms: snapshotMs};
      const events = Array.isArray(value.events) ? value.events : [];
      const draws = events.filter(event => event && event.type === 'drawImage').length;
      const states = Array.isArray(value.sourceStates) ? value.sourceStates : [];
      const state = states.length === 1 ? states[0] : {};
      const paint = value.paint && typeof value.paint === 'object' ? value.paint : {};
      const summary = {
        target_id_present: typeof value.id === 'string' && value.id.length > 0,
        dimensions: value.dimensions,
        initial_dimensions: value.initialDimensions, connected: value.connected,
        generation: value.generation, retired: value.retired,
        overflow: value.overflow, total_overflow: value.totalOverflow,
        event_count: events.length, draw_count: draws, source_count: states.length,
        source_complete: state.complete,
        source_dimensions: [state.naturalWidth ?? null, state.naturalHeight ?? null],
        source_generation: [state.assignmentGeneration ?? null, state.loadGeneration ?? null,
          state.lastLoadedAssignmentGeneration ?? null],
        paint_ancestor_count: Array.isArray(paint.ancestors) ? paint.ancestors.length : 0,
        paint_overlap_count: Array.isArray(paint.overlappingDescendants) ? paint.overlappingDescendants.length : 0,
        paint_first_opaque_index: paint.firstOpaqueIndex ?? null,
        paint_covers_canvas: paint.firstOpaqueCoversCanvas ?? null,
        paint_canvas_rect: paint.canvasRect ?? null,
        hooks_intact: value.hooksIntact, attribute_observer_ready: value.attributeObserverReady,
      };
      const fullJsonBytes = new TextEncoder().encode(JSON.stringify(value)).length;
      const compactJsonBytes = new TextEncoder().encode(JSON.stringify(summary)).length;
      const metrics = {browser_exec_ms: snapshotMs,
        summary_exec_ms: performance.now() - start - snapshotMs,
        paint_ms: paintTimes.reduce((sum, item) => sum + Number(item || 0), 0),
        paint_count: paintTimes.length,
        full_json_bytes: fullJsonBytes, compact_json_bytes: compactJsonBytes};
      if (__JSON_STRING__) return {payload_json: JSON.stringify(value), summary, ...metrics};
      return __COMPACT__ ? {summary, ...metrics} : {payload: value, summary, ...metrics};
    }"""
    return script.replace("__COMPACT__", "true" if compact else "false").replace(
        "__JSON_STRING__", "true" if json_string else "false"
    )


def _stats(values: list[float], *, unit: str) -> dict[str, float | int]:
    if not values:
        return {"n": 0}
    ordered = sorted(values)
    return {
        "n": len(ordered),
        f"mean_{unit}": statistics.mean(ordered),
        f"median_{unit}": statistics.median(ordered),
        f"p90_{unit}": ordered[math.ceil(0.9 * len(ordered)) - 1],
        f"max_{unit}": max(ordered),
    }


async def _probe(endpoint: str, run_root: Path, report_path: Path, pairs: int) -> dict[str, Any]:
    if report_path.exists() or run_root.exists():
        raise FileExistsError("Refusing to overwrite probe artifacts")
    run_root.mkdir(parents=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    run_dir = run_root / "runner"
    run_dir.mkdir()

    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(endpoint)
        context = await browser.new_context(
            viewport={"width": 1904, "height": 1200}, device_scale_factor=1
        )
        page = await context.new_page()
        adapter = PiccomaAdapter()
        viewer_responses: list[dict[str, Any]] = []
        observed = {"response_body_calls": 0, "tile_replay_calls": 0}

        from playwright.async_api import Response

        original_response_body = Response.body

        async def count_response_body(response: Any) -> bytes:
            observed["response_body_calls"] += 1
            return await original_response_body(response)

        Response.body = count_response_body
        from screenshot_crawler.site_adapters.piccoma import adapter as adapter_module

        original_tile_replay = adapter_module.capture_native_tile_replay

        async def count_tile_replay(*args: Any, **kwargs: Any) -> Any:
            observed["tile_replay_calls"] += 1
            return await original_tile_replay(*args, **kwargs)

        adapter_module.capture_native_tile_replay = count_tile_replay

        def observe_viewer_response(response: Any) -> None:
            from screenshot_crawler.site_adapters.piccoma.adapter import parse_piccoma_viewer_url

            if parse_piccoma_viewer_url(response.url) is not None:
                identity = parse_piccoma_viewer_url(response.url)
                if identity and identity.external_id == "28600:1910027":
                    viewer_responses.append({
                        "status": response.status,
                        "resource_type_document": response.request.resource_type == "document",
                        "content_type_html": response.headers.get("content-type", "").split(";", 1)[0].lower() == "text/html",
                    })

        page.on("response", observe_viewer_response)
        async def discard_raw_diagnostics(*_args: Any, **_kwargs: Any) -> None:
            return None

        # Runner's ordinary exception diagnostics can include HTML/screenshots.
        # This probe keeps only our scalar redacted observations.
        runner_module.write_diagnostics = discard_raw_diagnostics
        config = RunConfig(
            site="piccoma",
            source_url="https://piccoma.com/web/viewer/28600/1910027",
            output_dir=run_dir / "crawl",
            diagnostics_dir=run_dir / "diagnostics",
            max_pages=1,
            max_same_content=3,
            page_turn_delay_ms=1000,
            stop_on_http_403=True,
            stop_on_http_429=True,
            stop_on_challenge=True,
            stop_on_captcha=True,
            access_strategy="direct",
        )
        runner_error = "none"
        runner_return: Any = None
        try:
            try:
                runner_return = await CrawlerRunner(config).run(page, adapter)
            except MaxPagesExceededError:
                runner_error = "max_pages_exceeded_bounded_probe"
            except CrawlerError as exc:
                runner_error = type(exc).__name__
            except PlaywrightError as exc:
                runner_error = type(exc).__name__

            initial: dict[str, Any] | None = None
            repeat_allowed = False
            try:
                initial = await adapter._reader_snapshot(page)
                row = adapter._page_row(initial, "p1")
                try:
                    adapter._validate_canvas_geometry(initial, row)
                except UnknownPageStateError:
                    viewport = initial.get("viewport")
                    canvas = row.get("canvas", {})
                    rect = canvas.get("rect", [])
                    frame_rect = initial.get("frameRect", [])
                    dimensions_ok = (
                        canvas.get("width") == 844 and canvas.get("height") == 1200
                        and len(rect) == 4 and abs(rect[2] - 844) <= 0.5
                        and abs(rect[3] - 1200) <= 0.5 and canvas.get("inFrame") is True
                        and len(frame_rect) == 4 and abs(frame_rect[2] - 844) <= 0.5
                        and abs(frame_rect[3] - 1200) <= 0.5
                        and float(rect[0]) >= 0 and float(rect[1]) >= 0
                        and float(rect[0]) + float(rect[2]) <= 1904.5
                        and float(rect[1]) + float(rect[3]) <= 1200.5
                        and adapter._canvas_renderability_is_valid(row)
                    )
                    repeat_allowed = (
                        runner_error == "UnknownPageStateError"
                        and initial.get("activeIds") == ["p1"]
                        and viewport == [1904, 1200, 1.0000000298023224]
                        and dimensions_ok
                        and adapter._title is not None
                        and adapter._page_count is not None and adapter._page_count > 0
                        and getattr(adapter._source_identity, "external_id", None) == "28600:1910027"
                        and any(item["status"] == 200 for item in viewer_responses)
                    )
                else:
                    repeat_allowed = False
            except (UnknownPageStateError, PlaywrightError):
                initial = None

            result: dict[str, Any] = {
                "browser_version": browser.version,
                "runner_error_type": runner_error,
                "fresh_free_preflight_completed": bool(
                    adapter._title is not None and adapter._page_count is not None
                    and getattr(adapter._source_identity, "external_id", None) == "28600:1910027"
                    and any(item["status"] == 200 for item in viewer_responses)
                ),
                "viewer_response_metadata": viewer_responses,
                "raw_runner_diagnostics_disabled": True,
                "page_saved_by_probe": bool(runner_return and runner_return.pages),
                "runner_saved_page_count": len(runner_return.pages) if runner_return else 0,
                "source_body_read": observed["response_body_calls"] > 0,
                "source_body_call_count": observed["response_body_calls"],
                "tile_replay_called": observed["tile_replay_calls"] > 0,
                "tile_replay_call_count": observed["tile_replay_calls"],
                "capture_method": "not_successful_or_not_requested",
                "repeat_probe_allowed_by_observed_guard": repeat_allowed,
                "ab_pairs_requested": pairs if repeat_allowed else 0,
                "reader": {},
                "trace": {},
            }
            if not repeat_allowed or initial is None:
                return result

            before_summary = _finite_summary(initial)
            canvas_locator = page.locator(
                "#react_PageListApp .PCM-viewer2_pageWrapper.current#p1 canvas"
            )
            if await canvas_locator.count() != 1:
                result["repeat_probe_allowed_by_observed_guard"] = False
                result["skip_reason"] = "unique_active_canvas_not_found"
                return result

            reader_full_js = _reader_script(adapter._reader_snapshot_js, compact=False)
            reader_compact_js = _reader_script(adapter._reader_snapshot_js, compact=True)
            reader_rows: list[dict[str, Any]] = []
            reader_full_payloads: list[dict[str, Any]] = []
            reader_compact_payloads: list[dict[str, Any]] = []
            reader_warmup = []
            for label, script, is_full in (
                ("full", reader_full_js, True), ("compact", reader_compact_js, False)
            ):
                wall_start, cpu_start = time.perf_counter(), time.process_time()
                response = await page.evaluate(script)
                wall, cpu = time.perf_counter() - wall_start, time.process_time() - cpu_start
                warm_summary = (
                    _finite_summary(response.get("payload", {}))
                    if is_full else response.get("summary", {})
                )
                reader_warmup.append({
                    "variant": label, "wall_s": wall, "cpu_s": cpu,
                    "browser_exec_ms": float(response.get("browser_exec_ms", 0.0)),
                    "summary_exec_ms": float(response.get("summary_exec_ms", 0.0)),
                    "projection_matches": warm_summary == before_summary,
                })
                await asyncio.sleep(0.1)
            for pair in range(pairs):
                pair_before = _finite_summary(await adapter._reader_snapshot(page))
                for label, script, is_full in (
                    ("full", reader_full_js, True),
                    ("compact", reader_compact_js, False),
                ):
                    wall_start, cpu_start = time.perf_counter(), time.process_time()
                    response = await page.evaluate(script)
                    wall, cpu = time.perf_counter() - wall_start, time.process_time() - cpu_start
                    if is_full:
                        payload = response.get("payload", {})
                        payload_summary = _finite_summary(payload)
                        reader_full_payloads.append(payload_summary)
                        size_bytes = int(response.get("full_json_bytes", 0))
                    else:
                        payload_summary = response.get("summary", {})
                        reader_compact_payloads.append(payload_summary)
                        size_bytes = int(response.get("compact_json_bytes", 0))
                    reader_rows.append({
                        "pair": pair + 1, "variant": label,
                        "wall_s": wall, "cpu_s": cpu,
                        "browser_exec_ms": float(response.get("browser_exec_ms", 0.0)),
                        "summary_exec_ms": float(response.get("summary_exec_ms", 0.0)),
                        "full_json_bytes": int(response.get("full_json_bytes", 0)),
                        "compact_json_bytes": int(response.get("compact_json_bytes", 0)),
                        "browser_payload_json_bytes": size_bytes,
                        "rpc_residual_ms": wall * 1000
                        - float(response.get("browser_exec_ms", 0.0))
                        - float(response.get("summary_exec_ms", 0.0)),
                    })
                    await asyncio.sleep(0.1)
                pair_after = _finite_summary(await adapter._reader_snapshot(page))
                reader_rows[-2]["pair_p1_stable"] = pair_before == before_summary == pair_after
                reader_rows[-1]["pair_p1_stable"] = pair_before == before_summary == pair_after

            trace_full_rows: list[dict[str, Any]] = []
            trace_full_raw: list[dict[str, Any]] = []
            trace_compact_rows: list[dict[str, Any]] = []
            trace_compact_raw: list[dict[str, Any]] = []
            trace_string_rows: list[dict[str, Any]] = []
            trace_full_js = _browser_trace_script(compact=False)
            compact_trace_js = _browser_trace_script(compact=True)
            trace_string_js = _browser_trace_script(compact=False, json_string=True)
            trace_warmup = []
            for label, script, is_full in (
                ("full", trace_full_js, True), ("compact", compact_trace_js, False),
                ("json_string", trace_string_js, False)
            ):
                wall_start, cpu_start = time.perf_counter(), time.process_time()
                response = await canvas_locator.evaluate(script)
                wall, cpu = time.perf_counter() - wall_start, time.process_time() - cpu_start
                payload = response.get("payload") if is_full else None
                string_payload = None
                if label == "json_string":
                    try:
                        string_payload = json.loads(response.get("payload_json", "null"))
                    except (TypeError, json.JSONDecodeError):
                        pass
                trace_warmup.append({
                    "variant": label, "wall_s": wall, "cpu_s": cpu,
                    "browser_exec_ms": float(response.get("browser_exec_ms", 0.0)),
                    "paint_ms": float(response.get("paint_ms", 0.0)),
                    "full_json_bytes": int(response.get("full_json_bytes", 0)),
                    "compact_json_bytes": int(response.get("compact_json_bytes", 0)),
                    "projection_matches_python": (
                        _trace_summary(payload) == response.get("summary", {})
                        if isinstance(payload, dict) else True
                    ),
                    "json_string_roundtrip_deep_equal": (
                        string_payload == payload if isinstance(payload, dict) else None
                    ),
                })
                await asyncio.sleep(0.1)
            trace_pair_matches: list[bool] = []
            trace_pair_stable: list[bool] = []
            for pair in range(pairs):
                trace_pair_reader_before = _finite_summary(await adapter._reader_snapshot(page))
                wall_start, cpu_start = time.perf_counter(), time.process_time()
                full_response = await canvas_locator.evaluate(trace_full_js)
                wall, cpu = time.perf_counter() - wall_start, time.process_time() - cpu_start
                full_trace = full_response.get("payload")
                if not isinstance(full_trace, dict):
                    result["skip_reason"] = "full_native_snapshot_missing"
                    return result
                full_summary = _trace_summary(full_trace)
                full_browser_summary = full_response.get("summary", {})
                trace_full_raw.append(full_trace)
                trace_full_rows.append({
                    "pair": pair + 1, "variant": "full",
                    "wall_s": wall, "cpu_s": cpu,
                    "browser_exec_ms": float(full_response.get("browser_exec_ms", 0.0)),
                    "summary_exec_ms": float(full_response.get("summary_exec_ms", 0.0)),
                    "paint_ms": float(full_response.get("paint_ms", 0.0)),
                    "paint_count": int(full_response.get("paint_count", 0)),
                    "full_json_bytes": int(full_response.get("full_json_bytes", 0)),
                    "compact_json_bytes": int(full_response.get("compact_json_bytes", 0)),
                    "numeric_projection_matches_python": full_browser_summary == full_summary,
                    "numeric_summary": full_browser_summary,
                    "rpc_residual_ms": wall * 1000
                    - float(full_response.get("browser_exec_ms", 0.0))
                    - float(full_response.get("summary_exec_ms", 0.0)),
                })
                await asyncio.sleep(0.1)
                between_summaries = _finite_summary(await adapter._reader_snapshot(page))
                wall_start, cpu_start = time.perf_counter(), time.process_time()
                compact_trace = await canvas_locator.evaluate(compact_trace_js)
                wall, cpu = time.perf_counter() - wall_start, time.process_time() - cpu_start
                trace_pair_reader_after = _finite_summary(await adapter._reader_snapshot(page))
                trace_compact_raw.append(compact_trace)
                compact_summary = compact_trace.get("summary", {})
                trace_compact_rows.append({
                    "pair": pair + 1, "variant": "compact",
                    "wall_s": wall, "cpu_s": cpu,
                    "browser_exec_ms": float(compact_trace.get("browser_exec_ms", 0.0)),
                    "summary_exec_ms": float(compact_trace.get("summary_exec_ms", 0.0)),
                    "paint_ms": float(compact_trace.get("paint_ms", 0.0)),
                    "paint_count": int(compact_trace.get("paint_count", 0)),
                    "full_json_bytes": int(compact_trace.get("full_json_bytes", 0)),
                    "compact_json_bytes": int(compact_trace.get("compact_json_bytes", 0)),
                    "numeric_summary": compact_summary,
                    "rpc_residual_ms": wall * 1000
                    - float(compact_trace.get("browser_exec_ms", 0.0))
                    - float(compact_trace.get("summary_exec_ms", 0.0)),
                })
                await asyncio.sleep(0.1)
                string_wall_start, string_cpu_start = time.perf_counter(), time.process_time()
                string_response = await canvas_locator.evaluate(trace_string_js)
                string_wall = time.perf_counter() - string_wall_start
                string_cpu = time.process_time() - string_cpu_start
                parse_start, parse_cpu_start = time.perf_counter(), time.process_time()
                string_payload = json.loads(string_response.get("payload_json", "null"))
                parse_wall = time.perf_counter() - parse_start
                parse_cpu = time.process_time() - parse_cpu_start
                string_deep_equal = string_payload == full_trace
                trace_string_rows.append({
                    "pair": pair + 1, "variant": "json_string",
                    "wall_s": string_wall, "cpu_s": string_cpu,
                    "python_json_loads_wall_s": parse_wall,
                    "python_json_loads_cpu_s": parse_cpu,
                    "evaluate_plus_json_loads_wall_s": string_wall + parse_wall,
                    "json_string_utf8_bytes": len(string_response.get("payload_json", "").encode("utf-8")),
                    "browser_exec_ms": float(string_response.get("browser_exec_ms", 0.0)),
                    "summary_exec_ms": float(string_response.get("summary_exec_ms", 0.0)),
                    "paint_ms": float(string_response.get("paint_ms", 0.0)),
                    "full_json_bytes": int(string_response.get("full_json_bytes", 0)),
                    "compact_json_bytes": int(string_response.get("compact_json_bytes", 0)),
                    "deep_equal_to_full_object": string_deep_equal,
                    "numeric_projection_matches_python": (
                        _trace_summary(string_payload) == string_response.get("summary", {})
                    ),
                    "numeric_summary": string_response.get("summary", {}),
                    "rpc_residual_ms": string_wall * 1000
                    - float(string_response.get("browser_exec_ms", 0.0))
                    - float(string_response.get("summary_exec_ms", 0.0)),
                })
                trace_pair_reader_after = _finite_summary(await adapter._reader_snapshot(page))
                pair_valid = (
                    trace_pair_reader_before == before_summary
                    and between_summaries == before_summary
                    and trace_pair_reader_after == before_summary
                    and full_trace.get("hooksIntact") is True
                    and full_trace.get("overflow") is False
                    and full_trace.get("totalOverflow") is False
                    and compact_summary.get("hooks_intact") is True
                    and compact_summary.get("overflow") is False
                    and compact_summary.get("total_overflow") is False
                    and _target_signature(full_trace) == _target_signature(trace_full_raw[0])
                    and _source_signature(full_trace) == _source_signature(trace_full_raw[0])
                    and full_trace.get("paint") == trace_full_raw[0].get("paint")
                    and string_deep_equal
                )
                trace_pair_stable.append(pair_valid)
                trace_pair_matches.append(full_summary == compact_summary)
                for row in (trace_full_rows[-1], trace_compact_rows[-1], trace_string_rows[-1]):
                    row["pair_page_and_trace_stable"] = pair_valid
                await asyncio.sleep(0.1)

            final_snapshot = await adapter._reader_snapshot(page)
            after_summary = _finite_summary(final_snapshot)
            reader_pair_stable = [
                reader_rows[index]["pair_p1_stable"]
                for index in range(1, len(reader_rows), 2)
            ]
            if (
                len(reader_pair_stable) != pairs
                or len(trace_pair_stable) != pairs
                or not all(reader_pair_stable)
                or not all(trace_pair_stable)
            ):
                raise RuntimeError(
                    "snapshot shadow probe invalid: pair count mismatch or unstable pair"
                )
            reader_pairs_match = [
                full == compact
                for full, compact in zip(reader_full_payloads, reader_compact_payloads, strict=True)
            ]
            reader_repeat_equal = all(
                item == reader_full_payloads[0] for item in reader_full_payloads
            ) and all(item == reader_compact_payloads[0] for item in reader_compact_payloads)

            trace_stable = True
            for full_trace, compact_trace in zip(trace_full_raw, trace_compact_raw, strict=True):
                if _target_signature(full_trace) != _target_signature(trace_full_raw[0]):
                    trace_stable = False
                if _source_signature(full_trace) != _source_signature(trace_full_raw[0]):
                    trace_stable = False
                if full_trace.get("paint") != trace_full_raw[0].get("paint"):
                    trace_stable = False

            validated_trace = None
            white_paint_valid = False
            trace_validation_reason = "not_run"
            try:
                first_trace = trace_full_raw[0]
                first_row = adapter._page_row(initial, "p1")
                dims = [first_row["canvas"]["width"], first_row["canvas"]["height"]]
                validated_trace = validate_tile_trace(
                    first_trace, expected_width=dims[0], expected_height=dims[1]
                )
                white_paint_valid = validate_white_paint_path(
                    first_trace.get("paint"), width=dims[0], height=dims[1]
                )
                trace_validation_reason = "valid"
            except NativeCaptureUnavailable as exc:
                trace_validation_reason = type(exc).__name__

            response_binding = {
                "trace_validated": validated_trace is not None,
                "response_count_for_bound_source": 0,
                "unique_response_matches_source": False,
                "response_status": None,
                "request_is_exact_unredirected_image": False,
                "content_type_is_jpeg": False,
                "declared_length_bytes": None,
                "response_body_read": False,
            }
            if validated_trace is not None:
                url = validated_trace.source_url
                responses = adapter._native_responses.get(url, [])
                response_binding["response_count_for_bound_source"] = len(responses)
                if len(responses) == 1:
                    response = responses[0]
                    request = response.request
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    response_binding.update({
                        "unique_response_matches_source": response.url == url,
                        "response_status": response.status,
                        "request_is_exact_unredirected_image": (
                            request.url == url and request.redirected_from is None
                            and request.resource_type == "image"
                        ),
                        "content_type_is_jpeg": content_type == "image/jpeg",
                    })
                    try:
                        length = int(response.headers.get("content-length", ""))
                    except ValueError:
                        length = None
                    response_binding["declared_length_bytes"] = length

            reader_group = {}
            for variant in ("full", "compact"):
                selected = [row for row in reader_rows if row["variant"] == variant]
                reader_group[variant] = {
                    "wall": _stats([row["wall_s"] for row in selected], unit="s"),
                    "cpu": _stats([row["cpu_s"] for row in selected], unit="s"),
                    "browser_exec": _stats([row["browser_exec_ms"] for row in selected], unit="ms"),
                    "summary_exec": _stats([row["summary_exec_ms"] for row in selected], unit="ms"),
                    "payload_json_size": _stats(
                        [float(row["browser_payload_json_bytes"]) for row in selected], unit="bytes"
                    ),
                }
            trace_group = {}
            for variant, selected in (
                ("full", trace_full_rows), ("compact", trace_compact_rows),
                ("json_string", trace_string_rows)
            ):
                trace_group[variant] = {
                    "wall": _stats([row["wall_s"] for row in selected], unit="s"),
                    "cpu": _stats([row["cpu_s"] for row in selected], unit="s"),
                    "browser_exec": _stats([row["browser_exec_ms"] for row in selected], unit="ms"),
                    "summary_exec": _stats([row["summary_exec_ms"] for row in selected], unit="ms"),
                    "paint": _stats([row["paint_ms"] for row in selected], unit="ms"),
                    "full_json_size": _stats([float(row["full_json_bytes"]) for row in selected], unit="bytes"),
                    "compact_json_size": _stats([float(row["compact_json_bytes"]) for row in selected], unit="bytes"),
                    "draw_counts": [row["numeric_summary"].get("draw_count") for row in selected],
                }
                if variant == "json_string":
                    trace_group[variant]["json_string_utf8_size"] = _stats(
                        [float(row["json_string_utf8_bytes"]) for row in selected], unit="bytes"
                    )
                    trace_group[variant]["python_json_loads_wall"] = _stats(
                        [float(row["python_json_loads_wall_s"]) for row in selected], unit="s"
                    )
                    trace_group[variant]["python_json_loads_cpu"] = _stats(
                        [float(row["python_json_loads_cpu_s"]) for row in selected], unit="s"
                    )
                    trace_group[variant]["evaluate_plus_json_loads_wall"] = _stats(
                        [float(row["evaluate_plus_json_loads_wall_s"]) for row in selected], unit="s"
                    )

            result["reader"] = {
                "snapshot_count_per_variant": pairs,
                "before_after_page_summary_equal": before_summary == after_summary,
                "before_active_page_number": before_summary["active_page_number"],
                "after_active_page_number": after_summary["active_page_number"],
                "projection_matches_on_stable_pairs": sum(
                    match and stable
                    for match, stable in zip(reader_pairs_match, reader_pair_stable, strict=True)
                ),
                "pairs_checked": len(reader_pair_stable),
                "stable_pairs": sum(reader_pair_stable),
                "projection_mismatches_on_stable_pairs": sum(
                    not match for match, stable in zip(reader_pairs_match, reader_pair_stable, strict=True)
                    if stable
                ),
                "unstable_pairs": reader_pair_stable.count(False),
                "per_pair_stable": reader_pair_stable,
                "full_snapshots_stable": reader_repeat_equal,
                "full_vs_compact": reader_group,
                "first_warmup_excluded": reader_warmup,
                "rows": reader_rows,
            }
            result["trace"] = {
                "snapshot_count_per_variant": pairs,
                "projection_matches_on_stable_pairs": sum(
                    match for match, stable in zip(trace_pair_matches, trace_pair_stable, strict=True)
                    if stable
                ),
                "pairs_checked": len(trace_pair_stable),
                "stable_pairs": sum(trace_pair_stable),
                "unstable_pairs": trace_pair_stable.count(False),
                "per_pair_stable": trace_pair_stable,
                "full_target_source_paint_signatures_stable": trace_stable,
                "json_string_full_deep_equality_count": sum(
                    bool(row["deep_equal_to_full_object"]) for row in trace_string_rows
                ),
                "json_string_full_deep_equality_n": len(trace_string_rows),
                "tile_trace_validation_reason": trace_validation_reason,
                "white_paint_valid": white_paint_valid,
                "source_response_metadata": response_binding,
                "full_vs_compact": trace_group,
                "first_warmup_excluded": trace_warmup,
                "full_rows": trace_full_rows,
                "compact_rows": trace_compact_rows,
                "json_string_rows": trace_string_rows,
            }
            result["page_state_before_after"] = {
                "same_expected_viewer": adapter._source_identity is not None
                and parse_piccoma_viewer_url(page.url) == adapter._source_identity,
                "reader_projection_unchanged": before_summary == after_summary,
            }
            await retire_native_trace(page, canvas_locator)
            return result
        finally:
            await context.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("endpoint")
    parser.add_argument("run_root", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--pairs", type=int, default=12)
    args = parser.parse_args()
    result = asyncio.run(_probe(args.endpoint, args.run_root, args.report, args.pairs))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({
        "report": str(args.report),
        "runner_error_type": result.get("runner_error_type"),
        "repeat_probe_allowed": result.get("repeat_probe_allowed_by_observed_guard"),
        "reader_projection_matches": result.get("reader", {}).get(
            "projection_matches_on_stable_pairs", 0
        ),
        "reader_pairs_checked": result.get("reader", {}).get("pairs_checked", 0),
        "trace_projection_matches": result.get("trace", {}).get(
            "projection_matches_on_stable_pairs", 0
        ),
        "trace_pairs_checked": result.get("trace", {}).get("pairs_checked", 0),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
