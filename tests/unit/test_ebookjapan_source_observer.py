from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace

import pytest

from screenshot_crawler.site_adapters.ebookjapan.source_observer import (
    MAX_ACTIVE_EPOCHS,
    MAX_ROI_OPERATIONS,
    BoundedEpochROICache,
    BoundSourceResponse,
    CanvasDrawState,
    ContextAttributes,
    MethodExceptionProof,
    RequestResponseObservation,
    SourceObserverProofError,
    bind_unique_current_response,
    context_draw_state_is_eligible,
    read_bound_response_body_once,
    target_draw_binding_is_current,
)
from screenshot_crawler.site_adapters.ebookjapan.source_pixels import TileROI


class _Request:
    pass


class _Response:
    def __init__(self, request, body: bytes) -> None:
        self.request = request
        self._body = body
        self.calls = 0

    async def body(self) -> bytes:
        self.calls += 1
        return self._body


def _observation(
    *,
    current_src: str,
    document_token: object,
    body: bytes,
    status: int = 200,
    redirected: bool = False,
    mime: str = "image/webp",
    request: object | None = None,
    response_request: object | None = None,
    request_document: object | None = None,
    response_document: object | None = None,
    declared_length: int | None = None,
) -> tuple[RequestResponseObservation, _Response]:
    actual_request = request if request is not None else _Request()
    response = _Response(
        actual_request if response_request is None else response_request,
        body,
    )
    observation = RequestResponseObservation(
        request_object=actual_request,
        response_object=response,
        response_request_object=response.request,
        request_document_token=(
            document_token if request_document is None else request_document
        ),
        response_document_token=(
            document_token if response_document is None else response_document
        ),
        request_url=current_src,
        status=status,
        redirected=redirected,
        mime_type=mime,
        declared_length=len(body) if declared_length is None else declared_length,
    )
    return observation, response


def _epoch_record(**overrides) -> dict[str, object]:
    record: dict[str, object] = {
        "canvas_object_id": 7,
        "context_object_id": 8,
        "epoch": 2,
        "reset_sequence": 2,
        "dimension_reset_count": 2,
        "successful_reset_count": 2,
        "failed_reset_count": 0,
        "unknown_attribute_reset_count": 0,
        "context_loss_count": 0,
        "width": 1128,
        "height": 1600,
        "known": True,
        "reset_in_progress": False,
        "own_dimension_properties_absent": True,
        "setters_intact": True,
        "last_successful_draw_sequence": 50,
        "last_successful_draw_epoch": 2,
        "last_successful_draw_reset_sequence": 2,
        "last_successful_bitmap_object_id": 42,
        "last_failure_reason": "none",
    }
    record.update(overrides)
    return record


def _default_draw_state() -> CanvasDrawState:
    return CanvasDrawState(
        context_attributes=ContextAttributes(
            alpha=True,
            color_space="srgb",
            color_type="unorm8",
            desynchronized=False,
            will_read_frequently=False,
        ),
        transform=(1, 0, 0, 1, 0, 0),
        global_alpha=1.0,
        composite_operation="source-over",
        filter_value="none",
        shadow_color="rgba(0, 0, 0, 0)",
        shadow_blur=0.0,
        shadow_offset_x=0.0,
        shadow_offset_y=0.0,
        image_smoothing_enabled=True,
        image_smoothing_quality="low",
        clip_count=0,
        state_mutation_count=0,
        context_reset_count=0,
        context_loss_count=0,
        critical_wrappers_match=True,
        method_exceptions=(),
    )


def test_response_binding_requires_one_exact_request_response_and_document() -> None:
    body = b"already-loaded-webp-body"
    document = object()
    current_src = "https://private.invalid/image.webp?token=private"
    observation, response = _observation(
        current_src=current_src,
        document_token=document,
        body=body,
    )

    binding = bind_unique_current_response(
        current_src,
        current_document_token=document,
        observations=(observation,),
    )

    assert binding.response_object is response
    assert binding.request_object is response.request
    assert binding.declared_length == len(body)
    assert current_src not in repr(observation)
    assert current_src not in repr(binding)


