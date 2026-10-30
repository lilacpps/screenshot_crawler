from __future__ import annotations

import base64
from io import BytesIO

import pytest
from PIL import Image
from playwright.async_api import Page

from screenshot_crawler.core.errors import PageChangeTimeoutError
from screenshot_crawler.core.models import ContentIdentity
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.bookwalker import adapter as adapter_module
from screenshot_crawler.site_adapters.bookwalker import terminal_match
from screenshot_crawler.site_adapters.bookwalker.adapter import (
    _SCALED_SOURCE_PIXEL_EXACT_COMPARISON_SCRIPT,
    _SELECTED_COMPLETED_MAPPINGS_COMPACT_SCRIPT,
    BookWalkerAdapter,
)
from screenshot_crawler.site_adapters.bookwalker.original_capture import (
    image_signature,
    imagebitmap_signature,
)
from screenshot_crawler.site_adapters.bookwalker.purchased_mapping import (
    MAPPING_PROVEN,
    analyze_purchased_mapping,
    decode_compact_completed_mappings,
)
from screenshot_crawler.site_adapters.bookwalker.terminal_match import (
    TERMINAL_DESCRIPTOR_SCRIPT,
)

pytestmark = pytest.mark.asyncio(loop_scope="module")


class _PreparePage:
    def __init__(self) -> None:
        self.listener_count = 0
        self.route_count = 0
        self.init_scripts: list[str] = []

    async def add_init_script(self, script: str) -> None:
        self.init_scripts.append(script)

    def on(self, _event: str, _handler: object) -> None:
        self.listener_count += 1

    async def route(self, _pattern: str, _handler: object) -> None:
        self.route_count += 1


def _patterned_cover_jpeg() -> bytes:
    image = Image.new("RGB", (16, 1200))
    pixels = image.load()
    for y in range(1200):
        for x in range(16):
            pixels[x, y] = ((x * 31 + y * 3) % 256, (y * 7) % 256, (x * 47 + y) % 256)
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=95, subsampling=0)
    return buffer.getvalue()


def _solid_large_jpeg() -> bytes:
    image = Image.new("RGB", (1448, 2048), (23, 47, 71))
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=95, subsampling=0)
    return buffer.getvalue()


SYNTHETIC_NOTICE_HASH = "7588e561d2897f4fb7a8466fcf66f887cd49a578c5e8cb99e2b534b2d4629d55"
SYNTHETIC_LOGO_HASH = "4f63ad79af8dd49ae670664d9bfeda48ba170664396ab0ed1b44b3997cdeea6f"


async def _setup_synthetic_terminal_page(page: Page, *, counter: str = "2/3") -> None:
    async def fulfill(route) -> None:
        await route.fulfill(content_type="text/html", body="<html><body></body></html>")

    await page.route("https://viewer.bookwalker.jp/**", fulfill)
    await page.add_init_script(adapter_module._DRAW_TRACE_SCRIPT)
    await page.goto("https://viewer.bookwalker.jp/03/30/viewer.html?cid=synthetic")
    await page.evaluate(
        """
        ({counter}) => {
          document.body.innerHTML = `
            <div id="pageSliderCounter">${counter}</div>
            <div id="renderer"><div class="currentScreen">
              <canvas width="1200" height="800" style="width:1200px;height:800px"></canvas>
            </div></div>
            <div id="endOfBook" style="display:none"></div>`;
          const source = document.createElement('canvas');
          source.width = 8; source.height = 600;
          document.body.appendChild(source);
          const target = document.querySelector('#renderer canvas');
          const counterNode = document.querySelector('#pageSliderCounter');
          const setPage = (text, color) => {
            counterNode.textContent = text;
            const sourceContext = source.getContext('2d');
            sourceContext.clearRect(0, 0, source.width, source.height);
            sourceContext.fillStyle = color;
            sourceContext.fillRect(0, 0, source.width, source.height);
            const targetContext = target.getContext('2d');
            targetContext.clearRect(0, 0, target.width, target.height);
            targetContext.drawImage(source, 0, 0, source.width, source.height,
              100, 0, 800, 600);
          };
          window.__syntheticSetTerminalPage = setPage;
          window.__syntheticSource = source;
          window.__syntheticTarget = target;
          window.addEventListener('keydown', event => {
            if (event.key !== 'ArrowLeft') return;
            if (counterNode.textContent === '2/3') {
              setPage('3/3', 'rgb(90,40,20)');
            } else {
              document.querySelector('#endOfBook').style.display = 'block';
            }
          });
          setPage(counter, 'rgb(12,34,56)');
        }
        """,
        {"counter": counter},
    )


