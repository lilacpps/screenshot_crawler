from __future__ import annotations

import base64

from screenshot_crawler.core.capture import capture_png_bytes
from screenshot_crawler.core.errors import CaptureUnavailableError
from screenshot_crawler.site_adapters.bookwalker.adapter import (
    _MATERIALIZE_NATIVE_SOURCE_SCRIPT,
    BookWalkerAdapter,
    _capture_from_data_url,
    _native_call_is_safe,
)
from screenshot_crawler.site_adapters.bookwalker.native_capture import (
    select_native_draw_calls,
)

PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x04\x00\x00\x00\xb5\x1c\x0c\x02"
    b"\x00\x00\x00\x0bIDAT\x08\xd7c\x9a\xc0\xf0\x1f\x00\x05\x01\x01\x02"
    b"\x1b\xc9\x8d\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _safe_call() -> dict:
    return {
        "source": {"constructor": "ImageBitmap", "width": 960, "height": 1280},
        "transform": {"a": 1, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0},
        "globalCompositeOperation": "source-over",
        "filter": "none",
        "sourceCropPngError": None,
    }


def test_capture_png_bytes_reads_dimensions() -> None:
    result = capture_png_bytes(PNG_1X1)

    assert (result.width, result.height) == (1, 1)


def test_native_data_url_is_decoded_to_capture_result() -> None:
    result = _capture_from_data_url(
        "data:image/png;base64," + base64.b64encode(PNG_1X1).decode("ascii")
    )

    assert result.data == PNG_1X1
    assert (result.width, result.height) == (1, 1)


def test_native_data_url_rejects_non_png() -> None:
    try:
        _capture_from_data_url("data:image/jpeg;base64,AAAA")
    except CaptureUnavailableError:
        pass
    else:
        raise AssertionError("non-PNG data URL must be rejected")


def test_native_safety_rejects_transform_composite_filter_and_copy_error() -> None:
    for field, value in (
        ("transform", {"a": 1, "b": 0, "c": 1, "d": 1, "e": 0, "f": 0}),
        ("globalCompositeOperation", "multiply"),
        ("filter", "blur(1px)"),
        ("sourceCropPngError", "copy failed"),
    ):
        call = _safe_call()
        call[field] = value
        assert not _native_call_is_safe(call)


def test_native_safety_accepts_identity_source_over_without_filter() -> None:
    assert _native_call_is_safe(_safe_call())


def test_native_safety_accepts_purchased_viewer_canvas_sources() -> None:
    call = _safe_call()
    call["source"]["constructor"] = "HTMLCanvasElement"
    call["sourceCropPng"] = "data:image/png;base64," + base64.b64encode(PNG_1X1).decode()
    assert _native_call_is_safe(call)


def test_native_safety_rejects_other_non_image_sources() -> None:
    for constructor in ("HTMLImageElement", "OffscreenCanvas", None):
        call = _safe_call()
        call["source"]["constructor"] = constructor
        assert not _native_call_is_safe(call)


def test_native_safety_rejects_canvas_without_eager_crop() -> None:
    call = _safe_call()
    call["source"]["constructor"] = "HTMLCanvasElement"
    assert _native_call_is_safe(call) is False


def test_deferred_materialization_preserves_null_copy_error() -> None:
    assert "error: copy ? copy.error : 'native source crop unavailable'" in (
        _MATERIALIZE_NATIVE_SOURCE_SCRIPT
    )


def test_native_selection_rejects_one_source_for_two_spread_parts() -> None:
    first = _native_call_fixture()
    second = _native_call_fixture()
    first.pop("sourceCropPng")
    first.pop("sourceCropPngError")
    second.pop("sourceCropPng")
    second.pop("sourceCropPngError")
    second["destination"] = {"x": 100, "y": 0, "width": 100, "height": 100}
    assert (
        select_native_draw_calls(
            [first, second],
            canvas_id="content",
            canvas_width=200,
            canvas_height=100,
            boxes=[
                {"x": 0, "y": 0, "width": 100, "height": 100},
                {"x": 100, "y": 0, "width": 100, "height": 100},
            ],
        )
        is None
    )


def test_native_selection_allows_repeated_source_when_crops_were_eagerly_saved() -> None:
    first = _native_call_fixture()
    second = _native_call_fixture()
    second["destination"] = {"x": 100, "y": 0, "width": 100, "height": 100}
    second["sourceCropPng"] = first["sourceCropPng"] + "different"
    selected = select_native_draw_calls(
        [first, second],
        canvas_id="content",
        canvas_width=200,
        canvas_height=100,
        boxes=[
            {"x": 0, "y": 0, "width": 100, "height": 100},
            {"x": 100, "y": 0, "width": 100, "height": 100},
        ],
    )
    assert selected is not None


