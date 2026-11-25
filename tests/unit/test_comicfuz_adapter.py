from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image

from screenshot_crawler.core.errors import UnknownPageStateError, UnsupportedAccessStrategyError
from screenshot_crawler.site_adapters.base import AccessConsumption
from screenshot_crawler.site_adapters.comicfuz import ComicFuzAdapter
from screenshot_crawler.site_adapters.comicfuz.access import comicfuz_access_profile
from screenshot_crawler.site_adapters.comicfuz.adapter import _classify_viewer_pages
from screenshot_crawler.site_adapters.comicfuz.native_capture import (
    capture_comicfuz_source_bytes,
)


def _jpeg_bytes() -> bytes:
    image = Image.new("RGB", (19, 31), color=(23, 97, 181))
    output = BytesIO()
    image.save(output, format="JPEG", quality=92)
    return output.getvalue()


def test_comicfuz_source_capture_preserves_only_matching_complete_jpeg() -> None:
    source = _jpeg_bytes()
    capture = capture_comicfuz_source_bytes(source, expected_width=19, expected_height=31)
    assert capture is not None
    assert capture.data == source
    assert (capture.width, capture.height) == (19, 31)
    assert capture.mime_type == "image/jpeg"
    assert capture.file_extension == ".jpg"

    assert capture_comicfuz_source_bytes(source, expected_width=20, expected_height=31) is None
    assert (
        capture_comicfuz_source_bytes(source[:-15], expected_width=19, expected_height=31) is None
    )


def test_comicfuz_page_roles_accept_only_observed_body_extra_tail_shape() -> None:
    image = {"role": "image", "is_extra": None, "has_link": False,
             "link_metadata_valid": True, "width": 1353, "height": 1920}
    extra = {"role": "image", "is_extra": True, "has_link": True,
             "link_metadata_valid": True, "width": 750, "height": 1334}
    pages = [image.copy(), image.copy(), extra, {"role": "google_ads"}, {"role": "last_page"}]

    assert _classify_viewer_pages(pages) == ((0, 1), 2)
    assert _classify_viewer_pages(
        [image.copy(), {"role": "google_ads"}, {"role": "last_page"}]
    ) == ((0,), None)
    assert _classify_viewer_pages(
        [*[image.copy() for _ in range(11)], {"role": "google_ads"}, {"role": "last_page"}]
    ) == (tuple(range(11)), None)
    unlinked_extra = {**extra, "has_link": False}
    triple = [image.copy(), image.copy(), extra, unlinked_extra, extra.copy(),
              {"role": "google_ads"}, {"role": "last_page"}]
    assert _classify_viewer_pages(triple) == ((0, 1), 2)
    unlinked_pair_tail = [
        *[image.copy() for _ in range(12)],
        unlinked_extra.copy(), unlinked_extra.copy(), extra.copy(),
        {"role": "google_ads"}, {"role": "last_page"},
    ]
    assert _classify_viewer_pages(unlinked_pair_tail) == (tuple(range(12)), 12)
    linked_pair_tail = [
        *[image.copy() for _ in range(11)],
        extra.copy(), extra.copy(), {"role": "google_ads"}, {"role": "last_page"},
    ]
    assert _classify_viewer_pages(linked_pair_tail) == (tuple(range(11)), 11)
    assert _classify_viewer_pages([image.copy(), *linked_pair_tail]) == (tuple(range(12)), 12)

    invalid = [
        [{"role": "google_ads"}, {"role": "last_page"}],
        [image.copy(), {"role": "last_page"}, {"role": "google_ads"}],
        [image.copy(), {"role": "google_ads"}, {"role": "last_page"}, image.copy()],
        [image.copy(), {**image, "has_link": True}, {"role": "google_ads"}, {"role": "last_page"}],
        [image.copy(), extra, image.copy(), {"role": "google_ads"}, {"role": "last_page"}],
        [image.copy(), extra, extra, {"role": "google_ads"}, {"role": "last_page"}],
        linked_pair_tail[9:],
        [image.copy(), extra, {"role": "last_page"}, {"role": "google_ads"}],
        [image.copy(), {**extra, "link_metadata_valid": False}, {"role": "google_ads"}, {"role": "last_page"}],
        [image.copy(), extra, {"role": "unknown"}, {"role": "last_page"}],
        [image.copy(), unlinked_extra, {"role": "google_ads"}, {"role": "last_page"}],
        [image.copy(), extra, unlinked_extra, {"role": "google_ads"}, {"role": "last_page"}],
        [image.copy(), extra, extra, extra, {"role": "google_ads"}, {"role": "last_page"}],
        [image.copy(), extra, unlinked_extra, image.copy(),
         {"role": "google_ads"}, {"role": "last_page"}],
        [image.copy(), unlinked_extra, extra.copy(),
         {"role": "google_ads"}, {"role": "last_page"}],
        [image.copy(), unlinked_extra, unlinked_extra, unlinked_extra, extra.copy(),
         {"role": "google_ads"}, {"role": "last_page"}],
    ]
    for candidate in invalid:
        with pytest.raises(UnknownPageStateError):
            _classify_viewer_pages(candidate)
    assert (
        capture_comicfuz_source_bytes(b"not a jpeg", expected_width=19, expected_height=31) is None
    )


