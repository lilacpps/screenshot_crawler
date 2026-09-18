from __future__ import annotations

from pathlib import Path

import pytest
from playwright.async_api import Error, async_playwright

from screenshot_crawler.catalog import CatalogService
from screenshot_crawler.discovery import (
    DiscoveryIncompleteError,
    DiscoverySourceSnapshot,
    IncrementalStopDecision,
)
from screenshot_crawler.site_adapters.bookwalker.discovery import (
    BookWalkerDiscoveryAdapter,
    map_bookwalker_access_mode,
    parse_bookwalker_order,
    parse_bookwalker_product_url,
    parse_bookwalker_series_url,
)
from screenshot_crawler.watchlist import WatchlistTarget


def test_bookwalker_series_url_parser_is_strict() -> None:
    assert parse_bookwalker_series_url(
        "https://bookwalker.jp/series/123/list/?from=watchlist"
    ).series_id == "123"
    assert parse_bookwalker_series_url("https://www.bookwalker.jp/series/123/list/")
    assert parse_bookwalker_series_url("http://bookwalker.jp/series/123/list/") is None
    assert parse_bookwalker_series_url("https://bookwalker.jp/series/abc/list/") is None
    assert parse_bookwalker_series_url("https://bookwalker.jp/de123/") is None


def test_bookwalker_product_identity_uses_de_uuid() -> None:
    product = parse_bookwalker_product_url(
        "https://bookwalker.jp/de6DE7534D-7022-481D-B2D3-05F03F384454/?x=1"
    )
    assert product is not None
    assert product.external_id == "6de7534d-7022-481d-b2d3-05f03f384454"
    assert parse_bookwalker_product_url("https://bookwalker.jp/viewer/abc") is None


@pytest.mark.parametrize(
    ("controls", "expected"),
    [
        ([{"text": "試し読み", "action": "trial_reading", "href": ""}], "paid"),
        ([{"text": "10分まる読み", "action": "subscription_reading", "href": ""}], "quota"),
        ([{"text": "読み放題で読む", "action": "subscription_reading", "href": ""}], "unknown"),
        ([{"text": "読む", "action": "reading", "href": ""}], "owned"),
        (
            [
                {"text": "試し読み", "action": "trial_reading", "href": ""},
                {"text": "読む", "action": "reading", "href": ""},
            ],
            "owned",
        ),
    ],
)
def test_bookwalker_access_mode_uses_reader_classifier(
    controls: list[dict[str, object]],
    expected: str,
) -> None:
    assert map_bookwalker_access_mode(controls) == expected


def test_bookwalker_order_keeps_special_products_unparsed() -> None:
    assert parse_bookwalker_order("作品名4") == ("4", "第04巻")
    assert parse_bookwalker_order("作品名 番外編") == (None, "作品名 番外編")


def test_bookwalker_hooks_preserve_scope_and_stable_access() -> None:
    adapter = BookWalkerDiscoveryAdapter()
    target = WatchlistTarget(
        key="series-one",
        site="bookwalker",
        url="https://bookwalker.jp/series/123/list/",
    )
    previous = DiscoverySourceSnapshot(
        external_id="product-one",
        discovery_key="series-one",
        access_mode="quota",
        available=True,
    )
    assert adapter.reconcile_access_mode("paid", previous, target) == "quota"
    assert adapter.incremental_stop_decision(None, previous, target) is (  # type: ignore[arg-type]
        IncrementalStopDecision.STOP
    )
    with pytest.raises(DiscoveryIncompleteError):
        adapter.reconcile_access_mode(
            "paid",
            DiscoverySourceSnapshot(
                external_id="product-one",
                discovery_key="other-series",
                access_mode="quota",
                available=True,
            ),
            target,
        )


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


def _series_listing_html() -> str:
    first_page = """
      <article><a href="/de00000000-0000-0000-0000-000000000003/">作品名3</a></article>
      <article><a href="/de00000000-0000-0000-0000-000000000002/">作品名2</a></article>
      <article><a href="/de00000000-0000-0000-0000-000000000003/">重複作品名3</a></article>
      <button id="next">次へ</button>
    """
    second_page = """
      <article><a href="/de00000000-0000-0000-0000-000000000001/">作品名1</a></article>
      <button id="next" disabled>次へ</button>
    """
    return f"""
      <div id="js-series-list">
        <h1>シリーズ公式タイトル</h1>
        {first_page}
      </div>
      <script>
        document.querySelector('#next').addEventListener('click', () => {{
          document.querySelector('#js-series-list').innerHTML = `{second_page}`;
        }});
      </script>
    """


def _product_html(external_id: str) -> str:
    controls = {
        "00000000-0000-0000-0000-000000000003": '<a data-action-label="reading" href="/viewer/3">読む</a>',
        "00000000-0000-0000-0000-000000000002": '<button data-action-label="subscription_reading">10分まる読み</button>',
        "00000000-0000-0000-0000-000000000001": '<a data-action-label="trial_reading" href="?sample=1">試し読み</a>',
    }
    return f"""
      <h1 class="t-c-product-main-data__title">作品名{int(external_id[-1])}</h1>
      <div class="t-c-product-main-data__authors">作者A</div>
      <div id="js-read-check">{controls[external_id]}</div>
    """


async def test_bookwalker_discovery_scans_series_pages_and_product_controls(
    browser_page,
    tmp_path: Path,
) -> None:
    async def fulfill(route) -> None:
        url = route.request.url
        if "/series/123/list/" in url:
            body = _series_listing_html()
        else:
            external_id = url.split("/de", 1)[1].split("/", 1)[0]
            body = _product_html(external_id)
        await route.fulfill(body=body, content_type="text/html; charset=utf-8")

    await browser_page.route("https://bookwalker.jp/**", fulfill)
    target = WatchlistTarget(
        key="series-one",
        site="bookwalker",
        url="https://bookwalker.jp/series/123/list/",
        label="表示用シリーズ名",
    )
    adapter = BookWalkerDiscoveryAdapter()
    records = [record async for record in adapter.iter_records(browser_page, target, "full")]

    assert [item.source.external_id for item in records] == [
        "00000000-0000-0000-0000-000000000003",
        "00000000-0000-0000-0000-000000000002",
        "00000000-0000-0000-0000-000000000001",
    ]
    assert [item.source.access_mode for item in records] == ["owned", "quota", "paid"]
    assert all(item.item.canonical_title == "表示用シリーズ名" for item in records)
    assert all(item.item.author == "作者A" for item in records)

    catalog = CatalogService(tmp_path / "catalog.sqlite")
    assert catalog.list_sources() == []
