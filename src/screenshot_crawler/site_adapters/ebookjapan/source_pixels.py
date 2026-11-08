"""Bounded, deterministic WebP atlas reconstruction for EbookJapan C captures.

This module intentionally has no browser or network dependencies. The caller
must establish response, page, frame, draw-state, and epoch identity before it
passes already-read bytes and observed integer ROIs here.
"""

from __future__ import annotations

import hashlib
import io
import json
import struct
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Final

from PIL import Image, ImageChops, ImageStat, features

from screenshot_crawler.core.capture import CaptureResult

MAX_SOURCE_BODY_BYTES: Final = 8 * 1024 * 1024
MAX_SOURCE_PIXEL_COUNT: Final = 4_000_000
MAX_TARGET_PIXEL_COUNT: Final = 2_000_000
MAX_ROI_OPERATIONS: Final = 512
WEBP_LOSSLESS_METHOD: Final = 4
WEBP_LOSSLESS_QUALITY: Final = 80
MAX_DIMENSION: Final = 16_384


class SourcePixelProofError(ValueError):
    """A failure with a fixed, non-sensitive reason code."""

    __slots__ = ("reason_code",)

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


@dataclass(frozen=True, slots=True)
class TileROI:
    """A 1:1 tile as six integers: source x/y, destination x/y, shared w/h."""

    source_x: int
    source_y: int
    destination_x: int
    destination_y: int
    width: int
    height: int

    @classmethod
    def from_draw_image_numeric_args(cls, args: object) -> TileROI:
        """Normalize the eight numeric arguments of an observed 9-arg draw.

        The source and destination extents must match exactly. Booleans and
        non-integer values are rejected instead of being coerced or rounded.
        """

        if not isinstance(args, (tuple, list)) or len(args) != 8:
            raise SourcePixelProofError("draw-overload-not-nine-argument")
        if any(type(value) is not int for value in args):
            raise SourcePixelProofError("roi-coordinate-not-integer")
        source_x, source_y, source_width, source_height, destination_x, destination_y, destination_width, destination_height = args
        if source_width <= 0 or source_height <= 0:
            raise SourcePixelProofError("roi-size-invalid")
        if (source_width, source_height) != (destination_width, destination_height):
            raise SourcePixelProofError("roi-scale-unsupported")
        return cls(
            source_x=source_x,
            source_y=source_y,
            destination_x=destination_x,
            destination_y=destination_y,
            width=source_width,
            height=source_height,
        )

    def as_six_integers(self) -> tuple[int, int, int, int, int, int]:
        return (
            self.source_x,
            self.source_y,
            self.destination_x,
            self.destination_y,
            self.width,
            self.height,
        )


@dataclass(frozen=True, slots=True)
class WebPSourceInfo:
    width: int
    height: int
    encoded_length: int
    encoded_sha256: str
    first_chunk: str
    pixel_count: int


@dataclass(frozen=True, slots=True)
class DecodedWebPSource:
    """Decoded source pixels and safe metadata; encoded bytes are not retained."""

    width: int
    height: int
    rgba: bytes = field(repr=False)
    info: WebPSourceInfo


@dataclass(frozen=True, slots=True)
class ROICoverageProof:
    operation_count: int
    destination_area: int
    target_area: int
    source_rois_in_bounds: bool
    destination_coverage_complete_once: bool
    roi_geometry_sha256: str
    roi_six_integer_rows: tuple[tuple[int, int, int, int, int, int], ...]


@dataclass(frozen=True, slots=True)
class CandidatePixels:
    width: int
    height: int
    rgba: bytes = field(repr=False)
    rgba_sha256: str
    source_info: WebPSourceInfo
    roi_proof: ROICoverageProof


@dataclass(frozen=True, slots=True)
class EncodedCandidate:
    capture: CaptureResult = field(repr=False)
    output_format: str
    encoded_sha256: str
    rgba_sha256: str
    exact_roundtrip: bool
    fallback_reason_code: str | None


