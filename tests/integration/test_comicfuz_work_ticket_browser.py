from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest

from screenshot_crawler.core.errors import UnknownPageStateError
from screenshot_crawler.discovery.service import DiscoveryIncompleteError
from screenshot_crawler.site_adapters.comicfuz import work_ticket as work_ticket_module
from screenshot_crawler.site_adapters.comicfuz.adapter import ComicFuzAdapter
from screenshot_crawler.site_adapters.comicfuz.discovery import ComicFuzDiscoveryAdapter
from screenshot_crawler.site_adapters.comicfuz.work_ticket import (
    API_HOST,
    API_PATH,
    API_ROUTE_PATTERN,
    TICKET_AVAILABLE_LABELS,
    TICKET_RECOVERY_UI_FALLBACK,
    ComicFuzTicketEntry,
    ComicFuzTicketNotAttemptedError,
    NativeTicketSnapshot,
    find_ticket_modal_cta,
    read_native_ticket_snapshot,
    read_ticket_modal,
)

pytestmark = pytest.mark.asyncio(loop_scope="module")

BASE = "https://comic-fuz.com"
WORK_ID = "3667"
CHAPTER_ID = "76630"
CHAPTER_LABEL = "Synthetic chapter"
AVAILABLE = next(iter(TICKET_AVAILABLE_LABELS))
RECOVERY = "0\u6642\u306b\u56de\u5fa9!"
CTA = "\u30c1\u30e3\u30fc\u30b8\u3067\u8aad\u3080"
CANCEL = "\u30ad\u30e3\u30f3\u30bb\u30eb"
APP = "\u30a2\u30d7\u30ea\u306f\u3053\u3061\u3089"
COMMENTS = "\u30b3\u30e1\u30f3\u30c8\u4e00\u89a7\u3078"


def _varint(value: int) -> bytes:
    output = bytearray()
    while value > 0x7F:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def _number(field: int, value: int) -> bytes:
    return _varint(field << 3) + _varint(value)


def _bytes(field: int, value: bytes) -> bytes:
    return _varint((field << 3) | 2) + _varint(len(value)) + value


def _request_body(*, chapter_id: int = int(CHAPTER_ID), paid_points: int = 0) -> bytes:
    device = _bytes(1, b"opaque-test-device-value") + _bytes(2, b"synthetic") + _number(3, 2)
    points = _number(2, paid_points) if paid_points else b""
    return (
        _bytes(1, device)
        + _number(2, 1)
        + _bytes(3, points)
        + _number(4, chapter_id)
    )


def _viewer_response(
    *, rental_expiry: str | None, manga_id: int = int(WORK_ID), ticket_available: bool = False
) -> bytes:
    charge_status = AVAILABLE if ticket_available else RECOVERY
    manga = _number(1, manga_id) + _number(13, 1) + _bytes(18, charge_status.encode())
    if ticket_available:
        manga += _number(12, 1)
    chapter = (
        _number(1, int(CHAPTER_ID))
        + _bytes(5, _number(2, 30))
    )
    if rental_expiry is not None:
        chapter += _bytes(10, rental_expiry.encode())
    group = _bytes(2, chapter)
    viewer_data = _bytes(2, _bytes(1, b"page-envelope"))
    return _bytes(2, viewer_data) + _bytes(5, group) + _bytes(11, manga) + _number(
        12, int(CHAPTER_ID)
    )


def _pre_state() -> NativeTicketSnapshot:
    return NativeTicketSnapshot(
        work_id=WORK_ID,
        chapter_id=CHAPTER_ID,
        chapter_label=CHAPTER_LABEL,
        is_charge_needed=True,
        is_charge_needed_present=True,
        is_ticket_available=True,
        is_ticket_available_present=True,
        is_ticket_available_in=True,
        is_ticket_available_prototype_default=False,
        charge_status=AVAILABLE,
        charge_status_present=True,
        point_type=0,
        point_amount=30,
        is_read=True,
        rental_value="",
        rental_present=False,
        rental_label="",
        viewer_chapter_id="",
    )


def _listing_html(*, modal_variant: str = "valid") -> str:
    title = "Different chapter" if modal_variant == "wrong_label" else CHAPTER_LABEL
    if modal_variant == "duplicate_price":
        price_values = ("1", "30")
    elif modal_variant == "price_two_with_unrelated_one":
        price_values = ("2",)
    else:
        price_values = ("1",)
    unrelated_price_one = modal_variant == "price_two_with_unrelated_one"
    price_extra_class = (
        " Dialog_items__mystery__fixture"
        if modal_variant == "unknown_price_marker"
        else ""
    )
    price_markup = "".join(
        f'<p class="Dialog_items__amount__fixture{price_extra_class}">{value}</p>'
        for value in price_values
    )
    duplicate_title = (
        '<p class="Dialog_chapter__mainText__duplicate">Different chapter</p>'
        if modal_variant == "duplicate_title"
        else ""
    )
    unknown_control = (
        '<button class="Dialog_buttons__extra__fixture">Another access</button>'
        if modal_variant == "unknown_control"
        else ""
    )
    app_pair = (
        f'<a>{APP}</a>'
        f'<button class="Dialog_appflow__button__fixture">{APP}</button>'
    )
    if modal_variant == "lookalike_app_control":
        app_control = f'<button class="Dialog_unknown__fixture">{APP}</button>'
    elif modal_variant == "third_app_control":
        app_control = f'{app_pair}<a>{APP}</a>'
    elif modal_variant == "unknown_app_anchor_class":
        app_control = (
            f'<a class="Dialog_unknown__fixture">{APP}</a>'
            f'<button class="Dialog_appflow__button__fixture">{APP}</button>'
        )
    elif modal_variant == "unknown_app_button_class":
        app_control = (
            f'<a>{APP}</a><button class="Dialog_unknown__fixture">{APP}</button>'
        )
    elif modal_variant == "unknown_app_tag":
        app_control = (
            f'<a>{APP}</a>'
            f'<div role="button" class="Dialog_appflow__button__fixture">{APP}</div>'
        )
    else:
        app_control = app_pair
    modal = f"""<div class="Dialog_modal__fixture">
        <div class="Dialog_content__fixture">
          <div class="Dialog_chapter__fixture">
            <p class="Dialog_chapter__mainText__fixture">{title}</p>
            {duplicate_title}
          </div>
          <div class="Dialog_items__fixture">
            <div class="Dialog_items__item__fixture">
              <span class="Dialog_items__icon__fixture"></span>
              {price_markup}
              {'<span>1</span>' if unrelated_price_one else ''}
            </div>
          </div>
          <div class="Dialog_buttons__fixture">
            <a class="Dialog_buttons__active__fixture">{CTA}</a>
            {app_control}
            <a class="Dialog_buttons__active__fixture">{COMMENTS}</a>
            <a class="Dialog_buttons__cancel__fixture">{CANCEL}</a>
            {unknown_control}
          </div>
        </div>
      </div>"""
    if modal_variant == "duplicate_dialog":
        modal += modal
    elif modal_variant == "hidden_duplicate_dialog":
        modal += modal.replace(
            'class="Dialog_modal__fixture"',
            'class="Dialog_modal__hidden__fixture" style="display:none"',
        )
    elif modal_variant == "opacity_zero_duplicate_dialog":
        modal += modal.replace(
            'class="Dialog_modal__fixture"',
            'class="Dialog_modal__hidden__fixture" style="opacity:0"',
        )
    return f"""<!doctype html><html><body>
      <h3 class="Chapter_chapter__name__fixture">{CHAPTER_LABEL}</h3>
      <button class="page-control__fixture">Background control</button>
      <div class="Charge_charge__charged__fixture">{AVAILABLE}
        <img alt="\u30c1\u30e3\u30fc\u30b8" src="/assets/manga_detail/charged.svg">
      </div>
      {modal}
    </body></html>"""


