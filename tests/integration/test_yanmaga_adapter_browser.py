from __future__ import annotations

import asyncio
import base64
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from urllib.parse import quote, unquote, urlsplit

import pytest
from PIL import Image
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from screenshot_crawler.batch import (
    BatchExecutionError,
    BatchExecutor,
    BatchInterruptedError,
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
    AccessStopError,
    PageChangeTimeoutError,
    UnknownPageStateError,
)
from screenshot_crawler.core.models import RunConfig
from screenshot_crawler.core.runner import CrawlerRunner
from screenshot_crawler.core.state import PageState
from screenshot_crawler.runtime_settings import SiteRuntimeSettings
from screenshot_crawler.site_adapters.registry import AdapterRegistry
from screenshot_crawler.site_adapters.yanmaga import adapter as adapter_module
from screenshot_crawler.site_adapters.yanmaga.adapter import YanmagaAdapter
from screenshot_crawler.site_adapters.yanmaga.discovery import (
    YanmagaDiscoveryAdapter,
    YanmagaEpisodeParts,
)
from screenshot_crawler.site_adapters.yanmaga.native_capture import (
    MAX_CAPTURE_ENCODED_BYTES,
    MAX_CAPTURE_PIXELS,
    capture_yanmaga_native_webp,
    dispose_yanmaga_native_observer,
    install_yanmaga_native_observer,
    release_yanmaga_native_page,
)
from screenshot_crawler.site_adapters.yanmaga.rental_history import (
    RentalCountdown,
    RentalHistoryObservation,
)
from screenshot_crawler.site_policies import SitePolicyRegistry, YanmagaSitePolicy
from tests.helpers.acquisition_scope import synchronized_legacy_planner

pytestmark = pytest.mark.asyncio(loop_scope="module")

SLUG = "ウサギとカメのゆる山歩"
EPISODE_ID = "2de76848d607c9920f18147b763a6aec"
NEXT_EPISODE_ID = "abcdef0123456789abcdef0123456789"
NEXT_ORDER_LABEL = "\u6b21\u306e\u8a71 \u6b69\u8abf"
WAIT_NEXT_ORDER_LABEL = "\u7b2c\uff13\uff10\u8a71 \u30c6\u30b9\u30c8"
WAIT_END_CLOCK_SRC = (
    "https://viewer-assets.yanmaga.jp/viewer/assets/img/"
    "icon_clock-048e89030730e8f736d174dde55780bad06a38135282b236b2c20ae032812836.svg"
)
LATEST_AUTHOR_LINK_SRC = (
    "https://viewer-assets.yanmaga.jp/viewer/assets/img/"
    "sns-x-9af04e53dce57ba890a7ccc29c10ef2d0359814ed03edf511023afb6a28b852b.png"
)
LATEST_AUTHOR_ARROW_SRC = (
    "https://viewer-assets.yanmaga.jp/viewer/assets/img/"
    "arrow-right-402a9836009e2194d9ea5e0cfe96f36bc4dc1aa721be087f829dc8e19f2a1d11.png"
)
ENGAGEMENT_NOTE_SRC = (
    "https://viewer-assets.yanmaga.jp/viewer/assets/img/"
    "like_note-4469488c0f4e846b0cc34a2dcb85e4d6b0eb5f68101e4ebfb5a521476d99adf3.png"
)
WAIT_MODAL_WORK_TITLE = "Synthetic work"
WAIT_MODAL_EPISODE_TITLE = "\u7b2c\uff11\u8a71\u3000Synthetic"
WORK_URL = f"https://yanmaga.jp/comics/{quote(SLUG, safe='')}"
SOURCE_URL = f"{WORK_URL}/{EPISODE_ID}"
VIEWER_URL = f"https://yanmaga.jp/viewer/comics/{quote(SLUG, safe='')}/{EPISODE_ID}"
VIEWER_NAVIGATION_URL = f"{VIEWER_URL}?cid=AbCd0123456789EfGhIj"
WORK_KEY = f"yanmaga:{SLUG}"
NOW = datetime(2026, 10, 20, 12, tzinfo=JST)
GRANT_OBSERVED_AT = datetime.now(UTC) - timedelta(minutes=5)
GRANT_UNTIL = GRANT_OBSERVED_AT + timedelta(hours=21)


def _segment_data(color: str, index: int) -> str:
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="1127" height="536">'
        f'<rect width="1127" height="536" fill="{color}"/>'
        f'<text x="32" y="80" font-size="48">page {index}</text></svg>'
    )
    return f"data:image/svg+xml,{quote(svg, safe='')}"


