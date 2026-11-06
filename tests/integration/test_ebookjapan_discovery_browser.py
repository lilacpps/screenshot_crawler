from __future__ import annotations

import time

import pytest
from playwright.async_api import BrowserContext, Page

from screenshot_crawler.catalog import CatalogService
from screenshot_crawler.core.errors import AccessStopError
from screenshot_crawler.discovery.registry import DiscoveryAdapterRegistry
from screenshot_crawler.discovery.service import DiscoveryService
from screenshot_crawler.site_adapters.ebookjapan import EbookJapanDiscoveryAdapter
from screenshot_crawler.site_adapters.ebookjapan import discovery as ebookjapan_discovery
from screenshot_crawler.watchlist.models import WatchlistTarget

pytestmark = pytest.mark.asyncio(loop_scope="module")

TARGET_URL = "https://ebookjapan.yahoo.co.jp/books/all/134336/"


def _card(
    product_id: str,
    title: str,
    *,
    owned: bool = False,
    not_owned: bool = False,
    unknown: bool = False,
    hidden_owned: bool = False,
) -> str:
    badges = (
        '<span class="book-caption__tagtext" style="display:none">購入済み</span>'
        if hidden_owned
        else '<span class="book-caption__tagtext">購入済み</span>' if owned else ""
    )
    price = '<div class="book-caption__price">646円（税込）</div>' if not_owned else ""
    cart = '<button><i class="font-basket-v1">カゴ</i></button>' if not_owned else ""
    if unknown:
        badges = ""
        price = ""
        cart = ""
    return (
        '<li class="book-list__item">'
        f'<a class="book-item" href="/books/134336/{product_id}/">book</a>'
        f'<div class="book-caption__title">{title}</div>'
        f'{badges}{price}{cart}'
        "</li>"
    )


def _html(
    *,
    second_owned: bool = False,
    first_not_owned: bool = False,
    first_unknown: bool = False,
    delayed_owned_hydration: bool = False,
    unrelated_pager_controls: bool = False,
    all_not_owned: bool = False,
    permanent_owned_mismatch: bool = False,
    logged_out: bool = False,
    hidden_first_owned: bool = False,
    declared_total: int | None = None,
) -> str:
    cards = [
        _card(
            "A000000001",
            "Example series（1）",
            owned=not first_not_owned and not first_unknown and not hidden_first_owned and not all_not_owned,
            not_owned=first_not_owned or all_not_owned,
            unknown=first_unknown,
            hidden_owned=hidden_first_owned,
        ),
        _card(
            "A000000002",
            "Example series 2巻",
            owned=second_owned and not all_not_owned,
            not_owned=not second_owned or all_not_owned,
        ),
        _card("A000000003", "Example series（3）", owned=not all_not_owned, not_owned=all_not_owned),
    ]
    account_shell = "" if logged_out else (
        '<div class="account__user">Synthetic signed-in marker '
        '<a href="/mypage/">mypage</a></div>'
    )
    total = declared_total if declared_total is not None else len(cards)
    unrelated_controls = (
        '<aside class="promotion"><button>次へ</button><span>9</span></aside>'
        if unrelated_pager_controls else ""
    )
    delayed_ownership = """
      <script>
        setTimeout(() => {
          const card = document.querySelectorAll('.book-list__item')[0];
          card.querySelector('.book-caption__tagtext')?.remove();
          const price = document.createElement('div');
          price.className = 'book-caption__price';
          price.textContent = '646円（税込）';
          card.append(price);
          const cart = document.createElement('button');
          cart.innerHTML = '<i class="font-basket-v1">カゴ</i>';
          card.append(cart);
        }, 100);
        setTimeout(() => {
          const card = document.querySelectorAll('.book-list__item')[0];
          card.querySelector('.book-caption__price')?.remove();
          card.querySelector('button')?.remove();
          const badge = document.createElement('span');
          badge.className = 'book-caption__tagtext';
          badge.textContent = '購入済み';
          card.append(badge);
        }, 2600);
      </script>
    """ if delayed_owned_hydration else ""
    permanent_mismatch = """
      <script>
        setTimeout(() => {
          const card = document.querySelectorAll('.book-list__item')[0];
          card.querySelector('.book-caption__tagtext')?.remove();
          const price = document.createElement('div');
          price.className = 'book-caption__price';
          price.textContent = '646円（税込）';
          card.append(price);
          const cart = document.createElement('button');
          cart.innerHTML = '<i class="font-basket-v1">カゴ</i>';
          card.append(cart);
        }, 50);
      </script>
    """ if permanent_owned_mismatch else ""
    return f"""<!doctype html>
<html><head><link rel="canonical" href="{TARGET_URL}"></head>
<body>
  {account_shell}
  <h1 class="page-books-all__heading">Example series</h1>
  <section class="page-books-all__list-header">
    <div class="search-header__result">{total}冊</div>
    <div class="search-filter__item"><label>1巻から<input type="radio" checked></label></div>
    <div class="search-filter__item"><label>最新巻から<input type="radio"></label></div>
  </section>
  <span class="book-caption__tagtext">購入済み</span>
  <ul>{''.join(cards)}</ul>
  {unrelated_controls}
  <div class="page-books-all__bottom"><a href="/books/134336/">作品詳細に戻る</a></div>
  <style>body {{ margin: 0; }} .book-list__item {{ height: 400px; }}</style>
  {delayed_ownership}
  {permanent_mismatch}
</body></html>"""