async def _prepare_page(
    browser_page,
    browser_context,
    *,
    body: bytes,
    downstream: list[bytes],
    request_frame: str = "main",
    api_action=None,
    omit_response_expiry: bool = False,
    response_ticket_available: bool = False,
    inherit_viewer_ticket_default: bool = False,
    mismatch_response_expiry: bool = False,
    api_url: str | None = None,
    send_request: bool = True,
    rental_expiry_override: str | None = None,
    modal_variant: str = "valid",
):
    expiry = rental_expiry_override or (
        datetime.now(UTC) + timedelta(hours=24)
    ).isoformat()
    response_expiry = (
        datetime.fromisoformat(expiry) + timedelta(days=1)
        if mismatch_response_expiry
        else datetime.fromisoformat(expiry)
    )
    response_body = _viewer_response(
        rental_expiry=None if omit_response_expiry else response_expiry.isoformat(),
        ticket_available=response_ticket_available,
    )
    async def listing(route) -> None:
        await route.fulfill(
            status=200,
            content_type="text/html; charset=utf-8",
            body=_listing_html(modal_variant=modal_variant),
        )

    async def badge(route) -> None:
        await route.fulfill(
            status=200,
            content_type="image/svg+xml",
            body='<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"></svg>',
        )

    await browser_page.route(f"{BASE}/manga/{WORK_ID}", listing)
    await browser_page.route(f"{BASE}/assets/manga_detail/charged.svg", badge)
    await browser_page.goto(f"{BASE}/manga/{WORK_ID}")
    await browser_page.evaluate(
        """({viewerUrl, apiUrl, bodyBytes, workId, chapterId, chapterLabel, expiry, recovery, chargeLabel, requestFrame, inheritTicketDefault, sendRequest}) => {
          const cta=[...document.querySelectorAll('a[class*="Dialog_buttons__active__"]')]
            .find(e=>e.innerText.trim()===chargeLabel);
          cta.addEventListener('click',()=>{
            history.pushState({},'',viewerUrl);
            const updateViewer=()=>{
                const manga={mangaId:workId,isChargeNeeded:true,chargeStatus:recovery};
                if(inheritTicketDefault)Object.setPrototypeOf(manga,{isTicketAvailable:false});
                else manga.isTicketAvailable=false;
                const data={chapterId,manga,chapters:[{chapters:[{
                    chapterId,chapterMainName:chapterLabel,pointConsumption:{type:0,amount:30},
                    isRead:true,endOfRentalPeriod:expiry
                  }]}]};
                const image=document.createElement('img');
                image.className='G54Y0W_page__fixture';
                image.__reactFiber$synthetic={memoizedProps:{webMangaViewerData:data},return:null};
                document.body.replaceChildren(image);
            };
            if(requestFrame==='subframe'){
              const frame=document.createElement('iframe');
              frame.onload=()=>frame.contentWindow.fetch(apiUrl,{method:'POST',
                headers:{'content-type':'text/plain'},body:new Uint8Array(bodyBytes)}).catch(()=>{});
              frame.srcdoc='<!doctype html><html><body></body></html>';
              document.body.append(frame);
              return;
            }
              if(!sendRequest){updateViewer();return;}
            fetch(apiUrl,{method:'POST',headers:{'content-type':'text/plain'},
              body:new Uint8Array(bodyBytes)}).then(()=>updateViewer()).catch(()=>{});
          });
        }""",
        {
            "viewerUrl": f"{BASE}/manga/viewer/{CHAPTER_ID}?ticket=true",
            "apiUrl": api_url or f"https://{API_HOST}{API_PATH}",
            "bodyBytes": list(body),
            "workId": WORK_ID,
            "chapterId": CHAPTER_ID,
            "chapterLabel": CHAPTER_LABEL,
            "expiry": expiry,
            "recovery": RECOVERY,
            "chargeLabel": CTA,
            "requestFrame": request_frame,
            "inheritTicketDefault": inherit_viewer_ticket_default,
            "sendRequest": send_request,
        },
    )

    async def api(route) -> None:
        request = route.request
        if request.url != f"https://{API_HOST}{API_PATH}":
            downstream.append(b"noncanonical-endpoint-forwarded")
            await route.abort("blockedbyclient")
            return
        downstream.append(request.post_data_buffer or b"")
        if api_action is not None:
            await api_action(route, response_body)
            return
        await route.fulfill(
            status=200,
            content_type="application/octet-stream",
            headers={"access-control-allow-origin": BASE},
            body=response_body,
        )

    await browser_context.route(API_ROUTE_PATTERN, api)
    return browser_page


async def _post_ticket_again(page, body: bytes) -> str:
    return await page.evaluate(
        """async body => {
          try {
            await fetch('https://api.comic-fuz.com/v1/web_manga_viewer_2', {
              method:'POST',headers:{'content-type':'text/plain'},body:new Uint8Array(body)
            });
            return 'forwarded';
          } catch (_) { return 'blocked'; }
        }""",
        list(body),
    )


