from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from screenshot_crawler.catalog import CatalogService
from screenshot_crawler.discovery import DiscoveryAdapterRegistry, DiscoveryService
from screenshot_crawler.site_adapters.piccoma import PiccomaDiscoveryAdapter
from screenshot_crawler.watchlist import DiscoveryScope, WatchlistTarget

pytestmark = pytest.mark.asyncio(loop_scope="module")


def _listing_html(
    *,
    list_class: str = "PCM-epList PCM-epList_published PCM-list_asc",
    declared_count: int = 4,
    product_id: str = "900",
    duplicate_last_id: bool = False,
    foreign_last_product_id: str | None = None,
    free_wrapper_marker: str | None = None,
    first_marker: str = "PCM-epList_status_free",
    first_label: str = "¥0",
) -> str:
    rows = (
        ("101", "第1話 Alpha", first_marker, first_label),
        ("102", "第2話 Beta", "PCM-epList_status_waitfree PCM-epList_status_bingefree", ""),
        ("103", "第3話 Gamma", "PCM-epList_status_point js_point", "69"),
        (
            "103" if duplicate_last_id else "104",
            "第4話 Delta",
            "PCM-epList_status_other",
            "公開終了",
        ),
    )
    cards = "\n".join(
        f"""<a href="#" data-user_access="require" data-product_id="{foreign_last_product_id if index == 3 and foreign_last_product_id else product_id}" data-episode_id="{episode_id}">
          <div class="PCM-epList_ep">
            <div class="PCM-epList_title">{title}</div>
            <div class="PCM-epList_status{(' ' + free_wrapper_marker) if index == 0 and free_wrapper_marker else ''}"><p class="{marker}"><span>{label}</span></p></div>
          </div>
        </a>"""
        for index, (episode_id, title, marker, label) in enumerate(rows)
    )
    return f"""<!doctype html>
    <html><head><title>Fixture</title></head><body>
      <main id="js_contentBody">
        <div class="PCM-headTitle_name">Fixture Work</div>
        <p>全{declared_count}話</p>
        <section class="PCM-productSaleList_episode">
          <ul id="js_episodeList" class="{list_class}">{cards}</ul>
        </section>
      </main>
    </body></html>"""


def _target(
    *,
    episode_id: str = "101",
    discovery_scope: DiscoveryScope | None = None,
) -> WatchlistTarget:
    return WatchlistTarget(
        key="piccoma-fixture",
        work_key="piccoma-fixture-work",
        site="piccoma",
        url=f"https://piccoma.com/web/viewer/900/{episode_id}",
        label="Fixture Work Label",
        discovery_scope=discovery_scope,
    )


async def _install_listing(browser_page, html: str | Callable[[], str]) -> None:
    async def fulfill(route) -> None:
        body = html() if callable(html) else html
        await route.fulfill(body=body, content_type="text/html; charset=utf-8")

    await browser_page.route("https://piccoma.com/**", fulfill)


def _registry() -> DiscoveryAdapterRegistry:
    registry = DiscoveryAdapterRegistry()
    registry.register("piccoma", PiccomaDiscoveryAdapter)
    return registry


async def test_piccoma_full_discovery_validates_and_syncs_complete_latest_first_listing(
    browser_page, tmp_path: Path
) -> None:
    await _install_listing(browser_page, _listing_html())
    catalog = CatalogService(tmp_path / "catalog.sqlite")

    result = await DiscoveryService(catalog, _registry()).discover(
        browser_page, _target(), "full"
    )

    sources = catalog.list_sources(site="piccoma")
    assert result.complete is True
    assert result.observed_count == 4
    assert [source.external_id for source in sources] == [
        "900:104",
        "900:103",
        "900:102",
        "900:101",
    ]
    assert {source.external_id: source.access_mode for source in sources} == {
        "900:101": "free",
        "900:102": "quota",
        "900:103": "paid",
        "900:104": "unknown",
    }
    assert {source.external_id: source.display_position for source in sources} == {
        "900:101": 1,
        "900:102": 2,
        "900:103": 3,
        "900:104": 4,
    }
    assert {target.locator for target in catalog.list_source_targets()} == {
        f"https://piccoma.com/web/viewer/900/{episode_id}"
        for episode_id in ("101", "102", "103", "104")
    }
    assert all(source.discovery_key == "piccoma-fixture" for source in sources)


@pytest.mark.parametrize(
    "wrapper_marker",
    ["PCM-epList_status_waitfree", "PCM-epList_status_unrecognized"],
)
async def test_piccoma_status_markers_on_wrapper_conflict_with_nested_free(
    browser_page, tmp_path: Path, wrapper_marker: str
) -> None:
    await _install_listing(
        browser_page,
        _listing_html(free_wrapper_marker=wrapper_marker),
    )
    catalog = CatalogService(tmp_path / "catalog.sqlite")

    result = await DiscoveryService(catalog, _registry()).discover(
        browser_page, _target(), "full"
    )

    assert result.complete is True
    assert next(
        source for source in catalog.list_sources(site="piccoma")
        if source.external_id == "900:101"
    ).access_mode == "unknown"


