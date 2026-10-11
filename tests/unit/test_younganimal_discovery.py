from __future__ import annotations

import asyncio

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from screenshot_crawler.core.errors import AccessStopError
from screenshot_crawler.discovery import DiscoveryIncompleteError
from screenshot_crawler.site_adapters.younganimal import discovery as younganimal_discovery
from screenshot_crawler.site_adapters.younganimal.discovery import (
    YounganimalEpisodeIdentity,
    YounganimalListingRow,
    _apply_discovery_scope,
    _guard_checkpoint,
    _navigate,
    _pace_before_range_navigation,
    _parse_range_links,
    _records_from_rows,
    _validate_page_ranges,
    canonical_younganimal_episode_url,
    classify_younganimal_access,
    parse_younganimal_episode_url,
    parse_younganimal_work_url,
)
from screenshot_crawler.watchlist import DiscoveryScope

BASE = "https://younganimal.com"
WORK_ID = "aee4fa742b0fe"
SEED_ID = "55889b8a851cb"


def _range_entries(*, total: int = 32, selected_alias: int | None = None):
    entries = [
        {
            "label": "最新話から",
            "href": f"{BASE}/series/{WORK_ID}/new",
        }
    ]
    for page_number, start in enumerate(range(1, total + 1, 30), start=1):
        end = min(start + 29, total)
        url = (
            f"{BASE}/series/{WORK_ID}"
            if selected_alias == page_number
            else f"{BASE}/series/{WORK_ID}/{page_number}"
        )
        entries.append({"label": f"{start}-{end}", "href": url})
    return entries


def test_younganimal_urls_are_strict_and_work_scoped() -> None:
    assert parse_younganimal_episode_url(f"{BASE}/episodes/{SEED_ID}") is not None
    assert parse_younganimal_episode_url(f"{BASE}/episodes/{SEED_ID}/") is not None
    assert canonical_younganimal_episode_url(f"{BASE}/episodes/{SEED_ID}/") == (
        f"{BASE}/episodes/{SEED_ID}"
    )
    assert parse_younganimal_work_url(f"{BASE}/series/{WORK_ID}") == WORK_ID
    for value in (
        f"http://younganimal.com/episodes/{SEED_ID}",
        f"https://www.younganimal.com/episodes/{SEED_ID}",
        f"https://example.com/episodes/{SEED_ID}",
        f"https://user@younganimal.com/episodes/{SEED_ID}",
        f"{BASE}:444/episodes/{SEED_ID}",
        f"{BASE}/episodes/{SEED_ID}?page=1",
        f"{BASE}/episodes/{SEED_ID}#reader",
        f"{BASE}/episodes/{SEED_ID}/1",
        "https://younganimal.com/episodes/not-an-id",
    ):
        assert parse_younganimal_episode_url(value) is None


@pytest.mark.parametrize(
    ("labels", "expected"),
    [
        (("無料",), "free"),
        ((" 今なら無料 ",), "unknown"),
        (("今なら無料",), "unknown"),
        (("待つと無料",), "unknown"),
        (("無料", "無料"), "unknown"),
        (("無料", "今なら無料"), "unknown"),
        (("購入",), "unknown"),
        ((), "unknown"),
    ],
)
def test_younganimal_access_needs_one_exact_free_label(labels, expected) -> None:
    observed = classify_younganimal_access(labels)
    assert observed.raw_labels == labels
    assert observed.access_mode == expected


def test_younganimal_range_map_requires_contiguous_oldest_first_routes() -> None:
    ranges = _parse_range_links(_range_entries(), work_id=WORK_ID)
    assert [(item.page_number, item.start_position, item.end_position) for item in ranges] == [
        (1, 1, 30),
        (2, 31, 32),
    ]
    assert [item.url for item in ranges] == [
        f"{BASE}/series/{WORK_ID}/1",
        f"{BASE}/series/{WORK_ID}/2",
    ]


