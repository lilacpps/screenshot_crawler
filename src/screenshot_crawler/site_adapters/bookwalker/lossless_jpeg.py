"""BookWalker lossless JPEG reconstruction in the quantized DCT domain."""

from __future__ import annotations

import contextlib
import math
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from screenshot_crawler.site_adapters.bookwalker.purchased_mapping import mapping_sha256

MAX_MCU_WORK = 262_144

_TIMING_KEYS = (
    "jpeg_header_and_validation_ms",
    "source_tempfile_write_ms",
    "source_dct_read_ms",
    "coefficient_array_copy_ms",
    "coefficient_rearrange_ms",
    "jpeg_dct_write_ms",
    "output_jpeg_file_read_ms",
    "output_readback_tempfile_write_ms",
    "output_dct_readback_ms",
    "coefficient_readback_compare_ms",
    "total_ms",
)


def _timing_defaults() -> dict[str, float]:
    return {key: 0.0 for key in _TIMING_KEYS}


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


@dataclass(frozen=True, slots=True)
class LosslessJpegResult:
    """Result of one bounded reconstruction attempt.

    ``data`` is populated only for a proven reconstruction.  The adapter may
    return it as a reconstructed JPEG artifact when its explicit output switch
    is enabled and every production proof gate passes.
    """

    data: bytes | None
    width: int | None
    height: int | None
    tile_dimensions: tuple[int, int] | None
    mcu_dimensions: tuple[int, int] | None
    mapping_sha256: str | None
    coefficient_validation: dict[str, Any]
    available: bool
    reason: str | None = None
    timing: dict[str, float] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.available and self.data is not None


def _mapping_values(mapping: object) -> tuple[list[dict[str, Any]], tuple[int, int] | None, tuple[int, int] | None, tuple[int, int] | None, str | None]:
    if hasattr(mapping, "mapping"):
        items = mapping.mapping  # type: ignore[attr-defined]
        source = getattr(mapping, "coded_dimensions", None) or getattr(mapping, "source_dimensions", None)
        destination = getattr(mapping, "visible_dimensions", None) or getattr(mapping, "destination_dimensions", None)
        tiles = getattr(mapping, "tile_dimensions", None)
        mapping_hash = getattr(mapping, "mapping_sha256", None)
    elif isinstance(mapping, Mapping):
        payload: Mapping[str, Any] = mapping
        if isinstance(payload.get("permutation"), Mapping):
            payload = payload["permutation"]
        items = payload.get("mapping")
        source = payload.get("coded_dimensions") or payload.get("source_dimensions")
        destination = payload.get("visible_dimensions") or payload.get("target_dimensions") or payload.get("destination_dimensions")
        tiles = payload.get("tile_dimensions")
        mapping_hash = payload.get("mapping_sha256")
    elif isinstance(mapping, (list, tuple)):
        items = mapping
        source = None
        destination = None
        tiles = None
        mapping_hash = None
    else:
        return [], None, None, None, None

    def dimensions(value: object) -> tuple[int, int] | None:
        if isinstance(value, Mapping):
            try:
                result = (_strict_integer(value["width"]), _strict_integer(value["height"]))
            except (KeyError, TypeError, ValueError):
                return None
        elif isinstance(value, (tuple, list)) and len(value) == 2:
            try:
                result = (_strict_integer(value[0]), _strict_integer(value[1]))
            except (TypeError, ValueError):
                return None
        else:
            return None
        return result if min(result) > 0 else None

    normalized_source = dimensions(source)
    normalized_destination = dimensions(destination)
    normalized_tiles = dimensions(tiles)
    if (
        (source is not None and normalized_source is None)
        or (destination is not None and normalized_destination is None)
        or (tiles is not None and normalized_tiles is None)
    ):
        return [], None, None, None, mapping_hash

    normalized: list[dict[str, Any]] = []
    if not isinstance(items, (list, tuple)):
        return [], normalized_source, normalized_destination, normalized_tiles, mapping_hash
    for item in items:
        if not isinstance(item, Mapping):
            return [], normalized_source, normalized_destination, normalized_tiles, mapping_hash
        try:
            normalized.append({
                "source_x": _strict_integer(item["source_x"] if "source_x" in item else item["sx"]),
                "source_y": _strict_integer(item["source_y"] if "source_y" in item else item["sy"]),
                "destination_x": _strict_integer(item["destination_x"] if "destination_x" in item else item["dx"]),
                "destination_y": _strict_integer(item["destination_y"] if "destination_y" in item else item["dy"]),
                "width": _strict_integer(item["width"] if "width" in item else item["sw"]),
                "height": _strict_integer(item["height"] if "height" in item else item["sh"]),
            })
        except (KeyError, TypeError, ValueError):
            return [], normalized_source, normalized_destination, normalized_tiles, mapping_hash
    return normalized, normalized_source, normalized_destination, normalized_tiles, mapping_hash


