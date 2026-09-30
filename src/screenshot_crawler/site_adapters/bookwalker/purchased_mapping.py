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
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

TRACE_OPERATION_LIMIT = 5_000
MAPPING_PROVEN = "MAPPING_PROVEN"
MAPPING_UNAVAILABLE = "MAPPING_UNAVAILABLE"

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


def analyze_purchased_mapping(
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
    source_rect = _rect(renderer.get("sourceRect"))
    destination = _rect(renderer.get("destination"))
    if source_dimensions is None or source_rect is None or destination is None:
        return _reject_result("renderer geometry is unavailable")
    if source_rect != (0, 0, *source_dimensions):
        return _reject_result("renderer draw crops or resizes the source canvas")
    if destination[2:] != source_dimensions:
        return _reject_result("renderer draw destination differs from source dimensions")
    renderer_dimensions = _source_dimensions(renderer.get("target", {}))
    if renderer_dimensions is not None:
        dx, dy, dw, dh = destination
        if dx < 0 or dy < 0 or dx + dw > renderer_dimensions[0] or dy + dh > renderer_dimensions[1]:
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
    source_counts = {position: source_positions.count(position) for position in set(source_positions)}
    destination_counts = {
        position: destination_positions.count(position) for position in set(destination_positions)
    }
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