async def test_ticket_controller_succeeds_once_and_keeps_page_route_guard(
    browser_page, browser_context
) -> None:
    body = _request_body()
    downstream: list[bytes] = []
    page = await _prepare_page(
        browser_page,
        browser_context,
        body=body,
        downstream=downstream,
        inherit_viewer_ticket_default=True,
    )
    controller = ComicFuzTicketEntry(
        work_id=WORK_ID, chapter_id=CHAPTER_ID, external_id=f"{WORK_ID}:{CHAPTER_ID}"
    )
    observations = []
    grants = []
    cta = page.get_by_text(CTA, exact=True)

    async def click() -> None:
        await cta.click()

    proof = await controller.enter(
        page,
        chapter_label=CHAPTER_LABEL,
        native_state=_pre_state(),
        row_access_mode="quota",
        attempt_reporter=observations.append,
        grant_reporter=grants.append,
        click=click,
    )

    assert proof.request_started_at.tzinfo is not None
    assert proof.confirmed_at.date() == proof.request_started_at.date()
    assert controller.consumption.consumed is True
    assert controller.consumption.stop_resource_pass is False
    post_state = await read_native_ticket_snapshot(
        page,
        work_id=WORK_ID,
        chapter_id=CHAPTER_ID,
        page_mode="viewer",
    )
    assert post_state.is_ticket_available is False
    assert post_state.is_ticket_available_present is False
    assert post_state.is_ticket_available_prototype_default is True
    assert len(downstream) == 1 and downstream[0] == body
    assert [row.status for row in observations] == ["attempting", "confirmed"]

    with pytest.raises(UnknownPageStateError, match="already latched"):
        await controller.enter(
            page,
            chapter_label=CHAPTER_LABEL,
            native_state=_pre_state(),
            row_access_mode="quota",
            attempt_reporter=observations.append,
            grant_reporter=grants.append,
            click=click,
        )
    retry_result = await page.evaluate(
        """async body => {
          try {
            await fetch('https://api.comic-fuz.com/v1/web_manga_viewer_2',{
              method:'POST',headers:{'content-type':'text/plain'},body:new Uint8Array(body)
            });
            return 'forwarded';
          } catch (_) { return 'blocked'; }
        }""",
        list(body),
    )
    assert retry_result == "blocked"
    assert len(downstream) == 1


async def test_paid_point_viewer_request_is_aborted_before_network_send(
    browser_page, browser_context
) -> None:
    body = _request_body(paid_points=1)
    downstream: list[bytes] = []
    page = await _prepare_page(browser_page, browser_context, body=body, downstream=downstream)
    controller = ComicFuzTicketEntry(
        work_id=WORK_ID, chapter_id=CHAPTER_ID, external_id=f"{WORK_ID}:{CHAPTER_ID}"
    )
    observations = []
    cta = page.get_by_text(CTA, exact=True)

    async def click() -> None:
        await cta.click()

    with pytest.raises(UnknownPageStateError, match="result is unknown"):
        await controller.enter(
            page,
            chapter_label=CHAPTER_LABEL,
            native_state=_pre_state(),
            row_access_mode="quota",
            attempt_reporter=observations.append,
            grant_reporter=lambda grant: None,
            click=click,
        )

    assert downstream == []
    assert controller.attempt_latched is True
    assert [row.status for row in observations] == ["attempting", "unknown"]
    assert await _post_ticket_again(page, _request_body()) == "blocked"
    assert downstream == []


@pytest.mark.parametrize(
    "api_url",
    [
        f"https://{API_HOST}:9443{API_PATH}",
        f"https://{API_HOST}{API_PATH}?unexpected=1",
    ],
)
async def test_noncanonical_known_endpoint_is_aborted_before_context_forward(
    browser_page, browser_context, api_url: str
) -> None:
    downstream: list[bytes] = []
    page = await _prepare_page(
        browser_page,
        browser_context,
        body=_request_body(),
        downstream=downstream,
        api_url=api_url,
    )
    controller = ComicFuzTicketEntry(
        work_id=WORK_ID, chapter_id=CHAPTER_ID, external_id=f"{WORK_ID}:{CHAPTER_ID}"
    )
    observations = []

    with pytest.raises(UnknownPageStateError, match="result is unknown"):
        await controller.enter(
            page,
            chapter_label=CHAPTER_LABEL,
            native_state=_pre_state(),
            row_access_mode="quota",
            attempt_reporter=observations.append,
            grant_reporter=lambda grant: None,
            click=lambda: page.get_by_text(CTA, exact=True).click(),
        )

    assert downstream == []
    assert [observation.status for observation in observations] == ["attempting", "unknown"]


async def test_consumption_is_kept_when_grant_expiry_is_missing(
    browser_page, browser_context
) -> None:
    body = _request_body()
    downstream: list[bytes] = []
    page = await _prepare_page(
        browser_page,
        browser_context,
        body=body,
        downstream=downstream,
        omit_response_expiry=True,
    )
    controller = ComicFuzTicketEntry(
        work_id=WORK_ID, chapter_id=CHAPTER_ID, external_id=f"{WORK_ID}:{CHAPTER_ID}"
    )
    observations = []

    with pytest.raises(UnknownPageStateError, match="result is unknown"):
        await controller.enter(
            page,
            chapter_label=CHAPTER_LABEL,
            native_state=_pre_state(),
            row_access_mode="quota",
            attempt_reporter=observations.append,
            grant_reporter=lambda grant: None,
            click=lambda: page.get_by_text(CTA, exact=True).click(),
        )

    adapter = ComicFuzAdapter()
    adapter._ticket_entry = controller
    consumption = adapter.get_access_consumption()
    assert consumption.consumed is True
    assert consumption.resource == "work_ticket"
    assert consumption.access_granted_until is None
    assert [row.status for row in observations] == ["attempting", "confirmed"]
    assert len(downstream) == 1


async def test_response_and_react_expiry_must_match_after_consumption(
    browser_page, browser_context
) -> None:
    body = _request_body()
    downstream: list[bytes] = []
    page = await _prepare_page(
        browser_page,
        browser_context,
        body=body,
        downstream=downstream,
        mismatch_response_expiry=True,
    )
    controller = ComicFuzTicketEntry(
        work_id=WORK_ID, chapter_id=CHAPTER_ID, external_id=f"{WORK_ID}:{CHAPTER_ID}"
    )
    observations = []

    with pytest.raises(UnknownPageStateError, match="result is unknown"):
        await controller.enter(
            page,
            chapter_label=CHAPTER_LABEL,
            native_state=_pre_state(),
            row_access_mode="quota",
            attempt_reporter=observations.append,
            grant_reporter=lambda grant: None,
            click=lambda: page.get_by_text(CTA, exact=True).click(),
        )

    assert controller.consumption.consumed is True
    assert controller.consumption.access_granted_until is None
    assert [row.status for row in observations] == ["attempting", "confirmed"]
    assert len(downstream) == 1


