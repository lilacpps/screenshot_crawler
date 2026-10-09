from __future__ import annotations

import copy
from dataclasses import replace

import pytest

from screenshot_crawler.site_adapters.bookwalker.purchased_mapping import (
    MAPPING_PROVEN,
    analyze_purchased_mapping,
    decode_compact_completed_mappings,
    resolve_scaled_canvas_source_candidate,
    validate_scaled_canvas_source_analysis,
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
        "nonImageBitmapDraws": [],
    }
    record.update(overrides)
    return record


def _completed_draw(record: dict) -> dict:
    return {
        "mappingId": record["mappingId"],
        "traceOperationIndex": record["rendererOperationIndex"],
        "sourceCanvasId": record["sourceCanvas"]["canvasId"],
    }


def _cropped_completed_record(
    *, visible_width: int = 36, mapping_id: str = "mapping-cropped"
) -> dict:
    """A small nonuniform 40px coded frame cropped to a 36px visible frame."""

    tiles: list[dict] = []
    operation = 102
    for y in (0, 16):
        tiles.extend(
            [
                {
                    "operationIndex": operation,
                    "source": {
                        "sourceId": "bitmap-cropped",
                        "constructor": "ImageBitmap",
                        "width": 40,
                        "height": 32,
                    },
                    "target": {
                        "canvasId": "source-canvas",
                        "width": visible_width,
                        "height": 32,
                    },
                    "sourceRect": {"x": 0, "y": y, "width": 16, "height": 16},
                    "destination": {"x": 16, "y": y, "width": 16, "height": 16},
                    "transform": dict(IDENTITY),
                    "globalAlpha": 1,
                    "globalCompositeOperation": "source-over",
                    "filter": "none",
                },
                {
                    "operationIndex": operation + 1,
                    "source": {
                        "sourceId": "bitmap-cropped",
                        "constructor": "ImageBitmap",
                        "width": 40,
                        "height": 32,
                    },
                    "target": {
                        "canvasId": "source-canvas",
                        "width": visible_width,
                        "height": 32,
                    },
                    "sourceRect": {"x": 16, "y": y, "width": 16, "height": 16},
                    "destination": {"x": 0, "y": y, "width": 16, "height": 16},
                    "transform": dict(IDENTITY),
                    "globalAlpha": 1,
                    "globalCompositeOperation": "source-over",
                    "filter": "none",
                },
                {
                    "operationIndex": operation + 2,
                    "source": {
                        "sourceId": "bitmap-cropped",
                        "constructor": "ImageBitmap",
                        "width": 40,
                        "height": 32,
                    },
                    "target": {
                        "canvasId": "source-canvas",
                        "width": visible_width,
                        "height": 32,
                    },
                    "sourceRect": {"x": 32, "y": y, "width": 8, "height": 16},
                    "destination": {"x": 32, "y": y, "width": 8, "height": 16},
                    "transform": dict(IDENTITY),
                    "globalAlpha": 1,
                    "globalCompositeOperation": "source-over",
                    "filter": "none",
                },
            ]
        )
        operation += 3
    record = _completed_record(
        mapping_id=mapping_id,
        renderer_index=110,
        clear_index=101,
        tile_draws=tiles,
        source_rect={"x": 0, "y": 0, "width": visible_width, "height": 32},
        destination={"x": 0, "y": 0, "width": visible_width, "height": 32},
        segmentExpectedTileCount=len(tiles),
    )
    record["rendererTarget"] = {"canvasId": "renderer", "width": 64, "height": 32}
    record["sourceCanvas"] = {
        "canvasId": "source-canvas",
        "width": visible_width,
        "height": 32,
    }
    record["segmentClearRectangle"] = {
        "x": 0,
        "y": 0,
        "width": visible_width,
        "height": 32,
    }
    record["segmentFirstTileOperationIndex"] = 102
    record["segmentLastTileOperationIndex"] = operation - 1
    record["sourceIds"] = ["bitmap-cropped"]
    return record


def test_completed_mapping_proves_nonuniform_final_mcu_crop() -> None:
    record = _cropped_completed_record()

    result = analyze_purchased_mapping(
        {"completedMappings": [record]}, _completed_draw(record)
    )

    assert result.proven
    assert result.mapping is not None
    assert result.mapping.coded_dimensions == (40, 32)
    assert result.mapping.visible_dimensions == (36, 32)
    assert result.mapping.tile_dimensions_uniform is False
    assert result.mapping.tile_dimension_variants == ((8, 16), (16, 16))


@pytest.mark.parametrize("visible_width", [32, 41])
def test_completed_mapping_rejects_crop_outside_final_mcu(visible_width: int) -> None:
    record = _cropped_completed_record(visible_width=visible_width)

    result = analyze_purchased_mapping(
        {"completedMappings": [record]}, _completed_draw(record)
    )

    assert not result.proven


