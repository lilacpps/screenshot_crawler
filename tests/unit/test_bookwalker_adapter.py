import pytest
from playwright.async_api import Error, Page, async_playwright

from screenshot_crawler.core.errors import UnsupportedAccessStrategyError
from screenshot_crawler.site_adapters.bookwalker.adapter import (
    BookWalkerAdapter,
    BookWalkerStrictEntryError,
    clean_bookwalker_title,
    is_last_page_counter,
    split_bookwalker_title,
)

PRODUCT_ID = "6de7534d-7022-481d-b2d3-05f03f384454"
PRODUCT_URL = f"https://bookwalker.jp/de{PRODUCT_ID}/"
VIEWER_BASE = "https://viewer.bookwalker.jp/03/21/viewer.html"


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


def _viewer_html() -> str:
    return """
    <div id="renderer">
      <div class="currentScreen">
        <canvas width="100" height="100" style="width:100px;height:100px"></canvas>
      </div>
    </div>
    """


def _control_html(
    *,
    action: str,
    text: str,
    entry: str,
    uuid: str | None = PRODUCT_ID,
    element: str = "a",
) -> str:
    uuid_attribute = f' data-uuid="{uuid}"' if uuid is not None else ""
    href = f'{VIEWER_BASE}?cid={PRODUCT_ID}&entry={entry}' if element == "a" else "#"
    return (
        f'<{element} data-action-label="{action}"{uuid_attribute} '
        f'href="{href}" target="_blank">{text}</{element}>'
    )


async def _goto_product(browser_page: Page, controls: str) -> None:
    product_html = f"""
    <h1 class="t-c-product-main-data__title">作品</h1>
    <div id="js-read-check">{controls}</div>
    <div id="js-subscription-check"></div>
    """

    async def fulfill_product(route) -> None:
        await route.fulfill(content_type="text/html", body=product_html)

    async def fulfill_viewer(route) -> None:
        await route.fulfill(content_type="text/html", body=_viewer_html())

    await browser_page.route("https://bookwalker.jp/**", fulfill_product)
    await browser_page.route("https://viewer.bookwalker.jp/**", fulfill_viewer)
    await browser_page.goto(PRODUCT_URL)


async def _initialize_strict(
    browser_page: Page, strategy: str, controls: str, *, timeout_ms: int = 300
) -> BookWalkerAdapter:
    await _goto_product(browser_page, controls)
    adapter = BookWalkerAdapter()
    adapter.read_link_wait_timeout_ms = timeout_ms
    await adapter.configure_run(browser_page, strategy)  # type: ignore[arg-type]
    await adapter.initialize(browser_page)
    return adapter


@pytest.mark.asyncio
async def test_bookwalker_configure_run_accepts_all_strategies() -> None:
    adapter = BookWalkerAdapter()
    page = object()

    for strategy in ("auto", "direct", "quota"):
        await adapter.configure_run(page, strategy)  # type: ignore[arg-type]
        assert adapter._access_strategy == strategy


@pytest.mark.asyncio
async def test_bookwalker_configure_run_rejects_unknown_strategy() -> None:
    with pytest.raises(UnsupportedAccessStrategyError, match="access_strategy='invalid'"):
        await BookWalkerAdapter().configure_run(object(), "invalid")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_bookwalker_strict_quota_clicks_only_maruyomi(browser_page: Page) -> None:
    controls = """
    <a data-action-label="trial_reading" href="https://viewer.bookwalker.jp/trial">試し読み</a>
    """ + _control_html(action="read_maruyomi", text="10分まる読み", entry="quota")
    await _initialize_strict(browser_page, "quota", controls)
    assert "entry=quota" in browser_page.url


@pytest.mark.asyncio
async def test_bookwalker_strict_direct_clicks_only_owned(browser_page: Page) -> None:
    controls = """
    <a data-action-label="trial_reading" href="https://viewer.bookwalker.jp/trial">試し読み</a>
    """ + _control_html(action="reading", text="読む", entry="owned")
    await _initialize_strict(browser_page, "direct", controls)
    assert "entry=owned" in browser_page.url


