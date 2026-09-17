"""Command line entry point for crawl and probe."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from screenshot_crawler.auth.env import (
    read_env_file,
    require_site_env_value,
)
from screenshot_crawler.core.browser import (
    DEFAULT_CDP_ENDPOINT,
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
from screenshot_crawler.watchlist.service import WatchlistError, WatchlistService


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
        help=(
            "Attach to an existing Chromium browser, "
            f"for example {DEFAULT_CDP_ENDPOINT}"
        ),
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
    crawl.add_argument(
        "--access-strategy",
        choices=("auto", "direct", "quota"),
        default="auto",
        help="Site access intent (direct/quota require adapter support)",
    )
    crawl.add_argument("--title")
    crawl.add_argument("--author")
    crawl.add_argument("--order")
    crawl.add_argument("--genre")
    crawl.add_argument("--env-file", type=Path, default=Path(".env"))
    crawl.add_argument(
        "--cdp-endpoint",
        help=(
            "Attach to an existing Chromium browser "
            f"(default: site .env, CRAWLER_CDP_ENDPOINT, or {DEFAULT_CDP_ENDPOINT})"
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

    watch = subparsers.add_parser("watch", help="Manage Discovery watchlist targets")
    watch.add_argument(
        "--watchlist",
        type=Path,
        default=Path("watchlist.yaml"),
        help="Watchlist YAML path (default: watchlist.yaml)",
    )
    watch_subparsers = watch.add_subparsers(dest="watch_action", required=True)
    watch_list = watch_subparsers.add_parser("list", help="List watchlist targets")
    watch_list.add_argument("--watchlist", type=Path, default=argparse.SUPPRESS)

    watch_add = watch_subparsers.add_parser("add", help="Add a watchlist target")
    watch_add.add_argument("--watchlist", type=Path, default=argparse.SUPPRESS)
    watch_add.add_argument("--key", required=True)
    watch_add.add_argument("--site", required=True)
    watch_add.add_argument("--url", required=True)
    watch_add.add_argument("--label")

    for action in ("remove", "enable", "disable"):
        action_parser = watch_subparsers.add_parser(action)
        action_parser.add_argument("--watchlist", type=Path, default=argparse.SUPPRESS)
        action_parser.add_argument("--key", required=True)
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
        access_strategy=args.access_strategy,
        output_metadata={
            field_name: value
            for field_name, value in (
                ("title", args.title),
                ("author", args.author),
                ("order", args.order),
                ("genre", args.genre),
            )
            if value is not None
        },
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
                    explicit_metadata=config.output_metadata,
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
    page = None
    try:
        page = await session.new_page()
        await login(page, email=email, password=password, home_url=home_url)
        print(f"Login submitted for site '{args.site}'. Credentials were not printed.")
        if args.keep_open:
            print("Browser is open. Press Enter here to disconnect.")
            await asyncio.to_thread(input)
    finally:
        if page is not None:
            await session.close_page(page)
        await session.close()


def _run_watch(args: argparse.Namespace) -> None:
    service = WatchlistService(args.watchlist)
    if args.watch_action == "list":
        targets = service.list_targets()
        if not targets:
            print("No watchlist targets.")
            return
        for target in targets:
            enabled = "enabled" if target.enabled else "disabled"
            label = f"\t{target.label}" if target.label is not None else ""
            print(f"{target.key}\t{target.site}\t{enabled}\t{target.url}{label}")
    elif args.watch_action == "add":
        target = service.add(
            key=args.key,
            site=args.site,
            url=args.url,
            label=args.label,
        )
        print(f"Added watchlist target '{target.key}'.")
    elif args.watch_action == "remove":
        removed = service.remove(args.key)
        print(f"Removed watchlist target '{removed.key}'.")
    elif args.watch_action == "enable":
        service.enable(args.key)
        print(f"Enabled watchlist target '{args.key}'.")
    elif args.watch_action == "disable":
        service.disable(args.key)
        print(f"Disabled watchlist target '{args.key}'.")


def main() -> None:
    args = _parser().parse_args()
    try:
        if args.command == "probe":
            asyncio.run(_run_probe(args))
        elif args.command == "crawl":
            asyncio.run(_run_crawl(args))
        elif args.command == "login":
            asyncio.run(_run_login(args))
        elif args.command == "watch":
            _run_watch(args)
    except WatchlistError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
