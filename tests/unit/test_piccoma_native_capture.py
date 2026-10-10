from __future__ import annotations

import json
from io import BytesIO

import pytest
from PIL import Image, ImageChops

import screenshot_crawler.site_adapters.piccoma.native_capture as piccoma_native_capture_module
from screenshot_crawler.core.capture import CaptureResult
from screenshot_crawler.core.errors import UnknownPageStateError
from screenshot_crawler.site_adapters.piccoma.adapter import PiccomaAdapter
from screenshot_crawler.site_adapters.piccoma.native_capture import (
    NativeCaptureUnavailable,
    _decode_native_snapshot_json,
    capture_result_format_is_valid,
    composite_replay_png_on_white,
    encode_lossless_webp,
    encode_lossless_webp_or_png,
    target_generation_signature,
    validate_source_jpeg,
    validate_tile_trace,
    validate_white_paint_path,
)

SOURCE_URL = "https://pcm.kakaocdn.net/dna/a/b/c/i123.jpg?token=fixture"
CONTEXT_ATTRIBUTES = {
    "alpha": True,
    "colorSpace": "srgb",
    "colorType": "unorm8",
    "desynchronized": False,
    "toneMapping": {"mode": "standard"},
    "willReadFrequently": False,
}
DRAW_STATE = {
    "alpha": 1,
    "composite": "source-over",
    "filter": "none",
    "smoothing": True,
    "smoothingQuality": "low",
    "shadowBlur": 0,
    "shadowColor": "rgba(0, 0, 0, 0)",
    "shadowOffsetX": 0,
    "shadowOffsetY": 0,
    "transform": [1, 0, 0, 1, 0, 0],
    "clipCount": 0,
}


def _trace(width: int = 844) -> dict[str, object]:
    events: list[dict[str, object]] = [
        {
            "type": "getContext",
            "contextType": "2d",
            "argumentCount": 1,
            "options": None,
            "attributes": CONTEXT_ATTRIBUTES,
            "canvasDimensions": [300, 150],
        },
        {
            "type": "dimension_set",
            "dimension": "width",
            "requested": width,
            "before": [300, 150],
            "after": [width, 150],
        },
        {
            "type": "dimension_set",
            "dimension": "height",
            "requested": 1200,
            "before": [width, 150],
            "after": [width, 1200],
        },
    ]
    for row in range(24):
        for column in range(17):
            destination_x = column * 50
            destination_y = row * 50
            source_index = (row * 17 + column) * 37 % 408
            source_x = (source_index % 17) * 50
            source_y = (source_index // 17) * 50
            tile_width = min(50, width - destination_x)
            events.append(
                {
                    "type": "drawImage",
                    "sourceId": "image-1",
                    "sourceKind": "HTMLImageElement",
                    "sourceUrl": SOURCE_URL,
                    "sourceWidth": width,
                    "sourceHeight": 1200,
                    "sourceComplete": True,
                    "assignmentGeneration": 1,
                    "loadGeneration": 1,
                    "lastLoadedAssignmentGeneration": 1,
                    "lastLoadedSource": SOURCE_URL,
                    "args": [
                        source_x,
                        source_y,
                        min(50, width - source_x),
                        50.01,
                        destination_x,
                        destination_y,
                        tile_width,
                        50,
                    ],
                    "overload": 9,
                    "state": DRAW_STATE,
                    "targetDimensions": [width, 1200],
                }
            )
    return {
        "id": "canvas-1",
        "initialDimensions": [300, 150],
        "dimensions": [width, 1200],
        "connected": True,
        "overflow": False,
        "totalOverflow": False,
        "sourceOverflow": False,
        "unobservedAttributeMutation": False,
        "generation": 411,
        "retired": False,
        "retained": True,
        "hooksIntact": True,
        "sourceStates": [
            {
                "id": "image-1",
                "currentSrc": SOURCE_URL,
                "src": SOURCE_URL,
                "assignmentGeneration": 1,
                "loadGeneration": 1,
                "lastLoadedAssignmentGeneration": 1,
                "lastLoadedSource": SOURCE_URL,
                "complete": True,
                "naturalWidth": width,
                "naturalHeight": 1200,
            }
        ],
        "events": events,
    }


def _snapshot_json_fixture() -> dict[str, object]:
    snapshot = _trace()
    snapshot["attributeObserverReady"] = True
    snapshot["paint"] = {"firstOpaqueColor": None}
    return snapshot


def test_native_snapshot_json_round_trip_preserves_full_trace_and_nulls() -> None:
    snapshot = _snapshot_json_fixture()

    restored = _decode_native_snapshot_json(json.dumps(snapshot))

    assert restored == snapshot
    assert restored is not None
    assert restored["events"][0]["options"] is None
    assert restored["paint"]["firstOpaqueColor"] is None
    assert target_generation_signature(restored) == target_generation_signature(snapshot)
    assert validate_tile_trace(
        restored, expected_width=844, expected_height=1200
    ) == validate_tile_trace(snapshot, expected_width=844, expected_height=1200)


@pytest.mark.parametrize(
    "value",
    [
        "{",
        "[]",
        "true",
        "0",
        '"trace"',
        'NaN',
        '{"id":"first","id":"second"}',
        '{"dimensions":[-0,0]}',
        '{"dimensions":[-0.0,0]}',
    ],
)
def test_native_snapshot_json_rejects_malformed_or_ambiguous_values(value: str) -> None:
    with pytest.raises(NativeCaptureUnavailable) as error:
        _decode_native_snapshot_json(value)

    assert error.value.unsafe_live_change is True


@pytest.mark.parametrize(
    "mutate",
    [
        lambda snapshot: snapshot.pop("paint"),
        lambda snapshot: snapshot.update(generation="1"),
        lambda snapshot: snapshot.update(events=[None]),
        lambda snapshot: snapshot.update(sourceStates="missing"),
        lambda snapshot: snapshot.update(paint=[]),
    ],
)
def test_native_snapshot_json_rejects_incomplete_or_wrong_schema(mutate) -> None:
    snapshot = _snapshot_json_fixture()
    mutate(snapshot)

    with pytest.raises(NativeCaptureUnavailable) as error:
        _decode_native_snapshot_json(json.dumps(snapshot))

    assert error.value.unsafe_live_change is True


def test_native_snapshot_json_rejects_oversized_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        piccoma_native_capture_module, "MAX_NATIVE_SNAPSHOT_BYTES", 8
    )

    with pytest.raises(NativeCaptureUnavailable) as error:
        _decode_native_snapshot_json('"123456789"')

    assert error.value.unsafe_live_change is True


