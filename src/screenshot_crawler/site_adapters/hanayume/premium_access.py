"""Hanayume's account-wide すぐ無料 stock, daily gacha and exact rental entry.

Stock bounds Catalog selection before entry. No candidate-by-candidate search,
resource fallback, daily ledger, or replay of a possibly dispatched action.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page, Request, Response

from screenshot_crawler.core.errors import (
    AccessConsumptionUnconfirmedError,
    AccessResourceUnavailableError,
    UnknownPageStateError,
)
from screenshot_crawler.site_adapters.base import AccessConsumption, AccessResourceResolution

HOME = "https://hanayume.com/"
GACHA = HOME + "gacha"
RESOLUTION_BUDGET_MS = 65_000
GACHA_SETTLE_SECONDS = 5.0
READY_SECONDS = 8.0
RECOVERY_SECONDS = 5.0
PREMIUM_SECONDS = 15 * 24 * 60 * 60
CONTROL = ('div.ep-main-content.mode-charge > div.ep-charge > div.ep-charge-act '
           '> button.ep-charge-act-btn[data-e2e="ifRead"]')
CONFIRM = ('div.ep-main-content.mode-charge > div.ep-charge > dialog.dialog[data-e2e="pop"][open] '
           'button.dialog-btn.mode-buy[data-e2e="rentConf"]')
LABEL = "「すぐ無料」で読む1枚"


def _integer(value: object, *, maximum: int | None = None) -> bool:
    return type(value) is int and value >= 0 and (maximum is None or value <= maximum)


def _ticket_checkout(payload: object, episode: str) -> bool:
    return (type(payload) is dict and set(payload) == {"articleIds", "amount", "ticketCount"}
            and payload["articleIds"] == [episode]
            and type(payload["amount"]) is int and payload["amount"] == 0
            and type(payload["ticketCount"]) is int and payload["ticketCount"] == 1)


def _exact_path(url: str) -> str | None:
    try:
        p = urlsplit(url)
        if (p.scheme == "https" and p.hostname == "hanayume.com" and p.port in (None, 443)
                and p.username is None and p.password is None and not p.query and not p.fragment):
            return p.path
    except ValueError:
        pass
    return None


class PremiumObserver:
    """Bounded same-main-frame natural responses; retain only entitlement scalars."""

    def __init__(self, page: Page, episode: str, work: str) -> None:
        self.page, self.episode, self.work = page, episode, work
        self.starts: dict[Request, tuple[str, datetime, bool]] = {}
        self.rows: dict[str, list[tuple[datetime, dict | None]]] = {}
        self.tasks: list[asyncio.Task] = []
        self.completed: set[Request] = set()
        self.overflow = False
        self.request_listener = self._request
        self.response_listener = self._response
        page.on("request", self.request_listener)
        page.on("response", self.response_listener)

    def _request(self, request: Request) -> None:
        path = _exact_path(request.url)
        kind = {"/api/userPoint": "stock", f"/api/episodes/{self.episode}": "episode",
                "/api/checkout/rental": "checkout", "/api/gacha": "gacha"}.get(path)
        if kind is None:
            return
        if len(self.starts) >= 64:
            self.overflow = True
            return
        valid = (request.frame == self.page.main_frame and not request.is_navigation_request()
                 and request.redirected_from is None and request.resource_type in {"fetch", "xhr"}
                 and request.method == ("POST" if kind == "checkout" else "GET"))
        if kind == "gacha":
            valid = (request.frame == self.page.main_frame and not request.is_navigation_request()
                     and request.redirected_from is None and request.resource_type in {"fetch", "xhr"}
                     and request.method in {"GET", "POST"})
        if kind == "checkout":
            try:
                valid = valid and _ticket_checkout(request.post_data_json, self.episode)
            except (ValueError, PlaywrightError):
                valid = False
        self.starts[request] = (kind, datetime.now(UTC), valid)

    def _response(self, response: Response) -> None:
        if response.request in self.starts:
            self.tasks.append(asyncio.create_task(self._capture(response)))

    async def _capture(self, response: Response) -> None:
        kind, started, valid = self.starts[response.request]
        reduced = None
        try:
            if (valid and response.status == 200 and response.frame == self.page.main_frame
                    and _exact_path(response.url) == _exact_path(response.request.url)):
                if kind == "checkout":
                    reduced = {"ok": True}
                else:
                    data = await asyncio.wait_for(response.json(), 2.0)
                    if kind == "stock":
                        if isinstance(data, dict) and all(_integer(data.get(k)) for k in ("bonusValue", "paidCoin")):
                            reduced = {"count": data["bonusValue"], "coins": data["paidCoin"]}
                    elif kind == "episode":
                        e = data.get("episode") if isinstance(data, dict) else None
                        a = e.get("access") if isinstance(e, dict) else None
                        s = e.get("series") if isinstance(e, dict) else None
                        if (isinstance(a, dict) and isinstance(s, dict) and e.get("id") == self.episode
                                and a.get("episodeId") == self.episode and s.get("id") == self.work
                                and type(a.get("hasAccess")) is bool and isinstance(a.get("accessType"), str)
                                and type(a.get("isDisableBonus")) is bool
                                and _integer(s.get("waitAndFreeRecoveryTime"), maximum=23 * 3600)
                                and (a.get("timeRemainingInSeconds") is None
                                     or _integer(a["timeRemainingInSeconds"], maximum=PREMIUM_SECONDS))):
                            reduced = {"access": a["hasAccess"], "type": a["accessType"],
                                       "remaining": a.get("timeRemainingInSeconds"),
                                       "disabled": a["isDisableBonus"],
                                       "recovery": s["waitAndFreeRecoveryTime"]}
                    else:
                        g = data.get("gacha") if isinstance(data, dict) else None
                        if (isinstance(g, dict) and type(g.get("canRollGacha")) is bool
                                and _integer(g.get("gachaTimes"))):
                            reduced = {"can": g["canRollGacha"], "times": g["gachaTimes"]}
        except (PlaywrightError, TimeoutError, ValueError, TypeError, AttributeError):
            pass
        self.rows.setdefault(kind, []).append((started, reduced))
        self.completed.add(response.request)

    def latest(self, kind: str, *, after: datetime | None = None) -> tuple[datetime, dict] | None:
        if self.overflow:
            raise UnknownPageStateError("Hanayume Premium response bound exceeded")
        rows = [r for r in self.rows.get(kind, ()) if after is None or r[0] > after]
        if not rows:
            return None
        at = max(r[0] for r in rows)
        if any(k == kind and started >= at and req not in self.completed
               for req, (k, started, _valid) in self.starts.items()):
            return None
        latest = [r for r in rows if r[0] == at]
        if len(latest) != 1 or latest[0][1] is None:
            raise UnknownPageStateError("Hanayume Premium native state is invalid or ambiguous")
        return latest[0]

    async def wait(self, kind: str, *, after: datetime | None = None) -> tuple[datetime, dict]:
        deadline = time.monotonic() + READY_SECONDS
        while time.monotonic() < deadline:
            row = self.latest(kind, after=after)
            if row is not None:
                return row
            await asyncio.sleep(0.1)
        raise UnknownPageStateError("Hanayume Premium native state did not arrive")

    async def close(self) -> None:
        self.page.remove_listener("request", self.request_listener)
        self.page.remove_listener("response", self.response_listener)
        for task in self.tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)


async def _goto(page: Page, url: str, timeout_ms: int) -> None:
    response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    if response is None or response.status != 200 or page.url != url:
        raise UnknownPageStateError("Hanayume Premium prerequisite route changed")


async def _log_home_popup(page: Page, event: str) -> None:
    """Bounded structural evidence for worker stdout; never log page content/URLs."""
    try:
        async with asyncio.timeout(1):
            details = await page.evaluate("""() => {
                const meta = n => n && ({tag: n.tagName,
                    classes: (n.getAttribute('class') || '').slice(0, 120),
                    e2e: n.getAttribute('data-e2e')?.slice(0, 80),
                    role: n.getAttribute('role')?.slice(0, 40),
                    type: n.getAttribute('type')?.slice(0, 20)});
                const ancestors = n => {
                    const result = [];
                    for (let p = n; p && result.length < 5; p = p.parentElement)
                        result.push({...meta(p), controls: [...p.querySelectorAll('button,a')]
                            .slice(0, 8).map(meta)});
                    return result;
                };
                const target = selector => {
                    const nodes = document.querySelectorAll(selector), n = nodes[0];
                    const r = n?.getBoundingClientRect();
                    return {count: nodes.length, node: meta(n),
                        cover: r ? ancestors(document.elementFromPoint(
                            r.x + r.width / 2, r.y + r.height / 2)) : []};
                };
                const dialogs = [...document.querySelectorAll('dialog[open]')];
                const links = document.querySelectorAll('div.home-gacha > a.home-gacha-btn[href="/gacha"]');
                const rect = links[0]?.getBoundingClientRect();
                return {open_dialog_count: dialogs.length,
                    dialogs: dialogs.slice(0, 4).map(n => ({...meta(n),
                        controls: [...n.querySelectorAll('button,a')].slice(0, 8).map(meta)})),
                    gacha_link_count: links.length,
                    link_cover: rect ? meta(document.elementFromPoint(
                        rect.x + rect.width / 2, rect.y + rect.height / 2)) : null,
                    targets: {home_link: target('div.home-gacha > a.home-gacha-btn[href="/gacha"]'),
                        spin: target('[data-e2e="gachaExecBtn"]')},
                    other_popups: [...document.querySelectorAll('[role="dialog"],[aria-modal="true"],.mission-modal')]
                        .filter(n => n.getBoundingClientRect().width && n.getBoundingClientRect().height)
                        .slice(0, 4).map(n => ({...meta(n),
                            controls: [...n.querySelectorAll('button,a')].slice(0, 8).map(meta)}))};
            }""")
    except Exception as exc:  # noqa: BLE001 - diagnostics must preserve the original failure
        details = {"inspection_error": type(exc).__name__}
    phase = {HOME: "home", GACHA: "gacha"}.get(page.url, "other")
    print("Hanayume home popup: " + json.dumps({"event": event, "phase": phase, **details}), flush=True)


async def prepare_daily_gacha(page: Page, observer: PremiumObserver, *, timeout_ms: int) -> None:
    await _goto(page, HOME, timeout_ms)
    await observer.wait("stock")  # Account hydration, not mere absence of a button.
    await page.locator('#xHeader [data-e2e="signoutBtn"]').wait_for(state="attached", timeout=timeout_ms)
    campaign = page.locator('dialog.dialog.mode-campaign[data-e2e="pop"][open]')
    dismissed_routes: set[str] = set()
    handler_added = False

    async def dismiss_campaign() -> None:
        await _log_home_popup(page, "campaign_detected")
        if page.url not in {HOME, GACHA} or page.url in dismissed_routes or await campaign.count() != 1:
            raise UnknownPageStateError("Hanayume campaign popup is ambiguous or repeated")
        # The current site applies POPUP_CLOSE after its legacy campaign marker,
        # so the rendered close button uses popClose rather than closeCpPop.
        close = campaign.locator('button.dialog-btn.mode-campaign:is([data-e2e="popClose"],'
                                 '[data-e2e="closeCpPop"])')
        if await close.count() != 1 or await close.get_attribute("type") != "submit":
            raise UnknownPageStateError("Hanayume campaign close is ambiguous")
        dismissed_routes.add(page.url)
        await close.click(timeout=2_000)
        await campaign.wait_for(state="hidden", timeout=2_000)
        print('Hanayume home popup: {"event": "campaign_dismissed"}', flush=True)

    async def handle_campaign() -> None:
        try:
            await dismiss_campaign()
        except (PlaywrightError, UnknownPageStateError):
            # Exceptions escaping a locator-handler event can poison the next
            # Playwright call, including read-only recovery. Leave the popup
            # untouched and let the original action's bounded wait fail.
            await _log_home_popup(page, "campaign_close_failed")

    try:
        if await campaign.count() and await campaign.first.is_visible():
            await dismiss_campaign()
        # A campaign can appear after account hydration, while the link waits
        # for actionability. Never force-click through an unknown overlay.
        await page.add_locator_handler(campaign, handle_campaign)
        handler_added = True
        link = page.locator('div.home-gacha > a.home-gacha-btn[href="/gacha"]')
        if await link.count() == 0 or (await link.count() == 1 and not await link.is_visible()):
            return
        if await link.count() != 1:
            raise UnknownPageStateError("Hanayume daily gacha link is ambiguous")
        await link.click(timeout=timeout_ms, no_wait_after=True)
        await page.wait_for_url(GACHA, timeout=timeout_ms)
        if page.url != GACHA:
            raise UnknownPageStateError("Hanayume daily gacha route changed")
        _, native = await observer.wait("gacha")
        if not native["can"] or native["times"] != 0:
            return  # Never use a share/retry entitlement.
        button = page.locator('div.gacha-btn-wrap > a.gacha-btn.mode-user[data-e2e="gachaExecBtn"]')
        if await button.count() != 1 or not await button.is_visible():
            raise UnknownPageStateError("Hanayume daily gacha action is unknown")
        if "すぐ無料ガチャをまわす" not in await button.inner_text():
            raise UnknownPageStateError("Hanayume daily gacha label changed")
        # One dispatch only. Results/animation are irrelevant to resource selection;
        # the resolver reads fresh ticket stock afterward, even if this click fails.
        await button.click(timeout=2_000, no_wait_after=True)
        await asyncio.sleep(GACHA_SETTLE_SECONDS)
    except (PlaywrightError, UnknownPageStateError):
        await _log_home_popup(page, "home_gacha_navigation_failed" if page.url == HOME
                              else "gacha_preparation_failed")
        raise
    finally:
        if handler_added:
            await page.remove_locator_handler(campaign)


async def _wallet_count(page: Page, observer: PremiumObserver, *, after: datetime) -> dict:
    _, stock = await observer.wait("stock", after=after)
    nodes = page.locator('div.ep-charge-wallet [data-e2e="epChgWalletTicket"]')
    if await nodes.count():
        text = await nodes.inner_text() if await nodes.count() == 1 else ""
        if not re.fullmatch(r"[0-9]+", text) or int(text) != stock["count"]:
            raise UnknownPageStateError("Hanayume Premium wallet/native balance disagrees")
    return stock


async def resolve_ticket_candidates(page: Page, candidates: tuple[object, ...], resource: str,
                                    *, timeout_ms: int, before_episode=None) -> AccessResourceResolution:
    if resource != "premium_ticket" or not candidates:
        raise UnknownPageStateError("Hanayume Premium requires a nonempty explicit pool")
    first = candidates[0]
    match = re.fullmatch(r"([0-9a-f]{13}):([0-9a-f]{13})", first.external_id)
    if (match is None or first.work_id is None or len({c.work_id for c in candidates}) != 1
            or len({c.source_id for c in candidates}) != len(candidates)
            or any(c.site != "hanayume" or c.quota_resource != resource
                   or c.access_strategy != "quota" or not c.consumes_quota
                   or re.fullmatch(match[1] + r":[0-9a-f]{13}", c.external_id) is None
                   or c.locator != HOME + "episodes/" + c.external_id.split(":")[-1]
                   for c in candidates)):
        raise UnknownPageStateError("Hanayume Premium pool identity is invalid")
    observer = PremiumObserver(page, match[2], match[1])
    try:
        async with asyncio.timeout(RESOLUTION_BUDGET_MS / 1000):
            try:
                await prepare_daily_gacha(page, observer, timeout_ms=timeout_ms)
            except (PlaywrightError, TimeoutError, UnknownPageStateError) as exc:
                # Optional preparation never authorizes a replay or stale stock.
                # Recover only the read-only account page, not the gacha action.
                await _log_home_popup(page, "gacha_preparation_skipped")
                print("Hanayume daily gacha: " + json.dumps({
                    "event": "preparation_skipped", "error_type": type(exc).__name__,
                }), flush=True)
                await _goto(page, HOME, timeout_ms)
                await page.locator('#xHeader [data-e2e="signoutBtn"]').wait_for(
                    state="attached", timeout=timeout_ms)
            refreshed = datetime.now(UTC)
            await page.evaluate("() => fetch('/api/userPoint',{cache:'no-store',redirect:'error'})")
            _, home_stock = await observer.wait("stock", after=refreshed)
            if home_stock["count"] == 0:
                return _selection(candidates, 0)
            if before_episode is not None:
                await before_episode(page)
            started = datetime.now(UTC)
            await _goto(page, first.locator, timeout_ms)
            _, native = await observer.wait("episode", after=started)
            stock = await _wallet_count(page, observer, after=started)
            count = stock["count"]
            if count == 0:
                return _selection(candidates, 0)
            if native["recovery"] == 0:
                return _selection(candidates, count, reason="work_ticket_priority", limit=0)
            if (native["disabled"] or (not native["access"] and native["type"] != "waitAndFree")):
                return _selection(candidates, count, reason="premium_ticket_unavailable", limit=0)
            return _selection(candidates, count)
    finally:
        await observer.close()


def _selection(candidates: tuple[object, ...], count: int, *, reason: str | None = None,
               limit: int | None = None) -> AccessResourceResolution:
    n = count if limit is None else limit
    reason = reason or ("premium_ticket_exhausted" if count == 0 else "premium_ticket_stock_limit")
    return AccessResourceResolution(tuple(c.source_id for c in candidates[:n]),
                                    tuple((c.source_id, reason) for c in candidates[n:]),
                                    stop_resource_pass=count == 0)


class AlreadyAccessible(AccessResourceUnavailableError):
    def __init__(self) -> None:
        super().__init__("already_accessible")
        self.stop_work = False


class PremiumEntry:
    def __init__(self, page: Page, episode: str, work: str) -> None:
        self.observer = PremiumObserver(page, episode, work)
        self.url = HOME + "episodes/" + episode
        self.consumption = AccessConsumption()
        self.clicked = False
        self.confirming = False
        self.checkout_dispatched = False
        self.bad_checkout = False

    async def install(self) -> None:
        async def route_checkout(route) -> None:
            request = route.request
            try:
                valid = (self.confirming and not self.checkout_dispatched
                         and _exact_path(request.url) == "/api/checkout/rental"
                         and request.frame == self.observer.page.main_frame
                         and request.method == "POST"
                         and _ticket_checkout(request.post_data_json, self.observer.episode))
            except (ValueError, PlaywrightError):
                valid = False
            if not valid:
                self.bad_checkout = True
                await route.abort()
                return
            self.checkout_dispatched = True
            await route.fallback()
        await self.observer.page.route("**/api/checkout/rental*", route_checkout)

    async def _control(self, page: Page, selector: str, label: str):
        nodes = page.locator(selector)
        if await nodes.count() != 1:
            raise AccessResourceUnavailableError("premium_ticket_unavailable")
        handle = await nodes.element_handle()
        if handle is None:
            raise UnknownPageStateError("Hanayume Premium control disappeared")
        await handle.click(trial=True, timeout=2_000)
        if not await handle.evaluate(r'''(n, args) => {
          const [selector,label]=args, nodes=[...document.querySelectorAll(selector)];
          const r=n.getBoundingClientRect(),s=getComputedStyle(n);
          const c=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);
          const dialog=n.closest('dialog');
          const dialogs=[...document.querySelectorAll('dialog[open]')];
          const price=dialog?[...dialog.querySelectorAll('.dialog-h-price')]:[];
          const term=dialog?[...dialog.querySelectorAll('.dialog-term-term')]:[];
          const confirmation=label!=='レンタルする' || (dialogs.length===1 && dialogs[0]===dialog &&
            price.length===1 && price[0].innerText==='1枚' && term.length===1 && term[0].innerText==='15日間');
          return confirmation && n.isConnected && nodes.length===1 && nodes[0]===n && n.tagName==='BUTTON' &&
            n.type==='button' && !n.disabled && n.getAttribute('aria-disabled')!=='true' &&
            n.innerText.replace(/\s+/g,'').trim()===label && !n.hasAttribute('onclick') &&
            !['data-price','data-cost','data-buy-price','formaction'].some(a=>n.hasAttribute(a)) &&
            s.display!=='none' && s.visibility!=='hidden' && Number(s.opacity||'1')>0 &&
            r.width>0 && r.height>0 &&
            !!c && (c===n || n.contains(c));
        }''', [selector, label]):
            raise UnknownPageStateError("Hanayume Premium action changed or is ambiguous")
        return handle

    async def enter(self, page: Page, *, entry_only: bool, read_identity, guard) -> None:
        observer = self.observer
        try:
            if self.clicked:
                raise AccessConsumptionUnconfirmedError("Hanayume Premium action cannot be replayed")
            await read_identity(page)
            _, native = await observer.wait("episode")
            _, stock = await observer.wait("stock")
            if native["access"]:
                if entry_only:
                    raise AlreadyAccessible()
                return
            if stock["count"] == 0:
                raise AccessResourceUnavailableError("premium_ticket_exhausted", stop_resource_pass=True)
            if native["type"] != "waitAndFree" or native["disabled"] or native["recovery"] <= 0:
                raise AccessResourceUnavailableError("premium_ticket_unavailable")
            await _wallet_count(page, observer, after=datetime.min.replace(tzinfo=UTC))
            if await page.locator('button[data-e2e="ifRead"]').count() != 1 or await page.locator('button[data-e2e="wfRead"]').count():
                raise UnknownPageStateError("Hanayume Premium/Work Ticket controls conflict")
            await read_identity(page)
            control = await self._control(page, CONTROL, LABEL)
            guard()
            if page.url != self.url:
                raise UnknownPageStateError("Hanayume Premium target route changed")
            self.clicked = True  # The first action opens a confirmation, never retry it either.
            await control.click(timeout=2_000, no_wait_after=True)
            dialog = page.locator('div.ep-main-content.mode-charge > div.ep-charge > dialog.dialog[data-e2e="pop"][open]')
            await dialog.wait_for(state="visible", timeout=3_000)
            if (await page.locator('dialog[open]').count() != 1
                    or await dialog.locator('.dialog-h-price').count() != 1
                    or await dialog.locator('.dialog-h-price').inner_text() != "1枚"
                    or await dialog.locator('.dialog-term-term').count() != 1
                    or await dialog.locator('.dialog-term-term').inner_text() != "15日間"):
                raise UnknownPageStateError("Hanayume Premium confirmation cost/term changed")
            confirm = await self._control(page, CONFIRM, "レンタルする")
            guard()
            # Recheck same native state and live account balance after the actionability trial.
            _, current = observer.latest("episode")
            _, latest_stock = observer.latest("stock")
            if current != native or latest_stock != stock or page.url != self.url:
                raise UnknownPageStateError("Hanayume Premium state changed before confirmation")
            started = datetime.now(UTC)
            self.confirming = True
            click_error = None
            try:
                await confirm.click(timeout=2_000, no_wait_after=True)
            except BaseException as exc:  # noqa: BLE001 - observe a possibly dispatched click once
                click_error = exc
            await self._reconcile(page, started=started, stock=stock, native=native, guard=guard)
            if click_error is not None:
                raise click_error
        finally:
            await observer.close()

    async def _reconcile(self, page: Page, *, started: datetime, stock: dict, native: dict, guard) -> None:
        deadline = time.monotonic() + RECOVERY_SECONDS
        reads = 0
        while time.monotonic() < deadline:
            guard()
            if self.bad_checkout:
                raise AccessConsumptionUnconfirmedError("Hanayume blocked a non-ticket or duplicate checkout")
            if page.url != self.url:
                break
            checkout = self.observer.latest("checkout", after=started)
            after = self.observer.latest("episode", after=started)
            points = self.observer.latest("stock", after=started)
            if checkout is not None and after is not None and points is not None:
                at, grant = after
                remaining = grant["remaining"]
                if (grant["access"] is True and grant["type"] == "purchased"
                        and _integer(remaining, maximum=PREMIUM_SECONDS) and remaining > 1
                        and 0 < grant["recovery"] <= native["recovery"]
                        and points[1] == {"count": stock["count"] - 1, "coins": stock["coins"]}):
                    # Native debit + exact checkout/grant are durable even if viewer readiness fails later.
                    self.consumption = AccessConsumption(
                        consumed=True, resource="premium_ticket", consumed_at=datetime.now(UTC),
                        access_granted_until=at + timedelta(seconds=remaining - 1),
                        stop_resource_pass=points[1]["count"] == 0,
                    )
                    if (await page.locator('#comici-viewer').count() == 1
                            and await page.locator('#comici-viewer').is_visible()
                            and await page.locator('button[data-e2e="ifRead"],button[data-e2e="wfRead"],dialog[open]').count() == 0):
                        return
            if checkout is not None and reads < 2:
                reads += 1
                try:
                    await asyncio.wait_for(page.evaluate('''async paths => {
                      for (const path of paths) await fetch(path,{method:'GET',cache:'no-store',redirect:'error'});
                    }''', ["/api/userPoint", f"/api/episodes/{self.observer.episode}"]),
                        timeout=min(2.0, max(0.01, deadline - time.monotonic())))
                except (PlaywrightError, TimeoutError):
                    pass
            await asyncio.sleep(0.1)
        raise AccessConsumptionUnconfirmedError("Hanayume Premium consumption unconfirmed; no automatic retry")
