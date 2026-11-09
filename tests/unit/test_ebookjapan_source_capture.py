from __future__ import annotations

import io

import pytest
from PIL import Image

from screenshot_crawler.site_adapters.ebookjapan.adapter import EbookJapanAdapter
from screenshot_crawler.site_adapters.ebookjapan.source_capture import (
    LIMITED_HISTORY_PROFILE,
    MAX_SOURCE_RESPONSE_CANDIDATES,
    SourceCaptureProofError,
    SourceRequestLedger,
    limited_history_profile_matches,
    select_source_roi_candidate,
)
from screenshot_crawler.site_adapters.ebookjapan.source_observer import SourceObserverProofError
from screenshot_crawler.site_adapters.ebookjapan.source_pixels import (
    ReferencePixels,
    decode_webp_source,
)

READER_URL = "https://ebookjapan.yahoo.co.jp/viewer/purchased/B123456789012/"
CACHE_SOURCE_URL = "https://cache2-ebookjapan.akamaized.net/fixture-atlas.webp"
PRODUCTION_SOURCE_URL = "https://prod-contents-br-page.akamaized.net/fixture-atlas.webp"
SOURCE_URL = CACHE_SOURCE_URL


class _Frame:
    pass


class _Request:
    def __init__(
        self,
        frame: object,
        url: str,
        *,
        navigation: bool = False,
        redirected_from: object | None = None,
    ) -> None:
        self.frame = frame
        self.url = url
        self.resource_type = "document" if navigation else "image"
        self._navigation = navigation
        self.redirected_from = redirected_from

    def is_navigation_request(self) -> bool:
        return self._navigation


class _Response:
    def __init__(
        self,
        request: _Request,
        frame: object,
        *,
        status: int = 200,
        content_type: str = "image/webp",
    ) -> None:
        self.request = request
        self.frame = frame
        self.status = status
        self.headers = {"content-type": content_type, "content-length": "128"}


def _add_image_response(
    ledger: SourceRequestLedger,
    frame: object,
    *,
    url: str = SOURCE_URL,
    status: int = 200,
    redirected_from: object | None = None,
) -> tuple[_Request, _Response]:
    request = _Request(frame, url, redirected_from=redirected_from)
    ledger.request_started(request, main_frame=frame, reader_url=READER_URL)
    response = _Response(request, frame, status=status)
    ledger.response_received(response, main_frame=frame)
    return request, response


def _ledger() -> tuple[SourceRequestLedger, _Frame]:
    ledger = SourceRequestLedger()
    frame = _Frame()
    ledger.main_frame_committed(frame, main_frame=frame)
    return ledger, frame


def _profile() -> dict[str, object]:
    return {
        "sourceMethodCoverage": True,
        "sourceStateCoverage": True,
        "offscreenInstall": False,
        "currentSlotMismatch": True,
        "sourceMethodMissing": [],
        "sourceMethodNonNative": [],
        "stateSetterMissing": [],
        "stateSetterNonNative": [],
        "offscreenStateSetterMissing": [],
        "offscreenStateSetterNonNative": [],
        "slotMismatchStateProperties": [],
        "slotMismatchDimensionProperties": [],
        "offscreenInstallOtherCount": 1,
        "currentSlotOtherCount": 0,
        "unknownMethodSlotCount": 1,
        "unknownMethodSlotDescriptorsOmittedCount": 0,
        "unknownMethodSlotOverflow": False,
        "offscreenMethodMissing": ["getImageData"],
        "offscreenMethodNonNative": ["arc"],
        "slotMismatchMethods": ["arc", "getImageData"],
        "otherMethodCount": 1,
        "unknownMethodSlotDescriptors": [
            {
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
        ],
    }


def test_only_the_exact_live_v3_limited_history_profile_is_eligible() -> None:
    assert LIMITED_HISTORY_PROFILE == "muda2-install-unknown-callable-v3"
    assert limited_history_profile_matches(_profile()) is True


def test_access_profile_marks_only_the_observed_source_hosts_relevant() -> None:
    matcher = EbookJapanAdapter().get_access_profile().relevant_host
    assert matcher("https://ebookjapan.yahoo.co.jp/viewer/purchased/B123456789012/")
    assert matcher(SOURCE_URL)
    assert matcher("https://ebookjapan.akamaized.net/atlas.webp")
    assert matcher(PRODUCTION_SOURCE_URL)
    assert not matcher("https://cache2-ebookjapan.akamaized.net.attacker.example/atlas.webp")
    assert not matcher("https://prod-contents-br-page.akamaized.net.attacker.example/atlas.webp")
    assert not matcher("https://sub.prod-contents-br-page.akamaized.net/atlas.webp")
    assert not matcher("https://unobserved.example/atlas.webp")


def test_limited_profile_method_enums_ignore_native_enumeration_order_only() -> None:
    diagnostic = _profile()
    diagnostic["slotMismatchMethods"] = ["getImageData", "arc"]
    assert limited_history_profile_matches(diagnostic) is True

    diagnostic["slotMismatchMethods"] = ["getImageData", "getImageData"]
    assert limited_history_profile_matches(diagnostic) is False


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("offscreenInstallOtherCount",), True),
        (("unknownMethodSlotDescriptors", 0, "ownerDepth"), False),
        (("unknownMethodSlotDescriptors", 0, "writable"), 1),
    ],
)
def test_limited_profile_rejects_bool_as_int_and_int_as_bool(
    path: tuple[object, ...], value: object
) -> None:
    diagnostic = _profile()
    target: object = diagnostic
    for name in path[:-1]:
        target = target[name]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]
    assert limited_history_profile_matches(diagnostic) is False


