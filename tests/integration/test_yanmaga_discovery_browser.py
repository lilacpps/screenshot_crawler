from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

import pytest

from screenshot_crawler.catalog import ArtifactInput, CatalogService
from screenshot_crawler.discovery import DiscoveryAdapterRegistry, DiscoveryService
from screenshot_crawler.site_adapters.yanmaga import YanmagaDiscoveryAdapter
from screenshot_crawler.site_adapters.yanmaga import discovery as yanmaga_discovery
from screenshot_crawler.watchlist import DiscoveryScope, WatchlistTarget

pytestmark = pytest.mark.asyncio(loop_scope="module")

BASE = "https://yanmaga.jp"
SLUG = "テスト作"
WORK_URL = f"{BASE}/comics/{quote(SLUG, safe='')}"
WORK_KEY = f"yanmaga:{SLUG}"


def _episode_id(number: int) -> str:
    return f"{number:032x}"


def _row(
    episode_id: str,
    title: str,
    marker: str = "red",
    *,
    href: str | None = None,
    hidden: bool = False,
    extra_badge: str = "",
) -> str:
    access = {
        "red": '<span class="mod-episode-point--free">無料</span>',
        "wait": '<span class="mod-episode-point--free by_wait">無料</span>',
        "point": '<span class="mod-episode-point">70</span>',
        "none": "",
    }[marker]
    modal = ' js-modal' if marker in {"wait", "point"} else ""
    style = ' style="display:none"' if hidden else ""
    href = href or f"{WORK_URL}/{episode_id}"
    return f'''<li class="mod-episode-item{modal}" data-is-free="false" data-modal="registration"{style}>
      <a class="mod-episode-link" href="{href}">
        <p class="mod-episode-title">{title}</p>{access}{extra_badge}
      </a>
    </li>'''


def _listing_html(
    rows: list[tuple[str, str, str]],
    *,
    anonymous: bool = True,
    signin: bool = True,
    signout: bool = False,
    emit_telemetry: bool = True,
    conflict_telemetry: bool = False,
    telemetry_count: int = 1,
    frame_telemetry: bool = False,
    current_slug: str = SLUG,
    canonical_slug: str = SLUG,
    continuation: tuple[int, int, str] | None = None,
    insert_row: str | None = None,
    continuation_sort: str = "older",
    continuation_fetch: bool = False,
    unsupported_paging: bool = False,
    raw_row_html: str | None = None,
) -> str:
    encoded_current = quote(current_slug, safe="")
    encoded_canonical = quote(canonical_slug, safe="")
    row_html = raw_row_html if raw_row_html is not None else "".join(_row(*row) for row in rows)
    continuation_html = ""
    expand_script = ""
    if continuation is not None:
        limit, offset, path = continuation
        continuation_html = (
            '<button class="mod-episode-more-button" '
            f'data-limit="{limit}" data-offset="{offset}" data-sort="{continuation_sort}" '
            f'data-path="{path}">もっと見る</button>'
        )
        if insert_row is not None:
            row_json = json.dumps(insert_row, ensure_ascii=False)
            expand_script = f'''<script>
              document.querySelector('.mod-episode-more-button').addEventListener('click', () => {{
                const rows = [...document.querySelectorAll('.mod-episode-item')];
                rows[{offset}].insertAdjacentHTML('beforebegin', {row_json});
                document.querySelector('.mod-episode-more-button').remove();
              }});
            </script>'''
        elif continuation_fetch:
            expand_script = f'''<script>
              document.querySelector('.mod-episode-more-button').addEventListener('click', () => {{
                fetch('{path}?limit={limit}&offset={offset}&sort={continuation_sort}');
              }});
            </script>'''
    sign_in_link = (
        '<a class="header-utilities-customer--sign_in" href="/customers/sign-up">ログイン</a>'
        if signin
        else ""
    )
    sign_out_link = '<a href="/customers/sign-out">ログアウト</a>' if signout else ""
    login_value = "false" if anonymous else "true"
    telemetry_calls = "".join(
        f'fetch("https://www.google-analytics.com/g/collect?ep.is_logged_in={login_value}&n={index}", '
        '{mode:"no-cors"}).catch(() => {});'
        for index in range(telemetry_count)
    )
    if conflict_telemetry:
        telemetry_calls += (
            'fetch("https://www.google-analytics.com/g/collect?ep.is_logged_in=true", '
            '{mode:"no-cors"}).catch(() => {});'
        )
    telemetry_script = f"<script>{telemetry_calls}</script>" if emit_telemetry else ""
    frame_telemetry_html = (
        '<iframe title="analytics" src="https://www.google-analytics.com/g/collect?ep.is_logged_in=false"></iframe>'
        if frame_telemetry
        else ""
    )
    return f'''<!doctype html><html><head><meta charset="utf-8">
      <title>Synthetic Yanmaga Work</title>
      <link rel="canonical" href="{BASE}/comics/{encoded_canonical}">
      <meta property="og:url" content="{BASE}/comics/{encoded_canonical}">
      <style>.mod-episode-point--free {{ color: rgb(220, 0, 0); }}
        .by_wait {{ color: rgb(238, 117, 27); }}</style>
      {telemetry_script}
      </head><body>{sign_in_link}{sign_out_link}
      {frame_telemetry_html}
      <div class="detailv2-episodes"><p class="episode-free-browse-text">無料は1日で読める数に限りがあります。</p>
        <ul>{row_html}{continuation_html}{'<a rel="next" href="/comics/next">next</a>' if unsupported_paging else ''}</ul>
      </div>{expand_script}</body></html>'''.replace(
        f"/comics/{quote(SLUG, safe='')}", f"/comics/{encoded_current}"
    )


