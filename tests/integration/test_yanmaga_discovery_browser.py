from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlsplit

import pytest

from screenshot_crawler.catalog import ArtifactInput, CatalogService
from screenshot_crawler.discovery import DiscoveryAdapterRegistry, DiscoveryService
from screenshot_crawler.discovery.models import DiscoverySourceSnapshot
from screenshot_crawler.discovery.service import DiscoveryIncompleteError
from screenshot_crawler.site_adapters.yanmaga import YanmagaDiscoveryAdapter
from screenshot_crawler.site_adapters.yanmaga import discovery as yanmaga_discovery
from screenshot_crawler.site_adapters.yanmaga.rental_history import (
    RentalCountdown,
    RentalHistoryObservation,
)
from screenshot_crawler.site_policies import YanmagaSitePolicy
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
        "first": (
            '<span class="mod-episode-point--free by_first_time">初回無料</span>'
            '<span class="mod-episode-point--normal">70</span>'
        ),
        "wait": '<span class="mod-episode-point--free by_wait">無料</span>',
        "wait_browse": (
            '<span class="mod-episode-free_browse">'
            '<img src="/assets/logo_free_browse-96b8e1d8.svg"></span>'
            '<span class="mod-episode-point--normal">70</span>'
        ),
        "point": '<span class="mod-episode-point">70</span>',
        "none": "",
    }[marker]
    modal = ' js-modal' if marker in {"wait", "point"} else ""
    style = ' style="display:none"' if hidden else ""
    href = href or f"{WORK_URL}/{episode_id}"
    data_is_free = "true" if marker == "wait_browse" else "false"
    original_url = f' data-original-url="{href}"' if marker == "wait_browse" else ""
    return f'''<li class="mod-episode-item{modal}" data-is-free="{data_is_free}" data-modal="registration"{original_url}{style}>
      <a class="mod-episode-link" href="{href}">
        <p class="mod-episode-title">{title}</p>{access}{extra_badge}
      </a>
    </li>'''


def _upcoming_row(episode_id: str) -> str:
    return f'''<li class="mod-episode-item" data-episode-title="Synthetic upcoming"
      data-is-free="false" data-modal="registration" data-original-url="{WORK_URL}/{episode_id}">
      <div class="mod-episode-link mod-episode-nopublic">
        <div class="mod-episode-thumbnail"><div class="mod-episode-thumbnail-image"></div></div>
        <div class="mod-episode-body"><div class="mod-episode-text">
          <p class="mod-episode-date mod-episode-date-before-publication">
            <span>次回公開予定：</span><time>2026/11/24(火)</time>
          </p>
        </div></div>
      </div>
    </li>'''


