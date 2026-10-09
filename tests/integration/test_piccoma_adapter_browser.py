from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
import pytest_asyncio
from PIL import Image
from playwright.async_api import Browser, Page

import screenshot_crawler.site_adapters.piccoma.adapter as piccoma_adapter_module
from screenshot_crawler.batch import (
    BatchExecutionError,
    BatchExecutor,
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
    UnsupportedAccessStrategyError,
)
from screenshot_crawler.core.models import ContentIdentity
from screenshot_crawler.core.packaging import package_crawl_output
from screenshot_crawler.core.state import PageState
from screenshot_crawler.runtime_settings import SiteRuntimeSettings
from screenshot_crawler.site_adapters.piccoma.adapter import PiccomaAdapter
from screenshot_crawler.site_adapters.registry import AdapterRegistry
from screenshot_crawler.site_policies import PiccomaSitePolicy, SitePolicyRegistry

pytestmark = pytest.mark.asyncio(loop_scope="module")

PRODUCT_ID = "900"
EPISODE_ID = "101"
SOURCE_URL = f"https://piccoma.com/web/viewer/{PRODUCT_ID}/{EPISODE_ID}"
WORK_KEY = "caller-owned-opaque-work-key"
PAGE_WIDTH = 20
PAGE_HEIGHT = 30
PAGE_COLOR = (16, 40, 80)
BATCH_NOW = datetime(2026, 10, 9, 12, tzinfo=JST)


@pytest_asyncio.fixture(loop_scope="module")
async def browser_page(integration_browser: Browser) -> Page:
    context = await integration_browser.new_context(viewport={"width": 800, "height": 600})
    page = await context.new_page()
    try:
        yield page
    finally:
        await page.close()
        await context.close()


def _listing_html(*, status: str = "free") -> str:
    if status == "free":
        marker, label = "PCM-epList_status_free", "&#165;0"
    elif status == "quota":
        marker, label = "PCM-epList_status_waitfree", "&#165;0"
    else:
        marker, label = "PCM-epList_status_point", "5"
    return f"""<!doctype html><html><body>
      <main id="js_contentBody"><h1 class="PCM-headTitle_name">Fixture Work</h1>
      <div id="js_episodeList" class="PCM-list_asc">
        <a data-product_id="{PRODUCT_ID}" data-episode_id="{EPISODE_ID}">
          <span class="PCM-epList_ep"><span class="PCM-epList_title">Episode 1</span>
            <span class="PCM-epList_status {marker}"><span>{label}</span></span>
          </span>
        </a>
      </div></main>
    </body></html>"""


