"""Single-page native series completeness, safe metadata and one-shot replay."""
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import urlsplit

import pytest
from playwright.async_api import Route

from screenshot_crawler.catalog import CatalogService
from screenshot_crawler.discovery import DiscoveryAdapterRegistry, DiscoveryService
from screenshot_crawler.discovery.listing_service import ListingPreviewService
from screenshot_crawler.discovery.service import DiscoveryIncompleteError
from screenshot_crawler.site_adapters.bookwalker import discovery as bw
from screenshot_crawler.watchlist.models import DiscoveryScope, WatchlistTarget
from screenshot_crawler.watchlist.selection import SelectionPlanner
from tests.integration.test_bookwalker_discovery_browser import _product_page_html, _uuid

pytestmark = pytest.mark.asyncio(loop_scope='module')
URL = 'https://bookwalker.jp/series/900/list/'


def target(scope=None):
    return WatchlistTarget('isolated_bw', 'isolated_work', 'bookwalker', URL, 'Synthetic', discovery_scope=scope)


def registry():
    result = DiscoveryAdapterRegistry()
    result.register('bookwalker', bw.BookWalkerDiscoveryAdapter)
    return result


def html(fault=None):
    cards = []
    for i in (4, 3, 2, 1):
        identity = _uuid(2 if fault == 'duplicate' and i == 1 else i)
        link = f'https://bookwalker.jp/de{identity}/'
        if fault in {'query', 'fragment', 'credentials', 'port'} and i == 1:
            link += '?tracking=1' if fault == 'query' else '#reader' if fault == 'fragment' else ''
            link = link.replace('https://', 'https://user@') if fault == 'credentials' else link.replace('.jp/', '.jp:443/') if fault == 'port' else link
        hidden = ' hidden' if fault == 'hidden' and i == 1 else ''
        second = f'<a href="https://bookwalker.jp/de{_uuid(99)}/">foreign</a>' if fault == 'two_ids' and i == 1 else ''
        cards.append(f'<li class="m-tile"{hidden}><h3>Synthetic {i}</h3><a href="{link}">cover</a>'
            f'<a href="{link}">title</a><a href="https://bookwalker.jp/de{identity}/?sample=1">trial</a>{second}</li>')
    count = '1～4件目/全5件' if fault == 'partial' else '1～4件目/全4件'
    footer = '1～4件目/全6件' if fault == 'counts' else count
    counts = '' if fault == 'no_count' else f'<p class="o-contents-section__search_count">{count}</p>'
    counts += '' if fault in {'no_count', 'one_count'} else f'<div class="o-contents-section__search_count">{footer}</div>'
    sort = '' if fault == 'no_sort' else '<select id="sortDropdownBox"><option value="' + ('title' if fault == 'sort' else 'release') + '" selected>native order</option></select>'
    next_link = '<a rel="next" href="?page=2">Next</a>' if fault == 'pagination' else ''
    return f'<h1>『Synthetic』の電子書籍一覧</h1>{sort}<section class="o-contents-section">{counts}' \
        f'<ul class="m-tile-list">{"".join(cards)}</ul>{next_link}</section>'


@pytest.fixture
def upstream(monkeypatch):
    state = {'fault': None, 'calls': [], 'status': 200, 'canonical': URL, 'product_fault': None}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            original = self.headers['X-Original-URL']
            path = urlsplit(original).path
            faulty_product = path == f'/de{_uuid(2)}/'
            status = state['status'] if path.startswith('/series/') else 302 if state['product_fault'] == 'redirect' and faulty_product else 200
            self.send_response(status)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            if status == 302:
                self.send_header('Location', 'https://foreign.invalid/reader')
            self.end_headers()
            body = html(state['fault']) if path.startswith('/series/') else _product_page_html(path[3:-1], 'owned')
            if state['product_fault'] == 'missing' and faulty_product:
                body = '<h1>Missing product metadata</h1>'
            canonical = state['canonical'] if path.startswith('/series/') else original
            body = f'<link rel="canonical" href="{canonical}">{body}'
            body += '<script>window.viewerStarted=true;fetch("/spend",{method:"POST"})</script><img src="/reader-image">'
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
        return await fetch(route, url=f'http://127.0.0.1:{server.server_port}/',
            headers={'X-Original-URL': route.request.url}, **kwargs)

    monkeypatch.setattr(Route, 'fetch', supply)
    monkeypatch.setattr(bw, 'PRODUCT_CONTROL_WAIT_TIMEOUT_MS', 100)
    yield state
    server.shutdown()
    server.server_close()
    thread.join()


