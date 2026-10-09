"""Command line entry point for crawl and probe."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from collections.abc import Awaitable
from pathlib import Path
from typing import Any

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from screenshot_crawler.auth.env import (
    env_value,
    read_env_file,
    require_site_env_value,
)
from screenshot_crawler.batch import (
    BatchCandidate,
    BatchExecutionError,
    BatchExecutor,
    BatchInterruptedError,
    BatchPlan,
    BatchPlanner,
    BatchPlanningError,
    CandidateExecutionError,
)
from screenshot_crawler.batch.metrics import BatchMetricsWriter
from screenshot_crawler.catalog import CatalogError, CatalogService
from screenshot_crawler.catalog.backup import backup_catalog, default_backup_path
from screenshot_crawler.catalog.export import export_catalog_csv
from screenshot_crawler.catalog.migrations import migrate_catalog
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
from screenshot_crawler.core.errors import AccessResourceUnavailableError, AccessStopError
from screenshot_crawler.core.models import RunConfig
from screenshot_crawler.core.packaging import package_crawl_output
from screenshot_crawler.core.progress import normalize_path
from screenshot_crawler.core.runner import CrawlerRunner
from screenshot_crawler.core.state import PageState
from screenshot_crawler.discovery import (
    DiscoveryAdapterRegistry,
    DiscoveryIncompleteError,
    DiscoveryService,
)
from screenshot_crawler.discovery.models import DiscoveredRecord, DiscoveryResult
from screenshot_crawler.probe.collector import ProbeCollector
from screenshot_crawler.runtime_settings import load_runtime_settings
from screenshot_crawler.site_adapters.registry import AdapterRegistry
from screenshot_crawler.site_policies import (
    BookWalkerSitePolicy,
    JumpPlusSitePolicy,
    MagapokeSitePolicy,
    MangaOneSitePolicy,
    PiccomaSitePolicy,
    SitePolicyRegistry,
    ZeblackSitePolicy,
)
from screenshot_crawler.site_policies.base import SitePolicyError
from screenshot_crawler.watchlist.models import WatchlistTarget
from screenshot_crawler.watchlist.service import WatchlistError, WatchlistService


class DiscoveryAllError(RuntimeError):
    """Raised after a multi-target Discovery run has one or more failures."""

    def __init__(self, failures: list[tuple[str, str]], total: int) -> None:
        self.failures = tuple(failures)
        self.total = total
        super().__init__(
            f"Discovery failed for {len(self.failures)} of {self.total} targets"
        )


class EpisodeListError(RuntimeError):
    """Raised when the read-only episode-list helper cannot complete safely."""


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return parsed


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
        "--crawler-config",
        type=Path,
        default=Path("crawler.yaml"),
        help="Runtime settings YAML path (default: crawler.yaml)",
    )
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

    discover = subparsers.add_parser(
        "discover",
        help="Synchronize Watchlist targets into the Catalog",
    )
    target_group = discover.add_mutually_exclusive_group(required=True)
    target_group.add_argument("--key")
    target_group.add_argument(
        "--site",
        help="Synchronize all enabled Watchlist targets for this site",
    )
    target_group.add_argument(
        "--all",
        action="store_true",
        help="Synchronize all enabled Watchlist targets in file order",
    )
    discover.add_argument("--mode", choices=("full", "incremental"), required=True)
    discover.add_argument(
        "--watchlist",
        type=Path,
        default=Path("watchlist.yaml"),
        help="Watchlist YAML path (default: watchlist.yaml)",
    )
    discover.add_argument(
        "--catalog",
        type=Path,
        default=Path("catalog.sqlite"),
        help="Catalog SQLite path (default: catalog.sqlite)",
    )
    discover.add_argument("--env-file", type=Path, default=Path(".env"))
    discover.add_argument(
        "--cdp-endpoint",
        help=(
            "Attach to an existing Chromium browser "
            f"(default: site .env, CRAWLER_CDP_ENDPOINT, or {DEFAULT_CDP_ENDPOINT})"
        ),
    )
    discover.add_argument(
        "--keep-open",
        action="store_true",
        help="Keep the connected browser open until Enter is pressed",
    )

    episode_list = subparsers.add_parser(
        "episode-list",
        help="List episodes from a Zeblack or Jump+ page without Catalog writes",
    )
    episode_list.add_argument("--url", required=True)
    episode_list.add_argument(
        "--contains",
        action="append",
        default=[],
        metavar="TEXT",
        help="Show rows whose order key or visible title contains TEXT (repeatable, OR)",
    )
    episode_list.add_argument("--env-file", type=Path, default=Path(".env"))
    episode_list.add_argument(
        "--cdp-endpoint",
        help=(
            "Attach to an existing Chromium browser "
            f"(default: CRAWLER_CDP_ENDPOINT or {DEFAULT_CDP_ENDPOINT})"
        ),
    )
    episode_list.add_argument(
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
    watch_add.add_argument("--work-key", required=True)
    watch_add.add_argument("--site", required=True)
    watch_add.add_argument("--url", required=True)
    watch_add.add_argument("--label", required=True)

    for action in ("remove", "enable", "disable"):
        action_parser = watch_subparsers.add_parser(action)
        action_parser.add_argument("--watchlist", type=Path, default=argparse.SUPPRESS)
        action_parser.add_argument("--key", required=True)

    catalog = subparsers.add_parser("catalog", help="Manage and inspect Catalog data")
    catalog_subparsers = catalog.add_subparsers(dest="catalog_action", required=True)
    catalog_export = catalog_subparsers.add_parser(
        "export", help="Export Catalog items and sources as a CSV snapshot"
    )
    catalog_export.add_argument(
        "--catalog",
        type=Path,
        default=Path("catalog.sqlite"),
        help="Catalog SQLite path (default: catalog.sqlite)",
    )
    catalog_export.add_argument(
        "--output-dir",
        type=Path,
        default=Path("catalog-export"),
        help="Directory for six CSV snapshots (default: catalog-export)",
    )
    catalog_backup = catalog_subparsers.add_parser(
        "backup", help="Create a schema-neutral SQLite backup"
    )
    catalog_backup.add_argument(
        "--catalog",
        type=Path,
        default=Path("catalog.sqlite"),
        help="Catalog SQLite path (default: catalog.sqlite)",
    )
    catalog_backup.add_argument(
        "--output",
        type=Path,
        help="Backup SQLite path (default: backup/<catalog>-backup-<JST timestamp>.sqlite)",
    )
    catalog_migrate = catalog_subparsers.add_parser(
        "migrate", help="Explicitly migrate Catalog to the current schema"
    )
    catalog_migrate.add_argument(
        "--catalog",
        type=Path,
        default=Path("catalog.sqlite"),
        help="Catalog SQLite path (default: catalog.sqlite)",
    )
    catalog_migrate.add_argument(
        "--backup-dir",
        type=Path,
        default=Path("backup"),
        help="Directory for the automatic pre-migration backup (default: backup)",
    )
    catalog_item_status = catalog_subparsers.add_parser(
        "item-status", help="Show or change a Catalog item's Batch status"
    )
    catalog_item_status.add_argument("item_id", type=_positive_int)
    catalog_item_status.add_argument(
        "status", nargs="?", choices=("pending", "completed", "skipped", "external")
    )
    catalog_item_status.add_argument(
        "--catalog",
        type=Path,
        default=Path("catalog.sqlite"),
        help="Catalog SQLite path (default: catalog.sqlite)",
    )
    catalog_item_note = catalog_subparsers.add_parser(
        "item-note", help="Show or change a Catalog item's operator note"
    )
    catalog_item_note.add_argument("item_id", type=_positive_int)
    note_group = catalog_item_note.add_mutually_exclusive_group()
    note_group.add_argument("note", nargs="?", help="New note text")
    note_group.add_argument("--clear", action="store_true", help="Clear the note")
    catalog_item_note.add_argument(
        "--catalog",
        type=Path,
        default=Path("catalog.sqlite"),
        help="Catalog SQLite path (default: catalog.sqlite)",
    )

    batch = subparsers.add_parser("batch", help="Plan or execute Catalog crawl candidates")
    batch_subparsers = batch.add_subparsers(dest="batch_action", required=True)
    batch_plan = batch_subparsers.add_parser(
        "plan", help="Create a read-only Batch Plan without crawling"
    )
    batch_plan.add_argument("--site", required=True)
    batch_plan.add_argument(
        "--catalog",
        type=Path,
        default=Path("catalog.sqlite"),
        help="Catalog SQLite path (default: catalog.sqlite)",
    )
    batch_run = batch_subparsers.add_parser(
        "run", help="Execute the planned candidates sequentially"
    )
    batch_run.add_argument("--site", required=True)
    batch_run.add_argument(
        "--catalog",
        type=Path,
        default=Path("catalog.sqlite"),
        help="Catalog SQLite path (default: catalog.sqlite)",
    )
    batch_run.add_argument(
        "--output-root",
        type=Path,
        default=Path("output/batch"),
        help="Root directory for candidate crawl runs (default: output/batch)",
    )
    batch_run.add_argument(
        "--library-dir",
        type=Path,
        default=Path("output/Books"),
        help="Root directory for completed ZIP archives (default: output/Books)",
    )
    batch_run.add_argument("--env-file", type=Path, default=Path(".env"))
    batch_run.add_argument(
        "--crawler-config",
        type=Path,
        default=Path("crawler.yaml"),
        help="Runtime settings YAML path (default: crawler.yaml)",
    )
    batch_run.add_argument("--cdp-endpoint")
    batch_run.add_argument(
        "--limit",
        type=_positive_int,
        help="Execute only the first N planned candidates (N >= 1)",
    )
    batch_run.add_argument(
        "--grant-only",
        metavar="RESOURCE",
        help="Confirm an explicit access grant without capturing content",
    )
    batch_run.add_argument("--max-pages", type=int, default=1000)
    batch_run.add_argument("--max-same-content", type=int, default=3)
    batch_run.add_argument(
        "--keep-open",
        action="store_true",
        help="Keep the connected browser open until Enter is pressed",
    )
    return parser


def _registry() -> AdapterRegistry:
    registry = AdapterRegistry()
    from screenshot_crawler.site_adapters.bookwalker import BookWalkerAdapter
    from screenshot_crawler.site_adapters.comicdays import ComicDaysAdapter
    from screenshot_crawler.site_adapters.jumpplus import JumpPlusAdapter
    from screenshot_crawler.site_adapters.magapoke import MagapokeAdapter
    from screenshot_crawler.site_adapters.mangaone import MangaOneAdapter
    from screenshot_crawler.site_adapters.piccoma import PiccomaAdapter
    from screenshot_crawler.site_adapters.zeblack import ZeblackAdapter

    registry.register("bookwalker", BookWalkerAdapter)
    registry.register("jumpplus", JumpPlusAdapter)
    registry.register("magapoke", MagapokeAdapter)
    registry.register("mangaone", MangaOneAdapter)
    registry.register("zeblack", ZeblackAdapter)
    registry.register("comicdays", ComicDaysAdapter)
    registry.register("piccoma", PiccomaAdapter)
    return registry


def _batch_adapter_registry(values: dict[str, str]) -> AdapterRegistry:
    """Build the Batch registry with BookWalker-only site-local credentials."""

    registry = AdapterRegistry()
    from screenshot_crawler.site_adapters.bookwalker import BookWalkerAdapter
    from screenshot_crawler.site_adapters.comicdays import ComicDaysAdapter
    from screenshot_crawler.site_adapters.jumpplus import JumpPlusAdapter
    from screenshot_crawler.site_adapters.magapoke import MagapokeAdapter
    from screenshot_crawler.site_adapters.mangaone import MangaOneAdapter
    from screenshot_crawler.site_adapters.piccoma import PiccomaAdapter
    from screenshot_crawler.site_adapters.zeblack import ZeblackAdapter

    registry.register(
        "bookwalker",
        lambda: BookWalkerAdapter(
            auto_login_email=env_value("BOOKWALKER_EMAIL", values),
            auto_login_password=env_value("BOOKWALKER_PASSWORD", values),
        ),
    )
    registry.register("jumpplus", JumpPlusAdapter)
    registry.register("magapoke", MagapokeAdapter)
    registry.register("mangaone", MangaOneAdapter)
    registry.register("zeblack", ZeblackAdapter)
    registry.register("comicdays", ComicDaysAdapter)
    registry.register("piccoma", PiccomaAdapter)
    return registry


def _discovery_registry() -> DiscoveryAdapterRegistry:
    """Build the Discovery registry separately from viewer adapters."""

    from screenshot_crawler.site_adapters.bookwalker import BookWalkerDiscoveryAdapter
    from screenshot_crawler.site_adapters.comicdays import ComicDaysDiscoveryAdapter
    from screenshot_crawler.site_adapters.jumpplus import JumpPlusDiscoveryAdapter
    from screenshot_crawler.site_adapters.magapoke import MagapokeDiscoveryAdapter
    from screenshot_crawler.site_adapters.mangaone import MangaOneDiscoveryAdapter
    from screenshot_crawler.site_adapters.piccoma import PiccomaDiscoveryAdapter
    from screenshot_crawler.site_adapters.zeblack import ZeblackDiscoveryAdapter

    registry = DiscoveryAdapterRegistry()
    registry.register("bookwalker", BookWalkerDiscoveryAdapter)
    registry.register("jumpplus", JumpPlusDiscoveryAdapter)
    registry.register("magapoke", MagapokeDiscoveryAdapter)
    registry.register("mangaone", MangaOneDiscoveryAdapter)
    registry.register("piccoma", PiccomaDiscoveryAdapter)
    registry.register("zeblack", ZeblackDiscoveryAdapter)
    registry.register("comicdays", ComicDaysDiscoveryAdapter)
    return registry


def _batch_policy_registry() -> SitePolicyRegistry:
    registry = SitePolicyRegistry()
    registry.register("bookwalker", BookWalkerSitePolicy)
    registry.register("jumpplus", JumpPlusSitePolicy)
    registry.register("magapoke", MagapokeSitePolicy)
    registry.register("mangaone", MangaOneSitePolicy)
    registry.register("zeblack", ZeblackSitePolicy)
    from screenshot_crawler.site_policies.comicdays import ComicDaysSitePolicy
    registry.register("comicdays", ComicDaysSitePolicy)
    registry.register("piccoma", PiccomaSitePolicy)
    return registry


def _episode_list_site(url: str) -> str:
    """Identify one of the two supported episode-list input URL shapes."""

    from screenshot_crawler.site_adapters.jumpplus import parse_jumpplus_episode_url
    from screenshot_crawler.site_adapters.zeblack import parse_zeblack_chapter_list_url

    if parse_zeblack_chapter_list_url(url) is not None:
        return "zeblack"
    if parse_jumpplus_episode_url(url) is not None:
        return "jumpplus"
    raise EpisodeListError(
        "Unsupported episode-list URL; expected a Zeblack chapter-list URL "
        "or a Jump+ episode URL"
    )


def _episode_list_adapter(site: str) -> Any:
    """Create only the site Discovery adapter supported by episode-list."""

    if site == "zeblack":
        from screenshot_crawler.site_adapters.zeblack import ZeblackDiscoveryAdapter

        return ZeblackDiscoveryAdapter()
    if site == "jumpplus":
        from screenshot_crawler.site_adapters.jumpplus import JumpPlusDiscoveryAdapter

        return JumpPlusDiscoveryAdapter()
    raise EpisodeListError(f"Unsupported episode-list site: {site}")


def _episode_list_target(site: str, url: str) -> WatchlistTarget:
    """Build the non-persistent target consumed by an existing adapter."""

    return WatchlistTarget(
        key="episode-list",
        work_key="episode-list",
        site=site,
        url=url,
        label="episode-list",
        enabled=True,
        discovery_scope=None,
    )


def _filter_episode_records(
    records: list[DiscoveredRecord], contains: list[str]
) -> list[DiscoveredRecord]:
    """Apply the display-only OR substring filter without changing record order."""

    if not contains:
        return records
    filtered: list[DiscoveredRecord] = []
    for record in records:
        searchable = " ".join(
            value
            for value in (record.item.order_key, record.item.order_label)
            if value is not None
        )
        if any(needle in searchable for needle in contains):
            filtered.append(record)
    return filtered


def _format_episode_record(record: DiscoveredRecord) -> str:
    """Format one record as order, visible title, and canonical URL."""

    order_key = record.item.order_key or "-"
    order_label = record.item.order_label or "-"
    return f"{order_key}\t{order_label}\t{record.source.url}"


async def _run_episode_list(args: argparse.Namespace) -> None:
    """List validated site-adapter records without invoking Catalog Discovery."""

    site = _episode_list_site(args.url)
    target = _episode_list_target(site, args.url)
    adapter = _episode_list_adapter(site)
    values = read_env_file(args.env_file) if args.env_file.is_file() else {}
    endpoint = resolve_cdp_endpoint(
        site=site,
        cli_endpoint=args.cdp_endpoint,
        values=values,
    )
    try:
        session = await BrowserSession.connect(endpoint)
    except Exception as exc:
        detail = str(exc).strip() or type(exc).__name__
        raise EpisodeListError(f"Episode listing browser connection failed: {detail}") from exc

    try:
        page = await session.new_page()
        try:
            try:
                records = [
                    record
                    async for record in adapter.iter_records(page, target, "full")
                ]
            except DiscoveryIncompleteError as exc:
                detail = str(exc).strip() or "adapter validation failed"
                raise EpisodeListError(f"Episode listing incomplete: {detail}") from exc
            except Exception as exc:
                detail = str(exc).strip() or type(exc).__name__
                raise EpisodeListError(f"Episode listing failed: {detail}") from exc

            filtered = _filter_episode_records(records, args.contains)
            if not filtered:
                print("No episodes matched the filters.")
            else:
                for record in filtered:
                    print(_format_episode_record(record))
            if args.keep_open:
                print("Browser is open. Press Enter here to disconnect.")
                await asyncio.to_thread(input)
        finally:
            await session.close_page(page)
    finally:
        await session.close()


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
    runtime_settings = load_runtime_settings(args.crawler_config).for_site(args.site)
    config = RunConfig(
        site=args.site,
        source_url=args.url,
        output_dir=output_dir,
        diagnostics_dir=diagnostics_dir,
        max_pages=args.max_pages,
        max_same_content=args.max_same_content,
        page_turn_delay_ms=runtime_settings.page_turn_delay_ms,
        stop_on_http_403=runtime_settings.stop_on_http_403,
        stop_on_http_429=runtime_settings.stop_on_http_429,
        stop_on_challenge=runtime_settings.stop_on_challenge,
        stop_on_captcha=runtime_settings.stop_on_captcha,
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
    result = None
    try:
        page = await session.new_page()
        try:
            result = await CrawlerRunner(config).run(page, adapter)
            print(f"Saved {len(result.pages)} pages; stopped at {result.stop_reason}.")
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

    # Packaging is filesystem-only. Do it after the Page and Playwright/CDP
    # connection are closed so late browser events cannot race transport
    # teardown and emit asyncio "socket.send() raised exception" warnings.
    if result is not None and result.stop_state in {PageState.END, PageState.NEXT_CONTENT}:
        package = package_crawl_output(
            output_dir,
            adapter.get_output_metadata(),
            library_dir=library_dir,
            explicit_metadata=config.output_metadata,
        )
        print(f"Archive saved to {package.archive_path}")
        print(f"Completion status saved to {package.status_path}")


async def _discover_target(
    *,
    target: WatchlistTarget,
    mode: str,
    catalog: CatalogService,
    registry: DiscoveryAdapterRegistry,
    values: dict[str, str],
    cli_endpoint: str | None,
    keep_open: bool = False,
) -> DiscoveryResult:
    """Run one target with a caller-owned, target-scoped browser session."""

    endpoint = resolve_cdp_endpoint(
        site=target.site,
        cli_endpoint=cli_endpoint,
        values=values,
    )
    session = await BrowserSession.connect(endpoint)
    try:
        page = await session.new_page()
        try:
            result = await DiscoveryService(catalog, registry).discover(page, target, mode)
            if keep_open:
                print("Browser is open. Press Enter here to disconnect.")
                await asyncio.to_thread(input)
            return result
        finally:
            await session.close_page(page)
    finally:
        await session.close()


def _print_discovery_result(
    result: DiscoveryResult,
    *,
    all_targets: bool = False,
    status: str = "OK",
    error: str | None = None,
) -> None:
    if all_targets:
        print(f"  observed: {result.observed_count}")
        print(f"  new: {result.new_count}")
        print(f"  known: {result.known_count}")
        print(f"  complete: {result.complete}")
        print(f"  stopped_reason: {result.stopped_reason}")
        for warning in result.warnings:
            print(f"  warning: {warning}")
        print(f"  status: {status}")
        if error is not None:
            print(f"  error: {error}")
        return

    print("Discovery completed:")
    print(f"  target: {result.target_key}")
    print(f"  mode: {result.mode}")
    print(f"  observed: {result.observed_count}")
    print(f"  new: {result.new_count}")
    print(f"  known: {result.known_count}")
    print(f"  complete: {result.complete}")
    print(f"  stopped_reason: {result.stopped_reason}")
    for warning in result.warnings:
        print(f"Warning: {warning}")


async def _run_discover(args: argparse.Namespace) -> None:
    watchlist = WatchlistService(args.watchlist)
    is_multi_target = args.all or args.site is not None
    if args.all:
        targets = [target for target in watchlist.list_targets() if target.enabled is True]
        if not targets:
            print("No enabled watchlist targets.")
            return
    elif args.site is not None:
        targets = [
            target
            for target in watchlist.list_targets()
            if target.enabled is True and target.site == args.site
        ]
        if not targets:
            print(f"No enabled watchlist targets for site '{args.site}'.")
            return
    else:
        targets = [watchlist.get(args.key)]

    values = read_env_file(args.env_file) if args.env_file.is_file() else {}
    catalog = CatalogService(args.catalog)
    registry = _discovery_registry()

    if not is_multi_target:
        result = await _discover_target(
            target=targets[0],
            mode=args.mode,
            catalog=catalog,
            registry=registry,
            values=values,
            cli_endpoint=args.cdp_endpoint,
            keep_open=args.keep_open,
        )
        _print_discovery_result(result)
        return

    failures: list[tuple[str, str]] = []
    succeeded = 0
    total = len(targets)
    for index, target in enumerate(targets, start=1):
        print(f"[{index}/{total}] {target.key} ({target.site})")
        try:
            result = await _discover_target(
                target=target,
                mode=args.mode,
                catalog=catalog,
                registry=registry,
                values=values,
                cli_endpoint=args.cdp_endpoint,
            )
        except Exception as exc:  # noqa: BLE001 - one target must not stop the batch
            error = str(exc) or type(exc).__name__
            failures.append((target.key, error))
            print("  status: FAILED")
            print(f"  error: {error}")
            continue

        if result.stopped_reason == "incomplete":
            error = "Discovery incomplete"
            failures.append((target.key, error))
            _print_discovery_result(
                result,
                all_targets=True,
                status="FAILED",
                error=error,
            )
            continue

        succeeded += 1
        _print_discovery_result(result, all_targets=True)

    print("Discovery summary:")
    print(f"  mode: {args.mode}")
    if args.site is not None:
        print(f"  site: {args.site}")
    print(f"  targets: {total}")
    print(f"  succeeded: {succeeded}")
    print(f"  failed: {len(failures)}")
    if failures:
        print("Failed targets:")
        for target_key, error in failures:
            print(f"  {target_key}: {error}")
        raise DiscoveryAllError(failures, total)


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
            print(
                f"{target.key}\t{target.work_key}\t{target.site}\t{enabled}\t"
                f"{target.url}\t{target.label}"
            )
    elif args.watch_action == "add":
        target = service.add(
            key=args.key,
            work_key=args.work_key,
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


def _run_catalog(args: argparse.Namespace) -> None:
    if args.catalog_action == "export":
        result = export_catalog_csv(args.catalog, args.output_dir)
        print("Catalog export completed:")
        for table in ("works", "items", "sources", "source_targets", "crawl_runs", "artifacts"):
            print(f"  {table}: {getattr(result, table)}")
        print(f"  output: {result.output_dir}")
    elif args.catalog_action == "backup":
        output = args.output or default_backup_path(args.catalog)
        result = backup_catalog(args.catalog, output)
        print("Catalog backup completed:")
        print(f"  source: {result.source_path}")
        print(f"  schema_version: {result.schema_version}")
        print(f"  backup: {result.backup_path}")
        print(f"  bytes: {result.byte_size}")
    elif args.catalog_action == "migrate":
        result = migrate_catalog(args.catalog, backup_dir=args.backup_dir)
        status = "migrated" if result.migrated else "already current"
        print("Catalog migration:")
        print(f"  current_version: {result.from_version}")
        print(f"  target_version: {result.to_version}")
        print(f"  status: {status}")
        if result.backup_path is not None:
            print(f"  backup: {result.backup_path}")
    elif args.catalog_action == "item-status":
        service = CatalogService(args.catalog)
        if args.status is not None:
            item = service.set_item_status(args.item_id, args.status)
        else:
            item = service.get_item(args.item_id)
        print(
            f"item={item.id} status={item.status} completed_at={item.completed_at}"
        )
    elif args.catalog_action == "item-note":
        service = CatalogService(args.catalog)
        if args.clear:
            item = service.clear_item_note(args.item_id)
        elif args.note is not None:
            item = service.set_item_note(args.item_id, args.note)
        else:
            item = service.get_item(args.item_id)
        print(f"item={item.id} note={item.note}")


def _print_batch_plan(
    plan: BatchPlan, *, site: str, defer_quota: bool = False
) -> None:
    """Print the stable, human-readable plan summary."""

    immediate_candidates, deferred_candidates, deferred_resource = (
        _partition_deferred_candidates(plan.candidates, defer_quota=defer_quota)
    )
    print("Batch plan:")
    print(f"  site: {site}")
    print(f"  eligible: {len(plan.candidates)}")
    direct_count = len(immediate_candidates) if defer_quota else plan.direct_count
    print(f"  direct: {direct_count}")
    if defer_quota:
        deferred_summary = f"  deferred: {len(deferred_candidates)}"
        if deferred_resource is not None:
            deferred_summary += f" resource={deferred_resource}"
        print(deferred_summary)
    else:
        print(f"  quota: {plan.quota_count}")
    if plan.quota_remaining is not None:
        print(f"  quota_available: {plan.quota_available}")
        print(f"  quota_remaining: {plan.quota_remaining} (after in-memory reservations)")
    print(f"  skipped: {len(plan.skipped)}")
    visible_candidates = immediate_candidates if defer_quota else plan.candidates
    if visible_candidates:
        print("Candidates:")
        for candidate in visible_candidates:
            _print_batch_candidate(candidate)
    if defer_quota and deferred_candidates:
        print("Deferred access-resource pool:")
        print(f"  resource: {deferred_resource}")
        print(f"  candidates: {len(deferred_candidates)}")
        print("  availability: checked during batch run")
    if plan.skipped:
        print("Skipped:")
        for reason, count in sorted(Counter(item.reason for item in plan.skipped).items()):
            print(f"  {reason}: {count}")


def _print_batch_candidate(candidate: BatchCandidate) -> None:
    order = candidate.metadata.get("order", "-")
    print(
        f"  item={candidate.item_id} source={candidate.source_id} "
        f"{order} {candidate.access_mode} -> "
        f"{candidate.access_strategy} {candidate.locator}"
    )


def _run_batch_plan(args: argparse.Namespace) -> None:
    policies = _batch_policy_registry()
    planner = BatchPlanner(CatalogService(args.catalog), policies)
    plan = planner.plan(site=args.site)
    policy = policies.create(args.site)
    _print_batch_plan(
        plan,
        site=args.site,
        defer_quota=_policy_defers_quota_access(policy),
    )
    for resource in _additional_access_resource_passes(policy):
        resource_plan = planner.plan(site=args.site, quota_resource=resource)
        print(f"Potential resource pass ({resource}):")
        print(f"  candidates: {len(resource_plan.candidates)}")
        print("  availability: checked during batch run")


def _additional_access_resource_passes(policy: object) -> tuple[str, ...]:
    """Resolve policy-ordered passes without interpreting resource names."""

    additional = getattr(policy, "additional_access_resource_passes", None)
    if callable(additional):
        return tuple(additional())
    ordered = getattr(policy, "ordered_access_resource_passes", None)
    if callable(ordered):
        values = tuple(ordered())
        return values[1:]
    legacy = getattr(policy, "additional_quota_resources", None)
    if callable(legacy):
        return tuple(legacy())
    return ()


def _policy_defers_quota_access(policy: object) -> bool:
    """Read the optional site-owned direct -> grant -> replan contract."""

    method = getattr(policy, "defer_quota_access_to_grant_phase", None)
    return bool(method()) if callable(method) else False


def _single_deferred_quota_resource(
    candidates: list[BatchCandidate],
) -> str | None:
    """Return the one resource owned by a deferred quota phase.

    Deferred candidates are already policy-selected.  The generic CLI may carry
    their resource through the resolver contract, but it must not infer a site
    resource name or silently discard an incomplete/mixed plan.
    """

    if not candidates:
        return None
    resources = {candidate.quota_resource for candidate in candidates}
    if None in resources or len(resources) != 1:
        raise BatchPlanningError(
            "Deferred quota candidates must share exactly one access resource"
        )
    resource = next(iter(resources))
    if not isinstance(resource, str) or not resource:
        raise BatchPlanningError(
            "Deferred quota candidates must provide a non-empty access resource"
        )
    return resource


def _partition_deferred_candidates(
    candidates: list[BatchCandidate],
    *,
    defer_quota: bool,
) -> tuple[list[BatchCandidate], list[BatchCandidate], str | None]:
    """Partition a plan without changing the planner-owned candidate pool."""

    if not defer_quota:
        return list(candidates), [], None
    immediate = [candidate for candidate in candidates if not candidate.consumes_quota]
    deferred = [candidate for candidate in candidates if candidate.consumes_quota]
    return immediate, deferred, _single_deferred_quota_resource(deferred)


async def _resolve_access_resource_candidates(
    session: BrowserSession,
    executor: BatchExecutor,
    candidates: list[BatchCandidate],
    *,
    resource: str,
    delay_before_first_ms: int | None = None,
    metrics: BatchMetricsWriter | None = None,
) -> list[BatchCandidate]:
    """Resolve site-native candidates without counting the snapshot as an attempt."""

    if not candidates:
        return []
    if delay_before_first_ms is not None:
        await asyncio.sleep(delay_before_first_ms / 1000)
    page = await session.new_page()
    site = str(getattr(candidates[0], "site", "unknown"))
    print(
        f"Batch access-resource resolver: site={site} resource={resource} "
        f"snapshot start candidates={len(candidates)}"
    )
    try:
        resolver = getattr(executor, "resolve_access_resource_candidates", None)
        if not callable(resolver):
            raise BatchPlanningError(
                "Selected site does not provide the access-resource resolver contract"
            )
        resolution = await resolver(page, candidates, resource)
        print(
            f"Batch access-resource resolver: site={site} resource={resource} "
            f"snapshot complete selected={len(resolution.selected_source_ids)}"
        )
    except BaseException as exc:
        print(
            f"Batch access-resource resolver: site={site} resource={resource} "
            f"failed: {exc}",
            file=sys.stderr,
        )
        raise
    finally:
        await _best_effort_cleanup(session.close_page(page))

    if metrics is not None:
        for source_id, reason in resolution.skipped_source_reasons:
            candidate = next(
                (item for item in candidates if item.source_id == source_id), None
            )
            if candidate is not None:
                metrics.record_local_skip(candidate, reason=reason)
    selected_ids = set(resolution.selected_source_ids)
    return [candidate for candidate in candidates if candidate.source_id in selected_ids]


def _completed_candidate_count(
    catalog: CatalogService, candidates: list[BatchCandidate]
) -> int:
    return sum(catalog.get_item(candidate.item_id).status == "completed" for candidate in candidates)


def _candidate_failure_reason(error: BaseException) -> str:
    """Keep the original site/crawler error visible in Batch metrics."""

    root = _candidate_failure_root(error)
    return (
        getattr(root, "reason", None)
        or type(root).__name__
    )


def _candidate_failure_root(error: BaseException) -> BaseException:
    """Return the underlying candidate error when Batch wrapped it."""

    return error.__cause__ if error.__cause__ is not None else error


async def _best_effort_cleanup(awaitable: Awaitable[Any]) -> None:
    """Bound cleanup and keep it from replacing the active Batch error."""

    task = asyncio.ensure_future(awaitable)
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=5)
    except TimeoutError:
        if not task.done():
            task.cancel()
    except (KeyboardInterrupt, asyncio.CancelledError):
        if not task.done():
            task.cancel()
        raise
    except BaseException:  # noqa: BLE001 - cleanup is best effort
        if not task.done():
            task.cancel()


async def _run_batch_run(args: argparse.Namespace) -> None:
    catalog = CatalogService(args.catalog)
    policies = _batch_policy_registry()
    planner = BatchPlanner(catalog, policies)
    runtime_settings = load_runtime_settings(args.crawler_config).for_site(args.site)
    grant_only = getattr(args, "grant_only", None)
    grant_only_all = grant_only == "all"
    limit = getattr(args, "limit", None)
    policy = policies.create(args.site)
    defer_quota = _policy_defers_quota_access(policy)
    deferred_candidates: list[BatchCandidate] = []
    deferred_resource: str | None = None
    if grant_only_all:
        grant_only_resources = _grant_only_resource_passes(policy)
        plan = None
        candidates: list[BatchCandidate] = []
        metrics_mode = "grant-only:all"
    elif grant_only is not None:
        try:
            policy.validate_grant_only_resource(grant_only)
        except SitePolicyError as exc:
            raise BatchPlanningError(str(exc)) from exc
        plan = planner.plan(site=args.site, quota_resource=grant_only)
        candidates = plan.candidates
        if defer_quota:
            _immediate_candidates, candidates, _deferred_resource = (
                _partition_deferred_candidates(candidates, defer_quota=True)
            )
        metrics_mode = "grant-only"
    else:
        plan = planner.plan(site=args.site)
        if defer_quota:
            direct_candidates, deferred_candidates, deferred_resource = (
                _partition_deferred_candidates(plan.candidates, defer_quota=True)
            )
            candidates = direct_candidates[:limit] if limit is not None else direct_candidates
        else:
            candidates = plan.candidates[:limit] if limit is not None else plan.candidates
        metrics_mode = "normal"
    metrics = BatchMetricsWriter("output/metrics", site=args.site, mode=metrics_mode)
    if plan is not None:
        metrics.record_planned_skips(plan.skipped)
    print("Batch run:")
    print(f"  site: {args.site}")
    print(
        f"  planned: {len(plan.candidates) if plan is not None else 'policy resource passes'}"
    )
    if grant_only_all and defer_quota:
        print("  executing: policy resource passes")
    elif defer_quota and grant_only is not None:
        print("  deferred candidate pool:")
        print(f"    resource: {grant_only}")
        print(f"    candidates: {len(candidates)}")
        print("    selection: live resolver")
        print("  executing: resolver-selected candidates")
    elif defer_quota:
        print(f"  direct: {len(direct_candidates)}")
        deferred_summary = f"  deferred: {len(deferred_candidates)}"
        if deferred_resource is not None:
            deferred_summary += f" resource={deferred_resource}"
        print(deferred_summary)
        print(f"  executing direct: {len(candidates)}")
    else:
        print(
            f"  executing: {len(candidates)}"
            + (f" resource={grant_only}" if grant_only is not None else "")
        )
        if plan is not None:
            print(f"  direct: {sum(item.access_strategy == 'direct' for item in candidates)}")
            print(f"  quota: {sum(item.access_strategy == 'quota' for item in candidates)}")
    if plan is not None and plan.skipped:
        print(f"  skipped: {len(plan.skipped)}")
    has_deferred_normal_work = (
        grant_only is None and not grant_only_all and bool(deferred_candidates)
    )
    if not grant_only_all and not candidates and not has_deferred_normal_work:
        metrics.finish(stop_reason="no_candidates")
        metrics.close()
        print(f"  metrics: {metrics.path}")
        return

    session = None
    primary_error: BaseException | None = None
    try:
        values = read_env_file(args.env_file) if args.env_file.is_file() else {}
        endpoint = resolve_cdp_endpoint(
            site=args.site,
            cli_endpoint=args.cdp_endpoint,
            values=values,
        )
        session = await BrowserSession.connect(endpoint)
        executor = BatchExecutor(catalog, policies, _batch_adapter_registry(values))
        # Keep the orchestration input site-neutral and preserve compatibility with
        # lightweight test doubles that implement the pre-Phase-1 constructor.
        if hasattr(executor, "runtime_settings"):
            executor.runtime_settings = runtime_settings
        if hasattr(executor, "access_event_sink"):
            executor.access_event_sink = metrics.record_access_event
        if grant_only_all:
            attempts = 0
            previous_phase_had_site_access = False
            for resource in grant_only_resources:
                remaining_limit = None if limit is None else max(0, limit - attempts)
                if remaining_limit == 0:
                    break
                resource_plan = planner.plan(
                    site=args.site,
                    quota_resource=resource,
                )
                metrics.record_planned_skips(resource_plan.skipped)
                resource_candidates = resource_plan.candidates
                deferred_pool_count = len(resource_candidates)
                if defer_quota:
                    _immediate_candidates, resource_candidates, _resource = (
                        _partition_deferred_candidates(
                            resource_candidates,
                            defer_quota=True,
                        )
                    )
                    resolver_had_candidates = bool(resource_candidates)
                    resource_candidates = await _resolve_access_resource_candidates(
                        session,
                        executor,
                        resource_candidates,
                        resource=resource,
                        delay_before_first_ms=(
                            runtime_settings.inter_candidate_delay_ms
                            if previous_phase_had_site_access
                            else None
                        ),
                        metrics=metrics,
                    )
                    previous_phase_had_site_access = (
                        previous_phase_had_site_access or resolver_had_candidates
                    )
                if defer_quota:
                    print("Deferred access-resource pool:")
                    print(f"  resource: {resource}")
                    print(f"  candidates: {deferred_pool_count}")
                    print("  selection: live resolver")
                    print(
                        f"Batch grant-only resource pass ({resource}); "
                        f"selected={len(resource_candidates)}"
                    )
                else:
                    print(
                        f"Batch grant-only resource pass ({resource}); "
                        f"planned={len(resource_candidates)}"
                    )
                pass_attempts, _pass_continue = await _execute_batch_candidates(
                    args,
                    session,
                    executor,
                    resource_candidates,
                    phase=f"grant-only:{resource}",
                    inter_candidate_delay_ms=runtime_settings.inter_candidate_delay_ms,
                    delay_before_first_ms=(
                        runtime_settings.inter_candidate_delay_ms
                        if resource_candidates
                        and (defer_quota or previous_phase_had_site_access)
                        else None
                    ),
                    metrics=metrics,
                    grant_only=True,
                    attempt_limit=remaining_limit,
                )
                attempts += pass_attempts
                previous_phase_had_site_access = (
                    previous_phase_had_site_access or pass_attempts > 0
                )
            if attempts == 0:
                metrics.finish(stop_reason="no_candidates")
            if args.keep_open:
                print("Browser is open. Press Enter here to disconnect.")
                await asyncio.to_thread(input)
        elif grant_only is not None:
            if defer_quota:
                candidates = await _resolve_access_resource_candidates(
                    session,
                    executor,
                    candidates,
                    resource=grant_only,
                    metrics=metrics,
                )
            processed, should_continue = await _execute_batch_candidates(
                args,
                session,
                executor,
                candidates,
                phase=(f"{args.site} grant-only:{grant_only}" if defer_quota else f"grant-only:{grant_only}"),
                inter_candidate_delay_ms=runtime_settings.inter_candidate_delay_ms,
                delay_before_first_ms=(
                    runtime_settings.inter_candidate_delay_ms if defer_quota else None
                ),
                metrics=metrics,
                grant_only=True,
                attempt_limit=limit,
            )
            if processed == 0 and not candidates:
                metrics.finish(stop_reason="no_candidates")
        elif defer_quota:
            print(f"Batch phase: {args.site} direct")
            _phase_a_processed, should_continue = await _execute_batch_candidates(
                args,
                session,
                executor,
                candidates,
                phase=f"{args.site} direct",
                inter_candidate_delay_ms=runtime_settings.inter_candidate_delay_ms,
                metrics=metrics,
            )
            phase_a_completed = _completed_candidate_count(catalog, candidates)
            remaining_limit = (
                None if limit is None else max(0, limit - phase_a_completed)
            )
            if should_continue and remaining_limit != 0 and deferred_candidates:
                if deferred_resource is None:
                    raise BatchPlanningError(
                        "Deferred quota candidates have no access resource"
                    )
                selected = await _resolve_access_resource_candidates(
                    session,
                    executor,
                    deferred_candidates,
                    resource=deferred_resource,
                    delay_before_first_ms=(
                        runtime_settings.inter_candidate_delay_ms
                        if _phase_a_processed > 0
                        else None
                    ),
                    metrics=metrics,
                )
                if selected:
                    print(f"Batch phase: {args.site} grant-access")
                    grant_processed, _grant_should_continue = await _execute_batch_candidates(
                        args,
                        session,
                        executor,
                        selected,
                        phase=f"{args.site} grant-access",
                        inter_candidate_delay_ms=runtime_settings.inter_candidate_delay_ms,
                        delay_before_first_ms=runtime_settings.inter_candidate_delay_ms,
                        metrics=metrics,
                        grant_only=True,
                        attempt_limit=remaining_limit,
                    )
                    granted_source_ids = {
                        candidate.source_id
                        for candidate in selected
                        if catalog.get_source(candidate.source_id).quota_started_at is not None
                    }
                    if granted_source_ids:
                        post_plan = planner.plan(site=args.site)
                        post_candidates = [
                            candidate
                            for candidate in post_plan.candidates
                            if candidate.access_strategy == "direct"
                            and candidate.source_id in granted_source_ids
                        ]
                        post_completed = _completed_candidate_count(catalog, candidates)
                        post_remaining_limit = (
                            None
                            if limit is None
                            else max(0, limit - post_completed)
                        )
                        if post_remaining_limit != 0 and post_candidates:
                            if post_remaining_limit is not None:
                                post_candidates = post_candidates[:post_remaining_limit]
                            print(f"Batch phase: {args.site} post-grant direct")
                            await _execute_batch_candidates(
                                args,
                                session,
                                executor,
                                post_candidates,
                                phase=f"{args.site} post-grant direct",
                                inter_candidate_delay_ms=runtime_settings.inter_candidate_delay_ms,
                                delay_before_first_ms=(
                                    runtime_settings.inter_candidate_delay_ms
                                    if grant_processed > 0
                                    else None
                                ),
                                metrics=metrics,
                            )
        else:
            initial_complete = len(candidates) == len(plan.candidates)
            processed, should_continue = await _execute_batch_candidates(
                args,
                session,
                executor,
                candidates,
                phase=(f"grant-only:{grant_only}" if grant_only is not None else "default"),
                inter_candidate_delay_ms=runtime_settings.inter_candidate_delay_ms,
                metrics=metrics,
                grant_only=False,
                attempt_limit=None,
            )
        if (
            not grant_only_all
            and grant_only is None
            and not defer_quota
            and should_continue
            and initial_complete
        ):
            previous_phase_had_site_access = processed > 0
            remaining_limit = (
                None if limit is None else max(0, limit - processed)
            )
            for quota_resource in _additional_access_resource_passes(policy):
                if remaining_limit == 0:
                    break
                # Re-plan from Catalog after direct and Work Ticket execution.
                resource_plan = planner.plan(
                    site=args.site,
                    quota_resource=quota_resource,
                )
                resource_candidates = resource_plan.candidates
                if remaining_limit is not None:
                    resource_candidates = resource_candidates[:remaining_limit]
                print(
                    f"Batch resource pass ({quota_resource}); "
                    f"planned={len(resource_plan.candidates)} "
                    f"executing={len(resource_candidates)}"
                )
                pass_processed, should_continue = await _execute_batch_candidates(
                    args,
                    session,
                    executor,
                    resource_candidates,
                    phase=quota_resource,
                    inter_candidate_delay_ms=runtime_settings.inter_candidate_delay_ms,
                    metrics=metrics,
                    delay_before_first_ms=(
                        runtime_settings.inter_candidate_delay_ms
                        if previous_phase_had_site_access
                        else None
                    ),
                )
                previous_phase_had_site_access = (
                    previous_phase_had_site_access or pass_processed > 0
                )
                if remaining_limit is not None:
                    remaining_limit -= pass_processed
                if not should_continue or len(resource_candidates) < len(resource_plan.candidates):
                    break
        if not grant_only_all and args.keep_open:
            print("Browser is open. Press Enter here to disconnect.")
            await asyncio.to_thread(input)
    except BaseException as exc:
        primary_error = exc
        access_stop = getattr(exc, "access_stop", None)
        metrics.finish(
            stop_reason=(
                getattr(access_stop, "reason", None)
                or getattr(exc, "stop_reason", None)
                or getattr(exc, "reason", None)
                or (
                    _candidate_failure_reason(exc)
                    if isinstance(exc, CandidateExecutionError)
                    else None
                )
                or type(exc).__name__
            )
        )
        raise
    finally:
        cleanup_interruption: BatchInterruptedError | None = None
        if session is not None:
            try:
                await _best_effort_cleanup(session.close())
            except (KeyboardInterrupt, asyncio.CancelledError):
                if primary_error is None:
                    cleanup_interruption = BatchInterruptedError(
                        "Batch interrupted while closing the browser session"
                    )
        if cleanup_interruption is not None:
            metrics.finish(stop_reason="interrupted")
            print(f"  metrics: {metrics.path}")
            metrics.close()
            raise cleanup_interruption
        metrics.finish()
        print(f"  metrics: {metrics.path}")
        metrics.close()


def _grant_only_resource_passes(policy: object) -> tuple[str, ...]:
    """Resolve and validate the policy-owned resource order for ``all``."""

    ordered_method = getattr(policy, "ordered_access_resource_passes", None)
    supported_method = getattr(policy, "grant_only_supported_access_resources", None)
    if not callable(ordered_method) or not callable(supported_method):
        raise BatchPlanningError(
            "Selected site policy does not expose the grant-only resource contract"
        )
    ordered = tuple(ordered_method())
    supported = set(supported_method())
    if not ordered:
        raise BatchPlanningError(
            "Selected site policy does not support any grant-only resource"
        )
    unsupported = tuple(resource for resource in ordered if resource not in supported)
    if unsupported:
        raise BatchPlanningError(
            "Grant-only resource contract mismatch: " + ", ".join(unsupported)
        )
    if len(set(ordered)) != len(ordered):
        raise BatchPlanningError("Selected site policy returned duplicate grant-only resources")
    return ordered


async def _execute_batch_candidates(
    args: argparse.Namespace,
    session: BrowserSession,
    executor: BatchExecutor,
    candidates: list[BatchCandidate],
    *,
    phase: str,
    inter_candidate_delay_ms: int = 3000,
    delay_before_first_ms: int | None = None,
    metrics: BatchMetricsWriter | None = None,
    grant_only: bool = False,
    attempt_limit: int | None = None,
) -> tuple[int, bool]:
    """Execute a sequential resource phase; return attempts and continue flag."""

    attempts = 0
    for index, candidate in enumerate(candidates, start=1):
        if attempt_limit is not None and attempts >= attempt_limit:
            break
        if grant_only:
            local_skip_reason = executor.grant_only_skip_reason(candidate)
            if local_skip_reason is not None:
                print(
                    f"[{phase} {index}/{len(candidates)}] item={candidate.item_id} "
                    f"SKIPPED {local_skip_reason}"
                )
                if metrics is not None:
                    metrics.record_local_skip(candidate, reason=local_skip_reason)
                continue
        elif getattr(candidate, "consumes_quota", False):
            resource_state_check = getattr(executor, "resource_state_skip_reason", None)
            if callable(resource_state_check):
                local_skip_reason = resource_state_check(candidate)
                if local_skip_reason is not None:
                    print(
                        f"[{phase} {index}/{len(candidates)}] item={candidate.item_id} "
                        f"SKIPPED {local_skip_reason}"
                    )
                    if metrics is not None:
                        metrics.record_local_skip(candidate, reason=local_skip_reason)
                    continue
        if attempts == 0 and delay_before_first_ms is not None:
            await asyncio.sleep(delay_before_first_ms / 1000)
        attempts += 1
        order = candidate.metadata.get("order", "-")
        resource = f" resource={candidate.quota_resource}" if candidate.quota_resource else ""
        print(
            f"[{phase} {index}/{len(candidates)}] item={candidate.item_id} "
            f"source={candidate.source_id} {order} {candidate.access_strategy}{resource}"
        )
        page = None
        contacted_site = False
        continue_after_candidate = False
        primary_error: BaseException | None = None
        if metrics is not None:
            metrics.start_candidate(candidate)
        try:
            page = await session.new_page()
            contacted_site = True
            if grant_only:
                result = await executor.execute_grant_only_candidate(
                    page,
                    candidate,
                    output_root=args.output_root,
                    max_pages=args.max_pages,
                    max_same_content=args.max_same_content,
                )
                print(f"  grant confirmed: {result.resource}")
            else:
                result = await executor.execute_candidate(
                    page,
                    candidate,
                    output_root=args.output_root,
                    library_dir=args.library_dir,
                    max_pages=args.max_pages,
                    max_same_content=args.max_same_content,
                )
                print(f"  completed: {result.archive_path}")
            continue_after_candidate = True
            if metrics is not None:
                metrics.finish_candidate(
                    result="completed",
                    stop_reason=getattr(result, "stop_reason", None),
                    resource_consumed=(
                        getattr(result, "resource_consumed", None)
                        if grant_only else None
                    ),
                )
        except BatchInterruptedError as exc:
            primary_error = exc
            if metrics is not None:
                metrics.finish_candidate(
                    result="failed",
                    stop_reason="interrupted",
                    error_type="BatchInterruptedError",
                    error_message="Batch interrupted by user",
                )
            print("  Batch interrupted by user.", file=sys.stderr)
            raise
        except (KeyboardInterrupt, asyncio.CancelledError) as exc:
            interruption = BatchInterruptedError(
                f"Batch interrupted while executing item={candidate.item_id}, "
                f"source={candidate.source_id}"
            )
            primary_error = interruption
            if metrics is not None:
                metrics.finish_candidate(
                    result="failed",
                    stop_reason="interrupted",
                    error_type="BatchInterruptedError",
                    error_message=str(interruption),
                )
            print("  Batch interrupted by user.", file=sys.stderr)
            raise interruption from exc
        except AccessResourceUnavailableError as exc:
            reason = exc.reason
            print(f"  SKIPPED item={candidate.item_id} reason={reason} ({exc})")
            if metrics is not None:
                metrics.finish_candidate(result="skipped", stop_reason=reason)
            if exc.stop_resource_pass:
                print("  Stopping this resource pass.")
                return attempts, False
            continue_after_candidate = True
        except CandidateExecutionError as exc:
            primary_error = exc
            root = _candidate_failure_root(exc)
            if metrics is not None:
                metrics.finish_candidate(
                    result="failed",
                    stop_reason=_candidate_failure_reason(exc),
                    error_type=type(root).__name__,
                    error_message=str(root)[:4000] or None,
                )
            print("FAILED (stopping batch):", file=sys.stderr)
            print(f"  item={candidate.item_id}", file=sys.stderr)
            print(f"  source={candidate.source_id}", file=sys.stderr)
            print(f"  error={exc}", file=sys.stderr)
            raise
        except BaseException as exc:
            primary_error = exc
            if metrics is not None:
                access_stop = getattr(exc, "access_stop", None)
                metrics.finish_candidate(
                    result="failed",
                    stop_reason=(
                        getattr(access_stop, "reason", None)
                        or getattr(exc, "reason", None)
                        or type(exc).__name__
                    ),
                    error_type=type(exc).__name__,
                    error_message=str(exc)[:4000] or None,
                )
            print("FAILED:", file=sys.stderr)
            print(f"  item={candidate.item_id}", file=sys.stderr)
            print(f"  source={candidate.source_id}", file=sys.stderr)
            print(f"  strategy={candidate.access_strategy}", file=sys.stderr)
            print(f"  error={exc}", file=sys.stderr)
            if args.keep_open:
                print("Browser is open. Press Enter here to disconnect.")
                await asyncio.to_thread(input)
            if isinstance(exc, BatchExecutionError):
                raise
            raise BatchExecutionError(str(exc)) from exc
        finally:
            try:
                if page is not None:
                    await _best_effort_cleanup(session.close_page(page))
                if contacted_site and continue_after_candidate:
                    if grant_only:
                        has_future_access = any(
                            executor.grant_only_skip_reason(future)
                            is None
                            for future in candidates[index:]
                        )
                        if attempt_limit is not None and attempts >= attempt_limit:
                            has_future_access = False
                    else:
                        has_future_access = index < len(candidates)
                    if has_future_access:
                        await asyncio.sleep(inter_candidate_delay_ms / 1000)
            except (KeyboardInterrupt, asyncio.CancelledError) as exc:
                if primary_error is not None:
                    pass
                else:
                    interruption = BatchInterruptedError(
                        f"Batch interrupted while finishing item={candidate.item_id}, "
                        f"source={candidate.source_id}"
                    )
                    if metrics is not None:
                        metrics.finish_candidate(
                            result="failed",
                            stop_reason="interrupted",
                            error_type="BatchInterruptedError",
                            error_message=str(interruption),
                        )
                    print("  Batch interrupted by user.", file=sys.stderr)
                    raise interruption from exc
    return attempts, True


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    if args.command == "discover" and (args.all or args.site is not None) and args.keep_open:
        parser.error("discover --all/--site cannot be combined with --keep-open")
    try:
        if args.command == "probe":
            asyncio.run(_run_probe(args))
        elif args.command == "crawl":
            asyncio.run(_run_crawl(args))
        elif args.command == "discover":
            asyncio.run(_run_discover(args))
        elif args.command == "episode-list":
            asyncio.run(_run_episode_list(args))
        elif args.command == "login":
            asyncio.run(_run_login(args))
        elif args.command == "watch":
            _run_watch(args)
        elif args.command == "catalog":
            _run_catalog(args)
        elif args.command == "batch":
            if args.batch_action == "plan":
                _run_batch_plan(args)
            elif args.batch_action == "run":
                asyncio.run(_run_batch_run(args))
    except WatchlistError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    except CatalogError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    except BatchPlanningError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    except BatchInterruptedError as exc:
        print(f"Interrupted: {exc}", file=sys.stderr)
        raise SystemExit(130) from exc
    except BatchExecutionError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    except AccessStopError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    except DiscoveryAllError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    except EpisodeListError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
