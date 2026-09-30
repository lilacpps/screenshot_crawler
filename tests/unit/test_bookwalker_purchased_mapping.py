from __future__ import annotations

import pytest

from screenshot_crawler.site_adapters.bookwalker.purchased_mapping import (
    MAPPING_PROVEN,
    analyze_purchased_mapping,
)

IDENTITY = {"a": 1, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0}


def _draw(
    index: int,
    source_x: int,
    source_y: int,
    destination_x: int,
    destination_y: int,
    *,
    source_id: str = "bitmap-a",
    **overrides: object,
) -> dict:
    operation = {
        "index": index,
        "operation": "drawImage",
        "target": {"canvasId": "source-canvas", "width": 32, "height": 32},
        "source": {
            "sourceId": source_id,
            "constructor": "ImageBitmap",
            "width": 32,
            "height": 32,
        },
        "sourceRect": {"x": source_x, "y": source_y, "width": 16, "height": 16},
        "destination": {
            "x": destination_x,
            "y": destination_y,
            "width": 16,
            "height": 16,
        },
        "transform": dict(IDENTITY),
        "globalAlpha": 1,
        "globalCompositeOperation": "source-over",
        "filter": "none",
    }
    operation.update(overrides)
    return operation


def _trace(*, include_prefetch: bool = False, operations: list[dict] | None = None) -> tuple[dict, dict]:
    source_operations = [
        {"index": 1, "operation": "clearRect", "target": {"canvasId": "source-canvas"}, "arguments": [0, 0, 32, 32]},
        _draw(2, 0, 0, 16, 0),
        _draw(3, 16, 0, 0, 0),
        _draw(4, 0, 16, 0, 16),
        _draw(5, 16, 16, 16, 16),
    ]
    if include_prefetch:
        source_operations.insert(0, _draw(0, 0, 0, 0, 0, source_id="prefetch"))
    renderer = {
        "index": 6,
        "operation": "drawImage",
        "target": {"canvasId": "renderer", "width": 32, "height": 32},
        "source": {
            "sourceId": "source-object",
            "canvasId": "source-canvas",
            "constructor": "HTMLCanvasElement",
            "width": 32,
            "height": 32,
        },
        "sourceRect": {"x": 0, "y": 0, "width": 32, "height": 32},
        "destination": {"x": 0, "y": 0, "width": 32, "height": 32},
        "transform": dict(IDENTITY),
        "globalAlpha": 1,
        "globalCompositeOperation": "source-over",
        "filter": "none",
    }
    return {"operations": [*source_operations, renderer] if operations is None else operations}, renderer


def test_purchased_mapping_proves_identity_and_tile_swap_with_object_identity() -> None:
    trace, renderer = _trace()

    result = analyze_purchased_mapping(trace, renderer)

    assert result.status == MAPPING_PROVEN
    assert result.mapping is not None
    assert result.mapping.source_canvas_id == "source-canvas"
    assert result.mapping.imagebitmap_source_id == "bitmap-a"
    assert result.mapping.mapping[0]["destination_x"] == 16
    assert result.mapping.mapping_sha256


def test_latest_clear_boundary_ignores_prefetch_group() -> None:
    trace, renderer = _trace(include_prefetch=True)

    result = analyze_purchased_mapping(trace, renderer)

    assert result.proven
    assert result.mapping is not None
    assert result.mapping.imagebitmap_source_id == "bitmap-a"


def test_renderer_destination_offset_is_allowed_for_spread_part() -> None:
    trace, renderer = _trace()
    renderer["destination"] = {"x": 960, "y": 0, "width": 32, "height": 32}
    renderer["target"] = {"canvasId": "renderer", "width": 1024, "height": 32}
    trace["operations"][-1]["destination"] = dict(renderer["destination"])
    trace["operations"][-1]["target"] = dict(renderer["target"])

    result = analyze_purchased_mapping(trace, renderer)

    assert result.proven


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("transform", {"a": 1, "b": 0, "c": 1, "d": 1, "e": 0, "f": 0}, "pixel processing"),
        ("globalAlpha", 0.5, "pixel processing"),
        ("globalCompositeOperation", "multiply", "pixel processing"),
        ("filter", "blur(1px)", "pixel processing"),
    ],
)
def test_unsafe_tile_draw_fails_closed(field: str, value: object, reason: str) -> None:
    trace, renderer = _trace()
    trace["operations"][1][field] = value

    result = analyze_purchased_mapping(trace, renderer)

    assert not result.proven
    assert reason in result.reason


