from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest
from playwright.async_api import Error, Page, async_playwright

from screenshot_crawler.core.capture import CaptureResult
from screenshot_crawler.site_adapters.bookwalker import adapter as adapter_module
from screenshot_crawler.site_adapters.bookwalker.adapter import BookWalkerAdapter
from screenshot_crawler.site_adapters.bookwalker.original_capture import (
    OriginalJpegCache,
    candidate_capture,
    candidate_from_jpeg,
    image_signature,
    is_jpeg_bytes,
    jpeg_dimensions,
)

JPEG_1X1 = (
    b"\xff\xd8\xff\xe0\x00\x04\x00\x00"
    b"\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03"
    b"\x01\x11\x00\x02\x11\x00\x03\x11\x00\xff\xd9"
)
PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x04\x00\x00\x00\xb5\x1c\x0c\x02"
    b"\x00\x00\x00\x0bIDAT\x08\xd7c\x9a\xc0\xf0\x1f\x00\x05\x01\x01\x02"
    b"\x1b\xc9\x8d\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _candidate(data: bytes = JPEG_1X1, *, sequence: int = 1):
    candidate = candidate_from_jpeg(
        data,
        url="https://viewer-epubs-trial.bookwalker.jp/path/page.jpegbvCoverImage?redacted=1",
        sequence=sequence,
        fetched_at=1.0,
    )
    assert candidate is not None
    return candidate


def test_jpeg_magic_dimensions_and_capture_result() -> None:
    assert is_jpeg_bytes(JPEG_1X1)
    assert jpeg_dimensions(JPEG_1X1) == (1, 1)

    result = candidate_capture(_candidate())

    assert isinstance(result, CaptureResult)
    assert result.data == JPEG_1X1
    assert (result.width, result.height) == (1, 1)
    assert result.mime_type == "image/jpeg"
    assert result.file_extension == ".jpg"


def test_invalid_jpeg_magic_or_dimensions_is_rejected() -> None:
    assert not is_jpeg_bytes(PNG_1X1)
    assert jpeg_dimensions(PNG_1X1) is None
    assert candidate_from_jpeg(
        b"\xff\xd8\xff\xe0\x00\x04\x00\x00",
        url="https://viewer-epubs-trial.bookwalker.jp/page.jpeg",
        sequence=1,
    ) is None


def test_original_jpeg_cache_deduplicates_and_evicts_old_entries() -> None:
    cache = OriginalJpegCache(max_entries=2, max_bytes=1024)
    first = _candidate(sequence=1)
    second = _candidate(JPEG_1X1 + b"a", sequence=2)
    third = _candidate(JPEG_1X1 + b"b", sequence=3)

    assert cache.add(first)
    assert not cache.add(first)
    assert cache.add(second)
    assert cache.add(third)
    assert len(cache) == 2
    assert cache.total_bytes == len(second.data) + len(third.data)
    assert [item.sequence for item in cache.values()] == [2, 3]


class _FakeResponse:
    def __init__(self) -> None:
        self.url = (
            "https://viewer-epubs-trial.bookwalker.jp/"
            "path/0.jpegbvCoverImage?redacted=1"
        )
        self.status = 200
        self.headers = {
            "content-type": "image/jpeg",
            "content-length": str(len(JPEG_1X1)),
        }
        self.request = SimpleNamespace(resource_type="xhr")

    async def body(self) -> bytes:
        return JPEG_1X1


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


@pytest.mark.asyncio
async def test_original_jpeg_capture_is_enabled_for_production_runs() -> None:
    adapter = adapter_module.BookWalkerAdapter()
    page = _PreparePage()

    await adapter.prepare_page(page)  # type: ignore[arg-type]

    assert adapter.enable_original_jpeg_capture
    assert page.listener_count == 1
    assert page.route_count == 2


@pytest.mark.asyncio
async def test_native_capture_mode_init_script_controls_trace(
    browser_page: Page,
) -> None:
    adapter = BookWalkerAdapter()
    prepared = _PreparePage()
    await adapter.prepare_page(prepared)  # type: ignore[arg-type]
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
            await context.close()

    draw_script = adapter_module._DRAW_TRACE_SCRIPT
    assert await evaluate_scripts(
        "https://viewer.bookwalker.jp/order-a",
        ("window.__bookwalkerCaptureMode = 'native';", draw_script),
    ) == {"mode": "native", "enabled": True, "installed": True}
    assert await evaluate_scripts(
        "https://viewer.bookwalker.jp/production",
        (mode_script, draw_script),
    ) == {"mode": "native", "enabled": True, "installed": True}
    assert await evaluate_scripts(
        "https://trial.bookwalker.jp/production",
        ("window.__bookwalkerCaptureMode = 'canvas';", draw_script),
    ) == {"mode": "canvas", "enabled": False, "installed": True}


