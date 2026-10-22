from __future__ import annotations

import json
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID

import pytest

from screenshot_crawler.catalog import ArtifactInput, CatalogService
from screenshot_crawler.catalog.service import now_jst
from screenshot_crawler.core.errors import AccessStopError
from screenshot_crawler.discovery import DiscoveryAdapterRegistry, DiscoveryService
from screenshot_crawler.site_adapters.kadocomi import KadocomiDiscoveryAdapter
from screenshot_crawler.site_adapters.kadocomi import discovery as kadocomi_discovery
from screenshot_crawler.watchlist import DiscoveryScope, WatchlistTarget
from screenshot_crawler.watchlist.reconcile import ScopeReconciler
from screenshot_crawler.watchlist.service import WatchlistService

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
    ended_after: tuple[int, ...] = (0,),
) -> str:
    row_markup_parts = []
    ended_marker = "<li><p>その他の話は公開終了しました</p></li>"
    if non_episode_child == "ended_at_start":
        row_markup_parts.append(ended_marker)
    for index, number in enumerate(rows):
        row_markup_parts.append(
            _row_html(
                number,
                deadline=deadlines.get(number),
                sibling_title=number == sibling_title_row,
            )
        )
        if non_episode_child == "ended" and index in ended_after:
            row_markup_parts.append(ended_marker)
        elif index == 0 and non_episode_child == "ended_adjacent":
            row_markup_parts.extend([ended_marker, ended_marker])
        elif non_episode_child == "ended_malformed":
            if index == 0:
                row_markup_parts.append(ended_marker)
            elif index == 1:
                row_markup_parts.append(
                    '<li class="unknown"><p>その他の話は公開終了しました</p></li>'
                )
        elif index == 0 and non_episode_child == "unknown":
            row_markup_parts.append("<li><p>Unclassified list message</p></li>")
    if non_episode_child == "ended_at_end":
        row_markup_parts.append(ended_marker)
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
            ended_after=listing_state.get("ended_after", (0,)),
        )
        await route.fulfill(status=200, body=body, content_type="text/html; charset=utf-8")

    await page.route("https://comic-walker.com/**", fulfill)


@pytest.mark.parametrize(
    "ended_after", [(), (0,), (0, 1)], ids=["zero_markers", "one_marker", "two_markers"]
)
async def test_kadocomi_full_history_republication_and_null_expiry_preserve_catalog_identity(
    browser_page, tmp_path, ended_after
) -> None:
    catalog, service = _services(tmp_path)
    target = _target()
    deadline = now_jst().replace(microsecond=0) + timedelta(days=14)
    state = {
        "rows": [1, 2, 3],
        "declared": 3,
        "deadlines": {2: deadline},
        "non_episode_child": "ended",
        "ended_after": ended_after,
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
    state.update(rows=[2, 4], declared=2, deadlines={}, ended_after=ended_after[:1])
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
    state.update(rows=[1, 2, 3, 4], declared=4, deadlines={}, ended_after=ended_after)
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
    [
        ("unknown", None),
        (None, 2),
        ("ended_adjacent", None),
        ("ended_at_start", None),
        ("ended_at_end", None),
        ("ended_malformed", None),
    ],
)
async def test_kadocomi_unknown_list_shapes_fail_closed(
    browser_page, tmp_path, monkeypatch, non_episode_child, sibling_title_row
) -> None:
    monkeypatch.setattr(kadocomi_discovery, "SETTLEMENT_TIMEOUT_SECONDS", 0.25)
    monkeypatch.setattr(kadocomi_discovery, "SETTLEMENT_INTERVAL_MS", 10)
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
    state = {
        "rows": [1, 2, 3, 4], "declared": 4, "deadlines": {},
        "non_episode_child": "ended", "ended_after": (0, 1),
    }
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


