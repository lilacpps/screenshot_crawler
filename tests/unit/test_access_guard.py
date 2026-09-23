from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from playwright.async_api import Page, async_playwright

from screenshot_crawler.batch.metrics import BatchMetricsWriter
from screenshot_crawler.batch.models import BatchExecutionError
from screenshot_crawler.cli import _execute_batch_candidates
from screenshot_crawler.core.access_guard import AccessEvent, AccessGuard, AccessProfile
from screenshot_crawler.core.errors import AccessStopError
from screenshot_crawler.core.models import ContentContext, ContentIdentity, RunConfig
from screenshot_crawler.core.runner import CrawlerRunner
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.base import SiteAdapter


def _response(
    url: str,
    status: int,
    *,
    headers: dict[str, str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        url=url,
        status=status,
        headers=headers or {},
        request=SimpleNamespace(method="GET", resource_type="document"),
    )


def _guard(
    events: list[AccessEvent],
    *,
    stop_on_http_403: bool = True,
    stop_on_http_429: bool = True,
    stop_on_challenge: bool = True,
    stop_on_captcha: bool = True,
) -> AccessGuard:
    return AccessGuard(
        site="test",
        relevant_host=lambda url: "first-party.test" in url,
        stop_on_http_403=stop_on_http_403,
        stop_on_http_429=stop_on_http_429,
        stop_on_challenge=stop_on_challenge,
        stop_on_captcha=stop_on_captcha,
        event_sink=events.append,
    )


def test_relevant_403_is_fatal_and_unrelated_403_is_not() -> None:
    events: list[AccessEvent] = []
    guard = _guard(events)

    guard._handle_response(_response("https://third-party.test/ad", 403))
    guard.raise_if_stopped()
    guard._handle_response(_response("https://first-party.test/viewer", 403))

    with pytest.raises(AccessStopError) as exc_info:
        guard.raise_if_stopped()
    assert exc_info.value.reason == "http_403"
    assert [event.status for event in events if event.event_type == "request"] == [403, 403]
    assert events[0].relevant_host is False
    assert events[1].relevant_host is True


def test_relevant_429_records_retry_after_and_stop_flag_can_disable_stop() -> None:
    events: list[AccessEvent] = []
    guard = _guard(events, stop_on_http_429=False)

    guard._handle_response(
        _response(
            "https://first-party.test/api",
            429,
            headers={"Retry-After": "17", "Content-Length": "12"},
        )
    )

    guard.raise_if_stopped()
    request = events[0]
    assert request.status == 429
    assert request.retry_after == "17"
    assert request.response_bytes == 12


def test_explicit_challenge_marker_has_distinct_reason() -> None:
    events: list[AccessEvent] = []
    guard = _guard(events)

    guard._handle_response(
        _response(
            "https://first-party.test/challenge",
            403,
            headers={"cf-mitigated": "challenge"},
        )
    )

    with pytest.raises(AccessStopError) as exc_info:
        guard.raise_if_stopped()
    assert exc_info.value.reason == "challenge_detected"
    assert any(event.event_type == "challenge" for event in events)


@pytest.mark.asyncio
async def test_runner_propagates_relevant_http_stop_without_retrying_adapter(
    tmp_path: Path,
) -> None:
    class Page:
        url = "https://first-party.test/viewer"

        def __init__(self) -> None:
            self.listener = None

        def on(self, event: str, listener: object) -> None:
            assert event == "response"
            self.listener = listener

        def remove_listener(self, _event: str, _listener: object) -> None:
            self.listener = None

        async def goto(self, *_args: object, **_kwargs: object) -> None:
            assert self.listener is not None
            self.listener(_response(self.url, 403))

    class Adapter(SiteAdapter):
        initialize_calls = 0

        def get_access_profile(self):
            return AccessProfile(relevant_host=lambda url: "first-party.test" in url)

        async def initialize(self, _page: Page) -> None:
            self.initialize_calls += 1

        async def detect_state(self, _page: Page) -> PageState:
            return PageState.END

        async def get_capture_target(self, _page: Page) -> object:
            return object()

        async def get_content_identity(self, _page: Page) -> ContentIdentity:
            return ContentIdentity()

        async def get_content_context(self, _page: Page) -> ContentContext:
            return ContentContext()

        async def go_next(self, _page: Page) -> None:
            raise AssertionError("navigation must not start after access stop")

        async def wait_for_change(self, _page: Page, _previous: ContentIdentity | None) -> None:
            raise AssertionError("wait must not start after access stop")

    page = Page()
    adapter = Adapter()
    with pytest.raises(AccessStopError, match="http_403"):
        await CrawlerRunner(
            RunConfig(
                site="test",
                source_url=page.url,
                output_dir=tmp_path / "run",
                diagnostics_dir=tmp_path / "diagnostics",
            )
        ).run(page, adapter)
    assert adapter.initialize_calls == 0


@pytest.mark.asyncio
async def test_visible_captcha_providers_stop_but_hidden_provider_does_not() -> None:
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True)
    page = await browser.new_page()
    try:
        for html, provider in (
            (
                '<div class="g-recaptcha" style="display:block;width:300px;height:80px"></div>',
                "recaptcha",
            ),
            (
                '<div class="h-captcha" style="display:block;width:300px;height:80px"></div>',
                "hcaptcha",
            ),
            (
                '<div class="cf-turnstile" style="display:block;width:300px;height:80px"></div>',
                "turnstile",
            ),
        ):
            await page.set_content(html)
            events: list[AccessEvent] = []
            guard = _guard(events)
            with pytest.raises(AccessStopError) as exc_info:
                await guard.check_page(page)
            assert exc_info.value.reason == "captcha_detected"
            assert exc_info.value.provider == provider

        await page.set_content(
            '<iframe src="https://www.google.com/recaptcha/api2/anchor" '
            'style="display:none"></iframe><script src="/recaptcha.js"></script>'
        )
        guard = _guard([])
        await guard.check_page(page)
        guard.raise_if_stopped()
    finally:
        await page.close()
        await browser.close()
        await playwright.stop()


