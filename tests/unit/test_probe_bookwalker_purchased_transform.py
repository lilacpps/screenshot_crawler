from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path

from PIL import Image

SCRIPT_PATH = (
    Path(__file__).parents[2]
    / "scripts"
    / "probe_bookwalker_purchased_transform.py"
)
SPEC = importlib.util.spec_from_file_location(
    "probe_bookwalker_purchased_transform",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)


def _gradient(width: int, height: int) -> Image.Image:
    image = Image.new("RGB", (width, height))
    pixels = image.load()
    for y in range(height):
        for x in range(width):
            pixels[x, y] = ((x * 17 + y * 3) % 256, (x * 5 + y * 19) % 256, (x * 11 + y * 7) % 256)
    return image


def _jpeg_bytes(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=90)
    return output.getvalue()


def _trace_tile_operation(
    *,
    target_id: str,
    source_id: str,
    source_x: int,
    source_y: int,
    destination_x: int,
    destination_y: int,
    tile_size: int,
    target_size: int,
    target_constructor: str = "HTMLCanvasElement",
    source_constructor: str = "ImageBitmap",
    index: int = 1,
) -> dict[str, object]:
    return {
        "index": index,
        "operation": "drawImage",
        "target": {
            "canvasId": target_id,
            "constructor": target_constructor,
            "width": target_size,
            "height": target_size,
        },
        "source": {
            "sourceId": source_id,
            "constructor": source_constructor,
            "width": target_size,
            "height": target_size,
            **(
                {"canvasId": source_id}
                if source_constructor == "HTMLCanvasElement"
                else {}
            ),
        },
        "sourceRect": {
            "x": source_x,
            "y": source_y,
            "width": tile_size,
            "height": tile_size,
        },
        "destination": {
            "x": destination_x,
            "y": destination_y,
            "width": tile_size,
            "height": tile_size,
        },
        "transform": {"a": 1, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0},
        "globalCompositeOperation": "source-over",
        "globalAlpha": 1,
        "filter": "none",
    }


def test_exact_image_comparison_is_direct_decode() -> None:
    image = _gradient(12, 10)
    result, aligned = probe.analyze_image_pair(image, image.copy())

    assert result["classification"] == "DIRECT_DECODE"
    assert result["direct_pixel_diff"]["exact_pixel_equality"] is True
    assert result["direct_pixel_diff"]["diff_bounding_box"] is None
    assert aligned.tobytes() == image.tobytes()


def test_crop_offset_detection_finds_five_pixel_left_crop() -> None:
    raw = _gradient(13, 8)
    native = raw.crop((5, 0, 13, 8))
    result, _ = probe.analyze_image_pair(raw, native)

    assert result["classification"] == "SIMPLE_CROP"
    assert result["best_crop"]["exact_pixel_equality"] is True
    assert result["best_crop"]["parameters"]["left"] == 5
    assert result["best_crop"]["parameters"]["right"] == 13


def test_pixel_diff_statistics_reports_small_channel_change_and_spatial_data() -> None:
    first = _gradient(8, 8)
    second = first.copy()
    second.putpixel((3, 4), (second.getpixel((3, 4))[0] + 1, *second.getpixel((3, 4))[1:]))

    stats = probe.pixel_diff_statistics(first, second)

    assert stats["exact_pixel_equality"] is False
    assert stats["differing_pixel_count"] == 1
    assert stats["differing_pixel_ratio"] == 1 / 64
    assert stats["max_absolute_channel_difference"] == 1
    assert stats["diff_bounding_box"] == {"left": 3, "top": 4, "right": 4, "bottom": 5}
    assert stats["channel_differences"]["r"]["histogram"]["1"] == 1
    assert stats["channel_differences"]["g"]["histogram"] == {}
    assert stats["channel_differences"]["b"]["histogram"] == {}
    assert stats["block_histogram"]["8"]["0,0"] == 1