def _native_episodes() -> list[dict[str, object]]:
    labels = {
        1: "Episode 1",
        2: "Episode 2",
        3: "Episode 4-A",
        4: "Episode 44",
        5: "Episode 59",
        6: "Episode 60",
        7: "Episode 77",
    }
    positions = {1: 1, 2: 2, 3: 6, 4: 88, 5: 89, 6: 108, 7: 125}
    active = {1, 2, 5}
    return [
        {
            "code": _episode_id(number),
            "id": str(UUID(int=500 + number)),
            "title": labels[number],
            "serviceId": "web",
            "type": "normal",
            "isActive": number in active,
            "internal": {
                "episodeNo": positions[number],
                "episodetype": "normal",
                "pageCount": 12,
            },
            "hasRead": False,
            "deliveryPeriod": None,
        }
        for number in range(1, 8)
    ]


def _native_page_html(
    *,
    episodes: list[dict[str, object]] | None = None,
    expand: bool = False,
    expand_count: int = 3,
    omit_marker: bool = False,
    post_click: str | None = None,
) -> str:
    episodes = episodes or _native_episodes()
    children: list[str] = []
    for index, episode in enumerate(episodes):
        if episode["isActive"] is not True:
            continue
        code = str(episode["code"])
        href = f"/detail/{WORK_ID}/episodes/{code}"
        title = str(episode["title"])
        children.append(
            f'''<li><a href="{href}"><div class="EpisodeThumbnail_title__fixture">{title}</div>
              <span>2026/10/07 {title}</span></a></li>'''
        )
        if (
            index + 1 < len(episodes)
            and episodes[index + 1]["isActive"] is False
            and not omit_marker
        ):
            children.append(
                f"<li><p>{kadocomi_discovery._ENDED_EPISODES_PLACEHOLDER}</p></li>"
            )
    rendered = "".join(children)
    data = {
        "props": {
            "pageProps": {
                "dehydratedState": {
                    "queries": [
                        {
                            "queryKey": [
                                "/api/contents/details/work",
                                {"workCode": WORK_ID},
                            ],
                            "state": {
                                "data": {
                                    "work": {
                                        "code": WORK_ID,
                                        "id": str(UUID(int=900)),
                                        "title": "Fixture Work",
                                    },
                                    "firstEpisodes": {
                                        "total": len(episodes),
                                        "result": episodes,
                                    },
                                    "latestEpisodes": {
                                        "total": len(episodes),
                                        "result": list(reversed(episodes)),
                                    },
                                }
                            },
                        }
                    ]
                }
            }
        }
    }
    initial_rows = "" if expand else rendered
    button = f'<button type="button">全{expand_count}話を表示</button>' if expand else ""
    on_click = (
        f"document.querySelector('button').addEventListener('click', () => "
        f"{{ document.querySelector('ul').innerHTML = {rendered!r}; {post_click or ''} }});"
        if expand
        else ""
    )
    return f'''<!doctype html><html><head><meta charset="utf-8">
      <meta property="og:title" content="Fixture Work{kadocomi_discovery._OG_TITLE_SUFFIX}">
      <script id="__NEXT_DATA__" type="application/json">{json.dumps(data, ensure_ascii=False)}</script>
      </head><body><h1>Fixture Work</h1>
      <div class="EpisodesTabContents_root__fixture">{button}
        <ul class="EpisodesTabContents_episodeList__fixture">{initial_rows}</ul>
      </div><script>{on_click}</script></body></html>'''


async def _route_native_listing(page, html: str) -> None:
    async def fulfill(route) -> None:
        parsed = urlsplit(route.request.url)
        if parsed.path != f"/detail/{WORK_ID}":
            await route.fulfill(status=404, body="")
            return
        await route.fulfill(body=html, content_type="text/html; charset=utf-8")

    await page.route("https://comic-walker.com/**", fulfill)


def _native_target(*, scope=None, archive_order: int | None = 1) -> WatchlistTarget:
    return WatchlistTarget(
        key="kadocomi-test",
        work_key=f"kadocomi:{WORK_ID}",
        site="kadocomi",
        url=WORK_URL,
        label="Fixture work",
        discovery_scope=scope,
        archive_order=archive_order,
    )


