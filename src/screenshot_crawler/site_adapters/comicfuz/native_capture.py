"""Validation for ComicFUZ viewer-delivered JPEG response bytes."""

from __future__ import annotations

from io import BytesIO

from PIL import Image, UnidentifiedImageError

from screenshot_crawler.core.capture import CaptureResult

MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_SOURCE_PIXELS = 40_000_000


def capture_comicfuz_source_bytes(
    data: bytes,
    *,
    expected_width: int,
    expected_height: int,
) -> CaptureResult | None:
    """Accept only a complete JPEG matching the selected HTML image dimensions."""

    if (
        not data
        or len(data) > MAX_SOURCE_BYTES
        or not data.startswith(b"\xff\xd8\xff")
        or not data.endswith(b"\xff\xd9")
        or expected_width <= 0
        or expected_height <= 0
        or expected_width * expected_height > MAX_SOURCE_PIXELS
    ):
        return None
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format != "JPEG" or image.size != (expected_width, expected_height):
                return None
            image.verify()
    except (OSError, ValueError, UnidentifiedImageError):
        return None
    return CaptureResult(
        data=data,
        width=expected_width,
        height=expected_height,
        mime_type="image/jpeg",
        file_extension=".jpg",
    )
