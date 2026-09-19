from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from diagnose_bookwalker_native_source import select_final_draw_calls

from screenshot_crawler.site_adapters.bookwalker.native_capture import (
    normalize_destination,
    select_native_draw_calls,
)


def _call(x: int, width: int, *, timestamp: int, source_width: int) -> dict:
    return {
        "timestamp": timestamp,
        "canvasId": "content",
        "destination": {"x": x, "y": 0, "width": width, "height": 1479},
        "source": {"width": source_width, "height": 2048},
    }


def test_select_final_draw_calls_prefers_latest_transition_call() -> None:
    calls = [
        _call(900, 941, timestamp=1, source_width=1303),
        _call(900, 941, timestamp=2, source_width=1303),
    ]

    selected = select_final_draw_calls(calls, "content")

    assert selected == [calls[-1]]


def test_select_final_draw_calls_keeps_spread_in_right_to_left_order() -> None:
    right = _call(1429, 941, timestamp=1, source_width=1303)
    left = _call(488, 941, timestamp=2, source_width=1303)

    selected = select_final_draw_calls([left, right], "content")

    assert selected == [right, left]


def test_select_final_draw_calls_ignores_other_canvas() -> None:
    target = _call(900, 941, timestamp=1, source_width=1303)
    other = _call(900, 941, timestamp=2, source_width=960)
    other["canvasId"] = "offscreen"

    selected = select_final_draw_calls([target, other], "content")

    assert selected == [target]


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
