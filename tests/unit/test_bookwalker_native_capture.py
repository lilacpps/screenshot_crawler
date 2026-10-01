from __future__ import annotations

import base64

import pytest

from screenshot_crawler.core.capture import CaptureResult, capture_png_bytes
from screenshot_crawler.core.errors import CaptureUnavailableError
from screenshot_crawler.site_adapters.bookwalker import adapter as adapter_module
from screenshot_crawler.site_adapters.bookwalker.adapter import (
    _DRAW_TRACE_SCRIPT,
    _MATERIALIZE_NATIVE_SOURCE_SCRIPT,
    BookWalkerAdapter,
    _capture_from_data_url,
    _native_call_is_safe,
    _trace_payload_stats,
    parse_bookwalker_lossless_jpeg_output,
)
from screenshot_crawler.site_adapters.bookwalker.lossless_jpeg import LosslessJpegResult
from screenshot_crawler.site_adapters.bookwalker.native_capture import (
    select_native_draw_calls,
)
from screenshot_crawler.site_adapters.bookwalker.original_capture import candidate_from_jpeg
from screenshot_crawler.site_adapters.bookwalker.purchased_mapping import (
    MAPPING_PROVEN,
    MappingAnalysis,
    PurchasedMapping,
)

PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x04\x00\x00\x00\xb5\x1c\x0c\x02"
    b"\x00\x00\x00\x0bIDAT\x08\xd7c\x9a\xc0\xf0\x1f\x00\x05\x01\x01\x02"
    b"\x1b\xc9\x8d\x00\x00\x00\x00IEND\xaeB`\x82"
)
JPEG_1X1 = (
    b"\xff\xd8\xff\xe0\x00\x04\x00\x00"
    b"\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03"
    b"\x01\x11\x00\x02\x11\x00\x03\x11\x00\xff\xd9"
)

EMPTY_COMPACT_PAYLOAD = {
    "transportVersion": 1,
    "compactMappings": [],
    "retainedCompletedMappingCount": 0,
    "retainedCompletedTileRecordCount": 0,
    "activeSegmentCount": 0,
    "activeTileRecordCount": 0,
    "droppedCompletedMappingCount": 0,
    "droppedActiveSegmentCount": 0,
    "requestedMappingCount": 0,
    "returnedCompletedMappingCount": 0,
    "returnedTileRecordCount": 0,
    "missingMappingCount": 0,
    "compactSourceTableCount": 0,
    "compactTargetTableCount": 0,
    "compactTransformTableCount": 0,
    "compactCompositeTableCount": 0,
    "compactFilterTableCount": 0,
}


def _safe_call() -> dict:
    return {
        "source": {"constructor": "ImageBitmap", "width": 960, "height": 1280},
        "transform": {"a": 1, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0},
        "globalCompositeOperation": "source-over",
        "filter": "none",
        "snapshotError": None,
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
        ("snapshotError", "copy failed"),
    ):
        call = _safe_call()
        call[field] = value
        assert not _native_call_is_safe(call)


def test_native_safety_accepts_identity_source_over_without_filter() -> None:
    assert _native_call_is_safe(_safe_call())


def test_native_safety_accepts_purchased_viewer_canvas_sources() -> None:
    call = _safe_call()
    call["source"]["constructor"] = "HTMLCanvasElement"
    call["snapshotId"] = "snapshot-1"
    assert _native_call_is_safe(call)


def test_native_safety_rejects_other_non_image_sources() -> None:
    for constructor in ("HTMLImageElement", "OffscreenCanvas", None):
        call = _safe_call()
        call["source"]["constructor"] = constructor
        assert not _native_call_is_safe(call)


def test_native_safety_rejects_canvas_without_snapshot() -> None:
    call = _safe_call()
    call["source"]["constructor"] = "HTMLCanvasElement"
    assert _native_call_is_safe(call) is False


def test_deferred_materialization_materializes_snapshot_or_source_reference() -> None:
    assert "__bookwalkerMaterializeNativeSourceCrop" in _MATERIALIZE_NATIVE_SOURCE_SCRIPT
    assert "snapshotId" in _DRAW_TRACE_SCRIPT
    assert "sourceConstructor" in _DRAW_TRACE_SCRIPT
    assert "sourceCanvasId" in _DRAW_TRACE_SCRIPT
    assert "globalAlpha" in _DRAW_TRACE_SCRIPT
    assert "clearRect" in _DRAW_TRACE_SCRIPT
    assert "putImageData" in _DRAW_TRACE_SCRIPT


