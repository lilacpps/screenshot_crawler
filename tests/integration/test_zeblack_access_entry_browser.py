from __future__ import annotations

import pytest
from playwright.async_api import Page

from screenshot_crawler.site_adapters.zeblack.adapter import ZeblackAdapter
from screenshot_crawler.site_adapters.zeblack.live_access import ZeblackLiveAccessState

pytestmark = pytest.mark.asyncio(loop_scope="module")

LIST_URL = "https://zebrack-comic.shueisha.co.jp/title/3890/chapter/list"
TARGET_URL = "https://zebrack-comic.shueisha.co.jp/title/3890/chapter/58493/viewer"
MAIN_NAME = "第25話 プロの実力"


def _chapter_list_html() -> str:
    return f"""
    <div id="chapter58493"><p>{MAIN_NAME}</p></div>
    <script>
      const listUrl = {LIST_URL!r};
      const targetUrl = {TARGET_URL!r};
      const row = document.querySelector('#chapter58493');
      row.querySelector('p').addEventListener('click', () => {{
        row.insertAdjacentHTML('afterend', `
          <div id="modal-root">
            <div>{MAIN_NAME}</div>
            <div id="ticket">チケットを使って読む</div>
            <button id="cancel" type="button">キャンセル</button>
          </div>`);
        document.querySelector('#ticket').addEventListener('click', () => {{
          history.pushState({{}}, '', targetUrl);
          document.body.innerHTML = '<img alt="page_1" src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==">';
        }});
      }});
    </script>
    """


async def test_zeblack_work_ticket_entry_uses_modal_then_target_viewer(
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
            body=_chapter_list_html(),
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
