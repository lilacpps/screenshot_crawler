from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from screenshot_crawler.core.errors import (
    AccessConsumptionUnconfirmedError,
    AccessResourceUnavailableError,
    PageChangeTimeoutError,
    UnknownPageStateError,
    UnsupportedAccessStrategyError,
)
from screenshot_crawler.site_adapters.base import AccessConsumption
from screenshot_crawler.site_adapters.comicdays import adapter as adapter_module
from screenshot_crawler.site_adapters.comicdays.adapter import ComicDaysAdapter
from screenshot_crawler.site_adapters.comicdays.live_access import (
    ComicDaysLiveAccessState,
    ComicDaysTicketState,
)

pytestmark = pytest.mark.asyncio(loop_scope="module")


ENTRY_HTML = """
<section class="private-viewer js-viewer" data-json-url="https://comic-days.com/episode/1.json">
  <div id="content"><div class="read-button-container">
    <button data-test-id="use-series-ticket-button" data-ticket-type="series" data-behaviour="button"
            title="作品チケットを使って読む"
            data-ticket-rental-id="1">\u4f5c\u54c1\u30c1\u30b1\u30c3\u30c8\u3067\u8aad\u3080\uff08\u7121\u6599\uff09</button>
    <button data-test-id="purchase-button" data-buy-price="100">購入して読む</button>
  </div><div class="image-container js-viewer-content"><canvas class="page-image js-page-image"></canvas></div></div>
</section>
<div data-aggregate-id="1" data-type="episode" class="access-panel" style="width:1px;height:1px"></div>
<div data-series-id="1"></div>
"""


def _state(
    *, mode: str, charged: bool, changed: bool = False,
    term: object = 72, charged_at: datetime | None = None,
) -> ComicDaysLiveAccessState:
    return ComicDaysLiveAccessState(
        series_id="1",
        episode_id="1",
        row={
            "purchase_info": {
                "can_read": mode == "quota" and not charged,
                "has_rented_via_ticket": mode == "quota" and not charged,
            },
            "status": {"rental_term": term},
        },
        access_mode=mode,
        grant_until=(datetime.now(UTC) + timedelta(hours=72) if mode == "quota" and not charged else None),
        grant_observed=mode == "quota" and not charged,
        ticket=ComicDaysTicketState(
            series_id="1",
            is_charged=charged,
            charged_at=(charged_at if charged_at is not None else (datetime.now(UTC) + timedelta(hours=1) if changed else datetime(1999, 1, 1, tzinfo=UTC))),
        ),
    )


class _ClickRaisesAfterDispatch:
    def __init__(self, locator, error: BaseException) -> None:
        self._locator = locator
        self._error = error

    async def click(self, **kwargs: object) -> None:
        await self._locator.click(**kwargs)
        raise self._error


async def _ticket_page(browser_page, *, html: str = ENTRY_HTML):
    await browser_page.route(
        "https://comic-days.com/episode/1",
        lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html),
    )
    await browser_page.goto("https://comic-days.com/episode/1")
    await browser_page.evaluate("""() => {
      window.__comicDaysProductionCapture = { active: () => ({rows: [{renderReady: true}], sliderNow: 1, sliderLast: 1}) };
      document.querySelector('[data-test-id="use-series-ticket-button"]').addEventListener('click', () => {
        document.querySelector('section.private-viewer')?.classList.remove('private-viewer');
        document.querySelector('section.js-viewer')?.classList.add('viewer');
      });
    }""")
    return browser_page