def _target(scope: DiscoveryScope | None = None) -> WatchlistTarget:
    return WatchlistTarget(
        key="yanmaga-test",
        work_key=WORK_KEY,
        site="yanmaga",
        url=WORK_URL,
        label="テスト作品",
        discovery_scope=scope,
    )


async def _discover_with_listener_check(browser_page, service, target, mode):
    events = ("request", "framenavigated")
    listener_counts = {
        event: len(browser_page._impl_obj.listeners(event)) for event in events
    }
    result = await service.discover(browser_page, target, mode)
    listeners_clean = all(
        len(browser_page._impl_obj.listeners(event)) == listener_counts[event]
        for event in events
    )
    return result, listeners_clean


async def _run_discovery(browser_page, tmp_path: Path, html: str, *, mode="full", scope=None):
    state = {"html": html}

    async def fulfill(route) -> None:
        if state.get("fail_continuation") and "/episodes?" in route.request.url:
            await route.abort(error_code="failed")
            return
        await route.fulfill(body=state["html"], content_type="text/html; charset=utf-8")

    async def fulfill_telemetry(route) -> None:
        await route.fulfill(status=204)

    await browser_page.route(f"{BASE}/**", fulfill)
    await browser_page.route("https://www.google-analytics.com/**", fulfill_telemetry)
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    registry = DiscoveryAdapterRegistry()
    registry.register("yanmaga", YanmagaDiscoveryAdapter)
    service = DiscoveryService(catalog, registry)
    result, state["listeners_clean"] = await _discover_with_listener_check(
        browser_page, service, _target(scope), mode
    )
    return catalog, result, service, state


async def test_yanmaga_full_expands_complete_oldest_list_and_repeat_refreshes_catalog(
    browser_page,
    tmp_path: Path,
) -> None:
    path = f"/comics/{quote(SLUG, safe='')}/episodes"
    html = _listing_html(
        [(_episode_id(1), "第1話", "red"), (_episode_id(3), "第3話", "wait")],
        continuation=(2, 1, path),
        insert_row=_row(_episode_id(2), "第2話", "red"),
    )
    catalog, result, service, _state = await _run_discovery(browser_page, tmp_path, html)

    assert _state["listeners_clean"] is True
    sources = catalog.list_sources(site="yanmaga")
    assert result.complete is True
    assert result.observed_count == 3
    assert [source.external_id for source in sources] == [
        f"{SLUG}:{_episode_id(3)}",
        f"{SLUG}:{_episode_id(2)}",
        f"{SLUG}:{_episode_id(1)}",
    ]
    assert [source.access_mode for source in sources] == ["unknown", "free", "free"]
    assert [source.display_position for source in sources] == [3, 2, 1]
    assert [source.free_until for source in sources] == [None, None, None]
    assert all(source.available is True for source in sources)
    targets = {target.source_id: target.locator for target in catalog.list_source_targets()}
    assert [targets[source.id] for source in sources] == [
        f"{WORK_URL}/{_episode_id(3)}",
        f"{WORK_URL}/{_episode_id(2)}",
        f"{WORK_URL}/{_episode_id(1)}",
    ]

    repeated = await service.discover(browser_page, _target(), "full")
    assert repeated.complete is True
    assert repeated.new_count == 0
    assert repeated.known_count == 3
    assert len(catalog.list_sources(site="yanmaga")) == 3


