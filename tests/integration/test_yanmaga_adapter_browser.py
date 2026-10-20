from __future__ import annotations

import json
import zipfile
from datetime import datetime
from urllib.parse import quote, unquote, urlsplit

import pytest
from PIL import Image

from screenshot_crawler.batch import BatchExecutor, BatchPlanner, CandidateExecutionError
from screenshot_crawler.catalog import (
    CatalogService,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.core.errors import (
    AccessResourceUnavailableError,
    PageChangeTimeoutError,
    UnknownPageStateError,
)
from screenshot_crawler.core.models import RunConfig
from screenshot_crawler.core.runner import CrawlerRunner
from screenshot_crawler.core.state import PageState
from screenshot_crawler.discovery.models import DiscoveredItem, DiscoveredRecord, DiscoveredSource
from screenshot_crawler.runtime_settings import SiteRuntimeSettings
from screenshot_crawler.site_adapters.registry import AdapterRegistry
from screenshot_crawler.site_adapters.yanmaga import adapter as adapter_module
from screenshot_crawler.site_adapters.yanmaga.adapter import YanmagaAdapter
from screenshot_crawler.site_adapters.yanmaga.discovery import (
    YanmagaDiscoveryAdapter,
    YanmagaListingRow,
    YanmagaListingSnapshot,
)
from screenshot_crawler.site_adapters.yanmaga.native_capture import (
    MAX_CAPTURE_PIXELS,
    capture_yanmaga_native_webp,
    dispose_yanmaga_native_observer,
    install_yanmaga_native_observer,
)
from screenshot_crawler.site_policies import SitePolicyRegistry, YanmagaSitePolicy

pytestmark = pytest.mark.asyncio(loop_scope="module")

SLUG = "ウサギとカメのゆる山歩"
EPISODE_ID = "2de76848d607c9920f18147b763a6aec"
NEXT_EPISODE_ID = "abcdef0123456789abcdef0123456789"
NEXT_ORDER_LABEL = "\u6b21\u306e\u8a71 \u6b69\u8abf"
WORK_URL = f"https://yanmaga.jp/comics/{quote(SLUG, safe='')}"
SOURCE_URL = f"{WORK_URL}/{EPISODE_ID}"
VIEWER_URL = f"https://yanmaga.jp/viewer/comics/{quote(SLUG, safe='')}/{EPISODE_ID}"
VIEWER_NAVIGATION_URL = f"{VIEWER_URL}?cid=AbCd0123456789EfGhIj"
WORK_KEY = f"yanmaga:{SLUG}"
NOW = datetime(2026, 10, 20, 12, tzinfo=JST)


def _segment_data(color: str, index: int) -> str:
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="1127" height="536">'
        f'<rect width="1127" height="536" fill="{color}"/>'
        f'<text x="32" y="80" font-size="48">page {index}</text></svg>'
    )
    return f"data:image/svg+xml,{quote(svg, safe='')}"


