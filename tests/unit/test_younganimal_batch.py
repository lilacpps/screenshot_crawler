from __future__ import annotations

import pytest

from screenshot_crawler.core.errors import UnknownPageStateError, UnsupportedAccessStrategyError
from screenshot_crawler.site_adapters.younganimal.adapter import YounganimalAdapter

WORK_ID = "aee4fa742b0fe"
EPISODE_ID = "55889b8a851cb"
EXTERNAL_ID = f"{WORK_ID}:{EPISODE_ID}"
EPISODE_URL = f"https://younganimal.com/episodes/{EPISODE_ID}"


@pytest.mark.asyncio
async def test_younganimal_batch_uses_catalog_identity_and_direct_episode_entry() -> None:
    adapter = YounganimalAdapter()
    await adapter.configure_target_identity(EXTERNAL_ID, "opaque-catalog-work-key")

    await adapter.configure_run(object(), "direct")
    entry_url = adapter.resolve_initial_navigation_url(EPISODE_URL)

    assert entry_url == EPISODE_URL
    assert adapter._work_id == WORK_ID
    assert adapter._target_url == EPISODE_URL
    assert adapter._preflight_work_url is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "external_id",
    [
        "",
        f"{WORK_ID}:{EPISODE_ID.upper()}",
        f"{WORK_ID}:not-an-episode",
        f"{WORK_ID}:{EPISODE_ID}:extra",
    ],
)
async def test_younganimal_batch_rejects_malformed_catalog_identity(external_id: str) -> None:
    adapter = YounganimalAdapter()
    with pytest.raises(UnknownPageStateError, match="identity is malformed"):
        await adapter.configure_target_identity(external_id, "opaque-work-key")


@pytest.mark.asyncio
async def test_younganimal_batch_rejects_url_or_strategy_that_disagrees_with_identity() -> None:
    adapter = YounganimalAdapter()
    await adapter.configure_target_identity(EXTERNAL_ID, "opaque-work-key")

    with pytest.raises(UnknownPageStateError, match="differs from the configured Catalog target"):
        adapter.resolve_initial_navigation_url(
            "https://younganimal.com/episodes/0000000000001"
        )
    with pytest.raises(UnknownPageStateError, match="exact canonical episode URL"):
        adapter.resolve_initial_navigation_url(f"{EPISODE_URL}?extra=1")
    with pytest.raises(UnsupportedAccessStrategyError, match="direct.*only"):
        await adapter.configure_run(object(), "auto")


@pytest.mark.asyncio
async def test_younganimal_manual_path_cannot_request_batch_direct_strategy() -> None:
    adapter = YounganimalAdapter(preflight_work_url=f"https://younganimal.com/series/{WORK_ID}")
    assert adapter.resolve_initial_navigation_url(EPISODE_URL) == EPISODE_URL

    with pytest.raises(UnsupportedAccessStrategyError, match="auto.*only"):
        await adapter.configure_run(object(), "direct")
