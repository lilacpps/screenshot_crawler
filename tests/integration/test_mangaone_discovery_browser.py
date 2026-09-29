from __future__ import annotations

from pathlib import Path

import pytest

from screenshot_crawler.catalog import CatalogService
from screenshot_crawler.discovery import (
    DiscoveryAdapterRegistry,
    DiscoveryService,
)
from screenshot_crawler.site_adapters.mangaone import discovery as mangaone_discovery
from screenshot_crawler.site_adapters.mangaone.discovery import (
    CARD_SELECTOR,
    MangaOneDiscoveryAdapter,
)
from screenshot_crawler.watchlist import DiscoveryScope, WatchlistTarget

pytestmark = pytest.mark.asyncio(loop_scope="module")


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


def _target(discovery_scope: DiscoveryScope | None = None) -> WatchlistTarget:
    return WatchlistTarget(
        key="juou",
        work_key="juou-work",
        site="mangaone",
        url="https://manga-one.com/manga/2379/chapter/214131",
        label="迯｣邇九→阮ｬ闕・",
        discovery_scope=discovery_scope,
    )


def _stalling_listing_html() -> str:
    card_classes = CARD_SELECTOR.removeprefix("div.").replace(".", " ")
    return f"""
    <title>迯｣邇九→阮ｬ闕・隨ｬ1隧ｱ | 繝槭Φ繧ｬ繝ｯ繝ｳ</title>
    <div id="chapterList">
      <div class="{card_classes}" id="card-3">
        <img alt="隨ｬ80隧ｱ(蠕檎ｷｨ)" src="https://manga-one.com/chapter/3.webp">
        <span>蜈郁ｪｭ</span>
      </div>
      <button type="button" id="next">谺｡縺ｸ</button>
    </div>
    <script>
      document.querySelector('#next').addEventListener('click', () => {{
        document.querySelector('#chapterList').innerHTML = `
          <div class="{card_classes}" id="card-2">
            <a href="/manga/2379/chapter/2"><img alt="隨ｬ80隧ｱ(蜑咲ｷｨ)" src="https://manga-one.com/chapter/2.webp"></a>
            <span>辟｡譁・</span>
          </div>
          <button type="button" id="next">谺｡縺ｸ</button>`;
      }});
    </script>
    """


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


@pytest.mark.parametrize(
    ("scope", "expected"),
    [
        (
            DiscoveryScope(
                from_url="https://manga-one.com/manga/2379/chapter/2",
                through_url="https://manga-one.com/manga/2379/chapter/0",
            ),
            ["2", "1", "0"],
        ),
        (
            DiscoveryScope(from_url="https://manga-one.com/manga/2379/chapter/1"),
            ["1", "0"],
        ),
        (
            DiscoveryScope(through_url="https://manga-one.com/manga/2379/chapter/1"),
            ["3", "2", "1"],
        ),
        (
            DiscoveryScope(
                from_url="https://manga-one.com/manga/2379/chapter/2",
                through_url="https://manga-one.com/manga/2379/chapter/2",
            ),
            ["2"],
        ),
    ],
)
async def test_mangaone_bounded_scope_selects_inclusive_listing_range(
    browser_page,
    tmp_path: Path,
    scope: DiscoveryScope,
    expected: list[str],
) -> None:
    async def fulfill(route) -> None:
        await route.fulfill(body=_listing_html(), content_type="text/html; charset=utf-8")

    await browser_page.route("https://manga-one.com/**", fulfill)
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    registry = DiscoveryAdapterRegistry()
    registry.register("mangaone", MangaOneDiscoveryAdapter)

    result = await DiscoveryService(catalog, registry).discover(
        browser_page,
        _target(scope),
        "full",
    )

    assert result.complete is True
    assert result.stopped_reason == "exhausted"
    assert [source.external_id for source in catalog.list_sources()] == expected


async def test_mangaone_bounded_scope_keeps_special_pr_record(
    browser_page,
    tmp_path: Path,
) -> None:
    async def fulfill(route) -> None:
        await route.fulfill(body=_listing_html(), content_type="text/html; charset=utf-8")

    await browser_page.route("https://manga-one.com/**", fulfill)
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    registry = DiscoveryAdapterRegistry()
    registry.register("mangaone", MangaOneDiscoveryAdapter)

    result = await DiscoveryService(catalog, registry).discover(
        browser_page,
        _target(
            DiscoveryScope(
                from_url="https://manga-one.com/manga/2379/chapter/2",
                through_url="https://manga-one.com/manga/2379/chapter/0",
            )
        ),
        "full",
    )

    pr_source = catalog.find_source("mangaone", "1")
    pr_item = catalog.get_item(pr_source.item_id)
    assert result.complete is True
    assert pr_item.order_key is None
    assert pr_item.order_label == "9巻コミックPR"


