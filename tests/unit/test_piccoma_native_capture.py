from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image, ImageChops

from screenshot_crawler.site_adapters.piccoma.native_capture import (
    NativeCaptureUnavailable,
    composite_replay_png_on_white,
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
