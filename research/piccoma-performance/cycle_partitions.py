"""Partition real Python spans; never use synthetic browser-JS timestamps."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from itertools import pairwise
from pathlib import Path

TOP = {
    "runner.capture_page": "capture",
    "runner.pacing": "pacing",
    "runner.go_next": "go_next",
    "runner.wait_for_change": "wait_for_change",
    "runner.detect_state": "runner_state_metadata",
    "runner.get_content_context": "runner_state_metadata",
    "runner.get_content_identity": "runner_state_metadata",
    "runner.collect_debug_metadata": "runner_state_metadata",
    "runner.access_check": "access_check",
    "core.save_capture": "save",
    "core.manifest_progress_write": "manifest",
}
# Specific child categories take priority over their containing helper.
CAPTURE = {
    "browser.snapshot_evaluate": (0, "native_trace_rpc"),
    "native.snapshot_json_decode": (0, "native_trace_json_decode"),
    "adapter.reader_snapshot": (0, "reader_rpc"),
    "browser.response_body": (0, "source_body"),
    "image.source_jpeg_validation": (0, "source_jpeg_validation"),
    "browser.replay_evaluate": (0, "replay_rpc_including_browser_png"),
    "image.png_decode_white_composite": (0, "white_composite_rgb_png"),
    "pillow.save.webp": (0, "webp_encode"),
    "pillow.convert.webp_to_RGB": (0, "webp_roundtrip_convert"),
    "pillow.tobytes.memory.inside_webp_encode": (0, "webp_roundtrip_tobytes"),
    "image.webp_fallback_png_validation": (0, "fallback_png_validation"),
    "image.final_format_validation": (0, "final_format_validation"),
    "image.webp_encode": (1, "webp_input_and_container_preparation"),
    "image.webp_encode_or_fallback": (2, "fallback_png_input_preparation"),
    "native.validate_current": (3, "final_native_compare_python"),
    "browser.Locator.count": (4, "other_browser_controls"),
    "browser.Locator.evaluate": (4, "other_browser_controls"),
}
CAPTURE_GROUPS = {
    "native_trace_rpc": ["native_trace_rpc"],
    "native_trace_json_decode": ["native_trace_json_decode"],
    "reader_and_controls": ["reader_rpc", "other_browser_controls"],
    "source_body": ["source_body"],
    "source_jpeg_validation": ["source_jpeg_validation"],
    "replay_rpc_including_browser_png": ["replay_rpc_including_browser_png"],
    "white_composite_rgb_png": ["white_composite_rgb_png"],
    "png_and_codec_preparation": ["fallback_png_validation",
                                  "fallback_png_input_preparation",
                                  "webp_input_and_container_preparation"],
    "webp_encode": ["webp_encode"],
    "webp_roundtrip": ["webp_roundtrip_convert", "webp_roundtrip_tobytes"],
    "final_format_and_native_compare": ["final_format_validation",
                                        "final_native_compare_python"],
    "other_capture": ["other_capture"],
}


def stats(values: list[float]) -> dict[str, float | int]:
    seq = sorted(values)
    return {"n": len(seq), "mean_s": statistics.mean(seq),
            "median_s": statistics.median(seq),
            "p90_s": seq[math.ceil(.9 * len(seq)) - 1], "max_s": seq[-1]}


def partition(events: list[dict], start: float, end: float, mapping: dict,
              residual: str) -> dict[str, float]:
    spans = []
    for row in events:
        if row["stage"] not in mapping:
            continue
        a, b = max(start, row["start_s"]), min(end, row["end_s"])
        if b <= a:
            continue
        spec = mapping[row["stage"]]
        priority, name = spec if isinstance(spec, tuple) else (0, spec)
        spans.append((a, b, priority, name))
    boundaries = sorted({start, end, *(x for a, b, _, _ in spans for x in (a, b))})
    result = dict.fromkeys([residual, *(s[3] for s in spans)], 0.0)
    for a, b in pairwise(boundaries):
        mid = (a + b) / 2
        active = [(p, label) for left, right, p, label in spans if left <= mid < right]
        name = min(active)[1] if active else residual
        result[name] += b - a
    if abs(sum(result.values()) - (end - start)) > 1e-8:
        raise ValueError("Non-conserving partition")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_root", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument(
        "--without-replay-js", action="store_true",
        help="Require no injected replay JS timings; report Python spans only",
    )
    parser.add_argument(
        "--run-dirs", nargs="+",
        default=["20261010_full_profile_01/run-1", "20261010_full_profile_02/run-1"],
        help="Run directories relative to output_root; each must have eleven complete cycles",
    )
    args = parser.parse_args()
    if args.report.exists():
        raise FileExistsError("Refusing to overwrite derived evidence")
    rows = []
    for run in args.run_dirs:
        data = json.loads((args.output_root / run / "timings.json").read_text())
        events = data["events"]
        cycles = [e for e in events if e["stage"] == "page.capture_start_to_capture_start"]
        if len(cycles) != 11:
            raise ValueError("Expected eleven complete cycles")
        for cycle in cycles:
            start, end = cycle["start_s"], cycle["end_s"]
            captures = [e for e in events if e["stage"] == "runner.capture_page"
                        and start - 1e-5 <= e["start_s"] < end - 1e-5]
            if len(captures) != 1:
                raise ValueError("Expected one capture per complete cycle")
            capture = captures[0]
            lo, hi = capture["start_s"], capture["end_s"]
            trace_rows = [e for e in events if e["stage"] == "browser.snapshot_evaluate"
                          and lo <= e["start_s"] and e["end_s"] <= hi]
            if len(trace_rows) != 6:
                raise ValueError("Expected six full native snapshots")
            capture_parts = partition(events, lo, hi, CAPTURE, "other_capture")
            js = {}
            for label in ("jpeg_decode_ms", "draw_408_ms", "png_encode_ms"):
                found = [e for e in events if e["stage"] == f"browser.js.{label}"
                         and e.get("page_index") == cycle["page_index"]]
                if args.without_replay_js:
                    if found:
                        raise ValueError("Unexpected injected replay JS timings")
                    continue
                if len(found) != 1:
                    raise ValueError("Expected one JS duration for each replay stage")
                js[label.removesuffix("_ms")] = found[0]["wall_s"]
            if not args.without_replay_js:
                js["replay_rpc_residual"] = (
                    capture_parts["replay_rpc_including_browser_png"] - sum(js.values())
                )
            rows.append({"run": run, "page": cycle["page_index"],
                         "cycle_wall_s": end - start,
                         "capture_cpu_s": capture["cpu_s"],
                         "top": partition(events, start, end, TOP, "other_gap"),
                         "capture": capture_parts,
                         "capture_groups": {
                             name: sum(capture_parts.get(k, 0) for k in keys)
                             for name, keys in CAPTURE_GROUPS.items()},
                         "replay_js": js,
                         "full_trace_count": len(trace_rows)})
    summary = {}
    for kind in ("first", "normal"):
        selected = [r for r in rows if (r["page"] == 1) == (kind == "first")]
        summary[kind] = {"cycle": stats([r["cycle_wall_s"] for r in selected]),
                         "capture_cpu": stats([r["capture_cpu_s"] for r in selected])}
        for key in ("top", "capture", "capture_groups", "replay_js"):
            names = sorted({name for r in selected for name in r[key]})
            summary[kind][key] = {name: stats([r[key].get(name, 0) for r in selected])
                                  for name in names}
    report = {"scope": f"{len(args.run_dirs)} runs, complete p1..p11 cycles; p12 partial excluded",
              "replay_js_instrumented": not args.without_replay_js,
              "method": "Atomize measured Python intervals; specific children override parents. Browser JS synthetic spans excluded. Capture children partition capture only and are not added to top capture again.",
              "summary": summary, "rows": rows}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
