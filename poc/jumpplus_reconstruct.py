"""J2 PoC: reconstruct Jump+ canvas output from transport JPEG draw mappings.

This is diagnostic code only.  It consumes a completed J1 output directory and
does not connect to a browser or change production capture behavior.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import itertools
import json
import math
import tempfile
from collections import Counter
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageStat, UnidentifiedImageError

DEFAULT_INPUT_DIR = Path("output/jumpplus_probe")
DEFAULT_OUTPUT_DIR = Path("output/jumpplus_probe/j2")
IDENTITY = {"a": 1, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0}


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def decoded_pixel_sha256(image: Image.Image) -> str:
    """Hash RGB pixels, independent of PNG/JPEG encoding."""

    return hashlib.sha256(image.convert("RGB").tobytes()).hexdigest()


def _is_identity_transform(transform: dict[str, Any] | None) -> bool:
    return bool(transform) and all(transform.get(key) == value for key, value in IDENTITY.items())


def _integer_value(value: Any) -> int | None:
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    integer = round(value)
    return integer if abs(value - integer) < 1e-6 else None


def _rect_values(rect: dict[str, Any] | None, keys: tuple[str, ...]) -> tuple[int, ...] | None:
    if not rect:
        return None
    values = tuple(_integer_value(rect.get(key)) for key in keys)
    return values if all(value is not None for value in values) else None


def classify_draw_stage(draws: list[dict[str, Any]]) -> str:
    """Describe full-frame and tile calls without assuming one is disposable."""

    full = 0
    partial = 0
    for draw in draws:
        source = draw.get("source") or {}
        source_rect = draw.get("sourceRect") or {}
        destination = draw.get("destinationRect") or {}
        if (
            source_rect.get("sx") == 0
            and source_rect.get("sy") == 0
            and source_rect.get("sw") == source.get("naturalWidth")
            and source_rect.get("sh") == source.get("naturalHeight")
            and destination.get("dx") == 0
            and destination.get("dy") == 0
            and destination.get("dw") == (draw.get("canvas") or {}).get("width")
            and destination.get("dh") == (draw.get("canvas") or {}).get("height")
        ):
            full += 1
        else:
            partial += 1
    if full and partial:
        return "full_frame_plus_tiles"
    if full:
        return "full_frame_only"
    if partial:
        return "tiles_only"
    return "unknown"


def _visual_comparison(reconstructed: Image.Image, reference_path: Path, difference_path: Path) -> dict[str, Any]:
    """Compare only as a visual reference; this is not canvas pixel ground truth."""

    with Image.open(reference_path) as reference_source:
        reference = reference_source.convert("RGB")
        rendered = reconstructed.convert("RGB")
        resized_for_comparison = rendered.size != reference.size
        if rendered.size != reference.size:
            rendered = rendered.resize(reference.size, Image.Resampling.LANCZOS)
        difference = ImageChops.difference(rendered, reference)
        means = ImageStat.Stat(difference).mean
        pixels = reference.width * reference.height
        max_channel = max(channel.getextrema()[1] for channel in (
            difference.getchannel(0), difference.getchannel(1), difference.getchannel(2)
        ))
        nonzero = sum(value != 0 for value in difference.convert("L").tobytes())
        difference_path.parent.mkdir(parents=True, exist_ok=True)
        difference.save(difference_path)
        return {
            "reference_file": str(reference_path),
            "reference_dimensions": [reference.width, reference.height],
            "resized_for_comparison": resized_for_comparison,
            "mean_absolute_difference": sum(means) / 3,
            "max_channel_difference": max_channel,
            "different_pixel_count": nonzero,
            "different_pixel_ratio": nonzero / pixels if pixels else 0.0,
            "difference_file": str(difference_path),
            "assessment": "close" if sum(means) / 3 <= 12 else "visual_mismatch",
        }


def _candidate_index(candidate_images: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidate_images:
        pixel_sha = candidate.get("pixel_sha256")
        if pixel_sha:
            result.setdefault(str(pixel_sha), []).append(candidate)
    return result


def select_transport_candidate(
    source_pixel_sha256: str | None,
    candidates: list[dict[str, Any]],
    *,
    load_bytes: Callable[[dict[str, Any]], bytes] | None = None,
    analyze_candidate: Callable[[dict[str, Any], bytes], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Select a transport JPEG only after proving candidate equivalence.

    A single pixel-SHA candidate is safe to select.  Multiple candidates are
    accepted only when their raw bytes or their JPEG image-domain content is
    identical.  The returned ``selected_candidate`` is intentionally absent
    for an ambiguous set; callers may use ``pixel_fallback_candidate`` only
    for decoded-pixel reconstruction.
    """

    matching = [
        candidate for candidate in candidates
        if source_pixel_sha256 and str(candidate.get("pixel_sha256") or "") == source_pixel_sha256
    ]
    result: dict[str, Any] = {
        "selected_candidate": None,
        "pixel_fallback_candidate": None,
        "selection_status": "unmatched",
        "selection_reason": "no_pixel_sha_match",
        "candidate_count": len(matching),
        "equivalent_candidate_count": 0,
        "metadata_equivalent": None,
    }
    if not matching:
        return result
    if len(matching) == 1:
        candidate = next(iter(matching))
        result.update({
            "selected_candidate": candidate,
            "pixel_fallback_candidate": candidate,
            "selection_status": "unique",
            "selection_reason": "single_pixel_match",
            "equivalent_candidate_count": 1,
            "metadata_equivalent": True,
        })
        return result

    if load_bytes is None:
        result.update({
            "selection_status": "ambiguous",
            "selection_reason": "candidate_equivalence_unproven",
            "pixel_fallback_candidate": next(iter(matching)),
        })
        return result
    raw_sha256: list[str] = []
    raw_bytes: dict[int, bytes] = {}
    try:
        for index, candidate in enumerate(matching):
            data = load_bytes(candidate)
            raw_bytes[index] = data
            raw_sha256.append(hashlib.sha256(data).hexdigest())
    except Exception as exc:  # noqa: BLE001 - candidate ambiguity fails closed
        result.update({
            "selection_status": "ambiguous",
            "selection_reason": "candidate_equivalence_unproven",
            "pixel_fallback_candidate": next(iter(matching)),
            "selection_error": f"{type(exc).__name__}: {exc}",
        })
        return result

    if len(set(raw_sha256)) == 1:
        result.update({
            "selected_candidate": next(iter(matching)),
            "pixel_fallback_candidate": next(iter(matching)),
            "selection_status": "equivalent_multiple",
            "selection_reason": "identical_raw_sha256",
            "equivalent_candidate_count": len(matching),
            "metadata_equivalent": True,
        })
        return result

    signatures: list[dict[str, Any]] = []
    try:
        for index, candidate in enumerate(matching):
            if analyze_candidate is None:
                raise ValueError("JPEG candidate analyzer is unavailable")
            signatures.append(analyze_candidate(candidate, raw_bytes[index]))
    except Exception as exc:  # noqa: BLE001 - candidate ambiguity fails closed
        result.update({
            "selection_status": "ambiguous",
            "selection_reason": "candidate_equivalence_unproven",
            "pixel_fallback_candidate": next(iter(matching)),
            "selection_error": f"{type(exc).__name__}: {exc}",
        })
        return result

    content_keys = [signature.get("content_key") for signature in signatures]
    equivalent_count = sum(key == content_keys[0] for key in content_keys)
    metadata_keys = [signature.get("metadata_key") for signature in signatures]
    metadata_equivalent = len(set(metadata_keys)) == 1
    if len(set(content_keys)) == 1:
        result.update({
            "selected_candidate": next(iter(matching)),
            "pixel_fallback_candidate": next(iter(matching)),
            "selection_status": "equivalent_multiple",
            "selection_reason": "identical_dct_image_content",
            "equivalent_candidate_count": equivalent_count,
            "metadata_equivalent": metadata_equivalent,
        })
        return result

    result.update({
        "selection_status": "ambiguous",
        "selection_reason": "multiple_pixel_equal_but_dct_distinct_candidates",
        "equivalent_candidate_count": equivalent_count,
        "metadata_equivalent": metadata_equivalent,
        "pixel_fallback_candidate": next(iter(matching)),
    })
    return result


