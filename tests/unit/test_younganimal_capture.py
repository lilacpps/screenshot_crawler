from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from screenshot_crawler.core.errors import UnknownPageStateError
from screenshot_crawler.site_adapters.younganimal import native_capture
from screenshot_crawler.site_adapters.younganimal.adapter import (
    _native_failure_details,
    _native_failure_reason,
)
from screenshot_crawler.site_adapters.younganimal.capture import (
    _parse_viewer_observation,
    decode_canvas_png,
    decode_capture_results,
)

EPISODE_URL = "https://younganimal.com/episodes/55889b8a851cb"
BODY_SLOTS = tuple(range(1, 17))
STANDARD15_BODY_SLOTS = tuple(range(1, 16))


def _snapshot(
    seek_value: int,
    *,
    missing_canvas: int | None = None,
    standard15_body: bool = False,
    odd_body_count: int | None = None,
    pr_tail_body_count: int | None = None,
    tail_pr_count: int = 1,
    top_empty_pr: bool = False,
    no_top_pr: bool = False,
    standard_body_count: int | None = None,
) -> dict[str, object]:
    viewer_classes = {"-cv", "mode-spread", "mode-dir-rtl", "mode-nav-dir-rtl"}
    odd_body_profile = standard15_body or odd_body_count is not None
    body_count = standard_body_count if standard_body_count is not None else pr_tail_body_count if pr_tail_body_count is not None else odd_body_count if odd_body_count is not None else 15 if standard15_body else 16
    seek_max = 7 if standard_body_count in {1, 2} else body_count + tail_pr_count + 4 if pr_tail_body_count is not None else body_count + 5 if standard_body_count is not None else body_count + 6 if odd_body_profile else 21
    if top_empty_pr:
        seek_max += 1
    pr_tail_odd = pr_tail_body_count is not None and not top_empty_pr and body_count % 2 == 1
    if pr_tail_odd:
        seek_max -= 1
    ci_seek = tail_pr_count + (2 if pr_tail_odd else 4) if pr_tail_body_count is not None else 5
    if odd_body_profile or pr_tail_body_count is not None or standard_body_count in {1, 2}:
        viewer_classes.update({"mode-has-pr", "mode-has-comic-info", "mode-has-good-page"})
    if pr_tail_body_count is not None or standard_body_count in {1, 2}:
        viewer_classes.add("mode-h")
    if no_top_pr:
        viewer_classes.update({"mode-h", "mode-has-top-emptypage"})
    if top_empty_pr:
        viewer_classes.add("mode-has-top-emptypage")
    if seek_value == seek_max:
        viewer_classes.update({"mode-first-page", "mode-top-pr-page"})
    elif seek_value == ci_seek:
        viewer_classes.update({"mode-pr-page", "mode-ci-page"})
    elif 1 < seek_value < ci_seek:
        viewer_classes.add("mode-pr-page")
    elif seek_value == 1:
        viewer_classes.update({"mode-pr-page", "mode-last-page"})
    if no_top_pr:
        viewer_classes.discard("mode-top-pr-page")
    body_slots = tuple(range(2, body_count + 2)) if top_empty_pr else tuple(range(1, body_count + 1))
    ci_slot = body_slots[-1] + 1
    wrapper_count = ci_slot + (tail_pr_count + 3 if pr_tail_body_count is not None else 5)
    if (odd_body_profile or (pr_tail_body_count is not None and not pr_tail_odd) or standard_body_count == 1) and seek_value == 1:
        viewer_classes.discard("mode-pr-page")
    slots: list[dict[str, object]] = []
    for index in range(wrapper_count):
        if index == 0:
            classes = {"-cv-page", "mode-empty"} if no_top_pr else {"-cv-page", "mode-empty", "mode-pr", "mode-top-pr"}
        elif top_empty_pr and index == 1:
            classes = {"-cv-page", "mode-empty"}
        elif index in body_slots:
            classes = {"-cv-page", "mode-loaded", "mode-rendered"}
        elif index == ci_slot:
            classes = {"-cv-page", "mode-ci"}
        elif index in (set(range(ci_slot + 1, ci_slot + tail_pr_count + 1)) if pr_tail_body_count is not None else {ci_slot + 1, ci_slot + 2}):
            classes = {"-cv-page", "mode-empty", "mode-pr"}
        elif index == ci_slot + (tail_pr_count + 1 if pr_tail_body_count is not None else 3):
            classes = {"-cv-page", "mode-good"}
        else:
            classes = {"-cv-page", "mode-last"}
        rect_x = 945 + ((seek_max - seek_value + 1 - index - 1) * 946)
        canvas = None
        canvas_count = 0
        if index in body_slots and index != missing_canvas:
            canvas_count = 1
            canvas = {
                "node": index + 100,
                "width": 984,
                "height": 1329,
                "rect": [rect_x + 145, 0, 656, 886],
                "parentNode": index + 200,
                "parentClasses": ["-cv-page-canvas"],
                "ready": True,
                "visible": True,
                "generation": 0,
                "writes": 3,
                "pixels": "one:two",
                "pixelError": None,
            }
        slots.append(
            {
                "index": index,
                "wrapperNode": index + 1,
                "classes": sorted(classes),
                "wrapperRect": [rect_x, 0, 946, 886],
                "wrapperCenterInViewport": 0 <= rect_x + 473 <= 1906,
                "canvasCount": canvas_count,
                "canvas": canvas,
            }
        )
    return {
        "url": EPISODE_URL,
        "viewerCount": 1,
        "pagesCount": 1,
        "seekCount": 1,
        "viewerNode": 1,
        "pagesNode": 2,
        "seekNode": 3,
        "viewerClasses": sorted(viewer_classes),
        "seek": {
            "type": "range",
            "value": str(seek_value),
            "min": "1",
            "max": str(seek_max),
            "step": "2",
            "disabled": False,
        },
        "pages": {"className": "-cv-pages", "childCount": wrapper_count},
        "viewport": {"width": 1906, "height": 986, "dpr": 1.5},
        "domGeneration": 0,
        "captureDomGeneration": 0,
        "slots": slots,
        "terminalMarkerCount": 1 if seek_value == 1 else 0,
        "terminalMarkerParentIndex": wrapper_count - 1 if seek_value == 1 else None,
        "terminalMarkerVisible": seek_value == 1,
        "terminalMarkerCenterInViewport": seek_value == 1,
    }


def _top_empty_no_ci_snapshot(seek_value: int, *, body_count: int = 10, no_lead: bool = False) -> dict[str, object]:
    body_start = 0 if no_lead else 1
    body_end = body_start + body_count
    wrapper_count = body_end + 4
    even_wrappers = wrapper_count % 2 == 0
    seek_max = wrapper_count - int(even_wrappers)
    viewer_classes = {
        "-cv", "mode-h", "mode-spread", "mode-dir-rtl", "mode-nav-dir-rtl",
        "mode-has-pr", "mode-has-good-page",
    }
    if not no_lead:
        viewer_classes.add("mode-has-top-emptypage")
    if seek_value == seek_max:
        viewer_classes.add("mode-first-page")
    elif seek_value == 3 or (seek_value == 5 and not even_wrappers):
        viewer_classes.add("mode-pr-page")
    elif seek_value == 1:
        viewer_classes.add("mode-last-page")
        if even_wrappers:
            viewer_classes.add("mode-pr-page")
    focus = seek_max - seek_value + 1
    slots: list[dict[str, object]] = []
    for index in range(wrapper_count):
        if index == 0 and not no_lead:
            classes = {"-cv-page", "mode-empty"}
        elif index < body_end:
            classes = {"-cv-page", "mode-loaded", "mode-rendered"}
        elif index < body_end + 2:
            classes = {"-cv-page", "mode-empty", "mode-pr"}
        elif index == body_end + 2:
            classes = {"-cv-page", "mode-good"}
        else:
            classes = {"-cv-page", "mode-last"}
        rect_x = 945 + ((focus - index - 1) * 946)
        canvas = None
        canvas_count = 0
        if body_start <= index < body_end:
            canvas_count = 1
            canvas = {
                "node": index + 100,
                "width": 925,
                "height": 1329,
                "rect": [rect_x + 120, 0, 685, 886],
                "parentNode": index + 200,
                "parentClasses": ["-cv-page-canvas"],
                "ready": True,
                "visible": True,
                "generation": 0,
                "writes": 3,
                "pixels": f"body:{index}",
                "pixelError": None,
            }
        slots.append({
            "index": index,
            "wrapperNode": index + 1,
            "classes": sorted(classes),
            "wrapperRect": [rect_x, 0, 946, 886],
            "wrapperCenterInViewport": 0 <= rect_x + 473 <= 1906,
            "canvasCount": canvas_count,
            "canvas": canvas,
        })
    return {
        "url": EPISODE_URL,
        "viewerCount": 1,
        "pagesCount": 1,
        "seekCount": 1,
        "viewerNode": 1,
        "pagesNode": 2,
        "seekNode": 3,
        "viewerClasses": sorted(viewer_classes),
        "seek": {
            "type": "range", "value": str(seek_value), "min": "1",
            "max": str(seek_max), "step": "2", "disabled": False,
        },
        "pages": {"className": "-cv-pages", "childCount": wrapper_count},
        "viewport": {"width": 1906, "height": 986, "dpr": 1.5},
        "domGeneration": 0,
        "captureDomGeneration": 0,
        "slots": slots,
        "terminalMarkerCount": 1,
        "terminalMarkerParentIndex": wrapper_count - 1,
        "terminalMarkerVisible": seek_value == 1,
        "terminalMarkerCenterInViewport": seek_value == 1,
    }


