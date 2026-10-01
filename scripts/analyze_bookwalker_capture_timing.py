"""Summarize BookWalker capture timing without changing production behavior."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path
from typing import Any


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _stats(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"count": 0}
    ordered = sorted(values)
    p90_index = max(0, math.ceil(len(ordered) * 0.9) - 1)
    return {
        "count": len(values),
        "median": round(statistics.median(ordered), 2),
        "p90": round(ordered[p90_index], 2),
        "max": round(max(ordered), 2),
    }


def _capture_key(page: dict[str, Any]) -> str:
    identity = page.get("identity") or {}
    metadata = page.get("metadata") or {}
    shadow = (metadata.get("bookwalker_capture") or {}).get("lossless_shadow") or {}
    key = {
        "page_id": identity.get("page_id"),
        "page_number": identity.get("page_number", page.get("page_number")),
        "parts": metadata.get("parts"),
        "timing_ms": shadow.get("timing_ms") or {},
    }
    return json.dumps(key, sort_keys=True, separators=(",", ":"))


def _deduplicate_pages(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    captures: dict[str, dict[str, Any]] = {}
    for page in pages:
        captures.setdefault(_capture_key(page), page)
    return list(captures.values())


def _timing_records(captures: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    part_records: list[dict[str, Any]] = []
    for capture in captures:
        metadata = capture.get("metadata") or {}
        bookwalker = metadata.get("bookwalker_capture") or {}
        shadow = bookwalker.get("lossless_shadow") or {}
        parts = shadow.get("parts") or []
        part_records.extend(part for part in parts if isinstance(part, dict))
    return captures, part_records


def analyze(manifest: dict[str, Any]) -> dict[str, Any]:
    pages = [page for page in manifest.get("pages", []) if isinstance(page, dict)]
    captures, parts = _timing_records(_deduplicate_pages(pages))
    capture_metrics: dict[str, list[float]] = {}
    part_metrics: dict[str, list[float]] = {}
    reconstruction_metrics: dict[str, list[float]] = {}

    for capture in captures:
        metadata = capture.get("metadata") or {}
        bookwalker = metadata.get("bookwalker_capture") or {}
        capture_timing = bookwalker.get("timing_ms") or {}
        shadow = bookwalker.get("lossless_shadow") or {}
        evaluation_timing = shadow.get("timing_ms") or {}
        for name, value in capture_timing.items():
            number = _number(value)
            if number is not None:
                capture_metrics.setdefault(name, []).append(number)
        for name in (
            "evaluation_total",
            "trace_fetch_ms",
            "trace_decode_ms",
            "measured_component_total_ms",
            "unaccounted_ms",
        ):
            number = _number(evaluation_timing.get(name))
            if number is not None:
                capture_metrics.setdefault(name, []).append(number)

    for part in parts:
        timing = part.get("timing_ms") or {}
        signatures = (
            _number(timing.get("imagebitmap_signature_ms")) or 0.0
        ) + (_number(timing.get("candidate_signature_ms_total")) or 0.0)
        part_metrics.setdefault("signatures", []).append(signatures)
        for name in (
            "mapping_analysis_ms",
            "raw_full_resolution_compare_ms",
            "lossless_reconstruction_ms",
            "final_browser_pixel_compare_ms",
        ):
            number = _number(timing.get(name))
            if number is not None:
                part_metrics.setdefault(name, []).append(number)
        lossless_timing = part.get("lossless_timing_ms") or {}
        for name, value in lossless_timing.items():
            number = _number(value)
            if number is not None:
                reconstruction_metrics.setdefault(name, []).append(number)

    parts_by_capture: dict[str, int] = {}
    spread_count = 0
    for capture in captures:
        metadata = capture.get("metadata") or {}
        part_count = int(metadata.get("parts", 1) or 1)
        parts_by_capture[str(part_count)] = parts_by_capture.get(str(part_count), 0) + 1
        spread_count += int(part_count > 1)

    trace_rows = []
    for capture in captures:
        metadata = capture.get("metadata") or {}
        shadow = ((metadata.get("bookwalker_capture") or {}).get("lossless_shadow") or {})
        evaluation_timing = shadow.get("timing_ms") or {}
        trace_rows.append(
            {
                "page_id": (capture.get("identity") or {}).get("page_id"),
                "trace_fetch_ms": evaluation_timing.get("trace_fetch_ms"),
                "trace_fetch_mode": shadow.get("trace_fetch_mode"),
                "trace_decode_ms": evaluation_timing.get("trace_decode_ms"),
                "retained_mapping_count": shadow.get(
                    "trace_completed_mapping_count"
                ),
                "retained_tile_record_count": shadow.get(
                    "trace_completed_tile_record_count"
                ),
                "requested_mapping_count": shadow.get(
                    "trace_requested_mapping_count"
                ),
                "returned_mapping_count": shadow.get("trace_returned_mapping_count"),
                "returned_tile_record_count": shadow.get(
                    "trace_returned_tile_record_count"
                ),
                "missing_mapping_count": shadow.get("trace_missing_mapping_count"),
                "compact_source_table_count": shadow.get(
                    "trace_compact_source_table_count"
                ),
                "compact_target_table_count": shadow.get(
                    "trace_compact_target_table_count"
                ),
                "compact_transform_table_count": shadow.get(
                    "trace_compact_transform_table_count"
                ),
                "compact_composite_table_count": shadow.get(
                    "trace_compact_composite_table_count"
                ),
                "compact_filter_table_count": shadow.get(
                    "trace_compact_filter_table_count"
                ),
                # Compatibility aliases for the P4-1 report.
                "completed_mapping_count": shadow.get("trace_completed_mapping_count"),
                "completed_tile_record_count": shadow.get(
                    "trace_completed_tile_record_count"
                ),
                "active_segment_count": shadow.get("trace_active_segment_count"),
                "active_tile_record_count": shadow.get("trace_active_tile_record_count"),
                "dropped_completed_mapping_count": shadow.get(
                    "trace_dropped_completed_mapping_count"
                ),
                "dropped_active_segment_count": shadow.get(
                    "trace_dropped_active_segment_count"
                ),
            }
        )

    all_stage_metrics = {
        **capture_metrics,
        **part_metrics,
        **reconstruction_metrics,
    }
    excluded_totals = {
        "capture_total_ms",
        "lossless_evaluation_total_ms",
        "evaluation_total",
        "measured_component_total_ms",
        "capture_unaccounted_ms",
        "unaccounted_ms",
        "total_ms",
    }
    top_costs = sorted(
        (
            (name, statistics.median(values))
            for name, values in all_stage_metrics.items()
            if name not in excluded_totals and values
        ),
        key=lambda item: item[1],
        reverse=True,
    )[:5]
    return {
        "artifact_count": len(pages),
        "logical_capture_count": len(captures),
        "part_count": len(parts),
        "spread_count": spread_count,
        "logical_captures_by_parts": parts_by_capture,
        "capture_metrics": {name: _stats(values) for name, values in capture_metrics.items()},
        "part_metrics": {name: _stats(values) for name, values in part_metrics.items()},
        "reconstruction_metrics": {
            name: _stats(values) for name, values in reconstruction_metrics.items()
        },
        "top_5_median_costs_ms": [
            {"measurement": name, "median": round(value, 2)}
            for name, value in top_costs
        ],
        "trace_payload": {
            name: _stats(
                [
                    float(row[name])
                    for row in trace_rows
                    if isinstance(row[name], int)
                ]
            )
            for name in (
                "completed_mapping_count",
                "completed_tile_record_count",
                "active_segment_count",
                "active_tile_record_count",
                "dropped_completed_mapping_count",
                "dropped_active_segment_count",
                "retained_mapping_count",
                "retained_tile_record_count",
                "requested_mapping_count",
                "returned_mapping_count",
                "returned_tile_record_count",
                "missing_mapping_count",
                "compact_source_table_count",
                "compact_target_table_count",
                "compact_transform_table_count",
                "compact_composite_table_count",
                "compact_filter_table_count",
            )
        },
        "trace_rows": trace_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    print(json.dumps(analyze(manifest), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
