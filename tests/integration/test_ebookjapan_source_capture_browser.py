from __future__ import annotations

import hashlib
import io
import json

import pytest
import pytest_asyncio
from PIL import Image, ImageDraw
from playwright.async_api import Browser, Page

from screenshot_crawler.core.errors import UnknownPageStateError
from screenshot_crawler.site_adapters.ebookjapan.adapter import EbookJapanAdapter

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


def _reader_html(*, clip_source: bool = False, source_url: str = SOURCE_URL) -> str:
    clip_statement = (
        "context.beginPath();context.rect(0,0,1088,1600);context.clip();"
        if clip_source
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
      const drawCanvas=canvas=>{{
        canvas.width={SOURCE_WIDTH};canvas.height={SOURCE_HEIGHT};
        const offscreen=new OffscreenCanvas({SOURCE_WIDTH},{SOURCE_HEIGHT});
        window.__fixtureSources.push(offscreen);
        const context=offscreen.getContext('2d');
        {clip_statement}
        for(let row=0;row<{ROIS_Y};row++)for(let column=0;column<{ROIS_X};column++){{
          const sx=column*{SOURCE_WIDTH // ROIS_X},sy=row*{SOURCE_HEIGHT // ROIS_Y};
          context.drawImage(image,sx,sy,{SOURCE_WIDTH // ROIS_X},{SOURCE_HEIGHT // ROIS_Y},
            sx,sy,{SOURCE_WIDTH // ROIS_X},{SOURCE_HEIGHT // ROIS_Y});
        }}
        const bitmap=offscreen.transferToImageBitmap();
        canvas.getContext('2d').drawImage(bitmap,0,0);
      }};
      image.decode().then(()=>{{
        for(const canvas of document.querySelectorAll('.page-canvas'))drawCanvas(canvas);
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


async def _open_owned_reader(
    page: Page,
    webp_bytes: bytes,
    *,
    clip_source: bool = False,
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
            body=_reader_html(clip_source=clip_source, source_url=source_url),
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


async def test_late_duplicate_image_request_keeps_the_complete_capture_on_d(
    c2_browser: Page,
) -> None:
    adapter = await _open_owned_reader(c2_browser, _generated_vp8_webp())
    await adapter.get_content_identity(c2_browser)
    native_capture = adapter.capture_page

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

    adapter.capture_page = duplicate_before_d  # type: ignore[method-assign]
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
    native_capture = adapter.capture_page

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

    adapter.capture_page = change_source_during_d  # type: ignore[method-assign]
    with pytest.raises(UnknownPageStateError, match="source image identity"):
        await adapter._research_compare_source_capture(c2_browser)


async def test_source_dimension_reset_during_d_capture_is_fatal(c2_browser: Page) -> None:
    adapter = await _open_owned_reader(c2_browser, _generated_vp8_webp())
    await adapter.get_content_identity(c2_browser)
    native_capture = adapter.capture_page

    async def reset_source_during_d(page: Page):
        result = await native_capture(page)
        await page.evaluate(
            """()=>{
              const source=window.__fixtureSources[0];source.width=source.width;
            }"""
        )
        return result

    adapter.capture_page = reset_source_during_d  # type: ignore[method-assign]
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