def test_tile_swap_is_detected_only_after_direct_comparison_fails() -> None:
    raw = Image.new("RGB", (8, 8))
    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
    for tile_index, color in enumerate(colors):
        left = (tile_index % 2) * 4
        top = (tile_index // 2) * 4
        for y in range(top, top + 4):
            for x in range(left, left + 4):
                raw.putpixel((x, y), color)
    native = Image.new("RGB", (8, 8))
    for source_index, destination_index in enumerate((1, 0, 2, 3)):
        source_left = (source_index % 2) * 4
        source_top = (source_index // 2) * 4
        destination_left = (destination_index % 2) * 4
        destination_top = (destination_index // 2) * 4
        tile = raw.crop((source_left, source_top, source_left + 4, source_top + 4))
        native.paste(tile, (destination_left, destination_top))

    result, _ = probe.analyze_image_pair(raw, native)

    assert result["classification"] == "TILE_REARRANGEMENT"
    assert result["tile_permutation"]["grids"]["2"]["permutation_detected"] is True


def test_trace_tile_report_proves_complete_bijection_and_canonical_mapping() -> None:
    operations = []
    for source_index, destination_index in enumerate((1, 0, 2, 3)):
        source_x = (source_index % 2) * 4
        source_y = (source_index // 2) * 4
        destination_x = (destination_index % 2) * 4
        destination_y = (destination_index // 2) * 4
        operations.append(
            _trace_tile_operation(
                target_id="source-canvas",
                source_id="bitmap-a",
                source_x=source_x,
                source_y=source_y,
                destination_x=destination_x,
                destination_y=destination_y,
                tile_size=4,
                target_size=8,
                index=len(operations) + 1,
            )
        )

    report = probe.trace_tile_rearrangement_report({"operations": operations})
    group = report["groups"][0]

    assert report["detected"] is True
    assert group["complete_bijection"] is True
    assert group["source_duplicate_tile_count"] == 0
    assert group["destination_duplicate_tile_count"] == 0
    assert group["source_tile_gap_count"] == 0
    assert group["destination_tile_gap_count"] == 0
    assert group["source_out_of_bounds_count"] == 0
    assert group["destination_out_of_bounds_count"] == 0
    assert len(group["mapping"]) == 4
    assert len(group["mapping_sha256"]) == 64


def test_trace_tile_report_rejects_duplicate_and_gap_mapping() -> None:
    operations = [
        _trace_tile_operation(
            target_id="source-canvas",
            source_id="bitmap-a",
            source_x=0,
            source_y=0,
            destination_x=0,
            destination_y=0,
            tile_size=4,
            target_size=8,
        ),
        _trace_tile_operation(
            target_id="source-canvas",
            source_id="bitmap-a",
            source_x=0,
            source_y=0,
            destination_x=4,
            destination_y=0,
            tile_size=4,
            target_size=8,
            index=2,
        ),
    ]
    group = probe.trace_tile_rearrangement_report({"operations": operations})["groups"][0]

    assert group["complete_bijection"] is False
    assert group["source_duplicate_tile_count"] == 1
    assert group["source_tile_gap_count"] == 3
    assert group["destination_tile_gap_count"] == 2


def test_trace_tile_report_keeps_geometry_rejected_groups_for_diagnostics() -> None:
    operation = _trace_tile_operation(
        target_id="intermediate",
        source_id="bitmap-a",
        source_x=0,
        source_y=0,
        destination_x=0,
        destination_y=0,
        tile_size=4,
        target_size=8,
    )
    operation["source"]["width"] = 12
    operation["source"]["height"] = 8

    report = probe.trace_tile_rearrangement_report({"operations": [operation]})

    assert report["groups"] == []
    rejected = report["rejected_groups"][0]
    assert rejected["source_dimensions"] == {"width": 12, "height": 8}
    assert rejected["target_dimensions"] == {"width": 8, "height": 8}
    assert rejected["expected_source_tile_count"] == 6
    assert "target_source_dimension_mismatch" in rejected["rejection_reasons"]


def test_trace_tile_report_segments_repeated_passes_at_clear_rect() -> None:
    operations = []
    for pass_index in range(2):
        operations.append({
            "index": len(operations) + 1,
            "operation": "clearRect",
            "target": {"canvasId": "source-canvas"},
        })
        for source_index, destination_index in enumerate((1, 0, 2, 3)):
            operations.append(
                _trace_tile_operation(
                    target_id="source-canvas",
                    source_id="bitmap-a",
                    source_x=(source_index % 2) * 4,
                    source_y=(source_index // 2) * 4,
                    destination_x=(destination_index % 2) * 4,
                    destination_y=(destination_index // 2) * 4,
                    tile_size=4,
                    target_size=8,
                    index=len(operations) + 1,
                )
            )

    report = probe.trace_tile_rearrangement_report({"operations": operations})

    assert report["detected"] is True
    assert len(report["groups"]) == 2
    assert [group["operations"] for group in report["groups"]] == [4, 4]
    assert [group["target_segment"] for group in report["groups"]] == [1, 2]


def test_trace_mapping_window_reports_overflow_after_complete_mapping() -> None:
    mapping_group = {
        "target_canvas_id": "source-canvas",
        "source_id": "bitmap-a",
        "first_operation_index": 5,
        "last_operation_index": 8,
        "operations": 4,
        "expected_tile_count": 4,
        "complete_bijection": True,
    }
    mapping = {
        "renderer": {
            "draw_operation_index": 10,
            "source_canvas_id": "source-canvas",
        },
        "permutation": mapping_group,
    }
    trace = {
        "operations": [
            {
                "index": 3,
                "operation": "clearRect",
                "target": {"canvasId": "source-canvas"},
            },
            {"index": 10, "operation": "drawImage", "target": {}},
        ],
        "max_operations": 6,
        "trace_overflow": True,
        "overflow_operation_index": 10,
        "observed_operation_count": 12,
        "retained_first_operation_index": 3,
        "retained_last_operation_index": 12,
        "dropped_operation_count": 2,
        "post_overflow_operation_counts": {"drawImage": 3},
    }

    report = probe.trace_mapping_window_diagnostic(
        trace,
        mapping,
        [mapping_group],
    )

    assert report["renderer_draw_after_overflow"] is True
    assert report["current_mapping_complete_bijection"] is True
    assert report["current_mapping_window_fully_retained"] is True
    assert report["overflow_after_current_mapping"] is True
    assert report["overflow_category"] == "OVERFLOW_AFTER_CURRENT_MAPPING"
    assert report["post_overflow_operation_counts"] == {"drawImage": 3}


def test_renderer_geometry_distinguishes_pure_scale_from_crop() -> None:
    scaled = probe.renderer_geometry_report({
        "source_dimensions": {"width": 100, "height": 200},
        "target_dimensions": {"width": 100, "height": 200},
        "source_rect": {"x": 0, "y": 0, "width": 100, "height": 200},
        "destination": {"x": 0, "y": 0, "width": 50, "height": 100},
        "transform": {"a": 1, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0},
        "global_alpha": 1,
        "global_composite_operation": "source-over",
        "filter": "none",
    })
    cropped = probe.renderer_geometry_report({
        "source_dimensions": {"width": 100, "height": 200},
        "target_dimensions": {"width": 100, "height": 200},
        "source_rect": {"x": 4, "y": 0, "width": 96, "height": 200},
        "destination": {"x": 0, "y": 0, "width": 96, "height": 200},
    })

    assert scaled["classification"] == "PURE_RENDERER_SCALE"
    assert scaled["destination_differs_from_source_dimensions"] is True
    assert cropped["classification"] == "CROP_OR_PIXEL_PROCESSING"
    assert cropped["source_rect_is_full"] is False


def test_part_mapping_uses_object_identity_and_supports_mixed_classification() -> None:
    tile_operations = []
    for source_index, destination_index in enumerate((1, 0, 2, 3)):
        tile_operations.append(
            _trace_tile_operation(
                target_id="source-canvas-a",
                source_id="bitmap-a",
                source_x=(source_index % 2) * 4,
                source_y=(source_index // 2) * 4,
                destination_x=(destination_index % 2) * 4,
                destination_y=(destination_index // 2) * 4,
                tile_size=4,
                target_size=8,
                index=source_index + 1,
            )
        )
    renderer_operation = _trace_tile_operation(
        target_id="renderer",
        source_id="source-canvas-a",
        source_x=0,
        source_y=0,
        destination_x=0,
        destination_y=0,
        tile_size=8,
        target_size=8,
        source_constructor="HTMLCanvasElement",
        index=5,
    )
    native_part = {
        "source_constructor": "HTMLCanvasElement",
        "source_width": 8,
        "source_height": 8,
        "source_rect": {"x": 0, "y": 0, "width": 8, "height": 8},
        "destination": {"x": 0, "y": 0, "width": 8, "height": 8},
    }
    matches = [{
        "source_id": "bitmap-a",
        "source_dimensions": {"width": 8, "height": 8},
        "snapshot_sha256": "snapshot-a",
        "candidate_count_compared": 1,
        "exact_decoded_pixel_match_count": 1,
        "exact_candidate_sha256": ["raw-a"],
        "best_candidates": [],
    }]
    mapping = probe.build_part_mapping_records(
        {"operations": [*tile_operations, renderer_operation]},
        [native_part],
        probe.trace_tile_rearrangement_report({"operations": [*tile_operations, renderer_operation]}),
        matches,
    )[0]

    assert mapping["renderer"]["draw_operation_index"] == 5
    assert mapping["renderer"]["source_canvas_id"] == "source-canvas-a"
    assert mapping["permutation"]["source_id"] == "bitmap-a"
    assert mapping["mapping_status"] == "PART_MAPPING_PROVEN"
    assert probe.classify_part_from_mapping(None, mapping) == "TILE_REARRANGEMENT"
    assert probe.classify_part_from_mapping(
        {"classification": "DIRECT_DECODE"},
        {"mapping_status": "NOT_APPLICABLE"},
    ) == "DIRECT_DECODE"


def test_multiple_imagebitmap_sources_are_not_collapsed_into_one_part() -> None:
    operations = [
        _trace_tile_operation(
            target_id="source-canvas",
            source_id="bitmap-a",
            source_x=0,
            source_y=0,
            destination_x=0,
            destination_y=0,
            tile_size=4,
            target_size=4,
        ),
        _trace_tile_operation(
            target_id="source-canvas",
            source_id="bitmap-b",
            source_x=0,
            source_y=0,
            destination_x=0,
            destination_y=0,
            tile_size=4,
            target_size=4,
            index=2,
        ),
        _trace_tile_operation(
            target_id="renderer",
            source_id="source-canvas",
            source_x=0,
            source_y=0,
            destination_x=0,
            destination_y=0,
            tile_size=4,
            target_size=4,
            source_constructor="HTMLCanvasElement",
            index=3,
        ),
    ]
    native_part = {
        "source_constructor": "HTMLCanvasElement",
        "source_width": 4,
        "source_height": 4,
        "source_rect": {"x": 0, "y": 0, "width": 4, "height": 4},
        "destination": {"x": 0, "y": 0, "width": 4, "height": 4},
    }
    mapping = probe.build_part_mapping_records(
        {"operations": operations},
        [native_part],
        probe.trace_tile_rearrangement_report({"operations": operations}),
        [],
    )[0]

    assert mapping["permutation_group_count"] == 2
    assert mapping["multiple_imagebitmap_sources"] is True
    assert mapping["mapping_status"] == "PART_MAPPING_AMBIGUOUS"
    assert probe.classify_part_from_mapping(None, mapping) == "MULTI_SOURCE_PERMUTATION"


def test_jpeg_mcu_geometry_reads_444_and_420_sampling() -> None:
    image = _gradient(17, 19)
    outputs: dict[int, dict[str, object]] = {}
    for subsampling in (0, 2):
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=90, subsampling=subsampling)
        geometry = probe.jpeg_mcu_geometry(output.getvalue())
        assert geometry is not None
        outputs[subsampling] = geometry

    assert outputs[0]["mcu_width"] == 8
    assert outputs[0]["mcu_height"] == 8
    assert outputs[2]["mcu_width"] == 16
    assert outputs[2]["mcu_height"] == 16
    assert outputs[2]["coded_width"] >= outputs[2]["visible_width"]
    assert outputs[2]["coded_height"] >= outputs[2]["visible_height"]


def test_mcu_alignment_allows_only_visible_edge_padding() -> None:
    image = _gradient(17, 19)
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=90, subsampling=0)
    geometry = probe.jpeg_mcu_geometry(output.getvalue())
    assert geometry is not None
    group = {
        "target_dimensions": {"width": 17, "height": 19},
        "mapping": [{
            "source_x": 0,
            "source_y": 0,
            "destination_x": 0,
            "destination_y": 0,
            "width": 17,
            "height": 19,
        }],
    }

    report = probe.mcu_alignment_report(output.getvalue(), group)

    assert report["all_mapping_mcu_aligned"] is True
    assert report["strict_all_mapping_mcu_aligned"] is False
    assert report["edge_condition"]["right_edge_padding"] > 0
    assert report["edge_condition"]["bottom_edge_padding"] > 0


def test_transformation_safety_separates_clear_background_and_edge_operations() -> None:
    mapping = {
        "renderer": {
            "canvas_id": "renderer",
            "draw_operation_index": 5,
            "destination": {"x": 0, "y": 0, "width": 8, "height": 8},
        },
        "source_canvas": {"canvas_id": "source", "width": 8, "height": 8},
        "permutation": {"first_operation_index": 2},
    }
    trace = {
        "operations": [
            {
                "index": 1,
                "operation": "clearRect",
                "target": {"canvasId": "source"},
                "arguments": [0, 0, 8, 8],
            },
            {
                "index": 2,
                "operation": "drawImage",
                "target": {"canvasId": "source"},
                "source": {"constructor": "ImageBitmap"},
            },
            {
                "index": 3,
                "operation": "fillRect",
                "target": {"canvasId": "renderer"},
                "arguments": [0, 0, 8, 8],
            },
            {
                "index": 4,
                "operation": "fillRect",
                "target": {"canvasId": "renderer"},
                "arguments": [0, 0, 1, 8],
            },
            {
                "index": 5,
                "operation": "drawImage",
                "target": {"canvasId": "renderer"},
                "globalAlpha": 1,
                "globalCompositeOperation": "source-over",
                "filter": "none",
                "transform": {"a": 1, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0},
            },
        ],
    }

    safety = probe.transformation_safety_report(trace, mapping)

    assert safety["source_canvas_initialization_clears"] == [{
        "index": 1,
        "operation": "clearRect",
        "rect": {"x": 0, "y": 0, "width": 8, "height": 8},
    }]
    assert safety["source_canvas_content_writes"] == []
    assert len(safety["renderer_background_operations"]) == 1
    assert len(safety["renderer_edge_operations"]) == 1
    assert safety["renderer_intersecting_content_writes"] == []
    assert safety["additional_pixel_processing"] is False


def test_reload_mapping_comparison_reports_stability_separately() -> None:
    runs = [
        {"pages": [{"page_counter": "1/2", "parts": [{
            "part": 1,
            "raw": {"sha256": "raw-a"},
            "native": {"sha256": "native-a"},
            "mapping_sha256": "mapping-a",
        }]}]},
        {"pages": [{"page_counter": "1/2", "parts": [{
            "part": 1,
            "raw": {"sha256": "raw-a"},
            "native": {"sha256": "native-a"},
            "mapping_sha256": "mapping-a",
        }]}]},
    ]

    comparison = probe.aggregate_reload_comparison(runs)

    assert comparison["classification"] == ["RAW_SAME_NATIVE_SAME"]
    assert comparison["mapping_comparison"] == ["MAPPING_SAME"]
    assert comparison["mapping_comparison_counts"] == {"MAPPING_SAME": 1}


def test_reload_classification_is_deterministic_when_both_hashes_match() -> None:
    assert probe.classify_reload(
        ["raw-a"],
        ["native-a"],
        ["raw-a"],
        ["native-a"],
    ) == ["RAW_SAME_NATIVE_SAME"]
    assert probe.classify_reload(
        ["raw-a"],
        ["native-a"],
        ["raw-a"],
        ["native-b"],
    ) == ["RAW_SAME_NATIVE_DIFFERENT"]


def test_jpeg_marker_metadata_redacts_printable_comment() -> None:
    jpeg = _jpeg_bytes(_gradient(16, 12))
    secret = b"account@example.invalid"
    segment = b"\xff\xfe" + (len(secret) + 2).to_bytes(2, "big") + secret
    marked = jpeg[:2] + segment + jpeg[2:]

    markers = probe.jpeg_marker_metadata(marked)

    comment = next(marker for marker in markers if marker["marker"] == "COM")
    assert comment["printable_string_present"] is True
    assert comment["byte_length"] == len(secret) + 2
    assert "account@example.invalid" not in str(comment)
    assert len(comment["payload_sha256"]) == 64


def test_reload_summary_aggregation_counts_page_classifications() -> None:
    runs = [
        {
            "pages": [
                {
                    "parts": [
                        {
                            "raw": {"sha256": "raw-a"},
                            "native": {"sha256": "native-a"},
                        }
                    ]
                }
            ]
        },
        {
            "pages": [
                {
                    "parts": [
                        {
                            "raw": {"sha256": "raw-a"},
                            "native": {"sha256": "native-b"},
                        }
                    ]
                }
            ]
        },
    ]

    comparison = probe.aggregate_reload_comparison(runs)

    assert comparison["classification"] == ["RAW_SAME_NATIVE_DIFFERENT"]
    assert comparison["classification_counts"] == {
        "RAW_SAME_NATIVE_DIFFERENT": 1
    }
