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
    single_pr_body_count: int | None = None,
) -> dict[str, object]:
    viewer_classes = {"-cv", "mode-spread", "mode-dir-rtl", "mode-nav-dir-rtl"}
    odd_body_profile = standard15_body or odd_body_count is not None
    body_count = single_pr_body_count if single_pr_body_count is not None else odd_body_count if odd_body_count is not None else 15 if standard15_body else 16
    seek_max = body_count + 5 if single_pr_body_count is not None else body_count + 6 if odd_body_profile else 21
    if odd_body_profile or single_pr_body_count is not None:
        viewer_classes.update({"mode-has-pr", "mode-has-comic-info", "mode-has-good-page"})
    if single_pr_body_count is not None:
        viewer_classes.add("mode-h")
    if seek_value == seek_max:
        viewer_classes.update({"mode-first-page", "mode-top-pr-page"})
    elif seek_value == 5:
        viewer_classes.update({"mode-pr-page", "mode-ci-page"})
    elif seek_value == 3:
        viewer_classes.add("mode-pr-page")
    elif seek_value == 1:
        viewer_classes.update({"mode-pr-page", "mode-last-page"})
    body_slots = tuple(range(1, body_count + 1))
    ci_slot = body_slots[-1] + 1
    wrapper_count = ci_slot + (4 if single_pr_body_count is not None else 5)
    if (odd_body_profile or single_pr_body_count is not None) and seek_value == 1:
        viewer_classes.discard("mode-pr-page")
    slots: list[dict[str, object]] = []
    for index in range(wrapper_count):
        if index == 0:
            classes = {"-cv-page", "mode-empty", "mode-pr", "mode-top-pr"}
        elif index in body_slots:
            classes = {"-cv-page", "mode-loaded", "mode-rendered"}
        elif index == ci_slot:
            classes = {"-cv-page", "mode-ci"}
        elif index in ({ci_slot + 1} if single_pr_body_count is not None else {ci_slot + 1, ci_slot + 2}):
            classes = {"-cv-page", "mode-empty", "mode-pr"}
        elif index == ci_slot + (2 if single_pr_body_count is not None else 3):
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


def _top_empty_no_ci_snapshot(seek_value: int, *, body_count: int = 10) -> dict[str, object]:
    if body_count < 4 or body_count % 2:
        raise ValueError("fixture body_count must be an even value of at least four")
    seek_max = body_count + 5
    viewer_classes = {
        "-cv", "mode-h", "mode-spread", "mode-dir-rtl", "mode-nav-dir-rtl",
        "mode-has-top-emptypage", "mode-has-pr", "mode-has-good-page",
    }
    if seek_value == seek_max:
        viewer_classes.add("mode-first-page")
    elif seek_value in {5, 3}:
        viewer_classes.add("mode-pr-page")
    elif seek_value == 1:
        viewer_classes.add("mode-last-page")
    focus = seek_max - seek_value + 1
    wrapper_count = seek_max
    slots: list[dict[str, object]] = []
    for index in range(wrapper_count):
        if index == 0:
            classes = {"-cv-page", "mode-empty"}
        elif index <= body_count:
            classes = {"-cv-page", "mode-loaded", "mode-rendered"}
        elif index <= body_count + 2:
            classes = {"-cv-page", "mode-empty", "mode-pr"}
        elif index == body_count + 3:
            classes = {"-cv-page", "mode-good"}
        else:
            classes = {"-cv-page", "mode-last"}
        rect_x = 945 + ((focus - index - 1) * 946)
        canvas = None
        canvas_count = 0
        if 1 <= index <= body_count:
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
    observed = _parse_viewer_observation(_snapshot(seek, single_pr_body_count=6), expected_url=EPISODE_URL)

    assert observed.layout_variant == "standard_single_pr"
    assert observed.body_slots == tuple(range(1, 7))
    assert (observed.ci_slot, observed.pr_slots, observed.good_slot, observed.last_slot) == (7, (8,), 9, 10)
    assert observed.seek_max == 11
    assert observed.page_state == state
    assert observed.active_slots == active
    if state == "content":
        assert observed.ready_slots == active


@pytest.mark.parametrize(
    "mutation",
    ["capability", "vertical", "single", "top_empty", "range", "tail", "tail_canvas",
     "body", "phase", "center", "end_parent", "end_duplicate", "end_invisible", "end_offscreen"],
)
def test_younganimal_single_pr_rejects_role_phase_or_terminal_drift(mutation: str) -> None:
    raw = _snapshot(1 if mutation.startswith("end_") else 11, single_pr_body_count=6)
    if mutation == "capability":
        raw["viewerClasses"].remove("mode-has-comic-info")
    elif mutation in {"vertical", "single", "top_empty"}:
        raw["viewerClasses"].append({"vertical": "mode-v", "single": "mode-single", "top_empty": "mode-has-top-emptypage"}[mutation])
    elif mutation == "range":
        raw["seek"]["max"] = "13"
    elif mutation == "tail":
        raw["slots"][9]["classes"] = ["-cv-page", "mode-empty", "mode-pr"]
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
        raw["terminalMarkerParentIndex"] = 9
    elif mutation == "end_duplicate":
        raw["terminalMarkerCount"] = 2
    elif mutation == "end_invisible":
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


@pytest.mark.parametrize("body_count", [7, 9, 15])
def test_younganimal_standard_odd_body_profile_maps_markers_and_selected_centers(body_count: int) -> None:
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
        raw = _snapshot(seek_value, odd_body_count=body_count)
        observation = _parse_viewer_observation(raw, expected_url=EPISODE_URL)

        assert observation.layout_variant == "standard_odd_body"
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


@pytest.mark.parametrize("body_count", [6, 10])
def test_younganimal_top_empty_no_ci_profile_maps_all_observed_roles_and_seek_states(
    body_count: int,
) -> None:
    maximum = body_count + 5
    pr_slots = (body_count + 1, body_count + 2)
    good_slot = body_count + 3
    last_slot = body_count + 4
    for value in range(maximum, 0, -2):
        raw = _top_empty_no_ci_snapshot(value, body_count=body_count)
        observation = _parse_viewer_observation(raw, expected_url=EPISODE_URL)
        focus = maximum - value + 1
        centers = tuple(index for index in (focus - 1, focus) if 0 <= index < maximum)
        body_centers = tuple(index for index in centers if 1 <= index <= body_count)
        expected_state = "end" if value == 1 else "ad" if value == 3 else "content"
        expected_active = (last_slot,) if value == 1 else () if value == 3 else body_centers

        assert observation.layout_variant == "top_empty_no_ci"
        assert observation.body_slots == tuple(range(1, body_count + 1))
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
        ("wrong_seek_max", 15),
        ("odd_body_role", 13),
        ("extra_ci_role", 15),
        ("tail_role", 15),
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
def test_younganimal_top_empty_no_ci_profile_rejects_unobserved_markers_roles_and_geometry(
    mutation: str, seek_value: int
) -> None:
    raw = _top_empty_no_ci_snapshot(seek_value)
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
        raw["slots"][14]["wrapperCenterInViewport"] = False

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
