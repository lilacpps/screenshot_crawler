import io

import pytest
from PIL import Image

from screenshot_crawler.site_adapters.comicdays.native_capture import (
    _jpeg_header,
    _jpeg_normalize_writer_metadata,
    reconstruct_jpeg,
    reconstruct_png,
    strict_canvas_sequence,
)


def _row(*, mutation: bool = False) -> dict:
    safe = {"a": 1, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0, "alpha": 1, "composite": "source-over", "filter": "none"}
    def draw(args: list[int], seq: int) -> dict:
        return {"sequence": seq, "sourceId": 1, "sourceUrl": "blob:x", "args": args, "state": safe}
    base = {**draw([0, 0, 11, 8, 0, 0, 11, 8], 1), "canvasWidth": 11, "canvasHeight": 8, "source": {"id": 1, "width": 11, "height": 8}}
    # Runtime order transposes the 4x4 tile grid; the untiled edge is
    # represented by the base draw and is intentionally distinctive below.
    tiles = []
    sequence = 2
    for dest_y in range(4):
        for dest_x in range(4):
            tiles.append(draw([dest_y * 2, dest_x * 2, 2, 2, dest_x * 2, dest_y * 2, 2, 2], sequence))
            sequence += 1
    return {"canvasWidth": 11, "canvasHeight": 8, "base": base, "mapping": tiles, "mutations": [{"operation": "fillRect"}] if mutation else []}


def test_strict_sequence_requires_safe_complete_mapping() -> None:
    plan = strict_canvas_sequence(_row())
    assert plan is not None and len(plan["tiles"]) == 16
    assert strict_canvas_sequence(_row(mutation=True)) is None