@dataclass(frozen=True, slots=True)
class ReferencePixels:
    width: int
    height: int
    rgba: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class PerReferenceComparison:
    max_rgb_delta_by_channel: tuple[int, int, int]
    rgb_pixels_changed: int
    rgb_pixels_over_tolerance: int
    alpha_mismatch_pixels: int
    mean_absolute_rgb_delta: float
    alpha_exact: bool
    within_tolerance: bool


@dataclass(frozen=True, slots=True)
class PixelComparisonProof:
    width: int
    height: int
    tolerance: int
    candidate_rgba_sha256: str
    reference_rgba_sha256: tuple[str, str]
    reference_pair_exact: bool
    dimensions_exact: bool
    first_reference: PerReferenceComparison
    second_reference: PerReferenceComparison
    passed: bool


def _dimensions(value: object, *, pixel_limit: int, reason: str) -> tuple[int, int]:
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise SourcePixelProofError(reason)
    width, height = value
    if (
        type(width) is not int
        or type(height) is not int
        or width <= 0
        or height <= 0
        or width > MAX_DIMENSION
        or height > MAX_DIMENSION
        or width * height > pixel_limit
    ):
        raise SourcePixelProofError(reason)
    return width, height


def _webp_riff_header(data: bytes, *, expected_chunk: bytes | None) -> str:
    if (
        type(data) is not bytes
        or len(data) < 25
        or len(data) > MAX_SOURCE_BODY_BYTES
        or data[:4] != b"RIFF"
        or struct.unpack_from("<I", data, 4)[0] != len(data) - 8
        or data[8:12] != b"WEBP"
    ):
        raise SourcePixelProofError("source-webp-container-invalid")
    chunk = data[12:16]
    if expected_chunk is not None and chunk != expected_chunk:
        raise SourcePixelProofError("source-webp-chunk-unsupported")
    chunk_length = struct.unpack_from("<I", data, 16)[0]
    if chunk_length <= 0 or 20 + chunk_length + (chunk_length & 1) > len(data):
        raise SourcePixelProofError("source-webp-chunk-invalid")
    try:
        return chunk.decode("ascii")
    except UnicodeDecodeError as exc:
        raise SourcePixelProofError("source-webp-chunk-invalid") from exc


def decode_webp_source(
    data: bytes,
    *,
    source_mime: str,
    expected_dimensions: tuple[int, int],
) -> DecodedWebPSource:
    """Validate one bounded VP8 WebP body and decode it to in-memory RGBA."""

    if type(data) is not bytes or not 1 <= len(data) <= MAX_SOURCE_BODY_BYTES:
        raise SourcePixelProofError("source-body-size-invalid")
    if not isinstance(source_mime, str) or source_mime.strip().lower() != "image/webp":
        raise SourcePixelProofError("source-mime-mismatch")
    chunk = _webp_riff_header(data, expected_chunk=b"VP8 ")
    expected_width, expected_height = _dimensions(
        expected_dimensions,
        pixel_limit=MAX_SOURCE_PIXEL_COUNT,
        reason="source-dimensions-invalid",
    )
    if not features.check("webp"):
        raise SourcePixelProofError("webp-decoder-unavailable")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if (
                image.format != "WEBP"
                or image.size != (expected_width, expected_height)
                or getattr(image, "n_frames", 1) != 1
                or getattr(image, "is_animated", False)
                or image.width * image.height > MAX_SOURCE_PIXEL_COUNT
            ):
                raise SourcePixelProofError("source-format-or-dimensions-mismatch")
            image.load()
            rgba = image.convert("RGBA").tobytes()
    except SourcePixelProofError:
        raise
    except Exception as exc:  # Pillow's decoder error text may contain private details.
        raise SourcePixelProofError("source-webp-decode-failed") from exc
    expected_length = expected_width * expected_height * 4
    if len(rgba) != expected_length:
        raise SourcePixelProofError("source-decoded-buffer-size-invalid")
    info = WebPSourceInfo(
        width=expected_width,
        height=expected_height,
        encoded_length=len(data),
        encoded_sha256=hashlib.sha256(data).hexdigest(),
        first_chunk=chunk,
        pixel_count=expected_width * expected_height,
    )
    return DecodedWebPSource(
        width=expected_width,
        height=expected_height,
        rgba=rgba,
        info=info,
    )


