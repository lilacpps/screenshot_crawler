from poc.bookwalker.diagnose_bookwalker_native_source import select_final_draw_calls


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
