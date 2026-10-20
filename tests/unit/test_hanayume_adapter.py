from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from playwright.async_api import Error as PlaywrightError

from screenshot_crawler.core.capture import CaptureResult
from screenshot_crawler.core.errors import (
    PageChangeTimeoutError,
    UnknownPageStateError,
    UnsupportedAccessStrategyError,
)
from screenshot_crawler.site_adapters.hanayume import adapter as hanayume_adapter
from screenshot_crawler.site_adapters.hanayume.adapter import (
    HanayumeAdapter,
    HanayumeNativeEpisodeAccess,
    _capture_output_format,
    _episode_row_signature,
    _expected_active_slots,
    _matches_episode_preview,
    _parse_series_ranges,
    _parse_viewer_observation,
    _preview_is_unselected,
)

WORK_ID = "1f9f5b0d4cd52"
EPISODE_ID = "0000000000002"


class _CurrentObserverPage:
    def __init__(self) -> None:
        self.main_frame = object()

    def on(self, _event: str, _callback) -> None:
        return None

    def remove_listener(self, _event: str, _callback) -> None:
        return None


def _current_access_event(
    page: _CurrentObserverPage,
    *,
    has_access: bool,
    url: str | None = None,
    frame: object | None = None,
    redirected_from: object | None = None,
    status: int = 200,
    body_gate: asyncio.Event | None = None,
    body_error: bool = False,
):
    request_url = url or f"https://hanayume.com/api/episodes/{EPISODE_ID}"
    request_frame = page.main_frame if frame is None else frame
    request = SimpleNamespace(
        url=request_url,
        method="GET",
        resource_type="fetch",
        frame=request_frame,
        is_navigation_request=lambda: False,
        redirected_from=redirected_from,
    )
    payload = {
        "episode": {
            "id": EPISODE_ID,
            "series": {"id": WORK_ID},
            "access": {
                "episodeId": EPISODE_ID,
                "accessType": "waitAndFree",
                "hasAccess": has_access,
                "timeRemainingInSeconds": 172800 if has_access else 0,
            },
        }
    }

    async def read_payload():
        if body_gate is not None:
            await body_gate.wait()
        if body_error:
            raise ValueError("synthetic malformed current access response")
        return payload

    response = SimpleNamespace(
        request=request,
        url=request_url,
        frame=request_frame,
        status=status,
        json=read_payload,
    )
    return request, response


def _native_series_row(requested_at: datetime) -> HanayumeNativeEpisodeAccess:
    return HanayumeNativeEpisodeAccess(
        episode_id=EPISODE_ID,
        access_type="waitAndFree",
        has_access=True,
        remaining_seconds=172800,
        requested_at=requested_at,
    )


def test_hanayume_latest_series_target_keeps_target_across_later_omission() -> None:
    adapter = HanayumeAdapter()
    adapter._episode_id = EPISODE_ID
    adapter._expected_work_id = WORK_ID
    requested_at = datetime(2026, 10, 17, tzinfo=UTC)
    target = _native_series_row(requested_at)
    snapshots = (
        SimpleNamespace(work_id=WORK_ID, rows=(target,)),
        SimpleNamespace(work_id=WORK_ID, rows=()),
    )

    latest, duplicate_at, foreign_at = adapter._latest_series_ticket_target(
        snapshots, current_requested_at=None
    )

    assert latest is target
    assert duplicate_at is None
    assert foreign_at is None


def test_hanayume_latest_series_target_reports_newer_foreign_work_collision() -> None:
    adapter = HanayumeAdapter()
    adapter._episode_id = EPISODE_ID
    adapter._expected_work_id = WORK_ID
    requested_at = datetime(2026, 10, 17, tzinfo=UTC)
    foreign_at = requested_at + timedelta(milliseconds=37)
    target = _native_series_row(requested_at)
    foreign_target = _native_series_row(foreign_at)
    snapshots = (
        SimpleNamespace(work_id=WORK_ID, rows=(target,)),
        SimpleNamespace(work_id="0000000000001", rows=(foreign_target,)),
    )

    latest, duplicate_at, conflict_at = adapter._latest_series_ticket_target(
        snapshots, current_requested_at=requested_at
    )

    assert latest is target
    assert duplicate_at is None
    assert conflict_at == foreign_at
    assert conflict_at > requested_at


