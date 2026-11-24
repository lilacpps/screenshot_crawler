from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest

from screenshot_crawler.core.errors import UnknownPageStateError
from screenshot_crawler.site_adapters.comicfuz import work_ticket as work_ticket_module
from screenshot_crawler.site_adapters.comicfuz.adapter import ComicFuzAdapter
from screenshot_crawler.site_adapters.comicfuz.work_ticket import (
    API_HOST,
    API_PATH,
    API_ROUTE_PATTERN,
    TICKET_AVAILABLE_LABELS,
    ComicFuzTicketEntry,
    ComicFuzTicketNotAttemptedError,
    NativeTicketSnapshot,
    read_native_ticket_snapshot,
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


def _listing_html() -> str:
    return f"""<!doctype html><html><body>
      <div class="Charge_charge__charged__fixture">{AVAILABLE}
        <img alt="\u30c1\u30e3\u30fc\u30b8" src="/assets/manga_detail/charged.svg">
      </div>
      <section id="ticket-modal"><h2>{CHAPTER_LABEL}</h2><p>{CTA}</p>
        <span>1</span><button>{APP}</button><button>{COMMENTS}</button>
        <button>{CANCEL}</button></section>
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
        await route.fulfill(status=200, content_type="text/html; charset=utf-8", body=_listing_html())

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
          const cta=[...document.querySelectorAll('p')].find(e=>e.innerText.trim()===chargeLabel);
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
    await page.locator("p").evaluate("element => element.remove()")
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


async def test_listing_snapshot_uses_target_react_chapter_and_charge_props(browser_page) -> None:
    native = {
        "page": "/manga/[mangaId]",
        "query": {"mangaId": WORK_ID},
        "props": {"pageProps": {"chapters": [{"chapters": [
            {"chapterId": CHAPTER_ID, "chapterMainName": CHAPTER_LABEL}
        ]}]}},
    }
    html = f"""<!doctype html><html><body>
      <script id="__NEXT_DATA__" type="application/json">{json.dumps(native)}</script>
      <div class="title_detail_chapters__list__fixture"><div class="Chapter_chapter__row__fixture">
        <div><h3 class="Chapter_chapter__name__fixture">{CHAPTER_LABEL}</h3></div>
      </div></div>
      <div class="Charge_charge__charged__fixture">{AVAILABLE}</div>
    </body></html>"""

    async def listing(route) -> None:
        await route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)

    await browser_page.route(f"{BASE}/manga/{WORK_ID}**", listing)
    await browser_page.goto(f"{BASE}/manga/{WORK_ID}?position=thumbnail")
    await browser_page.evaluate(
        """({chapterId, chapterLabel, chargeStatus}) => {
          const chapter=Object.assign(Object.create({endOfRentalPeriod:''}),{
            chapterId,chapterMainName:chapterLabel,pointConsumption:{type:0,amount:30},isRead:true
          });
          document.querySelector('h3').__reactFiber$target={memoizedProps:{chapter},return:null};
          document.querySelector('.Charge_charge__charged__fixture').__reactFiber$charge={
            memoizedProps:{isChargeNeeded:true,isTicketAvailable:true,chargeStatus},return:null
          };
        }""",
        {"chapterId": CHAPTER_ID, "chapterLabel": CHAPTER_LABEL, "chargeStatus": AVAILABLE},
    )

    snapshot = await read_native_ticket_snapshot(
        browser_page,
        work_id=WORK_ID,
        chapter_id=CHAPTER_ID,
        page_mode="listing",
    )

    assert snapshot.work_id == WORK_ID
    assert snapshot.chapter_id == CHAPTER_ID
    assert snapshot.point_type == 0 and snapshot.point_amount == 30
    assert snapshot.is_read is True
    assert snapshot.rental_value == "" and snapshot.rental_present is False
    assert snapshot.is_charge_needed and snapshot.is_ticket_available
    assert snapshot.charge_status == AVAILABLE


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