def test_completed_mapping_rejects_excessive_mcu_work_before_expansion() -> None:
    record = _completed_record()
    record["rendererTarget"] = {
        "canvasId": "renderer", "width": 8192, "height": 8192,
    }
    record["sourceCanvas"] = {
        "canvasId": "source-canvas", "width": 8192, "height": 8192,
    }
    record["rendererSourceRect"] = {
        "x": 0, "y": 0, "width": 8192, "height": 8192,
    }
    record["rendererDestination"] = {
        "x": 0, "y": 0, "width": 8192, "height": 8192,
    }
    record["segmentClearRectangle"] = {
        "x": 0, "y": 0, "width": 8192, "height": 8192,
    }
    record["segmentExpectedTileCount"] = 1
    record["tileDraws"] = [
        {
            **record["tileDraws"][0],
            "source": {
                "sourceId": "bitmap-a", "constructor": "ImageBitmap",
                "width": 8192, "height": 8192,
            },
            "target": {
                "canvasId": "source-canvas", "width": 8192, "height": 8192,
            },
            "sourceRect": {"x": 0, "y": 0, "width": 8192, "height": 8192},
            "destination": {"x": 0, "y": 0, "width": 8192, "height": 8192},
        }
    ]

    result = analyze_purchased_mapping(
        {"completedMappings": [record]}, _completed_draw(record)
    )

    assert not result.proven
    assert result.reason == "completed segment exceeds MCU work bound"