@pytest.mark.parametrize(
    ("classes", "rental_stats", "expected"),
    [
        (["mode-current", "mode-store-item-blank", "series-eplist-item"], [], "blank"),
        (["mode-current", "mode-store-item-start", "series-eplist-item"], [], "blank"),
        (
            ["mode-current", "mode-store-item-start", "series-eplist-item", "extra"],
            [],
            "unknown",
        ),
        (
            ["mode-current", "mode-store-item-start", "series-eplist-item"],
            ["rental marker"],
            "unknown",
        ),
    ],
    ids=("blank", "unrented-store-start", "extra-class", "store-start-rental"),
)
def test_hanayume_ticket_account_row_accepts_only_observed_unrented_blank_shapes(
    classes: list[str], rental_stats: list[str], expected: str,
) -> None:
    state = {
        "targetRows": [{"classes": classes, "rentalStats": rental_stats}],
        "publicTargetRows": [{"classes": classes, "rentalStats": rental_stats}],
    }

    assert HanayumeAdapter._ticket_account_row_state(state) == expected


async def _observe_current_access(
    observer, page: _CurrentObserverPage, *, has_access: bool, **kwargs
):
    request, response = _current_access_event(
        page, has_access=has_access, **kwargs
    )
    observer._on_request(request)
    observer._on_response(response)
    await observer.wait_for_pending(0.1)
    return request, response


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kwargs", "status"),
    [
        ({"frame": object()}, 200),
        ({"redirected_from": object()}, 200),
        ({"url": f"https://hanayume.com/api/episodes/{EPISODE_ID}?stale=1"}, 200),
        ({}, 503),
    ],
    ids=("foreign-frame", "redirect", "query", "non-200"),
)
async def test_hanayume_current_episode_observer_rejects_untrusted_transport(
    kwargs: dict[str, object], status: int,
) -> None:
    page = _CurrentObserverPage()
    observer = hanayume_adapter._CurrentEpisodeAccessObserver(EPISODE_ID, WORK_ID)
    observer.attach(page)  # type: ignore[arg-type]
    await _observe_current_access(observer, page, has_access=True, status=status, **kwargs)

    with pytest.raises(UnknownPageStateError):
        observer.latest_access()
    await observer.close()


@pytest.mark.asyncio
async def test_hanayume_current_episode_observer_rejects_duplicate_response_event() -> None:
    page = _CurrentObserverPage()
    observer = hanayume_adapter._CurrentEpisodeAccessObserver(EPISODE_ID, WORK_ID)
    observer.attach(page)  # type: ignore[arg-type]
    _request, response = await _observe_current_access(observer, page, has_access=True)
    observer._on_response(response)

    with pytest.raises(UnknownPageStateError):
        observer.latest_access()
    await observer.close()


@pytest.mark.asyncio
async def test_hanayume_current_episode_observer_excludes_old_snapshot_after_attempt() -> None:
    page = _CurrentObserverPage()
    observer = hanayume_adapter._CurrentEpisodeAccessObserver(EPISODE_ID, WORK_ID)
    observer.attach(page)  # type: ignore[arg-type]
    _request, _response = await _observe_current_access(observer, page, has_access=True)
    snapshot = observer.latest_access()
    assert snapshot is not None

    assert observer.latest_access(
        after=snapshot.native.requested_at + timedelta(seconds=1)
    ) is None
    await observer.close()


