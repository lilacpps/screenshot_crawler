"""Bounded ComicFUZ Work Ticket entry evidence and state transitions."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlparse

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from screenshot_crawler.catalog.service import JST
from screenshot_crawler.core.errors import AccessResourceUnavailableError, UnknownPageStateError
from screenshot_crawler.site_adapters.base import (
    AccessAttemptObservation,
    AccessConsumption,
    ConfirmedAccessGrant,
)

SITE = "comicfuz"
RESOURCE = "work_ticket"
API_HOST = "api.comic-fuz.com"
API_PATH = "/v1/web_manga_viewer_2"
API_ROUTE_PATTERN = f"**://*{API_HOST}*/{API_PATH.lstrip('/')}*"
ACTION_TIMEOUT_MS = 15_000
RESPONSE_BODY_TIMEOUT_MS = 2_000
MAX_VIEWER_RESPONSE_BYTES = 2 * 1024 * 1024
NO_ATTEMPT_STOP_REASON = "comicfuz_work_ticket_not_attempted"
TICKET_AVAILABLE_LABELS = {"\u30c1\u30e3\u30fc\u30b8\u5b8c\u4e86!"}
TICKET_RECOVERY_LABELS = {"0\u6642\u306b\u56de\u5fa9!"}
TICKET_CTA_LABEL = "\u30c1\u30e3\u30fc\u30b8\u3067\u8aad\u3080"
TICKET_CANCEL_LABEL = "\u30ad\u30e3\u30f3\u30bb\u30eb"
TICKET_APP_LABEL = "\u30a2\u30d7\u30ea\u306f\u3053\u3061\u3089"
TICKET_COMMENTS_LABEL = "\u30b3\u30e1\u30f3\u30c8\u4e00\u89a7\u3078"
TICKET_CHARGE_ALT = "\u30c1\u30e3\u30fc\u30b8"


class ComicFuzTicketNotAttemptedError(AccessResourceUnavailableError):
    """A typed, positive no-action result safe to reconsider on a later plan."""

    stop_reason = NO_ATTEMPT_STOP_REASON

    def __init__(self, reason: str) -> None:
        super().__init__(reason, stop_resource_pass=False)


def is_canonical_viewer_api_request(url: str, method: str) -> bool:
    try:
        parsed = urlparse(url)
        return (
            parsed.scheme.lower() == "https"
            and parsed.hostname == API_HOST
            and parsed.port is None
            and parsed.username is None
            and parsed.password is None
            and parsed.path == API_PATH
            and not parsed.query
            and not parsed.fragment
            and method.upper() == "POST"
        )
    except (AttributeError, ValueError):
        return False


async def read_bounded_viewer_response_body(response: object, *, timeout: float) -> bytes:
    """Read a small native viewer response within the current action budget."""

    headers = getattr(response, "headers", None)
    if not isinstance(headers, Mapping):
        raise TypeError("ComicFUZ viewer response headers are unavailable")
    content_length = headers.get("content-length")
    if content_length is not None and (
        not isinstance(content_length, str)
        or not content_length.isascii()
        or not content_length.isdecimal()
        or int(content_length) > MAX_VIEWER_RESPONSE_BYTES
    ):
        raise ValueError("ComicFUZ viewer response exceeds its declared size limit")
    body = await asyncio.wait_for(response.body(), timeout=timeout)  # type: ignore[attr-defined]
    if not isinstance(body, bytes) or len(body) > MAX_VIEWER_RESPONSE_BYTES:
        raise ValueError("ComicFUZ viewer response exceeds its body size limit")
    return body


@dataclass(frozen=True, slots=True)
class NativeTicketSnapshot:
    work_id: str
    chapter_id: str
    chapter_label: str
    is_charge_needed: bool
    is_charge_needed_present: bool
    is_ticket_available: bool
    is_ticket_available_present: bool
    is_ticket_available_in: bool
    is_ticket_available_prototype_default: bool
    charge_status: str
    charge_status_present: bool
    point_type: int
    point_amount: int
    is_read: bool
    rental_value: str
    rental_present: bool
    rental_label: str
    viewer_chapter_id: str


@dataclass(frozen=True, slots=True)
class TicketEntryProof:
    request_started_at: datetime
    confirmed_at: datetime
    access_granted_until: datetime


@dataclass(frozen=True, slots=True)
class DecodedViewerRequest:
    chapter_id: int
    use_ticket: bool
    point_free: int
    point_paid: int


@dataclass(frozen=True, slots=True)
class DecodedViewerResponse:
    manga_id: int
    chapter_id: int
    ticket_available: bool
    ticket_available_present: bool
    is_charge_needed: bool
    is_charge_needed_present: bool
    charge_status: str
    charge_status_present: bool
    rental_value: str
    rental_present: bool
    point_type: int | None
    point_amount: int | None


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while offset < len(data) and shift < 70:
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7
    raise ValueError("malformed protobuf varint")


def _protobuf_fields(data: bytes, *, maximum_size: int = 8_192):
    if not isinstance(data, bytes) or len(data) > maximum_size:
        raise ValueError("protobuf body is unavailable or oversized")
    offset = 0
    while offset < len(data):
        tag, offset = _read_varint(data, offset)
        field_number, wire_type = tag >> 3, tag & 7
        if field_number <= 0 or wire_type in {3, 4, 6, 7}:
            raise ValueError("protobuf field tag is unsupported")
        if wire_type == 0:
            value, offset = _read_varint(data, offset)
        elif wire_type == 1:
            if offset + 8 > len(data):
                raise ValueError("truncated protobuf fixed64")
            value = data[offset : offset + 8]
            offset += 8
        elif wire_type == 2:
            length, offset = _read_varint(data, offset)
            if length > len(data) - offset:
                raise ValueError("truncated protobuf length-delimited field")
            value = data[offset : offset + length]
            offset += length
        else:  # wire type 5
            if offset + 4 > len(data):
                raise ValueError("truncated protobuf fixed32")
            value = data[offset : offset + 4]
            offset += 4
        yield field_number, wire_type, value


def _strict_message_fields(data: bytes, schema: Mapping[int, int]) -> dict[int, object]:
    values: dict[int, object] = {}
    for field_number, wire_type, value in _protobuf_fields(data):
        if field_number not in schema or schema[field_number] != wire_type:
            raise ValueError("protobuf message contains an unknown or mistyped field")
        if field_number in values:
            raise ValueError("protobuf message repeats a scalar field")
        values[field_number] = value
    return values


def decode_viewer_request(data: bytes) -> DecodedViewerRequest:
    """Strictly decode the observed WebMangaViewer2Request without secrets."""

    # Generated from WebMangaViewer2Request: deviceInfo=1, useTicket=2,
    # consumePoint=3, chapterId=4, chapterArgument=5. The latter is not
    # accepted because this controller must bind an exact chapter ID.
    message = _strict_message_fields(data, {1: 2, 2: 0, 3: 2, 4: 0})
    chapter_id = message.get(4)
    use_ticket = message.get(2, 0)
    point_bytes = message.get(3, b"")
    if (
        1 not in message
        or type(chapter_id) is not int
        or type(use_ticket) is not int
        or use_ticket not in {0, 1}
        or not isinstance(point_bytes, bytes)
    ):
        raise ValueError("ComicFUZ viewer request lacks required native fields")
    device = _strict_message_fields(message[1], {1: 2, 2: 2, 3: 0, 4: 2, 5: 0, 6: 0})
    device_type = device.get(3)
    if type(device_type) is not int or device_type != 2:
        raise ValueError("ComicFUZ viewer request is not from the observed browser device")
    points = _strict_message_fields(point_bytes, {1: 0, 2: 0})
    free, paid = points.get(1, 0), points.get(2, 0)
    if type(free) is not int or type(paid) is not int:
        raise ValueError("ComicFUZ viewer request point fields are malformed")
    return DecodedViewerRequest(
        chapter_id=chapter_id,
        use_ticket=use_ticket == 1,
        point_free=free,
        point_paid=paid,
    )


def decode_viewer_response(
    data: bytes, *, work_id: str, chapter_id: str
) -> DecodedViewerResponse:
    """Decode only the exact WebMangaViewer2Response access metadata.

    Generated first-party code maps this response to manga, current chapter,
    grouped chapters, and viewer data. Page image payloads/URLs are skipped in
    memory and never returned or logged.
    """

    response: dict[int, object] = {}
    groups: list[bytes] = []
    for field_number, wire_type, value in _protobuf_fields(
        data, maximum_size=2 * 1024 * 1024
    ):
        expected = {2: 2, 5: 2, 11: 2, 12: 0}.get(field_number)
        if expected is not None and wire_type != expected:
            raise ValueError("ComicFUZ viewer response contains a mistyped access field")
        if field_number == 5:
            if not isinstance(value, bytes):
                raise ValueError("ComicFUZ viewer response chapter group is malformed")
            groups.append(value)
            if len(groups) > 10_000:
                raise ValueError("ComicFUZ viewer response has too many chapter groups")
        elif field_number in {2, 11, 12}:
            if field_number in response:
                raise ValueError("ComicFUZ viewer response repeats an access field")
            response[field_number] = value

    manga_bytes = response.get(11)
    response_chapter_id = response.get(12)
    target_chapter_id = int(chapter_id)
    if (
        not isinstance(manga_bytes, bytes)
        or type(response_chapter_id) is not int
        or response_chapter_id <= 0
        or response_chapter_id > 0xFFFF_FFFF
        or response_chapter_id != target_chapter_id
    ):
        raise ValueError("ComicFUZ viewer response lacks exact work/chapter metadata")

    manga = _selected_fields(manga_bytes, {1: 0, 12: 0, 13: 0, 18: 2})
    manga_id = manga.get(1)
    ticket_available = manga.get(12, 0)
    is_charge_needed = manga.get(13, 0)
    charge_bytes = manga.get(18, b"")
    try:
        charge_status = charge_bytes.decode("utf-8") if isinstance(charge_bytes, bytes) else None
    except UnicodeDecodeError as exc:
        raise ValueError("ComicFUZ viewer response charge status is malformed") from exc
    if (
        type(manga_id) is not int
        or manga_id <= 0
        or manga_id > 0xFFFF_FFFF
        or manga_id != int(work_id)
        or type(ticket_available) is not int
        or ticket_available not in {0, 1}
        or type(is_charge_needed) is not int
        or is_charge_needed not in {0, 1}
        or not isinstance(charge_status, str)
    ):
        raise ValueError("ComicFUZ viewer response manga metadata is incomplete")

    matching_chapters: list[dict[int, object]] = []
    for group in groups:
        group_fields = _selected_fields(group, {2: 2}, repeated={2})
        chapter_messages = group_fields.get(2, [])
        if not isinstance(chapter_messages, list):
            raise TypeError("ComicFUZ viewer response chapters are malformed")
        for chapter_message in chapter_messages:
            chapter_fields = _selected_fields(chapter_message, {1: 0, 5: 2, 10: 2})
            if chapter_fields.get(1) == response_chapter_id:
                matching_chapters.append(chapter_fields)
    if len(matching_chapters) != 1:
        raise ValueError("ComicFUZ viewer response target chapter is missing or ambiguous")

    chapter = matching_chapters[0]
    rental_bytes = chapter.get(10, b"")
    point_bytes = chapter.get(5)
    try:
        rental_value = rental_bytes.decode("utf-8") if isinstance(rental_bytes, bytes) else None
    except UnicodeDecodeError as exc:
        raise ValueError(
            "ComicFUZ viewer response target rental metadata is malformed"
        ) from exc
    if not isinstance(rental_value, str):
        raise TypeError("ComicFUZ viewer response target rental metadata is malformed")
    point_type: int | None = None
    point_amount: int | None = None
    if point_bytes is not None:
        if not isinstance(point_bytes, bytes):
            raise ValueError("ComicFUZ viewer response target point metadata is malformed")
        point = _selected_fields(point_bytes, {1: 0, 2: 0})
        point_type = point.get(1, 0)
        point_amount = point.get(2, 0)
        if type(point_type) is not int or type(point_amount) is not int:
            raise ValueError("ComicFUZ viewer response target point metadata is malformed")

    return DecodedViewerResponse(
        manga_id=manga_id,
        chapter_id=response_chapter_id,
        ticket_available=ticket_available == 1,
        ticket_available_present=12 in manga,
        is_charge_needed=is_charge_needed == 1,
        is_charge_needed_present=13 in manga,
        charge_status=charge_status,
        charge_status_present=18 in manga,
        rental_value=rental_value,
        rental_present=10 in chapter,
        point_type=point_type,
        point_amount=point_amount,
    )


def _selected_fields(
    data: bytes,
    schema: Mapping[int, int],
    *,
    repeated: set[int] | None = None,
) -> dict[int, object]:
    """Extract allowlisted native fields, safely skipping other wire fields."""

    values: dict[int, object] = {}
    repeated_fields = repeated or set()
    for field_number, wire_type, value in _protobuf_fields(
        data, maximum_size=2 * 1024 * 1024
    ):
        if field_number not in schema:
            continue
        if schema[field_number] != wire_type:
            raise ValueError("ComicFUZ protobuf access metadata has a mistyped field")
        if field_number in repeated_fields:
            values.setdefault(field_number, []).append(value)
        elif field_number in values:
            raise ValueError("ComicFUZ protobuf access metadata repeats a scalar")
        else:
            values[field_number] = value
    return values


def is_exact_ticket_request(data: bytes, *, chapter_id: str) -> bool:
    try:
        decoded = decode_viewer_request(data)
        return (
            decoded.chapter_id == int(chapter_id)
            and decoded.use_ticket
            and decoded.point_free == 0
            and decoded.point_paid == 0
        )
    except (ValueError, OverflowError):
        return False


def is_zero_cost_direct_request(data: bytes, *, chapter_id: str) -> bool:
    try:
        decoded = decode_viewer_request(data)
        return (
            decoded.chapter_id == int(chapter_id)
            and not decoded.use_ticket
            and decoded.point_free == 0
            and decoded.point_paid == 0
        )
    except (ValueError, OverflowError):
        return False


def parse_rental_expiry(value: object) -> datetime | None:
    """Parse only timezone-bearing native ISO timestamps; never invent a zone."""

    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    try:
        parsed = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
    except ValueError as exc:
        raise UnknownPageStateError(
            "ComicFUZ rental expiry has an unsupported native format"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise UnknownPageStateError("ComicFUZ rental expiry has no explicit timezone")
    return parsed


def is_ticket_viewer_url(url: str, *, chapter_id: str) -> bool:
    try:
        parsed = urlparse(url)
        return bool(
            parsed.scheme.lower() == "https"
            and parsed.hostname == "comic-fuz.com"
            and parsed.port is None
            and parsed.username is None
            and parsed.password is None
            and parsed.path == f"/manga/viewer/{chapter_id}"
            and parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
            == [("ticket", "true")]
            and not parsed.fragment
            and not parsed.params
        )
    except ValueError:
        return False


async def read_native_ticket_snapshot(
    page: Page,
    *,
    work_id: str,
    chapter_id: str,
    page_mode: str = "listing",
) -> NativeTicketSnapshot:
    """Read an allowlisted projection from hydrated first-party React data."""

    if page_mode == "listing":
        parsed_page = urlparse(page.url)
        query = parse_qsl(parsed_page.query, keep_blank_values=True, strict_parsing=True)
        if (
            parsed_page.scheme.lower() != "https"
            or parsed_page.hostname != "comic-fuz.com"
            or parsed_page.port is not None
            or parsed_page.username is not None
            or parsed_page.password is not None
            or parsed_page.path != f"/manga/{work_id}"
            or parsed_page.fragment
            or parsed_page.params
            or (query and query != [("position", "thumbnail")])
        ):
            raise UnknownPageStateError("ComicFUZ ticket snapshot is outside the target work page")
    if page_mode == "viewer":
        canonical_viewer = f"https://comic-fuz.com/manga/viewer/{chapter_id}"
        if page.url != canonical_viewer and not is_ticket_viewer_url(
            page.url, chapter_id=chapter_id
        ):
            raise UnknownPageStateError(
                "ComicFUZ ticket snapshot is outside the target viewer route"
            )

    value = await page.evaluate(
        r"""({workId, chapterId, pageMode}) => {
          const fiberOf = element => {
            const key = Object.keys(element || {}).find(name => name.startsWith('__reactFiber$'));
            return key ? element[key] : null;
          };
          const next = JSON.parse(document.querySelector('#__NEXT_DATA__')?.textContent || 'null');
          const nextChapters = (next?.props?.pageProps?.chapters || [])
            .flatMap(group => Array.isArray(group?.chapters) ? group.chapters : []);
          const targetIndex = nextChapters.findIndex(chapter =>
            String(chapter?.chapterId ?? '') === chapterId);
          let chapter = null;
          let manga = null;
          let mangaId = '';
          let viewerChapterId = '';
          let charge = null;
          let row = null;
          let headingElements = [];
          let rentalLabels = [];
          if (pageMode === 'listing') {
            const headingList = document.querySelector('div[class*="title_detail_chapters__list__"]');
            headingElements = headingList
              ? [...headingList.querySelectorAll('h3[class*="Chapter_chapter__name__"]')] : [];
            const heading = targetIndex >= 0 ? headingElements[targetIndex] : null;
            row = heading?.parentElement?.parentElement || null;
            rentalLabels = row
              ? [...row.querySelectorAll('p[class*="Chapter_chapter__rentalPeriod__"]')]
                  .filter(element => element.getClientRects().length > 0)
                  .map(element => element.innerText.trim()) : [];
            let fiber = fiberOf(heading);
            const chapterCandidates = [];
            for (let depth = 0; fiber && depth < 35; depth++, fiber = fiber.return) {
              const props = fiber.memoizedProps || {};
              const candidate = props.chapter;
              if (candidate && typeof candidate === 'object'
                  && String(candidate.chapterId ?? '') === chapterId) {
                if (!chapterCandidates.includes(candidate)) chapterCandidates.push(candidate);
              }
            }
            if (chapterCandidates.length === 1) chapter = chapterCandidates[0];
            const visible = element => !!element?.getClientRects().length
              && getComputedStyle(element).visibility === 'visible'
              && getComputedStyle(element).display !== 'none';
            const badges = [...document.querySelectorAll('div[class*="Charge_charge__"]')]
              .filter(visible);
            const chargeProps = [];
            for (const badge of badges) {
              let node = fiberOf(badge);
              for (let depth = 0; node && depth < 20; depth++, node = node.return) {
                const props = node.memoizedProps || {};
                if (Object.hasOwn(props,'isChargeNeeded')
                    && Object.hasOwn(props,'isTicketAvailable')
                    && Object.hasOwn(props,'chargeStatus')) {
                  chargeProps.push(props);
                  break;
                }
              }
            }
            if (chargeProps.length === 1) charge = chargeProps[0];
            manga = charge;
            mangaId = String(next?.query?.mangaId ?? '');
          } else {
            const webData = [];
            for (const image of document.querySelectorAll('img[class*="G54Y0W_page"]')) {
              let fiber = fiberOf(image);
              for (let depth = 0; fiber && depth < 35; depth++, fiber = fiber.return) {
                const data = fiber.memoizedProps?.webMangaViewerData;
                if (data && typeof data === 'object' && data.manga
                    && String(data.manga.mangaId ?? '') === workId) {
                  if (!webData.includes(data)) webData.push(data);
                  break;
                }
              }
            }
            if (webData.length !== 1) return {state:'viewer_work_data_missing_or_ambiguous'};
            const web = webData[0];
            viewerChapterId = String(web.chapterId ?? '');
            const groups = Array.isArray(web.chapters) ? web.chapters : [];
            const chapters = groups.flatMap(group => Array.isArray(group?.chapters) ? group.chapters : []);
            const selected = chapters.filter(candidate => String(candidate?.chapterId ?? '') === chapterId);
            if (selected.length !== 1) return {state:'viewer_target_chapter_missing_or_ambiguous'};
            chapter = selected[0];
            manga = web.manga;
            mangaId = String(manga.mangaId ?? '');
          }
          if (!chapter || typeof chapter !== 'object' || !manga || typeof manga !== 'object')
            return {state:'native_target_props_missing'};
          const point = chapter.pointConsumption;
          const ticketDescriptor = Object.getOwnPropertyDescriptor(
            Object.getPrototypeOf(manga) || {}, 'isTicketAvailable');
          return {
            state:'ok',
            mangaId,
            isChargeNeeded:manga.isChargeNeeded,
            isChargeNeededPresent:Object.hasOwn(manga,'isChargeNeeded'),
            isTicketAvailable:manga.isTicketAvailable,
            isTicketAvailablePresent:Object.hasOwn(manga,'isTicketAvailable'),
            isTicketAvailableIn:'isTicketAvailable' in manga,
            isTicketAvailablePrototypeDefault:!!ticketDescriptor
              &&Object.hasOwn(ticketDescriptor,'value')
              &&typeof ticketDescriptor.value==='boolean'
              &&ticketDescriptor.value===false,
            chargeStatus:manga.chargeStatus,
            chargeStatusPresent:Object.hasOwn(manga,'chargeStatus'),
            chapterId:String(chapter.chapterId ?? ''),
            chapterLabel:typeof chapter.chapterMainName === 'string' ? chapter.chapterMainName : '',
            pointType:point?.type,
            pointAmount:point?.amount,
            isRead:chapter.isRead,
            rentalValue:chapter.endOfRentalPeriod,
            rentalPresent:Object.hasOwn(chapter,'endOfRentalPeriod'),
            rentalLabels,
            viewerChapterId,
            nextPage:next?.page,
            currentPath:location.pathname,
            currentSearch:location.search,
            nextWorkId:String(next?.query?.mangaId ?? ''),
            nativeChapterCount:nextChapters.length,
            domHeadingCount:headingElements.length,
            targetIndex
          };
        }""",
        {"workId": work_id, "chapterId": chapter_id, "pageMode": page_mode},
    )
    if not isinstance(value, Mapping) or value.get("state") != "ok":
        state = value.get("state") if isinstance(value, Mapping) else "malformed_projection"
        raise UnknownPageStateError(
            f"ComicFUZ hydrated ticket state is missing or ambiguous ({state})"
        )
    if (
        value.get("mangaId") != work_id
        or value.get("chapterId") != chapter_id
        or page_mode not in {"listing", "viewer"}
        or (
            page_mode == "listing"
            and (
                value.get("nextPage") != "/manga/[mangaId]"
                or value.get("nextWorkId") != work_id
                or value.get("currentPath") != f"/manga/{work_id}"
            )
        )
        or (
            page_mode == "viewer"
            and (
                value.get("currentPath") != f"/manga/viewer/{chapter_id}"
                or value.get("viewerChapterId") != chapter_id
                or value.get("currentSearch") not in {"", "?ticket=true"}
            )
        )
        or (page_mode == "listing" and type(value.get("targetIndex")) is not int)
        or (page_mode == "listing" and value.get("nativeChapterCount") != value.get("domHeadingCount"))
        or (page_mode == "listing" and value.get("targetIndex") < 0)
        or not isinstance(value.get("rentalLabels"), list)
    ):
        raise UnknownPageStateError("ComicFUZ ticket snapshot identity does not match the target")
    point_type, point_amount = value.get("pointType"), value.get("pointAmount")
    is_read = value.get("isRead")
    rental_value = value.get("rentalValue")
    charge_status = value.get("chargeStatus")
    if (
        type(point_type) is not int
        or type(point_amount) is not int
        or type(is_read) is not bool
        or type(value.get("isChargeNeeded")) is not bool
        or type(value.get("isTicketAvailable")) is not bool
        or value.get("isChargeNeededPresent") is not True
        or value.get("chargeStatusPresent") is not True
        or type(value.get("isTicketAvailablePresent")) is not bool
        or type(value.get("isTicketAvailableIn")) is not bool
        or type(value.get("isTicketAvailablePrototypeDefault")) is not bool
        or (
            page_mode == "listing"
            and value.get("isTicketAvailablePresent") is not True
        )
        or (
            page_mode == "viewer"
            and value.get("isTicketAvailablePresent") is not True
            and not (
                value.get("isTicketAvailableIn") is True
                and value.get("isTicketAvailablePrototypeDefault") is True
            )
        )
        or not isinstance(rental_value, str)
        or not isinstance(charge_status, str)
        or len(value["rentalLabels"]) > 1
        or (
            page_mode == "listing"
            and value["rentalLabels"]
            and value["rentalLabels"][0] != rental_value
        )
        or (page_mode == "listing" and rental_value and not value["rentalLabels"])
    ):
        raise UnknownPageStateError("ComicFUZ ticket native fields are malformed or contradictory")
    return NativeTicketSnapshot(
        work_id=work_id,
        chapter_id=chapter_id,
        chapter_label=str(value.get("chapterLabel") or ""),
        is_charge_needed=value.get("isChargeNeeded") is True,
        is_charge_needed_present=value.get("isChargeNeededPresent") is True,
        is_ticket_available=value.get("isTicketAvailable") is True,
        is_ticket_available_present=value.get("isTicketAvailablePresent") is True,
        is_ticket_available_in=value.get("isTicketAvailableIn") is True,
        is_ticket_available_prototype_default=value.get(
            "isTicketAvailablePrototypeDefault"
        )
        is True,
        charge_status=charge_status,
        charge_status_present=value.get("chargeStatusPresent") is True,
        point_type=point_type,
        point_amount=point_amount,
        is_read=is_read,
        rental_value=rental_value,
        rental_present=value.get("rentalPresent") is True,
        rental_label=value["rentalLabels"][0] if value["rentalLabels"] else "",
        viewer_chapter_id=str(value.get("viewerChapterId") or ""),
    )


async def read_work_ticket_badge(page: Page) -> dict[str, object]:
    """Read the one visible charged badge; selectors stay inside ComicFUZ."""

    value = await page.evaluate(
        r"""() => {
          const visible = element => {
            if (!element || !element.getClientRects().length) return false;
            const style=getComputedStyle(element);
            return !element.hidden && style.display!=='none' && style.visibility==='visible'
              && Number(style.opacity)!==0;
          };
          const all=[...document.querySelectorAll('div[class*="Charge_charge__"]')].filter(visible);
          return {count:all.length,items:all.map(element=>({
            className:typeof element.className==='string'?element.className:'',
            text:element.innerText.trim(),
            imagePath:(()=>{try{return new URL(element.querySelector('img')?.currentSrc
              || element.querySelector('img')?.src || '',location.href).pathname}catch(_){return ''}})(),
            imageAlt:element.querySelector('img')?.alt || ''
          }))};
        }"""
    )
    if not isinstance(value, dict):
        raise UnknownPageStateError("ComicFUZ charged badge is unavailable")
    return value


async def read_ticket_modal(page: Page, *, chapter_label: str) -> dict[str, object]:
    """Require one visible target-bound Work Ticket modal action before attempt."""

    value = await page.evaluate(
        r"""({chapterLabel, chargeLabel, cancelLabel, appLabel, commentsLabel}) => {
          const visible = element => {
            if (!element || !element.getClientRects().length) return false;
            for(let node=element;node;node=node.parentElement){
              const style=getComputedStyle(node);
              if(node.hidden||style.display==='none'||style.visibility==='hidden'
                ||style.visibility==='collapse'||Number(style.opacity)===0)return false;
            }
            return true;
          };
          const norm=value=>String(value||'').trim().replace(/\s+/g,' ');
          const exact=[...document.querySelectorAll('*')]
            .filter(element=>visible(element)&&norm(element.innerText)===chargeLabel);
          const ctas=exact.filter(element=>![...element.children]
            .some(child=>norm(child.innerText)===chargeLabel));
          if(ctas.length!==1)return {ctaCount:ctas.length};
          const cta=ctas[0];
          let modal=null;
          for(let node=cta,depth=0;node&&depth<10;node=node.parentElement,depth++){
            const text=norm(node.innerText);
            const headings=[...node.querySelectorAll('h1,h2,h3,h4')]
              .filter(visible).map(element=>norm(element.innerText));
            if(headings.includes(chapterLabel)&&text.includes(cancelLabel)){modal=node;break;}
          }
          if(!modal)return {ctaCount:1,modal:false};
          const leafOne=[...modal.querySelectorAll('*')].filter(element=>
            visible(element)&&element.children.length===0&&norm(element.innerText)==='1').length;
          const otherAccess=[...modal.querySelectorAll('a,button,[role="button"]')].filter(element=>
            visible(element)&&!element.contains(cta)&&!cta.contains(element)
              &&![appLabel,commentsLabel,cancelLabel]
              .includes(norm(element.innerText)));
          return {ctaCount:1,modal:true,tag:cta.tagName,chapterTitleMatch:true,
            ticketCountOne:leafOne===1,otherAccessCount:otherAccess.length,
            disabled:!!cta.disabled||cta.getAttribute('aria-disabled')==='true'
              ||!!cta.closest('button[disabled],[aria-disabled="true"]'),
            ctaText:norm(cta.innerText)};
        }""",
        {
            "chapterLabel": chapter_label,
            "chargeLabel": TICKET_CTA_LABEL,
            "cancelLabel": TICKET_CANCEL_LABEL,
            "appLabel": TICKET_APP_LABEL,
            "commentsLabel": TICKET_COMMENTS_LABEL,
        },
    )
    if not isinstance(value, dict):
        raise UnknownPageStateError("ComicFUZ ticket modal could not be read")
    return value


class ComicFuzTicketEntry:
    """One-click, same-Page, fail-closed Work Ticket controller."""

    def __init__(self, *, work_id: str, chapter_id: str, external_id: str) -> None:
        self.work_id = work_id
        self.chapter_id = chapter_id
        self.external_id = external_id
        self.attempt_latched = False
        self._terminal_attempt_reported = False
        self.consumption = AccessConsumption()
        self.pre_snapshot: NativeTicketSnapshot | None = None
        self.proof: TicketEntryProof | None = None

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    async def _before_ticket_request_forward(self) -> None:
        """Yield once so cancellation/terminal state is visible before POST forwarding."""

        await asyncio.sleep(0)

    async def _mark_no_action(
        self,
        reporter: Callable[[AccessAttemptObservation], None],
        reason: str,
    ) -> None:
        reporter(
            AccessAttemptObservation(
                site=SITE,
                external_id=self.external_id,
                resource=RESOURCE,
                resource_kind="work_ticket",
                status="not_attempted",
                observed_at=self._now(),
                reason=reason,
            )
        )
        self._terminal_attempt_reported = True
        raise ComicFuzTicketNotAttemptedError(reason)

    async def _mark_unknown(
        self,
        reporter: Callable[[AccessAttemptObservation], None],
        reason: str,
        *,
        cause: BaseException | None = None,
    ) -> None:
        if not self.consumption.consumed:
            try:
                reporter(
                    AccessAttemptObservation(
                        site=SITE,
                        external_id=self.external_id,
                        resource=RESOURCE,
                        resource_kind="work_ticket",
                        status="unknown",
                        observed_at=self._now(),
                        reason=reason,
                    )
                )
            except Exception:  # noqa: BLE001, S110 - preserve the original unknown outcome if its sink fails
                pass
        self._terminal_attempt_reported = True
        if isinstance(cause, (KeyboardInterrupt, asyncio.CancelledError)):
            raise cause
        error = UnknownPageStateError(
            f"ComicFUZ Work Ticket result is unknown ({reason}); retry is prohibited"
        )
        if cause is not None:
            raise error from cause
        raise error

    async def enter(
        self,
        page: Page,
        *,
        chapter_label: str,
        native_state: NativeTicketSnapshot,
        row_access_mode: str,
        attempt_reporter: Callable[[AccessAttemptObservation], None],
        grant_reporter: Callable[[ConfirmedAccessGrant], None],
        click: Callable[[], Awaitable[object]],
    ) -> TicketEntryProof:
        """Enter only through a fresh target-bound native ticket modal and exact CTA."""

        self.pre_snapshot = native_state
        if self.attempt_latched:
            raise UnknownPageStateError(
                "ComicFUZ Work Ticket action is already latched; re-entry is prohibited"
            )
        if row_access_mode != "quota":
            await self._mark_no_action(attempt_reporter, f"target_access_{row_access_mode}")
        if not (
            native_state.work_id == self.work_id
            and native_state.chapter_id == self.chapter_id
            and native_state.chapter_label == chapter_label
            and native_state.point_type == 0
            and native_state.point_amount > 0
        ):
            raise UnknownPageStateError("ComicFUZ native chapter is not a bound Work Ticket target")
        now = self._now()
        if native_state.rental_value and not native_state.rental_present:
            raise UnknownPageStateError("ComicFUZ rental expiry lacks native field presence")
        if native_state.rental_value:
            expiry = parse_rental_expiry(native_state.rental_value)
            if expiry is None:
                raise UnknownPageStateError("ComicFUZ rental marker has no expiry")
            if expiry > now:
                grant_reporter(
                    ConfirmedAccessGrant(
                        site=SITE,
                        external_id=self.external_id,
                        observed_at=now,
                        access_granted_until=expiry,
                        expiry_evidence="site_absolute_expiry",
                    )
                )
                await self._mark_no_action(attempt_reporter, "target_has_active_rental")
        if not (
            native_state.is_charge_needed_present
            and native_state.is_charge_needed
            and native_state.is_ticket_available_present
            and native_state.is_ticket_available
            and native_state.charge_status_present
            and native_state.charge_status in TICKET_AVAILABLE_LABELS
        ):
            await self._mark_no_action(attempt_reporter, "work_ticket_unavailable")

        if native_state.viewer_chapter_id == self.chapter_id:
            raise UnknownPageStateError(
                "ComicFUZ target viewer was already open before the ticket action"
            )

        badge = await read_work_ticket_badge(page)
        items = badge.get("items")
        if (
            badge.get("count") != 1
            or not isinstance(items, list)
            or len(items) != 1
            or not isinstance(items[0], Mapping)
            or "Charge_charge__charged__" not in str(items[0].get("className") or "")
            or items[0].get("imagePath") != "/assets/manga_detail/charged.svg"
            or items[0].get("imageAlt") != "\u30c1\u30e3\u30fc\u30b8"
            or items[0].get("text") not in TICKET_AVAILABLE_LABELS
        ):
            await self._mark_no_action(attempt_reporter, "charged_badge_not_available")

        modal = await read_ticket_modal(page, chapter_label=chapter_label)
        if (
            modal.get("ctaCount") != 1
            or modal.get("modal") is not True
            or modal.get("chapterTitleMatch") is not True
            or modal.get("ticketCountOne") is not True
            or modal.get("otherAccessCount") != 0
            or modal.get("disabled") is not False
            or modal.get("ctaText") != "\u30c1\u30e3\u30fc\u30b8\u3067\u8aad\u3080"
        ):
            await self._mark_no_action(attempt_reporter, "target_ticket_modal_not_exact")

        api_requests = 0
        consuming_requests = 0
        expected_request = None
        response_future = asyncio.get_running_loop().create_future()
        request_started_at: datetime | None = None
        click_started_at: datetime | None = None
        click_event_at: datetime | None = None
        click_event_count = 0
        click_event = asyncio.Event()
        click_nonce = f"cfz-{id(self):x}-{int(self._now().timestamp() * 1_000_000)}"
        binding_name = f"__cfzTicketClick_{id(self):x}"
        route_failure: str | None = None
        binding_active = True
        operation_active = False
        operation_succeeded = False

        async def record_trusted_click(payload: object) -> None:
            nonlocal click_event_at, click_event_count
            if not binding_active:
                return
            if (
                not isinstance(payload, Mapping)
                or payload.get("nonce") != click_nonce
                or payload.get("count") != 1
                or payload.get("trusted") is not True
                or payload.get("chapterLabel") != chapter_label
                or payload.get("chargeLabel") != TICKET_CTA_LABEL
            ):
                return
            click_event_count += 1
            click_event_at = self._now()
            click_event.set()

        def is_viewer_request(request) -> bool:
            return is_canonical_viewer_api_request(request.url, request.method)

        def same_request(left, right) -> bool:
            return getattr(left, "_impl_obj", left) is getattr(right, "_impl_obj", right)

        def same_frame(left, right) -> bool:
            return getattr(left, "_impl_obj", left) is getattr(right, "_impl_obj", right)

        def fail_route(reason: str) -> None:
            nonlocal route_failure
            route_failure = reason
            if operation_active and not response_future.done():
                response_future.set_exception(UnknownPageStateError(reason))

        async def route_viewer_api(route) -> None:
            nonlocal api_requests, consuming_requests, expected_request
            nonlocal request_started_at, route_failure, operation_active
            request = route.request
            api_requests += 1
            if not is_viewer_request(request):
                fail_route("viewer_request_route_mismatch")
                await route.abort("blockedbyclient")
                return
            if route_failure is not None:
                await route.abort("blockedbyclient")
                return
            if not operation_active:
                if operation_succeeded:
                    try:
                        direct_body = request.post_data_buffer or b""
                        if is_zero_cost_direct_request(
                            direct_body, chapter_id=self.chapter_id
                        ) and api_requests <= 3:
                            await route.fallback()
                            return
                    except (ValueError, TypeError, PlaywrightError):
                        pass
                await route.abort("blockedbyclient")
                return
            try:
                request_frame = request.frame
                is_main_frame = same_frame(request_frame, page.main_frame)
                frame_url = request_frame.url
                page_url = page.url
            except (AttributeError, PlaywrightError):
                fail_route("ticket_request_frame_unavailable")
                await route.abort("blockedbyclient")
                return
            if (
                not is_main_frame
                or not is_ticket_viewer_url(page_url, chapter_id=self.chapter_id)
                or not is_ticket_viewer_url(frame_url, chapter_id=self.chapter_id)
                or click_started_at is None
                or self._now() < click_started_at
            ):
                fail_route("ticket_request_outside_target_operation")
                await route.abort("blockedbyclient")
                return
            try:
                await asyncio.wait_for(click_event.wait(), timeout=5)
                if not operation_active or route_failure is not None:
                    fail_route("ticket_operation_ended_before_request_forward")
                    await route.abort("blockedbyclient")
                    return
                if (
                    click_event_count != 1
                    or click_event_at is None
                    or click_event_at < click_started_at
                ):
                    raise ValueError("target CTA click was not observed exactly once")
                body = request.post_data_buffer or b""
                decoded = decode_viewer_request(body)
                if decoded.chapter_id != int(self.chapter_id):
                    raise ValueError("viewer request target chapter differs")
                if decoded.use_ticket:
                    if not is_exact_ticket_request(body, chapter_id=self.chapter_id):
                        raise ValueError("viewer ticket request is not zero-cost and target-bound")
                    if consuming_requests:
                        fail_route("duplicate_ticket_request_blocked")
                        await route.abort("blockedbyclient")
                        return
                    consuming_requests += 1
                    expected_request = request
                    request_started_at = self._now()
                    if click_event_at is None or request_started_at < click_event_at:
                        consuming_requests -= 1
                        expected_request = None
                        request_started_at = None
                        fail_route("ticket_request_precedes_target_click")
                        await route.abort("blockedbyclient")
                        return
                    await self._before_ticket_request_forward()
                    if not operation_active or route_failure is not None:
                        fail_route("ticket_operation_ended_before_request_forward")
                        await route.abort("blockedbyclient")
                        return
                    await route.fallback()
                    return
                if not is_zero_cost_direct_request(body, chapter_id=self.chapter_id):
                    raise ValueError("non-ticket viewer request is not zero-cost")
                if api_requests > 3:
                    raise ValueError("zero-cost viewer request limit exceeded")
                await route.fallback()
            except (ValueError, TypeError, TimeoutError, PlaywrightError):
                fail_route("viewer_request_not_allowlisted")
                await route.abort("blockedbyclient")

        def record_response(response) -> None:
            if response_future.done() or expected_request is None:
                return
            try:
                if same_request(response.request, expected_request) and same_frame(
                    response.request.frame, page.main_frame
                ):
                    response_future.set_result(response)
            except (AttributeError, PlaywrightError):
                return

        route_attached = False
        page.on("response", record_response)
        try:
            await page.expose_function(binding_name, record_trusted_click)
            await page.evaluate(
                r"""({nonce, chapterLabel, chargeLabel, cancelLabel, bindingName}) => {
          const norm=value=>String(value||'').trim().replace(/\s+/g,' ');
                  const visible=element=>!!element&&!!element.getClientRects().length
                    &&getComputedStyle(element).visibility==='visible'
                    &&getComputedStyle(element).display!=='none';
                  const exact=[...document.querySelectorAll('*')]
                    .filter(element=>visible(element)&&norm(element.innerText)===chargeLabel);
                  const ctas=exact.filter(element=>![...element.children]
                    .some(child=>norm(child.innerText)===chargeLabel));
                  if(ctas.length!==1)throw new Error('ticket CTA is not unique');
                  const cta=ctas[0];
                  let modal=null;
                  for(let node=cta,depth=0;node&&depth<10;node=node.parentElement,depth++){
                    const headings=[...node.querySelectorAll('h1,h2,h3,h4')].map(e=>norm(e.innerText));
                    if(headings.includes(chapterLabel)&&norm(node.innerText).includes(cancelLabel)){
                      modal=node;break;
                    }
                  }
                  if(!modal||!modal.contains(cta))throw new Error('target modal is not bound');
                  document.addEventListener('click',event=>{
                    if(event.isTrusted===true&&(event.target===cta||cta.contains(event.target))){
                      const report=window[bindingName];
                      if(typeof report==='function')report({nonce,count:1,trusted:true,
                        chapterLabel,chargeLabel}).catch(()=>{});
                    }
                  },true);
                }""",
                {
                    "nonce": click_nonce,
                    "chapterLabel": chapter_label,
                    "chargeLabel": TICKET_CTA_LABEL,
                    "cancelLabel": TICKET_CANCEL_LABEL,
                    "bindingName": binding_name,
                },
            )
            operation_active = True
            await page.route(API_ROUTE_PATTERN, route_viewer_api)
            route_attached = True
            attempt_at = self._now()
            attempt_reporter(
                AccessAttemptObservation(
                    site=SITE,
                    external_id=self.external_id,
                    resource=RESOURCE,
                    resource_kind="work_ticket",
                    status="attempting",
                    observed_at=attempt_at,
                )
            )
            self.attempt_latched = True
            click_started_at = self._now()
            try:
                loop = asyncio.get_running_loop()
                action_deadline = loop.time() + ACTION_TIMEOUT_MS / 1000
                await asyncio.wait_for(
                    click(), timeout=max(0.0, action_deadline - loop.time())
                )
                response = await asyncio.wait_for(
                    response_future,
                    timeout=max(0.0, action_deadline - loop.time()),
                )
            except (
                asyncio.CancelledError,
                KeyboardInterrupt,
                TimeoutError,
                PlaywrightError,
                UnknownPageStateError,
            ) as exc:
                await self._mark_unknown(
                    attempt_reporter,
                    "ticket_request_or_response_missing",
                    cause=exc,
                )
            if (
                consuming_requests != 1
                or response.status != 200
                or request_started_at is None
                or route_failure is not None
            ):
                await self._mark_unknown(attempt_reporter, "ticket_api_response_unconfirmed")
            try:
                remaining_body_budget = min(
                    RESPONSE_BODY_TIMEOUT_MS / 1000,
                    max(0.0, action_deadline - asyncio.get_running_loop().time()),
                )
                response_metadata = decode_viewer_response(
                    await read_bounded_viewer_response_body(
                        response, timeout=remaining_body_budget
                    ),
                    work_id=self.work_id,
                    chapter_id=self.chapter_id,
                )
            except (
                TypeError,
                ValueError,
                OverflowError,
                OSError,
                TimeoutError,
                PlaywrightError,
            ) as exc:
                await self._mark_unknown(
                    attempt_reporter,
                    "ticket_native_response_invalid",
                    cause=exc,
                )
            response_confirmed_at = self._now()
            if (
                request_started_at.astimezone(JST).date()
                != response_confirmed_at.astimezone(JST).date()
            ):
                await self._mark_unknown(
                    attempt_reporter,
                    "ticket_consumption_date_crossed_jst_midnight",
                )
            if not (
                response_metadata.manga_id == int(self.work_id)
                and response_metadata.chapter_id == int(self.chapter_id)
                and native_state.is_ticket_available
                and response_metadata.is_charge_needed
                and response_metadata.charge_status_present
                and response_metadata.charge_status in TICKET_RECOVERY_LABELS
                and not response_metadata.ticket_available
            ):
                await self._mark_unknown(
                    attempt_reporter,
                    "ticket_native_consumption_transition_unconfirmed",
                )
            grant_expiry: datetime | None = None
            if response_metadata.rental_present:
                try:
                    candidate_expiry = parse_rental_expiry(
                        response_metadata.rental_value
                    )
                except UnknownPageStateError:
                    candidate_expiry = None
                if (
                    candidate_expiry is not None
                    and candidate_expiry > response_confirmed_at
                    and response_metadata.rental_value != native_state.rental_value
                ):
                    grant_expiry = candidate_expiry
            self.consumption = AccessConsumption(
                consumed=True,
                resource=RESOURCE,
                consumed_at=request_started_at,
                access_granted_until=None,
                stop_resource_pass=False,
            )
            self._terminal_attempt_reported = True
            attempt_reporter(
                AccessAttemptObservation(
                    site=SITE,
                    external_id=self.external_id,
                    resource=RESOURCE,
                    resource_kind="work_ticket",
                    status="confirmed",
                    observed_at=response_confirmed_at,
                    reason="native_work_ticket_transition",
                )
            )
            try:
                await page.wait_for_url(
                    lambda url: is_ticket_viewer_url(str(url), chapter_id=self.chapter_id),
                    timeout=ACTION_TIMEOUT_MS,
                    wait_until="domcontentloaded",
                )
            except (asyncio.CancelledError, TimeoutError, PlaywrightError) as exc:
                await self._mark_unknown(
                    attempt_reporter,
                    "ticket_viewer_route_unconfirmed",
                    cause=exc,
                )
            deadline = asyncio.get_running_loop().time() + ACTION_TIMEOUT_MS / 1000
            post_state: NativeTicketSnapshot | None = None
            last_error: BaseException | None = None
            while asyncio.get_running_loop().time() < deadline:
                try:
                    post_state = await read_native_ticket_snapshot(
                        page,
                        work_id=self.work_id,
                        chapter_id=self.chapter_id,
                        page_mode="viewer",
                    )
                    if post_state.viewer_chapter_id == self.chapter_id:
                        break
                except (PlaywrightError, UnknownPageStateError, TimeoutError) as exc:
                    last_error = exc
                post_state = None
                await page.wait_for_timeout(100)
            if post_state is None:
                await self._mark_unknown(
                    attempt_reporter,
                    "fresh_target_viewer_state_missing",
                    cause=last_error,
                )
            if not (
                post_state.work_id == self.work_id
                and post_state.chapter_id == self.chapter_id
                and post_state.is_charge_needed_present
                and post_state.is_charge_needed
                and not post_state.is_ticket_available
                and post_state.charge_status_present
                and post_state.charge_status == response_metadata.charge_status
                and post_state.is_ticket_available
                == response_metadata.ticket_available
                and post_state.is_charge_needed
                == response_metadata.is_charge_needed
            ):
                await self._mark_unknown(
                    attempt_reporter,
                    "viewer_state_does_not_match_native_response",
                )
            if (
                not response_metadata.rental_present
                or not post_state.rental_value
                or not post_state.rental_present
                or post_state.rental_value != response_metadata.rental_value
                or grant_expiry is None
            ):
                await self._mark_unknown(attempt_reporter, "target_rental_expiry_missing")
            expiry = grant_expiry
            if expiry <= self._now():
                await self._mark_unknown(attempt_reporter, "target_rental_expiry_not_future")
            if (
                response_metadata.point_type is not None
                and response_metadata.point_amount is not None
                and (
                    response_metadata.point_type != native_state.point_type
                    or response_metadata.point_amount != native_state.point_amount
                )
            ):
                await self._mark_unknown(
                    attempt_reporter,
                    "target_point_metadata_changed_in_response",
                )
            if (
                post_state.point_type != native_state.point_type
                or post_state.point_amount != native_state.point_amount
                or native_state.rental_value == post_state.rental_value
            ):
                await self._mark_unknown(
                    attempt_reporter,
                    "target_native_grant_transition_unconfirmed",
                )
            if route_failure is not None:
                await self._mark_unknown(
                    attempt_reporter,
                    "additional_or_malformed_viewer_request_blocked",
                )

            self.consumption = AccessConsumption(
                consumed=True,
                resource=RESOURCE,
                consumed_at=request_started_at,
                access_granted_until=expiry,
                stop_resource_pass=False,
            )

            self.proof = TicketEntryProof(
                request_started_at=request_started_at,
                confirmed_at=response_confirmed_at,
                access_granted_until=expiry,
            )
            operation_succeeded = True
            return self.proof
        except BaseException:
            if self.attempt_latched and not self._terminal_attempt_reported:
                try:
                    attempt_reporter(
                        AccessAttemptObservation(
                            site=SITE,
                            external_id=self.external_id,
                            resource=RESOURCE,
                            resource_kind="work_ticket",
                            status="unknown",
                            observed_at=self._now(),
                            reason="ticket_action_interrupted_or_proof_incomplete",
                        )
                    )
                except Exception:  # noqa: BLE001, S110 - keep the original post-latch failure
                    pass
                self._terminal_attempt_reported = True
            raise
        finally:
            operation_active = False
            if response_future.done() and not response_future.cancelled():
                response_future.exception()
            page.remove_listener("response", record_response)
            binding_active = False
            if route_attached and not self.attempt_latched:
                try:
                    await page.unroute(API_ROUTE_PATTERN, route_viewer_api)
                except PlaywrightError:
                    pass
