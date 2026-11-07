from __future__ import annotations

import io
import json
import zipfile

import pytest
import pytest_asyncio
from PIL import Image
from playwright.async_api import Browser, Page

from screenshot_crawler.core.errors import (
    MaxPagesExceededError,
    UnknownPageStateError,
)
from screenshot_crawler.core.models import RunConfig
from screenshot_crawler.core.packaging import package_crawl_output
from screenshot_crawler.core.runner import CrawlerRunner
from screenshot_crawler.site_adapters.ebookjapan.adapter import EbookJapanAdapter
from screenshot_crawler.site_adapters.ebookjapan.viewer import (
    ANCHOR_READER_JS,
    CAPTURE_OBSERVER_JS,
    FRAME_STATE_JS,
)

pytestmark = pytest.mark.asyncio(loop_scope="module")

READER_PATH = "/viewer/purchased/B123456789012/"
READER_URL = f"https://ebookjapan.yahoo.co.jp{READER_PATH}"
TITLE = "Neutral Fixture Volume"
PRODUCT_URL = "https://ebookjapan.yahoo.co.jp/books/134336/A000083590/"
LISTING_URL = "https://ebookjapan.yahoo.co.jp/books/all/134336/"


@pytest_asyncio.fixture(loop_scope="module")
async def browser_page(integration_browser: Browser) -> Page:
    context = await integration_browser.new_context(viewport={"width": 1906, "height": 986})
    page = await context.new_page()
    try:
        yield page
    finally:
        await page.close()
        await context.close()


def _html(*, current: int = 1, total: int = 1, slot_count: int = 1) -> str:
    slots = []
    for index in range(slot_count):
        if slot_count == 3:
            left = "0px" if index == 2 else "10000px"
        else:
            left = "50vw" if index == 1 and slot_count > 1 else "0px"
        slots.append(
            f'<div class="comic-viewer__page-slot" data-index="{index}" '
            f'style="position:fixed;left:{left};top:0;width:50vw;height:100vh;'
            f'{"display:none;" if slot_count == 3 and index != 2 else ""}">'
            '<canvas class="page-canvas" width="300" height="150" '
            'style="position:absolute;right:0;width:auto;height:100%"></canvas></div>'
        )
    return f"""<!doctype html><html><head><style>
      .legacy-comic-header,.legacy-comic-footer{{position:fixed;left:0;width:100%;height:24px;z-index:20;background:#ddd}}
      .legacy-comic-header{{top:0}} .legacy-comic-footer{{bottom:0}}
      </style></head><body>
      <header class="legacy-comic-header"><span class="legacy-comic-header__title">{TITLE}</span></header>
      <footer class="legacy-comic-footer"><span class="legacy-comic-footer__page-output">{current} / {total}</span></footer>
      <div class="comic-viewer__scroll-container comic-viewer__scroll-container--horizontal-rtl comic-viewer__scroll-container--spread">
        {''.join(slots)}
      </div>
      <div class="next-item book-last-dead-end__next" style="display:none;position:fixed;left:40px;top:180px;z-index:30">&#12371;&#12398;&#20316;&#21697;&#12399;&#12371;&#12371;&#12414;&#12391;&#12391;&#12377;</div>
      <input type="range" class="seekbar__slider" min="0" max="{total - 1}" value="0" style="position:fixed;left:0;top:650px">
      <script>
      let fixtureCurrent={current};
      document.addEventListener('click',event=>{{
        if(!(event.target instanceof HTMLCanvasElement))return;
        const header=document.querySelector('.legacy-comic-header'),footer=document.querySelector('.legacy-comic-footer');
        if(!header.hidden||!footer.hidden){{
          if(window.__ejCenterClickAdvances&&fixtureCurrent===1&&event.clientX/innerWidth<=.25&&{total}===3){{
            fixtureCurrent=2;header.hidden=true;footer.hidden=true;
            document.querySelector('.legacy-comic-footer__page-output').textContent='2 / {total}';
            const slots=[...document.querySelectorAll('.comic-viewer__page-slot')];
            slots[0].style.display='block';slots[1].style.display='block';slots[2].style.display='none';return;
          }}
          header.hidden=true;footer.hidden=true;return;
        }}
        if(event.clientX>16||{total}!==3)return;
        if(fixtureCurrent===1){{
          fixtureCurrent=2;document.querySelector('.legacy-comic-footer__page-output').textContent='2 / {total}';
          const slots=[...document.querySelectorAll('.comic-viewer__page-slot')];
          slots[0].style.display='block';slots[0].style.left='0px';
          slots[1].style.display='block';slots[1].style.left='408px';
          slots[2].style.display='none';
        }}else if(fixtureCurrent===2){{
          fixtureCurrent=3;document.querySelectorAll('.comic-viewer__page-slot').forEach(slot=>slot.style.display='none');
          document.querySelector('.book-last-dead-end__next').style.display='block';
        }}
      }});
      </script>
    </body></html>"""


async def _open_reader(page: Page, *, current: int = 1, total: int = 1, slot_count: int = 1) -> None:
    await page.context.route(
        "https://ebookjapan.yahoo.co.jp/**",
        lambda route: route.fulfill(
            status=200,
            content_type="text/html",
            body=_html(current=current, total=total, slot_count=slot_count),
        ),
    )
    await page.goto(READER_URL)
    installed = await page.evaluate(CAPTURE_OBSERVER_JS)
    assert installed.get("installed") is True
    anchor = await page.evaluate(
        ANCHOR_READER_JS,
        {"expectedTitle": TITLE, "expectedPath": READER_PATH, "maxSlots": 2_000},
    )
    assert anchor.get("ok") is True


async def _draw_full_same_size(page: Page) -> None:
    await page.evaluate(
        """async() => {
          const source=document.createElement('canvas');source.width=408;source.height=600;
          source.getContext('2d').fillRect(0,0,408,600);
          for(const target of document.querySelectorAll('.page-canvas')){
            target.width=408;target.height=600;
            target.getContext('2d').drawImage(source,0,0);
          }
          await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
        }"""
    )


