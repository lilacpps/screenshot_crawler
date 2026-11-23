"""Synthetic controls and body observations; no external account or content."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from screenshot_crawler.core.errors import (
    AccessStopError,
    PageChangeTimeoutError,
    UnknownPageStateError,
)
from screenshot_crawler.core.models import ContentIdentity, RunConfig
from screenshot_crawler.core.runner import CrawlerRunner
from screenshot_crawler.patterns.forward_click import ForwardClick
from screenshot_crawler.site_adapters.comicdays.adapter import ComicDaysAdapter
from screenshot_crawler.site_adapters.jumpplus.adapter import JumpPlusAdapter
from screenshot_crawler.site_adapters.magapoke.adapter import MagapokeAdapter

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest.fixture(params=[MagapokeAdapter, ComicDaysAdapter, JumpPlusAdapter])
def adapter(request):
    return request.param()


async def setup(page: Page, adapter, monkeypatch: pytest.MonkeyPatch) -> None:
    await page.set_content("""
      <section class="viewer js-viewer"><div class="c-viewer">
        <button class="c-viewer__pager-next page-navigation-forward js-slide-forward"
          style="width:200px;height:100px">next</button>
      </div></section>
      <script>
        window.index=0;window.ready=true;window.clicks=0;window.target=1;
        window.delay=0;window.progress=true;
        document.querySelector('button').onclick=()=>{
          ++window.clicks;
          if(window.progress)setTimeout(()=>{window.index=window.target},window.delay);
        };
      </script>
    """)
    adapter.page_change_timeout_ms = 800
    adapter._forward_click.poll_ms = 10
    if isinstance(adapter, JumpPlusAdapter):
        adapter._first_content_page_index = 0
        adapter._content_page_count = 10

    async def rows(_page):
        state = await page.evaluate("() => ({index:window.index,ready:window.ready})")
        if not state["ready"]:
            return []
        index = state["index"]
        return [{"pageIndex": index, "areaIndex": index, "canvasId": index,
                 "sourcePath": f"synthetic-{index}", "source": {"sourceId": index},
                 "x": 0, "y": 0, "width": 20, "height": 20}]

    if isinstance(adapter, MagapokeAdapter):
        monkeypatch.setattr(adapter, "_canvas_rows", rows)
    elif isinstance(adapter, JumpPlusAdapter):
        monkeypatch.setattr(adapter, "_capture_rows", rows)
    else:
        async def active(_page, **_kwargs):
            body = await rows(page)
            return {"rows": body, "ready": bool(body), "complete": bool(body),
                    "sliderNow": 1 + 2 * await page.evaluate("window.index"), "sliderLast": 20}

        monkeypatch.setattr(adapter, "_active", active)
        monkeypatch.setattr(adapter, "_signature", lambda body: tuple(r["areaIndex"] for r in body))


def lose_click_result(monkeypatch: pytest.MonkeyPatch, *, dispatch: bool = True) -> list[int]:
    original = Locator.click
    calls = []

    async def click(locator, **kwargs):
        calls.append(1)
        if dispatch:
            await original(locator, **kwargs)
        raise PlaywrightTimeoutError("synthetic ambiguous click")

    monkeypatch.setattr(Locator, "click", click)
    return calls


async def test_click_returns_early_and_uses_three_second_upper_bound(
    browser_page, adapter, monkeypatch,
) -> None:
    await setup(browser_page, adapter, monkeypatch)
    observed = []
    original = Locator.click

    async def click(locator, **kwargs):
        observed.append(kwargs["timeout"])
        await original(locator, **kwargs)

    monkeypatch.setattr(Locator, "click", click)
    await adapter.go_next(browser_page)
    assert observed == [3_000]
    assert await browser_page.evaluate("window.clicks") == 1
    assert adapter._forward_click.error is None
    assert adapter._forward_click.debug["click_ms"] < 1_500


@pytest.mark.parametrize("delay", [0, 120])
async def test_timeout_observes_delayed_body_without_second_click(
    browser_page, adapter, monkeypatch, delay,
) -> None:
    await setup(browser_page, adapter, monkeypatch)
    await browser_page.evaluate("delay => window.delay=delay", delay)
    lose_click_result(monkeypatch)
    await adapter.go_next(browser_page)
    await adapter.wait_for_change(browser_page, ContentIdentity(page_id="before"))
    assert await browser_page.evaluate("window.clicks") == 1
    assert adapter._forward_click.debug["outcome"] == "recovered_body"
    assert adapter._forward_click.error is None
    assert adapter._advance_pending is False


async def test_timeout_waits_for_ready_body(browser_page, adapter, monkeypatch) -> None:
    await setup(browser_page, adapter, monkeypatch)
    lose_click_result(monkeypatch)
    await adapter.go_next(browser_page)
    await browser_page.evaluate("() => {window.ready=false;setTimeout(()=>window.ready=true,120)}")
    await adapter.wait_for_change(browser_page, ContentIdentity(page_id="before"))
    assert await browser_page.evaluate("window.clicks") == 1
    assert adapter._forward_click.debug["outcome"] == "recovered_body"


async def test_unchanged_body_preserves_timeout_without_replaying_magapoke_retries(
    browser_page, adapter, monkeypatch,
) -> None:
    await setup(browser_page, adapter, monkeypatch)
    adapter.page_change_timeout_ms = 160
    calls = lose_click_result(monkeypatch, dispatch=False)
    await adapter.go_next(browser_page)
    error = adapter._forward_click.error
    with pytest.raises((PlaywrightTimeoutError, PageChangeTimeoutError)) as raised:
        await adapter.wait_for_change(browser_page, ContentIdentity(page_id="before"))
    assert raised.value is error
    assert await browser_page.evaluate("window.clicks") == 0
    # Even an accidental second go_next must not dispatch another click.
    with pytest.raises((PlaywrightTimeoutError, PageChangeTimeoutError)):
        await adapter.go_next(browser_page)
    assert await browser_page.evaluate("window.clicks") == 0
    assert len(calls) == 1


@pytest.mark.parametrize("fault", ["skipped", "reverse", "route", "empty"])
async def test_unknown_or_missing_progress_never_recovers(
    browser_page, adapter, monkeypatch, fault,
) -> None:
    await setup(browser_page, adapter, monkeypatch)
    adapter.page_change_timeout_ms = 160
    await browser_page.evaluate("() => window.target=3")
    if fault == "reverse":
        await browser_page.evaluate("() => {window.index=2;window.target=0}")
    lose_click_result(monkeypatch)
    await adapter.go_next(browser_page)
    if fault == "route":
        await browser_page.evaluate("location.hash='changed'")
    if fault == "empty":
        await browser_page.evaluate("window.ready=false")
    with pytest.raises((UnknownPageStateError, PlaywrightTimeoutError, PageChangeTimeoutError)):
        await adapter.wait_for_change(browser_page, ContentIdentity(page_id="before"))
    assert await browser_page.evaluate("window.clicks") == 1


async def test_cancelled_read_only_recovery_propagates(browser_page, adapter, monkeypatch) -> None:
    await setup(browser_page, adapter, monkeypatch)
    lose_click_result(monkeypatch, dispatch=False)
    await adapter.go_next(browser_page)
    task = asyncio.create_task(adapter.wait_for_change(browser_page, ContentIdentity()))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await browser_page.evaluate("window.clicks") == 0


async def test_real_actionability_wait_recovers_temporary_cover(browser_page, monkeypatch) -> None:
    adapter = MagapokeAdapter()
    await setup(browser_page, adapter, monkeypatch)
    await browser_page.evaluate("""() => {
      const cover=document.createElement('div');
      cover.style='position:fixed;inset:0;z-index:999;background:white';
      document.body.append(cover);setTimeout(()=>cover.remove(),1100);
    }""")
    await adapter.go_next(browser_page)
    assert await browser_page.evaluate("window.clicks") == 1
    assert adapter._forward_click.debug["outcome"] == "click_returned"


async def test_control_diagnostics_exclude_content_and_survive_failure(browser_page, monkeypatch) -> None:
    adapter = MagapokeAdapter()
    await setup(browser_page, adapter, monkeypatch)
    await browser_page.evaluate("document.querySelector('button').textContent='secret body'")
    lose_click_result(monkeypatch, dispatch=False)
    await adapter.go_next(browser_page)
    assert "secret body" not in json.dumps(adapter._forward_click.debug)
    assert "coveringTag" in adapter._forward_click.debug["control"]
    assert ForwardClick.timeout_ms == 3_000


async def test_persistent_cover_stops_with_control_diagnostics(browser_page, adapter, monkeypatch):
    await setup(browser_page, adapter, monkeypatch)
    adapter._forward_click.timeout_ms = 80
    adapter.page_change_timeout_ms = 120
    await browser_page.evaluate("""() => {
      const cover=document.createElement('div');cover.textContent='private';
      cover.style='position:fixed;inset:0;z-index:999;background:white';
      document.body.append(cover);
    }""")
    await adapter.go_next(browser_page)
    with pytest.raises((PlaywrightTimeoutError, PageChangeTimeoutError)):
        await adapter.wait_for_change(browser_page, ContentIdentity())
    assert await browser_page.evaluate("window.clicks") == 0
    assert adapter._forward_click.debug["control"]["receivesPointer"] is False
    assert adapter._forward_click.debug["control"]["coveringTag"] == "DIV"
    assert 'private' not in json.dumps(adapter._forward_click.debug)


async def test_diagnostic_error_does_not_prevent_recovery(browser_page, adapter, monkeypatch):
    await setup(browser_page, adapter, monkeypatch)
    lose_click_result(monkeypatch)

    async def broken(*_args, **_kwargs):
        raise RuntimeError('diagnostic failure')

    monkeypatch.setattr(Locator, 'evaluate', broken)
    await adapter.go_next(browser_page)
    await adapter.wait_for_change(browser_page, ContentIdentity())
    assert adapter._forward_click.debug['control'] == {'observation_failed': True}
    assert adapter._forward_click.debug['outcome'] == 'recovered_body'


async def test_slow_observation_cannot_reset_recovery_deadline(browser_page, adapter, monkeypatch):
    await setup(browser_page, adapter, monkeypatch)
    calls = lose_click_result(monkeypatch, dispatch=False)
    adapter.page_change_timeout_ms = 100
    await adapter.go_next(browser_page)
    cancelled = []

    async def blocked(_page):
        try:
            await asyncio.Future()
        finally:
            cancelled.append(True)

    monkeypatch.setattr(adapter, '_forward_observation', blocked)
    with pytest.raises((PlaywrightTimeoutError, PageChangeTimeoutError)):
        await asyncio.wait_for(adapter.wait_for_change(browser_page, ContentIdentity()), timeout=1)
    assert cancelled == [True]
    assert len(calls) == 1


@pytest.mark.parametrize('error', [RuntimeError('failure'), asyncio.CancelledError()])
async def test_non_timeout_click_failure_propagates(browser_page, adapter, monkeypatch, error):
    await setup(browser_page, adapter, monkeypatch)

    async def broken(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(Locator, 'click', broken)
    with pytest.raises(type(error)) as raised:
        await adapter.go_next(browser_page)
    assert raised.value is error
    assert adapter._forward_click.error is None


async def test_no_body_prestate_keeps_original_click_failure(browser_page, adapter, monkeypatch):
    await setup(browser_page, adapter, monkeypatch)
    await browser_page.evaluate('window.ready=false')
    calls = lose_click_result(monkeypatch, dispatch=False)
    with pytest.raises((PlaywrightTimeoutError, PageChangeTimeoutError)) as raised:
        await adapter.go_next(browser_page)
    assert raised.value is adapter._forward_click.error
    assert raised.value.__cause__ is not raised.value
    assert len(calls) == 1


async def test_access_stop_interrupts_read_only_recovery(
    browser_page, adapter, monkeypatch, tmp_path,
):
    await setup(browser_page, adapter, monkeypatch)
    calls = lose_click_result(monkeypatch, dispatch=False)
    await adapter.go_next(browser_page)
    stop = AccessStopError(reason='http_429', site='synthetic', url='https://example.test')

    async def wait_for_stop():
        await asyncio.sleep(0.03)
        return stop

    runner = CrawlerRunner(RunConfig(site='synthetic', source_url='https://example.test',
                                    output_dir=tmp_path/'out', diagnostics_dir=tmp_path/'diag'))
    runner._access_guard = SimpleNamespace(wait_for_stop=wait_for_stop)
    with pytest.raises(AccessStopError) as raised:
        await runner._adapter_call(
            adapter.wait_for_change(browser_page, ContentIdentity()), 'wait_for_change')
    assert raised.value is stop
    assert adapter._forward_click.debug['outcome'] == 'cancelled'
    assert len(calls) == 1
