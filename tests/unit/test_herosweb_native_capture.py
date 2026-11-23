from __future__ import annotations

import base64
import io

import pytest
from PIL import Image, features

from screenshot_crawler.core.errors import UnknownPageStateError
from screenshot_crawler.site_adapters.herosweb import native_capture

WIDTH = 1440
HEIGHT = 2048
B_WIDTH = 844
B_HEIGHT = 1200
TARGET = {
    "slot": 1,
    "nodeId": 23,
    "width": 934,
    "height": 1329,
    "drawEpoch": 9,
    "generation": 0,
    "wrapperNodeId": 4,
    "rootNodeId": 1,
    "pagesWrapNodeId": 2,
    "pagesRootNodeId": 3,
    "seekNodeId": 8,
    "seekValue": 17,
    "seekMax": 17,
    "pairStart": 0,
    "pairSlots": [0, 1],
    "rootStructuralModes": ["mode-h", "mode-has-pr", "mode-pc", "mode-spread"],
}


def _target_for_slot(slot: int, *, seek_max: int = 17) -> dict[str, object]:
    seek_value = seek_max if slot == 1 else seek_max - 2
    pair_start = 0 if slot == 1 else 2
    return {
        **TARGET,
        "slot": slot,
        "nodeId": 22 + slot,
        "wrapperNodeId": 3 + slot,
        "seekValue": seek_value,
        "seekMax": seek_max,
        "pairStart": pair_start,
        "pairSlots": [pair_start, pair_start + 1],
    }


def _png_data_url(*, width: int = WIDTH, height: int = HEIGHT) -> str:
    buffer = io.BytesIO()
    Image.new("RGBA", (width, height), (19, 20, 30, 255)).save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _tile_history(
    *,
    width: int = WIDTH,
    height: int = HEIGHT,
    tile_width: int = 360,
    tile_height: int = 512,
    source_type: str = "HTMLImageElement",
) -> list[dict[str, object]]:
    context = {
        "transform": [1, 0, 0, 1, 0, 0],
        "globalAlpha": 1,
        "globalCompositeOperation": "source-over",
        "filter": "none",
        "shadowBlur": 0,
        "shadowOffsetX": 0,
        "shadowOffsetY": 0,
        "attributes": {"colorSpace": "srgb", "colorType": "unorm8"},
    }
    result = []
    for row in range(4):
        for column in range(4):
            x, y = column * tile_width, row * tile_height
            result.append(
                {
                    "ordinal": len(result),
                    "kind": "drawImage",
                    "sourceType": source_type,
                    "args": [x, y, tile_width, tile_height, x, y, tile_width, tile_height],
                    "sourceDimensions": [width, height],
                    "targetDimensions": [width, height],
                    "context": context,
                    "clipCountBefore": 0,
                }
            )
    return result