async def _redraw_on_resize(page: Page) -> None:
    await page.evaluate(
        """()=>window.addEventListener('resize',()=>{
          for(const target of document.querySelectorAll('.page-canvas')){
            const source=document.createElement('canvas');source.width=target.width;source.height=target.height;
            source.getContext('2d').fillRect(0,0,source.width,source.height);
            target.getContext('2d').drawImage(source,0,0);
          }
        })"""
    )


async def _frame(page: Page, *, current: int = 1) -> dict[str, object]:
    return await page.evaluate(FRAME_STATE_JS, {"expectedCurrent": current})


def _runner_listing_html(*, account_mode: str = "present") -> str:
    account_markup = (
        '<div class="account__user"><a href="/mypage/">signed-in</a></div>'
        if account_mode == "present"
        else ""
    )
    account_script = (
        "<script>setTimeout(()=>{const shell=document.createElement('div');"
        "shell.className='account__user';const link=document.createElement('a');"
        "link.href='/mypage/';link.textContent='signed-in';shell.append(link);"
        "document.body.append(shell);},900);</script>"
        if account_mode == "delayed"
        else ""
    )
    return f"""<!doctype html><html><body>
      <header class="page-books-all__list-header">
        <span class="search-header__result">\u51681\u518a</span>
        <label class="search-filter__item"><input type="radio" checked>\u0031\u5dfb\u304b\u3089</label>
      </header>
      {account_markup}
      <h1 class="page-books-all__heading">Neutral Fixture Work</h1>
      <ul><li class="book-list__item">
        <a class="book-item" href="/books/134336/A000083590/"><span class="book-caption__title">{TITLE}</span></a>
        <span class="book-caption__tagtext">\u8cfc\u5165\u6e08\u307f</span>
        <button class="icon-btn-wrapper__btn icon-btn"><span class="font-read">\u8aad\u3080</span></button>
      </li></ul>
      {account_script}
      <script>document.querySelector('button.icon-btn').addEventListener('click',()=>location.href='{READER_URL}');</script>
    </body></html>"""


def _runner_reader_html(*, mode: str = "normal") -> str:
    body = _html(current=1, total=3, slot_count=3)
    prefix = f"""
      window.__ejFixtureMode={mode!r};
      function renderFixturePages(){{
        for(const [index,canvas] of [...document.querySelectorAll('.page-canvas')].entries()){{
          if(window.__ejFixtureMode==='half-spread'&&fixtureCurrent===2&&index===1){{canvas.width=408;canvas.height=600;continue;}}
          canvas.width=408;canvas.height=600;
          const source=document.createElement('canvas');source.width=408;source.height=600;
          const sourceContext=source.getContext('2d');sourceContext.fillStyle=`rgb(${{index*40}},0,0)`;sourceContext.fillRect(0,0,408,600);
          canvas.getContext('2d').drawImage(source,0,0);
        }}
      }}
      window.addEventListener('resize',renderFixturePages);
    """
    body = body.replace("<script>\n      let fixtureCurrent=1;", "<script>\n      let fixtureCurrent=1;\n" + prefix + "\n      renderFixturePages();")
    body = body.replace(
        "if(fixtureCurrent===1){\n          fixtureCurrent=2;",
        "if(fixtureCurrent===1){\n          if(window.__ejFixtureMode==='premature-end'){document.querySelectorAll('.comic-viewer__page-slot').forEach(slot=>slot.style.display='none');document.querySelector('.book-last-dead-end__next').style.display='block';return;}\n          fixtureCurrent=2;",
    )
    body = body.replace(
        "slots[2].style.display='none';\n        }else if(fixtureCurrent===2){",
        "slots[2].style.display='none';\n          renderFixturePages();\n          if(window.__ejFixtureMode==='wrong-route')history.replaceState({},'', '/viewer/purchased/B999999999999/');\n        }else if(fixtureCurrent===2){",
    )
    return body