@pytest.mark.parametrize(
    ("device_pixel_ratio", "supported"),
    [
        (1, True),
        (1.0, True),
        (1 + 2**-25, True),
        (1 - 2**-25, True),
        (1 + 0.99e-7, True),
        (float("nan"), False),
        (float("inf"), False),
        (float("-inf"), False),
        (True, False),
        (False, False),
        (1 + 1.01e-7, False),
        (1.25, False),
        (2, False),
        (None, False),
        ("1", False),
    ],
)
def test_piccoma_geometry_accepts_only_finite_near_one_device_pixel_ratio(
    device_pixel_ratio: object, supported: bool
) -> None:
    adapter = PiccomaAdapter()
    row = {
        "canvas": {
            "width": 844,
            "height": 1200,
            "rect": [530, 0, 844, 1200],
            "inFrame": True,
            "renderability": {
                "visible": True,
                "ancestors": [
                    {
                        "display": "block",
                        "visibility": "visible",
                        "opacity": 1,
                        "contentVisibility": "visible",
                    }
                ],
            },
        }
    }
    snapshot = {
        "viewport": [1904, 1200, device_pixel_ratio],
        "frameRect": [530, 0, 844, 1200],
    }

    if supported:
        assert adapter._validate_canvas_geometry(snapshot, row) == (844, 1200)
    else:
        with pytest.raises(UnknownPageStateError, match="supported viewport"):
            adapter._validate_canvas_geometry(snapshot, row)