def _compact_payload(record: dict) -> dict:
    sources: list[list[object]] = []
    targets: list[list[object]] = []
    transforms: list[list[object]] = []
    composites: list[str] = []
    filters: list[str] = []
    tile_rows: list[list[object]] = []

    def table_index(table: list, value: object) -> int:
        if value not in table:
            table.append(value)
        return table.index(value)

    for tile in record["tileDraws"]:
        source = tile["source"]
        target = tile["target"]
        source_row = [
            source["constructor"],
            source["sourceId"],
            source["width"],
            source["height"],
            source.get("canvasId", source.get("sourceCanvasId")),
        ]
        target_row = [target["canvasId"], target["width"], target["height"]]
        transform = tile["transform"]
        transform_row = [transform[key] for key in ("a", "b", "c", "d", "e", "f")]
        source_index = table_index(sources, source_row)
        target_index = table_index(targets, target_row)
        transform_index = table_index(transforms, transform_row)
        composite_index = table_index(composites, tile["globalCompositeOperation"])
        filter_index = table_index(filters, tile["filter"])
        source_rect = tile["sourceRect"]
        destination = tile["destination"]
        tile_rows.append([
            tile["operationIndex"],
            source_index,
            target_index,
            source_rect["x"],
            source_rect["y"],
            source_rect["width"],
            source_rect["height"],
            destination["x"],
            destination["y"],
            destination["width"],
            destination["height"],
            transform_index,
            tile["globalAlpha"],
            composite_index,
            filter_index,
        ])

    compact = {
        key: copy.deepcopy(record[key])
        for key in (
            "mappingId",
            "rendererOperationIndex",
            "rendererTarget",
            "sourceCanvas",
            "rendererSourceRect",
            "rendererDestination",
            "rendererTransform",
            "rendererAlpha",
            "rendererComposite",
            "rendererFilter",
            "segmentClearOperationIndex",
            "segmentClearRectangle",
            "segmentFirstTileOperationIndex",
            "segmentLastTileOperationIndex",
            "segmentTileCount",
            "segmentExpectedTileCount",
            "unsafeOperationCount",
            "firstUnsafeOperationIndex",
            "unsafeOperationTypes",
            "segmentOverflow",
            "sourceIds",
            "nonImageBitmapDraws",
        )
    }
    compact.update({
        "sources": sources,
        "targets": targets,
        "transforms": transforms,
        "composites": composites,
        "filters": filters,
        "tileRows": tile_rows,
    })
    return {
        "transportVersion": 1,
        "compactMappings": [compact],
        "retainedCompletedMappingSummaries": [{
            "mappingId": record["mappingId"],
            "sourceCanvasId": record["sourceCanvas"]["canvasId"],
            "targetCanvasId": record["rendererTarget"]["canvasId"],
            "rendererOperationIndex": record["rendererOperationIndex"],
            "segmentClearOperationIndex": record["segmentClearOperationIndex"],
            "segmentFirstTileOperationIndex": record["segmentFirstTileOperationIndex"],
            "segmentLastTileOperationIndex": record["segmentLastTileOperationIndex"],
            "segmentTileCount": record["segmentTileCount"],
            "sourceImageBitmapIds": ["bitmap-a"],
            "sourceDimensions": {"width": 32, "height": 32},
            "targetDimensions": {"width": 32, "height": 32},
        }],
        "retainedCompletedMappingCount": 1,
        "retainedCompletedTileRecordCount": len(tile_rows),
        "activeSegmentCount": 0,
        "activeTileRecordCount": 0,
        "droppedCompletedMappingCount": 0,
        "droppedActiveSegmentCount": 0,
        "requestedMappingCount": 1,
        "returnedCompletedMappingCount": 1,
        "returnedTileRecordCount": len(tile_rows),
        "missingMappingCount": 0,
        "compactSourceTableCount": len(sources),
        "compactTargetTableCount": len(targets),
        "compactTransformTableCount": len(transforms),
        "compactCompositeTableCount": len(composites),
        "compactFilterTableCount": len(filters),
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
    assert result.mapping.mapping_provenance == "direct"


def test_selected_mapping_keeps_bounded_non_image_bitmap_provenance_diagnostic() -> None:
    record = _completed_record()
    record["tileDraws"] = []
    record["segmentFirstTileOperationIndex"] = None
    record["segmentLastTileOperationIndex"] = None
    record["segmentTileCount"] = 0
    record["nonImageBitmapDraws"] = [{
        "operationIndex": 105,
        "source": {
            "sourceId": "source-a",
            "constructor": "HTMLCanvasElement",
            "width": 32,
            "height": 32,
            "canvasId": "canvas-a",
        },
        "target": {"canvasId": "canvas-b", "width": 32, "height": 32},
        "sourceRect": {"x": 0, "y": 0, "width": 32, "height": 32},
        "destination": {"x": 0, "y": 0, "width": 32, "height": 32},
        "transform": dict(IDENTITY),
        "globalAlpha": 1,
        "globalCompositeOperation": "source-over",
        "filter": "none",
    }]
    result = analyze_purchased_mapping({"completedMappings": [record]}, _completed_draw(record))

    assert not result.proven
    assert result.reason == "completed segment has no tile draws"
    assert result.to_debug()["non_image_bitmap_draws"][0]["source"]["canvasId"] == "canvas-a"


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


def test_selected_completed_mapping_has_full_trace_proof_parity() -> None:
    record = _completed_record()
    unrelated = _completed_record(
        mapping_id="mapping-unrelated",
        renderer_index=207,
        clear_index=201,
    )
    full_result = analyze_purchased_mapping(
        {"completedMappings": [unrelated, record]},
        _completed_draw(record),
    )
    selected_result = analyze_purchased_mapping(
        {"completedMappings": [record]},
        _completed_draw(record),
    )

    assert full_result.mapping is not None
    assert selected_result.mapping is not None
    assert (full_result.status, full_result.reason, full_result.proven) == (
        selected_result.status,
        selected_result.reason,
        selected_result.proven,
    )
    assert full_result.to_debug() == selected_result.to_debug()
    assert {
        "mapping_id": full_result.mapping.mapping_id,
        "mapping_sha256": full_result.mapping.mapping_sha256,
        "source_dimensions": full_result.mapping.source_dimensions,
        "destination_dimensions": full_result.mapping.destination_dimensions,
        "tile_dimensions": full_result.mapping.tile_dimensions,
        "imagebitmap_source_id": full_result.mapping.imagebitmap_source_id,
        "segment_tile_count": full_result.segment_tile_count,
        "unsafe_operation_types": full_result.unsafe_operation_types,
    } == {
        "mapping_id": selected_result.mapping.mapping_id,
        "mapping_sha256": selected_result.mapping.mapping_sha256,
        "source_dimensions": selected_result.mapping.source_dimensions,
        "destination_dimensions": selected_result.mapping.destination_dimensions,
        "tile_dimensions": selected_result.mapping.tile_dimensions,
        "imagebitmap_source_id": selected_result.mapping.imagebitmap_source_id,
        "segment_tile_count": selected_result.segment_tile_count,
        "unsafe_operation_types": selected_result.unsafe_operation_types,
    }


def test_compact_decode_has_full_rich_proof_parity() -> None:
    record = _completed_record()
    rich_result = analyze_purchased_mapping(
        {"completedMappings": [record]},
        _completed_draw(record),
    )
    decoded = decode_compact_completed_mappings(_compact_payload(record))

    assert decoded is not None
    assert decoded["retainedCompletedMappingSummaries"][0]["sourceCanvasId"] == "source-canvas"
    compact_result = analyze_purchased_mapping(decoded, _completed_draw(record))
    assert (rich_result.status, rich_result.reason, rich_result.proven) == (
        compact_result.status,
        compact_result.reason,
        compact_result.proven,
    )
    assert rich_result.to_debug() == compact_result.to_debug()
    assert rich_result.mapping is not None and compact_result.mapping is not None
    assert rich_result.mapping.as_dict() == compact_result.mapping.as_dict()


def test_compact_decode_preserves_null_draw_target_for_empty_segment() -> None:
    payload = _compact_payload(_completed_record())
    payload["compactMappings"][0]["segmentDrawTarget"] = None

    decoded = decode_compact_completed_mappings(payload)

    assert decoded is not None
    assert decoded["completedMappings"][0]["segmentDrawTarget"] is None


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda payload: payload.update(transportVersion=2), id="unknown-version"),
        pytest.param(
            lambda payload: payload["compactMappings"][0]["tileRows"][0].pop(),
            id="wrong-tile-array-length",
        ),
        pytest.param(
            lambda payload: payload["compactMappings"][0].update(sources={}),
            id="non-list-table",
        ),
        pytest.param(
            lambda payload: payload["compactMappings"][0]["tileRows"][0].__setitem__(1, 99),
            id="index-out-of-range",
        ),
        pytest.param(
            lambda payload: payload["compactMappings"][0].pop("rendererTarget"),
            id="missing-metadata",
        ),
        pytest.param(
            lambda payload: payload["compactMappings"][0]["tileRows"][0].__setitem__(0, "102"),
            id="impossible-tile-type",
        ),
        pytest.param(
            lambda payload: payload["compactMappings"][0]["tileRows"][0].__setitem__(0, 10**1000),
            id="integer-overflow",
        ),
    ],
)
def test_compact_decoder_fails_closed_for_transport_shape_errors(mutate) -> None:
    payload = _compact_payload(_completed_record())
    mutate(payload)

    assert decode_compact_completed_mappings(payload) is None


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda record: record["tileDraws"][1].update(
                sourceRect=copy.deepcopy(record["tileDraws"][0]["sourceRect"])
            ),
            id="duplicate-source-tile",
        ),
        pytest.param(
            lambda record: record["tileDraws"][1].update(
                destination=copy.deepcopy(record["tileDraws"][0]["destination"])
            ),
            id="duplicate-destination-tile",
        ),
        pytest.param(
            lambda record: record["tileDraws"][0]["sourceRect"].update(x=24),
            id="missing-source-tile-and-out-of-bounds",
        ),
        pytest.param(
            lambda record: record["tileDraws"][0]["destination"].update(x=24),
            id="missing-destination-tile-and-out-of-bounds",
        ),
        pytest.param(
            lambda record: record["tileDraws"][0].update(
                transform={"a": 1, "b": 0, "c": 1, "d": 1, "e": 0, "f": 0}
            ),
            id="unsafe-transform",
        ),
        pytest.param(
            lambda record: record["tileDraws"][0].update(globalAlpha=0.5),
            id="unsafe-alpha",
        ),
        pytest.param(
            lambda record: record["tileDraws"][0].update(
                globalCompositeOperation="multiply"
            ),
            id="unsafe-composite",
        ),
        pytest.param(
            lambda record: record["tileDraws"][0].update(filter="blur(1px)"),
            id="unsafe-filter",
        ),
        pytest.param(
            lambda record: record["tileDraws"][0]["source"].update(
                constructor="HTMLImageElement"
            ),
            id="non-imagebitmap",
        ),
        pytest.param(
            lambda record: record["tileDraws"][0]["source"].update(width=16),
            id="wrong-source-dimensions",
        ),
        pytest.param(
            lambda record: record["tileDraws"][0]["target"].update(
                canvasId="other-canvas"
            ),
            id="wrong-target-canvas",
        ),
        pytest.param(
            lambda record: record["tileDraws"][1].update(
                operationIndex=record["tileDraws"][0]["operationIndex"]
            ),
            id="duplicate-operation-index",
        ),
        pytest.param(
            lambda record: record["segmentClearRectangle"].update(width=31),
            id="partial-clear",
        ),
        pytest.param(
            lambda record: record["rendererSourceRect"].update(width=31.5),
            id="crop",
        ),
    ],
)
def test_compact_decode_preserves_rejection_semantics(mutate) -> None:
    rich_record = _completed_record()
    mutate(rich_record)
    rich_result = analyze_purchased_mapping(
        {"completedMappings": [rich_record]},
        _completed_draw(rich_record),
    )
    decoded = decode_compact_completed_mappings(_compact_payload(rich_record))

    assert not rich_result.proven
    assert decoded is not None
    compact_result = analyze_purchased_mapping(decoded, _completed_draw(rich_record))
    assert not compact_result.proven
    assert compact_result.status == rich_result.status


