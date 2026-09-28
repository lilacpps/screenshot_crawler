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
