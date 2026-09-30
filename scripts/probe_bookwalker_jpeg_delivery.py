"""Probe BookWalker's JPEG delivery without changing production capture.

The probe follows the normal BookWalker product-to-viewer entry flow with the
existing adapter, but observes every response from a BookWalker host instead
of only the production JPEG route patterns.  It records bounded response
metadata, JPEG metadata, native draw traces, and per-page JPEG/native matching
results.  It intentionally does not call ``BookWalkerAdapter.capture_page``.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import fnmatch
import hashlib
import io
import json
import os
import re
from binascii import Error as BinasciiError
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from PIL import Image, JpegImagePlugin
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page, Request, Response, Route

from screenshot_crawler.core.browser import BrowserSession, resolve_cdp_endpoint
from screenshot_crawler.core.capture import capture_png_bytes
from screenshot_crawler.core.models import ContentIdentity
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.bookwalker.adapter import BookWalkerAdapter
from screenshot_crawler.site_adapters.bookwalker.native_capture import (
    select_native_draw_calls,
)
from screenshot_crawler.site_adapters.bookwalker.original_capture import (
    image_signature,
    jpeg_dimensions,
)

DEFAULT_MAX_PAGES = 8
DEFAULT_MAX_RESPONSE_BODY_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_RESPONSES = 2_000
DEFAULT_MAX_BODY_READS = 256
DEFAULT_MAX_CONCURRENT_BODY_READS = 4
BODY_READ_TIMEOUT_MS = 5_000
PAGE_SETTLE_MS = 350

_BOOKWALKER_HOST_SUFFIX = ".bookwalker.jp"
_IMAGE_RESOURCE_TYPES = {"image", "xhr", "fetch"}
_MAGIC_TYPES = ("jpeg", "png", "webp", "avif", "gif", "unknown")

_JPEG_LUMA_BASE = (
    16,
    11,
    10,
    16,
    24,
    40,
    51,
    61,
    12,
    12,
    14,
    19,
    26,
    58,
    60,
    55,
    14,
    13,
    16,
    24,
    40,
    57,
    69,
    56,
    14,
    17,
    22,
    29,
    51,
    87,
    80,
    62,
    18,
    22,
    37,
    56,
    68,
    109,
    103,
    77,
    24,
    35,
    55,
    64,
    81,
    104,
    113,
    92,
    49,
    64,
    78,
    87,
    103,
    121,
    120,
    101,
    72,
    92,
    95,
    98,
    112,
    100,
    103,
    99,
)
_JPEG_CHROMA_BASE = (
    17,
    18,
    24,
    47,
    99,
    99,
    99,
    99,
    18,
    21,
    26,
    66,
    99,
    99,
    99,
    99,
    24,
    26,
    56,
    99,
    99,
    99,
    99,
    99,
    99,
    47,
    66,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
)
_JPEG_CHROMA_BASE = (
    17, 18, 24, 47, 99, 99, 99, 99,
    18, 21, 26, 66, 99, 99, 99, 99,
    24, 26, 56, 99, 99, 99, 99, 99,
    47, 66, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99,
)
_JPEG_SAMPLING_LABELS = {
    0: "4:4:4",
    1: "4:2:2",
    2: "4:2:0",
    3: "4:4:0",
    4: "4:1:1",
    5: "4:1:0",
}


def redact_url(value: str) -> str:
    """Keep URL shape while removing query values and long path tokens."""

    try:
        parsed = urlsplit(value)
        query_keys = sorted(
            {key for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
        )
        query = urlencode([(key, "<redacted>") for key in query_keys])
        path = "/".join(
            "<redacted>" if len(part) > 96 else part
            for part in parsed.path.split("/")
        )
        return urlunsplit((parsed.scheme, parsed.netloc, path, query, ""))
    except Exception:  # noqa: BLE001
        return "<unparseable-url>"


def is_bookwalker_host(hostname: str | None) -> bool:
    host = (hostname or "").lower().rstrip(".")
    return host == "bookwalker.jp" or host.endswith(_BOOKWALKER_HOST_SUFFIX)


def magic_type(data: bytes) -> str:
    """Identify common image formats from bytes, independent of headers/URL."""

    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brands = {data[8:12]}
        for offset in range(16, min(len(data), 64), 4):
            brands.add(data[offset : offset + 4])
        if brands & {b"avif", b"avis"}:
            return "avif"
    return "unknown"


def _scaled_quantization_table(base: tuple[int, ...], quality: int) -> tuple[int, ...]:
    scale = 5000 // quality if quality < 50 else 200 - quality * 2
    return tuple(max(1, min(255, (value * scale + 50) // 100)) for value in base)


def estimate_jpeg_quality(quantization: dict[int, list[int]]) -> int | None:
    """Return a quality only for an exact standard libjpeg table match."""

    normalized = {int(key): tuple(int(value) for value in values) for key, values in quantization.items()}
    if set(normalized) != {0, 1}:
        return None
    for quality in range(1, 101):
        expected = {
            0: _scaled_quantization_table(_JPEG_LUMA_BASE, quality),
            1: _scaled_quantization_table(_JPEG_CHROMA_BASE, quality),
        }
        if normalized == expected:
            return quality
    return None


def jpeg_metadata(data: bytes) -> dict[str, Any]:
    """Extract bounded diagnostic metadata from one JPEG body."""

    dimensions = jpeg_dimensions(data)
    metadata: dict[str, Any] = {
        "byte_size": len(data),
        "width": dimensions[0] if dimensions else None,
        "height": dimensions[1] if dimensions else None,
        "sha256": hashlib.sha256(data).hexdigest(),
        "progressive": None,
        "subsampling": None,
        "quantization_tables": None,
        "estimated_quality": None,
    }
    try:
        with Image.open(io.BytesIO(data)) as image:
            metadata["width"], metadata["height"] = image.size
            progressive_value = image.info.get("progressive", image.info.get("progression"))
            metadata["progressive"] = (
                bool(progressive_value) if progressive_value is not None else None
            )
            sampling = JpegImagePlugin.get_sampling(image)
            metadata["subsampling"] = _JPEG_SAMPLING_LABELS.get(sampling, str(sampling))
            raw_quantization = getattr(image, "quantization", {}) or {}
            quantization = {
                int(key): [int(value) for value in values]
                for key, values in raw_quantization.items()
            }
            metadata["quantization_tables"] = {
                str(key): values for key, values in sorted(quantization.items())
            }
            metadata["estimated_quality"] = estimate_jpeg_quality(quantization)
    except Exception:  # noqa: BLE001 - malformed bodies remain observable as JPEG magic
        return metadata
    return metadata


def current_route_pattern_match(
    url: str,
    patterns: tuple[str, ...] = BookWalkerAdapter.original_response_route_patterns,
) -> bool:
    """Mirror Playwright's current route-pattern intent for reporting."""

    lowered = url.lower()
    return any(fnmatch.fnmatchcase(lowered, pattern.lower()) for pattern in patterns)