def _no_lead_ci_snapshot(seek_value: int, *, body_count: int = 15) -> dict[str, object]:
    raw = _top_empty_no_ci_snapshot(seek_value, body_count=body_count + 1, no_lead=True)
    raw["viewerClasses"].append("mode-has-comic-info")
    if seek_value == 5:
        raw["viewerClasses"].extend(["mode-ci-page", "mode-pr-page"])
    ci = raw["slots"][body_count]
    ci.update(classes=["-cv-page", "mode-ci"], canvasCount=0, canvas=None)
    return raw


@pytest.mark.parametrize("body_count", [5, 15, 6, 12])
def test_younganimal_no_lead_ci_maps_every_phase(body_count: int) -> None:
    covered = []
    maximum = body_count + 5 - body_count % 2
    even_body = body_count % 2 == 0
    for seek in range(maximum, 0, -2):
        row = _parse_viewer_observation(_no_lead_ci_snapshot(seek, body_count=body_count), expected_url=EPISODE_URL)
        assert row.layout_variant == ("no_lead_ci_even_body" if even_body else "no_lead_ci_odd_body")
        assert row.body_slots == tuple(range(body_count))
        assert row.ci_slot == body_count
        assert row.pr_slots == (body_count + 1, body_count + 2)
        assert row.page_state == ("end" if seek == 1 else "ad" if seek == 3 or (even_body and seek == 5) else "content")
        if row.page_state == "content":
            focus = maximum - seek + 1
            assert row.active_slots == tuple(i for i in (focus - 1, focus) if i < body_count)
            assert row.ready_slots == row.active_slots
            covered.extend(row.active_slots)
    assert covered == list(range(body_count))


@pytest.mark.parametrize("mutation", [
    "horizontal", "pr", "ci", "good", "top_empty", "vertical", "single", "range", "step", "min",
    "short_body", "short_even_body", "lead", "body", "tail", "tail_canvas", "centers", "first_phase",
    "body_phase", "ci_phase", "pr_phase", "end_phase", "end_parity_phase", "end_missing", "end_duplicate",
    "end_parent", "end_hidden", "end_offscreen", "end_centers",
])
@pytest.mark.parametrize("body_count", [15, 12])
def test_younganimal_no_lead_ci_rejects_unproven_layout(mutation: str, body_count: int) -> None:
    body_count = 3 if mutation == "short_body" else 4 if mutation == "short_even_body" else body_count
    maximum = body_count + 5 - body_count % 2
    seek = 1 if mutation.startswith("end_") else 5 if mutation == "ci_phase" else 3 if mutation == "pr_phase" else maximum - 2 if mutation == "body_phase" else maximum
    raw = _no_lead_ci_snapshot(seek, body_count=body_count)
    flags = {"horizontal": "mode-h", "pr": "mode-has-pr", "ci": "mode-has-comic-info", "good": "mode-has-good-page"}
    if mutation in flags:
        raw["viewerClasses"].remove(flags[mutation])
    elif mutation in {"top_empty", "vertical", "single"}:
        raw["viewerClasses"].append({"top_empty": "mode-has-top-emptypage", "vertical": "mode-v", "single": "mode-single"}[mutation])
    elif mutation in {"range", "step", "min"}:
        raw["seek"][{"range": "max", "step": "step", "min": "min"}[mutation]] = {"range": str(maximum + 2), "step": "1", "min": "0"}[mutation]
    elif mutation == "lead":
        raw["slots"][0]["classes"] = ["-cv-page", "mode-pr"]
    elif mutation in {"body", "tail"}:
        raw["slots"][4 if mutation == "body" else body_count]["classes"] = ["-cv-page", "mode-good"]
    elif mutation == "tail_canvas":
        raw["slots"][body_count].update(canvasCount=1, canvas=raw["slots"][0]["canvas"])
    elif mutation.endswith("centers"):
        raw["slots"][0]["wrapperCenterInViewport"] = not raw["slots"][0]["wrapperCenterInViewport"]
    elif mutation == "end_parity_phase":
        if body_count % 2:
            raw["viewerClasses"].remove("mode-pr-page")
        else:
            raw["viewerClasses"].append("mode-pr-page")
    elif mutation.endswith("phase"):
        raw["viewerClasses"].append("mode-top-pr-page")
    elif mutation in {"end_missing", "end_duplicate"}:
        raw["terminalMarkerCount"] = 0 if mutation == "end_missing" else 2
    elif mutation == "end_parent":
        raw["terminalMarkerParentIndex"] = body_count + 3
    elif mutation in {"end_hidden", "end_offscreen"}:
        raw["terminalMarkerVisible" if mutation == "end_hidden" else "terminalMarkerCenterInViewport"] = False
    with pytest.raises(UnknownPageStateError):
        _parse_viewer_observation(raw, expected_url=EPISODE_URL)


def _top_empty_snapshot(seek_value: int, *, body_count: int = 44) -> dict[str, object]:
    raw = _snapshot(21)
    base = raw["slots"]
    wrapper_count = body_count + 7
    maximum = wrapper_count if wrapper_count % 2 else wrapper_count - 1
    ci_slot = body_count + 2
    focus = maximum - seek_value + 1
    active = {focus - 1, focus}
    slots: list[dict[str, object]] = []
    lead = dict(base[0])
    lead["index"] = 0
    lead["wrapperCenterInViewport"] = 0 in active
    slots.append(lead)
    slots.append({
        "index": 1, "wrapperNode": 2, "classes": ["-cv-page", "mode-empty"],
        "wrapperRect": [945 + (focus - 2) * 946, 0, 946, 886],
        "wrapperCenterInViewport": focus == 1, "canvasCount": 0, "canvas": None,
    })
    body_template = base[1]
    for index in range(2, ci_slot):
        center = index in active
        wrapper_x = 945 + (focus - index - 1) * 946
        canvas = dict(body_template["canvas"])
        canvas.update({
            "node": index + 100, "parentNode": index + 200,
            "width": 942, "height": 1329,
            "rect": [wrapper_x + 159, 0, 628, 886],
        })
        slots.append({
            "index": index, "wrapperNode": index + 1,
            "classes": ["-cv-page", "mode-loaded", "mode-rendered"],
            "wrapperRect": [wrapper_x, 0, 946, 886],
            "wrapperCenterInViewport": center, "canvasCount": 1, "canvas": canvas,
        })
    for index, original in enumerate(base[17:22], start=ci_slot):
        wrapper_x = 945 + (focus - index - 1) * 946
        slots.append({
            **original, "index": index, "wrapperNode": index + 1,
            "wrapperRect": [wrapper_x, 0, 946, 886],
            "wrapperCenterInViewport": index in active or (seek_value == 1 and index == wrapper_count - 1),
        })
    viewer_classes = set(raw["viewerClasses"])
    viewer_classes.add("mode-has-top-emptypage")
    viewer_classes.discard("mode-last-page")
    if seek_value == maximum:
        viewer_classes.update({"mode-first-page", "mode-top-pr-page"})
    else:
        viewer_classes.discard("mode-first-page")
        viewer_classes.discard("mode-top-pr-page")
    if seek_value == 1:
        viewer_classes.add("mode-last-page")
    if body_count % 2:
        viewer_classes.update({"mode-h", "mode-has-pr", "mode-has-comic-info", "mode-has-good-page"})
        if seek_value == 5:
            viewer_classes.update({"mode-ci-page", "mode-pr-page"})
        elif seek_value in {1, 3}:
            viewer_classes.add("mode-pr-page")
    raw.update({
        "viewerClasses": sorted(viewer_classes),
        "seek": {"type": "range", "value": str(seek_value), "min": "1", "max": str(maximum), "step": "2", "disabled": False},
        "pages": {"className": "-cv-pages", "childCount": wrapper_count},
        "slots": slots,
        "terminalMarkerCount": 1 if seek_value == 1 else 0,
        "terminalMarkerParentIndex": wrapper_count - 1 if seek_value == 1 else None,
        "terminalMarkerVisible": seek_value == 1,
        "terminalMarkerCenterInViewport": seek_value == 1,
    })
    return raw