async def test_expiry_must_still_be_future_at_grant_commit(
    browser_page, browser_context
) -> None:
    expiry = datetime.now(UTC) + timedelta(seconds=2)
    clock_values = [
        expiry - timedelta(minutes=1),
        expiry - timedelta(minutes=1),
        expiry - timedelta(minutes=1),
        expiry - timedelta(minutes=1),
        expiry - timedelta(minutes=1),
        expiry - timedelta(minutes=1),
        expiry - timedelta(milliseconds=100),
        expiry + timedelta(milliseconds=100),
    ]
    downstream: list[bytes] = []
    page = await _prepare_page(
        browser_page,
        browser_context,
        body=_request_body(),
        downstream=downstream,
        rental_expiry_override=expiry.isoformat(),
    )
    controller = ComicFuzTicketEntry(
        work_id=WORK_ID, chapter_id=CHAPTER_ID, external_id=f"{WORK_ID}:{CHAPTER_ID}"
    )
    controller._now = lambda: clock_values.pop(0)
    observations = []

    with pytest.raises(UnknownPageStateError, match="result is unknown"):
        await controller.enter(
            page,
            chapter_label=CHAPTER_LABEL,
            native_state=_pre_state(),
            row_access_mode="quota",
            attempt_reporter=observations.append,
            grant_reporter=lambda grant: None,
            click=lambda: page.get_by_text(CTA, exact=True).click(),
        )

    assert controller.consumption.consumed is True
    assert controller.consumption.access_granted_until is None
    assert [observation.status for observation in observations] == ["attempting", "confirmed"]


async def test_http_200_without_native_ticket_transition_stays_unknown(
    browser_page, browser_context
) -> None:
    body = _request_body()
    downstream: list[bytes] = []
    page = await _prepare_page(
        browser_page,
        browser_context,
        body=body,
        downstream=downstream,
        response_ticket_available=True,
    )
    controller = ComicFuzTicketEntry(
        work_id=WORK_ID, chapter_id=CHAPTER_ID, external_id=f"{WORK_ID}:{CHAPTER_ID}"
    )
    observations = []

    with pytest.raises(UnknownPageStateError, match="result is unknown"):
        await controller.enter(
            page,
            chapter_label=CHAPTER_LABEL,
            native_state=_pre_state(),
            row_access_mode="quota",
            attempt_reporter=observations.append,
            grant_reporter=lambda grant: None,
            click=lambda: page.get_by_text(CTA, exact=True).click(),
        )

    assert len(downstream) == 1
    assert controller.consumption.consumed is False
    assert [row.status for row in observations] == ["attempting", "unknown"]
    assert await _post_ticket_again(page, _request_body()) == "blocked"
    assert len(downstream) == 1


async def test_consumption_survives_confirmation_sink_failure(browser_page, browser_context) -> None:
    body = _request_body()
    downstream: list[bytes] = []
    page = await _prepare_page(browser_page, browser_context, body=body, downstream=downstream)
    controller = ComicFuzTicketEntry(
        work_id=WORK_ID, chapter_id=CHAPTER_ID, external_id=f"{WORK_ID}:{CHAPTER_ID}"
    )
    adapter = ComicFuzAdapter()
    adapter._ticket_entry = controller
    statuses: list[str] = []

    def failing_reporter(observation) -> None:
        statuses.append(observation.status)
        if observation.status == "confirmed":
            raise RuntimeError("synthetic observation sink failure")

    with pytest.raises(RuntimeError, match="sink failure"):
        await controller.enter(
            page,
            chapter_label=CHAPTER_LABEL,
            native_state=_pre_state(),
            row_access_mode="quota",
            attempt_reporter=failing_reporter,
            grant_reporter=lambda grant: None,
            click=lambda: page.get_by_text(CTA, exact=True).click(),
        )

    assert statuses == ["attempting", "confirmed"]
    assert adapter.get_access_consumption().consumed is True
    assert adapter.get_access_consumption().access_granted_until is None


async def test_missing_ticket_cta_is_a_proved_no_action(browser_page, browser_context) -> None:
    body = _request_body()
    downstream: list[bytes] = []
    page = await _prepare_page(browser_page, browser_context, body=body, downstream=downstream)
    await page.evaluate(
        "label => [...document.querySelectorAll('a[class*=\\\"Dialog_buttons__active__\\\"]')]"
        ".find(element => element.innerText.trim() === label)?.remove()",
        CTA,
    )
    controller = ComicFuzTicketEntry(
        work_id=WORK_ID, chapter_id=CHAPTER_ID, external_id=f"{WORK_ID}:{CHAPTER_ID}"
    )
    observations = []

    async def unexpected_click() -> None:
        raise AssertionError("CTA should not be clicked when the visible modal is absent")

    with pytest.raises(ComicFuzTicketNotAttemptedError, match="target_ticket_modal_not_exact"):
        await controller.enter(
            page,
            chapter_label=CHAPTER_LABEL,
            native_state=_pre_state(),
            row_access_mode="quota",
            attempt_reporter=observations.append,
            grant_reporter=lambda grant: None,
            click=unexpected_click,
        )

    assert controller.attempt_latched is False
    assert [row.status for row in observations] == ["not_attempted"]
    assert downstream == []


@pytest.mark.parametrize(
    "modal_variant",
    ("valid", "hidden_duplicate_dialog", "opacity_zero_duplicate_dialog"),
)
async def test_ticket_modal_scope_ignores_background_heading_and_controls(
    browser_page, browser_context, modal_variant: str
) -> None:
    page = await _prepare_page(
        browser_page,
        browser_context,
        body=_request_body(),
        downstream=[],
        modal_variant=modal_variant,
    )

    modal = await read_ticket_modal(page, chapter_label=CHAPTER_LABEL)
    cta = await find_ticket_modal_cta(page, chapter_label=CHAPTER_LABEL)

    assert modal["dialogRootCount"] == 1
    assert modal["globalCtaCount"] == 1
    assert modal["ctaCount"] == 1
    assert modal["chapterTitleCount"] == 1
    assert modal["chapterTitleMatch"] is True
    assert modal["cancelCount"] == 1
    assert modal["ticketCountOne"] is True
    assert modal["allowedControls"] == {"app": 2, "comments": 1, "cancel": 1}
    assert modal["otherAccessCount"] == 0
    assert modal["disabled"] is False
    assert modal["exact"] is True
    assert await cta.evaluate("element => element.tagName") == "A"
    assert " ".join((await cta.inner_text()).split()) == CTA


@pytest.mark.parametrize(
    "modal_variant",
    ("hidden_duplicate_dialog", "opacity_zero_duplicate_dialog"),
)
async def test_ticket_controller_accepts_only_one_visible_dialog_root(
    browser_page, browser_context, modal_variant: str
) -> None:
    body = _request_body()
    downstream: list[bytes] = []
    page = await _prepare_page(
        browser_page,
        browser_context,
        body=body,
        downstream=downstream,
        modal_variant=modal_variant,
        inherit_viewer_ticket_default=True,
    )
    controller = ComicFuzTicketEntry(
        work_id=WORK_ID, chapter_id=CHAPTER_ID, external_id=f"{WORK_ID}:{CHAPTER_ID}"
    )
    observations = []

    async def click_visible_modal_cta() -> None:
        cta = await find_ticket_modal_cta(page, chapter_label=CHAPTER_LABEL)
        await cta.click()

    proof = await controller.enter(
        page,
        chapter_label=CHAPTER_LABEL,
        native_state=_pre_state(),
        row_access_mode="quota",
        attempt_reporter=observations.append,
        grant_reporter=lambda grant: None,
        click=click_visible_modal_cta,
    )

    assert proof.request_started_at.tzinfo is not None
    assert controller.consumption.consumed is True
    assert len(downstream) == 1


