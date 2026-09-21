from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
from PIL import Image

from screenshot_crawler.core.capture import CaptureResult
from screenshot_crawler.site_adapters.magapoke.adapter import MagapokeAdapter
from screenshot_crawler.site_adapters.magapoke.native_capture import (
    is_magapoke_jpeg_response,
    jpeg_dimensions,
    jpeg_mcu_dimensions,
    normalize_source_path,
    parse_magapoke_url,
    reconstruct_jpeg_lossless,
    reconstruct_jpeg_png,
    safe_canvas_source_paths,
    source_matches_episode,
)

SOURCE_PATH = "/static/web_titles/695/episodes/244815/p1.jpg"


def _response(url: str, *, content_type: str = "image/jpeg", resource_type: str = "image"):
    return SimpleNamespace(
        url=url,
        headers={"content-type": content_type},
        request=SimpleNamespace(resource_type=resource_type),
    )


def _mapping(*, sx: int, sy: int, sw: int, sh: int, dx: int, dy: int, **overrides):
    result = {
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
    result.update(overrides)
    return result


BASE = _mapping(sx=0, sy=0, sw=10, sh=7, dx=0, dy=0)
VISIBLE = BASE
MAPPINGS = [
    _mapping(sx=0, sy=0, sw=3, sh=7, dx=7, dy=0),
    _mapping(sx=3, sy=0, sw=7, sh=7, dx=0, dy=0),
]


def _jpeg() -> bytes:
    image = Image.new("RGB", (10, 7))
    for y in range(7):
        for x in range(10):
            image.putpixel((x, y), ((x * 23) % 256, (y * 31) % 256, (x + y) * 17 % 256))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=95, subsampling=0)
    return buffer.getvalue()


def test_magapoke_url_parse_preserves_leading_zero_identity() -> None:
    parts = parse_magapoke_url(
        "https://pocket.shonenmagazine.com/title/00695/episode/244815"
    )

    assert parts is not None
    assert (parts.work_id, parts.episode_id, parts.content_id) == (
        "00695",
        "244815",
        "244815",
    )
    assert parse_magapoke_url("https://example.test/title/695") is None


def test_magapoke_response_filter_and_source_path() -> None:
    expected = parse_magapoke_url(
        "https://pocket.shonenmagazine.com/title/00695/episode/244815"
    )
    assert expected is not None
    response = _response(
        "https://mgpk-cdn.magazinepocket.com/static/web_titles/695/episodes/244815/p1.jpg?sig=x"
    )

    assert is_magapoke_jpeg_response(response, expected=expected)
    assert normalize_source_path(response.url).endswith("/244815/p1.jpg")
    source_path = normalize_source_path(response.url)
    assert source_path is not None
    assert source_matches_episode(source_path, expected)
    assert not is_magapoke_jpeg_response(
        _response(response.url.replace("mgpk-cdn", "other")), expected=expected
    )
    assert not is_magapoke_jpeg_response(
        _response(response.url, content_type="image/png"), expected=expected
    )
    assert not is_magapoke_jpeg_response(
        _response(response.url.replace("244815", "244816")), expected=expected
    )


def test_jpeg_magic_dimensions_and_mcu_are_inspected_without_reencoding() -> None:
    data = _jpeg()
    assert data[:3] == b"\xff\xd8\xff"
    assert jpeg_dimensions(data) == (10, 7)
    assert jpeg_mcu_dimensions(data) == (8, 8)
    assert jpeg_dimensions(b"\xff\xd8\xffbad") is None


def test_reconstructs_non_divisible_tile_permutation_to_png() -> None:
    result = reconstruct_jpeg_png(
        _jpeg(),
        base=BASE,
        mappings=MAPPINGS,
        visible_draw=VISIBLE,
        source_path=SOURCE_PATH,
        canvas_size=(10, 7),
    )

    assert result is not None
    assert result.mime_type == "image/png"
    assert result.file_extension == ".png"
    assert (result.width, result.height) == (10, 7)
    assert result.data.startswith(b"\x89PNG\r\n\x1a\n")


