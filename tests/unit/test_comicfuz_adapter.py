from __future__ import annotations

import asyncio
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image

from screenshot_crawler.core.errors import UnknownPageStateError, UnsupportedAccessStrategyError
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
    unlinked_extra = {**extra, "has_link": False}
    triple = [image.copy(), image.copy(), extra, unlinked_extra, extra.copy(),
              {"role": "google_ads"}, {"role": "last_page"}]
    assert _classify_viewer_pages(triple) == ((0, 1), 2)

    invalid = [
        [image.copy(), {**image, "has_link": True}, {"role": "google_ads"}, {"role": "last_page"}],
        [image.copy(), extra, image.copy(), {"role": "google_ads"}, {"role": "last_page"}],
        [image.copy(), extra, extra, {"role": "google_ads"}, {"role": "last_page"}],
        [image.copy(), extra, {"role": "last_page"}, {"role": "google_ads"}],
        [image.copy(), {**extra, "link_metadata_valid": False}, {"role": "google_ads"}, {"role": "last_page"}],
        [image.copy(), extra, {"role": "unknown"}, {"role": "last_page"}],
        [image.copy(), unlinked_extra, {"role": "google_ads"}, {"role": "last_page"}],
        [image.copy(), extra, unlinked_extra, {"role": "google_ads"}, {"role": "last_page"}],
        [image.copy(), extra, extra, extra, {"role": "google_ads"}, {"role": "last_page"}],
        [image.copy(), extra, unlinked_extra, image.copy(),
         {"role": "google_ads"}, {"role": "last_page"}],
    ]
    for candidate in invalid:
        with pytest.raises(UnknownPageStateError):
            _classify_viewer_pages(candidate)
    assert (
        capture_comicfuz_source_bytes(b"not a jpeg", expected_width=19, expected_height=31) is None
    )


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
async def test_comicfuz_rejects_quota_or_resource_strategies() -> None:
    adapter = ComicFuzAdapter()
    with pytest.raises(UnsupportedAccessStrategyError):
        await adapter.configure_run(None, "quota")  # type: ignore[arg-type]
    with pytest.raises(UnsupportedAccessStrategyError):
        await adapter.configure_quota_resource(None, "ticket")  # type: ignore[arg-type]


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
