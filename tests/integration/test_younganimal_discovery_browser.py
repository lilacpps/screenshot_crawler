from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from screenshot_crawler.catalog import CatalogService, ItemInput, SourceInput, WorkInput
from screenshot_crawler.core.access_guard import AccessGuard
from screenshot_crawler.discovery import DiscoveryAdapterRegistry, DiscoveryService
from screenshot_crawler.site_adapters.younganimal import YounganimalDiscoveryAdapter
from screenshot_crawler.site_adapters.younganimal import discovery as younganimal_discovery
from screenshot_crawler.watchlist import DiscoveryScope, WatchlistTarget

pytestmark = pytest.mark.asyncio(loop_scope="module")

BASE = "https://younganimal.com"
WORK_ID = "aee4fa742b0fe"
SEED_ID = "55889b8a851cb"
TOTAL = 32


def _episode_id(position: int) -> str:
    return {
        1: SEED_ID,
        2: "528a05e37879f",
        3: "483eff20ba210",
        4: "ed87698bc768d",
    }.get(position, f"{position:013x}")


def _row(
    position: int,
    *,
    label: str | None = None,
    title: str | None = None,
) -> str:
    default_label = {
        1: "\u7121\u6599",
        2: "\u4eca\u306a\u3089\u7121\u6599",
        3: "\u5f85\u3064\u3068\u7121\u6599",
    }.get(position, "\u7121\u6599")
    row_label = default_label if label is None else label
    row_title = f"PART.{position}" if title is None else title
    return f'''<div class="series-eplist-item">
      <a class="series-eplist-item-link" href="/episodes/{_episode_id(position)}">
        <span class="series-eplist-item-h-text">{row_title}</span>
        <span class="series-eplist-item-access-text">{row_label}</span>
      </a>
    </div>'''


def _range_links(*, selected_page: int | None) -> str:
    links = [
        f'<a class="series-sort-link" href="/series/{WORK_ID}/new">最新話から</a>'
    ]
    for page_number, start in enumerate(range(1, TOTAL + 1, 30), start=1):
        end = min(start + 29, TOTAL)
        href = (
            f"/series/{WORK_ID}"
            if selected_page == page_number and page_number > 1
            else f"/series/{WORK_ID}/{page_number}"
        )
        links.append(
            f'<a class="series-sort-link" href="{href}">{start}-{end}</a>'
        )
    return "".join(links)


def _listing_html(
    *,
    positions: list[int],
    selected_page: int | None,
    title: bool,
    user_rows: str = "",
    labels_by_position: dict[int, str] | None = None,
    native_access: list[dict[str, object]] | None = None,
    late_guard_trigger: bool = False,
) -> str:
    heading = '<h1>Fixture Work</h1>' if title else ""
    labels = labels_by_position or {}
    rows = "".join(
        _row(position, label=labels.get(position)) for position in positions
    )
    account_script = ""
    if user_rows:
        account_script = f'''<script>
          const root = document.querySelector('[data-e2e="epListUser"]');
          root.classList.add('mode-loading');
          setTimeout(() => {{root.innerHTML = {json.dumps(user_rows)};
            root.classList.remove('mode-loading');}}, 50);
        </script>'''
    native_script = ""
    if native_access is not None:
        native_script = '''<script>
          fetch('/api/auth/session');
          fetch('/api/series/access?context=series');
        </script>'''
    late_guard_script = (
        "<script>fetch('/api/late-guard-trigger');</script>" if late_guard_trigger else ""
    )
    return f'''<!doctype html><html><head><meta charset="utf-8"></head><body>{heading}
      <div class="series-eplist-main">
        <div class="series-eplist" data-e2e="epList">{rows}</div>
        <div class="series-eplist mode-user" data-e2e="epListUser"></div>
        <div class="series-sort">{_range_links(selected_page=selected_page)}</div>
      </div>{account_script}{native_script}{late_guard_script}</body></html>'''


def _target(
    *,
    scope: DiscoveryScope | None = None,
    url: str | None = None,
) -> WatchlistTarget:
    return WatchlistTarget(
        key="younganimal-fixture",
        work_key=f"younganimal:{WORK_ID}",
        site="younganimal",
        url=url or f"{BASE}/series/{WORK_ID}",
        label="Fixture Work",
        discovery_scope=scope,
    )


def _registry() -> DiscoveryAdapterRegistry:
    registry = DiscoveryAdapterRegistry()
    registry.register("younganimal", YounganimalDiscoveryAdapter)
    return registry