@pytest.mark.parametrize(
    "modal_variant",
    (
        "duplicate_dialog",
        "wrong_label",
        "duplicate_title",
        "duplicate_price",
        "price_two_with_unrelated_one",
        "unknown_price_marker",
        "unknown_control",
        "lookalike_app_control",
        "third_app_control",
        "unknown_app_anchor_class",
        "unknown_app_button_class",
        "unknown_app_tag",
    ),
)
async def test_ambiguous_ticket_dialog_is_a_no_action(
    browser_page, browser_context, modal_variant: str
) -> None:
    body = _request_body()
    downstream: list[bytes] = []
    page = await _prepare_page(
        browser_page,
        browser_context,
        body=body,
        downstream=downstream,
        modal_variant=modal_variant,
    )
    controller = ComicFuzTicketEntry(
        work_id=WORK_ID, chapter_id=CHAPTER_ID, external_id=f"{WORK_ID}:{CHAPTER_ID}"
    )
    observations = []

    async def unexpected_click() -> None:
        raise AssertionError("CTA must not be clicked for an ambiguous modal")

    with pytest.raises(ComicFuzTicketNotAttemptedError, match="target_ticket_modal_not_exact"):
        await controller.enter(
            page,
            chapter_label=CHAPTER_LABEL,
            native_state=_pre_state(),
            row_access_mode="quota",
            attempt_reporter=observations.append,
            grant_reporter=lambda grant: None,
            click=unexpected_click,
        )

    assert controller.attempt_latched is False
    assert [row.status for row in observations] == ["not_attempted"]
    assert downstream == []


async def test_wrong_chapter_request_is_aborted_before_network_send(
    browser_page, browser_context
) -> None:
    body = _request_body(chapter_id=int(CHAPTER_ID) + 1)
    downstream: list[bytes] = []
    page = await _prepare_page(browser_page, browser_context, body=body, downstream=downstream)
    controller = ComicFuzTicketEntry(
        work_id=WORK_ID, chapter_id=CHAPTER_ID, external_id=f"{WORK_ID}:{CHAPTER_ID}"
    )
    observations = []

    with pytest.raises(UnknownPageStateError, match="result is unknown"):
        await controller.enter(
            page,
            chapter_label=CHAPTER_LABEL,
            native_state=_pre_state(),
            row_access_mode="quota",
            attempt_reporter=observations.append,
            grant_reporter=lambda grant: None,
            click=lambda: page.get_by_text(CTA, exact=True).click(),
        )

    assert downstream == []
    assert [row.status for row in observations] == ["attempting", "unknown"]
    assert await _post_ticket_again(page, _request_body()) == "blocked"
    assert downstream == []


@pytest.mark.parametrize("interruption", ["timeout", "cancel"])
async def test_terminal_operation_blocks_late_ticket_after_timeout_or_cancel(
    browser_page, browser_context, monkeypatch, interruption: str
) -> None:
    if interruption == "timeout":
        monkeypatch.setattr(work_ticket_module, "ACTION_TIMEOUT_MS", 500)
    downstream: list[bytes] = []
    page = await _prepare_page(
        browser_page,
        browser_context,
        body=_request_body(),
        downstream=downstream,
        send_request=False,
    )
    controller = ComicFuzTicketEntry(
        work_id=WORK_ID, chapter_id=CHAPTER_ID, external_id=f"{WORK_ID}:{CHAPTER_ID}"
    )
    observations = []
    operation = asyncio.create_task(
        controller.enter(
            page,
            chapter_label=CHAPTER_LABEL,
            native_state=_pre_state(),
            row_access_mode="quota",
            attempt_reporter=observations.append,
            grant_reporter=lambda grant: None,
            click=lambda: page.get_by_text(CTA, exact=True).click(),
        )
    )

    if interruption == "cancel":
        await page.wait_for_url(
            f"{BASE}/manga/viewer/{CHAPTER_ID}?ticket=true", timeout=2_000
        )
        await asyncio.sleep(0.05)
        operation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await operation
    else:
        with pytest.raises(UnknownPageStateError, match="result is unknown"):
            await operation

    assert controller.attempt_latched is True
    assert [observation.status for observation in observations] == ["attempting", "unknown"]
    assert await _post_ticket_again(page, _request_body()) == "blocked"
    assert downstream == []


async def test_inflight_ticket_request_is_aborted_if_operation_cancels_before_forward(
    browser_page, browser_context
) -> None:
    downstream: list[bytes] = []
    page = await _prepare_page(
        browser_page,
        browser_context,
        body=_request_body(),
        downstream=downstream,
    )
    controller = ComicFuzTicketEntry(
        work_id=WORK_ID, chapter_id=CHAPTER_ID, external_id=f"{WORK_ID}:{CHAPTER_ID}"
    )
    observations = []
    forward_gate_entered = asyncio.Event()
    release_forward_gate = asyncio.Event()

    async def pause_before_forward() -> None:
        forward_gate_entered.set()
        await release_forward_gate.wait()

    controller._before_ticket_request_forward = pause_before_forward
    operation = asyncio.create_task(
        controller.enter(
            page,
            chapter_label=CHAPTER_LABEL,
            native_state=_pre_state(),
            row_access_mode="quota",
            attempt_reporter=observations.append,
            grant_reporter=lambda grant: None,
            click=lambda: page.get_by_text(CTA, exact=True).click(),
        )
    )
    await asyncio.wait_for(forward_gate_entered.wait(), timeout=2)
    operation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await operation
    release_forward_gate.set()

    assert await _post_ticket_again(page, _request_body()) == "blocked"
    assert downstream == []
    assert controller.attempt_latched is True
    assert [observation.status for observation in observations] == ["attempting", "unknown"]


async def test_subframe_ticket_request_is_aborted_before_network_send(
    browser_page, browser_context
) -> None:
    body = _request_body()
    downstream: list[bytes] = []
    page = await _prepare_page(
        browser_page,
        browser_context,
        body=body,
        downstream=downstream,
        request_frame="subframe",
    )
    controller = ComicFuzTicketEntry(
        work_id=WORK_ID, chapter_id=CHAPTER_ID, external_id=f"{WORK_ID}:{CHAPTER_ID}"
    )
    observations = []

    with pytest.raises(UnknownPageStateError, match="result is unknown"):
        await controller.enter(
            page,
            chapter_label=CHAPTER_LABEL,
            native_state=_pre_state(),
            row_access_mode="quota",
            attempt_reporter=observations.append,
            grant_reporter=lambda grant: None,
            click=lambda: page.get_by_text(CTA, exact=True).click(),
        )

    assert downstream == []
    assert [row.status for row in observations] == ["attempting", "unknown"]