@pytest.mark.parametrize("source_url", [CACHE_SOURCE_URL, PRODUCTION_SOURCE_URL])
def test_unique_same_document_loaded_response_can_be_latched_and_revalidated(
    source_url: str,
) -> None:
    ledger, frame = _ledger()
    request, response = _add_image_response(ledger, frame, url=source_url)
    binding, facts = ledger.bind_current_src(source_url)

    assert facts.current_document_matches is True
    assert facts.request_response_identity_matches is True
    assert source_url not in repr(ledger)
    ledger.mark_body_attempted(facts.request_id)
    validated = ledger.validate_held_binding(
        source_url,
        request_id=facts.request_id,
        response_id=facts.response_id,
        request_object=request,
        response_object=response,
        document_token=binding.document_token,
    )
    assert validated == facts
    with pytest.raises(SourceObserverProofError, match="source-response-body-already-read"):
        ledger.bind_current_src(source_url)


def test_late_duplicate_response_invalidates_a_held_binding() -> None:
    ledger, frame = _ledger()
    request, response = _add_image_response(ledger, frame)
    binding, facts = ledger.bind_current_src(SOURCE_URL)
    ledger.mark_body_attempted(facts.request_id)
    ledger.validate_held_binding(
        SOURCE_URL,
        request_id=facts.request_id,
        response_id=facts.response_id,
        request_object=request,
        response_object=response,
        document_token=binding.document_token,
    )

    _duplicate, _duplicate_response = _add_image_response(ledger, frame)
    with pytest.raises(SourceObserverProofError, match="source-response-ambiguous"):
        ledger.validate_held_binding(
            SOURCE_URL,
            request_id=facts.request_id,
            response_id=facts.response_id,
            request_object=request,
            response_object=response,
            document_token=binding.document_token,
        )


def test_duplicate_response_event_on_the_same_request_is_ambiguous() -> None:
    ledger, frame = _ledger()
    request, response = _add_image_response(ledger, frame)
    binding, facts = ledger.bind_current_src(SOURCE_URL)
    ledger.mark_body_attempted(facts.request_id)

    ledger.response_received(response, main_frame=frame)

    with pytest.raises(SourceObserverProofError, match="source-response-binding-stale"):
        ledger.validate_held_binding(
            SOURCE_URL,
            request_id=facts.request_id,
            response_id=facts.response_id,
            request_object=request,
            response_object=response,
            document_token=binding.document_token,
        )