@pytest.mark.asyncio
async def test_hanayume_current_episode_observer_prefers_newest_denial() -> None:
    page = _CurrentObserverPage()
    observer = hanayume_adapter._CurrentEpisodeAccessObserver(EPISODE_ID, WORK_ID)
    observer.attach(page)  # type: ignore[arg-type]
    await _observe_current_access(observer, page, has_access=True)
    await asyncio.sleep(0.002)
    await _observe_current_access(observer, page, has_access=False)

    latest = observer.latest_access()
    assert latest is not None and latest.native.has_access is False
    await observer.close()


@pytest.mark.asyncio
async def test_hanayume_current_episode_observer_does_not_use_old_snapshot_while_newer_body_is_pending() -> None:
    page = _CurrentObserverPage()
    observer = hanayume_adapter._CurrentEpisodeAccessObserver(EPISODE_ID, WORK_ID)
    observer.attach(page)  # type: ignore[arg-type]
    await _observe_current_access(observer, page, has_access=True)
    old = observer.latest_access()
    assert old is not None

    await asyncio.sleep(0.002)
    body_gate = asyncio.Event()
    request, response = _current_access_event(
        page, has_access=False, body_gate=body_gate
    )
    observer._on_request(request)
    observer._on_response(response)
    assert observer.has_pending_access(after=old.native.requested_at) is True

    body_gate.set()
    await observer.wait_for_pending(0.1)
    latest = observer.latest_access()
    assert latest is not None and latest.native.has_access is False
    await observer.close()


@pytest.mark.asyncio
async def test_hanayume_current_episode_observer_newer_invalid_response_blocks_old_snapshot() -> None:
    page = _CurrentObserverPage()
    observer = hanayume_adapter._CurrentEpisodeAccessObserver(EPISODE_ID, WORK_ID)
    observer.attach(page)  # type: ignore[arg-type]
    await _observe_current_access(observer, page, has_access=True)
    await asyncio.sleep(0.002)
    request, response = _current_access_event(
        page, has_access=False, body_error=True
    )
    observer._on_request(request)
    observer._on_response(response)
    await observer.wait_for_pending(0.1)

    with pytest.raises(UnknownPageStateError):
        observer.latest_access()
    await observer.close()


@pytest.mark.parametrize("resource_type", ["fetch", "other"])
@pytest.mark.parametrize("prefetch", [None, "1"])
def test_hanayume_batch_route_signature_accepts_only_observed_next_rsc_shape(
    resource_type: str, prefetch: str | None
) -> None:
    headers = {"rsc": "1"}
    if prefetch is not None:
        headers["next-router-prefetch"] = prefetch
    request = SimpleNamespace(
        url="https://hanayume.com/episodes/49b7e11049871?_rsc=flight",
        method="GET",
        headers=headers,
        resource_type=resource_type,
    )
    assert HanayumeAdapter()._batch_route_signature(request) is True


