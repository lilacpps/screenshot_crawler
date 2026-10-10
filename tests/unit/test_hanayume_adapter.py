from __future__ import annotations

import pytest

from screenshot_crawler.core.errors import UnknownPageStateError
from screenshot_crawler.site_adapters.hanayume.adapter import (
    HanayumeAdapter,
    _expected_active_slots,
    _parse_series_ranges,
    _parse_viewer_observation,
)

WORK_ID = "1f9f5b0d4cd52"


@pytest.mark.asyncio
async def test_batch_direct_strategy_uses_the_observed_free_viewer_path() -> None:
    adapter = HanayumeAdapter()

    await adapter.configure_run(None, "direct")

    with pytest.raises(UnknownPageStateError):
        await adapter.configure_run(None, "quota")


def _range_entries(*, selected_page: int | None = None) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for page, (start, end) in enumerate(((1, 30), (31, 31)), start=1):
        entries.append(
            {
                "label": f"{start}-{end}",
                "href": (
                    f"https://hanayume.com/series/{WORK_ID}"
                    if page == selected_page
                    else f"https://hanayume.com/series/{WORK_ID}/{page}"
                ),
                "current": page == selected_page,
            }
        )
    return entries


def _viewer_snapshot(*, current: int = 1, visible: tuple[int, ...] | None = None) -> dict[str, object]:
    total = 9
    body_total = total - 5
    visible = visible if visible is not None else _expected_active_slots(current, body_total)
    viewport = {"width": 1906, "height": 986}
    slots = []
    for index in range(total + 1):
        if index == 0:
            classes = ["-cv-page", "mode-empty", "mode-pr", "mode-top-pr"]
        elif index == total - 4:
            classes = ["-cv-page", "mode-ci"]
        elif index in {total - 3, total - 2}:
            classes = ["-cv-page", "mode-empty", "mode-pr"]
        elif index == total - 1:
            classes = ["-cv-page", "mode-good"]
        elif index == total:
            classes = ["-cv-page", "mode-last"]
        else:
            classes = ["-cv-page"]
            if index in visible:
                classes += ["mode-loaded", "mode-rendered"]
        selected = index in visible and 1 <= index <= body_total
        if selected:
            wrapper_x = 0 if index == current else 100
        elif current > 1 and index == current - 2:
            wrapper_x = viewport["width"] - 15.3333
        else:
            wrapper_x = viewport["width"] + 200 if index > current else -200
        wrapper = [wrapper_x, 0, 100, 100]
        center_x = wrapper_x + wrapper[2] / 2
        center_y = wrapper[1] + wrapper[3] / 2
        slots.append(
            {
                "index": index,
                "classes": classes,
                "wrapper": wrapper,
                "wrapperCenterInViewport": (
                    0 <= center_x <= viewport["width"]
                    and 0 <= center_y <= viewport["height"]
                ),
                "canvasCount": 1 if selected else 0,
                "canvas": (
                    {
                        "width": 5,
                        "height": 7,
                        "ready": True,
                        "visible": True,
                    }
                    if selected
                    else None
                ),
            }
        )
    return {
        "viewerCount": 1,
        "viewerClasses": ["-cv", "mode-spread"],
        "pagesCount": 1,
        "seekCount": 1,
        "currentText": str(current),
        "totalText": str(total),
        "viewport": viewport,
        "seek": {
            "type": "range",
            "min": "1",
            "max": str(total),
            "step": "2",
            "value": str(total - (current - 1)),
        },
        "slots": slots,
    }


def test_hanayume_series_ranges_accept_only_observed_active_alias() -> None:
    initial = _parse_series_ranges(_range_entries(), work_id=WORK_ID)
    selected = _parse_series_ranges(
        _range_entries(selected_page=2),
        work_id=WORK_ID,
        require_selected_page=2,
        actual_page_url=f"https://hanayume.com/series/{WORK_ID}/2",
    )
    assert [(row.page_number, row.start, row.end) for row in initial] == [
        (1, 1, 30),
        (2, 31, 31),
    ]
    assert selected == initial


@pytest.mark.parametrize(
    ("selected_page", "actual_url"),
    [
        (2, f"https://hanayume.com/series/{WORK_ID}/1"),
        (1, f"https://example.com/series/{WORK_ID}/1"),
    ],
)
def test_hanayume_series_ranges_reject_selected_route_or_host_mismatch(
    selected_page: int, actual_url: str
) -> None:
    with pytest.raises(UnknownPageStateError):
        _parse_series_ranges(
            _range_entries(selected_page=selected_page),
            work_id=WORK_ID,
            require_selected_page=selected_page,
            actual_page_url=actual_url,
        )


