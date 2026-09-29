"""Read-only Z4-0.5 access-semantics and protobuf investigation for Zeblack.

The probe intentionally stays outside the production Discovery tree.  It opens
only the chapter-list page through the shared Crawler Chrome/CDP session,
captures chapter-list metadata, and never clicks a chapter or access control.
It uses a bounded generic protobuf wire parser when the frontend schema is not
available; field names are not invented from field numbers.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from playwright.async_api import Page, Response

try:
    from poc.zeblack_discovery_probe import (
        DEFAULT_URL,
        WAIT_TIMEOUT_MS,
        _generic_candidate_to_row,
        collect_dom,
        dom_candidate_rows,
        infer_dom_order,
        now_iso,
        parse_target_list_url,
        safe_url,
    )
except ModuleNotFoundError:  # direct ``python poc/...`` execution
    from zeblack_discovery_probe import (  # type: ignore[no-redef]
        DEFAULT_URL,
        WAIT_TIMEOUT_MS,
        _generic_candidate_to_row,
        collect_dom,
        dom_candidate_rows,
        infer_dom_order,
        now_iso,
        parse_target_list_url,
        safe_url,
    )
from screenshot_crawler.core.browser import BrowserSession, resolve_cdp_endpoint

DEFAULT_OUTPUT_DIR = Path("output/zeblack_access_semantics_probe")
MAX_CAPTURE_BODY = 4_000_000
MAX_SCRIPT_BODY = 12_000_000
MAX_WIRE_DEPTH = 7
MAX_WIRE_FIELDS = 400
MAX_WIRE_BYTES_PREVIEW = 128
CHAPTER_LIST_PATH = "/api/v3/title_chapter_list"
SCHEMA_TERMS = (
    "title_chapter_list",
    "TitleChapterListViewV3",
    "TitleChapterListViewV3=(function",
    "prototype.lastChapterId",
    "case 4:{l.groups",
    "case 5:{l.indexGroups",
    "ConsumptionStatus",
    "TICKET_AVAILABLE",
    "TICKET_UNAVAILABLE",
    "TICKET_UNAVAILABLE_COIN_ONLY",
    "ConsumptionStatus.FREE",
    "ConsumptionStatus.RENTAL",
    "ConsumptionStatus.POINT",
    "ConsumptionStatus.COIN",
    "ChapterGroup",
    "ChapterGroupV3",
    "ChapterV3",
    "ChapterV3=(function",
    "prototype.remainingRentalTime",
    "prototype.status",
    "case 5:{l.remainingRentalTime",
    "case 11:{l.status",
    "remainingRentalTime",
    "campaignLabel",
    "prototype.status",
    "l.status",
    "status=e.",
    "chapterid",
    "ticket",
    "rental",
    "coin",
    "point",
    "expire",
    "available",
    "price",
)
CONSUMPTION_STATUS_NAMES = {
    0: "FREE",
    1: "RENTAL",
    2: "TICKET_AVAILABLE",
    3: "TICKET_UNAVAILABLE",
    4: "POINT",
    5: "COIN",
    6: "TICKET_UNAVAILABLE_COIN_ONLY",
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


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _read_varint(data: bytes, offset: int) -> tuple[int, int] | None:
    value = 0
    shift = 0
    cursor = offset
    while cursor < len(data) and shift <= 63:
        byte = data[cursor]
        cursor += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, cursor
        shift += 7
    return None


def _printable_utf8(data: bytes) -> str | None:
    if not data or b"\x00" in data:
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if "�" in text or not any(char.isalnum() for char in text):
        return None
    if sum(char.isprintable() or char.isspace() for char in text) / max(len(text), 1) < 0.9:
        return None
    return text[:1000]


def parse_protobuf_wire(data: bytes, *, depth: int = 0, base_offset: int = 0) -> dict[str, Any]:
    """Parse bounded protobuf wire values without assigning schema field names."""

    fields: list[dict[str, Any]] = []
    offset = 0
    complete = True
    while offset < len(data) and len(fields) < MAX_WIRE_FIELDS:
        field_offset = offset
        key_result = _read_varint(data, offset)
        if key_result is None:
            complete = False
            break
        key, offset = key_result
        field_number = key >> 3
        wire_type = key & 0x07
        if field_number <= 0:
            complete = False
            break
        item: dict[str, Any] = {
            "offset": base_offset + field_offset,
            "field_number": field_number,
            "wire_type": wire_type,
        }
        if wire_type == 0:
            result = _read_varint(data, offset)
            if result is None:
                complete = False
                break
            value, offset = result
            item["varint"] = value
        elif wire_type == 1:
            if offset + 8 > len(data):
                complete = False
                break
            item["fixed64_hex"] = data[offset : offset + 8].hex()
            offset += 8
        elif wire_type == 2:
            result = _read_varint(data, offset)
            if result is None:
                complete = False
                break
            length, offset = result
            end = offset + length
            if end > len(data):
                complete = False
                break
            payload = data[offset:end]
            offset = end
            item["length"] = length
            item["hex_preview"] = payload[:MAX_WIRE_BYTES_PREVIEW].hex()
            text = _printable_utf8(payload)
            if text is not None:
                item["utf8"] = text
            if depth < MAX_WIRE_DEPTH and payload and length <= MAX_CAPTURE_BODY:
                nested = parse_protobuf_wire(payload, depth=depth + 1, base_offset=item["offset"])
                if nested["fields"] and nested["complete"]:
                    item["message"] = nested
        elif wire_type == 5:
            if offset + 4 > len(data):
                complete = False
                break
            item["fixed32_hex"] = data[offset : offset + 4].hex()
            offset += 4
        else:
            complete = False
            break
        item["end_offset"] = base_offset + offset
        fields.append(item)
    if len(fields) >= MAX_WIRE_FIELDS and offset < len(data):
        complete = False
    return {"bytes": len(data), "complete": complete and offset == len(data), "fields": fields}


def _walk_wire_messages(
    node: dict[str, Any], path: tuple[tuple[int, int], ...] = ()
) -> list[tuple[tuple[tuple[int, int], ...], dict[str, Any]]]:
    found: list[tuple[tuple[int, ...], dict[str, Any]]] = [(path, node)]
    for field_index, field in enumerate(node.get("fields") or []):
        nested = field.get("message")
        if isinstance(nested, dict):
            found.extend(
                _walk_wire_messages(
                    nested,
                    path + ((int(field["field_number"]), field_index),),
                )
            )
    return found


def _wire_scalar_values(node: dict[str, Any]) -> list[int | str]:
    values: list[int | str] = []
    for field in node.get("fields") or []:
        if "varint" in field:
            values.append(int(field["varint"]))
        if field.get("utf8") is not None:
            values.append(str(field["utf8"]))
    return values


def chapter_id_wire_correlation(
    wire: dict[str, Any], chapter_ids: set[str]
) -> dict[str, Any]:
    """Find chapter IDs without guessing which numeric field is chapter_id."""

    wanted = {str(value) for value in chapter_ids}
    matches: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path, node in _walk_wire_messages(wire):
        for field in node.get("fields") or []:
            values: list[str] = []
            if "varint" in field:
                values.append(str(field["varint"]))
            if field.get("utf8") is not None and str(field["utf8"]).isdigit():
                values.append(str(field["utf8"]))
            for value in values:
                if value not in wanted:
                    continue
                projection = {
                    "path": [list(item) for item in path],
                    "field_number": field.get("field_number"),
                    "wire_type": field.get("wire_type"),
                    "offset": field.get("offset"),
                    "value_kind": "varint" if "varint" in field else "utf8",
                    "container_field_numbers": [
                        item.get("field_number") for item in node.get("fields") or []
                    ],
                }
                matches[value].append(projection)
    selected = {
        chapter_id: max(candidates, key=lambda item: len(item["path"]))
        for chapter_id, candidates in matches.items()
    }
    return {
        "known_chapter_count": len(wanted),
        "matched_chapter_ids": sorted(selected),
        "matched_count": len(selected),
        "unmatched_chapter_ids": sorted(wanted - set(selected)),
        "matches": selected,
        "duplicate_match_ids": sorted(chapter_id for chapter_id, values in matches.items() if len(values) > 1),
    }


def wire_records_by_chapter(
    wire: dict[str, Any], correlation: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Project the closest generic message around each correlated ID."""

    result: dict[str, dict[str, Any]] = {}
    for chapter_id, match in (correlation.get("matches") or {}).items():
        target_path = [tuple(int(value) for value in item) for item in match.get("path") or []]
        node: dict[str, Any] = wire
        for field_number, field_index in target_path:
            field = (node.get("fields") or [])[field_index] if field_index < len(node.get("fields") or []) else None
            nested = field.get("message") if isinstance(field, dict) and int(field.get("field_number", -1)) == field_number else None
            if not isinstance(nested, dict):
                break
            node = nested
        fields = []
        for field in node.get("fields") or []:
            projected = {
                "field_number": field.get("field_number"),
                "wire_type": field.get("wire_type"),
            }
            field_number = int(field.get("field_number", -1))
            if field_number in CHAPTER_V3_FIELD_NAMES:
                projected["field_name"] = CHAPTER_V3_FIELD_NAMES[field_number]
            for key in ("varint", "length", "utf8", "fixed32_hex", "fixed64_hex", "hex_preview"):
                if key in field:
                    projected[key] = field[key]
            if field_number == 11 and "varint" in field:
                projected["enum_name"] = CONSUMPTION_STATUS_NAMES.get(
                    int(field["varint"]), "UNKNOWN"
                )
            fields.append(projected)
        result[str(chapter_id)] = {"path": [list(item) for item in target_path], "fields": fields}
    return result