def _viewer_html(
    *,
    page_count: int = 3,
    initial_page: int = 1,
    resume_dialog: bool = False,
    resume_variant: str = "numeric",
    delayed_resume_ms: int = 0,
    unknown_dialog: bool = False,
    omit_page: int | None = None,
    incomplete_page: int | None = None,
    duplicate_page: int | None = None,
) -> str:
    wrappers = []
    for number in range(page_count, 0, -1):
        if number == omit_page:
            continue
        if number == incomplete_page:
            canvas = '<canvas width="0" height="0"></canvas>'
        else:
            canvas = f'<canvas width="{PAGE_WIDTH}" height="{PAGE_HEIGHT}"></canvas>'
        wrappers.append(
            f'<section id="p{number}" class="PCM-viewer2_pageWrapper'
            f'{" current" if number == initial_page else ""}">'
            f'<div class="PCM-viewer2_canvasWrapper loaded">{canvas}</div></section>'
        )
        if number == duplicate_page:
            wrappers.append(
                f'<section id="p{number}" class="PCM-viewer2_pageWrapper">'
                f'<div class="PCM-viewer2_canvasWrapper loaded">'
                f'<canvas width="{PAGE_WIDTH}" height="{PAGE_HEIGHT}"></canvas>'
                '</div></section>'
            )
    wrappers.insert(
        0,
        '<section id="last" class="PCM-viewer2_pageWrapper">'
        '<div id="js_viewerEnd" class="PCM-viewer2_endPage">'
        '<a class="js_first_page" href="#">First page</a>'
        '<a class="PCM-viewer2ReadBtn" href="/web/product/900/episodes">Next episode</a>'
        '</div></section>',
    )
    prompt = ""
    delayed_prompt = ""
    if resume_dialog:
        resume_texts = {
            "numeric": (
                "\u524d\u56de2\u30da\u30fc\u30b8\u3092\u8aad\u3093\u3067\u3044\u307e\u3057\u305f\u3002 "
                "2\u30da\u30fc\u30b8\u306b\u79fb\u52d5\u3057\u307e\u3059\u304b\uff1f"
            ),
            "last": (
                "\u524d\u56de\u6700\u5f8c\u306e\u30da\u30fc\u30b8\u3092 \u8aad\u3093\u3067\u3044\u307e\u3057\u305f\u3002 "
                "\u6700\u5f8c\u306e\u30da\u30fc\u30b8\u306b\u79fb\u52d5\u3057\u307e\u3059\u304b\uff1f"
            ),
            "mixed": (
                "\u524d\u56de\u6700\u5f8c\u306e\u30da\u30fc\u30b8\u3092 \u8aad\u3093\u3067\u3044\u307e\u3057\u305f\u3002 "
                "2\u30da\u30fc\u30b8\u306b\u79fb\u52d5\u3057\u307e\u3059\u304b\uff1f"
            ),
            "extra": (
                "\u524d\u56de\u6700\u5f8c\u306e\u30da\u30fc\u30b8\u3092 \u8aad\u3093\u3067\u3044\u307e\u3057\u305f\u3002 "
                "\u6700\u5f8c\u306e\u30da\u30fc\u30b8\u306b\u79fb\u52d5\u3057\u307e\u3059\u304b\uff1f "
                "\u7121\u6599"
            ),
        }
        resume_markup = f"""<div class="jconfirm-open PCM-pcmConfirm">
          <p>{resume_texts[resume_variant]}</p>
          <button data-action="resume">\u79fb\u52d5\u3059\u308b</button>
          <button data-action="cancel">\u30ad\u30e3\u30f3\u30bb\u30eb</button>
        </div>"""
        if delayed_resume_ms:
            delayed_prompt = (
                f"<script>setTimeout(()=>{{const wrapper=document.createElement('div');"
                f"wrapper.innerHTML={json.dumps(resume_markup)};"
                "const dialog=wrapper.firstElementChild;document.body.append(dialog);"
                "wireActions(dialog);},"
                f"{delayed_resume_ms});</script>"
            )
        else:
            prompt = resume_markup
    elif unknown_dialog:
        prompt = '<div class="jconfirm-open"><button data-action="login">Continue</button></div>'
    return f"""<!doctype html><html><head><style>
      html,body {{ margin:0; }}
      #js_frame {{ position:relative; width:{PAGE_WIDTH}px; height:{PAGE_HEIGHT}px; margin:0 auto; }}
      .PCM-viewer2_pageWrapper {{ position:absolute; inset:0; display:none; }}
      .PCM-viewer2_pageWrapper.current {{ display:block; }}
      .PCM-viewer2_canvasWrapper {{ width:{PAGE_WIDTH}px; height:{PAGE_HEIGHT}px; }}
      .PCM-viewer2_canvasWrapper canvas {{ display:block; }}
      #js_scrollTypeSing {{ position:fixed; z-index:101000; left:calc(50% - 5px); top:10px;
        width:10px; height:10px; background:rgba(32,32,32,.9); }}
      #js_scrollTypeSing > div {{ display:none; }}
      .jconfirm-open {{ position:fixed; inset:0; z-index:200000; background:#fff; }}
    </style></head><body class="PCM-viewer2 PCM-stt_horizontal PCM-prop_scroll_l">
      <div id="react_ViewerApp"><div id="js_frame" class="PCM-viewer2_frame">
        <div id="react_PageListApp" class="PCM-viewer2_wrapper">{''.join(wrappers)}</div>
      </div><div id="js_scrollTypeSing" class="PCM-viewer2_scrollTypeSign PCM-viewer2_scrollTypeSign_sh PCM-viewer2_scrollTypeSign_show">
        <div class="PCM-viewer2_scrollTypeSign_v"><img alt="\u30bf\u30c6\u8aad\u307f"></div>
        <div class="PCM-viewer2_scrollTypeSign_h"><img class="PCM-viewer2_scrollTypeSign_l" alt="\u30e8\u30b3\u8aad\u307f"><img class="PCM-viewer2_scrollTypeSign_r" alt="\u30e8\u30b3\u8aad\u307f"></div>
      </div>{prompt}{delayed_prompt}</div>
      <button class="PCM-viewer2_pagingBtn_prev" onclick="step(-1)">Previous</button>
      <button class="PCM-viewer2_pagingBtn_next" onclick="step(1)">Next</button>
      <script>
        window.forbiddenClicks = 0;
        window.resumeClicks = 0;
        window.cancelClicks = 0;
        function wireActions(root) {{
          root.querySelectorAll('.PCM-viewer2ReadBtn').forEach(node =>
            node.addEventListener('click', () => window.forbiddenClicks++));
          root.querySelectorAll('[data-action="resume"]').forEach(node =>
            node.addEventListener('click', () => window.resumeClicks++));
          root.querySelectorAll('[data-action="cancel"]').forEach(node =>
            node.addEventListener('click', () => {{ window.cancelClicks++; node.parentElement.remove(); }}));
          root.querySelectorAll('[data-action="login"]').forEach(node =>
            node.addEventListener('click', () => window.forbiddenClicks++));
        }}
        wireActions(document);
        function step(direction) {{
          const active = document.querySelector('#react_PageListApp .PCM-viewer2_pageWrapper.current');
          if (!active) return;
          const match = active.id.match(/^p([0-9]+)$/);
          let nextId;
          if (!match && direction < 0) nextId = 'p{page_count}';
          else if (!match) return;
          else {{
            const number = Number(match[1]);
            if (direction > 0 && number === {page_count}) nextId = 'last';
            else nextId = 'p' + (number + direction);
          }}
          const target = document.getElementById(nextId);
          if (!target) return;
          active.classList.remove('current'); target.classList.add('current');
          document.body.classList.toggle('PCM-viewer2_last', nextId === 'last');
        }}
        window.piccomaStep = step;
        const canvas = document.querySelector('#p1 canvas');
        if (canvas && canvas.width > 0) {{
          const ctx = canvas.getContext('2d');
          ctx.fillStyle = 'rgb({PAGE_COLOR[0]},{PAGE_COLOR[1]},{PAGE_COLOR[2]})';
          ctx.fillRect(0,0,canvas.width,canvas.height);
          const image = new Image();
          image.onload = () => {{ ctx.drawImage(image,0,0,canvas.width,canvas.height); canvas.dataset.drawn='true'; }};
          image.src = 'https://pcm.kakaocdn.net/fixture/body.png';
        }}
      </script>
    </body></html>"""