def test_reconstructs_aligned_tile_permutation_in_jpeg_coefficient_domain() -> None:
    width, height = 70, 48
    source_path = SOURCE_PATH
    normal = Image.new("RGB", (width, height))
    for y in range(height):
        for x in range(width):
            normal.putpixel((x, y), ((x * 17 + y * 3) % 256, (y * 19) % 256, (x * 7 + y * 11) % 256))

    tile_order = [
        (0, 0, 16, 16, 48, 32),
        (16, 0, 16, 16, 32, 32),
        (32, 0, 16, 16, 16, 32),
        (48, 0, 16, 16, 0, 32),
        (0, 16, 16, 16, 48, 16),
        (16, 16, 16, 16, 32, 16),
        (32, 16, 16, 16, 16, 16),
        (48, 16, 16, 16, 0, 16),
        (0, 32, 16, 16, 48, 0),
        (16, 32, 16, 16, 32, 0),
        (32, 32, 16, 16, 16, 0),
        (48, 32, 16, 16, 0, 0),
    ]
    mappings = [
        _mapping(
            sx=sx,
            sy=sy,
            sw=sw,
            sh=sh,
            dx=dx,
            dy=dy,
            sourceWidth=width,
            sourceHeight=height,
            canvasWidth=width,
            canvasHeight=height,
            dw=sw,
            dh=sh,
        )
        for sx, sy, sw, sh, dx, dy in tile_order
    ]
    scrambled = normal.copy()
    for item in mappings:
        crop = normal.crop((item["dx"], item["dy"], item["dx"] + item["dw"], item["dy"] + item["dh"]))
        scrambled.paste(crop, (item["sx"], item["sy"]))
    buffer = io.BytesIO()
    scrambled.save(buffer, format="JPEG", quality=87, subsampling=0)

    base = _mapping(
        sx=0,
        sy=0,
        sw=width,
        sh=height,
        dx=0,
        dy=0,
        sourceWidth=width,
        sourceHeight=height,
        canvasWidth=width,
        canvasHeight=height,
        dw=width,
        dh=height,
    )
    jpeg = reconstruct_jpeg_lossless(
        buffer.getvalue(),
        base=base,
        mappings=mappings,
        visible_draw=base,
        source_path=source_path,
        canvas_size=(width, height),
    )
    png = reconstruct_jpeg_png(
        buffer.getvalue(),
        base=base,
        mappings=mappings,
        visible_draw=base,
        source_path=source_path,
        canvas_size=(width, height),
    )

    assert jpeg is not None
    assert png is not None
    assert jpeg.mime_type == "image/jpeg"
    assert jpeg.file_extension == ".jpg"
    assert (jpeg.width, jpeg.height) == (width, height)
    assert Image.open(io.BytesIO(jpeg.data)).convert("RGB").tobytes() == Image.open(
        io.BytesIO(png.data)
    ).convert("RGB").tobytes()

    subsampled = io.BytesIO()
    scrambled.save(subsampled, format="JPEG", quality=87, subsampling=2)
    assert (
        reconstruct_jpeg_lossless(
            subsampled.getvalue(),
            base=base,
            mappings=mappings,
            visible_draw=base,
            source_path=source_path,
            canvas_size=(width, height),
        )
        is None
    )


def test_visible_final_draw_and_source_canvas_size_are_safety_gates() -> None:
    assert (
        reconstruct_jpeg_png(
            _jpeg(),
            base=BASE,
            mappings=MAPPINGS,
            visible_draw=_mapping(sx=0, sy=0, sw=10, sh=7, dx=0, dy=0, dw=9),
            source_path=SOURCE_PATH,
            canvas_size=(10, 7),
        )
        is None
    )
    assert (
        reconstruct_jpeg_png(
            _jpeg(),
            base=BASE,
            mappings=MAPPINGS,
            visible_draw=VISIBLE,
            source_path=SOURCE_PATH,
            canvas_size=(20, 14),
        )
        is None
    )


