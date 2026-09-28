from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.async_api import Error, async_playwright

from screenshot_crawler.batch import BatchPlanner
from screenshot_crawler.catalog import CatalogService, ItemInput, SourceInput, WorkInput
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.discovery import (
    DiscoveryAdapterRegistry,
    DiscoveryService,
)
from screenshot_crawler.site_adapters.bookwalker import discovery as bookwalker_discovery
from screenshot_crawler.site_adapters.bookwalker.discovery import (
    BookWalkerDiscoveryAdapter,
    BookWalkerListedProduct,
    parse_bookwalker_order,
    parse_bookwalker_product_url,
)
from screenshot_crawler.site_policies import BookWalkerSitePolicy, SitePolicyRegistry
from screenshot_crawler.watchlist import WatchlistTarget


def _listed_product(
    number: int,
    title: str,
    *,
    special: bool = False,
) -> BookWalkerListedProduct:
    external_id = f"00000000-0000-0000-0000-{number:012d}"
    return BookWalkerListedProduct(
        external_id=external_id,
        url=f"https://bookwalker.jp/de{external_id}/",
        title=title,
        special=special,
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
        "00000000-0000-0000-0000-000000000003": '<div id="js-read-check-book-cover-main-button"><a data-action-label="read_purchased" href="/viewer/3">読む</a></div>',
        "00000000-0000-0000-0000-000000000002": '<button data-action-label="subscription_reading">10分まる読み</button>',
        "00000000-0000-0000-0000-000000000001": '<a data-action-label="trial_reading" href="?sample=1">試し読み</a>',
    }
    return f"""
      <h1 class="t-c-product-main-data__title">作品名{int(external_id[-1])}</h1>
      <div class="t-c-product-main-data__authors">作者A</div>
      <div id="js-read-check">{controls[external_id]}</div>
    """


def _uuid(number: int) -> str:
    return f"00000000-0000-0000-0000-{number:012d}"


def _product_url(external_id: str) -> str:
    return f"https://bookwalker.jp/de{external_id}/"


def _listing_html(
    products: list[tuple[str, str, bool]],
    *,
    header: str = "",
    next_button: str = "",
) -> str:
    cards = []
    for external_id, title, special in products:
        marker = '<span data-badge="special">購入特典</span>' if special else ""
        cards.append(
            f'<article><h3>{title}</h3>{marker}'
            f'<a href="/de{external_id}/">{title}</a></article>'
        )
    return (
        f"{header}<div id=\"js-series-list\"><h1>シリーズ公式タイトル</h1>"
        f"{''.join(cards)}{next_button}</div>"
    )


def _current_tile_listing_html(
    products: list[tuple[str, str, bool]],
) -> str:
    cards = []
    for external_id, title, _special in products:
        cards.append(
            f'<li class="m-tile"><div class="m-book-item">'
            f'<a class="m-thumb__image" href="/de{external_id}/"></a>'
            f'<p class="m-book-item__title"><a href="/de{external_id}/">'
            f"{title}</a></p></div></li>"
        )
    return f'<h1>シリーズ公式タイトル</h1><ul class="m-tile-list">{"".join(cards)}</ul>'


def _access_control(access_mode: str, *, click_endpoint: bool = False) -> str:
    onclick = " onclick=\"fetch('/__reader-click')\"" if click_endpoint else ""
    if access_mode == "owned":
        return f'<div id="js-read-check-book-cover-main-button"><a data-action-label="read_purchased" href="/viewer"{onclick}>読む</a></div>'
    if access_mode == "quota":
        return f'<button data-action-label="read_maruyomi"{onclick}>10分まる読み</button>'
    if access_mode == "paid":
        return f'<a data-action-label="trial_reading" href="?sample=1"{onclick}>試し読み</a>'
    if access_mode == "subscription":
        return '<button data-action-label="subscription_reading">読み放題で読む</button>'
    return ""


def _product_page_html(
    external_id: str,
    access_mode: str,
    *,
    title: str | None = None,
    delayed: bool = False,
    click_endpoint: bool = False,
    header: str = "",
) -> str:
    control = _access_control(access_mode, click_endpoint=click_endpoint)
    initial = "" if delayed else control
    delayed_script = (
        f"<script>setTimeout(() => document.querySelector('#js-read-check').innerHTML = "
        f"{control!r}, 300);</script>"
        if delayed
        else ""
    )
    return f"""{header}
      <h1 class="t-c-product-main-data__title">{title or f"作品名 {external_id[-2:]}"}</h1>
      <div class="t-c-product-main-data__authors">作者A</div>
      <div id="js-read-check">{initial}</div>
      {delayed_script}
    """


