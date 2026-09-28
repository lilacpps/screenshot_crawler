from __future__ import annotations

import io
from types import SimpleNamespace
from urllib.parse import quote

import pytest
import pytest_asyncio
from PIL import Image
from playwright.async_api import Browser, BrowserContext, Error, Page, async_playwright

from screenshot_crawler.core.errors import (
    AccessResourceUnavailableError,
    PageChangeTimeoutError,
    UnsupportedAccessStrategyError,
)
from screenshot_crawler.core.models import ContentContext, ContentIdentity
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.magapoke.adapter import (
    _WORK_TICKET_TEXT,
    MagapokeAdapter,
)

pytestmark = pytest.mark.asyncio(loop_scope="module")

SOURCE_PATH = "/static/web_titles/695/episodes/244815/p1.jpg"


def _response(url: str, *, content_type: str = "image/jpeg", resource_type: str = "image"):
    return SimpleNamespace(
        url=url,
        headers={"content-type": content_type},
        request=SimpleNamespace(resource_type=resource_type),
    )


def _mapping(*, sx: int, sy: int, sw: int, sh: int, dx: int, dy: int, **overrides):
    result = {
        "sourcePath": SOURCE_PATH,
        "sourceWidth": 10,
        "sourceHeight": 7,
        "canvasWidth": 10,
        "canvasHeight": 7,
        "sx": sx,
        "sy": sy,
        "sw": sw,
        "sh": sh,
        "dx": dx,
        "dy": dy,
        "dw": sw,
        "dh": sh,
        "transform": [1, 0, 0, 1, 0, 0],
        "compositeOperation": "source-over",
        "filter": "none",
    }
    result.update(overrides)
    return result


BASE = _mapping(sx=0, sy=0, sw=10, sh=7, dx=0, dy=0)
VISIBLE = BASE
MAPPINGS = [
    _mapping(sx=0, sy=0, sw=3, sh=7, dx=7, dy=0),
    _mapping(sx=3, sy=0, sw=7, sh=7, dx=0, dy=0),
]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def playwright_instance():
    playwright = await async_playwright().start()
    try:
        yield playwright
    finally:
        await playwright.stop()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def browser(playwright_instance) -> Browser:
    try:
        browser = await playwright_instance.chromium.launch(headless=True)
    except Error as exc:
        pytest.skip(f"Chromium is unavailable: {exc}")
    try:
        yield browser
    finally:
        await browser.close()


@pytest_asyncio.fixture(loop_scope="module")
async def browser_context(browser: Browser) -> BrowserContext:
    context = await browser.new_context()
    try:
        yield context
    finally:
        await context.close()


@pytest_asyncio.fixture(loop_scope="module")
async def browser_page(browser_context: BrowserContext) -> Page:
    page = await browser_context.new_page()
    try:
        yield page
    finally:
        await page.close()


LEADING_NON_CONTENT_VIEWER = """
  <div class="c-viewer__pages">
    <div class="c-viewer__pages-item"><img src="/ad.jpg"></div>
    <div class="c-viewer__pages-item"></div>
    <div class="c-viewer__pages-item">
      <div class="c-viewer__comic"><canvas width="10" height="10"></canvas></div>
    </div>
    <div class="c-viewer__pages-item">
      <div class="c-viewer__comic"><canvas width="10" height="10"></canvas></div>
    </div>
  </div>
  <button class="c-viewer__pager-next" type="button">next</button>
  <button class="c-viewer__pager-prev" type="button">previous</button>
  <script>window.prevClicks = 0; window.nextClicks = 0;</script>
"""


async def _install_leading_non_content_viewer(
    adapter: MagapokeAdapter, page: Page
) -> None:
    await adapter.prepare_page(page)
    await page.goto(f"data:text/html,{quote(LEADING_NON_CONTENT_VIEWER)}")


@pytest.mark.asyncio(loop_scope="module")
async def test_first_content_page_index_ignores_ad_and_blank_items(browser_page: Page) -> None:
    page = browser_page
    adapter = MagapokeAdapter()
    await _install_leading_non_content_viewer(adapter, page)

    assert await adapter._first_content_page_index(page) == 2


