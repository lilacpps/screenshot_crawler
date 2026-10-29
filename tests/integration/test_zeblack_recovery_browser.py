from __future__ import annotations

import asyncio

import pytest
from playwright.async_api import Page

from screenshot_crawler.batch import BatchCandidate
from screenshot_crawler.core.errors import PageChangeTimeoutError
from screenshot_crawler.site_adapters.zeblack.adapter import ZeblackAdapter
from screenshot_crawler.site_adapters.zeblack.discovery_protobuf import ConsumptionStatus as Status
from screenshot_crawler.site_adapters.zeblack.live_access import ZeblackLiveAccessError
from screenshot_crawler.site_adapters.zeblack.recovery import observe_ticket_stock

pytestmark = pytest.mark.asyncio(loop_scope="module")
ROOT = "https://zebrack-comic.shueisha.co.jp"
LIST = ROOT + "/title/5123/chapter/list"
PREVIOUS = ROOT + "/title/5123/chapter/100/viewer"
TARGET = ROOT + "/title/5123/chapter/900/viewer"
API = "https://api2.zebrack-comic.com/api/v3/title_chapter_list"
GIF = "R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=="


def _varint(value):
    result = bytearray()
    while value >= 128:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def _number(field, value):
    return _varint(field << 3) + _varint(value)


def _bytes(field, value):
    return _varint((field << 3) | 2) + _varint(len(value)) + value


def _chapter(cid, status, remaining=None):
    body = (_number(1, cid) + _number(2, 5123) + _bytes(3, f"#{cid}".encode())
            + _number(7, 1) + _number(11, int(status)))
    if remaining is not None:
        body += _number(5, remaining)
    return _bytes(1, body)


def _candidate():
    return BatchCandidate(
        item_id=1, source_id=1, target_id=1, site="zeblack", backend="web",
        target_key="default", locator=TARGET, external_id="900", work_id=1,
        access_mode="quota", access_strategy="quota", consumes_quota=True,
        quota_resource="work_ticket",
    )


def _viewer(*, start=0, broken=False):
    return f"""<meta charset="utf-8"><style>
      img {{width:70px;height:100px}} #ad,#final {{display:none;width:300px;height:200px}}
      button.sc-bEHKTb {{width:40px;height:40px}}
    </style><button class="sc-bEHKTb"></button><div id="body"></div>
    <div id="ad" class="-KWKsa_spread"><iframe srcdoc="fixture"></iframe></div>
    <div id="final"><button id="next-story">次の話を読む</button></div>
    <script>
      let stage={start};
      const content=document.querySelector('#body');
      const ad=document.querySelector('#ad'), final=document.querySelector('#final');
      function render() {{
        for(const img of content.children) img.style.display=img.alt==='page_'+stage?'block':'none';
        ad.style.display=stage===3?'block':'none';
        final.style.display=stage===4?'block':'none';
        console.log('fixture-stage:'+stage);
      }}
      window.ready=(async()=>{{
        const bytes=Uint8Array.from(atob('{GIF}'),c=>c.charCodeAt(0));
        for(let i=0;i<3;i++) {{
          const img=new Image();img.alt='page_'+i;
          img.src=URL.createObjectURL(new Blob([bytes],{{type:'image/gif'}}));
          content.appendChild(img);await img.decode();
        }}
        render();
      }})();
      document.addEventListener('keydown',e=>{{
        if ({str(broken).lower()}) return;
        if(e.key==='ArrowLeft') stage=Math.min(stage+1,4);
        else if(e.key==='ArrowRight') stage=Math.max(stage-1,0);
        else return;
        render();
      }});
      document.querySelector('#next-story').onclick=()=>console.log('fixture-next-click');
      document.querySelector('button.sc-bEHKTb').onclick=async()=>{{
        if(stage!==4) throw Error('premature close');
        await fetch('/fixture-closed');location.assign('{LIST}');
      }};
    </script>"""