def _target() -> WatchlistTarget:
    return WatchlistTarget(
        key="example_ebookjapan",
        work_key="example",
        site="ebookjapan",
        url=TARGET_URL,
        label="Example series",
    )


async def _serve_html(page: Page, html: str) -> None:
    async def route(request_route) -> None:
        await request_route.fulfill(
            status=200,
            headers={"content-type": "text/html; charset=utf-8"},
            body=html,
        )

    await page.route("**/*", route)


async def test_full_discovery_buffers_visible_owned_cards_and_reconciles_history(
    browser_context: BrowserContext,
    tmp_path,
) -> None:
    page = await browser_context.new_page()
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    target = _target()
    registry = DiscoveryAdapterRegistry()
    registry.register("ebookjapan", EbookJapanDiscoveryAdapter)
    service = DiscoveryService(catalog, registry)
    html_state = {"value": _html(), "redirect": False}

    async def route(request_route) -> None:
        if html_state["redirect"] and request_route.request.url == TARGET_URL:
            await request_route.fulfill(
                status=302,
                headers={"location": TARGET_URL + "?alias=1"},
            )
            return
        await request_route.fulfill(
            status=200,
            headers={"content-type": "text/html; charset=utf-8"},
            body=html_state["value"],
        )

    await page.route("**/*", route)
    first = await service.discover(page, target, "full")
    assert first.complete is True
    assert (first.observed_count, first.new_count, first.known_count) == (2, 2, 0)
    sources = catalog.list_sources(site="ebookjapan")
    assert {source.external_id for source in sources} == {"A000000001", "A000000003"}
    assert {source.external_id: source.display_position for source in sources} == {
        "A000000001": 1,
        "A000000003": 3,
    }
    assert all(source.access_mode == "owned" and source.available for source in sources)
    evidence = catalog.get_discovery_inventory_evidence(target.key)
    assert evidence is not None and evidence.source_count == 3
    assert [
        (entry.external_id, entry.display_position, entry.in_scope)
        for entry in evidence.positions
    ] == [
        ("A000000001", 1, True),
        ("A000000002", 2, False),
        ("A000000003", 3, True),
    ]

    first_ids = {source.external_id: source.id for source in sources}
    completed_item = catalog.find_source("ebookjapan", "A000000001")
    assert completed_item is not None
    catalog.mark_item_completed(completed_item.item_id)
    second = await service.discover(page, target, "full")
    assert second.complete is True
    assert (second.observed_count, second.new_count, second.known_count) == (2, 0, 2)
    assert {source.external_id: source.id for source in catalog.list_sources(site="ebookjapan")} == first_ids
    assert catalog.get_item(completed_item.item_id).status == "completed"

    html_state["value"] = _html(second_owned=True)
    bought = await service.discover(page, target, "full")
    assert bought.complete is True and bought.new_count == 1
    newly_owned = catalog.find_source("ebookjapan", "A000000002")
    assert newly_owned is not None and newly_owned.available is True
    assert catalog.get_item(newly_owned.item_id).status == "pending"
    assert catalog.get_item(completed_item.item_id).status == "completed"

    html_state["value"] = _html(second_owned=True, first_not_owned=True)
    lost = await service.discover(page, target, "full")
    assert lost.complete is True and lost.observed_count == 2
    lost_source = catalog.find_source("ebookjapan", "A000000001")
    assert lost_source is not None and lost_source.available is False
    assert lost_source.id == first_ids["A000000001"]
    assert catalog.get_item(completed_item.item_id).status == "completed"

    state_before_unknown = {
        source.external_id: (source.id, source.available)
        for source in catalog.list_sources(site="ebookjapan")
    }
    html_state["value"] = _html(second_owned=True, first_unknown=True)
    incomplete = await service.discover(page, target, "full")
    assert incomplete.complete is False and incomplete.observed_count == 0
    assert any(
        marker in (incomplete.error or "")
        for marker in ("ownership is unknown", "rights branch is missing or ambiguous")
    )
    assert {
        source.external_id: (source.id, source.available)
        for source in catalog.list_sources(site="ebookjapan")
    } == state_before_unknown
    await page.close()


