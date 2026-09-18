from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.async_api import Error, async_playwright

from screenshot_crawler.catalog import CatalogService, ItemInput
from screenshot_crawler.discovery import (
    DiscoveredItem,
    DiscoveredRecord,
    DiscoveredSource,
    DiscoveryAdapterRegistry,
    DiscoveryIncompleteError,
    DiscoveryService,
    DiscoverySourceSnapshot,
    IncrementalStopDecision,
)
from screenshot_crawler.site_adapters.bookwalker import discovery as bookwalker_discovery
from screenshot_crawler.site_adapters.bookwalker.discovery import (
    BookWalkerAccountState,
    BookWalkerDiscoveryAdapter,
    classify_bookwalker_account_state,
    is_bookwalker_special_title,
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
    ("metadata", "expected"),
    [
        ({"login_cta": True}, BookWalkerAccountState.LOGGED_OUT),
        ({"password_input": True}, BookWalkerAccountState.LOGGED_OUT),
        ({"auth_challenge": True}, BookWalkerAccountState.AMBIGUOUS),
        ({"member_link": True}, BookWalkerAccountState.READY),
        ({}, BookWalkerAccountState.READY),
    ],
)
def test_bookwalker_account_state_requires_explicit_account_evidence(
    metadata: dict[str, object],
    expected: BookWalkerAccountState,
) -> None:
    assert classify_bookwalker_account_state(metadata) is expected


@pytest.mark.parametrize(
    "title",
    [
        "【購入特典】作品",
        "【特典】作品",
        "〖購入特典〗作品",
        "〖特典〗作品",
    ],
)
def test_bookwalker_special_title_prefixes(title: str) -> None:
    assert is_bookwalker_special_title(title) is True


@pytest.mark.parametrize(
    "title",
    [
        "作品名 #16",
        "作品名 特典について #16",
    ],
)
def test_bookwalker_special_title_requires_prefix(title: str) -> None:
    assert is_bookwalker_special_title(title) is False


@pytest.mark.parametrize(
    ("controls", "expected"),
    [
        ([{"text": "試し読み", "action": "trial_reading", "href": ""}], "paid"),
        ([{"text": "10分まる読み", "action": "subscription_reading", "href": ""}], "quota"),
        ([{"text": "読み放題で読む", "action": "subscription_reading", "href": ""}], "unknown"),
        ([{"text": "", "action": None, "href": "https://viewer.bookwalker.jp/viewer"}], "unknown"),
        ([], "unknown"),
        ([{"text": "読む", "action": "reading", "href": ""}], "owned"),
        (
            [
                {"text": "試し読み", "action": "trial_reading", "href": ""},
                {"text": "読む", "action": "reading", "href": ""},
            ],
            "owned",
        ),
        (
            [
                {"text": "試し読み", "action": "trial_reading", "href": ""},
                {"text": "10分まる読み", "action": "read_maruyomi", "href": ""},
            ],
            "quota",
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
    assert parse_bookwalker_order("作品名 #16 サブタイトル") == ("16", "第16巻")
    assert parse_bookwalker_order("作品名 第16巻") == ("16", "第16巻")
    assert parse_bookwalker_order("作品名 16巻") == ("16", "第16巻")
    assert parse_bookwalker_order(
        "【購入特典】『作品名 #16 サブタイトル』BOOK☆WALKER限定",
        special=True,
    ) == (
        None,
        "『作品名 #16 サブタイトル』BOOK☆WALKER限定",
    )
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
    minimal_record = DiscoveredRecord(
        item=DiscoveredItem(),
        source=DiscoveredSource(
            external_id="product-one",
            url="https://bookwalker.jp/deproduct-one/",
        ),
    )
    assert adapter.incremental_stop_decision(minimal_record, previous, target) is (
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
        return f'<a data-action-label="reading" href="/viewer"{onclick}>読む</a>'
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


def _seed_source(
    catalog: CatalogService,
    target: WatchlistTarget,
    external_id: str,
    access_mode: str,
    *,
    title: str | None = None,
) -> None:
    catalog.upsert_item_source(
        ItemInput(canonical_title=title or external_id),
        {
            "site": target.site,
            "external_id": external_id,
            "discovery_key": target.key,
            "url": _product_url(external_id),
            "access_mode": access_mode,
        },
    )


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
        site="bookwalker",
        url="https://bookwalker.jp/series/123/list/",
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
    existing = catalog.upsert_item_source(
        ItemInput(canonical_title="旧タイトル"),
        {
            "site": "bookwalker",
            "external_id": product,
            "discovery_key": "old-series",
            "url": _product_url(product),
            "access_mode": "quota",
        },
    )
    registry = DiscoveryAdapterRegistry()
    registry.register("bookwalker", BookWalkerDiscoveryAdapter)

    result = await DiscoveryService(catalog, registry).discover(
        browser_page, target, "full"
    )

    source = catalog.get_source(existing.source.id)
    item = catalog.get_item(existing.item.id)
    assert result.stopped_reason == "incomplete"
    assert source.discovery_key == "old-series"
    assert source.access_mode == "quota"
    assert item.canonical_title == "旧タイトル"


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