def _runner_seven_slot_reader_html(*, mode: str = "normal") -> str:
    slots = "".join(
        f'<section class="comic-viewer__page-slot" data-page="{page}" '
        'style="position:fixed;top:0;left:0;width:50vw;height:100vh;display:none">'
        '<canvas class="page-canvas" width="816" height="1200" '
        'style="position:absolute;right:0;width:auto;height:100%"></canvas></section>'
        for page in range(7, 0, -1)
    )
    body = """<!doctype html><html><head><style>
      html,body{margin:0;width:100%;height:100%;overflow:hidden}
      .legacy-comic-header__title,.legacy-comic-footer__page-output,.seekbar__slider{position:fixed;z-index:5}
      .legacy-comic-header__title{top:0;left:0}
      .legacy-comic-footer__page-output{bottom:0;left:0}
      .seekbar__slider{bottom:10px;left:10vw;width:80vw}
      .comic-viewer__page-slot{background:transparent}
      .comic-viewer__scroll-container{position:fixed;inset:0;direction:rtl}
      .comic-viewer__scroll-container--horizontal-rtl{direction:rtl}
      .comic-viewer__scroll-container--spread{display:block}
      .comic-viewer__page-slot canvas{display:block}
      .next-item.book-last-dead-end__next{position:fixed;inset:0;display:grid;place-items:center}
      .next-item.book-last-dead-end__next[hidden],body.toolbar-hidden .legacy-comic-header__title,
      body.toolbar-hidden .legacy-comic-footer__page-output,body.toolbar-hidden .seekbar__slider{display:none}
      </style></head><body>
      <header class="legacy-comic-header__title">__TITLE__</header>
      <footer class="legacy-comic-footer__page-output">1 / 7</footer>
      <input class="seekbar__slider" type="range" min="0" max="6" step="1" value="6">
      <main class="comic-viewer__scroll-container comic-viewer__scroll-container--horizontal-rtl comic-viewer__scroll-container--spread">__SLOTS__</main>
      <div class="next-item book-last-dead-end__next" hidden>\u3053\u306e\u4f5c\u54c1\u306f\u3053\u3053\u307e\u3067\u3067\u3059</div>
      <script>
      let current=1;const sequence=[1,2,4,6,7];const mode=__MODE__;
      const root=document.querySelector('.comic-viewer__scroll-container');
      const counter=document.querySelector('.legacy-comic-footer__page-output');
      const dead=document.querySelector('.book-last-dead-end__next');
      const slots=[...root.querySelectorAll('.comic-viewer__page-slot')];
      function render(){
        const active=current===1?[1]:current<4?[2,3]:current<6?[4,5]:current===6?[6,7]:[];
        for(const slot of slots){
          const page=Number(slot.dataset.page),shown=active.includes(page);
          slot.style.display=shown?'block':'none';
          slot.style.left=page%2===0?'50vw':'0px';
          if(shown){
            const canvas=slot.querySelector('canvas');canvas.width=816;canvas.height=1200;
            const source=document.createElement('canvas');source.width=816;source.height=1200;
            const sourceContext=source.getContext('2d');sourceContext.fillStyle='rgb(32,48,64)';sourceContext.fillRect(0,0,816,1200);
            canvas.getContext('2d').drawImage(source,0,0);
          }
        }
        counter.textContent=current+' / 7';dead.hidden=current!==7;
      }
      function advance(){
        if(mode==='premature-end'&&current===1){current=7;render();return;}
        const index=sequence.indexOf(current);if(index<0||index===sequence.length-1)return;
        current=sequence[index+1];render();
        if(mode==='wrong-route'&&current===2)history.replaceState({},'', '/viewer/purchased/B999999999999/');
        if(mode==='half-spread'&&current===2){const slot=slots.find(s=>Number(s.dataset.page)===3);slot.querySelector('canvas').width=816;slot.querySelector('canvas').height=1200;}
      }
      window.addEventListener('resize',render);render();
      document.addEventListener('click',event=>{
        if(!document.body.classList.contains('toolbar-hidden')){document.body.classList.add('toolbar-hidden');return;}
        if(event.clientX<innerWidth*.18){document.body.classList.add('toolbar-hidden');advance();}
      });
      </script></body></html>"""
    return (
        body.replace("__TITLE__", TITLE)
        .replace("__SLOTS__", slots)
        .replace("__MODE__", json.dumps(mode))
    )


async def _run_neutral_core_flow(
    page: Page,
    tmp_path,
    *,
    mode: str = "normal",
    max_pages: int = 5,
    total_slots: int = 3,
) -> tuple[EbookJapanAdapter, object]:
    async def route_fixture(route) -> None:
        path = route.request.url.split("?", 1)[0]
        if path == LISTING_URL:
            account_mode = {
                "delayed-account": "delayed",
                "missing-account": "missing",
            }.get(mode, "present")
            await route.fulfill(status=200, content_type="text/html; charset=utf-8", body=_runner_listing_html(account_mode=account_mode))
        elif path == READER_URL:
            title = "Other Volume" if mode == "wrong-title" else TITLE
            reader_body = (
                _runner_seven_slot_reader_html(mode=mode)
                if total_slots == 7
                else _runner_reader_html(mode=mode)
            )
            await route.fulfill(
                status=200,
                content_type="text/html; charset=utf-8",
                body=reader_body.replace(TITLE, title),
            )
        else:
            await route.abort()

    await page.route("https://ebookjapan.yahoo.co.jp/**", route_fixture)
    adapter = EbookJapanAdapter()
    await adapter.configure_target_identity("A000083590", "neutral-work")
    config = RunConfig(
        site="ebookjapan",
        source_url=PRODUCT_URL,
        output_dir=tmp_path / "catalog-isolated" / "run",
        diagnostics_dir=tmp_path / "diagnostics-isolated",
        access_strategy="direct",
        page_turn_delay_ms=0,
        max_pages=max_pages,
        page_change_timeout_ms=500,
    )
    result = await CrawlerRunner(config).run(page, adapter)
    return adapter, result


async def test_core_runner_completes_neutral_owned_entry_capture_end_and_zip(
    browser_page: Page, tmp_path
) -> None:
    _adapter, result = await _run_neutral_core_flow(
        browser_page, tmp_path, total_slots=7, max_pages=10
    )

    assert result.stop_state.value == "end"
    assert len(result.pages) == 7
    output = tmp_path / "catalog-isolated" / "run"
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert [page["sequence"] for page in manifest["pages"]] == list(range(1, 8))
    assert {page["identity"]["source_id"] for page in manifest["pages"]} == {"A000083590"}
    assert manifest["pages"][0]["metadata"]["ebookjapan_capture_parts"][0]["side"] == "single"
    assert [page["metadata"].get("part") for page in manifest["pages"]] == [None, 1, 2, 1, 2, 1, 2]
    part_groups = [
        page["metadata"]["ebookjapan_capture_parts"]
        for page in manifest["pages"]
    ]
    assert [part_groups[index][0]["slot_id"] for index in (0, 1, 3, 5)] == [7, 6, 4, 2]
    assert part_groups[1] == part_groups[2]
    assert part_groups[3] == part_groups[4]
    assert part_groups[5] == part_groups[6]
    assert len({page["fingerprint"] for page in manifest["pages"]}) == 1
    assert all(
        page["metadata"]["ebookjapan_source_provenance"] == "UNKNOWN"
        for page in manifest["pages"]
    )

    packaged = package_crawl_output(
        output,
        {"title": TITLE, "genre": "neutral-test"},
        library_dir=tmp_path / "library-isolated",
    )
    assert packaged.archive_path.is_file()
    assert json.loads(packaged.status_path.read_text(encoding="utf-8"))["status"] == "completed"
    with zipfile.ZipFile(packaged.archive_path) as archive:
        assert sorted(archive.namelist()) == [f"page-{index:04d}.png" for index in range(1, 8)]


