from __future__ import annotations

import io

import pytest
from PIL import Image
from playwright.async_api import Error, Page, async_playwright

from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.magapoke import MagapokeAdapter
from screenshot_crawler.site_adapters.magapoke.native_capture import reconstruct_jpeg_png

SOURCE_PATH = "/static/web_titles/695/episodes/244815/p1.jpg"


@pytest.fixture
async def browser_page() -> Page:
    playwright = await async_playwright().start()
    try:
        browser = await playwright.chromium.launch(headless=True)
    except Error as exc:
        await playwright.stop()
        pytest.skip(f"Chromium is unavailable: {exc}")
    page = await browser.new_page(viewport={"width": 800, "height": 600})
    try:
        yield page
    finally:
        await browser.close()
        await playwright.stop()


def _mapping(*, sx: int, sy: int, sw: int, sh: int, dx: int, dy: int) -> dict:
    return {
        "sourcePath": SOURCE_PATH,
        "sourceWidth": 10,
        "sourceHeight": 7,
        "canvasWidth": 10,
        "canvasHeight": 7,
        "sx": sx,
        "sy": sy,
        "sw": sw,
        "sh": sh,
        "dx": dx,
        "dy": dy,
        "dw": sw,
        "dh": sh,
        "transform": [1, 0, 0, 1, 0, 0],
        "compositeOperation": "source-over",
        "filter": "none",
    }


MAPPINGS = [
    _mapping(sx=0, sy=0, sw=3, sh=7, dx=7, dy=0),
    _mapping(sx=3, sy=0, sw=7, sh=7, dx=0, dy=0),
]
BASE = _mapping(sx=0, sy=0, sw=10, sh=7, dx=0, dy=0)
VISIBLE = BASE

ALIGNED_WIDTH = 70
ALIGNED_HEIGHT = 48


def _aligned_mapping(
    *, sx: int, sy: int, dx: int, dy: int, sw: int = 16, sh: int = 16
) -> dict:
    return {
        "sourcePath": SOURCE_PATH,
        "sourceWidth": ALIGNED_WIDTH,
        "sourceHeight": ALIGNED_HEIGHT,
        "canvasWidth": ALIGNED_WIDTH,
        "canvasHeight": ALIGNED_HEIGHT,
        "sx": sx,
        "sy": sy,
        "sw": sw,
        "sh": sh,
        "dx": dx,
        "dy": dy,
        "dw": sw,
        "dh": sh,
        "transform": [1, 0, 0, 1, 0, 0],
        "compositeOperation": "source-over",
        "filter": "none",
    }


ALIGNED_MAPPINGS = [
    _aligned_mapping(sx=sx, sy=sy, dx=dx, dy=dy)
    for sx, sy, dx, dy in [
        (0, 0, 48, 32),
        (16, 0, 32, 32),
        (32, 0, 16, 32),
        (48, 0, 0, 32),
        (0, 16, 48, 16),
        (16, 16, 32, 16),
        (32, 16, 16, 16),
        (48, 16, 0, 16),
        (0, 32, 48, 0),
        (16, 32, 32, 0),
        (32, 32, 16, 0),
        (48, 32, 0, 0),
    ]
]
ALIGNED_BASE = _aligned_mapping(sx=0, sy=0, dx=0, dy=0, sw=ALIGNED_WIDTH, sh=ALIGNED_HEIGHT)
ALIGNED_VISIBLE = ALIGNED_BASE


def _scrambled_jpeg() -> bytes:
    normal = Image.new("RGB", (10, 7))
    for y in range(7):
        for x in range(10):
            normal.putpixel((x, y), ((x * 23) % 256, (y * 31) % 256, (x + y) * 17 % 256))
    scrambled = normal.copy()
    for item in MAPPINGS:
        crop = normal.crop((item["dx"], item["dy"], item["dx"] + item["dw"], item["dy"] + item["dh"]))
        scrambled.paste(crop, (item["sx"], item["sy"]))
    buffer = io.BytesIO()
    scrambled.save(buffer, format="JPEG", quality=95, subsampling=0)
    return buffer.getvalue()


