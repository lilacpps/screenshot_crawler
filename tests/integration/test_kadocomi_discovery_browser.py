from __future__ import annotations

from datetime import datetime, timedelta
from urllib.parse import urlsplit

import pytest

from screenshot_crawler.catalog import ArtifactInput, CatalogService
from screenshot_crawler.catalog.service import now_jst
from screenshot_crawler.discovery import DiscoveryAdapterRegistry, DiscoveryService
from screenshot_crawler.site_adapters.kadocomi import KadocomiDiscoveryAdapter
from screenshot_crawler.site_adapters.kadocomi import discovery as kadocomi_discovery
from screenshot_crawler.watchlist import WatchlistTarget

pytestmark = pytest.mark.asyncio(loop_scope="module")

BASE = "https://comic-walker.com"
WORK_ID = "KC_011605_S"
WORK_URL = f"{BASE}/detail/{WORK_ID}?episodeType=first"


def _episode_id(number: int) -> str:
    return f"KC_011605{number:010d}_E"


def _row_html(
    number: int,
    *,
    deadline: datetime | None = None,
    sibling_title: bool = False,
) -> str:
    title = f"\u7B2C{number}\u8A71"
    published = "2026/10/07"
    published_accessible = "2026\u5E7410\u670807\u65E5"
    expiry = ""
    if deadline is not None:
        expiry = (
            f'<span>\u914D\u4FE1\u671F\u9650\uff1A{deadline:%Y/%m/%d %H:%M}</span>'
            f'<time datetime="{deadline:%Y-%m-%d %H:%M:%S}.000">'
            f'{deadline:%Y\u5E74%m\u6708%d\u65E5 %H\u6642%M\u5206}</time>'
        )
    href = (
        f"/detail/{WORK_ID}/episodes/{_episode_id(number)}"
        "?co=true&episodeType=first"
    )
    title_markup = (
        "" if sibling_title else f'<div class="EpisodeThumbnail_title__G1eWj">{title}</div>'
    )
    sibling_title_markup = (
        f'<div class="EpisodeThumbnail_title__G1eWj">{title}</div>'
        if sibling_title
        else ""
    )
    return f'''<li><a class="EpisodeThumbnail_episodeThumbnail__0lFSg" href="{href}">
      <span class="EpisodeThumbnail_updateDate__OYfbI">{published}</span>
      <time datetime="2026-10-07">{published_accessible}</time>
      {title_markup}
      {expiry}
    </a>{sibling_title_markup}</li>'''


def _page_html(
    *,
    rows: list[int],
    declared_count: int,
    deadlines: dict[int, datetime],
    non_episode_child: str | None = None,
    sibling_title_row: int | None = None,
) -> str:
    row_markup_parts = []
    for index, number in enumerate(rows):
        row_markup_parts.append(
            _row_html(
                number,
                deadline=deadlines.get(number),
                sibling_title=number == sibling_title_row,
            )
        )
        if index == 0 and non_episode_child == "ended":
            row_markup_parts.append("<li><p>その他の話は公開終了しました</p></li>")
        elif index == 0 and non_episode_child == "unknown":
            row_markup_parts.append("<li><p>Unclassified list message</p></li>")
    row_markup = "".join(row_markup_parts)
    title = "Fixture Work｜カドコミ (コミックウォーカー)"
    button = f'\u5168{declared_count}\u8A71\u3092\u8868\u793A'
    recommendation = (
        '<aside class="recommendations"><a href="/detail/KC_000001_S/'
        'episodes/KC_0000010000000001_E">Recommendation</a></aside>'
    )
    return f'''<!doctype html><html><head><meta charset="utf-8">
      <meta property="og:title" content="{title}"></head><body>
      <h1>\u3010\u7B2C1\u8A71\u3011Fixture Work</h1>
      <div class="EpisodesTabContents_root__VrJZ1">
        <button type="button">{button}</button>
        <ul class="EpisodesTabContents_episodeList__cIDQz"></ul>
      </div>
      {recommendation}
      <script>
        document.querySelector('button').addEventListener('click', () => {{
          document.querySelector('ul.EpisodesTabContents_episodeList__cIDQz')
            .innerHTML = {row_markup!r};
        }});
      </script></body></html>'''


def _target() -> WatchlistTarget:
    return WatchlistTarget(
        key="kadocomi-test",
        work_key=f"kadocomi:{WORK_ID}",
        site="kadocomi",
        url=WORK_URL,
        label="Watchlist work title",
    )


def _services(tmp_path):
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    registry = DiscoveryAdapterRegistry()
    registry.register("kadocomi", KadocomiDiscoveryAdapter)
    return catalog, DiscoveryService(catalog, registry)