def test_younganimal_known_latest_and_href_less_ellipsis_controls_are_exact() -> None:
    entries = _range_entries()
    entries.insert(1, {"label": "...", "href": "", "raw_href": None})
    assert len(_parse_range_links(entries, work_id=WORK_ID)) == 2

    unknown = [*entries, {"label": "More", "href": f"{BASE}/series/{WORK_ID}/new"}]
    with pytest.raises(DiscoveryIncompleteError):
        _parse_range_links(unknown, work_id=WORK_ID)

    wrong_latest = _range_entries()
    wrong_latest[0] = {"label": "最新話から", "href": f"{BASE}/episodes/{SEED_ID}"}
    with pytest.raises(DiscoveryIncompleteError):
        _parse_range_links(wrong_latest, work_id=WORK_ID)

    linked_ellipsis = [*entries, {"label": "...", "href": f"{BASE}/series/{WORK_ID}/1", "raw_href": "/1"}]
    with pytest.raises(DiscoveryIncompleteError):
        _parse_range_links(linked_ellipsis, work_id=WORK_ID)


@pytest.mark.parametrize(
    "entries",
    [
        [
            {"label": "1-30", "href": f"{BASE}/series/{WORK_ID}/1"},
            {"label": "32-32", "href": f"{BASE}/series/{WORK_ID}/2"},
        ],
        [
            {"label": "1-30", "href": f"{BASE}/series/{WORK_ID}/2"},
            {"label": "31-32", "href": f"{BASE}/series/{WORK_ID}/1"},
        ],
        [
            {"label": "1-30", "href": f"https://example.com/series/{WORK_ID}/1"},
            {"label": "31-32", "href": f"{BASE}/series/{WORK_ID}/2"},
        ],
        [
            {"label": "1-30", "href": f"{BASE}/series/{WORK_ID}/1?x=2"},
            {"label": "31-32", "href": f"{BASE}/series/{WORK_ID}/2"},
        ],
        [
            {"label": "1-30", "href": f"{BASE}/series/{WORK_ID}/1"},
            {"label": "31-32", "href": f"{BASE}/series/{WORK_ID}/2"},
            {"label": "31-32", "href": f"{BASE}/series/{WORK_ID}/2"},
        ],
        [
            {"label": "1-30", "href": f"{BASE}/series/{WORK_ID}/1"},
            {"label": "31-30", "href": f"{BASE}/series/{WORK_ID}/2"},
        ],
    ],
)
def test_younganimal_invalid_range_set_fails_closed(entries) -> None:
    with pytest.raises(DiscoveryIncompleteError):
        _parse_range_links(entries, work_id=WORK_ID)


def test_younganimal_page_range_alias_is_limited_to_selected_range() -> None:
    ranges = _parse_range_links(_range_entries(total=60), work_id=WORK_ID)
    _validate_page_ranges(
        _range_entries(total=60, selected_alias=1),
        work_id=WORK_ID,
        ranges=ranges,
        selected=ranges[0],
    )
    _validate_page_ranges(
        _range_entries(total=60, selected_alias=2),
        work_id=WORK_ID,
        ranges=ranges,
        selected=ranges[1],
    )
    bad = _range_entries(total=60, selected_alias=1)
    with pytest.raises(DiscoveryIncompleteError):
        _validate_page_ranges(
            bad,
            work_id=WORK_ID,
            ranges=ranges,
            selected=ranges[1],
        )


def _row(episode_id: str, position: int, label: str) -> YounganimalListingRow:
    return YounganimalListingRow(
        identity=YounganimalEpisodeIdentity(WORK_ID, episode_id),
        title=f"PART.{position}",
        access=classify_younganimal_access((label,)),
        global_position=position,
    )


def test_younganimal_records_are_latest_first_and_keep_global_positions() -> None:
    rows = [
        _row(SEED_ID, 1, "無料"),
        _row("528a05e37879f", 2, "今なら無料"),
        _row("483eff20ba210", 3, "待つと無料"),
        _row("ed87698bc768d", 4, "無料"),
    ]
    records = _records_from_rows(
        rows_oldest_first=rows,
        work_title="Fixture Work",
        scope=None,
    )
    assert [record.source.external_id for record in records] == [
        f"{WORK_ID}:ed87698bc768d",
        f"{WORK_ID}:483eff20ba210",
        f"{WORK_ID}:528a05e37879f",
        f"{WORK_ID}:{SEED_ID}",
    ]
    assert [record.source.global_display_position for record in records] == [4, 3, 2, 1]
    assert [record.source.access_mode for record in records] == [
        "free",
        "unknown",
        "unknown",
        "free",
    ]
    assert records[0].item.order_label == "PART.4"