def _trial_to_maruyomi_product_html(external_id: str) -> str:
    return f"""
      <h1 class="t-c-product-main-data__title">作品名 {external_id[-2:]}</h1>
      <div class="t-c-product-main-data__authors">作者A</div>
      <div id="js-read-check">
        <a data-action-label="trial_reading" data-uuid="{external_id}">
          試し読み
        </a>
      </div>
      <script>
        setTimeout(() => document.querySelector('#js-read-check').innerHTML =
          '<button data-action-label="read_maruyomi">まる読み10分</button>', 50);
      </script>
    """


async def _install_route(
    page,
    products: list[tuple[str, str, bool]],
    access_modes: dict[str, str],
    *,
    listing_header: str = "",
    listing_next: str = "",
    product_titles: dict[str, str] | None = None,
    delayed_ids: set[str] | None = None,
    click_endpoint_counter: list[int] | None = None,
    redirect: dict[str, str] | None = None,
    product_header: str = "",
) -> None:
    product_titles = product_titles or {}
    delayed_ids = delayed_ids or set()
    redirect = redirect or {}

    async def fulfill(route) -> None:
        path = urlparse(route.request.url).path
        if path.startswith("/series/"):
            body = _listing_html(
                products,
                header=listing_header,
                next_button=listing_next,
            )
            await route.fulfill(body=body, content_type="text/html; charset=utf-8")
            return
        if path == "/__reader-click":
            if click_endpoint_counter is not None:
                click_endpoint_counter[0] += 1
            await route.fulfill(body="ok")
            return
        product = parse_bookwalker_product_url(route.request.url)
        if product is None:
            await route.fulfill(status=404, body="not found")
            return
        if product.external_id in redirect:
            await route.fulfill(
                status=302,
                headers={"location": _product_url(redirect[product.external_id])},
            )
            return
        body = _product_page_html(
            product.external_id,
            access_modes[product.external_id],
            title=product_titles.get(product.external_id),
            delayed=product.external_id in delayed_ids,
            click_endpoint=click_endpoint_counter is not None,
            header=product_header,
        )
        await route.fulfill(body=body, content_type="text/html; charset=utf-8")

    await page.route("https://bookwalker.jp/**", fulfill)


async def _run_service(page, tmp_path: Path, target: WatchlistTarget, mode: str):
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    registry = DiscoveryAdapterRegistry()
    registry.register("bookwalker", BookWalkerDiscoveryAdapter)
    result = await DiscoveryService(catalog, registry).discover(page, target, mode)
    return result, catalog


async def test_bookwalker_full_discovery_read_purchased_reaches_direct_batch_candidate(
    browser_page,
    tmp_path: Path,
) -> None:
    product = _uuid(16)
    target = _series_target()
    await _install_route(
        browser_page,
        [(product, "菴懷刀蜷・#16", False)],
        {product: "owned"},
    )

    result, catalog = await _run_service(browser_page, tmp_path, target, "full")

    assert result.complete is True
    source = catalog.get_source_by_external_id("bookwalker", product)
    assert source.access_mode == "owned"
    source_target = catalog.find_source_target(source.id, "web", "default")
    assert source_target is not None
    assert source_target.locator == _product_url(product)

    policies = SitePolicyRegistry()
    policies.register("bookwalker", BookWalkerSitePolicy)
    plan = BatchPlanner(catalog, policies).plan(
        site="bookwalker",
        now=datetime(2026, 9, 20, 12, 0, tzinfo=JST),
    )

    assert len(plan.candidates) == 1
    candidate = plan.candidates[0]
    assert candidate.access_mode == "owned"
    assert candidate.access_strategy == "direct"
    assert candidate.consumes_quota is False
    assert candidate.locator == _product_url(product)


def _seed_source(
    catalog: CatalogService,
    target: WatchlistTarget,
    external_id: str,
    access_mode: str,
    *,
    title: str | None = None,
) -> None:
    work = catalog.find_work(target.work_key)
    if work is None:
        work = catalog.create_work(WorkInput(work_key=target.work_key, title=target.label))
    item = catalog.create_item(
        ItemInput(item_title=title or external_id),
        work_id=work.id,
    )
    catalog.create_source(
        SourceInput(
            site=target.site,
            external_id=external_id,
            discovery_key=target.key,
            access_mode=access_mode,
        ),
        item_id=item.id,
    )


