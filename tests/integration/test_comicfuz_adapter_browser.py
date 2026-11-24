from __future__ import annotations

import asyncio
import base64
import json
import zipfile
from dataclasses import replace
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from screenshot_crawler import cli
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
from screenshot_crawler.site_adapters.base import AccessConsumption
from screenshot_crawler.site_adapters.comicfuz import (
    ComicFuzAdapter,
    ComicFuzDiscoveryAdapter,
)
from screenshot_crawler.site_adapters.comicfuz.adapter import _TicketReaderBinding
from screenshot_crawler.site_adapters.comicfuz.work_ticket import (
    ComicFuzTicketEntry,
    TicketEntryProof,
)
from screenshot_crawler.site_adapters.registry import AdapterRegistry
from screenshot_crawler.site_policies import ComicFuzSitePolicy, SitePolicyRegistry
from screenshot_crawler.watchlist import WatchlistTarget

pytestmark = pytest.mark.asyncio(loop_scope="module")

BASE = "https://comic-fuz.com"
WORK_URL = f"{BASE}/manga/1970?position=thumbnail"
VIEWER_URL = f"{BASE}/manga/viewer/80641"
NOW = datetime(2026, 10, 13, 12, tzinfo=JST)
TICKET_AVAILABLE = "\u30c1\u30e3\u30fc\u30b8\u5b8c\u4e86!"
TICKET_RECOVERY = "0\u6642\u306b\u56de\u5fa9!"
TICKET_RECOVERY_UI_FALLBACK = "0\u6642\u306b\u56de\u5fa9\uff01"
TICKET_CTA = "\u30c1\u30e3\u30fc\u30b8\u3067\u8aad\u3080"
TICKET_APP = "\u30a2\u30d7\u30ea\u306f\u3053\u3061\u3089"
RENTAL_ROW_ROOT_CLASSES = (
    "Chapter_chapter__wJPBe",
    "Chapter_chapter__alreadyViewed__BYLMn",
)
EPISODE_TITLE = "第31話"


def _jpeg_bytes(color: tuple[int, int, int] = (38, 121, 205)) -> bytes:
    image = Image.new("RGB", (96, 144), color=color)
    output = BytesIO()
    image.save(output, format="JPEG", quality=91)
    return output.getvalue()


def _ticket_varint(value: int) -> bytes:
    encoded = bytearray()
    while value > 0x7F:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _ticket_uint(field: int, value: int) -> bytes:
    return _ticket_varint(field << 3) + _ticket_varint(value)


def _ticket_bytes(field: int, value: bytes) -> bytes:
    return _ticket_varint((field << 3) | 2) + _ticket_varint(len(value)) + value


def _ticket_request(chapter_id: int) -> bytes:
    return _ticket_bytes(1, _ticket_uint(3, 2)) + _ticket_uint(2, 1) + _ticket_bytes(
        3, b""
    ) + _ticket_uint(4, chapter_id)


def _ticket_response(
    *,
    work_id: int,
    chapter_id: int,
    expiry: str,
    point_amount: int = 30,
    point_present: bool = True,
) -> bytes:
    manga = (
        _ticket_uint(1, work_id)
        + _ticket_uint(13, 1)
        + _ticket_bytes(18, TICKET_RECOVERY.encode())
    )
    point = _ticket_uint(2, point_amount) if point_amount else b""
    chapter = _ticket_uint(1, chapter_id)
    if point_present:
        chapter += _ticket_bytes(5, point)
    chapter += _ticket_bytes(10, expiry.encode())
    groups = _ticket_bytes(2, chapter)
    viewer_page = _ticket_bytes(1, b"synthetic-page")
    viewer_data = _ticket_bytes(2, viewer_page)
    return (
        _ticket_bytes(2, viewer_data)
        + _ticket_bytes(5, groups)
        + _ticket_bytes(11, manga)
        + _ticket_uint(12, chapter_id)
    )


def _direct_viewer_request(
    chapter_id: int,
    *,
    use_ticket: bool = False,
    point_free: int = 0,
    point_paid: int = 0,
) -> bytes:
    device = _ticket_uint(3, 2)
    # Proto3 omits false useTicket; point costs are present and explicitly zero.
    consume_point = _ticket_uint(1, point_free) + _ticket_uint(2, point_paid)
    request = _ticket_bytes(1, device)
    if use_ticket:
        request += _ticket_uint(2, 1)
    return request + _ticket_bytes(3, consume_point) + _ticket_uint(4, chapter_id)


def _work_html(
    *, free: bool = True, sign_in: bool = True, episode_title: str = EPISODE_TITLE,
) -> str:
    chapters = [("80641", episode_title), ("80640", "第30話"), ("80639", "第29話")]
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
    account_link = ('<a href="/account/signin">Sign in</a>' if sign_in
                    else '<a href="/mypage">My page</a>')
    return f'''<!doctype html><html><head><title>サンプル作品</title>
      <link rel="canonical" href="{BASE}/manga/1970">
      <script id="__NEXT_DATA__" type="application/json">{json.dumps(data, ensure_ascii=False)}</script>
      </head><body>{account_link}
      <div class="title_detail_chapters__list__fixture"><ul>{rows}</ul></div>
      <style>body{{min-height:1200px}}</style></body></html>'''


def _work_ticket_listing_html(
    *,
    work_id: str,
    chapter_id: str,
    chapter_label: str,
    request_body: bytes,
    viewer_html: str,
    charge_available: bool = True,
    listing_ready_delay_ms: int = 0,
    hidden_duplicate_dialog: bool = False,
    ticket_query: bool = True,
) -> str:
    next_data = {
        "page": "/manga/[mangaId]",
        "query": {"mangaId": work_id},
        "props": {
            "pageProps": {
                "chapters": [
                    {
                        "chapters": [
                            {"chapterId": chapter_id, "chapterMainName": chapter_label,
                             "pointConsumption": {"amount": 30}}
                        ]
                    }
                ]
            }
        },
    }
    request_values = list(request_body)
    viewer_html_js = json.dumps(viewer_html).replace("</", "<\\/")
    listing_class = (
        "title_detail_chapters__pending__fixture"
        if listing_ready_delay_ms > 0
        else "title_detail_chapters__list__fixture"
    )
    viewer_route = f"/manga/viewer/{chapter_id}"
    if ticket_query:
        viewer_route += "?ticket=true"
    modal = f'''<div class="Dialog_modal__fixture" id="ticket-modal" style="display:none">
        <div class="Dialog_content__fixture">
          <div class="Dialog_chapter__fixture">
            <p class="Dialog_chapter__mainText__fixture">{chapter_label}</p>
          </div>
          <div class="Dialog_items__fixture"><div class="Dialog_items__item__fixture">
            <span class="Dialog_items__icon__fixture"></span>
            <p class="Dialog_items__amount__fixture">1</p>
          </div></div>
          <div class="Dialog_buttons__fixture">
            <a class="Dialog_buttons__active__fixture" id="ticket-cta">{TICKET_CTA}</a>
            <a>{TICKET_APP}</a>
            <button class="Dialog_appflow__button__fixture">{TICKET_APP}</button>
            <a class="Dialog_buttons__active__fixture">コメント一覧へ</a>
            <a class="Dialog_buttons__cancel__fixture">キャンセル</a>
          </div>
        </div>
      </div>'''
    hidden_modal = (
        modal.replace(
            'class="Dialog_modal__fixture"',
            'class="Dialog_modal__hidden__fixture" style="opacity:0"',
            1,
        )
        if hidden_duplicate_dialog
        else ""
    )
    return f'''<!doctype html><html><head><title>Verified ComicFUZ Work</title>
      <link rel="canonical" href="{BASE}/manga/{work_id}">
      <script id="__NEXT_DATA__" type="application/json">{json.dumps(next_data)}</script>
      </head><body><div id="ticket-list" class="{listing_class}">
        <div class="Chapter_chapter__row__fixture"><div class="Chapter_chapter__detail__fixture">
          <h3 class="Chapter_chapter__name__fixture">{chapter_label}</h3>
        </div></div></div>
        <div class="Charge_charge__charged__fixture"><img alt="チャージ"
          src="/assets/manga_detail/charged.svg"><p>{TICKET_AVAILABLE}</p></div>
        <button class="page-control__fixture">Background control</button>
        {modal}{hidden_modal}
        <script>
          (() => {{
          const chargeAvailable={json.dumps(charge_available)};
          const listingReadyDelayMs={listing_ready_delay_ms};
          if(listingReadyDelayMs>0){{
            setTimeout(()=>{{
              const list=document.querySelector('#ticket-list');
              list.className='title_detail_chapters__list__fixture';
            }},listingReadyDelayMs);
          }}
          const workId={json.dumps(work_id)}, chapterId={json.dumps(chapter_id)};
          const chapterLabel={json.dumps(chapter_label)};
          const mangaPrototype=chargeAvailable?{{}}:{{isTicketAvailable:false,chargeStatus:''}};
          const manga=Object.assign(Object.create(mangaPrototype),{{
            mangaId:Number(workId),isChargeNeeded:true
          }});
          if(chargeAvailable){{manga.isTicketAvailable=true;manga.chargeStatus={json.dumps(TICKET_AVAILABLE)};}}
          const point=Object.assign(Object.create({{type:0}}),{{amount:30}});
          const chapter=Object.assign(Object.create({{endOfRentalPeriod:''}}),{{
            chapterId:Number(chapterId),chapterMainName:chapterLabel,pointConsumption:point
          }});
          const webMangaViewerData={{manga,chapters:[{{chapters:[chapter]}}]}};
          const heading=document.querySelector('h3');
          heading.__reactFiber$target={{memoizedProps:{{chapter}},
            return:{{memoizedProps:{{webMangaViewerData}},return:null}}}};
          const chargeBadge=document.querySelector('.Charge_charge__charged__fixture');
          const chargeLabel=chargeAvailable?manga.chargeStatus:'{TICKET_RECOVERY_UI_FALLBACK}';
          chargeBadge.className=chargeAvailable
            ?'Charge_charge__charged__fixture':'Charge_charge__not_charged__fixture';
          chargeBadge.querySelector('img').src=chargeAvailable
            ?'/assets/manga_detail/charged.svg':'/assets/manga_detail/charge.svg';
          chargeBadge.querySelector('p').textContent=chargeLabel;
          const chargeDataFiber={{memoizedProps:{{webMangaViewerData}},return:null}};
          const chargePropsFiber={{memoizedProps:{{isTicketAvailable:!!manga.isTicketAvailable,
            labelText:manga.chargeStatus||''}},return:chargeDataFiber}};
          chargeBadge.__reactFiber$host={{memoizedProps:{{className:chargeBadge.className}},
            return:chargePropsFiber}};
          const modal=document.querySelector('#ticket-modal');
          heading.addEventListener('click',()=>modal.style.display='block');
          document.querySelector('#ticket-cta').addEventListener('click',()=>{{
            if({json.dumps(ticket_query)}){{
              history.pushState({{}},'',{json.dumps(viewer_route)});
              fetch('https://api.comic-fuz.com/v1/web_manga_viewer_2',{{method:'POST',
                headers:{{'content-type':'text/plain'}},
                body:new Uint8Array({request_values})}})
                .then(()=>{{document.open();document.write({viewer_html_js});document.close();}})
                .catch(()=>{{}});
            }}else{{
              window.location.assign({json.dumps(viewer_route)});
            }}
          }});
          }})();
        </script></body></html>'''