def _viewer_html(
    *,
    missing_half: bool = False,
    thin_segment: bool = False,
    oversized_last_segment: bool = False,
    unknown_aux: bool = False,
    unsafe_end: bool = False,
    delayed_end: bool = False,
    access_gate: bool = False,
    terminal_geometry: str = "valid",
    arrow_mode: str = "hidden",
    first_page_overlay: bool = False,
    menu_hideable: bool = True,
    edge_obstruction: bool = False,
    adjacent_overlap: bool = False,
    terminal_control: str = "valid_next",
    native_capture: bool = False,
    native_style_unsupported: bool = False,
    native_layer_unsupported: bool = False,
    native_transparent: bool = False,
    native_ambiguous: bool = False,
    native_host_pseudo_issue: str | None = None,
    native_wrapper_transform: str | None = None,
) -> str:
    wrappers = []
    colors = ("#b32b39", "#22784c", "#345ca8", "#b08228")
    pseudo_issue_css = {
        None: "",
        "background": "background-color:rgba(255,0,0,.2)",
        "filter": "filter:blur(1px)",
        "backdrop_filter": "backdrop-filter:blur(1px)",
        "shadow": "box-shadow:0 0 2px #f00",
        "content": "content:'x'",
    }
    if native_host_pseudo_issue not in pseudo_issue_css:
        raise ValueError(f"unsupported synthetic host pseudo issue: {native_host_pseudo_issue}")
    for index, color in enumerate(colors, start=1):
        segment_images = []
        for segment_index in range(3):
            styles = []
            if native_style_unsupported and index in {1, 3}:
                styles.append("filter:blur(1px)")
            if native_layer_unsupported and index == 1 and segment_index == 1:
                styles.append("z-index:2")
            if thin_segment and index == 4 and segment_index == 0:
                styles.append("width:1px")
            if oversized_last_segment and index == 4 and segment_index == 2:
                styles.append("height:700px")
            style_attr = f' style="{";".join(styles)}"' if styles else ""
            if native_capture:
                pseudo_issue = (
                    pseudo_issue_css[native_host_pseudo_issue]
                    if index == 1 and segment_index == 0
                    else ""
                )
                pseudo_class = (
                    f" pseudo-{native_host_pseudo_issue}"
                    if pseudo_issue
                    else ""
                )
                segment_images.append(
                    f'<div class="segment-host{pseudo_class}">'
                    f'<img alt=""{style_attr}></div>'
                )
            else:
                segment_images.append(
                    f'<img src="{_segment_data(color, index)}" alt=""{style_attr}>'
                )
        images = "" if missing_half and index == 3 else "".join(segment_images)
        left = (
            "1264px"
            if index == 3 and adjacent_overlap
            else "1290px"
            if index == 3
            else "0px"
        )
        if native_capture:
            transform_override = (
                f";transform:{native_wrapper_transform}"
                if index == 1 and native_wrapper_transform is not None
                else ""
            )
            if missing_half and index == 3:
                images = ""
            wrappers.append(
                f'<div id="content-p{index}" class="body-page" '
                f'style="left:0;display:none{transform_override}">'
                f'<div class="pt-img">{images}</div></div>'
            )
        else:
            wrappers.append(
                f'<div id="content-p{index}" class="body-page" '
                f'style="left:{left};display:none">{images}</div>'
            )
    recommend_display = "block" if terminal_geometry == "obstructed" else "none"
    auxiliary = (
        '<div id="ads"></div>'
        f'<div id="recommend" style="display:{recommend_display}"></div>'
    )
    if unknown_aux:
        auxiliary += '<div id="unknown-promo"></div>'
    if access_gate:
        auxiliary += (
            '<div role="dialog" class="quota-modal" '
            'style="position:absolute;right:10px;bottom:50px;width:220px;height:100px">'
            'ポイントを使って読む</div>'
        )
    title = '<span class="episode-modal-eptitle">次の話 歩調</span>'
    next_control = '<a id="js-btn-valid-next-episode">次の話を読む</a>'
    signup_control = (
        '<a class="mod-button--orange content ga-viewer-rental-signup" '
        f'href="/customers/sign-up?forward={NEXT_EPISODE_ID}">無料登録して読む</a>'
    )
    controls = {
        "valid_next": next_control,
        "signup": signup_control,
        "signup_wrong_title": signup_control,
        "signup_wrong_label": signup_control.replace("無料登録して読む", "読む"),
        "signup_wrong_path": signup_control.replace("/customers/sign-up", "/customers/sign-in"),
        "signup_foreign": signup_control.replace(
            'href="/customers/sign-up?forward=',
            'href="https://example.invalid/customers/sign-up?forward=',
        ),
        "signup_duplicate_forward": signup_control.replace(
            f"?forward={NEXT_EPISODE_ID}",
            f"?forward={NEXT_EPISODE_ID}&forward={NEXT_EPISODE_ID}",
        ),
        "signup_extra_forward": signup_control.replace(
            f"?forward={NEXT_EPISODE_ID}", f"?forward={NEXT_EPISODE_ID}&extra=1"
        ),
        "signup_empty_forward": signup_control.replace(
            f"?forward={NEXT_EPISODE_ID}", "?forward="
        ),
        "signup_malformed_forward": signup_control.replace(
            NEXT_EPISODE_ID, "g" + NEXT_EPISODE_ID[1:]
        ),
        "signup_wrong_id": signup_control.replace(
            NEXT_EPISODE_ID, "f" * 32
        ),
        "signup_nested_forward": signup_control.replace(
            NEXT_EPISODE_ID, "https%3A%2F%2Fyanmaga.jp%2Fviewer"
        ),
        "signup_fragment": signup_control.replace(
            f"?forward={NEXT_EPISODE_ID}", f"?forward={NEXT_EPISODE_ID}#next"
        ),
        "signup_credentials": signup_control.replace(
            'href="/customers/sign-up?',
            'href="https://user@yanmaga.jp/customers/sign-up?',
        ),
        "signup_and_next": signup_control + next_control,
        "duplicate_signup": signup_control + signup_control,
        "missing": "",
    }
    if terminal_control not in controls:
        raise ValueError(f"unsupported synthetic terminal control: {terminal_control}")
    rental_title = title
    if terminal_control == "signup_wrong_title":
        rental_title = title.replace(NEXT_ORDER_LABEL, "\u5225\u306e\u8a71")
    rental_content = "" if unsafe_end else rental_title + controls[terminal_control]
    rental = f'<div id="rental" style="display:none">{rental_content}</div>'
    rental_top = "1900px" if terminal_geometry == "offscreen" else "20px"
    obstruction_css = (
        "#recommend{position:absolute!important;left:20px!important;top:20px!important;"
        "width:500px!important;height:300px!important;z-index:20!important;background:#f00!important}"
        if terminal_geometry == "obstructed"
        else ""
    )
    arrow = (
        '<div id="arrow-content" class="hide"><button class="arrow-next-page"></button></div>'
        if arrow_mode != "absent"
        else ""
    )
    arrow_visible_at_end = json.dumps(arrow_mode == "visible")
    initial_page = 1 if first_page_overlay else 4
    menu_initial_display = "block" if first_page_overlay else "none"
    menu_after_roundtrip = "none" if menu_hideable else "block"
    edge_overlay = '<div id="edge-obstruction"></div>' if edge_obstruction else ""
    return f'''<!doctype html><html><head><meta charset="utf-8"><title>Test | YanmagaWeb</title>
    <style>
      html,body{{margin:0;width:100%;height:100%;overflow:hidden}}
      .pages#content{{position:absolute;top:0;left:0;width:2560px;height:1800px;overflow:hidden}}
      .body-page{{position:absolute;top:0;width:{'1265.625px' if native_capture else '1266px'};height:1800px;overflow:hidden}}
      .body-page img{{position:absolute;left:0;width:{'1267.875px' if native_capture else '1266px'};height:{'auto' if native_capture else '602px'};object-fit:fill;object-position:50% 50%}}
      .body-page img:nth-child(1){{top:0}}
      .body-page img:nth-child(2){{top:{'598.5px' if native_capture else '598px'};height:{'603px' if native_capture else '602px'}}}
      .body-page img:nth-child(3){{top:{'1197px' if native_capture else '1196px'};height:{'605.25px' if native_capture else '602px'}}}
      {'#content-p1,#content-p3,#content-p4{transform:translateX(14.375px)} #content-p2{transform:translateX(1280px)} #content-p3{padding-right:2px}' if native_capture else ''}
      {'.pt-img{position:relative;width:1265.625px;height:1800px;overflow:visible} .segment-host{position:absolute;left:0;box-sizing:border-box;width:1267.864624px;overflow:hidden} .segment-host:nth-child(1){top:0;height:603px} .segment-host:nth-child(2){top:598.5px;height:603px} .segment-host:nth-child(3){top:1197px;height:605.239624px} .segment-host img{position:absolute;left:0;top:0;width:100%;height:100%;overflow:clip;object-fit:fill;object-position:50% 50%} .segment-host::after{content:"";display:block;position:absolute;left:0;top:0;width:100%;height:100%;background-color:rgba(0,0,0,0);background-image:none;border:0;outline-style:none;box-shadow:none;text-shadow:none;filter:none;backdrop-filter:none;transform:none;mix-blend-mode:normal;isolation:auto;clip-path:none;mask-image:none;overflow:visible;padding:0;margin:0} .segment-host.pseudo-background::after{background-color:rgba(255,0,0,.2)} .segment-host.pseudo-filter::after{filter:blur(1px)} .segment-host.pseudo-backdrop_filter::after{backdrop-filter:blur(1px)} .segment-host.pseudo-shadow::after{box-shadow:0 0 2px #f00} .segment-host.pseudo-content::after{content:"x"}' if native_capture else ''}
      #arrow-content{{position:absolute;right:10px;bottom:10px;width:40px;height:40px}}
      #arrow-content.hide .arrow-next-page{{display:none}}
      .arrow-next-page{{width:40px;height:40px}}
      #rental{{position:absolute;top:{rental_top};left:20px;width:500px;height:300px;background:#eee}}
      #menu{{position:fixed;inset:0;display:{menu_initial_display};z-index:30;background:rgba(0,0,0,.01)}}
      #menu_transparent{{position:absolute;inset:0;background:rgba(0,0,0,.01)}}
      #menu_header{{position:absolute;top:0;left:0;width:100%;height:100px;background:#ddd}}
      #menu_controller{{position:absolute;bottom:0;left:0;width:100%;height:100px;background:#ddd}}
      #edge-obstruction{{position:fixed;left:0;top:0;width:8px;height:8px;z-index:40;background:#f00}}
      #ads,#recommend{{position:absolute;width:1px;height:1px;overflow:hidden}}
      {obstruction_css}
    </style></head><body>
    <span id="counter">{initial_page}/4</span>
    {arrow}
    <div class="pages" id="content">{''.join(wrappers)}{rental}{auxiliary}</div>
    <div id="menu"><div id="menu_transparent"></div><div id="menu_header"></div><div id="menu_controller"></div></div>
    {edge_overlay}
    <script>
      let current={initial_page};
      const counter=document.querySelector('#counter');
      const pages=[...document.querySelectorAll('.body-page')];
      const rental=document.querySelector('#rental');
      const menu=document.querySelector('#menu');
      const arrow=document.querySelector('#arrow-content');
      const initialOverlay={json.dumps(first_page_overlay)};
      const menuHideable={json.dumps(menu_hideable)};
      let leftFromFirst=false;
      const delayedEnd={json.dumps(delayed_end)};
      const arrowVisibleAtEnd={arrow_visible_at_end};
      const nativeCapture={json.dumps(native_capture)};
      const nativeTransparent={json.dumps(native_transparent)};
      const nativeAmbiguous={json.dumps(native_ambiguous)};
      function show(value){{
        const previous=current;
        current=value; counter.textContent=`${{value}}/4`;
        pages.forEach(node=>node.style.display='none');
        if(value===1) document.querySelector('#content-p1').style.display='block';
        if(value===2){{document.querySelector('#content-p2').style.display='block';document.querySelector('#content-p3').style.display='block';}}
        if(value===4) document.querySelector('#content-p4').style.display='block';
        rental.style.display=value===4?'block':'none';
        if(value===4 && delayedEnd){{
          rental.innerHTML='';
          setTimeout(()=>{{rental.innerHTML={json.dumps(title + controls[terminal_control])}; }},250);
        }}
        if(arrow) arrow.className=value===4?(arrowVisibleAtEnd?'':'hide'):'';
        if(initialOverlay && previous===1 && value===2) leftFromFirst=true;
        if(initialOverlay && leftFromFirst && previous===2 && value===1 && menuHideable)
          menu.style.display='{menu_after_roundtrip}';
      }}
      document.addEventListener('keydown', event=>{{
        if(event.key==='ArrowRight') show(current===4?2:1);
        if(event.key==='ArrowLeft') show(current===1?2:4);
      }});
      if(nativeCapture){{
        window.__yanmagaTestOriginals={{
          canvas:window.__yanmagaNativeCaptureV1.originalCanvasDescriptor.value,
          blob:window.__yanmagaNativeCaptureV1.originalBlobDescriptor.value,
          url:window.__yanmagaNativeCaptureV1.originalUrlDescriptor.value
        }};
        const generated=[];
        for(const wrapper of pages){{
          const page=Number(wrapper.id.replace('content-p',''));
          [...wrapper.querySelectorAll('img')].forEach((image,segment)=>{{
            const canvas=document.createElement('canvas');
            canvas.width=1127; canvas.height=segment===2?538:536;
            const context=canvas.getContext('2d');
            const duplicate=nativeAmbiguous && page===1 && segment===1;
            const sourceSegment=duplicate?0:segment;
            const red=40+page*31+sourceSegment*17;
            const green=35+page*19+sourceSegment*29;
            const blue=45+page*23+sourceSegment*13;
            context.fillStyle=nativeTransparent && page===1 && segment===0
              ? `rgba(${{red}},${{green}},${{blue}},0.5)`
              : `rgb(${{red}},${{green}},${{blue}})`;
            context.fillRect(0,0,canvas.width,canvas.height);
            const data=canvas.toDataURL('image/jpeg',0.9);
            generated.push({{image,data}});
          }});
        }}
        const createBlobUrl=({{image,data}})=>{{
          const bytes=Uint8Array.from(atob(data.split(',')[1]),char=>char.charCodeAt(0));
          image.src=URL.createObjectURL(new Blob([bytes],{{type:'image/jpeg'}}));
        }};
        generated.forEach(createBlobUrl);
      }}
      show({initial_page});
    </script></body></html>'''


