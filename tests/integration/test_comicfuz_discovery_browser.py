from __future__ import annotations

import json
from pathlib import Path

import pytest

from screenshot_crawler.catalog import ArtifactInput, CatalogService
from screenshot_crawler.discovery import DiscoveryAdapterRegistry, DiscoveryService
from screenshot_crawler.site_adapters.comicfuz import ComicFuzDiscoveryAdapter
from screenshot_crawler.watchlist import DiscoveryScope, WatchlistTarget

pytestmark = pytest.mark.asyncio(loop_scope="module")

BASE = "https://comic-fuz.com"
WORK_ID = "1970"
WORK_URL = f"{BASE}/manga/{WORK_ID}?position=thumbnail"


def _target(scope: DiscoveryScope | None = None) -> WatchlistTarget:
    return WatchlistTarget(
        key="comicfuz-test",
        work_key=f"comicfuz:{WORK_ID}",
        site="comicfuz",
        url=WORK_URL,
        label="Fixture work",
        discovery_scope=scope,
    )


def _listing_html(
    chapters: list[tuple[str, str]],
    *,
    free_ids: set[str] | None = None,
    duplicate_free_ids: set[str] | None = None,
    hidden_free_ids: set[str] | None = None,
    canonical_work_id: str = WORK_ID,
    current_work_id: str = WORK_ID,
    signin: bool = True,
    signout: bool = False,
    add_control: bool = False,
    replace_on_scroll: bool = False,
    delayed_mutation: str | None = None,
) -> str:
    free_ids = free_ids or set()
    duplicate_free_ids = duplicate_free_ids or set()
    hidden_free_ids = hidden_free_ids or set()
    records = [
        {"chapterId": chapter_id, "chapterMainName": label, "pointConsumption": 88}
        for chapter_id, label in chapters
    ]
    groups = [{"chapters": records[:2]}, {"chapters": records[2:]}]
    groups = [group for group in groups if group["chapters"]]
    rows = "".join(
        f'''<div class="Chapter_chapter__row false false">
          <div class="Chapter_chapter__detail__fixture">
            <h3 class="Chapter_chapter__name__fixture">{label}</h3>
            {('<p class="Chapter_chapter__price_free__fixture">無料</p>' if chapter_id in free_ids else '')}
            {('<p class="Chapter_chapter__price_free__fixture">無料</p>' if chapter_id in duplicate_free_ids else '')}
            {('<p class="Chapter_chapter__price_free__fixture" style="display:none">無料</p>' if chapter_id in hidden_free_ids else '')}
          </div>
        </div>'''
        for chapter_id, label in chapters
    )
    signin_link = '<a href="/account/signin">Sign in</a>' if signin else ""
    signout_link = '<a href="/account/signout">Sign out</a>' if signout else ""
    control = '<button type="button">More</button>' if add_control else ""
    scroll_script = """<script>
      window.addEventListener('scroll', () => {
        const list = document.querySelector('.title_detail_chapters__list__fixture');
        if (list && !list.dataset.changed) {
          list.dataset.changed = '1';
          list.insertAdjacentHTML('beforeend', '<div class="Chapter_chapter__row"><div><h3 class="Chapter_chapter__name__fixture">late row</h3></div></div>');
        }
      });
    </script><style>body { min-height: 1200px; }</style>""" if replace_on_scroll else ""
    next_data = {
        "page": "/manga/[mangaId]",
        "props": {"pageProps": {"chapters": groups}},
    }
    current_path_script = (
        f"<script>history.replaceState(null, '', '/manga/{current_work_id}');</script>"
        if current_work_id != WORK_ID
        else ""
    )
    delayed_scripts = {
        "route": "history.replaceState(null, '', '/manga/999');",
        "canonical": f"document.querySelector('link[rel=canonical]').href = '{BASE}/manga/999';",
        "anonymous": "document.querySelector('a[href=\"/account/signin\"]').remove(); const a=document.createElement('a'); a.href='/account/signout'; document.body.append(a);",
    }
    delayed_script = (
        f"<script>setTimeout(() => {{{delayed_scripts[delayed_mutation]}}}, 150);</script>"
        if delayed_mutation is not None
        else ""
    )
    return f'''<!doctype html><html><head><meta charset="utf-8">
      <title>Synthetic ComicFUZ Work</title>
      <link rel="canonical" href="{BASE}/manga/{canonical_work_id}">
      <script id="__NEXT_DATA__" type="application/json">{json.dumps(next_data, ensure_ascii=False)}</script>
      {current_path_script}{delayed_script}</head><body>{signin_link}{signout_link}
      <div class="title_detail_chapters__list__fixture"><ul>{rows}{control}</ul></div>
      {scroll_script}</body></html>'''