@pytest.mark.parametrize(
    ("seek_value", "state", "active"),
    [
        (21, "content", (1,)),
        (19, "content", (2, 3)),
        (17, "content", (4, 5)),
        (5, "content", (16,)),
        (3, "ad", (17, 18, 19)),
        (1, "end", (19, 20, 21)),
    ],
)
@pytest.mark.parametrize("no_top_pr", [False, True])
def test_younganimal_observed_seek_roles_map_to_contiguous_physical_body_slots(
    seek_value: int, state: str, active: tuple[int, ...], no_top_pr: bool
) -> None:
    raw = _snapshot(seek_value)
    if no_top_pr:
        raw["viewerClasses"] = [name for name in raw["viewerClasses"] if name != "mode-top-pr-page"] + ["mode-has-top-emptypage"]
        raw["slots"][0]["classes"] = ["-cv-page", "mode-empty"]
    observation = _parse_viewer_observation(raw, expected_url=EPISODE_URL)
    assert observation.layout_variant == ("top_empty_no_pr" if no_top_pr else "standard")

    assert observation.body_slots == BODY_SLOTS
    assert observation.ci_slot == 17
    assert observation.page_state == state
    assert observation.active_slots == active
    if state == "content":
        assert observation.ready_slots == active


@pytest.mark.parametrize("mutation", ["flag", "canvas", "range", "pr_marker", "offscreen"])
def test_younganimal_no_pr_profile_requires_its_positive_structural_proof(mutation: str) -> None:
    raw = _snapshot(21)
    raw["viewerClasses"] = [name for name in raw["viewerClasses"] if name != "mode-top-pr-page"] + ["mode-has-top-emptypage"]
    raw["slots"][0]["classes"] = ["-cv-page", "mode-empty"]
    if mutation == "flag":
        raw["viewerClasses"].remove("mode-has-top-emptypage")
    elif mutation == "canvas":
        raw["slots"][0]["canvasCount"] = 1
        raw["slots"][0]["canvas"] = raw["slots"][1]["canvas"]
    elif mutation == "range":
        raw["seek"]["max"] = "23"
    elif mutation == "pr_marker":
        raw["viewerClasses"].append("mode-top-pr-page")
    else:
        raw["slots"][0]["wrapperCenterInViewport"] = False
    with pytest.raises(UnknownPageStateError):
        _parse_viewer_observation(raw, expected_url=EPISODE_URL)


@pytest.mark.parametrize("value", [None, True, -1, 1.5, "0"])
def test_younganimal_capture_mutation_epoch_must_be_a_nonnegative_integer(value: object) -> None:
    raw = _snapshot(21)
    raw["captureDomGeneration"] = value

    with pytest.raises(UnknownPageStateError, match="capture mutation epoch"):
        _parse_viewer_observation(raw, expected_url=EPISODE_URL)


def test_younganimal_body_interval_is_derived_from_verified_roles_not_fixed_count() -> None:
    raw = _snapshot(21)
    raw["slots"] = raw["slots"][:5] + raw["slots"][17:]
    raw["pages"]["childCount"] = 10
    raw["seek"].update({"value": "9", "max": "9"})
    raw["slots"] = [dict(slot, index=index) for index, slot in enumerate(raw["slots"])]

    observation = _parse_viewer_observation(raw, expected_url=EPISODE_URL)

    assert observation.body_slots == (1, 2, 3, 4)
    assert observation.ci_slot == 5
    assert observation.seek_max == 9
    assert observation.active_slots == (1,)


@pytest.mark.parametrize(
    "mutation",
    [
        "lead_in_class",
        "interior_empty_slot",
        "tail_shift",
        "wrapper_count",
        "seek_relation",
        "wrong_route",
        "no_lead_short_body",
        "no_lead_short_even_body",
        "no_lead_even_wrong_range",
        "top_empty_no_ci_wrong_range",
        "top_empty_no_ci_short_odd_body",
    ],
)
def test_younganimal_unobserved_physical_layouts_fail_closed(mutation: str) -> None:
    raw = _snapshot(21)
    if mutation == "lead_in_class":
        raw["slots"][0]["classes"] = ["-cv-page", "mode-empty", "mode-pr"]
    elif mutation == "interior_empty_slot":
        raw["slots"][8]["classes"] = ["-cv-page", "mode-empty", "mode-pr"]
    elif mutation == "tail_shift":
        raw["slots"][17]["classes"] = ["-cv-page", "mode-empty", "mode-pr"]
    elif mutation == "wrapper_count":
        raw["slots"].pop()
        raw["pages"]["childCount"] = 21
    elif mutation == "seek_relation":
        raw["seek"]["max"] = "23"
    elif mutation.startswith("no_lead_"):
        body_count = 3 if mutation == "no_lead_short_body" else 4 if mutation == "no_lead_short_even_body" else 12
        raw = _top_empty_no_ci_snapshot(body_count + 4, body_count=body_count, no_lead=True)
        if mutation == "no_lead_even_wrong_range":
            raw["seek"]["max"] = str(body_count + 4)
    elif mutation.startswith("top_empty_no_ci_"):
        body_count = 11 if mutation == "top_empty_no_ci_wrong_range" else 3
        raw = _top_empty_no_ci_snapshot(body_count + 4, body_count=body_count)
        if mutation == "top_empty_no_ci_wrong_range":
            raw["seek"]["max"] = str(body_count + 5)
    else:
        raw["url"] = "https://younganimal.com/episodes/0000000000001"

    with pytest.raises(UnknownPageStateError):
        _parse_viewer_observation(raw, expected_url=EPISODE_URL)


@pytest.mark.parametrize(
    ("seek", "state", "active"),
    [(11, "content", (1,)), (9, "content", (2, 3)), (7, "content", (4, 5)),
     (5, "content", (6,)), (3, "ad", ()), (1, "end", (10,))],
)
def test_younganimal_single_pr_maps_body_ci_and_visible_terminal(seek, state, active) -> None:
    observed = _parse_viewer_observation(_snapshot(seek, pr_tail_body_count=6), expected_url=EPISODE_URL)

    assert observed.layout_variant == "standard_single_pr"
    assert observed.body_slots == tuple(range(1, 7))
    assert (observed.ci_slot, observed.pr_slots, observed.good_slot, observed.last_slot) == (7, (8,), 9, 10)
    assert observed.seek_max == 11
    assert observed.page_state == state
    assert observed.active_slots == active
    if state == "content":
        assert observed.ready_slots == active