@pytest.mark.asyncio
@pytest.mark.parametrize("strategy", ["direct", "quota"])
async def test_bookwalker_strict_trial_only_fails_before_click(
    browser_page: Page, strategy: str
) -> None:
    controls = _control_html(action="trial_reading", text="試し読み", entry="trial")
    with pytest.raises(BookWalkerStrictEntryError, match="observed kinds=trial"):
        await _initialize_strict(browser_page, strategy, controls, timeout_ms=150)
    assert browser_page.url == PRODUCT_URL


@pytest.mark.asyncio
@pytest.mark.parametrize("strategy", ["direct", "quota"])
async def test_bookwalker_strict_subscription_only_fails(
    browser_page: Page, strategy: str
) -> None:
    controls = _control_html(
        action="subscription_reading", text="読み放題で読む", entry="subscription"
    )
    with pytest.raises(BookWalkerStrictEntryError):
        await _initialize_strict(browser_page, strategy, controls, timeout_ms=150)
    assert browser_page.url == PRODUCT_URL


@pytest.mark.asyncio
@pytest.mark.parametrize("strategy", ["direct", "quota"])
async def test_bookwalker_strict_generic_viewer_only_fails(
    browser_page: Page, strategy: str
) -> None:
    controls = '<a href="https://viewer.bookwalker.jp/generic"></a>'
    with pytest.raises(BookWalkerStrictEntryError):
        await _initialize_strict(browser_page, strategy, controls, timeout_ms=150)
    assert browser_page.url == PRODUCT_URL


@pytest.mark.asyncio
async def test_bookwalker_strict_wrong_strategy_does_not_fallback(browser_page: Page) -> None:
    controls = _control_html(action="reading", text="読む", entry="owned")
    with pytest.raises(BookWalkerStrictEntryError, match="expected kind='maruyomi'"):
        await _initialize_strict(browser_page, "quota", controls, timeout_ms=150)
    assert browser_page.url == PRODUCT_URL


@pytest.mark.asyncio
async def test_bookwalker_strict_multiple_matching_controls_fail(browser_page: Page) -> None:
    controls = (
        _control_html(action="read_maruyomi", text="10分まる読み", entry="quota-a")
        + _control_html(action="read_maruyomi", text="10分まる読み", entry="quota-b")
    )
    with pytest.raises(BookWalkerStrictEntryError, match="multiple matching"):
        await _initialize_strict(browser_page, "quota", controls)
    assert browser_page.url == PRODUCT_URL


@pytest.mark.asyncio
async def test_bookwalker_strict_overlapping_scopes_count_same_element_once(
    browser_page: Page,
) -> None:
    quota_url = f"{VIEWER_BASE}?cid={PRODUCT_ID}&entry=quota"
    await _goto_product(
        browser_page,
        f"""
        <div id="js-read-check-book-cover-main-button">
          <div id="js-read-check">
            <a data-action-label="read_maruyomi" href="{quota_url}" target="_blank">10分まる読み</a>
          </div>
        </div>
        """,
    )
    adapter = BookWalkerAdapter()
    await adapter.configure_run(browser_page, "quota")
    await adapter.initialize(browser_page)
    assert "entry=quota" in browser_page.url


@pytest.mark.asyncio
async def test_bookwalker_strict_waits_for_delayed_maruyomi(browser_page: Page) -> None:
    controls = _control_html(action="trial_reading", text="試し読み", entry="trial")
    await _goto_product(browser_page, controls)
    quota_url = f"{VIEWER_BASE}?cid={PRODUCT_ID}&entry=quota"
    await browser_page.locator("#js-read-check").evaluate(
        f"""
        element => setTimeout(() => {{
          element.insertAdjacentHTML(
            'beforeend',
            '<a data-action-label="read_maruyomi" href="{quota_url}" target="_blank">10分まる読み</a>'
          );
        }}, 300)
        """
    )
    adapter = BookWalkerAdapter()
    await adapter.configure_run(browser_page, "quota")
    await adapter.initialize(browser_page)
    assert "entry=quota" in browser_page.url


@pytest.mark.asyncio
async def test_bookwalker_strict_uuid_mismatch_is_excluded(browser_page: Page) -> None:
    controls = _control_html(
        action="read_maruyomi",
        text="10分まる読み",
        entry="wrong-uuid",
        uuid="00000000-0000-0000-0000-000000000000",
    )
    with pytest.raises(BookWalkerStrictEntryError):
        await _initialize_strict(browser_page, "quota", controls, timeout_ms=150)
    assert browser_page.url == PRODUCT_URL


