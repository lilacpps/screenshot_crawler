from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from urllib.parse import urlsplit
from zipfile import ZipFile

import pytest
import pytest_asyncio
from PIL import Image
from playwright.async_api import Browser, Page

from screenshot_crawler import cli
from screenshot_crawler.batch import BatchExecutor, BatchPlanner, CandidateExecutionError
from screenshot_crawler.catalog import CatalogService
from screenshot_crawler.catalog.service import now_jst
from screenshot_crawler.core.errors import (
    PageChangeTimeoutError,
    UnknownPageStateError,
    UnsupportedAccessStrategyError,
)
from screenshot_crawler.core.models import RunConfig
from screenshot_crawler.core.runner import CrawlerRunner
from screenshot_crawler.core.state import PageState
from screenshot_crawler.discovery import DiscoveryAdapterRegistry, DiscoveryService
from screenshot_crawler.runtime_settings import SiteRuntimeSettings
from screenshot_crawler.site_adapters.kadocomi import KadocomiDiscoveryAdapter
from screenshot_crawler.site_adapters.kadocomi.adapter import KadocomiAdapter
from screenshot_crawler.site_adapters.kadocomi.native_capture import (
    NATIVE_CAPTURE_SCRIPT,
    NATIVE_OBSERVER_INIT_SCRIPT,
)
from screenshot_crawler.watchlist.models import WatchlistTarget

pytestmark = pytest.mark.asyncio(loop_scope="module")

WORK_ID = "KC_004915_S"
EPISODE_ID = "KC_0049150000400011_E"
WORK_URL = f"https://comic-walker.com/detail/{WORK_ID}"
EPISODE_URL = f"{WORK_URL}/episodes/{EPISODE_ID}"
WORK_TITLE = "\u592b\u5a66\u4ee5\u4e0a\u3001\u604b\u4eba\u672a\u6e80\u3002"
EPISODE_LABEL = "\u7b2c4\u8a71\u305d\u306e1"
SITE_SUFFIX = "\uFF5C\u30AB\u30C9\u30B3\u30DF (\u30B3\u30DF\u30C3\u30AF\u30A6\u30A9\u30FC\u30AB\u30FC)"
RIFF = b"RIFF"


@pytest_asyncio.fixture(loop_scope="module")
async def browser_page(integration_browser: Browser) -> Page:
    context = await integration_browser.new_context(viewport={"width": 800, "height": 600})
    page = await context.new_page()
    try:
        yield page
    finally:
        await page.close()
        await context.close()


def _webp(color: tuple[int, int, int, int], *, width: int = 16, height: int = 12) -> bytes:
    image = Image.new("RGBA", (width, height))
    image.putdata(
        [
            (
                (color[0] + x * 3) % 256,
                (color[1] + y * 5) % 256,
                color[2],
                color[3],
            )
            for y in range(height)
            for x in range(width)
        ]
    )
    output = io.BytesIO()
    image.save(output, format="WEBP", lossless=True, exact=True)
    return output.getvalue()


def _fixture_images(count: int) -> list[bytes]:
    return [
        _webp(((index * 37 + 17) % 256, (index * 71 + 29) % 256, (index * 113 + 43) % 256, 255 - index % 80))
        for index in range(count)
    ]


def _listing_html(*, episode_id: str = EPISODE_ID, deadline: str = "2099/10/14 11:00") -> str:
    heading = f"\u3010\u7b2c1\u8a71\u3011{WORK_TITLE}"
    og_title = f"{WORK_TITLE}{SITE_SUFFIX}"
    target_href = f"/detail/{WORK_ID}/episodes/{episode_id}?co=true&episodeType=first"
    return f"""<!doctype html><html><head><meta charset="utf-8">
      <meta property="og:title" content="{og_title}"></head><body>
      <h1>{heading}</h1>
      <div class="EpisodesTabContents_root__VrJZ1">
        <button type="button">\u51681\u8a71\u3092\u8868\u793a</button>
        <ul class="EpisodesTabContents_episodeList__cIDQz"></ul>
      </div>
      <script>
        document.querySelector('button').addEventListener('click', () => {{
          document.querySelector('ul').innerHTML = `<li><a href="{target_href}">
            <span>2026/10/07</span><time>2026\u5e7410\u670807\u65e5</time>
            <div class="EpisodeThumbnail_title__G1eWj">{EPISODE_LABEL}</div>
            <span>\u914d\u4fe1\u671f\u9650\uff1a{deadline}</span>
            <time datetime="{deadline.replace('/', '-')}:00.000">{deadline}</time>
          </a></li>`;
        }});
      </script></body></html>"""