def test_completed_mapping_counter_duplicate_counts_preserve_semantics() -> None:
    clean = _completed_record()
    clean_result = analyze_purchased_mapping(
        {"completedMappings": [clean]}, _completed_draw(clean)
    )
    assert clean_result.proven

    source_duplicate = _completed_record()
    source_duplicate["tileDraws"][1]["sourceRect"] = copy.deepcopy(
        source_duplicate["tileDraws"][0]["sourceRect"]
    )
    source_result = analyze_purchased_mapping(
        {"completedMappings": [source_duplicate]}, _completed_draw(source_duplicate)
    )
    assert source_result.to_debug()["source_duplicate_tile_count"] == 1
    assert source_result.to_debug()["destination_duplicate_tile_count"] == 0

    triple_source = _completed_record()
    triple_source["tileDraws"][1]["sourceRect"] = copy.deepcopy(
        triple_source["tileDraws"][0]["sourceRect"]
    )
    triple_source["tileDraws"][2]["sourceRect"] = copy.deepcopy(
        triple_source["tileDraws"][0]["sourceRect"]
    )
    triple_result = analyze_purchased_mapping(
        {"completedMappings": [triple_source]}, _completed_draw(triple_source)
    )
    assert triple_result.to_debug()["source_duplicate_tile_count"] == 2

    destination_duplicate = _completed_record()
    destination_duplicate["tileDraws"][1]["destination"] = copy.deepcopy(
        destination_duplicate["tileDraws"][0]["destination"]
    )
    destination_result = analyze_purchased_mapping(
        {"completedMappings": [destination_duplicate]},
        _completed_draw(destination_duplicate),
    )
    assert destination_result.to_debug()["source_duplicate_tile_count"] == 0
    assert destination_result.to_debug()["destination_duplicate_tile_count"] == 1


def test_duplicate_completed_mapping_id_fails_closed_as_ambiguous() -> None:
    first = _completed_record()
    duplicate = _completed_record(renderer_index=107, clear_index=106)

    result = analyze_purchased_mapping(
        {"completedMappings": [first, duplicate]},
        _completed_draw(first),
    )

    assert not result.proven
    assert result.status == "MAPPING_UNAVAILABLE"
    assert result.completed_mapping_evicted is True
    assert result.mapping_id == first["mappingId"]
    assert "unavailable" in result.reason


