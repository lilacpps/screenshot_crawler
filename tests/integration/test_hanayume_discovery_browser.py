from __future__ import annotations

import json
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from screenshot_crawler.batch import (
    BatchExecutionError,
    BatchExecutor,
    BatchPlanner,
    CandidateExecutionError,
)
from screenshot_crawler.catalog import CatalogService
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.core.packaging import package_crawl_output
from screenshot_crawler.discovery import DiscoveryAdapterRegistry, DiscoveryService
from screenshot_crawler.runtime_settings import SiteRuntimeSettings
from screenshot_crawler.site_adapters.hanayume import HanayumeAdapter, HanayumeDiscoveryAdapter
from screenshot_crawler.site_adapters.hanayume import adapter as hanayume_adapter
from screenshot_crawler.site_adapters.hanayume import discovery as hanayume_discovery
from screenshot_crawler.site_adapters.registry import AdapterRegistry
from screenshot_crawler.site_policies import SitePolicyRegistry
from screenshot_crawler.site_policies.hanayume import HanayumeSitePolicy
from screenshot_crawler.watchlist import DiscoveryScope, WatchlistTarget

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest.fixture(autouse=True)
def _short_hanayume_test_timeouts(monkeypatch) -> None:
    monkeypatch.setattr(hanayume_discovery, "NAVIGATION_TIMEOUT_MS", 3_000)
    monkeypatch.setattr(hanayume_discovery, "DOM_TIMEOUT_MS", 3_000)
    monkeypatch.setattr(hanayume_discovery, "RANGE_PACING_MS", 10)
    monkeypatch.setattr(hanayume_adapter, "NAVIGATION_TIMEOUT_MS", 3_000)
    monkeypatch.setattr(hanayume_adapter, "DOM_TIMEOUT_MS", 3_000)
    monkeypatch.setattr(hanayume_adapter, "RANGE_PACING_MS", 0)
    monkeypatch.setattr(hanayume_discovery, "SERIES_AUTH_HYDRATION_TIMEOUT_SECONDS", 0.45)
    monkeypatch.setattr(hanayume_adapter, "VIEWER_COUNTER_READY_TIMEOUT_MS", 400)
    monkeypatch.setattr(HanayumeAdapter, "page_change_timeout_ms", 1_000)

BASE = "https://hanayume.com"
SEED_ID = f"{1:013x}"
WORK_ID = f"{900:013x}"
TOTAL = 32
TARGET_POSITION = 2
NOW_FREE_LABEL = "\u4eca\u306a\u3089\u7121\u6599"


def _episode_id(position: int) -> str:
    return f"{position:013x}"


def _title(position: int) -> str:
    if position in (4, 5):
        return f"第4話{'①' if position == 4 else '②'}"
    return f"第{position}話"


def _row(position: int, label: str) -> str:
    episode_id = _episode_id(position)
    return f"""<div class="series-eplist-item" data-e2e="eli">
      <a class="series-eplist-item-link" href="/episodes/{episode_id}">
        <h2 class="series-eplist-item-h">
          <span class="series-eplist-item-h-text" data-e2e="eliTitle">{_title(position)}</span>
        </h2>
        <span class="series-eplist-item-access-text" data-e2e="eliFreeBadge">{label}</span>
      </a>
    </div>"""


def _series_auth_header(state: str) -> str:
    if state == "authenticated":
        login_anchor = ""
        extra_icon = ""
        menu = '''<a class="h-main-nav-link mode-user" data-e2e="hUserMenu" href="#account">
          <svg data-e2e="hUserIcon"></svg></a>
          <div class="h-usermenu"><ul><li><button data-e2e="signoutBtn">Sign out</button></li></ul></div>'''
    elif state == "delayed":
        return '''<header id="xHeader" class="h"><nav></nav></header>
          <script>
            setTimeout(() => {
              const header = document.querySelector('#xHeader.h');
              if (header) header.innerHTML = '<nav><a class="h-main-nav-link mode-user" data-e2e="hUserMenu" href="#account"><svg data-e2e="hUserIcon"></svg></a><div class="h-usermenu"><ul><li><button data-e2e="signoutBtn">Sign out</button></li></ul></div></nav>';
            }, 220);
          </script>'''
    elif state == "ambiguous":
        login_anchor = '<a href="/login">Login</a>'
        extra_icon = '<svg data-e2e="hUserIcon"></svg>'
        menu = '''<a class="h-main-nav-link mode-user" data-e2e="hUserMenu" href="#account">
          <svg data-e2e="hUserIcon"></svg></a>
          <div class="h-usermenu"><ul><li><button data-e2e="signoutBtn">Sign out</button></li></ul></div>'''
    else:
        login_anchor = '<a href="/login">Login</a>'
        extra_icon = ""
        menu = ""
    return f'''<header id="xHeader" class="h"><nav class="h-main-nav">
      {menu}{extra_icon}{login_anchor}
    </nav></header>'''


