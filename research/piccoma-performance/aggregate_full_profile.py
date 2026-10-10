"""Aggregate isolated full-profile run timings into sanitized JSON/CSV."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from pathlib import Path
from typing import Any

RUN_NAMES = ("20261010_full_profile_01", "20261010_full_profile_02")
STAGE_GROUPS = {
    "page_cycle_capture_start_to_next_capture_start": [
        "page.capture_start_to_capture_start",
    ],
    "fixed_pacing": ["runner.pacing"],
    "page_turn": [
        "adapter.go_next_total", "transition.next_click_dom_action",
        "adapter.wait_for_change_total", "transition.click_start_to_wait_complete",
        "transition.first_expected_id", "transition.first_loaded_snapshot",
        "transition.three_stable_snapshots",
    ],
    "page_state_and_canvas_proof": [
        "runner.detect_state", "runner.get_content_context",
        "runner.get_content_identity", "adapter.reader_snapshot",
        "native.snapshot_native_trace", "native.validate_current",
        "browser.snapshot_evaluate", "browser.Locator.count",
    ],
    "source_jpeg_transfer_and_validation": [
        "browser.response_body", "image.source_jpeg_validation",
    ],
    "tile_replay_and_browser_png": [
        "browser.replay_evaluate", "browser.js.jpeg_decode_ms",
        "browser.js.draw_408_ms", "browser.js.png_encode_ms",
    ],
    "white_composite_and_rgb_png": [
        "image.png_decode_white_composite", "pillow.codec_decode.png",
        "pillow.save.png",
    ],
    "lossless_webp_encode_and_roundtrip": [
        "image.webp_encode_or_fallback", "image.webp_encode",
        "pillow.save.webp",
    ],
    "webp_roundtrip_and_decode": [
        "pillow.codec_decode.webp_roundtrip",
        "pillow.convert.webp_to_RGB", "pillow.tobytes.memory.inside_webp_encode",
    ],
    "final_validation_and_commit": [
        "image.final_format_validation", "image.webp_fallback_png_validation",
        "image.webp_encoder_output_validation", "core.save_capture",
        "core.manifest_progress_write", "pillow.codec_decode.webp_final_validation",
    ],
}


def _stats(values: list[float]) -> dict[str, float | int] | None:
    if not values:
        return None
    ordered = sorted(values)
    return {
        "n": len(ordered),
        "mean_s": statistics.mean(ordered),
        "median_s": statistics.median(ordered),
        "p90_s": ordered[math.ceil(0.9 * len(ordered)) - 1],
        "max_s": max(ordered),
    }


def _page_class(page_index: Any) -> str:
    return "first" if page_index == 1 else "normal"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_root", type=Path)
    parser.add_argument("report_dir", type=Path)
    parser.add_argument(
        "--run-name", action="append", dest="run_names",
        help="Isolated run directory name; repeat once per run (defaults to baseline names)",
    )
    parser.add_argument(
        "--run-dirs", nargs="+", type=Path,
        help="Run directories relative to output_root, each containing timings.json and run_result.json",
    )
    args = parser.parse_args()
    if args.report_dir.exists() and any(args.report_dir.iterdir()):
        raise SystemExit("Refusing to overwrite a non-empty aggregate report directory")
    args.report_dir.mkdir(parents=True, exist_ok=True)

    run_data: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    run_summaries: list[dict[str, Any]] = []
    if args.run_dirs:
        run_specs = [(path.as_posix().replace("/", "_"), args.output_root / path)
                     for path in args.run_dirs]
    else:
        run_specs = [(name, args.output_root / name / "run-1")
                     for name in args.run_names or RUN_NAMES]
    for run_name, run_root in run_specs:
        timing = json.loads((run_root / "timings.json").read_text(encoding="utf-8"))
        result = json.loads((run_root / "run_result.json").read_text(encoding="utf-8"))
        if (
            result.get("saved_pages") != 12
            or result.get("native_webp_pages") != 12
            or result.get("fallback_pages") != 0
            or result.get("terminal") != "max_pages_exceeded_bounded_probe_not_end"
        ):
            raise RuntimeError(f"{run_name} did not meet the expected bounded native-only result")
        events = timing.get("events", [])
        run_data.append({"name": run_name, "timing": timing, "result": result, "events": events})
        event_counts = timing.get("counts", {})
        encode_parents = [event for event in events
                          if event.get("stage") == "image.webp_encode"]
        final_parents = [event for event in events
                         if event.get("stage") == "image.final_format_validation"]
        normalized_events = []
        for event in events:
            stage = str(event.get("stage", "unknown"))
            page_index = event.get("page_index")
            normalized_stage = stage
            if stage == "pillow.codec_decode.webp":
                start_s, end_s = float(event["start_s"]), float(event["end_s"])
                if any(
                    parent.get("page_index") == page_index
                    and float(parent["start_s"]) <= start_s
                    and end_s <= float(parent["end_s"])
                    for parent in encode_parents
                ):
                    normalized_stage = "pillow.codec_decode.webp_roundtrip"
                elif any(
                    parent.get("page_index") == page_index
                    and float(parent["start_s"]) <= start_s
                    and end_s <= float(parent["end_s"])
                    for parent in final_parents
                ):
                    normalized_stage = "pillow.codec_decode.webp_final_validation"
            normalized = {**event, "profile_stage": normalized_stage}
            normalized_events.append(normalized)
            event_rows.append({
                "run": run_name,
                "page_class": _page_class(page_index),
                "page_index": page_index,
                "stage": stage,
                "profile_stage": normalized_stage,
                "wall_s": event.get("wall_s"),
                "cpu_s": event.get("cpu_s"),
                "bytes": event.get("bytes"),
                "passed": event.get("passed"),
                "method": event.get("method"),
                "timestamp_basis": event.get(
                    "timestamp_basis",
                    "duration_only_after_evaluate_return"
                    if stage.startswith("browser.js.") else "measured_span",
                ),
            })

        complete_cycles = [event for event in events
                           if event.get("stage") == "page.capture_start_to_capture_start"]
        if len(complete_cycles) != 11:
            raise RuntimeError(f"{run_name} expected 11 complete page cycles, got {len(complete_cycles)}")
        per_run_metrics: dict[str, Any] = {}
        for page_class in ("first", "normal"):
            per_run_metrics[page_class] = {}
            for group, stages in STAGE_GROUPS.items():
                selected = [event for event in normalized_events
                            if event.get("profile_stage") in stages
                            and _page_class(event.get("page_index")) == page_class]
                # The cycle period is the primary whole-page measure. All other
                # values are inclusive or nested spans and must not be summed.
                per_run_metrics[page_class][group] = {
                    "stages": {
                        stage: {
                            "wall": _stats([
                                float(event["wall_s"]) for event in selected
                                if event.get("profile_stage") == stage and isinstance(event.get("wall_s"), (int, float))
                            ]),
                            "cpu": _stats([
                                float(event["cpu_s"]) for event in selected
                                if event.get("profile_stage") == stage and isinstance(event.get("cpu_s"), (int, float))
                            ]),
                            "count": sum(event.get("profile_stage") == stage for event in selected),
                        }
                        for stage in stages
                    },
                    "inclusive_values_must_not_be_summed": True,
                }
        whole_run = next((event for event in events if event.get("stage") == "runner.whole_run"), {})
        heartbeat = next((event for event in events if event.get("stage") == "event_loop.heartbeat"), {})
        run_summaries.append({
            "run": run_name,
            "saved_pages": result["saved_pages"],
            "native_webp_pages": result["native_webp_pages"],
            "fallback_pages": result["fallback_pages"],
            "sequences": result["sequences"],
            "terminal": result["terminal"],
            "page_turn_delay_ms": result.get("page_turn_delay_ms"),
            "end_verified": False,
            "whole_run_wall_s": whole_run.get("wall_s"),
            "whole_run_cpu_s": whole_run.get("cpu_s"),
            "heartbeat_max_lag_s": heartbeat.get("max_lag_s"),
            "heartbeat_ticks": heartbeat.get("ticks"),
            "python_rss_final_mb": timing.get("rss_final_mb"),
            "python_rss_peak_mb": timing.get("rss_peak_mb"),
            "call_counts": {
                key: value for key, value in event_counts.items()
                if key.startswith(("browser.Page.", "browser.Locator."))
                or key in {"adapter.reader_snapshot", "native.snapshot_native_trace"}
            },
            "first_and_normal": per_run_metrics,
            "transition_milestone_anchor": (
                "wait_start; next click was separately timed but click marker unavailable"
                if run_name.endswith("_01") else "exact Locator.click start"
            ),
            "transition_reset_reasons": "not observed; no rect/style/viewport/backing change counter was installed",
            "progress_json_write": "one small numeric snapshot after p1 manifest commit; outside capture_page span",
            "shared_chrome_cpu_rss": "not measured; existing shared browser activity would be mixed",
        })

    output = {
        "measurement_scope": {
            "runs": len(run_data),
            "pages_per_run": 12,
            "max_pages_stop_is_not_end": True,
            "baseline": "source-native lossless WebP, method=6, full JSON object return",
            "shared_cdp": "9222; isolated uncredentialed browser context per run",
            "pacing_ms": run_data[0]["result"].get("page_turn_delay_ms"),
            "sample_source": "fresh-free viewer 28600/1910027; no paid resource",
        },
        "stage_interpretation": {
            "wall_cpu_units": "seconds",
            "percentile": "nearest-rank ceil(0.9*n)-1",
            "browser_js_timestamps": "durations from performance.now converted to seconds; old event start/end positions were return-relative, never use as interval boundaries",
            "nesting": "helper, save, codec decode and validation spans can be nested; listed values are inclusive measurements and must not be added",
            "capture_cycle": "capture_page start for page n to capture_page start for page n+1; 11 complete cycles/run; last-page-to-run-end is partial and excluded",
            "measurement_gap": "residual wall contains state/polling, CDP and scheduling not assigned to an exclusive child; progress-file write occurs after p1 commit",
        },
        "runs": run_summaries,
    }
    with (args.report_dir / "full-profile.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=list(event_rows[0]))
        writer.writeheader()
        writer.writerows(event_rows)
    (args.report_dir / "full-profile.json").write_text(
        json.dumps(output, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
