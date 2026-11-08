"""Purchased-only ebookjapan Reader adapter (Stage 02 implementation)."""

from __future__ import annotations

import asyncio
import hashlib
import io
import re
import time
from collections.abc import Mapping
from urllib.parse import urlsplit

from PIL import Image
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page, Response

from screenshot_crawler.core.access_guard import AccessProfile
from screenshot_crawler.core.capture import CaptureResult
from screenshot_crawler.core.errors import (
    UnknownPageStateError,
    UnsupportedAccessStrategyError,
)
from screenshot_crawler.core.models import AccessStrategy, ContentContext, ContentIdentity
from screenshot_crawler.core.state import PageState
from screenshot_crawler.discovery.service import DiscoveryIncompleteError
from screenshot_crawler.site_adapters.base import SiteAdapter
from screenshot_crawler.site_adapters.ebookjapan.discovery import (
    _FULL_LISTING_JS,
    MAX_SOURCE_RESPONSE_BYTES,
    SITE_HOST,
    SITE_ORIGIN,
    _classify_card,
    _rights_signature,
    parse_ebookjapan_source_witness,
)
from screenshot_crawler.site_adapters.ebookjapan.viewer import (
    ANCHOR_READER_JS,
    CAPTURE_OBSERVER_JS,
    FRAME_STATE_JS,
    MAX_PART_PIXELS,
    MAX_SLOTS,
    NAVIGATION_TARGET_JS,
    normalize_title,
)

_PRODUCT_URL = re.compile(
    r"^https://ebookjapan\.yahoo\.co\.jp/books/(?P<series>[1-9][0-9]*)/(?P<product>A[0-9]+)/$"
)
_PURCHASED_READER_PATH = re.compile(r"^/viewer/purchased/B[0-9]+/$")
_PRODUCT_ID = re.compile(r"^A[0-9]+$")
_LISTING_WAIT_MS = 15_000
_SOURCE_BODY_WAIT_SECONDS = 8
_OWNERSHIP_SETTLE_SECONDS = 8
_OWNERSHIP_POLL_SECONDS = 0.35
_OWNERSHIP_STABLE_READS = 3
_READER_NAVIGATION_WAIT_MS = 15_000
_INTRO_READY_WAIT_MS = 8_000
_READER_ROUTE_WAIT_MS = 20_000
_FRAME_READY_WAIT_MS = 20_000
_FRAME_POLL_MS = 150
_INIT_BUDGET_MS = 120_000
_RANGE_SELECTOR = "input[type='range'].seekbar__slider"
# These are the only observed toolbar-center action profiles. The click must
# happen at the original viewport and match a unique backing-size/rect pair;
# fitting first can put the same center inside the page-turn region.
_OBSERVED_CENTER_ACTION_VIEWPORT = (1906, 986)
_OBSERVED_CENTER_ACTION_RECT_TOLERANCE = 1.0
_OBSERVED_CENTER_ACTION_PROFILES: tuple[
    tuple[str, tuple[int, int], tuple[float, float, float, float, float, float]], ...
] = (
    (
        "angel10-cover-816x1200",
        (816, 1200),
        (282.5208, 953.0, 0.0, 986.0, 670.4792, 986.0),
    ),
    (
        "muda1-cover-1088x1600",
        (1088, 1600),
        (282.5208, 953.0, 0.0, 986.0, 670.4792, 986.0),
    ),
    (
        "muda16-cover-1120x1600",
        (1120, 1600),
        (
            262.8020935058594,
            953.0000305175781,
            0.0,
            986.0,
            690.1979370117188,
            986.0,
        ),
    ),
)
_CAPTURE_CLASS = "D"
_FALLBACK_REASON_CODE = "SOURCE_NATIVE_PROOF_NOT_ESTABLISHED"
_CAPTURE_POLICY_REVISION = "ebookjapan-owned-rendered-png-v1-20261108"


def parse_ebookjapan_product_url(url: str) -> tuple[str, str] | None:
    """Accept only a canonical Catalog product URL without query or fragment."""

    match = _PRODUCT_URL.fullmatch(url) if isinstance(url, str) else None
    return (match.group("series"), match.group("product")) if match else None


def _same_listing_document(response: Response, *, series_id: str) -> bool:
    try:
        request = response.request
        frame = request.frame
        parsed = urlsplit(response.url)
    except Exception:  # noqa: BLE001 - a detached/malformed response is UNKNOWN
        return False
    return (
        request.resource_type == "document"
        and request.is_navigation_request()
        and frame == response.frame.page.main_frame
        and parsed.scheme == "https"
        and parsed.hostname == SITE_HOST
        and parsed.path == f"/books/all/{series_id}/"
        and not parsed.query
        and not parsed.fragment
        and response.request.redirected_from is None
    )


