from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
from playwright.async_api import Error, Route

from screenshot_crawler.cli import _discovery_registry
from screenshot_crawler.registration.resolver import UrlResolver

pytestmark = pytest.mark.asyncio(loop_scope="module")
URL = "https://piccoma.com/web/product/63/episodes"


def document(mode):
    canonical = "https://piccoma.com/web/product/64/episodes" if mode == "wrong_canonical" else URL
    header = "" if mode == "missing_canonical" else f'<link rel="canonical" href="{canonical}">'
    title = "" if mode == "missing_title" else '<h1 class="PCM-headTitle_name">人工作品</h1>'
    if mode == "duplicate_title":
        title *= 2
    count = "" if mode == "missing_count" else "全4話" if mode == "wrong_count" else "全3話"
    if mode == "duplicate_count":
        count *= 2
    classes = "PCM-list_desc" if mode == "wrong_order" else "PCM-list_asc"
    if mode == "ambiguous_order":
        classes += " PCM-list_desc"
    rows = []
    # DOM order deliberately differs from numeric episode ID order.
    for index, episode in enumerate(("700", "900", "100")):
        product = "64" if mode == "foreign_row" and index == 2 else "63"
        if mode == "duplicate_row" and index == 2:
            episode = "900"
        marker, label = ("PCM-epList_status_waitfree", "待てば¥0") if index == 0 else ("PCM-epList_status_free", "¥0")
        if mode == "paid_only" or mode == "skip_paid" and index == 1:
            marker, label = "PCM-epList_status_point js_point", "55"
        if mode == "quota_only":
            marker, label = "PCM-epList_status_waitfree", "待てば¥0"
        if mode == "granted_only":
            marker, label = "PCM-epList_status_waitfreeRead", "閲覧期限 残り23時間"
        if mode == "unknown_only":
            marker, label = "PCM-epList_status_unobserved", "¥0"
        if mode == "ambiguous_free" and index > 0:
            marker += " PCM-epList_status_waitfree"
        status = f'<div class="PCM-epList_status"><span class="{marker}">{label}</span></div>'
        if mode == "missing_status" and index == 2:
            status = ""
        if mode == "duplicate_status" and index == 2:
            status *= 2
        title_row = "" if mode == "missing_row_title" and index == 2 else '<span class="PCM-epList_title">人工話</span>'
        row = f'<a data-product_id="{product}" data-episode_id="{episode}"><div class="PCM-epList_ep">{title_row}{status}</div></a>'
        rows.append(row)
    listing = f'<div id="js_episodeList" class="{classes}">{"".join(rows)}</div>'
    if mode == "duplicate_list":
        listing *= 2
    body = f'<div id="js_contentBody">{title}{count}{listing}</div>'
    if mode == "no_list":
        body = '<div id="js_contentBody">全0話</div>'
    # These must never dispatch; reader-shaped anchor URLs are not visited either.
    return (header + body + '<img src="https://foreign.invalid/image">'
        '<iframe src="https://foreign.invalid/frame"></iframe>'
        '<script>fetch("https://foreign.invalid/post", {method:"POST"}).catch(()=>{});</script>').encode("utf-8")


@pytest.mark.parametrize("mode", [
    "ok", "missing_title", "duplicate_title", "skip_paid", "missing_canonical", "wrong_canonical",
    "missing_count", "wrong_count", "duplicate_count", "wrong_order", "ambiguous_order",
    "foreign_row", "duplicate_row", "paid_only", "quota_only", "granted_only", "unknown_only",
    "ambiguous_free", "missing_status", "duplicate_status", "missing_row_title", "duplicate_list",
    "no_list", "redirect", "http_error", "transport",
])
async def test_conversion_observes_one_work_document_and_never_opens_reader(browser_page, monkeypatch, mode):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302 if mode == "redirect" else 403 if mode == "http_error" else 200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            if mode == "redirect":
                self.send_header("Location", "https://piccoma.com/web/viewer/63/900")
            self.end_headers()
            self.wfile.write(document(mode))

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
            raise Error("synthetic transport error")
        return await fetch(route, url=f"http://127.0.0.1:{server.server_port}/", **kwargs)
    monkeypatch.setattr(Route, "fetch", upstream)
    resolver = UrlResolver(_discovery_registry())
    try:
        result = await resolver.observe_conversion(browser_page, resolver.resolve(URL))
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert requests == [("GET", URL)]
    if mode in {"ok", "missing_title", "duplicate_title", "skip_paid"}:
        assert result.status == "converted" and resolver.resolution_error(result) is None
        assert result.discovery_url == "https://piccoma.com/web/viewer/63/" + ("100" if mode == "skip_paid" else "900")
        assert result.conversion_proof.dom_index == (2 if mode == "skip_paid" else 1)
        assert result.conversion_proof.row_count == 3
        assert result.title == (None if mode in {"missing_title", "duplicate_title"} else "人工作品")
        assert result.input_url == URL and result.site_work_identity == "piccoma-product:63"
    else:
        assert result.status == "blocked" and result.conversion_proof is None
        assert result.discovery_url is None and result.site_work_identity is None
