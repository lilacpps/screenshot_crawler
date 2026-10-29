from __future__ import annotations

import asyncio
from typing import ClassVar

import pytest

from screenshot_crawler.site_adapters.zeblack.live_access import (
    ZeblackLiveAccessError,
    observe_zeblack_chapter_list,
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
        self.request = type("Request", (), {"url": self.url})()

    async def body(self) -> bytes:
        return self._body


class _HangingResponse(_Response):
    async def body(self) -> bytes:
        await asyncio.sleep(3600)
        return self._body


class _Page:
    def __init__(self, payload: bytes) -> None:
        self.url = "about:blank"
        self.payload = payload
        self.listeners: list[object] = []
        self.request_listeners: list[object] = []

    def on(self, event: str, listener: object) -> None:
        if event == "response":
            self.listeners.append(listener)
        elif event == "request":
            self.request_listeners.append(listener)

    def remove_listener(self, event: str, listener: object) -> None:
        if event == "response" and listener in self.listeners:
            self.listeners.remove(listener)
        elif event == "request" and listener in self.request_listeners:
            self.request_listeners.remove(listener)

    async def goto(self, url: str, **_kwargs: object) -> None:
        self.url = url
        response = _Response(self.payload)
        for listener in tuple(self.request_listeners):
            listener(response.request)
        for listener in tuple(self.listeners):
            listener(response)  # type: ignore[operator]

    async def wait_for_timeout(self, _milliseconds: int) -> None:
        return None


class _HangingBodyPage(_Page):
    async def goto(self, url: str, **_kwargs: object) -> None:
        self.url = url
        response = _HangingResponse(self.payload)
        for listener in tuple(self.request_listeners):
            listener(response.request)
        for listener in tuple(self.listeners):
            listener(response)  # type: ignore[operator]


@pytest.mark.parametrize("state", ["same", "changed", "timeout"])
async def test_prepared_observation_binds_the_document_within_its_deadline(state: str) -> None:
    class Document:
        async def evaluate(self, _expression):
            if state == "timeout":
                await asyncio.sleep(3600)
            return state == "same"

    class DocumentPage(_Page):
        def locator(self, selector):
            assert selector == "html"
            return self

        async def element_handle(self, **_kwargs):
            return document

    document = Document()
    page = DocumentPage(_payload(_chapter(101, 2, "#17")))
    if state == "same":
        snapshot = await observe_zeblack_chapter_list(
            page, title_id="5123", timeout_ms=50, capture_document=True
        )
        assert snapshot.document is document and snapshot.ticket_available_ids == ("101",)
    else:
        with pytest.raises(ZeblackLiveAccessError, match="document changed"):
            await observe_zeblack_chapter_list(
                page, title_id="5123", timeout_ms=50, capture_document=True
            )
    assert page.listeners == []
    assert page.request_listeners == []


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


async def test_chapter_observation_ignores_late_response_from_before_its_navigation():
    class StaleResponse(_Response):
        async def body(self):
            pytest.fail("A previous navigation's response must never be read")

    stale = StaleResponse(_payload(_chapter(999, 2, "old")))

    class PageWithStaleResponse(_Page):
        async def goto(self, url, **kwargs):
            for listener in tuple(self.listeners):
                listener(stale)
            await super().goto(url, **kwargs)

    page = PageWithStaleResponse(_payload(_chapter(101, 2, "new")))
    snapshot = await observe_zeblack_chapter_list(page, title_id="5123", timeout_ms=100)
    assert tuple(snapshot.by_id) == ("101",)
    assert page.listeners == [] and page.request_listeners == []


@pytest.mark.asyncio
async def test_live_access_fails_closed_when_target_is_missing() -> None:
    page = _Page(_payload(_chapter(101, 2, "#17")))

    with pytest.raises(ZeblackLiveAccessError, match="did not contain"):
        await observe_zeblack_live_access(
            page, title_id="5123", chapter_id="999", timeout_ms=1000
        )


@pytest.mark.asyncio
async def test_chapter_list_response_body_wait_is_bounded() -> None:
    page = _HangingBodyPage(_payload(_chapter(101, 2, "#17")))

    with pytest.raises(
        ZeblackLiveAccessError,
        match="protobuf response body timed out",
    ):
        await observe_zeblack_chapter_list(page, title_id="5123", timeout_ms=50)

    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_chapter_list_observation_propagates_cancellation() -> None:
    page = _HangingBodyPage(_payload(_chapter(101, 2, "#17")))
    observation = asyncio.create_task(
        observe_zeblack_chapter_list(page, title_id="5123", timeout_ms=5000)
    )
    await asyncio.sleep(0.01)
    observation.cancel()

    with pytest.raises(asyncio.CancelledError):
        await observation
