from poc.jumpplus_discovery_probe import (
    access_pattern,
    extract_episode_id,
    identity_signature,
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
