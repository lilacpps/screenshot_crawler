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
from screenshot_crawler.site_adapters.younganimal import premium_access as premium
from screenshot_crawler.site_adapters.younganimal.adapter import YounganimalAdapter
from tests.integration.test_younganimal_adapter_browser import (
    EPISODE_ID,
    EPISODE_URL,
    WORK_ID,
    _episode_html,
)

NOW_ID = "00000000002bc"
MISSING_RECOVERY = object()

CHARGE_NOTICE = '''<dialog class="dialog" data-e2e="pop" id="charge-notice">
  <div class="dialog-content"><h2 class="dialog-h mode-waitfree">「待つと無料」購読中作品の<br>チャージが完了しました。</h2>
    <div class="dialog-main"><a class="dialog-main-link" href="/episodes/unselected"
      onclick="console.log('read-notice')">private-work-title<span class="dialog-main-btn">読む</span></a></div>
    <button class="dialog-close" data-e2e="popClose" onclick="console.log('notice-x')">×</button>
    <div class="dialog-f"><button class="dialog-f-btn"
      onclick="console.log('closed-charge');this.closest('dialog').close()">閉じる</button></div>
  </div></dialog>'''

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest.fixture(autouse=True)
def short_waits(monkeypatch):
    monkeypatch.setattr(premium, "READY_SECONDS", 0.6)
    monkeypatch.setattr(premium, "RECOVERY_SECONDS", 0.6)
    from screenshot_crawler.site_adapters.younganimal import adapter
    monkeypatch.setattr(adapter, "INITIAL_QUIET_MS", 30)
    monkeypatch.setattr(adapter, "INITIAL_QUIET_POLL_MS", 10)
    monkeypatch.setattr(adapter, "VIEWER_READY_POLL_MS", 20)