def test_hanayume_series_ranges_reject_missing_selected_marker_and_range_drift() -> None:
    entries = _range_entries()
    with pytest.raises(UnknownPageStateError):
        _parse_series_ranges(
            entries,
            work_id=WORK_ID,
            require_selected_page=1,
            actual_page_url=f"https://hanayume.com/series/{WORK_ID}/1",
        )
    drifted = _range_entries()
    drifted[1]["label"] = "31-61"
    with pytest.raises(UnknownPageStateError):
        _parse_series_ranges(drifted, work_id=WORK_ID)


def test_hanayume_viewer_accepts_offscreen_loaded_placeholder_but_checks_active_spread() -> None:
    snapshot = _viewer_snapshot()
    slots = snapshot["slots"]
    assert isinstance(slots, list)
    slots[2]["classes"] = ["-cv-page", "mode-loaded"]
    slots[2]["wrapperCenterInViewport"] = False
    slots[2]["canvasCount"] = 0
    slots[2]["canvas"] = None
    observation = _parse_viewer_observation(snapshot)
    assert observation.body_total == 4
    assert observation.active_slots == (1,)
    assert observation.ready_slots == (1,)
    assert _expected_active_slots(3, observation.body_total) == (2, 3)


def test_hanayume_viewer_keeps_observed_loading_placeholder_out_of_ready_pages() -> None:
    snapshot = _viewer_snapshot()
    slots = snapshot["slots"]
    assert isinstance(slots, list)
    slots[2]["classes"] = ["-cv-page", "mode-loading", "mode-req-render"]
    slots[2]["wrapperCenterInViewport"] = False
    slots[2]["canvasCount"] = 0
    slots[2]["canvas"] = None

    observation = _parse_viewer_observation(snapshot)
    assert observation.active_slots == (1,)
    assert observation.ready_slots == (1,)

    slots[2]["classes"] = ["-cv-page", "mode-loading"]
    observation = _parse_viewer_observation(snapshot)
    assert observation.active_slots == (1,)
    assert observation.ready_slots == (1,)

    slots[2]["classes"] = ["-cv-page", "mode-req-render"]
    with pytest.raises(UnknownPageStateError, match="unknown state class"):
        _parse_viewer_observation(snapshot)


def test_hanayume_viewer_rejects_unknown_slot_or_seek_drift() -> None:
    snapshot = _viewer_snapshot()
    slots = snapshot["slots"]
    assert isinstance(slots, list)
    slots[2]["classes"] = ["-cv-page", "mode-sponsored"]
    with pytest.raises(UnknownPageStateError):
        _parse_viewer_observation(snapshot)

    drifted = _viewer_snapshot(current=3)
    seek = drifted["seek"]
    assert isinstance(seek, dict)
    seek["value"] = "9"
    with pytest.raises(UnknownPageStateError):
        _parse_viewer_observation(drifted)


def test_hanayume_viewer_rejects_missing_half_of_a_spread() -> None:
    snapshot = _viewer_snapshot(current=3, visible=(2,))
    observation = _parse_viewer_observation(snapshot)
    assert observation.active_slots == (2,)
    assert observation.ready_slots == (2,)
    assert observation.ready_slots != _expected_active_slots(3, observation.body_total)


def test_hanayume_viewer_keeps_loading_spread_side_active_without_prior_sliver() -> None:
    snapshot = _viewer_snapshot(current=3)
    slots = snapshot["slots"]
    assert isinstance(slots, list)
    # The previous page wrapper intersects by about 15px, but its center and
    # canvas remain outside the viewport.
    assert slots[1]["wrapper"] == [1890.6667, 0, 100, 100]
    assert slots[1]["wrapperCenterInViewport"] is False
    slots[1]["classes"] = ["-cv-page", "mode-loaded", "mode-rendered"]
    slots[1]["canvasCount"] = 1
    slots[1]["canvas"] = {
        "width": 5,
        "height": 7,
        "ready": True,
        "visible": False,
    }
    slots[2]["classes"] = ["-cv-page", "mode-loading", "mode-req-render"]
    slots[2]["canvasCount"] = 0
    slots[2]["canvas"] = None

    observation = _parse_viewer_observation(snapshot)

    assert observation.active_slots == (2, 3)
    assert observation.ready_slots == (3,)
    assert observation.ready_slots != _expected_active_slots(3, observation.body_total)