def _viewer_html(
    *,
    first_free_completion_notice: bool = False,
    quota_completion_notice: bool = False,
    access_proof_delay_ms: int = 0,
    access_proof_never_ready: bool = False,
    access_gate_text: str | None = None,
    inline_rental_card: bool = False,
    inline_rental_dialog: bool = False,
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
    native_page_width: int = 1125,
    native_style_unsupported: bool = False,
    native_layer_unsupported: bool = False,
    native_transparent: bool = False,
    native_ambiguous: bool = False,
    native_host_pseudo_issue: str | None = None,
    native_wrapper_transform: str | None = None,
    odd_terminal_only: bool = False,
    even_terminal_only: bool = False,
    single_page: bool = False,
) -> str:
    wrappers = []
    colors = ("#b32b39", "#22784c", "#345ca8", "#b08228")
    if odd_terminal_only:
        colors = colors[:3]
    if single_page:
        colors = colors[:1]
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
            else "1280px"
            if index == 4 and inline_rental_card
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
    if access_gate_text is not None:
        auxiliary += f'<div class="access-gate-modal">{access_gate_text}</div>'
    if access_gate:
        auxiliary += (
            '<div role="dialog" class="quota-modal" '
            'style="position:absolute;right:10px;bottom:50px;width:220px;height:100px">'
            'ポイントを使って読む</div>'
        )
    title_label = (
        WAIT_NEXT_ORDER_LABEL
        if terminal_control.startswith(("wait_countdown", "point_rental", "ready_wait"))
        else NEXT_ORDER_LABEL
    )
    title = f'<span class="episode-modal-eptitle">{title_label}</span>'
    next_control = '<a id="js-btn-valid-next-episode">次の話を読む</a>'
    signup_control = (
        '<a class="mod-button--orange content ga-viewer-rental-signup" '
        f'href="/customers/sign-up?forward={NEXT_EPISODE_ID}">無料登録して読む</a>'
    )
    point_code = "06A0000000001000001A"
    point_control = (
        '<div class="episode-modal-thumbnail"><div class="episode-modal-image">'
        '<img class="content" src="https://eh96lnrmau.user-space.cdn.idcfcloud.net/'
        f'thumbnail/episode/{point_code}.jpg"></div></div>'
        '<dl class="episode-modal-point--necessary"><dd>'
        '<span class="mod-episode-point--normal">70</span></dd></dl>'
        '<div class="aspect-ratio-108-17 mt-button">'
        '<a id="js-btn-rental" class="mod-button--orange rental content">'
        '<span>レンタルして読む</span>'
        '<form id="form-rental" class="ga-viewer-rental-point" action="/viewer/rental" method="post">'
        f'<input type="hidden" name="jdcn" value="{point_code}">'
        '<input type="hidden" name="rental_type" value="point_rental">'
        '</form></a></div>'
    )
    point_controls = {
        "point_rental": point_control,
        "point_rental_wrong_title": point_control,
        "point_rental_semantic_dialog": point_control,
        "point_rental_wrong_label": point_control.replace("レンタルして読む", "読む"),
        "point_rental_foreign_action": point_control.replace(
            'action="/viewer/rental"', 'action="https://example.invalid/viewer/rental"'
        ),
        "point_rental_wrong_action": point_control.replace('/viewer/rental"', '/other"'),
        "point_rental_wrong_method": point_control.replace('method="post"', 'method="get"'),
        "point_rental_wrong_type": point_control.replace('value="point_rental"', 'value="other"'),
        "point_rental_duplicate_code": point_control.replace(
            '</form>', f'<input type="hidden" name="jdcn" value="{point_code}"></form>'
        ),
        "point_rental_wrong_thumbnail": point_control.replace(
            f'{point_code}.jpg', '06A0000000001000002B.jpg'
        ),
        "point_rental_bad_code": point_control.replace(point_code, 'not-a-code'),
        "point_rental_zero_cost": point_control.replace('>70<', '>0<'),
        "point_rental_duplicate": point_control + point_control,
        "point_rental_hidden": point_control.replace(
            'id="js-btn-rental"', 'id="js-btn-rental" style="display:none"'
        ),
        "point_rental_and_next": point_control + next_control,
    }
    ready_wait_control = point_control.replace(
        '<dl class="episode-modal-point--necessary"><dd>'
        '<span class="mod-episode-point--normal">70</span></dd></dl>', ''
    ).replace('ga-viewer-rental-point', 'ga-viewer-rental-free-wait').replace(
        'value="point_rental"', 'value="free_rental_if_wait"'
    ).replace('レンタルして読む', '「待つと無料....！」で読む')
    point_controls.update({
        "ready_wait": ready_wait_control,
        "ready_wait_missing_marker": ready_wait_control,
        "ready_wait_wrong_title": ready_wait_control,
        "ready_wait_wrong_label": ready_wait_control.replace('「待つと無料....！」で読む', '読む'),
        "ready_wait_wrong_type": ready_wait_control.replace('free_rental_if_wait', 'other'),
        "ready_wait_foreign_action": ready_wait_control.replace(
            'action="/viewer/rental"', 'action="https://example.invalid/viewer/rental"'),
        "ready_wait_wrong_thumbnail": ready_wait_control.replace(
            f'{point_code}.jpg', '06A0000000001000002B.jpg'),
        "ready_wait_duplicate": ready_wait_control + ready_wait_control,
    })
    latest_author_control = (
        '<div id="js-rental-box" class="rental-bg ga-viewer-rental">'
        '<div id="js-modal-content" class="rental-modal">'
        '<div class="wrapper-rental-button">'
        '<div id="js-modal-button" class="wrapper-mod-modal background-transparent">'
        '<a class="author-info" href="https://x.com/test-author" '
        'target="_blank" rel="noopener noreferrer">'
        f'<img class="author-link" src="{LATEST_AUTHOR_LINK_SRC}">'
        '<span class="author-name">'
        '\u4f5c\u8005\u3092\u30d5\u30a9\u30ed\u30fc\u3057\u3066'
        '\u6b21\u306e\u66f4\u65b0\u3092\u5f85\u3064\uff01'
        '</span>'
        f'<img class="author-arrow" src="{LATEST_AUTHOR_ARROW_SRC}">'
        '</a></div></div></div></div>'
    )
    controls = {
        **point_controls,
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
        "wait_countdown": (
            '<div class="aspect-ratio-2-27 mt-wait">'
            '<div class="episode-modal-wait content">'
            f'<img class="icon-clock" src="{WAIT_END_CLOCK_SRC}">'
            '<span>あと22:04で無料</span></div></div>'
        ),
        "latest_author": latest_author_control,
        "latest_author_nonlatest": latest_author_control,
        "latest_author_missing": "",
        "missing": "",
    }
    engagement_control = (
        '<div id="js-rental-box" class="rental-bg ga-viewer-rental">'
        '<div id="js-modal-content" class="rental-modal"><div class="wrapper-rental-button">'
        f'<div class="like-note"><img src="{ENGAGEMENT_NOTE_SRC}"></div>'
        '<div id="js-modal-button" class="wrapper-mod-modal background-transparent">'
        '<div class="mod-modal-button"><div class="spacer"></div>'
        '<a id="js-btn-favorite" class="circle-button favorite">'
        '<div class="icon-wrapper"><span>お気に入り</span></div>'
        '<form id="form-favorite" class="ga-viewer-rental-favorite" '
        'action="/viewer/favorite" method="post">'
        '<input type="hidden" name="jdcn" value="AbCd0123456789EfGhIj"></form></a>'
        '<div class="like-wrapper"><a id="js-btn-like" class="circle-button like">'
        '<div class="icon-wrapper"><span>いいね</span><span>12</span></div>'
        '<form id="form-like" class="ga-viewer-rental-like" action="/viewer/like" method="post">'
        '<input type="hidden" name="jdcn" value="AbCd0123456789EfGhIj"></form></a></div>'
        '<a id="js-btn-twitter" class="circle-button shared ga-viewer-rental-share" '
        f'href="https://twitter.com/intent/tweet?url={quote(SOURCE_URL, safe="")}">'
        '<div class="icon-wrapper"><span>シェア</span></div></a>'
        '<div class="spacer"></div></div></div>'
        '<p id="error-favorite-like" class="error-text"></p></div></div></div>'
    )
    author_control = latest_author_control[
        latest_author_control.index('<a class="author-info"'):latest_author_control.index('</a>') + 4
    ].replace('https://x.com/test-author', 'https://x.com/test-author?s=20')
    engagement_with_author = engagement_control.replace(
        '<div class="spacer"></div></div></div>',
        '<div class="spacer"></div></div>' + author_control + '</div>',
    )
    controls.update({
        "engagement": engagement_control,
        "engagement_author": engagement_with_author,
        "engagement_author_plain_url": engagement_with_author.replace('?s=20', ''),
        "engagement_author_bad_query": engagement_with_author.replace('?s=20', '?s=21'),
        "engagement_author_duplicate_query": engagement_with_author.replace('?s=20', '?s=20&s=20'),
        "engagement_author_foreign": engagement_with_author.replace('https://x.com/', 'https://example.invalid/'),
        "engagement_author_wrong_label": engagement_with_author.replace('作者をフォロー', '作品をフォロー'),
        "engagement_author_wrong_asset": engagement_with_author.replace('sns-x-', 'unknown-'),
        "engagement_author_duplicate": engagement_with_author.replace(author_control, author_control * 2),
        "engagement_author_hidden": engagement_with_author.replace(
            'class="author-info"', 'class="author-info" style="display:none"'),
        "engagement_author_wrong_position": engagement_with_author.replace(
            author_control, '').replace('<div class="mod-modal-button">',
                                       author_control + '<div class="mod-modal-button">'),
        "engagement_author_wrong_code": engagement_with_author.replace('AbCd0123456789EfGhIj', '0' * 20),
        "engagement_offscreen": engagement_control,
        "engagement_obstructed": engagement_control,
        "engagement_wrong_code": engagement_control.replace('AbCd0123456789EfGhIj', '0' * 20),
        "engagement_duplicate_code": engagement_control.replace(
            '</form>', '<input type="hidden" name="jdcn" value="AbCd0123456789EfGhIj"></form>'
        ),
        "engagement_visible_code": engagement_control.replace('type="hidden"', 'type="text"'),
        "engagement_wrong_action": engagement_control.replace('/viewer/like', '/viewer/rental'),
        "engagement_foreign_action": engagement_control.replace(
            'action="/viewer/like"', 'action="https://example.invalid/viewer/like"'
        ),
        "engagement_wrong_method": engagement_control.replace('method="post"', 'method="get"'),
        "engagement_wrong_label": engagement_control.replace('お気に入り', '読む'),
        "engagement_missing_like": engagement_control.replace('id="js-btn-like"', 'id="other"'),
        "engagement_duplicate_like": engagement_control.replace(
            '<div class="spacer"></div>', '<a id="js-btn-like">いいね</a>'
        ),
        "engagement_wrong_note": engagement_control.replace('like_note-', 'unknown-'),
        "engagement_hidden": engagement_control.replace(
            'id="js-btn-favorite"', 'id="js-btn-favorite" style="visibility:hidden"'
        ),
        "engagement_wrong_share": engagement_control.replace(
            quote(SOURCE_URL, safe=''), quote(SOURCE_URL.replace(EPISODE_ID, 'f' * 32), safe='')
        ),
        "engagement_with_next": engagement_control + next_control,
        "engagement_semantic_dialog": engagement_control + '<div role="dialog">ログイン</div>',
    })
    if terminal_control == "wait_countdown_bad_time":
        controls[terminal_control] = controls["wait_countdown"].replace(
            "あと22:04で無料", "あと22:90で無料"
        )
    elif terminal_control in {
        "wait_countdown_bad_time",
        "wait_countdown_wrong_title",
        "wait_countdown_semantic_dialog",
        "wait_countdown_missing_marker",
    }:
        controls[terminal_control] = controls["wait_countdown"]
    if terminal_control not in controls:
        raise ValueError(f"unsupported synthetic terminal control: {terminal_control}")
    rental_title = title
    if terminal_control == "signup_wrong_title":
        rental_title = title.replace(NEXT_ORDER_LABEL, "\u5225\u306e\u8a71")
    elif terminal_control in {
        "wait_countdown_wrong_title", "point_rental_wrong_title", "ready_wait_wrong_title"
    }:
        rental_title = title.replace(WAIT_NEXT_ORDER_LABEL, "\u5225\u306e\u8a71")
    rental_card = ""
    if inline_rental_card:
        dialog = (
            '<div role="dialog" class="episode-modal-expire">'
            "\u30ec\u30f3\u30bf\u30eb</div>"
            if inline_rental_dialog
            else ""
        )
        rental_card = (
            '<div id="js-modal-content" class="rental-modal">'
            '<div class="mod-modal-content wrapper-mod-modal">'
            '<div class="mod-modal-content-inner episode-modal">'
            '<div class="episode-modal-rental-detail">'
            "\u30ec\u30f3\u30bf\u30eb\u4e2d</div>"
            '<div class="episode-modal-expire">'
            "\u6b8b\u308a23\u6642\u9593</div>"
            '<div class="episode-modal-point">'
            "\u30dd\u30a4\u30f3\u30c8 70</div>"
            '<dl class="episode-modal-point--posession">'
            '<dt>\u4fdd\u6709\u30dd\u30a4\u30f3\u30c8</dt><dd>70</dd></dl>'
            '<dl class="episode-modal-point--necessary">'
            '<dt>\u5fc5\u8981\u30dd\u30a4\u30f3\u30c8</dt><dd>70</dd></dl>'
            '<div class="episode-modal-short">\u30ec\u30f3\u30bf\u30eb\u4e2d</div>'
            f"{dialog}</div></div></div>"
        )
    rental_content = (
        ""
        if unsafe_end
        else controls[terminal_control]
        if terminal_control.startswith(("latest_author", "engagement"))
        else rental_title + controls[terminal_control] + rental_card
    )
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
    initial_page = 1 if single_page else 5 if even_terminal_only else 1 if first_page_overlay else 4
    menu_initial_display = "block" if first_page_overlay else "none"
    menu_after_roundtrip = "none" if menu_hideable else "block"
    edge_overlay = '<div id="edge-obstruction"></div>' if edge_obstruction else ""
    first_free_notice = (
        "<div>" + "".join(map(chr, (0x7121, 0x6599, 0x30ec, 0x30f3, 0x30bf, 0x30eb,
                                     0x304c, 0x5b8c, 0x4e86, 0x3057, 0x307e, 0x3057, 0x305f))) + "</div>"
        if first_free_completion_notice
        else ""
    )
    quota_notice = (
        "<div>" + "".join(map(chr, (0x30ec, 0x30f3, 0x30bf, 0x30eb,
                                     0x304c, 0x5b8c, 0x4e86, 0x3057, 0x307e, 0x3057, 0x305f))) + "</div>"
        if quota_completion_notice
        else ""
    )
    html = f'''<!doctype html><html><head><meta charset="utf-8"><title>Test | YanmagaWeb</title>
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
      #rental{{position:absolute;top:{rental_top};left:{'8px' if inline_rental_card else '20px'};width:{'1272px' if inline_rental_card else '500px'};height:{'1700px' if inline_rental_card else '300px'};background:#eee}}
      #rental .aspect-ratio-2-27.mt-wait{{width:220px;height:32px}}
      #rental .episode-modal-wait.content{{display:flex;align-items:center;gap:6px;width:220px;height:32px}}
      #rental .episode-modal-wait img.icon-clock{{width:16px;height:16px}}
      #rental .circle-button{{display:inline-block;width:120px;height:90px;vertical-align:top}}
      #rental .like-wrapper{{display:inline-block}}
      #menu{{position:fixed;inset:0;display:{menu_initial_display};z-index:30;background:rgba(0,0,0,.01)}}
      #menu_transparent{{position:absolute;inset:0;background:rgba(0,0,0,.01)}}
      #menu_header{{position:absolute;top:0;left:0;width:100%;height:100px;background:#ddd}}
      #menu_controller{{position:absolute;bottom:0;left:0;width:100%;height:100px;background:#ddd}}
      #edge-obstruction{{position:fixed;left:0;top:0;width:8px;height:8px;z-index:40;background:#f00}}
      #ads,#recommend{{position:absolute;width:1px;height:1px;overflow:hidden}}
      {obstruction_css}
    </style></head><body>{first_free_notice}{quota_notice}
    {'' if odd_terminal_only or even_terminal_only or single_page else f'<span id="counter">{initial_page}/4</span>'}
    {arrow}
    <div class="pages" id="content">{''.join(wrappers)}{rental}{auxiliary}</div>
    <div id="menu"><div id="menu_transparent"></div><div id="menu_header">
      <span id="menu_header_parent_title">テスト作品</span><span id="menu_header_tittle">第1話</span>
      <a id="detail_story" class="button-episode" href="{WORK_URL}">作品詳細</a>
      <a href="/mypage">マイページ</a>
      {'' if terminal_control.startswith('latest_author') and terminal_control != 'latest_author_nonlatest' else f'<a id="next_story" class="button-episode" title="次の話" href="{WORK_URL}/{NEXT_EPISODE_ID}">次の話</a>'}
    </div><div id="menu_controller"></div>
      {f'<div id="menu_seekbar"><div id="menu_slidercaption_base"><div id="menu_slidercaption">{"1/1" if single_page else "-/4" if even_terminal_only else "-/3"}</div></div></div>' if odd_terminal_only or even_terminal_only or single_page else ''}
    </div>
    {edge_overlay}
    <script>
      let current={initial_page};
      const counter=document.querySelector('#counter,#menu_slidercaption');
      const pages=[...document.querySelectorAll('.body-page')];
      const rental=document.querySelector('#rental');
      const menu=document.querySelector('#menu');
      const arrow=document.querySelector('#arrow-content');
      const initialOverlay={json.dumps(first_page_overlay)};
      const menuHideable={json.dumps(menu_hideable)};
      let leftFromFirst=false;
      const delayedEnd={json.dumps(delayed_end)};
      const accessProofDelayMs={access_proof_delay_ms};
      const accessProofNeverReady={json.dumps(access_proof_never_ready)};
      const arrowVisibleAtEnd={arrow_visible_at_end};
      const nativeCapture={json.dumps(native_capture)};
      const nativeTransparent={json.dumps(native_transparent)};
      const nativeAmbiguous={json.dumps(native_ambiguous)};
      const oddTerminalOnly={json.dumps(odd_terminal_only)};
      const evenTerminalOnly={json.dumps(even_terminal_only)};
      const singlePage={json.dumps(single_page)};
      function show(value){{
        const previous=current;
        if(singlePage){{
          current=value;counter.textContent=value===1?'1/1':'-/1';
          pages[0].style.display='block';pages[0].style.left=value===1?'0px':'2602px';
          rental.style.display=value===1?'none':'block';
          rental.style.left='1280px';rental.style.top='0px';
          rental.style.width='1272px';rental.style.height='1800px';
          return;
        }}
        current=value; counter.textContent=`${{value}}/4`;
        if(oddTerminalOnly) counter.textContent=value===4?'-/3':`${{value}}/3`;
        pages.forEach(node=>node.style.display='none');
        if(oddTerminalOnly) pages.forEach(node=>{{
          node.style.left=node.id==='content-p3'?'1290px':'0px';
        }});
        if(value===1) document.querySelector('#content-p1').style.display='block';
        if(value===2){{document.querySelector('#content-p2').style.display='block';document.querySelector('#content-p3').style.display='block';}}
        if(value===4 && !oddTerminalOnly) document.querySelector('#content-p4').style.display='block';
        rental.style.display=value===4?'block':'none';
        if(value===4 && oddTerminalOnly){{
          pages.forEach((node,index)=>{{node.style.display='block';node.style.left=(5200-index*1300)+'px';}});
          rental.style.left='1280px';rental.style.top='0px';
          rental.style.width='1272px';rental.style.height='1800px';
        }}
        if(evenTerminalOnly){{
          counter.textContent=value===5?'-/4':`${{value}}/4`;
          pages.forEach((node,index)=>{{
            node.style.display='block';
            node.style.left=value===5?(6500-index*1300)+'px':
              value===1?(index<2?index*1290:-2600)+'px':
              (index>=2?(index-2)*1290:-2600)+'px';
          }});
          rental.style.display=value===5?'block':'none';
          rental.style.left='1280px';rental.style.top='0px';
          rental.style.width='1272px';rental.style.height='1800px';
        }}
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
        if(singlePage){{
          if(event.key==='d' && menuHideable)setTimeout(()=>menu.style.display='none',80);
          if(event.key==='ArrowRight')show(1);
          if(event.key==='ArrowLeft')show(2);
          return;
        }}
        if(evenTerminalOnly){{
          if(event.key==='ArrowRight') show(current===5?3:1);
          if(event.key==='ArrowLeft') show(current===1?3:5);
          return;
        }}
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
      if(accessProofDelayMs>0 || accessProofNeverReady){{
        counter.textContent='';
        pages.forEach(node=>node.style.display='none');
        if(!accessProofNeverReady) setTimeout(()=>show({initial_page}),accessProofDelayMs);
      }} else show({initial_page});
      fetch('/viewer/rental_episode?jdcn=AbCd0123456789EfGhIj&random_identification={EPISODE_ID}&viewer_type=comics&vm=2');
    </script></body></html>'''
    if native_capture and native_page_width != 1125:
        html = (html.replace('canvas.width=1127;', f'canvas.width={native_page_width + 2};')
                .replace('1267.864624px', f'{(native_page_width + 2) * 1.125}px')
                .replace('1267.875px', f'{(native_page_width + 2) * 1.125}px')
                .replace('1265.625px', f'{native_page_width * 1.125}px')
                .replace('14.375px', f'{1280 - native_page_width * 1.125}px'))
    response_content = rental_content
    if terminal_control.endswith('_wrong_title'):
        response_content = response_content.replace('別の話', title_label)
    if terminal_control in {'wait_countdown_missing_marker', 'ready_wait_missing_marker'}:
        response_content = ''
    html += '<!--NATIVE_RESPONSE--><div id="rental">' + response_content + '</div>'
    return html


def _wait_rental_intro_html(
    form_episode_id: str = EPISODE_ID,
    button_attributes: str = "",
    modal_delay_ms: int = 0,
) -> str:
    modal_hidden_attribute = (
        'style="display: none"'
        if modal_delay_ms
        else ""
    )
    modal_script = (
        '<script>setTimeout(() => { '
        'document.querySelector(".mod-modal-content.js-modal-content").removeAttribute("style"); '
        f'}}, {modal_delay_ms});</script>'
        if modal_delay_ms
        else ""
    )
    return f'''<!doctype html><html><head>
      <meta charset="utf-8">
      <link rel="canonical" href="{WORK_URL}">
      <meta property="og:url" content="{SOURCE_URL}">
      </head><body>
      <a href="/mypage">My page</a>
      <div class="episode-ui"><div class="episode-free-time charged">
        <span class="episode-free-time-bar-label">チャージ完了</span>
        <span class="episode-free-time-label"><img src="/assets/logo_free_browse-96b8e1d8.svg"></span>
      </div></div>
      <div class="mod-modal-content js-modal-content" {modal_hidden_attribute}>
        <div class="mod-modal-content-inner episode-modal active">
          <p class="mod-modal-title">\u300c\u5f85\u3064\u3068\u7121\u6599....!\u300d\u3067\u30ec\u30f3\u30bf\u30eb</p>
          <p class="episode-modal-title">{WAIT_MODAL_WORK_TITLE}</p>
          <p class="episode-modal-eptitle">{WAIT_MODAL_EPISODE_TITLE}</p>
          <div class="episode-modal-rental-detail">
            <div class="episode-modal-expire">\u30ec\u30f3\u30bf\u30eb\u671f\u9593 /
              <span>3\u65e5\u9593</span>
            </div>
          </div>
          <form class="button_to" method="post"
                action="/rental/episodes/{form_episode_id}/by_free_waits" data-remote="true">
            <button id="free-browse-rental" class="mod-button--orange" type="submit" {button_attributes}>\u8aad\u3080</button>
            <input type="hidden" name="authenticity_token" value="synthetic-token">
          </form>
        </div>
      </div>
      {modal_script}
      </body></html>'''


