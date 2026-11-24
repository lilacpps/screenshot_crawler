from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from screenshot_crawler.core.errors import UnknownPageStateError
from screenshot_crawler.site_adapters.comicfuz.work_ticket import (
    API_HOST,
    API_PATH,
    MAX_VIEWER_RESPONSE_BYTES,
    decode_viewer_request,
    decode_viewer_response,
    is_canonical_viewer_api_request,
    is_canonical_viewer_url,
    is_exact_ticket_request,
    is_target_viewer_url,
    is_ticket_viewer_url,
    is_zero_cost_direct_request,
    parse_relative_rental_days,
    parse_rental_expiry,
    read_bounded_viewer_response_body,
)


def _varint(value: int) -> bytes:
    encoded = bytearray()
    while value > 0x7F:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _number(field: int, value: int) -> bytes:
    return _varint(field << 3) + _varint(value)


def _bytes(field: int, value: bytes) -> bytes:
    return _varint((field << 3) | 2) + _varint(len(value)) + value


def _viewer_request(
    *,
    chapter_id: int = 76630,
    use_ticket: bool | None = True,
    free_points: int = 0,
    paid_points: int = 0,
    include_points: bool = True,
    unknown_field: bool = False,
) -> bytes:
    device = _bytes(1, b"opaque-secret-not-retained") + _bytes(2, b"test") + _number(3, 2)
    point = b""
    if free_points:
        point += _number(1, free_points)
    if paid_points:
        point += _number(2, paid_points)
    message = _bytes(1, device)
    if use_ticket is not None:
        message += _number(2, int(use_ticket))
    if include_points:
        message += _bytes(3, point)
    message += _number(4, chapter_id)
    if unknown_field:
        message += _number(9, 1)
    return message


def test_viewer_request_decodes_target_and_does_not_retain_device_secret() -> None:
    body = _viewer_request()

    decoded = decode_viewer_request(body)

    assert decoded.chapter_id == 76630
    assert decoded.use_ticket is True
    assert decoded.point_free == 0
    assert decoded.point_paid == 0
    assert "opaque-secret" not in repr(decoded)
    assert is_exact_ticket_request(body, chapter_id="76630")


def test_direct_request_accepts_proto3_omission_of_false_and_zero_point_fields() -> None:
    body = _viewer_request(use_ticket=None, include_points=False)

    decoded = decode_viewer_request(body)

    assert decoded.use_ticket is False
    assert decoded.point_free == decoded.point_paid == 0
    assert is_zero_cost_direct_request(body, chapter_id="76630")
    assert not is_exact_ticket_request(body, chapter_id="76630")


@pytest.mark.parametrize(
    "body",
    [
        _viewer_request(chapter_id=76631),
        _viewer_request(free_points=1),
        _viewer_request(paid_points=1),
        _viewer_request(unknown_field=True),
        _viewer_request(use_ticket=False),
    ],
)
def test_ticket_request_rejects_wrong_target_cost_or_mode(body: bytes) -> None:
    assert not is_exact_ticket_request(body, chapter_id="76630")


def test_direct_request_rejects_nonzero_points_and_unknown_fields() -> None:
    assert not is_zero_cost_direct_request(
        _viewer_request(use_ticket=None, paid_points=1), chapter_id="76630"
    )
    assert not is_zero_cost_direct_request(
        _viewer_request(use_ticket=None, unknown_field=True), chapter_id="76630"
    )


def test_ticket_viewer_url_requires_only_exact_ticket_query() -> None:
    assert is_ticket_viewer_url(
        "https://comic-fuz.com/manga/viewer/76630?ticket=true", chapter_id="76630"
    )
    for url in (
        "https://comic-fuz.com/manga/viewer/76630",
        "https://comic-fuz.com/manga/viewer/76631?ticket=true",
        "https://comic-fuz.com/manga/viewer/76630?ticket=false",
        "https://comic-fuz.com/manga/viewer/76630?ticket=true&point=1",
        "http://comic-fuz.com/manga/viewer/76630?ticket=true",
        "https://comic-fuz.com.evil.example/manga/viewer/76630?ticket=true",
    ):
        assert not is_ticket_viewer_url(url, chapter_id="76630")