def _aligned_scrambled_jpeg() -> bytes:
    normal = Image.new("RGB", (ALIGNED_WIDTH, ALIGNED_HEIGHT))
    for y in range(ALIGNED_HEIGHT):
        for x in range(ALIGNED_WIDTH):
            normal.putpixel(
                (x, y),
                ((x * 17 + y * 3) % 256, (y * 19) % 256, (x * 7 + y * 11) % 256),
            )
    scrambled = normal.copy()
    for item in ALIGNED_MAPPINGS:
        crop = normal.crop(
            (item["dx"], item["dy"], item["dx"] + item["dw"], item["dy"] + item["dh"])
        )
        scrambled.paste(crop, (item["sx"], item["sy"]))
    buffer = io.BytesIO()
    scrambled.save(buffer, format="JPEG", quality=87, subsampling=0)
    return buffer.getvalue()


def magapoke_fixture_html() -> str:
    mapping = [{key: value for key, value in item.items() if key in {"sx", "sy", "sw", "sh", "dx", "dy", "dw", "dh"}} for item in MAPPINGS]
    return f"""
    <title>Fixture Work | Episode 1 / Test</title>
    <style>
      body {{ margin: 0; }} .c-viewer {{ width: 400px; height: 500px; }}
      .c-viewer__comic canvas {{ width: 240px; height: 360px; }}
      .c-viewer__pager-next {{ position: fixed; left: 500px; top: 200px; }}
    </style>
    <div class="c-viewer">
      <div class="c-viewer__pages-item">
        <div class="c-viewer__comic"><canvas width="10" height="7"></canvas></div>
      </div>
      <button class="c-viewer__pager-next" type="button">next</button>
    </div>
    <script>
      const paths = [
        'https://mgpk-cdn.magazinepocket.com/static/web_titles/695/episodes/244815/p1.jpg',
        'https://mgpk-cdn.magazinepocket.com/static/web_titles/695/episodes/244815/p2.jpg'
      ];
      const tileMapping = {mapping!r};
      let index = 0;
      const canvas = document.querySelector('canvas');
      function render() {{
        const image = new Image();
        image.onload = () => {{
          const offscreen = new OffscreenCanvas(image.naturalWidth, image.naturalHeight);
          const ctx = offscreen.getContext('2d');
          ctx.drawImage(image, 0, 0);
          for (const tile of tileMapping) {{
            ctx.drawImage(image, tile.sx, tile.sy, tile.sw, tile.sh,
              tile.dx, tile.dy, tile.dw, tile.dh);
          }}
          canvas.getContext('2d').drawImage(offscreen, 0, 0, canvas.width, canvas.height);
        }};
        image.src = paths[index];
      }}
      document.querySelector('.c-viewer__pager-next').onclick = () => {{
        if (index === 0) {{ index = 1; render(); return; }}
        history.pushState({{}}, '', '/title/00695/episode/244816');
        canvas.style.display = 'none';
      }};
      render();
    </script>
    """


def aligned_magapoke_fixture_html() -> str:
    mapping = [
        {
            key: value
            for key, value in item.items()
            if key in {"sx", "sy", "sw", "sh", "dx", "dy", "dw", "dh"}
        }
        for item in ALIGNED_MAPPINGS
    ]
    return f"""
    <title>Fixture Work | Aligned Episode</title>
    <style>
      body {{ margin: 0; }} .c-viewer {{ width: 400px; height: 500px; }}
      .c-viewer__comic canvas {{ width: 240px; height: 360px; }}
    </style>
    <div class="c-viewer">
      <div class="c-viewer__pages-item">
        <div class="c-viewer__comic"><canvas width="{ALIGNED_WIDTH}" height="{ALIGNED_HEIGHT}"></canvas></div>
      </div>
    </div>
    <script>
      const path = 'https://mgpk-cdn.magazinepocket.com/static/web_titles/695/episodes/244815/p1.jpg';
      const tileMapping = {mapping!r};
      const canvas = document.querySelector('canvas');
      const image = new Image();
      image.onload = () => {{
        const offscreen = new OffscreenCanvas(image.naturalWidth, image.naturalHeight);
        const ctx = offscreen.getContext('2d');
        ctx.drawImage(image, 0, 0);
        for (const tile of tileMapping) {{
          ctx.drawImage(image, tile.sx, tile.sy, tile.sw, tile.sh,
            tile.dx, tile.dy, tile.dw, tile.dh);
        }}
        canvas.getContext('2d').drawImage(offscreen, 0, 0, canvas.width, canvas.height);
      }};
      image.src = path;
    </script>
    """