def _scaled_chain_fixture() -> tuple[dict, dict, dict, dict]:
    upstream = _completed_record(
        mapping_id="mapping-upstream",
        renderer_index=6,
        clear_index=1,
    )
    upstream["sourceCanvas"] = {
        "canvasId": "canvas-a", "width": 32, "height": 32
    }
    upstream["rendererTarget"] = {
        "canvasId": "canvas-b", "width": 16, "height": 16
    }
    upstream["rendererSourceRect"] = {
        "x": 0, "y": 0, "width": 32, "height": 32
    }
    upstream["rendererDestination"] = {
        "x": 0, "y": 0, "width": 16, "height": 16
    }
    upstream["nonImageBitmapDraws"] = []
    for tile_index, tile in enumerate(upstream["tileDraws"], start=2):
        tile["operationIndex"] = tile_index
        tile["target"] = {
            "canvasId": "canvas-a", "width": 32, "height": 32
        }
    upstream["segmentFirstTileOperationIndex"] = 2
    upstream["segmentLastTileOperationIndex"] = 5

    downstream = _completed_record(
        mapping_id="mapping-downstream",
        renderer_index=8,
        clear_index=5,
    )
    downstream["sourceCanvas"] = {
        "canvasId": "canvas-b", "width": 16, "height": 16
    }
    downstream["rendererTarget"] = {
        "canvasId": "canvas-renderer", "width": 16, "height": 16
    }
    downstream["rendererSourceRect"] = {
        "x": 0, "y": 0, "width": 16, "height": 16
    }
    downstream["rendererDestination"] = {
        "x": 0, "y": 0, "width": 16, "height": 16
    }
    downstream["segmentClearRectangle"] = {
        "x": 0, "y": 0, "width": 16, "height": 16
    }
    downstream["segmentFirstTileOperationIndex"] = None
    downstream["segmentLastTileOperationIndex"] = None
    downstream["tileDraws"] = []
    downstream["segmentTileCount"] = 0
    downstream["segmentExpectedTileCount"] = None
    downstream["unsafeOperationCount"] = 1
    downstream["unsafeOperationTypes"] = ["non_image_bitmap_draw"]
    downstream["nonImageBitmapDraws"] = [{
        "operationIndex": 6,
        "source": {
            "sourceId": "canvas-a-object",
            "constructor": "HTMLCanvasElement",
            "canvasId": "canvas-a",
            "width": 32,
            "height": 32,
        },
        "target": {
            "canvasId": "canvas-b", "width": 16, "height": 16
        },
        "sourceRect": {"x": 0, "y": 0, "width": 32, "height": 32},
        "destination": {"x": 0, "y": 0, "width": 16, "height": 16},
        "transform": dict(IDENTITY),
        "globalAlpha": 1,
        "globalCompositeOperation": "source-over",
        "filter": "none",
        "imageSmoothingEnabled": True,
        "imageSmoothingQuality": "high",
    }]
    upstream_summary = {
        "mappingId": "mapping-upstream",
        "sourceCanvasId": "canvas-a",
        "targetCanvasId": "canvas-b",
        "rendererOperationIndex": 6,
        "segmentClearOperationIndex": 1,
        "segmentFirstTileOperationIndex": 2,
        "segmentLastTileOperationIndex": 5,
        "segmentTileCount": 4,
        "sourceImageBitmapIds": ["bitmap-a"],
        "sourceDimensions": {"width": 32, "height": 32},
        "targetDimensions": {"width": 16, "height": 16},
    }
    downstream_draw = {
        "mappingId": "mapping-downstream",
        "traceOperationIndex": 8,
        "canvasId": "canvas-renderer",
        "sourceCanvasId": "canvas-b",
        "source": {"constructor": "HTMLCanvasElement", "canvasId": "canvas-b", "width": 16, "height": 16},
        "sourceRect": {"x": 0, "y": 0, "width": 16, "height": 16},
        "destination": {"x": 0, "y": 0, "width": 16, "height": 16},
        "canvasWidth": 16,
        "canvasHeight": 16,
    }
    return upstream, downstream, upstream_summary, downstream_draw


