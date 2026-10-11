from __future__ import annotations

import asyncio
import io
import json
import threading
from urllib.parse import urlsplit

import pytest
from PIL import Image
from playwright.async_api import Page

from screenshot_crawler.core.errors import PageChangeTimeoutError, UnknownPageStateError
from screenshot_crawler.core.models import RunConfig
from screenshot_crawler.core.runner import CrawlerRunner
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.hanayume import adapter as hanayume_adapter_module
from screenshot_crawler.site_adapters.hanayume import discovery as hanayume_discovery_module
from screenshot_crawler.site_adapters.hanayume.adapter import HanayumeAdapter

WORK_ID = "1f9f5b0d4cd52"
EPISODE_ID = "8c6f15923caa0"
NOW_ID = "9202b052ad237"
EPISODE_URL = f"https://hanayume.com/episodes/{EPISODE_ID}"
WORK_URL = f"https://hanayume.com/series/{WORK_ID}"
FREE_LABEL = "\u7121\u6599"
NOW_FREE_LABEL = "\u4eca\u306a\u3089\u7121\u6599"


@pytest.fixture(autouse=True)
def _short_hanayume_initialization_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hanayume_discovery_module, "SERIES_AUTH_HYDRATION_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(hanayume_adapter_module, "VIEWER_COUNTER_READY_TIMEOUT_MS", 400)
    monkeypatch.setattr(hanayume_adapter_module, "INITIAL_CANVAS_QUIET_MS", 60)
    monkeypatch.setattr(hanayume_adapter_module, "INITIAL_CANVAS_POLL_INTERVAL_MS", 20)
    monkeypatch.setattr(hanayume_adapter_module, "INITIAL_CANVAS_SETTLE_TIMEOUT_MS", 800)


def _row(episode_id: str, label: str) -> str:
    return f"""<div class="series-eplist-item" data-e2e="eli">
      <a class="series-eplist-item-link" href="/episodes/{episode_id}">episode</a>
      <span class="series-eplist-item-access-text">{label}</span>
    </div>"""


def _preview_rows(count: int = 4) -> list[tuple[str, str]]:
    return [(f"{index:013x}", FREE_LABEL) for index in range(700, 700 + count)]


def _series_auth_header(*, authenticated: bool = False) -> str:
    if authenticated:
        return """<header id="xHeader" class="h"><nav>
          <a class="h-main-nav-link mode-user" data-e2e="hUserMenu" href="#account">
            <svg data-e2e="hUserIcon"></svg></a>
          <div class="h-usermenu"><button data-e2e="signoutBtn">Sign out</button></div>
        </nav></header>"""
    return '<header id="xHeader" class="h"></header>'


def _listing(*, selected: bool, target_label: str = "\u7121\u6599") -> str:
    class_name = "series-sort-link mode-current" if selected else "series-sort-link"
    rows = (
        _row(EPISODE_ID, target_label)
        + _row(NOW_ID, "\u4eca\u306a\u3089\u7121\u6599")
    )
    return f"""<div class="series mode-series-top series-safe-filter-target" data-e2e="pageSeries">
      <div class="series-eplist-wrap">
      <a class="{class_name}" href="{WORK_URL if selected else WORK_URL + '/1'}">1-2</a>
      <div class="series-eplist-main">
        <div class="series-eplist" data-e2e="epList">
          <div class="series-eplist-default has-store-item mode-last">{rows}</div>
        </div>
        <div class="series-eplist mode-user" data-e2e="epListUser">
          <div class="series-eplist-default has-store-item mode-last">{rows}</div>
        </div>
      </div></div></div>"""


def _episode_html(
    *, current: int = 3, label: str = "無料", user_target_label: str | None = None,
    episode_rows: list[tuple[str, str]] | None = None,
    episode_history_rows: list[tuple[str, str]] | None = None,
    episode_unknown_rows: list[tuple[str, str]] | None = None,
    counter_delay_ms: int = 0, counter_never: bool = False,
    counter_duplicate: bool = False, counter_malformed: bool = False,
    top_empty: bool = False, top_empty_seek_locked: bool = False,
    top_empty_first_marker_missing: bool = False, top_empty_interior_empty: bool = False,
    padded_counter: bool = False,
) -> str:
    public_values = episode_rows if episode_rows is not None else [
        (EPISODE_ID, label),
        (NOW_ID, NOW_FREE_LABEL),
    ]
    history_values = episode_history_rows if episode_history_rows is not None else (
        [(EPISODE_ID, user_target_label)] if user_target_label is not None else []
    )
    public_rows_html = "".join(_row(episode_id, row_label) for episode_id, row_label in public_values)
    history_rows_html = "".join(_row(episode_id, row_label) for episode_id, row_label in history_values)
    unknown_rows_html = "".join(
        _row(episode_id, row_label) for episode_id, row_label in episode_unknown_rows or []
    )
    return f"""<!doctype html><html><body>
      <header id="xHeader"><a class="ep-h-main-h-series" href="{WORK_URL}">work</a></header>
      <div class="ep-main series-safe-filter-target" data-e2e="pageEpisode">
      <div class="series mode-ep"><div class="series-eplist-wrap">
        <div class="series-eplist-main"><div class="series-eplist" data-e2e="epList">
          <div class="series-eplist-default has-store-item mode-last">
          {public_rows_html}
          </div></div>
        <div class="series-eplist mode-user" data-e2e="epListUser">
          <div class="series-eplist-default has-store-item mode-last">
          {history_rows_html}
          </div></div>
        </div>
      </div></div></div>
      <div class="series-eplist-extra">{unknown_rows_html}</div>
      <div id="comici-viewer" class="-cv mode-spread">
        <div class="-cv-f-page-current"></div>
        {'<div class="-cv-f-page-current"></div>' if counter_duplicate else ''}
        <div class="-cv-f-page-total">{'' if counter_delay_ms or counter_never else '9'}</div>
        <input id="xCVSeekBar" type="range" min="1" max="9" step="2" value="9">
        <div id="xCVPages"></div>
      </div>
      <script>
        (() => {{
          const total = 9;
          const lastSlot = total - {int(padded_counter)};
          const topEmpty = {json.dumps(top_empty)};
          const bodyStart = topEmpty ? 2 : 1;
          const bodyEnd = lastSlot - 5;
          const bodyTotal = bodyEnd - bodyStart + 1;
          const root = document.querySelector('#comici-viewer');
          const pageRoot = document.querySelector('#xCVPages');
          const seek = document.querySelector('#xCVSeekBar');
          const currentText = document.querySelector('.-cv-f-page-current');
          const wrappers = [];
          for (let i = 0; i <= lastSlot; i++) {{
            const node = document.createElement('div');
            node.className = '-cv-page';
            node.style.cssText = 'position:absolute;top:0;width:100px;height:100px;left:-3000px';
            pageRoot.append(node);
            wrappers.push(node);
          }}
          const baseCanvas = () => {{
            const canvas = document.createElement('canvas');
            canvas.width = 5; canvas.height = 7;
            canvas.style.cssText = 'width:5px;height:7px';
            return canvas;
          }};
          const reusedCanvas = baseCanvas();
          const secondCanvas = baseCanvas();
          const preloaded = new WeakSet();
          const sourceFor = index => {{
            const canvas = document.createElement('canvas');
            canvas.width = 960; canvas.height = 1540;
            const context = canvas.getContext('2d');
            context.fillStyle = `rgb(${{index * 20}},40,60)`;
            context.fillRect(0, 0, canvas.width, canvas.height);
            return canvas;
          }};
          const classFor = index => {{
            if (index === 0) return '-cv-page mode-empty mode-pr mode-top-pr';
            if (topEmpty && index === 1) return '-cv-page mode-empty';
            if (index === lastSlot - 4) return '-cv-page mode-ci';
            if (index === lastSlot - 3 || index === lastSlot - 2) return '-cv-page mode-empty mode-pr';
            if (index === lastSlot - 1) return '-cv-page mode-good';
            if (index === lastSlot) return '-cv-page mode-last';
            return '-cv-page';
          }};
          function render(current, terminal = false) {{
            currentText.textContent = {json.dumps('not-a-number' if counter_malformed else None)} ?? String(current);
            document.querySelector('.-cv-f-page-total').textContent = String(total);
            seek.value = String(total - (current - 1));
            root.classList.toggle('mode-last-page', terminal);
            root.classList.toggle('mode-has-top-emptypage', topEmpty);
            root.classList.toggle('mode-first-page', topEmpty && current === 1 &&
              !{json.dumps(top_empty_first_marker_missing)});
            const visible = current === 1 ? [0, 1] : [current - 1, current];
            for (let i = 0; i <= lastSlot; i++) {{
              const node = wrappers[i];
              node.replaceChildren();
              node.className = classFor(i);
              node.style.left = '-3000px';
            }}
            if (current === 1) wrappers[0].style.left = '200px';
            if (topEmpty && current === 1) wrappers[1].style.left = '0px';
            visible.forEach((index, side) => {{
              if (index > lastSlot) return;
              wrappers[index].style.left = `${{side * 100}}px`;
              if (index < bodyStart || index > bodyEnd) return;
              if (topEmpty && {json.dumps(top_empty_interior_empty)} && index === bodyStart) {{
                wrappers[index].className = '-cv-page mode-empty';
                return;
              }}
              const canvas = index % 2 === 1 ? reusedCanvas : secondCanvas;
              const context = canvas.getContext('2d');
              const holder = document.createElement('div');
              holder.className = '-cv-page-canvas';
              holder.append(canvas);
              wrappers[index].append(holder);
              if (!(index === 2 && current === 3 && preloaded.has(canvas))) {{
                const source = sourceFor(index);
                context.drawImage(source, 0, 0, 960, 1540, 0, 0, canvas.width, canvas.height);
                source.getContext('2d').clearRect(0, 0, source.width, source.height);
              }}
              wrappers[index].classList.add('mode-loaded', 'mode-rendered');
            }});
            if (current === 1) {{
              const wrapper = wrappers[2];
              const holder = document.createElement('div');
              holder.className = '-cv-page-canvas';
              holder.append(secondCanvas);
              wrapper.append(holder);
              const source = sourceFor(2);
              secondCanvas.getContext('2d').drawImage(source, 0, 0, 960, 1540, 0, 0, secondCanvas.width, secondCanvas.height);
              source.getContext('2d').clearRect(0, 0, source.width, source.height);
              preloaded.add(secondCanvas);
              wrapper.classList.add('mode-loaded', 'mode-req-render');
            }}
            if (current === 3 && !topEmpty) {{
              const previous = wrappers[1];
              previous.style.left = `${{innerWidth - 15.3333}}px`;
              const offscreen = baseCanvas();
              offscreen.style.cssText = 'position:absolute;left:110px;top:0;width:5px;height:7px';
              const holder = document.createElement('div');
              holder.className = '-cv-page-canvas';
              holder.append(offscreen);
              previous.append(holder);
              previous.classList.add('mode-loaded', 'mode-rendered');
            }}
            if (current === 1) wrappers[2].classList.add('mode-loaded');
          }}
          seek.addEventListener('input', () => {{
            if (topEmpty && {json.dumps(top_empty_seek_locked)} && currentText.textContent === '1') return;
            render(total - Number(seek.value) + 1);
          }});
          seek.addEventListener('change', () => {{
            if (topEmpty && {json.dumps(top_empty_seek_locked)} && currentText.textContent === '1') return;
            render(total - Number(seek.value) + 1);
          }});
          seek.addEventListener('keydown', event => {{
            if (event.key === 'End') {{ event.preventDefault(); render(1); }}
            if (event.key === 'Home') {{ event.preventDefault(); render(total, true); }}
          }});
          if (!{json.dumps(counter_never)}) {{
            if ({counter_delay_ms} > 0) setTimeout(() => render({current}), {counter_delay_ms});
            else render({current});
          }}
        }})();
      </script>
    </body></html>"""


