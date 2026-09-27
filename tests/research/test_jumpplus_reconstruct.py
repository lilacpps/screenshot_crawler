from __future__ import annotations

from pathlib import Path

from PIL import Image

from poc.jumpplus_reconstruct import (
    _candidate_index,
    dct_lossless_feasibility,
    decoded_pixel_sha256,
    reconstruct_canvas,
    reconstruct_jpeg_dct,
    select_transport_candidate,
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
        "source_artifacts": [{"sourceId": 1, "url": "blob:one", "pixel_sha256": source_sha}],
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
            "url": "blob:one",
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
    assert result["status"] in {"likely", "lossless_mapping_complete"}
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


def test_same_source_id_with_different_url_is_rejected(tmp_path: Path) -> None:
    input_dir, output_dir, state, fixture = _fixture(
        tmp_path,
        [_draw(1, (0, 0, 4, 4), (0, 0, 4, 4), source={"sourceId": 1, "url": "blob:two"})],
    )
    result = reconstruct_canvas(
        input_dir=input_dir,
        output_dir=output_dir,
        state=state,
        pixels=fixture["pixels"],
        candidates_by_pixel=_candidate_index(fixture["candidates"]),
    )
    assert result["mapping"]["source_match"] == "changed_after_draw"
    assert result["mapping"]["unmatched_sources"][0]["reason"] == "changed_after_draw"


def test_content_canvas_mutation_is_unsupported(tmp_path: Path) -> None:
    input_dir, output_dir, state, fixture = _fixture(
        tmp_path,
        [_draw(1, (0, 0, 4, 4), (0, 0, 4, 4))],
    )
    state["content_mutations"] = [{"operation": "clearRect", "sequence": 1}]
    result = reconstruct_canvas(
        input_dir=input_dir,
        output_dir=output_dir,
        state=state,
        pixels=fixture["pixels"],
        candidates_by_pixel=_candidate_index(fixture["candidates"]),
    )
    assert result["mapping"]["mapping_status"] == "unsupported"
    assert "unsupported_canvas_mutation" in result["mapping"]["unsupported"]


def test_mcu_alignment_rejects_misaligned_tile(tmp_path: Path) -> None:
    jpeg_path = tmp_path / "aligned.jpg"
    Image.new("L", (16, 16), 128).save(jpeg_path, quality=90)
    result = dct_lossless_feasibility(
        jpeg_bytes=jpeg_path.read_bytes(),
        source_rectangles=[(1, 0, 8, 8)],
        destination_rectangles=[(0, 0, 8, 8)],
        canvas_size=(16, 16),
    )
    assert result["status"] == "infeasible"
    assert result["reason"] == "tile_geometry_not_mcu_aligned"


def test_dct_reorder_preserves_coefficients_and_decoded_pixels(tmp_path: Path) -> None:
    image = Image.new("L", (16, 16))
    for y in range(16):
        for x in range(16):
            image.putpixel((x, y), (x * 11 + y * 7) % 256)
    jpeg_path = tmp_path / "transport.jpg"
    image.save(jpeg_path, quality=90)
    with Image.open(jpeg_path) as source:
        expected = source.convert("RGB").copy()
    tiles = []
    for sy, dy in ((0, 8), (8, 0)):
        tiles.append({
            "sourceRect": {"sx": 0, "sy": sy, "sw": 16, "sh": 8},
            "destinationRect": {"dx": 0, "dy": dy, "dw": 16, "dh": 8},
        })
        expected.paste(source.crop((0, sy, 16, sy + 8)).convert("RGB"), (0, dy))
    png_path = tmp_path / "reconstructed.png"
    expected.save(png_path)
    output_path = tmp_path / "reconstructed.jpg"
    result = reconstruct_jpeg_dct(
        jpeg_bytes=jpeg_path.read_bytes(),
        tile_draws=tiles,
        canvas_size=(16, 16),
        output_path=output_path,
        png_path=png_path,
    )
    assert result["feasibility"]["status"] == "feasible"
    assert result["jpeg_dct_reconstruction"] == "successful"
    assert result["coefficients_equal"] is True
    assert result["decoded_pixel_comparison"]["exact"] is True


def test_candidate_selection_unique() -> None:
    candidate = {"file": "one.jpg", "pixel_sha256": "pixel"}
    result = select_transport_candidate("pixel", [candidate])
    assert result["selection_status"] == "unique"
    assert result["selected_candidate"] is candidate
    assert result["candidate_count"] == 1


def test_candidate_selection_accepts_identical_raw_duplicates() -> None:
    candidates = [
        {"file": "one.jpg", "pixel_sha256": "pixel", "raw_sha256": "same"},
        {"file": "two.jpg", "pixel_sha256": "pixel", "raw_sha256": "same"},
    ]
    result = select_transport_candidate("pixel", candidates, load_bytes=lambda _: b"same")
    assert result["selection_status"] == "equivalent_multiple"
    assert result["selection_reason"] == "identical_raw_sha256"
    assert result["equivalent_candidate_count"] == 2


def test_candidate_selection_accepts_dct_equivalent_distinct_bytes() -> None:
    candidates = [
        {"file": "one.jpg", "pixel_sha256": "pixel", "raw_sha256": "one"},
        {"file": "two.jpg", "pixel_sha256": "pixel", "raw_sha256": "two"},
    ]
    signatures = {
        "one.jpg": {"content_key": (1,), "metadata_key": ("a",)},
        "two.jpg": {"content_key": (1,), "metadata_key": ("b",)},
    }
    result = select_transport_candidate(
        "pixel",
        candidates,
        load_bytes=lambda candidate: candidate["file"].encode(),
        analyze_candidate=lambda candidate, _: signatures[candidate["file"]],
    )
    assert result["selection_status"] == "equivalent_multiple"
    assert result["selection_reason"] == "identical_dct_image_content"
    assert result["metadata_equivalent"] is False


def test_candidate_selection_rejects_dct_distinct_pixel_duplicates() -> None:
    candidates = [
        {"file": "one.jpg", "pixel_sha256": "pixel", "raw_sha256": "one"},
        {"file": "two.jpg", "pixel_sha256": "pixel", "raw_sha256": "two"},
    ]
    result = select_transport_candidate(
        "pixel",
        candidates,
        load_bytes=lambda candidate: candidate["file"].encode(),
        analyze_candidate=lambda candidate, _: {
            "content_key": (candidate["file"],),
            "metadata_key": (),
        },
    )
    assert result["selection_status"] == "ambiguous"
    assert result["selection_reason"] == "multiple_pixel_equal_but_dct_distinct_candidates"
    assert result["selected_candidate"] is None


def test_candidate_selection_parse_failure_is_fail_closed() -> None:
    candidates = [
        {"file": "one.jpg", "pixel_sha256": "pixel", "raw_sha256": "one"},
        {"file": "two.jpg", "pixel_sha256": "pixel", "raw_sha256": "two"},
    ]

    def fail(_: dict, __: bytes) -> dict:
        raise ValueError("invalid JPEG")

    result = select_transport_candidate(
        "pixel",
        candidates,
        load_bytes=lambda candidate: candidate["file"].encode(),
        analyze_candidate=fail,
    )
    assert result["selection_status"] == "ambiguous"
    assert result["selection_reason"] == "candidate_equivalence_unproven"


def test_ambiguous_candidate_uses_pixel_fallback_but_skips_dct(tmp_path: Path) -> None:
    draws = [_draw(1, (0, 0, 4, 4), (0, 0, 4, 4))]
    input_dir, output_dir, state, fixture = _fixture(tmp_path, draws)
    bad_path = input_dir / "network_images" / "not-a-jpeg.jpg"
    bad_path.write_bytes(b"not a jpeg")
    pixel_sha = fixture["candidates"][0]["pixel_sha256"]
    fixture["candidates"].append({
        "file": "network_images/not-a-jpeg.jpg",
        "pixel_sha256": pixel_sha,
        "raw_sha256": "different-raw-bytes",
    })
    result = reconstruct_canvas(
        input_dir=input_dir,
        output_dir=output_dir,
        state=state,
        pixels=fixture["pixels"],
        candidates_by_pixel=_candidate_index(fixture["candidates"]),
    )
    assert result["mapping"]["candidate_selection_statuses"] == ["ambiguous"]
    assert result["mapping"]["pixel_reconstruction"] == "successful"
    assert result["mapping"]["jpeg_dct_reconstruction"] == "not_attempted"