def _record(
    *,
    slot: int = 1,
    source_data_url: str | None = None,
    source_profile: str = "a1440",
) -> dict[str, object]:
    if source_profile == "a1440":
        width, height, tile_width, tile_height = WIDTH, HEIGHT, 360, 512
        tile_source_type, seek_max = "HTMLImageElement", 17
    elif source_profile == "b844":
        width, height, tile_width, tile_height = B_WIDTH, B_HEIGHT, 211, 300
        tile_source_type, seek_max = "HTMLImageElement", 45
    else:
        raise ValueError("unknown synthetic HERO'S WEB source profile")
    target = _target_for_slot(slot, seek_max=seek_max)
    draw_x = -2.0 if slot == 1 else -948.0
    capture_x = -2.0 if slot == 1 else 944.0
    proof = {
        "targetNodeId": 23 + slot - 1,
        "targetSlotBefore": slot,
        "targetSlotAfter": slot,
        "targetEpochBefore": 9,
        "targetEpochAfter": 9,
        "targetGenerationBefore": 0,
        "targetGenerationAfter": 0,
        "candidateTargetEpochAfterDraw": 9,
        "candidateTargetGenerationAfterDraw": 0,
        "drawRootNodeId": target["rootNodeId"],
        "drawPagesWrapNodeId": target["pagesWrapNodeId"],
        "drawPagesRootNodeId": target["pagesRootNodeId"],
        "drawWrapperNodeId": target["wrapperNodeId"],
        "drawSeekNodeId": target["seekNodeId"],
        "drawSeekValue": target["seekValue"],
        "drawSeekMax": target["seekMax"],
        "drawPairStart": target["pairStart"],
        "drawPairSlots": target["pairSlots"],
        "drawRootStructuralModes": target["rootStructuralModes"],
        "drawTargetRectBefore": {"x": draw_x, "y": 0, "width": 623, "height": 886},
        "drawTargetRectAfter": {"x": draw_x, "y": 0, "width": 623, "height": 886},
        "drawWrapperRectBefore": {"x": draw_x, "y": 0, "width": 946, "height": 886},
        "drawWrapperRectAfter": {"x": draw_x, "y": 0, "width": 946, "height": 886},
        "materializedTargetRect": {"x": capture_x, "y": 0, "width": 623, "height": 886},
        "materializedWrapperRect": {"x": capture_x, "y": 0, "width": 946, "height": 886},
        "drawToCaptureCommonTranslation": True,
        "targetPixelsStable": True,
        "sourceReplayMatchesTarget": True,
        "sourceHistoryComplete": True,
        "observerDrawsBefore": 150,
        "observerDrawsAfter": 150,
        "sourceCanvasNodeId": 41,
        "sourceGenerationAtDraw": 14,
        "sourceEpochAtDraw": 16,
        "sourceType": "HTMLCanvasElement",
        "sourceDimensions": [width, height],
        "drawArguments": [0, 0, width, height, 0, 0, 934.5, 1329],
        "context": {
            "transform": [1, 0, 0, 1, 0, 0],
            "globalAlpha": 1,
            "globalCompositeOperation": "source-over",
            "filter": "none",
            "shadowBlur": 0,
            "shadowOffsetX": 0,
            "shadowOffsetY": 0,
            "attributes": {"colorSpace": "srgb", "colorType": "unorm8"},
        },
        "sourceColorSpace": "srgb",
        "sourceColorType": "unorm8",
        "targetColorSpace": "srgb",
        "targetColorType": "unorm8",
        "clipCountBefore": 0,
        "sourceTileHistory": _tile_history(
            width=width,
            height=height,
            tile_width=tile_width,
            tile_height=tile_height,
            source_type=tile_source_type,
        ),
    }
    return {
        "slot": slot,
        "supported": True,
        "width": width,
        "height": height,
        "sourcePng": source_data_url or _png_data_url(width=width, height=height),
        "proof": proof,
    }


def _materialization(*records: dict[str, object]) -> dict[str, object]:
    first_proof = records[0].get("proof") if records else None
    seek_value = first_proof.get("drawSeekValue", 17) if isinstance(first_proof, dict) else 17
    return {
        "status": "ok",
        "observerStable": True,
        "documentBefore": {"url": "https://heros-web.com/episodes/0123456789abc"},
        "documentAfter": {"url": "https://heros-web.com/episodes/0123456789abc"},
        "seekBefore": [{"value": str(seek_value)}],
        "seekAfter": [{"value": str(seek_value)}],
        "records": list(records),
    }


@pytest.mark.parametrize(
    ("source_profile", "width", "height", "tile_geometry", "seek_max"),
    [
        (
            "a1440",
            WIDTH,
            HEIGHT,
            "complete_4x4_360x512_8px_aligned",
            17,
        ),
        (
            "b844",
            B_WIDTH,
            B_HEIGHT,
            "complete_4x4_211x300_1to1_rgba_verified",
            45,
        ),
    ],
    ids=("A-1440-profile", "B-844-profile"),
)
def test_herosweb_native_source_emits_lossless_vp8l_or_verified_native_png(
    source_profile: str,
    width: int,
    height: int,
    tile_geometry: str,
    seek_max: int,
) -> None:
    candidate = native_capture.decode_native_candidates(
        _materialization(_record(source_profile=source_profile)),
        expected_targets=[_target_for_slot(1, seek_max=seek_max)],
    )[0]
    assert candidate is not None
    assert candidate.proof["original_bytes"] is False
    assert candidate.proof["native_pixels"] is True
    assert candidate.proof["drawPairStart"] == 0
    assert candidate.proof["drawPairSlots"] == [0, 1]
    assert candidate.proof["drawToCaptureCommonTranslation"] is True

    output = native_capture.encode_native_candidates((candidate,))[0]
    assert output is not None
    assert (output.capture.width, output.capture.height) == (width, height)
    assert candidate.proof["sourceTileGeometry"] == tile_geometry
    if features.check("webp"):
        assert output.mode == "source_canvas_lossless_vp8l"
        assert output.capture.mime_type == "image/webp"
        assert native_capture._single_vp8l(
            output.capture.data, width=width, height=height
        )
        assert output.proof["webp_vp8l_rgba_verified"] is True
    else:
        assert output.mode == "source_canvas_native_png"
        assert output.capture.mime_type == "image/png"
        assert output.capture.data.startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.parametrize(
    ("source_profile", "index", "replacement", "seek_max"),
    [
        ("a1440", 0, [0.5, 0, 360, 512, 0, 0, 360, 512], 17),
        ("a1440", 0, [8, 0, 360, 512, 0, 0, 360, 512], 17),
        ("b844", 0, [0.5, 0, 211, 300, 0, 0, 211, 300], 45),
        ("b844", 0, [211, 0, 211, 300, 0, 0, 211, 300], 45),
    ],
    ids=("A-fractional", "A-off-grid", "B-fractional", "B-off-grid"),
)
def test_herosweb_native_source_rejects_fractional_and_off_grid_tile_maps(
    source_profile: str,
    index: int,
    replacement: list[float],
    seek_max: int,
) -> None:
    record = _record(source_profile=source_profile)
    proof = record["proof"]
    assert isinstance(proof, dict)
    tile_history = proof["sourceTileHistory"]
    assert isinstance(tile_history, list)
    tile_history[index]["args"] = replacement
    decoded = native_capture.decode_native_candidates(
        _materialization(record),
        expected_targets=[_target_for_slot(1, seek_max=seek_max)],
    )
    assert decoded == (None,)


