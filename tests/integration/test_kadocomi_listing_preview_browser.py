"""Inert native history preview, including sparse ordinals and ended rows."""
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import urlsplit

import pytest
from playwright.async_api import Route

from screenshot_crawler.catalog import CatalogService
from screenshot_crawler.cli import _discovery_registry
from screenshot_crawler.discovery import DiscoveryService
from screenshot_crawler.discovery.listing_service import ListingPreviewService
from screenshot_crawler.watchlist.models import DiscoveryScope
from screenshot_crawler.watchlist.selection import SelectionPlanner
from screenshot_crawler.watchlist.work_edit import WorkDraft
from tests.integration import test_kadocomi_discovery_browser as fixture

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest.fixture
def upstream(monkeypatch):
    state = {"fault": None, "calls": []}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            episodes = fixture._native_episodes()
            fault = state["fault"]
            if fault == "duplicate":
                episodes[-1] = episodes[-2]
            if fault == "foreign":
                episodes[-1]["code"] = "KC_9999990000000001_E"
            if fault == "leading":
                episodes[0]["isActive"] = False
            if fault == "reverse":
                episodes.reverse()
            body = fixture._native_page_html(episodes=episodes, expand=True)
            if fault == "total":
                body = body.replace('"total": 7', '"total": 8')
            canonical = "https://foreign.invalid/" if fault == "canonical" else fixture.WORK_URL.split("?")[0]
            body += f'<link rel="canonical" href="{canonical}">'
            body += '<script>window.viewerStarted=true;fetch("/spend",{method:"POST"})</script>'
            self.send_response(302 if fault == "redirect" else 503 if fault == "http" else 200)
            if fault == "redirect":
                self.send_header("Location", "https://foreign.invalid/reader")
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    fetch = Route.fetch

    async def supply(route, **kwargs):
        state["calls"].append((route.request.method, route.request.url))
        return await fetch(route, url=f"http://127.0.0.1:{server.server_port}{urlsplit(route.request.url).path}", **kwargs)

    monkeypatch.setattr(Route, "fetch", supply)
    yield state
    server.shutdown()
    server.server_close()
    thread.join()


async def test_complete_sparse_native_preview_never_expands_or_bootstraps(browser_page, upstream, tmp_path):
    target = fixture._native_target(archive_order=None)
    listing = await ListingPreviewService(_discovery_registry()).preview_complete_listing(browser_page, target)
    assert listing.ready and listing.native_order.declared_count == 7
    assert [row.site_position for row in listing.rows] == [125, 108, 89, 88, 6, 2, 1]
    assert sum(row.access_observation == "unavailable" for row in listing.rows) == 4
    assert await browser_page.evaluate("typeof window.viewerStarted") == "undefined"
    assert len(upstream["calls"]) == 1 and upstream["calls"][0][0] == "GET"
    assert not tuple(tmp_path.iterdir())
    draft = WorkDraft((target,), target.work_key)
    draft.set_listing(listing)
    boundary = listing.rows[1]
    draft.set_range(target.key, boundary.external_id, None)
    draft.validate()
    assert draft.target(target.key).discovery_scope == DiscoveryScope(through_url=boundary.url)
    assert SelectionPlanner().plan(listing, [r.external_id for r in listing.rows[:2]]).ready
    assert not SelectionPlanner().plan(listing, [listing.rows[0].external_id, listing.rows[2].external_id]).ready


@pytest.mark.parametrize("fault", ["total", "duplicate", "foreign", "leading", "reverse", "canonical", "redirect", "http"])
async def test_incomplete_or_foreign_native_preview_stays_blocked(browser_page, upstream, fault):
    upstream["fault"] = fault
    listing = await ListingPreviewService(_discovery_registry()).preview_complete_listing(
        browser_page, fixture._native_target())
    assert not listing.ready and listing.blockers
    assert len(upstream["calls"]) == 1


async def test_exclusion_is_rejected_before_any_store_or_page_request(browser_page, upstream, tmp_path):
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    target = replace(fixture._native_target(), discovery_scope=DiscoveryScope(
        through_url=f"{fixture.BASE}/detail/{fixture.WORK_ID}/episodes/{fixture._episode_id(2)}",
        excluded_external_ids=(f"{fixture.WORK_ID}:{fixture._episode_id(3)}",)))
    result = await DiscoveryService(catalog, _discovery_registry()).discover(browser_page, target, "full")
    assert not result.complete and "replays" in result.error
    assert upstream["calls"] == [] and not catalog.path.exists()