async def _set_routes(
    page,
    monkeypatch,
    *,
    access_mode: str = "free",
    terminal_response_case: str = "valid",
    charged_ui: bool = True,
    authenticated_listing: bool | None = None,
    wait_form_episode_id: str = EPISODE_ID,
    wait_button_attributes: str = "",
    wait_modal_delay_ms: int = 0,
    quota_completion_notice: bool = False,
    source_goto_failure: str | None = None,
    first_free_completion_notice: bool = False,
    access_proof_delay_ms: int = 0,
    access_proof_never_ready: bool = False,
    access_gate_text: str | None = None,
    missing_half: bool = False,
    thin_segment: bool = False,
    oversized_last_segment: bool = False,
    unknown_aux: bool = False,
    unsafe_end: bool = False,
    delayed_end: bool = False,
    access_gate: bool = False,
    inline_rental_card: bool = False,
    inline_rental_dialog: bool = False,
    terminal_geometry: str = "valid",
    arrow_mode: str = "hidden",
    first_page_overlay: bool = False,
    menu_hideable: bool = True,
    edge_obstruction: bool = False,
    adjacent_overlap: bool = False,
    terminal_control: str = "valid_next",
    native_capture: bool = False,
    native_page_width: int = 1125,
    native_style_unsupported: bool = False,
    native_layer_unsupported: bool = False,
    native_transparent: bool = False,
    native_ambiguous: bool = False,
    native_host_pseudo_issue: str | None = None,
    native_wrapper_transform: str | None = None,
    odd_terminal_only: bool = False,
    even_terminal_only: bool = False,
    single_page: bool = False,
    wrong_route: bool = False,
) -> list[str]:
    requested: list[str] = []
    monkeypatch.setattr(adapter_module, "RENDER_POLL_MS", 20)

    async def fake_records(*_args, **_kwargs):
        pytest.fail("Capture must never run Full Discovery")
        yield  # pragma: no cover

    monkeypatch.setattr(YanmagaDiscoveryAdapter, "iter_records", fake_records)
    wrong_viewer_url = f"https://yanmaga.jp/viewer/comics/別作品/{EPISODE_ID}"

    viewer_document = _viewer_html(
        missing_half=missing_half,
        access_proof_delay_ms=access_proof_delay_ms,
        access_proof_never_ready=access_proof_never_ready,
        access_gate_text=access_gate_text,
        thin_segment=thin_segment,
        oversized_last_segment=oversized_last_segment,
        unknown_aux=unknown_aux,
        unsafe_end=unsafe_end,
        delayed_end=delayed_end,
        access_gate=access_gate,
        inline_rental_card=inline_rental_card,
        inline_rental_dialog=inline_rental_dialog,
        terminal_geometry=terminal_geometry,
        arrow_mode=arrow_mode,
        first_page_overlay=first_page_overlay,
        menu_hideable=menu_hideable,
        first_free_completion_notice=first_free_completion_notice,
        quota_completion_notice=quota_completion_notice,
        edge_obstruction=edge_obstruction,
        adjacent_overlap=adjacent_overlap,
        terminal_control=terminal_control,
        native_capture=native_capture,
        native_page_width=native_page_width,
        native_style_unsupported=native_style_unsupported,
        native_layer_unsupported=native_layer_unsupported,
        native_transparent=native_transparent,
        native_ambiguous=native_ambiguous,
        native_host_pseudo_issue=native_host_pseudo_issue,
        native_wrapper_transform=native_wrapper_transform,
        odd_terminal_only=odd_terminal_only,
        even_terminal_only=even_terminal_only,
        single_page=single_page,
    )
    viewer_document, native_response = viewer_document.split("<!--NATIVE_RESPONSE-->", 1)
    if terminal_response_case == "wrong_episode":
        viewer_document = viewer_document.replace(
            "random_identification=" + EPISODE_ID, "random_identification=" + "f" * 32
        )
    elif terminal_response_case == "duplicate_query":
        viewer_document = viewer_document.replace(
            "viewer_type=comics", "viewer_type=comics&viewer_type=comics"
        )
    elif terminal_response_case == "wrong_code":
        viewer_document = viewer_document.replace("jdcn=AbCd0123456789EfGhIj", "jdcn=" + "0" * 20)
    elif terminal_response_case == "unknown_mode":
        viewer_document = viewer_document.replace("vm=2", "vm=3")
    elif terminal_response_case == "duplicate_root":
        native_response += '<div id="rental"></div>'
    elif terminal_response_case == "oversized":
        native_response += "x" * (512 * 1024)
    elif terminal_response_case == "popup_iframe":
        viewer_document = viewer_document.replace(
            "&viewer_type=comics&vm=2');",
            "&viewer_type=comics&vm=2').then(() => {const f=document.createElement('iframe');"
            "f.style.display='none';f.src='/viewer/rental_episode?viewer_type=comics&popup=true';"
            "document.body.append(f);});",
        )

    if access_mode in {"known_restricted", "unknown"}:
        viewer_document = '<div role="dialog">ポイントを使って読む</div>'
    if access_mode == "wait_free":
        source_document = _wait_rental_intro_html(
            wait_form_episode_id,
            button_attributes=wait_button_attributes,
            modal_delay_ms=wait_modal_delay_ms,
        )
        if not charged_ui:
            source_document = source_document.replace(
                "episode-free-time charged", "episode-free-time"
            )
        if authenticated_listing is False:
            source_document = source_document.replace('<a href="/mypage">My page</a>', "")
    else:
        source_document = ""

    async def route_handler(route):
        url = route.request.url
        requested.append(url)
        parsed_url = urlsplit(url)
        path = unquote(parsed_url.path)
        if path == "/mypage":
            await route.fulfill(
                status=200, content_type="text/html", body='<a href="/mypage">マイページ</a>'
            )
        elif path == "/viewer/rental_episode":
            await route.fulfill(
                status=404 if terminal_response_case == "missing" else 200,
                content_type="application/json"
                if terminal_response_case == "wrong_mime"
                else "text/html",
                body=native_response,
            )
        elif path == unquote(urlsplit(WORK_URL).path):
            pytest.fail("Capture must not open the work listing")
        elif path in {
            unquote(urlsplit(VIEWER_URL).path),
            unquote(urlsplit(wrong_viewer_url).path),
        }:
            await route.fulfill(
                status=200,
                content_type="text/html",
                body=viewer_document,
            )
        elif path == unquote(urlsplit(SOURCE_URL).path) and access_mode == "wait_free":
            await route.fulfill(
                status=200,
                content_type="text/html",
                body=source_document,
            )
        elif (
            path == f"/rental/episodes/{EPISODE_ID}/by_free_waits"
            and access_mode == "wait_free"
            and route.request.method.upper() == "POST"
        ):
            await route.fulfill(
                status=200,
                content_type="text/html",
                body=f'<script>location.replace("{VIEWER_NAVIGATION_URL}")</script>',
            )
        elif path == "/assets/logo_free_browse-96b8e1d8.svg":
            await route.fulfill(
                status=200,
                content_type="image/svg+xml",
                body='<svg xmlns="http://www.w3.org/2000/svg" width="102" height="16"></svg>',
            )
        else:
            await route.fulfill(status=404, body="not found")

    await page.route("https://yanmaga.jp/**", route_handler)

    async def route_wait_clock(route):
        await route.fulfill(
            status=200,
            content_type="image/svg+xml",
            body='<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"></svg>',
        )

    await page.route(WAIT_END_CLOCK_SRC, route_wait_clock)
    if terminal_control.startswith(("latest_author", "point_rental", "engagement", "ready_wait")):
        tiny = io.BytesIO()
        Image.new("RGBA", (2, 2), (255, 255, 255, 255)).save(tiny, format="PNG")
        image_bytes = tiny.getvalue()

        async def route_author_asset(route):
            await route.fulfill(status=200, content_type="image/png", body=image_bytes)

        await page.route(LATEST_AUTHOR_LINK_SRC, route_author_asset)
        await page.route(LATEST_AUTHOR_ARROW_SRC, route_author_asset)
        await page.route(ENGAGEMENT_NOTE_SRC, route_author_asset)

        async def route_unknown_note(route):
            await route.fulfill(status=404, body="not found")

        await page.route(ENGAGEMENT_NOTE_SRC.replace("like_note-", "unknown-"), route_unknown_note)
        await page.route(
            "https://eh96lnrmau.user-space.cdn.idcfcloud.net/thumbnail/episode/*",
            route_author_asset,
        )
    original_goto = page.goto

    async def goto_final_viewer_for_public_episode(url, *args, **kwargs):
        if url == SOURCE_URL:
            if access_mode == "wait_free":
                return await original_goto(url, *args, **kwargs)
            requested.append(url)
            destination = wrong_viewer_url if wrong_route else VIEWER_NAVIGATION_URL
            result = await original_goto(destination, *args, **kwargs)
            if source_goto_failure == "timeout_after_navigation":
                raise PlaywrightTimeoutError("synthetic source navigation timeout")
            if source_goto_failure == "cancel_after_navigation":
                raise asyncio.CancelledError
            return result
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


def _seed_batch_candidate(
    tmp_path, *, access_mode="free", output_mode="capture"
):
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
            access_mode=access_mode,
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
    planner = synchronized_legacy_planner(catalog, policies)
    plan = planner.plan(
        site="yanmaga",
        now=NOW,
        quota_resource="work_ticket" if access_mode == "quota" else None,
        output_mode=output_mode,
    )
    assert len(plan.candidates) == 1
    return catalog, policies, adapters, plan.candidates[0], item, source, target, planner.watchlist


def _install_rental_history_proof(monkeypatch):
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def fake_fetch(
        _page,
        *,
        observed_mypage_href,
        targets,
        max_countdown_hours=23,
    ):
        calls.append((observed_mypage_href, tuple(targets)))
        assert observed_mypage_href == "https://yanmaga.jp/mypage"
        assert len(targets) == 1
        assert targets[0].episode_id == EPISODE_ID
        assert max_countdown_hours in {23, 72}
        return (
            (
                f"{SLUG}:{EPISODE_ID}",
                RentalCountdown(
                    observed_at=GRANT_OBSERVED_AT,
                    remaining_hours=22,
                    access_granted_until=GRANT_UNTIL,
                    expiry_evidence="site_countdown_lower_bound",
                ),
            ),
        )

    monkeypatch.setattr(adapter_module, "fetch_rental_history_countdowns", fake_fetch)
    return calls


async def _adapter_at_work(
    page,
    monkeypatch,
    *,
    access_mode="free",
    access_strategy="direct",
    **route_options,
):
    requested = await _set_routes(
        page,
        monkeypatch,
        access_mode=access_mode,
        **route_options,
    )
    adapter = YanmagaAdapter()
    await adapter.configure_run(page, access_strategy)
    await adapter.configure_target_identity(f"{SLUG}:{EPISODE_ID}", WORK_KEY)
    if access_strategy == "quota":
        await adapter.configure_quota_resource(page, "work_ticket")
    if access_mode in {'trusted_grant', 'trusted_wait'}:
        adapter.configure_existing_access_grant(GRANT_UNTIL)
    await adapter.prepare_page(page)
    entry = adapter.resolve_initial_navigation_url(SOURCE_URL)
    adapter.set_confirmed_access_grant_observer(lambda _grant: None)
    await page.goto(entry, wait_until="domcontentloaded")
    return requested, adapter


def _install_wait_history_observations(
    monkeypatch,
    *,
    initial: str = "absent",
    remaining_hours: int = 22,
    remaining_days: int | None = None,
):
    calls: list[tuple[str, tuple[object, ...]]] = []
    external_id = f"{SLUG}:{EPISODE_ID}"

    def active_observation() -> RentalHistoryObservation:
        observed_at = datetime.now(UTC)
        if remaining_days is not None:
            expiry = (
                observed_at + timedelta(days=remaining_days) - timedelta(hours=1, seconds=5)
            )
            evidence = "site_day_countdown_estimate"
        else:
            expiry = (
                observed_at + timedelta(hours=remaining_hours - 1) - timedelta(seconds=5)
                if remaining_hours > 1
                else None
            )
            evidence = "site_countdown_lower_bound" if expiry is not None else None
        return RentalHistoryObservation(
            external_id,
            RentalCountdown(
                observed_at=observed_at,
                remaining_hours=remaining_hours if remaining_days is None else 0,
                access_granted_until=expiry,
                expiry_evidence=evidence,
                remaining_days=remaining_days,
            ),
        )

    async def fetch(
        _page,
        *,
        observed_mypage_href,
        targets,
        max_countdown_hours=23,
    ):
        calls.append((observed_mypage_href, tuple(targets)))
        assert observed_mypage_href == "https://yanmaga.jp/mypage"
        assert len(targets) == 1
        assert targets[0].episode_id == EPISODE_ID
        assert max_countdown_hours == 72
        if len(calls) == 1:
            if initial == "unknown":
                return None
            if initial == "active":
                return (active_observation(),)
            return (RentalHistoryObservation(external_id, None),)
        return (active_observation(),)

    monkeypatch.setattr(adapter_module, "fetch_rental_history_observations", fetch)
    return calls


