"""Optional preparation must not make stale stock usable or hide fatal stops."""

import asyncio
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from playwright.async_api import Error as PlaywrightError

from screenshot_crawler.core.errors import AccessStopError, UnknownPageStateError
from tests.integration import test_hanayume_premium_browser as hanayume
from tests.integration import test_younganimal_premium_browser as younganimal

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest.mark.parametrize("fixture", [hanayume, younganimal], ids=["hanayume", "younganimal"])
@pytest.mark.parametrize("failure,count", [
    (None, 2), ("click", 0), ("unknown", 2), ("timeout", None),
    ("cancel", 2), ("access-stop", 2),
])
async def test_optional_preparation_uses_fresh_stock_and_preserves_fatal_stops(
    browser_page, monkeypatch, capsys, fixture, failure, count,
):
    premium = fixture.premium
    monkeypatch.setattr(premium, "READY_SECONDS", 0.6)
    adapter, state = await fixture.install(browser_page, count=count if count is not None else 7)
    state["count"] = 7
    calls = []

    async def home(route):
        calls.append("home")
        await route.fulfill(content_type="text/html", body='''
          <header id="xHeader"><button data-e2e="signoutBtn">Logout</button></header>
          <script>fetch('/api/auth/session');fetch('/api/userPoint')</script>''')

    await browser_page.route(premium.HOME, home)
    errors = {
        "click": PlaywrightError("private-url-token"),
        "unknown": UnknownPageStateError("private-account-value"),
        "timeout": TimeoutError(),
        "cancel": asyncio.CancelledError(),
        "access-stop": AccessStopError(reason="http_429", site="synthetic", url="synthetic"),
    }

    async def daily(page, observer, **kwargs):
        calls.append("prepare")
        await page.goto(premium.HOME)
        assert (await observer.wait("stock"))[1]["count"] == 7
        state["count"] = count
        if failure is not None:
            raise errors[failure]

    monkeypatch.setattr(premium, "prepare_daily_gacha", daily)
    pool = tuple(SimpleNamespace(site=premium.HOME.split("//")[1].split(".")[0],
        work_id=1, source_id=i, external_id=f"{fixture.WORK_ID}:{fixture.EPISODE_ID if i == 0 else f'{i:013x}'}",
        locator=premium.HOME + "episodes/" + (fixture.EPISODE_ID if i == 0 else f"{i:013x}"),
        quota_resource="premium_ticket", access_strategy="quota", consumes_quota=True)
        for i in range(4))
    resolver = type(adapter)()
    state["paths"].clear()
    try:
        if failure in {"cancel", "access-stop"}:
            with pytest.raises(type(errors[failure])):
                await resolver.resolve_access_resource_candidates(
                    browser_page, pool, "premium_ticket", timeout_ms=1000)
            assert calls == ["prepare", "home"]
        elif count is None:
            with pytest.raises(UnknownPageStateError):
                await resolver.resolve_access_resource_candidates(
                    browser_page, pool, "premium_ticket", timeout_ms=1000)
        else:
            result = await resolver.resolve_access_resource_candidates(
                browser_page, pool, "premium_ticket", timeout_ms=1000)
            assert result.selected_source_ids == tuple(range(count))
            assert result.stop_resource_pass == (count == 0)
        assert calls.count("prepare") == 1
        assert state["checkouts"] == 0 and not state["access"]
        if not count or failure in {"cancel", "access-stop"}:
            assert not any(p.startswith("/episodes/") for p in state["paths"])
        else:
            assert [p for p in state["paths"] if p.startswith("/episodes/")] == [
                f"/episodes/{fixture.EPISODE_ID}"]
        log = capsys.readouterr().out
        assert ('"event": "preparation_skipped"' in log) == (failure in {"click", "unknown", "timeout"})
        assert "private-url-token" not in log and "private-account-value" not in log
    finally:
        await adapter._premium_entry.observer.close()


@pytest.mark.parametrize("fixture", [hanayume, younganimal], ids=["hanayume", "younganimal"])
@pytest.mark.parametrize("popup", ["invalid-close", "unknown-dialog"])
async def test_actual_gacha_overlay_failure_recovers_without_spin_or_stale_stock(
    browser_page, monkeypatch, capsys, fixture, popup,
):
    premium = fixture.premium
    monkeypatch.setattr(premium, "READY_SECONDS", 0.6)
    state = {"homes": 0, "writes": 0}
    home = '''<header id="xHeader"><button data-e2e="signoutBtn">Logout</button></header>
      <div class="home-gacha"><a class="home-gacha-btn" href="/gacha">Gacha</a></div>
      <script>fetch('/api/auth/session');fetch('/api/userPoint')</script>'''
    gacha = '''<div class="gacha-btn-wrap"><a class="gacha-btn mode-user" data-e2e="gachaExecBtn">すぐ無料ガチャをまわす</a></div>
      <dialog class="dialog POPUP" data-e2e="pop" role="dialog">
      <button type="reset" class="dialog-btn mode-campaign" data-e2e="closeCpPop">×</button></dialog>
      <script>document.querySelector('dialog').showModal();fetch('/api/gacha')</script>'''.replace(
          "POPUP", "mode-campaign" if popup == "invalid-close" else "mode-other")

    async def route(r):
        path = urlsplit(r.request.url).path
        if r.request.method == "POST":
            state["writes"] += 1
            await r.abort()
        elif path == "/":
            state["homes"] += 1
            await r.fulfill(content_type="text/html; charset=utf-8", body=home)
        elif path == "/gacha":
            await r.fulfill(content_type="text/html; charset=utf-8", body=gacha)
        elif path == "/api/gacha":
            await r.fulfill(json={"gacha": {"canRollGacha": True, "gachaTimes": 0}})
        elif path == "/api/userPoint":
            await r.fulfill(json={"bonusValue": 0 if state["homes"] > 1 else 3, "paidCoin": 0})
        elif path == "/api/auth/session":
            await r.fulfill(json={"user": 101})
        else:
            pytest.fail(f"Unexpected synthetic route: {path}")

    await browser_page.route("**/*", route)
    pool = (SimpleNamespace(site=urlsplit(premium.HOME).hostname.split(".")[0],
        work_id=1, source_id=1, external_id=f"{fixture.WORK_ID}:{fixture.EPISODE_ID}",
        locator=fixture.EPISODE_URL, quota_resource="premium_ticket",
        access_strategy="quota", consumes_quota=True),)
    result = await premium.resolve_ticket_candidates(
        browser_page, pool, "premium_ticket", timeout_ms=1000)
    assert result.stop_resource_pass and result.selected_source_ids == ()
    assert state == {"homes": 2, "writes": 0}
    log = capsys.readouterr().out
    assert '"event": "preparation_skipped"' in log
    if fixture is hanayume:
        assert '"event": "gacha_preparation_skipped"' in log
        assert '"phase": "gacha"' in log and '"targets"' in log
