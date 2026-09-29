from __future__ import annotations

import hashlib
import json

from poc.zeblack_access_semantics_probe import (
    _load_protobuf_artifact,
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


def _string_field(field_number: int, value: str) -> bytes:
    encoded = value.encode("utf-8")
    return _varint((field_number << 3) | 2) + _varint(len(encoded)) + encoded


def _chapter(chapter_id: int, title_id: int = 5123, label: str = "#1") -> bytes:
    return b"".join(
        (
            _field(1, chapter_id),
            _field(2, title_id),
            _string_field(3, label),
            _field(7, 1),
            _field(8, 1),
        )
    )


def test_raw_protobuf_wire_parser_correlates_known_chapter_ids_with_chapter_shape() -> None:
    payload = _message(1, _chapter(132107)) + _message(1, _chapter(224191, label="#26"))
    wire = parse_protobuf_wire(payload)
    correlation = chapter_id_wire_correlation(
        wire, {"132107", "224191", "999999"}, expected_title_id="5123"
    )

    assert wire["complete"] is True
    assert correlation["matched_chapter_ids"] == ["132107", "224191"]
    assert correlation["unmatched_chapter_ids"] == ["999999"]
    assert correlation["dom_only_ids"] == ["999999"]
    assert correlation["protobuf_only_ids"] == []
    records = wire_records_by_chapter(wire, correlation)
    assert records["132107"]["fields"][0]["varint"] == 132107


def test_wire_projection_applies_only_frontend_evidenced_field_names() -> None:
    payload = _message(
        1,
        _chapter(132107)
        + _field(11, 2)
        + _field(12, 40),
    )
    wire = parse_protobuf_wire(payload)
    correlation = chapter_id_wire_correlation(
        wire, {"132107"}, expected_title_id="5123", schema_recovered=True
    )
    records = wire_records_by_chapter(wire, correlation, schema_recovered=True)

    fields = {field["field_number"]: field for field in records["132107"]["fields"]}
    assert fields[11]["field_name"] == "status"
    assert fields[11]["enum_name"] == "TICKET_AVAILABLE"
    assert fields[12]["field_name"] == "price"


def test_protobuf_only_ids_are_reported_directionally() -> None:
    payload = _message(1, _chapter(132107)) + _message(1, _chapter(224191)) + _message(
        1, _chapter(999999, label="#99")
    )
    correlation = chapter_id_wire_correlation(
        parse_protobuf_wire(payload), {"132107", "224191"}, expected_title_id="5123"
    )

    assert correlation["intersection"] == ["132107", "224191"]
    assert correlation["dom_only_ids"] == []
    assert correlation["protobuf_only_ids"] == ["999999"]
    assert correlation["matched_count"] == 2


def test_dom_only_ids_are_reported_directionally() -> None:
    payload = _message(1, _chapter(132107)) + _message(1, _chapter(224191))
    correlation = chapter_id_wire_correlation(
        parse_protobuf_wire(payload),
        {"132107", "224191", "999999"},
        expected_title_id="5123",
    )

    assert correlation["intersection"] == ["132107", "224191"]
    assert correlation["dom_only_ids"] == ["999999"]
    assert correlation["protobuf_only_ids"] == []


def test_exact_dom_and_protobuf_sets_have_no_directional_unmatched_ids() -> None:
    payload = _message(1, _chapter(132107)) + _message(1, _chapter(224191))
    correlation = chapter_id_wire_correlation(
        parse_protobuf_wire(payload), {"132107", "224191"}, expected_title_id="5123"
    )

    assert correlation["chapter_record_count"] == 2
    assert correlation["matched_count"] == 2
    assert correlation["dom_only_count"] == 0
    assert correlation["protobuf_only_count"] == 0


def test_unrelated_numeric_field_one_message_is_not_a_chapter_v3_record() -> None:
    unrelated = _message(1, _field(1, 132107) + _field(2, 5123))
    valid = _message(1, _chapter(224191))
    correlation = chapter_id_wire_correlation(
        parse_protobuf_wire(unrelated + valid),
        {"132107", "224191"},
        expected_title_id="5123",
    )

    assert correlation["matched_chapter_ids"] == ["224191"]
    assert correlation["dom_only_ids"] == ["132107"]


def test_schema_evidence_gates_chapter_record_extraction(tmp_path) -> None:
    output_dir = tmp_path / "probe"
    (output_dir / "protobuf").mkdir(parents=True)
    (output_dir / "protobuf" / "response.bin").write_bytes(_message(1, _chapter(132107)))

    without_schema = _load_protobuf_artifact(
        output_dir,
        {"132107"},
        expected_title_id="5123",
        frontend_schema_evidence={
            "frontend_decoder_observed": False,
            "chapter_schema_recovered": False,
            "consumption_status_enum_recovered": False,
        },
    )
    assert without_schema["protobuf_body_observed"] is True
    assert without_schema["chapter_schema_recovered"] is False
    assert without_schema["chapter_record_count"] == 0
    assert without_schema["dom_only_ids"] == ["132107"]

    with_schema = _load_protobuf_artifact(
        output_dir,
        {"132107"},
        expected_title_id="5123",
        frontend_schema_evidence={
            "frontend_decoder_observed": True,
            "chapter_schema_recovered": True,
            "consumption_status_enum_recovered": True,
        },
    )
    assert with_schema["chapter_schema_recovered"] is True
    assert with_schema["chapter_record_count"] == 1
    assert with_schema["matched_count"] == 1
    assert with_schema["dom_only_ids"] == []
    assert with_schema["protobuf_only_ids"] == []


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