def test_native_selection_rejects_one_source_for_two_spread_parts() -> None:
    first = _native_call_fixture()
    second = _native_call_fixture()
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


def test_native_selection_allows_repeated_source_when_snapshots_were_saved() -> None:
    first = _native_call_fixture()
    second = _native_call_fixture()
    first["source"]["constructor"] = "HTMLCanvasElement"
    second["source"]["constructor"] = "HTMLCanvasElement"
    first["snapshotId"] = "snapshot-1"
    second["destination"] = {"x": 100, "y": 0, "width": 100, "height": 100}
    second["snapshotId"] = "snapshot-2"
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
        "snapshotId": None,
        "snapshotError": None,
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
    page = _FakePage([call])
    adapter = _TestBookWalkerAdapter()

    result = await adapter.capture_page(page)  # type: ignore[arg-type]

    assert result is not None
    assert page.materialize_count == 1


async def test_canvas_source_snapshot_is_materialized_after_selection() -> None:
    call = _native_call_fixture(constructor="HTMLCanvasElement")
    call["snapshotId"] = "snapshot-1"
    page = _FakePage([call])
    adapter = _TestBookWalkerAdapter()

    result = await adapter.capture_page(page)  # type: ignore[arg-type]

    assert result is not None
    assert page.materialize_count == 1


async def test_canvas_mode_returns_none_without_touching_native_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOOKWALKER_CAPTURE_MODE", "canvas")
    monkeypatch.setenv("BOOKWALKER_LOSSLESS_JPEG_OUTPUT", "1")
    page = _FakePage([])
    adapter = _TestBookWalkerAdapter()
    _add_purchased_candidate(adapter)
    reconstruction_called = False

    async def unexpected_reconstruction(*_args: object) -> object:
        nonlocal reconstruction_called
        reconstruction_called = True
        return None

    monkeypatch.setattr(
        adapter,
        "_evaluate_lossless_reconstruction",
        unexpected_reconstruction,
    )

    result = await adapter.capture_page(page)  # type: ignore[arg-type]

    assert result is None
    assert page.materialize_count == 0
    assert reconstruction_called is False
    debug = await adapter.collect_debug_metadata(page)  # type: ignore[arg-type]
    assert debug["bookwalker_capture"]["returned_path"] == "rendered_canvas"
    assert debug["bookwalker_capture"]["lossless_shadow"]["output_used"] is False


@pytest.mark.asyncio
async def test_existing_original_jpeg_wins_before_lossless_shadow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BOOKWALKER_LOSSLESS_JPEG_OUTPUT", raising=False)
    page = _FakePage([_native_call_fixture()])
    adapter = _TestBookWalkerAdapter()
    original = CaptureResult(b"original-jpeg", 1, 1, "image/jpeg", ".jpg")
    shadow_called = False

    async def original_capture(_page: object, _native: tuple[CaptureResult, ...]) -> tuple[CaptureResult, ...]:
        return (original,)

    async def shadow(*_args: object) -> dict[str, object]:
        nonlocal shadow_called
        shadow_called = True
        return {}

    monkeypatch.setattr(adapter, "_capture_original_jpegs", original_capture)
    monkeypatch.setattr(adapter, "_evaluate_lossless_reconstruction", shadow)

    result = await adapter.capture_page(page)  # type: ignore[arg-type]

    assert result == (original,)
    assert shadow_called is False
    debug = await adapter.collect_debug_metadata(page)  # type: ignore[arg-type]
    assert debug["bookwalker_capture"]["returned_path"] == "original_jpeg"
    assert debug["bookwalker_capture"]["lossless_shadow"]["output_enabled"] is True
    assert debug["bookwalker_capture"]["lossless_shadow"]["output_used"] is False
    assert debug["bookwalker_capture"]["timing_ms"]["original_jpeg_match_ms"] >= 0