def _reader_html(
    images: list[bytes],
    *,
    include_end: bool = True,
    reverse_spread: bool = False,
    skip_to_end: bool = False,
    computed_direction: str = "ltr",
    reader_layout: str = "paired",
    mixed_fault: str | None = None,
    mixed_key_behavior: str = "advance",
    metadata_fault: str | None = None,
) -> str:
    image_data = [base64.b64encode(image).decode("ascii") for image in images]
    if reader_layout == "paired":
        pages = [
            {"images": [0]},
            {"images": [1, 2]},
            {"images": [], "end_numbers": ["1", "2"] if include_end else []},
            {"images": [], "trailing": True},
        ]
    elif reader_layout in {"mixed_final", "mixed_final_with_recommendation"}:
        mixed_slot_count = len(images) - (
            1 if mixed_fault in {"content_at_end", "content_at_recommendation"} else 0
        )
        pages = [{"images": [0]}]
        pages.extend(
            {"images": [index, index + 1]}
            for index in range(1, mixed_slot_count - 1, 2)
        )
        pages.extend(
            [
                {"images": [mixed_slot_count - 1], "end_numbers": ["2"]},
                {"images": [], "end_numbers": ["1", "2"]},
            ]
        )
        if reader_layout == "mixed_final_with_recommendation":
            pages.append({"images": [], "trailing": True})
        if mixed_fault == "missing_marker":
            pages[-2]["end_numbers"] = []
        elif mixed_fault == "moved_marker":
            pages[-3]["end_numbers"] = ["2"]
            pages[-2]["end_numbers"] = []
        elif mixed_fault == "duplicate_marker":
            pages[-2]["end_numbers"] = ["2", "2"]
        elif mixed_fault == "wrong_marker_n":
            pages[-2]["end_numbers"] = ["1"]
        elif mixed_fault == "content_at_end":
            end_page_index = -2 if reader_layout == "mixed_final_with_recommendation" else -1
            pages[end_page_index]["images"] = [mixed_slot_count]
        elif mixed_fault == "extra_slide":
            pages.append({"images": []})
        elif mixed_fault == "missing_terminal_pair":
            pages[-1]["end_numbers"] = ["2"]
        elif mixed_fault == "secondary_missing":
            pages[-1]["trailing"] = False
        elif mixed_fault == "secondary_duplicate":
            pages[-1]["trailing_count"] = 2
        elif mixed_fault == "secondary_wrong_owner":
            pages[-1]["trailing"] = False
            pages[-2]["trailing"] = True
        elif mixed_fault == "content_at_recommendation":
            pages[-1]["images"] = [mixed_slot_count]
        elif mixed_fault == "extra_after_recommendation":
            pages.append({"images": []})
        if mixed_fault == "missing_end":
            end_page_index = -2 if reader_layout == "mixed_final_with_recommendation" else -1
            pages[end_page_index - 1]["end_numbers"] = []
            pages[end_page_index]["end_numbers"] = []
    else:
        raise ValueError(f"unknown reader fixture layout: {reader_layout}")
    page_markup = []
    for index, page in enumerate(pages):
        active = " is-active" if index == 0 else ""
        canvas_markup = []
        for image_index in page["images"]:
            left = 35 if reverse_spread and len(page["images"]) == 2 and image_index % 2 == 1 else (
                350 if len(page["images"]) == 1 or image_index % 2 == 1 else 35
            )
            if reverse_spread and len(page["images"]) == 2 and image_index % 2 == 0:
                left = 350
            canvas_markup.append(
                f'<div class="_pageCanvasWrapper_k9w27_25" data-type="contents" '
                f'style="position:absolute;left:{left}px;top:30px">'
                f'<canvas class="_root_bx4cr_1" data-image="{image_index}"></canvas></div>'
            )
        marker_markup = "".join(
            '<div class="_endOfBookWrapper_k9w27_34" data-type="end-of-book" '
            f'data-n="{number}" style="position:absolute;left:{marker_index * 42}px;top:0;'
            'width:36px;height:36px"></div>'
            for marker_index, number in enumerate(page.get("end_numbers", []))
        )
        if reader_layout.startswith("mixed_final") and index == 0:
            marker_markup += (
                '<div class="_endOfBookWrapper_k9w27_34" data-type="pr" '
                'data-n="1" style="position:absolute;left:0;top:0;width:36px;height:36px"></div>'
            )
        trailing_count = page.get("trailing_count", 1 if page.get("trailing") else 0)
        trailing_markup = (
            '<a href="/detail/other-work">Related work</a>'
            + "".join(
                '<div class="_root_1w5tt_1" data-type="end">'
                '<div class="_endOfBook_1w5tt_50" data-type="end-of-book"></div></div>'
                for _ in range(trailing_count)
            )
            if trailing_count
            else ""
        )
        page_markup.append(
            f'<div class="splide__slide{active}" data-slide="{index}">'
            + "".join(canvas_markup)
            + marker_markup
            + trailing_markup
            + '<div class="_cover_bx4cr_11" data-turn="next"></div></div>'
        )
    episode_heading = f"\u3010{EPISODE_LABEL}\u3011{WORK_TITLE}"
    episode_title = f"{episode_heading}{SITE_SUFFIX}"
    if metadata_fault == "delayed":
        document_title = ""
        og_title = ""
    else:
        document_title = episode_title
        og_title = f"{episode_title} wrong" if metadata_fault == "og_mismatch" else episode_title
    heading_markup = (
        ""
        if metadata_fault in {"missing_heading", "delayed"}
        else f"<h1>{episode_heading}</h1>"
    )
    dialog_markup = (
        '<div role="dialog" style="position:fixed;inset:0;z-index:100">access</div>'
        if metadata_fault == "dialog"
        else ""
    )
    is_mixed_layout = reader_layout.startswith("mixed_final")
    mixed_end_index = len(pages) - (2 if reader_layout == "mixed_final_with_recommendation" else 1)
    mixed_final_content_index = mixed_end_index - 1
    delayed_metadata_script = (
        f"setTimeout(() => {{ document.title = {json.dumps(episode_title)}; "
        "document.querySelector('meta[property=\\\"og:title\\\"]')?.setAttribute('content', "
        f"{json.dumps(episode_title)}); const h1 = document.createElement('h1'); "
        f"h1.textContent = {json.dumps(episode_heading)}; document.body.prepend(h1); }}, 300);"
        if metadata_fault == "delayed"
        else ""
    )
    return f"""<!doctype html><html><head><meta charset="utf-8">
      <title>{document_title}</title><meta property="og:title" content="{og_title}">
      <style>
        body {{ margin:0; }}
        ._mainScreen_191o7_1 {{ position:relative;width:800px;height:600px; }}
        .splide._root_1542n_1 {{ position:absolute;left:40px;top:40px;width:700px;height:400px;direction:{computed_direction}; }}
        .splide__slide {{ position:absolute;left:0;top:0;width:700px;height:400px;visibility:hidden; }}
        .splide__slide.is-active {{ visibility:visible;z-index:2; }}
        ._root_bx4cr_1 {{ width:16px;height:12px; }}
        ._cover_bx4cr_11 {{ position:absolute;left:0;top:0;width:80px;height:100%;z-index:5; }}
      </style></head><body>
      {heading_markup}{dialog_markup}<div class="_mainScreen_191o7_1">
        <div class="splide _root_1542n_1 splide--rtl">{''.join(page_markup)}</div>
      </div>
      <script>
        const imageBytes = {json.dumps(image_data)};
        const root = document.querySelector('.splide._root_1542n_1');
        const slides = [...root.querySelectorAll('.splide__slide')];
        for (const canvas of root.querySelectorAll('._pageCanvasWrapper_k9w27_25[data-type="contents"] canvas._root_bx4cr_1')) {{
          const bytes = Uint8Array.from(atob(imageBytes[Number(canvas.dataset.image)]), c => c.charCodeAt(0));
          const blob = new Blob([bytes], {{type:'image/webp'}});
          const url = URL.createObjectURL(blob);
          const image = new Image();
          image.onload = () => {{
            canvas.width = image.naturalWidth;
            canvas.height = image.naturalHeight;
            canvas.getContext('2d').drawImage(image, 0, 0);
          }};
          image.src = url;
        }}
        root.addEventListener('click', event => {{
          if (!event.target.closest('._cover_bx4cr_11')) return;
          const index = slides.findIndex(slide => slide.classList.contains('is-active'));
          if ({str(skip_to_end).lower()} && index === 0) {{
            slides[index].classList.remove('is-active');
            slides[{2 if reader_layout == 'paired' else mixed_end_index}].classList.add('is-active');
          }} else if ({str(is_mixed_layout).lower()} && index === {mixed_final_content_index}) {{
            return;
          }} else if (index >= 0 && index + 1 < slides.length) {{
            slides[index].classList.remove('is-active');
            slides[index + 1].classList.add('is-active');
          }}
        }});
        if ({str(is_mixed_layout).lower()}) {{
          document.addEventListener('keydown', event => {{
            if (event.key !== 'ArrowLeft') return;
            const index = slides.findIndex(slide => slide.classList.contains('is-active'));
            if (index !== {mixed_final_content_index}) return;
            const behavior = {json.dumps(mixed_key_behavior)};
            if (behavior === 'advance') {{
              slides[index].classList.remove('is-active');
              slides[{mixed_end_index}].classList.add('is-active');
            }} else if (behavior === 'skip') {{
              slides[index].classList.remove('is-active');
              slides[0].classList.add('is-active');
            }}
          }});
        }}
        {delayed_metadata_script}
      </script></body></html>"""


