from __future__ import annotations

import asyncio

import pytest
from playwright.async_api import Error as PlaywrightError

from screenshot_crawler.core.capture import CaptureResult
from screenshot_crawler.core.errors import PageChangeTimeoutError, UnknownPageStateError
from screenshot_crawler.site_adapters.hanayume import adapter as hanayume_adapter
from screenshot_crawler.site_adapters.hanayume.adapter import (
    HanayumeAdapter,
    _capture_output_format,
    _episode_row_signature,
    _expected_active_slots,
    _matches_episode_preview,
    _parse_series_ranges,
    _parse_viewer_observation,
    _preview_is_unselected,
)

WORK_ID = "1f9f5b0d4cd52"


async def test_hanayume_initial_canvas_deadline_bounds_a_stalled_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hanayume_adapter, "INITIAL_CANVAS_SETTLE_TIMEOUT_MS", 20)
    adapter = HanayumeAdapter()

    async def stalled_observation(_page, **_kwargs):
        await asyncio.Future()

    monkeypatch.setattr(adapter, "_observe", stalled_observation)
    with pytest.raises(PageChangeTimeoutError, match="initial canvas did not settle"):
        await asyncio.wait_for(
            adapter._wait_for_observation(
                None, lambda _: True, reason="initial canvas did not settle",
                initial_canvas_slots=(1,),
            ),
            timeout=0.5,
        )
    assert adapter._initial_canvas_settle["status"] == "timeout"
    assert adapter._captured_slots == []


@pytest.mark.parametrize(
    ("result", "error", "reason"),
    [
        (None, TimeoutError(), "verification_timeout"),
        (None, PlaywrightError("synthetic evaluation failure"), "verification_evaluation_failed"),
        (True, None, "verification_result_malformed"),
        ({"ok": "true"}, None, "verification_result_malformed"),
        ({"ok": False, "reason": "proof_missing"}, None, "proof_missing"),
    ],
)
async def test_hanayume_native_verification_transport_failure_is_diagnostic_and_closed(
    result, error, reason: str,
) -> None:
    class FakePage:
        async def evaluate(self, _script, _token):
            if error is not None:
                raise error
            return result

    adapter = HanayumeAdapter()
    assert await adapter._verify_native_capture(FakePage(), "h1") is False
    debug = await adapter.collect_debug_metadata(FakePage())
    assert debug["capture"]["verification"] == {"ok": False, "reason": reason}


def _episode_rows(ids: tuple[str, ...], label: str = "無料") -> list[dict[str, object]]:
    return [
        {
            "linkCount": 1,
            "href": f"https://hanayume.com/episodes/{episode_id}",
            "labels": [label],
        }
        for episode_id in ids
    ]


def test_hanayume_preview_signature_is_exact_or_observed_reverse_only() -> None:
    preview = _episode_row_signature(_episode_rows(("0000000000001", "0000000000002")))

    assert _matches_episode_preview(preview, preview)
    assert _matches_episode_preview(tuple(reversed(preview)), preview)
    assert not _matches_episode_preview((), preview)
    assert not _matches_episode_preview(preview[:1], preview)
    assert not _matches_episode_preview(
        _episode_row_signature(_episode_rows(("0000000000001", "0000000000002"), "今なら無料")),
        preview,
    )
    three_row_preview = _episode_row_signature(
        _episode_rows(("0000000000001", "0000000000002", "0000000000003"))
    )
    arbitrary_order = _episode_row_signature(
        _episode_rows(("0000000000002", "0000000000001", "0000000000003"))
    )
    assert not _matches_episode_preview(arbitrary_order, three_row_preview)


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [
            {"linkCount": 1, "href": "https://hanayume.com/episodes/0000000000001?x=1", "labels": ["無料"]}
        ],
        _episode_rows(("0000000000001", "0000000000001")),
        [{"linkCount": 2, "href": "https://hanayume.com/episodes/0000000000001", "labels": ["無料"]}],
    ],
    ids=("empty", "query-url", "duplicate-id", "duplicate-link"),
)
def test_hanayume_preview_signature_rejects_incomplete_or_ambiguous_rows(
    rows: list[dict[str, object]],
) -> None:
    with pytest.raises(UnknownPageStateError):
        _episode_row_signature(rows)


