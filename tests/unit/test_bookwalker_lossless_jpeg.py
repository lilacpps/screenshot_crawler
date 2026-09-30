from __future__ import annotations

import io

import pytest
from PIL import Image

from screenshot_crawler.site_adapters.bookwalker.lossless_jpeg import (
    reconstruct_lossless_jpeg,
)
from screenshot_crawler.site_adapters.bookwalker.purchased_mapping import mapping_sha256


def _jpeg(width: int = 32, height: int = 32, *, progressive: bool = False, subsampling: int = 0) -> bytes:
    image = Image.new("RGB", (width, height))
    for y in range(height):
        for x in range(width):
            image.putpixel((x, y), ((x * 17 + y * 3) % 256, (x * 5 + y * 19) % 256, (x * 11 + y * 7) % 256))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90, subsampling=subsampling, progressive=progressive)
    return buffer.getvalue()


def _mapping(width: int = 32, height: int = 32) -> list[dict[str, int]]:
    return [
        {
            "source_x": x,
            "source_y": y,
            "destination_x": x,
            "destination_y": y,
            "width": 16,
            "height": 16,
        }
        for y in range(0, height, 16)
        for x in range(0, width, 16)
    ]


def _mapping_object(mapping: list[dict[str, int]]) -> dict[str, object]:
    return {
        "source_dimensions": {"width": 32, "height": 32},
        "target_dimensions": {"width": 32, "height": 32},
        "tile_dimensions": {"width": 16, "height": 16},
        "mapping_sha256": mapping_sha256(mapping),
        "mapping": mapping,
    }


def test_identity_reconstruction_is_coefficient_exact() -> None:
    data = _jpeg()
    result = reconstruct_lossless_jpeg(data, _mapping_object(_mapping()))

    assert result.available
    assert result.data
    assert result.width == 32 and result.height == 32
    assert result.tile_dimensions == (16, 16)
    assert result.mcu_dimensions == (8, 8)
    assert result.coefficient_validation["mismatched_blocks"] == 0
    assert result.coefficient_validation["mismatched_coefficients"] == 0
    assert result.coefficient_validation["quantization_tables_equal"] is True


def test_two_tile_swap_reconstructs_without_rgb_requantization() -> None:
    mapping = _mapping()
    mapping[0]["destination_x"], mapping[1]["destination_x"] = 16, 0
    result = reconstruct_lossless_jpeg(_jpeg(), _mapping_object(mapping))

    assert result.success
    assert result.coefficient_validation["mismatched_coefficients"] == 0
    assert result.data != _jpeg()


@pytest.mark.parametrize(
    "data,mapping",
    [
        (_jpeg(progressive=True), _mapping_object(_mapping())),
        (_jpeg(subsampling=2), _mapping_object(_mapping())),
        (_jpeg(width=17, height=19), _mapping_object(_mapping(17, 19))),
    ],
    ids=["progressive", "420", "partial-edge"],
)
def test_unsupported_jpeg_layout_returns_no_artifact(data: bytes, mapping: dict[str, object]) -> None:
    result = reconstruct_lossless_jpeg(data, mapping)

    assert not result.available
    assert result.data is None


def test_duplicate_or_gap_mapping_returns_no_artifact() -> None:
    mapping = _mapping()
    mapping[-1] = dict(mapping[0])
    result = reconstruct_lossless_jpeg(_jpeg(), _mapping_object(mapping))

    assert not result.available
    assert result.data is None
