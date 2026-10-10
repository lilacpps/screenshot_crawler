from __future__ import annotations

import io
from urllib.parse import urlsplit

import pytest
from PIL import Image
from playwright.async_api import Page

from screenshot_crawler.core.errors import PageChangeTimeoutError, UnknownPageStateError
from screenshot_crawler.core.models import RunConfig
from screenshot_crawler.core.runner import CrawlerRunner
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.hanayume.adapter import HanayumeAdapter

WORK_ID = "1f9f5b0d4cd52"
EPISODE_ID = "8c6f15923caa0"
NOW_ID = "9202b052ad237"
EPISODE_URL = f"https://hanayume.com/episodes/{EPISODE_ID}"
WORK_URL = f"https://hanayume.com/series/{WORK_ID}"
FREE_LABEL = "\u7121\u6599"
NOW_FREE_LABEL = "\u4eca\u306a\u3089\u7121\u6599"


def _row(episode_id: str, label: str) -> str:
    return f"""<div class="series-eplist-item" data-e2e="eli">
      <a class="series-eplist-item-link" href="/episodes/{episode_id}">episode</a>
      <span class="series-eplist-item-access-text">{label}</span>
    </div>"""


def _listing(*, selected: bool, target_label: str = "無料") -> str:
    class_name = "series-sort-link mode-current" if selected else "series-sort-link"
    return f"""<div class="series-eplist-wrap">
      <a class="{class_name}" href="{WORK_URL if selected else WORK_URL + '/1'}">1-2</a>
      {_row(EPISODE_ID, target_label)}
      {_row(NOW_ID, "今なら無料")}
    </div>"""


def _episode_html(*, current: int = 3, label: str = "無料") -> str:
    return f"""<!doctype html><html><body>
      <header id="xHeader"><a class="ep-h-main-h-series" href="{WORK_URL}">work</a></header>
      {_listing(selected=False, target_label=label)}
      <div id="comici-viewer" class="-cv mode-spread">
        <div class="-cv-f-page-current"></div><div class="-cv-f-page-total">9</div>
        <input id="xCVSeekBar" type="range" min="1" max="9" step="2" value="9">
        <div id="xCVPages"></div>
      </div>
      <script>
        (() => {{
          const total = 9;
          const bodyTotal = 4;
          const root = document.querySelector('#comici-viewer');
          const pageRoot = document.querySelector('#xCVPages');
          const seek = document.querySelector('#xCVSeekBar');
          const currentText = document.querySelector('.-cv-f-page-current');
          const wrappers = [];
          for (let i = 0; i <= total; i++) {{
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
          const classFor = index => {{
            if (index === 0) return '-cv-page mode-empty mode-pr mode-top-pr';
            if (index === total - 4) return '-cv-page mode-ci';
            if (index === total - 3 || index === total - 2) return '-cv-page mode-empty mode-pr';
            if (index === total - 1) return '-cv-page mode-good';
            if (index === total) return '-cv-page mode-last';
            return '-cv-page';
          }};
          function render(current, terminal = false) {{
            currentText.textContent = String(current);
            document.querySelector('.-cv-f-page-total').textContent = String(total);
            seek.value = String(total - (current - 1));
            root.classList.toggle('mode-last-page', terminal);
            const visible = current === 1 ? [0, 1] : [current - 1, current];
            for (let i = 0; i <= total; i++) {{
              const node = wrappers[i];
              node.replaceChildren();
              node.className = classFor(i);
              node.style.left = '-3000px';
            }}
            if (current === 1) wrappers[0].style.left = '200px';
            visible.forEach((index, side) => {{
              wrappers[index].style.left = `${{side * 100}}px`;
              if (index < 1 || index > bodyTotal) return;
              const canvas = side === 0 ? reusedCanvas : secondCanvas;
              const context = canvas.getContext('2d');
              context.fillStyle = `rgb(${{index * 20}},40,60)`;
              context.fillRect(0, 0, canvas.width, canvas.height);
              const holder = document.createElement('div');
              holder.className = '-cv-page-canvas';
              holder.append(canvas);
              wrappers[index].append(holder);
              wrappers[index].classList.add('mode-loaded', 'mode-rendered');
            }});
            if (current === 3) {{
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
          seek.addEventListener('input', () => render(total - Number(seek.value) + 1));
          seek.addEventListener('change', () => render(total - Number(seek.value) + 1));
          seek.addEventListener('keydown', event => {{
            if (event.key === 'End') {{ event.preventDefault(); render(1); }}
            if (event.key === 'Home') {{ event.preventDefault(); render(total, true); }}
          }});
          render({current});
        }})();
      </script>
    </body></html>"""


