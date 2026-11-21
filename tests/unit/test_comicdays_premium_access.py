from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from screenshot_crawler.core.errors import UnknownPageStateError
from screenshot_crawler.site_adapters.base import AccessResourceResolution
from screenshot_crawler.site_adapters.comicdays import premium_access as module


def _pool(resource="premium_ticket", size=10):
    return tuple(SimpleNamespace(
        site="comicdays", work_id=1, source_id=i, external_id=str(i),
        locator=f"https://comic-days.com/episode/{i}", access_strategy="quota",
        consumes_quota=True, quota_resource=resource,
    ) for i in range(1, size + 1))


@pytest.mark.parametrize("count,charged,expected", [(3, False, 3), (0, False, 0), (7, True, 0)])
async def test_stock_bounds_pool_before_any_selected_episode_entry(monkeypatch, count, charged, expected):
    page = SimpleNamespace(url="", wait_for_timeout=AsyncMock())
    visited = []

    async def goto(url, **kwargs):
        visited.append(url)
        page.url = url
        return SimpleNamespace(status=200)

    page.goto = goto
    monkeypatch.setattr(module, "_series_id_from_page", AsyncMock(return_value="900"))
    monkeypatch.setattr(module, "observe_comicdays_ticket", AsyncMock(return_value=SimpleNamespace(
        event_ticket_count=count, ticket_present=True, is_charged=charged,
    )))
    feed = AsyncMock(return_value=[{"episode_id": str(i)} for i in range(1, 1001)])
    monkeypatch.setattr(module, "fetch_comicdays_atom", feed)
    pool = _pool(size=1000)
    result = await module.resolve_ticket_candidates(page, pool, "premium_ticket", timeout_ms=15000)
    assert result.selected_source_ids == tuple(range(1, expected + 1))
    assert len(result.skipped_source_reasons) == 1000 - expected
    assert result.stop_resource_pass == (count == 0)
    assert visited == [module.HOME_URL, pool[0].locator]
    page.wait_for_timeout.assert_awaited_once_with(3000)
    assert feed.await_count == bool(expected)


@pytest.mark.parametrize("bad_count", [None, True, -1, "7"])
async def test_unknown_stock_never_selects_candidates(monkeypatch, bad_count):
    page = SimpleNamespace(url="", wait_for_timeout=AsyncMock())

    async def goto(url, **kwargs):
        page.url = url
        return SimpleNamespace(status=200)

    page.goto = goto
    monkeypatch.setattr(module, "_series_id_from_page", AsyncMock(return_value="900"))
    monkeypatch.setattr(module, "observe_comicdays_ticket", AsyncMock(return_value=SimpleNamespace(
        event_ticket_count=bad_count, ticket_present=True, is_charged=False,
    )))
    with pytest.raises(UnknownPageStateError, match="balance is unknown"):
        await module.resolve_ticket_candidates(page, _pool(), "premium_ticket", timeout_ms=15000)


async def test_work_ticket_resolution_never_checks_premium_or_visits_home():
    result = await module.resolve_ticket_candidates(
        object(), _pool("work_ticket", 1), "work_ticket", timeout_ms=15000,
    )
    assert result.selected_source_ids == (1,)


def test_exhausted_selection_is_empty_and_flag_is_boolean():
    with pytest.raises(ValueError, match="empty"):
        AccessResourceResolution((1,), stop_resource_pass=True)
    with pytest.raises(ValueError, match="boolean"):
        AccessResourceResolution(stop_resource_pass=1)