class EbookJapanAdapter(SiteAdapter):
    """Capture only a Catalog book whose current listing card proves ownership."""

    page_change_timeout_ms = 15_000

    def __init__(self) -> None:
        self._series_id: str | None = None
        self._external_id: str | None = None
        self._work_key: str | None = None
        self._access_strategy: AccessStrategy = "auto"
        self._source_response: Response | None = None
        self._owned_title: str | None = None
        self._page: Page | None = None
        self._reader_path: str | None = None
        self._reader_total: int | None = None
        self._reader_entry_counter: tuple[int, int] | None = None
        self._last_native_counter: int | None = None
        self._expected_current: int = 1
        self._capture_viewport: tuple[int, int] | None = None
        self._seen_slot_ids: set[int] = set()
        self._captured_slot_order: list[int] = []
        self._next_dom_ordinal: int | None = None
        self._pending_identity_key: tuple[object, ...] | None = None
        self._pending_page_id: str | None = None
        self._last_capture_page_id: str | None = None
        self._last_capture_parts: tuple[dict[str, object], ...] = ()
        self._last_capture_node_key: tuple[object, ...] | None = None
        self._last_capture_paint_signature: tuple[object, ...] | None = None
        self._last_capture_ids: tuple[int, ...] = ()
        self._last_capture_ordinals: tuple[int, ...] = ()
        self._last_capture_part_count: int = 0
        self._transition_before_key: tuple[object, ...] | None = None
        self._transition_pending: bool = False
        self._terminal_end_verified: bool = False

    def get_access_profile(self) -> AccessProfile:
        return AccessProfile(
            relevant_host=lambda url: (urlsplit(url).hostname or "").lower() == SITE_HOST
        )

    def get_initialize_timeout_ms(self, default_ms: int) -> int:
        # Includes the bounded source-body read, ownership settle window, and
        # one normal Reader navigation. Every wait still has its own limit.
        return max(default_ms, _INIT_BUDGET_MS)

    def resolve_initial_navigation_url(self, source_url: str) -> str:
        identity = parse_ebookjapan_product_url(source_url)
        if identity is None:
            raise UnknownPageStateError(
                "ebookjapan requires an exact canonical product URL"
            )
        series_id, external_id = identity
        if self._external_id is not None and self._external_id != external_id:
            raise UnknownPageStateError(
                "ebookjapan Catalog identity differs from its product URL"
            )
        self._series_id = series_id
        self._external_id = external_id
        return f"{SITE_ORIGIN}/books/all/{series_id}/"

    async def configure_target_identity(
        self, external_id: str, work_key: str
    ) -> None:
        if not isinstance(external_id, str) or not _PRODUCT_ID.fullmatch(external_id):
            raise UnknownPageStateError("ebookjapan Catalog product identity is invalid")
        if self._external_id is not None and self._external_id != external_id:
            raise UnknownPageStateError(
                "ebookjapan Catalog identity differs from its product URL"
            )
        self._external_id = external_id
        self._work_key = work_key

    async def configure_run(self, page: Page, access_strategy: AccessStrategy) -> None:
        del page
        if access_strategy != "direct":
            raise UnsupportedAccessStrategyError(
                "ebookjapan owned Reader capture requires access_strategy='direct'"
            )
        self._access_strategy = access_strategy

    async def configure_quota_resource(
        self, page: Page, quota_resource: str | None
    ) -> None:
        del page
        if quota_resource is not None:
            raise UnsupportedAccessStrategyError(
                "ebookjapan does not support quota resources"
            )

    async def prepare_page(self, page: Page) -> None:
        self._page = page
        self._source_response = None
        # This Page-only init hook observes normal Reader rendering before the
        # site's scripts run. It is inert outside the exact purchased route.
        await page.add_init_script(script=CAPTURE_OBSERVER_JS)

        def observe_response(response: Response) -> None:
            series_id = self._series_id
            if series_id is not None and _same_listing_document(
                response, series_id=series_id
            ):
                self._source_response = response

        page.on("response", observe_response)

    async def _verify_static_owned_witness(self) -> None:
        series_id, external_id = self._series_id, self._external_id
        response = self._source_response
        if series_id is None or external_id is None or response is None:
            raise UnknownPageStateError(
                "ebookjapan exact listing source response is unavailable"
            )
        if response.status != 200:
            raise UnknownPageStateError(
                "ebookjapan listing source response was not HTTP 200"
            )
        content_type = response.headers.get("content-type", "").lower()
        if not content_type.startswith("text/html"):
            raise UnknownPageStateError(
                "ebookjapan listing source response is not HTML"
            )
        try:
            body = await asyncio.wait_for(
                response.body(), timeout=_SOURCE_BODY_WAIT_SECONDS
            )
            if len(body) > MAX_SOURCE_RESPONSE_BYTES:
                raise UnknownPageStateError(
                    "ebookjapan listing source response exceeded its size bound"
                )
            source_html = body.decode("utf-8")
            witnesses = parse_ebookjapan_source_witness(
                source_html, series_id=series_id
            )
        except (
            DiscoveryIncompleteError,
            UnicodeDecodeError,
            TimeoutError,
            PlaywrightError,
        ):
            raise UnknownPageStateError(
                "ebookjapan listing source ownership witness is incomplete"
            ) from None
        finally:
            if "body" in locals():
                del body
            if "source_html" in locals():
                del source_html
        matches = [item for item in witnesses if item.external_id == external_id]
        if len(matches) != 1 or matches[0].path != f"/books/{series_id}/{external_id}/" or not matches[0].owned:
            raise UnknownPageStateError(
                "ebookjapan source does not prove the exact Catalog book is owned"
            )

    async def _owned_listing_snapshot(self, page: Page) -> Mapping[str, object]:
        series_id, external_id = self._series_id, self._external_id
        if series_id is None or external_id is None:
            raise UnknownPageStateError("ebookjapan Catalog target is not configured")
        expected_url = f"{SITE_ORIGIN}/books/all/{series_id}/"
        current = urlsplit(page.url)
        if (current.scheme, current.hostname, current.path, current.query, current.fragment) != (
            "https", SITE_HOST, f"/books/all/{series_id}/", "", ""
        ):
            raise UnknownPageStateError("ebookjapan left the exact full-list entry route")
        payload = await page.evaluate(_FULL_LISTING_JS)
        if not isinstance(payload, Mapping):
            raise UnknownPageStateError("ebookjapan listing identity is unavailable")
        if (
            payload.get("pageUrl") != expected_url
            or payload.get("pagePath") != f"/books/all/{series_id}/"
            or payload.get("pageHost") != SITE_HOST
            or payload.get("accountAuthenticated") is not True
            or payload.get("oldestFirst") is not True
            or type(payload.get("declaredTotal")) is not int
        ):
            raise UnknownPageStateError(
                "ebookjapan signed-in listing or oldest-first state is unverified"
            )
        rows = payload.get("rows")
        if not isinstance(rows, list):
            raise UnknownPageStateError("ebookjapan listing rows are malformed")
        target_path = f"/books/{series_id}/{external_id}/"
        matches = [
            row for row in rows
            if isinstance(row, Mapping) and row.get("path") == target_path
        ]
        if len(matches) != 1:
            raise UnknownPageStateError(
                "ebookjapan exact Catalog card is missing or duplicated"
            )
        row = matches[0]
        title = row.get("title")
        if not isinstance(title, str) or not title.strip():
            raise UnknownPageStateError("ebookjapan owned card title is missing")
        return {
            "payload": payload,
            "row": row,
            "title": title,
            "ownership": _classify_card(row),
        }

    async def _wait_for_owned_card(self, page: Page) -> Mapping[str, object]:
        """Wait for the static owned bit to agree with settled visible rights."""

        deadline = time.monotonic() + _OWNERSHIP_SETTLE_SECONDS
        previous: tuple[object, ...] | None = None
        stable_reads = 0
        while time.monotonic() < deadline:
            snapshot = await self._owned_listing_snapshot(page)
            payload = snapshot["payload"]
            row = snapshot["row"]
            assert isinstance(payload, Mapping) and isinstance(row, Mapping)
            # A matching SSR-owned bit is a hydration witness, not a live
            # entitlement. Wait through a transient client price/basket state;
            # never click until the visible card independently says owned.
            if snapshot["ownership"] == "owned":
                signature = (
                    payload.get("pageUrl"),
                    payload.get("accountAuthenticated"),
                    row.get("path"),
                    row.get("title"),
                    _rights_signature({"rows": [row]}),
                )
                if signature == previous:
                    stable_reads += 1
                else:
                    previous = signature
                    stable_reads = 1
                if stable_reads >= _OWNERSHIP_STABLE_READS:
                    return snapshot
            else:
                previous = None
                stable_reads = 0
            remaining = deadline - time.monotonic()
            if remaining > 0:
                await page.wait_for_timeout(
                    min(round(_OWNERSHIP_POLL_SECONDS * 1000), max(1, round(remaining * 1000)))
                )
        raise UnknownPageStateError(
            "ebookjapan owned-card hydration did not settle to the static ownership witness"
        ) from None

    async def _wait_for_signed_in_listing(self, page: Page) -> None:
        """Wait only for the observed account shell to finish hydrating."""

        series_id = self._series_id
        if series_id is None:
            raise UnknownPageStateError("ebookjapan Catalog target is not configured")
        expected_url = f"{SITE_ORIGIN}/books/all/{series_id}/"
        deadline = time.monotonic() + _OWNERSHIP_SETTLE_SECONDS
        while True:
            payload = await page.evaluate(_FULL_LISTING_JS)
            if not isinstance(payload, Mapping):
                raise UnknownPageStateError("ebookjapan listing identity is unavailable")
            if (
                payload.get("pageUrl") != expected_url
                or payload.get("pagePath") != f"/books/all/{series_id}/"
                or payload.get("pageHost") != SITE_HOST
            ):
                raise UnknownPageStateError(
                    "ebookjapan left the exact full-list entry route while account state settled"
                )
            if (
                payload.get("oldestFirst") is not True
                or type(payload.get("declaredTotal")) is not int
                or payload.get("declaredTotal", 0) < 1
            ):
                raise UnknownPageStateError(
                    "ebookjapan oldest-first listing state is unavailable"
                )
            if payload.get("accountAuthenticated") is True:
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            await page.wait_for_timeout(
                min(
                    round(_OWNERSHIP_POLL_SECONDS * 1000),
                    max(1, round(remaining * 1000)),
                )
            )
        raise UnknownPageStateError(
            "ebookjapan signed-in account shell did not settle within its bounded wait"
        ) from None

    async def _preflight_owned_card(self, page: Page) -> str:
        await self._verify_static_owned_witness()
        series_id, external_id = self._series_id, self._external_id
        if series_id is None or external_id is None:
            raise UnknownPageStateError("ebookjapan Catalog target is not configured")
        target_path = f"/books/{series_id}/{external_id}/"
        card = page.locator(".book-list__item").filter(
            has=page.locator(f'a.book-item[href="{target_path}"]')
        )
        await page.wait_for_function(
            "path => [...document.querySelectorAll('.book-list__item')].some(card => "
            "[...card.querySelectorAll('a.book-item[href]')].some(a => new URL(a.href).pathname === path))",
            arg=target_path,
            timeout=_LISTING_WAIT_MS,
        )
        await self._wait_for_signed_in_listing(page)
        await card.scroll_into_view_if_needed()
        stable = await self._wait_for_owned_card(page)
        action = card.locator("button.icon-btn-wrapper__btn.icon-btn")
        if await card.count() != 1 or await action.count() != 1:
            raise UnknownPageStateError("ebookjapan owned Reader action is missing or ambiguous")
        if not await action.is_visible() or not await action.is_enabled():
            raise UnknownPageStateError("ebookjapan owned Reader action is unavailable")
        action_shape = await action.evaluate(
            "button => ({label:(button.innerText||'').trim().normalize('NFKC'), "
            "readIcon:[...button.querySelectorAll('[class]')].filter(e=>e.classList.contains('font-read')).length})"
        )
        if action_shape != {"label": "読む", "readIcon": 1}:
            raise UnknownPageStateError("ebookjapan owned card action is not the observed Reader control")
        self._owned_title = str(stable["title"])
        return target_path

    async def _recheck_target_before_click(
        self, page: Page, *, target_path: str, card, action
    ) -> None:
        snapshot = await self._owned_listing_snapshot(page)
        if snapshot["ownership"] != "owned" or normalize_title(str(snapshot["title"])) != normalize_title(self._owned_title or ""):
            raise UnknownPageStateError(
                "ebookjapan owned card changed immediately before Reader entry"
            )
        if await card.count() != 1 or await action.count() != 1:
            raise UnknownPageStateError(
                "ebookjapan exact owned Reader action became ambiguous"
            )
        hrefs = await card.locator("a.book-item[href]").evaluate_all(
            "links => links.map(a => {try {const u=new URL(a.href); return u.origin==='https://ebookjapan.yahoo.co.jp'&&!u.search&&!u.hash?u.pathname:null;} catch{return null;}})"
        )
        if hrefs != [target_path] or not await action.is_visible() or not await action.is_enabled():
            raise UnknownPageStateError(
                "ebookjapan exact owned Reader action is no longer available"
            )

    async def _dismiss_known_intro(self, page: Page) -> None:
        # Wait only for the observed benign onboarding notice or the normal
        # Reader controls. Unknown overlays remain a fail-closed state.
        await page.wait_for_function(
            """() => {
              const visible=e=>!!e&&e.getClientRects().length>0&&getComputedStyle(e).display!=='none'&&getComputedStyle(e).visibility!=='hidden';
              return visible(document.querySelector('.intro-modal__box')) ||
                (visible(document.querySelector('.legacy-comic-header__title')) &&
                 visible(document.querySelector('.legacy-comic-footer__page-output')));
            }""",
            timeout=_INTRO_READY_WAIT_MS,
        )
        modal = page.locator(".intro-modal__box")
        if await modal.count() == 0:
            return
        if await modal.count() != 1 or not await modal.is_visible():
            raise UnknownPageStateError("ebookjapan Reader has an ambiguous onboarding overlay")
        details = await modal.evaluate(
            """box => ({
              text:(box.innerText||box.textContent||'').normalize('NFKC').replace(/\\s+/g,' ').trim(),
              controls:[...box.querySelectorAll('button,[role="button"]')].filter(e=>e.getClientRects().length>0)
                .map(e=>(e.innerText||e.getAttribute('aria-label')||'').normalize('NFKC').trim()),
              formControls:box.querySelectorAll('input,select,textarea').length
            })"""
        )
        if not isinstance(details, Mapping):
            raise UnknownPageStateError("ebookjapan Reader onboarding notice is unavailable")
        text = normalize_title(str(details.get("text") or ""))
        controls = details.get("controls")
        benign = (
            "ビューアーが新しくなりました" in text
            and "ビューアーメニュー" in text
            and "旧バージョンに変更" in text
            and details.get("formControls") == 0
            and controls == ["OK"]
        )
        if not benign:
            raise UnknownPageStateError(
                "ebookjapan Reader onboarding overlay differs from the observed reading notice"
            )
        button = modal.get_by_role("button", name="OK", exact=True)
        if await button.count() != 1 or not await button.is_visible() or not await button.is_enabled():
            raise UnknownPageStateError("ebookjapan Reader onboarding OK control is ambiguous")
        await button.click(timeout=_READER_NAVIGATION_WAIT_MS)
        await modal.wait_for(state="detached", timeout=_READER_NAVIGATION_WAIT_MS)

    async def _reader_controls(self, page: Page, *, expected_path: str) -> Mapping[str, object]:
        state = await page.evaluate(
            """({expectedPath}) => {
              const visible=e=>{if(!e||e.getClientRects().length===0)return false;for(let n=e;n;n=n.parentElement){const s=getComputedStyle(n);if(n.hidden||s.display==='none'||s.visibility==='hidden'||s.visibility==='collapse'||Number(s.opacity)===0)return false;}return true;};
              const title=document.querySelector('.legacy-comic-header__title'),counter=document.querySelector('.legacy-comic-footer__page-output');
              const value=(counter?.innerText||counter?.textContent||'').trim(),m=value.match(/^(\\d+)\\s*\\/\\s*(\\d+)$/);
              const range=[...document.querySelectorAll("input[type='range'].seekbar__slider")];
              const layout=document.querySelector('.comic-viewer__scroll-container');
              const slots=[...document.querySelectorAll('.comic-viewer__page-slot')];
              const end=[...document.querySelectorAll('.next-item.book-last-dead-end__next')].some(e=>visible(e)&&(()=>{const r=e.getBoundingClientRect();return r.right>0&&r.left<innerWidth&&r.bottom>0&&r.top<innerHeight;})());
              const rangeInfo=range.length===1?{tag:range[0].tagName,type:range[0].type,min:Number(range[0].min),max:Number(range[0].max),value:Number(range[0].value),disabled:range[0].disabled,visible:visible(range[0])}:null;
              return {path:location.pathname,host:location.hostname,query:location.search,hash:location.hash,
                expectedPath,documentReady:document.readyState,title:title&&visible(title)?(title.innerText||title.textContent||'').trim():null,
                counter:counter&&visible(counter)&&m?{current:Number(m[1]),total:Number(m[2])}:null,
                rangeCount:range.length,range:rangeInfo,slotCount:slots.length,
                horizontalRtl:!!layout?.classList.contains('comic-viewer__scroll-container--horizontal-rtl'),
                spread:!!layout?.classList.contains('comic-viewer__scroll-container--spread'),visibleEnd:end,
                documentMatches:!!window.__ejReaderAnchor&&window.__ejReaderAnchor.document===document&&window.__ejReaderAnchor.pathname===location.pathname,
                layoutMatchesAnchor:!!window.__ejReaderAnchor&&window.__ejReaderAnchor.layout===layout};
            }""",
            {"expectedPath": expected_path},
        )
        if not isinstance(state, Mapping):
            raise UnknownPageStateError("ebookjapan Reader control state is unavailable")
        expected_host = "ebookjapan.yahoo.co.jp"
        if state.get("host") != expected_host or state.get("path") != expected_path or state.get("query") or state.get("hash"):
            raise UnknownPageStateError("ebookjapan Reader left the exact purchased route")
        return state

    async def _require_reader_content(self, page: Page, *, expected_path: str) -> tuple[int, int]:
        state = await self._reader_controls(page, expected_path=expected_path)
        title = state.get("title")
        if title is not None and normalize_title(str(title)) != normalize_title(self._owned_title or ""):
            raise UnknownPageStateError("ebookjapan Reader title differs from the owned Catalog card")
        counter = state.get("counter")
        if not isinstance(counter, Mapping):
            raise UnknownPageStateError("ebookjapan Reader counter is not visibly available")
        parsed = (counter.get("current"), counter.get("total"))
        if not all(type(value) is int for value in parsed):
            raise UnknownPageStateError("ebookjapan Reader counter is malformed")
        current, total = parsed
        if current < 1 or total != self._reader_total or current > total:
            raise UnknownPageStateError("ebookjapan Reader counter does not match its frozen slot inventory")
        if state.get("documentMatches") is not True:
            raise UnknownPageStateError("ebookjapan Reader document anchor changed")
        if (
            state.get("horizontalRtl") is not True
            or state.get("spread") is not True
            or state.get("layoutMatchesAnchor") is not True
        ):
            raise UnknownPageStateError("ebookjapan Reader layout mode changed after its slot anchor")
        if state.get("visibleEnd") is True:
            raise UnknownPageStateError("ebookjapan Reader is already at its observed END state")
        return current, total

    async def _wait_for_content_frame(
        self,
        page: Page,
        *,
        expected_path: str,
        expected_current: int,
        expected_total: int,
        require_counter: bool = False,
    ) -> Mapping[str, object]:
        """Allow a bounded natural canvas transfer to settle after navigation."""

        deadline = time.monotonic() + _FRAME_READY_WAIT_MS / 1000
        last_status = "unobserved"
        while time.monotonic() < deadline:
            frame = await page.evaluate(
                FRAME_STATE_JS, {"expectedCurrent": expected_current}
            )
            if not isinstance(frame, Mapping):
                raise UnknownPageStateError("ebookjapan Reader frame state is malformed")
            status = frame.get("status")
            if frame.get("routeStable") is not True and status not in {"identity-mismatch", "slot-order-mismatch"}:
                raise UnknownPageStateError("ebookjapan Reader frame route is not stable")
            if frame.get("slotCount") not in (None, expected_total):
                raise UnknownPageStateError("ebookjapan Reader slot inventory changed while waiting for content")
            if status == "content":
                counter = frame.get("counter")
                if require_counter and (frame.get("counterVisible") is not True or not isinstance(counter, Mapping)):
                    raise UnknownPageStateError("ebookjapan Reader native counter is not visibly available")
                if isinstance(counter, Mapping):
                    native_current, native_total = counter.get("current"), counter.get("total")
                    if (
                        native_total != expected_total
                        or (expected_current == 1 and native_current != 1)
                        or (expected_current != 1 and (type(native_current) is not int or native_current < 2))
                    ):
                        raise UnknownPageStateError("ebookjapan Reader native counter conflicts with the current frame shape")
                title = frame.get("title")
                if title is not None and normalize_title(str(title)) != normalize_title(self._owned_title or ""):
                    raise UnknownPageStateError("ebookjapan Reader title changed while content was settling")
                if urlsplit(page.url).path != expected_path:
                    raise UnknownPageStateError("ebookjapan Reader left its pinned purchased route")
                return frame
            if status in {"identity-mismatch", "slot-order-mismatch", "counter-total-mismatch", "end"}:
                raise UnknownPageStateError(
                    f"ebookjapan Reader frame changed identity while waiting ({status})"
                )
            if status not in {"partial", "loading"}:
                raise UnknownPageStateError("ebookjapan Reader frame state is unsupported")
            last_status = str(status)
            await page.wait_for_timeout(_FRAME_POLL_MS)
        raise UnknownPageStateError(
            f"ebookjapan Reader frame did not settle from {last_status} within its bounded wait"
        ) from None

    @staticmethod
    def _frame_nodes_key(frame: Mapping[str, object]) -> tuple[object, ...]:
        parts = frame.get("parts")
        if not isinstance(parts, list):
            raise UnknownPageStateError("ebookjapan visible frame parts are malformed")
        key: list[object] = []
        for part in parts:
            if not isinstance(part, Mapping):
                raise UnknownPageStateError("ebookjapan visible frame part is malformed")
            key.extend((part.get("slotId"), part.get("canvasId")))
        return tuple(key)

    @staticmethod
    def _frame_slot_backing_signature(frame: Mapping[str, object]) -> tuple[object, ...]:
        parts = frame.get("parts")
        if not isinstance(parts, list):
            raise UnknownPageStateError("ebookjapan frame backing signature is malformed")
        keys = (
            "slotId", "slotOrdinal", "canvasId", "canvasIndex",
            "backingWidth", "backingHeight",
        )
        if any(not isinstance(part, Mapping) for part in parts):
            raise UnknownPageStateError("ebookjapan frame backing part is malformed")
        return tuple(tuple(part.get(key) for key in keys) for part in parts)

    @staticmethod
    def _frame_transfer_signature(frame: Mapping[str, object]) -> tuple[object, ...]:
        parts = frame.get("parts")
        if not isinstance(parts, list):
            raise UnknownPageStateError("ebookjapan frame transfer signature is malformed")
        keys = (
            "drawGeneration", "successfulDraws", "mutationCount", "clipCalls",
            "lastFullDraw", "resetObserved", "contextIs2d", "observerOverflow",
            "drawReady",
        )
        if any(not isinstance(part, Mapping) for part in parts):
            raise UnknownPageStateError("ebookjapan frame transfer part is malformed")
        return tuple(tuple(part.get(key) for key in keys) for part in parts)

    @staticmethod
    def _visible_slot_ids(frame: Mapping[str, object]) -> list[int]:
        parts = frame.get("parts")
        if not isinstance(parts, list):
            raise UnknownPageStateError("ebookjapan visible frame parts are malformed")
        result: list[int] = []
        for part in parts:
            if not isinstance(part, Mapping) or type(part.get("slotId")) is not int:
                raise UnknownPageStateError("ebookjapan frame lacks a stable run-local slot ID")
            result.append(part["slotId"])
        if len(result) != len(set(result)):
            raise UnknownPageStateError("ebookjapan visible frame repeats a run-local slot ID")
        return result

    @staticmethod
    def _native_counter(frame: Mapping[str, object]) -> int | None:
        if frame.get("counterVisible") is not True:
            return None
        counter = frame.get("counter")
        if not isinstance(counter, Mapping):
            return None
        current, total = counter.get("current"), counter.get("total")
        return current if type(current) is int and type(total) is int else None

    def _capture_coverage_complete(self) -> bool:
        total = self._reader_total
        return (
            type(total) is int
            and total > 0
            and len(self._captured_slot_order) == total
            and len(self._seen_slot_ids) == total
            and self._seen_slot_ids == set(range(1, total + 1))
            and len(set(self._captured_slot_order)) == total
            and self._next_dom_ordinal == -1
        )

    @staticmethod
    def _is_verified_end_frame(frame: Mapping[str, object], *, total: int) -> bool:
        if (
            frame.get("status") != "end"
            or frame.get("routeStable") is not True
            or frame.get("slotCount") != total
            or frame.get("parts") != []
            or frame.get("visibleSlots") != []
        ):
            return False
        terminal = frame.get("terminal")
        if not isinstance(terminal, Mapping):
            return False
        common = (
            terminal.get("rootCount") == 1
            and terminal.get("innerCount") == 1
            and terminal.get("rootVisible") is True
            and terminal.get("innerVisible") is True
            and terminal.get("rootInViewport") is True
            and terminal.get("innerInViewport") is True
            and terminal.get("insidePinnedLayout") is True
            and terminal.get("shellChainValid") is True
            and terminal.get("visibleSlotCount") == 0
            and terminal.get("visiblePageCanvasCount") == 0
            and terminal.get("modalCount") == 0
            and terminal.get("actionInventoryCapped") is False
            and terminal.get("actionPartitionComplete") is True
            and terminal.get("unknownActionCount") == 0
            and terminal.get("visibleActionCount") == frame.get("visibleActions")
        )
        if not common:
            return False
        if terminal.get("nativeCounterVisible") is not frame.get("counterVisible"):
            return False
        if terminal.get("nativeCounterVisible") is True:
            counter = terminal.get("nativeCounter")
            if not isinstance(counter, Mapping) or counter.get("current") != total or counter.get("total") != total:
                return False
        partition = terminal.get("partition")
        if not isinstance(partition, Mapping) or any(
            type(count) is not int or count < 0 for count in partition.values()
        ) or sum(partition.values()) != frame.get("visibleActions"):
            return False
        profile = terminal.get("profile")
        if profile == "angel-dead-end":
            marker = frame.get("deadEnd")
            modules = terminal.get("moduleCounts")
            return (
                isinstance(marker, list)
                and len(marker) == 1
                and isinstance(marker[0], Mapping)
                and marker[0].get("visible") is True
                and marker[0].get("textExact") is True
                and marker[0].get("controls") == 0
                and isinstance(marker[0].get("rect"), Mapping)
                and marker[0]["rect"].get("viewport") is True
                and terminal.get("markerCount") == 1
                and terminal.get("markerInsideInner") is True
                and terminal.get("markerVisible") is True
                and terminal.get("markerTextExact") is True
                and terminal.get("markerControls") == 0
                and terminal.get("riskyActionCount") == 0
                and isinstance(modules, Mapping)
                and modules.get("review") == 1
                and modules.get("coupon") == 1
                and modules.get("author") == 1
                and modules.get("i2i") == 1
                and partition.get("review") == 1
                and partition.get("coupon") == 1
                and partition.get("recommendAuthor", 0) >= 1
                and partition.get("recommendI2i", 0) >= 1
                and set(modules) == {"review", "coupon", "author", "i2i"}
                and set(partition).issubset({"review", "coupon", "recommendAuthor", "recommendI2i"})
                and terminal.get("variant") == "line-coupon-only-v1"
                and terminal.get("lotteryButtonCount") == 0
                and isinstance(terminal.get("headerCounts"), Mapping)
                and terminal["headerCounts"] == {
                    "close-button": 0,
                    "contents-button": 0,
                    "settings-button": 0,
                }
            )
        if profile == "angel-dead-end-observed-controls":
            marker = frame.get("deadEnd")
            modules = terminal.get("moduleCounts")
            headers = terminal.get("headerCounts")
            return (
                isinstance(marker, list)
                and len(marker) == 1
                and isinstance(marker[0], Mapping)
                and marker[0].get("visible") is True
                and marker[0].get("textExact") is True
                and marker[0].get("controls") == 0
                and isinstance(marker[0].get("rect"), Mapping)
                and marker[0]["rect"].get("viewport") is True
                and terminal.get("variant") == "lottery-plus-native-header-v1"
                and terminal.get("markerCount") == 1
                and terminal.get("markerInsideInner") is True
                and terminal.get("markerVisible") is True
                and terminal.get("markerTextExact") is True
                and terminal.get("markerControls") == 0
                and terminal.get("riskyActionCount") == 0
                and isinstance(modules, Mapping)
                and set(modules) == {"review", "coupon", "author", "i2i"}
                and all(type(modules.get(name)) is int and modules.get(name) == 1 for name in modules)
                and type(terminal.get("lotteryButtonCount")) is int
                and type(terminal.get("headerRootCount")) is int
                and type(terminal.get("headerBarCount")) is int
                and type(terminal.get("headerMenuCount")) is int
                and terminal.get("lotteryButtonCount") == 1
                and terminal.get("headerRootCount") == 1
                and terminal.get("headerBarCount") == 1
                and terminal.get("headerMenuCount") == 1
                and isinstance(headers, Mapping)
                and set(headers) == {"close-button", "contents-button", "settings-button"}
                and all(type(headers.get(name)) is int and headers.get(name) == 1 for name in headers)
                and partition.get("review") == 1
                and partition.get("coupon") == 1
                and partition.get("lottery") == 1
                and partition.get("header") == 3
                and partition.get("recommendAuthor", 0) >= 1
                and partition.get("recommendI2i", 0) >= 1
                and set(partition).issubset(
                    {"review", "coupon", "lottery", "header", "recommendAuthor", "recommendI2i"}
                )
            )
        if profile == "muda-book-last":
            modules = terminal.get("moduleCounts")
            headers = terminal.get("headerCounts")
            required_modules = {
                "review", "nextItem", "cta", "banner", "i2i", "author", "forYou"
            }
            required_headers = {"close-button", "contents-button", "settings-button"}
            return (
                isinstance(modules, Mapping)
                and set(modules) == required_modules
                and all(modules.get(name) == 1 for name in required_modules)
                and terminal.get("moduleChildCount") == 7
                and isinstance(headers, Mapping)
                and set(headers) == required_headers
                and all(headers.get(name) == 1 for name in required_headers)
                and terminal.get("moduleChildCount") == 7
                and terminal.get("headerBarCount") == 1
                and terminal.get("headerMenuCount") == 1
                and terminal.get("riskyActionCount") == 0
                and partition.get("review") == 1
                and partition.get("nextItem") == 1
                and partition.get("cta") == 1
                and partition.get("banner") == 2
                and partition.get("header") == 3
                and set(partition).issubset(required_modules | {"header"})
            )
        return False

    async def _ensure_native_css_viewport(
        self, page: Page, *, expected_path: str, current: int, total: int
    ) -> Mapping[str, object]:
        """Fit only the owned Page to its observed native canvas pixel geometry."""

        frame = await self._wait_for_content_frame(
            page,
            expected_path=expected_path,
            expected_current=current,
            expected_total=total,
        )
        parts = frame.get("parts")
        if not isinstance(parts, list) or not 1 <= len(parts) <= 2:
            raise UnknownPageStateError("ebookjapan Reader does not expose the observed one/two-part layout")
        dimensions: list[tuple[int, int]] = []
        for part in parts:
            if not isinstance(part, Mapping):
                raise UnknownPageStateError("ebookjapan Reader canvas geometry is malformed")
            width, height = part.get("backingWidth"), part.get("backingHeight")
            if type(width) is not int or type(height) is not int or width < 2 or height < 100 or width * height > MAX_PART_PIXELS:
                raise UnknownPageStateError("ebookjapan Reader canvas exceeds its observed size bounds")
            dimensions.append((width, height))
        target_viewport = (
            sum(width for width, _height in dimensions) if len(dimensions) == 2 else dimensions[0][0] * 2,
            max(height for _width, height in dimensions),
        )
        if target_viewport[0] < 1 or target_viewport[1] < 1 or target_viewport[0] > 4096 or target_viewport[1] > 4096:
            raise UnknownPageStateError("ebookjapan native CSS viewport exceeds its safe bounds")
        current_viewport = await page.evaluate("() => ({width:innerWidth,height:innerHeight})")
        if not isinstance(current_viewport, Mapping):
            raise UnknownPageStateError("ebookjapan Reader viewport is unavailable")
        if (
            current_viewport.get("width") == target_viewport[0]
            and current_viewport.get("height") == target_viewport[1]
            and self._parts_are_css_native(parts)
        ):
            self._capture_viewport = target_viewport
            return frame

        before_key = self._frame_nodes_key(frame)
        before_backing = self._frame_slot_backing_signature(frame)
        before_transfer = self._frame_transfer_signature(frame)
        if any(
            not isinstance(part, Mapping)
            or part.get("drawReady") is not True
            or part.get("resetObserved") is not False
            or part.get("observerOverflow") is not False
            for part in parts
        ):
            raise UnknownPageStateError("ebookjapan pre-fit frame lacks complete natural draw evidence")
        before_counter = frame.get("counter") if frame.get("counterVisible") is True else None
        before_title = frame.get("title")
        await page.set_viewport_size({"width": target_viewport[0], "height": target_viewport[1]})
        deadline = time.monotonic() + _FRAME_READY_WAIT_MS / 1000
        last_fit_signature: tuple[object, ...] | None = None
        stable_fit_samples = 0
        while time.monotonic() < deadline:
            next_frame = await page.evaluate(FRAME_STATE_JS, {"expectedCurrent": current})
            if not isinstance(next_frame, Mapping):
                raise UnknownPageStateError("ebookjapan resized frame state is malformed")
            status = next_frame.get("status")
            if status in {"identity-mismatch", "slot-order-mismatch", "layout-mismatch", "observer-unavailable", "observer-overflow", "observer-metadata-failure", "counter-total-mismatch", "end"}:
                raise UnknownPageStateError(f"ebookjapan Reader changed identity during viewport fit ({status})")
            if status == "content":
                next_parts = next_frame.get("parts")
                if (
                    not isinstance(next_parts, list)
                    or self._frame_nodes_key(next_frame) != before_key
                    or self._frame_slot_backing_signature(next_frame) != before_backing
                ):
                    raise UnknownPageStateError("ebookjapan selected canvas nodes changed during viewport fit")
                next_counter = next_frame.get("counter") if next_frame.get("counterVisible") is True else None
                next_title = next_frame.get("title")
                if before_counter != next_counter or before_title != next_title:
                    raise UnknownPageStateError("ebookjapan Reader identity changed during viewport fit")
                viewport_after = next_frame.get("viewport")
                if not isinstance(viewport_after, Mapping) or (
                    viewport_after.get("width"), viewport_after.get("height")
                ) != target_viewport:
                    raise UnknownPageStateError("ebookjapan Reader did not retain its fitted viewport")
                if self._parts_are_css_native(next_parts):
                    next_transfer = self._frame_transfer_signature(next_frame)
                    unchanged_full_draw = (
                        next_transfer == before_transfer
                        and all(
                            isinstance(part, Mapping)
                            and part.get("drawReady") is True
                            and part.get("resetObserved") is False
                            and part.get("observerOverflow") is False
                            for part in next_parts
                        )
                    )
                    redrawn_full_frame = all(
                        isinstance(before_part, Mapping)
                        and isinstance(next_part, Mapping)
                        and type(before_part.get("drawGeneration")) is int
                        and type(before_part.get("successfulDraws")) is int
                        and type(next_part.get("drawGeneration")) is int
                        and type(next_part.get("successfulDraws")) is int
                        # drawGeneration is reset when the canvas backing store
                        # is resized. successfulDraws is cumulative, so it is
                        # the monotonic witness for a fresh complete paint.
                        and next_part.get("drawGeneration") > 0
                        and next_part.get("successfulDraws") > before_part.get("successfulDraws")
                        and next_part.get("drawReady") is True
                        and next_part.get("resetObserved") is False
                        and next_part.get("observerOverflow") is False
                        for before_part, next_part in zip(parts, next_parts, strict=True)
                    )
                    if unchanged_full_draw or redrawn_full_frame:
                        fit_signature = self._frame_paint_signature(next_frame)
                        if fit_signature == last_fit_signature:
                            stable_fit_samples += 1
                        else:
                            last_fit_signature = fit_signature
                            stable_fit_samples = 1
                        # Resize-triggered natural draws can be queued after
                        # the first valid geometry sample. Require the pinned,
                        # complete frame signature to survive two animation
                        # frames before capture starts.
                        if stable_fit_samples >= 2:
                            self._capture_viewport = target_viewport
                            return next_frame
                        await page.evaluate(
                            "() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
                        )
                        continue
                    last_fit_signature = None
                    stable_fit_samples = 0
                else:
                    last_fit_signature = None
                    stable_fit_samples = 0
            elif status not in {"partial", "loading"}:
                raise UnknownPageStateError("ebookjapan Reader resize entered an unsupported state")
            else:
                last_fit_signature = None
                stable_fit_samples = 0
            await page.wait_for_timeout(_FRAME_POLL_MS)
        raise UnknownPageStateError("ebookjapan canvas did not redraw at its native CSS viewport") from None

    @staticmethod
    def _parts_are_css_native(parts: list[object]) -> bool:
        for part in parts:
            if not isinstance(part, Mapping):
                return False
            rect = part.get("cssRect")
            if not isinstance(rect, Mapping):
                return False
            width, height = part.get("backingWidth"), part.get("backingHeight")
            if (
                type(width) is not int
                or type(height) is not int
                or abs(float(rect.get("width", -10_000)) - width) > 1
                or abs(float(rect.get("height", -10_000)) - height) > 1
            ):
                return False
        return True

    async def _pin_reader_anchor(
        self,
        page: Page,
        *,
        expected_path: str,
        expected_current: int,
        expected_total: int,
    ) -> None:
        deadline = time.monotonic() + _FRAME_READY_WAIT_MS / 1000
        last: Mapping[str, object] | None = None
        while time.monotonic() < deadline:
            anchor = await page.evaluate(
                ANCHOR_READER_JS,
                {
                    "expectedTitle": self._owned_title,
                    "expectedPath": expected_path,
                    "maxSlots": MAX_SLOTS,
                },
            )
            if not isinstance(anchor, Mapping):
                raise UnknownPageStateError("ebookjapan Reader anchor state is malformed")
            last = anchor
            if anchor.get("ok") is True:
                if (
                    anchor.get("current") != expected_current
                    or anchor.get("total") != expected_total
                    or anchor.get("slotCount") != expected_total
                ):
                    raise UnknownPageStateError("ebookjapan Reader identity changed while pinning its slots")
                return
            if anchor.get("route") is False or anchor.get("titleMatches") is False:
                raise UnknownPageStateError("ebookjapan Reader route or title differs from the owned card")
            if anchor.get("total") not in (None, expected_total):
                raise UnknownPageStateError("ebookjapan Reader native total differs from the owned book")
            await page.wait_for_timeout(_FRAME_POLL_MS)
        del last
        raise UnknownPageStateError(
            "ebookjapan Reader could not pin its complete native slot inventory within the bounded wait"
        ) from None

    async def _rewind_to_first(self, page: Page, *, expected_path: str) -> None:
        current, total = await self._require_reader_content(page, expected_path=expected_path)
        range_control = page.locator(_RANGE_SELECTOR)
        if await range_control.count() != 1:
            raise UnknownPageStateError("ebookjapan observed native Reader range is missing or ambiguous")
        range_state = await range_control.evaluate(
            "el=>({tag:el.tagName,type:el.type,min:Number(el.min),max:Number(el.max),value:Number(el.value),disabled:el.disabled})"
        )
        if (
            range_state.get("tag") != "INPUT"
            or range_state.get("type") != "range"
            or range_state.get("min") != 0
            or range_state.get("max") != total - 1
            or range_state.get("disabled") is not False
            or not await range_control.is_visible()
            or not await range_control.is_enabled()
        ):
            raise UnknownPageStateError("ebookjapan native range differs from the observed Reader control")
        if current != 1:
            await range_control.focus()
            await range_control.press("End", timeout=_READER_NAVIGATION_WAIT_MS)
            await page.wait_for_function(
                """({path,total})=>{
                  const title=document.querySelector('.legacy-comic-header__title'),counter=document.querySelector('.legacy-comic-footer__page-output');
                  const m=(counter?.innerText||counter?.textContent||'').trim().match(/^(\\d+)\\s*\\/\\s*(\\d+)$/);
                  return location.hostname==='ebookjapan.yahoo.co.jp'&&location.pathname===path&&!location.search&&!location.hash
                    &&title&&counter&&m&&Number(m[1])===1&&Number(m[2])===total;
                }""",
                arg={"path": expected_path, "total": total},
                timeout=_READER_NAVIGATION_WAIT_MS,
            )
        await self._wait_for_content_frame(
            page,
            expected_path=expected_path,
            expected_current=1,
            expected_total=total,
        )

    async def initialize(self, page: Page) -> None:
        if self._access_strategy != "direct":
            raise UnsupportedAccessStrategyError(
                "ebookjapan Reader requires direct owned access"
            )
        target_path = await self._preflight_owned_card(page)
        series_id, external_id = self._series_id, self._external_id
        assert series_id is not None and external_id is not None
        card = page.locator(".book-list__item").filter(
            has=page.locator(f'a.book-item[href="{target_path}"]')
        )
        action = card.locator("button.icon-btn-wrapper__btn.icon-btn")
        await self._recheck_target_before_click(
            page, target_path=target_path, card=card, action=action
        )
        self._page = page
        await action.click(timeout=_READER_NAVIGATION_WAIT_MS)
        await page.wait_for_function(
            """() => location.hostname==='ebookjapan.yahoo.co.jp'&&
              /^\\/viewer\\/purchased\\/B[0-9]+\\/$/.test(location.pathname)&&!location.search&&!location.hash""",
            timeout=_READER_ROUTE_WAIT_MS,
        )
        reader_url = urlsplit(page.url)
        if (
            reader_url.scheme != "https"
            or reader_url.hostname != SITE_HOST
            or reader_url.query
            or reader_url.fragment
            or _PURCHASED_READER_PATH.fullmatch(reader_url.path) is None
        ):
            raise UnknownPageStateError("ebookjapan owned Reader action did not open an exact purchased route")
        self._reader_path = reader_url.path
        await self._dismiss_known_intro(page)
        state = await self._reader_controls(page, expected_path=self._reader_path)
        title = state.get("title")
        # The toolbar may intentionally hide the header. Preserve the exact
        # route and fail as UNKNOWN until the observed native identity is visible.
        if title is None:
            raise UnknownPageStateError("ebookjapan Reader title is hidden or unavailable after entry")
        if normalize_title(str(title)) != normalize_title(self._owned_title or ""):
            raise UnknownPageStateError("ebookjapan purchased Reader title differs from its owned card")
        counter = state.get("counter")
        if not isinstance(counter, Mapping):
            raise UnknownPageStateError("ebookjapan Reader native page counter is unavailable")
        current, total = counter.get("current"), counter.get("total")
        if type(current) is not int or type(total) is not int or current < 1 or total < current:
            raise UnknownPageStateError("ebookjapan Reader native page counter is malformed")
        self._reader_entry_counter = (current, total)
        if state.get("horizontalRtl") is not True or state.get("spread") is not True:
            raise UnknownPageStateError("ebookjapan Reader layout is not the observed horizontal RTL spread")
        if state.get("slotCount") != total:
            raise UnknownPageStateError("ebookjapan native page total differs from the complete slot inventory")
        self._reader_total = total
        # Pin the same route/document, normalized title, all actual slot node
        # references/order, native total, and observed spread layout before any
        # page navigation. Then use the observed native End control to rewind.
        await self._pin_reader_anchor(
            page,
            expected_path=self._reader_path,
            expected_current=current,
            expected_total=total,
        )
        if current != 1:
            # Entry slider is an observed normal control; validate it and the
            # visible Reader content again before sending End.
            await self._wait_for_content_frame(
                page,
                expected_path=self._reader_path,
                expected_current=current,
                expected_total=total,
            )
            if state.get("visibleEnd") is True:
                raise UnknownPageStateError("ebookjapan Reader is at END; normal rewind is unsafe")
            await self._rewind_to_first(page, expected_path=self._reader_path)
        else:
            await self._wait_for_content_frame(
                page,
                expected_path=self._reader_path,
                expected_current=1,
                expected_total=total,
            )
        self._last_native_counter = 1
        self._expected_current = 1
        self._reader_path = reader_url.path

    async def detect_state(self, page: Page) -> PageState:
        reader_path, total = self._reader_path, self._reader_total
        if reader_path is None or total is None or page is not self._page:
            raise UnknownPageStateError("ebookjapan Reader state is not initialized on this Page")
        controls = await self._reader_controls(page, expected_path=reader_path)
        if controls.get("documentMatches") is not True or controls.get("layoutMatchesAnchor") is not True:
            raise UnknownPageStateError("ebookjapan Reader document or layout anchor changed")
        title = controls.get("title")
        if title is not None and normalize_title(str(title)) != normalize_title(self._owned_title or ""):
            raise UnknownPageStateError("ebookjapan Reader title differs from its owned card")
        frame = await page.evaluate(
            FRAME_STATE_JS, {"expectedCurrent": self._expected_current}
        )
        if not isinstance(frame, Mapping):
            raise UnknownPageStateError("ebookjapan Reader state frame is malformed")
        status = frame.get("status")
        if status == "end":
            if self._capture_coverage_complete() and self._is_verified_end_frame(frame, total=total):
                self._terminal_end_verified = True
                self._last_native_counter = None
                return PageState.END
            raise UnknownPageStateError(
                "ebookjapan displayed END before complete ordered page-slot coverage"
            )
        if status in {"partial", "loading"}:
            return PageState.LOADING
        if status != "content":
            raise UnknownPageStateError(f"ebookjapan Reader state is unsupported ({status})")
        if self._terminal_end_verified:
            raise UnknownPageStateError("ebookjapan Reader changed after verified END")
        ready = await self._read_ready_frame(
            page,
            expected_path=reader_path,
            current=self._expected_current,
            total=total,
        )
        self._last_native_counter = self._native_counter(ready)
        ids = self._visible_slot_ids(ready)
        if self._seen_slot_ids.intersection(ids):
            raise UnknownPageStateError("ebookjapan Reader returned to an already captured slot")
        return PageState.CONTENT

    async def get_capture_target(self, page: Page):
        del page
        raise UnknownPageStateError("ebookjapan unverified D capture is disabled")

    async def get_capture_targets(self, page: Page):
        del page
        raise UnknownPageStateError("ebookjapan unverified D capture is disabled")

    async def capture_page(self, page: Page) -> tuple[CaptureResult, ...] | None:
        reader_path = self._reader_path
        total = self._reader_total
        current = self._expected_current
        if reader_path is None or total is None:
            raise UnknownPageStateError("ebookjapan pinned Reader is not initialized")
        before = await self._read_ready_frame(page, expected_path=reader_path, current=current, total=total)
        native_counter_for_capture = self._native_counter(before)
        self._last_native_counter = native_counter_for_capture
        identity_key = self._frame_nodes_key(before)
        if self._pending_identity_key is None or identity_key != self._pending_identity_key:
            raise UnknownPageStateError("ebookjapan visible page changed after identity was read")
        before = await self._hide_toolbar_for_capture(
            page, frame=before, expected_path=reader_path, current=current, total=total
        )
        before = await self._ensure_native_css_viewport(
            page, expected_path=reader_path, current=current, total=total
        )
        self._last_native_counter = self._native_counter(before)
        if self._frame_nodes_key(before) != identity_key:
            raise UnknownPageStateError("ebookjapan selected page nodes changed during compositor setup")
        self._require_safe_capture_surface(before)
        parts = before.get("parts")
        if not isinstance(parts, list) or not parts:
            raise UnknownPageStateError("ebookjapan has no complete visible page parts to capture")
        ids, ordinals = self._validate_capture_sequence(parts, current=current)
        frame_signature = self._frame_paint_signature(before)
        first_pngs: list[tuple[bytes, int, int, str]] = []
        for part in parts:
            if not isinstance(part, Mapping):
                raise UnknownPageStateError("ebookjapan visible page part is malformed")
            width, height = part.get("backingWidth"), part.get("backingHeight")
            if type(width) is not int or type(height) is not int or width * height > MAX_PART_PIXELS:
                raise UnknownPageStateError("ebookjapan part exceeds the verified D pixel limit")
            locator = await self._pinned_canvas_locator(page, part)
            if not await locator.is_visible():
                raise UnknownPageStateError("ebookjapan selected canvas is no longer visible")
            current_frame = await self._read_ready_frame(
                page, expected_path=reader_path, current=current, total=total
            )
            if (
                self._frame_paint_signature(current_frame) != frame_signature
                or self._frame_nodes_key(current_frame) != identity_key
            ):
                raise UnknownPageStateError("ebookjapan frame changed before a D compositor sample")
            self._require_safe_capture_surface(current_frame)
            png = await locator.screenshot(animations="disabled", scale="css")
            pixel_hash, png_width, png_height = self._decode_png(png)
            if (png_width, png_height) != (width, height):
                raise UnknownPageStateError("ebookjapan compositor PNG does not match native canvas dimensions")
            first_pngs.append((png, png_width, png_height, pixel_hash))

        await page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
        middle = await self._read_ready_frame(page, expected_path=reader_path, current=current, total=total)
        if self._frame_paint_signature(middle) != frame_signature:
            raise UnknownPageStateError("ebookjapan frame or native draw generation changed during D capture")
        self._require_safe_capture_surface(middle)

        second_pngs: list[tuple[bytes, int, int, str]] = []
        for part in parts:
            assert isinstance(part, Mapping)
            current_frame = await self._read_ready_frame(
                page, expected_path=reader_path, current=current, total=total
            )
            if (
                self._frame_paint_signature(current_frame) != frame_signature
                or self._frame_nodes_key(current_frame) != identity_key
            ):
                raise UnknownPageStateError("ebookjapan frame changed before the repeated D sample")
            self._require_safe_capture_surface(current_frame)
            locator = await self._pinned_canvas_locator(page, part)
            png = await locator.screenshot(animations="disabled", scale="css")
            pixel_hash, png_width, png_height = self._decode_png(png)
            if (png_width, png_height) != (part.get("backingWidth"), part.get("backingHeight")):
                raise UnknownPageStateError("ebookjapan repeated compositor PNG has unexpected dimensions")
            second_pngs.append((png, png_width, png_height, pixel_hash))
        await page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
        after = await self._read_ready_frame(page, expected_path=reader_path, current=current, total=total)
        if self._frame_paint_signature(after) != frame_signature:
            raise UnknownPageStateError("ebookjapan frame changed after the second D compositor sample")
        self._require_safe_capture_surface(after)
        if len(first_pngs) != len(second_pngs) or any(
            first[1:] != second[1:] for first, second in zip(first_pngs, second_pngs, strict=True)
        ):
            raise UnknownPageStateError("ebookjapan D compositor pixels were not stable across two frames")

        captures = tuple(
            CaptureResult(data=first[0], width=first[1], height=first[2])
            for first in first_pngs
        )
        cached_parts: list[dict[str, object]] = []
        for index, (part, first) in enumerate(zip(parts, first_pngs, strict=True)):
            assert isinstance(part, Mapping)
            cached_parts.append({
                "slot_id": part.get("slotId"),
                "slot_ordinal": part.get("slotOrdinal"),
                "canvas_id": part.get("canvasId"),
                "canvas_index": part.get("canvasIndex"),
                "side": "single" if len(parts) == 1 else ("right" if index == 0 else "left"),
                "derived_sequence": len(self._captured_slot_order) + index + 1,
                "native_page_number": None,
                "native_counter": native_counter_for_capture,
                "derived_frame_shape": "cover" if current == 1 else "spread",
                "width": first[1],
                "height": first[2],
                "css_rect": dict(part["cssRect"]) if isinstance(part.get("cssRect"), Mapping) else None,
                "draw_generation": part.get("drawGeneration"),
                "successful_draws": part.get("successfulDraws"),
                "mutation_count": part.get("mutationCount"),
                "clip_calls": part.get("clipCalls"),
                "last_full_draw": part.get("lastFullDraw"),
                "reset_observed": part.get("resetObserved"),
                "context_is_2d": part.get("contextIs2d"),
                "observer_overflow": part.get("observerOverflow"),
                "draw_ready": part.get("drawReady"),
                "draw_geometry": dict(part["drawGeometry"]) if isinstance(part.get("drawGeometry"), Mapping) else None,
                "compositor_pixel_sha256": first[3],
                "capture_method": "D_compositor_png",
                "capture_class": _CAPTURE_CLASS,
                "fallback_reason_code": _FALLBACK_REASON_CODE,
                "ebookjapan_capture_policy_revision": _CAPTURE_POLICY_REVISION,
                "source_provenance": "UNKNOWN",
            })
        # Commit sequence coverage only after every part passed route, node,
        # geometry, natural draw, decode, and repeated-pixel checks.
        self._seen_slot_ids.update(ids)
        self._captured_slot_order.extend(ids)
        self._last_capture_parts = tuple(cached_parts)
        self._last_capture_node_key = identity_key
        self._last_capture_paint_signature = frame_signature
        self._last_capture_ids = tuple(ids)
        self._last_capture_ordinals = tuple(ordinals)
        self._last_capture_part_count = len(parts)
        self._last_capture_page_id = self._pending_page_id
        self._pending_page_id = None
        self._transition_pending = False
        self._terminal_end_verified = False
        if self._next_dom_ordinal is None:
            self._next_dom_ordinal = ordinals[-1] - 1
        else:
            self._next_dom_ordinal = ordinals[-1] - 1
        self._pending_identity_key = None
        return captures

    async def _hide_toolbar_for_capture(
        self,
        page: Page,
        *,
        frame: Mapping[str, object],
        expected_path: str,
        current: int,
        total: int,
    ) -> Mapping[str, object]:
        if frame.get("toolbarVisible") is False:
            return frame
        if frame.get("toolbarVisible") is not True:
            raise UnknownPageStateError("ebookjapan Reader toolbar visibility is unknown")
        await self._require_reader_content(page, expected_path=expected_path)
        profile = self._observed_toolbar_hide_geometry_profile(frame)
        if profile is None:
            raise UnknownPageStateError(
                "ebookjapan center toolbar action is unverified at this viewport geometry"
            )
        _profile_name, expected_backing, expected_rect = profile
        parts = frame.get("parts")
        if not isinstance(parts, list) or not parts or not isinstance(parts[0], Mapping):
            raise UnknownPageStateError("ebookjapan cannot locate a safe normal toolbar control area")
        part = parts[0]
        locator = await self._pinned_canvas_locator(page, part)
        geometry = await locator.evaluate(
            """canvas=>{
              const r=canvas.getBoundingClientRect(),x=r.left+r.width/2,y=r.top+r.height/2;
              const hit=document.elementFromPoint(x,y);
              return {connected:canvas.isConnected,viewport:{width:innerWidth,height:innerHeight},
                backing:{width:canvas.width,height:canvas.height},
                rect:{left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height},
                center:{x,y},hit:hit===canvas||canvas.contains(hit)};
            }"""
        )
        if not isinstance(geometry, Mapping) or geometry.get("connected") is not True:
            raise UnknownPageStateError("ebookjapan selected page bounds are unavailable")
        live_viewport = geometry.get("viewport")
        live_backing = geometry.get("backing")
        rect = geometry.get("rect")
        center = geometry.get("center")
        if (
            not isinstance(live_viewport, Mapping)
            or (live_viewport.get("width"), live_viewport.get("height"))
            != _OBSERVED_CENTER_ACTION_VIEWPORT
            or not isinstance(live_backing, Mapping)
            or (live_backing.get("width"), live_backing.get("height")) != expected_backing
            or not isinstance(rect, Mapping)
            or any(
                type(value) not in (int, float)
                or abs(float(value) - expected) > _OBSERVED_CENTER_ACTION_RECT_TOLERANCE
                for value, expected in zip(
                    (rect.get(key) for key in ("left", "right", "top", "bottom", "width", "height")),
                    expected_rect,
                    strict=True,
                )
            )
            or not isinstance(center, Mapping)
            or type(center.get("x")) not in (int, float)
            or type(center.get("y")) not in (int, float)
            or geometry.get("hit") is not True
        ):
            raise UnknownPageStateError(
                "ebookjapan toolbar action bounds changed after the verified frame sample"
            )
        x, y = float(center["x"]), float(center["y"])
        identity_key = self._frame_nodes_key(frame)
        paint_signature = self._frame_paint_signature(frame)
        native_counter_before = self._native_counter(frame)
        await asyncio.wait_for(
            page.mouse.click(x, y),
            timeout=_READER_NAVIGATION_WAIT_MS / 1000,
        )
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            changed = await page.evaluate(FRAME_STATE_JS, {"expectedCurrent": current})
            if not isinstance(changed, Mapping):
                raise UnknownPageStateError("ebookjapan toolbar state after center action is malformed")
            if changed.get("status") in {
                "identity-mismatch", "slot-order-mismatch", "layout-mismatch",
                "observer-unavailable", "observer-overflow", "observer-metadata-failure",
                "counter-total-mismatch", "end",
            }:
                raise UnknownPageStateError("ebookjapan center action changed the pinned Reader state")
            if changed.get("status") == "content":
                if (
                    changed.get("toolbarVisible") is False
                    and self._frame_nodes_key(changed) == identity_key
                    and self._frame_paint_signature(changed) == paint_signature
                    and self._reader_path == expected_path
                ):
                    counter = changed.get("counter")
                    if changed.get("counterVisible") is True and (
                        not isinstance(counter, Mapping)
                        or counter.get("total") != total
                        or (native_counter_before is not None and counter.get("current") != native_counter_before)
                        or (native_counter_before is None and (
                            (current == 1 and counter.get("current") != 1)
                            or (current != 1 and (type(counter.get("current")) is not int or counter.get("current") < 2))
                        ))
                    ):
                        raise UnknownPageStateError("ebookjapan center action changed the native page counter")
                    self._require_safe_capture_surface(changed)
                    return changed
                if changed.get("toolbarVisible") is True:
                    raise UnknownPageStateError("ebookjapan observed center action did not hide the Reader toolbar")
            elif changed.get("status") not in {"partial", "loading"}:
                raise UnknownPageStateError("ebookjapan center action entered an unsupported state")
            await page.wait_for_timeout(_FRAME_POLL_MS)
        raise UnknownPageStateError("ebookjapan toolbar did not hide within the bounded center action wait") from None

    @staticmethod
    def _has_observed_toolbar_hide_geometry(frame: Mapping[str, object]) -> bool:
        return EbookJapanAdapter._observed_toolbar_hide_geometry_profile(frame) is not None

    @staticmethod
    def _observed_toolbar_hide_geometry_profile(
        frame: Mapping[str, object],
    ) -> tuple[str, tuple[int, int], tuple[float, float, float, float, float, float]] | None:
        viewport = frame.get("viewport")
        parts = frame.get("parts")
        if (
            not isinstance(viewport, Mapping)
            or (viewport.get("width"), viewport.get("height")) != _OBSERVED_CENTER_ACTION_VIEWPORT
            or not isinstance(parts, list)
            or len(parts) != 1
            or not isinstance(parts[0], Mapping)
        ):
            return None
        part = parts[0]
        backing_width, backing_height = part.get("backingWidth"), part.get("backingHeight")
        rect = part.get("cssRect")
        if (
            type(backing_width) is not int
            or type(backing_height) is not int
            or not isinstance(rect, Mapping)
            or rect.get("viewport") is not True
        ):
            return None
        backing = (backing_width, backing_height)
        observed = tuple(
            rect.get(key)
            for key in ("left", "right", "top", "bottom", "width", "height")
        )
        matches = [
            profile
            for profile in _OBSERVED_CENTER_ACTION_PROFILES
            if profile[1] == backing
            and all(
                type(value) in (int, float)
                and abs(float(value) - expected) <= _OBSERVED_CENTER_ACTION_RECT_TOLERANCE
                for value, expected in zip(observed, profile[2], strict=True)
            )
        ]
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _require_safe_capture_surface(frame: Mapping[str, object]) -> None:
        if frame.get("toolbarVisible") is not False:
            raise UnknownPageStateError("ebookjapan Reader chrome is visible during D capture")
        parts = frame.get("parts")
        if not isinstance(parts, list) or not parts:
            raise UnknownPageStateError("ebookjapan D capture has no verified page surface")
        unsafe = [
            str(part.get("captureSurfaceReason") or "unknown")
            if isinstance(part, Mapping)
            else "malformed"
            for part in parts
            if not isinstance(part, Mapping) or part.get("captureSurfaceSafe") is not True
        ]
        if unsafe:
            raise UnknownPageStateError(
                "ebookjapan D canvas surface is unsafe (" + ",".join(sorted(set(unsafe))) + ")"
            )

    async def get_content_identity(self, page: Page) -> ContentIdentity:
        if self._reader_path is None or self._reader_total is None or self._external_id is None:
            raise UnknownPageStateError("ebookjapan Reader identity is not initialized")
        current = self._expected_current
        frame = await self._read_ready_frame(
            page,
            expected_path=self._reader_path,
            current=current,
            total=self._reader_total,
        )
        parts = frame.get("parts")
        if not isinstance(parts, list) or not parts:
            raise UnknownPageStateError("ebookjapan frame has no page-slot identity")
        self._last_native_counter = self._native_counter(frame)
        ids = [part.get("slotId") for part in parts if isinstance(part, Mapping)]
        if len(ids) != len(parts) or any(type(value) is not int for value in ids) or len(set(ids)) != len(ids):
            raise UnknownPageStateError("ebookjapan frame has missing or duplicate slot identities")
        if self._seen_slot_ids.intersection(ids):
            raise UnknownPageStateError("ebookjapan reader revisited an already captured page slot")
        self._pending_identity_key = self._frame_nodes_key(frame)
        page_id = f"{self._series_id}/{self._external_id}/slots:{','.join(str(value) for value in ids)}"
        self._pending_page_id = page_id
        return ContentIdentity(page_id=page_id, page_number=None, source_id=self._external_id)

    async def get_content_context(self, page: Page) -> ContentContext:
        del page
        if self._series_id is None or self._external_id is None or self._work_key is None:
            raise UnknownPageStateError("ebookjapan ContentContext is not initialized")
        return ContentContext(
            content_id=self._external_id,
            work_id=self._work_key,
            title=self._owned_title,
        )

    async def go_next(self, page: Page) -> None:
        reader_path, total = self._reader_path, self._reader_total
        if (
            reader_path is None
            or total is None
            or page is not self._page
            or self._terminal_end_verified
            or self._transition_pending
            or self._pending_identity_key is not None
            or self._last_capture_node_key is None
        ):
            raise UnknownPageStateError("ebookjapan normal advance is not ready for the captured frame")
        frame = await self._read_ready_frame(
            page,
            expected_path=reader_path,
            current=self._expected_current,
            total=total,
        )
        if self._frame_nodes_key(frame) != self._last_capture_node_key:
            raise UnknownPageStateError("ebookjapan page changed after its atomic capture")
        if tuple(self._visible_slot_ids(frame)) != self._last_capture_ids:
            raise UnknownPageStateError("ebookjapan captured slot order changed before normal advance")
        if (
            self._last_capture_paint_signature is None
            or self._frame_paint_signature(frame) != self._last_capture_paint_signature
        ):
            raise UnknownPageStateError(
                "ebookjapan captured paint and geometry state changed before normal advance"
            )
        controls = await self._reader_controls(page, expected_path=reader_path)
        if controls.get("visibleEnd") is True:
            raise UnknownPageStateError("ebookjapan is already showing an END control before normal advance")
        target = await page.evaluate(
            NAVIGATION_TARGET_JS,
            {
                "x": 12,
                "capturedParts": [
                    {
                        "slotId": part.get("slot_id"),
                        "slotOrdinal": part.get("slot_ordinal"),
                        "canvasId": part.get("canvas_id"),
                        "canvasIndex": part.get("canvas_index"),
                        "backingWidth": part.get("width"),
                        "backingHeight": part.get("height"),
                        "cssRect": part.get("css_rect"),
                        "drawGeneration": part.get("draw_generation"),
                        "successfulDraws": part.get("successful_draws"),
                        "mutationCount": part.get("mutation_count"),
                        "clipCalls": part.get("clip_calls"),
                        "lastFullDraw": part.get("last_full_draw"),
                        "resetObserved": part.get("reset_observed"),
                        "contextIs2d": part.get("context_is_2d"),
                        "observerOverflow": part.get("observer_overflow"),
                        "drawReady": part.get("draw_ready"),
                        "drawGeometry": part.get("draw_geometry"),
                    }
                    for part in self._last_capture_parts
                ],
            },
        )
        if (
            not isinstance(target, Mapping)
            or target.get("safe") is not True
            or target.get("slotsPinned") is not True
            or target.get("capturedPartsMatch") is not True
            or target.get("inPinnedSlot") is not True
            or target.get("insideSlot") is not True
            or target.get("interactive") is not False
            or target.get("blocked") is not False
            or target.get("modalVisible") is not False
            or type(target.get("x")) is not int
                or target.get("x") != 12
            or type(target.get("y")) is not int
                or not isinstance(target.get("viewport"), Mapping)
                or target.get("y") != target["viewport"].get("height", -1) // 2
        ):
            raise UnknownPageStateError(
                "ebookjapan normal advance hit is not bound to the captured pinned page slot"
            )
        self._transition_before_key = self._last_capture_node_key
        self._transition_pending = True
        self._terminal_end_verified = False
        # After the cover, the observed viewer displays a spread. Keep this as
        # a shape expectation only; it is not a native page counter.
        self._expected_current = 2
        self._last_native_counter = None
        await asyncio.wait_for(
            page.mouse.click(target["x"], target["y"]),
            timeout=_READER_NAVIGATION_WAIT_MS / 1000,
        )

    async def wait_for_change(
        self, page: Page, previous_identity: ContentIdentity | None
    ) -> None:
        reader_path, total = self._reader_path, self._reader_total
        if (
            reader_path is None
            or total is None
            or page is not self._page
            or self._terminal_end_verified
            or not self._transition_pending
            or self._transition_before_key is None
            or previous_identity is None
            or previous_identity.page_id != self._last_capture_page_id
        ):
            raise UnknownPageStateError("ebookjapan page-change wait is not bound to the last captured frame")
        deadline = time.monotonic() + _FRAME_READY_WAIT_MS / 1000
        while time.monotonic() < deadline:
            frame = await page.evaluate(
                FRAME_STATE_JS, {"expectedCurrent": self._expected_current}
            )
            if not isinstance(frame, Mapping):
                raise UnknownPageStateError("ebookjapan page-change state is malformed")
            status = frame.get("status")
            if status in {
                "identity-mismatch", "slot-order-mismatch", "layout-mismatch",
                "observer-unavailable", "observer-overflow", "observer-metadata-failure",
                "counter-total-mismatch", "unknown-terminal-marker",
            }:
                raise UnknownPageStateError(f"ebookjapan Reader changed identity during advance ({status})")
            if status == "end":
                if (
                    not self._capture_coverage_complete()
                    or not self._is_verified_end_frame(frame, total=total)
                ):
                    raise UnknownPageStateError(
                        "ebookjapan Reader reached an unverified END or terminal notice"
                    )
                self._transition_pending = False
                self._terminal_end_verified = True
                self._last_native_counter = None
                self._transition_before_key = None
                return
            if status == "content":
                key = self._frame_nodes_key(frame)
                if key == self._transition_before_key:
                    await page.wait_for_timeout(_FRAME_POLL_MS)
                    continue
                ready = await self._read_ready_frame(
                    page,
                    expected_path=reader_path,
                    current=self._expected_current,
                    total=total,
                )
                ids = self._visible_slot_ids(ready)
                if self._seen_slot_ids.intersection(ids):
                    raise UnknownPageStateError("ebookjapan normal advance revisited a captured slot")
                parts = ready.get("parts")
                if not isinstance(parts, list):
                    raise UnknownPageStateError("ebookjapan advanced frame has malformed parts")
                self._validate_capture_sequence(parts, current=self._expected_current)
                self._last_native_counter = self._native_counter(ready)
                self._transition_pending = False
                self._transition_before_key = None
                return
            if status not in {"partial", "loading"}:
                raise UnknownPageStateError(f"ebookjapan page-change state is unsupported ({status})")
            await page.wait_for_timeout(_FRAME_POLL_MS)
        raise UnknownPageStateError(
            "ebookjapan normal page advance did not produce a new full content frame"
        ) from None

    async def collect_debug_metadata(self, page: Page) -> dict[str, object]:
        del page
        return {
            "capture_method": "D_compositor_png",
            "capture_class": _CAPTURE_CLASS,
            "fallback_reason_code": _FALLBACK_REASON_CODE,
            "ebookjapan_capture_policy_revision": _CAPTURE_POLICY_REVISION,
            "ebookjapan_capture_parts": [dict(part) for part in self._last_capture_parts],
            "ebookjapan_native_counter": self._last_native_counter,
            "ebookjapan_derived_frame_shape": "cover" if self._expected_current == 1 else "spread",
            "ebookjapan_native_page_number": None,
            "ebookjapan_source_provenance": "UNKNOWN",
        }

    async def _read_ready_frame(
        self,
        page: Page,
        *,
        expected_path: str,
        current: int,
        total: int,
    ) -> Mapping[str, object]:
        controls = await self._reader_controls(page, expected_path=expected_path)
        if controls.get("documentMatches") is not True or controls.get("layoutMatchesAnchor") is not True:
            raise UnknownPageStateError("ebookjapan Reader document or layout anchor changed")
        title = controls.get("title")
        if title is not None and normalize_title(str(title)) != normalize_title(self._owned_title or ""):
            raise UnknownPageStateError("ebookjapan visible Reader title changed")
        control_counter = controls.get("counter")
        if isinstance(control_counter, Mapping) and control_counter.get("total") != total:
            raise UnknownPageStateError("ebookjapan native Reader total changed")
        frame = await self._wait_for_content_frame(
            page,
            expected_path=expected_path,
            expected_current=current,
            expected_total=total,
        )
        if frame.get("routeStable") is not True or frame.get("toolbarVisible") not in (True, False):
            raise UnknownPageStateError("ebookjapan frame identity is not stable")
        frame_counter = frame.get("counter")
        if isinstance(frame_counter, Mapping) and (
            frame_counter.get("total") != total
            or frame_counter.get("current") != current
        ):
            raise UnknownPageStateError("ebookjapan native page counter changed unexpectedly")
        return frame

    @staticmethod
    def _frame_paint_signature(frame: Mapping[str, object]) -> tuple[object, ...]:
        parts = frame.get("parts")
        if not isinstance(parts, list):
            raise UnknownPageStateError("ebookjapan paint frame is malformed")
        signature: list[object] = []
        for part in parts:
            if not isinstance(part, Mapping):
                raise UnknownPageStateError("ebookjapan paint part is malformed")
            rect = part.get("cssRect")
            draw_geometry = part.get("drawGeometry")
            geometry_signature = (
                tuple(
                    (key, tuple(value) if isinstance(value, list) else value)
                    for key, value in sorted(draw_geometry.items())
                )
                if isinstance(draw_geometry, Mapping)
                else None
            )
            signature.extend((
                part.get("slotId"),
                part.get("canvasId"),
                part.get("slotOrdinal"),
                part.get("canvasIndex"),
                part.get("backingWidth"),
                part.get("backingHeight"),
                tuple(sorted(rect.items())) if isinstance(rect, Mapping) else None,
                part.get("drawGeneration"),
                part.get("successfulDraws"),
                part.get("mutationCount"),
                part.get("clipCalls"),
                part.get("lastFullDraw"),
                part.get("resetObserved"),
                part.get("contextIs2d"),
                part.get("observerOverflow"),
                part.get("drawReady"),
                geometry_signature,
            ))
        return tuple(signature)

    def _validate_capture_sequence(
        self, parts: list[object], *, current: int
    ) -> tuple[list[int], list[int]]:
        if not 1 <= len(parts) <= 2:
            raise UnknownPageStateError("ebookjapan current frame is not the observed one/two-part shape")
        ids: list[int] = []
        ordinals: list[int] = []
        for part in parts:
            if not isinstance(part, Mapping):
                raise UnknownPageStateError("ebookjapan frame contains an invalid slot")
            slot_id, ordinal = part.get("slotId"), part.get("slotOrdinal")
            if type(slot_id) is not int or type(ordinal) is not int:
                raise UnknownPageStateError("ebookjapan frame lacks an ephemeral slot identity")
            ids.append(slot_id)
            ordinals.append(ordinal)
        if len(set(ids)) != len(ids) or self._seen_slot_ids.intersection(ids):
            raise UnknownPageStateError("ebookjapan frame repeats a page slot")
        if self._next_dom_ordinal is None:
            if current != 1 or len(parts) != 1:
                raise UnknownPageStateError("ebookjapan capture did not begin at the observed single-page cover")
        else:
            expected = self._next_dom_ordinal
            for ordinal in ordinals:
                if ordinal != expected:
                    raise UnknownPageStateError("ebookjapan page-slot sequence skipped or revisited a DOM slot")
                expected -= 1
        return ids, ordinals

    async def _pinned_canvas_locator(self, page: Page, part: Mapping[str, object]):
        slot_ordinal, canvas_index = part.get("slotOrdinal"), part.get("canvasIndex")
        slot_id, canvas_id = part.get("slotId"), part.get("canvasId")
        if any(type(value) is not int for value in (slot_ordinal, canvas_index, slot_id, canvas_id)):
            raise UnknownPageStateError("ebookjapan selected canvas locator identity is malformed")
        locator = page.locator(".comic-viewer__page-slot").nth(slot_ordinal).locator("canvas").nth(canvas_index)
        valid = await locator.evaluate(
            """(canvas,{slotOrdinal,canvasIndex,slotId,canvasId})=>{
              const a=window.__ejReaderAnchor,slots=[...document.querySelectorAll('.comic-viewer__page-slot')],slot=slots[slotOrdinal];
              return !!a&&document===a.document&&slots.length===a.slots.length&&slots.every((e,i)=>e===a.slots[i])
                &&a.weak.get(slot)===slotId&&slot?.querySelectorAll('canvas')[canvasIndex]===canvas
                &&a.canvasWeak.get(canvas)===canvasId&&canvas.isConnected;
            }""",
            {"slotOrdinal": slot_ordinal, "canvasIndex": canvas_index, "slotId": slot_id, "canvasId": canvas_id},
        )
        if valid is not True:
            raise UnknownPageStateError("ebookjapan canvas element no longer matches its pinned slot reference")
        return locator

    @staticmethod
    def _decode_png(data: bytes) -> tuple[str, int, int]:
        if (
            not isinstance(data, bytes)
            or len(data) < 24
            or len(data) > 16 * 1024 * 1024
            or not data.startswith(b"\x89PNG\r\n\x1a\n")
        ):
            raise UnknownPageStateError("ebookjapan compositor returned an invalid or oversized PNG")
        try:
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                rgba = image.convert("RGBA")
                width, height = rgba.size
                pixel_hash = hashlib.sha256(rgba.tobytes()).hexdigest()
                rgba.close()
        except (OSError, ValueError, Image.DecompressionBombError):
            raise UnknownPageStateError("ebookjapan compositor PNG could not be decoded") from None
        if width < 1 or height < 1 or width * height > MAX_PART_PIXELS:
            raise UnknownPageStateError("ebookjapan compositor PNG dimensions exceed the per-part bound")
        return pixel_hash, width, height
