"""Observation never releases a dedicated Page's guard before cleanup completes."""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
from playwright.async_api import Error, Route

from screenshot_crawler.core.browser import BrowserSession
from screenshot_crawler.registration.observation import (
    ObservationRejected,
    ObservationUnavailable,
    registration_document,
)

pytestmark = pytest.mark.asyncio(loop_scope="module")
URL = "https://piccoma.com/web/product/63/episodes"


@pytest.mark.parametrize("delay", [0, 20])
@pytest.mark.parametrize("error", [None, ObservationUnavailable, ObservationRejected, RuntimeError])
@pytest.mark.parametrize("cleanup_delay", [0, 0.1])
async def test_dedicated_page_cleanup_does_not_dispatch_delayed_post(
    browser_context, monkeypatch, delay, error, cleanup_delay,
):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<html><title>synthetic work document</title></html>")

        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    dispatched, escaped, fetch = [], [], Route.fetch

    async def upstream(route, **kwargs):
        dispatched.append((route.request.method, route.request.url))
        return await fetch(route, url=f"http://127.0.0.1:{server.server_port}/", **kwargs)

    async def catch_escape(route):
        # Page guard takes precedence; this catches any missing lifetime guard.
        escaped.append((route.request.method, route.request.url))
        try:
            await route.abort()
        except Error:
            pass  # A racing Page.close may have already ended this sentinel request.

    monkeypatch.setattr(Route, "fetch", upstream)
    await browser_context.route("**/*", catch_escape)
    session = BrowserSession(None, None, browser_context)
    page = await session.new_page()
    caught = None
    try:
        try:
            async with registration_document(page, URL):
                await page.evaluate("""delay => {
                    setTimeout(() => fetch('/delayed-registration-sentinel',
                        {method:'POST'}).catch(() => {}), delay);
                }""", delay)
                if error:
                    raise error("synthetic observer error")
        except (ObservationUnavailable, RuntimeError) as exc:
            caught = type(exc)
        finally:
            if cleanup_delay:
                await asyncio.sleep(cleanup_delay)
            # Zero delay uses the exact immediate BrowserSession cleanup of GUI.
            await session.close_page(page)
        assert page.is_closed()
        assert caught is error
        await asyncio.sleep(0.1)
    finally:
        if not page.is_closed():
            await page.close()
        await browser_context.unroute("**/*", catch_escape)
        server.shutdown()
        server.server_close()
        thread.join()
    assert dispatched == [("GET", URL)] and escaped == []
