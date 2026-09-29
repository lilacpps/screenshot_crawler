import json

import pytest
import pytest_asyncio
from playwright.async_api import Browser, Page

import screenshot_crawler.site_adapters.bookwalker.adapter as bookwalker_adapter_module
import screenshot_crawler.site_adapters.bookwalker.login as bookwalker_login_module
from screenshot_crawler.site_adapters.bookwalker.adapter import (
    BookWalkerAdapter,
    BookWalkerStrictEntryError,
)
from screenshot_crawler.site_adapters.bookwalker.login import (
    BookWalkerLoginError,
    login_bookwalker,
)

PRODUCT_ID = "6de7534d-7022-481d-b2d3-05f03f384454"
PRODUCT_URL = f"https://bookwalker.jp/de{PRODUCT_ID}/"
VIEWER_BASE = "https://viewer.bookwalker.jp/03/21/viewer.html"
FAST_STRICT_SETTLE_MS = 10
FAST_STRICT_POLL_INTERVAL_MS = 20

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(loop_scope="module")
async def browser_page(integration_browser: Browser) -> Page:
    context = await integration_browser.new_context(viewport={"width": 800, "height": 600})
    page = await context.new_page()
    try:
        yield page
    finally:
        await page.close()
        await context.close()


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
    initial_settle_ms: int | None = None,
    poll_interval_ms: int | None = None,
) -> BookWalkerAdapter:
    await _goto_product(browser_page, controls, product_url=product_url)
    adapter = BookWalkerAdapter()
    adapter.read_link_wait_timeout_ms = timeout_ms
    if initial_settle_ms is not None:
        adapter.strict_entry_initial_settle_ms = initial_settle_ms
    if poll_interval_ms is not None:
        adapter.strict_candidate_poll_interval_ms = poll_interval_ms
    await adapter.configure_run(browser_page, strategy)  # type: ignore[arg-type]
    await adapter.initialize(browser_page)
    return adapter


async def test_bookwalker_strict_quota_clicks_only_maruyomi(browser_page: Page) -> None:
    controls = """
    <a data-action-label="trial_reading" href="https://viewer.bookwalker.jp/trial">試し読み</a>
    """ + _control_html(action="read_maruyomi", text="10分まる読み", entry="quota")
    await _initialize_strict(
        browser_page,
        "quota",
        controls,
        initial_settle_ms=FAST_STRICT_SETTLE_MS,
        poll_interval_ms=FAST_STRICT_POLL_INTERVAL_MS,
    )
    assert "entry=quota" in browser_page.url


async def _goto_login_redirect_product(
    browser_page: Page,
    *,
    login_redirects_to_viewer: bool,
    product_request_count: list[int],
    login_destination: str | None = None,
    reader_destination: str = "https://member.bookwalker.jp/login",
    login_mount_delay_ms: int = 0,
) -> None:
    viewer_url = f"{VIEWER_BASE}?cid={PRODUCT_ID}&entry=quota"
    destination = login_destination or viewer_url
    login_form = """
    <form id="login-form" onsubmit="event.preventDefault();">
      <input type="email" name="email">
      <input type="password" name="password">
      <button type="submit">ログイン</button>
    </form>
    """
    if login_redirects_to_viewer:
        login_form = f"""
        <form id="login-form" onsubmit="
          event.preventDefault();
          window.name = document.querySelector('[name=email]').value;
          window.location.href = '{destination}';
        ">
          <input type="email" name="email">
          <input type="password" name="password">
          <button type="submit">ログイン</button>
        </form>
        """
    product_html = f"""
    <h1 class="t-c-product-main-data__title">作品</h1>
    <div id="js-read-check">
      <a data-action-label="read_maruyomi" data-uuid="{PRODUCT_ID}"
         href="{reader_destination}">10分まる読み</a>
    </div>
    <div id="js-subscription-check"></div>
    """

    async def fulfill_product(route) -> None:
        product_request_count[0] += 1
        await route.fulfill(content_type="text/html", body=product_html)

    async def fulfill_login(route) -> None:
        body = login_form
        if login_mount_delay_ms:
            body = (
                "<!doctype html><body><script>"
                f"setTimeout(() => {{ document.body.innerHTML = {json.dumps(login_form)}; }}, "
                f"{login_mount_delay_ms});"
                "</script></body>"
            )
        await route.fulfill(content_type="text/html", body=body)

    async def fulfill_viewer(route) -> None:
        await route.fulfill(content_type="text/html", body=_viewer_html())

    await browser_page.route("https://bookwalker.jp/**", fulfill_product)
    await browser_page.route("https://member.bookwalker.jp/**", fulfill_login)
    await browser_page.route("https://viewer.bookwalker.jp/**", fulfill_viewer)
    await browser_page.goto(PRODUCT_URL)