def _page_html(
    *,
    page_number: int | None,
    series_route: bool = False,
    drift_last_range: bool = False,
    first_badge: str = "無料",
    foreign_work: bool = False,
    duplicate_boundary_row: bool = False,
    omit_last_row: bool = False,
    target_badge: str | None = None,
    series_auth_state: str | None = None,
    work_id_override: str | None = None,
    history_conflict: bool = False,
    unknown_root: bool = False,
    nested_user_root: bool = False,
    duplicate_public_root: bool = False,
    wrong_outer: bool = False,
) -> str:
    final_end = 33 if drift_last_range else TOTAL
    ranges = [(1, 30), (31, final_end)]
    range_links = [
        (
            f'<a class="series-sort-link{" mode-current" if page_number is None else ""}" '
            f'href="/episodes/{SEED_ID}/old">最新話から</a>'
        )
    ]
    for index, (start, end) in enumerate(ranges, start=1):
        label = f"{start}-{end}"
        path = f"/episodes/{SEED_ID}/{index}"
        is_current = page_number == index
        href = f"/episodes/{SEED_ID}" if is_current else path
        range_links.append(
            f'<a class="series-sort-link{" mode-current" if is_current else ""}" '
            f'href="{href}">{label}</a>'
        )
    range_links.append(
        f'<a class="series-sort-link" href="/episodes/{SEED_ID}/1">...</a>'
    )

    if page_number is None:
        positions = range(TOTAL - 9, TOTAL + 1)
    elif page_number == 1:
        positions = range(1, 31)
    else:
        positions = range(31, TOTAL + 1)
    if page_number == 2 and omit_last_row:
        positions = range(31, TOTAL)
    rows = []
    for position in positions:
        row_position = 30 if page_number == 2 and duplicate_boundary_row and position == 31 else position
        if position == 1:
            label = first_badge
        elif position == TARGET_POSITION and target_badge is not None:
            label = target_badge
        elif position <= 3:
            label = "無料"
        else:
            label = "今なら無料"
        rows.append(_row(row_position, label))
    work_id = work_id_override or (
        f"{901:013x}" if foreign_work and page_number == 2 else WORK_ID
    )
    header = (
        _series_auth_header(series_auth_state)
        if series_auth_state is not None
        else f'<header id="xHeader"><a class="ep-h-main-h-series" href="/series/{work_id}">Fixture Work</a></header>'
    )
    history_rows = list(rows)
    if history_conflict and page_number == 1 and history_rows:
        history_rows[0] = _row(1, NOW_FREE_LABEL)
    user_markup = (
        '<div class="series-eplist mode-loading mode-user" data-e2e="epListUser"></div>'
        if series_route
        else '<div class="series-eplist mode-user" data-e2e="epListUser">'
        '<div class="series-eplist-default has-store-item mode-last">'
        + "".join(history_rows)
        + "</div></div>"
    )
    if nested_user_root:
        user_markup = (
            '<div class="series-eplist-extra">'
            '<div class="series-eplist mode-user" data-e2e="epListUser">'
            + "".join(history_rows)
            + "</div></div>"
        )
    public_markup = (
        '<div class="series-eplist" data-e2e="epList">'
        '<div class="series-eplist-default has-store-item mode-last">'
        + "".join(rows)
        + "</div></div>"
    )
    if duplicate_public_root:
        public_markup += public_markup
    if unknown_root:
        user_markup += '<div class="series-eplist" data-e2e="unknownList"></div>'
    if series_route and not wrong_outer:
        route_open = (
            '<div class="series mode-series-top series-safe-filter-target" data-e2e="pageSeries">'
        )
        route_close = "</div>"
    elif series_route or not wrong_outer:
        route_open = (
            '<div class="ep-main series-safe-filter-target" data-e2e="pageEpisode">'
            '<div class="series mode-ep">'
        )
        route_close = "</div></div>"
    else:
        route_open = (
            '<div class="series mode-series-top series-safe-filter-target" data-e2e="pageSeries">'
        )
        route_close = "</div>"
    return f"""<!doctype html><html><head><title>Fixture Work</title></head>
      <body><div class="base">
        {header}
          {route_open}
            <div class="series-eplist-wrap">
              <nav>{''.join(range_links)}</nav>
              <div class="series-eplist-main">
                {public_markup}{user_markup}
              </div>
            </div>
          {route_close}
      </div></body></html>"""


def _target(
    *,
    key: str = "hanayume-fixture",
    discovery_scope: DiscoveryScope | None = None,
) -> WatchlistTarget:
    return WatchlistTarget(
        key=key,
        work_key="hanayume-fixture-work",
        site="hanayume",
        url=f"{BASE}/episodes/{SEED_ID}",
        label="Fixture Work",
        discovery_scope=discovery_scope,
    )


