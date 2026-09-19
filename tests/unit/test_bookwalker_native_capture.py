from __future__ import annotations

import base64

from screenshot_crawler.core.capture import capture_png_bytes
from screenshot_crawler.core.errors import CaptureUnavailableError
from screenshot_crawler.site_adapters.bookwalker.adapter import (
    _capture_from_data_url,
    _native_call_is_safe,
)

PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x04\x00\x00\x00\xb5\x1c\x0c\x02"
    b"\x00\x00\x00\x0bIDAT\x08\xd7c\x9a\xc0\xf0\x1f\x00\x05\x01\x01\x02"
    b"\x1b\xc9\x8d\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _safe_call() -> dict:
    return {
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
