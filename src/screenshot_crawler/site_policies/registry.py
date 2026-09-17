"""Explicit registry for site-specific Batch policies."""

from __future__ import annotations

from collections.abc import Callable

from screenshot_crawler.site_policies.base import SitePolicy, SitePolicyError

SitePolicyFactory = Callable[[], SitePolicy]


class SitePolicyRegistry:
    """Keep site names out of the site-neutral Batch Planner."""

    def __init__(self) -> None:
        self._factories: dict[str, SitePolicyFactory] = {}

    def register(self, site: str, factory: SitePolicyFactory) -> None:
        if site in self._factories:
            raise SitePolicyError(f"Site Policy already registered: {site}")
        self._factories[site] = factory

    def create(self, site: str) -> SitePolicy:
        try:
            factory = self._factories[site]
        except KeyError as exc:
            raise SitePolicyError(f"No Site Policy registered for site: {site}") from exc
        policy = factory()
        if policy.site != site:
            raise SitePolicyError(
                f"Site Policy for {site!r} identifies itself as {policy.site!r}"
            )
        return policy

    def sites(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))
