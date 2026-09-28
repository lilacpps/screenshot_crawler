from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from screenshot_crawler.catalog.service import JST
from screenshot_crawler.discovery import (
    DiscoveryIncompleteError,
)
from screenshot_crawler.site_adapters.magapoke.discovery import (
    canonical_magapoke_episode_url,
    magapoke_rental_grant_until,
    map_magapoke_access_mode,
    parse_magapoke_episode_url,
    parse_magapoke_published_at,
)

TARGET_URL = "https://pocket.shonenmagazine.com/title/00695/episode/244815"


def test_magapoke_episode_url_parser_is_strict_and_preserves_zeroes() -> None:
    parts = parse_magapoke_episode_url(f"{TARGET_URL}?from=watchlist")

    assert parts is not None
    assert (parts.title_id, parts.episode_id) == ("00695", "244815")
    assert canonical_magapoke_episode_url(parts) == TARGET_URL
    assert parse_magapoke_episode_url(
        "https://example.test/title/00695/episode/244815"
    ) is None
    assert parse_magapoke_episode_url(
        "https://pocket.shonenmagazine.com/title/00695"
    ) is None
    assert parse_magapoke_episode_url(
        "https://pocket.shonenmagazine.com/title/00695/episode/"
    ) is None
    assert parse_magapoke_episode_url(
        "https://pocket.shonenmagazine.com/episode/244815"
    ) is None
    assert parse_magapoke_episode_url(
        "http://pocket.shonenmagazine.com/title/00695/episode/244815"
    ) is None


@pytest.mark.parametrize(
    ("classes", "expected"),
    [
        ("c-episode-item__ico c-episode-item__ico--free", "free"),
        ("c-episode-item__ico c-episode-item__ico--ticket-free", "quota"),
        ("c-episode-item__ico c-episode-item__ico--renting", "quota"),
        ("c-episode-item__ico c-episode-item__ico--point", "paid"),
        ("c-episode-item__ico", "unknown"),
        (None, "unknown"),
    ],
)
def test_magapoke_access_mapping(classes: str | None, expected: str) -> None:
    assert map_magapoke_access_mode(classes) == expected


def test_magapoke_conflicting_access_states_are_incomplete() -> None:
    with pytest.raises(DiscoveryIncompleteError):
        map_magapoke_access_mode(
            [
                "c-episode-item__ico c-episode-item__ico--ticket-free",
                "c-episode-item__ico c-episode-item__ico--renting",
            ]
        )


def test_magapoke_duplicate_known_class_and_unknown_presentation_are_allowed() -> None:
    assert map_magapoke_access_mode(
        [
            "c-episode-item__ico c-episode-item__ico--free",
            "c-episode-item__ico c-episode-item__ico--free",
        ]
    ) == "free"
    assert map_magapoke_access_mode(
        "c-episode-item__ico some-presentation-class c-episode-item__ico--free"
    ) == "free"


def test_magapoke_rental_display_produces_conservative_lower_bound() -> None:
    observed = datetime(2026, 9, 22, 10, 30, tzinfo=UTC)
    assert magapoke_rental_grant_until("あと71時間", observed_at=observed) == (
        observed + timedelta(hours=71)
    )
    assert magapoke_rental_grant_until("あと0時間", observed_at=observed) == observed
    assert magapoke_rental_grant_until("あと22時間58分", observed_at=observed) is None
    assert magapoke_rental_grant_until("", observed_at=observed) is None
    with pytest.raises(ValueError, match="timezone-aware"):
        magapoke_rental_grant_until(
            "あと71時間", observed_at=datetime(2026, 9, 22, 10, 30)  # noqa: DTZ001
        )


def test_magapoke_published_date_parser_uses_jst_midnight() -> None:
    parsed = parse_magapoke_published_at("2026/09/22")
    assert parsed == datetime(2026, 9, 22, tzinfo=JST)
    assert parse_magapoke_published_at(None) is None
    assert parse_magapoke_published_at("2026-09-22") is None
    assert parse_magapoke_published_at("2026/9/22") is None
    assert parse_magapoke_published_at("2026/02/30") is None