async def _install_mock_site(
    page: Page,
    *,
    return_episode_label: str = "無料",
    resume_current: int = 3,
) -> dict[str, object]:
    state: dict[str, object] = {"episode_visits": 0, "paths": []}

    async def route_handler(route) -> None:
        path = urlsplit(route.request.url).path
        state["paths"].append(path)  # type: ignore[union-attr]
        if path == f"/episodes/{EPISODE_ID}":
            visits = int(state["episode_visits"]) + 1
            state["episode_visits"] = visits
            label = "無料" if visits == 1 else return_episode_label
            body = _episode_html(current=resume_current, label=label)
        elif path == f"/series/{WORK_ID}":
            body = f"""<div class="series-eplist-wrap">
              <a class="series-sort-link" href="{WORK_URL}/1">1-2</a>
            </div>"""
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
    return (
        '<div class="series-eplist-wrap">'
        + "".join(links)
        + "".join(_row(episode_id, label) for episode_id, label in rows)
        + "</div>"
    )


async def _install_preflight_site(
    page: Page,
    *,
    bare_rows: list[tuple[str, str]],
    range_rows: dict[int, list[tuple[str, str]]],
    drift_first_range: bool = False,
    entered_episode_id: str = EPISODE_ID,
    entered_episode_href: str | None = None,
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
            body = _episode_html()
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
            body = _search_listing(selected_page=None, rows=bare_rows)
        elif path == f"/series/{WORK_ID}/1":
            body = _search_listing(
                selected_page=1,
                rows=defaults[1],
                drift=drift_first_range,
            )
        elif path == f"/series/{WORK_ID}/2":
            body = _search_listing(selected_page=2, rows=defaults[2])
        else:
            await route.fulfill(status=404, body="")
            return
        await route.fulfill(status=200, content_type="text/html; charset=utf-8", body=body)

    await page.route("https://hanayume.com/**", route_handler)
    return state


async def _initialized(page: Page, *, adapter: HanayumeAdapter | None = None) -> HanayumeAdapter:
    instance = adapter or HanayumeAdapter()
    url = instance.resolve_initial_navigation_url(EPISODE_URL)
    response = await page.goto(url, wait_until="domcontentloaded")
    assert response is not None and response.status == 200
    await instance.initialize(page)
    return instance


async def _body_state(page: Page, adapter: HanayumeAdapter) -> None:
    assert await adapter.detect_state(page) is PageState.CONTENT


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
    assert first.size == (5, 7)
    assert first.getpixel((0, 0)) == (20, 40, 60)
    assert first_identity.page_id == "1"

    await adapter.go_next(browser_page)
    await adapter.wait_for_change(browser_page, first_identity)
    await _body_state(browser_page, adapter)
    spread_identity = await adapter.get_content_identity(browser_page)
    spread = await adapter.capture_page(browser_page)
    assert spread is not None and len(spread) == 2
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
    assert Image.open(io.BytesIO(final[0].data)).convert("RGB").getpixel((0, 0)) == (80, 40, 60)

    await adapter.go_next(browser_page)
    await adapter.wait_for_change(browser_page, final_identity)
    assert await adapter.detect_state(browser_page) is PageState.END


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
async def test_hanayume_local_viewer_fails_closed_when_spread_half_is_missing(browser_page: Page) -> None:
    await _install_mock_site(browser_page)
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
async def test_hanayume_local_viewer_rejects_terminal_before_complete_body_coverage(browser_page: Page) -> None:
    await _install_mock_site(browser_page)
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
async def test_hanayume_local_viewer_rejects_free_label_change_after_preflight(browser_page: Page) -> None:
    state = await _install_mock_site(browser_page, return_episode_label="今なら無料")
    await _initialized_before_return(browser_page)
    assert state["episode_visits"] == 2
    assert state["paths"].count(f"/series/{WORK_ID}/1") == 1  # type: ignore[union-attr]


async def _initialized_before_return(page: Page) -> None:
    adapter = HanayumeAdapter()
    url = adapter.resolve_initial_navigation_url(EPISODE_URL)
    response = await page.goto(url, wait_until="domcontentloaded")
    assert response is not None and response.status == 200
    with pytest.raises(UnknownPageStateError, match="no longer has one exact"):
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
async def test_hanayume_preflight_rejects_range_drift_before_searching_next_range(
    browser_page: Page,
) -> None:
    state = await _install_preflight_site(
        browser_page,
        bare_rows=[],
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
        bare_rows=[],
        range_rows={1: range_one},
        entered_episode_id=NOW_ID,
    )
    adapter = HanayumeAdapter()
    adapter.resolve_initial_navigation_url(EPISODE_URL)
    response = await browser_page.goto(EPISODE_URL, wait_until="domcontentloaded")
    assert response is not None and response.status == 200

    with pytest.raises(UnknownPageStateError, match="current episode row is missing"):
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
        bare_rows=[],
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