async def test_request_and_proof_crossing_jst_midnight_is_unknown(
    browser_page, browser_context
) -> None:
    body = _request_body()
    downstream: list[bytes] = []
    before = datetime(2026, 11, 24, 14, 59, 59, tzinfo=UTC)
    after = datetime(2026, 11, 24, 15, 0, 2, tzinfo=UTC)
    clock = [before]

    async def advance_after_request(route, response_body: bytes) -> None:
        clock[0] = after
        await route.fulfill(
            status=200,
            content_type="application/octet-stream",
            headers={"access-control-allow-origin": BASE},
            body=response_body,
        )

    page = await _prepare_page(
        browser_page,
        browser_context,
        body=body,
        downstream=downstream,
        api_action=advance_after_request,
    )
    controller = ComicFuzTicketEntry(
        work_id=WORK_ID, chapter_id=CHAPTER_ID, external_id=f"{WORK_ID}:{CHAPTER_ID}"
    )
    controller._now = lambda: clock[0]
    observations = []

    with pytest.raises(UnknownPageStateError, match="result is unknown"):
        await controller.enter(
            page,
            chapter_label=CHAPTER_LABEL,
            native_state=_pre_state(),
            row_access_mode="quota",
            attempt_reporter=observations.append,
            grant_reporter=lambda grant: None,
            click=lambda: page.get_by_text(CTA, exact=True).click(),
        )

    assert len(downstream) == 1
    assert [row.status for row in observations] == ["attempting", "unknown"]
    assert controller.consumption.consumed is False
    with pytest.raises(UnknownPageStateError, match="already latched"):
        await controller.enter(
            page,
            chapter_label=CHAPTER_LABEL,
            native_state=_pre_state(),
            row_access_mode="quota",
            attempt_reporter=observations.append,
            grant_reporter=lambda grant: None,
            click=lambda: page.get_by_text(CTA, exact=True).click(),
        )


async def _install_listing_snapshot_fixture(browser_page, *, variant: str = "valid") -> None:
    records = [(int(CHAPTER_ID), CHAPTER_LABEL, 30)]
    if variant == "non_target_id_order_mismatch":
        records.extend([(76631, "Other one", 30), (76632, "Other two", 30)])
    native = {
        "page": "/manga/[mangaId]",
        "query": {"mangaId": WORK_ID},
        "props": {"pageProps": {"chapters": [{"chapters": [
            {"chapterId": chapter_id, "chapterMainName": label,
             "pointConsumption": {"amount": amount}}
            for chapter_id, label, amount in records
        ]}]}}
    }
    rows = "".join(
        f'<div class="Chapter_chapter__row__fixture"><div><h3 '
        f'class="Chapter_chapter__name__fixture">{label}</h3></div></div>'
        for _, label, _ in records
    )
    html = f"""<!doctype html><html><body>
      <script id="__NEXT_DATA__" type="application/json">{json.dumps(native)}</script>
      <div class="title_detail_chapters__list__fixture">{rows}</div>
      <div class="Charge_charge__charged__fixture"><img alt="\u30c1\u30e3\u30fc\u30b8"
        src="/assets/manga_detail/charged.svg"><p>{AVAILABLE}</p></div>
    </body></html>"""

    async def listing(route) -> None:
        await route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)

    async def badge(route) -> None:
        await route.fulfill(
            status=200,
            content_type="image/svg+xml",
            body='<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"></svg>',
        )

    await browser_page.route(f"{BASE}/manga/{WORK_ID}**", listing)
    await browser_page.route(f"{BASE}/assets/manga_detail/charged.svg", badge)
    await browser_page.route(f"{BASE}/assets/manga_detail/charge.svg", badge)
    await browser_page.goto(f"{BASE}/manga/{WORK_ID}?position=thumbnail")
    await browser_page.evaluate(
        """({workId, chapterId, chapterLabel, available, recovery, recoveryUiFallback, variant, records}) => {
          const pointProto=variant==='point_type_missing'?{}:{type:0};
          const rentalProto=variant==='rental_default_missing'?{}:{endOfRentalPeriod:''};
          const runtimeChapters=records.map(([id,label,amount])=>Object.assign(
            Object.create(rentalProto),{chapterId:id,chapterMainName:label,
              pointConsumption:Object.assign(Object.create(pointProto),{amount})}));
          if(variant==='runtime_point_amount_mismatch')
            runtimeChapters[0].pointConsumption.amount=31;
          const parsed=JSON.parse(document.querySelector('#__NEXT_DATA__').textContent);
          const nativeChapters=parsed.props.pageProps.chapters[0].chapters;
          if(variant==='whitespace_label_match'){
            runtimeChapters[0].chapterMainName=` \t${chapterLabel}  `;
            nativeChapters[0].chapterMainName=` ${chapterLabel} `;
          }
          if(variant==='ssr_point_type_conflict')nativeChapters[0].pointConsumption.type=1;
          if(variant==='ssr_point_amount_conflict')nativeChapters[0].pointConsumption.amount=31;
          if(variant==='ssr_label_conflict')nativeChapters[0].chapterMainName='Different label';
          document.querySelector('#__NEXT_DATA__').textContent=JSON.stringify(parsed);
          const rowChapters=[...runtimeChapters];
          if(variant==='row_label_conflict')rowChapters[0]=Object.assign(
            Object.create(rentalProto),{chapterId:Number(chapterId),chapterMainName:'Different label',
              pointConsumption:runtimeChapters[0].pointConsumption});
          let webChapters=[...runtimeChapters];
          if(variant==='non_target_id_order_mismatch')
            webChapters=[webChapters[0],webChapters[2],webChapters[1]];
          if(variant==='duplicate_target')webChapters.push(runtimeChapters[0]);
          const mangaProto=variant==='unavailable_known_default'
            ?{isTicketAvailable:false,chargeStatus:''}:{};
          const manga=Object.assign(Object.create(mangaProto),{
            mangaId:Number(variant==='wrong_work'?9999:workId),isChargeNeeded:true});
          if(variant!=='unavailable_known_default'){
            manga.isTicketAvailable=true;
            manga.chargeStatus=available;
          }
          if(variant==='missing_runtime_availability'){
            delete manga.isTicketAvailable;
            delete manga.chargeStatus;
          }
          const webData={manga,chapters:[{chapters:webChapters}]};
          let chargeData=webData;
          if(variant==='different_messages_same_values')
            chargeData={manga:Object.assign(Object.create(Object.getPrototypeOf(manga)),manga),
              chapters:[{chapters:webChapters}]};
          const headings=[...document.querySelectorAll('h3')];
          headings.forEach((heading,index)=>{
            const dataFiber={memoizedProps:{webMangaViewerData:webData},return:null};
            const rowFiber={memoizedProps:{chapter:rowChapters[index]},return:dataFiber};
            if(index===0&&variant==='missing_runtime_data')rowFiber.return=null;
            if(index===0&&variant==='multiple_heading_messages')
              dataFiber.return={memoizedProps:{webMangaViewerData:{manga:{...manga},
                chapters:[{chapters:webChapters}]}},return:null};
            heading.__reactFiber$target=rowFiber;
          });
          const unavailable=variant==='unavailable_known_default';
          const directAvailable=variant==='charge_state_mismatch'?false:!!manga.isTicketAvailable;
          const directLabel=variant==='charge_state_mismatch'?recovery:(manga.chargeStatus||'');
          const visibleLabel=directLabel||(directAvailable?available:recoveryUiFallback);
          const charge=document.querySelector('.Charge_charge__charged__fixture');
          charge.className=unavailable?'Charge_charge__not_charged__fixture':'Charge_charge__charged__fixture';
          charge.querySelector('img').src=unavailable
            ?'/assets/manga_detail/charge.svg':'/assets/manga_detail/charged.svg';
          charge.querySelector('p').textContent=visibleLabel;
          const chargeDataFiber={memoizedProps:{webMangaViewerData:chargeData},return:null};
          charge.__reactFiber$host={memoizedProps:{className:charge.className},
            return:{memoizedProps:{isTicketAvailable:directAvailable,labelText:directLabel},return:chargeDataFiber}};
        }""",
        {"workId": WORK_ID, "chapterId": CHAPTER_ID, "chapterLabel": CHAPTER_LABEL,
         "available": AVAILABLE, "recovery": RECOVERY,
         "recoveryUiFallback": TICKET_RECOVERY_UI_FALLBACK, "variant": variant,
         "records": records},
    )


