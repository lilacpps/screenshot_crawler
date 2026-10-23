"""P2 subprocess entry point with one Catalog lock and preflight boundary.

P3 will add durable events around this entry point.  Keeping the lock and the
revalidation in the worker process closes the GUI-to-browser drift window.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from argparse import Namespace
from collections.abc import Mapping
from pathlib import Path

from screenshot_crawler.auth.env import read_env_file
from screenshot_crawler.catalog import CatalogService
from screenshot_crawler.cli import (
    _batch_policy_registry,
    _discover_target,
    _discovery_registry,
)
from screenshot_crawler.management.execution import ExecutionPlanService
from screenshot_crawler.management.inventory import InventoryService
from screenshot_crawler.watchlist.service import WatchlistService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="screenshot-crawler-execution-worker")
    parser.add_argument("--request-json", required=True)
    return parser


def _request_namespace(request: dict[str, object], *, site: str, keys: tuple[str, ...]) -> Namespace:
    root = Path(request.get("catalog_path") or "catalog.sqlite").parent
    return Namespace(
        site=site,
        selected_keys=list(keys),
        catalog=Path(request.get("catalog_path") or "catalog.sqlite"),
        watchlist=Path(request.get("watchlist_path") or "watchlist.yaml"),
        crawler_config=Path(request.get("runtime_path") or "crawler.yaml"),
        env_file=Path(request.get("env_file") or ".env"),
        cdp_endpoint=request.get("cdp_endpoint"),
        output_root=Path(request.get("output_root") or root / "output" / "batch"),
        library_dir=Path(request.get("library_dir") or root / "output" / "Books"),
        metrics_root=Path(request.get("metrics_root") or root / "output" / "metrics"),
        grant_only=request.get("resource") if request.get("action") == "grant_only" else None,
        limit=request.get("limit"),
        max_pages=1000,
        max_same_content=3,
        keep_open=False,
    )


def _validated_selection(request: dict[str, object]) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]]]:
    raw_selected = request.get("selected_keys")
    if not isinstance(raw_selected, (list, tuple)):
        raise TypeError("invalid selected_keys in execution request")
    selected = tuple(raw_selected)
    if not selected or any(not isinstance(key, str) or not key for key in selected):
        raise RuntimeError("execution request has no valid selected keys")
    if len(set(selected)) != len(selected):
        raise RuntimeError("execution request contains duplicate selected keys")

    raw_by_site = request.get("keys_by_site")
    if isinstance(raw_by_site, Mapping):
        pairs = raw_by_site.items()
    elif isinstance(raw_by_site, (list, tuple)):
        pairs = raw_by_site
    else:
        raise TypeError("invalid keys_by_site in execution request")
    by_site: dict[str, tuple[str, ...]] = {}
    for pair in pairs:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise RuntimeError("invalid site selection in execution request")
        site, raw_keys = pair
        if not isinstance(site, str) or not site or not isinstance(raw_keys, (list, tuple)):
            raise RuntimeError("invalid site selection in execution request")
        if site in by_site:
            raise RuntimeError("duplicate site selection in execution request")
        keys = tuple(raw_keys)
        if not keys or any(not isinstance(key, str) or not key for key in keys):
            raise RuntimeError("invalid site selection keys in execution request")
        if len(set(keys)) != len(keys):
            raise RuntimeError("duplicate site selection keys in execution request")
        by_site[site] = keys
    flattened = tuple(key for keys in by_site.values() for key in keys)
    if set(flattened) != set(selected) or len(flattened) != len(selected):
        raise RuntimeError("site selection does not match selected_keys")
    raw_sites = request.get("sites")
    if not isinstance(raw_sites, (list, tuple)) or tuple(sorted(by_site)) != tuple(sorted(raw_sites)):
        raise RuntimeError("site selection does not match sites")
    return selected, by_site


def _required_fingerprint(request: dict[str, object]) -> str:
    expected = request.get("plan_fingerprint")
    if not isinstance(expected, str) or not expected:
        raise RuntimeError("execution request is missing its confirmation fingerprint")
    return expected


def _validated_resources(
    request: dict[str, object], sites: Mapping[str, tuple[str, ...]]
) -> dict[str, str]:
    if str(request.get("action")) != "grant_only":
        return {}
    raw = request.get("resources_by_site")
    if isinstance(raw, Mapping):
        resources = dict(raw)
    elif request.get("resource") is not None:
        resources = {site: request["resource"] for site in sites}
    else:
        raise RuntimeError("Grant-only request is missing per-site resources")
    if set(resources) != set(sites) or any(
        not isinstance(site, str)
        or not isinstance(resource, str)
        or not resource
        for site, resource in resources.items()
    ):
        raise RuntimeError("Grant-only resources do not match selected sites")
    return resources


def _aggregate_fingerprint(request: dict[str, object], policies) -> str:
    service = ExecutionPlanService()
    _selected, keys_by_site = _validated_selection(request)
    resources = _validated_resources(request, keys_by_site)
    fingerprints = []
    for site, keys in sorted(keys_by_site.items()):
        preview = service.preview_batch(
            str(request["catalog_path"]),
            str(request["watchlist_path"]),
            policies,
            site=site,
            selected_keys=tuple(keys),
            resource=resources.get(site),
            limit=request.get("limit"),
            runtime_path=str(request.get("runtime_path") or "crawler.yaml"),
            library_dir=str(request.get("library_dir") or ""),
            output_root=str(request.get("output_root") or ""),
            metrics_root=str(request.get("metrics_root") or ""),
            env_file=str(request.get("env_file") or ".env"),
            cdp_endpoint=(
                str(request["cdp_endpoint"])
                if request.get("cdp_endpoint") is not None
                else None
            ),
        )
        if preview.blockers:
            raise RuntimeError("preflight blocked: " + "; ".join(preview.blockers))
        fingerprints.append(preview.fingerprint)
    if len(fingerprints) == 1:
        return fingerprints[0]
    return hashlib.sha256(json.dumps(fingerprints, separators=(",", ":")).encode()).hexdigest()


async def _run(request: dict[str, object]) -> None:
    action = str(request["action"])
    if action not in {"discover", "batch", "grant_only"}:
        raise RuntimeError(f"unsupported execution action: {action}")
    catalog_path = Path(str(request["catalog_path"]))
    watchlist = WatchlistService(str(request["watchlist_path"]))
    policies = _batch_policy_registry()
    _selected, keys_by_site = _validated_selection(request)
    resources = _validated_resources(request, keys_by_site)
    # All selected sites are planned before opening any BrowserSession.  The
    # same lock remains held while the actual site operation runs.
    with CatalogService(catalog_path).job_lock():
        if action == "discover":
            keys = _selected
            mode = str(request.get("mode") or "full")
            if mode not in {"full", "incremental"}:
                raise RuntimeError(f"unsupported Discover mode: {mode}")
            snapshot = InventoryService().load(
                str(request["catalog_path"]),
                str(request["watchlist_path"]),
                runtime_path=str(request.get("runtime_path") or "crawler.yaml"),
            )
            preview = ExecutionPlanService().preview(
                snapshot,
                keys,
                action="discover",
                mode=mode,
                runtime_path=str(request.get("runtime_path") or "crawler.yaml"),
                env_file=str(request.get("env_file") or ".env"),
                cdp_endpoint=(
                    str(request["cdp_endpoint"])
                    if request.get("cdp_endpoint") is not None
                    else None
                ),
                output_root=str(request.get("output_root") or ""),
                library_dir=str(request.get("library_dir") or ""),
                metrics_root=str(request.get("metrics_root") or ""),
            )
            expected = _required_fingerprint(request)
            if preview.blockers or preview.fingerprint != expected:
                raise RuntimeError("Catalog/Watchlist changed after confirmation")
            targets = {target.key: target for target in watchlist.list_targets()}
            selected = [targets.get(key) for key in keys]
            if any(target is None for target in selected):
                raise RuntimeError("Catalog/Watchlist changed after confirmation")
            for site, site_keys in keys_by_site.items():
                for key in site_keys:
                    target = targets.get(key)
                    if target is None or target.site != site:
                        raise RuntimeError("Catalog/Watchlist changed after confirmation")
            # Discovery has no Batch plan; verify identity and key ownership
            # for every target before the first CDP connection.
            if len({target.site for target in selected if target is not None}) == 0:
                raise RuntimeError("no Watchlist keys selected")
            env_path = Path(str(request.get("env_file") or ".env"))
            values = read_env_file(env_path) if env_path.is_file() else {}
            registry = _discovery_registry()
            for target in selected:
                assert target is not None
                if not target.enabled:
                    print(f"Discovery skipped disabled key: {target.key}")
                    continue
                result = await _discover_target(
                    target=target,
                    mode=mode,
                    catalog=CatalogService(catalog_path),
                    registry=registry,
                    values=values,
                    cli_endpoint=request.get("cdp_endpoint"),
                )
                if result.complete is False or result.stopped_reason == "incomplete":
                    raise RuntimeError(
                        f"Discovery incomplete for key {target.key}: "
                        f"{result.stopped_reason}"
                    )
            return

        expected = _required_fingerprint(request)
        current = _aggregate_fingerprint(request, policies)
        if current != expected:
            raise RuntimeError("Catalog/Watchlist changed after confirmation")
        catalog = CatalogService(catalog_path)
        for site, keys in sorted(keys_by_site.items()):
            args = _request_namespace(
                {**request, "resource": resources.get(site)},
                site=site,
                keys=tuple(keys),
            )
            from screenshot_crawler.cli import _run_batch_run_locked

            await _run_batch_run_locked(args, catalog)


def main() -> None:
    args = _parser().parse_args()
    request = json.loads(args.request_json)
    asyncio.run(_run(request))


if __name__ == "__main__":
    main()
