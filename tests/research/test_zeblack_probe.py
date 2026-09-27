from __future__ import annotations

import json

import pytest

from poc.zeblack_capture_probe import (
    ZebrackZ1Probe,
    classify_z1_comparison,
    classify_z1_verdict,
    is_exact_pixel_match,
    order_page_metadata,
    parse_page_index,
)
from poc.zeblack_probe import (
    ZebrackProbe,
    classify_draw_geometry,
    classify_resource,
    classify_url_change,
    extract_viewer_identity,
    fingerprint_changed,
    is_target_viewer_url,
    looks_like_page_navigation,
    navigation_candidate_is_forbidden,
    navigation_succeeded,
)

TARGET = "https://zebrack-comic.shueisha.co.jp/title/118286/chapter/9265713/viewer"


def test_extract_viewer_identity_requires_zebrack_viewer_url() -> None:
    assert extract_viewer_identity(TARGET) == {"title_id": "118286", "chapter_id": "9265713"}
    assert extract_viewer_identity(TARGET + "?from=probe#page=2") == {
        "title_id": "118286",
        "chapter_id": "9265713",
    }
    assert extract_viewer_identity("https://example.test/title/118286/chapter/9265713/viewer") is None
    assert extract_viewer_identity("https://zebrack-comic.shueisha.co.jp/title/118286/chapter/1") is None


def test_target_guard_rejects_title_or_chapter_change() -> None:
    assert is_target_viewer_url(TARGET + "#page=2", "118286", "9265713")
    assert not is_target_viewer_url(
        "https://zebrack-comic.shueisha.co.jp/title/118286/chapter/9265714/viewer",
        "118286",
        "9265713",
    )
    assert not is_target_viewer_url(
        "https://zebrack-comic.shueisha.co.jp/title/118287/chapter/9265713/viewer",
        "118286",
        "9265713",
    )


def test_query_or_hash_change_is_not_target_escape() -> None:
    assert classify_url_change(TARGET, TARGET + "?page=2", "118286", "9265713") == "query_or_hash_changed"
    assert classify_url_change(TARGET, TARGET + "#page=2", "118286", "9265713") == "query_or_hash_changed"
    assert classify_url_change(TARGET, TARGET, "118286", "9265713") == "unchanged"
    assert classify_url_change(
        TARGET,
        "https://zebrack-comic.shueisha.co.jp/title/118286/chapter/9265714/viewer",
        "118286",
        "9265713",
    ) == "target_changed"


def test_access_and_next_chapter_candidates_are_never_safe_navigation() -> None:
    assert navigation_candidate_is_forbidden("購入", "next page")
    assert navigation_candidate_is_forbidden("ポイントを使う")
    assert navigation_candidate_is_forbidden("レンタル")
    assert navigation_candidate_is_forbidden("毎日無料")
    assert navigation_candidate_is_forbidden("次のチャプター")
    assert navigation_candidate_is_forbidden("next chapter")
    assert not navigation_candidate_is_forbidden("次のページ")
    assert looks_like_page_navigation("次のページ")
    assert looks_like_page_navigation("page-navigation-forward")
    assert not looks_like_page_navigation("作品詳細")


def test_network_classification_prefers_explicit_json_content_type() -> None:
    assert classify_resource("image", "application/json", "https://example.test/event") == "json"
    assert classify_resource("image", "image/jpeg", "https://example.test/page") == "image"


def test_page_fingerprint_requires_changed_and_stable() -> None:
    assert fingerprint_changed("before", "after") is True
    assert fingerprint_changed("before", "before") is False
    assert fingerprint_changed("before", None) is False
    assert navigation_succeeded(False, True) is False
    assert navigation_succeeded(True, False) is False
    assert navigation_succeeded(True, True) is True


def test_draw_geometry_classification_has_bounded_basic_cases() -> None:
    full = {
        "canvas": {"width": 100, "height": 200},
        "source": {"naturalWidth": 100, "naturalHeight": 200},
        "sourceRect": {"sx": 0, "sy": 0, "sw": 100, "sh": 200},
        "destinationRect": {"dx": 0, "dy": 0, "dw": 100, "dh": 200},
        "transform": {"a": 1, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0},
    }
    crop = {
        **full,
        "sourceRect": {"sx": 10, "sy": 0, "sw": 50, "sh": 100},
        "destinationRect": {"dx": 0, "dy": 0, "dw": 50, "dh": 100},
    }
    scaled = {**full, "destinationRect": {"dx": 0, "dy": 0, "dw": 50, "dh": 100}}
    assert classify_draw_geometry([full]) == "full_frame_copy"
    assert classify_draw_geometry([crop]) == "cropped"
    assert classify_draw_geometry([crop, crop]) == "tiled"
    assert classify_draw_geometry([scaled]) == "scaled"
    assert classify_draw_geometry([]) == "unknown"


class _FailingResponse:
    async def body(self) -> bytes:
        raise RuntimeError("body unavailable")


@pytest.mark.asyncio
async def test_image_body_read_failure_is_recorded_without_failing_probe(tmp_path) -> None:
    probe = ZebrackProbe(
        page=None,
        output_dir=tmp_path,
        expected_title_id="118286",
        expected_chapter_id="9265713",
    )
    record = {
        "url": "https://cdn.example.test/page.webp",
        "host": "cdn.example.test",
        "content_type": "image/webp",
        "timestamp": "2026-09-27T00:00:00+00:00",
        "body": {},
    }

    await probe._save_image_response(_FailingResponse(), record)

    assert record["body"]["attempted"] is True
    assert "body unavailable" in record["body"]["error"]
    assert probe.saved_images == []