def _strict_integer(value: object) -> int:
    if isinstance(value, bool):
        raise TypeError("boolean is not integer geometry")
    number = float(value)
    if not math.isfinite(number) or number != round(number):
        raise ValueError("fractional or non-finite geometry")
    return int(number)


def _fail(
    reason: str,
    *,
    width: int | None = None,
    height: int | None = None,
    tiles: tuple[int, int] | None = None,
    mapping_hash: str | None = None,
    coefficients: dict[str, Any] | None = None,
    timing: Mapping[str, float] | None = None,
) -> LosslessJpegResult:
    return LosslessJpegResult(
        data=None,
        width=width,
        height=height,
        tile_dimensions=tiles,
        mcu_dimensions=(8, 8),
        mapping_sha256=mapping_hash,
        coefficient_validation=coefficients or {},
        available=False,
        reason=reason,
        timing=dict(_timing_defaults() if timing is None else timing),
    )


def _jpeg_header(data: bytes) -> tuple[str, int, int, int, list[tuple[int, int, tuple[int, ...]]], tuple[int, ...]] | None:
    if not data.startswith(b"\xff\xd8"):
        return None
    offset = 2
    quantization: list[tuple[int, int, tuple[int, ...]]] = []
    while offset + 1 < len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            return None
        marker = data[offset]
        offset += 1
        if marker == 0xDA:
            return None
        if marker == 0xD9:
            return None
        if marker in {0xD8, *range(0xD0, 0xD8), 0x01}:
            continue
        if offset + 2 > len(data):
            return None
        length = int.from_bytes(data[offset : offset + 2], "big")
        if length < 2 or offset + length > len(data):
            return None
        payload = data[offset + 2 : offset + length]
        if marker == 0xDB:
            cursor = 0
            while cursor < len(payload):
                info = payload[cursor]
                cursor += 1
                precision = info >> 4
                table_id = info & 0x0F
                value_size = 2 if precision else 1
                byte_count = 64 * value_size
                if cursor + byte_count > len(payload):
                    return None
                if precision:
                    values = tuple(
                        int.from_bytes(payload[index : index + 2], "big")
                        for index in range(cursor, cursor + byte_count, 2)
                    )
                else:
                    values = tuple(payload[cursor : cursor + byte_count])
                quantization.append((table_id, precision, values))
                cursor += byte_count
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            if len(payload) < 6:
                return None
            components = payload[5]
            if len(payload) < 6 + (3 * components):
                return None
            component_selectors = tuple(
                payload[8 + (3 * index)] for index in range(components)
            )
            return (
                {0xC0: "SOF0", 0xC1: "SOF1", 0xC2: "SOF2", 0xC3: "SOF3"}.get(marker, f"0x{marker:02x}"),
                int.from_bytes(payload[3:5], "big"),
                int.from_bytes(payload[1:3], "big"),
                components,
                quantization,
                component_selectors,
            )
        offset += length
    return None


