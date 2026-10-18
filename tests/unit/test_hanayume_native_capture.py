from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from screenshot_crawler.core.errors import UnknownPageStateError
from screenshot_crawler.site_adapters.hanayume import native_capture


def _opaque_png(width: int = 13, height: int = 7) -> bytes:
    output = io.BytesIO()
    image = Image.new("RGBA", (width, height), (23, 87, 141, 255))
    image.putpixel((width - 1, height - 1), (141, 23, 87, 255))
    image.save(output, format="PNG")
    return output.getvalue()


@pytest.mark.parametrize("dimensions", [(13, 7), (960, 1540), (960, 1508), (1200, 1600)])
def test_hanayume_native_webp_is_single_vp8l_and_exact_rgba(dimensions) -> None:
    width, height = dimensions
    source = _opaque_png(width, height)
    image = native_capture.NativeImage(slot=4, width=width, height=height, png=source)

    (capture,) = native_capture.encode_native_webp((image,))

    assert capture.mime_type == "image/webp"
    assert capture.file_extension == ".webp"
    assert (capture.width, capture.height) == dimensions
    assert native_capture._single_vp8l(capture.data, width=width, height=height)
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


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [(960, 1508, True), (1200, 1600, True), (2000, 2000, True),
     (2001, 2000, False), (4097, 1, False), (1, 4097, False),
     (0, 1508, False), (-1, 1508, False), (True, 1508, False), (960, 1508.0, False)],
)
def test_hanayume_native_dimensions_are_bounded(width, height, expected: bool) -> None:
    assert native_capture.valid_native_dimensions(width, height) is expected


def test_hanayume_capture_image_decode_requires_expected_order_and_opaque_native_pixels() -> None:
    encoded = "data:image/png;base64," + base64.b64encode(_opaque_png()).decode("ascii")
    rows = [{"slot": 3, "width": 13, "height": 7, "png": encoded}]

    assert native_capture.decode_capture_images(
        rows, expected_slots=(3,), require_opaque=True
    )[0].png == _opaque_png()

    rows[0]["slot"] = 4
    with pytest.raises(UnknownPageStateError, match="order"):
        native_capture.decode_capture_images(rows, expected_slots=(3,), require_opaque=True)

    rows[0].update(slot=3, width=4097, height=1)
    with pytest.raises(UnknownPageStateError, match="capture limits"):
        native_capture.decode_capture_images(rows, expected_slots=(3,), require_opaque=True)