def validate_roi_coverage(
    *,
    source_dimensions: tuple[int, int],
    target_dimensions: tuple[int, int],
    rois: object,
) -> ROICoverageProof:
    """Prove exact 1:1 source bounds and full, once-only target coverage."""

    source_width, source_height = _dimensions(
        source_dimensions,
        pixel_limit=MAX_SOURCE_PIXEL_COUNT,
        reason="source-dimensions-invalid",
    )
    target_width, target_height = _dimensions(
        target_dimensions,
        pixel_limit=MAX_TARGET_PIXEL_COUNT,
        reason="target-dimensions-invalid",
    )
    if not isinstance(rois, (tuple, list)) or not 1 <= len(rois) <= MAX_ROI_OPERATIONS:
        raise SourcePixelProofError("roi-operation-count-invalid")

    normalized: list[TileROI] = []
    y_boundaries = {0, target_height}
    destination_area = 0
    for value in rois:
        if isinstance(value, TileROI):
            roi = value
        else:
            roi = TileROI.from_draw_image_numeric_args(value)
        if (
            any(type(number) is not int for number in roi.as_six_integers())
            or roi.source_x < 0
            or roi.source_y < 0
            or roi.destination_x < 0
            or roi.destination_y < 0
            or roi.width <= 0
            or roi.height <= 0
            or roi.source_x + roi.width > source_width
            or roi.source_y + roi.height > source_height
        ):
            raise SourcePixelProofError("roi-source-bounds-invalid")
        if (
            roi.destination_x + roi.width > target_width
            or roi.destination_y + roi.height > target_height
        ):
            raise SourcePixelProofError("roi-target-bounds-invalid")
        normalized.append(roi)
        destination_area += roi.width * roi.height
        y_boundaries.add(roi.destination_y)
        y_boundaries.add(roi.destination_y + roi.height)

    # Coordinate compression keeps validation bounded by at most 2*512 y
    # edges, regardless of the target's pixel dimensions.
    ordered_y = sorted(y_boundaries)
    for band_start, band_end in pairwise(ordered_y):
        if band_start == band_end:
            continue
        intervals = sorted(
            (roi.destination_x, roi.destination_x + roi.width)
            for roi in normalized
            if roi.destination_y <= band_start
            and roi.destination_y + roi.height >= band_end
        )
        cursor = 0
        for left, right in intervals:
            if left != cursor or right <= left:
                raise SourcePixelProofError("roi-target-coverage-invalid")
            cursor = right
        if cursor != target_width:
            raise SourcePixelProofError("roi-target-coverage-invalid")

    target_area = target_width * target_height
    if destination_area != target_area:
        raise SourcePixelProofError("roi-target-coverage-invalid")
    roi_rows = tuple(roi.as_six_integers() for roi in normalized)
    canonical = json.dumps(roi_rows, separators=(",", ":")).encode("ascii")
    return ROICoverageProof(
        operation_count=len(normalized),
        destination_area=destination_area,
        target_area=target_area,
        source_rois_in_bounds=True,
        destination_coverage_complete_once=True,
        roi_geometry_sha256=hashlib.sha256(canonical).hexdigest(),
        roi_six_integer_rows=roi_rows,
    )


