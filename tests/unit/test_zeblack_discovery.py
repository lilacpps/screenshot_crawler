from __future__ import annotations

import pytest

from screenshot_crawler.discovery import DiscoveryIncompleteError
from screenshot_crawler.site_adapters.zeblack.discovery import (
    ZeblackDiscoveryAdapter,
    parse_zeblack_chapter_list_url,
    parse_zeblack_order_label,
)
from screenshot_crawler.site_adapters.zeblack.discovery_protobuf import (
    ConsumptionStatus,
    ZeblackProtobufError,
    decode_zeblack_chapter_records,
    map_zeblack_access_mode,
)
from screenshot_crawler.watchlist import DiscoveryScope, WatchlistTarget


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


def _chapter(
    chapter_id: int,
    *,
    title_id: int = 5123,
    label: str = "#1",
    status: int | None = None,
    price: int | None = None,
) -> bytes:
    fields = [
        _field(1, chapter_id),
        _field(2, title_id),
        _string_field(3, label),
        _field(7, 1),
    ]
    if status is not None:
        fields.append(_field(11, status))
    if price is not None:
        fields.append(_field(12, price))
    return b"".join(fields)


def _payload(*chapters: bytes) -> bytes:
    return b"".join(_message(1, chapter) for chapter in chapters)


def _target(*, scope: DiscoveryScope | None = None) -> WatchlistTarget:
    return WatchlistTarget(
        key="zeblack-test",
        work_key="zeblack-work",
        site="zeblack",
        url="https://zebrack-comic.shueisha.co.jp/title/5123/chapter/list",
        label="Zeblack Test",
        discovery_scope=scope,
    )


class _FakeRow:
    def __init__(self, chapter_id: str) -> None:
        self.chapter_id = chapter_id

    async def get_attribute(self, name: str) -> str | None:
        return f"chapter{self.chapter_id}" if name == "id" else None


class _FakeLocator:
    def __init__(self, rows: list[str]) -> None:
        self.rows = rows

    async def count(self) -> int:
        return len(self.rows)

    def nth(self, index: int) -> _FakeRow:
        return _FakeRow(self.rows[index])


class _FakeResponse:
    def __init__(self, body: bytes, *, status: int = 200, content_type: str = "application/protobuf"):
        self.url = "https://api2.zebrack-comic.com/api/v3/title_chapter_list"
        self.status = status
        self.headers = {"content-type": content_type}
        self._body = body

    async def body(self) -> bytes:
        return self._body


class _FakePage:
    def __init__(self, rows: list[str], responses: list[_FakeResponse]) -> None:
        self.url = "about:blank"
        self._rows = rows
        self._responses = responses
        self._listeners: list[object] = []

    def on(self, event: str, listener: object) -> None:
        if event == "response":
            self._listeners.append(listener)

    def remove_listener(self, event: str, listener: object) -> None:
        if event == "response" and listener in self._listeners:
            self._listeners.remove(listener)

    def locator(self, _selector: str) -> _FakeLocator:
        return _FakeLocator(self._rows)

    async def goto(self, url: str, **_kwargs: object) -> None:
        self.url = url
        for response in self._responses:
            for listener in tuple(self._listeners):
                listener(response)  # type: ignore[operator]

    async def wait_for_timeout(self, _milliseconds: int) -> None:
        return None


def test_zeblack_list_url_parser_is_strict_and_canonical() -> None:
    identity = parse_zeblack_chapter_list_url(
        "https://zebrack-comic.shueisha.co.jp/title/5123/chapter/list?tab=all#top"
    )
    assert identity is not None
    assert identity.title_id == "5123"
    assert identity.canonical_url.endswith("/title/5123/chapter/list")
    for url in (
        "http://zebrack-comic.shueisha.co.jp/title/5123/chapter/list",
        "https://example.test/title/5123/chapter/list",
        "https://zebrack-comic.shueisha.co.jp/title/5123/chapter/list/",
        "https://zebrack-comic.shueisha.co.jp/title/x/chapter/list",
        "https://user:z@zebrack-comic.shueisha.co.jp/title/5123/chapter/list",
        "https://zebrack-comic.shueisha.co.jp:443/title/5123/chapter/list",
    ):
        assert parse_zeblack_chapter_list_url(url) is None


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (ConsumptionStatus.FREE, "free"),
        (ConsumptionStatus.RENTAL, "quota"),
        (ConsumptionStatus.TICKET_AVAILABLE, "quota"),
        (ConsumptionStatus.TICKET_UNAVAILABLE, "quota"),
        (ConsumptionStatus.POINT, "quota"),
        (ConsumptionStatus.COIN, "paid"),
        (ConsumptionStatus.TICKET_UNAVAILABLE_COIN_ONLY, "paid"),
        (99, "unknown"),
    ],
)
def test_zeblack_access_mapping(status: int, expected: str) -> None:
    assert map_zeblack_access_mode(status) == expected


def test_zeblack_protobuf_defaults_status_and_decodes_required_fields() -> None:
    records = decode_zeblack_chapter_records(
        _payload(_chapter(101, label="#17"), _chapter(202, label="special", status=5, price=40)),
        expected_title_id="5123",
    )
    assert records["101"].status_value == 0
    assert records["101"].status_name == "FREE"
    assert records["101"].main_name == "#17"
    assert records["202"].status_name == "COIN"
    assert records["202"].price == 40


