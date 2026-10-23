from __future__ import annotations

import asyncio
import base64
import json
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from screenshot_crawler.batch import (
    BatchExecutor,
    BatchPlanner,
    CandidateExecutionError,
)
from screenshot_crawler.catalog import CatalogService
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.core.errors import (
    MaxPagesExceededError,
    PageChangeTimeoutError,
    UnknownPageStateError,
)
from screenshot_crawler.core.models import RunConfig
from screenshot_crawler.core.runner import CrawlerRunner
from screenshot_crawler.core.state import PageState
from screenshot_crawler.discovery import DiscoveryAdapterRegistry, DiscoveryService
from screenshot_crawler.runtime_settings import SiteRuntimeSettings
from screenshot_crawler.site_adapters.comicfuz import (
    ComicFuzAdapter,
    ComicFuzDiscoveryAdapter,
)
from screenshot_crawler.site_adapters.registry import AdapterRegistry
from screenshot_crawler.site_policies import ComicFuzSitePolicy, SitePolicyRegistry
from screenshot_crawler.watchlist import WatchlistTarget

pytestmark = pytest.mark.asyncio(loop_scope="module")

BASE = "https://comic-fuz.com"
WORK_URL = f"{BASE}/manga/1970?position=thumbnail"
VIEWER_URL = f"{BASE}/manga/viewer/80641"
NOW = datetime(2026, 10, 13, 12, tzinfo=JST)
EPISODE_TITLE = "第31話"


def _jpeg_bytes(color: tuple[int, int, int] = (38, 121, 205)) -> bytes:
    image = Image.new("RGB", (96, 144), color=color)
    output = BytesIO()
    image.save(output, format="JPEG", quality=91)
    return output.getvalue()


def _work_html(*, free: bool = True) -> str:
    chapters = [("80641", "第31話"), ("80640", "第30話"), ("80639", "第29話")]
    data = {
        "page": "/manga/[mangaId]",
        "props": {
            "pageProps": {
                "chapters": [
                    {
                        "chapters": [
                            {"chapterId": chapter, "chapterMainName": label}
                            for chapter, label in chapters
                        ]
                    }
                ]
            }
        },
    }
    rows = "".join(
        f"""<div class="Chapter_chapter__row false false"><div class="Chapter_chapter__detail__fixture">
          <h3 class="Chapter_chapter__name__fixture">{label}</h3>
          {('<p class="Chapter_chapter__price_free__fixture">無料</p>' if free and chapter == "80641" else "")}
        </div></div>"""
        for chapter, label in chapters
    )
    return f'''<!doctype html><html><head><title>サンプル作品</title>
      <link rel="canonical" href="{BASE}/manga/1970">
      <script id="__NEXT_DATA__" type="application/json">{json.dumps(data, ensure_ascii=False)}</script>
      </head><body><a href="/account/signin">Sign in</a>
      <div class="title_detail_chapters__list__fixture"><ul>{rows}</ul></div>
      <style>body{{min-height:1200px}}</style></body></html>'''


