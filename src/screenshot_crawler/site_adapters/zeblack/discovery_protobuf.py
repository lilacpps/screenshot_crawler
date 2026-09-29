"""Bounded production decoder for Zeblack's chapter-list protobuf.

The site does not expose a generated Python schema.  The frontend evidence
recovered by the Z4-0.5 probe identifies the small ``ChapterV3`` contract, so
this module contains a deliberately narrow wire decoder rather than a generic
protobuf framework.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any

MAX_PROTOBUF_BODY_BYTES = 4_000_000
MAX_PROTOBUF_DEPTH = 12
MAX_FIELDS_PER_MESSAGE = 512
MAX_MESSAGES_VISITED = 100_000


class ZeblackProtobufError(ValueError):
    """Raised when a response cannot be safely decoded as a chapter list."""


class ConsumptionStatus(IntEnum):
    FREE = 0
    RENTAL = 1
    TICKET_AVAILABLE = 2
    TICKET_UNAVAILABLE = 3
    POINT = 4
    COIN = 5
    TICKET_UNAVAILABLE_COIN_ONLY = 6


CONSUMPTION_STATUS_NAMES = {
    int(status): status.name for status in ConsumptionStatus
}

CHAPTER_V3_FIELD_NAMES = {
    1: "id",
    2: "titleId",
    3: "mainName",
    4: "alreadyViewed",
    5: "remainingRentalTime",
    6: "campaignLabel",
    7: "canComment",
    8: "numberOfComments",
    9: "isUpdated",
    10: "isAdvanced",
    11: "status",
    12: "price",
    13: "canUseVideoReward",
    14: "publishedDeadline",
    15: "consumptionDialog",
}


@dataclass(frozen=True, slots=True)
class ZeblackChapterV3:
    """Production fields required to create one Discovery record."""

    chapter_id: str
    title_id: str
    main_name: str
    remaining_rental_time: int | None
    status_value: int
    price: int | None

    @property
    def status_name(self) -> str:
        return CONSUMPTION_STATUS_NAMES.get(self.status_value, "UNKNOWN")


@dataclass(frozen=True, slots=True)
class _WireField:
    field_number: int
    wire_type: int
    value: int | bytes
    nested: tuple[_WireField, ...] | None = None


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    cursor = offset
    for _ in range(10):
        if cursor >= len(data):
            raise ZeblackProtobufError("truncated protobuf varint")
        byte = data[cursor]
        cursor += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, cursor
        shift += 7
    raise ZeblackProtobufError("protobuf varint is too long")


def _parse_message(
    data: bytes,
    *,
    depth: int,
) -> tuple[_WireField, ...]:
    if depth > MAX_PROTOBUF_DEPTH:
        raise ZeblackProtobufError("protobuf nesting depth exceeded")

    fields: list[_WireField] = []
    offset = 0
    while offset < len(data):
        if len(fields) >= MAX_FIELDS_PER_MESSAGE:
            raise ZeblackProtobufError("protobuf message has too many fields")
        key, offset = _read_varint(data, offset)
        field_number = key >> 3
        wire_type = key & 0x07
        if field_number <= 0 or wire_type == 3 or wire_type == 4 or wire_type > 5:
            raise ZeblackProtobufError("invalid protobuf field key")

        if wire_type == 0:
            value, offset = _read_varint(data, offset)
            fields.append(_WireField(field_number, wire_type, value))
        elif wire_type == 1:
            end = offset + 8
            if end > len(data):
                raise ZeblackProtobufError("truncated protobuf fixed64 field")
            fields.append(_WireField(field_number, wire_type, data[offset:end]))
            offset = end
        elif wire_type == 2:
            length, offset = _read_varint(data, offset)
            end = offset + length
            if end > len(data):
                raise ZeblackProtobufError("truncated protobuf length-delimited field")
            payload = data[offset:end]
            offset = end
            nested: tuple[_WireField, ...] | None = None
            if payload and depth < MAX_PROTOBUF_DEPTH:
                try:
                    nested = _parse_message(
                        payload,
                        depth=depth + 1,
                    )
                except ZeblackProtobufError:
                    # A length-delimited field may be a string, bytes, or a
                    # nested message. Only a message that parses completely is
                    # traversed; the enclosing wire message remains valid.
                    nested = None
            fields.append(_WireField(field_number, wire_type, payload, nested))
        else:
            end = offset + 4
            if end > len(data):
                raise ZeblackProtobufError("truncated protobuf fixed32 field")
            fields.append(_WireField(field_number, wire_type, data[offset:end]))
            offset = end
    return tuple(fields)


def parse_zeblack_protobuf_wire(data: bytes) -> tuple[_WireField, ...]:
    """Parse bounded protobuf wire data and fail closed on malformed input."""

    if not isinstance(data, bytes):
        raise ZeblackProtobufError("protobuf body must be bytes")
    if len(data) > MAX_PROTOBUF_BODY_BYTES:
        raise ZeblackProtobufError("protobuf body exceeds the production limit")
    if not data:
        raise ZeblackProtobufError("protobuf body is empty")
    return _parse_message(data, depth=0)


def _walk_messages(
    fields: tuple[_WireField, ...], *, visited: list[int]
) -> list[tuple[_WireField, ...]]:
    visited[0] += 1
    if visited[0] > MAX_MESSAGES_VISITED:
        raise ZeblackProtobufError("protobuf message count exceeded")
    result = [fields]
    for field in fields:
        if field.nested is not None:
            result.extend(_walk_messages(field.nested, visited=visited))
    return result


def _fields_by_number(fields: tuple[_WireField, ...], number: int) -> tuple[_WireField, ...]:
    return tuple(field for field in fields if field.field_number == number)


def _single_field(
    fields: tuple[_WireField, ...], number: int, *, required: bool
) -> _WireField | None:
    matches = _fields_by_number(fields, number)
    if len(matches) > 1:
        raise ZeblackProtobufError(f"ChapterV3 field {number} is duplicated")
    if not matches:
        if required:
            raise ZeblackProtobufError(f"ChapterV3 field {number} is missing")
        return None
    return matches[0]


def _decode_utf8(field: _WireField) -> str | None:
    if field.wire_type != 2 or not isinstance(field.value, bytes):
        return None
    try:
        value = field.value.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not value.strip():
        return None
    return value


def _decode_varint(field: _WireField, number: int) -> int:
    if field.wire_type != 0 or not isinstance(field.value, int):
        raise ZeblackProtobufError(f"ChapterV3 field {number} is not a varint")
    return field.value


def _chapter_candidate(fields: tuple[_WireField, ...], expected_title_id: str) -> ZeblackChapterV3 | None:
    id_fields = _fields_by_number(fields, 1)
    title_fields = _fields_by_number(fields, 2)
    name_fields = _fields_by_number(fields, 3)
    # Containers such as TitleChapterListViewV3 may repeat field 1 while
    # lacking the ChapterV3 identity triplet. They are not candidates and
    # must not be rejected as duplicate ChapterV3 records.
    if not id_fields or not title_fields or not name_fields:
        return None
    if len(id_fields) > 1 or len(title_fields) > 1 or len(name_fields) > 1:
        return None
    required = (id_fields[0], title_fields[0], name_fields[0])
    id_field, title_field, name_field = required
    assert id_field is not None and title_field is not None and name_field is not None
    if id_field.wire_type != 0 or title_field.wire_type != 0:
        return None
    chapter_id_value = _decode_varint(id_field, 1)
    title_id_value = _decode_varint(title_field, 2)
    main_name = _decode_utf8(name_field)
    if main_name is None:
        return None
    if chapter_id_value <= 0 or str(title_id_value) != str(expected_title_id):
        return None

    field_numbers = {field.field_number for field in fields}
    if not field_numbers.intersection(set(CHAPTER_V3_FIELD_NAMES) - {1, 2, 3}):
        return None

    rental_field = _single_field(fields, 5, required=False)
    status_field = _single_field(fields, 11, required=False)
    price_field = _single_field(fields, 12, required=False)
    if any(
        field is not None and field.wire_type != 0
        for field in (rental_field, status_field, price_field)
    ):
        return None
    return ZeblackChapterV3(
        chapter_id=str(chapter_id_value),
        title_id=str(title_id_value),
        main_name=main_name,
        remaining_rental_time=(
            _decode_varint(rental_field, 5) if rental_field is not None else None
        ),
        status_value=_decode_varint(status_field, 11) if status_field is not None else 0,
        price=_decode_varint(price_field, 12) if price_field is not None else None,
    )


def decode_zeblack_chapter_records(
    data: bytes, *, expected_title_id: str
) -> dict[str, ZeblackChapterV3]:
    """Decode unique, title-correlated ChapterV3 messages from one body."""

    fields = parse_zeblack_protobuf_wire(data)
    records: dict[str, ZeblackChapterV3] = {}
    for message in _walk_messages(fields, visited=[0]):
        candidate = _chapter_candidate(message, expected_title_id)
        if candidate is None:
            continue
        if candidate.chapter_id in records:
            raise ZeblackProtobufError(
                f"duplicate ChapterV3 chapter_id: {candidate.chapter_id}"
            )
        records[candidate.chapter_id] = candidate
    if not records:
        raise ZeblackProtobufError("no correlated ChapterV3 records were decoded")
    return records


def map_zeblack_access_mode(status: int | ConsumptionStatus) -> str:
    """Map the recovered enum to the site-neutral Catalog access mode."""

    try:
        value = int(status)
    except (TypeError, ValueError):
        return "unknown"
    return {
        int(ConsumptionStatus.FREE): "free",
        int(ConsumptionStatus.RENTAL): "quota",
        int(ConsumptionStatus.TICKET_AVAILABLE): "quota",
        int(ConsumptionStatus.TICKET_UNAVAILABLE): "quota",
        int(ConsumptionStatus.POINT): "quota",
        int(ConsumptionStatus.COIN): "paid",
        int(ConsumptionStatus.TICKET_UNAVAILABLE_COIN_ONLY): "paid",
    }.get(value, "unknown")


def decoded_chapter_content(records: dict[str, ZeblackChapterV3]) -> tuple[tuple[Any, ...], ...]:
    """Return a field-order-independent value for duplicate response checks."""

    return tuple(
        (
            record.chapter_id,
            record.title_id,
            record.main_name,
            record.remaining_rental_time,
            record.status_value,
            record.price,
        )
        for record in sorted(records.values(), key=lambda item: item.chapter_id)
    )


__all__ = [
    "CHAPTER_V3_FIELD_NAMES",
    "CONSUMPTION_STATUS_NAMES",
    "MAX_PROTOBUF_BODY_BYTES",
    "ConsumptionStatus",
    "ZeblackChapterV3",
    "ZeblackProtobufError",
    "decode_zeblack_chapter_records",
    "decoded_chapter_content",
    "map_zeblack_access_mode",
    "parse_zeblack_protobuf_wire",
]