async def _route_listing(page, listing_state: dict) -> None:
    async def fulfill(route) -> None:
        parsed = urlsplit(route.request.url)
        if parsed.path != f"/detail/{WORK_ID}":
            await route.fulfill(status=404, body="")
            return
        body = _page_html(
            rows=listing_state["rows"],
            declared_count=listing_state["declared"],
            deadlines=listing_state["deadlines"],
            non_episode_child=listing_state.get("non_episode_child"),
            sibling_title_row=listing_state.get("sibling_title_row"),
        )
        await route.fulfill(status=200, body=body, content_type="text/html; charset=utf-8")

    await page.route("https://comic-walker.com/**", fulfill)


async def test_kadocomi_full_history_republication_and_null_expiry_preserve_catalog_identity(
    browser_page, tmp_path
) -> None:
    catalog, service = _services(tmp_path)
    target = _target()
    deadline = now_jst().replace(microsecond=0) + timedelta(days=14)
    state = {
        "rows": [1, 2, 3],
        "declared": 3,
        "deadlines": {2: deadline},
        "non_episode_child": "ended",
    }
    await _route_listing(browser_page, state)

    first = await service.discover(browser_page, target, "full")
    assert (first.complete, first.observed_count, first.new_count) == (True, 3, 3)
    initial = {
        source.external_id: source
        for source in catalog.list_sources(site="kadocomi", discovery_key=target.key)
    }
    assert set(initial) == {f"{WORK_ID}:{_episode_id(i)}" for i in (1, 2, 3)}
    assert all(source.available for source in initial.values())
    assert all(source.access_mode == "free" for source in initial.values())
    for number in (1, 3):
        assert initial[f"{WORK_ID}:{_episode_id(number)}"].free_until is None
    assert all(source.display_position is None for source in initial.values())
    assert initial[f"{WORK_ID}:{_episode_id(2)}"].access_mode == "free"
    assert initial[f"{WORK_ID}:{_episode_id(2)}"].free_until is not None
    for external_id, source in initial.items():
        source_target = catalog.find_source_target(source.id, "web")
        assert source_target is not None
        parsed = urlsplit(source_target.locator)
        assert parsed.query == ""
        assert parsed.path.endswith(f"/{external_id.split(':')[1]}")

    catalog.set_source_display_positions(
        site="kadocomi",
        discovery_key=target.key,
        assignments={source.id: index * 10 for index, source in enumerate(initial.values(), 1)},
    )
    item2_source = catalog.find_source(
        "kadocomi", f"{WORK_ID}:{_episode_id(2)}"
    )
    item2 = catalog.get_item(item2_source.item_id)
    source_target = catalog.find_source_target(item2_source.id, "web")
    run = catalog.create_crawl_run(
        item_id=item2.id,
        source_id=item2_source.id,
        target_id=source_target.id,
        access_strategy="direct",
    )
    _, artifact, completed_item = catalog.finalize_successful_crawl(
        run.id,
        artifact=ArtifactInput(
            kind="archive",
            format="zip",
            sha256="a" * 64,
            byte_size=128,
            storage_backend="local",
            locator="test-only.zip",
            state="present",
        ),
        page_count=1,
    )
    completion_time = completed_item.completed_at

    # A different completed source will disappear from the next full list.
    # This checks that unavailable reconciliation does not erase its history.
    item1_source = catalog.find_source(
        "kadocomi", f"{WORK_ID}:{_episode_id(1)}"
    )
    item1 = catalog.get_item(item1_source.item_id)
    item1_target = catalog.find_source_target(item1_source.id, "web")
    run1 = catalog.create_crawl_run(
        item_id=item1.id,
        source_id=item1_source.id,
        target_id=item1_target.id,
        access_strategy="direct",
    )
    _, artifact1, completed_item1 = catalog.finalize_successful_crawl(
        run1.id,
        artifact=ArtifactInput(
            kind="archive",
            format="zip",
            sha256="b" * 64,
            byte_size=256,
            storage_backend="local",
            locator="test-only-source-1.zip",
            state="present",
        ),
        page_count=1,
    )
    completion_time1 = completed_item1.completed_at
    positions = {
        source.external_id: catalog.get_source(source.id).display_position
        for source in initial.values()
    }

    # The listed source disappears while another is added. The same source IDs
    # and durable Completed/Artifact/CrawlRun data remain in Catalog.
    state.update(rows=[2, 4], declared=2, deadlines={})
    second = await service.discover(browser_page, target, "full")
    assert (second.complete, second.observed_count, second.new_count) == (True, 2, 1)
    refreshed2 = catalog.find_source("kadocomi", f"{WORK_ID}:{_episode_id(2)}")
    assert refreshed2.id == item2_source.id
    assert refreshed2.free_until is None
    assert refreshed2.access_mode == "free"
    assert refreshed2.available is True
    disappeared1 = catalog.find_source("kadocomi", f"{WORK_ID}:{_episode_id(1)}")
    assert disappeared1.id == item1_source.id
    assert disappeared1.available is False
    assert catalog.find_source("kadocomi", f"{WORK_ID}:{_episode_id(3)}").available is False
    source4 = catalog.find_source("kadocomi", f"{WORK_ID}:{_episode_id(4)}")
    assert source4 is not None and source4.display_position is None
    assert catalog.get_item(item2.id).status == "completed"
    assert catalog.get_item(item2.id).completed_at == completion_time
    assert catalog.get_crawl_run(run.id).status == "succeeded"
    assert [item.id for item in catalog.list_artifacts(item_id=item2.id)] == [artifact.id]
    assert catalog.get_item(item1.id).status == "completed"
    assert catalog.get_item(item1.id).completed_at == completion_time1
    assert catalog.get_crawl_run(run1.id).status == "succeeded"
    assert [item.id for item in catalog.list_artifacts(item_id=item1.id)] == [artifact1.id]
    for external_id, position in positions.items():
        assert catalog.find_source("kadocomi", external_id).display_position == position

    # Republishing the same external identities restores availability without
    # replacing their Sources or historical Item/Artifact identities.
    state.update(rows=[1, 2, 3, 4], declared=4, deadlines={})
    third = await service.discover(browser_page, target, "full")
    assert (third.complete, third.observed_count, third.new_count) == (True, 4, 0)
    for number in (1, 2, 3, 4):
        restored = catalog.find_source("kadocomi", f"{WORK_ID}:{_episode_id(number)}")
        assert restored.available is True
        assert restored.display_position == positions.get(restored.external_id)
    assert catalog.find_source("kadocomi", f"{WORK_ID}:{_episode_id(2)}").id == item2_source.id
    assert catalog.get_item(item2.id).status == "completed"
    assert catalog.get_crawl_run(run.id).id == run.id
    assert catalog.get_artifact(artifact.id).id == artifact.id
    restored1 = catalog.find_source("kadocomi", f"{WORK_ID}:{_episode_id(1)}")
    assert restored1.id == item1_source.id
    assert restored1.available is True
    assert catalog.get_item(item1.id).status == "completed"
    assert catalog.get_item(item1.id).completed_at == completion_time1
    assert catalog.get_crawl_run(run1.id).id == run1.id
    assert catalog.get_artifact(artifact1.id).id == artifact1.id


