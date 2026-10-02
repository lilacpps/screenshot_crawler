"""Conservative BookWalker purchased-viewer tile mapping helpers.

The purchased viewer observed in the probes draws a scrambled JPEG into an
intermediate ``HTMLCanvasElement`` and then copies that canvas to the visible
renderer.  This module only reasons about the recorded draw trace.  It never
decodes pixels and it deliberately returns an unavailable result for any
ambiguous or incomplete trace.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# Kept for the legacy operations-array compatibility path used by old probes
# and unit fixtures. Production authority is the bounded completed-mapping
# store, which has no global operation-list limit.
TRACE_OPERATION_LIMIT = 5_000
MAX_TILE_DRAW_RECORDS = 16_384
MAX_COMPLETED_MAPPINGS = 12
MAX_COMPLETED_TILE_RECORDS = 20_000
MAPPING_PROVEN = "MAPPING_PROVEN"
MAPPING_UNAVAILABLE = "MAPPING_UNAVAILABLE"

DIRECT_RENDERER_DRAW = "DIRECT_RENDERER_DRAW"
PURE_RENDERER_SCALE = "PURE_RENDERER_SCALE"
CROP_OR_PIXEL_PROCESSING = "CROP_OR_PIXEL_PROCESSING"
GEOMETRY_UNAVAILABLE = "GEOMETRY_UNAVAILABLE"

COMPACT_COMPLETED_MAPPING_TRANSPORT_VERSION = 1
_COMPACT_TILE_FIELD_COUNT = 15
_COMPACT_SUMMARY_FIELDS = (
    "retainedCompletedMappingCount",
    "retainedCompletedTileRecordCount",
    "activeSegmentCount",
    "activeTileRecordCount",
    "droppedCompletedMappingCount",
    "droppedActiveSegmentCount",
    "requestedMappingCount",
    "returnedCompletedMappingCount",
    "returnedTileRecordCount",
    "missingMappingCount",
    "compactSourceTableCount",
    "compactTargetTableCount",
    "compactTransformTableCount",
    "compactCompositeTableCount",
    "compactFilterTableCount",
)

_IDENTITY_TRANSFORM = {"a": 1, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0}


@dataclass(frozen=True, slots=True)
class PurchasedMapping:
    """A proven one-to-one source/destination tile permutation."""

    mapping: tuple[dict[str, int], ...]
    source_dimensions: tuple[int, int]
    destination_dimensions: tuple[int, int]
    tile_dimensions: tuple[int, int]
    mcu_dimensions: tuple[int, int] = (8, 8)
    renderer_canvas_id: str | None = None
    source_canvas_id: str | None = None
    imagebitmap_source_id: str | None = None
    renderer_draw_operation_index: int | None = None
    first_operation_index: int | None = None
    last_operation_index: int | None = None
    clear_boundary_operation_index: int | None = None
    mapping_sha256: str = ""
    mapping_id: str | None = None
    renderer_geometry_classification: str = GEOMETRY_UNAVAILABLE
    renderer_source_rect: dict[str, float] | None = None
    renderer_destination: dict[str, float] | None = None
    renderer_target_dimensions: tuple[int, int] | None = None
    segment_tile_count: int = 0
    segment_expected_tile_count: int | None = None
    segment_overflow: bool = False
    unsafe_operation_count: int = 0
    first_unsafe_operation_index: int | None = None
    unsafe_operation_types: tuple[str, ...] = ()
    mapping_provenance: str = "direct"

    def as_dict(self) -> dict[str, Any]:
        """Return the small JSON-compatible contract used by diagnostics."""

        return {
            "mapping": [dict(item) for item in self.mapping],
            "source_dimensions": {
                "width": self.source_dimensions[0],
                "height": self.source_dimensions[1],
            },
            "target_dimensions": {
                "width": self.destination_dimensions[0],
                "height": self.destination_dimensions[1],
            },
            "tile_dimensions": {
                "width": self.tile_dimensions[0],
                "height": self.tile_dimensions[1],
            },
            "mcu_dimensions": {
                "width": self.mcu_dimensions[0],
                "height": self.mcu_dimensions[1],
            },
            "renderer_canvas_id": self.renderer_canvas_id,
            "source_canvas_id": self.source_canvas_id,
            "imagebitmap_source_id": self.imagebitmap_source_id,
            "renderer_draw_operation_index": self.renderer_draw_operation_index,
            "first_operation_index": self.first_operation_index,
            "last_operation_index": self.last_operation_index,
            "clear_boundary_operation_index": self.clear_boundary_operation_index,
            "mapping_sha256": self.mapping_sha256,
            "mapping_id": self.mapping_id,
            "renderer_geometry_classification": self.renderer_geometry_classification,
            "renderer_source_rect": self.renderer_source_rect,
            "renderer_destination": self.renderer_destination,
            "renderer_target_dimensions": self.renderer_target_dimensions,
            "segment_tile_count": self.segment_tile_count,
            "segment_expected_tile_count": self.segment_expected_tile_count,
            "segment_overflow": self.segment_overflow,
            "unsafe_operation_count": self.unsafe_operation_count,
            "first_unsafe_operation_index": self.first_unsafe_operation_index,
            "unsafe_operation_types": list(self.unsafe_operation_types),
            "mapping_provenance": self.mapping_provenance,
            "complete_bijection": True,
        }


@dataclass(frozen=True, slots=True)
class MappingAnalysis:
    """Bounded mapping decision, including a reason for fail-safe fallback."""

    status: str
    reason: str
    mapping: PurchasedMapping | None = None
    source_duplicate_tile_count: int = 0
    destination_duplicate_tile_count: int = 0
    source_tile_gap_count: int = 0
    destination_tile_gap_count: int = 0
    source_out_of_bounds_count: int = 0
    destination_out_of_bounds_count: int = 0
    trace_overflow: bool = False
    additional_pixel_processing: bool = False
    mapping_source: str | None = None
    mapping_id: str | None = None
    segment_clear_operation_index: int | None = None
    segment_first_tile_operation_index: int | None = None
    segment_last_tile_operation_index: int | None = None
    segment_tile_count: int = 0
    segment_expected_tile_count: int | None = None
    segment_overflow: bool = False
    completed_mapping_evicted: bool = False
    renderer_geometry_classification: str = GEOMETRY_UNAVAILABLE
    unsafe_operation_count: int = 0
    first_unsafe_operation_index: int | None = None
    unsafe_operation_types: tuple[str, ...] = ()
    mapping_provenance: str | None = None
    non_image_bitmap_draws: tuple[dict[str, Any], ...] = ()
    renderer_canvas_id: str | None = None
    source_canvas_id: str | None = None

    @property
    def proven(self) -> bool:
        return self.status == MAPPING_PROVEN and self.mapping is not None

    def to_debug(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": self.status,
            "reason": self.reason,
            "mapping_proven": self.proven,
            "source_duplicate_tile_count": self.source_duplicate_tile_count,
            "destination_duplicate_tile_count": self.destination_duplicate_tile_count,
            "source_tile_gap_count": self.source_tile_gap_count,
            "destination_tile_gap_count": self.destination_tile_gap_count,
            "source_out_of_bounds_count": self.source_out_of_bounds_count,
            "destination_out_of_bounds_count": self.destination_out_of_bounds_count,
            "trace_overflow": self.trace_overflow,
            "additional_pixel_processing": self.additional_pixel_processing,
            "mapping_source": self.mapping_source,
            "mapping_id": self.mapping_id,
            "segment_clear_operation_index": self.segment_clear_operation_index,
            "segment_first_tile_operation_index": self.segment_first_tile_operation_index,
            "segment_last_tile_operation_index": self.segment_last_tile_operation_index,
            "segment_tile_count": self.segment_tile_count,
            "segment_expected_tile_count": self.segment_expected_tile_count,
            "segment_overflow": self.segment_overflow,
            "completed_mapping_evicted": self.completed_mapping_evicted,
            "renderer_geometry_classification": self.renderer_geometry_classification,
            "unsafe_operation_count": self.unsafe_operation_count,
            "first_unsafe_operation_index": self.first_unsafe_operation_index,
            "unsafe_operation_types": list(self.unsafe_operation_types),
            "mapping_provenance": self.mapping_provenance,
            "non_image_bitmap_draws": [
                json.loads(json.dumps(item)) for item in self.non_image_bitmap_draws
            ],
            "renderer_canvas_id": self.renderer_canvas_id,
            "source_canvas_id": self.source_canvas_id,
        }
        if self.mapping is not None:
            result.update({
                "mapping_sha256": self.mapping.mapping_sha256,
                "tile_dimensions": {
                    "width": self.mapping.tile_dimensions[0],
                    "height": self.mapping.tile_dimensions[1],
                },
                "mcu_dimensions": {
                    "width": self.mapping.mcu_dimensions[0],
                    "height": self.mapping.mcu_dimensions[1],
                },
                "source_canvas_id": self.mapping.source_canvas_id,
                "imagebitmap_source_id": self.mapping.imagebitmap_source_id,
                "renderer_canvas_id": self.mapping.renderer_canvas_id,
                "mapping_id": self.mapping.mapping_id,
            })
        return result


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


def mapping_sha256(mapping: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> str:
    """Hash the canonical mapping without retaining trace data."""

    canonical = json.dumps(
        _canonical_mapping(list(mapping)),
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _number(value: object) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite trace number")
    return number


def _integer(value: object) -> int:
    number = _number(value)
    if number != round(number):
        raise ValueError("non-integer trace geometry")
    return int(number)


def _rect(value: object) -> tuple[int, int, int, int] | None:
    if not isinstance(value, Mapping):
        return None
    try:
        return (
            _integer(value["x"]),
            _integer(value["y"]),
            _integer(value["width"]),
            _integer(value["height"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _numeric_rect(value: object) -> tuple[float, float, float, float] | None:
    if not isinstance(value, Mapping):
        return None
    try:
        return tuple(_number(value[key]) for key in ("x", "y", "width", "height"))  # type: ignore[return-value]
    except (KeyError, TypeError, ValueError):
        return None


def _compact_number(value: object) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("compact number has an impossible type")
    try:
        finite = math.isfinite(float(value))
    except (OverflowError, ValueError) as error:
        raise ValueError("compact number is not finite") from error
    if not finite:
        raise ValueError("compact number is not finite")
    return value


def _compact_integer(value: object) -> int:
    number = _compact_number(value)
    if number != round(float(number)):
        raise ValueError("compact integer is not integral")
    return int(number)


def _compact_required(mapping: Mapping[str, Any], key: str) -> Any:
    if key not in mapping:
        raise ValueError(f"compact field is missing: {key}")
    return mapping[key]


def _compact_rectangle(value: object) -> dict[str, int | float]:
    if not isinstance(value, Mapping):
        raise TypeError("compact rectangle is not an object")
    return {
        key: _compact_number(_compact_required(value, key))
        for key in ("x", "y", "width", "height")
    }


def _compact_transform(value: object) -> dict[str, int | float]:
    if not isinstance(value, Mapping):
        raise TypeError("compact transform is not an object")
    return {
        key: _compact_number(_compact_required(value, key))
        for key in ("a", "b", "c", "d", "e", "f")
    }


def _compact_canvas(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("compact canvas metadata is not an object")
    canvas_id = _compact_required(value, "canvasId")
    width = _compact_number(_compact_required(value, "width"))
    height = _compact_number(_compact_required(value, "height"))
    if not isinstance(canvas_id, str):
        raise TypeError("compact canvas id has an impossible type")
    result: dict[str, Any] = {
        "canvasId": canvas_id,
        "width": width,
        "height": height,
    }
    if "constructor" in value:
        constructor = value["constructor"]
        if not isinstance(constructor, str):
            raise ValueError("compact canvas constructor has an impossible type")
        result["constructor"] = constructor
    return result


def _decode_compact_sources(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise TypeError("compact sources table is not a list")
    sources: list[dict[str, Any]] = []
    for row in value:
        if not isinstance(row, list) or len(row) != 5:
            raise ValueError("compact source table row has the wrong length")
        constructor, source_id, width, height, canvas_id = row
        if not isinstance(constructor, str) or not isinstance(source_id, str):
            raise TypeError("compact source table string has an impossible type")
        width = _compact_number(width)
        height = _compact_number(height)
        if canvas_id is not None and not isinstance(canvas_id, str):
            raise ValueError("compact source canvas id has an impossible type")
        source: dict[str, Any] = {
            "sourceId": source_id,
            "constructor": constructor,
            "width": width,
            "height": height,
        }
        if canvas_id is not None:
            source["canvasId"] = canvas_id
            source["sourceCanvasId"] = canvas_id
        sources.append(source)
    return sources


def _decode_compact_targets(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise TypeError("compact targets table is not a list")
    targets: list[dict[str, Any]] = []
    for row in value:
        if not isinstance(row, list) or len(row) != 3:
            raise ValueError("compact target table row has the wrong length")
        canvas_id, width, height = row
        if not isinstance(canvas_id, str):
            raise TypeError("compact target canvas id has an impossible type")
        targets.append({
            "canvasId": canvas_id,
            "width": _compact_number(width),
            "height": _compact_number(height),
        })
    return targets


def _decode_compact_transforms(value: object) -> list[dict[str, int | float]]:
    if not isinstance(value, list):
        raise TypeError("compact transforms table is not a list")
    transforms: list[dict[str, int | float]] = []
    for row in value:
        if not isinstance(row, list) or len(row) != 6:
            raise ValueError("compact transform table row has the wrong length")
        transforms.append({
            key: _compact_number(number)
            for key, number in zip(("a", "b", "c", "d", "e", "f"), row, strict=True)
        })
    return transforms


def _decode_compact_strings(value: object, name: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"compact {name} table is invalid")
    return list(value)


def _compact_table_item(table: list[Any], index: object, name: str) -> Any:
    index = _compact_integer(index)
    if index < 0 or index >= len(table):
        raise ValueError(f"compact {name} index is out of range")
    return table[index]


def _decode_compact_tiles(
    mapping: Mapping[str, Any],
    sources: list[dict[str, Any]],
    targets: list[dict[str, Any]],
    transforms: list[dict[str, int | float]],
    composites: list[str],
    filters: list[str],
) -> list[dict[str, Any]]:
    value = _compact_required(mapping, "tileRows")
    if not isinstance(value, list):
        raise TypeError("compact tile rows are not a list")
    tiles: list[dict[str, Any]] = []
    for row in value:
        if not isinstance(row, list) or len(row) != _COMPACT_TILE_FIELD_COUNT:
            raise ValueError("compact tile row has the wrong length")
        (
            operation_index,
            source_index,
            target_index,
            source_x,
            source_y,
            source_width,
            source_height,
            destination_x,
            destination_y,
            destination_width,
            destination_height,
            transform_index,
            global_alpha,
            composite_index,
            filter_index,
        ) = row
        source = _compact_table_item(sources, source_index, "source")
        target = _compact_table_item(targets, target_index, "target")
        transform = _compact_table_item(transforms, transform_index, "transform")
        composite = _compact_table_item(composites, composite_index, "composite")
        filter_value = _compact_table_item(filters, filter_index, "filter")
        tiles.append({
            "operationIndex": _compact_integer(operation_index),
            "source": dict(source),
            "target": dict(target),
            "sourceRect": {
                "x": _compact_number(source_x),
                "y": _compact_number(source_y),
                "width": _compact_number(source_width),
                "height": _compact_number(source_height),
            },
            "destination": {
                "x": _compact_number(destination_x),
                "y": _compact_number(destination_y),
                "width": _compact_number(destination_width),
                "height": _compact_number(destination_height),
            },
            "transform": dict(transform),
            "globalAlpha": _compact_number(global_alpha),
            "globalCompositeOperation": composite,
            "filter": filter_value,
        })
    return tiles


def _decode_compact_non_image_bitmap_draws(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise TypeError("compact non-ImageBitmap draws are not a list")
    draws: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise TypeError("compact non-ImageBitmap draw is not an object")
        operation_index = _compact_integer(_compact_required(item, "operationIndex"))
        source_value = _compact_required(item, "source")
        if not isinstance(source_value, Mapping):
            raise TypeError("compact provenance source is not an object")
        constructor = _compact_required(source_value, "constructor")
        source_id = _compact_required(source_value, "sourceId")
        if not isinstance(constructor, str) or not isinstance(source_id, str):
            raise TypeError("compact provenance source identity has an impossible type")
        source: dict[str, Any] = {
            "constructor": constructor,
            "sourceId": source_id,
            "width": _compact_number(_compact_required(source_value, "width")),
            "height": _compact_number(_compact_required(source_value, "height")),
        }
        canvas_id = source_value.get("canvasId", source_value.get("sourceCanvasId"))
        if canvas_id is not None and not isinstance(canvas_id, str):
            raise TypeError("compact provenance source canvas id has an impossible type")
        if canvas_id is not None:
            source["canvasId"] = canvas_id
            source["sourceCanvasId"] = canvas_id
        draws.append({
            "operationIndex": operation_index,
            "source": source,
            "target": _compact_canvas(_compact_required(item, "target")),
            "sourceRect": _compact_rectangle(_compact_required(item, "sourceRect")),
            "destination": _compact_rectangle(_compact_required(item, "destination")),
            "transform": _compact_transform(_compact_required(item, "transform")),
            "globalAlpha": _compact_number(_compact_required(item, "globalAlpha")),
            "globalCompositeOperation": _compact_required(item, "globalCompositeOperation"),
            "filter": _compact_required(item, "filter"),
        })
        if not isinstance(draws[-1]["globalCompositeOperation"], str):
            raise TypeError("compact provenance composite has an impossible type")
        if not isinstance(draws[-1]["filter"], str):
            raise TypeError("compact provenance filter has an impossible type")
    return draws


def _decode_compact_mapping_summaries(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise TypeError("compact mapping summaries are not a list")
    summaries: list[dict[str, Any]] = []
    nullable_fields = {
        "segmentFirstTileOperationIndex",
        "segmentLastTileOperationIndex",
    }
    for item in value:
        if not isinstance(item, Mapping):
            raise TypeError("compact mapping summary is not an object")
        result: dict[str, Any] = {}
        for key in (
            "mappingId",
            "sourceCanvasId",
            "targetCanvasId",
        ):
            field = _compact_required(item, key)
            if not isinstance(field, str):
                raise TypeError("compact mapping summary id has an impossible type")
            result[key] = field
        for key in (
            "rendererOperationIndex",
            "segmentClearOperationIndex",
            "segmentTileCount",
        ):
            number = _compact_integer(_compact_required(item, key))
            if number < 0:
                raise ValueError("compact mapping summary has a negative index/count")
            result[key] = number
        for key in nullable_fields:
            value_for_key = _compact_required(item, key)
            result[key] = (
                None if value_for_key is None else _compact_integer(value_for_key)
            )
        source_ids = _compact_required(item, "sourceImageBitmapIds")
        if not isinstance(source_ids, list) or any(
            not isinstance(source_id, str) for source_id in source_ids
        ):
            raise TypeError("compact mapping summary source ids are invalid")
        result["sourceImageBitmapIds"] = list(source_ids)
        for key in ("sourceDimensions", "targetDimensions"):
            dimensions = _compact_required(item, key)
            if not isinstance(dimensions, Mapping):
                raise TypeError("compact mapping summary dimensions are invalid")
            width = _compact_integer(_compact_required(dimensions, "width"))
            height = _compact_integer(_compact_required(dimensions, "height"))
            if width <= 0 or height <= 0:
                raise ValueError("compact mapping summary dimensions are invalid")
            result[key] = {"width": width, "height": height}
        summaries.append(result)
    return summaries


def _decode_compact_mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("compact mapping is not an object")
    required_fields = (
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
        "sources",
        "targets",
        "transforms",
        "composites",
        "filters",
        "tileRows",
    )
    for key in required_fields:
        _compact_required(value, key)
    mapping_id = value["mappingId"]
    if not isinstance(mapping_id, str):
        raise TypeError("compact mapping id has an impossible type")
    renderer_operation_index = _compact_integer(value["rendererOperationIndex"])
    renderer_target = _compact_canvas(value["rendererTarget"])
    source_canvas = _compact_canvas(value["sourceCanvas"])
    renderer_source_rect = _compact_rectangle(value["rendererSourceRect"])
    renderer_destination = _compact_rectangle(value["rendererDestination"])
    renderer_transform = _compact_transform(value["rendererTransform"])
    renderer_alpha = _compact_number(value["rendererAlpha"])
    renderer_composite = value["rendererComposite"]
    renderer_filter = value["rendererFilter"]
    if not isinstance(renderer_composite, str) or not isinstance(renderer_filter, str):
        raise TypeError("compact renderer operation string has an impossible type")
    clear_index = _compact_integer(value["segmentClearOperationIndex"])
    clear_rectangle = _compact_rectangle(value["segmentClearRectangle"])
    nullable_indices: dict[str, int | None] = {}
    for key in (
        "segmentFirstTileOperationIndex",
        "segmentLastTileOperationIndex",
        "segmentExpectedTileCount",
        "firstUnsafeOperationIndex",
    ):
        nullable_indices[key] = (
            None if value[key] is None else _compact_integer(value[key])
        )
    segment_tile_count = _compact_integer(value["segmentTileCount"])
    unsafe_count = _compact_integer(value["unsafeOperationCount"])
    unsafe_types = value["unsafeOperationTypes"]
    source_ids = value["sourceIds"]
    if (
        segment_tile_count < 0
        or unsafe_count < 0
        or not isinstance(unsafe_types, list)
        or any(not isinstance(item, str) for item in unsafe_types)
        or not isinstance(source_ids, list)
        or any(not isinstance(item, str) for item in source_ids)
        or not isinstance(value["segmentOverflow"], bool)
    ):
        raise ValueError("compact mapping metadata is invalid")
    sources = _decode_compact_sources(value["sources"])
    targets = _decode_compact_targets(value["targets"])
    transforms = _decode_compact_transforms(value["transforms"])
    composites = _decode_compact_strings(value["composites"], "composite")
    filters = _decode_compact_strings(value["filters"], "filter")
    tiles = _decode_compact_tiles(
        value,
        sources,
        targets,
        transforms,
        composites,
        filters,
    )
    non_image_bitmap_draws = _decode_compact_non_image_bitmap_draws(
        value.get("nonImageBitmapDraws", [])
    )
    if segment_tile_count != len(tiles):
        raise ValueError("compact segment tile count does not match tile rows")
    return {
        "mappingId": mapping_id,
        "rendererOperationIndex": renderer_operation_index,
        "rendererTarget": renderer_target,
        "sourceCanvas": source_canvas,
        "rendererSourceRect": renderer_source_rect,
        "rendererDestination": renderer_destination,
        "rendererTransform": renderer_transform,
        "rendererAlpha": renderer_alpha,
        "rendererComposite": renderer_composite,
        "rendererFilter": renderer_filter,
        "segmentClearOperationIndex": clear_index,
        "segmentClearRectangle": clear_rectangle,
        "segmentFirstTileOperationIndex": nullable_indices["segmentFirstTileOperationIndex"],
        "segmentLastTileOperationIndex": nullable_indices["segmentLastTileOperationIndex"],
        "segmentTileCount": segment_tile_count,
        "segmentExpectedTileCount": nullable_indices["segmentExpectedTileCount"],
        "tileDraws": tiles,
        "sourceIds": list(source_ids),
        "unsafeOperationCount": unsafe_count,
        "firstUnsafeOperationIndex": nullable_indices["firstUnsafeOperationIndex"],
        "unsafeOperationTypes": list(unsafe_types),
        "segmentOverflow": value["segmentOverflow"],
        "nonImageBitmapDraws": non_image_bitmap_draws,
    }


def decode_compact_completed_mappings(
    payload: object,
) -> dict[str, Any] | None:
    """Decode versioned compact mappings without changing proof semantics."""

    try:
        if not isinstance(payload, Mapping):
            raise TypeError("compact payload is not an object")
        if payload.get("transportVersion") != COMPACT_COMPLETED_MAPPING_TRANSPORT_VERSION:
            raise ValueError("unknown compact transport version")
        if payload.get("transportError") is not None:
            raise ValueError("compact transport reported an error")
        compact_mappings = payload.get("compactMappings")
        if not isinstance(compact_mappings, list):
            raise TypeError("compact mappings are not a list")
        summary: dict[str, int] = {}
        for key in _COMPACT_SUMMARY_FIELDS:
            number = _compact_integer(_compact_required(payload, key))
            if number < 0:
                raise ValueError("compact summary contains a negative count")
            summary[key] = number
        mappings = [_decode_compact_mapping(item) for item in compact_mappings]
        retained_summaries = _decode_compact_mapping_summaries(
            payload.get("retainedCompletedMappingSummaries", [])
        )
        returned_tile_count = sum(len(item["tileDraws"]) for item in mappings)
        if summary["returnedCompletedMappingCount"] != len(mappings):
            raise ValueError("compact returned mapping count is inconsistent")
        if summary["returnedTileRecordCount"] != returned_tile_count:
            raise ValueError("compact returned tile count is inconsistent")
        result: dict[str, Any] = {
            "completedMappings": mappings,
            "retainedCompletedMappingSummaries": retained_summaries,
            **summary,
        }
        return result
    except (OverflowError, TypeError, ValueError, KeyError):
        return None


def _first(value: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in value:
            return value[key]
    return None


def _dimensions(value: object) -> tuple[int, int] | None:
    if not isinstance(value, Mapping):
        return None
    try:
        width = _integer(_first(value, "width"))
        height = _integer(_first(value, "height"))
    except (TypeError, ValueError):
        return None
    return (width, height) if width > 0 and height > 0 else None


def _record_segment_value(record: Mapping[str, Any], segment: Mapping[str, Any], *keys: str) -> Any:
    value = _first(record, *keys)
    if value is not None:
        return value
    return _first(segment, *keys)


def _geometry_classification(
    source_dimensions: tuple[int, int] | None,
    source_rect: tuple[float, float, float, float] | None,
    destination: tuple[float, float, float, float] | None,
    renderer_dimensions: tuple[int, int] | None,
    safe: bool,
) -> str:
    if (
        source_dimensions is None
        or source_rect is None
        or destination is None
        or renderer_dimensions is None
    ):
        return GEOMETRY_UNAVAILABLE
    full_source = source_rect == (0.0, 0.0, float(source_dimensions[0]), float(source_dimensions[1]))
    dx, dy, dw, dh = destination
    in_bounds = dx >= 0 and dy >= 0 and dw > 0 and dh > 0 and (
        dx + dw <= renderer_dimensions[0] and dy + dh <= renderer_dimensions[1]
    )
    if not full_source or not in_bounds or not safe:
        return CROP_OR_PIXEL_PROCESSING
    if dw == source_dimensions[0] and dh == source_dimensions[1]:
        return DIRECT_RENDERER_DRAW
    return PURE_RENDERER_SCALE


def _canvas_id(operation: Mapping[str, Any], key: str = "target") -> str:
    value = operation.get(key)
    if isinstance(value, Mapping):
        return str(value.get("canvasId") or value.get("sourceCanvasId") or "")
    return ""


def _source_id(operation: Mapping[str, Any]) -> str:
    source = operation.get("source")
    if not isinstance(source, Mapping):
        return ""
    return str(source.get("sourceId") or "")


def _operation_index(operation: Mapping[str, Any], fallback: int) -> int:
    try:
        return _integer(operation.get("index", fallback))
    except (TypeError, ValueError):
        return fallback


def _same_geometry(first: object, second: object) -> bool:
    return _rect(first) == _rect(second) and _rect(first) is not None


def _find_renderer_operation(
    operations: list[dict[str, Any]],
    renderer_draw: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, bool]:
    """Find the trace operation represented by a selected native draw call."""

    requested_index = renderer_draw.get("traceOperationIndex", renderer_draw.get("index"))
    if requested_index is not None:
        matches = [
            operation
            for position, operation in enumerate(operations, start=1)
            if _operation_index(operation, position) == _integer(requested_index)
            and operation.get("operation") == "drawImage"
        ]
        if len(matches) == 1:
            return matches[0], False
        if len(matches) > 1:
            return None, True

    renderer_canvas_id = str(
        renderer_draw.get("canvasId")
        or _canvas_id(renderer_draw)
        or ""
    )
    source_id = str(renderer_draw.get("sourceId") or _source_id(renderer_draw) or "")
    source_rect = renderer_draw.get("sourceRect")
    destination = renderer_draw.get("destination")
    matches = [
        operation
        for operation in operations
        if operation.get("operation") == "drawImage"
        and _canvas_id(operation) == renderer_canvas_id
        and _source_id(operation) == source_id
        and (source_rect is None or _same_geometry(operation.get("sourceRect"), source_rect))
        and (destination is None or _same_geometry(operation.get("destination"), destination))
    ]
    if len(matches) != 1:
        return None, len(matches) > 1
    return matches[0], False


def _source_dimensions(source: Mapping[str, Any]) -> tuple[int, int] | None:
    try:
        width = _integer(source["width"])
        height = _integer(source["height"])
    except (KeyError, TypeError, ValueError):
        return None
    return (width, height) if width > 0 and height > 0 else None


def _reject_result(reason: str, **kwargs: Any) -> MappingAnalysis:
    return MappingAnalysis(status=MAPPING_UNAVAILABLE, reason=reason, **kwargs)


def _analyze_legacy_operations(
    trace: Mapping[str, Any],
    renderer_draw: Mapping[str, Any],
    *,
    max_operations: int = TRACE_OPERATION_LIMIT,
) -> MappingAnalysis:
    """Prove one purchased source canvas is a complete tile permutation."""

    if not isinstance(trace, Mapping):
        return _reject_result("trace is not an object")
    operations_value = trace.get("operations")
    if not isinstance(operations_value, list):
        return _reject_result("trace operations are unavailable")
    trace_overflow = bool(trace.get("trace_overflow") or trace.get("overflow"))
    if trace_overflow or len(operations_value) > max_operations:
        return _reject_result("trace_overflow", trace_overflow=True)
    operations = [item for item in operations_value if isinstance(item, dict)]
    if len(operations) != len(operations_value):
        return _reject_result("trace contains an invalid operation")

    renderer, ambiguous_renderer = _find_renderer_operation(operations, renderer_draw)
    if renderer is None:
        return _reject_result(
            "renderer-to-source draw operation is missing or not unique"
            if not ambiguous_renderer
            else "renderer-to-source draw operation is ambiguous"
        )
    renderer_source = renderer.get("source")
    if not isinstance(renderer_source, Mapping):
        return _reject_result("renderer source metadata is unavailable")
    if renderer_source.get("constructor") != "HTMLCanvasElement":
        return _reject_result("renderer source is not an HTMLCanvasElement")

    renderer_canvas_id = _canvas_id(renderer)
    source_canvas_id = str(
        renderer_source.get("canvasId")
        or renderer_source.get("sourceCanvasId")
        or ""
    )
    if not renderer_canvas_id or not source_canvas_id or renderer_canvas_id == source_canvas_id:
        return _reject_result("renderer/source canvas identity is unavailable or invalid")
    source_dimensions = _source_dimensions(renderer_source)
    source_rect = _numeric_rect(renderer.get("sourceRect"))
    destination = _numeric_rect(renderer.get("destination"))
    if source_dimensions is None or source_rect is None or destination is None:
        return _reject_result("renderer geometry is unavailable")
    if source_rect != (0.0, 0.0, float(source_dimensions[0]), float(source_dimensions[1])):
        return _reject_result("renderer draw crops or resizes the source canvas")
    renderer_dimensions = _source_dimensions(renderer.get("target", {}))
    if renderer_dimensions is not None:
        dx, dy, dw, dh = destination
        if dx < 0 or dy < 0 or dw <= 0 or dh <= 0 or dx + dw > renderer_dimensions[0] or dy + dh > renderer_dimensions[1]:
            return _reject_result("renderer draw is cropped by the target canvas")
    if not _safe_draw_operation(renderer):
        return _reject_result("renderer draw has non-identity pixel processing")

    renderer_index = _operation_index(renderer, operations.index(renderer) + 1)
    reset_indices = [
        _operation_index(operation, index)
        for index, operation in enumerate(operations, start=1)
        if operation.get("operation") == "clearRect"
        and _canvas_id(operation) == source_canvas_id
        and _operation_index(operation, index) < renderer_index
    ]
    if not reset_indices:
        return _reject_result("source canvas clear boundary is unavailable")
    clear_boundary = max(reset_indices)

    window: list[tuple[int, dict[str, Any]]] = [
        (_operation_index(operation, index), operation)
        for index, operation in enumerate(operations, start=1)
        if clear_boundary < _operation_index(operation, index) < renderer_index
        and _canvas_id(operation) == source_canvas_id
    ]
    draw_operations = [
        operation
        for _, operation in window
        if operation.get("operation") == "drawImage"
    ]
    source_groups: dict[str, list[dict[str, Any]]] = {}
    additional_pixel_processing = False
    for _, operation in window:
        operation_name = operation.get("operation")
        if operation_name == "clearRect":
            # A second clear would make the boundary ambiguous.
            additional_pixel_processing = True
            continue
        if operation_name != "drawImage":
            additional_pixel_processing = True
            continue
        source = operation.get("source")
        source_id = _source_id(operation)
        if not isinstance(source, Mapping) or source.get("constructor") != "ImageBitmap":
            additional_pixel_processing = True
            continue
        if not source_id:
            additional_pixel_processing = True
            continue
        source_groups.setdefault(source_id, []).append(operation)
    if additional_pixel_processing:
        return _reject_result(
            "source canvas contains additional pixel processing",
            additional_pixel_processing=True,
        )
    if not draw_operations or len(source_groups) != 1:
        return _reject_result(
            "source canvas maps to zero or multiple ImageBitmap sources"
        )

    imagebitmap_source_id, tiles = next(iter(source_groups.items()))
    if any(not _safe_draw_operation(operation) for operation in tiles):
        return _reject_result("tile draw has non-identity pixel processing")
    dimensions = source_dimensions
    tile_dimensions: set[tuple[int, int]] = set()
    mappings: list[dict[str, int]] = []
    source_positions: list[tuple[int, int]] = []
    destination_positions: list[tuple[int, int]] = []
    source_out_of_bounds = 0
    destination_out_of_bounds = 0
    for operation in tiles:
        source = operation.get("source")
        if not isinstance(source, Mapping) or _source_dimensions(source) != dimensions:
            return _reject_result("ImageBitmap dimensions differ from source canvas")
        source_rect = _rect(operation.get("sourceRect"))
        destination_rect = _rect(operation.get("destination"))
        if source_rect is None or destination_rect is None:
            return _reject_result("tile geometry is unavailable")
        sx, sy, sw, sh = source_rect
        dx, dy, dw, dh = destination_rect
        if sw <= 0 or sh <= 0 or (sw, sh) != (dw, dh):
            return _reject_result("tile dimensions are invalid")
        tile_dimensions.add((sw, sh))
        source_positions.append((sx, sy))
        destination_positions.append((dx, dy))
        source_out_of_bounds += int(sx < 0 or sy < 0 or sx + sw > dimensions[0] or sy + sh > dimensions[1])
        destination_out_of_bounds += int(dx < 0 or dy < 0 or dx + dw > dimensions[0] or dy + dh > dimensions[1])
        mappings.append({
            "source_x": sx,
            "source_y": sy,
            "destination_x": dx,
            "destination_y": dy,
            "width": sw,
            "height": sh,
        })
    if len(tile_dimensions) != 1:
        return _reject_result("tile dimensions are not uniform")
    tile_width, tile_height = next(iter(tile_dimensions))
    if dimensions[0] % tile_width or dimensions[1] % tile_height:
        return _reject_result("tile grid does not cover complete source dimensions")

    expected_positions = {
        (x, y)
        for y in range(0, dimensions[1], tile_height)
        for x in range(0, dimensions[0], tile_width)
    }
    source_counts = Counter(source_positions)
    destination_counts = Counter(destination_positions)
    source_duplicates = sum(max(0, count - 1) for count in source_counts.values())
    destination_duplicates = sum(max(0, count - 1) for count in destination_counts.values())
    source_unique = set(source_positions)
    destination_unique = set(destination_positions)
    source_gaps = len(expected_positions - source_unique)
    destination_gaps = len(expected_positions - destination_unique)
    if (
        source_out_of_bounds
        or destination_out_of_bounds
        or source_duplicates
        or destination_duplicates
        or source_gaps
        or destination_gaps
        or len(tiles) != len(expected_positions)
    ):
        return _reject_result(
            "tile mapping is not a complete bijection",
            source_duplicate_tile_count=source_duplicates,
            destination_duplicate_tile_count=destination_duplicates,
            source_tile_gap_count=source_gaps,
            destination_tile_gap_count=destination_gaps,
            source_out_of_bounds_count=source_out_of_bounds,
            destination_out_of_bounds_count=destination_out_of_bounds,
        )

    ordered = tuple(_canonical_mapping(mappings))
    index_values = [
        _operation_index(operation, operations.index(operation) + 1)
        for operation in tiles
    ]
    proven = PurchasedMapping(
        mapping=ordered,
        source_dimensions=dimensions,
        destination_dimensions=dimensions,
        tile_dimensions=(tile_width, tile_height),
        renderer_canvas_id=renderer_canvas_id,
        source_canvas_id=source_canvas_id,
        imagebitmap_source_id=imagebitmap_source_id,
        renderer_draw_operation_index=renderer_index,
        first_operation_index=min(index_values),
        last_operation_index=max(index_values),
        clear_boundary_operation_index=clear_boundary,
        mapping_sha256=mapping_sha256(ordered),
    )
    return MappingAnalysis(status=MAPPING_PROVEN, reason="complete source/destination bijection", mapping=proven)


def _safe_draw_operation(operation: Mapping[str, Any]) -> bool:
    transform = operation.get("transform")
    if not isinstance(transform, Mapping):
        return False
    if any(transform.get(key) != value for key, value in _IDENTITY_TRANSFORM.items()):
        return False
    alpha = operation.get("globalAlpha")
    if alpha != 1 and alpha != 1.0:
        return False
    if operation.get("globalCompositeOperation") != "source-over":
        return False
    return operation.get("filter") == "none"


def _completed_mapping_match(
    record: Mapping[str, Any],
    renderer_draw: Mapping[str, Any],
) -> bool:
    requested_mapping_id = _first(renderer_draw, "mappingId", "mapping_id")
    record_mapping_id = _first(record, "mappingId", "mapping_id")
    if requested_mapping_id is not None:
        return (
            record_mapping_id is not None
            and str(record_mapping_id) == str(requested_mapping_id)
        )

    requested_index = _first(
        renderer_draw,
        "traceOperationIndex",
        "rendererOperationIndex",
        "renderer_operation_index",
        "index",
    )
    record_index = _first(
        record,
        "rendererOperationIndex",
        "renderer_operation_index",
    )
    requested_source_canvas = _first(renderer_draw, "sourceCanvasId", "source_canvas_id")
    source = _first(record, "sourceCanvas", "source_canvas")
    record_source_canvas = _first(record, "sourceCanvasId", "source_canvas_id")
    if isinstance(source, Mapping):
        record_source_canvas = _first(source, "canvasId", "canvas_id") or record_source_canvas
    if requested_index is None or record_index is None or requested_source_canvas is None:
        return False
    try:
        return (
            _integer(requested_index) == _integer(record_index)
            and str(requested_source_canvas) == str(record_source_canvas or "")
        )
    except (TypeError, ValueError):
        return False


def _completed_record_identity(
    record: Mapping[str, Any],
) -> tuple[str | None, int | None, str | None]:
    mapping_id = _first(record, "mappingId", "mapping_id")
    renderer_index_value = _first(
        record,
        "rendererOperationIndex",
        "renderer_operation_index",
    )
    try:
        renderer_index = (
            None if renderer_index_value is None else _integer(renderer_index_value)
        )
    except (TypeError, ValueError):
        renderer_index = None
    source = _first(record, "sourceCanvas", "source_canvas")
    source_canvas_id = _first(record, "sourceCanvasId", "source_canvas_id")
    if isinstance(source, Mapping):
        source_canvas_id = _first(source, "canvasId", "canvas_id") or source_canvas_id
    return (
        None if mapping_id is None else str(mapping_id),
        renderer_index,
        None if source_canvas_id is None else str(source_canvas_id),
    )


def _analyze_completed_mapping(
    trace: Mapping[str, Any],
    renderer_draw: Mapping[str, Any],
) -> MappingAnalysis:
    records_value = _first(trace, "completedMappings", "completed_mappings")
    if not isinstance(records_value, list):
        return _reject_result(
            "completed mappings are unavailable",
            mapping_source="completed_segment",
        )
    records = [record for record in records_value if isinstance(record, Mapping)]
    matches = [record for record in records if _completed_mapping_match(record, renderer_draw)]
    if len(matches) != 1:
        requested_mapping_id = _first(renderer_draw, "mappingId", "mapping_id")
        reason = (
            "completed mapping was evicted or unavailable"
            if requested_mapping_id is not None
            else "completed mapping identity is missing or unavailable"
        )
        return _reject_result(
            reason,
            mapping_source="completed_segment",
            mapping_id=None if requested_mapping_id is None else str(requested_mapping_id),
            completed_mapping_evicted=requested_mapping_id is not None,
        )
    record = matches[0]
    mapping_id, renderer_index, record_source_canvas_id = _completed_record_identity(record)
    segment_value = _first(record, "segment")
    segment: Mapping[str, Any] = segment_value if isinstance(segment_value, Mapping) else record
    source_canvas_value = _first(record, "sourceCanvas", "source_canvas")
    source_canvas: Mapping[str, Any] = (
        source_canvas_value if isinstance(source_canvas_value, Mapping) else {}
    )
    renderer_target_value = _first(record, "rendererTarget", "renderer_target")
    renderer_target: Mapping[str, Any] = (
        renderer_target_value if isinstance(renderer_target_value, Mapping) else {}
    )
    source_dimensions = _dimensions(source_canvas)
    renderer_dimensions = _dimensions(renderer_target)
    source_rect_value = _record_segment_value(
        record, segment, "rendererSourceRect", "renderer_source_rect", "sourceRect", "source_rect"
    )
    destination_value = _record_segment_value(
        record, segment, "rendererDestination", "renderer_destination", "destination"
    )
    source_rect = _numeric_rect(source_rect_value)
    destination = _numeric_rect(destination_value)
    renderer_operation = {
        "transform": _record_segment_value(
            record, segment, "rendererTransform", "renderer_transform", "transform"
        ),
        "globalAlpha": _record_segment_value(
            record, segment, "rendererAlpha", "renderer_alpha", "globalAlpha", "global_alpha"
        ),
        "globalCompositeOperation": _record_segment_value(
            record,
            segment,
            "rendererComposite",
            "renderer_composite",
            "globalCompositeOperation",
            "global_composite_operation",
        ),
        "filter": _record_segment_value(record, segment, "rendererFilter", "renderer_filter", "filter"),
    }
    classification = _geometry_classification(
        source_dimensions,
        source_rect,
        destination,
        renderer_dimensions,
        _safe_draw_operation(renderer_operation),
    )
    base = {
        "mapping_source": "completed_segment",
        "mapping_id": mapping_id,
        "mapping_provenance": None,
        "renderer_geometry_classification": classification,
        "renderer_canvas_id": str(_first(renderer_target, "canvasId", "canvas_id") or "") or None,
        "source_canvas_id": record_source_canvas_id,
        "segment_clear_operation_index": _record_segment_value(
            record, segment, "segmentClearOperationIndex", "segment_clear_operation_index", "clearOperationIndex", "clear_operation_index"
        ),
        "segment_first_tile_operation_index": _record_segment_value(
            record, segment, "segmentFirstTileOperationIndex", "segment_first_tile_operation_index", "firstTileOperationIndex", "first_tile_operation_index"
        ),
        "segment_last_tile_operation_index": _record_segment_value(
            record, segment, "segmentLastTileOperationIndex", "segment_last_tile_operation_index", "lastTileOperationIndex", "last_tile_operation_index"
        ),
        "segment_tile_count": 0,
        "segment_expected_tile_count": _record_segment_value(
            record, segment, "segmentExpectedTileCount", "segment_expected_tile_count", "expectedTileCount", "expected_tile_count"
        ),
        "segment_overflow": bool(_record_segment_value(record, segment, "segmentOverflow", "segment_overflow", "overflow")),
        "first_unsafe_operation_index": _record_segment_value(record, segment, "firstUnsafeOperationIndex", "first_unsafe_operation_index"),
        "unsafe_operation_types": (),
    }
    non_image_bitmap_draws_value = _record_segment_value(
        record, segment, "nonImageBitmapDraws", "non_image_bitmap_draws"
    )
    if non_image_bitmap_draws_value is None:
        base["non_image_bitmap_draws"] = ()
    elif not isinstance(non_image_bitmap_draws_value, list) or any(
        not isinstance(item, Mapping) for item in non_image_bitmap_draws_value
    ):
        return _reject_result(
            "completed segment non-ImageBitmap provenance metadata is invalid",
            **base,
        )
    else:
        base["non_image_bitmap_draws"] = tuple(
            dict(item) for item in non_image_bitmap_draws_value
        )
    unsafe_count_value = _record_segment_value(
        record, segment, "unsafeOperationCount", "unsafe_operation_count"
    )
    try:
        base["unsafe_operation_count"] = 0 if unsafe_count_value is None else _integer(unsafe_count_value)
    except (TypeError, ValueError):
        return _reject_result("completed segment unsafe-operation metadata is invalid", **base)
    unsafe_types_value = _record_segment_value(
        record, segment, "unsafeOperationTypes", "unsafe_operation_types"
    )
    if unsafe_types_value is not None and not isinstance(unsafe_types_value, list):
        return _reject_result("completed segment unsafe-operation metadata is invalid", **base)
    base["unsafe_operation_types"] = tuple(
        str(item) for item in (unsafe_types_value or []) if item is not None
    )
    if classification == GEOMETRY_UNAVAILABLE:
        return _reject_result(
            "renderer geometry is unavailable",
            **base,
        )
    if classification == CROP_OR_PIXEL_PROCESSING:
        return _reject_result(
            "renderer geometry crops or applies pixel processing",
            **base,
        )
    if source_dimensions is None or renderer_dimensions is None or source_rect is None or destination is None:
        return _reject_result("renderer geometry is unavailable", **base)
    if renderer_index is None or record_source_canvas_id is None:
        return _reject_result("source canvas identity is unavailable", **base)
    if source_rect != (0.0, 0.0, float(source_dimensions[0]), float(source_dimensions[1])):
        return _reject_result("renderer draw crops the source canvas", **base)

    tile_draws_value = _record_segment_value(record, segment, "tileDraws", "tile_draws")
    if not isinstance(tile_draws_value, list):
        return _reject_result("completed segment tile records are unavailable", **base)
    base["segment_tile_count"] = len(tile_draws_value)
    if base["segment_overflow"]:
        return _reject_result("completed segment overflow", trace_overflow=True, **base)
    if len(tile_draws_value) == 0:
        return _reject_result("completed segment has no tile draws", **base)
    if len(tile_draws_value) > MAX_TILE_DRAW_RECORDS:
        return _reject_result("completed segment exceeds tile record bound", trace_overflow=True, **base)
    if base["unsafe_operation_count"] or base["unsafe_operation_types"]:
        return _reject_result("completed segment contains unsafe operations", additional_pixel_processing=True, **base)

    clear_index_value = base["segment_clear_operation_index"]
    try:
        clear_index = _integer(clear_index_value)
    except (TypeError, ValueError):
        return _reject_result("completed segment clear boundary is unavailable", **base)
    clear_rectangle = _record_segment_value(
        record, segment, "segmentClearRectangle", "segment_clear_rectangle", "clearRectangle", "clear_rectangle"
    )
    clear_rect = _rect(clear_rectangle)
    if clear_rect is None:
        return _reject_result("completed segment clear boundary geometry is unavailable", **base)
    if clear_rect != (0, 0, *source_dimensions):
        return _reject_result("completed segment clear boundary is partial", additional_pixel_processing=True, **base)

    source_ids: set[str] = set()
    tile_dimensions: set[tuple[int, int]] = set()
    mappings: list[dict[str, int]] = []
    source_positions: list[tuple[int, int]] = []
    destination_positions: list[tuple[int, int]] = []
    operation_indices: list[int] = []
    source_out_of_bounds = 0
    destination_out_of_bounds = 0
    for tile in tile_draws_value:
        if not isinstance(tile, Mapping):
            return _reject_result("completed segment contains an invalid tile record", **base)
        source = _first(tile, "source")
        target = _first(tile, "target")
        if not isinstance(source, Mapping) or source.get("constructor") != "ImageBitmap":
            return _reject_result("completed segment has a non-ImageBitmap source", **base)
        source_id = str(_first(source, "sourceId", "source_id") or "")
        if not source_id:
            return _reject_result("ImageBitmap source identity is unavailable", **base)
        source_ids.add(source_id)
        if _dimensions(source) != source_dimensions:
            return _reject_result("ImageBitmap dimensions differ from source canvas", **base)
        if not isinstance(target, Mapping) or str(_first(target, "canvasId", "canvas_id") or "") != record_source_canvas_id:
            return _reject_result("tile target canvas identity is invalid", **base)
        if _dimensions(target) != source_dimensions:
            return _reject_result("tile target dimensions are invalid", **base)
        if not _safe_draw_operation({
            "transform": _first(tile, "transform"),
            "globalAlpha": _first(tile, "globalAlpha", "global_alpha"),
            "globalCompositeOperation": _first(tile, "globalCompositeOperation", "global_composite_operation"),
            "filter": _first(tile, "filter"),
        }):
            return _reject_result("tile draw has non-identity pixel processing", **base)
        source_rect_tile = _rect(_first(tile, "sourceRect", "source_rect"))
        destination_tile = _rect(_first(tile, "destination"))
        if source_rect_tile is None or destination_tile is None:
            return _reject_result("tile geometry is unavailable", **base)
        sx, sy, sw, sh = source_rect_tile
        dx, dy, dw, dh = destination_tile
        if sw <= 0 or sh <= 0 or (sw, sh) != (dw, dh):
            return _reject_result("tile dimensions are invalid", **base)
        tile_dimensions.add((sw, sh))
        source_positions.append((sx, sy))
        destination_positions.append((dx, dy))
        source_out_of_bounds += int(sx < 0 or sy < 0 or sx + sw > source_dimensions[0] or sy + sh > source_dimensions[1])
        destination_out_of_bounds += int(dx < 0 or dy < 0 or dx + dw > source_dimensions[0] or dy + dh > source_dimensions[1])
        try:
            operation_indices.append(_integer(_first(tile, "operationIndex", "operation_index")))
        except (TypeError, ValueError):
            return _reject_result("tile operation identity is unavailable", **base)
        mappings.append({
            "source_x": sx,
            "source_y": sy,
            "destination_x": dx,
            "destination_y": dy,
            "width": sw,
            "height": sh,
        })
    if len(source_ids) != 1:
        return _reject_result("completed segment maps multiple ImageBitmap sources", **base)
    if len(tile_dimensions) != 1:
        return _reject_result("tile dimensions are not uniform", **base)
    tile_width, tile_height = next(iter(tile_dimensions))
    if source_dimensions[0] % tile_width or source_dimensions[1] % tile_height:
        return _reject_result("tile grid does not cover complete source dimensions", **base)
    expected_positions = {
        (x, y)
        for y in range(0, source_dimensions[1], tile_height)
        for x in range(0, source_dimensions[0], tile_width)
    }
    expected_count = base["segment_expected_tile_count"]
    if expected_count is not None:
        try:
            expected_count = _integer(expected_count)
        except (TypeError, ValueError):
            return _reject_result("completed segment expected tile count is invalid", **base)
        if expected_count != len(expected_positions):
            return _reject_result("completed segment expected tile count is invalid", **base)
    else:
        expected_count = len(expected_positions)
    source_counts = Counter(source_positions)
    destination_counts = Counter(destination_positions)
    source_duplicates = sum(max(0, count - 1) for count in source_counts.values())
    destination_duplicates = sum(max(0, count - 1) for count in destination_counts.values())
    source_gaps = len(expected_positions - set(source_positions))
    destination_gaps = len(expected_positions - set(destination_positions))
    if (
        source_out_of_bounds
        or destination_out_of_bounds
        or source_duplicates
        or destination_duplicates
        or source_gaps
        or destination_gaps
        or len(mappings) != expected_count
    ):
        return _reject_result(
            "tile mapping is not a complete bijection",
            source_duplicate_tile_count=source_duplicates,
            destination_duplicate_tile_count=destination_duplicates,
            source_tile_gap_count=source_gaps,
            destination_tile_gap_count=destination_gaps,
            source_out_of_bounds_count=source_out_of_bounds,
            destination_out_of_bounds_count=destination_out_of_bounds,
            **base,
        )
    first_tile = min(operation_indices)
    last_tile = max(operation_indices)
    if len(set(operation_indices)) != len(operation_indices):
        return _reject_result("completed segment tile operation identity is duplicated", **base)
    try:
        if base["segment_first_tile_operation_index"] is not None and _integer(base["segment_first_tile_operation_index"]) != first_tile:
            return _reject_result("completed segment first tile identity is invalid", **base)
        if base["segment_last_tile_operation_index"] is not None and _integer(base["segment_last_tile_operation_index"]) != last_tile:
            return _reject_result("completed segment last tile identity is invalid", **base)
    except (TypeError, ValueError):
        return _reject_result("completed segment tile identity is invalid", **base)
    if not all(clear_index < index < (renderer_index or index + 1) for index in operation_indices):
        return _reject_result("completed segment operation ordering is invalid", **base)
    ordered = tuple(_canonical_mapping(mappings))
    proven = PurchasedMapping(
        mapping=ordered,
        source_dimensions=source_dimensions,
        destination_dimensions=source_dimensions,
        tile_dimensions=(tile_width, tile_height),
        renderer_canvas_id=str(_first(renderer_target, "canvasId", "canvas_id") or "") or None,
        source_canvas_id=record_source_canvas_id,
        imagebitmap_source_id=next(iter(source_ids)),
        renderer_draw_operation_index=renderer_index,
        first_operation_index=first_tile,
        last_operation_index=last_tile,
        clear_boundary_operation_index=clear_index,
        mapping_sha256=mapping_sha256(ordered),
        mapping_id=mapping_id,
        renderer_geometry_classification=classification,
        renderer_source_rect={key: float(value) for key, value in zip(("x", "y", "width", "height"), source_rect, strict=True)},
        renderer_destination={key: float(value) for key, value in zip(("x", "y", "width", "height"), destination, strict=True)},
        renderer_target_dimensions=renderer_dimensions,
        segment_tile_count=len(mappings),
        segment_expected_tile_count=expected_count,
        segment_overflow=False,
        unsafe_operation_count=0,
        first_unsafe_operation_index=None,
        unsafe_operation_types=(),
        mapping_provenance="direct",
    )
    return MappingAnalysis(
        status=MAPPING_PROVEN,
        reason="completed segment source/destination bijection",
        mapping=proven,
        mapping_source="completed_segment",
        mapping_id=mapping_id,
        segment_clear_operation_index=clear_index,
        segment_first_tile_operation_index=first_tile,
        segment_last_tile_operation_index=last_tile,
        segment_tile_count=len(mappings),
        segment_expected_tile_count=expected_count,
        segment_overflow=False,
        renderer_geometry_classification=classification,
        mapping_provenance="direct",
        non_image_bitmap_draws=(),
    )


def analyze_purchased_mapping(
    trace: Mapping[str, Any],
    renderer_draw: Mapping[str, Any],
    *,
    max_operations: int = TRACE_OPERATION_LIMIT,
) -> MappingAnalysis:
    """Analyze a completed segment; retain the old operations fallback for probes."""

    if isinstance(trace, Mapping) and (
        "completedMappings" in trace or "completed_mappings" in trace
    ):
        return _analyze_completed_mapping(trace, renderer_draw)
    return _analyze_legacy_operations(
        trace,
        renderer_draw,
        max_operations=max_operations,
    )


def build_purchased_mapping(
    trace: Mapping[str, Any],
    renderer_draw: Mapping[str, Any],
    *,
    max_operations: int = TRACE_OPERATION_LIMIT,
) -> PurchasedMapping | None:
    """Return a proven mapping or ``None`` for the native PNG fallback."""

    return analyze_purchased_mapping(
        trace,
        renderer_draw,
        max_operations=max_operations,
    ).mapping


# Small aliases make the pure helper convenient for probe-to-production tests.
mapping_from_trace = build_purchased_mapping
validate_purchased_mapping = analyze_purchased_mapping