def _viewer_html(
    jpeg: bytes,
    *,
    viewer_title: str = EPISODE_TITLE,
    sign_in: bool = True,
    transition_delay_ms: int = 0,
    missing_second_page: bool = False,
    clipped_second_page: bool = False,
    descriptor_width_mismatch: bool = False,
    route_change_on_first_turn: bool = False,
    delayed_manifest_ms: int = 0,
    initial_state: int = 0,
    unknown_tail: bool = False,
    first_page_blank: bool | None = True,
    first_page_blank_inherited: bool = False,
    first_page_blank_malformed: bool = False,
    first_mode_body_page_count: int = 4,
    true_mode_body_page_count: int = 2,
    missing_first_pair_page: int | None = None,
    delayed_first_pair_ms: int = 0,
    transition_overlap_state: int | None = None,
    transition_overlap_new_count: int = 1,
    persistent_transition_overlap: bool = False,
    transition_overlap_variant: str = "valid",
    extra_tail: bool = False,
    latest_end: str = "none",
    stuck_extra_tail: bool = False,
    native_subtitle: str = "",
) -> str:
    encoded = base64.b64encode(jpeg).decode("ascii")
    next_data = {
        "page": "/manga/viewer/[chapterId]",
        "props": {
            "pageProps": {
                "chapterId": "80641",
                "data": {
                    "mangaId": "1970",
                    "chapterMainName": EPISODE_TITLE,
                    "chapterSubName": native_subtitle,
                    "mangaName": "Verified ComicFUZ Work",
                },
            }
        },
    }
    next_data_json = json.dumps(next_data, ensure_ascii=False).replace("</", "<\\/")
    if native_subtitle and viewer_title == EPISODE_TITLE:
        viewer_title = f"{EPISODE_TITLE}　{native_subtitle}"
    sign_in_link = '<a href="/account/signin">Sign in</a>' if sign_in else ""
    second_left = "1279" if clipped_second_page else "355"
    first_page_blank_js = (
        "undefined" if first_page_blank is None else str(first_page_blank).lower()
    )
    if first_page_blank_malformed:
        first_page_blank_js = "'false'"
    first_pair_mode = first_page_blank is False or first_page_blank_inherited
    body_descriptor_count = (
        first_mode_body_page_count if first_pair_mode else true_mode_body_page_count
    )
    initial_partial = "[0]" if missing_first_pair_page in {None, 1} else "[1]"
    if first_pair_mode:
        image_groups = {
            state: list(range(start, min(start + 2, body_descriptor_count)))
            for state, start in enumerate(range(0, body_descriptor_count, 2))
        }
    else:
        image_groups = {0: [0]}
        for state, start in enumerate(range(1, body_descriptor_count, 2), start=1):
            image_groups[state] = list(range(start, min(start + 2, body_descriptor_count)))
            state += 1
    if image_groups:
        last_state = max(image_groups)
        if len(image_groups[last_state]) == 1:
            image_groups[last_state].append(body_descriptor_count)
        if not first_pair_mode and missing_second_page:
            image_groups[1] = [1]
        if extra_tail:
            image_groups[max(image_groups) + 1] = [body_descriptor_count + 1, body_descriptor_count + 2]
    terminal_state = max(image_groups) + 1 if image_groups else 0
    native_page_count = body_descriptor_count + (5 if extra_tail else 3)
    counter_values = [
        f"{group[0] + 1}/{native_page_count}" for _state, group in image_groups.items()
    ] + [f"{native_page_count}/{native_page_count}"]
    if transition_overlap_state is not None and transition_overlap_state >= terminal_state:
        raise ValueError("transition overlap state must identify a body spread")
    images_js = json.dumps(image_groups)
    counter_values_js = json.dumps(counter_values)
    return f"""<!doctype html><html><head><title>ComicFUZ viewer</title></head><body>
      <script id="__NEXT_DATA__" type="application/json">{next_data_json}</script>
        {sign_in_link}<div id="counter">1/{native_page_count}</div><main id="reader"></main>
      <script>
        const bytes = Uint8Array.from(atob('{encoded}'), c => c.charCodeAt(0));
        const imageBlob = new Blob([bytes], {{type:'image/jpeg'}});
        const src = URL.createObjectURL(imageBlob);
        const wrongDimensionSrc = URL.createObjectURL(new Blob([
          '<svg xmlns="http://www.w3.org/2000/svg" width="97" height="144"></svg>'
        ], {{type:'image/svg+xml'}}));
        const reader = document.querySelector('#reader');
        const counter = document.querySelector('#counter');
        let state = {initial_state};
        const firstPageBlank = {first_page_blank_js};
        const firstPairMode = {str(first_pair_mode).lower()};
        const images = {images_js};
        const counterValues = {counter_values_js};
        let firstPairReady = {str(missing_first_pair_page is None and delayed_first_pair_ms == 0).lower()};
        const pageDescriptors = Array.from({{length:{body_descriptor_count}}}, (_, index) => ({{
          image:{{imageWidth:{97 if descriptor_width_mismatch else 96},imageHeight:144}}
        }}));
        pageDescriptors.push(
          {{image:{{imageWidth:96,imageHeight:144,isExtraPage:true,urlScheme:'krr://manga?id=999'}}}},
          {{googleAds:{{}}}}, {{lastPage:{{}}}}
        );
        if ({str(extra_tail).lower()}) pageDescriptors.splice(pageDescriptors.length - 2, 0,
          {{image:{{imageWidth:96,imageHeight:144,isExtraPage:true}}}},
          {{image:{{imageWidth:96,imageHeight:144,isExtraPage:true,urlScheme:'krr://manga?id=998'}}}}
        );
        const viewerData = {{pages:pageDescriptors}};
        if ({str(first_page_blank_inherited).lower()})
          Object.setPrototypeOf(viewerData, {{isFirstPageBlank:false}});
        else if (firstPageBlank !== undefined)
          viewerData.isFirstPageBlank = firstPageBlank;
        window.nativeFlagFixture = {{
          value:viewerData.isFirstPageBlank,
          own:Object.hasOwn(viewerData,'isFirstPageBlank')
        }};
        const webMangaViewerData = {{chapterId:'80641',viewerData}};
        const transitionOverlapState = {json.dumps(transition_overlap_state)};
        function showOverlap() {{
          const prior = images[state - 1] || [];
          const next = images[state] || [];
          let numbers = [...new Set([
            ...prior,
            ...next.slice(0, {transition_overlap_new_count})
          ])].sort((a, b) => a - b);
          if ('{transition_overlap_variant}' === 'outside') numbers = [3, 4, 99];
          if ('{transition_overlap_variant}' === 'gap') numbers = [3, 5, 6];
          if ('{transition_overlap_variant}' === 'duplicate') numbers = [3, 4, 4];
          if ('{transition_overlap_variant}' === 'all_ready') numbers = [3, 4, 5];
          if ('{transition_overlap_variant}' === 'role') numbers = [3, 4, 10];
          reader.innerHTML = `<div id="pages"></div><h2 class="title_detail_viewer__detail__info__viewerTitle__GrN4D">{viewer_title}</h2>`;
          const area = document.querySelector('#pages');
          area.style.cssText = 'position:fixed;left:0;top:0;width:1280px;height:720px';
          numbers.forEach((n, index) => {{
            const image = document.createElement('img');
            image.className = 'G54Y0W_page'; image.alt = `page_${{n}}`;
            image['__reactFiber$fixture'] = {{memoizedProps:{{webMangaViewerData}},return:null}};
            image.src = ('{transition_overlap_variant}' === 'dimensions' && n === 4)
              ? wrongDimensionSrc : src;
            const allReadyPositions = [945, 655, 355, 55];
            const clippedPositions = numbers.length === 4
              ? [1100, 800, 500, -25] : [1100, 655, -25];
            const positions = '{transition_overlap_variant}' === 'all_ready'
              ? allReadyPositions : clippedPositions;
            const left = positions[index] ?? 55;
            image.style.cssText = `position:absolute;top:40px;left:${{left}}px;width:300px;height:450px;object-fit:fill`;
            if ('{transition_overlap_variant}' === 'visual_unsafe' && n === 4)
              image.style.filter = 'grayscale(1)';
            area.append(image);
          }});
          const overlapImages = [...reader.querySelectorAll('img.G54Y0W_page')];
          window.transitionOverlapSeen = {{
            state,
            numbers,
            imageReady: overlapImages.map(image => image.complete
              && image.naturalWidth > 0 && image.naturalHeight > 0),
            ready: overlapImages.map(image => {{
              const rect = image.getBoundingClientRect();
              return rect.left >= 0 && rect.top >= 0 && rect.right <= innerWidth
                && rect.bottom <= innerHeight && image.complete
                && image.naturalWidth > 0 && image.naturalHeight > 0;
            }})
          }};
          window.transitionUnreadySeen = [...reader.querySelectorAll('img.G54Y0W_page')]
            .some(image => !image.complete || image.naturalWidth === 0);
        }}
        function show() {{
          counter.textContent = counterValues[state];
          if (state < {terminal_state}) {{
            let numbers = state === 0 && firstPairMode && !firstPairReady
              ? {initial_partial} : images[state];
            if (!firstPairMode && state === 1 && {str(missing_second_page).lower()}) numbers = [1];
            reader.innerHTML = `<div id="pages"></div><h2 class="title_detail_viewer__detail__info__viewerTitle__GrN4D">{viewer_title}</h2>`;
            const area = document.querySelector('#pages');
            area.style.cssText = 'position:fixed;left:0;top:0;width:1280px;height:720px';
            numbers.forEach((n, index) => {{
              const image = document.createElement('img');
              image.className = 'G54Y0W_page'; image.alt = `page_${{n}}`;
              if ({delayed_manifest_ms} === 0)
                image['__reactFiber$fixture'] = {{memoizedProps:{{webMangaViewerData}},return:null}};
              image.src = src;
              const left = numbers.length===1?360:(index===0?945:{second_left});
              image.style.cssText = `position:absolute;top:40px;left:${{left}}px;width:300px;height:450px;object-fit:fill`;
              area.append(image);
            }});
          }} else if ({str(unknown_tail).lower()}) {{
            reader.innerHTML = `<h2 class="title_detail_viewer__detail__info__viewerTitle__GrN4D">{viewer_title}</h2>`;
          }} else if ('{latest_end}' !== 'none') {{
            reader.innerHTML = `<div class="ChapterLastPage_lastpage__iBifl" style="position:fixed;left:200px;top:30px;width:500px;height:650px">
              <div class="ChapterLastPage_lastpage__actions__3actions__CLl36">
                <a><p class="ChapterLastPage_action__text__HOiTZ">お気に入り</p></a>
                <a><p class="ChapterLastPage_action__text__HOiTZ">いいね</p></a>
                <a><p class="ChapterLastPage_action__text__HOiTZ">コメント</p></a>
              </div>
              <div class="ChapterLastPage_lastpagetitle__INDwU">この作品を読んだあなたにおすすめ</div>
            </div><h2 class="title_detail_viewer__detail__info__viewerTitle__GrN4D" style="position:absolute;top:800px">{viewer_title}</h2>`;
            if ('{latest_end}' === 'missing_actions')
              reader.querySelector('[class*="3actions"]').remove();
            if ('{latest_end}' === 'wrong_labels')
              reader.querySelector('p').textContent = 'other';
            if ('{latest_end}' === 'hidden_recommendations')
              reader.querySelector('[class*="lastpagetitle"]').style.display = 'none';
            if ('{latest_end}' === 'duplicate_title')
              reader.append(reader.querySelector('h2').cloneNode(true));
          }} else {{
            reader.innerHTML = `<div class="ChapterLastPage_lastpage__iBifl" style="position:fixed;left:200px;top:30px;width:500px;height:650px">
              <div class="ChapterLastPage_lastpage__nextChapter__6t7yj" style="position:absolute;left:15px;top:260px;width:470px;height:260px">
                <a class="ChapterLastPage_nextChapter__button__x1P_o" href="/manga/viewer/999">次の話を読む</a>
              </div>
              <h2 class="title_detail_viewer__detail__info__viewerTitle__GrN4D" style="position:absolute;left:120px;top:600px">{viewer_title}</h2>
            </div>`;
          }}
        }}
        if ({delayed_manifest_ms} > 0) setTimeout(() => {{
          for (const image of reader.querySelectorAll('img.G54Y0W_page'))
            image['__reactFiber$fixture'] = {{memoizedProps:{{webMangaViewerData}},return:null}};
        }}, {delayed_manifest_ms});
        if ({delayed_first_pair_ms} > 0) setTimeout(() => {{
          firstPairReady = true;
          show();
        }}, {delayed_first_pair_ms});
        window.addEventListener('keydown', event => {{
          if (event.key === 'ArrowLeft') {{
            if ({str(route_change_on_first_turn).lower()} && state === 0) {{
              history.replaceState(null, '', '/manga/viewer/999');
              return;
            }}
            window.leftTurns = (window.leftTurns || 0) + 1;
            event.preventDefault(); state=Math.min(
              {terminal_state - 1 if stuck_extra_tail else terminal_state},state+1);
            counter.textContent = counterValues[state];
            if (state === transitionOverlapState) {{
              showOverlap();
              if (!{str(persistent_transition_overlap).lower()})
                setTimeout(show, {transition_delay_ms});
            }} else if ({transition_delay_ms} > 0) {{
              for (const image of reader.querySelectorAll('img.G54Y0W_page')) image.removeAttribute('src');
              window.transitionUnreadySeen = [...reader.querySelectorAll('img.G54Y0W_page')]
                .some(image => !image.complete || image.naturalWidth === 0);
              setTimeout(show, {transition_delay_ms});
            }} else {{
              setTimeout(show, {transition_delay_ms});
            }}
          }}
          if (event.key === 'ArrowRight') {{
            event.preventDefault(); state=Math.max(0,state-1);
            counter.textContent = counterValues[state];
            setTimeout(show, {transition_delay_ms});
          }}
        }});
        show();
      </script></body></html>"""