def test_additional_pixel_operation_and_overflow_fail_closed() -> None:
    trace, renderer = _trace()
    trace["operations"].insert(
        2,
        {
            "index": 2,
            "operation": "putImageData",
            "target": {"canvasId": "source-canvas"},
            "arguments": [0, 0],
        },
    )
    result = analyze_purchased_mapping(trace, renderer)
    assert not result.proven
    assert result.additional_pixel_processing

    overflow_trace, overflow_renderer = _trace()
    overflow_trace["trace_overflow"] = True
    overflow_result = analyze_purchased_mapping(overflow_trace, overflow_renderer)
    assert not overflow_result.proven
    assert overflow_result.trace_overflow


def _completed_record(
    *,
    mapping_id: str = "mapping-106",
    renderer_index: int = 106,
    clear_index: int = 101,
    destination: dict[str, float | int] | None = None,
    source_rect: dict[str, float | int] | None = None,
    tile_draws: list[dict] | None = None,
    **overrides: object,
) -> dict:
    tiles = tile_draws or [
        {
            "operationIndex": 102,
            "source": {"sourceId": "bitmap-a", "constructor": "ImageBitmap", "width": 32, "height": 32},
            "target": {"canvasId": "source-canvas", "width": 32, "height": 32},
            "sourceRect": {"x": 0, "y": 0, "width": 16, "height": 16},
            "destination": {"x": 16, "y": 0, "width": 16, "height": 16},
            "transform": dict(IDENTITY), "globalAlpha": 1,
            "globalCompositeOperation": "source-over", "filter": "none",
        },
        {
            "operationIndex": 103,
            "source": {"sourceId": "bitmap-a", "constructor": "ImageBitmap", "width": 32, "height": 32},
            "target": {"canvasId": "source-canvas", "width": 32, "height": 32},
            "sourceRect": {"x": 16, "y": 0, "width": 16, "height": 16},
            "destination": {"x": 0, "y": 0, "width": 16, "height": 16},
            "transform": dict(IDENTITY), "globalAlpha": 1,
            "globalCompositeOperation": "source-over", "filter": "none",
        },
        {
            "operationIndex": 104,
            "source": {"sourceId": "bitmap-a", "constructor": "ImageBitmap", "width": 32, "height": 32},
            "target": {"canvasId": "source-canvas", "width": 32, "height": 32},
            "sourceRect": {"x": 0, "y": 16, "width": 16, "height": 16},
            "destination": {"x": 0, "y": 16, "width": 16, "height": 16},
            "transform": dict(IDENTITY), "globalAlpha": 1,
            "globalCompositeOperation": "source-over", "filter": "none",
        },
        {
            "operationIndex": 105,
            "source": {"sourceId": "bitmap-a", "constructor": "ImageBitmap", "width": 32, "height": 32},
            "target": {"canvasId": "source-canvas", "width": 32, "height": 32},
            "sourceRect": {"x": 16, "y": 16, "width": 16, "height": 16},
            "destination": {"x": 16, "y": 16, "width": 16, "height": 16},
            "transform": dict(IDENTITY), "globalAlpha": 1,
            "globalCompositeOperation": "source-over", "filter": "none",
        },
    ]
    record = {
        "mappingId": mapping_id,
        "rendererOperationIndex": renderer_index,
        "rendererTarget": {"canvasId": "renderer", "width": 32, "height": 32},
        "sourceCanvas": {"canvasId": "source-canvas", "width": 32, "height": 32},
        "rendererSourceRect": source_rect or {"x": 0, "y": 0, "width": 32, "height": 32},
        "rendererDestination": destination or {"x": 0, "y": 0, "width": 32, "height": 32},
        "rendererTransform": dict(IDENTITY),
        "rendererAlpha": 1,
        "rendererComposite": "source-over",
        "rendererFilter": "none",
        "segmentClearOperationIndex": clear_index,
        "segmentClearRectangle": {"x": 0, "y": 0, "width": 32, "height": 32},
        "segmentFirstTileOperationIndex": tiles[0]["operationIndex"] if tiles else None,
        "segmentLastTileOperationIndex": tiles[-1]["operationIndex"] if tiles else None,
        "segmentTileCount": len(tiles),
        "segmentExpectedTileCount": 4,
        "tileDraws": tiles,
        "sourceIds": ["bitmap-a"],
        "unsafeOperationCount": 0,
        "firstUnsafeOperationIndex": None,
        "unsafeOperationTypes": [],
        "segmentOverflow": False,
    }
    record.update(overrides)
    return record