def _write_native_watchlist(path, target: WatchlistTarget, scope: DiscoveryScope) -> None:
    path.write_text(
        "targets:\n"
        f"  - key: {target.key}\n"
        f"    work_key: {target.work_key}\n"
        f"    site: {target.site}\n"
        f"    url: {target.url}\n"
        f"    label: {target.label}\n"
        f"    archive_order: {target.archive_order}\n"
        "    discovery_scope:\n"
        f"      from_url: {scope.from_url}\n"
        f"      through_url: {scope.through_url}\n",
        encoding="utf-8",
    )


async def test_kadocomi_archive_order_full_inventory_scope_sync_preserves_native_positions(
    browser_page,
    tmp_path,
) -> None:
    catalog, service = _services(tmp_path)
    scope = DiscoveryScope(
        from_url=f"{BASE}/detail/{WORK_ID}/episodes/{_episode_id(5)}",
        through_url=f"{BASE}/detail/{WORK_ID}/episodes/{_episode_id(2)}",
    )
    target = _native_target(scope=scope)
    watchlist_path = tmp_path / "watchlist.yaml"
    _write_native_watchlist(watchlist_path, target, scope)
    actual_target = WatchlistService(watchlist_path).list_targets()[0]
    await _route_native_listing(browser_page, _native_page_html(expand=True))

    result = await service.discover(browser_page, actual_target, "full")

    assert result.complete is True
    assert result.observed_count == 4
    evidence = catalog.get_discovery_inventory_evidence(actual_target.key)
    assert evidence is not None
    assert evidence.listing_identity == f"kadocomi-native-work:{WORK_ID}"
    assert [
        (position.external_id, position.display_position, position.in_scope)
        for position in evidence.positions
    ] == [
        (f"{WORK_ID}:{_episode_id(1)}", 1, False),
        (f"{WORK_ID}:{_episode_id(2)}", 2, True),
        (f"{WORK_ID}:{_episode_id(3)}", 6, True),
        (f"{WORK_ID}:{_episode_id(4)}", 88, True),
        (f"{WORK_ID}:{_episode_id(5)}", 89, True),
        (f"{WORK_ID}:{_episode_id(6)}", 108, False),
        (f"{WORK_ID}:{_episode_id(7)}", 125, False),
    ]
    sources = catalog.list_sources(site="kadocomi", discovery_key=actual_target.key)
    assert len(sources) == 4
    assert {
        source.external_id: (source.display_position, source.available, source.access_mode)
        for source in sources
    } == {
        f"{WORK_ID}:{_episode_id(2)}": (2, True, "free"),
        f"{WORK_ID}:{_episode_id(3)}": (6, False, "unknown"),
        f"{WORK_ID}:{_episode_id(4)}": (88, False, "unknown"),
        f"{WORK_ID}:{_episode_id(5)}": (89, True, "free"),
    }

    reconciler = ScopeReconciler(WatchlistService(watchlist_path), catalog)
    preview = reconciler.preview(target.work_key)
    assert preview.ready
    applied_sources = reconciler.apply(preview)
    assert all(source.acquisition_enabled for source in applied_sources)
    ordinal_rows = preview.archive_order_preview["positions"]
    assert len(ordinal_rows) == 4
    assert {row["archive_position"] for row in ordinal_rows} == {1, 2, 3, 4}

    unavailable_source = catalog.find_source(
        "kadocomi", f"{WORK_ID}:{_episode_id(3)}"
    )
    unavailable_item = catalog.get_item(unavailable_source.item_id)
    unavailable_target = catalog.find_source_target(unavailable_source.id, "web")
    crawl_run = catalog.create_crawl_run(
        item_id=unavailable_item.id,
        source_id=unavailable_source.id,
        target_id=unavailable_target.id,
        access_strategy="direct",
    )
    _, historical_artifact, completed_item = catalog.finalize_successful_crawl(
        crawl_run.id,
        artifact=ArtifactInput(
            kind="archive",
            format="zip",
            sha256="c" * 64,
            byte_size=256,
            storage_backend="local",
            locator="isolated-native-test.zip",
            state="present",
        ),
        page_count=1,
    )
    assert completed_item.status == "completed"
    initial_source_ids = {
        source.external_id: source.id
        for source in catalog.list_sources(site="kadocomi", discovery_key=target.key)
    }

    narrow_scope = DiscoveryScope(
        from_url=scope.from_url,
        through_url=f"{BASE}/detail/{WORK_ID}/episodes/{_episode_id(3)}",
    )
    _write_native_watchlist(watchlist_path, target, narrow_scope)
    narrow_target = WatchlistService(watchlist_path).list_targets()[0]
    assert not reconciler.preview(target.work_key).ready
    narrowed = await service.discover(browser_page, narrow_target, "full")
    assert narrowed.complete is True
    assert narrowed.observed_count == 3
    narrow_preview = reconciler.preview(target.work_key)
    assert narrow_preview.ready
    reconciler.apply(narrow_preview)
    assert not catalog.get_source(initial_source_ids[f"{WORK_ID}:{_episode_id(2)}"]).acquisition_enabled

    _write_native_watchlist(watchlist_path, target, scope)
    reexpanded_target = WatchlistService(watchlist_path).list_targets()[0]
    reexpanded = await service.discover(browser_page, reexpanded_target, "full")
    assert reexpanded.complete is True
    assert reexpanded.observed_count == 4
    reexpanded_preview = reconciler.preview(target.work_key)
    assert reexpanded_preview.ready
    restored_sources = reconciler.apply(reexpanded_preview)
    assert all(source.acquisition_enabled for source in restored_sources)
    assert {
        source.external_id: source.id
        for source in catalog.list_sources(site="kadocomi", discovery_key=target.key)
    } == initial_source_ids
    assert catalog.get_item(unavailable_item.id).status == "completed"
    assert catalog.get_crawl_run(crawl_run.id).status == "succeeded"
    assert catalog.get_artifact(historical_artifact.id).locator == "isolated-native-test.zip"
    assert catalog.get_source(initial_source_ids[f"{WORK_ID}:{_episode_id(3)}"]).available is False