def test_target_viewer_url_accepts_only_canonical_or_exact_ticket_route() -> None:
    canonical = "https://comic-fuz.com/manga/viewer/76630"
    ticket = f"{canonical}?ticket=true"
    assert is_canonical_viewer_url(canonical, chapter_id="76630")
    assert is_target_viewer_url(canonical, chapter_id="76630")
    assert not is_canonical_viewer_url(ticket, chapter_id="76630")
    assert is_ticket_viewer_url(ticket, chapter_id="76630")
    assert is_target_viewer_url(ticket, chapter_id="76630")

    for url in (
        "https://comic-fuz.com/manga/3667",
        "https://comic-fuz.com/manga/viewer/76631",
        "https://comic-fuz.com/manga/viewer/76631?ticket=true",
        f"{canonical}?other=1",
        f"{ticket}&other=1",
        f"{ticket}&ticket=true",
        f"{canonical}?",
        f"{canonical}#",
        f"{ticket}#section",
        "https://comic-fuz.com:443/manga/viewer/76630",
        "https://comic-fuz.com:9443/manga/viewer/76630?ticket=true",
        "http://comic-fuz.com/manga/viewer/76630",
        "https://user@comic-fuz.com/manga/viewer/76630",
        "https://comic-fuz.com.evil.example/manga/viewer/76630",
    ):
        assert not is_target_viewer_url(url, chapter_id="76630")


@pytest.mark.parametrize(
    ("url", "method", "expected"),
    [
        (f"https://{API_HOST}{API_PATH}", "POST", True),
        (f"http://{API_HOST}{API_PATH}", "POST", False),
        (f"https://{API_HOST}:9443{API_PATH}", "POST", False),
        (f"https://user@{API_HOST}{API_PATH}", "POST", False),
        (f"https://{API_HOST}{API_PATH}?unexpected=1", "POST", False),
        (f"https://{API_HOST}/other", "POST", False),
        (f"https://{API_HOST}{API_PATH}", "GET", False),
    ],
)
def test_viewer_api_requires_exact_canonical_request(url, method, expected) -> None:
    assert is_canonical_viewer_api_request(url, method) is expected


@pytest.mark.asyncio
async def test_viewer_response_declared_size_limit_precedes_body_read() -> None:
    class Response:
        def __init__(self) -> None:
            self.headers = {"content-length": str(MAX_VIEWER_RESPONSE_BYTES + 1)}
            self.body_calls = 0

        async def body(self) -> bytes:
            self.body_calls += 1
            return b"too large"

    response = Response()
    with pytest.raises(ValueError, match="declared size limit"):
        await read_bounded_viewer_response_body(response, timeout=1)
    assert response.body_calls == 0


@pytest.mark.asyncio
async def test_viewer_response_body_read_is_timed_and_post_read_bounded() -> None:
    class HangingResponse:
        def __init__(self) -> None:
            self.headers = {}

        async def body(self) -> bytes:
            await asyncio.Event().wait()
            return b"unreachable"

    with pytest.raises(TimeoutError):
        await read_bounded_viewer_response_body(HangingResponse(), timeout=0.01)

    class LargeResponse:
        def __init__(self) -> None:
            self.headers = {}

        async def body(self) -> bytes:
            return b"x" * (MAX_VIEWER_RESPONSE_BYTES + 1)

    with pytest.raises(ValueError, match="body size limit"):
        await read_bounded_viewer_response_body(LargeResponse(), timeout=1)


def test_rental_expiry_requires_explicit_timezone() -> None:
    assert parse_rental_expiry("2026-11-25T00:00:00+09:00") == datetime.fromisoformat(
        "2026-11-25T00:00:00+09:00"
    )
    assert parse_rental_expiry("") is None
    with pytest.raises(UnknownPageStateError):
        parse_rental_expiry("2026-11-25T00:00:00")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("残り2日", 2),
        ("残り1日", 1),
        ("残り0日", None),
        ("残り02日", None),
        ("残り-1日", None),
        ("残り2 日", None),
        ("2026-11-25T00:00:00+09:00", None),
        ("", None),
        (None, None),
    ],
)
def test_relative_rental_marker_is_recognized_without_deriving_expiry(
    value: object, expected: int | None
) -> None:
    assert parse_relative_rental_days(value) == expected


