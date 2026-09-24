from poc.jumpplus_discovery_matrix import pagination_offsets
from poc.jumpplus_discovery_probe import (
    access_pattern,
    extract_episode_id,
    identity_signature,
    manual_rental_candidates,
    network_episode_states,
    parse_range_label,
)


def test_extract_episode_id_accepts_only_canonical_jumpplus_episode_urls():
    assert extract_episode_id("https://shonenjumpplus.com/episode/12345") == "12345"
    assert extract_episode_id("https://www.shonenjumpplus.com/episode/12345/") == "12345"
    assert extract_episode_id("https://shonenjumpplus.com/episode/12345?from=work") == "12345"
    assert extract_episode_id("https://example.test/episode/12345") is None
    assert extract_episode_id("https://shonenjumpplus.com/series/12345") is None


def test_parse_range_label_is_value_agnostic():
    assert parse_range_label("286 - 187") == (286, 187)
    assert parse_range_label("  86-1 ") == (86, 1)
    assert parse_range_label("all") is None


def test_identity_signature_preserves_order_and_drops_missing_ids():
    rows = [{"episode_id": "b"}, {"episode_id": None}, {"episode_id": "a"}]
    assert identity_signature(rows) == ("b", "a")


def test_access_pattern_excludes_episode_identity_fields():
    row = {
        "episode_id": "ep-1",
        "text": "1話 title",
        "access_title": "40ポイント レンタル・48時間",
        "access_text": ["40pt", "レンタル・48時間"],
        "access_class": ["series-episode-list-price"],
        "access_icons": [],
    }
    assert access_pattern(row) == {
        "access_title": "40ポイント レンタル・48時間",
        "access_text": ["40pt", "レンタル・48時間"],
        "access_class": ["series-episode-list-price"],
        "access_icons": [],
    }


def test_network_episode_states_extracts_rental_and_expiry_fields():
    records = [
        {
            "url": "https://example.test/api",
            "json": [
                {
                    "readable_product_id": "ep-3",
                    "purchase_info": {"can_read": True, "has_rented_via_point": True},
                    "status": {"label": "has_rented", "rental_end_at": "2026-09-26T02:41:39Z"},
                }
            ],
        }
    ]
    assert network_episode_states(records) == [
        {
            "episode_id": "ep-3",
            "viewer_uri": None,
            "title": None,
            "display_open_at": None,
            "free_term_start_at": None,
            "open_limit": None,
            "purchase_info": {"can_read": True, "has_rented_via_point": True},
            "status": {"label": "has_rented", "rental_end_at": "2026-09-26T02:41:39Z"},
            "source_urls": ["https://example.test/api"],
        }
    ]


def test_manual_rental_candidates_do_not_depend_on_episode_number():
    rows = [
        {
            "episode_id": "ep-3",
            "href": "https://shonenjumpplus.com/episode/ep-3",
            "title_text": "第3話",
            "order_text": "3",
            "published_text": "2026/06/14",
            "access_text": ["レンタル中 2026/09/26 11:41まで"],
            "access_class": ["series-episode-list-rental"],
            "access_related_descendants": [],
        }
    ]
    candidates = manual_rental_candidates(rows, [])
    assert candidates[0]["episode_id"] == "ep-3"
    assert candidates[0]["order_key_candidate"] == "3"


def test_pagination_offsets_are_sorted_and_deduplicated():
    report = {
        "network_observation": {
            "additional_after_initial_load": [
                {"url": "https://x/api/pagination_readable_products?offset=200"},
                {"url": "https://x/api/pagination_readable_products?offset=0"},
                {"url": "https://x/api/pagination_readable_products?offset=200"},
            ]
        }
    }
    assert pagination_offsets(report) == [0, 200]
