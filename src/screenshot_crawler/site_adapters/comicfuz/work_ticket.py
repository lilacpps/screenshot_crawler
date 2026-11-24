"""Bounded ComicFUZ Work Ticket entry evidence and state transitions."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlparse

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page

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
TICKET_AVAILABLE_UI_FALLBACK = "\u30c1\u30e3\u30fc\u30b8\u5b8c\u4e86\uff01"
TICKET_RECOVERY_UI_FALLBACK = "0\u6642\u306b\u56de\u5fa9\uff01"
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
    is_read: bool | None
    rental_value: str
    rental_present: bool
    rental_label: str
    viewer_chapter_id: str
    point_type_present: bool = False
    point_type_in: bool = False
    point_type_prototype_default_zero: bool = False
    point_amount_present: bool = False
    point_amount_in: bool = False
    point_amount_prototype_default_zero: bool = False
    rental_row_validated: bool = False
    row_root_class_tokens: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DirectRentalViewerResult:
    snapshot: NativeTicketSnapshot
    assert_route_healthy: Callable[[], None]


@dataclass(frozen=True, slots=True)
class TicketEntryProof:
    request_started_at: datetime
    confirmed_at: datetime
    access_granted_until: datetime | None


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
    point_present: bool
    point_metadata_complete: bool


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
    point_present = point_bytes is not None
    point_metadata_complete = False
    if point_bytes is not None:
        if not isinstance(point_bytes, bytes):
            raise ValueError("ComicFUZ viewer response target point metadata is malformed")
        point_metadata_complete = all(
            field_number in {1, 2} and wire_type == 0
            for field_number, wire_type, _value in _protobuf_fields(
                point_bytes, maximum_size=2 * 1024 * 1024
            )
        )
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
        point_present=point_present,
        point_metadata_complete=point_metadata_complete,
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


_RELATIVE_RENTAL_DAYS = re.compile(r"残り([1-9][0-9]*)日")


def parse_relative_rental_days(value: object) -> int | None:
    """Recognize the observed current-entry marker without deriving an expiry."""

    if not isinstance(value, str) or len(value) > 160:
        return None
    match = _RELATIVE_RENTAL_DAYS.fullmatch(value)
    return int(match.group(1)) if match is not None else None


def _native_point_is_known_zero(snapshot: NativeTicketSnapshot) -> bool:
    """Accept explicit zero or a verified generated-prototype zero default."""

    type_is_zero = snapshot.point_type == 0 and (
        snapshot.point_type_present
        or (
            snapshot.point_type_in
            and snapshot.point_type_prototype_default_zero
        )
    )
    amount_is_zero = snapshot.point_amount == 0 and (
        snapshot.point_amount_present
        or (
            snapshot.point_amount_in
            and snapshot.point_amount_prototype_default_zero
        )
    )
    return type_is_zero and amount_is_zero


def is_canonical_viewer_url(url: str, *, chapter_id: str) -> bool:
    """Accept only the exact target viewer path without query or fragment."""

    try:
        parsed = urlparse(url)
        return bool(
            parsed.scheme.lower() == "https"
            and parsed.hostname == "comic-fuz.com"
            and parsed.port is None
            and parsed.username is None
            and parsed.password is None
            and parsed.path == f"/manga/viewer/{chapter_id}"
            and not parsed.query
            and not parsed.fragment
            and not parsed.params
            and "?" not in url
            and "#" not in url
        )
    except (AttributeError, TypeError, ValueError):
        return False


def is_ticket_viewer_url(url: str, *, chapter_id: str) -> bool:
    """Accept only the exact target viewer path with its one ticket query."""

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
            and "#" not in url
        )
    except (AttributeError, TypeError, ValueError):
        return False


def is_target_viewer_url(url: str, *, chapter_id: str) -> bool:
    """Accept the target's exact canonical route or exact ticket query route."""

    return is_canonical_viewer_url(url, chapter_id=chapter_id) or is_ticket_viewer_url(
        url, chapter_id=chapter_id
    )


