from __future__ import annotations

import pytest

from poc.jumpplus_vertical_j1 import build_region_states, classify_reconstruction, prefetch_bucket
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


def _j1_dom(*regions: dict) -> dict:
    return {"viewport": {"height": 1000}, "regions": list(regions)}


def _j1_region(index: int, canvas_id: int, *, top: int = 0) -> dict:
    return {
        "index": index,
        "isContentPage": True,
        "inViewport": top < 1000 and top + 500 > 0,
        "intersectionRatio": 1 if top == 0 else 0,
        "renderedRect": {"top": top, "bottom": top + 500},
        "image": {"canvasId": canvas_id, "width": 100, "height": 100},
    }


def _j1_draw(canvas_id: int, source_id: int = 1) -> list[dict]:
    source = {"sourceId": source_id, "url": f"blob:{source_id}", "naturalWidth": 100, "naturalHeight": 100}
    return [
        {
            "canvas": {"id": canvas_id},
            "source": source,
            "sourceRect": {"sx": 0, "sy": 0, "sw": 100, "sh": 100},
            "destinationRect": {"dx": 0, "dy": 0, "dw": 100, "dh": 100},
        },
        {
            "canvas": {"id": canvas_id},
            "source": source,
            "sourceRect": {"sx": 0, "sy": 0, "sw": 50, "sh": 50},
            "destinationRect": {"dx": 0, "dy": 0, "dw": 50, "dh": 50},
        },
    ]


def test_j1_region_states_distinguish_mounted_from_reconstructable() -> None:
    dom = _j1_dom(_j1_region(0, 7), _j1_region(1, 8, top=2000))
    sources = {(1, "blob:1"): {"sourceId": 1, "url": "blob:1", "file": "sources/1.png", "pixel_sha256": "p1"}}
    candidates = [{"url": "https://cdn/page/1.jpg", "pixel_sha256": "p1", "file": "network_images/1.jpg"}]

    rows = build_region_states(dom, _j1_draw(7), sources, candidates)

    assert rows[0]["mounted"] is True
    assert rows[0]["reconstructable"] is True
    assert rows[1]["mounted"] is True
    assert rows[1]["reconstructable"] is False
    assert rows[1]["unavailable_reason"] == "drawImage_not_observed"


def test_j1_missing_transport_is_inconclusive_not_failed() -> None:
    dom = _j1_dom(_j1_region(0, 7))
    rows = build_region_states(
        dom,
        _j1_draw(7),
        {(1, "blob:1"): {"sourceId": 1, "url": "blob:1", "file": "sources/1.png", "pixel_sha256": "p1"}},
        [],
    )

    assert rows[0]["transport_ready"] is False
    assert rows[0]["unavailable_reason"] == "network_response_unavailable"
    assert classify_reconstruction(None, rows[0]) == "inconclusive"


def test_j1_failed_and_confirmed_classification_is_separate() -> None:
    evidence = {"reconstructable": True}
    assert classify_reconstruction({"jpeg_dct_reconstruction": "successful"}, evidence) == "confirmed"
    assert classify_reconstruction({"pixel_reconstruction": "failed", "status": "inconclusive"}, evidence) == "failed"
    assert classify_reconstruction({"mapping_status": "incomplete"}, evidence) == "inconclusive"


def test_j1_prefetch_bucket_is_bounded_distance_classification() -> None:
    assert prefetch_bucket([], 1000) == "not_observed"
    assert prefetch_bucket([500], 1000) == "viewport_or_within_one_screen"
    assert prefetch_bucket([2500], 1000) == "a_few_screens"
    assert prefetch_bucket([4000], 1000) == "far_prefetch"
