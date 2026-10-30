"""BookWalker source-native draw-call selection helpers."""

from __future__ import annotations

from typing import Any


def normalize_destination(
    destination: object,
    *,
    canvas_width: int,
    canvas_height: int,
) -> dict[str, int] | None:
    """Clamp a draw destination to the visible canvas pixel bounds."""

    if not isinstance(destination, dict):
        return None
    try:
        x = round(float(destination["x"]))
        y = round(float(destination["y"]))
        width = round(float(destination["width"]))
        height = round(float(destination["height"]))
    except (KeyError, TypeError, ValueError):
        return None
    left = max(0, x)
    top = max(0, y)
    right = min(canvas_width, x + width)
    bottom = min(canvas_height, y + height)
    if right - left < 100 or bottom - top < 100:
        return None
    return {
        "x": left,
        "y": top,
        "width": right - left,
        "height": bottom - top,
    }


def select_native_draw_calls(
    draw_calls: list[dict[str, Any]],
    *,
    canvas_id: str,
    canvas_width: int,
    canvas_height: int,
    boxes: list[dict[str, int]],
    selection_debug: dict[str, Any] | None = None,
) -> list[dict[str, Any]] | None:
    """Match one stable native source call to every existing page rectangle.

    Repeated calls using the same source object are treated as redraws. If a
    rectangle has multiple distinct source objects, it may be a transition or
    a composition and native capture is rejected conservatively.
    """

    canvas_calls = [
        call for call in draw_calls if call.get("canvasId") == canvas_id
    ]
    calls = [
        call
        for call in canvas_calls
        if normalize_destination(
            call.get("destination"),
            canvas_width=canvas_width,
            canvas_height=canvas_height,
        )
        is not None
    ]
    if selection_debug is not None:
        selection_debug.update(
            {
                "draw_call_count": len(draw_calls),
                "canvas_draw_call_count": len(canvas_calls),
                "normalized_candidate_count": len(calls),
                "normalized_rejected_count": len(canvas_calls) - len(calls),
                "box_count": len(boxes),
                "outcome": "rejected",
                "rejection_branch": None,
                "rejection_box_index": None,
            }
        )
    if not boxes:
        if selection_debug is not None:
            selection_debug["rejection_branch"] = "no_page_boxes"
        return None
    selected: list[dict[str, Any]] = []
    for box_index, box in enumerate(boxes):
        matching = [
            call
            for call in calls
            if normalize_destination(
                call.get("destination"),
                canvas_width=canvas_width,
                canvas_height=canvas_height,
            )
            == box
        ]
        if not matching:
            if selection_debug is not None:
                selection_debug["rejection_branch"] = "no_matching_destination"
                selection_debug["rejection_box_index"] = box_index
            return None
        source_ids = {call.get("sourceId") for call in matching}
        if len(matching) > 1 and (None in source_ids or len(source_ids) != 1):
            if selection_debug is not None:
                selection_debug["rejection_branch"] = "ambiguous_source_id"
                selection_debug["rejection_box_index"] = box_index
            return None
        source_rects = {
            tuple(
                call.get("sourceRect", {}).get(key)
                for key in ("x", "y", "width", "height")
            )
            for call in matching
            if isinstance(call.get("sourceRect"), dict)
        }
        if len(matching) > 1 and len(source_rects) != 1:
            if selection_debug is not None:
                selection_debug["rejection_branch"] = "ambiguous_source_rect"
                selection_debug["rejection_box_index"] = box_index
            return None
        selected.append(matching[-1])
    if len(selected) > 1:
        source_ids = [call.get("sourceId") for call in selected]
        if (
            None in source_ids
            or (
                len(set(source_ids)) != len(source_ids)
                and any(
                    "sourceCropPng" not in call
                    and not call.get("snapshotId")
                    for call in selected
                )
            )
        ):
            if selection_debug is not None:
                selection_debug["rejection_branch"] = "ambiguous_spread_source"
            return None
    if selection_debug is not None:
        selection_debug["outcome"] = "selected"
        selection_debug["selected_count"] = len(selected)
    return selected
