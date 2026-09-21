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
from screenshot_crawler.site_adapters.magapoke.discovery import (
    MagapokeDiscoveryAdapter,
    canonical_magapoke_episode_url,
    map_magapoke_access_mode,
    parse_magapoke_episode_url,
)
from screenshot_crawler.watchlist import WatchlistTarget

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


def _row(
    episode_id: str,
    title: str,
    icon_class: str | None = None,
    icon_text: str = "",
) -> str:
    icon = ""
    if icon_class:
        icon = (
            '<div class="c-episode-item__ico '
            f'{icon_class}">{icon_text}</div>'
        )
    return f"""
      <li class="c-episode-items__item">
        <a class="c-episode-item" href="/title/00695/episode/{episode_id}">
          <div class="c-episode-item__detail">
            <h2 class="c-episode-item__ttl">{title}</h2>
            <div class="c-episode-item__label02">{icon}</div>
          </div>
        </a>
      </li>
    """


def _listing_html(
    *,
    duplicate: bool = False,
    wrong_work: bool = False,
    no_progress: bool = False,
    split_list_containers: bool = False,
) -> str:
    first = _row(
        "244819",
        "【第５話】「最新」(1)",
        "c-episode-item__ico--point",
        "90",
    )
    tail_id = "999001" if wrong_work else "244815"
    tail_href = f"/title/{'99999' if wrong_work else '00695'}/episode/{tail_id}"
    tail = f"""
      <li class="c-episode-items__item">
        <a class="c-episode-item" href="{tail_href}">
          <div class="c-episode-item__detail">
            <h2 class="c-episode-item__ttl">【第１話】「起点」(1)</h2>
          </div>
        </a>
      </li>
    """
    duplicate_tail = tail if duplicate else ""
    second_list = ""
    if split_list_containers:
        second_list = f'''
        <div class="p-episode__list">
          <ul class="c-episode-items">{_row("244814", "前編")}</ul>
        </div>
        '''
    no_progress_script = "" if no_progress else """
        const makeRow = (id, title, iconClass, text = '') => `
          <li class="c-episode-items__item">
            <a class="c-episode-item" href="/title/00695/episode/${id}">
              <div class="c-episode-item__detail">
                <h2 class="c-episode-item__ttl">${title}</h2>
                <div class="c-episode-item__label02">
                  ${iconClass ? `<div class="c-episode-item__ico ${iconClass}">${text}</div>` : ''}
                </div>
              </div>
            </a>
          </li>`;
        let expansion = 0;
        document.querySelector('#more').addEventListener('click', () => {
          if (expansion === 0) {
            tail.insertAdjacentHTML('beforebegin', makeRow('244818', '【第４話】「四」(1)', 'c-episode-item__ico--ticket-free'));
            tail.insertAdjacentHTML('beforebegin', makeRow('244817', '【第３話】「三」(1)', 'c-episode-item__ico--renting', 'あと71時間'));
            expansion += 1;
          } else if (expansion === 1) {
            tail.insertAdjacentHTML('beforebegin', makeRow('244816', '【第２話】「二」(1)', 'c-episode-item__ico--free'));
            document.querySelector('#more').remove();
            expansion += 1;
          }
        });
    """
    return f"""
    <html><head><title>fixture</title></head><body>
      <h1 class="p-episode__comic-ttl">Fixture Work</h1>
      <div class="p-episode__sec">
        <div class="p-episode__list">
          <ul class="c-episode-items">{first}{tail}{duplicate_tail}</ul>
          <button id="more" class="p-episode__more-btn">もっと見る</button>
        </div>
        {second_list}
      </div>
      <div class="p-episode__sec" style="display:none">
        <button class="p-episode__more-btn">もっと見る</button>
      </div>
      <script>
        const tail = document.querySelector('.c-episode-items > li:last-child');
        {no_progress_script}
      </script>
    </body></html>
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


def _target() -> WatchlistTarget:
    return WatchlistTarget(
        key="magapoke-fixture",
        work_key="magapoke-work",
        site="magapoke",
        url=TARGET_URL,
        label="Fixture Work",
    )


async def _install_route(page, html: str) -> None:
    async def fulfill(route) -> None:
        await route.fulfill(body=html, content_type="text/html; charset=utf-8")

    await page.route("https://pocket.shonenmagazine.com/**", fulfill)


async def test_magapoke_full_discovery_expands_validates_and_syncs_catalog(
    browser_page,
    tmp_path: Path,
) -> None:
    await _install_route(browser_page, _listing_html())
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    registry = DiscoveryAdapterRegistry()
    registry.register("magapoke", MagapokeDiscoveryAdapter)

    result = await DiscoveryService(catalog, registry).discover(
        browser_page, _target(), "full"
    )

    assert result.complete is True
    assert result.observed_count == 5
    assert result.stopped_reason == "exhausted"
    assert [source.external_id for source in catalog.list_sources()] == [
        "244819",
        "244818",
        "244817",
        "244816",
        "244815",
    ]
    assert [source.access_mode for source in catalog.list_sources()] == [
        "paid",
        "quota",
        "quota",
        "free",
        "unknown",
    ]
    assert all(item.order_key is None for item in catalog.list_items())
    assert [item.order_label for item in catalog.list_items()] == [
        "【第５話】「最新」(1)",
        "【第４話】「四」(1)",
        "【第３話】「三」(1)",
        "【第２話】「二」(1)",
        "【第１話】「起点」(1)",
    ]


async def test_magapoke_incremental_uses_generic_known_streak(
    browser_page,
    tmp_path: Path,
) -> None:
    await _install_route(browser_page, _listing_html())
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    registry = DiscoveryAdapterRegistry()
    registry.register("magapoke", MagapokeDiscoveryAdapter)
    service = DiscoveryService(catalog, registry)

    await service.discover(browser_page, _target(), "full")
    result = await service.discover(browser_page, _target(), "incremental")

    assert result.complete is None
    assert result.observed_count == 5
    assert result.known_count == 5
    assert result.stopped_reason == "known_streak"


async def test_magapoke_handles_multiple_list_containers_in_one_section(
    browser_page,
    tmp_path: Path,
) -> None:
    await _install_route(browser_page, _listing_html(split_list_containers=True))
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    registry = DiscoveryAdapterRegistry()
    registry.register("magapoke", MagapokeDiscoveryAdapter)

    result = await DiscoveryService(catalog, registry).discover(
        browser_page, _target(), "full"
    )

    assert result.complete is True
    assert [source.external_id for source in catalog.list_sources()] == [
        "244819",
        "244818",
        "244817",
        "244816",
        "244815",
        "244814",
    ]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"duplicate": True}, "duplicate"),
        ({"wrong_work": True}, "different title_id"),
    ],
)
async def test_magapoke_invalid_identity_is_incomplete_without_partial_catalog_write(
    browser_page,
    tmp_path: Path,
    kwargs: dict[str, bool],
    message: str,
) -> None:
    await _install_route(browser_page, _listing_html(**kwargs))
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    registry = DiscoveryAdapterRegistry()
    registry.register("magapoke", MagapokeDiscoveryAdapter)

    result = await DiscoveryService(catalog, registry).discover(
        browser_page, _target(), "full"
    )

    assert result.complete is False
    assert result.stopped_reason == "incomplete"
    assert catalog.list_sources() == []
    assert message in " ".join(result.warnings) or result.observed_count == 0


async def test_magapoke_no_progress_is_incomplete(
    browser_page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "screenshot_crawler.site_adapters.magapoke.discovery.WAIT_TIMEOUT_MS",
        200,
    )
    monkeypatch.setattr(
        "screenshot_crawler.site_adapters.magapoke.discovery.POLL_INTERVAL_MS",
        20,
    )
    await _install_route(browser_page, _listing_html(no_progress=True))
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    registry = DiscoveryAdapterRegistry()
    registry.register("magapoke", MagapokeDiscoveryAdapter)

    result = await DiscoveryService(catalog, registry).discover(
        browser_page, _target(), "full"
    )

    assert result.complete is False
    assert result.stopped_reason == "incomplete"
    assert catalog.list_sources() == []
