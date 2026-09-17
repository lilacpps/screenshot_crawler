"""Explicit registry for Discovery adapters."""

from __future__ import annotations

from collections.abc import Callable

from screenshot_crawler.discovery.base import DiscoveryAdapter

DiscoveryAdapterFactory = Callable[[], DiscoveryAdapter]


class DiscoveryAdapterRegistry:
    """Small registry kept separate from the viewer SiteAdapter registry."""

    def __init__(self) -> None:
        self._factories: dict[str, DiscoveryAdapterFactory] = {}

    def register(self, site: str, factory: DiscoveryAdapterFactory) -> None:
        if site in self._factories:
            raise ValueError(f"Discovery adapter already registered: {site}")
        self._factories[site] = factory

    def create(self, site: str) -> DiscoveryAdapter:
        try:
            factory = self._factories[site]
        except KeyError as exc:
            raise KeyError(f"Unknown discovery adapter: {site}") from exc
        return factory()

    def sites(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))
