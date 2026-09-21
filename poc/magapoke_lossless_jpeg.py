"""Feasibility PoC for Magapoke JPEG coefficient-domain tile permutation.

This file is deliberately outside the production package.  It requires the
optional ``jpeglib`` and ``numpy`` packages when it is run, for example:

    uv run --python 3.14 --with jpeglib --with numpy --with Pillow \
        python poc/magapoke_lossless_jpeg.py --fixture

The live mode attaches to the shared Crawler Chrome and writes only a JSON
report.  It never saves live JPEG/PNG artifacts.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image

from screenshot_crawler.core.browser import BrowserSession, resolve_cdp_endpoint
from screenshot_crawler.site_adapters.magapoke import MagapokeAdapter
from screenshot_crawler.site_adapters.magapoke.native_capture import (
    DrawMapping,
    reconstruct_jpeg_png,
)


def _require_optional_dependencies() -> tuple[Any, Any]:
    try:
        import jpeglib  # type: ignore[import-not-found]
        import numpy as np  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - exercised by CLI users
        raise RuntimeError(
            "PoC requires optional jpeglib and numpy; run it with uv --with jpeglib --with numpy"
        ) from exc
    return jpeglib, np


def _jpeg_dct(data: bytes) -> tuple[Any, Path]:
    jpeglib, _ = _require_optional_dependencies()
    handle_path: Path
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as handle:
            handle_path = Path(handle.name)
            handle.write(data)
        return jpeglib.read_dct(str(handle_path)), handle_path
    except BaseException:
        if "handle_path" in locals():
            handle_path.unlink(missing_ok=True)
        raise


def _dct_arrays(dct: Any) -> dict[str, Any]:
    _, np = _require_optional_dependencies()
    return {
        name: np.array(getattr(dct, name), dtype=np.int16, copy=True)
        for name in ("Y", "Cb", "Cr")
        if getattr(dct, name, None) is not None
    }


def _write_dct(dct: Any, arrays: dict[str, Any]) -> bytes:
    for name, array in arrays.items():
        getattr(dct, name)[...] = array
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as output:
        output_path = Path(output.name)
    try:
        dct.write_dct(str(output_path))
        return output_path.read_bytes()
    finally:
        output_path.unlink(missing_ok=True)


def _marker_name(marker: int) -> str:
    if 0xE0 <= marker <= 0xEF:
        return f"APP{marker - 0xE0}"
    return {
        0xC0: "SOF0",
        0xC1: "SOF1",
        0xC2: "SOF2",
        0xC3: "SOF3",
        0xC4: "DHT",
        0xD8: "SOI",
        0xD9: "EOI",
        0xDA: "SOS",
        0xDD: "DRI",
        0xFE: "COM",
    }.get(marker, f"0x{marker:02x}")


def jpeg_markers(data: bytes) -> dict[str, Any]:
    """Parse structural JPEG markers without decoding the image."""

    result: dict[str, Any] = {
        "markers": [],
        "appn": [],
        "quantization_marker_count": 0,
        "huffman_marker_count": 0,
        "restart_interval": 0,
        "progressive": False,
        "components": [],
        "width": None,
        "height": None,
    }
    if not data.startswith(b"\xff\xd8"):
        return result
    result["markers"].append("SOI")
    index = 2
    sof_markers = set(range(0xC0, 0xC4)) | set(range(0xC5, 0xC8))
    sof_markers |= set(range(0xC9, 0xCC)) | set(range(0xCD, 0xD0))
    while index < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        while index < len(data) and data[index] == 0xFF:
            index += 1
        if index >= len(data):
            break
        marker = data[index]
        index += 1
        if marker == 0xD9:
            result["markers"].append("EOI")
            break
        if marker == 0xDA:
            result["markers"].append("SOS")
            break
        if marker in {0xD8} or 0xD0 <= marker <= 0xD7:
            result["markers"].append(_marker_name(marker))
            continue
        if index + 2 > len(data):
            break
        length = int.from_bytes(data[index : index + 2], "big")
        if length < 2 or index + length > len(data):
            break
        payload = data[index + 2 : index + length]
        name = _marker_name(marker)
        result["markers"].append(name)
        if 0xE0 <= marker <= 0xEF:
            result["appn"].append(
                {
                    "marker": name,
                    "length": len(payload),
                    "signature": payload[:16].decode("latin1", errors="replace"),
                }
            )
        elif marker == 0xC4:
            result["huffman_marker_count"] += 1
        elif marker == 0xDB:
            result["quantization_marker_count"] += 1
        elif marker == 0xDD and len(payload) >= 2:
            result["restart_interval"] = int.from_bytes(payload[:2], "big")
        elif marker in sof_markers and len(payload) >= 6:
            result["progressive"] = marker in {0xC2, 0xC6, 0xCA, 0xCE}
            result["height"] = int.from_bytes(payload[1:3], "big")
            result["width"] = int.from_bytes(payload[3:5], "big")
            count = payload[5]
            components = []
            for offset in range(6, 6 + 3 * count, 3):
                if offset + 3 <= len(payload):
                    components.append(
                        {
                            "id": payload[offset],
                            "h": payload[offset + 1] >> 4,
                            "v": payload[offset + 1] & 0x0F,
                            "qt": payload[offset + 2],
                        }
                    )
            result["components"] = components
        index += length
    return result


def _segment_payloads(data: bytes, wanted: int) -> list[bytes]:
    payloads: list[bytes] = []
    if not data.startswith(b"\xff\xd8"):
        return payloads
    index = 2
    while index + 3 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        while index < len(data) and data[index] == 0xFF:
            index += 1
        if index >= len(data):
            break
        marker = data[index]
        index += 1
        if marker == 0xDA or marker == 0xD9:
            break
        if marker == 0xD8 or 0xD0 <= marker <= 0xD7:
            continue
        if index + 2 > len(data):
            break
        length = int.from_bytes(data[index : index + 2], "big")
        if length < 2 or index + length > len(data):
            break
        if marker == wanted:
            payloads.append(data[index + 2 : index + length])
        index += length
    return payloads


def _same_structural_metadata(left: bytes, right: bytes) -> dict[str, Any]:
    a = jpeg_markers(left)
    b = jpeg_markers(right)
    return {
        "dimensions_equal": (a["width"], a["height"]) == (b["width"], b["height"]),
        "sampling_equal": [
            (item["h"], item["v"], item["qt"]) for item in a["components"]
        ] == [
            (item["h"], item["v"], item["qt"]) for item in b["components"]
        ],
        "component_ids_equal": [item["id"] for item in a["components"]]
        == [item["id"] for item in b["components"]],
        "components_before": a["components"],
        "components_after": b["components"],
        "progressive_equal": a["progressive"] == b["progressive"],
        "restart_interval_equal": a["restart_interval"] == b["restart_interval"],
        "appn_before": a["appn"],
        "appn_after": b["appn"],
        "markers_before": a["markers"],
        "markers_after": b["markers"],
        "huffman_marker_count_before": a["huffman_marker_count"],
        "huffman_marker_count_after": b["huffman_marker_count"],
        "quantization_marker_count_before": a["quantization_marker_count"],
        "quantization_marker_count_after": b["quantization_marker_count"],
        "quantization_segments_byte_equal": _segment_payloads(left, 0xDB)
        == _segment_payloads(right, 0xDB),
        "huffman_segments_byte_equal": _segment_payloads(left, 0xC4)
        == _segment_payloads(right, 0xC4),
        "jfif_segments_byte_equal": _segment_payloads(left, 0xE0)
        == _segment_payloads(right, 0xE0),
    }


def _mapping_list(raw: list[object]) -> list[DrawMapping] | None:
    parsed = [DrawMapping.from_dict(item) for item in raw]
    return [item for item in parsed if item is not None] if all(parsed) else None


def _block_cells(rectangles: list[tuple[int, int, int, int]]) -> set[tuple[int, int]] | None:
    cells: set[tuple[int, int]] = set()
    for x, y, width, height in rectangles:
        if min(x, y, width, height) < 0 or any(value % 8 for value in (x, y, width, height)):
            return None
        for by in range(y // 8, (y + height) // 8):
            for bx in range(x // 8, (x + width) // 8):
                cell = (bx, by)
                if cell in cells:
                    return None
                cells.add(cell)
    return cells


def _prepare_permutation(
    dct: Any,
    *,
    mappings: list[object],
    source_path: str | None = None,
    base: object | None = None,
    visible_draw: object | None = None,
) -> tuple[list[DrawMapping], dict[str, Any]]:
    """Validate a current draw mapping for the restricted 4:4:4 PoC."""

    factors = [(int(row[0]), int(row[1])) for row in dct.samp_factor.tolist()]
    if len(factors) not in {1, 3} or any(pair != (1, 1) for pair in factors):
        raise ValueError(f"restricted PoC requires grayscale 1x1 or 4:4:4 sampling, got {factors}")
    if any(dct.width_in_blocks(i) * 8 != dct.width_in_blocks(0) * 8 for i in range(len(factors))):
        raise ValueError("component block grids are not identical")
    tiles = _mapping_list(mappings)
    if not tiles:
        raise ValueError("mapping list is empty or malformed")
    if source_path is not None and any(item.source_path != source_path for item in tiles):
        raise ValueError("mapping source path is inconsistent")
    dimensions = (int(dct.width), int(dct.height))
    for label, raw in (("base", base), ("visible draw", visible_draw)):
        full = DrawMapping.from_dict(raw)
        if (
            full is None
            or full.source_path != source_path
            or (full.source_width, full.source_height) != dimensions
            or (full.sx, full.sy, full.sw, full.sh) != (0, 0, *dimensions)
            or (full.dx, full.dy, full.dw, full.dh) != (0, 0, *dimensions)
            or full.transform != (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
            or full.composite_operation != "source-over"
            or full.filter != "none"
        ):
            raise ValueError(f"{label} is not a verified full-size identity draw")
    source_rectangles = [(item.sx, item.sy, item.sw, item.sh) for item in tiles]
    destination_rectangles = [(item.dx, item.dy, item.dw, item.dh) for item in tiles]
    source_cells = _block_cells(source_rectangles)
    destination_cells = _block_cells(destination_rectangles)
    if source_cells is None or destination_cells is None or len(source_cells) != len(destination_cells):
        raise ValueError("tile mapping is not a non-overlapping block permutation")
    for item in tiles:
        if (
            item.source_width,
            item.source_height,
        ) != dimensions or item.sw != item.dw or item.sh != item.dh:
            raise ValueError("tile mapping dimensions are unsafe")
        if item.sx + item.sw > dimensions[0] or item.sy + item.sh > dimensions[1]:
            raise ValueError("source tile exceeds JPEG dimensions")
        if item.dx + item.dw > dimensions[0] or item.dy + item.dh > dimensions[1]:
            raise ValueError("destination tile exceeds JPEG dimensions")
        if item.transform != (1.0, 0.0, 0.0, 1.0, 0.0, 0.0):
            raise ValueError("tile transform is not identity")
        if item.composite_operation != "source-over" or item.filter != "none":
            raise ValueError("tile compositing is unsafe")
    source_bounds = (
        min(x for x, _, _, _ in source_rectangles),
        min(y for _, y, _, _ in source_rectangles),
        max(x + width for x, _, width, _ in source_rectangles),
        max(y + height for _, y, _, height in source_rectangles),
    )
    destination_bounds = (
        min(x for x, _, _, _ in destination_rectangles),
        min(y for _, y, _, _ in destination_rectangles),
        max(x + width for x, _, width, _ in destination_rectangles),
        max(y + height for _, y, _, height in destination_rectangles),
    )
    for cells, bounds in ((source_cells, source_bounds), (destination_cells, destination_bounds)):
        expected_cells = {
            (bx, by)
            for by in range(bounds[1] // 8, bounds[3] // 8)
            for bx in range(bounds[0] // 8, bounds[2] // 8)
        }
        if cells != expected_cells:
            raise ValueError("tile mapping has a block gap")
    if source_bounds != destination_bounds or source_bounds[:2] != (0, 0):
        raise ValueError("source/destination tile extents do not match")
    coded_width = int(dct.width_in_blocks(0) * 8)
    coded_height = int(dct.height_in_blocks(0) * 8)
    if coded_width < dimensions[0] or coded_height < dimensions[1]:
        raise ValueError("DCT grid is smaller than the JPEG dimensions")
    return tiles, {
        "dimensions": [int(dct.width), int(dct.height)],
        "sampling_factors": factors,
        "coded_dimensions": [coded_width, coded_height],
        "source_bounds": list(source_bounds),
        "destination_bounds": list(destination_bounds),
        "source_block_count": len(source_cells),
        "untouched_block_columns": list(range(source_bounds[2] // 8, int(dct.width_in_blocks(0)))),
        "untouched_block_rows": list(range(source_bounds[3] // 8, int(dct.height_in_blocks(0)))),
    }


def permute_coefficients(
    data: bytes,
    *,
    mappings: list[object],
    source_path: str | None = None,
    base: object | None = None,
    visible_draw: object | None = None,
) -> dict[str, Any]:
    """Permute 4:4:4 Y/Cb/Cr block arrays and write a JPEG without re-DCT."""

    _, np = _require_optional_dependencies()
    dct, source_temp = _jpeg_dct(data)
    try:
        tiles, structure = _prepare_permutation(
            dct,
            mappings=mappings,
            source_path=source_path,
            base=base,
            visible_draw=visible_draw,
        )
        original = _dct_arrays(dct)
        expected = {name: array.copy() for name, array in original.items()}
        for item in tiles:
            sx, sy = item.sx // 8, item.sy // 8
            dx, dy = item.dx // 8, item.dy // 8
            width, height = item.sw // 8, item.sh // 8
            for name, destination in expected.items():
                destination[dy : dy + height, dx : dx + width] = original[name][
                    sy : sy + height, sx : sx + width
                ]
        output_bytes = _write_dct(dct, expected)
        output_dct, output_temp = _jpeg_dct(output_bytes)
        try:
            observed = _dct_arrays(output_dct)
            coefficient_equal = all(np.array_equal(expected[name], observed[name]) for name in expected)
            right_edge_equal = True
            edge_start = structure["source_bounds"][2] // 8
            for name, array in original.items():
                right_edge_equal &= bool(np.array_equal(array[:, edge_start:], observed[name][:, edge_start:]))
            return {
                "jpeg": output_bytes,
                "structure": structure,
                "coefficients_expected_equal": coefficient_equal,
                "coefficients_expected_equal_by_component": {
                    name: bool(np.array_equal(expected[name], observed[name])) for name in expected
                },
                "right_edge_unchanged": right_edge_equal,
                "quantization_equal": bool(np.array_equal(dct.qt, output_dct.qt)),
                "sampling_equal": dct.samp_factor.tolist() == output_dct.samp_factor.tolist(),
                "source_coefficients": original,
                "expected_coefficients": expected,
                "output_coefficients": observed,
                "metadata": _same_structural_metadata(data, output_bytes),
            }
        finally:
            output_dct.close()
            output_temp.unlink(missing_ok=True)
    finally:
        dct.close()
        source_temp.unlink(missing_ok=True)


def _inverse_mappings(mappings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    inverse = []
    for item in mappings:
        copy = dict(item)
        copy.update(
            {
                "sx": item["dx"],
                "sy": item["dy"],
                "dx": item["sx"],
                "dy": item["sy"],
                "sourceWidth": item["sourceWidth"],
                "sourceHeight": item["sourceHeight"],
            }
        )
        inverse.append(copy)
    return inverse


def _pattern_image(size: tuple[int, int]) -> Image.Image:
    image = Image.new("RGB", size)
    pixels = image.load()
    for y in range(size[1]):
        for x in range(size[0]):
            pixels[x, y] = ((x * 17 + y * 3) % 256, (x * 5 + y * 23) % 256, (x * 31 + y * 7) % 256)
    return image


def _jpeg_bytes(image: Image.Image, *, subsampling: int) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=87, subsampling=subsampling, optimize=False)
    return buffer.getvalue()


def run_fixture() -> dict[str, Any]:
    size = (70, 48)
    path = "/static/web_titles/695/episodes/fixture/poc.jpg"
    # 64x48 is the permuted area.  The visible 6px right strip and the two
    # coded pixels after it remain in the initial full draw.
    mappings: list[dict[str, Any]] = []
    destination_order = [(0, 0), (16, 0), (32, 0), (48, 0), (0, 16), (16, 16),
                         (32, 16), (48, 16), (0, 32), (16, 32), (32, 32), (48, 32)]
    source_order = [(32, 16), (48, 0), (0, 32), (16, 0), (48, 32), (0, 16),
                    (32, 0), (0, 0), (16, 32), (48, 16), (16, 16), (32, 32)]
    for (dx, dy), (sx, sy) in zip(destination_order, source_order):
        mappings.append(
            {
                "sourcePath": path, "sourceWidth": size[0], "sourceHeight": size[1],
                "canvasWidth": size[0], "canvasHeight": size[1],
                "sx": sx, "sy": sy, "sw": 16, "sh": 16,
                "dx": dx, "dy": dy, "dw": 16, "dh": 16,
                "transform": [1, 0, 0, 1, 0, 0],
                "compositeOperation": "source-over", "filter": "none",
            }
        )
    normal = _pattern_image(size)
    scrambled = normal.copy()
    for item in mappings:
        crop = normal.crop((item["dx"], item["dy"], item["dx"] + 16, item["dy"] + 16))
        scrambled.paste(crop, (item["sx"], item["sy"]))
    scrambled_bytes = _jpeg_bytes(scrambled, subsampling=0)
    full_mapping = {
        **mappings[0], "sx": 0, "sy": 0, "sw": size[0], "sh": size[1],
        "dx": 0, "dy": 0, "dw": size[0], "dh": size[1],
    }
    result = permute_coefficients(
        scrambled_bytes, mappings=mappings, source_path=path,
        base=full_mapping, visible_draw=full_mapping,
    )
    restored = permute_coefficients(
        result["jpeg"], mappings=_inverse_mappings(mappings), source_path=path,
        base=full_mapping, visible_draw=full_mapping,
    )
    rejected_subsampling: dict[str, str] = {}
    for label, subsampling in (("4:2:2", 1), ("4:2:0", 2)):
        try:
            permute_coefficients(
                _jpeg_bytes(scrambled, subsampling=subsampling),
                mappings=mappings, source_path=path,
                base=full_mapping, visible_draw=full_mapping,
            )
        except ValueError as exc:
            rejected_subsampling[label] = str(exc)
    truth = reconstruct_jpeg_png(
        scrambled_bytes,
        base=full_mapping,
        mappings=mappings,
        visible_draw=full_mapping,
        source_path=path,
        canvas_size=size,
    )
    assert truth is not None
    reconstructed_image = Image.open(io.BytesIO(result["jpeg"])).convert("RGB")
    truth_image = Image.open(io.BytesIO(truth.data)).convert("RGB")
    return {
        "status": "verified" if result["coefficients_expected_equal"] and restored["coefficients_expected_equal"] else "failed",
        "dimensions": list(size),
        "sampling": jpeg_markers(scrambled_bytes)["components"],
        "coded_dimensions": result["structure"]["coded_dimensions"],
        "right_edge": {
            "visible_x": [64, 69], "coded_block_columns": [8],
            "unchanged": result["right_edge_unchanged"],
        },
        "coefficient_permutation": result["coefficients_expected_equal"],
        "inverse_restore_coefficients": restored["coefficients_expected_equal"],
        "original_coefficients_equal_after_inverse": all(
            bool((restored["output_coefficients"][name] == result["source_coefficients"][name]).all())
            for name in result["source_coefficients"]
        ),
        "decoded_pixels_equal_png_truth": reconstructed_image.tobytes() == truth_image.tobytes(),
        "decoded_difference": _pixel_difference(truth_image, reconstructed_image),
        "rejected_subsampling": rejected_subsampling,
        "bytes": {
            "scrambled_jpeg": len(scrambled_bytes),
            "reconstructed_jpeg": len(result["jpeg"]),
            "truth_png": len(truth.data),
        },
        "metadata": result["metadata"],
    }


def _pixel_difference(left: Image.Image, right: Image.Image) -> dict[str, Any]:
    _, np = _require_optional_dependencies()
    a = np.asarray(left.convert("RGB"), dtype=np.int16)
    b = np.asarray(right.convert("RGB"), dtype=np.int16)
    difference = np.abs(a - b)
    changed = np.any(difference != 0, axis=2)
    if not changed.any():
        bbox = None
    else:
        ys, xs = np.where(changed)
        bbox = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
    return {
        "different_pixel_count": int(changed.sum()),
        "max_abs_channel_difference": int(difference.max()),
        "bounding_box": bbox,
    }


async def run_live(*, target_count: int, endpoint: str) -> dict[str, Any]:
    session = await BrowserSession.connect(endpoint)
    page = await session.new_page()
    adapter = MagapokeAdapter()
    source_url = "https://pocket.shonenmagazine.com/title/00695/episode/244815"
    rows_report: list[dict[str, Any]] = []
    try:
        await adapter.prepare_page(page)
        await page.goto(source_url, wait_until="domcontentloaded")
        await adapter.initialize(page)
        while len(rows_report) < target_count:
            rows = await adapter._canvas_rows(page)  # diagnostic-only use of existing hook state
            if not rows:
                break
            for row in rows:
                if len(rows_report) >= target_count:
                    break
                path = str(row.get("sourcePath") or "")
                body = await adapter._source_bytes_for(path) if path else None
                png = None
                coefficient = None
                if body is not None:
                    png = reconstruct_jpeg_png(
                        body,
                        base=row.get("base"), mappings=row.get("mapping") or [],
                        visible_draw=row.get("visibleDraw"), source_path=path,
                        canvas_size=(int(row.get("canvasWidth") or 0), int(row.get("canvasHeight") or 0)),
                    )
                    if png is not None:
                        coefficient = permute_coefficients(
                            body,
                            mappings=row.get("mapping") or [], source_path=path,
                            base=row.get("base"), visible_draw=row.get("visibleDraw"),
                        )
                pixel_difference = None
                pixel_equal = False
                if coefficient is not None and png is not None:
                    pixel_difference = _pixel_difference(
                        Image.open(io.BytesIO(png.data)).convert("RGB"),
                        Image.open(io.BytesIO(coefficient["jpeg"])).convert("RGB"),
                    )
                    pixel_equal = pixel_difference["different_pixel_count"] == 0
                markers = jpeg_markers(body) if body is not None else {}
                rows_report.append(
                    {
                        "page_source": path,
                        "page_index": row.get("pageIndex"),
                        "dimensions": [markers.get("width"), markers.get("height")],
                        "sampling": markers.get("components"),
                        "mcu_or_block": [8, 8] if markers.get("components") else None,
                        "tile_count": len(row.get("mapping") or []),
                        "original_jpeg_bytes": len(body) if body is not None else None,
                        "lossless_reconstructed_jpeg_bytes": len(coefficient["jpeg"]) if coefficient else None,
                        "current_png_bytes": len(png.data) if png else None,
                        "jpeg_original_ratio": len(coefficient["jpeg"]) / len(body) if coefficient and body else None,
                        "jpeg_png_ratio": len(coefficient["jpeg"]) / len(png.data) if coefficient and png else None,
                        "pixel_equality": pixel_equal,
                        "pixel_difference": pixel_difference,
                        "coefficient_validation": coefficient["coefficients_expected_equal"] if coefficient else False,
                        "coefficient_validation_by_component": coefficient["coefficients_expected_equal_by_component"] if coefficient else {},
                        "quantization_tables_equal": coefficient["quantization_equal"] if coefficient else False,
                        "sampling_factors_equal": coefficient["sampling_equal"] if coefficient else False,
                        "right_edge_validation": coefficient["right_edge_unchanged"] if coefficient else False,
                        "structure": coefficient["structure"] if coefficient else None,
                        "metadata": coefficient["metadata"] if coefficient else None,
                    }
                )
                if path:
                    await adapter._discard_source(path)
            if len(rows_report) >= target_count:
                break
            previous = await adapter.get_content_identity(page)
            await adapter.go_next(page)
            await adapter.wait_for_change(page, previous)
        return {
            "status": "verified" if len(rows_report) == target_count and rows_report else "not_verified",
            "source_url": source_url,
            "target_count": target_count,
            "pages": rows_report,
        }
    finally:
        await session.close_page(page)
        await session.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--pages", type=int, default=5)
    parser.add_argument("--cdp-endpoint", default=None)
    args = parser.parse_args()
    if not args.fixture and not args.live:
        parser.error("choose --fixture or --live")
    if args.fixture:
        print(json.dumps({"fixture": run_fixture()}, ensure_ascii=False, indent=2, default=_json_default))
    if args.live:
        endpoint = resolve_cdp_endpoint(cli_endpoint=args.cdp_endpoint)
        result = asyncio.run(run_live(target_count=args.pages, endpoint=endpoint))
        print(json.dumps({"live": result}, ensure_ascii=False, indent=2, default=_json_default))


def _json_default(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return value.tolist()
    raise TypeError(f"not JSON serializable: {type(value)!r}")


if __name__ == "__main__":
    main()