def _cropped_scaled_chain_fixture() -> tuple[dict, dict, dict, dict]:
    upstream = _completed_record(mapping_id="mapping-cropped", renderer_index=8, clear_index=1)
    upstream["sourceCanvas"] = {"canvasId": "canvas-a", "width": 17, "height": 16, "resetEpoch": 1}
    upstream["rendererTarget"] = {"canvasId": "canvas-b", "width": 8, "height": 8}
    upstream["rendererSourceRect"] = {"x": 0, "y": 0, "width": 17, "height": 16}
    upstream["rendererDestination"] = {"x": 0, "y": 0, "width": 8, "height": 8}
    upstream["segmentClearRectangle"] = {"x": 0, "y": 0, "width": 17, "height": 16}
    upstream["segmentClearTarget"] = {"canvasId": "canvas-a", "width": 17, "height": 16, "resetEpoch": 1}
    upstream["segmentDrawTarget"] = {"canvasId": "canvas-a", "width": 17, "height": 16, "resetEpoch": 1}
    upstream["segmentResetKind"] = "canvas_dimension_reset"
    upstream["segmentResetEpoch"] = 1
    upstream["segmentResetObservationAvailable"] = True
    upstream["segmentMutationObserverAvailable"] = True
    upstream["segmentMutationObserverTakeRecordsAvailable"] = True
    upstream["segmentUnknownMutation"] = False
    tile_positions = [(0, 0), (8, 0), (16, 0), (0, 8), (8, 8), (16, 8)]
    upstream["tileDraws"] = [
        {
            "operationIndex": index,
            "source": {"sourceId": "bitmap-a", "constructor": "ImageBitmap", "width": 24, "height": 16},
            "target": {"canvasId": "canvas-a", "width": 17, "height": 16, "resetEpoch": 1},
            "sourceRect": {"x": x, "y": y, "width": 8, "height": 8},
            "destination": {"x": x, "y": y, "width": 8, "height": 8},
            "transform": dict(IDENTITY), "globalAlpha": 1,
            "globalCompositeOperation": "source-over", "filter": "none",
        }
        for index, (x, y) in enumerate(tile_positions, start=2)
    ]
    upstream["segmentFirstTileOperationIndex"] = 2
    upstream["segmentLastTileOperationIndex"] = 7
    upstream["segmentTileCount"] = 6
    upstream["segmentExpectedTileCount"] = 6
    downstream = _completed_record(mapping_id="mapping-downstream-cropped", renderer_index=10, clear_index=7)
    downstream["sourceCanvas"] = {"canvasId": "canvas-b", "width": 8, "height": 8, "resetEpoch": 2}
    downstream["rendererTarget"] = {"canvasId": "canvas-renderer", "width": 8, "height": 8}
    downstream["rendererSourceRect"] = {"x": 0, "y": 0, "width": 8, "height": 8}
    downstream["rendererDestination"] = {"x": 0, "y": 0, "width": 8, "height": 8}
    downstream["segmentClearRectangle"] = {"x": 0, "y": 0, "width": 8, "height": 8}
    downstream["segmentClearTarget"] = {"canvasId": "canvas-b", "width": 8, "height": 8, "resetEpoch": 2}
    downstream["segmentDrawTarget"] = {"canvasId": "canvas-b", "width": 8, "height": 8, "resetEpoch": 2}
    downstream["segmentResetKind"] = "canvas_dimension_reset"
    downstream["segmentResetEpoch"] = 2
    downstream["segmentResetObservationAvailable"] = True
    downstream["segmentMutationObserverAvailable"] = True
    downstream["segmentMutationObserverTakeRecordsAvailable"] = True
    downstream["segmentUnknownMutation"] = False
    downstream["segmentFirstTileOperationIndex"] = None
    downstream["segmentLastTileOperationIndex"] = None
    downstream["tileDraws"] = []
    downstream["segmentTileCount"] = 0
    downstream["segmentExpectedTileCount"] = None
    downstream["unsafeOperationCount"] = 1
    downstream["unsafeOperationTypes"] = ["non_image_bitmap_draw"]
    downstream["nonImageBitmapDraws"] = [{
        "operationIndex": 8,
        "source": {"sourceId": "canvas-a-object", "constructor": "HTMLCanvasElement", "canvasId": "canvas-a", "width": 17, "height": 16, "resetEpoch": 1},
        "target": {"canvasId": "canvas-b", "width": 8, "height": 8, "resetEpoch": 2},
        "sourceRect": {"x": 0, "y": 0, "width": 17, "height": 16},
        "destination": {"x": 0, "y": 0, "width": 8, "height": 8},
        "transform": dict(IDENTITY), "globalAlpha": 1,
        "globalCompositeOperation": "source-over", "filter": "none",
        "imageSmoothingEnabled": True, "imageSmoothingQuality": "high",
    }]
    summary = {
        "mappingId": "mapping-cropped", "sourceCanvasId": "canvas-a", "targetCanvasId": "canvas-b",
        "rendererOperationIndex": 8, "segmentClearOperationIndex": 1,
        "segmentFirstTileOperationIndex": 2, "segmentLastTileOperationIndex": 7,
        "segmentTileCount": 6, "sourceImageBitmapIds": ["bitmap-a"],
        "sourceDimensions": {"width": 17, "height": 16}, "targetDimensions": {"width": 8, "height": 8},
        "sourceResetEpoch": 1, "targetResetEpoch": 2,
        "clearTarget": {"canvasId": "canvas-a", "width": 17, "height": 16, "resetEpoch": 1},
        "resetKind": "canvas_dimension_reset", "resetEpoch": 1,
        "drawTarget": {"canvasId": "canvas-a", "width": 17, "height": 16, "resetEpoch": 1}, "unknownMutation": False,
        "resetObservationAvailable": True,
        "mutationObserverAvailable": True,
        "mutationObserverTakeRecordsAvailable": True,
    }
    draw = {"mappingId": "mapping-downstream-cropped", "traceOperationIndex": 10,
            "canvasId": "canvas-renderer", "sourceCanvasId": "canvas-b",
            "source": {"constructor": "HTMLCanvasElement", "canvasId": "canvas-b",
                       "width": 8, "height": 8, "resetEpoch": 2},
            "sourceRect": {"x": 0, "y": 0, "width": 8, "height": 8},
            "destination": {"x": 0, "y": 0, "width": 8, "height": 8},
            "canvasWidth": 8, "canvasHeight": 8}
    return upstream, downstream, summary, draw