async def _route_comicfuz(
    page,
    *,
    viewer_title: str = EPISODE_TITLE,
    free: bool = True,
    transition_delay_ms: int = 0,
    missing_second_page: bool = False,
    clipped_second_page: bool = False,
    descriptor_width_mismatch: bool = False,
    route_change_on_first_turn: bool = False,
    delayed_manifest_ms: int = 0,
    initial_state: int = 0,
    unknown_tail: bool = False,
    first_page_blank: bool | None = True,
    first_page_blank_inherited: bool = False,
    first_page_blank_malformed: bool = False,
    first_mode_body_page_count: int = 4,
    true_mode_body_page_count: int = 2,
    missing_first_pair_page: int | None = None,
    delayed_first_pair_ms: int = 0,
    transition_overlap_state: int | None = None,
    transition_overlap_new_count: int = 1,
    persistent_transition_overlap: bool = False,
    transition_overlap_variant: str = "valid",
    extra_tail: bool = False,
    latest_end: str = "none",
    stuck_extra_tail: bool = False,
    native_subtitle: str = "",
):
    body = _work_html(free=free)
    image = _viewer_html(
        _jpeg_bytes(),
        viewer_title=viewer_title,
        transition_delay_ms=transition_delay_ms,
        missing_second_page=missing_second_page,
        clipped_second_page=clipped_second_page,
        descriptor_width_mismatch=descriptor_width_mismatch,
        route_change_on_first_turn=route_change_on_first_turn,
        delayed_manifest_ms=delayed_manifest_ms,
        initial_state=initial_state,
        unknown_tail=unknown_tail,
        first_page_blank=first_page_blank,
        first_page_blank_inherited=first_page_blank_inherited,
        first_page_blank_malformed=first_page_blank_malformed,
        first_mode_body_page_count=first_mode_body_page_count,
        true_mode_body_page_count=true_mode_body_page_count,
        missing_first_pair_page=missing_first_pair_page,
        delayed_first_pair_ms=delayed_first_pair_ms,
        transition_overlap_state=transition_overlap_state,
        transition_overlap_new_count=transition_overlap_new_count,
        persistent_transition_overlap=persistent_transition_overlap,
        transition_overlap_variant=transition_overlap_variant,
        extra_tail=extra_tail,
        latest_end=latest_end,
        stuck_extra_tail=stuck_extra_tail,
        native_subtitle=native_subtitle,
    )
    seen: list[str] = []

    async def route_request(route) -> None:
        path = route.request.url.split("?", 1)[0]
        seen.append(path)
        if path == f"{BASE}/manga/1970":
            await route.fulfill(body=body, content_type="text/html; charset=utf-8")
        elif path == VIEWER_URL:
            await route.fulfill(body=image, content_type="text/html; charset=utf-8")
        else:
            await route.fulfill(status=404, body="not found")

    await page.route(f"{BASE}/**", route_request)
    return seen


async def _comicfuz_batch_fixture(
    browser_page,
    tmp_path: Path,
    sync_legacy_unscoped_work,
    *,
    package_function=None,
    unknown_tail: bool = False,
    route_change_on_first_turn: bool = False,
    page_change_timeout_ms: int | None = None,
    **route_options,
):
    seen = await _route_comicfuz(
        browser_page,
        unknown_tail=unknown_tail,
        route_change_on_first_turn=route_change_on_first_turn,
        **route_options,
    )
    target = WatchlistTarget(
        key="comicfuz-batch-fixture",
        work_key="comicfuz:1970",
        site="comicfuz",
        url=WORK_URL,
        label="Verified ComicFUZ Work",
    )
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    discovery_registry = DiscoveryAdapterRegistry()
    discovery_registry.register("comicfuz", ComicFuzDiscoveryAdapter)
    discovery = DiscoveryService(catalog, discovery_registry)
    discovery_result = await discovery.discover(browser_page, target, "full")
    assert discovery_result.complete is True
    watchlist = sync_legacy_unscoped_work(catalog, target)

    policies = SitePolicyRegistry()
    policies.register("comicfuz", ComicFuzSitePolicy)
    adapters = AdapterRegistry()
    if page_change_timeout_ms is None:
        adapters.register("comicfuz", ComicFuzAdapter)
    else:
        def create_adapter():
            adapter = ComicFuzAdapter()
            adapter.page_change_timeout_ms = page_change_timeout_ms
            adapter.render_poll_ms = 10
            return adapter

        adapters.register("comicfuz", create_adapter)
    plan = BatchPlanner(catalog, policies, watchlist=watchlist).plan(site="comicfuz")
    assert len(plan.candidates) == 1
    candidate = plan.candidates[0]
    assert candidate.external_id == "1970:80641"
    assert candidate.artifact_prefix == "003"
    executor_kwargs = {
        "runtime_settings": SiteRuntimeSettings(page_turn_delay_ms=0),
        "library_dir": tmp_path / "library",
        "watchlist": watchlist,
    }
    if package_function is not None:
        executor_kwargs["package_function"] = package_function
    executor = BatchExecutor(catalog, policies, adapters, **executor_kwargs)
    return catalog, discovery, target, plan, candidate, executor, seen, watchlist