async def read_native_ticket_snapshot(
    page: Page,
    *,
    work_id: str,
    chapter_id: str,
    page_mode: str = "listing",
) -> NativeTicketSnapshot:
    """Read an allowlisted projection from hydrated first-party React data."""

    if page_mode in {"listing", "rental_listing"}:
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
    if page_mode in {"viewer", "ticket_post"} and not is_target_viewer_url(
        page.url, chapter_id=chapter_id
    ):
        raise UnknownPageStateError(
            "ComicFUZ ticket snapshot is outside the target viewer route"
        )

    value = await page.evaluate(
        r"""({workId, chapterId, pageMode, ticketAvailableLabels, recoveryLabels,
            availableFallback, recoveryFallback, chargeAlt}) => {
          const fiberOf = element => {
            const key = Object.keys(element || {}).find(name => name.startsWith('__reactFiber$'));
            return key ? element[key] : null;
          };
          const normalizeLabel = value => String(value ?? '').split(/\s+/).filter(Boolean).join(' ');
          const next = JSON.parse(document.querySelector('#__NEXT_DATA__')?.textContent || 'null');
          const nextChapters = (next?.props?.pageProps?.chapters || [])
            .flatMap(group => Array.isArray(group?.chapters) ? group.chapters : []);
          let chapter = null;
          let rowChapter = null;
          let manga = null;
          let mangaId = '';
          let viewerChapterId = '';
          let chargePresentationMatched = false;
          let chargeStatusIn = false;
          let chargeStatusPrototypeDefaultEmpty = false;
          let row = null;
          let headingElements = [];
          let rentalLabels = [];
          let targetIndex = -1;
          let chapterLabel = '';
          let pointType = null;
          let pointAmount = null;
          let pointTypePresent = false;
          let pointTypeIn = false;
          let pointTypePrototypeDefaultZero = false;
          let pointAmountPresent = false;
          let pointAmountIn = false;
          let pointAmountPrototypeDefaultZero = false;
          let rentalValue = null;
          let rentalPresent = false;
          let rentalIn = false;
          let rentalPrototypeDefaultEmpty = false;
          let isRead = null;
          let rentalRowValidated = false;
          let rowRootClassTokens = [];
          if (pageMode === 'listing' || pageMode === 'rental_listing') {
            const headingList = document.querySelector('div[class*="title_detail_chapters__list__"]');
            headingElements = headingList
              ? [...headingList.querySelectorAll('h3[class*="Chapter_chapter__name__"]')] : [];
            const nativeChapterIds = nextChapters.map(candidate =>
              String(candidate?.chapterId ?? ''));
            const nativeMatches = nextChapters
              .map((candidate, index) => ({candidate, index}))
              .filter(entry => String(entry.candidate?.chapterId ?? '') === chapterId);
            if (nativeMatches.length !== 1) return {state:'listing_native_target_missing_or_ambiguous'};
            targetIndex = nativeMatches[0].index;
            const nativeTarget = nativeMatches[0].candidate;
            const heading = targetIndex >= 0 ? headingElements[targetIndex] : null;
            row = heading?.parentElement?.parentElement || null;
            rowRootClassTokens = row ? [...row.classList] : [];
            rentalLabels = row
              ? [...row.querySelectorAll('p[class*="Chapter_chapter__rentalPeriod__"]')]
                  .filter(element => element.getClientRects().length > 0)
                  .map(element => normalizeLabel(element.innerText)) : [];
            const chapterCandidatesForHeading = element => {
              let node = fiberOf(element);
              const candidates = [];
              for (let depth = 0; node && depth < 35; depth++, node = node.return) {
                const candidate = node.memoizedProps?.chapter;
                if (candidate && typeof candidate === 'object' && !candidates.includes(candidate))
                  candidates.push(candidate);
              }
              return candidates;
            };
            const domRowCandidates = headingElements.map(chapterCandidatesForHeading);
            const domChapterIds = domRowCandidates.map(candidates =>
              candidates.length === 1 ? String(candidates[0].chapterId ?? '') : '');
            if (nextChapters.length !== headingElements.length
                || nativeChapterIds.some(id => !id)
                || new Set(nativeChapterIds).size !== nativeChapterIds.length
                || domChapterIds.some(id => !id)
                || JSON.stringify(nativeChapterIds) !== JSON.stringify(domChapterIds)) {
              return {state:'listing_native_dom_chapter_order_mismatch'};
            }
            const chapterCandidates = domRowCandidates[targetIndex] || [];
            if (chapterCandidates.length !== 1) return {state:'listing_row_chapter_missing_or_ambiguous'};
            rowChapter = chapterCandidates[0];

            const visible = element => {
              if (!element || !element.getClientRects().length) return false;
              for (let node = element; node; node = node.parentElement) {
                const style = getComputedStyle(node);
                if (node.hidden || style.display === 'none' || style.visibility !== 'visible'
                    || Number(style.opacity) === 0) return false;
              }
              return true;
            };
            const badges = [...document.querySelectorAll('div[class*="Charge_charge__"]')]
              .filter(visible);
            if (badges.length !== 1) return {state:'listing_charge_component_missing_or_ambiguous'};

            const webDataFrom = element => {
              let node = fiberOf(element);
              const values = [];
              for (let depth = 0; node && depth < 35; depth++, node = node.return) {
                const data = node.memoizedProps?.webMangaViewerData;
                if (data && typeof data === 'object' && !values.includes(data)) values.push(data);
              }
              return values;
            };
            const headingData = webDataFrom(heading);
            const chargeData = webDataFrom(badges[0]);
            if (headingData.length !== 1 || chargeData.length !== 1
                || headingData[0] !== chargeData[0]) {
              return {state:'listing_runtime_work_data_missing_or_ambiguous'};
            }
            const webData = headingData[0];
            const groups = Array.isArray(webData.chapters) ? webData.chapters : [];
            const runtimeChapters = groups.flatMap(group =>
              Array.isArray(group?.chapters) ? group.chapters : []);
            const runtimeChapterIds = runtimeChapters.map(candidate =>
              String(candidate?.chapterId ?? ''));
            const runtimeMatches = runtimeChapters
              .map((candidate, index) => ({candidate, index}))
              .filter(entry => String(entry.candidate?.chapterId ?? '') === chapterId);
            if (runtimeChapters.length !== nextChapters.length
                || runtimeChapterIds.some(id => !id)
                || new Set(runtimeChapterIds).size !== runtimeChapterIds.length
                || JSON.stringify(runtimeChapterIds) !== JSON.stringify(nativeChapterIds)
                || runtimeMatches.length !== 1
                || runtimeMatches[0].index !== targetIndex) {
              return {state:'listing_runtime_target_missing_or_out_of_order'};
            }
            chapter = runtimeMatches[0].candidate;
            manga = webData.manga;
            if (!manga || typeof manga !== 'object'
                || String(manga.mangaId ?? '') !== workId
                || String(next?.query?.mangaId ?? '') !== workId) {
              return {state:'listing_runtime_work_identity_mismatch'};
            }
            mangaId = String(manga.mangaId ?? '');

            const nativeChapter = nativeTarget;
            const rowPoint = rowChapter.pointConsumption;
            const nativePoint = nativeChapter?.pointConsumption;
            const runtimePoint = chapter.pointConsumption;
            if (!row || !heading || !rowPoint || typeof rowPoint !== 'object'
                || !nativePoint || typeof nativePoint !== 'object'
                || !runtimePoint || typeof runtimePoint !== 'object') {
              return {state:'listing_runtime_chapter_metadata_missing'};
            }
            const labels = [rowChapter.chapterMainName, nativeChapter?.chapterMainName,
              chapter.chapterMainName];
            if (labels.some(label => typeof label !== 'string')
                || labels.some(label => normalizeLabel(label) !== normalizeLabel(labels[0]))) {
              return {state:'listing_runtime_chapter_label_mismatch'};
            }
            const amountValues = [rowPoint.amount, nativePoint.amount, runtimePoint.amount];
            if (pageMode === 'rental_listing') {
              const runtimeAmountDescriptor = Object.getOwnPropertyDescriptor(
                Object.getPrototypeOf(runtimePoint) || {}, 'amount');
              const runtimeAmountKnownZero = runtimePoint.amount === 0
                && Number.isInteger(runtimePoint.amount)
                && (Object.hasOwn(runtimePoint, 'amount') || (
                  'amount' in runtimePoint && !!runtimeAmountDescriptor
                  && Object.hasOwn(runtimeAmountDescriptor, 'value')
                  && runtimeAmountDescriptor.value === 0
                ));
              if (!runtimeAmountKnownZero
                  || (Object.hasOwn(rowPoint, 'amount')
                    && rowPoint.amount !== runtimePoint.amount)
                  || (Object.hasOwn(nativePoint, 'amount')
                    && nativePoint.amount !== runtimePoint.amount)) {
                return {state:'listing_runtime_point_amount_mismatch'};
              }
            } else if (amountValues.some(amount => !Number.isInteger(amount) || amount < 0)
                || !Object.hasOwn(rowPoint,'amount')
                || !Object.hasOwn(nativePoint,'amount')
                || !Object.hasOwn(runtimePoint,'amount')
                || amountValues.some(amount => amount !== amountValues[0])) {
              return {state:'listing_runtime_point_amount_mismatch'};
            }
            const runtimeTypeDescriptor = Object.getOwnPropertyDescriptor(
              Object.getPrototypeOf(runtimePoint) || {}, 'type');
            pointType = runtimePoint.type;
            pointTypePresent = Object.hasOwn(runtimePoint, 'type');
            pointTypeIn = 'type' in runtimePoint;
            pointTypePrototypeDefaultZero = !!runtimeTypeDescriptor
              && Object.hasOwn(runtimeTypeDescriptor,'value')
              && typeof runtimeTypeDescriptor.value === 'number'
              && Number.isInteger(runtimeTypeDescriptor.value)
              && runtimeTypeDescriptor.value === 0;
            const rowTypePresent = Object.hasOwn(rowPoint,'type');
            const nativeTypePresent = Object.hasOwn(nativePoint,'type');
            if (typeof pointType !== 'number' || !Number.isInteger(pointType)
                || (!pointTypePresent && !(pointTypeIn && pointTypePrototypeDefaultZero
                  && pointType === 0))
                || (pageMode === 'rental_listing' && pointType !== 0)
                || (rowTypePresent && rowPoint.type !== pointType)
                || (nativeTypePresent && nativePoint.type !== pointType)) {
              return {state:'listing_runtime_point_type_unproven'};
            }
            pointAmount = runtimePoint.amount;
            pointAmountPresent = Object.hasOwn(runtimePoint,'amount');
            pointAmountIn = 'amount' in runtimePoint;
            const runtimeAmountDescriptor = Object.getOwnPropertyDescriptor(
              Object.getPrototypeOf(runtimePoint) || {}, 'amount');
            pointAmountPrototypeDefaultZero = !!runtimeAmountDescriptor
              && Object.hasOwn(runtimeAmountDescriptor,'value')
              && typeof runtimeAmountDescriptor.value === 'number'
              && Number.isInteger(runtimeAmountDescriptor.value)
              && runtimeAmountDescriptor.value === 0;

            const rentalDescriptor = Object.getOwnPropertyDescriptor(
              Object.getPrototypeOf(chapter) || {}, 'endOfRentalPeriod');
            rentalValue = chapter.endOfRentalPeriod;
            rentalPresent = Object.hasOwn(chapter,'endOfRentalPeriod');
            rentalIn = 'endOfRentalPeriod' in chapter;
            rentalPrototypeDefaultEmpty = !!rentalDescriptor
              && Object.hasOwn(rentalDescriptor,'value')
              && typeof rentalDescriptor.value === 'string'
              && rentalDescriptor.value === '';
            if (typeof rentalValue !== 'string'
                || (!rentalPresent && !(rentalIn && rentalPrototypeDefaultEmpty
                  && rentalValue === ''))) {
              return {state:'listing_runtime_rental_unproven'};
            }
            if (rentalLabels.length > 1
                || (rentalValue
                  ? rentalLabels.length !== 1 || normalizeLabel(rentalLabels[0]) !== normalizeLabel(rentalValue)
                  : rentalLabels.length !== 0)) {
              return {state:'listing_runtime_rental_label_mismatch'};
            }
            if (pageMode === 'rental_listing') {
              const row = heading?.parentElement?.parentElement || null;
              const rowTokens = row ? [...row.classList] : [];
              const exactRootTokens = new Set([
                'Chapter_chapter__wJPBe', 'Chapter_chapter__alreadyViewed__BYLMn'
              ]);
              const visibleWithin = element => !!row && row.contains(element) && visible(element);
              const freeNodes = row ? [...row.querySelectorAll('p[class*="Chapter_chapter__price_free__"]')] : [];
              const visibleFree = freeNodes.filter(node => visibleWithin(node));
              const rentalNodes = row ? [...row.querySelectorAll('p[class*="Chapter_chapter__rentalPeriod__"]')] : [];
              const visibleRental = rentalNodes.filter(node => visibleWithin(node));
              const priceNodes = row ? [...row.querySelectorAll('[class*="Chapter_chapter__price"]')] : [];
              const priceSlots = priceNodes.filter(node => node.matches('i[class*="Chapter_chapter__price__"]'));
              const otherPriceNodes = priceNodes.filter(node =>
                !node.matches('p[class*="Chapter_chapter__price_free__"]')
                && !node.matches('i[class*="Chapter_chapter__price__"]')
                && !priceSlots.some(slot => slot.contains(node))
              );
              const knownClass = token => [
                /^Chapter_chapter__row(?:__[A-Za-z0-9_-]+)?$/,
                /^Chapter_chapter__thumbnail_wrapper__[A-Za-z0-9_-]+$/,
                /^Chapter_chapter__thumbnail__[A-Za-z0-9_-]+$/,
                /^Chapter_chapter__thumbnail_overlay__[A-Za-z0-9_-]+$/,
                /^Chapter_chapter__label__[A-Za-z0-9_-]+$/,
                /^Chapter_chapter__label_(advance|update)__[A-Za-z0-9_-]+$/,
                /^Chapter_chapter__detail__[A-Za-z0-9_-]+$/,
                /^Chapter_chapter__name__[A-Za-z0-9_-]+$/,
                /^Chapter_chapter__subName__[A-Za-z0-9_-]+$/,
                /^Chapter_chapter__updateDate__[A-Za-z0-9_-]+$/,
                /^Chapter_chapter__bottom__[A-Za-z0-9_-]+$/,
                /^Chapter_chapter__userAction__[A-Za-z0-9_-]+$/,
                /^Chapter_chapter__userAction_item__[A-Za-z0-9_-]+$/,
                /^Chapter_chapter__userAction_icon__[A-Za-z0-9_-]+$/,
                /^Chapter_chapter__userAction_text__[A-Za-z0-9_-]+$/,
                /^Chapter_chapter__price_free__[A-Za-z0-9_-]+$/,
                /^Chapter_chapter__price__[A-Za-z0-9_-]+$/,
                /^Chapter_chapter__price_gold__[A-Za-z0-9_-]+$/,
                /^Chapter_chapter__rentalPeriod__[A-Za-z0-9_-]+$/
              ].some(pattern => pattern.test(token));
              const thumbnail = row?.querySelector('div[class*="Chapter_chapter__thumbnail_wrapper__"]');
              const unknownMarkers = row ? [row, ...row.querySelectorAll('*')].filter(node => {
                if (node.hasAttribute('aria-label') || node.hasAttribute('title') || node.hasAttribute('role')) return true;
                const style = getComputedStyle(node);
                if (style.backgroundImage !== 'none'
                    || getComputedStyle(node, '::before').backgroundImage !== 'none'
                    || getComputedStyle(node, '::after').backgroundImage !== 'none') return true;
                const tokens = [...node.classList];
                if (node === row) return tokens.length !== exactRootTokens.size
                  || tokens.some(token => !exactRootTokens.has(token));
                const chapterTokens = tokens.filter(token => token.startsWith('Chapter_chapter__'));
                if (chapterTokens.some(token => !knownClass(token))) return true;
                if (node.tagName === 'IMG') {
                  if (thumbnail?.contains(node) && node.matches('img[class*="Chapter_chapter__thumbnail__"]')) return false;
                  if (node.matches('img[class*="Chapter_chapter__userAction_icon__"]')) {
                    let path = null;
                    try { path = new URL(node.currentSrc || node.src, location.href).pathname; } catch (_) {}
                    return !['/assets/manga_detail/comment.svg', '/assets/manga_detail/like.svg'].includes(path);
                  }
                  return !priceSlots.some(slot => slot.contains(node));
                }
                if (node.tagName.toLowerCase() === 'svg') return true;
                if (node.tagName === 'DIV') return chapterTokens.length === 0;
                if (node.tagName === 'P') return !node.matches(
                  'p[class*="Chapter_chapter__subName__"], p[class*="Chapter_chapter__updateDate__"], '
                  + 'p[class*="Chapter_chapter__userAction_text__"], p[class*="Chapter_chapter__price_free__"], '
                  + 'p[class*="Chapter_chapter__rentalPeriod__"]');
                if (node.tagName === 'H3') return !node.matches('h3[class*="Chapter_chapter__name__"]');
                if (node.tagName === 'I') return !node.matches('i[class*="Chapter_chapter__label__"], i[class*="Chapter_chapter__price__"]');
                return true;
              }).length : 1;
              rentalRowValidated = !!row
                && rowTokens.length === exactRootTokens.size
                && rowTokens.every(token => exactRootTokens.has(token))
                && freeNodes.length === 1 && visibleFree.length === 1
                && normalizeLabel(visibleFree[0].innerText) === '無料'
                && rentalNodes.length === 1 && visibleRental.length === 1
                && normalizeLabel(visibleRental[0].innerText) === normalizeLabel(rentalValue)
                && typeof rentalValue === 'string' && rentalValue.length > 0
                && priceSlots.length === 0 && otherPriceNodes.length === 0
                && unknownMarkers === 0;
              if (!rentalRowValidated) return {state:'rental_listing_row_not_exact'};
            }
            const availableLabels = ticketAvailableLabels;
            const recoveryLabelSet = new Set(recoveryLabels);
            const chargeNode = badges[0];
            const chargeProps = [];
            for (const badge of badges) {
              let node = fiberOf(badge);
              for (let depth = 0; node && depth < 20; depth++, node = node.return) {
                const props = node.memoizedProps || {};
                if (Object.hasOwn(props,'isTicketAvailable')
                    && Object.hasOwn(props,'labelText')) {
                  chargeProps.push(props);
                  break;
                }
              }
            }
            if (chargeProps.length !== 1
                || !Object.hasOwn(manga,'isChargeNeeded')
                || typeof manga.isChargeNeeded !== 'boolean') {
              return {state:'listing_runtime_charge_state_missing'};
            }
            const ticketDescriptor = Object.getOwnPropertyDescriptor(
              Object.getPrototypeOf(manga) || {}, 'isTicketAvailable');
            const chargeStatusDescriptor = Object.getOwnPropertyDescriptor(
              Object.getPrototypeOf(manga) || {}, 'chargeStatus');
            const isTicketAvailable = manga.isTicketAvailable;
            const isTicketAvailablePresent = Object.hasOwn(manga,'isTicketAvailable');
            const isTicketAvailableIn = 'isTicketAvailable' in manga;
            const isTicketAvailablePrototypeDefault = !!ticketDescriptor
              && Object.hasOwn(ticketDescriptor,'value')
              && typeof ticketDescriptor.value === 'boolean'
              && ticketDescriptor.value === false;
            const chargeStatus = manga.chargeStatus;
            const chargeStatusPresent = Object.hasOwn(manga,'chargeStatus');
            chargeStatusIn = 'chargeStatus' in manga;
            chargeStatusPrototypeDefaultEmpty = !!chargeStatusDescriptor
              && Object.hasOwn(chargeStatusDescriptor,'value')
              && typeof chargeStatusDescriptor.value === 'string'
              && chargeStatusDescriptor.value === '';
            if (typeof isTicketAvailable !== 'boolean'
                || (!isTicketAvailablePresent
                  && !(isTicketAvailableIn && isTicketAvailablePrototypeDefault))
                || typeof chargeStatus !== 'string'
                || (!chargeStatusPresent
                  && !(chargeStatusIn && chargeStatusPrototypeDefaultEmpty && chargeStatus === ''))) {
              return {state:'listing_runtime_charge_state_missing'};
            }
            const chargeProp = chargeProps[0];
            const img = chargeNode.querySelector('img');
            let imagePath = '';
            try { imagePath = new URL(img?.currentSrc || img?.src || '', location.href).pathname; }
            catch (_) { imagePath = ''; }
            const chargeText = normalizeLabel(chargeNode.innerText);
            const chargeClass = String(chargeNode.className || '');
            const chargeClassTokens = chargeClass.split(/\s+/).filter(Boolean);
            const displayChargeStatus = chargeStatus || (isTicketAvailable
              ? availableFallback : recoveryFallback);
            const relativeRentalRecoveryPresentation = pageMode === 'rental_listing'
              && !isTicketAvailable
              && chargeStatusPresent
              && recoveryLabelSet.has(chargeStatus)
              && displayChargeStatus === chargeStatus
              && chargeText === chargeStatus
              && imagePath === '/assets/manga_detail/charge.svg'
              && img?.alt === chargeAlt
              && chargeClassTokens.length === 2
              && chargeClassTokens.includes('Charge_charge__JSGmu')
              && chargeClassTokens.includes('undefined');
            const statusMatches = isTicketAvailable
              ? availableLabels.includes(chargeStatus)
              : chargeStatus
                ? recoveryLabelSet.has(chargeStatus)
                : chargeStatusPrototypeDefaultEmpty
                  && displayChargeStatus === recoveryFallback;
            const expectedImagePath = isTicketAvailable
              ? '/assets/manga_detail/charged.svg' : '/assets/manga_detail/charge.svg';
            const expectedClass = isTicketAvailable
              ? 'Charge_charge__charged__' : 'Charge_charge__not_charged__';
            const chargeLabelMatches = pageMode === 'rental_listing' && !isTicketAvailable
              ? relativeRentalRecoveryPresentation
              : (pageMode === 'rental_listing'
                ? (chargeProp.labelText === chargeStatus || relativeRentalRecoveryPresentation)
                : chargeProp.labelText === chargeStatus);
            chargePresentationMatched = chargeProp.isTicketAvailable === isTicketAvailable
              && chargeLabelMatches
              && statusMatches
              && chargeText === displayChargeStatus
              && imagePath === expectedImagePath
              && img?.alt === chargeAlt
              && (relativeRentalRecoveryPresentation
                || chargeClass.includes(expectedClass));
            if (!chargePresentationMatched) return {state:'listing_charge_presentation_mismatch'};
            chapterLabel = normalizeLabel(labels[0]);
            isRead = typeof chapter.isRead === 'boolean' ? chapter.isRead : null;
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
            const point = chapter.pointConsumption;
            const typeDescriptor = Object.getOwnPropertyDescriptor(
              Object.getPrototypeOf(point || {}) || {}, 'type');
            pointType = point?.type;
            pointTypePresent = !!point && Object.hasOwn(point,'type');
            pointTypeIn = !!point && 'type' in point;
            pointTypePrototypeDefaultZero = !!typeDescriptor
              && Object.hasOwn(typeDescriptor,'value')
              && typeof typeDescriptor.value === 'number'
              && Number.isInteger(typeDescriptor.value)
              && typeDescriptor.value === 0;
            pointAmount = point?.amount;
            pointAmountPresent = !!point && Object.hasOwn(point,'amount');
            pointAmountIn = !!point && 'amount' in point;
            const amountDescriptor = Object.getOwnPropertyDescriptor(
              Object.getPrototypeOf(point || {}) || {}, 'amount');
            pointAmountPrototypeDefaultZero = !!amountDescriptor
              && Object.hasOwn(amountDescriptor,'value')
              && typeof amountDescriptor.value === 'number'
              && Number.isInteger(amountDescriptor.value)
              && amountDescriptor.value === 0;
            chargeStatusIn = 'chargeStatus' in manga;
            const chargeStatusDescriptor = Object.getOwnPropertyDescriptor(
              Object.getPrototypeOf(manga) || {}, 'chargeStatus');
            chargeStatusPrototypeDefaultEmpty = !!chargeStatusDescriptor
              && Object.hasOwn(chargeStatusDescriptor,'value')
              && typeof chargeStatusDescriptor.value === 'string'
              && chargeStatusDescriptor.value === '';
            const rentalDescriptor = Object.getOwnPropertyDescriptor(
              Object.getPrototypeOf(chapter) || {}, 'endOfRentalPeriod');
            rentalValue = chapter.endOfRentalPeriod;
            rentalPresent = Object.hasOwn(chapter,'endOfRentalPeriod');
            rentalIn = 'endOfRentalPeriod' in chapter;
            rentalPrototypeDefaultEmpty = !!rentalDescriptor
              && Object.hasOwn(rentalDescriptor,'value')
              && typeof rentalDescriptor.value === 'string'
              && rentalDescriptor.value === '';
            chapterLabel = typeof chapter.chapterMainName === 'string'
              ? normalizeLabel(chapter.chapterMainName) : '';
            isRead = typeof chapter.isRead === 'boolean' ? chapter.isRead : null;
          }
          if (!chapter || typeof chapter !== 'object' || !manga || typeof manga !== 'object')
            return {state:'native_target_props_missing'};
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
            chapterLabel,
            pointType,
            pointTypePresent,
            pointTypeIn,
            pointTypePrototypeDefaultZero,
            pointAmount,
            pointAmountPresent,
            pointAmountIn,
            pointAmountPrototypeDefaultZero,
            isRead,
            rentalValue,
            rentalPresent,
            rentalIn,
            rentalPrototypeDefaultEmpty,
            chargeStatusIn,
            chargeStatusPrototypeDefaultEmpty,
            chargePresentationMatched,
            rentalLabels,
            viewerChapterId,
            nextPage:next?.page,
            currentPath:location.pathname,
            currentSearch:location.search,
            nextWorkId:String(next?.query?.mangaId ?? ''),
            nativeChapterCount:nextChapters.length,
            domHeadingCount:headingElements.length,
            targetIndex,
            rentalRowValidated,
            rowRootClassTokens
          };
        }""",
        {"workId": work_id, "chapterId": chapter_id, "pageMode": page_mode,
         "ticketAvailableLabels": sorted(TICKET_AVAILABLE_LABELS),
         "recoveryLabels": sorted(TICKET_RECOVERY_LABELS),
         "availableFallback": TICKET_AVAILABLE_UI_FALLBACK,
         "recoveryFallback": TICKET_RECOVERY_UI_FALLBACK,
         "chargeAlt": TICKET_CHARGE_ALT},
    )
    if not isinstance(value, Mapping) or value.get("state") != "ok":
        state = value.get("state") if isinstance(value, Mapping) else "malformed_projection"
        raise UnknownPageStateError(
            f"ComicFUZ hydrated ticket state is missing or ambiguous ({state})"
        )
    if (
        value.get("mangaId") != work_id
        or value.get("chapterId") != chapter_id
         or page_mode not in {"listing", "rental_listing", "viewer", "ticket_post"}
        or (
            page_mode in {"listing", "rental_listing"}
            and (
                value.get("nextPage") != "/manga/[mangaId]"
                or value.get("nextWorkId") != work_id
                or value.get("currentPath") != f"/manga/{work_id}"
            )
        )
        or (
            page_mode in {"viewer", "ticket_post"}
            and (
                value.get("currentPath") != f"/manga/viewer/{chapter_id}"
                or value.get("viewerChapterId") != chapter_id
                or value.get("currentSearch") not in {"", "?ticket=true"}
            )
        )
        or (page_mode in {"listing", "rental_listing"} and type(value.get("targetIndex")) is not int)
        or (page_mode in {"listing", "rental_listing"} and value.get("nativeChapterCount") != value.get("domHeadingCount"))
        or (page_mode in {"listing", "rental_listing"} and value.get("targetIndex") < 0)
        or not isinstance(value.get("rentalLabels"), list)
    ):
        raise UnknownPageStateError("ComicFUZ ticket snapshot identity does not match the target")
    point_type, point_amount = value.get("pointType"), value.get("pointAmount")
    point_type_present = value.get("pointTypePresent")
    point_type_in = value.get("pointTypeIn")
    point_type_default_zero = value.get("pointTypePrototypeDefaultZero")
    point_amount_present = value.get("pointAmountPresent")
    point_amount_in = value.get("pointAmountIn")
    point_amount_default_zero = value.get("pointAmountPrototypeDefaultZero")
    is_read = value.get("isRead")
    rental_value = value.get("rentalValue")
    rental_present = value.get("rentalPresent")
    rental_in = value.get("rentalIn")
    rental_default_empty = value.get("rentalPrototypeDefaultEmpty")
    charge_status = value.get("chargeStatus")
    if (
        type(point_type) is not int
        or type(point_amount) is not int
        or type(point_type_present) is not bool
        or type(point_type_in) is not bool
        or type(point_type_default_zero) is not bool
        or type(point_amount_present) is not bool
        or type(point_amount_in) is not bool
        or type(point_amount_default_zero) is not bool
        or (
            not point_amount_present
            and not (
                page_mode in {"ticket_post", "rental_listing"}
                and point_amount == 0
                and point_amount_in
                and point_amount_default_zero
            )
        )
        or (
            not point_type_present
            and not (point_type_in and point_type_default_zero and point_type == 0)
        )
        or (is_read is not None and type(is_read) is not bool)
        or type(value.get("isChargeNeeded")) is not bool
        or type(value.get("isTicketAvailable")) is not bool
        or value.get("isChargeNeededPresent") is not True
        or type(value.get("isTicketAvailablePresent")) is not bool
        or type(value.get("isTicketAvailableIn")) is not bool
        or type(value.get("isTicketAvailablePrototypeDefault")) is not bool
        or type(value.get("chargeStatusPresent")) is not bool
        or type(value.get("chargeStatusIn")) is not bool
        or type(value.get("chargeStatusPrototypeDefaultEmpty")) is not bool
        or type(rental_present) is not bool
        or type(rental_in) is not bool
        or type(rental_default_empty) is not bool
        or (
            page_mode in {"listing", "rental_listing"}
            and value.get("isTicketAvailablePresent") is not True
            and not (
                value.get("isTicketAvailable") is False
                and value.get("isTicketAvailableIn") is True
                and value.get("isTicketAvailablePrototypeDefault") is True
            )
        )
        or (
            page_mode in {"viewer", "ticket_post"}
            and value.get("isTicketAvailablePresent") is not True
            and not (
                value.get("isTicketAvailableIn") is True
                and value.get("isTicketAvailablePrototypeDefault") is True
            )
        )
        or not isinstance(rental_value, str)
        or (not rental_present and not (rental_in and rental_default_empty and not rental_value))
        or not isinstance(charge_status, str)
        or (
            not value.get("chargeStatusPresent")
            and not (
                value.get("chargeStatusIn") is True
                and value.get("chargeStatusPrototypeDefaultEmpty") is True
                and charge_status == ""
            )
        )
        or len(value["rentalLabels"]) > 1
        or (
            page_mode in {"listing", "rental_listing"}
            and value.get("chargePresentationMatched") is not True
        )
        or (
            page_mode in {"listing", "rental_listing"}
            and value["rentalLabels"]
            and value["rentalLabels"][0] != rental_value
        )
        or (page_mode in {"listing", "rental_listing"} and rental_value and not value["rentalLabels"])
        or (
            page_mode == "rental_listing"
            and (
                value.get("rentalRowValidated") is not True
                or not isinstance(value.get("rowRootClassTokens"), list)
                or set(value.get("rowRootClassTokens", [])) != {
                    "Chapter_chapter__wJPBe",
                    "Chapter_chapter__alreadyViewed__BYLMn",
                }
                or len(value.get("rowRootClassTokens", [])) != 2
                or type(point_amount) is not int
                or point_amount != 0
                or (point_amount_present is not True and not (
                    point_amount_in is True and point_amount_default_zero is True
                ))
                or not rental_value
                or parse_relative_rental_days(rental_value) is None
            )
        )
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
        is_read=is_read if isinstance(is_read, bool) else None,
        rental_value=rental_value,
        rental_present=rental_present,
        rental_label=value["rentalLabels"][0] if value["rentalLabels"] else "",
        viewer_chapter_id=str(value.get("viewerChapterId") or ""),
        point_type_present=point_type_present,
        point_type_in=point_type_in,
        point_type_prototype_default_zero=point_type_default_zero,
        point_amount_present=point_amount_present,
        point_amount_in=point_amount_in,
        point_amount_prototype_default_zero=point_amount_default_zero,
        rental_row_validated=value.get("rentalRowValidated") is True,
        row_root_class_tokens=tuple(value.get("rowRootClassTokens") or ()),
    )