def test_late_old_document_request_invalidates_a_new_document_binding() -> None:
    ledger, frame = _ledger()
    old_request = _Request(frame, SOURCE_URL)
    ledger.request_started(old_request, main_frame=frame, reader_url=READER_URL)
    navigation = _Request(frame, READER_URL, navigation=True)
    ledger.request_started(navigation, main_frame=frame, reader_url=READER_URL)
    assert ledger.pending_main_navigation is True
    ledger.main_frame_committed(frame, main_frame=frame)

    new_request, new_response = _add_image_response(ledger, frame)
    with pytest.raises(SourceObserverProofError, match="source-request-ambiguous"):
        ledger.bind_current_src(SOURCE_URL)
    old_response = _Response(old_request, frame)
    ledger.response_received(old_response, main_frame=frame)

    with pytest.raises(SourceObserverProofError, match="source-response-ambiguous"):
        ledger.validate_held_binding(
            SOURCE_URL,
            request_id=1,
            response_id=1,
            request_object=new_request,
            response_object=new_response,
            document_token=ledger.document_token,
        )


@pytest.mark.parametrize(
    ("host", "status"),
    [
        ("ebookjapan.akamaized.net", 403),
        ("ebookjapan.akamaized.net", 429),
        ("prod-contents-br-page.akamaized.net", 403),
        ("prod-contents-br-page.akamaized.net", 429),
    ],
)
def test_nonselected_first_party_403_or_429_is_a_latched_access_stop(
    host: str,
    status: int,
) -> None:
    ledger, frame = _ledger()
    _request, _response = _add_image_response(
        ledger,
        frame,
        url=f"https://{host}/unselected.webp",
        status=status,
    )
    assert ledger.access_stop_status == status
    with pytest.raises(SourceObserverProofError, match="source-access-stop"):
        ledger.bind_current_src(PRODUCTION_SOURCE_URL)


@pytest.mark.parametrize("status", [403, 429])
def test_duplicate_production_host_stop_response_is_latched(status: int) -> None:
    ledger, frame = _ledger()
    request, _response = _add_image_response(
        ledger,
        frame,
        url=PRODUCTION_SOURCE_URL,
    )
    assert ledger.access_stop_status is None

    duplicate_stop = _Response(request, frame, status=status)
    ledger.response_received(duplicate_stop, main_frame=frame)

    assert ledger.access_stop_status == status
    with pytest.raises(SourceObserverProofError, match="source-access-stop"):
        ledger.bind_current_src(PRODUCTION_SOURCE_URL)


@pytest.mark.parametrize(
    "source_url",
    [
        "https://prod-contents-br-page.akamaized.net.attacker.example/atlas.webp",
        "https://sub.prod-contents-br-page.akamaized.net/atlas.webp",
        "http://prod-contents-br-page.akamaized.net/atlas.webp",
    ],
)
def test_production_host_lookalikes_are_not_tracked_or_adopted(source_url: str) -> None:
    ledger, frame = _ledger()
    request = _Request(frame, source_url)

    ledger.request_started(request, main_frame=frame, reader_url=READER_URL)

    assert len(ledger._requests) == 0
    with pytest.raises(SourceObserverProofError, match="source-current-src-host-unobserved"):
        ledger.bind_current_src(source_url)


def test_redirected_request_cannot_bind_current_src() -> None:
    ledger, frame = _ledger()
    _add_image_response(ledger, frame, redirected_from=object())
    with pytest.raises(SourceObserverProofError, match="source-response-redirect-invalid"):
        ledger.bind_current_src(SOURCE_URL)


def test_source_request_during_pending_navigation_is_not_adopted() -> None:
    ledger, frame = _ledger()
    navigation = _Request(frame, READER_URL, navigation=True)
    ledger.request_started(navigation, main_frame=frame, reader_url=READER_URL)
    _add_image_response(ledger, frame)
    with pytest.raises(SourceObserverProofError, match="source-document-navigation-pending"):
        ledger.bind_current_src(SOURCE_URL)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["late-request", "duplicate-event", "navigation", "access-stop"])
async def test_loaded_cohort_rejects_late_unsafe_changes(mutation: str) -> None:
    ledger, frame = _ledger()
    for _ in range(2):
        _request, response = _add_image_response(ledger, frame)
        async def body():
            return b"x" * 128
        response.body = body
    cohort = await ledger.load_current_src_candidates(SOURCE_URL)
    cohort.validate(ledger, SOURCE_URL)
    if mutation == "late-request":
        _add_image_response(ledger, frame)
    elif mutation == "duplicate-event":
        ledger.response_received(response, main_frame=frame)
    elif mutation == "navigation":
        ledger.main_frame_committed(frame, main_frame=frame)
    else:
        _add_image_response(ledger, frame, url=PRODUCTION_SOURCE_URL, status=429)
    with pytest.raises(SourceObserverProofError):
        cohort.validate(ledger, SOURCE_URL)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["count", "bytes", "pending", "old-document", "body-failed"])
