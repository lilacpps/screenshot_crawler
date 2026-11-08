"""Bounded source-response and draw-epoch proof primitives for EbookJapan.

The browser integration will feed this module safe snapshots from the existing
viewer observer. This module does not install a second canvas wrapper, navigate
or fetch URLs, or persist request URLs/source bodies.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from screenshot_crawler.site_adapters.ebookjapan.source_pixels import TileROI

MAX_ACTIVE_EPOCHS: Final = 32
MAX_ROI_OPERATIONS: Final = 512
MAX_RESPONSE_BODY_BYTES: Final = 8 * 1024 * 1024
MAX_RESPONSE_BODY_WAIT_SECONDS: Final = 5.0
KNOWN_SAFE_EXCEPTION_METHODS: Final = frozenset({"arc", "getImageData"})


class SourceObserverProofError(ValueError):
    """A bounded proof failure with a fixed reason code only."""

    __slots__ = ("reason_code",)

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


@dataclass(frozen=True, slots=True)
class RequestResponseObservation:
    """One in-memory response observation; URL and browser objects are private.

    `request_url` is used only to bind an observed image's currentSrc during
    this call. It is excluded from repr and is never included in the returned
    proof object.
    """

    request_object: object = field(repr=False, compare=False)
    response_object: object = field(repr=False, compare=False)
    response_request_object: object = field(repr=False, compare=False)
    request_document_token: object = field(repr=False, compare=False)
    response_document_token: object = field(repr=False, compare=False)
    request_url: str = field(repr=False, compare=False)
    status: int
    redirected: bool
    mime_type: str
    declared_length: int


@dataclass(slots=True)
class BoundSourceResponse:
    """One unique, current-document response eligible for one body read."""

    response_object: object = field(repr=False)
    request_object: object = field(repr=False)
    document_token: object = field(repr=False)
    status: int
    mime_type: str
    declared_length: int
    _read_attempted: bool = field(default=False, init=False, repr=False)


@dataclass(frozen=True, slots=True)
class LoadedSourceBody:
    """A single in-memory response body plus non-sensitive validation facts."""

    data: bytes = field(repr=False)
    encoded_length: int
    encoded_sha256: str
    mime_type: str


class BoundedEpochROICache:
    """A no-TTL cache for at most 32 epochs and 512 observed ROIs per epoch."""

    __slots__ = ("_entries", "_pinned")

    def __init__(self) -> None:
        self._entries: OrderedDict[tuple[int, int], list[TileROI]] = OrderedDict()
        self._pinned: set[tuple[int, int]] = set()

    @staticmethod
    def _key(value: object) -> tuple[int, int]:
        if (
            not isinstance(value, tuple)
            or len(value) != 2
            or any(type(part) is not int or part < 0 for part in value)
        ):
            raise SourceObserverProofError("epoch-cache-key-invalid")
        return value

    def _ensure(self, key: tuple[int, int]) -> None:
        if key in self._entries:
            self._entries.move_to_end(key)
            return
        if len(self._entries) >= MAX_ACTIVE_EPOCHS:
            evictable = next((candidate for candidate in self._entries if candidate not in self._pinned), None)
            if evictable is None:
                raise SourceObserverProofError("active-epoch-cache-full")
            del self._entries[evictable]
        self._entries[key] = []

    def pin(self, key: tuple[int, int]) -> None:
        normalized = self._key(key)
        self._ensure(normalized)
        self._pinned.add(normalized)

    def unpin(self, key: tuple[int, int]) -> None:
        self._pinned.discard(self._key(key))

    def append(self, key: tuple[int, int], roi: TileROI) -> None:
        normalized = self._key(key)
        if not isinstance(roi, TileROI):
            raise SourceObserverProofError("epoch-cache-roi-invalid")
        self._ensure(normalized)
        rows = self._entries[normalized]
        if len(rows) >= MAX_ROI_OPERATIONS:
            raise SourceObserverProofError("epoch-roi-operation-cap-exceeded")
        rows.append(roi)

    def snapshot(self, key: tuple[int, int]) -> tuple[TileROI, ...]:
        normalized = self._key(key)
        rows = self._entries.get(normalized)
        if rows is None:
            raise SourceObserverProofError("epoch-cache-entry-missing")
        self._entries.move_to_end(normalized)
        return tuple(rows)

    @property
    def active_epoch_count(self) -> int:
        return len(self._entries)


def bind_unique_current_response(
    current_src: str,
    *,
    current_document_token: object,
    observations: Sequence[RequestResponseObservation],
) -> BoundSourceResponse:
    """Bind currentSrc to one exact same-document Request/Response pair.

    URL equality is a transient lookup only. A valid binding additionally
    requires object identity between the held Request and
    ``Response.request``, and both observations must belong to the exact
    current document token.
    """

    if not isinstance(current_src, str) or not current_src:
        raise SourceObserverProofError("source-current-src-unavailable")
    matching = [
        observation
        for observation in observations
        if observation.request_url == current_src
        and observation.request_document_token is current_document_token
        and observation.response_document_token is current_document_token
    ]
    if len(matching) != 1:
        raise SourceObserverProofError(
            "source-response-unmatched" if not matching else "source-response-ambiguous"
        )
    observation = matching[0]
    if observation.response_request_object is not observation.request_object:
        raise SourceObserverProofError("source-response-request-identity-mismatch")
    if type(observation.status) is not int or observation.status != 200:
        raise SourceObserverProofError("source-response-status-invalid")
    if type(observation.redirected) is not bool or observation.redirected:
        raise SourceObserverProofError("source-response-redirect-invalid")
    if (
        not isinstance(observation.mime_type, str)
        or observation.mime_type.strip().lower() != "image/webp"
    ):
        raise SourceObserverProofError("source-response-mime-invalid")
    if (
        type(observation.declared_length) is not int
        or not 1 <= observation.declared_length <= MAX_RESPONSE_BODY_BYTES
    ):
        raise SourceObserverProofError("source-response-length-invalid")
    return BoundSourceResponse(
        response_object=observation.response_object,
        request_object=observation.request_object,
        document_token=current_document_token,
        status=observation.status,
        mime_type="image/webp",
        declared_length=observation.declared_length,
    )


async def read_bound_response_body_once(
    binding: BoundSourceResponse,
    *,
    timeout_seconds: float = MAX_RESPONSE_BODY_WAIT_SECONDS,
) -> LoadedSourceBody:
    """Read one already-loaded Playwright Response body once, in memory only."""

    if not isinstance(binding, BoundSourceResponse):
        raise SourceObserverProofError("source-response-binding-invalid")
    if binding._read_attempted:
        raise SourceObserverProofError("source-response-body-already-read")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(float(timeout_seconds))
        or not 0 < float(timeout_seconds) <= MAX_RESPONSE_BODY_WAIT_SECONDS
    ):
        raise SourceObserverProofError("source-response-timeout-invalid")
    # Set before awaiting so timeout or decoder failure can never be retried.
    binding._read_attempted = True
    response_body = getattr(binding.response_object, "body", None)
    if not callable(response_body):
        raise SourceObserverProofError("source-response-body-unavailable")
    try:
        data = await asyncio.wait_for(response_body(), timeout=float(timeout_seconds))
    except TimeoutError as exc:
        raise SourceObserverProofError("source-response-body-timeout") from exc
    except Exception as exc:  # response exception text can contain a private URL
        raise SourceObserverProofError("source-response-body-read-failed") from exc
    if type(data) is not bytes or not 1 <= len(data) <= MAX_RESPONSE_BODY_BYTES:
        raise SourceObserverProofError("source-response-body-size-invalid")
    if len(data) != binding.declared_length:
        raise SourceObserverProofError("source-response-length-mismatch")
    return LoadedSourceBody(
        data=data,
        encoded_length=len(data),
        encoded_sha256=hashlib.sha256(data).hexdigest(),
        mime_type=binding.mime_type,
    )


@dataclass(frozen=True, slots=True)
class ContextAttributes:
    alpha: bool
    color_space: str
    color_type: str
    desynchronized: bool
    will_read_frequently: bool


@dataclass(frozen=True, slots=True)
class MethodExceptionProof:
    method: str
    descriptor_matches: bool
    exception_safe: bool
    invocation_count: int | None
    invocations_observed_all: bool


@dataclass(frozen=True, slots=True)
class CanvasDrawState:
    """Immutable call-time state captured with one source/target draw."""

    context_attributes: ContextAttributes
    transform: tuple[float, float, float, float, float, float]
    global_alpha: float
    composite_operation: str
    filter_value: str
    shadow_color: str
    shadow_blur: float
    shadow_offset_x: float
    shadow_offset_y: float
    image_smoothing_enabled: bool
    image_smoothing_quality: str
    clip_count: int
    state_mutation_count: int
    context_reset_count: int
    context_loss_count: int
    critical_wrappers_match: bool
    method_exceptions: tuple[MethodExceptionProof, ...]


def context_draw_state_is_eligible(
    state: CanvasDrawState,
) -> bool:
    """Require the observed default, unclipped, mutation-free draw state.

    The two reviewed descriptor exceptions are retained as explicit rows.
    This function does not claim every attempted `getImageData` call was
    observed; its `invocations_observed_all` value remains part of the proof.
    """

    if not isinstance(state, CanvasDrawState):
        return False
    attributes = state.context_attributes
    if not isinstance(attributes, ContextAttributes):
        return False
    if (
        attributes.alpha is not True
        or attributes.color_space != "srgb"
        or attributes.color_type != "unorm8"
        or attributes.desynchronized is not False
        or attributes.will_read_frequently is not False
    ):
        return False
    if (
        not isinstance(state.transform, tuple)
        or len(state.transform) != 6
        or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            for value in state.transform
        )
        or any(
            abs(float(actual) - expected) > 1e-6
            for actual, expected in zip(state.transform, (1, 0, 0, 1, 0, 0), strict=True)
        )
        or isinstance(state.global_alpha, bool)
        or not isinstance(state.global_alpha, (int, float))
        or not math.isfinite(float(state.global_alpha))
        or abs(float(state.global_alpha) - 1.0) > 1e-6
        or state.composite_operation != "source-over"
        or state.filter_value != "none"
        or state.shadow_color not in {"rgba(0, 0, 0, 0)", "transparent"}
        or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or abs(float(value)) > 1e-6
            for value in (state.shadow_blur, state.shadow_offset_x, state.shadow_offset_y)
        )
        or state.image_smoothing_enabled is not True
        or state.image_smoothing_quality != "low"
        or type(state.clip_count) is not int
        or state.clip_count != 0
        or type(state.state_mutation_count) is not int
        or state.state_mutation_count != 0
        or type(state.context_reset_count) is not int
        or state.context_reset_count != 0
        or type(state.context_loss_count) is not int
        or state.context_loss_count != 0
        or state.critical_wrappers_match is not True
    ):
        return False
    if not isinstance(state.method_exceptions, tuple):
        return False
    for exception in state.method_exceptions:
        if not isinstance(exception, MethodExceptionProof):
            return False
        if (
            type(exception.descriptor_matches) is not bool
            or type(exception.exception_safe) is not bool
            or type(exception.invocations_observed_all) is not bool
            or (
                exception.invocation_count is not None
                and type(exception.invocation_count) is not int
            )
        ):
            return False
        if exception.descriptor_matches:
            continue
        if (
            exception.method not in KNOWN_SAFE_EXCEPTION_METHODS
            or exception.exception_safe is not True
            or exception.invocation_count not in (None, 0)
        ):
            return False
    return True


def target_draw_binding_is_current(
    call_epoch: Mapping[str, object],
    draw_epoch: Mapping[str, object],
    current_epoch: Mapping[str, object],
    *,
    expected_dimensions: tuple[int, int],
    expected_bitmap_id: int,
    same_document: bool,
) -> bool:
    """Reject stale target pixels, including a same-size reset without redraw."""

    if same_document is not True or type(expected_bitmap_id) is not int or expected_bitmap_id <= 0:
        return False
    if not isinstance(call_epoch, Mapping) or not isinstance(draw_epoch, Mapping) or not isinstance(current_epoch, Mapping):
        return False
    if (
        not isinstance(expected_dimensions, tuple)
        or len(expected_dimensions) != 2
        or any(type(value) is not int or value <= 0 for value in expected_dimensions)
    ):
        return False
    records = (call_epoch, draw_epoch, current_epoch)
    required_true = ("known", "own_dimension_properties_absent", "setters_intact")
    required_false = ("reset_in_progress",)
    shared_integer_fields = (
        "canvas_object_id",
        "context_object_id",
        "epoch",
        "reset_sequence",
        "dimension_reset_count",
        "successful_reset_count",
        "failed_reset_count",
        "unknown_attribute_reset_count",
        "context_loss_count",
        "width",
        "height",
    )
    first = records[0]
    for record in records:
        if any(record.get(key) is not True for key in required_true):
            return False
        if any(record.get(key) is not False for key in required_false):
            return False
        if record.get("last_failure_reason") != "none":
            return False
        for key in shared_integer_fields:
            value = record.get(key)
            if type(value) is not int or value < 0:
                return False
            if value != first.get(key):
                return False
        reset_count = record.get("dimension_reset_count")
        if (
            record.get("successful_reset_count") != reset_count
            or record.get("failed_reset_count") != 0
            or record.get("unknown_attribute_reset_count") != 0
            or record.get("context_loss_count") != 0
        ):
            return False
        if (record.get("width"), record.get("height")) != expected_dimensions:
            return False
    if draw_epoch.get("epoch") != current_epoch.get("epoch"):
        return False
    if draw_epoch.get("reset_sequence") != current_epoch.get("reset_sequence"):
        return False
    draw_fields = (
        ("last_successful_draw_sequence", 1, None),
        ("last_successful_draw_epoch", 0, draw_epoch.get("epoch")),
        ("last_successful_draw_reset_sequence", 0, draw_epoch.get("reset_sequence")),
        ("last_successful_bitmap_object_id", 1, expected_bitmap_id),
    )
    current_fields = (
        ("last_successful_draw_sequence", 1, draw_epoch.get("last_successful_draw_sequence")),
        ("last_successful_draw_epoch", 0, current_epoch.get("epoch")),
        ("last_successful_draw_reset_sequence", 0, current_epoch.get("reset_sequence")),
        ("last_successful_bitmap_object_id", 1, expected_bitmap_id),
    )
    for record, fields in ((draw_epoch, draw_fields), (current_epoch, current_fields)):
        for name, minimum, expected in fields:
            value = record.get(name)
            if type(value) is not int or value < minimum:
                return False
            if expected is not None and value != expected:
                return False
    return True

