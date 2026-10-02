"""Pure research tests for Comic DAYS native selection and tile provenance."""

from __future__ import annotations

import pytest
from PIL import Image

from poc.comicdays_c1_capture_probe import (
    active_reading_area_indices,
    observed_tile_mapping,
    reconstruct_from_mapping,
    strict_canvas_sequences,
)


def _draws(*, canvas_id: int = 1, include_base: bool = True, source_name: str = "blob:a") -> list[dict]:
    source = {"type": "HTMLImageElement", "width": 1125, "height": 1600, "src": source_name, "currentSrc": source_name}
    draws = []
    if include_base:
        draws.append({"canvas_id": canvas_id, "canvas": {"width": 1125, "height": 1600}, "source": source, "args": [0, 0, 1125, 1600, 0, 0, 1125, 1600], "transform": {"a": 1, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0}, "alpha": 1, "composite": "source-over", "filter": "none"})
    for sy in range(0, 1600, 400):
        for sx in range(0, 1120, 280):
            draws.append({
                "canvas_id": canvas_id,
                "canvas": {"width": 1125, "height": 1600},
                "source": source,
                "args": [sx, sy, 280, 400, sy // 400 * 280, sx // 280 * 400, 280, 400],
                "transform": {"a": 1, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0},
                "alpha": 1,
                "composite": "source-over",
                "filter": "none",
            })
    return draws


def test_runtime_mapping_requires_full_base_and_exact_4x4_tiles() -> None:
    state = {"draws": _draws()}

    mapping = observed_tile_mapping(state, canvas_id=1)

    assert len(mapping) == 16
    assert mapping[0] == [0, 0, 280, 400, 0, 0, 280, 400]
    assert mapping[-1] == [840, 1200, 280, 400, 840, 1200, 280, 400]


def test_runtime_mapping_rejects_incomplete_or_mixed_source() -> None:
    incomplete = {"draws": _draws()[:-1]}
    mixed = {"draws": _draws()[:1] + _draws(source_name="blob:b")[1:]}

    assert strict_canvas_sequences(incomplete) == {}
    assert strict_canvas_sequences(mixed) == {}


def test_runtime_mapping_rejects_unsupported_fifth_tile_column() -> None:
    draws = _draws()
    draws.insert(-1, {
        "canvas_id": 1,
        "canvas": {"width": 1125, "height": 1600},
        "source": draws[1]["source"],
        "args": [1120, 0, 5, 400, 1120, 0, 5, 400],
    })

    assert strict_canvas_sequences({"draws": draws}) == {}


@pytest.mark.parametrize(
    ("field", "value"),
    [("transform", {"a": 2, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0}), ("alpha", 0.5), ("composite", "multiply"), ("filter", "blur(1px)")],
)
def test_runtime_mapping_rejects_unsafe_draw_state(field: str, value: object) -> None:
    draws = _draws()
    draws[1][field] = value

    assert strict_canvas_sequences({"draws": draws}) == {}


def test_runtime_mapping_rejects_fractional_or_duplicate_geometry() -> None:
    fractional = _draws()
    fractional[1]["args"][0] = 0.5
    duplicate = _draws()
    duplicate[-1]["args"][4:6] = [0, 0]

    assert strict_canvas_sequences({"draws": fractional}) == {}
    assert strict_canvas_sequences({"draws": duplicate}) == {}


def test_runtime_mapping_rejects_latest_incomplete_generation_and_in_canvas_mutation() -> None:
    latest_incomplete = _draws() + _draws()[:2]
    mutation = _draws()
    mutation.append({
        **mutation[-1],
        "args": [0, 0, 1, 1, 1, 1, 1, 1],
    })

    assert strict_canvas_sequences({"draws": latest_incomplete}) == {}
    assert strict_canvas_sequences({"draws": mutation}) == {}


def test_runtime_mapping_allows_only_proven_zero_area_spacer_after_tiles() -> None:
    draws = _draws()
    draws.append({
        "canvas_id": 1,
        "canvas": {"width": 1125, "height": 1600},
        "source": {"type": "HTMLImageElement", "width": 10, "height": 10, "src": "spacer", "currentSrc": "spacer"},
        "args": [-1, -1, 1, 1],
        "transform": {"a": 1, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0},
        "alpha": 1,
        "composite": "source-over",
        "filter": "none",
    })

    assert len(strict_canvas_sequences({"draws": draws})) == 1

    moved_spacer = {**draws[-1], "transform": {"a": 1, "b": 0, "c": 0, "d": 1, "e": 100, "f": 100}}
    assert strict_canvas_sequences({"draws": draws[:-1] + [moved_spacer]}) == {}


def test_reconstruction_preserves_untiled_right_edge() -> None:
    sequence = strict_canvas_sequences({"draws": _draws()})[1]
    source = Image.new("RGB", (1125, 1600), (10, 20, 30))
    for x in range(1120, 1125):
        for y in range(1600):
            source.putpixel((x, y), (240, 10, 20))

    reconstructed = reconstruct_from_mapping(source, sequence)

    assert reconstructed.getpixel((1124, 800)) == (240, 10, 20)


def test_active_area_selection_excludes_ad_prefetch_and_terminal_slots() -> None:
    areas = [
        {"index": 0, "canvas_count": 0, "image_count": 1, "id": None},
        {"index": 1, "canvas_count": 1, "image_count": 0, "id": None},
        {"index": 2, "canvas_count": 1, "image_count": 0, "id": None},
        {"index": 3, "canvas_count": 1, "image_count": 0, "id": None},
        {"index": 32, "canvas_count": 1, "image_count": 0, "id": None},
        {"index": 33, "canvas_count": 0, "image_count": 2, "id": None},
        {"index": 34, "canvas_count": 0, "image_count": 0, "id": None},
        {"index": 35, "canvas_count": 0, "image_count": 10, "id": "viewer-colophon"},
    ]

    assert active_reading_area_indices({"slider_now": "1", "areas": areas}) == [1]
    assert active_reading_area_indices({"slider_now": "3", "areas": areas}) == [2, 3]
    assert active_reading_area_indices({"slider_now": "33", "areas": areas}) == [32]
    assert active_reading_area_indices({"slider_now": "35", "areas": areas}) == []