async def _set_routes(
    page,
    monkeypatch,
    *,
    access_mode: str = "free",
    missing_half: bool = False,
    thin_segment: bool = False,
    oversized_last_segment: bool = False,
    unknown_aux: bool = False,
    unsafe_end: bool = False,
    delayed_end: bool = False,
    access_gate: bool = False,
    terminal_geometry: str = "valid",
    arrow_mode: str = "hidden",
    first_page_overlay: bool = False,
    menu_hideable: bool = True,
    edge_obstruction: bool = False,
    adjacent_overlap: bool = False,
    terminal_control: str = "valid_next",
    native_capture: bool = False,
    native_style_unsupported: bool = False,
    native_layer_unsupported: bool = False,
    native_transparent: bool = False,
    native_ambiguous: bool = False,
    native_host_pseudo_issue: str | None = None,
    native_wrapper_transform: str | None = None,
    wrong_route: bool = False,
) -> list[str]:
    requested: list[str] = []

    async def fake_records(_self, _page, target, mode):
        assert target.url == WORK_URL
        assert mode == "full"
        _self.last_snapshot = YanmagaListingSnapshot(
            title="テスト作品",
            anonymous=True,
            rows=(
                YanmagaListingRow(
                    episode_id=EPISODE_ID,
                    title="第1話",
                    url=SOURCE_URL,
                    free_marker=access_mode == "free",
                    red_marker_present=access_mode == "free",
                    known_restricted=access_mode == "known_restricted",
                ),
                YanmagaListingRow(
                    episode_id=NEXT_EPISODE_ID,
                    title=NEXT_ORDER_LABEL,
                    url=f"{WORK_URL}/{NEXT_EPISODE_ID}",
                    free_marker=True,
                    red_marker_present=True,
                    known_restricted=False,
                ),
            ),
            continuation=None,
        )
        yield DiscoveredRecord(
            item=DiscoveredItem(canonical_title="テスト作品", order_label="第1話"),
            source=DiscoveredSource(
                external_id=f"{SLUG}:{EPISODE_ID}",
                url=SOURCE_URL,
                access_mode="unknown" if access_mode == "known_restricted" else access_mode,
                available=True,
            ),
        )
        yield DiscoveredRecord(
            item=DiscoveredItem(
                canonical_title="\u30c6\u30b9\u30c8\u4f5c\u54c1",
                order_label=NEXT_ORDER_LABEL,
            ),
            source=DiscoveredSource(
                external_id=f"{SLUG}:{NEXT_EPISODE_ID}",
                url=f"{WORK_URL}/{NEXT_EPISODE_ID}",
                access_mode="free",
                available=True,
            ),
        )

    monkeypatch.setattr(YanmagaDiscoveryAdapter, "iter_records", fake_records)
    wrong_viewer_url = f"https://yanmaga.jp/viewer/comics/別作品/{EPISODE_ID}"

    async def route_handler(route):
        url = route.request.url
        requested.append(url)
        path = unquote(urlsplit(url).path)
        if path == unquote(urlsplit(WORK_URL).path):
            await route.fulfill(status=200, content_type="text/html", body="<title>Work</title>")
        elif path in {
            unquote(urlsplit(VIEWER_URL).path),
            unquote(urlsplit(wrong_viewer_url).path),
        }:
            await route.fulfill(
                status=200,
                content_type="text/html",
                body=_viewer_html(
                    missing_half=missing_half,
                    thin_segment=thin_segment,
                    oversized_last_segment=oversized_last_segment,
                    unknown_aux=unknown_aux,
                    unsafe_end=unsafe_end,
                    delayed_end=delayed_end,
                    access_gate=access_gate,
                    terminal_geometry=terminal_geometry,
                    arrow_mode=arrow_mode,
                    first_page_overlay=first_page_overlay,
                    menu_hideable=menu_hideable,
                    edge_obstruction=edge_obstruction,
                    adjacent_overlap=adjacent_overlap,
                    terminal_control=terminal_control,
                    native_capture=native_capture,
                    native_style_unsupported=native_style_unsupported,
                    native_layer_unsupported=native_layer_unsupported,
                    native_transparent=native_transparent,
                    native_ambiguous=native_ambiguous,
                    native_host_pseudo_issue=native_host_pseudo_issue,
                    native_wrapper_transform=native_wrapper_transform,
                ),
            )
        else:
            await route.fulfill(status=404, body="not found")

    await page.route("https://yanmaga.jp/**", route_handler)
    original_goto = page.goto

    async def goto_final_viewer_for_public_episode(url, *args, **kwargs):
        if url == SOURCE_URL:
            requested.append(url)
            destination = wrong_viewer_url if wrong_route else VIEWER_NAVIGATION_URL
            return await original_goto(destination, *args, **kwargs)
        return await original_goto(url, *args, **kwargs)

    monkeypatch.setattr(page, "goto", goto_final_viewer_for_public_episode)
    return requested


def _config(tmp_path, *, source_url: str = SOURCE_URL) -> RunConfig:
    return RunConfig(
        site="yanmaga",
        source_url=source_url,
        output_dir=tmp_path / "isolated-output",
        diagnostics_dir=tmp_path / "isolated-output" / "diagnostics",
        max_pages=8,
        max_same_content=2,
        retry_count=1,
        navigation_timeout_ms=2_000,
        page_change_timeout_ms=1_000,
        page_turn_delay_ms=0,
        access_strategy="direct",
    )


