import asyncio

import pytest
from playwright.async_api import Error, Page, async_playwright

from screenshot_crawler.core.errors import (
    PageChangeTimeoutError,
    UnsupportedAccessStrategyError,
)
from screenshot_crawler.core.models import ContentIdentity
from screenshot_crawler.site_adapters.mangaone.adapter import (
    MangaOneAdapter,
    mangaone_identity_from_pages,
    order_mangaone_pages,
    parse_mangaone_page_number,
    split_mangaone_episode_title,
)
from screenshot_crawler.site_adapters.mangaone.native_capture import (
    capture_source_bytes,
)


@pytest.fixture
async def browser_page() -> Page:
    playwright = await async_playwright().start()
    try:
        browser = await playwright.chromium.launch(headless=True)
    except Error as exc:
        await playwright.stop()
        pytest.skip(f"Chromium is unavailable: {exc}")
    page = await browser.new_page(viewport={"width": 800, "height": 600})
    try:
        yield page
    finally:
        await browser.close()
        await playwright.stop()


def test_mangaone_chapter_parts_from_url() -> None:
    assert MangaOneAdapter.chapter_parts_from_url(
        "https://manga-one.com/manga/2379/chapter/214131"
    ) == ("2379", "214131")


def test_mangaone_page_label_parser() -> None:
    assert parse_mangaone_page_number("page_0") == 0
    assert parse_mangaone_page_number("page_104") == 104
    assert parse_mangaone_page_number("cover") is None


def test_mangaone_episode_title_uses_two_digit_episode_number() -> None:
    assert split_mangaone_episode_title("獣王と薬草 第1話 | マンガワン") == (
        "獣王と薬草",
        "第01話",
    )
    assert split_mangaone_episode_title("獣王と薬草 第80話(後編)") == (
        "獣王と薬草",
        "第80話-後編",
    )


def test_mangaone_episode_title_without_episode_number_is_preserved() -> None:
    assert split_mangaone_episode_title("作品名 | マンガワン") == ("作品名", None)


def test_mangaone_spread_is_captured_right_to_left() -> None:
    assert order_mangaone_pages([("page_2", 200.0), ("page_1", 900.0)]) == (
        "page_1",
        "page_2",
    )


def test_mangaone_identity_supports_single_page_and_spread() -> None:
    assert mangaone_identity_from_pages(
        ("page_1", "page_2"), chapter_id="214131"
    ) == ContentIdentity(
        page_id="page_1|page_2", page_number=3, source_id="214131"
    )
    assert mangaone_identity_from_pages(("page_0",), chapter_id="214131").page_number == 1


def _synthetic_webp(width: int, height: int) -> bytes:
    payload = (
        b"\x00\x00\x00\x00"
        + (width - 1).to_bytes(3, "little")
        + (height - 1).to_bytes(3, "little")
    )
    return (
        b"RIFF"
        + (4 + 8 + len(payload)).to_bytes(4, "little")
        + b"WEBPVP8X"
        + len(payload).to_bytes(4, "little")
        + payload
    )


def test_mangaone_native_capture_preserves_webp_bytes_and_dimensions() -> None:
    source = _synthetic_webp(720, 1020)

    result = capture_source_bytes(source)

    assert result is not None
    assert result.data == source
    assert (result.width, result.height) == (720, 1020)
    assert result.mime_type == "image/webp"
    assert result.file_extension == ".webp"


def test_mangaone_native_capture_rejects_undecodable_bytes() -> None:
    assert capture_source_bytes(b"not-an-image") is None


class _CaptureLocator:
    def __init__(self, screenshot_bytes: bytes = b"fallback") -> None:
        self.screenshot_bytes = screenshot_bytes
        self.screenshot_calls = 0

    async def evaluate(self, expression: str) -> object:
        if "instanceof HTMLCanvasElement" in expression:
            return False
        raise AssertionError(f"unexpected locator evaluation: {expression}")

    async def screenshot(self, **_kwargs: object) -> bytes:
        self.screenshot_calls += 1
        return self.screenshot_bytes

    async def bounding_box(self) -> dict[str, float]:
        return {"width": 720.0, "height": 1020.0}


class _BodyResponse:
    def __init__(self, url: str, outcomes: list[object]) -> None:
        self.url = url
        self.outcomes = outcomes
        self.calls = 0

    async def body(self) -> bytes | None:
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome  # type: ignore[return-value]


