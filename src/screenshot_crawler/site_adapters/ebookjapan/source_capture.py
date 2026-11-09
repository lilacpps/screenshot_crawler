"""Private, bounded source ROI comparison used by conditional EbookJapan C capture.

The adapter accepts C only after complete per-part lineage and pixel proof;
otherwise it uses a fresh D spread. URLs, Playwright objects, and source bytes
exist only in the per-run in-memory ledger and are omitted from safe projections.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Final, Literal
from urllib.parse import urlsplit

from playwright.async_api import Response

from screenshot_crawler.core.capture import CaptureResult
from screenshot_crawler.site_adapters.ebookjapan.source_observer import (
    MAX_RESPONSE_BODY_BYTES,
    BoundSourceResponse,
    LoadedSourceBody,
    RequestResponseObservation,
    SourceObserverProofError,
    bind_unique_current_response,
    read_bound_response_body_once,
)
from screenshot_crawler.site_adapters.ebookjapan.source_pixels import (
    RGB_OUTLIER_LIMIT_DENOMINATOR,
    CandidatePixels,
    EncodedCandidate,
    PixelComparisonProof,
    ReferencePixels,
    SourcePixelProofError,
    compare_candidate_rgba,
    decode_webp_source,
    reconstruct_roi_part,
)

MAX_TRACKED_IMAGE_REQUESTS: Final = 4096
MAX_SOURCE_RESPONSE_CANDIDATES: Final = 4
SOURCE_CANDIDATE_POLICY_REVISION: Final = "ebookjapan-response-candidates-v1-20261110"
SOURCE_IMAGE_HOSTS: Final = frozenset(
    {
        "cache2-ebookjapan.akamaized.net",
        "ebookjapan.akamaized.net",
        "prod-contents-br-page.akamaized.net",
    }
)
LIMITED_HISTORY_PROFILE: Final = "muda2-install-unknown-callable-v3"
SOURCE_METHOD: Final = "C_source_roi_lossless"
SOURCE_POLICY_REVISION: Final = "ebookjapan-owned-source-roi-v2-20261109"

ComparisonStatus = Literal["C_VERIFIED", "D_FALLBACK"]


class SourceCaptureProofError(ValueError):
    """A fixed-code expected source proof failure."""

    __slots__ = ("reason_code",)

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


@dataclass(slots=True)
class _TrackedRequest:
    request_object: object = field(repr=False)
    request_url: str = field(repr=False)
    request_document_token: object = field(repr=False)
    request_id: int
    response_object: object = field(default=None, repr=False)
    response_request_object: object = field(default=None, repr=False)
    response_document_token: object = field(default=None, repr=False)
    response_id: int | None = None
    status: int | None = None
    redirected: bool | None = None
    mime_type: str | None = None
    declared_length: int | None = None
    response_count: int = 0
    body_read: bool = False


@dataclass(frozen=True, slots=True)
class BoundResponseFacts:
    request_id: int
    response_id: int
    document_id: int
    status: int
    mime_type: str
    encoded_length: int
    redirected: bool
    request_response_identity_matches: bool
    current_document_matches: bool
    current_src_matches: bool
    candidate_count: int = 1
    verified_candidate_count: int = 1
    selection_status: str = "unique_request"


@dataclass(frozen=True, slots=True)
class SourceResponseCohort:
    """Frozen same-URL request cohort; bodies exist only during this capture."""

    entries: tuple[tuple[BoundSourceResponse, BoundResponseFacts, LoadedSourceBody], ...] = field(repr=False)

    def validate(self, ledger: SourceRequestLedger, current_src: str) -> None:
        request_ids = tuple(facts.request_id for _, facts, _ in self.entries)
        for binding, facts, _ in self.entries:
            ledger.validate_held_binding(
                current_src,
                request_id=facts.request_id,
                response_id=facts.response_id,
                request_object=binding.request_object,
                response_object=binding.response_object,
                document_token=binding.document_token,
                candidate_request_ids=request_ids,
            )


def select_source_roi_candidate(
    cohort: SourceResponseCohort,
    *,
    expected_dimensions: tuple[int, int],
    target_dimensions: tuple[object, object],
    rois: object,
    first_reference: ReferencePixels,
    second_reference: ReferencePixels,
) -> tuple[CandidatePixels, PixelComparisonProof, BoundResponseFacts]:
    """Verify every distinct body; multiple passing outputs must be byte-exact RGBA.

    URL/timing/order never chooses a differing candidate. This proves a source
    ROI-derived output, not which equivalent HTTP event supplied the Image.
    """

    selected: tuple[CandidatePixels, PixelComparisonProof, BoundResponseFacts] | None = None
    verified_count = 0
    seen: dict[bytes, bool] = {}
    for _binding, facts, loaded in cohort.entries:
        if loaded.data in seen:
            verified_count += int(seen[loaded.data])
            continue
        try:
            decoded = decode_webp_source(
                loaded.data, source_mime=loaded.mime_type,
                expected_dimensions=expected_dimensions,
            )
            candidate = reconstruct_roi_part(decoded, target_dimensions=target_dimensions, rois=rois)
            comparison = compare_candidate_rgba(candidate, first_reference, second_reference, tolerance=2)
        except SourcePixelProofError:
            if len(cohort.entries) == 1:
                raise
            seen[loaded.data] = False
            continue
        # Keep historical single-response diagnostics, including a failed comparison.
        if len(cohort.entries) == 1:
            return candidate, comparison, facts
        seen[loaded.data] = comparison.passed
        if not comparison.passed:
            continue
        verified_count += 1
        if selected is None:
            selected = candidate, comparison, facts
        elif candidate.rgba != selected[0].rgba:
            raise SourceCaptureProofError("source-candidate-output-ambiguous")
    if selected is None:
        raise SourceCaptureProofError("source-pixel-equivalence-failed")
    candidate, comparison, facts = selected
    return candidate, comparison, replace(
        facts,
        candidate_count=len(cohort.entries),
        verified_candidate_count=verified_count,
        selection_status=(
            "unique_verified_candidate" if verified_count == 1
            else "equivalent_bytes" if len(seen) == 1
            else "equivalent_verified_pixels"
        ),
    )


class SourceRequestLedger:
    """Retain a bounded same-Page image request/response cohort in RAM."""

    __slots__ = (
        "_access_stop_status",
        "_document_id",
        "_document_token",
        "_next_request_id",
        "_next_response_id",
        "_overflowed",
        "_pending_main_navigation",
        "_request_by_identity",
        "_requests",
    )

    def __init__(self) -> None:
        self._requests: deque[_TrackedRequest] = deque()
        self._request_by_identity: dict[int, _TrackedRequest] = {}
        self._document_token: object = object()
        self._document_id = 1
        self._next_request_id = 0
        self._next_response_id = 0
        self._pending_main_navigation = False
        self._overflowed = False
        self._access_stop_status: int | None = None

    @property
    def document_token(self) -> object:
        return self._document_token

    @property
    def document_id(self) -> int:
        return self._document_id

    @property
    def pending_main_navigation(self) -> bool:
        return self._pending_main_navigation

    @property
    def overflowed(self) -> bool:
        return self._overflowed

    @property
    def access_stop_status(self) -> int | None:
        return self._access_stop_status

    @staticmethod
    def _reader_url_allowed(value: object) -> bool:
        if not isinstance(value, str):
            return False
        parsed = urlsplit(value)
        return (
            parsed.scheme == "https"
            and parsed.hostname == "ebookjapan.yahoo.co.jp"
            and _PURCHASED_READER_PATH.fullmatch(parsed.path) is not None
            and not parsed.query
            and not parsed.fragment
        )

    @staticmethod
    def _source_image_url_allowed(value: object) -> bool:
        if not isinstance(value, str):
            return False
        parsed = urlsplit(value)
        return parsed.scheme == "https" and parsed.hostname in SOURCE_IMAGE_HOSTS

    def request_started(
        self,
        request: object,
        *,
        main_frame: object,
        reader_url: object,
    ) -> None:
        try:
            frame = request.frame
            is_navigation = request.is_navigation_request()
        except Exception:  # noqa: BLE001 - a detached Playwright request is UNKNOWN.
            return
        if frame is main_frame and is_navigation:
            self._pending_main_navigation = True
            return
        if (
            self._pending_main_navigation
            or frame is not main_frame
            or not self._reader_url_allowed(reader_url)
        ):
            return
        try:
            resource_type = request.resource_type
            request_url = request.url
        except Exception:  # noqa: BLE001 - a detached Playwright request is UNKNOWN.
            return
        if resource_type != "image" or not self._source_image_url_allowed(request_url):
            return
        if len(self._requests) >= MAX_TRACKED_IMAGE_REQUESTS:
            self._overflowed = True
            return
        self._next_request_id += 1
        tracked = _TrackedRequest(
            request_object=request,
            request_url=request_url,
            request_document_token=self._document_token,
            request_id=self._next_request_id,
        )
        self._requests.append(tracked)
        self._request_by_identity[id(request)] = tracked

    def main_frame_committed(self, frame: object, *, main_frame: object) -> None:
        if frame is not main_frame:
            return
        # Completed observations from the old document cannot bind the new
        # currentSrc. Keep only old in-flight requests so a later response from
        # one of them makes a same-URL binding fail closed.
        retained = deque(item for item in self._requests if item.response_object is None)
        self._requests = retained
        self._request_by_identity = {
            id(item.request_object): item for item in retained
        }
        self._document_token = object()
        self._document_id += 1
        self._pending_main_navigation = False

    def response_received(self, response: Response, *, main_frame: object) -> None:
        try:
            request = response.request
        except Exception:  # noqa: BLE001 - a disposed response is UNKNOWN.
            return
        tracked = self._request_by_identity.get(id(request))
        if tracked is None or tracked.request_object is not request:
            return
        if tracked.response_object is not None:
            # Preserve an explicit duplicate response event as ambiguity.
            try:
                duplicate_status = response.status
            except Exception:  # noqa: BLE001 - disposed duplicate responses remain UNKNOWN.
                duplicate_status = None
            if type(duplicate_status) is int and duplicate_status in (403, 429):
                self._access_stop_status = duplicate_status
            tracked.response_count += 1
            self._next_response_id += 1
            tracked.response_id = self._next_response_id
            tracked.response_request_object = request
            tracked.response_document_token = self._document_token
            return
        try:
            response_frame = response.frame
            status = response.status
            headers = response.headers
            redirected = request.redirected_from is not None
            mime_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
            length_text = headers.get("content-length", "")
            declared_length = int(length_text) if length_text.isdigit() else -1
        except Exception:  # noqa: BLE001 - malformed response metadata is UNKNOWN.
            return
        if status in (403, 429):
            self._access_stop_status = status
        if response_frame is not main_frame:
            return
        self._next_response_id += 1
        tracked.response_count = 1
        tracked.response_object = response
        tracked.response_request_object = request
        tracked.response_document_token = self._document_token
        tracked.response_id = self._next_response_id
        tracked.status = status if type(status) is int else -1
        tracked.redirected = bool(redirected)
        tracked.mime_type = mime_type
        tracked.declared_length = declared_length

    def bind_current_src(self, current_src: str) -> tuple[BoundSourceResponse, BoundResponseFacts]:
        """Legacy strict single-response binding; capture uses the bounded cohort API."""
        candidates = self.bind_current_src_candidates(current_src)
        if len(candidates) != 1:
            raise SourceObserverProofError("source-request-ambiguous")
        return candidates[0]

    def bind_current_src_candidates(
        self, current_src: str,
    ) -> tuple[tuple[BoundSourceResponse, BoundResponseFacts], ...]:
        if self._access_stop_status in (403, 429):
            raise SourceObserverProofError("source-access-stop")
        if self._overflowed:
            raise SourceObserverProofError("source-response-tracker-overflow")
        if self._pending_main_navigation:
            raise SourceObserverProofError("source-document-navigation-pending")
        if not self._source_image_url_allowed(current_src):
            raise SourceObserverProofError("source-current-src-host-unobserved")
        matching_requests = [
            tracked for tracked in self._requests if tracked.request_url == current_src
        ]
        if not matching_requests:
            raise SourceObserverProofError("source-request-unmatched")
        if len(matching_requests) > MAX_SOURCE_RESPONSE_CANDIDATES:
            raise SourceObserverProofError("source-candidate-limit-exceeded")
        # Old in-flight requests are intentionally retained across navigation;
        # never silently filter them out to make the current cohort look unique.
        if any(item.request_document_token is not self._document_token for item in matching_requests):
            raise SourceObserverProofError("source-request-ambiguous")
        return tuple(self._bind_tracked(tracked, current_src) for tracked in matching_requests)

    def _bind_tracked(
        self, tracked: _TrackedRequest, current_src: str,
    ) -> tuple[BoundSourceResponse, BoundResponseFacts]:
        if tracked.response_object is None:
            raise SourceObserverProofError("source-response-not-loaded")
        if tracked.response_id is None or tracked.status is None or tracked.redirected is None:
            raise SourceObserverProofError("source-response-observation-incomplete")
        if tracked.response_count != 1:
            raise SourceObserverProofError("source-response-ambiguous")
        if tracked.body_read:
            raise SourceObserverProofError("source-response-body-already-read")
        if tracked.status in (403, 429):
            raise SourceObserverProofError("source-access-stop")
        observation = RequestResponseObservation(
            request_object=tracked.request_object,
            response_object=tracked.response_object,
            response_request_object=tracked.response_request_object,
            request_document_token=tracked.request_document_token,
            response_document_token=tracked.response_document_token,
            request_url=tracked.request_url,
            status=tracked.status,
            redirected=tracked.redirected,
            mime_type=tracked.mime_type or "",
            declared_length=tracked.declared_length
            if tracked.declared_length is not None
            else -1,
        )
        binding = bind_unique_current_response(
            current_src,
            current_document_token=self._document_token,
            observations=(observation,),
        )
        facts = BoundResponseFacts(
            request_id=tracked.request_id,
            response_id=tracked.response_id,
            document_id=self._document_id,
            status=binding.status,
            mime_type=binding.mime_type,
            encoded_length=binding.declared_length,
            redirected=tracked.redirected,
            request_response_identity_matches=(
                tracked.response_request_object is tracked.request_object
            ),
            current_document_matches=(
                tracked.request_document_token is self._document_token
                and tracked.response_document_token is self._document_token
            ),
            current_src_matches=(tracked.request_url == current_src),
        )
        return binding, facts

    async def load_current_src_candidates(self, current_src: str) -> SourceResponseCohort:
        candidates = self.bind_current_src_candidates(current_src)
        # Total encoded memory and body-wait budget are per URL cohort, not
        # multiplied by the number of duplicate requests. No additional fetch.
        if sum(binding.declared_length for binding, _ in candidates) > MAX_RESPONSE_BODY_BYTES:
            raise SourceObserverProofError("source-candidate-byte-limit-exceeded")
        entries = []
        try:
            async with asyncio.timeout(5.0):
                for binding, facts in candidates:
                    self.mark_body_attempted(facts.request_id)
                    loaded = await read_bound_response_body_once(binding, timeout_seconds=5.0)
                    entries.append((binding, facts, loaded))
        except TimeoutError:
            raise SourceObserverProofError("source-response-body-timeout") from None
        cohort = SourceResponseCohort(tuple(entries))
        cohort.validate(self, current_src)
        return cohort

    def mark_body_attempted(self, request_id: int) -> None:
        for tracked in self._requests:
            if tracked.request_id == request_id:
                if tracked.body_read:
                    raise SourceObserverProofError("source-response-body-already-read")
                tracked.body_read = True
                return
        raise SourceObserverProofError("source-response-observation-evicted")

    def validate_held_binding(
        self,
        current_src: str,
        *,
        request_id: int,
        response_id: int,
        request_object: object,
        response_object: object,
        document_token: object,
        candidate_request_ids: tuple[int, ...] | None = None,
    ) -> BoundResponseFacts:
        """Recheck the frozen request cohort and held identities after awaits."""

        if self._access_stop_status in (403, 429):
            raise SourceObserverProofError("source-access-stop")
        if self._overflowed:
            raise SourceObserverProofError("source-response-tracker-overflow")
        if self._pending_main_navigation:
            raise SourceObserverProofError("source-document-navigation-pending")
        if not self._source_image_url_allowed(current_src):
            raise SourceObserverProofError("source-current-src-host-unobserved")
        matching = [item for item in self._requests if item.request_url == current_src]
        if (
            candidate_request_ids is None and len(matching) != 1
            or candidate_request_ids is not None
            and tuple(item.request_id for item in matching) != candidate_request_ids
        ):
            raise SourceObserverProofError(
                "source-response-unmatched" if not matching else "source-response-ambiguous"
            )
        tracked = next((item for item in matching if item.request_id == request_id), None)
        if tracked is None:
            raise SourceObserverProofError("source-response-binding-stale")
        if (
            tracked.request_id != request_id
            or tracked.response_id != response_id
            or tracked.request_object is not request_object
            or tracked.response_object is not response_object
            or tracked.response_request_object is not request_object
            or tracked.request_document_token is not self._document_token
            or tracked.response_document_token is not self._document_token
            or document_token is not self._document_token
            or tracked.response_count != 1
            or not tracked.body_read
        ):
            raise SourceObserverProofError("source-response-binding-stale")
        if tracked.status in (403, 429):
            raise SourceObserverProofError("source-access-stop")
        if tracked.status != 200 or tracked.redirected is not False:
            raise SourceObserverProofError("source-response-status-or-redirect-invalid")
        return BoundResponseFacts(
            request_id=tracked.request_id,
            response_id=tracked.response_id,
            document_id=self._document_id,
            status=tracked.status,
            mime_type=tracked.mime_type or "",
            encoded_length=tracked.declared_length or 0,
            redirected=tracked.redirected,
            request_response_identity_matches=True,
            current_document_matches=True,
            current_src_matches=True,
        )


_PURCHASED_READER_PATH = re.compile(r"^/viewer/purchased/B[0-9]+/$")


@dataclass(frozen=True, slots=True)
class SourceResearchPartProof:
    part_index: int
    width: int
    height: int
    source_width: int
    source_height: int
    source_format: str
    source_encoded_length: int
    source_encoded_sha256: str
    roi_count: int
    roi_geometry_sha256: str
    roi_six_integer_rows: tuple[tuple[int, int, int, int, int, int], ...]
    source_response: BoundResponseFacts
    source_epoch: int
    source_reset_sequence: int
    source_transfer_sequence: int
    source_canvas_object_id: int
    source_context_object_id: int
    target_canvas_object_id: int
    target_binding_token: int
    target_reset_sequence: int
    target_draw_sequence: int
    d_draw_generation: int
    source_image_identity_stable: bool
    source_natural_dimensions_stable: bool
    viewport_stable: bool
    viewport_before: tuple[int, int]
    viewport_after: tuple[int, int]
    default_context_attributes_valid: bool
    context_attributes: tuple[bool, str, str, bool, bool]
    draw_attributes: tuple[
        tuple[float, float, float, float, float, float],
        float,
        str,
        str,
        bool,
        float,
        float,
        float,
        bool,
        str,
    ]
    paint_history_complete: bool
    source_rgba_sha256: str
    output_rgba_sha256: str
    d_reference_rgba_sha256: tuple[str, str]
    d_reference_pair_exact: bool
    comparison_passed: bool
    max_rgb_delta_by_channel: tuple[int, int, int]
    rgb_tolerance: int
    rgb_pixels_over_tolerance_by_reference: tuple[int, int]
    rgb_pixels_total: int
    rgb_pixels_over_tolerance_bbox_by_reference: tuple[
        tuple[int, int, int, int] | None,
        tuple[int, int, int, int] | None,
    ]
    rgb_outlier_limit_denominator: int
    alpha_mismatch_pixels: int
    dimensions_exact: bool
    output_format: str
    output_encoded_sha256: str
    output_roundtrip_exact: bool
    capture: CaptureResult = field(repr=False)

    def safe_projection(self) -> dict[str, object]:
        return {
            "part_index": self.part_index,
            "width": self.width,
            "height": self.height,
            "source_width": self.source_width,
            "source_height": self.source_height,
            "source_format": self.source_format,
            "source_encoded_length": self.source_encoded_length,
            "source_encoded_sha256": self.source_encoded_sha256,
            "roi_count": self.roi_count,
            "roi_geometry_sha256": self.roi_geometry_sha256,
            "roi_six_integer_rows": [list(row) for row in self.roi_six_integer_rows],
            "source_response": {
                "request_id": self.source_response.request_id,
                "response_id": self.source_response.response_id,
                "document_id": self.source_response.document_id,
                "status": self.source_response.status,
                "mime_type": self.source_response.mime_type,
                "encoded_length": self.source_response.encoded_length,
                "redirected": self.source_response.redirected,
                "request_response_identity_matches": self.source_response.request_response_identity_matches,
                "current_document_matches": self.source_response.current_document_matches,
                "current_src_matches": self.source_response.current_src_matches,
                "candidate_count": self.source_response.candidate_count,
                "verified_candidate_count": self.source_response.verified_candidate_count,
                "selection_status": self.source_response.selection_status,
                "candidate_policy_revision": SOURCE_CANDIDATE_POLICY_REVISION,
            },
            "source_epoch": self.source_epoch,
            "source_reset_sequence": self.source_reset_sequence,
            "source_transfer_sequence": self.source_transfer_sequence,
            "source_canvas_object_id": self.source_canvas_object_id,
            "source_context_object_id": self.source_context_object_id,
            "target_canvas_object_id": self.target_canvas_object_id,
            "target_binding_token": self.target_binding_token,
            "target_reset_sequence": self.target_reset_sequence,
            "target_draw_sequence": self.target_draw_sequence,
            "d_draw_generation": self.d_draw_generation,
            "source_image_identity_stable": self.source_image_identity_stable,
            "source_natural_dimensions_stable": self.source_natural_dimensions_stable,
            "viewport_stable": self.viewport_stable,
            "viewport_before": list(self.viewport_before),
            "viewport_after": list(self.viewport_after),
            "default_context_attributes_valid": self.default_context_attributes_valid,
            "context_attributes": {
                "alpha": self.context_attributes[0],
                "color_space": self.context_attributes[1],
                "color_type": self.context_attributes[2],
                "desynchronized": self.context_attributes[3],
                "will_read_frequently": self.context_attributes[4],
            },
            "draw_attributes": {
                "transform": list(self.draw_attributes[0]),
                "global_alpha": self.draw_attributes[1],
                "composite_operation": self.draw_attributes[2],
                "filter_value": self.draw_attributes[3],
                "shadow_is_transparent": self.draw_attributes[4],
                "shadow_blur": self.draw_attributes[5],
                "shadow_offset_x": self.draw_attributes[6],
                "shadow_offset_y": self.draw_attributes[7],
                "image_smoothing_enabled": self.draw_attributes[8],
                "image_smoothing_quality": self.draw_attributes[9],
            },
            "paint_history_complete": self.paint_history_complete,
            "source_rgba_sha256": self.source_rgba_sha256,
            "output_rgba_sha256": self.output_rgba_sha256,
            "d_reference_rgba_sha256": list(self.d_reference_rgba_sha256),
            "d_reference_pair_exact": self.d_reference_pair_exact,
            "comparison_passed": self.comparison_passed,
            "max_rgb_delta_by_channel": list(self.max_rgb_delta_by_channel),
            "rgb_tolerance": self.rgb_tolerance,
            "rgb_outlier_policy": {
                "qualifying_pixel": "any RGB channel delta greater than tolerance",
                "counting": "union pixels per exact D reference",
                "maximum_fraction": {
                    "numerator": 1,
                    "denominator": self.rgb_outlier_limit_denominator,
                },
                "acceptance": "outlier_pixels * denominator <= total_pixels",
                "per_reference": [
                    {
                        "outlier_pixels": count,
                        "total_pixels": self.rgb_pixels_total,
                        "bbox_xyxy": list(bbox) if bbox is not None else None,
                    }
                    for count, bbox in zip(
                        self.rgb_pixels_over_tolerance_by_reference,
                        self.rgb_pixels_over_tolerance_bbox_by_reference,
                        strict=True,
                    )
                ],
            },
            "alpha_mismatch_pixels": self.alpha_mismatch_pixels,
            "dimensions_exact": self.dimensions_exact,
            "output_format": self.output_format,
            "output_encoded_sha256": self.output_encoded_sha256,
            "output_roundtrip_exact": self.output_roundtrip_exact,
        }


@dataclass(frozen=True, slots=True)
class SourceResearchOutcome:
    status: ComparisonStatus
    failure_reason: str | None
    limited_history_profile: str | None
    paint_history_complete: bool
    parts: tuple[SourceResearchPartProof, ...]
    captures: tuple[CaptureResult, ...] = field(repr=False)
    fallback_captures: tuple[CaptureResult, ...] = field(default=(), repr=False)

    def safe_projection(self) -> dict[str, object]:
        verified = self.status == "C_VERIFIED"
        return {
            "status": self.status,
            "failure_reason": self.failure_reason,
            "capture_method": SOURCE_METHOD if verified else "D_compositor_png",
            "capture_policy_revision": SOURCE_POLICY_REVISION if verified else None,
            "provenance": "VERIFIED_SOURCE_ROI" if verified else "NOT_ESTABLISHED",
            "runtime_adoption_status": "NOT_ADOPTED",
            "limited_history_profile": self.limited_history_profile,
            "paint_history_complete": self.paint_history_complete,
            "native_page": None,
            "parts": [part.safe_projection() for part in self.parts],
        }


def limited_history_profile_matches(diagnostic: object) -> bool:
    """Match only the exact bounded install-time unknown profile observed at v3."""

    if not isinstance(diagnostic, Mapping):
        return False
    expected_empty = (
        "sourceMethodMissing",
        "sourceMethodNonNative",
        "stateSetterMissing",
        "stateSetterNonNative",
        "offscreenStateSetterMissing",
        "offscreenStateSetterNonNative",
        "slotMismatchStateProperties",
        "slotMismatchDimensionProperties",
    )
    if any(diagnostic.get(name) != [] for name in expected_empty):
        return False
    expected_counts = {
        "offscreenInstallOtherCount": 1,
        "currentSlotOtherCount": 0,
        "unknownMethodSlotCount": 1,
        "unknownMethodSlotDescriptorsOmittedCount": 0,
        "otherMethodCount": 1,
    }
    if any(
        type(diagnostic.get(name)) is not int or diagnostic.get(name) != expected
        for name, expected in expected_counts.items()
    ):
        return False
    def exact_enum_list(name: str, expected: tuple[str, ...]) -> bool:
        value = diagnostic.get(name)
        return (
            isinstance(value, list)
            and len(value) == len(expected)
            and all(type(item) is str for item in value)
            and set(value) == set(expected)
        )

    if (
        diagnostic.get("sourceMethodCoverage") is not True
        or diagnostic.get("sourceStateCoverage") is not True
        or diagnostic.get("offscreenInstall") is not False
        or diagnostic.get("currentSlotMismatch") is not True
        or diagnostic.get("unknownMethodSlotOverflow") is not False
        or not exact_enum_list("offscreenMethodMissing", ("getImageData",))
        or not exact_enum_list("offscreenMethodNonNative", ("arc",))
        or not exact_enum_list("slotMismatchMethods", ("arc", "getImageData"))
    ):
        return False
    descriptors = diagnostic.get("unknownMethodSlotDescriptors")
    if not isinstance(descriptors, list) or len(descriptors) != 1:
        return False
    descriptor = descriptors[0]
    expected_descriptor: dict[str, object] = {
        "opaqueId": "slot-1",
        "ownerDepth": 0,
        "offscreenInstallObserved": True,
        "currentSlotMismatchObserved": False,
        "descriptorKind": "data",
        "valueType": "function",
        "functionNative": False,
        "writable": True,
        "configurable": True,
        "enumerable": True,
        "getterPresent": False,
        "getterNative": False,
        "setterPresent": False,
        "setterNative": False,
    }
    if not isinstance(descriptor, Mapping) or set(descriptor) != set(expected_descriptor):
        return False
    return all(
        type(descriptor.get(name)) is type(expected)
        and descriptor.get(name) == expected
        for name, expected in expected_descriptor.items()
    )


def comparison_proof_fields(
    *,
    part_index: int,
    candidate: object,
    encoded: EncodedCandidate,
    comparison: PixelComparisonProof,
    response: BoundResponseFacts,
    source_binding: Mapping[str, object],
    target_binding: Mapping[str, object],
    default_context_attributes_valid: bool,
    context_attributes: tuple[bool, str, str, bool, bool],
    draw_attributes: tuple[
        tuple[float, float, float, float, float, float],
        float,
        str,
        str,
        bool,
        float,
        float,
        float,
        bool,
        str,
    ],
    source_image_identity_stable: bool,
    source_natural_dimensions_stable: bool,
    viewport_stable: bool,
    viewport_before: tuple[int, int],
    viewport_after: tuple[int, int],
) -> SourceResearchPartProof:
    """Build the explicit, non-secret per-part research proof DTO."""

    source_info = candidate.source_info
    coverage = candidate.roi_proof
    first = comparison.first_reference
    second = comparison.second_reference
    max_delta = tuple(
        max(left, right)
        for left, right in zip(
            first.max_rgb_delta_by_channel,
            second.max_rgb_delta_by_channel,
            strict=True,
        )
    )
    return SourceResearchPartProof(
        part_index=part_index,
        width=candidate.width,
        height=candidate.height,
        source_width=source_info.width,
        source_height=source_info.height,
        source_format=source_info.first_chunk,
        source_encoded_length=source_info.encoded_length,
        source_encoded_sha256=source_info.encoded_sha256,
        roi_count=coverage.operation_count,
        roi_geometry_sha256=coverage.roi_geometry_sha256,
        roi_six_integer_rows=coverage.roi_six_integer_rows,
        source_response=response,
        source_epoch=_integer(source_binding.get("epoch"), "source-epoch-invalid"),
        source_reset_sequence=_integer(source_binding.get("resetSequence"), "source-reset-sequence-invalid"),
        source_transfer_sequence=_integer(source_binding.get("transferSequence"), "source-transfer-sequence-invalid"),
        source_canvas_object_id=_integer(source_binding.get("sourceCanvasObjectId"), "source-canvas-id-invalid"),
        source_context_object_id=_integer(source_binding.get("sourceContextObjectId"), "source-context-id-invalid"),
        target_canvas_object_id=_integer(target_binding.get("canvasObjectId"), "target-canvas-id-invalid"),
        target_binding_token=_integer(target_binding.get("bindingToken"), "target-binding-token-invalid"),
        target_reset_sequence=_integer(target_binding.get("resetSequence"), "target-reset-sequence-invalid"),
        target_draw_sequence=_integer(target_binding.get("lastDrawSequence"), "target-draw-sequence-invalid"),
        d_draw_generation=_integer(target_binding.get("dDrawGeneration"), "target-draw-generation-invalid"),
        source_image_identity_stable=source_image_identity_stable,
        source_natural_dimensions_stable=source_natural_dimensions_stable,
        viewport_stable=viewport_stable,
        viewport_before=viewport_before,
        viewport_after=viewport_after,
        default_context_attributes_valid=default_context_attributes_valid,
        context_attributes=context_attributes,
        draw_attributes=draw_attributes,
        paint_history_complete=False,
        source_rgba_sha256=candidate.rgba_sha256,
        output_rgba_sha256=encoded.rgba_sha256,
        d_reference_rgba_sha256=comparison.reference_rgba_sha256,
        d_reference_pair_exact=comparison.reference_pair_exact,
        comparison_passed=comparison.passed,
        max_rgb_delta_by_channel=max_delta,
        rgb_tolerance=comparison.tolerance,
        rgb_pixels_over_tolerance_by_reference=(
            first.rgb_pixels_over_tolerance,
            second.rgb_pixels_over_tolerance,
        ),
        rgb_pixels_total=candidate.width * candidate.height,
        rgb_pixels_over_tolerance_bbox_by_reference=(
            first.rgb_pixels_over_tolerance_bbox,
            second.rgb_pixels_over_tolerance_bbox,
        ),
        rgb_outlier_limit_denominator=RGB_OUTLIER_LIMIT_DENOMINATOR,
        alpha_mismatch_pixels=max(
            first.alpha_mismatch_pixels, second.alpha_mismatch_pixels
        ),
        dimensions_exact=comparison.dimensions_exact,
        output_format=encoded.output_format,
        output_encoded_sha256=encoded.encoded_sha256,
        output_roundtrip_exact=encoded.exact_roundtrip,
        capture=encoded.capture,
    )


def _integer(value: object, reason: str) -> int:
    if type(value) is not int or value < 0:
        raise SourceCaptureProofError(reason)
    return value


def image_source_sha256(data: bytes) -> str:
    """Hash transient image bytes without exposing or retaining them here."""

    return hashlib.sha256(data).hexdigest()