def test_reconstruct_png_preserves_source_pixels() -> None:
    image = Image.new("RGB", (11, 8))
    for y in range(8):
        for x in range(10):
            image.putpixel((x, y), (10 + 20 * (x // 2), 20 + 20 * (y // 2), 30 + 5 * (x // 2 + y // 2)))
    for y in range(8):
        image.putpixel((10, y), (17, 19, 23))
    data = io.BytesIO(); image.save(data, format="PNG")
    result = reconstruct_png(data.getvalue(), strict_canvas_sequence(_row()) or {})
    assert result is not None and result.width == 11 and result.height == 8
    restored = Image.open(io.BytesIO(result.data)).convert("RGB")
    assert restored.getpixel((1, 1)) == (10, 20, 30)
    assert restored.getpixel((1, 3)) == (30, 20, 35)
    assert restored.getpixel((3, 1)) == (10, 40, 35)
    assert restored.getpixel((10, 7)) == (17, 19, 23)


def test_strict_sequence_rejects_mixed_source_duplicate_and_unsafe_state() -> None:
    mixed = _row(); mixed["mapping"][0]["sourceId"] = 2
    duplicate = _row(); duplicate["mapping"][1]["args"][4:8] = [0, 0, 5, 5]
    unsafe = _row(); unsafe["mapping"][0]["state"]["alpha"] = 0.5
    resized = _row(); resized["mutations"] = [{"operation": "resize"}]
    assert strict_canvas_sequence(mixed) is None
    assert strict_canvas_sequence(duplicate) is None
    assert strict_canvas_sequence(unsafe) is None
    assert strict_canvas_sequence(resized) is None


def test_strict_sequence_rejects_incomplete_latest_generation() -> None:
    value = _row(); value["mapping"] = value["mapping"][:3]
    assert strict_canvas_sequence(value) is None


def test_strict_sequence_keeps_persistent_mutation_boundary_after_trace_eviction() -> None:
    before_base = _row(); before_base["unsafeSequence"] = 0
    after_base = _row(); after_base["unsafeSequence"] = after_base["base"]["sequence"]
    assert strict_canvas_sequence(before_base) is not None
    assert strict_canvas_sequence(after_base) is None


def test_strict_sequence_rejects_missing_column_and_fractional_geometry() -> None:
    missing = _row(); missing["mapping"] = [item for item in missing["mapping"] if item["args"][4] != 6]
    fractional = _row(); fractional["mapping"][0]["args"][4] = 0.5
    assert strict_canvas_sequence(missing) is None
    assert strict_canvas_sequence(fractional) is None


def _jpeg_row(*, subsampling: int = 0, progressive: bool = False) -> tuple[dict, bytes]:
    image = Image.new("RGB", (1125, 1600))
    for y in range(1600):
        for x in range(1125):
            image.putpixel((x, y), ((x // 32) % 256, (y // 32) % 256, (x + y) % 256))
    data = io.BytesIO()
    image.save(data, format="JPEG", quality=85, subsampling=subsampling, progressive=progressive)
    safe = {"a": 1, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0, "alpha": 1, "composite": "source-over", "filter": "none"}
    source_url = "blob:comicdays-jpeg"
    def draw(args: list[int], sequence: int) -> dict:
        return {
            "sequence": sequence,
            "canvasWidth": 1125,
            "canvasHeight": 1600,
            "sourceId": 1,
            "sourceUrl": source_url,
            "source": {"id": 1, "url": source_url, "width": 1125, "height": 1600},
            "args": args,
            "state": safe,
        }
    base = draw([0, 0, 1125, 1600, 0, 0, 1125, 1600], 1)
    tiles = []
    sequence = 2
    for dest_y in range(4):
        for dest_x in range(4):
            tiles.append(draw([dest_y * 280, dest_x * 400, 280, 400, dest_x * 280, dest_y * 400, 280, 400], sequence))
            sequence += 1
    return {"canvasWidth": 1125, "canvasHeight": 1600, "base": base, "mapping": tiles, "mutations": []}, data.getvalue()


def test_reconstruct_jpeg_preserves_coefficients_and_edge() -> None:
    row, source = _jpeg_row()
    plan = strict_canvas_sequence(row)
    assert plan is not None
    result = reconstruct_jpeg(source, plan)
    assert result is not None
    assert result.mime_type == "image/jpeg"
    assert result.file_extension == ".jpg"
    assert Image.open(io.BytesIO(result.data)).size == (1125, 1600)


@pytest.mark.parametrize("subsampling", [1, 2])
def test_unsupported_sampling_uses_png_reconstruction_fallback(subsampling: int) -> None:
    row, source = _jpeg_row(subsampling=subsampling)
    plan = strict_canvas_sequence(row)
    assert plan is not None
    assert reconstruct_jpeg(source, plan) is None
    png = reconstruct_png(source, plan)
    assert png is not None and png.mime_type == "image/png"


def test_reconstruct_jpeg_rejects_unsupported_subsampling() -> None:
    row, source = _jpeg_row(subsampling=2)
    plan = strict_canvas_sequence(row)
    assert plan is not None
    assert reconstruct_jpeg(source, plan) is None


def test_reconstruct_jpeg_rejects_progressive_source() -> None:
    row, source = _jpeg_row(progressive=True)
    plan = strict_canvas_sequence(row)
    assert plan is not None
    assert reconstruct_jpeg(source, plan) is None
    png = reconstruct_png(source, plan)
    assert png is not None and png.mime_type == "image/png"


def test_reconstruct_jpeg_rejects_malformed_source() -> None:
    row, _ = _jpeg_row()
    plan = strict_canvas_sequence(row)
    assert plan is not None
    assert reconstruct_jpeg(b"not-a-jpeg", plan) is None


def _insert_after_soi(data: bytes, marker: int, payload: bytes) -> bytes:
    segment = bytes((0xFF, marker)) + (len(payload) + 2).to_bytes(2, "big") + payload
    return data[:2] + segment + data[2:]


def test_jpeg_metadata_normalizer_allows_only_one_observed_duplicate_app0() -> None:
    _, source = _jpeg_row()
    header = _jpeg_header(source)
    assert header is not None
    app0 = next(item["payload"] for item in header["records"] if item["marker"] == 0xE0)
    generated = _insert_after_soi(source, 0xE0, app0)
    assert _jpeg_normalize_writer_metadata(source, generated) == source

    original_duplicate = _insert_after_soi(source, 0xE0, app0)
    generated_duplicate = _insert_after_soi(original_duplicate, 0xE0, app0)
    assert _jpeg_normalize_writer_metadata(original_duplicate, generated_duplicate) == original_duplicate


def test_jpeg_metadata_normalizer_rejects_unknown_or_changed_markers() -> None:
    _, source = _jpeg_row()
    header = _jpeg_header(source)
    assert header is not None
    app0 = next(item["payload"] for item in header["records"] if item["marker"] == 0xE0)
    assert _jpeg_normalize_writer_metadata(source, _insert_after_soi(source, 0xE1, b"unknown")) is None
    changed = _insert_after_soi(source, 0xE0, app0[:-1] + b"X")
    assert _jpeg_normalize_writer_metadata(source, changed) is None
    assert _jpeg_header(source[:-2]) is None


def test_reconstruct_jpeg_rejects_postscan_metadata_marker() -> None:
    row, source = _jpeg_row()
    plan = strict_canvas_sequence(row)
    assert plan is not None
    postscan = b"\xff\xfe\x00\x06after"  # COM after SOS entropy is unsupported.
    assert reconstruct_jpeg(source[:-2] + postscan + source[-2:], plan) is None


def test_reconstruct_jpeg_rejects_direct_incomplete_plan() -> None:
    _, source = _jpeg_row()
    assert reconstruct_jpeg(source, {"width": 1125, "height": 1600, "tiles": []}) is None