async def test_comicdays_ticket_entry_confirms_consumption_and_never_clicks_paid(
    browser_page, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = await _ticket_page(browser_page)
    states = iter([_state(mode="quota", charged=True), _state(mode="quota", charged=False, changed=True)])
    monkeypatch.setattr(adapter_module, "observe_comicdays_live_access", lambda *_a, **_k: _anext(states))
    await page.evaluate("""() => {
      document.querySelector('[data-test-id="purchase-button"]').addEventListener('click', () => window.paidClicked = true);
    }""")
    adapter = ComicDaysAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    await adapter.initialize_entry_only(page)
    assert adapter.get_access_consumption().consumed is True
    assert adapter.get_access_consumption().resource == "work_ticket"
    assert await page.evaluate("() => window.paidClicked === true") is False


async def test_comicdays_ticket_guard_uses_locked_private_viewer_scope(
    browser_page,
) -> None:
    page = await _ticket_page(browser_page, html=ENTRY_HTML.replace(
        'class="private-viewer js-viewer viewer"', 'class="private-viewer js-viewer"'
    ))
    adapter = ComicDaysAdapter()
    adapter._episode_id = "1"
    adapter._work_id = "1"
    control = await adapter._exact_ticket_control(page, asyncio.get_running_loop().time() + 2_000)
    assert await control.count() == 1


async def test_comicdays_ticket_entry_free_state_does_not_click(
    browser_page, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = await _ticket_page(browser_page)
    monkeypatch.setattr(adapter_module, "observe_comicdays_live_access", lambda *_a, **_k: _anext(iter([_state(mode="free", charged=True)])))
    clicked = await page.locator('[data-test-id="use-series-ticket-button"]').evaluate(
        "node => { node.addEventListener('click', () => window.ticketClicked = true); return true; }"
    )
    assert clicked is True
    adapter = ComicDaysAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    with pytest.raises(AccessResourceUnavailableError, match="not_needed"):
        await adapter.initialize_entry_only(page)
    assert await page.evaluate("() => window.ticketClicked === true") is False
    assert adapter.get_access_consumption().consumed is False


async def test_comicdays_ticket_entry_rejects_hidden_control(
    browser_page, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = await _ticket_page(browser_page, html=ENTRY_HTML.replace(
        "data-ticket-rental-id=\"1\"", "data-ticket-rental-id=\"1\" style=\"display:none\""
    ))
    monkeypatch.setattr(adapter_module, "observe_comicdays_live_access", lambda *_a, **_k: _anext(iter([_state(mode="quota", charged=True)])))
    adapter = ComicDaysAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    with pytest.raises(AccessResourceUnavailableError, match="not_actionable"):
        await adapter.initialize_entry_only(page)
    assert adapter.get_access_consumption().consumed is False


async def test_comicdays_ticket_entry_rejects_disabled_control(
    browser_page, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = await _ticket_page(browser_page, html=ENTRY_HTML.replace(
        'data-ticket-rental-id="1"', 'data-ticket-rental-id="1" disabled'
    ))
    monkeypatch.setattr(adapter_module, "observe_comicdays_live_access", lambda *_a, **_k: _anext(iter([_state(mode="quota", charged=True)])))
    adapter = ComicDaysAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    with pytest.raises(AccessResourceUnavailableError, match="not_actionable"):
        await adapter.initialize_entry_only(page)
    assert adapter.get_access_consumption().consumed is False


async def test_comicdays_ticket_entry_rejects_duplicate_control(
    browser_page, monkeypatch: pytest.MonkeyPatch
) -> None:
    duplicate = '<button data-test-id="use-series-ticket-button" data-ticket-type="series" data-behaviour="button" title="作品チケットを使って読む" data-ticket-rental-id="1">\u4f5c\u54c1\u30c1\u30b1\u30c3\u30c8\u3067\u8aad\u3080\uff08\u7121\u6599\uff09</button>'
    page = await _ticket_page(browser_page, html=ENTRY_HTML.replace(
        '    <button data-test-id="purchase-button"', duplicate + '\n    <button data-test-id="purchase-button"'
    ))
    monkeypatch.setattr(adapter_module, "observe_comicdays_live_access", lambda *_a, **_k: _anext(iter([_state(mode="quota", charged=True)])))
    adapter = ComicDaysAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    with pytest.raises(AccessResourceUnavailableError, match="ambiguous"):
        await adapter.initialize_entry_only(page)
    assert adapter.get_access_consumption().consumed is False


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ('data-json-url="https://comic-days.com/episode/1.json"', 'data-json-url="https://comic-days.com/episode/2.json"'),
        ('data-aggregate-id="1"', 'data-aggregate-id="2"'),
        ('data-ticket-rental-id="1"', 'data-ticket-rental-id="2"'),
        (r"\u4f5c", "x"),
        ('data-behaviour="button"', 'data-buy-price="1" data-behaviour="button"'),
    ],
)
async def test_comicdays_ticket_entry_rejects_identity_label_and_paid_conflicts(
    browser_page, monkeypatch: pytest.MonkeyPatch, old: str, new: str
) -> None:
    html = ENTRY_HTML.replace(chr(0x4F5C), "x") if old == r"\u4f5c" else ENTRY_HTML.replace(old, new)
    page = await _ticket_page(browser_page, html=html)
    monkeypatch.setattr(
        adapter_module,
        "observe_comicdays_live_access",
        lambda *_a, **_k: _anext(iter([_state(mode="quota", charged=True)])),
    )
    adapter = ComicDaysAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    with pytest.raises(AccessResourceUnavailableError):
        await adapter.initialize_entry_only(page)
    assert adapter.get_access_consumption().consumed is False


async def test_comicdays_post_grant_viewer_failure_keeps_confirmed_consumption(
    browser_page, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = await _ticket_page(browser_page)
    await page.evaluate(
        "() => { window.__comicDaysProductionCapture.active = () => ({rows: [], ready: false}); }"
    )
    states = iter([_state(mode="quota", charged=True), _state(mode="quota", charged=False, changed=True)])
    monkeypatch.setattr(adapter_module, "observe_comicdays_live_access", lambda *_a, **_k: _anext(states))
    adapter = ComicDaysAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    with pytest.raises(PageChangeTimeoutError):
        await adapter.initialize_entry_only(page)
    assert adapter.get_access_consumption().consumed is True


async def test_comicdays_delayed_viewer_readiness_succeeds_after_one_click(
    browser_page, monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = await _ticket_page(browser_page)
    await page.evaluate("""() => {
      window.ticketClicks = 0;
      document.querySelector('[data-test-id=use-series-ticket-button]').addEventListener('click', () => window.ticketClicks++);
      let polls = 0;
      window.__comicDaysProductionCapture.active = () => ({
        rows: [{renderReady: ++polls >= 3}], sliderNow: 1, sliderLast: 1
      });
    }""")
    states = iter([_state(mode="quota", charged=True), _state(mode="quota", charged=False, changed=True)])
    monkeypatch.setattr(adapter_module, "observe_comicdays_live_access", lambda *_a, **_k: _anext(states))
    adapter = ComicDaysAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    await adapter.initialize_entry_only(page)
    assert await page.evaluate("() => window.ticketClicks") == 1
    assert adapter.get_access_consumption().consumed is True


async def test_comicdays_postgrant_identity_mismatch_fails_closed_after_debit(
    browser_page, monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = await _ticket_page(browser_page, html=ENTRY_HTML.replace(
        'data-json-url="https://comic-days.com/episode/1.json"',
        'data-json-url="https://comic-days.com/episode/2.json"',
    ))
    states = iter([_state(mode="quota", charged=True), _state(mode="quota", charged=False, changed=True)])
    monkeypatch.setattr(adapter_module, "observe_comicdays_live_access", lambda *_a, **_k: _anext(states))
    adapter = ComicDaysAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    with pytest.raises(AccessResourceUnavailableError):
        await adapter.initialize_entry_only(page)
    assert adapter.get_access_consumption().consumed is False


@pytest.mark.parametrize("mutation", ["json", "episode", "work"])
async def test_comicdays_post_debit_identity_mismatch_retains_consumption(
    browser_page, monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    page = await _ticket_page(browser_page)
    await page.evaluate("() => { window.ticketClicks = 0; document.querySelector('[data-test-id=use-series-ticket-button]').addEventListener('click', () => window.ticketClicks++); }")
    states = iter([_state(mode="quota", charged=True), _state(mode="quota", charged=False, changed=True)])
    monkeypatch.setattr(adapter_module, "observe_comicdays_live_access", lambda *_a, **_k: _anext(states))
    adapter = ComicDaysAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    original_reobserve = adapter._reobserve_consumption

    async def mutate_after_native(page, previous_charged_at, deadline):
        result = await original_reobserve(page, previous_charged_at, deadline)
        if result:
            if mutation == "json":
                await page.evaluate("() => document.querySelector('section.js-viewer')?.setAttribute('data-json-url', 'https://comic-days.com/episode/2.json')")
            elif mutation == "episode":
                await page.evaluate("() => history.replaceState({}, '', '/episode/2')")
            else:
                await page.evaluate("() => document.querySelector('[data-aggregate-id][data-type=episode]')?.setAttribute('data-aggregate-id', '2')")
        return result

    monkeypatch.setattr(adapter, "_reobserve_consumption", mutate_after_native)
    with pytest.raises((AccessResourceUnavailableError, PageChangeTimeoutError, UnknownPageStateError)):
        await adapter.initialize_entry_only(page)
    consumed_at = adapter.get_access_consumption().consumed_at
    assert adapter.get_access_consumption().consumed is True
    assert consumed_at is not None
    assert await page.evaluate("() => window.ticketClicks") == 1


async def test_comicdays_detaching_postgrant_read_is_bounded_and_retains_consumption(
    browser_page, monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = await _ticket_page(browser_page)
    await page.evaluate("""() => document.querySelector('[data-test-id=use-series-ticket-button]').addEventListener('click', () => document.querySelector('section.js-viewer')?.remove())""")
    states = iter([_state(mode="quota", charged=True), _state(mode="quota", charged=False, changed=True)])
    monkeypatch.setattr(adapter_module, "observe_comicdays_live_access", lambda *_a, **_k: _anext(states))
    adapter = ComicDaysAdapter()
    adapter.page_change_timeout_ms = 150
    adapter.ticket_recovery_window_ms = 50
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    started = asyncio.get_running_loop().time()
    with pytest.raises(PageChangeTimeoutError):
        await adapter.initialize_entry_only(page)
    assert asyncio.get_running_loop().time() - started < 2
    assert adapter.get_access_consumption().consumed is True


async def test_comicdays_hanging_postgrant_locator_is_cancelled_by_overall_deadline(
    browser_page,
) -> None:
    class _HangingLocator:
        async def count(self) -> int:
            await asyncio.sleep(60)
            return 0

    class _HangingPage:
        url = "https://comic-days.com/episode/1"

        def locator(self, _selector: str) -> _HangingLocator:
            return _HangingLocator()

    adapter = ComicDaysAdapter()
    adapter._episode_id = "1"
    adapter._work_id = "1"
    consumed_at = datetime.now(UTC)
    adapter._access_consumption = AccessConsumption(
        consumed=True, resource="work_ticket", consumed_at=consumed_at
    )
    started = asyncio.get_running_loop().time()
    assert await adapter._post_grant_viewer_ready(
        _HangingPage(), asyncio.get_running_loop().time() + 50 / 1000
    ) is False
    assert asyncio.get_running_loop().time() - started < 1
    assert adapter.get_access_consumption().consumed is True
    assert adapter.get_access_consumption().consumed_at == consumed_at


async def test_comicdays_cancel_during_viewer_readiness_keeps_first_consumption(
    browser_page, monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = await _ticket_page(browser_page)
    await page.evaluate("() => { window.ticketClicks = 0; document.querySelector('[data-test-id=use-series-ticket-button]').addEventListener('click', () => window.ticketClicks++); }")
    states = iter([_state(mode="quota", charged=True), _state(mode="quota", charged=False, changed=True)])
    monkeypatch.setattr(adapter_module, "observe_comicdays_live_access", lambda *_a, **_k: _anext(states))

    async def cancel_readiness(self, page, deadline):
        raise asyncio.CancelledError()

    monkeypatch.setattr(ComicDaysAdapter, "_post_grant_viewer_ready", cancel_readiness)
    adapter = ComicDaysAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    with pytest.raises(asyncio.CancelledError):
        await adapter.initialize_entry_only(page)
    assert await page.evaluate("() => window.ticketClicks") == 1
    assert adapter.get_access_consumption().consumed is True


async def test_comicdays_consumed_timestamp_is_latched_across_readonly_polls(
    browser_page, monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = await _ticket_page(browser_page)
    adapter = ComicDaysAdapter()
    adapter._work_id = "1"
    adapter._episode_id = "1"
    first = _state(mode="quota", charged=False, changed=True)
    second = _state(mode="quota", charged=False, changed=True)
    states = iter([first, second])
    monkeypatch.setattr(adapter, "_observe_live_access", lambda *_a, **_k: _anext(states))
    previous = datetime(1999, 1, 1, tzinfo=UTC)
    assert await adapter._reobserve_consumption(page, previous, asyncio.get_running_loop().time() + 2) is True
    consumed_at = adapter.get_access_consumption().consumed_at
    assert consumed_at is not None
    assert await adapter._reobserve_consumption(page, previous, asyncio.get_running_loop().time() + 2) is True
    assert adapter.get_access_consumption().consumed_at == consumed_at


async def test_comicdays_entry_never_retries_after_click_attempt(
    browser_page, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = await _ticket_page(browser_page)
    await page.evaluate(
        "() => { window.ticketClicks = 0; document.querySelector('[data-test-id=use-series-ticket-button]').addEventListener('click', () => window.ticketClicks++); }"
    )
    states = iter([_state(mode="quota", charged=True), _state(mode="quota", charged=False, changed=True)])
    monkeypatch.setattr(adapter_module, "observe_comicdays_live_access", lambda *_a, **_k: _anext(states))
    adapter = ComicDaysAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    await adapter.initialize_entry_only(page)
    with pytest.raises(UnsupportedAccessStrategyError, match="already attempted"):
        await adapter.initialize_entry_only(page)
    assert await page.evaluate("() => window.ticketClicks") == 1


@pytest.mark.parametrize("error_kind", ["timeout", "cancel"])
async def test_comicdays_click_failure_reconciles_without_retry(
    browser_page, monkeypatch: pytest.MonkeyPatch, error_kind: str
) -> None:
    page = await _ticket_page(browser_page)
    await page.evaluate("() => { window.ticketClicks = 0; document.querySelector('[data-test-id=use-series-ticket-button]').addEventListener('click', () => window.ticketClicks++); }")
    states = iter([_state(mode="quota", charged=True), _state(mode="quota", charged=False, changed=True)])
    monkeypatch.setattr(adapter_module, "observe_comicdays_live_access", lambda *_a, **_k: _anext(states))
    error: BaseException = PlaywrightTimeoutError("post-dispatch timeout") if error_kind == "timeout" else asyncio.CancelledError()
    real_locator = page.locator('[data-test-id="use-series-ticket-button"]')

    async def exact(*_args: object, **_kwargs: object):
        return _ClickRaisesAfterDispatch(real_locator, error)

    monkeypatch.setattr(ComicDaysAdapter, "_exact_ticket_control", exact)
    adapter = ComicDaysAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    with pytest.raises(type(error)):
        await adapter.initialize_entry_only(page)
    assert await page.evaluate("() => window.ticketClicks") == 1
    assert adapter.get_access_consumption().consumed is True


async def test_comicdays_confirmation_cancellation_reconciles_after_click_returns(
    browser_page, monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = await _ticket_page(browser_page)
    await page.evaluate("() => { window.ticketClicks = 0; document.querySelector('[data-test-id=use-series-ticket-button]').addEventListener('click', () => window.ticketClicks++); }")
    states = iter([_state(mode="quota", charged=True), _state(mode="quota", charged=False, changed=True)])
    monkeypatch.setattr(adapter_module, "observe_comicdays_live_access", lambda *_a, **_k: _anext(states))
    original_poll = ComicDaysAdapter._poll_consumption
    poll_calls = 0

    async def cancel_during_confirmation(self, page, previous_charged_at, deadline):
        nonlocal poll_calls
        poll_calls += 1
        if poll_calls == 1:
            raise asyncio.CancelledError()
        return await original_poll(self, page, previous_charged_at, deadline)

    monkeypatch.setattr(ComicDaysAdapter, "_poll_consumption", cancel_during_confirmation)
    adapter = ComicDaysAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    with pytest.raises(asyncio.CancelledError):
        await adapter.initialize_entry_only(page)
    assert poll_calls == 2
    assert await page.evaluate("() => window.ticketClicks") == 1
    assert adapter.get_access_consumption().consumed is True


async def test_comicdays_delayed_native_poststate_is_polled_once_per_attempt(
    browser_page, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = await _ticket_page(browser_page)
    await page.evaluate("() => { window.ticketClicks = 0; document.querySelector('[data-test-id=use-series-ticket-button]').addEventListener('click', () => window.ticketClicks++); }")
    states = iter([
        _state(mode="quota", charged=True),
        _state(mode="quota", charged=True),
        _state(mode="quota", charged=False, changed=True),
    ])
    monkeypatch.setattr(adapter_module, "observe_comicdays_live_access", lambda *_a, **_k: _anext(states))
    adapter = ComicDaysAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    await adapter.initialize_entry_only(page)
    assert await page.evaluate("() => window.ticketClicks") == 1
    assert adapter.get_access_consumption().consumed is True


@pytest.mark.parametrize("term", [None, True, "72", 71, 73])
async def test_comicdays_unsupported_native_term_never_clicks(
    browser_page, monkeypatch: pytest.MonkeyPatch, term: object
) -> None:
    page = await _ticket_page(browser_page)
    await page.evaluate("() => { window.ticketClicks = 0; document.querySelector('[data-test-id=use-series-ticket-button]').addEventListener('click', () => window.ticketClicks++); }")
    monkeypatch.setattr(adapter_module, "observe_comicdays_live_access", lambda *_a, **_k: _anext(iter([_state(mode="quota", charged=True, term=term)])))
    adapter = ComicDaysAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    with pytest.raises(AccessResourceUnavailableError, match="unsupported_rental_term"):
        await adapter.initialize_entry_only(page)
    assert await page.evaluate("() => window.ticketClicks") == 0


async def test_comicdays_preexisting_active_grant_does_not_consume(
    browser_page, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = await _ticket_page(browser_page)
    await page.evaluate("() => { window.ticketClicks = 0; document.querySelector('[data-test-id=use-series-ticket-button]').addEventListener('click', () => window.ticketClicks++); }")
    monkeypatch.setattr(adapter_module, "observe_comicdays_live_access", lambda *_a, **_k: _anext(iter([_state(mode="quota", charged=False, changed=True)])))
    adapter = ComicDaysAdapter()
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    with pytest.raises(AccessResourceUnavailableError, match="not_needed"):
        await adapter.initialize_entry_only(page)
    assert await page.evaluate("() => window.ticketClicks") == 0
    assert adapter.get_access_consumption().consumed is False


async def test_comicdays_unsupported_resource_is_rejected(browser_page) -> None:
    adapter = ComicDaysAdapter()
    await adapter.configure_run(browser_page, "quota")
    with pytest.raises(UnsupportedAccessStrategyError):
        await adapter.configure_quota_resource(browser_page, "premium_ticket")


@pytest.mark.parametrize(
    "post_time", [datetime(2026, 1, 1, tzinfo=UTC), datetime(1999, 1, 1, tzinfo=UTC)]
)
async def test_comicdays_past_or_unchanged_recharge_is_not_consumed(
    browser_page, monkeypatch: pytest.MonkeyPatch, post_time: datetime
) -> None:
    page = await _ticket_page(browser_page)
    states = iter([
        _state(mode="quota", charged=True),
        _state(mode="quota", charged=False, changed=True, charged_at=post_time),
    ])
    monkeypatch.setattr(adapter_module, "observe_comicdays_live_access", lambda *_a, **_k: _anext(states))
    adapter = ComicDaysAdapter()
    adapter.page_change_timeout_ms = 100
    adapter.ticket_recovery_window_ms = 10
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    with pytest.raises(AccessConsumptionUnconfirmedError):
        await adapter.initialize_entry_only(page)
    assert adapter.get_access_consumption().consumed is False


async def _anext(iterator):
    return next(iterator)