def _read_dct(
    data: bytes,
    jpeglib: object,
    *,
    timing: dict[str, float] | None = None,
    tempfile_key: str | None = None,
    read_key: str | None = None,
) -> tuple[object, Path]:
    write_started = time.perf_counter()
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as handle:
        path = Path(handle.name)
        handle.write(data)
    if timing is not None and tempfile_key is not None:
        timing[tempfile_key] = _elapsed_ms(write_started)
    try:
        read_started = time.perf_counter()
        result = jpeglib.read_dct(str(path))  # type: ignore[attr-defined]
        if timing is not None and read_key is not None:
            timing[read_key] = _elapsed_ms(read_started)
        return result, path
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _write_dct(
    dct: object,
    arrays: Mapping[str, object],
    jpeglib: object,
    *,
    timing: dict[str, float] | None = None,
) -> tuple[bytes, Path]:
    for name, array in arrays.items():
        getattr(dct, name)[...] = array
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as handle:
        path = Path(handle.name)
    try:
        write_started = time.perf_counter()
        dct.write_dct(str(path), quality=-1)  # type: ignore[attr-defined]
        if timing is not None:
            timing["jpeg_dct_write_ms"] = _elapsed_ms(write_started)
        read_started = time.perf_counter()
        output = path.read_bytes()
        if timing is not None:
            timing["output_jpeg_file_read_ms"] = _elapsed_ms(read_started)
        return output, path
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _array_equal(first: object, second: object) -> bool:
    import numpy as np

    return bool(np.array_equal(np.asarray(first), np.asarray(second)))


def _supported_dct_layout(dct: Any, numpy_module: Any) -> tuple[object, ...] | None:
    """Return the supported jpeglib layout, or ``None`` if it is unsafe."""

    try:
        factors = tuple(
            tuple(int(value) for value in row)
            for row in numpy_module.asarray(dct.samp_factor).tolist()
        )
        layout = (
            int(dct.num_components),
            factors,
            bool(dct.progressive_mode),
            int(dct.num_scans),
        )
    except (AttributeError, TypeError, ValueError):
        return None
    if layout != (3, ((1, 1), (1, 1), (1, 1)), False, 1):
        return None
    return layout