async def test_yanmaga_wait_ticket_confirms_once_from_notice_and_fresh_history(
    browser_page, monkeypatch
) -> None:
    requested, adapter = await _adapter_at_work(
        browser_page,
        monkeypatch,
        access_mode="wait_free",
        access_strategy="quota",
        quota_completion_notice=True,
        wait_modal_delay_ms=100,
    )
    requests = []
    browser_page.on("request", lambda request: requests.append((request.method, request.url)))
    history_calls = _install_wait_history_observations(monkeypatch)
    await adapter.prepare_page(browser_page)

    await adapter.initialize(browser_page)

    consumption = adapter.get_access_consumption()
    assert consumption.consumed is True
    assert consumption.resource == "work_ticket"
    assert consumption.consumed_at is not None
    assert consumption.access_granted_until is not None
    assert adapter.quota_release_state == "site_confirmed"
    assert adapter._first_free_grant is None
    assert len(history_calls) == 2
    assert sum(urlsplit(url).path == urlsplit(SOURCE_URL).path for url in requested) == 1
    assert sum(
        method == "POST"
        and urlsplit(url).path == f"/rental/episodes/{EPISODE_ID}/by_free_waits"
        for method, url in requests
    ) == 1
    assert browser_page.url == VIEWER_NAVIGATION_URL


@pytest.mark.parametrize(
    ("initial_history", "charged_ui", "expected_error"),
    [
        ("unknown", True, UnknownPageStateError),
        ("active", True, AccessResourceUnavailableError),
        ("absent", False, UnknownPageStateError),
    ],
    ids=("unknown-history", "untrusted-active-history", "missing-charged-state"),
)
async def test_yanmaga_wait_ticket_unknown_or_inconsistent_preflight_never_enters(
    browser_page, monkeypatch, initial_history, charged_ui, expected_error
) -> None:
    requested, adapter = await _adapter_at_work(
        browser_page,
        monkeypatch,
        access_mode="wait_free",
        access_strategy="quota",
        charged_ui=charged_ui,
    )
    history_calls = _install_wait_history_observations(
        monkeypatch, initial=initial_history
    )

    with pytest.raises(expected_error):
        await adapter.initialize_entry_only(browser_page)

    assert adapter.get_access_consumption().consumed is False
    assert adapter.quota_release_state == "not_attempted"
    assert sum(urlsplit(url).path == urlsplit(SOURCE_URL).path for url in requested) == int(initial_history == "absent")
    assert len(history_calls) == 1


async def test_yanmaga_wait_rental_form_for_another_episode_is_not_submitted(
    browser_page, monkeypatch
) -> None:
    requested, adapter = await _adapter_at_work(
        browser_page,
        monkeypatch,
        access_mode="wait_free",
        access_strategy="quota",
        wait_form_episode_id=NEXT_EPISODE_ID,
    )
    _install_wait_history_observations(monkeypatch)

    await adapter.prepare_entry_only_page(browser_page)
    with pytest.raises(UnknownPageStateError):
        await adapter.initialize_entry_only(browser_page)

    assert adapter.quota_release_state == "not_attempted"
    assert adapter.get_access_consumption().consumed is False
    assert not any(
        urlsplit(url).path.startswith("/rental/episodes/")
        and urlsplit(url).path.endswith("/by_free_waits")
        for url in requested
    )
    assert sum(urlsplit(url).path == urlsplit(SOURCE_URL).path for url in requested) == 1


@pytest.mark.parametrize(
    "button_attributes",
    [
        'formaction="/rental/episodes/other/by_free_waits"',
        'formmethod="get"',
        'formtarget="_blank"',
        'formenctype="text/plain"',
        "formnovalidate",
        'form="other-form"',
    ],
    ids=("formaction", "formmethod", "formtarget", "formenctype", "formnovalidate", "form-owner"),
)
async def test_yanmaga_wait_rental_submitter_overrides_are_rejected(
    browser_page, monkeypatch, button_attributes
) -> None:
    requested, adapter = await _adapter_at_work(
        browser_page,
        monkeypatch,
        access_mode="wait_free",
        access_strategy="quota",
        wait_button_attributes=button_attributes,
    )
    _install_wait_history_observations(monkeypatch)

    await adapter.prepare_entry_only_page(browser_page)
    with pytest.raises(UnknownPageStateError):
        await adapter.initialize_entry_only(browser_page)

    assert adapter.quota_release_state == "not_attempted"
    assert adapter.get_access_consumption().consumed is False
    assert not any("/by_free_waits" in url for url in requested)
    assert sum(urlsplit(url).path == urlsplit(SOURCE_URL).path for url in requested) == 1


async def test_yanmaga_wait_ticket_entry_only_confirms_without_pixel_initialization(
    browser_page, monkeypatch
) -> None:
    requested, adapter = await _adapter_at_work(
        browser_page,
        monkeypatch,
        access_mode="wait_free",
        access_strategy="quota",
        quota_completion_notice=True,
    )
    history_calls = _install_wait_history_observations(monkeypatch)
    await adapter.prepare_entry_only_page(browser_page)

    await adapter.initialize_entry_only(browser_page)

    assert adapter.get_access_consumption().consumed is True
    assert adapter._total_pages is None
    assert len(history_calls) == 2
    assert sum(urlsplit(url).path == urlsplit(SOURCE_URL).path for url in requested) == 1


async def test_yanmaga_wait_ticket_batch_grant_only_persists_use_without_capture(
    browser_page, tmp_path, monkeypatch
) -> None:
    requested = await _set_routes(
        browser_page,
        monkeypatch,
        access_mode="wait_free",
        quota_completion_notice=True,
    )
    history_calls = _install_wait_history_observations(monkeypatch)
    catalog, policies, adapters, candidate, item, source, _target, watchlist = (
        _seed_batch_candidate(
            tmp_path, access_mode="quota", output_mode="grant_only"
        )
    )
    assert candidate.access_strategy == "quota"
    assert candidate.quota_resource == "work_ticket"
    executor = BatchExecutor(
        catalog,
        policies,
        adapters,
        watchlist=watchlist,
        library_dir=tmp_path / "library",
    )

    result = await executor.execute_grant_only_candidate(
        browser_page,
        candidate,
        output_root=tmp_path / "batch-output",
        max_pages=8,
        now=NOW,
    )

    assert result.resource_consumed is True
    assert result.resource == "work_ticket"
    assert catalog.get_item(item.id).status == "pending"
    assert catalog.list_artifacts(item_id=item.id) == []
    saved_source = catalog.get_source(source.id)
    assert saved_source.quota_started_at is not None
    assert saved_source.access_granted_until is not None
    assert datetime.fromisoformat(saved_source.access_granted_until) == (
        datetime.fromisoformat(saved_source.quota_started_at)
        + timedelta(hours=21)
        - timedelta(seconds=5)
    )
    state = catalog.get_quota_resource_state(
        item.work_id, site="yanmaga", resource="work_ticket"
    )
    assert state is not None and state.last_consumed_at is not None
    assert len(history_calls) == 2
    assert sum(urlsplit(url).path == urlsplit(SOURCE_URL).path for url in requested) == 1
    run_dirs = list((tmp_path / "batch-output" / "yanmaga").iterdir())
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    assert (run_dir / "diagnostics" / "entry_trace.json").is_file()
    assert not (run_dir / "manifest.json").exists()
    assert not (run_dir / "progress.json").exists()
    assert not list(run_dir.glob("page-*.*"))
    assert not list((tmp_path / "library").rglob("*.zip"))


@pytest.mark.parametrize("remaining_days", [1, 2])
async def test_yanmaga_wait_ticket_day_grant_survives_capture_failure(
    browser_page, tmp_path, monkeypatch, remaining_days
) -> None:
    requested = await _set_routes(
        browser_page,
        monkeypatch,
        access_mode="wait_free",
        quota_completion_notice=True,
        thin_segment=True,
    )
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 350)
    history_calls = _install_wait_history_observations(
        monkeypatch, remaining_days=remaining_days
    )
    catalog, policies, adapters, candidate, item, source, _target, watchlist = (
        _seed_batch_candidate(tmp_path, access_mode="quota")
    )
    executor = BatchExecutor(catalog, policies, adapters, watchlist=watchlist)

    with pytest.raises(CandidateExecutionError) as raised:
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "batch-output",
            library_dir=tmp_path / "library",
            max_pages=8,
            now=NOW,
        )

    assert raised.value.resource_consumed is True
    assert catalog.get_item(item.id).status == "pending"
    assert catalog.list_artifacts(item_id=item.id) == []
    saved_source = catalog.get_source(source.id)
    assert saved_source.quota_started_at is not None
    assert saved_source.access_granted_until is not None
    expiry = datetime.fromisoformat(saved_source.access_granted_until).astimezone(UTC)
    assert expiry == (
        datetime.fromisoformat(saved_source.quota_started_at).astimezone(UTC)
        + timedelta(days=remaining_days) - timedelta(hours=1, seconds=5)
    )
    state = catalog.get_quota_resource_state(
        item.work_id, site="yanmaga", resource="work_ticket"
    )
    assert state is not None and state.last_consumed_at is not None
    assert len(history_calls) == 2
    assert sum(urlsplit(url).path == urlsplit(SOURCE_URL).path for url in requested) == 1
    assert sum(
        urlsplit(url).path == f"/rental/episodes/{EPISODE_ID}/by_free_waits"
        for url in requested
    ) == 1
    assert not list((tmp_path / "batch-output").rglob("page-*.*"))
    assert not list((tmp_path / "library").rglob("*.zip"))


async def test_yanmaga_wait_ticket_h1_latches_consumption_without_inventing_expiry(
    browser_page, tmp_path, monkeypatch
) -> None:
    requested = await _set_routes(
        browser_page,
        monkeypatch,
        access_mode="wait_free",
        quota_completion_notice=True,
    )
    history_calls = _install_wait_history_observations(
        monkeypatch, remaining_hours=1
    )
    catalog, policies, adapters, candidate, item, source, _target, watchlist = (
        _seed_batch_candidate(
            tmp_path, access_mode="quota", output_mode="grant_only"
        )
    )
    executor = BatchExecutor(catalog, policies, adapters, watchlist=watchlist)

    with pytest.raises(CandidateExecutionError) as raised:
        await executor.execute_grant_only_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "batch-output",
            max_pages=8,
            now=NOW,
        )

    assert raised.value.resource_consumed is True
    assert catalog.get_item(item.id).status == "pending"
    assert catalog.list_artifacts(item_id=item.id) == []
    saved_source = catalog.get_source(source.id)
    assert saved_source.quota_started_at is not None
    assert saved_source.access_granted_until is None
    state = catalog.get_quota_resource_state(
        item.work_id, site="yanmaga", resource="work_ticket"
    )
    assert state is not None and state.last_consumed_at is not None
    assert len(history_calls) == 2
    assert sum(urlsplit(url).path == urlsplit(SOURCE_URL).path for url in requested) == 1
    assert not list((tmp_path / "batch-output").rglob("page-*.*"))
    assert not list((tmp_path / "library").rglob("*.zip"))


@pytest.mark.parametrize(
    "first_free_completion_notice", (False, True), ids=("missing", "wrong-first-free-text")
)
async def test_yanmaga_wait_ticket_requires_generic_completion_proof_and_never_retries(
    browser_page, monkeypatch, first_free_completion_notice
) -> None:
    requested, adapter = await _adapter_at_work(
        browser_page,
        monkeypatch,
        access_mode="wait_free",
        access_strategy="quota",
        first_free_completion_notice=first_free_completion_notice,
    )
    history_calls = _install_wait_history_observations(monkeypatch)

    with pytest.raises(AccessResourceUnavailableError):
        await adapter.initialize_entry_only(browser_page)

    assert adapter.quota_release_state == "attempted_unknown"
    assert adapter.get_access_consumption().consumed is False
    assert len(history_calls) == 1
    assert sum(urlsplit(url).path == urlsplit(SOURCE_URL).path for url in requested) == 1


async def test_yanmaga_first_free_proof_does_not_accept_wait_ticket_notice(
    browser_page, monkeypatch
) -> None:
    _requested, adapter = await _adapter_at_work(
        browser_page,
        monkeypatch,
        access_mode="first_free",
        quota_completion_notice=True,
    )
    await browser_page.goto(VIEWER_NAVIGATION_URL, wait_until="domcontentloaded")

    assert not await adapter._has_first_free_access_proof(
        browser_page, YanmagaEpisodeParts(SLUG, EPISODE_ID)
    )


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


async def test_yanmaga_inline_rental_card_does_not_block_final_body_or_end(
    browser_page, tmp_path, monkeypatch
) -> None:
    requested = await _set_routes(browser_page, monkeypatch, inline_rental_card=True)
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 500)

    result = await CrawlerRunner(_config(tmp_path)).run(browser_page, YanmagaAdapter())

    assert result.stop_state is PageState.END
    assert len(result.pages) == 4
    assert await browser_page.locator("#rental .episode-modal-expire").is_visible()
    assert (tmp_path / "isolated-output" / "page-0004.png").is_file()
    assert not any(NEXT_EPISODE_ID in urlsplit(url).path for url in requested)


