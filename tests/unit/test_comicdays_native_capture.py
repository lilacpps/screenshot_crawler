import io

from PIL import Image

from screenshot_crawler.site_adapters.comicdays.native_capture import (
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