async def _run_discovery(browser_page, tmp_path: Path, html: str, *, scope=None, mode="full"):
    async def fulfill(route) -> None:
        await route.fulfill(body=html, content_type="text/html; charset=utf-8")

    await browser_page.route(f"{BASE}/**", fulfill)
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    registry = DiscoveryAdapterRegistry()
    registry.register("comicfuz", ComicFuzDiscoveryAdapter)
    service = DiscoveryService(catalog, registry)
    result = await service.discover(
        browser_page, _target(scope), mode
    )
    return catalog, result, service


async def test_comicfuz_full_discovery_reconciles_catalog_and_global_positions(
    browser_page,
    tmp_path: Path,
) -> None:
    chapters = [("30", "第3話"), ("20", "第2話"), ("10", "第1話(後編)"), ("1", "第1話(前編)")]
    catalog, result, service = await _run_discovery(
        browser_page,
        tmp_path,
        _listing_html(chapters, free_ids={"20", "1"}),
    )

    sources = catalog.list_sources(site="comicfuz")
    assert result.complete is True
    assert result.observed_count == 4
    assert [source.external_id for source in sources] == [
        "1970:30", "1970:20", "1970:10", "1970:1"
    ]
    assert [source.access_mode for source in sources] == ["unknown", "free", "unknown", "free"]
    assert [source.display_position for source in sources] == [4, 3, 2, 1]
    assert [source.free_until for source in sources] == [None, None, None, None]
    targets_by_source = {
        target.source_id: target.locator for target in catalog.list_source_targets()
    }
    assert [targets_by_source[source.id] for source in sources] == [
        f"{BASE}/manga/viewer/30",
        f"{BASE}/manga/viewer/20",
        f"{BASE}/manga/viewer/10",
        f"{BASE}/manga/viewer/1",
    ]

    rerun = await service.discover(browser_page, _target(), "full")
    assert rerun.complete is True
    assert rerun.new_count == 0
    assert rerun.known_count == 4
    assert len(catalog.list_sources(site="comicfuz")) == 4