@pytest.mark.asyncio
async def test_adapter_retries_current_spread_after_retryable_observation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakePage:
        def __init__(self) -> None:
            self.waits: list[int] = []

        async def wait_for_timeout(self, timeout: int) -> None:
            self.waits.append(timeout)

    adapter = MagapokeAdapter()
    page = FakePage()
    row_calls = 0
    attempt_calls = 0
    capture = CaptureResult(b"jpeg", 1, 1, "image/jpeg", ".jpg")

    async def fake_rows(_page: object) -> list[dict[str, object]]:
        nonlocal row_calls
        row_calls += 1
        return [{"index": 0}]

    async def fake_attempt(
        _page: object,
        _rows: list[dict[str, object]],
        _paths: set[str],
    ) -> tuple[tuple[CaptureResult, ...] | None, tuple[object, ...], bool]:
        nonlocal attempt_calls
        attempt_calls += 1
        if attempt_calls == 1:
            return None, (object(),), True
        return (capture,), (object(),), False

    monkeypatch.setattr(adapter, "_canvas_rows", fake_rows)
    monkeypatch.setattr(adapter, "_capture_native_attempt", fake_attempt)

    result = await adapter.capture_page(page)  # type: ignore[arg-type]

    assert result == (capture,)
    assert row_calls == 2
    assert attempt_calls == 2
    assert page.waits == [adapter.capture_retry_interval_ms]


@pytest.mark.asyncio
async def test_adapter_does_not_retry_deterministic_spread_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakePage:
        def __init__(self) -> None:
            self.waits: list[int] = []

        async def wait_for_timeout(self, timeout: int) -> None:
            self.waits.append(timeout)

    adapter = MagapokeAdapter()
    page = FakePage()
    row_calls = 0
    attempt_calls = 0
    fallback = CaptureResult(b"png", 1, 1)

    async def fake_rows(_page: object) -> list[dict[str, object]]:
        nonlocal row_calls
        row_calls += 1
        return [{"index": 0}]

    async def fake_attempt(
        _page: object,
        _rows: list[dict[str, object]],
        _paths: set[str],
    ) -> tuple[tuple[CaptureResult, ...] | None, tuple[object, ...], bool]:
        nonlocal attempt_calls
        attempt_calls += 1
        return None, (object(),), False

    async def fake_capture_locator(_target: object) -> CaptureResult:
        return fallback

    monkeypatch.setattr(adapter, "_canvas_rows", fake_rows)
    monkeypatch.setattr(adapter, "_capture_native_attempt", fake_attempt)
    monkeypatch.setattr(
        "screenshot_crawler.site_adapters.magapoke.adapter.capture_locator",
        fake_capture_locator,
    )

    result = await adapter.capture_page(page)  # type: ignore[arg-type]

    assert result == (fallback,)
    assert row_calls == 1
    assert attempt_calls == 1
    assert page.waits == []


@pytest.mark.parametrize(
    ("name", "mappings"),
    [
        ("missing boundary tile", MAPPINGS[:1]),
        ("destination overlap", [MAPPINGS[0], _mapping(sx=3, sy=0, sw=7, sh=7, dx=7, dy=0)]),
        ("destination gap", [_mapping(sx=0, sy=0, sw=3, sh=7, dx=0, dy=0), MAPPINGS[1]]),
        ("ambiguous source", [_mapping(sx=0, sy=0, sw=3, sh=7, dx=7, dy=0), MAPPINGS[0]]),
        (
            "unknown transform",
            [MAPPINGS[0], _mapping(sx=3, sy=0, sw=7, sh=7, dx=0, dy=0, transform=[0, 1, -1, 0, 0, 0])],
        ),
        (
            "scaling",
            [MAPPINGS[0], _mapping(sx=3, sy=0, sw=7, sh=7, dx=0, dy=0, dw=6)],
        ),
    ],
)
def test_unsafe_mapping_falls_out_of_native_reconstruction(name: str, mappings: list[dict]) -> None:
    del name
    assert (
        reconstruct_jpeg_png(
            _jpeg(),
            base=BASE,
            mappings=mappings,
            visible_draw=VISIBLE,
            source_path=SOURCE_PATH,
            canvas_size=(10, 7),
        )
        is None
    )


def test_mapping_requires_unique_stable_source_paths() -> None:
    rows = [
        {"sourcePath": "/static/web_titles/695/episodes/244815/right.jpg"},
        {"sourcePath": "/static/web_titles/695/episodes/244815/left.jpg"},
    ]
    assert safe_canvas_source_paths(rows) == (
        "/static/web_titles/695/episodes/244815/right.jpg",
        "/static/web_titles/695/episodes/244815/left.jpg",
    )
    assert safe_canvas_source_paths([rows[0], rows[0]]) is None
    assert safe_canvas_source_paths([{"sourcePath": None}]) is None