def _analyze_jpeg_candidate(candidate: dict[str, Any], data: bytes) -> dict[str, Any]:
    """Return a comparable JPEG image-domain signature for candidate selection."""

    dimensions = jpeg_dimensions(data)
    sampling = jpeg_sampling_factors(data)
    if dimensions is None or sampling is None:
        raise ValueError("invalid JPEG dimensions or sampling factors")
    import numpy as np  # type: ignore[import-not-found]

    dct, temporary_path = _read_dct(data)
    try:
        component_names = [
            name for name in ("Y", "Cb", "Cr") if getattr(dct, name, None) is not None
        ]
        if not component_names:
            raise ValueError("JPEG has no supported DCT components")
        coefficient_hashes = tuple(
            (name, hashlib.sha256(np.asarray(getattr(dct, name)).tobytes()).hexdigest())
            for name in component_names
        )
        quant_hash = hashlib.sha256(np.asarray(dct.qt).tobytes()).hexdigest()
        quant_number_hash = hashlib.sha256(np.asarray(dct.quant_tbl_no).tobytes()).hexdigest()
        content_key = (
            tuple(dimensions),
            tuple(tuple(item) for item in sampling),
            quant_hash,
            quant_number_hash,
            coefficient_hashes,
        )
        metadata_key = tuple(_jpeg_marker_payloads(data))
        return {
            "content_key": content_key,
            "metadata_key": metadata_key,
            "raw_sha256": hashlib.sha256(data).hexdigest(),
        }
    finally:
        with suppress(Exception):
            dct.close()
        with suppress(OSError):
            temporary_path.unlink(missing_ok=True)


def _jpeg_sof(data: bytes) -> tuple[int, int, tuple[tuple[int, int], ...]] | None:
    """Read JPEG dimensions and sampling factors without decoding the image."""

    if len(data) < 4 or data[:3] != b"\xff\xd8\xff":
        return None
    index = 2
    sof_markers = set(range(0xC0, 0xC4)) | set(range(0xC5, 0xC8))
    sof_markers |= set(range(0xC9, 0xCC)) | set(range(0xCD, 0xD0))
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
        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        if index + 2 > len(data):
            break
        length = int.from_bytes(data[index:index + 2], "big")
        if length < 2 or index + length > len(data):
            break
        if marker in sof_markers and length >= 8:
            height = int.from_bytes(data[index + 3:index + 5], "big")
            width = int.from_bytes(data[index + 5:index + 7], "big")
            components = data[index + 7]
            end = index + 8 + 3 * components
            if not width or not height or end > index + length:
                return None
            factors = tuple(
                (data[offset + 1] >> 4, data[offset + 1] & 0x0F)
                for offset in range(index + 8, end, 3)
            )
            if any(horizontal < 1 or vertical < 1 for horizontal, vertical in factors):
                return None
            return width, height, factors
        index += length
    return None


def jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    sof = _jpeg_sof(data)
    return sof[:2] if sof else None


def jpeg_sampling_factors(data: bytes) -> list[list[int]] | None:
    sof = _jpeg_sof(data)
    return [list(item) for item in sof[2]] if sof else None


def jpeg_mcu_dimensions(data: bytes) -> tuple[int, int] | None:
    sof = _jpeg_sof(data)
    if not sof:
        return None
    factors = sof[2]
    return 8 * max(item[0] for item in factors), 8 * max(item[1] for item in factors)