async def test_bookwalker_quota_login_redirect_submits_once_and_uses_viewer(
    browser_page: Page,
) -> None:
    product_request_count = [0]
    await _goto_login_redirect_product(
        browser_page,
        login_redirects_to_viewer=True,
        product_request_count=product_request_count,
    )
    adapter = BookWalkerAdapter(
        auto_login_email="reader@example.test",
        auto_login_password="password-not-logged",
    )
    adapter.read_link_wait_timeout_ms = 500
    adapter.strict_entry_initial_settle_ms = FAST_STRICT_SETTLE_MS
    adapter.strict_candidate_poll_interval_ms = FAST_STRICT_POLL_INTERVAL_MS
    await adapter.configure_run(browser_page, "quota")
    await adapter.initialize(browser_page)

    assert browser_page.url == f"{VIEWER_BASE}?cid={PRODUCT_ID}&entry=quota"
    assert await browser_page.evaluate("window.name") == "reader@example.test"
    assert product_request_count == [1]
    assert adapter._auto_login_attempted


async def test_bookwalker_quota_waits_for_delayed_login_form_mount(
    browser_page: Page,
) -> None:
    product_request_count = [0]
    await _goto_login_redirect_product(
        browser_page,
        login_redirects_to_viewer=True,
        product_request_count=product_request_count,
        login_mount_delay_ms=300,
    )
    adapter = BookWalkerAdapter(
        auto_login_email="reader@example.test",
        auto_login_password="password-not-logged",
    )
    adapter.read_link_wait_timeout_ms = 500
    adapter.strict_entry_initial_settle_ms = FAST_STRICT_SETTLE_MS
    adapter.strict_candidate_poll_interval_ms = FAST_STRICT_POLL_INTERVAL_MS
    adapter.strict_entry_destination_poll_interval_ms = 20
    await adapter.configure_run(browser_page, "quota")
    await adapter.initialize(browser_page)

    assert browser_page.url == f"{VIEWER_BASE}?cid={PRODUCT_ID}&entry=quota"
    assert await browser_page.evaluate("window.name") == "reader@example.test"
    assert product_request_count == [1]


async def test_bookwalker_quota_login_redirect_without_credentials_fails_explicitly(
    browser_page: Page,
) -> None:
    product_request_count = [0]
    await _goto_login_redirect_product(
        browser_page,
        login_redirects_to_viewer=True,
        product_request_count=product_request_count,
    )
    adapter = BookWalkerAdapter()
    adapter.read_link_wait_timeout_ms = 500
    adapter.strict_entry_initial_settle_ms = FAST_STRICT_SETTLE_MS
    adapter.strict_candidate_poll_interval_ms = FAST_STRICT_POLL_INTERVAL_MS
    await adapter.configure_run(browser_page, "quota")

    with pytest.raises(
        BookWalkerLoginError,
        match="BookWalker auto-login is required but BOOKWALKER_EMAIL / BOOKWALKER_PASSWORD are not configured",
    ):
        await adapter.initialize(browser_page)
    assert product_request_count == [1]


async def test_bookwalker_quota_login_form_remaining_fails_without_retry(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bookwalker_login_module, "_LOGIN_RESULT_TIMEOUT_MS", 20)
    product_request_count = [0]
    await _goto_login_redirect_product(
        browser_page,
        login_redirects_to_viewer=False,
        product_request_count=product_request_count,
    )
    adapter = BookWalkerAdapter(
        auto_login_email="reader@example.test",
        auto_login_password="password-not-logged",
    )
    adapter.read_link_wait_timeout_ms = 500
    adapter.strict_entry_initial_settle_ms = FAST_STRICT_SETTLE_MS
    adapter.strict_candidate_poll_interval_ms = FAST_STRICT_POLL_INTERVAL_MS
    await adapter.configure_run(browser_page, "quota")

    with pytest.raises(BookWalkerLoginError, match="login form is still visible"):
        await adapter.initialize(browser_page)
    assert product_request_count == [1]
    assert adapter._auto_login_attempted