async def test_listing_snapshot_joins_row_and_charge_to_same_runtime_message(browser_page) -> None:
    await _install_listing_snapshot_fixture(browser_page)
    snapshot = await read_native_ticket_snapshot(
        browser_page, work_id=WORK_ID, chapter_id=CHAPTER_ID, page_mode="listing"
    )

    assert snapshot.work_id == WORK_ID
    assert snapshot.chapter_id == CHAPTER_ID
    assert snapshot.point_type == 0 and snapshot.point_amount == 30
    assert snapshot.is_read is None
    assert snapshot.rental_value == "" and snapshot.rental_present is False
    assert snapshot.is_charge_needed and snapshot.is_ticket_available
    assert snapshot.charge_status == AVAILABLE


async def test_listing_snapshot_returns_whitespace_normalized_chapter_label(browser_page) -> None:
    await _install_listing_snapshot_fixture(browser_page, variant="whitespace_label_match")
    snapshot = await read_native_ticket_snapshot(
        browser_page, work_id=WORK_ID, chapter_id=CHAPTER_ID, page_mode="listing"
    )

    assert snapshot.chapter_label == CHAPTER_LABEL


async def test_listing_snapshot_accepts_only_proven_unavailable_defaults(browser_page) -> None:
    await _install_listing_snapshot_fixture(browser_page, variant="unavailable_known_default")
    snapshot = await read_native_ticket_snapshot(
        browser_page, work_id=WORK_ID, chapter_id=CHAPTER_ID, page_mode="listing"
    )

    assert snapshot.is_ticket_available is False
    assert snapshot.is_ticket_available_present is False
    assert snapshot.is_ticket_available_prototype_default is True
    assert snapshot.charge_status == ""
    assert snapshot.charge_status_present is False


@pytest.mark.parametrize(
    "variant",
    [
        "missing_runtime_availability",
        "missing_runtime_data",
        "wrong_work",
        "different_messages_same_values",
        "multiple_heading_messages",
        "duplicate_target",
        "non_target_id_order_mismatch",
        "runtime_point_amount_mismatch",
        "ssr_point_type_conflict",
        "ssr_point_amount_conflict",
        "ssr_label_conflict",
        "row_label_conflict",
        "rental_default_missing",
        "point_type_missing",
        "charge_state_mismatch",
    ],
)
async def test_listing_snapshot_rejects_incomplete_or_contradictory_runtime_data(
    browser_page, variant: str
) -> None:
    await _install_listing_snapshot_fixture(browser_page, variant=variant)

    with pytest.raises(UnknownPageStateError):
        await read_native_ticket_snapshot(
            browser_page, work_id=WORK_ID, chapter_id=CHAPTER_ID, page_mode="listing"
        )


@pytest.mark.parametrize("delay_kind", ["dom_and_runtime", "runtime_only"])
async def test_ticket_listing_readiness_waits_for_delayed_dom_and_runtime(
    browser_page, delay_kind: str
) -> None:
    work_id, chapter_id = "3667", "76588"
    target_url = f"{BASE}/manga/{work_id}"
    native = {
        "page": "/manga/[mangaId]",
        "query": {"mangaId": work_id},
        "props": {"pageProps": {"chapters": [{"chapters": [{"chapterId": chapter_id}]}]}},
    }
    runtime_attach = f"""
      const chapter={{chapterId:{chapter_id}}};
      const webMangaViewerData={{manga:{{mangaId:{work_id}}},chapters:[{{chapters:[chapter]}}]}};
      const heading=document.querySelector('h3');
      heading.__reactFiber$target={{memoizedProps:{{chapter}},
        return:{{memoizedProps:{{webMangaViewerData}},return:null}}}};
      document.querySelector('.Charge_charge__fixture').__reactFiber$charge={{
        memoizedProps:{{webMangaViewerData}},return:null}};
      window.__hydrationComplete=true;
    """
    if delay_kind == "dom_and_runtime":
        body = f"""
          <script>
            window.__ticketClicks=0;
            setTimeout(()=>{{
              const list=document.createElement('div');
              list.className='title_detail_chapters__list__fixture';
              list.innerHTML='<h3 class="Chapter_chapter__name__fixture">Synthetic target</h3>';
              const charge=document.createElement('div');
              charge.className='Charge_charge__fixture';
              const button=document.createElement('button');
              button.textContent='charge control fixture';
              button.addEventListener('click',()=>window.__ticketClicks++);
              charge.append(button);
              document.body.append(list,charge);
              {runtime_attach}
            }},350);
          </script>
        """
    else:
        body = f"""
          <div class="title_detail_chapters__list__fixture">
            <h3 class="Chapter_chapter__name__fixture">Synthetic target</h3>
          </div>
          <div class="Charge_charge__fixture"><button>charge control fixture</button></div>
          <script>
            window.__ticketClicks=0;
            document.querySelector('button').addEventListener('click',()=>window.__ticketClicks++);
            setTimeout(()=>{{{runtime_attach}}},350);
          </script>
        """
    html = f'''<!doctype html><html><head>
      <link rel="canonical" href="{target_url}">
      <script id="__NEXT_DATA__" type="application/json">{json.dumps(native)}</script>
      </head><body>{body}</body></html>'''

    async def listing(route) -> None:
        await route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)

    await browser_page.route(target_url, listing)
    api_requests: list[bool] = []
    browser_page.on(
        "request",
        lambda request: api_requests.append(True)
        if f"{API_HOST}{API_PATH}" in request.url
        else None,
    )
    await browser_page.route(f"https://{API_HOST}{API_PATH}**", lambda route: route.abort())
    await browser_page.goto(target_url, wait_until="commit")
    expected_initial_list_count = 0 if delay_kind == "dom_and_runtime" else 1
    assert (
        await browser_page.locator('div[class*="title_detail_chapters__list__"]').count()
        == expected_initial_list_count
    )

    await ComicFuzDiscoveryAdapter().wait_for_target_row_hydration(
        browser_page, work_id=work_id, chapter_id=chapter_id, timeout_ms=1500
    )

    assert await browser_page.evaluate("window.__hydrationComplete") is True
    assert await browser_page.locator('div[class*="title_detail_chapters__list__"]').count() == 1
    assert await browser_page.evaluate("window.__ticketClicks") == 0
    assert api_requests == []