def _native_capture_html(webp_b64: str, *, fault: str | None = None) -> str:
    transform = "context.setTransform(1,0,0,1,1,0);" if fault == "transform" else ""
    delay_array_buffer = (
        "const originalArrayBuffer = blob.arrayBuffer.bind(blob);"
        "blob.arrayBuffer = async () => { await new Promise(resolve => setTimeout(resolve, 10));"
        "context.fillRect(0,0,1,1); return originalArrayBuffer(); };"
        if fault == "mutate"
        else ""
    )
    return f"""<!doctype html><html><body>
      <div class="_mainScreen_191o7_1"><div class="splide _root_1542n_1 splide--rtl">
        <div class="splide__slide is-active"><div class="_pageCanvasWrapper_k9w27_25" data-type="contents"><canvas class="_root_bx4cr_1"></canvas></div></div>
        <div class="splide__slide"><div class="_endOfBookWrapper_k9w27_34" data-type="end-of-book" data-n="1"></div><div class="_endOfBookWrapper_k9w27_34" data-type="end-of-book" data-n="2"></div></div>
      </div></div><script>
        const bytes = Uint8Array.from(atob({json.dumps(webp_b64)}), c => c.charCodeAt(0));
        const blob = new Blob([bytes], {{type:'image/webp'}});
        const url = URL.createObjectURL(blob);
        const canvas = document.querySelector('._pageCanvasWrapper_k9w27_25[data-type="contents"] canvas._root_bx4cr_1');
        const context = canvas.getContext('2d');
        const image = new Image();
        {delay_array_buffer}
        image.onload = () => {{ canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;
          {transform}context.drawImage(image,0,0); }};
        image.src=url;
        window.__testSourceBlob = blob;
        window.__testSourceUrl = url;
        window.__testCanvas = canvas;
        window.__testContext = context;
      </script></body></html>"""