async def _install(
    page, *, predecessor=Status.RENTAL, remaining=10000, stock=1,
    restored=True, older_available=False, start=0, bad_order=False, broken=False,
):
    state = {"closed": 0, "list_loads": 0, "viewers": [], "stages": [], "next_clicks": 0}

    def console(message):
        if message.text.startswith("fixture-stage:"):
            state["stages"].append(int(message.text.split(":")[1]))
        elif message.text == "fixture-next-click":
            state["next_clicks"] += 1

    page.on("console", console)

    async def route(request):
        url = request.request.url
        if url == API:
            payload = _chapter(50, Status.TICKET_AVAILABLE if older_available else Status.FREE)
            payload += _chapter(100, predecessor, remaining)
            payload += _chapter(900, Status.TICKET_AVAILABLE if state["closed"] and restored
                                else Status.POINT)
            await request.fulfill(body=payload, headers={
                "content-type": "application/protobuf", "access-control-allow-origin": "*",
            })
        elif url == LIST:
            state["list_loads"] += 1
            ids = [50, 100, 900] if not bad_order else [50, 100, 100, 900]
            rows = ''.join(f'<div id="chapter{i}" style="height:50px"><p>#{i}</p></div>'
                           for i in ids)
            html = f"""<meta charset="utf-8">{rows}<script>
              fetch('{API}');window.ticketClicks=0;
              document.querySelector('#chapter900 p').onclick=()=>{{
                const modal=document.createElement('div');
                modal.innerHTML='<p>#900</p><button id="ticket">チケットを使って読む</button>'+
                  '<button>キャンセル</button>';
                document.body.appendChild(modal);
                document.querySelector('#ticket').onclick=async()=>{{
                  window.ticketClicks++;
                  history.pushState({{}},'', '{TARGET}');
                  const bytes=Uint8Array.from(atob('{GIF}'),c=>c.charCodeAt(0));
                  const img=new Image();img.alt='page_0';
                  img.src=URL.createObjectURL(new Blob([bytes],{{type:'image/gif'}}));
                  document.body.replaceChildren(img);await img.decode();
                }};
              }};
            </script>"""
            await request.fulfill(body=html, content_type="text/html")
        elif url == ROOT + "/title/5123":
            await request.fulfill(body=f'<meta charset="utf-8"><h1>Fixture</h1><div>'
                                  f'<div><img alt="チケット" src="data:image/gif;base64,{GIF}">'
                                  f'<span>× {stock}</span></div><p>チケットでさっそく読もう！</p></div>',
                                  content_type="text/html")
        elif url == PREVIOUS:
            state["viewers"].append(url)
            await request.fulfill(body=_viewer(start=start, broken=broken), content_type="text/html")
        elif url == ROOT + "/fixture-closed":
            state["closed"] += 1
            await request.fulfill(body="ok")
        else:
            raise AssertionError(f"Unexpected navigation/request (possible consumption): {url}")

    await page.route("**/*", route)
    return state


@pytest.mark.parametrize("older_available,start", [(False, 0), (True, 1)])
async def test_recovery_rereads_from_start_then_reuses_final_document_for_ticket_entry(
    browser_page: Page, older_available, start,
):
    state = await _install(browser_page, older_available=older_available, start=start)
    adapter = ZeblackAdapter()
    budget = adapter.configure_access_resource_resolution(timeout_ms=15000, page_turn_delay_ms=0)
    assert budget == 180000
    result = await adapter.resolve_access_resource_candidates(browser_page, (_candidate(),), "work_ticket")
    assert result.selected_source_ids == (1,)
    assert state["closed"] == 1 and state["list_loads"] == 4
    assert state["viewers"] == [PREVIOUS]
    assert state["stages"] == ([1, 0, 1, 2, 3, 4] if start else [0, 1, 2, 3, 4])
    assert state["next_clicks"] == 0
    assert await browser_page.evaluate("window.ticketClicks") == 0
    await adapter.configure_run(browser_page, "quota")
    await adapter.configure_quota_resource(browser_page, "work_ticket")
    assert adapter.resolve_initial_navigation_url(TARGET) == LIST
    assert await adapter.adopt_prepared_access_entry(browser_page, TARGET)
    await adapter.initialize_entry_only(browser_page)
    assert adapter.get_access_consumption().consumed is True
    assert await browser_page.evaluate("window.ticketClicks") == 1
    assert state["list_loads"] == 4


