from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from PIL import Image
from playwright.async_api import ElementHandle
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from screenshot_crawler.batch import (
    BatchExecutor,
    BatchInterruptedError,
    BatchPlanner,
    CandidateExecutionError,
)
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
from screenshot_crawler.core.packaging import package_crawl_output
from screenshot_crawler.core.runner import CrawlerRunner
from screenshot_crawler.core.state import PageState
from screenshot_crawler.runtime_settings import SiteRuntimeSettings
from screenshot_crawler.site_adapters.registry import AdapterRegistry
from screenshot_crawler.site_adapters.younganimal import adapter as younganimal_adapter_module
from screenshot_crawler.site_adapters.younganimal.adapter import YounganimalAdapter
from screenshot_crawler.site_policies import SitePolicyRegistry, YounganimalSitePolicy

pytestmark = pytest.mark.asyncio(loop_scope="module")

BASE = "https://younganimal.com"
WORK_ID = "aee4fa742b0fe"
EPISODE_ID = "55889b8a851cb"
WORK_URL = f"{BASE}/series/{WORK_ID}"
EPISODE_URL = f"{BASE}/episodes/{EPISODE_ID}"
PAGE_WIDTH = 984
PAGE_HEIGHT = 1329
NOW = datetime(2026, 10, 11, 12, 0, tzinfo=JST)


def _episode_id(position: int) -> str:
    if position == 1:
        return EPISODE_ID
    return f"{position:013x}"


def _row(
    position: int, *, selected: bool = False, label: str | None = None
) -> str:
    episode_id = _episode_id(position)
    label = label if label is not None else ("無料" if selected else "今なら無料")
    return f'''<div class="series-eplist-item">
      <a class="series-eplist-item-link" href="/episodes/{episode_id}">
        <span class="series-eplist-item-h-text">Fixture part {position}</span>
        <span class="series-eplist-item-access-text">{label}</span>
      </a>
    </div>'''


def _listing(*, selected_range: bool, target_label: str = "無料", rental: bool = False) -> str:
    href = WORK_URL if selected_range else f"{WORK_URL}/1"
    rows = "".join(
        _row(
            position,
            selected=position == 1,
            label=target_label if position == 1 else None,
        )
        for position in range(1, 17)
    )
    user_rows = _row(1, label="レンタル中 閲覧期限 14日+23時間") if rental else ""
    return f'''<div class="series-eplist-main">
      <div class="series-eplist" data-e2e="epList">{rows}</div>
      <div class="series-eplist mode-user" data-e2e="epListUser">{user_rows}</div>
      <nav class="series-sort">
        <a class="series-sort-link" href="{WORK_URL}/new">最新話から</a>
        <a class="series-sort-link" href="{href}">1-16</a>
      </nav>
    </div>'''


def _viewer_html(
    initial_seek: int = 11,
    native_source_slots: tuple[int, ...] = (),
    clip_slots: tuple[int, ...] = (),
    no_top_pr: bool = False,
    standard15_body: bool = False,
    standard_body_count: int | None = None,
    odd_body_count: int | None = None,
    top_empty_no_ci_body_count: int | None = None,
    pr_tail_body_count: int | None = None,
    tail_pr_count: int = 1,
) -> str:
    wrappers: list[str] = []
    odd_profile = standard15_body or odd_body_count is not None
    no_ci_profile = top_empty_no_ci_body_count is not None
    pr_tail_profile = pr_tail_body_count is not None
    body_last = (
        pr_tail_body_count if pr_tail_profile else
        top_empty_no_ci_body_count if no_ci_profile else
        odd_body_count if odd_body_count is not None else
        15 if standard15_body else
        standard_body_count if standard_body_count is not None else 16
    )
    ci_index = body_last + 1
    wrapper_count = ci_index + (tail_pr_count + 3 if pr_tail_profile else 4 if no_ci_profile else 5)
    seek_max = wrapper_count if body_last == 1 or odd_profile or no_ci_profile or pr_tail_profile else wrapper_count - 1
    pr_tail_odd = pr_tail_profile and body_last % 2 == 1
    if pr_tail_odd:
        seek_max -= 1
    ci_seek = tail_pr_count + (2 if pr_tail_odd else 4) if pr_tail_profile else 5
    for index in range(wrapper_count):
        if index == 0:
            classes = (
                "mode-empty -cv-page" if no_top_pr or no_ci_profile
                else "mode-empty mode-pr mode-top-pr -cv-page"
            )
            body = ""
        elif index <= body_last:
            classes = "-cv-page mode-loaded mode-rendered"
            shade = (index * 13) % 255
            if index in native_source_slots:
                clip_prefix = (
                    'x.save();x.rect(0,0,c.width,c.height);x.clip();'
                    if index in clip_slots else ""
                )
                clip_suffix = "x.restore();" if index in clip_slots else ""
                draw_script = (
                    f'window.__yaRenderers=window.__yaRenderers||{{}};'
                    f'window.__yaSources=window.__yaSources||{{}};'
                    f'const s=document.createElement("canvas");s.width=47;s.height=61;'
                    f'const sx=s.getContext("2d");sx.fillStyle="rgb({shade},40,90)";'
                    f'sx.fillRect(0,0,s.width,s.height);window.__yaSources[{index}]=s;'
                    f'window.__yaRenderers[{index}]=()=>{{{clip_prefix}'
                    + 'x.clearRect(0,0,c.width,c.height);'
                    + f'x.drawImage(s,0,0,s.width,s.height,0,0,c.width,c.height);{clip_suffix}}};'
                )
            else:
                draw_script = (
                    f'window.__yaRenderers=window.__yaRenderers||{{}};'
                    f'window.__yaRenderers[{index}]=()=>{{x.fillStyle="rgb({shade},40,90)";'
                    'x.fillRect(0,0,c.width,c.height);};'
                )
            body = (
                f'<div class="-cv-page-canvas"><canvas width="{PAGE_WIDTH}" '
                f'height="{PAGE_HEIGHT}" data-slot="{index}" '
                f'style="position:absolute;left:145px;top:0;width:656px;height:886px"></canvas></div>'
                f'<script>(function(){{const c=document.currentScript.previousElementSibling.querySelector("canvas");'
                f'const x=c.getContext("2d");{draw_script}window.__yaRenderers[{index}]();}})()</script>'
            )
        elif not no_ci_profile and index == ci_index:
            classes = "mode-ci -cv-page"
            body = (
                '<div class="-cv-ci -cv-page-content">'
                '<div class="-cv-ci-content" data-ya-scroll-widget="fixture">'
                '<span class="-cv-ci-item"></span><span class="-cv-ci-item"></span>'
                '</div></div>'
            )
        elif index in ({ci_index, ci_index + 1} if no_ci_profile else set(range(ci_index + 1, ci_index + tail_pr_count + 1)) if pr_tail_profile else {ci_index + 1, ci_index + 2}):
            classes = "mode-empty mode-pr -cv-page"
            body = ""
        elif index == ci_index + (tail_pr_count + 1 if pr_tail_profile else 2 if no_ci_profile else 3):
            classes = "mode-good -cv-page"
            body = ""
        else:
            classes = "mode-last -cv-page"
            body = ""
        is_last = index == wrapper_count - 1
        marker_id = ' id="xCVLastPage"' if is_last and not no_ci_profile else ""
        if is_last and no_ci_profile:
            body = '<span id="xCVLastPage" style="position:absolute;left:50%;top:50%;width:1px;height:1px"></span>'
        wrappers.append(
            f'<div class="{classes}"{marker_id} data-slot="{index}">{body}</div>'
        )
    wrappers_html = "".join(wrappers)
    root_flag = "mode-has-top-emptypage" if no_top_pr or no_ci_profile else ""
    odd_flags = (
        "mode-has-pr mode-has-comic-info mode-has-good-page" if odd_profile or pr_tail_profile or body_last in {1, 2} else
        "mode-has-pr mode-has-good-page" if no_ci_profile else ""
    )
    terminal_markers = "viewer.classList.add('mode-last-page');" if body_last == 1 or odd_profile or no_ci_profile or (pr_tail_profile and not pr_tail_odd) else (
        "viewer.classList.add('mode-pr-page','mode-last-page');"
    )
    return f'''<section id="comici-viewer" class="-cv mode-lang-ja mode-h mode-dir-rtl mode-nav-dir-rtl mode-spread {root_flag} {odd_flags}">
      <input id="xCVSeekBar" type="range" min="1" max="{seek_max}" step="2" value="{initial_seek}">
      <div id="xCVPages" class="-cv-pages">{wrappers_html}</div>
    </section>
    <style>
      html,body {{ margin:0; width:1906px; height:986px; overflow:hidden; }}
      #comici-viewer {{ position:{"fixed" if pr_tail_profile or body_last in {1, 2} else "relative"}; top:0; width:1906px; height:986px; overflow:hidden; }}
      #xCVSeekBar {{ position:absolute; top:900px; }}
      #xCVPages {{ position:absolute; left:0; top:0; width:1906px; height:886px; }}
      .-cv-page {{ position:absolute; top:0; width:946px; height:886px; }}
      .-cv-page-canvas {{ position:absolute; inset:0; }}
      .-cv-ci.-cv-page-content {{ position:absolute; left:0; top:0; width:628px; height:886px; }}
      .-cv-ci-content {{ position:absolute; left:392px; top:160px; width:450px; height:565px; }}
      canvas {{ display:block; }}
    </style>
    <script>
      (() => {{
        const viewer = document.querySelector('#comici-viewer');
        const seek = document.querySelector('#xCVSeekBar');
        const pages = document.querySelector('#xCVPages');
        const wrappers = [...pages.children];
        const body = wrappers.slice(1, {body_last + 1});
        const update = () => {{
          const value = Number(seek.value);
          const focus = Number(seek.max) - value + 1;
          const positionWrappers = () => wrappers.forEach((wrapper, index) => {{
            wrapper.style.left = `${{945 + (focus - index - 1) * 946}}px`;
          }});
          if (!{str(odd_profile and no_top_pr).lower()}) positionWrappers();
          viewer.classList.remove('mode-first-page','mode-top-pr-page','mode-pr-page','mode-ci-page','mode-last-page');
          if (value === Number(seek.max)) {{
            viewer.classList.add('mode-first-page');
            if (!{str(no_top_pr or no_ci_profile).lower()}) viewer.classList.add('mode-top-pr-page');
          }}
          if (value === {ci_seek}) viewer.classList.add({"'mode-pr-page'" if no_ci_profile else "'mode-pr-page','mode-ci-page'"});
          if (value > 1 && value < {ci_seek}) viewer.classList.add('mode-pr-page');
          if (value === 1) {terminal_markers}
          body.forEach(wrapper => {{
            wrapper.classList.add('mode-loaded','mode-rendered');
          }});
          const active = [focus - 1, focus].filter(slot => slot >= 1 && slot <= body.length);
          active.forEach(slot => window.__yaRenderers?.[slot]?.());
          if ({str(odd_profile and no_top_pr).lower()}) positionWrappers();
        }};
        seek.addEventListener('input', update);
        seek.addEventListener('change', update);
        update();
      }})();
    </script>'''


def _episode_html(
    *,
    native_source_slots: tuple[int, ...] = (),
    clip_slots: tuple[int, ...] = (),
    target_label: str = "無料",
    rental: bool = False,
    no_top_pr: bool = False,
    standard15_body: bool = False,
    standard_body_count: int | None = None,
    odd_body_count: int | None = None,
    top_empty_no_ci_body_count: int | None = None,
    pr_tail_body_count: int | None = None,
    tail_pr_count: int = 1,
    ticket_gate: bool = False,
    ticket_control_missing: bool = False,
) -> str:
    gate = ""
    if ticket_gate:
        gate = """<div id="ticket-gate" class="ep-main-content mode-charge">
          <div class="ep-charge">
            <div class="ep-charge-act"><button class="ep-charge-act-btn mode-waitfree"
              data-e2e="wfRead">待つと無料で読む</button></div>
            <div class="ep-charge-act"><button class="ep-charge-act-btn mode-alt"
              data-e2e="epBulkRentTrig">この話をレンタル</button></div>
          </div>
        </div>"""
        if ticket_control_missing:
            gate = re.sub(
                r'<button(?=[^>]*\bdata-e2e="wfRead")[^>]*>.*?</button>',
                "",
                gate,
                count=1,
                flags=re.DOTALL,
            )
    elif target_label != "無料" and not rental:
        gate = (
            f'<div class="ep-main-content mode-charge"><div class="ep-charge">'
            f"<button>{target_label}</button></div></div>"
        )
    return f'''<!doctype html><html><head><meta charset="utf-8"><title>Fixture viewer</title></head>
      <body><div id="xHeader"><a class="ep-h-main-h-series" href="{WORK_URL}">Fixture Work</a></div>
      {gate}
      {"" if no_top_pr else _listing(selected_range=True, target_label=target_label, rental=rental)}
      {_viewer_html(native_source_slots=native_source_slots, clip_slots=clip_slots, no_top_pr=no_top_pr,
                    standard15_body=standard15_body, standard_body_count=standard_body_count,
                    odd_body_count=odd_body_count,
                    top_empty_no_ci_body_count=top_empty_no_ci_body_count,
                    pr_tail_body_count=pr_tail_body_count, tail_pr_count=tail_pr_count)}</body></html>'''


def _top_empty_viewer_html(
    *,
    native_source_slots: tuple[int, ...] = (),
    initial_nav_open: bool = False,
    initial_splash_count: int = 0,
    body_count: int = 44,
    tail_pr_count: int = 2,
    initial_seek: int | None = None,
) -> str:
    wrappers: list[str] = []
    ci_slot = body_count + 2
    wrapper_count = body_count + tail_pr_count + 5
    maximum = wrapper_count if wrapper_count % 2 else wrapper_count - 1
    for index in range(wrapper_count):
        if index == 0:
            classes, body = "mode-empty mode-pr mode-top-pr -cv-page", ""
        elif index == 1:
            classes, body = "mode-empty -cv-page", ""
        elif index < ci_slot:
            classes = "-cv-page mode-loaded mode-rendered"
            shade = (index * 13) % 255
            if index in native_source_slots:
                draw = (
                    f'window.__yaRenderers[{index}]=()=>{{'
                    f'x.drawImage(s,0,0,s.width,s.height,0,0,c.width,c.height);}};'
                )
                source = (
                    f'const s=document.createElement("canvas");s.width=47;s.height=61;'
                    f'const sx=s.getContext("2d");sx.fillStyle="rgb({shade},40,90)";'
                    f'sx.fillRect(0,0,s.width,s.height);window.__yaSources=window.__yaSources||{{}};'
                    f'window.__yaSources[{index}]=s;'
                )
            else:
                source = ""
                draw = (
                    f'window.__yaRenderers[{index}]=()=>{{x.fillStyle="rgb({shade},40,90)";'
                    'x.fillRect(0,0,c.width,c.height);};'
                )
            body = (
                '<div class="-cv-page-content"><div class="-cv-page-canvas"><canvas width="942" height="1329" '
                f'data-slot="{index}" style="position:absolute;left:159px;top:0;'
                'width:628px;height:886px"></canvas></div></div>'
                '<script>(function(){const c=document.currentScript.previousElementSibling.querySelector("canvas");'
                'const x=c.getContext("2d");window.__yaRenderers=window.__yaRenderers||{};'
                f'{source}{draw}window.__yaRenderers[{index}]();}})()</script>'
            )
        elif index == ci_slot:
            classes = "mode-ci -cv-page"
            body = (
                '<div class="-cv-ci -cv-page-content">'
                '<div class="-cv-ci-content" data-ya-scroll-widget="fixture">'
                '<span class="-cv-ci-item"></span><span class="-cv-ci-item"></span>'
                '<span class="-cv-ci-item"></span><span class="-cv-ci-item"></span>'
                '</div></div>'
            )
        elif index in range(ci_slot + 1, ci_slot + tail_pr_count + 1):
            classes, body = "mode-empty mode-pr -cv-page", ""
        elif index == ci_slot + tail_pr_count + 1:
            classes, body = "mode-good -cv-page", ""
        else:
            classes, body = "mode-last -cv-page", ""
        marker = ' id="xCVLastPage"' if index == wrapper_count - 1 else ""
        wrappers.append(f'<div class="{classes}"{marker} data-slot="{index}">{body}</div>')

    nav_class = " mode-nav-open" if initial_nav_open else ""
    splash_nodes = ''.join('<div class="-cv-splash"></div>' for _ in range(initial_splash_count))
    capabilities = " mode-has-pr mode-has-comic-info mode-has-good-page" if body_count % 2 else ""
    return f'''<section id="comici-viewer" class="-cv mode-lang-ja mode-h mode-dir-rtl mode-nav-dir-rtl mode-spread mode-has-top-emptypage{nav_class}{capabilities}">
      {splash_nodes}
      <input id="xCVSeekBar" type="range" min="1" max="{maximum}" step="2" value="{maximum if initial_seek is None else initial_seek}">
      <div id="xCVPages" class="-cv-pages">{"".join(wrappers)}</div>
    </section>
    <style>
      html,body {{ margin:0; width:1906px; height:986px; overflow:hidden; }}
      #comici-viewer {{ position:absolute; left:0; top:0; width:1906px; height:986px; overflow:hidden; }}
      #xCVSeekBar {{ position:absolute; top:900px; }}
      #xCVPages {{ position:absolute; left:0; top:0; width:1906px; height:886px; }}
      .-cv-page {{ position:absolute; top:0; width:946px; height:886px; }}
      .-cv-page-content {{ position:absolute; inset:0; }}
      .-cv-page-canvas {{ position:absolute; inset:0; }}
      .-cv-ci.-cv-page-content {{ position:absolute; left:0; top:0; width:628px; height:886px; }}
      .-cv-ci-content {{ position:absolute; left:90px; top:207px; width:450px; height:470px; }}
      canvas {{ display:block; }}
    </style>
    <script>
      (() => {{
        const viewer = document.querySelector('#comici-viewer');
        const seek = document.querySelector('#xCVSeekBar');
        const wrappers = [...document.querySelector('#xCVPages').children];
        const body = wrappers.slice(2, {ci_slot});
        const update = () => {{
          const value = Number(seek.value);
          const focus = Number(seek.max) - value + 1;
          wrappers.forEach((wrapper, index) => {{
            wrapper.style.left = `${{945 + (focus - index - 1) * 946}}px`;
          }});
          viewer.classList.remove('mode-first-page','mode-top-pr-page','mode-last-page','mode-ci-page','mode-pr-page');
          if (value === {maximum}) viewer.classList.add('mode-first-page','mode-top-pr-page');
          if (value === 1) viewer.classList.add('mode-last-page');
          if ({str(body_count % 2 == 1).lower()} && value === {7 if tail_pr_count == 3 else 5}) viewer.classList.add('mode-ci-page','mode-pr-page');
          if ({str(body_count % 2 == 1 and tail_pr_count == 2).lower()} && [1,3].includes(value)) viewer.classList.add('mode-pr-page');
          if ({str(tail_pr_count == 3).lower()} && [3,5].includes(value)) viewer.classList.add('mode-pr-page');
          body.forEach(wrapper => wrapper.classList.add('mode-loaded','mode-rendered'));
          const active = [focus - 1, focus].filter(slot => slot >= 2 && slot < {ci_slot});
          active.forEach(slot => window.__yaRenderers?.[slot]?.());
        }};
        seek.addEventListener('input', update);
        seek.addEventListener('change', update);
        update();
      }})();
    </script>'''


def _top_empty_episode_html(
    *,
    native_source_slots: tuple[int, ...] = (),
    initial_nav_open: bool = False,
    initial_splash_count: int = 0,
    body_count: int = 44,
    tail_pr_count: int = 2,
    initial_seek: int | None = None,
) -> str:
    return f'''<!doctype html><html><head><meta charset="utf-8"><title>Fixture viewer</title></head>
      <body><div id="xHeader"><a class="ep-h-main-h-series" href="{WORK_URL}">Fixture Work</a></div>
      {_listing(selected_range=True)}
      {_top_empty_viewer_html(native_source_slots=native_source_slots, initial_nav_open=initial_nav_open,
                              initial_splash_count=initial_splash_count, body_count=body_count,
                              tail_pr_count=tail_pr_count, initial_seek=initial_seek)}</body></html>'''