def _rect_coverage(rectangles: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int] | None:
    """Return a bounding box only when rectangles partition it without overlap/gaps."""

    if not rectangles or any(width <= 0 or height <= 0 for _, _, width, height in rectangles):
        return None
    x_values = sorted({value for x, _, width, _ in rectangles for value in (x, x + width)})
    y_values = sorted({value for _, y, _, height in rectangles for value in (y, y + height)})
    for y0, y1 in itertools.pairwise(y_values):
        for x0, x1 in itertools.pairwise(x_values):
            count = sum(
                x <= x0 and x + width >= x1 and y <= y0 and y + height >= y1
                for x, y, width, height in rectangles
            )
            if count != 1:
                return None
    return x_values[0], y_values[0], x_values[-1], y_values[-1]


def _coverage_is_inside(
    coverage: tuple[int, int, int, int] | None,
    image_size: tuple[int, int],
) -> bool:
    return bool(
        coverage
        and coverage[0] == 0
        and coverage[1] == 0
        and 0 < coverage[2] <= image_size[0]
        and 0 < coverage[3] <= image_size[1]
    )


def dct_lossless_feasibility(
    *,
    jpeg_bytes: bytes,
    source_rectangles: list[tuple[int, int, int, int]],
    destination_rectangles: list[tuple[int, int, int, int]],
    canvas_size: tuple[int, int],
) -> dict[str, Any]:
    """Check only the structural preconditions for a coefficient tile reorder."""

    dimensions = jpeg_dimensions(jpeg_bytes)
    sampling = jpeg_sampling_factors(jpeg_bytes)
    mcu = jpeg_mcu_dimensions(jpeg_bytes)
    result: dict[str, Any] = {
        "status": "unknown",
        "feasible": False,
        "jpeg_dimensions": list(dimensions) if dimensions else None,
        "sampling_factors": sampling,
        "mcu": list(mcu) if mcu else None,
    }
    if not dimensions or not sampling or not mcu:
        result["reason"] = "invalid_or_unsupported_jpeg_header"
        return result
    if dimensions != canvas_size:
        result["status"] = "infeasible"
        result["reason"] = "jpeg_dimensions_do_not_match_canvas"
        return result
    mcu_width, mcu_height = mcu
    values = [value for rect in source_rectangles + destination_rectangles for value in rect]
    if any(value < 0 for value in values):
        result["status"] = "infeasible"
        result["reason"] = "negative_tile_geometry"
        return result
    for x, y, width, height in source_rectangles + destination_rectangles:
        if any((value % unit) for value, unit in (
            (x, mcu_width), (width, mcu_width), (y, mcu_height), (height, mcu_height)
        )):
            result["status"] = "infeasible"
            result["reason"] = "tile_geometry_not_mcu_aligned"
            result["offending_rectangle"] = [x, y, width, height]
            return result
    source_coverage = _rect_coverage(source_rectangles)
    destination_coverage = _rect_coverage(destination_rectangles)
    result["source_coverage"] = list(source_coverage) if source_coverage else None
    result["destination_coverage"] = list(destination_coverage) if destination_coverage else None
    result["source_area"] = sum(width * height for _, _, width, height in source_rectangles)
    result["destination_area"] = sum(width * height for _, _, width, height in destination_rectangles)
    if not _coverage_is_inside(source_coverage, dimensions):
        result["status"] = "infeasible"
        result["reason"] = "source_tiles_have_gap_overlap_or_invalid_extent"
        return result
    if not _coverage_is_inside(destination_coverage, canvas_size):
        result["status"] = "infeasible"
        result["reason"] = "destination_tiles_have_gap_overlap_or_invalid_extent"
        return result
    if source_coverage[2:] != destination_coverage[2:]:
        result["status"] = "infeasible"
        result["reason"] = "source_destination_coverage_extent_differs"
        return result
    if result["source_area"] != result["destination_area"]:
        result["status"] = "infeasible"
        result["reason"] = "source_destination_area_differs"
        return result
    result["status"] = "feasible"
    result["feasible"] = True
    result["reason"] = "coverage_and_mcu_alignment_valid"
    return result