async def test_yanmaga_access_refresh_clears_expiry_and_incomplete_full_preserves_history(
    browser_page,
    tmp_path: Path,
) -> None:
    episodes = [(_episode_id(3), "第3話", "red"), (_episode_id(2), "第2話", "none")]
    catalog, first, _service, state = await _run_discovery(
        browser_page, tmp_path, _listing_html(episodes)
    )
    assert first.complete is True
    source = catalog.find_source("yanmaga", f"{SLUG}:{_episode_id(3)}")
    assert source is not None and source.access_mode == "free"
    catalog.update_source_external_state(
        "yanmaga", source.external_id, free_until="2099-10-14T11:00:00+09:00"
    )
    item = catalog.get_item(source.item_id)
    target = catalog.find_source_target(source.id, "web")
    run = catalog.create_crawl_run(
        item_id=item.id, source_id=source.id, target_id=target.id, access_strategy="direct"
    )
    _sequence, artifact, completed_item = catalog.finalize_successful_crawl(
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
    completed_at = completed_item.completed_at

    state["html"] = _listing_html([(_episode_id(3), "第3話", "none")])
    refreshed = await _service.discover(browser_page, _target(), "full")
    current = catalog.find_source("yanmaga", source.external_id)
    assert refreshed.complete is True
    assert current is not None and current.access_mode == "unknown"
    assert current.free_until is None
    assert catalog.get_item(item.id).status == "completed"
    assert catalog.get_item(item.id).completed_at == completed_at
    assert catalog.get_crawl_run(run.id).status == "succeeded"
    assert [saved.id for saved in catalog.list_artifacts(item_id=item.id)] == [artifact.id]

    before = {saved.external_id: saved.available for saved in catalog.list_sources(site="yanmaga")}
    invalid_path = "/comics/foreign-work/episodes"
    state["html"] = _listing_html(
        [(_episode_id(3), "第3話", "red")],
        continuation=(1, 0, invalid_path),
    )
    incomplete = await _service.discover(browser_page, _target(), "full")
    after = {saved.external_id: saved.available for saved in catalog.list_sources(site="yanmaga")}
    assert incomplete.complete is False
    assert incomplete.observed_count == 0
    assert after == before
    assert catalog.get_item(item.id).status == "completed"
    assert catalog.get_artifact(artifact.id).id == artifact.id


async def test_yanmaga_incremental_yields_latest_first_and_uses_shared_known_streak(
    browser_page,
    tmp_path: Path,
) -> None:
    rows = [(_episode_id(value), f"第{value}話", "none") for value in range(1, 8)]
    catalog, first, service, _state = await _run_discovery(
        browser_page, tmp_path, _listing_html(rows)
    )
    incremental = await service.discover(browser_page, _target(), "incremental")

    assert first.complete is True
    assert incremental.complete is None
    assert incremental.observed_count == 5
    assert incremental.known_count == 5
    assert incremental.stopped_reason == "known_streak"
    by_id = {source.external_id: source for source in catalog.list_sources(site="yanmaga")}
    assert by_id[f"{SLUG}:{_episode_id(7)}"].display_position == 7
    assert by_id[f"{SLUG}:{_episode_id(3)}"].display_position == 3
    assert len(by_id) == 7


async def test_yanmaga_unverified_anonymous_state_never_marks_red_row_free(
    browser_page,
    tmp_path: Path,
) -> None:
    rows = [(_episode_id(1), "第1話", "red")]
    catalog, result, _service, _state = await _run_discovery(
        browser_page,
        tmp_path,
        _listing_html(rows, anonymous=False, signin=False),
    )

    source = catalog.find_source("yanmaga", f"{SLUG}:{_episode_id(1)}")
    assert result.complete is True
    assert source is not None
    assert source.access_mode == "unknown"


async def test_yanmaga_conflicting_login_telemetry_fails_closed_for_free_rows(
    browser_page,
    tmp_path: Path,
) -> None:
    catalog, result, _service, _state = await _run_discovery(
        browser_page,
        tmp_path,
        _listing_html(
            [(_episode_id(1), "第1話", "red")],
            conflict_telemetry=True,
        ),
    )

    source = catalog.find_source("yanmaga", f"{SLUG}:{_episode_id(1)}")
    assert result.complete is True
    assert source is not None
    assert source.access_mode == "unknown"


async def test_yanmaga_subframe_login_telemetry_is_not_anonymous_evidence(
    browser_page,
    tmp_path: Path,
) -> None:
    catalog, result, _service, _state = await _run_discovery(
        browser_page,
        tmp_path,
        _listing_html(
            [(_episode_id(1), "第1話", "red")],
            emit_telemetry=False,
            frame_telemetry=True,
        ),
    )

    source = catalog.find_source("yanmaga", f"{SLUG}:{_episode_id(1)}")
    assert result.complete is True
    assert source is not None
    assert source.access_mode == "unknown"


async def test_yanmaga_telemetry_overflow_fails_closed_stickily(
    browser_page,
    tmp_path: Path,
) -> None:
    catalog, result, _service, _state = await _run_discovery(
        browser_page,
        tmp_path,
        _listing_html(
            [(_episode_id(1), "第1話", "red")],
            telemetry_count=65,
        ),
    )

    source = catalog.find_source("yanmaga", f"{SLUG}:{_episode_id(1)}")
    assert result.complete is True
    assert source is not None
    assert source.access_mode == "unknown"


@pytest.mark.parametrize(
    ("badge", "expected_access"),
    [
        ('<span class="mod-episode-point">70</span>', "free"),
        ('<span class="mod-episode-point">初回無料</span>', "unknown"),
        ('<span class="mod-episode-point">無料</span>', "unknown"),
        ('<div class="mod-episode-detail"><div class="mod-episode-price">無料</div></div>', "free"),
    ],
)
async def test_yanmaga_restricted_badge_conflicts_with_red_free_marker(
    browser_page,
    tmp_path: Path,
    badge: str,
    expected_access: str,
) -> None:
    catalog, result, _service, _state = await _run_discovery(
        browser_page,
        tmp_path,
        _listing_html(
            [], raw_row_html=_row(_episode_id(1), "one", extra_badge=badge)
        ),
    )

    source = catalog.find_source("yanmaga", f"{SLUG}:{_episode_id(1)}")
    assert result.complete is True
    assert source is not None
    assert source.access_mode == expected_access


async def test_yanmaga_bounded_scope_is_unsupported_without_navigation(
    browser_page,
    tmp_path: Path,
) -> None:
    scope = DiscoveryScope(from_url=f"{WORK_URL}/{_episode_id(2)}")
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    registry = DiscoveryAdapterRegistry()
    registry.register("yanmaga", YanmagaDiscoveryAdapter)
    result = await DiscoveryService(catalog, registry).discover(
        browser_page, _target(scope), "full"
    )

    assert result.complete is False
    assert result.stopped_reason == "incomplete"
    assert result.observed_count == 0
    assert catalog.list_sources(site="yanmaga") == []


async def test_yanmaga_duplicate_from_expansion_fails_before_any_record_is_yielded(
    browser_page,
    tmp_path: Path,
) -> None:
    path = f"/comics/{quote(SLUG, safe='')}/episodes"
    html = _listing_html(
        [(_episode_id(1), "第1話", "red"), (_episode_id(3), "第3話", "none")],
        continuation=(1, 1, path),
        insert_row=_row(_episode_id(1), "重複", "red"),
    )
    catalog, result, _service, _state = await _run_discovery(browser_page, tmp_path, html)

    assert result.complete is False
    assert result.observed_count == 0
    assert catalog.list_sources(site="yanmaga") == []
    assert catalog.list_items() == []


@pytest.mark.parametrize(
    "failure",
    [
        "hidden_row",
        "foreign_episode",
        "foreign_canonical",
        "sort_drift",
        "unsupported_paging",
        "no_progress",
        "fetch_failure",
    ],
)
async def test_yanmaga_invalid_or_incomplete_listing_fails_before_catalog_reconcile(
    browser_page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    catalog, first, service, state = await _run_discovery(
        browser_page,
        tmp_path,
        _listing_html([(_episode_id(99), "existing", "red")]),
    )
    assert first.complete is True
    original = [
        (source.external_id, source.available, source.access_mode, source.display_position)
        for source in catalog.list_sources(site="yanmaga")
    ]
    path = f"/comics/{quote(SLUG, safe='')}/episodes"
    continuation = (1, 1, path)
    monkeypatch.setattr(yanmaga_discovery, "WAIT_TIMEOUT_MS", 100)

    if failure == "hidden_row":
        html = _listing_html(
            [], raw_row_html=_row(_episode_id(1), "hidden", hidden=True)
        )
    elif failure == "foreign_episode":
        html = _listing_html(
            [], raw_row_html=_row(
                _episode_id(1), "foreign", href=f"{BASE}/comics/foreign/{_episode_id(1)}"
            )
        )
    elif failure == "foreign_canonical":
        html = _listing_html(
            [(_episode_id(1), "foreign canonical", "red")], canonical_slug="other-work"
        )
    elif failure == "sort_drift":
        html = _listing_html(
            [(_episode_id(1), "one", "red"), (_episode_id(3), "three", "none")],
            continuation=continuation,
            insert_row=_row(_episode_id(2), "two", "red"),
            continuation_sort="newer",
        )
    elif failure == "unsupported_paging":
        html = _listing_html(
            [(_episode_id(1), "one", "red")], unsupported_paging=True
        )
    elif failure == "no_progress":
        html = _listing_html(
            [(_episode_id(1), "one", "red"), (_episode_id(3), "three", "none")],
            continuation=continuation,
        )
    else:
        html = _listing_html(
            [(_episode_id(1), "one", "red"), (_episode_id(3), "three", "none")],
            continuation=continuation,
            continuation_fetch=True,
        )
        state["fail_continuation"] = True

    state["html"] = html
    failed, listeners_clean = await _discover_with_listener_check(
        browser_page, service, _target(), "full"
    )

    assert failed.complete is False, failure
    assert failed.observed_count == 0, failure
    assert listeners_clean is True, failure
    after = [
        (source.external_id, source.available, source.access_mode, source.display_position)
        for source in catalog.list_sources(site="yanmaga")
    ]
    assert after == original, failure
    assert catalog.list_items()


async def test_yanmaga_keeps_ephemeral_reason_for_stale_free_preflight(
    browser_page,
) -> None:
    point_badge = '<span class="mod-episode-point">70</span>'
    initial_free = '<span class="mod-episode-label">初回無料</span>'
    html = _listing_html(
        [
            (_episode_id(1), "red free", "red"),
            (_episode_id(2), "wait", "wait"),
            (_episode_id(3), "points", "point"),
            (_episode_id(4), "initial free", "none"),
        ],
        raw_row_html=(
            _row(_episode_id(1), "red free", "red")
            + _row(_episode_id(2), "wait", "wait")
            + _row(_episode_id(3), "points", "none", extra_badge=point_badge)
            + _row(_episode_id(4), "initial free", "none", extra_badge=initial_free)
        ),
    )
    async def fulfill(route) -> None:
        await route.fulfill(body=html, content_type="text/html; charset=utf-8")

    async def fulfill_telemetry(route) -> None:
        await route.fulfill(status=204)

    await browser_page.route(f"{BASE}/**", fulfill)
    await browser_page.route("https://www.google-analytics.com/**", fulfill_telemetry)
    adapter = YanmagaDiscoveryAdapter()
    records = [record async for record in adapter.iter_records(browser_page, _target(), "full")]

    assert len(records) == 4
    assert adapter.last_snapshot is not None
    assert adapter.last_snapshot.anonymous is True
    rows = {row.episode_id: row for row in adapter.last_snapshot.rows}
    assert rows[_episode_id(1)].free_marker is True
    assert rows[_episode_id(1)].known_restricted is False
    assert rows[_episode_id(2)].known_restricted is True
    assert rows[_episode_id(3)].known_restricted is True
    assert rows[_episode_id(4)].known_restricted is True