async def test_core_runner_waits_for_delayed_signed_in_account_shell(
    browser_page: Page, tmp_path
) -> None:
    _adapter, result = await _run_neutral_core_flow(
        browser_page, tmp_path, mode="delayed-account", max_pages=10
    )

    assert result.stop_state.value == "end"
    assert len(result.pages) == 3


async def test_core_runner_rejects_missing_account_shell_before_reader_entry(
    browser_page: Page, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from screenshot_crawler.site_adapters.ebookjapan import adapter as adapter_module

    monkeypatch.setattr(adapter_module, "_OWNERSHIP_SETTLE_SECONDS", 0.02)
    monkeypatch.setattr(adapter_module, "_OWNERSHIP_POLL_SECONDS", 0.002)
    with pytest.raises(UnknownPageStateError, match="account shell did not settle"):
        await _run_neutral_core_flow(
            browser_page, tmp_path, mode="missing-account", max_pages=10
        )
    assert browser_page.url == LISTING_URL


@pytest.mark.parametrize(
    ("mode", "max_pages", "error_type"),
    [
        ("normal", 1, MaxPagesExceededError),
        ("premature-end", 5, UnknownPageStateError),
        ("wrong-route", 5, UnknownPageStateError),
        ("wrong-title", 5, UnknownPageStateError),
        ("half-spread", 5, UnknownPageStateError),
    ],
)
async def test_core_runner_incomplete_neutral_flow_never_writes_completed_or_package(
    browser_page: Page,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    max_pages: int,
    error_type: type[BaseException],
) -> None:
    if mode == "half-spread":
        from screenshot_crawler.site_adapters.ebookjapan import adapter as adapter_module

        monkeypatch.setattr(adapter_module, "_FRAME_READY_WAIT_MS", 250)
        monkeypatch.setattr(adapter_module, "_FRAME_POLL_MS", 10)

    with pytest.raises(error_type):
        await _run_neutral_core_flow(
            browser_page, tmp_path, mode=mode, max_pages=max_pages
        )

    output = tmp_path / "catalog-isolated" / "run"
    manifest_path = output / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest.get("status") != "completed"
    assert not list(tmp_path.rglob("*.zip"))
    assert not (tmp_path / "crawl-status").exists()


async def test_frame_waits_past_placeholder_until_observed_full_transfer(browser_page: Page) -> None:
    await _open_reader(browser_page)

    placeholder = await _frame(browser_page)
    assert placeholder["status"] == "partial"

    await _draw_full_same_size(browser_page)
    content = await _frame(browser_page)
    assert content["status"] == "content"
    assert content["parts"][0]["drawReady"] is True
    assert content["parts"][0]["backingAspect"] == pytest.approx(0.68)


@pytest.mark.parametrize("overload", ["scaled", "cropped"])
async def test_unobserved_scaled_or_cropped_draw_does_not_mark_content_ready(
    browser_page: Page, overload: str
) -> None:
    await _open_reader(browser_page)
    await browser_page.evaluate(
        """overload=>{
          const source=document.createElement('canvas');source.width=408;source.height=600;
          source.getContext('2d').fillRect(0,0,408,600);
          const target=document.querySelector('.page-canvas');target.width=816;target.height=1200;
          const context=target.getContext('2d');
          if(overload==='scaled')context.drawImage(source,0,0,816,1200);
          else context.drawImage(source,0,0,204,300,0,0,816,1200);
        }""",
        overload,
    )
    assert (await _frame(browser_page))["status"] == "partial"


async def test_canvas_reset_and_observer_stop_invalidate_prior_full_draw(browser_page: Page) -> None:
    await _open_reader(browser_page)
    await _draw_full_same_size(browser_page)
    assert (await _frame(browser_page))["status"] == "content"

    await browser_page.evaluate(
        """async()=>{document.querySelector('.page-canvas').getContext('2d').reset();
          await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));}"""
    )
    assert (await _frame(browser_page))["status"] == "partial"

    await _draw_full_same_size(browser_page)
    assert (await _frame(browser_page))["status"] == "content"
    await browser_page.evaluate("window.__ejCaptureObserver.stop()")
    assert (await _frame(browser_page))["status"] == "observer-unavailable"


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ("wrong-title", "identity-mismatch"),
        ("wrong-route", "identity-mismatch"),
        ("changed-layout", "layout-mismatch"),
        ("replaced-slot", "slot-order-mismatch"),
    ],
)
async def test_pinned_reader_rejects_title_route_layout_and_slot_drift(
    browser_page: Page, change: str, expected: str
) -> None:
    await _open_reader(browser_page)
    await browser_page.evaluate(
        """change=>{
          if(change==='wrong-title')document.querySelector('.legacy-comic-header__title').textContent='Other Volume';
          if(change==='wrong-route')history.replaceState({},'', '/viewer/purchased/B999999999999/');
          if(change==='changed-layout')document.querySelector('.comic-viewer__scroll-container').classList.remove('comic-viewer__scroll-container--spread');
          if(change==='replaced-slot')document.querySelector('.comic-viewer__page-slot').replaceWith(document.querySelector('.comic-viewer__page-slot').cloneNode(true));
        }""",
        change,
    )
    assert (await _frame(browser_page))["status"] == expected


async def test_observed_native_end_key_rewinds_same_pinned_reader_to_first(browser_page: Page) -> None:
    await _open_reader(browser_page, current=2, total=2, slot_count=2)
    await _draw_full_same_size(browser_page)
    await browser_page.evaluate(
        """()=>{
          const range=document.querySelector('.seekbar__slider');
          range.addEventListener('keydown',event=>{
            if(event.key==='End'){
              document.querySelector('.legacy-comic-footer__page-output').textContent='1 / 2';
              document.querySelectorAll('.comic-viewer__page-slot')[1].style.display='none';
            }
          });
        }"""
    )
    assert (await _frame(browser_page, current=2))["status"] == "content"
    adapter = EbookJapanAdapter()
    adapter._owned_title = TITLE
    adapter._series_id = "134336"
    adapter._external_id = "A000083590"
    adapter._work_key = "neutral-work"
    adapter._reader_path = READER_PATH
    adapter._reader_total = 2

    await adapter._rewind_to_first(browser_page, expected_path=READER_PATH)

    first = await _frame(browser_page, current=1)
    assert first["status"] == "content"
    assert first["counter"] == {"current": 1, "total": 2}


