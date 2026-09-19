from __future__ import annotations

from pathlib import Path

import pytest
from playwright.async_api import Error, async_playwright

from screenshot_crawler.catalog import CatalogService
from screenshot_crawler.discovery import (
    DiscoveryAdapterRegistry,
    DiscoveryIncompleteError,
    DiscoveryService,
)
from screenshot_crawler.site_adapters.mangaone.discovery import (
    CARD_SELECTOR,
    MangaOneDiscoveryAdapter,
    chapter_id_from_image_url,
    mangaone_title_from_page_title,
    map_mangaone_access_mode,
    parse_mangaone_chapter_url,
    parse_mangaone_episode_label,
)
from screenshot_crawler.watchlist import WatchlistTarget


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


def _listing_html() -> str:
    card_classes = CARD_SELECTOR.removeprefix("div.").replace(".", " ")
    return f"""
    <title>獣王と薬草 第1話 | マンガワン</title>
    <div id="chapterList">
      <div class="{card_classes}" id="card-3">
        <img alt="第80話(後編)" src="https://manga-one.com/chapter/3.webp">
        <span>先読</span>
      </div>
      <div class="{card_classes}" id="card-2">
        <a href="/manga/2379/chapter/2"><img alt="第80話(前編)" src="https://manga-one.com/chapter/2.webp"></a>
        <span>無料</span>
      </div>
      <div class="{card_classes}" id="card-pr">
        <img alt="9巻コミックPR" src="https://manga-one.com/chapter/1.webp">
      </div>
      <div class="{card_classes}" id="card-other-work">
        <a href="/manga/999/chapter/999"><img alt="別作品" src="https://manga-one.com/chapter/999.webp"></a>
      </div>
      <button type="button" id="next">次へ</button>
    </div>
    <script>
      document.querySelector('#next').addEventListener('click', () => {{
        document.querySelector('#chapterList').innerHTML = `
          <div class="{card_classes}">
            <img alt="第79話" src="https://manga-one.com/chapter/0.webp">
          </div>
          <button type="button" id="next" disabled>次へ</button>`;
      }});
    </script>
    """


@pytest.fixture
async def browser_page():
    playwright = await async_playwright().start()
    try:
        browser = await playwright.chromium.launch(headless=True)
    except Error as exc:
        await playwright.stop()
        pytest.skip(f"Chromium is unavailable: {exc}")
    page = await browser.new_page()
    try:
        yield page
    finally:
        await browser.close()
        await playwright.stop()


async def test_mangaone_discovery_scans_pages_and_maps_cards(browser_page, tmp_path: Path) -> None:
    target_url = "https://manga-one.com/manga/2379/chapter/214131"

    async def fulfill(route) -> None:
        await route.fulfill(body=_listing_html(), content_type="text/html; charset=utf-8")

    await browser_page.route("https://manga-one.com/**", fulfill)
    target = WatchlistTarget(
        key="juou",
        work_key="juou-work",
        site="mangaone",
        url=target_url,
        label="獣王と薬草",
    )
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    registry = DiscoveryAdapterRegistry()
    registry.register("mangaone", MangaOneDiscoveryAdapter)

    result = await DiscoveryService(catalog, registry).discover(
        browser_page, target, "full"
    )

    assert result.complete is True
    assert result.observed_count == 4
    assert [source.external_id for source in catalog.list_sources()] == ["3", "2", "1", "0"]
    assert [source.access_mode for source in catalog.list_sources()] == [
        "paid",
        "free",
        "quota",
        "quota",
    ]
    assert all(source.discovery_key == "juou" for source in catalog.list_sources())
    assert catalog.list_works()[0].title == "獣王と薬草"
    assert catalog.list_items()[0].order_key == "80-後編"
