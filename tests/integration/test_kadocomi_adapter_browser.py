from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import pytest_asyncio
from PIL import Image
from playwright.async_api import Browser, Page

from screenshot_crawler.core.errors import (
    PageChangeTimeoutError,
    UnknownPageStateError,
    UnsupportedAccessStrategyError,
)
from screenshot_crawler.core.models import RunConfig
from screenshot_crawler.core.runner import CrawlerRunner
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.kadocomi.adapter import KadocomiAdapter
from screenshot_crawler.site_adapters.kadocomi.native_capture import (
    NATIVE_CAPTURE_SCRIPT,
    NATIVE_OBSERVER_INIT_SCRIPT,
)

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
) -> str:
    image_data = [base64.b64encode(image).decode("ascii") for image in images]
    pages = [
        {"images": [0]},
        {"images": [1, 2]},
        {"images": [], "end": include_end},
        {"images": [], "trailing": True},
    ]
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
        marker_markup = (
            '<div class="_endOfBookWrapper_k9w27_34" data-type="end-of-book" data-n="1"></div>'
            '<div class="_endOfBookWrapper_k9w27_34" data-type="end-of-book" data-n="2"></div>'
            if page.get("end")
            else ""
        )
        trailing_markup = (
            '<a href="/detail/other-work">Related work</a>'
            '<div class="_root_1w5tt_1" data-type="end">'
            '<div class="_endOfBook_1w5tt_50" data-type="end-of-book"></div></div>'
            if page.get("trailing")
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
    return f"""<!doctype html><html><head><meta charset="utf-8">
      <title>{episode_title}</title><meta property="og:title" content="{episode_title}">
      <style>
        body {{ margin:0; }}
        ._mainScreen_191o7_1 {{ position:relative;width:800px;height:600px; }}
        .splide._root_1542n_1 {{ position:absolute;left:40px;top:40px;width:700px;height:400px;direction:{computed_direction}; }}
        .splide__slide {{ position:absolute;left:0;top:0;width:700px;height:400px;visibility:hidden; }}
        .splide__slide.is-active {{ visibility:visible;z-index:2; }}
        ._root_bx4cr_1 {{ width:16px;height:12px; }}
        ._cover_bx4cr_11 {{ position:absolute;left:0;top:0;width:80px;height:100%;z-index:5; }}
      </style></head><body>
      <h1>{episode_heading}</h1><div class="_mainScreen_191o7_1">
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
            slides[2].classList.add('is-active');
          }} else if (index >= 0 && index + 1 < slides.length) {{
            slides[index].classList.remove('is-active');
            slides[index + 1].classList.add('is-active');
          }}
        }});
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
) -> None:
    listing = _listing_html(episode_id=listed_episode_id, deadline=deadline)
    viewer = _reader_html(
        images,
        include_end=include_end,
        reverse_spread=reverse_spread,
        skip_to_end=skip_to_end,
        computed_direction=computed_direction,
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
            await route.fulfill(status=200, body=viewer, content_type="text/html; charset=utf-8")
        elif path.startswith(f"/detail/{WORK_ID}/episodes/"):
            await route.fulfill(status=200, body=viewer, content_type="text/html; charset=utf-8")
        else:
            await route.fulfill(status=404, body="not found")

    await page.route("https://comic-walker.com/**", fulfill)


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
async def test_kadocomi_runner_captures_right_to_left_spread_and_requires_explicit_end(
    browser_page: Page,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    computed_direction: str,
) -> None:
    from screenshot_crawler.site_adapters.kadocomi import discovery

    monkeypatch.setattr(discovery, "SETTLEMENT_INTERVAL_MS", 5)
    monkeypatch.setattr(discovery, "SETTLEMENT_TIMEOUT_SECONDS", 1.0)
    images = [
        _webp((30, 90, 150, 255)),
        _webp((170, 30, 70, 193)),
        _webp((20, 180, 80, 255)),
    ]
    await _install_reader_routes(browser_page, images, computed_direction=computed_direction)
    adapter = KadocomiAdapter()
    result = await CrawlerRunner(
        RunConfig(
            site="kadocomi",
            source_url=f"{EPISODE_URL}?co=true&episodeType=first",
            output_dir=tmp_path / "output",
            diagnostics_dir=tmp_path / "diagnostics",
            access_strategy="direct",
            page_turn_delay_ms=0,
            max_pages=10,
        )
    ).run(browser_page, adapter)

    assert result.stop_state is PageState.END
    assert len(result.pages) == 3
    assert [page.file_extension for page in result.pages] == [".webp"] * 3
    assert [page.mime_type for page in result.pages] == ["image/webp"] * 3
    assert [(tmp_path / "output" / page.file).read_bytes() for page in result.pages] == images
    assert adapter.get_output_metadata() == {"title": WORK_TITLE, "order": EPISODE_LABEL}
    final_snapshot = await browser_page.evaluate(
        "window.__kadocomiNativeCaptureV1.snapshot()"
    )
    assert len(final_snapshot["slideRows"]) == 4
    assert final_snapshot["activeIndex"] == 2
    assert final_snapshot["markerSlideIndexes"] == [2, 2]
    assert final_snapshot["markerNumbers"] == ["1", "2"]
    assert final_snapshot["secondaryEndMarkerSlideIndexes"] == [3]
    assert final_snapshot["slideRows"][3]["contentSlots"] == []
    assert len(list((tmp_path / "output").glob("page-*.webp"))) == 3


@pytest.mark.parametrize(
    "scenario",
    ["expired", "missing_target", "foreign_redirect", "missing_end", "reverse_spread", "skip_slide"],
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
    images = [_webp((30, 90, 150, 255)), _webp((170, 30, 70, 193)), _webp((20, 180, 80, 255))]
    options: dict[str, object] = {}
    if scenario == "expired":
        options["deadline"] = "2020/10/14 11:00"
    elif scenario == "missing_target":
        options["listed_episode_id"] = "KC_0049150000400012_E"
    elif scenario == "foreign_redirect":
        options["redirect_foreign_episode"] = True
    elif scenario == "missing_end":
        options["include_end"] = False
    elif scenario == "reverse_spread":
        options["reverse_spread"] = True
    elif scenario == "skip_slide":
        options["skip_to_end"] = True
    await _install_reader_routes(browser_page, images, **options)
    if scenario == "missing_end":
        monkeypatch.setattr(kadocomi_adapter, "VIEWER_READY_TIMEOUT_SECONDS", 0.2)
    output_dir = tmp_path / scenario / "output"
    runner = CrawlerRunner(
        RunConfig(
            site="kadocomi",
            source_url=f"{EPISODE_URL}?co=true&episodeType=first",
            output_dir=output_dir,
            diagnostics_dir=tmp_path / scenario / "diagnostics",
            access_strategy="direct",
            page_turn_delay_ms=0,
            max_pages=10,
        )
    )

    expected_error = PageChangeTimeoutError if scenario == "missing_end" else UnknownPageStateError
    with pytest.raises(expected_error):
        await runner.run(browser_page, KadocomiAdapter())

    if scenario == "skip_slide":
        manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
        assert len(manifest["pages"]) == 1
        assert manifest["pages"][0]["file"] == "page-0001.webp"
        assert "status" not in manifest
        assert list(output_dir.glob("page-*.webp")) == [output_dir / "page-0001.webp"]
    else:
        assert list(output_dir.glob("page-*.webp")) == []
        assert not (output_dir / "manifest.json").exists()


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