async def test_ticket_listing_readiness_rejects_runtime_mismatch_before_charge_mount(
    browser_page,
) -> None:
    work_id, chapter_id = "3667", "76588"
    target_url = f"{BASE}/manga/{work_id}"
    native = {
        "page": "/manga/[mangaId]",
        "query": {"mangaId": work_id},
        "props": {"pageProps": {"chapters": [{"chapters": [{"chapterId": chapter_id}]}]}},
    }
    html = f'''<!doctype html><html><head>
      <link rel="canonical" href="{target_url}">
      <script id="__NEXT_DATA__" type="application/json">{json.dumps(native)}</script>
      </head><body>
        <div class="title_detail_chapters__list__fixture">
          <h3 class="Chapter_chapter__name__fixture">Synthetic target</h3>
        </div>
        <script>
          window.__ticketClicks=0;
          const chapter={{chapterId:{chapter_id}}};
          const webMangaViewerData={{manga:{{mangaId:9999}},chapters:[{{chapters:[chapter]}}]}};
          document.querySelector('h3').__reactFiber$target={{memoizedProps:{{chapter}},
            return:{{memoizedProps:{{webMangaViewerData}},return:null}}}};
        </script>
      </body></html>'''

    await browser_page.route(
        target_url,
        lambda route: route.fulfill(status=200, content_type="text/html", body=html),
    )
    api_requests: list[bool] = []
    browser_page.on(
        "request",
        lambda request: api_requests.append(True)
        if f"{API_HOST}{API_PATH}" in request.url
        else None,
    )
    await browser_page.route(f"https://{API_HOST}{API_PATH}**", lambda route: route.abort())
    await browser_page.goto(target_url, wait_until="commit")

    with pytest.raises(DiscoveryIncompleteError, match="runtime work data is incomplete"):
        await ComicFuzDiscoveryAdapter().wait_for_target_row_hydration(
            browser_page, work_id=work_id, chapter_id=chapter_id, timeout_ms=250
        )

    assert await browser_page.evaluate("window.__ticketClicks") == 0
    assert api_requests == []


async def test_ticket_listing_readiness_timeout_does_not_click_or_request(browser_page) -> None:
    work_id, chapter_id = "3667", "76588"
    target_url = f"{BASE}/manga/{work_id}"

    async def listing(route) -> None:
        await route.fulfill(
            status=200,
            content_type="text/html; charset=utf-8",
            body="<!doctype html><html><body><script>window.__ticketClicks=0</script></body></html>",
        )

    await browser_page.route(target_url, listing)
    api_requests: list[bool] = []
    browser_page.on(
        "request",
        lambda request: api_requests.append(True)
        if f"{API_HOST}{API_PATH}" in request.url
        else None,
    )
    await browser_page.route(f"https://{API_HOST}{API_PATH}**", lambda route: route.abort())
    await browser_page.goto(target_url, wait_until="commit")

    with pytest.raises(DiscoveryIncompleteError, match="did not hydrate"):
        await ComicFuzDiscoveryAdapter().wait_for_target_row_hydration(
            browser_page, work_id=work_id, chapter_id=chapter_id, timeout_ms=100
        )

    assert await browser_page.evaluate("window.__ticketClicks") == 0
    assert api_requests == []


async def test_ticket_listing_readiness_rejects_duplicate_container_immediately(browser_page) -> None:
    work_id, chapter_id = "3667", "76588"
    target_url = f"{BASE}/manga/{work_id}"

    async def listing(route) -> None:
        await route.fulfill(
            status=200,
            content_type="text/html; charset=utf-8",
            body="""<!doctype html><html><body>
              <div class="title_detail_chapters__list__one"></div>
              <div class="title_detail_chapters__list__two"></div>
              <script>window.__ticketClicks=0</script>
            </body></html>""",
        )

    await browser_page.route(target_url, listing)
    api_requests: list[bool] = []
    browser_page.on(
        "request",
        lambda request: api_requests.append(True)
        if f"{API_HOST}{API_PATH}" in request.url
        else None,
    )
    await browser_page.route(f"https://{API_HOST}{API_PATH}**", lambda route: route.abort())
    await browser_page.goto(target_url, wait_until="commit")

    with pytest.raises(DiscoveryIncompleteError, match="chapter list container is ambiguous"):
        await ComicFuzDiscoveryAdapter().wait_for_target_row_hydration(
            browser_page, work_id=work_id, chapter_id=chapter_id, timeout_ms=1000
        )

    assert await browser_page.evaluate("window.__ticketClicks") == 0
    assert api_requests == []

async def test_entry_only_page_does_not_attach_image_response_observer(browser_page) -> None:
    adapter = ComicFuzAdapter()
    seen_responses = []

    async def observe_response(response) -> None:
        seen_responses.append(response.url)

    adapter._handle_source_response = observe_response
    image_url = f"{BASE}/synthetic-page.png"

    async def listing(route) -> None:
        await route.fulfill(
            status=200,
            content_type="text/html; charset=utf-8",
            body=f'<img src="{image_url}" width="1" height="1">',
        )

    async def image(route) -> None:
        await route.fulfill(status=200, content_type="image/png", body=b"not-an-image")

    await browser_page.route(f"{BASE}/manga/{WORK_ID}", listing)
    await browser_page.route(image_url, image)
    await adapter.prepare_entry_only_page(browser_page)
    await browser_page.goto(f"{BASE}/manga/{WORK_ID}")
    await browser_page.wait_for_timeout(50)

    assert seen_responses == []
    assert adapter._bound_page is browser_page
