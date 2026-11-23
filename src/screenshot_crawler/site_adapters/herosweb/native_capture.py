"""Bounded native-canvas capture for the observed HERO'S WEB viewer profile."""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import math
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError, features

from screenshot_crawler.core.capture import CaptureResult
from screenshot_crawler.core.errors import UnknownPageStateError

MAX_NATIVE_PIXELS = 3_000_000
MAX_NATIVE_SPREAD_PIXELS = 6_000_000
MAX_CAPTURE_BYTES = 24 * 1024 * 1024
_PNG_PREFIX = "data:image/png;base64,"


@dataclass(frozen=True, slots=True)
class NativeCandidate:
    """A copied source-canvas PNG plus its point-in-time proof."""

    slot: int
    width: int
    height: int
    png: bytes
    proof: dict[str, object]


@dataclass(frozen=True, slots=True)
class NativeOutput:
    capture: CaptureResult
    mode: str
    proof: dict[str, object]


def _decode_data_url(value: object) -> bytes | None:
    if not isinstance(value, str) or not value.startswith(_PNG_PREFIX):
        return None
    if len(value) > len(_PNG_PREFIX) + 4 * ((MAX_CAPTURE_BYTES + 2) // 3):
        return None
    try:
        data = base64.b64decode(value[len(_PNG_PREFIX) :], validate=True)
    except (binascii.Error, ValueError):
        return None
    return data if len(data) <= MAX_CAPTURE_BYTES else None


def _decode_png(data: bytes, *, width: int, height: int) -> bytes | None:
    if len(data) > MAX_CAPTURE_BYTES or width <= 0 or height <= 0:
        return None
    if width * height > MAX_NATIVE_PIXELS or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "PNG" or image.size != (width, height):
                return None
            if getattr(image, "n_frames", 1) != 1:
                return None
            image.load()
            return image.convert("RGBA").tobytes()
    except (UnidentifiedImageError, OSError, ValueError):
        return None


def _expected_target_map(expected_targets: object) -> dict[int, dict[str, object]]:
    if not isinstance(expected_targets, list) or not expected_targets or len(expected_targets) > 2:
        raise UnknownPageStateError("HERO'S WEB native target group is malformed")
    result: dict[int, dict[str, object]] = {}
    for item in expected_targets:
        if not isinstance(item, dict):
            raise UnknownPageStateError("HERO'S WEB native target proof is malformed")
        slot = item.get("slot")
        if type(slot) is not int or slot in result:
            raise UnknownPageStateError("HERO'S WEB native target slots are duplicated")
        for field in ("nodeId", "width", "height", "drawEpoch"):
            if type(item.get(field)) is not int or item[field] <= 0:
                raise UnknownPageStateError("HERO'S WEB native target identity is incomplete")
        if type(item.get("generation")) is not int or item["generation"] < 0:
            raise UnknownPageStateError("HERO'S WEB native target generation is malformed")
        for field in (
            "wrapperNodeId",
            "rootNodeId",
            "pagesWrapNodeId",
            "pagesRootNodeId",
            "seekNodeId",
            "seekValue",
            "seekMax",
        ):
            if type(item.get(field)) is not int or item[field] <= 0:
                raise UnknownPageStateError("HERO'S WEB native layout binding is incomplete")
        if type(item.get("pairStart")) is not int or item["pairStart"] < 0:
            raise UnknownPageStateError("HERO'S WEB native logical spread is malformed")
        pair_slots = item.get("pairSlots")
        root_modes = item.get("rootStructuralModes")
        if (
            not isinstance(pair_slots, list)
            or not 1 <= len(pair_slots) <= 2
            or any(type(value) is not int for value in pair_slots)
            or slot not in pair_slots
            or not isinstance(root_modes, list)
            or any(not isinstance(value, str) for value in root_modes)
        ):
            raise UnknownPageStateError("HERO'S WEB native logical spread binding is incomplete")
        result[slot] = item
    return result


def _positive_rect(value: object) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    result: dict[str, float] = {}
    for key in ("x", "y", "width", "height"):
        number = value.get(key)
        if (
            isinstance(number, bool)
            or not isinstance(number, (int, float))
            or not math.isfinite(float(number))
        ):
            return None
        result[key] = float(number)
    return result if result["width"] > 0 and result["height"] > 0 else None


def _same_translation(
    target_before: object,
    target_after: object,
    wrapper_before: object,
    wrapper_after: object,
) -> bool:
    target_start, target_end = _positive_rect(target_before), _positive_rect(target_after)
    wrapper_start, wrapper_end = _positive_rect(wrapper_before), _positive_rect(wrapper_after)
    if None in (target_start, target_end, wrapper_start, wrapper_end):
        return False
    assert target_start is not None and target_end is not None
    assert wrapper_start is not None and wrapper_end is not None
    for start, end in ((target_start, target_end), (wrapper_start, wrapper_end)):
        if abs(start["width"] - end["width"]) > 0.001 or abs(start["height"] - end["height"]) > 0.001:
            return False
    target_delta = (target_end["x"] - target_start["x"], target_end["y"] - target_start["y"])
    wrapper_delta = (wrapper_end["x"] - wrapper_start["x"], wrapper_end["y"] - wrapper_start["y"])
    return all(abs(left - right) <= 0.001 for left, right in zip(target_delta, wrapper_delta, strict=True))


def _source_grid_profile(width: int, height: int) -> tuple[int, int, str, str] | None:
    if (width, height) == (1440, 2048):
        return (
            360,
            512,
            "HTMLImageElement",
            "complete_4x4_360x512_8px_aligned",
        )
    if (width, height) == (844, 1200):
        return (
            211,
            300,
            "HTMLImageElement",
            "complete_4x4_211x300_1to1_rgba_verified",
        )
    return None


def _validated_source_tile_history(
    value: object, *, width: int, height: int
) -> str | None:
    if not isinstance(value, list) or len(value) != 16:
        return None
    profile = _source_grid_profile(width, height)
    if profile is None:
        return None
    tile_width, tile_height, tile_source_type, profile_name = profile
    source_cells: set[tuple[int, int]] = set()
    target_cells: set[tuple[int, int]] = set()
    for ordinal, item in enumerate(value):
        if (
            not isinstance(item, dict)
            or type(item.get("ordinal")) is not int
            or item["ordinal"] != ordinal
            or type(item.get("clipCountBefore")) is not int
        ):
            return None
        args = item.get("args")
        context = item.get("context")
        if (
            item.get("kind") != "drawImage"
            or item.get("clipCountBefore") != 0
            or item.get("sourceType") != tile_source_type
            or item.get("sourceDimensions") != [width, height]
            or item.get("targetDimensions") != [width, height]
            or not isinstance(args, list)
            or len(args) != 8
            or not isinstance(context, dict)
            or context.get("transform") != [1, 0, 0, 1, 0, 0]
            or context.get("globalAlpha") != 1
            or context.get("globalCompositeOperation") != "source-over"
            or context.get("filter") != "none"
            or context.get("shadowBlur") != 0
            or context.get("shadowOffsetX") != 0
            or context.get("shadowOffsetY") != 0
        ):
            return None
        attributes = context.get("attributes")
        if (
            not isinstance(attributes, dict)
            or attributes.get("colorSpace") != "srgb"
            or attributes.get("colorType") != "unorm8"
        ):
            return None
        if any(
            isinstance(number, bool)
            or not isinstance(number, (int, float))
            or not math.isfinite(float(number))
            or int(number) != number
            for number in args
        ):
            return None
        sx, sy, sw, sh, dx, dy, dw, dh = (int(number) for number in args)
        if (sw, sh, dw, dh) != (tile_width, tile_height, tile_width, tile_height):
            return None
        if (sx % tile_width or dx % tile_width or sy % tile_height or dy % tile_height):
            return None
        if min(sx, sy, dx, dy) < 0 or sx + sw > width or sy + sh > height:
            return None
        if dx + dw > width or dy + dh > height:
            return None
        if width == 1440 and any(
            number % 8 for number in (sx, sy, sw, sh, dx, dy, dw, dh)
        ):
            return None
        for row in range(sy // tile_height, (sy + sh) // tile_height):
            for column in range(sx // tile_width, (sx + sw) // tile_width):
                cell = (column, row)
                if cell in source_cells:
                    return None
                source_cells.add(cell)
        for row in range(dy // tile_height, (dy + dh) // tile_height):
            for column in range(dx // tile_width, (dx + dw) // tile_width):
                cell = (column, row)
                if cell in target_cells:
                    return None
                target_cells.add(cell)
    complete = {(column, row) for row in range(4) for column in range(4)}
    return profile_name if source_cells == complete and target_cells == complete else None


def decode_native_candidates(
    raw: object,
    *,
    expected_targets: object,
) -> tuple[NativeCandidate | None, ...]:
    """Validate materialized source PNGs and their frozen target proof fields."""

    targets = _expected_target_map(expected_targets)
    if not isinstance(raw, dict):
        return tuple(None for _ in targets)
    status = raw.get("status")
    if status in {"identity_drift", "target_drift", "observer_drift"}:
        raise UnknownPageStateError("HERO'S WEB Viewer changed during native pixel materialization")
    if status != "ok":
        return tuple(None for _ in targets)
    if raw.get("observerStable") is not True:
        return tuple(None for _ in targets)
    before = raw.get("documentBefore")
    after = raw.get("documentAfter")
    if not isinstance(before, dict) or not isinstance(after, dict) or before != after:
        raise UnknownPageStateError("HERO'S WEB document identity changed during native materialization")
    if raw.get("seekBefore") != raw.get("seekAfter"):
        raise UnknownPageStateError("HERO'S WEB seek changed during native materialization")
    records = raw.get("records")
    if not isinstance(records, list) or len(records) != len(targets):
        return tuple(None for _ in targets)
    by_slot = {record.get("slot"): record for record in records if isinstance(record, dict)}
    if set(by_slot) != set(targets):
        return tuple(None for _ in targets)

    total_pixels = 0
    candidates: list[NativeCandidate | None] = []
    for slot, expected in targets.items():
        record = by_slot[slot]
        if record.get("supported") is not True:
            candidates.append(None)
            continue
        proof = record.get("proof")
        if not isinstance(proof, dict):
            candidates.append(None)
            continue
        required_equalities = (
            (proof.get("targetNodeId"), expected["nodeId"]),
            (proof.get("targetSlotBefore"), slot),
            (proof.get("targetSlotAfter"), slot),
            (proof.get("targetEpochBefore"), expected["drawEpoch"]),
            (proof.get("targetEpochAfter"), expected["drawEpoch"]),
            (proof.get("targetGenerationBefore"), expected["generation"]),
            (proof.get("targetGenerationAfter"), expected["generation"]),
            (proof.get("candidateTargetEpochAfterDraw"), expected["drawEpoch"]),
            (proof.get("candidateTargetGenerationAfterDraw"), expected["generation"]),
            (proof.get("drawRootNodeId"), expected["rootNodeId"]),
            (proof.get("drawPagesWrapNodeId"), expected["pagesWrapNodeId"]),
            (proof.get("drawPagesRootNodeId"), expected["pagesRootNodeId"]),
            (proof.get("drawWrapperNodeId"), expected["wrapperNodeId"]),
            (proof.get("drawSeekNodeId"), expected["seekNodeId"]),
            (proof.get("drawSeekValue"), expected["seekValue"]),
            (proof.get("drawSeekMax"), expected["seekMax"]),
            (proof.get("drawPairStart"), expected["pairStart"]),
        )
        if any(actual != wanted for actual, wanted in required_equalities):
            raise UnknownPageStateError(
                "HERO'S WEB body target identity changed during native materialization"
            )
        if proof.get("targetPixelsStable") is not True:
            raise UnknownPageStateError(
                "HERO'S WEB body pixels changed during native materialization"
            )
        if (
            proof.get("drawPairSlots") != expected.get("pairSlots")
            or proof.get("drawToCaptureCommonTranslation") is not True
        ):
            candidates.append(None)
            continue
        draw_modes = proof.get("drawRootStructuralModes")
        expected_modes = expected.get("rootStructuralModes")
        if not isinstance(draw_modes, list) or not isinstance(expected_modes, list):
            candidates.append(None)
            continue
        if draw_modes != expected_modes:
            early_pr_shell = (
                "mode-has-pr" in expected_modes
                and expected.get("seekValue") == expected.get("seekMax")
                and expected.get("pairStart") == 0
                and "mode-has-pr" not in draw_modes
                and len(draw_modes) + 1 == len(expected_modes)
                and all(mode in expected_modes for mode in draw_modes)
            )
            if not early_pr_shell:
                candidates.append(None)
                continue
        draw_target_before = proof.get("drawTargetRectBefore")
        draw_target_after = proof.get("drawTargetRectAfter")
        draw_wrapper_before = proof.get("drawWrapperRectBefore")
        draw_wrapper_after = proof.get("drawWrapperRectAfter")
        materialized_target = proof.get("materializedTargetRect")
        materialized_wrapper = proof.get("materializedWrapperRect")
        if (
            not _same_translation(
                draw_target_before,
                draw_target_after,
                draw_wrapper_before,
                draw_wrapper_after,
            )
            or not _same_translation(
                draw_target_after,
                materialized_target,
                draw_wrapper_after,
                materialized_wrapper,
            )
        ):
            candidates.append(None)
            continue
        source_tile_geometry = _validated_source_tile_history(
            proof.get("sourceTileHistory"), width=record.get("width"), height=record.get("height")
        )
        if (
            proof.get("sourceReplayMatchesTarget") is not True
            or proof.get("sourceHistoryComplete") is not True
            or source_tile_geometry is None
            or proof.get("observerDrawsBefore") != proof.get("observerDrawsAfter")
        ):
            candidates.append(None)
            continue
        width, height = record.get("width"), record.get("height")
        if type(width) is not int or type(height) is not int or width * height > MAX_NATIVE_PIXELS:
            candidates.append(None)
            continue
        encoded = _decode_data_url(record.get("sourcePng"))
        rgba = _decode_png(encoded, width=width, height=height) if encoded is not None else None
        if encoded is None or rgba is None:
            candidates.append(None)
            continue
        source_node_id = proof.get("sourceCanvasNodeId")
        source_generation = proof.get("sourceGenerationAtDraw")
        source_epoch = proof.get("sourceEpochAtDraw")
        if (
            type(source_node_id) is not int
            or source_node_id <= 0
            or type(source_generation) is not int
            or source_generation <= 0
            or type(source_epoch) is not int
            or source_epoch <= 0
            or proof.get("sourceType") != "HTMLCanvasElement"
            or proof.get("sourceDimensions") != [width, height]
            or proof.get("sourceDimensions") != [width, height]
            or proof.get("sourceColorSpace") != "srgb"
            or proof.get("sourceColorType") != "unorm8"
            or proof.get("targetColorSpace") != "srgb"
            or proof.get("targetColorType") != "unorm8"
            or proof.get("drawArguments")
            != [0, 0, width, height, 0, 0, 934.5, 1329]
        ):
            candidates.append(None)
            continue
        context = proof.get("context")
        if (
            not isinstance(context, dict)
            or context.get("transform") != [1, 0, 0, 1, 0, 0]
            or context.get("globalAlpha") != 1
            or context.get("globalCompositeOperation") != "source-over"
            or context.get("filter") != "none"
            or context.get("shadowBlur") != 0
            or context.get("shadowOffsetX") != 0
            or context.get("shadowOffsetY") != 0
            or not isinstance(context.get("attributes"), dict)
            or context["attributes"].get("colorSpace") != "srgb"
            or context["attributes"].get("colorType") != "unorm8"
            or proof.get("clipCountBefore") != 0
        ):
            candidates.append(None)
            continue
        total_pixels += width * height
        if total_pixels > MAX_NATIVE_SPREAD_PIXELS:
            return tuple(None for _ in targets)
        safe_proof = {
            "slot": slot,
            "sourceCanvasNodeId": source_node_id,
            "sourceGenerationAtDraw": source_generation,
            "sourceEpochAtDraw": source_epoch,
            "sourceDimensions": [width, height],
            "sourceColorSpace": proof.get("sourceColorSpace"),
            "sourceColorType": proof.get("sourceColorType"),
            "targetCanvasNodeId": proof.get("targetNodeId"),
            "targetDimensions": [expected["width"], expected["height"]],
            "targetColorSpace": proof.get("targetColorSpace"),
            "targetColorType": proof.get("targetColorType"),
            "targetEpoch": expected["drawEpoch"],
            "targetGeneration": expected["generation"],
            "drawRootNodeId": expected["rootNodeId"],
            "drawPagesWrapNodeId": expected["pagesWrapNodeId"],
            "drawPagesRootNodeId": expected["pagesRootNodeId"],
            "drawWrapperNodeId": expected["wrapperNodeId"],
            "drawSeekNodeId": expected["seekNodeId"],
            "drawSeekValue": expected["seekValue"],
            "drawSeekMax": expected["seekMax"],
            "drawPairStart": expected["pairStart"],
            "drawPairSlots": list(expected["pairSlots"]),
            "drawRootStructuralModes": list(draw_modes),
            "drawTargetRectBefore": _positive_rect(draw_target_before),
            "drawTargetRectAfter": _positive_rect(draw_target_after),
            "drawWrapperRectBefore": _positive_rect(draw_wrapper_before),
            "drawWrapperRectAfter": _positive_rect(draw_wrapper_after),
            "materializedTargetRect": _positive_rect(materialized_target),
            "materializedWrapperRect": _positive_rect(materialized_wrapper),
            "drawToCaptureCommonTranslation": True,
            "drawArguments": list(proof.get("drawArguments", [])),
            "context": dict(context),
            "sourceTileDrawCount": 16,
            "sourceTileGeometry": source_tile_geometry,
            "sourceHistoryComplete": True,
            "sourceReplayMatchesTarget": True,
            "targetPixelsStableAfterMaterialization": True,
            "source_rgba_sha256": hashlib.sha256(rgba).hexdigest(),
            "source_png_sha256": hashlib.sha256(encoded).hexdigest(),
            "original_bytes": False,
            "native_pixels": True,
        }
        candidates.append(NativeCandidate(slot, width, height, encoded, safe_proof))
    if len(candidates) > 1 and any(candidate is None for candidate in candidates):
        return tuple(None for _ in candidates)
    return tuple(candidates)


def encode_native_candidates(
    candidates: tuple[NativeCandidate | None, ...],
) -> tuple[NativeOutput | None, ...]:
    """Encode exact source snapshots as VP8L; preserve verified native PNG on failure."""

    outputs: list[NativeOutput | None] = []
    webp_available = bool(features.check("webp"))
    for candidate in candidates:
        if candidate is None:
            outputs.append(None)
            continue
        fallback = CaptureResult(
            candidate.png, candidate.width, candidate.height, "image/png", ".png"
        )
        if not webp_available:
            proof = dict(candidate.proof)
            proof["webp_vp8l_rgba_verified"] = False
            proof["capture_strategy"] = "source_canvas_native_png"
            proof["encoder_status"] = "unavailable"
            outputs.append(
                NativeOutput(fallback, "source_canvas_native_png", proof)
            )
            continue
        try:
            with Image.open(io.BytesIO(candidate.png)) as original_png:
                if original_png.format != "PNG" or original_png.size != (
                    candidate.width,
                    candidate.height,
                ):
                    raise ValueError("source PNG changed after validation")
                original_png.load()
                original = original_png.convert("RGBA")
            output = io.BytesIO()
            original.save(output, format="WEBP", lossless=True, method=4)
            encoded = output.getvalue()
            if len(encoded) > MAX_CAPTURE_BYTES or not _single_vp8l(
                encoded, width=candidate.width, height=candidate.height
            ):
                raise ValueError("encoder did not produce one validated VP8L chunk")
            with Image.open(io.BytesIO(encoded)) as decoded:
                if (
                    decoded.format != "WEBP"
                    or decoded.size != (candidate.width, candidate.height)
                    or getattr(decoded, "n_frames", 1) != 1
                ):
                    raise ValueError("encoded WebP dimensions or frame count changed")
                decoded.load()
                if decoded.convert("RGBA").tobytes() != original.tobytes():
                    raise ValueError("lossless WebP RGBA did not match source PNG")
            proof = dict(candidate.proof)
            proof["webp_vp8l_rgba_verified"] = True
            proof["capture_strategy"] = "source_canvas_lossless_vp8l"
            outputs.append(
                NativeOutput(
                    CaptureResult(encoded, candidate.width, candidate.height, "image/webp", ".webp"),
                    "source_canvas_lossless_vp8l",
                    proof,
                )
            )
        except Exception:  # noqa: BLE001 - keep the already verified native PNG
            proof = dict(candidate.proof)
            proof["webp_vp8l_rgba_verified"] = False
            proof["capture_strategy"] = "source_canvas_native_png"
            proof["encoder_status"] = "failed_validation"
            outputs.append(
                NativeOutput(fallback, "source_canvas_native_png", proof)
            )
    return tuple(outputs)


def _single_vp8l(data: bytes, *, width: int, height: int) -> bool:
    if (
        len(data) < 25
        or data[:4] != b"RIFF"
        or int.from_bytes(data[4:8], "little") != len(data) - 8
        or data[8:12] != b"WEBP"
        or data[12:16] != b"VP8L"
    ):
        return False
    chunk_size = int.from_bytes(data[16:20], "little")
    end = 20 + chunk_size
    if chunk_size < 5 or end + (chunk_size & 1) != len(data) or data[20] != 0x2F:
        return False
    encoded_width = 1 + data[21] + ((data[22] & 0x3F) << 8)
    encoded_height = 1 + (data[22] >> 6) + (data[23] << 2) + ((data[24] & 0x0F) << 10)
    version = data[24] >> 5
    return encoded_width == width and encoded_height == height and version == 0


__all__ = [
    "MAX_CAPTURE_BYTES",
    "MAX_NATIVE_PIXELS",
    "MAX_NATIVE_SPREAD_PIXELS",
    "NativeCandidate",
    "NativeOutput",
    "decode_native_candidates",
    "encode_native_candidates",
]