def _seed_batch_candidate(tmp_path):
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(
        WorkInput(work_key="yanmaga-usagi", title="テスト作品")
    )
    item = catalog.create_item(
        ItemInput(kind="episode", order_label="第1話"), work_id=work.id
    )
    source = catalog.create_source(
        SourceInput(
            site="yanmaga",
            external_id=f"{SLUG}:{EPISODE_ID}",
            discovery_key="yanmaga-isolated-fixture",
            access_mode="free",
            available=True,
            free_until=None,
            display_position=3,
        ),
        item_id=item.id,
    )
    target = catalog.create_source_target(
        SourceTargetInput(backend="web", locator=SOURCE_URL), source_id=source.id
    )
    policies = SitePolicyRegistry()
    policies.register("yanmaga", YanmagaSitePolicy)
    adapters = AdapterRegistry()
    adapters.register("yanmaga", YanmagaAdapter)
    plan = BatchPlanner(catalog, policies).plan(site="yanmaga", now=NOW)
    assert len(plan.candidates) == 1
    return catalog, policies, adapters, plan.candidates[0], item, source, target


async def test_yanmaga_runner_rewinds_captures_spread_and_stops_at_verified_end(
    browser_page, tmp_path, monkeypatch
) -> None:
    await _set_routes(browser_page, monkeypatch)
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 500)

    result = await CrawlerRunner(_config(tmp_path)).run(browser_page, YanmagaAdapter())

    assert result.stop_state is PageState.END
    assert len(result.pages) == 4
    assert [capture.identity.page_id for capture in result.pages] == [
        "content-p1",
        "content-p2|content-p3",
        "content-p2|content-p3",
        "content-p4",
    ]
    assert [capture.identity.source_id for capture in result.pages] == [
        f"{SLUG}:{EPISODE_ID}"
    ] * 4
    assert all(capture.mime_type == "image/png" for capture in result.pages)
    assert all(capture.width >= 1127 and capture.height == 1800 for capture in result.pages)
    assert [capture.metadata.get("part") for capture in result.pages] == [None, 1, 2, None]
    assert [capture.metadata.get("parts") for capture in result.pages] == [None, 2, 2, None]
    assert browser_page.url == VIEWER_NAVIGATION_URL
    assert (tmp_path / "isolated-output" / "page-0004.png").is_file()


@pytest.mark.parametrize("native_wrapper_transform", [None, "translateX(24px)"])
async def test_yanmaga_captures_exact_pre_jpeg_page_pixels_as_lossless_webp(
    browser_page, tmp_path, monkeypatch, native_wrapper_transform
) -> None:
    await _set_routes(
        browser_page,
        monkeypatch,
        native_capture=True,
        native_wrapper_transform=native_wrapper_transform,
    )
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 500)
    result = await CrawlerRunner(_config(tmp_path)).run(
        browser_page, YanmagaAdapter()
    )

    assert result.stop_state is PageState.END
    assert len(result.pages) == 4
    assert all(
        (capture.mime_type, capture.file_extension, capture.width, capture.height)
        == ("image/webp", ".webp", 1125, 1600)
        for capture in result.pages
    )
    assert all(
        capture.metadata["capture_method"] == "native_pre_jpeg_lossless_webp"
        and capture.metadata["source_native_pixels_used"] is True
        for capture in result.pages
    )
    pseudo = await browser_page.evaluate(
        """() => {
          const host=document.querySelector('#content-p1 .pt-img > .segment-host');
          const style=getComputedStyle(host,'::after');
          return {content:style.content,background:style.backgroundColor,
            image:style.backgroundImage,outline:style.outlineStyle,
            outlineWidth:style.outlineWidth,boxShadow:style.boxShadow,
            filter:style.filter,backdrop:style.backdropFilter};
        }"""
    )
    assert pseudo == {
        "content": '""',
        "background": "rgba(0, 0, 0, 0)",
        "image": "none",
        "outline": "none",
        "outlineWidth": pseudo["outlineWidth"],
        "boxShadow": "none",
        "filter": "none",
        "backdrop": "none",
    }
    assert pseudo["outlineWidth"] not in {"0px", "0px 0px 0px 0px"}
    with Image.open(tmp_path / "isolated-output" / "page-0001.webp") as image:
        image.load()
        assert image.format == "WEBP"
        rgba = image.convert("RGBA")
        assert rgba.getpixel((10, 100)) == (71, 54, 68, 255)
        assert rgba.getpixel((10, 532)) == (88, 83, 81, 255)
        assert rgba.getpixel((10, 1064)) == (105, 112, 94, 255)
        assert rgba.getpixel((1124, 1599)) == (105, 112, 94, 255)
    assert await browser_page.evaluate(
        """() => !window.__yanmagaNativeCaptureV1 &&
          HTMLCanvasElement.prototype.toDataURL===window.__yanmagaTestOriginals.canvas &&
          Blob===window.__yanmagaTestOriginals.blob &&
          URL.createObjectURL===window.__yanmagaTestOriginals.url"""
    )


async def test_yanmaga_native_observer_is_top_frame_viewer_route_only(
    browser_page, monkeypatch
) -> None:
    await _set_routes(browser_page, monkeypatch, native_capture=True)
    await install_yanmaga_native_observer(browser_page)

    await browser_page.goto(WORK_URL, wait_until="domcontentloaded")
    assert await browser_page.evaluate(
        """() => !window.__yanmagaNativeCaptureV1 &&
          !window.__yanmagaNativeCaptureArmV1"""
    )

    await browser_page.goto(VIEWER_NAVIGATION_URL, wait_until="domcontentloaded")
    await browser_page.wait_for_function(
        "window.__yanmagaNativeCaptureV1?.active === true"
    )
    await browser_page.evaluate(
        """() => {
          const frame=document.createElement('iframe');
          frame.id='native-observer-frame';
          frame.srcdoc='<html><body>child</body></html>';
          document.body.append(frame);
        }"""
    )
    frame = next(item for item in browser_page.frames if item.parent_frame is not None)
    assert await frame.evaluate("typeof window.__yanmagaNativeCaptureV1 === 'undefined'")
    assert await browser_page.evaluate("window.__yanmagaNativeCaptureV1.active === true")


async def test_yanmaga_observes_preloads_after_page_capture_returns(
    browser_page, tmp_path, monkeypatch
) -> None:
    await _set_routes(browser_page, monkeypatch, native_capture=True)
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 500)
    adapter = YanmagaAdapter()
    capture = adapter.capture_page
    first_capture = True
    hook_state: dict[str, bool] = {}
    encoded_budget_observations: list[tuple[int, int]] = []

    release_page = adapter_module.release_yanmaga_native_page

    async def release_and_check_encoded_budget(page, page_id):
        before = await page.evaluate(
            "window.__yanmagaNativeCaptureV1?.storedEncodedBytes ?? -1"
        )
        await release_page(page, page_id)
        after = await page.evaluate(
            "window.__yanmagaNativeCaptureV1?.storedEncodedBytes ?? -1"
        )
        encoded_budget_observations.append((before, after))

    monkeypatch.setattr(
        adapter_module, "release_yanmaga_native_page", release_and_check_encoded_budget
    )

    async def capture_then_generate_later_page(page):
        nonlocal first_capture
        result = await capture(page)
        if first_capture:
            first_capture = False
            hook_state.update(
                await page.evaluate(
                    """() => {
                      const state=window.__yanmagaNativeCaptureV1;
                      const active=!!state && state.active;
                      [...document.querySelectorAll('#content-p4 img')].forEach((image,index)=>{
                        const canvas=document.createElement('canvas');
                        canvas.width=1127; canvas.height=index===2?538:536;
                        const context=canvas.getContext('2d');
                        context.fillStyle=['#e10221','#31e243','#4254e6'][index];
                        context.fillRect(0,0,canvas.width,canvas.height);
                        const data=canvas.toDataURL('image/jpeg',0.9);
                        const bytes=Uint8Array.from(atob(data.split(',')[1]),char=>char.charCodeAt(0));
                        image.src=URL.createObjectURL(new Blob([bytes],{type:'image/jpeg'}));
                      });
                      return {activeBefore:active,activeAfter:!!state && state.active};
                    }"""
                )
            )
        return result

    monkeypatch.setattr(adapter, "capture_page", capture_then_generate_later_page)
    result = await CrawlerRunner(_config(tmp_path)).run(browser_page, adapter)

    assert hook_state == {"activeBefore": True, "activeAfter": True}
    assert encoded_budget_observations
    assert all(before == after and before >= 0 for before, after in encoded_budget_observations)
    assert result.stop_state is PageState.END
    assert [capture.mime_type for capture in result.pages] == ["image/webp"] * 4


