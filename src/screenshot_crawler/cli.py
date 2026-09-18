"""Command line entry point for crawl and probe."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from screenshot_crawler.auth.env import (
    read_env_file,
    require_site_env_value,
)
from screenshot_crawler.batch import (
    BatchExecutionError,
    BatchExecutor,
    BatchPlan,
    BatchPlanner,
    BatchPlanningError,
)
from screenshot_crawler.catalog import CatalogError, CatalogService
from screenshot_crawler.catalog.export import export_catalog_csv
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
from screenshot_crawler.discovery import DiscoveryAdapterRegistry, DiscoveryService
from screenshot_crawler.discovery.models import DiscoveryResult
from screenshot_crawler.probe.collector import ProbeCollector
from screenshot_crawler.site_adapters.registry import AdapterRegistry
from screenshot_crawler.site_policies import (
    BookWalkerSitePolicy,
    MangaOneSitePolicy,
    SitePolicyRegistry,
)
from screenshot_crawler.watchlist.models import WatchlistTarget
from screenshot_crawler.watchlist.service import WatchlistError, WatchlistService


class DiscoveryAllError(RuntimeError):
    """Raised after an ``discover --all`` run has one or more failures."""

    def __init__(self, failures: list[tuple[str, str]], total: int) -> None:
        self.failures = tuple(failures)
        self.total = total
        super().__init__(
            f"Discovery failed for {len(self.failures)} of {self.total} targets"
        )


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

    catalog = subparsers.add_parser("catalog", help="Inspect Catalog data")
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
        "--output",
        type=Path,
        default=Path("catalog-export.csv"),
        help="CSV output path (default: catalog-export.csv)",
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
    batch_run.add_argument("--cdp-endpoint")
    batch_run.add_argument(
        "--limit",
        type=_positive_int,
        help="Execute only the first N planned candidates (N >= 1)",
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
    from screenshot_crawler.site_adapters.mangaone import MangaOneAdapter

    registry.register("bookwalker", BookWalkerAdapter)
    registry.register("mangaone", MangaOneAdapter)
    return registry


def _discovery_registry() -> DiscoveryAdapterRegistry:
    """Build the Discovery registry separately from viewer adapters."""

    from screenshot_crawler.site_adapters.bookwalker import BookWalkerDiscoveryAdapter
    from screenshot_crawler.site_adapters.mangaone import MangaOneDiscoveryAdapter

    registry = DiscoveryAdapterRegistry()
    registry.register("bookwalker", BookWalkerDiscoveryAdapter)
    registry.register("mangaone", MangaOneDiscoveryAdapter)
    return registry


def _batch_policy_registry() -> SitePolicyRegistry:
    registry = SitePolicyRegistry()
    registry.register("bookwalker", BookWalkerSitePolicy)
    registry.register("mangaone", MangaOneSitePolicy)
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
    if args.all:
        targets = [target for target in watchlist.list_targets() if target.enabled is True]
        if not targets:
            print("No enabled watchlist targets.")
            return
    else:
        targets = [watchlist.get(args.key)]

    values = read_env_file(args.env_file) if args.env_file.is_file() else {}
    catalog = CatalogService(args.catalog)
    registry = _discovery_registry()

    if not args.all:
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


def _run_catalog(args: argparse.Namespace) -> None:
    if args.catalog_action == "export":
        result = export_catalog_csv(args.catalog, args.output)
        print("Catalog exported:")
        print(f"  rows: {result.rows}")
        print(f"  output: {result.output_path.resolve()}")


def _print_batch_plan(plan: BatchPlan, *, site: str) -> None:
    """Print the stable, human-readable plan summary."""

    print("Batch plan:")
    print(f"  site: {site}")
    print(f"  eligible: {len(plan.candidates)}")
    print(f"  direct: {plan.direct_count}")
    print(f"  quota: {plan.quota_count}")
    if plan.quota_remaining is not None:
        print(f"  quota_available: {plan.quota_available}")
        print(f"  quota_remaining: {plan.quota_remaining} (after in-memory reservations)")
    print(f"  skipped: {len(plan.skipped)}")
    if plan.candidates:
        print("Candidates:")
        for candidate in plan.candidates:
            order = candidate.metadata.get("order", "-")
            print(
                f"  item={candidate.item_id} source={candidate.source_id} "
                f"{order} {candidate.access_mode} -> "
                f"{candidate.access_strategy} {candidate.url}"
            )
    if plan.skipped:
        print("Skipped:")
        for reason, count in sorted(Counter(item.reason for item in plan.skipped).items()):
            print(f"  {reason}: {count}")


def _run_batch_plan(args: argparse.Namespace) -> None:
    plan = BatchPlanner(
        CatalogService(args.catalog),
        _batch_policy_registry(),
    ).plan(site=args.site)
    _print_batch_plan(plan, site=args.site)


async def _run_batch_run(args: argparse.Namespace) -> None:
    catalog = CatalogService(args.catalog)
    policies = _batch_policy_registry()
    plan = BatchPlanner(catalog, policies).plan(site=args.site)
    candidates = plan.candidates[: args.limit] if args.limit is not None else plan.candidates
    print("Batch run:")
    print(f"  site: {args.site}")
    print(f"  planned: {len(plan.candidates)}")
    print(f"  executing: {len(candidates)}")
    print(f"  direct: {sum(item.access_strategy == 'direct' for item in candidates)}")
    print(f"  quota: {sum(item.access_strategy == 'quota' for item in candidates)}")
    if plan.skipped:
        print(f"  skipped: {len(plan.skipped)}")
    if not candidates:
        return

    values = read_env_file(args.env_file) if args.env_file.is_file() else {}
    endpoint = resolve_cdp_endpoint(
        site=args.site,
        cli_endpoint=args.cdp_endpoint,
        values=values,
    )
    session = await BrowserSession.connect(endpoint)
    executor = BatchExecutor(catalog, policies, _registry())
    try:
        for index, candidate in enumerate(candidates, start=1):
            order = candidate.metadata.get("order", "-")
            print(
                f"[{index}/{len(candidates)}] item={candidate.item_id} "
                f"source={candidate.source_id} {order} {candidate.access_strategy}"
            )
            page = None
            try:
                page = await session.new_page()
                result = await executor.execute_candidate(
                    page,
                    candidate,
                    output_root=args.output_root,
                    library_dir=args.library_dir,
                    max_pages=args.max_pages,
                    max_same_content=args.max_same_content,
                )
                print(f"  completed: {result.archive_path}")
            except BaseException as exc:
                print(
                    "FAILED:",
                    file=sys.stderr,
                )
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
                if page is not None:
                    await session.close_page(page)
        if args.keep_open:
            print("Browser is open. Press Enter here to disconnect.")
            await asyncio.to_thread(input)
    finally:
        await session.close()


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    if args.command == "discover" and args.all and args.keep_open:
        parser.error("discover --all cannot be combined with --keep-open")
    try:
        if args.command == "probe":
            asyncio.run(_run_probe(args))
        elif args.command == "crawl":
            asyncio.run(_run_crawl(args))
        elif args.command == "discover":
            asyncio.run(_run_discover(args))
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
    except BatchExecutionError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    except DiscoveryAllError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