@pytest.mark.parametrize("status,remaining,stock,blocked,reason", [
    (Status.RENTAL, 0, 1, False, "requires_access"),
    (Status.RENTAL, None, 1, False, "requires_access"),
    (Status.RENTAL, 1, 1, False, "requires_access"),
    (Status.POINT, None, 1, False, "requires_access"),
    (Status.TICKET_AVAILABLE, None, 1, False, "requires_access"),
    (Status.COIN, None, 1, False, "predecessor_paid"),
    (Status.RENTAL, 10000, 0, False, "stock_unconfirmed_or_empty"),
    (Status.RENTAL, 10000, 1, True, "predecessor_excluded"),
])
async def test_recovery_never_opens_a_predecessor_requiring_rights(
    browser_page: Page, status, remaining, stock, blocked, reason,
):
    state = await _install(browser_page, predecessor=status, remaining=remaining, stock=stock)
    adapter = ZeblackAdapter()
    adapter.configure_access_resource_resolution(
        timeout_ms=15000, page_turn_delay_ms=0,
        blocked_external_ids=frozenset({"100"}) if blocked else frozenset(),
    )
    result = await adapter.resolve_access_resource_candidates(browser_page, (_candidate(),), "work_ticket")
    assert result.selected_source_ids == ()
    assert reason in result.skipped_source_reasons[0][1]
    assert state["viewers"] == [] and state["closed"] == 0
    assert adapter.get_access_consumption().consumed is False


async def test_recovery_does_not_repeat_reading_if_availability_stays_unavailable(browser_page):
    state = await _install(browser_page, restored=False, predecessor=Status.FREE, remaining=None)
    adapter = ZeblackAdapter()
    adapter.configure_access_resource_resolution(timeout_ms=15000, page_turn_delay_ms=0)
    result = await adapter.resolve_access_resource_candidates(browser_page, (_candidate(),), "work_ticket")
    assert result.selected_source_ids == ()
    assert result.skipped_source_reasons == ((1, "work_ticket_unavailable_after_reread"),)
    assert state["closed"] == 1 and state["viewers"] == [PREVIOUS]


async def test_recovery_rejects_ambiguous_listing_before_reader(browser_page):
    state = await _install(browser_page, bad_order=True)
    adapter = ZeblackAdapter()
    with pytest.raises(ZeblackLiveAccessError, match="duplicate"):
        await adapter.resolve_access_resource_candidates(browser_page, (_candidate(),), "work_ticket")
    assert state["viewers"] == []


@pytest.mark.parametrize("failure", ["no_change", "max_pages", "deadline"])
async def test_recovery_bounds_reading_and_never_reaches_a_consuming_control(
    browser_page, monkeypatch, failure,
):
    state = await _install(browser_page, broken=failure == "no_change")
    if failure == "no_change":
        monkeypatch.setattr(ZeblackAdapter, "page_change_timeout_ms", 100)
    elif failure == "max_pages":
        monkeypatch.setattr("screenshot_crawler.site_adapters.zeblack.recovery.MAX_REREAD_PAGES", 1)
    else:
        monkeypatch.setattr("screenshot_crawler.site_adapters.zeblack.recovery.RECOVERY_TIMEOUT_MS", 1)
        async def stalled_stock(*_args, **_kwargs):
            await asyncio.Event().wait()
        monkeypatch.setattr(
            "screenshot_crawler.site_adapters.zeblack.recovery.observe_ticket_stock", stalled_stock,
        )
    adapter = ZeblackAdapter()
    adapter.configure_access_resource_resolution(timeout_ms=15000, page_turn_delay_ms=0)
    with pytest.raises(TimeoutError if failure == "deadline" else PageChangeTimeoutError):
        await adapter.resolve_access_resource_candidates(browser_page, (_candidate(),), "work_ticket")
    assert state["closed"] == 0 and state["next_clicks"] == 0
    assert adapter.get_access_consumption().consumed is False


@pytest.mark.parametrize("banner,expected_error", [
    ('<div><img alt="チケット"><span>× 1</span><p>チケットでさっそく読もう！</p></div>' * 2, True),
    ('<div><img alt="チケット利用可"><span>× 1</span><p>チケットでさっそく読もう！</p></div>', False),
    (('<div style="display:none"><img alt="チケット"><span>× 1</span>'
      '<p>チケットでさっそく読もう！</p></div>'), False),
])
async def test_stock_requires_unique_visible_title_banner(browser_page, banner, expected_error):
    async def route(request):
        await request.fulfill(
            body='<meta charset="utf-8"><style>img{width:16px;height:16px}</style>'+banner,
            content_type="text/html; charset=utf-8",
        )

    await browser_page.route("**/*", route)
    if expected_error:
        with pytest.raises(ZeblackLiveAccessError, match="ambiguous"):
            await observe_ticket_stock(browser_page, "5123", timeout_ms=100)
    else:
        assert await observe_ticket_stock(browser_page, "5123", timeout_ms=100) is None