def _listing_html(
    rows: list[tuple[str, str, str]],
    *,
    anonymous: bool = True,
    signin: bool = True,
    signout: bool = False,
    mypage: bool = False,
    emit_telemetry: bool = True,
    conflict_telemetry: bool = False,
    telemetry_count: int = 1,
    frame_telemetry: bool = False,
    current_slug: str = SLUG,
    canonical_slug: str = SLUG,
    canonical_query: str = "",
    og_query: str | None = None,
    canonical_href_override: str | None = None,
    og_href_override: str | None = None,
    duplicate_canonical: bool = False,
    duplicate_og_url: bool = False,
    continuation: tuple[int | None, int, str] | None = None,
    insert_row: str | None = None,
    continuation_sort: str = "older",
    continuation_fetch: bool = False,
    continuation_fetch_insert_row: str | None = None,
    continuation_sort_drift: str | None = None,
    unsupported_paging: bool = False,
    raw_row_html: str | None = None,
    sort_state: str | None = None,
    sort_variant: str | None = None,
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
            + (f'data-limit="{limit}" ' if limit is not None else '')
            + f'data-offset="{offset}" data-sort="{continuation_sort}" '
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
        elif continuation_fetch_insert_row is not None:
            if continuation_sort_drift not in {
                None,
                "deactivate_oldest",
                "activate_newest",
            }:
                raise ValueError("unsupported continuation sort drift")
            row_json = json.dumps(continuation_fetch_insert_row, ensure_ascii=False)
            drift_script = ""
            if continuation_sort_drift is not None:
                drift_script = f"""
                  const controls = [...document.querySelectorAll('a.ga-sort.nav-link')];
                  const oldestLabel = String.fromCharCode(0x6700, 0x521d, 0x304b, 0x3089);
                  const newestLabel = String.fromCharCode(0x65b0, 0x7740, 0x9806);
                  const oldest = controls.find(a => a.innerText.trim() === oldestLabel);
                  const newest = controls.find(a => a.innerText.trim() === newestLabel);
                  if ('{continuation_sort_drift}' === 'deactivate_oldest') {{
                    oldest?.classList.remove('active');
                  }} else {{
                    oldest?.classList.remove('active');
                    newest?.classList.add('active');
                  }}
                """
            expand_script = f'''<script>
              document.querySelector('.mod-episode-more-button').addEventListener('click', async () => {{
                const response = await fetch('{path}?offset={offset}&limit={limit}&sort={continuation_sort}');
                if (!response.ok) return;
                const rows = [...document.querySelectorAll('.mod-episode-item')];
                rows[{offset}].insertAdjacentHTML('beforebegin', {row_json});
                document.querySelector('.mod-episode-more-button').remove();
                {drift_script}
              }});
            </script>'''
    sort_html = ""
    if sort_state is not None:
        if sort_state not in {"newer", "older"}:
            raise ValueError("sort_state must be newer, older, or None")
        newest_class = " active" if sort_state == "newer" else ""
        oldest_class = " active" if sort_state == "older" else ""
        newest_href = f"{BASE}/comics/{encoded_current}?sort=newer"
        oldest_href = f"{BASE}/comics/{encoded_current}?sort=older"
        newest_label = "".join(map(chr, (0x65B0, 0x7740, 0x9806)))
        oldest_label = "".join(map(chr, (0x6700, 0x521D, 0x304B, 0x3089)))
        oldest_style = ""
        extra_oldest = ""
        if sort_variant == "hidden_oldest":
            oldest_style = ' style="display:none"'
        elif sort_variant == "foreign_oldest":
            oldest_href = f"{BASE}/comics/foreign-work?sort=older"
        elif sort_variant == "unknown_query":
            oldest_href += "&extra=1"
        elif sort_variant == "label_conflict":
            oldest_label = newest_label
        elif sort_variant == "active_conflict":
            oldest_class = " active"
        elif sort_variant == "duplicate_oldest":
            extra_oldest = (
                f'<a class="ga-sort nav-link" href="{oldest_href}">{oldest_label}</a>'
            )
        sort_html = (
            '<nav class="episode-sort">'
            f'<a class="ga-sort nav-link{newest_class}" href="{newest_href}">{newest_label}</a>'
            f'<a class="ga-sort nav-link{oldest_class}" href="{oldest_href}"{oldest_style}>{oldest_label}</a>'
            f"{extra_oldest}</nav>"
        )
    sign_in_link = (
        '<a class="header-utilities-customer--sign_in" href="/customers/sign-up">ログイン</a>'
        if signin
        else ""
    )
    sign_out_link = '<a href="/customers/sign-out">ログアウト</a>' if signout else ""
    mypage_link = '<a href="/mypage">マイページ</a>' if mypage else ""
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
    selected_og_query = canonical_query if og_query is None else og_query
    canonical_href = canonical_href_override or f"{BASE}/comics/{encoded_canonical}{canonical_query}"
    og_href = og_href_override or f"{BASE}/comics/{encoded_canonical}{selected_og_query}"
    canonical_tag = f'<link rel="canonical" href="{canonical_href}">'
    og_tag = f'<meta property="og:url" content="{og_href}">'
    canonical_tags = canonical_tag * (2 if duplicate_canonical else 1)
    og_tags = og_tag * (2 if duplicate_og_url else 1)
    return f'''<!doctype html><html><head><meta charset="utf-8">
      <title>Synthetic Yanmaga Work</title>
      {canonical_tags}
      {og_tags}
      <style>.mod-episode-point--free {{ color: rgb(220, 0, 0); }}
        .by_wait {{ color: rgb(238, 117, 27); }}</style>
      {telemetry_script}
      </head><body>{sign_in_link}{sign_out_link}{mypage_link}
      {frame_telemetry_html}
      {sort_html}
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


async def _run_discovery(
    browser_page,
    tmp_path: Path,
    html: str,
    *,
    mode="full",
    scope=None,
    sorted_html: str | None = None,
):
    state = {"html": html, "requests": []}
    if sorted_html is not None:
        state["sorted_html"] = sorted_html

    async def fulfill(route) -> None:
        request_url = urlsplit(route.request.url)
        if state.get("fail_continuation") and request_url.path.endswith("/episodes") and request_url.query:
            await route.abort(error_code="failed")
            return
        if request_url.path.endswith("/episodes") and request_url.query:
            await route.fulfill(
                body=state.get("continuation_response", '{"ok":true}'),
                content_type="application/json; charset=utf-8",
            )
            return
        if request_url.query == "sort=older" and state.get("sorted_html"):
            body = state["sorted_html"]
        else:
            body = state["html"]
        await route.fulfill(body=body, content_type="text/html; charset=utf-8")

    async def fulfill_telemetry(route) -> None:
        await route.fulfill(status=204)

    await browser_page.route(f"{BASE}/**", fulfill)
    await browser_page.route("https://www.google-analytics.com/**", fulfill_telemetry)
    def record_request(request) -> None:
        parsed = urlsplit(request.url)
        if parsed.hostname == "yanmaga.jp":
            state["requests"].append(
                {
                    "method": request.method,
                    "path": parsed.path,
                    "query": parsed.query,
                }
            )

    browser_page.on("request", record_request)
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    registry = DiscoveryAdapterRegistry()
    registry.register("yanmaga", YanmagaDiscoveryAdapter)
    service = DiscoveryService(catalog, registry)
    try:
        result, state["listeners_clean"] = await _discover_with_listener_check(
            browser_page, service, _target(scope), mode
        )
    finally:
        browser_page.remove_listener("request", record_request)
    return catalog, result, service, state


@pytest.mark.parametrize(
    "popup_mode", ["absent", "hidden", "initial", "sorted", "more", "delayed",
                   "broken", "duplicate", "repeat_limit", "no_actions"]
)
async def test_yanmaga_discovery_dismisses_optional_native_popup(
    browser_page, tmp_path, monkeypatch, popup_mode,
) -> None:
    monkeypatch.setattr(yanmaga_discovery, "WAIT_TIMEOUT_MS", 1_000)
    if popup_mode == "repeat_limit":
        monkeypatch.setattr(yanmaga_discovery, "MAX_POPUP_DISMISSALS", 1)
    path = f"/comics/{quote(SLUG, safe='')}/episodes"
    rows = [(_episode_id(1), "first", "red"), (_episode_id(3), "last", "red")]
    html = _listing_html(rows, sort_state="newer")
    if popup_mode == "no_actions":
        html = _listing_html(rows)
    sorted_html = _listing_html(
        rows, sort_state="older", canonical_query="?sort=older",
        continuation=(1, 1, path), insert_row=_row(_episode_id(2), "middle"),
    )
    popup_html = '''
      <div class="js-popup-close" id="promo-backdrop"
           style="display:none;position:fixed;inset:0;z-index:5000;background:white">
        <div class="js-popup-content" data-modalcontent="popup">
          <div class="js-popup-close" id="promo-close" style="width:40px;height:40px">×</div>
          DUPLICATE
          <a href="/comics/another-synthetic-work">Synthetic work introduction</a>
        </div>
      </div>
      <script>
        window.showPromo = () => {
          document.querySelector('#promo-backdrop').style.display = 'block';
          document.body.classList.add('is-open-popup');
        };
        document.querySelector('#promo-close').addEventListener('click', event => {
          event.stopPropagation();
          window.promoCloseClicks = (window.promoCloseClicks || 0) + 1;
          if (BROKEN) return;
          document.body.classList.remove('is-open-popup');
          document.querySelector('#promo-backdrop').style.display = 'none';
        });
        SHOW
      </script>
    '''.replace("BROKEN", json.dumps(popup_mode == "broken")).replace(
        "DUPLICATE",
        '<div class="js-popup-close" style="width:40px;height:40px">×</div>'
        if popup_mode == "duplicate" else "",
    )

    def with_popup(document, show=False):
        if popup_mode == "absent":
            return document
        return document.replace(
            "</body>", popup_html.replace("SHOW", "showPromo();" if show else "") + "</body>"
        )

    # Reveal immediately before More, or after its actionability wait starts.
    # The latter proves that an eager one-time check would miss the popup.
    if popup_mode in {"more", "delayed"}:
        original = YanmagaDiscoveryAdapter._wait_for_stable_snapshot

        async def snapshot_then_popup(self, page, *args):
            snapshot = await original(self, page, *args)
            if snapshot.continuation is not None:
                if popup_mode == "delayed":
                    await page.evaluate('''() => {
                      const more = document.querySelector('.mod-episode-more-button');
                      more.disabled = true;
                      setTimeout(() => { showPromo(); more.disabled = false; }, 100);
                    }''')
                else:
                    await page.evaluate("showPromo()")
            return snapshot

        monkeypatch.setattr(YanmagaDiscoveryAdapter, "_wait_for_stable_snapshot", snapshot_then_popup)

    catalog, result, _, state = await _run_discovery(
        browser_page, tmp_path,
        with_popup(html, popup_mode in {
            "initial", "broken", "duplicate", "repeat_limit", "no_actions"
        }),
        sorted_html=with_popup(sorted_html, popup_mode in {"sorted", "repeat_limit"}),
    )
    expected_complete = popup_mode not in {"broken", "duplicate", "repeat_limit"}
    assert result.complete is expected_complete
    expected_count = 2 if popup_mode == "no_actions" else 3
    assert len(catalog.list_sources(site="yanmaga")) == (expected_count if expected_complete else 0)
    if popup_mode in {"sorted", "more", "delayed", "broken", "no_actions"}:
        assert await browser_page.evaluate("window.promoCloseClicks || 0") == 1
    assert state["listeners_clean"] is True
    assert all(request["method"] == "GET" for request in state["requests"])
    assert not any("another-synthetic-work" in request["path"] for request in state["requests"])
    # The handler must not survive success or failure on a reused Page.
    await browser_page.set_content('''<body class="is-open-popup">
      <button class="js-popup-close">×</button><button id="probe">Probe</button></body>''')
    await browser_page.locator("#probe").click(timeout=500)


@pytest.mark.parametrize("failure", [None, "oversize", "offset_drift", "no_progress"])
async def test_yanmaga_missing_limit_continuation_pages_before_catalog_emit(
    browser_page, tmp_path: Path, failure: str | None,
) -> None:
    catalog, first, service, state = await _run_discovery(
        browser_page, tmp_path, _listing_html([(_episode_id(999), "existing", "red")]))
    assert first.complete is True
    original = catalog.list_sources(site="yanmaga")
    path = f"/comics/{quote(SLUG, safe='')}/episodes"
    html = _listing_html(
        [(_episode_id(i), f"第{i}話", "red") for i in [*range(1, 6), *range(344, 349)]],
        continuation=(None, 5, path), sort_state="older",
    )
    pages = [
        {"rows": "".join(_row(_episode_id(i), f"第{i}話") for i in range(start, end)),
         "offset": offset, "limit": limit}
        for start, end, offset, limit in [(6, 156, 155, None), (156, 306, 305, 38),
                                          (306, 344, None, None)]
    ]
    if failure == "oversize":
        pages[0]["rows"] += _row(_episode_id(500), "extra")
    elif failure == "offset_drift":
        pages[0]["offset"] = 156
    elif failure == "no_progress":
        pages = [{"rows": "", "offset": None, "limit": None}]
    script = '''<script>
      const pages = PAGES;
      document.querySelector('.mod-episode-more-button').addEventListener('click', async event => {
        const button = event.currentTarget;
        const offset = Number(button.dataset.offset);
        const query = new URLSearchParams({offset, sort:button.dataset.sort});
        if (button.hasAttribute('data-limit')) query.set('limit', button.dataset.limit);
        const response = await fetch(button.dataset.path + '?' + query);
        if (!response.ok) return;
        const next = pages.shift();
        document.querySelectorAll('.mod-episode-item')[offset].insertAdjacentHTML('beforebegin', next.rows);
        if (next.offset === null) { button.remove(); return; }
        button.dataset.offset = next.offset;
        if (next.limit === null) button.removeAttribute('data-limit');
        else button.dataset.limit = next.limit;
      });
    </script>'''.replace("PAGES", json.dumps(pages, ensure_ascii=False))
    state["html"] = html.replace("</body>", script + "</body>")
    queries = []
    def record(request):
        parsed = urlsplit(request.url)
        if parsed.path.endswith('/episodes'):
            queries.append(parsed.query)
    browser_page.on("request", record)
    try:
        result, clean = await _discover_with_listener_check(browser_page, service, _target(), "full")
    finally:
        browser_page.remove_listener("request", record)
    assert clean is True
    if failure is not None:
        assert result.complete is False and result.observed_count == 0
        assert catalog.list_sources(site="yanmaga") == original
    else:
        assert result.complete is True and result.observed_count == 348
        sources = [s for s in catalog.list_sources(site="yanmaga") if s.available]
        assert [s.display_position for s in sources] == list(range(348, 0, -1))
        assert [s.external_id for s in sources] == [f"{SLUG}:{_episode_id(i)}" for i in range(348, 0, -1)]
        assert queries == [
            "offset=5&sort=older", "offset=155&sort=older", "offset=305&sort=older&limit=38"]


@pytest.mark.parametrize("upcoming", [False, True])
async def test_yanmaga_full_expands_complete_oldest_list_and_repeat_refreshes_catalog(
    browser_page,
    tmp_path: Path,
    upcoming: bool,
) -> None:
    path = f"/comics/{quote(SLUG, safe='')}/episodes"
    html = _listing_html(
        [(_episode_id(1), "第1話", "red"), (_episode_id(3), "第3話", "wait")],
        continuation=(2, 1, path),
        insert_row=_row(_episode_id(2), "第2話", "red"),
        raw_row_html=(
            _row(_episode_id(1), "第1話") + _row(_episode_id(3), "第3話", "wait")
            + _upcoming_row(_episode_id(4)) if upcoming else None
        ),
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


@pytest.mark.parametrize(
    ("authenticated", "expected_mode"),
    [(True, "quota"), (False, "unknown")],
)
async def test_yanmaga_wait_browse_badge_requires_authenticated_listing(
    browser_page,
    tmp_path: Path,
    authenticated: bool,
    expected_mode: str,
) -> None:
    html = _listing_html(
        [(_episode_id(29), "Wait marker", "wait_browse")],
        anonymous=not authenticated,
        signin=not authenticated,
        mypage=authenticated,
    )
    catalog, result, _service, _state = await _run_discovery(
        browser_page, tmp_path / str(authenticated), html
    )

    source = catalog.find_source("yanmaga", f"{SLUG}:{_episode_id(29)}")
    assert result.complete is True
    assert source is not None
    assert source.access_mode == expected_mode
    assert source.free_until is None


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


async def test_yanmaga_unverified_anonymous_state_keeps_access_unknown(
    browser_page,
    tmp_path: Path,
) -> None:
    rows = [(_episode_id(1), "第1話", "red"), (_episode_id(2), "第2話", "point")]
    catalog, result, _service, _state = await _run_discovery(
        browser_page,
        tmp_path,
        _listing_html(rows, anonymous=False, signin=False),
    )

    source = catalog.find_source("yanmaga", f"{SLUG}:{_episode_id(1)}")
    assert result.complete is True
    assert source is not None
    assert source.access_mode == "unknown"
    assert catalog.find_source("yanmaga", f"{SLUG}:{_episode_id(2)}").access_mode == "unknown"


@pytest.mark.parametrize(
    ("point_badge", "expected"),
    [
        ('<span class="mod-episode-point">70</span>', "paid"),
        ('<span class="mod-episode-point--normal">90</span>', "paid"),
        (('<span class="mod-icon-point mod-episode-point">'
          '<span class="mod-episode-point--normal">70</span></span>'), "paid"),
        ('<span class="mod-episode-point--normal">0</span>', "unknown"),
        ('<span class="mod-episode-point--normal">-70</span>', "unknown"),
        ('<span class="mod-episode-point--normal">70P</span>', "unknown"),
        ('<span class="mod-episode-point--normal" hidden>70</span>', "unknown"),
        (('<span class="mod-episode-point--normal">70</span>'
          '<span class="mod-episode-point--normal">90</span>'), "unknown"),
        ('<span class="mod-episode-point--other">70</span>', "unknown"),
        (('<span class="mod-episode-point--normal">70</span>'
          '<span class="mod-episode-point--free by_first_time">初回無料</span>'), "free"),
        (('<span class="mod-episode-point--normal">70</span>'
          '<span class="mod-episode-point--free by_wait">無料</span>'), "unknown"),
        (('<span class="mod-episode-point--normal">70</span>'
          '<span class="mod-episode-free_browse">'
          '<img src="/assets/logo_free_browse-96b8e1d8.svg"></span>'), "unknown"),
    ],
)
async def test_yanmaga_authenticated_listing_classifies_observed_access_rows(
    browser_page,
    tmp_path: Path,
    point_badge: str,
    expected: str,
) -> None:
    rows = [
        (_episode_id(1), "初回無料", "first"),
        (_episode_id(2), "通常無料", "red"),
        (_episode_id(3), "ポイントのみ", "point"),
    ]
    html = _listing_html(
        rows, anonymous=False, signin=False, mypage=True,
        raw_row_html=(
            _row(_episode_id(1), "初回無料", "first")
            + _row(_episode_id(2), "通常無料", "red")
            + _row(_episode_id(3), "ポイントのみ", "none", extra_badge=point_badge)
        ),
    )
    html = html.replace(
        "</body>",
        '<script>window.accessClicks=0</script>'
        '<button id="unlock" onclick="window.accessClicks=(window.accessClicks||0)+1">'
        "無料で読む</button>"
        "</body>",
    )
    forbidden_requests: list[str] = []

    def observe_non_consuming_probe(request) -> None:
        parsed = urlsplit(request.url)
        if parsed.hostname == "yanmaga.jp" and request.method != "GET":
            forbidden_requests.append("non_get")
        parts = parsed.path.rstrip("/").split("/")
        if (
            parsed.hostname == "yanmaga.jp"
            and len(parts) == 4
            and parts[1] == "comics"
            and len(parts[3]) == 32
        ):
            forbidden_requests.append("episode_navigation")

    browser_page.on("request", observe_non_consuming_probe)
    catalog, result, _service, _state = await _run_discovery(
        browser_page,
        tmp_path,
        html,
    )
    browser_page.remove_listener("request", observe_non_consuming_probe)

    assert result.complete is True
    assert catalog.find_source("yanmaga", f"{SLUG}:{_episode_id(1)}").access_mode == "free"
    assert catalog.find_source("yanmaga", f"{SLUG}:{_episode_id(2)}").access_mode == "free"
    source = catalog.find_source("yanmaga", f"{SLUG}:{_episode_id(3)}")
    assert source.access_mode == expected
    assert source.access_granted_until is None
    assert catalog.get_item(source.item_id).status == "pending"
    assert await browser_page.evaluate("window.accessClicks || 0") == 0
    assert forbidden_requests == []


@pytest.mark.parametrize("data_is_free", [None, "true", "false"])
async def test_yanmaga_point_price_requires_explicit_nonfree_row(
    browser_page, tmp_path: Path, data_is_free: str | None,
) -> None:
    row = _row(_episode_id(1), "ポイント話", "point")
    attribute = "" if data_is_free is None else f' data-is-free="{data_is_free}"'
    row = row.replace(' data-is-free="false"', attribute)
    catalog, result, _service, state = await _run_discovery(
        browser_page, tmp_path, _listing_html([], raw_row_html=row),
    )
    assert result.complete is True
    assert state["listeners_clean"] is True
    source = catalog.find_source("yanmaga", f"{SLUG}:{_episode_id(1)}")
    assert source.access_mode == ("paid" if data_is_free == "false" else "unknown")


async def test_yanmaga_imports_exact_active_rental_for_existing_unknown_source(
    browser_page,
    tmp_path: Path,
    monkeypatch,
) -> None:
    episode_id = _episode_id(29)
    external_id = f"{SLUG}:{episode_id}"
    target = _target()
    html = _listing_html(
        [(episode_id, "episode 29", "none")],
        anonymous=False,
        signin=False,
        mypage=True,
    )
    now = datetime.now(UTC)
    expiry = now + timedelta(hours=71, seconds=-5)
    history_days = 3
    history_hours = 0
    history_calls = 0

    async def history_countdowns(
        _page,
        *,
        observed_mypage_href,
        targets,
        max_countdown_hours=23,
    ):
        nonlocal history_calls
        history_calls += 1
        assert observed_mypage_href == f"{BASE}/mypage"
        assert targets == (yanmaga_discovery.YanmagaEpisodeParts(SLUG, episode_id),)
        assert max_countdown_hours == 72
        if history_calls in {1, 3}:
            return (RentalHistoryObservation(external_id, None),)
        return (
            RentalHistoryObservation(
                external_id,
                RentalCountdown(
                    observed_at=now,
                    remaining_hours=history_hours,
                    remaining_days=history_days,
                    access_granted_until=expiry,
                    expiry_evidence=("site_day_countdown_estimate" if history_days is not None
                                     else "site_countdown_lower_bound"),
                ),
            ),
        )

    monkeypatch.setattr(
        yanmaga_discovery, "fetch_rental_history_observations", history_countdowns
    )
    catalog, first, service, _state = await _run_discovery(browser_page, tmp_path, html)
    source = catalog.find_source("yanmaga", external_id)
    assert first.complete is True
    assert source is not None and source.access_mode == "unknown"
    assert source.access_granted_until is None

    item = catalog.get_item(source.item_id)
    web_target = catalog.find_source_target(source.id, "web")
    crawl_run = catalog.create_crawl_run(
        item_id=item.id,
        source_id=source.id,
        target_id=web_target.id,
        access_strategy="direct",
    )
    _sequence, artifact, completed_item = catalog.finalize_successful_crawl(
        crawl_run.id,
        artifact=ArtifactInput(
            kind="archive",
            format="zip",
            sha256="b" * 64,
            byte_size=128,
            storage_backend="local",
            locator="existing-completed-item.zip",
            state="present",
        ),
        page_count=1,
    )
    completed_at = completed_item.completed_at

    # A formerly expired grant must not prevent importing the current rental.
    catalog.record_confirmed_access_grant(
        source.id, site="yanmaga", external_id=external_id,
        observed_at=now - timedelta(days=3), access_granted_until=now - timedelta(days=2),
    )
    refreshed = await service.discover(browser_page, target, "full")
    current = catalog.find_source("yanmaga", external_id)
    current_item = catalog.get_item(item.id)
    assert refreshed.complete is True
    assert current is not None and current.id == source.id
    assert current.item_id == source.item_id
    assert current.access_mode == "quota"
    assert current.access_granted_until is not None
    assert datetime.fromisoformat(current.access_granted_until) == expiry
    assert current.quota_started_at is None
    assert current_item.status == "completed"
    assert current_item.completed_at == completed_at
    assert catalog.get_crawl_run(crawl_run.id).status == "succeeded"
    assert [saved.id for saved in catalog.list_artifacts(item_id=item.id)] == [artifact.id]
    assert catalog.get_quota_resource_state(
        item.work_id, site="yanmaga", resource="work_ticket"
    ) is None
    policy = YanmagaSitePolicy()
    assert policy.evaluate(current, now=now, quota_available=None).access_strategy == "direct"

    # Verified inactive history removes even a still-future old bound and
    # restores ticket candidacy. It does not consume or invent a ticket.
    expired = await service.discover(browser_page, target, "full")
    inactive = catalog.find_source("yanmaga", external_id)
    assert expired.complete is True and inactive.access_mode == "quota"
    assert inactive.access_granted_until is None
    assert policy.evaluate(inactive, now=now, quota_available=None).access_strategy == "quota"

    history_days, history_hours = None, 3
    expiry = now + timedelta(hours=2, seconds=-5)
    renewed = await service.discover(browser_page, target, "full")
    active_again = catalog.find_source("yanmaga", external_id)
    assert renewed.complete is True and active_again.access_mode == "quota"
    assert datetime.fromisoformat(active_again.access_granted_until) == expiry
    assert policy.evaluate(active_again, now=now, quota_available=None).access_strategy == "direct"
    assert active_again.quota_started_at is None
    assert catalog.get_item(item.id).completed_at == completed_at
    assert [saved.id for saved in catalog.list_artifacts(item_id=item.id)] == [artifact.id]
    assert catalog.get_quota_resource_state(
        item.work_id, site="yanmaga", resource="work_ticket"
    ) is None
    # A current quota rental refreshes an existing future bound as well.
    history_days, history_hours = 1, 0
    expiry = now + timedelta(hours=23, seconds=-5)
    refreshed_again = await service.discover(browser_page, target, "full")
    latest = catalog.find_source("yanmaga", external_id)
    assert refreshed_again.complete is True and latest.access_mode == "quota"
    assert datetime.fromisoformat(latest.access_granted_until) == expiry
    assert latest.quota_started_at is None
    assert history_calls == 5


async def test_yanmaga_revalidates_listing_after_async_grant_history_probe(
    browser_page, monkeypatch
) -> None:
    external_id = f"{SLUG}:{_episode_id(1)}"
    target = _target()
    html = _listing_html(
        [(_episode_id(1), "unknown access", "none")],
        anonymous=False,
        signin=False,
        mypage=True,
    )

    async def fulfill(route) -> None:
        await route.fulfill(body=html, content_type="text/html; charset=utf-8")

    async def fulfill_telemetry(route) -> None:
        await route.fulfill(status=204)

    await browser_page.route(f"{BASE}/**", fulfill)
    await browser_page.route("https://www.google-analytics.com/**", fulfill_telemetry)
    adapter = YanmagaDiscoveryAdapter()
    adapter.configure_source_snapshots(
        target,
        (
            DiscoverySourceSnapshot(
                external_id=external_id,
                discovery_key=target.key,
                access_mode="paid",
                available=True,
                access_granted_until=datetime.now(UTC) + timedelta(hours=2),
            ),
        ),
    )
    observed_target = yanmaga_discovery.YanmagaEpisodeParts(SLUG, _episode_id(1))

    async def mutate_during_history_fetch(
        _page,
        *,
        observed_mypage_href,
        targets,
        max_countdown_hours=23,
    ):
        assert observed_mypage_href == f"{BASE}/mypage"
        assert targets == (observed_target,)
        assert max_countdown_hours == 72
        await browser_page.evaluate(
            "document.querySelector('.mod-episode-title').textContent='changed during probe'"
        )
        now = datetime.now(UTC)
        return (
            RentalHistoryObservation(
                external_id,
                RentalCountdown(
                    observed_at=now,
                    remaining_hours=2,
                    access_granted_until=now + timedelta(hours=1),
                    expiry_evidence="site_countdown_lower_bound",
                ),
            ),
        )

    monkeypatch.setattr(
        yanmaga_discovery, "fetch_rental_history_observations", mutate_during_history_fetch
    )
    emitted = []
    with pytest.raises(DiscoveryIncompleteError):
        async for record in adapter.iter_records(browser_page, target, "full"):
            emitted.append(record)

    assert emitted == []
    assert adapter.last_snapshot is None


@pytest.mark.parametrize("already_oldest", [False, True])
async def test_yanmaga_observed_oldest_sort_preserves_positions_source_and_completed(
    browser_page,
    tmp_path: Path,
    already_oldest: bool,
) -> None:
    path = f"/comics/{quote(SLUG, safe='')}/episodes"
    newest_numbers = [57, 56, 55, 54, 53, 5, 4, 3, 2, 1]
    oldest_page_numbers = [1, 2, 3, 4, 5, 53, 54, 55, 56, 57]

    def row(number: int) -> tuple[str, str, str]:
        marker = "first" if number == 32 else "red" if number == 1 else "none"
        return (_episode_id(number), f"episode {number}", marker)

    default_html = _listing_html(
        [row(number) for number in newest_numbers],
        anonymous=False,
        signin=False,
        mypage=True,
        sort_state="newer",
    )
    inserted_rows = "".join(
        _row(*row(number)) for number in range(6, 53)
    )
    oldest_html = _listing_html(
        [row(number) for number in oldest_page_numbers],
        anonymous=False,
        signin=False,
        mypage=True,
        sort_state="older",
        canonical_query="" if already_oldest else "?sort=older",
        continuation=(47, 5, path),
        continuation_sort="older",
        continuation_fetch_insert_row=inserted_rows,
    )
    initial_html = oldest_html if already_oldest else default_html
    catalog, first, service, state = await _run_discovery(
        browser_page,
        tmp_path,
        initial_html,
        sorted_html=None if already_oldest else oldest_html,
    )

    assert first.complete is True
    sources = catalog.list_sources(site="yanmaga")
    assert len(sources) == 57
    by_episode = {
        source.external_id.rsplit(":", 1)[1]: source for source in sources
    }
    assert [by_episode[_episode_id(number)].display_position for number in range(1, 58)] == list(
        range(1, 58)
    )
    assert [source.external_id for source in sources] == [
        f"{SLUG}:{_episode_id(number)}" for number in range(57, 0, -1)
    ]
    first_free = by_episode[_episode_id(32)]
    assert first_free.access_mode == "free"
    target = catalog.find_source_target(first_free.id, "web")
    assert target is not None
    assert target.locator == f"{WORK_URL}/{_episode_id(32)}"
    assert "?sort=" not in target.locator

    item = catalog.get_item(first_free.item_id)
    run = catalog.create_crawl_run(
        item_id=item.id,
        source_id=first_free.id,
        target_id=target.id,
        access_strategy="direct",
    )
    _sequence, artifact, completed_item = catalog.finalize_successful_crawl(
        run.id,
        artifact=ArtifactInput(
            kind="archive",
            format="zip",
            sha256="b" * 64,
            byte_size=128,
            storage_backend="local",
            locator="sort-test-only.zip",
            state="present",
        ),
        page_count=1,
    )
    completed_at = completed_item.completed_at
    repeated = await service.discover(browser_page, _target(), "full")

    assert repeated.complete is True
    assert catalog.get_item(item.id).status == "completed"
    assert catalog.get_item(item.id).completed_at == completed_at
    assert catalog.get_crawl_run(run.id).status == "succeeded"
    assert [saved.id for saved in catalog.list_artifacts(item_id=item.id)] == [artifact.id]
    assert state["listeners_clean"] is True
    assert all(request["method"] == "GET" for request in state["requests"])
    sort_requests = [
        request
        for request in state["requests"]
        if request["path"] == f"/comics/{quote(SLUG, safe='')}"
        and request["query"] == "sort=older"
    ]
    more_requests = [
        request
        for request in state["requests"]
        if request["path"] == path and request["query"] == "offset=5&limit=47&sort=older"
    ]
    assert len(sort_requests) == (0 if already_oldest else 1)
    assert len(more_requests) == 1
    assert not any(
        re.fullmatch(r"/comics/[^/]+/[0-9a-f]{32}", request["path"])
        or request["path"].startswith("/viewer/")
        for request in state["requests"]
    )


@pytest.mark.parametrize(
    ("case", "expected_complete", "sort_count"),
    [
        ("sorted_pair", True, 1),
        ("base_pair", True, 1),
        ("mixed_pair", False, 1),
        ("unknown_query", False, 1),
        ("duplicate_query", False, 1),
        ("fragment", False, 1),
        ("userinfo", False, 1),
        ("foreign_sorted_identity", False, 1),
        ("duplicate_canonical", False, 1),
        ("duplicate_og", False, 1),
        ("base_document_sorted_pair", False, 0),
        ("no_ui_sorted_pair", False, 0),
    ],
)
async def test_yanmaga_sorted_canonical_identity_requires_exact_oldest_document_and_ui(
    browser_page,
    tmp_path: Path,
    case: str,
    expected_complete: bool,
    sort_count: int,
) -> None:
    row = (_episode_id(1), "episode 1", "red")
    initial_state = "newer"
    initial_query = ""
    sorted_state: str | None = "older"
    sorted_canonical_query = "?sort=older"
    sorted_og_query: str | None = None
    canonical_href_override: str | None = None
    duplicate_canonical = False
    duplicate_og = False

    if case == "base_pair":
        sorted_canonical_query = ""
    elif case == "mixed_pair":
        sorted_og_query = ""
    elif case == "unknown_query":
        sorted_canonical_query = "?sort=older&extra=1"
    elif case == "duplicate_query":
        sorted_canonical_query = "?sort=older&sort=older"
    elif case == "fragment":
        sorted_canonical_query = "?sort=older#episodes"
    elif case == "userinfo":
        canonical_href_override = (
            f"https://user@yanmaga.jp/comics/{quote(SLUG, safe='')}?sort=older"
        )
    elif case == "foreign_sorted_identity":
        canonical_href_override = "https://yanmaga.jp/comics/other-work?sort=older"
    elif case == "duplicate_canonical":
        duplicate_canonical = True
    elif case == "duplicate_og":
        duplicate_og = True
    elif case == "base_document_sorted_pair":
        initial_state = "older"
        initial_query = "?sort=older"
    elif case == "no_ui_sorted_pair":
        initial_state = None
        initial_query = "?sort=older"
        sorted_state = None

    initial_html = _listing_html(
        [row],
        anonymous=False,
        signin=False,
        mypage=True,
        sort_state=initial_state,
        canonical_query=initial_query,
    )
    sorted_html = _listing_html(
        [row],
        anonymous=False,
        signin=False,
        mypage=True,
        sort_state=sorted_state,
        canonical_query=sorted_canonical_query,
        og_query=sorted_og_query,
        canonical_href_override=canonical_href_override,
        duplicate_canonical=duplicate_canonical,
        duplicate_og_url=duplicate_og,
    )
    catalog, result, _service, state = await _run_discovery(
        browser_page,
        tmp_path,
        initial_html,
        sorted_html=sorted_html,
    )

    assert result.complete is expected_complete
    assert len(catalog.list_sources(site="yanmaga")) == (1 if expected_complete else 0)
    sort_requests = [
        request
        for request in state["requests"]
        if request["path"] == f"/comics/{quote(SLUG, safe='')}"
        and request["query"] == "sort=older"
    ]
    assert len(sort_requests) == sort_count
    assert not any(
        re.fullmatch(r"/comics/[^/]+/[^/]+", request["path"])
        and not request["path"].endswith("/episodes")
        or request["path"].startswith("/viewer/")
        for request in state["requests"]
    )


@pytest.mark.parametrize("drift", ["deactivate_oldest", "activate_newest"])
async def test_yanmaga_active_oldest_state_is_rechecked_after_more_before_catalog_emit(
    browser_page,
    tmp_path: Path,
    drift: str,
) -> None:
    path = f"/comics/{quote(SLUG, safe='')}/episodes"
    episode_id = _episode_id(32)
    catalog, first, service, state = await _run_discovery(
        browser_page,
        tmp_path,
        _listing_html([(episode_id, "completed episode", "red")]),
    )
    assert first.complete is True
    source = catalog.find_source("yanmaga", f"{SLUG}:{episode_id}")
    assert source is not None
    item = catalog.get_item(source.item_id)
    target = catalog.find_source_target(source.id, "web")
    assert target is not None
    run = catalog.create_crawl_run(
        item_id=item.id,
        source_id=source.id,
        target_id=target.id,
        access_strategy="direct",
    )
    _sequence, artifact, completed_item = catalog.finalize_successful_crawl(
        run.id,
        artifact=ArtifactInput(
            kind="archive",
            format="zip",
            sha256="c" * 64,
            byte_size=128,
            storage_backend="local",
            locator="sort-drift-test-only.zip",
            state="present",
        ),
        page_count=1,
    )
    completed_at = completed_item.completed_at
    initial_positions = {
        saved.external_id: saved.display_position
        for saved in catalog.list_sources(site="yanmaga")
    }
    initial_status = catalog.get_item(item.id).status

    oldest_page_numbers = [1, 2, 3, 4, 5, 53, 54, 55, 56, 57]

    def row(number: int) -> tuple[str, str, str]:
        marker = "first" if number == 32 else "red" if number == 1 else "none"
        return (_episode_id(number), f"episode {number}", marker)

    inserted_rows = "".join(_row(*row(number)) for number in range(6, 53))
    state["html"] = _listing_html(
        [row(number) for number in oldest_page_numbers],
        anonymous=False,
        signin=False,
        mypage=True,
        sort_state="older",
        continuation=(47, 5, path),
        continuation_sort="older",
        continuation_fetch_insert_row=inserted_rows,
        continuation_sort_drift=drift,
    )
    drift_requests: list[dict[str, str]] = []

    def observe_drift_request(request) -> None:
        parsed = urlsplit(request.url)
        if parsed.hostname == "yanmaga.jp":
            drift_requests.append(
                {
                    "method": request.method,
                    "path": parsed.path,
                    "query": parsed.query,
                }
            )

    browser_page.on("request", observe_drift_request)
    try:
        failed = await service.discover(browser_page, _target(), "full")
    finally:
        browser_page.remove_listener("request", observe_drift_request)

    assert failed.complete is False
    assert failed.observed_count == 0
    assert all(request["method"] == "GET" for request in drift_requests)
    assert any(
        request["path"] == path and request["query"] == "offset=5&limit=47&sort=older"
        for request in drift_requests
    )
    assert not any(
        request["path"] == f"/comics/{quote(SLUG, safe='')}"
        and request["query"] == "sort=older"
        for request in drift_requests
    )
    assert not any(
        re.fullmatch(r"/comics/[^/]+/[0-9a-f]{32}", request["path"])
        or request["path"].startswith("/viewer/")
        for request in drift_requests
    )
    current_source = catalog.find_source("yanmaga", source.external_id)
    assert current_source is not None
    assert current_source.display_position == initial_positions[source.external_id]
    assert catalog.get_item(item.id).status == initial_status == "completed"
    assert catalog.get_item(item.id).completed_at == completed_at
    assert catalog.get_crawl_run(run.id).status == "succeeded"
    assert [saved.id for saved in catalog.list_artifacts(item_id=item.id)] == [artifact.id]


@pytest.mark.parametrize("destination", ["source", "foreign"])
async def test_yanmaga_sort_href_drift_never_clicks_mutated_target(
    browser_page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    destination: str,
) -> None:
    html = _listing_html(
        [(_episode_id(1), "episode 1", "first")],
        anonymous=False,
        signin=False,
        mypage=True,
        sort_state="newer",
    )
    target_href = (
        f"{WORK_URL}/{_episode_id(1)}"
        if destination == "source"
        else f"{BASE}/comics/foreign-work?sort=older"
    )
    original = YanmagaDiscoveryAdapter._sort_control_state
    calls = 0
    oldest_label = "".join(map(chr, (0x6700, 0x521D, 0x304B, 0x3089)))

    async def drift_after_final_observation(self, page):
        nonlocal calls
        state = await original(self, page)
        calls += 1
        if calls == 2:
            await page.evaluate(
                """args => {
                  const anchor = [...document.querySelectorAll('a.ga-sort.nav-link')]
                    .find(element => element.innerText.trim() === args.label);
                  anchor.setAttribute('href', args.href);
                }""",
                {"label": oldest_label, "href": target_href},
            )
        return state

    monkeypatch.setattr(
        YanmagaDiscoveryAdapter,
        "_sort_control_state",
        drift_after_final_observation,
    )
    catalog, result, _service, state = await _run_discovery(
        browser_page,
        tmp_path,
        html,
    )

    assert calls == 2
    assert result.complete is False
    assert result.observed_count == 0
    assert catalog.list_sources(site="yanmaga") == []
    assert catalog.list_items() == []
    assert all(request["method"] == "GET" for request in state["requests"])
    assert not any(
        request["path"] == f"/comics/{quote(SLUG, safe='')}"
        and request["query"] == "sort=older"
        for request in state["requests"]
    )
    assert not any(
        request["path"].endswith(f"/{_episode_id(1)}")
        or request["path"] == "/comics/foreign-work"
        for request in state["requests"]
    )


@pytest.mark.parametrize(
    "variant",
    [
        "hidden_oldest",
        "foreign_oldest",
        "unknown_query",
        "label_conflict",
        "active_conflict",
        "duplicate_oldest",
    ],
)
async def test_yanmaga_unknown_oldest_sort_ui_fails_closed_before_navigation(
    browser_page,
    tmp_path: Path,
    variant: str,
) -> None:
    html = _listing_html(
        [(_episode_id(1), "episode 1", "red")],
        anonymous=False,
        signin=False,
        mypage=True,
        sort_state="newer",
        sort_variant=variant,
    )
    catalog, result, _service, state = await _run_discovery(browser_page, tmp_path, html)

    assert result.complete is False
    assert result.observed_count == 0
    assert catalog.list_sources(site="yanmaga") == []
    assert catalog.list_items() == []
    assert all(request["method"] == "GET" for request in state["requests"])
    assert not any(request["query"] == "sort=older" for request in state["requests"])
    assert not any(request["path"].endswith("/episodes") for request in state["requests"])
    assert not any(
        re.fullmatch(r"/comics/[^/]+/[0-9a-f]{32}", request["path"])
        or request["path"].startswith("/viewer/")
        for request in state["requests"]
    )


async def test_yanmaga_conflicting_login_ui_keeps_free_rows_unknown(
    browser_page,
    tmp_path: Path,
) -> None:
    catalog, result, _service, _state = await _run_discovery(
        browser_page,
        tmp_path,
        _listing_html(
            [(_episode_id(1), "第1話", "red")],
            anonymous=True,
            signin=True,
            mypage=True,
        ),
    )

    source = catalog.find_source("yanmaga", f"{SLUG}:{_episode_id(1)}")
    assert result.complete is True
    assert source is not None
    assert source.access_mode == "unknown"


async def test_yanmaga_noncanonical_mypage_links_are_not_authentication_evidence(
    browser_page,
    tmp_path: Path,
) -> None:
    html = _listing_html(
        [(_episode_id(1), "第1話", "red")],
        anonymous=False,
        signin=False,
    ).replace(
        "</body>",
        '<a href="/mypage?mode=menu">query</a>'
        '<a href="/mypage#menu">fragment</a>'
        '<a href="https://user@yanmaga.jp/mypage">userinfo</a>'
        '<a href="https://other.example/mypage">foreign</a>'
        '<a href="/mypage/">trailing-slash</a>'
        '<a href="/mypage" style="display:none">hidden</a>'
        "</body>",
    )
    catalog, result, _service, _state = await _run_discovery(
        browser_page,
        tmp_path,
        html,
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


@pytest.mark.parametrize("failure", [
    None, "missing_class", "foreign", "missing_url", "missing_title", "missing_date",
    "wrong_label", "bad_date", "wrong_weekday", "duplicate_time", "link", "free",
    "hidden", "duplicate_id", "not_last",
])
async def test_yanmaga_upcoming_row_is_metadata_only_and_never_entered(
    browser_page, tmp_path, failure,
) -> None:
    catalog, initial, service, state = await _run_discovery(
        browser_page, tmp_path, _listing_html([(_episode_id(1), "existing", "red")]))
    assert initial.complete is True
    original = catalog.list_sources(site="yanmaga")
    upcoming = _upcoming_row(_episode_id(3))
    changes = {
        "missing_class": ('mod-episode-nopublic', 'unknown'),
        "foreign": (f'{WORK_URL}/{_episode_id(3)}', f'{BASE}/comics/other/{_episode_id(3)}'),
        "missing_url": ('data-original-url=', 'data-other='),
        "missing_title": ('data-episode-title=', 'data-other='),
        "missing_date": ('mod-episode-date-before-publication', 'other'),
        "wrong_label": ('次回公開予定：', '公開中'),
        "bad_date": ('2026/11/24(火)', '2026/02/31(火)'),
        "wrong_weekday": ('2026/11/24(火)', '2026/11/24(水)'),
        "duplicate_time": ('</time>', '</time><time>2026/11/24(火)</time>'),
        "link": ('</time>', '</time><a href="/customers/sign-up">読む</a>'),
        "free": ('</time>', '</time><span class="mod-episode-point--free">無料</span>'),
        "hidden": ('class="mod-episode-link', 'style="display:none" class="mod-episode-link'),
        "duplicate_id": (_episode_id(3), _episode_id(1)),
    }
    if failure in changes:
        upcoming = upcoming.replace(*changes[failure])
    published = _row(_episode_id(1), "existing") + _row(_episode_id(2), "second")
    raw = published + upcoming
    if failure == "not_last":
        raw = upcoming + published
    state['html'] = _listing_html([], raw_row_html=raw)
    result = await service.discover(browser_page, _target(), "full")
    if failure:
        assert result.complete is False and result.observed_count == 0
        assert catalog.list_sources(site="yanmaga") == original
    else:
        assert result.complete is True and result.observed_count == 2
        sources = catalog.list_sources(site="yanmaga")
        assert {s.external_id for s in sources} == {f'{SLUG}:{_episode_id(i)}' for i in (1, 2)}
        assert sorted(s.display_position for s in sources) == [1, 2]
        assert catalog.get_source(original[0].id).external_id == original[0].external_id
        repeated = await service.discover(browser_page, _target(), "incremental")
        assert repeated.observed_count == 2
        state['html'] = _listing_html([
            (_episode_id(i), f'published {i}', 'red') for i in (1, 2, 3)])
        released = await service.discover(browser_page, _target(), "full")
        assert released.complete is True and released.observed_count == 3
        assert len(catalog.list_sources(site="yanmaga")) == 3
    assert all(r['method'] == 'GET' and r['path'].split('/')[-1] not in {
        _episode_id(1), _episode_id(2), _episode_id(3), 'sign-up'
    } for r in state['requests'])


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
    assert next(record.source.access_mode for record in records
                if record.source.external_id == f"{SLUG}:{_episode_id(3)}") == "paid"
