from __future__ import annotations

from poc.zeblack_discovery_probe import (
    classify_frontier,
    classify_raw_access_state,
    derive_current_access,
    extract_structured_chapter_records,
    infer_dom_order,
    parse_chapter_identity,
    parse_target_list_url,
)


def test_parse_target_and_chapter_identity_are_site_and_shape_bounded() -> None:
    assert parse_target_list_url(
        "https://zebrack-comic.shueisha.co.jp/title/5123/chapter/list"
    ) == {
        "title_id": "5123",
        "list_url": "https://zebrack-comic.shueisha.co.jp/title/5123/chapter/list",
    }
    assert parse_target_list_url("https://example.test/title/5123/chapter/list") is None
    assert parse_chapter_identity(
        "https://zebrack-comic.shueisha.co.jp/title/5123/chapter/224191/viewer?x=1",
        expected_title_id="5123",
    ) == {
        "title_id": "5123",
        "chapter_id": "224191",
        "viewer_url": "https://zebrack-comic.shueisha.co.jp/title/5123/chapter/224191/viewer",
    }
    assert parse_chapter_identity(
        "https://zebrack-comic.shueisha.co.jp/title/5124/chapter/224191/viewer",
        expected_title_id="5123",
    ) is None


def test_raw_access_classifier_keeps_native_signals_separate() -> None:
    assert classify_raw_access_state({"texts": ["無料"]}) == "free_unconditional"
    assert classify_raw_access_state({"icon_alts": ["チケット利用可"]}) == "ticket_available_now"
    assert classify_raw_access_state({"icon_alts": ["ポイント画像"]}) == "ticket_candidate_later"
    assert classify_raw_access_state({"texts": ["P"]}) == "ticket_candidate_later"
    assert classify_raw_access_state({"icon_alts": ["コイン画像"]}) == "coin_only"
    assert classify_raw_access_state({"texts": ["閲覧期限 残り2時間"]}) == "rental_active"
    assert classify_raw_access_state({"texts": ["P"], "icon_alts": ["コイン画像"]}) == "unknown"
    assert classify_raw_access_state({"icon_alts": ["Free"]}) == "ticket_available_now"


def test_derived_mapping_is_explicitly_hypothetical() -> None:
    assert derive_current_access("free_unconditional") == "free_unconditional"
    assert derive_current_access("ticket_available_now") == "ticket_available_now"
    assert derive_current_access("ticket_candidate_later") == "ticket_candidate_later"
    assert derive_current_access("rental_active") == "rental_active"
    assert derive_current_access("coin_only") == "coin_only"
    assert derive_current_access("unknown") == "unknown"


def test_frontier_preserves_dom_segments_without_sorting() -> None:
    states = [
        {"index": 0, "chapter_id": "old", "derived_current_access": "free_unconditional"},
        {"index": 1, "chapter_id": "eligible", "derived_current_access": "ticket_available_now"},
        {"index": 2, "chapter_id": "later", "derived_current_access": "ticket_candidate_later"},
        {"index": 3, "chapter_id": "coin", "derived_current_access": "coin_only"},
    ]
    result = classify_frontier(states)
    assert result["observed"] is True
    assert [segment["state"] for segment in result["segments"]] == [
        "free_unconditional",
        "ticket_available_now",
        "ticket_candidate_later",
        "coin_only",
    ]
    assert result["ticket_available_now_chapter_ids"] == ["eligible"]
    assert result["ticket_candidate_later_chapter_ids"] == ["later"]
    assert result["coin_only_chapter_ids"] == ["coin"]


def test_dom_order_uses_observed_labels_without_reordering() -> None:
    assert infer_dom_order([{"label": "#1"}, {"label": "#2"}])["value"] == "oldest-first"
    assert infer_dom_order([{"label": "#2"}, {"label": "#1"}])["value"] == "latest-first"
    assert infer_dom_order([{"label": "special"}, {"label": "unknown"}])["value"] == "unknown"


def test_structured_extractor_keeps_chapter_metadata_bounded() -> None:
    payload = {
        "chapters": [
            {
                "chapterId": 224191,
                "titleId": 5123,
                "viewerUrl": "/title/5123/chapter/224191/viewer",
                "accessType": "point",
                "price": {"point": 40},
            },
            {"id": "not-a-chapter", "title": "ignored"},
        ]
    }
    records = extract_structured_chapter_records(payload, "https://api.example.test/title_chapter_list")
    assert records[0]["chapter_id"] == "224191"
    assert records[0]["title_id"] == "5123"
    assert records[0]["accessType"] == "point"
    assert records[0]["price"] == '{"point":40}'
