"""Site-neutral preflight checks for Discovery request capabilities."""

from __future__ import annotations

from typing import TYPE_CHECKING

from screenshot_crawler.discovery.models import DiscoveryResult

if TYPE_CHECKING:
    from screenshot_crawler.discovery.base import DiscoveryAdapter
    from screenshot_crawler.watchlist.models import WatchlistTarget


def discovery_capability_error(
    adapter: DiscoveryAdapter,
    target: WatchlistTarget,
    mode: str,
) -> str | None:
    """Return a request-capability blocker before any Catalog/browser work."""

    if mode == "incremental" and getattr(adapter, "supports_incremental_discovery", True) is not True:
        return "Discovery adapter does not support incremental discovery"
    scope = target.discovery_scope
    if scope is None:
        return None
    if getattr(adapter, "supports_bounded_discovery", False) is not True:
        return "Discovery adapter does not support bounded scope"
    if (
        scope.from_url is None
        and scope.through_url is None
        and getattr(adapter, "supports_exclusion_only_scope", False) is not True
    ):
        return "Discovery adapter does not support exclusion-only scope"
    if (
        scope.excluded_external_ids
        and getattr(adapter, "supports_exclusion_replay", False) is not True
    ):
        return "Exclusion scope requires an adapter that replays the validated complete listing"
    return None


def blocked_discovery_result(target: WatchlistTarget, mode: str, error: str) -> DiscoveryResult:
    """Build the standard zero-observation result for a preflight rejection."""

    return DiscoveryResult(
        mode=mode,  # type: ignore[arg-type]
        target_key=target.key,
        observed_count=0,
        new_count=0,
        known_count=0,
        complete=False if mode == "full" else None,
        stopped_reason="incomplete",
        warnings=(),
        error=error,
    )