@pytest.mark.parametrize("source_profile", ["a1440", "b844"])
@pytest.mark.parametrize("corruption", ["missing", "duplicate-target"])
def test_herosweb_native_source_rejects_incomplete_or_duplicate_tile_grid(
    source_profile: str,
    corruption: str,
) -> None:
    record = _record(source_profile=source_profile)
    proof = record["proof"]
    assert isinstance(proof, dict)
    tile_history = proof["sourceTileHistory"]
    assert isinstance(tile_history, list)
    if corruption == "missing":
        tile_history.pop()
    else:
        duplicate = dict(tile_history[-1])
        duplicate["ordinal"] = 15
        duplicate["args"] = [*duplicate["args"][:4], 0, 0, *duplicate["args"][6:]]
        tile_history[-1] = duplicate
    seek_max = 17 if source_profile == "a1440" else 45
    assert native_capture.decode_native_candidates(
        _materialization(record),
        expected_targets=[_target_for_slot(1, seek_max=seek_max)],
    ) == (None,)

@pytest.mark.parametrize(
    ("source_profile", "corruption"),
    [("a1440", "B-history"), ("b844", "A-history"), ("b844", "unknown-dimensions")],
)
def test_herosweb_native_source_rejects_unknown_and_cross_profile_geometry(
    source_profile: str,
    corruption: str,
) -> None:
    record = _record(source_profile=source_profile)
    proof = record["proof"]
    assert isinstance(proof, dict)
    if corruption == "B-history":
        proof["sourceTileHistory"] = _tile_history(
            width=B_WIDTH,
            height=B_HEIGHT,
            tile_width=211,
            tile_height=300,
            source_type="HTMLImageElement",
        )
    elif corruption == "A-history":
        proof["sourceTileHistory"] = _tile_history()
    else:
        record["width"] = B_WIDTH + 1
    seek_max = 17 if source_profile == "a1440" else 45
    assert native_capture.decode_native_candidates(
        _materialization(record),
        expected_targets=[_target_for_slot(1, seek_max=seek_max)],
    ) == (None,)


def test_herosweb_native_spread_is_all_or_none() -> None:
    second_target = _target_for_slot(2)
    decoded = native_capture.decode_native_candidates(
        _materialization(_record(), {"slot": 2, "supported": False}),
        expected_targets=[TARGET, second_target],
    )
    assert decoded == (None, None)


def test_herosweb_native_spread_pixel_overflow_uses_rendered_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    second_target = _target_for_slot(2)
    second_record = _record(slot=2)
    second_proof = second_record["proof"]
    assert isinstance(second_proof, dict)
    second_proof["targetNodeId"] = 24
    monkeypatch.setattr(native_capture, "MAX_NATIVE_SPREAD_PIXELS", WIDTH * HEIGHT)
    decoded = native_capture.decode_native_candidates(
        _materialization(_record(), second_record),
        expected_targets=[TARGET, second_target],
    )
    assert decoded == (None, None)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sourceColorSpace", "display-p3"),
        ("targetColorSpace", "display-p3"),
        ("sourceColorType", "float16"),
        ("targetColorType", "float16"),
    ],
    ids=("source-p3", "target-p3", "source-float16", "target-float16"),
)
def test_herosweb_native_decoder_rejects_unobserved_color_formats(
    field: str, value: str
) -> None:
    record = _record()
    proof = record["proof"]
    assert isinstance(proof, dict)
    proof[field] = value
    assert native_capture.decode_native_candidates(
        _materialization(record), expected_targets=[TARGET]
    ) == (None,)