@pytest.mark.parametrize(
    "scope",
    [
        DiscoveryScope(from_url="https://example.test/manga/2379/chapter/2"),
        DiscoveryScope(from_url="http://manga-one.com/manga/2379/chapter/2"),
        DiscoveryScope(from_url="https://manga-one.com/manga/999/chapter/2"),
        DiscoveryScope(from_url="https://manga-one.com/manga/2379/chapter/999"),
        DiscoveryScope(through_url="https://manga-one.com/manga/2379/chapter/999"),
        DiscoveryScope(
            from_url="https://manga-one.com/manga/2379/chapter/1",
            through_url="https://manga-one.com/manga/2379/chapter/3",
        ),
    ],
)
async def test_mangaone_invalid_bounded_scope_fails_without_catalog_mutation(
    browser_page,
    tmp_path: Path,
    scope: DiscoveryScope,
) -> None:
    async def fulfill(route) -> None:
        await route.fulfill(body=_listing_html(), content_type="text/html; charset=utf-8")

    await browser_page.route("https://manga-one.com/**", fulfill)
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    registry = DiscoveryAdapterRegistry()
    registry.register("mangaone", MangaOneDiscoveryAdapter)

    result = await DiscoveryService(catalog, registry).discover(
        browser_page,
        _target(scope),
        "full",
    )

    assert result.complete is False
    assert result.stopped_reason == "incomplete"
    assert result.observed_count == 0
    assert catalog.list_items() == []
    assert catalog.list_sources() == []
    assert catalog.list_source_targets() == []


async def test_mangaone_bounded_pagination_failure_does_not_write_partial_records(
    browser_page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mangaone_discovery, "WAIT_TIMEOUT_MS", 200)

    async def fulfill(route) -> None:
        await route.fulfill(
            body=_stalling_listing_html(),
            content_type="text/html; charset=utf-8",
        )

    await browser_page.route("https://manga-one.com/**", fulfill)
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    registry = DiscoveryAdapterRegistry()
    registry.register("mangaone", MangaOneDiscoveryAdapter)

    result = await DiscoveryService(catalog, registry).discover(
        browser_page,
        _target(
            DiscoveryScope(
                through_url="https://manga-one.com/manga/2379/chapter/2",
            )
        ),
        "full",
    )

    assert result.complete is False
    assert result.stopped_reason == "incomplete"
    assert result.observed_count == 0
    assert catalog.list_items() == []
    assert catalog.list_sources() == []
    assert catalog.list_source_targets() == []


async def test_mangaone_unbounded_pagination_failure_keeps_partial_refresh_behavior(
    browser_page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mangaone_discovery, "WAIT_TIMEOUT_MS", 1_000)

    async def fulfill(route) -> None:
        await route.fulfill(
            body=_stalling_listing_html(),
            content_type="text/html; charset=utf-8",
        )

    await browser_page.route("https://manga-one.com/**", fulfill)
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    registry = DiscoveryAdapterRegistry()
    registry.register("mangaone", MangaOneDiscoveryAdapter)

    result = await DiscoveryService(catalog, registry).discover(
        browser_page,
        _target(),
        "full",
    )

    assert result.complete is False
    assert result.stopped_reason == "incomplete"
    assert result.observed_count == 1
    assert [source.external_id for source in catalog.list_sources()] == ["3"]


async def test_mangaone_bounded_incremental_uses_common_known_streak_semantics(
    browser_page,
    tmp_path: Path,
) -> None:
    async def fulfill(route) -> None:
        await route.fulfill(body=_listing_html(), content_type="text/html; charset=utf-8")

    await browser_page.route("https://manga-one.com/**", fulfill)
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    registry = DiscoveryAdapterRegistry()
    registry.register("mangaone", MangaOneDiscoveryAdapter)
    service = DiscoveryService(catalog, registry)

    full_result = await service.discover(browser_page, _target(), "full")
    bounded_result = await service.discover(
        browser_page,
        _target(
            DiscoveryScope(
                through_url="https://manga-one.com/manga/2379/chapter/1",
            )
        ),
        "incremental",
    )

    assert full_result.complete is True
    assert bounded_result.complete is None
    assert bounded_result.observed_count == 3
    assert bounded_result.known_count == 3
    assert bounded_result.stopped_reason == "exhausted"