@pytest.mark.parametrize(
    "scope,omit_marker,expand_count",
    [
        (
            DiscoveryScope(from_url=f"{BASE}/detail/{WORK_ID}/episodes/{_episode_id(9)}"),
            False,
            3,
        ),
        (
            DiscoveryScope(
                from_url=f"{BASE}/detail/{WORK_ID}/episodes/{_episode_id(2)}",
                through_url=f"{BASE}/detail/{WORK_ID}/episodes/{_episode_id(5)}",
            ),
            False,
            3,
        ),
        (
            DiscoveryScope(
                from_url=f"{BASE}/detail/{WORK_ID}/episodes/{_episode_id(5)}",
                through_url=f"{BASE}/detail/{WORK_ID}/episodes/{_episode_id(2)}",
            ),
            True,
            3,
        ),
        (
            DiscoveryScope(
                from_url="https://comic-walker.com/detail/KC_000001_S/episodes/KC_0000010000000001_E"
            ),
            False,
            3,
        ),
        (
            DiscoveryScope(
                from_url=f"{BASE}/detail/{WORK_ID}/episodes/{_episode_id(5)}",
                through_url=f"{BASE}/detail/{WORK_ID}/episodes/{_episode_id(2)}",
            ),
            False,
            4,
        ),
    ],
    ids=["unknown-boundary", "reversed-boundaries", "missing-native-marker", "foreign-work", "expand-count-mismatch"],
)
async def test_kadocomi_opt_in_scope_errors_publish_no_sources_or_proof(
    browser_page,
    tmp_path,
    monkeypatch,
    scope,
    omit_marker,
    expand_count,
) -> None:
    monkeypatch.setattr(kadocomi_discovery, "SETTLEMENT_TIMEOUT_SECONDS", 0.03)
    monkeypatch.setattr(kadocomi_discovery, "SETTLEMENT_INTERVAL_MS", 1)
    catalog, service = _services(tmp_path)
    await _route_native_listing(
        browser_page,
        _native_page_html(
            expand=True,
            expand_count=expand_count,
            omit_marker=omit_marker,
        ),
    )

    result = await service.discover(browser_page, _native_target(scope=scope), "full")

    assert result.complete is False
    assert result.observed_count == 0
    assert catalog.list_sources(site="kadocomi") == []
    assert catalog.get_discovery_inventory_evidence("kadocomi-test") is None