async def test_preview_deduplicates_links_only_inside_each_card_without_product_or_store_io(browser_page, upstream, tmp_path):
    before = tuple(tmp_path.iterdir())
    preview = await ListingPreviewService(registry()).preview_complete_listing(browser_page, target())
    assert preview.ready and preview.listing_identity == 'bookwalker-series:900'
    assert [r.external_id for r in preview.rows] == [_uuid(i) for i in (4, 3, 2, 1)]
    assert [r.site_position for r in preview.rows] == [4, 3, 2, 1]
    assert {r.access_observation for r in preview.rows} == {'unknown'}
    assert SelectionPlanner().plan(preview, [_uuid(i) for i in (4, 2, 1)]).ready
    assert tuple(tmp_path.iterdir()) == before
    assert await browser_page.evaluate('typeof window.viewerStarted') == 'undefined'
    assert upstream['calls'] == [('GET', URL)]


@pytest.mark.parametrize('fault', ['duplicate', 'two_ids', 'hidden', 'query', 'fragment', 'credentials', 'port',
    'partial', 'counts', 'no_count', 'one_count', 'sort', 'no_sort', 'pagination', 'canonical', 'redirect', 'http'])
async def test_partial_ambiguous_or_unsafe_series_is_blocked_before_writes(browser_page, upstream, tmp_path, fault):
    upstream['fault'] = fault
    if fault == 'canonical':
        upstream['canonical'] = URL.replace('/900/', '/901/')
    upstream['status'] = 302 if fault == 'redirect' else 503 if fault == 'http' else 200
    catalog = CatalogService(tmp_path / 'isolated.sqlite')
    catalog.initialize()
    scoped = target(DiscoveryScope(excluded_external_ids=(_uuid(3),)))
    result = await DiscoveryService(catalog, registry()).discover(browser_page, scoped, 'full')
    assert result.complete is False and result.observed_count == 0
    assert not catalog.list_works() and not catalog.list_sources()
    assert upstream['calls'] == [('GET', URL)]


async def test_full_exclusions_replay_one_list_and_observe_only_selected_static_product_metadata(browser_page, upstream, tmp_path):
    catalog = CatalogService(tmp_path / 'isolated.sqlite')
    scoped = target(DiscoveryScope(excluded_external_ids=(_uuid(3),)))
    result = await DiscoveryService(catalog, registry()).discover(browser_page, scoped, 'full')
    assert result.complete and result.observed_count == 3
    sources = catalog.list_sources()
    assert {s.external_id for s in sources} == {_uuid(i) for i in (4, 2, 1)}
    assert {s.access_mode for s in sources} == {'owned'}
    assert upstream['calls'] == [('GET', URL)] + [('GET', f'https://bookwalker.jp/de{_uuid(i)}/') for i in (4, 2, 1)]
    assert await browser_page.evaluate('typeof window.viewerStarted') == 'undefined'


@pytest.mark.parametrize('fault', ['missing', 'stale', 'target', 'page', 'scope', 'digest', 'consumed'])
async def test_replay_substitution_never_rereads(browser_page, upstream, fault):
    adapter = bw.BookWalkerDiscoveryAdapter()
    scoped = target(DiscoveryScope(excluded_external_ids=(_uuid(3),)))
    if fault != 'missing':
        await adapter.prepare_exclusion_preview(browser_page, scoped)
        cached = adapter._prepared_series_listing
        if fault == 'stale':
            adapter._prepared_series_listing = replace(cached, expires_at=0)
        if fault == 'page':
            adapter._prepared_series_listing = replace(cached, page_id=-1)
        if fault == 'digest':
            adapter._prepared_series_listing = replace(cached, digest='changed')
        if fault == 'target':
            scoped = replace(scoped, key='different')
        if fault == 'scope':
            scoped = replace(scoped, discovery_scope=DiscoveryScope(excluded_external_ids=(_uuid(2),)))
        if fault == 'consumed':
            assert len([r async for r in adapter.iter_records(browser_page, scoped, 'full')]) == 3
    calls = list(upstream['calls'])
    with pytest.raises(DiscoveryIncompleteError):
        _ = [r async for r in adapter.iter_records(browser_page, scoped, 'full')]
    assert upstream['calls'] == calls
    assert adapter._prepared_series_listing is None


@pytest.mark.parametrize('fault', ['redirect', 'missing'])
async def test_failed_product_metadata_publishes_no_sources_or_inventory(browser_page, upstream, tmp_path, fault):
    catalog = CatalogService(tmp_path / 'isolated.sqlite')
    upstream['product_fault'] = fault
    adapter = bw.BookWalkerDiscoveryAdapter()
    scoped = target(DiscoveryScope(excluded_external_ids=(_uuid(3),)))
    await adapter.prepare_exclusion_preview(browser_page, scoped)
    yielded = []
    with pytest.raises(DiscoveryIncompleteError):
        async for record in adapter.iter_records(browser_page, scoped, 'full'):
            yielded.append(record)
    assert not yielded
    assert adapter.complete_listing_inventory is None
    assert not catalog.path.exists()
