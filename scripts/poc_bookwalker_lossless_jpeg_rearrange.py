"""PoC for reconstructing a BookWalker scrambled JPEG in the DCT domain.

This script is intentionally outside production capture.  It consumes the
local output of ``probe_bookwalker_purchased_transform.py`` and only accepts a
part whose mapping was already proven with strict MCU alignment.  The source
JPEG is read and written through jpeglib/libjpeg coefficient APIs; Pillow is
used only for final decoded-pixel comparison and never for JPEG output.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import jpeglib
import numpy as np
from PIL import Image

from screenshot_crawler.core.browser import BrowserSession, resolve_cdp_endpoint

SOF0 = 0xC0
PROGRESSIVE_SOF = {0xC2, 0xC6, 0xCA, 0xCE}
ALL_SOF = (
    set(range(0xC0, 0xC4))
    | set(range(0xC5, 0xC8))
    | set(range(0xC9, 0xCC))
    | set(range(0xCD, 0xD0))
)
COMPONENT_NAMES = ("Y", "Cb", "Cr")


class PocFailure(RuntimeError):
    def __init__(self, status: str, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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
        0xDB: "DQT",
        0xFE: "COM",
    }.get(marker, f"0x{marker:02X}")


def parse_jpeg_structure(data: bytes) -> dict[str, Any]:
    """Parse structural JPEG metadata before the entropy-coded scan."""

    result: dict[str, Any] = {
        "markers": [],
        "segments": [],
        "width": None,
        "height": None,
        "sof_marker": None,
        "progressive": False,
        "components": [],
        "quantization_tables": {},
        "restart_interval": 0,
        "huffman_segment_count": 0,
    }
    if not data.startswith(b"\xff\xd8"):
        return result
    result["markers"].append("SOI")
    offset = 2
    while offset + 1 < len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            break
        marker = data[offset]
        offset += 1
        if marker == 0x00:
            continue
        if marker == 0xD9:
            result["markers"].append("EOI")
            break
        if marker == 0xDA:
            result["markers"].append("SOS")
            break
        name = _marker_name(marker)
        if marker in {0xD8} or 0xD0 <= marker <= 0xD7:
            result["markers"].append(name)
            continue
        if offset + 2 > len(data):
            break
        length = int.from_bytes(data[offset : offset + 2], "big")
        if length < 2 or offset + length > len(data):
            break
        payload = data[offset + 2 : offset + length]
        result["markers"].append(name)
        result["segments"].append({
            "marker": name,
            "byte_length": length,
            "payload_sha256": _sha256(payload),
            "printable_string_present": any(32 <= byte <= 126 for byte in payload),
        })
        if marker in ALL_SOF and len(payload) >= 6:
            component_count = payload[5]
            components = []
            for component_offset in range(6, 6 + component_count * 3, 3):
                if component_offset + 3 > len(payload):
                    raise PocFailure("UNSUPPORTED_JPEG_LAYOUT", "truncated SOF component")
                sampling = payload[component_offset + 1]
                components.append({
                    "id": payload[component_offset],
                    "h_sampling_factor": sampling >> 4,
                    "v_sampling_factor": sampling & 0x0F,
                    "quantization_table_id": payload[component_offset + 2],
                })
            result.update({
                "width": int.from_bytes(payload[3:5], "big"),
                "height": int.from_bytes(payload[1:3], "big"),
                "sof_marker": name,
                "sof_marker_code": marker,
                "progressive": marker in PROGRESSIVE_SOF,
                "precision": payload[0],
                "components": components,
            })
        elif marker == 0xDB:
            cursor = 0
            while cursor < len(payload):
                info = payload[cursor]
                cursor += 1
                precision = info >> 4
                table_id = info & 0x0F
                value_bytes = 2 if precision else 1
                value_count = 64 * value_bytes
                if cursor + value_count > len(payload):
                    raise PocFailure("UNSUPPORTED_JPEG_LAYOUT", "truncated DQT")
                if precision:
                    values = [
                        int.from_bytes(payload[cursor + index : cursor + index + 2], "big")
                        for index in range(0, value_count, 2)
                    ]
                else:
                    values = list(payload[cursor : cursor + value_count])
                result["quantization_tables"][str(table_id)] = {
                    "precision": precision,
                    "values": values,
                }
                cursor += value_count
        elif marker == 0xDD and len(payload) >= 2:
            result["restart_interval"] = int.from_bytes(payload[:2], "big")
        elif marker == 0xC4:
            result["huffman_segment_count"] += 1
        offset += length
    return result


def _component_names(dct: Any) -> list[str]:
    if int(dct.num_components) == 1:
        return ["Y"]
    if int(dct.num_components) == 3:
        return list(COMPONENT_NAMES)
    raise PocFailure(
        "UNSUPPORTED_JPEG_LAYOUT",
        f"only grayscale or three-component JPEG is supported, got {dct.num_components}",
    )


def _dct_structure(dct: Any, parsed: dict[str, Any]) -> dict[str, Any]:
    names = _component_names(dct)
    factors = [
        {
            "h": int(row[0]),
            "v": int(row[1]),
        }
        for row in np.asarray(dct.samp_factor).tolist()
    ]
    max_h = max(item["h"] for item in factors)
    max_v = max(item["v"] for item in factors)
    components = []
    parsed_components = parsed.get("components") or []
    for index, name in enumerate(names):
        array = np.asarray(getattr(dct, name))
        parsed_component = parsed_components[index] if index < len(parsed_components) else {}
        components.append({
            "name": name,
            "id": parsed_component.get("id"),
            "h_sampling_factor": factors[index]["h"],
            "v_sampling_factor": factors[index]["v"],
            "width_in_blocks": int(array.shape[1]),
            "height_in_blocks": int(array.shape[0]),
            "quantization_table_id": int(np.asarray(dct.quant_tbl_no)[index]),
        })
    return {
        "visible_dimensions": {
            "width": int(dct.width),
            "height": int(dct.height),
        },
        "sof": parsed.get("sof_marker"),
        "progressive": bool(parsed.get("progressive")),
        "num_scans": int(dct.num_scans),
        "component_count": int(dct.num_components),
        "components": components,
        "sampling_factors": factors,
        "mcu_dimensions": {"width": 8 * max_h, "height": 8 * max_v},
        "quantization_tables": parsed.get("quantization_tables", {}),
        "restart_interval": int(parsed.get("restart_interval", 0)),
        "huffman_segment_count": int(parsed.get("huffman_segment_count", 0)),
        "markers": parsed.get("markers", []),
        "segments": parsed.get("segments", []),
    }


def _canonical_mapping(mapping: list[dict[str, Any]]) -> list[dict[str, int]]:
    fields = (
        "source_x",
        "source_y",
        "destination_x",
        "destination_y",
        "width",
        "height",
    )
    return sorted(
        [{field: int(item[field]) for field in fields} for item in mapping],
        key=lambda item: (
            item["source_y"],
            item["source_x"],
            item["destination_y"],
            item["destination_x"],
            item["width"],
            item["height"],
        ),
    )


def mapping_sha256(mapping: list[dict[str, Any]]) -> str:
    canonical = json.dumps(
        _canonical_mapping(mapping),
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return _sha256(canonical)


def validate_part_evidence(part_mapping: dict[str, Any]) -> None:
    required = {
        "mapping_status": "PART_MAPPING_PROVEN",
        "readiness": "LOSSLESS_JPEG_REARRANGEMENT_READY",
    }
    for field, expected in required.items():
        if part_mapping.get(field) != expected:
            raise PocFailure("UNSAFE_MAPPING", f"{field} is not {expected}")
    permutation = part_mapping.get("permutation") or {}
    imagebitmap = part_mapping.get("imagebitmap") or {}
    raw = part_mapping.get("raw_jpeg") or {}
    safety = part_mapping.get("safety") or {}
    mcu = part_mapping.get("mcu_alignment") or {}
    checks = {
        "complete_bijection": permutation.get("complete_bijection") is True,
        "raw_decoded_pixel_exact": raw.get("decoded_pixel_exact_match") is True,
        "one_exact_imagebitmap_match": imagebitmap.get(
            "exact_decoded_pixel_match_count"
        ) == 1,
        "no_additional_pixel_processing": safety.get("additional_pixel_processing") is False,
        "strict_mcu_alignment": mcu.get("strict_all_mapping_mcu_aligned") is True,
    }
    failed = [name for name, value in checks.items() if not value]
    if failed:
        raise PocFailure("UNSAFE_MAPPING", f"failed evidence checks: {', '.join(failed)}")


def validate_mapping(
    part_mapping: dict[str, Any],
    *,
    dct: Any,
    parsed: dict[str, Any],
) -> dict[str, Any]:
    permutation = part_mapping.get("permutation") or {}
    mapping = permutation.get("mapping") or []
    if not mapping:
        raise PocFailure("UNSAFE_MAPPING", "permutation mapping is empty")
    source_dimensions = permutation.get("source_dimensions") or {}
    destination_dimensions = permutation.get("target_dimensions") or {}
    dimensions = (int(dct.width), int(dct.height))
    if (
        (int(source_dimensions.get("width", -1)), int(source_dimensions.get("height", -1)))
        != dimensions
        or (
            int(destination_dimensions.get("width", -1)),
            int(destination_dimensions.get("height", -1)),
        )
        != dimensions
        or (int(parsed.get("width", -1)), int(parsed.get("height", -1))) != dimensions
    ):
        raise PocFailure("UNSAFE_MAPPING", "source, destination, and JPEG dimensions differ")
    factors = np.asarray(dct.samp_factor).tolist()
    if int(dct.num_components) != 3 or any(tuple(row) != (1, 1) for row in factors):
        raise PocFailure("UNSUPPORTED_JPEG_LAYOUT", "PoC target is baseline 4:4:4 JPEG")
    mcu_width = 8 * max(int(row[0]) for row in factors)
    mcu_height = 8 * max(int(row[1]) for row in factors)
    if dimensions[0] % mcu_width or dimensions[1] % mcu_height:
        raise PocFailure("UNSAFE_MAPPING", "partial edge MCU is outside the PoC scope")
    for label, evidence in (
        ("raw JPEG", part_mapping.get("raw_jpeg") or {}),
        ("ImageBitmap", part_mapping.get("imagebitmap") or {}),
    ):
        recorded_dimensions = evidence.get("dimensions") or {}
        if recorded_dimensions and (
            int(recorded_dimensions.get("width", -1)),
            int(recorded_dimensions.get("height", -1)),
        ) != dimensions:
            raise PocFailure(
                "UNSAFE_MAPPING",
                f"{label} dimensions differ from destination canvas",
            )
    source_cells: set[tuple[int, int]] = set()
    destination_cells: set[tuple[int, int]] = set()
    tile_dimensions: set[tuple[int, int]] = set()
    component_block_counts = [0] * int(dct.num_components)
    for item in mapping:
        try:
            source_x = int(item["source_x"])
            source_y = int(item["source_y"])
            destination_x = int(item["destination_x"])
            destination_y = int(item["destination_y"])
            width = int(item["width"])
            height = int(item["height"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PocFailure("UNSAFE_MAPPING", "malformed mapping entry") from exc
        if min(source_x, source_y, destination_x, destination_y, width, height) < 0:
            raise PocFailure("UNSAFE_MAPPING", "negative mapping coordinate")
        if any(
            value % divisor
            for value, divisor in (
                (source_x, mcu_width),
                (source_y, mcu_height),
                (destination_x, mcu_width),
                (destination_y, mcu_height),
                (width, mcu_width),
                (height, mcu_height),
            )
        ):
            raise PocFailure("UNSAFE_MAPPING", "mapping is not strict MCU aligned")
        if source_x + width > dimensions[0] or source_y + height > dimensions[1]:
            raise PocFailure("UNSAFE_MAPPING", "source tile is out of bounds")
        if destination_x + width > dimensions[0] or destination_y + height > dimensions[1]:
            raise PocFailure("UNSAFE_MAPPING", "destination tile is out of bounds")
        tile_dimensions.add((width, height))
        source_mcu_x = source_x // mcu_width
        source_mcu_y = source_y // mcu_height
        destination_mcu_x = destination_x // mcu_width
        destination_mcu_y = destination_y // mcu_height
        tile_mcu_width = width // mcu_width
        tile_mcu_height = height // mcu_height
        for local_y in range(tile_mcu_height):
            for local_x in range(tile_mcu_width):
                source_cell = (source_mcu_x + local_x, source_mcu_y + local_y)
                destination_cell = (destination_mcu_x + local_x, destination_mcu_y + local_y)
                if source_cell in source_cells:
                    raise PocFailure("UNSAFE_MAPPING", "duplicate source MCU tile")
                if destination_cell in destination_cells:
                    raise PocFailure("UNSAFE_MAPPING", "duplicate destination MCU tile")
                source_cells.add(source_cell)
                destination_cells.add(destination_cell)
        for index, row in enumerate(factors):
            component_block_counts[index] += tile_mcu_width * tile_mcu_height * int(row[0]) * int(row[1])
    if len(tile_dimensions) != 1:
        raise PocFailure("UNSAFE_MAPPING", "mapping contains partial or mixed-size tiles")
    recorded_tile_dimensions = permutation.get("tile_dimensions") or {}
    if recorded_tile_dimensions and (
        int(recorded_tile_dimensions.get("width", -1)),
        int(recorded_tile_dimensions.get("height", -1)),
    ) != next(iter(tile_dimensions)):
        raise PocFailure("UNSAFE_MAPPING", "mapping tile dimensions differ from probe evidence")
    expected_cells = {
        (x, y)
        for y in range(dimensions[1] // mcu_height)
        for x in range(dimensions[0] // mcu_width)
    }
    if source_cells != expected_cells or destination_cells != expected_cells:
        raise PocFailure("UNSAFE_MAPPING", "mapping has an MCU gap or uncovered edge")
    expected_hash = part_mapping.get("permutation", {}).get("mapping_sha256")
    actual_hash = mapping_sha256(mapping)
    if expected_hash and expected_hash != actual_hash:
        raise PocFailure("UNSAFE_MAPPING", "mapping canonical hash differs")
    return {
        "tile_dimensions": [
            {"width": width, "height": height}
            for width, height in sorted(tile_dimensions)
        ],
        "tile_count": len(mapping),
        "mcu_dimensions": {"width": mcu_width, "height": mcu_height},
        "mcu_grid": {
            "width": dimensions[0] // mcu_width,
            "height": dimensions[1] // mcu_height,
        },
        "mapping_sha256": actual_hash,
        "source_mcu_cells": len(source_cells),
        "destination_mcu_cells": len(destination_cells),
        "component_block_counts": {
            name: count
            for name, count in zip(COMPONENT_NAMES, component_block_counts, strict=True)
        },
    }


def _read_arrays(dct: Any) -> dict[str, np.ndarray]:
    names = _component_names(dct)
    return {
        name: np.array(getattr(dct, name), dtype=np.int16, copy=True)
        for name in names
    }


def _apply_coefficient_mapping(
    dct: Any,
    source_arrays: dict[str, np.ndarray],
    mapping: list[dict[str, Any]],
) -> tuple[dict[str, np.ndarray], dict[str, int]]:
    factors = np.asarray(dct.samp_factor).tolist()
    mcu_width = 8 * max(int(row[0]) for row in factors)
    mcu_height = 8 * max(int(row[1]) for row in factors)
    destination_arrays = {name: array.copy() for name, array in source_arrays.items()}
    checked_blocks = {name: 0 for name in source_arrays}
    for item in mapping:
        source_mcu_x = int(item["source_x"]) // mcu_width
        source_mcu_y = int(item["source_y"]) // mcu_height
        destination_mcu_x = int(item["destination_x"]) // mcu_width
        destination_mcu_y = int(item["destination_y"]) // mcu_height
        tile_mcu_width = int(item["width"]) // mcu_width
        tile_mcu_height = int(item["height"]) // mcu_height
        for component_index, name in enumerate(source_arrays):
            h_factor, v_factor = (int(value) for value in factors[component_index])
            for local_mcu_y in range(tile_mcu_height):
                for local_mcu_x in range(tile_mcu_width):
                    for block_y in range(v_factor):
                        for block_x in range(h_factor):
                            source_y = (
                                (source_mcu_y + local_mcu_y) * v_factor + block_y
                            )
                            source_x = (
                                (source_mcu_x + local_mcu_x) * h_factor + block_x
                            )
                            destination_y = (
                                (destination_mcu_y + local_mcu_y) * v_factor + block_y
                            )
                            destination_x = (
                                (destination_mcu_x + local_mcu_x) * h_factor + block_x
                            )
                            destination_arrays[name][destination_y, destination_x] = (
                                source_arrays[name][source_y, source_x]
                            )
                            checked_blocks[name] += 1
    return destination_arrays, checked_blocks


def _coefficient_validation(
    expected: dict[str, np.ndarray],
    observed: dict[str, np.ndarray],
    checked_blocks: dict[str, int],
) -> dict[str, Any]:
    mismatched_blocks = 0
    mismatched_coefficients = 0
    components: dict[str, Any] = {}
    for name, expected_array in expected.items():
        difference = expected_array != observed[name]
        block_mask = np.any(difference, axis=(2, 3))
        blocks = int(block_mask.sum())
        coefficients = int(difference.sum())
        mismatched_blocks += blocks
        mismatched_coefficients += coefficients
        components[name] = {
            "source_blocks_checked": checked_blocks[name],
            "destination_blocks_checked": checked_blocks[name],
            "coefficient_values_checked": checked_blocks[name] * 64,
            "mismatched_blocks": blocks,
            "mismatched_coefficients": coefficients,
        }
    return {
        "components_checked": len(expected),
        "source_blocks_checked": sum(checked_blocks.values()),
        "destination_blocks_checked": sum(checked_blocks.values()),
        "coefficient_values_checked": sum(checked_blocks.values()) * 64,
        "mismatched_blocks": mismatched_blocks,
        "mismatched_coefficients": mismatched_coefficients,
        "by_component": components,
    }


def _write_reconstructed_jpeg(
    source_path: Path,
    output_path: Path,
    mapping: list[dict[str, Any]],
) -> dict[str, Any]:
    dct = jpeglib.read_dct(str(source_path))
    try:
        source_arrays = _read_arrays(dct)
        expected_arrays, checked_blocks = _apply_coefficient_mapping(
            dct,
            source_arrays,
            mapping,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists():
            raise PocFailure("UNKNOWN", f"refusing to overwrite existing output: {output_path}")
        for name, array in expected_arrays.items():
            getattr(dct, name)[...] = array
        dct.write_dct(str(output_path), quality=-1)
        output_dct = jpeglib.read_dct(str(output_path))
        try:
            observed_arrays = _read_arrays(output_dct)
            coefficients = _coefficient_validation(
                expected_arrays,
                observed_arrays,
                checked_blocks,
            )
            return {
                "coefficients": coefficients,
                "source_arrays": source_arrays,
                "expected_arrays": expected_arrays,
                "observed_arrays": observed_arrays,
                "source_dct": dct,
                "output_dct": output_dct,
            }
        except BaseException:
            output_dct.close()
            raise
    except BaseException:
        dct.close()
        raise


def _ssim(first: np.ndarray, second: np.ndarray) -> float:
    first_float = first.astype(np.float64)
    second_float = second.astype(np.float64)
    c1 = (0.01 * 255.0) ** 2
    c2 = (0.03 * 255.0) ** 2
    values = []
    for channel in range(first.shape[2]):
        left = first_float[:, :, channel]
        right = second_float[:, :, channel]
        mean_left = left.mean()
        mean_right = right.mean()
        variance_left = left.var()
        variance_right = right.var()
        covariance = ((left - mean_left) * (right - mean_right)).mean()
        numerator = (2 * mean_left * mean_right + c1) * (2 * covariance + c2)
        denominator = (
            (mean_left**2 + mean_right**2 + c1)
            * (variance_left + variance_right + c2)
        )
        values.append(float(numerator / denominator) if denominator else 1.0)
    return float(sum(values) / len(values))


def pixel_comparison(first: Image.Image, second: Image.Image) -> dict[str, Any]:
    first_array = np.asarray(first.convert("RGB"), dtype=np.int16)
    second_array = np.asarray(second.convert("RGB"), dtype=np.int16)
    if first_array.shape != second_array.shape:
        return {
            "dimensions_equal": False,
            "first_dimensions": [first.width, first.height],
            "second_dimensions": [second.width, second.height],
            "exact_pixel_equality": False,
        }
    delta = np.abs(first_array - second_array)
    differing = np.any(delta != 0, axis=2)
    rmse = math.sqrt(float(np.mean((first_array - second_array) ** 2)))
    psnr = None if rmse == 0 else float(20 * math.log10(255.0 / rmse))
    return {
        "dimensions_equal": True,
        "dimensions": [first.width, first.height],
        "exact_pixel_equality": not bool(differing.any()),
        "differing_pixel_count": int(differing.sum()),
        "differing_pixel_ratio": float(differing.mean()),
        "max_absolute_channel_difference": int(delta.max()),
        "mean_absolute_channel_difference": float(delta.mean()),
        "rmse": rmse,
        "psnr_db": psnr,
        "ssim": _ssim(first_array, second_array),
    }


def _data_url(path: Path) -> str:
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


async def browser_pixel_comparison(
    reconstructed_path: Path,
    native_path: Path,
    *,
    cdp_endpoint: str | None = None,
) -> dict[str, Any]:
    endpoint = resolve_cdp_endpoint(site="bookwalker", cli_endpoint=cdp_endpoint)
    session = await BrowserSession.connect(endpoint)
    page = await session.new_page()
    try:
        return await page.evaluate(
            """
            async ({reconstructed, native}) => {
              async function load(dataUrl) {
                const response = await fetch(dataUrl);
                return await createImageBitmap(await response.blob());
              }
              const left = await load(reconstructed);
              const right = await load(native);
              if (left.width !== right.width || left.height !== right.height) {
                left.close(); right.close();
                return {
                  available: true,
                  dimensions_equal: false,
                  exact_rgba_equal: false,
                };
              }
              const canvas = document.createElement('canvas');
              canvas.width = left.width;
              canvas.height = left.height;
              const context = canvas.getContext('2d', {willReadFrequently: true});
              context.drawImage(left, 0, 0);
              const leftData = context.getImageData(0, 0, left.width, left.height).data;
              const width = left.width;
              const height = left.height;
              context.clearRect(0, 0, left.width, left.height);
              context.drawImage(right, 0, 0);
              const rightData = context.getImageData(0, 0, right.width, right.height).data;
              let differing = 0;
              let maxDifference = 0;
              for (let index = 0; index < leftData.length; index += 4) {
                let pixelDifferent = false;
                for (let channel = 0; channel < 4; channel++) {
                  const difference = Math.abs(leftData[index + channel] - rightData[index + channel]);
                  maxDifference = Math.max(maxDifference, difference);
                  pixelDifferent ||= difference !== 0;
                }
                if (pixelDifferent) differing++;
              }
              left.close(); right.close();
              return {
                available: true,
                dimensions_equal: true,
                width,
                height,
                exact_rgba_equal: differing === 0,
                differing_pixel_count: differing,
                max_channel_difference: maxDifference,
              };
            }
            """,
            {"reconstructed": _data_url(reconstructed_path), "native": _data_url(native_path)},
        )
    finally:
        await session.close_page(page)
        await session.close()


def _load_inputs(page_dir: Path, part_number: int) -> dict[str, Any]:
    try:
        mappings = json.loads((page_dir / "part-mappings.json").read_text(encoding="utf-8"))
        metadata = json.loads((page_dir / "metadata.json").read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PocFailure("UNKNOWN", f"missing probe input: {exc.filename}") from exc
    part_mapping = next(
        (item for item in mappings if int(item.get("part", -1)) == part_number),
        None,
    )
    metadata_part = next(
        (item for item in metadata.get("parts", []) if int(item.get("part", -1)) == part_number),
        None,
    )
    if part_mapping is None or metadata_part is None:
        raise PocFailure("UNKNOWN", f"part {part_number} is missing from probe metadata")
    raw_file = (metadata_part.get("raw") or {}).get("file")
    native_file = (metadata_part.get("native") or {}).get("file")
    if not raw_file or not native_file:
        raise PocFailure("UNKNOWN", "probe metadata does not identify raw/native files")
    raw_path = page_dir / str(raw_file)
    native_path = page_dir / str(native_file)
    if not raw_path.is_file() or not native_path.is_file():
        raise PocFailure("UNKNOWN", "raw or native artifact is missing")
    expected_raw_sha = (part_mapping.get("raw_jpeg") or {}).get("sha256")
    actual_raw_sha = _sha256(raw_path.read_bytes())
    if expected_raw_sha and expected_raw_sha != actual_raw_sha:
        raise PocFailure("UNSAFE_MAPPING", "raw JPEG SHA-256 differs from part mapping")
    return {
        "part_mapping": part_mapping,
        "metadata_part": metadata_part,
        "raw_path": raw_path,
        "native_path": native_path,
        "raw_bytes": raw_path.read_bytes(),
    }


def _backend_info() -> dict[str, Any]:
    return {
        "name": "jpeglib",
        "version": getattr(jpeglib, "__version__", None),
        "read_api": "jpeglib.read_dct",
        "write_api": "DCTJPEG.write_dct",
        "coefficient_domain": True,
    }


def _summary_path(output_path: Path) -> Path:
    return output_path.parent / "summary.json"


def _root_summary_path(output_path: Path) -> Path:
    if output_path.parent.name.startswith("part-"):
        return output_path.parent.parent / "summary.json"
    return output_path.parent / "summary.json"


def _update_root_summary(output_path: Path, summary: dict[str, Any]) -> None:
    root_path = _root_summary_path(output_path)
    if root_path == _summary_path(output_path):
        root_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    root: dict[str, Any] = {}
    if root_path.is_file():
        try:
            root = json.loads(root_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            root = {}
    parts = dict(root.get("parts") or {})
    parts[str(summary.get("part"))] = summary
    root.update({
        "page_dir": summary.get("page_dir"),
        "parts": parts,
        "final_statuses": {
            key: value.get("final_status") for key, value in sorted(parts.items())
        },
    })
    root_path.parent.mkdir(parents=True, exist_ok=True)
    root_path.write_text(json.dumps(root, ensure_ascii=False, indent=2), encoding="utf-8")


def run_poc(
    *,
    page_dir: Path,
    part_number: int,
    output_path: Path,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "page_dir": str(page_dir),
        "part": part_number,
        "output": str(output_path),
        "backend": _backend_info(),
        "final_status": "UNKNOWN",
    }
    output_written = False
    dct_result: dict[str, Any] | None = None
    try:
        inputs = _load_inputs(page_dir, part_number)
        part_mapping = inputs["part_mapping"]
        validate_part_evidence(part_mapping)
        raw_bytes = inputs["raw_bytes"]
        parsed = parse_jpeg_structure(raw_bytes)
        dct = jpeglib.read_dct(str(inputs["raw_path"]))
        try:
            structure = _dct_structure(dct, parsed)
            if parsed.get("sof_marker") != "SOF0" or parsed.get("progressive"):
                raise PocFailure("UNSUPPORTED_JPEG_LAYOUT", "only baseline SOF0 is supported")
            if int(dct.num_scans) != 1:
                raise PocFailure("UNSUPPORTED_JPEG_LAYOUT", "only one sequential scan is supported")
            if int(dct.num_components) != 3 or any(
                tuple(row) != (1, 1) for row in np.asarray(dct.samp_factor).tolist()
            ):
                raise PocFailure("UNSUPPORTED_JPEG_LAYOUT", "only baseline 4:4:4 is supported")
            mapping_validation = validate_mapping(
                part_mapping,
                dct=dct,
                parsed=parsed,
            )
        finally:
            dct.close()
        mapping = (part_mapping.get("permutation") or {}).get("mapping") or []
        dct_result = _write_reconstructed_jpeg(
            inputs["raw_path"],
            output_path,
            mapping,
        )
        output_written = True
        output_bytes = output_path.read_bytes()
        output_parsed = parse_jpeg_structure(output_bytes)
        output_dct = dct_result["output_dct"]
        source_dct = dct_result["source_dct"]
        try:
            output_structure = _dct_structure(output_dct, output_parsed)
            source_component_ids = [
                component.get("id") for component in structure["components"]
            ]
            output_component_ids = [
                component.get("id") for component in output_structure["components"]
            ]
            structural_equal = {
                "dimensions_equal": (
                    output_structure["visible_dimensions"] == structure["visible_dimensions"]
                ),
                "component_count_equal": (
                    output_structure["component_count"] == structure["component_count"]
                ),
                "sampling_factors_equal": (
                    output_structure["sampling_factors"] == structure["sampling_factors"]
                ),
                "quantization_tables_equal": (
                    output_parsed.get("quantization_tables") == parsed.get("quantization_tables")
                ),
            }
        finally:
            output_dct.close()
            source_dct.close()
        with Image.open(inputs["native_path"]) as native_image:
            native = native_image.convert("RGB").copy()
        with Image.open(output_path) as reconstructed_image:
            reconstructed = reconstructed_image.convert("RGB").copy()
        pillow_pixels = pixel_comparison(reconstructed, native)
        summary.update({
            "source_jpeg_sha256": _sha256(raw_bytes),
            "output_jpeg_sha256": _sha256(output_bytes),
            "source_bytes": len(raw_bytes),
            "output_bytes": len(output_bytes),
            "visible_dimensions": structure["visible_dimensions"],
            "jpeg_structure": structure,
            "output_jpeg_structure": output_structure,
            "tile": mapping_validation,
            "coefficient_validation": dct_result["coefficients"],
            "quantization_tables_equal": structural_equal["quantization_tables_equal"],
            "component_id_validation": {
                "source_ids": source_component_ids,
                "output_ids": output_component_ids,
                "equal": source_component_ids == output_component_ids,
                "note": "jpeglib/libjpeg may normalize component IDs while preserving component order",
            },
            "structural_validation": structural_equal,
            "pillow_pixel_comparison": pillow_pixels,
            "native_png": str(inputs["native_path"]),
            "browser_pixel_comparison": {"available": False, "pending": True},
        })
        if (
            dct_result["coefficients"]["mismatched_blocks"]
            or dct_result["coefficients"]["mismatched_coefficients"]
            or not all(structural_equal.values())
        ):
            summary["final_status"] = "COEFFICIENT_MAPPING_MISMATCH"
        elif not pillow_pixels.get("exact_pixel_equality"):
            summary["final_status"] = "PIXEL_OUTPUT_MISMATCH"
        else:
            summary["final_status"] = "UNKNOWN"
    except PocFailure as exc:
        summary.update({"final_status": exc.status, "reason": exc.reason})
    except ImportError as exc:
        summary.update({
            "final_status": "BLOCKED_NO_COEFFICIENT_BACKEND",
            "reason": str(exc),
        })
    except Exception as exc:  # noqa: BLE001 - CLI report must retain failure status
        summary.update({
            "final_status": "UNKNOWN",
            "reason": f"{type(exc).__name__}: {exc}",
        })
    if not output_written and output_path.exists():
        summary["reason"] = "output already existed; no overwrite was attempted"
    return summary


async def complete_browser_validation(
    summary: dict[str, Any],
    *,
    cdp_endpoint: str | None,
    skip: bool,
) -> dict[str, Any]:
    browser_eligible = (
        not skip
        and Path(str(summary.get("output", ""))).is_file()
        and Path(str(summary.get("native_png", ""))).is_file()
        and summary.get("final_status") not in {
            "UNSAFE_MAPPING",
            "UNSUPPORTED_JPEG_LAYOUT",
            "BLOCKED_NO_COEFFICIENT_BACKEND",
        }
    )
    if not browser_eligible:
        if skip:
            summary["browser_pixel_comparison"] = {
                "available": False,
                "skipped": True,
            }
        return summary
    try:
        comparison = await browser_pixel_comparison(
            Path(str(summary["output"])),
            Path(str(summary["native_png"])),
            cdp_endpoint=cdp_endpoint,
        )
        summary["browser_pixel_comparison"] = comparison
        if (
            comparison.get("exact_rgba_equal") is True
            and summary.get("final_status") == "UNKNOWN"
        ):
            summary["final_status"] = "LOSSLESS_JPEG_RECONSTRUCTION_PROVEN"
        elif summary.get("final_status") == "UNKNOWN":
            summary["final_status"] = "PIXEL_OUTPUT_MISMATCH"
    except Exception as exc:  # noqa: BLE001 - unavailable CDP is a reportable result
        summary["browser_pixel_comparison"] = {
            "available": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
        summary["final_status"] = "UNKNOWN"
    return summary


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--page-dir", type=Path, required=True)
    parser.add_argument("--part", type=_positive_int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cdp-endpoint")
    parser.add_argument("--skip-browser-validation", action="store_true")
    args = parser.parse_args()
    summary = run_poc(
        page_dir=args.page_dir,
        part_number=args.part,
        output_path=args.output,
    )
    summary = asyncio.run(
        complete_browser_validation(
            summary,
            cdp_endpoint=args.cdp_endpoint,
            skip=args.skip_browser_validation,
        )
    )
    summary_path = _summary_path(args.output)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    _update_root_summary(args.output, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["final_status"] not in {
        "LOSSLESS_JPEG_RECONSTRUCTION_PROVEN",
        "UNKNOWN",
    }:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