@pytest.mark.parametrize("native_wrapper_transform", [None, "translateX(24px)"])
@pytest.mark.parametrize("regenerate_last_page", [False, True])
@pytest.mark.parametrize("native_page_width", [1125, 1127])
async def test_yanmaga_captures_exact_pre_jpeg_page_pixels_as_lossless_webp(
    browser_page, tmp_path, monkeypatch, native_wrapper_transform, regenerate_last_page,
    native_page_width
) -> None:
    await _set_routes(
        browser_page,
        monkeypatch,
        native_capture=True,
        native_page_width=native_page_width,
        native_wrapper_transform=native_wrapper_transform,
    )
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 500)
    adapter = YanmagaAdapter()
    capture = adapter.capture_page
    regenerated = False

    async def capture_after_regeneration(page):
        nonlocal regenerated
        if regenerate_last_page and not regenerated:
            await page.wait_for_function("window.__yanmagaNativeCaptureV1.inFlight===0")
            counts = await page.evaluate(
                """async () => {
                  const state=window.__yanmagaNativeCaptureV1;
                  const originals=[...document.querySelectorAll('#content-p4 img')]
                    .map(image=>image.currentSrc);
                  for(let round=0;round<2;round++) {
                    for(const image of document.querySelectorAll('#content-p4 img')) {
                      const record=state.byUrl.get(image.currentSrc);
                      const canvas=document.createElement('canvas');
                      canvas.width=record.width;canvas.height=record.height;
                      const context=canvas.getContext('2d');
                      const pixels=context.createImageData(record.width,record.height);
                      pixels.data.set(record.pixels);context.putImageData(pixels,0,0);
                      const data=canvas.toDataURL('image/jpeg',0.9);
                      const bytes=Uint8Array.from(atob(data.split(',')[1]),c=>c.charCodeAt(0));
                      image.src=URL.createObjectURL(new Blob([bytes],{type:'image/jpeg'}));
                    }
                    while(state.inFlight) await new Promise(resolve=>setTimeout(resolve,0));
                  }
                  return {regenerated:state.stats.regeneratedBlobBindings,
                    originalsPreserved:originals.every(url=>state.byUrl.has(url))};
                }"""
            )
            assert counts == {"regenerated": 6, "originalsPreserved": True}
            regenerated = True
        return await capture(page)

    monkeypatch.setattr(adapter, "capture_page", capture_after_regeneration)
    result = await CrawlerRunner(_config(tmp_path)).run(browser_page, adapter)

    assert result.stop_state is PageState.END
    assert len(result.pages) == 4
    assert all(
        (capture.mime_type, capture.file_extension, capture.width, capture.height)
        == ("image/webp", ".webp", native_page_width, 1600)
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
        assert rgba.getpixel((native_page_width - 1, 1599)) == (105, 112, 94, 255)
    with Image.open(tmp_path / "isolated-output" / "page-0004.webp") as image:
        assert image.convert("RGBA").getpixel((10, 100)) == (164, 111, 137, 255)
    assert await browser_page.evaluate(
        """() => !window.__yanmagaNativeCaptureV1 &&
          HTMLCanvasElement.prototype.toDataURL===window.__yanmagaTestOriginals.canvas &&
          Blob===window.__yanmagaTestOriginals.blob &&
          URL.createObjectURL===window.__yanmagaTestOriginals.url"""
    )


@pytest.mark.parametrize("scenario", ["different_pixels", "released_history", "two_pending"])
async def test_yanmaga_regenerated_segment_requires_complete_exact_pixel_history(
    browser_page, monkeypatch, scenario
) -> None:
    await _set_routes(browser_page, monkeypatch, native_capture=True)
    await install_yanmaga_native_observer(browser_page)
    await browser_page.goto(VIEWER_NAVIGATION_URL, wait_until="domcontentloaded")
    await browser_page.wait_for_function("window.__yanmagaNativeCaptureV1.inFlight===0")
    await browser_page.evaluate(
        """async () => {
          const canvas=document.createElement('canvas');canvas.width=1127;canvas.height=536;
          const context=canvas.getContext('2d');context.fillStyle='rgb(90,120,160)';
          context.fillRect(0,0,1127,536);
          const data=canvas.toDataURL('image/jpeg',0.9);
          const bytes=Uint8Array.from(atob(data.split(',')[1]),c=>c.charCodeAt(0));
          const url=URL.createObjectURL(new Blob([bytes],{type:'image/jpeg'}));
          const wrapper=document.createElement('div');wrapper.id='history-probe';
          const image=document.createElement('img');image.src=url;
          wrapper.append(image);document.body.append(wrapper);
          window.__historyProbe={canvas,data,url};
          while(window.__yanmagaNativeCaptureV1.inFlight)
            await new Promise(resolve=>setTimeout(resolve,0));
          if(!window.__yanmagaNativeCaptureV1.byUrl.has(url)) throw Error('missing control binding');
        }"""
    )
    if scenario == "released_history":
        await release_yanmaga_native_page(browser_page, "history-probe")
    observations = await browser_page.evaluate(
        """async scenario => {
          const state=window.__yanmagaNativeCaptureV1,{canvas,data,url}=window.__historyProbe;
          const previous=state.byUrl.get(url),before=state.storedPixelBytes;
          if(scenario==='different_pixels') {
            const context=canvas.getContext('2d'),pixel=context.getImageData(0,0,1,1);
            pixel.data[0]++;context.putImageData(pixel,0,0);
          }
          const next=canvas.toDataURL('image/jpeg',0.9);
          if(scenario==='two_pending') canvas.toDataURL('image/jpeg',0.9);
          const bytes=Uint8Array.from(atob(next.split(',')[1]),c=>c.charCodeAt(0));
          const nextUrl=URL.createObjectURL(new Blob([bytes],{type:'image/jpeg'}));
          while(state.inFlight) await new Promise(resolve=>setTimeout(resolve,0));
          let rejectedHistoryPreserved=true;
          if(scenario==='different_pixels') {
            const context=canvas.getContext('2d'),pixel=context.getImageData(0,0,1,1);
            pixel.data[0]--;context.putImageData(pixel,0,0);
            const again=canvas.toDataURL('image/jpeg',0.9);
            const bytes=Uint8Array.from(atob(again.split(',')[1]),c=>c.charCodeAt(0));
            const againUrl=URL.createObjectURL(new Blob([bytes],{type:'image/jpeg'}));
            while(state.inFlight) await new Promise(resolve=>setTimeout(resolve,0));
            rejectedHistoryPreserved=again===data && !state.byUrl.has(againUrl);
          }
          return {jpegEqual:data===next,firstBound:state.byUrl.get(url)===previous && !!previous,
            secondBound:state.byUrl.has(nextUrl),retainedBytes:state.storedPixelBytes-before,
            rejectedHistoryPreserved,regenerated:state.stats.regeneratedBlobBindings,
            overflow:state.overflow};
        }""",
        scenario,
    )
    assert observations == {
        "jpegEqual": True,
        "firstBound": scenario != "released_history",
        "secondBound": False,
        "retainedBytes": 0,
        "rejectedHistoryPreserved": True,
        "regenerated": 0,
        "overflow": False,
    }
    await dispose_yanmaga_native_observer(browser_page)


async def test_yanmaga_native_observer_is_top_frame_viewer_route_only(
    browser_page, monkeypatch
) -> None:
    await _set_routes(browser_page, monkeypatch, native_capture=True)
    await install_yanmaga_native_observer(browser_page)

    async def work_document(route):
        await route.fulfill(status=200, content_type="text/html", body="<body>work</body>")

    # This test deliberately inspects the observer outside its viewer route.
    await browser_page.route(WORK_URL, work_document)
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


@pytest.mark.parametrize("decoded_segments", [False, True])
async def test_yanmaga_native_group_revalidation_rejects_prior_page_style_drift(
    browser_page, tmp_path, monkeypatch, decoded_segments
) -> None:
    await _set_routes(browser_page, monkeypatch, native_capture=True)
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 500)
    capture_name = (
        "capture_yanmaga_decoded_segment_webp" if decoded_segments else "capture_yanmaga_native_webp"
    )
    capture = getattr(adapter_module, capture_name)
    if decoded_segments:
        native_capture = adapter_module.capture_yanmaga_native_webp

        async def capture_with_unbound_spread(page, page_id):
            if page_id == "content-p2":
                await page.evaluate(
                    """() => window.__yanmagaNativeCaptureV1.byUrl.delete(
                      document.querySelector('#content-p2 img').currentSrc)"""
                )
            return await native_capture(page, page_id)

        monkeypatch.setattr(adapter_module, "capture_yanmaga_native_webp", capture_with_unbound_spread)
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
        adapter_module, capture_name, capture_then_change_prior_spread_page
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
            {"native_page_width": 1126},
            ("unsupported_native_geometry", "unsupported_native_geometry"),
            ("image/png", "image/png", "image/png", "image/png"),
        ),
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
            ("image/webp", "image/webp", "image/webp", "image/webp"),
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
    decoded = options.get("native_ambiguous", False)
    assert result.pages[0].metadata["capture_method"] == (
        "decoded_viewer_segment_lossless_webp" if decoded else "rendered_dom_body_wrapper_png"
    )
    assert result.pages[0].metadata["source_native_pixels_used"] is decoded
    assert result.pages[0].metadata["pre_jpeg_pixels_used"] is False
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
        ("wait_countdown", True),
        ("wait_countdown_wrong_title", False),
        ("wait_countdown_bad_time", False),
        ("wait_countdown_missing_marker", False),
        ("wait_countdown_semantic_dialog", False),
        ("point_rental", True),
        ("point_rental_wrong_title", False),
        ("point_rental_wrong_label", False),
        ("point_rental_foreign_action", False),
        ("point_rental_wrong_action", False),
        ("point_rental_wrong_method", False),
        ("point_rental_wrong_type", False),
        ("point_rental_duplicate_code", False),
        ("point_rental_wrong_thumbnail", False),
        ("point_rental_bad_code", False),
        ("point_rental_zero_cost", False),
        ("point_rental_duplicate", False),
        ("point_rental_hidden", False),
        ("point_rental_and_next", False),
        ("point_rental_semantic_dialog", False),
        ("ready_wait", True),
        ("ready_wait_missing_marker", False),
        ("ready_wait_wrong_title", False),
        ("ready_wait_wrong_label", False),
        ("ready_wait_wrong_type", False),
        ("ready_wait_foreign_action", False),
        ("ready_wait_wrong_thumbnail", False),
        ("ready_wait_duplicate", False),
        ("engagement", True),
        ("engagement_author", True),
        ("engagement_author_plain_url", True),
        ("engagement_author_bad_query", False),
        ("engagement_author_duplicate_query", False),
        ("engagement_author_foreign", False),
        ("engagement_author_wrong_label", False),
        ("engagement_author_wrong_asset", False),
        ("engagement_author_duplicate", False),
        ("engagement_author_hidden", False),
        ("engagement_author_wrong_position", False),
        ("engagement_author_wrong_code", False),
        ("engagement_offscreen", False),
        ("engagement_obstructed", False),
        ("engagement_wrong_code", False),
        ("engagement_duplicate_code", False),
        ("engagement_visible_code", False),
        ("engagement_wrong_action", False),
        ("engagement_foreign_action", False),
        ("engagement_wrong_method", False),
        ("engagement_wrong_label", False),
        ("engagement_missing_like", False),
        ("engagement_duplicate_like", False),
        ("engagement_wrong_note", False),
        ("engagement_hidden", False),
        ("engagement_wrong_share", False),
        ("engagement_with_next", False),
        ("engagement_semantic_dialog", False),
        ("missing", False),
    ],
)
async def test_yanmaga_terminal_signup_boundary_is_exact_and_never_activated(
    browser_page, tmp_path, monkeypatch, terminal_control, accepted
) -> None:
    wait_countdown = terminal_control.startswith("wait_countdown")
    point_rental = terminal_control.startswith("point_rental")
    engagement = terminal_control.startswith("engagement")
    ready_wait = terminal_control.startswith("ready_wait")
    requested = await _set_routes(
        browser_page,
        monkeypatch,
        terminal_control=terminal_control,
        inline_rental_card=wait_countdown or point_rental or engagement or ready_wait,
        terminal_geometry=(
            "offscreen" if terminal_control == "engagement_offscreen" else
            "obstructed" if terminal_control == "engagement_obstructed" else "valid"
        ),
        inline_rental_dialog=terminal_control in {
            "wait_countdown_semantic_dialog", "point_rental_semantic_dialog"
        },
        authenticated_listing=True if wait_countdown or point_rental or ready_wait else None,
    )
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 300)

    if accepted:
        result = await CrawlerRunner(_config(tmp_path)).run(browser_page, YanmagaAdapter())
        assert result.stop_state is PageState.END
        assert len(result.pages) == 4
    else:
        expected_error = (
            PageChangeTimeoutError
            if terminal_control in {
                "wait_countdown_semantic_dialog", "point_rental_semantic_dialog",
                "engagement_semantic_dialog",
            }
            else UnknownPageStateError
        )
        with pytest.raises(expected_error):
            await CrawlerRunner(_config(tmp_path)).run(browser_page, YanmagaAdapter())
    assert browser_page.url == VIEWER_NAVIGATION_URL
    assert not any(urlsplit(url).path == "/customers/sign-up" for url in requested)
    assert not any(urlsplit(url).path == "/viewer/rental" for url in requested)
    if terminal_control == "wait_countdown":
        assert await browser_page.locator(".episode-modal-wait.content").is_visible()
        assert await browser_page.locator("#js-btn-valid-next-episode").count() == 0
    if engagement:
        assert not any(urlsplit(url).path in {"/viewer/favorite", "/viewer/like"}
                       or urlsplit(url).hostname == "twitter.com" for url in requested)


@pytest.mark.parametrize(
    ("control", "menu_visible", "hideable", "accepted"),
    [("valid_next", True, True, True), ("valid_next", False, True, True),
     ("ready_wait", True, True, True), ("ready_wait_wrong_title", True, True, False),
     ("ready_wait_wrong_type", True, True, False), ("missing", True, True, False),
     ("valid_next", True, False, False)],
)
async def test_yanmaga_single_page_hides_native_menu_then_requires_terminal_proof(
    browser_page, tmp_path, monkeypatch, control, menu_visible, hideable, accepted
) -> None:
    ready_wait = control.startswith("ready_wait")
    requested = await _set_routes(
        browser_page, monkeypatch, single_page=True, first_page_overlay=menu_visible,
        menu_hideable=hideable, terminal_control=control,
        authenticated_listing=True if ready_wait else None,
    )
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 500)
    keys = []
    press = browser_page.keyboard.press

    async def record_key(key, **kwargs):
        keys.append(key)
        await press(key, **kwargs)

    monkeypatch.setattr(browser_page.keyboard, "press", record_key)
    config = _config(tmp_path)
    config.max_pages = 1
    adapter = YanmagaAdapter()
    if accepted:
        result = await CrawlerRunner(config).run(browser_page, adapter)
        assert result.stop_state is PageState.END and len(result.pages) == 1
        debug = await adapter.collect_debug_metadata(browser_page)
        assert debug["native_counter"] == "-/1" and debug["terminal_only"]
        assert adapter._captured_indices == [1]
        with pytest.raises(UnknownPageStateError, match="terminal-only.*identity"):
            await adapter.get_content_identity(browser_page)
    else:
        with pytest.raises((UnknownPageStateError, PageChangeTimeoutError)):
            await CrawlerRunner(config).run(browser_page, adapter)
    assert keys.count("d") == int(menu_visible)
    assert keys.count("ArrowLeft") == int(hideable)
    assert not any(urlsplit(url).path == "/viewer/rental" for url in requested)
    assert not any(NEXT_EPISODE_ID in urlsplit(url).path for url in requested)
    assert len(list(config.output_dir.glob("page-*.png"))) == int(hideable)