def test_younganimal_bounded_scope_is_inclusive_without_renumbering() -> None:
    rows = [
        _row(SEED_ID, 1, "無料"),
        _row("528a05e37879f", 2, "無料"),
        _row("483eff20ba210", 3, "無料"),
        _row("ed87698bc768d", 4, "無料"),
    ]
    records = _records_from_rows(
        rows_oldest_first=rows,
        work_title="Fixture Work",
        scope=None,
    )
    selected = _apply_discovery_scope(
        records,
        scope=DiscoveryScope(
            from_url=f"{BASE}/episodes/483eff20ba210",
            through_url=f"{BASE}/episodes/528a05e37879f",
        ),
        work_id=WORK_ID,
    )
    assert [record.source.global_display_position for record in selected] == [3, 2]
    assert [record.source.external_id for record in selected] == [
        f"{WORK_ID}:483eff20ba210",
        f"{WORK_ID}:528a05e37879f",
    ]
    with pytest.raises(DiscoveryIncompleteError):
        _apply_discovery_scope(
            records,
            scope=DiscoveryScope(from_url=f"{BASE}/episodes/0000000000000"),
            work_id=WORK_ID,
        )


def test_younganimal_duplicate_episode_identity_fails_closed() -> None:
    with pytest.raises(DiscoveryIncompleteError):
        _records_from_rows(
            rows_oldest_first=[
                _row("528a05e37879f", 1, "free-fixture"),
                _row("528a05e37879f", 2, "free-fixture"),
            ],
            work_title="Fixture Work",
            scope=None,
        )


async def test_younganimal_guard_cleanup_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    finished = asyncio.Event()

    class SlowGuard:
        async def close(self) -> None:
            try:
                await asyncio.Event().wait()
            finally:
                finished.set()

    monkeypatch.setattr(younganimal_discovery, "GUARD_CLEANUP_TIMEOUT_SECONDS", 0.01)
    await younganimal_discovery._close_guard_bounded(SlowGuard())  # type: ignore[arg-type]
    await asyncio.sleep(0)
    assert finished.is_set()


async def test_younganimal_guard_checkpoint_timeout_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SlowGuard:
        async def check_page(self, page) -> None:
            await asyncio.Event().wait()

    monkeypatch.setattr(younganimal_discovery, "OBSERVATION_TIMEOUT_SECONDS", 0.01)
    page = type("PageWithUrl", (), {"url": f"{BASE}/series/{WORK_ID}/3"})()
    with pytest.raises(DiscoveryIncompleteError, match="access check exceeded its time limit"):
        await _guard_checkpoint(SlowGuard(), page)  # type: ignore[arg-type]


async def test_younganimal_range_pacing_is_one_second_before_guard_checkpoint() -> None:
    calls: list[tuple[str, object]] = []

    class FakePage:
        url = f"{BASE}/series/{WORK_ID}"

        async def wait_for_timeout(self, timeout_ms: float) -> None:
            calls.append(("wait", timeout_ms))

    class FakeGuard:
        async def check_page(self, page) -> None:
            calls.append(("guard", page.url))

    await _pace_before_range_navigation(  # type: ignore[arg-type]
        FakePage(), FakeGuard()  # type: ignore[arg-type]
    )

    assert calls == [("wait", 1_000), ("guard", f"{BASE}/series/{WORK_ID}")]


class _FakeNavigationRequest:
    def __init__(
        self,
        url: str,
        frame: object,
        *,
        is_navigation: bool = True,
        resource_type: str = "document",
    ) -> None:
        self.url = url
        self.frame = frame
        self.resource_type = resource_type
        self._is_navigation = is_navigation

    def is_navigation_request(self) -> bool:
        return self._is_navigation


class _FakeNavigationResponse:
    def __init__(self, request, url: str, status: int) -> None:
        self.request = request
        self.url = url
        self.status = status