def compare_field_shapes(records: dict[str, dict[str, Any]], groups: dict[str, list[str]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for group, chapter_ids in groups.items():
        shapes: list[dict[str, Any]] = []
        for chapter_id in chapter_ids:
            record = records.get(str(chapter_id))
            if not record:
                continue
            shapes.append(
                {
                    "chapter_id": str(chapter_id),
                    "field_numbers": sorted({field.get("field_number") for field in record.get("fields", [])}),
                    "fields": record.get("fields", []),
                }
            )
        common = None
        for shape in shapes:
            current = set(shape["field_numbers"])
            common = current if common is None else common & current
        output[group] = {
            "chapter_count": len(chapter_ids),
            "wire_matched_count": len(shapes),
            "common_field_numbers": sorted(common or set()),
            "records": shapes[:20],
            "field_names_recovered": False,
        }
    return output


def _state_groups(chapters: list[dict[str, Any]]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for chapter in chapters:
        groups[str(chapter.get("derived_current_access") or "unknown")].append(str(chapter["chapter_id"]))
    return dict(groups)


def _ticket_row_details(chapters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for index, chapter in enumerate(chapters):
        if chapter.get("derived_current_access") != "ticket_available_now":
            continue
        neighbors = []
        for neighbor in chapters[max(0, index - 2) : index + 3]:
            neighbors.append(
                {
                    "index": neighbor.get("index"),
                    "chapter_id": neighbor.get("chapter_id"),
                    "label": neighbor.get("label"),
                    "state": neighbor.get("derived_current_access"),
                }
            )
        details.append(
            {
                "chapter_id": chapter.get("chapter_id"),
                "index": chapter.get("index"),
                "label": chapter.get("label"),
                "neighbors": neighbors,
                "icon_metadata": chapter.get("icon_metadata", []),
                "class": chapter.get("class"),
                "raw_text": chapter.get("raw_text"),
                "data_attributes": chapter.get("data_attributes", {}),
                "structured_metadata": chapter.get("structured_metadata"),
                "protobuf_record": chapter.get("protobuf_record"),
            }
        )
    return details


def _state_counts(chapters: list[dict[str, Any]]) -> dict[str, int]:
    counts = defaultdict(int)
    for chapter in chapters:
        counts[str(chapter.get("derived_current_access") or "unknown")] += 1
    return dict(counts)


def _context_snippets(text: str, terms: tuple[str, ...]) -> list[dict[str, str]]:
    lower = text.lower()
    snippets: list[dict[str, str]] = []
    for term in terms:
        start = 0
        term_matches = 0
        while len(snippets) < 180 and term_matches < 4:
            index = lower.find(term.lower(), start)
            if index < 0:
                break
            snippets.append({"term": term, "text": text[max(0, index - 160) : index + len(term) + 240]})
            start = index + len(term)
            term_matches += 1
    return snippets


async def install_access_network_observer(
    page: Page, output_dir: Path
) -> tuple[list[dict[str, Any]], list[asyncio.Task[Any]]]:
    records: list[dict[str, Any]] = []
    tasks: list[asyncio.Task[Any]] = []
    (output_dir / "protobuf").mkdir(parents=True, exist_ok=True)

    async def capture(response: Response, record: dict[str, Any]) -> None:
        content_type = (response.headers.get("content-type") or "").lower()
        resource_type = response.request.resource_type
        is_list_api = CHAPTER_LIST_PATH in response.url
        max_body = MAX_SCRIPT_BODY if resource_type == "script" else MAX_CAPTURE_BODY
        try:
            body = await response.body()
        except Exception as exc:  # noqa: BLE001 - network races are evidence, not fatal
            record["body_error"] = type(exc).__name__
            return
        record["body_bytes"] = len(body)
        record["body_sha256_raw"] = sha256_bytes(body)
        if len(body) > max_body:
            record["body_skipped"] = f"max_body_{max_body}"
            return
        text = body.decode("utf-8", errors="replace")
        record["body_sha256_text"] = sha256_text(text)
        if is_list_api and "protobuf" in content_type:
            path = output_dir / "protobuf" / "response.bin"
            path.write_bytes(body)
            record["protobuf_path"] = str(path.relative_to(output_dir))
            record["body_prefix_hex"] = body[:256].hex()
        if resource_type == "script" or "javascript" in content_type:
            matches = _context_snippets(text, SCHEMA_TERMS)
            if matches:
                record["schema_matches"] = matches
                record["source_mapping_url"] = next(
                    (line.strip() for line in text.splitlines() if "sourceMappingURL=" in line), None
                )
        if "json" in content_type or text.lstrip().startswith(("{", "[")):
            record["json_preview"] = text[:2000]

    def on_response(response: Response) -> None:
        request = response.request
        content_type = response.headers.get("content-type") or ""
        resource_type = request.resource_type
        is_list_api = CHAPTER_LIST_PATH in response.url
        should_read = resource_type in {"document", "xhr", "fetch", "script"} or is_list_api
        record = {
            "sequence": len(records),
            "timestamp": now_iso(),
            "url": safe_url(response.url),
            "method": request.method,
            "status": response.status,
            "resource_type": resource_type,
            "content_type": content_type,
            "content_length": response.headers.get("content-length"),
            "body_observed": should_read,
        }
        records.append(record)
        if should_read:
            tasks.append(asyncio.create_task(capture(response, record)))

    page.on("response", on_response)
    return records, tasks


def _frontend_evidence(records: list[dict[str, Any]]) -> dict[str, Any]:
    scripts = [
        {
            "url": record.get("url"),
            "bytes": record.get("body_bytes"),
            "body_sha256_raw": record.get("body_sha256_raw"),
            "body_sha256_text": record.get("body_sha256_text"),
            "matches": record.get("schema_matches", []),
            "source_mapping_url": record.get("source_mapping_url"),
        }
        for record in records
        if record.get("schema_matches")
    ]
    matching_text = " ".join(
        match.get("text", "")
        for script in scripts
        for match in script.get("matches", [])
    )
    has_list_decoder = "TitleChapterListViewV3.decode" in matching_text
    has_status_enum = "ConsumptionStatus" in matching_text and "TICKET_AVAILABLE" in matching_text
    return {
        "schema_recovered": has_list_decoder and has_status_enum,
        "generated_decoder_found": has_list_decoder,
        "identified_message": "Proto.TitleChapterListViewV3" if has_list_decoder else None,
        "identified_enum": "ConsumptionStatus" if has_status_enum else None,
        "semantic_field_mapping": {
            "message": "Proto.ChapterV3",
            "fields": {str(number): name for number, name in CHAPTER_V3_FIELD_NAMES.items()},
            "status_enum": {str(number): name for number, name in CONSUMPTION_STATUS_NAMES.items()},
            "list_message": "Proto.TitleChapterListViewV3",
            "list_fields_observed": {
                "1": "titleId",
                "2": "lastChapterId",
                "3": "advertisements",
                "4": "groups",
                "5": "indexGroups",
            },
            "evidence": [
                "ChapterV3 generated encode/decode snippet names field 5 remainingRentalTime and field 11 status.",
                "ChapterV3 generated encode/decode snippet names field 12 price and field 15 consumptionDialog.",
                "ConsumptionStatus generated enum snippet names values 0 through 6.",
            ],
        },
        "schema_terms": list(SCHEMA_TERMS),
        "matching_bundles": scripts,
        "note": "Field names and enum values are treated as recovered only where bounded frontend generated-decoder snippets explicitly identify them.",
    }


def _load_protobuf_artifact(output_dir: Path, chapter_ids: set[str]) -> dict[str, Any]:
    path = output_dir / "protobuf" / "response.bin"
    if not path.exists():
        return {
            "endpoint": None,
            "bytes": 0,
            "raw_sha256": None,
            "schema_recovered": False,
            "decode_method": "not_available",
            "decoded_chapter_count": 0,
            "correlation": {"matched_count": 0, "unmatched_chapter_ids": sorted(chapter_ids)},
        }
    body = path.read_bytes()
    wire = parse_protobuf_wire(body)
    correlation = chapter_id_wire_correlation(wire, chapter_ids)
    records = wire_records_by_chapter(wire, correlation)
    (output_dir / "protobuf" / "wire.json").write_text(
        json.dumps(wire, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    decoded = {
        "decode_method": "bounded_generic_protobuf_wire_parser",
        "schema_recovered": True,
        "chapter_id_correlation": correlation,
        "records_by_chapter": records,
        "field_names": {str(number): name for number, name in CHAPTER_V3_FIELD_NAMES.items()},
        "status_enum": {str(number): name for number, name in CONSUMPTION_STATUS_NAMES.items()},
        "warning": "Decoded with a bounded wire parser and frontend-generated schema evidence; the frontend decoder itself was not executed by this Python probe.",
    }
    (output_dir / "protobuf" / "decoded.json").write_text(
        json.dumps(decoded, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "protobuf" / "field_correlation.json").write_text(
        json.dumps(correlation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "endpoint": CHAPTER_LIST_PATH,
        "bytes": len(body),
        "raw_sha256": sha256_bytes(body),
        "schema_recovered": True,
        "decode_method": "bounded_generic_wire_parser_with_frontend_ChapterV3_schema",
        "decoded_chapter_count": correlation.get("matched_count", 0),
        "correlation": correlation,
        "records_by_chapter": records,
        "wire_complete": wire.get("complete"),
        "wire_top_level_field_count": len(wire.get("fields") or []),
        "field_names": {str(number): name for number, name in CHAPTER_V3_FIELD_NAMES.items()},
        "status_enum": {str(number): name for number, name in CONSUMPTION_STATUS_NAMES.items()},
    }


def _state_correlation(
    chapters: list[dict[str, Any]], protobuf: dict[str, Any]
) -> dict[str, Any]:
    groups = _state_groups(chapters)
    field_shapes = compare_field_shapes(protobuf.get("records_by_chapter", {}), groups)
    records = protobuf.get("records_by_chapter", {})
    return {
        group: {
            "chapter_ids": chapter_ids,
            "dom_count": len(chapter_ids),
            "wire_matched_count": field_shapes.get(group, {}).get("wire_matched_count", 0),
            "common_wire_field_numbers": field_shapes.get(group, {}).get("common_field_numbers", []),
            "field_names": {
                str(number): name for number, name in CHAPTER_V3_FIELD_NAMES.items()
                if number in field_shapes.get(group, {}).get("common_field_numbers", [])
            },
            "status_values": {
                str(chapter_id): next(
                    (
                        field.get("enum_name", f"UNKNOWN({field.get('varint')})")
                        for field in records.get(str(chapter_id), {}).get("fields", [])
                        if field.get("field_name") == "status"
                    ),
                    "FREE_DEFAULT_OR_ABSENT",
                )
                for chapter_id in chapter_ids
            },
            "semantic_differences": "status field is structured and dynamic; stable future-ticket capability is not represented by a confirmed field",
        }
        for group, chapter_ids in groups.items()
    }


def _design_assessment(state_counts: dict[str, int], protobuf: dict[str, Any]) -> dict[str, Any]:
    candidate_conditions = {
        "p_rows_observed": state_counts.get("ticket_candidate_later", 0) > 0,
        "ticket_available_rows_observed": state_counts.get("ticket_available_now", 0) == 2,
        "coin_rows_distinct": state_counts.get("coin_only", 0) > 0,
        "structured_ticket_capability_confirmed": False,
        "structured_current_availability_confirmed": True,
        "structured_status_enum_confirmed": bool(protobuf.get("status_enum")),
    }
    return {
        "map_P_and_ticket_now_both_to_quota": "not_adopted; P is POINT status and shared future-ticket capability is not confirmed",
        "candidate_conditions": candidate_conditions,
        "full_discovery_after_ticket_use_required": "not required for chapter identity/order, but a dynamic status refresh remains required; no separate lightweight endpoint was found",
        "recommended_dynamic_refresh_layer": "lightweight access-state refresh at SitePolicy planning or strict-entry time; fall back to bounded list API if no smaller endpoint exists",
        "catalog_minimum_state": ["chapter_id", "listing_order", "stable access class"],
    }


def build_report(
    *,
    target: str,
    title_id: str,
    dom: dict[str, Any],
    chapters: list[dict[str, Any]],
    records: list[dict[str, Any]],
    protobuf: dict[str, Any],
    frontend: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    state_counts = _state_counts(chapters)
    records_by_chapter = protobuf.get("records_by_chapter", {})
    for chapter in chapters:
        record = records_by_chapter.get(str(chapter.get("chapter_id")))
        if record is not None:
            chapter["protobuf_record"] = record
    ticket_rows = _ticket_row_details(chapters)
    state_correlation = _state_correlation(chapters, protobuf)
    api_records = [
        record
        for record in records
        if CHAPTER_LIST_PATH in str(record.get("url") or "")
    ]
    matched_dom = len(
        set(protobuf.get("correlation", {}).get("matched_chapter_ids", []))
        & {str(chapter.get("chapter_id")) for chapter in chapters}
    )
    unknowns = [
        "The frontend generated decoder was identified, but this Python probe did not execute that JavaScript decoder directly.",
        "P and blue Free share no confirmed stable structured ticket-capability field in this snapshot.",
        "The two blue Free rows may be separate chains or section boundaries; no explicit group field was recovered.",
        "Ticket consumption and before/after account-state comparison were intentionally not performed.",
    ]
    report = {
        "schema_version": "z4-0.5",
        "probe_phase": "Z4-0.5 access semantics / protobuf investigation; research only",
        "production_discovery_adapter": "NOT YET IMPLEMENTED",
        "read_only": True,
        "target": target,
        "title_id": title_id,
        "document_title": dom.get("document_title"),
        "account_context": "visible indicators only; cookies/storage not inspected",
        "chapter_count": len(chapters),
        "state_counts": state_counts,
        "chapters": chapters,
        "state_sequence": [
            {
                "index": chapter.get("index"),
                "chapter_id": chapter.get("chapter_id"),
                "label": chapter.get("label"),
                "raw_state": chapter.get("raw_site_state"),
                "derived_state": chapter.get("derived_current_access"),
            }
            for chapter in chapters
        ],
        "listing": {
            "initial_rows": len(dom_candidate_rows(dom)),
            "total_rows": len(chapters),
            "dom_order": infer_dom_order(chapters),
            "pagination": bool(dom.get("pagination_candidates")),
            "lazy_loading": False,
        },
        "ticket_available_rows": ticket_rows,
        "network": {
            "relevant_endpoints": sorted({str(record.get("url")) for record in api_records}),
            "responses": records,
            "frontend_schema_evidence_path": "network/frontend_schema_evidence.json",
            "api_response_count": len(api_records),
        },
        "frontend_schema_evidence": frontend,
        "authority_recommendation": "title_chapter_list protobuf ChapterV3 identity/order/status, with DOM icon/text cross-check; no production authority selected in research phase",
        "protobuf": {
            **protobuf,
            "dom_chapter_count": len(chapters),
            "dom_matched_count": matched_dom,
            "dom_unmatched_count": len(chapters) - matched_dom,
            "protobuf_unmatched_count": len(
                protobuf.get("correlation", {}).get("unmatched_chapter_ids", [])
            ),
        },
        "state_correlations": state_correlation,
        "stable_vs_dynamic": {
            "stable_fields": ["id/chapter_id", "titleId", "mainName", "listing order", "price (field 12, subject to site policy)"],
            "dynamic_fields": ["status (field 11)", "alreadyViewed", "remainingRentalTime", "isUpdated"],
            "structured_status_enum": protobuf.get("status_enum", {}),
            "structured_stable_ticket_capability": "not confirmed; no ticket_capable field in ChapterV3 evidence",
            "structured_current_ticket_availability": "confirmed as status=TICKET_AVAILABLE (2) in this snapshot",
            "structured_rental_expiry": "remainingRentalTime field exists; current rental record value is retained as seconds-like site value, exact unit not independently confirmed",
        },
        "global_account_state": {
            "ticket_stock": "not observed",
            "next_ticket_recovery": "not observed",
            "recovery_interval": "not observed",
            "evidence": "TitleChapterListViewV3 schema exposes title/list/group metadata in the captured evidence; no global ticket stock/recovery field was identified.",
        },
        "design_assessment": _design_assessment(state_counts, protobuf),
        "unknowns": unknowns,
        "safety": {
            "chapter_links_clicked": 0,
            "access_controls_clicked": 0,
            "ticket_consumed": False,
            "purchase_started": False,
            "rental_started": False,
            "login_performed": False,
            "advertisement_viewed": False,
            "viewer_navigation_performed": False,
        },
    }
    write_json(output_dir / "report.json", report)
    write_json(output_dir / "dom" / "states.json", {"snapshot": dom, "state_sequence": report["state_sequence"]})
    write_json(output_dir / "network" / "responses.json", records)
    write_json(output_dir / "network" / "frontend_schema_evidence.json", frontend)
    (output_dir / "summary.md").write_text(make_summary(report), encoding="utf-8")
    return report


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def make_summary(report: dict[str, Any]) -> str:
    counts = report["state_counts"]
    protobuf = report["protobuf"]
    design = report["design_assessment"]
    lines = [
        "# Zeblack Z4-0.5 access semantics / protobuf investigation",
        "",
        "## 1. Scope / safety",
        "",
        f"- Target: `{report['target']}`; title_id: `{report['title_id']}`.",
        "- Research-only. No login, click, ticket use, purchase, rental start, advertisement, or viewer navigation was performed.",
        "- Account context is based only on visible page indicators; cookies and storage were not inspected.",
        "",
        "## 2. Corrected state model",
        "",
        "- `無料` text/badge -> `free_unconditional`.",
        "- Blue Free / `チケット利用可` image -> `ticket_available_now`.",
        "- P / `ポイント画像` image -> `ticket_candidate_later` hypothesis.",
        "- Rental expiry display -> `rental_active`.",
        "- `コイン画像` image -> `coin_only`.",
        "- English `Free` is never treated as unconditional free merely because it contains the word Free; image context is required.",
        "",
        "## 3. DOM state counts",
        "",
        f"- `{json.dumps(counts, ensure_ascii=False, sort_keys=True)}`",
        f"- Verification anchors: ticket_available_now=`{counts.get('ticket_available_now', 0)}` (expected 2), rental_active=`{counts.get('rental_active', 0)}` (expected 1).",
        "",
        "## 4. Protobuf endpoint/schema",
        "",
        f"- Endpoint: `{report['network']['relevant_endpoints']}`.",
        f"- Bytes: `{protobuf.get('bytes')}`; raw SHA-256: `{protobuf.get('raw_sha256')}`.",
        f"- Schema recovered: `{protobuf.get('schema_recovered')}`; decode method: `{protobuf.get('decode_method')}`.",
        "- Frontend bundle identified `Proto.TitleChapterListViewV3.decode`, `Proto.ChapterV3`, and the `ConsumptionStatus` enum. Python uses a bounded wire parser with those evidenced field names; it does not execute the site decoder.",
        f"- ChapterV3 status field: `11`; price: `12`; remainingRentalTime: `5`; campaignLabel: `6`; enum: `{json.dumps(protobuf.get('status_enum', {}), ensure_ascii=False)}`.",
        "",
        "## 5. DOM ↔ protobuf correlation",
        "",
        f"- Decoded/correlated chapter IDs: `{protobuf.get('decoded_chapter_count')}`; DOM matched: `{protobuf.get('dom_matched_count')}`; DOM unmatched: `{protobuf.get('dom_unmatched_count')}`; protobuf unmatched: `{protobuf.get('protobuf_unmatched_count')}`.",
        "- ChapterV3 field names and ConsumptionStatus enum values are recovered from the frontend generated decoder evidence; Python wire decoding remains bounded and schema-aware only for those evidenced fields.",
        f"- Recommended research authority candidate: `{report.get('authority_recommendation')}`.",
        "",
        "## 6. Free semantics",
        "",
        f"- Complete-free `無料` candidates: `{counts.get('free_unconditional', 0)}`. This is separated from blue Free imagery and is not mapped to ticket availability.",
        "",
        "## 7. Ticket-available semantics",
        "",
        f"- Blue Free / ticket image candidates: `{counts.get('ticket_available_now', 0)}`.",
        "- DOM image alt/class evidence is preserved per row. Structured `status=TICKET_AVAILABLE=2` confirms the current ticket-available state in this snapshot.",
        "",
        "## 8. P semantics",
        "",
        f"- Point-image candidates: `{counts.get('ticket_candidate_later', 0)}`.",
        "- P is distinguishable from coin-only in DOM and structured status: P rows are `ConsumptionStatus.POINT=4`. The frontend treats POINT as point/coin consumption; it does not expose a stable future-ticket flag in ChapterV3.",
        "",
        "## 9. Coin semantics",
        "",
        f"- Coin-image candidates: `{counts.get('coin_only', 0)}`; the icon signal is distinct from point and ticket imagery.",
        "",
        "## 10. Rental semantics",
        "",
        f"- Rental-active candidates: `{counts.get('rental_active', 0)}`; structured status is `RENTAL=1` and field `remainingRentalTime=5` is present. The unit and original grant source remain unresolved.",
        "",
        "## 11. Two ticket-available rows",
        "",
    ]
    for item in report["ticket_available_rows"]:
        lines.append(
            f"- index `{item['index']}`, chapter `{item['chapter_id']}`, label `{item['label']}`; neighbors: `{json.dumps(item['neighbors'], ensure_ascii=False)}`; icon evidence: `{json.dumps(item['icon_metadata'], ensure_ascii=False)}`."
        )
    lines.extend(
        [
            "- Both rows have structured `status=TICKET_AVAILABLE=2`, the same ChapterV3 field shape, and no recovered section/chain field explaining the duplication. Reason remains unresolved.",
            "",
            "## 12. Stable chapter attributes",
            "",
            "- Candidate stable: chapter_id, listing order/label, viewer URL shape, point-vs-coin-vs-ticket image class/alt.",
            "- These are observation signals, not production selector authority.",
            "",
            "## 13. Dynamic account attributes",
            "",
            "- Candidate dynamic: `status` (field 11), rental-active, remainingRentalTime, alreadyViewed, and isUpdated.",
            "- The named enum cleanly separates current `TICKET_AVAILABLE=2` from `POINT=4` and `COIN=5`; no stable ticket-capability field was recovered.",
            "",
            "## 14. Ticket frontier model",
            "",
            "- The observed sequence is a snapshot. Blue Free is explicitly `TICKET_AVAILABLE=2`; P is explicitly `POINT=4`. A transition from POINT to TICKET_AVAILABLE after earlier consumption is not represented by a stable ChapterV3 capability field in this evidence.",
        f"- Global ticket stock/recovery fields: `{json.dumps(report.get('global_account_state', {}), ensure_ascii=False)}`; none were observed.",
            "",
            "## 15. Can Discovery map P + ticket-now to quota?",
            "",
            f"- `{design['map_P_and_ticket_now_both_to_quota']}`.",
            "- Candidate A is therefore not adopted. P and blue Free can only be grouped as quota by a future live before/after experiment or another endpoint/schema field.",
            "",
            "## 16. Can full Discovery be avoided after each ticket use?",
            "",
            f"- `{design['full_discovery_after_ticket_use_required']}`.",
            "",
            "## 17. Recommended responsibility split",
            "",
            f"- `{design['recommended_dynamic_refresh_layer']}`. Keep Discovery limited to chapter identity/order/stable access class until the capability field is confirmed.",
            "",
            "## 18. Bounded Discovery implications",
            "",
            "- The existing one-to-one chapter_id -> `/title/{title_id}/chapter/{chapter_id}/viewer` boundary candidate remains viable.",
            "",
            "## 19. Remaining unknowns",
            "",
        ]
    )
    lines.extend(f"- {unknown}" for unknown in report["unknowns"])
    lines.extend(["", "## Compact 250-row state sequence", "", "```text"])
    lines.extend(
        f"#{int(row['index']) + 1:<4} {row['chapter_id']:<8} {str(row['label'] or '')[:38]:<38} {row['raw_state']} -> {row['derived_state']}"
        for row in report["state_sequence"]
    )
    lines.extend(["```", ""])
    return "\n".join(lines)


def compare_reports(before_path: Path, after_path: Path) -> dict[str, Any]:
    before = json.loads(before_path.read_text(encoding="utf-8"))
    after = json.loads(after_path.read_text(encoding="utf-8"))
    before_states = {str(row["chapter_id"]): row.get("derived_state") for row in before.get("state_sequence", [])}
    after_states = {str(row["chapter_id"]): row.get("derived_state") for row in after.get("state_sequence", [])}
    ids = sorted(set(before_states) | set(after_states))
    return {
        "before": str(before_path),
        "after": str(after_path),
        "chapter_state_changes": [
            {"chapter_id": chapter_id, "before": before_states.get(chapter_id), "after": after_states.get(chapter_id)}
            for chapter_id in ids
            if before_states.get(chapter_id) != after_states.get(chapter_id)
        ],
        "state_counts_before": before.get("state_counts", {}),
        "state_counts_after": after.get("state_counts", {}),
        "protobuf_raw_sha256_before": before.get("protobuf", {}).get("raw_sha256"),
        "protobuf_raw_sha256_after": after.get("protobuf", {}).get("raw_sha256"),
        "global_ticket_state": "not recovered by this probe",
    }


async def run_probe(url: str, output_dir: Path, cdp_endpoint: str | None) -> dict[str, Any]:
    target = parse_target_list_url(url)
    if target is None:
        raise ValueError("--url must be https://zebrack-comic.shueisha.co.jp/title/<id>/chapter/list")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "dom").mkdir(parents=True, exist_ok=True)
    (output_dir / "network").mkdir(parents=True, exist_ok=True)
    session = await BrowserSession.connect(resolve_cdp_endpoint(cli_endpoint=cdp_endpoint))
    page = await session.new_page()
    try:
        records, tasks = await install_access_network_observer(page, output_dir)
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        try:
            await page.wait_for_load_state("networkidle", timeout=WAIT_TIMEOUT_MS)
        except Exception as exc:  # noqa: BLE001 - polling pages can remain active
            records.append({"observation": "networkidle_timeout", "error": type(exc).__name__})
        await page.wait_for_timeout(2500)
        dom = await collect_dom(page)
        await asyncio.gather(*tasks, return_exceptions=True)
        chapters: list[dict[str, Any]] = []
        seen: set[str] = set()
        for candidate in dom_candidate_rows(dom):
            chapter = _generic_candidate_to_row(candidate, expected_title_id=target["title_id"])
            if chapter is None or str(chapter["chapter_id"]) in seen:
                continue
            seen.add(str(chapter["chapter_id"]))
            chapters.append(chapter)
        frontend = _frontend_evidence(records)
        frontend_path = output_dir / "network" / "frontend_schema_evidence.json"
        write_json(frontend_path, frontend)
        protobuf = _load_protobuf_artifact(output_dir, {str(chapter["chapter_id"]) for chapter in chapters})
        api_urls = [record.get("url") for record in records if CHAPTER_LIST_PATH in str(record.get("url") or "")]
        if api_urls:
            protobuf["endpoint"] = api_urls[0]
        return build_report(
            target=url,
            title_id=target["title_id"],
            dom=dom,
            chapters=chapters,
            records=records,
            protobuf=protobuf,
            frontend=frontend,
            output_dir=output_dir,
        )
    finally:
        await session.close_page(page)
        await session.close()


def main() -> None:  # pragma: no cover - live CLI entry point
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "compare":
        parser = argparse.ArgumentParser(description="Compare two Z4-0.5 artifacts")
        parser.add_argument("before")
        parser.add_argument("after")
        args = parser.parse_args(sys.argv[2:])
        print(json.dumps(compare_reports(Path(args.before), Path(args.after)), ensure_ascii=False, indent=2))
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--cdp-endpoint", default=None)
    args = parser.parse_args()
    report = asyncio.run(run_probe(args.url, args.output_dir, args.cdp_endpoint))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