@pytest.mark.parametrize(
    ("terminal_control", "terminal_geometry", "access_gate", "accepted"),
    [
        ("latest_author", "valid", False, True),
        ("latest_author_nonlatest", "valid", False, False),
        ("latest_author_missing", "valid", False, False),
        ("latest_author", "valid", True, False),
        ("latest_author", "obstructed", False, False),
    ],
)
async def test_yanmaga_latest_listed_author_card_is_a_bounded_end_signal(
    browser_page,
    tmp_path,
    monkeypatch,
    terminal_control,
    terminal_geometry,
    access_gate,
    accepted,
) -> None:
    await _set_routes(
        browser_page,
        monkeypatch,
        terminal_control=terminal_control,
        terminal_geometry=terminal_geometry,
        access_gate=access_gate,
    )
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 300)

    if accepted:
        result = await CrawlerRunner(_config(tmp_path)).run(browser_page, YanmagaAdapter())
        assert result.stop_state is PageState.END
        assert len(result.pages) == 4
    else:
        expected_error = PageChangeTimeoutError if access_gate else UnknownPageStateError
        with pytest.raises(expected_error):
            await CrawlerRunner(_config(tmp_path)).run(browser_page, YanmagaAdapter())
    assert browser_page.url == VIEWER_NAVIGATION_URL
    author_count = await browser_page.locator("a.author-info").count()
    assert author_count == (0 if terminal_control.endswith("_missing") else 1)
    if author_count:
        assert await browser_page.locator("a.author-info").get_attribute("target") == "_blank"


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


@pytest.mark.parametrize(
    "reason", ["pixel_collision", "missing_binding", "non_jpeg_blob", "buffer_overflow"]
)
@pytest.mark.parametrize("native_page_width", [1125, 1127])
async def test_yanmaga_decoded_segments_match_current_dom_pixels_for_the_whole_group(
    browser_page, tmp_path, monkeypatch, reason, native_page_width
) -> None:
    await _set_routes(
        browser_page, monkeypatch, native_capture=True, native_page_width=native_page_width
    )
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 500)
    adapter = YanmagaAdapter()
    capture = adapter.capture_page
    references = {}
    affected = (
        [4] if reason == "pixel_collision"
        else [2, 3, 4] if reason == "buffer_overflow"
        else [2, 3]
    )
    overflow_copies = None

    async def capture_with_missing_pre_jpeg_proof(page):
        nonlocal overflow_copies
        if len(adapter._captured_indices) == affected[0] - 1:
            if reason == "pixel_collision":
                assert await page.evaluate(
                    """async () => {
                      const state=window.__yanmagaNativeCaptureV1;
                      const image=document.querySelector('#content-p4 img');
                      const previous=state.byUrl.get(image.currentSrc);
                      const canvas=document.createElement('canvas');
                      canvas.width=previous.width;canvas.height=previous.height;
                      const context=canvas.getContext('2d');
                      const data=context.createImageData(canvas.width,canvas.height);
                      data.data.set(previous.pixels);data.data[0]++;
                      context.putImageData(data,0,0);
                      const encoded=canvas.toDataURL('image/jpeg',0.9);
                      const same=encoded.split(',')[1]===previous.payload;
                      const bytes=Uint8Array.from(atob(encoded.split(',')[1]),c=>c.charCodeAt(0));
                      image.src=URL.createObjectURL(new Blob([bytes],{type:'image/jpeg'}));
                      while(state.inFlight) await new Promise(resolve=>setTimeout(resolve,0));
                      await image.decode();
                      return same && !state.byUrl.has(image.currentSrc);
                    }"""
                )
            elif reason == "buffer_overflow":
                overflow_copies = await page.evaluate(
                    """limit => {
                      const state=window.__yanmagaNativeCaptureV1;
                      state.storedEncodedBytes=limit-1;
                      const canvas=document.createElement('canvas');
                      canvas.width=1127;canvas.height=536;
                      canvas.getContext('2d').fillRect(0,0,1127,536);
                      canvas.toDataURL('image/jpeg',0.9);
                      return state.stats.canvasCopies;
                    }""",
                    MAX_CAPTURE_ENCODED_BYTES,
                )
            elif reason == "non_jpeg_blob":
                await page.evaluate(
                    """async () => {
                      const image=document.querySelector('#content-p3 img');
                      const canvas=document.createElement('canvas');
                      canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;
                      canvas.getContext('2d').drawImage(image,0,0);
                      image.src=URL.createObjectURL(await new Promise(resolve=>canvas.toBlob(resolve)));
                      await image.decode();
                    }"""
                )
            else:
                await page.evaluate(
                    """() => window.__yanmagaNativeCaptureV1.byUrl.delete(
                      document.querySelector('#content-p3 img').currentSrc)"""
                )
            for index in affected:
                references[index] = await page.evaluate(
                    """([index,width]) => {
                      const canvas=document.createElement('canvas');canvas.width=width;canvas.height=1600;
                      const context=canvas.getContext('2d',{alpha:false,colorSpace:'srgb'});
                      [...document.querySelectorAll('#content-p'+index+' img')].forEach((image,n)=>
                        context.drawImage(image,0,[0,532,1064][n]));
                      return canvas.toDataURL('image/png').split(',')[1];
                    }""",
                    [index, native_page_width],
                )
        result = await capture(page)
        if overflow_copies is not None:
            assert await page.evaluate(
                """() => {
                  const state=window.__yanmagaNativeCaptureV1;
                  return [state.overflowReason,state.storedEncodedBytes,state.stats.canvasCopies];
                }"""
            ) == ["capture_buffer_overflow", MAX_CAPTURE_ENCODED_BYTES - 1, overflow_copies]
        return result

    monkeypatch.setattr(adapter, "capture_page", capture_with_missing_pre_jpeg_proof)
    result = await CrawlerRunner(_config(tmp_path)).run(browser_page, adapter)
    assert result.stop_state is PageState.END
    assert len(result.pages) == 4
    assert sorted(references) == affected
    if reason == "non_jpeg_blob":
        assert [p.mime_type for p in result.pages] == [
            "image/webp", "image/png", "image/png", "image/webp"
        ]
        assert result.pages[1].metadata["capture_group"]["decoded_failure_reason"] == (
            "decoded_segment_not_bounded_jpeg"
        )
        return
    assert all(p.mime_type == "image/webp" for p in result.pages)
    for index in affected:
        captured = result.pages[index - 1]
        assert captured.metadata["capture_method"] == "decoded_viewer_segment_lossless_webp"
        assert captured.metadata["capture_provenance"] == "decoded_visible_image_composition"
        assert captured.metadata["pre_jpeg_pixels_used"] is False
        assert captured.metadata["capture_group"]["fallback_reason"] == (
            "capture_buffer_overflow" if reason == "buffer_overflow"
            else "segment_source_not_exactly_bound"
        )
        with Image.open(tmp_path / "isolated-output" / captured.file) as saved, Image.open(
            io.BytesIO(base64.b64decode(references[index]))
        ) as reference:
            assert saved.size == (native_page_width, 1600)
            assert saved.convert("RGBA").tobytes() == reference.convert("RGBA").tobytes()


@pytest.mark.parametrize("decoded_segments", [False, True])
async def test_yanmaga_native_capture_rejects_same_geometry_source_replacement(
    browser_page, tmp_path, monkeypatch, decoded_segments
) -> None:
    await _set_routes(
        browser_page, monkeypatch, native_capture=True, native_ambiguous=decoded_segments
    )
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 500)
    capture_name = (
        "capture_yanmaga_decoded_segment_webp" if decoded_segments else "capture_yanmaga_native_webp"
    )
    capture = getattr(adapter_module, capture_name)
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

    monkeypatch.setattr(adapter_module, capture_name, capture_then_replace_source)
    with pytest.raises(
        UnknownPageStateError,
        match="reader changed while page pixels were captured",
    ):
        await CrawlerRunner(_config(tmp_path)).run(browser_page, YanmagaAdapter())

    assert changed
    assert not list((tmp_path / "isolated-output").glob("page-*.webp"))
    assert not list((tmp_path / "isolated-output").glob("page-*.png"))


@pytest.mark.parametrize("prompt", ["valid", "wrong_title", "wrong_cancel", "duplicate_cancel"])
async def test_yanmaga_cancels_only_the_observed_first_page_previous_episode_prompt(
    browser_page, tmp_path, monkeypatch, prompt
) -> None:
    requested = await _set_routes(browser_page, monkeypatch, native_capture=True)
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 500)
    adapter = YanmagaAdapter()
    normal_wait = adapter._wait_for_stable_snapshot
    inserted = False

    async def wait_with_previous_prompt(page, **kwargs):
        nonlocal inserted
        if not inserted and await page.locator("#content-p1").is_visible():
            inserted = True
            await page.evaluate(
                """args => {
                  const popup=document.createElement('div');popup.id='wrap-popup';
                  popup.className='active show-animation';
                  popup.style.cssText='position:fixed;top:200px;left:200px;z-index:100;background:white';
                  popup.innerHTML='<div id="popup-header"></div><div id="popup-footer">'+
                    '<div id="popup-footer-other"><a class="btn-ok">読む</a></div>'+
                    '<button id="popup-cancel-btn"></button></div>';
                  popup.querySelector('#popup-header').textContent=args.prompt==='wrong_title'
                    ? '次の話を読みますか？' : '前の話を読みますか？';
                  const cancel=popup.querySelector('button');
                  cancel.textContent=args.prompt==='wrong_cancel'?'読む':'キャンセル';
                  popup.querySelector('a').href=args.other;
                  window.__previousPromptCancels=0;
                  cancel.addEventListener('click',()=>{
                    window.__previousPromptCancels++;popup.style.display='none';
                    document.getElementById('menu').style.display='none';
                  });
                  if(args.prompt==='duplicate_cancel')popup.lastChild.append(cancel.cloneNode(true));
                  document.body.append(popup);document.getElementById('menu').style.display='block';
                }""",
                {"prompt": prompt, "other": f"{WORK_URL}/{NEXT_EPISODE_ID}"},
            )
        return await normal_wait(page, **kwargs)

    monkeypatch.setattr(adapter, "_wait_for_stable_snapshot", wait_with_previous_prompt)
    if prompt == "valid":
        result = await CrawlerRunner(_config(tmp_path)).run(browser_page, adapter)
        assert result.stop_state is PageState.END and len(result.pages) == 4
        assert all(p.metadata["previous_episode_prompt_cancelled"] for p in result.pages)
        assert await browser_page.evaluate("window.__previousPromptCancels") == 1
    else:
        with pytest.raises(UnknownPageStateError, match="not the known cancel prompt"):
            await CrawlerRunner(_config(tmp_path)).run(browser_page, adapter)
        assert await browser_page.evaluate("window.__previousPromptCancels") == 0
    assert inserted
    assert not any(urlsplit(url).path.endswith(NEXT_EPISODE_ID) for url in requested)


@pytest.mark.parametrize("arrow_mode", ["absent", "visible"])
async def test_yanmaga_waits_for_delayed_positive_terminal_controls_without_arrow_gate(
    browser_page, tmp_path, monkeypatch, arrow_mode
) -> None:
    await _set_routes(
        browser_page, monkeypatch, arrow_mode=arrow_mode
    )
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 1_000)

    adapter = YanmagaAdapter()
    capture = adapter.capture_page

    async def delayed_terminal_after_body(page):
        result = await capture(page)
        if adapter._captured_indices == [1, 2, 3, 4]:
            await page.evaluate("""() => {
              const rental=document.querySelector('#rental'), html=rental.innerHTML;
              rental.innerHTML='';setTimeout(()=>rental.innerHTML=html,250);
            }""")
        return result

    monkeypatch.setattr(adapter, "capture_page", delayed_terminal_after_body)
    result = await CrawlerRunner(_config(tmp_path)).run(browser_page, adapter)

    assert result.stop_state is PageState.END
    assert len(result.pages) == 4
    assert browser_page.url == VIEWER_NAVIGATION_URL