class _FakeNavigationPage:
    def __init__(self, behaviors: list[dict[str, object]], expected_url: str) -> None:
        self.behaviors = behaviors
        self.url = expected_url
        self.main_frame = object()
        self.events: list[tuple[object, ...]] = []
        self.listeners: dict[str, list[object]] = {"request": [], "response": []}
        self.goto_calls = 0
        self._drift_on_wait: str | None = None

    def on(self, event: str, callback) -> None:
        self.listeners[event].append(callback)

    def remove_listener(self, event: str, callback) -> None:
        self.listeners[event].remove(callback)

    async def goto(self, url: str, **kwargs):
        del kwargs
        self.goto_calls += 1
        self.events.append(("goto", self.goto_calls, url))
        behavior = self.behaviors.pop(0)
        final_url = behavior.get("page_url", url)
        self.url = str(final_url)
        self._drift_on_wait = (
            str(behavior["drift_on_wait"])
            if behavior.get("drift_on_wait") is not None
            else None
        )
        frame = self.main_frame if behavior.get("main_frame", True) else object()
        request = _FakeNavigationRequest(
            url,
            frame,
            is_navigation=bool(behavior.get("is_navigation", True)),
            resource_type=str(behavior.get("resource_type", "document")),
        )
        if behavior.get("emit_request", True):
            for callback in tuple(self.listeners["request"]):
                callback(request)

        status = behavior.get("status")
        response = None
        if status is not None:
            response_request = (
                _FakeNavigationRequest(url, self.main_frame)
                if behavior.get("stale_response", False)
                else request
            )
            response = _FakeNavigationResponse(
                response_request,
                str(behavior.get("response_url", url)),
                int(status),
            )
            if behavior.get("emit_response", True):
                for callback in tuple(self.listeners["response"]):
                    callback(response)

        if behavior.get("timeout", False):
            raise PlaywrightTimeoutError("synthetic DOMContentLoaded timeout")
        if behavior.get("cancel", False):
            raise asyncio.CancelledError
        return response

    async def wait_for_timeout(self, timeout_ms: float) -> None:
        self.events.append(("wait", timeout_ms))
        if self._drift_on_wait is not None:
            self.url = self._drift_on_wait


class _FakeNavigationGuard:
    def __init__(self, events: list[tuple[object, ...]], *, stop_at: int | None = None) -> None:
        self.events = events
        self.stop_at = stop_at
        self.checks = 0

    async def check_page(self, page) -> None:
        del page
        self.checks += 1
        self.events.append(("guard", self.checks))
        if self.checks == self.stop_at:
            raise AccessStopError(
                reason="synthetic stop",
                site="younganimal",
                url=f"{BASE}/series/{WORK_ID}/2",
                status=429,
            )


async def test_younganimal_navigation_retries_only_after_exact_current_attempt_200() -> None:
    expected_url = f"{BASE}/series/{WORK_ID}/2"
    page = _FakeNavigationPage(
        [
            {"timeout": True, "status": 200},
            {"status": 200},
        ],
        expected_url,
    )
    guard = _FakeNavigationGuard(page.events)

    retries_used = await _navigate(  # type: ignore[arg-type]
        page,
        expected_url,
        guard,  # type: ignore[arg-type]
        retry_budget_remaining=2,
    )

    assert retries_used == 1
    assert page.goto_calls == 2
    assert page.events == [
        ("goto", 1, expected_url),
        ("guard", 1),
        ("wait", younganimal_discovery.NAVIGATION_RETRY_BACKOFF_MS),
        ("guard", 2),
        ("goto", 2, expected_url),
        ("guard", 3),
    ]
    assert page.listeners == {"request": [], "response": []}