def _registry() -> DiscoveryAdapterRegistry:
    registry = DiscoveryAdapterRegistry()
    registry.register("hanayume", HanayumeDiscoveryAdapter)
    return registry


async def _install_pages(
    browser_page,
    *,
    drift_last_range: bool = False,
    base_status: int = 200,
    first_badge: str = "無料",
    base_headers: dict[str, str] | None = None,
    foreign_work: bool = False,
    duplicate_boundary_row: bool = False,
    omit_last_row: bool = False,
    target_badge: str | None = None,
    series_auth_state: str = "logged-out",
    history_conflict: bool = False,
    unknown_root: bool = False,
    nested_user_root: bool = False,
    duplicate_public_root: bool = False,
    wrong_series_outer: bool = False,
    wrong_episode_outer: bool = False,
    return_route_drift: bool = False,
    return_work_drift: bool = False,
    return_range_drift: bool = False,
) -> list[str]:
    requested_paths: list[str] = []
    seed_requests = 0

    async def fulfill(route) -> None:
        nonlocal seed_requests
        parsed = urlsplit(route.request.url)
        requested_paths.append(parsed.path)
        if parsed.path == f"/series/{WORK_ID}":
            await route.fulfill(
                status=200,
                body=_page_html(
                    page_number=None,
                    series_route=True,
                    target_badge=target_badge,
                    series_auth_state=series_auth_state,
                    wrong_outer=wrong_series_outer,
                ),
                content_type="text/html; charset=utf-8",
            )
            return
        if parsed.path == f"/episodes/{SEED_ID}" and base_status != 200:
            await route.fulfill(status=base_status, body="", headers=base_headers or {})
            return
        if parsed.path == f"/episodes/{SEED_ID}":
            seed_requests += 1
            if return_route_drift and seed_requests > 1:
                await route.fulfill(
                    status=302,
                    headers={"location": f"/episodes/{_episode_id(5)}"},
                )
                return
            page_number = None
        elif parsed.path == f"/episodes/{SEED_ID}/1":
            page_number = 1
        elif parsed.path == f"/episodes/{SEED_ID}/2":
            page_number = 2
        else:
            await route.fulfill(status=404, body="")
            return
        await route.fulfill(
            status=200,
            body=_page_html(
                page_number=page_number,
                drift_last_range=(
                    drift_last_range
                    or (
                        return_range_drift
                        and seed_requests > 1
                        and parsed.path == f"/episodes/{SEED_ID}"
                    )
                ),
                first_badge=first_badge,
                foreign_work=foreign_work,
                duplicate_boundary_row=duplicate_boundary_row,
                omit_last_row=omit_last_row,
                target_badge=target_badge,
                history_conflict=history_conflict,
                unknown_root=unknown_root,
                nested_user_root=nested_user_root,
                duplicate_public_root=duplicate_public_root,
                wrong_outer=wrong_episode_outer,
                work_id_override=(
                    f"{901:013x}"
                    if return_work_drift and parsed.path == f"/episodes/{SEED_ID}"
                    and seed_requests > 1
                    else None
                ),
            ),
            content_type="text/html; charset=utf-8",
        )

    await browser_page.route("https://hanayume.com/**", fulfill)
    return requested_paths


async def test_hanayume_full_incremental_and_bounded_discovery(
    browser_page, tmp_path: Path
) -> None:
    requested = await _install_pages(browser_page)
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    service = DiscoveryService(catalog, _registry())

    full = await service.discover(browser_page, _target(), "full")

    assert full.complete is True
    assert full.observed_count == TOTAL
    sources = catalog.list_sources(site="hanayume")
    assert len(sources) == TOTAL
    assert {source.access_mode for source in sources} == {"free", "unknown"}
    assert sum(source.access_mode == "free" for source in sources) == 3
    assert {source.display_position for source in sources} == set(range(1, TOTAL + 1))
    assert {source.external_id.split(":", 1)[0] for source in sources} == {WORK_ID}
    seed_source = next(source for source in sources if source.external_id.endswith(f":{SEED_ID}"))
    assert seed_source.display_position == 1
    assert next(
        item for item in catalog.list_items() if item.id == seed_source.item_id
    ).status == "pending"
    catalog.mark_item_completed(seed_source.item_id)

    requested.clear()
    incremental = await service.discover(browser_page, _target(), "incremental")
    assert incremental.complete is None
    assert incremental.stopped_reason == "known_streak"
    assert incremental.observed_count == 5
    assert requested.count(f"/episodes/{SEED_ID}/1") == 1
    assert requested.count(f"/episodes/{SEED_ID}/2") == 1
    assert catalog.get_item(seed_source.item_id).status == "completed"

    bounded_catalog = CatalogService(tmp_path / "bounded.sqlite")
    bounded = await DiscoveryService(bounded_catalog, _registry()).discover(
        browser_page,
        _target(
            key="hanayume-bounded",
            discovery_scope=DiscoveryScope(
                from_url=f"{BASE}/episodes/{_episode_id(30)}",
                through_url=f"{BASE}/episodes/{_episode_id(28)}",
            ),
        ),
        "full",
    )
    bounded_sources = bounded_catalog.list_sources(site="hanayume")
    assert bounded.complete is True
    assert bounded.observed_count == 3
    assert [source.display_position for source in bounded_sources] == [30, 29, 28]