def test_herosweb_native_target_drift_is_fatal_instead_of_png_fallback() -> None:
    record = _record()
    proof = record["proof"]
    assert isinstance(proof, dict)
    proof["targetEpochAfter"] = 10
    with pytest.raises(UnknownPageStateError, match="target identity changed"):
        native_capture.decode_native_candidates(
            _materialization(record), expected_targets=[TARGET]
        )


def test_herosweb_native_materialization_drift_is_fatal() -> None:
    raw = _materialization(_record())
    raw["status"] = "target_drift"
    with pytest.raises(UnknownPageStateError, match="changed during native"):
        native_capture.decode_native_candidates(raw, expected_targets=[TARGET])


@pytest.mark.parametrize(
    ("field", "value"),
    [("drawSeekValue", 15), ("drawWrapperNodeId", 99)],
    ids=("wrong-draw-seek", "wrong-draw-owner"),
)
def test_herosweb_native_draw_binding_drift_is_fatal(field: str, value: int) -> None:
    record = _record()
    proof = record["proof"]
    assert isinstance(proof, dict)
    proof[field] = value
    with pytest.raises(UnknownPageStateError, match="target identity changed"):
        native_capture.decode_native_candidates(
            _materialization(record), expected_targets=[TARGET]
        )


@pytest.mark.parametrize(
    ("rect_field", "field", "value"),
    [
        ("materializedTargetRect", "width", 624),
        ("materializedTargetRect", "width", 623.4),
        ("materializedTargetRect", "x", 945),
        ("materializedTargetRect", "x", -1.6),
    ],
    ids=("scale-change", "subpixel-scale-change", "target-wrapper-translation-mismatch", "subpixel-relative-offset"),
)
def test_herosweb_native_draw_geometry_mismatch_uses_png_fallback(
    rect_field: str, field: str, value: float
) -> None:
    record = _record()
    proof = record["proof"]
    assert isinstance(proof, dict)
    rect = proof[rect_field]
    assert isinstance(rect, dict)
    rect[field] = value
    assert native_capture.decode_native_candidates(
        _materialization(record), expected_targets=[TARGET]
    ) == (None,)


def test_herosweb_native_draw_accepts_only_the_observed_pending_pr_root_mode() -> None:
    record = _record()
    proof = record["proof"]
    assert isinstance(proof, dict)
    proof["drawRootStructuralModes"] = [
        mode for mode in TARGET["rootStructuralModes"] if mode != "mode-has-pr"
    ]
    candidate = native_capture.decode_native_candidates(
        _materialization(record), expected_targets=[TARGET]
    )[0]
    assert candidate is not None
    assert "mode-has-pr" not in candidate.proof["drawRootStructuralModes"]


def test_herosweb_native_draw_rejects_pending_pr_mode_after_first_spread() -> None:
    target = _target_for_slot(2)
    record = _record(slot=2)
    proof = record["proof"]
    assert isinstance(proof, dict)
    proof["drawRootStructuralModes"] = [
        mode for mode in target["rootStructuralModes"] if mode != "mode-has-pr"
    ]
    assert native_capture.decode_native_candidates(
        _materialization(record), expected_targets=[target]
    ) == (None,)


def test_herosweb_native_draw_rejects_other_root_mode_differences() -> None:
    record = _record()
    proof = record["proof"]
    assert isinstance(proof, dict)
    proof["drawRootStructuralModes"] = ["mode-h", "mode-has-pr", "mode-other", "mode-spread"]
    assert native_capture.decode_native_candidates(
        _materialization(record), expected_targets=[TARGET]
    ) == (None,)


def test_herosweb_verified_native_png_is_kept_when_webp_validation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = native_capture.decode_native_candidates(
        _materialization(_record()), expected_targets=[TARGET]
    )[0]
    assert candidate is not None
    monkeypatch.setattr(native_capture.features, "check", lambda _name: True)
    monkeypatch.setattr(native_capture, "_single_vp8l", lambda *_args, **_kwargs: False)
    output = native_capture.encode_native_candidates((candidate,))[0]
    assert output is not None
    assert output.mode == "source_canvas_native_png"
    assert output.capture.mime_type == "image/png"
    assert output.capture.file_extension == ".png"
    assert output.capture.data == candidate.png
    assert output.proof["encoder_status"] == "failed_validation"


def test_herosweb_missing_native_source_remains_rendered_png_fallback() -> None:
    record = _record()
    record["supported"] = False
    assert native_capture.decode_native_candidates(
        _materialization(record), expected_targets=[TARGET]
    ) == (None,)