def test_response_binding_rejects_ambiguous_urls_old_documents_and_swapped_request() -> None:
    current_src = "https://private.invalid/image.webp?token=private"
    document = object()
    first, _ = _observation(current_src=current_src, document_token=document, body=b"a")
    second, _ = _observation(current_src=current_src, document_token=document, body=b"b")
    with pytest.raises(SourceObserverProofError, match="source-response-ambiguous"):
        bind_unique_current_response(
            current_src,
            current_document_token=document,
            observations=(first, second),
        )

    old_document = object()
    stale, _ = _observation(
        current_src=current_src,
        document_token=document,
        request_document=old_document,
        response_document=old_document,
        body=b"a",
    )
    with pytest.raises(SourceObserverProofError, match="source-response-unmatched"):
        bind_unique_current_response(
            current_src,
            current_document_token=document,
            observations=(stale,),
        )

    request = _Request()
    swapped, _ = _observation(
        current_src=current_src,
        document_token=document,
        body=b"a",
        request=request,
        response_request=_Request(),
    )
    with pytest.raises(SourceObserverProofError, match="source-response-request-identity-mismatch"):
        bind_unique_current_response(
            current_src,
            current_document_token=document,
            observations=(swapped,),
        )


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"status": 403}, "source-response-status-invalid"),
        ({"redirected": True}, "source-response-redirect-invalid"),
        ({"mime": "image/png"}, "source-response-mime-invalid"),
        ({"declared_length": 0}, "source-response-length-invalid"),
    ],
)
def test_response_binding_rejects_noncandidate_responses(overrides, reason: str) -> None:
    current_src = "https://private.invalid/image.webp"
    document = object()
    observation, _ = _observation(
        current_src=current_src,
        document_token=document,
        body=b"body",
        **overrides,
    )
    with pytest.raises(SourceObserverProofError, match=reason):
        bind_unique_current_response(
            current_src,
            current_document_token=document,
            observations=(observation,),
        )


def test_response_body_is_read_once_and_only_length_hash_metadata_is_safe() -> None:
    body = b"already-loaded-webp-body"
    document = object()
    current_src = "https://private.invalid/image.webp?token=private"
    observation, response = _observation(
        current_src=current_src,
        document_token=document,
        body=body,
    )
    binding = bind_unique_current_response(
        current_src,
        current_document_token=document,
        observations=(observation,),
    )

    loaded = asyncio.run(read_bound_response_body_once(binding))

    assert loaded.data == body
    assert loaded.encoded_length == len(body)
    assert loaded.encoded_sha256 == hashlib.sha256(body).hexdigest()
    assert current_src not in repr(loaded)
    assert response.calls == 1
    with pytest.raises(SourceObserverProofError, match="source-response-body-already-read"):
        asyncio.run(read_bound_response_body_once(binding))
    assert response.calls == 1


def test_body_timeout_and_length_mismatch_are_terminal_for_the_one_response() -> None:
    current_src = "https://private.invalid/image.webp"
    document = object()
    observation, _ = _observation(
        current_src=current_src,
        document_token=document,
        body=b"short",
        declared_length=8,
    )
    binding = bind_unique_current_response(
        current_src,
        current_document_token=document,
        observations=(observation,),
    )
    with pytest.raises(SourceObserverProofError, match="source-response-length-mismatch"):
        asyncio.run(read_bound_response_body_once(binding))

    class SlowResponse:
        async def body(self) -> bytes:
            await asyncio.sleep(0.1)
            return b"body"

    slow_binding = BoundSourceResponse(
        response_object=SlowResponse(),
        request_object=object(),
        document_token=document,
        status=200,
        mime_type="image/webp",
        declared_length=4,
    )
    with pytest.raises(SourceObserverProofError, match="source-response-body-timeout"):
        asyncio.run(read_bound_response_body_once(slow_binding, timeout_seconds=0.001))
    with pytest.raises(SourceObserverProofError, match="source-response-body-already-read"):
        asyncio.run(read_bound_response_body_once(slow_binding))


def test_bounded_epoch_cache_caps_entries_operations_and_preserves_pins() -> None:
    cache = BoundedEpochROICache()
    for epoch in range(MAX_ACTIVE_EPOCHS):
        cache.append((epoch + 1, 1), TileROI(0, 0, 0, 0, 1, 1))
    assert cache.active_epoch_count == MAX_ACTIVE_EPOCHS
    cache.append((MAX_ACTIVE_EPOCHS + 1, 1), TileROI(0, 0, 0, 0, 1, 1))
    assert cache.active_epoch_count == MAX_ACTIVE_EPOCHS
    with pytest.raises(SourceObserverProofError, match="epoch-cache-entry-missing"):
        cache.snapshot((1, 1))

    pinned = BoundedEpochROICache()
    for epoch in range(MAX_ACTIVE_EPOCHS):
        key = (epoch + 1, 1)
        pinned.pin(key)
    with pytest.raises(SourceObserverProofError, match="active-epoch-cache-full"):
        pinned.append((MAX_ACTIVE_EPOCHS + 1, 1), TileROI(0, 0, 0, 0, 1, 1))
    assert pinned.active_epoch_count == MAX_ACTIVE_EPOCHS

    capped = BoundedEpochROICache()
    key = (1, 1)
    for _ in range(MAX_ROI_OPERATIONS):
        capped.append(key, TileROI(0, 0, 0, 0, 1, 1))
    with pytest.raises(SourceObserverProofError, match="epoch-roi-operation-cap-exceeded"):
        capped.append(key, TileROI(0, 0, 0, 0, 1, 1))
    assert len(capped.snapshot(key)) == MAX_ROI_OPERATIONS