@pytest.mark.parametrize(
    ("seek", "state", "active"),
    [(17, "content", (1,)), (15, "content", (2, 3)), (13, "content", (4, 5)),
     (11, "content", (6, 7)), (9, "content", (8, 9)), (7, "content", (10,)),
     (5, "ad", ()), (3, "ad", ()), (1, "end", (16,))],
)
def test_younganimal_three_pr_maps_all_observed_phases(seek, state, active) -> None:
    observed = _parse_viewer_observation(_snapshot(seek, pr_tail_body_count=10, tail_pr_count=3), expected_url=EPISODE_URL)
    assert observed.layout_variant == "standard_three_pr"
    assert observed.body_slots == tuple(range(1, 11))
    assert (observed.ci_slot, observed.pr_slots, observed.good_slot, observed.last_slot) == (11, (12, 13, 14), 15, 16)
    assert observed.seek_max == 17 and observed.page_state == state
    assert observed.active_slots == active
    if state == "content":
        assert observed.ready_slots == active


@pytest.mark.parametrize(
    ("seek", "state", "active"),
    [(17, "content", (1,)), (15, "content", (2, 3)), (13, "content", (4, 5)),
     (11, "content", (6, 7)), (9, "content", (8, 9)), (7, "content", (10, 11)),
     (5, "ad", ()), (3, "ad", ()), (1, "end", (17,))],
)
def test_younganimal_three_pr_odd_body_maps_all_observed_phases(seek, state, active) -> None:
    observed = _parse_viewer_observation(
        _snapshot(seek, pr_tail_body_count=11, tail_pr_count=3), expected_url=EPISODE_URL,
    )
    assert observed.layout_variant == "standard_three_pr_odd_body"
    assert observed.body_slots == tuple(range(1, 12))
    assert (observed.ci_slot, observed.pr_slots, observed.good_slot, observed.last_slot) == (12, (13, 14, 15), 16, 17)
    assert observed.page_state == state and observed.active_slots == active
    if state == "content":
        assert observed.ready_slots == active


@pytest.mark.parametrize("mutation", ["capability", "blank", "range", "body", "tail", "canvas", "ci_phase", "end_phase", "end_marker", "end_hidden", "center", "single_pr"])
def test_three_pr_odd_body_rejects_unobserved_or_changed_profile(mutation: str) -> None:
    raw = _snapshot(1 if mutation.startswith("end_") else 5, pr_tail_body_count=11, tail_pr_count=3)
    if mutation == "capability":
        raw["viewerClasses"].remove("mode-has-comic-info")
    elif mutation == "blank":
        raw["viewerClasses"].append("mode-has-top-emptypage")
    elif mutation == "range":
        raw["seek"]["max"] = "19"
    elif mutation in {"body", "tail"}:
        raw["slots"][4 if mutation == "body" else 14]["classes"] = ["-cv-page", "mode-empty"]
    elif mutation == "canvas":
        raw["slots"][13]["canvasCount"] = 1
        raw["slots"][13]["canvas"] = raw["slots"][1]["canvas"]
    elif mutation == "ci_phase":
        raw["viewerClasses"].remove("mode-ci-page")
    elif mutation == "end_phase":
        raw["viewerClasses"].remove("mode-pr-page")
    elif mutation == "end_marker":
        raw["terminalMarkerCount"] = 2
    elif mutation == "end_hidden":
        raw["terminalMarkerVisible"] = False
    elif mutation == "center":
        raw["slots"][4]["wrapperCenterInViewport"] = True
    else:
        raw = _snapshot(15, pr_tail_body_count=11, tail_pr_count=1)
    with pytest.raises(UnknownPageStateError):
        _parse_viewer_observation(raw, expected_url=EPISODE_URL)


@pytest.mark.parametrize(
    ("seek", "state", "active"),
    [(17, "initial_blank", (1,)), (15, "content", (2, 3)), (13, "content", (4, 5)),
     (11, "content", (6, 7)), (9, "content", (8, 9)), (7, "content", (10,)),
     (5, "ad", ()), (3, "ad", ()), (1, "end", (16,))],
)
def test_younganimal_top_empty_three_pr_maps_all_observed_phases(seek, state, active) -> None:
    observed = _parse_viewer_observation(
        _snapshot(seek, pr_tail_body_count=9, tail_pr_count=3, top_empty_pr=True),
        expected_url=EPISODE_URL,
    )
    assert observed.layout_variant == "top_empty_three_pr"
    assert observed.body_slots == tuple(range(2, 11))
    assert (observed.ci_slot, observed.pr_slots, observed.good_slot, observed.last_slot) == (11, (12, 13, 14), 15, 16)
    assert observed.page_state == state and observed.active_slots == active
    assert observed.initial_blank is (seek == 17)


@pytest.mark.parametrize("mutation", ["blank", "blank_canvas", "capability", "phase", "center", "tail", "tail_canvas", "range", "end_marker", "end_hidden", "unsupported_pr"])
def test_top_empty_three_pr_rejects_unknown_or_incomplete_layout(mutation: str) -> None:
    raw = _snapshot(1 if mutation.startswith("end_") else 17, pr_tail_body_count=9, tail_pr_count=3, top_empty_pr=True)
    if mutation == "blank":
        raw["slots"][1]["classes"].append("mode-pr")
    elif mutation in {"blank_canvas", "tail_canvas"}:
        index = 1 if mutation == "blank_canvas" else 12
        raw["slots"][index]["canvasCount"] = 1
        raw["slots"][index]["canvas"] = raw["slots"][2]["canvas"]
    elif mutation == "capability":
        raw["viewerClasses"].remove("mode-has-comic-info")
    elif mutation == "phase":
        raw["viewerClasses"].append("mode-ci-page")
    elif mutation == "center":
        raw["slots"][2]["wrapperCenterInViewport"] = True
    elif mutation == "tail":
        raw["slots"][14]["classes"] = ["-cv-page", "mode-good"]
    elif mutation == "range":
        raw["seek"]["max"] = "15"
    elif mutation == "end_marker":
        raw["terminalMarkerCount"] = 2
    elif mutation == "end_hidden":
        raw["terminalMarkerVisible"] = False
    else:
        raw = _snapshot(15, pr_tail_body_count=9, tail_pr_count=1, top_empty_pr=True)
    with pytest.raises(UnknownPageStateError):
        _parse_viewer_observation(raw, expected_url=EPISODE_URL)


@pytest.mark.parametrize(
    "mutation",
    ["capability", "vertical", "single", "top_empty", "range", "ci_phase", "interstitial_ci", "tail", "tail_canvas",
     "body", "phase", "center", "end_parent", "end_duplicate", "end_invisible", "end_offscreen"],
)
@pytest.mark.parametrize("pr_count", [1, 3])
def test_younganimal_pr_tail_rejects_role_phase_or_terminal_drift(mutation: str, pr_count: int) -> None:
    raw = _snapshot(1 if mutation.startswith("end_") else 11, pr_tail_body_count=6, tail_pr_count=pr_count)
    if not mutation.startswith("end_"):
        raw = _snapshot(6 + pr_count + 4, pr_tail_body_count=6, tail_pr_count=pr_count)
    if mutation == "capability":
        raw["viewerClasses"].remove("mode-has-comic-info")
    elif mutation in {"vertical", "single", "top_empty"}:
        raw["viewerClasses"].append({"vertical": "mode-v", "single": "mode-single", "top_empty": "mode-has-top-emptypage"}[mutation])
    elif mutation == "range":
        raw["seek"]["max"] = str(int(raw["seek"]["max"]) + 2)
    elif mutation == "ci_phase":
        raw = _snapshot(pr_count + 4, pr_tail_body_count=6, tail_pr_count=pr_count)
        raw["viewerClasses"].remove("mode-ci-page")
    elif mutation == "interstitial_ci":
        raw = _snapshot(pr_count + 2, pr_tail_body_count=6, tail_pr_count=pr_count)
        raw["viewerClasses"].append("mode-ci-page")
    elif mutation == "tail":
        raw["slots"][pr_count + 8]["classes"] = ["-cv-page", "mode-empty", "mode-pr"]
    elif mutation == "tail_canvas":
        raw["slots"][8]["canvasCount"] = 1
        raw["slots"][8]["canvas"] = raw["slots"][1]["canvas"]
    elif mutation == "body":
        raw["slots"][4]["classes"] = ["-cv-page", "mode-empty"]
    elif mutation == "phase":
        raw["viewerClasses"].append("mode-pr-page")
    elif mutation == "center":
        raw["slots"][4]["wrapperCenterInViewport"] = True
    elif mutation == "end_parent":
        raw["terminalMarkerParentIndex"] = pr_count + 8
    elif mutation == "end_duplicate":
        raw["terminalMarkerCount"] = 2
    elif mutation == "end_invisible":
        raw["terminalMarkerVisible"] = False
    else:
        raw["terminalMarkerCenterInViewport"] = False

    with pytest.raises(UnknownPageStateError):
        _parse_viewer_observation(raw, expected_url=EPISODE_URL)