def _synthetic_png() -> bytes:
    output = BytesIO()
    Image.new("RGB", (PAGE_WIDTH, PAGE_HEIGHT), PAGE_COLOR).save(output, format="PNG")
    return output.getvalue()


async def _configure(adapter: PiccomaAdapter, page: Page, *, mode: str = "auto") -> str:
    await adapter.prepare_page(page)
    await adapter.configure_run(page, mode)  # manual CLI defaults to auto
    await adapter.configure_target_identity(f"{PRODUCT_ID}:{EPISODE_ID}", WORK_KEY)
    return adapter.resolve_initial_navigation_url(SOURCE_URL)


async def _route_fixture(
    page: Page,
    *,
    status: str = "free",
    viewer_options: dict[str, object] | None = None,
    viewer_redirect: str | None = None,
) -> dict[str, int]:
    counts = {"viewer": 0, "next_episode": 0}
    body = _synthetic_png()

    async def route_handler(route: object) -> None:
        request = route.request  # type: ignore[attr-defined]
        path = request.url.split("?", 1)[0]
        if path.startswith("https://pcm.kakaocdn.net/"):
            await route.fulfill(status=200, body=body, content_type="image/png")  # type: ignore[attr-defined]
        elif path.endswith(f"/web/product/{PRODUCT_ID}/episodes"):
            await route.fulfill(status=200, body=_listing_html(status=status), content_type="text/html; charset=utf-8")  # type: ignore[attr-defined]
        elif path.endswith(f"/web/viewer/{PRODUCT_ID}/{EPISODE_ID}"):
            counts["viewer"] += 1
            if viewer_redirect:
                await route.fulfill(
                    status=302,
                    headers={"Location": viewer_redirect},
                )  # type: ignore[attr-defined]
            else:
                await route.fulfill(
                    status=200,
                    body=_viewer_html(**(viewer_options or {})),
                    content_type="text/html; charset=utf-8",
                )  # type: ignore[attr-defined]
        elif path.startswith("https://piccoma.com/web/viewer/"):
            await route.fulfill(
                status=200,
                body=_viewer_html(**(viewer_options or {})),
                content_type="text/html; charset=utf-8",
            )  # type: ignore[attr-defined]
        else:
            await route.fulfill(status=404, body="missing")  # type: ignore[attr-defined]

    await page.route("**/*", route_handler)
    return counts


