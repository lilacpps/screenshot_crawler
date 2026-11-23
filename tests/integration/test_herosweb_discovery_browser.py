from __future__ import annotations

import asyncio
import json
from typing import ClassVar

import pytest
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from screenshot_crawler.catalog import CatalogService
from screenshot_crawler.discovery import (
    DiscoveryAdapterRegistry,
    DiscoveryIncompleteError,
    DiscoveryService,
)
from screenshot_crawler.site_adapters.herosweb import discovery as discovery_module
from screenshot_crawler.site_adapters.herosweb.discovery import (
    LATEST_LABEL,
    HeroswebDiscoveryAdapter,
    _snapshot_script,
)
from screenshot_crawler.watchlist.models import DiscoveryScope, WatchlistTarget

pytestmark = pytest.mark.asyncio(loop_scope="module")

WORK_ID = "aaaaaaaaaaaaa"
BASE = f"https://heros-web.com/series/{WORK_ID}"
_PRODUCTION_DOCUMENT_FETCH = discovery_module._fetch_main_document_response_without_redirect


@pytest.fixture(autouse=True)
def _use_mocked_document_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fallback_to_fixture(route):
        await route.fallback()

    monkeypatch.setattr(
        discovery_module,
        "_fetch_main_document_response_without_redirect",
        fallback_to_fixture,
    )


def _multi_range_html(
    *,
    work_id: str,
    page_number: int | None,
    fault: str | None = None,
) -> str:
    base = f"https://heros-web.com/series/{work_id}"
    ranges = ((1, 30), (31, 31))
    links = [
        f'<a class="series-sort-link mode-new" href="{base}/new">{LATEST_LABEL}</a>'
    ]
    for index, (start, end) in enumerate(ranges, start=1):
        selected = index == page_number
        href = base if selected else f"{base}/{index}"
        classes = "series-sort-link mode-current" if selected else "series-sort-link"
        if page_number is None:
            href = f"{base}/{index}"
        links.append(f'<a class="{classes}" href="{href}">{start}-{end}</a>')
    if page_number is None:
        rows_html = ""
    else:
        start, end = ranges[page_number - 1]
        rows = []
        for position in range(start, end + 1):
            episode_id = f"{position:013x}"
            if fault == "duplicate" and page_number == 2:
                episode_id = f"{1:013x}"
            if fault == "foreign_scope" and page_number == 2 and position == 31:
                episode_id = "bbbbbbbbbbbbb"
            rows.append(
                '<div class="series-eplist-item"><a class="series-eplist-item-link" '
                f'href="https://heros-web.com/episodes/{episode_id}">'
                '<div class="series-eplist-item-main">'
                f'<span class="series-eplist-item-h-text">Episode {position}</span>'
                '<div class="series-eplist-item-meta"><div class="series-eplist-item-meta-date">'
                '2026/05/18</div></div></div></a></div>'
            )
        rows_html = "".join(rows)
    canonical = base if page_number is None else f"{base}/{page_number}"
    extra_scope = (
        '<div class="series-eplist-item"><a class="series-eplist-item-link" '
        'href="https://heros-web.com/episodes/bbbbbbbbbbbbb">'
        '<span class="series-eplist-item-h-text">outside selected root</span>'
        '<div class="series-eplist-item-meta"><div class="series-eplist-item-meta-date">'
        '2026/05/18</div></div></a></div>'
        if fault == "foreign_scope" and page_number == 2
        else ""
    )
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f'<link rel="canonical" href="{canonical}"></head><body>'
        '<div class="series-h"><h1>Fixture Work</h1></div>'
        f'<div class="series-sort">{"".join(links)}</div>'
        '<div class="series-eplist-main"><div class="series-eplist">'
        f'<div class="series-eplist-default">{rows_html}</div>{extra_scope}'
        '</div></div><script>fetch("/api/auth/session").catch(() => {});</script>'
        '</body></html>'
    )


def _multi_range_target(*, scope: DiscoveryScope | None = None) -> WatchlistTarget:
    return WatchlistTarget(
        key="multi-range-fixture",
        work_key="multi-range-fixture-work",
        site="herosweb",
        url=BASE,
        label="Fixture Work",
        discovery_scope=scope,
    )