async def wait_for_native_viewer_presence(
    page: Page,
    *,
    work_id: str,
    chapter_id: str,
    timeout_ms: int = ACTION_TIMEOUT_MS,
) -> None:
    """Wait for the exact viewer runtime message without interpreting access."""

    if type(timeout_ms) is not int or timeout_ms < 1:
        raise ValueError("ComicFUZ viewer readiness timeout is invalid")
    try:
        await page.wait_for_function(
            r"""({workId, chapterId}) => {
              const current = new URL(location.href);
              if (current.protocol !== 'https:' || current.hostname !== 'comic-fuz.com'
                  || current.port || current.username || current.password
                  || current.pathname !== `/manga/viewer/${chapterId}`
                  || current.search || current.hash) return false;
              let next = null;
              try { next = JSON.parse(document.querySelector('#__NEXT_DATA__')?.textContent || 'null'); }
              catch (_) { return false; }
              if (next?.page !== '/manga/viewer/[chapterId]'
                  || String(next?.props?.pageProps?.chapterId ?? '') !== chapterId
                  || (next?.query?.chapterId != null
                    && String(next.query.chapterId) !== chapterId)) return false;
              for (const image of document.querySelectorAll('img[class*="G54Y0W_page"]')) {
                let key = Object.keys(image).find(name => name.startsWith('__reactFiber$'));
                let fiber = key ? image[key] : null;
                for (let depth = 0; fiber && depth < 35; depth++, fiber = fiber.return) {
                  const data = fiber.memoizedProps?.webMangaViewerData;
                  if (!data || typeof data !== 'object'
                      || String(data.manga?.mangaId ?? '') !== workId
                      || String(data.chapterId ?? '') !== chapterId
                      || !Array.isArray(data.chapters)) continue;
                  const chapters = data.chapters.flatMap(group =>
                    Array.isArray(group?.chapters) ? group.chapters : []);
                  if (chapters.filter(chapter =>
                    String(chapter?.chapterId ?? '') === chapterId).length === 1) return true;
                }
              }
              return false;
            }""",
            arg={"workId": work_id, "chapterId": chapter_id},
            timeout=timeout_ms,
            polling=100,
        )
    except (PlaywrightError, TimeoutError) as exc:
        raise UnknownPageStateError(
            "ComicFUZ exact viewer runtime data did not become available"
        ) from exc