async def install(page, *, count=3, case="ok", initial=False, recovery=60000):
    await page.set_viewport_size({"width": 1906, "height": 986})
    state = {"count": count, "access": initial, "checkouts": 0, "paths": [], "gacha": 0}
    html = _episode_html(native_source_slots=tuple(range(1, 17)))
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
    html = html.replace('<section id="comici-viewer"', ("" if initial else charge) + '<section id="comici-viewer"')
    script = f'''<script>
      window.entryClicks=0;window.confirmClicks=0;window.paidClicks=0;
      const viewer=document.querySelector('#comici-viewer');
      viewer.style.display={json.dumps('block' if initial else 'none')};
      {'fetch("/api/series/access").then(r=>r.json()).then(()=>window.seriesReady=true);' if case == 'series-older-pending-duplicate' else ''}
      fetch('/api/auth/session');fetch('/api/userPoint');fetch('/api/episodes/{EPISODE_ID}');
      {'fetch("/api/series/access").then(r=>r.json()).then(()=>window.seriesReady=true);' if case.startswith('series-') and case != 'series-older-pending-duplicate' else ''}
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
        {'await fetch("/api/series/access");' if case == 'series-agrees' else ''}
        if(response.ok && {json.dumps(case != 'viewer-stuck')}){{
          document.querySelector('.ep-main-content').remove();viewer.style.display='block';
        }}
      }});
    </script>'''
    html += script

    async def route(r):
        path = urlsplit(r.request.url).path
        state["paths"].append(path)
        if path == '/':
            await r.fulfill(content_type='text/html', body='<script>fetch("/api/auth/session");fetch("/api/userPoint")</script>')
        elif path == f"/episodes/{EPISODE_ID}":
            await r.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)
        elif path == "/api/auth/session":
            user = None if case == "auth-none" else True if case == "auth-bool" else 202 if case == "auth-switch" and state["access"] else 101
            await r.fulfill(json={"user": user})
        elif path == "/api/userPoint":
            await r.fulfill(json={"bonusValue": state["count"], "paidCoin": 0})
        elif path == f"/api/episodes/{EPISODE_ID}":
            current_recovery = {
                "work-ready": 0, "recovery-missing": MISSING_RECOVERY,
                "recovery-null": None, "recovery-bool": True, "recovery-negative": -1,
                "recovery-string": "60000", "recovery-float": 60000.0,
                "recovery-overflow": 23 * 3600 + 1,
            }.get(case, recovery)
            if case == "recovery-disappears" and state["access"]:
                current_recovery = MISSING_RECOVERY
            await r.fulfill(json={"episode": {
                "id": NOW_ID if case == "wrong-id" else EPISODE_ID,
                "series": {"id": NOW_ID if case == "wrong-work" else WORK_ID,
                           **({} if current_recovery is MISSING_RECOVERY else
                              {"waitAndFreeRecoveryTime": current_recovery})},
                "access": {"episodeId": NOW_ID if case == "wrong-access-id" else EPISODE_ID, "hasAccess": state["access"],
                           "accessType": "purchased" if state["access"] else "waitAndFree",
                           **({"timeRemainingInSeconds": 1295999} if state["access"] else {"timeRemainingInSeconds": None} if case == "null-timer" else {}),
                           "isDisableBonus": case == "coin-only"},
            }})
        elif path == "/api/series/access":
            if case in {"series-pending-conflict", "series-older-pending-duplicate"}:
                await asyncio.sleep(0.15)
            row = {"episodeId": EPISODE_ID, "hasAccess": not state["access"] if case in {"series-conflict", "series-pending-conflict"} else state["access"],
                   "accessType": "purchased" if state["access"] else "waitAndFree"}
            if state["access"]:
                row["timeRemainingInSeconds"] = 1295900
            await r.fulfill(json={"seriesAccess": {"seriesId": WORK_ID,
                "episodeAccesses": [row, row] if case in {"series-duplicate", "series-older-pending-duplicate"} else [row]}})
        elif path == "/api/checkout/rental":
            state["checkouts"] += 1
            state["access"] = True
            if case != "no-debit":
                state["count"] -= 1
            await r.fulfill(status=200, json={"message": "ok"})
        else:
            await r.fulfill(status=404)
    await page.route("https://younganimal.com/**", route)
    adapter = YounganimalAdapter()
    await adapter.configure_target_identity(f"{WORK_ID}:{EPISODE_ID}", "synthetic")
    await adapter.prepare_page(page)
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "premium_ticket")
    adapter.resolve_initial_navigation_url(EPISODE_URL)
    await page.goto(EPISODE_URL)
    if case.startswith('series-') and case not in {"series-pending-conflict", "series-older-pending-duplicate"}:
        await page.wait_for_function('window.seriesReady===true')
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
                                  "boolean-body", "wrong-episode-body", "transparent",
                                  "auth-none", "auth-bool", "wrong-work", "wrong-access-id",
                                  "null-timer", "series-duplicate", "series-conflict", "series-pending-conflict",
                                  "series-older-pending-duplicate", "recovery-missing",
                                  "recovery-null", "recovery-bool", "recovery-negative",
                                  "recovery-string", "recovery-float", "recovery-overflow"])
async def test_premium_invalid_ui_or_identity_never_dispatches_checkout(browser_page, case):
    adapter, state = await install(browser_page, case=case)
    with pytest.raises((UnknownPageStateError, AccessResourceUnavailableError,
                        AccessConsumptionUnconfirmedError, PlaywrightError)):
        await adapter.initialize_entry_only(browser_page)
    assert state["checkouts"] == 0 and state["count"] == 3
    assert not adapter.get_access_consumption().consumed
    assert await browser_page.evaluate("paidClicks") == 0


@pytest.mark.parametrize("case", ["no-debit", "viewer-stuck", "auth-switch", "recovery-disappears"])
async def test_no_reclick_and_confirmed_debit_survives_viewer_failure(browser_page, case):
    adapter, state = await install(browser_page, case=case)
    with pytest.raises(AccessConsumptionUnconfirmedError):
        await adapter.initialize_entry_only(browser_page)
    assert state["checkouts"] == 1
    assert adapter.get_access_consumption().consumed == (case == "viewer-stuck")
    assert await browser_page.evaluate("confirmClicks") == 1


