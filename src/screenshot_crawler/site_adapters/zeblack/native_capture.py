"""Pure helpers for Zeblack page attribution and source-native capture."""

from __future__ import annotations

import io
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from PIL import Image, UnidentifiedImageError

from screenshot_crawler.core.capture import CaptureResult

_PAGE_ALT_RE = re.compile(r"^page_(?P<index>[0-9]+)$")
_ZEBLACK_BLOB_PREFIX = "blob:https://zebrack-comic.shueisha.co.jp/"


def parse_zeblack_page_alt(value: object) -> int | None:
    """Parse only the verified ``page_N`` image label form."""

    if not isinstance(value, str):
        return None
    match = _PAGE_ALT_RE.fullmatch(value)
    return int(match.group("index")) if match is not None else None


def is_zeblack_blob_url(url: object) -> bool:
    """Accept only blob URLs created by the verified Zeblack viewer origin."""

    if not isinstance(url, str) or not url.startswith(_ZEBLACK_BLOB_PREFIX):
        return False
    embedded = urlsplit(url[len("blob:") :])
    return embedded.scheme == "https" and embedded.hostname == "zebrack-comic.shueisha.co.jp"


def is_zeblack_blob_response(response: object) -> bool:
    """Return whether a Playwright response is an eligible blob response."""

    return is_zeblack_blob_url(getattr(response, "url", None))


def _value(row: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in row:
            return row[name]
    return default


def _as_positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _is_active(row: Mapping[str, Any]) -> bool:
    visible = _value(row, "visible", "visibility", default=False)
    if isinstance(visible, str):
        visible = visible not in {"", "hidden", "collapse", "none"}
    return bool(visible) and bool(_value(row, "in_viewport", "inViewport", default=False))


def select_zeblack_active_rows(rows: object) -> list[dict[str, object]]:
    """Validate and numerically order the active page image rows.

    Non-page images and page images outside the viewport are ignored. Any
    malformed or ambiguous active page candidate raises ``ValueError`` so a
    caller cannot silently recover using DOM or screen order.
    """

    if not isinstance(rows, list):
        raise TypeError("Zeblack image rows are not a list")

    selected: list[dict[str, object]] = []
    for dom_order, raw in enumerate(rows):
        if not isinstance(raw, Mapping):
            continue
        alt = _value(raw, "page_alt", "pageAlt", "alt", default="")
        if not isinstance(alt, str):
            alt = ""
        page_index = parse_zeblack_page_alt(alt)
        if alt.startswith("page_") and page_index is None:
            raise ValueError(f"Malformed Zeblack page alt: {alt!r}")
        if page_index is None or not _is_active(raw):
            continue

        current_src = _value(raw, "current_src", "currentSrc", default="")
        src = _value(raw, "src", default="")
        source_url = current_src or src
        natural_width = _as_positive_int(
            _value(raw, "natural_width", "naturalWidth", default=0)
        )
        natural_height = _as_positive_int(
            _value(raw, "natural_height", "naturalHeight", default=0)
        )
        if natural_width is None or natural_height is None:
            raise ValueError(f"Invalid natural dimensions for {alt}")
        if not is_zeblack_blob_url(source_url):
            raise ValueError(f"Active {alt} has no Zeblack blob source")

        normalized = dict(raw)
        normalized.update(
            {
                "page_alt": alt,
                "page_index": page_index,
                "current_src": str(current_src or ""),
                "source_url": str(source_url),
                "natural_width": natural_width,
                "natural_height": natural_height,
                "dom_order": int(_value(raw, "dom_order", "domOrder", default=dom_order)),
            }
        )
        selected.append(normalized)

    indices = [int(row["page_index"]) for row in selected]
    if len(indices) != len(set(indices)):
        raise ValueError("Duplicate active Zeblack page index")
    source_urls = [str(row["source_url"]) for row in selected]
    if len(source_urls) != len(set(source_urls)):
        raise ValueError("Duplicate active Zeblack blob source")
    return sorted(selected, key=lambda row: int(row["page_index"]))


def source_image_info(data: bytes) -> tuple[str, tuple[int, int]] | None:
    """Decode a supported source image and return its format and dimensions."""

    if not isinstance(data, bytes) or not data:
        return None
    try:
        with Image.open(io.BytesIO(data)) as image:
            image_format = image.format
            if image_format not in {"JPEG", "WEBP"}:
                return None
            if image.width <= 0 or image.height <= 0:
                return None
            dimensions = (int(image.width), int(image.height))
            image.load()
    except (UnidentifiedImageError, OSError, ValueError):
        return None
    return image_format, dimensions


def jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    """Decode and validate JPEG bytes without changing them.

    Keep this narrow helper for callers that specifically need to assert JPEG
    input. Zeblack production capture uses :func:`source_image_info` because
    the viewer can expose either JPEG or WebP blob bodies.
    """

    info = source_image_info(data)
    if info is None or info[0] != "JPEG":
        return None
    return info[1]


def capture_zeblack_source_image(
    data: bytes,
    *,
    expected_width: int,
    expected_height: int,
) -> CaptureResult:
    """Build a source-native result when format and DOM dimensions agree."""

    info = source_image_info(data)
    if info is None:
        raise ValueError("blob response is not a supported decodable image")
    image_format, dimensions = info
    if dimensions != (expected_width, expected_height):
        raise ValueError(
            "blob image dimensions do not match HTMLImageElement natural dimensions"
        )
    mime_type, file_extension = {
        "JPEG": ("image/jpeg", ".jpg"),
        "WEBP": ("image/webp", ".webp"),
    }[image_format]
    return CaptureResult(
        data=data,
        width=dimensions[0],
        height=dimensions[1],
        mime_type=mime_type,
        file_extension=file_extension,
    )


def capture_zeblack_jpeg(
    data: bytes,
    *,
    expected_width: int,
    expected_height: int,
) -> CaptureResult:
    """Build a JPEG-only result for backwards-compatible helper callers."""

    result = capture_zeblack_source_image(
        data,
        expected_width=expected_width,
        expected_height=expected_height,
    )
    if result.mime_type != "image/jpeg":
        raise ValueError("blob response is not a decodable JPEG")
    return result