async def test_yanmaga_retains_eager_60_segment_preload_before_first_capture(
    browser_page, tmp_path, monkeypatch
) -> None:
    await _set_routes(browser_page, monkeypatch, native_capture=True)
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 500)
    adapter = YanmagaAdapter()
    capture = adapter.capture_page
    observations: dict[str, object] = {}

    async def capture_after_eager_preload(page):
        if "before" not in observations:
            await page.wait_for_function(
                "window.__yanmagaNativeCaptureV1?.inFlight === 0", timeout=2_000
            )
            observations["generated"] = await page.evaluate(
                """async () => {
                  const state=window.__yanmagaNativeCaptureV1;
                  const generated=[];
                  for(let index=0;index<48;index++){
                    const canvas=document.createElement('canvas');
                    canvas.width=1127; canvas.height=index%3===2?538:536;
                    const context=canvas.getContext('2d');
                    const red=(index*37+111)%256, green=(index*71+44)%256;
                    const blue=(index*113+7)%256;
                    context.fillStyle=`rgb(${red},${green},${blue})`;
                    context.fillRect(0,0,canvas.width,canvas.height);
                    context.fillStyle=`rgb(${(red+83)%256},${(green+127)%256},${(blue+191)%256})`;
                    context.fillRect((index*13)%1100,(index*17)%500,27,27);
                    const data=canvas.toDataURL('image/jpeg',0.9);
                    const bytes=Uint8Array.from(atob(data.split(',')[1]),char=>char.charCodeAt(0));
                    const blob=new Blob([bytes],{type:'image/jpeg'});
                    generated.push(URL.createObjectURL(blob));
                  }
                  return {generatedCount:generated.length, maxPixelBytes:state.maxPixelBytes};
                }"""
            )
            await page.wait_for_function(
                """() => {
                  const state=window.__yanmagaNativeCaptureV1;
                  return !!state && state.inFlight===0 && state.byUrl.size===60;
                }""",
                timeout=5_000,
            )
            observations["before"] = await page.evaluate(
                """() => {
                  const state=window.__yanmagaNativeCaptureV1;
                  return {overflow:state.overflow,reason:state.overflowReason,
                    total:state.totalCandidates,pending:state.candidates.length,
                    bound:state.boundCandidates.size,urls:state.byUrl.size,
                    storedPixelBytes:state.storedPixelBytes,
                    canvasCopies:state.stats.canvasCopies,
                    exactBlobBindings:state.stats.exactBlobBindings,
                    ambiguities:state.stats.ambiguities,misses:state.stats.misses,
                    readFailures:state.stats.readFailures,inFlight:state.inFlight};
                }"""
            )
        result = await capture(page)
        if "firstCapture" not in observations:
            observations["firstCapture"] = {
                "mime": result[0].mime_type if result else None,
                "dimensions": (result[0].width, result[0].height) if result else None,
            }
            observations["afterFirstCapture"] = await page.evaluate(
                """() => {
                  const state=window.__yanmagaNativeCaptureV1;
                  return {overflow:state.overflow,total:state.totalCandidates,
                    bound:state.boundCandidates.size,urls:state.byUrl.size,
                    storedPixelBytes:state.storedPixelBytes,inFlight:state.inFlight};
                }"""
            )
        return result

    monkeypatch.setattr(adapter, "capture_page", capture_after_eager_preload)
    result = await CrawlerRunner(_config(tmp_path)).run(browser_page, adapter)

    expected_page_bytes = 7_257_880
    expected_chapter_bytes = 20 * expected_page_bytes
    assert observations["generated"] == {
        "generatedCount": 48,
        "maxPixelBytes": MAX_CAPTURE_PIXELS,
    }
    before = observations["before"]
    assert before == {
        "overflow": False,
        "reason": None,
        "total": 60,
        "pending": 0,
        "bound": 60,
        "urls": 60,
        "storedPixelBytes": expected_chapter_bytes,
        "canvasCopies": 60,
        "exactBlobBindings": 60,
        "ambiguities": 0,
        "misses": 0,
        "readFailures": 0,
        "inFlight": 0,
    }
    assert expected_chapter_bytes == 145_157_600
    assert expected_chapter_bytes < MAX_CAPTURE_PIXELS
    assert observations["firstCapture"] == {
        "mime": "image/webp",
        "dimensions": (1125, 1600),
    }
    assert observations["afterFirstCapture"] == {
        "overflow": False,
        "total": 60,
        "bound": 60,
        "urls": 57,
        "storedPixelBytes": expected_chapter_bytes - expected_page_bytes,
        "inFlight": 0,
    }
    assert result.stop_state is PageState.END
    assert [capture.mime_type for capture in result.pages] == ["image/webp"] * 4


async def test_yanmaga_native_pixel_budget_exact_boundary_and_overflow(
    browser_page, monkeypatch
) -> None:
    await _set_routes(browser_page, monkeypatch, native_capture=True)
    await install_yanmaga_native_observer(browser_page)
    await browser_page.goto(VIEWER_NAVIGATION_URL, wait_until="domcontentloaded")
    await browser_page.wait_for_function(
        "window.__yanmagaNativeCaptureV1?.active === true"
    )

    observations = await browser_page.evaluate(
        """() => {
          const state=window.__yanmagaNativeCaptureV1;
          const pixels=1127*536*4;
          const makeCanvas=(color)=>{
            const canvas=document.createElement('canvas');
            canvas.width=1127; canvas.height=536;
            const context=canvas.getContext('2d');
            context.fillStyle=color; context.fillRect(0,0,canvas.width,canvas.height);
            return canvas;
          };
          state.storedPixelBytes=state.maxPixelBytes-pixels;
          const copiesBefore=state.stats.canvasCopies;
          makeCanvas('#21a3d9').toDataURL('image/jpeg',0.9);
          const accepted={maxPixelBytes:state.maxPixelBytes,
            storedPixelBytes:state.storedPixelBytes,overflow:state.overflow,
            canvasCopies:state.stats.canvasCopies-copiesBefore};
          state.storedPixelBytes=state.maxPixelBytes-pixels+1;
          makeCanvas('#db7132').toDataURL('image/jpeg',0.9);
          const rejected={storedPixelBytes:state.storedPixelBytes,
            overflow:state.overflow,reason:state.overflowReason,
            canvasCopies:state.stats.canvasCopies-copiesBefore};
          return {accepted,rejected};
        }"""
    )

    assert observations == {
        "accepted": {
            "maxPixelBytes": MAX_CAPTURE_PIXELS,
            "storedPixelBytes": MAX_CAPTURE_PIXELS,
            "overflow": False,
            "canvasCopies": 1,
        },
        "rejected": {
            "storedPixelBytes": MAX_CAPTURE_PIXELS - (1127 * 536 * 4) + 1,
            "overflow": True,
            "reason": "capture_buffer_overflow",
            "canvasCopies": 1,
        },
    }
    await dispose_yanmaga_native_observer(browser_page)