async def test_piccoma_full_rediscovery_updates_access_state_and_preserves_completed_item(
    browser_page, tmp_path: Path
) -> None:
    current_html = {"body": _listing_html()}
    await _install_listing(browser_page, lambda: current_html["body"])
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    service = DiscoveryService(catalog, _registry())

    initial = await service.discover(browser_page, _target(), "full")
    assert initial.complete is True
    source = next(
        source for source in catalog.list_sources(site="piccoma")
        if source.external_id == "900:101"
    )
    item_id = source.item_id
    catalog.mark_item_completed(item_id)

    for marker, label, expected_access in (
        ("PCM-epList_status_point js_point", "69", "paid"),
        (
            "PCM-epList_status_waitfree PCM-epList_status_bingefree",
            "",
            "quota",
        ),
        ("PCM-epList_status_unknown", "公開終了", "unknown"),
    ):
        current_html["body"] = _listing_html(
            first_marker=marker,
            first_label=label,
        )
        refreshed = await service.discover(browser_page, _target(), "full")

        assert refreshed.complete is True
        refreshed_source = next(
            source for source in catalog.list_sources(site="piccoma")
            if source.external_id == "900:101"
        )
        assert refreshed_source.id == source.id
        assert refreshed_source.access_mode == expected_access
        assert catalog.get_item(item_id).status == "completed"


async def test_piccoma_incremental_uses_latest_first_generic_discovery_order(
    browser_page, tmp_path: Path
) -> None:
    await _install_listing(browser_page, _listing_html())
    catalog = CatalogService(tmp_path / "catalog.sqlite")

    result = await DiscoveryService(catalog, _registry()).discover(
        browser_page, _target(), "incremental"
    )

    assert result.complete is None
    assert result.stopped_reason == "exhausted"
    assert [source.external_id for source in catalog.list_sources(site="piccoma")] == [
        "900:104",
        "900:103",
        "900:102",
        "900:101",
    ]


async def test_piccoma_bounded_full_preserves_complete_list_positions(
    browser_page, tmp_path: Path
) -> None:
    await _install_listing(browser_page, _listing_html())
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    target = _target(
        discovery_scope=DiscoveryScope(
            from_url="https://piccoma.com/web/viewer/900/103",
            through_url="https://piccoma.com/web/viewer/900/102",
        )
    )

    result = await DiscoveryService(catalog, _registry()).discover(
        browser_page, target, "full"
    )

    assert result.complete is True
    sources = catalog.list_sources(site="piccoma")
    assert [source.external_id for source in sources] == ["900:103", "900:102"]
    assert [source.display_position for source in sources] == [3, 2]


@pytest.mark.parametrize(
    "html",
    [
        _listing_html(declared_count=5),
        _listing_html(duplicate_last_id=True),
        _listing_html(foreign_last_product_id="901"),
        _listing_html(list_class="PCM-epList PCM-epList_published PCM-list_desc"),
    ],
)
async def test_piccoma_incomplete_listing_never_writes_partial_sources(
    browser_page, tmp_path: Path, html: str
) -> None:
    await _install_listing(browser_page, html)
    catalog = CatalogService(tmp_path / "catalog.sqlite")

    result = await DiscoveryService(catalog, _registry()).discover(
        browser_page, _target(), "full"
    )

    assert result.complete is False
    assert result.observed_count == 0
    assert catalog.list_items() == []
    assert catalog.list_sources() == []
    assert catalog.list_source_targets() == []


async def test_piccoma_cross_product_redirect_fails_before_catalog_writes(
    browser_page, tmp_path: Path
) -> None:
    async def redirect(route) -> None:
        if route.request.url.endswith("/web/product/900/episodes"):
            await route.fulfill(
                status=302,
                headers={"Location": "https://piccoma.com/web/product/901/episodes"},
            )
            return
        await route.fulfill(
            body=_listing_html(product_id="901"),
            content_type="text/html; charset=utf-8",
        )

    await browser_page.route("https://piccoma.com/**", redirect)
    catalog = CatalogService(tmp_path / "catalog.sqlite")

    result = await DiscoveryService(catalog, _registry()).discover(
        browser_page, _target(), "full"
    )

    assert result.complete is False
    assert result.observed_count == 0
    assert catalog.list_items() == []
    assert catalog.list_sources() == []
    assert catalog.list_source_targets() == []


async def test_piccoma_target_must_belong_to_complete_product_listing(
    browser_page, tmp_path: Path
) -> None:
    await _install_listing(browser_page, _listing_html())
    catalog = CatalogService(tmp_path / "catalog.sqlite")

    result = await DiscoveryService(catalog, _registry()).discover(
        browser_page, _target(episode_id="999"), "full"
    )

    assert result.complete is False
    assert result.observed_count == 0
    assert catalog.list_items() == []
    assert catalog.list_sources() == []


@pytest.mark.parametrize(
    "scope",
    [
        DiscoveryScope(from_url="https://example.test/web/viewer/900/103"),
        DiscoveryScope(from_url="https://piccoma.com/web/viewer/901/103"),
        DiscoveryScope(from_url="https://piccoma.com/web/viewer/900/999"),
        DiscoveryScope(
            from_url="https://piccoma.com/web/viewer/900/102",
            through_url="https://piccoma.com/web/viewer/900/103",
        ),
    ],
)
async def test_piccoma_invalid_boundaries_fail_before_catalog_writes(
    browser_page, tmp_path: Path, scope: DiscoveryScope
) -> None:
    await _install_listing(browser_page, _listing_html())
    catalog = CatalogService(tmp_path / "catalog.sqlite")

    result = await DiscoveryService(catalog, _registry()).discover(
        browser_page, _target(discovery_scope=scope), "full"
    )

    assert result.complete is False
    assert result.observed_count == 0
    assert catalog.list_items() == []
    assert catalog.list_sources() == []
    assert catalog.list_source_targets() == []
