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


async def test_mangaone_configure_run_accepts_auto_and_quota() -> None:
    adapter = MangaOneAdapter()
    page = object()

    await adapter.configure_run(page, "auto")  # type: ignore[arg-type]
    assert adapter._access_strategy == "auto"
    await adapter.configure_run(page, "quota")  # type: ignore[arg-type]
    assert adapter._access_strategy == "quota"


async def test_mangaone_configure_run_rejects_direct() -> None:
    with pytest.raises(UnsupportedAccessStrategyError, match="access_strategy='direct'"):
        await MangaOneAdapter().configure_run(object(), "direct")  # type: ignore[arg-type]


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


async def test_mangaone_quota_entry_fails_closed_without_button(
    browser_page: Page,
) -> None:
    await browser_page.set_content("<div class='viewer-container' hidden></div>")
    adapter = MangaOneAdapter()
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