async def _start(
    adapter: PiccomaAdapter,
    page: Page,
    *,
    status: str = "free",
    viewer_options: dict[str, object] | None = None,
    viewer_redirect: str | None = None,
    mode: str = "auto",
) -> dict[str, int]:
    counts = await _route_fixture(
        page,
        status=status,
        viewer_options=viewer_options,
        viewer_redirect=viewer_redirect,
    )
    listing_url = await _configure(adapter, page, mode=mode)
    await page.goto(listing_url, wait_until="commit")
    await adapter.initialize(page)
    return counts


async def test_piccoma_auto_preflight_routes_only_exact_free_and_normalizes_to_p1(
    browser_page: Page,
) -> None:
    adapter = PiccomaAdapter()
    counts = await _start(
        adapter,
        browser_page,
        viewer_options={"initial_page": 2, "resume_dialog": True},
    )

    assert counts["viewer"] == 1
    assert browser_page.url == SOURCE_URL
    assert await adapter.detect_state(browser_page) is PageState.CONTENT
    assert await adapter.get_content_identity(browser_page) == ContentIdentity(
        page_id="p1", page_number=1, source_id=f"{PRODUCT_ID}:{EPISODE_ID}"
    )
    assert await browser_page.evaluate("window.resumeClicks") == 0
    assert await browser_page.evaluate("window.cancelClicks") == 1
    assert await browser_page.evaluate("window.forbiddenClicks") == 0


async def test_piccoma_delayed_exact_resume_prompt_is_handled_safely(
    browser_page: Page,
) -> None:
    adapter = PiccomaAdapter()
    await _start(
        adapter,
        browser_page,
        viewer_options={
            "initial_page": 2,
            "resume_dialog": True,
            "delayed_resume_ms": 250,
        },
    )

    assert await adapter._current_id(browser_page) == "p1"
    assert await browser_page.evaluate("window.cancelClicks") == 1
    assert await browser_page.evaluate("window.resumeClicks") == 0
    assert await browser_page.evaluate("window.forbiddenClicks") == 0


async def test_piccoma_exact_last_page_resume_prompt_is_cancelled_safely(
    browser_page: Page,
) -> None:
    adapter = PiccomaAdapter()
    await _start(
        adapter,
        browser_page,
        viewer_options={
            "initial_page": 3,
            "resume_dialog": True,
            "resume_variant": "last",
        },
    )

    assert await adapter._current_id(browser_page) == "p1"
    assert await browser_page.evaluate("window.cancelClicks") == 1
    assert await browser_page.evaluate("window.resumeClicks") == 0
    assert await browser_page.evaluate("window.forbiddenClicks") == 0


@pytest.mark.parametrize("resume_variant", ["mixed", "extra"])
async def test_piccoma_near_miss_last_page_resume_prompt_fails_closed(
    browser_page: Page, resume_variant: str
) -> None:
    adapter = PiccomaAdapter()
    await _route_fixture(
        browser_page,
        viewer_options={
            "resume_dialog": True,
            "resume_variant": resume_variant,
        },
    )
    listing_url = await _configure(adapter, browser_page)
    await browser_page.goto(listing_url, wait_until="commit")

    with pytest.raises(UnknownPageStateError, match="resume prompt"):
        await adapter.initialize(browser_page)
    assert await browser_page.evaluate("window.cancelClicks") == 0
    assert await browser_page.evaluate("window.resumeClicks") == 0
    assert await browser_page.evaluate("window.forbiddenClicks") == 0


@pytest.mark.parametrize("status", ["quota", "paid"])
async def test_piccoma_stale_nonfree_listing_never_enters_viewer(
    browser_page: Page, status: str
) -> None:
    adapter = PiccomaAdapter()
    counts = await _route_fixture(browser_page, status=status)
    listing_url = await _configure(adapter, browser_page, mode="direct")
    await browser_page.goto(listing_url, wait_until="commit")

    with pytest.raises(AccessResourceUnavailableError):
        await adapter.initialize(browser_page)
    assert counts["viewer"] == 0
    assert browser_page.url == listing_url


