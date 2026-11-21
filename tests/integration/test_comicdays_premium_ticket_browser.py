from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from screenshot_crawler.core.errors import (
    AccessConsumptionUnconfirmedError,
    AccessResourceUnavailableError,
    UnknownPageStateError,
)
from screenshot_crawler.site_adapters.comicdays import live_access
from screenshot_crawler.site_adapters.comicdays.adapter import ComicDaysAdapter
from screenshot_crawler.site_adapters.comicdays.live_access import ComicDaysTicketState

pytestmark = pytest.mark.asyncio(loop_scope="module")

HTML = """
<section class="private-viewer js-viewer" data-json-url="https://comic-days.com/episode/1.json">
<div class="read-button-container">
  <button style="display:none" data-test-id="use-series-ticket-button" data-ticket-type="series"
    data-ticket-rental-id="1" data-behaviour="button">作品チケットで読む（無料）</button>
  <button data-test-id="use-premium-ticket-button" data-ticket-type="premium"
    data-ticket-rental-id="1" data-behaviour="button" title="いつでもチケットを使って読む">いつでもチケットで読む（無料）</button>
  <button data-test-id="purchase-button" data-buy-price="90">購入して読む90pt</button>
</div></section>
<div data-series-id="1"></div>
<div class="js-readable-products-pagination" data-type="episode" data-aggregate-id="1" data-rental-term="259200"></div>
<script>
window.premiumClicks=0; window.workClicks=0; window.paidClicks=0;
document.querySelector('[data-test-id="use-series-ticket-button"]').addEventListener('click',()=>window.workClicks++);
document.querySelector('[data-test-id="purchase-button"]').addEventListener('click',()=>window.paidClicks++);
document.querySelector('[data-test-id="use-premium-ticket-button"]').addEventListener('click',()=>{
 window.premiumClicks++;
 const v=document.querySelector('section');v.className='viewer js-viewer';
 v.innerHTML='<div style="width:100px;height:100px">Synthetic unlocked viewer</div>';
});
</script>
"""


async def setup(page, monkeypatch, *, before=3, after=None, charged=False, html=HTML):
    await page.route("https://comic-days.com/episode/1", lambda r: r.fulfill(
        status=200, content_type="text/html; charset=utf-8", body=html,
    ))
    await page.goto("https://comic-days.com/episode/1")
    recharge = datetime.now(UTC) + timedelta(hours=18)

    async def ticket(*args, **kwargs):
        clicked = await page.evaluate("window.premiumClicks")
        count = (before - 1 if after is None else after) if clicked else before
        return ComicDaysTicketState("1", charged, recharge, count)

    monkeypatch.setattr(live_access, "observe_comicdays_ticket", ticket)
    adapter = ComicDaysAdapter()
    adapter.page_change_timeout_ms = 400
    adapter.ticket_recovery_window_ms = 20
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "premium_ticket")
    return adapter


@pytest.mark.parametrize("before", [1, 3])
async def test_exact_premium_debit_and_viewer_confirm_entry_without_work_use(browser_page, monkeypatch, before):
    adapter = await setup(browser_page, monkeypatch, before=before)
    await adapter.initialize_entry_only(browser_page)
    result = adapter.get_access_consumption()
    assert result.consumed and result.resource == "premium_ticket"
    assert result.stop_resource_pass == (before == 1)
    assert await browser_page.evaluate("[premiumClicks,workClicks,paidClicks]") == [1, 0, 0]


@pytest.mark.parametrize("case", ["work_ready", "work_visible", "zero", "unknown", "duplicate", "wrong_id", "paid_attribute", "wrong_term"])
async def test_premium_ambiguity_or_work_priority_never_clicks(browser_page, monkeypatch, case):
    html = HTML
    if case == "work_ready":
        html = html.replace('style="display:none"', '').replace(
            'data-test-id="use-premium-ticket-button" data-ticket-type',
            'style="display:none" data-test-id="use-premium-ticket-button" data-ticket-type',
        )
    elif case == "work_visible":
        html = html.replace('style="display:none"', '')
    elif case == "duplicate":
        html = html.replace('</div></section>', '<button data-test-id="use-premium-ticket-button" data-ticket-type="premium">duplicate</button></div></section>')
    elif case == "wrong_id":
        html = html.replace('data-ticket-rental-id="1"', 'data-ticket-rental-id="2"')
    elif case == "paid_attribute":
        html = html.replace('data-ticket-type="premium"', 'data-ticket-type="premium" data-buy-price="90"')
    elif case == "wrong_term":
        html = html.replace('data-rental-term="259200"', 'data-rental-term="172800"')
    adapter = await setup(
        browser_page, monkeypatch, before=0 if case == "zero" else None if case == "unknown" else 3,
        charged=case == "work_ready", html=html,
    )
    with pytest.raises((AccessResourceUnavailableError, UnknownPageStateError)):
        await adapter.initialize_entry_only(browser_page)
    assert not adapter.get_access_consumption().consumed
    assert await browser_page.evaluate("[premiumClicks,workClicks,paidClicks]") == [0, 0, 0]


@pytest.mark.parametrize("after", [3, 1])
async def test_unlock_without_exact_one_debit_is_unconfirmed_and_never_reclicked(browser_page, monkeypatch, after):
    adapter = await setup(browser_page, monkeypatch, before=3, after=after)
    with pytest.raises(AccessConsumptionUnconfirmedError):
        await adapter.initialize_entry_only(browser_page)
    assert not adapter.get_access_consumption().consumed
    assert await browser_page.evaluate("[premiumClicks,workClicks,paidClicks]") == [1, 0, 0]


@pytest.mark.parametrize("entry_only", [True, False])
async def test_preexisting_readable_premium_target_never_spends_again(browser_page, monkeypatch, entry_only):
    adapter = await setup(browser_page, monkeypatch)
    await browser_page.evaluate("""() => {
      const v=document.querySelector('section'); v.className='viewer js-viewer';
      v.innerHTML='<div style="width:100px;height:100px">Existing grant</div>';
    }""")
    if entry_only:
        with pytest.raises(AccessResourceUnavailableError, match="already_accessible") as caught:
            await adapter.initialize_entry_only(browser_page)
        assert caught.value.stop_work is False
    else:
        monkeypatch.setattr(adapter, "_read_metadata", AsyncMock(return_value=("Synthetic", "Author")))
        monkeypatch.setattr(adapter, "_normalize_viewer", AsyncMock())
        await adapter.initialize(browser_page)
    assert adapter._preexisting_accessible
    assert not adapter.get_access_consumption().consumed
    assert await browser_page.evaluate("[premiumClicks,workClicks,paidClicks]") == [0, 0, 0]
