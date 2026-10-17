from __future__ import annotations

import asyncio
import json
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.async_api import ElementHandle
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from screenshot_crawler.batch import (
    BatchExecutionError,
    BatchExecutor,
    BatchInterruptedError,
    BatchPlanner,
    CandidateExecutionError,
)
from screenshot_crawler.catalog import CatalogService
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.core.errors import AccessResourceUnavailableError
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
    monkeypatch.setattr(hanayume_discovery, "NATIVE_ACCESS_OBSERVATION_TIMEOUT_SECONDS", 0.25)
    monkeypatch.setattr(hanayume_adapter, "TICKET_AUTH_READY_TIMEOUT_SECONDS", 0.45)
    monkeypatch.setattr(hanayume_adapter, "TICKET_RECOVERY_WINDOW_SECONDS", 2.25)
    monkeypatch.setattr(hanayume_adapter, "TICKET_POLL_INTERVAL_SECONDS", 0.01)
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


def _row(position: int, label: str, *, manual_rental: bool = False) -> str:
    episode_id = _episode_id(position)
    row_class = (
        "series-eplist-item mode-read mode-current mode-store-item-start"
        if manual_rental
        else "series-eplist-item"
    )
    rental_stat = (
        '<span data-e2e="eliRentStat">'
        '\u30ec\u30f3\u30bf\u30eb\u4e2d \u95b2\u89a7\u671f\u9650'
        '<br>2\u65e5+23\u6642\u9593</span>'
        if manual_rental
        else ""
    )
    return f"""<div class="{row_class}" data-e2e="eli">
      <a class="series-eplist-item-link" href="/episodes/{episode_id}">
        <h2 class="series-eplist-item-h">
          <span class="series-eplist-item-h-text" data-e2e="eliTitle">{_title(position)}</span>
        </h2>
        <span class="series-eplist-item-access-text" data-e2e="eliFreeBadge">{label}</span>
        {rental_stat}
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
    all_badge: str | None = None,
    manual_rental_ids: set[str] | None = None,
    manual_history_label_diff: bool = False,
    series_auth_state: str | None = None,
    work_id_override: str | None = None,
    history_conflict: bool = False,
    unknown_root: bool = False,
    nested_user_root: bool = False,
    duplicate_public_root: bool = False,
    wrong_outer: bool = False,
    delayed_history_ms: int | None = None,
    history_preview_ids: set[str] | None = None,
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
    row_details: list[tuple[int, str]] = []
    for position in positions:
        row_position = 30 if page_number == 2 and duplicate_boundary_row and position == 31 else position
        if all_badge is not None:
            label = all_badge
        elif position == 1:
            label = first_badge
        elif position == TARGET_POSITION and target_badge is not None:
            label = target_badge
        elif position <= 3:
            label = "無料"
        else:
            label = "今なら無料"
        rows.append(_row(row_position, label))
        row_details.append((row_position, label))
    work_id = work_id_override or (
        f"{901:013x}" if foreign_work and page_number == 2 else WORK_ID
    )
    header = (
        _series_auth_header(series_auth_state)
        if series_auth_state is not None
        else f'<header id="xHeader"><a class="ep-h-main-h-series" href="/series/{work_id}">Fixture Work</a></header>'
    )
    manual_rental_ids = manual_rental_ids or set()
    history_rows = [
        _row(
            position,
            (
                "\u30ec\u30f3\u30bf\u30eb\u4e2d"
                if manual_history_label_diff
                and _episode_id(position) in manual_rental_ids
                else label
            ),
            manual_rental=_episode_id(position) in manual_rental_ids,
        )
        for position, label in row_details
        if history_preview_ids is None or _episode_id(position) in history_preview_ids
    ]
    if history_conflict and page_number == 1 and history_rows:
        history_rows[0] = _row(1, NOW_FREE_LABEL)
    user_markup = (
        '<div class="series-eplist mode-loading mode-user" data-e2e="epListUser"></div>'
        if series_route
        else '<div class="series-eplist mode-user mode-has-eps" data-e2e="epListUser">'
        '<div class="series-eplist-default has-store-item mode-last">'
        + "".join(history_rows)
        + "</div></div>"
    )
    history_hydration_script = ""
    if delayed_history_ms is not None and not series_route:
        user_markup = (
            '<div class="series-eplist mode-loading mode-user" data-e2e="epListUser">'
            '<div class="series-eplist-default has-store-item mode-last"></div></div>'
        )
        history_hydration_script = f"""<script>
          setTimeout(() => {{
            const root=document.querySelector('[data-e2e="epListUser"]');
            if (!root) return;
            root.className='series-eplist mode-user mode-has-eps';
            root.querySelector('.series-eplist-default').innerHTML={json.dumps(''.join(history_rows))};
          }}, {delayed_history_ms});
        </script>"""
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
      </div><script>fetch('/api/series/access');</script>{history_hydration_script}</body></html>"""


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
    all_badge: str | None = None,
    manual_rental_ids: set[str] | None = None,
    manual_history_label_diff: bool = False,
    native_access_response: dict[str, object] | None = None,
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
    delayed_history_ms: int | None = None,
    history_preview_ids: set[str] | None = None,
) -> list[str]:
    requested_paths: list[str] = []
    seed_requests = 0

    async def fulfill(route) -> None:
        nonlocal seed_requests
        parsed = urlsplit(route.request.url)
        if parsed.path != "/api/series/access":
            requested_paths.append(parsed.path)
        if parsed.path == "/api/series/access":
            await route.fulfill(
                status=200,
                json=native_access_response
                or {"seriesAccess": {"seriesId": WORK_ID, "episodeAccesses": []}},
            )
            return
        if parsed.path == f"/series/{WORK_ID}":
            await route.fulfill(
                status=200,
                body=_page_html(
                    page_number=None,
                    series_route=True,
                    target_badge=target_badge,
                    all_badge=all_badge,
                    manual_rental_ids=manual_rental_ids,
                    manual_history_label_diff=manual_history_label_diff,
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
                all_badge=all_badge,
                manual_rental_ids=manual_rental_ids,
                manual_history_label_diff=manual_history_label_diff,
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
                delayed_history_ms=delayed_history_ms,
                history_preview_ids=history_preview_ids,
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
    assert incremental.stopped_reason == "exhausted"
    assert incremental.observed_count == TOTAL
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


@pytest.mark.parametrize("outside_preview", [False, True], ids=["in-preview", "outside-preview"])
@pytest.mark.parametrize("refresh_mode", ["full", "incremental"])
async def test_hanayume_manual_ticket_grants_refresh_in_full_and_incremental_discovery(
    browser_page, tmp_path: Path, refresh_mode: str, outside_preview: bool
) -> None:
    episode_id = _episode_id(TARGET_POSITION)
    native_payload: dict[str, object] = {
        "seriesAccess": {
            "seriesId": WORK_ID,
            "episodeAccesses": [
                {
                    "episodeId": episode_id,
                    "accessType": "waitAndFree",
                    "hasAccess": True,
                    "timeRemainingInSeconds": 172800,
                },
                {
                    "episodeId": _episode_id(3),
                    "accessType": "waitAndFree",
                    "hasAccess": False,
                    "timeRemainingInSeconds": 0,
                },
            ],
        }
    }
    await _install_pages(
        browser_page,
        all_badge="unknown",
        manual_rental_ids=None if outside_preview else {episode_id},
        native_access_response=native_payload,
        series_auth_state="authenticated",
        history_preview_ids=(
            {_episode_id(position) for position in range(TOTAL - 9, TOTAL + 1)}
            if outside_preview
            else None
        ),
    )
    catalog = CatalogService(
        tmp_path / f"manual-grant-{refresh_mode}-{outside_preview}.sqlite"
    )
    service = DiscoveryService(catalog, _registry())

    full_started = datetime.now(UTC)
    full = await service.discover(browser_page, _target(), "full")
    full_finished = datetime.now(UTC)
    source = catalog.find_source("hanayume", f"{WORK_ID}:{episode_id}")
    assert full.complete is True and full.observed_count == TOTAL
    assert source is not None and source.access_mode == "quota"
    first_expiry = datetime.fromisoformat(source.access_granted_until)
    assert full_started + timedelta(seconds=172799) <= first_expiry
    assert first_expiry <= full_finished + timedelta(seconds=172799)
    catalog.mark_item_completed(source.item_id)
    sibling = catalog.find_source("hanayume", f"{WORK_ID}:{_episode_id(3)}")
    unknown = catalog.find_source("hanayume", f"{WORK_ID}:{_episode_id(4)}")
    assert sibling is not None and sibling.access_mode == "quota"
    assert sibling.access_granted_until is None
    assert unknown is not None and unknown.access_mode == "unknown"

    native_row = native_payload["seriesAccess"]["episodeAccesses"][0]
    native_row["timeRemainingInSeconds"] = 3600
    update_started = datetime.now(UTC)
    updated = await service.discover(browser_page, _target(), refresh_mode)
    update_finished = datetime.now(UTC)
    source = catalog.find_source("hanayume", f"{WORK_ID}:{episode_id}")
    assert updated.observed_count == TOTAL
    assert updated.complete is (True if refresh_mode == "full" else None)
    assert updated.stopped_reason == "exhausted"
    assert source is not None and source.access_mode == "quota"
    updated_expiry = datetime.fromisoformat(source.access_granted_until)
    assert update_started + timedelta(seconds=3599) <= updated_expiry
    assert updated_expiry <= update_finished + timedelta(seconds=3599)
    assert updated_expiry < first_expiry

    native_row["timeRemainingInSeconds"] = "3600"
    incremental_malformed = await service.discover(browser_page, _target(), refresh_mode)
    preserved = catalog.find_source("hanayume", f"{WORK_ID}:{episode_id}")
    assert incremental_malformed.observed_count == TOTAL
    assert catalog.get_item(source.item_id).status == "completed"
    assert preserved is not None
    assert preserved.access_granted_until == source.access_granted_until

    native_row["hasAccess"] = False
    native_row["timeRemainingInSeconds"] = 0
    cleared_result = await service.discover(browser_page, _target(), refresh_mode)
    cleared = catalog.find_source("hanayume", f"{WORK_ID}:{episode_id}")
    assert cleared_result.observed_count == TOTAL
    assert cleared_result.complete is (True if refresh_mode == "full" else None)
    assert cleared is not None and cleared.access_granted_until is None
    assert catalog.get_item(cleared.item_id).status == "completed"


async def test_hanayume_present_account_preview_row_without_rental_does_not_mint_grant(
    browser_page, tmp_path: Path
) -> None:
    episode_id = _episode_id(TARGET_POSITION)
    await _install_pages(
        browser_page,
        all_badge="unknown",
        native_access_response={
            "seriesAccess": {
                "seriesId": WORK_ID,
                "episodeAccesses": [
                    {
                        "episodeId": episode_id,
                        "accessType": "waitAndFree",
                        "hasAccess": True,
                        "timeRemainingInSeconds": 172800,
                    }
                ],
            }
        },
        series_auth_state="authenticated",
    )
    catalog = CatalogService(tmp_path / "present-unrented-preview.sqlite")
    result = await DiscoveryService(catalog, _registry()).discover(
        browser_page, _target(), "full"
    )

    source = catalog.find_source("hanayume", f"{WORK_ID}:{episode_id}")
    assert result.complete is True and result.observed_count == TOTAL
    assert source is not None and source.access_mode == "quota"
    assert source.access_granted_until is None


@pytest.mark.parametrize("refresh_mode", ["full", "incremental"])
async def test_hanayume_delayed_account_history_still_refreshes_manual_ticket_grant(
    browser_page, tmp_path: Path, monkeypatch, refresh_mode: str
) -> None:
    episode_id = _episode_id(TARGET_POSITION)
    native_payload: dict[str, object] = {
        "seriesAccess": {
            "seriesId": WORK_ID,
            "episodeAccesses": [
                {
                    "episodeId": episode_id,
                    "accessType": "waitAndFree",
                    "hasAccess": True,
                    "timeRemainingInSeconds": 172800,
                }
            ],
        }
    }
    await _install_pages(
        browser_page,
        all_badge="unknown",
        manual_rental_ids={episode_id},
        native_access_response=native_payload,
        series_auth_state="authenticated",
        delayed_history_ms=1_500,
    )
    monkeypatch.setattr(
        hanayume_discovery, "SERIES_HISTORY_HYDRATION_TIMEOUT_SECONDS", 2.5
    )
    catalog = CatalogService(tmp_path / f"delayed-manual-grant-{refresh_mode}.sqlite")
    result = await DiscoveryService(catalog, _registry()).discover(
        browser_page, _target(), refresh_mode
    )

    source = catalog.find_source("hanayume", f"{WORK_ID}:{episode_id}")
    assert result.observed_count == TOTAL
    assert result.complete is (True if refresh_mode == "full" else None)
    assert source is not None and source.access_mode == "quota"
    assert source.access_granted_until is not None


@pytest.mark.parametrize("refresh_mode", ["full", "incremental"])
async def test_hanayume_active_manual_grant_allows_exact_history_label_difference(
    browser_page, tmp_path: Path, refresh_mode: str
) -> None:
    episode_id = _episode_id(TARGET_POSITION)
    native_payload: dict[str, object] = {
        "seriesAccess": {
            "seriesId": WORK_ID,
            "episodeAccesses": [
                {
                    "episodeId": episode_id,
                    "accessType": "waitAndFree",
                    "hasAccess": True,
                    "timeRemainingInSeconds": 172800,
                }
            ],
        }
    }
    await _install_pages(
        browser_page,
        all_badge="",
        manual_rental_ids={episode_id},
        manual_history_label_diff=True,
        native_access_response=native_payload,
        series_auth_state="authenticated",
    )
    catalog = CatalogService(tmp_path / "history-label-difference.sqlite")
    result = await DiscoveryService(catalog, _registry()).discover(
        browser_page, _target(), refresh_mode
    )

    source = catalog.find_source("hanayume", f"{WORK_ID}:{episode_id}")
    assert result.observed_count == TOTAL
    assert result.complete is (True if refresh_mode == "full" else None)
    assert source is not None and source.access_mode == "quota"
    assert source.access_granted_until is not None


@pytest.mark.parametrize("conflicting_duplicate", [False, True])
async def test_hanayume_duplicate_native_episode_rows_do_not_mint_or_clear_grants(
    browser_page, tmp_path: Path, conflicting_duplicate: bool
) -> None:
    episode_id = _episode_id(TARGET_POSITION)
    native_row: dict[str, object] = {
        "episodeId": episode_id,
        "accessType": "waitAndFree",
        "hasAccess": True,
        "timeRemainingInSeconds": 172800,
    }
    accesses = [native_row]
    native_payload: dict[str, object] = {
        "seriesAccess": {"seriesId": WORK_ID, "episodeAccesses": accesses}
    }
    await _install_pages(
        browser_page,
        all_badge="unknown",
        manual_rental_ids={episode_id},
        native_access_response=native_payload,
        series_auth_state="authenticated",
    )
    catalog = CatalogService(tmp_path / "duplicate-native.sqlite")
    service = DiscoveryService(catalog, _registry())
    initial = await service.discover(browser_page, _target(), "full")
    source = catalog.find_source("hanayume", f"{WORK_ID}:{episode_id}")
    assert initial.complete is True
    assert source is not None and source.access_granted_until is not None
    original_expiry = source.access_granted_until

    duplicate = dict(native_row)
    if conflicting_duplicate:
        duplicate["timeRemainingInSeconds"] = 3600
    accesses.extend([dict(native_row), duplicate])
    refreshed = await service.discover(browser_page, _target(), "incremental")

    preserved = catalog.find_source("hanayume", f"{WORK_ID}:{episode_id}")
    assert refreshed.observed_count == TOTAL
    assert refreshed.stopped_reason == "exhausted"
    assert preserved is not None
    assert preserved.access_granted_until == original_expiry


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
    ticket_entry: bool = False,
    ticket_variant: str = "normal",
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
    if ticket_entry:
        account_class = {
            "login": "series-eplist mode-user mode-no-user",
            "unknown-root": "series-eplist mode-user mode-unexpected",
            "delayed": "series-eplist mode-user mode-loading",
            "loading-timeout": "series-eplist mode-user mode-loading",
        }.get(ticket_variant, "series-eplist mode-user mode-has-eps")
        target_account_row = _ticket_account_row(episode_id)
        if ticket_variant == "already-granted":
            target_account_row = _ticket_account_row(episode_id).replace(
                'class="series-eplist-item mode-current mode-store-item-blank"',
                'class="series-eplist-item mode-read mode-current mode-store-item-start"',
            ).replace(
                '</span>\n      </a>',
                '</span><span data-e2e="eliRentStat">レンタル中 閲覧期限<br>2日+23時間</span>\n      </a>',
            )
        if ticket_variant == "wrong-row-episode":
            target_account_row = _ticket_account_row(_episode_id(3))
        if ticket_variant == "duplicate-account-row":
            target_account_row += _ticket_account_row(episode_id)
        account_rows = "" if ticket_variant in {"login", "unknown-root", "loading-timeout"} else target_account_row
        control_text = "購入して読む" if ticket_variant == "paid-button" else "待つと無料で読む"
        control_attrs = {
            "hidden-button": 'style="display:none"',
            "disabled-button": "disabled",
            "paid-button": 'data-price="1"',
        }.get(ticket_variant, "")
        button_markup = (
            ""
            if ticket_variant in {"missing-button", "delayed-direct-gate"}
            else (
                '<a href="/login">ログイン</a>'
                if ticket_variant == "charge-login"
                else f'<button data-e2e="wfRead" {control_attrs}>{control_text}</button>'
            )
        )
        duplicate_button = (
            f'<button data-e2e="wfRead">{control_text}</button>'
            if ticket_variant == "duplicate-button"
            else ""
        )
        login_link = '<a href="/login">Login</a>' if ticket_variant == "login-link" else ""
        overlay = '<div role="dialog" aria-label="unexpected">Wait</div>' if ticket_variant == "overlay" else ""
        delayed_script = ""
        if ticket_variant == "delayed":
            delayed_script = """setTimeout(() => {
              const root=document.querySelector('[data-e2e="epListUser"]');
              root.className='series-eplist mode-user mode-has-eps';
              root.querySelector('.series-eplist-default').innerHTML=window.ticketAccountRows;
            },120);"""
        if ticket_variant == "login":
            account_rows = ""
        if ticket_variant == "delayed-direct-gate":
            delayed_script = """window.showDelayedDirectGate=()=>{
              const action=document.querySelector(
                '.ep-main-content.mode-charge > .ep-charge > .ep-charge-act');
              if (!action) return;
              const button=document.createElement('button');
              button.dataset.e2e='wfRead';
              button.textContent='\u5f85\u3064\u3068\u7121\u6599\u3067\u8aad\u3080';
              action.append(button);
            };"""
        ticket_markup = f"""
          <div class="ep-main-content mode-charge"><div class="ep-charge">
            <div class="ep-charge-act">{button_markup}{duplicate_button}</div>
          </div></div>{login_link}{overlay}
          <script>
            window.ticketClicks=0;
            window.ticketAccountRows={json.dumps(target_account_row)};
            fetch('/api/series/access');
            document.querySelectorAll('button[data-e2e="wfRead"]').forEach(button =>
              button.addEventListener('click', () => {{
                window.ticketClicks++;
                if ({json.dumps(ticket_variant != 'unconfirmed')}) {{
                  const row=document.querySelector('[data-e2e="epListUser"] .series-eplist-item[data-e2e="eli"]');
                  if (row) {{
                    row.className='series-eplist-item mode-read mode-current mode-store-item-start';
                    const link=row.querySelector('a.series-eplist-item-link');
                    link.insertAdjacentHTML('beforeend','<span data-e2e="eliRentStat">レンタル中 閲覧期限<br>2日+23時間</span>');
                  }}
                }}
                if ({json.dumps(ticket_variant == 'route-drift')}) {{
                  history.pushState({{}}, '', '/episodes/0000000000001');
                }}
                if ({json.dumps(ticket_variant == 'work-drift')}) {{
                  document.querySelector('#xHeader a.ep-h-main-h-series').href=
                    '{BASE}/series/0000000000001';
                }}
                fetch('/api/series/access?after=1');
              }}));
            {delayed_script}
          </script>"""
        header_markup = (
            f'<header id="xHeader" class="ep-h"><a class="ep-h-main-h-series" '
            f'href="{BASE}/series/{work_id}">work</a></header>'
        )
        episode_markup = f"""
          <div class="ep-main series-safe-filter-target" data-e2e="pageEpisode">
            <div class="series mode-ep"><div class="series-eplist-wrap">
              <div class="series-eplist-main">
                <div class="series-eplist" data-e2e="epList"><div class="series-eplist-default has-store-item mode-last">{target_row}</div></div>
                <div class="{account_class}" data-e2e="epListUser"><div class="series-eplist-default has-store-item mode-last">{account_rows}</div></div>
              </div>
            </div></div>
          </div>"""
    else:
        header_markup = (
            f'<header id="xHeader"><a class="ep-h-main-h-series" '
            f'href="{BASE}/series/{work_id}">work</a></header>'
        )
        episode_markup = f"""
          <div class="ep-main series-safe-filter-target" data-e2e="pageEpisode">
          <div class="series mode-ep"><div class="series-eplist-wrap">
            <div class="series-eplist-main">
              <div class="series-eplist" data-e2e="epList">
                <div class="series-eplist-default has-store-item mode-last">{target_row}</div>
              </div>
            </div>
          </div></div></div>
          </div>"""
        ticket_markup = ""
    return f"""<!doctype html><html><head><style>
      body {{ margin:0 }} #comici-viewer {{ position:relative;width:200px;height:100px }}
      #xCVPages {{ position:absolute;inset:0 }} .-cv-page {{ position:absolute;top:0;width:100px;height:100px }}
    </style></head><body>
      {header_markup}{episode_markup}{ticket_markup}
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


def _ticket_account_row(episode_id: str) -> str:
    return f'''<div class="series-eplist-item mode-current mode-store-item-blank" data-e2e="eli">
      <a class="series-eplist-item-link" href="/episodes/{episode_id}">
        <span data-e2e="eliTitle">Episode</span>
        <span data-e2e="eliWfIcon"></span><span data-e2e="eliIfIcon"></span>
      </a>
    </div>'''


async def _install_batch_routes(
    browser_page,
    *,
    target_badge: str = "\u7121\u6599",
    work_id: str = WORK_ID,
    mutation: str = "none",
    series_auth_state: str = "logged-out",
    entry_gate: bool = False,
    ticket_entry: bool = False,
    ticket_variant: str = "normal",
    native_work_id: str = WORK_ID,
) -> list[str]:
    requested: list[str] = []
    target_path = f"/episodes/{TARGET_EPISODE_ID}"

    async def fulfill(route) -> None:
        path = urlsplit(route.request.url).path
        requested.append(path)
        parsed = urlsplit(route.request.url)
        if path == "/api/series/access" and ticket_entry:
            pre_granted = ticket_variant == "already-granted"
            post_click = (
                ("after=1" in parsed.query and ticket_variant != "unconfirmed")
                or pre_granted
            )
            await route.fulfill(
                status=200,
                json={
                    "seriesAccess": {
                        "seriesId": native_work_id,
                        "episodeAccesses": [
                            {
                                "episodeId": TARGET_EPISODE_ID,
                                "accessType": (
                                    "premium" if ticket_variant == "paid-native" else "waitAndFree"
                                ),
                                "hasAccess": post_click,
                                "timeRemainingInSeconds": 259199 if post_click else 0,
                            }
                        ],
                    }
                },
            )
            return
        if path == target_path:
            body = _batch_viewer_html(
                episode_id=TARGET_EPISODE_ID,
                work_id=work_id,
                target_badge=target_badge,
                mutation=mutation,
                entry_gate=entry_gate,
                ticket_entry=ticket_entry,
                ticket_variant=ticket_variant,
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
    quota_candidate: bool = False,
    active_grant_candidate: bool = False,
    ticket_variant: str = "normal",
    native_work_id: str = WORK_ID,
    runtime_ticket_entry: bool = False,
):
    discovery_native = None
    discovery_badge = discovery_target_badge
    if quota_candidate or active_grant_candidate:
        discovery_badge = "unknown-ticket-state"
        discovery_native = {
            "seriesAccess": {
                "seriesId": WORK_ID,
                "episodeAccesses": [
                    {
                        "episodeId": TARGET_EPISODE_ID,
                        "accessType": "waitAndFree",
                        "hasAccess": active_grant_candidate,
                        "timeRemainingInSeconds": 172800 if active_grant_candidate else 0,
                    }
                ],
            }
        }
    await _install_pages(
        browser_page,
        target_badge=discovery_badge,
        native_access_response=discovery_native,
        manual_rental_ids={TARGET_EPISODE_ID} if active_grant_candidate else None,
        series_auth_state=("authenticated" if active_grant_candidate else discovery_auth_state),
    )
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    discovery = await DiscoveryService(catalog, _registry()).discover(
        browser_page, _target(), "full"
    )
    assert discovery.complete is True and discovery.observed_count == TOTAL
    external_id = f"{WORK_ID}:{TARGET_EPISODE_ID}"
    source = catalog.find_source("hanayume", external_id)
    expected_source_mode = "quota" if quota_candidate or active_grant_candidate else "free"
    assert source is not None and source.access_mode == expected_source_mode

    policies = SitePolicyRegistry()
    policies.register("hanayume", HanayumeSitePolicy)
    adapters = AdapterRegistry()
    adapters.register("hanayume", HanayumeAdapter)
    plan = BatchPlanner(catalog, policies).plan(site="hanayume", now=BATCH_NOW)
    candidate = next(item for item in plan.candidates if item.external_id == external_id)
    assert candidate.access_mode == expected_source_mode
    if active_grant_candidate:
        assert candidate.access_strategy == "direct" and not candidate.consumes_quota
    elif quota_candidate:
        assert candidate.access_strategy == "quota" and candidate.consumes_quota

    await browser_page.unroute_all()
    requested = await _install_batch_routes(
        browser_page,
        target_badge=target_badge,
        work_id=viewer_work_id,
        mutation=mutation,
        series_auth_state=runtime_auth_state or discovery_auth_state,
        entry_gate=entry_gate,
        ticket_entry=quota_candidate or runtime_ticket_entry,
        ticket_variant=ticket_variant,
        native_work_id=native_work_id,
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


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_quota_batch_uses_one_ticket_on_same_page_then_crawls_to_end(
    browser_page, tmp_path: Path
) -> None:
    catalog, source, candidate, _plan, executor, requested = await _batch_fixture(
        browser_page, tmp_path, quota_candidate=True
    )
    assert candidate.access_strategy == "quota"
    assert candidate.quota_resource == "work_ticket"
    assert candidate.quota_scope == "work" and candidate.quota_limit == 1

    result = await executor.execute_candidate(
        browser_page,
        candidate,
        output_root=tmp_path / "ticket-output",
        library_dir=tmp_path / "library",
        max_pages=10,
        now=BATCH_NOW,
    )

    saved_source = catalog.get_source(source.id)
    item = catalog.get_item(candidate.item_id)
    state = catalog.get_quota_resource_state(
        item.work_id, site="hanayume", resource="work_ticket"
    )
    assert result.stop_reason == "end" and result.page_count == 4
    assert item.status == "completed"
    assert saved_source.access_granted_until is not None
    assert state is not None and state.last_consumed_at is not None
    confirmation = datetime.fromisoformat(state.last_consumed_at)
    expiry = datetime.fromisoformat(saved_source.access_granted_until)
    assert timedelta(hours=71, minutes=59) < expiry - confirmation <= timedelta(hours=72)
    assert await browser_page.evaluate("() => window.ticketClicks") == 1
    assert requested.count(f"/episodes/{TARGET_EPISODE_ID}") == 1
    assert "/api/series/access" in requested
    assert all(not path.startswith("/series/") for path in requested)
    assert len(catalog.list_artifacts(item_id=item.id)) == 1


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_delayed_native_grant_body_survives_multiple_reconciliation_polls(
    browser_page, tmp_path: Path, monkeypatch
) -> None:
    catalog, source, candidate, _plan, executor, requested = await _batch_fixture(
        browser_page, tmp_path, quota_candidate=True
    )
    original_capture = hanayume_discovery._SeriesAccessObserver._capture
    original_wait = hanayume_discovery._SeriesAccessObserver.wait_for_pending
    body_started = asyncio.Event()
    body_finished = asyncio.Event()
    polls_during_body = 0

    async def delayed_capture(observer, response, *, requested_at):
        if "after=1" in urlsplit(response.url).query:
            body_started.set()
            await asyncio.sleep(0.35)
            body_finished.set()
        await original_capture(observer, response, requested_at=requested_at)

    async def tracking_wait(observer, timeout_seconds):
        nonlocal polls_during_body
        if body_started.is_set() and not body_finished.is_set():
            polls_during_body += 1
        return await original_wait(observer, timeout_seconds)

    monkeypatch.setattr(
        hanayume_discovery._SeriesAccessObserver, "_capture", delayed_capture
    )
    monkeypatch.setattr(
        hanayume_discovery._SeriesAccessObserver, "wait_for_pending", tracking_wait
    )
    monkeypatch.setattr(
        hanayume_discovery, "NATIVE_ACCESS_OBSERVATION_TIMEOUT_SECONDS", 1.0
    )
    monkeypatch.setattr(hanayume_adapter, "TICKET_RECOVERY_WINDOW_SECONDS", 1.25)

    result = await executor.execute_candidate(
        browser_page,
        candidate,
        output_root=tmp_path / "delayed-native-output",
        library_dir=tmp_path / "library",
        max_pages=10,
        now=BATCH_NOW,
    )

    state = catalog.get_quota_resource_state(
        catalog.get_item(candidate.item_id).work_id,
        site="hanayume",
        resource="work_ticket",
    )
    saved_source = catalog.get_source(source.id)
    assert result.stop_reason == "end" and result.page_count == 4
    assert body_started.is_set() and body_finished.is_set()
    assert polls_during_body >= 2
    assert await browser_page.evaluate("() => window.ticketClicks") == 1
    assert state is not None and state.last_consumed_at is not None
    assert saved_source.access_granted_until is not None
    confirmation = datetime.fromisoformat(state.last_consumed_at)
    expiry = datetime.fromisoformat(saved_source.access_granted_until)
    assert timedelta(hours=71, minutes=59) < expiry - confirmation <= timedelta(hours=72)
    assert requested.count(f"/episodes/{TARGET_EPISODE_ID}") == 1
    assert all(not path.startswith("/series/") for path in requested)


@pytest.mark.parametrize("mutation", ["replace", "add-paid-attribute"])
@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_ticket_control_change_after_trial_fails_without_click(
    browser_page, tmp_path: Path, monkeypatch, mutation: str
) -> None:
    _catalog, _source, candidate, _plan, executor, requested = await _batch_fixture(
        browser_page, tmp_path, quota_candidate=True
    )
    original_wait = HanayumeAdapter._wait_for_native_ticket_state
    calls = 0

    async def mutate_after_native_read(adapter, page, **kwargs):
        nonlocal calls
        native = await original_wait(adapter, page, **kwargs)
        calls += 1
        if calls == 2:
            await page.evaluate(
                """mutation => {
                  const button = document.querySelector('button[data-e2e="wfRead"]');
                  if (mutation === 'replace') button.replaceWith(button.cloneNode(true));
                  else button.setAttribute('data-price', '1');
                }""",
                mutation,
            )
        return native

    monkeypatch.setattr(
        HanayumeAdapter, "_wait_for_native_ticket_state", mutate_after_native_read
    )
    with pytest.raises(AccessResourceUnavailableError):
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "changed-control-output",
            library_dir=tmp_path / "library",
            max_pages=10,
            now=BATCH_NOW,
        )

    assert calls >= 2
    assert await browser_page.evaluate("() => window.ticketClicks") == 0
    assert requested.count(f"/episodes/{TARGET_EPISODE_ID}") == 1
    assert all(not path.startswith("/series/") for path in requested)
    assert not list((tmp_path / "changed-control-output").rglob("*.zip"))


@pytest.mark.parametrize("variant", ["route-drift", "work-drift"])
@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_ticket_post_click_identity_drift_is_fatal_without_navigation(
    browser_page, tmp_path: Path, variant: str
) -> None:
    catalog, source, candidate, _plan, executor, requested = await _batch_fixture(
        browser_page, tmp_path, quota_candidate=True, ticket_variant=variant
    )
    with pytest.raises(CandidateExecutionError) as raised:
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / f"{variant}-output",
            library_dir=tmp_path / "library",
            max_pages=10,
            now=BATCH_NOW,
        )

    assert raised.value.resource_consumed is None
    assert await browser_page.evaluate("() => window.ticketClicks") == 1
    assert requested.count(f"/episodes/{TARGET_EPISODE_ID}") == 1
    assert all(not path.startswith("/series/") for path in requested)
    assert catalog.get_source(source.id).access_granted_until is None
    assert catalog.get_item(candidate.item_id).status == "pending"
    assert catalog.list_artifacts(item_id=candidate.item_id) == []


@pytest.mark.parametrize(
    "variant", ["normal", "login", "charge-login", "paid-button"]
)
@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_configured_direct_batch_rejects_central_ticket_or_login_gate(
    browser_page, tmp_path: Path, variant: str
) -> None:
    catalog, source, candidate, _plan, executor, requested = await _batch_fixture(
        browser_page,
        tmp_path,
        runtime_ticket_entry=True,
        ticket_variant=variant,
        discovery_auth_state="logged-out",
    )
    assert candidate.access_strategy == "direct"

    with pytest.raises(AccessResourceUnavailableError):
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / f"direct-gate-{variant}",
            library_dir=tmp_path / "library",
            max_pages=10,
            now=BATCH_NOW,
        )

    assert await browser_page.evaluate("() => window.ticketClicks") == 0
    assert requested.count(f"/episodes/{TARGET_EPISODE_ID}") == 1
    assert all(not path.startswith("/series/") for path in requested)
    assert catalog.get_source(source.id).access_granted_until is None
    assert catalog.get_item(candidate.item_id).status == "pending"
    assert catalog.list_artifacts(item_id=candidate.item_id) == []


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_direct_batch_rechecks_a_delayed_central_ticket_gate(
    browser_page, tmp_path: Path, monkeypatch
) -> None:
    catalog, source, candidate, _plan, executor, requested = await _batch_fixture(
        browser_page,
        tmp_path,
        runtime_ticket_entry=True,
        ticket_variant="delayed-direct-gate",
        discovery_auth_state="logged-out",
    )
    original_check = HanayumeAdapter._reject_central_work_ticket_gate
    original_observe = HanayumeAdapter._observe
    visible_before_each_check: list[bool] = []
    hydrated_after_ready_viewer = False

    async def observe_then_hydrate(adapter, page, **kwargs):
        nonlocal hydrated_after_ready_viewer
        observation = await original_observe(adapter, page, **kwargs)
        if (
            not hydrated_after_ready_viewer
            and observation.current == 1
            and observation.active_slots
            and observation.active_slots == observation.ready_slots
        ):
            await page.evaluate("() => window.showDelayedDirectGate()")
            hydrated_after_ready_viewer = True
        return observation

    async def record_gate_check(adapter, page):
        visible = await page.evaluate(
            """() => [...document.querySelectorAll(
              '.ep-main-content.mode-charge > .ep-charge > .ep-charge-act > button[data-e2e="wfRead"]'
            )].some(node => { const rect=node.getBoundingClientRect(); return rect.width>0 && rect.height>0; })"""
        )
        visible_before_each_check.append(visible)
        await original_check(adapter, page)

    monkeypatch.setattr(HanayumeAdapter, "_observe", observe_then_hydrate)

    monkeypatch.setattr(
        HanayumeAdapter,
        "_reject_central_work_ticket_gate",
        record_gate_check,
    )
    with pytest.raises(AccessResourceUnavailableError):
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "direct-delayed-gate-output",
            library_dir=tmp_path / "library",
            max_pages=10,
            now=BATCH_NOW,
        )

    assert visible_before_each_check[:2] == [False, True]
    assert await browser_page.evaluate("() => window.ticketClicks") == 0
    assert requested.count(f"/episodes/{TARGET_EPISODE_ID}") == 1
    assert all(not path.startswith("/series/") for path in requested)
    assert catalog.get_source(source.id).access_granted_until is None
    assert catalog.get_item(candidate.item_id).status == "pending"
    assert catalog.list_artifacts(item_id=candidate.item_id) == []
    assert not list((tmp_path / "direct-delayed-gate-output").rglob("*.zip"))


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_grant_only_work_ticket_confirms_without_capture_or_completion(
    browser_page, tmp_path: Path
) -> None:
    catalog, source, candidate, _plan, executor, requested = await _batch_fixture(
        browser_page, tmp_path, quota_candidate=True, ticket_variant="delayed"
    )

    result = await executor.execute_grant_only_candidate(
        browser_page,
        candidate,
        output_root=tmp_path / "grant-only-output",
        max_pages=10,
        now=BATCH_NOW,
    )

    item = catalog.get_item(candidate.item_id)
    run = catalog.get_crawl_run(result.crawl_run_id)
    saved_source = catalog.get_source(source.id)
    assert result.resource_consumed is True and result.stop_reason == "entry_confirmed"
    assert item.status == "pending"
    assert run.status == "succeeded" and run.page_count == 0
    assert catalog.list_artifacts(item_id=item.id) == []
    assert saved_source.access_granted_until is not None
    assert not any(
        path.suffix.lower() in {".png", ".webp"}
        for path in (tmp_path / "grant-only-output").rglob("*")
        if path.is_file()
    )
    assert await browser_page.evaluate("() => window.ticketClicks") == 1
    assert requested.count(f"/episodes/{TARGET_EPISODE_ID}") == 1
    assert all(not path.startswith("/series/") for path in requested)
    assert not list((tmp_path / "grant-only-output").rglob("*.zip"))


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_discovery_active_manual_grant_uses_direct_batch_without_ticket(
    browser_page, tmp_path: Path
) -> None:
    catalog, source, candidate, _plan, executor, requested = await _batch_fixture(
        browser_page, tmp_path, active_grant_candidate=True
    )
    assert candidate.access_strategy == "direct" and not candidate.consumes_quota
    assert source.access_granted_until is not None

    result = await executor.execute_candidate(
        browser_page,
        candidate,
        output_root=tmp_path / "active-grant-output",
        library_dir=tmp_path / "library",
        max_pages=10,
        now=BATCH_NOW,
    )

    assert result.stop_reason == "end" and result.page_count == 4
    assert await browser_page.evaluate("() => window.ticketClicks || 0") == 0
    assert catalog.get_source(source.id).access_granted_until is not None
    assert catalog.get_quota_resource_state(
        catalog.get_item(candidate.item_id).work_id,
        site="hanayume",
        resource="work_ticket",
    ) is None
    assert all(not path.startswith("/series/") for path in requested)


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_ticket_consumption_survives_packaging_failure(
    browser_page, tmp_path: Path
) -> None:
    catalog, source, candidate, _plan, executor, requested = await _batch_fixture(
        browser_page, tmp_path, quota_candidate=True
    )

    def fail_package(*_args, **_kwargs):
        raise OSError("simulated packaging failure")

    executor.package_function = fail_package
    with pytest.raises(CandidateExecutionError) as raised:
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "package-failure-output",
            library_dir=tmp_path / "library",
            max_pages=10,
            now=BATCH_NOW,
        )

    assert raised.value.resource_consumed is True
    assert await browser_page.evaluate("() => window.ticketClicks") == 1
    assert catalog.get_source(source.id).access_granted_until is not None
    assert catalog.get_item(candidate.item_id).status == "pending"
    assert catalog.list_artifacts(item_id=candidate.item_id) == []
    assert all(not path.startswith("/series/") for path in requested)


@pytest.mark.parametrize(
    ("variant", "viewer_work_id", "native_work_id"),
    [
        ("login", WORK_ID, WORK_ID),
        ("login-link", WORK_ID, WORK_ID),
        ("overlay", WORK_ID, WORK_ID),
        ("unknown-root", WORK_ID, WORK_ID),
        ("loading-timeout", WORK_ID, WORK_ID),
        ("duplicate-account-row", WORK_ID, WORK_ID),
        ("wrong-row-episode", WORK_ID, WORK_ID),
        ("duplicate-button", WORK_ID, WORK_ID),
        ("missing-button", WORK_ID, WORK_ID),
        ("hidden-button", WORK_ID, WORK_ID),
        ("disabled-button", WORK_ID, WORK_ID),
        ("paid-button", WORK_ID, WORK_ID),
        ("paid-native", WORK_ID, WORK_ID),
        ("normal", f"{901:013x}", WORK_ID),
        ("normal", WORK_ID, f"{901:013x}"),
    ],
    ids=(
        "no-user", "login-link", "overlay", "unknown-root", "loading-timeout",
        "duplicate-account", "wrong-episode-row", "duplicate-control", "missing-control",
        "hidden-control", "disabled-control", "paid-control", "paid-native-state",
        "work-header-mismatch", "native-work-mismatch",
    ),
)
@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_ticket_preflight_fail_closed_without_click(
    browser_page, tmp_path: Path, variant: str, viewer_work_id: str, native_work_id: str
) -> None:
    _catalog, _source, candidate, _plan, executor, requested = await _batch_fixture(
        browser_page,
        tmp_path,
        quota_candidate=True,
        ticket_variant=variant,
        viewer_work_id=viewer_work_id,
        native_work_id=native_work_id,
    )

    with pytest.raises((AccessResourceUnavailableError, CandidateExecutionError)):
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "rejected-ticket-output",
            library_dir=tmp_path / "library",
            max_pages=10,
            now=BATCH_NOW,
        )

    assert await browser_page.evaluate("() => window.ticketClicks") == 0
    assert requested.count(f"/episodes/{TARGET_EPISODE_ID}") == 1
    assert all(not path.startswith("/series/") for path in requested)


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_unconfirmed_ticket_click_is_not_retried_or_recorded(
    browser_page, tmp_path: Path
) -> None:
    catalog, source, candidate, _plan, executor, requested = await _batch_fixture(
        browser_page, tmp_path, quota_candidate=True, ticket_variant="unconfirmed"
    )

    with pytest.raises(CandidateExecutionError):
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "unconfirmed-output",
            library_dir=tmp_path / "library",
            max_pages=10,
            now=BATCH_NOW,
        )

    assert await browser_page.evaluate("() => window.ticketClicks") == 1
    assert requested.count(f"/episodes/{TARGET_EPISODE_ID}") == 1
    assert all(not path.startswith("/series/") for path in requested)
    assert catalog.get_source(source.id).access_granted_until is None
    assert catalog.get_item(candidate.item_id).status == "pending"
    assert catalog.list_artifacts(item_id=candidate.item_id) == []


@pytest.mark.parametrize(
    ("phase", "error_kind", "expected_consumed"),
    [
        ("before-dispatch", "timeout", False),
        ("before-dispatch", "error", False),
        ("after-dispatch", "timeout", True),
        ("after-dispatch", "error", True),
        ("after-dispatch", "cancel", True),
    ],
)
@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_ticket_click_errors_are_reconciled_once(
    browser_page, tmp_path: Path, monkeypatch, phase: str, error_kind: str,
    expected_consumed: bool,
) -> None:
    catalog, source, candidate, _plan, executor, requested = await _batch_fixture(
        browser_page, tmp_path, quota_candidate=True
    )
    original_click = ElementHandle.click
    action_calls = 0

    def injected_error() -> BaseException:
        if error_kind == "timeout":
            return PlaywrightTimeoutError("synthetic click timeout")
        if error_kind == "error":
            return PlaywrightError("synthetic click error")
        return asyncio.CancelledError()

    async def fail_during_action(locator, *args, **kwargs):
        nonlocal action_calls
        if kwargs.get("no_wait_after") is not True:
            return await original_click(locator, *args, **kwargs)
        action_calls += 1
        if phase == "after-dispatch":
            await original_click(locator, *args, **kwargs)
        raise injected_error()

    monkeypatch.setattr(ElementHandle, "click", fail_during_action)
    error_type = BatchInterruptedError if error_kind == "cancel" else CandidateExecutionError
    with pytest.raises(error_type) as raised:
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / f"click-{phase}-{error_kind}-output",
            library_dir=tmp_path / "library",
            max_pages=10,
            now=BATCH_NOW,
        )

    click_count = await browser_page.evaluate("() => window.ticketClicks")
    assert action_calls == 1, (
        f"entry click interception was not reached: {raised.value!r}; "
        f"cause={raised.value.__cause__!r}"
    )
    assert click_count == (1 if phase == "after-dispatch" else 0)
    assert raised.value.resource_consumed is (True if expected_consumed else None)
    assert requested.count(f"/episodes/{TARGET_EPISODE_ID}") == 1
    assert all(not path.startswith("/series/") for path in requested)
    assert catalog.get_item(candidate.item_id).status == "pending"
    assert catalog.list_artifacts(item_id=candidate.item_id) == []
    assert not list((tmp_path / "library").rglob("*.zip"))
    if expected_consumed:
        assert catalog.get_source(source.id).access_granted_until is not None
        state = catalog.get_quota_resource_state(
            catalog.get_item(candidate.item_id).work_id,
            site="hanayume",
            resource="work_ticket",
        )
        assert state is not None and state.last_consumed_at is not None
    else:
        assert catalog.get_source(source.id).access_granted_until is None
        assert catalog.get_quota_resource_state(
            catalog.get_item(candidate.item_id).work_id,
            site="hanayume",
            resource="work_ticket",
        ) is None


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_ticket_consumption_survives_later_crawl_failure(
    browser_page, tmp_path: Path
) -> None:
    catalog, source, candidate, _plan, executor, requested = await _batch_fixture(
        browser_page,
        tmp_path,
        quota_candidate=True,
        mutation="unknown-after-advance",
    )

    with pytest.raises(CandidateExecutionError) as raised:
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "post-ticket-failure",
            library_dir=tmp_path / "library",
            max_pages=10,
            now=BATCH_NOW,
        )

    assert raised.value.resource_consumed is True
    assert await browser_page.evaluate("() => window.ticketClicks") == 1
    assert catalog.get_source(source.id).access_granted_until is not None
    assert catalog.get_item(candidate.item_id).status == "pending"
    assert catalog.list_artifacts(item_id=candidate.item_id) == []
    assert all(not path.startswith("/series/") for path in requested)


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_ticket_consumption_survives_runner_interruption(
    browser_page, tmp_path: Path, monkeypatch
) -> None:
    catalog, source, candidate, _plan, executor, requested = await _batch_fixture(
        browser_page, tmp_path, quota_candidate=True
    )
    original_detect_state = HanayumeAdapter.detect_state

    async def interrupt_after_ticket(adapter, page):
        if adapter.get_access_consumption().consumed:
            raise asyncio.CancelledError()
        return await original_detect_state(adapter, page)

    monkeypatch.setattr(HanayumeAdapter, "detect_state", interrupt_after_ticket)
    with pytest.raises(BatchInterruptedError) as raised:
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "interrupted-output",
            library_dir=tmp_path / "library",
            max_pages=10,
            now=BATCH_NOW,
        )

    assert raised.value.resource_consumed is True
    assert await browser_page.evaluate("() => window.ticketClicks") == 1
    assert catalog.get_source(source.id).access_granted_until is not None
    assert catalog.get_item(candidate.item_id).status == "pending"
    assert catalog.list_artifacts(item_id=candidate.item_id) == []
    assert all(not path.startswith("/series/") for path in requested)


@pytest.mark.parametrize(
    ("variant", "target_badge", "viewer_work_id", "max_pages"),
    [
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
    catalog, _source, candidate, _plan, executor, _requested = await _batch_fixture(
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


@pytest.mark.asyncio(loop_scope="module")
async def test_hanayume_catalog_eligible_source_does_not_recheck_series_auth(
    browser_page, tmp_path: Path
) -> None:
    catalog, source, candidate, _plan, executor, requested = await _batch_fixture(
        browser_page,
        tmp_path,
        target_badge=NOW_FREE_LABEL,
        discovery_target_badge=NOW_FREE_LABEL,
        discovery_auth_state="authenticated",
        runtime_auth_state="logged-out",
    )

    assert source.access_mode == "free"
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
    assert len(catalog.list_artifacts(item_id=candidate.item_id)) == 1
    assert requested.count(f"/episodes/{TARGET_EPISODE_ID}") == 1
    assert not any(path.startswith(f"/series/{WORK_ID}") for path in requested)


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