@pytest.mark.asyncio
async def test_bookwalker_strict_rejects_already_viewer_url(browser_page: Page) -> None:
    async def fulfill_viewer(route) -> None:
        await route.fulfill(content_type="text/html", body=_viewer_html())

    await browser_page.route("https://viewer.bookwalker.jp/**", fulfill_viewer)
    await browser_page.goto(f"{VIEWER_BASE}?cid={PRODUCT_ID}")
    adapter = BookWalkerAdapter()
    await adapter.configure_run(browser_page, "direct")
    with pytest.raises(BookWalkerStrictEntryError, match="already in a viewer"):
        await adapter.initialize(browser_page)


def test_bookwalker_content_id_from_url() -> None:
    url = "https://viewer.bookwalker.jp/03/30/viewer.html?cid=abc-123&cty=0"
    assert BookWalkerAdapter.content_id_from_url(url) == "abc-123"


def test_bookwalker_content_id_from_product_url() -> None:
    url = "https://bookwalker.jp/de6de7534d-7022-481d-b2d3-05f03f384454/"
    assert (
        BookWalkerAdapter.content_id_from_url(url)
        == "6de7534d-7022-481d-b2d3-05f03f384454"
    )


def test_bookwalker_page_counter_parser() -> None:
    assert BookWalkerAdapter.parse_page_counter("3 / 120") == (3, "3 / 120")
    assert BookWalkerAdapter.parse_page_counter("") == (None, None)


def test_bookwalker_last_page_counter() -> None:
    assert is_last_page_counter("59 / 59")
    assert not is_last_page_counter("58 / 59")


def test_bookwalker_read_link_score_prefers_owned_reader_over_trial() -> None:
    content_id = "6de7534d-7022-481d-b2d3-05f03f384454"
    trial = {
        "text": "試し読み",
        "action": "trial_reading",
        "href": "https://bookwalker.jp/item/?sample=1",
        "uuid": content_id,
    }
    owned = {
        "text": "読む",
        "action": "reading",
        "href": "https://viewer.bookwalker.jp/03/21/viewer.html?cid=" + content_id,
        "uuid": content_id,
    }

    assert BookWalkerAdapter.score_read_link(owned, content_id) > (
        BookWalkerAdapter.score_read_link(trial, content_id)
    )


def test_bookwalker_read_link_score_recognizes_ten_minute_reading() -> None:
    candidate = {
        "text": "10分まる読み",
        "action": "subscription_reading",
        "href": "https://viewer.bookwalker.jp/viewer.html",
        "uuid": "content-id",
    }

    assert BookWalkerAdapter.score_read_link(candidate, "content-id") >= 260


def test_bookwalker_read_link_candidate_recognizes_actual_japanese_labels() -> None:
    candidate = {
        "text": "10\u5206\u307e\u308b\u8aad\u307f",
        "action": None,
        "href": "",
    }

    assert BookWalkerAdapter.is_read_link_candidate(candidate)


def test_bookwalker_read_link_candidate_excludes_cover_and_check_links() -> None:
    assert not BookWalkerAdapter.is_read_link_candidate(
        {"text": "", "action": "cover", "href": "?sample=1"}
    )
    assert not BookWalkerAdapter.is_read_link_candidate(
        {"text": "", "action": "check", "href": "https://member.bookwalker.jp/"}
    )
    assert BookWalkerAdapter.is_read_link_candidate(
        {"text": "10分まる読み", "action": "subscription_reading", "href": ""}
    )
    assert BookWalkerAdapter.is_read_link_candidate(
        {"text": "", "action": "read_maruyomi", "href": ""}
    )


def test_bookwalker_title_removes_campaign_tag_and_formats_volume() -> None:
    assert clean_bookwalker_title("作品名4【電子特別版】") == "作品名4"
    assert split_bookwalker_title("作品名4【電子特別版】") == ("作品名", "第04巻")


def test_bookwalker_title_uses_three_digits_for_large_series() -> None:
    assert split_bookwalker_title("作品名1", series_count=100) == ("作品名", "第001巻")
    assert split_bookwalker_title("作品名100") == ("作品名", "第100巻")


def test_bookwalker_title_without_volume_is_preserved() -> None:
    assert split_bookwalker_title("作品名【期間限定】") == ("作品名", None)