@pytest.mark.parametrize(("extra_tail", "latest_end"), [
    (False, "none"), (True, "none"), (True, "valid"), (False, "valid"),
])
async def test_comicfuz_discovery_to_batch_zip_completes_and_rerun_preserves_artifact(
    browser_page, tmp_path: Path, sync_legacy_unscoped_work, extra_tail: bool, latest_end: str
) -> None:
    (
        catalog,
        discovery,
        target,
        plan,
        candidate,
        executor,
        _seen,
        watchlist,
    ) = await _comicfuz_batch_fixture(
        browser_page, tmp_path, sync_legacy_unscoped_work,
        extra_tail=extra_tail, latest_end=latest_end,
        native_subtitle="Fixture subtitle" if latest_end == "valid" else "",
    )

    result = await executor.execute_candidate(
        browser_page,
        candidate,
        output_root=tmp_path / "batch-output",
        library_dir=tmp_path / "library",
        max_pages=5,
        now=NOW,
    )

    item = catalog.get_item(candidate.item_id)
    run = catalog.get_crawl_run(result.crawl_run_id)
    artifacts = catalog.list_artifacts(item_id=item.id)
    assert item.status == "completed"
    assert run.status == "succeeded" and run.stop_reason == "end"
    assert result.stop_reason == "end" and result.page_count == 2
    assert len(artifacts) == 1 and artifacts[0].format == "zip"
    assert result.archive_path.name.startswith("003-")
    with zipfile.ZipFile(result.archive_path) as archive:
        names = archive.namelist()
        assert len(names) == 2
        assert all(name.lower().endswith(".png") for name in names)

    rediscovered = await discovery.discover(browser_page, target, "full")
    planner = BatchPlanner(catalog, executor.policies, watchlist=watchlist)
    assert rediscovered.complete is True
    assert rediscovered.new_count == 0 and rediscovered.known_count == 3
    replanned = planner.plan(site="comicfuz", now=NOW)
    assert catalog.get_item(candidate.item_id).status == "completed"
    assert len(catalog.list_artifacts(item_id=candidate.item_id)) == 1
    assert all(entry.item_id != candidate.item_id for entry in replanned.candidates)
    assert len(plan.candidates) == 1


@pytest.mark.parametrize("failure", [
    "stale_free", "route_drift", "unknown_tail", "stuck_extra_tail",
    "missing_actions", "wrong_labels", "hidden_recommendations", "duplicate_title",
])
async def test_comicfuz_batch_failures_never_complete_or_create_artifact(
    browser_page, tmp_path: Path, sync_legacy_unscoped_work, failure: str
) -> None:
    route_change = failure == "route_drift"
    unknown_tail = failure == "unknown_tail"
    catalog, _discovery, _target, _plan, candidate, executor, _seen, _watchlist = (
        await _comicfuz_batch_fixture(
            browser_page,
            tmp_path,
            sync_legacy_unscoped_work,
            unknown_tail=unknown_tail,
            route_change_on_first_turn=route_change,
            extra_tail=failure not in {"stale_free", "route_drift", "unknown_tail"},
            stuck_extra_tail=failure == "stuck_extra_tail",
            latest_end=failure if failure in {
                "missing_actions", "wrong_labels", "hidden_recommendations", "duplicate_title",
            } else "none",
            page_change_timeout_ms=700,
        )
    )

    if failure == "stale_free":
        await browser_page.unroute_all()
        seen = await _route_comicfuz(browser_page, free=False)
    else:
        seen = None

    with pytest.raises(CandidateExecutionError):
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "batch-output",
            library_dir=tmp_path / "library",
            max_pages=5,
            now=NOW,
        )

    item = catalog.get_item(candidate.item_id)
    assert item.status == "pending"
    assert catalog.list_artifacts(item_id=item.id) == []
    runs = catalog.list_crawl_runs(item_id=item.id)
    assert len(runs) == 1 and runs[0].status == "failed"
    assert not list((tmp_path / "library").rglob("*.zip"))
    if failure == "stale_free":
        assert seen is not None
        assert f"{BASE}/manga/viewer/80641" not in seen
    if failure == "stuck_extra_tail":
        assert await browser_page.evaluate("window.leftTurns") == 3


async def test_comicfuz_batch_packaging_failure_keeps_item_pending(
    browser_page, tmp_path: Path, sync_legacy_unscoped_work
) -> None:
    def fail_package(*_args, **_kwargs):
        raise OSError("synthetic ZIP failure")

    catalog, _discovery, _target, _plan, candidate, executor, _seen, _watchlist = (
        await _comicfuz_batch_fixture(
            browser_page, tmp_path, sync_legacy_unscoped_work,
            package_function=fail_package
        )
    )

    with pytest.raises(CandidateExecutionError):
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "batch-output",
            library_dir=tmp_path / "library",
            max_pages=5,
            now=NOW,
        )

    item = catalog.get_item(candidate.item_id)
    assert item.status == "pending"
    assert catalog.list_artifacts(item_id=item.id) == []
    runs = catalog.list_crawl_runs(item_id=item.id)
    assert len(runs) == 1 and runs[0].status == "failed"
    assert not list((tmp_path / "library").rglob("*.zip"))


async def test_comicfuz_runner_crawls_verified_spreads_to_positive_end(
    browser_page, tmp_path: Path
) -> None:
    seen = await _route_comicfuz(browser_page, transition_delay_ms=350)
    adapter = ComicFuzAdapter(preflight_work_url=WORK_URL)
    adapter.page_change_timeout_ms = 800
    config = RunConfig(
        site="comicfuz",
        source_url=VIEWER_URL,
        output_dir=tmp_path / "isolated-output",
        diagnostics_dir=tmp_path / "isolated-output" / "diagnostics",
        max_pages=5,
        page_turn_delay_ms=0,
        page_change_timeout_ms=2_000,
        navigation_timeout_ms=2_000,
    )

    result = await CrawlerRunner(config).run(browser_page, adapter)

    assert result.stop_state is PageState.END
    assert len(result.pages) == 2
    assert [page.identity.page_id for page in result.pages] == [
        "page_0",
        "page_1",
    ]
    assert all(page.mime_type in {"image/jpeg", "image/png"} for page in result.pages)
    assert f"{BASE}/manga/viewer/80641" in seen
    assert f"{BASE}/manga/viewer/999" not in seen
    assert (tmp_path / "isolated-output" / "page-0001.png").is_file()
    assert await browser_page.evaluate("() => window.transitionUnreadySeen === true")