class _FakeCanvas:
    async def get_attribute(self, name: str) -> str | None:
        assert name == "data-bookwalker-trace-id"
        return "content"

    async def evaluate(self, _expression: str) -> dict[str, int]:
        return {"width": 100, "height": 100}


class _FakeLocator:
    async def evaluate_all(self, _expression: str) -> None:
        return None


class _FakePage:
    def __init__(self, calls: list[dict]) -> None:
        self.calls = calls
        self.geometry_cleared = False
        self.native_cleared = False
        self.materialize_count = 0

    async def evaluate(self, expression: str, *_args: object) -> object:
        if "__bookwalkerNativeDrawCalls" in expression and ".filter" in expression:
            return self.calls
        if "__bookwalkerMaterializeNativeSourceCrop" in expression:
            self.materialize_count += 1
            payload = _args[0]
            return [
                {
                    "dataUrl": (
                        "data:image/png;base64,"
                        + base64.b64encode(PNG_1X1).decode()
                    ),
                    "error": None,
                }
                for _item in payload  # type: ignore[union-attr]
            ]
        if "__bookwalkerNativeCaptureEnabled = false" in expression:
            self.native_cleared = True
        if "__bookwalkerDrawCalls = []" in expression:
            self.geometry_cleared = True
        return None

    def locator(self, _selector: str) -> _FakeLocator:
        return _FakeLocator()


class _TestBookWalkerAdapter(BookWalkerAdapter):
    async def get_capture_target(self, page: _FakePage) -> _FakeCanvas:
        return _FakeCanvas()

    async def _page_draw_rectangles(
        self, page: _FakePage, canvas: _FakeCanvas
    ) -> list[dict[str, int]]:
        return [{"x": 0, "y": 0, "width": 100, "height": 100}]


def _native_call_fixture(*, constructor: str | None = "ImageBitmap") -> dict:
    return {
        "canvasId": "content",
        "sourceId": "page-1",
        "source": {"constructor": constructor, "width": 1, "height": 1},
        "sourceRect": {"x": 0, "y": 0, "width": 1, "height": 1},
        "destination": {"x": 0, "y": 0, "width": 100, "height": 100},
        "transform": {"a": 1, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0},
        "globalCompositeOperation": "source-over",
        "filter": "none",
        "sourceCropPng": "data:image/png;base64," + base64.b64encode(PNG_1X1).decode(),
        "sourceCropPngError": None,
    }


async def test_native_success_clears_geometry_but_failure_keeps_fallback_trace() -> None:
    success_page = _FakePage([_native_call_fixture()])
    adapter = _TestBookWalkerAdapter()

    result = await adapter.capture_page(success_page)  # type: ignore[arg-type]

    assert result is not None
    assert result[0].data == PNG_1X1
    assert result[0].mime_type == "image/png"
    assert result[0].file_extension == ".png"
    assert success_page.native_cleared
    assert success_page.geometry_cleared

    failure_page = _FakePage([_native_call_fixture(constructor="HTMLImageElement")])
    result = await adapter.capture_page(failure_page)  # type: ignore[arg-type]

    assert result is None
    assert failure_page.native_cleared
    assert not failure_page.geometry_cleared

    await adapter.cleanup_capture_targets(failure_page)  # type: ignore[arg-type]
    assert failure_page.geometry_cleared


async def test_native_source_png_is_materialized_only_for_selected_calls() -> None:
    call = _native_call_fixture()
    call.pop("sourceCropPng")
    call.pop("sourceCropPngError")
    page = _FakePage([call])
    adapter = _TestBookWalkerAdapter()

    result = await adapter.capture_page(page)  # type: ignore[arg-type]

    assert result is not None
    assert page.materialize_count == 1


async def test_canvas_source_without_eager_crop_skips_materialization() -> None:
    call = _native_call_fixture(constructor="HTMLCanvasElement")
    call.pop("sourceCropPng")
    call.pop("sourceCropPngError")
    page = _FakePage([call])
    adapter = _TestBookWalkerAdapter()

    result = await adapter.capture_page(page)  # type: ignore[arg-type]

    assert result is None
    assert page.materialize_count == 0