async def test_newer_purchased_series_agreement_does_not_use_work_ticket_proof(browser_page):
    adapter, state = await install(browser_page, case="series-agrees")
    await adapter.initialize_entry_only(browser_page)
    assert adapter.get_access_consumption().consumed and state["checkouts"] == 1


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
@pytest.mark.parametrize("recovery", [60000, MISSING_RECOVERY], ids=["recovering", "omitted-ready"])
async def test_preexisting_grant_does_not_spend_or_invent_consumption(browser_page, entry_only, recovery):
    adapter, state = await install(browser_page, initial=True, recovery=recovery)
    if entry_only:
        with pytest.raises(premium.AlreadyAccessible) as error:
            await adapter.initialize_entry_only(browser_page)
        assert error.value.stop_work is False
    else:
        await adapter.initialize(browser_page)
    assert state["checkouts"] == 0 and not adapter.get_access_consumption().consumed


@pytest.mark.parametrize("count", [0, 2])
@pytest.mark.parametrize("adapter_hook", [False, True])
@pytest.mark.parametrize("recovery", [60000, 0, MISSING_RECOVERY], ids=["recovering", "zero-ready", "omitted-ready"])
@pytest.mark.parametrize("initial", [False, True], ids=["ungranted", "rental"])
async def test_stock_resolver_never_walks_large_quota_pool(browser_page, monkeypatch, count, adapter_hook, recovery, initial):
    adapter, state = await install(browser_page, count=count, recovery=recovery, initial=initial)
    await adapter._premium_entry.observer.wait("episode")
    await adapter._close_ticket_route_guard()
    await adapter._premium_entry.observer.close()
    state["paths"].clear()
    async def daily(page, observer, **kwargs):
        if adapter_hook:
            assert resolver._ticket_route_guard is None
        await page.goto(premium.HOME)
        await observer.wait("stock")
    monkeypatch.setattr(premium, "prepare_daily_gacha", daily)
    pool = tuple(SimpleNamespace(site="younganimal", work_id=1, source_id=i,
                                external_id=f"{WORK_ID}:{EPISODE_ID if i == 0 else f'{i:013x}'}",
                                locator=premium.HOME+"episodes/"+(EPISODE_ID if i == 0 else f'{i:013x}'),
                                quota_resource="premium_ticket", access_strategy="quota", consumes_quota=True)
                 for i in range(9000))
    if adapter_hook:
        resolver = YounganimalAdapter()
        result = await resolver.resolve_access_resource_candidates(browser_page, pool, "premium_ticket", timeout_ms=1000)
        assert (resolver._ticket_route_guard is not None) == (count > 0)
    else:
        result = await premium.resolve_ticket_candidates(browser_page, pool, "premium_ticket", timeout_ms=1000)
    selected = count if recovery == 60000 else 0
    assert result.selected_source_ids == tuple(range(selected))
    if count and not selected:
        assert result.skipped_source_reasons == tuple((i, "work_ticket_priority") for i in range(9000))
    assert result.stop_resource_pass == (count == 0)
    episode_paths = [p for p in state["paths"] if p.startswith('/episodes/')]
    assert episode_paths == ([f'/episodes/{EPISODE_ID}'] if count else [])
    assert state["checkouts"] == 0


@pytest.mark.parametrize("mode", ["absent", "used", "win", "zero", "uncertain", "popup-late", "popup-none",
                                  "popup-legacy", "popup-gacha", "popup-gacha-late", "popup-both",
                                  "campaign-submit", "charge", "charge-late", "charge-absent",
                                  "charge-then-campaign"])