def test_report_and_summary_are_written_as_artifacts(tmp_path) -> None:
    probe = ZebrackProbe(
        page=None,
        output_dir=tmp_path,
        expected_title_id="118286",
        expected_chapter_id="9265713",
    )
    probe.write_report(
        {
            "target_url": TARGET,
            "target_title_id": "118286",
            "target_chapter_id": "9265713",
            "final_url": TARGET,
            "final_url_change_kind": "unchanged",
            "steps_requested": 3,
            "max_steps": 3,
            "states_observed": 0,
            "navigation": [],
            "saved_network_images": [],
            "draw_calls_observed": 0,
            "draw_geometry_classification": "unknown",
            "observations": [],
            "stopped_reason": None,
            "errors": [],
        }
    )

    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert report["target_chapter_id"] == "9265713"
    assert "## 11. Capture strategy assessment" in summary


def test_page_alt_parser_accepts_only_numeric_page_alt() -> None:
    assert parse_page_index("page_0") == 0
    assert parse_page_index("page_12") == 12
    assert parse_page_index("page_") is None
    assert parse_page_index("page_1_extra") is None
    assert parse_page_index("cover") is None
    assert parse_page_index(None) is None


def test_page_metadata_order_is_numeric_and_rejects_malformed_or_duplicate() -> None:
    ordered = order_page_metadata(
        [{"page_alt": "page_2"}, {"page_alt": "page_0"}, {"page_alt": "page_1"}]
    )
    assert ordered["status"] == "stable"
    assert ordered["indices"] == [0, 1, 2]
    assert [item["page_alt"] for item in ordered["ordered"]] == ["page_0", "page_1", "page_2"]

    malformed = order_page_metadata([{"page_alt": "page_0"}, {"page_alt": "not-a-page"}])
    assert malformed["status"] == "ambiguous"
    assert malformed["malformed_count"] == 1

    duplicate = order_page_metadata([{"page_alt": "page_1"}, {"page_alt": "page_1"}])
    assert duplicate["status"] == "ambiguous"
    assert duplicate["duplicate_indices"] == [1]


def test_exact_pixel_match_requires_equal_native_dimensions_and_hashes() -> None:
    assert is_exact_pixel_match("a", "a", [760, 1080], [760, 1080])
    assert not is_exact_pixel_match("a", "b", [760, 1080], [760, 1080])
    assert not is_exact_pixel_match("a", "a", [760, 1080], [380, 540])
    assert not is_exact_pixel_match("a", "a", None, [760, 1080])


def test_z1_comparison_classification_is_fail_closed() -> None:
    common = {
        "fetch_error": None,
        "decoded_format": "JPEG",
        "decoded_dimensions": [760, 1080],
        "natural_dimensions": [760, 1080],
        "decoded_pixel_sha256": "a",
        "img_pixel_sha256": "a",
        "canvas_error": None,
    }
    assert classify_z1_comparison(**common) == "exact_pixel_match"
    assert classify_z1_comparison(**{**common, "decoded_dimensions": [380, 540]}) == "mismatch"
    assert classify_z1_comparison(**{**common, "img_pixel_sha256": "b"}) == "mismatch"
    assert classify_z1_comparison(**{**common, "canvas_error": "SecurityError"}) == "inconclusive"
    assert classify_z1_comparison(**{**common, "fetch_error": "missing_blob"}) == "unavailable"
    assert classify_z1_comparison(**{**common, "decoded_format": "PNG"}) == "unavailable"


def test_z1_verdict_does_not_confirm_dimension_mismatch_or_ambiguous_order() -> None:
    pages = [
        {"page_index": 0, "equivalence": "exact_pixel_match"},
        {"page_index": 1, "equivalence": "mismatch"},
    ]
    stable_spread = {
        "status": "stable",
        "spread_observed": True,
        "gaps": [],
    }
    assert classify_z1_verdict(pages, stable_spread) == "rejected"
    assert classify_z1_verdict(
        [{"page_index": 0, "equivalence": "exact_pixel_match"}], stable_spread
    ) == "inconclusive"
    assert classify_z1_verdict(
        [
            {"page_index": 0, "equivalence": "exact_pixel_match"},
            {"page_index": 1, "equivalence": "exact_pixel_match"},
        ],
        {**stable_spread, "status": "ambiguous"},
    ) == "inconclusive"


class _UnexpectedZ1Page:
    async def evaluate(self, *args, **kwargs):
        raise AssertionError("missing blob source must not trigger guessed browser access")


@pytest.mark.asyncio
async def test_z1_missing_blob_source_is_unavailable_without_guessing(tmp_path) -> None:
    probe = ZebrackZ1Probe(
        page=_UnexpectedZ1Page(),
        output_dir=tmp_path,
        expected_title_id="118286",
        expected_chapter_id="9265713",
    )
    result = await probe._capture_page(
        "state_000",
        {
            "page_alt": "page_0",
            "dom_order": 0,
            "blob_url": None,
            "natural_dimensions": [760, 1080],
        },
    )
    assert result["equivalence"] == "unavailable"
    assert result["fetch_error"] == "malformed_page_alt_or_missing_blob_source"