@pytest.mark.parametrize(
    "viewer_options",
    [
        {"unknown_dialog": True},
        {"omit_page": 2},
        {"duplicate_page": 2},
    ],
)
async def test_piccoma_unknown_dialog_or_incomplete_page_sequence_fails_closed(
    browser_page: Page, viewer_options: dict[str, object]
) -> None:
    adapter = PiccomaAdapter()
    adapter.page_change_timeout_ms = 100
    await _route_fixture(browser_page, viewer_options=viewer_options)
    listing_url = await _configure(adapter, browser_page)
    await browser_page.goto(listing_url, wait_until="commit")

    with pytest.raises(UnknownPageStateError):
        await adapter.initialize(browser_page)
    assert await browser_page.evaluate("window.forbiddenClicks") == 0
    assert await browser_page.evaluate("window.resumeClicks") == 0


async def test_piccoma_incomplete_active_canvas_readiness_times_out_safely(
    browser_page: Page,
) -> None:
    adapter = PiccomaAdapter()
    adapter.page_change_timeout_ms = 100
    await _route_fixture(browser_page, viewer_options={"incomplete_page": 1})
    listing_url = await _configure(adapter, browser_page)
    await browser_page.goto(listing_url, wait_until="commit")

    with pytest.raises(PageChangeTimeoutError):
        await adapter.initialize(browser_page)


@pytest.mark.parametrize(
    ("selector", "property_name", "value"),
    [
        ("#p1 canvas", "opacity", "0"),
        ("#p1", "opacity", "0"),
        ("#p1 canvas", "visibility", "hidden"),
        ("#p1 canvas", "display", "none"),
        ("#js_frame", "visibility", "hidden"),
        ("#js_frame", "display", "none"),
    ],
)
async def test_piccoma_hidden_canvas_or_ancestor_is_unknown_and_never_captured(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
    selector: str,
    property_name: str,
    value: str,
) -> None:
    adapter = PiccomaAdapter()
    await _start(adapter, browser_page)
    await browser_page.locator(selector).evaluate(
        "(node, setting) => node.style.setProperty(setting.property, setting.value)",
        {"property": property_name, "value": value},
    )

    assert await adapter.detect_state(browser_page) is PageState.UNKNOWN
    capture_calls = 0

    async def unexpected_capture(_locator: object):
        nonlocal capture_calls
        capture_calls += 1
        raise AssertionError("hidden canvas must be rejected before capture")

    monkeypatch.setattr(piccoma_adapter_module, "capture_locator", unexpected_capture)
    with pytest.raises(UnknownPageStateError, match="ready"):
        await adapter.capture_page(browser_page)
    assert capture_calls == 0


@pytest.mark.parametrize("selector", ["#p1 canvas", "#js_frame"])
async def test_piccoma_visibility_change_during_capture_fails_after_capture(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
    selector: str,
) -> None:
    adapter = PiccomaAdapter()
    await _start(adapter, browser_page)
    real_capture = piccoma_adapter_module.capture_locator

    async def hide_after_capture(locator: object):
        result = await real_capture(locator)  # type: ignore[arg-type]
        await browser_page.locator(selector).evaluate(
            "node => node.style.setProperty('opacity', '0')"
        )
        return result

    monkeypatch.setattr(piccoma_adapter_module, "capture_locator", hide_after_capture)
    with pytest.raises(UnknownPageStateError, match="changed during capture"):
        await adapter.capture_page(browser_page)


@pytest.mark.parametrize(
    ("advance_to_middle", "unexpected_page"),
    [(False, "p2"), (True, "p3"), (True, "p1")],
)
async def test_piccoma_unapproved_cursor_jump_or_rewind_is_unknown(
    browser_page: Page,
    advance_to_middle: bool,
    unexpected_page: str,
) -> None:
    adapter = PiccomaAdapter()
    await _start(adapter, browser_page)
    if advance_to_middle:
        prior = await adapter.get_content_identity(browser_page)
        await adapter.go_next(browser_page)
        await adapter.wait_for_change(browser_page, prior)
        assert adapter._expected_page_id == "p2"

    await browser_page.evaluate(
        """target => {
          for (const page of document.querySelectorAll(
            '#react_PageListApp .PCM-viewer2_pageWrapper'
          )) page.classList.toggle('current', page.id === target);
        }""",
        unexpected_page,
    )
    assert await adapter.detect_state(browser_page) is PageState.UNKNOWN
    with pytest.raises(UnknownPageStateError):
        await adapter.get_content_identity(browser_page)
    with pytest.raises(UnknownPageStateError):
        await adapter.capture_page(browser_page)