async def test_terminal_native_ad_boundary_is_non_consuming_and_reaches_end(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _setup_synthetic_terminal_page(browser_page)
    monkeypatch.setitem(
        BookWalkerAdapter._known_terminal_native_artifacts,
        (8, 600, SYNTHETIC_NOTICE_HASH),
        "notice",
    )
    monkeypatch.setitem(
        BookWalkerAdapter._known_terminal_native_artifacts,
        (8, 600, SYNTHETIC_LOGO_HASH),
        "logo",
    )
    adapter = BookWalkerAdapter()
    adapter._initial_content_id = "synthetic"

    before = await browser_page.evaluate(
        "() => ({calls: window.__bookwalkerNativeDrawCalls.length, snapshots: window.__bookwalkerNativeSnapshots.size})"
    )
    assert await adapter.detect_state(browser_page) is PageState.AD
    after = await browser_page.evaluate(
        "() => ({calls: window.__bookwalkerNativeDrawCalls.length, snapshots: window.__bookwalkerNativeSnapshots.size})"
    )
    assert after == before

    previous = await adapter.get_content_identity(browser_page)
    await adapter.go_next(browser_page)
    await adapter.wait_for_change(browser_page, previous)
    assert await adapter.detect_state(browser_page) is PageState.AD
    assert (await browser_page.locator("#pageSliderCounter").inner_text()) == "3/3"

    logo_identity = await adapter.get_content_identity(browser_page)
    await adapter.go_next(browser_page)
    await adapter.wait_for_change(browser_page, logo_identity)
    assert await adapter.detect_state(browser_page) is PageState.END


@pytest.mark.parametrize("variant", ["unknown", "one_pixel_mismatch"])
async def test_terminal_native_ad_unknown_or_pixel_mismatch_stays_content(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
    variant: str,
) -> None:
    await _setup_synthetic_terminal_page(browser_page)
    if variant == "unknown":
        expected = "0" * 64
        registered_hash = expected
    else:
        registered_hash = SYNTHETIC_NOTICE_HASH
        await browser_page.evaluate(
            """
            () => {
              const source = window.__syntheticSource;
              const context = source.getContext('2d');
              context.fillStyle = 'rgb(255,0,0)';
              context.fillRect(source.width - 1, source.height - 1, 1, 1);
              const target = window.__syntheticTarget;
              const targetContext = target.getContext('2d');
              targetContext.clearRect(0, 0, target.width, target.height);
              targetContext.drawImage(source, 0, 0, source.width, source.height,
                100, 0, 800, 600);
            }
            """
        )
    monkeypatch.setitem(
        BookWalkerAdapter._known_terminal_native_artifacts,
        (8, 600, registered_hash),
        "notice",
    )
    adapter = BookWalkerAdapter()
    adapter._initial_content_id = "synthetic"
    assert await adapter.detect_state(browser_page) is PageState.CONTENT
    captures = await adapter.capture_page(browser_page)
    assert captures is not None
    assert len(captures) == 1
    assert captures[0].mime_type == "image/png"
    assert (captures[0].width, captures[0].height) == (8, 600)
    image = Image.open(BytesIO(captures[0].data)).convert("RGBA")
    assert image.getpixel((0, 0)) == (12, 34, 56, 255)
    assert image.getpixel((7, 599)) == (
        (255, 0, 0, 255) if variant == "one_pixel_mismatch" else (12, 34, 56, 255)
    )


@pytest.mark.parametrize("mutation", ["counter", "renderer_fill"])
async def test_terminal_native_ad_anchor_change_during_hash_fails_closed(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    await _setup_synthetic_terminal_page(browser_page)
    monkeypatch.setitem(
        BookWalkerAdapter._known_terminal_native_artifacts,
        (8, 600, SYNTHETIC_NOTICE_HASH),
        "notice",
    )
    await browser_page.evaluate(
        """
        (mutation) => {
          const digest = crypto.subtle.digest.bind(crypto.subtle);
          crypto.subtle.digest = async (...args) => {
            if (mutation === 'counter') {
              document.querySelector('#pageSliderCounter').textContent = '3/3';
            } else {
              const canvas = document.querySelector('#renderer canvas');
              const context = canvas.getContext('2d');
              context.fillStyle = 'rgb(255,0,0)';
              context.fillRect(0, 0, 1, 1);
            }
            return digest(...args);
          };
        }
        """,
        mutation,
    )
    adapter = BookWalkerAdapter()
    adapter._initial_content_id = "synthetic"
    assert await adapter.detect_state(browser_page) is PageState.CONTENT


@pytest.mark.parametrize("role", ["notice", "logo"])
async def test_terminal_approximate_layout_reads_complete_canvas_without_native_artifact(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
    role: str,
) -> None:
    """The terminal fallback classifies only a complete synthetic canvas."""

    await _setup_synthetic_terminal_page(
        browser_page, counter="3/3" if role == "logo" else "2/3"
    )
    await browser_page.evaluate(
        """
        role => {
          const canvas = window.__syntheticTarget;
          canvas.width = 960;
          canvas.height = 1280;
          canvas.setAttribute('data-bookwalker-trace-id', 'approx-terminal');
          const context = canvas.getContext('2d');
          context.fillStyle = 'white';
          context.fillRect(0, 0, canvas.width, canvas.height);
          const templates = {
            notice: ['............', '..#####.....', '............',
              '..########..', '..########..', '..########..', '..########..'],
            logo: ['...######...', '...######...', '..#######...',
              '.##########.', '.##########.'],
          };
          const rows = templates[role];
          const start = role === 'notice' ? 0 : 5;
          const cellWidth = canvas.width / 12;
          const cellHeight = canvas.height / 16;
          const widthFraction = role === 'notice' ? 0.3 : 0.6;
          const heightFraction = role === 'notice' ? 0.35 : 0.65;
          context.fillStyle = '#111';
          rows.forEach((row, offset) => {
            [...row].forEach((value, column) => {
              if (value === '#') {
                context.fillRect(column * cellWidth + cellWidth * 0.35,
                  (start + offset) * cellHeight + cellHeight * 0.3,
                  cellWidth * widthFraction, cellHeight * heightFraction);
              }
            });
          });
        }
        """,
        role,
    )
    adapter = BookWalkerAdapter()
    adapter._initial_content_id = "synthetic"
    async def no_native(*_args: object) -> None:
        return None

    monkeypatch.setattr(adapter, "_native_terminal_artifact", no_native)
    descriptor = await browser_page.locator(
        "#renderer .currentScreen canvas"
    ).evaluate(TERMINAL_DESCRIPTOR_SCRIPT)
    png = terminal_match.decode_terminal_data_url(descriptor["dataUrl"])
    calibrated = terminal_match.describe_terminal_png(png)
    assert calibrated is not None
    monkeypatch.setitem(
        terminal_match._TERMINAL_HASHES, role, calibrated["perceptualHash256"]
    )
    monkeypatch.setitem(
        terminal_match._TERMINAL_ASPECT, role, calibrated["foregroundAspect"]
    )
    monkeypatch.setitem(
        terminal_match._TERMINAL_DENSITY, role, calibrated["inkDensity"]
    )
    matched = await adapter._approx_terminal_canvas(  # type: ignore[arg-type]
        browser_page.locator("#renderer .currentScreen canvas"), role,
        expected_content_id="synthetic", expected_counter="2/3" if role == "notice" else "3/3",
    )
    assert matched is not None
    assert matched["role"] == role
    detected, debug = await adapter._terminal_ad_state(browser_page)
    assert detected is True
    assert debug["reason"] == "stable complete-canvas terminal image"


async def test_terminal_approximate_layout_rejects_mixed_canvas(
    browser_page: Page,
) -> None:
    await _setup_synthetic_terminal_page(browser_page)
    await browser_page.evaluate(
        """
        () => {
          const canvas = window.__syntheticTarget;
          canvas.width = 960;
          canvas.height = 1280;
          canvas.setAttribute('data-bookwalker-trace-id', 'approx-mixed');
          const context = canvas.getContext('2d');
          context.fillStyle = 'white';
          context.fillRect(0, 0, canvas.width, canvas.height);
          context.fillStyle = '#111';
          context.fillRect(0, 0, canvas.width, canvas.height / 2);
        }
        """
    )
    adapter = BookWalkerAdapter()
    matched = await adapter._approx_terminal_canvas(  # type: ignore[arg-type]
        browser_page.locator("#renderer .currentScreen canvas"), "logo",
        expected_content_id="synthetic", expected_counter="2/3",
    )
    assert matched is None


@pytest.mark.parametrize("mutation", ["hidden", "multiple"])
async def test_terminal_approximate_layout_requires_one_visible_active_canvas(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    await _setup_synthetic_terminal_page(browser_page)
    adapter = BookWalkerAdapter()
    adapter._initial_content_id = "synthetic"
    raw = await browser_page.locator(
        "#renderer .currentScreen canvas"
    ).evaluate(TERMINAL_DESCRIPTOR_SCRIPT)
    assert raw is not None
    calibrated = terminal_match.describe_terminal_png(
        terminal_match.decode_terminal_data_url(raw["dataUrl"])
    )
    assert calibrated is not None
    monkeypatch.setitem(
        terminal_match._TERMINAL_HASHES, "logo", calibrated["perceptualHash256"]
    )
    monkeypatch.setitem(
        terminal_match._TERMINAL_ASPECT, "logo", calibrated["foregroundAspect"]
    )
    monkeypatch.setitem(
        terminal_match._TERMINAL_DENSITY, "logo", calibrated["inkDensity"]
    )
    await browser_page.evaluate(
        """
        mutation => {
          const canvas = window.__syntheticTarget;
          if (mutation === 'hidden') {
            canvas.style.display = 'none';
          } else {
            const second = canvas.cloneNode(true);
            canvas.parentElement.appendChild(second);
          }
        }
        """,
        mutation,
    )
    assert await adapter._approx_terminal_canvas(  # type: ignore[arg-type]
        browser_page.locator("#renderer .currentScreen canvas"), "logo",
        expected_content_id="synthetic", expected_counter="2/3",
    ) is None


@pytest.mark.parametrize("mutation", ["cid", "missing_cid", "missing_counter"])
async def test_terminal_approximate_layout_requires_authorized_identity_and_counter(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    await _setup_synthetic_terminal_page(browser_page)
    adapter = BookWalkerAdapter()
    adapter._initial_content_id = "synthetic"
    if mutation == "cid":
        await browser_page.evaluate(
            "() => history.replaceState({}, '', '/03/30/viewer.html?cid=other')"
        )
    elif mutation == "missing_cid":
        await browser_page.evaluate(
            "() => history.replaceState({}, '', '/03/30/viewer.html')"
        )
    else:
        await browser_page.locator("#pageSliderCounter").evaluate(
            "node => node.textContent = ''"
        )
    raw = await browser_page.locator(
        "#renderer .currentScreen canvas"
    ).evaluate(TERMINAL_DESCRIPTOR_SCRIPT)
    if mutation == "cid":
        assert raw is not None
        assert await adapter._approx_terminal_canvas(  # type: ignore[arg-type]
            browser_page.locator("#renderer .currentScreen canvas"), "logo",
            expected_content_id="synthetic", expected_counter="2/3",
        ) is None
    else:
        assert raw is None


async def test_terminal_ad_requires_authorized_initial_content_id(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _setup_synthetic_terminal_page(browser_page)
    adapter = BookWalkerAdapter()
    async def no_native(*_args: object) -> None:
        return None

    monkeypatch.setattr(adapter, "_native_terminal_artifact", no_native)
    detected, debug = await adapter._terminal_ad_state(browser_page)
    assert detected is False
    assert debug["reason"] == "authorized content identity unavailable"


async def test_terminal_ad_capture_target_failure_is_content(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _setup_synthetic_terminal_page(browser_page)
    adapter = BookWalkerAdapter()
    adapter._initial_content_id = "synthetic"

    async def fail_target(*_args: object) -> object:
        raise LookupError("target missing")

    monkeypatch.setattr(adapter, "get_capture_target", fail_target)
    detected, debug = await adapter._terminal_ad_state(browser_page)
    assert detected is False
    assert debug["reason"] == "capture target unavailable"


async def test_terminal_approximate_layout_allows_missing_trace_and_rejects_replaced_canvas(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _setup_synthetic_terminal_page(browser_page)
    await browser_page.evaluate(
        """() => window.__syntheticTarget.removeAttribute('data-bookwalker-trace-id')"""
    )
    adapter = BookWalkerAdapter()
    raw = await browser_page.locator(
        "#renderer .currentScreen canvas"
    ).evaluate(TERMINAL_DESCRIPTOR_SCRIPT)
    calibrated = terminal_match.describe_terminal_png(
        terminal_match.decode_terminal_data_url(raw["dataUrl"])
    )
    assert calibrated is not None
    monkeypatch.setitem(
        terminal_match._TERMINAL_HASHES, "logo", calibrated["perceptualHash256"]
    )
    monkeypatch.setitem(
        terminal_match._TERMINAL_ASPECT, "logo", calibrated["foregroundAspect"]
    )
    monkeypatch.setitem(
        terminal_match._TERMINAL_DENSITY, "logo", calibrated["inkDensity"]
    )
    assert await adapter._approx_terminal_canvas(  # type: ignore[arg-type]
        browser_page.locator("#renderer .currentScreen canvas"), "logo",
        expected_content_id="synthetic", expected_counter="2/3",
    ) is not None

    await _setup_synthetic_terminal_page(browser_page)
    await browser_page.evaluate(
        """() => {
          const canvas = window.__syntheticTarget;
          canvas.width = 960;
          canvas.height = 1280;
          canvas.setAttribute('data-bookwalker-trace-id', 'replacement');
          const context = canvas.getContext('2d');
          context.fillStyle = 'white';
          context.fillRect(0, 0, canvas.width, canvas.height);
          context.fillStyle = '#111';
          context.fillRect(160, 300, 624, 438);
        }"""
    )
    raw = await browser_page.locator(
        "#renderer .currentScreen canvas"
    ).evaluate(TERMINAL_DESCRIPTOR_SCRIPT)
    calibrated = terminal_match.describe_terminal_png(
        terminal_match.decode_terminal_data_url(raw["dataUrl"])
    )
    assert calibrated is not None
    monkeypatch.setitem(
        terminal_match._TERMINAL_HASHES, "notice", calibrated["perceptualHash256"]
    )
    monkeypatch.setitem(
        terminal_match._TERMINAL_ASPECT, "notice", calibrated["foregroundAspect"]
    )
    monkeypatch.setitem(
        terminal_match._TERMINAL_DENSITY, "notice", calibrated["inkDensity"]
    )
    await browser_page.evaluate(
        """() => {
          const canvas = window.__syntheticTarget;
          const original = canvas.toDataURL.bind(canvas);
          let first = true;
          canvas.toDataURL = (...args) => {
            const value = original(...args);
            if (first) {
              first = false;
              const replacement = canvas.cloneNode(false);
              replacement.setAttribute('data-bookwalker-trace-id', 'replacement');
              canvas.replaceWith(replacement);
            }
            return value;
          };
        }"""
    )
    assert await adapter._approx_terminal_canvas(  # type: ignore[arg-type]
        browser_page.locator("#renderer .currentScreen canvas"), "notice",
        expected_content_id="synthetic", expected_counter="2/3",
    ) is None


async def test_terminal_approximate_layout_rejects_counter_change(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _setup_synthetic_terminal_page(browser_page)
    adapter = BookWalkerAdapter()
    adapter._initial_content_id = "synthetic"
    async def no_native(*_args: object) -> None:
        return None

    async def matched_then_change(*_args: object, **_kwargs: object) -> dict[str, object]:
        await browser_page.locator("#pageSliderCounter").evaluate(
            "node => node.textContent = '3/3'"
        )
        return {"role": "notice", "frameSha256": "synthetic"}

    monkeypatch.setattr(adapter, "_native_terminal_artifact", no_native)
    monkeypatch.setattr(adapter, "_approx_terminal_canvas", matched_then_change)
    detected, debug = await adapter._terminal_ad_state(browser_page)
    assert detected is False
    assert debug["matched"] is False


@pytest.mark.parametrize("role", ["notice", "logo"])
async def test_terminal_approximate_layout_handles_wide_renderer_canvas(
    browser_page: Page,
    role: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _setup_synthetic_terminal_page(browser_page)
    await browser_page.evaluate(
        """
        role => {
          const canvas = window.__syntheticTarget;
          canvas.width = 1905;
          canvas.height = 944;
          canvas.setAttribute('data-bookwalker-trace-id', 'wide-terminal');
          const context = canvas.getContext('2d');
          context.fillStyle = 'white';
          context.fillRect(0, 0, canvas.width, canvas.height);
          const templates = {
            notice: ['............', '....###.....', '............',
              '....####....', '....####....', '....####....', '....####....'],
            logo: ['....####....', '....####....', '....####....',
              '....####....', '....####....'],
          };
          const rows = templates[role];
          const start = role === 'notice' ? 0 : 5;
          const cellWidth = canvas.width / 12;
          const cellHeight = canvas.height / 16;
          const widthFraction = role === 'notice' ? 0.3 : 0.6;
          const heightFraction = role === 'notice' ? 0.35 : 0.65;
          context.fillStyle = '#111';
          rows.forEach((row, offset) => {
            [...row].forEach((value, column) => {
              if (value === '#') {
                context.fillRect(column * cellWidth + cellWidth * 0.35,
                  (start + offset) * cellHeight + cellHeight * 0.3,
                  cellWidth * widthFraction, cellHeight * heightFraction);
              }
            });
          });
        }
        """,
        role,
    )
    adapter = BookWalkerAdapter()
    raw = await browser_page.locator(
        "#renderer .currentScreen canvas"
    ).evaluate(TERMINAL_DESCRIPTOR_SCRIPT)
    png = terminal_match.decode_terminal_data_url(raw["dataUrl"])
    calibrated = terminal_match.describe_terminal_png(png)
    assert calibrated is not None
    monkeypatch.setitem(
        terminal_match._TERMINAL_HASHES, role, calibrated["perceptualHash256"]
    )
    monkeypatch.setitem(
        terminal_match._TERMINAL_ASPECT, role, calibrated["foregroundAspect"]
    )
    monkeypatch.setitem(
        terminal_match._TERMINAL_DENSITY, role, calibrated["inkDensity"]
    )
    matched = await adapter._approx_terminal_canvas(  # type: ignore[arg-type]
        browser_page.locator("#renderer .currentScreen canvas"), role,
        expected_content_id="synthetic", expected_counter="2/3",
    )
    assert matched is not None


@pytest.mark.parametrize("previous_mode", ["none", "body"])
async def test_terminal_ad_trace_reset_demotion_is_bounded_with_or_without_previous_identity(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
    previous_mode: str,
) -> None:
    await _setup_synthetic_terminal_page(browser_page)
    monkeypatch.setitem(
        BookWalkerAdapter._known_terminal_native_artifacts,
        (8, 600, SYNTHETIC_NOTICE_HASH),
        "notice",
    )
    adapter = BookWalkerAdapter()
    adapter._initial_content_id = "synthetic"
    adapter._terminal_skip_identity = await adapter.get_content_identity(browser_page)
    await adapter._arm_native_capture(browser_page)
    adapter.page_change_timeout_ms = 250
    adapter.advance_retry_count = 0
    adapter.advance_retry_interval_ms = 0
    previous = None if previous_mode == "none" else ContentIdentity(
        page_id="1/3", page_number=1, source_id="synthetic"
    )
    with pytest.raises(PageChangeTimeoutError):
        await adapter.wait_for_change(browser_page, previous)


def _completed_mapping_fixture(mapping_id: str, renderer_index: int) -> dict[str, object]:
    source_id = f"bitmap-{mapping_id}"
    tiles = []
    for offset, (source_x, source_y, destination_x, destination_y) in enumerate(
        ((0, 0, 16, 0), (16, 0, 0, 0), (0, 16, 0, 16), (16, 16, 16, 16)),
        start=102,
    ):
        tiles.append(
            {
                "operationIndex": offset,
                "source": {
                    "sourceId": source_id,
                    "constructor": "ImageBitmap",
                    "width": 32,
                    "height": 32,
                },
                "target": {"canvasId": "source-canvas", "width": 32, "height": 32},
                "sourceRect": {"x": source_x, "y": source_y, "width": 16, "height": 16},
                "destination": {
                    "x": destination_x,
                    "y": destination_y,
                    "width": 16,
                    "height": 16,
                },
                "transform": {"a": 1, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0},
                "globalAlpha": 1,
                "globalCompositeOperation": "source-over",
                "filter": "none",
            }
        )
    return {
        "mappingId": mapping_id,
        "rendererOperationIndex": renderer_index,
        "rendererTarget": {"canvasId": "renderer", "width": 32, "height": 32},
        "sourceCanvas": {"canvasId": "source-canvas", "width": 32, "height": 32},
        "rendererSourceRect": {"x": 0, "y": 0, "width": 32, "height": 32},
        "rendererDestination": {"x": 0, "y": 0, "width": 32, "height": 32},
        "rendererTransform": {"a": 1, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0},
        "rendererAlpha": 1,
        "rendererComposite": "source-over",
        "rendererFilter": "none",
        "segmentClearOperationIndex": 101,
        "segmentClearRectangle": {"x": 0, "y": 0, "width": 32, "height": 32},
        "segmentFirstTileOperationIndex": 102,
        "segmentLastTileOperationIndex": 105,
        "segmentTileCount": 4,
        "segmentExpectedTileCount": 4,
        "tileDraws": tiles,
        "sourceIds": [source_id],
        "unsafeOperationCount": 0,
        "firstUnsafeOperationIndex": None,
        "unsafeOperationTypes": [],
        "segmentOverflow": False,
    }


async def test_native_capture_mode_init_script_controls_trace(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = BookWalkerAdapter()
    prepared = _PreparePage()
    await adapter.prepare_page(prepared)  # type: ignore[arg-type]
    assert len(prepared.init_scripts) == 1
    mode_script = prepared.init_scripts[0]

    async def evaluate_scripts(url: str, scripts: tuple[str, ...]) -> dict[str, object]:
        browser = browser_page.context.browser
        assert browser is not None
        context = await browser.new_context()
        page = await context.new_page()

        async def fulfill(route: object) -> None:
            await route.fulfill(status=200, body="<html></html>")  # type: ignore[attr-defined]

        await page.route(f"{url}**", fulfill)  # type: ignore[arg-type]
        try:
            for script in scripts:
                await page.add_init_script(script)
            await page.goto(url)
            return await page.evaluate(
                "() => ({ mode: window.__bookwalkerCaptureMode, "
                "enabled: window.__bookwalkerNativeCaptureEnabled, "
                "installed: window.__bookwalkerDrawTraceInstalled })"
            )
        finally:
            await page.close()
            await context.close()

    draw_script = adapter_module._DRAW_TRACE_SCRIPT
    assert await evaluate_scripts(
        "https://viewer.bookwalker.jp/order-a",
        ("window.__bookwalkerCaptureMode = 'native';", draw_script),
    ) == {"mode": "native", "enabled": True, "installed": True}
    assert await evaluate_scripts(
        "https://viewer.bookwalker.jp/production",
        (mode_script,),
    ) == {"mode": "native", "enabled": True, "installed": True}

    monkeypatch.setenv("BOOKWALKER_CAPTURE_MODE", "canvas")
    canvas_adapter = BookWalkerAdapter()
    canvas_prepared = _PreparePage()
    await canvas_adapter.prepare_page(canvas_prepared)  # type: ignore[arg-type]
    assert len(canvas_prepared.init_scripts) == 1
    assert await evaluate_scripts(
        "https://trial.bookwalker.jp/production",
        (canvas_prepared.init_scripts[0],),
    ) == {"mode": "canvas", "enabled": False, "installed": True}


async def test_dimension_reset_epoch_and_cropped_one_hop_snapshots_are_recorded(
    browser_page: Page,
) -> None:
    await browser_page.add_init_script(
        "window.__bookwalkerCaptureMode = 'native'; "
        "window.__bookwalkerDirectOriginalEnabled = true;"
    )
    await browser_page.add_init_script(adapter_module._DRAW_TRACE_SCRIPT)
    await browser_page.goto("data:text/html,<html><body></body></html>")
    result = await browser_page.evaluate(
        """
        async () => {
          const bitmapSource = document.createElement('canvas');
          bitmapSource.width = 24; bitmapSource.height = 16;
          const sourceContext = bitmapSource.getContext('2d');
          sourceContext.fillStyle = 'rgb(20,40,60)'; sourceContext.fillRect(0, 0, 24, 16);
          const bitmap = await createImageBitmap(bitmapSource);
          const tileCanvas = document.createElement('canvas');
          tileCanvas.width = 17; tileCanvas.height = 16;
          const tileContext = tileCanvas.getContext('2d');
          const positions = [[0,0],[8,0],[16,0],[0,8],[8,8],[16,8]];
          for (const [x, y] of positions) {
            tileContext.drawImage(bitmap, x, y, 8, 8, x, y, 8, 8);
          }
          // A same-value setter is still a destructive reset boundary.
          tileCanvas.width = 17;
          tileCanvas.height = 16;
          for (const [x, y] of positions) {
            tileContext.drawImage(bitmap, x, y, 8, 8, x, y, 8, 8);
          }
          const intermediate = document.createElement('canvas');
          intermediate.width = 8; intermediate.height = 8;
          intermediate.getContext('2d').drawImage(tileCanvas, 0, 0, 17, 16, 0, 0, 8, 8);
          const renderer = document.createElement('canvas');
          renderer.width = 1200; renderer.height = 600;
          renderer.getContext('2d').drawImage(intermediate, 0, 0, 8, 8, 10, 10, 100, 100);
          await new Promise(resolve => setTimeout(resolve, 0));
          const trace = window.__bookwalkerTransformTrace;
          const completed = trace.completedMappings || [];
          const mapping = completed.find(item => item.sourceCanvas?.width === 17);
          const calls = window.__bookwalkerNativeDrawCalls || [];
          const call = calls[calls.length - 1];
          const unknownCanvas = document.createElement('canvas');
          unknownCanvas.width = 4; unknownCanvas.height = 4;
          unknownCanvas.setAttribute('width', '5');
          const internalCanvas = document.createElement('canvas');
          window.__bookwalkerMarkInternalCanvas(internalCanvas);
          internalCanvas.width = 4; internalCanvas.height = 4;
          internalCanvas.setAttribute('width', '5');
          await new Promise(resolve => setTimeout(resolve, 0));
          return {
            resetObserved: trace.diagnostics.canvasResetObservationAvailable,
            unknownMutations: trace.diagnostics.unknownCanvasMutationCount,
            mapping: mapping ? {
              resetKind: mapping.segmentResetKind,
              resetEpoch: mapping.segmentResetEpoch,
              clearTarget: mapping.segmentClearTarget,
              drawTarget: mapping.segmentDrawTarget,
              resetObservationAvailable: mapping.segmentResetObservationAvailable,
              mutationObserverAvailable: mapping.segmentMutationObserverAvailable,
              mutationObserverTakeRecordsAvailable:
                mapping.segmentMutationObserverTakeRecordsAvailable,
              tileCount: mapping.segmentTileCount,
            } : null,
            native: call ? {
              fullSourceSnapshotId: call.fullSourceSnapshotId || null,
              targetSnapshotId: call.targetSnapshotId || null,
              sourceRect: call.sourceRect,
              destination: call.destination,
            } : null,
            resetEpochs: completed.filter(item => item.sourceCanvas?.width === 17)
              .map(item => item.segmentResetEpoch),
          };
        }
        """
    )
    assert result["resetObserved"] is True
    assert result["unknownMutations"] >= 1
    assert result["mapping"]["resetKind"] == "canvas_dimension_reset"
    assert result["mapping"]["resetEpoch"] is not None
    assert result["mapping"]["clearTarget"]["width"] == 17
    assert result["mapping"]["drawTarget"]["width"] == 17
    assert result["mapping"]["resetObservationAvailable"] is True
    assert result["mapping"]["mutationObserverAvailable"] is True
    assert result["mapping"]["mutationObserverTakeRecordsAvailable"] is True
    assert result["mapping"]["tileCount"] == 6
    assert max(result["resetEpochs"]) >= 3
    assert result["native"]["fullSourceSnapshotId"]
    assert result["native"]["targetSnapshotId"]


@pytest.mark.parametrize(
    "clear_mode",
    [
        "positive", "partial", "transform", "clip", "coercion",
        "coercion_throw", "observer_take_records_throw", "same_task_attribute",
    ],
)
async def test_executed_full_clear_witness_is_strict_and_versioned(
    browser_page: Page,
    clear_mode: str,
) -> None:
    await browser_page.add_init_script("window.__bookwalkerCaptureMode = 'native';")
    await browser_page.add_init_script(adapter_module._DRAW_TRACE_SCRIPT)
    await browser_page.goto("data:text/html,<html><body></body></html>")
    result = await browser_page.evaluate(
        """
        async mode => {
          const canvas = document.createElement('canvas');
          canvas.width = 32;
          canvas.height = 32;
          const context = canvas.getContext('2d');
          const contextLostAvailable = typeof context.isContextLost === 'function';
          let clearError = null;
          let clearSucceeded = false;
          let pixelAfterClear = null;
          if (mode === 'transform') context.translate(1, 0);
          if (mode === 'clip') {
            context.beginPath();
            context.rect(0, 0, 32, 31);
            context.clip();
          }
          if (mode === 'same_task_attribute') {
            context.fillRect(0, 0, 1, 1);
            canvas.setAttribute('width', '32');
            context.clearRect(0, 0, 32, 32);
            clearSucceeded = true;
          } else if (mode === 'partial') context.clearRect(0, 0, 31, 32);
          else if (mode === 'coercion') {
            context.clearRect({valueOf: () => 0}, 0, 32, 32);
            clearSucceeded = true;
          } else if (mode === 'coercion_throw') {
            try {
              context.clearRect({valueOf: () => { throw new Error('coercion-sentinel'); }}, 0, 32, 32);
              clearSucceeded = true;
            } catch (error) {
              clearError = String(error?.message || error);
            }
          } else if (mode === 'observer_take_records_throw') {
            const originalTakeRecords = MutationObserver.prototype.takeRecords;
            MutationObserver.prototype.takeRecords = function() {
              throw new Error('observer-sentinel');
            };
            context.fillRect(0, 0, 1, 1);
            try {
              context.clearRect(0, 0, 32, 32);
              clearSucceeded = true;
            } finally {
              MutationObserver.prototype.takeRecords = originalTakeRecords;
            }
          } else {
            context.clearRect(0, 0, 32, 32);
            clearSucceeded = true;
          }
          try {
            pixelAfterClear = [...context.getImageData(0, 0, 1, 1).data];
          } catch (error) {}
          const trace = window.__bookwalkerTransformTrace;
          let mapping = null;
          if (mode === 'positive') {
            const bitmapSource = document.createElement('canvas');
            bitmapSource.width = 32; bitmapSource.height = 32;
            bitmapSource.getContext('2d').fillRect(0, 0, 32, 32);
            const bitmap = await createImageBitmap(bitmapSource);
            context.drawImage(bitmap, 0, 0, 32, 32, 0, 0, 32, 32);
            const renderer = document.createElement('canvas');
            renderer.width = 64; renderer.height = 64;
            renderer.getContext('2d').drawImage(canvas, 0, 0);
            bitmap.close();
            mapping = (trace.completedMappings || []).find(item =>
              item.sourceCanvas?.canvasId === window.__bookwalkerCanvasIdentity(canvas));
          }
          const segments = Object.values(trace.activeSegments || {});
          const segment = segments.find(item => item.target?.width === 32);
          return {
            contextLostAvailable,
            witness: segment?.executedFullClearWitness || null,
            rejection: segment?.executedFullClearWitnessRejection || null,
            clearError,
            clearSucceeded,
            pixelAfterClear,
            mappingId: mapping?.mappingId || null,
            mappingWitness: mapping?.segmentExecutedFullClearWitness || null,
            diagnostics: trace.diagnostics,
            nativeDiagnostics: window.__bookwalkerNativeCaptureDiagnostics,
          };
        }
        """,
        clear_mode,
    )
    if clear_mode == "positive":
        assert result["contextLostAvailable"] is True
        witness = result["witness"]
        assert witness is not None, result
        assert witness["version"] == 1
        assert witness["kind"] == "executed_full_clear"
        assert witness["canvasId"]
        assert witness["dimensionsBefore"] == witness["dimensionsAfter"] == {
            "width": 32, "height": 32,
        }
        assert witness["resetEpoch"] >= 2
        assert witness["traceEpoch"] >= 1
        assert witness["contentVersionAfter"] > witness["contentVersionBefore"]
        assert witness["observerAvailable"] is True
        assert witness["takeRecordsAvailable"] is True
        assert witness["observerFlushedBefore"] is True
        assert witness["observerFlushedAfter"] is True
        assert witness["contextLostBefore"] is False
        assert witness["contextLostAfter"] is False
        assert result["diagnostics"]["executedFullClearWitnessCount"] == 1
        assert result["nativeDiagnostics"]["executedFullClearWitnessCount"] == 1
        assert result["mappingId"]
        assert result["mappingWitness"] == witness
        compact_payload = await browser_page.evaluate(
            adapter_module._SELECTED_COMPLETED_MAPPINGS_COMPACT_SCRIPT,
            [result["mappingId"]],
        )
        compact = decode_compact_completed_mappings(compact_payload)
        assert compact is not None
        assert compact["completedMappings"][0]["segmentExecutedFullClearWitness"] == witness
    elif clear_mode in {"coercion_throw", "observer_take_records_throw"}:
        assert result["witness"] is None
        assert result["clearSucceeded"] is (clear_mode == "observer_take_records_throw")
        if clear_mode == "coercion_throw":
            assert result["clearError"] == "coercion-sentinel"
        else:
            assert result["pixelAfterClear"] == [0, 0, 0, 0]
        assert result["diagnostics"]["executedFullClearWitnessCount"] == 0
        assert result["nativeDiagnostics"]["executedFullClearWitnessCount"] == 0
    else:
        assert result["witness"] is None
        assert result["rejection"] is not None
        assert result["diagnostics"]["executedFullClearWitnessCount"] == 0
        assert result["diagnostics"]["rejectedFullClearWitnessCount"] >= 1
        assert result["nativeDiagnostics"]["executedFullClearWitnessCount"] == 0
        assert result["nativeDiagnostics"]["rejectedFullClearWitnessCount"] >= 1


async def test_p4b_current_roi_requires_actual_visible_target_and_full_anchor(
    browser_page: Page,
) -> None:
    """Exercise the diagnostic current-DOM join without changing production gates."""
    async def fulfill(route) -> None:
        await route.fulfill(content_type="text/html", body="<html><body></body></html>")

    await browser_page.route("https://viewer.bookwalker.jp/**", fulfill)
    await browser_page.add_init_script(adapter_module._DRAW_TRACE_SCRIPT)
    await browser_page.goto(
        "https://viewer.bookwalker.jp/03/30/viewer.html?cid=synthetic-p4b"
    )
    setup = await browser_page.evaluate(
        """
        () => {
          document.body.innerHTML = `
            <div id="pageSliderCounter">1/2</div>
            <div id="renderer"><div class="currentScreen">
              <canvas width="2" height="2" style="width:2px;height:2px"></canvas>
            </div></div>`;
          const element = document.querySelector('#renderer .currentScreen canvas');
          const context = element.getContext('2d');
          context.fillStyle = 'rgb(10, 20, 30)';
          context.fillRect(0, 0, 2, 2);
          const snapshot = document.createElement('canvas');
          snapshot.width = 2; snapshot.height = 2;
          const snapshotContext = snapshot.getContext('2d');
          snapshotContext.fillStyle = 'rgb(10, 20, 30)';
          snapshotContext.fillRect(0, 0, 2, 2);
          const traceId = 'p4b-target';
          const canvasId = String(window.__bookwalkerCanvasIdentity(element));
          element.setAttribute('data-bookwalker-trace-id', traceId);
          const sourceRect = {x: 0, y: 0, width: 2, height: 2};
          const destination = {x: 0, y: 0, width: 2, height: 2};
          const selected = {
            canvasId: traceId, operationIndex: 17, sourceId: 'source-1',
            sourceCanvasId: 'source-canvas-1', sourceContentVersion: 3,
                traceEpoch: 1,
            fullSourceSnapshotId: 'source-snapshot-1', targetSnapshotId: 'target-snapshot-1',
            targetContentVersionAfter: 4, sourceRect, destination,
          };
          window.__bookwalkerNativeDrawCalls = [{
            canvasId: traceId, sourceId: 'source-1', sourceCanvasId: 'source-canvas-1',
            snapshotId: 'source-snapshot-1',
            sourceContentVersion: 3, fullSourceSnapshotId: 'source-snapshot-1',
            targetSnapshotId: 'target-snapshot-1', targetContentVersionAfter: 4,
                sourceRect, destination, operation: {index: 17, traceEpoch: 1},
          }];
          window.__bookwalkerNativeSnapshots = new Map([['target-snapshot-1', snapshot]]);
          window.__bookwalkerDirectOneHopGeometryState = () => ({
                token: 'geometry-1', traceEpoch: 1, geometryVersion: 2, contentVersion: 5,
            geometryHistoryIncomplete: false, observerFlushed: true,
            observerAvailable: true, observerTakeRecordsAvailable: true,
            unknownMutation: false, resetEpoch: 1, width: 2, height: 2,
          });
          const anchor = {
            traceId, actualCanvasId: canvasId, connected: true,
            bookIdentity: 'synthetic-p4b', counter: '1/2',
                geometryToken: 'geometry-1', traceEpoch: 1, geometryVersion: 2,
            geometryHistoryIncomplete: false, observerFlushed: true,
            observerAvailable: true, observerTakeRecordsAvailable: true,
            unknownMutation: false, resetEpoch: 1, canvasWidth: 2, canvasHeight: 2,
            targetContentVersion: 5, selected,
          };
          return {
            expected: {
              traceId, actualCanvasId: canvasId, operationIndex: 17,
              sourceId: 'source-1', sourceCanvasId: 'source-canvas-1',
                  selectedTraceEpoch: 1,
              sourceContentVersion: 3, fullSourceSnapshotId: 'source-snapshot-1',
              targetSnapshotId: 'target-snapshot-1', targetContentVersionAfter: 4,
              sourceRect, destination,
            }, initialAnchor: anchor, destination,
          };
        }
        """
    )
    original_handle = await browser_page.locator(
        "#renderer .currentScreen canvas"
    ).element_handle()
    assert original_handle is not None
    setup["originalElement"] = original_handle
    positive = await browser_page.evaluate(
        adapter_module._BOOKWALKER_P4B_CURRENT_ROI_ANCHOR_SCRIPT,
        setup,
    )
    assert positive["available"] is True, positive
    assert positive["exact"] is True, positive

    ambiguous = await browser_page.evaluate(
        """
        () => {
          const original = document.querySelector('#renderer .currentScreen canvas');
          const duplicate = original.cloneNode(false);
          duplicate.style.width = '2px'; duplicate.style.height = '2px';
          original.parentElement.appendChild(duplicate);
          return true;
        }
        """
    )
    assert ambiguous is True
    rejected = await browser_page.evaluate(
        adapter_module._BOOKWALKER_P4B_CURRENT_ROI_ANCHOR_SCRIPT,
        setup,
    )
    assert rejected["available"] is False
    assert rejected["reason"] == "current renderer canvas is missing or ambiguous"

    replaced = await browser_page.evaluate(
        """
        () => {
          const current = document.querySelector('#renderer .currentScreen canvas');
          const replacement = current.cloneNode(false);
          replacement.width = current.width;
          replacement.height = current.height;
          replacement.style.width = '2px';
          replacement.style.height = '2px';
          current.replaceWith(replacement);
          return true;
        }
        """
    )
    assert replaced is True
    replacement_rejected = await browser_page.evaluate(
        adapter_module._BOOKWALKER_P4B_CURRENT_ROI_ANCHOR_SCRIPT,
        setup,
    )
    assert replacement_rejected["available"] is False
    assert replacement_rejected["reason"] == "original renderer element is unavailable"


@pytest.mark.parametrize(
    "mutation",
    ["none", "pixel", "replace", "active_canvas", "attribute", "trace_reset", "document_replace"],
)
async def test_p4b_current_roi_actual_hook_and_element_identity(
    browser_page: Page,
    mutation: str,
) -> None:
    """Use real draw hooks, snapshots, and mutations for the atomic join."""
    async def fulfill(route) -> None:
        await route.fulfill(content_type="text/html", body="<html><body></body></html>")

    await browser_page.route("https://viewer.bookwalker.jp/**", fulfill)
    await browser_page.add_init_script(
        "window.__p4bNativePutImageData = CanvasRenderingContext2D.prototype.putImageData;"
        "window.__p4bNativeDrawImage = CanvasRenderingContext2D.prototype.drawImage;"
        + adapter_module._DRAW_TRACE_SCRIPT
    )
    await browser_page.goto(
        "https://viewer.bookwalker.jp/03/30/viewer.html?cid=synthetic-p4b-hook"
    )
    setup = await browser_page.evaluate(
        """
        async () => {
          document.body.innerHTML = `
            <div id="pageSliderCounter">1/2</div>
            <div id="renderer"><div class="currentScreen"></div></div>`;
          const source = document.createElement('canvas');
          window.__p4bFixtureSource = source;
          source.width = 1443; source.height = 2048;
          const sourceContext = source.getContext('2d');
          sourceContext.fillStyle = 'rgb(20,40,60)';
          sourceContext.fillRect(0, 0, 1443, 2048);
          const renderer = document.createElement('canvas');
          renderer.width = 1200; renderer.height = 600;
          renderer.style.width = '1200px'; renderer.style.height = '600px';
          document.querySelector('#renderer .currentScreen').appendChild(renderer);
          renderer.setAttribute(
            'data-bookwalker-trace-id',
            String(window.__bookwalkerCanvasIdentity(renderer)),
          );
          const context = renderer.getContext('2d');
          context.drawImage(source, 0, 0, 1443, 2048, 0, 0, 1200, 600);
          await new Promise(resolve => setTimeout(resolve, 0));
          const traceId = renderer.getAttribute('data-bookwalker-trace-id');
          const calls = (window.__bookwalkerNativeDrawCalls || [])
            .filter(call => call.canvasId === traceId);
          const call = calls[calls.length - 1];
          if (!call) return {
            error: 'native call missing',
            diagnostics: window.__bookwalkerNativeCaptureDiagnostics,
            nativeCalls: window.__bookwalkerNativeDrawCalls,
            drawCalls: window.__bookwalkerDrawCalls,
            traceInstalled: window.__bookwalkerDrawTraceInstalled,
          };
          const anchor = window.__bookwalkerP4BCurrentAnchor(
            renderer, call.traceOperationIndex,
          );
          const selected = anchor.selected;
          if (!selected) return {error: 'selected anchor missing', anchor};
          return {
            anchor,
            debug: {
              destination: selected.destination,
              targetSnapshot: window.__bookwalkerNativeSnapshots?.get(
                String(selected.targetSnapshotId),
              ) ? {
                width: window.__bookwalkerNativeSnapshots.get(
                  String(selected.targetSnapshotId),
                ).width,
                height: window.__bookwalkerNativeSnapshots.get(
                  String(selected.targetSnapshotId),
                ).height,
              } : null,
              renderer: {width: renderer.width, height: renderer.height},
            },
            expected: {
              traceId: anchor.traceId,
              actualCanvasId: anchor.actualCanvasId,
              traceEpoch: anchor.traceEpoch,
              operationIndex: selected.operationIndex,
              sourceId: selected.sourceId,
              sourceCanvasId: selected.sourceCanvasId,
              selectedTraceEpoch: selected.traceEpoch,
              sourceContentVersion: selected.sourceContentVersion,
              fullSourceSnapshotId: selected.fullSourceSnapshotId,
              targetSnapshotId: selected.targetSnapshotId,
              targetContentVersionAfter: selected.targetContentVersionAfter,
              sourceRect: selected.sourceRect,
              destination: selected.destination,
            },
          };
        }
        """
    )
    assert "error" not in setup, setup
    original_handle = await browser_page.locator(
        "#renderer .currentScreen canvas"
    ).element_handle()
    assert original_handle is not None
    setup["originalElement"] = original_handle

    if mutation == "pixel":
        await browser_page.evaluate(
            """
            () => {
              const canvas = document.querySelector('#renderer .currentScreen canvas');
              const context = canvas.getContext('2d');
              const pixel = context.getImageData(0, 0, 1, 1);
              pixel.data[0] = (pixel.data[0] + 1) % 255;
              window.__p4bNativePutImageData.call(context, pixel, 0, 0);
            }
            """
        )
    elif mutation == "replace":
        await browser_page.evaluate(
            """
            () => {
              const current = document.querySelector('#renderer .currentScreen canvas');
              const replacement = current.cloneNode(false);
              replacement.width = current.width;
              replacement.height = current.height;
              replacement.style.width = '1200px';
              replacement.style.height = '600px';
              current.replaceWith(replacement);
            }
            """
        )
    elif mutation == "active_canvas":
        await browser_page.evaluate(
            """
            () => {
              const current = document.querySelector('#renderer .currentScreen canvas');
              const replacement = document.createElement('canvas');
              replacement.width = current.width;
              replacement.height = current.height;
              replacement.style.width = '1200px';
              replacement.style.height = '600px';
              current.style.display = 'none';
              current.parentElement.appendChild(replacement);
              replacement.getContext('2d').drawImage(
                window.__p4bFixtureSource, 0, 0, 1443, 2048, 0, 0, 1200, 600,
              );
            }
            """
        )
    elif mutation == "attribute":
        observation = await browser_page.evaluate(
            """
            async ({setup, atomicScript}) => {
              const canvas = document.querySelector('#renderer .currentScreen canvas');
              const context = canvas.getContext('2d');
              const beforePixel = Array.from(context.getImageData(0, 0, 1, 1).data);
              const beforeState = window.__bookwalkerDirectOneHopGeometryState(canvas);
              canvas.setAttribute('width', String(canvas.width));
              window.__p4bNativeDrawImage.call(
                context, window.__p4bFixtureSource,
                0, 0, 1443, 2048, 0, 0, 1200, 600,
              );
              const afterPixel = Array.from(context.getImageData(0, 0, 1, 1).data);
              const atomic = (new Function('return (' + atomicScript + ')'))();
              const result = atomic({
                ...setup,
                initialAnchor: setup.anchor,
                destination: setup.expected.destination,
              });
              const afterState = window.__bookwalkerDirectOneHopGeometryState(canvas);
              return {
                beforePixel, afterPixel,
                beforeContentVersion: beforeState.contentVersion,
                afterContentVersion: afterState.contentVersion,
                result,
              };
            }
            """,
            {"setup": setup, "atomicScript": adapter_module._BOOKWALKER_P4B_CURRENT_ROI_ANCHOR_SCRIPT},
        )
        assert observation["beforePixel"] == observation["afterPixel"], observation
        assert observation["beforeContentVersion"] == observation["afterContentVersion"], observation
        result = observation["result"]
    elif mutation == "trace_reset":
        await browser_page.evaluate("() => window.__bookwalkerResetTransformTrace?.()")
    elif mutation == "document_replace":
        await browser_page.reload()

    if mutation not in {"none", "attribute"}:
        await browser_page.wait_for_timeout(0)
    if mutation == "document_replace":
        adapter = BookWalkerAdapter()
        adapter._initial_content_id = "synthetic-p4b-hook"
        selected_call = dict(setup["anchor"]["selected"])
        selected_call["traceOperationIndex"] = setup["expected"]["operationIndex"]
        selected_call["traceEpoch"] = setup["expected"]["selectedTraceEpoch"]
        selected_call["source"] = {"canvasId": selected_call["sourceCanvasId"]}
        result = await adapter._p4b_current_roi_atomic_proof(
            browser_page,
            selected_call,
            setup["anchor"],
            renderer_handle=original_handle,
            proof_trace_epoch=setup["expected"]["traceEpoch"],
        )
        assert result["available"] is False, result
        return
    if mutation == "attribute":
        assert result["available"] is False or result["exact"] is False, result
        return
    result = await browser_page.evaluate(
        adapter_module._BOOKWALKER_P4B_CURRENT_ROI_ANCHOR_SCRIPT,
        {
            **setup,
            "initialAnchor": setup["anchor"],
            "destination": setup["expected"]["destination"],
        },
    )
    if mutation == "none":
        assert result["available"] is True, {"result": result, "setup": setup}
        assert result["exact"] is True, result
    else:
        assert result["available"] is False or result["exact"] is False, result


@pytest.mark.parametrize("failure_mode", ["partial_setter", "observer_unavailable"])
async def test_cropped_reset_proof_fails_closed_when_observation_is_incomplete(
    browser_page: Page,
    failure_mode: str,
) -> None:
    if failure_mode == "partial_setter":
        await browser_page.add_init_script(
            """
            (() => {
              const descriptor = Object.getOwnPropertyDescriptor(
                HTMLCanvasElement.prototype, 'height');
              Object.defineProperty(HTMLCanvasElement.prototype, 'height', {
                configurable: false,
                enumerable: descriptor.enumerable,
                get: descriptor.get,
                set: descriptor.set,
              });
            })();
            """
        )
    else:
        await browser_page.add_init_script(
            "Object.defineProperty(window, 'MutationObserver', {value: undefined, configurable: true});"
        )
    await browser_page.add_init_script(
        "window.__bookwalkerCaptureMode = 'native'; "
        "window.__bookwalkerDirectOriginalEnabled = true;"
    )
    await browser_page.add_init_script(adapter_module._DRAW_TRACE_SCRIPT)
    await browser_page.goto("data:text/html,<html><body></body></html>")
    result = await browser_page.evaluate(
        """
        async () => {
          const source = document.createElement('canvas');
          source.width = 8; source.height = 8;
          source.getContext('2d').fillRect(0, 0, 8, 8);
          const bitmap = await createImageBitmap(source);
          const tiled = document.createElement('canvas');
          tiled.width = 8; tiled.height = 8;
          tiled.getContext('2d').drawImage(bitmap, 0, 0, 8, 8, 0, 0, 8, 8);
          const renderer = document.createElement('canvas');
          renderer.width = 1200; renderer.height = 600;
          renderer.getContext('2d').drawImage(tiled, 0, 0, 8, 8, 0, 0, 8, 8);
          await new Promise(resolve => setTimeout(resolve, 0));
          const trace = window.__bookwalkerTransformTrace;
          const mapping = (trace.completedMappings || [])
            .find(item => item.sourceCanvas?.width === 8);
          return {
            hooks: trace.diagnostics.canvasResetObservationAvailable,
            mapping: mapping ? {
              resetObservationAvailable: mapping.segmentResetObservationAvailable,
              mutationObserverAvailable: mapping.segmentMutationObserverAvailable,
              mutationObserverTakeRecordsAvailable:
                mapping.segmentMutationObserverTakeRecordsAvailable,
            } : null,
          };
        }
        """
    )
    assert result["hooks"] is (failure_mode != "partial_setter")
    assert result["mapping"] is not None
    assert result["mapping"]["resetObservationAvailable"] is False
    assert result["mapping"]["mutationObserverAvailable"] is (
        failure_mode != "observer_unavailable"
    )
    assert result["mapping"]["mutationObserverTakeRecordsAvailable"] is (
        failure_mode != "observer_unavailable"
    )


async def test_same_task_canvas_attribute_mutation_is_flushed_before_mapping_freeze(
    browser_page: Page,
) -> None:
    await browser_page.add_init_script("window.__bookwalkerCaptureMode = 'native';")
    await browser_page.add_init_script(adapter_module._DRAW_TRACE_SCRIPT)
    await browser_page.goto("data:text/html,<html><body></body></html>")
    result = await browser_page.evaluate(
        """
        async () => {
          const source = document.createElement('canvas');
          source.width = 8; source.height = 8;
          source.getContext('2d').fillRect(0, 0, 8, 8);
          const bitmap = await createImageBitmap(source);
          const tiled = document.createElement('canvas');
          tiled.width = 8; tiled.height = 8;
          tiled.getContext('2d').drawImage(bitmap, 0, 0, 8, 8, 0, 0, 8, 8);
          // The mutation and selected renderer draw happen in the same task.
          tiled.setAttribute('width', '8');
          const renderer = document.createElement('canvas');
          renderer.width = 1200; renderer.height = 600;
          renderer.getContext('2d').drawImage(tiled, 0, 0, 8, 8, 0, 0, 8, 8);
          const trace = window.__bookwalkerTransformTrace;
          const mapping = (trace.completedMappings || [])
            .find(item => item.sourceCanvas?.width === 8);
          return {
            unknownCount: trace.diagnostics.unknownCanvasMutationCount,
            unknown: mapping?.segmentUnknownMutation === true,
          };
        }
        """
    )
    assert result["unknownCount"] >= 1
    assert result["unknown"] is True


async def test_html_canvas_snapshot_is_pixel_stable_until_materialize(
    browser_page: Page,
) -> None:
    await browser_page.add_init_script(adapter_module._DRAW_TRACE_SCRIPT)
    await browser_page.goto("data:text/html,<html><body></body></html>")

    result = await browser_page.evaluate(
        """
        async () => {
          const source = document.createElement('canvas');
          source.width = 2;
          source.height = 2;
          document.body.appendChild(source);
          const sourceContext = source.getContext('2d');
          sourceContext.fillStyle = 'black';
          sourceContext.fillRect(0, 0, 2, 2);

          const renderer = document.createElement('canvas');
          renderer.width = 1200;
          renderer.height = 600;
          document.body.appendChild(renderer);
          const rendererContext = renderer.getContext('2d');
          const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
          let toDataURLCalls = 0;
          HTMLCanvasElement.prototype.toDataURL = function(...args) {
            toDataURLCalls += 1;
            return originalToDataURL.apply(this, args);
          };

          rendererContext.drawImage(source, 0, 0, 2, 2, 0, 0, 100, 100);
          const drawCalls = window.__bookwalkerNativeDrawCalls;
          const drawTimeToDataURLCalls = toDataURLCalls;
          sourceContext.fillStyle = 'white';
          sourceContext.fillRect(0, 0, 2, 2);
          const call = drawCalls[drawCalls.length - 1];
          const materialized = window.__bookwalkerMaterializeNativeSourceCrop({
            sourceId: call.sourceId,
            snapshotId: call.snapshotId,
            sourceConstructor: call.source.constructor,
            sourceRect: call.sourceRect,
          });
          const image = new Image();
          image.src = materialized.dataUrl;
          await image.decode();
          const probe = document.createElement('canvas');
          probe.width = 2;
          probe.height = 2;
          probe.getContext('2d').drawImage(image, 0, 0);
          const pixel = [...probe.getContext('2d').getImageData(0, 0, 1, 1).data];
          return {
            constructor: call.source.constructor,
            snapshotId: call.snapshotId,
            drawTimeToDataURLCalls,
            materializeToDataURLCalls: toDataURLCalls,
            error: materialized.error,
            pixel,
          };
        }
        """
    )

    assert result["constructor"] == "HTMLCanvasElement"
    assert result["snapshotId"]
    assert result["drawTimeToDataURLCalls"] == 0
    assert result["materializeToDataURLCalls"] == 1
    assert result["error"] is None
    assert result["pixel"][:3] == [0, 0, 0]


async def test_same_image_jpeg_and_png_have_exact_browser_signature(
    browser_page: Page,
) -> None:
    data_urls = await browser_page.evaluate(
        """
        () => {
          const canvas = document.createElement('canvas');
          canvas.width = 64;
          canvas.height = 64;
          const context = canvas.getContext('2d');
          context.fillStyle = '#ffffff';
          context.fillRect(0, 0, 64, 64);
          return {
            png: canvas.toDataURL('image/png'),
            jpeg: canvas.toDataURL('image/jpeg', 1.0),
          };
        }
        """
    )
    png_data = base64.b64decode(data_urls["png"].split(",", 1)[1])
    jpeg_data = base64.b64decode(data_urls["jpeg"].split(",", 1)[1])

    assert await image_signature(browser_page, png_data, "image/png") == await image_signature(
        browser_page, jpeg_data, "image/jpeg"
    )


async def test_retained_imagebitmap_uses_the_same_signature_contract(
    browser_page: Page,
) -> None:
    await browser_page.add_init_script(adapter_module._DRAW_TRACE_SCRIPT)
    await browser_page.goto("data:text/html,<html><body></body></html>")
    data_url = await browser_page.evaluate(
        """
        async () => {
          const canvas = document.createElement('canvas');
          canvas.width = 128;
          canvas.height = 64;
          const context = canvas.getContext('2d');
          context.fillStyle = '#ffffff';
          context.fillRect(0, 0, 128, 64);
          const bitmap = await createImageBitmap(canvas);
          window.__bookwalkerNativeSourceObjects.set('signature-bitmap', bitmap);
          return canvas.toDataURL('image/png');
        }
        """
    )
    png_data = base64.b64decode(data_url.split(",", 1)[1])

    assert await image_signature(browser_page, png_data, "image/png") == (
        await imagebitmap_signature(browser_page, "signature-bitmap")
    )


async def test_different_images_have_different_browser_signature(
    browser_page: Page,
) -> None:
    data_urls = await browser_page.evaluate(
        """
        () => {
          const make = color => {
            const canvas = document.createElement('canvas');
            canvas.width = 64;
            canvas.height = 64;
            const context = canvas.getContext('2d');
            context.fillStyle = color;
            context.fillRect(0, 0, 64, 64);
            return canvas.toDataURL('image/png');
          };
          return {white: make('#ffffff'), black: make('#000000')};
        }
        """
    )
    white = base64.b64decode(data_urls["white"].split(",", 1)[1])
    black = base64.b64decode(data_urls["black"].split(",", 1)[1])

    assert await image_signature(browser_page, white, "image/png") != await image_signature(
        browser_page, black, "image/png"
    )


async def test_scaled_source_diagnostic_reproduces_observed_full_frame_scale(
    browser_page: Page,
) -> None:
    source_and_native = await browser_page.evaluate(
        """
        async () => {
          const source = document.createElement('canvas');
          source.width = 32;
          source.height = 32;
          const sourceContext = source.getContext('2d');
          for (let y = 0; y < 32; y += 1) {
            for (let x = 0; x < 32; x += 1) {
              sourceContext.fillStyle = `rgb(${x * 8}, ${y * 8}, ${(x + y) * 4})`;
              sourceContext.fillRect(x, y, 1, 1);
            }
          }
          const reconstructed = source.toDataURL('image/jpeg', 1.0);
          const image = await createImageBitmap(
            await (await fetch(reconstructed)).blob(),
          );
          const target = document.createElement('canvas');
          target.width = 16;
          target.height = 16;
          const targetContext = target.getContext('2d');
          targetContext.imageSmoothingEnabled = true;
          targetContext.imageSmoothingQuality = 'high';
          targetContext.drawImage(image, 0, 0, 32, 32, 0, 0, 16, 16);
          image.close();
          return {reconstructed, native: target.toDataURL('image/png')};
        }
        """
    )
    result = await browser_page.evaluate(
        _SCALED_SOURCE_PIXEL_EXACT_COMPARISON_SCRIPT,
        {
            **source_and_native,
            "sourceRect": {"x": 0, "y": 0, "width": 32, "height": 32},
            "destination": {"x": 0, "y": 0, "width": 16, "height": 16},
            "targetDimensions": {"width": 16, "height": 16},
            "imageSmoothingEnabled": True,
            "imageSmoothingQuality": "high",
        },
    )

    assert result["available"] is True
    assert result["exact"] is True
    assert result["differing_pixel_count"] == 0
    assert result["max_channel_difference"] == 0


async def test_completed_segment_freeze_survives_large_post_render_prefetch(
    browser_page: Page,
) -> None:
    await browser_page.add_init_script(adapter_module._DRAW_TRACE_SCRIPT)
    await browser_page.goto("data:text/html,<html><body></body></html>")

    capture = await browser_page.evaluate(
        """
        async () => {
          const source = document.createElement('canvas');
          source.width = 64;
          source.height = 64;
          const sourceContext = source.getContext('2d');
          sourceContext.fillStyle = '#123456';
          sourceContext.fillRect(0, 0, 64, 64);
          const bitmap = await createImageBitmap(source);

          const intermediate = document.createElement('canvas');
          intermediate.width = 64;
          intermediate.height = 64;
          const intermediateContext = intermediate.getContext('2d');
          intermediateContext.clearRect(0, 0, 64, 64);
          const tiles = [
            [0, 0, 32, 32], [32, 0, 0, 32],
            [0, 32, 32, 0], [32, 32, 0, 0],
          ];
          for (const [sx, sy, dx, dy] of tiles) {
            intermediateContext.drawImage(bitmap, sx, sy, 32, 32, dx, dy, 32, 32);
          }

          const renderer = document.createElement('canvas');
          renderer.width = 64;
          renderer.height = 64;
          renderer.getContext('2d').drawImage(intermediate, 0, 0);

          // Keep concrete output bytes from the existing reconstructed page
          // before stressing the bounded geometry ledger.  The flood below
          // is unrelated to this source/copy chain, so these are the parity
          // assertions that the proof result is still usable after eviction
          // pressure rather than only a ledger-count assertion.
          const sourceJpegBefore = source.toDataURL('image/jpeg', 1.0);
          const rendererPngBefore = renderer.toDataURL('image/png');

          const prefetch = document.createElement('canvas');
          // Keep this in the production native-candidate canvas class so the
          // small-destination filter is exercised rather than bypassed by the
          // hook's large-canvas guard.
          prefetch.width = 1443;
          prefetch.height = 2048;
          const prefetchContext = prefetch.getContext('2d');
          for (let index = 0; index < 8201; index += 1) {
            prefetchContext.drawImage(bitmap, 0, 0, 32, 32, 0, 0, 32, 32);
          }
          return {
            trace: window.__bookwalkerTransformTrace,
            sourceJpegBefore,
            sourceJpegAfter: source.toDataURL('image/jpeg', 1.0),
            rendererPngBefore,
            rendererPngAfter: renderer.toDataURL('image/png'),
            diagnostics: window.__bookwalkerNativeCaptureDiagnostics,
          };
        }
        """
    )

    trace = capture["trace"]
    assert trace["nextOperationIndex"] > 8000
    assert "operations" not in trace
    assert len(trace["completedMappings"]) == 1
    record = trace["completedMappings"][0]
    assert capture["sourceJpegBefore"] == capture["sourceJpegAfter"]
    assert capture["rendererPngBefore"] == capture["rendererPngAfter"]
    assert capture["diagnostics"]["geometrySmallCallsDropped"] >= 8201
    assert record["segmentTileCount"] == 4
    assert record["segmentOverflow"] is False
    result = analyze_purchased_mapping(
        trace,
        {
            "mappingId": record["mappingId"],
            "traceOperationIndex": record["rendererOperationIndex"],
            "sourceCanvasId": record["sourceCanvas"]["canvasId"],
        },
    )
    assert result.status == MAPPING_PROVEN
    assert result.mapping is not None
    assert result.mapping.segment_tile_count == 4

    compact_payload = await browser_page.evaluate(
        _SELECTED_COMPLETED_MAPPINGS_COMPACT_SCRIPT,
        [record["mappingId"]],
    )
    decoded = decode_compact_completed_mappings(compact_payload)
    assert decoded is not None
    compact_result = analyze_purchased_mapping(
        decoded,
        {
            "mappingId": record["mappingId"],
            "traceOperationIndex": record["rendererOperationIndex"],
            "sourceCanvasId": record["sourceCanvas"]["canvasId"],
        },
    )
    assert compact_result.to_debug() == result.to_debug()


async def test_selected_completed_mapping_fetch_excludes_unrelated_records(
    browser_page: Page,
) -> None:
    await browser_page.goto("data:text/html,<html><body></body></html>")
    await browser_page.evaluate(
        """
        (completedMappings) => {
          window.__bookwalkerTransformTrace = {
            completedMappings,
            activeSegments: {active: {tileDraws: [{}, {}]}},
            droppedCompletedMappingCount: 2,
            droppedActiveSegmentCount: 1,
          };
        }
        """,
        [
            _completed_mapping_fixture("unrelated-a", 106),
            _completed_mapping_fixture("requested", 206),
            _completed_mapping_fixture("unrelated-b", 306),
            _completed_mapping_fixture("unrelated-c", 406),
        ],
    )

    selected_payload = await browser_page.evaluate(
        _SELECTED_COMPLETED_MAPPINGS_COMPACT_SCRIPT,
        ["requested"],
    )

    assert selected_payload["transportVersion"] == 1
    assert "completedMappings" not in selected_payload
    assert [record["mappingId"] for record in selected_payload["compactMappings"]] == [
        "requested"
    ]
    assert selected_payload["retainedCompletedMappingCount"] == 4
    assert selected_payload["retainedCompletedTileRecordCount"] == 16
    assert selected_payload["activeSegmentCount"] == 1
    assert selected_payload["activeTileRecordCount"] == 2
    assert selected_payload["requestedMappingCount"] == 1
    assert selected_payload["returnedCompletedMappingCount"] == 1
    assert selected_payload["returnedTileRecordCount"] == 4
    assert selected_payload["missingMappingCount"] == 0
    assert selected_payload["compactSourceTableCount"] == 1
    assert selected_payload["compactTargetTableCount"] == 1
    assert selected_payload["compactTransformTableCount"] == 1
    assert selected_payload["compactCompositeTableCount"] == 1
    assert selected_payload["compactFilterTableCount"] == 1
    decoded = decode_compact_completed_mappings(selected_payload)
    assert decoded is not None
    assert [record["mappingId"] for record in decoded["completedMappings"]] == [
        "requested"
    ]


async def test_selected_completed_mapping_fetch_preserves_two_part_selection_order(
    browser_page: Page,
) -> None:
    await browser_page.goto("data:text/html,<html><body></body></html>")
    await browser_page.evaluate(
        """
        (completedMappings) => {
          window.__bookwalkerTransformTrace = {completedMappings, activeSegments: {}};
        }
        """,
        [
            _completed_mapping_fixture("mapping-A", 106),
            _completed_mapping_fixture("mapping-B", 206),
            _completed_mapping_fixture("unrelated-C", 306),
            _completed_mapping_fixture("unrelated-D", 406),
        ],
    )

    selected_payload = await browser_page.evaluate(
        _SELECTED_COMPLETED_MAPPINGS_COMPACT_SCRIPT,
        ["mapping-A", "mapping-B"],
    )

    assert [record["mappingId"] for record in selected_payload["compactMappings"]] == [
        "mapping-A",
        "mapping-B",
    ]
    assert selected_payload["requestedMappingCount"] == 2
    assert selected_payload["returnedCompletedMappingCount"] == 2
    assert selected_payload["returnedTileRecordCount"] == 8
    assert selected_payload["missingMappingCount"] == 0
    assert selected_payload["compactSourceTableCount"] == 2
    assert selected_payload["compactTargetTableCount"] == 2
    assert selected_payload["compactTransformTableCount"] == 2
    assert selected_payload["compactCompositeTableCount"] == 2
    assert selected_payload["compactFilterTableCount"] == 2
    decoded = decode_compact_completed_mappings(selected_payload)
    assert decoded is not None
    assert [record["mappingId"] for record in decoded["completedMappings"]] == [
        "mapping-A",
        "mapping-B",
    ]
    for record in decoded["completedMappings"]:
        analysis = analyze_purchased_mapping(
            decoded,
            {
                "mappingId": record["mappingId"],
                "traceOperationIndex": record["rendererOperationIndex"],
                "sourceCanvasId": record["sourceCanvas"]["canvasId"],
            },
        )
        assert analysis.proven


async def test_selected_completed_mapping_fetch_exposes_duplicates_and_missing_ids(
    browser_page: Page,
) -> None:
    await browser_page.goto("data:text/html,<html><body></body></html>")
    await browser_page.evaluate(
        """
        (completedMappings) => {
          window.__bookwalkerTransformTrace = {completedMappings, activeSegments: {}};
        }
        """,
        [
            _completed_mapping_fixture("duplicate", 106),
            _completed_mapping_fixture("duplicate", 206),
        ],
    )

    selected_payload = await browser_page.evaluate(
        _SELECTED_COMPLETED_MAPPINGS_COMPACT_SCRIPT,
        ["duplicate", "missing", "duplicate"],
    )

    assert [record["mappingId"] for record in selected_payload["compactMappings"]] == [
        "duplicate",
        "duplicate",
    ]
    assert selected_payload["requestedMappingCount"] == 2
    assert selected_payload["returnedCompletedMappingCount"] == 2
    assert selected_payload["returnedTileRecordCount"] == 8
    assert selected_payload["missingMappingCount"] == 1
    decoded = decode_compact_completed_mappings(selected_payload)
    assert decoded is not None

    duplicate_analysis = analyze_purchased_mapping(
        decoded,
        {"mappingId": "duplicate"},
    )
    missing_analysis = analyze_purchased_mapping(
        decoded,
        {"mappingId": "missing"},
    )
    assert duplicate_analysis.proven is False
    assert missing_analysis.proven is False
    assert missing_analysis.completed_mapping_evicted is True


async def test_direct_one_hop_ledger_keeps_actual_objects_and_bounded_snapshots(
    browser_page: Page,
) -> None:
    await browser_page.add_init_script(
        "window.__bookwalkerCaptureMode = 'native'; "
        "window.__bookwalkerDirectOriginalEnabled = true;"
    )
    await browser_page.add_init_script(adapter_module._DRAW_TRACE_SCRIPT)
    await browser_page.goto("data:text/html,<html><body></body></html>")
    result = await browser_page.evaluate(
        """
        async () => {
          const sourceCanvas = document.createElement('canvas');
          sourceCanvas.width = 8; sourceCanvas.height = 600;
          const sourceContext = sourceCanvas.getContext('2d');
          sourceContext.fillStyle = 'rgb(20,40,60)';
          sourceContext.fillRect(0, 0, 8, 600);
          const bitmap = await createImageBitmap(sourceCanvas);
          const intermediate = document.createElement('canvas');
          intermediate.width = 8; intermediate.height = 600;
          const intermediateContext = intermediate.getContext('2d');
          intermediateContext.imageSmoothingEnabled = true;
          intermediateContext.imageSmoothingQuality = 'low';
          intermediateContext.drawImage(bitmap, 0, 0, 8, 600);
          const renderer = document.createElement('canvas');
          renderer.width = 1200; renderer.height = 800;
          const rendererContext = renderer.getContext('2d');
          rendererContext.imageSmoothingEnabled = true;
          rendererContext.imageSmoothingQuality = 'low';
          rendererContext.drawImage(intermediate, 0, 0, 7.5, 599.5, 100, 13, 100, 600);
          const records = window.__bookwalkerMaterializeDirectOneHop(renderer);
          return {
            count: records.length,
            record: records[records.length - 1] || null,
            sourceSnapshotBytes: records[records.length - 1]?.copy?.sourceSnapshot?.length || 0,
            intermediateBytes: records[records.length - 1]?.copy?.intermediate?.length || 0,
            sourceBBytes: records[records.length - 1]?.renderer?.sourceB?.length || 0,
          };
        }
        """,
    )
    assert result["count"] == 1
    record = result["record"]
    assert record["copy"]["sourceInfo"]["constructor"] == "ImageBitmap"
    assert record["copy"]["targetInfo"]["width"] == 8
    assert record["renderer"]["targetInfo"]["width"] == 1200
    assert record["renderer"]["sameCurrentObject"] is True
    assert record["renderer"]["mutation"] is None
    assert record["copy"]["targetContentVersionAfter"] == record["renderer"]["sourceContentVersion"]
    assert record["copy"]["sourceSnapshot"]
    assert record["copy"]["intermediate"]
    assert record["renderer"]["sourceB"]
    assert result["sourceSnapshotBytes"] > 0
    assert result["intermediateBytes"] > 0
    assert result["sourceBBytes"] > 0


async def test_direct_one_hop_returns_unique_raw_jpeg_after_full_pixel_proof(
    browser_page: Page,
) -> None:
    jpeg = _patterned_cover_jpeg()
    adapter = BookWalkerAdapter()
    candidate = adapter_module.candidate_from_jpeg(
        jpeg,
        url="https://bw-bv-epubs.bookwalker.jp/cover.jpg",
        sequence=1,
    )
    assert candidate is not None
    adapter._original_candidates.add(candidate)
    await browser_page.add_init_script(
        "window.__bookwalkerCaptureMode = 'native'; "
        "window.__bookwalkerDirectOriginalEnabled = true;"
    )
    await browser_page.add_init_script(adapter_module._DRAW_TRACE_SCRIPT)
    await browser_page.goto("data:text/html,<html><body></body></html>")
    encoded = base64.b64encode(jpeg).decode("ascii")
    await browser_page.evaluate(
        """
        async ({encoded}) => {
          const counter = document.createElement('div');
          counter.id = 'pageSliderCounter'; counter.textContent = '1/322';
          document.body.appendChild(counter);
          const source = await createImageBitmap(
            await (await fetch(`data:image/jpeg;base64,${encoded}`)).blob(),
          );
          const intermediate = document.createElement('canvas');
          intermediate.width = 8; intermediate.height = 600;
          intermediate.getContext('2d').drawImage(source, 0, 0, 8, 600);
          const renderer = document.createElement('canvas');
          renderer.id = 'cover-renderer'; renderer.width = 1200; renderer.height = 800;
          renderer.__bookwalkerTestIntermediate = intermediate;
          document.body.appendChild(renderer);
          const rendererContext = renderer.getContext('2d');
          rendererContext.drawImage(
            intermediate, 0, 0, 7.5, 599.5, 100, 13, 100, 600,
          );
          rendererContext.fillStyle = 'rgba(255,0,0,1)';
          rendererContext.fillRect(10, 10, 2, 2);
          const sprite = document.createElement('canvas');
          sprite.width = 2; sprite.height = 2;
          sprite.getContext('2d').fillRect(0, 0, 2, 2);
          rendererContext.save();
          // Fractional X is safe because Y touches the selected ROI's integer
          // bottom boundary exactly; the separating axis remains Y.
          rendererContext.drawImage(sprite, 0, 0, 2, 2, 0.5, 613, 2, 2);
          rendererContext.restore();
          const intermediate2 = document.createElement('canvas');
          intermediate2.width = 8; intermediate2.height = 600;
          intermediate2.getContext('2d').drawImage(source, 0, 0, 8, 600);
          rendererContext.drawImage(
            intermediate2, 0, 0, 7.5, 599.5, 100, 13, 100, 600,
          );
        }
        """,
        {"encoded": encoded},
    )
    selected_draw = await browser_page.evaluate(
        "() => window.__bookwalkerNativeDrawCalls.at(-1)"
    )
    selection_geometry_state = await browser_page.evaluate(
        "() => window.__bookwalkerDirectOneHopGeometryState(document.querySelector('#cover-renderer'))"
    )
    captures = await adapter._capture_direct_one_hop_original_jpeg(
        browser_page,
        browser_page.locator("#cover-renderer"),
        selected_draw,
        selection_geometry_state,
    )
    assert captures is not None
    assert captures[0].data == jpeg
    assert captures[0].mime_type == "image/jpeg"
    assert adapter._capture_debug["bookwalker_capture"]["direct_original_jpeg"]["accepted"] is True
    assert adapter._capture_debug["bookwalker_capture"]["direct_original_jpeg"]["records"][0][
        "renderer_non_intersecting_draw"
    ] is True
    assert adapter._capture_debug["bookwalker_capture"]["direct_original_jpeg"][
        "record_count"
    ] >= 2
    await browser_page.evaluate(
        "() => { document.querySelector('#pageSliderCounter').textContent = '2/322'; }"
    )
    assert (
        await adapter._capture_direct_one_hop_original_jpeg(
            browser_page, browser_page.locator("#cover-renderer"), selected_draw,
            selection_geometry_state,
        )
        is None
    )
    stale_records = adapter._capture_debug["bookwalker_capture"]["direct_original_jpeg"][
        "records"
    ]
    assert any(
        row.get("renderer_operation") == selected_draw["traceOperationIndex"]
        and row.get("reason") == "direct cover record is not page one"
        for row in stale_records
    )
    await browser_page.evaluate(
        "() => document.querySelector('#pageSliderCounter').remove()"
    )
    assert (
        await adapter._capture_direct_one_hop_original_jpeg(
            browser_page, browser_page.locator("#cover-renderer"), selected_draw,
            selection_geometry_state,
        )
        is None
    )
    missing_counter_records = adapter._capture_debug["bookwalker_capture"][
        "direct_original_jpeg"
    ]["records"]
    assert any(
        row.get("renderer_operation") == selected_draw["traceOperationIndex"]
        and row.get("reason") == "direct cover page counter unavailable"
        for row in missing_counter_records
    )


@pytest.mark.parametrize(
    ("sprite_x", "sprite_y", "accepted"),
    [(100.5, 613, True), (100.5, 612, False), (100.5, 613.5, False)],
)
async def test_direct_one_hop_fractional_external_draw_requires_integer_separator(
    browser_page: Page,
    sprite_x: float,
    sprite_y: float,
    accepted: bool,
) -> None:
    jpeg = _patterned_cover_jpeg()
    adapter = BookWalkerAdapter()
    candidate = adapter_module.candidate_from_jpeg(
        jpeg,
        url="https://bw-bv-epubs.bookwalker.jp/cover.jpg",
        sequence=1,
    )
    assert candidate is not None
    adapter._original_candidates.add(candidate)
    await browser_page.add_init_script(
        "window.__bookwalkerCaptureMode = 'native'; "
        "window.__bookwalkerDirectOriginalEnabled = true;"
    )
    await browser_page.add_init_script(adapter_module._DRAW_TRACE_SCRIPT)
    await browser_page.goto("data:text/html,<html><body></body></html>")
    encoded = base64.b64encode(jpeg).decode("ascii")
    await browser_page.evaluate(
        """
        async ({encoded, spriteX, spriteY}) => {
          const counter = document.createElement('div');
          counter.id = 'pageSliderCounter'; counter.textContent = '1/322';
          document.body.appendChild(counter);
          const source = await createImageBitmap(
            await (await fetch(`data:image/jpeg;base64,${encoded}`)).blob(),
          );
          const intermediate = document.createElement('canvas');
          intermediate.width = 8; intermediate.height = 600;
          intermediate.getContext('2d').drawImage(source, 0, 0, 8, 600);
          const renderer = document.createElement('canvas');
          renderer.id = 'cover-renderer'; renderer.width = 1200; renderer.height = 800;
          document.body.appendChild(renderer);
          const rendererContext = renderer.getContext('2d');
          rendererContext.drawImage(
            intermediate, 0, 0, 7.5, 599.5, 100, 13, 100, 600,
          );
          const sprite = document.createElement('canvas');
          sprite.width = 2; sprite.height = 2;
          sprite.getContext('2d').fillRect(0, 0, 2, 2);
          rendererContext.save();
          rendererContext.drawImage(
            sprite, 0, 0, 2, 2, spriteX, spriteY, 2, 2,
          );
          rendererContext.restore();
        }
        """,
        {"encoded": encoded, "spriteX": sprite_x, "spriteY": sprite_y},
    )
    selected_draw = await browser_page.evaluate(
        "() => window.__bookwalkerNativeDrawCalls.find(call => call.destination.width === 100)"
    )
    selection_geometry_state = await browser_page.evaluate(
        "() => window.__bookwalkerDirectOneHopGeometryState(document.querySelector('#cover-renderer'))"
    )
    captures = await adapter._capture_direct_one_hop_original_jpeg(
        browser_page,
        browser_page.locator("#cover-renderer"),
        selected_draw,
        selection_geometry_state,
    )
    assert (captures is not None) is accepted
    if accepted:
        assert captures[0].data == jpeg
        assert adapter._capture_debug["bookwalker_capture"][
            "direct_original_jpeg"
        ]["records"][0]["renderer_non_intersecting_draw"] is True
    else:
        debug = adapter._capture_debug["bookwalker_capture"]["direct_original_jpeg"]
        assert debug["records"][0]["reason"] == "renderer record was invalidated after selection"
        assert debug["records"][0]["renderer_first_hard_invalid"]["kind"] == "drawImage"


async def test_direct_one_hop_eviction_keeps_snapshot_budget_bounded(
    browser_page: Page,
) -> None:
    await browser_page.add_init_script(
        "window.__bookwalkerCaptureMode = 'native'; "
        "window.__bookwalkerDirectOriginalEnabled = true;"
    )
    await browser_page.add_init_script(adapter_module._DRAW_TRACE_SCRIPT)
    await browser_page.goto("data:text/html,<html><body></body></html>")
    result = await browser_page.evaluate(
        """
        async () => {
          const materialized = [];
          for (let index = 0; index < 4; index += 1) {
            const sourceCanvas = document.createElement('canvas');
            sourceCanvas.width = 400; sourceCanvas.height = 2000;
            const sourceContext = sourceCanvas.getContext('2d');
            sourceContext.fillStyle = `rgb(${index * 20},40,60)`;
            sourceContext.fillRect(0, 0, 400, 2000);
            const bitmap = await createImageBitmap(sourceCanvas);
            const intermediate = document.createElement('canvas');
            intermediate.width = 400; intermediate.height = 2000;
            intermediate.getContext('2d').drawImage(bitmap, 0, 0, 400, 2000);
            const renderer = document.createElement('canvas');
            renderer.width = 1200; renderer.height = 2000;
            renderer.getContext('2d').drawImage(intermediate, 0, 0, 400, 2000);
            materialized.push(window.__bookwalkerMaterializeDirectOneHop(renderer));
          }
          const records = window.__bookwalkerDirectOneHopRecords;
          return {
            recordCount: records.length,
            snapshotBytes: records.reduce(
              (sum, record) => sum + Number(record.snapshotBytes || 0), 0,
            ),
            materializedCount: materialized.flat().length,
          };
        }
        """,
    )
    assert result["recordCount"] <= 4
    assert result["snapshotBytes"] <= 32 * 1024 * 1024
    assert result["materializedCount"] >= 1


async def test_direct_one_hop_fails_closed_after_geometry_ledger_eviction(
    browser_page: Page,
) -> None:
    jpeg = _patterned_cover_jpeg()
    adapter = BookWalkerAdapter()
    candidate = adapter_module.candidate_from_jpeg(
        jpeg,
        url="https://bw-bv-epubs.bookwalker.jp/cover.jpg",
        sequence=1,
    )
    assert candidate is not None
    adapter._original_candidates.add(candidate)
    await browser_page.add_init_script(
        "window.__bookwalkerCaptureMode = 'native'; "
        "window.__bookwalkerDirectOriginalEnabled = true;"
    )
    await browser_page.add_init_script(adapter_module._DRAW_TRACE_SCRIPT)
    await browser_page.goto("data:text/html,<html><body></body></html>")
    encoded = base64.b64encode(jpeg).decode("ascii")
    selection_result = await browser_page.evaluate(
        """
        async ({encoded}) => {
          const counter = document.createElement('div');
          counter.id = 'pageSliderCounter'; counter.textContent = '1/322';
          document.body.appendChild(counter);
          const source = await createImageBitmap(
            await (await fetch(`data:image/jpeg;base64,${encoded}`)).blob(),
          );
          const intermediate = document.createElement('canvas');
          intermediate.width = 8; intermediate.height = 600;
          intermediate.getContext('2d').drawImage(source, 0, 0, 8, 600);
          const renderer = document.createElement('canvas');
          renderer.id = 'cover-renderer'; renderer.width = 1200; renderer.height = 800;
          document.body.appendChild(renderer);
          renderer.getContext('2d').drawImage(
            intermediate, 0, 0, 7.5, 599.5, 100, 13, 100, 600,
          );
          const selectedDraw = window.__bookwalkerNativeDrawCalls.at(-1);
          const selectionState = window.__bookwalkerDirectOneHopGeometryState(renderer);
          window.__bookwalkerNativeCaptureEnabled = false;
          const filler = document.createElement('canvas');
          filler.width = 100; filler.height = 100;
          filler.getContext('2d').fillRect(0, 0, 100, 100);
          const context = renderer.getContext('2d');
          for (let index = 0; index < 8193; index += 1) {
            context.drawImage(filler, 0, 0, 100, 100);
          }
          return {selectedDraw, selectionState};
        }
        """,
        {"encoded": encoded},
    )
    selected_draw = selection_result["selectedDraw"]
    selection_geometry_state = selection_result["selectionState"]
    assert (
        await adapter._capture_direct_one_hop_original_jpeg(
            browser_page, browser_page.locator("#cover-renderer"), selected_draw,
            selection_geometry_state,
        )
        is None
    )
    direct = adapter._capture_debug["bookwalker_capture"]["direct_original_jpeg"]
    assert direct["records"][0]["geometry_history_incomplete"] is True
    assert direct["records"][0]["reason"] == "direct cover geometry history incomplete"


async def test_disabled_direct_window_keeps_legacy_draw_ledger_bound(
    browser_page: Page,
) -> None:
    await browser_page.add_init_script(
        "window.__bookwalkerCaptureMode = 'native'; "
        "window.__bookwalkerDirectOriginalEnabled = false;"
    )
    await browser_page.add_init_script(adapter_module._DRAW_TRACE_SCRIPT)
    await browser_page.goto("data:text/html,<html><body></body></html>")
    length = await browser_page.evaluate(
        """() => {
          const source = document.createElement('canvas');
          source.width = 2; source.height = 2;
          source.getContext('2d').fillRect(0, 0, 2, 2);
          const target = document.createElement('canvas');
          target.width = 1200; target.height = 800;
          document.body.appendChild(target);
          const context = target.getContext('2d');
          for (let index = 0; index < 501; index += 1) {
                context.drawImage(source, 0, 0, 2, 2, 0, 0, 100, 100);
          }
          return window.__bookwalkerDrawCalls.length;
        }""",
    )
    assert length == 500


async def test_small_native_candidates_are_dropped_without_dropping_trace_records(
    browser_page: Page,
) -> None:
    await browser_page.add_init_script(
        "window.__bookwalkerCaptureMode = 'native'; "
        "window.__bookwalkerDirectOriginalEnabled = false;"
    )
    await browser_page.add_init_script(adapter_module._DRAW_TRACE_SCRIPT)
    await browser_page.goto("data:text/html,<html><body></body></html>")
    result = await browser_page.evaluate(
        """
        () => {
          const source = document.createElement('canvas');
          source.width = 128; source.height = 128;
          source.getContext('2d').fillRect(0, 0, 128, 128);
          const small = document.createElement('canvas');
          small.width = 4; small.height = 4;
          small.getContext('2d').fillRect(0, 0, 4, 4);
          const target = document.createElement('canvas');
          target.width = 1200; target.height = 800;
          document.body.appendChild(target);
          const context = target.getContext('2d');
          context.drawImage(source, 0, 0, 128, 128, 100, 0, 800, 600);
          for (let index = 0; index < 200; index += 1) {
            context.drawImage(small, 0, 0, 4, 4, 10, 10, 99, 2);
          }
          // Fractional eligibility is retained for the authoritative Python
          // selector instead of being decided by the browser-side filter.
          context.drawImage(small, 0, 0, 4, 4, 10, 10, 99.5, 200);
          context.drawImage(small, 0, 0, 4, 4, 10, 10, 100, 100);
          context.drawImage(small, 0, 0, 4, 4, 10, 10, -1, 200);
          context.drawImage(small, 0, 0, 4, 4, 10, 10, NaN, 200);
          const diagnostics = window.__bookwalkerNativeCaptureDiagnostics;
          return {
            diagnostics,
            nativeCount: window.__bookwalkerNativeDrawCalls.length,
            geometryCount: window.__bookwalkerDrawCalls.length,
            nativeCalls: window.__bookwalkerNativeDrawCalls.map(call => ({
              operation: call.traceOperationIndex,
              destination: call.destination,
            })),
            drawImageCount: window.__bookwalkerTransformTrace.diagnostics.drawImageCount,
          };
        }
        """,
    )
    assert result["diagnostics"] == {
        "nativeCallsSeen": 205,
        "nativeCallsAdmitted": 5,
        "nativeCallsRetained": 5,
        "nativeCallsEvicted": 0,
        "definitelySmallCallsDropped": 200,
        "geometrySmallCallsDropped": 200,
        "executedFullClearWitnessCount": 0,
        "rejectedFullClearWitnessCount": 0,
    }
    assert result["nativeCount"] == 5
    assert result["geometryCount"] == 5
    assert result["nativeCalls"][0]["destination"]["width"] == 800
    assert result["nativeCalls"][0]["destination"]["height"] == 600
    assert result["nativeCalls"][1]["destination"]["width"] == 99.5
    assert result["nativeCalls"][1]["destination"]["height"] == 200
    assert result["nativeCalls"][2]["destination"]["width"] == 100
    assert result["nativeCalls"][3]["destination"]["width"] == -1
    assert result["drawImageCount"] == 205


@pytest.mark.parametrize("offscreen_count, current_retained", [(99, True), (100, False)])
async def test_native_candidate_cap_boundary_remains_bounded(
    browser_page: Page,
    offscreen_count: int,
    current_retained: bool,
) -> None:
    await browser_page.add_init_script(
        "window.__bookwalkerCaptureMode = 'native'; "
        "window.__bookwalkerDirectOriginalEnabled = false;"
    )
    await browser_page.add_init_script(adapter_module._DRAW_TRACE_SCRIPT)
    await browser_page.goto("data:text/html,<html><body></body></html>")
    result = await browser_page.evaluate(
        """
        ({offscreenCount}) => {
          const source = document.createElement('canvas');
          source.width = 128; source.height = 128;
          source.getContext('2d').fillRect(0, 0, 128, 128);
          const target = document.createElement('canvas');
          target.width = 1200; target.height = 800;
          document.body.appendChild(target);
          const context = target.getContext('2d');
          context.drawImage(source, 0, 0, 128, 128, 100, 0, 800, 600);
          const currentOperation = window.__bookwalkerNativeDrawCalls[0].traceOperationIndex;
          for (let index = 0; index < offscreenCount; index += 1) {
            context.drawImage(source, 0, 0, 128, 128, 200, 0, 100, 100);
          }
          const diagnostics = window.__bookwalkerNativeCaptureDiagnostics;
          return {
            diagnostics,
            nativeCount: window.__bookwalkerNativeDrawCalls.length,
            geometryCount: window.__bookwalkerDrawCalls.length,
            currentRetained: window.__bookwalkerNativeDrawCalls.some(
              call => call.traceOperationIndex === currentOperation,
            ),
            drawImageCount: window.__bookwalkerTransformTrace.diagnostics.drawImageCount,
          };
        }
        """,
        {"offscreenCount": offscreen_count},
    )
    assert result["nativeCount"] == 100
    assert result["geometryCount"] == offscreen_count + 1
    assert result["currentRetained"] is current_retained
    assert result["diagnostics"] == {
        "nativeCallsSeen": offscreen_count + 1,
        "nativeCallsAdmitted": offscreen_count + 1,
        "nativeCallsRetained": 100,
        "nativeCallsEvicted": max(0, offscreen_count - 99),
        "definitelySmallCallsDropped": 0,
        "geometrySmallCallsDropped": 0,
        "executedFullClearWitnessCount": 0,
        "rejectedFullClearWitnessCount": 0,
    }
    assert result["drawImageCount"] == offscreen_count + 1


async def test_large_prefetch_tile_flood_does_not_evict_current_native_candidate(
    browser_page: Page,
) -> None:
    await browser_page.add_init_script(
        "window.__bookwalkerCaptureMode = 'native'; "
        "window.__bookwalkerDirectOriginalEnabled = false;"
    )
    await browser_page.add_init_script(adapter_module._DRAW_TRACE_SCRIPT)
    await browser_page.goto("data:text/html,<html><body></body></html>")
    result = await browser_page.evaluate(
        """
        () => {
          const source = document.createElement('canvas');
          source.width = 128; source.height = 128;
          source.getContext('2d').fillRect(0, 0, 128, 128);
          const current = document.createElement('canvas');
          current.width = 1200; current.height = 800;
          document.body.appendChild(current);
          current.getContext('2d').drawImage(
            source, 0, 0, 128, 128, 100, 0, 800, 600,
          );
          const tile = document.createElement('canvas');
          tile.width = 32; tile.height = 32;
          tile.getContext('2d').fillRect(0, 0, 32, 32);
          const prefetch = document.createElement('canvas');
          prefetch.width = 1443; prefetch.height = 2048;
          const context = prefetch.getContext('2d');
          for (let index = 0; index < 2944; index += 1) {
            const x = (index % 45) * 32;
            const y = Math.floor(index / 45) * 32;
            context.drawImage(tile, 0, 0, 32, 32, x, y, 32, 32);
          }
          const diagnostics = window.__bookwalkerNativeCaptureDiagnostics;
          return {
            diagnostics,
            nativeCount: window.__bookwalkerNativeDrawCalls.length,
            geometryCount: window.__bookwalkerDrawCalls.length,
            currentDestination: window.__bookwalkerNativeDrawCalls[0]?.destination,
            drawImageCount: window.__bookwalkerTransformTrace.diagnostics.drawImageCount,
          };
        }
        """,
    )
    assert result["nativeCount"] == 1
    assert result["geometryCount"] == 1
    assert result["currentDestination"]["width"] == 800
    assert result["currentDestination"]["height"] == 600
    assert result["diagnostics"] == {
        "nativeCallsSeen": 2945,
        "nativeCallsAdmitted": 1,
        "nativeCallsRetained": 1,
        "nativeCallsEvicted": 0,
        "definitelySmallCallsDropped": 2944,
        "geometrySmallCallsDropped": 2944,
        "executedFullClearWitnessCount": 0,
        "rejectedFullClearWitnessCount": 0,
    }
    assert result["drawImageCount"] == 2945


@pytest.mark.parametrize("flood_on_current", [False, True])
async def test_small_prefetch_flood_over_geometry_limit_is_filtered_before_ledger(
    browser_page: Page,
    flood_on_current: bool,
) -> None:
    await browser_page.add_init_script(
        "window.__bookwalkerCaptureMode = 'native'; "
        "window.__bookwalkerDirectOriginalEnabled = true;"
    )
    await browser_page.add_init_script(adapter_module._DRAW_TRACE_SCRIPT)
    await browser_page.goto("data:text/html,<html><body></body></html>")
    result = await browser_page.evaluate(
        """
        floodOnCurrent => {
          const source = document.createElement('canvas');
          source.width = 128; source.height = 128;
          source.getContext('2d').fillRect(0, 0, 128, 128);
          const current = document.createElement('canvas');
          current.width = 1200; current.height = 800;
          document.body.appendChild(current);
          current.getContext('2d').drawImage(
            source, 0, 0, 128, 128, 100, 0, 800, 600,
          );
          const prefetch = document.createElement('canvas');
          prefetch.width = 1443; prefetch.height = 2048;
          const context = (floodOnCurrent ? current : prefetch).getContext('2d');
          for (let index = 0; index < 8201; index += 1) {
            context.drawImage(source, 0, 0, 128, 128, 0, 0, 32, 32);
          }
          const diagnostics = window.__bookwalkerNativeCaptureDiagnostics;
          return {
            diagnostics,
            nativeCount: window.__bookwalkerNativeDrawCalls.length,
            geometryCount: window.__bookwalkerDrawCalls.length,
            currentDestination: window.__bookwalkerNativeDrawCalls[0]?.destination,
            drawImageCount: window.__bookwalkerTransformTrace.diagnostics.drawImageCount,
          };
        }
        """,
        flood_on_current,
    )
    assert result["nativeCount"] == 1
    assert result["geometryCount"] == 1
    assert result["currentDestination"]["width"] == 800
    assert result["diagnostics"] == {
        "nativeCallsSeen": 8202,
        "nativeCallsAdmitted": 1,
        "nativeCallsRetained": 1,
        "nativeCallsEvicted": 0,
        "definitelySmallCallsDropped": 8201,
        "geometrySmallCallsDropped": 8201,
        "executedFullClearWitnessCount": 0,
        "rejectedFullClearWitnessCount": 0,
    }
    assert result["drawImageCount"] == 8202


async def test_capture_page_automatically_returns_direct_cover_jpeg(
    browser_page: Page,
) -> None:
    class DirectCoverAdapter(BookWalkerAdapter):
        async def get_capture_target(self, page: Page):
            return page.locator("#cover-renderer")

        async def _page_draw_rectangles(self, page: Page, canvas):
            return [{"x": 100, "y": 13, "width": 100, "height": 600}]

        async def _is_first_page(self, page: Page) -> bool:
            return True

    jpeg = _patterned_cover_jpeg()
    adapter = DirectCoverAdapter()
    adapter.capture_mode = "native"
    adapter.enable_original_jpeg_capture = True
    candidate = adapter_module.candidate_from_jpeg(
        jpeg,
        url="https://bw-bv-epubs.bookwalker.jp/cover.jpg",
        sequence=1,
    )
    assert candidate is not None
    adapter._original_candidates.add(candidate)
    await browser_page.add_init_script(
        "window.__bookwalkerCaptureMode = 'native'; "
        "window.__bookwalkerDirectOriginalEnabled = true;"
    )
    await browser_page.add_init_script(adapter_module._DRAW_TRACE_SCRIPT)
    await browser_page.goto("data:text/html,<html><body></body></html>")
    encoded = base64.b64encode(jpeg).decode("ascii")
    await browser_page.evaluate(
        """
        async ({encoded}) => {
          const counter = document.createElement('div');
          counter.id = 'pageSliderCounter'; counter.textContent = '1/322';
          document.body.appendChild(counter);
          const source = await createImageBitmap(
            await (await fetch(`data:image/jpeg;base64,${encoded}`)).blob(),
          );
          const intermediate = document.createElement('canvas');
          intermediate.width = 8; intermediate.height = 600;
          intermediate.getContext('2d').drawImage(source, 0, 0, 8, 600);
          const renderer = document.createElement('canvas');
          renderer.id = 'cover-renderer'; renderer.width = 1200; renderer.height = 800;
          document.body.appendChild(renderer);
          const context = renderer.getContext('2d');
          context.drawImage(intermediate, 0, 0, 7.5, 599.5, 100, 13, 100, 600);
          context.fillStyle = 'rgba(255,0,0,1)';
          context.fillRect(10, 10, 2, 2);
        }
        """,
        {"encoded": encoded},
    )
    captures = await adapter.capture_page(browser_page)
    assert captures is not None
    assert captures[0].data == jpeg
    assert captures[0].mime_type == "image/jpeg"
    assert adapter._capture_debug["bookwalker_capture"]["returned_path"] == (
        "direct_original_jpeg"
    )
    direct = adapter._capture_debug["bookwalker_capture"]["direct_original_jpeg"]
    assert direct["selected_native_draw"]["trace_operation_index"] == direct["records"][0][
        "renderer_operation"
    ]


async def test_capture_page_default_proves_executed_clear_scaled_reconstruction(
    browser_page: Page,
) -> None:
    """The normal adapter path accepts a complete executed-clear chain."""

    class ScaledAdapter(BookWalkerAdapter):
        async def get_capture_target(self, page: Page):
            return page.locator("#scaled-renderer")

        async def _page_draw_rectangles(self, page: Page, canvas):
            return [{"x": 0, "y": 0, "width": 1200, "height": 800}]

        async def _is_first_page(self, page: Page) -> bool:
            return False

    jpeg = _solid_large_jpeg()
    adapter = ScaledAdapter()
    adapter._initial_content_id = "synthetic-executed-clear"
    adapter.capture_mode = "native"
    adapter.enable_original_jpeg_capture = True
    adapter.lossless_jpeg_output_enabled = True
    candidate = adapter_module.candidate_from_jpeg(
        jpeg,
        url="https://bw-bv-epubs.bookwalker.jp/scaled.jpg",
        sequence=1,
    )
    assert candidate is not None
    adapter._original_candidates.add(candidate)
    await browser_page.add_init_script(
        "window.__bookwalkerCaptureMode = 'native'; "
        "window.__bookwalkerDirectOriginalEnabled = true;"
    )
    await browser_page.add_init_script(adapter_module._DRAW_TRACE_SCRIPT)
    async def fulfill(route) -> None:
        await route.fulfill(content_type="text/html", body="<html><body></body></html>")

    await browser_page.route("https://viewer.bookwalker.jp/**", fulfill)
    await browser_page.goto(
        "https://viewer.bookwalker.jp/03/30/viewer.html?cid=synthetic-executed-clear"
    )
    encoded = base64.b64encode(jpeg).decode("ascii")
    await browser_page.evaluate(
        """
        async encoded => {
          document.body.innerHTML = `
            <div id="pageSliderCounter">2/3</div>
            <div id="renderer"><div class="currentScreen">
              <canvas id="scaled-renderer" width="1200" height="800"></canvas>
            </div></div>`;
          const source = await createImageBitmap(
            await (await fetch(`data:image/jpeg;base64,${encoded}`)).blob(),
          );
          const upstream = document.createElement('canvas');
          upstream.width = 1443; upstream.height = 2048;
          const upstreamContext = upstream.getContext('2d');
          upstreamContext.fillStyle = 'rgb(1,2,3)';
          upstreamContext.fillRect(0, 0, upstream.width, upstream.height);
          upstreamContext.clearRect(0, 0, upstream.width, upstream.height);
          upstreamContext.drawImage(
            source, 0, 0, 1448, 2048, 0, 0, 1448, 2048,
          );
          const intermediate = document.createElement('canvas');
          intermediate.width = 722; intermediate.height = 1024;
          intermediate.getContext('2d').drawImage(
            upstream, 0, 0, 1443, 2048, 0, 0, 722, 1024,
          );
          const renderer = document.querySelector('#scaled-renderer');
          renderer.width = 1200;
          renderer.height = 800;
          renderer.setAttribute(
            'data-bookwalker-trace-id',
            String(window.__bookwalkerCanvasIdentity(renderer)),
          );
          renderer.getContext('2d').drawImage(
            intermediate, 0, 0, 722, 1024, 0, 0, 1200, 800,
          );
        }
        """,
        encoded,
    )
    captures = await adapter.capture_page(browser_page)
    assert captures is not None
    assert len(captures) == 1
    if captures[0].mime_type != "image/jpeg":
        raise AssertionError(adapter._capture_debug)
    assert captures[0].mime_type == "image/jpeg"
    output_image = Image.open(BytesIO(captures[0].data)).convert("RGBA")
    expected_image = Image.open(BytesIO(jpeg)).convert("RGBA").crop(
        (0, 0, 1443, 2048)
    )
    assert output_image.size == expected_image.size
    assert output_image.tobytes() == expected_image.tobytes()
    capture_debug = adapter._capture_debug["bookwalker_capture"]
    assert capture_debug["returned_path"] == "reconstructed_jpeg"
    shadow = capture_debug["lossless_shadow"]
    assert shadow["spread_ready"] is True, shadow
    parts = shadow["parts"]
    assert len(parts) == 1
    assert parts[0]["executed_clear_provenance"] is True
    assert parts[0]["raw_jpeg_exact"] is True
    assert parts[0]["cropped_chain_pixel_exact"] is True
    assert parts[0]["cropped_chain_pixel_comparison"]["p4b_atomic_current_roi"][
        "exact"
    ] is True


async def test_capture_page_does_not_use_direct_for_cover_union(
    browser_page: Page,
) -> None:
    class UnionCoverAdapter(BookWalkerAdapter):
        async def get_capture_target(self, page: Page):
            return page.locator("#cover-renderer")

        async def _page_draw_rectangles(self, page: Page, canvas):
            return [
                {"x": 0, "y": 0, "width": 500, "height": 800},
                {"x": 500, "y": 0, "width": 500, "height": 800},
            ]

        async def _is_first_page(self, page: Page) -> bool:
            return True

    adapter = UnionCoverAdapter()
    adapter.capture_mode = "native"
    adapter.enable_original_jpeg_capture = True
    await browser_page.add_init_script(
        "window.__bookwalkerCaptureMode = 'native'; "
        "window.__bookwalkerDirectOriginalEnabled = true;"
    )
    await browser_page.add_init_script(adapter_module._DRAW_TRACE_SCRIPT)
    await browser_page.goto("data:text/html,<html><body></body></html>")
    await browser_page.evaluate(
        """() => {
          const counter = document.createElement('div');
          counter.id = 'pageSliderCounter'; counter.textContent = '1/322';
          document.body.appendChild(counter);
          const renderer = document.createElement('canvas');
          renderer.id = 'cover-renderer'; renderer.width = 1200; renderer.height = 800;
          document.body.appendChild(renderer);
        }"""
    )
    captures = await adapter.capture_page(browser_page)
    assert captures is None
    assert adapter._capture_debug["bookwalker_capture"].get(
        "direct_original_jpeg"
    ) is None


async def test_direct_one_hop_falls_back_after_renderer_mutation(
    browser_page: Page,
) -> None:
    jpeg = _patterned_cover_jpeg()
    adapter = BookWalkerAdapter()
    candidate = adapter_module.candidate_from_jpeg(
        jpeg,
        url="https://bw-bv-epubs.bookwalker.jp/cover.jpg",
        sequence=1,
    )
    assert candidate is not None
    adapter._original_candidates.add(candidate)
    await browser_page.add_init_script(
        "window.__bookwalkerCaptureMode = 'native'; "
        "window.__bookwalkerDirectOriginalEnabled = true;"
    )
    await browser_page.add_init_script(adapter_module._DRAW_TRACE_SCRIPT)
    await browser_page.goto("data:text/html,<html><body></body></html>")
    encoded = base64.b64encode(jpeg).decode("ascii")
    await browser_page.evaluate(
        """
        async ({encoded}) => {
          const counter = document.createElement('div');
          counter.id = 'pageSliderCounter'; counter.textContent = '1/322';
          document.body.appendChild(counter);
          const source = await createImageBitmap(
            await (await fetch(`data:image/jpeg;base64,${encoded}`)).blob(),
          );
          const intermediate = document.createElement('canvas');
          intermediate.width = 8; intermediate.height = 600;
          intermediate.getContext('2d').drawImage(source, 0, 0, 8, 600);
          const renderer = document.createElement('canvas');
          renderer.id = 'cover-renderer'; renderer.width = 1200; renderer.height = 800;
          renderer.__bookwalkerTestIntermediate = intermediate;
          document.body.appendChild(renderer);
          const context = renderer.getContext('2d');
          context.drawImage(intermediate, 0, 0, 7.5, 599.5, 100, 13, 100, 600);
          context.fillStyle = 'rgba(255,0,0,1)';
          context.fillRect(110, 20, 2, 2);
        }
        """,
        {"encoded": encoded},
    )
    initial_selected_draw = await browser_page.evaluate(
        "() => window.__bookwalkerNativeDrawCalls.at(-1)"
    )
    initial_selection_geometry_state = await browser_page.evaluate(
        "() => window.__bookwalkerDirectOneHopGeometryState(document.querySelector('#cover-renderer'))"
    )
    captures = await adapter._capture_direct_one_hop_original_jpeg(
        browser_page,
        browser_page.locator("#cover-renderer"),
        initial_selected_draw,
        initial_selection_geometry_state,
    )
    assert captures is None
    debug = adapter._capture_debug["bookwalker_capture"]["direct_original_jpeg"]
    assert debug["records"][0]["renderer_mutation"] == "fillRect"
    assert debug["records"][0]["reason"] == "direct output-equivalence mismatch"
    await browser_page.evaluate(
        """() => {
          const renderer = document.querySelector('#cover-renderer');
          const intermediate = renderer.__bookwalkerTestIntermediate;
          renderer.getContext('2d').drawImage(intermediate, 0, 0, 7.5, 599.5, 700, 13, 100, 600);
        }""",
    )
    # The fixture stores the source explicitly so the follow-up drawImage
    # remains a real replacement operation rather than a synthetic flag.
    selected_draw = await browser_page.evaluate(
        "() => window.__bookwalkerNativeDrawCalls.at(-1)"
    )
    # A different page-relevant geometry must not be accepted against the
    # initial selection stamp, even though the current draw is otherwise a
    # valid single-cover candidate.  This models left -> right before the
    # later left redraw and keeps the initial geometry join fail-closed.
    stale_geometry_capture = await adapter._capture_direct_one_hop_original_jpeg(
        browser_page,
        browser_page.locator("#cover-renderer"),
        selected_draw,
        initial_selection_geometry_state,
    )
    assert stale_geometry_capture is None
    stale_debug = adapter._capture_debug["bookwalker_capture"][
        "direct_original_jpeg"
    ]
    stale_record = next(
        row for row in stale_debug["records"]
        if row.get("renderer_operation") == selected_draw["traceOperationIndex"]
    )
    assert stale_record["reason"] == "direct cover geometry changed before validation"
    await browser_page.evaluate(
        """() => {
          const renderer = document.querySelector('#cover-renderer');
          const intermediate = renderer.__bookwalkerTestIntermediate;
          renderer.getContext('2d').drawImage(intermediate, 0, 0, 7.5, 599.5, 100, 13, 100, 600);
        }""",
    )
    selected_draw = await browser_page.evaluate(
        "() => window.__bookwalkerNativeDrawCalls.at(-1)"
    )
    selection_geometry_state = await browser_page.evaluate(
        "() => window.__bookwalkerDirectOneHopGeometryState(document.querySelector('#cover-renderer'))"
    )
    captures = await adapter._capture_direct_one_hop_original_jpeg(
        browser_page,
        browser_page.locator("#cover-renderer"),
        selected_draw,
        selection_geometry_state,
    )
    assert captures is not None
    debug = adapter._capture_debug["bookwalker_capture"]["direct_original_jpeg"]
    old_record = next(
        row for row in debug["records"]
        if row.get("renderer_operation") == initial_selected_draw["traceOperationIndex"]
    )
    assert old_record["renderer_geometry_version"] < old_record["current_geometry_version"]
    assert old_record["reason"] == "renderer operation is not the selected native draw"
    latest_record = next(
        row for row in debug["records"]
        if row.get("renderer_operation") == selected_draw["traceOperationIndex"]
    )
    assert latest_record["reason"] == "direct output-equivalence exact"
    assert debug["accepted"] is True
    first_hard_invalid = debug["records"][0]["renderer_first_hard_invalid"]
    assert first_hard_invalid["kind"] == "drawImage"
    assert first_hard_invalid["operationIndex"] > debug["records"][0]["renderer_operation"]
    assert first_hard_invalid["target"]["constructor"] == "HTMLCanvasElement"
    await browser_page.evaluate(
        """() => {
          const renderer = document.querySelector('#cover-renderer');
          const context = renderer.getContext('2d');
          renderer.__bookwalkerValidationMutationTimer = setInterval(
            () => context.fillRect(0, 0, 1, 1), 0,
          );
        }""",
    )
    try:
        await browser_page.wait_for_timeout(5)
        validation_capture = await adapter._capture_direct_one_hop_original_jpeg(
            browser_page,
            browser_page.locator("#cover-renderer"),
            selected_draw,
            selection_geometry_state,
        )
    finally:
        await browser_page.evaluate(
            """() => {
              const renderer = document.querySelector('#cover-renderer');
              clearInterval(renderer.__bookwalkerValidationMutationTimer);
            }""",
        )
    assert validation_capture is None
    validation_debug = adapter._capture_debug["bookwalker_capture"][
        "direct_original_jpeg"
    ]
    validation_record = next(
        row for row in validation_debug["records"]
        if row.get("renderer_operation") == selected_draw["traceOperationIndex"]
    )
    assert validation_record["reason"] in {
        "direct cover geometry changed before validation",
        "renderer geometry changed during validation",
        "direct hook changed during validation",
        "direct output-equivalence mismatch",
    }
    # A legal JPEG COM marker changes the candidate bytes without changing
    # decoded pixels.  The direct path must reject this ambiguity itself;
    # the older tiled reconstruction ambiguity test is not a substitute.
    ambiguous_jpeg = jpeg[:2] + b"\xff\xfe\x00\x04AB" + jpeg[2:]
    ambiguous_candidate = adapter_module.candidate_from_jpeg(
        ambiguous_jpeg,
        url="https://bw-bv-epubs.bookwalker.jp/cover-com-marker.jpg",
        sequence=2,
    )
    assert ambiguous_candidate is not None
    adapter._original_candidates.add(ambiguous_candidate)
    ambiguous_capture = await adapter._capture_direct_one_hop_original_jpeg(
        browser_page,
        browser_page.locator("#cover-renderer"),
        selected_draw,
        selection_geometry_state,
    )
    assert ambiguous_capture is None
    ambiguous_debug = adapter._capture_debug["bookwalker_capture"][
        "direct_original_jpeg"
    ]
    ambiguous_record = next(
        row for row in ambiguous_debug["records"]
        if row.get("renderer_operation") == selected_draw["traceOperationIndex"]
    )
    assert ambiguous_record["exact_candidate_count"] == 2
    assert ambiguous_record["reason"] == "direct JPEG candidate is not unique"