@pytest.mark.parametrize(
    ("url", "method", "headers", "resource_type"),
    [
        ("https://hanayume.com/series/34bf61d51ebc3", "GET", {"rsc": "1"}, "fetch"),
        (
            "https://hanayume.com/series/34bf61d51ebc3?_rsc=flight",
            "GET",
            {"next-router-prefetch": "1"},
            "fetch",
        ),
        (
            "https://hanayume.com/series/34bf61d51ebc3?_rsc=flight&_rsc=other",
            "GET",
            {"rsc": "1"},
            "fetch",
        ),
        (
            "https://hanayume.com/series/34bf61d51ebc3?_rsc=flight",
            "POST",
            {"rsc": "1"},
            "fetch",
        ),
        (
            "https://hanayume.com/series/34bf61d51ebc3?_rsc=flight",
            "GET",
            {"rsc": "1", "next-router-prefetch": "0"},
            "fetch",
        ),
        (
            "http://hanayume.com/series/34bf61d51ebc3?_rsc=flight",
            "GET",
            {"rsc": "1"},
            "fetch",
        ),
        (
            "https://example.com/series/34bf61d51ebc3?_rsc=flight",
            "GET",
            {"rsc": "1"},
            "fetch",
        ),
        (
            "https://hanayume.com/series/34bf61d51ebc3?_rsc=flight",
            "GET",
            {"rsc": "1"},
            "image",
        ),
        (
            "https://hanayume.com/episodes/not-an-id?_rsc=flight",
            "GET",
            {"rsc": "1"},
            "fetch",
        ),
        (
            "https://hanayume.com/episodes/49b7e11049871/unknown?_rsc=flight",
            "GET",
            {"rsc": "1"},
            "fetch",
        ),
        (
            "https://user@hanayume.com/series/34bf61d51ebc3?_rsc=flight",
            "GET",
            {"rsc": "1"},
            "fetch",
        ),
        (
            "https://hanayume.com:444/series/34bf61d51ebc3?_rsc=flight",
            "GET",
            {"rsc": "1"},
            "fetch",
        ),
    ],
)
def test_hanayume_batch_route_signature_rejects_unobserved_shape(
    url: str, method: str, headers: dict[str, str], resource_type: str
) -> None:
    request = SimpleNamespace(
        url=url, method=method, headers=headers, resource_type=resource_type
    )
    assert HanayumeAdapter()._batch_route_signature(request) is False


@pytest.mark.parametrize(
    ("url", "method", "headers", "resource_type", "expected_action", "fatal"),
    [
        (
            "https://hanayume.com/episodes/49b7e11049871",
            "GET",
            {},
            "document",
            "fallback",
            None,
        ),
        (
            "https://hanayume.com/episodes/49b7e11049871?_rsc=selected",
            "GET",
            {"rsc": "1"},
            "fetch",
            "fallback",
            None,
        ),
        (
            "https://hanayume.com/series/34bf61d51ebc3/1?_rsc=range",
            "GET",
            {"rsc": "1", "next-router-prefetch": "1"},
            "other",
            "abort",
            None,
        ),
        (
            "https://hanayume.com/episodes/not-an-id?_rsc=unknown",
            "GET",
            {"rsc": "1"},
            "fetch",
            "abort",
            "unrecognized_page_route_request",
        ),
        (
            "https://hanayume.com/episodes/49b7e11049871/unknown?_rsc=unknown",
            "GET",
            {"rsc": "1"},
            "fetch",
            "abort",
            "unrecognized_page_route_request",
        ),
        (
            "https://user@hanayume.com/series/34bf61d51ebc3?_rsc=unknown",
            "GET",
            {"rsc": "1"},
            "fetch",
            "abort",
            "unrecognized_page_route_request",
        ),
        (
            "https://hanayume.com:444/series/34bf61d51ebc3?_rsc=unknown",
            "GET",
            {"rsc": "1"},
            "fetch",
            "abort",
            "unrecognized_page_route_request",
        ),
        (
            "http://hanayume.com/series/34bf61d51ebc3?_rsc=unknown",
            "GET",
            {"rsc": "1"},
            "fetch",
            "abort",
            "unrecognized_page_route_request",
        ),
        (
            "https://hanayume.com/series/34bf61d51ebc3?_rsc=unknown",
            "POST",
            {"rsc": "1"},
            "fetch",
            "abort",
            "unrecognized_page_route_request",
        ),
        (
            "https://outside.example/series/34bf61d51ebc3?_rsc=unknown",
            "GET",
            {"rsc": "1"},
            "fetch",
            "fallback",
            None,
        ),
    ],
)
async def test_hanayume_batch_route_handler_passes_selected_and_blocks_unknown(
    url: str,
    method: str,
    headers: dict[str, str],
    resource_type: str,
    expected_action: str,
    fatal: str | None,
) -> None:
    class FakeRoute:
        def __init__(self, request) -> None:
            self.request = request
            self.action: str | None = None
            self.error_code: str | None = None

        async def fallback(self) -> None:
            self.action = "fallback"

        async def abort(self, error_code: str | None = None) -> None:
            self.action = "abort"
            self.error_code = error_code

    adapter = HanayumeAdapter()
    adapter._episode_id = "49b7e11049871"
    route = FakeRoute(
        SimpleNamespace(
            url=url,
            method=method,
            headers=headers,
            resource_type=resource_type,
        )
    )
    await adapter._handle_batch_navigation_route(route)

    assert route.action == expected_action
    assert route.error_code == ("blockedbyclient" if expected_action == "abort" else None)
    assert adapter._batch_route_fatal_reason == fatal
    assert adapter._batch_route_blocked_rsc == (1 if fatal is None and expected_action == "abort" else 0)
    if fatal is not None:
        assert adapter._batch_route_blocked_unexpected == 1