@pytest.mark.asyncio
async def test_canvas_mode_does_not_install_original_jpeg_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOOKWALKER_CAPTURE_MODE", "canvas")
    adapter = BookWalkerAdapter()
    page = _PreparePage()

    await adapter.prepare_page(page)  # type: ignore[arg-type]

    assert adapter.capture_mode == "canvas"
    assert page.listener_count == 0
    assert page.route_count == 0


@pytest.mark.asyncio
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

          rendererContext.drawImage(source, 0, 0, 2, 2, 0, 0, 2, 2);
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


@pytest.mark.asyncio
async def test_response_body_listener_is_host_limited_and_redacts_url() -> None:
    adapter = BookWalkerAdapter()
    await adapter._read_original_response(_FakeResponse())

    assert len(adapter._original_candidates) == 1
    candidate = adapter._original_candidates.values()[0]
    assert candidate.mime_type == "image/jpeg"
    assert "?" not in candidate.redacted_url
    assert candidate.redacted_url.endswith("/path/0.jpegbvCoverImage")

    assert adapter._is_original_response(_FakeResponse())
    assert adapter._is_original_response(
        SimpleNamespace(
            url="https://bw-bv-epubs.bookwalker.jp/03/30/normal_default/page.jpeg",
            request=SimpleNamespace(resource_type="xhr"),
            headers={"content-type": "image/jpeg"},
        )
    )
    assert not adapter._is_original_response(
        SimpleNamespace(
            url="https://viewer.bookwalker.jp/path/page.jpeg",
            request=SimpleNamespace(resource_type="xhr"),
            headers={"content-type": "image/jpeg"},
        )
    )
    assert not adapter._is_original_response(
        SimpleNamespace(
            url="https://viewer-epubs-trial.bookwalker.jp/path/page.jpeg",
            request=SimpleNamespace(resource_type="stylesheet"),
            headers={"content-type": "image/jpeg"},
        )
    )


@pytest.fixture
async def browser_page() -> Page:
    playwright = await async_playwright().start()
    try:
        browser = await playwright.chromium.launch(headless=True)
    except Error as exc:
        await playwright.stop()
        pytest.skip(f"Chromium is unavailable: {exc}")
    page = await browser.new_page()
    try:
        yield page
    finally:
        await browser.close()
        await playwright.stop()


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_unique_signature_match_returns_jpeg_and_ambiguous_match_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_signature(_page: object, data: bytes, mime_type: str) -> str:
        return (
            "native"
            if mime_type == "image/png"
            or data.endswith((b"native", b"native2"))
            else "other"
        )

    monkeypatch.setattr(adapter_module, "image_signature", fake_signature)
    adapter = BookWalkerAdapter()
    native = CaptureResult(PNG_1X1, 1, 1)
    matching = _candidate(JPEG_1X1 + b"native", sequence=1)
    adapter._original_candidates.add(matching)

    result = await adapter._capture_original_jpegs(SimpleNamespace(), (native,))

    assert result is not None
    assert result[0].mime_type == "image/jpeg"
    assert result[0].file_extension == ".jpg"
    assert result[0].data == matching.data

    ambiguous = BookWalkerAdapter()
    ambiguous._original_candidates.add(matching)
    ambiguous._original_candidates.add(_candidate(JPEG_1X1 + b"native2", sequence=2))
    assert await ambiguous._capture_original_jpegs(SimpleNamespace(), (native,)) is None


@pytest.mark.asyncio
async def test_original_capture_retries_twice_then_returns_native_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_signature(_page: object, _data: bytes, _mime_type: str) -> str:
        return "native"

    monkeypatch.setattr(adapter_module, "image_signature", fake_signature)
    adapter = BookWalkerAdapter()
    adapter.original_capture_retry_interval_ms = 0
    waits = 0

    async def wait_for_timeout(_milliseconds: int) -> None:
        nonlocal waits
        waits += 1

    page = SimpleNamespace(wait_for_timeout=wait_for_timeout)
    native = CaptureResult(PNG_1X1, 1, 1)

    assert await adapter._capture_original_jpegs(page, (native,)) is None
    assert waits == 2

    adapter._original_candidates.add(_candidate(JPEG_1X1 + b"native", sequence=1))
    assert await adapter._capture_original_jpegs(page, (native,)) is None
    assert waits == 2


@pytest.mark.asyncio
async def test_spread_requires_all_parts_to_match_before_any_jpeg_is_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_signature(_page: object, data: bytes, mime_type: str) -> str:
        return "native" if mime_type == "image/png" else data[-1:].hex()

    monkeypatch.setattr(adapter_module, "image_signature", fake_signature)
    adapter = BookWalkerAdapter()
    adapter.original_capture_retry_interval_ms = 0
    adapter._original_candidates.add(_candidate(JPEG_1X1 + b"native", sequence=1))

    native = (
        CaptureResult(PNG_1X1, 1, 1),
        CaptureResult(PNG_1X1, 1, 1),
    )

    assert await adapter._capture_original_jpegs(SimpleNamespace(), native) is None
