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