async def test_bookwalker_quota_login_unexpected_redirect_fails_safe(
    browser_page: Page,
) -> None:
    product_request_count = [0]
    await _goto_login_redirect_product(
        browser_page,
        login_redirects_to_viewer=True,
        product_request_count=product_request_count,
        login_destination=PRODUCT_URL,
    )
    adapter = BookWalkerAdapter(
        auto_login_email="reader@example.test",
        auto_login_password="password-not-logged",
    )
    adapter.read_link_wait_timeout_ms = 500
    adapter.strict_entry_initial_settle_ms = FAST_STRICT_SETTLE_MS
    adapter.strict_candidate_poll_interval_ms = FAST_STRICT_POLL_INTERVAL_MS
    await adapter.configure_run(browser_page, "quota")

    with pytest.raises(BookWalkerStrictEntryError, match="did not reach the target viewer"):
        await adapter.initialize(browser_page)
    assert adapter._auto_login_attempted


async def test_bookwalker_quota_unknown_destination_fails_at_entry(
    browser_page: Page,
) -> None:
    product_request_count = [0]
    await _goto_login_redirect_product(
        browser_page,
        login_redirects_to_viewer=False,
        product_request_count=product_request_count,
        reader_destination="https://bookwalker.jp/unexpected/",
    )
    adapter = BookWalkerAdapter()
    adapter.read_link_wait_timeout_ms = 500
    adapter.strict_entry_initial_settle_ms = FAST_STRICT_SETTLE_MS
    adapter.strict_candidate_poll_interval_ms = FAST_STRICT_POLL_INTERVAL_MS
    adapter.navigation_wait_timeout_ms = 150
    adapter.strict_entry_destination_poll_interval_ms = 20
    await adapter.configure_run(browser_page, "quota")

    with pytest.raises(
        BookWalkerStrictEntryError,
        match="destination did not resolve to viewer or login form",
    ):
        await adapter.initialize(browser_page)
    assert product_request_count == [2]