def reconstruct_roi_part(
    source: DecodedWebPSource,
    *,
    target_dimensions: tuple[int, int],
    rois: object,
) -> CandidatePixels:
    """Rebuild one candidate target from the exact observed integer ROIs."""

    if not isinstance(source, DecodedWebPSource):
        raise SourcePixelProofError("decoded-source-invalid")
    source_width, source_height = _dimensions(
        (source.width, source.height),
        pixel_limit=MAX_SOURCE_PIXEL_COUNT,
        reason="source-dimensions-invalid",
    )
    expected_source_bytes = source_width * source_height * 4
    if type(source.rgba) is not bytes or len(source.rgba) != expected_source_bytes:
        raise SourcePixelProofError("source-decoded-buffer-size-invalid")
    target_width, target_height = _dimensions(
        target_dimensions,
        pixel_limit=MAX_TARGET_PIXEL_COUNT,
        reason="target-dimensions-invalid",
    )
    coverage = validate_roi_coverage(
        source_dimensions=(source_width, source_height),
        target_dimensions=(target_width, target_height),
        rois=rois,
    )
    try:
        with (
            Image.frombytes("RGBA", (source_width, source_height), source.rgba) as atlas,
            Image.new("RGBA", (target_width, target_height)) as candidate,
        ):
            for source_x, source_y, destination_x, destination_y, width, height in coverage.roi_six_integer_rows:
                with atlas.crop(
                    (source_x, source_y, source_x + width, source_y + height)
                ) as tile:
                    candidate.paste(tile, (destination_x, destination_y))
            rgba = candidate.tobytes()
    except SourcePixelProofError:
        raise
    except Exception as exc:
        raise SourcePixelProofError("roi-reconstruction-failed") from exc
    if len(rgba) != target_width * target_height * 4:
        raise SourcePixelProofError("candidate-buffer-size-invalid")
    return CandidatePixels(
        width=target_width,
        height=target_height,
        rgba=rgba,
        rgba_sha256=hashlib.sha256(rgba).hexdigest(),
        source_info=source.info,
        roi_proof=coverage,
    )


def reconstruct_webp_atlas_rgba(
    source_bytes: bytes,
    *,
    source_mime: str,
    expected_source_dimensions: tuple[int, int],
    target_dimensions: tuple[int, int],
    rois: object,
) -> CandidatePixels:
    """Convenience API for one source body and one target part."""

    source = decode_webp_source(
        source_bytes,
        source_mime=source_mime,
        expected_dimensions=expected_source_dimensions,
    )
    return reconstruct_roi_part(
        source,
        target_dimensions=target_dimensions,
        rois=rois,
    )


def _has_single_lossless_vp8l_chunk(
    data: bytes, *, width: int, height: int
) -> bool:
    if (
        len(data) < 25
        or data[:4] != b"RIFF"
        or struct.unpack_from("<I", data, 4)[0] != len(data) - 8
        or data[8:12] != b"WEBP"
        or data[12:16] != b"VP8L"
    ):
        return False
    chunk_length = struct.unpack_from("<I", data, 16)[0]
    if chunk_length < 5 or 20 + chunk_length + (chunk_length & 1) != len(data):
        return False
    if data[20] != 0x2F:
        return False
    width_minus_one = data[21] | ((data[22] & 0x3F) << 8)
    height_minus_one = (data[22] >> 6) | (data[23] << 2) | ((data[24] & 0x0F) << 10)
    version = (data[24] >> 5) & 0x07
    return width_minus_one + 1 == width and height_minus_one + 1 == height and version == 0


def _encode_png_exact(candidate: CandidatePixels, *, fallback_reason: str) -> EncodedCandidate:
    try:
        with Image.frombytes("RGBA", (candidate.width, candidate.height), candidate.rgba) as image:
            output = io.BytesIO()
            image.save(output, format="PNG", optimize=False)
        data = output.getvalue()
        with Image.open(io.BytesIO(data)) as decoded:
            if decoded.format != "PNG" or decoded.size != (candidate.width, candidate.height):
                raise SourcePixelProofError("png-roundtrip-invalid")
            decoded.load()
            exact = decoded.convert("RGBA").tobytes() == candidate.rgba
        if not exact:
            raise SourcePixelProofError("png-roundtrip-mismatch")
    except SourcePixelProofError:
        raise
    except Exception as exc:
        raise SourcePixelProofError("png-encode-failed") from exc
    capture = CaptureResult(
        data=data,
        width=candidate.width,
        height=candidate.height,
        mime_type="image/png",
        file_extension=".png",
    )
    return EncodedCandidate(
        capture=capture,
        output_format="png",
        encoded_sha256=hashlib.sha256(data).hexdigest(),
        rgba_sha256=candidate.rgba_sha256,
        exact_roundtrip=True,
        fallback_reason_code=fallback_reason,
    )