def _herosweb_registry() -> DiscoveryAdapterRegistry:
    registry = DiscoveryAdapterRegistry()
    registry.register("herosweb", HeroswebDiscoveryAdapter)
    return registry


def _page_html(*, base: bool, row_count: int, defer_rows: bool = False) -> str:
    latest = f'<a class="series-sort-link mode-new" href="{BASE}/new">最新話から</a>'
    selected_href = f"{BASE}/1" if base else BASE
    selected_class = "series-sort-link" if base else "series-sort-link mode-current"
    range_links = latest + (
        f'<a class="{selected_class}" href="{selected_href}">1-2</a>'
    )
    rows = []
    for index in range(row_count):
        episode_id = f"{index + 1:013x}"
        if index == 0:
            badge = ('<div class="series-eplist-item-access"><div>'
                     '<span class="series-eplist-item-access-text mode-free" data-e2e="eliFreeBadge">無料</span>'
                     '</div></div>')
        else:
            badge = (
                '<div class="series-eplist-item-access"><div><div class="series-eplist-item-access-paid">'
                '<span class="series-eplist-item-access-paid-item" data-e2e="eliPrice">'
                '<img alt="コイン" data-e2e="eliCoinIcon" data-nimg="1" src="/images/icons/coin.svg">90</span>'
                "</div></div></div>"
            )
        rows.append(
            f'<div class="series-eplist-item"><a class="series-eplist-item-link" '
            f'href="https://heros-web.com/episodes/{episode_id}">'
            f'<div class="series-eplist-item-main"><span class="series-eplist-item-h-text">Episode {index + 1}</span>'
            '<div class="series-eplist-item-meta"><div class="series-eplist-item-meta-date">2026/05/18</div>'
            '<div class="series-eplist-item-meta-fav"><span class="series-eplist-item-meta-count">828</span></div>'
            f"</div></div>{badge}</a></div>"
        )
    canonical = BASE if base else f"{BASE}/1"
    complete_rows = "".join(rows)
    listing_rows = "" if base or defer_rows else complete_rows
    deferred_hydration = (
        "<script>setTimeout(() => { document.querySelector('.series-eplist-default').innerHTML = "
        f"{json.dumps(complete_rows)}; }}, 100);</script>"
        if defer_rows
        else ""
    )
    mission_telemetry = (
        "<script>setTimeout(() => fetch('/api/missions', {method:'POST'}).catch(() => {}), 0);</script>"
        if base
        else ""
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f'<link rel="canonical" href="{canonical}"></head><body>'
        '<h1 class="h-main-logo"></h1><div class="series-h"><h1>Fixture Work</h1></div>'
        f'<div class="series-sort">{range_links}</div>'
        '<div class="series-eplist-main"><div class="series-eplist">'
        f'<div class="series-eplist-default">{listing_rows}</div></div></div>'
        f"{deferred_hydration}{mission_telemetry}"
        "</body></html>"
    )


