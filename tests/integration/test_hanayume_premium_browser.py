"""Artificial native/UI contracts; never call the live site."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from playwright.async_api import Error as PlaywrightError

from screenshot_crawler.core.errors import (
    AccessConsumptionUnconfirmedError,
    AccessResourceUnavailableError,
    UnknownPageStateError,
)
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.hanayume import premium_access as premium
from screenshot_crawler.site_adapters.hanayume.adapter import HanayumeAdapter
from tests.integration.test_hanayume_adapter_browser import (
    EPISODE_ID,
    EPISODE_URL,
    NOW_ID,
    WORK_ID,
    _episode_html,
    _row,
    _ticket_row,
)

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest.fixture(autouse=True)
def short_waits(monkeypatch):
    monkeypatch.setattr(premium, "READY_SECONDS", 0.6)
    monkeypatch.setattr(premium, "RECOVERY_SECONDS", 0.6)
    from screenshot_crawler.site_adapters.hanayume import adapter
    monkeypatch.setattr(adapter, "INITIAL_CANVAS_QUIET_MS", 30)
    monkeypatch.setattr(adapter, "INITIAL_CANVAS_POLL_INTERVAL_MS", 10)


async def install(page, *, count=3, case="ok", initial=False):
    state = {"count": count, "access": initial, "checkouts": 0, "paths": [], "gacha": 0}
    html = _episode_html(current=1, episode_rows=[(NOW_ID, "")], episode_history_rows=[(NOW_ID, "")])
    html = html.replace('<header id="xHeader">', '<header id="xHeader" class="ep-h">')
    html = html.replace('class="series-eplist mode-user"', 'class="series-eplist mode-user mode-has-eps"')
    html = html.replace(_row(NOW_ID, ""), _ticket_row(NOW_ID, account=False, target=False), 1)
    html = html.replace(_row(NOW_ID, ""), _ticket_row(NOW_ID, account=True, target=False), 1)
    charge = '''<div class="ep-main-content mode-charge"><div class="ep-charge">
      <div class="ep-charge-act"><button type="button" class="ep-charge-act-btn" data-e2e="ifRead">「すぐ無料」で読む<span class="ep-charge-act-btn-price mode-ticket">1枚</span></button>
      <button type="button" id="paid">80コインで購入</button></div>
      <div class="ep-charge-wallet"><span data-e2e="epChgWalletTicket">STOCK</span></div>
      <dialog class="dialog" data-e2e="pop"><div class="dialog-h-price">1枚</div>
        <div class="dialog-term-term">15日間</div>
        <button type="button" class="dialog-btn mode-buy" data-e2e="rentConf">レンタルする</button>
      </dialog></div></div>'''.replace("STOCK", str(count))
    if case == "duplicate":
        charge = charge.replace('<button type="button" id="paid">', '<button data-e2e="ifRead">duplicate</button><button type="button" id="paid">')
    if case == "cost":
        charge = charge.replace('class="dialog-h-price">1枚', 'class="dialog-h-price">80コイン')
    if case == "term":
        charge = charge.replace('>15日間<', '>3日間<')
    if case == "hidden":
        charge = charge.replace('data-e2e="ifRead"', 'data-e2e="ifRead" style="display:none"')
    if case == "transparent":
        charge = charge.replace('data-e2e="ifRead"', 'data-e2e="ifRead" style="opacity:0"')
    if case == "disabled":
        charge = charge.replace('data-e2e="ifRead"', 'data-e2e="ifRead" disabled')
    if case == "paid-attribute":
        charge = charge.replace('data-e2e="rentConf"', 'data-e2e="rentConf" data-buy-price="80"')
    html = html.replace('<div id="comici-viewer"', ("" if initial else charge) + '<div id="comici-viewer"')
    script = f'''<script>
      window.entryClicks=0;window.confirmClicks=0;window.paidClicks=0;
      const viewer=document.querySelector('#comici-viewer');
      viewer.style.display={json.dumps('block' if initial else 'none')};
      fetch('/api/userPoint');fetch('/api/episodes/{EPISODE_ID}');
      document.querySelector('#paid')?.addEventListener('click',()=>window.paidClicks++);
      document.querySelector('[data-e2e="ifRead"]')?.addEventListener('click',()=>{{
        window.entryClicks++;document.querySelector('dialog').showModal();
      }});
      document.querySelector('[data-e2e="rentConf"]')?.addEventListener('click',async()=>{{
        window.confirmClicks++;
        const response=await fetch('/api/checkout/rental',{{method:'POST',body:JSON.stringify({{
          articleIds:['{NOW_ID if case == 'wrong-episode-body' else EPISODE_ID}'],amount:{80 if case == 'wrong-body' else 0},ticketCount:{'true' if case == 'boolean-body' else 1}
        }})}});
        await fetch('/api/episodes/{EPISODE_ID}');await fetch('/api/userPoint');
        if(response.ok && {json.dumps(case != 'viewer-stuck')}){{
          document.querySelector('.ep-main-content').remove();viewer.style.display='block';
        }}
      }});
    </script>'''
    html += script

    async def route(r):
        path = urlsplit(r.request.url).path
        state["paths"].append(path)
        if path == f"/episodes/{EPISODE_ID}":
            await r.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)
        elif path == "/api/userPoint":
            await r.fulfill(json={"bonusValue": state["count"], "paidCoin": 0})
        elif path == f"/api/episodes/{EPISODE_ID}":
            await r.fulfill(json={"episode": {
                "id": NOW_ID if case == "wrong-id" else EPISODE_ID,
                "series": {"id": WORK_ID, "waitAndFreeRecoveryTime": 0 if case == "work-ready" else 60000},
                "access": {"episodeId": EPISODE_ID, "hasAccess": state["access"],
                           "accessType": "purchased" if state["access"] else "waitAndFree",
                           "timeRemainingInSeconds": 1295999 if state["access"] else None,
                           "isDisableBonus": case == "coin-only"},
            }})
        elif path == "/api/checkout/rental":
            state["checkouts"] += 1
            state["access"] = True
            if case != "no-debit":
                state["count"] -= 1
            await r.fulfill(status=200, json={"message": "ok"})
        else:
            await r.fulfill(status=404)
    await page.route("https://hanayume.com/**", route)
    adapter = HanayumeAdapter()
    await adapter.configure_target_identity(f"{WORK_ID}:{EPISODE_ID}", "synthetic")
    await adapter.prepare_page(page)
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "premium_ticket")
    adapter.resolve_initial_navigation_url(EPISODE_URL)
    await page.goto(EPISODE_URL)
    return adapter, state


@pytest.mark.parametrize("count", [1, 3])
@pytest.mark.parametrize("entry_only", [False, True])
async def test_premium_exact_two_step_entry_and_15_day_grant(browser_page, count, entry_only):
    adapter, state = await install(browser_page, count=count)
    if entry_only:
        await adapter.initialize_entry_only(browser_page)
    else:
        await adapter.initialize(browser_page)
        assert await adapter.detect_state(browser_page) is PageState.CONTENT
    consumption = adapter.get_access_consumption()
    assert consumption.consumed and consumption.resource == "premium_ticket"
    assert consumption.stop_resource_pass == (count == 1)
    assert datetime.now(UTC) + timedelta(days=14) < consumption.access_granted_until < datetime.now(UTC) + timedelta(days=15)
    assert state["checkouts"] == 1 and state["count"] == count - 1
    debug = await adapter.collect_debug_metadata(browser_page)
    assert debug["premium_ticket"] == {
        "entry_only": entry_only, "action_attempted": True,
        "checkout_dispatched": True, "consumption_confirmed": True,
    }
    assert await browser_page.evaluate("[entryClicks,confirmClicks,paidClicks]") == [1, 1, 0]
    assert not any(p.startswith('/series/') for p in state['paths'])


@pytest.mark.parametrize("case", ["duplicate", "cost", "term", "hidden", "disabled", "paid-attribute",
                                  "wrong-id", "work-ready", "coin-only", "wrong-body",
                                  "boolean-body", "wrong-episode-body", "transparent"])
async def test_premium_invalid_ui_or_identity_never_dispatches_checkout(browser_page, case):
    adapter, state = await install(browser_page, case=case)
    with pytest.raises((UnknownPageStateError, AccessResourceUnavailableError,
                        AccessConsumptionUnconfirmedError, PlaywrightError)):
        await adapter.initialize_entry_only(browser_page)
    assert state["checkouts"] == 0 and state["count"] == 3
    assert not adapter.get_access_consumption().consumed
    assert await browser_page.evaluate("paidClicks") == 0


@pytest.mark.parametrize("case", ["no-debit", "viewer-stuck"])
async def test_no_reclick_and_confirmed_debit_survives_viewer_failure(browser_page, case):
    adapter, state = await install(browser_page, case=case)
    with pytest.raises(AccessConsumptionUnconfirmedError):
        await adapter.initialize_entry_only(browser_page)
    assert state["checkouts"] == 1
    assert adapter.get_access_consumption().consumed == (case == "viewer-stuck")
    assert await browser_page.evaluate("confirmClicks") == 1


async def test_zero_and_already_accessible_never_click(browser_page):
    adapter, state = await install(browser_page, count=0)
    with pytest.raises(AccessResourceUnavailableError) as error:
        await adapter.initialize_entry_only(browser_page)
    assert error.value.stop_resource_pass
    assert state["checkouts"] == 0


@pytest.mark.parametrize("count", [None, True, -1, "3"])
async def test_unknown_stock_stops_without_trying_a_ticket(browser_page, count):
    adapter, state = await install(browser_page, count=count)
    with pytest.raises(UnknownPageStateError):
        await adapter.initialize_entry_only(browser_page)
    assert state["checkouts"] == 0
    assert await browser_page.evaluate("[entryClicks,confirmClicks,paidClicks]") == [0, 0, 0]


@pytest.mark.parametrize("entry_only", [True, False])
async def test_preexisting_grant_does_not_spend_or_invent_consumption(browser_page, entry_only):
    adapter, state = await install(browser_page, initial=True)
    if entry_only:
        with pytest.raises(premium.AlreadyAccessible) as error:
            await adapter.initialize_entry_only(browser_page)
        assert error.value.stop_work is False
    else:
        await adapter.initialize(browser_page)
    assert state["checkouts"] == 0 and not adapter.get_access_consumption().consumed


@pytest.mark.parametrize("count", [0, 2])
@pytest.mark.parametrize("adapter_hook", [False, True])
async def test_stock_resolver_never_walks_large_quota_pool(browser_page, monkeypatch, count, adapter_hook):
    adapter, state = await install(browser_page, count=count)
    async def daily(page, observer, **kwargs):
        if adapter_hook:
            assert not resolver._batch_route_guard_enabled
        await page.goto(EPISODE_URL)
        await observer.wait("stock")
    monkeypatch.setattr(premium, "prepare_daily_gacha", daily)
    pool = tuple(SimpleNamespace(site="hanayume", work_id=1, source_id=i,
                                external_id=f"{WORK_ID}:{EPISODE_ID if i == 0 else f'{i:013x}'}",
                                locator=premium.HOME+"episodes/"+(EPISODE_ID if i == 0 else f'{i:013x}'),
                                quota_resource="premium_ticket", access_strategy="quota", consumes_quota=True)
                 for i in range(9000))
    if adapter_hook:
        resolver = HanayumeAdapter()
        result = await resolver.resolve_access_resource_candidates(browser_page, pool, "premium_ticket", timeout_ms=1000)
        assert resolver._batch_route_guard_enabled == (count > 0)
    else:
        result = await premium.resolve_ticket_candidates(browser_page, pool, "premium_ticket", timeout_ms=1000)
    assert result.selected_source_ids == tuple(range(count))
    assert result.stop_resource_pass == (count == 0)
    assert {p for p in state["paths"] if p.startswith('/episodes/')} == {f'/episodes/{EPISODE_ID}'}
    assert state["checkouts"] == 0
    await adapter._premium_entry.observer.close()


@pytest.mark.parametrize("mode", ["absent", "hidden", "used", "win", "zero", "uncertain",
                                  "popup-late", "popup-none", "popup-legacy",
                                  "popup-gacha", "popup-gacha-late", "popup-both"])
async def test_daily_gacha_once_or_absent_never_shares_or_retries(browser_page, monkeypatch,
                                                               capsys, mode):
    settles = []
    original_sleep = asyncio.sleep
    async def sleep(delay):
        if delay == premium.GACHA_SETTLE_SECONDS:
            settles.append(delay)
            await original_sleep(0.05)
        else:
            await original_sleep(delay)
    monkeypatch.setattr(premium.asyncio, "sleep", sleep)
    counts = {"spin": 0, "share": 0, "close": 0}
    home = '''<header id="xHeader"><button data-e2e="signoutBtn">Logout</button></header>
      <dialog class="dialog mode-campaign" data-e2e="pop"><button type="submit" class="dialog-btn mode-campaign" data-e2e="popClose" onclick="console.log('closed-campaign');this.closest('dialog').close()">Close</button></dialog>
      <script>document.querySelector('dialog').showModal()</script>'''
    if mode == "popup-late":
        home = home.replace("document.querySelector('dialog').showModal()", "setTimeout(()=>{document.querySelector('dialog').showModal();document.querySelector('.home-gacha-btn').style.pointerEvents='auto'},150)")
    elif mode in {"popup-none", "popup-gacha", "popup-gacha-late"}:
        home = home.replace("document.querySelector('dialog').showModal()", "")
    if mode == "popup-legacy":
        home = home.replace('data-e2e="popClose"', 'data-e2e="closeCpPop"')
    browser_page.on('console', lambda message: counts.__setitem__('close', counts['close'] + 1)
                    if message.text == 'closed-campaign' else None)
    if mode != "absent":
        home += '<div class="home-gacha"><a class="home-gacha-btn" href="/gacha">毎日引ける！すぐ無料ガチャ</a></div>'
    if mode == "hidden":
        home += '<style>.home-gacha{display:none}</style>'
    elif mode == "popup-late":
        home += '<style>.home-gacha-btn{pointer-events:none}</style>'
    home += '<script>fetch("/api/userPoint")</script>'
    gacha = '''<div class="gacha-btn-wrap"><a class="gacha-btn mode-user" data-e2e="gachaExecBtn">すぐ無料ガチャをまわす</a></div>
      <a href="https://x.com/" data-e2e="gachaShareBtn">Share</a>
      <script>fetch('/api/gacha');document.querySelector('[data-e2e="gachaExecBtn"]').onclick=async()=>{
      await fetch('/api/gacha',{method:'POST'});RENDER
      }</script>'''
    gacha = gacha.replace('RENDER', '' if mode == 'uncertain' else
        f'''document.body.insertAdjacentHTML('beforeend','<div data-e2e="gachaResult"><span data-e2e="gachaResTicket">{0 if mode == 'zero' else 1}</span></div>');''')
    if mode in {"popup-gacha", "popup-gacha-late", "popup-both"}:
        gacha += '''<dialog class="dialog mode-campaign" data-e2e="pop"><button type="submit"
          class="dialog-btn mode-campaign" data-e2e="closeCpPop"
          onclick="console.log('closed-campaign');this.closest('dialog').close()">×</button></dialog>'''
        show = "document.querySelector('dialog').showModal()"
        if mode == "popup-gacha-late":
            gacha += '<style>[data-e2e="gachaExecBtn"]{pointer-events:none}</style>'
            show = "setTimeout(()=>{" + show + ";document.querySelector('[data-e2e=\"gachaExecBtn\"]').style.pointerEvents='auto'},150)"
        gacha += '<script>' + show + '</script>'
    async def route(r):
        path = urlsplit(r.request.url).path
        if path == '/':
            await r.fulfill(content_type='text/html; charset=utf-8', body=home)
        elif path == '/gacha':
            await r.fulfill(content_type='text/html; charset=utf-8', body=gacha)
        elif path == '/api/userPoint':
            await r.fulfill(json={'bonusValue': 3, 'paidCoin': 0})
        elif path == '/api/gacha':
            if r.request.method == 'POST':
                counts['spin'] += 1
            await r.fulfill(json={'gacha': {'canRollGacha': mode != 'used' and not counts['spin'],
                'gachaTimes': 1 if mode == 'used' or counts['spin'] else 0,
                'gachaBonusResult': 0 if mode == 'zero' else 1}})
        else:
            counts['share'] += 1
            await r.abort()
    await browser_page.route('**/*', route)
    observer = premium.PremiumObserver(browser_page, EPISODE_ID, WORK_ID)
    try:
        await premium.prepare_daily_gacha(browser_page, observer, timeout_ms=1500)
        assert counts['spin'] == (0 if mode in {'absent', 'hidden', 'used'} else 1)
        assert settles == ([5.0] if counts['spin'] else [])
        assert counts['share'] == 0
        assert counts['close'] == (0 if mode == 'popup-none' else 2 if mode == 'popup-both' else 1)
        log = capsys.readouterr().out
        assert ('"event": "campaign_detected"' in log) == (mode != 'popup-none')
        assert ('"event": "campaign_dismissed"' in log) == (mode != 'popup-none')
    finally:
        await observer.close()


@pytest.mark.parametrize("case", ["missing", "duplicate", "wrong-type", "unknown-dialog"])
@pytest.mark.parametrize("phase", ["home", "gacha"])
async def test_home_popup_unknown_controls_leave_structural_diagnostics(browser_page, capsys, case, phase):
    button = '<button type="submit" class="dialog-btn mode-campaign" data-e2e="popClose" onclick="window.closeClicks++">Close</button>'
    if case == "missing":
        button = ""
    elif case == "duplicate":
        button *= 2
    elif case == "wrong-type":
        button = button.replace('type="submit"', 'type="reset"')
    dialog_class = "dialog mode-other" if case == "unknown-dialog" else "dialog mode-campaign"
    home = f'''<header id="xHeader"><button data-e2e="signoutBtn">Logout</button></header>
      <div class="home-gacha"><a class="home-gacha-btn" href="/gacha">Gacha</a></div>
      <button data-e2e="popClose" onclick="window.closeClicks++">Unrelated</button>
      <dialog class="{dialog_class}" data-e2e="pop">{button}
        <input value="private-account-value"><a href="https://example.invalid/?token=private-url-token">Private text</a>
      </dialog><script>window.closeClicks=0;document.querySelector('dialog').showModal();fetch('/api/userPoint')</script>'''
    paths = []
    gacha = home.replace(
        '<div class="home-gacha"><a class="home-gacha-btn" href="/gacha">Gacha</a></div>',
        '<div class="gacha-btn-wrap"><a class="gacha-btn mode-user" data-e2e="gachaExecBtn">すぐ無料ガチャをまわす</a></div>')
    gacha += "<script>fetch('/api/gacha')</script>"
    if phase == "gacha":
        home = '''<header id="xHeader"><button data-e2e="signoutBtn">Logout</button></header>
          <div class="home-gacha"><a class="home-gacha-btn" href="/gacha">Gacha</a></div>
          <script>fetch('/api/userPoint')</script>'''

    async def route(r):
        path = urlsplit(r.request.url).path
        paths.append(path)
        if path == '/':
            await r.fulfill(content_type='text/html; charset=utf-8', body=home)
        elif path == '/api/userPoint':
            await r.fulfill(json={'bonusValue': 3, 'paidCoin': 0})
        elif path == '/gacha':
            await r.fulfill(content_type='text/html; charset=utf-8', body=gacha)
        elif path == '/api/gacha':
            await r.fulfill(json={'gacha': {'canRollGacha': True, 'gachaTimes': 0}})
        else:
            await r.abort()

    await browser_page.route('**/*', route)
    observer = premium.PremiumObserver(browser_page, EPISODE_ID, WORK_ID)
    try:
        with pytest.raises((UnknownPageStateError, PlaywrightError)) as error:
            await premium.prepare_daily_gacha(browser_page, observer, timeout_ms=500)
        assert await browser_page.evaluate('closeClicks') == 0
        assert ('/gacha' in paths and '/api/gacha' in paths) == (phase == 'gacha')
        logs = [json.loads(line.split(': ', 1)[1]) for line in capsys.readouterr().out.splitlines()
                if line.startswith('Hanayume home popup: ')]
        failure = logs[-1]
        assert failure['event'] == ('home_gacha_navigation_failed' if phase == 'home' else 'gacha_preparation_failed'), str(error.value)
        assert failure['phase'] == phase
        structure = next(row for row in reversed(logs) if 'open_dialog_count' in row)
        assert structure['open_dialog_count'] == 1
        assert structure['dialogs'][0]['classes'] == dialog_class
        assert structure['gacha_link_count'] == (1 if phase == 'home' else 0)
        target = structure['targets']['home_link' if phase == 'home' else 'spin']
        assert target['count'] == 1 and target['cover']
        controls = structure['dialogs'][0]['controls']
        assert sum(c['e2e'] == 'popClose' for c in controls) == (0 if case == 'missing' else 2 if case == 'duplicate' else 1)
        assert not any(value in json.dumps(logs) for value in
                       ('private-account-value', 'private-url-token', 'Private text', 'https://'))
    finally:
        await observer.close()
