from __future__ import annotations

import io
import struct

from PIL import Image

from screenshot_crawler.site_adapters.kadocomi.native_capture import (
    MAX_NATIVE_BLOB_BYTES,
    capture_kadocomi_webp,
    source_identity_metadata,
)


def _webp(width: int = 13, height: int = 7) -> bytes:
    output = io.BytesIO()
    Image.new("RGBA", (width, height), (23, 87, 141, 191)).save(
        output, format="WEBP", lossless=True, exact=True
    )
    return output.getvalue()


def test_kadocomi_capture_preserves_verified_webp_bytes_and_accepts_empty_mime() -> None:
    original = _webp()

    result = capture_kadocomi_webp(
        original,
        source_mime_type="",
        width=13,
        height=7,
    )

    assert result is not None
    assert result.data is original
    assert (result.width, result.height) == (13, 7)
    assert (result.mime_type, result.file_extension) == ("image/webp", ".webp")


def test_kadocomi_capture_rejects_unknown_mime_corrupt_length_and_unsafe_dimensions() -> None:
    original = _webp()
    corrupt = bytearray(original)
    struct.pack_into("<I", corrupt, 4, len(original) - 7)

    assert capture_kadocomi_webp(
        original, source_mime_type="image/png", width=13, height=7
    ) is None
    assert capture_kadocomi_webp(
        bytes(corrupt), source_mime_type="image/webp", width=13, height=7
    ) is None
    assert capture_kadocomi_webp(
        original, source_mime_type="image/webp", width=13, height=7_000_000
    ) is None
    assert capture_kadocomi_webp(
        b"RIFF\x00\x00\x00\x00WEBP" + b"x" * MAX_NATIVE_BLOB_BYTES,
        source_mime_type="image/webp",
        width=13,
        height=7,
    ) is None


def test_kadocomi_source_identity_metadata_reads_only_the_requested_slot() -> None:
    snapshot = {
        "slideRows": [
            {
                "contentCanvases": [
                    {"slot": "canvas-1", "last": {"sourceTag": "IMG", "sourceUrl": "blob:one"}},
                    {"slot": "canvas-2", "last": {"sourceTag": "IMG", "sourceUrl": "blob:two"}},
                ]
            }
        ]
    }

    assert source_identity_metadata(snapshot, "canvas-2") == {
        "sourceTag": "IMG",
        "sourceUrl": "blob:two",
    }
    assert source_identity_metadata(snapshot, "missing") is None
    assert source_identity_metadata(None, "canvas-1") is None
