"""Complete static listing preview and same-observation exclusion replay."""
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
from playwright.async_api import Route

from screenshot_crawler.catalog import CatalogService
from screenshot_crawler.discovery import DiscoveryService
from screenshot_crawler.discovery.listing_service import ListingPreviewService
from screenshot_crawler.discovery.service import DiscoveryIncompleteError
from screenshot_crawler.site_adapters.piccoma import PiccomaDiscoveryAdapter
from screenshot_crawler.watchlist.models import DiscoveryScope
from screenshot_crawler.watchlist.selection import SelectionPlanner
from tests.integration.test_piccoma_discovery_browser import _listing_html, _registry, _target

pytestmark = pytest.mark.asyncio(loop_scope='module')
URL = 'https://piccoma.com/web/product/900/episodes'


@pytest.fixture
def upstream(monkeypatch):
    state = {'html': _listing_html(), 'status': 200, 'canonical': URL, 'calls': []}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(state['status'])
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            if state['status'] == 302:
                self.send_header('Location', 'https://foreign.invalid/reader')
            self.end_headers()
            body = f'<link rel="canonical" href="{state["canonical"]}">' + state['html']
            body += '<script>window.viewerStarted=true;fetch("/spend",{method:"POST"})</script><img src="https://foreign.invalid/image">'
            self.wfile.write(body.encode('utf-8'))

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    fetch = Route.fetch

    async def supply(route, **kwargs):
        state['calls'].append((route.request.method, route.request.url))
        assert kwargs['max_redirects'] == 0
        return await fetch(route, url=f'http://127.0.0.1:{server.server_port}/', **kwargs)

    monkeypatch.setattr(Route, 'fetch', supply)
    yield state
    server.shutdown()
    server.server_close()
    thread.join()


async def test_piccoma_preview_is_complete_without_catalog_or_viewer(browser_page, upstream, tmp_path):
    before = tuple(tmp_path.iterdir())
    listing = await ListingPreviewService(_registry()).preview_complete_listing(browser_page, _target())
    assert listing.ready and listing.listing_identity == 'piccoma-product:900'
    assert [row.external_id for row in listing.rows] == ['900:104', '900:103', '900:102', '900:101']
    assert [row.site_position for row in listing.rows] == [4, 3, 2, 1]
    assert [row.access_observation for row in listing.rows] == ['unknown', 'paid', 'quota', 'free']
    plan = SelectionPlanner().plan(listing, ['900:104', '900:102', '900:101'])
    assert plan.ready and plan.discovery_scope.excluded_external_ids == ('900:103',)
    assert tuple(tmp_path.iterdir()) == before
    assert await browser_page.evaluate('typeof window.viewerStarted') == 'undefined'
    assert upstream['calls'] == [('GET', URL)]


@pytest.mark.parametrize('fault', ['count', 'duplicate', 'foreign', 'order', 'missing_seed', 'canonical', 'redirect', 'http'])
async def test_piccoma_partial_or_foreign_preview_fails_closed(browser_page, upstream, fault):
    kwargs = {'declared_count': 5} if fault == 'count' else {'duplicate_last_id': True} if fault == 'duplicate' else (
        {'foreign_last_product_id': '901'} if fault == 'foreign' else {'list_class': 'PCM-list_desc'} if fault == 'order' else {})
    upstream['html'] = _listing_html(**kwargs)
    if fault == 'canonical':
        upstream['canonical'] = URL.replace('/900/', '/901/')
    if fault in {'redirect', 'http'}:
        upstream['status'] = 302 if fault == 'redirect' else 503
    listing = await ListingPreviewService(_registry()).preview_complete_listing(
        browser_page, _target(episode_id='999' if fault == 'missing_seed' else '101'))
    assert not listing.ready and not listing.complete and listing.blockers
    assert upstream['calls'] == [('GET', URL)]


async def test_piccoma_exclusion_full_replays_one_read_before_any_write(browser_page, upstream, tmp_path):
    target = _target(discovery_scope=DiscoveryScope(excluded_external_ids=('900:103',)))
    catalog = CatalogService(tmp_path / 'catalog.sqlite')
    result = await DiscoveryService(catalog, _registry()).discover(browser_page, target, 'full')
    assert result.complete and result.observed_count == 3
    assert {s.external_id for s in catalog.list_sources()} == {'900:104', '900:102', '900:101'}
    assert upstream['calls'] == [('GET', URL)]


@pytest.mark.parametrize('fault', ['missing', 'stale', 'target', 'scope', 'page', 'consumed'])
async def test_piccoma_replay_never_rereads_without_matching_fresh_proof(browser_page, upstream, monkeypatch, fault):
    target = _target(discovery_scope=DiscoveryScope(excluded_external_ids=('900:103',)))
    adapter = PiccomaDiscoveryAdapter()
    if fault != 'missing':
        await adapter.prepare_exclusion_preview(browser_page, target)
    if fault == 'stale':
        monkeypatch.setattr('screenshot_crawler.site_adapters.piccoma.discovery.monotonic', lambda: float('inf'))
    if fault == 'target':
        target = replace(target, key='changed')
    if fault == 'scope':
        target = replace(target, discovery_scope=DiscoveryScope(excluded_external_ids=('900:102',)))
    if fault == 'page':
        adapter._exclusion_preview_cache = (-1, *adapter._exclusion_preview_cache[1:])
    if fault == 'consumed':
        first = [r async for r in adapter.iter_records(browser_page, target, 'full')]
        assert len(first) == 3
    with pytest.raises(DiscoveryIncompleteError, match='fresh same-Page'):
        _ = [r async for r in adapter.iter_records(browser_page, target, 'full')]
    assert len(upstream['calls']) == (0 if fault == 'missing' else 1)


@pytest.mark.parametrize('scope', [
    DiscoveryScope(excluded_external_ids=('900:999',)),
    DiscoveryScope(from_url='https://piccoma.com/web/viewer/900/103', through_url='https://piccoma.com/web/viewer/900/102', excluded_external_ids=('900:101',)),
    DiscoveryScope(from_url='https://piccoma.com/web/viewer/900/101', through_url='https://piccoma.com/web/viewer/900/104', excluded_external_ids=('900:102',)),
])
async def test_piccoma_invalid_exclusion_preflight_creates_no_work(browser_page, upstream, tmp_path, scope):
    catalog = CatalogService(tmp_path / 'catalog.sqlite')
    result = await DiscoveryService(catalog, _registry()).discover(browser_page, _target(discovery_scope=scope), 'full')
    assert not result.complete and catalog.list_works() == [] and catalog.list_sources() == []
    assert upstream['calls'] == [('GET', URL)]