async def open_direct_relative_rental_viewer(
    page: Page,
    *,
    pre_state: NativeTicketSnapshot,
    on_guard_installed: Callable[[Callable[[], None]], None] | None = None,
) -> DirectRentalViewerResult:
    """Open a Catalog-selected active rental through one strict zero-cost request."""

    work_id, chapter_id = pre_state.work_id, pre_state.chapter_id
    if (
        not re.fullmatch(r"[0-9]+", work_id)
        or not re.fullmatch(r"[0-9]+", chapter_id)
        or not pre_state.rental_row_validated
        or not pre_state.rental_present
        or parse_relative_rental_days(pre_state.rental_value) is None
        or not _native_point_is_known_zero(pre_state)
        or pre_state.point_type != 0
        or pre_state.point_amount != 0
        or not pre_state.chapter_label
    ):
        raise UnknownPageStateError("ComicFUZ direct rental pre-state is not exact")
    target_url = f"https://comic-fuz.com/manga/viewer/{chapter_id}"
    if not is_canonical_viewer_url(target_url, chapter_id=chapter_id):
        raise UnknownPageStateError("ComicFUZ direct rental target route is not canonical")

    expected_request: object | None = None
    request_count = 0
    route_failure: str | None = None
    operation_active = False
    operation_succeeded = False
    response_future: asyncio.Future[object] = asyncio.get_running_loop().create_future()

    def same_request(left: object, right: object) -> bool:
        return getattr(left, "_impl_obj", left) is getattr(right, "_impl_obj", right)

    def same_frame(left: object, right: object) -> bool:
        return getattr(left, "_impl_obj", left) is getattr(right, "_impl_obj", right)

    def fail(reason: str) -> None:
        nonlocal route_failure
        if route_failure is None:
            route_failure = reason

    def assert_route_healthy() -> None:
        if route_failure is not None:
            raise UnknownPageStateError(
                f"ComicFUZ direct viewer route failed ({route_failure})"
            )
        if not operation_succeeded:
            raise UnknownPageStateError(
                "ComicFUZ direct viewer operation did not reach a confirmed state"
            )

    async def route_request(route) -> None:
        nonlocal expected_request, request_count
        request = route.request
        request_count += 1
        if not operation_active:
            fail('direct_viewer_operation_ended')
            await route.abort('blockedbyclient')
            return
        if request_count != 1:
            fail("direct_viewer_request_count_not_one")
            await route.abort("blockedbyclient")
            return
        if not is_canonical_viewer_api_request(request.url, request.method):
            fail("direct_viewer_request_route_not_canonical")
            await route.abort("blockedbyclient")
            return
        try:
            request_frame = request.frame
            if (
                not same_frame(request_frame, page.main_frame)
                or not is_canonical_viewer_url(page.url, chapter_id=chapter_id)
                or not is_canonical_viewer_url(request_frame.url, chapter_id=chapter_id)
            ):
                fail("direct_viewer_request_not_bound_to_main_target")
                await route.abort("blockedbyclient")
                return
            body = request.post_data_buffer
            decoded = decode_viewer_request(body) if isinstance(body, bytes) else None
            if (
                decoded is None
                or decoded.chapter_id != int(chapter_id)
                or decoded.use_ticket
                or decoded.point_free != 0
                or decoded.point_paid != 0
                or not is_zero_cost_direct_request(body, chapter_id=chapter_id)
            ):
                fail("direct_viewer_request_not_zero_cost_exact")
                await route.abort("blockedbyclient")
                return
            expected_request = request
            if not operation_active or route_failure is not None:
                fail("direct_viewer_operation_ended")
                await route.abort("blockedbyclient")
                return
            await route.fallback()
        except (AttributeError, TypeError, ValueError, PlaywrightError):
            fail("direct_viewer_request_metadata_unavailable")
            await route.abort("blockedbyclient")

    def on_response(response) -> None:
        if expected_request is None or response_future.done():
            return
        try:
            if same_request(response.request, expected_request) and same_frame(
                response.request.frame, page.main_frame
            ):
                response_future.set_result(response)
        except (AttributeError, PlaywrightError):
            return

    await page.route(API_ROUTE_PATTERN, route_request)
    if on_guard_installed is not None:
        on_guard_installed(assert_route_healthy)
    operation_active = True
    page.on("response", on_response)
    try:
        try:
            await page.goto(
                target_url,
                wait_until="domcontentloaded",
                timeout=ACTION_TIMEOUT_MS,
            )
        except (PlaywrightError, TimeoutError) as exc:
            raise UnknownPageStateError("ComicFUZ direct viewer navigation failed") from exc
        if route_failure is not None or request_count != 1 or expected_request is None:
            raise UnknownPageStateError(
                route_failure or "direct_viewer_request_not_observed_once"
            )
        try:
            response = await asyncio.wait_for(
                response_future,
                timeout=ACTION_TIMEOUT_MS / 1000,
            )
        except asyncio.CancelledError:
            raise
        except TimeoutError as exc:
            raise UnknownPageStateError("ComicFUZ direct viewer response was not matched") from exc
        if route_failure is not None or getattr(response, "status", None) != 200:
            raise UnknownPageStateError(
                route_failure or "direct_viewer_response_status_not_200"
            )
        try:
            body = await read_bounded_viewer_response_body(
                response,
                timeout=RESPONSE_BODY_TIMEOUT_MS / 1000,
            )
            response_state = decode_viewer_response(
                body,
                work_id=work_id,
                chapter_id=chapter_id,
            )
        except (TypeError, ValueError, OSError, TimeoutError, PlaywrightError) as exc:
            raise UnknownPageStateError("ComicFUZ direct viewer response metadata is invalid") from exc
        if not (
            response_state.manga_id == int(work_id)
            and response_state.chapter_id == int(chapter_id)
            and response_state.rental_present
            and response_state.rental_value == pre_state.rental_value
            and parse_relative_rental_days(response_state.rental_value) is not None
            and response_state.point_present
            and response_state.point_metadata_complete
            and response_state.point_type == 0
            and response_state.point_amount == 0
            and response_state.is_charge_needed_present
        ):
            raise UnknownPageStateError("ComicFUZ direct viewer response does not match its rental")
        if not is_canonical_viewer_url(page.url, chapter_id=chapter_id):
            raise UnknownPageStateError("ComicFUZ direct viewer did not reach the canonical target")
        await wait_for_native_viewer_presence(
            page,
            work_id=work_id,
            chapter_id=chapter_id,
        )
        post_state = await read_native_ticket_snapshot(
            page,
            work_id=work_id,
            chapter_id=chapter_id,
            page_mode="ticket_post",
        )
        if not (
            post_state.work_id == work_id
            and post_state.chapter_id == chapter_id
            and post_state.viewer_chapter_id == chapter_id
            and post_state.chapter_label == pre_state.chapter_label
            and post_state.rental_present
            and post_state.rental_value == pre_state.rental_value
            and post_state.rental_value == response_state.rental_value
            and parse_relative_rental_days(post_state.rental_value) is not None
            and _native_point_is_known_zero(post_state)
            and post_state.point_type == 0
            and post_state.point_amount == 0
            and post_state.is_charge_needed == response_state.is_charge_needed
            and post_state.is_charge_needed_present
                == response_state.is_charge_needed_present
        ):
            raise UnknownPageStateError("ComicFUZ fresh direct viewer state does not match response")
        if route_failure is not None or request_count != 1:
            raise UnknownPageStateError(
                route_failure or "direct_viewer_request_count_changed"
            )
        operation_succeeded = True
        return DirectRentalViewerResult(
            snapshot=post_state,
            assert_route_healthy=assert_route_healthy,
        )
    finally:
        operation_active = False
        page.remove_listener("response", on_response)


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