def test_hanayume_preview_absence_requires_unselected_range_navigation() -> None:
    assert _preview_is_unselected([{"current": False}, {"current": False}])
    assert not _preview_is_unselected([{"current": False}, {"current": True}])
    assert not _preview_is_unselected([])
    assert not _preview_is_unselected([{"current": "false"}])


def test_capture_output_format_reports_mixed_native_and_rendered_captures() -> None:
    captures = [
        CaptureResult(b"webp", 2, 3, "image/webp", ".webp"),
        CaptureResult(b"png", 2, 3),
    ]

    assert _capture_output_format(captures) == "mixed"


@pytest.mark.asyncio
async def test_batch_direct_strategy_uses_the_observed_free_viewer_path() -> None:
    adapter = HanayumeAdapter()

    await adapter.configure_run(None, "direct")

    with pytest.raises(UnknownPageStateError):
        await adapter.configure_run(None, "quota")


@pytest.mark.asyncio
async def test_capture_budget_timeout_fails_closed_without_generic_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = HanayumeAdapter()
    monkeypatch.setattr(hanayume_adapter, "CAPTURE_BUDGET_SECONDS", 0.001)

    async def slow_capture(_page) -> None:
        await asyncio.sleep(0.05)

    adapter._capture_page_within_budget = slow_capture  # type: ignore[method-assign]
    with pytest.raises(UnknownPageStateError, match="atomic capture exceeded"):
        await adapter.capture_page(None)  # type: ignore[arg-type]

    assert adapter._capture_diagnostics == {
        "mode": "capture_failed",
        "reason": "capture_budget_exceeded",
    }


@pytest.mark.asyncio
async def test_hanayume_leading_empty_page_has_no_content_identity() -> None:
    adapter = HanayumeAdapter()
    observation = _parse_viewer_observation(_viewer_snapshot(top_empty=True))

    async def intro(_page, *, include_png: bool = False):
        del include_png
        return observation

    adapter._observe = intro  # type: ignore[method-assign]
    with pytest.raises(UnknownPageStateError, match="non-body lead-in"):
        await adapter.get_content_identity(None)  # type: ignore[arg-type]


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


def _viewer_snapshot(
    *, current: int = 1, visible: tuple[int, ...] | None = None, top_empty: bool = False,
    padded_counter: bool = False, total: int = 9,
) -> dict[str, object]:
    last_slot = total - int(padded_counter)
    body_slots = tuple(range(2 if top_empty else 1, last_slot - 4))
    visible = visible if visible is not None else _expected_active_slots(current, body_slots)
    viewport = {"width": 1906, "height": 986}
    slots = []
    for index in range(last_slot + 1):
        if index == 0:
            classes = ["-cv-page", "mode-empty", "mode-pr", "mode-top-pr"]
        elif index == 1 and top_empty:
            classes = ["-cv-page", "mode-empty"]
        elif index == last_slot - 4:
            classes = ["-cv-page", "mode-ci"]
        elif index in {last_slot - 3, last_slot - 2}:
            classes = ["-cv-page", "mode-empty", "mode-pr"]
        elif index == last_slot - 1:
            classes = ["-cv-page", "mode-good"]
        elif index == last_slot:
            classes = ["-cv-page", "mode-last"]
        else:
            classes = ["-cv-page"]
            if index in visible:
                classes += ["mode-loaded", "mode-rendered"]
        selected = index in visible and index in body_slots
        if selected:
            wrapper_x = 0 if index == current else 100
        elif top_empty and current == 1 and index == 1:
            wrapper_x = 0
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
        "viewerClasses": [
            "-cv", "mode-spread",
            *( ["mode-has-top-emptypage"] if top_empty else [] ),
            *( ["mode-first-page"] if top_empty and current == 1 else [] ),
        ],
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
    assert _expected_active_slots(3, observation.body_slots) == (2, 3)


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


