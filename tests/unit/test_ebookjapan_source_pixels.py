from __future__ import annotations

import hashlib
import io
from dataclasses import replace

import pytest
from PIL import Image

from screenshot_crawler.core.capture import CaptureResult
from screenshot_crawler.site_adapters.ebookjapan.source_pixels import (
    MAX_ROI_OPERATIONS,
    MAX_SOURCE_BODY_BYTES,
    CandidatePixels,
    DecodedWebPSource,
    EncodedCandidate,
    ReferencePixels,
    SourcePixelProofError,
    TileROI,
    WebPSourceInfo,
    compare_candidate_rgba,
    decode_webp_source,
    encode_lossless_candidate,
    reconstruct_roi_part,
    reconstruct_webp_atlas_rgba,
    validate_roi_coverage,
)


def _webp(width: int = 8, height: int = 6) -> bytes:
    image = Image.new("RGB", (width, height))
    image.putdata(
        [
            ((x * 31 + y * 17) % 256, (x * 13 + y * 43) % 256, (x * 53 + y * 7) % 256)
            for y in range(height)
            for x in range(width)
        ]
    )
    output = io.BytesIO()
    image.save(output, format="WEBP", lossless=False, quality=92, method=4)
    image.close()
    return output.getvalue()


def _rois() -> tuple[TileROI, TileROI]:
    return (
        TileROI(0, 0, 0, 0, 2, 3),
        TileROI(4, 0, 2, 0, 2, 3),
    )


def _candidate() -> CandidatePixels:
    return reconstruct_webp_atlas_rgba(
        _webp(),
        source_mime="image/webp",
        expected_source_dimensions=(8, 6),
        target_dimensions=(4, 3),
        rois=_rois(),
    )


def test_reconstructs_exact_observed_rois_and_records_complete_six_integer_geometry() -> None:
    source_bytes = _webp()
    candidate = reconstruct_webp_atlas_rgba(
        source_bytes,
        source_mime="image/webp",
        expected_source_dimensions=(8, 6),
        target_dimensions=(4, 3),
        rois=_rois(),
    )

    with Image.open(io.BytesIO(source_bytes)) as source:
        source_rgba = source.convert("RGBA")
        expected = Image.new("RGBA", (4, 3))
        expected.paste(source_rgba.crop((0, 0, 2, 3)), (0, 0))
        expected.paste(source_rgba.crop((4, 0, 6, 3)), (2, 0))
        assert candidate.rgba == expected.tobytes()
        expected.close()
        source_rgba.close()

    assert candidate.source_info.first_chunk == "VP8 "
    assert candidate.source_info.encoded_length == len(source_bytes)
    assert candidate.roi_proof.operation_count == 2
    assert candidate.roi_proof.destination_area == candidate.roi_proof.target_area == 12
    assert candidate.roi_proof.source_rois_in_bounds is True
    assert candidate.roi_proof.destination_coverage_complete_once is True
    assert candidate.roi_proof.roi_six_integer_rows == ((0, 0, 0, 0, 2, 3), (4, 0, 2, 0, 2, 3))
    assert len(candidate.roi_proof.roi_geometry_sha256) == 64


def test_pixel_and_encoded_buffers_are_not_exposed_by_dataclass_repr() -> None:
    secret = b"private-pixel-buffer-sentinel"
    info = WebPSourceInfo(
        width=1,
        height=1,
        encoded_length=1,
        encoded_sha256="0" * 64,
        first_chunk="VP8 ",
        pixel_count=1,
    )
    source = DecodedWebPSource(1, 1, secret, info)
    candidate = CandidatePixels(
        width=1,
        height=1,
        rgba=secret,
        rgba_sha256="1" * 64,
        source_info=info,
        roi_proof=validate_roi_coverage(
            source_dimensions=(1, 1),
            target_dimensions=(1, 1),
            rois=(TileROI(0, 0, 0, 0, 1, 1),),
        ),
    )
    reference = ReferencePixels(1, 1, secret)
    encoded = EncodedCandidate(
        capture=CaptureResult(secret, width=1, height=1),
        output_format="png",
        encoded_sha256="2" * 64,
        rgba_sha256="1" * 64,
        exact_roundtrip=True,
        fallback_reason_code=None,
    )
    for value in (source, candidate, reference, encoded):
        assert secret.decode("ascii") not in repr(value)


