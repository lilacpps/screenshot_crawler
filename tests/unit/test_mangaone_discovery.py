from __future__ import annotations

import pytest

from screenshot_crawler.discovery import (
    DiscoveryIncompleteError,
)
from screenshot_crawler.site_adapters.mangaone.discovery import (
    chapter_id_from_image_url,
    mangaone_title_from_page_title,
    map_mangaone_access_mode,
    parse_mangaone_chapter_url,
    parse_mangaone_episode_label,
)


def test_mangaone_chapter_identity_is_path_based() -> None:
    parts = parse_mangaone_chapter_url(
        "https://manga-one.com/manga/2379/chapter/214131?type=chapter"
    )
    assert parts is not None
    assert (parts.work_id, parts.chapter_id) == ("2379", "214131")
    assert parse_mangaone_chapter_url("https://manga-one.com/manga/2379") is None
    assert chapter_id_from_image_url(
        "https://manga-one.com/assets/chapter/214131.webp"
    ) == "214131"
    assert chapter_id_from_image_url("https://manga-one.com/chapter/not-an-image") is None


@pytest.mark.parametrize(
    "url",
    [
        "http://manga-one.com/manga/2379/chapter/214131",
        "https://www.manga-one.com/manga/2379/chapter/214131",
        "https://example.test/manga/2379/chapter/214131",
        "/manga/2379/chapter/214131",
        "https://manga-one.com/manga/2379",
    ],
)
def test_mangaone_chapter_url_parser_requires_canonical_https_host_and_path(
    url: str,
) -> None:
    assert parse_mangaone_chapter_url(url) is None


@pytest.mark.parametrize(
    ("label", "order_key", "order_label"),
    [
        ("第80話", "80", "第80話"),
        ("第80話(前編)", "80-前編", "第80話-前編"),
        ("9巻コミックPR", None, "9巻コミックPR"),
    ],
)
def test_mangaone_episode_metadata(
    label: str,
    order_key: str | None,
    order_label: str | None,
) -> None:
    assert parse_mangaone_episode_label(label) == (order_key, order_label)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("無料", "free"), ("FREE", "free"), ("先読み", "paid"), ("先読", "paid"), ("", "quota")],
)
def test_mangaone_access_mapping(text: str, expected: str) -> None:
    assert map_mangaone_access_mode(text) == expected


def test_mangaone_conflicting_access_badges_are_incomplete() -> None:
    with pytest.raises(DiscoveryIncompleteError):
        map_mangaone_access_mode("無料 先読み")


def test_mangaone_title_mapping() -> None:
    assert mangaone_title_from_page_title("獣王と薬草 第80話(後編) | マンガワン") == "獣王と薬草"