def current_original_filter_match(
    *,
    url: str,
    resource_type: str,
    headers: dict[str, str],
) -> bool:
    """Apply the production filter to a small response-shaped test object."""

    response = SimpleNamespace(
        url=url,
        headers=headers,
        request=SimpleNamespace(resource_type=resource_type),
    )
    return BookWalkerAdapter._is_original_response(response)


def _header_value(headers: Any, name: str) -> str | None:
    try:
        value = headers.get(name)
    except AttributeError:
        value = None
    return str(value) if value is not None else None


def _int_or_none(value: object) -> int | None:
    try:
        return int(str(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


@dataclass(slots=True)
class MagicJpegCandidate:
    body: bytes
    record_index: int
    page_index: int
    metadata: dict[str, Any]
    url: str
    hostname: str
    path: str
    resource_type: str
    content_type: str | None
    route_match: bool
    filter_match: bool

    def public(self) -> dict[str, Any]:
        return {
            "record_index": self.record_index,
            "page_index": self.page_index,
            "url": self.url,
            "hostname": self.hostname,
            "path": self.path,
            "resource_type": self.resource_type,
            "content_type": self.content_type,
            "current_route_pattern_match": self.route_match,
            "current_original_filter_match": self.filter_match,
            **self.metadata,
        }


class ResponseCollector:
    """Collect bounded metadata and image bodies from relevant responses."""

    route_patterns = (
        "**://bookwalker.jp/**",
        "**://*.bookwalker.jp/**",
    )

    def __init__(
        self,
        *,
        max_body_bytes: int = DEFAULT_MAX_RESPONSE_BODY_BYTES,
        max_responses: int = DEFAULT_MAX_RESPONSES,
        max_body_reads: int = DEFAULT_MAX_BODY_READS,
        max_concurrent_body_reads: int = DEFAULT_MAX_CONCURRENT_BODY_READS,
    ) -> None:
        if min(max_body_bytes, max_responses, max_body_reads, max_concurrent_body_reads) <= 0:
            raise ValueError("response observation bounds must be positive")
        self.max_body_bytes = max_body_bytes
        self.max_responses = max_responses
        self.max_body_reads = max_body_reads
        self.records: list[dict[str, Any]] = []
        self.candidates: list[MagicJpegCandidate] = []
        self.active_page_index = 1
        self.body_reads_reserved = 0
        self.body_reads_completed = 0
        self.body_bytes_read = 0
        self.responses_ignored_after_limit = 0
        self.body_reads_skipped_after_limit = 0
        self._tasks: set[asyncio.Task[None]] = set()
        self._semaphore = asyncio.Semaphore(max_concurrent_body_reads)

    def set_page(self, page_index: int) -> None:
        self.active_page_index = page_index

    def _new_record(
        self,
        response: object,
        request: Request,
    ) -> dict[str, Any] | None:
        url = str(response.url)
        parsed = urlsplit(url)
        hostname = (parsed.hostname or "").lower()
        if not is_bookwalker_host(hostname):
            return None
        if len(self.records) >= self.max_responses:
            self.responses_ignored_after_limit += 1
            return None
        resource_type = str(request.resource_type or "unknown").lower()
        headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
        route_match = current_route_pattern_match(
            url, BookWalkerAdapter.original_response_route_patterns
        )
        filter_match = current_original_filter_match(
            url=url,
            resource_type=resource_type,
            headers=headers,
        )
        record: dict[str, Any] = {
            "index": len(self.records) + 1,
            "page_index": self.active_page_index,
            "url": redact_url(url),
            "hostname": hostname,
            "path": parsed.path,
            "status": response.status,
            "method": request.method,
            "resource_type": resource_type,
            "content_type": headers.get("content-type"),
            "content_length_header": headers.get("content-length"),
            "content_encoding": headers.get("content-encoding"),
            "current_route_pattern_match": route_match,
            "current_original_filter_match": filter_match,
            "body_read_status": "not_scheduled",
            "body_size": None,
            "magic_type": "unknown",
        }
        self.records.append(record)
        return record

    def _reserve_body_read(self, record: dict[str, Any]) -> bool:
        if self.body_reads_reserved >= self.max_body_reads:
            self.body_reads_skipped_after_limit += 1
            record["body_read_status"] = "skipped_body_read_limit"
            return False
        self.body_reads_reserved += 1
        record["body_read_status"] = "scheduled"
        return True

    def on_response(self, response: Response) -> None:
        """Fallback response callback used by unit tests and non-route callers."""

        record = self._new_record(response, response.request)
        if record is None:
            return
        if self._should_read_body(record):
            if not self._reserve_body_read(record):
                return
            task = asyncio.create_task(self._read_body(response, record))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    def on_cdp_response_received(
        self,
        params: dict[str, Any],
        *,
        request_methods: dict[str, str],
    ) -> dict[str, Any] | None:
        response = params.get("response") or {}
        request_id = str(params.get("requestId") or "")
        if not request_id:
            return None
        headers = {
            str(key).lower(): str(value)
            for key, value in (response.get("headers") or {}).items()
        }
        response_like = SimpleNamespace(
            url=str(response.get("url") or ""),
            status=response.get("status"),
            headers=headers,
        )
        if current_route_pattern_match(
            str(response.get("url") or ""),
            BookWalkerAdapter.original_response_route_patterns,
        ):
            return None
        request_like = SimpleNamespace(
            resource_type=str(params.get("type") or "unknown").lower(),
            method=request_methods.get(request_id, "GET"),
        )
        response_like.request = request_like
        record = self._new_record(response_like, request_like)
        return record

    def on_cdp_loading_finished(
        self,
        cdp: Any,
        params: dict[str, Any],
        record_by_request_id: dict[str, dict[str, Any]],
    ) -> None:
        request_id = str(params.get("requestId") or "")
        record = record_by_request_id.get(request_id)
        if record is None or not self._should_read_body(record):
            return
        if not self._reserve_body_read(record):
            return
        task = asyncio.create_task(self._read_cdp_body(cdp, request_id, record))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _read_cdp_body(
        self,
        cdp: Any,
        request_id: str,
        record: dict[str, Any],
    ) -> None:
        try:
            async with self._semaphore:
                payload = await asyncio.wait_for(
                    cdp.send("Network.getResponseBody", {"requestId": request_id}),
                    timeout=BODY_READ_TIMEOUT_MS / 1000,
                )
            encoded = bool(payload.get("base64Encoded"))
            body_value = payload.get("body", "")
            body = (
                base64.b64decode(body_value)
                if encoded
                else str(body_value).encode("utf-8")
            )
            self.body_reads_completed += 1
            self._store_body(record, body)
        except Exception as exc:  # noqa: BLE001 - body observation is best effort
            record["body_read_status"] = "error"
            record["body_error"] = str(exc)

    async def on_route(self, route: Route, request: Request) -> None:
        """Observe raw fetched bytes and return the same response unchanged."""

        try:
            fetched = await route.fetch()
            record = self._new_record(fetched, request)
            response_body: bytes | None = None
            if (
                record is not None
                and self._should_read_body(record)
                and self._reserve_body_read(record)
            ):
                try:
                    async with self._semaphore:
                        body = await asyncio.wait_for(
                            fetched.body(), timeout=BODY_READ_TIMEOUT_MS / 1000
                        )
                    response_body = body
                    self.body_reads_completed += 1
                    self._store_body(record, body)
                except Exception as exc:  # noqa: BLE001
                    record["body_read_status"] = "error"
                    record["body_error"] = str(exc)
            if response_body is None:
                await route.fulfill(response=fetched)
            else:
                await route.fulfill(response=fetched, body=response_body)
        except Exception:  # noqa: BLE001 - never change normal viewer flow
            try:
                await route.continue_()
            except PlaywrightError:
                return

    def _should_read_body(self, record: dict[str, Any]) -> bool:
        status = _int_or_none(record.get("status"))
        if status is None or status < 200 or status >= 300:
            return False
        content_length = _int_or_none(record.get("content_length_header"))
        if content_length is not None and content_length > self.max_body_bytes:
            record["body_read_status"] = "skipped_content_length_limit"
            record["body_size"] = content_length
            return False
        content_type = str(record.get("content_type") or "").lower()
        path = str(record.get("path") or "").lower()
        return (
            record.get("current_route_pattern_match")
            or record.get("current_original_filter_match")
            or record.get("resource_type") in _IMAGE_RESOURCE_TYPES
            or content_type.startswith("image/")
            or content_type == "application/octet-stream"
            or any(path.endswith(suffix) for suffix in (".jpg", ".jpeg", ".jpe", ".png", ".webp", ".avif", ".gif"))
        )

    async def _read_body(self, response: Response, record: dict[str, Any]) -> None:
        try:
            async with self._semaphore:
                body = await asyncio.wait_for(
                    response.body(), timeout=BODY_READ_TIMEOUT_MS / 1000
                )
            self.body_reads_completed += 1
            self._store_body(record, body)
        except Exception as exc:  # noqa: BLE001 - a failed body must not change viewer behavior
            record["body_read_status"] = "error"
            record["body_error"] = str(exc)

    def _store_body(self, record: dict[str, Any], body: bytes) -> None:
        record["body_size"] = len(body)
        self.body_bytes_read += len(body)
        if len(body) > self.max_body_bytes:
            record["body_read_status"] = "discarded_body_size_limit"
            return
        detected = magic_type(body)
        record["body_read_status"] = "read"
        record["magic_type"] = detected
        if detected == "jpeg":
            metadata = jpeg_metadata(body)
            record.update({
                "width": metadata["width"],
                "height": metadata["height"],
                "sha256": metadata["sha256"],
                "estimated_quality": metadata["estimated_quality"],
                "progressive": metadata["progressive"],
                "subsampling": metadata["subsampling"],
            })
            self.candidates.append(
                MagicJpegCandidate(
                    body=body,
                    record_index=int(record["index"]),
                    page_index=int(record["page_index"]),
                    metadata=metadata,
                    url=str(record["url"]),
                    hostname=str(record["hostname"]),
                    path=str(record["path"]),
                    resource_type=str(record["resource_type"]),
                    content_type=record.get("content_type"),
                    route_match=bool(record["current_route_pattern_match"]),
                    filter_match=bool(record["current_original_filter_match"]),
                )
            )

    async def drain(self) -> None:
        while self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
            await asyncio.sleep(0)


def _decode_png_data_url(value: object) -> bytes | None:
    if not isinstance(value, str) or not value.startswith("data:image/png;base64,"):
        return None
    try:
        return base64.b64decode(value.split(",", 1)[1], validate=True)
    except (ValueError, TypeError, BinasciiError):
        return None


def _identity_dict(identity: ContentIdentity) -> dict[str, Any]:
    return {
        "page_id": identity.page_id,
        "page_number": identity.page_number,
        "source_id": identity.source_id,
    }


def _public_draw_call(call: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in call.items()
        if key not in {"sourceCropPng", "sourceCropPngError"}
    }


async def collect_native_parts(
    page: Page,
    adapter: BookWalkerAdapter,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    """Read current production draw metadata and native source crops."""

    canvas = await adapter._visible_canvas(page)
    if canvas is None:
        return [], [], "visible canvas unavailable"
    trace_id = await canvas.get_attribute("data-bookwalker-trace-id")
    if not trace_id:
        return [], [], "canvas trace id unavailable"
    size = await canvas.evaluate("element => ({width: element.width, height: element.height})")
    width = int(size["width"])
    height = int(size["height"])
    raw_calls = await page.evaluate(
        """
        traceId => (window.__bookwalkerNativeDrawCalls || [])
          .filter(call => call.canvasId === traceId)
        """,
        trace_id,
    )
    boxes = await adapter._page_draw_rectangles(page, canvas)
    selected = select_native_draw_calls(
        raw_calls,
        canvas_id=trace_id,
        canvas_width=width,
        canvas_height=height,
        boxes=boxes,
    )
    if selected is None or len(selected) != len(boxes):
        return [_public_draw_call(call) for call in raw_calls], [], "native draw calls did not match visible geometry"
    materialized = await adapter._materialize_native_source_crops(page, selected)
    parts: list[dict[str, Any]] = []
    for index, call in enumerate(materialized, start=1):
        data = _decode_png_data_url(call.get("sourceCropPng"))
        if data is None:
            continue
        capture = capture_png_bytes(data)
        parts.append(
            {
                "part": index,
                "width": capture.width,
                "height": capture.height,
                "sha256": hashlib.sha256(data).hexdigest(),
                "signature": await image_signature(page, data, "image/png"),
                "source_constructor": (call.get("source") or {}).get("constructor"),
                "source_width": (call.get("source") or {}).get("width"),
                "source_height": (call.get("source") or {}).get("height"),
                "source_rect": call.get("sourceRect"),
                "destination": call.get("destination"),
                "argument_form": call.get("argumentForm"),
                "transform": call.get("transform"),
                "global_composite_operation": call.get("globalCompositeOperation"),
                "filter": call.get("filter"),
                "snapshot_id_present": bool(call.get("snapshotId")),
                "snapshot_error": call.get("snapshotError"),
                "_data": data,
            }
        )
    return [_public_draw_call(call) for call in raw_calls], parts, None


def _unique_candidates(candidates: list[MagicJpegCandidate]) -> list[MagicJpegCandidate]:
    unique: dict[str, MagicJpegCandidate] = {}
    for candidate in candidates:
        unique.setdefault(str(candidate.metadata["sha256"]), candidate)
    return list(unique.values())


async def classify_page(
    page: Page,
    native_parts: list[dict[str, Any]],
    candidates: list[MagicJpegCandidate],
    signature_cache: dict[tuple[str, str], str | None],
) -> tuple[str, dict[str, Any]]:
    """Match native source crops against all and current-filter JPEG sets."""

    all_candidates = _unique_candidates(candidates)
    current_candidates = [candidate for candidate in all_candidates if candidate.filter_match]
    details: dict[str, Any] = {
        "current_filter_jpeg_candidates": len(current_candidates),
        "all_magic_jpeg_candidates": len(all_candidates),
        "raw_magic_jpeg_candidates": len(candidates),
        "dimension_matches": 0,
        "signature_matches": 0,
        "native_parts": len(native_parts),
        "unique_exact_match": False,
        "current_filter_unique_exact_match": False,
    }
    if not native_parts:
        return "UNKNOWN", {**details, "reason": "native source crop unavailable"}
    if not all_candidates:
        return "NO_JPEG_OBSERVED", details

    async def candidate_signature(candidate: MagicJpegCandidate) -> str | None:
        key = (str(candidate.metadata["sha256"]), "image/jpeg")
        if key not in signature_cache:
            signature_cache[key] = await image_signature(page, candidate.body, "image/jpeg")
        return signature_cache[key]

    assignments: list[tuple[dict[str, Any], MagicJpegCandidate]] = []
    current_assignments: list[tuple[dict[str, Any], MagicJpegCandidate]] = []
    ambiguous = False
    for native in native_parts:
        dimension_candidates = [
            candidate
            for candidate in all_candidates
            if (candidate.metadata.get("width"), candidate.metadata.get("height"))
            == (native.get("width"), native.get("height"))
        ]
        details["dimension_matches"] += len(dimension_candidates)
        matching: list[MagicJpegCandidate] = []
        for candidate in dimension_candidates:
            if await candidate_signature(candidate) == native.get("signature"):
                matching.append(candidate)
        details["signature_matches"] += len(matching)
        if len(matching) == 1:
            assignments.append((native, matching[0]))
        elif len(matching) > 1:
            ambiguous = True
        current_matching = [candidate for candidate in matching if candidate.filter_match]
        if len(current_matching) == 1:
            current_assignments.append((native, current_matching[0]))
        elif len(current_matching) > 1:
            ambiguous = True

    assigned_hashes = [candidate.metadata["sha256"] for _, candidate in assignments]
    current_hashes = [candidate.metadata["sha256"] for _, candidate in current_assignments]
    unique_exact = (
        len(assignments) == len(native_parts)
        and len(set(assigned_hashes)) == len(native_parts)
        and not ambiguous
    )
    current_unique_exact = (
        len(current_assignments) == len(native_parts)
        and len(set(current_hashes)) == len(native_parts)
        and not ambiguous
    )
    details["unique_exact_match"] = unique_exact
    details["current_filter_unique_exact_match"] = current_unique_exact
    details["matched_candidates"] = [candidate.public() for _, candidate in assignments]

    if current_unique_exact:
        return "JPEG_EXACT_MATCH_CURRENT_FILTER", details
    if unique_exact:
        exact_candidates = [candidate for _, candidate in assignments]
        if any(not candidate.route_match for candidate in exact_candidates):
            return "JPEG_ROUTE_MISS", details
        if any(not candidate.filter_match for candidate in exact_candidates):
            return "JPEG_RESPONSE_FILTER_MISS", details
        return "JPEG_FILTER_MISS", details
    if ambiguous or details["signature_matches"] > len(native_parts):
        return "JPEG_AMBIGUOUS", details
    if details["dimension_matches"] == 0:
        return "JPEG_DIMENSION_MISMATCH", details
    if details["signature_matches"] == 0:
        return "JPEG_SIGNATURE_MISMATCH", details
    return "UNKNOWN", details


def _counter_dict(values: list[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def build_summary(
    *,
    label: str,
    input_url: str,
    final_url: str,
    page_records: list[dict[str, Any]],
    response_records: list[dict[str, Any]],
    candidates: list[MagicJpegCandidate],
    collector: ResponseCollector,
) -> dict[str, Any]:
    unique_candidates = _unique_candidates(candidates)
    page_classifications = Counter(str(page.get("classification")) for page in page_records)
    constructors = [
        str(part.get("source_constructor"))
        for page in page_records
        for part in page.get("native", {}).get("parts", [])
        if part.get("source_constructor")
    ]
    content_types = [str(record.get("content_type")) for record in response_records if record.get("content_type")]
    jpeg_records = [record for record in response_records if record.get("magic_type") == "jpeg"]
    filter_miss_candidates = [candidate for candidate in unique_candidates if not candidate.filter_match]
    route_miss_candidates = [candidate for candidate in filter_miss_candidates if not candidate.route_match]
    response_filter_miss_candidates = [candidate for candidate in filter_miss_candidates if candidate.route_match]
    dimension_match_count = sum(
        int(page.get("jpeg_matching", {}).get("dimension_matches", 0))
        for page in page_records
    )
    signature_match_count = sum(
        int(page.get("jpeg_matching", {}).get("signature_matches", 0))
        for page in page_records
    )
    return {
        "label": label,
        "input_url": redact_url(input_url),
        "final_url": redact_url(final_url),
        "pages_observed": len(page_records),
        "responses_observed": len(response_records),
        "hosts": _counter_dict([str(record["hostname"]) for record in response_records]),
        "magic_jpeg_hosts": _counter_dict([candidate.hostname for candidate in unique_candidates]),
        "magic_jpeg_count": len(jpeg_records),
        "unique_magic_jpeg_candidate_count": len(unique_candidates),
        "magic_jpeg_host_list": sorted({candidate.hostname for candidate in unique_candidates}),
        "route_pattern_match_count": sum(bool(record["current_route_pattern_match"]) for record in response_records),
        "current_filter_match_count": sum(bool(record["current_original_filter_match"]) for record in response_records),
        "jpeg_route_pattern_match_count": sum(candidate.route_match for candidate in unique_candidates),
        "jpeg_current_filter_match_count": sum(candidate.filter_match for candidate in unique_candidates),
        "filter_miss_jpeg_count": len(filter_miss_candidates),
        "route_miss_jpeg_count": len(route_miss_candidates),
        "response_filter_miss_jpeg_count": len(response_filter_miss_candidates),
        "dimension_match_count": dimension_match_count,
        "signature_match_count": signature_match_count,
        "page_classifications": dict(sorted(page_classifications.items())),
        "source_constructors": _counter_dict(constructors),
        "content_types": _counter_dict(content_types),
        "jpeg_paths": sorted({candidate.path for candidate in unique_candidates}),
        "jpeg_quality_estimates": _counter_dict(
            [str(candidate.metadata.get("estimated_quality")) for candidate in unique_candidates]
        ),
        "jpeg_subsampling": _counter_dict(
            [str(candidate.metadata.get("subsampling")) for candidate in unique_candidates]
        ),
        "bounds": {
            "max_response_body_bytes": collector.max_body_bytes,
            "max_responses": collector.max_responses,
            "max_body_reads": collector.max_body_reads,
            "body_reads_reserved": collector.body_reads_reserved,
            "body_reads_completed": collector.body_reads_completed,
            "body_bytes_read": collector.body_bytes_read,
            "responses_ignored_after_limit": collector.responses_ignored_after_limit,
            "body_reads_skipped_after_limit": collector.body_reads_skipped_after_limit,
        },
    }


async def run_probe(
    *,
    url: str,
    label: str,
    access_strategy: str,
    output_dir: Path,
    max_pages: int = DEFAULT_MAX_PAGES,
    cdp_endpoint: str | None = None,
    max_response_body_bytes: int = DEFAULT_MAX_RESPONSE_BODY_BYTES,
    max_responses: int = DEFAULT_MAX_RESPONSES,
    max_body_reads: int = DEFAULT_MAX_BODY_READS,
    max_concurrent_body_reads: int = DEFAULT_MAX_CONCURRENT_BODY_READS,
) -> dict[str, Any]:
    if max_pages <= 0:
        raise ValueError("max_pages must be positive")
    run_dir = output_dir / label
    run_dir.mkdir(parents=True, exist_ok=True)
    endpoint = resolve_cdp_endpoint(site="bookwalker", cli_endpoint=cdp_endpoint)
    collector = ResponseCollector(
        max_body_bytes=max_response_body_bytes,
        max_responses=max_responses,
        max_body_reads=max_body_reads,
        max_concurrent_body_reads=max_concurrent_body_reads,
    )
    page_records: list[dict[str, Any]] = []
    final_url = url
    signature_cache: dict[tuple[str, str], str | None] = {}
    session = await BrowserSession.connect(endpoint)
    page = await session.new_page()
    adapter = BookWalkerAdapter(
        auto_login_email=os.environ.get("BOOKWALKER_EMAIL"),
        auto_login_password=os.environ.get("BOOKWALKER_PASSWORD"),
    )
    cdp = await session.context.new_cdp_session(page)
    request_methods: dict[str, str] = {}
    record_by_request_id: dict[str, dict[str, Any]] = {}

    def on_cdp_request(params: dict[str, Any]) -> None:
        request_id = str(params.get("requestId") or "")
        request = params.get("request") or {}
        if request_id:
            request_methods[request_id] = str(request.get("method") or "GET")

    def on_cdp_response(params: dict[str, Any]) -> None:
        record = collector.on_cdp_response_received(
            params,
            request_methods=request_methods,
        )
        if record is not None:
            record_by_request_id[str(params.get("requestId") or "")] = record

    def on_cdp_loading_finished(params: dict[str, Any]) -> None:
        collector.on_cdp_loading_finished(cdp, params, record_by_request_id)

    cdp.on("Network.requestWillBeSent", on_cdp_request)
    cdp.on("Network.responseReceived", on_cdp_response)
    cdp.on("Network.loadingFinished", on_cdp_loading_finished)
    try:
        await cdp.send("Network.enable")
        await adapter.prepare_page(page)
        for pattern in BookWalkerAdapter.original_response_route_patterns:
            await page.route(pattern, collector.on_route)
        await adapter.configure_run(page, access_strategy)  # type: ignore[arg-type]
        collector.set_page(1)
        await page.goto(url, wait_until="commit", timeout=60_000)
        await adapter.initialize(page)
        await page.wait_for_timeout(PAGE_SETTLE_MS)
        await collector.drain()

        for page_index in range(1, max_pages + 1):
            collector.set_page(page_index)
            state = await adapter.detect_state(page)
            if state is not PageState.CONTENT:
                break
            identity = await adapter.get_content_identity(page)
            raw_draw_calls, native_parts, native_error = await collect_native_parts(page, adapter)
            page_candidates = [
                candidate
                for candidate in collector.candidates
                if candidate.page_index <= page_index
            ]
            classification, matching = await classify_page(
                page, native_parts, page_candidates, signature_cache
            )
            counter = page.locator("#pageSliderCounter")
            page_counter = await counter.inner_text() if await counter.count() else None
            public_native_parts = [
                {key: value for key, value in part.items() if key != "_data"}
                for part in native_parts
            ]
            page_records.append(
                {
                    "page_index": page_index,
                    "page_counter": page_counter,
                    "url": redact_url(page.url),
                    "identity": _identity_dict(identity),
                    "native": {
                        "parts": public_native_parts,
                        "source_constructors": _counter_dict(
                            [
                                str(part.get("source_constructor"))
                                for part in native_parts
                                if part.get("source_constructor")
                            ]
                        ),
                        "error": native_error,
                    },
                    "draw_calls": raw_draw_calls,
                    "jpeg_matching": matching,
                    "classification": classification,
                }
            )
            if page_index >= max_pages:
                break
            await page.evaluate(
                "window.__bookwalkerNativeDrawCalls = []; window.__bookwalkerDrawCalls = [];"
            )
            previous_identity = identity
            collector.set_page(page_index + 1)
            await adapter.go_next(page)
            await adapter.wait_for_change(page, previous_identity)
            await adapter._wait_for_render_ready(page)
            await page.wait_for_timeout(PAGE_SETTLE_MS)
            await collector.drain()
        final_url = page.url
    finally:
        await collector.drain()
        final_url = page.url
        try:
            await cdp.detach()
        except PlaywrightError:
            pass
        await session.close_page(page)
        await session.close()

    summary = build_summary(
        label=label,
        input_url=url,
        final_url=final_url,
        page_records=page_records,
        response_records=collector.records,
        candidates=collector.candidates,
        collector=collector,
    )
    (run_dir / "responses.jsonl").write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in collector.records),
        encoding="utf-8",
    )
    (run_dir / "jpeg_candidates.json").write_text(
        json.dumps([candidate.public() for candidate in collector.candidates], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_dir / "pages.json").write_text(
        json.dumps(page_records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--access-strategy", choices=("auto", "direct", "quota"), default="auto")
    parser.add_argument("--max-pages", type=_positive_int, default=DEFAULT_MAX_PAGES)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cdp-endpoint")
    parser.add_argument("--max-response-body-bytes", type=_positive_int, default=DEFAULT_MAX_RESPONSE_BODY_BYTES)
    parser.add_argument("--max-responses", type=_positive_int, default=DEFAULT_MAX_RESPONSES)
    parser.add_argument("--max-body-reads", type=_positive_int, default=DEFAULT_MAX_BODY_READS)
    parser.add_argument("--max-concurrent-body-reads", type=_positive_int, default=DEFAULT_MAX_CONCURRENT_BODY_READS)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.label):
        parser.error("--label must contain only letters, digits, '.', '_' or '-'")
    summary = asyncio.run(
        run_probe(
            url=args.url,
            label=args.label,
            access_strategy=args.access_strategy,
            output_dir=args.output_dir,
            max_pages=args.max_pages,
            cdp_endpoint=args.cdp_endpoint,
            max_response_body_bytes=args.max_response_body_bytes,
            max_responses=args.max_responses,
            max_body_reads=args.max_body_reads,
            max_concurrent_body_reads=args.max_concurrent_body_reads,
        )
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