def reconstruct_lossless_jpeg(
    jpeg_bytes: bytes,
    mapping: object,
) -> LosslessJpegResult:
    """Reorder quantized DCT blocks without RGB decode/re-encode.

    The function is intentionally fail-closed: an unsupported JPEG or unsafe
    mapping returns an unavailable result and never leaves a temporary file.
    """

    reconstruction_started = time.perf_counter()
    timing = _timing_defaults()
    items, source_dimensions, destination_dimensions, tile_dimensions, mapping_hash = _mapping_values(mapping)
    if not mapping_hash:
        mapping_hash = None
    if not isinstance(jpeg_bytes, bytes):
        return _fail("invalid JPEG bytes", tiles=tile_dimensions, mapping_hash=mapping_hash)
    header = _jpeg_header(jpeg_bytes)
    if header is None:
        return _fail("invalid JPEG structure", tiles=tile_dimensions, mapping_hash=mapping_hash)
    sof, header_width, header_height, header_components, quantization, component_selectors = header
    if source_dimensions is None:
        source_dimensions = (header_width, header_height)
    if destination_dimensions is None:
        destination_dimensions = (header_width, header_height)
    if tile_dimensions is None and items:
        try:
            tile_dimensions = (int(items[0]["width"]), int(items[0]["height"]))
        except (KeyError, TypeError, ValueError):
            return _fail("mapping is malformed", width=header_width, height=header_height)
    if items:
        try:
            computed_mapping_hash = mapping_sha256(items)
        except (KeyError, TypeError, ValueError):
            return _fail("mapping is malformed", width=header_width, height=header_height)
        if mapping_hash is not None and mapping_hash != computed_mapping_hash:
            return _fail(
                "mapping hash mismatch",
                width=header_width,
                height=header_height,
                tiles=tile_dimensions,
                mapping_hash=mapping_hash,
            )
        mapping_hash = computed_mapping_hash
    if sof != "SOF0" or header_components != 3:
        return _fail("UNSUPPORTED_JPEG_LAYOUT", width=header_width, height=header_height, tiles=tile_dimensions, mapping_hash=mapping_hash)
    if source_dimensions != (header_width, header_height):
        return _fail("coded JPEG dimensions do not match mapping", width=header_width, height=header_height, tiles=tile_dimensions, mapping_hash=mapping_hash)
    if destination_dimensions is None or any(value <= 0 for value in destination_dimensions):
        return _fail("visible dimensions are unavailable", width=header_width, height=header_height, tiles=tile_dimensions, mapping_hash=mapping_hash)
    cropped = destination_dimensions != source_dimensions
    if (
        destination_dimensions[0] > source_dimensions[0]
        or destination_dimensions[1] > source_dimensions[1]
        or source_dimensions[0] - destination_dimensions[0] >= 8
        or source_dimensions[1] - destination_dimensions[1] >= 8
    ):
        return _fail("visible crop is outside the final MCU", width=header_width, height=header_height, tiles=tile_dimensions, mapping_hash=mapping_hash)
    if not items or tile_dimensions is None:
        return _fail("mapping is unavailable", width=header_width, height=header_height, mapping_hash=mapping_hash)
    if header_width % 8 or header_height % 8:
        return _fail("partial edge MCU is outside the supported scope", width=header_width, height=header_height, tiles=tile_dimensions, mapping_hash=mapping_hash)
    if any(value % 8 for item in items for value in (item["source_x"], item["source_y"], item["destination_x"], item["destination_y"], item["width"], item["height"])):
        return _fail("mapping is not strict MCU aligned", width=header_width, height=header_height, tiles=tile_dimensions, mapping_hash=mapping_hash)
    if not cropped and any((item["width"], item["height"]) != tile_dimensions for item in items):
        return _fail("mapping tile dimensions are not uniform", width=header_width, height=header_height, tiles=tile_dimensions, mapping_hash=mapping_hash)
    if min(tile_dimensions) <= 0:
        return _fail("mapping tile dimensions are invalid", width=header_width, height=header_height, tiles=tile_dimensions, mapping_hash=mapping_hash)
    if not cropped and (header_width % tile_dimensions[0] or header_height % tile_dimensions[1]):
        return _fail("mapping tile grid is incomplete", width=header_width, height=header_height, tiles=tile_dimensions, mapping_hash=mapping_hash)
    coded_mcu_count = (header_width // 8) * (header_height // 8)
    tile_mcu_count = 0
    for item in items:
        if item["width"] <= 0 or item["height"] <= 0:
            return _fail("mapping tile dimensions are invalid", width=header_width, height=header_height, tiles=tile_dimensions, mapping_hash=mapping_hash)
        if (
            item["source_x"] < 0
            or item["source_y"] < 0
            or item["destination_x"] < 0
            or item["destination_y"] < 0
            or item["source_x"] + item["width"] > header_width
            or item["source_y"] + item["height"] > header_height
            or item["destination_x"] + item["width"] > header_width
            or item["destination_y"] + item["height"] > header_height
        ):
            return _fail("mapping geometry is out of bounds", width=header_width, height=header_height, tiles=tile_dimensions, mapping_hash=mapping_hash)
        tile_mcu_count += (item["width"] // 8) * (item["height"] // 8)
        if coded_mcu_count + tile_mcu_count > MAX_MCU_WORK:
            return _fail("mapping exceeds MCU work bound", width=header_width, height=header_height, tiles=tile_dimensions, mapping_hash=mapping_hash)
    expected = {(x, y) for y in range(0, header_height, 8) for x in range(0, header_width, 8)}
    source_positions = []
    destination_positions = []
    for item in items:
        source_positions.extend(
            (x, y)
            for y in range(item["source_y"], item["source_y"] + item["height"], 8)
            for x in range(item["source_x"], item["source_x"] + item["width"], 8)
        )
        destination_positions.extend(
            (x, y)
            for y in range(item["destination_y"], item["destination_y"] + item["height"], 8)
            for x in range(item["destination_x"], item["destination_x"] + item["width"], 8)
        )
    if (
        set(source_positions) != expected
        or set(destination_positions) != expected
        or len(set(source_positions)) != len(source_positions)
        or len(set(destination_positions)) != len(destination_positions)
        or any(item["source_x"] + item["width"] > header_width or item["source_y"] + item["height"] > header_height for item in items)
        or any(item["destination_x"] + item["width"] > header_width or item["destination_y"] + item["height"] > header_height for item in items)
        or any(
            (x >= destination_dimensions[0] and x != header_width - 8)
            or (y >= destination_dimensions[1] and y != header_height - 8)
            for x, y in destination_positions
        )
    ):
        return _fail("mapping is not a complete bijection", width=header_width, height=header_height, tiles=tile_dimensions, mapping_hash=mapping_hash)

    timing["jpeg_header_and_validation_ms"] = _elapsed_ms(reconstruction_started)

    try:
        import jpeglib  # type: ignore[import-not-found]
        import numpy as np  # type: ignore[import-not-found]
    except (ImportError, OSError):
        return _fail("BLOCKED_NO_COEFFICIENT_BACKEND", width=header_width, height=header_height, tiles=tile_dimensions, mapping_hash=mapping_hash)

    source_dct = None
    output_dct = None
    source_path: Path | None = None
    output_path: Path | None = None
    try:
        source_dct, source_path = _read_dct(
            jpeg_bytes,
            jpeglib,
            timing=timing,
            tempfile_key="source_tempfile_write_ms",
            read_key="source_dct_read_ms",
        )
        if int(source_dct.width) != header_width or int(source_dct.height) != header_height:
            return _fail("DCT dimensions differ from JPEG header", width=header_width, height=header_height, tiles=tile_dimensions, mapping_hash=mapping_hash)
        source_layout = _supported_dct_layout(source_dct, np)
        if source_layout is None:
            return _fail("UNSUPPORTED_JPEG_LAYOUT", width=header_width, height=header_height, tiles=tile_dimensions, mapping_hash=mapping_hash)
        names = ("Y", "Cb", "Cr")
        copy_started = time.perf_counter()
        original = {name: np.array(getattr(source_dct, name), dtype=np.int16, copy=True) for name in names}
        expected_arrays = {name: array.copy() for name, array in original.items()}
        timing["coefficient_array_copy_ms"] = _elapsed_ms(copy_started)
        checked_blocks = 0
        rearrange_started = time.perf_counter()
        for item in items:
            source_x = item["source_x"] // 8
            source_y = item["source_y"] // 8
            destination_x = item["destination_x"] // 8
            destination_y = item["destination_y"] // 8
            width = item["width"] // 8
            height = item["height"] // 8
            for name in names:
                expected_arrays[name][destination_y:destination_y + height, destination_x:destination_x + width] = original[name][source_y:source_y + height, source_x:source_x + width]
            checked_blocks += width * height
        timing["coefficient_rearrange_ms"] = _elapsed_ms(rearrange_started)
        if cropped:
            # jpeglib keeps the coded MCU arrays while changing only the SOF
            # visible frame.  This is the encoded equivalent of clipping
            # the final destination MCU row/column; it does not decode/
            # re-encode RGB.
            source_dct.width = destination_dimensions[0]
            output_height = destination_dimensions[1]
            source_dct.height = output_height
        output_bytes, output_path = _write_dct(
            source_dct,
            expected_arrays,
            jpeglib,
            timing=timing,
        )
        output_dct, output_path_read = _read_dct(
            output_bytes,
            jpeglib,
            timing=timing,
            tempfile_key="output_readback_tempfile_write_ms",
            read_key="output_dct_readback_ms",
        )
        # The second path is distinct from the write path and is cleaned below.
        readback_path = output_path_read
        try:
            output_layout = _supported_dct_layout(output_dct, np)
            if output_layout is None or output_layout != source_layout:
                return _fail(
                    "UNSUPPORTED_JPEG_LAYOUT",
                    width=header_width,
                    height=header_height,
                    tiles=tile_dimensions,
                    mapping_hash=mapping_hash,
                )
            compare_started = time.perf_counter()
            observed = {name: np.array(getattr(output_dct, name), dtype=np.int16, copy=True) for name in names}
            mismatched_blocks = 0
            mismatched_coefficients = 0
            by_component: dict[str, Any] = {}
            for name in names:
                difference = expected_arrays[name] != observed[name]
                mismatched_blocks += int(np.any(difference, axis=(2, 3)).sum())
                mismatched_coefficients += int(difference.sum())
                by_component[name] = {
                    "source_blocks_checked": checked_blocks,
                    "destination_blocks_checked": checked_blocks,
                    "coefficient_values_checked": checked_blocks * 64,
                    "mismatched_blocks": int(np.any(difference, axis=(2, 3)).sum()),
                    "mismatched_coefficients": int(difference.sum()),
                }
            quantization_tables_equal = _array_equal(source_dct.qt, output_dct.qt)
            output_component_selectors = _jpeg_header(output_bytes)
            component_selectors_equal = bool(
                output_component_selectors is not None
                and output_component_selectors[5] == component_selectors
            )
            coefficient_validation = {
                "components_checked": 3,
                "source_blocks_checked": checked_blocks * 3,
                "destination_blocks_checked": checked_blocks * 3,
                "coefficient_values_checked": checked_blocks * 3 * 64,
                "mismatched_blocks": mismatched_blocks,
                "mismatched_coefficients": mismatched_coefficients,
                "quantization_tables_equal": quantization_tables_equal,
                "component_quantization_selectors_equal": component_selectors_equal,
                "source_component_quantization_selectors": list(component_selectors),
                "output_component_quantization_selectors": (
                    list(output_component_selectors[5])
                    if output_component_selectors is not None else None
                ),
                "by_component": by_component,
            }
            timing["coefficient_readback_compare_ms"] = _elapsed_ms(compare_started)
            if mismatched_blocks or mismatched_coefficients:
                return _fail("COEFFICIENT_MAPPING_MISMATCH", width=header_width, height=header_height, tiles=tile_dimensions, mapping_hash=mapping_hash, coefficients=coefficient_validation)
            if not quantization_tables_equal:
                return _fail("QUANTIZATION_TABLE_MISMATCH", width=header_width, height=header_height, tiles=tile_dimensions, mapping_hash=mapping_hash, coefficients=coefficient_validation)
            if not component_selectors_equal:
                return _fail("COMPONENT_QUANTIZATION_SELECTOR_MISMATCH", width=header_width, height=header_height, tiles=tile_dimensions, mapping_hash=mapping_hash, coefficients=coefficient_validation)
            output_header = _jpeg_header(output_bytes)
            if output_header is None or output_header[0] != "SOF0" or output_header[1:4] != (destination_dimensions[0], destination_dimensions[1], 3) or output_header[4] != quantization or output_header[5] != component_selectors:
                return _fail("JPEG structure changed during reconstruction", width=header_width, height=header_height, tiles=tile_dimensions, mapping_hash=mapping_hash, coefficients=coefficient_validation)
            return LosslessJpegResult(
                data=output_bytes,
                width=destination_dimensions[0],
                height=destination_dimensions[1],
                tile_dimensions=tile_dimensions,
                mcu_dimensions=(8, 8),
                mapping_sha256=mapping_hash,
                coefficient_validation=coefficient_validation,
                available=True,
                timing={
                    **timing,
                    "total_ms": _elapsed_ms(reconstruction_started),
                },
            )
        finally:
            with contextlib.suppress(Exception):
                output_dct.close()
            readback_path.unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001 - shadow optimization must fail closed
        timing["total_ms"] = _elapsed_ms(reconstruction_started)
        return _fail(
            f"reconstruction failed: {type(exc).__name__}",
            width=header_width,
            height=header_height,
            tiles=tile_dimensions,
            mapping_hash=mapping_hash,
            timing=timing,
        )
    finally:
        if output_dct is not None:
            with contextlib.suppress(Exception):
                output_dct.close()
        if source_dct is not None:
            with contextlib.suppress(Exception):
                source_dct.close()
        if source_path is not None:
            source_path.unlink(missing_ok=True)
        if output_path is not None:
            output_path.unlink(missing_ok=True)


reconstruct_jpeg_lossless = reconstruct_lossless_jpeg