async def test_hanayume_batch_route_guard_installs_before_batch_navigation() -> None:
    class FakePage:
        def __init__(self) -> None:
            self.events: list[tuple[str, str]] = []

        def on(self, event: str, _callback) -> None:
            self.events.append(("on", event))

        async def route(self, pattern: str, _callback) -> None:
            self.events.append(("route", pattern))

    adapter = HanayumeAdapter()
    adapter._episode_id = "49b7e11049871"
    page = FakePage()
    await adapter._install_batch_route_guard(page)

    assert page.events == [
        ("on", "response"),
        ("route", "**://*/episodes/**"),
        ("route", "**://*/series/**"),
    ]
    assert adapter._batch_route_guard_enabled is True


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
async def test_batch_adapter_accepts_direct_and_work_ticket_strategies() -> None:
    adapter = HanayumeAdapter()

    await adapter.configure_run(None, "direct")
    await adapter.configure_run(None, "quota")

    with pytest.raises(UnsupportedAccessStrategyError):
        await adapter.configure_run(None, "premium")


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
    padded_counter: bool = False, total: int = 9, tail_pr_count: int = 2,
) -> dict[str, object]:
    last_slot = total - int(padded_counter)
    ci_slot = last_slot - tail_pr_count - 2
    body_slots = tuple(range(2 if top_empty else 1, ci_slot))
    visible = visible if visible is not None else _expected_active_slots(current, body_slots)
    viewport = {"width": 1906, "height": 986}
    slots = []
    for index in range(last_slot + 1):
        if index == 0:
            classes = ["-cv-page", "mode-empty", "mode-pr", "mode-top-pr"]
        elif index == 1 and top_empty:
            classes = ["-cv-page", "mode-empty"]
        elif index == ci_slot:
            classes = ["-cv-page", "mode-ci"]
        elif ci_slot < index < last_slot - 1:
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


@pytest.mark.parametrize("diagnostic_unavailable", [False, True])
async def test_hanayume_viewer_failure_keeps_exact_snapshot_before_later_diagnostics(
    diagnostic_unavailable: bool,
) -> None:
    raw = _viewer_snapshot(total=21, top_empty=True, padded_counter=True)
    raw["slots"].pop()
    raw["url"] = f"https://hanayume.com/episodes/{EPISODE_ID}?private=do-not-log"
    raw["slots"][2]["canvas"] = {"width": 5, "height": 7, "png": "do-not-log-pixels"}
    later = _viewer_snapshot(total=21, top_empty=True)

    class FakePage:
        url = raw["url"]
        calls = 0

        async def evaluate(self, _script, options):
            assert options.get("includePng") is False
            self.calls += 1
            if self.calls == 1:
                return raw
            if diagnostic_unavailable:
                raise PlaywrightError("do-not-log-transport-details")
            return later

    adapter = HanayumeAdapter()
    page = FakePage()
    with pytest.raises(UnknownPageStateError, match="page-wrapper count is incomplete"):
        await adapter._observe(page)
    debug = await adapter.collect_debug_metadata(page)
    assert page.calls == 2
    failure = debug["viewer"]["failure"]
    snapshot = failure["observation"]
    assert failure["error"] == "Hanayume viewer page-wrapper count is incomplete"
    assert snapshot["wrapper_count"] == 20
    assert snapshot["totalText"] == "21"
    assert snapshot["currentText"] == "1"
    assert snapshot["seek"]["value"] == "21"
    assert "mode-has-top-emptypage" in snapshot["viewerClasses"]
    assert snapshot["slots"][-1]["classes"] == ["-cv-page", "mode-good"]
    if diagnostic_unavailable:
        assert debug["viewer"]["diagnostic_error_type"] == "Error"
    else:
        assert debug["viewer"]["at_diagnostics"]["wrapper_count"] == 22
    assert "do-not-log" not in json.dumps(debug)
    assert adapter.get_access_consumption().consumed is False
    assert adapter._captured_slots == []