def _authenticated_page_html(
    *, base: bool, delay_auth_header_ms: int = 0
) -> str:
    latest = f'<a class="series-sort-link mode-new" href="{BASE}/new">最新話から</a>'
    selected_href = f"{BASE}/1" if base else BASE
    selected_class = "series-sort-link" if base else "series-sort-link mode-current"
    links = latest + f'<a class="{selected_class}" href="{selected_href}">1-3</a>'
    now_free = (
        '<div class="series-eplist-item-access"><div><span '
        'class="series-eplist-item-access-text mode-free" data-e2e="eliMemFreeBadge">今なら無料</span></div></div>'
    )
    quota = (
        '<div class="series-eplist-item-access"><div>'
        '<svg class="series-eplist-item-access-icon" data-e2e="eliWfIcon" viewBox="0 0 24 24"><path></path></svg>'
        '<svg class="series-eplist-item-access-icon" data-e2e="eliIfIcon" viewBox="0 0 32 32"><path></path></svg>'
        '</div></div>'
    )
    paid = (
        '<div class="series-eplist-item-access"><div><div class="series-eplist-item-access-paid">'
        '<span class="series-eplist-item-access-paid-item" data-e2e="eliPrice">'
        '<img alt="コイン" data-e2e="eliCoinIcon" data-nimg="1" src="/images/icons/coin.svg">60</span>'
        '</div></div></div>'
    )
    badges = [now_free, quota, paid]
    rows = []
    for index, badge in enumerate(badges, start=1):
        episode_id = f"{index:013x}"
        rows.append(
            f'<div class="series-eplist-item"><a class="series-eplist-item-link" '
            f'href="https://heros-web.com/episodes/{episode_id}">'
            '<div class="series-eplist-item-main">'
            f'<span class="series-eplist-item-h-text">Episode {index}</span>'
            '<div class="series-eplist-item-meta"><div class="series-eplist-item-meta-date">2026/05/18</div>'
            '</div></div>' + badge + '</a></div>'
        )
    row_html = "".join(rows)
    canonical = BASE if base else f"{BASE}/1"
    listing = (
        '<div class="series-eplist mode-user mode-has-eps">'
        f'<div class="series-eplist-default mode-last">{row_html}</div></div>'
        '<div class="series-eplist" style="display:none">'
        f'<div class="series-eplist-default mode-last" style="width:0;height:0;overflow:hidden">'
        f'{row_html}</div></div>'
    )
    authenticated_header = (
        '<header><a class="h-main-nav-link mode-user"></a>'
        '<div class="h-usermenu-vnav-link"></div>'
        '<a href="/auth/signout">ログアウト</a></header>'
    )
    initial_header = (
        "<header></header>" if delay_auth_header_ms > 0 else authenticated_header
    )
    delayed_header = (
        "setTimeout(() => { document.querySelector('header').outerHTML = "
        f"{json.dumps(authenticated_header)}; }}, {delay_auth_header_ms});"
        if delay_auth_header_ms > 0
        else ""
    )
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f'<link rel="canonical" href="{canonical}"></head><body>'
        f'{initial_header}'
        '<div class="series-h"><h1>Fixture Work</h1></div>'
        f'<div class="series-sort">{links}</div><div class="series-eplist-main">{listing}</div>'
        '<script>fetch("/api/auth/session").catch(() => {}); '
        f'{delayed_header}'
        'fetch("/api/missions", {method:"POST"}).catch(() => {});</script>'
        '</body></html>'
    )