@pytest.mark.parametrize(("overlap_state", "overlap_size"), [(3, 3), (3, 4), (5, 3)])
async def test_comicfuz_waits_through_contiguous_transition_overlap_and_reaches_end(
    browser_page, tmp_path: Path, overlap_state: int, overlap_size: int
) -> None:
    await _route_comicfuz(
        browser_page,
        true_mode_body_page_count=10,
        transition_delay_ms=180,
        transition_overlap_state=overlap_state,
        transition_overlap_new_count=overlap_size - 2,
    )
    adapter = ComicFuzAdapter(preflight_work_url=WORK_URL)
    config = RunConfig(
        site="comicfuz",
        source_url=VIEWER_URL,
        output_dir=tmp_path / "overlap-output",
        diagnostics_dir=tmp_path / "overlap-output" / "diagnostics",
        max_pages=12,
        page_turn_delay_ms=0,
        page_change_timeout_ms=1_000,
        navigation_timeout_ms=2_000,
    )

    result = await CrawlerRunner(config).run(browser_page, adapter)

    assert result.stop_state is PageState.END
    assert len(result.pages) == 10
    assert [page.identity.page_id for page in result.pages] == [
        "page_0",
        "page_1|page_2",
        "page_1|page_2",
        "page_3|page_4",
        "page_3|page_4",
        "page_5|page_6",
        "page_5|page_6",
        "page_7|page_8",
        "page_7|page_8",
        "page_9",
    ]
    assert adapter._captured_indices == list(range(10))
    previous = [3, 4] if overlap_state == 3 else [7, 8]
    next_group = [5, 6] if overlap_state == 3 else [9, 10]
    expected_overlap = previous + next_group[: overlap_size - 2]
    observed_overlap = await browser_page.evaluate("() => window.transitionOverlapSeen")
    assert observed_overlap == {
        "state": overlap_state,
        "numbers": expected_overlap,
        "imageReady": [True] * overlap_size,
        "ready": [False, *([True] * (overlap_size - 2)), False],
    }
    assert not (tmp_path / "overlap-output" / "archive.zip").exists()


async def test_comicfuz_persistent_transition_overlap_times_out_without_batch_artifact(
    browser_page, tmp_path: Path, sync_legacy_unscoped_work
) -> None:
    catalog, _discovery, _target, _plan, candidate, executor, _seen, _watchlist = (
        await _comicfuz_batch_fixture(
            browser_page,
            tmp_path,
            sync_legacy_unscoped_work,
            page_change_timeout_ms=250,
            true_mode_body_page_count=10,
            transition_delay_ms=80,
            transition_overlap_state=3,
            persistent_transition_overlap=True,
        )
    )

    with pytest.raises(CandidateExecutionError):
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "batch-output",
            library_dir=tmp_path / "library",
            max_pages=12,
            now=NOW,
        )

    item = catalog.get_item(candidate.item_id)
    assert item.status == "pending"
    assert catalog.list_artifacts(item_id=item.id) == []
    run = catalog.list_crawl_runs(item_id=item.id)[0]
    assert run.status == "failed"
    assert run.error_type == "PageChangeTimeoutError"
    assert run.error_message is not None
    assert "did not reach a stable next page or end panel" in run.error_message
    assert not list((tmp_path / "library").rglob("*.zip"))


@pytest.mark.parametrize(
    "variant",
    ["outside", "gap", "duplicate", "role", "all_ready", "visual_unsafe", "dimensions"],
)
async def test_comicfuz_invalid_transition_wide_shapes_fail_closed(
    browser_page, tmp_path: Path, variant: str
) -> None:
    await _route_comicfuz(
        browser_page,
        true_mode_body_page_count=10,
        transition_delay_ms=160,
        transition_overlap_state=3,
        transition_overlap_variant=variant,
    )
    adapter = ComicFuzAdapter(preflight_work_url=WORK_URL)
    config = RunConfig(
        site="comicfuz",
        source_url=VIEWER_URL,
        output_dir=tmp_path / "invalid-overlap-output",
        diagnostics_dir=tmp_path / "invalid-overlap-output" / "diagnostics",
        max_pages=12,
        retry_count=0,
        page_turn_delay_ms=0,
        page_change_timeout_ms=1_000,
        navigation_timeout_ms=2_000,
    )

    with pytest.raises(UnknownPageStateError):
        await CrawlerRunner(config).run(browser_page, adapter)

    assert not (tmp_path / "invalid-overlap-output" / "archive.zip").exists()


@pytest.mark.parametrize("operation", ["detect", "capture"])
async def test_comicfuz_transition_wait_does_not_weaken_capture_or_state_shape_guard(
    browser_page, operation: str
) -> None:
    await _route_comicfuz(browser_page, true_mode_body_page_count=10)
    adapter = ComicFuzAdapter(preflight_work_url=WORK_URL)
    await adapter.prepare_page(browser_page)
    await browser_page.goto(WORK_URL, wait_until="commit")
    await adapter.configure_target_identity("1970:80641", "comicfuz:1970")
    adapter.resolve_initial_navigation_url(VIEWER_URL)
    await adapter.initialize(browser_page)
    await browser_page.evaluate(
        """() => {
          const area = document.querySelector('#pages');
          const template = area.querySelector('img.G54Y0W_page');
          const key = Object.keys(template).find(name => name.startsWith('__reactFiber$'));
          for (const [number, left] of [[1, 655], [2, 355]]) {
            const image = document.createElement('img');
            image.className = 'G54Y0W_page';
            image.alt = `page_${number}`;
            image.src = template.src;
            image[key] = template[key];
            image.style.cssText = `position:absolute;top:40px;left:${left}px;width:300px;height:450px;object-fit:fill`;
            area.append(image);
          }
        }"""
    )
    adapter._advance_pending = True

    with pytest.raises(UnknownPageStateError, match="unsupported shape"):
        if operation == "detect":
            await adapter.detect_state(browser_page)
        else:
            await adapter.capture_page(browser_page)

    assert adapter._captured_indices == []


async def test_comicfuz_nonfree_preflight_stops_before_reader_navigation(
    browser_page, tmp_path: Path
) -> None:
    seen = await _route_comicfuz(browser_page, free=False)
    adapter = ComicFuzAdapter(preflight_work_url=WORK_URL)
    config = RunConfig(
        site="comicfuz",
        source_url=VIEWER_URL,
        output_dir=tmp_path / "isolated-output",
        diagnostics_dir=tmp_path / "isolated-output" / "diagnostics",
        page_turn_delay_ms=0,
        navigation_timeout_ms=2_000,
    )

    with pytest.raises(UnknownPageStateError, match="lacks exact current anonymous free-listing"):
        await CrawlerRunner(config).run(browser_page, adapter)

    assert f"{BASE}/manga/viewer/80641" not in seen
    assert not (tmp_path / "isolated-output" / "page-0001.png").exists()


@pytest.mark.parametrize("failure", ["missing", "clipped", "wrong_dimensions"])
async def test_comicfuz_incomplete_spread_never_completes(
    browser_page, tmp_path: Path, failure: str
) -> None:
    seen = await _route_comicfuz(
        browser_page,
        missing_second_page=failure == "missing",
        clipped_second_page=failure == "clipped",
        descriptor_width_mismatch=failure == "wrong_dimensions",
    )
    adapter = ComicFuzAdapter(preflight_work_url=WORK_URL)
    adapter.page_change_timeout_ms = 800
    config = RunConfig(
        site="comicfuz",
        source_url=VIEWER_URL,
        output_dir=tmp_path / "isolated-output",
        diagnostics_dir=tmp_path / "isolated-output" / "diagnostics",
        max_pages=5,
        retry_count=1,
        page_turn_delay_ms=0,
        page_change_timeout_ms=800,
        navigation_timeout_ms=2_000,
    )

    with pytest.raises((UnknownPageStateError, PageChangeTimeoutError)):
        await CrawlerRunner(config).run(browser_page, adapter)

    assert f"{BASE}/manga/viewer/80641" in seen
    assert not (tmp_path / "isolated-output" / "archive.zip").exists()
    manifest_path = tmp_path / "isolated-output" / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected_sequences = [] if failure == "wrong_dimensions" else [1]
        assert [page["sequence"] for page in manifest["pages"]] == expected_sequences
    else:
        assert failure == "wrong_dimensions"