def test_younganimal_unobserved_five_pr_tail_remains_unsupported() -> None:
    with pytest.raises(UnknownPageStateError):
        _parse_viewer_observation(_snapshot(15, pr_tail_body_count=6, tail_pr_count=5), expected_url=EPISODE_URL)


@pytest.mark.parametrize(
    ("seek", "state", "active"),
    [(7, "content", (1,)), (5, "content", (2,)), (3, "ad", (3, 4, 5)), (1, "end", (5, 6, 7))],
)
@pytest.mark.parametrize("body_count", [1, 2])
def test_younganimal_short_standard_maps_pages_and_terminal(seek, state, active, body_count: int) -> None:
    if body_count == 1:
        state = "content" if seek == 7 else "end" if seek == 1 else "ad"
        active = {7: (1,), 5: (2, 3), 3: (4, 5), 1: (6,)}[seek]
    observed = _parse_viewer_observation(_snapshot(seek, standard_body_count=body_count), expected_url=EPISODE_URL)
    ci = body_count + 1
    assert observed.layout_variant == ("standard_one_body" if body_count == 1 else "standard_two_body")
    assert observed.body_slots == tuple(range(1, body_count + 1))
    assert (observed.ci_slot, observed.pr_slots, observed.good_slot, observed.last_slot) == (ci, (ci + 1, ci + 2), ci + 3, ci + 4)
    assert observed.seek_max == 7 and observed.page_state == state
    assert observed.active_slots == active
    if state == "content":
        assert observed.ready_slots == active


@pytest.mark.parametrize(
    "mutation", ["horizontal", "capability", "top_empty", "vertical", "single", "lead", "body", "tail",
                 "tail_canvas", "range", "phase", "center", "last_parent", "last_duplicate", "last_hidden", "last_offscreen"],
)
@pytest.mark.parametrize("body_count", [1, 2])
def test_younganimal_short_standard_rejects_unproven_layout(mutation: str, body_count: int) -> None:
    raw = _snapshot(1 if mutation.startswith("last_") else 7, standard_body_count=body_count)
    ci = body_count + 1
    if mutation in {"horizontal", "capability"}:
        raw["viewerClasses"].remove("mode-h" if mutation == "horizontal" else "mode-has-comic-info")
    elif mutation in {"top_empty", "vertical", "single"}:
        raw["viewerClasses"].append({"top_empty": "mode-has-top-emptypage", "vertical": "mode-v", "single": "mode-single"}[mutation])
    elif mutation in {"lead", "body", "tail"}:
        raw["slots"][{"lead": 0, "body": body_count, "tail": ci}[mutation]]["classes"] = ["-cv-page", "mode-empty"]
    elif mutation == "tail_canvas":
        raw["slots"][ci]["canvasCount"] = 1
        raw["slots"][ci]["canvas"] = raw["slots"][1]["canvas"]
    elif mutation == "range":
        raw["seek"]["max"] = "9"
    elif mutation == "phase":
        raw["viewerClasses"].append("mode-pr-page")
    elif mutation == "center":
        raw["slots"][2]["wrapperCenterInViewport"] = True
    elif mutation == "last_parent":
        raw["terminalMarkerParentIndex"] = ci + 3
    elif mutation == "last_duplicate":
        raw["terminalMarkerCount"] = 2
    elif mutation == "last_hidden":
        raw["terminalMarkerVisible"] = False
    else:
        raw["terminalMarkerCenterInViewport"] = False
    with pytest.raises(UnknownPageStateError):
        _parse_viewer_observation(raw, expected_url=EPISODE_URL)


def test_younganimal_missing_active_canvas_is_not_reported_ready() -> None:
    observation = _parse_viewer_observation(
        _snapshot(19, missing_canvas=3), expected_url=EPISODE_URL
    )

    assert observation.active_slots == (2, 3)
    assert observation.ready_slots == (2,)


def test_younganimal_known_initial_blank_is_recognized_but_not_ready() -> None:
    raw = _snapshot(21)
    raw["slots"][1]["classes"] = ["-cv-page"]
    raw["slots"][1]["canvas"] = None
    raw["slots"][1]["canvasCount"] = 0

    observation = _parse_viewer_observation(raw, expected_url=EPISODE_URL)

    assert observation.page_state == "content"
    assert observation.active_slots == (1,)
    assert observation.ready_slots == ()


def test_younganimal_top_empty_wrapper_variant_requires_one_blank_step_and_maps_physical_body() -> None:
    initial = _parse_viewer_observation(_top_empty_snapshot(51), expected_url=EPISODE_URL)
    first_spread = _parse_viewer_observation(_top_empty_snapshot(49), expected_url=EPISODE_URL)
    terminal = _parse_viewer_observation(_top_empty_snapshot(1), expected_url=EPISODE_URL)

    assert initial.layout_variant == "top_emptypage"
    assert initial.initial_blank is True
    assert initial.page_state == "initial_blank"
    assert initial.active_slots == (1,)
    assert initial.ready_slots == ()
    assert initial.body_slots == tuple(range(2, 46))
    assert initial.ci_slot == 46
    assert first_spread.seek_value == 49
    assert first_spread.initial_blank is False
    assert first_spread.active_slots == first_spread.ready_slots == (2, 3)
    assert first_spread.raw["slots"][2]["canvas"]["width"] == 942
    assert first_spread.raw["slots"][2]["wrapperRect"][2:] == [946, 886]
    assert terminal.page_state == "end"
    assert terminal.body_slots == tuple(range(2, 46))
    assert terminal.raw["terminalMarkerParentIndex"] == 50


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [("blank_class", "top-empty-page"), ("blank_canvas", "top-empty-page"), ("seek_relation", "seek range")],
)
def test_younganimal_top_empty_variant_rejects_unknown_blank_or_wrapper_contract(
    mutation: str, expected_error: str
) -> None:
    raw = _top_empty_snapshot(51)
    if mutation == "blank_class":
        raw["slots"][1]["classes"] = ["-cv-page", "mode-empty", "mode-pr"]
    elif mutation == "blank_canvas":
        raw["slots"][1]["canvasCount"] = 1
        raw["slots"][1]["canvas"] = {"node": 999, "width": 1, "height": 1}
    else:
        raw["seek"]["max"] = "50"

    with pytest.raises(UnknownPageStateError, match=expected_error):
        _parse_viewer_observation(raw, expected_url=EPISODE_URL)


@pytest.mark.parametrize(
    ("seek_value", "state", "active"),
    [(17, "initial_blank", (1,)), (15, "content", (2, 3)), (7, "content", (10, 11)),
     (5, "content", (12,)), (3, "ad", (13, 14, 15)), (1, "end", (15, 16, 17))],
)
def test_younganimal_shorter_top_empty_maps_last_body_ci_and_terminal(seek_value, state, active) -> None:
    raw = _top_empty_snapshot(seek_value, body_count=11)

    observed = _parse_viewer_observation(raw, expected_url=EPISODE_URL)

    assert observed.layout_variant == "top_emptypage"
    assert observed.body_slots == tuple(range(2, 13))
    assert (observed.ci_slot, observed.pr_slots, observed.good_slot, observed.last_slot) == (13, (14, 15), 16, 17)
    assert observed.seek_max == 17
    assert observed.page_state == state
    assert observed.active_slots == active
    if state == "content":
        assert observed.ready_slots == active


