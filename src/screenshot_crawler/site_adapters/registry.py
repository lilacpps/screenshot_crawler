from __future__ import annotations

from collections.abc import Callable

from screenshot_crawler.site_adapters.base import SiteAdapter

AdapterFactory = Callable[[], SiteAdapter]


class AdapterRegistry:
    """Small explicit registry. Avoid auto-discovery magic in v1."""

    def __init__(self) -> None:
        self._factories: dict[str, AdapterFactory] = {}

    def register(self, site: str, factory: AdapterFactory) -> None:
        if site in self._factories:
            raise ValueError(f"Adapter already registered: {site}")
        self._factories[site] = factory

    def create(self, site: str) -> SiteAdapter:
        try:
            factory = self._factories[site]
        except KeyError as exc:
            raise KeyError(f"Unknown site adapter: {site}") from exc
        return factory()

    def sites(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))