def _viewer_response(
    *,
    manga_id: int = 3667,
    chapter_id: int = 76630,
    ticket_available: bool = False,
    charge_status: str = "0時に回復!",
    rental_expiry: str = "2026-11-25T00:00:00+09:00",
    point_amount: int = 30,
    include_rental: bool = True,
    include_page: bool = True,
    include_point: bool = True,
    unknown_point_field: bool = False,
) -> bytes:
    manga = _number(1, manga_id)
    if ticket_available:
        manga += _number(12, 1)
    manga += _number(13, 1) + _bytes(18, charge_status.encode())
    point = _number(2, point_amount) if point_amount else b""
    if unknown_point_field:
        point += _number(3, 1)
    chapter = _number(1, chapter_id)
    if include_point:
        chapter += _bytes(5, point)
    if include_rental:
        chapter += _bytes(10, rental_expiry.encode())
    group = _bytes(2, chapter)
    viewer_data = _bytes(2, _bytes(1, b"page-envelope")) if include_page else b""
    return (
        _bytes(2, viewer_data)
        + _bytes(5, group)
        + _bytes(11, manga)
        + _number(12, chapter_id)
    )


def test_web_manga_viewer2_response_decodes_exact_native_access_projection() -> None:
    decoded = decode_viewer_response(
        _viewer_response(), work_id="3667", chapter_id="76630"
    )

    assert decoded.manga_id == 3667
    assert decoded.chapter_id == 76630
    assert decoded.ticket_available is False
    assert decoded.ticket_available_present is False
    assert decoded.is_charge_needed is True
    assert decoded.charge_status == "0時に回復!"
    assert decoded.rental_value == "2026-11-25T00:00:00+09:00"
    assert decoded.rental_present is True
    assert decoded.point_type == 0
    assert decoded.point_amount == 30
    assert decoded.point_present is True
    assert decoded.point_metadata_complete is True


def test_viewer_response_distinguishes_present_default_zero_point_from_missing() -> None:
    present_default = decode_viewer_response(
        _viewer_response(point_amount=0), work_id="3667", chapter_id="76630"
    )
    missing = decode_viewer_response(
        _viewer_response(include_point=False), work_id="3667", chapter_id="76630"
    )

    assert present_default.point_present is True
    assert present_default.point_metadata_complete is True
    assert present_default.point_type == 0 and present_default.point_amount == 0
    assert missing.point_present is False
    assert missing.point_type is None and missing.point_amount is None


def test_viewer_response_marks_unknown_point_cost_fields_incomplete() -> None:
    decoded = decode_viewer_response(
        _viewer_response(point_amount=0, unknown_point_field=True),
        work_id="3667",
        chapter_id="76630",
    )

    assert decoded.point_present is True
    assert decoded.point_type == 0 and decoded.point_amount == 0
    assert decoded.point_metadata_complete is False


@pytest.mark.parametrize(
    "body,work_id",
    [
        (_viewer_response(manga_id=3668), "3667"),
        (_viewer_response(chapter_id=76631), "3667"),
        (_viewer_response() + _number(12, 76630), "3667"),
    ],
)
def test_web_manga_viewer2_response_rejects_incomplete_or_mismatched_access(body, work_id) -> None:
    with pytest.raises(ValueError):
        decode_viewer_response(body, work_id=work_id, chapter_id="76630")


def test_web_manga_viewer2_consumption_metadata_does_not_require_grant_expiry() -> None:
    decoded = decode_viewer_response(
        _viewer_response(include_rental=False), work_id="3667", chapter_id="76630"
    )

    assert decoded.ticket_available is False
    assert decoded.charge_status == "0時に回復!"
    assert decoded.rental_value == ""
    assert decoded.rental_present is False


def test_web_manga_viewer2_response_preserves_ticket_still_available_state() -> None:
    decoded = decode_viewer_response(
        _viewer_response(ticket_available=True),
        work_id="3667",
        chapter_id="76630",
    )

    assert decoded.ticket_available is True
    assert decoded.ticket_available_present is True