def _white_paint_path(width: int = 844) -> dict[str, object]:
    rect = [530, 0, width, 1200]
    transparent = {
        "rect": rect,
        "backgroundColor": "rgba(0, 0, 0, 0)",
        "backgroundImage": "none",
        "opacity": "1",
        "filter": "none",
        "backdropFilter": "none",
        "mixBlendMode": "normal",
        "maskImage": "none",
        "clipPath": "none",
        "clip": "auto",
        "backgroundClip": "border-box",
        "borderWidths": ["0px", "0px", "0px", "0px"],
        "borderRadius": "0px",
        "boxShadow": "none",
        "overflow": "visible",
        "transform": "none",
        "visibility": "visible",
        "display": "block",
        "alpha": 0,
        "before": {
            "content": "none",
            "backgroundColor": "rgba(0, 0, 0, 0)",
            "backgroundImage": "none",
            "opacity": "1",
            "filter": "none",
            "mixBlendMode": "normal",
        },
        "after": {
            "content": "none",
            "backgroundColor": "rgba(0, 0, 0, 0)",
            "backgroundImage": "none",
            "opacity": "1",
            "filter": "none",
            "mixBlendMode": "normal",
        },
    }
    opaque = {
        **transparent,
        "backgroundColor": "rgb(255, 255, 255)",
        "alpha": 1,
        "overflow": "hidden",
    }
    return {
        "canvasId": "canvas-1",
        "canvasRect": rect,
        "ancestors": [transparent, transparent.copy(), opaque],
        "overlappingDescendants": [],
        "firstOpaqueIndex": 2,
        "firstOpaqueColor": [255, 255, 255, 1],
        "firstOpaqueCoversCanvas": True,
    }


def _jpeg(*, subsampling: int = 0, progressive: bool = False) -> bytes:
    image = Image.new("RGB", (844, 1200), "white")
    output = BytesIO()
    image.save(
        output,
        format="JPEG",
        quality=90,
        subsampling=subsampling,
        progressive=progressive,
    )
    return output.getvalue()


@pytest.mark.parametrize("width", [842, 844])
def test_validates_full_fractional_source_and_destination_grid(width: int) -> None:
    result = validate_tile_trace(_trace(width), expected_width=width, expected_height=1200)

    assert result.width == width
    assert result.height == 1200
    assert result.source_url == SOURCE_URL
    assert len(result.draws) == 408
    assert all(draw["args"][3] == 50.01 for draw in result.draws)
    assert result.draws[-1]["args"][6:] == [width % 50 or 50, 50]


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (lambda trace: trace.update(overflow=True), "overflow"),
        (lambda trace: trace.update(unobservedAttributeMutation=True), "attribute"),
        (lambda trace: trace.update(hooksIntact=False), "hooks"),
        (lambda trace: trace["events"].append({"type": "clip"}), "count"),
        (lambda trace: trace["events"].__setitem__(1, {"type": "attribute_dimension_set"}), "reset"),
        (lambda trace: trace["events"][3].update(state={**DRAW_STATE, "filter": "blur(1px)"}), "state"),
        (lambda trace: trace["events"][4].update(sourceId="image-2"), "source"),
        (lambda trace: trace["events"][4].update(loadGeneration=2), "reload"),
        (lambda trace: trace["events"][3].update(args=[550, 150, 50, 50, 0, 0, 50, 50]), "fraction"),
        (lambda trace: trace["events"][3].update(sourceUrl="https://other.example/dna/x?y=1"), "url"),
        (lambda trace: trace["events"][3].update(sourceUrl="https://pcm.kakaocdn.net/dna/a/b/c/not-image.jpg?token=x"), "path"),
        (lambda trace: trace["events"][3].update(sourceUrl="https://pcm.kakaocdn.net/dna/a/b/i123.jpg?token=x"), "path"),
        (lambda trace: trace["events"][3].update(overload=5), "overload"),
        (lambda trace: trace["events"][3].update(sourceComplete=False), "complete"),
    ],
)
def test_rejects_trace_gaps_or_unobserved_generation_changes(change, reason: str) -> None:
    trace = _trace()
    change(trace)

    with pytest.raises(NativeCaptureUnavailable):
        validate_tile_trace(trace, expected_width=844, expected_height=1200)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda trace: trace["sourceStates"][0].update(assignmentGeneration=2),
        lambda trace: trace["sourceStates"][0].update(loadGeneration=2),
        lambda trace: trace["sourceStates"][0].update(currentSrc="https://other.example/a"),
        lambda trace: trace["sourceStates"].append(dict(trace["sourceStates"][0], id="image-2")),
        lambda trace: trace.update(sourceOverflow=True),
    ],
)
def test_rejects_unstable_or_ambiguous_live_image_object_state(mutate) -> None:
    trace = _trace()
    mutate(trace)

    with pytest.raises(NativeCaptureUnavailable):
        validate_tile_trace(trace, expected_width=844, expected_height=1200)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda rows: rows[1].update(backgroundColor="rgb(250, 255, 255)", alpha=1),
        lambda rows: rows[1].update(backgroundImage="url(x.png)"),
        lambda rows: rows[1].update(filter="blur(1px)"),
        lambda rows: rows[1].update(maskImage="url(x.svg)"),
        lambda rows: rows[1].update(clipPath="inset(1px)"),
        lambda rows: rows[2].update(backgroundClip="text"),
        lambda rows: rows[2].update(borderWidths=["0px", "1px", "0px", "0px"]),
        lambda rows: rows[2].update(clip="rect(0px, 1px, 1px, 0px)"),
        lambda rows: rows[1].update(transform="matrix(1, 0, 0, 1, 1, 0)"),
        lambda rows: rows[1]["before"].update(content='"unknown"'),
        lambda rows: rows[2].update(rect=[530, 0, 800, 1200]),
        lambda rows: rows[2].update(boxShadow="0 0 2px black"),
    ],
)
def test_white_backdrop_gate_rejects_unobserved_paint(mutate) -> None:
    snapshot = _white_paint_path()
    mutate(snapshot["ancestors"])

    assert not validate_white_paint_path(snapshot, width=844, height=1200)


