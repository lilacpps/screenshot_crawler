from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import jpeglib
import numpy as np
import pytest
from PIL import Image

SCRIPT_PATH = (
    Path(__file__).parents[2]
    / "scripts"
    / "poc_bookwalker_lossless_jpeg_rearrange.py"
)
SPEC = importlib.util.spec_from_file_location(
    "poc_bookwalker_lossless_jpeg_rearrange",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
poc = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = poc
SPEC.loader.exec_module(poc)


def _source_image(width: int, height: int) -> Image.Image:
    image = Image.new("RGB", (width, height))
    pixels = image.load()
    for y in range(height):
        for x in range(width):
            pixels[x, y] = (
                (x * 17 + y * 3) % 256,
                (x * 5 + y * 19) % 256,
                (x * 11 + y * 7) % 256,
            )
    return image


def _write_source(path: Path, width: int, height: int, *, progressive: bool = False) -> None:
    # Pillow is only used to make a synthetic source fixture, never for PoC output.
    image = _source_image(width, height)
    image.save(path, format="JPEG", quality=90, subsampling=0, progressive=progressive)


def _mapping(width: int, height: int, tile_width: int, tile_height: int) -> list[dict[str, int]]:
    return [
        {
            "source_x": x,
            "source_y": y,
            "destination_x": x,
            "destination_y": y,
            "width": tile_width,
            "height": tile_height,
        }
        for y in range(0, height, tile_height)
        for x in range(0, width, tile_width)
    ]


def _swap_first_two(mapping: list[dict[str, int]]) -> list[dict[str, int]]:
    swapped = [dict(item) for item in mapping]
    first = swapped[0]
    second = swapped[1]
    first["destination_x"], second["destination_x"] = (
        second["destination_x"],
        first["destination_x"],
    )
    return swapped


def _cycle_four(mapping: list[dict[str, int]]) -> list[dict[str, int]]:
    cycled = [dict(item) for item in mapping]
    destinations = [
        (mapping[1]["destination_x"], mapping[1]["destination_y"]),
        (mapping[3]["destination_x"], mapping[3]["destination_y"]),
        (mapping[2]["destination_x"], mapping[2]["destination_y"]),
        (mapping[0]["destination_x"], mapping[0]["destination_y"]),
    ]
    for item, (x, y) in zip(cycled[:4], destinations, strict=True):
        item["destination_x"] = x
        item["destination_y"] = y
    return cycled


def _expected_tile_image(
    source: Image.Image,
    mapping: list[dict[str, int]],
) -> Image.Image:
    expected = Image.new("RGB", source.size)
    for item in mapping:
        tile = source.crop((
            item["source_x"],
            item["source_y"],
            item["source_x"] + item["width"],
            item["source_y"] + item["height"],
        ))
        expected.paste(tile, (item["destination_x"], item["destination_y"]))
    return expected


def _run_mapping(
    tmp_path: Path,
    mapping: list[dict[str, int]],
    *,
    width: int,
    height: int,
) -> tuple[Path, dict[str, object]]:
    source_path = tmp_path / "source.jpg"
    output_path = tmp_path / "reconstructed.jpg"
    _write_source(source_path, width, height)
    result = poc._write_reconstructed_jpeg(source_path, output_path, mapping)
    result["output_dct"].close()
    result["source_dct"].close()
    return output_path, result


def test_baseline_structure_and_metadata_parser(tmp_path: Path) -> None:
    source_path = tmp_path / "source.jpg"
    _write_source(source_path, 32, 32)
    data = source_path.read_bytes()
    parsed = poc.parse_jpeg_structure(data)

    assert parsed["sof_marker"] == "SOF0"
    assert parsed["progressive"] is False
    assert parsed["width"] == 32
    assert parsed["height"] == 32
    assert parsed["components"] == [
        {"id": 1, "h_sampling_factor": 1, "v_sampling_factor": 1, "quantization_table_id": 0},
        {"id": 2, "h_sampling_factor": 1, "v_sampling_factor": 1, "quantization_table_id": 1},
        {"id": 3, "h_sampling_factor": 1, "v_sampling_factor": 1, "quantization_table_id": 1},
    ]
    assert parsed["quantization_tables"]
    assert all("payload_sha256" in segment for segment in parsed["segments"])
    assert all("printable_string_present" in segment for segment in parsed["segments"])


def test_identity_mapping_preserves_coefficients_and_pixels(tmp_path: Path) -> None:
    mapping = _mapping(32, 32, 16, 16)
    output_path, result = _run_mapping(tmp_path, mapping, width=32, height=32)

    assert result["coefficients"]["mismatched_coefficients"] == 0
    assert result["coefficients"]["coefficient_values_checked"] == 3 * 16 * 64
    with Image.open(tmp_path / "source.jpg") as source, Image.open(output_path) as output:
        assert np.array_equal(np.asarray(source), np.asarray(output))


@pytest.mark.parametrize(
    ("width", "height", "mapping_factory"),
    [
        (32, 16, lambda mapping: _swap_first_two(mapping)),
        (64, 64, lambda mapping: _cycle_four(mapping)),
    ],
    ids=["two-tile-swap", "four-tile-cycle"],
)
def test_tile_permutations_are_reconstructed_without_requantization(
    tmp_path: Path,
    width: int,
    height: int,
    mapping_factory: object,
) -> None:
    base_mapping = _mapping(width, height, 16, 16)
    mapping = mapping_factory(base_mapping)
    output_path, result = _run_mapping(
        tmp_path,
        mapping,
        width=width,
        height=height,
    )

    assert result["coefficients"]["mismatched_blocks"] == 0
    assert result["coefficients"]["mismatched_coefficients"] == 0
    with Image.open(tmp_path / "source.jpg") as source:
        expected = _expected_tile_image(source.convert("RGB"), mapping)
    with Image.open(output_path) as output:
        assert np.array_equal(np.asarray(expected), np.asarray(output.convert("RGB")))


def _fake_part_mapping(
    raw_path: Path,
    mapping: list[dict[str, int]],
    *,
    width: int = 32,
    height: int = 32,
    progressive: bool = False,
) -> dict[str, object]:
    raw_bytes = raw_path.read_bytes()
    return {
        "part": 1,
        "mapping_status": "PART_MAPPING_PROVEN",
        "readiness": "LOSSLESS_JPEG_REARRANGEMENT_READY",
        "permutation": {
            "complete_bijection": True,
            "source_dimensions": {"width": width, "height": height},
            "target_dimensions": {"width": width, "height": height},
            "tile_dimensions": {"width": 16, "height": 16},
            "mapping_sha256": poc.mapping_sha256(mapping),
            "mapping": mapping,
        },
        "raw_jpeg": {
            "sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "decoded_pixel_exact_match": True,
            "dimensions": {"width": width, "height": height},
        },
        "imagebitmap": {
            "exact_decoded_pixel_match_count": 1,
            "dimensions": {"width": width, "height": height},
        },
        "safety": {"additional_pixel_processing": False},
        "mcu_alignment": {"strict_all_mapping_mcu_aligned": True},
        "synthetic_progressive": progressive,
    }


@pytest.mark.parametrize(
    "mutator",
    [
        lambda mapping: mapping[:-1],  # gap
        lambda mapping: mapping[:1] + [dict(mapping[0])] + mapping[2:],  # duplicate source/dest
        lambda mapping: [dict(mapping[0], source_x=40)],  # out of bounds / incomplete
        lambda mapping: [dict(mapping[0], source_x=1)],  # non-MCU aligned
        lambda mapping: [dict(mapping[0], width=24)],  # non-strict edge/tile
    ],
    ids=["gap", "duplicate", "out-of-bounds", "non-mcu", "non-strict"],
)
def test_invalid_mapping_fails_closed(tmp_path: Path, mutator: object) -> None:
    source_path = tmp_path / "source.jpg"
    _write_source(source_path, 32, 32)
    mapping = mutator(_mapping(32, 32, 16, 16))
    dct = jpeglib.read_dct(str(source_path))
    try:
        with pytest.raises(poc.PocFailure) as failure:
            poc.validate_mapping(
                _fake_part_mapping(source_path, mapping),
                dct=dct,
                parsed=poc.parse_jpeg_structure(source_path.read_bytes()),
            )
    finally:
        dct.close()
    assert failure.value.status == "UNSAFE_MAPPING"
    assert not (tmp_path / "reconstructed.jpg").exists()


def test_dimensions_mismatch_fails_closed(tmp_path: Path) -> None:
    source_path = tmp_path / "source.jpg"
    _write_source(source_path, 32, 32)
    part_mapping = _fake_part_mapping(source_path, _mapping(32, 32, 16, 16))
    part_mapping["permutation"]["target_dimensions"] = {"width": 16, "height": 32}
    dct = jpeglib.read_dct(str(source_path))
    try:
        with pytest.raises(poc.PocFailure) as failure:
            poc.validate_mapping(
                part_mapping,
                dct=dct,
                parsed=poc.parse_jpeg_structure(source_path.read_bytes()),
            )
    finally:
        dct.close()
    assert failure.value.status == "UNSAFE_MAPPING"


def test_progressive_jpeg_is_rejected_without_output(tmp_path: Path) -> None:
    raw_path = tmp_path / "raw.jpg"
    native_path = tmp_path / "native.png"
    output_path = tmp_path / "reconstructed.jpg"
    _write_source(raw_path, 32, 32, progressive=True)
    _source_image(32, 32).save(native_path, format="PNG")
    mapping = _mapping(32, 32, 16, 16)
    (tmp_path / "part-mappings.json").write_text(
        json.dumps([_fake_part_mapping(raw_path, mapping, progressive=True)]),
        encoding="utf-8",
    )
    (tmp_path / "metadata.json").write_text(
        json.dumps({
            "parts": [{
                "part": 1,
                "raw": {"file": raw_path.name},
                "native": {"file": native_path.name},
            }]
        }),
        encoding="utf-8",
    )

    summary = poc.run_poc(
        page_dir=tmp_path,
        part_number=1,
        output_path=output_path,
    )

    assert summary["final_status"] == "UNSUPPORTED_JPEG_LAYOUT"
    assert not output_path.exists()