async def test_bookwalker_quota_without_login_form_does_not_call_auto_login(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unexpected_auto_login(*_args, **_kwargs) -> None:
        pytest.fail("auto-login should not run for an active session")

    monkeypatch.setattr(
        bookwalker_adapter_module,
        "submit_bookwalker_login_form",
        unexpected_auto_login,
    )
    controls = _control_html(action="read_maruyomi", text="10分まる読み", entry="quota")
    await _initialize_strict(
        browser_page,
        "quota",
        controls,
        initial_settle_ms=FAST_STRICT_SETTLE_MS,
        poll_interval_ms=FAST_STRICT_POLL_INTERVAL_MS,
    )
    assert "entry=quota" in browser_page.url


async def test_bookwalker_standalone_login_helper_keeps_cta_entry(
    browser_page: Page,
) -> None:
    viewer_url = f"{VIEWER_BASE}?cid={PRODUCT_ID}"
    home_html = '<a href="https://member.bookwalker.jp/login">ログイン</a>'
    login_html = f"""
    <form onsubmit="
      event.preventDefault();
      window.name = document.querySelector('[name=email]').value;
      window.location.href = '{viewer_url}';
    ">
      <input type="email" name="email">
      <input type="password" name="password">
      <button type="submit">ログイン</button>
    </form>
    """

    async def fulfill_home(route) -> None:
        await route.fulfill(content_type="text/html", body=home_html)

    async def fulfill_login(route) -> None:
        await route.fulfill(content_type="text/html", body=login_html)

    async def fulfill_viewer(route) -> None:
        await route.fulfill(content_type="text/html", body=_viewer_html())

    await browser_page.route("https://bookwalker.jp/", fulfill_home)
    await browser_page.route("https://bookwalker.jp/**", fulfill_home)
    await browser_page.route("https://member.bookwalker.jp/**", fulfill_login)
    await browser_page.route("https://viewer.bookwalker.jp/**", fulfill_viewer)
    await browser_page.goto("https://bookwalker.jp/")
    await browser_page.set_content(home_html)
    await login_bookwalker(
        browser_page,
        email="reader@example.test",
        password="password-not-logged",
        home_url="https://bookwalker.jp/",
    )

    assert browser_page.url == viewer_url
    assert await browser_page.evaluate("window.name") == "reader@example.test"


async def test_bookwalker_strict_direct_clicks_only_owned(browser_page: Page) -> None:
    controls = """
    <a data-action-label="trial_reading" href="https://viewer.bookwalker.jp/trial">試し読み</a>
    """ + _control_html(action="reading", text="読む", entry="owned")
    await _initialize_strict(
        browser_page,
        "direct",
        controls,
        initial_settle_ms=FAST_STRICT_SETTLE_MS,
        poll_interval_ms=FAST_STRICT_POLL_INTERVAL_MS,
    )
    assert "entry=owned" in browser_page.url


async def test_bookwalker_strict_direct_clicks_purchased_owned_control(
    browser_page: Page,
) -> None:
    controls = _control_html(
        action="read_purchased", text="読む", entry="owned-purchased"
    )
    await _initialize_strict(
        browser_page,
        "direct",
        controls,
        initial_settle_ms=FAST_STRICT_SETTLE_MS,
        poll_interval_ms=FAST_STRICT_POLL_INTERVAL_MS,
    )
    assert "entry=owned-purchased" in browser_page.url


async def test_bookwalker_strict_direct_allows_owned_without_control_uuid(
    browser_page: Page,
) -> None:
    controls = _control_html(
        action="reading", text="読む", entry="owned", uuid=None
    )
    await _initialize_strict(
        browser_page,
        "direct",
        controls,
        initial_settle_ms=FAST_STRICT_SETTLE_MS,
        poll_interval_ms=FAST_STRICT_POLL_INTERVAL_MS,
    )
    assert "entry=owned" in browser_page.url


async def test_bookwalker_strict_direct_rejects_maruyomi_only(
    browser_page: Page,
) -> None:
    controls = _control_html(action="read_maruyomi", text="10分まる読み", entry="quota")
    with pytest.raises(BookWalkerStrictEntryError, match="expected kind='owned'"):
        await _initialize_strict(browser_page, "direct", controls, timeout_ms=150)
    assert browser_page.url == PRODUCT_URL


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


@pytest.mark.parametrize("strategy", ["direct", "quota"])
async def test_bookwalker_strict_trial_only_fails_before_click(
    browser_page: Page, strategy: str
) -> None:
    controls = _control_html(action="trial_reading", text="試し読み", entry="trial")
    with pytest.raises(BookWalkerStrictEntryError, match="observed kinds=trial"):
        await _initialize_strict(browser_page, strategy, controls, timeout_ms=150)
    assert browser_page.url == PRODUCT_URL


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


@pytest.mark.parametrize("strategy", ["direct", "quota"])
async def test_bookwalker_strict_generic_viewer_only_fails(
    browser_page: Page, strategy: str
) -> None:
    controls = '<a href="https://viewer.bookwalker.jp/generic"></a>'
    with pytest.raises(BookWalkerStrictEntryError):
        await _initialize_strict(browser_page, strategy, controls, timeout_ms=150)
    assert browser_page.url == PRODUCT_URL


async def test_bookwalker_strict_wrong_strategy_does_not_fallback(browser_page: Page) -> None:
    controls = _control_html(action="reading", text="読む", entry="owned")
    with pytest.raises(BookWalkerStrictEntryError, match="expected kind='maruyomi'"):
        await _initialize_strict(browser_page, "quota", controls, timeout_ms=150)
    assert browser_page.url == PRODUCT_URL


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


async def test_bookwalker_strict_uuid_comparison_is_case_insensitive(
    browser_page: Page,
) -> None:
    uppercase_product_url = f"https://bookwalker.jp/de{PRODUCT_ID.upper()}/"
    controls = _control_html(
        action="reading", text="読む", entry="owned", uuid=PRODUCT_ID
    )
    await _initialize_strict(
        browser_page,
        "direct",
        controls,
        product_url=uppercase_product_url,
        initial_settle_ms=FAST_STRICT_SETTLE_MS,
        poll_interval_ms=FAST_STRICT_POLL_INTERVAL_MS,
    )
    assert "entry=owned" in browser_page.url


async def test_bookwalker_auto_trial_fallback_still_navigates(browser_page: Page) -> None:
    controls = _control_html(action="trial_reading", text="試し読み", entry="trial")
    await _initialize_strict(
        browser_page,
        "auto",
        controls,
        timeout_ms=300,
        initial_settle_ms=FAST_STRICT_SETTLE_MS,
        poll_interval_ms=FAST_STRICT_POLL_INTERVAL_MS,
    )
    assert "entry=trial" in browser_page.url


async def test_bookwalker_strict_rejects_already_viewer_url(browser_page: Page) -> None:
    async def fulfill_viewer(route) -> None:
        await route.fulfill(content_type="text/html", body=_viewer_html())

    await browser_page.route("https://viewer.bookwalker.jp/**", fulfill_viewer)
    await browser_page.goto(f"{VIEWER_BASE}?cid={PRODUCT_ID}")
    adapter = BookWalkerAdapter()
    await adapter.configure_run(browser_page, "direct")
    with pytest.raises(BookWalkerStrictEntryError, match="already in a viewer"):
        await adapter.initialize(browser_page)


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