@pytest.mark.parametrize(
    ("node_selector", "style_property", "style_value"),
    [
        ("#content-p1 img", "filter", "blur(1px)"),
        ("#content-p1 img", "opacity", "0.99"),
        ("#content-p1 .pt-img > div:first-child", "filter", "blur(1px)"),
        ("#content-p1 .pt-img > div:first-child", "opacity", "0.99"),
        ("#content-p1 .pt-img", "filter", "blur(1px)"),
        ("#content-p1 .pt-img", "opacity", "0.99"),
    ],
)
async def test_yanmaga_native_proof_rejects_same_size_style_drift_during_source_wait(
    browser_page, tmp_path, monkeypatch, node_selector, style_property, style_value
) -> None:
    await _set_routes(browser_page, monkeypatch, native_capture=True)
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 500)
    capture = adapter_module.capture_yanmaga_native_webp
    armed = False

    async def capture_with_delayed_style_change(page, page_id):
        nonlocal armed
        if page_id == "content-p1" and not armed:
            armed = True
            await page.evaluate(
                """({selector,property,value}) => {
                  const node=document.querySelector(selector);
                  const state=window.__yanmagaNativeCaptureV1;
                  const source=document.querySelector('#content-p1 img').currentSrc;
                  const record=state.byUrl.get(source);
                  state.byUrl.delete(source);
                  setTimeout(()=>{
                    node.style.setProperty(property,value);
                    state.byUrl.set(source,record);
                  },40);
                }""",
                {
                    "selector": node_selector,
                    "property": style_property,
                    "value": style_value,
                },
            )
        return await capture(page, page_id)

    monkeypatch.setattr(
        adapter_module, "capture_yanmaga_native_webp", capture_with_delayed_style_change
    )
    result = await CrawlerRunner(_config(tmp_path)).run(
        browser_page, YanmagaAdapter()
    )

    assert result.stop_state is PageState.END
    assert armed
    assert [capture.mime_type for capture in result.pages] == [
        "image/png",
        "image/webp",
        "image/webp",
        "image/webp",
    ]
    assert result.pages[0].metadata["capture_group"]["fallback_reason"] == (
        "native_proof_changed_while_waiting"
    )


async def test_yanmaga_native_group_revalidation_rejects_prior_page_style_drift(
    browser_page, tmp_path, monkeypatch
) -> None:
    await _set_routes(browser_page, monkeypatch, native_capture=True)
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 500)
    capture = adapter_module.capture_yanmaga_native_webp
    changed = False

    async def capture_then_change_prior_spread_page(page, page_id):
        nonlocal changed
        outcome = await capture(page, page_id)
        if page_id == "content-p3" and not changed and outcome.capture is not None:
            changed = True
            await page.locator("#content-p2 img").first.evaluate(
                "image => { image.style.opacity='0.99'; }"
            )
        return outcome

    monkeypatch.setattr(
        adapter_module, "capture_yanmaga_native_webp", capture_then_change_prior_spread_page
    )
    result = await CrawlerRunner(_config(tmp_path)).run(
        browser_page, YanmagaAdapter()
    )

    assert result.stop_state is PageState.END
    assert changed
    assert [capture.mime_type for capture in result.pages] == [
        "image/webp",
        "image/png",
        "image/png",
        "image/webp",
    ]
    assert result.pages[1].metadata["capture_group"]["fallback_reason"] == (
        "native_capture_group_proof_changed"
    )
    assert result.pages[2].metadata["capture_group"]["fallback_reason"] == (
        "native_capture_group_proof_changed"
    )


@pytest.mark.parametrize(
    ("options", "expected_reasons", "expected_types"),
    [
        (
            {"native_style_unsupported": True},
            ("unsupported_compositing_style", "unsupported_compositing_style"),
            ("image/png", "image/png", "image/png", "image/webp"),
        ),
        (
            {"native_transparent": True},
            ("segment_not_opaque",),
            ("image/png", "image/webp", "image/webp", "image/webp"),
        ),
        (
            {"native_ambiguous": True},
            ("segment_source_not_exactly_bound",),
            ("image/png", "image/webp", "image/webp", "image/webp"),
        ),
        (
            {"native_layer_unsupported": True},
            ("unsupported_painter_order",),
            ("image/png", "image/webp", "image/webp", "image/webp"),
        ),
        *[
            (
                {"native_host_pseudo_issue": issue},
                ("unsupported_compositing_style",),
                ("image/png", "image/webp", "image/webp", "image/webp"),
            )
            for issue in ("background", "filter", "backdrop_filter", "shadow", "content")
        ],
    ],
)
async def test_yanmaga_native_capture_falls_back_for_unproven_segment_groups(
    browser_page, tmp_path, monkeypatch, options, expected_reasons, expected_types
) -> None:
    await _set_routes(browser_page, monkeypatch, native_capture=True, **options)
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 500)

    result = await CrawlerRunner(_config(tmp_path)).run(
        browser_page, YanmagaAdapter()
    )

    assert result.stop_state is PageState.END
    assert len(result.pages) == 4
    assert tuple(capture.mime_type for capture in result.pages) == expected_types
    assert result.pages[0].metadata["capture_group"]["fallback_reason"] == expected_reasons[0]
    assert result.pages[0].metadata["capture_method"] == "rendered_dom_body_wrapper_png"
    assert result.pages[0].metadata["source_native_pixels_used"] is False
    if len(expected_reasons) == 2:
        assert result.pages[1].metadata["capture_group"]["fallback_reason"] == expected_reasons[1]
        assert result.pages[2].metadata["capture_group"]["fallback_reason"] == expected_reasons[1]
    if expected_types[-1] == "image/webp":
        assert result.pages[-1].metadata["capture_method"] == "native_pre_jpeg_lossless_webp"


@pytest.mark.parametrize(
    "native_wrapper_transform",
    ["translateY(1px)", "scale(1.01)", "skewX(1deg)", "rotateY(1deg)"],
)
async def test_yanmaga_native_page_profile_rejects_non_x_wrapper_transforms(
    browser_page, monkeypatch, native_wrapper_transform
) -> None:
    await _set_routes(
        browser_page,
        monkeypatch,
        native_capture=True,
        native_wrapper_transform=native_wrapper_transform,
    )
    await install_yanmaga_native_observer(browser_page)
    try:
        await browser_page.goto(VIEWER_NAVIGATION_URL, wait_until="domcontentloaded")
        await browser_page.wait_for_function(
            "window.__yanmagaNativeCaptureV1?.active === true"
        )
        await browser_page.wait_for_function(
            """() => [...document.querySelectorAll('#content-p1 img')].length === 3 &&
              [...document.querySelectorAll('#content-p1 img')].every(
                image => image.complete && image.naturalWidth === 1127)"""
        )
        await browser_page.keyboard.press("ArrowRight")
        await browser_page.keyboard.press("ArrowRight")
        await browser_page.wait_for_function(
            "getComputedStyle(document.querySelector('#content-p1')).display === 'block'"
        )

        outcome = await capture_yanmaga_native_webp(browser_page, "content-p1")

        assert outcome.capture is None
        assert outcome.reason == "unsupported_compositing_style"
    finally:
        await dispose_yanmaga_native_observer(browser_page)