async def _install_pages(
    browser_page,
    *,
    omit_last: bool = False,
    history_conflict: str | None = None,
    rental_label: str | None = None,
    labels_by_position: dict[int, str] | None = None,
    native_access: list[dict[str, object]] | None = None,
    native_auth_user: int | None = 42,
    late_guard_response_gate: asyncio.Event | None = None,
) -> list[str]:
    requested: list[str] = []
    root_requests = 0
    history_rows = (
        _row(1, label="待つと無料", title="PART.999")
        if history_conflict
        else ""
    )
    if rental_label is not None:
        history_rows = _row(2, label=rental_label)
    if history_conflict == "duplicate":
        history_rows = _row(1, label="レンタル中 閲覧期限 2日+23時間") * 2

    async def fulfill(route) -> None:
        nonlocal root_requests
        parsed = urlsplit(route.request.url)
        requested.append(parsed.path)
        if parsed.path == "/api/auth/session" and native_access is not None:
            await route.fulfill(
                status=200,
                body=json.dumps({"user": native_auth_user}),
                content_type="application/json",
            )
            return
        if parsed.path == "/api/series/access" and native_access is not None:
            await route.fulfill(
                status=200,
                body=json.dumps(
                    {
                        "seriesAccess": {
                            "seriesId": WORK_ID,
                            "episodeAccesses": native_access,
                        }
                    }
                ),
                content_type="application/json",
            )
            return
        if parsed.path == "/api/late-guard-trigger" and late_guard_response_gate is not None:
            await late_guard_response_gate.wait()
            await route.fulfill(status=429, body="", content_type="text/plain")
            return
        if parsed.path == f"/episodes/{SEED_ID}":
            body = f'''<!doctype html><html><body>
              <a class="ep-h-main-h-series" href="/series/{WORK_ID}">Fixture Work</a>
              <div class="series-eplist-main"></div>
            </body></html>'''
            await route.fulfill(status=200, body=body, content_type="text/html")
            return
        if parsed.path == f"/series/{WORK_ID}/1":
            await route.fulfill(
                status=200,
                body=_listing_html(
                    positions=list(range(1, 31)), selected_page=None, title=True,
                    user_rows=history_rows,
                    labels_by_position=labels_by_position,
                    native_access=native_access,
                ),
                content_type="text/html",
            )
            return
        if parsed.path == f"/series/{WORK_ID}":
            root_requests += 1
            positions = list(range(1, 6)) if root_requests == 1 else list(range(1, 31))
            await route.fulfill(
                status=200,
                body=_listing_html(
                    positions=positions, selected_page=None, title=True,
                    user_rows=history_rows,
                    labels_by_position=labels_by_position,
                    native_access=native_access,
                ),
                content_type="text/html",
            )
            return
        if parsed.path == f"/series/{WORK_ID}/2":
            positions = [31] if omit_last else [31, 32]
            await route.fulfill(
                status=200,
                body=_listing_html(
                    positions=positions, selected_page=2, title=True,
                    user_rows=history_rows,
                    labels_by_position=labels_by_position,
                    native_access=native_access,
                    late_guard_trigger=late_guard_response_gate is not None,
                ),
                content_type="text/html",
            )
            return
        await route.fulfill(status=404, body="")

    await browser_page.route("https://younganimal.com/**", fulfill)
    return requested


