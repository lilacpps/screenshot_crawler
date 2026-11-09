from __future__ import annotations

import asyncio
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
NEW_ARRIVAL_MARKUP = (
    '<section class="recommend-grid book-last-dead-end__section book-last-dead-end__new-arrival">'
    '<a class="recommend-grid__heading recommend-grid__heading--more" href="/books/134336/A000000011/">More</a>'
    '<ul class="recommend-grid__list"><li class="recommend-grid__item">'
    '<a class="recommend-grid__link" href="/books/134336/A000000012/">Related</a>'
    '</li></ul></section>'
)


@pytest_asyncio.fixture(loop_scope="module")
async def browser_page(integration_browser: Browser) -> Page:
    context = await integration_browser.new_context(viewport={"width": 1906, "height": 986})
    page = await context.new_page()
    try:
        yield page
    finally:
        await page.close()
        await context.close()


def _html(
    *, current: int = 1, total: int = 1, slot_count: int = 1,
    terminal_profile: str = "angel",
) -> str:
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
    if terminal_profile not in {"angel", "angel-observed", "angel-new-arrival", "muda"}:
        raise ValueError("unsupported neutral terminal profile")
    viewer_open = '<div class="comic-viewer">' if terminal_profile in {"muda", "angel-observed"} else ""
    viewer_close = "</div>" if terminal_profile in {"muda", "angel-observed"} else ""
    header_controls = (
        '<div class="legacy-comic-header__bar is-entrance-delayed"><button class="close-button">Close</button>'
        '<div class="legacy-comic-header__menu legacy-comic-header__menu--pc">'
        '<button class="contents-button">Contents</button><button class="settings-button">Settings</button></div></div>'
        if terminal_profile in {"muda", "angel-observed"} else ""
    )
    terminal_markup = (
        '<div class="comic-viewer__custom-cell comic-viewer__custom-cell--interactive" style="display:none"><div class="viewer-liber__viewer-last-cell">'
        '<div class="viewer-last-shell" style="display:none">'
        '<div class="book-last" style="position:fixed;left:30vw;top:80px;width:40vw;height:1400px;overflow:auto;background:#eee">'
        '<div class="book-last__inner">'
        '<div class="review-module book-last__review"><button class="review-module__action">Review</button></div>'
        '<div class="next-item book-last__next"><div class="next-item__outline"><button class="next-item__rating">Rate</button></div></div>'
        '<div class="cta-button book-last__cta"><div class="cta-button__row"><div class="cta-button__primary"><button class="cta-button__read-btn">Read</button></div></div></div>'
        '<div class="banner-group book-last__banner-group"><div class="matilda-module"><a class="matilda-banner" href="/books/134336/A000000005/" target="_blank">Offer</a></div><button class="banner__row--lottery">Lottery</button><button class="banner__row--line-coupon">Coupon</button></div>'
        '<section class="recommend-grid book-last__section book-last__i2i"><ul class="recommend-grid__list"><li class="recommend-grid__item"><a class="recommend-grid__link" href="/books/134336/A000000001/">Related</a></li></ul></section>'
        '<section class="recommend-grid book-last__section book-last__author"><a class="recommend-grid__heading recommend-grid__heading--more" href="/books/134336/A000000004/">More</a><ul class="recommend-grid__list"><li class="recommend-grid__item"><a class="recommend-grid__link" href="/books/134336/A000000002/">Related</a></li></ul></section>'
        '<section class="recommend-grid book-last__section book-last__for-you"><ul class="recommend-grid__list"><li class="recommend-grid__item"><a class="recommend-grid__link" href="/books/134336/A000000003/">Related</a></li></ul></section>'
        '</div></div></div></div></div>'
        if terminal_profile == "muda" else ""
    )
    if terminal_profile in {"angel", "angel-observed", "angel-new-arrival"}:
        observed_lottery = (
            '<button class="banner__row banner__row--lottery">Lottery</button>'
            if terminal_profile == "angel-observed" else ""
        )
        new_arrival = NEW_ARRIVAL_MARKUP if terminal_profile == "angel-new-arrival" else ""
        terminal_markup = (
            '<div class="comic-viewer__custom-cell comic-viewer__custom-cell--interactive" style="display:none"><div class="viewer-liber__viewer-last-cell">'
            '<div class="viewer-last-shell" style="display:none"><div class="book-last-dead-end" style="position:fixed;left:30vw;top:80px;width:40vw;height:300px;background:#eee">'
            '<div class="book-last-dead-end__inner">'
            '<div class="review-module book-last-dead-end__review"><button class="review-module__action">Review</button></div>'
            '<div class="banner-group book-last-dead-end__banner-group"><button class="banner__row banner__row--line-coupon">Coupon</button>'
            f'{observed_lottery}</div>'
            '<section class="recommend-grid book-last-dead-end__section book-last-dead-end__author"><a class="recommend-grid__heading recommend-grid__heading--more" href="/books/134336/A000000001/">More</a><ul class="recommend-grid__list"><li class="recommend-grid__item"><a class="recommend-grid__link" href="/books/134336/A000000002/">Related</a></li></ul></section>'
            '<section class="recommend-grid book-last-dead-end__section book-last-dead-end__i2i"><ul class="recommend-grid__list"><li class="recommend-grid__item"><a class="recommend-grid__link" href="/books/134336/A000000003/">Related</a></li></ul></section>'
            f'{new_arrival}'
            '<div class="next-item book-last-dead-end__next">&#12371;&#12398;&#20316;&#21697;&#12399;&#12371;&#12371;&#12414;&#12391;&#12391;&#12377;</div>'
            '</div></div></div></div></div>'
        )
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
      .legacy-comic-header,.legacy-comic-footer{{position:fixed;left:0;width:100%;height:24px;z-index:20;background:#ddd}}
      .legacy-comic-header{{top:0}} .legacy-comic-footer{{bottom:0}}
      .book-last__author{{margin-top:1050px}}
      body.toolbar-hidden .legacy-comic-header,
      body.toolbar-hidden .legacy-comic-footer,
      body.toolbar-hidden .seekbar__slider{{display:none}}
      {'.book-last__author{margin-top:0}' if terminal_profile == 'muda' else ''}
      </style></head><body>
      {viewer_open}
      <header class="legacy-comic-header"><span class="legacy-comic-header__title">{TITLE}</span>{header_controls}</header>
      <footer class="legacy-comic-footer"><span class="legacy-comic-footer__page-output">{current} / {total}</span></footer>
      <div class="comic-viewer__scroll-container comic-viewer__scroll-container--horizontal-rtl comic-viewer__scroll-container--spread">
        {''.join(slots)}{terminal_markup}
      </div>
      {viewer_close}
      <input type="range" class="seekbar__slider" min="0" max="{total - 1}" value="0" style="position:fixed;left:0;top:650px">
      <script>
      let fixtureCurrent={current};
      window.__ejToggleKeyCount=0;
      document.addEventListener('keydown',event=>{{
        if(event.key.toLowerCase()!=='i')return;
        window.__ejToggleKeyCount++;
        if(window.__ejIgnoreToggle||event.target!==document.body)return;
        const hidden=document.body.classList.toggle('toolbar-hidden');
        document.querySelector('.legacy-comic-header').hidden=hidden;
        document.querySelector('.legacy-comic-footer').hidden=hidden;
        document.querySelector('.seekbar__slider').style.display=hidden?'none':'';
      }});
      document.addEventListener('click',event=>{{
        if(!(event.target instanceof HTMLCanvasElement))return;
        const header=document.querySelector('.legacy-comic-header'),footer=document.querySelector('.legacy-comic-footer');
        if(!header.hidden||!footer.hidden){{
          if(window.__ejCenterClickAdvances&&fixtureCurrent===1&&event.clientX/innerWidth<=.25&&{total}===3){{
            fixtureCurrent=2;header.hidden=true;footer.hidden=true;
            document.querySelector('.seekbar__slider').style.display='none';
            document.querySelector('.legacy-comic-footer__page-output').textContent='2 / {total}';
            const slots=[...document.querySelectorAll('.comic-viewer__page-slot')];
            slots[0].style.display='block';slots[1].style.display='block';slots[2].style.display='none';return;
          }}
          header.hidden=true;footer.hidden=true;
          document.querySelector('.seekbar__slider').style.display='none';
          return;
        }}
        if(event.clientX>16||{total}!==3)return;
        if(fixtureCurrent===1){{
          fixtureCurrent=2;document.querySelector('.legacy-comic-footer__page-output').textContent='2 / {total}';
          const slots=[...document.querySelectorAll('.comic-viewer__page-slot')];
          slots[0].style.display='block';slots[0].style.left='0px';
          slots[1].style.display='block';slots[1].style.left=slots[1].querySelector('canvas').width+'px';
          slots[2].style.display='none';
        }}else if(fixtureCurrent===2){{
          fixtureCurrent=3;document.querySelectorAll('.comic-viewer__page-slot').forEach(slot=>slot.style.display='none');
          document.querySelector('.legacy-comic-footer__page-output').textContent='3 / {total}';
          document.querySelector('.seekbar__slider').style.display='none';
          document.querySelector('.comic-viewer__custom-cell--interactive').style.display='block';
          const terminalShell=document.querySelector('.viewer-last-shell');
          if(window.__ejFixtureMode==='delayed-terminal'){{terminalShell.style.display='none';setTimeout(()=>terminalShell.style.display='block',250);}}
          else if(window.__ejFixtureMode==='opacity-hidden-terminal'){{terminalShell.style.display='block';terminalShell.style.opacity='0';setTimeout(()=>terminalShell.style.opacity='1',250);}}
          else terminalShell.style.display='block';
          if('{terminal_profile}'==='muda'||'{terminal_profile}'==='angel-observed'){{document.body.classList.remove('toolbar-hidden');document.querySelector('.legacy-comic-header').hidden=false;document.querySelector('.legacy-comic-footer').hidden=false;}}
          if('{terminal_profile}'==='muda'&&window.__ejFixtureMode==='muda-transient-header'){{
            const header=document.querySelector('.legacy-comic-header'),footer=document.querySelector('.legacy-comic-footer');
            const parent=header.parentNode,next=header.nextSibling,title=header.querySelector('.legacy-comic-header__title');
            const counter=footer.querySelector('.legacy-comic-footer__page-output');
            const controls=[...header.querySelectorAll('button.close-button,button.contents-button,button.settings-button')];
            header.remove();footer.hidden=true;
            setTimeout(()=>{{parent.insertBefore(header,next);header.hidden=false;footer.hidden=false;
              title.style.visibility='hidden';counter.style.visibility='hidden';controls.forEach(button=>button.style.visibility='hidden');}},260);
            setTimeout(()=>{{title.style.visibility='';counter.style.visibility='';controls.forEach(button=>button.style.visibility='');}},650);
          }}
          if('{terminal_profile}'==='muda'&&window.__ejFixtureMode==='muda-persistent-partial-header'){{
            const settings=document.querySelector('.legacy-comic-header button.settings-button');
            if(settings)settings.style.visibility='hidden';
          }}
          if('{terminal_profile}'==='angel-observed'&&['transient-observed-terminal','permanent-hidden-observed-terminal'].includes(window.__ejFixtureMode)){{
            const title=document.querySelector('.legacy-comic-header__title');
            const counter=document.querySelector('.legacy-comic-footer__page-output');
            const controls=[...document.querySelectorAll('.legacy-comic-header button.close-button,.legacy-comic-header button.contents-button,.legacy-comic-header button.settings-button')];
            title.style.visibility='hidden';counter.style.visibility='hidden';controls.forEach(control=>control.style.visibility='hidden');
            const hydratingAction=document.createElement('button');
            hydratingAction.className='fixture-hydrating-action';
            const hydratingModule=document.querySelector('.book-last-dead-end__author');
            const moduleParent=hydratingModule?.parentElement||null;
            const moduleNext=hydratingModule?.nextSibling||null;
            if(window.__ejFixtureMode==='transient-observed-terminal'){{
              document.querySelector('.book-last-dead-end__inner').append(hydratingAction);
              setTimeout(()=>hydratingModule?.remove(),100);
              setTimeout(()=>{{
                title.style.visibility='';controls.forEach(control=>control.style.visibility='');
                if(hydratingModule&&moduleParent)moduleParent.insertBefore(hydratingModule,moduleNext);
                hydratingAction.remove();
              }},350);
            }}
          }}
        }}
      }});
      </script>
    </body></html>"""


async def _open_reader(
    page: Page, *, current: int = 1, total: int = 1, slot_count: int = 1,
    terminal_profile: str = "angel",
) -> None:
    await page.context.route(
        "https://ebookjapan.yahoo.co.jp/**",
        lambda route: route.fulfill(
            status=200,
            content_type="text/html",
            body=_html(current=current, total=total, slot_count=slot_count, terminal_profile=terminal_profile),
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


async def _draw_full_same_size(
    page: Page, *, width: int = 816, height: int = 1200
) -> None:
    await page.evaluate(
        """async({width,height}) => {
          const source=document.createElement('canvas');source.width=width;source.height=height;
          source.getContext('2d').fillRect(0,0,width,height);
          for(const target of document.querySelectorAll('.page-canvas')){
            target.width=width;target.height=height;
            target.getContext('2d').drawImage(source,0,0);
          }
          await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
        }""",
        {"width": width, "height": height},
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


async def _toolbar_shortcut_fixture(page: Page) -> tuple[EbookJapanAdapter, dict[str, object]]:
    await _open_reader(page, current=1, total=3, slot_count=3)
    await _draw_full_same_size(page)
    adapter = EbookJapanAdapter()
    adapter._page = page
    adapter._owned_title = TITLE
    adapter._series_id = "134336"
    adapter._external_id = "A000083590"
    adapter._work_key = "neutral-work"
    adapter._reader_path = READER_PATH
    adapter._reader_total = 3
    adapter._last_native_counter = 1
    await adapter._pin_reader_anchor(
        page, expected_path=READER_PATH, expected_current=1, expected_total=3
    )
    return adapter, await _frame(page)


async def _capture_neutral_cover(page: Page) -> tuple[EbookJapanAdapter, object]:
    await _open_reader(page, current=1, total=3, slot_count=3)
    await _draw_full_same_size(page)
    adapter = EbookJapanAdapter()
    adapter._page = page
    adapter._owned_title = TITLE
    adapter._series_id = "134336"
    adapter._external_id = "A000083590"
    adapter._work_key = "neutral-work"
    adapter._reader_path = READER_PATH
    adapter._reader_total = 3
    adapter._expected_current = 1
    await _redraw_on_resize(page)
    await adapter._pin_reader_anchor(
        page, expected_path=READER_PATH, expected_current=1, expected_total=3
    )
    identity = await adapter.get_content_identity(page)
    await adapter.capture_page(page)
    await page.evaluate("window.__fixtureClickCount=0;document.addEventListener('click',()=>window.__fixtureClickCount++)")
    return adapter, identity


async def _show_terminal_profile(page: Page, profile: str) -> dict[str, object]:
    await _open_reader(page, current=3, total=3, slot_count=3, terminal_profile=profile)
    await page.evaluate(
        """profile=>{
          document.querySelectorAll('.comic-viewer__page-slot').forEach(slot=>slot.style.display='none');
          document.querySelector('.legacy-comic-footer__page-output').textContent='3 / 3';
          document.querySelector('.seekbar__slider').style.display='none';
          document.querySelector('.comic-viewer__custom-cell--interactive').style.display='block';
          document.querySelector('.viewer-last-shell').style.display='block';
          if(profile==='angel')document.querySelector('.book-last-dead-end').style.display='block';
          else {
            document.querySelector('.legacy-comic-header').hidden=false;
            document.querySelector('.legacy-comic-footer').hidden=false;}
        }""",
        profile,
    )
    return await _frame(page, current=3)


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


def _runner_reader_html(*, mode: str = "normal", terminal_profile: str = "angel") -> str:
    body = _html(current=1, total=3, slot_count=3, terminal_profile=terminal_profile)
    prefix = f"""
      window.__ejFixtureMode={mode!r};
      function renderFixturePages(){{
        for(const [index,canvas] of [...document.querySelectorAll('.page-canvas')].entries()){{
          if(window.__ejFixtureMode==='half-spread'&&fixtureCurrent===2&&index===1){{canvas.width=408;canvas.height=600;continue;}}
          canvas.width=816;canvas.height=1200;
          const source=document.createElement('canvas');source.width=816;source.height=1200;
          const sourceContext=source.getContext('2d');sourceContext.fillStyle=`rgb(${{index*40}},0,0)`;sourceContext.fillRect(0,0,816,1200);
          canvas.getContext('2d').drawImage(source,0,0);
        }}
      }}
      window.addEventListener('resize',renderFixturePages);
    """
    body = body.replace("<script>\n      let fixtureCurrent=1;", "<script>\n      let fixtureCurrent=1;\n" + prefix + "\n      renderFixturePages();")
    body = body.replace(
        "if(fixtureCurrent===1){\n          fixtureCurrent=2;",
        "if(fixtureCurrent===1){\n          if(window.__ejFixtureMode==='premature-end'){document.querySelectorAll('.comic-viewer__page-slot').forEach(slot=>slot.style.display='none');document.querySelector('.seekbar__slider').style.display='none';document.querySelector('.comic-viewer__custom-cell--interactive').style.display='block';document.querySelector('.viewer-last-shell').style.display='block';document.querySelector('.book-last-dead-end').style.display='block';return;}\n          fixtureCurrent=2;",
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
      .book-last-dead-end{position:fixed;inset:0;display:grid;place-items:center}
      .book-last-dead-end[hidden],body.toolbar-hidden .legacy-comic-header__title,
      body.toolbar-hidden .legacy-comic-footer__page-output,body.toolbar-hidden .seekbar__slider{display:none}
      </style></head><body>
      <header class="legacy-comic-header__title">__TITLE__</header>
      <footer class="legacy-comic-footer__page-output">1 / 7</footer>
      <input class="seekbar__slider" type="range" min="0" max="6" step="1" value="6">
      <main class="comic-viewer__scroll-container comic-viewer__scroll-container--horizontal-rtl comic-viewer__scroll-container--spread">__SLOTS__
      <div class="comic-viewer__custom-cell comic-viewer__custom-cell--interactive">
        <div class="viewer-liber__viewer-last-cell"><div class="viewer-last-shell">
          <div class="book-last-dead-end" hidden><div class="book-last-dead-end__inner">
            <div class="review-module book-last-dead-end__review"><button class="review-module__action">Review</button></div>
            <div class="banner-group book-last-dead-end__banner-group"><button class="banner__row banner__row--line-coupon">Coupon</button></div>
            <section class="recommend-grid book-last-dead-end__section book-last-dead-end__author">
              <a class="recommend-grid__heading recommend-grid__heading--more" href="/books/134336/A000000001/">More</a>
              <ul class="recommend-grid__list"><li class="recommend-grid__item"><a class="recommend-grid__link" href="/books/134336/A000000002/">Related</a></li></ul>
            </section>
            <section class="recommend-grid book-last-dead-end__section book-last-dead-end__i2i">
              <ul class="recommend-grid__list"><li class="recommend-grid__item"><a class="recommend-grid__link" href="/books/134336/A000000003/">Related</a></li></ul>
            </section>
            <div class="next-item book-last-dead-end__next">\u3053\u306e\u4f5c\u54c1\u306f\u3053\u3053\u307e\u3067\u3067\u3059</div>
          </div></div>
        </div></div>
      </div>
      </main>
      <script>
      let current=1;const sequence=[1,2,4,6,7];const mode=__MODE__;
      const root=document.querySelector('.comic-viewer__scroll-container');
      const counter=document.querySelector('.legacy-comic-footer__page-output');
      const dead=document.querySelector('.book-last-dead-end');
      const slots=[...root.querySelectorAll('.comic-viewer__page-slot')];
      document.addEventListener('keydown',event=>{
        if(event.key!=='i'||event.target!==document.body)return;
        document.body.classList.add('toolbar-hidden');
      });
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
    terminal_profile: str = "angel",
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
                else _runner_reader_html(mode=mode, terminal_profile=terminal_profile)
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
    for page in manifest["pages"]:
        metadata = page["metadata"]
        assert metadata["capture_method"] == "D_compositor_png"
        assert metadata["capture_class"] == "D"
        assert metadata["fallback_reason_code"] == "SOURCE_NATIVE_PROOF_NOT_ESTABLISHED"
        assert metadata["ebookjapan_capture_policy_revision"] == "ebookjapan-owned-rendered-png-v1-20261108"
        assert all(
            part["capture_class"] == "D"
            and part["fallback_reason_code"] == "SOURCE_NATIVE_PROOF_NOT_ESTABLISHED"
            and part["ebookjapan_capture_policy_revision"] == "ebookjapan-owned-rendered-png-v1-20261108"
            for part in metadata["ebookjapan_capture_parts"]
        )
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


@pytest.mark.parametrize("terminal_profile", ["angel", "angel-observed", "angel-new-arrival", "muda"])
@pytest.mark.parametrize(
    "fixture_mode", ["normal", "delayed-terminal", "opacity-hidden-terminal"]
)
async def test_core_runner_accepts_each_observed_book_terminal_profile(
    browser_page: Page, tmp_path, monkeypatch: pytest.MonkeyPatch,
    terminal_profile: str, fixture_mode: str,
) -> None:
    from screenshot_crawler.site_adapters.ebookjapan.viewer import NAVIGATION_TARGET_JS

    navigation_samples: list[object] = []
    original_evaluate = browser_page.evaluate

    async def record_navigation_sample(expression, *args, **kwargs):
        result = await original_evaluate(expression, *args, **kwargs)
        if expression == NAVIGATION_TARGET_JS:
            navigation_samples.append(result)
        return result

    monkeypatch.setattr(browser_page, "evaluate", record_navigation_sample)
    try:
        _adapter, result = await _run_neutral_core_flow(
            browser_page,
            tmp_path,
            total_slots=3,
            max_pages=10,
            terminal_profile=terminal_profile,
            mode=fixture_mode,
        )
    except UnknownPageStateError as exc:
        pytest.fail(
            f"neutral {terminal_profile}/{fixture_mode} flow stopped at "
            f"{navigation_samples!r}: {exc}"
        )

    assert result.stop_state.value == "end"
    assert len(result.pages) == 3
    if terminal_profile == "angel-new-arrival":
        output = tmp_path / "catalog-isolated" / "run"
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        assert [page["sequence"] for page in manifest["pages"]] == [1, 2, 3]
        packaged = package_crawl_output(
            output,
            {"title": TITLE, "genre": "neutral-test"},
            library_dir=tmp_path / "library-isolated",
        )
        assert packaged.archive_path.is_file()
        assert json.loads(packaged.status_path.read_text(encoding="utf-8"))["status"] == "completed"
        with zipfile.ZipFile(packaged.archive_path) as archive:
            assert sorted(archive.namelist()) == [f"page-{index:04d}.png" for index in range(1, 4)]


async def test_core_runner_waits_for_exact_hidden_angel_terminal_to_settle(
    browser_page: Page, tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from screenshot_crawler.site_adapters.ebookjapan import adapter as adapter_module

    monkeypatch.setattr(adapter_module, "_FRAME_READY_WAIT_MS", 2_000)
    monkeypatch.setattr(adapter_module, "_FRAME_POLL_MS", 20)
    original_go_next = EbookJapanAdapter.go_next

    async def seed_stale_terminal_cache(adapter, page):
        adapter._terminal_diagnostics = {
            "first_unknown": {"status": "identity-mismatch"},
            "last_sample": {"status": "identity-mismatch"},
        }
        await original_go_next(adapter, page)

    monkeypatch.setattr(EbookJapanAdapter, "go_next", seed_stale_terminal_cache)
    original_evaluate = browser_page.evaluate
    terminal_samples: list[dict[str, object]] = []

    async def record_terminal_samples(expression, *args, **kwargs):
        result = await original_evaluate(expression, *args, **kwargs)
        if expression == FRAME_STATE_JS and isinstance(result, dict):
            terminal = result.get("terminal")
            if isinstance(terminal, dict) and terminal.get("profile") == "angel-dead-end-observed-controls":
                terminal_samples.append(result)
        return result

    monkeypatch.setattr(browser_page, "evaluate", record_terminal_samples)
    adapter, result = await _run_neutral_core_flow(
        browser_page,
        tmp_path,
        mode="transient-observed-terminal",
        max_pages=10,
        terminal_profile="angel-observed",
    )

    assert result.stop_state.value == "end"
    assert len(result.pages) == 3
    assert adapter._capture_coverage_complete() is True
    assert adapter._terminal_end_verified is True
    transient = [sample for sample in terminal_samples if sample.get("status") == "unknown-terminal-marker"]
    settled = [sample for sample in terminal_samples if sample.get("status") == "end"]
    assert transient, json.dumps(terminal_samples, sort_keys=True)
    assert settled, json.dumps(terminal_samples, sort_keys=True)
    unknown = transient[0]
    terminal = unknown["terminal"]
    assert unknown["toolbarVisible"] is False
    assert unknown["visibleSlots"] == []
    assert terminal["nativeCounterVisible"] is False
    assert terminal["visiblePageCanvasCount"] == 0
    assert terminal["visibleSlotCount"] == 0
    assert terminal["lotteryButtonCount"] == 1
    assert terminal["headerRootCount"] == terminal["headerBarCount"] == terminal["headerMenuCount"] == 1
    assert terminal["headerCounts"] == {
        "close-button": 0,
        "contents-button": 0,
        "settings-button": 0,
    }
    assert terminal["partition"] == {
        "review": 1,
        "coupon": 1,
        "lottery": 1,
        "recommendAuthor": 2,
        "recommendI2i": 1,
    }
    assert settled[-1]["terminal"]["partition"] == {
        "review": 1,
        "coupon": 1,
        "lottery": 1,
        "recommendAuthor": 2,
        "recommendI2i": 1,
        "header": 3,
    }
    assert settled[-1]["counterVisible"] is False
    assert settled[-1]["terminal"]["headerCounts"] == {
        "close-button": 1,
        "contents-button": 1,
        "settings-button": 1,
    }
    diagnostics = await adapter.collect_debug_metadata(browser_page)
    terminal_wait = diagnostics["ebookjapan_terminal_wait"]
    assert terminal_wait["first_unknown"]["status"] == "unknown-terminal-marker"
    assert terminal_wait["first_unknown"]["unknown_outside_known_region_count"] == 0
    assert terminal_wait["first_unknown"]["unknown_action_count"] == 1
    assert terminal_wait["first_unknown"]["coverage_complete"] is True
    assert any(sample["terminal"]["moduleCounts"]["author"] == 0 for sample in transient)
    assert terminal_wait["last_sample"]["status"] == "end"
    assert terminal_wait["last_sample"]["module_counts"]["author"] == 1


async def test_permanently_hidden_angel_terminal_times_out_without_packaging(
    browser_page: Page, tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from screenshot_crawler.site_adapters.ebookjapan import adapter as adapter_module

    monkeypatch.setattr(adapter_module, "_FRAME_READY_WAIT_MS", 120)
    monkeypatch.setattr(adapter_module, "_FRAME_POLL_MS", 10)
    with pytest.raises(UnknownPageStateError, match="did not produce a new full content frame"):
        await _run_neutral_core_flow(
            browser_page,
            tmp_path,
            mode="permanent-hidden-observed-terminal",
            max_pages=10,
            terminal_profile="angel-observed",
        )

    output = tmp_path / "catalog-isolated" / "run"
    manifest_path = output / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest.get("status") != "completed"
    assert not list(tmp_path.rglob("*.zip"))


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
    await _draw_full_same_size(browser_page, width=408, height=600)
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
    await _draw_full_same_size(browser_page, width=408, height=600)
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


@pytest.mark.parametrize(
    ("viewport", "device_scale_factor", "width", "height", "series_id", "external_id"),
    [
        ((1904, 985), 1, 816, 1200, "134336", "A000083590"),
        ((1440, 900), 1.5, 1088, 1600, "115888", "A000039104"),
        ((1280, 720), 1.5, 1120, 1600, "115888", "A001574536"),
        ((1537, 877), 1.5, 934, 1500, "134336", "A000083590"),
    ],
    ids=["angel-dpr1", "muda1-dpr1_5", "muda16-dpr1_5", "other-shape-dpr1_5"],
)
async def test_capture_hides_toolbar_with_native_shortcut_across_viewports_and_dpr(
    integration_browser: Browser,
    viewport: tuple[int, int],
    device_scale_factor: float,
    width: int,
    height: int,
    series_id: str,
    external_id: str,
) -> None:
    context = await integration_browser.new_context(
        viewport={"width": viewport[0], "height": viewport[1]},
        device_scale_factor=device_scale_factor,
    )
    page = await context.new_page()
    try:
        await _open_reader(page, current=1, total=3, slot_count=3)
        await _draw_full_same_size(page, width=width, height=height)
        initial_dpr = await page.evaluate("() => devicePixelRatio")
        adapter = EbookJapanAdapter()
        adapter._page = page
        adapter._owned_title = TITLE
        adapter._series_id = series_id
        adapter._external_id = external_id
        adapter._work_key = "neutral-work"
        adapter._reader_path = READER_PATH
        adapter._reader_total = 3
        adapter._last_native_counter = 1
        await page.evaluate(
            """()=>{
              window.__ejMouseClickCount=0;
              document.addEventListener('click',()=>window.__ejMouseClickCount++);
            }"""
        )
        await adapter._pin_reader_anchor(
            page, expected_path=READER_PATH, expected_current=1, expected_total=3
        )
        before = await _frame(page)
        assert before["viewport"] == {"width": viewport[0], "height": viewport[1]}
        assert before["parts"][0]["drawReady"] is True
        identity = await adapter.get_content_identity(page)

        captures = await adapter.capture_page(page)
        after = await _frame(page)
        counter_text = await page.locator(
            ".legacy-comic-footer__page-output"
        ).text_content()
        assert captures is not None and len(captures) == 1
        image = Image.open(io.BytesIO(captures[0].data)).convert("RGBA")

        assert identity.source_id == external_id
        assert image.size == (width, height)
        assert image.getpixel((0, 0)) == (0, 0, 0, 255)
        assert after["status"] == "content"
        assert after["toolbarVisible"] is False
        assert after["viewport"] == {"width": width * 2, "height": height}
        assert after["parts"][0]["slotId"] == before["parts"][0]["slotId"]
        assert (after["parts"][0]["backingWidth"], after["parts"][0]["backingHeight"]) == (width, height)
        assert counter_text == "1 / 3"
        assert await page.evaluate("() => window.__ejToggleKeyCount") == 1
        assert await page.evaluate("() => window.__ejMouseClickCount") == 0
        assert await page.evaluate("() => devicePixelRatio") == initial_dpr == device_scale_factor
        assert adapter._last_capture_parts[0]["capture_class"] == "D"
        assert adapter._last_capture_parts[0]["source_provenance"] == "UNKNOWN"
        assert adapter._seen_slot_ids == {before["parts"][0]["slotId"]}
    finally:
        await page.close()
        await context.close()


async def test_toolbar_shortcut_blurs_only_the_verified_native_range(
    browser_page: Page,
) -> None:
    adapter, frame = await _toolbar_shortcut_fixture(browser_page)
    slider = browser_page.locator(".seekbar__slider")
    await slider.focus()
    assert await browser_page.evaluate("() => document.activeElement.className") == "seekbar__slider"

    hidden = await adapter._hide_toolbar_for_capture(
        browser_page, frame=frame, expected_path=READER_PATH, current=1, total=3
    )

    assert hidden["toolbarVisible"] is False
    assert await browser_page.evaluate("() => document.activeElement === document.body") is True
    assert await browser_page.evaluate("() => window.__ejToggleKeyCount") == 1
    assert adapter._seen_slot_ids == set()


@pytest.mark.parametrize("unsafe_state", ["textarea", "contenteditable", "button", "modal"])
async def test_toolbar_shortcut_rejects_unsafe_initial_focus_or_modal(
    browser_page: Page, unsafe_state: str
) -> None:
    adapter, frame = await _toolbar_shortcut_fixture(browser_page)
    await browser_page.evaluate(
        """state=>{
          if(state==='textarea'){
            const node=document.createElement('textarea');node.style.cssText='position:fixed;left:-100px;top:0';
            document.body.append(node);node.focus();
          }else if(state==='contenteditable'){
            document.body.contentEditable='true';document.body.focus();
          }else if(state==='button'){
            const node=document.createElement('button');node.textContent='focus';
            node.style.cssText='position:fixed;left:0;top:40px';document.body.append(node);node.focus();
          }else{
            const node=document.createElement('div');node.setAttribute('role','dialog');
            node.style.cssText='position:fixed;left:20px;top:30px;width:100px;height:100px;background:white';
            document.body.append(node);
          }
        }""",
        unsafe_state,
    )

    with pytest.raises(UnknownPageStateError):
        await adapter._hide_toolbar_for_capture(
            browser_page, frame=frame, expected_path=READER_PATH, current=1, total=3
        )

    assert await browser_page.evaluate("() => window.__ejToggleKeyCount") == 0
    assert adapter._seen_slot_ids == set()


@pytest.mark.parametrize("drift", ["focus", "modal"])
async def test_toolbar_shortcut_rechecks_body_after_final_frame_read(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    adapter, frame = await _toolbar_shortcut_fixture(browser_page)
    original_read_ready_frame = adapter._read_ready_frame
    ready_reads = 0

    async def inject_drift_after_ready_read(
        page: Page, *, expected_path: str, current: int, total: int
    ) -> dict[str, object]:
        nonlocal ready_reads
        result = await original_read_ready_frame(
            page, expected_path=expected_path, current=current, total=total
        )
        ready_reads += 1
        if ready_reads == 2:
            await page.evaluate(
                """drift=>{
                  if(drift==='focus'){
                    const node=document.createElement('textarea');
                    node.style.cssText='position:fixed;left:-100px;top:0';document.body.append(node);node.focus();
                  }else{
                    const node=document.createElement('div');node.setAttribute('role','dialog');
                    node.style.cssText='position:fixed;left:20px;top:30px;width:100px;height:100px;background:white';
                    document.body.append(node);
                  }
                }""",
                drift,
            )
        return result

    monkeypatch.setattr(adapter, "_read_ready_frame", inject_drift_after_ready_read)
    with pytest.raises(UnknownPageStateError, match="unsafe BODY focus or modal state before shortcut"):
        await adapter._hide_toolbar_for_capture(
            browser_page, frame=frame, expected_path=READER_PATH, current=1, total=3
        )

    assert ready_reads == 2
    assert await browser_page.evaluate("() => window.__ejToggleKeyCount") == 0
    assert adapter._seen_slot_ids == set()


async def test_toolbar_shortcut_fails_closed_when_native_key_is_ignored(
    browser_page: Page,
) -> None:
    adapter, frame = await _toolbar_shortcut_fixture(browser_page)
    await browser_page.evaluate("() => {window.__ejIgnoreToggle=true}")

    with pytest.raises(UnknownPageStateError, match="did not hide within the bounded shortcut wait"):
        await adapter._hide_toolbar_for_capture(
            browser_page, frame=frame, expected_path=READER_PATH, current=1, total=3
        )

    assert await browser_page.evaluate("() => window.__ejToggleKeyCount") == 1
    assert (await _frame(browser_page))["toolbarVisible"] is True
    assert adapter._seen_slot_ids == set()


@pytest.mark.parametrize(
    ("width", "external_id"),
    [
        (1088, "A000039104"),
        (1120, "A001574536"),
    ],
)
async def test_capture_hides_toolbar_and_fits_mudazumo_cover_dimensions(
    browser_page: Page,
    width: int,
    external_id: str,
) -> None:
    await _open_reader(browser_page)
    await _draw_full_same_size(browser_page, width=width, height=1600)
    adapter = EbookJapanAdapter()
    adapter._page = browser_page
    adapter._owned_title = TITLE
    adapter._series_id = "115888"
    adapter._external_id = external_id
    adapter._work_key = "mudazumo"
    adapter._reader_path = READER_PATH
    adapter._reader_total = 1
    adapter._last_native_counter = 1
    await adapter._pin_reader_anchor(
        browser_page, expected_path=READER_PATH, expected_current=1, expected_total=1
    )
    before = await _frame(browser_page)
    before_part = before["parts"][0]
    assert (before_part["backingWidth"], before_part["backingHeight"]) == (width, 1600)
    assert before_part["drawReady"] is True
    identity = await adapter.get_content_identity(browser_page)

    captures = await adapter.capture_page(browser_page)
    after = await _frame(browser_page)
    counter_text = await browser_page.locator(
        ".legacy-comic-footer__page-output"
    ).text_content()
    debug = await adapter.collect_debug_metadata(browser_page)

    assert identity.source_id == external_id
    assert len(captures) == 1
    assert (captures[0].width, captures[0].height) == (width, 1600)
    assert after["status"] == "content"
    assert after["toolbarVisible"] is False
    assert after["viewport"] == {"width": width * 2, "height": 1600}
    assert after["parts"][0]["slotId"] == before_part["slotId"]
    assert (after["parts"][0]["cssRect"]["width"], after["parts"][0]["cssRect"]["height"]) == (width, 1600)
    assert counter_text == "1 / 1"
    assert adapter._seen_slot_ids == {before_part["slotId"]}
    assert debug["capture_class"] == "D"
    assert debug["fallback_reason_code"] == "SOURCE_NATIVE_PROOF_NOT_ESTABLISHED"
    assert debug["ebookjapan_capture_policy_revision"] == "ebookjapan-owned-rendered-png-v1-20261108"
    assert debug["ebookjapan_capture_parts"][0]["source_provenance"] == "UNKNOWN"


async def test_fitted_cover_center_can_advance_in_the_neutral_fixture(
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
    assert fitted["viewport"] == {"width": 1632, "height": 1200}
    assert fitted["toolbarVisible"] is True
    assert await browser_page.locator(
        ".legacy-comic-footer__page-output"
    ).text_content() == "1 / 3"
    canvas = browser_page.locator(".page-canvas").nth(2)
    box = await canvas.bounding_box()
    assert box is not None
    center_x = box["x"] + box["width"] / 2
    assert center_x / 1632 == pytest.approx(0.25)
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
    assert (captures[0].width, captures[0].height) == (816, 1200)
    with Image.open(io.BytesIO(captures[0].data)) as image:
        assert image.convert("RGBA").getpixel((408, 600)) == (0, 0, 0, 255)
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
        "() => {document.querySelector('.legacy-comic-header').hidden=true;document.querySelector('.legacy-comic-footer').hidden=true;document.querySelector('.seekbar__slider').style.display='none';}"
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
        "img-outline-expanded-touch",
        "img-outline-expanded-contact",
        "img-outline-huge-offset-reaches-canvas",
        "img-outline-negative-offset-reaches-canvas",
        "img-outline-negative-huge-offset-reaches-canvas",
        "img-outline-ancestor-scale",
        "img-outline-ancestor-zoom",
        "img-outline-ancestor-rotate",
        "img-outline-ancestor-motion-path",
        "img-outline-ancestor-skew",
        "img-outline-ancestor-perspective",
        "img-outline-self-scale",
        "img-outline-ancestor-border-image",
        "img-outline-ancestor-reflection",
        "img-outline-svg-ancestor",
        "img-outline-border-image-outset",
        "img-outline-reflection",
        "img-outline-pseudo",
        "svg-image-outline",
        "outlined-div",
        "aggregate-visible-text-media",
        "aggregate-sampled-visible-overlay",
        "aggregate-direct-text",
        "aggregate-visible-media",
        "aggregate-own-background",
        "aggregate-own-pseudo",
        "aggregate-own-effect",
        "aggregate-visibility-hidden-visible-override",
        "aggregate-node-overflow",
        "aggregate-candidate-overflow",
        "aggregate-ancestor-overflow",
        "aggregate-unknown-shadow",
        "aggregate-open-shadow",
        "aggregate-closed-shadow",
        "aggregate-nested-closed-shadow",
        "aggregate-declarative-closed-shadow",
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
        """async issue=>{
          const betweenSampleStyle=()=>{
            const r=document.querySelector('.page-canvas').getBoundingClientRect();
            return `position:fixed;left:${r.left+r.width*.12}px;top:${r.top+r.height*.944}px;width:${r.width*.03}px;height:${r.height*.031}px;pointer-events:none`;
          };
          const makeAggregateContainer=()=>{
            const container=document.createElement('div');container.id='aggregate-container';
            container.style.cssText=betweenSampleStyle();
            document.body.append(container);return container;
          };
          const appendSvgMedia=parent=>{
            const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
            svg.setAttribute('width','8');svg.setAttribute('height','8');
            const image=document.createElementNS('http://www.w3.org/2000/svg','image');
            image.setAttribute('width','8');image.setAttribute('height','8');
            image.setAttribute('href','data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=');
            svg.append(image);parent.append(svg);
          };
          const appendOpacitySuppressedAggregate=container=>{
            const suppressed=document.createElement('div');suppressed.id='suppressed-aggregate';
            suppressed.style.opacity='0';
            const text=document.createElement('span');text.textContent='suppressed child label';
            appendSvgMedia(suppressed);suppressed.append(text);container.append(suppressed);
          };
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
          }else if(issue.startsWith('img-outline-')){
            const image=document.createElement('img');image.className='neutral-outline-image';
            image.src='data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=';
            const mode=issue.slice('img-outline-'.length);
            if(mode==='ancestor-scale'||mode==='ancestor-zoom'||mode==='ancestor-rotate'||mode==='ancestor-motion-path'
              ||mode==='ancestor-skew'||mode==='ancestor-perspective'){
              const host=document.createElement('div');host.style.cssText='position:fixed;left:calc(50vw + 100px);top:100px;width:40px;height:40px';
              if(mode==='ancestor-scale')host.style.scale='2';
              else if(mode==='ancestor-zoom')host.style.zoom='2';
              else if(mode==='ancestor-rotate')host.style.rotate='10deg';
              else if(mode==='ancestor-motion-path'){host.style.offsetPath='ray(45deg)';host.style.offsetDistance='20px';}
              else if(mode==='ancestor-skew')host.style.transform='skew(10deg)';
              else host.style.perspective='100px';
              host.append(image);document.body.append(host);
            }else if(mode==='ancestor-border-image'||mode==='ancestor-reflection'){
              const host=document.createElement('div');host.style.cssText='position:fixed;left:calc(50vw + 100px);top:100px;width:40px;height:40px';
              if(mode==='ancestor-border-image'){
                host.style.border='4px solid transparent';host.style.borderImageSource='linear-gradient(red,blue)';
                host.style.borderImageSlice='1';host.style.borderImageOutset='2';
              }else host.style.webkitBoxReflect='below 2px';
              image.style.cssText='width:24px;height:24px;outline:solid 1px red';
              host.append(image);document.body.append(host);
            }else if(mode==='svg-ancestor'){
              const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
              svg.style.cssText='position:fixed;left:calc(50vw + 100px);top:100px;width:40px;height:40px';
              const foreign=document.createElementNS('http://www.w3.org/2000/svg','foreignObject');
              foreign.setAttribute('width','40');foreign.setAttribute('height','40');
              image.style.cssText='width:24px;height:24px;outline:solid 1px red';
              foreign.append(image);svg.append(foreign);document.body.append(svg);
            }else if(mode==='border-image-outset'){
              image.style.cssText='position:fixed;left:calc(50vw + 100px);top:100px;width:24px;height:24px;outline:solid 1px red;border:4px solid transparent;border-image-source:linear-gradient(red,blue);border-image-slice:1;border-image-outset:2';
              document.body.append(image);
            }else if(mode==='reflection'){
              image.style.cssText='position:fixed;left:calc(50vw + 100px);top:100px;width:24px;height:24px;outline:solid 1px red;-webkit-box-reflect:below 2px';
              document.body.append(image);
            }else if(mode==='pseudo'){
              const style=document.createElement('style');style.textContent='img.neutral-outline-image::after{content:"";position:absolute;inset:-5px;background:red}';document.head.append(style);
              image.style.cssText='position:fixed;left:calc(50vw + 100px);top:100px;width:24px;height:24px;outline:solid 1px red';document.body.append(image);
            }else{
              let gap=100,outline='solid 1px red',offset='0px';
              if(mode==='expanded-touch'){gap=2;outline='solid 2px red';}
              else if(mode==='expanded-contact'){gap=3;outline='solid 1px red';}
              else if(mode==='huge-offset-reaches-canvas')offset='100px';
              else if(mode==='negative-offset-reaches-canvas'){gap=1;outline='solid 2px red';offset='-1px';}
              else if(mode==='negative-huge-offset-reaches-canvas'){gap=150;offset='-150px';}
              if(mode==='self-scale')image.style.cssText='position:fixed;left:calc(50vw + '+gap+'px);top:100px;width:24px;height:24px;outline:'+outline+';outline-offset:'+offset+';scale:2';
              else image.style.cssText='position:fixed;left:calc(50vw + '+gap+'px);top:100px;width:24px;height:24px;outline:'+outline+';outline-offset:'+offset;
              document.body.append(image);
            }
            if(mode==='ancestor-scale'||mode==='ancestor-zoom'||mode==='ancestor-rotate'||mode==='ancestor-motion-path'
              ||mode==='ancestor-skew'||mode==='ancestor-perspective'
              ||mode==='ancestor-border-image'||mode==='ancestor-reflection'||mode==='svg-ancestor'){
              image.style.cssText='width:24px;height:24px;outline:solid 1px red';
            }
            await image.decode();
          }else if(issue==='svg-image-outline'){
            const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
            svg.style.cssText='position:fixed;left:calc(50vw + 100px);top:100px;width:24px;height:24px;outline:solid 1px red';
            const image=document.createElementNS('http://www.w3.org/2000/svg','image');
            image.setAttribute('width','24');image.setAttribute('height','24');
            image.setAttribute('href','data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=');svg.append(image);document.body.append(svg);
          }else if(issue==='outlined-div'){
            const div=document.createElement('div');div.style.cssText='position:fixed;left:calc(50vw + 100px);top:100px;width:24px;height:24px;outline:solid 1px red';document.body.append(div);
          }else if(issue==='aggregate-visible-text-media'){
            const container=makeAggregateContainer(),text=document.createElement('span');
            text.textContent='visible child label';container.append(text);appendSvgMedia(container);
          }else if(issue==='aggregate-sampled-visible-overlay'){
            const container=document.createElement('div'),r=document.querySelector('.page-canvas').getBoundingClientRect();
            container.style.cssText=`position:fixed;left:${r.left+r.width*.1-2}px;top:${r.top+r.height*.1-2}px;width:12px;height:12px`;
            container.append(document.createTextNode('sampled visible overlay'));document.body.append(container);
          }else if(issue==='aggregate-direct-text'){
            const container=makeAggregateContainer();container.append(document.createTextNode('direct visible label'));
          }else if(issue==='aggregate-visible-media'){
            const container=makeAggregateContainer(),image=document.createElement('img');
            image.src='data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=';
            image.style.cssText='width:8px;height:8px';container.append(image);
          }else if(issue==='aggregate-own-background'||issue==='aggregate-own-effect'||issue==='aggregate-own-pseudo'){
            const container=makeAggregateContainer();container.append(document.createTextNode('own-style-risk'));
            if(issue==='aggregate-own-background')container.style.backgroundColor='rgb(255,0,0)';
            else if(issue==='aggregate-own-effect')container.style.boxShadow='0 0 2px rgb(255,0,0)';
            else{
              container.classList.add('aggregate-own-pseudo');
              const style=document.createElement('style');
              style.textContent='.aggregate-own-pseudo::before{content:"paint";position:absolute;inset:0;color:red}';
              document.head.append(style);
            }
          }else if(issue==='aggregate-visibility-hidden-visible-override'){
            const container=makeAggregateContainer(),hidden=document.createElement('div');
            hidden.style.visibility='hidden';
            const text=document.createElement('span');text.style.visibility='visible';
            text.textContent='visible override';hidden.append(text);container.append(hidden);
          }else if(issue==='aggregate-node-overflow'){
            const container=makeAggregateContainer(),suppressed=document.createElement('div');
            suppressed.style.opacity='0';container.append(suppressed);
            for(let index=0;index<513;index++){const child=document.createElement('span');child.textContent='x';suppressed.append(child);}
          }else if(issue==='aggregate-candidate-overflow'){
            for(let index=0;index<9;index++){
              const container=makeAggregateContainer();container.id='aggregate-candidate-'+index;
              const child=document.createElement('span');child.style.opacity='0';
              child.textContent='suppressed candidate '+index;container.append(child);
            }
          }else if(issue==='aggregate-ancestor-overflow'){
            let root=null,parent=null;
            for(let index=0;index<66;index++){
              const wrapper=document.createElement('div');
              wrapper.style.cssText=betweenSampleStyle();
              if(parent)parent.append(wrapper);else root=wrapper;
              parent=wrapper;
            }
            document.body.append(root);
            const container=document.createElement('div');container.style.cssText='width:20px;height:20px';
            const text=document.createElement('span');text.textContent='deep visible label';container.append(text);parent.append(container);
          }else if(issue==='aggregate-unknown-shadow'){
            const container=makeAggregateContainer(),text=document.createElement('span');
            text.textContent='unknown shadow host';container.append(text);
            const custom=document.createElement('x-unknown-content');custom.attachShadow({mode:'open'});
            custom.shadowRoot.innerHTML='<span>shadow content</span>';container.append(custom);
          }else if(issue==='aggregate-open-shadow'||issue==='aggregate-closed-shadow'){
            const container=makeAggregateContainer(),child=document.createElement('span');
            child.style.opacity='0';child.textContent='suppressed light text';container.append(child);
            const shadow=container.attachShadow({mode:issue==='aggregate-open-shadow'?'open':'closed'});
            shadow.append(document.createElement('slot'));
            const paint=document.createElement('div');paint.style.cssText='position:absolute;inset:0;background:red';shadow.append(paint);
          }else if(issue==='aggregate-nested-closed-shadow'){
            const container=makeAggregateContainer(),nested=document.createElement('span');
            nested.style.opacity='0';nested.textContent='nested suppressed label';
            const shadow=nested.attachShadow({mode:'closed'});
            shadow.append(document.createElement('slot'));
            const paint=document.createElement('div');paint.style.cssText='position:absolute;inset:0;background:red';shadow.append(paint);
            container.append(nested);
          }else if(issue==='aggregate-declarative-closed-shadow'){
            const container=makeAggregateContainer(),hidden=document.createElement('div');hidden.style.opacity='0';
            if(typeof hidden.setHTMLUnsafe!=='function')throw new Error('declarative shadow fixture unavailable');
            hidden.setHTMLUnsafe('<template shadowrootmode="closed"><div style="width:100%;height:100%;background:red"></div></template>');
            const child=document.createElement('span');child.textContent='suppressed light text';hidden.append(child);container.append(hidden);
          }else{
            document.querySelector('.comic-viewer__page-slot').style.transform='rotate(180deg)';
          }
        }""",
        surface_issue,
    )

    if surface_issue in {
        "aggregate-closed-shadow",
        "aggregate-nested-closed-shadow",
        "aggregate-declarative-closed-shadow",
    }:
        expected_reason = "opacity-shadow-proof-unavailable"
        diagnostic_frame = await _frame(browser_page)
        diagnostic_part = diagnostic_frame["parts"][0]
        assert diagnostic_part["captureSurfaceReason"] == "opacity-shadow-proof-required", {
            "reason": diagnostic_part["captureSurfaceReason"],
            "candidate_count": len(diagnostic_part.get("captureSurfaceCandidates", [])),
        }
    else:
        expected_reason = None
    with pytest.raises(UnknownPageStateError) as error:
        await adapter.capture_page(browser_page)
    if expected_reason is not None:
        assert expected_reason in str(error.value)
    assert adapter._seen_slot_ids == set()
    assert adapter._captured_slot_order == []


async def _prepare_opacity_candidate_capture(page: Page) -> EbookJapanAdapter:
    await _open_reader(page)
    await _draw_full_same_size(page)
    adapter = EbookJapanAdapter()
    adapter._owned_title = TITLE
    adapter._series_id = "134336"
    adapter._external_id = "A000083590"
    adapter._work_key = "neutral-work"
    adapter._reader_path = READER_PATH
    adapter._reader_total = 1
    adapter._last_native_counter = 1
    await _redraw_on_resize(page)
    await adapter._pin_reader_anchor(
        page, expected_path=READER_PATH, expected_current=1, expected_total=1
    )
    await adapter.get_content_identity(page)
    frame = await _frame(page)
    await adapter._hide_toolbar_for_capture(
        page, frame=frame, expected_path=READER_PATH, current=1, total=1
    )
    await page.evaluate(
        """()=>{
          const r=document.querySelector('.page-canvas').getBoundingClientRect();
          const container=document.createElement('div');container.id='aggregate-container';
          container.style.cssText=`position:fixed;left:${r.left+r.width*.12}px;top:${r.top+r.height*.944}px;width:${r.width*.03}px;height:${r.height*.031}px;pointer-events:none`;
          const suppressed=document.createElement('div');suppressed.id='suppressed-aggregate';suppressed.style.opacity='0';
          const text=document.createElement('span');text.textContent='suppressed child label';
          const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('width','8');svg.setAttribute('height','8');
          const image=document.createElementNS('http://www.w3.org/2000/svg','image');image.setAttribute('width','8');image.setAttribute('height','8');
          image.setAttribute('href','data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=');
          svg.append(image);suppressed.append(text,svg);container.append(suppressed);document.body.append(container);
        }"""
    )
    return adapter


async def test_capture_accepts_aggregate_text_and_svg_media_only_when_zero_opacity_suppressed(
    browser_page: Page,
) -> None:
    adapter = await _prepare_opacity_candidate_capture(browser_page)

    captures = await adapter.capture_page(browser_page)
    assert captures is not None and len(captures) == 1
    assert adapter._seen_slot_ids == {1}
    assert adapter._captured_slot_order == [1]


@pytest.mark.parametrize("failure_mode", ["unavailable", "timeout", "partial", "mutated"])
async def test_opacity_shadow_proof_failures_do_not_commit_coverage(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
) -> None:
    adapter = await _prepare_opacity_candidate_capture(browser_page)
    context = browser_page.context
    original_factory = context.new_cdp_session

    if failure_mode == "unavailable":

        async def unavailable(_page):
            raise RuntimeError("synthetic protocol unavailable")

        monkeypatch.setattr(context, "new_cdp_session", unavailable)
    else:

        async def instrumented_factory(page):
            session = await original_factory(page)
            original_send = session.send

            async def send(method: str, params: dict[str, object] | None = None):
                if method == "DOM.describeNode" and failure_mode == "timeout":
                    await asyncio.sleep(2.2)
                result = await original_send(method, params or {})
                if method == "DOM.describeNode" and failure_mode == "partial":
                    node = result.get("node")
                    assert isinstance(node, dict)
                    node["childNodeCount"] = node.get("childNodeCount", 0) + 1
                if method == "DOM.describeNode" and failure_mode == "mutated":
                    await page.evaluate(
                        "() => { document.querySelector('#suppressed-aggregate').style.opacity='1'; }"
                    )
                return result

            session.send = send
            return session

        monkeypatch.setattr(context, "new_cdp_session", instrumented_factory)

    with pytest.raises(UnknownPageStateError, match="opacity-shadow-proof-unavailable"):
        await adapter.capture_page(browser_page)
    assert adapter._seen_slot_ids == set()
    assert adapter._captured_slot_order == []


async def test_normal_capture_does_not_open_a_cdp_session_for_unconditional_surfaces(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
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
    calls = 0
    original_factory = browser_page.context.new_cdp_session

    async def counted_factory(page):
        nonlocal calls
        calls += 1
        return await original_factory(page)

    monkeypatch.setattr(browser_page.context, "new_cdp_session", counted_factory)
    captures = await adapter.capture_page(browser_page)
    assert captures is not None and len(captures) == 1
    assert calls == 0


async def test_capture_rechecks_opacity_suppressed_aggregate_after_first_reference(
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
    await adapter.get_content_identity(browser_page)
    frame = await _frame(browser_page)
    await adapter._hide_toolbar_for_capture(
        browser_page, frame=frame, expected_path=READER_PATH, current=1, total=1
    )
    await browser_page.evaluate(
        """()=>{
          const r=document.querySelector('.page-canvas').getBoundingClientRect();
          const container=document.createElement('div');container.id='aggregate-container';
          container.style.cssText=`position:fixed;left:${r.left+r.width*.12}px;top:${r.top+r.height*.944}px;width:${r.width*.03}px;height:${r.height*.031}px;pointer-events:none`;
          const suppressed=document.createElement('div');suppressed.id='suppressed-aggregate';suppressed.style.opacity='0';
          const text=document.createElement('span');text.textContent='suppressed child label';
          const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('width','8');svg.setAttribute('height','8');
          const image=document.createElementNS('http://www.w3.org/2000/svg','image');image.setAttribute('width','8');image.setAttribute('height','8');
          image.setAttribute('href','data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=');
          svg.append(image);suppressed.append(text,svg);container.append(suppressed);document.body.append(container);
        }"""
    )
    original_pinned_canvas_locator = adapter._pinned_canvas_locator
    revealed = False

    class RevealAfterFirstScreenshot:
        def __init__(self, locator):
            self.locator = locator

        async def is_visible(self):
            return await self.locator.is_visible()

        async def screenshot(self, *args, **kwargs):
            nonlocal revealed
            data = await self.locator.screenshot(*args, **kwargs)
            if not revealed:
                revealed = True
                await browser_page.evaluate(
                    "() => { document.querySelector('#suppressed-aggregate').style.opacity='1'; }"
                )
            return data

    async def reveal_after_first_reference(page: Page, part):
        locator = await original_pinned_canvas_locator(page, part)
        return RevealAfterFirstScreenshot(locator)

    adapter._pinned_canvas_locator = reveal_after_first_reference
    with pytest.raises(UnknownPageStateError):
        await adapter.capture_page(browser_page)
    assert revealed is True
    assert adapter._seen_slot_ids == set()
    assert adapter._captured_slot_order == []


@pytest.mark.parametrize("translation", [False, True], ids=["no-transform", "pure-2d-translation"])
async def test_capture_accepts_only_far_finite_solid_outline_on_complete_html_image(
    browser_page: Page, translation: bool,
) -> None:
    await _open_reader(browser_page)
    await _draw_full_same_size(browser_page)
    adapter = EbookJapanAdapter()
    adapter._page = browser_page
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
    await browser_page.evaluate(
        """async translation=>{
          const image=document.createElement('img');image.className='neutral-far-outline-image';
          image.src='data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=';
          image.style.cssText='width:24px;height:24px;outline:solid .666667px oklch(0 0 0 / 0.05)';
          if(translation){
            const host=document.createElement('div');
            host.style.cssText='position:fixed;left:calc(50vw + 100px);top:100px;transform:translate(8px,4px);translate:2px 1px';
            host.append(image);document.body.append(host);
          }else{
            image.style.position='fixed';image.style.left='calc(50vw + 100px)';image.style.top='100px';document.body.append(image);
          }
          await image.decode();
        }""",
        translation,
    )

    captures = await adapter.capture_page(browser_page)
    assert captures is not None and len(captures) == 1
    assert adapter._seen_slot_ids == {1}
    assert adapter._captured_slot_order == [1]


async def test_capture_rejects_finite_outline_qualifier_below_supported_dpr(
    integration_browser: Browser,
) -> None:
    context = await integration_browser.new_context(
        viewport={"width": 1906, "height": 986}, device_scale_factor=0.75
    )
    page = await context.new_page()
    try:
        await _open_reader(page)
        await _draw_full_same_size(page)
        adapter = EbookJapanAdapter()
        adapter._page = page
        adapter._owned_title = TITLE
        adapter._series_id = "134336"
        adapter._external_id = "A000083590"
        adapter._work_key = "neutral-work"
        adapter._reader_path = READER_PATH
        adapter._reader_total = 1
        adapter._last_native_counter = 1
        await _redraw_on_resize(page)
        await adapter._pin_reader_anchor(
            page, expected_path=READER_PATH, expected_current=1, expected_total=1
        )
        await adapter.get_content_identity(page)
        assert await page.evaluate("() => window.devicePixelRatio") == 0.75
        await page.evaluate(
            """async()=>{
              const image=document.createElement('img');image.className='neutral-low-dpr-outline-image';
              image.src='data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=';
              image.style.cssText='position:fixed;left:calc(50vw + 100px);top:100px;width:24px;height:24px;outline:solid .666667px red';
              document.body.append(image);await image.decode();
            }"""
        )

        with pytest.raises(UnknownPageStateError):
            await adapter.capture_page(page)
        assert adapter._seen_slot_ids == set()
        assert adapter._captured_slot_order == []
    finally:
        await context.close()


async def test_unknown_terminal_notice_is_not_classified_as_end(browser_page: Page) -> None:
    baseline = await _show_terminal_profile(browser_page, "angel")
    assert baseline["status"] == "end", json.dumps(baseline.get("terminal"), sort_keys=True)
    await browser_page.evaluate(
        """()=>{
          document.querySelector('.book-last-dead-end__next').textContent+=' UNKNOWN NOTICE';
        }"""
    )
    assert (await _frame(browser_page))["status"] == "unknown-terminal-marker"


@pytest.mark.parametrize("profile", ["angel", "angel-observed"])
async def test_angel_optional_new_arrival_requires_exact_two_action_shape(
    browser_page: Page, profile: str,
) -> None:
    baseline = await _show_terminal_profile(browser_page, profile)
    assert baseline["status"] == "end"
    assert EbookJapanAdapter._is_verified_end_frame(baseline, total=3) is True
    await browser_page.evaluate(
        """markup=>document.querySelector('.book-last-dead-end__next')
          .insertAdjacentHTML('beforebegin',markup)""",
        NEW_ARRIVAL_MARKUP,
    )

    frame = await _frame(browser_page, current=3)
    assert frame["status"] == "end", json.dumps(frame.get("terminal"), sort_keys=True)
    terminal = frame["terminal"]
    assert terminal["moduleCounts"]["newArrival"] == 1
    assert terminal["newArrivalShapeValid"] is True
    assert terminal["partition"]["recommendNewArrival"] == 2
    assert terminal["actionPartitionComplete"] is True
    assert EbookJapanAdapter._is_verified_end_frame(frame, total=3) is True


@pytest.mark.parametrize(
    "mutation",
    [
        "module.querySelector('.recommend-grid__heading--more').remove()",
        "module.querySelector('.recommend-grid__list').remove()",
        "module.querySelector('ul').append(module.querySelector('li').cloneNode(true))",
        "module.querySelector('ul').replaceWith(Object.assign(document.createElement('div'),{innerHTML:module.querySelector('ul').outerHTML}))",
        "module.append(document.createElement('button'))",
        "module.querySelector('.recommend-grid__link').style.display='none'",
        "document.querySelector('.book-last-dead-end__next').before(module.cloneNode(true))",
        "module.closest('.book-last-dead-end__inner').querySelector('.book-last-dead-end__author').append(module)",
        "module.outerHTML=module.outerHTML.replace('<section','<div').replace('</section>','</div>')",
    ],
    ids=[
        "missing-heading", "missing-list", "duplicate-item", "nested-list-wrapper",
        "extra-action", "incomplete-visible-actions", "duplicate-module", "wrong-parent",
        "wrong-module-tag",
    ],
)
async def test_angel_new_arrival_rejects_unobserved_structure(
    browser_page: Page, mutation: str,
) -> None:
    await _show_terminal_profile(browser_page, "angel")
    await browser_page.evaluate(
        """markup=>document.querySelector('.book-last-dead-end__next')
          .insertAdjacentHTML('beforebegin',markup)""",
        NEW_ARRIVAL_MARKUP,
    )
    await browser_page.evaluate(
        f"""()=>{{const module=document.querySelector('.book-last-dead-end__new-arrival');{mutation}}}"""
    )

    frame = await _frame(browser_page, current=3)
    assert frame["status"] == "unknown-terminal-marker", json.dumps(frame.get("terminal"), sort_keys=True)


async def test_angel_observed_terminal_variant_partitions_only_scoped_controls(browser_page: Page) -> None:
    frame = await _show_terminal_profile(browser_page, "angel-observed")

    assert frame["status"] == "end", json.dumps(frame.get("terminal"), sort_keys=True)
    terminal = frame["terminal"]
    assert terminal["profile"] == "angel-dead-end-observed-controls"
    assert terminal["variant"] == "lottery-plus-native-header-v1"
    assert terminal["lotteryButtonCount"] == 1
    assert terminal["headerRootCount"] == terminal["headerBarCount"] == terminal["headerMenuCount"] == 1
    assert terminal["headerCounts"] == {
        "close-button": 1,
        "contents-button": 1,
        "settings-button": 1,
    }
    assert terminal["partition"] == {
        "review": 1,
        "coupon": 1,
        "lottery": 1,
        "recommendAuthor": 2,
        "recommendI2i": 1,
        "header": 3,
    }
    assert terminal["actionPartitionComplete"] is True


@pytest.mark.parametrize(
    "mutation",
    [
        "document.querySelector('.book-last-dead-end__banner-group').insertAdjacentHTML('beforeend','<button class=\"banner__row banner__row--lottery\">extra</button>')",
        "document.querySelector('.legacy-comic-header__menu--pc').insertAdjacentHTML('beforeend','<button class=\"contents-button\">extra</button>')",
        "document.querySelector('.legacy-comic-header').append(document.querySelector('.legacy-comic-header__menu--pc'))",
        "document.querySelector('.book-last-dead-end__next').textContent='Unknown notice'",
        "document.querySelector('.comic-viewer').insertAdjacentHTML('beforeend','<button class=\"close-button\" style=\"position:fixed;left:100px;top:100px\">outside</button>')",
    ],
    ids=["duplicate-lottery", "duplicate-header-button", "wrong-header-ancestry", "missing-marker", "fake-outside-header"],
)
@pytest.mark.parametrize("hidden_toolbar", [False, True], ids=["visible-header", "hidden-header-transient"])
async def test_angel_observed_terminal_variant_rejects_unobserved_control_shapes(
    browser_page: Page, mutation: str, hidden_toolbar: bool,
) -> None:
    baseline = await _show_terminal_profile(browser_page, "angel-observed")
    assert baseline["status"] == "end", json.dumps(baseline.get("terminal"), sort_keys=True)
    if hidden_toolbar:
        await browser_page.evaluate(
            """()=>{
              document.querySelector('.legacy-comic-header__title').style.visibility='hidden';
              document.querySelector('.legacy-comic-footer__page-output').style.visibility='hidden';
              document.querySelectorAll('.legacy-comic-header button.close-button,.legacy-comic-header button.contents-button,.legacy-comic-header button.settings-button')
                .forEach(button=>button.style.visibility='hidden');
            }"""
        )
        transient = await _frame(browser_page, current=3)
        assert transient["status"] == "unknown-terminal-marker"
    await browser_page.evaluate(f"()=>{{{mutation}}}")

    frame = await _frame(browser_page, current=3)
    assert frame["status"] == "unknown-terminal-marker"


@pytest.mark.parametrize("visible_header_count", [1, 2, 4])
async def test_hidden_angel_terminal_rejects_partial_or_extra_header_controls(
    browser_page: Page, visible_header_count: int,
) -> None:
    await _show_terminal_profile(browser_page, "angel-observed")
    await browser_page.evaluate(
        """visibleCount=>{
          document.querySelector('.legacy-comic-header__title').style.visibility='hidden';
          document.querySelector('.legacy-comic-footer__page-output').style.visibility='hidden';
          const bar=document.querySelector('.legacy-comic-header__bar');
          const buttons=[...bar.querySelectorAll('button.close-button,button.contents-button,button.settings-button')];
          buttons.forEach(button=>button.style.visibility='hidden');
          if(visibleCount===4){
            const extra=document.createElement('button');extra.className='settings-button';extra.textContent='Extra';
            extra.style.cssText='position:fixed;left:1800px;top:40px';bar.append(extra);buttons.push(extra);
          }
          buttons.slice(0,visibleCount).forEach(button=>button.style.visibility='');
        }""",
        visible_header_count,
    )

    frame = await _frame(browser_page, current=3)
    assert frame["status"] == "unknown-terminal-marker"
    if visible_header_count == 1:
        assert frame["terminal"]["headerCounts"] == {
            "close-button": 1, "contents-button": 0, "settings-button": 0,
        }
    elif visible_header_count == 2:
        assert frame["terminal"]["headerCounts"] == {
            "close-button": 1, "contents-button": 1, "settings-button": 0,
        }
    else:
        assert frame["terminal"]["unknownActionCount"] == 1


@pytest.mark.parametrize("terminal_profile", ["angel", "angel-observed", "angel-new-arrival", "muda"])
@pytest.mark.parametrize(
    "extra_markup",
    [
        '<button id="outside-action" style="position:fixed;left:100px;top:100px">Next</button>',
        '<div class="review-module" style="position:fixed;left:100px;top:100px"><button>Extra</button></div>',
        '<button class="checkout-action" style="position:fixed;left:120px;top:100px">Purchase</button>',
        '<div role="dialog" aria-modal="true" style="position:fixed;left:100px;top:100px">Notice</div>',
    ],
    ids=["outside-action", "same-class-outside-root", "purchase-extra", "modal-extra"],
)
async def test_terminal_profiles_reject_unknown_or_mixed_visible_actions(
    browser_page: Page, terminal_profile: str, extra_markup: str,
) -> None:
    baseline = await _show_terminal_profile(browser_page, terminal_profile)
    assert baseline["status"] == "end", json.dumps(baseline.get("terminal"), sort_keys=True)
    await browser_page.evaluate(
        "extra=>document.body.insertAdjacentHTML('beforeend',extra)",
        extra_markup,
    )

    frame = await _frame(browser_page, current=3)
    assert frame["status"] == "unknown-terminal-marker"
    assert frame["terminal"]["actionPartitionComplete"] is False or frame["terminal"]["modalCount"] > 0


async def test_muda_terminal_rejects_purchase_action_inside_known_module(browser_page: Page) -> None:
    baseline = await _show_terminal_profile(browser_page, "muda")
    assert baseline["status"] == "end", json.dumps(baseline.get("terminal"), sort_keys=True)
    await browser_page.evaluate(
        """()=>document.querySelector('.book-last__cta').insertAdjacentHTML(
          'beforeend','<button class="checkout-action">Purchase</button>')"""
    )
    frame = await _frame(browser_page, current=3)
    assert frame["status"] == "unknown-terminal-marker"
    assert frame["terminal"]["unknownActionCount"] == 1
    assert frame["terminal"]["actionPartitionComplete"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        "document.querySelector('.matilda-module').insertAdjacentHTML('beforeend','<a class=\"matilda-banner\" href=\"/books/134336/A000000006/\" target=\"_blank\">Duplicate</a>')",
        "document.querySelector('.matilda-banner').target='_self'",
        "document.querySelector('.matilda-banner').removeAttribute('href')",
        "document.querySelector('.matilda-banner').parentElement.className='unknown-banner-parent'",
        "document.body.insertAdjacentHTML('beforeend','<a class=\"matilda-banner\" href=\"/books/134336/A000000006/\" target=\"_blank\" style=\"position:fixed;left:40px;top:40px\">Outside</a>')",
        "document.querySelector('.book-last__banner-group').insertAdjacentHTML('beforeend','<a class=\"unknown-banner-action\" href=\"/books/134336/A000000006/\" style=\"display:block;width:100px;height:20px\">Unknown</a>')",
    ],
    ids=["duplicate", "wrong-target", "missing-href", "wrong-parent", "outside", "unknown-banner-action"],
)
async def test_muda_terminal_rejects_unobserved_matilda_or_banner_actions(
    browser_page: Page, mutation: str,
) -> None:
    baseline = await _show_terminal_profile(browser_page, "muda")
    assert baseline["status"] == "end", json.dumps(baseline.get("terminal"), sort_keys=True)
    assert baseline["terminal"]["partition"]["matildaBanner"] == 1
    await browser_page.evaluate(f"()=>{{{mutation}}}")

    frame = await _frame(browser_page, current=3)
    assert frame["status"] == "unknown-terminal-marker", json.dumps(frame.get("terminal"), sort_keys=True)
    assert frame["terminal"]["actionPartitionComplete"] is False


@pytest.mark.parametrize("pending_shape", ["header-absent", "header-controls-hidden", "partial-header", "missing-rating-action"])
async def test_muda_partial_terminal_hydration_is_loading_not_end(
    browser_page: Page, pending_shape: str,
) -> None:
    baseline = await _show_terminal_profile(browser_page, "muda")
    assert baseline["status"] == "end"
    if pending_shape == "header-absent":
        await browser_page.evaluate(
            "document.querySelector('.legacy-comic-header').remove();document.querySelector('.legacy-comic-footer').remove()"
        )
    elif pending_shape == "header-controls-hidden":
        await browser_page.evaluate(
            """()=>{document.querySelector('.legacy-comic-header__title').style.visibility='hidden';
              document.querySelector('.legacy-comic-footer__page-output').style.visibility='hidden';
              document.querySelectorAll('.legacy-comic-header button').forEach(button=>button.style.visibility='hidden');} """
        )
    elif pending_shape == "partial-header":
        await browser_page.evaluate(
            """()=>{document.querySelector('.legacy-comic-header__menu--pc button.settings-button').style.visibility='hidden';} """
        )
    else:
        await browser_page.evaluate(
            "document.querySelector('.book-last__next-item .next-item__rating')?.remove()"
        )
        await browser_page.evaluate("document.querySelector('.next-item__rating').remove()")

    frame = await _frame(browser_page, current=3)
    assert frame["status"] == "loading", json.dumps(frame.get("terminal"), sort_keys=True)
    assert frame["terminal"]["profile"] == "muda-book-last"
    assert frame["terminal"]["actionPartitionComplete"] is True
    assert EbookJapanAdapter._is_verified_end_frame(frame, total=3) is False


async def test_muda_core_waits_for_header_and_known_actions_before_end(
    browser_page: Page, tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from screenshot_crawler.site_adapters.ebookjapan import adapter as adapter_module

    monkeypatch.setattr(adapter_module, "_FRAME_READY_WAIT_MS", 1_500)
    monkeypatch.setattr(adapter_module, "_FRAME_POLL_MS", 20)
    original_evaluate = browser_page.evaluate
    samples: list[dict[str, object]] = []

    async def collect_frames(expression, *args, **kwargs):
        result = await original_evaluate(expression, *args, **kwargs)
        if expression == FRAME_STATE_JS and isinstance(result, dict):
            samples.append(result)
        return result

    monkeypatch.setattr(browser_page, "evaluate", collect_frames)
    adapter, result = await _run_neutral_core_flow(
        browser_page, tmp_path, mode="muda-transient-header", max_pages=10, terminal_profile="muda",
    )
    assert result.stop_state.value == "end"
    assert len(result.pages) == 3
    assert adapter._capture_coverage_complete() is True
    assert adapter._terminal_end_verified is True
    transient = [sample for sample in samples if sample.get("status") == "loading"]
    assert any(sample["terminal"].get("headerRootCount") == 0 for sample in transient)
    assert any(
        sample["terminal"].get("headerRootCount") == 1
        and sample["terminal"].get("headerCounts") == {
            "close-button": 0, "contents-button": 0, "settings-button": 0,
        }
        for sample in transient
    )
    settled = [sample for sample in samples if sample.get("status") == "end"]
    assert settled
    assert settled[-1]["terminal"]["partition"]["matildaBanner"] == 1
    assert settled[-1]["terminal"]["headerCounts"] == {
        "close-button": 1, "contents-button": 1, "settings-button": 1,
    }


async def test_muda_persistent_partial_header_times_out_without_end_or_zip(
    browser_page: Page, tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from screenshot_crawler.site_adapters.ebookjapan import adapter as adapter_module

    monkeypatch.setattr(adapter_module, "_FRAME_READY_WAIT_MS", 180)
    monkeypatch.setattr(adapter_module, "_FRAME_POLL_MS", 10)
    with pytest.raises(UnknownPageStateError, match="did not produce a new full content frame"):
        await _run_neutral_core_flow(
            browser_page,
            tmp_path,
            mode="muda-persistent-partial-header",
            max_pages=10,
            terminal_profile="muda",
        )
    assert not list(tmp_path.rglob("*.zip"))


async def test_muda_terminal_accepts_observed_author_heading_in_tall_viewport(browser_page: Page) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 1600})
    baseline = await _show_terminal_profile(browser_page, "muda")
    assert baseline["status"] == "end", json.dumps(baseline.get("terminal"), sort_keys=True)

    frame = await _frame(browser_page, current=3)
    assert frame["status"] == "end", json.dumps(frame.get("terminal"), sort_keys=True)
    assert frame["terminal"]["partition"]["author"] == 2


@pytest.mark.parametrize("terminal_profile", ["angel", "angel-observed", "muda"])
async def test_terminal_profile_does_not_accept_visible_page_canvas(
    browser_page: Page, terminal_profile: str,
) -> None:
    await _open_reader(browser_page, current=3, total=3, slot_count=3, terminal_profile=terminal_profile)
    await _draw_full_same_size(browser_page)
    await browser_page.evaluate(
        """profile=>{
          const slots=[...document.querySelectorAll('.comic-viewer__page-slot')];
          slots.forEach((slot,index)=>slot.style.display=index===0?'block':'none');
          slots[0].style.left='0px';
          document.querySelector('.seekbar__slider').style.display='none';
          document.querySelector('.comic-viewer__custom-cell--interactive').style.display='block';
          document.querySelector('.viewer-last-shell').style.display='block';
          if(profile==='angel')document.querySelector('.book-last-dead-end').style.display='block';
        }""",
        terminal_profile,
    )

    frame = await _frame(browser_page, current=3)
    assert frame["status"] != "end"
    assert frame["visibleSlots"]


@pytest.mark.parametrize("terminal_profile", ["angel", "angel-observed", "muda"])
async def test_adapter_traverses_all_pinned_slots_before_accepting_neutral_end(
    browser_page: Page, terminal_profile: str,
) -> None:
    await _open_reader(
        browser_page, current=1, total=3, slot_count=3, terminal_profile=terminal_profile
    )
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

    await browser_page.evaluate("window.__terminalAdvanceClicks=0;document.addEventListener('click',()=>window.__terminalAdvanceClicks++)")
    await adapter.go_next(browser_page)
    terminal_snapshot = await browser_page.evaluate(FRAME_STATE_JS, {"expectedCurrent": 2})
    assert terminal_snapshot["status"] == "end", json.dumps(terminal_snapshot.get("terminal"), sort_keys=True)
    assert terminal_snapshot["terminal"]["profile"] == {
        "angel": "angel-dead-end",
        "angel-observed": "angel-dead-end-observed-controls",
        "muda": "muda-book-last",
    }[terminal_profile]
    assert terminal_snapshot["terminal"]["visiblePageCanvasCount"] == 0
    assert adapter._capture_coverage_complete() is True
    await adapter.wait_for_change(browser_page, spread_identity)
    assert await adapter.detect_state(browser_page) == "end"
    assert adapter._terminal_end_verified is True
    clicks_at_end = await browser_page.evaluate("window.__terminalAdvanceClicks")
    assert clicks_at_end == 1
    with pytest.raises(UnknownPageStateError, match="not ready"):
        await adapter.go_next(browser_page)
    assert await browser_page.evaluate("window.__terminalAdvanceClicks") == clicks_at_end


@pytest.mark.parametrize("terminal_profile", ["angel", "angel-observed"])
async def test_reader_end_is_rejected_until_every_frozen_slot_was_captured(
    browser_page: Page, terminal_profile: str,
) -> None:
    await _open_reader(
        browser_page, current=1, total=3, slot_count=3, terminal_profile=terminal_profile
    )
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
          document.querySelector('.seekbar__slider').style.display='none';
          document.querySelector('.comic-viewer__custom-cell--interactive').style.display='block';
          document.querySelector('.viewer-last-shell').style.display='block';
          document.querySelector('.book-last-dead-end').style.display='block';
        }"""
    )

    with pytest.raises(UnknownPageStateError, match="before complete ordered"):
        await adapter.detect_state(browser_page)
    assert adapter._seen_slot_ids == set()
    assert adapter._terminal_end_verified is False