async def _install_mock_site(
    page: Page,
    *,
    authenticated: bool = False,
    return_episode_label: str = "無料",
    user_target_label: str | None = None,
    episode_rows: list[tuple[str, str]] | None = None,
    resume_current: int = 3,
    counter_delay_ms: int = 0,
    counter_never: bool = False,
    counter_duplicate: bool = False,
    counter_malformed: bool = False,
    top_empty: bool = False,
    top_empty_seek_locked: bool = False,
    top_empty_first_marker_missing: bool = False,
    top_empty_interior_empty: bool = False,
    padded_counter: bool = False,
) -> dict[str, object]:
    state: dict[str, object] = {"episode_visits": 0, "paths": []}

    async def route_handler(route) -> None:
        path = urlsplit(route.request.url).path
        state["paths"].append(path)  # type: ignore[union-attr]
        if path == f"/episodes/{EPISODE_ID}":
            visits = int(state["episode_visits"]) + 1
            state["episode_visits"] = visits
            label = "無料" if visits == 1 else return_episode_label
            body = _episode_html(
                current=resume_current, label=label, user_target_label=user_target_label,
                episode_rows=episode_rows,
                counter_delay_ms=counter_delay_ms, counter_never=counter_never,
                counter_duplicate=counter_duplicate, counter_malformed=counter_malformed,
                top_empty=top_empty, top_empty_seek_locked=top_empty_seek_locked,
                top_empty_first_marker_missing=top_empty_first_marker_missing,
                top_empty_interior_empty=top_empty_interior_empty,
                padded_counter=padded_counter,
            )
        elif path == f"/series/{WORK_ID}":
            body = (
                "<!doctype html><html><body>"
                + _series_auth_header(authenticated=authenticated)
                + '<div class="series mode-series-top series-safe-filter-target" data-e2e="pageSeries">'
                + '<div class="series-eplist-wrap">'
                + f'<a class="series-sort-link" href="{WORK_URL}/1">1-2</a>'
                + '<div class="series-eplist-main">'
                + '<div class="series-eplist" data-e2e="epList"></div>'
                + '<div class="series-eplist mode-loading mode-user" data-e2e="epListUser"></div>'
                + '</div></div></div>'
                + "</body></html>"
            )
        elif path == f"/series/{WORK_ID}/1":
            body = _listing(selected=True)
        else:
            await route.fulfill(status=404, body="")
            return
        await route.fulfill(status=200, content_type="text/html; charset=utf-8", body=body)

    await page.route("https://hanayume.com/**", route_handler)
    return state


def _search_listing(
    *,
    selected_page: int | None,
    rows: list[tuple[str, str]],
    drift: bool = False,
    history_conflict: bool = False,
) -> str:
    ranges = ((1, 1, 30), (2, 31, 32 if not drift else 33))
    links = []
    for number, start, end in ranges:
        selected = selected_page == number
        href = WORK_URL if selected else f"{WORK_URL}/{number}"
        current = " mode-current" if selected else ""
        links.append(
            f'<a class="series-sort-link{current}" href="{href}">{start}-{end}</a>'
        )
    public_rows = "".join(_row(episode_id, label) for episode_id, label in rows)
    history_values = [
        (episode_id, NOW_FREE_LABEL if history_conflict and episode_id == EPISODE_ID else label)
        for episode_id, label in rows
    ]
    history_rows = "".join(_row(episode_id, label) for episode_id, label in history_values)
    return (
        _series_auth_header()
        + '<div class="series mode-series-top series-safe-filter-target" data-e2e="pageSeries">'
        + '<div class="series-eplist-wrap">'
        + "".join(links)
        + '<div class="series-eplist-main"><div class="series-eplist" data-e2e="epList">'
        + public_rows
        + '</div><div class="series-eplist mode-user" data-e2e="epListUser">'
        + history_rows
        + "</div></div></div></div>"
    )


async def _install_preflight_site(
    page: Page,
    *,
    bare_rows: list[tuple[str, str]],
    range_rows: dict[int, list[tuple[str, str]]],
    drift_first_range: bool = False,
    history_conflict: bool = False,
    entered_episode_id: str = EPISODE_ID,
    entered_episode_href: str | None = None,
    episode_rows: list[tuple[str, str]] | None = None,
    episode_history_rows: list[tuple[str, str]] | None = None,
    episode_unknown_rows: list[tuple[str, str]] | None = None,
) -> dict[str, object]:
    state: dict[str, object] = {"episode_visits": 0, "paths": []}
    defaults = {
        1: [(f"{index:013x}", FREE_LABEL) for index in range(100, 130)],
        2: [(f"{index:013x}", FREE_LABEL) for index in range(130, 132)],
    }
    defaults.update(range_rows)

    async def route_handler(route) -> None:
        path = urlsplit(route.request.url).path
        paths = state["paths"]
        assert isinstance(paths, list)
        paths.append(path)
        if path == f"/episodes/{EPISODE_ID}":
            visits = int(state["episode_visits"]) + 1
            state["episode_visits"] = visits
            body = _episode_html(
                episode_rows=episode_rows,
                episode_history_rows=episode_history_rows,
                episode_unknown_rows=episode_unknown_rows,
            )
            if visits > 1 and entered_episode_href is not None:
                body = body.replace(
                    f'href="/episodes/{EPISODE_ID}"',
                    f'href="{entered_episode_href}"',
                    1,
                )
            elif visits > 1 and entered_episode_id != EPISODE_ID:
                body = body.replace(
                    f'href="/episodes/{EPISODE_ID}"',
                    f'href="/episodes/{entered_episode_id}"',
                    1,
                )
        elif path == f"/series/{WORK_ID}":
            body = _search_listing(
                selected_page=None, rows=bare_rows, history_conflict=history_conflict
            )
        elif path == f"/series/{WORK_ID}/1":
            body = _search_listing(
                selected_page=1,
                rows=defaults[1],
                drift=drift_first_range,
                history_conflict=history_conflict,
            )
        elif path == f"/series/{WORK_ID}/2":
            body = _search_listing(
                selected_page=2, rows=defaults[2], history_conflict=history_conflict
            )
        else:
            await route.fulfill(status=404, body="")
            return
        await route.fulfill(status=200, content_type="text/html; charset=utf-8", body=body)

    await page.route("https://hanayume.com/**", route_handler)
    return state