@pytest.mark.asyncio(loop_scope="module")
async def test_initialize_does_not_rewind_when_first_content_starts_at_page_index_two(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = browser_page
    adapter = MagapokeAdapter()
    await _install_leading_non_content_viewer(adapter, page)

    async def rows(_page: object) -> list[dict[str, object]]:
        return [{"pageIndex": 2}, {"pageIndex": 3}]

    async def render_ready(_page: object, **_kwargs: object) -> None:
        return None

    async def content_context(_page: object) -> ContentContext:
        return ContentContext(content_id="episode", title="Title")

    monkeypatch.setattr(adapter, "_canvas_rows", rows)
    monkeypatch.setattr(adapter, "_wait_for_render_ready", render_ready)
    monkeypatch.setattr(adapter, "get_content_context", content_context)

    await adapter.initialize(page)

    assert await page.evaluate("window.prevClicks") == 0


@pytest.mark.asyncio(loop_scope="module")
async def test_initialize_does_not_rewind_while_canvas_rows_are_empty(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = browser_page
    adapter = MagapokeAdapter()
    await _install_leading_non_content_viewer(adapter, page)

    async def no_rows(_page: object) -> list[dict[str, object]]:
        return []

    async def render_ready(_page: object, **_kwargs: object) -> None:
        return None

    async def content_context(_page: object) -> ContentContext:
        return ContentContext(content_id="episode", title="Title")

    monkeypatch.setattr(adapter, "_canvas_rows", no_rows)
    monkeypatch.setattr(adapter, "_wait_for_render_ready", render_ready)
    monkeypatch.setattr(adapter, "get_content_context", content_context)

    await adapter.initialize(page)

    assert await page.evaluate("window.prevClicks") == 0
    debug = await adapter.collect_debug_metadata(page)
    recovery = debug["magapoke_entry_confirmation"]["initial_viewer_recovery"]
    assert recovery["first_content_page_index"] == 2
    assert recovery["initial_canvas_row_count"] == 0
    assert recovery["final_canvas_row_count"] == 0
    assert recovery["next_click_count"] == 0
    assert recovery["last_reason"] == "waiting_for_geometry"


@pytest.mark.asyncio(loop_scope="module")
async def test_initialize_recovers_when_first_content_is_left_of_viewer_prefix(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = browser_page
    adapter = MagapokeAdapter()
    await _install_leading_non_content_viewer(adapter, page)
    await page.locator(".c-viewer__pages-item").nth(2).evaluate(
        "element => { element.style.position = 'absolute'; element.style.left = '-2000px'; }"
    )
    await page.locator(".c-viewer__pager-next").evaluate(
        """element => element.onclick = () => {
            window.nextClicks++;
            document.querySelectorAll('.c-viewer__pages-item')[2].style.left = '0px';
        }"""
    )
    adapter.page_change_timeout_ms = 1_000

    async def rows(_page: object) -> list[dict[str, object]]:
        if await page.evaluate("window.nextClicks") == 0:
            return []
        return [{"pageIndex": 2, "sourcePath": SOURCE_PATH, "x": 0, "y": 0}]

    async def content_context(_page: object) -> ContentContext:
        return ContentContext(content_id="episode", title="Title")

    monkeypatch.setattr(adapter, "_canvas_rows", rows)
    monkeypatch.setattr(adapter, "get_content_context", content_context)

    await adapter.initialize(page)

    assert await page.evaluate("window.nextClicks") == 1
    assert await page.evaluate("window.prevClicks") == 0
    assert adapter._initial_viewer_recovery["next_click_count"] == 1


@pytest.mark.asyncio(loop_scope="module")
async def test_initial_prefix_waits_for_geometry_before_clicking_next(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = browser_page
    adapter = MagapokeAdapter()
    await _install_leading_non_content_viewer(adapter, page)
    await page.locator(".c-viewer__pager-next").evaluate(
        """element => element.onclick = () => {
            window.nextClicks++;
            document.querySelectorAll('.c-viewer__pages-item')[2].style.left = '0px';
        }"""
    )
    adapter.page_change_timeout_ms = 1_000
    geometry = {
        "index": 2,
        "left": -2_000,
        "right": -1_000,
        "viewportLeft": 0,
        "viewportRight": 1_000,
    }
    geometry_values = [None, geometry]

    async def delayed_geometry(_page: object) -> dict[str, float | int] | None:
        return geometry_values.pop(0) if geometry_values else geometry

    async def rows(_page: object) -> list[dict[str, object]]:
        if await page.evaluate("window.nextClicks") == 0:
            return []
        return [{"pageIndex": 2, "sourcePath": SOURCE_PATH, "x": 0, "y": 0}]

    monkeypatch.setattr(adapter, "_first_content_page_geometry", delayed_geometry)
    monkeypatch.setattr(adapter, "_canvas_rows", rows)

    adapter._initial_viewer_recovery = {
        "next_click_count": 0,
        "last_reason": "waiting_for_geometry",
    }
    await adapter._wait_for_render_ready(page, recover_initial_prefix=True)

    assert await page.evaluate("window.nextClicks") == 1
    assert adapter._initial_viewer_recovery["last_reason"] == "content_visible"


@pytest.mark.asyncio(loop_scope="module")
async def test_initial_prefix_with_unknown_geometry_times_out_without_clicking(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = browser_page
    adapter = MagapokeAdapter()
    await _install_leading_non_content_viewer(adapter, page)
    adapter.page_change_timeout_ms = 250
    adapter._initial_viewer_recovery = {"next_click_count": 0}

    async def no_geometry(_page: object) -> None:
        return None

    async def no_rows(_page: object) -> list[dict[str, object]]:
        return []

    monkeypatch.setattr(adapter, "_first_content_page_geometry", no_geometry)
    monkeypatch.setattr(adapter, "_canvas_rows", no_rows)

    with pytest.raises(PageChangeTimeoutError, match="did not finish loading"):
        await adapter._wait_for_render_ready(page, recover_initial_prefix=True)

    assert await page.evaluate("window.nextClicks") == 0
    assert adapter._initial_viewer_recovery["last_reason"] == "geometry_unavailable"


@pytest.mark.asyncio(loop_scope="module")
async def test_initial_prefix_url_change_fails_closed(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = browser_page
    adapter = MagapokeAdapter()
    await _install_leading_non_content_viewer(adapter, page)
    adapter.page_change_timeout_ms = 1_000
    await page.locator(".c-viewer__pager-next").evaluate(
        "element => element.onclick = () => { history.pushState({}, '', '#changed'); }"
    )
    geometry = {
        "index": 2,
        "left": -2_000,
        "right": -1_000,
        "viewportLeft": 0,
        "viewportRight": 1_000,
    }
    async def fixed_geometry(_page: object) -> dict[str, float | int]:
        return geometry

    monkeypatch.setattr(adapter, "_first_content_page_geometry", fixed_geometry)
    async def no_rows(_page: object) -> list[dict[str, object]]:
        return []

    monkeypatch.setattr(adapter, "_canvas_rows", no_rows)
    adapter._initial_url = page.url
    adapter._initial_viewer_recovery = {"next_click_count": 0}

    with pytest.raises(PageChangeTimeoutError, match="changed episode"):
        await adapter._wait_for_render_ready(page, recover_initial_prefix=True)

    assert adapter._initial_viewer_recovery["next_click_count"] == 1


@pytest.mark.asyncio(loop_scope="module")
async def test_rewind_stops_at_first_content_page_index_without_overshooting(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = browser_page
    adapter = MagapokeAdapter()
    await _install_leading_non_content_viewer(adapter, page)
    await page.locator(".c-viewer__pager-prev").evaluate(
        "element => element.onclick = () => { window.prevClicks++; window.currentIndex--; }"
    )
    await page.evaluate("window.currentIndex = 5")

    async def rows(_page: object) -> list[dict[str, object]]:
        return [{"pageIndex": await page.evaluate("window.currentIndex")}]

    monkeypatch.setattr(adapter, "_canvas_rows", rows)

    await adapter._rewind_to_first_content(page)

    assert await page.evaluate("window.prevClicks") == 3
    assert await page.evaluate("window.currentIndex") == 2


@pytest.mark.asyncio(loop_scope="module")
async def test_rewind_does_not_click_when_canvas_rows_are_empty(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = browser_page
    adapter = MagapokeAdapter()
    await _install_leading_non_content_viewer(adapter, page)

    async def no_rows(_page: object) -> list[dict[str, object]]:
        return []

    monkeypatch.setattr(adapter, "_canvas_rows", no_rows)

    await adapter._rewind_to_first_content(page)

    assert await page.evaluate("window.prevClicks") == 0


@pytest.mark.asyncio(loop_scope="module")
async def test_work_ticket_entry_clicks_exact_unique_control_once_and_confirms_content(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = browser_page
    await page.set_content("""
      <div class="p-episode-purchase">
        <a class="c-btn-icon-primary c-btn-icon-primary--ticket" href="javascript:void(0)">
          作品チケットで読む
        </a>
      </div>
      <script>
        window.clicks = 0;
        document.querySelector('a').addEventListener('click', () => {
          window.clicks++;
          document.querySelector('.p-episode-purchase').remove();
          document.body.insertAdjacentHTML('beforeend', '<canvas width="10" height="10"></canvas>');
        });
      </script>
    """)
    adapter = MagapokeAdapter()
    async def rows(_page):
        return [{"pageIndex": 0}] if await page.locator("canvas").count() else []
    monkeypatch.setattr(adapter, "_canvas_rows", rows)
    await adapter._enter_with_work_ticket(page)
    consumption = adapter.get_access_consumption()
    assert await page.evaluate("window.clicks") == 1
    assert consumption.consumed is True
    assert consumption.resource == "work_ticket"
    assert consumption.consumed_at is not None and consumption.consumed_at.utcoffset() is not None


@pytest.mark.asyncio(loop_scope="module")
async def test_work_ticket_confirmation_accepts_visible_viewer_without_canvas_rows(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = browser_page
    await page.set_content("""
      <div class="p-episode-purchase">
        <a class="c-btn-icon-primary c-btn-icon-primary--ticket" href="javascript:void(0)">
          菴懷刀繝√こ繝・ヨ縺ｧ隱ｭ繧
        </a>
      </div>
      <script>
        document.querySelector('a').addEventListener('click', event => {
          event.preventDefault();
          document.querySelector('.p-episode-purchase').remove();
          document.body.insertAdjacentHTML(
            'beforeend', '<div class="c-viewer__comic"><canvas width="10" height="10"></canvas></div>'
          );
        });
      </script>
    """)
    await page.locator("a").evaluate(
        "(element, text) => element.textContent = text", _WORK_TICKET_TEXT
    )
    adapter = MagapokeAdapter()
    async def no_rows(_page: object) -> list[dict[str, object]]:
        return []

    monkeypatch.setattr(adapter, "_canvas_rows", no_rows)

    await adapter._enter_with_work_ticket(page)

    consumption = adapter.get_access_consumption()
    assert consumption.consumed is True
    assert consumption.resource == "work_ticket"


@pytest.mark.asyncio(loop_scope="module")
async def test_work_ticket_confirmation_retries_transient_reload_probe_error(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = browser_page
    adapter = MagapokeAdapter()
    adapter.page_change_timeout_ms = 500
    probe_calls = 0

    async def rows(_page: object) -> list[dict[str, object]]:
        return []

    async def viewer(_page: object) -> bool:
        return True

    async def controls(_page: object) -> list[dict[str, object]]:
        nonlocal probe_calls
        probe_calls += 1
        if probe_calls == 1:
            raise Error("Execution context was destroyed")
        return []

    monkeypatch.setattr(adapter, "_canvas_rows", rows)
    monkeypatch.setattr(adapter, "_viewer_canvas_visible", viewer)
    monkeypatch.setattr(adapter, "_visible_access_control_state", controls)

    await adapter._confirm_ticket_consumption(page, resource="work_ticket")

    assert adapter.get_access_consumption().consumed is True
    assert probe_calls == 2
    outcomes = [item.get("outcome") for item in adapter._confirmation_trace]
    assert "transient_probe_error" in outcomes
    assert "confirmed" in outcomes


@pytest.mark.asyncio(loop_scope="module")
async def test_entry_only_initialization_skips_native_render_readiness(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = browser_page
    await page.set_content("""
      <div class="p-episode-purchase">
        <a class="c-btn-icon-primary c-btn-icon-primary--ticket" href="javascript:void(0)">
          作品チケットで読む
        </a>
      </div>
      <script>
        document.querySelector('a').addEventListener('click', event => {
          event.preventDefault();
          document.querySelector('.p-episode-purchase').remove();
          document.body.insertAdjacentHTML(
            'beforeend', '<div class="c-viewer__comic"><canvas width="10" height="10"></canvas></div>'
          );
        });
      </script>
    """)
    adapter = MagapokeAdapter()
    adapter.page_change_timeout_ms = 500
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")

    async def no_rows(_page: object) -> list[dict[str, object]]:
        return []

    async def unexpected_readiness(_page: object, **_kwargs: object) -> None:
        raise AssertionError("entry-only initialization must not wait for render readiness")

    async def unexpected_rewind(_page: object) -> None:
        raise AssertionError("entry-only initialization must not rewind the viewer")

    monkeypatch.setattr(adapter, "_canvas_rows", no_rows)
    monkeypatch.setattr(adapter, "_wait_for_render_ready", unexpected_readiness)
    monkeypatch.setattr(adapter, "_rewind_to_first_content", unexpected_rewind)

    await adapter.initialize_entry_only(page)

    consumption = adapter.get_access_consumption()
    assert consumption.consumed is True
    assert consumption.resource == "work_ticket"
    debug = await adapter.collect_debug_metadata(page)
    confirmation = debug["magapoke_entry_confirmation"]
    assert confirmation["initialization_mode"] == "entry_only"
    assert confirmation["canvas_row_count"] == 0
    assert confirmation["viewer_canvas_visible"] is True


@pytest.mark.asyncio(loop_scope="module")
async def test_initialize_waits_for_delayed_work_ticket_control_without_early_click(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = browser_page
    await page.set_content(r"""
      <div class="p-episode-purchase">
        <div class="p-episode-purchase__btn">
          <a class="p-episode-comment-btn p-episode-comment-btn--pc" href="#comment">Comments</a>
        </div>
        <div class="p-episode-purchase__btn" id="access-actions"></div>
      </div>
      <script>
        window.workClicks = 0;
        window.commentClicks = 0;
        document.querySelector('.p-episode-comment-btn').addEventListener('click', event => {
          event.preventDefault(); window.commentClicks++;
        });
        setTimeout(() => {
          const work = document.createElement('a');
          work.className = 'c-btn-icon-primary c-btn-icon-primary--ticket';
          work.href = 'javascript:void(0);';
          work.textContent = '\u4f5c\u54c1\u30c1\u30b1\u30c3\u30c8\u3067\u8aad\u3080';
          work.addEventListener('click', event => {
            event.preventDefault(); window.workClicks++; work.remove();
            document.querySelector('.p-episode-purchase').insertAdjacentHTML(
              'afterend', '<div class="c-viewer__comic"><canvas width="10" height="10"></canvas></div>'
            );
          });
          document.querySelector('#access-actions').append(work);
        }, 150);
      </script>
    """)
    adapter = MagapokeAdapter()
    adapter.page_change_timeout_ms = 1200
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")

    assert await adapter._visible_access_controls(page) == []
    assert not await adapter._viewer_canvas_visible(page)

    async def rows(_page):
        return [{"pageIndex": 0}] if await page.locator(".c-viewer__comic canvas").count() else []

    async def render_ready(_page, **_kwargs):
        return None

    async def content_context(_page):
        return ContentContext(content_id="episode")

    monkeypatch.setattr(adapter, "_canvas_rows", rows)
    monkeypatch.setattr(adapter, "_wait_for_render_ready", render_ready)
    monkeypatch.setattr(adapter, "get_content_context", content_context)

    await adapter.initialize(page)

    assert await page.evaluate("window.workClicks") == 1
    assert await page.evaluate("window.commentClicks") == 0
    assert adapter.get_access_consumption().consumed is True
    debug = await adapter.collect_debug_metadata(page)
    confirmation = debug["magapoke_entry_confirmation"]
    assert confirmation["ticket_click_attempted"] is True
    assert confirmation["poll_count"] >= 1
    assert any(
        item.get("outcome") == "confirmed" for item in confirmation["trace"]
    )


@pytest.mark.asyncio(loop_scope="module")
async def test_work_ticket_control_ignores_live_comment_navigation_link(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = browser_page
    await page.set_content(r"""
      <div class="p-episode-purchase">
        <div class="p-episode-purchase__btn">
          <a class="c-btn-icon-primary c-btn-icon-primary--ticket" href="javascript:void(0);"></a>
        </div>
        <div class="p-episode-purchase__btn">
          <a class="p-episode-comment-btn p-episode-comment-btn--pc" href="#comment">Comments</a>
          <a class="p-episode-comment-btn p-episode-comment-btn--sp" href="javascript:void(0);">Comments</a>
        </div>
      </div>
      <script>
        window.workClicks=0; window.commentClicks=0;
        const work = document.querySelector('.c-btn-icon-primary--ticket');
        work.textContent = '\u4f5c\u54c1\u30c1\u30b1\u30c3\u30c8\u3067\u8aad\u3080';
        work.addEventListener('click', event => {
          event.preventDefault(); window.workClicks++;
          event.currentTarget.remove();
          document.body.insertAdjacentHTML('beforeend', '<div class="c-viewer__comic"><canvas width="10" height="10"></canvas></div>');
        });
        document.querySelectorAll('.p-episode-comment-btn').forEach(link => link.addEventListener('click', event => {
          event.preventDefault(); window.commentClicks++;
        }));
      </script>
    """)
    adapter = MagapokeAdapter()

    async def rows(_page):
        return [{"pageIndex": 0}] if await page.locator(".c-viewer__comic canvas").count() else []

    monkeypatch.setattr(adapter, "_canvas_rows", rows)
    visible = await adapter._visible_access_controls(page)
    assert len(visible) == 1
    await adapter._enter_with_work_ticket(page)

    assert await page.evaluate("window.workClicks") == 1
    assert await page.evaluate("window.commentClicks") == 0
    assert adapter.get_access_consumption().consumed is True


@pytest.mark.asyncio(loop_scope="module")
async def test_work_ticket_entry_times_out_if_no_access_ui_or_viewer_appears(browser_page: Page) -> None:
    page = browser_page
    await page.set_content('<div class="p-episode-purchase"></div>')
    adapter = MagapokeAdapter()
    adapter.page_change_timeout_ms = 250
    with pytest.raises(PageChangeTimeoutError, match="access controls did not load"):
        await adapter._enter_with_work_ticket(page)
    assert adapter.get_access_consumption().consumed is False


@pytest.mark.asyncio(loop_scope="module")
async def test_visible_magapoke_terminal_card_is_end(browser_page: Page) -> None:
    page = browser_page
    await page.set_content(
        """
        <div class="c-viewer">
          <div class="c-viewer__last">
            <a class="c-viewer__page-btn" href="javascript:void(0)">次の話を読む</a>
          </div>
        </div>
        """
    )
    adapter = MagapokeAdapter()

    assert await adapter.detect_state(page) is PageState.END


@pytest.mark.asyncio(loop_scope="module")
async def test_magapoke_go_next_avoids_page_number_overlay(browser_page: Page) -> None:
    page = browser_page
    await page.set_content(
        """
        <style>
          .c-viewer__pager { position: fixed; left: 0; top: 0; width: 800px; height: 600px; }
          .c-viewer__pager-next { display: block; width: 400px; height: 600px; }
          .c-viewer__pages { position: fixed; left: 0; top: 0; width: 800px; height: 600px; z-index: 20; pointer-events: none; }
          .c-viewer__page-btn { position: absolute; left: 160px; top: 250px; width: 240px; height: 100px; pointer-events: auto; }
        </style>
        <div class="c-viewer__pager">
          <a class="c-viewer__pager-next">次の話</a>
        </div>
        <div class="c-viewer__pages">
          <a class="c-viewer__page-btn" href="#">5</a>
        </div>
        <script>
          window.nextClicks = 0;
          document.querySelector('.c-viewer__pager-next').onclick = () => window.nextClicks++;
        </script>
        """
    )
    adapter = MagapokeAdapter()

    await adapter.go_next(page)

    assert await page.evaluate("window.nextClicks") == 1


@pytest.mark.asyncio(loop_scope="module")
async def test_visible_magapoke_content_takes_precedence_over_terminal(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = browser_page
    await page.set_content(
        """
        <div class="c-viewer">
          <div class="c-viewer__comic"><canvas width="10" height="10"></canvas></div>
          <div class="c-viewer__last">
            <a class="c-viewer__page-btn" href="javascript:void(0)">次の話を読む</a>
          </div>
        </div>
        """
    )
    adapter = MagapokeAdapter()

    async def current_content(_page: Page) -> list[dict[str, object]]:
        return [{"index": 0, "pageIndex": 0, "sourcePath": "/content.jpg"}]

    monkeypatch.setattr(adapter, "_canvas_rows", current_content)

    assert await adapter.detect_state(page) is PageState.CONTENT


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.parametrize(
    "style",
    ["display: none", "position: absolute; top: 2000px; left: 0"],
)
async def test_magapoke_terminal_card_must_be_in_viewport(browser_page: Page, style: str) -> None:
    page = browser_page
    await page.set_content(
        f"""
        <div class="c-viewer">
          <div class="c-viewer__last" style="{style}">
            <a class="c-viewer__page-btn" href="javascript:void(0)">次の話を読む</a>
          </div>
        </div>
        """
    )
    adapter = MagapokeAdapter()

    assert await adapter.detect_state(page) is PageState.UNKNOWN


@pytest.mark.asyncio(loop_scope="module")
async def test_magapoke_wait_for_change_stops_on_terminal_card_without_retrying_next(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = browser_page
    await page.set_content(
        """
        <div class="c-viewer">
          <div class="c-viewer__last">
            <a class="c-viewer__page-btn" href="javascript:void(0)">次の話を読む</a>
          </div>
        </div>
        """
    )
    adapter = MagapokeAdapter()
    adapter.page_change_timeout_ms = 1_000
    next_calls = 0

    async def unexpected_next(_page: Page) -> None:
        nonlocal next_calls
        next_calls += 1

    monkeypatch.setattr(adapter, "go_next", unexpected_next)
    await adapter.wait_for_change(page, ContentIdentity(page_id="previous"))

    assert next_calls == 0
    assert adapter._advance_pending is False


@pytest.mark.asyncio(loop_scope="module")
async def test_magapoke_wait_for_change_prioritizes_new_content_over_terminal(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = browser_page
    await page.set_content(
        """
        <div class="c-viewer">
          <div class="c-viewer__comic"><canvas width="10" height="10"></canvas></div>
          <div class="c-viewer__last">
            <a class="c-viewer__page-btn" href="javascript:void(0)">次の話を読む</a>
          </div>
        </div>
        """
    )
    adapter = MagapokeAdapter()
    adapter.page_change_timeout_ms = 1_000
    render_ready_calls = 0
    next_calls = 0

    async def new_identity(_page: Page) -> ContentIdentity:
        return ContentIdentity(page_id="new-content")

    async def current_content(_page: Page) -> list[dict[str, object]]:
        return [{"index": 0, "pageIndex": 1, "sourcePath": "/new-content.jpg"}]

    async def render_ready(_page: Page, **_: object) -> None:
        nonlocal render_ready_calls
        render_ready_calls += 1

    async def unexpected_next(_page: Page) -> None:
        nonlocal next_calls
        next_calls += 1

    monkeypatch.setattr(adapter, "get_content_identity", new_identity)
    monkeypatch.setattr(adapter, "_canvas_rows", current_content)
    monkeypatch.setattr(adapter, "_wait_for_render_ready", render_ready)
    monkeypatch.setattr(adapter, "go_next", unexpected_next)

    await adapter.wait_for_change(page, ContentIdentity(page_id="previous"))

    assert render_ready_calls == 1
    assert next_calls == 0
    assert adapter._advance_pending is False


@pytest.mark.asyncio(loop_scope="module")
async def test_premium_only_is_expected_unavailable_without_click(browser_page: Page) -> None:
    page = browser_page
    await page.set_content("""
      <div class="p-episode-purchase">
        <a class="c-btn-icon-primary c-btn-icon-primary--premium-ticket">
          プレミアムチケットで読む
        </a>
      </div>
      <script>window.clicks = 0; document.querySelector('a').onclick = () => window.clicks++;</script>
    """)
    adapter = MagapokeAdapter()
    with pytest.raises(AccessResourceUnavailableError, match="work_ticket_unavailable"):
        await adapter._enter_with_work_ticket(page)
    assert await page.evaluate("window.clicks") == 0
    assert adapter.get_access_consumption().consumed is False


@pytest.mark.asyncio(loop_scope="module")
async def test_premium_ticket_click_requires_semantic_positive_balance_and_confirms(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = browser_page
    await page.set_content("""
      <div class="p-episode-purchase">
        <a class="c-btn-icon-primary c-btn-icon-primary--premium-ticket" href="javascript:void(0);">
          プレミアムチケットで読む
        </a>
        <dl class="p-episode-purchase__point">
          <dt class="p-episode-purchase__point-ttl">プレミアムチケット</dt>
          <dd class="p-episode-purchase__point-data">8枚</dd>
        </dl>
      </div>
      <script>
        window.premiumClicks = 0;
        window.document.querySelector('a').addEventListener('click', event => {
          event.preventDefault(); window.premiumClicks++;
          event.currentTarget.remove();
          document.body.insertAdjacentHTML('beforeend',
            '<div class="c-viewer__comic"><canvas width="10" height="10"></canvas></div>');
        });
      </script>
    """)
    adapter = MagapokeAdapter()

    async def rows(_page):
        return [{"pageIndex": 0}] if await page.locator("canvas").count() else []

    monkeypatch.setattr(adapter, "_canvas_rows", rows)
    await adapter._enter_with_premium_ticket(page)

    consumption = adapter.get_access_consumption()
    assert await page.evaluate("window.premiumClicks") == 1
    assert consumption.consumed is True
    assert consumption.resource == "premium_ticket"
    assert consumption.consumed_at is not None
    assert consumption.consumed_at.utcoffset() is not None


@pytest.mark.asyncio(loop_scope="module")
async def test_zero_premium_balance_is_expected_exhaustion_without_click(browser_page: Page) -> None:
    page = browser_page
    await page.set_content("""
      <div class="p-episode-purchase">
        <a class="c-btn-icon-primary c-btn-icon-primary--premium-ticket">プレミアムチケットで読む</a>
        <dl class="p-episode-purchase__point">
          <dt class="p-episode-purchase__point-ttl">プレミアムチケット</dt>
          <dd class="p-episode-purchase__point-data">0枚</dd>
        </dl>
      </div>
      <script>window.clicks=0; document.querySelector('a').onclick=()=>window.clicks++;</script>
    """)
    adapter = MagapokeAdapter()
    with pytest.raises(AccessResourceUnavailableError) as error:
        await adapter._enter_with_premium_ticket(page)
    assert error.value.reason == "premium_ticket_exhausted"
    assert error.value.stop_resource_pass is True
    assert await page.evaluate("window.clicks") == 0
    assert adapter.get_access_consumption().consumed is False


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.parametrize(
    "balance_markup",
    [
        "",
        "<dl class='p-episode-purchase__point'><dt class='p-episode-purchase__point-ttl'>ポイント</dt><dd class='p-episode-purchase__point-data'>8枚</dd></dl>",
        "<dl class='p-episode-purchase__point'><dt class='p-episode-purchase__point-ttl'>プレミアムチケット</dt><dd class='p-episode-purchase__point-data'>たくさん</dd></dl>",
        "<dl class='p-episode-purchase__point'><dt class='p-episode-purchase__point-ttl'>プレミアムチケット</dt><dt class='p-episode-purchase__point-ttl'>プレミアムチケット</dt><dd class='p-episode-purchase__point-data'>8枚</dd></dl>",
        "<dl class='p-episode-purchase__point'><dt class='p-episode-purchase__point-ttl'>プレミアムチケット</dt><dd class='p-episode-purchase__point-data'>8枚</dd></dl><dl class='p-episode-purchase__point'><dt class='p-episode-purchase__point-ttl'>プレミアムチケット</dt><dd class='p-episode-purchase__point-data'>8枚</dd></dl>",
    ],
)
async def test_premium_balance_unknown_fails_closed_without_click(browser_page: Page, balance_markup: str) -> None:
    page = browser_page
    await page.set_content(
        '<div class="p-episode-purchase">'
        '<a class="c-btn-icon-primary c-btn-icon-primary--premium-ticket">'
        'プレミアムチケットで読む</a>'
        + balance_markup
        + '</div><script>window.clicks=0;document.querySelector("a").onclick=()=>window.clicks++;</script>'
    )
    adapter = MagapokeAdapter()
    with pytest.raises(UnsupportedAccessStrategyError):
        await adapter._enter_with_premium_ticket(page)
    assert await page.evaluate("window.clicks") == 0
    assert adapter.get_access_consumption().consumed is False


@pytest.mark.asyncio(loop_scope="module")
async def test_premium_request_skips_work_only_control_without_fallback(browser_page: Page) -> None:
    page = browser_page
    await page.set_content("""
      <div class="p-episode-purchase">
        <a class="c-btn-icon-primary c-btn-icon-primary--ticket">作品チケットで読む</a>
      </div>
      <script>window.clicks=0;document.querySelector('a').onclick=()=>window.clicks++;</script>
    """)
    adapter = MagapokeAdapter()
    with pytest.raises(AccessResourceUnavailableError) as error:
        await adapter._enter_with_premium_ticket(page)
    assert error.value.reason == "premium_ticket_unavailable"
    assert await page.evaluate("window.clicks") == 0


@pytest.mark.asyncio(loop_scope="module")
async def test_premium_request_rejects_work_and_premium_controls_without_click(browser_page: Page) -> None:
    page = browser_page
    await page.set_content("""
      <div class="p-episode-purchase">
        <a class="c-btn-icon-primary c-btn-icon-primary--ticket">作品チケットで読む</a>
        <a class="c-btn-icon-primary c-btn-icon-primary--premium-ticket">プレミアムチケットで読む</a>
        <dl class="p-episode-purchase__point">
          <dt class="p-episode-purchase__point-ttl">プレミアムチケット</dt>
          <dd class="p-episode-purchase__point-data">8枚</dd>
        </dl>
      </div>
      <script>
        window.workClicks=0; window.premiumClicks=0;
        document.querySelector('.c-btn-icon-primary--ticket').onclick=()=>window.workClicks++;
        document.querySelector('.c-btn-icon-primary--premium-ticket').onclick=()=>window.premiumClicks++;
      </script>
    """)
    adapter = MagapokeAdapter()
    with pytest.raises(AccessResourceUnavailableError) as error:
        await adapter._enter_with_premium_ticket(page)
    assert error.value.reason == "premium_ticket_unavailable"
    assert await page.evaluate("window.workClicks") == 0
    assert await page.evaluate("window.premiumClicks") == 0
    assert adapter.get_access_consumption().consumed is False


@pytest.mark.asyncio(loop_scope="module")
async def test_premium_request_rejects_work_and_unknown_control_without_click(browser_page: Page) -> None:
    page = browser_page
    await page.set_content("""
      <div class="p-episode-purchase">
        <a class="c-btn-icon-primary c-btn-icon-primary--ticket">作品チケットで読む</a>
        <button class="purchase-unknown">コインで購入</button>
      </div>
      <script>
        window.workClicks=0; window.unknownClicks=0;
        document.querySelector('.c-btn-icon-primary--ticket').onclick=()=>window.workClicks++;
        document.querySelector('.purchase-unknown').onclick=()=>window.unknownClicks++;
      </script>
    """)
    adapter = MagapokeAdapter()
    with pytest.raises(UnsupportedAccessStrategyError):
        await adapter._enter_with_premium_ticket(page)
    assert await page.evaluate("window.workClicks") == 0
    assert await page.evaluate("window.unknownClicks") == 0
    assert adapter.get_access_consumption().consumed is False


@pytest.mark.asyncio(loop_scope="module")
async def test_premium_request_with_already_accessible_viewer_does_not_click(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = browser_page
    await page.set_content("""
      <div class="p-episode-purchase">
        <a class="c-btn-icon-primary c-btn-icon-primary--premium-ticket">プレミアムチケットで読む</a>
      </div>
      <canvas width="10" height="10"></canvas>
      <script>window.clicks=0;document.querySelector('a').onclick=()=>window.clicks++;</script>
    """)
    adapter = MagapokeAdapter()

    async def rows(_page):
        return [{"pageIndex": 0}]

    monkeypatch.setattr(adapter, "_canvas_rows", rows)
    await adapter._enter_with_premium_ticket(page)

    assert await page.evaluate("window.clicks") == 0
    assert adapter.get_access_consumption().consumed is False


@pytest.mark.asyncio(loop_scope="module")
async def test_duplicate_premium_controls_fail_without_click(browser_page: Page) -> None:
    page = browser_page
    await page.set_content("""
      <div class="p-episode-purchase">
        <a class="c-btn-icon-primary c-btn-icon-primary--premium-ticket">プレミアムチケットで読む</a>
        <a class="c-btn-icon-primary c-btn-icon-primary--premium-ticket">プレミアムチケットで読む</a>
        <dl class="p-episode-purchase__point">
          <dt class="p-episode-purchase__point-ttl">プレミアムチケット</dt>
          <dd class="p-episode-purchase__point-data">8枚</dd>
        </dl>
      </div>
      <script>window.clicks=0;document.querySelectorAll('a').forEach(x=>x.onclick=()=>window.clicks++);</script>
    """)
    adapter = MagapokeAdapter()
    with pytest.raises(UnsupportedAccessStrategyError):
        await adapter._enter_with_premium_ticket(page)
    assert await page.evaluate("window.clicks") == 0


@pytest.mark.asyncio(loop_scope="module")
async def test_premium_unknown_access_action_fails_without_click(browser_page: Page) -> None:
    page = browser_page
    await page.set_content("""
      <div class="p-episode-purchase">
        <a class="c-btn-icon-primary c-btn-icon-primary--premium-ticket">プレミアムチケットで読む</a>
        <button class="purchase-unknown">コインで購入</button>
        <dl class="p-episode-purchase__point">
          <dt class="p-episode-purchase__point-ttl">プレミアムチケット</dt>
          <dd class="p-episode-purchase__point-data">8枚</dd>
        </dl>
      </div>
      <script>window.clicks=0;document.querySelectorAll('a,button').forEach(x=>x.onclick=()=>window.clicks++);</script>
    """)
    adapter = MagapokeAdapter()
    with pytest.raises(UnsupportedAccessStrategyError):
        await adapter._enter_with_premium_ticket(page)
    assert await page.evaluate("window.clicks") == 0


@pytest.mark.asyncio(loop_scope="module")
async def test_already_visible_viewer_skips_work_ticket_entry(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = browser_page
    await page.set_content("""
      <div class="p-episode-purchase">
        <a class="c-btn-icon-primary c-btn-icon-primary--ticket">作品チケットで読む</a>
      </div>
      <canvas width="10" height="10"></canvas>
      <script>window.clicks=0; document.querySelector('a').onclick=()=>window.clicks++;</script>
    """)
    adapter = MagapokeAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    monkeypatch.setattr(adapter, "_canvas_rows", lambda _page: _ready_rows())
    async def ready(_page):
        return [{"pageIndex": 0}]
    async def no_wait(_page, **_kwargs):
        return None
    async def context(_page):
        return ContentContext(content_id="episode")
    monkeypatch.setattr(adapter, "_canvas_rows", ready)
    monkeypatch.setattr(adapter, "_wait_for_render_ready", no_wait)
    monkeypatch.setattr(adapter, "get_content_context", context)
    await adapter.initialize(page)
    assert await page.evaluate("window.clicks") == 0
    assert adapter.get_access_consumption().consumed is False
    debug = await adapter.collect_debug_metadata(page)
    assert debug["magapoke_entry_confirmation"]["preexisting_accessible"] is True
    assert debug["magapoke_entry_confirmation"]["ticket_click_attempted"] is False


async def _ready_rows():
    return [{"pageIndex": 0}]


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.parametrize(
    "markup",
    [
        (
            '<a class="c-btn-icon-primary c-btn-icon-primary--ticket">作品チケットで読む</a>'
            '<a class="c-btn-icon-primary c-btn-icon-primary--ticket">作品チケットで読む</a>'
        ),
        '<a class="c-btn-icon-primary c-btn-icon-primary--ticket c-btn-icon-primary--premium-ticket">作品チケットで読む</a>',
        '<button class="point-purchase">ポイントで購入</button>',
    ],
)
async def test_ambiguous_or_unknown_access_ui_fails_without_click(browser_page: Page, markup: str) -> None:
    page = browser_page
    await page.set_content(
        '<div class="p-episode-purchase">' + markup + '</div>'
        '<script>window.clicks=0; document.querySelectorAll("a,button").forEach(x => x.onclick=()=>window.clicks++);</script>'
    )
    adapter = MagapokeAdapter()
    with pytest.raises(UnsupportedAccessStrategyError):
        await adapter._enter_with_work_ticket(page)
    assert await page.evaluate("window.clicks") == 0


def _jpeg() -> bytes:
    image = Image.new("RGB", (10, 7))
    for y in range(7):
        for x in range(10):
            image.putpixel((x, y), ((x * 23) % 256, (y * 31) % 256, (x + y) * 17 % 256))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=95, subsampling=0)
    return buffer.getvalue()


@pytest.mark.parametrize("extension", ["jpg", "jpeg"])
@pytest.mark.asyncio(loop_scope="module")
async def test_magapoke_canvas_hook_tracks_jpeg_extensions(browser_page: Page, extension: str) -> None:
    page = browser_page
    adapter = MagapokeAdapter()
    await adapter.prepare_page(page)
    await page.goto("data:text/html,<html><body></body></html>")

    rows = await page.evaluate(
        """async extension => {
          document.body.innerHTML = `<div class="c-viewer__pages">
            <div class="c-viewer__pages-item"><div class="c-viewer__comic">
              <canvas width="1" height="1"></canvas>
            </div></div>
          </div>`;
          const source = new OffscreenCanvas(1, 1);
          source.getContext('2d').fillRect(0, 0, 1, 1);
          const image = new Image();
          image.src = URL.createObjectURL(await source.convertToBlob());
          await image.decode();
          Object.defineProperty(image, 'currentSrc', {
            configurable: true,
            value: `https://mgpk-cdn.magazinepocket.com/static/web_titles/695/episodes/244815/p1.${extension}`
          });
          const offscreen = new OffscreenCanvas(1, 1);
          offscreen.getContext('2d').drawImage(image, 0, 0);
          document.querySelector('canvas').getContext('2d').drawImage(offscreen, 0, 0);
          return window.__magapokeCaptureState.getCanvasSources();
        }""",
        extension,
    )

    assert len(rows) == 1
    assert rows[0]["sourcePath"].endswith(f"/244815/p1.{extension}")
    assert len(rows[0]["mapping"]) == 0
    assert rows[0]["base"] is not None
    assert rows[0]["visibleDraw"] is not None
