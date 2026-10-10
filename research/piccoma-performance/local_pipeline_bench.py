"""Benchmark unchanged Piccoma Pillow helpers on existing verified WebP pixels.

All archive bytes and reconstructed pixels stay in memory. The replay PNG is
an opaque RGBA surrogate built from already-composited RGB because the original
browser replay PNG is not retained in the approved evidence set.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import math
import statistics
import time
import zipfile
from pathlib import Path
from typing import Any

from PIL import Image

from screenshot_crawler.core.capture import CaptureResult
from screenshot_crawler.site_adapters.piccoma import native_capture


def _exact_vp8l(data: bytes, width: int, height: int) -> bool:
    return native_capture._has_single_lossless_vp8l_chunk(
        data, width=width, height=height
    )


def _sample_pixels(archive: Path, manifest_path: Path, page_limit: int) -> list[dict[str, Any]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pages = sorted(manifest.get("pages", []), key=lambda row: row.get("sequence", 0))
    selected = pages[:page_limit]
    samples = []
    with zipfile.ZipFile(archive) as zip_file:
        names = zip_file.namelist()
        for page in selected:
            metadata = page.get("metadata", {}).get("piccoma_capture", {})
            if (
                page.get("file_extension") != ".webp"
                or metadata.get("method") != "native_tile_replay_lossless_webp"
                or metadata.get("source_native") is not True
                or metadata.get("output_lossless") is not True
            ):
                raise RuntimeError("Source manifest does not prove native lossless WebP")
            leaf = Path(page["file"]).name
            members = [name for name in names if Path(name).name == leaf]
            if len(members) != 1:
                raise RuntimeError("Archive member mapping is missing or ambiguous")
            payload = zip_file.read(members[0])
            with Image.open(io.BytesIO(payload)) as image:
                image.load()
                width, height = image.size
                if (
                    image.format != "WEBP"
                    or image.mode != "RGB"
                    or image.n_frames != 1
                    or not _exact_vp8l(payload, width, height)
                ):
                    raise RuntimeError("Archive input failed lossless RGB WebP checks")
                rgb = image.tobytes()
            png_buffer = io.BytesIO()
            with Image.frombytes("RGB", (width, height), rgb) as source:
                rgba = source.convert("RGBA")
                rgba.save(png_buffer, format="PNG")
            samples.append({
                "sequence": page["sequence"],
                "width": width,
                "height": height,
                "rgb": rgb,
                "replay_png": png_buffer.getvalue(),
                "source_bytes": len(payload),
            })
    if len(samples) != page_limit:
        raise RuntimeError("Archive did not contain the requested number of samples")
    return samples


async def _run_benchmark(
    samples: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, float | int]]]:
    rows: list[dict[str, Any]] = []
    loop = asyncio.get_running_loop()
    heartbeat: dict[str, float | int] = {"max_lag_s": 0.0, "ticks": 0}
    lag_events: list[dict[str, float | int]] = []
    current = {"run": 0, "sequence": 0}
    stop = asyncio.Event()
    origin = time.perf_counter()

    async def beat() -> None:
        interval = 0.05
        target = loop.time() + interval
        while not stop.is_set():
            await asyncio.sleep(interval)
            now = loop.time()
            lag = max(0.0, now - target)
            heartbeat["ticks"] = int(heartbeat["ticks"]) + 1
            heartbeat["max_lag_s"] = max(float(heartbeat["max_lag_s"]), lag)
            if lag >= 0.005:
                lag_events.append({
                    "run": current["run"], "sequence": current["sequence"],
                    "start_s": now - origin - lag, "end_s": now - origin,
                    "lag_s": lag,
                })
            target = now + interval

    task = asyncio.create_task(beat())
    try:
        for run_index in (1, 2):
            for sample in samples:
                current.update({"run": run_index, "sequence": sample["sequence"]})
                width, height = sample["width"], sample["height"]
                wall_start, cpu_start = time.perf_counter(), time.process_time()
                rgb_png = native_capture.composite_replay_png_on_white(
                    sample["replay_png"], width=width, height=height
                )
                rows.append({
                    "run": run_index, "sequence": sample["sequence"],
                    "page_class": "first" if sample["sequence"] == 1 else "normal",
                    "pipeline": "production_png_intermediate",
                    "stage": "png_white_composite",
                    "wall_s": time.perf_counter() - wall_start,
                    "cpu_s": time.process_time() - cpu_start,
                    "start_s": wall_start - origin,
                    "end_s": time.perf_counter() - origin,
                    "input_bytes": len(sample["replay_png"]),
                    "output_bytes": len(rgb_png),
                })
                await asyncio.sleep(0.06)

                wall_start, cpu_start = time.perf_counter(), time.process_time()
                encoded, fallback_reason = native_capture.encode_lossless_webp_or_png(
                    rgb_png, width=width, height=height
                )
                helper_wall_s = time.perf_counter() - wall_start
                helper_cpu_s = time.process_time() - cpu_start
                if fallback_reason is not None or encoded.mime_type != "image/webp":
                    raise RuntimeError("Production helper used a WebP fallback")
                rows.append({
                    "run": run_index, "sequence": sample["sequence"],
                    "page_class": "first" if sample["sequence"] == 1 else "normal",
                    "pipeline": "production_png_intermediate",
                    "stage": "webp_method6_with_fallback_png_validation_and_exact_decode",
                    "wall_s": helper_wall_s,
                    "cpu_s": helper_cpu_s,
                    "start_s": wall_start - origin,
                    "end_s": time.perf_counter() - origin,
                    "input_bytes": len(rgb_png), "output_bytes": len(encoded.data),
                })
                await asyncio.sleep(0.06)

                capture = CaptureResult(
                    encoded.data, width, height, "image/webp", ".webp"
                )
                wall_start, cpu_start = time.perf_counter(), time.process_time()
                valid = native_capture.capture_result_format_is_valid(
                    capture, width=width, height=height
                )
                if not valid:
                    raise RuntimeError("Final production format revalidation failed")
                rows.append({
                    "run": run_index, "sequence": sample["sequence"],
                    "page_class": "first" if sample["sequence"] == 1 else "normal",
                    "pipeline": "production_png_intermediate",
                    "stage": "adapter_final_format_redecode_validation",
                    "wall_s": time.perf_counter() - wall_start,
                    "cpu_s": time.process_time() - cpu_start,
                    "start_s": wall_start - origin,
                    "end_s": time.perf_counter() - origin,
                    "input_bytes": len(encoded.data), "output_bytes": len(encoded.data),
                })
                await asyncio.sleep(0.06)

                # Experimental candidate: composite the same replay PNG into
                # white RGB in memory, pass RGB bytes to Pillow, and avoid the
                # post-composite PNG encode + later PNG decode. No production
                # helper or source image is altered.
                direct_composite_start = time.perf_counter()
                direct_composite_cpu = time.process_time()
                with Image.open(io.BytesIO(sample["replay_png"])) as replay:
                    if replay.format != "PNG" or replay.size != (width, height):
                        raise RuntimeError("Direct-RGB replay surrogate validation failed")
                    replay.load()
                    rgba = replay.convert("RGBA")
                background = Image.new("RGBA", (width, height), (255, 255, 255, 255))
                background.alpha_composite(rgba)
                direct_rgb = background.convert("RGB").tobytes()
                direct_composite_wall = time.perf_counter() - direct_composite_start
                direct_composite_cpu_s = time.process_time() - direct_composite_cpu
                if direct_rgb != sample["rgb"]:
                    raise RuntimeError("Direct-RGB white composite changed source RGB pixels")
                rows.append({
                    "run": run_index, "sequence": sample["sequence"],
                    "page_class": "first" if sample["sequence"] == 1 else "normal",
                    "pipeline": "experimental_direct_rgb",
                    "stage": "white_composite_to_rgb_bytes",
                    "wall_s": direct_composite_wall,
                    "cpu_s": direct_composite_cpu_s,
                    "start_s": direct_composite_start - origin,
                    "end_s": time.perf_counter() - origin,
                    "input_bytes": len(sample["replay_png"]),
                    "output_bytes": len(direct_rgb),
                })
                await asyncio.sleep(0.06)

                direct_encode_start = time.perf_counter()
                direct_encode_cpu = time.process_time()
                direct_buffer = io.BytesIO()
                with Image.frombytes("RGB", (width, height), direct_rgb) as image:
                    image.save(direct_buffer, format="WEBP", lossless=True, method=6)
                direct_bytes = direct_buffer.getvalue()
                if direct_rgb != sample["rgb"] or not _exact_vp8l(direct_bytes, width, height):
                    raise RuntimeError("Direct-RGB candidate failed native pixel/container proof")
                with Image.open(io.BytesIO(direct_bytes)) as decoded:
                    decoded.load()
                    if decoded.format != "WEBP" or decoded.tobytes() != direct_rgb:
                        raise RuntimeError("Direct-RGB candidate round trip changed RGB pixels")
                direct_capture = CaptureResult(
                    direct_bytes, width, height, "image/webp", ".webp"
                )
                direct_encode_wall = time.perf_counter() - direct_encode_start
                direct_encode_cpu_s = time.process_time() - direct_encode_cpu
                rows.append({
                    "run": run_index, "sequence": sample["sequence"],
                    "page_class": "first" if sample["sequence"] == 1 else "normal",
                    "pipeline": "experimental_direct_rgb",
                    "stage": "webp_method6_encode_vp8l_exact_decode",
                    "wall_s": direct_encode_wall,
                    "cpu_s": direct_encode_cpu_s,
                    "start_s": direct_encode_start - origin,
                    "end_s": time.perf_counter() - origin,
                    "input_bytes": len(sample["replay_png"]),
                    "output_bytes": len(direct_bytes),
                })
                await asyncio.sleep(0.06)
                direct_valid_start, direct_cpu_start = time.perf_counter(), time.process_time()
                if not native_capture.capture_result_format_is_valid(
                    direct_capture, width=width, height=height
                ):
                    raise RuntimeError("Direct-RGB final adapter validation failed")
                rows.append({
                    "run": run_index, "sequence": sample["sequence"],
                    "page_class": "first" if sample["sequence"] == 1 else "normal",
                    "pipeline": "experimental_direct_rgb",
                    "stage": "adapter_final_format_redecode_validation",
                    "wall_s": time.perf_counter() - direct_valid_start,
                    "cpu_s": time.process_time() - direct_cpu_start,
                    "start_s": direct_valid_start - origin,
                    "end_s": time.perf_counter() - origin,
                    "input_bytes": len(direct_bytes), "output_bytes": len(direct_bytes),
                })
                await asyncio.sleep(0.06)
    finally:
        stop.set()
        await asyncio.gather(task, return_exceptions=True)
    return rows, heartbeat, lag_events


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("report_dir", type=Path)
    parser.add_argument("--pages", type=int, default=12)
    args = parser.parse_args()
    args.report_dir.mkdir(parents=True, exist_ok=True)
    samples = _sample_pixels(args.archive, args.manifest, args.pages)
    rows, heartbeat, lag_events = asyncio.run(_run_benchmark(samples))
    fields = list(rows[0])
    with (args.report_dir / "local_pipeline_pages.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    grouped = []
    groups = sorted({(str(row["pipeline"]), str(row["stage"])) for row in rows})
    for run_index in (1, 2):
        for page_class in ("first", "normal"):
            for pipeline, stage in groups:
                selected = [
                    row for row in rows
                    if row["run"] == run_index
                    and row["page_class"] == page_class
                    and row["pipeline"] == pipeline
                    and row["stage"] == stage
                ]
                if not selected:
                    continue
                walls = sorted(float(row["wall_s"]) for row in selected)
                cpus = sorted(float(row["cpu_s"]) for row in selected)
                grouped.append({
                    "run": run_index,
                    "page_class": page_class,
                    "pipeline": pipeline,
                    "stage": stage,
                    "n": len(selected),
                    "wall_median_s": statistics.median(walls),
                    "wall_p90_s": walls[math.ceil(0.9 * len(walls)) - 1],
                    "wall_max_s": max(walls),
                    "cpu_median_s": statistics.median(cpus),
                    "cpu_p90_s": cpus[math.ceil(0.9 * len(cpus)) - 1],
                    "bytes_in_total": sum(int(row["input_bytes"]) for row in selected),
                    "bytes_out_total": sum(int(row["output_bytes"]) for row in selected),
                })
    summary = {
        "pages_per_run": args.pages,
        "run_count": 2,
        "validated_native_webp_inputs": len(samples),
        "surrogate_replay_png_is_opaque_rgba": True,
        "stage_wall_equals_sync_event_loop_blocking_time": True,
        "roundtrip_rgb_exact_all": True,
        "adapter_final_validation_all": True,
        "heartbeat_interval_s": 0.05,
        "heartbeat_ticks": heartbeat["ticks"],
        "heartbeat_max_lag_s": heartbeat["max_lag_s"],
        "heartbeat_lag_events": lag_events,
        "stages": grouped,
    }
    (args.report_dir / "local_pipeline_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