@pytest.mark.parametrize(
    ("args", "reason"),
    [
        ((0, 0, True, 3, 0, 0, 1, 3), "roi-coordinate-not-integer"),
        ((0, 0, 2.0, 3, 0, 0, 2, 3), "roi-coordinate-not-integer"),
        ((0, 0, 2, 3, 0, 0, 1, 3), "roi-scale-unsupported"),
        ((0, 0, 0, 3, 0, 0, 0, 3), "roi-size-invalid"),
    ],
)
def test_draw_normalization_rejects_coercion_scaling_and_empty_rects(args, reason: str) -> None:
    with pytest.raises(SourcePixelProofError) as exc_info:
        TileROI.from_draw_image_numeric_args(args)
    assert exc_info.value.reason_code == reason


def test_roi_coverage_rejects_gaps_overlaps_and_out_of_bounds_rectangles() -> None:
    with pytest.raises(SourcePixelProofError, match="roi-target-coverage-invalid"):
        validate_roi_coverage(
            source_dimensions=(8, 6),
            target_dimensions=(4, 3),
            rois=(TileROI(0, 0, 0, 0, 1, 3), TileROI(4, 0, 2, 0, 2, 3)),
        )
    with pytest.raises(SourcePixelProofError, match="roi-target-coverage-invalid"):
        validate_roi_coverage(
            source_dimensions=(8, 6),
            target_dimensions=(4, 3),
            rois=(TileROI(0, 0, 0, 0, 3, 3), TileROI(4, 0, 2, 0, 2, 3)),
        )
    with pytest.raises(SourcePixelProofError, match="roi-source-bounds-invalid"):
        validate_roi_coverage(
            source_dimensions=(8, 6),
            target_dimensions=(4, 3),
            rois=(TileROI(7, 0, 0, 0, 2, 3), TileROI(4, 0, 2, 0, 2, 3)),
        )
    with pytest.raises(SourcePixelProofError, match="roi-target-bounds-invalid"):
        validate_roi_coverage(
            source_dimensions=(8, 6),
            target_dimensions=(4, 3),
            rois=(TileROI(0, 0, 3, 0, 2, 3), TileROI(4, 0, 2, 0, 2, 3)),
        )


def test_roi_coverage_rejects_bool_fields_and_operation_cap() -> None:
    with pytest.raises(SourcePixelProofError, match="roi-source-bounds-invalid"):
        validate_roi_coverage(
            source_dimensions=(8, 6),
            target_dimensions=(4, 3),
            rois=(TileROI(True, 0, 0, 0, 2, 3), TileROI(4, 0, 2, 0, 2, 3)),
        )
    too_many = tuple(TileROI(0, 0, 0, 0, 2, 3) for _ in range(MAX_ROI_OPERATIONS + 1))
    with pytest.raises(SourcePixelProofError, match="roi-operation-count-invalid"):
        validate_roi_coverage(
            source_dimensions=(8, 6),
            target_dimensions=(4, 3),
            rois=too_many,
        )


def test_source_webp_validation_rejects_unverified_format_length_and_dimensions() -> None:
    data = _webp()
    invalid_cases = (
        ("image/png", (8, 6), data, "source-mime-mismatch"),
        ("image/webp", (7, 6), data, "source-format-or-dimensions-mismatch"),
        ("image/webp", (True, 6), data, "source-dimensions-invalid"),
        ("image/webp", (8, 6), b"not an image", "source-webp-container-invalid"),
        (
            "image/webp",
            (8, 6),
            b"x" * (MAX_SOURCE_BODY_BYTES + 1),
            "source-body-size-invalid",
        ),
    )
    for mime, dimensions, body, reason in invalid_cases:
        with pytest.raises(SourcePixelProofError, match=reason):
            decode_webp_source(body, source_mime=mime, expected_dimensions=dimensions)


def test_lossless_webp_output_is_vp8l_and_exact() -> None:
    candidate = _candidate()

    encoded = encode_lossless_candidate(candidate)

    assert encoded.output_format == "webp"
    assert (encoded.capture.mime_type, encoded.capture.file_extension) == ("image/webp", ".webp")
    assert encoded.capture.data[12:16] == b"VP8L"
    assert encoded.exact_roundtrip is True
    assert encoded.fallback_reason_code is None
    with Image.open(io.BytesIO(encoded.capture.data)) as decoded:
        assert decoded.convert("RGBA").tobytes() == candidate.rgba