async def test_comicfuz_capture_keeps_exact_bound_blob_jpeg_bytes(
    browser_page,
) -> None:
    await _route_comicfuz(browser_page)
    adapter = ComicFuzAdapter(preflight_work_url=WORK_URL)
    await adapter.prepare_page(browser_page)
    await browser_page.goto(WORK_URL, wait_until="commit")
    await adapter.configure_target_identity("1970:80641", "comicfuz:1970")
    adapter.resolve_initial_navigation_url(VIEWER_URL)
    await adapter.initialize(browser_page)
    rows = await adapter._active_page_rows(browser_page)
    selected = rows[0]
    exact_bytes = _jpeg_bytes((201, 43, 87))

    class _Response:
        def __init__(self, url: str, body: bytes) -> None:
            self.url = url
            self.request = SimpleNamespace(resource_type="image")
            self._body = body

        async def body(self) -> bytes:
            return self._body

    adapter._handle_source_response(_Response(str(selected["src"]), exact_bytes))
    result = await adapter.capture_page(browser_page)

    assert result is not None and result[0].file_extension == ".jpg"
    assert result[0].data == exact_bytes
    assert (result[0].width, result[0].height) == (96, 144)


async def test_comicfuz_restore_at_spread_rewinds_to_page_zero(browser_page) -> None:
    await _route_comicfuz(browser_page, initial_state=1)
    adapter = ComicFuzAdapter(preflight_work_url=WORK_URL)
    await adapter.prepare_page(browser_page)
    await browser_page.goto(WORK_URL, wait_until="commit")
    await adapter.configure_target_identity("1970:80641", "comicfuz:1970")
    adapter.resolve_initial_navigation_url(VIEWER_URL)

    await adapter.initialize(browser_page)

    rows = await adapter._active_page_rows(browser_page)
    assert tuple(row["number"] for row in rows) == (0,)


@pytest.mark.parametrize("extra_tail", [False, True])
async def test_comicfuz_native_nonblank_first_page_captures_verified_pair_to_end(
    browser_page, tmp_path: Path, extra_tail: bool
) -> None:
    seen = await _route_comicfuz(
        browser_page,
        first_page_blank=False,
        first_page_blank_inherited=True,
        first_mode_body_page_count=15,
        extra_tail=extra_tail,
        latest_end="valid" if extra_tail else "none",
        native_subtitle="Fixture subtitle" if extra_tail else "",
    )
    adapter = ComicFuzAdapter(preflight_work_url=WORK_URL)
    config = RunConfig(
        site="comicfuz",
        source_url=VIEWER_URL,
        output_dir=tmp_path / "isolated-output",
        diagnostics_dir=tmp_path / "isolated-output" / "diagnostics",
        max_pages=20,
        page_turn_delay_ms=0,
        page_change_timeout_ms=1_000,
        navigation_timeout_ms=2_000,
    )

    result = await CrawlerRunner(config).run(browser_page, adapter)

    assert result.stop_state is PageState.END
    assert len(result.pages) == 15
    assert result.pages[0].identity.page_id == "page_0|page_1"
    assert result.pages[-1].identity.page_id == "page_14"
    assert adapter._captured_indices == list(range(15))
    assert f"{BASE}/manga/viewer/80641" in seen
    assert f"{BASE}/manga/viewer/999" not in seen
    actual_flag = await browser_page.evaluate("() => window.nativeFlagFixture")
    assert actual_flag == {"value": False, "own": False}


async def test_comicfuz_restore_in_nonblank_mode_rewinds_to_exact_initial_pair(
    browser_page,
) -> None:
    await _route_comicfuz(
        browser_page,
        initial_state=1,
        first_page_blank=False,
        first_page_blank_inherited=True,
    )
    adapter = ComicFuzAdapter(preflight_work_url=WORK_URL)
    await adapter.prepare_page(browser_page)
    await browser_page.goto(WORK_URL, wait_until="commit")
    await adapter.configure_target_identity("1970:80641", "comicfuz:1970")
    adapter.resolve_initial_navigation_url(VIEWER_URL)

    await adapter.initialize(browser_page)

    assert tuple(
        row["number"] for row in await adapter._active_page_rows(browser_page)
    ) == (0, 1)


@pytest.mark.parametrize("missing_index", [0, 1])
async def test_comicfuz_waits_for_both_initial_pair_images(
    browser_page, missing_index: int
) -> None:
    await _route_comicfuz(
        browser_page,
        first_page_blank=False,
        missing_first_pair_page=missing_index,
        delayed_first_pair_ms=250,
    )
    adapter = ComicFuzAdapter(preflight_work_url=WORK_URL)
    adapter.page_change_timeout_ms = 1_000
    await adapter.prepare_page(browser_page)
    await browser_page.goto(WORK_URL, wait_until="commit")
    await adapter.configure_target_identity("1970:80641", "comicfuz:1970")
    adapter.resolve_initial_navigation_url(VIEWER_URL)

    await adapter.initialize(browser_page)

    assert tuple(
        row["number"] for row in await adapter._active_page_rows(browser_page)
    ) == (0, 1)
    assert adapter._captured_indices == []


@pytest.mark.parametrize("missing_index", [0, 1])
async def test_comicfuz_incomplete_initial_pair_times_out_without_capture(
    browser_page, tmp_path: Path, missing_index: int
) -> None:
    await _route_comicfuz(
        browser_page,
        first_page_blank=False,
        missing_first_pair_page=missing_index,
    )
    adapter = ComicFuzAdapter(preflight_work_url=WORK_URL)
    adapter.page_change_timeout_ms = 100
    await adapter.prepare_page(browser_page)
    await browser_page.goto(WORK_URL, wait_until="commit")
    await adapter.configure_target_identity("1970:80641", "comicfuz:1970")
    adapter.resolve_initial_navigation_url(VIEWER_URL)

    with pytest.raises(PageChangeTimeoutError, match="first reader page"):
        await adapter.initialize(browser_page)

    assert adapter._captured_indices == []
    assert not (tmp_path / "archive.zip").exists()


@pytest.mark.parametrize("flag_state", ["missing", "malformed"])
async def test_comicfuz_first_page_mode_requires_a_native_boolean(
    browser_page, flag_state: str
) -> None:
    await _route_comicfuz(
        browser_page,
        first_page_blank=None if flag_state == "missing" else True,
        first_page_blank_malformed=flag_state == "malformed",
    )
    adapter = ComicFuzAdapter(preflight_work_url=WORK_URL)
    await adapter.prepare_page(browser_page)
    await browser_page.goto(WORK_URL, wait_until="commit")
    await adapter.configure_target_identity("1970:80641", "comicfuz:1970")
    adapter.resolve_initial_navigation_url(VIEWER_URL)

    with pytest.raises(UnknownPageStateError, match="first-page layout flag"):
        await adapter.initialize(browser_page)