async def _install_fixture(
    page,
    *,
    initial_seek: int = 11,
    native_source_slots: tuple[int, ...] = (),
    clip_slots: tuple[int, ...] = (),
    top_empty: bool = False,
    top_empty_body_count: int = 44,
    top_empty_tail_pr_count: int = 2,
    top_empty_initial_seek: int | None = None,
    top_empty_initial_nav_open: bool = False,
    top_empty_initial_splash_count: int = 0,
    episode_target_label: str = "無料",
    rental: bool = False,
    no_top_pr: bool = False,
    standard15_body: bool = False,
    standard_body_count: int | None = None,
    odd_body_count: int | None = None,
    top_empty_no_ci_body_count: int | None = None,
    pr_tail_body_count: int | None = None,
    tail_pr_count: int = 1,
    ticket_gate: bool = False,
    ticket_initial_access: bool = False,
    ticket_access_type: str = "waitAndFree",
    ticket_auth_user: int | None = 101,
    ticket_work_id: str = WORK_ID,
    ticket_episode_payload_id: str | None = EPISODE_ID,
    ticket_control_variant: str = "normal",
    ticket_checkout_status: int = 200,
    ticket_grant_after_checkout: bool = True,
    ticket_checkout_target_id: str = EPISODE_ID,
    ticket_post_series_delay_ms: int = 0,
    ticket_series_conflict_after_checkout: bool = False,
    ticket_hydration_delay_ms: int = 0,
    ticket_prefetch_series: bool = False,
    ticket_prefetch_other_episode_rsc: bool = False,
    ticket_prefetch_known_pages: bool = False,
    ticket_prefetch_external_subframes: bool = False,
) -> list[str]:
    requested: list[str] = []
    ticket_state = {"consumed": ticket_initial_access, "clicks": 0}

    def ticket_access_payload() -> dict[str, object]:
        access = {
            "hasAccess": ticket_state["consumed"],
            "accessType": ticket_access_type,
        }
        if ticket_episode_payload_id is not None:
            access["episodeId"] = ticket_episode_payload_id
        access["timeRemainingInSeconds"] = 25_900 if ticket_state["consumed"] else 0
        return {"episode": {"access": access, "series": {"id": ticket_work_id}}}

    def series_access_payload() -> dict[str, object]:
        has_access = ticket_state["consumed"] and not ticket_series_conflict_after_checkout
        access = {
            "episodeId": EPISODE_ID,
            "hasAccess": has_access,
            "accessType": ticket_access_type,
        }
        access["timeRemainingInSeconds"] = 25_900 if has_access else 0
        return {"seriesAccess": {"seriesId": ticket_work_id, "episodeAccesses": [access]}}

    ticket_button_attrs = {
        "hidden": 'style="display:none"',
        "disabled": "disabled",
    }.get(ticket_control_variant, "")
    ticket_button_label = (
        "有料で読む" if ticket_control_variant == "paid_label" else "待つと無料で読む"
    )
    ticket_duplicate_button = (
        '<button data-e2e="wfRead">待つと無料で読む</button>'
        if ticket_control_variant == "duplicate"
        else ""
    )

    initial_hydration = (
        f"setTimeout(() => {{ void hydrateTicketState().catch(() => {{}}); }}, {ticket_hydration_delay_ms});"
        if ticket_hydration_delay_ms > 0
        else "void hydrateTicketState();"
    )
    ticket_prefetch_script = (
        f"fetch('/series/{WORK_ID}/1?_rsc=fixture').catch(() => {{}});"
        if ticket_prefetch_series
        else ""
    )
    ticket_other_episode_prefetch_script = (
        "fetch('/episodes/d19dd3fa4563f?_rsc=fixture', "
        "{headers:{rsc:'fixture'}}).catch(() => {});"
        if ticket_prefetch_other_episode_rsc
        else ""
    )
    ticket_known_page_prefetch_script = (
        "for (const path of ['/', '/store_items/series/1708/1', '/store_items/1888']) "
        "fetch(path + '?_rsc=fixture', {headers:{rsc:'fixture'}}).catch(() => {});"
        if ticket_prefetch_known_pages
        else ""
    )
    ticket_external_subframe_script = (
        "(() => {"
        "const stripe=document.createElement('iframe');"
        "stripe.style.display='none';"
        "stripe.src='https://js.stripe.com/v3/controller-with-preconnect-"
        "837b3ba280ce77b8f4416a2f4686fd3f.html#fixture-fragment';"
        "document.body.append(stripe);"
        "const fb=document.createElement('iframe');fb.name='ya-fb-tracker';"
        "fb.style.display='none';"
        "document.body.append(fb);"
        "const form=document.createElement('form');form.method='POST';"
        "form.style.display='none';"
        "form.action='https://www.facebook.com/tr/';form.target=fb.name;"
        "document.body.append(form);form.submit();form.remove();"
        "})();"
        if ticket_prefetch_external_subframes
        else ""
    )
    ticket_hydration_script = f"""<script>
      window.__ticketClicks = 0;
      const hydrateTicketState = () => Promise.all([
        fetch('/api/auth/session').then(response => response.json()),
        fetch('/api/episodes/{EPISODE_ID}').then(response => response.json()),
        fetch('/api/series/access').then(response => response.json())
      ]);
      {initial_hydration}
      {ticket_prefetch_script}
      {ticket_other_episode_prefetch_script}
      {ticket_known_page_prefetch_script}
      {ticket_external_subframe_script}
      document.querySelector('[data-e2e="wfRead"]')?.addEventListener('click', async () => {{
        window.__ticketClicks += 1;
        await fetch('/api/checkout/rental', {{method:'POST',
          headers:{{'content-type':'application/json'}},
          body:JSON.stringify({{episodeId:'{ticket_checkout_target_id}'}})}});
        document.querySelector('#ticket-gate')?.remove();
        await hydrateTicketState();
      }});
    </script>"""

    async def fulfill(route) -> None:
        path = route.request.url.split("?", 1)[0].removeprefix(BASE)
        requested.append(path)
        if path == f"/series/{WORK_ID}":
            body = f"""<!doctype html><html><head><meta charset="utf-8"></head><body>
              <h1>Fixture Work</h1>{_listing(selected_range=False)}</body></html>"""
            await route.fulfill(status=200, body=body, content_type="text/html")
        elif path == f"/series/{WORK_ID}/1":
            body = f"""<!doctype html><html><head><meta charset="utf-8"></head><body>
              <h1>Fixture Work</h1>{_listing(selected_range=True)}</body></html>"""
            await route.fulfill(status=200, body=body, content_type="text/html")
        elif path == f"/episodes/{EPISODE_ID}":
            if top_empty:
                body = _top_empty_episode_html(
                    body_count=top_empty_body_count,
                    tail_pr_count=top_empty_tail_pr_count,
                    initial_seek=top_empty_initial_seek,
                    native_source_slots=native_source_slots,
                    initial_nav_open=top_empty_initial_nav_open,
                    initial_splash_count=top_empty_initial_splash_count,
                )
            else:
                body = _episode_html(
                    native_source_slots=native_source_slots,
                    clip_slots=clip_slots,
                    target_label=episode_target_label,
                    rental=rental,
                    no_top_pr=no_top_pr,
                    standard15_body=standard15_body,
                    standard_body_count=standard_body_count,
                    odd_body_count=odd_body_count,
                    top_empty_no_ci_body_count=top_empty_no_ci_body_count,
                    pr_tail_body_count=pr_tail_body_count,
                    tail_pr_count=tail_pr_count,
                    ticket_gate=ticket_gate and not ticket_initial_access,
                    ticket_control_missing=ticket_control_variant == "missing",
                ).replace('value="11"', f'value="{initial_seek}"')
                if ticket_gate:
                    body = body.replace(
                        'data-e2e="wfRead">待つと無料で読む',
                        f'data-e2e="wfRead" {ticket_button_attrs}>{ticket_button_label}',
                        1,
                    )
                    body = body.replace(
                        "</body>",
                        f"{ticket_hydration_script}{ticket_duplicate_button}</body>",
                    )
            await route.fulfill(status=200, body=body, content_type="text/html")
        elif ticket_gate and path == "/api/auth/session" and route.request.method == "GET":
            await route.fulfill(status=200, json={"user": ticket_auth_user})
        elif (
            ticket_gate and path == f"/api/episodes/{EPISODE_ID}" and route.request.method == "GET"
        ):
            await route.fulfill(status=200, json=ticket_access_payload())
        elif ticket_gate and path == "/api/series/access" and route.request.method == "GET":
            if ticket_state["consumed"] and ticket_post_series_delay_ms:
                await asyncio.sleep(ticket_post_series_delay_ms / 1000)
            await route.fulfill(status=200, json=series_access_payload())
        elif ticket_gate and path == "/api/checkout/rental" and route.request.method == "POST":
            if ticket_checkout_status == 200 and ticket_grant_after_checkout:
                ticket_state["consumed"] = True
            ticket_state["clicks"] += 1
            await route.fulfill(
                status=ticket_checkout_status, body="ok", content_type="text/plain"
            )
        else:
            await route.fulfill(status=404, body="")

    await page.route("https://younganimal.com/**", fulfill)
    if ticket_prefetch_external_subframes:
        async def fulfill_external(route) -> None:
            requested.append(f"third-party:{urlsplit(route.request.url).path}")
            await route.fulfill(status=200, body="")

        await page.route("https://js.stripe.com/**", fulfill_external)
        await page.route("https://www.facebook.com/**", fulfill_external)
    return requested


def _content_document_paths(requested: list[str]) -> list[str]:
    return [path for path in requested if path.startswith(("/episodes/", "/series/"))]


def _rgba_from_png_data_url(value: str) -> tuple[tuple[int, int], bytes]:
    prefix = "data:image/png;base64,"
    assert value.startswith(prefix)
    raw = base64.b64decode(value.removeprefix(prefix), validate=True)
    with Image.open(io.BytesIO(raw)) as image:
        image.load()
        return image.size, image.convert("RGBA").tobytes()


def _rgba_from_output(data: bytes) -> tuple[tuple[int, int], bytes]:
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        return image.size, image.convert("RGBA").tobytes()


async def _read_fixture_pixel_authority(page, rendered_slots: tuple[int, ...] = (2, 3)) -> dict[str, object]:
    return await page.evaluate("""slots => {
      const png = canvas => canvas.toDataURL('image/png');
      const sources = Object.fromEntries(Object.entries(window.__yaSources || {})
        .map(([slot, canvas]) => [slot, png(canvas)]));
      const rendered = Object.fromEntries(slots.map(slot => {
        const wrapper = document.querySelector('#xCVPages').children[slot];
        const canvases = [...wrapper.querySelectorAll('canvas')];
        if (canvases.length !== 1) throw new Error(`fixture_target_canvas_${slot}_missing`);
        return [slot, png(canvases[0])];
      }));
      return {sources, rendered};
    }""", list(rendered_slots))


def _make_younganimal_batch(
    tmp_path: Path,
    *,
    manifest_observations: list[dict[str, object]] | None = None,
    external_work_id: str = WORK_ID,
    rental: bool = False,
    quota: bool = False,
) -> tuple[CatalogService, BatchExecutor, object]:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(
        WorkInput(work_key="opaque-work-key-for-fixture", title="Catalog Work")
    )
    item = catalog.create_item(
        ItemInput(item_title="Episode 1", kind="episode", order_label="第1話"),
        work_id=work.id,
    )
    source = catalog.create_source(
        SourceInput(
            site="younganimal",
            external_id=f"{external_work_id}:{EPISODE_ID}",
            discovery_key="fixture-discovery",
            access_mode="quota" if quota else ("paid" if rental else "free"),
            access_granted_until="2099-10-11T12:00:00+09:00" if rental else None,
            available=True,
            display_position=1,
        ),
        item_id=item.id,
    )
    catalog.create_source_target(
        SourceTargetInput(backend="web", locator=EPISODE_URL), source_id=source.id
    )
    policies = SitePolicyRegistry()
    policies.register("younganimal", YounganimalSitePolicy)
    adapters = AdapterRegistry()
    adapters.register("younganimal", YounganimalAdapter)
    plan = BatchPlanner(catalog, policies).plan(
        site="younganimal",
        now=NOW,
        quota_resource="work_ticket" if quota else None,
    )
    assert len(plan.candidates) == 1

    package_function = package_crawl_output
    if manifest_observations is not None:

        def observe_manifest(output_dir, metadata, **kwargs):
            manifest_observations.append(
                json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
            )
            return package_crawl_output(output_dir, metadata, **kwargs)

        package_function = observe_manifest
    executor = BatchExecutor(
        catalog,
        policies,
        adapters,
        package_function=package_function,
        runtime_settings=SiteRuntimeSettings(page_turn_delay_ms=0),
    )
    return catalog, executor, plan.candidates[0]


