from screenshot_crawler.core.models import ContentIdentity
from screenshot_crawler.site_adapters.mangaone.adapter import (
    MangaOneAdapter,
    mangaone_identity_from_pages,
    order_mangaone_pages,
    parse_mangaone_page_number,
    split_mangaone_episode_title,
)


def test_mangaone_chapter_parts_from_url() -> None:
    assert MangaOneAdapter.chapter_parts_from_url(
        "https://manga-one.com/manga/2379/chapter/214131"
    ) == ("2379", "214131")


def test_mangaone_page_label_parser() -> None:
    assert parse_mangaone_page_number("page_0") == 0
    assert parse_mangaone_page_number("page_104") == 104
    assert parse_mangaone_page_number("cover") is None


def test_mangaone_episode_title_uses_two_digit_episode_number() -> None:
    assert split_mangaone_episode_title("獣王と薬草 第1話 | マンガワン") == (
        "獣王と薬草",
        "第01話",
    )
    assert split_mangaone_episode_title("獣王と薬草 第80話(後編)") == (
        "獣王と薬草",
        "第80話-後編",
    )


def test_mangaone_episode_title_without_episode_number_is_preserved() -> None:
    assert split_mangaone_episode_title("作品名 | マンガワン") == ("作品名", None)


def test_mangaone_spread_is_captured_right_to_left() -> None:
    assert order_mangaone_pages([("page_2", 200.0), ("page_1", 900.0)]) == (
        "page_1",
        "page_2",
    )


def test_mangaone_identity_supports_single_page_and_spread() -> None:
    assert mangaone_identity_from_pages(
        ("page_1", "page_2"), chapter_id="214131"
    ) == ContentIdentity(
        page_id="page_1|page_2", page_number=3, source_id="214131"
    )
    assert mangaone_identity_from_pages(("page_0",), chapter_id="214131").page_number == 1
