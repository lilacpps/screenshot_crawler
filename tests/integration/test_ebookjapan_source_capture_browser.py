from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest
import pytest_asyncio
from PIL import Image, ImageDraw
from playwright.async_api import Browser, Page

from screenshot_crawler.core.capture import CaptureResult
from screenshot_crawler.core.errors import UnknownPageStateError
from screenshot_crawler.core.models import RunConfig
from screenshot_crawler.core.packaging import package_crawl_output
from screenshot_crawler.core.runner import CrawlerRunner
from screenshot_crawler.site_adapters.ebookjapan.adapter import EbookJapanAdapter
from screenshot_crawler.site_adapters.ebookjapan.source_capture import SourceResearchOutcome

pytestmark = pytest.mark.asyncio(loop_scope="module")

SERIES_ID = "134336"
PRODUCT_ID = "A000083590"
PRODUCT_URL = f"https://ebookjapan.yahoo.co.jp/books/{SERIES_ID}/{PRODUCT_ID}/"
LISTING_URL = f"https://ebookjapan.yahoo.co.jp/books/all/{SERIES_ID}/"
READER_URL = "https://ebookjapan.yahoo.co.jp/viewer/purchased/B123456789012/"
CACHE_SOURCE_HOST = "cache2-ebookjapan.akamaized.net"
PRODUCTION_SOURCE_HOST = "prod-contents-br-page.akamaized.net"
SOURCE_URL = f"https://{CACHE_SOURCE_HOST}/generated-c2-fixture.webp?fixture=roi-proof"
SOURCE_WIDTH = 1088
SOURCE_HEIGHT = 1600
ROIS_X = 16
ROIS_Y = 16


@pytest_asyncio.fixture(loop_scope="module")
async def c2_browser(integration_browser: Browser) -> Page:
    context = await integration_browser.new_context(
        viewport={"width": 1906, "height": 986},
        device_scale_factor=1,
    )
    page = await context.new_page()
    try:
        yield page
    finally:
        await page.close()
        await context.close()


@pytest_asyncio.fixture(loop_scope="module")
async def isolated_runner_page(integration_browser: Browser) -> Page:
    context = await integration_browser.new_context(
        viewport={"width": 1906, "height": 986},
        device_scale_factor=1,
    )
    page = await context.new_page()
    try:
        yield page
    finally:
        await page.close()
        await context.close()


def _generated_vp8_webp() -> bytes:
    image = Image.new("RGB", (SOURCE_WIDTH, SOURCE_HEIGHT), "white")
    draw = ImageDraw.Draw(image)
    roi_width = SOURCE_WIDTH // ROIS_X
    roi_height = SOURCE_HEIGHT // ROIS_Y
    for row in range(ROIS_Y):
        for column in range(ROIS_X):
            color = (
                (column * 29 + row * 7 + 11) % 240,
                (row * 31 + column * 5 + 17) % 240,
                (column * 13 + row * 19 + 23) % 240,
            )
            x0, y0 = column * roi_width, row * roi_height
            draw.rectangle(
                (x0, y0, x0 + roi_width - 1, y0 + roi_height - 1),
                fill=color,
            )
    output = io.BytesIO()
    image.save(output, format="WEBP", lossless=False, quality=100, method=4)
    encoded = output.getvalue()
    assert encoded[12:16] == b"VP8 "
    return encoded