def _relative_rental_listing_html(
    *, work_id: str, chapter_id: str, chapter_label: str, rental_value: str,
    ticket_available: bool = False,
    point_amount: int = 0,
    native_point_amount: int | str | None = 30,
    row_runtime_same_chapter: bool = True,
    row_runtime_same_point: bool = True,
    row_root_class_tokens: tuple[str, ...] = RENTAL_ROW_ROOT_CLASSES,
    false_descendant: bool = False,
) -> str:
    native_point = (
        {} if native_point_amount is None else {"amount": native_point_amount}
    )
    data = {
        "page": "/manga/[mangaId]",
        "query": {"mangaId": work_id},
        "props": {"pageProps": {"chapters": [{"chapters": [{
            "chapterId": chapter_id,
            "chapterMainName": chapter_label,
            "pointConsumption": native_point,
        }]}]}},
    }
    charge_class = (
        "Charge_charge__charged__fixture"
        if ticket_available
        else "Charge_charge__JSGmu undefined"
    )
    charge_image = "charged.svg" if ticket_available else "charge.svg"
    charge_label = TICKET_AVAILABLE if ticket_available else TICKET_RECOVERY
    row_root_classes = " ".join(row_root_class_tokens)
    false_descendant_markup = '<span class="false"></span>' if false_descendant else ""
    return f'''<!doctype html><html><head><title>Selected ComicFUZ Work</title>
      <link rel="canonical" href="{BASE}/manga/{work_id}">
      <script id="__NEXT_DATA__" type="application/json">{json.dumps(data, ensure_ascii=False)}</script>
      </head><body><div class="title_detail_chapters__list__fixture">
        <div class="{row_root_classes}">
          <div class="Chapter_chapter__detail__fixture">
            <h3 class="Chapter_chapter__name__fixture">{chapter_label}</h3>
            <p class="Chapter_chapter__price_free__fixture">免費_PLACEHOLDER</p>
            <p class="Chapter_chapter__rentalPeriod__fixture">{rental_value}</p>
            {false_descendant_markup}
          </div>
        </div>
      </div>
      <div class="{charge_class}">
        <img alt="\u30c1\u30e3\u30fc\u30b8" src="/assets/manga_detail/{charge_image}">
        <p>{charge_label}</p>
      </div>
      <script>(()=>{{
        const workId={json.dumps(work_id)}, chapterId={json.dumps(chapter_id)};
        const label={json.dumps(chapter_label)}, rental={json.dumps(rental_value, ensure_ascii=False)};
        const ticketAvailable={json.dumps(ticket_available)};
        const manga=Object.assign(Object.create(ticketAvailable?{{}}:{{isTicketAvailable:false}}),{{
          mangaId:Number(workId),isChargeNeeded:true
        }});
        if(ticketAvailable){{manga.isTicketAvailable=true;manga.chargeStatus={json.dumps(TICKET_AVAILABLE)};}}
        else manga.chargeStatus={json.dumps(TICKET_RECOVERY)};
        const point=Object.create({{type:0,amount:{point_amount}}});
        const chapter=Object.assign(Object.create({{endOfRentalPeriod:''}}),{{
          chapterId:Number(chapterId),chapterMainName:label,pointConsumption:point,
          endOfRentalPeriod:rental
        }});
        const rowPoint={json.dumps(row_runtime_same_point)}?point:
          Object.create({{type:0,amount:{point_amount}}});
        const rowChapter={json.dumps(row_runtime_same_chapter)}?chapter:
          Object.assign(Object.create(Object.getPrototypeOf(chapter)),chapter,
            {{pointConsumption:rowPoint}});
        const webMangaViewerData={{manga,chapters:[{{chapters:[chapter]}}]}};
        const heading=document.querySelector('h3');
        heading.__reactFiber$target={{memoizedProps:{{chapter:rowChapter}},
          return:{{memoizedProps:{{webMangaViewerData}},return:null}}}};
        const badge=document.querySelector('div[class*="Charge_charge__"]');
        const chargeData={{memoizedProps:{{webMangaViewerData}},return:null}};
        const chargeProps={{memoizedProps:{{isTicketAvailable:!!manga.isTicketAvailable,
          labelText:ticketAvailable?manga.chargeStatus:''}},return:chargeData}};
        badge.__reactFiber$host={{memoizedProps:{{className:badge.className}},return:chargeProps}};
      }})();</script></body></html>'''.replace(
        "免費_PLACEHOLDER", "\u7121\u6599"
    )