@pytest.mark.parametrize("flag_state", ["missing", "malformed", "changed"])
async def test_comicfuz_first_page_mode_drift_fails_closed(
    browser_page, flag_state: str
) -> None:
    await _route_comicfuz(browser_page)
    adapter = ComicFuzAdapter(preflight_work_url=WORK_URL)
    await adapter.prepare_page(browser_page)
    await browser_page.goto(WORK_URL, wait_until="commit")
    await adapter.configure_target_identity("1970:80641", "comicfuz:1970")
    adapter.resolve_initial_navigation_url(VIEWER_URL)
    await adapter.initialize(browser_page)
    await browser_page.locator("img.G54Y0W_page").first.evaluate(
        """(element, state) => {
          let fiber = element[Object.keys(element).find(key => key.startsWith('__reactFiber$'))];
          while (fiber && !fiber.memoizedProps?.webMangaViewerData) fiber = fiber.return;
          const data = fiber.memoizedProps.webMangaViewerData.viewerData;
          if (state === 'missing') delete data.isFirstPageBlank;
          else data.isFirstPageBlank = state === 'changed' ? false : 'true';
        }""",
        flag_state,
    )

    expected_error = (
        "viewer page-role manifest changed"
        if flag_state == "changed"
        else "first-page layout flag"
    )
    with pytest.raises(UnknownPageStateError, match=expected_error):
        await adapter.detect_state(browser_page)


async def test_comicfuz_output_metadata_uses_verified_work_and_episode_titles(
    browser_page,
) -> None:
    await _route_comicfuz(browser_page)
    adapter = ComicFuzAdapter(preflight_work_url=WORK_URL)
    await adapter.prepare_page(browser_page)
    await browser_page.goto(WORK_URL, wait_until="commit")
    await adapter.configure_target_identity("1970:80641", "comicfuz:1970")
    adapter.resolve_initial_navigation_url(VIEWER_URL)

    await adapter.initialize(browser_page)

    metadata = adapter.get_output_metadata()
    assert metadata["title"] == "Verified ComicFUZ Work"
    assert metadata["order"] == EPISODE_TITLE
    assert metadata["genre"] == "漫画"


async def test_comicfuz_reader_title_must_match_fresh_listing_row(browser_page) -> None:
    await _route_comicfuz(browser_page, viewer_title="different episode")
    adapter = ComicFuzAdapter(preflight_work_url=WORK_URL)
    await adapter.prepare_page(browser_page)
    await browser_page.goto(WORK_URL, wait_until="commit")
    await adapter.configure_target_identity("1970:80641", "comicfuz:1970")
    adapter.resolve_initial_navigation_url(VIEWER_URL)

    with pytest.raises(UnknownPageStateError, match="does not match its freshly verified"):
        await adapter.initialize(browser_page)


async def test_comicfuz_waits_for_initial_native_page_manifest(browser_page) -> None:
    await _route_comicfuz(browser_page, delayed_manifest_ms=250)
    adapter = ComicFuzAdapter(preflight_work_url=WORK_URL)
    adapter.page_change_timeout_ms = 1_000
    await adapter.prepare_page(browser_page)
    await browser_page.goto(WORK_URL, wait_until="commit")
    await adapter.configure_target_identity("1970:80641", "comicfuz:1970")
    adapter.resolve_initial_navigation_url(VIEWER_URL)

    await adapter.initialize(browser_page)

    assert adapter._viewer_pages is not None
    assert tuple(row["number"] for row in await adapter._active_page_rows(browser_page)) == (0,)


async def test_comicfuz_established_manifest_disappearance_fails_closed(browser_page) -> None:
    await _route_comicfuz(browser_page)
    adapter = ComicFuzAdapter(preflight_work_url=WORK_URL)
    await adapter.prepare_page(browser_page)
    await browser_page.goto(WORK_URL, wait_until="commit")
    await adapter.configure_target_identity("1970:80641", "comicfuz:1970")
    adapter.resolve_initial_navigation_url(VIEWER_URL)
    await adapter.initialize(browser_page)
    await browser_page.locator("img.G54Y0W_page").first.evaluate(
        """element => {
          const key = Object.keys(element).find(name => name.startsWith('__reactFiber$'));
          element[key].memoizedProps = {};
        }"""
    )

    with pytest.raises(UnknownPageStateError, match="established viewer page-role manifest disappeared"):
        await adapter.detect_state(browser_page)


@pytest.mark.parametrize("drift", ["anonymous", "title", "subtitle", "malformed_subtitle"])
async def test_comicfuz_identity_drift_fails_closed(browser_page, drift: str) -> None:
    await _route_comicfuz(browser_page)
    adapter = ComicFuzAdapter(preflight_work_url=WORK_URL)
    await adapter.prepare_page(browser_page)
    await browser_page.goto(WORK_URL, wait_until="commit")
    await adapter.configure_target_identity("1970:80641", "comicfuz:1970")
    adapter.resolve_initial_navigation_url(VIEWER_URL)
    await adapter.initialize(browser_page)

    if drift == "anonymous":
        await browser_page.locator('a[href="/account/signin"]').evaluate("element => element.remove()")
        await browser_page.evaluate(
            """() => document.body.insertAdjacentHTML('beforeend',
              '<a href="/account/signout">Sign out</a>')"""
        )
    elif drift == "title":
        await browser_page.locator(adapter.viewer_title_selector).evaluate(
            "element => element.textContent = 'different episode'"
        )
    else:
        await browser_page.evaluate(
            """value => {
              const node = document.querySelector('#__NEXT_DATA__');
              const data = JSON.parse(node.textContent);
              data.props.pageProps.data.chapterSubName = value;
              node.textContent = JSON.stringify(data);
            }""",
            1 if drift == "malformed_subtitle" else "different subtitle",
        )

    with pytest.raises(UnknownPageStateError):
        await adapter.detect_state(browser_page)


async def test_comicfuz_extra_tail_cannot_skip_uncaptured_body_or_be_captured(browser_page) -> None:
    await _route_comicfuz(browser_page, extra_tail=True)
    adapter = ComicFuzAdapter(preflight_work_url=WORK_URL)
    await browser_page.goto(WORK_URL, wait_until="commit")
    await adapter.configure_target_identity("1970:80641", "comicfuz:1970")
    adapter.resolve_initial_navigation_url(VIEWER_URL)
    await adapter.initialize(browser_page)
    await adapter.capture_page(browser_page)
    # Skip the final body+extra spread, simulating unexpected viewer drift.
    await browser_page.keyboard.press("ArrowLeft")
    await browser_page.wait_for_function("document.querySelector('img').alt === 'page_1'")
    await browser_page.keyboard.press("ArrowLeft")
    await browser_page.wait_for_function("document.querySelector('img').alt === 'page_3'")
    with pytest.raises(UnknownPageStateError, match="extra tail is out of sequence"):
        await adapter.detect_state(browser_page)
    with pytest.raises(UnknownPageStateError, match="no verified body"):
        await adapter.capture_page(browser_page)
    with pytest.raises(UnknownPageStateError):
        await adapter.go_next(browser_page)
    assert adapter._captured_indices == [0]
    assert await browser_page.evaluate("window.leftTurns") == 2