async def test_comicfuz_access_refresh_and_incomplete_full_preserve_catalog_history(
    browser_page,
    tmp_path: Path,
) -> None:
    chapters = [("30", "第3話"), ("20", "第2話"), ("10", "第1話(後編)"), ("1", "第1話(前編)")]
    state = {"html": _listing_html(chapters, free_ids={"20"})}

    async def fulfill(route) -> None:
        await route.fulfill(body=state["html"], content_type="text/html; charset=utf-8")

    await browser_page.route(f"{BASE}/**", fulfill)
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    registry = DiscoveryAdapterRegistry()
    registry.register("comicfuz", ComicFuzDiscoveryAdapter)
    service = DiscoveryService(catalog, registry)
    first = await service.discover(browser_page, _target(), "full")
    assert first.complete is True

    source = catalog.find_source("comicfuz", "1970:20")
    assert source is not None and source.access_mode == "free"
    catalog.update_source_external_state(
        "comicfuz",
        source.external_id,
        free_until="2099-10-14T11:00:00+09:00",
    )
    source = catalog.find_source("comicfuz", "1970:20")
    item = catalog.get_item(source.item_id)
    source_target = catalog.find_source_target(source.id, "web")
    run = catalog.create_crawl_run(
        item_id=item.id,
        source_id=source.id,
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

    # Losing the visible free proof must refresh to UNKNOWN and clear a stale
    # expiry, while preserving the existing successful crawl history.
    state["html"] = _listing_html(chapters)
    second = await service.discover(browser_page, _target(), "full")
    assert second.complete is True
    refreshed = catalog.find_source("comicfuz", "1970:20")
    assert refreshed.id == source.id
    assert refreshed.access_mode == "unknown"
    assert refreshed.free_until is None
    assert catalog.get_item(item.id).status == "completed"
    assert catalog.get_item(item.id).completed_at == completion_time
    assert catalog.get_crawl_run(run.id).status == "succeeded"
    assert [saved.id for saved in catalog.list_artifacts(item_id=item.id)] == [artifact.id]

    # A semantic paging control invalidates the next full snapshot. Even with
    # a shorter partial row set, no prior Source is marked unavailable.
    availability_before = {
        source.external_id: source.available for source in catalog.list_sources(site="comicfuz")
    }
    state["html"] = _listing_html([("20", "第2話")], add_control=True)
    incomplete = await service.discover(browser_page, _target(), "full")
    availability_after = {
        source.external_id: source.available for source in catalog.list_sources(site="comicfuz")
    }
    assert incomplete.complete is False
    assert incomplete.observed_count == 0
    assert availability_after == availability_before
    assert catalog.get_item(item.id).status == "completed"
    assert catalog.get_artifact(artifact.id).id == artifact.id


@pytest.mark.parametrize(
    "html_kwargs",
    [
        {"canonical_work_id": "999"},
        {"current_work_id": "999"},
        {"signin": False},
        {"signout": True},
        {"add_control": True},
        {"replace_on_scroll": True},
        {"delayed_mutation": "route"},
        {"delayed_mutation": "canonical"},
        {"delayed_mutation": "anonymous"},
    ],
)
async def test_comicfuz_unverified_listing_fails_before_source_upsert(
    browser_page,
    tmp_path: Path,
    html_kwargs,
) -> None:
    catalog, result, _service = await _run_discovery(
        browser_page,
        tmp_path,
        _listing_html([("3", "第3話"), ("2", "第2話")], **html_kwargs),
    )
    assert result.complete is False
    assert result.stopped_reason == "incomplete"
    assert result.observed_count == 0
    assert catalog.list_sources(site="comicfuz") == []
    assert catalog.list_items() == []


async def test_comicfuz_ambiguous_free_marker_fails_before_source_upsert(
    browser_page,
    tmp_path: Path,
) -> None:
    catalog, result, _service = await _run_discovery(
        browser_page,
        tmp_path,
        _listing_html(
            [("3", "第3話"), ("2", "第2話")],
            free_ids={"3"},
            duplicate_free_ids={"3"},
        ),
    )
    assert result.complete is False
    assert result.observed_count == 0
    assert catalog.list_sources(site="comicfuz") == []


async def test_comicfuz_hidden_free_marker_does_not_classify_source_as_free(
    browser_page,
    tmp_path: Path,
) -> None:
    catalog, result, _service = await _run_discovery(
        browser_page,
        tmp_path,
        _listing_html([("3", "第3話"), ("2", "第2話")], hidden_free_ids={"3"}),
    )
    source = catalog.find_source("comicfuz", "1970:3")
    assert result.complete is True
    assert source is not None
    assert source.access_mode == "unknown"


async def test_comicfuz_bounded_discovery_keeps_full_list_positions(
    browser_page,
    tmp_path: Path,
) -> None:
    chapters = [("4", "第4話"), ("3", "第3話"), ("2", "第2話"), ("1", "第1話")]
    scope = DiscoveryScope(
        from_url=f"{BASE}/manga/viewer/3",
        through_url=f"{BASE}/manga/viewer/2",
    )
    catalog, result, _service = await _run_discovery(
        browser_page,
        tmp_path,
        _listing_html(chapters, free_ids={"3"}),
        scope=scope,
    )
    sources = catalog.list_sources(site="comicfuz")
    assert result.complete is True
    assert [source.external_id for source in sources] == ["1970:3", "1970:2"]
    assert [source.display_position for source in sources] == [3, 2]


async def test_comicfuz_incremental_uses_shared_known_streak_without_local_renumbering(
    browser_page,
    tmp_path: Path,
) -> None:
    chapters = [(str(value), f"第{value}話") for value in range(7, 0, -1)]
    html = _listing_html(chapters, free_ids={"7"})

    async def fulfill(route) -> None:
        await route.fulfill(body=html, content_type="text/html; charset=utf-8")

    await browser_page.route(f"{BASE}/**", fulfill)
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    registry = DiscoveryAdapterRegistry()
    registry.register("comicfuz", ComicFuzDiscoveryAdapter)
    service = DiscoveryService(catalog, registry)
    full = await service.discover(browser_page, _target(), "full")
    incremental = await service.discover(browser_page, _target(), "incremental")

    assert full.complete is True
    assert incremental.complete is None
    assert incremental.observed_count == 5
    assert incremental.known_count == 5
    assert incremental.stopped_reason == "known_streak"
    by_id = {source.external_id: source for source in catalog.list_sources(site="comicfuz")}
    assert by_id["1970:7"].display_position == 7
    assert by_id["1970:3"].display_position == 3
    assert len(by_id) == 7
