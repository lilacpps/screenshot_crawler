from __future__ import annotations

import pytest
from playwright.async_api import Page

from screenshot_crawler.core.errors import UnsupportedAccessStrategyError
from screenshot_crawler.site_adapters.zeblack.adapter import ZeblackAdapter
from screenshot_crawler.site_adapters.zeblack.live_access import ZeblackLiveAccessState

pytestmark = pytest.mark.asyncio(loop_scope="module")

LIST_URL = "https://zebrack-comic.shueisha.co.jp/title/3890/chapter/list"
TARGET_URL = "https://zebrack-comic.shueisha.co.jp/title/3890/chapter/58493/viewer"
MAIN_NAME = "第25話 プロの実力"
HYDRATION_LIST_URL = "https://zebrack-comic.shueisha.co.jp/title/11551/chapter/list"
HYDRATION_TARGET_URL = (
    "https://zebrack-comic.shueisha.co.jp/title/11551/chapter/630652/viewer"
)
HYDRATION_MAIN_NAME = "個人指導3"


def _chapter_list_html(
    *,
    unrelated_node_count: int = 0,
    ticket_count: int = 1,
    paid_control: str | None = None,
    modal_main_name: str = MAIN_NAME,
    include_cancel: bool = True,
) -> str:
    unrelated_nodes = "".join(
        f'<div class="junk" data-index="{index}">unrelated-{index}</div>'
        for index in range(unrelated_node_count)
    )
    ticket_controls = "".join(
        '<div class="ticket">チケットを使って読む</div>'
        for _ in range(ticket_count)
    )
    paid_markup = f'<div>{paid_control}</div>' if paid_control else ""
    cancel_markup = (
        '<button id="cancel" type="button">キャンセル</button>'
        if include_cancel
        else ""
    )
    return f"""
    {unrelated_nodes}
    <div id="chapter58493"><p>{MAIN_NAME}</p></div>
    <script>
      const listUrl = {LIST_URL!r};
      const targetUrl = {TARGET_URL!r};
      const row = document.querySelector('#chapter58493');
      row.querySelector('p').addEventListener('click', () => {{
        row.insertAdjacentHTML('afterend', `
          <div id="modal-root">
            <div>{modal_main_name}</div>
            {ticket_controls}
            {cancel_markup}
            {paid_markup}
          </div>`);
        document.querySelector('#modal-root .ticket').addEventListener('click', () => {{
          history.pushState({{}}, '', targetUrl);
          document.body.innerHTML = '<img alt="page_1" src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==">';
        }});
      }});
    </script>
    """


def _chapter_list_with_direct_link_html() -> str:
    return f"""
    <div id="chapter58493">
      <a href="{TARGET_URL}"><p>{MAIN_NAME}</p></a>
    </div>
    """


def _hydrating_chapter_list_html(*, row_mode: str, main_mode: str) -> str:
    row_markup = ""
    if row_mode == "present":
        row_markup = (
            '<div id="chapter630652" style="min-height: 1px;">'
            f"{('<p>' + HYDRATION_MAIN_NAME + ' </p>') if main_mode == 'present' else ''}"
            "</div>"
        )
    elif row_mode == "ambiguous":
        row_markup = (
            '<div id="chapter630652" style="min-height: 1px;"></div>'
            '<div id="chapter630652" style="min-height: 1px;"></div>'
        )
    delayed_row = "" if row_mode != "delayed" else """
      window.setTimeout(() => {
        const row = document.createElement('div');
        row.id = 'chapter630652';
        row.style.minHeight = '1px';
        document.body.appendChild(row);
        window.setTimeout(() => {
          row.innerHTML = '<p>個人指導3 </p>';
        }, 150);
      }, 150);
    """
    delayed_main = "" if main_mode != "delayed" else """
      window.setTimeout(() => {
        document.querySelector('#chapter630652').innerHTML = '<p>個人指導3 </p>';
      }, 150);
    """
    return f"""
    {row_markup}
    <script>
      window.chapterClicks = 0;
      document.addEventListener('click', event => {{
        if (event.target.closest('#chapter630652')) window.chapterClicks += 1;
      }});
      {delayed_row}
      {delayed_main}
    </script>
    """