@pytest.mark.parametrize(
    "payload",
    [
        _payload(_chapter(101, title_id=9999)),
        _message(1, _field(1, 101) + _field(2, 5123)),
        _message(1, _field(1, 101) + _field(2, 5123) + _string_field(3, "")),
        _payload(_chapter(101))[:-1],
    ],
)
def test_zeblack_protobuf_rejects_invalid_or_unrelated_messages(payload: bytes) -> None:
    with pytest.raises(ZeblackProtobufError):
        decode_zeblack_chapter_records(payload, expected_title_id="5123")


def test_zeblack_protobuf_rejects_duplicate_ids_and_oversized_body() -> None:
    with pytest.raises(ZeblackProtobufError):
        decode_zeblack_chapter_records(
            _payload(_chapter(101), _chapter(101, label="#2")),
            expected_title_id="5123",
        )
    with pytest.raises(ZeblackProtobufError):
        decode_zeblack_chapter_records(b"\x00" * 4_000_001, expected_title_id="5123")


@pytest.mark.parametrize(
    ("label", "order_key", "order_label"),
    [
        ("#17", "17", "#17"),
        ("#17 chapter title", "17", "#17 chapter title"),
        ("special", None, "special"),
    ],
)
def test_zeblack_order_metadata_is_conservative(
    label: str, order_key: str | None, order_label: str
) -> None:
    assert parse_zeblack_order_label(label) == (order_key, order_label)


@pytest.mark.asyncio
async def test_zeblack_full_discovery_is_latest_first_and_buffered() -> None:
    payload = _payload(
        _chapter(101, label="#1", status=0),
        _chapter(202, label="#2", status=2),
        _chapter(303, label="bonus", status=5),
    )
    records = [
        record
        async for record in ZeblackDiscoveryAdapter().iter_records(
            _FakePage(["101", "202", "303"], [_FakeResponse(payload)]),
            _target(),
            "full",
        )
    ]
    assert [record.source.external_id for record in records] == ["303", "202", "101"]
    assert [record.item.order_key for record in records] == [None, "2", "1"]
    assert [record.source.access_mode for record in records] == ["paid", "quota", "free"]


@pytest.mark.asyncio
async def test_zeblack_bounded_discovery_is_inclusive_and_uses_chapter_id_only() -> None:
    payload = _payload(
        _chapter(101, label="#1"),
        _chapter(202, label="#2"),
        _chapter(303, label="bonus"),
        _chapter(404, label="#4"),
    )
    target = _target(
        scope=DiscoveryScope(
            from_url="https://zebrack-comic.shueisha.co.jp/title/5123/chapter/303/viewer",
            through_url="https://zebrack-comic.shueisha.co.jp/title/5123/chapter/202/viewer?x=1",
        )
    )
    records = [
        record
        async for record in ZeblackDiscoveryAdapter().iter_records(
            _FakePage(["101", "202", "303", "404"], [_FakeResponse(payload)]),
            target,
            "full",
        )
    ]
    assert [record.source.external_id for record in records] == ["303", "202"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope",
    [
        DiscoveryScope(from_url="https://zebrack-comic.shueisha.co.jp/title/9999/chapter/202/viewer"),
        DiscoveryScope(from_url="https://zebrack-comic.shueisha.co.jp/title/5123/chapter/999/viewer"),
        DiscoveryScope(
            from_url="https://zebrack-comic.shueisha.co.jp/title/5123/chapter/101/viewer",
            through_url="https://zebrack-comic.shueisha.co.jp/title/5123/chapter/202/viewer",
        ),
        DiscoveryScope(from_url="https://example.test/title/5123/chapter/202/viewer"),
    ],
)
async def test_zeblack_invalid_boundaries_fail_closed_without_yield(
    scope: DiscoveryScope,
) -> None:
    payload = _payload(_chapter(101, label="#1"), _chapter(202, label="#2"))
    yielded: list[object] = []
    with pytest.raises(DiscoveryIncompleteError):
        async for record in ZeblackDiscoveryAdapter().iter_records(
            _FakePage(["101", "202"], [_FakeResponse(payload)]),
            _target(scope=scope),
            "full",
        ):
            yielded.append(record)
    assert yielded == []
    # temporary patch marker
    # temporary patch marker
@pytest.mark.asyncio
async def test_zeblack_conflicting_duplicate_responses_fail_closed() -> None:
    first = _payload(_chapter(101, label="#1"), _chapter(202, label="#2"))
    second = _payload(_chapter(101, label="#1"), _chapter(202, label="#9"))
    with pytest.raises(DiscoveryIncompleteError):
        records = [
            record
            async for record in ZeblackDiscoveryAdapter().iter_records(
                _FakePage(["101", "202"], [_FakeResponse(first), _FakeResponse(second)]),
                _target(),
                "full",
            )
        ]
        assert records == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("dom_rows", "payload_rows"),
    [
        (["101", "202", "303"], [101, 202]),  # DOM-only
        (["101", "202"], [101, 202, 303]),  # protobuf-only
        (["101", "101"], [101]),  # duplicate DOM
    ],
)
async def test_zeblack_dom_and_protobuf_sets_must_match_before_yield(
    dom_rows: list[str], payload_rows: list[int]
) -> None:
    payload = _payload(*(_chapter(chapter_id, label=f"#{index + 1}") for index, chapter_id in enumerate(payload_rows)))
    yielded: list[object] = []
    with pytest.raises(DiscoveryIncompleteError):
        async for record in ZeblackDiscoveryAdapter().iter_records(
            _FakePage(dom_rows, [_FakeResponse(payload)]),
            _target(),
            "full",
        ):
            yielded.append(record)
    assert yielded == []