async def _install_reader_routes(
    page: Page,
    images: list[bytes],
    *,
    listed_episode_id: str = EPISODE_ID,
    deadline: str = "2099/10/14 11:00",
    redirect_foreign_episode: bool = False,
    include_end: bool = True,
    reverse_spread: bool = False,
    skip_to_end: bool = False,
    computed_direction: str = "ltr",
    reader_layout: str = "paired",
    mixed_fault: str | None = None,
    mixed_key_behavior: str = "advance",
    metadata_fault: str | None = None,
    episode_status: int = 200,
    http_error_with_viewer: bool = False,
    nonrender: bool = False,
) -> None:
    listing = _listing_html(episode_id=listed_episode_id, deadline=deadline)
    viewer = _reader_html(
        images,
        include_end=include_end,
        reverse_spread=reverse_spread,
        skip_to_end=skip_to_end,
        computed_direction=computed_direction,
        reader_layout=reader_layout,
        mixed_fault=mixed_fault,
        mixed_key_behavior=mixed_key_behavior,
        metadata_fault=metadata_fault,
    )

    async def fulfill(route) -> None:
        path = urlsplit(route.request.url).path
        if path == f"/detail/{WORK_ID}":
            await route.fulfill(status=200, body=listing, content_type="text/html; charset=utf-8")
        elif path == f"/detail/{WORK_ID}/episodes/{EPISODE_ID}":
            if redirect_foreign_episode:
                await route.fulfill(
                    status=302,
                    headers={"Location": f"/detail/{WORK_ID}/episodes/KC_0049150000400012_E"},
                )
                return
            if episode_status != 200 and not http_error_with_viewer:
                await route.fulfill(status=episode_status, body="unavailable")
                return
            if nonrender:
                episode_heading = f"\u3010{EPISODE_LABEL}\u3011{WORK_TITLE}"
                episode_title = f"{episode_heading}{SITE_SUFFIX}"
                body = (
                    "<!doctype html><html><head><title>"
                    + episode_title
                    + '</title><meta property="og:title" content="'
                    + episode_title
                    + '"></head><body><h1>'
                    + episode_heading
                    + "</h1></body></html>"
                )
                await route.fulfill(status=200, body=body, content_type="text/html; charset=utf-8")
                return
            await route.fulfill(
                status=episode_status,
                body=viewer,
                content_type="text/html; charset=utf-8",
            )
        elif path.startswith(f"/detail/{WORK_ID}/episodes/"):
            await route.fulfill(status=200, body=viewer, content_type="text/html; charset=utf-8")
        else:
            await route.fulfill(status=404, body="not found")

    await page.route("https://comic-walker.com/**", fulfill)


def _watch_main_document_requests(page: Page) -> list[str]:
    urls: list[str] = []

    def record(request) -> None:
        if (
            request.is_navigation_request()
            and request.resource_type == "document"
            and request.frame == page.main_frame
        ):
            urls.append(request.url)

    page.on("request", record)
    return urls


async def _run_native_capture_fixture(page: Page, webp: bytes, *, fault: str | None = None):
    await page.add_init_script(NATIVE_OBSERVER_INIT_SCRIPT)
    url = "https://kadocomi-native-fixture.test/reader"
    html = _native_capture_html(base64.b64encode(webp).decode("ascii"), fault=fault)

    async def fulfill(route) -> None:
        await route.fulfill(status=200, body=html, content_type="text/html; charset=utf-8")

    await page.route(url, fulfill)
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_function(
        "window.__kadocomiNativeCaptureV1?.snapshot()?.slideRows?.[0]?.contentCanvases?.[0]?.last?.complete === true"
    )
    snapshot = await page.evaluate("window.__kadocomiNativeCaptureV1.snapshot()")
    slot = snapshot["slideRows"][0]["contentSlots"][0]
    return slot


