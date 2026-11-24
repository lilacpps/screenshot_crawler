"""Younganimal's account-wide すぐ無料 stock, daily gacha and exact rental entry.

Stock bounds Catalog selection before entry. No candidate-by-candidate search,
resource fallback, daily ledger, or replay of a possibly dispatched action.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, urlsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page, Request, Response

from screenshot_crawler.core.errors import (
    AccessConsumptionUnconfirmedError,
    AccessResourceUnavailableError,
    UnknownPageStateError,
)
from screenshot_crawler.site_adapters.base import AccessConsumption, AccessResourceResolution
from screenshot_crawler.site_adapters.younganimal.live_access import (
    MAX_JSON_BYTES,
    _parse_episode_payload,
    _parse_series_payload,
)

HOME = "https://younganimal.com/"
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
        if (p.scheme == "https" and p.hostname == "younganimal.com" and p.port in (None, 443)
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
                "/api/checkout/rental": "checkout", "/api/gacha": "gacha",
                "/api/auth/session": "auth"}.get(path)
        if kind is None:
            try:
                url = urlsplit(request.url)
                if (_exact_path(request.url.split('?', 1)[0]) == "/api/series/access"
                        and not url.fragment):
                    kind = "series"
                    work_ids = [v for k, v in parse_qsl(url.query, max_num_fields=128)
                                if k.casefold().replace('_', '') in {"seriesid", "workid"}]
                    if any(value != self.work for value in work_ids):
                        self.rows.setdefault("series", []).append((datetime.now(UTC), None))
                        return
            except ValueError:
                self.rows.setdefault("series", []).append((datetime.now(UTC), None))
                return
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
                    and response.url == response.request.url):
                if kind == "checkout":
                    reduced = {"ok": True}
                else:
                    body = await asyncio.wait_for(response.body(), 2.0)
                    if len(body) > MAX_JSON_BYTES:
                        raise ValueError("Native metadata exceeds its bound")
                    data = json.loads(body)
                    if kind == "stock":
                        if isinstance(data, dict) and all(_integer(data.get(k)) for k in ("bonusValue", "paidCoin")):
                            reduced = {"count": data["bonusValue"], "coins": data["paidCoin"]}
                    elif kind == "auth":
                        user = data.get("user") if isinstance(data, dict) else None
                        if type(user) is int and user > 0:
                            reduced = {"user": user}  # Attempt-local only; never serialized.
                    elif kind == "series":
                        parsed = _parse_series_payload(data, episode_id=self.episode)
                        if parsed is not None and parsed[0] == self.work and parsed[1] <= 1:
                            state = parsed[2]
                            if parsed[1] == 0:
                                reduced = {"present": False}
                            elif (state is not None and state.remaining_state != "malformed"
                                  and (state.remaining_seconds is None or _integer(state.remaining_seconds, maximum=PREMIUM_SECONDS))):
                                reduced = {"present": True, "type": state.access_type,
                                           "access": state.has_access, "remaining": state.remaining_seconds}
                    elif kind == "episode":
                        parsed_current = _parse_episode_payload(data, episode_id=self.episode)
                        e = data.get("episode") if isinstance(data, dict) else None
                        a = e.get("access") if isinstance(e, dict) else None
                        s = e.get("series") if isinstance(e, dict) else None
                        if (parsed_current is not None and isinstance(a, dict) and isinstance(s, dict) and e.get("id") == self.episode
                                and a.get("episodeId") == self.episode and s.get("id") == self.work
                                and type(a.get("hasAccess")) is bool and isinstance(a.get("accessType"), str)
                                and type(a.get("isDisableBonus")) is bool
                                # Native UI treats an omitted recovery as Work-ready.
                                # Work can recover between the Work and Premium passes;
                                # this must skip Premium rather than stop the Batch.
                                # Explicit null/malformed values remain invalid.
                                and _integer(s.get("waitAndFreeRecoveryTime", 0), maximum=23 * 3600)
                                and (a.get("timeRemainingInSeconds") is None
                                     or _integer(a["timeRemainingInSeconds"], maximum=PREMIUM_SECONDS))):
                            reduced = {"access": a["hasAccess"], "type": a["accessType"],
                                       "remaining": a.get("timeRemainingInSeconds"),
                                       "remaining_state": ("missing" if "timeRemainingInSeconds" not in a
                                                           else "null" if a["timeRemainingInSeconds"] is None else "valid"),
                                       "disabled": a["isDisableBonus"],
                                       "recovery": s.get("waitAndFreeRecoveryTime", 0)}
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
            raise UnknownPageStateError("Younganimal Premium response bound exceeded")
        rows = [r for r in self.rows.get(kind, ()) if after is None or r[0] > after]
        if not rows:
            return None
        at = max(r[0] for r in rows)
        if any(k == kind and started >= at and req not in self.completed
               for req, (k, started, _valid) in self.starts.items()):
            return None
        latest = [r for r in rows if r[0] == at]
        if len(latest) != 1 or latest[0][1] is None:
            raise UnknownPageStateError(
                f"Younganimal Premium native state is invalid or ambiguous ({kind})")
        return latest[0]

    async def wait(self, kind: str, *, after: datetime | None = None) -> tuple[datetime, dict]:
        deadline = time.monotonic() + READY_SECONDS
        while time.monotonic() < deadline:
            row = self.episode_state(after=after) if kind == "episode" else self.latest(kind, after=after)
            if row is not None:
                return row
            await asyncio.sleep(0.1)
        raise UnknownPageStateError("Younganimal Premium native state did not arrive")

    def episode_state(self, *, after: datetime | None = None) -> tuple[datetime, dict] | None:
        current = self.latest("episode", after=after)
        if current is None or self.latest("auth") is None:
            return None
        at, state = current
        expiry = None
        for series_at, series in self.rows.get("series", ()):
            if series is None:
                raise UnknownPageStateError("Younganimal Premium series binding is ambiguous")
            if not series["present"] or series_at < at:
                continue
            if (series["type"] != state["type"] or series["access"] != state["access"]
                    or series.get("remaining") == 0 and state["access"]):
                raise UnknownPageStateError("Younganimal Premium current/series access conflicts")
            if state["access"] and _integer(series.get("remaining")) and series["remaining"] > 1:
                bound = series_at + timedelta(seconds=series["remaining"] - 1)
                expiry = min(expiry, bound) if expiry is not None else bound
        # An unresolved newer aggregate cannot authorize an earlier snapshot.
        if any(kind == "series" and req not in self.completed
               for req, (kind, start, _valid) in self.starts.items()):
            return None
        return at, {**state, "series_expiry": expiry}

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
        raise UnknownPageStateError("Younganimal Premium prerequisite route changed")


async def _log_home_popup(page: Page, event: str) -> None:
    """Bounded structural diagnostics, excluding titles, URLs and account data."""
    try:
        async with asyncio.timeout(1):
            details = await page.evaluate("""() => {
              const meta=n=>n&&({tag:n.tagName,classes:(n.getAttribute('class')||'').slice(0,120),
                e2e:n.getAttribute('data-e2e')?.slice(0,80),type:n.getAttribute('type')?.slice(0,20),
                role:n.getAttribute('role')?.slice(0,40)});
              const visible=n=>!!(n.getBoundingClientRect().width&&n.getBoundingClientRect().height);
              const ancestors=n=>{
                const rows=[];
                for(let p=n;p&&rows.length<5;p=p.parentElement)
                  rows.push({...meta(p),controls:[...p.querySelectorAll('button,a')].slice(0,8).map(meta)});
                return rows;
              };
              const target=selector=>{
                const nodes=document.querySelectorAll(selector),n=nodes[0],r=n?.getBoundingClientRect();
                return {count:nodes.length,node:meta(n),cover:r?ancestors(document.elementFromPoint(
                  r.x+r.width/2,r.y+r.height/2)):[]};
              };
              const roots=[...document.querySelectorAll('dialog[open],[role="dialog"],[aria-modal="true"]')].filter(visible);
              return {open_dialog_count:roots.length,dialogs:roots.slice(0,4).map(n=>({...meta(n),
                charge_heading_count:n.querySelectorAll('div.dialog-content > h2.dialog-h.mode-waitfree').length,
                controls:[...n.querySelectorAll('button,a')].slice(0,8).map(b=>({...meta(b),
                  is_close:(b.innerText||'').trim()==='閉じる',is_read:(b.innerText||'').trim()==='読む'}))})),
                targets:{home_link:target('div.home-gacha > a.home-gacha-btn[href="/gacha"]'),
                  spin:target('[data-e2e="gachaExecBtn"]')}};
            }""")
    except Exception as exc:  # noqa: BLE001 - diagnostics must not replace the original failure
        details = {"inspection_error": type(exc).__name__}
    phase = {HOME: "home", GACHA: "gacha"}.get(page.url, "other")
    print("Younganimal home popup: " + json.dumps({"event": event, "phase": phase, **details}), flush=True)


async def prepare_daily_gacha(page: Page, observer: PremiumObserver, *, timeout_ms: int) -> None:
    await _goto(page, HOME, timeout_ms)
    await observer.wait("stock")  # Account hydration, not mere absence of a button.
    await observer.wait("auth")
    await page.locator('#xHeader [data-e2e="signoutBtn"]').wait_for(state="attached", timeout=timeout_ms)
    campaign = page.locator('dialog.dialog.mode-campaign[data-e2e="pop"][open]')
    charge = page.locator('dialog.dialog[data-e2e="pop"][open]:has('
                          'div.dialog-content > h2.dialog-h.mode-waitfree)')
    dismissed_routes: set[str] = set()
    dismissed_charges: set[str] = set()
    handlers = []

    async def dismiss_campaign() -> None:
        await _log_home_popup(page, "campaign_detected")
        if page.url not in {HOME, GACHA} or page.url in dismissed_routes or await campaign.count() != 1:
            raise UnknownPageStateError("Younganimal campaign popup is ambiguous or repeated")
        close = campaign.locator('button.dialog-btn.mode-campaign:is([data-e2e="popClose"],'
                                 '[data-e2e="closeCpPop"])')
        if await close.count() != 1 or await close.get_attribute("type") not in {"button", "submit"}:
            raise UnknownPageStateError("Younganimal campaign close is ambiguous")
        dismissed_routes.add(page.url)
        await close.click(timeout=2_000)
        await campaign.wait_for(state="hidden", timeout=2_000)
        print('Younganimal home popup: {"event": "campaign_dismissed"}', flush=True)

    async def dismiss_charge() -> None:
        await _log_home_popup(page, "charge_notice_detected")
        if page.url not in {HOME, GACHA} or page.url in dismissed_charges or await charge.count() != 1:
            raise UnknownPageStateError("Younganimal charge notice is ambiguous or repeated")
        heading = charge.locator('div.dialog-content > h2.dialog-h.mode-waitfree')
        if (await heading.count() != 1 or re.sub(r"\s+", "", await heading.inner_text())
                != "「待つと無料」購読中作品のチャージが完了しました。"):
            raise UnknownPageStateError("Younganimal charge notice heading changed")
        close = charge.locator('div.dialog-content > div.dialog-f > button.dialog-f-btn')
        if (await close.count() != 1 or await close.inner_text() != "閉じる"
                or await close.get_attribute("type") not in {None, "button"}
                or not await close.evaluate("n => !n.closest('form')")):
            raise UnknownPageStateError("Younganimal charge notice close is ambiguous")
        dismissed_charges.add(page.url)
        await close.click(timeout=2_000)
        await charge.wait_for(state="hidden", timeout=2_000)
        print('Younganimal home popup: {"event": "charge_notice_dismissed"}', flush=True)

    async def handle_campaign() -> None:
        try:
            await dismiss_campaign()
        except (PlaywrightError, UnknownPageStateError) as exc:
            # Keep event-listener failures out of subsequent read-only recovery.
            # The original click still fails its bounded popup/actionability wait.
            await _log_home_popup(page, "campaign_close_failed")
            print("Younganimal daily gacha: " + json.dumps({
                "event": "campaign_close_failed", "error_type": type(exc).__name__,
            }), flush=True)

    async def handle_charge() -> None:
        try:
            await dismiss_charge()
        except (PlaywrightError, UnknownPageStateError):
            await _log_home_popup(page, "charge_notice_close_failed")

    try:
        if await page.locator('dialog[open],[role="dialog"],[aria-modal="true"]').count():
            await _log_home_popup(page, "home_ready")
        for popup, dismiss, handler in ((campaign, dismiss_campaign, handle_campaign),
                                        (charge, dismiss_charge, handle_charge)):
            if await popup.count() and await popup.first.is_visible():
                await dismiss()
            await page.add_locator_handler(popup, handler)
            handlers.append(popup)
        link = page.locator('div.home-gacha > a.home-gacha-btn[href="/gacha"]')
        if await link.count() == 0 or (await link.count() == 1 and not await link.is_visible()):
            return
        if await link.count() != 1:
            raise UnknownPageStateError("Younganimal daily gacha link is ambiguous")
        await link.click(timeout=timeout_ms, no_wait_after=True)
        await page.wait_for_url(GACHA, timeout=timeout_ms)
        if page.url != GACHA:
            raise UnknownPageStateError("Younganimal daily gacha route changed")
        _, native = await observer.wait("gacha")
        if not native["can"] or native["times"] != 0:
            return  # Never use a share/retry entitlement.
        button = page.locator('div.gacha-btn-wrap > a.gacha-btn.mode-user[data-e2e="gachaExecBtn"]')
        if await button.count() != 1 or not await button.is_visible():
            raise UnknownPageStateError("Younganimal daily gacha action is unknown")
        if "すぐ無料ガチャをまわす" not in await button.inner_text():
            raise UnknownPageStateError("Younganimal daily gacha label changed")
        await button.click(timeout=2_000, no_wait_after=True)
        # Allow the native action to finish without inspecting its result.
        await asyncio.sleep(GACHA_SETTLE_SECONDS)
    except (PlaywrightError, TimeoutError, UnknownPageStateError):
        await _log_home_popup(page, "gacha_preparation_failed")
        raise
    finally:
        for popup in reversed(handlers):
            await page.remove_locator_handler(popup)


async def _wallet_count(page: Page, observer: PremiumObserver, *, after: datetime) -> dict:
    _, stock = await observer.wait("stock", after=after)
    nodes = page.locator('div.ep-charge-wallet [data-e2e="epChgWalletTicket"]')
    if await nodes.count():
        text = await nodes.inner_text() if await nodes.count() == 1 else ""
        if not re.fullmatch(r"[0-9]+", text) or int(text) != stock["count"]:
            raise UnknownPageStateError("Younganimal Premium wallet/native balance disagrees")
    return stock


async def resolve_ticket_candidates(page: Page, candidates: tuple[object, ...], resource: str,
                                    *, timeout_ms: int, before_episode=None) -> AccessResourceResolution:
    if resource != "premium_ticket" or not candidates:
        raise UnknownPageStateError("Younganimal Premium requires a nonempty explicit pool")
    first = candidates[0]
    match = re.fullmatch(r"([0-9a-f]{13}):([0-9a-f]{13})", first.external_id)
    if (match is None or first.work_id is None or len({c.work_id for c in candidates}) != 1
            or len({c.source_id for c in candidates}) != len(candidates)
            or any(c.site != "younganimal" or c.quota_resource != resource
                   or c.access_strategy != "quota" or not c.consumes_quota
                   or re.fullmatch(match[1] + r":[0-9a-f]{13}", c.external_id) is None
                   or c.locator != HOME + "episodes/" + c.external_id.split(":")[-1]
                   for c in candidates)):
        raise UnknownPageStateError("Younganimal Premium pool identity is invalid")
    observer = PremiumObserver(page, match[2], match[1])
    try:
        async with asyncio.timeout(RESOLUTION_BUDGET_MS / 1000):
            try:
                await prepare_daily_gacha(page, observer, timeout_ms=timeout_ms)
            except (PlaywrightError, TimeoutError, UnknownPageStateError) as exc:
                await _log_home_popup(page, "gacha_preparation_skipped")
                print("Younganimal daily gacha: " + json.dumps({
                    "event": "preparation_skipped", "error_type": type(exc).__name__,
                }), flush=True)
                await _goto(page, HOME, timeout_ms)
                recovered = datetime.now(UTC)
                await page.evaluate("() => fetch('/api/auth/session',{cache:'no-store',redirect:'error'})")
                await observer.wait("auth", after=recovered)
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
            _validate_ungranted_timer(native)
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


def _validate_ungranted_timer(native: dict) -> None:
    if not native["access"] and not (
        native["remaining_state"] == "missing"
        or native["remaining_state"] == "valid" and native["remaining"] == 0
    ):
        raise UnknownPageStateError("Younganimal Premium ungranted timer is contradictory")


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
            raise UnknownPageStateError("Younganimal Premium control disappeared")
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
            raise UnknownPageStateError("Younganimal Premium action changed or is ambiguous")
        return handle

    async def enter(self, page: Page, *, entry_only: bool, read_identity, guard) -> None:
        observer = self.observer
        try:
            if self.clicked:
                raise AccessConsumptionUnconfirmedError("Younganimal Premium action cannot be replayed")
            await read_identity(page)
            _, native = await observer.wait("episode")
            _, stock = await observer.wait("stock")
            _, authenticated = await observer.wait("auth")
            if native["access"]:
                if entry_only:
                    raise AlreadyAccessible()
                return
            if stock["count"] == 0:
                raise AccessResourceUnavailableError("premium_ticket_exhausted", stop_resource_pass=True)
            if native["type"] != "waitAndFree" or native["disabled"] or native["recovery"] <= 0:
                raise AccessResourceUnavailableError("premium_ticket_unavailable")
            _validate_ungranted_timer(native)
            await _wallet_count(page, observer, after=datetime.min.replace(tzinfo=UTC))
            if await page.locator('button[data-e2e="ifRead"]').count() != 1 or await page.locator('button[data-e2e="wfRead"]').count():
                raise UnknownPageStateError("Younganimal Premium/Work Ticket controls conflict")
            await read_identity(page)
            control = await self._control(page, CONTROL, LABEL)
            guard()
            if page.url != self.url:
                raise UnknownPageStateError("Younganimal Premium target route changed")
            self.clicked = True  # The first action opens a confirmation, never retry it either.
            await control.click(timeout=2_000, no_wait_after=True)
            dialog = page.locator('div.ep-main-content.mode-charge > div.ep-charge > dialog.dialog[data-e2e="pop"][open]')
            await dialog.wait_for(state="visible", timeout=3_000)
            if (await page.locator('dialog[open]').count() != 1
                    or await dialog.locator('.dialog-h-price').count() != 1
                    or await dialog.locator('.dialog-h-price').inner_text() != "1枚"
                    or await dialog.locator('.dialog-term-term').count() != 1
                    or await dialog.locator('.dialog-term-term').inner_text() != "15日間"):
                raise UnknownPageStateError("Younganimal Premium confirmation cost/term changed")
            confirm = await self._control(page, CONFIRM, "レンタルする")
            guard()
            # Recheck same native state and live account balance after the actionability trial.
            current_row = observer.episode_state()
            if current_row is None:
                raise UnknownPageStateError("Younganimal Premium current authentication/access is unresolved")
            _, current = current_row
            stock_row = observer.latest("stock")
            auth_row = observer.latest("auth")
            if (stock_row is None or auth_row is None or current != native
                    or stock_row[1] != stock or page.url != self.url or auth_row[1] != authenticated):
                raise UnknownPageStateError("Younganimal Premium state changed before confirmation")
            started = datetime.now(UTC)
            self.confirming = True
            click_error = None
            try:
                await confirm.click(timeout=2_000, no_wait_after=True)
            except BaseException as exc:  # noqa: BLE001 - observe a possibly dispatched click once
                click_error = exc
            await self._reconcile(page, started=started, stock=stock, native=native,
                                  authenticated=authenticated, guard=guard)
            if click_error is not None:
                raise click_error
        finally:
            await observer.close()

    async def _reconcile(self, page: Page, *, started: datetime, stock: dict, native: dict,
                         authenticated: dict, guard) -> None:
        deadline = time.monotonic() + RECOVERY_SECONDS
        reads = 0
        while time.monotonic() < deadline:
            guard()
            if self.bad_checkout:
                raise AccessConsumptionUnconfirmedError("Younganimal blocked a non-ticket or duplicate checkout")
            if page.url != self.url:
                break
            checkout = self.observer.latest("checkout", after=started)
            after = self.observer.episode_state(after=started)
            points = self.observer.latest("stock", after=started)
            auth = self.observer.latest("auth", after=started)
            if checkout is not None and after is not None and points is not None and auth is not None:
                at, grant = after
                remaining = grant["remaining"]
                if (grant["access"] is True and grant["type"] == "purchased"
                        and _integer(remaining, maximum=PREMIUM_SECONDS) and remaining > 1
                        and 0 < grant["recovery"] <= native["recovery"]
                        and auth[1] == authenticated
                        and points[1] == {"count": stock["count"] - 1, "coins": stock["coins"]}):
                    # Native debit + exact checkout/grant are durable even if viewer readiness fails later.
                    expiry = at + timedelta(seconds=remaining - 1)
                    if grant.get("series_expiry") is not None:
                        expiry = min(expiry, grant["series_expiry"])
                    self.consumption = AccessConsumption(
                        consumed=True, resource="premium_ticket", consumed_at=datetime.now(UTC),
                        access_granted_until=expiry,
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
                    }''', ["/api/auth/session", "/api/userPoint", f"/api/episodes/{self.observer.episode}"]),
                        timeout=min(2.0, max(0.01, deadline - time.monotonic())))
                except (PlaywrightError, TimeoutError):
                    pass
            await asyncio.sleep(0.1)
        raise AccessConsumptionUnconfirmedError("Younganimal Premium consumption unconfirmed; no automatic retry")