async def test_viewport_fit_accepts_unchanged_full_draw_when_only_css_geometry_changes(
    browser_page: Page,
) -> None:
    await _open_reader(browser_page)
    await _draw_full_same_size(browser_page)
    adapter = EbookJapanAdapter()
    adapter._owned_title = TITLE
    adapter._series_id = "134336"
    adapter._external_id = "A000083590"
    adapter._work_key = "neutral-work"
    adapter._reader_path = READER_PATH
    adapter._reader_total = 1
    await adapter._pin_reader_anchor(
        browser_page, expected_path=READER_PATH, expected_current=1, expected_total=1
    )
    await browser_page.add_style_tag(
        content=".page-canvas{width:auto!important;height:100vh!important}"
    )
    before = await _frame(browser_page)
    before_part = before["parts"][0]
    assert before_part["drawReady"] is True
    assert before_part["drawGeneration"] == 1
    assert before_part["successfulDraws"] == 1
    assert before_part["cssRect"]["height"] == 986
    assert before_part["cssRect"]["height"] != before_part["backingHeight"]

    fitted = await adapter._ensure_native_css_viewport(
        browser_page, expected_path=READER_PATH, current=1, total=1
    )
    after = await _frame(browser_page)
    after_part = after["parts"][0]

    assert fitted["status"] == "content"
    assert fitted["viewport"] == {"width": 816, "height": 600}
    assert adapter._capture_viewport == (816, 600)
    assert after_part["slotId"] == before_part["slotId"]
    assert after_part["canvasId"] == before_part["canvasId"]
    assert after_part["backingWidth"] == before_part["backingWidth"] == 408
    assert after_part["backingHeight"] == before_part["backingHeight"] == 600
    assert after_part["cssRect"]["width"] == 408
    assert after_part["cssRect"]["height"] == 600
    assert after_part["cssRect"]["width"] == after_part["backingWidth"]
    assert after_part["cssRect"]["height"] == after_part["backingHeight"]
    assert after_part["drawReady"] is True
    assert after_part["drawGeneration"] == before_part["drawGeneration"]
    assert after_part["successfulDraws"] == before_part["successfulDraws"]
    assert after_part["mutationCount"] == before_part["mutationCount"]
    assert after_part["resetObserved"] is False
    assert adapter._seen_slot_ids == set()


async def test_viewport_fit_rejects_canvas_reset_without_redraw(
    browser_page: Page, monkeypatch: pytest.MonkeyPatch
) -> None:
    from screenshot_crawler.site_adapters.ebookjapan import adapter as adapter_module

    monkeypatch.setattr(adapter_module, "_FRAME_READY_WAIT_MS", 250)
    monkeypatch.setattr(adapter_module, "_FRAME_POLL_MS", 10)
    await _open_reader(browser_page)
    await _draw_full_same_size(browser_page)
    adapter = EbookJapanAdapter()
    adapter._owned_title = TITLE
    adapter._series_id = "134336"
    adapter._external_id = "A000083590"
    adapter._work_key = "neutral-work"
    adapter._reader_path = READER_PATH
    adapter._reader_total = 1
    await adapter._pin_reader_anchor(
        browser_page, expected_path=READER_PATH, expected_current=1, expected_total=1
    )
    viewport_before = await browser_page.evaluate("() => ({width:innerWidth,height:innerHeight})")
    assert viewport_before != {"width": 816, "height": 600}
    original_set_viewport_size = browser_page.set_viewport_size

    async def reset_after_viewport_fit(size: dict[str, int]) -> None:
        await original_set_viewport_size(size)
        await browser_page.evaluate(
            "document.querySelector('.page-canvas').getContext('2d').reset()"
        )

    monkeypatch.setattr(browser_page, "set_viewport_size", reset_after_viewport_fit)
    with pytest.raises(UnknownPageStateError, match="did not redraw"):
        await adapter._ensure_native_css_viewport(
            browser_page, expected_path=READER_PATH, current=1, total=1
        )

    frame = await _frame(browser_page)
    assert frame["status"] == "partial"
    assert frame["parts"][0]["resetObserved"] is True
    assert frame["parts"][0]["drawReady"] is False
    assert adapter._capture_viewport is None
    assert adapter._seen_slot_ids == set()
    assert adapter._captured_slot_order == []


async def test_capture_hides_toolbar_before_fitting_and_keeps_the_entry_slot(
    browser_page: Page,
) -> None:
    await _open_reader(browser_page, current=1, total=3, slot_count=3)
    await _draw_full_same_size(browser_page)
    adapter = EbookJapanAdapter()
    adapter._page = browser_page
    adapter._owned_title = TITLE
    adapter._series_id = "134336"
    adapter._external_id = "A000083590"
    adapter._work_key = "neutral-work"
    adapter._reader_path = READER_PATH
    adapter._reader_total = 3
    adapter._last_native_counter = 1
    await browser_page.evaluate("() => {window.__ejCenterClickAdvances=true}")
    await adapter._pin_reader_anchor(
        browser_page, expected_path=READER_PATH, expected_current=1, expected_total=3
    )
    before = await _frame(browser_page)
    assert before["viewport"] == {"width": 1906, "height": 986}
    assert before["parts"][0]["cssRect"]["left"] == pytest.approx(282.52, abs=1)
    assert before["parts"][0]["cssRect"]["width"] == pytest.approx(670.48, abs=1)
    assert before["parts"][0]["drawReady"] is True
    identity = await adapter.get_content_identity(browser_page)

    captures = await adapter.capture_page(browser_page)
    after = await _frame(browser_page)
    counter_text = await browser_page.locator(
        ".legacy-comic-footer__page-output"
    ).text_content()

    assert identity.source_id == "A000083590"
    assert len(captures) == 1
    assert (captures[0].width, captures[0].height) == (408, 600)
    assert after["status"] == "content"
    assert after["toolbarVisible"] is False
    assert after["viewport"] == {"width": 816, "height": 600}
    assert after["parts"][0]["slotId"] == before["parts"][0]["slotId"]
    assert counter_text == "1 / 3"
    assert adapter._seen_slot_ids == {before["parts"][0]["slotId"]}