_TICKET_MODAL_INSPECTOR = r"""({chapterLabel, chargeLabel, cancelLabel, appLabel, commentsLabel}) => {
  const visible=element=>{
    if(!element||!element.getClientRects().length)return false;
    for(let node=element;node;node=node.parentElement){
      const style=getComputedStyle(node);
      if(node.hidden||style.display==='none'||style.visibility==='hidden'
        ||style.visibility==='collapse'||Number(style.opacity)===0)return false;
    }
    return true;
  };
  const norm=value=>String(value||'').trim().replace(/\s+/g,' ');
  const classNames=element=>typeof element.className==='string'
    ?element.className.split(/\s+/).filter(Boolean):[];
  const hasClassPrefix=(element,prefix)=>classNames(element).some(name=>name.startsWith(prefix));
  const exactLeaves=(root,label)=>[...root.querySelectorAll('*')].filter(element=>
    visible(element)&&norm(element.innerText)===label
      &&![...element.children].some(child=>norm(child.innerText)===label));
  const dialogRoots=[...document.querySelectorAll('div[class*="Dialog_modal__"]')]
    .filter(visible);
  const modal=dialogRoots.length===1?dialogRoots[0]:null;
  const globalExactCtas=exactLeaves(document,chargeLabel);
  const globalCtas=globalExactCtas.filter(element=>element.tagName==='A'
    &&hasClassPrefix(element,'Dialog_buttons__active__'));
  const modalCtas=modal?globalCtas.filter(element=>modal.contains(element)):[];
  const cta=modalCtas.length===1?modalCtas[0]:null;
  const titles=modal?[...modal.querySelectorAll('p[class*="Dialog_chapter__mainText__"]')]
    .filter(visible):[];
  const chapterTitleMatch=titles.length===1&&norm(titles[0].innerText)===chapterLabel;
  const cancels=modal?exactLeaves(modal,cancelLabel):[];
  const ones=modal?exactLeaves(modal,'1'):[];
  const amountNodes=modal?[...modal.querySelectorAll('p[class*="Dialog_items__amount__"]')]
    .filter(visible):[];
  const itemClasses=element=>classNames(element)
    .filter(name=>name.startsWith('Dialog_items__'));
  const unknownPriceMarkers=modal?[...modal.querySelectorAll('[class*="Dialog_items__"]')]
    .filter(element=>{
      if(!visible(element))return false;
      return itemClasses(element).some(name=>{
        const knownSemantic=name.startsWith('Dialog_items__item__')
          ||name.startsWith('Dialog_items__amount__')||name.startsWith('Dialog_items__icon__');
        const generatedRoot=!name.slice('Dialog_items__'.length).includes('__');
        return !knownSemantic&&!generatedRoot;
      });
    }):[];
  const directText=element=>[...element.childNodes].filter(node=>node.nodeType===Node.TEXT_NODE)
    .map(node=>node.textContent||'').join('').trim();
  const ticketCountOne=amountNodes.length===1&&amountNodes[0].tagName==='P'
    &&directText(amountNodes[0])==='1'&&norm(amountNodes[0].innerText)==='1'
    &&ones.length===1&&ones[0]===amountNodes[0]
    &&unknownPriceMarkers.length===0;
  const controls=modal?[...modal.querySelectorAll('a,button,[role="button"]')]
    .filter(visible):[];
  const countLabel=label=>controls.filter(element=>norm(element.innerText)===label).length;
  const appControls=controls.filter(element=>norm(element.innerText)===appLabel);
  const commentsControls=controls.filter(element=>norm(element.innerText)===commentsLabel);
  const cancelControls=controls.filter(element=>norm(element.innerText)===cancelLabel);
  const appAnchors=appControls.filter(element=>element.tagName==='A'
    &&classNames(element).length===0);
  const appButtons=appControls.filter(element=>element.tagName==='BUTTON'
    &&hasClassPrefix(element,'Dialog_appflow__button__'));
  const allowedControls={app:countLabel(appLabel),comments:countLabel(commentsLabel),cancel:countLabel(cancelLabel)};
  const allowedControlShapes={
    app:appControls.length===2&&appAnchors.length===1&&appButtons.length===1,
    comments:commentsControls.length===1&&commentsControls[0].tagName==='A'
      &&hasClassPrefix(commentsControls[0],'Dialog_buttons__active__'),
    cancel:cancelControls.length===1&&cancelControls[0].tagName==='A'
      &&hasClassPrefix(cancelControls[0],'Dialog_buttons__cancel__')
  };
  const otherAccess=controls.filter(element=>element!==cta
    &&![appLabel,commentsLabel,cancelLabel].includes(norm(element.innerText)));
  const disabled=!cta||!!cta.disabled||cta.getAttribute('aria-disabled')==='true'
    ||!!cta.closest('button[disabled],[aria-disabled="true"]');
  const exact=dialogRoots.length===1&&globalExactCtas.length===1&&globalCtas.length===1&&modalCtas.length===1
    &&chapterTitleMatch&&cancels.length===1&&ticketCountOne
    &&allowedControls.app===2&&allowedControls.comments===1&&allowedControls.cancel===1
    &&allowedControlShapes.app&&allowedControlShapes.comments&&allowedControlShapes.cancel
    &&otherAccess.length===0&&!disabled;
  return {dialogRootCount:dialogRoots.length,modal:!!modal,modalRoot:modal,cta,
    globalCtaCount:globalExactCtas.length,
    ctaCount:modalCtas.length,chapterTitleCount:titles.length,chapterTitleMatch,
    cancelCount:cancels.length,priceAmountCount:amountNodes.length,
    unknownPriceMarkerCount:unknownPriceMarkers.length,
    priceDirectTextOne:amountNodes.length===1&&directText(amountNodes[0])==='1',
    ticketCountOne,allowedControls,allowedControlShapes,
    otherAccessCount:otherAccess.length,disabled,ctaText:cta?norm(cta.innerText):'',
    tag:cta?cta.tagName:'',exact};
}"""


