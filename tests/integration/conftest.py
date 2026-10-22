from __future__ import annotations

import pytest
import pytest_asyncio
from playwright.async_api import (
    Browser,
    BrowserContext,
    Error,
    Page,
    Playwright,
    async_playwright,
)

from screenshot_crawler.watchlist.reconcile import ScopeReconciler
from screenshot_crawler.watchlist.service import WatchlistService


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def integration_playwright() -> Playwright:
    playwright = await async_playwright().start()
    try:
        yield playwright
    finally:
        await playwright.stop()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def integration_browser(integration_playwright: Playwright) -> Browser:
    try:
        browser = await integration_playwright.chromium.launch(headless=True)
    except Error as exc:
        pytest.skip(f"Chromium is unavailable: {exc}")
    try:
        yield browser
    finally:
        await browser.close()


@pytest_asyncio.fixture(loop_scope="module")
async def browser_context(integration_browser: Browser) -> BrowserContext:
    context = await integration_browser.new_context()
    try:
        yield context
    finally:
        await context.close()


@pytest_asyncio.fixture(loop_scope="module")
async def browser_page(browser_context: BrowserContext) -> Page:
    page = await browser_context.new_page()
    try:
        yield page
    finally:
        await page.close()


@pytest.fixture
def sync_legacy_unscoped_work(tmp_path):
    """Create and explicitly sync an isolated Watchlist for legacy-style fixtures."""

    def sync(
        catalog,
        target=None,
        *,
        key: str | None = None,
        work_key: str | None = None,
        site: str | None = None,
        url: str | None = None,
        label: str = "Integration fixture",
    ):
        if target is not None:
            if target.discovery_scope is not None or target.archive_order is not None:
                raise AssertionError(
                    "legacy bootstrap fixture requires an unscoped, unordered target"
                )
            key, work_key, site, url, label = (
                target.key,
                target.work_key,
                target.site,
                target.url,
                target.label,
            )
        if None in (key, work_key, site, url):
            raise AssertionError("legacy bootstrap fixture requires a complete target identity")
        watchlist = WatchlistService(tmp_path / "watchlist.yaml")
        watchlist.add(
            key=key,
            work_key=work_key,
            site=site,
            url=url,
            label=label,
        )
        reconciler = ScopeReconciler(watchlist, catalog)
        preview = reconciler.preview(work_key)
        if not preview.ready:
            raise AssertionError(
                f"isolated unscoped fixture did not resolve safely: {preview.blockers}"
            )
        reconciler.apply(preview)
        return watchlist

    return sync
