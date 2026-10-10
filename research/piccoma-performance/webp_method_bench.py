"""Compare Pillow lossless WebP methods on isolated source-derived output."""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import statistics
import time
from pathlib import Path

from PIL import Image, features

from screenshot_crawler.site_adapters.piccoma.native_capture import (
    _has_single_lossless_vp8l_chunk,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_root", type=Path)
    parser.add_argument("report_dir", type=Path)
    parser.add_argument("--sample", type=Path, action="append", default=[])
    parser.add_argument("--limit", type=int, default=4)
    parser.add_argument("--repeats", type=int, default=4)
    args = parser.parse_args()
    report_rows: list[dict[str, object]] = []
    samples = args.sample or sorted(args.output_root.rglob("page-*.webp"))[: args.limit]
    if not samples:
        raise SystemExit("No isolated lossless WebP output pages were found")
    methods = (0, 3, 4, 6)
    if args.repeats < 1:
        raise SystemExit("--repeats must be positive")
    if args.report_dir.exists() and any(args.report_dir.iterdir()):
        raise SystemExit("Refusing to overwrite a non-empty report directory")
    args.report_dir.mkdir(parents=True, exist_ok=True)
    for sample_index, path in enumerate(samples, start=1):
        encoded = path.read_bytes()
        with Image.open(io.BytesIO(encoded)) as source:
            source.load()
            if (
                source.format != "WEBP"
                or source.mode != "RGB"
                or source.n_frames != 1
                or not _has_single_lossless_vp8l_chunk(
                    encoded, width=source.width, height=source.height
                )
            ):
                raise RuntimeError(f"Rejected non-RGB/single-frame sample {sample_index + 1}")
            rgb = source.tobytes()
            size = source.size

        # Warm each codec path once on the exact same pixels; exclude warmup.
        for method in methods:
            warmup = io.BytesIO()
            with Image.frombytes("RGB", size, rgb) as image:
                image.save(warmup, format="WEBP", lossless=True, method=method)

        for repeat in range(args.repeats):
            shift = (sample_index - 1 + repeat) % len(methods)
            order = methods[shift:] + methods[:shift]
            for order_index, method in enumerate(order):
                output = io.BytesIO()
                started = time.perf_counter()
                with Image.frombytes("RGB", size, rgb) as image:
                    image.save(output, format="WEBP", lossless=True, method=method)
                encode_s = time.perf_counter() - started
                result = output.getvalue()
                started = time.perf_counter()
                valid_container = _has_single_lossless_vp8l_chunk(
                    result, width=size[0], height=size[1]
                )
                with Image.open(io.BytesIO(result)) as decoded:
                    decoded.load()
                    exact = (
                        decoded.format == "WEBP"
                        and decoded.mode == "RGB"
                        and decoded.size == size
                        and decoded.n_frames == 1
                        and decoded.tobytes() == rgb
                    )
                verify_s = time.perf_counter() - started
                if not valid_container or not exact:
                    raise RuntimeError(
                        f"Lossless method {method} failed VP8L or exact RGB validation"
                    )
                report_rows.append({
                    "sample": sample_index,
                    "sample_source": path.name,
                    "width": size[0],
                    "height": size[1],
                    "method": method,
                    "repeat": repeat + 1,
                    "order_index": order_index + 1,
                    "encode_s": encode_s,
                    "verify_s": verify_s,
                    "bytes": len(result),
                    "source_output_bytes": len(encoded),
                    "single_vp8l": valid_container,
                    "rgb_exact": exact,
                })
    csv_path = args.report_dir / "webp_methods.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(report_rows[0]))
        writer.writeheader()
        writer.writerows(report_rows)
    summary: dict[str, object] = {
        "webp_supported": features.check("webp"),
        "samples": len(samples),
        "sample_names": [path.name for path in samples],
        "methods": list(methods),
        "warmups_per_method_per_sample": 1,
        "balanced_order": True,
        "repeats_per_method_per_sample": args.repeats,
        "rows": [],
    }
    summaries = []
    for method in methods:
        rows = [row for row in report_rows if row["method"] == method]
        encode_times = [float(row["encode_s"]) for row in rows]
        verify_times = [float(row["verify_s"]) for row in rows]
        sizes = [int(row["bytes"]) for row in rows]
        summaries.append({
            "method": method,
            "n": len(rows),
            "encode_mean_s": statistics.mean(encode_times),
            "encode_median_s": statistics.median(encode_times),
            "encode_p90_s": sorted(encode_times)[math.ceil(0.9 * len(encode_times)) - 1],
            "encode_max_s": max(encode_times),
            "verify_median_s": statistics.median(verify_times),
            "mean_bytes": statistics.mean(sizes),
            "median_bytes": statistics.median(sizes),
            "all_single_vp8l": all(row["single_vp8l"] for row in rows),
            "all_rgb_exact": all(row["rgb_exact"] for row in rows),
        })
    summary["rows"] = summaries
    (args.report_dir / "webp_methods.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
