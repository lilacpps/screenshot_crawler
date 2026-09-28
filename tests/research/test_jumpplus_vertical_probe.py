from __future__ import annotations

import pytest

from poc.jumpplus_vertical_probe import (
    geometry_order,
    loaded_content_count,
    next_content_reached,
    operation_key,
    recommend_navigation,
    scroll_delta,
)


def _snapshot(*, window_y: int, active: list[int], regions: list[dict]) -> dict:
    return {
        "scroll": {
            "windowX": 0,
            "windowY": window_y,
            "scrollingElement": {"scrollTop": window_y},
            "candidates": [
                {"name": "content", "scrollTop": 0},
                {"name": "vertical_inner", "scrollTop": 0},
            ],
        },
        "activeRegions": active,
        "regions": regions,
    }


def test_operation_aliases_are_bounded_and_normalized() -> None:
    assert operation_key("ArrowDown") == "ArrowDown"
    assert operation_key("page-down") == "PageDown"
    assert operation_key("scroll_into_view") == "scrollIntoView"
    with pytest.raises(ValueError):
        operation_key("click-forward")


def test_geometry_order_excludes_non_content_regions() -> None:
    snapshot = {
        "regions": [
            {"index": 1, "isContentPage": True, "renderedRect": {"top": 1400}},
            {"index": 99, "isContentPage": False, "renderedRect": {"top": 2800}},
            {"index": 0, "isContentPage": True, "renderedRect": {"top": 0}},
        ]
    }
    assert geometry_order(snapshot) == [0, 1]


def test_scroll_delta_and_next_content_are_geometry_signals() -> None:
    regions = [
        {"index": 0, "isContentPage": True},
        {"index": 1, "isContentPage": True},
    ]
    before = _snapshot(window_y=0, active=[0], regions=regions)
    after = _snapshot(window_y=862, active=[0, 1], regions=regions)
    assert scroll_delta(before, after)["window_y"] == 862
    assert next_content_reached(before, after) is True


def test_loaded_content_count_ignores_back_matter_images() -> None:
    snapshot = {
        "regions": [
            {"isContentPage": True, "image": {"tag": "canvas", "width": 575, "height": 1400}},
            {"isContentPage": True, "image": {"tag": "canvas", "width": 0, "height": 0}},
            {"isContentPage": False, "image": {"tag": "img", "complete": True, "naturalWidth": 380}},
        ]
    }
    assert loaded_content_count(snapshot) == 1


def test_navigation_recommendation_does_not_treat_arrow_down_as_one_page() -> None:
    recommendation = recommend_navigation(
        [
            {"operation": "ArrowDown", "status": "observed", "stable": True, "next_content_reached": False},
            {"operation": "scrollIntoView", "status": "observed", "stable": True, "next_content_reached": True, "active_after_count": 1},
            {"operation": "PageDown", "status": "observed", "stable": True, "next_content_reached": True, "active_after_count": 2},
        ]
    )
    assert recommendation["primary"] == "scrollIntoView(target content image)"
    assert recommendation["fallback"] == "PageDown"
    assert recommendation["do_not_use"] == ["ArrowDown"]