@pytest.mark.parametrize(
    "mutation", ["max", "flag", "capability", "blank", "blank_canvas", "tail", "phase", "center", "end_marker", "end_invisible"],
)
def test_younganimal_shorter_top_empty_rejects_unproven_structure_or_phase(mutation: str) -> None:
    raw = _top_empty_snapshot(1 if mutation.startswith("end_") else 15, body_count=11)
    if mutation == "max":
        raw["seek"]["max"] = "19"
    elif mutation == "flag":
        raw["viewerClasses"].remove("mode-has-top-emptypage")
    elif mutation == "capability":
        raw["viewerClasses"].remove("mode-has-comic-info")
    elif mutation == "blank":
        raw["slots"][1]["classes"].append("mode-pr")
    elif mutation == "blank_canvas":
        raw["slots"][1].update(canvasCount=1, canvas={"width": 1, "height": 1})
    elif mutation == "tail":
        raw["slots"][13]["classes"] = ["-cv-page", "mode-empty", "mode-pr"]
    elif mutation == "phase":
        raw["viewerClasses"].append("mode-pr-page")
    elif mutation == "center":
        raw["slots"][4]["wrapperCenterInViewport"] = True
    elif mutation == "end_marker":
        raw["terminalMarkerParentIndex"] = 16
    elif mutation == "end_invisible":
        raw["terminalMarkerVisible"] = False

    with pytest.raises(UnknownPageStateError):
        _parse_viewer_observation(raw, expected_url=EPISODE_URL)


@pytest.mark.parametrize("body_count", [7, 9, 15, 29])
@pytest.mark.parametrize("no_top_pr", [False, True])
def test_younganimal_standard_odd_body_profile_maps_markers_and_selected_centers(body_count: int, no_top_pr: bool) -> None:
    maximum = body_count + 6
    ci_slot = body_count + 1
    states = (
        (maximum, "content", (1,), (0, 1)),
        (maximum - 2, "content", (2, 3), (2, 3)),
        (7, "content", (body_count - 1, body_count), (body_count - 1, body_count)),
        (5, "ad", (ci_slot, ci_slot + 1), (ci_slot, ci_slot + 1)),
        (3, "ad", (ci_slot + 2, ci_slot + 3), (ci_slot + 2, ci_slot + 3)),
        (1, "end", (ci_slot + 2, ci_slot + 3, ci_slot + 4), (ci_slot + 4,)),
    )
    for seek_value, state, active, centers in states:
        raw = _snapshot(seek_value, odd_body_count=body_count, no_top_pr=no_top_pr)
        observation = _parse_viewer_observation(raw, expected_url=EPISODE_URL)

        assert observation.layout_variant == ("top_empty_no_pr_odd_body" if no_top_pr else "standard_odd_body")
        assert observation.body_slots == tuple(range(1, body_count + 1))
        assert observation.ci_slot == ci_slot
        assert observation.page_state == state
        assert observation.active_slots == active
        assert tuple(
            slot["index"]
            for slot in raw["slots"]
            if slot["wrapperCenterInViewport"] is True
        ) == centers
        if state == "content":
            assert observation.ready_slots == active


@pytest.mark.parametrize(
    "mutation",
    ["wrapper_count", "seek_max", "lead_role", "tail_role", "body_role", "last_marker"],
)
def test_younganimal_standard15_body_profile_rejects_nearby_layouts(mutation: str) -> None:
    raw = _snapshot(21, standard15_body=True)
    if mutation == "wrapper_count":
        raw["slots"].pop()
        raw["pages"]["childCount"] = 20
    elif mutation == "seek_max":
        raw["seek"]["max"] = "23"
    elif mutation == "lead_role":
        raw["slots"][0]["classes"] = ["-cv-page", "mode-empty", "mode-pr"]
    elif mutation == "tail_role":
        raw["slots"][16]["classes"] = ["-cv-page", "mode-empty", "mode-pr"]
    elif mutation == "body_role":
        raw["slots"][8]["classes"] = ["-cv-page", "mode-empty", "mode-pr"]
    else:
        raw = _snapshot(1, standard15_body=True)
        raw["terminalMarkerParentIndex"] = 19

    with pytest.raises(UnknownPageStateError):
        _parse_viewer_observation(raw, expected_url=EPISODE_URL)


def test_younganimal_standard15_body_profile_rejects_wrong_interstitial_marker_or_center() -> None:
    marker_drift = _snapshot(5, standard15_body=True)
    marker_drift["viewerClasses"].remove("mode-ci-page")
    center_drift = _snapshot(3, standard15_body=True)
    center_drift["slots"][19]["wrapperCenterInViewport"] = False

    for raw in (marker_drift, center_drift):
        with pytest.raises(UnknownPageStateError):
            _parse_viewer_observation(raw, expected_url=EPISODE_URL)


@pytest.mark.parametrize("marker", ["mode-has-pr", "mode-has-comic-info", "mode-has-good-page"])
def test_younganimal_standard_odd_body_requires_each_capability_marker(marker: str) -> None:
    raw = _snapshot(13, odd_body_count=7)
    raw["viewerClasses"].remove(marker)

    with pytest.raises(UnknownPageStateError, match="capability markers"):
        _parse_viewer_observation(raw, expected_url=EPISODE_URL)


@pytest.mark.parametrize("mutation", ["even_body_count", "other_body_center", "body_pair_missing_center"])
def test_younganimal_standard_odd_body_rejects_unsupported_shape_or_center(mutation: str) -> None:
    if mutation == "even_body_count":
        raw = _snapshot(13, odd_body_count=8)
    elif mutation == "other_body_center":
        raw = _snapshot(13, odd_body_count=7)
        raw["slots"][4]["wrapperCenterInViewport"] = True
    else:
        raw = _snapshot(11, odd_body_count=7)
        raw["slots"][3]["wrapperCenterInViewport"] = False

    with pytest.raises(UnknownPageStateError):
        _parse_viewer_observation(raw, expected_url=EPISODE_URL)


@pytest.mark.parametrize(
    "mutation", ["horizontal", "top_empty", "pr_capability", "ci_capability", "good_capability",
                 "vertical", "single", "lead", "lead_canvas", "range", "tail", "phase", "other_center",
                 "missing_half", "end_parent", "end_duplicate", "end_hidden", "end_offscreen"],
)
def test_younganimal_no_top_pr_odd_body_rejects_unproven_layout(mutation: str) -> None:
    raw = _snapshot(1 if mutation.startswith("end_") else 35, odd_body_count=29, no_top_pr=True)
    flags = {"horizontal": "mode-h", "top_empty": "mode-has-top-emptypage", "pr_capability": "mode-has-pr",
             "ci_capability": "mode-has-comic-info", "good_capability": "mode-has-good-page"}
    if mutation in flags:
        raw["viewerClasses"].remove(flags[mutation])
    elif mutation in {"vertical", "single"}:
        raw["viewerClasses"].append("mode-v" if mutation == "vertical" else "mode-single")
    elif mutation == "lead":
        raw["slots"][0]["classes"].append("mode-pr")
    elif mutation == "lead_canvas":
        raw["slots"][0]["canvasCount"] = 1
        raw["slots"][0]["canvas"] = raw["slots"][1]["canvas"]
    elif mutation == "range":
        raw["seek"]["max"] = "37"
    elif mutation == "tail":
        raw["slots"][30]["classes"] = ["-cv-page", "mode-empty", "mode-pr"]
    elif mutation == "phase":
        raw["viewerClasses"].append("mode-top-pr-page")
    elif mutation == "other_center":
        raw["slots"][3]["wrapperCenterInViewport"] = True
    elif mutation == "missing_half":
        raw = _snapshot(33, odd_body_count=29, no_top_pr=True)
        raw["slots"][3]["wrapperCenterInViewport"] = False
    elif mutation == "end_parent":
        raw["terminalMarkerParentIndex"] = 33
    elif mutation == "end_duplicate":
        raw["terminalMarkerCount"] = 2
    elif mutation == "end_hidden":
        raw["terminalMarkerVisible"] = False
    else:
        raw["terminalMarkerCenterInViewport"] = False
    with pytest.raises(UnknownPageStateError):
        _parse_viewer_observation(raw, expected_url=EPISODE_URL)