def test_default_draw_state_keeps_known_exceptions_explicit_and_rejects_unknowns() -> None:
    safe_known = replace(
        _default_draw_state(),
        method_exceptions=(
            MethodExceptionProof("arc", False, True, 0, True),
            MethodExceptionProof("getImageData", False, True, 0, False),
        ),
    )
    assert context_draw_state_is_eligible(safe_known) is True
    assert safe_known.method_exceptions[1].invocations_observed_all is False

    assert context_draw_state_is_eligible(
        replace(safe_known, clip_count=1)
    ) is False
    assert context_draw_state_is_eligible(
        replace(safe_known, state_mutation_count=1)
    ) is False
    assert context_draw_state_is_eligible(
        replace(safe_known, critical_wrappers_match=False)
    ) is False
    assert context_draw_state_is_eligible(
        replace(
            safe_known,
            method_exceptions=(MethodExceptionProof("drawImage", False, True, 0, True),),
        )
    ) is False
    assert context_draw_state_is_eligible(
        replace(
            safe_known,
            method_exceptions=(MethodExceptionProof("arc", False, False, 0, True),),
        )
    ) is False
    assert context_draw_state_is_eligible(
        replace(safe_known, context_attributes=replace(safe_known.context_attributes, alpha=False))
    ) is False


def test_target_binding_accepts_known_resets_only_with_current_redraw() -> None:
    call = _epoch_record(
        last_successful_draw_sequence=None,
        last_successful_draw_epoch=None,
        last_successful_draw_reset_sequence=None,
        last_successful_bitmap_object_id=None,
    )
    draw = _epoch_record()
    current = _epoch_record()
    assert target_draw_binding_is_current(
        call,
        draw,
        current,
        expected_dimensions=(1128, 1600),
        expected_bitmap_id=42,
        same_document=True,
    ) is True

    # Same-size reset increments the epoch. An old draw cannot prove freshness.
    reset_current = _epoch_record(
        epoch=3,
        reset_sequence=3,
        dimension_reset_count=3,
        successful_reset_count=3,
        last_successful_draw_epoch=2,
        last_successful_draw_reset_sequence=2,
    )
    assert target_draw_binding_is_current(
        call,
        draw,
        reset_current,
        expected_dimensions=(1128, 1600),
        expected_bitmap_id=42,
        same_document=True,
    ) is False
    assert target_draw_binding_is_current(
        call,
        _epoch_record(last_successful_bitmap_object_id=41),
        current,
        expected_dimensions=(1128, 1600),
        expected_bitmap_id=42,
        same_document=True,
    ) is False
    assert target_draw_binding_is_current(
        call,
        draw,
        current,
        expected_dimensions=(1128, 1600),
        expected_bitmap_id=42,
        same_document=False,
    ) is False


@pytest.mark.parametrize(
    ("side", "field", "value"),
    [
        ("draw", "last_successful_draw_sequence", True),
        ("current", "last_successful_draw_sequence", 50.0),
        ("draw", "last_successful_draw_epoch", True),
        ("current", "last_successful_draw_epoch", 2.0),
        ("draw", "last_successful_draw_reset_sequence", True),
        ("current", "last_successful_draw_reset_sequence", 2.0),
        ("draw", "last_successful_bitmap_object_id", True),
        ("current", "last_successful_bitmap_object_id", 42.0),
    ],
)
def test_target_binding_rejects_non_integer_draw_identity_fields(
    side: str, field: str, value: object
) -> None:
    call, draw, current = _epoch_record(), _epoch_record(), _epoch_record()
    (draw if side == "draw" else current)[field] = value
    assert target_draw_binding_is_current(
        call,
        draw,
        current,
        expected_dimensions=(1128, 1600),
        expected_bitmap_id=42,
        same_document=True,
    ) is False
