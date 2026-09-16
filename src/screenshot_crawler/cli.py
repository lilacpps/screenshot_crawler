"""Command line entry point for crawl and probe."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from screenshot_crawler.auth.env import (
    read_env_file,
    require_site_env_value,
)
from screenshot_crawler.core.browser import (
    BrowserSession,
    close_browser,
    connect_browser,
    create_browser_context,
    default_browser_context,
    launch_browser,
    resolve_cdp_endpoint,
)
from screenshot_crawler.core.models import RunConfig
from screenshot_crawler.core.packaging import package_crawl_output
from screenshot_crawler.core.progress import normalize_path
from screenshot_crawler.core.runner import CrawlerRunner
from screenshot_crawler.core.state import PageState
from screenshot_crawler.probe.collector import ProbeCollector
from screenshot_crawler.site_adapters.registry import AdapterRegistry


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="screenshot-crawler")
    subparsers = parser.add_subparsers(dest="command", required=True)

    probe = subparsers.add_parser("probe")
    probe.add_argument("--url", required=True)
    probe.add_argument("--output-dir", type=Path, default=Path("output/probe"))
    probe.add_argument("--site")
    probe.add_argument("--auth-state", type=Path)
    probe.add_argument("--auth-required", action="store_true")
    probe.add_argument("--headed", action="store_true")
    probe.add_argument(
        "--cdp-endpoint",
        help="Attach to an existing Chromium browser, for example http://127.0.0.1:9222",
    )
    probe.add_argument(
        "--native-window",
        action="store_true",
        help="In headed mode, maximize Chromium and use its native viewport",
    )
    probe.add_argument(
        "--keep-open",
        action="store_true",
        help="Keep the headed browser open until Enter is pressed",
    )

    crawl = subparsers.add_parser("crawl")
    crawl.add_argument("--site", required=True)
    crawl.add_argument("--url", required=True)
    crawl.add_argument("--output-dir", type=Path, default=Path("output/crawl"))
    crawl.add_argument("--diagnostics-dir", type=Path)
    crawl.add_argument(
        "--library-dir",
        type=Path,
        default=Path("output/Books"),
        help="Root directory for completed ZIP archives (default: output/Books)",
    )
    crawl.add_argument("--max-pages", type=int, default=1000)
    crawl.add_argument("--max-same-content", type=int, default=3)
    crawl.add_argument("--env-file", type=Path, default=Path(".env"))
    crawl.add_argument(
        "--cdp-endpoint",
        help=(
            "Attach to an existing Chromium browser "
            "(default: site .env, CRAWLER_CDP_ENDPOINT, or http://127.0.0.1:9222)"
        ),
    )
    crawl.add_argument(
        "--keep-open",
        action="store_true",
        help="Keep the connected browser open until Enter is pressed",
    )

    login = subparsers.add_parser(
        "login",
        help="Log in to a site using credentials from a local .env file",
    )
    login.add_argument("--site", required=True)
    login.add_argument("--env-file", type=Path, default=Path(".env"))
    login.add_argument("--cdp-endpoint")
    login.add_argument(
        "--keep-open",
        action="store_true",
        help="Keep the connected browser open until Enter is pressed",
    )
    return parser


def _registry() -> AdapterRegistry:
    registry = AdapterRegistry()
    from screenshot_crawler.site_adapters.bookwalker import BookWalkerAdapter
    from screenshot_crawler.site_adapters.mangaone import MangaOneAdapter

    registry.register("bookwalker", BookWalkerAdapter)
    registry.register("mangaone", MangaOneAdapter)
    return registry


async def _run_probe(args: argparse.Namespace) -> None:
    if args.cdp_endpoint and (args.auth_state or args.auth_required):
        raise ValueError("--cdp-endpoint cannot be combined with auth state options")

    remote_browser = bool(args.cdp_endpoint)
    if remote_browser:
        playwright, browser = await connect_browser(args.cdp_endpoint)
        try:
            context = default_browser_context(browser)
        except BaseException:
            await close_browser(playwright, browser, close_browser_instance=False)
            raise
    else:
        playwright, browser = await launch_browser(
            headless=not args.headed,
            start_maximized=args.native_window,
        )
        try:
            context = await create_browser_context(
                browser,
                site=args.site,
                auth_state=args.auth_state,
                auth_required=args.auth_required,
                no_viewport=args.native_window and args.headed,
            )
        except BaseException:
            await close_browser(playwright, browser)
            raise
    try:
        page = await context.new_page()
        try:
            await page.goto(args.url, wait_until="commit", timeout=10_000)
        except PlaywrightTimeoutError:
            # A viewer can keep navigation open while it establishes a long-lived
            # connection. Probe the partially loaded page instead of discarding
            # the observations already available in the DOM.
            print("Navigation timed out; collecting the partially loaded page.")
        output_dir = normalize_path(args.output_dir)
        result = await ProbeCollector().collect(page, output_dir)
        print(f"Probe saved to {output_dir}")
        print(f"URL: {result.url}")
        print(f"Title: {result.title}")
        if args.keep_open:
            print("Browser is open. Inspect it manually, then press Enter here to close it.")
            await asyncio.to_thread(input)
    finally:
        await close_browser(
            playwright,
            browser,
            close_browser_instance=not remote_browser,
        )


async def _run_crawl(args: argparse.Namespace) -> None:
    registry = _registry()
    adapter = registry.create(args.site)
    output_dir = normalize_path(args.output_dir)
    diagnostics_dir = (
        normalize_path(args.diagnostics_dir)
        if args.diagnostics_dir
        else output_dir / "diagnostics"
    )
    library_dir = normalize_path(args.library_dir)
    config = RunConfig(
        site=args.site,
        source_url=args.url,
        output_dir=output_dir,
        diagnostics_dir=diagnostics_dir,
        max_pages=args.max_pages,
        max_same_content=args.max_same_content,
    )

    values = read_env_file(args.env_file) if args.env_file.is_file() else {}
    endpoint = resolve_cdp_endpoint(
        site=args.site,
        cli_endpoint=args.cdp_endpoint,
        values=values,
    )
    session = await BrowserSession.connect(endpoint)
    try:
        page = await session.new_page()
        try:
            result = await CrawlerRunner(config).run(page, adapter)
            print(f"Saved {len(result.pages)} pages; stopped at {result.stop_reason}.")
            if result.stop_state in {PageState.END, PageState.NEXT_CONTENT}:
                package = package_crawl_output(
                    output_dir,
                    adapter.get_output_metadata(),
                    library_dir=library_dir,
                )
                print(f"Archive saved to {package.archive_path}")
                print(f"Completion status saved to {package.status_path}")
        except BaseException:
            if args.keep_open:
                print("Browser is open. Inspect it manually, then press Enter here to close it.")
                await asyncio.to_thread(input)
            raise
        else:
            if args.keep_open:
                print("Browser is open. Inspect it manually, then press Enter here to close it.")
                await asyncio.to_thread(input)
        finally:
            await session.close_page(page)
    finally:
        await session.close()


async def _run_login(args: argparse.Namespace) -> None:
    """Connect to the existing CDP browser and perform site login."""

    values = read_env_file(args.env_file)
    endpoint = resolve_cdp_endpoint(
        site=args.site,
        cli_endpoint=args.cdp_endpoint,
        values=values,
    )
    email = require_site_env_value(args.site, "EMAIL", values)
    password = require_site_env_value(args.site, "PASSWORD", values)
    home_url = require_site_env_value(args.site, "URL", values)

    adapter = _registry().create(args.site)
    login = getattr(adapter, "login", None)
    if login is None:
        raise ValueError(f"Site adapter '{args.site}' does not provide a login flow")

    session = await BrowserSession.connect(endpoint)
    page = session.existing_page()
    page_created = page is None
    try:
        if page is None:
            page = await session.new_page()
        await login(page, email=email, password=password, home_url=home_url)
        print(f"Login submitted for site '{args.site}'. Credentials were not printed.")
        if args.keep_open:
            print("Browser is open. Press Enter here to disconnect.")
            await asyncio.to_thread(input)
    finally:
        if page_created and page is not None:
            await session.close_page(page)
        await session.close()


def main() -> None:
    args = _parser().parse_args()
    if args.command == "probe":
        asyncio.run(_run_probe(args))
    elif args.command == "crawl":
        asyncio.run(_run_crawl(args))
    elif args.command == "login":
        asyncio.run(_run_login(args))


if __name__ == "__main__":
    main()