async def test_younganimal_full_incremental_and_bounded_discovery(
    browser_page, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    native_access = [
        {
            "episodeId": _episode_id(3),
            "accessType": "waitAndFree",
            "hasAccess": False,
        },
        {
            "episodeId": _episode_id(4),
            "accessType": "paidContent",
            "hasAccess": False,
        },
        {
            "episodeId": _episode_id(5),
            "accessType": "trial",
            "hasAccess": True,
        },
        {
            "episodeId": _episode_id(6),
            "accessType": "waitAndFree",
            "hasAccess": True,
            "timeRemainingInSeconds": 3600,
        },
    ]
    requested = await _install_pages(
        browser_page,
        native_access=native_access,
        labels_by_position={4: "購入", 5: "試読", 6: "作品チケット"},
    )
    pacing_navigation_counts: list[int] = []
    original_pacing = younganimal_discovery._pace_before_range_navigation

    async def record_pacing(page, guard) -> None:
        pacing_navigation_counts.append(
            sum(path.startswith(f"/series/{WORK_ID}") for path in requested)
        )
        await original_pacing(page, guard)

    monkeypatch.setattr(younganimal_discovery, "RANGE_PACING_MS", 0)
    monkeypatch.setattr(
        younganimal_discovery,
        "_pace_before_range_navigation",
        record_pacing,
    )
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    service = DiscoveryService(catalog, _registry())

    full = await service.discover(browser_page, _target(), "full")
    assert full.complete is True
    assert full.observed_count == TOTAL
    sources = catalog.list_sources(site="younganimal")
    assert len(sources) == TOTAL
    assert {source.external_id.split(":", 1)[0] for source in sources} == {WORK_ID}
    assert {source.display_position for source in sources} == set(range(1, TOTAL + 1))
    assert catalog.find_source("younganimal", f"{WORK_ID}:{SEED_ID}").display_position == 1
    assert catalog.find_source("younganimal", f"{WORK_ID}:{SEED_ID}").access_mode == "free"
    assert catalog.find_source("younganimal", f"{WORK_ID}:{_episode_id(2)}").access_mode == "unknown"
    assert catalog.find_source("younganimal", f"{WORK_ID}:{_episode_id(3)}").access_mode == "quota"
    assert catalog.find_source("younganimal", f"{WORK_ID}:{_episode_id(4)}").access_mode == "unknown"
    assert catalog.find_source("younganimal", f"{WORK_ID}:{_episode_id(5)}").access_mode == "unknown"
    manual_grant = catalog.find_source("younganimal", f"{WORK_ID}:{_episode_id(6)}")
    assert manual_grant.access_mode == "quota"
    assert manual_grant.access_granted_until is not None
    assert requested.count(f"/series/{WORK_ID}/1") == 1
    assert requested.count(f"/series/{WORK_ID}/2") == 1
    assert pacing_navigation_counts == [1, 2]
    assert catalog.find_source("younganimal", f"{WORK_ID}:{_episode_id(3)}").access_mode == "quota"

    bounded_catalog = CatalogService(tmp_path / "bounded.sqlite")
    requested.clear()
    pacing_navigation_counts.clear()
    bounded = await DiscoveryService(bounded_catalog, _registry()).discover(
        browser_page,
        _target(
            scope=DiscoveryScope(
                from_url=f"{BASE}/episodes/{_episode_id(30)}",
                through_url=f"{BASE}/episodes/{_episode_id(28)}",
            )
        ),
        "full",
    )
    assert bounded.complete is True
    assert bounded.observed_count == 3
    assert [source.display_position for source in bounded_catalog.list_sources(site="younganimal")] == [
        30,
        29,
        28,
    ]
    assert pacing_navigation_counts == [1, 2]
    assert catalog.find_source("younganimal", f"{WORK_ID}:{_episode_id(3)}").access_mode == "quota"

    requested.clear()
    pacing_navigation_counts.clear()
    incremental = await service.discover(browser_page, _target(), "incremental")
    assert incremental.complete is None
    assert incremental.stopped_reason == "exhausted"
    assert incremental.observed_count == TOTAL
    assert requested.count(f"/series/{WORK_ID}/1") == 1
    assert requested.count(f"/series/{WORK_ID}/2") == 1
    assert pacing_navigation_counts == [1, 2]


async def test_younganimal_native_ticket_access_requires_positive_authentication(
    browser_page, tmp_path: Path
) -> None:
    requested = await _install_pages(
        browser_page,
        native_access=[
            {
                "episodeId": _episode_id(3),
                "accessType": "waitAndFree",
                "hasAccess": False,
            }
        ],
        native_auth_user=None,
        labels_by_position={3: "待つと無料"},
    )
    service = DiscoveryService(CatalogService(tmp_path / "unauthenticated.sqlite"), _registry())

    result = await service.discover(browser_page, _target(), "full")

    assert result.complete is True
    assert "/api/auth/session" in requested
    assert service.catalog.find_source(
        "younganimal", f"{WORK_ID}:{_episode_id(3)}"
    ).access_mode == "unknown"


async def test_younganimal_rental_history_joins_public_identity_and_clears_stale_grant(
    browser_page, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from screenshot_crawler.batch.planner import BatchPlanner
    from screenshot_crawler.site_policies import SitePolicyRegistry, YounganimalSitePolicy

    monkeypatch.setattr(younganimal_discovery, "RANGE_PACING_MS", 0)
    catalog = CatalogService(tmp_path / "rental.sqlite")
    service = DiscoveryService(catalog, _registry())
    await _install_pages(browser_page, rental_label="レンタル中 閲覧期限 14日+23時間")
    result = await service.discover(browser_page, _target(), "full")
    assert result.complete is True
    assert len(catalog.list_sources(site="younganimal")) == TOTAL
    source = catalog.find_source("younganimal", f"{WORK_ID}:{_episode_id(2)}")
    assert source.access_mode == "paid"
    assert source.display_position == 2
    assert source.access_granted_until is not None
    policies = SitePolicyRegistry()
    policies.register("younganimal", YounganimalSitePolicy)
    plan = BatchPlanner(catalog, policies).plan(site="younganimal")
    candidate = next(row for row in plan.candidates if row.source_id == source.id)
    assert candidate.access_strategy == "direct"
    assert candidate.reason == "active_rental"
    assert not candidate.consumes_quota

    await browser_page.unroute("https://younganimal.com/**")
    await _install_pages(browser_page, rental_label="レンタル中")
    refreshed = await service.discover(browser_page, _target(), "incremental")
    assert refreshed.observed_count == TOTAL
    assert refreshed.complete is None
    assert refreshed.stopped_reason == "exhausted"
    source = catalog.get_source(source.id)
    assert source.access_mode == "unknown"
    assert source.access_granted_until is not None


async def test_younganimal_navigation_retry_budget_is_shared_across_work(
    browser_page, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _install_pages(browser_page)
    monkeypatch.setattr(younganimal_discovery, "RANGE_PACING_MS", 0)
    original_navigate = younganimal_discovery._navigate
    observed_budgets: list[tuple[str, int]] = []

    async def consume_two_retries_across_work(
        page, url: str, guard, *, retry_budget_remaining: int
    ) -> int:
        observed_budgets.append((urlsplit(url).path, retry_budget_remaining))
        retries_used = await original_navigate(
            page,
            url,
            guard,
            retry_budget_remaining=retry_budget_remaining,
        )
        simulated_retry_use = 1 if len(observed_budgets) <= 2 else 0
        assert retries_used == 0
        return simulated_retry_use

    monkeypatch.setattr(
        younganimal_discovery,
        "_navigate",
        consume_two_retries_across_work,
    )
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    result = await DiscoveryService(catalog, _registry()).discover(
        browser_page,
        _target(),
        "full",
    )

    assert result.complete is True
    assert observed_budgets == [
        (f"/series/{WORK_ID}", 2),
        (f"/series/{WORK_ID}/1", 1),
        (f"/series/{WORK_ID}/2", 0),
    ]
    assert len(catalog.list_sources(site="younganimal")) == TOTAL


async def test_younganimal_incomplete_range_yields_nothing_and_preserves_catalog(
    browser_page, tmp_path: Path
) -> None:
    await _install_pages(browser_page, omit_last=True)
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key=_target().work_key, title="Fixture Work"))
    item = catalog.create_item(ItemInput(kind="episode"), work_id=work.id)
    existing = catalog.create_source(
        SourceInput(
            site="younganimal",
            external_id=f"{WORK_ID}:fffffffffffff",
            discovery_key=_target().key,
            available=True,
        ),
        item_id=item.id,
    )
    unavailable_calls: list[dict[str, object]] = []
    original = catalog.mark_sources_unavailable_except

    def spy_mark_sources_unavailable_except(**kwargs: object) -> None:
        unavailable_calls.append(kwargs)
        original(**kwargs)

    catalog.mark_sources_unavailable_except = spy_mark_sources_unavailable_except  # type: ignore[method-assign]
    result = await DiscoveryService(catalog, _registry()).discover(browser_page, _target(), "full")

    assert result.complete is False
    assert result.observed_count == 0
    assert catalog.list_sources(site="younganimal") == [catalog.get_source(existing.id)]
    assert catalog.get_source(existing.id).available is True
    assert unavailable_calls == []


async def test_younganimal_late_429_during_native_drain_yields_nothing_and_cleans_up(
    browser_page, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    late_response_gate = asyncio.Event()
    native_body_gate = asyncio.Event()
    native_body_started = asyncio.Event()
    late_response_seen = asyncio.Event()
    native_access = [
        {
            "episodeId": _episode_id(3),
            "accessType": "waitAndFree",
            "hasAccess": False,
        }
    ]
    requested = await _install_pages(
        browser_page,
        native_access=native_access,
        late_guard_response_gate=late_response_gate,
    )
    response_callback = lambda response: (
        late_response_seen.set()
        if urlsplit(response.url).path == "/api/late-guard-trigger" and response.status == 429
        else None
    )
    browser_page.on("response", response_callback)

    observer_type = younganimal_discovery._YounganimalNativeAccessObserver
    original_capture = observer_type._capture
    original_finish = observer_type.finish
    original_attach = observer_type.attach
    observers = []
    guards = []

    async def delayed_capture(self, response, *, requested_at, path) -> None:
        if path == "/api/series/access" and not native_body_started.is_set():
            native_body_started.set()
            await native_body_gate.wait()
        await original_capture(self, response, requested_at=requested_at, path=path)

    async def finish_while_late_response_arrives(self):
        await asyncio.wait_for(native_body_started.wait(), timeout=2)
        drain = asyncio.create_task(original_finish(self))
        await asyncio.sleep(0)
        late_response_gate.set()
        await asyncio.wait_for(late_response_seen.wait(), timeout=2)
        native_body_gate.set()
        return await drain

    def track_observer(self, page) -> None:
        original_attach(self, page)
        observers.append(self)

    original_guard_factory = AccessGuard.from_profile

    def track_guard(cls, **kwargs):
        guard = original_guard_factory(**kwargs)
        guards.append(guard)
        return guard

    monkeypatch.setattr(observer_type, "_capture", delayed_capture)
    monkeypatch.setattr(observer_type, "finish", finish_while_late_response_arrives)
    monkeypatch.setattr(observer_type, "attach", track_observer)
    monkeypatch.setattr(AccessGuard, "from_profile", classmethod(track_guard))

    catalog = CatalogService(tmp_path / "catalog.sqlite")
    target = _target()
    work = catalog.create_work(WorkInput(work_key=target.work_key, title="Fixture Work"))
    item = catalog.create_item(ItemInput(kind="episode"), work_id=work.id)
    grant_until = datetime(2026, 10, 20, tzinfo=UTC)
    existing = catalog.create_source(
        SourceInput(
            site="younganimal",
            external_id=f"{WORK_ID}:{_episode_id(3)}",
            discovery_key=target.key,
            access_mode="quota",
            quota_started_at=datetime(2026, 10, 17, tzinfo=UTC),
            access_granted_until=grant_until,
            available=True,
        ),
        item_id=item.id,
    )
    source_before = catalog.get_source(existing.id)
    unavailable_calls: list[dict[str, object]] = []
    original_mark_unavailable = catalog.mark_sources_unavailable_except

    def spy_mark_sources_unavailable_except(**kwargs: object) -> None:
        unavailable_calls.append(kwargs)
        original_mark_unavailable(**kwargs)

    catalog.mark_sources_unavailable_except = spy_mark_sources_unavailable_except  # type: ignore[method-assign]
    try:
        result = await DiscoveryService(catalog, _registry()).discover(
            browser_page, target, "full"
        )
    finally:
        late_response_gate.set()
        native_body_gate.set()
        browser_page.remove_listener("response", response_callback)

    assert "/api/late-guard-trigger" in requested
    assert result.complete is False
    assert result.observed_count == 0
    assert catalog.get_source(existing.id) == source_before
    assert unavailable_calls == []
    assert observers and all(observer._page is None for observer in observers)
    assert guards and all(guard._page is None for guard in guards)


async def test_younganimal_episode_seed_is_rejected_before_any_navigation(
    browser_page, tmp_path: Path
) -> None:
    requested = await _install_pages(browser_page)
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    result = await DiscoveryService(catalog, _registry()).discover(
        browser_page,
        _target(url=f"{BASE}/episodes/{SEED_ID}"),
        "full",
    )

    assert result.complete is False
    assert result.observed_count == 0
    assert requested == []


@pytest.mark.parametrize("history_conflict", ["title", "duplicate"])
async def test_younganimal_conflicting_history_duplicate_fails_closed_and_preserves_catalog(
    browser_page, tmp_path: Path, history_conflict: str
) -> None:
    await _install_pages(browser_page, history_conflict=history_conflict)
    target = _target()
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key=target.work_key, title="Fixture Work"))
    item = catalog.create_item(ItemInput(kind="episode"), work_id=work.id)
    existing = catalog.create_source(
        SourceInput(
            site="younganimal",
            external_id=f"{WORK_ID}:fffffffffffff",
            discovery_key=target.key,
            available=True,
        ),
        item_id=item.id,
    )
    unavailable_calls: list[dict[str, object]] = []
    original = catalog.mark_sources_unavailable_except

    def spy_mark_sources_unavailable_except(**kwargs: object) -> None:
        unavailable_calls.append(kwargs)
        original(**kwargs)

    catalog.mark_sources_unavailable_except = spy_mark_sources_unavailable_except  # type: ignore[method-assign]
    result = await DiscoveryService(catalog, _registry()).discover(browser_page, target, "full")

    assert result.complete is False
    assert result.observed_count == 0
    assert catalog.list_sources(site="younganimal") == [catalog.get_source(existing.id)]
    assert catalog.get_source(existing.id).available is True
    assert unavailable_calls == []