def _state_paths(input_dir: Path, report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result = {}
    for state in report.get("states", []):
        name = str(state.get("state"))
        pixels_path = input_dir / "j1" / name / "pixels.json"
        if pixels_path.exists():
            result[name] = json.loads(pixels_path.read_text(encoding="utf-8"))
    return result


def _source_artifacts_by_id(pixels: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    result: dict[int, list[dict[str, Any]]] = {}
    for item in pixels.get("source_artifacts", []):
        if item.get("sourceId") is not None:
            result.setdefault(int(item["sourceId"]), []).append(item)
    return result


def _source_artifact_for_draw(
    source_by_id: dict[int, list[dict[str, Any]]],
    source_id: int | None,
    draw_url: str | None,
) -> tuple[dict[str, Any] | None, str]:
    """Require the stable source snapshot URL to equal the draw-time URL."""

    if source_id is None:
        return None, "unmatched"
    artifacts = source_by_id.get(source_id, [])
    exact = [item for item in artifacts if str(item.get("url") or "") == str(draw_url or "")]
    if exact:
        return exact[0], "confirmed"
    if artifacts:
        return None, "changed_after_draw"
    return None, "unmatched"


def _canvas_artifacts_by_id(pixels: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {
        int(item["canvasId"]): item
        for item in pixels.get("canvas_artifacts", [])
        if item.get("canvasId") is not None
    }


def _relative_path(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def _jpeg_marker_payloads(data: bytes) -> list[tuple[int, bytes]]:
    if not data.startswith(b"\xff\xd8"):
        return []
    result: list[tuple[int, bytes]] = []
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
        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            result.append((marker, b""))
            if marker == 0xD9:
                break
            continue
        if marker == 0xDA or index + 2 > len(data):
            break
        length = int.from_bytes(data[index:index + 2], "big")
        if length < 2 or index + length > len(data):
            break
        result.append((marker, data[index + 2:index + length]))
        index += length
    return result


def _marker_payloads(data: bytes, marker: int) -> list[bytes]:
    return [payload for current, payload in _jpeg_marker_payloads(data) if current == marker]


def _metadata_preserved(source: bytes, output: bytes) -> bool:
    wanted = [
        item for item in _jpeg_marker_payloads(source)
        if 0xE0 <= item[0] <= 0xEF or item[0] == 0xFE
    ]
    available = [
        item for item in _jpeg_marker_payloads(output)
        if 0xE0 <= item[0] <= 0xEF or item[0] == 0xFE
    ]
    position = 0
    for item in wanted:
        try:
            position = available.index(item, position) + 1
        except ValueError:
            return False
    return True


def _read_dct(data: bytes) -> tuple[Any, Path]:
    import jpeglib  # type: ignore[import-not-found]

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as handle:
        path = Path(handle.name)
        handle.write(data)
    try:
        return jpeglib.read_dct(str(path)), path
    except BaseException:
        with suppress(OSError):
            path.unlink(missing_ok=True)
        raise


def _write_dct(dct: Any, arrays: dict[str, Any]) -> bytes:
    for name, array in arrays.items():
        getattr(dct, name)[...] = array
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as handle:
        path = Path(handle.name)
    try:
        dct.write_dct(str(path))
        return path.read_bytes()
    finally:
        with suppress(OSError):
            path.unlink(missing_ok=True)


def _coefficient_sha256(array: Any) -> str:
    return hashlib.sha256(array.tobytes()).hexdigest()


def reconstruct_jpeg_dct(
    *,
    jpeg_bytes: bytes,
    tile_draws: list[dict[str, Any]],
    canvas_size: tuple[int, int],
    output_path: Path,
    png_path: Path,
) -> dict[str, Any]:
    """Reorder quantized DCT blocks without JPEG decode/re-encode."""

    source_rectangles = [
        tuple(int(draw["sourceRect"][key]) for key in ("sx", "sy", "sw", "sh"))
        for draw in tile_draws
    ]
    destination_rectangles = [
        tuple(int(draw["destinationRect"][key]) for key in ("dx", "dy", "dw", "dh"))
        for draw in tile_draws
    ]
    feasibility = dct_lossless_feasibility(
        jpeg_bytes=jpeg_bytes,
        source_rectangles=source_rectangles,
        destination_rectangles=destination_rectangles,
        canvas_size=canvas_size,
    )
    result: dict[str, Any] = {
        "feasibility": feasibility,
        "jpeg_dct_reconstruction": "not_attempted",
        "metadata": {"preserved": None},
    }
    if not feasibility.get("feasible"):
        result["jpeg_dct_reconstruction"] = "not_attempted"
        return result
    try:
        import numpy as np  # type: ignore[import-not-found]
        source_dct, source_temp = _read_dct(jpeg_bytes)
    except (ImportError, OSError, ValueError) as exc:
        result["reason"] = f"dct_dependency_or_read_failure: {type(exc).__name__}: {exc}"
        return result
    output_dct = None
    try:
        dimensions = (int(source_dct.width), int(source_dct.height))
        if dimensions != canvas_size:
            result["reason"] = "dct_dimensions_do_not_match_canvas"
            return result
        factors = [tuple(int(value) for value in row) for row in source_dct.samp_factor.tolist()]
        component_names = [
            name for name in ("Y", "Cb", "Cr") if getattr(source_dct, name, None) is not None
        ]
        if not component_names or len(component_names) != len(factors):
            result["reason"] = "unsupported_jpeg_components"
            return result
        if any(pair != (1, 1) for pair in factors):
            result["reason"] = "subsampled_components_not_supported_by_poc"
            return result
        original = {
            name: np.array(getattr(source_dct, name), dtype=np.int16, copy=True)
            for name in component_names
        }
        if len({array.shape[:2] for array in original.values()}) != 1:
            result["reason"] = "component_block_grids_differ"
            return result
        expected = {name: array.copy() for name, array in original.items()}
        for draw, source_rect, destination_rect in zip(
            tile_draws, source_rectangles, destination_rectangles
        ):
            sx, sy, sw, sh = source_rect
            dx, dy, dw, dh = destination_rect
            if sw != dw or sh != dh:
                result["reason"] = "scaled_draw_observed"
                return result
            source_x, source_y = sx // 8, sy // 8
            destination_x, destination_y = dx // 8, dy // 8
            width, height = sw // 8, sh // 8
            for name in component_names:
                expected[name][
                    destination_y:destination_y + height,
                    destination_x:destination_x + width,
                ] = original[name][source_y:source_y + height, source_x:source_x + width]
        output_bytes = _write_dct(source_dct, expected)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(output_bytes)
        output_dct, output_temp = _read_dct(output_bytes)
        observed = {
            name: np.array(getattr(output_dct, name), dtype=np.int16, copy=True)
            for name in component_names
        }
        coefficients_equal = all(np.array_equal(expected[name], observed[name]) for name in component_names)
        quantization_equal = np.array_equal(source_dct.qt, output_dct.qt) and np.array_equal(
            source_dct.quant_tbl_no, output_dct.quant_tbl_no
        )
        result.update({
            "jpeg_dimensions": list(dimensions),
            "coefficient_sha256_expected": {
                name: _coefficient_sha256(expected[name]) for name in component_names
            },
            "coefficient_sha256_observed": {
                name: _coefficient_sha256(observed[name]) for name in component_names
            },
            "coefficients_equal": coefficients_equal,
            "quantization_tables_equal": quantization_equal,
            "sampling_factors_equal": source_dct.samp_factor.tolist() == output_dct.samp_factor.tolist(),
            "metadata": {
                "preserved": _metadata_preserved(jpeg_bytes, output_bytes),
                "app_markers": len([m for m, _ in _jpeg_marker_payloads(jpeg_bytes) if 0xE0 <= m <= 0xEF]),
                "com_markers": len(_marker_payloads(jpeg_bytes, 0xFE)),
            },
            "output_file": str(output_path),
            "output_dimensions": list(dimensions),
        })
        with Image.open(io.BytesIO(output_bytes)) as lossless_image, Image.open(png_path) as png_image:
            left = lossless_image.convert("RGB")
            right = png_image.convert("RGB")
            if left.size == right.size:
                diff = ImageChops.difference(left, right)
                means = ImageStat.Stat(diff).mean
                result["decoded_pixel_comparison"] = {
                    "exact": left.tobytes() == right.tobytes(),
                    "mean_absolute_difference": sum(means) / 3,
                    "max_channel_difference": max(
                        diff.getchannel(index).getextrema()[1] for index in range(3)
                    ),
                }
            else:
                result["decoded_pixel_comparison"] = {
                    "exact": False,
                    "reason": "output_dimensions_do_not_match_png",
                }
        success = coefficients_equal and quantization_equal and result["sampling_factors_equal"]
        result["jpeg_dct_reconstruction"] = "successful" if success else "failed"
        if not success:
            result["reason"] = "output_dct_does_not_match_expected_coefficients"
        return result
    except Exception as exc:  # noqa: BLE001 - diagnostic path fails closed
        result["jpeg_dct_reconstruction"] = "failed"
        result["reason"] = f"dct_write_or_validation_failure: {type(exc).__name__}: {exc}"
        return result
    finally:
        if output_dct is not None:
            with suppress(Exception):
                output_dct.close()
        with suppress(Exception):
            source_dct.close()
        with suppress(OSError):
            source_temp.unlink(missing_ok=True)
        if "output_temp" in locals() and output_temp is not None:
            with suppress(OSError):
                output_temp.unlink(missing_ok=True)


def reconstruct_canvas(
    *,
    input_dir: Path,
    output_dir: Path,
    state: dict[str, Any],
    pixels: dict[str, Any],
    candidates_by_pixel: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    canvas_id = state.get("canvas_id")
    canvas_id = int(canvas_id) if canvas_id is not None else None
    canvas_artifact = _canvas_artifacts_by_id(pixels).get(canvas_id) if canvas_id is not None else None
    width, height = (state.get("canvas_dimensions") or [None, None])[:2]
    state_name = str(state.get("state"))
    mapping_dir = output_dir / state_name
    mapping_path = mapping_dir / f"canvas_{canvas_id if canvas_id is not None else 'unknown':02}_mapping.json"
    reconstructed_path = mapping_dir / f"canvas_{canvas_id if canvas_id is not None else 'unknown':02}_reconstructed.png"
    difference_path = mapping_dir / f"canvas_{canvas_id if canvas_id is not None else 'unknown':02}_difference.png"
    source_by_id = _source_artifacts_by_id(pixels)
    draws = sorted(state.get("draw_calls", []), key=lambda item: item.get("sequence", 0))
    canvas_mutations = list(state.get("canvas_mutations", []))
    content_mutations = list(state.get("content_mutations", []))
    mapping: dict[str, Any] = {
        "state": state_name,
        "canvas_id": canvas_id,
        "width": width,
        "height": height,
        "draw_count": len(draws),
        "draw_stage": classify_draw_stage(draws),
        "sources": [],
        "draws": [],
        "unsupported": [],
        "unmatched_sources": [],
        "ignored_draws": [],
        "canvas_mutations": canvas_mutations,
        "content_mutations": content_mutations,
        "source_match": "confirmed",
        "mapping_status": "complete",
        "pixel_reconstruction": "inconclusive",
        "jpeg_dct_feasibility": "unknown",
        "jpeg_dct_reconstruction": "not_attempted",
        "visual_reference": "unavailable",
        "candidate_selection_statuses": [],
        "candidate_selections": [],
        "background_mode": "unknown",
    }
    if canvas_id is None or not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        mapping["unsupported"].append("missing_canvas_id_or_dimensions")
        _write_json(mapping_path, mapping)
        mapping["mapping_status"] = "incomplete"
        return {"mapping": mapping, "status": "inconclusive"}
    if not draws:
        mapping["unsupported"].append("no_draw_calls_observed")
        mapping["mapping_status"] = "incomplete"
        mapping["status"] = "inconclusive"
        _write_json(mapping_path, mapping)
        return {"mapping": mapping, "status": mapping["status"]}

    if content_mutations:
        mapping["unsupported"].append("unsupported_canvas_mutation")
        mapping["mapping_status"] = "unsupported"

    output = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    loaded_sources: dict[
        tuple[int, str],
        tuple[Image.Image, dict[str, Any], list[dict[str, Any]], dict[str, Any]],
    ] = {}
    selection_cache: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {}
    for sequence, draw in enumerate(draws):
        source = draw.get("source") or {}
        destination = _rect_values(draw.get("destinationRect"), ("dx", "dy", "dw", "dh"))
        source_url = str(source.get("url") or "")
        if source_url.endswith("/images/spacer.png") and destination:
            dx, dy, dw, dh = destination
            if dx + dw <= 0 or dy + dh <= 0 or dx >= width or dy >= height:
                mapping["ignored_draws"].append({
                    "sequence": draw.get("sequence", sequence),
                    "source_id": source.get("sourceId"),
                    "reason": "out_of_bounds_spacer_noop",
                    "destinationRect": draw.get("destinationRect"),
                })
                mapping["draws"].append({
                    "sequence": draw.get("sequence", sequence),
                    "source_id": source.get("sourceId"),
                    "status": "ignored_non_content_noop",
                    "reason": "out_of_bounds_spacer_noop",
                })
                continue
        source_id = source.get("sourceId")
        source_id = int(source_id) if source_id is not None else None
        source_artifact, source_match = _source_artifact_for_draw(
            source_by_id, source_id, source_url
        )
        if source_match != "confirmed":
            mapping["source_match"] = source_match
        source_pixel_sha = source_artifact.get("pixel_sha256") if source_artifact else None
        candidates = candidates_by_pixel.get(str(source_pixel_sha), []) if source_pixel_sha else []
        if source_match != "confirmed" or source_artifact is None or not candidates:
            if source_match == "confirmed" and not candidates:
                mapping["source_match"] = "unmatched"
            reason = source_match if source_match != "confirmed" else "unmatched_source"
            if reason == "unmatched" and source_url.startswith("blob:"):
                reason = "draw_source_snapshot_unavailable"
            mapping["unmatched_sources"].append({
                "sequence": draw.get("sequence", sequence),
                "source_id": source_id,
                "source_url": source.get("url"),
                "reason": reason,
                "source_pixel_sha256": source_pixel_sha,
            })
            mapping["draws"].append({
                "sequence": draw.get("sequence", sequence),
                "source_id": source_id,
                "source_url": source_url,
                "sourceRect": draw.get("sourceRect"),
                "destinationRect": draw.get("destinationRect"),
                "status": reason,
            })
            continue
        selection_key = (
            str(source_pixel_sha),
            tuple(str(item.get("file") or "") for item in candidates),
        )
        selection = selection_cache.get(selection_key)
        if selection is None:
            selection = select_transport_candidate(
                source_pixel_sha,
                candidates,
                load_bytes=lambda item: (input_dir / str(item["file"])).read_bytes(),
                analyze_candidate=_analyze_jpeg_candidate,
            )
            selection_cache[selection_key] = selection
        selection_status = str(selection.get("selection_status") or "unmatched")
        if selection_status not in mapping["candidate_selection_statuses"]:
            mapping["candidate_selection_statuses"].append(selection_status)
        selection_record = {
            key: value for key, value in selection.items()
            if key not in {"selected_candidate", "pixel_fallback_candidate"}
        }
        selection_record["source_id"] = source_id
        selection_record["source_url"] = source_url
        selection_record["candidate_files"] = [item.get("file") for item in candidates]
        if selection_record not in mapping["candidate_selections"]:
            mapping["candidate_selections"].append(selection_record)
        candidate = selection.get("selected_candidate") or selection.get("pixel_fallback_candidate")
        if candidate is None:
            mapping["source_match"] = "unmatched"
            mapping["unmatched_sources"].append({
                "sequence": draw.get("sequence", sequence),
                "source_id": source_id,
                "source_url": source_url,
                "reason": "unmatched_source",
                "selection_status": selection_status,
            })
            continue
        loaded_key = (source_id, source_url)
        if loaded_key not in loaded_sources:
            source_path = input_dir / str(candidate["file"])
            try:
                loaded_sources[loaded_key] = (
                    Image.open(source_path).convert("RGBA"),
                    source_artifact,
                    candidates,
                    selection,
                )
            except (OSError, ValueError) as exc:
                mapping["unmatched_sources"].append({
                    "sequence": draw.get("sequence", sequence),
                    "source_id": source_id,
                    "reason": "network_image_unreadable",
                    "error": f"{type(exc).__name__}: {exc}",
                })
                mapping["draws"].append({
                    "sequence": draw.get("sequence", sequence),
                    "source_id": source_id,
                    "status": "unmatched_source",
                })
                continue
            mapping["sources"].append({
                "source_id": source_id,
                "source_url": source.get("url"),
                "artifact_url": source_artifact.get("url"),
                "network_file": candidate["file"],
                "network_candidates": [item["file"] for item in candidates],
                "pixel_sha256": source_pixel_sha,
                "matched_by": "decoded_pixel_sha256",
                "selection_status": selection_status,
                "selection_reason": selection.get("selection_reason"),
                "candidate_count": selection.get("candidate_count", len(candidates)),
                "equivalent_candidate_count": selection.get("equivalent_candidate_count", 0),
                "metadata_equivalent": selection.get("metadata_equivalent"),
            })
        source_image, source_artifact, candidates, selection = loaded_sources[loaded_key]
        source_rect = _rect_values(draw.get("sourceRect"), ("sx", "sy", "sw", "sh"))
        issues: list[str] = []
        if source.get("type") != "HTMLImageElement":
            issues.append("unsupported_source_type")
        if draw.get("argumentForm") != "9-argument" or source_rect is None or destination is None:
            issues.append("unsupported_draw_argument_form")
        if not _is_identity_transform(draw.get("transform")):
            issues.append("unsupported_transform")
        if draw.get("globalCompositeOperation") != "source-over":
            issues.append("unsupported_composite")
        if draw.get("filter") not in (None, "none"):
            issues.append("unsupported_filter")
        if draw.get("globalAlpha") != 1:
            issues.append("unsupported_alpha")
        if source_rect and destination:
            sx, sy, sw, sh = source_rect
            dx, dy, dw, dh = destination
            if sw != dw or sh != dh:
                issues.append("scaled_draw_observed")
            if sx < 0 or sy < 0 or sw <= 0 or sh <= 0 or sx + sw > source_image.width or sy + sh > source_image.height:
                issues.append("source_rect_out_of_bounds")
            if dx < 0 or dy < 0 or dw <= 0 or dh <= 0 or dx + dw > width or dy + dh > height:
                issues.append("destination_rect_out_of_bounds")
        draw_record = {
            "sequence": draw.get("sequence", sequence),
            "source_id": source_id,
            "source_url": source_url,
            "network_file": candidate["file"],
            "pixel_sha256": source_pixel_sha,
            "matched_by": "decoded_pixel_sha256",
            "selection_status": selection.get("selection_status"),
            "selection_reason": selection.get("selection_reason"),
            "sourceRect": draw.get("sourceRect"),
            "destinationRect": draw.get("destinationRect"),
            "status": "unsupported" if issues else "applied",
        }
        if issues:
            draw_record["issues"] = issues
            mapping["unsupported"].extend({"sequence": draw_record["sequence"], "reason": issue} for issue in issues)
        else:
            sx, sy, sw, sh = source_rect
            dx, dy, dw, dh = destination
            tile = source_image.crop((sx, sy, sx + sw, sy + sh))
            output.alpha_composite(tile, (dx, dy))
        mapping["draws"].append(draw_record)

    alpha_min, alpha_max = output.getchannel("A").getextrema()
    mapping["background_mode"] = "fully_opaque" if alpha_min == 255 and alpha_max == 255 else "rgba_transparent_uncovered"
    reconstructed_path.parent.mkdir(parents=True, exist_ok=True)
    if alpha_min == 255:
        output.convert("RGB").save(reconstructed_path)
    else:
        output.save(reconstructed_path)
    mapping["reconstructed_file"] = _relative_path(reconstructed_path, output_dir.parent)
    mapping["reconstructed_dimensions"] = [output.width, output.height]
    mapping["reconstructed_pixel_sha256"] = decoded_pixel_sha256(output)
    mapping["draw_count_applied"] = sum(item.get("status") == "applied" for item in mapping["draws"])
    mapping["draw_count_ignored"] = sum(
        item.get("status") == "ignored_non_content_noop" for item in mapping["draws"]
    )
    mapping["draw_count_unsupported"] = sum(item.get("status") == "unsupported" for item in mapping["draws"])
    if canvas_artifact and canvas_artifact.get("file"):
        reference_path = input_dir / str(canvas_artifact["file"])
        if reference_path.exists():
            mapping["visual_comparison"] = _visual_comparison(output, reference_path, difference_path)
            mapping["visual_reference"] = mapping["visual_comparison"].get("assessment", "unavailable")
    all_supported = not mapping["unsupported"] and not mapping["unmatched_sources"]
    mapping["mapping_status"] = "complete" if all_supported else (
        "unsupported" if mapping["unsupported"] else "incomplete"
    )
    mapping["pixel_reconstruction"] = "successful" if all_supported and mapping["background_mode"] == "fully_opaque" else (
        "failed" if mapping["unsupported"] else "inconclusive"
    )

    applied_draws = [item for item in mapping["draws"] if item.get("status") == "applied"]
    tile_draws = []
    for item in applied_draws:
        source_rect = item.get("sourceRect") or {}
        destination_rect = item.get("destinationRect") or {}
        is_full_frame = (
            source_rect.get("sx") == 0
            and source_rect.get("sy") == 0
            and destination_rect.get("dx") == 0
            and destination_rect.get("dy") == 0
            and source_rect.get("sw") == width
            and source_rect.get("sh") == height
            and destination_rect.get("dw") == width
            and destination_rect.get("dh") == height
        )
        if not is_full_frame:
            tile_draws.append(item)
    source_files = {str(item.get("network_file")) for item in mapping["sources"] if item.get("network_file")}
    dct_selection_allowed = bool(mapping["candidate_selection_statuses"]) and all(
        status in {"unique", "equivalent_multiple"}
        for status in mapping["candidate_selection_statuses"]
    )
    if all_supported and dct_selection_allowed and len(source_files) == 1 and tile_draws:
        source_file = input_dir / next(iter(source_files))
        if source_file.exists():
            try:
                dct_path = mapping_dir / f"canvas_{canvas_id:02}_reconstructed_lossless.jpg"
                dct_result = reconstruct_jpeg_dct(
                    jpeg_bytes=source_file.read_bytes(),
                    tile_draws=tile_draws,
                    canvas_size=(width, height),
                    output_path=dct_path,
                    png_path=reconstructed_path,
                )
                mapping["jpeg_dct_feasibility"] = dct_result["feasibility"].get("status", "unknown")
                mapping["jpeg_dct_reconstruction"] = dct_result.get(
                    "jpeg_dct_reconstruction", "not_attempted"
                )
                mapping["jpeg_dct"] = dct_result
            except (OSError, UnidentifiedImageError, ValueError) as exc:
                mapping["jpeg_dct_reconstruction"] = "failed"
                mapping["jpeg_dct_error"] = f"{type(exc).__name__}: {exc}"
        else:
            mapping["jpeg_dct_reconstruction"] = "not_attempted"
            mapping["jpeg_dct_error"] = "network_file_unavailable"
    elif all_supported and not dct_selection_allowed:
        mapping["jpeg_dct_reconstruction"] = "not_attempted"
        mapping["jpeg_dct_error"] = "ambiguous_transport_candidate"
    elif all_supported:
        mapping["jpeg_dct_reconstruction"] = "not_attempted"
        mapping["jpeg_dct_error"] = "no_single_source_tile_mapping"

    if mapping["jpeg_dct_reconstruction"] == "successful":
        mapping["status"] = "lossless_mapping_complete"
    elif all_supported:
        mapping["status"] = "likely"
    else:
        mapping["status"] = "inconclusive"
    _write_json(mapping_path, mapping)
    return {"mapping": mapping, "status": mapping["status"]}


def _mapping_pattern(report: dict[str, Any]) -> tuple[Any, ...]:
    pattern = []
    for draw in report.get("draws", []):
        pattern.append((
            draw.get("sourceRect", {}).get("sx"),
            draw.get("sourceRect", {}).get("sy"),
            draw.get("sourceRect", {}).get("sw"),
            draw.get("sourceRect", {}).get("sh"),
            draw.get("destinationRect", {}).get("dx"),
            draw.get("destinationRect", {}).get("dy"),
            draw.get("destinationRect", {}).get("dw"),
            draw.get("destinationRect", {}).get("dh"),
        ))
    return tuple(pattern)


def make_summary(report: dict[str, Any]) -> str:
    states = report.get("states", [])
    status_counts = Counter(state.get("status") for state in states)
    active_states = [
        state for state in states if state.get("mapping", {}).get("draw_count", 0) > 0
    ]
    patterns = {_mapping_pattern(state.get("mapping", {})) for state in active_states}
    tile_sizes = Counter(
        (draw.get("sourceRect", {}).get("sw"), draw.get("sourceRect", {}).get("sh"))
        for state in active_states
        for draw in state.get("mapping", {}).get("draws", [])
        if draw.get("sourceRect") and draw.get("status") == "applied"
    )
    dct_feasibility = Counter(
        state.get("mapping", {}).get("jpeg_dct_feasibility", "unknown")
        for state in active_states
    )
    dct_results = Counter(
        state.get("mapping", {}).get("jpeg_dct_reconstruction", "not_attempted")
        for state in active_states
    )
    mutation_counts = Counter(
        item.get("operation")
        for state in active_states
        for item in state.get("mapping", {}).get("canvas_mutations", [])
    )
    candidate_selection_counts = Counter(
        status
        for state in active_states
        for status in state.get("mapping", {}).get("candidate_selection_statuses", [])
    )
    lossless_count = sum(
        state.get("mapping", {}).get("status") == "lossless_mapping_complete"
        for state in active_states
    )
    lines = [
        "# Jump+ J2 lossless reconstruction PoC summary",
        "",
        f"- input: `{report.get('input_dir')}`",
        f"- target episode ID: `{report.get('target_episode_id')}`",
        f"- states/canvas reconstructions: `{len(states)}`",
        f"- status counts: `{json.dumps(dict(status_counts), ensure_ascii=False, sort_keys=True)}`",
        "",
        "## Reconstruction method",
        "",
        "- Candidate transport images were selected by decoded RGB pixel SHA-256 equality between J1 blob source and network JPEG.",
        "- Draw calls were filtered by `canvas.id == captured canvasId` and replayed in recorded `sequence` order.",
        "- Supported path was restricted to HTMLImageElement, 9-argument drawImage, identity transform, source-over, filter none, alpha 1, and integer crop/paste with no scaling.",
        "- Stable source artifacts were accepted only when `sourceId` and draw-time source URL both matched; a URL change is recorded as `source_changed_after_draw`.",
        f"- Canvas mutation operations observed on active canvases: `{json.dumps(dict(mutation_counts), ensure_ascii=False, sort_keys=True)}`; content-affecting operations are unsupported for lossless claims.",
        "- locator screenshots were used only as visual references; they were not treated as raw canvas pixel ground truth.",
        "",
        "## Mapping observations",
        "",
        f"- applied tile source-rect sizes: `{json.dumps(tile_sizes.most_common(), ensure_ascii=False)}`",
        f"- mapping geometry pattern: `{'fixed across observed canvases' if len(patterns) == 1 else 'variable / page-dependent'}`",
        f"- draw stage classifications: `{json.dumps(dict(Counter(state.get('mapping', {}).get('draw_stage') for state in active_states)), ensure_ascii=False, sort_keys=True)}`",
        f"- JPEG MCU/DCT feasibility: `{json.dumps(dict(dct_feasibility), ensure_ascii=False, sort_keys=True)}`",
        f"- JPEG DCT reconstruction results: `{json.dumps(dict(dct_results), ensure_ascii=False, sort_keys=True)}`",
        f"- transport candidate selection statuses: `{json.dumps(dict(candidate_selection_counts), ensure_ascii=False, sort_keys=True)}`",
        "- Full-frame and partial tile calls were retained and replayed in sequence; no call was discarded solely because it was a staging-looking full-frame draw.",
        "",
        "## Per-canvas results",
        "",
    ]
    for state in states:
        mapping = state.get("mapping", {})
        visual = mapping.get("visual_comparison", {})
        lines.append(
            f"- `{state.get('state')}` canvas `{state.get('canvas_id')}`: `{state.get('status')}`, source `{mapping.get('source_match')}`, mapping `{mapping.get('mapping_status')}`, pixel `{mapping.get('pixel_reconstruction')}`, DCT `{mapping.get('jpeg_dct_feasibility')}/{mapping.get('jpeg_dct_reconstruction')}`, draws `{mapping.get('draw_count_applied', 0)}/{mapping.get('draw_count', 0)}` applied, unmatched `{len(mapping.get('unmatched_sources', []))}`, unsupported `{len(mapping.get('unsupported', []))}`, visual `{visual.get('assessment', 'not_observed')}`"
        )
    lines.extend([
        "",
        "## Capture recommendation",
        "",
        f"- J2 reconstruction: `{'jpeg_lossless_confirmed' if active_states and lossless_count == len(active_states) else ('png_reconstruction_confirmed' if active_states and all(state.get('mapping', {}).get('pixel_reconstruction') == 'successful' for state in active_states) else 'inconclusive')}`.",
        f"- Lossless mapping-complete canvases: `{lossless_count}/{len(active_states)}`. This is a PoC reconstruction result, not raw canvas pixel ground truth.",
        "- Option A (runtime draw mapping reuse) remains the preferred candidate because mappings are taken from the actual page draw sequence.",
        "- Option B (static permutation) is not adopted; it is only safe if the observed geometry is proven fixed across more pages.",
        "- Production Site Adapter implementation is not included in this PoC.",
        "",
        "## Unknowns",
        "",
        "- Locator screenshot comparison is visual evidence only because raw canvas export is tainted.",
        "- Any unmatched source, source URL change after draw, scaled draw, unsupported operation, or missing stage prevents a lossless claim for that canvas.",
    ])
    return "\n".join(lines) + "\n"


def run_reconstruction(input_dir: Path, output_dir: Path, max_states: int | None = None) -> dict[str, Any]:
    report_path = input_dir / "j1" / "comparison_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    candidate_images = report.get("candidate_images", [])
    candidates_by_pixel = _candidate_index(candidate_images)
    pixels_by_state = _state_paths(input_dir, report)
    states: list[dict[str, Any]] = []
    for state in report.get("states", [])[:max_states]:
        state_name = str(state.get("state"))
        pixels = pixels_by_state.get(state_name, {})
        for canvas in state.get("canvas_comparisons", []):
            result = reconstruct_canvas(
                input_dir=input_dir,
                output_dir=output_dir,
                state=canvas,
                pixels=pixels,
                candidates_by_pixel=candidates_by_pixel,
            )
            states.append({
                "state": state_name,
                "canvas_id": canvas.get("canvas_id"),
                "status": result["status"],
                "mapping": result["mapping"],
            })
    output = {
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "target_episode_id": report.get("target_episode_id"),
        "states": states,
    }
    _write_json(output_dir / "reconstruction_report.json", output)
    _write_text(output_dir / "summary.md", make_summary(output))
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reconstruct Jump+ pages from J1 drawImage mappings")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-states", type=int, default=None)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = run_reconstruction(args.input_dir, args.output_dir, args.max_states)
    print(json.dumps({"states": len(result["states"]), "output_dir": str(args.output_dir)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