async def test_fitted_cover_center_is_a_page_turn_region_in_the_neutral_fixture(
    browser_page: Page,
) -> None:
    await _open_reader(browser_page, current=1, total=3, slot_count=3)
    await _draw_full_same_size(browser_page)
    adapter = EbookJapanAdapter()
    adapter._page = browser_page
    adapter._owned_title = TITLE
    adapter._series_id = "134336"
    adapter._external_id = "A000083590"
    adapter._work_key = "neutral-work"
    adapter._reader_path = READER_PATH
    adapter._reader_total = 3
    await adapter._pin_reader_anchor(
        browser_page, expected_path=READER_PATH, expected_current=1, expected_total=3
    )
    await browser_page.evaluate("() => {window.__ejCenterClickAdvances=true}")

    fitted = await adapter._ensure_native_css_viewport(
        browser_page, expected_path=READER_PATH, current=1, total=3
    )
    assert fitted["viewport"] == {"width": 816, "height": 600}
    with pytest.raises(UnknownPageStateError, match="unverified at this viewport geometry"):
        await adapter._hide_toolbar_for_capture(
            browser_page,
            frame=fitted,
            expected_path=READER_PATH,
            current=1,
            total=3,
        )
    assert await browser_page.locator(
        ".legacy-comic-footer__page-output"
    ).text_content() == "1 / 3"
    canvas = browser_page.locator(".page-canvas").nth(2)
    box = await canvas.bounding_box()
    assert box is not None
    center_x = box["x"] + box["width"] / 2
    assert center_x / 816 == pytest.approx(0.25)
    await browser_page.mouse.click(center_x, box["y"] + box["height"] / 2)

    turned = await browser_page.locator(
        ".legacy-comic-footer__page-output"
    ).text_content()
    assert turned == "2 / 3"
    assert await browser_page.locator(".comic-viewer__page-slot:visible").count() == 2
    assert adapter._seen_slot_ids == set()


async def test_capture_page_returns_decoded_css_native_png_after_atomic_two_sample_check(
    browser_page: Page,
) -> None:
    await _open_reader(browser_page)
    await _draw_full_same_size(browser_page)
    adapter = EbookJapanAdapter()
    adapter._owned_title = TITLE
    adapter._series_id = "134336"
    adapter._external_id = "A000083590"
    adapter._work_key = "neutral-work"
    adapter._reader_path = READER_PATH
    adapter._reader_total = 1
    adapter._last_native_counter = 1
    await _redraw_on_resize(browser_page)
    await adapter._pin_reader_anchor(
        browser_page, expected_path=READER_PATH, expected_current=1, expected_total=1
    )
    identity = await adapter.get_content_identity(browser_page)
    captures = await adapter.capture_page(browser_page)

    assert identity.page_number is None
    assert identity.source_id == "A000083590"
    assert len(captures) == 1
    assert captures[0].data.startswith(b"\x89PNG\r\n\x1a\n")
    assert (captures[0].width, captures[0].height) == (408, 600)
    with Image.open(io.BytesIO(captures[0].data)) as image:
        assert image.convert("RGBA").getpixel((204, 300)) == (0, 0, 0, 255)
    assert adapter._seen_slot_ids == {1}
    debug = await adapter.collect_debug_metadata(browser_page)
    assert debug["capture_method"] == "D_compositor_png"
    assert debug["ebookjapan_capture_parts"][0]["side"] == "single"
    assert debug["ebookjapan_capture_parts"][0]["native_page_number"] is None


async def test_capture_spread_is_atomic_and_emits_physical_right_to_left_parts(browser_page: Page) -> None:
    await _open_reader(browser_page, current=2, total=2, slot_count=2)
    await _draw_full_same_size(browser_page)
    adapter = EbookJapanAdapter()
    adapter._owned_title = TITLE
    adapter._series_id = "115888"
    adapter._external_id = "A000039104"
    adapter._work_key = "neutral-work"
    adapter._reader_path = READER_PATH
    adapter._reader_total = 2
    adapter._last_native_counter = 2
    adapter._expected_current = 2
    adapter._seen_slot_ids = {3}
    adapter._captured_slot_order = [3]
    adapter._next_dom_ordinal = 1
    await _redraw_on_resize(browser_page)
    await adapter._pin_reader_anchor(
        browser_page, expected_path=READER_PATH, expected_current=2, expected_total=2
    )
    await adapter.get_content_identity(browser_page)
    await browser_page.evaluate(
        "() => {document.querySelector('.legacy-comic-header').hidden=true;document.querySelector('.legacy-comic-footer').hidden=true;}"
    )

    captures = await adapter.capture_page(browser_page)

    assert len(captures) == 2
    assert adapter._captured_slot_order == [3, 2, 1]
    debug = await adapter.collect_debug_metadata(browser_page)
    parts = debug["ebookjapan_capture_parts"]
    assert [part["side"] for part in parts] == ["right", "left"]
    assert [part["slot_ordinal"] for part in parts] == [1, 0]