def _viewer_html(
    jpeg: bytes,
    *,
    empty_ssr: bool = False,
    bind_title_fiber: bool = False,
    viewer_title: str = EPISODE_TITLE,
    native_title: str = EPISODE_TITLE,
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
    extra_tail_unlinked_pair: bool = False,
    latest_end: str = "none",
    stuck_extra_tail: bool = False,
    native_subtitle: str = "",
) -> str:
    encoded = base64.b64encode(jpeg).decode("ascii")
    next_data = (
        {
            "page": "/manga/viewer/[chapterId]",
            "query": {},
            "props": {"pageProps": {}},
        }
        if empty_ssr
        else {
            "page": "/manga/viewer/[chapterId]",
            "props": {
                "pageProps": {
                    "chapterId": "80641",
                    "data": {
                        "mangaId": "1970",
                        "chapterMainName": native_title,
                        "chapterSubName": native_subtitle,
                        "mangaName": "Verified ComicFUZ Work",
                    },
                },
            },
        }
    )
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
        if len(image_groups[last_state]) == 1 and not (last_state == 0 and not first_pair_mode):
            image_groups[last_state].append(body_descriptor_count)
        if not first_pair_mode and missing_second_page:
            image_groups[1] = [1]
        if extra_tail_unlinked_pair:
            if body_descriptor_count in image_groups[last_state]:
                image_groups[last_state + 1] = [body_descriptor_count + 1, body_descriptor_count + 2]
            else:
                image_groups[last_state + 1] = [body_descriptor_count, body_descriptor_count + 1]
                image_groups[last_state + 2] = [body_descriptor_count + 2]
        elif extra_tail:
            remaining_extras = [n for n in range(body_descriptor_count, body_descriptor_count + 3)
                                if n not in image_groups[last_state]]
            for start in range(0, len(remaining_extras), 2):
                image_groups[max(image_groups) + 1] = remaining_extras[start:start + 2]
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
        if ({str(extra_tail_unlinked_pair).lower()}) {{
          pageDescriptors.push(
            {{image:{{imageWidth:96,imageHeight:144,isExtraPage:true}}}},
            {{image:{{imageWidth:96,imageHeight:144,isExtraPage:true}}}},
            {{image:{{imageWidth:96,imageHeight:144,isExtraPage:true,urlScheme:'krr://manga?id=999'}}}},
            {{googleAds:{{}}}}, {{lastPage:{{}}}}
          );
        }} else {{
          pageDescriptors.push(
            {{image:{{imageWidth:96,imageHeight:144,isExtraPage:true,urlScheme:'krr://manga?id=999'}}}},
            {{googleAds:{{}}}}, {{lastPage:{{}}}}
          );
          if ({str(extra_tail).lower()}) pageDescriptors.splice(pageDescriptors.length - 2, 0,
            {{image:{{imageWidth:96,imageHeight:144,isExtraPage:true}}}},
            {{image:{{imageWidth:96,imageHeight:144,isExtraPage:true,urlScheme:'krr://manga?id=998'}}}}
          );
        }}
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
          if ('{transition_overlap_variant}' === 'role') numbers = [3, 4, 10];
          reader.innerHTML = `<div id="pages"></div><h2 class="title_detail_viewer__detail__info__viewerTitle__GrN4D">{viewer_title}</h2>`;
          const area = document.querySelector('#pages');
          area.style.cssText = 'position:fixed;left:0;top:0;width:1280px;height:720px';
          numbers.forEach((n, index) => {{
            const image = document.createElement('img');
            image.className = 'G54Y0W_page'; image.alt = `page_${{n}}`;
            image['__reactFiber$fixture'] = {{memoizedProps:{{webMangaViewerData}},return:null}};
            image.src = ('{transition_overlap_variant}' === 'dimensions' && index === 1)
              ? wrongDimensionSrc : src;
            const allReadyPositions = [945, 655, 355, 55];
            const clippedPositions = numbers.length === 4
              ? [1100, 800, 500, -25] : [1100, 655, -25];
            const positions = '{transition_overlap_variant}' === 'all_ready'
              ? allReadyPositions : clippedPositions;
            const left = positions[index] ?? 55;
            image.style.cssText = `position:absolute;top:40px;left:${{left}}px;width:300px;height:450px;object-fit:fill`;
            if ('{transition_overlap_variant}' === 'visual_unsafe' && index === 1)
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
            if ('{latest_end}' === 'account_recommendations')
              reader.querySelector('div.ChapterLastPage_lastpage__iBifl').insertAdjacentHTML(
                'beforeend', '<div class="ChapterLastPage_lastpagetitle__INDwU">チャージが回復した作品</div>');
            if ('{latest_end}' === 'duplicate_recommendations') {{
              const recommendation = reader.querySelector('[class*="lastpagetitle"]');
              recommendation.parentElement.append(recommendation.cloneNode(true));
            }}
          }} else {{
            reader.innerHTML = `<div class="ChapterLastPage_lastpage__iBifl" style="position:fixed;left:200px;top:30px;width:500px;height:650px">
              <div class="ChapterLastPage_lastpage__nextChapter__6t7yj" style="position:absolute;left:15px;top:260px;width:470px;height:260px">
                <a class="ChapterLastPage_nextChapter__button__x1P_o" href="/manga/viewer/999">次の話を読む</a>
              </div>
              <h2 class="title_detail_viewer__detail__info__viewerTitle__GrN4D" style="position:absolute;left:120px;top:600px">{viewer_title}</h2>
            </div>`;
          }}
          if ({str(bind_title_fiber).lower()}) {{
            for (const title of reader.querySelectorAll(
              'h2[class*="title_detail_viewer__detail__info__viewerTitle"]')) {{
              title['__reactFiber$fixture'] = {{memoizedProps:{{webMangaViewerData}},return:null}};
            }}
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


def _ticket_viewer_html(
    *,
    work_id: str,
    chapter_id: str,
    expiry: str,
    chapter_label: str = EPISODE_TITLE,
    relative_rental: bool = False,
    empty_ssr: bool = False,
) -> str:
    html = _viewer_html(
        _jpeg_bytes(),
        empty_ssr=empty_ssr,
        bind_title_fiber=empty_ssr,
        latest_end="valid",
        native_title=chapter_label,
        viewer_title=chapter_label,
    )
    html = html.replace("80641", chapter_id).replace("1970", work_id)
    old = f"const webMangaViewerData = {{chapterId:'{chapter_id}',viewerData}};"
    point_consumption = (
        "Object.create({type:0,amount:0})"
        if relative_rental
        else "{type:0,amount:30}"
    )
    if empty_ssr:
        native_data = (
            "const targetChapter=Object.assign(Object.create({chapterSubName:''}),{"
            f"chapterId:{chapter_id},chapterMainName:{json.dumps(chapter_label)},"
            f"pointConsumption:{point_consumption},isRead:true,"
            f"endOfRentalPeriod:{json.dumps(expiry)}}});"
            f"const webMangaViewerData = {{chapterId:{chapter_id},viewerData,"
            f"manga:{{mangaId:{work_id},mangaName:'Verified ComicFUZ Work',"
            f"isChargeNeeded:true,isTicketAvailable:false,"
            f"chargeStatus:{json.dumps(TICKET_RECOVERY)}}},"
            "chapters:[{chapters:[targetChapter]}]};"
        )
    else:
        native_data = (
            f"const webMangaViewerData = {{chapterId:'{chapter_id}',viewerData,"
            f"manga:{{mangaId:'{work_id}',isChargeNeeded:true,isTicketAvailable:false,"
            f"chargeStatus:{json.dumps(TICKET_RECOVERY)}}},"
            f"chapters:[{{chapters:[{{chapterId:'{chapter_id}',"
            f"chapterMainName:{json.dumps(chapter_label)},"
            f"pointConsumption:{point_consumption},isRead:true,"
            f"endOfRentalPeriod:{json.dumps(expiry)}}}]}}]}};"
        )
    if old not in html:
        raise AssertionError("Synthetic viewer fixture lost its native React data marker")
    return html.replace(old, native_data)


async def _install_synthetic_ticket_binding(
    adapter: ComicFuzAdapter,
    page,
    *,
    work_id: str = "3667",
    chapter_id: str = "76630",
    chapter_label: str = "Ticket target episode",
) -> None:
    await adapter.configure_target_identity(
        f"{work_id}:{chapter_id}", "synthetic-managed-work-key"
    )
    await adapter.configure_run(page, "quota")
    await adapter.configure_quota_resource(page, "work_ticket")
    controller = adapter._ticket_entry
    assert controller is not None
    observed_at = datetime.now(JST)
    proof = TicketEntryProof(
        request_started_at=observed_at,
        confirmed_at=observed_at,
        access_granted_until=None,
    )
    controller.proof = proof
    controller.consumption = AccessConsumption(
        consumed=True,
        resource="work_ticket",
        consumed_at=observed_at,
    )
    adapter._ticket_entry_confirmed = True
    adapter._ticket_reader_binding = _TicketReaderBinding(
        controller=controller,
        proof=proof,
        page=page,
        work_id=work_id,
        chapter_id=chapter_id,
        external_id=f"{work_id}:{chapter_id}",
    )
    adapter._expected_episode_title = chapter_label


async def _route_comicfuz(
    page,
    *,
    viewer_title: str = EPISODE_TITLE,
    listing_title: str = EPISODE_TITLE,
    native_title: str = EPISODE_TITLE,
    free: bool = True,
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
    extra_tail_unlinked_pair: bool = False,
    latest_end: str = "none",
    stuck_extra_tail: bool = False,
    native_subtitle: str = "",
):
    body = _work_html(free=free, sign_in=sign_in, episode_title=listing_title)
    image = _viewer_html(
        _jpeg_bytes(),
        viewer_title=viewer_title,
        native_title=native_title,
        sign_in=sign_in,
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
        extra_tail_unlinked_pair=extra_tail_unlinked_pair,
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
    free_candidates = [
        candidate for candidate in plan.candidates
        if candidate.external_id == "1970:80641"
    ]
    assert len(free_candidates) == 1
    candidate = free_candidates[0]
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


@pytest.mark.parametrize("grant_only", [False, True], ids=["normal_batch", "grant_only"])
@pytest.mark.parametrize(
    "relative_rental",
    [False, True],
    ids=["absolute_expiry", "relative_current_entry"],
)
@pytest.mark.parametrize(
    "ticket_query",
    [False, True],
    ids=["canonical_viewer_route", "ticket_query_viewer_route"],
)
async def test_comicfuz_work_ticket_batch_entry_and_capture(
    browser_page,
    browser_context,
    tmp_path: Path,
    sync_legacy_unscoped_work,
    grant_only: bool,
    relative_rental: bool,
    ticket_query: bool,
) -> None:
    work_id, chapter_id = "3667", "76630"
    work_url = f"{BASE}/manga/{work_id}"
    chapter_label = "Ticket target episode"
    now = datetime.now(JST)
    expiry = "残り2日" if relative_rental else (now + timedelta(days=1)).isoformat()
    request_body = _ticket_request(int(chapter_id))
    response_body = _ticket_response(
        work_id=int(work_id),
        chapter_id=int(chapter_id),
        expiry=expiry,
        point_amount=0 if relative_rental else 30,
    )
    viewer_html = _ticket_viewer_html(
        work_id=work_id,
        chapter_id=chapter_id,
        expiry=expiry,
        chapter_label=chapter_label,
        relative_rental=relative_rental,
        empty_ssr=not grant_only and relative_rental,
    )
    listing_html = _work_ticket_listing_html(
        work_id=work_id,
        chapter_id=chapter_id,
        chapter_label=chapter_label,
        request_body=request_body,
        viewer_html=viewer_html,
        listing_ready_delay_ms=350,
        hidden_duplicate_dialog=True,
        ticket_query=ticket_query,
    )
    viewer_html_js = json.dumps(viewer_html).replace("</", "<\\/")
    viewer_bootstrap_html = f'''<!doctype html><html><head><title>ComicFUZ viewer bootstrap</title></head>
      <body><script>(()=>{{
        const body=new Uint8Array({json.dumps(list(request_body))});
        fetch('https://api.comic-fuz.com/v1/web_manga_viewer_2',{{method:'POST',
          headers:{{'content-type':'text/plain'}},body}})
          .then(()=>{{document.open();document.write({viewer_html_js});document.close();}})
          .catch(()=>{{}});
      }})();</script></body></html>'''
    api_requests: list[bytes] = []
    work_page_visits: list[str] = []

    async def comicfuz_route(route) -> None:
        path = route.request.url.split("?", 1)[0]
        if path == work_url:
            work_page_visits.append(path)
            await route.fulfill(
                status=200,
                content_type="text/html; charset=utf-8",
                body=listing_html,
            )
        elif path == f"{BASE}/manga/viewer/{chapter_id}":
            await route.fulfill(
                status=200,
                content_type="text/html; charset=utf-8",
                body=viewer_bootstrap_html,
            )
        elif path in {
            f"{BASE}/assets/manga_detail/charged.svg",
            f"{BASE}/assets/manga_detail/charge.svg",
        }:
            await route.fulfill(
                status=200,
                content_type="image/svg+xml",
                body='<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"></svg>',
            )
        else:
            await route.fulfill(status=404, body="not found")

    async def api_route(route) -> None:
        api_requests.append(route.request.post_data_buffer or b"")
        await route.fulfill(
            status=200,
            content_type="application/octet-stream",
            headers={"access-control-allow-origin": BASE},
            body=response_body,
        )

    await browser_page.route(f"{BASE}/**", comicfuz_route)
    await browser_context.route(
        "https://api.comic-fuz.com/v1/web_manga_viewer_2**", api_route
    )
    catalog = CatalogService(tmp_path / "ticket-catalog.sqlite")
    target = WatchlistTarget(
        key="comicfuz-ticket-target",
        work_key="stable-series-slug",
        site="comicfuz",
        url=work_url,
        label="Ticket target work",
    )
    discovery_registry = DiscoveryAdapterRegistry()
    discovery_registry.register("comicfuz", ComicFuzDiscoveryAdapter)
    discovery = DiscoveryService(catalog, discovery_registry)
    discovered = await discovery.discover(browser_page, target, "full")
    assert discovered.complete is True
    watchlist = sync_legacy_unscoped_work(catalog, target)

    policies = SitePolicyRegistry()
    policies.register("comicfuz", ComicFuzSitePolicy)
    plan = BatchPlanner(catalog, policies, watchlist=watchlist).plan(
        site="comicfuz", now=now
    )
    candidates = [
        candidate
        for candidate in plan.candidates
        if candidate.external_id == f"{work_id}:{chapter_id}"
    ]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.access_strategy == "quota"
    assert candidate.quota_resource == "work_ticket"

    adapter = ComicFuzAdapter()
    adapters = AdapterRegistry()
    adapters.register("comicfuz", lambda: adapter)
    attempt_observations = []
    executor = BatchExecutor(
        catalog,
        policies,
        adapters,
        runtime_settings=SiteRuntimeSettings(page_turn_delay_ms=0),
        library_dir=tmp_path / "library",
        watchlist=watchlist,
        access_attempt_sink=attempt_observations.append,
    )
    if grant_only:
        result = await executor.execute_grant_only_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "grant-only-output",
            now=now,
        )
        run = catalog.get_crawl_run(result.crawl_run_id)
        assert result.resource_consumed is True
        assert result.resource == "work_ticket"
        assert run.status == "succeeded" and run.page_count == 0
        assert catalog.get_item(candidate.item_id).status == "pending"
        assert catalog.list_artifacts(item_id=candidate.item_id) == []
        assert adapter.get_access_consumption().consumed is True
        if relative_rental:
            assert adapter.get_access_consumption().access_granted_until is None
        else:
            assert adapter.get_access_consumption().access_granted_until is not None
        assert adapter._source_response_tasks == {}
        assert adapter._source_responses == {}
    else:
        result = await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "normal-output",
            library_dir=tmp_path / "library",
            max_pages=5,
            now=now,
        )
        run = catalog.get_crawl_run(result.crawl_run_id)
        assert result.stop_reason == "end" and result.page_count == 2
        assert run.status == "succeeded" and run.page_count == 2
        assert "access_consumption_confirmed:" in (run.stop_reason or "")
        assert catalog.get_item(candidate.item_id).status == "completed"
        artifacts = catalog.list_artifacts(item_id=candidate.item_id)
        assert len(artifacts) == 1 and artifacts[0].format == "zip"
        assert adapter.get_access_consumption().consumed is True
        if relative_rental:
            assert adapter._ticket_reader_binding_matches(browser_page)
            assert adapter._empty_ssr_reader_identity is not None
            assert (
                adapter._empty_ssr_reader_identity.binding.proof
                is adapter._ticket_entry.proof
            )
        if relative_rental:
            assert adapter.get_access_consumption().access_granted_until is None
        else:
            assert adapter.get_access_consumption().access_granted_until is not None
    if relative_rental:
        assert catalog.get_source(candidate.source_id).access_granted_until is None
    assert api_requests == [request_body]
    assert len(work_page_visits) == 2
    assert [observation.status for observation in attempt_observations] == [
        "attempting",
        "confirmed",
    ]


@pytest.mark.parametrize(
    "variant",
    [
        "duplicate_next_data",
        "malformed_next_data",
        "conflicting_query",
        "conflicting_page_props",
        "bad_runtime_prop",
        "duplicate_runtime_object",
        "duplicate_non_target_chapter_id",
        "ambiguous_runtime_without_title",
        "duplicate_title",
        "wrong_work_id",
        "wrong_work_id_without_title",
        "wrong_chapter_id",
        "duplicate_non_target_chapter_id_without_title",
        "bad_runtime_prop_without_title",
        "missing_subtitle_default",
        "dom_title_mismatch",
        "missing_binding",
        "other_page_binding",
        "changed_proof_object",
        "changed_consumption_timestamp",
        "changed_controller",
        "direct_context",
        "auto_context",
        "missing_resource_context",
    ],
)
async def test_comicfuz_empty_ssr_ticket_reader_authority_fails_closed(
    browser_page,
    variant: str,
) -> None:
    work_id, chapter_id = "3667", "76630"
    chapter_label = "Ticket target episode"
    html = _ticket_viewer_html(
        work_id=work_id,
        chapter_id=chapter_id,
        expiry="\u6b8b\u308a2\u65e5",
        chapter_label=chapter_label,
        relative_rental=True,
        empty_ssr=True,
    )

    async def route_viewer(route) -> None:
        await route.fulfill(status=200, body=html, content_type="text/html; charset=utf-8")

    await browser_page.route(f"{BASE}/manga/viewer/{chapter_id}**", route_viewer)
    await browser_page.goto(f"{BASE}/manga/viewer/{chapter_id}?ticket=true")
    if variant == "duplicate_next_data":
        await browser_page.evaluate(
            """() => document.body.append(document.querySelector('#__NEXT_DATA__').cloneNode(true))"""
        )
    elif variant == "malformed_next_data":
        await browser_page.locator("#__NEXT_DATA__").evaluate("element => { element.textContent = '{'; }")
    elif variant == "conflicting_query":
        await browser_page.locator("#__NEXT_DATA__").evaluate(
            """element => { const data=JSON.parse(element.textContent); data.query={chapterId:'76630'};
              element.textContent=JSON.stringify(data); }"""
        )
    elif variant == "conflicting_page_props":
        await browser_page.locator("#__NEXT_DATA__").evaluate(
            """element => { const data=JSON.parse(element.textContent);
              data.props.pageProps={chapterId:'76630'}; element.textContent=JSON.stringify(data); }"""
        )
    elif variant in {"bad_runtime_prop", "bad_runtime_prop_without_title"}:
        await browser_page.locator("img[class*='G54Y0W_page']").first.evaluate(
            """image => { const key=Object.keys(image).find(name=>name.startsWith('__reactFiber$'));
              image[key].memoizedProps.webMangaViewerData=null; }"""
        )
    elif variant == "duplicate_runtime_object":
        await browser_page.locator("img[class*='G54Y0W_page']").first.evaluate(
            """image => { const fiberKey=Object.keys(image).find(key=>key.startsWith('__reactFiber$'));
              const web=image[fiberKey].memoizedProps.webMangaViewerData;
              image[fiberKey].memoizedProps.webMangaViewerData={...web,manga:{...web.manga}}; }"""
        )
    elif variant == "ambiguous_runtime_without_title":
        await browser_page.locator("img[class*='G54Y0W_page']").first.evaluate(
            """image => { const key=Object.keys(image).find(name=>name.startsWith('__reactFiber$'));
              const web=image[key].memoizedProps.webMangaViewerData;
              image[key].memoizedProps.webMangaViewerData={...web,manga:{...web.manga}}; }"""
        )
        await browser_page.locator("h2[class*='title_detail_viewer__detail__info__viewerTitle']") \
            .evaluate("element => { element.style.display = 'none'; }")
    elif variant in {
        "duplicate_non_target_chapter_id",
        "duplicate_non_target_chapter_id_without_title",
    }:
        await browser_page.locator("img[class*='G54Y0W_page']").first.evaluate(
            """image => { const key=Object.keys(image).find(name=>name.startsWith('__reactFiber$'));
              const chapters=image[key].memoizedProps.webMangaViewerData.chapters[0].chapters;
              chapters.push({...chapters[0],chapterId:777});
              chapters.push({...chapters[0],chapterId:777}); }"""
        )
    elif variant == "duplicate_title":
        await browser_page.locator("h2[class*='title_detail_viewer__detail__info__viewerTitle']") \
            .evaluate("element => element.after(element.cloneNode(true))")
    elif variant in {"wrong_work_id", "wrong_work_id_without_title"}:
        await browser_page.locator("img[class*='G54Y0W_page']").first.evaluate(
            """image => { const key=Object.keys(image).find(name=>name.startsWith('__reactFiber$'));
              image[key].memoizedProps.webMangaViewerData.manga.mangaId=999; }"""
        )
    elif variant == "wrong_chapter_id":
        await browser_page.locator("img[class*='G54Y0W_page']").first.evaluate(
            """image => { const key=Object.keys(image).find(name=>name.startsWith('__reactFiber$'));
              image[key].memoizedProps.webMangaViewerData.chapterId=999; }"""
        )
    elif variant == "missing_subtitle_default":
        await browser_page.locator("img[class*='G54Y0W_page']").first.evaluate(
            """image => { const key=Object.keys(image).find(name=>name.startsWith('__reactFiber$'));
              const chapter=image[key].memoizedProps.webMangaViewerData.chapters[0].chapters[0];
              Object.setPrototypeOf(chapter,{}); }"""
        )
    elif variant == "dom_title_mismatch":
        await browser_page.locator("h2[class*='title_detail_viewer__detail__info__viewerTitle']") \
            .evaluate("element => { element.textContent = 'Different episode'; }")
    if variant in {
        "wrong_work_id_without_title",
        "duplicate_non_target_chapter_id_without_title",
        "bad_runtime_prop_without_title",
    }:
        await browser_page.locator("h2[class*='title_detail_viewer__detail__info__viewerTitle']") \
            .evaluate("element => { element.style.display = 'none'; }")

    adapter = ComicFuzAdapter()
    await _install_synthetic_ticket_binding(adapter, browser_page)
    if variant == "missing_binding":
        adapter._ticket_entry_confirmed = False
        adapter._ticket_reader_binding = None
    elif variant == "other_page_binding":
        assert adapter._ticket_reader_binding is not None
        adapter._ticket_reader_binding = replace(adapter._ticket_reader_binding, page=object())
    elif variant == "changed_proof_object":
        assert adapter._ticket_entry is not None
        adapter._ticket_entry.proof = TicketEntryProof(
            request_started_at=NOW,
            confirmed_at=NOW + timedelta(seconds=1),
            access_granted_until=None,
        )
    elif variant == "changed_consumption_timestamp":
        assert adapter._ticket_entry is not None
        adapter._ticket_entry.consumption = AccessConsumption(
            consumed=True,
            resource="work_ticket",
            consumed_at=NOW + timedelta(seconds=1),
        )
    elif variant == "changed_controller":
        assert adapter._ticket_entry is not None
        adapter._ticket_entry = ComicFuzTicketEntry(
            work_id=work_id,
            chapter_id=chapter_id,
            external_id=f"{work_id}:{chapter_id}",
        )
    elif variant == "direct_context":
        adapter._access_strategy = "direct"
    elif variant == "auto_context":
        adapter._access_strategy = "auto"
    elif variant == "missing_resource_context":
        adapter._quota_resource = None

    with pytest.raises(UnknownPageStateError):
        await adapter._validate_reader_identity(
            browser_page,
            allow_initial_manifest_loading=True,
        )


@pytest.mark.parametrize("stage", ["initial_manifest", "cached_at_end"])
async def test_comicfuz_full_ssr_malformed_viewer_manifest_never_becomes_loading_or_cache(
    browser_page,
    stage: str,
) -> None:
    work_id, chapter_id = "3667", "76630"
    chapter_label = "Ticket target episode"
    html = _ticket_viewer_html(
        work_id=work_id,
        chapter_id=chapter_id,
        expiry="\u6b8b\u308a2\u65e5",
        chapter_label=chapter_label,
        relative_rental=True,
    )

    async def route_viewer(route) -> None:
        await route.fulfill(status=200, body=html, content_type="text/html; charset=utf-8")

    await browser_page.route(f"{BASE}/manga/viewer/{chapter_id}**", route_viewer)
    await browser_page.goto(f"{BASE}/manga/viewer/{chapter_id}")
    adapter = ComicFuzAdapter()
    await adapter.configure_target_identity(
        f"{work_id}:{chapter_id}", "synthetic-managed-work-key"
    )
    await adapter.configure_run(browser_page, "auto")
    adapter._expected_episode_title = chapter_label
    if stage == "cached_at_end":
        assert await adapter._validate_reader_identity(
            browser_page,
            allow_initial_manifest_loading=True,
        )
        adapter._episode_title = chapter_label
        adapter._captured_indices = list(adapter._body_page_indices)
    await browser_page.locator("img[class*='G54Y0W_page']").first.evaluate(
        """image => { const key=Object.keys(image).find(name=>name.startsWith('__reactFiber$'));
          image[key].memoizedProps.webMangaViewerData.viewerData.pages=null; }"""
    )

    with pytest.raises(UnknownPageStateError):
        await adapter._validate_reader_identity(
            browser_page,
            allow_initial_manifest_loading=True,
            allow_cached_manifest_at_end=stage == "cached_at_end",
            terminal_title=chapter_label if stage == "cached_at_end" else None,
        )


@pytest.mark.parametrize(
    ("complete_capture", "terminal_title", "should_pass"),
    [
        (True, "Ticket target episode", True),
        (False, "Ticket target episode", False),
        (True, "Another episode", False),
    ],
    ids=["complete-positive-end-cache", "partial-body-no-cache", "wrong-end-title-no-cache"],
)
async def test_comicfuz_empty_ssr_manifest_cache_is_end_only_and_bound(
    browser_page,
    complete_capture: bool,
    terminal_title: str,
    should_pass: bool,
) -> None:
    work_id, chapter_id = "3667", "76630"
    chapter_label = "Ticket target episode"
    html = _ticket_viewer_html(
        work_id=work_id,
        chapter_id=chapter_id,
        expiry="\u6b8b\u308a2\u65e5",
        chapter_label=chapter_label,
        relative_rental=True,
        empty_ssr=True,
    )

    async def route_viewer(route) -> None:
        await route.fulfill(status=200, body=html, content_type="text/html; charset=utf-8")

    await browser_page.route(f"{BASE}/manga/viewer/{chapter_id}**", route_viewer)
    await browser_page.goto(f"{BASE}/manga/viewer/{chapter_id}?ticket=true")
    adapter = ComicFuzAdapter()
    await _install_synthetic_ticket_binding(adapter, browser_page)
    assert await adapter._validate_reader_identity(
        browser_page,
        allow_initial_manifest_loading=True,
    )
    assert adapter._empty_ssr_reader_identity is not None
    adapter._episode_title = chapter_label
    adapter._captured_indices = (
        list(adapter._body_page_indices)
        if complete_capture
        else list(adapter._body_page_indices[:-1])
    )
    await browser_page.evaluate(
        """() => {
          const elements = [
            ...document.querySelectorAll('img[class*="G54Y0W_page"]'),
            ...document.querySelectorAll('h2[class*="title_detail_viewer__detail__info__viewerTitle"]')
          ];
          for (const element of elements) {
            for (const key of Object.keys(element))
              if (key.startsWith('__reactFiber$')) delete element[key];
            if (element.tagName === 'IMG') element.remove();
          }
        }"""
    )
    if should_pass:
        assert not await adapter._validate_reader_identity(
            browser_page,
            allow_cached_manifest_at_end=True,
            terminal_title=terminal_title,
        )
    else:
        with pytest.raises(UnknownPageStateError):
            await adapter._validate_reader_identity(
                browser_page,
                allow_cached_manifest_at_end=True,
                terminal_title=terminal_title,
            )


@pytest.mark.parametrize(
    (
        "ticket_available", "use_ticket", "point_free", "point_paid",
        "rental_value", "chapter_point_amount", "response_variant",
    ),
    [
        (False, False, 0, 0, "\u6b8b\u308a2\u65e5", 0, "valid"),
        (True, False, 0, 0, "\u6b8b\u308a2\u65e5", 0, "valid"),
        (False, True, 0, 0, "\u6b8b\u308a2\u65e5", 0, "valid"),
        (True, True, 0, 0, "\u6b8b\u308a2\u65e5", 0, "valid"),
        (False, False, 1, 0, "\u6b8b\u308a2\u65e5", 0, "valid"),
        (True, False, 1, 0, "\u6b8b\u308a2\u65e5", 0, "valid"),
        (False, False, 0, 1, "\u6b8b\u308a2\u65e5", 0, "valid"),
        (True, False, 0, 1, "\u6b8b\u308a2\u65e5", 0, "valid"),
        (False, False, 0, 0, "\u6b8b\u308a0\u65e5", 0, "valid"),
        (True, False, 0, 0, "\u6b8b\u308a0\u65e5", 0, "valid"),
        (False, False, 0, 0, "\u6b8b\u308a2\u65e5", 30, "valid"),
        (True, False, 0, 0, "\u6b8b\u308a2\u65e5", 30, "valid"),
        (False, False, 0, 0, "\u6b8b\u308a2\u65e5", 0, "wrong_chapter"),
        (True, False, 0, 0, "\u6b8b\u308a2\u65e5", 0, "rental_mismatch"),
        (False, False, 0, 0, "\u6b8b\u308a2\u65e5", 0, "missing_point"),
    ],
    ids=[
        "zero_cost_ticket_unavailable", "zero_cost_ticket_available",
        "ticket_request_unavailable", "ticket_request_available",
        "free_point_unavailable", "free_point_available",
        "paid_point_unavailable", "paid_point_available",
        "nonpositive_rental_unavailable", "nonpositive_rental_available",
        "nonzero_chapter_cost_unavailable", "nonzero_chapter_cost_available",
        "response_wrong_chapter", "response_rental_mismatch", "response_missing_point",
    ],
)
async def test_comicfuz_direct_past_ticket_revalidates_relative_rental_without_ticket(
    browser_page,
    browser_context,
    ticket_available: bool,
    use_ticket: bool,
    point_free: int,
    point_paid: int,
    rental_value: str,
    chapter_point_amount: int,
    response_variant: str,
) -> None:
    work_id, chapter_id = "3342", "46741"
    chapter_label = "Target rental episode"
    rental = rental_value
    work_url = f"{BASE}/manga/{work_id}"
    request_body = _direct_viewer_request(
        int(chapter_id),
        use_ticket=use_ticket,
        point_free=point_free,
        point_paid=point_paid,
    )
    response_chapter_id = int(chapter_id) + (1 if response_variant == "wrong_chapter" else 0)
    response_expiry = (
        "\u6b8b\u308a3\u65e5" if response_variant == "rental_mismatch" else rental
    )
    response_body = _ticket_response(
        work_id=int(work_id),
        chapter_id=response_chapter_id,
        expiry=response_expiry,
        point_amount=0,
        point_present=response_variant != "missing_point",
    )
    viewer_html = _ticket_viewer_html(
        work_id=work_id,
        chapter_id=chapter_id,
        expiry=rental,
        chapter_label=chapter_label,
        relative_rental=True,
    )
    viewer_html_js = json.dumps(viewer_html).replace("</", "<\\/")
    bootstrap_html = f'''<!doctype html><html><head><title>Viewer bootstrap</title></head>
      <body><script>(()=>{{
        fetch('https://api.comic-fuz.com/v1/web_manga_viewer_2',{{method:'POST',
          headers:{{'content-type':'text/plain'}},body:new Uint8Array({list(request_body)})}})
          .then(()=>{{document.open();document.write({viewer_html_js});document.close();}})
          .catch(()=>{{}});
      }})();</script></body></html>'''
    listing_html = _relative_rental_listing_html(
        work_id=work_id,
        chapter_id=chapter_id,
        chapter_label=chapter_label,
        rental_value=rental,
        ticket_available=ticket_available,
        point_amount=chapter_point_amount,
    )
    work_visits: list[str] = []
    api_requests: list[bytes] = []

    async def site_route(route) -> None:
        path = route.request.url.split("?", 1)[0]
        if path == work_url:
            work_visits.append(path)
            await route.fulfill(
                status=200,
                content_type="text/html; charset=utf-8",
                body=listing_html,
            )
        elif path == f"{BASE}/manga/viewer/{chapter_id}":
            await route.fulfill(
                status=200,
                content_type="text/html; charset=utf-8",
                body=bootstrap_html,
            )
        elif path in {
            f"{BASE}/assets/manga_detail/charged.svg",
            f"{BASE}/assets/manga_detail/charge.svg",
        }:
            await route.fulfill(
                status=200,
                content_type="image/svg+xml",
                body='<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"></svg>',
            )
        else:
            await route.fulfill(status=404, body="not found")

    async def api_route(route) -> None:
        api_requests.append(route.request.post_data_buffer or b"")
        await route.fulfill(
            status=200,
            content_type="application/octet-stream",
            headers={"access-control-allow-origin": BASE},
            body=response_body,
        )

    await browser_page.route(f"{BASE}/**", site_route)
    await browser_context.route(
        "https://api.comic-fuz.com/v1/web_manga_viewer_2**", api_route
    )
    adapter = ComicFuzAdapter(preflight_work_url=work_url)
    await adapter.prepare_page(browser_page)
    await adapter.configure_target_identity(f"{work_id}:{chapter_id}", "stable-series-slug")
    await adapter.configure_run(browser_page, "direct")
    await adapter.configure_quota_resource(browser_page, "work_ticket")
    initial_url = adapter.resolve_initial_navigation_url(
        f"{BASE}/manga/viewer/{chapter_id}"
    )
    assert initial_url == work_url

    await browser_page.goto(initial_url, wait_until="commit")
    if use_ticket or point_free or point_paid:
        with pytest.raises(UnknownPageStateError, match="direct_viewer_request_not_zero_cost_exact"):
            await adapter.initialize(browser_page)
        assert browser_page.url == f"{BASE}/manga/viewer/{chapter_id}"
        assert work_visits == [work_url]
        assert api_requests == []
        assert adapter.get_access_consumption().consumed is False
        assert adapter._ticket_entry is None
        return
    if rental_value != "\u6b8b\u308a2\u65e5" or chapter_point_amount != 0:
        with pytest.raises(UnknownPageStateError):
            await adapter.initialize(browser_page)
        assert browser_page.url == work_url
        assert work_visits == [work_url]
        assert api_requests == []
        assert adapter.get_access_consumption().consumed is False
        assert adapter._ticket_entry is None
        return
    if response_variant != "valid":
        with pytest.raises(UnknownPageStateError):
            await adapter.initialize(browser_page)
        assert api_requests == [request_body]
        assert adapter.get_access_consumption().consumed is False
        assert adapter._ticket_entry is None
        return
    await adapter.initialize(browser_page)

    assert browser_page.url == f"{BASE}/manga/viewer/{chapter_id}"
    assert work_visits == [work_url]
    assert api_requests == [request_body]
    assert adapter.get_access_consumption().consumed is False
    assert adapter._ticket_entry is None
    assert await adapter.detect_state(browser_page) is PageState.CONTENT
    identity = await adapter.get_content_identity(browser_page)
    assert await adapter.capture_page(browser_page)
    await adapter.go_next(browser_page)
    await adapter.wait_for_change(browser_page, identity)
    assert await adapter.detect_state(browser_page) is PageState.CONTENT
    second_identity = await adapter.get_content_identity(browser_page)
    assert await adapter.capture_page(browser_page)
    await adapter.go_next(browser_page)
    await adapter.wait_for_change(browser_page, second_identity)
    assert await adapter.detect_state(browser_page) is PageState.END
    late_ticket_request = _ticket_request(int(chapter_id))
    await browser_page.evaluate(
        """async body => {
          try {
            await fetch('https://api.comic-fuz.com/v1/web_manga_viewer_2', {
              method:'POST', headers:{'content-type':'text/plain'},
              body:new Uint8Array(body)
            });
          } catch (_) {}
        }""",
        list(late_ticket_request),
    )
    assert api_requests == [request_body]
    with pytest.raises(UnknownPageStateError, match="direct viewer route failed"):
        adapter.get_output_metadata()


async def test_comicfuz_direct_rental_route_stays_terminal_after_cancel(
    browser_page,
    browser_context,
) -> None:
    work_id, chapter_id = "3342", "46741"
    chapter_label = "Target rental episode"
    rental = "\u6b8b\u308a2\u65e5"
    work_url = f"{BASE}/manga/{work_id}"
    request_body = _direct_viewer_request(
        int(chapter_id), use_ticket=False, point_free=0, point_paid=0
    )
    response_body = _ticket_response(
        work_id=int(work_id), chapter_id=int(chapter_id), expiry=rental, point_amount=0
    )
    viewer_html_js = json.dumps(
        _ticket_viewer_html(
            work_id=work_id,
            chapter_id=chapter_id,
            expiry=rental,
            chapter_label=chapter_label,
            relative_rental=True,
        )
    ).replace("</", "<\\/")
    bootstrap_html = f'''<!doctype html><html><body><script>(()=>{{
      fetch('https://api.comic-fuz.com/v1/web_manga_viewer_2',{{method:'POST',
        headers:{{'content-type':'text/plain'}},body:new Uint8Array({list(request_body)})}})
        .then(()=>{{document.open();document.write({viewer_html_js});document.close();}})
        .catch(()=>{{}});
    }})();</script></body></html>'''
    listing_html = _relative_rental_listing_html(
        work_id=work_id,
        chapter_id=chapter_id,
        chapter_label=chapter_label,
        rental_value=rental,
    )
    request_started = asyncio.Event()
    release_response = asyncio.Event()
    api_requests: list[bytes] = []

    async def site_route(route) -> None:
        path = route.request.url.split("?", 1)[0]
        if path == work_url:
            await route.fulfill(
                status=200, content_type="text/html; charset=utf-8", body=listing_html
            )
        elif path == f"{BASE}/manga/viewer/{chapter_id}":
            await route.fulfill(
                status=200, content_type="text/html; charset=utf-8", body=bootstrap_html
            )
        elif path in {
            f"{BASE}/assets/manga_detail/charged.svg",
            f"{BASE}/assets/manga_detail/charge.svg",
        }:
            await route.fulfill(
                status=200,
                content_type="image/svg+xml",
                body='<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"></svg>',
            )
        else:
            await route.fulfill(status=404, body="not found")

    async def api_route(route) -> None:
        api_requests.append(route.request.post_data_buffer or b"")
        request_started.set()
        await release_response.wait()
        await route.fulfill(
            status=200,
            content_type="application/octet-stream",
            headers={"access-control-allow-origin": BASE},
            body=response_body,
        )

    await browser_page.route(f"{BASE}/**", site_route)
    await browser_context.route(
        "https://api.comic-fuz.com/v1/web_manga_viewer_2**", api_route
    )
    adapter = ComicFuzAdapter(preflight_work_url=work_url)
    await adapter.prepare_page(browser_page)
    await adapter.configure_target_identity(f"{work_id}:{chapter_id}", "stable-series-slug")
    await adapter.configure_run(browser_page, "direct")
    await adapter.configure_quota_resource(browser_page, "work_ticket")
    await browser_page.goto(work_url, wait_until="commit")

    operation = asyncio.create_task(adapter.initialize(browser_page))
    try:
        await asyncio.wait_for(request_started.wait(), timeout=5)
        operation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await operation

        late_ticket_request = _ticket_request(int(chapter_id))
        await browser_page.evaluate(
            """async body => {
              try {
                await fetch('https://api.comic-fuz.com/v1/web_manga_viewer_2', {
                  method:'POST', headers:{'content-type':'text/plain'},
                  body:new Uint8Array(body)
                });
              } catch (_) {}
            }""",
            list(late_ticket_request),
        )
        assert api_requests == [request_body]
        with pytest.raises(UnknownPageStateError, match="direct viewer route failed"):
            adapter.get_output_metadata()
    finally:
        release_response.set()
        if not operation.done():
            operation.cancel()


async def test_comicfuz_relative_rental_row_rejects_hidden_ancestor(browser_page) -> None:
    from screenshot_crawler.site_adapters.comicfuz.work_ticket import (
        read_native_ticket_snapshot,
    )

    work_id, chapter_id = "3342", "46741"
    url = f"{BASE}/manga/{work_id}"
    html = _relative_rental_listing_html(
        work_id=work_id,
        chapter_id=chapter_id,
        chapter_label="Target rental episode",
        rental_value="\u6b8b\u308a2\u65e5",
    )

    async def site_route(route) -> None:
        path = route.request.url.split("?", 1)[0]
        if path == url:
            await route.fulfill(
                status=200, content_type="text/html; charset=utf-8", body=html
            )
        elif path in {
            f"{BASE}/assets/manga_detail/charged.svg",
            f"{BASE}/assets/manga_detail/charge.svg",
        }:
            await route.fulfill(
                status=200,
                content_type="image/svg+xml",
                body='<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"></svg>',
            )
        else:
            await route.fulfill(status=404, body="not found")

    await browser_page.route(f"{BASE}/**", site_route)
    await browser_page.goto(url, wait_until="domcontentloaded")
    await browser_page.locator('div[class*="title_detail_chapters__list__"]').evaluate(
        "element => { element.style.opacity = '0'; }"
    )
    with pytest.raises(UnknownPageStateError):
        await read_native_ticket_snapshot(
            browser_page,
            work_id=work_id,
            chapter_id=chapter_id,
            page_mode="rental_listing",
        )


@pytest.mark.parametrize(
    (
        "native_amount",
        "row_same_chapter",
        "row_same_point",
        "row_root_class_tokens",
        "false_descendant",
        "expected_state",
    ),
    [
        (30, True, True, RENTAL_ROW_ROOT_CLASSES, False, None),
        (30, True, True, RENTAL_ROW_ROOT_CLASSES + ("false",), False, None),
        (30, True, True, (RENTAL_ROW_ROOT_CLASSES[0],), False, "rental_listing_row_not_exact"),
        (30, True, True, RENTAL_ROW_ROOT_CLASSES + ("true",), False, "rental_listing_row_not_exact"),
        (30, True, True, RENTAL_ROW_ROOT_CLASSES + ("null",), False, "rental_listing_row_not_exact"),
        (30, True, True, RENTAL_ROW_ROOT_CLASSES + ("undefined",), False, "rental_listing_row_not_exact"),
        (30, True, True, RENTAL_ROW_ROOT_CLASSES + ("mystery",), False, "rental_listing_row_not_exact"),
        (30, True, True, RENTAL_ROW_ROOT_CLASSES, True, "rental_listing_row_not_exact"),
        (30, False, True, RENTAL_ROW_ROOT_CLASSES, False, "listing_runtime_chapter_reference_mismatch"),
        (30, False, False, RENTAL_ROW_ROOT_CLASSES, False, "listing_runtime_chapter_reference_mismatch"),
        ("30", True, True, RENTAL_ROW_ROOT_CLASSES, False, "listing_runtime_point_amount_mismatch"),
        (-1, True, True, RENTAL_ROW_ROOT_CLASSES, False, "listing_runtime_point_amount_mismatch"),
        (None, True, True, RENTAL_ROW_ROOT_CLASSES, False, "listing_runtime_point_amount_mismatch"),
    ],
    ids=[
        "three_layer_ssr30_runtime_default_zero",
        "rental_root_cosmetic_false_token",
        "rental_root_missing_mandatory_token",
        "rental_root_extra_true_token",
        "rental_root_extra_null_token",
        "rental_root_extra_undefined_token",
        "rental_root_extra_unknown_token",
        "rental_descendant_false_token",
        "row_chapter_object_drift",
        "row_chapter_and_point_object_drift",
        "ssr_amount_string",
        "ssr_amount_negative",
        "ssr_amount_missing",
    ],
)
async def test_comicfuz_rental_listing_requires_runtime_refs_and_valid_ssr_amount(
    browser_page,
    native_amount: int | str | None,
    row_same_chapter: bool,
    row_same_point: bool,
    row_root_class_tokens: tuple[str, ...],
    false_descendant: bool,
    expected_state: str | None,
) -> None:
    from screenshot_crawler.site_adapters.comicfuz.work_ticket import (
        read_native_ticket_snapshot,
    )

    work_id, chapter_id = "3342", "46741"
    url = f"{BASE}/manga/{work_id}"
    html = _relative_rental_listing_html(
        work_id=work_id,
        chapter_id=chapter_id,
        chapter_label="Target rental episode",
        rental_value="\u6b8b\u308a2\u65e5",
        native_point_amount=native_amount,
        row_runtime_same_chapter=row_same_chapter,
        row_runtime_same_point=row_same_point,
        row_root_class_tokens=row_root_class_tokens,
        false_descendant=false_descendant,
    )

    async def site_route(route) -> None:
        path = route.request.url.split("?", 1)[0]
        if path == url:
            await route.fulfill(
                status=200, content_type="text/html; charset=utf-8", body=html
            )
        elif path in {
            f"{BASE}/assets/manga_detail/charged.svg",
            f"{BASE}/assets/manga_detail/charge.svg",
        }:
            await route.fulfill(
                status=200,
                content_type="image/svg+xml",
                body='<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"></svg>',
            )
        else:
            await route.fulfill(status=404, body="not found")

    await browser_page.route(f"{BASE}/**", site_route)
    await browser_page.goto(url, wait_until="domcontentloaded")
    if expected_state is None:
        snapshot = await read_native_ticket_snapshot(
            browser_page,
            work_id=work_id,
            chapter_id=chapter_id,
            page_mode="rental_listing",
        )
        assert snapshot.point_amount == 0
        assert snapshot.point_amount_present is False
        assert snapshot.point_amount_prototype_default_zero is True
        assert snapshot.point_type_present is False
        assert snapshot.point_type_prototype_default_zero is True
        return

    with pytest.raises(UnknownPageStateError, match=expected_state):
        await read_native_ticket_snapshot(
            browser_page,
            work_id=work_id,
            chapter_id=chapter_id,
            page_mode="rental_listing",
        )


async def test_comicfuz_batch_revalidates_past_quota_hint_as_direct_rental(
    browser_page,
    browser_context,
    tmp_path: Path,
    sync_legacy_unscoped_work,
) -> None:
    work_id, chapter_id = "3342", "46741"
    work_url = f"{BASE}/manga/{work_id}"
    label = "Target rental episode"
    now = datetime.now(JST)
    rental = "\u6b8b\u308a2\u65e5"
    direct_request = _direct_viewer_request(
        int(chapter_id), use_ticket=False, point_free=0, point_paid=0
    )
    response_body = _ticket_response(
        work_id=int(work_id), chapter_id=int(chapter_id), expiry=rental, point_amount=0
    )
    viewer_html_js = json.dumps(
        _ticket_viewer_html(
            work_id=work_id,
            chapter_id=chapter_id,
            expiry=rental,
            chapter_label=label,
            relative_rental=True,
        )
    ).replace("</", "<\\/")
    viewer_bootstrap = f'''<!doctype html><html><body><script>(()=>{{
      fetch('https://api.comic-fuz.com/v1/web_manga_viewer_2',{{method:'POST',
        headers:{{'content-type':'text/plain'}},body:new Uint8Array({list(direct_request)})}})
        .then(()=>{{document.open();document.write({viewer_html_js});document.close();}})
        .catch(()=>{{}});
    }})();</script></body></html>'''
    initial_quota_listing = _work_ticket_listing_html(
        work_id=work_id,
        chapter_id=chapter_id,
        chapter_label=label,
        request_body=_ticket_request(int(chapter_id)),
        viewer_html=_ticket_viewer_html(
            work_id=work_id,
            chapter_id=chapter_id,
            expiry=(now + timedelta(days=1)).isoformat(),
            chapter_label=label,
        ),
    )
    current_relative_rental_listing = _relative_rental_listing_html(
        work_id=work_id,
        chapter_id=chapter_id,
        chapter_label=label,
        rental_value=rental,
        row_root_class_tokens=RENTAL_ROW_ROOT_CLASSES + ("false",),
    )
    current_listing = [initial_quota_listing]
    work_visits: list[str] = []
    viewer_visits: list[str] = []
    api_requests: list[bytes] = []

    async def site_route(route) -> None:
        path = route.request.url.split("?", 1)[0]
        if path == work_url:
            work_visits.append(path)
            await route.fulfill(
                status=200,
                content_type="text/html; charset=utf-8",
                body=current_listing[0],
            )
        elif path == f"{BASE}/manga/viewer/{chapter_id}":
            viewer_visits.append(path)
            await route.fulfill(
                status=200,
                content_type="text/html; charset=utf-8",
                body=viewer_bootstrap,
            )
        elif path in {
            f"{BASE}/assets/manga_detail/charged.svg",
            f"{BASE}/assets/manga_detail/charge.svg",
        }:
            await route.fulfill(
                status=200,
                content_type="image/svg+xml",
                body='<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"></svg>',
            )
        else:
            await route.fulfill(status=404, body="not found")

    async def api_route(route) -> None:
        api_requests.append(route.request.post_data_buffer or b"")
        await route.fulfill(
            status=200,
            content_type="application/octet-stream",
            headers={"access-control-allow-origin": BASE},
            body=response_body,
        )

    await browser_page.route(f"{BASE}/**", site_route)
    await browser_context.route(
        "https://api.comic-fuz.com/v1/web_manga_viewer_2**", api_route
    )
    catalog = CatalogService(tmp_path / "relative-rental-batch.sqlite")
    target = WatchlistTarget(
        key="comicfuz-relative-rental-batch",
        work_key="after-work-slug",
        site="comicfuz",
        url=work_url,
        label="Relative rental batch target",
    )
    registry = DiscoveryAdapterRegistry()
    registry.register("comicfuz", ComicFuzDiscoveryAdapter)
    discovery = DiscoveryService(catalog, registry)
    result = await discovery.discover(browser_page, target, "full")
    assert result.complete is True
    watchlist = sync_legacy_unscoped_work(catalog, target)
    source = catalog.get_source_by_external_id("comicfuz", f"{work_id}:{chapter_id}")
    assert source.access_mode == "quota"
    quota_started_at = now - timedelta(days=2)
    catalog.record_quota_access(
        source.id,
        quota_started_at=quota_started_at,
        access_granted_until=None,
    )
    before_source = catalog.get_source(source.id)
    before_work_state = catalog.get_quota_resource_state(
        source_item_work_id := catalog.get_item(source.item_id).work_id,
        site="comicfuz",
        resource="work_ticket",
    )
    assert before_work_state is None

    current_listing[0] = current_relative_rental_listing
    policies = SitePolicyRegistry()
    policies.register("comicfuz", ComicFuzSitePolicy)
    plan = BatchPlanner(catalog, policies, watchlist=watchlist).plan(
        site="comicfuz", now=now
    )
    assert len(plan.candidates) == 1
    candidate = plan.candidates[0]
    assert candidate.external_id == f"{work_id}:{chapter_id}"
    assert candidate.access_strategy == "direct"
    assert candidate.quota_resource == "work_ticket"
    assert candidate.consumes_quota is False
    adapter = ComicFuzAdapter()
    adapters = AdapterRegistry()
    adapters.register("comicfuz", lambda: adapter)
    executor = BatchExecutor(
        catalog,
        policies,
        adapters,
        runtime_settings=SiteRuntimeSettings(page_turn_delay_ms=0),
        library_dir=tmp_path / "relative-rental-library",
        watchlist=watchlist,
    )

    result = await executor.execute_candidate(
        browser_page,
        candidate,
        output_root=tmp_path / "relative-rental-output",
        library_dir=tmp_path / "relative-rental-library",
        max_pages=5,
        now=now,
    )

    run = catalog.get_crawl_run(result.crawl_run_id)
    after_source = catalog.get_source(source.id)
    assert result.stop_reason == "end" and result.page_count == 2
    assert run.status == "succeeded" and run.page_count == 2
    assert "access_consumption_confirmed:" not in (run.stop_reason or "")
    assert catalog.get_item(candidate.item_id).status == "completed"
    artifacts = catalog.list_artifacts(item_id=candidate.item_id)
    assert len(artifacts) == 1 and artifacts[0].format == "zip"
    assert before_source.quota_started_at == after_source.quota_started_at
    assert before_source.access_granted_until is None
    assert after_source.access_granted_until is None
    assert catalog.get_quota_resource_state(
        source_item_work_id, site="comicfuz", resource="work_ticket"
    ) is None
    assert adapter.get_access_consumption().consumed is False
    assert api_requests == [direct_request]
    assert viewer_visits == [f"{BASE}/manga/viewer/{chapter_id}"]
    assert len(work_visits) == 2


async def test_unavailable_work_ticket_skips_only_that_work_and_replans(
    browser_page,
    browser_context,
    tmp_path: Path,
    sync_legacy_unscoped_work,
) -> None:
    work_data = [
        ("3667", "76630", "Unavailable target", False),
        ("3152", "49007", "Available target", True),
    ]
    now = datetime.now(JST)
    expiry = (now + timedelta(days=1)).isoformat()
    listings: dict[str, str] = {}
    targets = []
    for work_id, chapter_id, label, charge_available in work_data:
        request_body = _ticket_request(int(chapter_id))
        viewer_html = _ticket_viewer_html(
            work_id=work_id,
            chapter_id=chapter_id,
            expiry=expiry,
            chapter_label=label,
        )
        listings[f"{BASE}/manga/{work_id}"] = _work_ticket_listing_html(
            work_id=work_id,
            chapter_id=chapter_id,
            chapter_label=label,
            request_body=request_body,
            viewer_html=viewer_html,
            charge_available=charge_available,
        )
        targets.append(
            WatchlistTarget(
                key=f"comicfuz-ticket-{work_id}",
                work_key=f"series-{work_id}",
                site="comicfuz",
                url=f"{BASE}/manga/{work_id}",
                label=f"Ticket target {work_id}",
            )
        )
    work_page_visits: list[str] = []
    viewer_navigations: list[str] = []
    api_requests: list[bytes] = []

    async def comicfuz_route(route) -> None:
        path = route.request.url.split("?", 1)[0]
        if path in listings:
            work_page_visits.append(path)
            await route.fulfill(
                status=200,
                content_type="text/html; charset=utf-8",
                body=listings[path],
            )
        elif path.startswith(f"{BASE}/manga/viewer/"):
            viewer_navigations.append(path)
            await route.fulfill(status=404, body="unexpected viewer navigation")
        elif path in {
            f"{BASE}/assets/manga_detail/charged.svg",
            f"{BASE}/assets/manga_detail/charge.svg",
        }:
            await route.fulfill(
                status=200,
                content_type="image/svg+xml",
                body='<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"></svg>',
            )
        else:
            await route.fulfill(status=404, body="not found")

    async def api_route(route) -> None:
        request_body = route.request.post_data_buffer or b""
        api_requests.append(request_body)
        expected = _ticket_request(49007)
        if request_body != expected:
            await route.abort("blockedbyclient")
            return
        await route.fulfill(
            status=200,
            content_type="application/octet-stream",
            headers={"access-control-allow-origin": BASE},
            body=_ticket_response(work_id=3152, chapter_id=49007, expiry=expiry),
        )

    await browser_page.route(f"{BASE}/**", comicfuz_route)
    await browser_context.route(
        "https://api.comic-fuz.com/v1/web_manga_viewer_2**", api_route
    )
    catalog = CatalogService(tmp_path / "unavailable-catalog.sqlite")
    discovery_registry = DiscoveryAdapterRegistry()
    discovery_registry.register("comicfuz", ComicFuzDiscoveryAdapter)
    discovery = DiscoveryService(catalog, discovery_registry)
    watchlist = None
    for target in targets:
        discovered = await discovery.discover(browser_page, target, "full")
        assert discovered.complete is True
        watchlist = sync_legacy_unscoped_work(catalog, target)
    assert watchlist is not None
    catalog.record_quota_access(
        catalog.get_source_by_external_id("comicfuz", "3667:76630").id,
        quota_started_at=now - timedelta(days=2),
        access_granted_until=None,
    )

    policies = SitePolicyRegistry()
    policies.register("comicfuz", ComicFuzSitePolicy)
    plan = BatchPlanner(catalog, policies, watchlist=watchlist).plan(
        site="comicfuz", now=now
    )
    candidates = sorted(plan.candidates, key=lambda candidate: candidate.work_id or 0)
    assert [candidate.external_id for candidate in candidates] == ["3667:76630", "3152:49007"]
    assert [(candidate.access_strategy, candidate.quota_resource) for candidate in candidates] == [
        ("direct", "work_ticket"),
        ("quota", "work_ticket"),
    ]
    attempts = []
    adapters = AdapterRegistry()
    adapters.register("comicfuz", ComicFuzAdapter)
    executor = BatchExecutor(
        catalog,
        policies,
        adapters,
        runtime_settings=SiteRuntimeSettings(page_turn_delay_ms=0),
        library_dir=tmp_path / "unavailable-library",
        watchlist=watchlist,
        access_attempt_sink=attempts.append,
    )

    class Session:
        async def new_page(self):
            page = await browser_context.new_page()
            await page.route(f"{BASE}/**", comicfuz_route)
            return page

        async def close_page(self, page):
            await page.close()

    args = cli._parser().parse_args(["batch", "run", "--site", "comicfuz"])
    args.output_root = tmp_path / "unavailable-output"
    args.library_dir = tmp_path / "unavailable-library"
    args.max_pages = 5
    args.max_same_content = 2
    args.keep_open = False
    assert await cli._execute_batch_candidates(
        args,
        Session(),
        executor,
        candidates,
        phase="ComicFUZ ticket no-action fixture",
        inter_candidate_delay_ms=0,
    ) == (2, True)

    runs = catalog.list_crawl_runs()
    unavailable_run = next(run for run in runs if run.external_id_snapshot == "3667:76630")
    successful_run = next(run for run in runs if run.external_id_snapshot == "3152:49007")
    assert unavailable_run.status == "failed" and unavailable_run.page_count is None
    assert unavailable_run.stop_reason == "comicfuz_work_ticket_not_attempted"
    assert unavailable_run.error_type == "ComicFuzTicketNotAttemptedError"
    assert successful_run.status == "succeeded" and successful_run.page_count == 2
    assert [observation.status for observation in attempts] == [
        "not_attempted",
        "attempting",
        "confirmed",
    ]
    assert len(api_requests) == 1 and api_requests[0] == _ticket_request(49007)
    assert viewer_navigations == []
    assert set(work_page_visits) == {target.url for target in targets}
    replanned = BatchPlanner(catalog, policies, watchlist=watchlist).plan(
        site="comicfuz", now=now + timedelta(minutes=1)
    )
    assert any(candidate.external_id == "3667:76630" for candidate in replanned.candidates)


@pytest.mark.parametrize(
    ("extra_tail", "latest_end", "body_count", "extra_tail_unlinked_pair", "first_blank"),
    [
        (False, "none", 2, False, True), (True, "none", 2, False, True),
        (True, "valid", 2, False, True), (False, "valid", 2, False, True),
        (True, "account_recommendations", 2, False, True),
        (True, "none", 1, False, True),
        (True, "account_recommendations", 1, False, True),
        (True, "none", 12, True, True),
        (True, "none", 12, True, False),
    ],
    ids=[
        "body-only", "legacy-extra-tail", "legacy-next-chapter-end", "latest-end",
        "legacy-extra-account-recommendation", "legacy-single-body", "legacy-single-body-end",
        "unlinked-pair-tail-blank-first", "unlinked-pair-tail-nonblank-first",
    ],
)
async def test_comicfuz_discovery_to_batch_zip_completes_and_rerun_preserves_artifact(
    browser_page, tmp_path: Path, sync_legacy_unscoped_work, extra_tail: bool, latest_end: str,
    body_count: int, extra_tail_unlinked_pair: bool, first_blank: bool,
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
        extra_tail_unlinked_pair=extra_tail_unlinked_pair,
        first_page_blank=first_blank,
        first_mode_body_page_count=body_count,
        true_mode_body_page_count=body_count,
        native_subtitle="Fixture subtitle" if latest_end == "valid" else "",
    )

    result = await executor.execute_candidate(
        browser_page,
        candidate,
        output_root=tmp_path / "batch-output",
        library_dir=tmp_path / "library",
        max_pages=max(5, body_count),
        now=NOW,
    )

    item = catalog.get_item(candidate.item_id)
    run = catalog.get_crawl_run(result.crawl_run_id)
    artifacts = catalog.list_artifacts(item_id=item.id)
    assert item.status == "completed"
    assert run.status == "succeeded" and run.stop_reason == "end"
    assert result.stop_reason == "end" and result.page_count == body_count
    assert len(artifacts) == 1 and artifacts[0].format == "zip"
    assert result.archive_path.name.startswith("003-")
    with zipfile.ZipFile(result.archive_path) as archive:
        names = archive.namelist()
        assert len(names) == body_count
        assert all(name.lower().endswith(".png") for name in names)

    rediscovered = await discovery.discover(browser_page, target, "full")
    planner = BatchPlanner(catalog, executor.policies, watchlist=watchlist)
    assert rediscovered.complete is True
    assert rediscovered.new_count == 0 and rediscovered.known_count == 3
    replanned = planner.plan(site="comicfuz", now=NOW)
    assert catalog.get_item(candidate.item_id).status == "completed"
    assert len(catalog.list_artifacts(item_id=candidate.item_id)) == 1
    assert all(entry.item_id != candidate.item_id for entry in replanned.candidates)
    assert sum(candidate.external_id == "1970:80641" for candidate in plan.candidates) == 1


@pytest.mark.parametrize("failure", [
    "stale_free", "route_drift", "unknown_tail", "stuck_extra_tail", "stuck_single_extra_tail",
    "uul_stuck", "uul_premature_end",
    "missing_actions", "wrong_labels", "hidden_recommendations", "duplicate_title",
    "duplicate_recommendations",
])
async def test_comicfuz_batch_failures_never_complete_or_create_artifact(
    browser_page, tmp_path: Path, sync_legacy_unscoped_work, failure: str
) -> None:
    route_change = failure == "route_drift"
    unknown_tail = failure == "unknown_tail"
    unlinked_pair_tail = failure in {"uul_stuck", "uul_premature_end"}
    catalog, _discovery, _target, _plan, candidate, executor, _seen, _watchlist = (
        await _comicfuz_batch_fixture(
            browser_page,
            tmp_path,
            sync_legacy_unscoped_work,
            unknown_tail=unknown_tail,
            route_change_on_first_turn=route_change,
            extra_tail=unlinked_pair_tail or failure not in {"stale_free", "route_drift", "unknown_tail"},
            extra_tail_unlinked_pair=unlinked_pair_tail,
            true_mode_body_page_count=(
                12 if unlinked_pair_tail else (1 if failure == "stuck_single_extra_tail" else 2)
            ),
            first_mode_body_page_count=12 if unlinked_pair_tail else 4,
            first_page_blank=True,
            initial_state=99 if failure == "uul_premature_end" else 0,
            stuck_extra_tail=failure == "uul_stuck" or failure in {
                "stuck_extra_tail", "stuck_single_extra_tail"
            },
            latest_end=(
                "valid" if failure == "uul_premature_end" else (
                    failure if failure in {
                        "missing_actions", "wrong_labels", "hidden_recommendations",
                        "duplicate_title", "duplicate_recommendations",
                    }
                    else "none"
                )
            ),
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
            max_pages=20 if unlinked_pair_tail else 5,
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
    if failure in {"stuck_extra_tail", "stuck_single_extra_tail"}:
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


@pytest.mark.parametrize("sign_in", [True, False], ids=["anonymous", "signed-in"])
async def test_comicfuz_runner_crawls_verified_spreads_to_positive_end(
    browser_page, tmp_path: Path, sign_in: bool
) -> None:
    seen = await _route_comicfuz(browser_page, transition_delay_ms=350, sign_in=sign_in)
    adapter = ComicFuzAdapter(preflight_work_url=WORK_URL)
    # This success-path test needs animation + stable reads + browser latency;
    # its old 800 ms adapter budget was tighter than the Runner's 2 s budget.
    adapter.page_change_timeout_ms = 2_000
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


@pytest.mark.parametrize(("overlap_state", "overlap_size", "extra_tail", "body_count", "first_blank"), [
    (3, 3, False, 10, True), (3, 4, False, 10, True), (5, 3, False, 10, True),
    (2, 3, True, 2, True), (2, 4, True, 2, True),
    (1, 3, True, 1, True), (2, 3, True, 1, True),
    (1, 3, True, 4, False), (1, 4, True, 4, False), (4, 3, True, 9, True),
])
async def test_comicfuz_waits_through_contiguous_transition_overlap_and_reaches_end(
    browser_page, tmp_path: Path, overlap_state: int, overlap_size: int, extra_tail: bool,
    body_count: int, first_blank: bool,
) -> None:
    previous = [1, 2] if extra_tail else ([3, 4] if overlap_state == 3 else [7, 8])
    next_group = [3, 4] if extra_tail else ([5, 6] if overlap_state == 3 else [9, 10])
    if body_count == 1:
        previous, next_group = ([0], [1, 2]) if overlap_state == 1 else ([1, 2], [3])
    elif not first_blank:
        previous, next_group = [0, 1], [2, 3]
    elif body_count == 9:
        previous, next_group = [5, 6], [7, 8]
    new_count = overlap_size - len(previous)
    await _route_comicfuz(
        browser_page,
        true_mode_body_page_count=body_count,
        first_mode_body_page_count=body_count,
        first_page_blank=first_blank,
        extra_tail=extra_tail,
        transition_delay_ms=180,
        transition_overlap_state=overlap_state,
        transition_overlap_new_count=new_count,
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
    assert len(result.pages) == body_count
    expected_ids = ["page_0"] if first_blank else []
    for start in range(1 if first_blank else 0, body_count, 2):
        group = list(range(start, min(start + 2, body_count)))
        expected_ids.extend(["|".join(f"page_{number}" for number in group)] * len(group))
    assert [page.identity.page_id for page in result.pages] == expected_ids
    assert adapter._captured_indices == list(range(body_count))
    assert bool(adapter._advanced_extra_groups) is extra_tail
    expected_overlap = previous + next_group[:new_count]
    if body_count == 1:
        assert adapter._advanced_extra_groups == ((1, 2), (3,))
    observed_overlap = await browser_page.evaluate("() => window.transitionOverlapSeen")
    assert observed_overlap == {
        "state": overlap_state,
        "numbers": expected_overlap,
        "imageReady": [True] * overlap_size,
        "ready": [False, *([True] * (overlap_size - 2)), False],
    }
    assert not (tmp_path / "overlap-output" / "archive.zip").exists()


@pytest.mark.parametrize(("extra_tail", "body_count", "first_blank"), [
    (False, 10, True), (True, 2, True), (True, 1, True), (True, 4, False),
])
async def test_comicfuz_persistent_transition_overlap_times_out_without_batch_artifact(
    browser_page, tmp_path: Path, sync_legacy_unscoped_work, extra_tail: bool,
    body_count: int, first_blank: bool,
) -> None:
    catalog, _discovery, _target, _plan, candidate, executor, _seen, _watchlist = (
        await _comicfuz_batch_fixture(
            browser_page,
            tmp_path,
            sync_legacy_unscoped_work,
            page_change_timeout_ms=250,
            true_mode_body_page_count=body_count,
            first_mode_body_page_count=body_count,
            first_page_blank=first_blank,
            extra_tail=extra_tail,
            transition_delay_ms=80,
            transition_overlap_state=1 if body_count == 1 or not first_blank else (2 if extra_tail else 3),
            transition_overlap_new_count=2 if body_count == 1 else 1,
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
    ("variant", "extra_tail"),
    [(variant, False) for variant in [
        "outside", "gap", "duplicate", "role", "all_ready", "visual_unsafe", "dimensions",
    ]] + [(variant, True) for variant in ["role", "all_ready", "visual_unsafe", "dimensions"]],
)
async def test_comicfuz_invalid_transition_wide_shapes_fail_closed(
    browser_page, tmp_path: Path, variant: str, extra_tail: bool,
) -> None:
    await _route_comicfuz(
        browser_page,
        true_mode_body_page_count=2 if extra_tail else 10,
        extra_tail=extra_tail,
        transition_delay_ms=160,
        transition_overlap_state=2 if extra_tail else 3,
        transition_overlap_variant=variant,
        # Keep the invalid state observable; a transient 160 ms fixture can
        # disappear between browser polls under load before it is validated.
        persistent_transition_overlap=True,
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


@pytest.mark.parametrize("sign_in", [True, False], ids=["anonymous", "signed-in"])
async def test_comicfuz_nonfree_preflight_stops_before_reader_navigation(
    browser_page, tmp_path: Path, sign_in: bool
) -> None:
    seen = await _route_comicfuz(browser_page, free=False, sign_in=sign_in)
    adapter = ComicFuzAdapter(preflight_work_url=WORK_URL)
    config = RunConfig(
        site="comicfuz",
        source_url=VIEWER_URL,
        output_dir=tmp_path / "isolated-output",
        diagnostics_dir=tmp_path / "isolated-output" / "diagnostics",
        page_turn_delay_ms=0,
        navigation_timeout_ms=2_000,
    )

    with pytest.raises(UnknownPageStateError, match="lacks exact current public-free listing"):
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


@pytest.mark.parametrize(
    ("first_page_blank", "initial_state", "restored_numbers", "initial_numbers"),
    [
        (True, 6, (11, 12), (0,)),
        (False, 6, (12, 13), (0, 1)),
        (False, 7, (14,), (0, 1)),
    ],
    ids=["restored-final-body-and-extra", "restored-unlinked-pair", "restored-linked-last"],
)
async def test_comicfuz_uul_restored_positions_rewind_before_capture(
    browser_page,
    first_page_blank: bool,
    initial_state: int,
    restored_numbers: tuple[int, ...],
    initial_numbers: tuple[int, ...],
) -> None:
    await _route_comicfuz(
        browser_page,
        extra_tail_unlinked_pair=True,
        first_page_blank=first_page_blank,
        first_page_blank_inherited=not first_page_blank,
        first_mode_body_page_count=12,
        true_mode_body_page_count=12,
        initial_state=initial_state,
    )
    adapter = ComicFuzAdapter(preflight_work_url=WORK_URL)
    await adapter.prepare_page(browser_page)
    await browser_page.goto(WORK_URL, wait_until="commit")
    await adapter.configure_target_identity("1970:80641", "comicfuz:1970")
    adapter.resolve_initial_navigation_url(VIEWER_URL)

    await adapter.initialize(browser_page)

    rows = await adapter._active_page_rows(browser_page)
    assert tuple(row["number"] for row in rows) == initial_numbers
    assert adapter._captured_indices == []
    assert tuple(row["number"] for row in rows) != restored_numbers


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


@pytest.mark.parametrize("native_title", [
    "第31話 特典情報", "第31話\u3000特典情報", "  第31話\t\n\u3000特典情報  ",
])
async def test_comicfuz_output_metadata_uses_verified_work_and_episode_titles(
    browser_page,
    native_title: str,
) -> None:
    listing_title = "第31話 特典情報"
    await _route_comicfuz(browser_page, listing_title=listing_title,
                         native_title=native_title, viewer_title=listing_title)
    adapter = ComicFuzAdapter(preflight_work_url=WORK_URL)
    await adapter.prepare_page(browser_page)
    await browser_page.goto(WORK_URL, wait_until="commit")
    await adapter.configure_target_identity("1970:80641", "comicfuz:1970")
    adapter.resolve_initial_navigation_url(VIEWER_URL)

    await adapter.initialize(browser_page)

    metadata = adapter.get_output_metadata()
    assert metadata["title"] == "Verified ComicFUZ Work"
    assert metadata["order"] == listing_title
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


@pytest.mark.parametrize("loading", [
    "delayed-first", "temporary-gap", "temporary-gap-pair", "rewind-gap", "permanent-gap",
    "changed-after-gap", "chapter-drift-in-gap",
])
async def test_comicfuz_waits_for_initial_native_page_manifest(browser_page, monkeypatch, loading) -> None:
    await _route_comicfuz(browser_page, delayed_manifest_ms=250 if loading == "delayed-first" else 0,
                         initial_state=1 if loading == "rewind-gap" else 0,
                         first_page_blank=loading != "temporary-gap-pair")
    adapter = ComicFuzAdapter(preflight_work_url=WORK_URL)
    adapter.page_change_timeout_ms = 300 if loading == "permanent-gap" else 1_500
    missing_reads = 0
    if loading != "delayed-first":
        original = adapter._read_viewer_snapshot
        triggered = False
        restoration_scheduled = False

        async def replace_initial_fibers(page):
            nonlocal triggered, missing_reads, restoration_scheduled
            snapshot = await original(page)
            can_trigger = loading != "rewind-gap" or await page.locator("img.G54Y0W_page").first.get_attribute("alt") == "page_0"
            if snapshot["pages"] is not None and not triggered and can_trigger:
                triggered = True
                await page.evaluate("""mode => {
                  window.initialManifestGap = [...document.querySelectorAll('img.G54Y0W_page')].map(image => {
                    const key = Object.keys(image).find(k => k.startsWith('__reactFiber$'));
                    const fiber = image[key];
                    const props = fiber.memoizedProps;
                    fiber.memoizedProps = {};
                    return [fiber, props];
                  });
                  if (mode === 'chapter-drift-in-gap') {
                    const node = document.querySelector('#__NEXT_DATA__');
                    const data = JSON.parse(node.textContent);
                    data.props.pageProps.chapterId = '999';
                    node.textContent = JSON.stringify(data);
                  }
                }""", loading)
            elif snapshot["pages"] is None and triggered:
                missing_reads += 1
                if not restoration_scheduled and loading != "permanent-gap":
                    restoration_scheduled = True
                    # Restore only after the gap was actually observed, so a
                    # slow browser cannot make this success test vacuous.
                    await page.evaluate("""mode => setTimeout(() => {
                    for (const [fiber, props] of window.initialManifestGap) {
                      if (mode === 'changed-after-gap')
                        props.webMangaViewerData.viewerData.pages[0].image.imageWidth += 1;
                      fiber.memoizedProps = props;
                    }
                    }, 250)""", loading)
            return snapshot

        monkeypatch.setattr(adapter, "_read_viewer_snapshot", replace_initial_fibers)
    await adapter.prepare_page(browser_page)
    await browser_page.goto(WORK_URL, wait_until="commit")
    await adapter.configure_target_identity("1970:80641", "comicfuz:1970")
    adapter.resolve_initial_navigation_url(VIEWER_URL)

    if loading == "permanent-gap":
        with pytest.raises(PageChangeTimeoutError, match="first reader page did not become stable"):
            await adapter.initialize(browser_page)
    elif loading in {"changed-after-gap", "chapter-drift-in-gap"}:
        with pytest.raises(UnknownPageStateError, match=(
            "manifest changed" if loading == "changed-after-gap" else "metadata differs"
        )):
            await adapter.initialize(browser_page)
    else:
        await adapter.initialize(browser_page)
        expected_initial = (0, 1) if loading == "temporary-gap-pair" else (0,)
        assert tuple(row["number"] for row in await adapter._active_page_rows(browser_page)) == expected_initial

    assert adapter._viewer_pages is not None
    assert adapter._captured_indices == []
    if loading != "delayed-first":
        assert missing_reads > 0


@pytest.mark.parametrize("operation", ["detect", "capture"])
async def test_comicfuz_established_manifest_disappearance_fails_closed(browser_page, operation) -> None:
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
        if operation == "detect":
            await adapter.detect_state(browser_page)
        else:
            await adapter.capture_page(browser_page)


@pytest.mark.parametrize("drift", [
    "title", "subtitle", "malformed_subtitle", "main_title", "chapter", "work",
])
async def test_comicfuz_identity_drift_fails_closed(browser_page, drift: str) -> None:
    await _route_comicfuz(browser_page)
    adapter = ComicFuzAdapter(preflight_work_url=WORK_URL)
    await adapter.prepare_page(browser_page)
    await browser_page.goto(WORK_URL, wait_until="commit")
    await adapter.configure_target_identity("1970:80641", "comicfuz:1970")
    adapter.resolve_initial_navigation_url(VIEWER_URL)
    await adapter.initialize(browser_page)

    if drift == "title":
        await browser_page.locator(adapter.viewer_title_selector).evaluate(
            "element => element.textContent = 'different episode'"
        )
    else:
        field, value = {
            "main_title": ("chapterMainName", "different main title"),
            "chapter": ("chapterId", "999"),
            "work": ("mangaId", "999"),
            "subtitle": ("chapterSubName", "different subtitle"),
            "malformed_subtitle": ("chapterSubName", 1),
        }[drift]
        await browser_page.evaluate(
            """([field, value]) => {
              const node = document.querySelector('#__NEXT_DATA__');
              const data = JSON.parse(node.textContent);
              if (field === 'chapterId') data.props.pageProps.chapterId = value;
              else data.props.pageProps.data[field] = value;
              node.textContent = JSON.stringify(data);
            }""",
            [field, value],
        )

    with pytest.raises(UnknownPageStateError):
        await adapter.detect_state(browser_page)


@pytest.mark.parametrize("body_count", [1, 2])
async def test_comicfuz_extra_tail_cannot_skip_uncaptured_body_or_be_captured(
    browser_page, body_count: int,
) -> None:
    await _route_comicfuz(browser_page, extra_tail=True, true_mode_body_page_count=body_count)
    adapter = ComicFuzAdapter(preflight_work_url=WORK_URL)
    await browser_page.goto(WORK_URL, wait_until="commit")
    await adapter.configure_target_identity("1970:80641", "comicfuz:1970")
    adapter.resolve_initial_navigation_url(VIEWER_URL)
    await adapter.initialize(browser_page)
    await adapter.capture_page(browser_page)
    # Skip the final body+extra spread, or the required first extra pair.
    await browser_page.keyboard.press("ArrowLeft")
    await browser_page.wait_for_function("document.querySelector('img').alt === 'page_1'")
    await browser_page.keyboard.press("ArrowLeft")
    await browser_page.wait_for_function("document.querySelector('img').alt === 'page_3'")
    with pytest.raises(UnknownPageStateError, match="extra tail is out of sequence"):
        await adapter.detect_state(browser_page)
    capture_error = "page group does not match" if body_count == 1 else "no verified body"
    with pytest.raises(UnknownPageStateError, match=capture_error):
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