@pytest.mark.parametrize(("body_count", "no_lead"), [(6, False), (10, False), (5, True), (13, True), (6, True), (12, True), (5, False), (11, False)])
def test_younganimal_top_empty_no_ci_profile_maps_all_observed_roles_and_seek_states(
    body_count: int, no_lead: bool,
) -> None:
    body_start = 0 if no_lead else 1
    wrapper_count = body_count + body_start + 4
    even_wrappers = wrapper_count % 2 == 0
    maximum = wrapper_count - int(even_wrappers)
    pr_slots = (body_count + body_start, body_count + body_start + 1)
    good_slot = wrapper_count - 2
    last_slot = wrapper_count - 1
    for value in range(maximum, 0, -2):
        raw = _top_empty_no_ci_snapshot(value, body_count=body_count, no_lead=no_lead)
        observation = _parse_viewer_observation(raw, expected_url=EPISODE_URL)
        focus = maximum - value + 1
        centers = tuple(index for index in (focus - 1, focus) if 0 <= index < wrapper_count)
        body_centers = tuple(index for index in centers if body_start <= index < body_start + body_count)
        expected_state = "end" if value == 1 else "ad" if value == 3 else "content"
        expected_active = (last_slot,) if value == 1 else () if value == 3 else body_centers

        expected_variant = (
            "no_lead_no_ci_even_body" if no_lead and even_wrappers else
            "no_lead_no_ci" if no_lead else
            "top_empty_no_ci_odd_body" if even_wrappers else "top_empty_no_ci"
        )
        assert observation.layout_variant == expected_variant
        assert observation.body_slots == tuple(range(body_start, body_start + body_count))
        assert observation.ci_slot is None
        assert observation.pr_slots == pr_slots
        assert observation.good_slot == good_slot
        assert observation.last_slot == last_slot
        assert observation.initial_blank is False
        assert observation.page_state == expected_state
        assert observation.active_slots == expected_active
        assert tuple(
            slot["index"]
            for slot in raw["slots"]
            if slot["wrapperCenterInViewport"] is True
        ) == centers
        if expected_state == "content":
            assert observation.ready_slots == expected_active


@pytest.mark.parametrize(
    ("mutation", "seek_value"),
    [
        ("missing_horizontal", 15),
        ("missing_spread", 15),
        ("missing_rtl", 15),
        ("missing_nav_rtl", 15),
        ("missing_top_empty", 15),
        ("missing_pr_capability", 15),
        ("missing_good_capability", 15),
        ("comic_info_flag", 15),
        ("vertical_flag", 15),
        ("single_page_flag", 15),
        ("top_pr_marker", 15),
        ("top_pr_lead_role", 15),
        ("missing_first_marker", 15),
        ("ci_marker", 5),
        ("missing_pr_marker", 3),
        ("early_last_marker", 5),
        ("wrong_pr_phase", 5),
        ("wrong_terminal_pr", 1),
        ("wrong_seek_max", 15),
        ("odd_body_role", 13),
        ("extra_ci_role", 15),
        ("tail_role", 15),
        ("tail_canvas", 15),
        ("extra_center", 13),
        ("missing_center", 11),
        ("last_marker_parent", 1),
        ("last_marker_missing", 1),
        ("last_marker_duplicate", 1),
        ("last_marker_hidden", 1),
        ("last_marker_offscreen", 1),
        ("last_wrapper_center", 1),
    ],
)
@pytest.mark.parametrize(("no_lead", "body_count"), [(False, 10), (True, 11), (True, 12), (False, 11)])
def test_younganimal_top_empty_no_ci_profile_rejects_unobserved_markers_roles_and_geometry(
    mutation: str, seek_value: int, no_lead: bool, body_count: int,
) -> None:
    raw = _top_empty_no_ci_snapshot(seek_value, body_count=body_count, no_lead=no_lead)
    classes = raw["viewerClasses"]
    if mutation == "missing_horizontal":
        classes.remove("mode-h")
    elif mutation == "missing_spread":
        classes.remove("mode-spread")
    elif mutation == "missing_rtl":
        classes.remove("mode-dir-rtl")
    elif mutation == "missing_nav_rtl":
        classes.remove("mode-nav-dir-rtl")
    elif mutation == "missing_top_empty":
        if no_lead:
            classes.append("mode-has-top-emptypage")
        else:
            classes.remove("mode-has-top-emptypage")
    elif mutation == "missing_pr_capability":
        classes.remove("mode-has-pr")
    elif mutation == "missing_good_capability":
        classes.remove("mode-has-good-page")
    elif mutation in {"comic_info_flag", "vertical_flag", "single_page_flag"}:
        classes.append({
            "comic_info_flag": "mode-has-comic-info",
            "vertical_flag": "mode-v",
            "single_page_flag": "mode-single",
        }[mutation])
    elif mutation == "top_pr_marker":
        classes.append("mode-top-pr-page")
    elif mutation == "top_pr_lead_role":
        raw["slots"][0]["classes"] = ["-cv-page", "mode-empty", "mode-pr", "mode-top-pr"]
    elif mutation == "missing_first_marker":
        classes.remove("mode-first-page")
    elif mutation == "ci_marker":
        classes.append("mode-ci-page")
    elif mutation == "missing_pr_marker":
        classes.remove("mode-pr-page")
    elif mutation == "early_last_marker":
        classes.append("mode-last-page")
    elif mutation in {"wrong_pr_phase", "wrong_terminal_pr"}:
        if "mode-pr-page" in classes:
            classes.remove("mode-pr-page")
        else:
            classes.append("mode-pr-page")
    elif mutation == "wrong_seek_max":
        raw["seek"]["max"] = "14"
    elif mutation == "odd_body_role":
        raw["slots"][4]["classes"] = ["-cv-page", "mode-empty", "mode-pr"]
        raw["slots"][4]["canvasCount"] = 0
        raw["slots"][4]["canvas"] = None
    elif mutation == "extra_ci_role":
        raw["slots"][10]["classes"] = ["-cv-page", "mode-ci"]
    elif mutation == "tail_role":
        raw["slots"][11]["classes"] = ["-cv-page", "mode-good"]
    elif mutation == "tail_canvas":
        raw["slots"][-3]["canvasCount"] = 1
        raw["slots"][-3]["canvas"] = dict(raw["slots"][4]["canvas"])
    elif mutation == "extra_center":
        raw["slots"][4]["wrapperCenterInViewport"] = True
    elif mutation == "missing_center":
        raw["slots"][4]["wrapperCenterInViewport"] = False
    elif mutation == "last_marker_parent":
        raw["terminalMarkerParentIndex"] -= 1
    elif mutation == "last_marker_missing":
        raw["terminalMarkerCount"] = 0
    elif mutation == "last_marker_duplicate":
        raw["terminalMarkerCount"] = 2
    elif mutation == "last_marker_hidden":
        raw["terminalMarkerVisible"] = False
    elif mutation == "last_marker_offscreen":
        raw["terminalMarkerCenterInViewport"] = False
    else:
        raw["slots"][-1]["wrapperCenterInViewport"] = False

    with pytest.raises(UnknownPageStateError):
        _parse_viewer_observation(raw, expected_url=EPISODE_URL)


@pytest.mark.parametrize(
    ("seek_value", "marker", "remove"),
    [
        (21, "mode-top-pr-page", True),
        (21, "mode-pr-page", False),
        (19, "mode-ci-page", False),
        (5, "mode-first-page", False),
        (3, "mode-ci-page", False),
        (1, "mode-top-pr-page", False),
    ],
)
def test_younganimal_standard15_body_rejects_noncanonical_viewer_marker_sets(
    seek_value: int, marker: str, remove: bool
) -> None:
    raw = _snapshot(seek_value, standard15_body=True)
    if remove:
        raw["viewerClasses"].remove(marker)
    else:
        raw["viewerClasses"].append(marker)

    with pytest.raises(UnknownPageStateError, match="page markers changed"):
        _parse_viewer_observation(raw, expected_url=EPISODE_URL)