async def test_piccoma_redirect_to_wrong_composite_target_fails_closed(
    browser_page: Page,
) -> None:
    adapter = PiccomaAdapter()
    await _route_fixture(
        browser_page,
        viewer_redirect="https://piccoma.com/web/viewer/900/999",
    )
    listing_url = await _configure(adapter, browser_page)
    await browser_page.goto(listing_url, wait_until="commit")

    with pytest.raises(UnknownPageStateError, match="redirected"):
        await adapter.initialize(browser_page)
    assert browser_page.url.endswith("/web/viewer/900/999")


async def test_piccoma_steps_contiguous_pages_then_requires_explicit_end(
    browser_page: Page,
) -> None:
    adapter = PiccomaAdapter()
    await _start(adapter, browser_page)
    assert adapter._page_count == 3

    identities = []
    for number in (1, 2, 3):
        assert await adapter.detect_state(browser_page) is PageState.CONTENT
        previous = await adapter.get_content_identity(browser_page)
        identities.append(previous.page_id)
        await adapter.go_next(browser_page)
        await adapter.wait_for_change(browser_page, previous)
        if number < 3:
            assert await adapter._current_id(browser_page) == f"p{number + 1}"
        else:
            assert await adapter._current_id(browser_page) == "last"
            assert await adapter.detect_state(browser_page) is PageState.END
    assert identities == ["p1", "p2", "p3"]
    assert await browser_page.evaluate("window.forbiddenClicks") == 0