@pytest.mark.parametrize(
    ("auth_state", "expected_free_count"),
    [("logged-out", 2), ("ambiguous", 2), ("authenticated", TOTAL), ("delayed", TOTAL)],
)
async def test_hanayume_now_free_discovery_uses_only_fresh_series_auth_markers(
    browser_page, tmp_path: Path, auth_state: str, expected_free_count: int
) -> None:
    requested = await _install_pages(
        browser_page, target_badge=NOW_FREE_LABEL, series_auth_state=auth_state
    )
    catalog = CatalogService(tmp_path / "catalog.sqlite")

    result = await DiscoveryService(catalog, _registry()).discover(
        browser_page, _target(), "full"
    )

    target = catalog.find_source("hanayume", f"{WORK_ID}:{_episode_id(TARGET_POSITION)}")
    assert result.complete is True and result.observed_count == TOTAL
    assert target is not None
    assert target.access_mode == ("free" if auth_state in {"authenticated", "delayed"} else "unknown")
    assert sum(source.access_mode == "free" for source in catalog.list_sources(site="hanayume")) == expected_free_count
    assert requested[:3] == [f"/episodes/{SEED_ID}", f"/series/{WORK_ID}", f"/episodes/{SEED_ID}"]


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_discovery_and_batch_wait_for_delayed_now_free_auth_markers(
    browser_page, tmp_path: Path
) -> None:
    catalog, _source, candidate, plan, executor, _requested = await _batch_fixture(
        browser_page,
        tmp_path,
        target_badge=NOW_FREE_LABEL,
        discovery_target_badge=NOW_FREE_LABEL,
        discovery_auth_state="delayed",
    )

    result = await executor.execute_candidate(
        browser_page,
        candidate,
        output_root=tmp_path / "batch-output",
        library_dir=tmp_path / "library",
        max_pages=10,
        now=BATCH_NOW,
    )

    assert result.stop_reason == "end" and result.page_count == 4
    assert catalog.get_item(candidate.item_id).status == "completed"
    assert len(plan.candidates) == TOTAL


@pytest.mark.parametrize(
    "page_options",
    [
        pytest.param({"drift_last_range": True}, id="range-set-drift"),
        pytest.param({"foreign_work": True}, id="foreign-work-context"),
        pytest.param({"duplicate_boundary_row": True}, id="duplicate-episode-id"),
        pytest.param({"omit_last_row": True}, id="incomplete-declared-range"),
        pytest.param({"return_route_drift": True}, id="seed-return-route-drift"),
        pytest.param({"return_work_drift": True}, id="seed-return-work-drift"),
        pytest.param({"return_range_drift": True}, id="seed-return-range-drift"),
        pytest.param({"history_conflict": True}, id="conflicting-history-copy"),
        pytest.param({"unknown_root": True}, id="unknown-list-root"),
        pytest.param({"nested_user_root": True}, id="nested-history-root"),
        pytest.param({"duplicate_public_root": True}, id="duplicate-public-root"),
        pytest.param({"wrong_series_outer": True}, id="wrong-series-route-ancestry"),
        pytest.param({"wrong_episode_outer": True}, id="wrong-episode-route-ancestry"),
    ],
)
async def test_hanayume_incomplete_or_foreign_ranges_fail_before_catalog_sources_are_written(
    browser_page,
    tmp_path: Path,
    page_options: dict[str, object],
) -> None:
    await _install_pages(browser_page, **page_options)
    catalog = CatalogService(tmp_path / "catalog.sqlite")

    result = await DiscoveryService(catalog, _registry()).discover(
        browser_page, _target(), "full"
    )

    assert result.complete is False
    assert result.stopped_reason == "incomplete"
    assert result.observed_count == 0
    assert catalog.list_sources(site="hanayume") == []


async def test_hanayume_http_429_stops_discovery_without_retry_or_catalog_source(
    browser_page, tmp_path: Path
) -> None:
    requested = await _install_pages(browser_page, base_status=429)
    catalog = CatalogService(tmp_path / "catalog.sqlite")

    result = await DiscoveryService(catalog, _registry()).discover(
        browser_page, _target(), "full"
    )

    assert result.complete is False
    assert result.observed_count == 0
    assert catalog.list_sources(site="hanayume") == []
    assert requested == [f"/episodes/{SEED_ID}"]