async def test_yanmaga_accepts_verified_two_pixel_overlap_between_spread_pages(
    browser_page, tmp_path, monkeypatch
) -> None:
    await _set_routes(browser_page, monkeypatch, adjacent_overlap=True)
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 500)
    original_capture = adapter_module.capture_locator
    overlap_proofs = {}

    async def capture_with_overlap_proof(target):
        page_id = await target.get_attribute("id")
        proof = await browser_page.evaluate(
            """(id) => {
              const node=document.getElementById(id), sibling=document.querySelector('#content-p3');
              const box=node.getBoundingClientRect(), other=sibling.getBoundingClientRect();
              const hitPage=x=>{
                const hit=document.elementFromPoint(x,box.y+box.height/2);
                let current=hit;
                while(current && !/^content-p[1-9][0-9]*$/.test(current.id)) current=current.parentElement;
                return current?.id||null;
              };
              return {overlap:Math.max(0,box.x+box.width-other.x),
                onePxRight:hitPage(box.x+box.width-1),fourPxRight:hitPage(box.x+box.width-4)};
            }""",
            page_id,
        )
        if page_id == "content-p2":
            overlap_proofs[page_id] = proof
        return await original_capture(target)

    monkeypatch.setattr(adapter_module, "capture_locator", capture_with_overlap_proof)

    result = await CrawlerRunner(_config(tmp_path)).run(browser_page, YanmagaAdapter())

    assert result.stop_state is PageState.END
    assert len(result.pages) == 4
    assert overlap_proofs["content-p2"] == {
        "overlap": 2,
        "onePxRight": "content-p3",
        "fourPxRight": "content-p2",
    }
    assert all(
        (tmp_path / "isolated-output" / f"page-{index:04d}.png").is_file()
        for index in range(1, 5)
    )


async def test_yanmaga_hides_fresh_reader_menu_with_normal_roundtrip_before_capture(
    browser_page, tmp_path, monkeypatch
) -> None:
    await _set_routes(browser_page, monkeypatch, first_page_overlay=True)
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 500)
    original_capture = adapter_module.capture_locator
    capture_proofs = []

    async def capture_after_ui_proof(target):
        proof = await browser_page.evaluate(
            """(id) => {
              const node=document.getElementById(id), menu=document.querySelector('#menu');
              const box=node.getBoundingClientRect(), insetX=Math.min(4,box.width/4),
                insetY=Math.min(4,box.height/4);
              const points=[[box.x+insetX,box.y+insetY],[box.x+box.width/2,box.y+insetY],
                [box.x+box.width-insetX,box.y+insetY],[box.x+insetX,box.y+box.height/2],
                [box.x+box.width-insetX,box.y+box.height/2],[box.x+insetX,box.y+box.height-insetY],
                [box.x+box.width/2,box.y+box.height-insetY],
                [box.x+box.width-insetX,box.y+box.height-insetY]];
              return {id,hidden:menu && getComputedStyle(menu).display==='none' &&
                menu.getBoundingClientRect().width===0 && menu.getBoundingClientRect().height===0,
                perimeter:points.every(([x,y])=>{const hit=document.elementFromPoint(x,y);
                  return hit===node || node.contains(hit);})};
            }""",
            await target.get_attribute("id"),
        )
        capture_proofs.append(proof)
        return await original_capture(target)

    monkeypatch.setattr(adapter_module, "capture_locator", capture_after_ui_proof)
    result = await CrawlerRunner(_config(tmp_path)).run(browser_page, YanmagaAdapter())

    assert result.stop_state is PageState.END
    assert [proof["id"] for proof in capture_proofs] == [
        "content-p1",
        "content-p2",
        "content-p3",
        "content-p4",
    ]
    assert all(proof["hidden"] and proof["perimeter"] for proof in capture_proofs)


@pytest.mark.parametrize(
    ("terminal_control", "accepted"),
    [
        ("signup", True),
        ("signup_wrong_label", False),
        ("signup_wrong_path", False),
        ("signup_foreign", False),
        ("signup_credentials", False),
        ("signup_duplicate_forward", False),
        ("signup_extra_forward", False),
        ("signup_empty_forward", False),
        ("signup_malformed_forward", False),
        ("signup_wrong_id", False),
        ("signup_wrong_title", False),
        ("signup_nested_forward", False),
        ("signup_fragment", False),
        ("signup_and_next", False),
        ("duplicate_signup", False),
        ("missing", False),
    ],
)
async def test_yanmaga_terminal_signup_boundary_is_exact_and_never_activated(
    browser_page, tmp_path, monkeypatch, terminal_control, accepted
) -> None:
    requested = await _set_routes(
        browser_page, monkeypatch, terminal_control=terminal_control
    )
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 300)

    if accepted:
        result = await CrawlerRunner(_config(tmp_path)).run(browser_page, YanmagaAdapter())
        assert result.stop_state is PageState.END
        assert len(result.pages) == 4
    else:
        with pytest.raises(UnknownPageStateError):
            await CrawlerRunner(_config(tmp_path)).run(browser_page, YanmagaAdapter())
    assert browser_page.url == VIEWER_NAVIGATION_URL
    assert not any(urlsplit(url).path == "/customers/sign-up" for url in requested)


@pytest.mark.parametrize(
    ("first_page_overlay", "menu_hideable", "edge_obstruction", "expected_error"),
    [
        (True, False, False, UnknownPageStateError),
        (False, True, True, PageChangeTimeoutError),
    ],
)
async def test_yanmaga_refuses_uncleared_menu_or_edge_overlay_before_saving_page(
    browser_page,
    tmp_path,
    monkeypatch,
    first_page_overlay,
    menu_hideable,
    edge_obstruction,
    expected_error,
) -> None:
    await _set_routes(
        browser_page,
        monkeypatch,
        first_page_overlay=first_page_overlay,
        menu_hideable=menu_hideable,
        edge_obstruction=edge_obstruction,
    )
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 300)

    with pytest.raises(expected_error):
        await CrawlerRunner(_config(tmp_path)).run(browser_page, YanmagaAdapter())

    assert not list((tmp_path / "isolated-output").glob("page-*.png"))


async def test_yanmaga_rejects_same_geometry_source_replacement_during_capture(
    browser_page, tmp_path, monkeypatch
) -> None:
    await _set_routes(browser_page, monkeypatch)
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 500)
    capture = adapter_module.capture_locator
    changed = False

    async def capture_then_replace_source(target):
        nonlocal changed
        result = await capture(target)
        if not changed:
            changed = True
            await browser_page.locator("#content-p1 img").first.evaluate(
                "(image, source) => { image.src = source; }",
                _segment_data("#f000ff", 1),
            )
        return result

    monkeypatch.setattr(adapter_module, "capture_locator", capture_then_replace_source)
    with pytest.raises(
        UnknownPageStateError,
        match="reader changed while page pixels were captured",
    ):
        await CrawlerRunner(_config(tmp_path)).run(browser_page, YanmagaAdapter())

    assert changed
    assert not list((tmp_path / "isolated-output").glob("page-*.png"))


async def test_yanmaga_native_capture_rejects_same_geometry_source_replacement(
    browser_page, tmp_path, monkeypatch
) -> None:
    await _set_routes(browser_page, monkeypatch, native_capture=True)
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 500)
    capture = adapter_module.capture_yanmaga_native_webp
    changed = False

    async def capture_then_replace_source(page, page_id):
        nonlocal changed
        outcome = await capture(page, page_id)
        if not changed and page_id == "content-p1" and outcome.capture is not None:
            changed = True
            await page.locator("#content-p1 img").first.evaluate(
                "(image, source) => { image.src = source; }",
                _segment_data("#f000ff", 1),
            )
        return outcome

    monkeypatch.setattr(adapter_module, "capture_yanmaga_native_webp", capture_then_replace_source)
    with pytest.raises(
        UnknownPageStateError,
        match="reader changed while page pixels were captured",
    ):
        await CrawlerRunner(_config(tmp_path)).run(browser_page, YanmagaAdapter())

    assert changed
    assert not list((tmp_path / "isolated-output").glob("page-*.webp"))
    assert not list((tmp_path / "isolated-output").glob("page-*.png"))