@pytest.mark.parametrize(
    "failure",
    ["logged_out", "hidden_owned", "incomplete_total", "redirect", "ownership_mismatch"],
)
async def test_incomplete_refresh_preserves_previous_owned_sources(
    browser_context: BrowserContext,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    page = await browser_context.new_page()
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    registry = DiscoveryAdapterRegistry()
    registry.register("ebookjapan", EbookJapanDiscoveryAdapter)
    service = DiscoveryService(catalog, registry)
    html_state = {"value": _html(), "redirect": False}

    async def route(request_route) -> None:
        if html_state["redirect"] and request_route.request.url == TARGET_URL:
            await request_route.fulfill(
                status=302,
                headers={"location": TARGET_URL + "?alias=1"},
            )
            return
        await request_route.fulfill(
            status=200,
            headers={"content-type": "text/html; charset=utf-8"},
            body=html_state["value"],
        )

    await page.route("**/*", route)
    first = await service.discover(page, _target(), "full")
    assert first.complete is True and first.observed_count == 2
    previous = {
        source.external_id: (source.id, source.available, catalog.get_item(source.item_id).status)
        for source in catalog.list_sources(site="ebookjapan")
    }

    if failure == "logged_out":
        html_state["value"] = _html(logged_out=True)
    elif failure == "hidden_owned":
        html_state["value"] = _html(hidden_first_owned=True)
    elif failure == "incomplete_total":
        html_state["value"] = _html(declared_total=4)
    elif failure == "ownership_mismatch":
        html_state["value"] = _html(permanent_owned_mismatch=True)
    else:
        html_state["redirect"] = True
    if failure in {"logged_out", "incomplete_total", "ownership_mismatch"}:
        monkeypatch.setattr(ebookjapan_discovery, "SCROLL_TIMEOUT_MS", 300)
        monkeypatch.setattr(ebookjapan_discovery, "SCROLL_POLL_MS", 50)

    failed = await service.discover(page, _target(), "full")

    assert failed.complete is False and failed.observed_count == 0
    assert {
        source.external_id: (source.id, source.available, catalog.get_item(source.item_id).status)
        for source in catalog.list_sources(site="ebookjapan")
    } == previous
    await page.close()


async def test_full_discovery_ignores_global_owned_badge_for_card_access(
    browser_context: BrowserContext,
    tmp_path,
) -> None:
    page = await browser_context.new_page()
    await _serve_html(page, _html(first_not_owned=True))
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    registry = DiscoveryAdapterRegistry()
    registry.register("ebookjapan", EbookJapanDiscoveryAdapter)

    result = await DiscoveryService(catalog, registry).discover(page, _target(), "full")

    assert result.complete is True and result.observed_count == 1
    assert [source.external_id for source in catalog.list_sources(site="ebookjapan")] == [
        "A000000003"
    ]
    await page.close()


async def test_full_discovery_accepts_verified_zero_owned_listing(
    browser_context: BrowserContext,
    tmp_path,
) -> None:
    page = await browser_context.new_page()
    await _serve_html(page, _html(all_not_owned=True))
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    registry = DiscoveryAdapterRegistry()
    registry.register("ebookjapan", EbookJapanDiscoveryAdapter)

    result = await DiscoveryService(catalog, registry).discover(page, _target(), "full")

    assert result.complete is True and result.observed_count == 0
    assert catalog.list_sources(site="ebookjapan") == []
    evidence = catalog.get_discovery_inventory_evidence(_target().key)
    assert evidence is not None and evidence.source_count == 3
    assert all(not position.in_scope for position in evidence.positions)
    await page.close()


async def test_full_discovery_ignores_unrelated_pager_and_waits_for_static_owned_hydration(
    browser_context: BrowserContext,
    tmp_path,
) -> None:
    page = await browser_context.new_page()
    await _serve_html(
        page,
        _html(delayed_owned_hydration=True, unrelated_pager_controls=True),
    )
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    registry = DiscoveryAdapterRegistry()
    registry.register("ebookjapan", EbookJapanDiscoveryAdapter)

    started = time.monotonic()
    result = await DiscoveryService(catalog, registry).discover(page, _target(), "full")
    elapsed = time.monotonic() - started

    assert elapsed >= 2.4
    assert result.complete is True and result.observed_count == 2
    assert {source.external_id for source in catalog.list_sources(site="ebookjapan")} == {
        "A000000001",
        "A000000003",
    }
    await page.close()


@pytest.mark.parametrize(("late_host", "should_stop"), [("ebookjapan", True), ("ad", False)])
async def test_final_guard_check_observes_late_403_and_ignores_unrelated_host(
    browser_context: BrowserContext,
    late_host: str,
    should_stop: bool,
) -> None:
    page = await browser_context.new_page()
    html = _html()
    late_url = (
        "https://ebookjapan.yahoo.co.jp/books/all/134336/late-access-check"
        if late_host == "ebookjapan"
        else "https://ads.example.test/late-access-check"
    )

    async def route(request_route) -> None:
        if request_route.request.url == TARGET_URL:
            await request_route.fulfill(
                status=200,
                headers={"content-type": "text/html; charset=utf-8"},
                body=html,
            )
        elif request_route.request.url == late_url:
            await request_route.fulfill(status=403, body="")
        else:
            await request_route.abort()

    await page.route("**/*", route)

    class LateResponsePage:
        def __init__(self, wrapped_page: Page) -> None:
            self.wrapped_page = wrapped_page
            self.listing_snapshots = 0

        def __getattr__(self, name: str):
            return getattr(self.wrapped_page, name)

        async def evaluate(self, expression, *args):
            result = await self.wrapped_page.evaluate(expression, *args)
            if expression == ebookjapan_discovery._FULL_LISTING_JS:
                self.listing_snapshots += 1
                if self.listing_snapshots == 6:
                    await self.wrapped_page.evaluate(
                        "async url => (await fetch(url)).status",
                        late_url,
                    )
            return result

    guarded_page = LateResponsePage(page)
    adapter = EbookJapanDiscoveryAdapter()
    records = adapter.iter_records(guarded_page, _target(), "full")
    if should_stop:
        with pytest.raises(AccessStopError) as stop:
            await anext(records)
        assert stop.value.reason == "http_403"
        assert stop.value.host == "ebookjapan.yahoo.co.jp"
        assert adapter.complete_listing_inventory is None
    else:
        yielded = [record async for record in records]
        assert len(yielded) == 2
        assert adapter.complete_listing_inventory is not None
    assert guarded_page.listing_snapshots == 6
    await page.close()
