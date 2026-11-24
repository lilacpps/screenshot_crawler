from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import ClassVar
from urllib.parse import urlsplit

import pytest
from PIL import Image
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from screenshot_crawler.batch import BatchExecutionError, BatchExecutor, BatchPlanner
from screenshot_crawler.catalog import (
    CatalogService,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.core.access_guard import AccessGuard
from screenshot_crawler.core.errors import (
    AccessStopError,
    PageChangeTimeoutError,
    UnknownPageStateError,
    UnsupportedAccessStrategyError,
)
from screenshot_crawler.core.models import RunConfig
from screenshot_crawler.core.packaging import package_crawl_output
from screenshot_crawler.core.runner import CrawlerRunner
from screenshot_crawler.core.state import PageState
from screenshot_crawler.runtime_settings import SiteRuntimeSettings
from screenshot_crawler.site_adapters.herosweb import adapter as adapter_module
from screenshot_crawler.site_adapters.herosweb.access import herosweb_access_profile
from screenshot_crawler.site_adapters.herosweb.adapter import HeroswebAdapter
from screenshot_crawler.site_adapters.registry import AdapterRegistry
from screenshot_crawler.site_policies import SitePolicyRegistry
from screenshot_crawler.site_policies.herosweb import HeroswebSitePolicy
from screenshot_crawler.watchlist.reconcile import ScopeReconciler
from screenshot_crawler.watchlist.service import WatchlistService

pytestmark = pytest.mark.asyncio(loop_scope="module")

_PRODUCTION_MAIN_FRAME_FETCH = adapter_module._fetch_main_frame_response_without_redirect


@pytest.fixture(autouse=True)
def _use_mocked_document_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fallback_to_fixture(route):
        await route.fallback()

    monkeypatch.setattr(
        adapter_module,
        "_fetch_main_frame_response_without_redirect",
        fallback_to_fixture,
    )

BASE = "https://heros-web.com"
WORK_A = "dca88b215773f"
EPISODE_A = "4fe9831c6f540"
WORK_B = "0f023839d7bca"
EPISODE_B = "b92706d1ebe2e"
WORK_URL_A = f"{BASE}/series/{WORK_A}"
EPISODE_URL_A = f"{BASE}/episodes/{EPISODE_A}"
NOW = datetime(2026, 11, 22, 12, 0, tzinfo=JST)
_ROOT_MODES = (
    "mode-h mode-dir-rtl mode-nav-dir-rtl mode-spread mode-pc "
    "mode-has-good-page mode-skip-next-confirm mode-disable-toc "
    "mode-has-app-link mode-app-link-comimaga "
    "mode-no-toc mode-use-glimpse-bottom "
    "mode-glimpse-bottom mode-has-pr mode-has-comic-info"
)
_OPTIONAL_ROOT_FEATURE_MODES = {"mode-has-app-link", "mode-has-comic-info"}


def _episode_id(position: int, target_position: int, target_id: str) -> str:
    return target_id if position == target_position else f"{position:013x}"


def _row(position: int, *, target_position: int, target_id: str) -> str:
    episode_id = _episode_id(position, target_position, target_id)
    return f'''<div class="series-eplist-item">
      <a class="series-eplist-item-link" href="{BASE}/episodes/{episode_id}">
        <span class="series-eplist-item-h-text">Fixture episode {position}</span>
        <div class="series-eplist-item-meta"><div class="series-eplist-item-meta-date">2026/05/18</div></div>
      </a>
      <div class="series-eplist-item-access"><div>
        <span class="series-eplist-item-access-text mode-free" data-e2e="eliFreeBadge">無料</span>
      </div></div>
    </div>'''


def _listing_page(
    *,
    work_id: str,
    work_title: str,
    target_episode_id: str,
    target_position: int,
    ranges: tuple[tuple[int, int], ...],
    selected_range: int | None,
    rows: tuple[int, ...],
    target_label: str = "無料",
    authenticated: bool = True,
    delay_auth_header_ms: int = 0,
    fatal_subresource_status: int | None = None,
    ambiguous_preview_roots: bool = False,
) -> str:
    work_url = f"{BASE}/series/{work_id}"
    range_links = [f'<a class="series-sort-link mode-new" href="{work_url}/new">最新話から</a>']
    for index, (start, end) in enumerate(ranges, start=1):
        is_selected = selected_range == index
        href = work_url if is_selected else f"{work_url}/{index}"
        classes = "series-sort-link mode-current" if is_selected else "series-sort-link"
        range_links.append(f'<a class="{classes}" href="{href}">{start}-{end}</a>')
    rows_html = "".join(
        _row(position, target_position=target_position, target_id=target_episode_id)
        for position in rows
    )
    preview_mirror = (
        f'<div class="series-eplist-default">{rows_html}</div>'
        if ambiguous_preview_roots and selected_range is None
        else ""
    )
    if target_label == "今なら無料" and target_position in rows:
        rows_html = rows_html.replace(
            'class="series-eplist-item-access-text mode-free" data-e2e="eliFreeBadge">無料',
            'class="series-eplist-item-access-text mode-free" data-e2e="eliMemFreeBadge">今なら無料',
            1,
        )
    authenticated_header = (
        '<nav><a href="/auth/logout">ログアウト</a>'
        '<a class="h-main-nav-link mode-user" href="/mypage">My page</a>'
        '<a class="h-usermenu-vnav-link" href="/mypage">menu</a></nav>'
    )
    anonymous_header = (
        '<nav><a href="/auth/signin">ログイン</a>'
        '<a href="/auth/signup">無料登録</a></nav>'
    )
    user_header = (
        "<nav></nav>"
        if authenticated and delay_auth_header_ms > 0
        else authenticated_header if authenticated else anonymous_header
    )
    delayed_auth_header = (
        "setTimeout(() => { document.querySelector('header').innerHTML = "
        f"{json.dumps(authenticated_header)}; }}, {delay_auth_header_ms});"
        if authenticated and delay_auth_header_ms > 0
        else ""
    )
    return f'''<!doctype html><html><head><meta charset="utf-8">
      <link rel="canonical" href="{work_url if selected_range is None else f"{work_url}/{selected_range}"}">
      <title>{work_title}</title></head><body>
      <header>{user_header}</header><div class="series-h"><h1>{work_title}</h1></div>
      <div class="series-sort">{"".join(range_links)}</div>
      <div class="series-eplist-main"><div class="series-eplist">
        <div class="series-eplist-default">{rows_html}</div>{preview_mirror}
      </div></div>
      <script>fetch('/api/auth/session').catch(() => {{}});{delayed_auth_header}
        {'fetch("/api/preflight-stop").catch(() => {});' if fatal_subresource_status is not None else ''}</script>
      </body></html>'''


def _viewer_page(
    *,
    work_id: str,
    episode_id: str,
    episode_position: int,
    body_count: int,
    initial_seek: int | None = None,
    access_gate: bool = False,
    unknown_role: bool = False,
    omit_last: bool = False,
    draw_on_capture: bool = False,
    draw_delay_ms: int = 0,
    delay_structure_ms: int = 0,
    delay_pr_hydration_ms: int = 0,
    pr_mode_missing_forever: bool = False,
    resume_pr_loading_shape: bool = False,
    remove_root_mode: str | None = None,
    root_feature_flags: bool = True,
    stall_after_initial: bool = False,
    to_data_url_fails: bool = False,
    first_body_wrong_geometry: bool = False,
    clear_on_capture: str | None = None,
    post_url: str | None = None,
    post_on_seek: int | None = None,
    native_source: bool = False,
    native_source_profile: str = "a1440",
    nav_open_initial: bool = False,
    native_draw_before_slide: bool = False,
    native_draw_while_pr_pending: bool = False,
    native_mutate_during_materialization: bool = False,
    native_hide_nav_open_during_materialization: bool = False,
    native_add_root_mode_during_materialization: str | None = None,
    native_seek_during_materialization: bool = False,
    hide_nav_open_on_capture: bool = False,
    native_materialization_fails: bool = False,
    native_color_space: str = "srgb",
    seek_max_override: int | None = None,
) -> str:
    wrapper_count = body_count + 7
    seek_max = (
        seek_max_override
        if seek_max_override is not None
        else 2 * ((wrapper_count - 1) // 2) + 1
    )
    initial_value = initial_seek or seek_max
    wrappers: list[str] = []
    initial_wrapper_markup: list[str] = []
    for index in range(wrapper_count):
        if index == 0:
            classes = "-cv-page mode-empty mode-pr mode-top-pr"
            child = ""
        elif 1 <= index <= body_count:
            classes = "-cv-page mode-loaded mode-rendered"
            color = (index * 19) % 255
            draw_call = (
                ""
                if native_source
                else f'x.fillStyle="rgb({color},20,30)";x.fillRect(0,0,934,1329);'
            )
            if draw_delay_ms:
                draw_call = f'setTimeout(()=>{{{draw_call}}},{draw_delay_ms});'
            child = (
                f'<canvas data-slot="{index}" width="934" height="1329" '
                'style="position:absolute;left:161.5px;top:0;width:623px;height:886px"></canvas>'
                f'<script>(function(){{const c=document.currentScript.previousElementSibling;'
                f'const x=c.getContext("2d");{draw_call}}})();</script>'
            )
        elif index == body_count + 1:
            classes = "-cv-page mode-ci"
            child = ""
        elif index <= body_count + 4:
            classes = "-cv-page mode-empty mode-pr"
            child = ""
        elif index == body_count + 5:
            classes = "-cv-page mode-good"
            child = ""
        else:
            classes = "-cv-page mode-last"
            child = ""
        if unknown_role and index == body_count + 4:
            classes += " mode-unrecognized"
        if omit_last and index == body_count + 6:
            classes = "-cv-page mode-empty"
        wrapper_left = 944 - index * 946
        if index == 1 and first_body_wrong_geometry:
            wrapper_left += 10_000
        full_wrapper = (
            f'<div class="{classes}" data-index="{index}" '
            f'style="position:absolute;left:{wrapper_left}px;top:0;width:946px;height:886px">'
            f"{child}</div>"
        )
        wrappers.append(full_wrapper)
        if (delay_pr_hydration_ms or pr_mode_missing_forever) and 1 <= index <= body_count:
            if resume_pr_loading_shape:
                pending = index in {4, 5, 6}
            else:
                pending = index <= 2
            pending_classes = (
                "-cv-page mode-loading mode-req-render" if pending else "-cv-page"
            )
            initial_wrapper_markup.append(
                f'<div class="{pending_classes}" data-index="{index}" '
                f'style="position:absolute;left:{wrapper_left}px;top:0;width:946px;height:886px"></div>'
            )
        else:
            initial_wrapper_markup.append(full_wrapper)
    initial_seek_max = "1" if delay_structure_ms else str(seek_max)
    initial_seek_step = "1" if delay_structure_ms else "2"
    initial_seek_value = "1" if delay_structure_ms else str(initial_value)
    initial_wrappers = (
        ""
        if delay_structure_ms
        else "".join(initial_wrapper_markup)
    )
    loading_class = " mode-loading" if delay_structure_ms else ""
    delayed_structure_script = ""
    if delay_structure_ms:
        serialized_wrappers = json.dumps("".join(wrappers)).replace("</", "<\\/")
        delayed_structure_script = f'''setTimeout(()=>{{
          pages.innerHTML={serialized_wrappers};
          seek.max={json.dumps(str(seek_max))};seek.step="2";seek.value={json.dumps(str(seek_max))};
          const body=[...pages.children].filter(node=>node.classList.contains("mode-loaded"));
          const draw=()=>body.forEach((node,index)=>{{
            const canvas=node.querySelector("canvas");
            if(!canvas)return;
            const ctx=canvas.getContext("2d");
            ctx.fillStyle=`rgb(${((index+1)*19)%255},20,30)`;
            ctx.fillRect(0,0,934,1329);
          }});
          {f"setTimeout(draw,{draw_delay_ms});" if draw_delay_ms else "draw();"}
          root.classList.remove("mode-loading");update();
        }},{delay_structure_ms});'''
    if delay_pr_hydration_ms:
        serialized_wrappers = json.dumps("".join(wrappers)).replace("</", "<\\/")
        pending_pr_draw = (
            "drawVisibleNativeBodies();"
            if native_source and native_draw_while_pr_pending
            else ""
        )
        delayed_pr_hydration_script = f'''setTimeout(()=>{{
          pages.innerHTML={serialized_wrappers};
          {pending_pr_draw}
          root.classList.add("mode-has-pr");
          {'''const body=[...pages.children].filter(node=>node.classList.contains("mode-loaded"));
          body.forEach((node,index)=>{
            const canvas=node.querySelector("canvas");
            if(!canvas)return;
            const ctx=canvas.getContext("2d");
            ctx.fillStyle=`rgb(${((index+1)*19)%255},20,30)`;
            ctx.fillRect(0,0,934,1329);
          });''' if not native_source else ""}
        }},{delay_pr_hydration_ms});'''
    else:
        delayed_pr_hydration_script = ""
    if draw_on_capture:
        mutation = '''
          const original = HTMLCanvasElement.prototype.toDataURL;
          HTMLCanvasElement.prototype.toDataURL = function(...args) {
            if (!this.dataset.changedOnCapture) {
              this.dataset.changedOnCapture = "yes";
              this.getContext("2d").fillRect(0,0,1,1);
            }
            return original.apply(this,args);
          };
        '''
    else:
        mutation = ""
    if to_data_url_fails:
        mutation += "HTMLCanvasElement.prototype.toDataURL=function(){throw new Error('synthetic canvas export failure')};"
    if clear_on_capture is not None:
        clear_operation = {
            "same_size_width": "this.width=this.width;",
            "context_reset": "this.getContext('2d').reset();",
        }.get(clear_on_capture)
        if clear_operation is None:
            raise ValueError("unknown synthetic clear operation")
        mutation += f'''const prior=HTMLCanvasElement.prototype.toDataURL;
          HTMLCanvasElement.prototype.toDataURL=function(...args){{
            if(!this.dataset.changedOnCapture){{this.dataset.changedOnCapture="yes";{clear_operation}}}
            return prior.apply(this,args);
          }};'''
    if hide_nav_open_on_capture:
        mutation += '''const priorHideNavToDataURL=HTMLCanvasElement.prototype.toDataURL;
          HTMLCanvasElement.prototype.toDataURL=function(...args){
            root.classList.remove("mode-nav-open");
            return priorHideNavToDataURL.apply(this,args);
          };'''
    navigation_modes = (
        "mode-has-first-ep mode-has-next-ep"
        if episode_position == 1
        else "mode-has-prev-ep mode-has-next-ep"
    )
    root_modes = _ROOT_MODES.split(" ", 1)[1]
    if delay_pr_hydration_ms or pr_mode_missing_forever:
        root_modes = " ".join(
            mode for mode in root_modes.split() if mode != "mode-has-pr"
        )
    if remove_root_mode is not None:
        if remove_root_mode not in _ROOT_MODES.split():
            raise ValueError("cannot remove an unobserved fixture root mode")
        root_modes = " ".join(
            mode for mode in root_modes.split() if mode != remove_root_mode
        )
    if not root_feature_flags:
        root_modes = " ".join(
            mode for mode in root_modes.split() if mode not in _OPTIONAL_ROOT_FEATURE_MODES
        )
    if nav_open_initial:
        root_modes = f"{root_modes} mode-nav-open"
    post_script = (
        f"fetch({json.dumps(post_url)},{{method:'POST',mode:'no-cors',body:'synthetic'}}).catch(()=>{{}});"
        if post_url is not None and post_on_seek is None
        else ""
    )
    post_on_seek_script = (
        f"if (!window.__postAtSeekSent && Number(seek.value)==={post_on_seek}) "
        f"{{window.__postAtSeekSent=true;fetch({json.dumps(post_url)},"
        "{method:'POST',mode:'no-cors',body:'synthetic'}).catch(()=>{}); }"
        if post_url is not None and post_on_seek is not None
        else ""
    )
    native_draw_script = ""
    native_source_image_markup = ""
    if native_source:
        native_profiles = {
            "a1440": (1440, 2048, 360, 512),
            "b844": (844, 1200, 211, 300),
        }
        if native_source_profile not in native_profiles:
            raise ValueError("unknown synthetic HERO'S WEB native source profile")
        native_width, native_height, tile_width, tile_height = native_profiles[
            native_source_profile
        ]
        native_images: list[str] = []
        for slot in range(1, body_count + 1):
            color = (slot * 19) % 255
            svg = (
                f'<svg xmlns="http://www.w3.org/2000/svg" width="{native_width}" '
                f'height="{native_height}"><rect width="100%" height="100%" '
                f'fill="rgb({color},20,30)"/></svg>'
            )
            data_url = base64.b64encode(svg.encode()).decode()
            native_images.append(
                '<img class="hweb-native-atlas" '
                f'data-slot="{slot}" width="{native_width}" height="{native_height}" '
                'style="position:absolute;left:-10000px;top:0" '
                f'src="data:image/svg+xml;base64,{data_url}">'
            )
        native_source_image_markup = "".join(native_images)
        native_draw_script = f'''function drawNativeBody(canvas){{
          const wrapper=canvas.closest(".-cv-page");
          const delayMarkers=!wrapper.classList.contains("mode-rendered");
          if(delayMarkers)wrapper.classList.remove("mode-loaded","mode-rendered");
          const turn=(Number(seek.max)-Number(seek.value))/2;
          if(![...pages.children].slice(turn*2,turn*2+2).includes(wrapper))return;
          const slot=Number(canvas.dataset.slot);
          const atlas=document.querySelector('.hweb-native-atlas[data-slot="'+slot+'"]');
          if(!atlas || !atlas.complete || atlas.naturalWidth!=={native_width} || atlas.naturalHeight!=={native_height})return;
          let source=window.__herosNativeSource;
          if(!source){{source=document.createElement("canvas");window.__herosNativeSource=source;}}
          source.width={native_width};source.height={native_height};
          const sourceContext=source.getContext("2d");
          for(let row=0;row<4;row++)for(let column=0;column<4;column++){{
            const x=column*{tile_width},y=row*{tile_height};
            sourceContext.drawImage(atlas,x,y,{tile_width},{tile_height},x,y,{tile_width},{tile_height});
          }}
          canvas.getContext("2d",{{colorSpace:{json.dumps(native_color_space)}}})
            .drawImage(source,0,0,{native_width},{native_height},0,0,934.5,1329);
          if(delayMarkers)setTimeout(()=>wrapper.classList.add("mode-loaded","mode-rendered"),20);
        }}
        function drawVisibleNativeBodies(){{
          const turn=(Number(seek.max)-Number(seek.value))/2;
          const active=[...pages.children].slice(turn*2,turn*2+2);
          const pending=active.map(wrapper=>{{
            const canvas=wrapper.querySelector("canvas");
            return canvas && document.querySelector('.hweb-native-atlas[data-slot="'+canvas.dataset.slot+'"]');
          }}).filter(image=>image && !image.complete);
          if(pending.length){{
            for(const image of pending)if(!image.dataset.waitingForNativeLoad){{
              image.dataset.waitingForNativeLoad="1";
              image.addEventListener("load",()=>{{image.dataset.waitingForNativeLoad="";update();}},{{once:true}});
            }}
            return false;
          }}
          for(const wrapper of active){{const canvas=wrapper.querySelector("canvas");if(canvas)drawNativeBody(canvas);}}
          return true;
        }}'''
    native_color_script = ""
    if native_color_space != "srgb":
        native_color_script = f'''window.__nativeSourceReadbacks=0;
          const nativeGetAttributes=CanvasRenderingContext2D.prototype.getContextAttributes;
          CanvasRenderingContext2D.prototype.getContextAttributes=function(...args){{
            const value=nativeGetAttributes.apply(this,args);
            return this.canvas && this.canvas.dataset.slot
              ? {{...value,colorSpace:{json.dumps(native_color_space)}}} : value;
          }};
          const nativeGetImageData=CanvasRenderingContext2D.prototype.getImageData;
          CanvasRenderingContext2D.prototype.getImageData=function(...args){{
            if(this.canvas===window.__herosNativeSource)window.__nativeSourceReadbacks++;
            return nativeGetImageData.apply(this,args);
          }};'''
    native_mutation_actions: list[str] = []
    if native_mutate_during_materialization:
        native_mutation_actions.append('''
          const target=document.querySelector('.-cv-pages > .-cv-page[data-index="1"] canvas');
          target.getContext("2d").fillRect(0,0,1,1);
        ''')
    if native_hide_nav_open_during_materialization:
        native_mutation_actions.append('root.classList.remove("mode-nav-open");')
    if native_add_root_mode_during_materialization is not None:
        if native_add_root_mode_during_materialization != "mode-ci-page":
            raise ValueError("unsupported synthetic root mode mutation")
        native_mutation_actions.append('root.classList.add("mode-ci-page");')
    if native_seek_during_materialization:
        native_mutation_actions.append('''
          seek.value=String(Number(seek.max)-2);
          seek.dispatchEvent(new Event("input",{bubbles:true}));
        ''')
    native_mutation_script = ""
    if native_source and native_mutation_actions:
        mutation_actions = "\n".join(native_mutation_actions)
        native_mutation_script = f'''
          const nativeConvertToBlob=OffscreenCanvas.prototype.convertToBlob;
          OffscreenCanvas.prototype.convertToBlob=function(...args){{
            if(!window.__nativeMaterializationMutation){{
              window.__nativeMaterializationMutation=true;
              const canvas=this;
              return new Promise((resolve,reject)=>setTimeout(()=>{{
                {mutation_actions}
                nativeConvertToBlob.apply(canvas,args).then(resolve,reject);
              }},10));
            }}
            return nativeConvertToBlob.apply(this,args);
          }};
        '''
    native_failure_script = ""
    if native_source and native_materialization_fails:
        native_failure_script = '''setTimeout(()=>{
          const observer=window.__hwebCaptureObserver;
          observer.materializeNativeTargets=async()=>{throw new Error("synthetic native materializer failure")};
        },0);'''
    return f'''<!doctype html><html><head><meta charset="utf-8">
      <link rel="canonical" href="{BASE}/episodes/{episode_id}">
      <title>Fixture episode | HERO'S Web</title>
      <style>html,body{{margin:0;padding:0}} .-cv{{position:relative;width:1906px;height:886px;overflow:hidden}}
      .-cv-pages-wrap{{position:relative;width:1906px;height:886px;overflow:hidden}}
      .-cv-pages{{position:absolute;left:0;top:0;width:{wrapper_count * 946}px;height:886px}}
      .-cv-page{{display:inline-block;box-sizing:border-box;overflow:hidden}}</style></head><body>
      <header id="xHeader"><a class="ep-h-main-h-series" href="/series/{work_id}">Fixture Work</a></header>
      {native_source_image_markup}
      <main class="ep-main-content{' mode-charge' if access_gate else ''}">
        <div class="-cv mode-h mode-dir-rtl mode-nav-dir-rtl mode-spread mode-pc {root_modes} {navigation_modes}{loading_class}">
          <div class="-cv-pages-wrap"><div class="-cv-pages">{initial_wrappers}</div></div>
          <input class="-cv-input-seek mode-h" type="range" min="1" max="{initial_seek_max}" step="{initial_seek_step}" value="{initial_seek_value}">
          <div class="-cv-nav mode-center"></div>
        </div>
      </main>
      <script>
        const root=document.querySelector('.-cv'), pages=document.querySelector('.-cv-pages');
        const seek=document.querySelector('input[type=range]');
        {native_draw_script}
        {native_color_script}
        {native_mutation_script}
        {native_failure_script}
        function update(){{
          const turn=(Number(seek.max)-Number(seek.value))/2;
          {"if(window.__nativePreDrawnSeek!==seek.value){if(!drawVisibleNativeBodies())return;window.__nativePreDrawnSeek=seek.value;}" if native_source and native_draw_before_slide else ""}
          if(!window.__stallSeek || Number(seek.value)===Number(seek.max)) pages.style.transform=`translateX(${{turn*1892}}px)`;
          root.classList.remove('mode-first-page','mode-top-pr-page','mode-pr-page','mode-last-page','mode-ci-page');
          if(Number(seek.value)===Number(seek.max)) root.classList.add('mode-first-page','mode-top-pr-page');
          else if(Number(seek.value)===1) root.classList.add('mode-last-page');
          else {{
            const first=turn*2;
            const active=[...pages.children].slice(first,first+2);
            if(active.some(node=>node.classList.contains('mode-ci'))) root.classList.add('mode-ci-page');
            if(active.length && active.every(node=>node.classList.contains('mode-pr')||node.classList.contains('mode-ci')||node.classList.contains('mode-good'))) root.classList.add('mode-pr-page');
          }}
          {"drawVisibleNativeBodies();" if native_source and not native_draw_before_slide else ""}
          {post_on_seek_script}
        }}
        seek.addEventListener('input',update);seek.addEventListener('change',update);update();
        window.__stallSeek={str(stall_after_initial).lower()};
        {mutation}
        {delayed_structure_script}
        {delayed_pr_hydration_script}
        fetch('/api/missions',{{method:'POST',body:'fixture telemetry'}}).catch(()=>{{}});
        {post_script}
      </script>
      </body></html>'''


async def _install_live_fixture(
    page: Page,
    *,
    work_id: str,
    episode_id: str,
    body_count: int,
    target_position: int,
    ranges: tuple[tuple[int, int], ...],
    preview_rows: tuple[int, ...],
    target_label: str = "無料",
    authenticated: bool = True,
    auth_header_delay_ms: int = 0,
    viewer_options: dict[str, object] | None = None,
    bad_session_status: int | None = None,
    fatal_subresource_status: int | None = None,
    ambiguous_preview_roots: bool = False,
) -> list[str]:
    work_title = f"Fixture work {work_id}"
    requests: list[str] = []
    options = viewer_options or {}

    async def fulfill(route) -> None:
        parsed = urlsplit(route.request.url)
        requests.append(f"{route.request.method} {parsed.path}")
        if parsed.path == "/api/auth/session":
            await route.fulfill(
                status=bad_session_status or 200,
                headers={"content-type": "application/json"},
                body='{"user":{"id":"synthetic"}}' if authenticated else '{"user":null}',
            )
            return
        if parsed.path == "/api/preflight-stop" and fatal_subresource_status is not None:
            await route.fulfill(
                status=fatal_subresource_status,
                headers={"content-type": "text/plain"},
                body="blocked",
            )
            return
        if parsed.path == f"/episodes/{episode_id}":
            await route.fulfill(
                status=200,
                headers={"content-type": "text/html"},
                body=_viewer_page(
                    work_id=work_id,
                    episode_id=episode_id,
                    episode_position=target_position,
                    body_count=body_count,
                    **options,
                ),
            )
            return
        if parsed.path == f"/series/{work_id}":
            await route.fulfill(
                status=200,
                headers={"content-type": "text/html"},
                body=_listing_page(
                    work_id=work_id,
                    work_title=work_title,
                    target_episode_id=episode_id,
                    target_position=target_position,
                    ranges=ranges,
                    selected_range=None,
                    rows=preview_rows,
                    target_label=target_label,
                    authenticated=authenticated,
                    fatal_subresource_status=fatal_subresource_status,
                    ambiguous_preview_roots=ambiguous_preview_roots,
                ),
            )
            return
        range_match = None
        for index, (start, end) in enumerate(ranges, start=1):
            if parsed.path == f"/series/{work_id}/{index}":
                range_match = (index, start, end)
                break
        if range_match is not None:
            index, start, end = range_match
            await route.fulfill(
                status=200,
                headers={"content-type": "text/html"},
                body=_listing_page(
                    work_id=work_id,
                    work_title=work_title,
                    target_episode_id=episode_id,
                    target_position=target_position,
                    ranges=ranges,
                    selected_range=index,
                    rows=tuple(range(start, end + 1)),
                    target_label=target_label,
                    authenticated=authenticated,
                    delay_auth_header_ms=auth_header_delay_ms,
                    fatal_subresource_status=fatal_subresource_status,
                ),
            )
            return
        await route.fulfill(status=404, body="unexpected synthetic route")

    await page.route("https://heros-web.com/**", fulfill)
    return requests


def _run_config(
    tmp_path: Path,
    episode_id: str,
    *,
    max_pages: int,
    page_change_timeout_ms: int = 2_000,
) -> RunConfig:
    return RunConfig(
        site="herosweb",
        source_url=f"{BASE}/episodes/{episode_id}",
        output_dir=tmp_path / "crawl-output",
        diagnostics_dir=tmp_path / "diagnostics",
        viewport_width=1906,
        viewport_height=986,
        max_pages=max_pages,
        max_same_content=3,
        retry_count=2,
        navigation_timeout_ms=5_000,
        page_change_timeout_ms=page_change_timeout_ms,
        adapter_timeout_grace_ms=1_000,
        page_turn_delay_ms=0,
    )


def _make_herosweb_batch(
    tmp_path: Path,
    *, rented: bool = False,
) -> tuple[CatalogService, BatchExecutor, object]:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(
        WorkInput(work_key="herosweb-work-fixture", title="Catalog Work")
    )
    item = catalog.create_item(
        ItemInput(item_title="Fixture episode 1", kind="episode", order_label="1"),
        work_id=work.id,
    )
    source = catalog.create_source(
        SourceInput(
            site="herosweb",
            external_id=f"{WORK_A}:{EPISODE_A}",
            discovery_key="herosweb-fixture",
            access_mode="quota" if rented else "free",
            access_granted_until="2099-11-24T12:00:00+09:00" if rented else None,
            available=True,
            display_position=1,
        ),
        item_id=item.id,
    )
    target = catalog.create_source_target(
        SourceTargetInput(backend="web", locator=EPISODE_URL_A),
        source_id=source.id,
    )
    watchlist = WatchlistService(tmp_path / "watchlist.yaml")
    watchlist.add(
        key="herosweb-fixture",
        work_key=work.work_key,
        site="herosweb",
        url=WORK_URL_A,
        label="Catalog Work",
    )
    reconciler = ScopeReconciler(watchlist, catalog)
    preview = reconciler.preview(work.work_key)
    assert preview.ready, preview.blockers
    reconciler.apply(preview)

    policies = SitePolicyRegistry()
    policies.register("herosweb", HeroswebSitePolicy)
    adapters = AdapterRegistry()
    adapters.register("herosweb", HeroswebAdapter)
    plan = BatchPlanner(catalog, policies, watchlist=watchlist).plan(
        site="herosweb",
        now=NOW,
    )
    assert len(plan.candidates) == 1
    candidate = plan.candidates[0]
    assert candidate.source_id == source.id
    assert candidate.target_id == target.id
    assert candidate.locator == EPISODE_URL_A
    assert candidate.external_id == source.external_id
    assert candidate.access_strategy == "direct"
    executor = BatchExecutor(
        catalog,
        policies,
        adapters,
        watchlist=watchlist,
        library_dir=tmp_path / "Books",
        runtime_settings=SiteRuntimeSettings(
            page_turn_delay_ms=0,
            inter_candidate_delay_ms=0,
        ),
    )
    return catalog, executor, candidate


@pytest.mark.parametrize(
    ("work_id", "episode_id", "body_count", "target_position", "ranges", "preview_rows"),
    [
        (WORK_A, EPISODE_A, 10, 1, ((1, 10),), tuple(range(1, 11))),
        (WORK_B, EPISODE_B, 38, 6, ((1, 30), (31, 38)), tuple(range(1, 6))),
        (WORK_B, "e1d105f22de45", 15, 1, ((1, 15),), tuple(range(1, 16))),
    ],
)
async def test_herosweb_free_episode_runner_captures_all_body_and_terminal_end(
    browser_page: Page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    work_id: str,
    episode_id: str,
    body_count: int,
    target_position: int,
    ranges: tuple[tuple[int, int], ...],
    preview_rows: tuple[int, ...],
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    requests = await _install_live_fixture(
        browser_page,
        work_id=work_id,
        episode_id=episode_id,
        body_count=body_count,
        target_position=target_position,
        ranges=ranges,
        preview_rows=preview_rows,
        ambiguous_preview_roots=True,
    )
    monkeypatch.setattr(adapter_module, "RANGE_PACING_MS", 20)
    adapter = HeroswebAdapter()
    result = await CrawlerRunner(
        _run_config(tmp_path, episode_id, max_pages=body_count)
    ).run(browser_page, adapter)

    debug = await adapter.collect_debug_metadata(browser_page)
    assert debug["blocked_external_writes"] == {"count": 0, "host_paths": []}

    assert result.stop_state is PageState.END
    assert len(result.pages) == body_count
    assert [page.identity.page_id for page in result.pages] == [episode_id] * body_count
    expected_sources = ["body-slots:1"]
    expected_page_numbers = [1]
    for first_slot in range(2, body_count + 1, 2):
        slot_ids = ",".join(str(slot) for slot in range(first_slot, min(first_slot + 2, body_count + 1)))
        expected_sources.extend([f"body-slots:{slot_ids}"] * min(2, body_count - first_slot + 1))
        expected_page_numbers.extend([first_slot] * min(2, body_count - first_slot + 1))
    assert [page.identity.source_id for page in result.pages] == expected_sources
    assert [page.identity.page_number for page in result.pages] == expected_page_numbers
    assert [(page.width, page.height, page.mime_type, page.file_extension) for page in result.pages] == [
        (934, 1329, "image/png", ".png")
    ] * body_count
    output_dir = tmp_path / "crawl-output"
    assert all(
        (output_dir / page.file).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        for page in result.pages
    )
    assert [Image.open(output_dir / page.file).getpixel((100, 100))[:3] for page in result.pages] == [
        ((slot * 19) % 255, 20, 30) for slot in range(1, body_count + 1)
    ]
    assert requests.count(f"GET /episodes/{episode_id}") == 2
    assert requests.count(f"GET /series/{work_id}") == 1
    assert requests.count(f"GET /series/{work_id}/1") == 1
    assert any(request == "POST /api/missions" for request in requests) is False
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["pages"]) == body_count
    first_capture_metadata = manifest["pages"][0]["metadata"]["capture"]["pages"]
    latest_capture_metadata = manifest["pages"][-1]["metadata"]["capture"]["pages"]
    assert len(first_capture_metadata) == 1
    assert first_capture_metadata[0]["slots"] == [1]
    assert len(latest_capture_metadata) == (body_count + 2) // 2
    assert latest_capture_metadata[-1]["slots"] == (
        [body_count] if body_count % 2 == 0 else [body_count - 1, body_count]
    )
    assert first_capture_metadata[0]["images"][0]["mode"] == "rendered_canvas_png"
    assert first_capture_metadata[0]["images"][0]["target_generation"] == 0
    explicit_output_dir = tmp_path / "explicit-metadata-output"
    shutil.copytree(output_dir, explicit_output_dir)
    package = package_crawl_output(
        output_dir,
        adapter.get_output_metadata(),
        library_dir=tmp_path / "library",
    )
    assert adapter.get_output_metadata()["genre"] == "漫画"
    assert package.archive_path.parent.parent.name == "漫画"
    with zipfile.ZipFile(package.archive_path) as archive:
        assert len(archive.namelist()) == body_count
        assert all(name.endswith(".png") for name in archive.namelist())
    override_package = package_crawl_output(
        explicit_output_dir,
        adapter.get_output_metadata(),
        library_dir=tmp_path / "explicit-genre-library",
        explicit_metadata={"genre": "Explicit category"},
    )
    assert override_package.archive_path.parent.parent.name == "Explicit category"


async def test_herosweb_native_source_spread_is_lossless_and_draw_classes_can_hydrate_later(
    browser_page: Page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_live_fixture(
        browser_page,
        work_id=WORK_A,
        episode_id=EPISODE_A,
        body_count=4,
        target_position=1,
        ranges=((1, 4),),
        preview_rows=(1, 2, 3, 4),
        viewer_options={
            "native_source": True,
            "native_draw_before_slide": True,
        },
    )
    monkeypatch.setattr(adapter_module, "RANGE_PACING_MS", 20)
    adapter = HeroswebAdapter()
    result = await CrawlerRunner(_run_config(tmp_path, EPISODE_A, max_pages=4)).run(
        browser_page, adapter
    )

    assert result.stop_state is PageState.END
    assert len(result.pages) == 4
    assert [page.identity.source_id for page in result.pages] == [
        "body-slots:1",
        "body-slots:2,3",
        "body-slots:2,3",
        "body-slots:4",
    ]
    assert all((page.width, page.height) == (1440, 2048) for page in result.pages)
    assert all(
        (page.mime_type, page.file_extension)
        in {("image/webp", ".webp"), ("image/png", ".png")}
        for page in result.pages
    )
    manifest = json.loads(
        (tmp_path / "crawl-output" / "manifest.json").read_text(encoding="utf-8")
    )
    first_images = manifest["pages"][0]["metadata"]["capture"]["pages"][0]["images"]
    assert first_images[0]["mode"] in {
        "source_canvas_lossless_vp8l",
        "source_canvas_native_png",
    }
    assert first_images[0]["native_pixels_proven"] is True
    assert first_images[0]["original_bytes_proven"] is False
    assert first_images[0]["native_proof"]["sourceHistoryComplete"] is True
    assert first_images[0]["native_proof"]["sourceReplayMatchesTarget"] is True
    assert first_images[0]["native_proof"]["source_rgba_sha256"]
    if first_images[0]["mode"] == "source_canvas_lossless_vp8l":
        assert first_images[0]["native_proof"]["webp_vp8l_rgba_verified"] is True
    spread_images = manifest["pages"][2]["metadata"]["capture"]["pages"][-1]["images"]
    assert [image["slot"] for image in spread_images] == [2, 3]
    assert all(image["native_pixels_proven"] is True for image in spread_images)
    assert all(image["native_proof"]["drawPairStart"] == 2 for image in spread_images)
    assert all(image["native_proof"]["drawPairSlots"] == [2, 3] for image in spread_images)
    assert all(image["native_proof"]["drawToCaptureCommonTranslation"] is True for image in spread_images)
    assert all(image["native_proof"]["drawTargetRectAfter"]["x"] < 0 for image in spread_images)
    assert all(image["native_proof"]["materializedTargetRect"]["x"] >= 0 for image in spread_images)
    assert spread_images[0]["native_proof"]["sourceCanvasNodeId"] == spread_images[1]["native_proof"]["sourceCanvasNodeId"]
    assert spread_images[0]["native_proof"]["sourceGenerationAtDraw"] != spread_images[1]["native_proof"]["sourceGenerationAtDraw"]
    assert [
        Image.open(tmp_path / "crawl-output" / page.file).convert("RGB").getpixel((20, 20))
        for page in result.pages
    ] == [(19, 20, 30), (38, 20, 30), (57, 20, 30), (76, 20, 30)]
    materialization_request = await browser_page.evaluate(
        """() => {
          const observer=window.__hwebCaptureObserver;
          const seek=document.querySelector('input[type="range"]');
          const pages=document.querySelector('.-cv-pages');
          const layout=observer.currentLayout();
          seek.value=seek.max;
          seek.dispatchEvent(new Event('input',{bubbles:true}));
          const canvas=pages.children[1].querySelector('canvas');
          const value=Number(seek.value), pairStart=((Number(seek.max)-value)/Number(seek.step))*2;
          const pairSlots=[...pages.children].slice(pairStart,pairStart+2).map((_node,i)=>pairStart+i);
          const releasePromise=new Promise(resolve=>window.__releaseNativeConversion=resolve);
          const original=OffscreenCanvas.prototype.convertToBlob;
          window.__nativeConversionStarted=false;
          OffscreenCanvas.prototype.convertToBlob=function(...args){
            window.__nativeConversionStarted=true;
            const canvas=this;
            return releasePromise.then(()=>original.apply(canvas,args));
          };
          return {
            expectedUrl:location.href,episodeId:location.pathname.split('/').pop(),
            workId:document.querySelector('#xHeader a.ep-h-main-h-series').getAttribute('href').split('/').pop(),
            layout:observer.currentLayout(),
            seekNodeId:observer.nodeId(seek),seekValue:Number(seek.value),
            targets:[{
              slot:1,seekValue:Number(seek.value),nodeId:observer.nodeId(canvas),
              width:canvas.width,height:canvas.height,drawEpoch:observer.epoch(canvas),
              generation:observer.generation(canvas),wrapperNodeId:layout.wrapperNodeIds[1],
              rootNodeId:layout.rootNodeId,pagesWrapNodeId:layout.pagesWrapNodeId,
              pagesRootNodeId:layout.pagesRootNodeId,seekNodeId:layout.seekNodeId,
              pairStart,pairSlots,rootStructuralModes:layout.rootStructuralModes
            }]
          };
        }"""
    )
    first_materialization = asyncio.create_task(
        browser_page.evaluate(
            "request => window.__hwebCaptureObserver.materializeNativeTargets(request)",
            materialization_request,
        )
    )
    await browser_page.wait_for_function(
        "window.__nativeConversionStarted === true", timeout=5_000
    )
    second_materialization = await browser_page.evaluate(
        "request => window.__hwebCaptureObserver.materializeNativeTargets(request)",
        materialization_request,
    )
    assert second_materialization == {
        "status": "unsupported",
        "reason": "native_materialization_busy",
    }
    await browser_page.evaluate("window.__releaseNativeConversion()")
    first_materialization_result = await first_materialization
    assert first_materialization_result["status"] == "ok"
    assert first_materialization_result["records"][0]["supported"] is True
    cleanup = await browser_page.evaluate(
        """async () => {
          const observer=window.__hwebCaptureObserver;
          const seek=document.querySelector('input[type="range"]');
          const pages=document.querySelector('.-cv-pages');
          seek.value=seek.max;
          seek.dispatchEvent(new Event('input',{bubbles:true}));
          const canvas=pages.children[1].querySelector('canvas');
          const expected=()=>{
            const layout=observer.currentLayout();
            const value=Number(seek.value), pairStart=((Number(seek.max)-value)/Number(seek.step))*2;
            const pairSlots=[...pages.children].slice(pairStart,pairStart+2).map((_node,i)=>pairStart+i);
            return {
              slot:1,seekValue:Number(seek.value),nodeId:observer.nodeId(canvas),
              width:canvas.width,height:canvas.height,drawEpoch:observer.epoch(canvas),
              generation:observer.generation(canvas),wrapperNodeId:layout.wrapperNodeIds[1],
              rootNodeId:layout.rootNodeId,pagesWrapNodeId:layout.pagesWrapNodeId,
              pagesRootNodeId:layout.pagesRootNodeId,seekNodeId:layout.seekNodeId,
              pairStart,pairSlots,rootStructuralModes:layout.rootStructuralModes
            };
          };
          const request=target=>({
            expectedUrl:location.href,episodeId:location.pathname.split('/').pop(),
            workId:document.querySelector('#xHeader a.ep-h-main-h-series').getAttribute('href').split('/').pop(),
            layout:observer.currentLayout(),
            seekNodeId:observer.nodeId(seek),seekValue:Number(seek.value),targets:[target]
          });
          const matched=expected();
          observer.releaseNativeTargets([matched]);
          const afterMatched=await observer.materializeNativeTargets(request(matched));
          window.drawNativeBody(canvas);
          const newer=expected();
          observer.releaseNativeTargets([matched]);
          const afterStaleRelease=await observer.materializeNativeTargets(request(newer));
          observer.releaseNativeTargets([newer]);
          return {
            afterMatchedSupported:afterMatched.records[0].supported,
            afterStaleReleaseSupported:afterStaleRelease.records[0].supported,
            oldEpoch:matched.drawEpoch,newEpoch:newer.drawEpoch
          };
        }"""
    )
    assert cleanup["afterMatchedSupported"] is False
    assert cleanup["afterStaleReleaseSupported"] is True
    assert cleanup["newEpoch"] > cleanup["oldEpoch"]


async def test_herosweb_native_844_profile_preserves_reused_canvas_spread(
    browser_page: Page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_live_fixture(
        browser_page,
        work_id=WORK_B,
        episode_id=EPISODE_B,
        body_count=38,
        target_position=6,
        ranges=((1, 6),),
        preview_rows=tuple(range(1, 7)),
        viewer_options={
            "native_source": True,
            "native_source_profile": "b844",
        },
    )
    monkeypatch.setattr(adapter_module, "RANGE_PACING_MS", 20)
    result = await CrawlerRunner(_run_config(tmp_path, EPISODE_B, max_pages=38)).run(
        browser_page, HeroswebAdapter()
    )

    assert result.stop_state is PageState.END
    assert len(result.pages) == 38
    assert all((page.width, page.height) == (844, 1200) for page in result.pages)
    assert all(
        (page.mime_type, page.file_extension)
        in {("image/webp", ".webp"), ("image/png", ".png")}
        for page in result.pages
    )
    manifest = json.loads(
        (tmp_path / "crawl-output" / "manifest.json").read_text(encoding="utf-8")
    )
    spread_pages = [
        page
        for page in manifest["pages"]
        if page["identity"]["source_id"] == "body-slots:2,3"
    ]
    assert len(spread_pages) == 2
    spread_images = spread_pages[0]["metadata"]["capture"]["pages"][-1]["images"]
    assert [image["slot"] for image in spread_images] == [2, 3]
    assert all(image["native_pixels_proven"] is True for image in spread_images)
    assert all(image["original_bytes_proven"] is False for image in spread_images)
    assert all(
        image["native_proof"]["sourceDimensions"] == [844, 1200]
        for image in spread_images
    )
    assert all(
        image["native_proof"]["sourceTileGeometry"]
        == "complete_4x4_211x300_1to1_rgba_verified"
        for image in spread_images
    )
    assert all(image["native_proof"]["sourceHistoryComplete"] is True for image in spread_images)
    assert spread_images[0]["native_proof"]["sourceCanvasNodeId"] == spread_images[1]["native_proof"]["sourceCanvasNodeId"]
    assert spread_images[0]["native_proof"]["sourceGenerationAtDraw"] != spread_images[1]["native_proof"]["sourceGenerationAtDraw"]
    expected_rgba = {
        image["native_proof"]["source_rgba_sha256"] for image in spread_images
    }
    assert len(expected_rgba) == 2
    saved_rgba = set()
    for page in spread_pages:
        pixels = Image.open(
            tmp_path / "crawl-output" / page["file"]
        ).convert("RGBA").tobytes()
        saved_rgba.add(hashlib.sha256(pixels).hexdigest())
    assert saved_rgba == expected_rgba


async def test_herosweb_native_first_body_survives_the_observed_pending_pr_shell(
    browser_page: Page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_live_fixture(
        browser_page,
        work_id=WORK_A,
        episode_id=EPISODE_A,
        body_count=2,
        target_position=1,
        ranges=((1, 2),),
        preview_rows=(1, 2),
        viewer_options={
            "native_source": True,
            "delay_pr_hydration_ms": 35,
            "native_draw_while_pr_pending": True,
        },
    )
    monkeypatch.setattr(adapter_module, "RANGE_PACING_MS", 20)
    result = await CrawlerRunner(_run_config(tmp_path, EPISODE_A, max_pages=4)).run(
        browser_page, HeroswebAdapter()
    )

    assert result.stop_state is PageState.END
    assert len(result.pages) == 2
    manifest = json.loads(
        (tmp_path / "crawl-output" / "manifest.json").read_text(encoding="utf-8")
    )
    image = manifest["pages"][0]["metadata"]["capture"]["pages"][0]["images"][0]
    assert image["native_pixels_proven"] is True
    assert image["native_proof"]["drawPairStart"] == 0
    assert image["native_proof"]["drawPairSlots"] == [0, 1]
    assert "mode-has-pr" not in image["native_proof"]["drawRootStructuralModes"]
    assert image["native_proof"]["drawToCaptureCommonTranslation"] is True


async def test_herosweb_native_candidates_bind_seek_owner_scale_and_reset_generation(
    browser_page: Page,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await browser_page.add_init_script(adapter_module._OBSERVER_INIT_SCRIPT)
    await _install_live_fixture(
        browser_page,
        work_id=WORK_A,
        episode_id=EPISODE_A,
        body_count=4,
        target_position=1,
        ranges=((1, 4),),
        preview_rows=(1, 2, 3, 4),
        viewer_options={"native_source": True, "native_draw_before_slide": True},
    )
    await browser_page.goto(EPISODE_URL_A)
    await browser_page.wait_for_function(
        "document.querySelector('.-cv-pages > .-cv-page[data-index=\"1\"] canvas')?.width === 934"
    )
    outcomes = await browser_page.evaluate(
        """async () => {
          const observer=window.__hwebCaptureObserver;
          const seek=document.querySelector('input[type="range"]');
          const pages=document.querySelector('.-cv-pages');
          const requestFor=slot=>{
            const layout=observer.currentLayout();
            const value=Number(seek.value), max=Number(seek.max), step=Number(seek.step);
            const pairStart=((max-value)/step)*2;
            const pairSlots=[...pages.children].slice(pairStart,pairStart+2).map((_node,i)=>pairStart+i);
            const wrapper=pages.children[slot], canvas=wrapper.querySelector('canvas');
            return {
              expectedUrl:location.href,episodeId:location.pathname.split('/').pop(),
              workId:document.querySelector('#xHeader a.ep-h-main-h-series').getAttribute('href').split('/').pop(),
              layout,seekNodeId:observer.nodeId(seek),seekValue:value,
              targets:[{
                slot,seekValue:value,nodeId:observer.nodeId(canvas),width:canvas.width,height:canvas.height,
                drawEpoch:observer.epoch(canvas),generation:observer.generation(canvas),
                wrapperNodeId:layout.wrapperNodeIds[slot],rootNodeId:layout.rootNodeId,
                pagesWrapNodeId:layout.pagesWrapNodeId,pagesRootNodeId:layout.pagesRootNodeId,
                seekNodeId:layout.seekNodeId,pairStart,pairSlots,
                rootStructuralModes:layout.rootStructuralModes
              }]
            };
          };
          const initial=requestFor(1);
          const wrongOwner=structuredClone(initial);
          wrongOwner.targets[0].wrapperNodeId += 1000;
          const wrongOwnerResult=await observer.materializeNativeTargets(wrongOwner);
          seek.value=String(Number(seek.max)-2);
          seek.dispatchEvent(new Event('input',{bubbles:true}));
          const wrongSeekResult=await observer.materializeNativeTargets(initial);
          const target=pages.children[2].querySelector('canvas');
          const current=requestFor(2);
          target.style.width='624px';
          const scaleResult=await observer.materializeNativeTargets(current);
          observer.releaseNativeTargets(current.targets);
          target.style.width='';
          window.drawNativeBody(target);
          const root=document.querySelector('.-cv');
          root.classList.remove('mode-has-pr');
          window.drawNativeBody(target);
          root.classList.add('mode-has-pr');
          const laterPrResult=await observer.materializeNativeTargets(requestFor(2));
          observer.releaseNativeTargets(requestFor(2).targets);
          window.drawNativeBody(target);
          const generationBeforeReset=observer.generation(target);
          target.width=target.width;
          const afterReset=requestFor(2);
          const resetResult=await observer.materializeNativeTargets(afterReset);
          observer.releaseNativeTargets(afterReset.targets);
          return {
            wrongOwnerStatus:wrongOwnerResult.status,
            wrongSeekStatus:wrongSeekResult.status,
            scaledSupported:scaleResult.records?.[0]?.supported,
            laterPrSupported:laterPrResult.records?.[0]?.supported,
            generationBeforeReset,generationAfterReset:observer.generation(target),
            resetSupported:resetResult.records?.[0]?.supported
          };
        }"""
    )

    assert outcomes["wrongOwnerStatus"] == "target_drift"
    assert outcomes["wrongSeekStatus"] == "target_drift"
    assert outcomes["scaledSupported"] is False
    assert outcomes["laterPrSupported"] is False
    assert outcomes["generationAfterReset"] > outcomes["generationBeforeReset"]
    assert outcomes["resetSupported"] is False


async def test_herosweb_native_target_drift_during_async_materialization_stops_capture(
    browser_page: Page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_live_fixture(
        browser_page,
        work_id=WORK_A,
        episode_id=EPISODE_A,
        body_count=2,
        target_position=1,
        ranges=((1, 2),),
        preview_rows=(1, 2),
        viewer_options={
            "native_source": True,
            "native_mutate_during_materialization": True,
        },
    )
    monkeypatch.setattr(adapter_module, "RANGE_PACING_MS", 20)
    with pytest.raises(UnknownPageStateError, match="Viewer changed during native pixel materialization"):
        await CrawlerRunner(_run_config(tmp_path, EPISODE_A, max_pages=1)).run(
            browser_page, HeroswebAdapter()
        )
    assert not list((tmp_path / "crawl-output").glob("page-*"))


async def test_herosweb_fully_native_capture_allows_nav_open_to_hide_during_materialization(
    browser_page: Page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_live_fixture(
        browser_page,
        work_id=WORK_A,
        episode_id=EPISODE_A,
        body_count=2,
        target_position=1,
        ranges=((1, 2),),
        preview_rows=(1, 2),
        viewer_options={
            "native_source": True,
            "nav_open_initial": True,
            "native_hide_nav_open_during_materialization": True,
        },
    )
    monkeypatch.setattr(adapter_module, "RANGE_PACING_MS", 20)
    result = await CrawlerRunner(_run_config(tmp_path, EPISODE_A, max_pages=2)).run(
        browser_page, HeroswebAdapter()
    )

    assert result.stop_state is PageState.END
    assert len(result.pages) == 2
    assert all(page.mime_type == "image/webp" for page in result.pages)
    manifest = json.loads(
        (tmp_path / "crawl-output" / "manifest.json").read_text(encoding="utf-8")
    )
    assert [
        page["metadata"]["capture"]["pages"][-1]["images"][0]["mode"]
        for page in manifest["pages"]
    ] == ["source_canvas_lossless_vp8l", "source_canvas_lossless_vp8l"]


@pytest.mark.parametrize(
    "options",
    [
        {"native_seek_during_materialization": True},
        {"native_add_root_mode_during_materialization": "mode-ci-page"},
    ],
    ids=("seek-drift-remains-fatal", "other-root-mode-remains-strict"),
)
async def test_herosweb_native_capture_nav_exception_keeps_other_signature_changes_fatal(
    browser_page: Page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    options: dict[str, object],
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_live_fixture(
        browser_page,
        work_id=WORK_A,
        episode_id=EPISODE_A,
        body_count=2,
        target_position=1,
        ranges=((1, 2),),
        preview_rows=(1, 2),
        viewer_options={
            "native_source": True,
            "nav_open_initial": True,
            "native_hide_nav_open_during_materialization": True,
            **options,
        },
    )
    monkeypatch.setattr(adapter_module, "RANGE_PACING_MS", 20)
    with pytest.raises(UnknownPageStateError):
        await CrawlerRunner(_run_config(tmp_path, EPISODE_A, max_pages=2)).run(
            browser_page, HeroswebAdapter()
        )
    assert not list((tmp_path / "crawl-output").glob("page-*"))


async def test_herosweb_png_fallback_keeps_nav_open_signature_strict(
    browser_page: Page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_live_fixture(
        browser_page,
        work_id=WORK_A,
        episode_id=EPISODE_A,
        body_count=2,
        target_position=1,
        ranges=((1, 2),),
        preview_rows=(1, 2),
        viewer_options={
            "nav_open_initial": True,
            "hide_nav_open_on_capture": True,
        },
    )
    monkeypatch.setattr(adapter_module, "RANGE_PACING_MS", 20)
    with pytest.raises(UnknownPageStateError, match="body canvas changed"):
        await CrawlerRunner(_run_config(tmp_path, EPISODE_A, max_pages=2)).run(
            browser_page, HeroswebAdapter()
        )
    assert not list((tmp_path / "crawl-output").glob("page-*"))


async def test_herosweb_unsupported_display_p3_target_uses_rendered_png_fallback(
    browser_page: Page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_live_fixture(
        browser_page,
        work_id=WORK_A,
        episode_id=EPISODE_A,
        body_count=2,
        target_position=1,
        ranges=((1, 2),),
        preview_rows=(1, 2),
        viewer_options={"native_source": True, "native_color_space": "display-p3"},
    )
    monkeypatch.setattr(adapter_module, "RANGE_PACING_MS", 20)
    adapter = HeroswebAdapter()
    result = await CrawlerRunner(_run_config(tmp_path, EPISODE_A, max_pages=2)).run(
        browser_page, adapter
    )
    assert result.stop_state is PageState.END
    assert len(result.pages) == 2
    assert all((page.mime_type, page.file_extension) == ("image/png", ".png") for page in result.pages)
    manifest = json.loads(
        (tmp_path / "crawl-output" / "manifest.json").read_text(encoding="utf-8")
    )
    image = manifest["pages"][0]["metadata"]["capture"]["pages"][0]["images"][0]
    assert image["mode"] == "rendered_canvas_png"
    assert image["native_pixels_proven"] is False
    assert image["native_fallback_reason"] == "target_color_format_unsupported"
    assert await browser_page.evaluate("window.__nativeSourceReadbacks") == 0


@pytest.mark.parametrize(
    "failure",
    [PlaywrightError("synthetic evaluate failure"), TimeoutError("synthetic timeout")],
    ids=("evaluation-error", "bounded-timeout"),
)
async def test_herosweb_native_materialization_errors_keep_frozen_png_fallback(
    failure: Exception,
) -> None:
    class FakePage:
        url = EPISODE_URL_A

        async def evaluate(self, expression, argument=None):
            if expression.startswith("async request =>"):
                raise failure
            if "const cleanPath" in expression:
                return {
                    "url": EPISODE_URL_A,
                    "episodeId": EPISODE_A,
                    "canonical": [EPISODE_URL_A],
                    "headerCount": 1,
                    "workLinkCount": 1,
                    "workPath": f"/series/{WORK_A}",
                    "chargeGateCount": 0,
                    "visibleLoginActionCount": 0,
                    "viewerFrameCount": 0,
                }
            return None

    adapter = HeroswebAdapter()
    adapter._target_url = EPISODE_URL_A
    adapter._episode_id = EPISODE_A
    adapter._work_id = WORK_A
    adapter._layout = adapter_module._ViewerLayout(
        root_node_id=1,
        pages_wrap_node_id=2,
        pages_root_node_id=3,
        wrapper_node_ids=(4, 5),
        roles=("lead_pr", "body"),
        body_slots=(1,),
        ci_slot=0,
        pr_slots=(),
        good_slot=0,
        last_slot=0,
        seek_node_id=1,
        seek_min=1,
        seek_max=17,
        seek_step=2,
        root_structural_modes=tuple(sorted(adapter_module._ROOT_REQUIRED_MODES)),
    )
    before = {
        "seek": [{"nodeId": 1, "value": "17"}],
        "wrappers": [
            {"nodeId": 4, "canvases": []},
            {
                "nodeId": 5,
                "canvases": [
                    {
                        "nodeId": 23,
                        "width": 934,
                        "height": 1329,
                        "drawEpoch": 9,
                        "generation": 0,
                    }
                ]
            },
        ],
    }
    outputs, raw = await adapter._materialize_native_targets(FakePage(), before, (1,))
    assert outputs == (None,)
    assert raw["status"] == "unsupported"
    assert raw["reason"] in {"native_materialization_timeout", "native_materialization_error"}


async def test_herosweb_native_materializer_error_falls_back_without_losing_body_order(
    browser_page: Page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_live_fixture(
        browser_page,
        work_id=WORK_A,
        episode_id=EPISODE_A,
        body_count=2,
        target_position=1,
        ranges=((1, 2),),
        preview_rows=(1, 2),
        viewer_options={"native_source": True, "native_materialization_fails": True},
    )
    monkeypatch.setattr(adapter_module, "RANGE_PACING_MS", 20)
    adapter = HeroswebAdapter()
    result = await CrawlerRunner(_run_config(tmp_path, EPISODE_A, max_pages=2)).run(
        browser_page, adapter
    )
    assert result.stop_state is PageState.END
    assert [page.identity.source_id for page in result.pages] == [
        "body-slots:1",
        "body-slots:2",
    ]
    assert all((page.mime_type, page.file_extension) == ("image/png", ".png") for page in result.pages)
    manifest = json.loads(
        (tmp_path / "crawl-output" / "manifest.json").read_text(encoding="utf-8")
    )
    assert [
        page["metadata"]["capture"]["pages"][-1]["images"][0]["native_fallback_reason"]
        for page in manifest["pages"]
    ] == ["native_materialization_error", "native_materialization_error"]


@pytest.mark.parametrize(
    ("body_count", "native_source", "rented"),
    [(10, False, False), (10, True, False), (15, False, False), (15, True, False),
     (10, True, True)],
)
async def test_herosweb_free_direct_batch_completes_through_catalog_and_zip(
    browser_page: Page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    native_source: bool,
    body_count: int,
    rented: bool,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    requests = await _install_live_fixture(
        browser_page,
        work_id=WORK_A,
        episode_id=EPISODE_A,
        body_count=body_count,
        target_position=1,
        ranges=((1, 10),),
        preview_rows=tuple(range(1, 11)),
        ambiguous_preview_roots=True,
        viewer_options={
            "native_source": native_source,
            "delay_structure_ms": 600 if body_count % 2 else 0,
        },
    )
    monkeypatch.setattr(adapter_module, "RANGE_PACING_MS", 20)
    monkeypatch.setattr(adapter_module, "MAX_VIEWER_SETTLE_SECONDS", 3)
    catalog, executor, candidate = _make_herosweb_batch(tmp_path, rented=rented)

    result = await executor.execute_candidate(
        browser_page,
        candidate,
        output_root=tmp_path / "batch-output",
        library_dir=tmp_path / "Books",
        max_pages=body_count,
        now=NOW,
    )

    assert result.page_count == body_count
    assert result.stop_reason == "end"
    assert result.archive_path.is_file()
    assert result.status_path.is_file()
    assert result.archive_path.parent.parent.name == "漫画"
    assert "Catalog Work" in result.archive_path.name
    assert requests.count(f"GET /episodes/{EPISODE_A}") == 1
    assert not any(request.startswith("GET /series/") for request in requests)
    assert not any(request.startswith("POST ") for request in requests)

    item = catalog.get_item(candidate.item_id)
    source = catalog.get_source(candidate.source_id)
    target = catalog.get_source_target(candidate.target_id)
    assert item.status == "completed"
    assert target.locator == EPISODE_URL_A
    assert (source.quota_started_at, source.access_granted_until) == (
        None, "2099-11-24T12:00:00+09:00" if rented else None,
    )
    assert len(catalog.list_artifacts(item_id=candidate.item_id, state="present")) == 1
    assert len(catalog.list_crawl_runs(item_id=candidate.item_id, status="succeeded")) == 1
    with zipfile.ZipFile(result.archive_path) as archive:
        names = archive.namelist()
        assert len(names) == body_count
        assert all(name.endswith(".webp" if native_source else ".png") for name in names)


async def test_herosweb_batch_without_terminal_end_keeps_item_pending(
    browser_page: Page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_live_fixture(
        browser_page,
        work_id=WORK_A,
        episode_id=EPISODE_A,
        body_count=10,
        target_position=1,
        ranges=((1, 10),),
        preview_rows=tuple(range(1, 11)),
        viewer_options={"omit_last": True},
    )
    monkeypatch.setattr(adapter_module, "RANGE_PACING_MS", 20)
    catalog, executor, candidate = _make_herosweb_batch(tmp_path)

    with pytest.raises(BatchExecutionError):
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "batch-output",
            library_dir=tmp_path / "Books",
            max_pages=10,
            now=NOW,
        )

    assert catalog.get_item(candidate.item_id).status == "pending"
    assert catalog.list_artifacts(item_id=candidate.item_id, state="present") == []
    assert len(catalog.list_crawl_runs(item_id=candidate.item_id, status="failed")) == 1
    assert not list((tmp_path / "Books").rglob("*.zip"))
    source_before_retry = catalog.get_source(candidate.source_id)
    assert source_before_retry.quota_started_at is None
    assert source_before_retry.access_granted_until is None

    await browser_page.unroute("https://heros-web.com/**")
    await _install_live_fixture(
        browser_page,
        work_id=WORK_A,
        episode_id=EPISODE_A,
        body_count=10,
        target_position=1,
        ranges=((1, 10),),
        preview_rows=tuple(range(1, 11)),
    )
    await executor.execute_candidate(
        browser_page,
        candidate,
        output_root=tmp_path / "batch-output",
        library_dir=tmp_path / "Books",
        max_pages=10,
        now=NOW,
    )

    item_after_retry = catalog.get_item(candidate.item_id)
    assert item_after_retry.status == "completed"
    assert len(catalog.list_artifacts(item_id=candidate.item_id, state="present")) == 1
    assert len(catalog.list_crawl_runs(item_id=candidate.item_id, status="failed")) == 1
    assert len(catalog.list_crawl_runs(item_id=candidate.item_id, status="succeeded")) == 1
    assert len(list((tmp_path / "Books").rglob("*.zip"))) == 1
    source_after_retry = catalog.get_source(candidate.source_id)
    assert source_after_retry.quota_started_at is None
    assert source_after_retry.access_granted_until is None

    watchlist = WatchlistService(tmp_path / "watchlist.yaml")
    policies = SitePolicyRegistry()
    policies.register("herosweb", HeroswebSitePolicy)
    completed_plan = BatchPlanner(catalog, policies, watchlist=watchlist).plan(
        site="herosweb",
        now=NOW,
    )
    assert completed_plan.candidates == []


async def test_herosweb_runner_waits_for_explicit_loading_shell_structure(
    browser_page: Page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    requests = await _install_live_fixture(
        browser_page,
        work_id=WORK_A,
        episode_id=EPISODE_A,
        body_count=2,
        target_position=1,
        ranges=((1, 2),),
        preview_rows=(1, 2),
        viewer_options={"delay_structure_ms": 350},
    )
    monkeypatch.setattr(adapter_module, "RANGE_PACING_MS", 20)
    monkeypatch.setattr(adapter_module, "MAX_VIEWER_SETTLE_SECONDS", 3)
    result = await CrawlerRunner(
        _run_config(tmp_path, EPISODE_A, max_pages=2)
    ).run(browser_page, HeroswebAdapter())

    assert result.stop_state is PageState.END
    assert len(result.pages) == 2
    assert all(page.mime_type == "image/png" for page in result.pages)
    assert requests.count(f"GET /series/{WORK_A}/1") == 1


async def test_herosweb_optional_root_feature_modes_do_not_block_full_capture(
    browser_page: Page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_live_fixture(
        browser_page,
        work_id=WORK_A,
        episode_id=EPISODE_A,
        body_count=2,
        target_position=1,
        ranges=((1, 2),),
        preview_rows=(1, 2),
        viewer_options={"root_feature_flags": False},
    )
    monkeypatch.setattr(adapter_module, "RANGE_PACING_MS", 20)
    result = await CrawlerRunner(
        _run_config(tmp_path, EPISODE_A, max_pages=2)
    ).run(browser_page, HeroswebAdapter())

    assert result.stop_state is PageState.END
    assert len(result.pages) == 2
    assert all(page.mime_type == "image/png" for page in result.pages)


async def test_herosweb_waits_for_observed_required_pr_mode_hydration(
    browser_page: Page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_live_fixture(
        browser_page,
        work_id=WORK_A,
        episode_id=EPISODE_A,
        body_count=2,
        target_position=1,
        ranges=((1, 2),),
        preview_rows=(1, 2),
        viewer_options={"delay_pr_hydration_ms": 350},
    )
    monkeypatch.setattr(adapter_module, "RANGE_PACING_MS", 20)
    monkeypatch.setattr(adapter_module, "MAX_VIEWER_SETTLE_SECONDS", 3)
    monkeypatch.setattr(adapter_module, "POLL_INTERVAL_MS", 20)
    result = await CrawlerRunner(
        _run_config(tmp_path, EPISODE_A, max_pages=2)
    ).run(browser_page, HeroswebAdapter())

    assert result.stop_state is PageState.END
    assert len(result.pages) == 2
    assert all(page.mime_type == "image/png" for page in result.pages)


@pytest.mark.parametrize(
    (
        "work_id",
        "episode_id",
        "body_count",
        "target_position",
        "initial_seek",
        "ranges",
        "preview_rows",
    ),
    [
        (WORK_A, EPISODE_A, 10, 1, 13, ((1, 10),), tuple(range(1, 11))),
        (WORK_A, "abcdef0123456", 10, 1, 13, ((1, 10),), tuple(range(1, 11))),
        (WORK_B, EPISODE_B, 38, 6, 41, ((1, 6),), tuple(range(1, 7))),
    ],
    ids=("A-observed-profile", "A-same-layout-new-episode", "B-observed-profile"),
)
async def test_herosweb_resumed_pr_hydration_waits_then_rewinds_to_native_first_spread(
    browser_page: Page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    work_id: str,
    episode_id: str,
    body_count: int,
    target_position: int,
    initial_seek: int,
    ranges: tuple[tuple[int, int], ...],
    preview_rows: tuple[int, ...],
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_live_fixture(
        browser_page,
        work_id=work_id,
        episode_id=episode_id,
        body_count=body_count,
        target_position=target_position,
        ranges=ranges,
        preview_rows=preview_rows,
        viewer_options={
            "native_source": True,
            "initial_seek": initial_seek,
            "delay_pr_hydration_ms": 800,
            "resume_pr_loading_shape": True,
        },
    )
    monkeypatch.setattr(adapter_module, "RANGE_PACING_MS", 20)
    monkeypatch.setattr(adapter_module, "MAX_VIEWER_SETTLE_SECONDS", 3)
    monkeypatch.setattr(adapter_module, "POLL_INTERVAL_MS", 20)
    monkeypatch.setattr(adapter_module, "STABILITY_INTERVAL_MS", 20)
    result = await CrawlerRunner(
        _run_config(tmp_path, episode_id, max_pages=body_count)
    ).run(browser_page, HeroswebAdapter())

    assert result.stop_state is PageState.END
    assert len(result.pages) == body_count
    assert result.pages[0].identity.source_id == "body-slots:1"
    manifest = json.loads(
        (tmp_path / "crawl-output" / "manifest.json").read_text(encoding="utf-8")
    )
    first_images = manifest["pages"][0]["metadata"]["capture"]["pages"][-1]["images"]
    assert first_images[0]["native_pixels_proven"] is True
    assert first_images[0]["native_proof"]["drawSeekValue"] == body_count + 7
    pair_page = next(
        page
        for page in manifest["pages"]
        if page["identity"]["source_id"] == "body-slots:2,3"
    )
    pair_images = pair_page["metadata"]["capture"]["pages"][-1]["images"]
    assert [image["slot"] for image in pair_images] == [2, 3]
    assert all(image["native_pixels_proven"] is True for image in pair_images)


async def test_herosweb_missing_required_pr_mode_times_out_without_capture(
    browser_page: Page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_live_fixture(
        browser_page,
        work_id=WORK_A,
        episode_id=EPISODE_A,
        body_count=2,
        target_position=1,
        ranges=((1, 2),),
        preview_rows=(1, 2),
        viewer_options={"pr_mode_missing_forever": True},
    )
    monkeypatch.setattr(adapter_module, "RANGE_PACING_MS", 20)
    monkeypatch.setattr(adapter_module, "MAX_VIEWER_SETTLE_SECONDS", 0.4)
    monkeypatch.setattr(adapter_module, "POLL_INTERVAL_MS", 20)

    with pytest.raises(PageChangeTimeoutError, match="Viewer did not settle"):
        await CrawlerRunner(
            _run_config(tmp_path, EPISODE_A, max_pages=2)
        ).run(browser_page, HeroswebAdapter())


@pytest.mark.parametrize(
    ("work_id", "episode_id", "body_count", "target_position", "initial_seek", "ranges"),
    [
        (WORK_A, EPISODE_A, 10, 1, 13, ((1, 10),)),
        (WORK_B, EPISODE_B, 38, 6, 41, ((1, 6),)),
    ],
    ids=("A-observed-profile", "B-observed-profile"),
)
async def test_herosweb_resumed_missing_pr_mode_times_out_without_capture(
    browser_page: Page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    work_id: str,
    episode_id: str,
    body_count: int,
    target_position: int,
    initial_seek: int,
    ranges: tuple[tuple[int, int], ...],
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_live_fixture(
        browser_page,
        work_id=work_id,
        episode_id=episode_id,
        body_count=body_count,
        target_position=target_position,
        ranges=ranges,
        preview_rows=tuple(range(1, target_position + 1)),
        viewer_options={
            "initial_seek": initial_seek,
            "pr_mode_missing_forever": True,
            "resume_pr_loading_shape": True,
        },
    )
    monkeypatch.setattr(adapter_module, "RANGE_PACING_MS", 20)
    monkeypatch.setattr(adapter_module, "MAX_VIEWER_SETTLE_SECONDS", 0.4)
    monkeypatch.setattr(adapter_module, "POLL_INTERVAL_MS", 20)

    with pytest.raises(PageChangeTimeoutError, match="Viewer did not settle"):
        await CrawlerRunner(_run_config(tmp_path, episode_id, max_pages=body_count)).run(
            browser_page, HeroswebAdapter()
        )
    assert not list((tmp_path / "crawl-output").glob("page-*"))


@pytest.mark.parametrize(
    ("work_id", "episode_id", "body_count", "target_position", "initial_seek", "ranges"),
    [
        (WORK_A, EPISODE_A, 10, 1, 13, ((1, 10),)),
        (WORK_B, EPISODE_B, 38, 6, 41, ((1, 6),)),
    ],
    ids=("A-observed-profile", "B-observed-profile"),
)
async def test_herosweb_resumed_pr_wait_rejects_a_second_missing_required_mode(
    browser_page: Page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    work_id: str,
    episode_id: str,
    body_count: int,
    target_position: int,
    initial_seek: int,
    ranges: tuple[tuple[int, int], ...],
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_live_fixture(
        browser_page,
        work_id=work_id,
        episode_id=episode_id,
        body_count=body_count,
        target_position=target_position,
        ranges=ranges,
        preview_rows=tuple(range(1, target_position + 1)),
        viewer_options={
            "initial_seek": initial_seek,
            "pr_mode_missing_forever": True,
            "resume_pr_loading_shape": True,
            "remove_root_mode": "mode-use-glimpse-bottom",
        },
    )
    monkeypatch.setattr(adapter_module, "RANGE_PACING_MS", 20)
    monkeypatch.setattr(adapter_module, "MAX_VIEWER_SETTLE_SECONDS", 3)
    monkeypatch.setattr(adapter_module, "POLL_INTERVAL_MS", 20)

    with pytest.raises(UnknownPageStateError, match="not the observed RTL spread"):
        await CrawlerRunner(_run_config(tmp_path, episode_id, max_pages=body_count)).run(
            browser_page, HeroswebAdapter()
        )
    assert not list((tmp_path / "crawl-output").glob("page-*"))


@pytest.mark.parametrize(
    ("write_url", "expected_host_path"),
    [
        (
            "https://www.google.com/ccm/collect?measurement=synthetic",
            "www.google.com/ccm/collect",
        ),
        (
            "https://ad.doubleclick.net/ccm/s/collect?measurement=synthetic",
            "ad.doubleclick.net/ccm/s/collect",
        ),
        (
            "https://analytics.example/collect?synthetic=1",
            "analytics.example/collect",
        ),
    ],
)
async def test_herosweb_irrelevant_external_post_is_blocked_and_runner_continues(
    browser_page: Page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_url: str,
    expected_host_path: str,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_live_fixture(
        browser_page,
        work_id=WORK_A,
        episode_id=EPISODE_A,
        body_count=10,
        target_position=1,
        ranges=((1, 10),),
        preview_rows=tuple(range(1, 11)),
    )
    monkeypatch.setattr(adapter_module, "RANGE_PACING_MS", 20)
    adapter = HeroswebAdapter()

    class SyntheticRequest:
        def __init__(self) -> None:
            self.url = write_url
            self.method = "POST"

        @staticmethod
        def is_navigation_request() -> bool:
            return False

    class SyntheticRoute:
        request = SyntheticRequest()

        def __init__(self) -> None:
            self.aborted = False
            self.downstream_dispatches = 0

        async def abort(self) -> None:
            self.aborted = True

        async def fallback(self) -> None:
            self.downstream_dispatches += 1

    route = SyntheticRoute()
    observed_guard_state: dict[str, object] = {}
    original_prepare_page = adapter.prepare_page

    async def prepare_with_observed_post(page: Page) -> None:
        await original_prepare_page(page)
        guard = adapter._route_guard
        assert guard is not None
        await guard(route)
        assert route.aborted is True
        assert route.downstream_dispatches == 0
        observed_guard_state["blocked_external_writes"] = list(
            guard.blocked_external_writes
        )
        guard.raise_if_failed()

    adapter.prepare_page = prepare_with_observed_post  # type: ignore[method-assign]
    result = await CrawlerRunner(_run_config(tmp_path, EPISODE_A, max_pages=10)).run(
        browser_page, adapter
    )

    assert result.stop_state is PageState.END
    assert observed_guard_state["blocked_external_writes"] == [expected_host_path]
    debug = await adapter.collect_debug_metadata(browser_page)
    assert debug["blocked_external_writes"] == {
        "count": 1,
        "host_paths": [expected_host_path],
    }


async def test_herosweb_irrelevant_external_iframe_post_is_aborted_without_dispatch(
    browser_page: Page,
) -> None:
    adapter = HeroswebAdapter()
    downstream_trap_hits = 0

    async def downstream_trap(route) -> None:
        nonlocal downstream_trap_hits
        downstream_trap_hits += 1
        await route.abort()

    await browser_page.route(
        "https://analytics.example/iframe-submit**", downstream_trap
    )
    await adapter.prepare_page(browser_page)
    await browser_page.set_content(
        """<!doctype html><html><body>
        <iframe name="measurement"></iframe>
        <form id="measurement-form" method="POST"
              action="https://analytics.example/iframe-submit"
              target="measurement">
          <input name="event" value="synthetic">
        </form>
        <script>document.querySelector('#measurement-form').submit();</script>
        </body></html>""",
        wait_until="domcontentloaded",
    )
    await browser_page.wait_for_timeout(250)

    guard = adapter._route_guard
    assert guard is not None
    assert guard.navigation_frame_role == "subframe"
    assert guard.blocked_external_writes == [
        "analytics.example/iframe-submit"
    ]
    assert guard.unexpected_write is None
    assert guard.navigation_violation is None
    guard.raise_if_failed()
    assert downstream_trap_hits == 0


async def test_herosweb_now_free_requires_fresh_same_work_authentication(
    browser_page: Page, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_live_fixture(
        browser_page,
        work_id=WORK_A,
        episode_id=EPISODE_A,
        body_count=10,
        target_position=1,
        ranges=((1, 10),),
        preview_rows=tuple(range(1, 11)),
        target_label="今なら無料",
        authenticated=False,
    )
    monkeypatch.setattr(adapter_module, "RANGE_PACING_MS", 10)
    with pytest.raises(UnknownPageStateError, match="positively free"):
        await CrawlerRunner(_run_config(tmp_path, EPISODE_A, max_pages=10)).run(
            browser_page, HeroswebAdapter()
        )


async def test_herosweb_now_free_waits_for_current_document_auth_header_hydration(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    requests = await _install_live_fixture(
        browser_page,
        work_id=WORK_B,
        episode_id=EPISODE_B,
        body_count=38,
        target_position=6,
        ranges=((1, 30), (31, 38)),
        preview_rows=tuple(range(1, 6)),
        target_label="\u4eca\u306a\u3089\u7121\u6599",
        authenticated=True,
        auth_header_delay_ms=600,
    )
    monkeypatch.setattr(adapter_module, "RANGE_PACING_MS", 10)
    adapter = HeroswebAdapter()
    adapter._work_id = WORK_B
    adapter._episode_id = EPISODE_B
    await adapter.prepare_page(browser_page)
    auth = adapter_module._CurrentDocumentAuth(browser_page)
    started = asyncio.get_running_loop().time()
    try:
        access_mode = await adapter._prove_current_free_episode(browser_page)
        elapsed = asyncio.get_running_loop().time() - started
        assert access_mode == "free"
        assert adapter._free_proof == {
            "source": "fresh_same_work_listing",
            "work_id": WORK_B,
            "episode_id": EPISODE_B,
            "listing_path": f"/series/{WORK_B}/1",
            "authenticated": True,
            "access_mode": "free",
        }
        assert elapsed >= 0.5
        assert requests.count(f"GET /series/{WORK_B}/1") == 1
        assert requests.count(f"GET /episodes/{EPISODE_B}") == 0
    finally:
        await auth.close()
        await adapter._remove_route_guard(browser_page)
        adapter._remove_preflight_access_listener(browser_page)
        adapter._remove_preflight_access_listener(browser_page)


@pytest.mark.parametrize("access_strategy", ["auto", "direct"])
async def test_herosweb_catalog_work_mismatch_fails_before_work_preflight(
    browser_page: Page, tmp_path: Path, access_strategy: str
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    requests = await _install_live_fixture(
        browser_page,
        work_id=WORK_B,
        episode_id=EPISODE_A,
        body_count=10,
        target_position=1,
        ranges=((1, 10),),
        preview_rows=tuple(range(1, 11)),
    )
    adapter = HeroswebAdapter()
    await adapter.configure_target_identity(f"{WORK_A}:{EPISODE_A}", "expected-work")
    config = _run_config(tmp_path, EPISODE_A, max_pages=10)
    config.access_strategy = access_strategy
    with pytest.raises(UnknownPageStateError, match="Catalog Work"):
        await CrawlerRunner(config).run(browser_page, adapter)
    assert f"GET /series/{WORK_B}" not in requests


async def test_herosweb_rejects_quota_before_navigation(
    browser_page: Page,
) -> None:
    adapter = HeroswebAdapter()
    with pytest.raises(UnsupportedAccessStrategyError):
        await adapter.configure_run(browser_page, "quota")
    await adapter.configure_run(browser_page, "auto")
    with pytest.raises(UnsupportedAccessStrategyError):
        await adapter.configure_quota_resource(browser_page, "ticket")


async def test_herosweb_resume_rewinds_to_first_body_and_waits_for_slow_draw(
    browser_page: Page, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_live_fixture(
        browser_page,
        work_id=WORK_A,
        episode_id=EPISODE_A,
        body_count=10,
        target_position=1,
        ranges=((1, 10),),
        preview_rows=tuple(range(1, 11)),
        viewer_options={"initial_seek": 15, "draw_delay_ms": 700},
    )
    monkeypatch.setattr(adapter_module, "MAX_VIEWER_SETTLE_SECONDS", 3)
    monkeypatch.setattr(adapter_module, "POLL_INTERVAL_MS", 25)
    monkeypatch.setattr(adapter_module, "STABILITY_INTERVAL_MS", 25)
    adapter = HeroswebAdapter()
    result = await CrawlerRunner(_run_config(tmp_path, EPISODE_A, max_pages=10)).run(
        browser_page, adapter
    )
    assert result.stop_state is PageState.END
    assert result.pages[0].identity.source_id == "body-slots:1"
    assert len(result.pages) == 10


async def test_herosweb_existing_first_seek_waits_for_delayed_first_body(
    browser_page: Page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_live_fixture(
        browser_page,
        work_id=WORK_A,
        episode_id=EPISODE_A,
        body_count=10,
        target_position=1,
        ranges=((1, 10),),
        preview_rows=tuple(range(1, 11)),
        viewer_options={"draw_delay_ms": 900},
    )
    monkeypatch.setattr(adapter_module, "MAX_VIEWER_SETTLE_SECONDS", 3)
    monkeypatch.setattr(adapter_module, "POLL_INTERVAL_MS", 25)
    monkeypatch.setattr(adapter_module, "STABILITY_INTERVAL_MS", 25)
    result = await CrawlerRunner(_run_config(tmp_path, EPISODE_A, max_pages=10)).run(
        browser_page, HeroswebAdapter()
    )
    assert result.stop_state is PageState.END
    assert len(result.pages) == 10
    assert result.pages[0].metadata["capture"]["pages"][0]["seek_value"] == 17
    assert Image.open(tmp_path / "crawl-output" / result.pages[0].file).getpixel((50, 50))[:3] == (
        19,
        20,
        30,
    )


async def test_herosweb_wrong_geometry_at_max_seek_fails_closed_within_bound(
    browser_page: Page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_live_fixture(
        browser_page,
        work_id=WORK_A,
        episode_id=EPISODE_A,
        body_count=10,
        target_position=1,
        ranges=((1, 10),),
        preview_rows=tuple(range(1, 11)),
        viewer_options={"first_body_wrong_geometry": True},
    )
    monkeypatch.setattr(adapter_module, "MAX_VIEWER_SETTLE_SECONDS", 0.4)
    monkeypatch.setattr(adapter_module, "POLL_INTERVAL_MS", 20)
    with pytest.raises(UnknownPageStateError, match="first visible body slot"):
        await CrawlerRunner(_run_config(tmp_path, EPISODE_A, max_pages=10)).run(
            browser_page, HeroswebAdapter()
        )


async def test_herosweb_stalled_public_seek_does_not_accept_canvas_epoch_as_next_page(
    browser_page: Page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_live_fixture(
        browser_page,
        work_id=WORK_A,
        episode_id=EPISODE_A,
        body_count=10,
        target_position=1,
        ranges=((1, 10),),
        preview_rows=tuple(range(1, 11)),
        viewer_options={"stall_after_initial": True},
    )
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 350)
    monkeypatch.setattr(adapter_module, "POLL_INTERVAL_MS", 20)
    from screenshot_crawler.core.errors import PageChangeTimeoutError

    with pytest.raises(PageChangeTimeoutError, match="public seek did not settle"):
        await CrawlerRunner(
            _run_config(tmp_path, EPISODE_A, max_pages=10, page_change_timeout_ms=100)
        ).run(browser_page, HeroswebAdapter())


async def test_herosweb_capture_rejects_draw_epoch_change_during_png_serialization(
    browser_page: Page, tmp_path: Path
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_live_fixture(
        browser_page,
        work_id=WORK_A,
        episode_id=EPISODE_A,
        body_count=10,
        target_position=1,
        ranges=((1, 10),),
        preview_rows=tuple(range(1, 11)),
        viewer_options={"draw_on_capture": True},
    )
    with pytest.raises(UnknownPageStateError, match="canvas changed"):
        await CrawlerRunner(_run_config(tmp_path, EPISODE_A, max_pages=10)).run(
            browser_page, HeroswebAdapter()
        )


@pytest.mark.parametrize("clear_on_capture", ["same_size_width", "context_reset"])
async def test_herosweb_capture_rejects_canvas_clear_without_draw_call(
    browser_page: Page,
    tmp_path: Path,
    clear_on_capture: str,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_live_fixture(
        browser_page,
        work_id=WORK_A,
        episode_id=EPISODE_A,
        body_count=10,
        target_position=1,
        ranges=((1, 10),),
        preview_rows=tuple(range(1, 11)),
        viewer_options={"clear_on_capture": clear_on_capture},
    )
    with pytest.raises(UnknownPageStateError, match="canvas changed"):
        await CrawlerRunner(_run_config(tmp_path, EPISODE_A, max_pages=10)).run(
            browser_page, HeroswebAdapter()
        )


@pytest.mark.parametrize(
    ("viewer_options", "message"),
    [
        ({"unknown_role": True}, "wrapper role is unfamiliar"),
        ({"omit_last": True}, "unknown role mode"),
        ({"seek_max_override": 15}, "public seek and wrapper range disagree"),
    ],
)
async def test_herosweb_unknown_layout_and_missing_last_fail_closed(
    browser_page: Page,
    tmp_path: Path,
    viewer_options: dict[str, object],
    message: str,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_live_fixture(
        browser_page,
        work_id=WORK_A,
        episode_id=EPISODE_A,
        body_count=10,
        target_position=1,
        ranges=((1, 10),),
        preview_rows=tuple(range(1, 11)),
        viewer_options=viewer_options,
    )
    with pytest.raises(UnknownPageStateError, match=message):
        await CrawlerRunner(_run_config(tmp_path, EPISODE_A, max_pages=10)).run(
            browser_page, HeroswebAdapter()
        )


@pytest.mark.parametrize("status", [403, 429])
async def test_herosweb_preflight_access_stop_prevents_next_range_navigation(
    browser_page: Page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    requests = await _install_live_fixture(
        browser_page,
        work_id=WORK_B,
        episode_id=EPISODE_B,
        body_count=38,
        target_position=6,
        ranges=((1, 30), (31, 38)),
        preview_rows=tuple(range(1, 6)),
        fatal_subresource_status=status,
    )
    monkeypatch.setattr(adapter_module, "RANGE_PACING_MS", 10)
    with pytest.raises(AccessStopError) as exc_info:
        await CrawlerRunner(_run_config(tmp_path, EPISODE_B, max_pages=38)).run(
            browser_page, HeroswebAdapter()
        )
    assert exc_info.value.status == status
    assert f"GET /series/{WORK_B}/1" not in requests


async def test_herosweb_redirected_document_is_aborted_before_followup_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakePage:
        main_frame = object()

    class FakeRequest:
        url = f"{BASE}/episodes/{EPISODE_A}"
        method = "GET"
        frame = FakePage.main_frame
        headers: ClassVar[dict[str, str]] = {"cookie": "session=synthetic"}

        @staticmethod
        def is_navigation_request() -> bool:
            return True

    class FakeResponse:
        def __init__(self) -> None:
            self.status = 302
            self.disposed = False

        async def dispose(self):
            self.disposed = True

    class FakeRoute:
        def __init__(self) -> None:
            self.request = FakeRequest()
            self.response = FakeResponse()
            self.aborted = False
            self.fallback_called = False
            self.fetched_with: dict[str, object] | None = None

        async def fetch(self, **kwargs):
            self.fetched_with = kwargs
            return self.response

        async def abort(self):
            self.aborted = True

        async def fallback(self):
            self.fallback_called = True

        async def fulfill(self, **kwargs):
            raise AssertionError(f"redirect response should not be fulfilled: {kwargs}")

    monkeypatch.setattr(
        adapter_module,
        "_fetch_main_frame_response_without_redirect",
        _PRODUCTION_MAIN_FRAME_FETCH,
    )
    guard = adapter_module.HeroswebEpisodeRouteGuard(FakePage(), episode_id=EPISODE_A)
    guard.allow_navigation(f"{BASE}/episodes/{EPISODE_A}")
    route = FakeRoute()
    await guard(route)
    assert route.aborted is True
    assert route.fallback_called is False
    assert route.fetched_with == {
        "max_redirects": 0,
        "max_retries": 0,
        "timeout": adapter_module.PAGE_CHANGE_TIMEOUT_MS,
    }
    assert route.request.headers == {"cookie": "session=synthetic"}
    assert route.response.disposed is True
    assert guard.navigation_violation == f"GET heros-web.com/episodes/{EPISODE_A} redirect 302"


async def test_herosweb_runner_blocks_real_redirect_before_downstream_dispatch(
    browser_page: Page,
    tmp_path: Path,
) -> None:
    page = browser_page
    await page.set_viewport_size({"width": 1906, "height": 986})
    downstream_routes: list[str] = []
    await _install_live_fixture(
        page,
        work_id=WORK_A,
        episode_id=EPISODE_A,
        body_count=10,
        target_position=1,
        ranges=((1, 10),),
        preview_rows=tuple(range(1, 11)),
    )

    async def redirect_work_listing(route) -> None:
        path = urlsplit(route.request.url).path
        if path == f"/series/{WORK_A}":
            await route.fulfill(
                status=302,
                headers={"location": f"{BASE}/series/{WORK_B}"},
                body="",
            )
            return
        downstream_routes.append(path)
        await route.fallback()

    await page.route("https://heros-web.com/**", redirect_work_listing)
    with pytest.raises(UnknownPageStateError):
        await CrawlerRunner(_run_config(tmp_path, EPISODE_A, max_pages=10)).run(
            page, HeroswebAdapter()
        )
    assert f"/series/{WORK_B}" not in downstream_routes


@pytest.mark.parametrize("status", [200, 403, 429])
async def test_herosweb_main_document_guard_forwards_nonredirect_status_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    class FakePage:
        main_frame = object()

    class FakeRequest:
        url = f"{BASE}/episodes/{EPISODE_A}"
        method = "GET"
        frame = FakePage.main_frame
        headers: ClassVar[dict[str, str]] = {"cookie": "session=synthetic"}

        @staticmethod
        def is_navigation_request() -> bool:
            return True

    class FakeResponse:
        def __init__(self, response_status: int) -> None:
            self.status = response_status
            self.disposed = False

        async def dispose(self):
            self.disposed = True

    class FakeRoute:
        request = FakeRequest()
        aborted = False
        fallback_called = False

        def __init__(self) -> None:
            self.response = FakeResponse(status)
            self.fetched_with: dict[str, object] | None = None
            self.fulfilled_with: dict[str, object] | None = None

        async def fetch(self, **kwargs):
            self.fetched_with = kwargs
            return self.response

        async def abort(self):
            self.aborted = True

        async def fallback(self):
            self.fallback_called = True

        async def fulfill(self, **kwargs):
            self.fulfilled_with = kwargs

    monkeypatch.setattr(
        adapter_module,
        "_fetch_main_frame_response_without_redirect",
        _PRODUCTION_MAIN_FRAME_FETCH,
    )
    guard = adapter_module.HeroswebEpisodeRouteGuard(FakePage(), episode_id=EPISODE_A)
    guard.allow_navigation(f"{BASE}/episodes/{EPISODE_A}")
    route = FakeRoute()
    await guard(route)
    assert route.aborted is False
    assert route.fallback_called is False
    assert route.fulfilled_with == {"response": route.response}
    assert route.response.disposed is True
    assert route.fetched_with == {
        "max_redirects": 0,
        "max_retries": 0,
        "timeout": adapter_module.PAGE_CHANGE_TIMEOUT_MS,
    }
    assert guard.navigation_violation is None


async def test_herosweb_guard_blocks_real_local_http_redirect_before_target_request(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state: dict[str, object] = {"redirect": 0, "trap": 0, "cookie": ""}

    async def handle_http(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        request_line = await reader.readline()
        headers: list[str] = []
        while line := await reader.readline():
            if line in {b"\r\n", b"\n"}:
                break
            headers.append(line.decode("latin1").strip())
        path = request_line.decode("latin1").split(" ")[1]
        state["cookie"] = next(
            (line for line in headers if line.lower().startswith("cookie:")), ""
        )
        if path == "/redirect":
            state["redirect"] = int(state["redirect"]) + 1
            response = (
                "HTTP/1.1 302 Found\r\nLocation: /trap\r\n"
                "Content-Length: 0\r\nConnection: close\r\n\r\n"
            )
        elif path == "/trap":
            state["trap"] = int(state["trap"]) + 1
            response = (
                "HTTP/1.1 200 OK\r\nContent-Length: 4\r\n"
                "Connection: close\r\n\r\ntrap"
            )
        else:
            response = (
                "HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n"
                "Connection: close\r\n\r\n"
            )
        writer.write(response.encode("ascii"))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle_http, "127.0.0.1", 0)
    local_port = server.sockets[0].getsockname()[1]
    local_base = f"http://127.0.0.1:{local_port}"
    await browser_page.context.add_cookies(
        [{"name": "synthetic", "value": "cookie", "url": local_base}]
    )

    async def local_transport(route):
        return await route.fetch(
            url=f"{local_base}/redirect",
            max_redirects=0,
            max_retries=0,
            timeout=adapter_module.PAGE_CHANGE_TIMEOUT_MS,
        )

    monkeypatch.setattr(
        adapter_module, "_fetch_main_frame_response_without_redirect", local_transport
    )
    guard = adapter_module.HeroswebEpisodeRouteGuard(browser_page, episode_id=EPISODE_A)
    target_url = f"{BASE}/episodes/{EPISODE_A}"
    guard.allow_navigation(target_url)
    await browser_page.route("https://heros-web.com/**", guard)
    try:
        with pytest.raises(PlaywrightError):
            await browser_page.goto(target_url, wait_until="commit", timeout=5_000)
        assert state["redirect"] == 1
        assert state["trap"] == 0
        assert state["cookie"] == "cookie: synthetic=cookie"
        assert guard.navigation_violation == (
            f"GET heros-web.com/episodes/{EPISODE_A} redirect 302"
        )
    finally:
        await browser_page.unroute("https://heros-web.com/**", guard)
        server.close()
        await server.wait_closed()


@pytest.mark.parametrize("status", [200, 403, 429])
async def test_herosweb_forwarded_status_reaches_page_and_access_guard_once(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    async def handle_http(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readline()
        while line := await reader.readline():
            if line in {b"\r\n", b"\n"}:
                break
        body = b"<html><body>synthetic response</body></html>"
        response = (
            f"HTTP/1.1 {status} Synthetic\r\nContent-Length: {len(body)}\r\n"
            "Content-Type: text/html\r\nConnection: close\r\n\r\n"
        ).encode("ascii") + body
        writer.write(response)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle_http, "127.0.0.1", 0)
    local_port = server.sockets[0].getsockname()[1]
    local_url = f"http://127.0.0.1:{local_port}/document"

    async def local_transport(route):
        return await route.fetch(
            url=local_url,
            max_redirects=0,
            max_retries=0,
            timeout=adapter_module.PAGE_CHANGE_TIMEOUT_MS,
        )

    monkeypatch.setattr(
        adapter_module, "_fetch_main_frame_response_without_redirect", local_transport
    )
    route_guard = adapter_module.HeroswebEpisodeRouteGuard(
        browser_page, episode_id=EPISODE_A
    )
    target_url = f"{BASE}/episodes/{EPISODE_A}"
    route_guard.allow_navigation(target_url)
    access_events = []
    access_guard = AccessGuard.from_profile(
        site="herosweb",
        profile=herosweb_access_profile(),
        stop_on_http_403=True,
        stop_on_http_429=True,
        stop_on_challenge=True,
        stop_on_captcha=True,
        event_sink=access_events.append,
    )
    access_guard.start(browser_page)
    page_responses = []

    def record_response(response) -> None:
        page_responses.append(response)

    browser_page.on("response", record_response)
    await browser_page.route("https://heros-web.com/**", route_guard)
    try:
        response = await browser_page.goto(
            target_url, wait_until="domcontentloaded", timeout=5_000
        )
        assert response is not None and response.status == status
        assert [item.status for item in page_responses if item.url == target_url] == [status]
        matching_events = [
            event
            for event in access_events
            if event.event_type == "request" and event.url == target_url
        ]
        assert len(matching_events) == 1
        assert route_guard.navigation_violation is None
        if status in {403, 429}:
            with pytest.raises(AccessStopError) as exc_info:
                access_guard.raise_if_stopped()
            assert exc_info.value.status == status
        else:
            access_guard.raise_if_stopped()
    finally:
        browser_page.remove_listener("response", record_response)
        await access_guard.close()
        await browser_page.unroute("https://heros-web.com/**", route_guard)
        server.close()
        await server.wait_closed()


async def test_herosweb_main_document_fetch_failure_is_sanitized_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakePage:
        main_frame = object()

    class FakeRequest:
        url = f"{BASE}/episodes/{EPISODE_A}"
        method = "GET"
        frame = FakePage.main_frame

        @staticmethod
        def is_navigation_request() -> bool:
            return True

    class FakeRoute:
        request = FakeRequest()
        aborted = False
        fallback_called = False

        async def fetch(self, **_kwargs):
            raise PlaywrightTimeoutError("Timeout: leaked-cookie=synthetic")

        async def abort(self):
            self.aborted = True

        async def fallback(self):
            self.fallback_called = True

    monkeypatch.setattr(
        adapter_module,
        "_fetch_main_frame_response_without_redirect",
        _PRODUCTION_MAIN_FRAME_FETCH,
    )
    guard = adapter_module.HeroswebEpisodeRouteGuard(FakePage(), episode_id=EPISODE_A)
    guard.allow_navigation(FakeRequest.url)
    route = FakeRoute()
    await guard(route)
    assert route.aborted is True
    assert route.fallback_called is False
    assert guard.navigation_violation == (
        f"GET heros-web.com/episodes/{EPISODE_A} document fetch timed out"
    )
    assert "leaked-cookie" not in guard.navigation_violation


async def test_herosweb_response_cleanup_failure_stops_before_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakePage:
        main_frame = object()

    class FakeRequest:
        url = f"{BASE}/episodes/{EPISODE_A}"
        method = "GET"
        frame = FakePage.main_frame

        @staticmethod
        def is_navigation_request() -> bool:
            return True

    class FakeResponse:
        status = 200

        async def dispose(self):
            raise PlaywrightError("cleanup leaked-cookie=synthetic")

    class FakeRoute:
        request = FakeRequest()

        def __init__(self) -> None:
            self.response = FakeResponse()
            self.aborted = False
            self.fulfilled = False

        async def fetch(self, **_kwargs):
            return self.response

        async def abort(self):
            self.aborted = True

        async def fallback(self):
            raise AssertionError("failed cleanup must not fall back")

        async def fulfill(self, *, response):
            assert response is self.response
            self.fulfilled = True

    monkeypatch.setattr(
        adapter_module,
        "_fetch_main_frame_response_without_redirect",
        _PRODUCTION_MAIN_FRAME_FETCH,
    )
    guard = adapter_module.HeroswebEpisodeRouteGuard(FakePage(), episode_id=EPISODE_A)
    guard.allow_navigation(FakeRequest.url)
    route = FakeRoute()
    await guard(route)
    assert route.fulfilled is True
    assert route.aborted is False
    assert guard.navigation_violation == (
        f"GET heros-web.com/episodes/{EPISODE_A} document cleanup failed"
    )
    assert "leaked-cookie" not in guard.navigation_violation


async def test_herosweb_body_locator_screenshot_is_png_fallback_only_for_exact_canvas(
    browser_page: Page, tmp_path: Path
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_live_fixture(
        browser_page,
        work_id=WORK_A,
        episode_id=EPISODE_A,
        body_count=10,
        target_position=1,
        ranges=((1, 10),),
        preview_rows=tuple(range(1, 11)),
        viewer_options={"to_data_url_fails": True},
    )
    adapter = HeroswebAdapter()
    result = await CrawlerRunner(_run_config(tmp_path, EPISODE_A, max_pages=10)).run(
        browser_page, adapter
    )
    assert result.stop_state is PageState.END
    output_dir = tmp_path / "crawl-output"
    assert [(page.width, page.height, page.mime_type) for page in result.pages] == [
        (624, 886, "image/png")
    ] * 10
    assert all(
        Image.open(output_dir / page.file).getpixel((50, 50))[:3]
        == (((index + 1) * 19) % 255, 20, 30)
        for index, page in enumerate(result.pages)
    )
    assert all(
        page.metadata["capture"]["pages"][-1]["images"][0]["mode"]
        == "canvas_locator_screenshot_png"
        for page in result.pages
    )


@pytest.mark.parametrize("catalog_direct", [False, True])
async def test_herosweb_direct_reader_gate_blocks_before_png_capture(
    browser_page: Page, tmp_path: Path, catalog_direct: bool
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    requests = await _install_live_fixture(
        browser_page,
        work_id=WORK_A,
        episode_id=EPISODE_A,
        body_count=10,
        target_position=1,
        ranges=((1, 10),),
        preview_rows=tuple(range(1, 11)),
        viewer_options={"access_gate": True},
    )
    adapter = HeroswebAdapter()
    config = _run_config(tmp_path, EPISODE_A, max_pages=10)
    if catalog_direct:
        await adapter.configure_target_identity(f"{WORK_A}:{EPISODE_A}", "expected-work")
        config.access_strategy = "direct"
    with pytest.raises(UnknownPageStateError, match="access gate"):
        await CrawlerRunner(config).run(browser_page, adapter)
    if catalog_direct:
        assert requests == [f"GET /episodes/{EPISODE_A}"]
    assert not list((tmp_path / "crawl-output").glob("page-*"))


@pytest.mark.parametrize(
    ("post_url", "expected_blocked_path"),
    [
        (
            "https://heros-web.com/api/unapproved",
            "heros-web.com/api/unapproved",
        ),
        (
            "https://comicsviewer.heros-web.com/api/unapproved",
            "comicsviewer.heros-web.com/api/unapproved",
        ),
    ],
)
async def test_herosweb_unknown_post_remains_blocked_and_fatal(
    browser_page: Page,
    tmp_path: Path,
    post_url: str,
    expected_blocked_path: str,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_live_fixture(
        browser_page,
        work_id=WORK_A,
        episode_id=EPISODE_A,
        body_count=10,
        target_position=1,
        ranges=((1, 10),),
        preview_rows=tuple(range(1, 11)),
        viewer_options={"post_url": post_url},
    )
    downstream_trap_hits = 0

    async def downstream_trap(route) -> None:
        nonlocal downstream_trap_hits
        downstream_trap_hits += 1
        await route.abort()

    await browser_page.route(f"{post_url.split('?')[0]}**", downstream_trap)
    adapter = HeroswebAdapter()
    with pytest.raises(UnknownPageStateError, match="blocked an unapproved request write"):
        await CrawlerRunner(_run_config(tmp_path, EPISODE_A, max_pages=10)).run(
            browser_page, adapter
        )
    assert adapter._route_guard is not None
    assert adapter._route_guard.unexpected_write == expected_blocked_path
    assert downstream_trap_hits == 0
    assert not list((tmp_path / "crawl-output").glob("page-*.png"))


@pytest.mark.parametrize(
    ("post_episode_id", "expect_end"),
    [(EPISODE_A, True), ("0000000000000", False)],
)
async def test_herosweb_last_body_read_completed_is_blocked_without_dispatch(
    browser_page: Page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    post_episode_id: str,
    expect_end: bool,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    post_url = f"{BASE}/api/episodes/{post_episode_id}/readCompleted"
    await _install_live_fixture(
        browser_page,
        work_id=WORK_A,
        episode_id=EPISODE_A,
        body_count=10,
        target_position=1,
        ranges=((1, 10),),
        preview_rows=tuple(range(1, 11)),
        viewer_options={"post_url": post_url, "post_on_seek": 7},
    )
    monkeypatch.setattr(adapter_module, "RANGE_PACING_MS", 20)
    downstream_trap_hits = 0

    async def downstream_trap(route) -> None:
        nonlocal downstream_trap_hits
        downstream_trap_hits += 1
        await route.abort()

    await browser_page.route(f"{post_url.split('?')[0]}**", downstream_trap)
    adapter = HeroswebAdapter()
    observed_guard: dict[str, object] = {}
    remove_route_guard = adapter._remove_route_guard

    async def preserve_guard_summary(page: Page) -> None:
        guard = adapter._route_guard
        if guard is not None:
            observed_guard["blocked_read_completed"] = list(guard.blocked_read_completed)
            observed_guard["unexpected_write"] = guard.unexpected_write
        await remove_route_guard(page)

    adapter._remove_route_guard = preserve_guard_summary  # type: ignore[method-assign]
    runner = CrawlerRunner(_run_config(tmp_path, EPISODE_A, max_pages=10))
    if expect_end:
        result = await runner.run(browser_page, adapter)
        assert result.stop_state is PageState.END
        assert len(result.pages) == 10
        assert observed_guard["blocked_read_completed"] == [
            "/api/episodes/4fe9831c6f540/readCompleted"
        ]
        assert observed_guard["unexpected_write"] is None
    else:
        with pytest.raises(
            UnknownPageStateError, match="blocked an unapproved request write"
        ):
            await runner.run(browser_page, adapter)
        assert adapter._route_guard is not None
        assert adapter._route_guard.unexpected_write == (
            "heros-web.com/api/episodes/0000000000000/readCompleted"
        )
        assert not list((tmp_path / "crawl-output").glob("page-0010.png"))
    assert downstream_trap_hits == 0
