import pytest
from playwright.async_api import Error, Page, async_playwright

from screenshot_crawler.site_adapters.bookwalker.adapter import (
    BookWalkerAdapter,
    BookWalkerStrictEntryError,
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


async def _goto_product(
    browser_page: Page, controls: str, *, product_url: str = PRODUCT_URL
) -> None:
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
    await browser_page.goto(product_url)


async def _initialize_strict(
    browser_page: Page,
    strategy: str,
    controls: str,
    *,
    timeout_ms: int = 500,
    product_url: str = PRODUCT_URL,
) -> BookWalkerAdapter:
    await _goto_product(browser_page, controls, product_url=product_url)
    adapter = BookWalkerAdapter()
    adapter.read_link_wait_timeout_ms = timeout_ms
    await adapter.configure_run(browser_page, strategy)  # type: ignore[arg-type]
    await adapter.initialize(browser_page)
    return adapter


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
async def test_bookwalker_strict_direct_clicks_purchased_owned_control(
    browser_page: Page,
) -> None:
    controls = _control_html(
        action="read_purchased", text="読む", entry="owned-purchased"
    )
    await _initialize_strict(browser_page, "direct", controls)
    assert "entry=owned-purchased" in browser_page.url


@pytest.mark.asyncio
async def test_bookwalker_strict_direct_allows_owned_without_control_uuid(
    browser_page: Page,
) -> None:
    controls = _control_html(
        action="reading", text="読む", entry="owned", uuid=None
    )
    await _initialize_strict(browser_page, "direct", controls)
    assert "entry=owned" in browser_page.url


@pytest.mark.asyncio
async def test_bookwalker_strict_direct_rejects_maruyomi_only(
    browser_page: Page,
) -> None:
    controls = _control_html(action="read_maruyomi", text="10分まる読み", entry="quota")
    with pytest.raises(BookWalkerStrictEntryError, match="expected kind='owned'"):
        await _initialize_strict(browser_page, "direct", controls, timeout_ms=150)
    assert browser_page.url == PRODUCT_URL


@pytest.mark.asyncio
async def test_bookwalker_strict_direct_multiple_owned_controls_fail(
    browser_page: Page,
) -> None:
    controls = (
        _control_html(action="reading", text="読む", entry="owned-a")
        + _control_html(action="reading", text="読む", entry="owned-b")
    )
    with pytest.raises(
        BookWalkerStrictEntryError, match="matching control was not stably unique"
    ):
        await _initialize_strict(browser_page, "direct", controls)
    assert browser_page.url == PRODUCT_URL


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
    with pytest.raises(
        BookWalkerStrictEntryError, match="matching control was not stably unique"
    ):
        await _initialize_strict(browser_page, "quota", controls)
    assert browser_page.url == PRODUCT_URL


@pytest.mark.asyncio
async def test_bookwalker_strict_waits_for_transient_duplicate_to_settle(
    browser_page: Page,
) -> None:
    controls = (
        _control_html(action="read_maruyomi", text="10分まる読み", entry="old")
        + _control_html(action="read_maruyomi", text="10分まる読み", entry="new")
    )
    await _goto_product(browser_page, controls)
    stable_control = _control_html(
        action="read_maruyomi", text="10分まる読み", entry="stable"
    )
    await browser_page.locator("#js-read-check").evaluate(
        """
        (element, html) => setTimeout(() => { element.innerHTML = html; }, 350)
        """,
        stable_control,
    )

    adapter = BookWalkerAdapter()
    await adapter.configure_run(browser_page, "quota")
    await adapter.initialize(browser_page)
    assert "entry=stable" in browser_page.url


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
@pytest.mark.parametrize(
    ("strategy", "control"),
    [
        (
            "direct",
            _control_html(action="reading", text="読む", entry="owned", uuid=None),
        ),
        (
            "quota",
            _control_html(
                action="read_maruyomi", text="10分まる読み", entry="quota", uuid=None
            ),
        ),
    ],
)
async def test_bookwalker_strict_requires_product_identity_before_candidates(
    browser_page: Page, strategy: str, control: str
) -> None:
    invalid_product_url = "https://bookwalker.jp/deabcdef-/"
    with pytest.raises(BookWalkerStrictEntryError, match="product identity"):
        await _initialize_strict(
            browser_page,
            strategy,
            control,
            product_url=invalid_product_url,
            timeout_ms=150,
        )
    assert browser_page.url == invalid_product_url


@pytest.mark.asyncio
async def test_bookwalker_strict_uuid_comparison_is_case_insensitive(
    browser_page: Page,
) -> None:
    uppercase_product_url = f"https://bookwalker.jp/de{PRODUCT_ID.upper()}/"
    controls = _control_html(
        action="reading", text="読む", entry="owned", uuid=PRODUCT_ID
    )
    await _initialize_strict(
        browser_page, "direct", controls, product_url=uppercase_product_url
    )
    assert "entry=owned" in browser_page.url


@pytest.mark.asyncio
async def test_bookwalker_auto_trial_fallback_still_navigates(browser_page: Page) -> None:
    controls = _control_html(action="trial_reading", text="試し読み", entry="trial")
    await _initialize_strict(browser_page, "auto", controls, timeout_ms=300)
    assert "entry=trial" in browser_page.url


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


@pytest.mark.asyncio
async def test_bookwalker_keeps_first_page_cover_spread_as_one_target(
    browser_page: Page,
) -> None:
    await browser_page.set_content(
        """
        <span id="pageSliderCounter">1 / 10</span>
        <div id="renderer">
          <div class="currentScreen">
            <canvas width="2000" height="1000" style="width:2000px;height:1000px"></canvas>
          </div>
        </div>
        """
    )
    await browser_page.evaluate(
        """
        () => {
          const canvas = document.querySelector('canvas');
          canvas.dataset.bookwalkerTraceId = 'cover';
          window.__bookwalkerDrawCalls = [
            {canvasId: 'cover', destination: [200, 0, 600, 1000]},
            {canvasId: 'cover', destination: [1200, 0, 600, 1000]},
          ];
        }
        """
    )

    targets = await BookWalkerAdapter().get_capture_targets(browser_page)

    assert len(targets) == 1
    assert await targets[0].evaluate(
        "element => ({width: element.width, height: element.height})"
    ) == {"width": 1600, "height": 1000}


@pytest.mark.asyncio
async def test_bookwalker_crops_first_page_cover_to_draw_geometry(
    browser_page: Page,
) -> None:
    await browser_page.set_content(
        """
        <span id="pageSliderCounter">1 / 10</span>
        <div id="renderer">
          <div class="currentScreen">
            <canvas width="2000" height="1000" style="width:2000px;height:1000px"></canvas>
          </div>
        </div>
        """
    )
    await browser_page.evaluate(
        """
        () => {
          const canvas = document.querySelector('canvas');
          canvas.dataset.bookwalkerTraceId = 'cover';
          window.__bookwalkerDrawCalls = [
            {canvasId: 'cover', destination: [700, 0, 600, 1000]},
          ];
        }
        """
    )

    targets = await BookWalkerAdapter().get_capture_targets(browser_page)

    assert len(targets) == 1
    assert await targets[0].evaluate(
        "element => ({width: element.width, height: element.height})"
    ) == {"width": 600, "height": 1000}


@pytest.mark.asyncio
async def test_bookwalker_crops_cover_from_pixels_when_geometry_is_missing(
    browser_page: Page,
) -> None:
    await browser_page.set_content(
        """
        <span id="pageSliderCounter">1 / 10</span>
        <div id="renderer">
          <div class="currentScreen">
            <canvas width="2000" height="1000" style="width:2000px;height:1000px"></canvas>
          </div>
        </div>
        """
    )
    await browser_page.locator("canvas").evaluate(
        "element => {"
        " const context = element.getContext('2d');"
        " context.fillStyle = 'rgb(20, 20, 20)';"
        " context.fillRect(700, 0, 600, 1000);"
        "}"
    )

    targets = await BookWalkerAdapter().get_capture_targets(browser_page)

    assert len(targets) == 1
    assert await targets[0].evaluate(
        "element => ({width: element.width, height: element.height})"
    ) == {"width": 600, "height": 1000}