async def test_hanayume_http_403_stops_discovery_without_retry_or_catalog_source(
    browser_page, tmp_path: Path
) -> None:
    requested = await _install_pages(browser_page, base_status=403)
    catalog = CatalogService(tmp_path / "catalog.sqlite")

    result = await DiscoveryService(catalog, _registry()).discover(
        browser_page, _target(), "full"
    )

    assert result.complete is False
    assert result.observed_count == 0
    assert catalog.list_sources(site="hanayume") == []
    assert requested == [f"/episodes/{SEED_ID}"]


async def test_hanayume_cf_challenge_header_stops_without_catalog_source(browser_page, tmp_path: Path) -> None:
    requested = await _install_pages(
        browser_page,
        base_status=503,
        base_headers={"cf-mitigated": "challenge"},
    )
    catalog = CatalogService(tmp_path / "catalog.sqlite")

    result = await DiscoveryService(catalog, _registry()).discover(
        browser_page, _target(), "full"
    )

    assert result.complete is False
    assert result.observed_count == 0
    assert catalog.list_sources(site="hanayume") == []
    assert requested == [f"/episodes/{SEED_ID}"]


async def test_hanayume_unknown_badge_and_completed_item_are_preserved(
    browser_page, tmp_path: Path
) -> None:
    await _install_pages(browser_page)
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    service = DiscoveryService(catalog, _registry())
    initial = await service.discover(browser_page, _target(), "full")
    assert initial.complete is True
    seed = next(
        source
        for source in catalog.list_sources(site="hanayume")
        if source.external_id.endswith(f":{SEED_ID}")
    )
    catalog.mark_item_completed(seed.item_id)

    await browser_page.unroute_all()
    await _install_pages(browser_page, first_badge="今なら無料")
    refreshed = await service.discover(browser_page, _target(), "full")

    refreshed_seed = catalog.find_source("hanayume", seed.external_id)
    assert refreshed.complete is True
    assert refreshed_seed is not None
    assert refreshed_seed.access_mode == "unknown"
    assert catalog.get_item(seed.item_id).status == "completed"


TARGET_POSITION = 2
TARGET_EPISODE_ID = _episode_id(TARGET_POSITION)
SERIES_URL = f"{BASE}/series/{WORK_ID}"
BATCH_NOW = datetime(2026, 10, 10, 12, 0, tzinfo=JST)


def _series_batch_html(
    *,
    page_number: int | None,
    target_badge: str = "\u7121\u6599",
    series_auth_state: str = "logged-out",
) -> str:
    ranges = ((1, 1, 30), (2, 31, TOTAL))
    links = []
    for number, start, end in ranges:
        selected = page_number == number
        href = SERIES_URL if selected else f"{SERIES_URL}/{number}"
        current_class = " mode-current" if selected else ""
        links.append(
            f'<a class="series-sort-link{current_class}" href="{href}">{start}-{end}</a>'
        )
    if page_number is None:
        positions = range(TOTAL - 9, TOTAL + 1)
    elif page_number == 1:
        positions = range(1, 31)
    else:
        positions = range(31, TOTAL + 1)
    rows = [
        _row(position, target_badge if position == TARGET_POSITION else (
            "無料" if position <= 3 else "今なら無料"
        ))
        for position in positions
    ]
    return f"""<!doctype html><html><body>
      {_series_auth_header(series_auth_state)}
      <div class="series mode-series-top series-safe-filter-target" data-e2e="pageSeries"><div class="series-eplist-wrap"><nav>{''.join(links)}</nav>
        <div class="series-eplist-main">
          <div class="series-eplist" data-e2e="epList">
            <div class="series-eplist-default has-store-item mode-last">{''.join(rows)}</div>
          </div>
          <div class="series-eplist mode-user" data-e2e="epListUser">
            <div class="series-eplist-default has-store-item mode-last">{''.join(rows)}</div>
          </div>
        </div>
      </div></div>
    </body></html>"""