async def test_capture_page_is_atomic_when_one_spread_part_is_not_ready(
    browser_page: Page, monkeypatch
) -> None:
    from screenshot_crawler.site_adapters.ebookjapan import adapter as adapter_module

    monkeypatch.setattr(adapter_module, "_FRAME_READY_WAIT_MS", 1_000)
    await _open_reader(browser_page, current=2, total=2, slot_count=2)
    await _draw_full_same_size(browser_page)
    adapter = EbookJapanAdapter()
    adapter._owned_title = TITLE
    adapter._series_id = "115888"
    adapter._external_id = "A000039104"
    adapter._work_key = "neutral-work"
    adapter._reader_path = READER_PATH
    adapter._reader_total = 2
    adapter._last_native_counter = 2
    adapter._expected_current = 2
    adapter._seen_slot_ids = {3}
    adapter._captured_slot_order = [3]
    adapter._next_dom_ordinal = 1
    await _redraw_on_resize(browser_page)
    await adapter._pin_reader_anchor(
        browser_page, expected_path=READER_PATH, expected_current=2, expected_total=2
    )
    await adapter.get_content_identity(browser_page)
    await browser_page.evaluate(
        "() => {document.querySelector('.legacy-comic-header').hidden=true;document.querySelector('.legacy-comic-footer').hidden=true;}"
    )
    await browser_page.evaluate(
        """()=>{const canvas=document.querySelectorAll('.page-canvas')[1];canvas.width=300;canvas.height=150;}"""
    )

    with pytest.raises(UnknownPageStateError):
        await adapter.capture_page(browser_page)
    assert adapter._seen_slot_ids == {3}
    assert adapter._captured_slot_order == [3]


@pytest.mark.parametrize(
    "surface_issue",
    [
        "opaque-overlay",
        "pointer-events-none-overlay",
        "small-banner-between-samples",
        "clipped-ancestor",
        "transformed-canvas",
        "ancestor-opacity",
        "ancestor-rotation",
        "offscreen-host-fixed-pseudo",
        "offscreen-host-outset-shadow",
        "canvas-outline-outset",
        "ancestor-outline-outset",
    ],
)
async def test_capture_rejects_occluded_or_clipped_surfaces_without_coverage_commit(
    browser_page: Page, surface_issue: str
) -> None:
    await _open_reader(browser_page)
    await _draw_full_same_size(browser_page)
    adapter = EbookJapanAdapter()
    adapter._owned_title = TITLE
    adapter._series_id = "134336"
    adapter._external_id = "A000083590"
    adapter._work_key = "neutral-work"
    adapter._reader_path = READER_PATH
    adapter._reader_total = 1
    adapter._last_native_counter = 1
    await _redraw_on_resize(browser_page)
    await adapter._pin_reader_anchor(
        browser_page, expected_path=READER_PATH, expected_current=1, expected_total=1
    )
    await adapter.get_content_identity(browser_page)
    frame = await _frame(browser_page)
    await adapter._hide_toolbar_for_capture(
        browser_page, frame=frame, expected_path=READER_PATH, current=1, total=1
    )
    await browser_page.evaluate(
        """issue=>{
          if(issue==='opaque-overlay'){
            const overlay=document.createElement('div');overlay.id='opaque-overlay';
            overlay.style='position:fixed;inset:0;z-index:99999;background:rgb(255,0,0)';
            document.body.append(overlay);
          }else if(issue==='pointer-events-none-overlay'){
            const overlay=document.createElement('div');overlay.id='opaque-overlay';
            overlay.style='position:fixed;inset:0;z-index:99999;background:rgb(255,0,0);pointer-events:none';
            document.body.append(overlay);
          }else if(issue==='small-banner-between-samples'){
            const overlay=document.createElement('div');overlay.id='small-banner';
            overlay.style='position:fixed;left:70px;top:75px;width:20px;height:20px;z-index:99999;background:rgb(255,0,0);pointer-events:none';
            document.body.append(overlay);
          }else if(issue==='clipped-ancestor'){
            const slot=document.querySelector('.comic-viewer__page-slot');
            slot.style.width='300px';slot.style.overflow='hidden';
          }else if(issue==='transformed-canvas'){
            document.querySelector('.page-canvas').style.transform='rotate(180deg)';
          }else if(issue==='ancestor-opacity'){
            document.querySelector('.comic-viewer__page-slot').style.opacity='.5';
          }else if(issue==='offscreen-host-fixed-pseudo'){
            const host=document.createElement('div');host.style='position:absolute;left:600px;top:0;width:10px;height:10px';
            const style=document.createElement('style');style.textContent='div#outset-host::before{content:"";position:fixed;inset:0;background:rgb(255,0,0);pointer-events:none}';
            host.id='outset-host';host.append(style);document.body.append(host);
          }else if(issue==='offscreen-host-outset-shadow'){
            const host=document.createElement('div');host.style='position:fixed;left:600px;top:75px;width:20px;height:20px;box-shadow:-530px 0 rgb(255,0,0);pointer-events:none';
            document.body.append(host);
          }else if(issue==='canvas-outline-outset'){
            const canvas=document.querySelector('.page-canvas');canvas.style.outline='20px solid rgb(255,0,0)';canvas.style.outlineOffset='-20px';
          }else if(issue==='ancestor-outline-outset'){
            const slot=document.querySelector('.comic-viewer__page-slot');slot.style.outline='20px solid rgb(255,0,0)';slot.style.outlineOffset='-20px';
          }else{
            document.querySelector('.comic-viewer__page-slot').style.transform='rotate(180deg)';
          }
        }""",
        surface_issue,
    )

    with pytest.raises(UnknownPageStateError):
        await adapter.capture_page(browser_page)
    assert adapter._seen_slot_ids == set()
    assert adapter._captured_slot_order == []


async def test_unknown_terminal_notice_is_not_classified_as_end(browser_page: Page) -> None:
    await _open_reader(browser_page)
    await browser_page.evaluate(
        """()=>{
          document.querySelectorAll('.comic-viewer__page-slot').forEach(slot=>slot.style.display='none');
          document.querySelector('.book-last-dead-end__next').style.display='block';
        }"""
    )
    assert (await _frame(browser_page))["status"] == "end"
    await browser_page.evaluate(
        """()=>{document.querySelector('.book-last-dead-end__next').textContent+=' UNKNOWN NOTICE';}"""
    )
    assert (await _frame(browser_page))["status"] == "unknown-terminal-marker"