def _candidate_rgba_is_self_consistent(candidate: CandidatePixels) -> bool:
    if (
        type(candidate.width) is not int
        or type(candidate.height) is not int
        or candidate.width <= 0
        or candidate.height <= 0
        or candidate.width > MAX_DIMENSION
        or candidate.height > MAX_DIMENSION
        or candidate.width * candidate.height > MAX_TARGET_PIXEL_COUNT
        or type(candidate.rgba) is not bytes
        or len(candidate.rgba) != candidate.width * candidate.height * 4
    ):
        return False
    return candidate.rgba_sha256 == hashlib.sha256(candidate.rgba).hexdigest()


def encode_lossless_candidate(candidate: CandidatePixels) -> EncodedCandidate:
    """Emit exact lossless WebP; use PNG only if WebP encoding cannot prove exactness."""

    if not isinstance(candidate, CandidatePixels):
        raise SourcePixelProofError("candidate-invalid")
    if not _candidate_rgba_is_self_consistent(candidate):
        raise SourcePixelProofError("candidate-buffer-size-invalid")
    if not features.check("webp"):
        return _encode_png_exact(candidate, fallback_reason="lossless-webp-unavailable")
    try:
        with Image.frombytes("RGBA", (candidate.width, candidate.height), candidate.rgba) as image:
            output = io.BytesIO()
            image.save(
                output,
                format="WEBP",
                lossless=True,
                method=WEBP_LOSSLESS_METHOD,
                quality=WEBP_LOSSLESS_QUALITY,
                exact=True,
            )
        data = output.getvalue()
        if not _has_single_lossless_vp8l_chunk(
            data, width=candidate.width, height=candidate.height
        ):
            return _encode_png_exact(candidate, fallback_reason="lossless-webp-output-unverified")
        with Image.open(io.BytesIO(data)) as decoded:
            if decoded.format != "WEBP" or decoded.size != (candidate.width, candidate.height):
                return _encode_png_exact(candidate, fallback_reason="lossless-webp-output-unverified")
            decoded.load()
            exact = decoded.convert("RGBA").tobytes() == candidate.rgba
        if not exact:
            return _encode_png_exact(candidate, fallback_reason="lossless-webp-roundtrip-mismatch")
    except (OSError, ValueError, RuntimeError):  # Error strings may contain private details.
        return _encode_png_exact(candidate, fallback_reason="lossless-webp-encode-failed")
    capture = CaptureResult(
        data=data,
        width=candidate.width,
        height=candidate.height,
        mime_type="image/webp",
        file_extension=".webp",
    )
    return EncodedCandidate(
        capture=capture,
        output_format="webp",
        encoded_sha256=hashlib.sha256(data).hexdigest(),
        rgba_sha256=candidate.rgba_sha256,
        exact_roundtrip=True,
        fallback_reason_code=None,
    )