async def test_navigation_uses_a_bound_hit_without_rechecking_global_d_surface(
    browser_page: Page,
) -> None:
    adapter, identity = await _capture_neutral_cover(browser_page)
    await browser_page.evaluate(
        """()=>{
          const overlay=document.createElement('div');
          overlay.style='position:fixed;left:200px;top:200px;width:20px;height:20px;z-index:99999;background:red;pointer-events:none';
          document.body.append(overlay);
          const hidden=document.createElement('div');hidden.setAttribute('role','dialog');hidden.setAttribute('aria-modal','true');hidden.style.display='none';
          document.body.append(hidden);
        }"""
    )
    state = await _frame(browser_page)
    assert state["status"] == "content"
    assert state["parts"][0]["captureSurfaceSafe"] is False
    await adapter.go_next(browser_page)
    await adapter.wait_for_change(browser_page, identity)
    assert await browser_page.evaluate("window.__fixtureClickCount") == 1


@pytest.mark.parametrize("target_kind", ["cta", "visible-modal", "unknown-element", "interactive-ancestor"])
async def test_navigation_rejects_interactive_or_modal_hit_without_click(
    browser_page: Page, target_kind: str,
) -> None:
    adapter, _identity = await _capture_neutral_cover(browser_page)
    if target_kind == "cta":
        await browser_page.evaluate(
            """()=>{const b=document.createElement('button');b.id='navigation-cta';
              b.style='position:fixed;left:0;top:calc(50vh - 20px);width:24px;height:40px;z-index:99999';
              b.addEventListener('click',()=>window.__unsafeActionClick=(window.__unsafeActionClick||0)+1);document.body.append(b);} """
        )
    elif target_kind == "visible-modal":
        await browser_page.evaluate(
            """()=>{const modal=document.createElement('div');modal.setAttribute('role','dialog');
              modal.setAttribute('aria-modal','true');modal.style='position:fixed;left:700px;top:100px;width:50px;height:50px;background:#fff;z-index:99999';
              document.body.append(modal);} """
        )
    elif target_kind == "unknown-element":
        await browser_page.evaluate(
            """()=>{const unknown=document.createElement('div');unknown.id='navigation-unknown';
              unknown.style='position:fixed;left:0;top:calc(50vh - 20px);width:24px;height:40px;z-index:99999;background:#ddd';
              document.body.append(unknown);} """
        )
    else:
        await browser_page.evaluate(
            """()=>{const slot=document.querySelector('.comic-viewer__page-slot[data-index="2"]');
              const link=document.createElement('a');link.href='#navigation-ancestor-clicked';link.style='display:contents';
              link.addEventListener('click',()=>window.__ancestorLinkClicks=(window.__ancestorLinkClicks||0)+1);
              slot.before(link);link.append(slot);} """
        )

    with pytest.raises(UnknownPageStateError, match="hit is not bound"):
        await adapter.go_next(browser_page)
    assert await browser_page.evaluate("window.__fixtureClickCount") == 0
    assert await browser_page.evaluate("window.__unsafeActionClick||0") == 0
    assert await browser_page.evaluate("window.__ancestorLinkClicks||0") == 0