async def test_piccoma_capture_uses_core_rendered_png_and_excludes_known_guide(
    browser_page: Page,
) -> None:
    adapter = PiccomaAdapter()
    await _start(adapter, browser_page)
    await browser_page.wait_for_function("document.querySelector('#p1 canvas')?.dataset.drawn === 'true'")
    tainted = await browser_page.locator("#p1 canvas").evaluate(
        "canvas => { try { canvas.toDataURL('image/png'); return false; } catch (error) { return error.name === 'SecurityError'; } }"
    )
    assert tainted is True

    captured_display_states: list[str] = []
    real_capture = piccoma_adapter_module.capture_locator

    async def inspect_capture(locator: object):
        display = await browser_page.locator("#js_scrollTypeSing").evaluate(
            "node => getComputedStyle(node).display"
        )
        captured_display_states.append(display)
        return await real_capture(locator)  # type: ignore[arg-type]

    adapter_module_capture = piccoma_adapter_module.capture_locator
    piccoma_adapter_module.capture_locator = inspect_capture  # type: ignore[assignment]
    try:
        captures = await adapter.capture_page(browser_page)
    finally:
        piccoma_adapter_module.capture_locator = adapter_module_capture

    assert captures is not None and len(captures) == 1
    result = captures[0]
    assert result.mime_type == "image/png"
    assert result.file_extension == ".png"
    assert (result.width, result.height) == (PAGE_WIDTH, PAGE_HEIGHT)
    assert captured_display_states == ["none"]
    assert await browser_page.locator("#js_scrollTypeSing").evaluate(
        "node => getComputedStyle(node).display"
    ) != "none"
    image = Image.open(BytesIO(result.data)).convert("RGB")
    assert image.size == (PAGE_WIDTH, PAGE_HEIGHT)
    assert image.getpixel((PAGE_WIDTH // 2, PAGE_HEIGHT // 2)) == PAGE_COLOR
    assert await browser_page.evaluate("window.forbiddenClicks") == 0


async def test_piccoma_settled_known_guide_classes_remain_safe_to_exclude(
    browser_page: Page,
) -> None:
    adapter = PiccomaAdapter()
    await _start(adapter, browser_page)
    previous = await adapter.get_content_identity(browser_page)
    await adapter.go_next(browser_page)
    await adapter.wait_for_change(browser_page, previous)
    await browser_page.locator("#js_scrollTypeSing").evaluate(
        """node => {
          node.classList.remove(
            'PCM-viewer2_scrollTypeSign_sh',
            'PCM-viewer2_scrollTypeSign_show'
          );
        }"""
    )

    assert await adapter.detect_state(browser_page) is PageState.CONTENT
    captures = await adapter.capture_page(browser_page)
    assert captures is not None and len(captures) == 1
    assert captures[0].mime_type == "image/png"


@pytest.mark.parametrize(
    "mutation",
    [
        "node => node.querySelector('.PCM-viewer2_scrollTypeSign_h').append(document.createElement('button'))",
        "node => node.append(document.createTextNode('Sign in'))",
        """node => {
          const text = document.createElement('span');
          text.textContent = 'Access';
          node.append(text);
        }""",
    ],
)
async def test_piccoma_unknown_guide_structure_is_not_hidden_or_captured(
    browser_page: Page, mutation: str
) -> None:
    adapter = PiccomaAdapter()
    await _start(adapter, browser_page)
    await browser_page.locator("#js_scrollTypeSing").evaluate(mutation)

    with pytest.raises(UnknownPageStateError, match="guide"):
        await adapter.capture_page(browser_page)
    assert await browser_page.locator("#js_scrollTypeSing").evaluate(
        "node => getComputedStyle(node).display"
    ) != "none"


async def test_piccoma_work_key_is_opaque_and_quota_strategy_is_rejected(
    browser_page: Page,
) -> None:
    adapter = PiccomaAdapter()
    await adapter.configure_target_identity("900:101", WORK_KEY)
    assert adapter._work_key == WORK_KEY
    with pytest.raises(UnsupportedAccessStrategyError):
        await adapter.configure_run(browser_page, "quota")


def _piccoma_batch_setup(tmp_path: Path):
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(
        WorkInput(
            work_key=WORK_KEY,
            title="Fixture Work",
            author="Fixture Author",
            genre="Fixture Genre",
        )
    )
    item = catalog.create_item(
        ItemInput(item_title="Episode 1", order_label="Episode 1"),
        work_id=work.id,
    )
    source = catalog.create_source(
        SourceInput(
            site="piccoma",
            external_id=f"{PRODUCT_ID}:{EPISODE_ID}",
            discovery_key=PRODUCT_ID,
            access_mode="free",
            available=True,
            display_position=3,
        ),
        item_id=item.id,
    )
    target = catalog.create_source_target(
        SourceTargetInput(backend="web", locator=SOURCE_URL),
        source_id=source.id,
    )
    policies = SitePolicyRegistry()
    policies.register("piccoma", PiccomaSitePolicy)
    adapters = AdapterRegistry()
    adapters.register("piccoma", PiccomaAdapter)
    candidate = BatchPlanner(catalog, policies).plan(
        site="piccoma", now=BATCH_NOW
    ).candidates[0]
    return catalog, work, item, source, target, policies, adapters, candidate


async def test_piccoma_batch_executor_captures_manifest_packages_zip_and_completes(
    browser_page: Page, tmp_path: Path
) -> None:
    catalog, work, item, source, target, policies, adapters, candidate = (
        _piccoma_batch_setup(tmp_path)
    )
    route_counts = await _route_fixture(browser_page)
    manifest_snapshots: list[dict[str, object]] = []

    def package_with_manifest_copy(output_dir, metadata, **kwargs):
        manifest_snapshots.append(
            json.loads((Path(output_dir) / "manifest.json").read_text(encoding="utf-8"))
        )
        return package_crawl_output(output_dir, metadata, **kwargs)

    executor = BatchExecutor(
        catalog,
        policies,
        adapters,
        package_function=package_with_manifest_copy,
        runtime_settings=SiteRuntimeSettings(page_turn_delay_ms=0),
    )
    result = await executor.execute_candidate(
        browser_page,
        candidate,
        output_root=tmp_path / "batch-output",
        library_dir=tmp_path / "library",
        max_pages=3,
        now=BATCH_NOW,
    )

    assert route_counts["viewer"] == 1
    assert result.stop_reason == "end"
    assert result.page_count == 3
    assert result.archive_path.is_file()
    assert len(manifest_snapshots) == 1
    manifest = manifest_snapshots[0]
    assert manifest["source_url"] == SOURCE_URL
    assert manifest["site"] == "piccoma"
    assert manifest["content_context"]["work_id"] == WORK_KEY
    pages = manifest["pages"]
    assert [page["sequence"] for page in pages] == [1, 2, 3]
    assert [page["identity"]["page_id"] for page in pages] == ["p1", "p2", "p3"]
    assert [page["identity"]["page_number"] for page in pages] == [1, 2, 3]
    assert all(page["identity"]["source_id"] == f"{PRODUCT_ID}:{EPISODE_ID}" for page in pages)
    with ZipFile(result.archive_path) as archive:
        assert archive.namelist() == [page["file"] for page in pages]
        for page_path in archive.namelist():
            with Image.open(BytesIO(archive.read(page_path))) as image:
                assert image.size == (PAGE_WIDTH, PAGE_HEIGHT)

    updated_item = catalog.get_item(item.id)
    assert updated_item.status == "completed"
    assert updated_item.completed_at is not None
    run = catalog.get_crawl_run(result.crawl_run_id)
    assert run.status == "succeeded"
    assert run.stop_reason == "end"
    assert run.page_count == 3
    assert (run.source_id, run.target_id) == (source.id, target.id)
    artifacts = catalog.list_artifacts(crawl_run_id=result.crawl_run_id)
    assert len(artifacts) == 1
    assert artifacts[0].id == result.artifact_id
    assert (artifacts[0].format, artifacts[0].state) == ("zip", "present")
    status = json.loads(result.status_path.read_text(encoding="utf-8"))
    assert status["status"] == "completed"
    assert status["page_count"] == 3
    persisted_source = catalog.get_source(source.id)
    assert persisted_source.access_mode == "free"
    assert persisted_source.quota_started_at is None
    assert persisted_source.access_granted_until is None
    assert catalog.get_quota_resource_state(
        work.id, site="piccoma", resource="work_ticket"
    ) is None


@pytest.mark.parametrize("failure", ["stale_free", "wrong_id", "redirect"])
async def test_piccoma_batch_failures_never_package_complete_or_mutate_resources(
    browser_page: Page, tmp_path: Path, failure: str
) -> None:
    catalog, work, item, source, _target, policies, adapters, candidate = (
        _piccoma_batch_setup(tmp_path)
    )
    if failure == "stale_free":
        route_counts = await _route_fixture(browser_page, status="quota")
    elif failure == "redirect":
        route_counts = await _route_fixture(
            browser_page,
            viewer_redirect="https://piccoma.com/web/viewer/900/999",
        )
    else:
        route_counts = await _route_fixture(browser_page)
        candidate = replace(candidate, external_id="900:999")
    executor = BatchExecutor(
        catalog,
        policies,
        adapters,
        runtime_settings=SiteRuntimeSettings(page_turn_delay_ms=0),
    )

    if failure == "stale_free":
        with pytest.raises(AccessResourceUnavailableError, match="no longer unconditionally free"):
            await executor.execute_candidate(
                browser_page,
                candidate,
                output_root=tmp_path / "batch-output",
                library_dir=tmp_path / "library",
                now=BATCH_NOW,
            )
        assert route_counts["viewer"] == 0
    elif failure == "wrong_id":
        with pytest.raises(BatchExecutionError, match="stale batch candidate.*external_id"):
            await executor.execute_candidate(
                browser_page,
                candidate,
                output_root=tmp_path / "batch-output",
                library_dir=tmp_path / "library",
                now=BATCH_NOW,
            )
        assert route_counts["viewer"] == 0
    else:
        with pytest.raises(CandidateExecutionError, match="redirected outside the target episode"):
            await executor.execute_candidate(
                browser_page,
                candidate,
                output_root=tmp_path / "batch-output",
                library_dir=tmp_path / "library",
                now=BATCH_NOW,
            )
        assert route_counts["viewer"] == 1

    assert list((tmp_path / "library").rglob("*.zip")) == []
    assert catalog.get_item(item.id).status == "pending"
    assert catalog.list_artifacts(item_id=item.id) == []
    source_after = catalog.get_source(source.id)
    assert source_after.access_mode == "free"
    assert source_after.quota_started_at is None
    assert source_after.access_granted_until is None
    assert catalog.get_quota_resource_state(
        work.id, site="piccoma", resource="work_ticket"
    ) is None
    runs = catalog.list_crawl_runs()
    if failure == "wrong_id":
        assert runs == []
    else:
        assert len(runs) == 1
        assert runs[0].status == "failed"
