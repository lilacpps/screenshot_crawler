from __future__ import annotations

import pytest

from screenshot_crawler.discovery import (
    DiscoveredItem,
    DiscoveredRecord,
    DiscoveredSource,
    DiscoveryIncompleteError,
)
from screenshot_crawler.site_adapters.jumpplus.discovery import JumpPlusDiscoveryAdapter
from screenshot_crawler.site_adapters.zeblack.discovery import ZeblackDiscoveryAdapter
from screenshot_crawler.watchlist import DiscoveryScope, WatchlistTarget

pytestmark = pytest.mark.asyncio(loop_scope="module")


def _records(site: str, ids: list[str]) -> list[DiscoveredRecord]:
    return [
        DiscoveredRecord(
            item=DiscoveredItem(canonical_title="fixture", kind="episode", order_label=f"#{index + 1}"),
            source=DiscoveredSource(
                external_id=external_id,
                url=(
                    f"https://shonenjumpplus.com/episode/{external_id}"
                    if site == "jumpplus"
                    else f"https://zebrack-comic.shueisha.co.jp/title/5123/chapter/{external_id}/viewer"
                ),
                access_mode="free",
                available=True,
                global_display_position=len(ids) - index,
            ),
        )
        for index, external_id in enumerate(ids)
    ]


def _target(site: str, scope: DiscoveryScope | None = None) -> WatchlistTarget:
    return WatchlistTarget(
        key=f"{site}-fixture",
        work_key="fixture-work",
        site=site,
        url=(
            "https://shonenjumpplus.com/episode/123"
            if site == "jumpplus"
            else "https://zebrack-comic.shueisha.co.jp/title/5123/chapter/list"
        ),
        label="fixture",
        discovery_scope=scope,
    )


async def test_jumpplus_preview_prepare_replay_and_expiry_are_browser_backed(
    browser_page, monkeypatch
) -> None:
    await browser_page.set_content(
        '<main data-fixture-site="jumpplus"><ul><li>synthetic episode</li></ul></main>'
    )
    assert await browser_page.locator("main[data-fixture-site='jumpplus']").count() == 1
    adapter = JumpPlusDiscoveryAdapter()
    records = _records("jumpplus", ["300", "200", "100"])
    calls = 0

    async def load_complete(*_args):
        nonlocal calls
        calls += 1
        return "series-fixture", records

    monkeypatch.setattr(adapter, "_load_complete_records", load_complete)
    target = _target("jumpplus", DiscoveryScope(excluded_external_ids=("200",)))
    preview = await adapter.preview_complete_listing(browser_page, _target("jumpplus"))
    assert preview.ready
    assert [row.site_position for row in preview.rows] == [3, 2, 1]

    malformed = _target("jumpplus", DiscoveryScope(excluded_external_ids=("999",)))
    await adapter.prepare_exclusion_preview(browser_page, malformed)
    with pytest.raises(DiscoveryIncompleteError, match="excluded episode"):
        _ = [record async for record in adapter.iter_records(browser_page, malformed, "full")]

    await adapter.prepare_exclusion_preview(browser_page, target)
    observed = [record async for record in adapter.iter_records(browser_page, target, "full")]
    assert [record.source.external_id for record in observed] == ["300", "100"]
    assert calls == 3  # standalone + malformed/normal preparations; replay rereads zero times

    await adapter.prepare_exclusion_preview(browser_page, target)
    adapter._exclusion_preview_cache["expires_at"] = 0
    with pytest.raises(DiscoveryIncompleteError, match="fresh prepared"):
        _ = [record async for record in adapter.iter_records(browser_page, target, "full")]


async def test_zeblack_preview_prepare_replay_and_target_mismatch_fail_closed(
    browser_page, monkeypatch
) -> None:
    await browser_page.set_content(
        '<main data-fixture-site="zeblack"><ul><li>synthetic chapter</li></ul></main>'
    )
    assert await browser_page.locator("main[data-fixture-site='zeblack']").count() == 1
    adapter = ZeblackDiscoveryAdapter()
    records = _records("zeblack", ["303", "202", "101"])
    calls = 0

    async def load_listing(*_args):
        nonlocal calls
        calls += 1
        return object(), object()

    def build_records(*_args, **_kwargs):
        return records

    monkeypatch.setattr(adapter, "_load_listing", load_listing)
    monkeypatch.setattr(adapter, "_build_records", build_records)
    target = _target("zeblack", DiscoveryScope(excluded_external_ids=("202",)))
    malformed = _target("zeblack", DiscoveryScope(excluded_external_ids=("999",)))
    await adapter.prepare_exclusion_preview(browser_page, malformed)
    with pytest.raises(DiscoveryIncompleteError, match="excluded chapter"):
        _ = [record async for record in adapter.iter_records(browser_page, malformed, "full")]

    await adapter.prepare_exclusion_preview(browser_page, target)
    observed = [record async for record in adapter.iter_records(browser_page, target, "full")]
    assert [record.source.external_id for record in observed] == ["303", "101"]
    assert calls == 2

    def unexpected_reload(*_args, **_kwargs):
        raise AssertionError("expired/mismatched exclusion replay must not reread")

    monkeypatch.setattr(adapter, "_load_listing", unexpected_reload)
    mismatch = _target("zeblack", DiscoveryScope(excluded_external_ids=("101",)))
    with pytest.raises(DiscoveryIncompleteError, match="fresh prepared"):
        _ = [record async for record in adapter.iter_records(browser_page, mismatch, "full")]