def _listing_html() -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8"></head><body>
      <header class="page-books-all__list-header">
        <span class="search-header__result">全1冊</span>
        <label class="search-filter__item"><input type="radio" checked>1巻から</label>
      </header>
      <div class="account__user"><a href="/mypage/">fixture-account</a></div>
      <h1 class="page-books-all__heading">Generated Fixture Work</h1>
      <ul><li class="book-list__item">
        <a class="book-item" href="/books/{SERIES_ID}/{PRODUCT_ID}/">
          <span class="book-caption__title">生成作品 2巻</span>
        </a>
        <span class="book-caption__tagtext">購入済み</span>
        <button class="icon-btn-wrapper__btn icon-btn"><span class="font-read">読む</span></button>
      </li></ul>
      <script>document.querySelector('button.icon-btn').addEventListener('click',()=>location.href='{READER_URL}');</script>
    </body></html>"""


def _reader_html(
    *,
    clip_source: bool = False,
    clip_second_source: bool = False,
    source_url: str = SOURCE_URL,
) -> str:
    clip_statement = (
        "context.beginPath();context.rect(0,0,1088,1600);context.clip();"
        if clip_source
        else ""
    )
    clip_second_statement = (
        "context.beginPath();context.rect(0,0,1088,1600);context.clip();"
        if clip_second_source
        else ""
    )
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
      html,body{{margin:0;width:100%;height:100%;overflow:hidden}}
      .legacy-comic-header,.legacy-comic-footer{{position:fixed;left:0;width:200px;height:24px;z-index:20;background:#ddd}}
      .legacy-comic-header{{top:0}} .legacy-comic-footer{{bottom:0}}
      .comic-viewer__scroll-container{{position:fixed;inset:0;direction:rtl}}
      .comic-viewer__page-slot{{position:fixed;top:0;left:0;width:50vw;height:100vh}}
      .comic-viewer__page-slot[data-page="2"]{{left:50vw}}
      .comic-viewer__page-slot[hidden]{{display:none}}
      .page-canvas{{position:absolute;right:0;width:auto;height:100%;display:block}}
      .seekbar__slider{{position:fixed;left:20px;bottom:20px;width:200px;z-index:30}}
      </style></head><body>
      <header class="legacy-comic-header"><span class="legacy-comic-header__title">生成作品(2)</span></header>
      <footer class="legacy-comic-footer"><span class="legacy-comic-footer__page-output">2 / 2</span></footer>
      <div class="comic-viewer__scroll-container comic-viewer__scroll-container--horizontal-rtl comic-viewer__scroll-container--spread">
        <div class="comic-viewer__page-slot" data-page="1">
          <canvas class="page-canvas" width="300" height="150"></canvas>
        </div>
        <div class="comic-viewer__page-slot" data-page="2">
          <canvas class="page-canvas" width="300" height="150"></canvas>
        </div>
      </div>
      <input class="seekbar__slider" type="range" min="0" max="1" value="1">
      <script>
      const sourceUrl={json.dumps(source_url)};
      const htmlContextPrototype=CanvasRenderingContext2D.prototype;
      const arcDescriptor=Object.getOwnPropertyDescriptor(htmlContextPrototype,'arc');
      Object.defineProperty(htmlContextPrototype,'arc',{{...arcDescriptor,value:function fixtureLateArc(){{}}}});
      const imageDataDescriptor=Object.getOwnPropertyDescriptor(htmlContextPrototype,'getImageData');
      Object.defineProperty(htmlContextPrototype,'getImageData',{{...imageDataDescriptor,value:undefined}});
      window.__fixtureDrawComplete=false;
      window.__fixtureSources=[];
      const image=new Image();window.__fixtureImage=image;image.src=sourceUrl;
      const drawCanvas=(canvas,partIndex)=>{{
        canvas.width={SOURCE_WIDTH};canvas.height={SOURCE_HEIGHT};
        const offscreen=new OffscreenCanvas({SOURCE_WIDTH},{SOURCE_HEIGHT});
        window.__fixtureSources.push(offscreen);
        const context=offscreen.getContext('2d');
        {clip_statement}
        if(partIndex===1){{{clip_second_statement}}}
        for(let row=0;row<{ROIS_Y};row++)for(let column=0;column<{ROIS_X};column++){{
          const sx=column*{SOURCE_WIDTH // ROIS_X},sy=row*{SOURCE_HEIGHT // ROIS_Y};
          context.drawImage(image,sx,sy,{SOURCE_WIDTH // ROIS_X},{SOURCE_HEIGHT // ROIS_Y},
            sx,sy,{SOURCE_WIDTH // ROIS_X},{SOURCE_HEIGHT // ROIS_Y});
        }}
        const bitmap=offscreen.transferToImageBitmap();
        canvas.getContext('2d').drawImage(bitmap,0,0);
      }};
      image.decode().then(()=>{{
        for(const [index,canvas] of [...document.querySelectorAll('.page-canvas')].entries())drawCanvas(canvas,index);
        window.__fixtureDrawComplete=true;
      }}).catch(error=>window.__fixtureError=String(error?.name||'decode-failed'));
      document.addEventListener('keydown',event=>{{
        if(event.key!=='End')return;
        document.querySelector('.seekbar__slider').value='0';
        document.querySelector('.legacy-comic-footer__page-output').textContent='1 / 2';
        document.querySelectorAll('.comic-viewer__page-slot')[0].hidden=false;
        document.querySelectorAll('.comic-viewer__page-slot')[1].hidden=true;
      }});
      document.addEventListener('click',event=>{{
        if(!(event.target instanceof HTMLCanvasElement))return;
        document.querySelector('.legacy-comic-header').hidden=true;
        document.querySelector('.legacy-comic-footer').hidden=true;
        document.querySelector('.seekbar__slider').style.display='none';
      }});
      </script>
    </body></html>"""