async def test_bookwalker_full_reconciles_first_volume_after_later_release(
    browser_page,
    tmp_path: Path,
) -> None:
    first = _uuid(1)
    second = _uuid(2)
    products = [(first, "作品名", False)]
    access_modes = {first: "paid", second: "paid"}

    async def fulfill(route) -> None:
        if "/series/123/list/" in route.request.url:
            cards = "".join(
                f'<article><h3>{title}</h3><a href="/de{external_id}/">{title}</a></article>'
                for external_id, title, _special in products
            )
            body = f'<div id="js-series-list"><h1>作品名</h1>{cards}</div>'
        else:
            product = parse_bookwalker_product_url(route.request.url)
            assert product is not None
            title = next(
                title
                for external_id, title, _special in products
                if external_id == product.external_id
            )
            body = _product_page_html(
                product.external_id,
                access_modes[product.external_id],
                title=title,
            )
        await route.fulfill(body=body, content_type="text/html; charset=utf-8")

    await browser_page.route("https://bookwalker.jp/**", fulfill)
    target = WatchlistTarget(
        key="series-one",
        work_key="series-work",
        site="bookwalker",
        url="https://bookwalker.jp/series/123/list/",
        label="独自label",
    )

    first_result, first_catalog = await _run_service(
        browser_page, tmp_path, target, "full"
    )
    first_source = first_catalog.get_source_by_external_id("bookwalker", first)
    first_item = first_catalog.get_item(first_source.item_id)
    assert first_result.complete is True
    assert first_item.order_key is None
    assert first_catalog.get_work(first_item.work_id).title == "独自label"

    products[:] = [
        (second, "作品名2", False),
        (first, "作品名", False),
    ]
    second_result, second_catalog = await _run_service(
        browser_page, tmp_path, target, "full"
    )

    first_source_after = second_catalog.get_source_by_external_id("bookwalker", first)
    second_source = second_catalog.get_source_by_external_id("bookwalker", second)
    first_item_after = second_catalog.get_item(first_source_after.item_id)
    second_item = second_catalog.get_item(second_source.item_id)
    assert second_result.complete is True
    assert first_source_after.item_id == first_source.item_id
    assert first_item_after.order_key == "1"
    assert first_item_after.order_label == parse_bookwalker_order("作品名1")[1]
    assert second_item.order_key == "2"


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
        work_key="series-work",
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


async def test_bookwalker_discovery_supports_current_tile_listing_dom(
    browser_page,
) -> None:
    products = [
        (_uuid(3), "作品名 #3", False),
        (_uuid(2), "【購入特典】作品名 #2", True),
        (_uuid(1), "作品名 #1", False),
    ]

    async def fulfill(route) -> None:
        if "/series/123/list/" in route.request.url:
            body = _current_tile_listing_html(products)
        else:
            external_id = route.request.url.split("/de", 1)[1].split("/", 1)[0]
            body = _product_html(external_id)
        await route.fulfill(body=body, content_type="text/html; charset=utf-8")

    await browser_page.route("https://bookwalker.jp/**", fulfill)
    records = [
        record async for record in BookWalkerDiscoveryAdapter().iter_records(
            browser_page, _series_target(), "full"
        )
    ]

    assert [item.source.external_id for item in records] == [
        _uuid(3),
        _uuid(2),
        _uuid(1),
    ]
    assert records[0].item.order_key == "3"
    assert records[1].item.order_key is None
    assert records[2].item.order_key == "1"


def _series_target(key: str = "series-one") -> WatchlistTarget:
    return WatchlistTarget(
        key=key,
        work_key="series-work",
        site="bookwalker",
        url="https://bookwalker.jp/series/123/list/",
        label="表示用シリーズ名",
    )


async def test_bookwalker_logged_out_series_stops_before_first_record(
    browser_page,
    tmp_path: Path,
) -> None:
    product = _uuid(16)
    await _install_route(
        browser_page,
        [(product, "作品名 #16", False)],
        {product: "paid"},
        listing_header='<header><a href="/login">ログイン</a></header>',
    )

    result, catalog = await _run_service(
        browser_page, tmp_path, _series_target(), "full"
    )

    assert result.stopped_reason == "incomplete"
    assert result.observed_count == 0
    assert catalog.list_sources() == []


async def test_bookwalker_logged_out_product_stops_before_upsert(
    browser_page,
    tmp_path: Path,
) -> None:
    product = _uuid(16)
    await _install_route(
        browser_page,
        [(product, "作品名 #16", False)],
        {product: "paid"},
        product_header='<header><a href="/login">ログイン</a></header>',
    )

    result, catalog = await _run_service(
        browser_page, tmp_path, _series_target(), "full"
    )

    assert result.stopped_reason == "incomplete"
    assert result.observed_count == 0
    assert catalog.list_sources() == []


