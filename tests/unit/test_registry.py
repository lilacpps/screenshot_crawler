import pytest

from screenshot_crawler.site_adapters.registry import AdapterRegistry


def test_registry_rejects_duplicate_site() -> None:
    registry = AdapterRegistry()
    registry.register("x", lambda: object())  # type: ignore[arg-type,return-value]
    with pytest.raises(ValueError):
        registry.register("x", lambda: object())  # type: ignore[arg-type,return-value]