def _batch_viewer_html(
    *,
    episode_id: str,
    work_id: str = WORK_ID,
    target_badge: str = "\u7121\u6599",
    mutation: str = "none",
    entry_gate: bool = False,
) -> str:
    target_row = _row(TARGET_POSITION, target_badge)
    if entry_gate:
        return f"""<!doctype html><html><body>
          <header id="xHeader"><a class="ep-h-main-h-series" href="{BASE}/series/{work_id}">work</a></header>
          <div class="ep-main series-safe-filter-target" data-e2e="pageEpisode">
            <div class="series mode-ep"><div class="series-eplist-wrap">
              <div class="series-eplist-main"><div class="series-eplist" data-e2e="epList">
                <div class="series-eplist-default has-store-item mode-last">{target_row}</div>
              </div></div>
            </div></div>
          </div>
          <div role="dialog" aria-label="login required"><button id="entry-gate">Continue</button></div>
          <script>window.entryGateClicks=0;document.querySelector('#entry-gate').addEventListener('click',()=>window.entryGateClicks++);</script>
        </body></html>"""
    return f"""<!doctype html><html><head><style>
      body {{ margin:0 }} #comici-viewer {{ position:relative;width:200px;height:100px }}
      #xCVPages {{ position:absolute;inset:0 }} .-cv-page {{ position:absolute;top:0;width:100px;height:100px }}
    </style></head><body>
      <header id="xHeader"><a class="ep-h-main-h-series" href="{BASE}/series/{work_id}">work</a></header>
      <div class="ep-main series-safe-filter-target" data-e2e="pageEpisode">
      <div class="series mode-ep"><div class="series-eplist-wrap">
        <div class="series-eplist-main">
          <div class="series-eplist" data-e2e="epList">
            <div class="series-eplist-default has-store-item mode-last">{target_row}</div>
          </div>
        </div>
      </div></div></div>
      </div>
      <div id="comici-viewer" class="-cv mode-spread">
        <div class="-cv-f-page-current"></div><div class="-cv-f-page-total">9</div>
        <input id="xCVSeekBar" type="range" min="1" max="9" step="2" value="9">
        <div id="xCVPages"></div>
      </div>
      <script>
        (() => {{
          const total=9, bodyTotal=4, mutation={json.dumps(mutation)};
          const root=document.querySelector('#comici-viewer');
          const pageRoot=document.querySelector('#xCVPages');
          const seek=document.querySelector('#xCVSeekBar');
          const counter=document.querySelector('.-cv-f-page-current');
          const wrappers=[];
          for(let i=0;i<=total;i++){{
            const node=document.createElement('div');node.className='-cv-page';
            node.style.left='-3000px';pageRoot.append(node);wrappers.push(node);
          }}
          const tails={{
            0:'-cv-page mode-empty mode-pr mode-top-pr',
            [total-4]:'-cv-page mode-ci',
            [total-3]:'-cv-page mode-empty mode-pr',
            [total-2]:'-cv-page mode-empty mode-pr',
            [total-1]:'-cv-page mode-good',
            [total]:'-cv-page mode-last'
          }};
          function render(current,terminal=false){{
            counter.textContent=String(current);
            seek.value=String(total-(current-1));
            const early=mutation==='early-terminal' && current>1;
            root.classList.toggle('mode-last-page',terminal||early);
            const visible=current===1?[0,1]:[current-1,current];
            for(let i=0;i<=total;i++){{
              const node=wrappers[i];node.replaceChildren();node.className=tails[i]||'-cv-page';
              node.style.left='-3000px';
            }}
            if(current===1)wrappers[0].style.left='0px';
            visible.forEach((index,side)=>{{
              const node=wrappers[index];node.style.left=`${{side*100}}px`;
              if(index<1||index>bodyTotal)return;
              if(mutation==='unknown-after-advance' && current>1 && index===current-1){{
                node.className='-cv-page mode-sponsored';return;
              }}
              const canvas=document.createElement('canvas');canvas.width=5;canvas.height=7;
              canvas.style.cssText='width:5px;height:7px';
              const context=canvas.getContext('2d');context.fillStyle=`rgb(${{index*30}},40,60)`;
              context.fillRect(0,0,5,7);
              const holder=document.createElement('div');holder.className='-cv-page-canvas';
              holder.append(canvas);node.append(holder);node.classList.add('mode-loaded','mode-rendered');
            }});
          }}
          seek.addEventListener('input',()=>render(total-Number(seek.value)+1));
          seek.addEventListener('change',()=>render(total-Number(seek.value)+1));
          seek.addEventListener('keydown',event=>{{
            if(event.key==='End'){{event.preventDefault();render(1)}}
            if(event.key==='Home'){{event.preventDefault();render(total,true)}}
          }});
          render(1);
        }})();
      </script>
    </body></html>"""


async def _install_batch_routes(
    browser_page,
    *,
    target_badge: str = "\u7121\u6599",
    work_id: str = WORK_ID,
    mutation: str = "none",
    series_auth_state: str = "logged-out",
    entry_gate: bool = False,
) -> list[str]:
    requested: list[str] = []
    target_path = f"/episodes/{TARGET_EPISODE_ID}"

    async def fulfill(route) -> None:
        path = urlsplit(route.request.url).path
        requested.append(path)
        if path == target_path:
            body = _batch_viewer_html(
                episode_id=TARGET_EPISODE_ID,
                work_id=work_id,
                target_badge=target_badge,
                mutation=mutation,
                entry_gate=entry_gate,
            )
        elif path == f"/series/{WORK_ID}":
            body = _series_batch_html(
                page_number=None,
                target_badge=target_badge,
                series_auth_state=series_auth_state,
            )
        elif path == f"/series/{WORK_ID}/1":
            body = _series_batch_html(
                page_number=1,
                target_badge=target_badge,
                series_auth_state=series_auth_state,
            )
        elif path == f"/series/{WORK_ID}/2":
            body = _series_batch_html(
                page_number=2,
                target_badge=target_badge,
                series_auth_state=series_auth_state,
            )
        else:
            await route.fulfill(status=404, body="")
            return
        await route.fulfill(
            status=200,
            body=body,
            content_type="text/html; charset=utf-8",
        )

    await browser_page.route("https://hanayume.com/**", fulfill)
    return requested