async def test_bookwalker_delayed_control_is_observed_before_classification(
    browser_page,
    tmp_path: Path,
) -> None:
    product = _uuid(16)
    await _install_route(
        browser_page,
        [(product, "作品名 #16", False)],
        {product: "quota"},
        delayed_ids={product},
    )

    result, catalog = await _run_service(
        browser_page, tmp_path, _series_target(), "full"
    )

    assert result.complete is True
    assert catalog.get_source_by_external_id("bookwalker", product).access_mode == "quota"


async def test_bookwalker_trial_waits_for_later_maruyomi_control(
    browser_page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bookwalker_discovery, "PRODUCT_CONTROL_WAIT_TIMEOUT_MS", 1_000)
    product = _uuid(16)

    async def fulfill(route) -> None:
        if "/series/123/list/" in route.request.url:
            body = _listing_html([(product, "作品名 #16", False)])
        else:
            body = _trial_to_maruyomi_product_html(product)
        await route.fulfill(body=body, content_type="text/html; charset=utf-8")

    await browser_page.route("https://bookwalker.jp/**", fulfill)
    result, catalog = await _run_service(
        browser_page, tmp_path, _series_target(), "full"
    )

    assert result.complete is True
    assert catalog.get_source_by_external_id("bookwalker", product).access_mode == "quota"


async def test_bookwalker_no_control_product_is_unknown_not_incomplete(
    browser_page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bookwalker_discovery, "PRODUCT_CONTROL_WAIT_TIMEOUT_MS", 200)
    product = _uuid(16)
    await _install_route(
        browser_page,
        [(product, "購入特典", True)],
        {product: "unknown"},
    )

    result, catalog = await _run_service(
        browser_page, tmp_path, _series_target(), "full"
    )

    assert result.complete is True
    assert catalog.get_source_by_external_id("bookwalker", product).access_mode == "unknown"


async def test_bookwalker_related_trial_is_not_product_access_control(
    browser_page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bookwalker_discovery, "PRODUCT_CONTROL_WAIT_TIMEOUT_MS", 200)
    product = _uuid(16)
    related = _uuid(17)

    async def fulfill(route) -> None:
        if "/series/123/list/" in route.request.url:
            body = _listing_html([(product, "作品名 #16", False)])
        else:
            body = f"""
              <h1 class="t-c-product-main-data__title">作品名16</h1>
              <div class="t-c-product-main-data__authors">作者A</div>
              <div id="js-read-check"></div>
              <div id="js-series-list">
                <a data-action-label="trial_reading" data-uuid="{related}">試し読み</a>
              </div>
            """
        await route.fulfill(body=body, content_type="text/html; charset=utf-8")

    await browser_page.route("https://bookwalker.jp/**", fulfill)
    result, catalog = await _run_service(
        browser_page, tmp_path, _series_target(), "full"
    )

    assert result.complete is True
    assert catalog.get_source_by_external_id("bookwalker", product).access_mode == "unknown"


async def test_bookwalker_product_uuid_redirect_mismatch_is_incomplete(
    browser_page,
    tmp_path: Path,
) -> None:
    requested = _uuid(16)
    redirected = _uuid(17)
    await _install_route(
        browser_page,
        [(requested, "作品名 #16", False)],
        {requested: "paid", redirected: "paid"},
        redirect={requested: redirected},
    )

    result, catalog = await _run_service(
        browser_page, tmp_path, _series_target(), "full"
    )

    assert result.stopped_reason == "incomplete"
    assert catalog.list_sources() == []


async def test_bookwalker_special_card_does_not_use_hash_number_as_order_and_never_clicks(
    browser_page,
) -> None:
    normal = _uuid(16)
    special = _uuid(99)
    clicks = [0]
    await _install_route(
        browser_page,
        [
            (normal, "作品名 #16 サブタイトル", False),
            (special, "〖購入特典〗『作品名 #16 サブタイトル』BOOK☆WALKER限定", False),
        ],
        {normal: "paid", special: "paid"},
        click_endpoint_counter=clicks,
    )

    records = [
        record
        async for record in BookWalkerDiscoveryAdapter().iter_records(
            browser_page, _series_target(), "full"
        )
    ]

    assert records[0].item.order_key == "16"
    assert records[0].item.order_label == "第16巻"
    assert records[1].item.order_key is None
    assert "#16" in (records[1].item.order_label or "")
    assert records[1].source.access_mode == "unknown"
    assert clicks[0] == 0


