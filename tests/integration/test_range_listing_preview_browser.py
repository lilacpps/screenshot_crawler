"""Static Hanayume/Younganimal ranges: completeness, no viewer, exclusion replay."""
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
from screenshot_crawler.discovery.service import DiscoveryIncompleteError
from screenshot_crawler.watchlist.models import DiscoveryScope
from screenshot_crawler.watchlist.selection import SelectionPlanner
from tests.integration import test_hanayume_discovery_browser as hana
from tests.integration import test_younganimal_discovery_browser as ya

pytestmark = pytest.mark.asyncio(loop_scope='module')


@pytest.fixture
def upstream(monkeypatch):
    state = {'site': 'hanayume', 'fault': None, 'calls': []}
    for module in ('hanayume', 'younganimal'):
        monkeypatch.setattr(f'screenshot_crawler.site_adapters.{module}.discovery.RANGE_PACING_MS', 0)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            module = hana if state['site'] == 'hanayume' else ya
            target = module._target()
            suffix = self.path.removeprefix(urlsplit(target.url).path).strip('/')
            page = int(suffix) if suffix in ('1', '2') else None
            fault = state['fault'] if page == 2 else None
            status = 302 if fault == 'redirect' else 503 if fault == 'http' else 200
            self.send_response(status)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            if fault == 'redirect':
                self.send_header('Location', 'https://foreign.invalid/reader')
            self.end_headers()
            if module is hana:
                body = hana._page_html(page_number=page, omit_last_row=fault == 'missing',
                    duplicate_boundary_row=fault == 'duplicate', foreign_work=fault == 'foreign',
                    drift_last_range=fault == 'range')
            else:
                positions = list(range(23, 33)) if page is None else list(range(1, 31)) if page == 1 else (
                    [31] if fault == 'missing' else [30, 32] if fault == 'duplicate' else [31, 32])
                body = ya._listing_html(positions=positions, selected_page=page, title=True)
                if fault == 'foreign':
                    body = body.replace(ya.WORK_ID, 'fffffffffffff')
                if fault == 'range':
                    body = body.replace('31-32', '31-33')
                if state['fault'] == 'loading_history':
                    body = body.replace('class="series-eplist mode-user"', 'class="series-eplist mode-user mode-loading"')
                    body = body.replace('data-e2e="epListUser"></div>', 'data-e2e="epListUser"><div class="series-eplist-item">skeleton</div><div class="series-eplist">nested history skeleton</div></div>')
            canonical = 'https://foreign.invalid/' if state['fault'] == 'canonical' and page is None else target.url
            body += f'<link rel="canonical" href="{canonical}">'
            body += '<script>window.viewerStarted=true;fetch("/spend",{method:"POST"})</script>'
            self.wfile.write(body.encode('utf-8'))

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    fetch = Route.fetch

    async def supply(route, **kwargs):
        state['calls'].append((route.request.method, route.request.url))
        return await fetch(route, url=f'http://127.0.0.1:{server.server_port}{urlsplit(route.request.url).path}', **kwargs)

    monkeypatch.setattr(Route, 'fetch', supply)
    yield state
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.mark.parametrize('site', ['hanayume', 'younganimal'])
async def test_static_ranges_prove_all_positions_without_store_or_viewer(browser_page, upstream, tmp_path, site):
    upstream['site'] = site
    target = (hana if site == 'hanayume' else ya)._target()
    listing = await ListingPreviewService(_discovery_registry()).preview_complete_listing(browser_page, target)
    assert listing.ready and len(listing.rows) == 32
    assert [r.site_position for r in listing.rows] == list(range(32, 0, -1))
    assert listing.listing_identity == f'{site}-work:{(hana if site == "hanayume" else ya).WORK_ID}'
    plan = SelectionPlanner().plan(listing, [r.external_id for i, r in enumerate(listing.rows) if i != 2])
    assert plan.ready and len(plan.excluded_external_ids) == 1
    assert len(upstream['calls']) == 3 and all(method == 'GET' for method, _ in upstream['calls'])
    assert await browser_page.evaluate('typeof window.viewerStarted') == 'undefined'
    assert not tuple(tmp_path.iterdir())


@pytest.mark.parametrize('site', ['hanayume', 'younganimal'])
@pytest.mark.parametrize('fault', ['missing', 'duplicate', 'foreign', 'range', 'redirect', 'http', 'canonical'])
async def test_incomplete_foreign_or_changed_ranges_never_become_complete(browser_page, upstream, site, fault):
    upstream.update(site=site, fault=fault)
    target = (hana if site == 'hanayume' else ya)._target()
    listing = await ListingPreviewService(_discovery_registry()).preview_complete_listing(browser_page, target)
    assert not listing.ready and not listing.complete and listing.blockers
    assert all(method == 'GET' for method, _ in upstream['calls'])


@pytest.mark.parametrize('site', ['hanayume', 'younganimal'])
async def test_exclusion_discovery_uses_only_preflight_ranges(browser_page, upstream, tmp_path, site):
    upstream['site'] = site
    module = hana if site == 'hanayume' else ya
    target = replace(module._target(), discovery_scope=DiscoveryScope(
        excluded_external_ids=(f'{module.WORK_ID}:{module._episode_id(4)}',)))
    catalog = CatalogService(tmp_path / 'catalog.sqlite')
    result = await DiscoveryService(catalog, _discovery_registry()).discover(browser_page, target, 'full')
    assert result.complete and result.observed_count == 31
    assert len(catalog.list_sources()) == 31
    assert len(upstream['calls']) == 3


@pytest.mark.parametrize('site', ['hanayume', 'younganimal'])
async def test_consumed_or_stale_proof_is_not_reloaded(browser_page, upstream, monkeypatch, site):
    upstream['site'] = site
    module = hana if site == 'hanayume' else ya
    target = replace(module._target(), discovery_scope=DiscoveryScope(
        excluded_external_ids=(f'{module.WORK_ID}:{module._episode_id(4)}',)))
    adapter = _discovery_registry().create(site)
    await adapter.prepare_exclusion_preview(browser_page, target)
    monkeypatch.setattr('screenshot_crawler.discovery.listing_replay.monotonic', lambda: float('inf'))
    with pytest.raises(DiscoveryIncompleteError, match='fresh same-Page'):
        _ = [r async for r in adapter.iter_records(browser_page, target, 'full')]
    assert len(upstream['calls']) == 3


async def test_public_only_preview_ignores_loading_history_skeleton_but_normal_read_waits(browser_page, upstream, monkeypatch):
    from screenshot_crawler.site_adapters.younganimal import discovery
    upstream.update(site='younganimal', fault='loading_history')
    listing = await ListingPreviewService(_discovery_registry()).preview_complete_listing(browser_page, ya._target())
    assert listing.ready and len(listing.rows) == 32
    monkeypatch.setattr(discovery, 'DOM_TIMEOUT_MS', 100)
    with pytest.raises(DiscoveryIncompleteError, match='user listing did not settle'):
        await discovery._read_range_rows(browser_page, work_id=ya.WORK_ID, first_position=31)
