import asyncio

import pytest
from playwright.async_api import Error, Page, async_playwright

from screenshot_crawler.core.errors import (
    PageChangeTimeoutError,
)
from screenshot_crawler.site_adapters.mangaone.adapter import (
    MangaOneAdapter,
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