def test_white_backdrop_gate_accepts_only_covering_solid_white() -> None:
    assert validate_white_paint_path(_white_paint_path(), width=844, height=1200)


def test_white_backdrop_gate_rejects_visible_sibling_overlapping_canvas() -> None:
    snapshot = _white_paint_path()
    snapshot["overlappingDescendants"] = [
        {"tag": "DIV", "classes": "overlay", "rect": [530, 0, 844, 1200]}
    ]

    assert not validate_white_paint_path(snapshot, width=844, height=1200)


def test_target_generation_signature_tracks_evicted_lightweight_targets() -> None:
    snapshot = _trace()
    snapshot.update(generation=500, retired=True, retained=False, events=[])
    baseline = target_generation_signature(snapshot)
    assert baseline is not None

    snapshot["generation"] += 1
    assert target_generation_signature(snapshot) != baseline


@pytest.mark.parametrize(
    ("subsampling", "progressive", "accepted"),
    [(0, False, True), (2, False, False), (0, True, False)],
)
def test_source_jpeg_must_match_observed_baseline_444_layout(
    subsampling: int, progressive: bool, accepted: bool
) -> None:
    data = _jpeg(subsampling=subsampling, progressive=progressive)
    if accepted:
        validate_source_jpeg(data, width=844, height=1200)
    else:
        with pytest.raises(NativeCaptureUnavailable):
            validate_source_jpeg(data, width=844, height=1200)


def test_replay_output_is_composited_on_white_without_lossy_reencoding() -> None:
    source = Image.new("RGBA", (2, 1), (0, 0, 0, 0))
    source.putpixel((0, 0), (100, 20, 30, 128))
    source.putpixel((1, 0), (5, 6, 7, 255))
    encoded = BytesIO()
    source.save(encoded, format="PNG")

    result = composite_replay_png_on_white(encoded.getvalue(), width=2, height=1)
    with Image.open(BytesIO(result)) as actual:
        assert actual.format == "PNG"
        assert actual.size == (2, 1)
        assert actual.mode == "RGB"
        assert actual.getpixel((0, 0)) == (177, 137, 142)
        assert actual.getpixel((1, 0)) == (5, 6, 7)
        changed_rgb_pixel = actual.copy()
        changed_rgb_pixel.putpixel((0, 0), (177, 138, 142))
        assert ImageChops.difference(actual, changed_rgb_pixel).getbbox() is not None


