"""Artificial first-party listing with real DOM and browser HTTP routing."""

import json
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

from screenshot_crawler.site_adapters.comicdays.discovery import ComicDaysDiscoveryAdapter
from screenshot_crawler.watchlist import DiscoveryScope, WatchlistTarget
from tests.unit.test_comicdays_discovery import _row

pytestmark = pytest.mark.asyncio(loop_scope="module")


class _BrowserPage:
    """Route read-only request calls through the fixture browser's HTTP stack."""

    def __init__(self, page):
        self.page = page
        self.request = SimpleNamespace(get=self.get)

    def __getattr__(self, name):
        return getattr(self.page, name)

    async def get(self, url, **_kwargs):
        result = await self.page.evaluate("""async url => {
          const response = await fetch(url, {signal: AbortSignal.timeout(3000)});
          return {status: response.status, text: await response.text()};
        }""", url)

        async def body():
            return result["text"].encode("utf-8")

        return SimpleNamespace(status=result["status"], body=body)


@pytest.mark.parametrize("incomplete", [False, True])
async def test_comicdays_preview_validates_dom_feeds_and_replays_without_http(browser_page, incomplete):
    requests = []
    ids = ["4", "3", "2", "1"]
    feed = '<feed xmlns="http://www.w3.org/2005/Atom"><id>https://comic-days.com/atom/series/42</id>'
    feed += "".join(
        f'<entry><id>tag:fixture:episode:{i}</id><title>第{i}話</title>'
        f'<link href="https://comic-days.com/episode/{i}"/></entry>' for i in ids
    ) + "</feed>"

    async def route_request(route):
        assert route.request.method == "GET"
        requests.append(route.request.url)
        path = urlparse(route.request.url).path
        if path == "/episode/1":
            content_type = "text/html; charset=utf-8"
            body = '<html data-giga_series="42"><h1 class="series-header-title">Synthetic work</h1></html>'
        elif path == "/atom/series/42":
            content_type, body = "application/atom+xml; charset=utf-8", feed
        elif path == "/api/viewer/readable_product_pagination_information":
            content_type, body = "application/json", json.dumps({"total_count": 4})
        elif path == "/api/viewer/pagination_readable_products":
            content_type = "application/json"
            body = json.dumps([_row(i, free=True) for i in (ids[:-1] if incomplete else ids)])
        else:
            pytest.fail(f"Unexpected listing route: {path}")
        await route.fulfill(status=200, content_type=content_type, body=body)

    await browser_page.route("**/*", route_request)
    page = _BrowserPage(browser_page)
    target = WatchlistTarget("comic", "work", "comicdays", "https://comic-days.com/episode/1", "Synthetic work",
                             discovery_scope=DiscoveryScope(excluded_external_ids=("2", "3")))
    adapter = ComicDaysDiscoveryAdapter()
    if incomplete:
        from screenshot_crawler.discovery import DiscoveryIncompleteError

        with pytest.raises(DiscoveryIncompleteError, match="incomplete"):
            await adapter.preview_complete_listing(page, target)
        assert adapter.complete_listing_inventory is None
        return
    preview = await adapter.preview_complete_listing(page, target)
    assert preview.ready
    assert [row.external_id for row in preview.rows] == ids
    assert [row.site_position for row in preview.rows] == [4, 3, 2, 1]
    assert preview.listing_identity == "comicdays-series:42"
    assert adapter.complete_listing_inventory is None
    await adapter.prepare_exclusion_preview(page, target)
    before = list(requests)
    rows = [record async for record in adapter.iter_records(page, target, "full")]
    assert requests == before
    assert [record.source.external_id for record in rows] == ["4", "1"]
    assert [position.in_scope for position in adapter.complete_listing_inventory.positions] == [True, False, False, True]