def _pixel_difference(
    candidate: bytes,
    reference: bytes,
    *,
    width: int,
    height: int,
    tolerance: int,
) -> PerReferenceComparison:
    try:
        with (
            Image.frombytes("RGBA", (width, height), candidate) as candidate_image,
            Image.frombytes("RGBA", (width, height), reference) as reference_image,
        ):
            difference = ImageChops.difference(candidate_image, reference_image)
            red, green, blue, alpha = difference.split()
            channels = (red, green, blue)
            max_deltas = tuple(channel.getextrema()[1] for channel in channels)
            changed_rgb = ImageChops.lighter(ImageChops.lighter(red, green), blue)
            changed_pixels = sum(changed_rgb.histogram()[1:])
            over_mask = changed_rgb.point(
                [0 if value <= tolerance else 255 for value in range(256)]
            )
            over_pixels = over_mask.histogram()[255]
            alpha_mismatches = sum(alpha.histogram()[1:])
            mean_delta = sum(ImageStat.Stat(channel).mean[0] for channel in channels) / 3
            alpha_exact = alpha.getextrema() == (0, 0)
            return PerReferenceComparison(
                max_rgb_delta_by_channel=max_deltas,  # type: ignore[arg-type]
                rgb_pixels_changed=changed_pixels,
                rgb_pixels_over_tolerance=over_pixels,
                alpha_mismatch_pixels=alpha_mismatches,
                mean_absolute_rgb_delta=float(mean_delta),
                alpha_exact=alpha_exact,
                within_tolerance=max(max_deltas) <= tolerance,
            )
    except Exception as exc:
        raise SourcePixelProofError("pixel-comparison-failed") from exc


def compare_candidate_rgba(
    candidate: CandidatePixels,
    first_reference: ReferencePixels,
    second_reference: ReferencePixels,
    *,
    tolerance: int = 2,
) -> PixelComparisonProof:
    """Compare one candidate to two exact-pair D references, per RGB channel."""

    if type(tolerance) is not int or tolerance < 0 or tolerance > 2:
        raise SourcePixelProofError("rgb-tolerance-invalid")
    if not isinstance(candidate, CandidatePixels):
        raise SourcePixelProofError("candidate-invalid")
    buffers = (first_reference, second_reference)
    if any(not isinstance(value, ReferencePixels) for value in buffers):
        raise SourcePixelProofError("reference-invalid")
    if not _candidate_rgba_is_self_consistent(candidate):
        raise SourcePixelProofError("candidate-buffer-size-invalid")
    if any(
        type(reference.width) is not int
        or type(reference.height) is not int
        or (reference.width, reference.height) != (candidate.width, candidate.height)
        or type(reference.rgba) is not bytes
        or len(reference.rgba) != candidate.width * candidate.height * 4
        for reference in buffers
    ):
        raise SourcePixelProofError("reference-dimensions-or-buffer-invalid")
    first = _pixel_difference(
        candidate.rgba,
        first_reference.rgba,
        width=candidate.width,
        height=candidate.height,
        tolerance=tolerance,
    )
    second = _pixel_difference(
        candidate.rgba,
        second_reference.rgba,
        width=candidate.width,
        height=candidate.height,
        tolerance=tolerance,
    )
    # Compare all four bands. RGBA Image.getbbox() is not safe here because a
    # zero alpha difference can hide unequal RGB channel data.
    reference_pair_exact = True
    try:
        with (
            Image.frombytes(
                "RGBA", (candidate.width, candidate.height), first_reference.rgba
            ) as first_image,
            Image.frombytes(
                "RGBA", (candidate.width, candidate.height), second_reference.rgba
            ) as second_image,
        ):
            pair_difference = ImageChops.difference(first_image, second_image)
            reference_pair_exact = all(
                channel.getextrema() == (0, 0) for channel in pair_difference.split()
            )
    except Exception as exc:
        raise SourcePixelProofError("reference-pair-comparison-failed") from exc
    passed = (
        reference_pair_exact
        and first.alpha_exact
        and second.alpha_exact
        and first.within_tolerance
        and second.within_tolerance
    )
    return PixelComparisonProof(
        width=candidate.width,
        height=candidate.height,
        tolerance=tolerance,
        candidate_rgba_sha256=candidate.rgba_sha256,
        reference_rgba_sha256=(
            hashlib.sha256(first_reference.rgba).hexdigest(),
            hashlib.sha256(second_reference.rgba).hexdigest(),
        ),
        reference_pair_exact=reference_pair_exact,
        dimensions_exact=True,
        first_reference=first,
        second_reference=second,
        passed=passed,
    )