@pytest.mark.parametrize(
    "behavior",
    [
        {"timeout": True, "emit_response": False},
        {"timeout": True, "status": 503},
        {"timeout": True, "status": 302, "page_url": f"{BASE}/login"},
        {"timeout": True, "status": 200, "page_url": f"{BASE}/series/{WORK_ID}/3"},
        {"timeout": True, "status": 200, "stale_response": True},
        {"timeout": True, "status": 200, "main_frame": False},
        {"timeout": True, "status": 200, "is_navigation": False},
    ],
    ids=("unknown-response", "non-200", "redirect", "route-drift", "stale-response", "subframe", "non-navigation"),
)
async def test_younganimal_navigation_unknown_or_drifted_timeout_is_not_retried(
    behavior: dict[str, object],
) -> None:
    expected_url = f"{BASE}/series/{WORK_ID}/2"
    page = _FakeNavigationPage([behavior], expected_url)
    guard = _FakeNavigationGuard(page.events)

    with pytest.raises(DiscoveryIncompleteError, match="timed out without retry-eligible"):
        await _navigate(  # type: ignore[arg-type]
            page,
            expected_url,
            guard,  # type: ignore[arg-type]
            retry_budget_remaining=2,
        )

    assert page.goto_calls == 1
    assert page.listeners == {"request": [], "response": []}
    assert not any(event[0] == "wait" for event in page.events)


async def test_younganimal_navigation_retry_obeys_work_budget_and_guard_stop() -> None:
    expected_url = f"{BASE}/series/{WORK_ID}/2"
    no_budget_page = _FakeNavigationPage(
        [{"timeout": True, "status": 200}], expected_url
    )
    with pytest.raises(DiscoveryIncompleteError, match="timed out without retry-eligible"):
        await _navigate(  # type: ignore[arg-type]
            no_budget_page,
            expected_url,
            _FakeNavigationGuard(no_budget_page.events),  # type: ignore[arg-type]
            retry_budget_remaining=0,
        )
    assert no_budget_page.goto_calls == 1

    stopped_page = _FakeNavigationPage(
        [{"timeout": True, "status": 200}], expected_url
    )
    stopped_guard = _FakeNavigationGuard(stopped_page.events, stop_at=1)
    with pytest.raises(DiscoveryIncompleteError, match="stopped by the access guard"):
        await _navigate(  # type: ignore[arg-type]
            stopped_page,
            expected_url,
            stopped_guard,  # type: ignore[arg-type]
            retry_budget_remaining=2,
        )
    assert stopped_page.goto_calls == 1


async def test_younganimal_navigation_timeout_uses_only_one_retry() -> None:
    expected_url = f"{BASE}/series/{WORK_ID}/2"
    page = _FakeNavigationPage(
        [
            {"timeout": True, "status": 200},
            {"timeout": True, "status": 200},
        ],
        expected_url,
    )

    with pytest.raises(DiscoveryIncompleteError, match="timed out without retry-eligible"):
        await _navigate(  # type: ignore[arg-type]
            page,
            expected_url,
            _FakeNavigationGuard(page.events),  # type: ignore[arg-type]
            retry_budget_remaining=2,
        )

    assert page.goto_calls == 2
    assert sum(event[0] == "wait" for event in page.events) == 1
    assert page.listeners == {"request": [], "response": []}


async def test_younganimal_navigation_rechecks_route_after_backoff() -> None:
    expected_url = f"{BASE}/series/{WORK_ID}/2"
    page = _FakeNavigationPage(
        [
            {
                "timeout": True,
                "status": 200,
                "drift_on_wait": f"{BASE}/series/{WORK_ID}/3",
            }
        ],
        expected_url,
    )

    with pytest.raises(DiscoveryIncompleteError, match="route changed before"):
        await _navigate(  # type: ignore[arg-type]
            page,
            expected_url,
            _FakeNavigationGuard(page.events),  # type: ignore[arg-type]
            retry_budget_remaining=2,
        )

    assert page.goto_calls == 1
    assert page.listeners == {"request": [], "response": []}


async def test_younganimal_navigation_removes_listeners_on_cancellation() -> None:
    expected_url = f"{BASE}/series/{WORK_ID}/2"
    page = _FakeNavigationPage([{"cancel": True}], expected_url)

    with pytest.raises(asyncio.CancelledError):
        await _navigate(  # type: ignore[arg-type]
            page,
            expected_url,
            _FakeNavigationGuard(page.events),  # type: ignore[arg-type]
            retry_budget_remaining=2,
        )

    assert page.listeners == {"request": [], "response": []}