@pytest.mark.parametrize(
    ("scenario", "expected_error"),
    [
        ("unknown_access", UnknownPageStateError),
        ("known_restricted", UnknownPageStateError),
        ("wrong_route", UnknownPageStateError),
        ("missing_half", PageChangeTimeoutError),
        ("thin_segment", PageChangeTimeoutError),
        ("oversized_last_segment", PageChangeTimeoutError),
        ("unknown_aux", PageChangeTimeoutError),
        ("access_gate", PageChangeTimeoutError),
        ("inline_rental_dialog", PageChangeTimeoutError),
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
        "inline_rental_card": scenario == "inline_rental_dialog",
        "inline_rental_dialog": scenario == "inline_rental_dialog",
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
        assert sum(urlsplit(url).path == urlsplit(SOURCE_URL).path for url in requested) == 1
        assert not any(urlsplit(url).path == urlsplit(WORK_URL).path for url in requested)


@pytest.mark.parametrize("mutation", ["missing_work", "foreign_detail", "duplicate_title", "foreign_next"])
async def test_yanmaga_direct_entry_rejects_unbound_reader_metadata(
    browser_page, tmp_path, monkeypatch, mutation
) -> None:
    requested = await _set_routes(browser_page, monkeypatch)
    adapter = YanmagaAdapter()
    read = adapter._read_viewer_metadata

    async def drift(page):
        await page.evaluate("""mutation => {
          if(mutation==='missing_work')document.querySelector('#menu_header_parent_title').remove();
          if(mutation==='foreign_detail')document.querySelector('#detail_story').href='https://example.invalid/work';
          if(mutation==='duplicate_title')document.querySelector('#menu_header_tittle').after(document.querySelector('#menu_header_tittle').cloneNode(true));
          if(mutation==='foreign_next')document.querySelector('#next_story').href='https://example.invalid/next';
        }""",mutation)
        await read(page)

    monkeypatch.setattr(adapter, '_read_viewer_metadata', drift)
    monkeypatch.setattr(adapter_module, 'PAGE_CHANGE_TIMEOUT_MS', 200)
    with pytest.raises((UnknownPageStateError, PlaywrightTimeoutError)):
        await CrawlerRunner(_config(tmp_path)).run(browser_page,adapter)
    assert not any(urlsplit(url).path == urlsplit(WORK_URL).path for url in requested)
    assert sum(urlsplit(url).path == urlsplit(SOURCE_URL).path for url in requested) == 1


@pytest.mark.parametrize(
    ("scenario", "control"),
    [("valid", "valid_next"), ("valid", "point_rental"), ("counter_ahead", "valid_next"),
     *[(scenario, "valid_next") for scenario in (
         "bad_caption", "wrong_total", "unbound_caption", "duplicate_caption", "wrong_title",
         "missing_control", "edge_obstruction", "small_card", "missing_last", "visible_body",
         "premature",
     )]],
)
@pytest.mark.parametrize("even_terminal_only", [False, True], ids=["odd", "even"])
async def test_yanmaga_terminal_only_requires_all_body_pages_and_exact_native_shape(
    browser_page, tmp_path, monkeypatch, scenario, control, even_terminal_only
) -> None:
    requested = await _set_routes(
        browser_page, monkeypatch, odd_terminal_only=not even_terminal_only,
        even_terminal_only=even_terminal_only, terminal_control=control,
        inline_rental_card=control == "point_rental",
        authenticated_listing=True if control == "point_rental" else None,
    )
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 900 if scenario == "counter_ahead" else 450)
    adapter = YanmagaAdapter()
    capture = adapter.capture_page

    async def capture_then_alter_terminal(page):
        result = await capture(page)
        if adapter._captured_indices == ([1, 2] if even_terminal_only else [1]):
            await page.evaluate(
                """({scenario, even}) => {
                  const terminal=even?5:4;
                  const original=show;
                  show=value=>{
                    const previous=[...document.querySelectorAll('.body-page')]
                      .map(node=>[node,node.style.cssText]);
                    original(value);
                    if(scenario==='premature' && value===(even?3:2)){original(terminal);return;}
                    if(value!==terminal)return;
                    const caption=document.getElementById('menu_slidercaption');
                    const rental=document.getElementById('rental');
                    if(scenario==='counter_ahead'){
                      for(const [node,css] of previous)node.style.cssText=css;
                      rental.style.left='-1307.625px';
                      setTimeout(()=>original(terminal),250);
                    }
                    if(scenario==='bad_caption')caption.textContent='--/3';
                    if(scenario==='wrong_total')caption.textContent=even?'-/5':'-/4';
                    if(scenario==='unbound_caption')caption.id='other-caption';
                    if(scenario==='duplicate_caption')caption.parentElement.append(caption.cloneNode(true));
                    if(scenario==='wrong_title')rental.querySelector('.episode-modal-eptitle').textContent='wrong';
                    if(scenario==='missing_control')rental.querySelector('#js-btn-valid-next-episode').remove();
                    if(scenario==='small_card')rental.style.width='500px';
                    if(scenario==='missing_last')document.getElementById('content-p'+(even?4:3)).remove();
                    if(scenario==='visible_body')document.getElementById('content-p'+(even?4:3)).style.left='0px';
                    if(scenario==='edge_obstruction'){
                      const cover=document.createElement('div');
                      cover.style.cssText='position:fixed;left:1280px;top:1788px;width:12px;height:12px;z-index:100;background:red';
                      document.body.append(cover);
                    }
                  };
                }""",
                {"scenario": scenario, "even": even_terminal_only},
            )
        return result

    monkeypatch.setattr(adapter, "capture_page", capture_then_alter_terminal)
    config = _config(tmp_path)
    total = 4 if even_terminal_only else 3
    config.max_pages = total
    if scenario in {"valid", "counter_ahead"}:
        result = await CrawlerRunner(config).run(browser_page, adapter)
        assert result.stop_state is PageState.END and len(result.pages) == total
        assert adapter._captured_indices == list(range(1, total + 1))
        debug = await adapter.collect_debug_metadata(browser_page)
        assert debug["native_counter"] == f"-/{total}" and debug["terminal_only"] is True
        assert debug["terminal_proof"]["native_counter_complete"] is False
        assert debug["terminal_proof"]["terminal_only_layout_exact"] is True
        with pytest.raises(UnknownPageStateError, match="terminal-only.*identity"):
            await adapter.get_content_identity(browser_page)
    else:
        with pytest.raises((UnknownPageStateError, PageChangeTimeoutError)):
            await CrawlerRunner(config).run(browser_page, adapter)
    pages = list((tmp_path / "isolated-output").glob("page-*.png"))
    assert len(pages) == ((2 if even_terminal_only else 1) if scenario == "premature" else total)
    assert not any(urlsplit(url).path == "/viewer/rental" for url in requested)
    assert not any(NEXT_EPISODE_ID in urlsplit(url).path for url in requested)


@pytest.mark.parametrize("layout_arrives", [False, True])
@pytest.mark.parametrize("phase", ["next", "rewind"])
async def test_yanmaga_counter_precedes_layout_waits_without_another_turn(
    browser_page, tmp_path, monkeypatch, layout_arrives, phase
) -> None:
    await _set_routes(browser_page, monkeypatch)
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 900)
    adapter = YanmagaAdapter()
    capture = adapter.capture_page

    async def capture_then_delay_first_turn(page):
        result = await capture(page)
        if adapter._captured_indices == [1]:
            await page.evaluate(
                """layoutArrives => {
                  window.__testArrowCalls=0;
                  let first=true;
                  document.addEventListener('keydown',event=>{
                    if(event.key!=='ArrowLeft') return;
                    window.__testArrowCalls++;
                    if(!first) return;
                    first=false;event.stopImmediatePropagation();
                    const counter=[...document.querySelectorAll('body *')].find(node=>
                      !node.children.length && /^1\\s*\\/\\s*4$/.test(node.innerText||''));
                    counter.textContent='2 / 4';
                    if(layoutArrives) setTimeout(()=>show(2),400);
                  },true);
                }""",
                layout_arrives,
            )
        return result

    if phase == "rewind":
        read = adapter._read_viewer_metadata

        async def delay_initial_rewind(page):
            await read(page)
            await page.evaluate("""layoutArrives => {
              window.__testArrowCalls=0;
              let first=true;
              document.addEventListener('keydown',event=>{
                if(event.key!=='ArrowRight')return;
                window.__testArrowCalls++;
                if(!first)return;
                first=false;event.stopImmediatePropagation();
                document.querySelector('#counter').textContent='1/4';
                if(layoutArrives)setTimeout(()=>show(1),400);
              },true);
            }""",layout_arrives)

        monkeypatch.setattr(adapter, "_read_viewer_metadata", delay_initial_rewind)
    else:
        monkeypatch.setattr(adapter, "capture_page", capture_then_delay_first_turn)
    if layout_arrives:
        result = await CrawlerRunner(_config(tmp_path)).run(browser_page, adapter)
        assert result.stop_state is PageState.END and len(result.pages) == 4
    else:
        with pytest.raises(PageChangeTimeoutError, match="did not advance within|did not stabilize"):
            await CrawlerRunner(_config(tmp_path)).run(browser_page, adapter)
        assert len(list((tmp_path / "isolated-output").glob("page-*.png"))) == (0 if phase == "rewind" else 1)
    assert await browser_page.evaluate("window.__testArrowCalls") == (1 if phase == "rewind" else 2 if layout_arrives else 1)


async def test_yanmaga_first_free_saves_exact_finite_grant_before_capture_and_completes(
    browser_page, tmp_path, monkeypatch
) -> None:
    requested = await _set_routes(
        browser_page,
        monkeypatch,
        access_mode="first_free",
        first_free_completion_notice=True,
        access_proof_delay_ms=150,
    )
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 500)
    proof_calls = _install_rental_history_proof(monkeypatch)
    catalog, policies, adapters, candidate, item, source, _target, watchlist = _seed_batch_candidate(
        tmp_path
    )
    capture = YanmagaAdapter.capture_page

    async def capture_after_durable_grant(adapter, page):
        assert catalog.get_source(source.id).access_granted_until is not None
        return await capture(adapter, page)

    monkeypatch.setattr(YanmagaAdapter, "capture_page", capture_after_durable_grant)
    executor = BatchExecutor(
        catalog,
        policies,
        adapters,
        watchlist=watchlist,
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

    saved_source = catalog.get_source(source.id)
    assert result.stop_reason == "end" and result.page_count == 4
    assert catalog.get_item(item.id).status == "completed"
    assert datetime.fromisoformat(saved_source.access_granted_until).astimezone(UTC) == GRANT_UNTIL
    assert saved_source.quota_started_at is None
    assert len(proof_calls) == 1
    assert sum(urlsplit(url).path == urlsplit(SOURCE_URL).path for url in requested) == 1


@pytest.mark.parametrize("failure", ["missing", "duplicate", "foreign", "inactive"])
async def test_yanmaga_existing_grant_requires_exact_active_history_before_source_entry(
    browser_page, monkeypatch, failure
) -> None:
    requested, adapter = await _adapter_at_work(browser_page,monkeypatch,access_mode='trusted_grant')
    async def proof(*_args, **_kwargs):
        value = RentalCountdown(observed_at=GRANT_OBSERVED_AT,
            remaining_hours=0 if failure=='inactive' else 22,access_granted_until=GRANT_UNTIL,
            expiry_evidence='site_countdown_lower_bound')
        pair = (f"{SLUG}:{'f'*32 if failure=='foreign' else EPISODE_ID}",value)
        return () if failure=='missing' else (pair,pair) if failure=='duplicate' else (pair,)
    monkeypatch.setattr(adapter_module,'fetch_rental_history_countdowns',proof)
    with pytest.raises(AccessResourceUnavailableError):
        await adapter.initialize(browser_page)
    assert not any(urlsplit(url).path == urlsplit(SOURCE_URL).path for url in requested)


@pytest.mark.parametrize(
    "failure",
    ["pixel_readiness", "rewind", "end", "zip"],
)
async def test_yanmaga_first_free_grant_survives_render_end_and_package_failures(
    browser_page, tmp_path, monkeypatch, failure
) -> None:
    requested = await _set_routes(
        browser_page,
        monkeypatch,
        access_mode="first_free",
        first_free_completion_notice=True,
        thin_segment=failure == "pixel_readiness",
        missing_half=failure == "rewind",
        unsafe_end=failure == "end",
    )
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 350)
    proof_calls = _install_rental_history_proof(monkeypatch)
    catalog, policies, adapters, candidate, item, source, _target, watchlist = _seed_batch_candidate(
        tmp_path
    )
    executor_kwargs = {"runtime_settings": SiteRuntimeSettings(page_turn_delay_ms=0)}
    if failure == "zip":
        def fail_package(*_args, **_kwargs):
            raise OSError("synthetic ZIP packaging failure")

        executor_kwargs["package_function"] = fail_package
    executor = BatchExecutor(catalog, policies, adapters, watchlist=watchlist, **executor_kwargs)

    with pytest.raises(CandidateExecutionError):
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "batch-output",
            library_dir=tmp_path / "library",
            max_pages=8,
            now=NOW,
        )

    saved_source = catalog.get_source(source.id)
    assert catalog.get_item(item.id).status == "pending"
    assert catalog.list_artifacts(item_id=item.id) == []
    assert saved_source.access_granted_until is not None
    assert datetime.fromisoformat(saved_source.access_granted_until).astimezone(UTC) == GRANT_UNTIL
    assert saved_source.quota_started_at is None
    assert len(proof_calls) == 1
    assert sum(urlsplit(url).path == urlsplit(SOURCE_URL).path for url in requested) == 1
    assert not list((tmp_path / "library").rglob("*.zip"))


async def test_yanmaga_first_free_navigation_timeout_requires_discovery_without_retry(
    browser_page, tmp_path, monkeypatch
) -> None:
    requested = await _set_routes(
        browser_page,
        monkeypatch,
        access_mode="first_free",
        first_free_completion_notice=True,
        source_goto_failure="timeout_after_navigation",
    )
    proof_calls = _install_rental_history_proof(monkeypatch)
    catalog, policies, adapters, candidate, item, source, _target, watchlist = _seed_batch_candidate(
        tmp_path
    )
    executor = BatchExecutor(catalog, policies, adapters, watchlist=watchlist)

    with pytest.raises(CandidateExecutionError) as raised:
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "batch-output",
            library_dir=tmp_path / "library",
            now=NOW,
        )

    assert isinstance(raised.value.__cause__, PlaywrightTimeoutError)
    saved_source = catalog.get_source(source.id)
    assert browser_page.url == VIEWER_NAVIGATION_URL
    assert catalog.get_item(item.id).status == "pending"
    assert saved_source.access_granted_until is None
    assert proof_calls == []
    assert sum(urlsplit(url).path == urlsplit(SOURCE_URL).path for url in requested) == 1
    assert catalog.list_artifacts(item_id=item.id) == []


