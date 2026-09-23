from __future__ import annotations

from pathlib import Path

from PIL import Image

from poc.jumpplus_reconstruct import (
    _candidate_index,
    decoded_pixel_sha256,
    reconstruct_canvas,
)


def _fixture(tmp_path: Path, draw_calls: list[dict], source_sha: str = "source-sha") -> tuple[Path, Path, dict, dict]:
    input_dir = tmp_path / "input"
    network_dir = input_dir / "network_images"
    state_dir = input_dir / "j1" / "state_000"
    network_dir.mkdir(parents=True)
    state_dir.mkdir(parents=True)
    transport = Image.new("RGB", (4, 4), (255, 0, 0))
    transport.putpixel((0, 0), (0, 255, 0))
    transport_path = network_dir / "transport.jpg"
    transport.save(transport_path, quality=100, subsampling=0)
    with Image.open(transport_path) as decoded:
        actual_sha = decoded_pixel_sha256(decoded)
    canvas_reference = state_dir / "canvas.png"
    canvas_reference.write_bytes(transport_path.read_bytes())
    pixels = {
        "canvas_artifacts": [{"canvasId": 3, "file": "j1/state_000/canvas.png"}],
        "source_artifacts": [{"sourceId": 1, "pixel_sha256": source_sha}],
    }
    candidates = [{"file": "network_images/transport.jpg", "pixel_sha256": actual_sha}]
    if source_sha == "source-sha":
        pixels["source_artifacts"][0]["pixel_sha256"] = actual_sha
    state = {
        "state": "state_000",
        "canvas_id": 3,
        "canvas_dimensions": [4, 4],
        "draw_calls": draw_calls,
    }
    return input_dir, tmp_path / "j2", state, {"pixels": pixels, "candidates": candidates}


def _draw(sequence: int, source_rect: tuple[int, int, int, int], destination: tuple[int, int, int, int], **extra) -> dict:
    return {
        "sequence": sequence,
        "canvas": {"id": 3, "width": 4, "height": 4},
        "source": {
            "sourceId": 1,
            "type": "HTMLImageElement",
            "naturalWidth": 4,
            "naturalHeight": 4,
        },
        "argumentForm": "9-argument",
        "sourceRect": dict(zip(("sx", "sy", "sw", "sh"), source_rect)),
        "destinationRect": dict(zip(("dx", "dy", "dw", "dh"), destination)),
        "transform": {"a": 1, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0},
        "globalCompositeOperation": "source-over",
        "filter": "none",
        "globalAlpha": 1,
        **extra,
    }


def test_reconstructs_crop_paste_and_preserves_draw_order(tmp_path: Path) -> None:
    draws = [
        _draw(10, (0, 0, 4, 4), (0, 0, 4, 4)),
        _draw(11, (0, 0, 2, 2), (2, 2, 2, 2)),
    ]
    input_dir, output_dir, state, fixture = _fixture(tmp_path, draws)
    result = reconstruct_canvas(
        input_dir=input_dir,
        output_dir=output_dir,
        state=state,
        pixels=fixture["pixels"],
        candidates_by_pixel=_candidate_index(fixture["candidates"]),
    )
    assert result["status"] == "confirmed"
    assert result["mapping"]["draw_count_applied"] == 2
    with (
        Image.open(output_dir / "state_000" / "canvas_03_reconstructed.png") as image,
        Image.open(input_dir / "network_images" / "transport.jpg") as expected,
    ):
        assert image.convert("RGB").getpixel((2, 2)) == expected.convert("RGB").getpixel((0, 0))
        assert image.convert("RGB").getpixel((0, 3)) == expected.convert("RGB").getpixel((0, 3))


def test_unmatched_source_is_not_confirmed(tmp_path: Path) -> None:
    input_dir, output_dir, state, fixture = _fixture(
        tmp_path,
        [_draw(1, (0, 0, 4, 4), (0, 0, 4, 4))],
        source_sha="missing-sha",
    )
    result = reconstruct_canvas(
        input_dir=input_dir,
        output_dir=output_dir,
        state=state,
        pixels=fixture["pixels"],
        candidates_by_pixel=_candidate_index(fixture["candidates"]),
    )
    assert result["status"] == "inconclusive"
    assert result["mapping"]["unmatched_sources"][0]["reason"] == "unmatched_source"


def test_scaling_is_explicitly_unsupported_for_lossless_path(tmp_path: Path) -> None:
    input_dir, output_dir, state, fixture = _fixture(
        tmp_path,
        [_draw(1, (0, 0, 2, 2), (0, 0, 1, 1))],
    )
    result = reconstruct_canvas(
        input_dir=input_dir,
        output_dir=output_dir,
        state=state,
        pixels=fixture["pixels"],
        candidates_by_pixel=_candidate_index(fixture["candidates"]),
    )
    assert result["status"] == "inconclusive"
    assert any(item["reason"] == "scaled_draw_observed" for item in result["mapping"]["unsupported"])
