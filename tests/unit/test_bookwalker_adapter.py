import pytest
from playwright.async_api import Error, Page, async_playwright

from screenshot_crawler.core.errors import PageChangeTimeoutError, UnsupportedAccessStrategyError
from screenshot_crawler.core.models import ContentIdentity
from screenshot_crawler.core.state import PageState
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


@pytest.mark.asyncio
async def test_bookwalker_go_next_uses_arrow_left() -> None:
    class FakeKeyboard:
        def __init__(self) -> None:
            self.pressed: list[str] = []

        async def press(self, key: str) -> None:
            self.pressed.append(key)

    class FakePage:
        def __init__(self) -> None:
            self.keyboard = FakeKeyboard()

    adapter = BookWalkerAdapter()
    page = FakePage()
    armed = False

    async def is_last_page(_page: object) -> bool:
        return False

    async def arm_capture(_page: object) -> None:
        nonlocal armed
        armed = True

    adapter._is_last_page_counter = is_last_page  # type: ignore[method-assign]
    adapter._arm_native_capture = arm_capture  # type: ignore[method-assign]

    await adapter.go_next(page)  # type: ignore[arg-type]

    assert armed
    assert page.keyboard.pressed == ["ArrowLeft"]


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


@pytest.mark.asyncio
async def test_bookwalker_wait_for_change_uses_click_after_arrow_stalls() -> None:
    class FakePage:
        async def wait_for_timeout(self, _milliseconds: int) -> None:
            return

    adapter = BookWalkerAdapter()
    adapter.page_change_timeout_ms = 400
    adapter.advance_retry_count = 1
    adapter.advance_retry_interval_ms = 200
    page = FakePage()
    previous = ContentIdentity(page_id="1/60", page_number=1, source_id="source")
    current = previous
    click_count = 0

    async def detect_state(_page: object) -> PageState:
        return PageState.CONTENT

    async def get_identity(_page: object) -> ContentIdentity:
        return current

    async def is_last_page(_page: object) -> bool:
        return False

    async def render_ready(_page: object) -> None:
        return

    async def click_fallback(_page: object) -> None:
        nonlocal current, click_count
        click_count += 1
        current = ContentIdentity(
            page_id="2/60", page_number=2, source_id="source"
        )

    adapter.detect_state = detect_state  # type: ignore[method-assign]
    adapter.get_content_identity = get_identity  # type: ignore[method-assign]
    adapter._is_last_page_counter = is_last_page  # type: ignore[method-assign]
    adapter._wait_for_render_ready = render_ready  # type: ignore[method-assign]
    adapter._click_left_edge = click_fallback  # type: ignore[method-assign]

    await adapter.wait_for_change(page, previous)  # type: ignore[arg-type]

    assert click_count == 1
    assert current.page_id == "2/60"


@pytest.mark.asyncio
async def test_bookwalker_wait_for_change_times_out_after_fallback() -> None:
    class FakePage:
        async def wait_for_timeout(self, _milliseconds: int) -> None:
            return

    adapter = BookWalkerAdapter()
    adapter.page_change_timeout_ms = 200
    adapter.advance_retry_count = 1
    adapter.advance_retry_interval_ms = 100
    page = FakePage()
    identity = ContentIdentity(page_id="1/60", page_number=1, source_id="source")
    click_count = 0

    async def detect_state(_page: object) -> PageState:
        return PageState.CONTENT

    async def get_identity(_page: object) -> ContentIdentity:
        return identity

    async def is_last_page(_page: object) -> bool:
        return False

    async def click_fallback(_page: object) -> None:
        nonlocal click_count
        click_count += 1

    adapter.detect_state = detect_state  # type: ignore[method-assign]
    adapter.get_content_identity = get_identity  # type: ignore[method-assign]
    adapter._is_last_page_counter = is_last_page  # type: ignore[method-assign]
    adapter._click_left_edge = click_fallback  # type: ignore[method-assign]

    with pytest.raises(PageChangeTimeoutError):
        await adapter.wait_for_change(page, identity)  # type: ignore[arg-type]

    assert click_count == 1


@pytest.mark.asyncio
async def test_bookwalker_wait_for_change_alternates_click_and_arrow_retries() -> None:
    class FakePage:
        async def wait_for_timeout(self, _milliseconds: int) -> None:
            return

    adapter = BookWalkerAdapter()
    adapter.page_change_timeout_ms = 700
    adapter.advance_retry_count = 3
    adapter.advance_retry_interval_ms = 100
    page = FakePage()
    identity = ContentIdentity(page_id="1/60", page_number=1, source_id="source")
    actions: list[str] = []

    async def detect_state(_page: object) -> PageState:
        return PageState.CONTENT

    async def get_identity(_page: object) -> ContentIdentity:
        return identity

    async def is_last_page(_page: object) -> bool:
        return False

    async def click_fallback(_page: object) -> None:
        actions.append("click")

    async def press_arrow(_page: object) -> None:
        actions.append("arrow")

    adapter.detect_state = detect_state  # type: ignore[method-assign]
    adapter.get_content_identity = get_identity  # type: ignore[method-assign]
    adapter._is_last_page_counter = is_last_page  # type: ignore[method-assign]
    adapter._click_left_edge = click_fallback  # type: ignore[method-assign]
    adapter._press_left_arrow = press_arrow  # type: ignore[method-assign]

    with pytest.raises(PageChangeTimeoutError):
        await adapter.wait_for_change(page, identity)  # type: ignore[arg-type]

    assert actions == ["click", "arrow", "click"]


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