@pytest.mark.asyncio
async def test_batch_access_stop_does_not_start_remaining_candidate_or_delay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class Session:
        async def new_page(self) -> object:
            events.append("new_page")
            return object()

        async def close_page(self, _page: object) -> None:
            events.append("close_page")

    class Executor:
        async def execute_candidate(self, _page: object, candidate: object, **_kwargs: object) -> object:
            events.append(f"candidate:{candidate.item_id}")
            raise BatchExecutionError(
                "fatal access stop",
                access_stop=AccessStopError(
                    reason="http_429",
                    site="test",
                    url="https://first-party.test/viewer",
                    status=429,
                    retry_after="30",
                ),
            )

    async def fail_sleep(_seconds: float) -> None:
        events.append("unexpected_delay")

    monkeypatch.setattr("screenshot_crawler.cli.asyncio.sleep", fail_sleep)
    args = SimpleNamespace(
        output_root=Path("output/batch"),
        library_dir=Path("output/Books"),
        max_pages=1000,
        max_same_content=3,
        keep_open=False,
    )
    candidates = [
        SimpleNamespace(item_id=1, source_id=11, metadata={}, access_strategy="direct", quota_resource=None),
        SimpleNamespace(item_id=2, source_id=22, metadata={}, access_strategy="direct", quota_resource=None),
    ]

    with pytest.raises(BatchExecutionError):
        await _execute_batch_candidates(
            args,
            Session(),
            Executor(),
            candidates,
            phase="test",
            inter_candidate_delay_ms=1000,
        )

    assert events == ["new_page", "candidate:1", "close_page"]


def test_metrics_writer_flushes_request_candidate_and_summary_records(tmp_path: Path) -> None:
    writer = BatchMetricsWriter(tmp_path / "metrics", site="magapoke", mode="normal")
    candidate = SimpleNamespace(
        item_id=1,
        source_id=2,
        target_id=3,
        access_strategy="direct",
        quota_resource=None,
    )
    writer.start_candidate(candidate)  # type: ignore[arg-type]
    writer.record_access_event(
        AccessEvent(
            event_type="request",
            timestamp=writer._started_at,
            url="https://first-party.test/viewer",
            host="first-party.test",
            status=429,
            relevant_host=True,
            retry_after="5",
        )
    )
    writer.finish_candidate(result="failed", stop_reason="http_429")
    writer.finish(stop_reason="http_429")
    writer.close()

    records = [json.loads(line) for line in writer.path.read_text(encoding="utf-8").splitlines()]
    summary = records[-1]
    assert writer.path.parent == tmp_path / "metrics"
    assert any(record["type"] == "request" for record in records)
    assert any(record["type"] == "candidate" for record in records)
    assert summary["type"] == "batch_summary"
    assert summary["http_requests_total"] == 1
    assert summary["http_429_count"] == 1
    assert summary["stop_reason"] == "http_429"