async def test_herosweb_discovery_buffers_rows_and_rejects_incomplete_before_yield(
    browser_page: Page, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = browser_page
    incomplete = {"enabled": False}
    paths: list[str] = []
    blocked_post_attempts: list[tuple[str, str]] = []
    post_reached_fixture: list[str] = []
    delays: list[int] = []
    preview_mutated = {"done": False}

    async def fulfill(route) -> None:
        from urllib.parse import urlsplit

        if route.request.method.upper() not in {"GET", "HEAD"}:
            post_reached_fixture.append(route.request.method.upper())
            await route.fulfill(status=200, body="unexpected state-changing request")
            return
        path = urlsplit(route.request.url).path
        if path == "/images/icons/coin.svg":
            await route.fulfill(
                status=200,
                headers={"content-type": "image/svg+xml"},
                body="<svg xmlns='http://www.w3.org/2000/svg'></svg>",
            )
            return
        paths.append(path)
        if path == "/api/auth/session":
            await route.fulfill(
                status=200,
                headers={"content-type": "application/json"},
                body='{"user":null}',
            )
            return
        if path == f"/series/{WORK_ID}":
            html = _page_html(base=True, row_count=0)
        elif path == f"/series/{WORK_ID}/1":
            html = _page_html(
                base=False,
                row_count=1 if incomplete["enabled"] else 2,
                defer_rows=not incomplete["enabled"],
            )
        else:
            await route.fulfill(status=404, body="unexpected path")
            return
        await route.fulfill(
            status=200,
            headers={"content-type": "text/html; charset=utf-8"},
            body=html,
        )

    async def record_delay(milliseconds: int) -> None:
        delays.append(milliseconds)

    original_evaluate = page.evaluate

    async def mutate_preview_after_observation(expression, *args):
        result = await original_evaluate(expression, *args)
        if not preview_mutated["done"] and page.url == BASE and isinstance(expression, str):
            await original_evaluate(
                """() => {
                  document.querySelector('.series-eplist-default').innerHTML =
                    '<div class="series-eplist-item">preview changed after header read</div>';
                }"""
            )
            preview_mutated["done"] = True
        return result

    def observe_post(request) -> None:
        from urllib.parse import urlsplit

        parsed = urlsplit(request.url)
        if parsed.hostname == "heros-web.com" and request.method.upper() not in {"GET", "HEAD"}:
            blocked_post_attempts.append((request.method.upper(), parsed.path))

    page.on("request", observe_post)
    await page.route("https://heros-web.com/**", fulfill)
    monkeypatch.setattr(page, "wait_for_timeout", record_delay)
    monkeypatch.setattr(page, "evaluate", mutate_preview_after_observation)
    target = WatchlistTarget(
        key="fixture",
        work_key="fixture",
        site="herosweb",
        url=BASE,
        label="Fixture Work",
    )
    adapter = HeroswebDiscoveryAdapter()
    try:
        records = [record async for record in adapter.iter_records(page, target, "full")]
        assert [record.source.external_id for record in records] == [
            f"{WORK_ID}:0000000000002",
            f"{WORK_ID}:0000000000001",
        ]
        assert [record.source.access_mode for record in records] == ["paid", "free"]
        assert [record.source.global_display_position for record in records] == [2, 1]
        assert adapter.complete_listing_inventory is not None
        assert preview_mutated["done"] is True
        assert delays.count(3_200) == 1
        assert paths[-2:] == [f"/series/{WORK_ID}", f"/series/{WORK_ID}/1"]
        assert blocked_post_attempts == [("POST", "/api/missions")]
        assert post_reached_fixture == []

        incomplete["enabled"] = True
        generated = adapter.iter_records(page, target, "full")
        with pytest.raises(DiscoveryIncompleteError, match="row count"):
            await anext(generated)
        assert adapter.complete_listing_inventory is None
    finally:
        page.remove_listener("request", observe_post)
        await page.unroute("https://heros-web.com/**", fulfill)


async def test_herosweb_stability_polling_uses_two_consecutive_settled_snapshots(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = browser_page
    paths: list[str] = []

    async def fulfill(route) -> None:
        from urllib.parse import urlsplit

        path = urlsplit(route.request.url).path
        paths.append(path)
        if path == "/api/auth/session":
            await route.fulfill(
                status=200,
                headers={"content-type": "application/json"},
                body='{"user":null}',
            )
        elif path == f"/series/{WORK_ID}":
            await route.fulfill(
                status=200,
                headers={"content-type": "text/html"},
                body=_page_html(base=True, row_count=0),
            )
        elif path == f"/series/{WORK_ID}/1":
            await route.fulfill(
                status=200,
                headers={"content-type": "text/html"},
                body=_page_html(base=False, row_count=2),
            )
        else:
            await route.fulfill(status=404, body="unexpected route")

    original_evaluate = page.evaluate
    range_snapshots = 0

    async def mutate_after_first_range_snapshot(expression, *args):
        nonlocal range_snapshots
        result = await original_evaluate(expression, *args)
        if page.url == f"{BASE}/1" and expression == _snapshot_script():
            range_snapshots += 1
            if range_snapshots == 1:
                await original_evaluate(
                    """() => setTimeout(() => {
                      const badge = document.querySelector('.series-eplist-item-access-text');
                      if (badge) badge.setAttribute('data-e2e', 'eliLateUnknownBadge');
                    }, 0)"""
                )
        return result

    await page.route("https://heros-web.com/**", fulfill)
    monkeypatch.setattr(page, "evaluate", mutate_after_first_range_snapshot)
    target = WatchlistTarget(
        key="settling-fixture",
        work_key="settling-fixture-work",
        site="herosweb",
        url=BASE,
        label="Fixture Work",
    )
    try:
        records = [
            record
            async for record in HeroswebDiscoveryAdapter().iter_records(
                page, target, "full"
            )
        ]
        access_by_episode = {
            record.source.external_id.rpartition(":")[2]: record.source.access_mode
            for record in records
        }
        assert access_by_episode[f"{1:013x}"] == "unknown"
        assert access_by_episode[f"{2:013x}"] == "paid"
        assert range_snapshots >= 3
        assert paths.count(f"/series/{WORK_ID}/1") == 1
    finally:
        await page.unroute("https://heros-web.com/**", fulfill)


async def test_herosweb_discovery_aborts_real_redirect_before_followup_request(
    browser_page: Page,
) -> None:
    page = browser_page
    foreign_work_id = "fffffffffffff"
    work_url = f"https://heros-web.com/series/{WORK_ID}"
    foreign_url = f"https://heros-web.com/series/{foreign_work_id}"
    fixture_requests: list[str] = []

    def record_request(request) -> None:
        from urllib.parse import urlsplit

        fixture_requests.append(f"{request.method} {urlsplit(request.url).path}")

    async def fulfill(route) -> None:
        from urllib.parse import urlsplit

        path = urlsplit(route.request.url).path
        fixture_requests.append(f"ROUTE {path}")
        if path == f"/series/{WORK_ID}":
            await route.fulfill(status=302, headers={"location": foreign_url})
            return
        if path == f"/series/{foreign_work_id}":
            await route.fulfill(
                status=200, headers={"content-type": "text/html"}, body="foreign target"
            )
            return
        if path == "/api/auth/session":
            await route.fulfill(
                status=200,
                headers={"content-type": "application/json"},
                body='{"user":null}',
            )
            return
        await route.fulfill(status=404, body="unexpected redirect followup")

    page.on("request", record_request)
    await page.route("https://heros-web.com/**", fulfill)
    original = _multi_range_target()
    target = WatchlistTarget(
        key=original.key,
        work_key=original.work_key,
        site=original.site,
        url=work_url,
        label=original.label,
        discovery_scope=original.discovery_scope,
    )
    adapter = HeroswebDiscoveryAdapter()
    try:
        generated = adapter.iter_records(page, target, "full")
        with pytest.raises(DiscoveryIncompleteError):
            async for _record in generated:
                pass
        assert f"ROUTE /series/{foreign_work_id}" not in fixture_requests
        assert foreign_url not in page.url
    finally:
        page.remove_listener("request", record_request)
        await page.unroute("https://heros-web.com/**", fulfill)


@pytest.mark.parametrize("status", [200, 302, 403, 429])
async def test_herosweb_discovery_main_document_guard_preserves_status_and_disposes(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    class FakePage:
        main_frame = object()

    class FakeRequest:
        url = BASE
        method = "GET"
        frame = FakePage.main_frame
        headers: ClassVar[dict[str, str]] = {"cookie": "session=synthetic"}

        @staticmethod
        def is_navigation_request() -> bool:
            return True

    class FakeResponse:
        def __init__(self) -> None:
            self.status = status
            self.disposed = False

        async def dispose(self) -> None:
            self.disposed = True

    class FakeRoute:
        def __init__(self) -> None:
            self.request = FakeRequest()
            self.response = FakeResponse()
            self.fetched_with: dict[str, object] | None = None
            self.fulfilled_with: dict[str, object] | None = None
            self.aborted = False
            self.fallback_called = False

        async def fetch(self, **kwargs):
            self.fetched_with = kwargs
            return self.response

        async def fulfill(self, **kwargs):
            self.fulfilled_with = kwargs

        async def abort(self) -> None:
            self.aborted = True

        async def fallback(self) -> None:
            self.fallback_called = True

    monkeypatch.setattr(
        discovery_module,
        "_fetch_main_document_response_without_redirect",
        _PRODUCTION_DOCUMENT_FETCH,
    )
    guard = discovery_module._HeroswebRequestGuard(FakePage())
    guard.allow_navigation(BASE)
    route = FakeRoute()
    await guard(route)
    assert route.fetched_with == {
        "max_redirects": 0,
        "max_retries": 0,
        "timeout": discovery_module.NAVIGATION_TIMEOUT_MS,
    }
    assert route.request.headers == {"cookie": "session=synthetic"}
    assert route.response.disposed is True
    assert route.fallback_called is False
    if status == 302:
        assert route.aborted is True
        assert route.fulfilled_with is None
        assert guard.navigation_violation is not None
    else:
        assert route.aborted is False
        assert route.fulfilled_with == {"response": route.response}
        assert guard.navigation_violation is None


async def test_herosweb_discovery_guard_blocks_real_local_redirect_before_target_request(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {"redirect": 0, "trap": 0}

    async def handle_http(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        request_line = await reader.readline()
        while line := await reader.readline():
            if line in {b"\r\n", b"\n"}:
                break
        path = request_line.decode("latin1").split(" ")[1]
        if path == "/redirect":
            state["redirect"] += 1
            response = (
                "HTTP/1.1 302 Found\r\nLocation: /trap\r\n"
                "Content-Length: 0\r\nConnection: close\r\n\r\n"
            )
        elif path == "/trap":
            state["trap"] += 1
            response = (
                "HTTP/1.1 200 OK\r\nContent-Length: 4\r\n"
                "Connection: close\r\n\r\ntrap"
            )
        else:
            response = (
                "HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n"
                "Connection: close\r\n\r\n"
            )
        writer.write(response.encode("ascii"))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle_http, "127.0.0.1", 0)
    local_port = server.sockets[0].getsockname()[1]
    local_url = f"http://127.0.0.1:{local_port}/redirect"

    async def local_transport(route):
        return await route.fetch(
            url=local_url,
            max_redirects=0,
            max_retries=0,
            timeout=discovery_module.NAVIGATION_TIMEOUT_MS,
        )

    monkeypatch.setattr(
        discovery_module,
        "_fetch_main_document_response_without_redirect",
        local_transport,
    )
    guard = discovery_module._HeroswebRequestGuard(browser_page)
    guard.allow_navigation(BASE)
    await browser_page.route("https://heros-web.com/**", guard)
    try:
        with pytest.raises(PlaywrightError):
            await browser_page.goto(BASE, wait_until="commit", timeout=5_000)
        assert state == {"redirect": 1, "trap": 0}
        assert guard.navigation_violation == f"GET heros-web.com/series/{WORK_ID} redirect 302"
        assert guard.main_frame_navigation_urls == [BASE]
    finally:
        await browser_page.unroute("https://heros-web.com/**", guard)
        server.close()
        await server.wait_closed()


async def test_herosweb_authenticated_listing_checks_session_and_classifies_observed_access(
    browser_page: Page,
) -> None:
    page = browser_page
    paths: list[str] = []
    fixture_posts: list[str] = []
    blocked_posts: list[str] = []

    async def fulfill(route) -> None:
        from urllib.parse import urlsplit

        request = route.request
        path = urlsplit(request.url).path
        if request.method.upper() not in {"GET", "HEAD"}:
            fixture_posts.append(path)
            await route.fulfill(status=200, body="unexpected state change reached fixture")
            return
        paths.append(path)
        if path == "/api/auth/session":
            await route.fulfill(
                status=200,
                headers={"content-type": "application/json"},
                body='{"user":{"id":"fixture-only"}}',
            )
        elif path == f"/series/{WORK_ID}":
            await route.fulfill(
                status=200, headers={"content-type": "text/html"},
                body=_authenticated_page_html(base=True),
            )
        elif path == f"/series/{WORK_ID}/1":
            await route.fulfill(
                status=200, headers={"content-type": "text/html"},
                body=_authenticated_page_html(base=False, delay_auth_header_ms=600),
            )
        else:
            await route.fulfill(status=404, body="unexpected path")

    def observe_request(request) -> None:
        from urllib.parse import urlsplit

        parsed = urlsplit(request.url)
        if parsed.hostname == "heros-web.com" and request.method.upper() not in {"GET", "HEAD"}:
            blocked_posts.append(parsed.path)

    page.on("request", observe_request)
    await page.route("https://heros-web.com/**", fulfill)
    target = WatchlistTarget(
        key="authenticated-fixture",
        work_key="authenticated-fixture",
        site="herosweb",
        url=BASE,
        label="Fixture Work",
    )
    try:
        records = [
            record async for record in HeroswebDiscoveryAdapter().iter_records(page, target, "full")
        ]
        assert [record.source.access_mode for record in records] == ["paid", "quota", "free"]
        assert [record.source.global_display_position for record in records] == [3, 2, 1]
        assert paths.count("/api/auth/session") == 2
        assert paths.count(f"/series/{WORK_ID}") == 1
        assert paths.count(f"/series/{WORK_ID}/1") == 1
        assert blocked_posts == ["/api/missions", "/api/missions"]
        assert fixture_posts == []
    finally:
        page.remove_listener("request", observe_request)
        await page.unroute("https://heros-web.com/**", fulfill)


@pytest.mark.parametrize("mode", ["full", "incremental"])
async def test_herosweb_multirange_buffers_complete_listing_in_both_modes(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    page = browser_page
    paths: list[str] = []
    pacing: list[int] = []

    async def fulfill(route) -> None:
        from urllib.parse import urlsplit

        path = urlsplit(route.request.url).path
        paths.append(path)
        if path == f"/series/{WORK_ID}":
            body = _multi_range_html(work_id=WORK_ID, page_number=None)
        elif path == f"/series/{WORK_ID}/1":
            body = _multi_range_html(work_id=WORK_ID, page_number=1)
        elif path == f"/series/{WORK_ID}/2":
            body = _multi_range_html(work_id=WORK_ID, page_number=2)
        elif path == "/api/auth/session":
            await route.fulfill(
                status=200,
                headers={"content-type": "application/json"},
                body='{"user":null}',
            )
            return
        else:
            await route.fulfill(status=404, body="unexpected route")
            return
        await route.fulfill(
            status=200,
            headers={"content-type": "text/html; charset=utf-8"},
            body=body,
        )

    async def record_pacing(milliseconds: int) -> None:
        pacing.append(milliseconds)

    await page.route("https://heros-web.com/**", fulfill)
    monkeypatch.setattr(page, "wait_for_timeout", record_pacing)
    adapter = HeroswebDiscoveryAdapter()
    try:
        records = [
            record
            async for record in adapter.iter_records(page, _multi_range_target(), mode)
        ]
        assert len(records) == 31
        assert [record.source.global_display_position for record in records] == list(
            range(31, 0, -1)
        )
        assert len({record.source.external_id for record in records}) == 31
        assert adapter.complete_listing_inventory is not None if mode == "full" else True
        assert paths == [
            f"/series/{WORK_ID}",
            "/api/auth/session",
            f"/series/{WORK_ID}/1",
            "/api/auth/session",
            f"/series/{WORK_ID}/2",
            "/api/auth/session",
        ]
        assert pacing.count(3_200) == 2
    finally:
        await page.unroute("https://heros-web.com/**", fulfill)


@pytest.mark.parametrize(
    "fault",
    ["duplicate", "foreign_scope", "http_403", "http_429", "challenge", "redirect"],
)
async def test_herosweb_later_range_faults_fail_before_any_record_is_yielded(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    page = browser_page
    outside_host_requests: list[str] = []

    async def no_wait(_milliseconds: int) -> None:
        return None

    async def fulfill(route) -> None:
        from urllib.parse import urlsplit

        parsed = urlsplit(route.request.url)
        if parsed.hostname == "example.invalid":
            outside_host_requests.append(route.request.url)
            await route.fulfill(status=200, body="foreign document must not load")
            return
        path = parsed.path
        if path == f"/series/{WORK_ID}":
            body = _multi_range_html(work_id=WORK_ID, page_number=None)
            await route.fulfill(
                status=200, headers={"content-type": "text/html"}, body=body
            )
            return
        if path == "/api/auth/session":
            await route.fulfill(
                status=200,
                headers={"content-type": "application/json"},
                body='{"user":null}',
            )
            return
        if path == f"/series/{WORK_ID}/1":
            await route.fulfill(
                status=200,
                headers={"content-type": "text/html"},
                body=_multi_range_html(work_id=WORK_ID, page_number=1),
            )
            return
        if path == f"/series/{WORK_ID}/2":
            if fault == "http_403":
                await route.fulfill(status=403, body="forbidden")
            elif fault == "http_429":
                await route.fulfill(status=429, body="rate limited")
            elif fault == "challenge":
                await route.fulfill(
                    status=200,
                    headers={"content-type": "text/html"},
                    body="<div id='challenge-running'>challenge</div>",
                )
            elif fault == "redirect":
                await route.fulfill(
                    status=302,
                    headers={"location": "https://example.invalid/reader"},
                    body="",
                )
            else:
                await route.fulfill(
                    status=200,
                    headers={"content-type": "text/html"},
                    body=_multi_range_html(
                        work_id=WORK_ID,
                        page_number=2,
                        fault=fault,
                    ),
                )
            return
        await route.fulfill(status=404, body="unexpected route")

    await page.route("**/*", fulfill)
    monkeypatch.setattr(page, "wait_for_timeout", no_wait)
    adapter = HeroswebDiscoveryAdapter()
    target = _multi_range_target()
    try:
        generated = adapter.iter_records(page, target, "full")
        yielded = []
        with pytest.raises(DiscoveryIncompleteError):
            async for record in generated:
                yielded.append(record)
        assert yielded == []
        assert adapter.complete_listing_inventory is None
        assert outside_host_requests == []
    finally:
        await page.unroute("**/*", fulfill)


async def test_herosweb_exclusion_preview_replays_exact_listing_and_preserves_catalog_on_failure(
    browser_page: Page,
    tmp_path,
) -> None:
    page = browser_page
    state = {"fault": None}
    paths: list[str] = []

    async def fulfill(route) -> None:
        from urllib.parse import urlsplit

        path = urlsplit(route.request.url).path
        paths.append(path)
        if path == "/api/auth/session":
            await route.fulfill(
                status=200,
                headers={"content-type": "application/json"},
                body='{"user":null}',
            )
            return
        if path == f"/series/{WORK_ID}":
            body = _page_html(base=True, row_count=0)
            await route.fulfill(
                status=200, headers={"content-type": "text/html"}, body=body
            )
        elif path == f"/series/{WORK_ID}/1":
            body = _page_html(base=False, row_count=1 if state["fault"] else 2)
            await route.fulfill(
                status=503 if state["fault"] else 200,
                headers={"content-type": "text/html"},
                body=body,
            )
        else:
            await route.fulfill(status=404, body="unexpected route")

    await page.route("https://heros-web.com/**", fulfill)
    catalog = CatalogService(tmp_path / "isolated-herosweb.sqlite")
    registry = _herosweb_registry()
    target = _multi_range_target(
        scope=DiscoveryScope(
            excluded_external_ids=(f"{WORK_ID}:{1:013x}",),
        )
    )
    try:
        first = await DiscoveryService(catalog, registry).discover(page, target, "full")
        assert first.complete is True
        assert first.observed_count == 1
        assert [source.external_id for source in catalog.list_sources(site="herosweb")] == [
            f"{WORK_ID}:{2:013x}"
        ]
        # Preview plus acquisition replay one frozen listing; no second navigation.
        assert paths.count(f"/series/{WORK_ID}") == 1
        assert paths.count(f"/series/{WORK_ID}/1") == 1

        before = [
            (source.external_id, source.access_mode, source.available, source.display_position)
            for source in catalog.list_sources(site="herosweb")
        ]
        state["fault"] = "later-range"
        failed = await DiscoveryService(catalog, registry).discover(
            page, _multi_range_target(), "full"
        )
        after = [
            (source.external_id, source.access_mode, source.available, source.display_position)
            for source in catalog.list_sources(site="herosweb")
        ]
        assert failed.complete is False
        assert failed.observed_count == 0
        assert before == after
    finally:
        await page.unroute("https://heros-web.com/**", fulfill)