async def read_ticket_modal(page: Page, *, chapter_label: str) -> dict[str, object]:
    """Require one visible target-bound Work Ticket modal action before attempt."""

    script = (
        f"args => {{const result=({_TICKET_MODAL_INSPECTOR})(args);"
        "const {modalRoot,cta,...safe}=result;return safe;}"
    )
    value = await page.evaluate(
        script,
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


async def find_ticket_modal_cta(page: Page, *, chapter_label: str) -> Locator:
    """Resolve the exact CTA from the same unique visible modal contract."""

    state = await read_ticket_modal(page, chapter_label=chapter_label)
    if state.get("exact") is not True:
        raise UnknownPageStateError("ComicFUZ ticket modal is not exact before CTA selection")

    async def is_dom_visible(locator: Locator) -> bool:
        return await locator.evaluate(
            """element => {
              if(!element||!element.getClientRects().length)return false;
              for(let node=element;node;node=node.parentElement){
                const style=getComputedStyle(node);
                if(node.hidden||style.display==='none'||style.visibility==='hidden'
                  ||style.visibility==='collapse'||Number(style.opacity)===0)return false;
              }
              return true;
            }"""
        )

    roots = page.locator('div[class*="Dialog_modal__"]')
    visible_roots = []
    for index in range(await roots.count()):
        candidate = roots.nth(index)
        if await is_dom_visible(candidate):
            visible_roots.append(candidate)
    if len(visible_roots) != 1:
        raise UnknownPageStateError("ComicFUZ ticket modal root is not unique and visible")

    candidates = visible_roots[0].locator('a[class*="Dialog_buttons__active__"]')
    matching_ctas = []
    for index in range(await candidates.count()):
        candidate = candidates.nth(index)
        if (
            await is_dom_visible(candidate)
            and " ".join((await candidate.inner_text()).split()) == TICKET_CTA_LABEL
        ):
            matching_ctas.append(candidate)
    if len(matching_ctas) != 1:
        raise UnknownPageStateError("ComicFUZ ticket CTA is not unique within its modal")
    return matching_ctas[0]


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
            modal.get("dialogRootCount") != 1
            or modal.get("globalCtaCount") != 1
            or modal.get("ctaCount") != 1
            or modal.get("modal") is not True
            or modal.get("exact") is not True
            or modal.get("chapterTitleMatch") is not True
            or modal.get("chapterTitleCount") != 1
            or modal.get("cancelCount") != 1
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
            if route_failure is None:
                route_failure = reason
            if operation_active and not response_future.done():
                response_future.set_exception(UnknownPageStateError(route_failure))

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
                or not is_target_viewer_url(page_url, chapter_id=self.chapter_id)
                or not is_target_viewer_url(frame_url, chapter_id=self.chapter_id)
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
            arming_script = f"""config => {{
              const scope=({_TICKET_MODAL_INSPECTOR})(config);
              if(!scope.exact||!scope.modalRoot||!scope.cta)
                throw new Error('target ticket modal is not exact');
              const cta=scope.cta;
              document.addEventListener('click',event=>{{
                if(event.isTrusted===true&&(event.target===cta||cta.contains(event.target))){{
                  const report=window[config.bindingName];
                  if(typeof report==='function')report({{nonce:config.nonce,count:1,trusted:true,
                    chapterLabel:config.chapterLabel,chargeLabel:config.chargeLabel}}).catch(()=>{{}});
                }}
              }},true);
            }}"""
            await page.evaluate(
                arming_script,
                {
                    "nonce": click_nonce,
                    "chapterLabel": chapter_label,
                    "chargeLabel": TICKET_CTA_LABEL,
                    "cancelLabel": TICKET_CANCEL_LABEL,
                    "appLabel": TICKET_APP_LABEL,
                    "commentsLabel": TICKET_COMMENTS_LABEL,
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
                    route_failure or "ticket_request_or_response_missing",
                    cause=exc,
                )
            if (
                consuming_requests != 1
                or response.status != 200
                or request_started_at is None
                or route_failure is not None
            ):
                await self._mark_unknown(
                    attempt_reporter,
                    route_failure or "ticket_api_response_unconfirmed",
                )
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
            relative_rental_days = (
                parse_relative_rental_days(response_metadata.rental_value)
                if response_metadata.rental_present
                else None
            )
            grant_expiry: datetime | None = None
            if response_metadata.rental_present and relative_rental_days is None:
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
                    lambda url: is_target_viewer_url(str(url), chapter_id=self.chapter_id),
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
            post_snapshot_mode = (
                "ticket_post" if relative_rental_days is not None else "viewer"
            )
            while asyncio.get_running_loop().time() < deadline:
                try:
                    post_state = await read_native_ticket_snapshot(
                        page,
                        work_id=self.work_id,
                        chapter_id=self.chapter_id,
                        page_mode=post_snapshot_mode,
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
            if relative_rental_days is not None:
                if not (
                    response_metadata.rental_present
                    and response_metadata.rental_value != native_state.rental_value
                    and post_state.rental_present
                    and parse_relative_rental_days(post_state.rental_value)
                    == relative_rental_days
                    and post_state.rental_value == response_metadata.rental_value
                ):
                    await self._mark_unknown(
                        attempt_reporter,
                        "relative_rental_marker_mismatch",
                    )
                if not (
                    response_metadata.point_present
                    and response_metadata.point_metadata_complete
                    and response_metadata.point_type == 0
                    and response_metadata.point_amount == 0
                ):
                    await self._mark_unknown(
                        attempt_reporter,
                        "relative_rental_response_point_not_zero",
                    )
                if not _native_point_is_known_zero(post_state):
                    await self._mark_unknown(
                        attempt_reporter,
                        "relative_rental_post_point_not_zero_or_unproven",
                    )
                if (
                    self._now().astimezone(JST).date()
                    != response_confirmed_at.astimezone(JST).date()
                ):
                    await self._mark_unknown(
                        attempt_reporter,
                        "relative_rental_post_state_crossed_jst_midnight",
                    )
                expiry = None
            else:
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
                    route_failure,
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
                            reason=route_failure
                            or "ticket_action_interrupted_or_proof_incomplete",
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