def test_lossless_webp_round_trip_preserves_full_rgb_without_resizing() -> None:
    source = Image.new("RGB", (53, 31))
    source.putdata(
        [
            (x * 13 % 256, y * 17 % 256, (x * 7 + y * 19) % 256)
            for y in range(source.height)
            for x in range(source.width)
        ]
    )
    png = BytesIO()
    source.save(png, format="PNG")

    result = encode_lossless_webp(png.getvalue(), width=53, height=31)

    assert result.mime_type == "image/webp"
    assert result.file_extension == ".webp"
    assert (result.width, result.height) == (53, 31)
    assert result.data[:4] == b"RIFF" and result.data[8:12] == b"WEBP"
    with Image.open(BytesIO(result.data)) as decoded:
        assert decoded.format == "WEBP"
        assert decoded.size == source.size
        assert decoded.convert("RGB").tobytes() == source.tobytes()


def test_lossless_webp_round_trip_preserves_white_composited_partial_alpha_rgb() -> None:
    source = Image.new("RGBA", (3, 2), (0, 0, 0, 0))
    source.putpixel((0, 0), (17, 189, 231, 64))
    source.putpixel((1, 0), (211, 23, 88, 128))
    source.putpixel((2, 1), (35, 167, 29, 255))
    png = BytesIO()
    source.save(png, format="PNG")
    composite = composite_replay_png_on_white(png.getvalue(), width=3, height=2)
    with Image.open(BytesIO(composite)) as expected:
        expected_rgb = expected.convert("RGB").tobytes()

    result = encode_lossless_webp(composite, width=3, height=2)

    with Image.open(BytesIO(result.data)) as decoded:
        assert decoded.convert("RGB").tobytes() == expected_rgb


def test_lossless_webp_encode_failure_retains_validated_native_png(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = Image.new("RGB", (4, 3), (29, 141, 237))
    png = BytesIO()
    source.save(png, format="PNG")

    def fail_encoder(*_args, **_kwargs):
        raise NativeCaptureUnavailable("webp_codec_unavailable")

    monkeypatch.setattr(
        piccoma_native_capture_module, "encode_lossless_webp", fail_encoder
    )
    result, reason = encode_lossless_webp_or_png(
        png.getvalue(), width=4, height=3
    )

    assert reason == "webp_codec_unavailable"
    assert result.data == png.getvalue()
    assert result.mime_type == "image/png"
    assert result.file_extension == ".png"
    assert capture_result_format_is_valid(result, width=4, height=3)


def test_capture_result_metadata_rejects_mime_extension_payload_and_dimension_mismatch() -> None:
    source = Image.new("RGB", (4, 3), (29, 141, 237))
    png = BytesIO()
    source.save(png, format="PNG")
    webp = encode_lossless_webp(png.getvalue(), width=4, height=3)
    truncated_png = CaptureResult(png.getvalue()[:-10], 4, 3, "image/png", ".png")
    animated_png_bytes = BytesIO()
    source.save(
        animated_png_bytes,
        format="PNG",
        save_all=True,
        append_images=[Image.new("RGB", (4, 3), (1, 2, 3))],
    )
    animated_png = CaptureResult(
        animated_png_bytes.getvalue(), 4, 3, "image/png", ".png"
    )

    assert capture_result_format_is_valid(webp, width=4, height=3)
    invalid_results = (
        CaptureResult(webp.data, 4, 3, "image/png", ".png"),
        CaptureResult(webp.data, 4, 3, "image/webp", ".png"),
        CaptureResult(b"RIFF\x00\x00\x00\x00WEBPbad", 4, 3, "image/webp", ".webp"),
        CaptureResult(webp.data, 5, 3, "image/webp", ".webp"),
        CaptureResult(webp.data, 4, 3, "image/webp", ".jpg"),
        truncated_png,
        animated_png,
    )
    for result in invalid_results:
        assert not capture_result_format_is_valid(result, width=4, height=3), result


def test_capture_result_metadata_rejects_lossy_webp_even_when_rgb_is_exact() -> None:
    source = Image.new("RGB", (1, 1), (255, 255, 255))
    encoded = BytesIO()
    source.save(encoded, format="WEBP", lossless=False, quality=100)
    lossy = CaptureResult(
        encoded.getvalue(), 1, 1, "image/webp", ".webp"
    )
    with Image.open(BytesIO(lossy.data)) as decoded:
        assert decoded.convert("RGB").tobytes() == source.tobytes()
    assert not capture_result_format_is_valid(lossy, width=1, height=1)
