
import pytest

from screenshot_crawler.cli import _discovery_registry
from screenshot_crawler.registration.resolver import UrlResolver

pytestmark = pytest.mark.asyncio(loop_scope="module")
URL = "https://comic-walker.com/detail/KC_004915_S"


@pytest.mark.parametrize("mode", ["ok", "missing", "multiple", "suffix", "auth",
    "cross_host", "other_work", "http_error", "timeout"])
async def test_detail_observation_is_restricted_and_non_consuming(browser_page, mode, monkeypatch):
    resolver = UrlResolver(_discovery_registry())
    dispatched = []
    from playwright.async_api import Route
    original_fetch = Route.fetch
    # A local route supplies the upstream document to Route.fetch; no public
    # network is used, while Page navigation/DOM/request guards are real.
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(503 if mode == "http_error" else 302 if mode in (
                "cross_host", "other_work", "auth") else 200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            if mode in ("cross_host", "other_work", "auth"):
                self.send_header("Location", "https://evil.test/")
            self.end_headers()
            title = '<meta property="og:title" content="人工作品｜カドコミ (コミックウォーカー)">'
            body = {"missing": "", "multiple": title * 2,
                "suffix": title.replace("カドコミ", "unknown")}.get(mode, title)
            self.wfile.write((body + '<img src="https://evil.test/image">').encode())
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    async def upstream(route, **kwargs):
        dispatched.append(route.request.url)
        assert kwargs["max_redirects"] == 0
        return await original_fetch(route, url=f"http://127.0.0.1:{server.server_port}/", **kwargs)
    monkeypatch.setattr(Route, "fetch", upstream)
    if mode == "timeout":
        from playwright.async_api import TimeoutError
        async def timeout(*args, **kwargs):
            raise TimeoutError("synthetic")
        monkeypatch.setattr(browser_page, "goto", timeout)
    try:
        result = await resolver.observe(browser_page, resolver.resolve(URL))
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    if mode == "ok":
        assert result.title == "人工作品" and result.title_status == "observed"
    elif mode in ("auth", "cross_host", "other_work"):
        assert result.status == "blocked"
    else:
        assert result.title is None and result.status == "valid"
    assert all(url == URL for url in dispatched)