@pytest.mark.asyncio
async def test_purchased_direct_original_jpeg_is_returned_byte_for_byte(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BOOKWALKER_LOSSLESS_JPEG_OUTPUT", raising=False)
    page = _FakePage([_native_call_fixture()])
    adapter = _TestBookWalkerAdapter()
    candidate = candidate_from_jpeg(
        JPEG_1X1,
        url="https://bw-bv-epubs.bookwalker.jp/page.jpeg",
        sequence=1,
    )
    assert candidate is not None
    adapter._original_candidates.add(candidate)

    async def fake_signature(
        _page: object,
        _data: bytes,
        _mime_type: str,
    ) -> str:
        return "same-image"

    shadow_called = False

    async def shadow(*_args: object) -> dict[str, object]:
        nonlocal shadow_called
        shadow_called = True
        return {}

    monkeypatch.setattr(adapter_module, "image_signature", fake_signature)
    monkeypatch.setattr(adapter, "_evaluate_lossless_reconstruction", shadow)

    result = await adapter.capture_page(page)  # type: ignore[arg-type]

    assert result is not None
    assert result[0].data == candidate.data
    assert result[0].mime_type == "image/jpeg"
    assert result[0].file_extension == ".jpg"
    assert shadow_called is False
    debug = await adapter.collect_debug_metadata(page)  # type: ignore[arg-type]
    assert debug["bookwalker_capture"]["returned_path"] == "original_jpeg"
    assert (
        debug["bookwalker_capture"]["original_match"]["original_attempt_count"]
        == 1
    )
    assert (
        debug["bookwalker_capture"]["original_match"]["original_retry_wait_count"]
        == 0
    )
    assert debug["bookwalker_capture"]["timing_ms"]["original_retry_wait_ms"] == 0


def _add_purchased_candidate(adapter: BookWalkerAdapter) -> None:
    candidate = candidate_from_jpeg(
        JPEG_1X1,
        url="https://bw-bv-epubs.bookwalker.jp/page.jpeg",
        sequence=1,
    )
    assert candidate is not None
    adapter._original_candidates.add(candidate)


def _evaluation(
    adapter: BookWalkerAdapter,
    captures: tuple[CaptureResult, ...] | None,
    *,
    spread_ready: bool,
) -> adapter_module.LosslessReconstructionEvaluation:
    return adapter_module.LosslessReconstructionEvaluation(
        debug={
            "attempted": True,
            "spread_ready": spread_ready,
            "output_enabled": adapter.lossless_jpeg_output_enabled,
            "output_used": False,
            "parts": [],
        },
        captures=captures,
    )


async def _no_original_capture(
    _page: object,
    _native: tuple[CaptureResult, ...],
) -> None:
    return None


@pytest.mark.asyncio
async def test_lossless_output_switch_off_keeps_verified_shadow_native_png(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOOKWALKER_LOSSLESS_JPEG_OUTPUT", "0")
    page = _FakePage([_native_call_fixture()])
    adapter = _TestBookWalkerAdapter()
    _add_purchased_candidate(adapter)
    monkeypatch.setattr(adapter, "_capture_original_jpegs", _no_original_capture)
    native = CaptureResult(PNG_1X1, 1, 1)
    reconstructed = CaptureResult(
        b"verified-reconstructed-jpeg", 1, 1, "image/jpeg", ".jpg"
    )

    async def evaluate(*_args: object) -> adapter_module.LosslessReconstructionEvaluation:
        return _evaluation(adapter, (reconstructed,), spread_ready=True)

    monkeypatch.setattr(
        adapter,
        "_evaluate_lossless_reconstruction",
        evaluate,
    )

    result = await adapter.capture_page(page)  # type: ignore[arg-type]

    assert result is not None
    assert result == (native,)
    debug = await adapter.collect_debug_metadata(page)  # type: ignore[arg-type]
    shadow = debug["bookwalker_capture"]["lossless_shadow"]
    assert debug["bookwalker_capture"]["returned_path"] == "native_png"
    assert shadow["output_enabled"] is False
    assert shadow["output_used"] is False
    assert result[0].mime_type == "image/png"


@pytest.mark.asyncio
async def test_lossless_output_switch_returns_verified_bytes_without_reencoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BOOKWALKER_LOSSLESS_JPEG_OUTPUT", raising=False)
    page = _FakePage([_native_call_fixture()])
    adapter = _TestBookWalkerAdapter()
    _add_purchased_candidate(adapter)
    monkeypatch.setattr(adapter, "_capture_original_jpegs", _no_original_capture)
    verified_bytes = b"unique-verified-reconstructed-jpeg"
    reconstructed = CaptureResult(verified_bytes, 1, 1, "image/jpeg", ".jpg")

    async def evaluate(*_args: object) -> adapter_module.LosslessReconstructionEvaluation:
        return _evaluation(adapter, (reconstructed,), spread_ready=True)

    monkeypatch.setattr(
        adapter,
        "_evaluate_lossless_reconstruction",
        evaluate,
    )

    result = await adapter.capture_page(page)  # type: ignore[arg-type]

    assert result == (reconstructed,)
    assert result[0].data == verified_bytes
    assert result[0].mime_type == "image/jpeg"
    assert result[0].file_extension == ".jpg"
    assert (result[0].width, result[0].height) == (1, 1)
    debug = await adapter.collect_debug_metadata(page)  # type: ignore[arg-type]
    assert debug["bookwalker_capture"]["returned_path"] == "reconstructed_jpeg"
    shadow = debug["bookwalker_capture"]["lossless_shadow"]
    assert shadow["output_enabled"] is True
    assert shadow["output_used"] is True
    assert {
        "native_materialization_ms",
        "original_jpeg_match_ms",
        "lossless_evaluation_total_ms",
        "capture_total_ms",
        "capture_unaccounted_ms",
    } <= debug["bookwalker_capture"]["timing_ms"].keys()


@pytest.mark.asyncio
async def test_lossless_output_spread_is_all_or_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOOKWALKER_LOSSLESS_JPEG_OUTPUT", "1")
    first = _native_call_fixture(constructor="HTMLCanvasElement")
    first["snapshotId"] = "snapshot-1"
    second = _native_call_fixture(constructor="HTMLCanvasElement")
    second["snapshotId"] = "snapshot-2"
    second["destination"] = {"x": 100, "y": 0, "width": 100, "height": 100}

    class SpreadAdapter(_TestBookWalkerAdapter):
        async def get_capture_target(self, _page: _FakePage) -> _FakeCanvas:
            class SpreadCanvas(_FakeCanvas):
                async def evaluate(self, _expression: str) -> dict[str, int]:
                    return {"width": 200, "height": 100}

            return SpreadCanvas()

        async def _page_draw_rectangles(
            self, _page: _FakePage, _canvas: _FakeCanvas
        ) -> list[dict[str, int]]:
            return [
                {"x": 0, "y": 0, "width": 100, "height": 100},
                {"x": 100, "y": 0, "width": 100, "height": 100},
            ]

        async def _is_first_page(self, _page: _FakePage) -> bool:
            return False

    page = _FakePage([first, second])
    adapter = SpreadAdapter()
    _add_purchased_candidate(adapter)
    monkeypatch.setattr(adapter, "_capture_original_jpegs", _no_original_capture)
    jpeg_captures = (
        CaptureResult(b"jpeg-right", 1, 1, "image/jpeg", ".jpg"),
        CaptureResult(b"jpeg-left", 1, 1, "image/jpeg", ".jpg"),
    )

    async def evaluate(*_args: object) -> adapter_module.LosslessReconstructionEvaluation:
        return _evaluation(adapter, jpeg_captures, spread_ready=True)

    monkeypatch.setattr(
        adapter,
        "_evaluate_lossless_reconstruction",
        evaluate,
    )

    result = await adapter.capture_page(page)  # type: ignore[arg-type]

    assert result == jpeg_captures
    assert [capture.data for capture in result] == [b"jpeg-right", b"jpeg-left"]

    page = _FakePage([first, second])
    adapter = SpreadAdapter()
    _add_purchased_candidate(adapter)
    monkeypatch.setattr(adapter, "_capture_original_jpegs", _no_original_capture)
    partial = _evaluation(adapter, (jpeg_captures[0],), spread_ready=False)

    async def evaluate_partial(
        *_args: object,
    ) -> adapter_module.LosslessReconstructionEvaluation:
        return partial

    monkeypatch.setattr(adapter, "_evaluate_lossless_reconstruction", evaluate_partial)

    fallback = await adapter.capture_page(page)  # type: ignore[arg-type]

    assert fallback is not None
    assert len(fallback) == 2
    assert all(capture.mime_type == "image/png" for capture in fallback)
    debug = await adapter.collect_debug_metadata(page)  # type: ignore[arg-type]
    assert debug["bookwalker_capture"]["returned_path"] == "native_png"
    assert debug["bookwalker_capture"]["lossless_shadow"]["output_used"] is False


@pytest.mark.asyncio
async def test_lossless_shadow_spread_readiness_is_all_or_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ShadowPage:
        async def evaluate(self, _expression: str, *_args: object) -> dict[str, object]:
            return dict(EMPTY_COMPACT_PAYLOAD)

    mapping = PurchasedMapping(
        mapping=(
            {
                "source_x": 0,
                "source_y": 0,
                "destination_x": 0,
                "destination_y": 0,
                "width": 8,
                "height": 8,
            },
        ),
        source_dimensions=(8, 8),
        destination_dimensions=(8, 8),
        tile_dimensions=(8, 8),
        imagebitmap_source_id="bitmap-1",
        mapping_sha256="mapping-1",
    )
    ready = MappingAnalysis(
        MAPPING_PROVEN,
        "ready",
        mapping,
        mapping_source="completed_segment",
    )
    unsupported = MappingAnalysis("MAPPING_UNAVAILABLE", "unsupported")
    analyses = iter((ready, unsupported))

    def fake_analysis(_trace: object, _draw: object) -> MappingAnalysis:
        return next(analyses)

    async def fake_match(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {"available": True, "exact": True}

    async def fake_signature(*_args: object, **_kwargs: object) -> str:
        return "signature"

    async def fake_pixels(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {"available": True, "exact": True}

    def fake_reconstruct(*_args: object, **_kwargs: object) -> LosslessJpegResult:
        return LosslessJpegResult(
            data=b"reconstructed",
            width=8,
            height=8,
            tile_dimensions=(8, 8),
            mcu_dimensions=(8, 8),
            mapping_sha256="mapping-1",
            coefficient_validation={
                "mismatched_blocks": 0,
                "mismatched_coefficients": 0,
                "quantization_tables_equal": True,
            },
            available=True,
        )

    monkeypatch.setattr(adapter_module, "analyze_purchased_mapping", fake_analysis)
    monkeypatch.setattr(adapter_module, "image_signature", fake_signature)
    monkeypatch.setattr(adapter_module, "imagebitmap_signature", fake_signature)
    monkeypatch.setattr(adapter_module, "imagebitmap_pixel_exact_match", fake_match)
    monkeypatch.setattr(adapter_module, "reconstruct_lossless_jpeg", fake_reconstruct)
    adapter = BookWalkerAdapter()
    adapter._browser_pixel_exact = fake_pixels  # type: ignore[method-assign]
    candidate = candidate_from_jpeg(
        JPEG_1X1,
        url="https://bw-bv-epubs.bookwalker.jp/page.jpeg",
        sequence=1,
    )
    assert candidate is not None
    candidate.width = 8
    candidate.height = 8
    adapter._original_candidates.add(candidate)

    result = await adapter._evaluate_lossless_reconstruction(
        ShadowPage(),
        (CaptureResult(PNG_1X1, 1, 1), CaptureResult(PNG_1X1, 1, 1)),
        [{"part": 1, "mappingId": "mapping-1"}, {"part": 2, "mappingId": "mapping-2"}],
    )

    assert len(result["parts"]) == 2
    assert result["parts"][0]["native_pixel_exact"] is True
    assert result["parts"][1]["mapping_proven"] is False
    assert result["spread_ready"] is False


@pytest.mark.asyncio
async def test_lossless_shadow_prefilters_candidates_before_full_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ShadowPage:
        async def evaluate(self, _expression: str, *_args: object) -> dict[str, object]:
            return dict(EMPTY_COMPACT_PAYLOAD)

    mapping = PurchasedMapping(
        mapping=(
            {
                "source_x": 0,
                "source_y": 0,
                "destination_x": 0,
                "destination_y": 0,
                "width": 8,
                "height": 8,
            },
        ),
        source_dimensions=(8, 8),
        destination_dimensions=(8, 8),
        tile_dimensions=(8, 8),
        imagebitmap_source_id="bitmap-1",
        mapping_sha256="mapping-1",
    )
    ready = MappingAnalysis(
        MAPPING_PROVEN,
        "ready",
        mapping,
        mapping_source="completed_segment",
    )
    full_resolution_calls: list[bytes] = []

    def fake_analysis(_trace: object, _draw: object) -> MappingAnalysis:
        return ready

    async def fake_signature(_page: object, data: bytes, _mime_type: str) -> str:
        return "match" if data.endswith(b"candidate-31") else "other"

    async def fake_imagebitmap_signature(_page: object, _source_id: str) -> str:
        return "match"

    async def fake_full_match(_page: object, data: bytes, _source_id: str) -> dict[str, object]:
        full_resolution_calls.append(data)
        return {"available": True, "exact": data.endswith(b"candidate-31")}

    async def fake_native_pixels(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {"available": True, "exact": True}

    def fake_reconstruct(*_args: object, **_kwargs: object) -> LosslessJpegResult:
        return LosslessJpegResult(
            data=b"reconstructed",
            width=8,
            height=8,
            tile_dimensions=(8, 8),
            mcu_dimensions=(8, 8),
            mapping_sha256="mapping-1",
            coefficient_validation={
                "mismatched_blocks": 0,
                "mismatched_coefficients": 0,
                "quantization_tables_equal": True,
            },
            available=True,
        )

    monkeypatch.setattr(adapter_module, "analyze_purchased_mapping", fake_analysis)
    monkeypatch.setattr(adapter_module, "image_signature", fake_signature)
    monkeypatch.setattr(
        adapter_module,
        "imagebitmap_signature",
        fake_imagebitmap_signature,
    )
    monkeypatch.setattr(
        adapter_module,
        "imagebitmap_pixel_exact_match",
        fake_full_match,
    )
    monkeypatch.setattr(adapter_module, "reconstruct_lossless_jpeg", fake_reconstruct)
    adapter = BookWalkerAdapter()
    adapter._browser_pixel_exact = fake_native_pixels  # type: ignore[method-assign]

    for index in range(32):
        candidate = candidate_from_jpeg(
            JPEG_1X1 + f"candidate-{index:02d}".encode(),
            url="https://bw-bv-epubs.bookwalker.jp/page.jpeg",
            sequence=index + 1,
        )
        assert candidate is not None
        if index >= 30:
            candidate.width = 8
            candidate.height = 8
        else:
            candidate.width = 2
            candidate.height = 2
        adapter._original_candidates.add(candidate)

    result = await adapter._evaluate_lossless_reconstruction(
        ShadowPage(),
        (CaptureResult(PNG_1X1, 8, 8),),
        [{"part": 1, "mappingId": "mapping-1"}],
    )

    part = result["parts"][0]
    assert part["candidate_count_total"] == 32
    assert part["candidate_count_dimension_match"] == 2
    assert part["candidate_count_signature_match"] == 1
    assert part["full_resolution_comparison_count"] == 1
    assert part["candidate_count_full_exact"] == 1
    assert len(full_resolution_calls) == 1
    assert result["spread_ready"] is True
    assert {
        "evaluation_total",
        "trace_fetch_ms",
        "trace_decode_ms",
        "trace_python_analysis_ms",
        "mapping_analysis",
        "imagebitmap_signature",
        "candidate_signature_total",
        "raw_full_resolution_compare",
        "lossless_reconstruction",
        "final_browser_pixel_compare",
        "measured_component_total_ms",
        "unaccounted_ms",
    } <= result["timing_ms"].keys()
    assert {
        "mapping_analysis_ms",
        "imagebitmap_signature_ms",
        "candidate_signature_ms_total",
        "raw_full_resolution_compare_ms",
        "lossless_reconstruction_ms",
        "final_browser_pixel_compare_ms",
    } <= part["timing_ms"].keys()
    assert all(
        isinstance(value, (int, float))
        for value in result["timing_ms"].values()
    )
    assert all(
        isinstance(result["timing_ms"][key], (int, float))
        and result["timing_ms"][key] >= 0
        for key in result["timing_ms"]
        if key != "unaccounted_ms"
    )


def test_trace_payload_stats_count_bounded_records() -> None:
    stats = _trace_payload_stats(
        {
            "completedMappings": [
                {"tileDraws": [{}, {}]},
                {"tileDraws": [{}]},
            ],
            "activeSegments": {
                "canvas-1": {"tileDraws": [{}, {}, {}]},
                "canvas-2": {"tileDraws": []},
            },
            "droppedCompletedMappingCount": 4,
            "droppedActiveSegmentCount": 2,
        }
    )

    assert stats == {
        "trace_completed_mapping_count": 2,
        "trace_completed_tile_record_count": 3,
        "trace_active_segment_count": 2,
        "trace_active_tile_record_count": 3,
        "trace_dropped_completed_mapping_count": 4,
        "trace_dropped_active_segment_count": 2,
        "trace_requested_mapping_count": 0,
        "trace_returned_mapping_count": 0,
        "trace_returned_tile_record_count": 0,
        "trace_missing_mapping_count": 0,
        "trace_compact_source_table_count": 0,
        "trace_compact_target_table_count": 0,
        "trace_compact_transform_table_count": 0,
        "trace_compact_composite_table_count": 0,
        "trace_compact_filter_table_count": 0,
    }


def test_trace_payload_stats_keeps_retained_counts_separate_from_selected_counts() -> None:
    stats = _trace_payload_stats(
        {
            "completedMappings": [{"tileDraws": [{}]}],
            "retainedCompletedMappingCount": 4,
            "retainedCompletedTileRecordCount": 400,
            "activeSegmentCount": 2,
            "activeTileRecordCount": 20,
            "droppedCompletedMappingCount": 3,
            "droppedActiveSegmentCount": 1,
            "requestedMappingCount": 1,
            "returnedCompletedMappingCount": 1,
            "returnedTileRecordCount": 100,
            "missingMappingCount": 0,
            "compactSourceTableCount": 1,
            "compactTargetTableCount": 1,
            "compactTransformTableCount": 1,
            "compactCompositeTableCount": 1,
            "compactFilterTableCount": 1,
        }
    )

    assert stats["trace_completed_mapping_count"] == 4
    assert stats["trace_completed_tile_record_count"] == 400
    assert stats["trace_returned_mapping_count"] == 1
    assert stats["trace_returned_tile_record_count"] == 100
    assert stats["trace_requested_mapping_count"] == 1
    assert stats["trace_compact_source_table_count"] == 1
    assert stats["trace_compact_target_table_count"] == 1
    assert stats["trace_compact_transform_table_count"] == 1
    assert stats["trace_compact_composite_table_count"] == 1
    assert stats["trace_compact_filter_table_count"] == 1


@pytest.mark.asyncio
async def test_lossless_shadow_trace_unavailable_keeps_timing_metadata() -> None:
    class MissingTracePage:
        async def evaluate(self, _expression: str) -> object:
            raise RuntimeError("trace unavailable")

    adapter = BookWalkerAdapter()
    result = await adapter._evaluate_lossless_reconstruction(
        MissingTracePage(),
        (CaptureResult(PNG_1X1, 8, 8),),
        [{"part": 1, "mappingId": "mapping-1"}],
    )

    assert result["spread_ready"] is False
    assert result["trace_completed_mapping_count"] == 0
    assert result["timing_ms"]["trace_fetch_ms"] >= 0
    assert isinstance(result["timing_ms"]["unaccounted_ms"], (int, float))


@pytest.mark.asyncio
async def test_lossless_shadow_without_mapping_id_fails_closed_without_full_trace_fetch() -> None:
    class UnexpectedTraceFetchPage:
        def __init__(self) -> None:
            self.evaluate_calls = 0

        async def evaluate(self, _expression: str, *_args: object) -> object:
            self.evaluate_calls += 1
            raise AssertionError("mapping-id-unavailable path must not fetch full trace")

    page = UnexpectedTraceFetchPage()
    result = await BookWalkerAdapter()._evaluate_lossless_reconstruction(
        page,
        (CaptureResult(PNG_1X1, 8, 8),),
        [{"part": 1}],
    )

    assert result["spread_ready"] is False
    assert result["reason"] == "selected renderer draw mapping identity unavailable"
    assert result["trace_fetch_mode"] == "selected_completed_mappings_compact_v1"
    assert page.evaluate_calls == 0


@pytest.mark.asyncio
async def test_lossless_shadow_full_resolution_ambiguity_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ShadowPage:
        async def evaluate(self, _expression: str, *_args: object) -> dict[str, object]:
            return dict(EMPTY_COMPACT_PAYLOAD)

    mapping = PurchasedMapping(
        mapping=(
            {
                "source_x": 0,
                "source_y": 0,
                "destination_x": 0,
                "destination_y": 0,
                "width": 8,
                "height": 8,
            },
        ),
        source_dimensions=(8, 8),
        destination_dimensions=(8, 8),
        tile_dimensions=(8, 8),
        imagebitmap_source_id="bitmap-1",
        mapping_sha256="mapping-1",
    )
    ready = MappingAnalysis(MAPPING_PROVEN, "ready", mapping)
    reconstruct_called = False

    def fake_reconstruct(*_args: object, **_kwargs: object) -> LosslessJpegResult:
        nonlocal reconstruct_called
        reconstruct_called = True
        raise AssertionError("ambiguous candidates must not reconstruct")

    async def fake_signature(*_args: object, **_kwargs: object) -> str:
        return "same"

    async def fake_full_match(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {"available": True, "exact": True}

    monkeypatch.setattr(adapter_module, "analyze_purchased_mapping", lambda *_args: ready)
    monkeypatch.setattr(adapter_module, "image_signature", fake_signature)
    monkeypatch.setattr(adapter_module, "imagebitmap_signature", fake_signature)
    monkeypatch.setattr(adapter_module, "imagebitmap_pixel_exact_match", fake_full_match)
    monkeypatch.setattr(adapter_module, "reconstruct_lossless_jpeg", fake_reconstruct)
    adapter = BookWalkerAdapter()
    candidate_one = candidate_from_jpeg(
        JPEG_1X1 + b"one",
        url="https://bw-bv-epubs.bookwalker.jp/one.jpeg",
        sequence=1,
    )
    candidate_two = candidate_from_jpeg(
        JPEG_1X1 + b"two",
        url="https://bw-bv-epubs.bookwalker.jp/two.jpeg",
        sequence=2,
    )
    assert candidate_one is not None and candidate_two is not None
    candidate_one.width = candidate_two.width = 8
    candidate_one.height = candidate_two.height = 8
    adapter._original_candidates.add(candidate_one)
    adapter._original_candidates.add(candidate_two)

    result = await adapter._evaluate_lossless_reconstruction(
        ShadowPage(),
        (CaptureResult(PNG_1X1, 8, 8),),
        [{"part": 1, "mappingId": "mapping-1"}],
    )

    part = result["parts"][0]
    assert part["candidate_count_signature_match"] == 2
    assert part["full_resolution_comparison_count"] == 2
    assert part["candidate_count_full_exact"] == 2
    assert part["raw_jpeg_exact"] is False
    assert result["spread_ready"] is False
    assert reconstruct_called is False


@pytest.mark.asyncio
async def test_lossless_shadow_signature_mismatch_skips_full_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ShadowPage:
        async def evaluate(self, _expression: str, *_args: object) -> dict[str, object]:
            return dict(EMPTY_COMPACT_PAYLOAD)

    mapping = PurchasedMapping(
        mapping=(
            {
                "source_x": 0,
                "source_y": 0,
                "destination_x": 0,
                "destination_y": 0,
                "width": 8,
                "height": 8,
            },
        ),
        source_dimensions=(8, 8),
        destination_dimensions=(8, 8),
        tile_dimensions=(8, 8),
        imagebitmap_source_id="bitmap-1",
        mapping_sha256="mapping-1",
    )
    candidate = candidate_from_jpeg(
        JPEG_1X1 + b"candidate",
        url="https://bw-bv-epubs.bookwalker.jp/page.jpeg",
        sequence=1,
    )
    assert candidate is not None
    candidate.width = 8
    candidate.height = 8
    adapter = BookWalkerAdapter()
    adapter._original_candidates.add(candidate)
    full_resolution_calls = 0

    async def fake_signature(*_args: object, **_kwargs: object) -> str:
        return "candidate-signature"

    async def fake_imagebitmap_signature(*_args: object, **_kwargs: object) -> str:
        return "different-imagebitmap-signature"

    async def fake_full_match(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal full_resolution_calls
        full_resolution_calls += 1
        return {"available": True, "exact": True}

    monkeypatch.setattr(
        adapter_module,
        "analyze_purchased_mapping",
        lambda *_args: MappingAnalysis(MAPPING_PROVEN, "ready", mapping),
    )
    monkeypatch.setattr(adapter_module, "image_signature", fake_signature)
    monkeypatch.setattr(
        adapter_module,
        "imagebitmap_signature",
        fake_imagebitmap_signature,
    )
    monkeypatch.setattr(
        adapter_module,
        "imagebitmap_pixel_exact_match",
        fake_full_match,
    )

    result = await adapter._evaluate_lossless_reconstruction(
        ShadowPage(),
        (CaptureResult(PNG_1X1, 8, 8),),
        [{"part": 1, "mappingId": "mapping-1"}],
    )

    part = result["parts"][0]
    assert part["candidate_count_dimension_match"] == 1
    assert part["candidate_count_signature_match"] == 0
    assert part["full_resolution_comparison_count"] == 0
    assert full_resolution_calls == 0
    assert result["spread_ready"] is False


def test_invalid_capture_mode_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOOKWALKER_CAPTURE_MODE", "unexpected")

    with pytest.raises(ValueError, match="BOOKWALKER_CAPTURE_MODE"):
        BookWalkerAdapter()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, True),
        ("1", True),
        ("true", True),
        ("yes", True),
        ("on", True),
        ("0", False),
        ("false", False),
        ("no", False),
        ("off", False),
    ],
)
def test_lossless_output_switch_parser(value: str | None, expected: bool) -> None:
    assert parse_bookwalker_lossless_jpeg_output(value) is expected


def test_lossless_output_switch_defaults_on_and_rejects_invalid_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BOOKWALKER_LOSSLESS_JPEG_OUTPUT", raising=False)
    assert BookWalkerAdapter().lossless_jpeg_output_enabled is True

    monkeypatch.setenv("BOOKWALKER_LOSSLESS_JPEG_OUTPUT", "maybe")
    with pytest.raises(ValueError, match="BOOKWALKER_LOSSLESS_JPEG_OUTPUT"):
        BookWalkerAdapter()