@pytest.mark.parametrize(("body_count", "first_page_blank"), [(11, False), (12, True)])
def test_comicfuz_linked_extra_pair_requires_final_mixed_spread_and_extra_advance(
    body_count: int, first_page_blank: bool,
) -> None:
    adapter = ComicFuzAdapter()
    adapter._body_page_indices = tuple(range(body_count))
    adapter._extra_page_index = body_count
    adapter._is_first_page_blank = first_page_blank
    adapter._viewer_pages = [
        *[{} for _ in range(body_count)],
        *[{"role": "image", "is_extra": True, "has_link": True} for _ in range(2)],
        {"role": "google_ads"}, {"role": "last_page"},
    ]
    adapter._last_rendered_group = (body_count - 1, body_count)
    adapter._last_captured_group = (body_count - 1,)
    adapter._captured_indices = list(range(body_count - 1))
    assert adapter._expected_extra_tail_group() == ()

    adapter._captured_indices.append(body_count - 1)
    assert adapter._expected_extra_tail_group() == (body_count + 1,)
    with pytest.raises(UnknownPageStateError, match="skipped the final linked extra"):
        adapter._require_linked_extra_pair_end()
    adapter._require_extra_tail_sequence([{"number": body_count + 1, "role": "linked_extra"}])
    with pytest.raises(UnknownPageStateError, match="extra tail is out of sequence"):
        adapter._require_extra_tail_sequence([{"number": body_count, "role": "linked_extra"}])

    adapter._last_rendered_group = (body_count + 1,)
    adapter._advanced_extra_groups = ((body_count + 1,),)
    adapter._require_linked_extra_pair_end()
    assert adapter._expected_extra_tail_group() == ()