def test_scaled_canvas_source_accepts_only_observed_cropped_one_hop() -> None:
    upstream, downstream, summary, downstream_draw = _cropped_scaled_chain_fixture()
    downstream_analysis = analyze_purchased_mapping({"completedMappings": [downstream]}, downstream_draw)
    candidate = resolve_scaled_canvas_source_candidate(downstream_analysis, downstream_draw, [summary])
    assert candidate is not None
    upstream_analysis = analyze_purchased_mapping({"completedMappings": [upstream]}, candidate.upstream_renderer_draw())
    assert upstream_analysis.proven
    assert upstream_analysis.mapping is not None
    assert upstream_analysis.mapping.coded_dimensions == (24, 16)
    assert upstream_analysis.mapping.visible_dimensions == (17, 16)
    assert validate_scaled_canvas_source_analysis(upstream_analysis, candidate)
    assert not validate_scaled_canvas_source_analysis(
        upstream_analysis,
        replace(candidate, selected_source_canvas_generation=3),
    )
    missing_observer = copy.deepcopy(upstream)
    missing_observer["segmentMutationObserverAvailable"] = False
    missing_observer_result = analyze_purchased_mapping(
        {"completedMappings": [missing_observer]}, candidate.upstream_renderer_draw()
    )
    assert missing_observer_result.proven
    assert missing_observer_result.mapping is not None
    assert not validate_scaled_canvas_source_analysis(
        missing_observer_result, candidate
    )
    left_offset_draw = copy.deepcopy(downstream_draw)
    left_offset_draw["sourceRect"]["x"] = 1
    assert resolve_scaled_canvas_source_candidate(
        downstream_analysis, left_offset_draw, [summary]
    ) is None
    large_crop_draw = copy.deepcopy(downstream_draw)
    large_crop_draw["sourceRect"]["width"] = 6
    assert resolve_scaled_canvas_source_candidate(
        downstream_analysis, large_crop_draw, [summary]
    ) is None

    old_clear = copy.deepcopy(upstream)
    old_clear["segmentClearTarget"] = {"canvasId": "canvas-a", "width": 24, "height": 16, "resetEpoch": 1}
    old_clear["segmentClearRectangle"] = {"x": 0, "y": 0, "width": 24, "height": 16}
    old_clear_result = analyze_purchased_mapping({"completedMappings": [old_clear]}, candidate.upstream_renderer_draw())
    assert not old_clear_result.proven

    missing_reset = copy.deepcopy(upstream)
    missing_reset.pop("segmentResetKind")
    missing_reset.pop("segmentResetEpoch")
    missing_reset.pop("segmentClearTarget")
    missing_reset.pop("segmentDrawTarget")
    missing_reset.pop("segmentUnknownMutation")
    missing = analyze_purchased_mapping({"completedMappings": [missing_reset]}, candidate.upstream_renderer_draw())
    assert missing.proven
    assert not validate_scaled_canvas_source_analysis(missing, candidate)

    unknown = copy.deepcopy(upstream)
    unknown["segmentUnknownMutation"] = True
    unknown_result = analyze_purchased_mapping({"completedMappings": [unknown]}, candidate.upstream_renderer_draw())
    assert not unknown_result.proven


@pytest.mark.parametrize(
    "field, value",
    [
        pytest.param("segmentUnknownMutation", True, id="target-unknown-mutation"),
        pytest.param("segmentResetObservationAvailable", False, id="target-reset-observation"),
        pytest.param("segmentMutationObserverAvailable", False, id="target-observer"),
        pytest.param(
            "segmentMutationObserverTakeRecordsAvailable",
            False,
            id="target-take-records",
        ),
    ],
)
def test_cropped_one_hop_rejects_unproven_downstream_target(
    field: str,
    value: object,
) -> None:
    _upstream, downstream, summary, downstream_draw = _cropped_scaled_chain_fixture()
    downstream[field] = value
    downstream_analysis = analyze_purchased_mapping(
        {"completedMappings": [downstream]}, downstream_draw
    )
    assert not downstream_analysis.proven
    candidate = resolve_scaled_canvas_source_candidate(
        downstream_analysis, downstream_draw, [summary]
    )
    assert candidate is not None
    upstream, _valid_downstream, _summary, _draw = _cropped_scaled_chain_fixture()
    upstream_analysis = analyze_purchased_mapping(
        {"completedMappings": [upstream]}, candidate.upstream_renderer_draw()
    )
    assert not validate_scaled_canvas_source_analysis(upstream_analysis, candidate)


def test_scaled_canvas_source_resolves_exact_one_hop_and_reuses_upstream_proof() -> None:
    upstream, downstream, summary, downstream_draw = _scaled_chain_fixture()
    downstream_analysis = analyze_purchased_mapping(
        {"completedMappings": [downstream]}, downstream_draw
    )
    assert not downstream_analysis.proven
    assert downstream_analysis.segment_tile_count == 0

    candidate = resolve_scaled_canvas_source_candidate(
        downstream_analysis, downstream_draw, [summary]
    )
    assert candidate is not None
    assert candidate.upstream_mapping_id == "mapping-upstream"
    assert candidate.source_dimensions == (32, 32)
    assert candidate.target_dimensions == (16, 16)
    upstream_analysis = analyze_purchased_mapping(
        {"completedMappings": [upstream]}, candidate.upstream_renderer_draw()
    )
    assert upstream_analysis.proven
    assert validate_scaled_canvas_source_analysis(upstream_analysis, candidate)
    assert upstream_analysis.mapping is not None
    assert upstream_analysis.mapping.source_dimensions == (32, 32)
    assert upstream_analysis.mapping.destination_dimensions == (32, 32)