async def _batch_fixture(
    browser_page,
    tmp_path: Path,
    *,
    target_badge: str = "\u7121\u6599",
    discovery_target_badge: str | None = None,
    discovery_auth_state: str = "logged-out",
    runtime_auth_state: str | None = None,
    viewer_work_id: str = WORK_ID,
    mutation: str = "none",
    entry_gate: bool = False,
):
    await _install_pages(
        browser_page,
        target_badge=discovery_target_badge,
        series_auth_state=discovery_auth_state,
    )
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    discovery = await DiscoveryService(catalog, _registry()).discover(
        browser_page, _target(), "full"
    )
    assert discovery.complete is True and discovery.observed_count == TOTAL
    external_id = f"{WORK_ID}:{TARGET_EPISODE_ID}"
    source = catalog.find_source("hanayume", external_id)
    assert source is not None and source.access_mode == "free"

    policies = SitePolicyRegistry()
    policies.register("hanayume", HanayumeSitePolicy)
    adapters = AdapterRegistry()
    adapters.register("hanayume", HanayumeAdapter)
    plan = BatchPlanner(catalog, policies).plan(site="hanayume", now=BATCH_NOW)
    assert {candidate.access_mode for candidate in plan.candidates} == {"free"}
    candidate = next(item for item in plan.candidates if item.external_id == external_id)

    await browser_page.unroute_all()
    requested = await _install_batch_routes(
        browser_page,
        target_badge=target_badge,
        work_id=viewer_work_id,
        mutation=mutation,
        series_auth_state=runtime_auth_state or discovery_auth_state,
        entry_gate=entry_gate,
    )
    executor = BatchExecutor(
        catalog,
        policies,
        adapters,
        runtime_settings=SiteRuntimeSettings(page_turn_delay_ms=0),
    )
    return catalog, source, candidate, plan, executor, requested


@pytest.mark.parametrize(
    ("target_badge", "auth_state", "expected_candidates"),
    [("\u7121\u6599", "logged-out", 3), (NOW_FREE_LABEL, "authenticated", TOTAL)],
    ids=("free-logged-out", "now-free-logged-in"),
)
@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_discovery_to_batch_zip_completes_only_eligible_candidate(
    browser_page,
    tmp_path: Path,
    target_badge: str,
    auth_state: str,
    expected_candidates: int,
) -> None:
    catalog, source, candidate, plan, executor, requested = await _batch_fixture(
        browser_page,
        tmp_path,
        target_badge=target_badge,
        discovery_target_badge=target_badge,
        discovery_auth_state=auth_state,
    )
    manifest_snapshots: list[dict[str, object]] = []

    def package_with_manifest_copy(output_dir, metadata, **kwargs):
        manifest_snapshots.append(
            json.loads((Path(output_dir) / "manifest.json").read_text(encoding="utf-8"))
        )
        return package_crawl_output(output_dir, metadata, **kwargs)

    executor.package_function = package_with_manifest_copy
    result = await executor.execute_candidate(
        browser_page,
        candidate,
        output_root=tmp_path / "batch-output",
        library_dir=tmp_path / "library",
        max_pages=10,
        now=BATCH_NOW,
    )

    item = catalog.get_item(candidate.item_id)
    saved_source = catalog.get_source(source.id)
    run = catalog.get_crawl_run(result.crawl_run_id)
    artifacts = catalog.list_artifacts(item_id=item.id)
    assert result.stop_reason == "end" and result.page_count == 4
    assert item.status == "completed"
    assert run.status == "succeeded" and run.stop_reason == "end" and run.page_count == 4
    assert len(artifacts) == 1 and artifacts[0].format == "zip"
    assert saved_source.access_mode == "free"
    assert saved_source.quota_started_at is None and saved_source.access_granted_until is None
    assert candidate.access_strategy == "direct"
    assert candidate.consumes_quota is False and candidate.quota_resource is None
    assert catalog.get_quota_resource_state(
        catalog.get_work(item.work_id).id, site="hanayume", resource="work_ticket"
    ) is None
    assert len(plan.candidates) == expected_candidates
    assert {entry.access_mode for entry in plan.candidates} == {"free"}
    assert len(manifest_snapshots) == 1
    manifest = manifest_snapshots[0]
    manifest_pages = manifest["pages"]
    assert [entry["identity"]["page_id"] for entry in manifest_pages] == ["1", "2,3", "2,3", "4"]
    assert all(entry["file"].endswith(".png") for entry in manifest_pages)
    assert result.archive_path.name.startswith(candidate.artifact_prefix or "")
    with zipfile.ZipFile(result.archive_path) as archive:
        members = archive.namelist()
        assert len(members) == 4
        assert all(name.endswith(".png") for name in members)
    second_plan = BatchPlanner(catalog, executor.policies).plan(site="hanayume", now=BATCH_NOW)
    assert all(item.item_id != candidate.item_id for item in second_plan.candidates)
    assert any(
        skipped.item_id == candidate.item_id and skipped.reason == "completed"
        for skipped in second_plan.skipped
    )
    assert f"/episodes/{TARGET_EPISODE_ID}" in requested