async def test_younganimal_runner_captures_only_contiguous_rendered_pngs_and_packages_zip(
    browser_page, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    requested = await _install_fixture(browser_page)
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_MS", 50)
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_DEADLINE_MS", 1_000)
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_POLL_MS", 20)
    monkeypatch.setattr(younganimal_adapter_module, "PAGE_CHANGE_POLL_MS", 20)
    monkeypatch.setattr(younganimal_adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 2_000)
    original_collect = younganimal_adapter_module.COLLECT_CAPTURE_SCRIPT
    instrumented_collect = original_collect.replace("({expectedSlots", "async ({expectedSlots", 1).replace(
        "const after = api.inspect(expectedSlots);",
        "await new Promise(resolve => requestAnimationFrame(resolve));\n  const after = api.inspect(expectedSlots);",
        1,
    )
    monkeypatch.setattr(younganimal_adapter_module, "COLLECT_CAPTURE_SCRIPT", instrumented_collect)
    adapter = YounganimalAdapter(preflight_work_url=WORK_URL)
    original_evaluate = browser_page.evaluate
    rendered_epoch_audits: list[tuple[int, int]] = []
    instrumentation_installed = False

    async def instrument_rendered_capture(expression, *args, **kwargs):
        nonlocal instrumentation_installed
        if expression == instrumented_collect and not instrumentation_installed:
            instrumentation_installed = True
            await original_evaluate("""() => {
              const ci = [...document.querySelector('#xCVPages').children].slice(-5)[0];
              for (const canvas of document.querySelectorAll('#xCVPages .-cv-page canvas')) {
                const native = canvas.toDataURL;
                canvas.toDataURL = function(...args) {
                  if (!window.__yaCiMutationQueued) {
                    window.__yaCiMutationQueued = true;
                    requestAnimationFrame(() => ci.setAttribute('class', 'mode-ci -cv-page'));
                  }
                  return Reflect.apply(native, this, args);
                };
              }
            }""")
        result = await original_evaluate(expression, *args, **kwargs)
        if expression == instrumented_collect and isinstance(result, dict) and result.get("ok") is True:
            before = result["before"]
            after = result["after"]
            rendered_epoch_audits.append((
                after["domGeneration"] - before["domGeneration"],
                after["captureDomGeneration"] - before["captureDomGeneration"],
            ))
        return result

    monkeypatch.setattr(browser_page, "evaluate", instrument_rendered_capture)
    output_dir = tmp_path / "younganimal-crawl"
    result = await CrawlerRunner(
        RunConfig(
            site="younganimal",
            source_url=EPISODE_URL,
            output_dir=output_dir,
            diagnostics_dir=tmp_path / "diagnostics",
            page_turn_delay_ms=0,
            max_pages=20,
            max_same_content=3,
            page_change_timeout_ms=2_000,
            # Full-size PNG serialization/readback needs headroom on busy hosts.
            adapter_timeout_grace_ms=6_000,
        )
    ).run(browser_page, adapter)

    assert result.stop_state is PageState.END
    assert len(result.pages) == 16
    assert requested == [f"/episodes/{EPISODE_ID}"]
    assert [page.identity.page_id for page in result.pages] == [
        "1", "2,3", "2,3", "4,5", "4,5", "6,7", "6,7", "8,9", "8,9",
        "10,11", "10,11", "12,13", "12,13", "14,15", "14,15", "16",
    ]
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_url"] == EPISODE_URL
    assert [page["sequence"] for page in manifest["pages"]] == list(range(1, 17))
    assert {(page["width"], page["height"], page["mime_type"]) for page in manifest["pages"]} == {
        (PAGE_WIDTH, PAGE_HEIGHT, "image/png")
    }
    assert rendered_epoch_audits
    assert rendered_epoch_audits[0] == (1, 0)
    package = package_crawl_output(
        output_dir,
        adapter.get_output_metadata(),
        library_dir=tmp_path / "library",
    )
    with zipfile.ZipFile(package.archive_path) as archive:
        names = archive.namelist()
        assert len(names) == 16
        assert all(name.endswith(".png") for name in names)


@pytest.mark.parametrize(("rental", "no_top_pr"), [(False, False), (True, False), (True, True)])
async def test_younganimal_direct_batch_completes_from_one_canonical_episode_navigation(
    browser_page, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, rental: bool, no_top_pr: bool
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    requested = await _install_fixture(
        browser_page, rental=rental, episode_target_label="" if rental else "無料",
        no_top_pr=no_top_pr, native_source_slots=tuple(range(1, 17)) if no_top_pr else (),
    )
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_MS", 50)
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_DEADLINE_MS", 1_000)
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_POLL_MS", 20)
    monkeypatch.setattr(younganimal_adapter_module, "PAGE_CHANGE_POLL_MS", 20)
    monkeypatch.setattr(younganimal_adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 2_000)
    manifest_observations: list[dict[str, object]] = []
    catalog, executor, candidate = _make_younganimal_batch(
        tmp_path, manifest_observations=manifest_observations, rental=rental
    )

    result = await executor.execute_candidate(
        browser_page,
        candidate,
        output_root=tmp_path / "batch",
        library_dir=tmp_path / "library",
        max_pages=20,
        now=NOW,
    )

    assert _content_document_paths(requested) == [f"/episodes/{EPISODE_ID}"]
    assert await browser_page.locator("button").count() == 0
    assert result.page_count == 16
    assert result.stop_reason == "end"
    assert catalog.get_item(candidate.item_id).status == "completed"
    assert len(catalog.list_artifacts(item_id=candidate.item_id, state="present")) == 1
    assert len(catalog.list_crawl_runs(item_id=candidate.item_id, status="succeeded")) == 1
    source = catalog.get_source(candidate.source_id)
    target = catalog.get_source_target(candidate.target_id)
    assert target.locator == EPISODE_URL
    assert source.quota_started_at is None
    assert source.access_granted_until == ("2099-10-11T12:00:00+09:00" if rental else None)
    assert len(manifest_observations) == 1
    manifest = manifest_observations[0]
    assert manifest["source_url"] == EPISODE_URL
    assert len(manifest["pages"]) == 16
    assert result.archive_path.exists()
    assert "Catalog Work" in result.archive_path.name
    with zipfile.ZipFile(result.archive_path) as archive:
        assert len(archive.namelist()) == 16


async def test_younganimal_work_ticket_batch_clicks_once_then_uses_same_page_capture(
    browser_page, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    requested = await _install_fixture(
        browser_page,
        ticket_gate=True,
        native_source_slots=tuple(range(1, 17)),
    )
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_MS", 50)
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_DEADLINE_MS", 1_000)
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_POLL_MS", 20)
    monkeypatch.setattr(younganimal_adapter_module, "PAGE_CHANGE_POLL_MS", 20)
    monkeypatch.setattr(younganimal_adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 2_000)
    catalog, executor, candidate = _make_younganimal_batch(tmp_path, quota=True)

    result = await executor.execute_candidate(
        browser_page,
        candidate,
        output_root=tmp_path / "batch",
        library_dir=tmp_path / "library",
        max_pages=20,
        now=NOW,
    )

    assert await browser_page.evaluate("window.__ticketClicks") == 1
    assert requested.count("/api/checkout/rental") == 1
    assert _content_document_paths(requested) == [f"/episodes/{EPISODE_ID}"]
    assert result.stop_reason == "end"
    assert result.page_count == 16
    assert catalog.get_item(candidate.item_id).status == "completed"
    source = catalog.get_source(candidate.source_id)
    assert source.quota_started_at is not None
    assert source.access_granted_until is not None
    assert source.quota_started_at <= source.access_granted_until
    assert len(catalog.list_artifacts(item_id=candidate.item_id, state="present")) == 1
    assert result.archive_path.exists()


async def test_younganimal_work_ticket_grant_only_records_use_without_viewer_capture(
    browser_page, tmp_path: Path
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    requested = await _install_fixture(browser_page, ticket_gate=True)
    catalog, executor, candidate = _make_younganimal_batch(tmp_path, quota=True)

    result = await executor.execute_grant_only_candidate(
        browser_page,
        candidate,
        output_root=tmp_path / "batch",
        max_pages=20,
        now=NOW,
    )

    assert result.resource_consumed is True
    assert await browser_page.evaluate("window.__ticketClicks") == 1
    assert requested.count("/api/checkout/rental") == 1
    assert _content_document_paths(requested) == [f"/episodes/{EPISODE_ID}"]
    assert catalog.get_item(candidate.item_id).status == "pending"
    assert catalog.list_artifacts(item_id=candidate.item_id) == []
    source = catalog.get_source(candidate.source_id)
    assert source.quota_started_at is not None
    assert source.access_granted_until is not None
    assert list((tmp_path / "batch").rglob("page-*.*")) == []


async def test_younganimal_work_ticket_waits_for_delayed_initial_hydration(
    browser_page, tmp_path: Path
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    requested = await _install_fixture(
        browser_page, ticket_gate=True, ticket_hydration_delay_ms=150
    )
    catalog, executor, candidate = _make_younganimal_batch(tmp_path, quota=True)

    result = await executor.execute_grant_only_candidate(
        browser_page,
        candidate,
        output_root=tmp_path / "batch",
        max_pages=20,
        now=NOW,
    )

    assert result.resource_consumed is True
    assert await browser_page.evaluate("window.__ticketClicks") == 1
    assert requested.count("/api/checkout/rental") == 1
    assert catalog.get_source(candidate.source_id).quota_started_at is not None


@pytest.mark.parametrize("grant_only", [False, True])
async def test_younganimal_work_ticket_aborts_and_records_known_same_work_prefetch(
    browser_page, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, grant_only: bool
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    requested = await _install_fixture(
        browser_page,
        ticket_gate=True,
        ticket_prefetch_series=True,
        ticket_prefetch_other_episode_rsc=True,
        ticket_prefetch_known_pages=True,
        ticket_prefetch_external_subframes=True,
        native_source_slots=tuple(range(1, 17)),
    )
    guards = []
    original_guard = younganimal_adapter_module.YounganimalEpisodeRouteGuard

    class RecordingRouteGuard(original_guard):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            guards.append(self)

    monkeypatch.setattr(
        younganimal_adapter_module, "YounganimalEpisodeRouteGuard", RecordingRouteGuard
    )
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_MS", 50)
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_DEADLINE_MS", 1_000)
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_POLL_MS", 20)
    monkeypatch.setattr(younganimal_adapter_module, "PAGE_CHANGE_POLL_MS", 20)
    monkeypatch.setattr(younganimal_adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 2_000)
    catalog, executor, candidate = _make_younganimal_batch(tmp_path, quota=True)

    if grant_only:
        result = await executor.execute_grant_only_candidate(
            browser_page, candidate, output_root=tmp_path / "batch", max_pages=20, now=NOW,
        )
        assert result.resource_consumed is True
        assert catalog.get_item(candidate.item_id).status == "pending"
        assert catalog.list_artifacts(item_id=candidate.item_id) == []
    else:
        result = await executor.execute_candidate(
            browser_page, candidate, output_root=tmp_path / "batch",
            library_dir=tmp_path / "library", max_pages=20, now=NOW,
        )
        assert result.stop_reason == "end"
        assert result.page_count == 16
    assert await browser_page.evaluate("window.__ticketClicks") == 1
    assert requested.count("/api/checkout/rental") == 1
    assert not any(path.startswith("/series/") for path in requested)
    assert guards[0].same_work_prefetch_count == 1
    assert guards[0].same_work_prefetch_paths == [f"/series/{WORK_ID}/1"]
    assert guards[0].other_episode_prefetch_count == 1
    assert guards[0].other_episode_prefetch_paths == ["/episodes/d19dd3fa4563f"]
    assert "/episodes/d19dd3fa4563f" not in requested
    assert guards[0].known_page_rsc_prefetch_count == 3
    assert guards[0].known_page_rsc_prefetch_paths == [
        "/",
        "/store_items/series/1708/1",
        "/store_items/1888",
    ]
    assert "/" not in requested
    assert "/store_items/series/1708/1" not in requested
    assert "/store_items/1888" not in requested
    assert guards[0].stripe_subframe_count == 1
    assert guards[0].stripe_subframe_paths == [
        "/v3/controller-with-preconnect-837b3ba280ce77b8f4416a2f4686fd3f.html"
    ]
    assert guards[0].facebook_subframe_count == 1
    assert guards[0].facebook_subframe_paths == ["/tr/"]
    assert not any(path.startswith("third-party:") for path in requested)
    assert catalog.get_source(candidate.source_id).quota_started_at is not None


@pytest.mark.parametrize(
    "fixture_options",
    [
        {"ticket_access_type": "paidContent"},
        {"ticket_work_id": "0000000000001"},
        {"ticket_episode_payload_id": "0000000000001"},
        {"ticket_episode_payload_id": None},
        {"ticket_auth_user": None},
        {"ticket_control_variant": "hidden"},
        {"ticket_control_variant": "disabled"},
        {"ticket_control_variant": "paid_label"},
        {"ticket_control_variant": "duplicate"},
        {"ticket_control_variant": "missing"},
    ],
    ids=[
        "paid-native-state",
        "foreign-work",
        "wrong-native-episode",
        "missing-native-episode",
        "logged-out",
        "hidden",
        "disabled",
        "paid-label",
        "duplicate",
        "missing-free-control",
    ],
)
async def test_younganimal_work_ticket_unsafe_prestate_never_clicks(
    browser_page, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fixture_options: dict[str, object]
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    requested = await _install_fixture(browser_page, ticket_gate=True, **fixture_options)
    monkeypatch.setattr(younganimal_adapter_module, "TICKET_AUTH_READY_SECONDS", 0.2)
    catalog, executor, candidate = _make_younganimal_batch(tmp_path, quota=True)

    with pytest.raises((CandidateExecutionError, AccessResourceUnavailableError, UnknownPageStateError)):
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "batch",
            library_dir=tmp_path / "library",
            max_pages=20,
            now=NOW,
        )

    assert await browser_page.evaluate("window.__ticketClicks") == 0
    assert requested.count("/api/checkout/rental") == 0
    assert catalog.get_item(candidate.item_id).status == "pending"
    assert catalog.get_source(candidate.source_id).quota_started_at is None


async def test_younganimal_work_ticket_unconfirmed_checkout_is_never_retried(
    browser_page, tmp_path: Path
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    requested = await _install_fixture(
        browser_page, ticket_gate=True, ticket_grant_after_checkout=False
    )
    catalog, executor, candidate = _make_younganimal_batch(tmp_path, quota=True)

    with pytest.raises(CandidateExecutionError, match="consumption was not confirmed"):
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "batch",
            library_dir=tmp_path / "library",
            max_pages=20,
            now=NOW,
        )

    assert await browser_page.evaluate("window.__ticketClicks") == 1
    assert requested.count("/api/checkout/rental") == 1
    assert catalog.get_item(candidate.item_id).status == "pending"
    assert catalog.get_source(candidate.source_id).quota_started_at is None


async def test_younganimal_work_ticket_waits_for_newer_conflicting_series_response(
    browser_page, tmp_path: Path
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    requested = await _install_fixture(
        browser_page,
        ticket_gate=True,
        ticket_post_series_delay_ms=250,
        ticket_series_conflict_after_checkout=True,
    )
    catalog, executor, candidate = _make_younganimal_batch(tmp_path, quota=True)

    with pytest.raises(CandidateExecutionError, match="consumption was not confirmed"):
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "batch",
            library_dir=tmp_path / "library",
            max_pages=20,
            now=NOW,
        )

    assert await browser_page.evaluate("window.__ticketClicks") == 1
    assert requested.count("/api/checkout/rental") == 1
    assert catalog.get_source(candidate.source_id).quota_started_at is None


async def test_younganimal_work_ticket_requires_checkout_target_binding(
    browser_page, tmp_path: Path
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    requested = await _install_fixture(
        browser_page,
        ticket_gate=True,
        ticket_checkout_target_id="0000000000001",
    )
    catalog, executor, candidate = _make_younganimal_batch(tmp_path, quota=True)

    with pytest.raises(CandidateExecutionError, match="consumption was not confirmed"):
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "batch",
            library_dir=tmp_path / "library",
            max_pages=20,
            now=NOW,
        )

    assert await browser_page.evaluate("window.__ticketClicks") == 1
    assert requested.count("/api/checkout/rental") == 1
    assert catalog.get_source(candidate.source_id).quota_started_at is None


async def test_younganimal_work_ticket_rejects_replaced_retained_control_before_click(
    browser_page, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    requested = await _install_fixture(browser_page, ticket_gate=True)
    catalog, executor, candidate = _make_younganimal_batch(tmp_path, quota=True)
    original_match = YounganimalAdapter._retained_ticket_control_matches

    async def replace_before_identity_check(adapter, handle, *, expected_classes):
        await browser_page.evaluate("""() => {
          const button = document.querySelector('div.ep-main-content.mode-charge > div.ep-charge > div.ep-charge-act > button[data-e2e="wfRead"]');
          button.replaceWith(button.cloneNode(true));
        }""")
        return await original_match(
            adapter, handle, expected_classes=expected_classes
        )

    monkeypatch.setattr(
        YounganimalAdapter,
        "_retained_ticket_control_matches",
        replace_before_identity_check,
    )
    with pytest.raises(AccessResourceUnavailableError, match="work_ticket_control_changed_before_action"):
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "batch",
            library_dir=tmp_path / "library",
            max_pages=20,
            now=NOW,
        )

    assert await browser_page.evaluate("window.__ticketClicks") == 0
    assert requested.count("/api/checkout/rental") == 0
    assert catalog.get_source(candidate.source_id).quota_started_at is None


@pytest.mark.parametrize("status", [403, 429])
async def test_younganimal_work_ticket_rechecks_access_stop_before_latch(
    browser_page,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    status: int,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    requested = await _install_fixture(browser_page, ticket_gate=True)
    catalog, executor, candidate = _make_younganimal_batch(tmp_path, quota=True)
    original_match = YounganimalAdapter._retained_ticket_control_matches

    async def record_late_access_stop(adapter, handle, *, expected_classes):
        matched = await original_match(
            adapter, handle, expected_classes=expected_classes
        )
        if matched:
            adapter._access_stop = {
                "host": "younganimal.com",
                "path": "/api/episodes/" + EPISODE_ID,
                "status": status,
            }
        return matched

    monkeypatch.setattr(
        YounganimalAdapter,
        "_retained_ticket_control_matches",
        record_late_access_stop,
    )
    with pytest.raises(CandidateExecutionError, match=f"status={status}"):
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "batch",
            library_dir=tmp_path / "library",
            max_pages=20,
            now=NOW,
        )

    assert await browser_page.evaluate("window.__ticketClicks") == 0
    assert requested.count("/api/checkout/rental") == 0
    assert catalog.get_source(candidate.source_id).quota_started_at is None


async def test_younganimal_work_ticket_click_timeout_after_dispatch_is_reconciled_once(
    browser_page, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    requested = await _install_fixture(browser_page, ticket_gate=True)
    catalog, executor, candidate = _make_younganimal_batch(tmp_path, quota=True)
    original_click = ElementHandle.click

    async def click_then_timeout(handle, *args, **kwargs):
        await original_click(handle, *args, **kwargs)
        raise PlaywrightTimeoutError("synthetic click timeout after checkout dispatch")

    monkeypatch.setattr(ElementHandle, "click", click_then_timeout)
    result = await executor.execute_grant_only_candidate(
        browser_page,
        candidate,
        output_root=tmp_path / "batch",
        max_pages=20,
        now=NOW,
    )

    assert result.resource_consumed is True
    assert await browser_page.evaluate("window.__ticketClicks") == 1
    assert requested.count("/api/checkout/rental") == 1
    assert catalog.get_source(candidate.source_id).quota_started_at is not None
    assert catalog.get_item(candidate.item_id).status == "pending"
    assert catalog.list_artifacts(item_id=candidate.item_id) == []


async def test_younganimal_unknown_ticket_route_persists_first_failure_before_click(
    browser_page, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    requested = await _install_fixture(browser_page, ticket_gate=True)
    catalog, executor, candidate = _make_younganimal_batch(tmp_path, quota=True)
    original_entry = YounganimalAdapter._initialize_work_ticket_entry

    async def inject_unknown_routes(adapter, page, *, entry_only):
        await page.evaluate("""async () => {
          for (const path of ['/store_items/1888/extra', '/unrecognized']) {
            await fetch(path + '?_rsc=secret-query#secret-fragment',
              {headers: {rsc: 'secret-header'}}).catch(() => {});
          }
        }""")
        await original_entry(adapter, page, entry_only=entry_only)

    monkeypatch.setattr(
        YounganimalAdapter, "_initialize_work_ticket_entry", inject_unknown_routes
    )
    with pytest.raises(CandidateExecutionError, match="reason=unknown_rsc_page_route"):
        await executor.execute_grant_only_candidate(
            browser_page, candidate, output_root=tmp_path / "batch", max_pages=20, now=NOW,
        )
    assert await browser_page.evaluate("window.__ticketClicks") == 0
    assert "/api/checkout/rental" not in requested
    assert "/store_items/1888/extra" not in requested
    assert "/unrecognized" not in requested
    assert catalog.get_source(candidate.source_id).quota_started_at is None
    metadata_files = list((tmp_path / "batch").rglob("diagnostics/metadata.json"))
    assert len(metadata_files) == 1
    metadata = json.loads(metadata_files[0].read_text(encoding="utf-8"))
    debug = metadata["adapter_debug"]
    assert debug["ticket_action_attempted"] is False
    guard = debug["ticket_route_guard"]
    assert guard["failure_reason"] == "unknown_rsc_page_route"
    assert guard["blocked_count"] == 2
    assert guard["failure_request"] == {
        "host": "younganimal.com",
        "path": "/store_items/1888/extra",
        "method": "GET",
        "resource_type": "fetch",
        "is_navigation": False,
        "is_main_frame": True,
    }
    assert "secret-" not in json.dumps(debug)


async def test_younganimal_work_ticket_route_drift_after_proof_keeps_consumption_pending(
    browser_page, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    requested = await _install_fixture(browser_page, ticket_gate=True)
    catalog, executor, candidate = _make_younganimal_batch(tmp_path, quota=True)
    original_wait_for_viewer = YounganimalAdapter._wait_for_viewer_ready
    route_guards = []

    async def drift_after_confirmed_grant(adapter, page):
        observation = await original_wait_for_viewer(adapter, page)
        assert adapter.get_access_consumption().consumed is True
        guard = adapter._ticket_route_guard
        assert guard is not None
        route_guards.append(guard)
        request_failed = asyncio.create_task(
            page.wait_for_event(
                "requestfailed",
                predicate=lambda request: request.url == f"{BASE}/series/{WORK_ID}",
                timeout=2_000,
            )
        )
        await page.evaluate(
            "url => setTimeout(() => window.location.assign(url), 0)",
            f"{BASE}/series/{WORK_ID}",
        )
        await request_failed
        return observation

    monkeypatch.setattr(
        YounganimalAdapter, "_wait_for_viewer_ready", drift_after_confirmed_grant
    )

    with pytest.raises(CandidateExecutionError) as raised:
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "batch",
            library_dir=tmp_path / "library",
            max_pages=20,
            now=NOW,
        )

    assert raised.value.resource_consumed is True
    assert len(route_guards) == 1
    assert route_guards[0].failure_reason == "non_target_main_document"
    assert requested.count("/api/checkout/rental") == 1
    assert not any(path.startswith("/series/") for path in requested)
    assert catalog.get_source(candidate.source_id).quota_started_at is not None
    assert catalog.get_item(candidate.item_id).status == "pending"
    assert catalog.list_artifacts(item_id=candidate.item_id) == []

    metadata_files = list((tmp_path / "batch").rglob("diagnostics/metadata.json"))
    assert len(metadata_files) == 1
    debug = json.loads(metadata_files[0].read_text(encoding="utf-8"))["adapter_debug"]
    assert debug["ticket_action_attempted"] is True
    assert debug["ticket_route_guard"]["failure_reason"] == "non_target_main_document"
    assert debug["ticket_route_guard"]["failure_request"]["path"] == f"/series/{WORK_ID}"


async def test_younganimal_confirmed_ticket_is_persisted_when_viewer_initialization_fails(
    browser_page, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    requested = await _install_fixture(browser_page, ticket_gate=True)
    catalog, executor, candidate = _make_younganimal_batch(tmp_path, quota=True)

    async def fail_viewer(_adapter, _page):
        raise PageChangeTimeoutError("synthetic viewer failure after the ticket grant")

    monkeypatch.setattr(YounganimalAdapter, "_wait_for_viewer_ready", fail_viewer)
    with pytest.raises(CandidateExecutionError, match="synthetic viewer failure"):
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "batch",
            library_dir=tmp_path / "library",
            max_pages=20,
            now=NOW,
        )

    assert requested.count("/api/checkout/rental") == 1
    assert catalog.get_source(candidate.source_id).quota_started_at is not None
    assert catalog.get_item(candidate.item_id).status == "pending"
    assert catalog.list_artifacts(item_id=candidate.item_id) == []


async def test_younganimal_confirmed_ticket_is_persisted_when_batch_is_cancelled(
    browser_page, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    requested = await _install_fixture(browser_page, ticket_gate=True)
    catalog, executor, candidate = _make_younganimal_batch(tmp_path, quota=True)

    async def cancel_viewer(_adapter, _page):
        raise asyncio.CancelledError

    monkeypatch.setattr(YounganimalAdapter, "_wait_for_viewer_ready", cancel_viewer)
    with pytest.raises(BatchInterruptedError) as raised:
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "batch",
            library_dir=tmp_path / "library",
            max_pages=20,
            now=NOW,
        )

    assert raised.value.resource_consumed is True
    assert requested.count("/api/checkout/rental") == 1
    assert catalog.get_source(candidate.source_id).quota_started_at is not None
    assert catalog.get_item(candidate.item_id).status == "pending"


async def test_younganimal_confirmed_ticket_is_persisted_when_click_is_cancelled_after_action(
    browser_page, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    requested = await _install_fixture(browser_page, ticket_gate=True)
    catalog, executor, candidate = _make_younganimal_batch(tmp_path, quota=True)
    original_click = ElementHandle.click

    async def click_then_cancel(handle, *args, **kwargs):
        await original_click(handle, *args, **kwargs)
        raise asyncio.CancelledError

    monkeypatch.setattr(ElementHandle, "click", click_then_cancel)
    with pytest.raises(BatchInterruptedError) as raised:
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "batch",
            library_dir=tmp_path / "library",
            max_pages=20,
            now=NOW,
        )

    assert raised.value.resource_consumed is True
    assert await browser_page.evaluate("window.__ticketClicks") == 1
    assert requested.count("/api/checkout/rental") == 1
    assert catalog.get_source(candidate.source_id).quota_started_at is not None
    assert catalog.get_item(candidate.item_id).status == "pending"


async def test_younganimal_existing_ticket_grant_is_nonconsuming_for_normal_batch(
    browser_page, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    requested = await _install_fixture(
        browser_page,
        ticket_gate=True,
        ticket_initial_access=True,
        native_source_slots=tuple(range(1, 17)),
    )
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_MS", 50)
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_DEADLINE_MS", 1_000)
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_POLL_MS", 20)
    monkeypatch.setattr(younganimal_adapter_module, "PAGE_CHANGE_POLL_MS", 20)
    monkeypatch.setattr(younganimal_adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 2_000)
    catalog, executor, candidate = _make_younganimal_batch(tmp_path, quota=True)

    result = await executor.execute_candidate(
        browser_page,
        candidate,
        output_root=tmp_path / "batch",
        library_dir=tmp_path / "library",
        max_pages=20,
        now=NOW,
    )

    assert result.page_count == 16
    assert await browser_page.evaluate("window.__ticketClicks") == 0
    assert requested.count("/api/checkout/rental") == 0
    assert catalog.get_item(candidate.item_id).status == "completed"
    source = catalog.get_source(candidate.source_id)
    assert source.quota_started_at is None


async def test_younganimal_direct_batch_rejects_stale_free_row_before_capture_or_artifact(
    browser_page, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    requested = await _install_fixture(browser_page, episode_target_label=chr(0x5f85) + chr(0x3064) + chr(0x3068) + chr(0x7121) + chr(0x6599))
    catalog, executor, candidate = _make_younganimal_batch(tmp_path)

    with pytest.raises(CandidateExecutionError, match="direct access is blocked"):
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "batch",
            library_dir=tmp_path / "library",
            max_pages=20,
            now=NOW,
        )

    assert _content_document_paths(requested) == [f"/episodes/{EPISODE_ID}"]
    assert catalog.get_item(candidate.item_id).status == "pending"
    assert catalog.list_artifacts(item_id=candidate.item_id) == []
    assert list((tmp_path / "library").rglob("*.zip")) == []
    assert list((tmp_path / "batch").rglob("page-*.*")) == []
    source = catalog.get_source(candidate.source_id)
    assert source.quota_started_at is None
    assert source.access_granted_until is None


@pytest.mark.parametrize(
    ("external_work_id", "initial_url_override", "expected_requests", "error_message"),
    [
        (
            "0000000000001",
            None,
            [f"/episodes/{EPISODE_ID}"],
            "episode header does not prove the configured work",
        ),
        (
            WORK_ID,
            "https://younganimal.com/episodes/0000000000001",
            ["/episodes/0000000000001"],
            "initial navigation left its configured entry route",
        ),
    ],
)
async def test_younganimal_direct_batch_rejects_wrong_work_header_or_redirect_before_capture(
    browser_page,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    external_work_id: str,
    initial_url_override: str | None,
    expected_requests: list[str],
    error_message: str,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    requested = await _install_fixture(browser_page)
    if initial_url_override is not None:
        resolve_initial_navigation_url = YounganimalAdapter.resolve_initial_navigation_url

        def override_initial_navigation(adapter, source_url: str) -> str:
            resolve_initial_navigation_url(adapter, source_url)
            return initial_url_override

        monkeypatch.setattr(
            YounganimalAdapter,
            "resolve_initial_navigation_url",
            override_initial_navigation,
        )
    catalog, executor, candidate = _make_younganimal_batch(
        tmp_path, external_work_id=external_work_id
    )

    with pytest.raises(CandidateExecutionError, match=error_message):
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "batch",
            library_dir=tmp_path / "library",
            max_pages=20,
            now=NOW,
        )

    assert _content_document_paths(requested) == expected_requests
    assert catalog.get_item(candidate.item_id).status == "pending"
    assert catalog.list_artifacts(item_id=candidate.item_id) == []
    assert list((tmp_path / "library").rglob("*.zip")) == []
    assert list((tmp_path / "batch").rglob("page-*.*")) == []


async def test_younganimal_top_empty_profile_skips_only_observed_blank_and_captures_all_body_pages(
    browser_page, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    requested = await _install_fixture(
        browser_page,
        top_empty=True,
        native_source_slots=tuple(range(2, 46)),
        top_empty_initial_nav_open=True,
        top_empty_initial_splash_count=1,
    )
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_MS", 1_000)
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_DEADLINE_MS", 5_000)
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_POLL_MS", 20)
    monkeypatch.setattr(younganimal_adapter_module, "PAGE_CHANGE_POLL_MS", 10)
    monkeypatch.setattr(younganimal_adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 3_000)

    class PixelAuditAdapter(YounganimalAdapter):
        def __init__(self) -> None:
            super().__init__(preflight_work_url=WORK_URL)
            self.fixture_pixel_authority: dict[str, object] | None = None
            self.initial_ui_metrics: list[dict[str, object]] = []
            self.capture_modes: list[str] = []

        async def _wait_for_initial_quiet(self, page, initial):
            await page.evaluate("""() => {
              const viewer = document.querySelector('#comici-viewer');
              const splash = viewer.querySelector('.-cv-splash');
              window.__yaInitialUiTimeline = {started: performance.now()};
              window.__yaInitialUiTimers = [
                setTimeout(() => {
                  viewer.classList.remove('mode-nav-open');
                  splash.classList.add('mode-hide');
                  window.__yaInitialUiTimeline.navClosed = performance.now();
                }, 1200),
                setTimeout(() => {
                  splash.remove();
                  window.__yaInitialUiTimeline.firstSettled = performance.now();
                }, 1400),
                setTimeout(() => {
                  viewer.classList.add('mode-nav-open');
                  viewer.append(splash);
                  window.__yaInitialUiTimeline.reopened = performance.now();
                }, 1900),
                setTimeout(() => {
                  viewer.classList.remove('mode-nav-open');
                  splash.remove();
                  window.__yaInitialUiTimeline.finalSettled = performance.now();
                }, 2200),
              ];
            }""")
            await super()._wait_for_initial_quiet(page, initial)

        async def capture_page(self, page):
            if self.fixture_pixel_authority is None:
                # Read the fixture's private source canvases and visible target
                # canvases directly, before the production capture path runs.
                self.fixture_pixel_authority = await _read_fixture_pixel_authority(page)
            result = await super().capture_page(page)
            self.capture_modes.append(str(self._capture_diagnostics["mode"]))
            return result

    adapter = PixelAuditAdapter()
    original_verify = younganimal_adapter_module.VERIFY_NATIVE_CAPTURE_SCRIPT
    monkeypatch.setattr(
        younganimal_adapter_module,
        "VERIFY_NATIVE_CAPTURE_SCRIPT",
        f"""async token => {{
          const capture = window.__younganimalViewerCapture;
          const before = capture.inspect([]);
          const pages = document.querySelector('#xCVPages');
          const ci = pages.children[pages.children.length - 5];
          const widget = ci.querySelector(':scope > .-cv-ci.-cv-page-content > .-cv-ci-content');
          if (!widget) throw new Error('fixture_ci_scroll_widget_missing');
          const variants = ['mode-ci\\t-cv-page -cv-page', '-cv-page  mode-ci'];
          const audits = window.__yaCiNoopAudits || (window.__yaCiNoopAudits = []);
          const serialization = variants[audits.length % variants.length];
          ci.setAttribute('class', serialization);
          if (widget.classList.contains('mode-scroll-bottom')) {{
            widget.setAttribute('class', widget.getAttribute('class'));
          }} else {{
            widget.setAttribute('class', '-cv-ci-content mode-scroll-bottom');
          }}
          await new Promise(resolve => requestAnimationFrame(resolve));
          const after = capture.inspect([]);
          const mutations = capture.mutationsSince(before.domGeneration);
          const records = mutations.records.filter(item => item.generation > before.domGeneration);
          const record = records.find(item => item.canonicalCiClassNoop === true);
          const widgetRecord = records.find(item => item.ciScrollWidgetClassNoop === true);
          const verified = await ({original_verify})(token);
          audits.push({{
            globalDelta: after.domGeneration - before.domGeneration,
            captureDelta: after.captureDomGeneration - before.captureDomGeneration,
            record: record ? {{
              canonicalCiWrapper: record.canonicalCiWrapper,
              classTokenSetsSame: record.classTokenSetsSame,
              canonicalCiClassNoop: record.canonicalCiClassNoop,
              generation: record.generation,
              captureGeneration: record.captureGeneration,
            }} : null,
            widgetRecord: widgetRecord ? {{
              targetArea: widgetRecord.targetArea,
              ciScrollWidgetTarget: widgetRecord.ciScrollWidgetTarget,
              ciScrollWidgetClassNoop: widgetRecord.ciScrollWidgetClassNoop,
              classTokenSetsSame: widgetRecord.classTokenSetsSame,
              classAdded: widgetRecord.classAdded,
              classRemoved: widgetRecord.classRemoved,
              captureGeneration: widgetRecord.captureGeneration,
            }} : null,
            mutationCount: records.length,
            verified: verified.ok === true,
          }});
          return verified;
        }}""",
    )
    original_evaluate = browser_page.evaluate
    encode_events: list[dict[str, object]] = []
    original_encode = younganimal_adapter_module.encode_native_webp

    async def record_native_selection(expression, *args, **kwargs):
        if expression == younganimal_adapter_module.COLLECT_NATIVE_CAPTURE_SCRIPT:
            metrics = await original_evaluate("""() => {
              const viewer = document.querySelector('#comici-viewer');
              const timeline = window.__yaInitialUiTimeline;
              return {
                navOpen: viewer.classList.contains('mode-nav-open'),
                splashCount: viewer.querySelectorAll('.-cv-splash').length,
                afterFinalSettleMs: timeline?.finalSettled === undefined
                  ? null : performance.now() - timeline.finalSettled,
              };
            }""")
            adapter.initial_ui_metrics.append(metrics)
        return await original_evaluate(expression, *args, **kwargs)

    monkeypatch.setattr(browser_page, "evaluate", record_native_selection)

    def record_native_encoding(images):
        assert adapter.initial_ui_metrics
        encode_events.append(adapter.initial_ui_metrics[-1])
        return original_encode(images)

    monkeypatch.setattr(younganimal_adapter_module, "encode_native_webp", record_native_encoding)
    output_dir = tmp_path / "younganimal-top-empty-crawl"
    result = await CrawlerRunner(
        RunConfig(
            site="younganimal",
            source_url=EPISODE_URL,
            output_dir=output_dir,
            diagnostics_dir=tmp_path / "diagnostics",
            page_turn_delay_ms=0,
            max_pages=50,
            max_same_content=3,
            page_change_timeout_ms=3_000,
        )
    ).run(browser_page, adapter)

    assert result.stop_state is PageState.END
    assert len(result.pages) == 44
    assert len(adapter.capture_modes) == 22
    assert adapter.capture_modes == ["native_source_canvas"] * 22
    assert result.pages[0].identity.page_id == "2,3"
    assert [page.identity.page_id for page in result.pages] == [
        page_id
        for first_slot in range(2, 46, 2)
        for page_id in (f"{first_slot},{first_slot + 1}",) * 2
    ]
    assert requested == [f"/episodes/{EPISODE_ID}"]
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_url"] == EPISODE_URL
    assert [page["sequence"] for page in manifest["pages"]] == list(range(1, 45))
    assert all(
        (page["width"], page["height"]) == (47, 61)
        for page in manifest["pages"]
    )
    assert all(page["mime_type"] == "image/webp" for page in manifest["pages"])
    ci_audits = await browser_page.evaluate("() => window.__yaCiNoopAudits")
    assert len(ci_audits) == 22
    nested_body_holders = await browser_page.evaluate("""() => {
      const pages = document.querySelector('#xCVPages');
      return [...pages.children].slice(2, 46).map(wrapper => {
        const canvases = [...wrapper.querySelectorAll('canvas')];
        const canvas = canvases.length === 1 ? canvases[0] : null;
        const holder = canvas?.parentElement || null;
        return {
          canvasCount: canvases.length,
          wrapperContainsHolder: !!holder && wrapper.contains(holder),
          nearestPageIsWrapper: !!holder && holder.closest('.-cv-page') === wrapper,
          holderClass: holder?.classList.contains('-cv-page-canvas') === true,
          holderParentClass: holder?.parentElement?.classList.contains('-cv-page-content') === true,
        };
      });
    }""")
    assert len(nested_body_holders) == 44
    assert all(
        row == {
            "canvasCount": 1,
            "wrapperContainsHolder": True,
            "nearestPageIsWrapper": True,
            "holderClass": True,
            "holderParentClass": True,
        }
        for row in nested_body_holders
    )
    assert all(
        audit["globalDelta"] == 2
        and audit["captureDelta"] == 0
        and audit["record"]["canonicalCiWrapper"] is True
        and audit["record"]["classTokenSetsSame"] is True
        and audit["record"]["canonicalCiClassNoop"] is True
        and audit["record"]["captureGeneration"] is not None
        and audit["widgetRecord"]["ciScrollWidgetTarget"] is True
        and audit["widgetRecord"]["targetArea"] == "wrapper_descendant"
        and audit["widgetRecord"]["ciScrollWidgetClassNoop"] is True
        and audit["widgetRecord"]["classRemoved"] == []
        and audit["widgetRecord"]["captureGeneration"] is not None
        and audit["mutationCount"] == 2
        and audit["verified"] is True
        for audit in ci_audits
    )
    assert ci_audits[0]["widgetRecord"]["classAdded"] == ["mode-scroll-bottom"]
    assert all(audit["widgetRecord"]["classAdded"] == [] for audit in ci_audits[1:])
    assert len(adapter.initial_ui_metrics) == len(encode_events) > 0
    assert all(
        metric["navOpen"] is False
        and metric["splashCount"] == 0
        and isinstance(metric["afterFinalSettleMs"], (int, float))
        and metric["afterFinalSettleMs"] >= 1_000
        for metric in adapter.initial_ui_metrics
    )
    assert all(
        event["navOpen"] is False
        and event["splashCount"] == 0
        and event["afterFinalSettleMs"] >= 1_000
        for event in encode_events
    )
    output_page_bytes = {
        Path(page["file"]).name: (output_dir / Path(page["file"]).name).read_bytes()
        for page in manifest["pages"]
    }
    package = package_crawl_output(
        output_dir,
        adapter.get_output_metadata(),
        library_dir=tmp_path / "library",
    )
    assert adapter.fixture_pixel_authority is not None
    source_pixels = {
        int(slot): _rgba_from_png_data_url(value)
        for slot, value in adapter.fixture_pixel_authority["sources"].items()
    }
    manifest_pages = manifest["pages"]
    with zipfile.ZipFile(package.archive_path) as archive:
        members = {Path(name).name: archive.read(name) for name in archive.namelist()}
        assert len(members) == 44
        assert sum(name.endswith(".png") for name in members) == 0
        assert sum(name.endswith(".webp") for name in members) == 44
        for index, page_record in enumerate(manifest_pages):
            physical_slot = index + 2
            filename = Path(page_record["file"]).name
            output_bytes = output_page_bytes[filename]
            assert members[filename] == output_bytes
            actual_size, actual_rgba = _rgba_from_output(output_bytes)
            expected_size, expected_rgba = source_pixels[physical_slot]
            assert actual_size == expected_size
            assert hashlib.sha256(actual_rgba).digest() == hashlib.sha256(expected_rgba).digest()


@pytest.mark.parametrize(
    ("case", "malformed_field", "malformed_value"),
    [
        ("unsettled_ui", None, None),
        ("malformed_nav_type", "viewerNavOpen", 0),
        ("malformed_splash_type", "viewerSplashCount", True),
    ],
)
async def test_younganimal_initial_ui_unknown_or_unsettled_fails_before_capture(
    browser_page,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    case: str,
    malformed_field: str | None,
    malformed_value: object,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    requested = await _install_fixture(
        browser_page,
        top_empty=True,
        top_empty_initial_nav_open=case == "unsettled_ui",
        top_empty_initial_splash_count=1 if case == "unsettled_ui" else 0,
    )
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_MS", 30)
    monkeypatch.setattr(
        younganimal_adapter_module,
        "INITIAL_QUIET_DEADLINE_MS",
        200 if case == "unsettled_ui" else 1_000,
    )
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_POLL_MS", 10)
    monkeypatch.setattr(younganimal_adapter_module, "PAGE_CHANGE_POLL_MS", 10)
    monkeypatch.setattr(younganimal_adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 2_000)
    original_evaluate = browser_page.evaluate
    collection_calls: list[str] = []

    async def monitor_capture(expression, *args, **kwargs):
        result = await original_evaluate(expression, *args, **kwargs)
        if expression in {
            younganimal_adapter_module.COLLECT_NATIVE_CAPTURE_SCRIPT,
            younganimal_adapter_module.COLLECT_CAPTURE_SCRIPT,
        }:
            collection_calls.append(expression)
        if (
            malformed_field is not None
            and expression == younganimal_adapter_module.SNAPSHOT_SCRIPT
            and args
            and args[0].get("pixelSlots")
        ):
            result["snapshot"][malformed_field] = malformed_value
        return result

    monkeypatch.setattr(browser_page, "evaluate", monitor_capture)
    encoding_calls: list[object] = []
    original_encode = younganimal_adapter_module.encode_native_webp

    def track_encoding(images):
        encoding_calls.append(images)
        return original_encode(images)

    monkeypatch.setattr(younganimal_adapter_module, "encode_native_webp", track_encoding)
    adapter = YounganimalAdapter(preflight_work_url=WORK_URL)
    output_dir = tmp_path / f"younganimal-initial-ui-{case}"
    expected_error = (
        "did not settle within its 5 second bound"
        if case == "unsettled_ui"
        else "initial navigation or splash state is unknown"
    )
    with pytest.raises(UnknownPageStateError, match=expected_error):
        await CrawlerRunner(
            RunConfig(
                site="younganimal",
                source_url=EPISODE_URL,
                output_dir=output_dir,
                diagnostics_dir=tmp_path / f"diagnostics-{case}",
                page_turn_delay_ms=0,
                max_pages=50,
                max_same_content=3,
                page_change_timeout_ms=2_000,
            )
        ).run(browser_page, adapter)

    assert requested == [f"/episodes/{EPISODE_ID}"]
    assert collection_calls == []
    assert encoding_calls == []
    assert list(output_dir.rglob("page-*.*")) == []
    assert list(tmp_path.rglob("*.zip")) == []
    status = await original_evaluate("() => window.__younganimalNativeCapture.status()")
    assert status == {"candidateCount": 0, "proofCount": 0, "integrity": True}


@pytest.mark.parametrize("draw_before_translation", [False, True])
@pytest.mark.parametrize(("body_count", "pr_count"), [(11, 2), (9, 3), (3, 3)])
async def test_younganimal_shorter_top_empty_runner_captures_last_single_body_and_packages(
    browser_page, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, draw_before_translation: bool,
    body_count: int, pr_count: int,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    body_slots = tuple(range(2, body_count + 2))
    await _install_fixture(browser_page, top_empty=True, top_empty_body_count=body_count,
                           top_empty_tail_pr_count=pr_count, native_source_slots=body_slots,
                           top_empty_initial_seek=1 if pr_count == 3 and draw_before_translation else None)
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_MS", 20)
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_POLL_MS", 10)
    monkeypatch.setattr(younganimal_adapter_module, "PAGE_CHANGE_POLL_MS", 10)
    monkeypatch.setattr(younganimal_adapter_module, "VIEWER_READY_TIMEOUT_MS", 1_000)

    if pr_count == 3:
        verify = younganimal_adapter_module.VERIFY_NATIVE_CAPTURE_SCRIPT
        monkeypatch.setattr(younganimal_adapter_module, "VERIFY_NATIVE_CAPTURE_SCRIPT", f"""async token => {{
          if (document.querySelector('#xCVSeekBar').value === '7' && !window.__yaTopEmptyCiAudit) {{
            const capture=window.__younganimalViewerCapture, before=capture.inspect([]);
            const pages=document.querySelector('#xCVPages');
            pages.children[pages.children.length-6].querySelector('.-cv-ci-content').classList.add('mode-scroll-bottom');
            await new Promise(resolve=>requestAnimationFrame(resolve));
            window.__yaTopEmptyCiAudit=capture.inspect([]).captureDomGeneration-before.captureDomGeneration;
          }}
          return ({verify})(token);
        }}""")

    class AuditedAdapter(YounganimalAdapter):
        def __init__(self):
            super().__init__(preflight_work_url=WORK_URL)
            self.records = []
            self.sources = None

        async def capture_page(self, page):
            if self.sources is None:
                self.sources = (await _read_fixture_pixel_authority(page))["sources"]
                if draw_before_translation:
                    await page.evaluate("""() => {
                      const slots=document.querySelector('#xCVPages').children;
                      for(const slot of [2,3]) {
                        slots[slot].style.transform='translateX(-1900px)';
                        window.__yaRenderers[slot]();
                        slots[slot].style.transform='';
                      }
                    }""")
            captures = await super().capture_page(page)
            self.records.append(dict(self._capture_diagnostics))
            for slot, capture in zip(self._last_capture_slots, captures, strict=True):
                assert _rgba_from_output(capture.data) == _rgba_from_png_data_url(self.sources[str(slot)])
            return captures

    adapter = AuditedAdapter()
    output = tmp_path / "short-top-empty"
    result = await CrawlerRunner(RunConfig(
        site="younganimal", source_url=EPISODE_URL, output_dir=output,
        diagnostics_dir=tmp_path / "diagnostics", max_pages=body_count, page_turn_delay_ms=0,
    )).run(browser_page, adapter)

    assert result.stop_state is PageState.END and len(result.pages) == body_count
    assert adapter._captured_slots == list(body_slots)
    assert [row["slots"] for row in adapter.records] == [list(body_slots[i:i + 2]) for i in range(0, body_count, 2)]
    maximum = body_count + pr_count + 5
    maximum -= maximum % 2 == 0
    assert [row["seek_value"] for row in adapter.records] == list(range(maximum - 2, pr_count + 2, -2))
    assert all(row["mode"] == "native_source_canvas" for row in adapter.records)
    if pr_count == 3:
        assert await browser_page.evaluate("window.__yaTopEmptyCiAudit") == 0
    packaged = package_crawl_output(output, adapter.get_output_metadata(), library_dir=tmp_path / "library")
    with zipfile.ZipFile(packaged.archive_path) as archive:
        assert archive.testzip() is None and len(archive.namelist()) == body_count
        assert all(name.endswith(".webp") for name in archive.namelist())


@pytest.mark.parametrize("mutation", ["capability", "phase", "blank", "tail", "center", "premature_end"])
@pytest.mark.parametrize(("body_count", "pr_count"), [(11, 2), (9, 3)])
async def test_younganimal_shorter_top_empty_native_rejects_profile_drift(
    browser_page, monkeypatch: pytest.MonkeyPatch, mutation: str,
    body_count: int, pr_count: int,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_fixture(browser_page, top_empty=True, top_empty_body_count=body_count,
                           top_empty_tail_pr_count=pr_count, native_source_slots=(2, 3))
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_MS", 20)
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_POLL_MS", 10)
    adapter = YounganimalAdapter(preflight_work_url=WORK_URL)
    await adapter.prepare_page(browser_page)
    await adapter.configure_run(browser_page, "auto")
    await browser_page.goto(adapter.resolve_initial_navigation_url(EPISODE_URL), wait_until="commit")
    await adapter.initialize(browser_page)
    await browser_page.evaluate("""({mutation, ci}) => {
      const viewer=document.querySelector('#comici-viewer');
      const slots=document.querySelector('#xCVPages').children;
      if(mutation==='capability')viewer.classList.remove('mode-has-comic-info');
      if(mutation==='phase')viewer.classList.add('mode-pr-page');
      if(mutation==='blank')slots[1].classList.add('mode-pr');
      if(mutation==='tail')slots[ci].className='-cv-page mode-pr mode-empty';
      if(mutation==='center')slots[4].style.left='0px';
      if(mutation==='premature_end') {
        const seek=document.querySelector('#xCVSeekBar');seek.value='1';
        seek.dispatchEvent(new Event('input',{bubbles:true}));
      }
    }""", {"mutation": mutation, "ci": body_count + 2})
    if mutation == "premature_end":
        with pytest.raises(UnknownPageStateError, match="before every body slot was captured"):
            await adapter.detect_state(browser_page)
    raw = await browser_page.evaluate(younganimal_adapter_module.COLLECT_NATIVE_CAPTURE_SCRIPT, {
        "expectedSlots": [2, 3], "expectedSeek": 15, "episodePath": f"/episodes/{EPISODE_ID}",
        "maxPngChars": 12_000_000,
    })
    assert raw["mode"] == "fallback"
    assert "images" not in raw
    with pytest.raises(UnknownPageStateError):
        await adapter.capture_page(browser_page)
    assert adapter._captured_slots == []


@pytest.mark.parametrize("mutation", ["replacement", "seek"])
@pytest.mark.parametrize("top_empty", [False, True])
async def test_three_pr_post_encoding_mutation_saves_no_artifact(
    browser_page, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mutation: str,
    top_empty: bool,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_fixture(browser_page, top_empty=top_empty, top_empty_body_count=9,
                           top_empty_tail_pr_count=3, native_source_slots=(2, 3) if top_empty else (1,),
                           pr_tail_body_count=None if top_empty else 11, tail_pr_count=3)
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_MS", 20)
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_POLL_MS", 10)
    script = (
        f"const c=document.querySelector('#xCVPages').children[{2 if top_empty else 1}].querySelector('canvas');c.replaceWith(c.cloneNode(true));"
        if mutation == "replacement" else
        "const s=document.querySelector('#xCVSeekBar');s.value='1';s.dispatchEvent(new Event('input',{bubbles:true}));"
    )
    monkeypatch.setattr(younganimal_adapter_module, "VERIFY_NATIVE_CAPTURE_SCRIPT", f"""async token => {{
      {script}
      await new Promise(resolve=>requestAnimationFrame(resolve));
      return window.__younganimalNativeCapture.verify(token);
    }}""")
    output = tmp_path / "capture"
    with pytest.raises(UnknownPageStateError, match="native post-encoding proof failed"):
        await CrawlerRunner(RunConfig(
            site="younganimal", source_url=EPISODE_URL, output_dir=output,
            diagnostics_dir=tmp_path / "diagnostics", page_turn_delay_ms=0,
        )).run(browser_page, YounganimalAdapter(preflight_work_url=WORK_URL))
    assert list(output.glob("page-*.*")) == []
    assert await browser_page.evaluate("window.__younganimalNativeCapture.status()") == {
        "candidateCount": 0, "proofCount": 0, "integrity": True,
    }


@pytest.mark.parametrize("mutation", ["capability", "phase", "tail", "center", "premature_end"])
@pytest.mark.parametrize(("standard_body_count", "tail_pr_count", "pr_body_count"), [(None, 1, 6), (None, 3, 6), (1, 1, None), (2, 1, None), (None, 3, 11)],
                         ids=["single_pr", "three_pr", "one_body", "two_body", "three_pr_odd_body"])
async def test_younganimal_small_native_layout_rejects_profile_drift(
    browser_page, monkeypatch: pytest.MonkeyPatch, mutation: str, standard_body_count: int | None, tail_pr_count: int,
    pr_body_count: int | None,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_fixture(browser_page, pr_tail_body_count=pr_body_count,
                           standard_body_count=standard_body_count, tail_pr_count=tail_pr_count, native_source_slots=(1,))
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_MS", 20)
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_POLL_MS", 10)
    adapter = YounganimalAdapter(preflight_work_url=WORK_URL)
    await adapter.prepare_page(browser_page)
    await adapter.configure_run(browser_page, "auto")
    await browser_page.goto(adapter.resolve_initial_navigation_url(EPISODE_URL), wait_until="commit")
    await adapter.initialize(browser_page)
    await browser_page.evaluate("""({mutation,bodyCount,prCount,prBodyCount}) => {
      const viewer=document.querySelector('#comici-viewer');
      const slots=document.querySelector('#xCVPages').children;
      if(mutation==='capability')viewer.classList.remove('mode-has-comic-info');
      if(mutation==='phase')viewer.classList.add('mode-pr-page');
      if(mutation==='tail')slots[bodyCount===null?prBodyCount+prCount+2:bodyCount+4].className='-cv-page mode-pr mode-empty';
      if(mutation==='center')slots[bodyCount===null?4:2].style.left='0px';
      if(mutation==='premature_end') {
        const seek=document.querySelector('#xCVSeekBar');seek.value='1';
        seek.dispatchEvent(new Event('input',{bubbles:true}));
        seek.dispatchEvent(new Event('change',{bubbles:true}));
      }
    }""", {"mutation": mutation, "bodyCount": standard_body_count, "prCount": tail_pr_count, "prBodyCount": pr_body_count})
    if mutation == "premature_end":
        with pytest.raises(UnknownPageStateError, match="before every body slot was captured"):
            await adapter.detect_state(browser_page)
    maximum = pr_body_count + tail_pr_count + 4 if pr_body_count is not None else 7
    maximum -= maximum % 2 == 0
    raw = await browser_page.evaluate(younganimal_adapter_module.COLLECT_NATIVE_CAPTURE_SCRIPT, {
        "expectedSlots": [1], "expectedSeek": 1 if mutation == "premature_end" else maximum,
        "episodePath": f"/episodes/{EPISODE_ID}",
        "maxPngChars": 12_000_000,
    })
    assert raw["mode"] == "fallback"
    assert "images" not in raw
    with pytest.raises(UnknownPageStateError):
        await adapter.capture_page(browser_page)
    assert adapter._captured_slots == []


async def test_younganimal_unknown_initial_layout_retains_parser_reason(
    browser_page, monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _install_fixture(browser_page, top_empty=True, top_empty_body_count=11)
    adapter = YounganimalAdapter(preflight_work_url=WORK_URL)
    await adapter.prepare_page(browser_page)
    await browser_page.goto(adapter.resolve_initial_navigation_url(EPISODE_URL), wait_until="commit")
    await browser_page.locator("#xCVSeekBar").evaluate("seek => { seek.max='19'; }")
    monkeypatch.setattr(younganimal_adapter_module, "VIEWER_READY_TIMEOUT_MS", 60)
    monkeypatch.setattr(younganimal_adapter_module, "VIEWER_READY_POLL_MS", 5)

    with pytest.raises(PageChangeTimeoutError, match="seek range does not match"):
        await adapter._wait_for_viewer_ready(browser_page)

    diagnostic = adapter._capture_diagnostics["viewer_readiness"]
    assert diagnostic["last_error"] == "UnknownPageStateError"
    assert diagnostic["last_error_message"] == "Younganimal seek range does not match its physical wrapper layout"


async def test_younganimal_native_selection_cancellation_releases_unreturned_proof(
    browser_page, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_fixture(browser_page, native_source_slots=(1, 2))
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_MS", 20)
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_DEADLINE_MS", 500)
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_POLL_MS", 10)
    monkeypatch.setattr(younganimal_adapter_module, "PAGE_CHANGE_POLL_MS", 10)
    monkeypatch.setattr(younganimal_adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 2_000)

    original_evaluate = browser_page.evaluate
    selected = asyncio.Event()
    selected_result: dict[str, object] | None = None

    async def hold_after_selection(expression, *args, **kwargs):
        nonlocal selected_result
        result = await original_evaluate(expression, *args, **kwargs)
        if expression == younganimal_adapter_module.COLLECT_NATIVE_CAPTURE_SCRIPT:
            selected_result = result
            selected.set()
            await asyncio.Future()
        return result

    monkeypatch.setattr(browser_page, "evaluate", hold_after_selection)
    adapter = YounganimalAdapter(preflight_work_url=WORK_URL)
    await adapter.prepare_page(browser_page)
    await adapter.configure_run(browser_page, "auto")
    initial_url = adapter.resolve_initial_navigation_url(EPISODE_URL)
    await browser_page.goto(initial_url, wait_until="commit")
    await adapter.initialize(browser_page)
    task = asyncio.create_task(adapter.capture_page(browser_page))
    await asyncio.wait_for(selected.wait(), timeout=10)
    assert isinstance(selected_result, dict)
    assert selected_result.get("mode") == "native"
    assert isinstance(selected_result.get("token"), str)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    status = await original_evaluate("() => window.__younganimalNativeCapture.status()")
    assert status == {"candidateCount": 0, "proofCount": 0, "integrity": True}
    assert not list(tmp_path.glob("*.zip"))


@pytest.mark.parametrize(
    ("drift", "mutation"),
    [
        (
            "variant",
            "document.querySelector('#comici-viewer').classList.add('mode-has-top-emptypage')",
        ),
        (
            "wrapper_count",
            "document.querySelector('#xCVPages').append(document.createElement('div'))",
        ),
        (
            "tail_role",
            (
                "const ci=document.querySelector('#xCVPages').children[17];"
                "ci.className='-cv-page mode-good'"
            ),
        ),
    ],
)
@pytest.mark.parametrize("standard15_body", [False, True])
async def test_younganimal_capture_rejects_frozen_mapping_drift_before_native_or_png_fallback(
    browser_page,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    drift: str,
    mutation: str,
    standard15_body: bool,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_fixture(
        browser_page,
        native_source_slots=(1, 2),
        standard15_body=standard15_body,
    )
    if standard15_body:
        mutation = mutation.replace("children[17]", "children[16]")
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_MS", 20)
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_DEADLINE_MS", 500)
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_POLL_MS", 10)
    monkeypatch.setattr(younganimal_adapter_module, "PAGE_CHANGE_POLL_MS", 10)
    monkeypatch.setattr(younganimal_adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 2_000)

    class MappingDriftAdapter(YounganimalAdapter):
        def __init__(self) -> None:
            super().__init__(preflight_work_url=WORK_URL)
            self.drifted = False

        async def get_content_identity(self, page):
            identity = await super().get_content_identity(page)
            if not self.drifted:
                await page.evaluate(mutation)
                self.drifted = True
            return identity

    output_dir = tmp_path / f"younganimal-frozen-mapping-{drift}"
    adapter = MappingDriftAdapter()
    with pytest.raises(UnknownPageStateError, match="Younganimal"):
        await CrawlerRunner(
            RunConfig(
                site="younganimal",
                source_url=EPISODE_URL,
                output_dir=output_dir,
                diagnostics_dir=tmp_path / f"mapping-diagnostics-{drift}",
                page_turn_delay_ms=0,
                max_pages=20,
                max_same_content=3,
                page_change_timeout_ms=2_000,
            )
        ).run(browser_page, adapter)

    status = await browser_page.evaluate("() => window.__younganimalNativeCapture.status()")
    assert status["candidateCount"] == 0
    assert status["proofCount"] == 0
    assert not list(output_dir.glob("page-*.*"))
    assert not list(tmp_path.glob("*.zip"))


async def test_younganimal_capture_rejects_valid_profile_mapping_drift_after_detect(
    browser_page, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_fixture(browser_page, initial_seek=11, native_source_slots=(1, 2, 3, 4))
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_MS", 20)
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_DEADLINE_MS", 500)
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_POLL_MS", 10)
    monkeypatch.setattr(younganimal_adapter_module, "PAGE_CHANGE_POLL_MS", 10)
    monkeypatch.setattr(younganimal_adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 2_000)

    class ValidProfileDriftAdapter(YounganimalAdapter):
        def __init__(self) -> None:
            super().__init__(preflight_work_url=WORK_URL)
            self.direct_parser_result = None
            self.capture_called = False
            self.fallback_calls: list[object] = []

        async def get_content_identity(self, page):
            identity = await super().get_content_identity(page)
            if self.direct_parser_result is not None or self._captured_slots != [1]:
                return identity

            before = await self._observe(page)
            assert before.seek_value == 19
            assert len(before.active_slots) == 2
            before = await self._observe(page, pixel_slots=before.active_slots)
            mutation_result = await page.evaluate(
                """({activeSlots}) => {
                  const viewer = document.querySelector('#comici-viewer');
                  const pages = document.querySelector('#xCVPages');
                  const seek = document.querySelector('#xCVSeekBar');
                  const oldValue = Number(seek.value);
                  const oldMax = Number(seek.max);
                  const focus = oldMax - oldValue + 1;
                  const active = activeSlots.map(index => pages.children[index]);
                  const activeRects = active.map(wrapper => {
                    const r = wrapper.getBoundingClientRect();
                    return [r.x, r.y, r.width, r.height];
                  });
                  const blank = pages.children[1];
                  blank.replaceChildren();
                  blank.className = '-cv-page mode-empty';
                  const ci = [...pages.children].find(node => node.classList.contains('mode-ci'));
                  if (!ci) throw new Error('fixture_ci_missing');
                  const unloadedBody = document.createElement('div');
                  unloadedBody.className = '-cv-page';
                  pages.insertBefore(unloadedBody, ci);
                  const bodyIndex = [...pages.children].indexOf(unloadedBody);
                  unloadedBody.style.left = `${945 + (focus - bodyIndex - 1) * 946}px`;
                  viewer.classList.add('mode-has-top-emptypage');
                  seek.max = String(oldMax + 2);
                  seek.value = String(oldValue + 2);
                  return {
                    activeRects,
                    value: Number(seek.value),
                    max: Number(seek.max),
                    bodyIndex,
                    blankCanvasCount: blank.querySelectorAll('canvas').length,
                    unloadedCanvasCount: unloadedBody.querySelectorAll('canvas').length,
                    unloadedCenterInViewport: (() => {
                      const r = unloadedBody.getBoundingClientRect();
                      return r.width > 0 && r.height > 0 && r.x + r.width / 2 >= 0 &&
                        r.x + r.width / 2 <= innerWidth && r.y + r.height / 2 >= 0 &&
                        r.y + r.height / 2 <= innerHeight;
                    })(),
                  };
                }""",
                {"activeSlots": list(before.active_slots)},
            )
            snapshot_result = await page.evaluate(
                younganimal_adapter_module.SNAPSHOT_SCRIPT,
                {"pixelSlots": list(before.active_slots)},
            )
            assert isinstance(snapshot_result, dict)
            assert snapshot_result.get("observerReady") is True
            after = younganimal_adapter_module._parse_viewer_observation(
                snapshot_result.get("snapshot"), expected_url=EPISODE_URL
            )
            assert mutation_result["value"] == before.seek_value + 2
            assert mutation_result["max"] == before.seek_max + 2
            assert mutation_result["bodyIndex"] == 17
            assert mutation_result["blankCanvasCount"] == 0
            assert mutation_result["unloadedCanvasCount"] == 0
            assert mutation_result["unloadedCenterInViewport"] is False
            assert after.layout_variant == "top_emptypage"
            assert after.body_slots == tuple(range(2, 18))
            assert after.ci_slot == 18
            assert after.seek_value == 21
            assert after.seek_min == 1 and after.seek_max == 23 and after.seek_step == 2
            assert after.page_state == "content"
            assert after.active_slots == before.active_slots
            assert after.ready_slots == before.ready_slots == before.active_slots
            for slot in before.active_slots:
                before_row = before.raw["slots"][slot]
                after_row = after.raw["slots"][slot]
                assert after_row["wrapperNode"] == before_row["wrapperNode"]
                assert after_row["wrapperRect"] == before_row["wrapperRect"]
                assert after_row["canvas"]["node"] == before_row["canvas"]["node"]
                assert after_row["canvas"]["rect"] == before_row["canvas"]["rect"]
                assert after_row["canvas"]["pixels"] == before_row["canvas"]["pixels"]
            self.direct_parser_result = after
            return identity

        async def capture_page(self, page):
            self.capture_called = True
            return await super().capture_page(page)

        async def get_capture_targets(self, page):
            self.fallback_calls.append(page)
            raise AssertionError("generic capture fallback must not run")

    adapter = ValidProfileDriftAdapter()
    collect_calls: list[str] = []
    original_evaluate = browser_page.evaluate

    async def track_collection(expression, *args, **kwargs):
        if adapter.direct_parser_result is not None and expression in {
            younganimal_adapter_module.COLLECT_NATIVE_CAPTURE_SCRIPT,
            younganimal_adapter_module.COLLECT_CAPTURE_SCRIPT,
        }:
            collect_calls.append(expression)
        return await original_evaluate(expression, *args, **kwargs)

    monkeypatch.setattr(browser_page, "evaluate", track_collection)
    output_dir = tmp_path / "younganimal-valid-profile-mapping-drift"
    with pytest.raises(UnknownPageStateError, match="frozen body/tail roles"):
        await CrawlerRunner(
            RunConfig(
                site="younganimal",
                source_url=EPISODE_URL,
                output_dir=output_dir,
                diagnostics_dir=tmp_path / "valid-profile-mapping-diagnostics",
                page_turn_delay_ms=0,
                max_pages=20,
                max_same_content=3,
                page_change_timeout_ms=2_000,
            )
        ).run(browser_page, adapter)

    assert adapter.direct_parser_result is not None
    assert adapter.capture_called
    assert collect_calls == []
    assert adapter.fallback_calls == []
    page_files = list(output_dir.glob("page-*.*"))
    assert len(page_files) == 1
    assert page_files[0].name.startswith("page-0001.")
    assert not (output_dir / "page-0002.png").exists()
    assert not (output_dir / "page-0003.png").exists()
    status = await browser_page.evaluate("() => window.__younganimalNativeCapture.status()")
    assert status["candidateCount"] == 0
    assert status["proofCount"] == 0
    assert not list(tmp_path.glob("*.zip"))


@pytest.mark.parametrize(
    ("odd_body_count", "standard_body_count", "top_empty_no_ci_body_count", "pr_tail_body_count", "force_rendered_fallback", "no_top_pr", "tail_pr_count"),
    [
        (None, None, None, None, False, False, 1), (7, None, None, None, False, False, 1), (9, None, None, None, False, False, 1), (15, None, None, None, False, False, 1),
        (None, 12, None, None, False, False, 1), (None, None, 6, None, False, False, 1), (None, None, 10, None, False, False, 1),
        (None, None, 10, None, True, False, 1), (None, None, None, 6, False, False, 1), (None, None, None, 4, False, False, 1),
        pytest.param(7, None, None, None, False, True, 1, id="no_top_pr_odd_7"),
        pytest.param(3, None, None, None, False, True, 1, id="no_top_pr_odd_3"),
        pytest.param(None, 2, None, None, False, False, 1, id="two_body"),
        pytest.param(None, 1, None, None, False, False, 1, id="one_body"),
        pytest.param(None, None, None, 10, False, False, 3, id="three_pr_10"),
        pytest.param(None, None, None, 4, False, False, 3, id="three_pr_4"),
        pytest.param(None, None, None, 11, False, False, 3, id="three_pr_odd_11"),
        pytest.param(None, None, None, 3, False, False, 3, id="three_pr_odd_3"),
    ],
)
async def test_younganimal_runner_uses_lossless_native_spreads_after_pixel_proof(
    browser_page, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    odd_body_count: int | None, standard_body_count: int | None,
    top_empty_no_ci_body_count: int | None, pr_tail_body_count: int | None, force_rendered_fallback: bool, no_top_pr: bool, tail_pr_count: int,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    no_ci_profile = top_empty_no_ci_body_count is not None
    body_count = pr_tail_body_count or top_empty_no_ci_body_count or standard_body_count or (16 if odd_body_count is None else odd_body_count)
    body_slots = tuple(range(1, body_count + 1))
    final_body_seek = (
        str(tail_pr_count + 4) if pr_tail_body_count is not None else "7" if standard_body_count == 1 else "17" if standard_body_count == 12 else "5" if no_ci_profile else ("7" if odd_body_count is not None else "5")
    )
    exercise_overflow = standard_body_count == 12
    ci_slot = body_count + 1
    requested = await _install_fixture(
        browser_page,
        initial_seek=(body_count + 3 if no_ci_profile else 11),
        native_source_slots=() if force_rendered_fallback else body_slots,
        standard_body_count=standard_body_count,
        odd_body_count=odd_body_count,
        top_empty_no_ci_body_count=top_empty_no_ci_body_count,
        pr_tail_body_count=pr_tail_body_count,
        tail_pr_count=tail_pr_count,
        no_top_pr=no_top_pr,
    )
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_MS", 30)
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_DEADLINE_MS", 1_000)
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_POLL_MS", 10)
    monkeypatch.setattr(younganimal_adapter_module, "PAGE_CHANGE_POLL_MS", 10)
    monkeypatch.setattr(younganimal_adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 2_000)
    monkeypatch.setattr(younganimal_adapter_module, "VIEWER_READY_TIMEOUT_MS", 1_000)
    original_verify = younganimal_adapter_module.VERIFY_NATIVE_CAPTURE_SCRIPT
    monkeypatch.setattr(
        younganimal_adapter_module,
        "VERIFY_NATIVE_CAPTURE_SCRIPT",
        f"""async token => {{
          const capture = window.__younganimalViewerCapture;
          const before = capture.inspect([]);
          const seek = document.querySelector('#xCVSeekBar');
          if ({str(not no_ci_profile).lower()} && seek?.value === '{final_body_seek}' && !window.__yaStandardCiWidgetMutation) {{
            const pages = document.querySelector('#xCVPages');
            const ci = pages.children[pages.children.length - {tail_pr_count + 3 if pr_tail_body_count is not None else 5}];
            const widget = ci.querySelector(':scope > .-cv-ci.-cv-page-content > .-cv-ci-content');
            if (!widget) throw new Error('fixture_ci_scroll_widget_missing');
            const overflowProfile = {str(exercise_overflow).lower()};
            if (overflowProfile) {{
              widget.classList.add('mode-overflow');
              widget.setAttribute('class', widget.getAttribute('class'));
            }} else {{
              widget.classList.add('mode-scroll-bottom');
            }}
            window.__yaStandardCiWidgetMutation = true;
            await new Promise(resolve => requestAnimationFrame(resolve));
            const after = capture.inspect([]);
            const mutations = capture.mutationsSince(before.domGeneration);
            const records = mutations.records.filter(item => item.ciScrollWidgetTarget === true);
            window.__yaStandardCiWidgetAudit = {{
              seek: seek.value,
              globalDelta: after.domGeneration - before.domGeneration,
              captureDelta: after.captureDomGeneration - before.captureDomGeneration,
              records: records.map(record => ({{
                slot: record.slot,
                targetArea: record.targetArea,
                ciScrollWidgetClassNoop: record.ciScrollWidgetClassNoop,
                classAdded: record.classAdded,
                classRemoved: record.classRemoved,
              }})),
            }};
          }}
          return ({original_verify})(token);
        }}""",
    )

    class PixelAuditAdapter(YounganimalAdapter):
        def __init__(self) -> None:
            super().__init__(preflight_work_url=WORK_URL)
            self.capture_modes: list[str] = []
            self.capture_records: list[dict[str, object]] = []
            self.source_authority: dict[str, object] | None = None
            self.captured_by_slot: dict[int, tuple[tuple[int, int], bytes]] = {}

        async def capture_page(self, page):
            if self.source_authority is None:
                self.source_authority = await _read_fixture_pixel_authority(
                    page, rendered_slots=body_slots if force_rendered_fallback or body_count <= 2 else (2, 3)
                )
            result = await super().capture_page(page)
            self.capture_modes.append(str(self._capture_diagnostics["mode"]))
            self.capture_records.append(dict(self._capture_diagnostics))
            if result is not None:
                for slot, capture in zip(self._capture_diagnostics["slots"], result, strict=True):
                    self.captured_by_slot[int(slot)] = _rgba_from_output(capture.data)
            return result

    adapter = PixelAuditAdapter()
    output_dir = tmp_path / "younganimal-native-crawl"
    result = await CrawlerRunner(
        RunConfig(
            site="younganimal",
            source_url=EPISODE_URL,
            output_dir=output_dir,
            diagnostics_dir=tmp_path / "native-diagnostics",
            page_turn_delay_ms=0,
            max_pages=20,
            max_same_content=3,
            page_change_timeout_ms=2_000,
        )
    ).run(browser_page, adapter)

    assert result.stop_state is PageState.END
    assert len(result.pages) == len(body_slots)
    assert requested == [f"/episodes/{EPISODE_ID}"]
    expected_mode = "rendered_canvas_png" if force_rendered_fallback else "native_source_canvas"
    assert adapter.capture_modes[0] == expected_mode, adapter.capture_records[0]
    assert adapter.capture_modes == [expected_mode] * (1 + len(body_slots) // 2), adapter.capture_modes
    assert adapter.source_authority is not None
    sources = adapter.source_authority["sources"]
    assert isinstance(sources, dict)
    assert set(adapter.captured_by_slot) == set(body_slots)
    for slot, actual in adapter.captured_by_slot.items():
        authority = adapter.source_authority["rendered"] if force_rendered_fallback else sources
        expected = _rgba_from_png_data_url(authority[str(slot)])
        assert actual == expected
    ci_audit = await browser_page.evaluate("() => window.__yaStandardCiWidgetAudit")
    expected_widget_records = [
        {
            "slot": ci_slot,
            "targetArea": "wrapper_descendant",
            "ciScrollWidgetClassNoop": True,
            "classAdded": ["mode-overflow"] if exercise_overflow else ["mode-scroll-bottom"],
            "classRemoved": [],
        }
    ]
    if exercise_overflow:
        expected_widget_records.append(
            {
                "slot": ci_slot,
                "targetArea": "wrapper_descendant",
                "ciScrollWidgetClassNoop": True,
                "classAdded": [],
                "classRemoved": [],
            }
        )
    if no_ci_profile:
        assert ci_audit is None
    else:
        assert ci_audit == {
            "seek": final_body_seek,
            "globalDelta": len(expected_widget_records),
            "captureDelta": 0,
            "records": expected_widget_records,
        }
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    expected_page_size = (PAGE_WIDTH, PAGE_HEIGHT) if force_rendered_fallback else (47, 61)
    assert {(page["width"], page["height"]) for page in manifest["pages"]} == {expected_page_size}
    assert {page["mime_type"] for page in manifest["pages"]} <= {"image/png", "image/webp"}
    package = package_crawl_output(
        output_dir, adapter.get_output_metadata(), library_dir=tmp_path / "native-library"
    )
    manifest_rows = manifest["pages"]
    expected_names = [Path(row["file"]).name for row in manifest_rows]
    with zipfile.ZipFile(package.archive_path) as archive:
        names = archive.namelist()
        assert [Path(name).name for name in names] == expected_names
        assert archive.testzip() is None
        assert len(names) == len(body_slots)
        for slot, row, member in zip(body_slots, manifest_rows, names, strict=True):
            archived = archive.read(member)
            archived_size, archived_rgba = _rgba_from_output(archived)
            authority = adapter.source_authority["rendered"] if force_rendered_fallback else sources
            expected_size, expected_rgba = _rgba_from_png_data_url(authority[str(slot)])
            assert archived_size == expected_size
            assert hashlib.sha256(archived_rgba).digest() == hashlib.sha256(expected_rgba).digest()


@pytest.mark.parametrize(
    ("geometry_change", "expected_mode"),
    [
        ("pure_translation", "native_source_canvas"),
        ("size_change", "rendered_canvas_png"),
        ("target_relative_drift", "rendered_canvas_png"),
    ],
)
async def test_younganimal_draw_to_selection_geometry_requires_pure_translation(
    browser_page,
    monkeypatch: pytest.MonkeyPatch,
    geometry_change: str,
    expected_mode: str,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_fixture(browser_page, native_source_slots=(1, 2, 3))
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_MS", 20)
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_DEADLINE_MS", 1_000)
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_POLL_MS", 10)
    monkeypatch.setattr(younganimal_adapter_module, "PAGE_CHANGE_POLL_MS", 10)
    monkeypatch.setattr(younganimal_adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 2_000)

    adapter = YounganimalAdapter(preflight_work_url=WORK_URL)
    await adapter.prepare_page(browser_page)
    await adapter.configure_run(browser_page, "auto")
    await browser_page.goto(adapter.resolve_initial_navigation_url(EPISODE_URL), wait_until="commit")
    await adapter.initialize(browser_page)

    first = await adapter.capture_page(browser_page)
    assert first is not None
    assert adapter._capture_diagnostics["slots"] == [1]
    await adapter.go_next(browser_page)
    await adapter.wait_for_change(browser_page, None)
    before_authority = await _read_fixture_pixel_authority(browser_page)
    before = await adapter._observe(browser_page, pixel_slots=(2, 3))
    assert before.active_slots == before.ready_slots == (2, 3)

    geometry = await browser_page.evaluate(
        """({kind}) => {
          const pages = document.querySelector('#xCVPages');
          const wrappers = [pages.children[2], pages.children[3]];
          const rect = node => {
            const r = node.getBoundingClientRect();
            return [r.x, r.y, r.width, r.height];
          };
          const before = wrappers.map(wrapper => [rect(wrapper), rect(wrapper.querySelector('canvas'))]);
          if (kind === 'pure_translation') {
            wrappers.forEach(wrapper => { wrapper.style.transform = 'translate(20px, 5px)'; });
          } else if (kind === 'size_change') {
            wrappers.forEach(wrapper => { wrapper.style.width = '960px'; });
          } else {
            wrappers.forEach(wrapper => { wrapper.querySelector('canvas').style.transform = 'translateX(7px)'; });
          }
          const after = wrappers.map(wrapper => [rect(wrapper), rect(wrapper.querySelector('canvas'))]);
          return {before, after};
        }""",
        {"kind": geometry_change},
    )
    if geometry_change == "pure_translation":
        for before_row, after_row in zip(geometry["before"], geometry["after"], strict=True):
            before_wrapper, before_target = before_row
            after_wrapper, after_target = after_row
            for before_rect, after_rect in ((before_wrapper, after_wrapper), (before_target, after_target)):
                assert before_rect[2:] == after_rect[2:]
                assert [after_rect[i] - before_rect[i] for i in (0, 1)] == [20, 5]
    elif geometry_change == "size_change":
        assert any(
            before_rect[2:] != after_rect[2:]
            for before_row, after_row in zip(geometry["before"], geometry["after"], strict=True)
            for before_rect, after_rect in zip(before_row, after_row, strict=True)
        )
    else:
        assert all(
            before_row[0] == after_row[0]
            and [after_row[1][i] - before_row[1][i] for i in (0, 1)] == [7, 0]
            and before_row[1][2:] == after_row[1][2:]
            for before_row, after_row in zip(geometry["before"], geometry["after"], strict=True)
        )

    captures = await adapter.capture_page(browser_page)
    assert captures is not None and len(captures) == 2
    assert adapter._capture_diagnostics["slots"] == [2, 3]
    assert adapter._capture_diagnostics["mode"] == expected_mode
    if expected_mode == "native_source_canvas":
        assert [capture.mime_type for capture in captures] == ["image/webp", "image/webp"]
        sources = {
            int(slot): _rgba_from_png_data_url(value)
            for slot, value in before_authority["sources"].items()
        }
        for slot, capture in zip((2, 3), captures, strict=True):
            actual_size, actual_pixels = _rgba_from_output(capture.data)
            expected_size, expected_pixels = sources[slot]
            assert (capture.width, capture.height) == expected_size
            assert actual_size == expected_size
            assert hashlib.sha256(actual_pixels).digest() == hashlib.sha256(expected_pixels).digest()
    else:
        assert [capture.mime_type for capture in captures] == ["image/png", "image/png"]
        rendered = {
            int(slot): _rgba_from_png_data_url(value)
            for slot, value in before_authority["rendered"].items()
        }
        for slot, capture in zip((2, 3), captures, strict=True):
            actual_size, actual_pixels = _rgba_from_output(capture.data)
            expected_size, expected_pixels = rendered[slot]
            assert (capture.width, capture.height) == (PAGE_WIDTH, PAGE_HEIGHT)
            assert actual_size == expected_size
            assert hashlib.sha256(actual_pixels).digest() == hashlib.sha256(expected_pixels).digest()
    status = await browser_page.evaluate("() => window.__younganimalNativeCapture.status()")
    assert status == {"candidateCount": 0, "proofCount": 0, "integrity": True}


@pytest.mark.parametrize(
    ("geometry", "native"),
    [("fractional-width", True), ("fractional-height", True), ("fractional-both", True),
     ("underfill", False), ("whole-pixel-overhang", False), ("source-crop", False),
     ("destination-offset", False), ("nonfinite", False)],
)
async def test_younganimal_fractional_draw_preserves_native_pixels_and_rejects_unsafe_half(
    browser_page, monkeypatch: pytest.MonkeyPatch, geometry: str, native: bool,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_fixture(browser_page, native_source_slots=(1, 2, 3))
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_MS", 20)
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_POLL_MS", 10)
    monkeypatch.setattr(younganimal_adapter_module, "PAGE_CHANGE_POLL_MS", 10)
    adapter = YounganimalAdapter(preflight_work_url=WORK_URL)
    await adapter.prepare_page(browser_page)
    await adapter.configure_run(browser_page, "auto")
    await browser_page.goto(adapter.resolve_initial_navigation_url(EPISODE_URL), wait_until="commit")
    await adapter.initialize(browser_page)
    await adapter.capture_page(browser_page)
    await adapter.go_next(browser_page)
    await adapter.wait_for_change(browser_page, None)

    authority = await browser_page.evaluate("""geometry => {
      const result = [];
      for (const slot of [2,3]) {
        const target = document.querySelector('#xCVPages').children[slot].querySelector('canvas');
        const source = document.createElement('canvas'); source.width = 47; source.height = 61;
        const context = source.getContext('2d');
        const pixels = context.createImageData(47,61);
        for (let i=0; i<pixels.data.length; i+=4) {
          const p=i/4;
          pixels.data.set([(p*slot)%251,(p*17)%253,(p*37)%255,255],i);
        }
        context.putImageData(pixels,0,0);
        const args = [0,0,47,61,0,0,target.width,target.height];
        if (geometry === 'fractional-width') args[6] += 0.5;
        if (geometry === 'fractional-height') args[7] += 0.5;
        if (geometry === 'fractional-both') { args[6] += 0.999; args[7] += 0.999; }
        if (slot === 3) {
          if (geometry === 'underfill') args[7] -= 0.001;
          if (geometry === 'whole-pixel-overhang') args[7] += 1;
          if (geometry === 'source-crop') args[3] -= 0.5;
          if (geometry === 'destination-offset') args[5] = 0.5;
          if (geometry === 'nonfinite') args[7] = Infinity;
        }
        target.getContext('2d').drawImage(source,...args);
        result.push({source:source.toDataURL('image/png'),rendered:target.toDataURL('image/png')});
        context.clearRect(0,0,47,61);
      }
      return result;
    }""", geometry)

    captures = await adapter.capture_page(browser_page)

    assert len(captures) == 2
    assert adapter._capture_diagnostics["mode"] == ("native_source_canvas" if native else "rendered_canvas_png")
    if not native:
        assert adapter._capture_diagnostics["native_fallback_reason"] == "native_candidate_missing_or_stale"
    for capture, expected in zip(captures, authority, strict=True):
        assert capture.mime_type == ("image/webp" if native else "image/png")
        assert (capture.width, capture.height) == ((47, 61) if native else (PAGE_WIDTH, PAGE_HEIGHT))
        assert _rgba_from_output(capture.data) == _rgba_from_png_data_url(expected["source" if native else "rendered"])
    assert adapter._captured_slots == [1, 2, 3]


async def test_younganimal_unsafe_or_missing_native_half_falls_back_for_whole_spread(
    browser_page, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # This checks atomic fallback/cleanup, not large-bitmap throughput. Keep the
    # synthetic readbacks small enough for its deliberately short operation budget.
    monkeypatch.setitem(globals(), "PAGE_WIDTH", 98)
    monkeypatch.setitem(globals(), "PAGE_HEIGHT", 133)
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_fixture(browser_page, native_source_slots=(1, 2), clip_slots=(1,))
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_MS", 20)
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_DEADLINE_MS", 500)
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_POLL_MS", 10)
    monkeypatch.setattr(younganimal_adapter_module, "PAGE_CHANGE_POLL_MS", 10)
    monkeypatch.setattr(younganimal_adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 2_000)

    class RecordingAdapter(YounganimalAdapter):
        def __init__(self) -> None:
            super().__init__(preflight_work_url=WORK_URL)
            self.capture_modes: list[str] = []
            self.native_cache_counts: list[dict[str, object]] = []

        async def capture_page(self, page):
            result = await super().capture_page(page)
            self.capture_modes.append(str(self._capture_diagnostics["mode"]))
            self.native_cache_counts.append(
                await page.evaluate("window.__younganimalNativeCapture.status()")
            )
            return result

    adapter = RecordingAdapter()
    output_dir = tmp_path / "younganimal-atomic-native-fallback"
    result = await CrawlerRunner(
        RunConfig(
            site="younganimal",
            source_url=EPISODE_URL,
            output_dir=output_dir,
            diagnostics_dir=tmp_path / "atomic-fallback-diagnostics",
            page_turn_delay_ms=0,
            max_pages=20,
            max_same_content=3,
            page_change_timeout_ms=2_000,
        )
    ).run(browser_page, adapter)

    assert result.stop_state is PageState.END
    assert adapter.capture_modes[0] == "rendered_canvas_png"  # clipped snapshot was unsupported
    assert adapter.capture_modes[1] == "rendered_canvas_png"  # slot 3 had no source candidate
    assert adapter.native_cache_counts[0]["candidateCount"] == 0
    assert adapter.native_cache_counts[0]["proofCount"] == 0
    assert {(page["width"], page["height"]) for page in json.loads(
        (output_dir / "manifest.json").read_text(encoding="utf-8")
    )["pages"]} == {(PAGE_WIDTH, PAGE_HEIGHT)}


@pytest.mark.parametrize(
    "mutation",
    [
        "remove_capability",
        "remove_base_direction",
        "contradict_phase_marker",
        "extra_body_center",
    ],
)
@pytest.mark.parametrize("no_top_pr", [False, True])
async def test_younganimal_odd_body_native_collector_rejects_invalid_profile_directly(
    browser_page, mutation: str, no_top_pr: bool,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_fixture(
        browser_page,
        initial_seek=13,
        native_source_slots=tuple(range(1, 8)),
        odd_body_count=7,
        no_top_pr=no_top_pr,
    )
    adapter = YounganimalAdapter(preflight_work_url=WORK_URL)
    await adapter.prepare_page(browser_page)
    await adapter.configure_run(browser_page, "auto")
    episode_url = adapter.resolve_initial_navigation_url(EPISODE_URL)
    await browser_page.goto(episode_url, wait_until="commit")
    await browser_page.wait_for_load_state("load")
    baseline_snapshot = await browser_page.evaluate(
        younganimal_adapter_module.SNAPSHOT_SCRIPT,
        {"pixelSlots": []},
    )
    baseline = younganimal_adapter_module._parse_viewer_observation(
        baseline_snapshot.get("snapshot"), expected_url=EPISODE_URL
    )
    assert baseline_snapshot.get("observerReady") is True
    assert baseline.layout_variant == ("top_empty_no_pr_odd_body" if no_top_pr else "standard_odd_body")
    assert baseline.seek_value == 13 and baseline.page_state == "content"
    assert baseline.active_slots == (1,)

    mutations = {
        "remove_capability": "document.querySelector('#comici-viewer').classList.remove('mode-has-good-page')",
        "remove_base_direction": "document.querySelector('#comici-viewer').classList.remove('mode-dir-rtl')",
        "contradict_phase_marker": "document.querySelector('#comici-viewer').classList.add('mode-ci-page')",
        "extra_body_center": "document.querySelector('#xCVPages').children[2].style.left='0px'",
    }
    await browser_page.evaluate(mutations[mutation])
    result = await browser_page.evaluate(
        younganimal_adapter_module.COLLECT_NATIVE_CAPTURE_SCRIPT,
        {
            "expectedSlots": [1],
            "expectedSeek": 13,
            "episodePath": urlsplit(EPISODE_URL).path,
            "maxPngChars": 8_000_000,
        },
    )

    assert result == {"mode": "fallback", "reason": "selected_page_changed"}
    assert await browser_page.evaluate("() => window.__younganimalNativeCapture.status()") == {
        "candidateCount": 0,
        "proofCount": 0,
        "integrity": True,
    }


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_horizontal", "missing_spread", "missing_direction", "missing_nav_direction",
        "missing_top_empty", "missing_pr_capability", "missing_good_capability",
        "forbidden_comic_info", "forbidden_vertical", "forbidden_single_page",
        "extra_center", "ci_tail_role", "top_pr_marker",
        "top_pr_lead_role",
    ],
)
async def test_younganimal_no_ci_native_collector_rejects_unobserved_profile_mutations(
    browser_page, mutation: str
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_fixture(
        browser_page,
        initial_seek=13,
        native_source_slots=tuple(range(1, 11)),
        top_empty_no_ci_body_count=10,
    )
    adapter = YounganimalAdapter(preflight_work_url=WORK_URL)
    await adapter.prepare_page(browser_page)
    await adapter.configure_run(browser_page, "auto")
    await browser_page.goto(adapter.resolve_initial_navigation_url(EPISODE_URL), wait_until="commit")
    await browser_page.wait_for_load_state("load")
    await adapter.initialize(browser_page)
    baseline_snapshot = await browser_page.evaluate(
        younganimal_adapter_module.SNAPSHOT_SCRIPT,
        {"pixelSlots": []},
    )
    baseline = younganimal_adapter_module._parse_viewer_observation(
        baseline_snapshot.get("snapshot"), expected_url=EPISODE_URL
    )
    assert baseline_snapshot.get("observerReady") is True
    assert baseline.layout_variant == "top_empty_no_ci"
    assert baseline.seek_value == baseline.seek_max == 15
    assert baseline.active_slots == (1,)

    mutations = {
        "missing_horizontal": "document.querySelector('#comici-viewer').classList.remove('mode-h')",
        "missing_spread": "document.querySelector('#comici-viewer').classList.remove('mode-spread')",
        "forbidden_comic_info": "document.querySelector('#comici-viewer').classList.add('mode-has-comic-info')",
        "forbidden_vertical": "document.querySelector('#comici-viewer').classList.add('mode-v')",
        "forbidden_single_page": "document.querySelector('#comici-viewer').classList.add('mode-single')",
        "missing_direction": "document.querySelector('#comici-viewer').classList.remove('mode-dir-rtl')",
        "missing_nav_direction": "document.querySelector('#comici-viewer').classList.remove('mode-nav-dir-rtl')",
        "missing_top_empty": "document.querySelector('#comici-viewer').classList.remove('mode-has-top-emptypage')",
        "missing_pr_capability": "document.querySelector('#comici-viewer').classList.remove('mode-has-pr')",
        "missing_good_capability": "document.querySelector('#comici-viewer').classList.remove('mode-has-good-page')",
        "extra_center": "document.querySelector('#xCVPages').children[4].style.left='0px'",
        "ci_tail_role": "document.querySelector('#xCVPages').children[11].className='-cv-page mode-ci'",
        "top_pr_marker": "document.querySelector('#comici-viewer').classList.add('mode-top-pr-page')",
        "top_pr_lead_role": "document.querySelector('#xCVPages').children[0].className='-cv-page mode-empty mode-pr mode-top-pr'",
    }
    await browser_page.evaluate(mutations[mutation])
    result = await browser_page.evaluate(
        younganimal_adapter_module.COLLECT_NATIVE_CAPTURE_SCRIPT,
        {
            "expectedSlots": [1],
            "expectedSeek": 15,
            "episodePath": urlsplit(EPISODE_URL).path,
            "maxPngChars": 8_000_000,
        },
    )

    assert result == {"mode": "fallback", "reason": "selected_page_changed"}
    assert await browser_page.evaluate("() => window.__younganimalNativeCapture.status()") == {
        "candidateCount": 0,
        "proofCount": 0,
        "integrity": True,
    }

async def test_younganimal_invalid_odd_profile_ci_scroll_is_capture_mutation(
    browser_page,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_fixture(
        browser_page,
        initial_seek=13,
        native_source_slots=tuple(range(1, 8)),
        odd_body_count=7,
    )
    adapter = YounganimalAdapter(preflight_work_url=WORK_URL)
    await adapter.prepare_page(browser_page)
    await adapter.configure_run(browser_page, "auto")
    await browser_page.goto(adapter.resolve_initial_navigation_url(EPISODE_URL), wait_until="commit")
    await browser_page.wait_for_load_state("load")
    baseline_snapshot = await browser_page.evaluate(
        younganimal_adapter_module.SNAPSHOT_SCRIPT,
        {"pixelSlots": []},
    )
    baseline = younganimal_adapter_module._parse_viewer_observation(
        baseline_snapshot.get("snapshot"), expected_url=EPISODE_URL
    )
    assert baseline.layout_variant == "standard_odd_body"
    assert baseline.seek_value == 13

    before = await browser_page.evaluate("() => window.__younganimalViewerCapture.inspect([])")
    await browser_page.evaluate("() => document.querySelector('#comici-viewer').classList.remove('mode-has-good-page')")
    await browser_page.evaluate("() => new Promise(resolve => requestAnimationFrame(resolve))")
    invalid = await browser_page.evaluate("() => window.__younganimalViewerCapture.inspect([])")
    await browser_page.evaluate("""() => {
      const pages = document.querySelector('#xCVPages');
      const ci = pages.children[pages.children.length - 5];
      const widget = ci.querySelector(':scope > .-cv-ci.-cv-page-content > .-cv-ci-content');
      if (!widget) throw new Error('fixture_ci_scroll_widget_missing');
      widget.classList.add('mode-scroll-bottom');
    }""")
    await browser_page.evaluate("() => new Promise(resolve => requestAnimationFrame(resolve))")
    after = await browser_page.evaluate("() => window.__younganimalViewerCapture.inspect([])")
    mutations = await browser_page.evaluate(
        "from => window.__younganimalViewerCapture.mutationsSince(from)", invalid["domGeneration"]
    )
    widget_rows = [
        row for row in mutations["records"]
        if row.get("attributeName") == "class"
        and row.get("classAdded") == ["mode-scroll-bottom"]
    ]

    assert invalid["captureDomGeneration"] > before["captureDomGeneration"]
    assert after["captureDomGeneration"] > invalid["captureDomGeneration"]
    assert len(widget_rows) == 1
    assert widget_rows[0]["ciScrollWidgetClassNoop"] is False
    assert widget_rows[0]["captureGeneration"] > invalid["captureDomGeneration"]


@pytest.mark.parametrize(
    "mutation",
    [
        "redraw",
        "same_value_reset_redraw",
        "replacement",
        "replacement_resized",
        "resized",
        "layout_translation",
        "transient_nav_class",
        "root_class_noop",
        "transient_selected_class",
        "transient_structure",
        "rect_rounding_boundary",
        "observer_summary_failure",
        "ci_class_changed_restored",
        "ci_namespaced_class_changed_restored",
        "ci_unknown_extra",
        "ci_nbsp",
        "ci_vertical_tab",
        "ci_scroll_widget_unknown_transition",
        "ci_scroll_widget_visible_overlap",
        "ci_scroll_widget_visible_overlap_overflow",
        "ci_scroll_widget_ambiguous_active_geometry",
        "ci_scroll_widget_ambiguous_active_geometry_overflow",
        "ci_scroll_widget_overflow_noop_ambiguous_active_geometry",
        "ci_scroll_widget_other_parent",
        "ci_scroll_widget_other_parent_overflow",
        "ci_scroll_widget_reparented",
        "ci_scroll_widget_reparented_overflow",
        "ci_scroll_widget_replaced",
        "ci_scroll_widget_missing",
        "ci_scroll_widget_namespaced",
        "ci_scroll_widget_namespaced_overflow",
        "ci_scroll_widget_scroll_removed",
        "ci_scroll_widget_scroll_removed_overflow",
        "ci_scroll_widget_overflow_unknown_extra",
        "ci_id_noop",
        "selected_wrapper_noop",
        "nonselected_wrapper_noop",
        "replacement_standard15_body",
        "layout_translation_standard15_body",
        "root_class_noop_standard15_body",
        "replacement_single_pr",
        "replacement_three_pr",
        "replacement_two_body",
        "replacement_one_body",
        "root_class_noop_single_pr",
        "replacement_no_top_pr_odd",
        "public_seek_last_no_top_pr_odd",
        "public_seek_last_standard7_body",
        "replacement_top_empty_no_ci",
        "no_ci_wrapper_replacement_top_empty_no_ci",
        "no_ci_tail_role_top_empty_no_ci",
        "no_ci_fake_ci_widget_noop_top_empty_no_ci",
        "public_seek_last_top_empty_no_ci",
        "public_seek_last_hidden_marker_top_empty_no_ci",
        "public_seek_last_missing_marker_top_empty_no_ci",
        "public_seek_last_duplicate_marker_top_empty_no_ci",
        "public_seek_last_wrong_parent_marker_top_empty_no_ci",
        "public_seek_last_offscreen_marker_top_empty_no_ci",
    ],
)
async def test_younganimal_native_post_python_mutation_stops_without_saving_page(
    browser_page, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mutation: str
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    standard15_body = mutation.endswith("_standard15_body")
    standard7_body = mutation.endswith("_standard7_body")
    no_ci_profile = mutation.endswith("_top_empty_no_ci")
    pr_tail_profile = mutation.endswith(("_single_pr", "_three_pr"))
    tail_pr_count = 3 if mutation.endswith("_three_pr") else 1
    no_top_pr_odd = mutation.endswith("_no_top_pr_odd")
    two_body = mutation.endswith("_two_body")
    one_body = mutation.endswith("_one_body")
    overflow_case = mutation.endswith("_overflow")
    if one_body:
        mutation = mutation.removesuffix("_one_body")
    elif two_body:
        mutation = mutation.removesuffix("_two_body")
    elif no_top_pr_odd:
        mutation = mutation.removesuffix("_no_top_pr_odd")
    elif pr_tail_profile:
        mutation = mutation.removesuffix("_single_pr").removesuffix("_three_pr")
    elif no_ci_profile:
        mutation = mutation.removesuffix("_top_empty_no_ci")
    elif standard15_body:
        mutation = mutation.removesuffix("_standard15_body")
    elif standard7_body:
        mutation = mutation.removesuffix("_standard7_body")
    if overflow_case:
        mutation = mutation.removesuffix("_overflow")
    scroll_widget_case = mutation.startswith("ci_scroll_widget_")
    await _install_fixture(
        browser_page,
        native_source_slots=(2, 3) if scroll_widget_case else (1,),
        top_empty=scroll_widget_case,
        standard15_body=standard15_body,
        odd_body_count=7 if standard7_body or no_top_pr_odd else None,
        no_top_pr=no_top_pr_odd,
        top_empty_no_ci_body_count=10 if no_ci_profile else None,
        pr_tail_body_count=6 if pr_tail_profile else None,
        tail_pr_count=tail_pr_count,
        standard_body_count=1 if one_body else 2 if two_body else None,
    )
    if mutation in {"ci_namespaced_class_changed_restored", "ci_scroll_widget_namespaced"}:
        original_observer_script = younganimal_adapter_module.OBSERVER_INIT_SCRIPT
        test_namespaced_observer = """(() => {
          const NativeObserver = window.MutationObserver;
          window.MutationObserver = class extends NativeObserver {
            constructor(callback) {
              super(records => callback(records.filter(record => record.type !== 'attributes' ||
                (record.attributeNamespace === null && ['class', 'id'].includes(record.attributeName)) ||
                (record.attributeNamespace !== null && record.attributeName === 'class'))));
            }
            observe(target, options) {
              const testOptions = {...options};
              delete testOptions.attributeFilter;
              return super.observe(target, testOptions);
            }
          };
        })();
        """
        monkeypatch.setattr(
            younganimal_adapter_module,
            "OBSERVER_INIT_SCRIPT",
            test_namespaced_observer + original_observer_script,
        )
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_MS", 20)
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_DEADLINE_MS", 500)
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_POLL_MS", 10)
    monkeypatch.setattr(younganimal_adapter_module, "PAGE_CHANGE_POLL_MS", 10)
    monkeypatch.setattr(younganimal_adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 2_000)
    mutation_script = {
        "redraw": """const context = canvas.getContext('2d');
          context.fillStyle = 'rgb(1,2,3)'; context.fillRect(0, 0, 1, 1);""",
        "same_value_reset_redraw": """const width = canvas.width;
          canvas.setAttribute('width', String(width));
          const context = canvas.getContext('2d');
          context.drawImage(window.__yaSources[1], 0, 0, 47, 61, 0, 0, canvas.width, canvas.height);""",
        "replacement": """const replacement = canvas.cloneNode(); canvas.replaceWith(replacement);
          const capture = window.__younganimalViewerCapture;
          const original = capture.raw.getImageData;
          window.__yaPostproofTargetReadbacks = 0;
          capture.raw.getImageData = function(...args) {
            if (this.canvas?.isConnected && this.canvas.closest('.-cv-page'))
              window.__yaPostproofTargetReadbacks += 1;
            return Reflect.apply(original, this, args);
          };""",
        "no_ci_wrapper_replacement": """const pages = document.querySelector('#xCVPages');
          const wrapper = pages.children[1];
          wrapper.replaceWith(wrapper.cloneNode(true));""",
        "replacement_resized": """const replacement = canvas.cloneNode();
          replacement.width = canvas.width + 1; canvas.replaceWith(replacement);
          const capture = window.__younganimalViewerCapture;
          const original = capture.raw.getImageData;
          window.__yaPostproofTargetReadbacks = 0;
          capture.raw.getImageData = function(...args) {
            if (this.canvas?.isConnected && this.canvas.closest('.-cv-page'))
              window.__yaPostproofTargetReadbacks += 1;
            return Reflect.apply(original, this, args);
          };""",
        "resized": """const capture = window.__younganimalViewerCapture;
          const original = capture.raw.getImageData;
          window.__yaPostproofTargetReadbacks = 0;
          capture.raw.getImageData = function(...args) {
            if (this.canvas === canvas) window.__yaPostproofTargetReadbacks += 1;
            return Reflect.apply(original, this, args);
          };
          canvas.width = canvas.width + 1;""",
        "layout_translation": """const wrapper = document.querySelector('#xCVPages').children[1];
          wrapper.style.transform = 'translateX(7px)';""",
        "transient_nav_class": """const viewer = document.querySelector('#comici-viewer');
          const context = canvas.getContext('2d', {willReadFrequently: true});
          const beforePixels = new Uint8ClampedArray(
            context.getImageData(0, 0, canvas.width, canvas.height).data);
          viewer.classList.add('mode-nav-open');
          viewer.classList.remove('mode-nav-open');
          await new Promise(resolve => requestAnimationFrame(resolve));
          const afterCanvas = document.querySelector('#xCVPages').children[1].querySelector('canvas');
          const afterPixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
          let samePixels = beforePixels.length === afterPixels.length;
          for (let index = 0; samePixels && index < beforePixels.length; index += 1) {
            samePixels = beforePixels[index] === afterPixels[index];
          }
          window.__yaTransientNavMutationAudit = {
            sameNode: canvas === afterCanvas,
            samePixels,
          };""",
        "root_class_noop": """const viewer = document.querySelector('#comici-viewer');
          viewer.setAttribute('class', viewer.getAttribute('class'));""",
        "transient_selected_class": """const wrapper = document.querySelector('#xCVPages').children[1];
          wrapper.classList.add('mode-loading'); wrapper.classList.remove('mode-loading');""",
        "transient_structure": """const viewer = document.querySelector('#comici-viewer');
          const marker = document.createElement('span'); viewer.append(marker); marker.remove();""",
        "rect_rounding_boundary": """const viewer = document.querySelector('#comici-viewer');
          const before = canvas.getBoundingClientRect();
          let delta = null;
          for (let step = 1; step < 100 && delta === null; step += 1) {
            for (const sign of [1, -1]) {
              const candidate = sign * step / 10000;
              if (Math.round((before.x + candidate) * 100) !== Math.round(before.x * 100)) {
                delta = candidate; break;
              }
            }
          }
          if (delta === null) throw new Error('could_not_choose_rounding_boundary');
          canvas.style.transform = `translateX(${delta}px)`;
          const after = canvas.getBoundingClientRect();
          window.__yaRectRoundingAudit = {
            rawTargetSame: Math.abs(after.x - before.x) < 0.01,
            roundedTargetSame: Math.abs(Math.round(after.x * 100) - Math.round(before.x * 100)) < 1,
          };
          viewer.setAttribute('class', viewer.className);""",
        "observer_summary_failure": """const viewer = document.querySelector('#comici-viewer');
          const classValue = viewer.className;
          const original = Element.prototype.getAttribute;
          let didThrow = false;
          Element.prototype.getAttribute = function(name) {
            if (!didThrow && this === viewer && name === 'class') {
              didThrow = true; throw new Error('diagnostic test fault');
            }
            return Reflect.apply(original, this, [name]);
          };
          viewer.setAttribute('class', classValue);
          const marker = document.createElement('span'); viewer.append(marker);
          await new Promise(resolve => requestAnimationFrame(resolve));
          Element.prototype.getAttribute = original;
          window.__yaMutationSummaryFaultObserved = didThrow;""",
        "ci_class_changed_restored": """const pages = document.querySelector('#xCVPages');
          const ci = pages.children[pages.children.length - 5];
          ci.classList.add('mode-diagnostic-extra');
          ci.classList.remove('mode-diagnostic-extra');""",
        "ci_namespaced_class_changed_restored": """const pages = document.querySelector('#xCVPages');
          const ci = pages.children[pages.children.length - 5];
          ci.setAttributeNS('urn:fixture', 'fixture:class', 'private-user-token');
          ci.setAttribute('class', '-cv-page  mode-ci');
          ci.setAttributeNS('urn:fixture', 'fixture:class', '-cv-page mode-ci');
          ci.setAttribute('class', '-cv-page mode-ci');""",
        "ci_unknown_extra": """const pages = document.querySelector('#xCVPages');
          const ci = pages.children[pages.children.length - 5];
          ci.classList.add('private-user-token');""",
        "ci_nbsp": """const pages = document.querySelector('#xCVPages');
          const ci = pages.children[pages.children.length - 5];
          ci.setAttribute('class', '-cv-page mode-ci' + String.fromCharCode(160));""",
        "ci_vertical_tab": """const pages = document.querySelector('#xCVPages');
          const ci = pages.children[pages.children.length - 5];
          ci.setAttribute('class', '-cv-page mode-ci' + String.fromCharCode(11));""",
        "ci_scroll_widget_unknown_transition": """const pages = document.querySelector('#xCVPages');
          const ci = pages.children[pages.children.length - 5];
          const widget = ci.querySelector(':scope > .-cv-ci.-cv-page-content > .-cv-ci-content');
          widget.classList.add('mode-scroll-unknown');""",
        "ci_scroll_widget_overflow_unknown_extra": """const pages = document.querySelector('#xCVPages');
          const ci = pages.children[pages.children.length - 5];
          const widget = ci.querySelector(':scope > .-cv-ci.-cv-page-content > .-cv-ci-content');
          widget.classList.add('mode-overflow', 'private-user-token');""",
        "ci_scroll_widget_overflow_noop_ambiguous_active_geometry": """const pages = document.querySelector('#xCVPages');
          const ci = pages.children[pages.children.length - 5];
          const activeBody = pages.children[2];
          activeBody.append(document.createElement('canvas'));
          const widget = ci.querySelector(':scope > .-cv-ci.-cv-page-content > .-cv-ci-content');
          widget.classList.add('mode-overflow');
          widget.setAttribute('class', widget.getAttribute('class'));""",
        "ci_scroll_widget_visible_overlap": """const pages = document.querySelector('#xCVPages');
          const ci = pages.children[pages.children.length - 5];
          const activeBody = pages.children[2];
          ci.style.left = `${activeBody.getBoundingClientRect().left}px`;
          const widget = ci.querySelector(':scope > .-cv-ci.-cv-page-content > .-cv-ci-content');
          widget.classList.add('mode-scroll-bottom');""",
        "ci_scroll_widget_ambiguous_active_geometry": """const pages = document.querySelector('#xCVPages');
          const ci = pages.children[pages.children.length - 5];
          const activeBody = pages.children[2];
          activeBody.append(document.createElement('canvas'));
          const widget = ci.querySelector(':scope > .-cv-ci.-cv-page-content > .-cv-ci-content');
          widget.classList.add('mode-scroll-bottom');""",
        "ci_scroll_widget_other_parent": """const pages = document.querySelector('#xCVPages');
          const widget = pages.children[2].querySelector('.-cv-ci-content');
          if (!widget) throw new Error('fixture_body_scroll_decoy_missing');
          widget.classList.add('mode-scroll-bottom');""",
        "ci_scroll_widget_reparented": """const pages = document.querySelector('#xCVPages');
          const ci = pages.children[pages.children.length - 5];
          const widget = ci.querySelector(':scope > .-cv-ci.-cv-page-content > .-cv-ci-content');
          const otherParent = document.createElement('div'); otherParent.className = '-cv-other';
          widget.parentElement.append(otherParent); otherParent.append(widget);
          widget.classList.add('mode-scroll-bottom');""",
        "ci_scroll_widget_replaced": """const pages = document.querySelector('#xCVPages');
          const ci = pages.children[pages.children.length - 5];
          const widget = ci.querySelector(':scope > .-cv-ci.-cv-page-content > .-cv-ci-content');
          const replacement = widget.cloneNode(true); widget.replaceWith(replacement);
          replacement.classList.add('mode-scroll-bottom');""",
        "ci_scroll_widget_missing": """const pages = document.querySelector('#xCVPages');
          const ci = pages.children[pages.children.length - 5];
          const decoy = document.createElement('div'); decoy.className = '-cv-ci-content';
          ci.append(decoy); decoy.classList.add('mode-scroll-bottom');""",
        "ci_scroll_widget_namespaced": """const pages = document.querySelector('#xCVPages');
          const ci = pages.children[pages.children.length - 5];
          const widget = ci.querySelector(':scope > .-cv-ci.-cv-page-content > .-cv-ci-content');
          widget.setAttributeNS('urn:fixture', 'fixture:class', 'mode-scroll-bottom');""",
        "ci_scroll_widget_scroll_removed": """const pages = document.querySelector('#xCVPages');
          const ci = pages.children[pages.children.length - 5];
          const widget = ci.querySelector(':scope > .-cv-ci.-cv-page-content > .-cv-ci-content');
          widget.setAttribute('class', '-cv-ci-content');""",
        "ci_id_noop": """const pages = document.querySelector('#xCVPages');
          const ci = pages.children[pages.children.length - 5];
          ci.setAttribute('id', ci.getAttribute('id') || 'ya-ci-test');
          ci.setAttribute('id', ci.getAttribute('id'));""",
        "selected_wrapper_noop": """const wrapper = document.querySelector('#xCVPages').children[1];
          wrapper.setAttribute('class', wrapper.getAttribute('class'));""",
        "nonselected_wrapper_noop": """const wrapper = document.querySelector('#xCVPages').children[2];
          wrapper.setAttribute('class', wrapper.getAttribute('class'));""",
        "public_seek_last": """const seek = document.querySelector('#xCVSeekBar');
          seek.value = seek.min;
          seek.dispatchEvent(new Event('input', {bubbles: true}));
          seek.dispatchEvent(new Event('change', {bubbles: true}));""",
        "public_seek_last_hidden_marker": """const seek = document.querySelector('#xCVSeekBar');
          seek.value = seek.min;
          seek.dispatchEvent(new Event('input', {bubbles: true}));
          seek.dispatchEvent(new Event('change', {bubbles: true}));
          const last = document.querySelector('#xCVPages').children[14];
          last.removeAttribute('id');
          const previous = last.querySelector('#xCVLastPage');
          if (previous) previous.removeAttribute('id');
          const marker = document.createElement('div');
          marker.id = 'xCVLastPage';
          marker.style.cssText = 'position:absolute;left:50%;top:50%;width:20px;height:20px;visibility:hidden';
          last.append(marker);""",
        "public_seek_last_missing_marker": """const seek = document.querySelector('#xCVSeekBar');
          seek.value = seek.min;
          seek.dispatchEvent(new Event('input', {bubbles: true}));
          seek.dispatchEvent(new Event('change', {bubbles: true}));
          document.querySelector('#xCVLastPage').removeAttribute('id');""",
        "public_seek_last_duplicate_marker": """const seek = document.querySelector('#xCVSeekBar');
          seek.value = seek.min;
          seek.dispatchEvent(new Event('input', {bubbles: true}));
          seek.dispatchEvent(new Event('change', {bubbles: true}));
          document.querySelector('#xCVPages').children[0].id = 'xCVLastPage';""",
        "public_seek_last_wrong_parent_marker": """const seek = document.querySelector('#xCVSeekBar');
          seek.value = seek.min;
          seek.dispatchEvent(new Event('input', {bubbles: true}));
          seek.dispatchEvent(new Event('change', {bubbles: true}));
          const marker = document.querySelector('#xCVLastPage');
          document.querySelector('#xCVPages').children[13].append(marker);""",
        "public_seek_last_offscreen_marker": """const seek = document.querySelector('#xCVSeekBar');
          seek.value = seek.min;
          seek.dispatchEvent(new Event('input', {bubbles: true}));
          seek.dispatchEvent(new Event('change', {bubbles: true}));
          const last = document.querySelector('#xCVPages').children[14];
          last.removeAttribute('id');
          const previous = last.querySelector('#xCVLastPage');
          if (previous) previous.removeAttribute('id');
          const marker = document.createElement('div');
          marker.id = 'xCVLastPage';
          marker.style.cssText = 'position:absolute;left:50%;top:50%;width:20px;height:20px';
          marker.style.transform = 'translateX(3000px)';
          last.append(marker);""",
        "no_ci_tail_role": """document.querySelector('#xCVPages').children[13].className = '-cv-page mode-last';""",
        "no_ci_fake_ci_widget_noop": """const pages = document.querySelector('#xCVPages');
          const widget = pages.children[14].querySelector(
            ':scope > .-cv-ci.-cv-page-content > .-cv-ci-content');
          if (!widget) throw new Error('fixture_fake_ci_widget_missing');
          widget.setAttribute('class', widget.getAttribute('class'));""",
    }[mutation]
    if overflow_case:
        mutation_script = mutation_script.replace("mode-scroll-bottom", "mode-overflow")
    monkeypatch.setattr(
        younganimal_adapter_module,
        "VERIFY_NATIVE_CAPTURE_SCRIPT",
        f"""async token => {{
          const canvas = document.querySelector('#xCVPages').children[1].querySelector('canvas');
          {mutation_script}
          await new Promise(resolve => requestAnimationFrame(resolve));
          const result = await window.__younganimalNativeCapture.verify(token);
          if ('{mutation}'.startsWith('public_seek_last')) {{
            const observed = result.details?.observed;
            window.__yaLastLayoutAudit = observed ? {{
              layoutAvailable: observed.layoutAvailable,
              layoutVariant: observed.layoutVariant,
              activeSlots: observed.activeSlots,
            }} : null;
          }}
          return result;
        }}""",
    )
    output_dir = tmp_path / "younganimal-native-postproof-mutation"

    adapter = YounganimalAdapter(preflight_work_url=WORK_URL)
    if mutation in {
        "ci_namespaced_class_changed_restored", "ci_scroll_widget_namespaced",
        "ci_scroll_widget_missing", "ci_scroll_widget_other_parent",
        "ci_scroll_widget_scroll_removed",
    }:
        original_initialize = adapter.initialize

        async def initialize_with_namespaced_ci(page) -> None:
            await original_initialize(page)
            setup_script = """mutation => {
              const pages = document.querySelector('#xCVPages');
              const ci = pages.children[pages.children.length - 5];
              if (mutation === 'ci_namespaced_class_changed_restored') {
                ci.setAttributeNS('urn:fixture', 'fixture:class', '-cv-page mode-ci');
              } else if (mutation === 'ci_scroll_widget_namespaced') {
                ci.querySelector(':scope > .-cv-ci.-cv-page-content > .-cv-ci-content')
                  .setAttributeNS('urn:fixture', 'fixture:class', '-cv-ci-content');
              } else if (mutation === 'ci_scroll_widget_missing') {
                ci.querySelector(':scope > .-cv-ci.-cv-page-content > .-cv-ci-content').remove();
              } else if (mutation === 'ci_scroll_widget_other_parent') {
                const wrapper = pages.children[2];
                const parent = document.createElement('div');
                parent.className = '-cv-ci -cv-page-content';
                parent.style.cssText = 'position:absolute;left:-30000px;top:0;width:628px;height:886px';
                const widget = document.createElement('div');
                widget.className = '-cv-ci-content';
                widget.style.cssText = 'position:absolute;left:90px;top:207px;width:450px;height:470px';
                parent.append(widget); wrapper.append(parent);
              } else if (mutation === 'ci_scroll_widget_scroll_removed') {
                ci.querySelector(':scope > .-cv-ci.-cv-page-content > .-cv-ci-content')
                  .classList.add('mode-scroll-bottom');
              }
              return new Promise(resolve => requestAnimationFrame(resolve));
            }"""
            if overflow_case:
                setup_script = setup_script.replace("mode-scroll-bottom", "mode-overflow")
            await page.evaluate(setup_script, mutation)

        monkeypatch.setattr(adapter, "initialize", initialize_with_namespaced_ci)
    if mutation == "no_ci_fake_ci_widget_noop":
        original_initialize = adapter.initialize

        async def initialize_with_fake_ci_widget(page) -> None:
            await original_initialize(page)
            await page.evaluate("""() => {
              const last = document.querySelector('#xCVPages').children[14];
              const holder = document.createElement('div');
              holder.className = '-cv-ci -cv-page-content';
              const widget = document.createElement('div');
              widget.className = '-cv-ci-content';
              holder.append(widget); last.append(holder);
            }""")

        monkeypatch.setattr(adapter, "initialize", initialize_with_fake_ci_widget)
    locator_fallbacks: list[object] = []
    original_get_capture_targets = adapter.get_capture_targets

    async def track_locator_fallback(page):
        locator_fallbacks.append(page)
        return await original_get_capture_targets(page)

    monkeypatch.setattr(adapter, "get_capture_targets", track_locator_fallback)
    with pytest.raises(UnknownPageStateError, match="native post-encoding proof failed"):
        await CrawlerRunner(
            RunConfig(
                site="younganimal",
                source_url=EPISODE_URL,
                output_dir=output_dir,
                diagnostics_dir=tmp_path / "native-postproof-diagnostics",
                page_turn_delay_ms=0,
                max_pages=20,
                max_same_content=3,
                page_change_timeout_ms=2_000,
            )
        ).run(browser_page, adapter)

    assert not list(output_dir.glob("page-*.*"))
    assert locator_fallbacks == []
    status = await browser_page.evaluate("() => window.__younganimalNativeCapture.status()")
    assert status == {"candidateCount": 0, "proofCount": 0, "integrity": True}
    diagnostics = await adapter.collect_debug_metadata(browser_page)
    capture_diagnostics = diagnostics["capture"]
    assert capture_diagnostics["mode"] == "native_capture_failed"
    assert capture_diagnostics["stage"] == "native_post_encoding_verify"
    expected_reasons = {
        "redraw": "native_target_generation_or_write_changed",
        "same_value_reset_redraw": "native_target_generation_or_write_changed",
        "replacement": "native_reader_layout_changed",
        "replacement_resized": "native_reader_layout_changed",
        "resized": "native_target_generation_or_write_changed",
        "layout_translation": "native_target_layout_changed",
        "transient_nav_class": "native_reader_layout_changed",
        "root_class_noop": "native_reader_layout_changed",
        "transient_selected_class": "native_reader_layout_changed",
        "transient_structure": "native_reader_layout_changed",
        "rect_rounding_boundary": "native_reader_layout_changed",
        "observer_summary_failure": "native_reader_layout_changed",
        "ci_class_changed_restored": "native_reader_layout_changed",
        "ci_namespaced_class_changed_restored": "native_reader_layout_changed",
        "ci_unknown_extra": "native_reader_layout_changed",
        "ci_nbsp": "native_reader_layout_changed",
        "ci_vertical_tab": "native_reader_layout_changed",
        "ci_scroll_widget_unknown_transition": "native_reader_layout_changed",
        "ci_scroll_widget_overflow_unknown_extra": "native_reader_layout_changed",
        "ci_scroll_widget_overflow_noop_ambiguous_active_geometry": "native_reader_layout_changed",
        "ci_scroll_widget_visible_overlap": "native_reader_layout_changed",
        "ci_scroll_widget_ambiguous_active_geometry": "native_reader_layout_changed",
        "ci_scroll_widget_other_parent": "native_reader_layout_changed",
        "ci_scroll_widget_reparented": "native_reader_layout_changed",
        "ci_scroll_widget_replaced": "native_reader_layout_changed",
        "ci_scroll_widget_missing": "native_reader_layout_changed",
        "ci_scroll_widget_namespaced": "native_reader_layout_changed",
        "ci_scroll_widget_scroll_removed": "native_reader_layout_changed",
        "ci_id_noop": "native_reader_layout_changed",
        "selected_wrapper_noop": "native_reader_layout_changed",
        "nonselected_wrapper_noop": "native_reader_layout_changed",
        "public_seek_last": "native_reader_layout_changed",
        "public_seek_last_hidden_marker": "native_reader_layout_changed",
        "public_seek_last_missing_marker": "native_reader_layout_changed",
        "public_seek_last_duplicate_marker": "native_reader_layout_changed",
        "public_seek_last_wrong_parent_marker": "native_reader_layout_changed",
        "public_seek_last_offscreen_marker": "native_reader_layout_changed",
        "no_ci_wrapper_replacement": "native_reader_layout_changed",
        "no_ci_tail_role": "native_reader_layout_changed",
        "no_ci_fake_ci_widget_noop": "native_reader_layout_changed",
    }
    assert capture_diagnostics["reason"] == expected_reasons[mutation]
    assert capture_diagnostics["initial_canvas_quiet"]["status"] == "settled"
    detail = capture_diagnostics["details"]
    assert detail["available"] is True
    expected_active_slots = [2, 3] if scroll_widget_case else [1]
    assert detail["expected"]["activeSlots"] == expected_active_slots
    assert detail["observed"]["viewerIdentity"] is True
    no_ci_invalid_layout = mutation in {
        "no_ci_tail_role",
        "public_seek_last_hidden_marker",
        "public_seek_last_missing_marker",
        "public_seek_last_duplicate_marker",
        "public_seek_last_wrong_parent_marker",
        "public_seek_last_offscreen_marker",
    }
    assert detail["observed"]["layoutAvailable"] is (
        mutation not in {"ci_unknown_extra", "ci_nbsp", "ci_vertical_tab"}
        and not no_ci_invalid_layout
    )
    assert type(detail["expected"]["captureDomGeneration"]) is int
    assert type(detail["observed"]["captureDomGeneration"]) is int
    if mutation == "no_ci_fake_ci_widget_noop":
        assert detail["observed"]["captureDomGeneration"] > detail["expected"]["captureDomGeneration"]
        noop_rows = [
            record for record in detail["mutations"]["records"]
            if record["kind"] == "attributes"
            and record["attributeName"] == "class"
            and record["targetArea"] == "wrapper_descendant"
            and record["slot"] == 14
            and record["sameAssignment"] is True
        ]
        assert len(noop_rows) == 1
        assert noop_rows[0]["ciScrollWidgetTarget"] is False
        assert noop_rows[0]["ciScrollWidgetClassNoop"] is False
    assert detail["observed"]["queryPresent"] is False
    assert detail["observed"]["hashPresent"] is False
    if mutation.startswith("public_seek_last"):
        expected_layout_available = mutation == "public_seek_last"
        assert await browser_page.evaluate("() => window.__yaLastLayoutAudit") == {
            "layoutAvailable": expected_layout_available,
            "layoutVariant": (
                None if not expected_layout_available
                else "top_empty_no_pr_odd_body" if no_top_pr_odd
                else "top_empty_no_ci" if no_ci_profile else "standard_odd_body"
            ),
            "activeSlots": [] if expected_layout_available else None,
        }
        terminal_snapshot = await browser_page.evaluate(
            younganimal_adapter_module.SNAPSHOT_SCRIPT,
            {"pixelSlots": []},
        )
        assert terminal_snapshot.get("observerReady") is True
        if not expected_layout_available:
            with pytest.raises(UnknownPageStateError):
                younganimal_adapter_module._parse_viewer_observation(
                    terminal_snapshot.get("snapshot"), expected_url=EPISODE_URL
                )
        else:
            terminal = younganimal_adapter_module._parse_viewer_observation(
                terminal_snapshot.get("snapshot"), expected_url=EPISODE_URL
            )
            assert terminal.page_state == "end"
        if no_ci_profile and mutation in {
            "public_seek_last_hidden_marker",
            "public_seek_last_offscreen_marker",
        }:
            assert terminal_snapshot["snapshot"]["slots"][-1]["wrapperCenterInViewport"] is True
    assert len(detail["selected"]) == len(expected_active_slots)
    for selected in detail["selected"]:
        expected_target_same = mutation not in {
            "replacement", "replacement_resized", "no_ci_wrapper_replacement"
        }
        if mutation in {
            "ci_scroll_widget_ambiguous_active_geometry",
            "ci_scroll_widget_overflow_noop_ambiguous_active_geometry",
        } and selected["slot"] == 2:
            expected_target_same = False
        assert selected["targetSame"] is expected_target_same, selected
        assert type(selected["proofGeneration"]) is int
        assert type(selected["proofWrites"]) is int
        if mutation in {"redraw", "same_value_reset_redraw"}:
            assert not (selected["generationMatches"] and selected["writesMatch"])
        elif mutation not in {
            "replacement", "replacement_resized", "resized", "no_ci_wrapper_replacement"
        } and not (
                mutation in {
                    "ci_scroll_widget_ambiguous_active_geometry",
                    "ci_scroll_widget_overflow_noop_ambiguous_active_geometry",
                } and selected["slot"] == 2
        ):
            assert selected["generationMatches"] is True
            assert selected["writesMatch"] is True
        readback_unavailable = mutation in {
            "replacement", "replacement_resized", "resized", "no_ci_wrapper_replacement"
        } or (
            mutation in {
                "ci_scroll_widget_ambiguous_active_geometry",
                "ci_scroll_widget_overflow_noop_ambiguous_active_geometry",
            } and selected["slot"] == 2
        )
        if readback_unavailable:
            assert selected["readbackAvailable"] is False
            assert selected["contextMatches"] is None
            assert selected["pixelsMatchProof"] is None
            assert selected["replayMatchesProof"] is None
            if mutation not in {
                "ci_scroll_widget_ambiguous_active_geometry",
                "ci_scroll_widget_overflow_noop_ambiguous_active_geometry",
                "no_ci_wrapper_replacement",
            }:
                assert await browser_page.evaluate("() => window.__yaPostproofTargetReadbacks") == 0
            if mutation in {"replacement_resized", "resized"}:
                assert selected["width"] == selected["proofWidth"] + 1
                assert selected["height"] == selected["proofHeight"]
        else:
            assert selected["readbackAvailable"] is True
            assert selected["pixelsMatchProof"] is (mutation not in {"redraw"})
    assert detail["mutations"]["available"] is True
    if mutation == "observer_summary_failure":
        assert await browser_page.evaluate("() => window.__yaMutationSummaryFaultObserved") is True
        assert detail["mutations"]["complete"] is False
        assert detail["mutations"]["coverageContiguous"] is False
        assert detail["mutations"]["unrecordedCount"] >= 1
        assert detail["mutations"]["toGeneration"] >= detail["mutations"]["fromGeneration"] + 2
        assert detail["observed"]["captureDomGeneration"] > detail["expected"]["captureDomGeneration"]
        assert detail["selected"][0]["generationMatches"] is True
        assert detail["selected"][0]["writesMatch"] is True
        assert detail["selected"][0]["pixelsMatchProof"] is True
    else:
        assert detail["mutations"]["complete"] is True
        assert detail["mutations"]["coverageContiguous"] is True
    if mutation in {
        "ci_class_changed_restored", "ci_namespaced_class_changed_restored",
        "ci_unknown_extra", "ci_nbsp", "ci_vertical_tab",
        "ci_scroll_widget_overflow_unknown_extra",
        "ci_scroll_widget_overflow_noop_ambiguous_active_geometry",
        "ci_id_noop", "selected_wrapper_noop", "nonselected_wrapper_noop",
        "ci_scroll_widget_unknown_transition", "ci_scroll_widget_other_parent",
        "ci_scroll_widget_reparented", "ci_scroll_widget_replaced", "ci_scroll_widget_missing",
        "ci_scroll_widget_namespaced", "ci_scroll_widget_scroll_removed",
    }:
        assert detail["observed"]["captureDomGeneration"] > detail["expected"]["captureDomGeneration"]
    if mutation.startswith("ci_scroll_widget_"):
        records = detail["mutations"]["records"]
        if mutation == "ci_scroll_widget_unknown_transition":
            assert any(
                record["ciScrollWidgetTarget"] is True
                and record["ciScrollWidgetClassNoop"] is False
                for record in records
            )
        elif mutation == "ci_scroll_widget_overflow_unknown_extra":
            assert any(
                record["ciScrollWidgetTarget"] is True
                and record["ciScrollWidgetClassNoop"] is False
                and record["classAdded"] == ["mode-overflow"]
                for record in records
            )
        elif mutation == "ci_scroll_widget_overflow_noop_ambiguous_active_geometry":
            assert any(record["kind"] == "childList" and record["slot"] == 2 for record in records)
            widget_records = [
                record for record in records
                if record["ciScrollWidgetTarget"] is True
            ]
            assert len(widget_records) == 2
            assert all(record["ciScrollWidgetClassNoop"] is False for record in widget_records)
            assert widget_records[0]["classAdded"] == ["mode-overflow"]
            assert widget_records[1]["sameAssignment"] is True
        elif mutation == "ci_scroll_widget_visible_overlap":
            assert detail["observed"]["captureDomGeneration"] == detail["expected"]["captureDomGeneration"] + 1
            assert any(
                record["ciScrollWidgetTarget"] is True
                and record["ciScrollWidgetClassNoop"] is False
                and record["classAdded"] == ["mode-overflow" if overflow_case else "mode-scroll-bottom"]
                for record in records
            )
        elif mutation == "ci_scroll_widget_ambiguous_active_geometry":
            assert detail["observed"]["captureDomGeneration"] == detail["expected"]["captureDomGeneration"] + 2
            assert any(record["kind"] == "childList" and record["slot"] == 2 for record in records)
            assert any(
                record["ciScrollWidgetTarget"] is True
                and record["ciScrollWidgetClassNoop"] is False
                and record["classAdded"] == ["mode-overflow" if overflow_case else "mode-scroll-bottom"]
                for record in records
            )
        elif mutation == "ci_scroll_widget_other_parent":
            assert any(
                record["slot"] == 2 and record["ciScrollWidgetTarget"] is False
                for record in records
            )
        elif mutation == "ci_scroll_widget_reparented":
            assert any(
                record["slot"] == 46 and record["ciScrollWidgetTarget"] is False
                for record in records
            )
        elif mutation == "ci_scroll_widget_replaced":
            assert any(
                record["kind"] == "childList" and record["slot"] == 46
                for record in records
            )
        elif mutation == "ci_scroll_widget_missing":
            assert any(
                record["slot"] == 46 and record["targetArea"] == "wrapper_descendant"
                and record["ciScrollWidgetTarget"] is False
                for record in records
            )
        elif mutation == "ci_scroll_widget_namespaced":
            assert any(record["namespacePresent"] is True for record in records)
            assert all(record["ciScrollWidgetTarget"] is not True for record in records)
        elif mutation == "ci_scroll_widget_scroll_removed":
            assert any(
                record["ciScrollWidgetTarget"] is True
                and record["ciScrollWidgetClassNoop"] is False
                for record in records
            )
    if mutation == "ci_class_changed_restored":
        assert detail["observed"]["captureDomGeneration"] == detail["expected"]["captureDomGeneration"] + 2
        changed_ci_records = [
            record for record in detail["mutations"]["records"]
            if record["canonicalCiWrapper"] is True
        ]
        assert len(changed_ci_records) == 2
        assert all(record["canonicalCiClassNoop"] is False for record in changed_ci_records)
    if mutation == "ci_namespaced_class_changed_restored":
        assert detail["observed"]["captureDomGeneration"] == (
            detail["expected"]["captureDomGeneration"] + 2
        )
        records = detail["mutations"]["records"]
        namespaced_ci_records = [
            record for record in records
            if record["targetArea"] == "wrapper" and record["namespacePresent"] is True
        ]
        ordinary_ci_records = [
            record for record in records
            if record["targetArea"] == "wrapper" and record["attributeName"] == "class"
            and record["namespacePresent"] is False
        ]
        assert len(namespaced_ci_records) == 2
        assert all(record["attributeName"] == "class" for record in namespaced_ci_records)
        assert all(record["changed"] is None for record in namespaced_ci_records)
        assert all(record["sameAssignment"] is None for record in namespaced_ci_records)
        assert all(record["canonicalCiClassNoop"] is False for record in namespaced_ci_records)
        assert len(ordinary_ci_records) == 2
        assert all(record["canonicalCiClassNoop"] is True for record in ordinary_ci_records)
    if mutation in {"transient_nav_class", "root_class_noop", "transient_selected_class", "transient_structure"}:
        assert detail["mutations"]["records"]
    serialized = json.dumps(capture_diagnostics, ensure_ascii=True)
    assert "data:image" not in serialized
    assert "younganimal.com" not in serialized
    assert "private-user-token" not in serialized
    persisted = json.loads(
        (tmp_path / "native-postproof-diagnostics" / "metadata.json").read_text(encoding="utf-8")
    )
    assert persisted["adapter_debug"]["capture"] == capture_diagnostics
    if mutation == "transient_nav_class":
        audit = await browser_page.evaluate("() => window.__yaTransientNavMutationAudit")
        assert audit == {"sameNode": True, "samePixels": True}
    if mutation == "root_class_noop":
        root_record = next(
            record for record in detail["mutations"]["records"]
            if record["targetArea"] == "viewer" and record["attributeName"] == "class"
        )
        assert root_record["sameAssignment"] is True
    if mutation == "transient_structure":
        assert any(record["kind"] == "childList" for record in detail["mutations"]["records"])
    if mutation == "rect_rounding_boundary":
        audit = await browser_page.evaluate("() => window.__yaRectRoundingAudit")
        assert audit["rawTargetSame"] is True
        assert audit["roundedTargetSame"] is False
        assert detail["selected"][0]["rectsSame"] is audit["rawTargetSame"]


async def test_younganimal_mutation_journal_is_bounded_and_marks_lost_coverage(
    browser_page,
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    await _install_fixture(browser_page)
    adapter = YounganimalAdapter(preflight_work_url=WORK_URL)
    await adapter.prepare_page(browser_page)
    await browser_page.goto(EPISODE_URL, wait_until="load")
    generation = await browser_page.evaluate(
        "() => window.__younganimalViewerCapture.inspect([]).domGeneration"
    )
    result = await browser_page.evaluate("""generation => {
      const viewer = document.querySelector('#comici-viewer');
      for (let index = 0; index < 80; index += 1) {
        viewer.classList.toggle('mode-hide', index % 2 === 0);
      }
      return new Promise(resolve => requestAnimationFrame(() =>
        resolve(window.__younganimalViewerCapture.mutationsSince(generation))));
    }""", generation)

    assert result["available"] is True
    assert result["complete"] is False
    assert result["droppedCount"] >= 16
    assert len(result["records"]) == 64
    assert all(record["targetArea"] == "viewer" for record in result["records"])


@pytest.mark.parametrize("gate", ["すぐ無料で読む", "待つと無料で読む", "この話をレンタルする"])
async def test_younganimal_manual_entry_checks_reader_gate_without_listing_navigation(
    browser_page, gate: str
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    requested = await _install_fixture(browser_page, episode_target_label=gate)
    adapter = YounganimalAdapter(preflight_work_url=WORK_URL)
    await adapter.prepare_page(browser_page)
    entry = adapter.resolve_initial_navigation_url(EPISODE_URL)
    assert entry == EPISODE_URL
    await browser_page.goto(entry, wait_until="commit")
    with pytest.raises(UnknownPageStateError, match="direct access is blocked"):
        await adapter.initialize(browser_page)
    assert _content_document_paths(requested) == [f"/episodes/{EPISODE_ID}"]


async def test_younganimal_canvas_mutation_fails_without_runner_fallback_or_saved_page(
    browser_page, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    requested = await _install_fixture(browser_page)
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_MS", 20)
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_DEADLINE_MS", 500)
    monkeypatch.setattr(younganimal_adapter_module, "INITIAL_QUIET_POLL_MS", 10)
    adapter = YounganimalAdapter(preflight_work_url=WORK_URL)
    fallback_calls: list[object] = []
    capture_page = adapter.capture_page

    async def mutate_during_atomic_capture(page):
        await page.evaluate(
            """(() => {
              const original = HTMLCanvasElement.prototype.toDataURL;
              HTMLCanvasElement.prototype.toDataURL = function(...args) {
                const result = Reflect.apply(original, this, args);
                const context = this.getContext('2d', {willReadFrequently: true});
                context.fillStyle = 'rgb(1,2,3)';
                context.fillRect(0, 0, 1, 1);
                return result;
              };
            })();"""
        )
        return await capture_page(page)

    monkeypatch.setattr(adapter, "capture_page", mutate_during_atomic_capture)

    async def forbid_fallback(page) -> None:
        fallback_calls.append(page)
        raise AssertionError("generic capture fallback must not run")

    monkeypatch.setattr(adapter, "get_capture_targets", forbid_fallback)
    output_dir = tmp_path / "younganimal-mutated-canvas"
    with pytest.raises(UnknownPageStateError, match="integrity observer is missing"):
        await CrawlerRunner(
            RunConfig(
                site="younganimal",
                source_url=EPISODE_URL,
                output_dir=output_dir,
                diagnostics_dir=tmp_path / "mutation-diagnostics",
                page_turn_delay_ms=0,
                max_pages=20,
                max_same_content=3,
                page_change_timeout_ms=2_000,
            )
        ).run(browser_page, adapter)

    assert requested == [f"/episodes/{EPISODE_ID}"]
    assert fallback_calls == []
    assert list(output_dir.glob("page-*.png")) == []


async def test_younganimal_episode_429_stops_without_listing_navigation(
    browser_page, monkeypatch: pytest.MonkeyPatch
) -> None:
    await browser_page.set_viewport_size({"width": 1906, "height": 986})
    requested = await _install_fixture(browser_page)
    attempts: list[str] = []

    async def rate_limit(route) -> None:
        attempts.append(route.request.url.split("?", 1)[0])
        await route.fulfill(
            status=429,
            headers={"Retry-After": "1"},
            body="temporarily unavailable",
            content_type="text/plain",
        )

    await browser_page.route(EPISODE_URL, rate_limit)
    adapter = YounganimalAdapter(preflight_work_url=WORK_URL)
    await adapter.prepare_page(browser_page)
    entry = adapter.resolve_initial_navigation_url(EPISODE_URL)
    await browser_page.goto(entry, wait_until="commit")

    with pytest.raises(UnknownPageStateError, match="429"):
        await adapter.initialize(browser_page)

    assert attempts == [EPISODE_URL]
    assert requested == []