@pytest.mark.parametrize(
    ("initial", "observed"),
    [
        ({"16": "paid", "15": "paid", "14": "quota"}, {"16": "paid", "15": "paid", "14": "quota"}),
        ({"16": "paid", "15": "paid", "14": "quota"}, {"16": "paid", "15": "quota", "14": "quota"}),
        ({"14": "quota"}, {"16": "quota", "15": "paid", "14": "quota"}),
        ({"16": "owned", "15": "paid"}, {"16": "owned", "15": "paid"}),
    ],
)
async def test_bookwalker_incremental_stable_boundary_via_service(
    browser_page,
    tmp_path: Path,
    initial: dict[str, str],
    observed: dict[str, str],
) -> None:
    products = [(_uuid(int(number)), f"作品名 #{number}", False) for number in ("16", "15", "14")]
    await _install_route(
        browser_page,
        products,
        {_uuid(int(number)): mode for number, mode in observed.items()},
    )
    target = _series_target()
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    for number, mode in initial.items():
        _seed_source(catalog, target, _uuid(int(number)), mode)
    registry = DiscoveryAdapterRegistry()
    registry.register("bookwalker", BookWalkerDiscoveryAdapter)

    result = await DiscoveryService(catalog, registry).discover(
        browser_page, target, "incremental"
    )

    assert result.stopped_reason == "stable_boundary"
    assert result.observed_count == (3 if "14" in initial else 1)
    if "15" in initial and initial["15"] == "paid" and observed["15"] == "quota":
        assert catalog.get_source_by_external_id("bookwalker", _uuid(15)).access_mode == "quota"


async def test_bookwalker_scope_conflict_is_incomplete_without_catalog_mutation(
    browser_page,
    tmp_path: Path,
) -> None:
    product = _uuid(16)
    await _install_route(
        browser_page,
        [(product, "作品名 #16", False)],
        {product: "paid"},
    )
    target = _series_target("new-series")
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key="series-work", title="旧タイトル"))
    old_item = catalog.create_item(ItemInput(item_title="旧タイトル"), work_id=work.id)
    old_source = catalog.create_source(
        SourceInput(
            site="bookwalker",
            external_id=product,
            discovery_key="old-series",
            access_mode="quota",
        ),
        item_id=old_item.id,
    )
    registry = DiscoveryAdapterRegistry()
    registry.register("bookwalker", BookWalkerDiscoveryAdapter)

    result = await DiscoveryService(catalog, registry).discover(
        browser_page, target, "full"
    )

    source = catalog.get_source(old_source.id)
    item = catalog.get_item(old_item.id)
    assert result.stopped_reason == "incomplete"
    assert source.discovery_key == "old-series"
    assert source.access_mode == "quota"
    assert catalog.get_work(item.work_id).title == "旧タイトル"


async def test_bookwalker_full_clean_exhaustion_reconciles_missing_source(
    browser_page,
    tmp_path: Path,
) -> None:
    observed_ids = [_uuid(number) for number in (16, 15, 14)]
    await _install_route(
        browser_page,
        [(external_id, f"作品名 #{number}", False) for number, external_id in zip((16, 15, 14), observed_ids)],
        {external_id: "paid" for external_id in observed_ids},
    )
    target = _series_target()
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    for number in (16, 15, 14, 13):
        _seed_source(catalog, target, _uuid(number), "paid")
    registry = DiscoveryAdapterRegistry()
    registry.register("bookwalker", BookWalkerDiscoveryAdapter)

    result = await DiscoveryService(catalog, registry).discover(
        browser_page, target, "full"
    )

    assert result.complete is True
    assert catalog.get_source_by_external_id("bookwalker", _uuid(13)).available is False


async def test_bookwalker_full_incomplete_keeps_missing_source_available(
    browser_page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bookwalker_discovery, "WAIT_TIMEOUT_MS", 200)
    observed = _uuid(16)
    await _install_route(
        browser_page,
        [(observed, "作品名 #16", False)],
        {observed: "paid"},
        listing_next='<button id="next">次へ</button>',
    )
    target = _series_target()
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    _seed_source(catalog, target, _uuid(13), "paid")
    registry = DiscoveryAdapterRegistry()
    registry.register("bookwalker", BookWalkerDiscoveryAdapter)

    result = await DiscoveryService(catalog, registry).discover(
        browser_page, target, "full"
    )

    assert result.complete is False
    assert result.stopped_reason == "incomplete"
    assert catalog.get_source_by_external_id("bookwalker", _uuid(13)).available is True
