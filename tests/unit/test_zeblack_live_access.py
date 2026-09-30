from __future__ import annotations

from typing import ClassVar

import pytest

from screenshot_crawler.site_adapters.zeblack.live_access import (
    ZeblackLiveAccessError,
    observe_zeblack_live_access,
    parse_zeblack_chapter_list_title_id,
)


def _varint(value: int) -> bytes:
    result = bytearray()
    while value >= 0x80:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value)
    return bytes(result)


def _field(number: int, value: int) -> bytes:
    return _varint(number << 3) + _varint(value)


def _string_field(number: int, value: str) -> bytes:
    encoded = value.encode()
    return _varint((number << 3) | 2) + _varint(len(encoded)) + encoded


def _message(number: int, payload: bytes) -> bytes:
    return _varint((number << 3) | 2) + _varint(len(payload)) + payload


def _chapter(chapter_id: int, status: int, label: str) -> bytes:
    return b"".join(
        (
            _field(1, chapter_id),
            _field(2, 5123),
            _string_field(3, label),
            _field(7, 1),
            _field(11, status),
        )
    )


def _payload(*chapters: bytes) -> bytes:
    return b"".join(_message(1, chapter) for chapter in chapters)


class _Response:
    url = "https://api2.zebrack-comic.com/api/v3/title_chapter_list"
    status = 200
    headers: ClassVar[dict[str, str]] = {"content-type": "application/protobuf"}

    def __init__(self, body: bytes) -> None:
        self._body = body

    async def body(self) -> bytes:
        return self._body


class _Page:
    def __init__(self, payload: bytes) -> None:
        self.url = "about:blank"
        self.payload = payload
        self.listeners: list[object] = []

    def on(self, event: str, listener: object) -> None:
        if event == "response":
            self.listeners.append(listener)

    def remove_listener(self, event: str, listener: object) -> None:
        if event == "response" and listener in self.listeners:
            self.listeners.remove(listener)

    async def goto(self, url: str, **_kwargs: object) -> None:
        self.url = url
        response = _Response(self.payload)
        for listener in tuple(self.listeners):
            listener(response)  # type: ignore[operator]

    async def wait_for_timeout(self, _milliseconds: int) -> None:
        return None


def test_zeblack_chapter_list_title_parser_is_strict() -> None:
    assert (
        parse_zeblack_chapter_list_title_id(
            "https://zebrack-comic.shueisha.co.jp/title/5123/chapter/list?tab=all"
        )
        == "5123"
    )
    assert parse_zeblack_chapter_list_title_id("http://zebrack-comic.shueisha.co.jp/title/5123/chapter/list") is None
    assert parse_zeblack_chapter_list_title_id("https://example.test/title/5123/chapter/list") is None


@pytest.mark.asyncio
async def test_live_access_returns_target_status_and_all_ticket_ids() -> None:
    page = _Page(
        _payload(
            _chapter(101, 2, "#17"),
            _chapter(202, 4, "#18"),
            _chapter(303, 2, "#27"),
        )
    )

    state = await observe_zeblack_live_access(
        page, title_id="5123", chapter_id="202", timeout_ms=1000
    )

    assert state.status_name == "POINT"
    assert state.status_value == 4
    assert state.target_main_name == "#18"
    assert state.ticket_available_ids == ("101", "303")


@pytest.mark.asyncio
async def test_live_access_fails_closed_when_target_is_missing() -> None:
    page = _Page(_payload(_chapter(101, 2, "#17")))

    with pytest.raises(ZeblackLiveAccessError, match="did not contain"):
        await observe_zeblack_live_access(
            page, title_id="5123", chapter_id="999", timeout_ms=1000
        )