@pytest.mark.parametrize("fault", [None, "wrong_blob", "mutate", "transform"])
async def test_kadocomi_native_capture_requires_source_mapping_and_stable_full_frame(
    browser_page: Page, fault: str | None
) -> None:
    original = _webp((30, 90, 150, 177))
    wrong = _webp((190, 20, 30, 255))
    slot = await _run_native_capture_fixture(browser_page, original, fault=fault)
    if fault == "wrong_blob":
        await browser_page.evaluate(
            """wrong => {
              const entry = window.__kadocomiNativeCaptureV1.blobs.get(window.__testSourceUrl);
              entry.blob = new Blob([Uint8Array.from(atob(wrong), c => c.charCodeAt(0))], {type:'image/webp'});
              entry.size = entry.blob.size;
            }""",
            base64.b64encode(wrong).decode("ascii"),
        )
    draw_reference = await browser_page.evaluate(
        """() => {
          const last = window.__kadocomiNativeCaptureV1.draws.get(window.__testCanvas).last;
          return {sourceIsImage:last.sourceIsImage, hasImageReference:Object.hasOwn(last, 'image')};
        }"""
    )
    assert draw_reference == {"sourceIsImage": True, "hasImageReference": False}
    raw = await browser_page.evaluate(
        NATIVE_CAPTURE_SCRIPT,
        {
            "expectedSlots": [slot],
            "maxBytes": 4 * 1024 * 1024,
            "maxPixels": 20_000_000,
            "maxTotalPixels": 8_000_000,
        },
    )

    if fault is None:
        assert raw["ok"] is True
        assert base64.b64decode(raw["captures"][0]["data"]) == original
        assert raw["captures"][0]["mimeType"] == "image/webp"
    else:
        assert raw["ok"] is False
        assert raw["reason"] in {
            "pixel_mismatch_or_canvas_changed",
            "draw_state_unsupported",
            "canvas_mutated_after_image_draw",
            "canvas_or_draw_changed",
            "canvas_changed_after_async_read",
        }


@pytest.mark.parametrize("computed_direction", ["ltr", "rtl"])
@pytest.mark.parametrize(
    "reader_layout", ["paired", "mixed_final", "mixed_final_with_recommendation"]
)
async def test_kadocomi_runner_captures_right_to_left_spread_and_requires_explicit_end(
    browser_page: Page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    computed_direction: str,
    reader_layout: str,
) -> None:
    from screenshot_crawler.site_adapters.kadocomi import discovery

    monkeypatch.setattr(discovery, "SETTLEMENT_INTERVAL_MS", 5)
    monkeypatch.setattr(discovery, "SETTLEMENT_TIMEOUT_SECONDS", 1.0)
    image_count = {
        "paired": 3,
        "mixed_final": 38,
        "mixed_final_with_recommendation": 20,
    }[reader_layout]
    images = _fixture_images(image_count)
    await _install_reader_routes(
        browser_page,
        images,
        computed_direction=computed_direction,
        reader_layout=reader_layout,
    )
    main_document_urls = _watch_main_document_requests(browser_page)
    adapter = KadocomiAdapter()
    result = await CrawlerRunner(
        RunConfig(
            site="kadocomi",
            source_url=f"{EPISODE_URL}?co=true&episodeType=first",
            output_dir=tmp_path / "output",
            diagnostics_dir=tmp_path / "diagnostics",
            access_strategy="direct",
            page_turn_delay_ms=0,
            max_pages=50,
        )
    ).run(browser_page, adapter)

    assert result.stop_state is PageState.END
    assert main_document_urls == [EPISODE_URL]
    assert len(result.pages) == len(images)
    assert [page.file_extension for page in result.pages] == [".webp"] * len(images)
    assert [page.mime_type for page in result.pages] == ["image/webp"] * len(images)
    assert [(tmp_path / "output" / page.file).read_bytes() for page in result.pages] == images
    assert adapter.get_output_metadata() == {"title": WORK_TITLE, "order": EPISODE_LABEL}
    final_snapshot = await browser_page.evaluate(
        "window.__kadocomiNativeCaptureV1.snapshot()"
    )
    if reader_layout == "paired":
        assert len(final_snapshot["slideRows"]) == 4
        assert final_snapshot["activeIndex"] == 2
        assert final_snapshot["markerSlideIndexes"] == [2, 2]
        assert final_snapshot["markerNumbers"] == ["1", "2"]
        assert final_snapshot["secondaryEndMarkerSlideIndexes"] == [3]
    elif reader_layout == "mixed_final":
        assert len(final_snapshot["slideRows"]) == 21
        assert final_snapshot["activeIndex"] == 20
        assert final_snapshot["markerSlideIndexes"] == [19, 20, 20]
        assert final_snapshot["markerNumbers"] == ["2", "1", "2"]
        assert final_snapshot["secondaryEndMarkerSlideIndexes"] == []
        assert len(final_snapshot["slideRows"][19]["contentSlots"]) == 1
    else:
        assert len(final_snapshot["slideRows"]) == 13
        assert final_snapshot["activeIndex"] == 11
        assert final_snapshot["markerSlideIndexes"] == [10, 11, 11]
        assert final_snapshot["markerNumbers"] == ["2", "1", "2"]
        assert final_snapshot["secondaryEndMarkerSlideIndexes"] == [12]
        assert len(final_snapshot["slideRows"][10]["contentSlots"]) == 1
        assert final_snapshot["slideRows"][12]["active"] is False
        assert final_snapshot["endMarkerCount"] == 3
    assert final_snapshot["slideRows"][-1]["contentSlots"] == []
    assert len(list((tmp_path / "output").glob("page-*.webp"))) == len(images)