def test_png_is_only_an_exact_fallback_when_webp_codec_is_unavailable(monkeypatch) -> None:
    from screenshot_crawler.site_adapters.ebookjapan import source_pixels

    candidate = _candidate()
    monkeypatch.setattr(source_pixels.features, "check", lambda name: False)
    encoded = encode_lossless_candidate(candidate)

    assert encoded.output_format == "png"
    assert (encoded.capture.mime_type, encoded.capture.file_extension) == ("image/png", ".png")
    assert encoded.exact_roundtrip is True
    assert encoded.fallback_reason_code == "lossless-webp-unavailable"


def test_rgb_tolerance_is_per_channel_and_alpha_remains_exact() -> None:
    candidate = _candidate()
    reference = ReferencePixels(candidate.width, candidate.height, candidate.rgba)
    accepted_rgba = bytearray(candidate.rgba)
    accepted_rgba[0:3] = bytes((accepted_rgba[0] + 2, accepted_rgba[1] + 2, accepted_rgba[2] + 2))
    accepted = replace(
        candidate,
        rgba=bytes(accepted_rgba),
        rgba_sha256=hashlib.sha256(accepted_rgba).hexdigest(),
    )

    proof = compare_candidate_rgba(accepted, reference, reference)

    assert proof.passed is True
    assert proof.first_reference.max_rgb_delta_by_channel == (2, 2, 2)
    assert proof.first_reference.rgb_pixels_changed == 1
    assert proof.first_reference.rgb_pixels_over_tolerance == 0
    assert proof.first_reference.alpha_mismatch_pixels == 0
    rejected_rgba = bytearray(candidate.rgba)
    rejected_rgba[0] += 3
    rejected = replace(
        candidate,
        rgba=bytes(rejected_rgba),
        rgba_sha256=hashlib.sha256(rejected_rgba).hexdigest(),
    )
    assert compare_candidate_rgba(rejected, reference, reference).passed is False


def test_comparison_sees_rgb_differences_under_zero_alpha_and_rejects_alpha_change() -> None:
    pixels = CandidatePixels(
        width=1,
        height=1,
        rgba=bytes((101, 100, 100, 0)),
        rgba_sha256=hashlib.sha256(bytes((101, 100, 100, 0))).hexdigest(),
        source_info=_candidate().source_info,
        roi_proof=_candidate().roi_proof,
    )
    ref = ReferencePixels(width=1, height=1, rgba=bytes((100, 100, 100, 0)))
    proof = compare_candidate_rgba(pixels, ref, ref)
    assert proof.first_reference.rgb_pixels_changed == 1
    assert proof.first_reference.max_rgb_delta_by_channel == (1, 0, 0)
    assert proof.first_reference.alpha_exact is True

    changed_rgba = bytes((100, 100, 100, 1))
    alpha_changed = replace(
        pixels,
        rgba=changed_rgba,
        rgba_sha256=hashlib.sha256(changed_rgba).hexdigest(),
    )
    assert compare_candidate_rgba(alpha_changed, ref, ref).passed is False


def test_compare_and_encode_reject_stale_candidate_hash_claim() -> None:
    candidate = _candidate()
    forged = replace(candidate, rgba_sha256="0" * 64)
    reference = ReferencePixels(candidate.width, candidate.height, candidate.rgba)

    with pytest.raises(SourcePixelProofError, match="candidate-buffer-size-invalid"):
        compare_candidate_rgba(forged, reference, reference)
    with pytest.raises(SourcePixelProofError, match="candidate-buffer-size-invalid"):
        encode_lossless_candidate(forged)


def test_comparison_requires_the_two_d_references_to_match_exactly() -> None:
    candidate = _candidate()
    reference_a = ReferencePixels(candidate.width, candidate.height, candidate.rgba)
    reference_b_rgba = bytearray(candidate.rgba)
    reference_b_rgba[0] += 1
    reference_b = ReferencePixels(candidate.width, candidate.height, bytes(reference_b_rgba))

    proof = compare_candidate_rgba(candidate, reference_a, reference_b)

    assert proof.first_reference.within_tolerance is True
    assert proof.second_reference.within_tolerance is True
    assert proof.reference_pair_exact is False
    assert proof.passed is False


def test_same_decoded_source_can_reconstruct_parts_without_retaining_encoded_bytes() -> None:
    data = _webp()
    source = decode_webp_source(
        data,
        source_mime="image/webp",
        expected_dimensions=(8, 6),
    )
    candidate = reconstruct_roi_part(source, target_dimensions=(4, 3), rois=_rois())

    assert source.info.encoded_sha256
    assert not hasattr(source, "encoded_bytes")
    assert candidate.source_info is source.info