async def _capture_one_source(
    adapter: MangaOneAdapter,
    monkeypatch: pytest.MonkeyPatch,
    locator: _CaptureLocator,
    source_url: str,
) -> tuple[object, ...] | None:
    async def visible_images(_page: Page) -> list[tuple[object, dict[str, object]]]:
        return [
            (
                locator,
                {
                    "src": source_url,
                    "x": 900.0,
                    "naturalWidth": 720,
                    "naturalHeight": 1020,
                },
            )
        ]

    monkeypatch.setattr(adapter, "_visible_page_images", visible_images)
    return await adapter.capture_page(object())  # type: ignore[arg-type]


def _register_body_response(
    adapter: MangaOneAdapter,
    response: _BodyResponse,
) -> None:
    adapter._source_responses[response.url] = response
    adapter._source_response_tasks[response.url] = asyncio.create_task(
        adapter._read_source_response(response)
    )


async def test_mangaone_source_capture_succeeds_on_initial_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _synthetic_webp(720, 1020)
    locator = _CaptureLocator()
    adapter = MangaOneAdapter()
    response = _BodyResponse("blob:initial", [source])
    _register_body_response(adapter, response)

    captures = await _capture_one_source(adapter, monkeypatch, locator, response.url)

    assert captures is not None
    assert captures[0].data == source  # type: ignore[union-attr]
    assert response.calls == 1
    assert locator.screenshot_calls == 0


async def test_mangaone_source_capture_retries_after_one_transient_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _synthetic_webp(720, 1020)
    locator = _CaptureLocator()
    adapter = MangaOneAdapter()
    adapter.source_response_retry_interval_ms = 0
    response = _BodyResponse("blob:retry-once", [RuntimeError("temporary"), source])
    _register_body_response(adapter, response)

    captures = await _capture_one_source(adapter, monkeypatch, locator, response.url)

    assert captures is not None
    assert captures[0].data == source  # type: ignore[union-attr]
    assert response.calls == 2
    assert locator.screenshot_calls == 0


async def test_mangaone_source_capture_retries_twice_before_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _synthetic_webp(720, 1020)
    locator = _CaptureLocator()
    adapter = MangaOneAdapter()
    adapter.source_response_retry_interval_ms = 0
    response = _BodyResponse(
        "blob:retry-twice",
        [RuntimeError("temporary 1"), None, source],
    )
    _register_body_response(adapter, response)

    captures = await _capture_one_source(adapter, monkeypatch, locator, response.url)

    assert captures is not None
    assert captures[0].data == source  # type: ignore[union-attr]
    assert response.calls == 3
    assert locator.screenshot_calls == 0


async def test_mangaone_source_capture_falls_back_after_all_attempts_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    locator = _CaptureLocator()
    adapter = MangaOneAdapter()
    adapter.source_response_retry_interval_ms = 0
    response = _BodyResponse(
        "blob:all-fail",
        [RuntimeError("temporary 1"), RuntimeError("temporary 2"), None],
    )
    _register_body_response(adapter, response)

    captures = await _capture_one_source(adapter, monkeypatch, locator, response.url)

    assert captures is not None
    assert captures[0].data == b"fallback"  # type: ignore[union-attr]
    assert response.calls == 3
    assert locator.screenshot_calls == 1