async def test_kadocomi_incomplete_full_does_not_mark_missing_sources_unavailable(
    browser_page, tmp_path, monkeypatch
) -> None:
    catalog, service = _services(tmp_path)
    target = _target()
    state = {"rows": [1, 2, 3], "declared": 3, "deadlines": {}}
    await _route_listing(browser_page, state)
    first = await service.discover(browser_page, target, "full")
    assert first.complete is True
    monkeypatch.setattr(kadocomi_discovery, "SETTLEMENT_TIMEOUT_SECONDS", 0.02)
    monkeypatch.setattr(kadocomi_discovery, "SETTLEMENT_INTERVAL_MS", 1)
    state.update(rows=[1, 2], declared=3)
    incomplete = await service.discover(browser_page, target, "full")
    assert incomplete.complete is False
    assert incomplete.stopped_reason == "incomplete"
    assert incomplete.observed_count == 0
    assert all(
        source.available
        for source in catalog.list_sources(site="kadocomi", discovery_key=target.key)
    )


@pytest.mark.parametrize(
    ("non_episode_child", "sibling_title_row"),
    [("unknown", None), (None, 2)],
)
async def test_kadocomi_unknown_list_shapes_fail_closed(
    browser_page, tmp_path, non_episode_child, sibling_title_row
) -> None:
    catalog, service = _services(tmp_path)
    target = _target()
    state = {
        "rows": [1, 2, 3],
        "declared": 3,
        "deadlines": {},
        "non_episode_child": non_episode_child,
        "sibling_title_row": sibling_title_row,
    }
    await _route_listing(browser_page, state)

    result = await service.discover(browser_page, target, "full")

    assert result.complete is False
    assert result.observed_count == 0
    assert result.stopped_reason == "incomplete"
    assert catalog.list_sources(site="kadocomi", discovery_key=target.key) == []


async def test_kadocomi_incremental_does_not_change_unseen_sources(browser_page, tmp_path) -> None:
    catalog, service = _services(tmp_path)
    target = _target()
    state = {"rows": [1, 2, 3, 4], "declared": 4, "deadlines": {}}
    await _route_listing(browser_page, state)
    first = await service.discover(browser_page, target, "full")
    assert first.complete is True
    unseen_before = catalog.find_source("kadocomi", f"{WORK_ID}:{_episode_id(4)}")
    state.update(rows=[1, 2, 3], declared=3)
    incremental = await service.discover(browser_page, target, "incremental")
    assert incremental.complete is None
    assert incremental.observed_count == 3
    unseen_after = catalog.find_source("kadocomi", f"{WORK_ID}:{_episode_id(4)}")
    assert unseen_after.id == unseen_before.id
    assert unseen_after.available is True
    assert unseen_after.last_seen_at == unseen_before.last_seen_at

