"""BookWalker original JPEG capture and matching helpers.

BookWalker viewer responses on the ``viewer-epubs*.bookwalker.jp`` and
``bw-bv-epubs.bookwalker.jp`` hosts are already complete JPEG images in the
currently observed viewer. This module keeps that optimization deliberately
conservative: bytes must be valid JPEG, their dimensions must match the native
source PNG, and a browser-side 64x64 RGBA signature must match exactly. The
same signature contract is also available for a retained ImageBitmap used by
the purchased-JPEG shadow path.
"""

from __future__ import annotations

import base64
import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from screenshot_crawler.core.capture import CaptureResult

JPEG_SOI = b"\xff\xd8\xff"
DEFAULT_CACHE_ENTRIES = 32
DEFAULT_CACHE_BYTES = 64 * 1024 * 1024
MAX_RESPONSE_BODY_BYTES = 16 * 1024 * 1024

_JPEG_SOF_MARKERS = frozenset(
    {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
)
_JPEG_STANDALONE_MARKERS = frozenset({0x01, 0xD8, 0xD9, *range(0xD0, 0xD8)})

_SIGNATURE_SCRIPT = """
async ({encoded, mimeType}) => {
  const binary = atob(encoded);
  const bytes = Uint8Array.from(binary, character => character.charCodeAt(0));
  const blob = new Blob([bytes], {type: mimeType});
  const bitmap = await createImageBitmap(blob);
  try {
    const canvas = document.createElement('canvas');
    canvas.width = 64;
    canvas.height = 64;
    const context = canvas.getContext('2d', {willReadFrequently: true});
    if (!context) return null;
    context.clearRect(0, 0, 64, 64);
    context.drawImage(
      bitmap,
      0, 0, bitmap.width, bitmap.height,
      0, 0, 64, 64,
    );
    const rgba = context.getImageData(0, 0, 64, 64).data;
    // Keep the signature deterministic without depending on WebCrypto being
    // enabled on every local/test origin. Both JPEG and PNG use this exact
    // browser-side decode and resize path.
    let first = 2166136261;
    let second = 2246822519;
    let third = 3266489917;
    let fourth = 668265263;
    for (const value of rgba) {
      first = Math.imul(first ^ value, 16777619);
      second = Math.imul(second ^ first, 2246822519);
      third = Math.imul(third ^ second, 3266489917);
      fourth = Math.imul(fourth ^ third, 668265263);
    }
    const word = value => (value >>> 0).toString(16).padStart(8, '0');
    return word(first) + word(second) + word(third) + word(fourth);
  } finally {
    bitmap.close();
  }
}
"""

_IMAGEBITMAP_SIGNATURE_SCRIPT = """
async ({sourceId}) => {
  const source = window.__bookwalkerNativeSourceObjects?.get(String(sourceId));
  if (!source || source.constructor?.name !== 'ImageBitmap') return null;
  const canvas = document.createElement('canvas');
  canvas.width = 64;
  canvas.height = 64;
  const context = canvas.getContext('2d', {willReadFrequently: true});
  if (!context) return null;
  context.clearRect(0, 0, 64, 64);
  context.drawImage(
    source,
    0, 0, source.width, source.height,
    0, 0, 64, 64,
  );
  const rgba = context.getImageData(0, 0, 64, 64).data;
  // This is intentionally the same deterministic hash as _SIGNATURE_SCRIPT.
  let first = 2166136261;
  let second = 2246822519;
  let third = 3266489917;
  let fourth = 668265263;
  for (const value of rgba) {
    first = Math.imul(first ^ value, 16777619);
    second = Math.imul(second ^ first, 2246822519);
    third = Math.imul(third ^ second, 3266489917);
    fourth = Math.imul(fourth ^ third, 668265263);
  }
  const word = value => (value >>> 0).toString(16).padStart(8, '0');
  return word(first) + word(second) + word(third) + word(fourth);
}
"""

_FULL_RESOLUTION_IMAGEBITMAP_MATCH_SCRIPT = """
async ({encoded, mimeType, sourceId}) => {
  const source = window.__bookwalkerNativeSourceObjects?.get(String(sourceId));
  if (!source || source.constructor?.name !== 'ImageBitmap') {
    return {available: false, exact: false, reason: 'ImageBitmap source unavailable'};
  }
  const binary = atob(encoded);
  const bytes = Uint8Array.from(binary, character => character.charCodeAt(0));
  let candidate = null;
  try {
    candidate = await createImageBitmap(new Blob([bytes], {type: mimeType}));
    if (candidate.width !== source.width || candidate.height !== source.height) {
      return {
        available: true,
        dimensions_equal: false,
        exact: false,
        source_dimensions: [source.width, source.height],
        candidate_dimensions: [candidate.width, candidate.height],
      };
    }
    const canvas = document.createElement('canvas');
    canvas.width = source.width;
    canvas.height = source.height;
    const context = canvas.getContext('2d', {willReadFrequently: true});
    if (!context) return {available: false, exact: false, reason: '2d context unavailable'};
    context.drawImage(source, 0, 0);
    const sourceData = context.getImageData(0, 0, source.width, source.height).data;
    context.clearRect(0, 0, source.width, source.height);
    context.drawImage(candidate, 0, 0);
    const candidateData = context.getImageData(0, 0, candidate.width, candidate.height).data;
    let differingPixels = 0;
    let maxChannelDifference = 0;
    for (let index = 0; index < sourceData.length; index += 4) {
      let different = false;
      for (let channel = 0; channel < 4; channel += 1) {
        const difference = Math.abs(sourceData[index + channel] - candidateData[index + channel]);
        maxChannelDifference = Math.max(maxChannelDifference, difference);
        different ||= difference !== 0;
      }
      if (different) differingPixels += 1;
    }
    return {
      available: true,
      dimensions_equal: true,
      exact: differingPixels === 0,
      width: source.width,
      height: source.height,
      differing_pixel_count: differingPixels,
      max_channel_difference: maxChannelDifference,
    };
  } finally {
    candidate?.close();
  }
}
"""


def is_jpeg_bytes(data: bytes) -> bool:
    """Return whether bytes have the JPEG SOI magic prefix."""

    return data.startswith(JPEG_SOI)


def jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    """Read width and height from a JPEG SOF marker without decoding it."""

    if not is_jpeg_bytes(data):
        return None

    offset = 2
    data_length = len(data)
    while offset < data_length:
        while offset < data_length and data[offset] != 0xFF:
            offset += 1
        if offset >= data_length:
            return None
        while offset < data_length and data[offset] == 0xFF:
            offset += 1
        if offset >= data_length:
            return None
        marker = data[offset]
        offset += 1
        if marker == 0x00:
            continue
        if marker in _JPEG_STANDALONE_MARKERS:
            continue
        if offset + 2 > data_length:
            return None
        segment_length = int.from_bytes(data[offset : offset + 2], "big")
        if segment_length < 2 or offset + segment_length > data_length:
            return None
        if marker in _JPEG_SOF_MARKERS:
            if segment_length < 7:
                return None
            height = int.from_bytes(data[offset + 3 : offset + 5], "big")
            width = int.from_bytes(data[offset + 5 : offset + 7], "big")
            return (width, height) if width > 0 and height > 0 else None
        offset += segment_length
    return None


def redacted_image_url(url: str) -> str:
    """Keep only the URL origin/path for internal candidate identification."""

    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


@dataclass(slots=True)
class OriginalJpegCandidate:
    """A bounded-cache entry for one response body."""

    data: bytes
    mime_type: str
    file_extension: str
    width: int
    height: int
    sha256: str
    redacted_url: str
    sequence: int
    fetched_at: float
    signature: str | None = None


def is_purchased_jpeg_candidate(candidate: OriginalJpegCandidate) -> bool:
    """Return whether a cached candidate came from the purchased image host."""

    return urlsplit(candidate.redacted_url).netloc.lower() == "bw-bv-epubs.bookwalker.jp"


def candidate_from_jpeg(
    data: bytes,
    *,
    url: str,
    sequence: int,
    fetched_at: float | None = None,
) -> OriginalJpegCandidate | None:
    """Validate JPEG magic/dimensions and create a byte-preserving candidate."""

    dimensions = jpeg_dimensions(data)
    if dimensions is None:
        return None
    return OriginalJpegCandidate(
        data=data,
        mime_type="image/jpeg",
        file_extension=".jpg",
        width=dimensions[0],
        height=dimensions[1],
        sha256=hashlib.sha256(data).hexdigest(),
        redacted_url=redacted_image_url(url),
        sequence=sequence,
        fetched_at=time.time() if fetched_at is None else fetched_at,
    )


class OriginalJpegCache:
    """Bounded, de-duplicating cache for recent BookWalker JPEG bodies."""

    def __init__(
        self,
        *,
        max_entries: int = DEFAULT_CACHE_ENTRIES,
        max_bytes: int = DEFAULT_CACHE_BYTES,
    ) -> None:
        if max_entries <= 0 or max_bytes <= 0:
            raise ValueError("JPEG cache bounds must be positive")
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self._entries: OrderedDict[str, OriginalJpegCandidate] = OrderedDict()
        self._total_bytes = 0

    def add(self, candidate: OriginalJpegCandidate) -> bool:
        """Add a candidate unless it duplicates or exceeds the body bound."""

        if len(candidate.data) > self.max_bytes:
            return False
        if candidate.sha256 in self._entries:
            return False
        self._entries[candidate.sha256] = candidate
        self._total_bytes += len(candidate.data)
        while (
            len(self._entries) > self.max_entries
            or self._total_bytes > self.max_bytes
        ):
            _, removed = self._entries.popitem(last=False)
            self._total_bytes -= len(removed.data)
        return True

    def values(self) -> tuple[OriginalJpegCandidate, ...]:
        """Return a stable snapshot for one matching attempt."""

        return tuple(self._entries.values())

    def clear(self) -> None:
        self._entries.clear()
        self._total_bytes = 0

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def total_bytes(self) -> int:
        return self._total_bytes


async def image_signature(page: object, data: bytes, mime_type: str) -> str | None:
    """Decode, resize, and hash one image through the current browser page."""

    encoded = base64.b64encode(data).decode("ascii")
    try:
        result = await page.evaluate(  # type: ignore[attr-defined]
            _SIGNATURE_SCRIPT,
            {"encoded": encoded, "mimeType": mime_type},
        )
    except Exception:  # noqa: BLE001 - signature failure must use PNG fallback
        return None
    return result if isinstance(result, str) and result else None


async def imagebitmap_signature(page: object, source_id: str) -> str | None:
    """Hash a retained ImageBitmap with the existing 64x64 signature contract."""

    try:
        result = await page.evaluate(  # type: ignore[attr-defined]
            _IMAGEBITMAP_SIGNATURE_SCRIPT,
            {"sourceId": source_id},
        )
    except Exception:  # noqa: BLE001 - signature failure must use PNG fallback
        return None
    return result if isinstance(result, str) and result else None


async def imagebitmap_pixel_exact_match(
    page: object,
    data: bytes,
    source_id: str,
    mime_type: str = "image/jpeg",
) -> dict[str, object]:
    """Compare a candidate JPEG to a retained ImageBitmap at full resolution.

    This deliberately does not resize either image.  It is used only by the
    purchased shadow path after the ordinary original-JPEG match has failed.
    """

    encoded = base64.b64encode(data).decode("ascii")
    try:
        result = await page.evaluate(  # type: ignore[attr-defined]
            _FULL_RESOLUTION_IMAGEBITMAP_MATCH_SCRIPT,
            {"encoded": encoded, "mimeType": mime_type, "sourceId": source_id},
        )
    except Exception:  # noqa: BLE001 - shadow validation must fail closed
        return {"available": False, "exact": False, "reason": "browser comparison failed"}
    return result if isinstance(result, dict) else {
        "available": False,
        "exact": False,
        "reason": "browser comparison returned invalid data",
    }


def candidate_capture(candidate: OriginalJpegCandidate) -> CaptureResult:
    """Turn a validated candidate into a byte-preserving CaptureResult."""

    return CaptureResult(
        data=candidate.data,
        width=candidate.width,
        height=candidate.height,
        mime_type=candidate.mime_type,
        file_extension=candidate.file_extension,
    )