async def test_yanmaga_first_free_cancellation_does_not_start_metadata_retry(
    browser_page, tmp_path, monkeypatch
) -> None:
    requested = await _set_routes(
        browser_page,
        monkeypatch,
        access_mode="first_free",
        first_free_completion_notice=True,
        source_goto_failure="cancel_after_navigation",
    )
    proof_calls = _install_rental_history_proof(monkeypatch)
    catalog, policies, adapters, candidate, item, source, _target, watchlist = _seed_batch_candidate(
        tmp_path
    )
    executor = BatchExecutor(catalog, policies, adapters, watchlist=watchlist)

    with pytest.raises(BatchInterruptedError) as raised:
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "batch-output",
            library_dir=tmp_path / "library",
            now=NOW,
        )

    assert isinstance(raised.value.__cause__, asyncio.CancelledError)
    saved_source = catalog.get_source(source.id)
    assert browser_page.url == VIEWER_NAVIGATION_URL
    assert catalog.get_item(item.id).status == "pending"
    assert saved_source.access_granted_until is None
    assert saved_source.quota_started_at is None
    assert proof_calls == []
    assert sum(urlsplit(url).path == urlsplit(SOURCE_URL).path for url in requested) == 1
    assert catalog.list_artifacts(item_id=item.id) == []


async def test_yanmaga_first_free_unknown_access_proof_does_not_retry_entry_or_fetch_metadata(
    browser_page, tmp_path, monkeypatch
) -> None:
    requested = await _set_routes(
        browser_page,
        monkeypatch,
        access_mode="first_free",
        first_free_completion_notice=True,
        access_proof_never_ready=True,
    )
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 250)
    proof_calls = _install_rental_history_proof(monkeypatch)
    catalog, policies, adapters, candidate, item, source, _target, watchlist = _seed_batch_candidate(
        tmp_path
    )
    executor = BatchExecutor(catalog, policies, adapters, watchlist=watchlist)

    with pytest.raises(AccessResourceUnavailableError):
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "batch-output",
            library_dir=tmp_path / "library",
            now=NOW,
        )

    saved_source = catalog.get_source(source.id)
    assert catalog.get_item(item.id).status == "pending"
    assert saved_source.access_granted_until is None
    assert proof_calls == []
    assert sum(urlsplit(url).path == urlsplit(SOURCE_URL).path for url in requested) == 1
    assert catalog.list_artifacts(item_id=item.id) == []


@pytest.mark.parametrize(
    "gate_text",
    [
        pytest.param("\u30c1\u30b1\u30c3\u30c8", id="ticket-gate"),
        pytest.param("\u521d\u56de\u7121\u6599", id="first-free-gate"),
        pytest.param("\u4f1a\u54e1\u767b\u9332", id="registration-gate"),
        pytest.param("\u30ec\u30f3\u30bf\u30eb", id="rental-gate"),
        pytest.param("\u7121\u6599\u306f1\u65e5\u3067\u8aad\u3081\u308b\u6570", id="daily-limit-gate"),
    ],
)
async def test_yanmaga_first_free_roleless_access_gate_blocks_notice_and_history(
    browser_page, tmp_path, monkeypatch, gate_text
) -> None:
    requested = await _set_routes(
        browser_page,
        monkeypatch,
        access_mode="first_free",
        first_free_completion_notice=True,
        access_gate_text=gate_text,
    )
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 250)
    history_calls = _install_rental_history_proof(monkeypatch)
    catalog, policies, adapters, candidate, item, source, _target, watchlist = _seed_batch_candidate(
        tmp_path
    )
    executor = BatchExecutor(catalog, policies, adapters, watchlist=watchlist)

    with pytest.raises(AccessResourceUnavailableError):
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "batch-output",
            library_dir=tmp_path / "library",
            now=NOW,
        )

    saved_source = catalog.get_source(source.id)
    assert catalog.get_item(item.id).status == "pending"
    assert saved_source.access_granted_until is None
    assert history_calls == []
    assert sum(urlsplit(url).path == urlsplit(SOURCE_URL).path for url in requested) == 1
    assert catalog.list_artifacts(item_id=item.id) == []


async def test_yanmaga_first_free_guard_stop_during_confirmation_is_fatal(
    browser_page, tmp_path, monkeypatch
) -> None:
    requested = await _set_routes(
        browser_page,
        monkeypatch,
        access_mode="first_free",
        first_free_completion_notice=True,
    )
    proof_calls = _install_rental_history_proof(monkeypatch)

    async def stop_confirmation(_self, *_args, **_kwargs):
        raise AccessStopError(reason="http_429", site="yanmaga", url=VIEWER_NAVIGATION_URL)

    monkeypatch.setattr(YanmagaAdapter, "_confirm_and_persist_first_free_grant", stop_confirmation)
    catalog, policies, adapters, candidate, _item, _source, _target, watchlist = _seed_batch_candidate(
        tmp_path
    )
    executor = BatchExecutor(catalog, policies, adapters, watchlist=watchlist)

    with pytest.raises(BatchExecutionError) as raised:
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "batch-output",
            library_dir=tmp_path / "library",
            now=NOW,
        )

    assert raised.value.access_stop.reason == "http_429"
    assert proof_calls == []
    assert sum(urlsplit(url).path == urlsplit(SOURCE_URL).path for url in requested) == 1


@pytest.mark.parametrize(
    ("grant_is_future", "remaining_hours", "expected_entry"),
    [
        pytest.param(True, 1, True, id="active-one-hour-with-trusted-future-grant"),
        pytest.param(True, 0, False, id="inactive-countdown-does-not-enter"),
        pytest.param(False, 1, False, id="expired-catalog-grant-does-not-enter"),
    ],
)
@pytest.mark.parametrize("countdown_unit", ["hours", "days"])
async def test_yanmaga_existing_grant_recheck_uses_catalog_expiry_and_active_countdown(
    browser_page, monkeypatch, grant_is_future, remaining_hours, expected_entry, countdown_unit
) -> None:
    requested, adapter = await _adapter_at_work(
        browser_page,
        monkeypatch,
        access_mode="trusted_grant",
    )
    observed_at = datetime.now(UTC)
    expiry = (
        datetime.now(UTC) + timedelta(hours=4)
        if grant_is_future
        else datetime.now(UTC) - timedelta(minutes=1)
    )
    adapter.configure_existing_access_grant(expiry)
    calls = []

    async def fake_fetch(
        _page,
        *,
        observed_mypage_href,
        targets,
        max_countdown_hours=23,
    ):
        calls.append((observed_mypage_href, targets))
        assert max_countdown_hours == 72
        return (
            (
                f"{SLUG}:{EPISODE_ID}",
                RentalCountdown(
                    observed_at=observed_at,
                    remaining_hours=remaining_hours if countdown_unit == "hours" else 0,
                    remaining_days=remaining_hours if countdown_unit == "days" else None,
                    access_granted_until=None,
                    expiry_evidence=None,
                ),
            ),
        )

    monkeypatch.setattr(adapter_module, "fetch_rental_history_countdowns", fake_fetch)
    if expected_entry:
        await adapter.initialize(browser_page)
    else:
        with pytest.raises((AccessResourceUnavailableError, UnknownPageStateError)):
            await adapter.initialize(browser_page)

    source_requests = [url for url in requested if urlsplit(url).path == urlsplit(SOURCE_URL).path]
    assert len(source_requests) == int(expected_entry)
    assert len(calls) == int(grant_is_future)


async def test_yanmaga_retry_uses_saved_grant_without_reemitting_or_extending_it(
    browser_page, tmp_path, monkeypatch
) -> None:
    first_requested = await _set_routes(
        browser_page,
        monkeypatch,
        access_mode="first_free",
        first_free_completion_notice=True,
        unsafe_end=True,
    )
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 350)
    proof_calls = _install_rental_history_proof(monkeypatch)
    catalog, policies, adapters, candidate, item, source, _target, watchlist = _seed_batch_candidate(
        tmp_path
    )
    recorded_grants: list[dict[str, object]] = []
    original_record_grant = catalog.record_confirmed_access_grant

    def record_grant(*args, **kwargs):
        recorded_grants.append(dict(kwargs))
        return original_record_grant(*args, **kwargs)

    monkeypatch.setattr(catalog, "record_confirmed_access_grant", record_grant)
    failing_executor = BatchExecutor(catalog, policies, adapters, watchlist=watchlist)

    with pytest.raises(CandidateExecutionError):
        await failing_executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "first-output",
            library_dir=tmp_path / "library",
            max_pages=8,
            now=NOW,
        )

    first_saved_source = catalog.get_source(source.id)
    assert catalog.get_item(item.id).status == "pending"
    assert datetime.fromisoformat(first_saved_source.access_granted_until).astimezone(UTC) == GRANT_UNTIL
    assert len(recorded_grants) == 1
    assert len(proof_calls) == 1

    retry_requested = await _set_routes(
        browser_page,
        monkeypatch,
        access_mode="trusted_grant",
    )
    retry_executor = BatchExecutor(catalog, policies, adapters, watchlist=watchlist)
    result = await retry_executor.execute_candidate(
        browser_page,
        candidate,
        output_root=tmp_path / "retry-output",
        library_dir=tmp_path / "library",
        max_pages=8,
        now=NOW + timedelta(minutes=5),
    )

    retried_source = catalog.get_source(source.id)
    assert result.stop_reason == "end"
    assert catalog.get_item(item.id).status == "completed"
    assert datetime.fromisoformat(retried_source.access_granted_until).astimezone(UTC) == GRANT_UNTIL
    assert retried_source.quota_started_at is None
    assert len(recorded_grants) == 1
    assert len(proof_calls) >= 2
    assert sum(urlsplit(url).path == urlsplit(SOURCE_URL).path for url in first_requested) == 1
    assert sum(urlsplit(url).path == urlsplit(SOURCE_URL).path for url in retry_requested) == 1


async def test_yanmaga_batch_runs_direct_to_zip_and_completes_catalog_item(
    browser_page, tmp_path, monkeypatch
) -> None:
    requested = await _set_routes(browser_page, monkeypatch)
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 500)
    catalog, policies, adapters, candidate, item, source, target, watchlist = _seed_batch_candidate(
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
        watchlist=watchlist,
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


async def test_yanmaga_batch_stops_on_direct_source_access_gate(
    browser_page, tmp_path, monkeypatch
) -> None:
    requested = await _set_routes(browser_page, monkeypatch, access_mode="known_restricted")
    catalog, policies, adapters, candidate, item, _source, _target, watchlist = _seed_batch_candidate(
        tmp_path
    )
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 200)
    executor = BatchExecutor(catalog, policies, adapters, watchlist=watchlist)

    with pytest.raises(CandidateExecutionError):
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
    assert sum(urlsplit(url).path == urlsplit(SOURCE_URL).path for url in requested) == 1
    assert not any(urlsplit(url).path == urlsplit(WORK_URL).path for url in requested)


@pytest.mark.parametrize("failure", ["invalid_end", "zip_failure"])
async def test_yanmaga_batch_failure_keeps_item_pending_without_success_artifact(
    browser_page, tmp_path, monkeypatch, failure
) -> None:
    await _set_routes(browser_page, monkeypatch, unsafe_end=failure == "invalid_end")
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 300)
    catalog, policies, adapters, candidate, item, _source, _target, watchlist = _seed_batch_candidate(
        tmp_path
    )

    def fail_package(*_args, **_kwargs):
        raise OSError("synthetic ZIP packaging failure")

    executor_kwargs = {"runtime_settings": SiteRuntimeSettings(page_turn_delay_ms=0)}
    if failure == "zip_failure":
        executor_kwargs["package_function"] = fail_package
    executor = BatchExecutor(catalog, policies, adapters, watchlist=watchlist, **executor_kwargs)

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


@pytest.mark.parametrize(
    "case",
    [
        "valid",
        "popup_iframe",
        "missing",
        "wrong_episode",
        "duplicate_query",
        "wrong_code",
        "unknown_mode",
        "duplicate_root",
        "oversized",
        "wrong_mime",
    ],
)
async def test_yanmaga_terminal_requires_current_episode_native_response(
    browser_page, tmp_path, monkeypatch, case
) -> None:
    requested = await _set_routes(browser_page, monkeypatch, terminal_response_case=case)
    monkeypatch.setattr(adapter_module, "PAGE_CHANGE_TIMEOUT_MS", 400)
    adapter = YanmagaAdapter()
    if case in {"valid", "popup_iframe"}:
        result = await CrawlerRunner(_config(tmp_path)).run(browser_page, adapter)
        assert result.stop_state is PageState.END and len(result.pages) == 4
        metadata = await adapter.collect_debug_metadata(browser_page)
        assert metadata["terminal_proof"]["native_response_bound"] is True
    else:
        with pytest.raises(UnknownPageStateError):
            await CrawlerRunner(_config(tmp_path)).run(browser_page, adapter)
        assert len(list((tmp_path / "isolated-output").glob("page-*.png"))) == 4
    assert sum(urlsplit(url).path == urlsplit(SOURCE_URL).path for url in requested) == 1
    assert not any(urlsplit(url).path == urlsplit(WORK_URL).path for url in requested)


async def test_yanmaga_manual_first_free_direct_entry_can_finish_without_catalog_observer(
    browser_page, tmp_path, monkeypatch
) -> None:
    requested = await _set_routes(
        browser_page, monkeypatch, access_mode="first_free", first_free_completion_notice=True
    )
    adapter = YanmagaAdapter()
    result = await CrawlerRunner(_config(tmp_path)).run(browser_page, adapter)
    assert result.stop_state is PageState.END and len(result.pages) == 4
    assert adapter.first_free_release_state == "discovery_required"
    assert adapter._first_free_grant is None
    assert sum(urlsplit(url).path == urlsplit(SOURCE_URL).path for url in requested) == 1
    assert not any(urlsplit(url).path == urlsplit(WORK_URL).path for url in requested)


async def test_yanmaga_terminal_response_from_previous_document_is_not_reused(
    browser_page, monkeypatch
) -> None:
    _, adapter = await _adapter_at_work(browser_page, monkeypatch)
    await adapter.initialize(browser_page)
    observer = adapter._terminal_observer
    assert observer is not None and observer.signature is not None

    async def missing(route):
        await route.fulfill(status=404, body="missing")

    await browser_page.route("**/viewer/rental_episode?*", missing)
    await browser_page.reload(wait_until="networkidle")
    assert observer.signature is None
    snapshot = await adapter._read_snapshot(browser_page)
    assert snapshot is not None and not snapshot.rental_response_bound