async def test_magapoke_reconstructs_jpeg_and_falls_back_to_screenshot(
    browser_page: Page,
) -> None:
    jpeg = _scrambled_jpeg()
    target_url = "https://pocket.shonenmagazine.com/title/00695/episode/244815"

    async def html_route(route) -> None:
        await route.fulfill(body=magapoke_fixture_html(), content_type="text/html")

    async def image_route(route) -> None:
        # p2 deliberately has a non-JPEG header. The browser still decodes the
        # synthetic bytes, while the adapter must use the screenshot fallback.
        content_type = "image/jpeg" if route.request.url.endswith("p1.jpg") else "image/png"
        await route.fulfill(body=jpeg, content_type=content_type)

    await browser_page.route(target_url, html_route)
    await browser_page.route(
        "https://mgpk-cdn.magazinepocket.com/static/web_titles/695/episodes/244815/**",
        image_route,
    )

    adapter = MagapokeAdapter()
    await adapter.prepare_page(browser_page)
    await browser_page.goto(target_url)
    await adapter.initialize(browser_page)

    assert await adapter.detect_state(browser_page) is PageState.CONTENT
    context = await adapter.get_content_context(browser_page)
    assert (context.work_id, context.episode_id, context.content_id, context.chapter_id) == (
        "00695", "244815", "244815", None
    )
    first_identity = await adapter.get_content_identity(browser_page)
    assert first_identity.page_id
    assert first_identity.source_id == "244815"
    first_capture = await adapter.capture_page(browser_page)
    assert first_capture is not None
    assert first_capture[0].mime_type == "image/png"
    assert first_capture[0].file_extension == ".png"
    expected = reconstruct_jpeg_png(
        jpeg,
        base=BASE,
        mappings=MAPPINGS,
        visible_draw=VISIBLE,
        source_path=SOURCE_PATH,
        canvas_size=(10, 7),
    )
    assert expected is not None
    assert Image.open(io.BytesIO(first_capture[0].data)).convert("RGB").tobytes() == Image.open(
        io.BytesIO(expected.data)
    ).convert("RGB").tobytes()

    await adapter.go_next(browser_page)
    await adapter.wait_for_change(browser_page, first_identity)
    second_identity = await adapter.get_content_identity(browser_page)
    second_capture = await adapter.capture_page(browser_page)
    assert second_identity != first_identity
    assert second_capture is not None
    assert second_capture[0].mime_type == "image/png"
    assert second_capture[0].file_extension == ".png"

    await adapter.go_next(browser_page)
    await adapter.wait_for_change(browser_page, second_identity)
    assert await adapter.detect_state(browser_page) is PageState.NEXT_CONTENT
    assert "episode/244816" in browser_page.url


async def test_magapoke_adapter_prefers_coefficient_jpeg_for_aligned_mapping(
    browser_page: Page,
) -> None:
    jpeg = _aligned_scrambled_jpeg()
    target_url = "https://pocket.shonenmagazine.com/title/00695/episode/244815"

    async def html_route(route) -> None:
        await route.fulfill(body=aligned_magapoke_fixture_html(), content_type="text/html")

    async def image_route(route) -> None:
        await route.fulfill(body=jpeg, content_type="image/jpeg")

    await browser_page.route(target_url, html_route)
    await browser_page.route(
        "https://mgpk-cdn.magazinepocket.com/static/web_titles/695/episodes/244815/**",
        image_route,
    )

    adapter = MagapokeAdapter()
    await adapter.prepare_page(browser_page)
    await browser_page.goto(target_url)
    await adapter.initialize(browser_page)

    assert await adapter.detect_state(browser_page) is PageState.CONTENT
    capture = await adapter.capture_page(browser_page)

    assert capture is not None
    assert len(capture) == 1
    assert capture[0].mime_type == "image/jpeg"
    assert capture[0].file_extension == ".jpg"
    assert (capture[0].width, capture[0].height) == (ALIGNED_WIDTH, ALIGNED_HEIGHT)

    expected = reconstruct_jpeg_png(
        jpeg,
        base=ALIGNED_BASE,
        mappings=ALIGNED_MAPPINGS,
        visible_draw=ALIGNED_VISIBLE,
        source_path=SOURCE_PATH,
        canvas_size=(ALIGNED_WIDTH, ALIGNED_HEIGHT),
    )
    assert expected is not None
    assert Image.open(io.BytesIO(capture[0].data)).convert("RGB").tobytes() == Image.open(
        io.BytesIO(expected.data)
    ).convert("RGB").tobytes()