async def test_daily_gacha_once_or_absent_never_shares_or_retries(browser_page, monkeypatch, capsys, mode):
    settles = []
    original_sleep = asyncio.sleep
    async def sleep(delay):
        if delay == premium.GACHA_SETTLE_SECONDS:
            settles.append(delay)
            await original_sleep(0.05)
        else:
            await original_sleep(delay)
    monkeypatch.setattr(premium.asyncio, "sleep", sleep)
    counts = {"spin": 0, "share": 0, "close": 0, "charge": 0, "read": 0, "x": 0}
    home = '''<header id="xHeader"><button data-e2e="signoutBtn">Logout</button></header>
      <dialog class="dialog mode-campaign" data-e2e="pop"><button type="button" class="dialog-btn mode-campaign" data-e2e="popClose" onclick="console.log('closed-campaign');window.closedCampaign++;this.closest('dialog').close()">Close</button></dialog>
      <script>window.closedCampaign=0;document.querySelector('dialog').showModal()</script>'''
    if mode == "popup-late":
        home = home.replace("document.querySelector('dialog').showModal()", "setTimeout(()=>{document.querySelector('dialog').showModal();document.querySelector('.home-gacha-btn').style.pointerEvents='auto'},150)")
    elif mode in {"popup-none", "popup-gacha", "popup-gacha-late"}:
        home = home.replace("document.querySelector('dialog').showModal()", "")
    if mode == "popup-legacy":
        home = home.replace('data-e2e="popClose"', 'data-e2e="closeCpPop"')
    if mode == "campaign-submit":
        home = home.replace('type="button" class="dialog-btn mode-campaign"',
                            'type="submit" class="dialog-btn mode-campaign"')
    if mode.startswith("charge"):
        if mode == "charge-then-campaign":
            home = home.replace("document.querySelector('dialog').showModal()", "")
            notice = CHARGE_NOTICE.replace("this.closest('dialog').close()",
                "this.closest('dialog').close();document.querySelector('.mode-campaign').showModal()")
            home += notice
        else:
            home = '<header id="xHeader"><button data-e2e="signoutBtn">Logout</button></header>' + CHARGE_NOTICE
        show = "document.querySelector('#charge-notice').showModal()"
        if mode == "charge-late":
            show = "setTimeout(()=>{" + show + ";document.querySelector('.home-gacha-btn').style.pointerEvents='auto'},150)"
        home += '<script>' + show + '</script>'

    def console(message):
        key = {"closed-campaign": "close", "closed-charge": "charge", "read-notice": "read", "notice-x": "x"}.get(message.text)
        if key:
            counts[key] += 1
    browser_page.on('console', console)
    if mode not in {"absent", "charge-absent"}:
        home += '<div class="home-gacha"><a class="home-gacha-btn" href="/gacha">毎日引ける！すぐ無料ガチャ</a></div>'
    if mode in {"popup-late", "charge-late"}:
        home += '<style>.home-gacha-btn{pointer-events:none}</style>'
    home += '<script>fetch("/api/auth/session");fetch("/api/userPoint")</script>'
    gacha = '''<div class="gacha-btn-wrap"><a class="gacha-btn mode-user" data-e2e="gachaExecBtn">すぐ無料ガチャをまわす</a></div>
      <a href="https://x.com/" data-e2e="gachaShareBtn">Share</a>
      <script>fetch('/api/gacha');document.querySelector('[data-e2e="gachaExecBtn"]').onclick=async()=>{
      await fetch('/api/gacha',{method:'POST'});RENDER
      }</script>'''
    gacha = gacha.replace('RENDER', '' if mode == 'uncertain' else
        f'''document.body.insertAdjacentHTML('beforeend','<div data-e2e="gachaResult"><span data-e2e="gachaResTicket">{'はずれ' if mode == 'zero' else 1}</span></div>');''')
    if mode in {"popup-gacha", "popup-gacha-late", "popup-both"}:
        gacha += '''<dialog class="dialog mode-campaign" data-e2e="pop"><button type="button"
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
        elif path == '/api/auth/session':
            await r.fulfill(json={'user': 101})
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
        assert counts['spin'] == (0 if mode in {'absent', 'used', 'charge-absent'} else 1)
        assert settles == ([5.0] if counts['spin'] else [])
        assert counts['share'] == 0
        assert counts['close'] == (0 if mode in {'popup-none', 'charge', 'charge-late', 'charge-absent'}
                                   else 2 if mode == 'popup-both' else 1)
        assert counts['charge'] == int(mode.startswith('charge'))
        assert counts['read'] == counts['x'] == 0
        log = capsys.readouterr().out
        assert ('"event": "charge_notice_dismissed"' in log) == mode.startswith('charge')
        assert 'private-work-title' not in log
        if mode == 'absent':
            assert await browser_page.evaluate('closedCampaign') == 1
    finally:
        await observer.close()


@pytest.mark.parametrize("case", ["heading", "missing", "duplicate", "label", "form", "unknown-dialog"])
async def test_charge_notice_unknown_controls_log_structure_without_clicking(
    browser_page, capsys, case,
):
    notice = CHARGE_NOTICE
    if case == "heading":
        notice = notice.replace("チャージが完了しました。", "別のお知らせです。")
    elif case == "missing":
        notice = notice.replace('class="dialog-f-btn"', 'class="unknown-close"')
    elif case == "duplicate":
        notice = notice.replace('</div>\n  </div></dialog>',
            '<button class="dialog-f-btn" onclick="console.log(\'unexpected\')">閉じる</button></div>\n  </div></dialog>')
    elif case == "label":
        notice = notice.replace('>閉じる</button>', '>購入する</button>')
    elif case == "form":
        notice = notice.replace('<div class="dialog-content">', '<form><div class="dialog-content">')
        notice = notice.replace('</div></dialog>', '</div></form></dialog>')
    elif case == "unknown-dialog":
        notice = notice.replace('class="dialog-h mode-waitfree"', 'class="dialog-h mode-unknown"')
    notice = notice.replace('private-work-title', 'private-work-title<input value="private-account-value">')
    notice = notice.replace('/episodes/unselected', '/episodes/unselected?token=private-url-token')
    home = '''<header id="xHeader"><button data-e2e="signoutBtn">Logout</button></header>
      <div class="home-gacha"><a class="home-gacha-btn" href="/gacha">Gacha</a></div>''' + notice + '''
      <button class="dialog-f-btn" onclick="console.log('unexpected')">閉じる</button>
      <script>document.querySelector('dialog').showModal();fetch('/api/auth/session');fetch('/api/userPoint')</script>'''
    clicks = []
    browser_page.on('console', lambda message: clicks.append(message.text))
    async def route(r):
        path = urlsplit(r.request.url).path
        if path == '/':
            await r.fulfill(content_type='text/html; charset=utf-8', body=home)
        elif path == '/api/auth/session':
            await r.fulfill(json={'user': 101})
        elif path == '/api/userPoint':
            await r.fulfill(json={'bonusValue': 3, 'paidCoin': 0})
        else:
            pytest.fail(f'Unexpected synthetic route: {path}')
    await browser_page.route('**/*', route)
    observer = premium.PremiumObserver(browser_page, EPISODE_ID, WORK_ID)
    try:
        with pytest.raises((UnknownPageStateError, PlaywrightError)):
            await premium.prepare_daily_gacha(browser_page, observer, timeout_ms=500)
        assert not clicks
        logs = [json.loads(line.split(': ', 1)[1]) for line in capsys.readouterr().out.splitlines()
                if line.startswith('Younganimal home popup: ')]
        failure = logs[-1]
        assert failure['event'] == 'gacha_preparation_failed' and failure['phase'] == 'home'
        assert failure['open_dialog_count'] == 1
        assert failure['dialogs'][0]['charge_heading_count'] == (0 if case == 'unknown-dialog' else 1)
        assert failure['targets']['home_link']['count'] == 1
        assert failure['targets']['home_link']['cover']
        assert not any(secret in json.dumps(logs) for secret in
                       ('private-work-title', 'private-account-value', 'private-url-token', 'https://'))
    finally:
        await observer.close()