async def test_candidate_loading_remains_bounded_and_fail_closed(failure: str) -> None:
    ledger, frame = _ledger()
    if failure == "old-document":
        old = _Request(frame, SOURCE_URL)
        ledger.request_started(old, main_frame=frame, reader_url=READER_URL)
        ledger.main_frame_committed(frame, main_frame=frame)
    reads = 0

    async def body():
        nonlocal reads
        reads += 1
        if failure == "body-failed":
            raise RuntimeError("private response details")
        return b"x" * 128

    for _ in range(MAX_SOURCE_RESPONSE_CANDIDATES + 1 if failure == "count" else 2):
        _request, response = _add_image_response(ledger, frame)
        response.body = body
        if failure == "bytes":
            ledger._requests[-1].declared_length = 8 * 1024 * 1024
    if failure == "pending":
        pending = _Request(frame, SOURCE_URL)
        ledger.request_started(pending, main_frame=frame, reader_url=READER_URL)
    with pytest.raises(SourceObserverProofError):
        await ledger.load_current_src_candidates(SOURCE_URL)
    assert reads == (1 if failure == "body-failed" else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("colors", "distinct_bytes", "status", "verified_count"),
    [
        ([100, 100], False, "equivalent_bytes", 2),
        ([100, 100], True, "equivalent_verified_pixels", 2),
        ([220, 100], False, "unique_verified_candidate", 1),
        ([100, 220], False, "unique_verified_candidate", 1),
        ([100, 101], False, "source-candidate-output-ambiguous", None),
        ([220, 230], False, "source-pixel-equivalence-failed", None),
    ],
)
async def test_multiple_response_candidates_are_proved_instead_of_chosen_by_order(
    colors: list[int], distinct_bytes: bool, status: str, verified_count: int | None,
) -> None:
    ledger, frame = _ledger()
    bodies = []
    reads = []
    for index, color in enumerate(colors):
        buffer = io.BytesIO()
        Image.new("RGB", (16, 16), (color,) * 3).save(buffer, format="WEBP", quality=100)
        data = buffer.getvalue()
        if index and distinct_bytes:
            data += b"JUNK\x02\x00\x00\x00xx"
            data = data[:4] + (len(data) - 8).to_bytes(4, "little") + data[8:]
        bodies.append(data)
        _request, response = _add_image_response(ledger, frame)
        response.headers["content-length"] = str(len(data))
        ledger._requests[-1].declared_length = len(data)

        async def body(data=data, index=index):
            reads.append(index)
            return data

        response.body = body
    cohort = await ledger.load_current_src_candidates(SOURCE_URL)
    assert reads == [0, 1]
    baseline = next((data for color, data in zip(colors, bodies, strict=True) if color == 100), bodies[0])
    rgba = decode_webp_source(baseline, source_mime="image/webp", expected_dimensions=(16, 16)).rgba
    if verified_count is None and status == "source-pixel-equivalence-failed":
        rgba = bytes([100, 100, 100, 255]) * 256
    reference = ReferencePixels(16, 16, rgba)
    kwargs = {
        "expected_dimensions": (16, 16), "target_dimensions": (16, 16),
        "rois": [[0, 0, 16, 16, 0, 0, 16, 16]],
        "first_reference": reference, "second_reference": reference,
    }
    if verified_count is None:
        with pytest.raises(SourceCaptureProofError, match=status):
            select_source_roi_candidate(cohort, **kwargs)
    else:
        candidate, comparison, facts = select_source_roi_candidate(cohort, **kwargs)
        assert comparison.passed
        assert candidate.rgba == rgba
        assert facts.candidate_count == 2
        assert facts.verified_candidate_count == verified_count
        assert facts.selection_status == status
    cohort.validate(ledger, SOURCE_URL)
    assert reads == [0, 1]  # validation never rereads a body
