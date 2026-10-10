from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from screenshot_crawler.core.errors import UnknownPageStateError
from screenshot_crawler.site_adapters.hanayume import native_capture


def _opaque_png(width: int = 13, height: int = 7) -> bytes:
    output = io.BytesIO()
    Image.new("RGBA", (width, height), (23, 87, 141, 255)).save(output, format="PNG")
    return output.getvalue()


def test_hanayume_native_webp_is_single_vp8l_and_exact_rgba() -> None:
    source = _opaque_png()
    image = native_capture.NativeImage(slot=4, width=13, height=7, png=source)

    (capture,) = native_capture.encode_native_webp((image,))

    assert capture.mime_type == "image/webp"
    assert capture.file_extension == ".webp"
    assert (capture.width, capture.height) == (13, 7)
    assert native_capture._single_vp8l(capture.data, width=13, height=7)
    with Image.open(io.BytesIO(capture.data)) as decoded:
        actual = decoded.convert("RGBA").tobytes()
    with Image.open(io.BytesIO(source)) as original:
        expected = original.convert("RGBA").tobytes()
    assert actual == expected


def test_hanayume_native_webp_rejects_extra_chunk_and_wrong_dimensions() -> None:
    (capture,) = native_capture.encode_native_webp(
        (native_capture.NativeImage(1, 13, 7, _opaque_png()),)
    )

    assert not native_capture._single_vp8l(capture.data + b"JUNK", width=13, height=7)
    assert not native_capture._single_vp8l(capture.data, width=12, height=7)


def test_hanayume_native_webp_codec_failure_keeps_the_same_png(monkeypatch) -> None:
    source = _opaque_png()
    monkeypatch.setattr(native_capture.features, "check", lambda _name: False)

    (capture,) = native_capture.encode_native_webp(
        (native_capture.NativeImage(2, 13, 7, source),)
    )

    assert capture.data == source
    assert capture.mime_type == "image/png"
    assert capture.file_extension == ".png"


def test_hanayume_capture_image_decode_requires_expected_order_and_opaque_native_pixels() -> None:
    encoded = "data:image/png;base64," + base64.b64encode(_opaque_png()).decode("ascii")
    rows = [{"slot": 3, "width": 13, "height": 7, "png": encoded}]

    assert native_capture.decode_capture_images(
        rows, expected_slots=(3,), require_opaque=True
    )[0].png == _opaque_png()

    rows[0]["slot"] = 4
    with pytest.raises(UnknownPageStateError, match="order"):
        native_capture.decode_capture_images(rows, expected_slots=(3,), require_opaque=True)