def test_younganimal_atomic_png_decoder_checks_slot_pixels_and_dimensions() -> None:
    image = Image.new("RGBA", (3, 2), (17, 29, 41, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    png = buffer.getvalue()
    data_url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    _data, _sha256, fingerprint = decode_canvas_png(data_url, width=3, height=2)

    captures = decode_capture_results(
        {
            "ok": True,
            "images": [
                {
                    "slot": 1,
                    "width": 3,
                    "height": 2,
                    "pixel_fingerprint": fingerprint,
                    "png": data_url,
                }
            ],
        },
        expected_slots=(1,),
    )
    assert len(captures) == 1
    assert captures[0].data == png
    assert (captures[0].width, captures[0].height, captures[0].mime_type) == (3, 2, "image/png")

    with pytest.raises(UnknownPageStateError, match="pixels disagree"):
        decode_capture_results(
            {
                "ok": True,
                "images": [
                    {
                        "slot": 1,
                        "width": 3,
                        "height": 2,
                        "pixel_fingerprint": "wrong",
                        "png": data_url,
                    }
                ],
            },
            expected_slots=(1,),
        )


def test_younganimal_native_decoder_binds_actual_source_and_target_draw_proof() -> None:
    image = Image.new("RGBA", (3, 2), (17, 29, 41, 111))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    png = buffer.getvalue()
    data_url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    decoded = native_capture.decode_native_images(
        [{
            "slot": 1, "width": 3, "height": 2, "png": data_url,
            "sourceWidth": 3, "sourceHeight": 2,
            "targetWidth": 8, "targetHeight": 6,
            "generation": 2, "writes": 9,
            "sourceGeneration": 0, "sourceWrites": 8,
        }],
        expected_slots=(1,),
    )

    assert len(decoded) == 1
    assert decoded[0].png == png
    assert (decoded[0].width, decoded[0].height) == (3, 2)
    assert (decoded[0].target_width, decoded[0].target_height) == (8, 6)
    assert (decoded[0].generation, decoded[0].writes) == (2, 9)
    assert (decoded[0].source_generation, decoded[0].source_writes) == (0, 8)
    with pytest.raises(UnknownPageStateError, match="spread is incomplete"):
        native_capture.decode_native_images([], expected_slots=(1, 2))


@pytest.mark.parametrize(
    ("field", "value"),
    [("slot", True), ("sourceWidth", 4), ("targetWidth", True), ("writes", True)],
)
def test_younganimal_native_decoder_rejects_malformed_draw_proof(field: str, value: object) -> None:
    image = Image.new("RGBA", (3, 2), (17, 29, 41, 111))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    item: dict[str, object] = {
        "slot": 1, "width": 3, "height": 2,
        "sourceWidth": 3, "sourceHeight": 2,
        "png": "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii"),
        "targetWidth": 8, "targetHeight": 6,
        "generation": 2, "writes": 9,
        "sourceGeneration": 0, "sourceWrites": 8,
    }
    item[field] = value

    with pytest.raises(UnknownPageStateError, match="dimensions or draw proof"):
        native_capture.decode_native_images([item], expected_slots=(1,))


def test_younganimal_native_webp_is_lossless_or_returns_verified_png(monkeypatch) -> None:
    image = Image.new("RGBA", (3, 2))
    image.putdata([(17, 29, 41, alpha) for alpha in (0, 63, 127, 191, 223, 255)])
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    native = native_capture.NativeImage(
        slot=1, width=3, height=2, png=buffer.getvalue(),
        target_width=8, target_height=6, generation=2, writes=9,
        source_generation=0, source_writes=8,
    )
    result = native_capture.encode_native_webp((native,))[0]
    with Image.open(io.BytesIO(result.data)) as decoded:
        assert decoded.size == (3, 2)
        decoded.load()
        assert decoded.convert("RGBA").tobytes() == image.tobytes()
        if result.mime_type == "image/webp":
            assert native_capture._single_vp8l(result.data, width=3, height=2)
        else:
            assert result.data == native.png

    monkeypatch.setattr(native_capture.features, "check", lambda _name: False)
    fallback = native_capture.encode_native_webp((native,))[0]
    assert fallback.data == native.png
    assert (fallback.mime_type, fallback.file_extension) == ("image/png", ".png")


def test_younganimal_native_failure_details_are_bounded_and_drop_page_content() -> None:
    sanitized = _native_failure_details(
        {
            "expected": {
                "path": "/episodes/55889b8a851cb?secret=1",
                "seekValue": 49,
                "domGeneration": 7,
                "captureDomGeneration": 5,
                "wrapperCount": 22,
                "activeSlots": [2, 3, 4],
                "viewport": {"width": 1906, "height": 986, "dpr": 1.5},
                "cookie": "must-not-survive",
            },
            "observed": {
                "path": "/episodes/55889b8a851cb",
                "seekValue": 49,
                "domGeneration": 8,
                "captureDomGeneration": 5,
                "viewerIdentity": True,
                "pagesIdentity": True,
                "seekIdentity": True,
                "wrapperCount": 22,
                "activeSlots": [2, 3],
                "viewport": {"width": 1906, "height": 986, "dpr": 1.5},
            },
            "selected": [
                {
                    "slot": 2,
                    "targetSame": True,
                    "readbackAvailable": False,
                    "pixelsMatchProof": True,
                    "targetRect": [10, 20, 30, 40],
                    "data": "data:image/png;base64,not-for-diagnostics",
                }
            ],
            "mutations": {
                "available": True,
                "complete": True,
                "coverageContiguous": True,
                "fromGeneration": 7,
                "toGeneration": 8,
                "droppedCount": 0,
                "unrecordedCount": 0,
                "records": [
                    {
                        "generation": 8,
                        "captureGeneration": 5,
                        "kind": "attributes",
                        "targetArea": "wrapper_descendant",
                        "targetNode": 4,
                        "slot": 46,
                        "attributeName": "class",
                        "changed": False,
                        "sameAssignment": True,
                        "canonicalCiWrapper": True,
                        "classTokenSetsSame": True,
                        "canonicalCiClassNoop": True,
                        "ciScrollWidgetTarget": True,
                        "ciScrollWidgetClassNoop": True,
                        "classAdded": ["mode-overflow", "mode-scroll-bottom", "private-user-token"],
                        "classRemoved": [],
                        "href": "https://example.invalid/?private=1",
                    }
                ],
            },
        }
    )
    encoded = str(sanitized)

    assert sanitized["expected"]["path"] == "<changed>"
    assert sanitized["expected"]["activeSlots"] is None
    assert sanitized["expected"]["captureDomGeneration"] == 5
    assert sanitized["observed"]["captureDomGeneration"] == 5
    assert sanitized["selected"][0]["targetSame"] is True
    assert sanitized["selected"][0]["readbackAvailable"] is False
    assert sanitized["selected"][0]["pixelsMatchProof"] is None
    assert sanitized["mutations"]["records"][0]["sameAssignment"] is True
    assert sanitized["mutations"]["records"][0]["captureGeneration"] == 5
    assert sanitized["mutations"]["records"][0]["canonicalCiClassNoop"] is True
    assert sanitized["mutations"]["records"][0]["targetArea"] == "wrapper_descendant"
    assert sanitized["mutations"]["records"][0]["ciScrollWidgetTarget"] is True
    assert sanitized["mutations"]["records"][0]["ciScrollWidgetClassNoop"] is True
    assert sanitized["mutations"]["coverageContiguous"] is True
    assert sanitized["mutations"]["records"][0]["classAdded"] == ["mode-overflow", "mode-scroll-bottom"]
    assert "secret=1" not in encoded
    assert "must-not-survive" not in encoded
    assert "data:image" not in encoded
    assert "example.invalid" not in encoded

    assert _native_failure_reason("native_reader_layout_changed") == "native_reader_layout_changed"
    assert _native_failure_reason("arbitrary page text") == "unrecognized_native_verification_failure"
