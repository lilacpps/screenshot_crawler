"""Comic DAYS JPEG coefficient-permutation feasibility PoC.

This is deliberately a research helper, not a production capture path.  It
consumes a bounded report produced from ``__comicDaysProductionCapture`` plus
source bytes fetched by that hook.  Source bytes and reconstructed images are
written only below an ignored output directory; the checked-in report contains
headers, hashes, geometry, and validation results.

The coefficient writer is reused from the Magapoke PoC as an experiment only.
Comic DAYS production code must not import Magapoke code until a later phase
has independently accepted the metadata-preservation result.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image

from screenshot_crawler.site_adapters.magapoke.native_capture import (
    _marker_payloads,
    _source_metadata_is_preserved,
    reconstruct_jpeg_png,
)

try:
    from poc.magapoke_lossless_jpeg import (
        _dct_arrays,
        _jpeg_dct,
        _pixel_difference,
        jpeg_markers,
        permute_coefficients,
    )
except ModuleNotFoundError:  # direct ``python poc/comicdays_lossless_jpeg.py``
    from magapoke_lossless_jpeg import (  # type: ignore[no-redef]
        _dct_arrays,
        _jpeg_dct,
        _pixel_difference,
        jpeg_markers,
        permute_coefficients,
    )
TILE_WIDTH = 280
TILE_HEIGHT = 400
TILE_COLUMNS = 4
TILE_ROWS = 4
TILE_BLOCK_WIDTH = TILE_WIDTH // 8
TILE_BLOCK_HEIGHT = TILE_HEIGHT // 8


def _draw_mapping(draw: dict[str, Any]) -> dict[str, Any]:
    """Convert one production hook draw into the PoC's strict mapping shape."""

    args = draw.get("args")
    source = draw.get("source") or {}
    if not isinstance(args, list) or len(args) != 8 or not isinstance(source, dict):
        raise ValueError("draw is missing an 8-value geometry or source")
    return {
        "sourcePath": draw.get("sourceUrl") or source.get("url"),
        "sourceWidth": source.get("width") or draw.get("canvasWidth"),
        "sourceHeight": source.get("height") or draw.get("canvasHeight"),
        "canvasWidth": draw.get("canvasWidth"),
        "canvasHeight": draw.get("canvasHeight"),
        "sx": args[0],
        "sy": args[1],
        "sw": args[2],
        "sh": args[3],
        "dx": args[4],
        "dy": args[5],
        "dw": args[6],
        "dh": args[7],
        "transform": [1, 0, 0, 1, 0, 0],
        "compositeOperation": "source-over",
        "filter": "none",
    }