def _completed_draw(record: dict) -> dict:
    return {
        "mappingId": record["mappingId"],
        "traceOperationIndex": record["rendererOperationIndex"],
        "sourceCanvasId": record["sourceCanvas"]["canvasId"],
    }


def test_completed_segment_is_production_authority_past_global_operation_count() -> None:
    record = _completed_record()
    trace = {
        "completedMappings": [record],
        "nextOperationIndex": 9001,
        "traceOverflow": True,
        "droppedCompletedMappingCount": 0,
    }

    result = analyze_purchased_mapping(trace, _completed_draw(record))

    assert result.proven
    assert result.mapping is not None
    assert result.mapping.mapping_id == "mapping-106"
    assert result.mapping.renderer_geometry_classification == "DIRECT_RENDERER_DRAW"


def test_completed_segment_freezes_separate_repeated_passes() -> None:
    first = _completed_record()
    second = _completed_record(mapping_id="mapping-212", renderer_index=212, clear_index=207)
    second["tileDraws"] = [dict(tile, operationIndex=tile["operationIndex"] + 106) for tile in first["tileDraws"]]
    second["segmentFirstTileOperationIndex"] = 208
    second["segmentLastTileOperationIndex"] = 211
    trace = {"completedMappings": [first, second]}

    first_result = analyze_purchased_mapping(trace, _completed_draw(first))
    second_result = analyze_purchased_mapping(trace, _completed_draw(second))

    assert first_result.proven and second_result.proven
    assert first_result.mapping is not None and second_result.mapping is not None
    assert first_result.mapping.clear_boundary_operation_index == 101
    assert second_result.mapping.clear_boundary_operation_index == 207
    assert first_result.mapping.mapping_sha256 == second_result.mapping.mapping_sha256


def test_completed_segment_allows_pure_renderer_scale_but_rejects_crop() -> None:
    scaled = _completed_record(
        destination={"x": 0, "y": 0, "width": 24, "height": 24},
        rendererTarget={"canvasId": "renderer", "width": 24, "height": 24},
    )
    scaled_result = analyze_purchased_mapping({"completedMappings": [scaled]}, _completed_draw(scaled))
    assert scaled_result.proven
    assert scaled_result.renderer_geometry_classification == "PURE_RENDERER_SCALE"

    cropped = _completed_record(
        source_rect={"x": 0, "y": 0, "width": 31.5, "height": 32},
    )
    cropped_result = analyze_purchased_mapping({"completedMappings": [cropped]}, _completed_draw(cropped))
    assert not cropped_result.proven
    assert cropped_result.renderer_geometry_classification == "CROP_OR_PIXEL_PROCESSING"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("segmentOverflow", True),
        ("unsafeOperationCount", 1),
        ("unsafeOperationTypes", ["partial_clear"]),
    ],
)
def test_completed_segment_unsafe_metadata_fails_closed(field: str, value: object) -> None:
    record = _completed_record(**{field: value})

    result = analyze_purchased_mapping({"completedMappings": [record]}, _completed_draw(record))

    assert not result.proven


def test_evicted_completed_mapping_is_not_reconstructed_from_dimensions() -> None:
    record = _completed_record()
    draw = _completed_draw(record)
    draw["mappingId"] = "mapping-evicted"

    result = analyze_purchased_mapping({"completedMappings": []}, draw)

    assert not result.proven
    assert result.completed_mapping_evicted