async def test_comicfuz_other_episode_route_fails_closed(browser_page) -> None:
    await _route_comicfuz(browser_page)
    adapter = ComicFuzAdapter(preflight_work_url=WORK_URL)
    await adapter.prepare_page(browser_page)
    await browser_page.goto(WORK_URL, wait_until="commit")
    await adapter.configure_target_identity("1970:80641", "comicfuz:1970")
    adapter.resolve_initial_navigation_url(VIEWER_URL)
    await adapter.initialize(browser_page)
    await browser_page.goto(f"{BASE}/manga/viewer/999", wait_until="commit")

    with pytest.raises(UnknownPageStateError, match="left the configured free episode"):
        await adapter.detect_state(browser_page)


async def test_comicfuz_runner_rejects_episode_route_drift_without_archive(
    browser_page, tmp_path: Path
) -> None:
    await _route_comicfuz(browser_page, route_change_on_first_turn=True)
    adapter = ComicFuzAdapter(preflight_work_url=WORK_URL)
    adapter.page_change_timeout_ms = 800
    config = RunConfig(
        site="comicfuz",
        source_url=VIEWER_URL,
        output_dir=tmp_path / "isolated-output",
        diagnostics_dir=tmp_path / "isolated-output" / "diagnostics",
        page_turn_delay_ms=0,
        page_change_timeout_ms=800,
        navigation_timeout_ms=2_000,
    )

    with pytest.raises(UnknownPageStateError, match="left the configured free episode"):
        await CrawlerRunner(config).run(browser_page, adapter)

    assert not (tmp_path / "isolated-output" / "archive.zip").exists()


async def test_comicfuz_unknown_tail_does_not_complete(browser_page, tmp_path: Path) -> None:
    await _route_comicfuz(browser_page, unknown_tail=True)
    adapter = ComicFuzAdapter(preflight_work_url=WORK_URL)
    config = RunConfig(
        site="comicfuz",
        source_url=VIEWER_URL,
        output_dir=tmp_path / "isolated-output",
        diagnostics_dir=tmp_path / "isolated-output" / "diagnostics",
        max_pages=10,
        retry_count=0,
        page_turn_delay_ms=0,
        page_change_timeout_ms=500,
        navigation_timeout_ms=2_000,
    )

    with pytest.raises(UnknownPageStateError):
        await CrawlerRunner(config).run(browser_page, adapter)

    assert not (tmp_path / "isolated-output" / "archive.zip").exists()


async def test_comicfuz_max_pages_guard_prevents_partial_success(browser_page, tmp_path: Path) -> None:
    await _route_comicfuz(browser_page)
    adapter = ComicFuzAdapter(preflight_work_url=WORK_URL)
    config = RunConfig(
        site="comicfuz",
        source_url=VIEWER_URL,
        output_dir=tmp_path / "isolated-output",
        diagnostics_dir=tmp_path / "isolated-output" / "diagnostics",
        max_pages=1,
        retry_count=0,
        page_turn_delay_ms=0,
        page_change_timeout_ms=2_000,
        navigation_timeout_ms=2_000,
    )

    with pytest.raises(MaxPagesExceededError, match="max_pages exceeded"):
        await CrawlerRunner(config).run(browser_page, adapter)

    assert not (tmp_path / "isolated-output" / "archive.zip").exists()


async def test_comicfuz_unavailable_source_bytes_use_native_pixel_png(browser_page) -> None:
    await _route_comicfuz(browser_page)
    adapter = ComicFuzAdapter(preflight_work_url=WORK_URL)
    await adapter.prepare_page(browser_page)
    await browser_page.goto(WORK_URL, wait_until="commit")
    await adapter.configure_target_identity("1970:80641", "comicfuz:1970")
    adapter.resolve_initial_navigation_url(VIEWER_URL)
    await adapter.initialize(browser_page)
    rows = await adapter._active_page_rows(browser_page)
    src = str(rows[0]["src"])

    class _UnavailableResponse:
        url = src
        request = SimpleNamespace(resource_type="image")

        async def body(self) -> bytes:
            return b""

    adapter._handle_source_response(_UnavailableResponse())
    await asyncio.sleep(0)
    result = await adapter.capture_page(browser_page)

    assert result is not None and result[0].file_extension == ".png"
    assert (result[0].width, result[0].height) == (96, 144)


async def test_comicfuz_source_node_mutation_during_capture_is_rejected(browser_page) -> None:
    await _route_comicfuz(browser_page)
    adapter = ComicFuzAdapter(preflight_work_url=WORK_URL)
    await adapter.prepare_page(browser_page)
    await browser_page.goto(WORK_URL, wait_until="commit")
    await adapter.configure_target_identity("1970:80641", "comicfuz:1970")
    adapter.resolve_initial_navigation_url(VIEWER_URL)
    await adapter.initialize(browser_page)
    rows = await adapter._active_page_rows(browser_page)
    src = str(rows[0]["src"])

    class _MutatingResponse:
        url = src
        request = SimpleNamespace(resource_type="image")

        async def body(self) -> bytes:
            await browser_page.locator("img.G54Y0W_page").evaluate(
                "element => element.alt = 'page_99'"
            )
            return _jpeg_bytes()

    adapter._handle_source_response(_MutatingResponse())
    with pytest.raises(UnknownPageStateError):
        await adapter.capture_page(browser_page)


async def test_comicfuz_native_page_role_manifest_drift_is_rejected(browser_page) -> None:
    await _route_comicfuz(browser_page)
    adapter = ComicFuzAdapter(preflight_work_url=WORK_URL)
    await adapter.prepare_page(browser_page)
    await browser_page.goto(WORK_URL, wait_until="commit")
    await adapter.configure_target_identity("1970:80641", "comicfuz:1970")
    adapter.resolve_initial_navigation_url(VIEWER_URL)
    await adapter.initialize(browser_page)
    await browser_page.locator("img.G54Y0W_page").first.evaluate(
        """element => {
          let fiber = element[Object.keys(element).find(key => key.startsWith('__reactFiber$'))];
          while (fiber && !fiber.memoizedProps?.webMangaViewerData) fiber = fiber.return;
          fiber.memoizedProps.webMangaViewerData.viewerData.pages[0].image.imageWidth = 97;
        }"""
    )

    with pytest.raises(UnknownPageStateError, match="page-role manifest changed"):
        await adapter.detect_state(browser_page)


@pytest.mark.parametrize(
    ("property_name", "value"),
    [
        ("filter", "invert(1)"),
        ("transform", "rotate(2deg)"),
        ("rotate", "180deg"),
        ("scale", "1.01"),
        ("translate", "1px 0"),
        ("clip", "rect(0px, 10px, 10px, 0px)"),
        ("object-fit", "cover"),
        ("clip-path", "inset(1px)"),
    ],
)
async def test_comicfuz_rejects_visual_effects_that_change_visible_page_pixels(
    browser_page, property_name: str, value: str
) -> None:
    await _route_comicfuz(browser_page)
    adapter = ComicFuzAdapter(preflight_work_url=WORK_URL)
    await adapter.prepare_page(browser_page)
    await browser_page.goto(WORK_URL, wait_until="commit")
    await adapter.configure_target_identity("1970:80641", "comicfuz:1970")
    adapter.resolve_initial_navigation_url(VIEWER_URL)
    await adapter.initialize(browser_page)
    await browser_page.locator("img.G54Y0W_page").first.evaluate(
        "(element, [name, value]) => element.style.setProperty(name, value)",
        [property_name, value],
    )

    with pytest.raises(UnknownPageStateError, match="unverified filter, transform, or crop"):
        await adapter.detect_state(browser_page)