def runtime_plan(row: dict[str, Any]) -> dict[str, Any]:
    """Build a strict source/generation-checked coefficient plan from a row.

    The production hook records a harmless spacer draw after the 16 tile draws;
    it is intentionally excluded only when it is outside the canvas and has a
    different source identity.  Any in-canvas source replacement or generation
    mismatch is rejected.
    """

    base = row.get("base")
    if not isinstance(base, dict):
        raise TypeError("missing base draw")
    source = base.get("source")
    source_id = base.get("sourceId")
    source_url = base.get("sourceUrl")
    base_sequence = base.get("sequence")
    if not isinstance(source, dict) or not source_id or not isinstance(source_url, str):
        raise ValueError("base source identity is incomplete")
    if not isinstance(base_sequence, int) or isinstance(base_sequence, bool):
        raise TypeError("base generation is not an integer sequence")
    width = int(base.get("canvasWidth") or 0)
    height = int(base.get("canvasHeight") or 0)
    dimensions = (int(source.get("width") or 0), int(source.get("height") or 0))
    if dimensions != (width, height) or width <= 0 or height <= 0:
        raise ValueError("source and canvas dimensions disagree")

    mappings: list[dict[str, Any]] = []
    for draw in row.get("mapping") or []:
        if not isinstance(draw, dict):
            raise TypeError("mapping contains a non-object draw")
        args = draw.get("args")
        same_source = draw.get("sourceId") == source_id and draw.get("sourceUrl") == source_url
        outside = (
            isinstance(args, list)
            and len(args) == 8
            and (args[4] + args[6] <= 0 or args[5] + args[7] <= 0
                 or args[4] >= width or args[5] >= height)
        )
        sequence = draw.get("sequence")
        if outside and not same_source:
            continue
        if not same_source:
            raise ValueError("in-canvas source identity replacement")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < base_sequence:
            raise ValueError("mapping generation precedes the selected base")
        mapping = _draw_mapping(draw)
        if any(not isinstance(value, int) or isinstance(value, bool) for value in args):
            raise ValueError("mapping geometry is not integer-valued")
        mappings.append(mapping)

    if len(mappings) != TILE_COLUMNS * TILE_ROWS:
        raise ValueError(f"expected 16 tile draws, got {len(mappings)}")
    tile_rects = [(item["sx"], item["sy"], item["sw"], item["sh"]) for item in mappings]
    destination_rects = [(item["dx"], item["dy"], item["dw"], item["dh"]) for item in mappings]
    if any(
        item["sw"] != TILE_WIDTH or item["sh"] != TILE_HEIGHT
        or item["dw"] != TILE_WIDTH or item["dh"] != TILE_HEIGHT
        for item in mappings
    ):
        raise ValueError("Comic DAYS tile geometry is not 280x400")
    if any(value % 8 for rect in tile_rects + destination_rects for value in rect):
        raise ValueError("tile geometry is not DCT-block aligned")
    if len(set(tile_rects)) != 16 or len(set(destination_rects)) != 16:
        raise ValueError("tile mapping is not bijective")
    tiled_width = TILE_WIDTH * TILE_COLUMNS
    tiled_height = TILE_HEIGHT * TILE_ROWS
    expected = {(x, y) for y in range(0, tiled_height, TILE_HEIGHT) for x in range(0, tiled_width, TILE_WIDTH)}
    if {(x, y) for x, y, _, _ in tile_rects} != expected or {(x, y) for x, y, _, _ in destination_rects} != expected:
        raise ValueError("tile mapping does not cover the complete 4x4 area")
    coded_width = ((width + 7) // 8) * 8
    coded_height = ((height + 7) // 8) * 8
    return {
        "source_id": source_id,
        "source_url": source_url,
        "base_sequence": base_sequence,
        "dimensions": [width, height],
        "coded_dimensions": [coded_width, coded_height],
        "tile_pixels": [TILE_WIDTH, TILE_HEIGHT],
        "tile_blocks": [TILE_BLOCK_WIDTH, TILE_BLOCK_HEIGHT],
        "tile_area_pixels": [tiled_width, tiled_height],
        "tile_area_blocks": [tiled_width // 8, tiled_height // 8],
        "untiled_right_edge_pixels": width - tiled_width,
        "untiled_right_edge_blocks": [coded_width // 8 - tiled_width // 8],
        "base": _draw_mapping(base),
        "mappings": mappings,
    }


def _array_hash(value: Any) -> str:
    return hashlib.sha256(value.tobytes()).hexdigest()


def _write_qt_sentinel(data: bytes, arrays: dict[str, Any]) -> bytes:
    """Write with jpeglib's ``qt=-1`` source-table sentinel for comparison."""

    dct, source_temp = _jpeg_dct(data)
    try:
        for name, array in arrays.items():
            getattr(dct, name)[...] = array
        dct.qt = -1
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as handle:
            output_path = Path(handle.name)
        try:
            dct.write_dct(str(output_path))
            return output_path.read_bytes()
        finally:
            output_path.unlink(missing_ok=True)
    finally:
        dct.close()
        source_temp.unlink(missing_ok=True)


def _qt_sentinel_experiment(
    source_bytes: bytes,
    expected: dict[str, Any],
    png_image: Image.Image | None,
) -> dict[str, Any]:
    """Check whether the jpeglib source-table sentinel preserves semantics."""

    output_bytes = _write_qt_sentinel(source_bytes, expected)
    source_dct, source_temp = _jpeg_dct(source_bytes)
    output_dct, output_temp = _jpeg_dct(output_bytes)
    try:
        observed = _dct_arrays(output_dct)
        coefficient_equal = all(
            name in observed and (observed[name] == value).all()
            for name, value in expected.items()
        )
        dct_semantics = {
            "dimensions_equal": (int(source_dct.width), int(source_dct.height))
            == (int(output_dct.width), int(output_dct.height)),
            "sampling_equal": source_dct.samp_factor.tolist() == output_dct.samp_factor.tolist(),
            "quantization_equal": bool((source_dct.qt == output_dct.qt).all()),
            "quant_table_numbers_equal": source_dct.quant_tbl_no.tolist()
            == output_dct.quant_tbl_no.tolist(),
            "colorspace_equal": getattr(source_dct, "jpeg_color_space", None)
            == getattr(output_dct, "jpeg_color_space", None),
            "progressive_equal": bool(getattr(source_dct, "progressive_mode", False))
            == bool(getattr(output_dct, "progressive_mode", False)),
        }
    finally:
        source_dct.close()
        source_temp.unlink(missing_ok=True)
        output_dct.close()
        output_temp.unlink(missing_ok=True)
    output_image = Image.open(io.BytesIO(output_bytes)).convert("RGB")
    source_markers = jpeg_markers(source_bytes)
    output_markers = jpeg_markers(output_bytes)
    metadata = {
        "component_ids_equal": [item["id"] for item in source_markers["components"]]
        == [item["id"] for item in output_markers["components"]],
        "sampling_equal": source_markers["components"] == output_markers["components"],
        "quantization_segments_byte_equal": _marker_payloads(source_bytes, 0xDB)
        == _marker_payloads(output_bytes, 0xDB),
        "dht_segments_byte_equal": _marker_payloads(source_bytes, 0xC4)
        == _marker_payloads(output_bytes, 0xC4),
        "restart_interval_equal": source_markers["restart_interval"] == output_markers["restart_interval"],
        "appn_com_payloads_preserved": _source_metadata_is_preserved(source_bytes, output_bytes),
    }
    pixel_difference = (
        _pixel_difference(png_image, output_image) if png_image is not None else None
    )
    semantic_ok = (
        coefficient_equal
        and all(value for key, value in metadata.items() if key != "dht_segments_byte_equal")
        and all(dct_semantics.values())
        and (pixel_difference is None or pixel_difference["different_pixel_count"] == 0)
    )
    return {
        "status": "semantic_candidate" if semantic_ok else "rejected",
        "coefficient_equal": coefficient_equal,
        "pixel_difference_vs_png": pixel_difference,
        "output_sha256": hashlib.sha256(output_bytes).hexdigest(),
        "output_bytes": len(output_bytes),
        "source_markers": source_markers,
        "output_markers": output_markers,
        "metadata": metadata,
        "dct_semantics": dct_semantics,
    }


def _analyze_source(label: str, row: dict[str, Any], source_path: Path, output_dir: Path) -> dict[str, Any]:
    source_bytes = source_path.read_bytes()
    plan = runtime_plan(row)
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    marker = jpeg_markers(source_bytes)
    snapshot_url = row.get("sourceSnapshotUrl")
    result: dict[str, Any] = {
        "label": label,
        "source_path": str(source_path),
        "source_sha256": source_hash,
        "source_bytes": len(source_bytes),
        "runtime_source_identity_match": isinstance(snapshot_url, str) and plan["source_url"] == snapshot_url,
        "runtime_source_dimensions_match": plan["dimensions"] == [row["base"].get("canvasWidth"), row["base"].get("canvasHeight")],
        "markers": marker,
        "plan": {key: value for key, value in plan.items() if key not in {"base", "mappings"}},
    }
    source_dct, source_temp = _jpeg_dct(source_bytes)
    try:
        arrays = _dct_arrays(source_dct)
        result["dct"] = {
            "component_arrays": {name: {"shape": list(value.shape), "sha256": _array_hash(value)} for name, value in arrays.items()},
            "component_count": len(arrays),
            "sampling_factors": source_dct.samp_factor.tolist(),
            "quant_table_numbers": source_dct.quant_tbl_no.tolist(),
            "quant_tables": source_dct.qt.tolist(),
            "width_in_blocks": [int(source_dct.width_in_blocks(i)) for i in range(len(arrays))],
            "height_in_blocks": [int(source_dct.height_in_blocks(i)) for i in range(len(arrays))],
            "jpeg_color_space": str(getattr(source_dct, "jpeg_color_space", None)),
            "progressive_mode": bool(getattr(source_dct, "progressive_mode", False)),
        }
    finally:
        source_dct.close()
        source_temp.unlink(missing_ok=True)

    mappings = plan["mappings"]
    try:
        coefficient = permute_coefficients(
            source_bytes,
            mappings=mappings,
            source_path=plan["source_url"],
            base=plan["base"],
            visible_draw=plan["base"],
        )
    except Exception as exc:  # noqa: BLE001 - research path must fail closed
        result["coefficient_path"] = {"status": "rejected", "reason": f"{type(exc).__name__}: {exc}"}
        return result

    reconstructed = output_dir / f"{label}.reconstructed.jpg"
    reconstructed.write_bytes(coefficient["jpeg"])
    png = reconstruct_jpeg_png(
        source_bytes,
        base=plan["base"],
        mappings=mappings,
        visible_draw=plan["base"],
        source_path=plan["source_url"],
        canvas_size=tuple(plan["dimensions"]),
    )
    png_path = output_dir / f"{label}.reconstructed.png"
    if png is not None:
        png_path.write_bytes(png.data)
    jpeg_image = Image.open(io.BytesIO(coefficient["jpeg"])).convert("RGB")
    png_image = Image.open(io.BytesIO(png.data)).convert("RGB") if png is not None else None
    metadata = coefficient["metadata"]
    metadata_preserved = all(
        metadata.get(key) is True
        for key in (
            "dimensions_equal", "sampling_equal", "component_ids_equal", "progressive_equal",
            "restart_interval_equal", "quantization_segments_byte_equal",
            "huffman_segments_byte_equal", "jfif_segments_byte_equal",
        )
    )
    result["coefficient_path"] = {
        "status": "verified_coefficients_metadata_rejected" if not metadata_preserved else "verified",
        "output_sha256": hashlib.sha256(coefficient["jpeg"]).hexdigest(),
        "output_bytes": len(coefficient["jpeg"]),
        "coefficients_expected_equal": coefficient["coefficients_expected_equal"],
        "coefficients_expected_equal_by_component": coefficient["coefficients_expected_equal_by_component"],
        "right_edge_unchanged": coefficient["right_edge_unchanged"],
        "quantization_equal": coefficient["quantization_equal"],
        "sampling_equal": coefficient["sampling_equal"],
        "metadata_preserved": metadata_preserved,
        "metadata": metadata,
        "decoded_pixel_difference_vs_png": _pixel_difference(png_image, jpeg_image) if png_image is not None else None,
        "png_path": str(png_path) if png is not None else None,
        "jpeg_path": str(reconstructed),
    }
    result["qt_sentinel_experiment"] = _qt_sentinel_experiment(
        source_bytes,
        coefficient["expected_coefficients"],
        png_image,
    )
    result["production_safe"] = bool(
        result["runtime_source_identity_match"]
        and result["runtime_source_dimensions_match"]
        and coefficient["coefficients_expected_equal"]
        and coefficient["right_edge_unchanged"]
        and metadata_preserved
    )
    return result


def run_report(input_dir: Path, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    pages: list[dict[str, Any]] = []
    for report_path in sorted(input_dir.glob("*.json")):
        if report_path.name == "report.json":
            continue
        report = json.loads(report_path.read_text(encoding="utf-8"))
        for item in report.get("positions", []):
            row = item.get("row")
            source = row.get("sourceBytesPath") if isinstance(row, dict) else None
            if not isinstance(row, dict) or not source:
                continue
            label = f"{report_path.stem}_slider{item.get('slider')}_area{row.get('areaIndex')}"
            pages.append(_analyze_source(label, row, Path(source), output_dir))
    all_coefficient_valid = bool(pages) and all(
        item.get("coefficient_path", {}).get("coefficients_expected_equal") is True
        and item.get("coefficient_path", {}).get("right_edge_unchanged") is True
        for item in pages
    )
    return {
        "status": (
            "coefficient_verified_metadata_rejected"
            if all_coefficient_valid and not any(item.get("production_safe") for item in pages)
            else "verified"
            if all_coefficient_valid
            else "not_verified"
        ),
        "tile_geometry": {
            "tile_pixels": [TILE_WIDTH, TILE_HEIGHT],
            "tile_blocks": [TILE_BLOCK_WIDTH, TILE_BLOCK_HEIGHT],
            "tile_count": TILE_COLUMNS * TILE_ROWS,
            "tile_area_pixels": [TILE_WIDTH * TILE_COLUMNS, TILE_HEIGHT * TILE_ROWS],
            "right_edge_rule": "preserve coefficient block column 140; visible edge is 5px for 1125px and 7px for 1127px sources",
        },
        "pages": pages,
        "production_safe_page_count": sum(bool(item.get("production_safe")) for item in pages),
        "png_fallback_page_count": sum(not bool(item.get("production_safe")) for item in pages),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = run_report(args.input_dir, args.output_dir)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"status": result["status"], "pages": len(result["pages"]), "production_safe": result["production_safe_page_count"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
