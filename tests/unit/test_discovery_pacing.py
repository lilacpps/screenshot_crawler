from types import SimpleNamespace

import pytest

from screenshot_crawler import cli
from screenshot_crawler.discovery.pacing import DiscoveryPacer
from screenshot_crawler.runtime_settings import CrawlerRuntimeSettings, SiteRuntimeSettings
from screenshot_crawler.watchlist.models import WatchlistTarget


async def test_pacing_zero_and_cancellation_during_chunked_wait(monkeypatch):
    waits = []
    cancelled = False

    def checkpoint():
        if cancelled:
            raise RuntimeError("cancelled")

    async def sleep(seconds):
        nonlocal cancelled
        waits.append(seconds)
        cancelled = True

    monkeypatch.setattr("screenshot_crawler.discovery.pacing.asyncio.sleep", sleep)
    pacer = DiscoveryPacer(
        CrawlerRuntimeSettings(sites={"zero": SiteRuntimeSettings(discovery_inter_target_delay_ms=0)}),
        checkpoint=checkpoint,
    )
    await pacer.before_target("zero")
    await pacer.before_target("default")
    assert waits == []
    with pytest.raises(RuntimeError, match="cancelled"):
        await pacer.before_target("default")
    assert waits == [0.2]


async def test_target_preflight_skips_do_not_pace_but_connection_failures_do(monkeypatch):
    waits = []

    async def sleep(seconds):
        waits.append(seconds)

    async def connect(_endpoint):
        raise RuntimeError("connection failed")

    monkeypatch.setattr("screenshot_crawler.discovery.pacing.asyncio.sleep", sleep)
    monkeypatch.setattr(cli.BrowserSession, "connect", connect)
    monkeypatch.setattr(cli, "resolve_cdp_endpoint", lambda **kwargs: "unused")
    pacer = DiscoveryPacer(CrawlerRuntimeSettings(sites={}))
    adapter = SimpleNamespace(supports_incremental_discovery=True, supports_bounded_discovery=True)
    kwargs = {"mode": "incremental", "catalog": None,
              "registry": SimpleNamespace(create=lambda site: adapter),
              "values": {}, "cli_endpoint": None, "pacer": pacer}
    target = WatchlistTarget(key="a", work_key="a", label="A", site="mangaone",
                             url="https://example.invalid/a", enabled=False)
    await cli._discover_target(target=target, **kwargs)
    assert waits == []
    target = WatchlistTarget(key="a", work_key="a", label="A", site="mangaone",
                             url="https://example.invalid/a")
    with pytest.raises(RuntimeError, match="connection failed"):
        await cli._discover_target(target=target, **kwargs)
    adapter.supports_incremental_discovery = False
    with pytest.raises(cli.DiscoveryIncompleteError):
        await cli._discover_target(target=target, **kwargs)
    assert waits == []
    adapter.supports_incremental_discovery = True
    with pytest.raises(RuntimeError, match="connection failed"):
        await cli._discover_target(target=target, **kwargs)
    assert waits == [3.0]
