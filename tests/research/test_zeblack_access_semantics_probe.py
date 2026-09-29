from __future__ import annotations

import hashlib
import json

from poc.zeblack_access_semantics_probe import (
    chapter_id_wire_correlation,
    compare_field_shapes,
    compare_reports,
    parse_protobuf_wire,
    wire_records_by_chapter,
)


def _varint(value: int) -> bytes:
    output = bytearray()
    while value >= 0x80:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def _field(field_number: int, value: int) -> bytes:
    return _varint(field_number << 3) + _varint(value)


def _message(field_number: int, payload: bytes) -> bytes:
    return _varint((field_number << 3) | 2) + _varint(len(payload)) + payload


def test_raw_protobuf_wire_parser_correlates_known_chapter_ids_without_schema_names() -> None:
    payload = _message(1, _field(1, 132107) + _field(2, 5123)) + _message(1, _field(1, 224191))
    wire = parse_protobuf_wire(payload)
    correlation = chapter_id_wire_correlation(wire, {"132107", "224191", "999999"})

    assert wire["complete"] is True
    assert correlation["matched_chapter_ids"] == ["132107", "224191"]
    assert correlation["unmatched_chapter_ids"] == ["999999"]
    records = wire_records_by_chapter(wire, correlation)
    assert records["132107"]["fields"][0]["varint"] == 132107


def test_wire_projection_applies_only_frontend_evidenced_field_names() -> None:
    payload = _message(1, _field(1, 132107) + _field(11, 2) + _field(12, 40))
    wire = parse_protobuf_wire(payload)
    correlation = chapter_id_wire_correlation(wire, {"132107"})
    records = wire_records_by_chapter(wire, correlation)

    fields = {field["field_number"]: field for field in records["132107"]["fields"]}
    assert fields[11]["field_name"] == "status"
    assert fields[11]["enum_name"] == "TICKET_AVAILABLE"
    assert fields[12]["field_name"] == "price"


def test_state_field_shape_comparison_keeps_group_boundaries() -> None:
    records = {
        "free": {"fields": [{"field_number": 1}, {"field_number": 3}]},
        "ticket": {"fields": [{"field_number": 1}, {"field_number": 11}, {"field_number": 12}]},
    }
    result = compare_field_shapes(records, {"free_unconditional": ["free"], "ticket_available_now": ["ticket"]})

    assert result["free_unconditional"]["common_field_numbers"] == [1, 3]
    assert result["ticket_available_now"]["common_field_numbers"] == [1, 11, 12]


def test_raw_protobuf_hash_is_bytes_based() -> None:
    payload = b"\x00\xff\x80protobuf"
    assert hashlib.sha256(payload).hexdigest() == "7da7ad371674ea71a400779adb62a31c4e9760d99e91a5b351fe4f2409bcd1d2"


def test_before_after_comparison_reports_state_and_raw_hash_changes(tmp_path) -> None:
    before = {
        "state_sequence": [{"chapter_id": "132107", "derived_state": "ticket_candidate_later"}],
        "state_counts": {"ticket_candidate_later": 1},
        "protobuf": {"raw_sha256": "before"},
    }
    after = {
        "state_sequence": [{"chapter_id": "132107", "derived_state": "ticket_available_now"}],
        "state_counts": {"ticket_available_now": 1},
        "protobuf": {"raw_sha256": "after"},
    }
    before_path = tmp_path / "before.json"
    after_path = tmp_path / "after.json"
    before_path.write_text(json.dumps(before), encoding="utf-8")
    after_path.write_text(json.dumps(after), encoding="utf-8")

    result = compare_reports(before_path, after_path)

    assert result["chapter_state_changes"] == [
        {"chapter_id": "132107", "before": "ticket_candidate_later", "after": "ticket_available_now"}
    ]
    assert result["protobuf_raw_sha256_before"] == "before"
    assert result["protobuf_raw_sha256_after"] == "after"
