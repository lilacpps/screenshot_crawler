from __future__ import annotations

from screenshot_crawler.site_adapters.bookwalker.native_capture import (
    normalize_destination,
    select_native_draw_calls,
)


def _native_call(
    *,
    x: int,
    source_id: str,
    source_width: int = 960,
    source_height: int = 1280,
    destination_width: int = 960,
    destination_height: int = 1280,
) -> dict:
    return {
        "canvasId": "content",
        "sourceId": source_id,
        "destination": {
            "x": x,
            "y": 0,
            "width": destination_width,
            "height": destination_height,
        },
        "sourceRect": {
            "x": 0,
            "y": 0,
            "width": source_width,
            "height": source_height,
        },
    }


def test_normalize_destination_clips_to_canvas() -> None:
    assert normalize_destination(
        {"x": -10, "y": 0, "width": 970, "height": 1280},
        canvas_width=960,
        canvas_height=1280,
    ) == {"x": 0, "y": 0, "width": 960, "height": 1280}


def test_select_native_draw_calls_keeps_latest_same_source_and_box_order() -> None:
    right = _native_call(x=960, source_id="right")
    right_redraw = _native_call(x=960, source_id="right")
    left = _native_call(x=0, source_id="left")

    selected = select_native_draw_calls(
        [left, right, right_redraw],
        canvas_id="content",
        canvas_width=1920,
        canvas_height=1280,
        boxes=[
            {"x": 960, "y": 0, "width": 960, "height": 1280},
            {"x": 0, "y": 0, "width": 960, "height": 1280},
        ],
    )

    assert selected == [right_redraw, left]


def test_select_native_draw_calls_rejects_distinct_sources_for_one_box() -> None:
    first = _native_call(x=0, source_id="first")
    second = _native_call(x=0, source_id="second")

    assert select_native_draw_calls(
        [first, second],
        canvas_id="content",
        canvas_width=960,
        canvas_height=1280,
        boxes=[{"x": 0, "y": 0, "width": 960, "height": 1280}],
    ) is None


def test_select_native_draw_calls_rejects_atlas_rect_changes_for_one_box() -> None:
    first = _native_call(x=0, source_id="atlas", source_width=2048)
    second = _native_call(x=0, source_id="atlas", source_width=2048)
    second["sourceRect"]["x"] = 960

    assert select_native_draw_calls(
        [first, second],
        canvas_id="content",
        canvas_width=960,
        canvas_height=1280,
        boxes=[{"x": 0, "y": 0, "width": 960, "height": 1280}],
    ) is None
