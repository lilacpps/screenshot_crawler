"""Shared Playwright browser lifecycle and authenticated context creation."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from playwright.async_api import Browser, BrowserContext, async_playwright

from screenshot_crawler.auth.env import env_value, site_env_name
from screenshot_crawler.auth.storage import (
    AUTH_STATE_NOT_FOUND_MESSAGE,
    AuthenticationStateNotFoundError,
    auth_state_path,
    require_auth_state,
)

DEFAULT_CDP_ENDPOINT = "http://127.0.0.1:9222"
_CLEANUP_TIMEOUT_SECONDS = 5


def resolve_cdp_endpoint(
    *,
    site: str | None = None,
    cli_endpoint: str | None = None,
    values: Mapping[str, str] | None = None,
) -> str:
    """Resolve a real-site CDP endpoint using the shared precedence policy."""

    if cli_endpoint:
        return cli_endpoint

    env_values = dict(values or {})
    if site is not None:
        site_endpoint = env_value(
            site_env_name(site, "CDP_ENDPOINT"),
            env_values,
        )
        if site_endpoint:
            return site_endpoint

    return env_value(
        "CRAWLER_CDP_ENDPOINT",
        env_values,
        default=DEFAULT_CDP_ENDPOINT,
    ) or DEFAULT_CDP_ENDPOINT


async def launch_browser(
    *,
    headless: bool = True,
    start_maximized: bool = False,
) -> tuple[Any, Browser]:
    """Start Playwright and Chromium.

    The returned Playwright manager must be stopped by the caller after the
    browser is closed. ``headless=False`` is intended for manual login and
    interactive probing.
    """

    playwright = await async_playwright().start()
    try:
        launch_options: dict[str, Any] = {"headless": headless}
        if start_maximized and not headless:
            launch_options["args"] = ["--start-maximized"]
        browser = await playwright.chromium.launch(**launch_options)
    except BaseException:
        await playwright.stop()
        raise
    return playwright, browser


async def connect_browser(endpoint: str) -> tuple[Any, Browser]:
    """Attach to an already-running Chromium browser over CDP.

    This is intended for a manually logged-in, dedicated Chrome profile. The
    returned Browser is remote-owned, so callers must disconnect without
    closing that browser process.
    """

    playwright = await async_playwright().start()
    try:
        browser = await playwright.chromium.connect_over_cdp(endpoint)
    except BaseException:
        await playwright.stop()
        raise
    return playwright, browser


class BrowserSession:
    """Own a Playwright connection to an already-running crawler Chrome.

    The session owns the Playwright connection and any pages it creates, but
    never owns or closes the remote Chrome process itself.
    """

    def __init__(self, playwright: Any, browser: Browser, context: BrowserContext) -> None:
        self.playwright = playwright
        self.browser = browser
        self.context = context

    @classmethod
    async def connect(cls, endpoint: str) -> BrowserSession:
        """Connect to CDP and select the existing remote browser context."""

        playwright, browser = await connect_browser(endpoint)
        try:
            context = default_browser_context(browser)
        except BaseException:
            await close_browser(playwright, browser, close_browser_instance=False)
            raise
        return cls(playwright, browser, context)

    async def new_page(self) -> Any:
        """Create a page for a crawl or site-specific login handler."""

        return await self.context.new_page()

    async def close_page(self, page: Any) -> None:
        """Close a work page without affecting the remote browser."""

        task = asyncio.create_task(page.close())
        try:
            await asyncio.wait_for(
                asyncio.shield(task), timeout=_CLEANUP_TIMEOUT_SECONDS
            )
        except TimeoutError:
            if not task.done():
                task.cancel()
        except (KeyboardInterrupt, asyncio.CancelledError):
            if not task.done():
                task.cancel()
            raise
        except BaseException:  # noqa: BLE001 - cleanup must not replace the run error
            if not task.done():
                task.cancel()

    async def close(self) -> None:
        """Disconnect Playwright while leaving remote Chrome running."""

        await close_browser(self.playwright, self.browser, close_browser_instance=False)


def default_browser_context(browser: Browser) -> BrowserContext:
    """Return the existing context of a CDP-connected Chromium browser."""

    contexts = browser.contexts
    if not contexts:
        raise RuntimeError(
            "Connected Chromium has no browser context. "
            "Open a tab in the browser and try again."
        )
    return contexts[0]


async def create_browser_context(
    browser: Browser,
    *,
    site: str | None = None,
    auth_state: str | Path | None = None,
    auth_required: bool = False,
    auth_dir: str | Path = Path(".auth"),
    viewport_width: int = 1920,
    viewport_height: int = 1080,
    device_scale_factor: float = 1.0,
    no_viewport: bool = False,
    **context_options: Any,
) -> BrowserContext:
    """Create a BrowserContext, optionally reusing saved auth state.

    Callers can provide an explicit ``auth_state`` path, or provide ``site``
    to use ``.auth/<site>.json``. When ``auth_required`` is true, one of
    those must resolve to an existing file. The file contents are passed
    directly to Playwright and are never logged by this package.
    """

    state_path: Path | None = None
    if auth_state is not None:
        state_path = Path(auth_state)
        if not state_path.is_file():
            raise AuthenticationStateNotFoundError(AUTH_STATE_NOT_FOUND_MESSAGE)
    elif auth_required:
        if site is None:
            raise ValueError("site is required when auth_required is true")
        state_path = require_auth_state(site, auth_dir=auth_dir)
    elif site is not None:
        candidate = auth_state_path(site, auth_dir=auth_dir)
        if candidate.is_file():
            state_path = candidate

    options: dict[str, Any] = {**context_options}
    if no_viewport:
        options["no_viewport"] = True
    else:
        options.update(
            {
                "viewport": {"width": viewport_width, "height": viewport_height},
                "device_scale_factor": device_scale_factor,
            }
        )
    if state_path is not None:
        options["storage_state"] = str(state_path)
    return await browser.new_context(**options)


async def close_browser(
    playwright: Any,
    browser: Browser,
    *,
    close_browser_instance: bool = True,
) -> None:
    """Close or disconnect Chromium and stop its Playwright manager.

    A CDP-connected browser belongs to the user, so pass
    ``close_browser_instance=False`` to disconnect without closing Chrome.
    """

    if close_browser_instance:
        try:
            await asyncio.wait_for(browser.close(), timeout=5)
        except (KeyboardInterrupt, asyncio.CancelledError):
            raise
        except BaseException:  # noqa: BLE001, S110
            pass
    try:
        await asyncio.wait_for(playwright.stop(), timeout=5)
    except (KeyboardInterrupt, asyncio.CancelledError):
        raise
    except BaseException:  # noqa: BLE001, S110
        pass
