import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
from playwright.async_api import Error, Route

from screenshot_crawler.cli import _discovery_registry
from screenshot_crawler.registration.resolver import UrlResolver

pytestmark = pytest.mark.asyncio(loop_scope="module")
CASES = (
    ("bookwalker", "https://bookwalker.jp/series/123/list/", "https://bookwalker.jp/series/123/list/"),
    ("comicfuz", "https://comic-fuz.com/manga/123", "https://comic-fuz.com/manga/123"),
    ("younganimal", "https://younganimal.com/series/abcdef1234567", "https://younganimal.com/series/abcdef1234567"),
    ("piccoma", "https://piccoma.com/web/viewer/63/99", "https://piccoma.com/web/product/63/episodes"),
)


def document(site, url, mode):
    canonical = "https://evil.invalid/" if mode == "wrong_canonical" else url
    body = "" if mode == "missing_canonical" else f'<link rel="canonical" href="{canonical}">'
    if site == "bookwalker":
        title = "<h1>『人工作品』の電子書籍一覧</h1>"
    elif site == "piccoma":
        title = '<div id="js_contentBody"><h2 class="PCM-headTitle_name">人工作品</h2></div>'
        product = "999" if mode == "wrong_binding" else "63"
        body += f'<div id="js_episodeList"><a data-product_id="{product}" data-episode_id="99">人工話</a></div>'
    else:
        title = '<meta property="og:title" content="人工作品">'
        suffix = " - 人工作者 | ヤングアニマルWeb" if site == "younganimal" else ""
        body += f"<title>人工作品{suffix}</title>"
        if site == "comicfuz":
            native = {"page": "/manga/[mangaId]", "query": {"mangaId": "999" if mode == "wrong_binding" else "123"}}
            body += '<script id="__NEXT_DATA__" type="application/json">' + (
                "{" if mode == "malformed_native" else json.dumps(native)) + "</script>"
    body += "" if mode == "missing_title" else title * (2 if mode == "duplicate_title" else 1)
    body += '<img src="https://foreign.invalid/image"><iframe src="https://foreign.invalid/frame"></iframe>'
    body += '<script>fetch("https://foreign.invalid/post", {method:"POST"}).catch(()=>{});</script>'
    return body.encode("utf-8")


@pytest.mark.parametrize("site,input_url,document_url,mode", [
    (*case, mode) for case in CASES for mode in ("ok", "missing_title", "duplicate_title",
        "missing_canonical", "wrong_canonical", "redirect", "http_error", "transport")
] + [(*CASES[1], "wrong_binding"), (*CASES[3], "wrong_binding"), (*CASES[1], "malformed_native")])
async def test_registration_reads_only_bound_work_document(browser_page, monkeypatch, site, input_url, document_url, mode):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302 if mode == "redirect" else 503 if mode == "http_error" else 200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            if mode == "redirect":
                self.send_header("Location", "https://foreign.invalid/reader")
            self.end_headers()
            self.wfile.write(document(site, document_url, mode))
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    requests, fetch = [], Route.fetch
    async def upstream(route, **kwargs):
        requests.append((route.request.method, route.request.url))
        assert kwargs["max_redirects"] == 0
        if mode == "transport":
            raise Error("synthetic transport failure")
        return await fetch(route, url=f"http://127.0.0.1:{server.server_port}/", **kwargs)
    monkeypatch.setattr(Route, "fetch", upstream)
    resolver = UrlResolver(_discovery_registry())
    initial = resolver.resolve(input_url)
    try:
        observed = await resolver.observe(browser_page, initial)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert requests == [("GET", document_url)]
    assert observed.discovery_url == initial.discovery_url
    if mode == "ok":
        assert observed.title == "人工作品" and observed.status == "valid"
    elif mode in {"redirect", "wrong_canonical", "wrong_binding"}:
        assert observed.status == "blocked" and observed.title is None
    else:
        assert observed.status == "valid" and observed.title is None and observed.warnings