def test_hanayume_viewer_accepts_observed_loaded_request_render_preload_as_not_ready() -> None:
    snapshot = _viewer_snapshot()
    slots = snapshot["slots"]
    assert isinstance(slots, list)
    slots[2]["classes"] = ["-cv-page", "mode-loaded", "mode-req-render"]
    slots[2]["wrapperCenterInViewport"] = False
    slots[2]["canvasCount"] = 0
    slots[2]["canvas"] = None

    observation = _parse_viewer_observation(snapshot)

    assert observation.active_slots == (1,)
    assert observation.ready_slots == (1,)


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
    assert observation.ready_slots != _expected_active_slots(3, observation.body_slots)


@pytest.mark.parametrize("current", [1, 3, 11, 17])
def test_hanayume_padded_counter_uses_complete_physical_tail_and_body(current: int) -> None:
    snapshot = _viewer_snapshot(current=current, total=17, padded_counter=True)
    if current == 17:
        snapshot["viewerClasses"].append("mode-last-page")
    observation = _parse_viewer_observation(snapshot)
    assert observation.total == 17
    assert len(observation.raw["slots"]) == 17
    assert observation.body_total == 11
    assert observation.body_slots == tuple(range(1, 12))
    assert observation.active_slots == observation.ready_slots == (
        () if current == 17 else (1,) if current == 1 else (current - 1, current)
    )
    assert observation.terminal == (current == 17)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw["slots"].pop(),
        lambda raw: raw["slots"].append({"index": 17, "classes": ["-cv-page"]}),
        lambda raw: raw["slots"][12].update(classes=["-cv-page"]),
        lambda raw: raw["slots"][11].update(classes=["-cv-page", "mode-empty"]),
        lambda raw: raw["slots"][16].update(classes=["-cv-page", "mode-good"]),
        lambda raw: raw["viewerClasses"].append("mode-has-top-emptypage"),
    ],
)
def test_hanayume_padded_counter_rejects_missing_or_changed_layout(mutate) -> None:
    snapshot = _viewer_snapshot(total=17, padded_counter=True)
    mutate(snapshot)
    with pytest.raises(UnknownPageStateError):
        _parse_viewer_observation(snapshot)


def test_hanayume_viewer_uses_physical_body_slots_for_observed_top_empty_layout() -> None:
    intro = _parse_viewer_observation(_viewer_snapshot(top_empty=True))
    assert intro.has_top_empty_page is True
    assert intro.body_slots == (2, 3, 4)
    assert intro.body_total == 3
    assert intro.active_slots == ()
    assert intro.ready_slots == ()
    assert intro.raw["slots"][1]["wrapperCenterInViewport"] is True

    first_spread = _parse_viewer_observation(_viewer_snapshot(current=3, top_empty=True))
    assert first_spread.body_slots == (2, 3, 4)
    assert first_spread.active_slots == (2, 3)
    assert first_spread.ready_slots == (2, 3)
    assert _expected_active_slots(5, first_spread.body_slots) == (4,)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda snapshot: snapshot["viewerClasses"].remove("mode-has-top-emptypage"),
        lambda snapshot: snapshot["slots"][1].update(classes=["-cv-page", "mode-empty", "mode-pr"]),
        lambda snapshot: snapshot["slots"][1].update(canvasCount=1, canvas={"width": 1, "height": 1}),
        lambda snapshot: snapshot["slots"][2].update(classes=["-cv-page", "mode-empty"]),
    ],
)
def test_hanayume_top_empty_layout_rejects_unobserved_or_interior_empty_state(mutate) -> None:
    snapshot = _viewer_snapshot(top_empty=True)
    mutate(snapshot)
    with pytest.raises(UnknownPageStateError):
        _parse_viewer_observation(snapshot)


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
    assert observation.ready_slots != _expected_active_slots(3, observation.body_slots)