def test_hanayume_viewer_diagnostics_bound_slots_and_keep_tail() -> None:
    snapshot = hanayume_adapter._viewer_debug_snapshot(_viewer_snapshot(total=299))
    assert snapshot["wrapper_count"] == 300
    assert len(snapshot["slots"]) == 128
    assert snapshot["omitted_slots"] == 172
    assert snapshot["slots"][0]["index"] == 0
    assert snapshot["slots"][-1]["index"] == 299


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


@pytest.mark.parametrize(
    ("padded_counter", "total", "tail_pr_count"),
    [(padded, total, 2) for padded in (False, True) for total in (9, 17, 21)]
    + [(True, 11, 3)],
)
def test_hanayume_viewer_uses_physical_body_slots_for_observed_top_empty_layout(
    padded_counter: bool, total: int, tail_pr_count: int,
) -> None:
    body_slots = tuple(range(2, total - int(padded_counter) - tail_pr_count - 2))
    intro = _parse_viewer_observation(_viewer_snapshot(
        top_empty=True, padded_counter=padded_counter, total=total, tail_pr_count=tail_pr_count,
    ))
    assert intro.has_top_empty_page is True
    assert intro.body_slots == body_slots
    assert intro.body_total == len(body_slots)
    assert intro.active_slots == ()
    assert intro.ready_slots == ()
    assert intro.raw["slots"][1]["wrapperCenterInViewport"] is True

    first_spread = _parse_viewer_observation(_viewer_snapshot(
        current=3, top_empty=True, padded_counter=padded_counter, total=total,
        tail_pr_count=tail_pr_count,
    ))
    assert first_spread.body_slots == body_slots
    assert first_spread.active_slots == (2, 3)
    assert first_spread.ready_slots == (2, 3)
    assert _expected_active_slots(5, first_spread.body_slots) == tuple(
        slot for slot in (4, 5) if slot in body_slots
    )


@pytest.mark.parametrize("slot", [2, 4, 5, 6, 7, 8, 9, 10])
def test_hanayume_three_pr_tail_rejects_changed_body_or_tail(slot: int) -> None:
    snapshot = _viewer_snapshot(total=11, padded_counter=True, top_empty=True, tail_pr_count=3)
    snapshot["slots"][slot]["classes"].append("unobserved-state")
    with pytest.raises(UnknownPageStateError):
        _parse_viewer_observation(snapshot)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda snapshot: snapshot["viewerClasses"].remove("mode-has-top-emptypage"),
        lambda snapshot: snapshot["slots"][1].update(classes=["-cv-page", "mode-empty", "mode-pr"]),
        lambda snapshot: snapshot["slots"][1].update(canvasCount=1, canvas={"width": 1, "height": 1}),
        lambda snapshot: snapshot["slots"][2].update(classes=["-cv-page", "mode-empty"]),
    ],
)
@pytest.mark.parametrize("padded_counter", [False, True])
def test_hanayume_top_empty_layout_rejects_unobserved_or_interior_empty_state(
    mutate, padded_counter: bool,
) -> None:
    snapshot = _viewer_snapshot(top_empty=True, padded_counter=padded_counter)
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
