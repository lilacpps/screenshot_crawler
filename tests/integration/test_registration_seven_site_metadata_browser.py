"""Synthetic metadata only: no real sites, viewer, Catalog or operational YAML."""
import asyncio
import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
from playwright.async_api import Route

from screenshot_crawler.cli import _discovery_registry
from screenshot_crawler.registration.resolver import UrlResolver

pytestmark = pytest.mark.asyncio(loop_scope="module")
CASES = (
    ("magapoke", "https://pocket.shonenmagazine.com/title/01234/episode/5678"),
    ("mangaone", "https://manga-one.com/manga/123/chapter/456"),
    ("comicdays", "https://comic-days.com/episode/123"),
    ("jumpplus", "https://shonenjumpplus.com/episode/123"),
    ("hanayume", "https://hanayume.com/episodes/abcdef1234567/9"),
    ("kadocomi", "https://comic-walker.com/detail/KC_000123_S?episodeType=first"),
)
TITLE = "人工作品２！ | 副題"


def document(site, url, mode):
    canonical = "https://foreign.invalid/" if mode == "wrong_canonical" else url
    body = '' if mode == "missing_canonical" else f'<link rel="canonical" href="{canonical}">'
    title = "" if mode == "missing_title" else TITLE
    mismatch = "別の作品" if mode == "wrong_title" else title
    if site == "magapoke":
        node = f'<h1 class="p-episode__comic-ttl">{title}</h1>'
        body += node * (2 if mode == "duplicate" else 1)
        body += f'<meta property="og:title" content="{mismatch} | 人工話 / マガポケ">'
    elif site == "mangaone":
        meta = f'{title} 第1話' if mode != "unknown_format" else 'マンガワン'
        node = f'<meta property="og:title" content="{meta}">'
        body += node * (2 if mode == "duplicate" else 1)
        body += f'<title>{mismatch} 第1話 | マンガワン</title>' if mode != "unknown_format" else '<title>マンガワン | マンガワン</title>'
    elif site in {"comicdays", "jumpplus"}:
        product = {"id": "999" if mode == "wrong_binding" else "123",
                   "series": {"id": "567", "title": title}}
        if mode == "missing_binding":
            product.pop('id')
        if mode == "nonstring_title":
            product['series']['title'] = {"title": "bad"}
        native = '{' if mode == "malformed" else json.dumps({"readableProduct": product})
        node = f'<div id="episode-json" data-value="{html.escape(native, quote=True)}"></div>'
        body += node * (2 if mode == "duplicate" else 1)
        body += f'<h1 class="series-header-title">{mismatch}</h1>'
    elif site == "hanayume":
        link = 'https://foreign.invalid/series/abcdef1234567' if mode == "wrong_binding" else '/series/1234567abcdef'
        node = f'<a class="ep-h-main-h-series" href="{link}">{title}</a>'
        body += f'<div id="xHeader">{node * (2 if mode == "duplicate" else 1)}</div>'
    else:
        native = {"props": {"pageProps": {"dehydratedState": {"queries": [{
            "queryKey": ["/api/contents/details/work", {"workCode": "KC_000123_S"}],
            "state": {"data": {"work": {"code": "KC_000999_S" if mode == "wrong_binding" else "KC_000123_S", "title": title},
                               "firstComic": {"title": "誤ったコミックス名3【特典付き】"}}},
        }]}}}}
        if mode != "og_fallback":
            node = '<script id="__NEXT_DATA__" type="application/json">' + ('{' if mode == "malformed" else json.dumps(native)) + '</script>'
            body += node * (2 if mode == "duplicate" else 1)
        body += f'<meta property="og:title" content="{mismatch}｜カドコミ (コミックウォーカー)">'
    body += '<script>window.inlineViewerStarted=true;setTimeout(()=>fetch("https://foreign.invalid/post", {method:"POST"}).catch(()=>{}),20)</script>'
    body += '<img src="https://foreign.invalid/image"><iframe src="https://foreign.invalid/frame"></iframe>'
    return body.encode('utf-8')


MODES = [(*case, mode) for case in CASES for mode in (
    'ok', 'missing_title', 'duplicate', 'wrong_canonical', 'missing_canonical', 'redirect', 'http_error',
)] + [(*case, mode) for case in (CASES[2], CASES[3], CASES[5]) for mode in ('wrong_binding', 'malformed')]
MODES += [(*CASES[i], 'wrong_title') for i in (0, 1, 2, 3, 5)]
MODES += [(*CASES[i], mode) for i in (2, 3) for mode in ('missing_binding', 'nonstring_title')]
MODES += [(*CASES[4], 'wrong_binding'), (*CASES[1], 'unknown_format'), (*CASES[5], 'og_fallback')]


@pytest.mark.parametrize('site,input_url,mode', MODES)
async def test_metadata_is_bound_and_non_consuming(browser_page, monkeypatch, site, input_url, mode):
    resolver = UrlResolver(_discovery_registry())
    initial = resolver.resolve(input_url)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302 if mode == 'redirect' else 503 if mode == 'http_error' else 200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            if mode == 'redirect':
                self.send_header('Location', 'https://foreign.invalid/reader')
            self.end_headers()
            self.wfile.write(document(site, initial.discovery_url, mode))

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    requests, escaped, fetch = [], [], Route.fetch

    async def upstream(route, **kwargs):
        requests.append((route.request.method, route.request.url))
        assert kwargs['max_redirects'] == 0
        return await fetch(route, url=f'http://127.0.0.1:{server.server_port}/', **kwargs)

    async def sentinel(route):
        escaped.append(route.request.url)
        await route.abort()

    monkeypatch.setattr(Route, 'fetch', upstream)
    await browser_page.context.route('**/*', sentinel)
    try:
        result = await resolver.observe(browser_page, initial)
        if mode != 'redirect':  # Redirect response is aborted before any document loads.
            assert await browser_page.evaluate('typeof window.inlineViewerStarted') == 'undefined'
        await asyncio.sleep(0.06)  # Guard must remain after hook returns, including Kadocomi.
    finally:
        await browser_page.context.unroute('**/*', sentinel)
        server.shutdown()
        server.server_close()
        thread.join()
    assert requests == [('GET', initial.discovery_url)] and escaped == []
    assert result.discovery_url == initial.discovery_url
    assert result.site_work_identity == initial.site_work_identity
    if mode in {'ok', 'og_fallback'}:
        assert result.title == TITLE and result.status == initial.status
        assert resolver.resolution_error(result) is None
    elif mode in {'wrong_canonical', 'redirect', 'wrong_binding', 'wrong_title'}:
        assert result.status == 'blocked' and result.title is None
    else:
        assert result.status == initial.status and result.title is None and result.warnings