@pytest.mark.parametrize("mutation", ["native-title", "foreign-route"])
async def test_kadocomi_native_pre_emission_drift_yields_nothing(
    browser_page,
    tmp_path,
    mutation,
) -> None:
    catalog, service = _services(tmp_path)
    post_click = (
        "const node = document.querySelector('#__NEXT_DATA__'); "
        "const data = JSON.parse(node.textContent); "
        "data.props.pageProps.dehydratedState.queries[0].state.data.work.title = 'Changed Work'; "
        "node.textContent = JSON.stringify(data);"
        if mutation == "native-title"
        else "history.replaceState(null, '', '/detail/KC_000001_S');"
    )
    await _route_native_listing(
        browser_page,
        _native_page_html(expand=True, post_click=post_click),
    )

    result = await service.discover(browser_page, _native_target(), "full")

    assert result.complete is False
    assert result.observed_count == 0
    assert catalog.list_sources(site="kadocomi") == []
    assert catalog.get_discovery_inventory_evidence("kadocomi-test") is None


async def test_kadocomi_final_access_guard_stop_yields_nothing(
    browser_page,
    tmp_path,
    monkeypatch,
) -> None:
    catalog, service = _services(tmp_path)
    await _route_native_listing(browser_page, _native_page_html(expand=True))
    original_check_page = kadocomi_discovery.AccessGuard.check_page
    original_read_native_listing = kadocomi_discovery.KadocomiDiscoveryAdapter._read_native_listing
    final_listing_read = False
    native_listing_reads = 0

    async def mark_final_listing_read(self, page, *, work_id):
        nonlocal final_listing_read, native_listing_reads
        listing = await original_read_native_listing(self, page, work_id=work_id)
        native_listing_reads += 1
        if native_listing_reads == 2:
            final_listing_read = True
        return listing

    async def stop_on_final_check(self, page):
        if final_listing_read:
            raise AccessStopError(
                reason="challenge_detected",
                site="kadocomi",
                url=page.url,
            )
        await original_check_page(self, page)

    monkeypatch.setattr(
        kadocomi_discovery.AccessGuard,
        "check_page",
        stop_on_final_check,
    )
    monkeypatch.setattr(
        kadocomi_discovery.KadocomiDiscoveryAdapter,
        "_read_native_listing",
        mark_final_listing_read,
    )

    result = await service.discover(browser_page, _native_target(), "full")

    assert result.complete is False
    assert result.observed_count == 0
    assert catalog.list_sources(site="kadocomi") == []
    assert catalog.get_discovery_inventory_evidence("kadocomi-test") is None


async def test_kadocomi_native_incremental_does_not_publish_complete_inventory(
    browser_page,
    tmp_path,
) -> None:
    catalog, service = _services(tmp_path)
    await _route_native_listing(browser_page, _native_page_html())

    result = await service.discover(browser_page, _native_target(), "incremental")

    assert result.complete is None
    assert result.observed_count == 7
    assert catalog.get_discovery_inventory_evidence("kadocomi-test") is None
    assert {
        source.display_position
        for source in catalog.list_sources(site="kadocomi", discovery_key="kadocomi-test")
    } == {1, 2, 6, 88, 89, 108, 125}