@pytest.mark.parametrize("arrow_mode", ["absent", "visible"])
async def test_yanmaga_waits_for_delayed_positive_terminal_controls_without_arrow_gate(
    browser_page, tmp_path, monkeypatch, arrow_mode
) -> None:
    await _set_routes(
        browser_page, monkeypatch, delayed_end=True, arrow_mode=arrow_mode
    )
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 1_000)

    result = await CrawlerRunner(_config(tmp_path)).run(browser_page, YanmagaAdapter())

    assert result.stop_state is PageState.END
    assert len(result.pages) == 4
    assert browser_page.url == VIEWER_NAVIGATION_URL


@pytest.mark.parametrize(
    ("scenario", "expected_error"),
    [
        ("unknown_access", UnknownPageStateError),
        ("known_restricted", AccessResourceUnavailableError),
        ("wrong_route", UnknownPageStateError),
        ("missing_half", PageChangeTimeoutError),
        ("thin_segment", PageChangeTimeoutError),
        ("oversized_last_segment", PageChangeTimeoutError),
        ("unknown_aux", PageChangeTimeoutError),
        ("access_gate", PageChangeTimeoutError),
        ("unsafe_end", UnknownPageStateError),
        ("offscreen_rental", UnknownPageStateError),
        ("obstructed_rental", UnknownPageStateError),
    ],
)
async def test_yanmaga_runner_fails_closed_on_unproven_reader_state(
    browser_page, tmp_path, monkeypatch, scenario, expected_error
) -> None:
    options = {
        "access_mode": (
            "unknown" if scenario == "unknown_access" else
            "known_restricted" if scenario == "known_restricted" else "free"
        ),
        "wrong_route": scenario == "wrong_route",
        "missing_half": scenario == "missing_half",
        "thin_segment": scenario == "thin_segment",
        "oversized_last_segment": scenario == "oversized_last_segment",
        "unknown_aux": scenario == "unknown_aux",
        "unsafe_end": scenario == "unsafe_end",
        "native_capture": scenario in {"wrong_route", "unsafe_end"},
        "access_gate": scenario == "access_gate",
        "terminal_geometry": (
            "offscreen" if scenario == "offscreen_rental" else
            "obstructed" if scenario == "obstructed_rental" else "valid"
        ),
    }
    requested = await _set_routes(browser_page, monkeypatch, **options)
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 300)

    adapter = YanmagaAdapter()
    with pytest.raises(expected_error):
        await CrawlerRunner(_config(tmp_path)).run(browser_page, adapter)

    if scenario in {"wrong_route", "unsafe_end"}:
        assert await browser_page.evaluate(
            """() => !window.__yanmagaNativeCaptureV1 &&
              HTMLCanvasElement.prototype.toDataURL===window.__yanmagaTestOriginals.canvas &&
              Blob===window.__yanmagaTestOriginals.blob &&
              URL.createObjectURL===window.__yanmagaTestOriginals.url"""
        )
        assert adapter._native_observer_installed is False

    if scenario in {"unknown_access", "known_restricted"}:
        assert not any(urlsplit(url).path.endswith(EPISODE_ID) for url in requested)
        assert browser_page.url == WORK_URL


async def test_yanmaga_batch_runs_direct_to_zip_and_completes_catalog_item(
    browser_page, tmp_path, monkeypatch
) -> None:
    requested = await _set_routes(browser_page, monkeypatch)
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 500)
    catalog, policies, adapters, candidate, item, source, target = _seed_batch_candidate(
        tmp_path
    )
    assert candidate.access_strategy == "direct"
    assert candidate.access_mode == "free"
    assert candidate.artifact_prefix == "003"
    assert candidate.quota_resource is None and candidate.consumes_quota is False
    assert target.locator == SOURCE_URL

    executor = BatchExecutor(
        catalog,
        policies,
        adapters,
        runtime_settings=SiteRuntimeSettings(page_turn_delay_ms=0),
    )
    result = await executor.execute_candidate(
        browser_page,
        candidate,
        output_root=tmp_path / "batch-output",
        library_dir=tmp_path / "library",
        max_pages=8,
        now=NOW,
    )

    updated_item = catalog.get_item(item.id)
    run = catalog.get_crawl_run(result.crawl_run_id)
    artifacts = catalog.list_artifacts(item_id=item.id)
    assert result.stop_reason == "end" and result.page_count == 4
    assert updated_item.status == "completed" and updated_item.completed_at is not None
    assert run.status == "succeeded" and run.stop_reason == "end"
    assert run.locator_snapshot == SOURCE_URL
    assert len(artifacts) == 1
    assert (artifacts[0].format, artifacts[0].state) == ("zip", "present")
    assert artifacts[0].sha256
    assert result.archive_path.is_file() and result.archive_path.name.startswith("003-")
    with zipfile.ZipFile(result.archive_path) as archive:
        names = archive.namelist()
        assert names == [f"page-{index:04d}.png" for index in range(1, 5)]
        assert archive.testzip() is None
    assert catalog.get_source(source.id).quota_started_at is None
    assert catalog.get_source(source.id).access_granted_until is None
    assert browser_page.url == VIEWER_NAVIGATION_URL
    assert any(urlsplit(url).path == urlsplit(SOURCE_URL).path for url in requested)


async def test_yanmaga_batch_skips_catalog_free_when_fresh_listing_restricts_it(
    browser_page, tmp_path, monkeypatch
) -> None:
    requested = await _set_routes(browser_page, monkeypatch, access_mode="known_restricted")
    catalog, policies, adapters, candidate, item, _source, _target = _seed_batch_candidate(
        tmp_path
    )
    executor = BatchExecutor(catalog, policies, adapters)

    with pytest.raises(AccessResourceUnavailableError):
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "batch-output",
            library_dir=tmp_path / "library",
            now=NOW,
        )

    assert catalog.get_item(item.id).status == "pending"
    assert catalog.list_artifacts(item_id=item.id) == []
    runs = catalog.list_crawl_runs(item_id=item.id)
    assert len(runs) == 1 and runs[0].status == "failed"
    assert not list((tmp_path / "library").rglob("*.zip"))
    assert not any(
        urlsplit(url).path.endswith(EPISODE_ID)
        or urlsplit(url).path.startswith("/viewer/")
        for url in requested
    )


@pytest.mark.parametrize("failure", ["invalid_end", "zip_failure"])
async def test_yanmaga_batch_failure_keeps_item_pending_without_success_artifact(
    browser_page, tmp_path, monkeypatch, failure
) -> None:
    await _set_routes(browser_page, monkeypatch, unsafe_end=failure == "invalid_end")
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 300)
    catalog, policies, adapters, candidate, item, _source, _target = _seed_batch_candidate(
        tmp_path
    )

    def fail_package(*_args, **_kwargs):
        raise OSError("synthetic ZIP packaging failure")

    executor_kwargs = {"runtime_settings": SiteRuntimeSettings(page_turn_delay_ms=0)}
    if failure == "zip_failure":
        executor_kwargs["package_function"] = fail_package
    executor = BatchExecutor(catalog, policies, adapters, **executor_kwargs)

    with pytest.raises(CandidateExecutionError):
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "batch-output",
            library_dir=tmp_path / "library",
            max_pages=8,
            now=NOW,
        )

    assert catalog.get_item(item.id).status == "pending"
    assert catalog.list_artifacts(item_id=item.id) == []
    runs = catalog.list_crawl_runs(item_id=item.id)
    assert len(runs) == 1 and runs[0].status == "failed"
    assert not list((tmp_path / "library").rglob("*.zip"))
