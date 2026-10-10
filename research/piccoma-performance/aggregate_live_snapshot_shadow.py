"""Aggregate sanitized final live snapshot-shadow reports into JSON/CSV."""

from __future__ import annotations

import csv
import json
import math
import statistics
from pathlib import Path
from typing import Any

BASE = Path(__file__).parent / "measurements"


def _stats(values: list[float]) -> dict[str, float | int]:
    ordered = sorted(values)
    return {
        "n": len(ordered),
        "mean_s": statistics.mean(ordered),
        "median_s": statistics.median(ordered),
        "p90_s": ordered[math.ceil(0.9 * len(ordered)) - 1],
        "max_s": max(ordered),
    }


def _validate_stable_report(data: dict[str, Any], label: str) -> None:
    for stage in ("reader", "trace"):
        block = data[stage]
        pair_flags = block.get("per_pair_stable")
        if not isinstance(pair_flags, list) or not pair_flags or not all(pair_flags):
            raise RuntimeError(f"{label} {stage} contains an unstable or unverified pair")
        unstable_count = block.get("unstable_pairs", block.get("unstable_pairs_excluded"))
        if unstable_count != 0:
            raise RuntimeError(f"{label} {stage} reports unstable pairs")
        pairs_checked = block.get("pairs_checked", block.get("snapshot_count_per_variant"))
        if pairs_checked != len(pair_flags):
            raise RuntimeError(f"{label} {stage} pair count does not match stable flags")


def _run_summary(label: str, data: dict[str, Any]) -> dict[str, Any]:
    trace = data["trace"]
    trace_matches = trace.get(
        "projection_matches_on_stable_pairs",
        trace.get("full_compact_projection_matches"),
    )
    reader_matches = data["reader"].get(
        "projection_matches_on_stable_pairs",
        data["reader"].get("full_compact_projection_matches"),
    )
    json_rows = trace["json_string_rows"]
    return {
        "run": label,
        "runner_error_type": data["runner_error_type"],
        "fresh_free_preflight_completed": data["fresh_free_preflight_completed"],
        "reader_pairs_checked": data["reader"].get("pairs_checked", len(data["reader"]["per_pair_stable"])),
        "reader_projection_matches_on_stable_pairs": reader_matches,
        "trace_pairs_checked": trace.get("pairs_checked", len(trace["per_pair_stable"])),
        "trace_projection_matches_on_stable_pairs": trace_matches,
        "trace_string_deep_equal_n": trace["json_string_full_deep_equality_count"],
        "trace_string_deep_equal_total": trace["json_string_full_deep_equality_n"],
        "trace_unstable_pairs": trace.get(
            "unstable_pairs", trace.get("unstable_pairs_excluded")
        ),
        "trace_evaluate_plus_json_loads_wall": _stats([
            row["wall_s"] + row["python_json_loads_wall_s"] for row in json_rows
        ]),
        "draw_count": trace["full_vs_compact"]["full"]["draw_counts"][0],
        "tile_trace_validation_reason": trace["tile_trace_validation_reason"],
        "white_paint_valid": trace["white_paint_valid"],
        "response_binding": trace["source_response_metadata"],
        "source_body_call_count": data["source_body_call_count"],
        "tile_replay_call_count": data["tile_replay_call_count"],
        "saved_page_count": data["runner_saved_page_count"],
        "trace_timing": {
            variant: trace["full_vs_compact"][variant]
            for variant in ("full", "compact", "json_string")
        },
    }


def main() -> None:
    reports = [("A", BASE / "live-shadow-final-a.json"),
               ("B", BASE / "live-shadow-final-b.json")]
    csv_rows: list[dict[str, Any]] = []
    output: dict[str, Any] = {
        "interpretation": {
            "payload_sizes": "UTF-8 JSON lengths, not CDP wire byte counts.",
            "wall_residual": "Wall minus browser execution and summary timers; includes stringify, transport, Playwright conversion and scheduling, not pure RPC.",
            "json_string_variant": "Same full snapshot and summary calculations, but return the entire trace as JSON text; Python json.loads is measured separately, and parsed object equality is checked in memory.",
            "capture_scope": "Read-only p1 metadata probe after fresh-free preflight; strict geometry guard blocked normal capture; no body read, replay, or save.",
            "ordering": "Each pair used fixed full, compact, json-string order; timing is observed, not a randomized causal comparison.",
        },
        "runs": [],
    }
    for label, path in reports:
        data = json.loads(path.read_text(encoding="utf-8"))
        _validate_stable_report(data, label)
        for stage in ("reader", "trace"):
            groups = data[stage]["full_vs_compact"]
            for variant, stats in groups.items():
                wall = stats["wall"]
                cpu = stats["cpu"]
                if stage == "reader":
                    returned_size = stats["payload_json_size"]["median_bytes"]
                elif variant == "compact":
                    returned_size = stats["compact_json_size"]["median_bytes"]
                elif variant == "json_string":
                    returned_size = stats["json_string_utf8_size"]["median_bytes"]
                else:
                    returned_size = stats["full_json_size"]["median_bytes"]
                row_group = (
                    data["reader"]["rows"] if stage == "reader" else
                    data["trace"][{
                        "full": "full_rows", "compact": "compact_rows",
                        "json_string": "json_string_rows",
                    }[variant]]
                )
                selected = [row for row in row_group if row["variant"] == variant]
                e2e = [
                    row["wall_s"] + row.get("python_json_loads_wall_s", 0.0)
                    for row in selected
                ]
                loads = stats.get("python_json_loads_wall", {})
                csv_rows.append({
                    "run": label,
                    "stage": stage,
                    "variant": variant,
                    "n": wall["n"],
                    "wall_mean_s": wall["mean_s"],
                    "wall_median_s": wall["median_s"],
                    "wall_p90_s": wall["p90_s"],
                    "wall_max_s": wall["max_s"],
                    "process_cpu_mean_s": cpu["mean_s"],
                    "browser_exec_median_ms": stats["browser_exec"]["median_ms"],
                    "summary_exec_median_ms": stats["summary_exec"]["median_ms"],
                    "returned_json_bytes_median": returned_size,
                    "python_json_loads_median_s": loads.get("median_s"),
                    "evaluate_plus_json_loads_wall_mean_s": statistics.mean(e2e),
                    "evaluate_plus_json_loads_wall_median_s": statistics.median(e2e),
                    "evaluate_plus_json_loads_wall_p90_s": sorted(e2e)[
                        math.ceil(0.9 * len(e2e)) - 1
                    ],
                    "evaluate_plus_json_loads_wall_max_s": max(e2e),
                    "projection_matches_on_stable_pairs": data[stage].get(
                        "projection_matches_on_stable_pairs",
                        data[stage].get("full_compact_projection_matches"),
                    ),
                    "pairs_checked": data[stage].get(
                        "pairs_checked", len(data[stage]["per_pair_stable"])
                    ),
                    "json_string_deep_equal_n": (
                        data["trace"]["json_string_full_deep_equality_count"]
                        if stage == "trace" else None
                    ),
                    "unstable_pairs": data[stage].get(
                        "unstable_pairs", data[stage].get("unstable_pairs_excluded")
                    ),
                })
        output["runs"].append(_run_summary(label, data))

    fields = list(csv_rows[0])
    with (BASE / "live-shadow-final-summary.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(csv_rows)
    (BASE / "live-shadow-final-summary.json").write_text(
        json.dumps(output, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
