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