def _runner_end_reader_html(
    source_url: str = SOURCE_URL,
    *,
    clip_source: bool = False,
) -> str:
    reader_title = _reader_html().split(
        '<span class="legacy-comic-header__title">', 1
    )[1].split("</span>", 1)[0]
    clip_statement = (
        "context.beginPath();context.rect(0,0,1088,1600);context.clip();"
        if clip_source
        else ""
    )
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
      html,body{{margin:0;width:100%;height:100%;overflow:hidden}}
      .comic-viewer__scroll-container{{position:fixed;inset:0;direction:rtl}}
      .comic-viewer__page-slot{{position:fixed;top:0;left:0;width:50vw;height:100vh}}
      .page-canvas{{position:absolute;right:0;width:auto;height:100%;display:block}}
      .legacy-comic-header,.legacy-comic-footer{{position:fixed;left:0;width:100%;height:24px;z-index:20;background:#ddd}}
      .legacy-comic-header{{top:0}} .legacy-comic-footer{{bottom:0}}
      .book-last{{position:fixed;left:30vw;top:80px;width:40vw;height:1400px;overflow:auto;background:#eee}}
      </style></head><body><div class="comic-viewer">
      <header class="legacy-comic-header">
        <span class="legacy-comic-header__title">{reader_title}</span>
        <div class="legacy-comic-header__bar"><button class="close-button">Close</button>
          <div class="legacy-comic-header__menu legacy-comic-header__menu--pc">
            <button class="contents-button">Contents</button><button class="settings-button">Settings</button>
          </div>
        </div>
      </header>
      <footer class="legacy-comic-footer"><span class="legacy-comic-footer__page-output">1 / 1</span></footer>
      <div class="comic-viewer__scroll-container comic-viewer__scroll-container--horizontal-rtl comic-viewer__scroll-container--spread">
        <div class="comic-viewer__page-slot" data-page="1"><canvas class="page-canvas" width="300" height="150"></canvas></div>
        <div class="comic-viewer__custom-cell comic-viewer__custom-cell--interactive" style="display:none">
          <div class="viewer-liber__viewer-last-cell"><div class="viewer-last-shell" style="display:none">
            <div class="book-last"><div class="book-last__inner">
              <div class="review-module book-last__review"><button class="review-module__action">Review</button></div>
              <div class="next-item book-last__next"><div class="next-item__outline"><button class="next-item__rating">Rate</button></div></div>
              <div class="cta-button book-last__cta"><div class="cta-button__row"><div class="cta-button__primary"><button class="cta-button__read-btn">Read</button></div></div></div>
              <div class="banner-group book-last__banner-group"><button class="banner__row--lottery">Lottery</button><button class="banner__row--line-coupon">Coupon</button></div>
              <section class="recommend-grid book-last__i2i"><ul class="recommend-grid__list"><li class="recommend-grid__item"><a class="recommend-grid__link" href="/books/134336/A000000001/">Related</a></li></ul></section>
              <section class="recommend-grid book-last__author"><a class="recommend-grid__heading recommend-grid__heading--more" href="/books/134336/A000000004/">More</a><ul class="recommend-grid__list"><li class="recommend-grid__item"><a class="recommend-grid__link" href="/books/134336/A000000002/">Related</a></li></ul></section>
              <section class="recommend-grid book-last__for-you"><ul class="recommend-grid__list"><li class="recommend-grid__item"><a class="recommend-grid__link" href="/books/134336/A000000003/">Related</a></li></ul></section>
            </div></div></div></div>
        </div>
      </div>
      <input class="seekbar__slider" type="range" min="0" max="0" value="0">
      <script>
      const sourceUrl={json.dumps(source_url)};
      const htmlContextPrototype=CanvasRenderingContext2D.prototype;
      const arcDescriptor=Object.getOwnPropertyDescriptor(htmlContextPrototype,'arc');
      Object.defineProperty(htmlContextPrototype,'arc',{{...arcDescriptor,value:function fixtureLateArc(){{}}}});
      const imageDataDescriptor=Object.getOwnPropertyDescriptor(htmlContextPrototype,'getImageData');
      Object.defineProperty(htmlContextPrototype,'getImageData',{{...imageDataDescriptor,value:undefined}});
      const image=new Image();window.__fixtureImage=image;image.src=sourceUrl;
      window.__fixtureSources=[];window.__fixtureDrawComplete=false;
      image.decode().then(()=>{{
        const canvas=document.querySelector('.page-canvas');
        canvas.width={SOURCE_WIDTH};canvas.height={SOURCE_HEIGHT};
        const offscreen=new OffscreenCanvas({SOURCE_WIDTH},{SOURCE_HEIGHT});window.__fixtureSources.push(offscreen);
        const context=offscreen.getContext('2d');
        {clip_statement}
        for(let row=0;row<{ROIS_Y};row++)for(let column=0;column<{ROIS_X};column++){{
          const sx=column*{SOURCE_WIDTH // ROIS_X},sy=row*{SOURCE_HEIGHT // ROIS_Y};
          context.drawImage(image,sx,sy,{SOURCE_WIDTH // ROIS_X},{SOURCE_HEIGHT // ROIS_Y},sx,sy,{SOURCE_WIDTH // ROIS_X},{SOURCE_HEIGHT // ROIS_Y});
        }}
        const bitmap=offscreen.transferToImageBitmap();canvas.getContext('2d').drawImage(bitmap,0,0);
        window.__fixtureDrawComplete=true;
      }}).catch(error=>window.__fixtureError=String(error?.name||'decode-failed'));
      document.addEventListener('keydown',event=>{{if(event.key==='End')document.querySelector('.legacy-comic-footer__page-output').textContent='1 / 1';}});
      document.addEventListener('click',event=>{{
        if(!(event.target instanceof HTMLCanvasElement))return;
        const header=document.querySelector('.legacy-comic-header'),footer=document.querySelector('.legacy-comic-footer');
        if(!window.__fixtureToolbarHidden){{
          window.__fixtureToolbarHidden=true;header.hidden=true;footer.hidden=true;
          document.querySelector('.seekbar__slider').style.display='none';return;
        }}
        if(event.clientX<=16){{
          document.querySelector('.comic-viewer__page-slot').hidden=true;
          document.querySelector('.comic-viewer__custom-cell--interactive').style.display='block';
          document.querySelector('.viewer-last-shell').style.display='block';
          header.hidden=false;footer.hidden=true;
        }}
      }});
      </script></div></body></html>"""


async def _open_owned_reader(
    page: Page,
    webp_bytes: bytes,
    *,
    clip_source: bool = False,
    clip_second_source: bool = False,
    source_host: str = CACHE_SOURCE_HOST,
) -> EbookJapanAdapter:
    # Model only the exact v3 profile admitted for comparison. This is a local
    # generated fixture and does not restore or call the hidden methods.
    await page.add_init_script(
        """(()=>{
          const canvas=new OffscreenCanvas(1,1),prototype=Object.getPrototypeOf(canvas.getContext('2d'));
          Object.defineProperty(prototype,'getImageData',{configurable:true,writable:true,value:undefined});
          Object.defineProperty(prototype,'arc',{configurable:true,writable:true,value:function fixtureArc(){}});
          Object.defineProperty(prototype,'fixturePrivateCallable',{configurable:true,writable:true,enumerable:true,value:function fixturePrivateCallable(){}});
        })()"""
    )
    adapter = EbookJapanAdapter()
    resolved = adapter.resolve_initial_navigation_url(PRODUCT_URL)
    assert resolved == LISTING_URL
    await adapter.configure_target_identity(PRODUCT_ID, "generated-work")
    await adapter.configure_run(page, "direct")
    await adapter.prepare_page(page)
    source_url = f"https://{source_host}/generated-c2-fixture.webp?fixture=roi-proof"
    await page.route(
        LISTING_URL,
        lambda route: route.fulfill(
            status=200,
            content_type="text/html",
            body=_listing_html(),
        ),
    )
    await page.route(
        "https://ebookjapan.yahoo.co.jp/viewer/purchased/**",
        lambda route: route.fulfill(
            status=200,
            content_type="text/html",
            body=_reader_html(
                clip_source=clip_source,
                clip_second_source=clip_second_source,
                source_url=source_url,
            ),
        ),
    )
    await page.route(
        f"https://{source_host}/generated-c2-fixture.webp**",
        lambda route: route.fulfill(
            status=200,
            content_type="image/webp",
            headers={"cache-control": "no-store"},
            body=webp_bytes,
        ),
    )
    await page.goto(resolved)
    await adapter.initialize(page)
    assert adapter._reader_title == "生成作品(2)"
    assert adapter._owned_title == "生成作品 2巻"
    await page.wait_for_function("window.__fixtureDrawComplete===true", timeout=15_000)
    return adapter


@pytest.mark.parametrize(
    "source_host",
    [CACHE_SOURCE_HOST, PRODUCTION_SOURCE_HOST],
    ids=("observed-cache-host", "observed-production-host"),
)
async def test_generated_title_alias_rewind_and_source_roi_comparison(
    c2_browser: Page,
    source_host: str,
) -> None:
    webp_bytes = _generated_vp8_webp()
    source_url = f"https://{source_host}/generated-c2-fixture.webp?fixture=roi-proof"
    adapter = await _open_owned_reader(c2_browser, webp_bytes, source_host=source_host)
    identity = await adapter.get_content_identity(c2_browser)
    assert identity.source_id == PRODUCT_ID
    assert adapter._expected_current == 1
    assert await c2_browser.locator(".legacy-comic-footer__page-output").inner_text() == "1 / 2"

    outcome = await adapter._research_compare_source_capture(c2_browser)
    projection = outcome.safe_projection()
    projected_json = json.dumps(projection, sort_keys=True)

    assert outcome.status == "C_VERIFIED", projection
    assert len(outcome.captures) == 1
    assert outcome.fallback_captures == ()
    assert projection["capture_method"] == "C_source_roi_lossless"
    assert projection["capture_policy_revision"] == "ebookjapan-owned-source-roi-v1-20261109"
    assert projection["provenance"] == "VERIFIED_SOURCE_ROI"
    assert projection["runtime_adoption_status"] == "NOT_ADOPTED"
    assert projection["paint_history_complete"] is False
    assert source_url not in projected_json
    assert "fixturePrivateCallable" not in projected_json
    assert "生成作品" not in projected_json

    part = projection["parts"][0]
    assert part["source_format"] == "VP8 "
    assert part["source_width"] == SOURCE_WIDTH
    assert part["source_height"] == SOURCE_HEIGHT
    assert part["roi_count"] == ROIS_X * ROIS_Y == 256
    assert len(part["roi_six_integer_rows"]) == 256
    assert part["source_response"]["status"] == 200
    assert part["source_response"]["redirected"] is False
    assert part["source_response"]["request_response_identity_matches"] is True
    assert part["source_response"]["current_document_matches"] is True
    assert part["source_response"]["current_src_matches"] is True
    assert part["d_reference_pair_exact"] is True
    assert part["max_rgb_delta_by_channel"] <= [2, 2, 2]
    assert part["alpha_mismatch_pixels"] == 0
    assert part["dimensions_exact"] is True
    assert part["output_roundtrip_exact"] is True
    assert part["source_encoded_sha256"] == hashlib.sha256(webp_bytes).hexdigest()
    assert (outcome.captures[0].width, outcome.captures[0].height) == (
        SOURCE_WIDTH,
        SOURCE_HEIGHT,
    )


async def test_source_clip_keeps_the_complete_capture_on_d(c2_browser: Page) -> None:
    adapter = await _open_owned_reader(
        c2_browser,
        _generated_vp8_webp(),
        clip_source=True,
    )
    await adapter.get_content_identity(c2_browser)

    outcome = await adapter._research_compare_source_capture(c2_browser)

    assert outcome.status == "D_FALLBACK"
    assert outcome.failure_reason == "source-paint-state-unsupported"
    assert len(outcome.captures) == len(outcome.fallback_captures) == 1
    assert outcome.parts == ()
    assert outcome.safe_projection()["provenance"] == "NOT_ESTABLISHED"


async def test_public_capture_adopts_only_the_complete_verified_source_spread(
    c2_browser: Page,
) -> None:
    webp_bytes = _generated_vp8_webp()
    adapter = await _open_owned_reader(c2_browser, webp_bytes)
    await adapter.get_content_identity(c2_browser)

    captures = await adapter.capture_page(c2_browser)
    metadata = await adapter.collect_debug_metadata(c2_browser)
    serialized = json.dumps(metadata, sort_keys=True)

    assert captures is not None and len(captures) == 1
    assert captures[0].mime_type == "image/webp"
    assert captures[0].file_extension == ".webp"
    assert (captures[0].width, captures[0].height) == (SOURCE_WIDTH, SOURCE_HEIGHT)
    assert metadata["capture_method"] == "C_source_roi_lossless"
    assert metadata["capture_class"] == "C"
    assert metadata["ebookjapan_capture_policy_revision"] == "ebookjapan-owned-source-roi-v1-20261109"
    assert metadata["ebookjapan_source_provenance"] == "VERIFIED_SOURCE_ROI"
    assert metadata["ebookjapan_native_page_number"] is None
    attempt = metadata["ebookjapan_source_capture_attempt"]
    assert attempt["status"] == "C_VERIFIED"
    assert attempt["failure_reason_code"] is None
    assert attempt["runtime_adoption_status"] == "ADOPTED_CONDITIONAL"
    assert attempt["paint_history_complete"] is False
    assert attempt["proof_basis"] == "source-lineage+fullpixelcompare"
    part = metadata["ebookjapan_capture_parts"][0]
    assert part["capture_class"] == "C"
    assert part["source_provenance"] == "VERIFIED_SOURCE_ROI"
    assert part["source_roi_proof"]["roi_count"] == 256
    assert part["source_roi_proof"]["runtime_adoption_status"] == "ADOPTED_CONDITIONAL"
    assert part["source_roi_proof"]["proof_basis"] == "source-lineage+fullpixelcompare"
    assert part["source_roi_proof"]["source_encoded_sha256"] == hashlib.sha256(webp_bytes).hexdigest()
    assert part["source_roi_proof"]["d_reference_pair_exact"] is True
    assert part["source_roi_proof"]["alpha_mismatch_pixels"] == 0
    assert "compositor_pixel_sha256" in part
    assert "output_rgba_sha256" in part["source_roi_proof"]
    assert SOURCE_URL not in serialized
    assert "fixturePrivateCallable" not in serialized
    assert "逕滓・菴懷刀" not in serialized


@pytest.mark.parametrize(
    "clip_second_source",
    [False, True],
    ids=("two-part-C-atomic", "one-part-failure-whole-D"),
)
async def test_public_capture_keeps_two_part_source_spread_atomic(
    c2_browser: Page,
    clip_second_source: bool,
) -> None:
    adapter = await _open_owned_reader(
        c2_browser,
        _generated_vp8_webp(),
        clip_second_source=clip_second_source,
    )
    await c2_browser.evaluate(
        """()=>{
          const slots=[...document.querySelectorAll('.comic-viewer__page-slot')];
          slots.forEach(slot=>{slot.hidden=false;slot.style.display='block';});
          document.querySelector('.legacy-comic-footer__page-output').textContent='2 / 2';
          document.querySelector('.seekbar__slider').value='0';
              document.querySelector('.legacy-comic-header').hidden=true;
              document.querySelector('.legacy-comic-footer').hidden=true;
              document.querySelector('.seekbar__slider').style.display='none';
        }"""
    )
    adapter._expected_current = 2
    identity = await adapter.get_content_identity(c2_browser)
    assert identity.page_id.endswith("slots:2,1")
    frame = await adapter._read_ready_frame(
        c2_browser,
        expected_path=adapter._reader_path or "",
        current=2,
        total=2,
    )
    parts = frame.get("parts")
    assert isinstance(parts, list) and len(parts) == 2 and isinstance(parts[0], dict)
    # Model the post-cover sequence cursor so this local fixture can isolate
    # atomic spread output without also exercising the separate navigation test.
    adapter._next_dom_ordinal = parts[0]["slotOrdinal"]

    captures = await adapter.capture_page(c2_browser)
    metadata = await adapter.collect_debug_metadata(c2_browser)

    assert captures is not None and len(captures) == 2
    if clip_second_source:
        assert all(capture.mime_type == "image/png" for capture in captures)
        assert metadata["capture_method"] == "D_compositor_png"
        assert metadata["ebookjapan_source_capture_attempt"]["status"] == "D_FALLBACK"
        assert metadata["ebookjapan_source_capture_attempt"]["failure_reason_code"] == "source-paint-state-unsupported"
        assert all("source_roi_proof" not in part for part in metadata["ebookjapan_capture_parts"])
    else:
        assert all(capture.mime_type == "image/webp" for capture in captures)
        assert metadata["capture_method"] == "C_source_roi_lossless"
        proofs = [part["source_roi_proof"] for part in metadata["ebookjapan_capture_parts"]]
        assert [proof["part_index"] for proof in proofs] == [0, 1]
        assert all(proof["d_reference_pair_exact"] for proof in proofs)
        assert all(proof["output_roundtrip_exact"] for proof in proofs)
        assert proofs[0]["target_canvas_object_id"] != proofs[1]["target_canvas_object_id"]
        assert proofs[0]["source_canvas_object_id"] != proofs[1]["source_canvas_object_id"]


async def test_public_capture_source_proof_failure_returns_fresh_d_without_c_proof(
    c2_browser: Page,
) -> None:
    adapter = await _open_owned_reader(
        c2_browser,
        _generated_vp8_webp(),
        clip_source=True,
    )
    await adapter.get_content_identity(c2_browser)

    captures = await adapter.capture_page(c2_browser)
    metadata = await adapter.collect_debug_metadata(c2_browser)

    assert captures is not None and len(captures) == 1
    assert captures[0].mime_type == "image/png"
    assert captures[0].file_extension == ".png"
    assert metadata["capture_method"] == "D_compositor_png"
    assert metadata["capture_class"] == "D"
    assert metadata["ebookjapan_capture_policy_revision"] == "ebookjapan-owned-rendered-png-v1-20261108"
    assert metadata["ebookjapan_source_provenance"] == "UNKNOWN"
    assert metadata["fallback_reason_code"] == "SOURCE_NATIVE_PROOF_NOT_ESTABLISHED"
    attempt = metadata["ebookjapan_source_capture_attempt"]
    assert attempt["status"] == "D_FALLBACK"
    assert attempt["failure_reason_code"] == "source-paint-state-unsupported"
    assert attempt["runtime_adoption_status"] == "NOT_APPLIED"
    assert "source_roi_proof" not in metadata["ebookjapan_capture_parts"][0]
    assert metadata["ebookjapan_capture_parts"][0]["capture_class"] == "D"


async def test_next_d_fallback_clears_previous_c_part_projection(
    c2_browser: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = await _open_owned_reader(c2_browser, _generated_vp8_webp())
    await adapter.get_content_identity(c2_browser)
    c_capture = await adapter.capture_page(c2_browser)
    assert c_capture is not None and c_capture[0].mime_type == "image/webp"

    d_capture = CaptureResult(
        data=b"generated-D-fallback",
        width=SOURCE_WIDTH,
        height=SOURCE_HEIGHT,
    )

    async def fresh_d_fallback(_page: Page) -> SourceResearchOutcome:
        return SourceResearchOutcome(
            status="D_FALLBACK",
            failure_reason="source-paint-state-unsupported",
            limited_history_profile="v3-install-unknown-callable-1",
            paint_history_complete=False,
            parts=(),
            captures=(d_capture,),
            fallback_captures=(d_capture,),
        )

    monkeypatch.setattr(adapter, "_research_compare_source_capture", fresh_d_fallback)
    captures = await adapter.capture_page(c2_browser)
    metadata = await adapter.collect_debug_metadata(c2_browser)

    assert captures == (d_capture,)
    assert metadata["capture_method"] == "D_compositor_png"
    assert metadata["capture_class"] == "D"
    assert metadata["ebookjapan_capture_parts"][0]["capture_class"] == "D"
    assert metadata["ebookjapan_capture_parts"][0]["source_provenance"] == "UNKNOWN"
    assert "source_roi_proof" not in metadata["ebookjapan_capture_parts"][0]
    assert metadata["ebookjapan_source_capture_attempt"]["failure_reason_code"] == "source-paint-state-unsupported"


async def test_fatal_before_new_d_capture_does_not_emit_previous_c_proof(
    c2_browser: Page,
) -> None:
    adapter = await _open_owned_reader(c2_browser, _generated_vp8_webp())
    await adapter.get_content_identity(c2_browser)
    captures = await adapter.capture_page(c2_browser)
    assert captures is not None and captures[0].mime_type == "image/webp"

    with pytest.raises(UnknownPageStateError, match="identity was not read"):
        await adapter.capture_page(c2_browser)

    metadata = await adapter.collect_debug_metadata(c2_browser)
    assert metadata["capture_method"] == "D_compositor_png"
    assert metadata["capture_class"] == "D"
    assert metadata["ebookjapan_source_provenance"] == "UNKNOWN"
    assert all(
        "source_roi_proof" not in part and part["capture_class"] == "D"
        for part in metadata["ebookjapan_capture_parts"]
    )


@pytest.mark.parametrize("clip_source", [False, True], ids=("verified-C", "proof-unavailable-D"))
async def test_core_runner_manifest_and_zip_keep_one_complete_capture(
    isolated_runner_page: Page,
    tmp_path: Path,
    clip_source: bool,
) -> None:
    webp_bytes = _generated_vp8_webp()
    source_url = f"https://{PRODUCTION_SOURCE_HOST}/generated-c2-fixture.webp?fixture=runner-proof"
    source_requests: list[str] = []
    unexpected_requests: list[str] = []

    async def route_owned_fixture(route) -> None:
        url = route.request.url
        if url == LISTING_URL:
            await route.fulfill(status=200, content_type="text/html; charset=utf-8", body=_listing_html())
        elif url == READER_URL:
            await route.fulfill(
                status=200,
                content_type="text/html; charset=utf-8",
                body=_runner_end_reader_html(source_url, clip_source=clip_source),
            )
        else:
            unexpected_requests.append(url)
            await route.abort()

    async def route_generated_source(route) -> None:
        if route.request.url != source_url:
            unexpected_requests.append(route.request.url)
            await route.abort()
            return
        source_requests.append(route.request.url)
        await route.fulfill(
            status=200,
            content_type="image/webp",
            headers={"cache-control": "no-store"},
            body=webp_bytes,
        )

    async def abort_unexpected(route) -> None:
        unexpected_requests.append(route.request.url)
        await route.abort()

    await isolated_runner_page.route("**/*", abort_unexpected)
    await isolated_runner_page.route("https://ebookjapan.yahoo.co.jp/**", route_owned_fixture)
    await isolated_runner_page.route(f"https://{PRODUCTION_SOURCE_HOST}/**", route_generated_source)
    await isolated_runner_page.add_init_script(
        """(()=>{
          const canvas=new OffscreenCanvas(1,1),prototype=Object.getPrototypeOf(canvas.getContext('2d'));
          Object.defineProperty(prototype,'getImageData',{configurable:true,writable:true,value:undefined});
          Object.defineProperty(prototype,'arc',{configurable:true,writable:true,value:function fixtureArc(){}});
          Object.defineProperty(prototype,'fixturePrivateCallable',{configurable:true,writable:true,enumerable:true,value:function fixturePrivateCallable(){}});
        })()"""
    )
    adapter = EbookJapanAdapter()
    await adapter.configure_target_identity(PRODUCT_ID, "generated-work")
    output = tmp_path / "isolated-catalog" / "run"
    result = await CrawlerRunner(
        RunConfig(
            site="ebookjapan",
            source_url=PRODUCT_URL,
            output_dir=output,
            diagnostics_dir=tmp_path / "isolated-diagnostics",
            access_strategy="direct",
            page_turn_delay_ms=0,
            max_pages=3,
            page_change_timeout_ms=1_000,
        )
    ).run(isolated_runner_page, adapter)

    assert source_requests == [source_url]
    assert unexpected_requests == []
    assert result.stop_state.value == "end"
    assert len(result.pages) == 1
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    page_entry = manifest["pages"][0]
    metadata = page_entry["metadata"]
    expected_extension = ".png" if clip_source else ".webp"
    expected_mime = "image/png" if clip_source else "image/webp"
    assert page_entry["file"] == f"page-0001{expected_extension}", metadata
    assert page_entry["mime_type"] == expected_mime
    assert (page_entry["width"], page_entry["height"]) == (SOURCE_WIDTH, SOURCE_HEIGHT)
    attempt = metadata["ebookjapan_source_capture_attempt"]
    if clip_source:
        assert metadata["capture_method"] == "D_compositor_png"
        assert metadata["capture_class"] == "D"
        assert metadata["ebookjapan_source_provenance"] == "UNKNOWN"
        assert attempt["status"] == "D_FALLBACK"
        assert attempt["failure_reason_code"] == "source-paint-state-unsupported"
        assert attempt["runtime_adoption_status"] == "NOT_APPLIED"
        assert "source_roi_proof" not in metadata["ebookjapan_capture_parts"][0]
    else:
        assert metadata["capture_method"] == "C_source_roi_lossless"
        assert metadata["capture_class"] == "C"
        assert metadata["ebookjapan_source_provenance"] == "VERIFIED_SOURCE_ROI"
        assert attempt["status"] == "C_VERIFIED"
        assert attempt["runtime_adoption_status"] == "ADOPTED_CONDITIONAL"
        proof = metadata["ebookjapan_capture_parts"][0]["source_roi_proof"]
        assert proof["roi_count"] == 256
        assert proof["source_encoded_sha256"] == hashlib.sha256(webp_bytes).hexdigest()
        assert proof["output_encoded_sha256"] == hashlib.sha256((output / page_entry["file"]).read_bytes()).hexdigest()
    assert source_url not in json.dumps(metadata, sort_keys=True)

    expected_image = (output / page_entry["file"]).read_bytes()
    packaged = package_crawl_output(
        output,
        {"title": "Generated Fixture Work", "genre": "neutral-test"},
        library_dir=tmp_path / "isolated-library",
    )
    with zipfile.ZipFile(packaged.archive_path) as archive:
        assert archive.namelist() == [f"page-0001{expected_extension}"]
        assert archive.read(f"page-0001{expected_extension}") == expected_image


async def test_late_duplicate_image_request_keeps_the_complete_capture_on_d(
    c2_browser: Page,
) -> None:
    adapter = await _open_owned_reader(c2_browser, _generated_vp8_webp())
    await adapter.get_content_identity(c2_browser)
    native_capture = adapter._capture_rendered_page

    async def duplicate_before_d(page: Page):
        duplicate_request = type("DuplicateRequest", (), {})()
        duplicate_request.frame = page.main_frame
        duplicate_request.url = SOURCE_URL
        duplicate_request.resource_type = "image"
        duplicate_request.redirected_from = None
        duplicate_request.is_navigation_request = lambda: False
        duplicate_response = type("DuplicateResponse", (), {})()
        duplicate_response.request = duplicate_request
        duplicate_response.frame = page.main_frame
        duplicate_response.status = 200
        duplicate_response.headers = {
            "content-type": "image/webp",
            "content-length": "128",
        }
        ledger = adapter._source_request_ledger
        ledger.request_started(
            duplicate_request,
            main_frame=page.main_frame,
            reader_url=page.url,
        )
        ledger.response_received(duplicate_response, main_frame=page.main_frame)
        return await native_capture(page)

    adapter._capture_rendered_page = duplicate_before_d  # type: ignore[method-assign]
    outcome = await adapter._research_compare_source_capture(c2_browser)

    assert outcome.status == "D_FALLBACK"
    assert outcome.failure_reason == "source-response-ambiguous"
    assert len(outcome.captures) == len(outcome.fallback_captures) == 1
    assert outcome.parts == ()
    assert len(adapter._source_request_ledger._requests) == 2


async def test_source_image_identity_race_during_d_capture_is_fatal(
    c2_browser: Page,
) -> None:
    adapter = await _open_owned_reader(c2_browser, _generated_vp8_webp())
    await adapter.get_content_identity(c2_browser)
    native_capture = adapter._capture_rendered_page

    async def change_source_during_d(page: Page):
        result = await native_capture(page)
        await page.evaluate(
            """async()=>{
              const image=window.__fixtureImage;
              image.src=image.currentSrc+'&version=2';
              await image.decode();
            }"""
        )
        return result

    adapter._capture_rendered_page = change_source_during_d  # type: ignore[method-assign]
    with pytest.raises(UnknownPageStateError, match="source image identity"):
        await adapter._research_compare_source_capture(c2_browser)


async def test_source_dimension_reset_during_d_capture_is_fatal(c2_browser: Page) -> None:
    adapter = await _open_owned_reader(c2_browser, _generated_vp8_webp())
    await adapter.get_content_identity(c2_browser)
    native_capture = adapter._capture_rendered_page

    async def reset_source_during_d(page: Page):
        result = await native_capture(page)
        await page.evaluate(
            """()=>{
              const source=window.__fixtureSources[0];source.width=source.width;
            }"""
        )
        return result

    adapter._capture_rendered_page = reset_source_during_d  # type: ignore[method-assign]
    with pytest.raises(UnknownPageStateError, match="source canvas reset"):
        await adapter._research_compare_source_capture(c2_browser)


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("same-dimension-reset", "source canvas reset"),
        (
            "source-own-width-shadow",
            "source or target context, dimensions, or transfer changed",
        ),
        ("context-loss", "source or target context, dimensions, or transfer changed"),
    ],
    ids=(
        "same-dimension-reset-before-final-snapshot",
        "source-own-width-shadow-before-final-snapshot",
        "context-loss-before-final-snapshot",
    ),
)
async def test_late_source_health_change_before_final_snapshot_is_fatal(
    c2_browser: Page,
    mutation: str,
    reason: str,
) -> None:
    adapter = await _open_owned_reader(c2_browser, _generated_vp8_webp())
    await adapter.get_content_identity(c2_browser)
    native_snapshot = adapter._research_private_snapshot
    snapshot_calls = 0

    async def mutate_before_final_snapshot(page: Page, part):
        nonlocal snapshot_calls
        snapshot_calls += 1
        if snapshot_calls == 3:
            await page.evaluate(
                """mutation=>{
                  const source=window.__fixtureSources[0];
                  if(mutation==='same-dimension-reset')source.width=source.width;
                  else if(mutation==='source-own-width-shadow')
                    Object.defineProperty(source,'width',{configurable:true,value:source.width});
                  else if(mutation==='context-loss')source.dispatchEvent(new Event('contextlost'));
                }""",
                mutation,
            )
        return await native_snapshot(page, part)

    adapter._research_private_snapshot = mutate_before_final_snapshot  # type: ignore[method-assign]

    with pytest.raises(UnknownPageStateError, match=reason):
        await adapter._research_compare_source_capture(c2_browser)

    assert snapshot_calls == 3