@pytest.mark.parametrize("drift", ["geometry", "paint", "node"])
async def test_navigation_rejects_frame_drift_before_click(
    browser_page: Page, monkeypatch: pytest.MonkeyPatch, drift: str,
) -> None:
    from screenshot_crawler.site_adapters.ebookjapan import adapter as adapter_module

    adapter, _identity = await _capture_neutral_cover(browser_page)
    if drift == "geometry":
        await browser_page.evaluate(
            """()=>document.querySelector('.comic-viewer__page-slot[data-index="2"]').style.left='1px'"""
        )
    elif drift == "paint":
        await browser_page.evaluate(
            """()=>{const c=document.querySelector('.comic-viewer__page-slot[data-index="2"] canvas');
              const s=document.createElement('canvas');s.width=c.width;s.height=c.height;
              s.getContext('2d').fillRect(0,0,s.width,s.height);c.getContext('2d').drawImage(s,0,0);} """
        )
    else:
        monkeypatch.setattr(adapter_module, "_FRAME_READY_WAIT_MS", 100)
        await browser_page.evaluate(
            """()=>{const c=document.querySelector('.comic-viewer__page-slot[data-index="2"] canvas');c.replaceWith(c.cloneNode());} """
        )

    with pytest.raises(UnknownPageStateError):
        await adapter.go_next(browser_page)
    assert await browser_page.evaluate("window.__fixtureClickCount") == 0
    assert adapter._transition_pending is False