def test_comicfuz_unlinked_pair_tail_requires_exact_manifest_and_capture_history() -> None:
    image = {"role": "image", "is_extra": None, "has_link": False,
             "link_metadata_valid": True, "width": 1351, "height": 1920}
    unlinked = {"role": "image", "is_extra": True, "has_link": False,
                "link_metadata_valid": True, "width": 1359, "height": 1920}
    linked = {"role": "image", "is_extra": True, "has_link": True,
              "link_metadata_valid": True, "width": 750, "height": 1334}
    manifest = [
        *[image.copy() for _ in range(12)],
        unlinked.copy(), unlinked.copy(), linked.copy(),
        {"role": "google_ads"}, {"role": "last_page"},
    ]
    body_indices, extra_index = _classify_viewer_pages(manifest)
    adapter = ComicFuzAdapter()
    adapter._viewer_pages = manifest
    adapter._body_page_indices = body_indices
    adapter._extra_page_index = extra_index
    adapter._is_first_page_blank = True
    adapter._initial_body_indices = (0,)

    body_plus_unlinked = [
        {"number": 11, "alt": "page_11", "role": "body", "width": 1351, "height": 1920},
        {"number": 12, "alt": "page_12", "role": "unlinked_extra", "width": 1359, "height": 1920},
    ]
    adapter._captured_indices = []
    with pytest.raises(UnknownPageStateError, match="final body page"):
        adapter._validate_page_group(body_plus_unlinked)
    adapter._validate_page_group(body_plus_unlinked, allow_initial_rewind=True)
    adapter._initialized = True
    with pytest.raises(UnknownPageStateError, match="final body page"):
        adapter._validate_page_group(body_plus_unlinked, allow_initial_rewind=True)
    adapter._initialized = False
    adapter._captured_indices = [0]
    with pytest.raises(UnknownPageStateError, match="final body page"):
        adapter._validate_page_group(body_plus_unlinked, allow_initial_rewind=True)
    adapter._captured_indices = list(range(11))
    adapter._validate_page_group(body_plus_unlinked)
    adapter._captured_indices = list(range(12))
    adapter._last_captured_group = (11,)
    adapter._last_rendered_group = (11, 12)
    adapter._validate_page_group(body_plus_unlinked)

    mixed_tail_group = [
        {"number": 13, "alt": "page_13", "role": "unlinked_extra", "width": 1359, "height": 1920},
        {"number": 14, "alt": "page_14", "role": "linked_extra", "width": 750, "height": 1334},
    ]
    assert adapter._expected_extra_tail_group() == (13, 14)
    adapter._validate_page_group(mixed_tail_group)
    adapter._require_extra_tail_sequence(mixed_tail_group)

    unlinked_pair = [
        {"number": 12, "alt": "page_12", "role": "unlinked_extra", "width": 1359, "height": 1920},
        {"number": 13, "alt": "page_13", "role": "unlinked_extra", "width": 1359, "height": 1920},
    ]
    adapter._captured_indices = []
    with pytest.raises(UnknownPageStateError, match="expected post-body tail group"):
        adapter._validate_page_group(unlinked_pair)
    adapter._validate_page_group(unlinked_pair, allow_initial_rewind=True)
    adapter._initialized = True
    with pytest.raises(UnknownPageStateError, match="expected post-body tail group"):
        adapter._validate_page_group(unlinked_pair, allow_initial_rewind=True)
    adapter._initialized = False
    adapter._captured_indices = [0]
    with pytest.raises(UnknownPageStateError, match="expected post-body tail group"):
        adapter._validate_page_group(unlinked_pair, allow_initial_rewind=True)
    adapter._last_captured_group = (10, 11)
    adapter._last_rendered_group = (10, 11)
    adapter._captured_indices = list(range(12))
    adapter._validate_page_group(unlinked_pair)
    adapter._require_extra_tail_sequence(unlinked_pair)

    skipped_extra = mixed_tail_group
    with pytest.raises(UnknownPageStateError, match="extra tail is out of sequence"):
        adapter._require_extra_tail_sequence(skipped_extra)

    adapter._captured_indices = list(range(11))
    with pytest.raises(UnknownPageStateError, match="expected post-body tail group"):
        adapter._validate_page_group(unlinked_pair)

    adapter._captured_indices = list(range(10))
    with pytest.raises(UnknownPageStateError, match="final body page"):
        adapter._validate_page_group(body_plus_unlinked)


@pytest.mark.asyncio
async def test_comicfuz_initial_route_requires_same_work_public_listing() -> None:
    adapter = ComicFuzAdapter(
        preflight_work_url="https://comic-fuz.com/manga/1970?position=thumbnail"
    )
    await adapter.configure_target_identity("1970:80641", "comicfuz:1970")
    assert (
        adapter.resolve_initial_navigation_url("https://comic-fuz.com/manga/viewer/80641")
        == "https://comic-fuz.com/manga/1970?position=thumbnail"
    )

    with pytest.raises(UnknownPageStateError):
        adapter.resolve_initial_navigation_url("https://comic-fuz.com/manga/viewer/1")

    mismatched = ComicFuzAdapter(preflight_work_url="https://comic-fuz.com/manga/999")
    await mismatched.configure_target_identity("1970:80641", "comicfuz:1970")
    with pytest.raises(UnknownPageStateError):
        mismatched.resolve_initial_navigation_url("https://comic-fuz.com/manga/viewer/80641")


@pytest.mark.asyncio
async def test_comicfuz_accepts_quota_only_for_work_ticket() -> None:
    adapter = ComicFuzAdapter()
    with pytest.raises(UnsupportedAccessStrategyError):
        await adapter.configure_run(None, "premium_ticket")  # type: ignore[arg-type]
    with pytest.raises(UnsupportedAccessStrategyError):
        await adapter.configure_quota_resource(None, "work_ticket")  # type: ignore[arg-type]

    await adapter.configure_run(None, "quota")  # type: ignore[arg-type]
    with pytest.raises(UnsupportedAccessStrategyError):
        await adapter.configure_quota_resource(None, "ticket")  # type: ignore[arg-type]
    await adapter.configure_target_identity("3667:76630", "houkago-basket")
    await adapter.configure_quota_resource(None, "work_ticket")  # type: ignore[arg-type]
    assert adapter._quota_resource == "work_ticket"