def test_legacy_equal_size_one_hop_allows_clear_rect_b_without_reset_observer() -> None:
    _upstream, downstream, summary, downstream_draw = _scaled_chain_fixture()
    downstream["segmentResetKind"] = "clearRect"
    downstream["segmentResetObservationAvailable"] = False
    downstream["segmentMutationObserverAvailable"] = False
    downstream["segmentMutationObserverTakeRecordsAvailable"] = False
    downstream["segmentUnknownMutation"] = False
    downstream["segmentResetEpoch"] = 2
    downstream["segmentClearTarget"] = {
        "canvasId": "canvas-b", "width": 16, "height": 16, "resetEpoch": 2,
    }
    downstream["segmentDrawTarget"] = {
        "canvasId": "canvas-b", "width": 16, "height": 16, "resetEpoch": 2,
    }
    downstream_analysis = analyze_purchased_mapping(
        {"completedMappings": [downstream]}, downstream_draw
    )
    candidate = resolve_scaled_canvas_source_candidate(
        downstream_analysis, downstream_draw, [summary]
    )
    assert candidate is not None


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda record: record["nonImageBitmapDraws"].clear(), id="zero-draws"),
        pytest.param(
            lambda record: record["nonImageBitmapDraws"].append(
                copy.deepcopy(record["nonImageBitmapDraws"][0])
            ),
            id="ambiguous-draws",
        ),
        pytest.param(
            lambda record: record["nonImageBitmapDraws"][0]["source"].update(
                constructor="ImageBitmap"
            ),
            id="wrong-source-constructor",
        ),
        pytest.param(
            lambda record: record["nonImageBitmapDraws"][0]["target"].update(
                canvasId="wrong-target"
            ),
            id="wrong-target-identity",
        ),
        pytest.param(
            lambda record: record["nonImageBitmapDraws"][0]["sourceRect"].update(
                width=31
            ),
            id="partial-source",
        ),
        pytest.param(
            lambda record: record["nonImageBitmapDraws"][0]["destination"].update(
                x=1
            ),
            id="destination-offset",
        ),
        pytest.param(
            lambda record: record["nonImageBitmapDraws"][0].update(
                transform={"a": 2, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0}
            ),
            id="non-identity-transform",
        ),
        pytest.param(
            lambda record: record["nonImageBitmapDraws"][0].update(globalAlpha=0.5),
            id="alpha",
        ),
        pytest.param(
            lambda record: record["nonImageBitmapDraws"][0].update(
                globalCompositeOperation="multiply"
            ),
            id="composite",
        ),
        pytest.param(
            lambda record: record["nonImageBitmapDraws"][0].update(filter="blur(1px)"),
            id="filter",
        ),
        pytest.param(
            lambda record: record["unsafeOperationTypes"].append("other"),
            id="unsafe-types",
        ),
    ],
)
def test_scaled_canvas_source_rejects_unsafe_wrapper_metadata(mutate) -> None:
    _upstream, downstream, summary, downstream_draw = _scaled_chain_fixture()
    mutate(downstream)
    analysis = analyze_purchased_mapping(
        {"completedMappings": [downstream]}, downstream_draw
    )
    assert resolve_scaled_canvas_source_candidate(analysis, downstream_draw, [summary]) is None


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda summary: summary.update(rendererOperationIndex=7), id="wrong-operation"),
        pytest.param(lambda summary: summary.update(sourceCanvasId="other"), id="wrong-source-id"),
        pytest.param(lambda summary: summary.update(targetCanvasId="other"), id="wrong-target-id"),
        pytest.param(lambda summary: summary.update(segmentTileCount=0), id="zero-tiles"),
        pytest.param(lambda summary: summary.update(segmentFirstTileOperationIndex=6), id="ordering"),
    ],
)
def test_scaled_canvas_source_requires_exact_unique_summary(mutate) -> None:
    _upstream, downstream, summary, downstream_draw = _scaled_chain_fixture()
    mutate(summary)
    analysis = analyze_purchased_mapping(
        {"completedMappings": [downstream]}, downstream_draw
    )
    assert resolve_scaled_canvas_source_candidate(analysis, downstream_draw, [summary]) is None


def test_scaled_canvas_source_rejects_zero_or_ambiguous_summary_matches() -> None:
    _upstream, downstream, summary, downstream_draw = _scaled_chain_fixture()
    analysis = analyze_purchased_mapping(
        {"completedMappings": [downstream]}, downstream_draw
    )
    assert resolve_scaled_canvas_source_candidate(analysis, downstream_draw, []) is None
    assert resolve_scaled_canvas_source_candidate(
        analysis, downstream_draw, [summary, copy.deepcopy(summary)]
    ) is None


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