async def _hydration_adapter(
    page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> ZeblackAdapter:
    adapter = ZeblackAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    assert adapter.resolve_initial_navigation_url(HYDRATION_TARGET_URL) == HYDRATION_LIST_URL
    adapter._live_access = ZeblackLiveAccessState(
        title_id="11551",
        chapter_id="630652",
        target_main_name=HYDRATION_MAIN_NAME,
        status_value=2,
        status_name="TICKET_AVAILABLE",
        ticket_available_ids=("630652",),
    )
    adapter._target_main_name = HYDRATION_MAIN_NAME
    adapter.page_change_timeout_ms = 1_000

    async def wait_for_modal(_page: Page, **_kwargs: object):
        return page.locator("#chapter630652")

    monkeypatch.setattr(adapter, "_wait_for_ticket_modal", wait_for_modal)
    return adapter


@pytest.mark.parametrize(
    "unrelated_node_count",
    [0, 2500],
    ids=["normal_dom", "large_dom"],
)
async def test_zeblack_work_ticket_entry_uses_modal_then_target_viewer(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
    unrelated_node_count: int,
) -> None:
    page = browser_page
    navigation_urls: list[str] = []

    async def fulfill(route) -> None:  # type: ignore[no-untyped-def]
        navigation_urls.append(route.request.url)
        await route.fulfill(
            status=200,
            content_type="text/html; charset=utf-8",
            body=_chapter_list_html(unrelated_node_count=unrelated_node_count),
        )

    await page.route("https://zebrack-comic.shueisha.co.jp/**", fulfill)
    await page.goto(LIST_URL)

    adapter = ZeblackAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    assert adapter.resolve_initial_navigation_url(TARGET_URL) == LIST_URL

    async def observe(_page: Page, **_kwargs: object) -> ZeblackLiveAccessState:
        return ZeblackLiveAccessState(
            title_id="3890",
            chapter_id="58493",
            target_main_name=MAIN_NAME,
            status_value=2,
            status_name="TICKET_AVAILABLE",
            ticket_available_ids=("58493",),
        )

    monkeypatch.setattr(
        "screenshot_crawler.site_adapters.zeblack.adapter.observe_zeblack_live_access",
        observe,
    )

    async def stable_content(_page: Page) -> None:
        return None

    monkeypatch.setattr(adapter, "_wait_for_initial_content", stable_content)
    await adapter._initialize_quota_entry(page, entry_only=True)

    assert page.url == TARGET_URL
    assert navigation_urls == [LIST_URL]
    assert adapter._chapter_click_attempted is True
    assert adapter._ticket_click_attempted is True
    assert adapter.get_access_consumption().consumed is True
    assert adapter.get_access_consumption().resource == "work_ticket"


async def test_zeblack_target_chapter_waits_for_delayed_row_hydration(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = browser_page

    async def fulfill(route) -> None:  # type: ignore[no-untyped-def]
        await route.fulfill(
            status=200,
            content_type="text/html; charset=utf-8",
            body=_hydrating_chapter_list_html(row_mode="delayed", main_mode="delayed"),
        )

    await page.route("https://zebrack-comic.shueisha.co.jp/**", fulfill)
    await page.goto(HYDRATION_LIST_URL)
    adapter = await _hydration_adapter(page, monkeypatch)

    await adapter._click_target_chapter(page)

    assert await page.evaluate("window.chapterClicks") == 1
    assert adapter._chapter_click_attempted is True


async def test_zeblack_target_chapter_waits_for_delayed_main_name_hydration(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = browser_page

    async def fulfill(route) -> None:  # type: ignore[no-untyped-def]
        await route.fulfill(
            status=200,
            content_type="text/html; charset=utf-8",
            body=_hydrating_chapter_list_html(row_mode="present", main_mode="delayed"),
        )

    await page.route("https://zebrack-comic.shueisha.co.jp/**", fulfill)
    await page.goto(HYDRATION_LIST_URL)
    adapter = await _hydration_adapter(page, monkeypatch)

    await adapter._click_target_chapter(page)

    assert await page.evaluate("window.chapterClicks") == 1
    assert adapter._chapter_click_attempted is True


async def test_zeblack_target_chapter_missing_main_name_fails_closed(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = browser_page

    async def fulfill(route) -> None:  # type: ignore[no-untyped-def]
        await route.fulfill(
            status=200,
            content_type="text/html; charset=utf-8",
            body=_hydrating_chapter_list_html(row_mode="present", main_mode="missing"),
        )

    await page.route("https://zebrack-comic.shueisha.co.jp/**", fulfill)
    await page.goto(HYDRATION_LIST_URL)
    adapter = await _hydration_adapter(page, monkeypatch)
    adapter.page_change_timeout_ms = 300

    with pytest.raises(
        UnsupportedAccessStrategyError,
        match="mainName did not become ready",
    ):
        await adapter._click_target_chapter(page)

    assert await page.evaluate("window.chapterClicks") == 0
    assert adapter._chapter_click_attempted is False


async def test_zeblack_target_chapter_ambiguous_row_fails_immediately(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = browser_page

    async def fulfill(route) -> None:  # type: ignore[no-untyped-def]
        await route.fulfill(
            status=200,
            content_type="text/html; charset=utf-8",
            body=_hydrating_chapter_list_html(row_mode="ambiguous", main_mode="missing"),
        )

    await page.route("https://zebrack-comic.shueisha.co.jp/**", fulfill)
    await page.goto(HYDRATION_LIST_URL)
    adapter = await _hydration_adapter(page, monkeypatch)

    with pytest.raises(UnsupportedAccessStrategyError, match="row is ambiguous"):
        await adapter._click_target_chapter(page)

    assert await page.evaluate("window.chapterClicks") == 0
    assert adapter._chapter_click_attempted is False


async def test_zeblack_target_chapter_ambiguous_main_name_fails_immediately(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = browser_page

    async def fulfill(route) -> None:  # type: ignore[no-untyped-def]
        await route.fulfill(
            status=200,
            content_type="text/html; charset=utf-8",
            body="""
            <div id="chapter630652" style="min-height: 1px;">
              <p>個人指導3</p><p>個人指導3</p>
            </div>
            <script>window.chapterClicks = 0;</script>
            """,
        )

    await page.route("https://zebrack-comic.shueisha.co.jp/**", fulfill)
    await page.goto(HYDRATION_LIST_URL)
    adapter = await _hydration_adapter(page, monkeypatch)

    with pytest.raises(
        UnsupportedAccessStrategyError,
        match="mainName is ambiguous",
    ):
        await adapter._click_target_chapter(page)

    assert await page.evaluate("window.chapterClicks") == 0
    assert adapter._chapter_click_attempted is False


@pytest.mark.parametrize(
    ("ticket_count", "paid_control"),
    [(2, None), (1, "ポイントを使って読む")],
    ids=["ambiguous_ticket", "paid_contamination"],
)
async def test_zeblack_modal_identity_rejects_ambiguous_or_paid_controls(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
    ticket_count: int,
    paid_control: str | None,
) -> None:
    page = browser_page

    async def fulfill(route) -> None:  # type: ignore[no-untyped-def]
        await route.fulfill(
            status=200,
            content_type="text/html; charset=utf-8",
            body=_chapter_list_html(
                ticket_count=ticket_count,
                paid_control=paid_control,
            ),
        )

    await page.route("https://zebrack-comic.shueisha.co.jp/**", fulfill)
    await page.goto(LIST_URL)

    adapter = ZeblackAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    assert adapter.resolve_initial_navigation_url(TARGET_URL) == LIST_URL

    async def observe(_page: Page, **_kwargs: object) -> ZeblackLiveAccessState:
        return ZeblackLiveAccessState(
            title_id="3890",
            chapter_id="58493",
            target_main_name=MAIN_NAME,
            status_value=2,
            status_name="TICKET_AVAILABLE",
            ticket_available_ids=("58493",),
        )

    monkeypatch.setattr(
        "screenshot_crawler.site_adapters.zeblack.adapter.observe_zeblack_live_access",
        observe,
    )
    adapter.page_change_timeout_ms = 500

    with pytest.raises(UnsupportedAccessStrategyError):
        await adapter._initialize_quota_entry(page, entry_only=True)

    assert page.url == LIST_URL
    assert adapter._chapter_click_attempted is True
    assert adapter._ticket_click_attempted is False
    assert adapter.get_access_consumption().consumed is False


async def test_zeblack_modal_scope_requires_target_and_cancel_identity(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = browser_page

    async def fulfill(route) -> None:  # type: ignore[no-untyped-def]
        await route.fulfill(
            status=200,
            content_type="text/html; charset=utf-8",
            body=_chapter_list_html(
                modal_main_name="別の章",
                include_cancel=False,
            ),
        )

    await page.route("https://zebrack-comic.shueisha.co.jp/**", fulfill)
    await page.goto(LIST_URL)

    adapter = ZeblackAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    assert adapter.resolve_initial_navigation_url(TARGET_URL) == LIST_URL

    async def observe(_page: Page, **_kwargs: object) -> ZeblackLiveAccessState:
        return ZeblackLiveAccessState(
            title_id="3890",
            chapter_id="58493",
            target_main_name=MAIN_NAME,
            status_value=2,
            status_name="TICKET_AVAILABLE",
            ticket_available_ids=("58493",),
        )

    monkeypatch.setattr(
        "screenshot_crawler.site_adapters.zeblack.adapter.observe_zeblack_live_access",
        observe,
    )
    adapter.page_change_timeout_ms = 500

    with pytest.raises(UnsupportedAccessStrategyError):
        await adapter._initialize_quota_entry(page, entry_only=True)

    assert page.url == LIST_URL
    assert adapter._chapter_click_attempted is True
    assert adapter._ticket_click_attempted is False
    assert adapter.get_access_consumption().consumed is False


async def test_zeblack_direct_viewer_link_is_rejected_before_chapter_click(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = browser_page
    navigation_urls: list[str] = []

    async def fulfill(route) -> None:  # type: ignore[no-untyped-def]
        navigation_urls.append(route.request.url)
        await route.fulfill(
            status=200,
            content_type="text/html; charset=utf-8",
            body=_chapter_list_with_direct_link_html(),
        )

    await page.route("https://zebrack-comic.shueisha.co.jp/**", fulfill)
    await page.goto(LIST_URL)

    adapter = ZeblackAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    assert adapter.resolve_initial_navigation_url(TARGET_URL) == LIST_URL

    async def observe(_page: Page, **_kwargs: object) -> ZeblackLiveAccessState:
        return ZeblackLiveAccessState(
            title_id="3890",
            chapter_id="58493",
            target_main_name=MAIN_NAME,
            status_value=2,
            status_name="TICKET_AVAILABLE",
            ticket_available_ids=("58493",),
        )

    monkeypatch.setattr(
        "screenshot_crawler.site_adapters.zeblack.adapter.observe_zeblack_live_access",
        observe,
    )

    with pytest.raises(
        UnsupportedAccessStrategyError,
        match="direct navigation link",
    ):
        await adapter._initialize_quota_entry(page, entry_only=True)

    assert page.url == LIST_URL
    assert navigation_urls == [LIST_URL]
    assert adapter._chapter_click_attempted is False
    assert adapter._ticket_click_attempted is False
    assert adapter.get_access_consumption().consumed is False