@pytest.mark.asyncio
async def test_comicfuz_configure_run_resets_ticket_state_and_keeps_candidate_bindings() -> None:
    adapter = ComicFuzAdapter()
    await adapter.configure_target_identity("3667:76630", "houkago-basket")
    grant_until = datetime.now(UTC) + timedelta(hours=1)
    adapter.configure_existing_access_grant(grant_until)
    attempt_observer = lambda observation: None
    grant_observer = lambda grant: None
    adapter.set_access_attempt_observer(attempt_observer)
    adapter.set_confirmed_access_grant_observer(grant_observer)
    adapter._quota_resource = "work_ticket"
    adapter._ticket_entry = object()  # type: ignore[assignment]
    adapter._ticket_entry_confirmed = True
    adapter._access_consumption = AccessConsumption(
        consumed=True,
        resource="work_ticket",
        consumed_at=datetime.now(UTC),
    )

    await adapter.configure_run(None, "direct")  # type: ignore[arg-type]

    assert adapter._work_id == "3667" and adapter._chapter_id == "76630"
    assert adapter._existing_access_grant_until == grant_until
    assert adapter._access_attempt_observer is attempt_observer
    assert adapter._confirmed_access_grant_observer is grant_observer
    assert adapter._quota_resource is None
    assert adapter._ticket_entry is None
    assert adapter._ticket_entry_confirmed is False
    assert adapter.get_access_consumption().consumed is False


def test_comicfuz_access_profile_includes_first_party_api_host() -> None:
    profile = comicfuz_access_profile()
    assert profile.relevant_host("https://api.comic-fuz.com/v1/public")
    assert profile.relevant_host("https://img.comic-fuz.com/page.jpg")
    assert not profile.relevant_host("https://not-comic-fuz.com/page.jpg")
    assert not profile.relevant_host("http://api.comic-fuz.com/v1/public")


@pytest.mark.asyncio
async def test_comicfuz_hung_source_reads_are_bounded_and_cleaned_up() -> None:
    adapter = ComicFuzAdapter()
    adapter.source_response_timeout_ms = 10
    adapter.source_response_retries = 1
    source_url = "blob:https://comic-fuz.com/opaque-source"

    class HangingResponse:
        url = source_url
        request = SimpleNamespace(resource_type="image")

        def __init__(self) -> None:
            self.calls = 0

        async def body(self) -> bytes:
            self.calls += 1
            await asyncio.Event().wait()
            return b"unreachable"

    response = HangingResponse()
    adapter._handle_source_response(response)

    assert await adapter._source_bytes_for(source_url) is None
    assert response.calls <= 2
    assert source_url not in adapter._source_response_tasks
    assert source_url not in adapter._source_responses
    assert all(task.done() for task in adapter._source_response_tasks.values())


@pytest.mark.asyncio
async def test_comicfuz_prefetched_source_body_has_an_internal_deadline() -> None:
    adapter = ComicFuzAdapter()
    adapter.source_response_timeout_ms = 10
    adapter.source_response_retries = 0
    source_url = "blob:https://comic-fuz.com/background-read"

    class HangingResponse:
        url = source_url
        request = SimpleNamespace(resource_type="image")

        async def body(self) -> bytes:
            await asyncio.Event().wait()
            return b"unreachable"

    adapter._handle_source_response(HangingResponse())
    task = adapter._source_response_tasks[source_url]
    done, pending = await asyncio.wait({task}, timeout=0.2)

    assert done == {task}
    assert not pending
    assert task.result() is None
    await asyncio.sleep(0)
    assert source_url not in adapter._source_response_tasks
    assert source_url not in adapter._source_responses


def test_comicfuz_source_response_declared_oversize_is_discarded() -> None:
    adapter = ComicFuzAdapter()
    response = SimpleNamespace(
        url="blob:https://comic-fuz.com/oversize",
        request=SimpleNamespace(resource_type="image"),
        headers={"content-length": str(adapter.max_source_response_bytes + 1)},
    )

    adapter._handle_source_response(response)

    assert not adapter._source_responses
    assert not adapter._source_response_tasks