@pytest.mark.parametrize(
    ("variant", "target_badge", "viewer_work_id", "max_pages"),
    [
        ("now-free", "今なら無料", WORK_ID, 10),
        ("wrong-work", "無料", f"{901:013x}", 10),
        ("unknown-slot", "無料", WORK_ID, 10),
        ("premature-end", "無料", WORK_ID, 10),
        ("max-pages", "無料", WORK_ID, 2),
    ],
)
@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_batch_failures_never_complete_or_create_artifacts(
    browser_page,
    tmp_path: Path,
    variant: str,
    target_badge: str,
    viewer_work_id: str,
    max_pages: int,
) -> None:
    mutation = {
        "unknown-slot": "unknown-after-advance",
        "premature-end": "early-terminal",
    }.get(variant, "none")
    catalog, _source, candidate, _plan, executor, requested = await _batch_fixture(
        browser_page,
        tmp_path,
        target_badge=target_badge,
        viewer_work_id=viewer_work_id,
        mutation=mutation,
    )

    with pytest.raises(BatchExecutionError):
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "batch-output",
            library_dir=tmp_path / "library",
            max_pages=max_pages,
            now=BATCH_NOW,
        )

    assert catalog.get_item(candidate.item_id).status == "pending"
    assert catalog.list_artifacts(item_id=candidate.item_id) == []
    assert list((tmp_path / "library").rglob("*.zip")) == []
    if variant == "now-free":
        runs = catalog.list_crawl_runs(item_id=candidate.item_id)
        assert len(runs) == 1 and runs[0].status == "failed"
        assert runs[0].page_count is None
        assert requested.count(f"/episodes/{TARGET_EPISODE_ID}") == 1


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_now_free_batch_stops_when_fresh_auth_marker_expires(
    browser_page, tmp_path: Path, monkeypatch
) -> None:
    # Keep the negative-auth deadline short while leaving room for the browser
    # evaluation itself to complete under the full affected test selection.
    monkeypatch.setattr(
        hanayume_discovery, "SERIES_AUTH_HYDRATION_TIMEOUT_SECONDS", 1.5
    )
    catalog, _source, candidate, _plan, executor, requested = await _batch_fixture(
        browser_page,
        tmp_path,
        target_badge=NOW_FREE_LABEL,
        discovery_target_badge=NOW_FREE_LABEL,
        discovery_auth_state="authenticated",
        runtime_auth_state="logged-out",
    )

    with pytest.raises(BatchExecutionError):
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "batch-output",
            library_dir=tmp_path / "library",
            max_pages=10,
            now=BATCH_NOW,
        )

    assert catalog.get_item(candidate.item_id).status == "pending"
    assert catalog.list_artifacts(item_id=candidate.item_id) == []
    assert requested.count(f"/episodes/{TARGET_EPISODE_ID}") == 1
    assert f"/series/{WORK_ID}/1" in requested


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_login_entry_gate_is_not_clicked_or_treated_as_free(
    browser_page, tmp_path: Path
) -> None:
    catalog, _source, candidate, _plan, executor, _requested = await _batch_fixture(
        browser_page, tmp_path, entry_gate=True
    )

    with pytest.raises(BatchExecutionError):
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "batch-output",
            library_dir=tmp_path / "library",
            max_pages=10,
            now=BATCH_NOW,
        )

    assert await browser_page.evaluate("window.entryGateClicks") == 0
    assert catalog.get_item(candidate.item_id).status == "pending"
    assert catalog.list_artifacts(item_id=candidate.item_id) == []


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_package_failure_keeps_item_pending_without_artifact(
    browser_page, tmp_path: Path
) -> None:
    catalog, _source, candidate, _plan, executor, _requested = await _batch_fixture(
        browser_page, tmp_path
    )

    def fail_package(*_args, **_kwargs):
        raise OSError("synthetic package failure")

    executor.package_function = fail_package
    with pytest.raises(CandidateExecutionError, match="synthetic package failure"):
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "batch-output",
            library_dir=tmp_path / "library",
            max_pages=10,
            now=BATCH_NOW,
        )

    assert catalog.get_item(candidate.item_id).status == "pending"
    assert catalog.list_artifacts(item_id=candidate.item_id) == []
    assert list((tmp_path / "library").rglob("*.zip")) == []
