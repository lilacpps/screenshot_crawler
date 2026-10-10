"""Ephemeral per-process timing hooks for the Piccoma performance probe.

Loaded only when PERF_TRACE_FILE is set. It records sanitized timings and
counts; it never records browser URLs, bodies, screenshot bytes, or credentials.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


def _windows_memory_mb() -> tuple[float | None, float | None]:
    """Read process working-set counters without an extra runtime dependency."""
    if os.name != "nt":
        return None, None
    try:
        import ctypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong
        ]
        psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        process = kernel32.GetCurrentProcess()
        ok = psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb)
        if not ok:
            return None, None
        return counters.WorkingSetSize / 1048576, counters.PeakWorkingSetSize / 1048576
    except (AttributeError, OSError):
        return None, None


_TRACE = os.environ.get("PERF_TRACE_FILE")
if _TRACE:
    _PROGRESS = os.environ.get("PERF_PROGRESS_FILE")
    _events: list[dict[str, Any]] = []
    _counters: dict[str, int] = {}
    _totals: dict[str, dict[str, float]] = {}
    _origin = time.perf_counter()
    _current_page: int | None = None
    _page_count = 0
    _last_capture_start_s: float | None = None
    _last_capture_page: int | None = None
    _transition_window: dict[str, Any] | None = None
    _image_phase: list[str] = []
    _native_gate_passed: set[int] = set()
    _last_native_snapshot_metrics: dict[str, float | int] | None = None

    def _record(name: str, wall: float, cpu: float, **extra: Any) -> None:
        end = time.perf_counter()
        _counters[name] = _counters.get(name, 0) + 1
        row = _totals.setdefault(name, {"wall_s": 0.0, "cpu_s": 0.0})
        row["wall_s"] += wall
        row["cpu_s"] += cpu
        _events.append({"stage": name, "start_s": end - _origin - wall,
                        "end_s": end - _origin, "wall_s": wall, "cpu_s": cpu,
                        "page_index": _current_page, **extra})

    def _wrap_async(target: Any, attr: str, name: str) -> None:
        original = getattr(target, attr)

        async def wrapped(*args: Any, **kwargs: Any) -> Any:
            wall_start, cpu_start = time.perf_counter(), time.process_time()
            try:
                return await original(*args, **kwargs)
            finally:
                _record(name, time.perf_counter() - wall_start, time.process_time() - cpu_start)

        setattr(target, attr, wrapped)

    try:
        from screenshot_crawler.core.runner import CrawlerRunner

        _original_adapter_call = CrawlerRunner._adapter_call

        async def _timed_adapter_call(self: Any, awaitable: Any, operation: str, **kwargs: Any) -> Any:
            global _page_count, _current_page, _last_capture_start_s, _last_capture_page
            if operation == "capture_page":
                capture_start_s = time.perf_counter() - _origin
                if _last_capture_start_s is not None and _last_capture_page is not None:
                    _record(
                        "page.capture_start_to_capture_start",
                        capture_start_s - _last_capture_start_s,
                        0.0,
                        page_index=_last_capture_page,
                        next_page_index=_page_count + 1,
                        complete_cycle=True,
                    )
                _page_count += 1
                _current_page = _page_count
                _last_capture_start_s = capture_start_s
                _last_capture_page = _page_count
            wall_start, cpu_start = time.perf_counter(), time.process_time()
            try:
                return await _original_adapter_call(self, awaitable, operation, **kwargs)
            finally:
                if operation in {
                    "initialize", "detect_state", "get_content_context", "get_content_identity",
                    "capture_page", "go_next", "wait_for_change", "collect_debug_metadata",
                }:
                    _record(f"runner.{operation}", time.perf_counter() - wall_start,
                            time.process_time() - cpu_start)

        CrawlerRunner._adapter_call = _timed_adapter_call

        _original_pace = CrawlerRunner._pace_before_page_turn

        async def _timed_pace(self: Any, page: Any) -> None:
            wall_start, cpu_start = time.perf_counter(), time.process_time()
            try:
                await _original_pace(self, page)
            finally:
                _record("runner.pacing", time.perf_counter() - wall_start,
                        time.process_time() - cpu_start,
                        configured_ms=self.config.page_turn_delay_ms)

        CrawlerRunner._pace_before_page_turn = _timed_pace

        _original_run = CrawlerRunner.run

        async def _profiled_run(self: Any, page: Any, adapter: Any) -> Any:
            wall_start, cpu_start = time.perf_counter(), time.process_time()
            finished = asyncio.Event()
            heartbeat: dict[str, float | int] = {"max_lag_s": 0.0, "ticks": 0}

            async def beat() -> None:
                interval = 0.05
                target = time.perf_counter() + interval
                while not finished.is_set():
                    await asyncio.sleep(interval)
                    now = time.perf_counter()
                    heartbeat["ticks"] = int(heartbeat["ticks"]) + 1
                    lag = max(0.0, now - target)
                    heartbeat["max_lag_s"] = max(
                        float(heartbeat["max_lag_s"]), lag
                    )
                    if lag >= 0.005:
                        _events.append({
                            "stage": "event_loop.heartbeat_lag",
                            "start_s": now - _origin - lag,
                            "end_s": now - _origin,
                            "wall_s": lag,
                            "cpu_s": 0.0,
                            "page_index": _current_page,
                        })
                    target = now + interval

            monitor = asyncio.create_task(beat())
            outcome = "ok"
            try:
                return await _original_run(self, page, adapter)
            except BaseException as exc:
                outcome = type(exc).__name__
                raise
            finally:
                finished.set()
                await asyncio.gather(monitor, return_exceptions=True)
                if _last_capture_start_s is not None and _last_capture_page is not None:
                    end_s = time.perf_counter() - _origin
                    _events.append({
                        "stage": "page.last_capture_to_run_end_incomplete",
                        "start_s": _last_capture_start_s,
                        "end_s": end_s,
                        "wall_s": end_s - _last_capture_start_s,
                        "cpu_s": 0.0,
                        "page_index": _last_capture_page,
                        "complete_cycle": False,
                        "terminal_outcome": outcome,
                    })
                _record("runner.whole_run", time.perf_counter() - wall_start,
                        time.process_time() - cpu_start, outcome=outcome,
                        max_pages_config=self.config.max_pages)
                _record("event_loop.heartbeat", 0.0, 0.0,
                        interval_s=0.05, max_lag_s=heartbeat["max_lag_s"],
                        ticks=heartbeat["ticks"])

        CrawlerRunner.run = _profiled_run

        # Core page commit and progress/manifests are synchronously written.
        from screenshot_crawler.core import runner as runner_module
        from screenshot_crawler.core.progress import ProgressStore

        original_save_capture = runner_module.save_capture

        def timed_save_capture(*args: Any, **kwargs: Any) -> Any:
            if _current_page not in _native_gate_passed:
                raise RuntimeError("performance_probe_save_without_native_webp_proof")
            wall_start, cpu_start = time.perf_counter(), time.process_time()
            try:
                return original_save_capture(*args, **kwargs)
            finally:
                _record("core.save_capture", time.perf_counter() - wall_start,
                        time.process_time() - cpu_start)
                if _current_page is not None:
                    _native_gate_passed.discard(_current_page)

        runner_module.save_capture = timed_save_capture
        original_add_pages = ProgressStore.add_pages

        def timed_add_pages(self: Any, *args: Any, **kwargs: Any) -> Any:
            wall_start, cpu_start = time.perf_counter(), time.process_time()
            try:
                return original_add_pages(self, *args, **kwargs)
            finally:
                _record("core.manifest_progress_write", time.perf_counter() - wall_start,
                        time.process_time() - cpu_start)
                if _PROGRESS:
                    pages = args[0] if args else ()
                    sequences = [
                        getattr(item, "sequence", None) for item in pages
                        if isinstance(getattr(item, "sequence", None), int)
                    ]
                    latest = max(sequences, default=_current_page or 0)
                    safe_stages = {
                        "runner.capture_page", "adapter.capture_page_total",
                        "capture.native_webp_gate", "browser.response_body",
                        "image.source_jpeg_validation", "browser.js.jpeg_decode_ms",
                        "browser.js.draw_408_ms", "browser.js.png_encode_ms",
                        "image.png_decode_white_composite", "pillow.save.png",
                        "image.webp_encode", "image.webp_encode_or_fallback",
                        "pillow.save.webp", "pillow.codec_decode.webp",
                        "image.final_format_validation",
                        "image.webp_fallback_png_validation",
                        "image.webp_encoder_output_validation", "core.save_capture",
                        "core.manifest_progress_write",
                    }
                    events = [
                        {key: event[key] for key in (
                            "stage", "start_s", "end_s", "wall_s", "cpu_s",
                            "page_index", "bytes", "passed", "method", "result_count",
                        ) if key in event}
                        for event in _events
                        if event.get("page_index") == latest
                        and event.get("stage") in safe_stages
                    ]
                    progress = {
                        "committed_page_count": latest,
                        "latest_page_index": latest,
                        "profile_elapsed_s": time.perf_counter() - _origin,
                        "page_spans": events,
                    }
                    if latest == 1:
                        progress_path = Path(_PROGRESS)
                        progress_path.parent.mkdir(parents=True, exist_ok=True)
                        progress_path.write_text(
                            json.dumps(progress, indent=2), encoding="utf-8"
                        )

        ProgressStore.add_pages = timed_add_pages

        from screenshot_crawler.site_adapters.piccoma import adapter as adapter_module
        from screenshot_crawler.site_adapters.piccoma import native_capture as native_module

        _reader_snapshot_original = adapter_module.PiccomaAdapter._reader_snapshot

        async def _timed_reader_snapshot(self: Any, page: Any) -> Any:
            wall_start, cpu_start = time.perf_counter(), time.process_time()
            result = await _reader_snapshot_original(self, page)
            now = time.perf_counter()
            window = _transition_window
            if window is not None and window.get("phase") == "waiting":
                observer_cpu_start = time.process_time()
                expected = window.get("expected_id")
                try:
                    window["observed_reader_snapshots"] = int(
                        window.get("observed_reader_snapshots", 0)
                    ) + 1
                    active = result.get("activeIds")
                    if active == [expected] and window.get("first_expected_id_s") is None:
                        window["first_expected_id_s"] = now - float(window["click_start"])
                        _record(
                            "transition.first_expected_id",
                            now - float(window["click_start"]), 0.0,
                            page_index=window.get("page_index"),
                            expected_id=expected,
                        )
                    loaded = False
                    signature = None
                    if active == [expected]:
                        row = self._page_row(result, expected)
                        canvas = row.get("canvas")
                        loaded = (
                            row.get("canvasCount") == 1
                            and row.get("loadedCount") == 1
                            and isinstance(canvas, dict)
                            and canvas.get("loaded") is True
                            and isinstance(canvas.get("width"), int)
                            and canvas.get("width", 0) > 0
                            and isinstance(canvas.get("height"), int)
                            and canvas.get("height", 0) > 0
                            and self._canvas_renderability_is_valid(row)
                        )
                        if loaded:
                            renderability = canvas["renderability"]
                            signature = (
                                row["id"], canvas.get("width"), canvas.get("height"),
                                tuple(canvas.get("rect", [])),
                                tuple(result.get("viewport", [])),
                                tuple(tuple(sorted(item.items()))
                                      for item in renderability["ancestors"]),
                            )
                    if loaded and window.get("first_loaded_s") is None:
                        window["first_loaded_s"] = now - float(window["click_start"])
                        _record(
                            "transition.first_loaded_snapshot",
                            now - float(window["click_start"]), 0.0,
                            page_index=window.get("page_index"), expected_id=expected,
                        )
                    if signature is not None:
                        if signature == window.get("previous_signature"):
                            window["stable_samples"] = int(window.get("stable_samples", 0)) + 1
                        else:
                            window["stable_samples"] = 1
                        window["previous_signature"] = signature
                        if window["stable_samples"] == 3 and window.get("three_stable_s") is None:
                            window["three_stable_s"] = now - float(window["click_start"])
                            _record(
                                "transition.three_stable_snapshots",
                                now - float(window["click_start"]), 0.0,
                                page_index=window.get("page_index"), expected_id=expected,
                            )
                    else:
                        window["stable_samples"] = 0
                        window["previous_signature"] = None
                except Exception:  # noqa: BLE001 - observer must not affect adapter behavior
                    window["observer_error_count"] = int(window.get("observer_error_count", 0)) + 1
                finally:
                    window["observer_cpu_s"] = float(
                        window.get("observer_cpu_s", 0.0)
                    ) + time.process_time() - observer_cpu_start
            _record("adapter.reader_snapshot", now - wall_start,
                    time.process_time() - cpu_start)
            return result

        adapter_module.PiccomaAdapter._reader_snapshot = _timed_reader_snapshot

        _go_next_original = adapter_module.PiccomaAdapter.go_next

        async def _timed_go_next(self: Any, page: Any) -> None:
            global _transition_window
            current_id = getattr(self, "_expected_page_id", None)
            current_number = None
            if isinstance(current_id, str) and current_id.startswith("p"):
                try:
                    current_number = int(current_id[1:])
                except ValueError:
                    current_number = None
            _transition_window = {
                "phase": "before_click",
                "expected_id": (
                    "last" if current_number == getattr(self, "_page_count", None)
                    else f"p{current_number + 1}" if current_number else None
                ),
                "click_start": None,
                "page_index": _current_page,
                "go_next_start_s": time.perf_counter(),
                "stable_samples": 0,
                "observer_error_count": 0,
            }
            wall_start, cpu_start = time.perf_counter(), time.process_time()
            try:
                await _go_next_original(self, page)
            finally:
                _record("adapter.go_next_total", time.perf_counter() - wall_start,
                        time.process_time() - cpu_start)

        adapter_module.PiccomaAdapter.go_next = _timed_go_next

        _wait_for_change_original = adapter_module.PiccomaAdapter.wait_for_change

        async def _timed_wait_for_change(self: Any, page: Any, previous_identity: Any) -> None:
            global _transition_window
            expected_id = None
            if (
                previous_identity is not None
                and previous_identity.page_number is not None
                and self._page_count is not None
            ):
                expected_id = (
                    f"p{previous_identity.page_number + 1}"
                    if previous_identity.page_number < self._page_count else "last"
                )
            if expected_id is not None and _transition_window is not None:
                _transition_window["phase"] = "waiting"
                _transition_window["expected_id"] = expected_id
                if _transition_window.get("click_start") is None:
                    _transition_window["click_start"] = time.perf_counter()
            wall_start, cpu_start = time.perf_counter(), time.process_time()
            try:
                await _wait_for_change_original(self, page, previous_identity)
            finally:
                _record("adapter.wait_for_change_total", time.perf_counter() - wall_start,
                        time.process_time() - cpu_start,
                        expected_id=expected_id,
                        first_expected_id_s=(_transition_window or {}).get("first_expected_id_s"),
                        first_loaded_s=(_transition_window or {}).get("first_loaded_s"),
                        three_stable_s=(_transition_window or {}).get("three_stable_s"),
                        observed_reader_snapshots=(_transition_window or {}).get(
                            "observed_reader_snapshots", 0
                        ),
                        observer_cpu_s=(_transition_window or {}).get("observer_cpu_s", 0.0),
                        observer_error_count=(_transition_window or {}).get("observer_error_count", 0))
                window = _transition_window
                if window is not None and window.get("go_next_start_s") is not None:
                    end = time.perf_counter()
                    _record(
                        "transition.go_next_start_to_wait_complete",
                        end - float(window["go_next_start_s"]), 0.0,
                        page_index=window.get("page_index"), expected_id=expected_id,
                    )
                if window is not None and window.get("click_start") is not None:
                    end = time.perf_counter()
                    _record(
                        "transition.click_start_to_wait_complete",
                        end - float(window["click_start"]), 0.0,
                        page_index=window.get("page_index"), expected_id=expected_id,
                    )
                _transition_window = None

        adapter_module.PiccomaAdapter.wait_for_change = _timed_wait_for_change

        _original_capture_page = adapter_module.PiccomaAdapter.capture_page

        async def _native_only_capture(self: Any, page: Any) -> Any:
            wall_start, cpu_start = time.perf_counter(), time.process_time()
            try:
                result = await _original_capture_page(self, page)
                method = getattr(self, "_capture_method", None)
                source_native = getattr(self, "_capture_source_native", False)
                output_format = getattr(self, "_capture_output_format", None)
                output_lossless = getattr(self, "_capture_output_lossless", False)
                native_ok = (
                    method == "native_tile_replay_lossless_webp"
                    and source_native is True
                    and output_format == "image/webp"
                    and output_lossless is True
                )
                _record("capture.native_webp_gate", 0.0, 0.0,
                        passed=native_ok, method=method, result_count=len(result or ()))
                if result and not native_ok:
                    raise RuntimeError("performance_probe_requires_native_lossless_webp")
                if result and native_ok and _current_page is not None:
                    _native_gate_passed.add(_current_page)
                return result
            finally:
                _record("adapter.capture_page_total", time.perf_counter() - wall_start,
                        time.process_time() - cpu_start)

        adapter_module.PiccomaAdapter.capture_page = _native_only_capture

        async def reject_core_fallback(*args: Any, **kwargs: Any) -> Any:
            del args, kwargs
            _record("capture.core_fallback_rejected", 0.0, 0.0, passed=False)
            raise RuntimeError("performance_probe_rejects_non_native_capture")

        runner_module.capture_locator = reject_core_fallback
        _wrap_async(adapter_module, "capture_native_tile_replay", "native.capture_total")
        _wrap_async(adapter_module, "snapshot_native_trace", "native.snapshot_native_trace")
        _wrap_async(adapter_module, "validate_native_capture_still_current", "native.validate_current")
        _wrap_async(native_module, "snapshot_native_trace", "native.snapshot_native_trace")
        _wrap_async(native_module, "validate_native_capture_still_current", "native.validate_current")

        _evaluate_original = native_module._bounded_evaluate
        _phase07_profile = os.environ.get("PICCOMA_PHASE07_PROFILE") == "1"
        snapshot_json_expression = getattr(
            native_module, "SNAPSHOT_JSON_EXPRESSION", None
        )

        async def _timed_evaluate(subject: Any, expression: str, *args: Any, **kwargs: Any) -> Any:
            global _last_native_snapshot_metrics
            label = (
                "browser.snapshot_evaluate"
                if (
                    expression == snapshot_json_expression
                    or "snapshot(node)" in expression
                )
                else "browser.replay_evaluate" if "NativeCapture.replay(" in expression
                else "browser.other_evaluate"
            )
            if label == "browser.snapshot_evaluate" and not _phase07_profile:
                # The paint walk cost is collected out-of-band so proof values
                # and source signatures returned to production logic stay exact.
                expression = expression.replace(
                    "(node) => window.__piccomaNativeCapture?.snapshot(node) ?? null",
                    "(node) => { const started = performance.now(); "
                    "const value = window.__piccomaNativeCapture?.snapshot(node) ?? null; "
                    "const snapshotMs = performance.now() - started; "
                    "return { _probe_payload: value, _probe_snapshot_ms: snapshotMs, "
                    "_probe_paint: window.__piccomaPerf?.paint?.splice(0) ?? [] }; }",
                )
            wall_start, cpu_start = time.perf_counter(), time.process_time()
            try:
                result = await _evaluate_original(subject, expression, *args, **kwargs)
                if (
                    label == "browser.snapshot_evaluate"
                    and _phase07_profile
                ):
                    if isinstance(result, str):
                        result_kind = "json_string"
                        result_characters = len(result)
                    elif isinstance(result, dict):
                        result_kind = "object"
                        result_characters = None
                    elif result is None:
                        result_kind = "null"
                        result_characters = None
                    else:
                        result_kind = "unsupported"
                        result_characters = None
                    _record(
                        "browser.snapshot_return_shape", 0.0, 0.0,
                        result_kind=result_kind,
                        result_characters=result_characters,
                    )
                if label == "browser.snapshot_evaluate" and isinstance(result, dict) and "_probe_payload" in result:
                    paint_values = [
                        float(value) for value in result.get("_probe_paint", [])
                        if isinstance(value, (int, float))
                    ]
                    _last_native_snapshot_metrics = {
                        "browser_snapshot_ms": float(result.get("_probe_snapshot_ms", 0.0)),
                        "paint_ms": sum(paint_values),
                        "paint_count": len(paint_values),
                    }
                    for value in paint_values:
                        _record(
                            "browser.js.paint_snapshot_dom_walk", value / 1000, 0.0,
                            timestamp_basis="duration_only_after_evaluate_return",
                        )
                    result = result.get("_probe_payload")
                if label == "browser.replay_evaluate" and isinstance(result, dict):
                    perf = result.get("perf")
                    if isinstance(perf, dict):
                        for key, value in perf.items():
                            if isinstance(value, (int, float)):
                                _record(
                                    f"browser.js.{key}", float(value) / 1000, 0.0,
                                    timestamp_basis="duration_only_after_evaluate_return",
                                )
                return result
            finally:
                _record(label, time.perf_counter() - wall_start,
                        time.process_time() - cpu_start)

        native_module._bounded_evaluate = _timed_evaluate

        _decode_snapshot_original = getattr(
            native_module, "_decode_native_snapshot_json", None
        )
        if _phase07_profile and callable(_decode_snapshot_original):

            def _timed_decode_snapshot(raw: Any) -> Any:
                wall_start, cpu_start = time.perf_counter(), time.process_time()
                try:
                    return _decode_snapshot_original(raw)
                finally:
                    _record(
                        "native.snapshot_json_decode",
                        time.perf_counter() - wall_start,
                        time.process_time() - cpu_start,
                        input_characters=len(raw) if isinstance(raw, str) else None,
                    )

            native_module._decode_native_snapshot_json = _timed_decode_snapshot

        async def _timed_install_trace(page: Any) -> None:
            # Research-only edits to the init script return numeric stage times;
            # replay geometry and pixels remain untouched.
            script = native_module.TRACE_INIT_SCRIPT
            if _phase07_profile:
                await page.add_init_script(script)
                return
            script = script.replace(
                "const paintSnapshot = canvas => {\n    const rows = [], pathNodes = [], rectOf = node => {",
                "const paintSnapshot = canvas => {\n"
                "    const paintStarted = performance.now();\n"
                "    const rows = [], pathNodes = [], rectOf = node => {",
            )
            script = script.replace(
                "return { canvasId: objectId(canvasIds, canvas), canvasRect,\n        ancestors: rows, firstOpaqueIndex: rows.length - 1,",
                "(window.__piccomaPerf ||= {}).paint ||= []; window.__piccomaPerf.paint.push(performance.now() - paintStarted);\n"
                "      return { canvasId: objectId(canvasIds, canvas), canvasRect,\n        ancestors: rows, firstOpaqueIndex: rows.length - 1,",
            )
            script = script.replace(
                "return { canvasId: objectId(canvasIds, canvas), canvasRect, ancestors: rows,\n      firstOpaqueIndex: -1,",
                "(window.__piccomaPerf ||= {}).paint ||= []; window.__piccomaPerf.paint.push(performance.now() - paintStarted);\n"
                "    return { canvasId: objectId(canvasIds, canvas), canvasRect, ancestors: rows,\n      firstOpaqueIndex: -1,",
            )
            script = script.replace(
                "const replay = async (base64Bytes, specification) => {\n    let objectUrl = null, replayCanvas = null;",
                "const replay = async (base64Bytes, specification) => {\n"
                "    let objectUrl = null, replayCanvas = null, decodeMs = 0, drawMs = 0, pngEncodeMs = 0;",
            )
            script = script.replace(
                "image.src = objectUrl; await image.decode();",
                "image.src = objectUrl; { const t = performance.now(); await image.decode(); decodeMs = performance.now() - t; }",
            )
            script = script.replace(
                "for (const draw of specification.draws) {",
                "{ const t = performance.now(); for (const draw of specification.draws) {",
            )
            script = script.replace(
                "native.drawImage.call(ctx, image, ...draw.args);\n      }\n      return { dataUrl: replayCanvas.toDataURL('image/png'),",
                "native.drawImage.call(ctx, image, ...draw.args);\n      } drawMs = performance.now() - t; }\n"
                "      const pngStart = performance.now(); const dataUrl = replayCanvas.toDataURL('image/png');\n"
                "      pngEncodeMs = performance.now() - pngStart;\n"
                "      return { perf: { jpeg_decode_ms: decodeMs, draw_408_ms: drawMs, png_encode_ms: pngEncodeMs }, dataUrl,",
            )
            if "perf: { jpeg_decode_ms" not in script or "paintStarted" not in script:
                raise RuntimeError("research timing insertion did not match source")
            await page.add_init_script(script)

        adapter_module.install_native_trace = _timed_install_trace

        for attr, name in (
            ("validate_source_jpeg", "image.source_jpeg_validation"),
            ("composite_replay_png_on_white", "image.png_decode_white_composite"),
            ("encode_lossless_webp", "image.webp_encode"),
            ("encode_lossless_webp_or_png", "image.webp_encode_or_fallback"),
            ("capture_result_format_is_valid", "image.final_format_validation"),
        ):
            original = getattr(native_module, attr)

            def make_wrapper(fn: Any, label: str) -> Any:
                def wrapped(*args: Any, **kwargs: Any) -> Any:
                    wall_start, cpu_start = time.perf_counter(), time.process_time()
                    phase = None
                    if label in {
                        "image.webp_encode", "image.webp_encode_or_fallback"
                    }:
                        phase = label
                        _image_phase.append(phase)
                    elif label == "image.final_format_validation":
                        if "image.webp_encode_or_fallback" in _image_phase:
                            phase = "webp_fallback_png_validation"
                        elif "image.webp_encode" in _image_phase:
                            phase = "webp_encoder_output_validation"
                    try:
                        return fn(*args, **kwargs)
                    finally:
                        actual_label = (
                            f"image.{phase}" if label == "image.final_format_validation"
                            and phase is not None else label
                        )
                        _record(actual_label, time.perf_counter() - wall_start,
                                time.process_time() - cpu_start)
                        if phase in {
                            "image.webp_encode", "image.webp_encode_or_fallback"
                        }:
                            _image_phase.pop()

                return wrapped

            setattr(native_module, attr, make_wrapper(original, name))
            if hasattr(adapter_module, attr):
                setattr(adapter_module, attr, getattr(native_module, attr))

        # Count and time only response.body() calls used for exact source bytes.
        from playwright.async_api import Locator, Page, Response

        for target, methods, prefix in (
            (Page, ("evaluate", "wait_for_function", "goto", "wait_for_timeout",
                    "set_viewport_size", "add_init_script"), "browser.Page"),
            (Locator, ("count", "evaluate", "evaluate_all", "inner_text", "click", "wait_for"),
             "browser.Locator"),
        ):
            for method in methods:
                _wrap_async(target, method, f"{prefix}.{method}")

        _locator_click_original = Locator.click

        async def _timed_locator_click(self: Any, *args: Any, **kwargs: Any) -> Any:
            if (
                _transition_window is not None
                and _transition_window.get("phase") == "before_click"
            ):
                start = time.perf_counter()
                if _transition_window is not None:
                    _transition_window["click_start"] = start
                    _transition_window["phase"] = "clicking"
                try:
                    return await _locator_click_original(self, *args, **kwargs)
                finally:
                    end = time.perf_counter()
                    _record("transition.next_click_dom_action", end - start, 0.0,
                            page_index=_current_page,
                            identified_by="adapter_go_next_call_scope")
                    if _transition_window is not None:
                        _transition_window["click_complete_s"] = end - _origin
                        _transition_window["phase"] = "after_click"
            return await _locator_click_original(self, *args, **kwargs)

        Locator.click = _timed_locator_click

        _original_body = Response.body

        async def _timed_body(self: Any) -> bytes:
            wall_start, cpu_start = time.perf_counter(), time.process_time()
            body = await _original_body(self)
            _record("browser.response_body", time.perf_counter() - wall_start,
                    time.process_time() - cpu_start, bytes=len(body))
            return body

        Response.body = _timed_body

        # Measure synchronous Pillow calls individually, including the PNG
        # intermediate and final lossless WebP decode used by exact validation.
        from PIL import Image

        original_image_save = Image.Image.save
        original_image_load = Image.Image.load

        def timed_image_save(self: Any, fp: Any, *args: Any, **kwargs: Any) -> Any:
            fmt = str(kwargs.get("format") or "unknown").lower()
            wall_start, cpu_start = time.perf_counter(), time.process_time()
            try:
                return original_image_save(self, fp, *args, **kwargs)
            finally:
                _record(f"pillow.save.{fmt}", time.perf_counter() - wall_start,
                        time.process_time() - cpu_start)

        def timed_image_load(self: Any, *args: Any, **kwargs: Any) -> Any:
            fmt = str(getattr(self, "format", None) or "unknown").lower()
            wall_start, cpu_start = time.perf_counter(), time.process_time()
            try:
                return original_image_load(self, *args, **kwargs)
            finally:
                _record(f"pillow.load.{fmt}", time.perf_counter() - wall_start,
                        time.process_time() - cpu_start)

        Image.Image.save = timed_image_save
        Image.Image.load = timed_image_load

        from PIL import PngImagePlugin, WebPImagePlugin

        def time_codec_load(image_class: Any, codec: str) -> None:
            original_load = image_class.load

            def timed_codec_load(self: Any, *args: Any, **kwargs: Any) -> Any:
                wall_start, cpu_start = time.perf_counter(), time.process_time()
                try:
                    return original_load(self, *args, **kwargs)
                finally:
                    _record(f"pillow.codec_decode.{codec}",
                            time.perf_counter() - wall_start,
                            time.process_time() - cpu_start)

            image_class.load = timed_codec_load

        time_codec_load(PngImagePlugin.PngImageFile, "png")
        time_codec_load(WebPImagePlugin.WebPImageFile, "webp")

        original_image_convert = Image.Image.convert

        def timed_image_convert(self: Any, mode: str | None = None, *args: Any,
                                **kwargs: Any) -> Any:
            source_format = str(getattr(self, "format", None) or "memory").lower()
            target_mode = mode or "default"
            wall_start, cpu_start = time.perf_counter(), time.process_time()
            try:
                return original_image_convert(self, mode, *args, **kwargs)
            finally:
                _record(f"pillow.convert.{source_format}_to_{target_mode}",
                        time.perf_counter() - wall_start,
                        time.process_time() - cpu_start)

        Image.Image.convert = timed_image_convert

        original_image_tobytes = Image.Image.tobytes

        def timed_image_tobytes(self: Any, *args: Any, **kwargs: Any) -> bytes:
            source_format = str(getattr(self, "format", None) or "memory").lower()
            wall_start, cpu_start = time.perf_counter(), time.process_time()
            try:
                return original_image_tobytes(self, *args, **kwargs)
            finally:
                phase = "inside_webp_encode" if _image_phase else "outside_webp_encode"
                _record(f"pillow.tobytes.{source_format}.{phase}",
                        time.perf_counter() - wall_start,
                        time.process_time() - cpu_start)

        Image.Image.tobytes = timed_image_tobytes

        _wrap_async(CrawlerRunner, "_check_access", "runner.access_check")

        _rss_start_mb, _rss_peak_mb = _windows_memory_mb()

        _events.append({"stage": "process_start", "start_s": 0.0, "end_s": 0.0,
                        "rss_start_mb": _rss_start_mb, "rss_peak_start_mb": _rss_peak_mb,
                        "python": os.sys.version.split()[0]})

        def _flush() -> None:
            path = Path(_TRACE)
            path.parent.mkdir(parents=True, exist_ok=True)
            rss_current, rss_peak = _windows_memory_mb()
            source_modules: dict[str, dict[str, str]] = {}
            module_candidates = {
                "piccoma_adapter": sys.modules.get(
                    "screenshot_crawler.site_adapters.piccoma.adapter"
                ),
                "piccoma_native_capture": sys.modules.get(
                    "screenshot_crawler.site_adapters.piccoma.native_capture"
                ),
                "runtime_settings": sys.modules.get(
                    "screenshot_crawler.runtime_settings"
                ),
                "cli": sys.modules.get("__main__"),
            }
            for name, module in module_candidates.items():
                module_file = getattr(module, "__file__", None)
                if not isinstance(module_file, str):
                    continue
                module_path = Path(module_file)
                if not module_path.is_file():
                    continue
                digest = hashlib.sha256(module_path.read_bytes()).hexdigest()
                source_modules[name] = {
                    "module_path": str(module_path.resolve()),
                    "sha256": digest,
                }
            payload = {"totals": _totals, "counts": _counters, "events": _events,
                       "source_modules": source_modules,
                       "rss_final_mb": rss_current, "rss_peak_mb": rss_peak}
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        import atexit

        atexit.register(_flush)
    except Exception as exc:  # noqa: BLE001 - profiling must fail visibly, never affect crawl
        Path(_TRACE + ".error").write_text(type(exc).__name__, encoding="utf-8")