async def _initialized(page: Page, *, adapter: HanayumeAdapter | None = None) -> HanayumeAdapter:
    instance = adapter or HanayumeAdapter()
    url = instance.resolve_initial_navigation_url(EPISODE_URL)
    await instance.prepare_page(page)
    response = await page.goto(url, wait_until="domcontentloaded")
    assert response is not None and response.status == 200
    await instance.initialize(page)
    return instance


async def _body_state(page: Page, adapter: HanayumeAdapter) -> None:
    assert await adapter.detect_state(page) is PageState.CONTENT


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.parametrize("top_empty", [False, True])
@pytest.mark.parametrize("continuous", [False, True], ids=("late-reset", "never-quiet"))
async def test_hanayume_initial_canvas_wait_restarts_after_same_pixel_reset(
    browser_page: Page, monkeypatch: pytest.MonkeyPatch,
    top_empty: bool, continuous: bool,
) -> None:
    await _install_mock_site(browser_page, resume_current=1, top_empty=top_empty)
    monkeypatch.setattr(hanayume_adapter_module, "INITIAL_CANVAS_QUIET_MS", 160)
    monkeypatch.setattr(hanayume_adapter_module, "INITIAL_CANVAS_SETTLE_TIMEOUT_MS", 450)
    adapter = HanayumeAdapter()
    original_observe = adapter._observe
    scheduled = False

    async def observe(page, *, include_png=False, stability_slots=()):
        nonlocal scheduled
        result = await original_observe(
            page, include_png=include_png, stability_slots=stability_slots,
        )
        if stability_slots and not scheduled:
            scheduled = True
            await page.evaluate(
                """({slots, continuous}) => {
                  const redraw = () => {
                    for (const slot of slots) {
                      const canvas = document.querySelector('#xCVPages').children[slot].querySelector('canvas');
                      const source = document.createElement('canvas');
                      source.width = 960; source.height = 1540;
                      const ctx = source.getContext('2d');
                      ctx.fillStyle = `rgb(${slot * 20},40,60)`;
                      ctx.fillRect(0, 0, 960, 1540);
                      canvas.width = canvas.width; canvas.height = canvas.height;
                      canvas.getContext('2d').drawImage(source, 0, 0, 960, 1540, 0, 0, canvas.width, canvas.height);
                    }
                    window.lastInitialResetAt = performance.now();
                  };
                  window.initialResetTimer = continuous ? setInterval(redraw, 40) : setTimeout(redraw, 60);
                }""",
                {"slots": list(stability_slots), "continuous": continuous},
            )
        return result

    monkeypatch.setattr(adapter, "_observe", observe)
    try:
        if continuous:
            with pytest.raises(PageChangeTimeoutError, match="did not"):
                await _initialized(browser_page, adapter=adapter)
            debug = await adapter.collect_debug_metadata(browser_page)
            assert debug["initial_canvas_settle"]["status"] == "timeout"
            assert adapter._captured_slots == []
        else:
            await _initialized(browser_page, adapter=adapter)
            elapsed = await browser_page.evaluate("performance.now() - window.lastInitialResetAt")
            assert elapsed >= 160
            debug = await adapter.collect_debug_metadata(browser_page)
            assert debug["initial_canvas_settle"]["status"] == "settled"
            assert debug["initial_canvas_settle"]["canvas_tracking"] is True
            assert await adapter.detect_state(browser_page) is PageState.CONTENT
            captures = await adapter.capture_page(browser_page)
            assert len(captures) == (2 if top_empty else 1)
            assert all(item.mime_type == "image/webp" for item in captures)
    finally:
        await browser_page.evaluate("clearInterval(window.initialResetTimer)")


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_initial_canvas_wait_preserves_observer_missing_rendered_fallback(
    browser_page: Page, monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _install_mock_site(browser_page, resume_current=1)
    adapter = HanayumeAdapter()

    async def unavailable_observer(_page):
        pass

    monkeypatch.setattr(adapter, "prepare_page", unavailable_observer)
    await _initialized(browser_page, adapter=adapter)
    debug = await adapter.collect_debug_metadata(browser_page)
    assert debug["initial_canvas_settle"]["status"] == "settled"
    assert debug["initial_canvas_settle"]["canvas_tracking"] is False
    assert debug["initial_canvas_settle"]["elapsed_ms"] >= 60
    captures = await adapter.capture_page(browser_page)
    assert len(captures) == 1 and captures[0].mime_type == "image/png"


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_local_viewer_rewinds_resume_captures_reused_canvas_spreads_and_ends(
    browser_page: Page,
) -> None:
    await _install_mock_site(browser_page, resume_current=3)
    adapter = await _initialized(browser_page)
    await _body_state(browser_page, adapter)

    first_identity = await adapter.get_content_identity(browser_page)
    captures = await adapter.capture_page(browser_page)
    assert captures is not None and len(captures) == 1
    first = Image.open(io.BytesIO(captures[0].data)).convert("RGB")
    assert first.size == (960, 1540)
    assert captures[0].mime_type == "image/webp"
    assert first.getpixel((0, 0)) == (20, 40, 60)
    assert first_identity.page_id == "1"

    await adapter.go_next(browser_page)
    await adapter.wait_for_change(browser_page, first_identity)
    await _body_state(browser_page, adapter)
    spread_identity = await adapter.get_content_identity(browser_page)
    spread = await adapter.capture_page(browser_page)
    assert spread is not None and len(spread) == 2
    assert all(item.mime_type == "image/webp" and (item.width, item.height) == (960, 1540) for item in spread), adapter._capture_diagnostics
    assert [Image.open(io.BytesIO(item.data)).convert("RGB").getpixel((0, 0)) for item in spread] == [
        (40, 40, 60),
        (60, 40, 60),
    ]
    assert spread_identity.page_id == "2,3"

    await adapter.go_next(browser_page)
    await adapter.wait_for_change(browser_page, spread_identity)
    await _body_state(browser_page, adapter)
    final_identity = await adapter.get_content_identity(browser_page)
    final = await adapter.capture_page(browser_page)
    assert final is not None and len(final) == 1
    assert (final[0].width, final[0].height) == (960, 1540)
    assert Image.open(io.BytesIO(final[0].data)).convert("RGB").getpixel((0, 0)) == (80, 40, 60)

    await adapter.go_next(browser_page)
    await adapter.wait_for_change(browser_page, final_identity)
    assert await adapter.detect_state(browser_page) is PageState.END


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_top_empty_lead_in_captures_only_physical_body_slots_and_ends(
    browser_page: Page,
) -> None:
    await _install_mock_site(browser_page, resume_current=3, top_empty=True)
    adapter = await _initialized(browser_page)

    observation = await adapter._observe(browser_page)
    assert observation.current == 3
    assert observation.has_top_empty_page is True
    assert observation.body_slots == (2, 3, 4)
    assert observation.body_total == 3
    assert observation.active_slots == observation.ready_slots == (2, 3)
    assert adapter._captured_slots == []

    await _body_state(browser_page, adapter)
    first_identity = await adapter.get_content_identity(browser_page)
    first = await adapter.capture_page(browser_page)
    assert first is not None and len(first) == 2
    assert first_identity.page_id == "2,3" and first_identity.page_number == 2
    assert all(item.mime_type == "image/webp" for item in first)
    assert [Image.open(io.BytesIO(item.data)).convert("RGB").getpixel((0, 0)) for item in first] == [
        (40, 40, 60), (60, 40, 60)
    ]

    await adapter.go_next(browser_page)
    await adapter.wait_for_change(browser_page, first_identity)
    await _body_state(browser_page, adapter)
    final_identity = await adapter.get_content_identity(browser_page)
    assert final_identity.page_id == "4" and final_identity.page_number == 4
    final = await adapter.capture_page(browser_page)
    assert final is not None and len(final) == 1
    assert Image.open(io.BytesIO(final[0].data)).convert("RGB").getpixel((0, 0)) == (80, 40, 60)
    assert adapter._captured_slots == [2, 3, 4]

    await adapter.go_next(browser_page)
    await adapter.wait_for_change(browser_page, final_identity)
    assert await adapter.detect_state(browser_page) is PageState.END


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.parametrize(
    ("fixture_kwargs", "error_type", "message"),
    [
        ({"top_empty_first_marker_missing": True}, PageChangeTimeoutError, "did not settle at its observed lead-in"),
        ({"top_empty_seek_locked": True}, UnknownPageStateError, "counter and public seek control disagree"),
        ({"top_empty_interior_empty": True}, UnknownPageStateError, "unknown state class"),
    ],
)
async def test_hanayume_top_empty_lead_in_rejects_marker_seek_or_interior_drift(
    browser_page: Page, fixture_kwargs: dict[str, bool], error_type, message: str
) -> None:
    resume_current = 1 if fixture_kwargs.get("top_empty_seek_locked") else 3
    await _install_mock_site(
        browser_page, resume_current=resume_current, top_empty=True, **fixture_kwargs
    )
    adapter = HanayumeAdapter()
    adapter.page_change_timeout_ms = 800
    url = adapter.resolve_initial_navigation_url(EPISODE_URL)
    await adapter.prepare_page(browser_page)
    response = await browser_page.goto(url, wait_until="domcontentloaded")
    assert response is not None and response.status == 200
    with pytest.raises(error_type, match=message):
        await adapter.initialize(browser_page)
    assert adapter._captured_slots == []


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_top_empty_flag_drift_during_native_encoding_discards_proof(
    browser_page: Page, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _install_mock_site(browser_page, resume_current=3, top_empty=True)
    adapter = await _initialized(browser_page)
    entered = threading.Event()
    continue_encoding = threading.Event()
    original_encoder = hanayume_adapter_module.encode_native_webp

    def delayed_encoder(images):
        entered.set()
        if not continue_encoding.wait(timeout=3):
            raise TimeoutError("synthetic encoder wait timed out")
        return original_encoder(images)

    monkeypatch.setattr(hanayume_adapter_module, "encode_native_webp", delayed_encoder)
    task = asyncio.create_task(adapter.capture_page(browser_page))
    assert await asyncio.to_thread(entered.wait, 3)
    await browser_page.locator("#comici-viewer").evaluate(
        "viewer => viewer.classList.remove('mode-has-top-emptypage')"
    )
    continue_encoding.set()

    with pytest.raises(UnknownPageStateError, match="changed after native image encoding"):
        await task
    assert adapter._captured_slots == []
    debug = await adapter.collect_debug_metadata(browser_page)
    assert debug["capture"]["verification"]["reason"] == "body_layout_changed"
    status = await browser_page.evaluate("() => window.__hanayumeNativeCapture.status()")
    assert status["proofCount"] == 0


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_top_empty_flag_drift_before_capture_fails_closed(browser_page: Page) -> None:
    await _install_mock_site(browser_page, resume_current=3, top_empty=True)
    adapter = await _initialized(browser_page)
    await browser_page.locator("#comici-viewer").evaluate(
        "viewer => viewer.classList.remove('mode-has-top-emptypage')"
    )
    with pytest.raises(UnknownPageStateError):
        await adapter.detect_state(browser_page)


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_top_empty_missing_spread_half_and_premature_end_fail_closed(
    browser_page: Page,
) -> None:
    await _install_mock_site(browser_page, resume_current=3, top_empty=True)
    adapter = await _initialized(browser_page)
    await browser_page.locator("#xCVPages > .-cv-page:nth-child(3) .-cv-page-canvas").evaluate(
        "node => node.remove()"
    )
    assert await adapter.detect_state(browser_page) is PageState.LOADING
    with pytest.raises(UnknownPageStateError):
        await adapter.capture_page(browser_page)

    await browser_page.locator("#xCVSeekBar").focus()
    await browser_page.locator("#xCVSeekBar").press("Home")
    with pytest.raises(UnknownPageStateError, match="END before all body slots"):
        await adapter.detect_state(browser_page)


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_initialize_waits_for_delayed_known_viewer_counter(
    browser_page: Page,
) -> None:
    state = await _install_mock_site(browser_page, counter_delay_ms=180)

    adapter = await _initialized(browser_page)

    observation = await adapter._observe(browser_page)
    assert observation.current == 1 and observation.total == 9
    assert observation.ready_slots == (1,)
    assert state["paths"] == [
        f"/episodes/{EPISODE_ID}",
        f"/series/{WORK_ID}",
        f"/series/{WORK_ID}/1",
        f"/episodes/{EPISODE_ID}",
    ]


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_initialize_fails_closed_when_viewer_counter_never_appears(
    browser_page: Page,
) -> None:
    state = await _install_mock_site(browser_page, counter_never=True)

    adapter = HanayumeAdapter()
    adapter.resolve_initial_navigation_url(EPISODE_URL)
    response = await browser_page.goto(EPISODE_URL, wait_until="domcontentloaded")
    assert response is not None and response.status == 200
    started = asyncio.get_running_loop().time()

    with pytest.raises(UnknownPageStateError, match="counter did not become ready"):
        await adapter.initialize(browser_page)

    elapsed = asyncio.get_running_loop().time() - started
    assert 0.25 <= elapsed < 1.5
    assert state["paths"] == [
        f"/episodes/{EPISODE_ID}",
        f"/series/{WORK_ID}",
        f"/series/{WORK_ID}/1",
        f"/episodes/{EPISODE_ID}",
    ]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [("counter_duplicate", "counter is missing"), ("counter_malformed", "counter is malformed")],
)
@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_initialize_does_not_wait_past_duplicate_or_malformed_counter(
    browser_page: Page, mutation: str, message: str,
) -> None:
    state = await _install_mock_site(browser_page, **{mutation: True})
    adapter = HanayumeAdapter()
    adapter.resolve_initial_navigation_url(EPISODE_URL)
    response = await browser_page.goto(EPISODE_URL, wait_until="domcontentloaded")
    assert response is not None and response.status == 200
    started = asyncio.get_running_loop().time()

    with pytest.raises(UnknownPageStateError, match=message):
        await adapter.initialize(browser_page)

    assert asyncio.get_running_loop().time() - started < 0.4
    assert state["paths"] == [
        f"/episodes/{EPISODE_ID}",
        f"/series/{WORK_ID}",
        f"/series/{WORK_ID}/1",
        f"/episodes/{EPISODE_ID}",
    ]


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.parametrize(
    "mutation",
    [
        "write", "same-width-attribute", "same-height-attribute", "clip",
        "hook-tamper", "instance-write-tamper", "observer-error", "replace",
        "get-transform-tamper", "set-transform-tamper", "context-attrs-tamper",
        "paint-descriptor-tamper",
    ],
)
async def test_hanayume_unsafe_or_reset_target_uses_only_clean_rendered_png_fallback(
    browser_page: Page, mutation: str
) -> None:
    await _install_mock_site(browser_page)
    adapter = await _initialized(browser_page)
    await _body_state(browser_page, adapter)
    await browser_page.locator("#xCVPages > .-cv-page:nth-child(2) canvas").evaluate(
        """(canvas, mutation) => {
          if (mutation === 'write') {
            canvas.getContext('2d').fillRect(0, 0, canvas.width, canvas.height);
          } else if (mutation === 'same-width-attribute') {
            canvas.setAttribute('width', String(canvas.width));
          } else if (mutation === 'same-height-attribute') {
            canvas.setAttribute('height', String(canvas.height));
          } else if (mutation === 'clip') {
            const context = canvas.getContext('2d');
            context.save(); context.beginPath(); context.rect(0, 0, 3, 3); context.clip(); context.restore();
          } else if (mutation === 'replace') {
            canvas.replaceWith(canvas.cloneNode());
          } else if (mutation === 'instance-write-tamper') {
            const context = canvas.getContext('2d');
            const clearRect = CanvasRenderingContext2D.prototype.clearRect;
            context.clearRect = function(...args) { return clearRect.apply(this, args); };
          } else if (mutation === 'observer-error') {
            Object.defineProperty(canvas, 'closest', {configurable:true, value() { throw new Error('observer'); }});
            const source = document.createElement('canvas');
            source.width = 960; source.height = 1540;
            const sourceContext = source.getContext('2d');
            sourceContext.fillStyle = 'rgb(111,122,133)';
            sourceContext.fillRect(0, 0, source.width, source.height);
            canvas.getContext('2d').drawImage(source, 0, 0, 960, 1540, 0, 0, canvas.width, canvas.height);
          } else if (mutation === 'get-transform-tamper') {
            const prototype = CanvasRenderingContext2D.prototype;
            const descriptor = Object.getOwnPropertyDescriptor(prototype, 'getTransform');
            const setTransform = Object.getOwnPropertyDescriptor(prototype, 'setTransform').value;
            setTransform.call(canvas.getContext('2d'), 2, 0, 0, 1, 0, 0);
            Object.defineProperty(prototype, 'getTransform', {
              ...descriptor, value() { return new DOMMatrix([1, 0, 0, 1, 0, 0]); }
            });
          } else if (mutation === 'set-transform-tamper') {
            const prototype = CanvasRenderingContext2D.prototype;
            const descriptor = Object.getOwnPropertyDescriptor(prototype, 'setTransform');
            const original = descriptor.value;
            Object.defineProperty(prototype, 'setTransform', {
              ...descriptor, value(...args) { return original.apply(this, args); }
            });
          } else if (mutation === 'context-attrs-tamper') {
            const prototype = CanvasRenderingContext2D.prototype;
            const descriptor = Object.getOwnPropertyDescriptor(prototype, 'getContextAttributes');
            const original = descriptor.value;
            Object.defineProperty(prototype, 'getContextAttributes', {
              ...descriptor, value(...args) { return original.apply(this, args); }
            });
          } else if (mutation === 'paint-descriptor-tamper') {
            const prototype = CanvasRenderingContext2D.prototype;
            const descriptor = Object.getOwnPropertyDescriptor(prototype, 'shadowColor');
            Object.defineProperty(prototype, 'shadowColor', {
              ...descriptor, get() { return descriptor.get.call(this); }
            });
          } else {
            const prototype = CanvasRenderingContext2D.prototype;
            const drawImage = prototype.drawImage;
            prototype.drawImage = function(...args) { return drawImage.apply(this, args); };
          }
        }""",
        mutation,
    )

    captures = await adapter.capture_page(browser_page)

    assert captures is not None and len(captures) == 1
    assert captures[0].mime_type == "image/png"
    assert (captures[0].width, captures[0].height) == (5, 7)
    assert adapter._capture_diagnostics["mode"] == "rendered_body_canvas_png"
    assert adapter._capture_diagnostics["reason"] in {
        "native_candidate_missing_or_stale",
        "observer_integrity_lost",
    }
    if mutation == "observer-error":
        assert Image.open(io.BytesIO(captures[0].data)).convert("RGB").getpixel((0, 0)) == (111, 122, 133)


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_spread_uses_rendered_png_for_both_sides_when_one_native_candidate_is_unavailable(
    browser_page: Page,
) -> None:
    await _install_mock_site(browser_page)
    adapter = await _initialized(browser_page)
    first = await adapter.get_content_identity(browser_page)
    assert await adapter.capture_page(browser_page)
    await adapter.go_next(browser_page)
    await adapter.wait_for_change(browser_page, first)
    assert await adapter.detect_state(browser_page) is PageState.CONTENT
    await browser_page.locator("#xCVPages > .-cv-page:nth-child(3) canvas").evaluate(
        "canvas => canvas.getContext('2d').fillRect(0, 0, canvas.width, canvas.height)"
    )

    spread = await adapter.capture_page(browser_page)

    assert spread is not None and len(spread) == 2
    assert all(item.mime_type == "image/png" for item in spread)
    assert [(item.width, item.height) for item in spread] == [(5, 7), (5, 7)]
    assert adapter._capture_diagnostics["mode"] == "rendered_body_canvas_png"


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_native_replay_exception_falls_back_to_rendered_spread(
    browser_page: Page, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _install_mock_site(browser_page)
    adapter = await _initialized(browser_page)
    await _body_state(browser_page, adapter)
    monkeypatch.setattr(
        hanayume_adapter_module,
        "COLLECT_CAPTURE_SCRIPT",
        r"""args => {
          const descriptor = Object.getOwnPropertyDescriptor(Document.prototype, 'createElement');
          const original = descriptor.value;
          Object.defineProperty(Document.prototype, 'createElement', {
            ...descriptor,
            value(tag, ...rest) {
              if (String(tag).toLowerCase() === 'canvas') throw new Error('synthetic replay failure');
              return Reflect.apply(original, this, [tag, ...rest]);
            }
          });
          try { return window.__hanayumeNativeCapture.collect(args); }
          finally { Object.defineProperty(Document.prototype, 'createElement', descriptor); }
        }""",
    )

    captures = await adapter.capture_page(browser_page)

    assert captures is not None and len(captures) == 1
    assert captures[0].mime_type == "image/png"
    assert (captures[0].width, captures[0].height) == (5, 7)
    assert adapter._capture_diagnostics["mode"] == "rendered_body_canvas_png"
    assert adapter._capture_diagnostics["reason"] == "native_validation_exception"


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.parametrize("padded_counter", [False, True])
async def test_hanayume_native_proof_is_single_outstanding_and_release_keeps_preloads(
    browser_page: Page, padded_counter: bool,
) -> None:
    await _install_mock_site(browser_page, authenticated=True, padded_counter=padded_counter)
    adapter = await _initialized(browser_page)
    await _body_state(browser_page, adapter)
    args = {
        "expectedSlots": [1], "expectedCurrent": 1,
        "expectedBodyTotal": 3 if padded_counter else 4,
        "expectedBodySlots": [1, 2, 3] if padded_counter else [1, 2, 3, 4],
        "hasTopEmptyPage": False,
        "episodePath": f"/episodes/{EPISODE_ID}",
    }
    first = await browser_page.evaluate(
        "args => window.__hanayumeNativeCapture.collect(args)", args
    )
    assert first["ok"] is True and first["mode"] == "native"
    assert first["token"]
    assert (await browser_page.evaluate("() => window.__hanayumeNativeCapture.status()"))["proofCount"] == 1

    second = await browser_page.evaluate(
        "args => window.__hanayumeNativeCapture.collect(args)", args
    )
    assert second["ok"] is True and second["mode"] == "rendered"
    assert await browser_page.evaluate(
        "token => window.__hanayumeNativeCapture.verify(token)", first["token"]
    ) is False
    released = await browser_page.evaluate(
        "args => window.__hanayumeNativeCapture.release(args)",
        {**args, "token": first["token"]},
    )
    assert released["proofCount"] == 0
    assert released["candidateCount"] == 1


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.parametrize(
    "mutation",
    [
        "document.querySelector('#xCVPages').children[4].className = '-cv-page'",
        "document.querySelector('#xCVPages').lastElementChild.remove()",
        "document.querySelector('#comici-viewer').classList.add('mode-has-top-emptypage')",
    ],
    ids=["tail-class", "wrapper-count", "top-empty-flag"],
)
async def test_hanayume_padded_native_capture_rejects_wrong_body_and_layout_drift(
    browser_page: Page, mutation: str,
) -> None:
    await _install_mock_site(browser_page, padded_counter=True)
    adapter = await _initialized(browser_page)
    args = {
        "expectedSlots": [1], "expectedCurrent": 1, "expectedBodyTotal": 4,
        "expectedBodySlots": [1, 2, 3, 4], "hasTopEmptyPage": False,
        "episodePath": f"/episodes/{EPISODE_ID}",
    }
    wrong = await browser_page.evaluate(
        "args => window.__hanayumeNativeCapture.collect(args)", args
    )
    assert wrong["ok"] is False and wrong["reason"] == "selected_page_changed"
    args.update(expectedBodyTotal=3, expectedBodySlots=[1, 2, 3])
    valid = await browser_page.evaluate(
        "args => window.__hanayumeNativeCapture.collect(args)", args
    )
    assert valid["ok"] is True and valid["mode"] == "native"
    await browser_page.evaluate(f"() => {{ {mutation}; }}")
    assert await browser_page.evaluate(
        "token => window.__hanayumeNativeCapture.verify(token)", valid["token"]
    ) is False
    changed = await browser_page.evaluate(
        "args => window.__hanayumeNativeCapture.collect(args)", args
    )
    assert changed["ok"] is False and changed["reason"] == "selected_page_changed"
    assert adapter._captured_slots == []


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_native_candidate_is_bound_to_draw_time_episode_route(
    browser_page: Page,
) -> None:
    await _install_mock_site(browser_page)
    adapter = await _initialized(browser_page)
    await _body_state(browser_page, adapter)
    await browser_page.evaluate(
        "episode => history.replaceState({}, '', `/episodes/${episode}`)", NOW_ID
    )

    result = await browser_page.evaluate(
        "args => window.__hanayumeNativeCapture.collect(args)",
        {
            "expectedSlots": [1], "expectedCurrent": 1, "expectedBodyTotal": 4,
            "expectedBodySlots": [1, 2, 3, 4], "hasTopEmptyPage": False,
            "episodePath": f"/episodes/{NOW_ID}",
        },
    )

    assert result["ok"] is True and result["mode"] == "rendered"
    assert result["reason"] == "native_candidate_missing_or_stale"


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.parametrize("abort", ["cancel", "timeout"])
async def test_hanayume_aborted_native_capture_releases_its_proof_and_keeps_preloads(
    browser_page: Page, monkeypatch: pytest.MonkeyPatch, abort: str
) -> None:
    await _install_mock_site(browser_page)
    adapter = await _initialized(browser_page)
    await _body_state(browser_page, adapter)
    reached_verify = asyncio.Event()

    async def block_verification(_page: Page, _token: str) -> bool:
        reached_verify.set()
        await asyncio.Future()
        return False

    monkeypatch.setattr(adapter, "_verify_native_capture", block_verification)
    if abort == "timeout":
        monkeypatch.setattr(hanayume_adapter_module, "CAPTURE_BUDGET_SECONDS", 0.8)
    task = asyncio.create_task(adapter.capture_page(browser_page))
    await asyncio.wait_for(reached_verify.wait(), timeout=3)

    if abort == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(UnknownPageStateError, match="exceeded its adapter budget"):
            await task

    status = await browser_page.evaluate("() => window.__hanayumeNativeCapture.status()")
    assert status["proofCount"] == 0
    assert status["candidateCount"] == 1
    assert adapter._captured_slots == []


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.parametrize(
    ("mutation", "reason", "pixel_comparison"),
    [
        ("canvas.getContext('2d').fillRect(0, 0, 1, 1)", "canvas_writes_changed", "different"),
        (
            (
                "const ctx = canvas.getContext('2d'); "
                "ctx.putImageData(ctx.getImageData(0, 0, canvas.width, canvas.height), 0, 0)"
            ),
            "canvas_writes_changed", "equal",
        ),
        ("canvas.width = canvas.width", "canvas_generation_changed", "different"),
        ("canvas.replaceWith(canvas.cloneNode())", "canvas_replaced", "not_compared"),
        ("canvas.style.marginLeft = '-3000px'", "canvas_readiness_or_visibility_changed", "equal"),
        (
            "canvas.closest('.-cv-page').style.left = '-3000px'",
            "active_slots_changed", "equal",
        ),
        (
            "document.querySelector('.-cv-f-page-current').textContent = '3'",
            "episode_or_counter_changed", "equal",
        ),
    ],
    ids=(
        "changed-pixels", "same-pixel-redraw", "bitmap-reset", "replacement",
        "visibility", "position", "counter",
    ),
)
async def test_hanayume_target_change_after_native_encoding_discards_encoded_snapshot(
    browser_page: Page, monkeypatch: pytest.MonkeyPatch, tmp_path,
    mutation: str, reason: str, pixel_comparison: str,
) -> None:
    await _install_mock_site(browser_page)
    adapter = await _initialized(browser_page)
    await _body_state(browser_page, adapter)
    entered = threading.Event()
    continue_encoding = threading.Event()
    original_encoder = hanayume_adapter_module.encode_native_webp

    def delayed_encoder(images):
        entered.set()
        if not continue_encoding.wait(timeout=3):
            raise TimeoutError("synthetic encoder wait timed out")
        return original_encoder(images)

    monkeypatch.setattr(hanayume_adapter_module, "encode_native_webp", delayed_encoder)
    task = asyncio.create_task(adapter.capture_page(browser_page))
    assert await asyncio.to_thread(entered.wait, 3)
    await browser_page.locator("#xCVPages > .-cv-page:nth-child(2) canvas").evaluate(
        f"canvas => {{ {mutation}; }}"
    )
    continue_encoding.set()

    with pytest.raises(UnknownPageStateError, match=f"verification={reason}") as caught:
        await task

    debug = await adapter.collect_debug_metadata(browser_page)
    capture = debug["capture"]
    verification = capture["verification"]
    assert verification["reason"] == reason
    assert verification["ok"] is False
    assert capture["encode_elapsed_ms"] >= 0
    assert verification["elapsed_ms"] >= 0
    assert verification["expected"]["selected_slots"] == [1]
    row = verification["rows"][0]
    assert row["pixel_comparison"] == pixel_comparison
    assert row["expected"]["canvas"]["width"] == 5
    if reason == "canvas_writes_changed":
        assert row["observed_writes"] > row["expected_writes"]
        assert row["observed_generation"] == row["expected_generation"]
    if reason == "canvas_generation_changed":
        assert row["observed_generation"] > row["expected_generation"]
    if reason == "canvas_replaced":
        assert row["same_canvas"] is False
    if reason == "active_slots_changed":
        assert row["observed"]["wrapper"] != row["expected"]["wrapper"]
    # Exercise the actual failure diagnostics writer; cleanup must retain the evidence.
    if pixel_comparison == "different" and reason == "canvas_writes_changed":
        runner = CrawlerRunner(RunConfig(
            site="hanayume", source_url=EPISODE_URL,
            output_dir=tmp_path / "output", diagnostics_dir=tmp_path / "diagnostics",
        ))
        await runner._write_failure_diagnostics(browser_page, caught.value, adapter=adapter)
        saved = json.loads((tmp_path / "diagnostics" / "metadata.json").read_text(encoding="utf-8"))
        assert saved["adapter_debug"]["capture"]["verification"] == verification
        assert "data:image" not in json.dumps(saved["adapter_debug"])
    status = await browser_page.evaluate("() => window.__hanayumeNativeCapture.status()")
    assert status["proofCount"] == 0
    assert status["candidateCount"] == 1
    assert adapter._captured_slots == []


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_runner_does_not_fall_back_to_locator_capture(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    await _install_mock_site(browser_page)
    adapter = HanayumeAdapter()
    fallback_calls: list[str] = []

    async def timeout_capture(_page: Page):
        raise PageChangeTimeoutError("synthetic direct PNG readback timeout")

    async def forbidden_locator_capture(_locator):
        fallback_calls.append("screenshot")
        raise AssertionError("Hanayume must never use screenshot fallback")

    adapter.capture_page = timeout_capture  # type: ignore[method-assign]
    monkeypatch.setattr(
        "screenshot_crawler.core.runner.capture_locator", forbidden_locator_capture
    )

    with pytest.raises(UnknownPageStateError, match="generic locator or screenshot"):
        await CrawlerRunner(
            RunConfig(
                site="hanayume",
                source_url=EPISODE_URL,
                output_dir=tmp_path / "output",
                diagnostics_dir=tmp_path / "diagnostics",
                max_pages=10,
                page_turn_delay_ms=0,
                page_change_timeout_ms=1_000,
            )
        ).run(browser_page, adapter)
    assert fallback_calls == []


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.parametrize("padded_counter", [False, True])
async def test_hanayume_local_viewer_fails_closed_when_spread_half_is_missing(
    browser_page: Page, padded_counter: bool,
) -> None:
    await _install_mock_site(browser_page, padded_counter=padded_counter)
    adapter = await _initialized(browser_page)
    await _body_state(browser_page, adapter)
    await adapter.capture_page(browser_page)
    await browser_page.locator("#xCVSeekBar").evaluate(
        "input => { input.value = '7'; input.dispatchEvent(new Event('input', {bubbles:true})); input.dispatchEvent(new Event('change', {bubbles:true})); }"
    )
    await browser_page.locator("#xCVPages > .-cv-page:nth-child(4) .-cv-page-canvas").evaluate(
        "node => node.remove()"
    )
    assert await adapter.detect_state(browser_page) is PageState.LOADING
    with pytest.raises(UnknownPageStateError):
        await adapter.capture_page(browser_page)


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.parametrize(
    ("user_label", "accepted"),
    [(FREE_LABEL, True), (NOW_FREE_LABEL, False)],
    ids=("same-free-copy", "conflicting-user-copy"),
)
async def test_hanayume_entry_uses_unique_public_ep_list_and_checks_all_target_copies(
    browser_page: Page, user_label: str, accepted: bool
) -> None:
    await _install_mock_site(browser_page, user_target_label=user_label)
    adapter = HanayumeAdapter()
    url = adapter.resolve_initial_navigation_url(EPISODE_URL)
    await adapter.prepare_page(browser_page)
    response = await browser_page.goto(url, wait_until="domcontentloaded")
    assert response is not None and response.status == 200

    if accepted:
        await adapter.initialize(browser_page)
        assert await adapter.detect_state(browser_page) is PageState.CONTENT
    else:
        with pytest.raises(UnknownPageStateError, match="copies disagree"):
            await adapter.initialize(browser_page)


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.parametrize(
    "mutation",
    ["unknown-copy", "unknown-root", "duplicate-public-root", "nested-user-root", "wrong-outer"],
)
async def test_hanayume_entry_rejects_unknown_target_copy_or_public_list_shape(
    browser_page: Page, mutation: str
) -> None:
    await _install_mock_site(browser_page)
    adapter = await _initialized(browser_page)
    await browser_page.evaluate(
        """mutation => {
          const publicRoot = document.querySelector('.series-eplist[data-e2e="epList"]');
          const main = publicRoot.parentElement;
          const wrap = publicRoot.closest('.series-eplist-wrap');
          const target = publicRoot.querySelector('.series-eplist-item[data-e2e="eli"]');
          if (mutation === 'unknown-copy') {
            const extra = document.createElement('div');
            extra.className = 'series-eplist-extra';
            extra.append(target.cloneNode(true));
            wrap.append(extra);
          } else if (mutation === 'duplicate-public-root') {
            main.append(publicRoot.cloneNode(true));
          } else if (mutation === 'unknown-root') {
            const extra = document.createElement('div');
            extra.className = 'series-eplist';
            extra.dataset.e2e = 'unexpectedList';
            main.append(extra);
          } else if (mutation === 'wrong-outer') {
            wrap.parentElement.dataset.e2e = 'pageSeries';
          } else {
            const extra = document.createElement('div');
            extra.className = 'series-eplist-extra';
            const user = document.createElement('div');
            user.className = 'series-eplist mode-user';
            user.dataset.e2e = 'epListUser';
            user.append(target.cloneNode(true));
            extra.append(user);
            wrap.append(extra);
          }
        }""",
        mutation,
    )
    with pytest.raises(UnknownPageStateError):
        await adapter._read_episode_row_labels(browser_page)


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_centered_spread_ignores_clipped_previous_wrapper_and_waits_for_both_sides(
    browser_page: Page,
) -> None:
    await _install_mock_site(browser_page)
    adapter = await _initialized(browser_page)
    await _body_state(browser_page, adapter)
    first = await adapter.get_content_identity(browser_page)
    assert await adapter.capture_page(browser_page)

    await adapter.go_next(browser_page)
    await adapter.wait_for_change(browser_page, first)
    observation = await adapter._observe(browser_page)
    assert observation.current == 3
    assert observation.active_slots == (2, 3)
    assert observation.ready_slots == (2, 3)
    assert await adapter.detect_state(browser_page) is PageState.CONTENT

    await browser_page.locator("#xCVPages > .-cv-page:nth-child(3)").evaluate(
        """node => {
          node.className = '-cv-page mode-loading mode-req-render';
          node.replaceChildren();
        }"""
    )
    loading = await adapter._observe(browser_page)
    assert loading.active_slots == (2, 3)
    assert loading.ready_slots == (3,)
    assert await adapter.detect_state(browser_page) is PageState.LOADING


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.parametrize("padded_counter", [False, True])
async def test_hanayume_local_viewer_rejects_terminal_before_complete_body_coverage(
    browser_page: Page, padded_counter: bool,
) -> None:
    await _install_mock_site(browser_page, padded_counter=padded_counter)
    adapter = await _initialized(browser_page)
    await browser_page.locator("#xCVSeekBar").focus()
    await browser_page.locator("#xCVSeekBar").press("Home")
    with pytest.raises(UnknownPageStateError, match="END before all body slots"):
        await adapter.detect_state(browser_page)


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_local_viewer_rejects_work_mismatch_before_preflight(browser_page: Page) -> None:
    state = await _install_mock_site(browser_page)
    adapter = HanayumeAdapter()
    await adapter.configure_target_identity(f"0000000000000:{EPISODE_ID}", "opaque-catalog-key")
    adapter.resolve_initial_navigation_url(EPISODE_URL)
    response = await browser_page.goto(EPISODE_URL, wait_until="domcontentloaded")
    assert response is not None and response.status == 200
    with pytest.raises(UnknownPageStateError, match="different Catalog work"):
        await adapter.initialize(browser_page)
    assert state["paths"] == [f"/episodes/{EPISODE_ID}"]


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.parametrize("padded_counter", [False, True])
async def test_hanayume_configured_batch_target_skips_listing_preflight_and_captures_to_end(
    browser_page: Page, padded_counter: bool,
) -> None:
    state = await _install_mock_site(
        browser_page, episode_rows=_preview_rows(), padded_counter=padded_counter
    )
    adapter = HanayumeAdapter()
    await adapter.configure_target_identity(f"{WORK_ID}:{EPISODE_ID}", "opaque-catalog-key")
    url = adapter.resolve_initial_navigation_url(EPISODE_URL)
    await adapter.prepare_page(browser_page)
    response = await browser_page.goto(url, wait_until="domcontentloaded")
    assert response is not None and response.status == 200

    await adapter.initialize(browser_page)
    assert state["paths"] == [f"/episodes/{EPISODE_ID}"]

    captured: list[int] = []
    for _ in range((adapter._body_total or 0) + 1):
        state_now = await adapter.detect_state(browser_page)
        if state_now is PageState.END:
            break
        assert state_now is PageState.CONTENT
        identity = await adapter.get_content_identity(browser_page)
        captures = await adapter.capture_page(browser_page)
        assert captures
        assert adapter._capture_diagnostics["mode"] == "source_canvas_lossless_webp"
        assert [Image.open(io.BytesIO(item.data)).convert("RGB").getpixel((0, 0)) for item in captures] == [
            (slot * 20, 40, 60) for slot in adapter._last_capture_slots
        ]
        captured.extend(adapter._last_capture_slots)
        await adapter.go_next(browser_page)
        await adapter.wait_for_change(browser_page, identity)

    assert await adapter.detect_state(browser_page) is PageState.END
    assert captured == ([1, 2, 3] if padded_counter else [1, 2, 3, 4])
    assert state["paths"] == [f"/episodes/{EPISODE_ID}"]


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_configured_batch_target_rejects_wrong_episode_identity(
    browser_page: Page,
) -> None:
    await _install_mock_site(browser_page)
    adapter = HanayumeAdapter()
    await adapter.configure_target_identity(f"{WORK_ID}:{NOW_ID}", "opaque-catalog-key")

    with pytest.raises(UnknownPageStateError, match="differs from the Catalog target"):
        adapter.resolve_initial_navigation_url(EPISODE_URL)


@pytest.mark.parametrize("cta", ["待つと無料で読む", "この話をレンタルする"])
@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_configured_batch_stops_on_unreadable_cta_viewer_without_action(
    browser_page: Page,
    cta: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = await _install_mock_site(browser_page, resume_current=1)
    adapter = HanayumeAdapter()
    adapter.page_change_timeout_ms = 250
    await adapter.configure_target_identity(f"{WORK_ID}:{EPISODE_ID}", "opaque-catalog-key")
    url = adapter.resolve_initial_navigation_url(EPISODE_URL)
    await adapter.prepare_page(browser_page)
    response = await browser_page.goto(url, wait_until="domcontentloaded")
    assert response is not None and response.status == 200
    await browser_page.evaluate(
        """label => {
          window.__hanayumeCtaClicks = 0;
          const cta = document.createElement('button');
          cta.textContent = label;
          cta.addEventListener('click', () => window.__hanayumeCtaClicks++);
          document.body.append(cta);
          const first = document.querySelector('#xCVPages > .-cv-page:nth-child(2)');
          first.className = '-cv-page mode-loading';
          first.replaceChildren();
        }""",
        cta,
    )
    capture_calls = 0
    original_capture_page = adapter.capture_page

    async def count_capture_calls(page: Page):
        nonlocal capture_calls
        capture_calls += 1
        return await original_capture_page(page)

    monkeypatch.setattr(adapter, "capture_page", count_capture_calls)

    with pytest.raises(PageChangeTimeoutError, match="first body page"):
        await adapter.initialize(browser_page)

    assert state["paths"] == [f"/episodes/{EPISODE_ID}"]
    assert capture_calls == 0
    assert await browser_page.evaluate("window.__hanayumeCtaClicks") == 0


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_local_viewer_rejects_free_label_change_after_preflight(browser_page: Page) -> None:
    state = await _install_mock_site(browser_page, return_episode_label="今なら無料")
    await _initialized_before_return(browser_page)
    assert state["episode_visits"] == 2
    assert state["paths"].count(f"/series/{WORK_ID}/1") == 1  # type: ignore[union-attr]


async def _initialized_before_return(page: Page) -> None:
    adapter = HanayumeAdapter()
    url = adapter.resolve_initial_navigation_url(EPISODE_URL)
    await adapter.prepare_page(page)
    response = await page.goto(url, wait_until="domcontentloaded")
    assert response is not None and response.status == 200
    with pytest.raises(UnknownPageStateError, match="free access"):
        await adapter.initialize(page)


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_fresh_preflight_stops_at_unique_target_in_bare_listing(
    browser_page: Page,
) -> None:
    state = await _install_preflight_site(
        browser_page,
        bare_rows=[(EPISODE_ID, FREE_LABEL)],
        range_rows={},
    )

    await _initialized(browser_page)

    assert state["paths"] == [
        f"/episodes/{EPISODE_ID}",
        f"/series/{WORK_ID}",
        f"/episodes/{EPISODE_ID}",
    ]


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_fresh_preflight_stops_at_target_in_first_numbered_range(
    browser_page: Page,
) -> None:
    range_one = [(f"{index:013x}", FREE_LABEL) for index in range(200, 229)]
    range_one.insert(10, (EPISODE_ID, FREE_LABEL))
    state = await _install_preflight_site(
        browser_page,
        bare_rows=[(f"{index:013x}", FREE_LABEL) for index in range(500, 510)],
        range_rows={1: range_one},
    )

    await _initialized(browser_page)

    paths = state["paths"]
    assert isinstance(paths, list)
    assert paths.count(f"/series/{WORK_ID}/1") == 1
    assert f"/series/{WORK_ID}/2" not in paths
    assert paths[-1] == f"/episodes/{EPISODE_ID}"


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_fresh_preflight_exhausts_declared_ranges_only_when_target_missing(
    browser_page: Page,
) -> None:
    state = await _install_preflight_site(
        browser_page,
        bare_rows=[(f"{index:013x}", FREE_LABEL) for index in range(500, 510)],
        range_rows={},
    )
    adapter = HanayumeAdapter()
    adapter.resolve_initial_navigation_url(EPISODE_URL)
    response = await browser_page.goto(EPISODE_URL, wait_until="domcontentloaded")
    assert response is not None and response.status == 200

    with pytest.raises(UnknownPageStateError, match="target episode is missing"):
        await adapter.initialize(browser_page)

    assert state["paths"] == [
        f"/episodes/{EPISODE_ID}",
        f"/series/{WORK_ID}",
        f"/series/{WORK_ID}/1",
        f"/series/{WORK_ID}/2",
    ]


@pytest.mark.parametrize("reverse", [False, True], ids=("same-order", "observed-reverse"))
@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_absent_episode_row_accepts_exact_fresh_preview_and_reaches_end(
    browser_page: Page,
    reverse: bool,
) -> None:
    preview = _preview_rows()
    episode_rows = list(reversed(preview)) if reverse else preview
    range_one = [(EPISODE_ID, FREE_LABEL)] + [
        (f"{index:013x}", FREE_LABEL) for index in range(200, 229)
    ]
    state = await _install_preflight_site(
        browser_page,
        bare_rows=preview,
        range_rows={1: range_one},
        episode_rows=episode_rows,
        episode_history_rows=[],
    )

    adapter = await _initialized(browser_page)
    assert state["paths"][-2:] == [f"/series/{WORK_ID}/1", f"/episodes/{EPISODE_ID}"]
    captured: list[int] = []
    for _ in range((adapter._body_total or 0) + 1):
        state_now = await adapter.detect_state(browser_page)
        if state_now is PageState.END:
            break
        assert state_now is PageState.CONTENT
        identity = await adapter.get_content_identity(browser_page)
        result = await adapter.capture_page(browser_page)
        assert result
        captured.extend(adapter._last_capture_slots)
        await adapter.go_next(browser_page)
        await adapter.wait_for_change(browser_page, identity)
    assert await adapter.detect_state(browser_page) is PageState.END
    assert captured == [1, 2, 3, 4]


@pytest.mark.parametrize(
    ("episode_rows", "episode_history_rows", "message"),
    [
        (_preview_rows()[:-1] + [(f"{800:013x}", FREE_LABEL)], [], "exact fresh public preview"),
        (_preview_rows()[:-1] + [(_preview_rows()[-1][0], NOW_FREE_LABEL)], [], "exact fresh public preview"),
        ([_preview_rows()[0], _preview_rows()[2], _preview_rows()[1], _preview_rows()[3]], [], "exact fresh public preview"),
        ([_preview_rows()[0], _preview_rows()[0]], [], "duplicate ID"),
        (_preview_rows(), [(EPISODE_ID, FREE_LABEL)], "history listing"),
        (_preview_rows(), [(_preview_rows()[0][0], NOW_FREE_LABEL)], "copies disagree"),
    ],
    ids=("id-drift", "label-drift", "arbitrary-order", "duplicate-row", "history-target-only", "history-conflict"),
)
@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_absent_episode_row_rejects_preview_drift_or_history_target(
    browser_page: Page,
    episode_rows: list[tuple[str, str]],
    episode_history_rows: list[tuple[str, str]],
    message: str,
) -> None:
    preview = _preview_rows()
    range_one = [(EPISODE_ID, FREE_LABEL)] + [
        (f"{index:013x}", FREE_LABEL) for index in range(200, 229)
    ]
    state = await _install_preflight_site(
        browser_page,
        bare_rows=preview,
        range_rows={1: range_one},
        episode_rows=episode_rows,
        episode_history_rows=episode_history_rows,
    )
    adapter = HanayumeAdapter()
    adapter.resolve_initial_navigation_url(EPISODE_URL)
    response = await browser_page.goto(EPISODE_URL, wait_until="domcontentloaded")
    assert response is not None and response.status == 200

    with pytest.raises(UnknownPageStateError, match=message):
        await adapter.initialize(browser_page)

    assert state["paths"][-1] == f"/episodes/{EPISODE_ID}"


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_absent_episode_row_rejects_non_target_copy_outside_known_roots(
    browser_page: Page,
) -> None:
    range_one = [(EPISODE_ID, FREE_LABEL)] + [
        (f"{index:013x}", FREE_LABEL) for index in range(200, 229)
    ]
    state = await _install_preflight_site(
        browser_page,
        bare_rows=_preview_rows(),
        range_rows={1: range_one},
        episode_rows=_preview_rows(),
        episode_history_rows=[],
        episode_unknown_rows=[(f"{900:013x}", FREE_LABEL)],
    )
    adapter = HanayumeAdapter()
    adapter.resolve_initial_navigation_url(EPISODE_URL)
    response = await browser_page.goto(EPISODE_URL, wait_until="domcontentloaded")
    assert response is not None and response.status == 200

    with pytest.raises(UnknownPageStateError, match="outside the known public/history roots"):
        await adapter.initialize(browser_page)

    assert state["paths"][-1] == f"/episodes/{EPISODE_ID}"


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_empty_bare_listing_keeps_exact_numbered_target_path_available(
    browser_page: Page,
) -> None:
    state = await _install_preflight_site(
        browser_page,
        bare_rows=[],
        range_rows={1: [(EPISODE_ID, FREE_LABEL)] + [
            (f"{index:013x}", FREE_LABEL) for index in range(200, 229)
        ]},
    )
    await _initialized(browser_page)

    assert state["paths"] == [
        f"/episodes/{EPISODE_ID}",
        f"/series/{WORK_ID}",
        f"/series/{WORK_ID}/1",
        f"/episodes/{EPISODE_ID}",
    ]


@pytest.mark.parametrize(
    ("bare_rows", "error"),
    [
        ([(EPISODE_ID, FREE_LABEL), (EPISODE_ID, FREE_LABEL)], "duplicate episode ID"),
        ([(EPISODE_ID, f"{FREE_LABEL} / {NOW_FREE_LABEL}")], "not one exact"),
        ([(EPISODE_ID, NOW_FREE_LABEL)], "not one exact"),
    ],
    ids=("duplicate-target", "conflicting-badge", "now-free-target"),
)
@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_bare_preflight_rejects_ambiguous_or_nonfree_target_without_searching(
    browser_page: Page,
    bare_rows: list[tuple[str, str]],
    error: str,
) -> None:
    state = await _install_preflight_site(
        browser_page,
        bare_rows=bare_rows,
        range_rows={},
    )
    adapter = HanayumeAdapter()
    adapter.resolve_initial_navigation_url(EPISODE_URL)
    response = await browser_page.goto(EPISODE_URL, wait_until="domcontentloaded")
    assert response is not None and response.status == 200

    with pytest.raises(UnknownPageStateError, match=error):
        await adapter.initialize(browser_page)

    assert state["paths"] == [f"/episodes/{EPISODE_ID}", f"/series/{WORK_ID}"]


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_preflight_rejects_conflicting_public_and_history_badges(
    browser_page: Page,
) -> None:
    state = await _install_preflight_site(
        browser_page,
        bare_rows=[(EPISODE_ID, FREE_LABEL)],
        range_rows={},
        history_conflict=True,
    )
    adapter = HanayumeAdapter()
    adapter.resolve_initial_navigation_url(EPISODE_URL)
    response = await browser_page.goto(EPISODE_URL, wait_until="domcontentloaded")
    assert response is not None and response.status == 200

    with pytest.raises(UnknownPageStateError, match="copies disagree"):
        await adapter.initialize(browser_page)

    assert state["paths"] == [f"/episodes/{EPISODE_ID}", f"/series/{WORK_ID}"]


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_preflight_rejects_range_drift_before_searching_next_range(
    browser_page: Page,
) -> None:
    state = await _install_preflight_site(
        browser_page,
        bare_rows=_preview_rows(),
        range_rows={
            1: [(EPISODE_ID, FREE_LABEL)]
            + [(f"{index:013x}", FREE_LABEL) for index in range(200, 229)]
        },
        drift_first_range=True,
    )
    adapter = HanayumeAdapter()
    adapter.resolve_initial_navigation_url(EPISODE_URL)
    response = await browser_page.goto(EPISODE_URL, wait_until="domcontentloaded")
    assert response is not None and response.status == 200

    with pytest.raises(UnknownPageStateError, match="range set changed"):
        await adapter.initialize(browser_page)

    paths = state["paths"]
    assert isinstance(paths, list)
    assert f"/series/{WORK_ID}/1" in paths
    assert f"/series/{WORK_ID}/2" not in paths


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_preflight_rechecks_exact_episode_row_on_entry(browser_page: Page) -> None:
    range_one = [(EPISODE_ID, FREE_LABEL)] + [
        (f"{index:013x}", FREE_LABEL) for index in range(200, 229)
    ]
    state = await _install_preflight_site(
        browser_page,
        bare_rows=_preview_rows(),
        range_rows={1: range_one},
        episode_rows=[(NOW_ID, FREE_LABEL)],
    )
    adapter = HanayumeAdapter()
    adapter.resolve_initial_navigation_url(EPISODE_URL)
    response = await browser_page.goto(EPISODE_URL, wait_until="domcontentloaded")
    assert response is not None and response.status == 200

    with pytest.raises(UnknownPageStateError, match="absent outside the exact fresh public preview"):
        await adapter.initialize(browser_page)

    assert state["paths"][-1] == f"/episodes/{EPISODE_ID}"


@pytest.mark.parametrize(
    "entered_episode_href",
    (
        f"https://other.example/episodes/{EPISODE_ID}",
        f"https://hanayume.com/episodes/{EPISODE_ID}?source=other",
    ),
    ids=("foreign-origin", "query-suffix"),
)
@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_entry_recheck_rejects_noncanonical_target_like_episode_urls(
    browser_page: Page,
    entered_episode_href: str,
) -> None:
    range_one = [(EPISODE_ID, FREE_LABEL)] + [
        (f"{index:013x}", FREE_LABEL) for index in range(200, 229)
    ]
    state = await _install_preflight_site(
        browser_page,
        bare_rows=_preview_rows(),
        range_rows={1: range_one},
        entered_episode_href=entered_episode_href,
    )
    adapter = HanayumeAdapter()
    adapter.resolve_initial_navigation_url(EPISODE_URL)
    response = await browser_page.goto(EPISODE_URL, wait_until="domcontentloaded")
    assert response is not None and response.status == 200

    with pytest.raises(UnknownPageStateError, match="not the exact first-party target"):
        await adapter.initialize(browser_page)

    assert state["paths"] == [
        f"/episodes/{EPISODE_ID}",
        f"/series/{WORK_ID}",
        f"/series/{WORK_ID}/1",
        f"/episodes/{EPISODE_ID}",
    ]
