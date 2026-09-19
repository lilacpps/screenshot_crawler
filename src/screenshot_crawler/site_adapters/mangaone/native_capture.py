"""Manga ONE source-byte capture helpers.

The live viewer exposes the selected page image through a ``blob:`` URL.
Manga ONE's blob response body is already a complete WebP or PNG image, so
this module validates and describes those bytes without re-encoding them.
"""

from __future__ import annotations

import struct

from screenshot_crawler.core.capture import CaptureResult


def detected_image_format(data: bytes) -> str | None:
    """Return a supported raster MIME type based on magic bytes."""

    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def image_dimensions(data: bytes) -> tuple[int, int] | None:
    """Read dimensions from supported PNG and WebP headers."""

    if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    if len(data) < 20 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None

    chunk_type = data[12:16]
    if chunk_type == b"VP8X" and len(data) >= 30:
        return (
            1 + int.from_bytes(data[24:27], "little"),
            1 + int.from_bytes(data[27:30], "little"),
        )
    if chunk_type == b"VP8L" and len(data) >= 25 and data[20] == 0x2F:
        bits = int.from_bytes(data[21:25], "little")
        return ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
    if chunk_type == b"VP8 " and len(data) >= 30:
        marker = b"\x9d\x01\x2a"
        index = data.find(marker, 20, min(len(data), 64))
        if index >= 0 and index + 7 <= len(data):
            return (
                int.from_bytes(data[index + 3 : index + 5], "little") & 0x3FFF,
                int.from_bytes(data[index + 5 : index + 7], "little") & 0x3FFF,
            )
    return None


def capture_source_bytes(data: bytes) -> CaptureResult | None:
    """Describe valid Manga ONE source bytes, preserving them byte-for-byte."""

    image_format = detected_image_format(data)
    dimensions = image_dimensions(data)
    if image_format is None or dimensions is None:
        return None
    extension = ".webp" if image_format == "image/webp" else ".png"
    return CaptureResult(
        data=data,
        width=dimensions[0],
        height=dimensions[1],
        mime_type=image_format,
        file_extension=extension,
    )