async def test_kadocomi_runner_waits_for_delayed_same_page_metadata(
    browser_page: Page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from screenshot_crawler.site_adapters.kadocomi import adapter as kadocomi_adapter

    monkeypatch.setattr(kadocomi_adapter, "METADATA_READY_TIMEOUT_SECONDS", 2.0)
    images = _fixture_images(3)
    await _install_reader_routes(browser_page, images, metadata_fault="delayed")
    main_document_urls = _watch_main_document_requests(browser_page)

    adapter = KadocomiAdapter()
    result = await CrawlerRunner(
        RunConfig(
            site="kadocomi",
            source_url=EPISODE_URL,
            output_dir=tmp_path / "output",
            diagnostics_dir=tmp_path / "diagnostics",
            access_strategy="direct",
            page_turn_delay_ms=0,
            max_pages=10,
        )
    ).run(browser_page, adapter)

    assert result.stop_state is PageState.END
    assert len(result.pages) == len(images)
    assert main_document_urls == [EPISODE_URL]
    assert adapter.get_output_metadata() == {"title": WORK_TITLE, "order": EPISODE_LABEL}


@pytest.mark.parametrize(
    "scenario",
    [
        "http_404",
        "http_500_with_viewer",
        "nonrender",
        "missing_heading",
        "og_mismatch",
        "dialog",
        "foreign_redirect",
        "missing_end",
        "reverse_spread",
        "skip_slide",
        "mixed_missing_marker",
        "mixed_moved_marker",
        "mixed_duplicate_marker",
        "mixed_wrong_marker_n",
        "mixed_content_at_end",
        "mixed_extra_slide",
        "mixed_missing_terminal_pair",
        "mixed_reverse_spread",
        "mixed_final_no_arrow",
        "mixed_rec_missing_marker",
        "mixed_rec_duplicate_marker",
        "mixed_rec_wrong_owner",
        "mixed_rec_content",
        "mixed_rec_extra_slide",
        "mixed_rec_final_no_arrow",
    ],
)
async def test_kadocomi_runner_fails_closed_without_claiming_a_complete_run(
    browser_page: Page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
) -> None:
    from screenshot_crawler.site_adapters.kadocomi import adapter as kadocomi_adapter
    from screenshot_crawler.site_adapters.kadocomi import discovery

    monkeypatch.setattr(discovery, "SETTLEMENT_INTERVAL_MS", 5)
    monkeypatch.setattr(discovery, "SETTLEMENT_TIMEOUT_SECONDS", 1.0)
    mixed = scenario.startswith("mixed_")
    mixed_rec = scenario.startswith("mixed_rec_")
    image_count = (
        21
        if scenario == "mixed_rec_content"
        else 20
        if mixed_rec
        else 39
        if scenario == "mixed_content_at_end"
        else 38
        if mixed
        else 3
    )
    images = _fixture_images(image_count)
    options: dict[str, object] = {}
    if scenario == "http_404":
        options["episode_status"] = 404
    elif scenario == "http_500_with_viewer":
        options["episode_status"] = 500
        options["http_error_with_viewer"] = True
    elif scenario == "nonrender":
        options["nonrender"] = True
    elif scenario in {"missing_heading", "og_mismatch", "dialog"}:
        options["metadata_fault"] = scenario
    elif scenario == "foreign_redirect":
        options["redirect_foreign_episode"] = True
    elif scenario == "missing_end":
        options["include_end"] = False
    elif scenario == "reverse_spread":
        options["reverse_spread"] = True
    elif scenario == "skip_slide":
        options["skip_to_end"] = True
    if mixed_rec:
        options["reader_layout"] = "mixed_final_with_recommendation"
        recommendation_faults = {
            "mixed_rec_missing_marker": "secondary_missing",
            "mixed_rec_duplicate_marker": "secondary_duplicate",
            "mixed_rec_wrong_owner": "secondary_wrong_owner",
            "mixed_rec_content": "content_at_recommendation",
            "mixed_rec_extra_slide": "extra_after_recommendation",
        }
        if scenario in recommendation_faults:
            options["mixed_fault"] = recommendation_faults[scenario]
        elif scenario == "mixed_rec_final_no_arrow":
            options["mixed_key_behavior"] = "none"
    elif mixed:
        options["reader_layout"] = "mixed_final"
        if scenario.startswith("mixed_") and scenario not in {"mixed_reverse_spread", "mixed_final_no_arrow"}:
            options["mixed_fault"] = scenario.removeprefix("mixed_")
        if scenario == "mixed_reverse_spread":
            options["reverse_spread"] = True
        elif scenario == "mixed_final_no_arrow":
            options["mixed_key_behavior"] = "none"
    await _install_reader_routes(browser_page, images, **options)
    if scenario in {"missing_end", "nonrender"}:
        monkeypatch.setattr(kadocomi_adapter, "VIEWER_READY_TIMEOUT_SECONDS", 0.2)
    if scenario in {"missing_heading", "og_mismatch", "dialog"}:
        monkeypatch.setattr(kadocomi_adapter, "METADATA_READY_TIMEOUT_SECONDS", 0.2)
    if scenario in {"mixed_final_no_arrow", "mixed_rec_final_no_arrow"}:
        monkeypatch.setattr(kadocomi_adapter, "PAGE_CHANGE_TIMEOUT_SECONDS", 2.0)
    output_dir = tmp_path / scenario / "output"
    runner = CrawlerRunner(
        RunConfig(
            site="kadocomi",
            source_url=f"{EPISODE_URL}?co=true&episodeType=first",
            output_dir=output_dir,
            diagnostics_dir=tmp_path / scenario / "diagnostics",
            access_strategy="direct",
            page_turn_delay_ms=0,
            max_pages=50,
        )
    )

    expected_error = (
        PageChangeTimeoutError
        if scenario in {"missing_end", "nonrender", "mixed_final_no_arrow", "mixed_rec_final_no_arrow"}
        else UnknownPageStateError
    )
    with pytest.raises(expected_error):
        await runner.run(browser_page, KadocomiAdapter())

    if scenario == "skip_slide":
        manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
        assert len(manifest["pages"]) == 1
        assert manifest["pages"][0]["file"] == "page-0001.webp"
        assert "status" not in manifest
        assert list(output_dir.glob("page-*.webp")) == [output_dir / "page-0001.webp"]
    elif scenario in {"mixed_final_no_arrow", "mixed_rec_final_no_arrow"}:
        manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
        assert len(manifest["pages"]) == image_count
        assert "status" not in manifest
        assert len(list(output_dir.glob("page-*.webp"))) == image_count
    else:
        assert list(output_dir.glob("page-*.webp")) == []
        assert not (output_dir / "manifest.json").exists()


async def test_kadocomi_catalog_target_requires_canonical_query_free_episode_url() -> None:
    adapter = KadocomiAdapter()
    await adapter.configure_target_identity(
        f"{WORK_ID}:{EPISODE_ID}", f"kadocomi:{WORK_ID}"
    )

    assert adapter.resolve_initial_navigation_url(EPISODE_URL) == EPISODE_URL
    with pytest.raises(UnknownPageStateError, match="canonical query-free"):
        adapter.resolve_initial_navigation_url(
            f"{EPISODE_URL}?co=true&episodeType=first"
        )


async def _seed_kadocomi_batch_candidate(
    browser_page: Page,
    tmp_path: Path,
    monkeypatch,
    *,
    reader_layout: str = "paired",
):
    from screenshot_crawler.site_adapters.kadocomi import discovery

    monkeypatch.setattr(discovery, "SETTLEMENT_INTERVAL_MS", 5)
    monkeypatch.setattr(discovery, "SETTLEMENT_TIMEOUT_SECONDS", 1.0)
    image_count = {
        "paired": 3,
        "mixed_final": 38,
        "mixed_final_with_recommendation": 20,
    }[reader_layout]
    images = _fixture_images(image_count)
    await _install_reader_routes(browser_page, images, reader_layout=reader_layout)
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    registry = DiscoveryAdapterRegistry()
    registry.register("kadocomi", KadocomiDiscoveryAdapter)
    target = WatchlistTarget(
        key="kadocomi-batch-test",
        work_key=f"kadocomi:{WORK_ID}",
        site="kadocomi",
        url=WORK_URL,
        label=WORK_TITLE,
    )
    discovery = await DiscoveryService(catalog, registry).discover(
        browser_page, target, "full"
    )
    assert discovery.complete is True and discovery.observed_count == 1

    policies = cli._batch_policy_registry()
    plan = BatchPlanner(catalog, policies).plan(site="kadocomi", now=now_jst())
    assert len(plan.candidates) == 1
    candidate = plan.candidates[0]
    assert candidate.locator == EPISODE_URL
    assert candidate.external_id == f"{WORK_ID}:{EPISODE_ID}"
    assert candidate.access_strategy == "direct"
    assert candidate.consumes_quota is False and candidate.quota_resource is None
    executor = BatchExecutor(
        catalog,
        policies,
        cli._batch_adapter_registry({}),
        runtime_settings=SiteRuntimeSettings(page_turn_delay_ms=0),
    )
    return catalog, plan, candidate, executor, images


@pytest.mark.parametrize(
    "reader_layout", ["paired", "mixed_final", "mixed_final_with_recommendation"]
)
async def test_kadocomi_batch_discovers_captures_packages_and_completes(
    browser_page: Page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reader_layout: str,
) -> None:
    catalog, _plan, candidate, executor, images = await _seed_kadocomi_batch_candidate(
        browser_page, tmp_path, monkeypatch, reader_layout=reader_layout
    )
    main_document_urls = _watch_main_document_requests(browser_page)

    result = await executor.execute_candidate(
        browser_page,
        candidate,
        output_root=tmp_path / "batch-output",
        library_dir=tmp_path / "library",
        max_pages=50,
        now=now_jst(),
    )

    item = catalog.get_item(candidate.item_id)
    source = catalog.get_source(candidate.source_id)
    run = catalog.get_crawl_run(result.crawl_run_id)
    artifacts = catalog.list_artifacts(item_id=item.id)
    work = catalog.get_work(item.work_id)
    assert result.stop_reason == "end" and result.page_count == len(images)
    assert main_document_urls == [EPISODE_URL]
    assert item.status == "completed" and item.completed_at is not None
    assert work.title == WORK_TITLE
    assert item.order_label == EPISODE_LABEL
    assert source.available is True and source.access_mode == "free"
    assert source.quota_started_at is None and source.access_granted_until is None
    assert source.display_position is None
    assert run.status == "succeeded" and run.stop_reason == "end" and run.page_count == len(images)
    assert run.locator_snapshot == EPISODE_URL
    assert run.external_id_snapshot == f"{WORK_ID}:{EPISODE_ID}"
    assert len(artifacts) == 1
    assert (artifacts[0].format, artifacts[0].state) == ("zip", "present")
    assert result.archive_path.is_file()
    assert WORK_TITLE in result.archive_path.name
    assert EPISODE_LABEL in result.archive_path.name
    with ZipFile(result.archive_path) as archive:
        members = archive.namelist()
        assert members == [f"page-{index:04d}.webp" for index in range(1, len(images) + 1)]
        assert [archive.read(member) for member in members] == images
        for member in members:
            with Image.open(io.BytesIO(archive.read(member))) as image:
                assert image.format == "WEBP"
                assert image.size == (16, 12)
    status = json.loads(result.status_path.read_text(encoding="utf-8"))
    assert status["status"] == "completed" and status["page_count"] == len(images)
    second_plan = BatchPlanner(catalog, executor.policies).plan(
        site="kadocomi", now=now_jst()
    )
    assert all(entry.item_id != item.id for entry in second_plan.candidates)
    assert any(entry.item_id == item.id and entry.reason == "completed" for entry in second_plan.skipped)


@pytest.mark.parametrize(
    "failure",
    [
        "http_404",
        "http_500_with_viewer",
        "nonrender",
        "foreign_redirect",
        "missing_end",
        "mixed_missing_marker",
        "mixed_final_no_arrow",
        "mixed_rec_final_no_arrow",
    ],
)
async def test_kadocomi_batch_runtime_failures_leave_item_pending_without_zip(
    browser_page: Page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    from screenshot_crawler.site_adapters.kadocomi import adapter as kadocomi_adapter

    catalog, _plan, candidate, executor, images = await _seed_kadocomi_batch_candidate(
        browser_page, tmp_path, monkeypatch
    )
    await browser_page.unroute_all()
    options: dict[str, object] = {}
    if failure.startswith("mixed_rec_"):
        images = _fixture_images(20)
        options["reader_layout"] = "mixed_final_with_recommendation"
    elif failure.startswith("mixed_"):
        images = _fixture_images(38)
        options["reader_layout"] = "mixed_final"
    if failure == "http_404":
        options["episode_status"] = 404
    elif failure == "http_500_with_viewer":
        options["episode_status"] = 500
        options["http_error_with_viewer"] = True
    elif failure == "nonrender":
        options["nonrender"] = True
        monkeypatch.setattr(kadocomi_adapter, "VIEWER_READY_TIMEOUT_SECONDS", 0.2)
    elif failure == "foreign_redirect":
        options["redirect_foreign_episode"] = True
    elif failure == "missing_end":
        options["include_end"] = False
        monkeypatch.setattr(kadocomi_adapter, "VIEWER_READY_TIMEOUT_SECONDS", 0.2)
    elif failure == "mixed_missing_marker":
        options["mixed_fault"] = "missing_marker"
    elif failure in {"mixed_final_no_arrow", "mixed_rec_final_no_arrow"}:
        options["mixed_key_behavior"] = "none"
        monkeypatch.setattr(kadocomi_adapter, "PAGE_CHANGE_TIMEOUT_SECONDS", 2.0)
    await _install_reader_routes(browser_page, images, **options)
    main_document_urls = _watch_main_document_requests(browser_page)

    with pytest.raises(CandidateExecutionError):
        await executor.execute_candidate(
            browser_page,
            candidate,
            output_root=tmp_path / "batch-output",
            library_dir=tmp_path / "library",
            max_pages=50,
            now=now_jst(),
        )

    item = catalog.get_item(candidate.item_id)
    assert item.status == "pending" and item.completed_at is None
    assert catalog.list_artifacts(item_id=item.id) == []
    runs = catalog.list_crawl_runs(item_id=item.id)
    assert len(runs) == 1 and runs[0].status == "failed"
    assert list((tmp_path / "library").rglob("*.zip")) == []
    expected_navigation_paths = (
        [EPISODE_URL, f"{WORK_URL}/episodes/KC_0049150000400012_E"]
        if failure == "foreign_redirect"
        else [EPISODE_URL]
    )
    assert main_document_urls == expected_navigation_paths


async def test_kadocomi_adapter_rejects_auto_quota_and_locator_fallback(browser_page: Page) -> None:
    adapter = KadocomiAdapter()
    with pytest.raises(UnsupportedAccessStrategyError):
        await adapter.configure_run(browser_page, "auto")
    with pytest.raises(UnsupportedAccessStrategyError):
        await adapter.configure_run(browser_page, "quota")
    with pytest.raises(UnsupportedAccessStrategyError):
        await adapter.configure_quota_resource(browser_page, "ticket")
    with pytest.raises(UnknownPageStateError, match="screenshot fallback"):
        await adapter.get_capture_targets(browser_page)