async def test_adapter_traverses_all_pinned_slots_before_accepting_neutral_end(
    browser_page: Page,
) -> None:
    await _open_reader(browser_page, current=1, total=3, slot_count=3)
    await _draw_full_same_size(browser_page)
    adapter = EbookJapanAdapter()
    adapter._page = browser_page
    adapter._owned_title = TITLE
    adapter._series_id = "134336"
    adapter._external_id = "A000083590"
    adapter._work_key = "neutral-work"
    adapter._reader_path = READER_PATH
    adapter._reader_total = 3
    adapter._last_native_counter = 1
    adapter._expected_current = 1
    await _redraw_on_resize(browser_page)

    await adapter._pin_reader_anchor(
        browser_page, expected_path=READER_PATH, expected_current=1, expected_total=3
    )
    assert await adapter.detect_state(browser_page) == "content"
    first_identity = await adapter.get_content_identity(browser_page)
    first = await adapter.capture_page(browser_page)
    assert first_identity.page_number is None
    assert len(first) == 1
    assert adapter._last_native_counter is None

    await adapter.go_next(browser_page)
    await adapter.wait_for_change(browser_page, first_identity)
    assert await adapter.detect_state(browser_page) == "content"
    spread_identity = await adapter.get_content_identity(browser_page)
    assert spread_identity.page_number is None
    assert spread_identity.page_id != first_identity.page_id
    spread = await adapter.capture_page(browser_page)
    assert len(spread) == 2
    assert adapter._captured_slot_order == [3, 2, 1]
    assert adapter._capture_coverage_complete() is True
    assert adapter._last_native_counter is None

    await adapter.go_next(browser_page)
    terminal_snapshot = await browser_page.evaluate(FRAME_STATE_JS, {"expectedCurrent": 2})
    assert terminal_snapshot["status"] == "end", terminal_snapshot
    await adapter.wait_for_change(browser_page, spread_identity)
    assert await adapter.detect_state(browser_page) == "end"
    assert adapter._terminal_end_verified is True


async def test_reader_end_is_rejected_until_every_frozen_slot_was_captured(
    browser_page: Page,
) -> None:
    await _open_reader(browser_page, current=1, total=3, slot_count=3)
    await _draw_full_same_size(browser_page)
    adapter = EbookJapanAdapter()
    adapter._page = browser_page
    adapter._owned_title = TITLE
    adapter._series_id = "134336"
    adapter._external_id = "A000083590"
    adapter._work_key = "neutral-work"
    adapter._reader_path = READER_PATH
    adapter._reader_total = 3
    await _redraw_on_resize(browser_page)
    await adapter._pin_reader_anchor(
        browser_page, expected_path=READER_PATH, expected_current=1, expected_total=3
    )
    await browser_page.evaluate(
        """()=>{
          document.querySelectorAll('.comic-viewer__page-slot').forEach(slot=>slot.style.display='none');
          document.querySelector('.book-last-dead-end__next').style.display='block';
        }"""
    )

    with pytest.raises(UnknownPageStateError, match="before complete ordered"):
        await adapter.detect_state(browser_page)
    assert adapter._seen_slot_ids == set()
    assert adapter._terminal_end_verified is False


async def test_normal_advance_rejects_route_drift_and_skipped_slot_order(
    browser_page: Page, monkeypatch
) -> None:
    from screenshot_crawler.site_adapters.ebookjapan import adapter as adapter_module

    await _open_reader(browser_page, current=1, total=3, slot_count=3)
    await _draw_full_same_size(browser_page)
    adapter = EbookJapanAdapter()
    adapter._page = browser_page
    adapter._owned_title = TITLE
    adapter._series_id = "134336"
    adapter._external_id = "A000083590"
    adapter._work_key = "neutral-work"
    adapter._reader_path = READER_PATH
    adapter._reader_total = 3
    await _redraw_on_resize(browser_page)
    await adapter._pin_reader_anchor(
        browser_page, expected_path=READER_PATH, expected_current=1, expected_total=3
    )
    first_identity = await adapter.get_content_identity(browser_page)
    await adapter.capture_page(browser_page)
    await adapter.go_next(browser_page)
    await browser_page.evaluate("history.replaceState({},'', '/viewer/purchased/B999999999999/')")
    with pytest.raises(UnknownPageStateError, match="identity"):
        await adapter.wait_for_change(browser_page, first_identity)

    # A second fresh Reader changes the physical RTL order so the observed
    # next spread starts at the wrong frozen DOM ordinal.
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _open_reader(browser_page, current=1, total=3, slot_count=3)
    await _draw_full_same_size(browser_page)
    adapter = EbookJapanAdapter()
    adapter._page = browser_page
    adapter._owned_title = TITLE
    adapter._series_id = "134336"
    adapter._external_id = "A000083590"
    adapter._work_key = "neutral-work"
    adapter._reader_path = READER_PATH
    adapter._reader_total = 3
    await _redraw_on_resize(browser_page)
    await adapter._pin_reader_anchor(
        browser_page, expected_path=READER_PATH, expected_current=1, expected_total=3
    )
    first_identity = await adapter.get_content_identity(browser_page)
    await adapter.capture_page(browser_page)
    await adapter.go_next(browser_page)
    await browser_page.evaluate(
        """()=>{
          const slots=[...document.querySelectorAll('.comic-viewer__page-slot')];
          slots[0].style.left='408px';slots[1].style.left='0px';
        }"""
    )
    monkeypatch.setattr(adapter_module, "_FRAME_READY_WAIT_MS", 1_000)
    with pytest.raises(UnknownPageStateError, match="skip|revisited|slot"):
        await adapter.wait_for_change(browser_page, first_identity)
    assert adapter._captured_slot_order == [3]