async def test_mangaone_source_capture_retries_when_response_registration_races(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _synthetic_webp(720, 1020)
    locator = _CaptureLocator()
    adapter = MangaOneAdapter()
    adapter.source_response_retry_interval_ms = 0
    response = _BodyResponse("blob:late-registration", [source])

    async def register_late() -> None:
        await asyncio.sleep(0)
        adapter._handle_source_response(response)

    asyncio.create_task(register_late())
    captures = await _capture_one_source(adapter, monkeypatch, locator, response.url)

    assert captures is not None
    assert captures[0].data == source  # type: ignore[union-attr]
    assert response.calls == 1
    assert locator.screenshot_calls == 0


async def test_mangaone_source_timeout_keeps_pending_body_task_for_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _synthetic_webp(720, 1020)
    locator = _CaptureLocator()
    adapter = MangaOneAdapter()
    adapter.source_response_wait_timeout_ms = 10
    adapter.source_response_retry_interval_ms = 0
    body_ready = asyncio.Event()

    class DelayedResponse(_BodyResponse):
        async def body(self) -> bytes | None:
            self.calls += 1
            await body_ready.wait()
            return source

    response = DelayedResponse("blob:late-body", [])
    _register_body_response(adapter, response)

    async def finish_body() -> None:
        await asyncio.sleep(0.015)
        body_ready.set()

    asyncio.create_task(finish_body())
    captures = await _capture_one_source(adapter, monkeypatch, locator, response.url)

    assert captures is not None
    assert captures[0].data == source  # type: ignore[union-attr]
    assert response.calls == 1
    assert locator.screenshot_calls == 0


async def test_mangaone_invalid_source_bytes_fallback_without_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    locator = _CaptureLocator()
    adapter = MangaOneAdapter()
    response = _BodyResponse("blob:invalid", [b"invalid"])
    _register_body_response(adapter, response)

    captures = await _capture_one_source(adapter, monkeypatch, locator, response.url)

    assert captures is not None
    assert captures[0].data == b"fallback"  # type: ignore[union-attr]
    assert response.calls == 1
    assert locator.screenshot_calls == 1


async def test_mangaone_capture_preserves_spread_order_and_falls_back_per_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    right_source = _synthetic_webp(720, 1020)
    right = _CaptureLocator()
    left = _CaptureLocator()
    adapter = MangaOneAdapter()
    adapter.source_response_retry_interval_ms = 0

    async def visible_images(_page: Page) -> list[tuple[object, dict[str, object]]]:
        return [
            (
                right,
                {
                    "src": "blob:right",
                    "x": 900.0,
                    "naturalWidth": 720,
                    "naturalHeight": 1020,
                },
            ),
            (
                left,
                {
                    "src": "blob:left",
                    "x": 200.0,
                    "naturalWidth": 720,
                    "naturalHeight": 1020,
                },
            ),
        ]

    monkeypatch.setattr(adapter, "_visible_page_images", visible_images)
    right_response = _BodyResponse("blob:right", [right_source])
    left_response = _BodyResponse(
        "blob:left",
        [RuntimeError("temporary 1"), RuntimeError("temporary 2"), None],
    )
    _register_body_response(adapter, right_response)
    _register_body_response(adapter, left_response)

    captures = await adapter.capture_page(object())  # type: ignore[arg-type]

    assert captures is not None
    assert [capture.data for capture in captures] == [right_source, b"fallback"]
    assert [(capture.width, capture.height) for capture in captures] == [
        (720, 1020),
        (720, 1020),
    ]
    assert right_response.calls == 1
    assert left_response.calls == 3
    assert right.screenshot_calls == 0
    assert left.screenshot_calls == 1


async def test_mangaone_configure_run_accepts_all_mangaone_strategies() -> None:
    adapter = MangaOneAdapter()
    page = object()

    await adapter.configure_run(page, "auto")  # type: ignore[arg-type]
    assert adapter._access_strategy == "auto"
    await adapter.configure_run(page, "direct")  # type: ignore[arg-type]
    assert adapter._access_strategy == "direct"
    await adapter.configure_run(page, "quota")  # type: ignore[arg-type]
    assert adapter._access_strategy == "quota"


async def test_mangaone_configure_run_rejects_unknown_strategy() -> None:
    with pytest.raises(UnsupportedAccessStrategyError, match="access_strategy='invalid'"):
        await MangaOneAdapter().configure_run(object(), "invalid")  # type: ignore[arg-type]


async def test_mangaone_quota_entry_clicks_observed_button_once(
    browser_page: Page,
) -> None:
    await browser_page.set_content(
        """
        <button id="unrelated">\u306f\u3044</button>
        <button id="quota-entry">
          <span>\u7121\u6599\u30e9\u30a4\u30d5\u3067\u8aad\u3080</span>
          <span>\u95b2\u89a7\u671f\u9650 \u3042\u3068\u0032\u0034\u6642\u9593</span>
        </button>
        <div class="viewer-container" hidden>
          <img alt="page_0" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='10'%3E%3C/svg%3E">
        </div>
        <script>
          window.entryClicks = 0;
          window.unrelatedClicks = 0;
          document.querySelector('#unrelated').onclick = () => window.unrelatedClicks++;
          document.querySelector('#quota-entry').onclick = () => {
            window.entryClicks++;
            document.querySelector('.viewer-container').hidden = false;
          };
        </script>
        """
    )
    adapter = MangaOneAdapter()
    await adapter.configure_run(browser_page, "quota")
    await adapter.initialize(browser_page)

    assert await browser_page.evaluate("window.entryClicks") == 1
    assert await browser_page.evaluate("window.unrelatedClicks") == 0
    assert await browser_page.locator('.viewer-container img[alt^="page_"]').count() == 1

    with pytest.raises(PageChangeTimeoutError, match="already attempted"):
        await adapter.initialize(browser_page)
    assert await browser_page.evaluate("window.entryClicks") == 1


async def test_mangaone_quota_entry_waits_for_async_button(
    browser_page: Page,
) -> None:
    await browser_page.set_content(
        """
        <div id="quota-entry-host"></div>
        <div class="viewer-container" hidden>
          <img alt="page_0" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='10'%3E%3C/svg%3E">
        </div>
        <script>
          window.entryClicks = 0;
          setTimeout(() => {
            const entry = document.createElement('button');
            entry.innerHTML = '<span>\u7121\u6599\u30e9\u30a4\u30d5\u3067\u8aad\u3080</span> <span>\u95b2\u89a7\u671f\u9650 \u3042\u306824\u6642\u9593</span>';
            entry.onclick = () => {
              window.entryClicks++;
              document.querySelector('.viewer-container').hidden = false;
            };
            document.querySelector('#quota-entry-host').append(entry);
          }, 650);
        </script>
        """
    )
    adapter = MangaOneAdapter()
    await adapter.configure_run(browser_page, "quota")
    await adapter.initialize(browser_page)

    assert await browser_page.evaluate("window.entryClicks") == 1
    assert await browser_page.locator('.viewer-container img[alt^="page_"]').count() == 1


async def test_mangaone_auto_skips_quota_entry(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await browser_page.set_content(
        """
        <button id="quota-entry">\u7121\u6599\u30e9\u30a4\u30d5\u3067\u8aad\u3080</button>
        <script>window.entryClicks = 0; document.querySelector('#quota-entry').onclick = () => window.entryClicks++;</script>
        """
    )
    adapter = MangaOneAdapter()

    async def fail_if_called(_page: Page) -> None:
        raise AssertionError("auto must not enter the quota reader")

    async def no_wait(_page: Page) -> None:
        return None

    monkeypatch.setattr(adapter, "_enter_quota_reader", fail_if_called)
    monkeypatch.setattr(adapter, "_wait_for_render_ready", no_wait)
    monkeypatch.setattr(adapter, "_enter_fullscreen_reader", no_wait)
    await adapter.configure_run(browser_page, "auto")
    await adapter.initialize(browser_page)

    assert await browser_page.evaluate("window.entryClicks") == 0


async def test_mangaone_direct_skips_quota_entry(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await browser_page.set_content(
        """
        <button id="quota-entry">\u7121\u6599\u30e9\u30a4\u30d5\u3067\u8aad\u3080</button>
        <div class="viewer-container">
          <img alt="page_0" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='10'%3E%3C/svg%3E">
        </div>
        <script>window.entryClicks = 0; document.querySelector('#quota-entry').onclick = () => window.entryClicks++;</script>
        """
    )
    adapter = MangaOneAdapter()

    async def fail_if_called(_page: Page) -> None:
        raise AssertionError("direct must not enter the quota reader")

    monkeypatch.setattr(adapter, "_enter_quota_reader", fail_if_called)
    await adapter.configure_run(browser_page, "direct")
    await adapter.initialize(browser_page)

    assert await browser_page.evaluate("window.entryClicks") == 0


async def test_mangaone_quota_entry_fails_closed_without_button(
    browser_page: Page,
) -> None:
    await browser_page.set_content("<div class='viewer-container' hidden></div>")
    adapter = MangaOneAdapter()
    adapter.quota_entry_wait_timeout_ms = 200
    await adapter.configure_run(browser_page, "quota")

    with pytest.raises(PageChangeTimeoutError, match="not observed safely"):
        await adapter.initialize(browser_page)


async def test_mangaone_quota_entry_fails_closed_with_multiple_buttons(
    browser_page: Page,
) -> None:
    await browser_page.set_content(
        """
        <button>\u7121\u6599\u30e9\u30a4\u30d5\u3067\u8aad\u3080</button>
        <button>\u7121\u6599\u30e9\u30a4\u30d5\u3067\u8aad\u3080</button>
        """
    )
    adapter = MangaOneAdapter()
    adapter.quota_entry_wait_timeout_ms = 200
    await adapter.configure_run(browser_page, "quota")

    with pytest.raises(PageChangeTimeoutError, match="not observed safely"):
        await adapter.initialize(browser_page)


async def test_mangaone_quota_entry_fails_if_viewer_does_not_appear(
    browser_page: Page,
) -> None:
    await browser_page.set_content(
        "<button>\u7121\u6599\u30e9\u30a4\u30d5\u3067\u8aad\u3080</button>"
    )
    adapter = MangaOneAdapter()
    await adapter.configure_run(browser_page, "quota")

    with pytest.raises(PageChangeTimeoutError, match="did not reveal the viewer"):
        await adapter.initialize(browser_page)