@pytest.mark.parametrize("race", ["geometry", "paint"])
async def test_navigation_final_sample_rechecks_committed_canvas_state(
    browser_page: Page, monkeypatch: pytest.MonkeyPatch, race: str,
) -> None:
    from screenshot_crawler.site_adapters.ebookjapan.viewer import NAVIGATION_TARGET_JS

    adapter, _identity = await _capture_neutral_cover(browser_page)
    original_evaluate = browser_page.evaluate

    async def mutate_before_final_sample(expression, *args, **kwargs):
        if expression == NAVIGATION_TARGET_JS:
            if race == "geometry":
                await original_evaluate(
                    """()=>document.querySelector('.comic-viewer__page-slot[data-index="2"]').style.left='1px'"""
                )
            else:
                await original_evaluate(
                    """()=>{const c=document.querySelector('.comic-viewer__page-slot[data-index="2"] canvas');
                      const s=document.createElement('canvas');s.width=c.width;s.height=c.height;
                      s.getContext('2d').fillRect(0,0,s.width,s.height);c.getContext('2d').drawImage(s,0,0);} """
                )
        return await original_evaluate(expression, *args, **kwargs)

    monkeypatch.setattr(browser_page, "evaluate", mutate_before_final_sample)
    with pytest.raises(UnknownPageStateError, match="hit is not bound"):
        await adapter.go_next(browser_page)
    assert await original_evaluate("window.__fixtureClickCount") == 0
    assert adapter._transition_pending is False


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
