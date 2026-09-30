"""Diagnostic A/B runner for BookWalker's purchased original-JPEG path.

This script deliberately calls the production adapter methods without changing
their capture policy.  It records bounded, redacted observations for one
visible page and can return a persisted viewer to page 1 before capture.
Candidate query strings and image bodies are never written.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from screenshot_crawler.core.browser import BrowserSession
from screenshot_crawler.site_adapters.bookwalker import adapter as adapter_module
from screenshot_crawler.site_adapters.bookwalker.adapter import BookWalkerAdapter
from screenshot_crawler.site_adapters.bookwalker.original_capture import image_signature

URL_DEFAULT = "https://bookwalker.jp/dea0961d33-6ef8-4673-a455-0ec0ecd5de47/"
MAX_RESET_STEPS = 400
MAX_TRACE_RECORDS = 10_000

_INDEPENDENT_DRAW_TRACE_SCRIPT = f"""
(() => {{
  if (window.__bookwalkerAbTraceInstalled) return;
  window.__bookwalkerAbTraceInstalled = true;
  window.__bookwalkerAbTrace = {{operations: [], traceOverflow: false}};
  const previous = CanvasRenderingContext2D.prototype.drawImage;
  const canvasIds = new WeakMap();
  let nextCanvasId = 1;
  const canvasId = canvas => {{
    let id = canvasIds.get(canvas);
    if (!id) {{
      id = String(nextCanvasId++);
      canvasIds.set(canvas, id);
    }}
    return id;
  }};
  const sourceInfo = source => ({{
    constructor: source?.constructor?.name || null,
    width: Number.isFinite(source?.width) ? Number(source.width) : null,
    height: Number.isFinite(source?.height) ? Number(source.height) : null,
  }});
  const geometry = (source, values) => {{
    const width = Number.isFinite(source?.width) ? Number(source.width) : null;
    const height = Number.isFinite(source?.height) ? Number(source.height) : null;
    if (values.length === 2 && width !== null && height !== null) return {{
      sourceRect: {{x: 0, y: 0, width, height}},
      destination: {{x: values[0], y: values[1], width, height}},
    }};
    if (values.length === 4 && width !== null && height !== null) return {{
      sourceRect: {{x: 0, y: 0, width, height}},
      destination: {{x: values[0], y: values[1], width: values[2], height: values[3]}},
    }};
    if (values.length === 8) return {{
      sourceRect: {{x: values[0], y: values[1], width: values[2], height: values[3]}},
      destination: {{x: values[4], y: values[5], width: values[6], height: values[7]}},
    }};
    return {{sourceRect: null, destination: null}};
  }};
  CanvasRenderingContext2D.prototype.drawImage = function(...args) {{
    try {{
      const target = this.canvas;
      const values = args.slice(1).map(value => Number(value));
      const shape = geometry(args[0], values);
      const trace = window.__bookwalkerAbTrace;
      if (target && target.width >= 500 && target.height >= 500 && trace) {{
        if (trace.operations.length >= {MAX_TRACE_RECORDS}) {{
          trace.traceOverflow = true;
        }} else {{
          let transform = null;
          try {{
            const matrix = this.getTransform();
            transform = {{a: matrix.a, b: matrix.b, c: matrix.c, d: matrix.d, e: matrix.e, f: matrix.f}};
          }} catch (error) {{}}
          trace.operations.push({{
            index: trace.operations.length + 1,
            canvasId: canvasId(target),
            canvasWidth: Number(target.width),
            canvasHeight: Number(target.height),
            source: sourceInfo(args[0]),
            sourceRect: shape.sourceRect,
            destination: shape.destination,
            transform,
            alpha: Number.isFinite(this.globalAlpha) ? Number(this.globalAlpha) : null,
            composite: this.globalCompositeOperation || null,
            filter: this.filter || null,
          }});
        }}
      }}
    }} catch (error) {{}}
    return previous.apply(this, args);
  }};
}})();
"""


def _positive_int(value: str) -> int:
    result = int(value)
    if result < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return result


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _png_dimensions(data_url: object) -> tuple[int, int] | None:
    if not isinstance(data_url, str) or "," not in data_url:
        return None
    try:
        data = base64.b64decode(data_url.split(",", 1)[1], validate=True)
    except (ValueError, TypeError):
        return None
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def _source_summary(call: object) -> dict[str, Any]:
    if not isinstance(call, dict):
        return {}
    source = call.get("source")
    return {
        "operation": call.get("operation"),
        "index": call.get("index"),
        "canvas_id": call.get("canvasId"),
        "canvas_dimensions": [call.get("canvasWidth"), call.get("canvasHeight")],
        "source_id": call.get("sourceId"),
        "source": _json_safe(source),
        "source_rect": _json_safe(call.get("sourceRect")),
        "destination": _json_safe(call.get("destination")),
        "snapshot_id": call.get("snapshotId"),
        "snapshot_error": call.get("snapshotError"),
        "transform": _json_safe(call.get("transform")),
        "alpha": call.get("globalAlpha"),
        "composite": call.get("globalCompositeOperation"),
        "filter": call.get("filter"),
        "trace_operation_index": call.get("traceOperationIndex"),
    }


def _candidate_summary(candidate: object) -> dict[str, Any]:
    redacted_url = str(getattr(candidate, "redacted_url", ""))
    parsed = urlsplit(redacted_url)
    data = getattr(candidate, "data", b"")
    return {
        "host": parsed.netloc.lower(),
        "path": parsed.path,
        "width": getattr(candidate, "width", None),
        "height": getattr(candidate, "height", None),
        "byte_size": len(data) if isinstance(data, bytes) else None,
        "sequence": getattr(candidate, "sequence", None),
        "sha256": getattr(candidate, "sha256", None),
        "mime_type": getattr(candidate, "mime_type", None),
    }


def _stage_match_summary(
    *,
    native_captures: tuple[object, ...],
    candidates: tuple[object, ...],
    native_signatures: tuple[str | None, ...],
    signature_matches: list[list[object]],
) -> dict[str, Any]:
    dimensions = [
        [getattr(capture, "width", None), getattr(capture, "height", None)]
        for capture in native_captures
    ]
    dimension_matches = [
        [
            candidate
            for candidate in candidates
            if (getattr(candidate, "width", None), getattr(candidate, "height", None))
            == tuple(dimension)
        ]
        for dimension in dimensions
    ]
    return {
        "native_dimensions": dimensions,
        "native_signatures_available": [value is not None for value in native_signatures],
        "candidate_count_total": len(candidates),
        "candidate_count_dimension_match": [len(values) for values in dimension_matches],
        "candidate_count_signature_match": [len(values) for values in signature_matches],
        "candidate_count_unique_match": [len(values) == 1 for values in signature_matches],
        "selected_candidate_sha256": [
            getattr(values[0], "sha256", None) if len(values) == 1 else None
            for values in signature_matches
        ],
    }


async def _wait_for_counter_change(page: Any, previous: str) -> str:
    for _ in range(80):
        await page.wait_for_timeout(100)
        current = (await page.locator("#pageSliderCounter").inner_text()).strip()
        if current != previous:
            return current
    return (await page.locator("#pageSliderCounter").inner_text()).strip()


async def _return_to_first_page(page: Any, adapter: BookWalkerAdapter) -> list[str]:
    observed: list[str] = []
    for _ in range(MAX_RESET_STEPS):
        counter = (await page.locator("#pageSliderCounter").inner_text()).strip()
        if not observed or observed[-1] != counter:
            observed.append(counter)
        number, _ = adapter.parse_page_counter(counter)
        if number is None or number <= 1:
            return observed
        await page.keyboard.press("ArrowRight")
        await _wait_for_counter_change(page, counter)
    raise RuntimeError("viewer did not return to page 1 within the bounded reset")


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    adapter = BookWalkerAdapter()
    observations: dict[str, Any] = {
        "label": args.label,
        "url": args.url,
        "access_strategy": args.access_strategy,
        "reset_to_first_page": args.reset_to_first_page,
    }
    session = await BrowserSession.connect(args.cdp_endpoint)
    page = await session.new_page()
    try:
        await adapter.configure_run(page, args.access_strategy)
        await adapter.prepare_page(page)
        await page.add_init_script(_INDEPENDENT_DRAW_TRACE_SCRIPT)
        await page.goto(args.url, wait_until="commit")
        await adapter.initialize(page)
        observations["entry_url"] = page.url
        observations["counter_before_reset"] = (
            await page.locator("#pageSliderCounter").inner_text()
        ).strip()
        if args.reset_to_first_page:
            observations["reset_counters"] = await _return_to_first_page(page, adapter)
            await adapter._wait_for_render_ready(page)
        observations["counter_at_capture"] = (
            await page.locator("#pageSliderCounter").inner_text()
        ).strip()

        canvas = await adapter.get_capture_target(page)
        observations["renderer"] = {
            "canvas_id": await canvas.get_attribute("data-bookwalker-trace-id"),
            "bitmap": _json_safe(
                await canvas.evaluate("element => ({width: element.width, height: element.height})")
            ),
            "client": _json_safe(
                await canvas.evaluate(
                    "element => ({width: element.clientWidth, height: element.clientHeight})"
                )
            ),
            "bounding": _json_safe(await canvas.bounding_box()),
            "rect": _json_safe(
                await canvas.evaluate(
                    "element => { const r = element.getBoundingClientRect(); "
                    "return {x:r.x,y:r.y,width:r.width,height:r.height}; }"
                )
            ),
        }

        original_select = adapter_module.select_native_draw_calls
        original_materialize = adapter._materialize_native_source_crops
        original_matcher = adapter._capture_original_jpegs
        original_clear_geometry = adapter._clear_geometry_trace
        trace_observation: dict[str, Any] = {}
        selected_calls: list[dict[str, Any]] = []
        materialized: list[dict[str, Any]] = []
        matcher_observation: dict[str, Any] = {}
        wrapper_errors: list[str] = []

        def select_wrapper(*select_args: Any, **select_kwargs: Any) -> Any:
            result = original_select(*select_args, **select_kwargs)
            draw_calls = select_args[0] if select_args else select_kwargs.get("draw_calls")
            observations["draw_calls_all"] = _json_safe(draw_calls)
            observations["draw_call_candidates_count"] = len(draw_calls or [])
            observations["draw_call_selected_count"] = len(result or [])
            selected_calls.clear()
            selected_calls.extend(result or [])
            observations["selected_draw_calls"] = [
                _source_summary(call) for call in selected_calls
            ]
            return result

        async def materialize_wrapper(*materialize_args: Any, **materialize_kwargs: Any) -> Any:
            result = await original_materialize(*materialize_args, **materialize_kwargs)
            materialized.clear()
            materialized.extend(result or [])
            observations["native_materialization"] = [
                {
                    **_source_summary(call),
                    "crop_dimensions": _png_dimensions(call.get("sourceCropPng")),
                    "png_byte_size": (
                        len(base64.b64decode(call["sourceCropPng"].split(",", 1)[1]))
                        if isinstance(call.get("sourceCropPng"), str)
                        and "," in call["sourceCropPng"]
                        else None
                    ),
                }
                for call in materialized
            ]
            return result

        async def matcher_wrapper(page_arg: Any, native_arg: tuple[Any, ...]) -> Any:
            try:
                candidates = tuple(adapter._original_candidates.values())
                native_signatures = tuple(
                    [
                        await image_signature(page_arg, capture.data, "image/png")
                        for capture in native_arg
                    ]
                )
                signature_matches: list[list[Any]] = []
                for capture, native_signature in zip(
                    native_arg, native_signatures, strict=True
                ):
                    matches = []
                    for candidate in candidates:
                        if (candidate.width, candidate.height) != (
                            capture.width,
                            capture.height,
                        ):
                            continue
                        if candidate.signature is None:
                            candidate.signature = await image_signature(
                                page_arg, candidate.data, candidate.mime_type
                            )
                        if candidate.signature == native_signature:
                            matches.append(candidate)
                    signature_matches.append(matches)
                matcher_observation.update(
                    _stage_match_summary(
                        native_captures=native_arg,
                        candidates=candidates,
                        native_signatures=native_signatures,
                        signature_matches=signature_matches,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - preserve production behavior
                wrapper_errors.append(f"matcher instrumentation: {type(exc).__name__}: {exc}")
            try:
                result = await original_matcher(page_arg, native_arg)
            except Exception as exc:
                wrapper_errors.append(f"matcher production call: {type(exc).__name__}: {exc}")
                raise
            matcher_observation["decision"] = (
                "unique_match" if result is not None else "no_unique_match"
            )
            matcher_observation["returned_dimensions"] = [
                [capture.width, capture.height] for capture in result or ()
            ]
            matcher_observation["returned_sha256"] = [
                _sha256(capture.data) for capture in result or ()
            ]
            return result

        async def clear_geometry_wrapper(page_arg: Any) -> None:
            if not trace_observation:
                trace_observation["transform_trace"] = _json_safe(
                    await page_arg.evaluate(
                        "() => window.__bookwalkerTransformTrace || null"
                    )
                )
                trace_observation["draw_trace"] = _json_safe(
                    await page_arg.evaluate(
                        "() => window.__bookwalkerDrawCalls || []"
                    )
                )
            await original_clear_geometry(page_arg)

        adapter_module.select_native_draw_calls = select_wrapper
        adapter._materialize_native_source_crops = materialize_wrapper  # type: ignore[method-assign]
        adapter._capture_original_jpegs = matcher_wrapper  # type: ignore[method-assign]
        adapter._clear_geometry_trace = clear_geometry_wrapper  # type: ignore[method-assign]
        try:
            result = await adapter.capture_page(page)
        finally:
            adapter_module.select_native_draw_calls = original_select
        observations["production_capture"] = {
            "returned_path": (
                getattr(adapter, "_capture_debug", {})
                .get("bookwalker_capture", {})
                .get("returned_path")
            ),
            "result_count": len(result or ()),
            "results": [
                {
                    "width": capture.width,
                    "height": capture.height,
                    "byte_size": len(capture.data),
                    "mime_type": capture.mime_type,
                    "file_extension": capture.file_extension,
                    "sha256": _sha256(capture.data),
                }
                for capture in result or ()
            ],
        }
        observations["original_matcher"] = matcher_observation
        observations["trace_at_cleanup"] = trace_observation
        observations["independent_trace"] = _json_safe(
            await page.evaluate("() => window.__bookwalkerAbTrace || null")
        )
        observations["wrapper_errors"] = wrapper_errors
        observations["candidates"] = [
            _candidate_summary(candidate)
            for candidate in tuple(adapter._original_candidates.values())
        ]
        try:
            observations["adapter_debug"] = _json_safe(await adapter.collect_debug_metadata(page))
        except AttributeError:
            observations["adapter_debug"] = None
        return observations
    finally:
        await session.close_page(page)
        await session.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=URL_DEFAULT)
    parser.add_argument("--label", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cdp-endpoint", default="http://127.0.0.1:9222")
    parser.add_argument("--access-strategy", choices=("auto", "direct", "quota"), default="direct")
    parser.add_argument("--reset-to-first-page", action="store_true")
    parser.add_argument("--repeat", type=_positive_int, default=1)
    return parser


async def _main(args: argparse.Namespace) -> None:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for index in range(1, args.repeat + 1):
        args.label = f"{args.label}-{index}"
        result = await _run(args)
        path = args.output_dir / f"{args.label}.json"
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(path)


if __name__ == "__main__":
    asyncio.run(_main(_parser().parse_args()))
