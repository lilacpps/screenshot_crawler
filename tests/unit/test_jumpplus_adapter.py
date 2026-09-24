from __future__ import annotations

import asyncio
import io
from types import SimpleNamespace

import pytest
from PIL import Image

from screenshot_crawler import cli
from screenshot_crawler.core.capture import CaptureResult
from screenshot_crawler.core.errors import PageChangeTimeoutError, UnsupportedAccessStrategyError
from screenshot_crawler.core.models import ContentIdentity
from screenshot_crawler.site_adapters.jumpplus import adapter as jumpplus_adapter_module
from screenshot_crawler.site_adapters.jumpplus.access import is_jumpplus_relevant_host
from screenshot_crawler.site_adapters.jumpplus.adapter import _CANVAS_HOOK, JumpPlusAdapter
from screenshot_crawler.site_adapters.jumpplus.native_capture import (
    dct_lossless_feasibility,
    is_jumpplus_jpeg_response,
    jpeg_dimensions,
    parse_jumpplus_url,
    reconstruct_jpeg_lossless,
    reconstruct_jpeg_png,
    select_transport_candidate,
)


def _response(url: str, *, content_type: str = "image/jpeg", resource_type: str = "image"):
    return SimpleNamespace(
        url=url,
        headers={"content-type": content_type},
        request=SimpleNamespace(resource_type=resource_type),
    )


def _mapping(*, source: str = "blob:test", sx: int = 0, sy: int = 0, sw: int = 16, sh: int = 16, dx: int = 0, dy: int = 0, **overrides):
    value = {
        "sourcePath": source,
        "sourceWidth": 16,
        "sourceHeight": 16,
        "canvasWidth": 16,
        "canvasHeight": 16,
        "sx": sx,
        "sy": sy,
        "sw": sw,
        "sh": sh,
        "dx": dx,
        "dy": dy,
        "dw": sw,
        "dh": sh,
        "transform": {"a": 1, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0},
        "globalCompositeOperation": "source-over",
        "filter": "none",
        "globalAlpha": 1,
    }
    value.update(overrides)
    return value


def _jpeg_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90, subsampling=0)
    return buffer.getvalue()


def _source_png_with_delta(jpeg_data: bytes, delta: int, *, size: tuple[int, int] | None = None) -> bytes:
    with Image.open(io.BytesIO(jpeg_data)) as image:
        source = image.convert("RGB")
    if size is not None:
        source = source.resize(size)
    source = Image.eval(source, lambda value: min(255, value + delta))
    buffer = io.BytesIO()
    source.save(buffer, format="PNG")
    return buffer.getvalue()


def test_jumpplus_url_parsing_and_host_profile() -> None:
    assert parse_jumpplus_url("https://shonenjumpplus.com/episode/123") is not None
    assert parse_jumpplus_url("https://www.shonenjumpplus.com/episode/123?x=1").episode_id == "123"
    assert parse_jumpplus_url("https://example.test/episode/123") is None
    assert parse_jumpplus_url("https://shonenjumpplus.com/work/123") is None
    assert is_jumpplus_relevant_host("https://cdn-ak-img.shonenjumpplus.com/public/page/1.jpg")
    assert is_jumpplus_relevant_host("https://cdn-ak.shonenjumpplus.com/public/page/1.jpg")
    assert not is_jumpplus_relevant_host("https://cdn.example.test/public/page/1.jpg")
    assert parse_jumpplus_url("https://shonenjumpplus.com/episode/") is None
    assert parse_jumpplus_url("https://shonenjumpplus.com/episode/123/extra") is None


def test_jumpplus_transport_response_classification() -> None:
    accepted = _response("https://cdn-ak-img.shonenjumpplus.com/public/page/2/abc.jpg")
    assert is_jumpplus_jpeg_response(accepted)
    assert is_jumpplus_jpeg_response(_response(accepted.url, resource_type="fetch"))
    assert is_jumpplus_jpeg_response(_response(accepted.url, resource_type="other"))
    assert not is_jumpplus_jpeg_response(_response(accepted.url, content_type="", resource_type="other"))
    assert not is_jumpplus_jpeg_response(_response("https://example.test/public/page/2/a.jpg"))
    assert not is_jumpplus_jpeg_response(_response(accepted.url, content_type="image/png"))
    assert not is_jumpplus_jpeg_response(_response(accepted.url, resource_type="script"))
    assert not is_jumpplus_jpeg_response("not-a-response")


def test_j21_candidate_selection_is_fail_closed() -> None:
    one = {"pixel_sha256": "p", "data": b"one"}
    assert select_transport_candidate("p", [one])["selection_status"] == "unique"
    raw_duplicates = [{"pixel_sha256": "p", "data": b"same"}, {"pixel_sha256": "p", "data": b"same"}]
    assert select_transport_candidate("p", raw_duplicates, load_bytes=lambda item: item["data"])["selection_status"] == "equivalent_multiple"
    distinct = [{"pixel_sha256": "p", "data": b"one"}, {"pixel_sha256": "p", "data": b"two"}]
    result = select_transport_candidate(
        "p",
        distinct,
        load_bytes=lambda item: item["data"],
        analyze_candidate=lambda item, data: {"content_key": (data,), "metadata_key": ()},
    )
    assert result["selection_status"] == "ambiguous"
    assert result["pixel_fallback_candidate"] is distinct[0]
    assert select_transport_candidate("missing", [one])["selection_status"] == "unmatched"


def test_j21_raw_sha256_match_precedes_pixel_matching() -> None:
    candidate = {"raw_sha256": "raw", "pixel_sha256": "different", "data": b"not-an-image"}
    result = select_transport_candidate(
        "missing",
        [candidate],
        source_raw_sha256="raw",
        source_data=b"not-an-image",
    )
    assert result["selection_status"] == "unique"
    assert result["selection_reason"] == "single_raw_sha256"
    assert result["selected_candidate"] is candidate


def test_j21_decoder_tolerant_pixel_match_accepts_maximum_difference_two() -> None:
    image = Image.new("RGB", (8, 8), (40, 80, 120))
    candidate_data = _jpeg_bytes(image)
    source_data = _source_png_with_delta(candidate_data, 2)
    result = select_transport_candidate(
        "missing",
        [{"raw_sha256": "candidate", "pixel_sha256": "different", "data": candidate_data}],
        source_data=source_data,
        load_bytes=lambda item: item["data"],
    )
    assert result["selection_status"] == "unique"
    assert result["selection_reason"] == "single_decoder_tolerant_pixel_match"


def test_j21_decoder_tolerant_pixel_match_rejects_difference_above_two() -> None:
    image = Image.new("RGB", (8, 8), (40, 80, 120))
    candidate_data = _jpeg_bytes(image)
    source_data = _source_png_with_delta(candidate_data, 3)
    result = select_transport_candidate(
        "missing",
        [{"raw_sha256": "candidate", "pixel_sha256": "different", "data": candidate_data}],
        source_data=source_data,
        load_bytes=lambda item: item["data"],
    )
    assert result["selection_status"] == "unmatched"
    assert result["selected_candidate"] is None


def test_j21_decoder_tolerant_pixel_match_rejects_size_mismatch() -> None:
    source_image = Image.new("RGB", (8, 8), (40, 80, 120))
    candidate_data = _jpeg_bytes(Image.new("RGB", (4, 4), (40, 80, 120)))
    source_buffer = io.BytesIO()
    source_image.save(source_buffer, format="PNG")
    result = select_transport_candidate(
        "missing",
        [{"raw_sha256": "candidate", "pixel_sha256": "different", "data": candidate_data}],
        source_data=source_buffer.getvalue(),
        load_bytes=lambda item: item["data"],
    )
    assert result["selection_status"] == "unmatched"


def test_j21_decoder_tolerant_pixel_match_is_ambiguous_for_multiple_candidates() -> None:
    image = Image.new("RGB", (8, 8), (40, 80, 120))
    candidate_data = _jpeg_bytes(image)
    source_data = _source_png_with_delta(candidate_data, 1)
    candidates = [
        {"raw_sha256": "one", "pixel_sha256": "different-one", "data": candidate_data},
        {"raw_sha256": "two", "pixel_sha256": "different-two", "data": candidate_data},
    ]
    result = select_transport_candidate(
        "missing",
        candidates,
        source_data=source_data,
        load_bytes=lambda item: item["data"],
    )
    assert result["selection_status"] == "ambiguous"
    assert result["selection_reason"] == "multiple_decoder_tolerant_pixel_matches"
    assert result["selected_candidate"] is None


def test_dct_feasibility_rejects_misalignment_and_reconstruction_preserves_jpeg() -> None:
    image = Image.new("RGB", (16, 16), "white")
    for y in range(16):
        for x in range(16):
            image.putpixel((x, y), ((x * 13) % 256, (y * 17) % 256, (x + y) % 256))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90, subsampling=0)
    data = buffer.getvalue()
    assert jpeg_dimensions(data) == (16, 16)
    assert dct_lossless_feasibility(
        jpeg_bytes=data,
        source_rectangles=[(1, 0, 8, 8)],
        destination_rectangles=[(0, 0, 8, 8)],
        canvas_size=(16, 16),
    )["status"] == "infeasible"
    source = "blob:test"
    base = _mapping(source=source)
    visible = _mapping(source=source)
    tiles = [
        _mapping(source=source, sx=0, sy=0, sw=16, sh=8, dx=0, dy=8, sequence=1),
        _mapping(source=source, sx=0, sy=8, sw=16, sh=8, dx=0, dy=0, sequence=2),
    ]
    jpeg = reconstruct_jpeg_lossless(data, base=base, mappings=tiles, visible_draw=visible, source_path=source, canvas_size=(16, 16))
    png = reconstruct_jpeg_png(data, base=base, mappings=tiles, visible_draw=visible, source_path=source, canvas_size=(16, 16))
    assert jpeg is not None and jpeg.mime_type == "image/jpeg" and jpeg.file_extension == ".jpg"
    assert png is not None and png.mime_type == "image/png" and png.file_extension == ".png"


@pytest.mark.asyncio
async def test_jumpplus_access_rejects_quota_and_resource() -> None:
    adapter = JumpPlusAdapter()
    await adapter.configure_run(object(), "auto")  # type: ignore[arg-type]
    await adapter.configure_run(object(), "direct")  # type: ignore[arg-type]
    with pytest.raises(UnsupportedAccessStrategyError):
        await adapter.configure_run(object(), "quota")  # type: ignore[arg-type]
    with pytest.raises(UnsupportedAccessStrategyError):
        await adapter.configure_quota_resource(object(), "points")  # type: ignore[arg-type]


def test_jumpplus_registry_entry_has_policy_without_resources() -> None:
    assert isinstance(cli._registry().create("jumpplus"), JumpPlusAdapter)
    assert "jumpplus" in cli._discovery_registry().sites()
    policy = cli._batch_policy_registry().create("jumpplus")
    assert "jumpplus" in cli._batch_policy_registry().sites()
    assert policy.supported_access_resources() == ()
    assert policy.grant_only_supported_access_resources() == ()


def test_jumpplus_renderer_hook_is_lightweight_and_tracks_mutations() -> None:
    for marker in ("sourceId", "drawImage", "snapshotSources", "clearRect", "fillRect", "putImageData", "strokeText"):
        assert marker in _CANVAS_HOOK
    assert JumpPlusAdapter._native_candidate_status("unique")
    assert JumpPlusAdapter._native_candidate_status("equivalent_multiple")
    assert not JumpPlusAdapter._native_candidate_status("ambiguous")


def test_capture_result_extensions_match_native_provenance() -> None:
    assert CaptureResult(b"x", 1, 1, "image/jpeg", ".jpg").file_extension == ".jpg"


class _FakePage:
    url = "https://shonenjumpplus.com/episode/123"

    def locator(self, _selector: str):
        return SimpleNamespace(nth=lambda _index: object())

    async def wait_for_timeout(self, _milliseconds: int) -> None:
        return None


async def _completed_task(value: object = None) -> object:
    return value


def _seed_source_cache(adapter: JumpPlusAdapter, urls: list[str]) -> None:
    for url in urls:
        adapter._source_responses[url] = object()
        adapter._source_tasks[url] = asyncio.create_task(_completed_task())  # type: ignore[assignment]


@pytest.mark.asyncio
async def test_capture_fallback_releases_used_source_but_retains_prefetch_cache(monkeypatch) -> None:
    adapter = JumpPlusAdapter()
    page = _FakePage()
    _seed_source_cache(adapter, ["page1.jpg", "page2.jpg", "page3.jpg"])

    async def rows(_page):
        return [{"index": 0, "pageIndex": 2}]

    async def candidates():
        return []

    async def native(_page, _rows, _candidates):
        return None, "safe_pixel_reconstruction_unavailable", ["ambiguous"], {"page1.jpg"}

    async def screenshot(_target):
        return CaptureResult(b"screen", 1, 1, "image/png", ".png")

    monkeypatch.setattr(adapter, "_rows", rows)
    monkeypatch.setattr(adapter, "_source_candidates", candidates)
    monkeypatch.setattr(adapter, "_native_attempt", native)
    monkeypatch.setattr(jumpplus_adapter_module, "capture_locator", screenshot)

    result = await adapter.capture_page(page)  # type: ignore[arg-type]

    assert result is not None
    assert "page1.jpg" not in adapter._source_responses
    assert {"page2.jpg", "page3.jpg"} <= set(adapter._source_responses)
    await adapter._discard_sources()


@pytest.mark.asyncio
async def test_screenshot_fallback_without_used_candidate_keeps_prefetch_cache(monkeypatch) -> None:
    adapter = JumpPlusAdapter()
    page = _FakePage()
    _seed_source_cache(adapter, ["page2.jpg", "page3.jpg"])

    async def rows(_page):
        return [{"index": 0, "pageIndex": 2}]

    async def candidates():
        return []

    async def native(_page, _rows, _candidates):
        return None, "unmatched_transport_candidate", ["unmatched"], set()

    async def screenshot(_target):
        return CaptureResult(b"screen", 1, 1, "image/png", ".png")

    monkeypatch.setattr(adapter, "_rows", rows)
    monkeypatch.setattr(adapter, "_source_candidates", candidates)
    monkeypatch.setattr(adapter, "_native_attempt", native)
    monkeypatch.setattr(jumpplus_adapter_module, "capture_locator", screenshot)

    await adapter.capture_page(page)  # type: ignore[arg-type]

    assert {"page2.jpg", "page3.jpg"} <= set(adapter._source_responses)
    await adapter._discard_sources()


def _patch_initialize_dependencies(monkeypatch, adapter: JumpPlusAdapter, rows):
    async def page_count(_page):
        return None

    async def metadata(_page):
        return None

    async def ready(_page):
        return rows

    monkeypatch.setattr(adapter, "_read_content_page_count", page_count)
    monkeypatch.setattr(adapter, "_read_output_metadata", metadata)
    monkeypatch.setattr(adapter, "_wait_for_render_ready", ready)


@pytest.mark.asyncio
async def test_initialize_waits_for_content_without_startup_forward(monkeypatch) -> None:
    adapter = JumpPlusAdapter()
    page = _FakePage()
    rows = [{"pageIndex": 2}]
    calls = []
    _patch_initialize_dependencies(monkeypatch, adapter, rows)

    async def initial_state(_page):
        return "content", rows

    async def rewind(_page):
        calls.append("rewind")
        return True

    async def forward(_page):
        calls.append("forward")

    monkeypatch.setattr(adapter, "_wait_for_initial_viewer_state", initial_state)
    monkeypatch.setattr(adapter, "_rewind_to_first", rewind)
    monkeypatch.setattr(adapter, "go_next", forward)

    await adapter.initialize(page)  # type: ignore[arg-type]

    assert calls == ["rewind"]


@pytest.mark.asyncio
async def test_initialize_start_state_forwards_once_and_guarantees_first_content(monkeypatch) -> None:
    adapter = JumpPlusAdapter()
    page = _FakePage()
    rows = [{"pageIndex": 2}]
    calls = []
    _patch_initialize_dependencies(monkeypatch, adapter, rows)

    async def initial_state(_page):
        return "start", []

    async def forward(_page):
        calls.append("forward")

    async def rewind(_page):
        calls.append("rewind")
        adapter._first_content_page_index = 2
        return True

    monkeypatch.setattr(adapter, "_wait_for_initial_viewer_state", initial_state)
    monkeypatch.setattr(adapter, "go_next", forward)
    monkeypatch.setattr(adapter, "_rewind_to_first", rewind)

    await adapter.initialize(page)  # type: ignore[arg-type]

    assert calls == ["forward", "rewind"]


@pytest.mark.asyncio
async def test_initial_start_waits_for_mounted_content_hint(monkeypatch) -> None:
    adapter = JumpPlusAdapter()

    class _MountedContentPage:
        async def evaluate(self, _script):
            return True

        async def wait_for_timeout(self, _milliseconds: int) -> None:
            return None

    page = _MountedContentPage()
    calls = 0

    async def rows(_page):
        nonlocal calls
        calls += 1
        return [] if calls == 1 else [{"pageIndex": 1}]

    async def initial_state(_page):
        return "start"

    monkeypatch.setattr(adapter, "_rows", rows)
    monkeypatch.setattr(adapter, "_initial_viewer_state", initial_state)

    state, result = await adapter._wait_for_initial_viewer_state(page)  # type: ignore[arg-type]

    assert state == "content"
    assert result == [{"pageIndex": 1}]


@pytest.mark.asyncio
async def test_initialize_unknown_state_fails_closed_without_forward(monkeypatch) -> None:
    adapter = JumpPlusAdapter()
    page = _FakePage()
    calls = []

    async def page_count(_page):
        return None

    async def initial_state(_page):
        raise PageChangeTimeoutError("unknown")

    async def forward(_page):
        calls.append("forward")

    monkeypatch.setattr(adapter, "_read_content_page_count", page_count)
    monkeypatch.setattr(adapter, "_wait_for_initial_viewer_state", initial_state)
    monkeypatch.setattr(adapter, "go_next", forward)

    with pytest.raises(PageChangeTimeoutError):
        await adapter.initialize(page)  # type: ignore[arg-type]
    assert calls == []


def test_runtime_content_boundaries_support_front_link_and_index_zero_layouts() -> None:
    adapter = JumpPlusAdapter()

    adapter._first_content_page_index = 2
    adapter._content_page_count = 65
    assert adapter._content_end_index() == 66

    adapter._first_content_page_index = 0
    adapter._content_page_count = 23
    assert adapter._content_end_index() == 22

    adapter._content_page_count = 27
    assert adapter._content_end_index() == 26


def test_runtime_terminal_contract_requires_count_and_end_index() -> None:
    adapter = JumpPlusAdapter()
    adapter._first_content_page_index = 0
    adapter._content_page_count = 23
    adapter._last_active_max_page_index = 22

    adapter._captured_content_page_count = 22
    assert not adapter._all_main_content_captured()

    adapter._captured_content_page_count = 23
    assert adapter._all_main_content_captured()

    adapter._last_active_max_page_index = 21
    assert not adapter._all_main_content_captured()


def test_runtime_terminal_contract_supports_spread_end_index() -> None:
    adapter = JumpPlusAdapter()
    adapter._first_content_page_index = 2
    adapter._content_page_count = 10
    adapter._captured_content_page_count = 10
    adapter._last_active_max_page_index = 11

    assert adapter._content_end_index() == 11
    assert adapter._all_main_content_captured()


class _Control:
    def __init__(self) -> None:
        self.click_count = 0

    async def click(self, **_kwargs) -> None:
        self.click_count += 1

    async def count(self) -> int:
        return 0

    async def is_visible(self) -> bool:
        return False

    async def inner_text(self) -> str:
        return ""

    async def get_attribute(self, name: str) -> str | None:
        return None if name != "class" else "page-navigation-forward js-slide-forward"


class _ControlPage:
    url = "https://shonenjumpplus.com/episode/123"

    def __init__(self) -> None:
        self.control = _Control()

    def locator(self, _selector: str):
        return self.control

    async def wait_for_timeout(self, _milliseconds: int) -> None:
        return None


@pytest.mark.asyncio
async def test_rewind_from_middle_discovers_index_zero_without_threshold(monkeypatch) -> None:
    adapter = JumpPlusAdapter()
    page = _ControlPage()
    calls = 0

    async def rows(_page):
        nonlocal calls
        calls += 1
        return (
            [{"pageIndex": 20, "canvasId": "middle"}]
            if calls == 1
            else [{"pageIndex": 0, "canvasId": "first"}]
        )

    availability_calls = 0

    async def available(_button):
        nonlocal availability_calls
        availability_calls += 1
        return availability_calls == 1

    monkeypatch.setattr(adapter, "_rows", rows)
    monkeypatch.setattr(adapter, "_control_available", available)

    assert await adapter._rewind_to_first(page)  # type: ignore[arg-type]
    assert adapter._first_content_page_index == 0
    assert page.control.click_count == 1


@pytest.mark.asyncio
async def test_rewind_front_link_restores_content_after_precontent_state(monkeypatch) -> None:
    adapter = JumpPlusAdapter()
    page = _ControlPage()
    calls = 0

    async def rows(_page):
        nonlocal calls
        calls += 1
        if calls == 1:
            return [{"pageIndex": 2}]
        if calls == 2:
            return []
        return [{"pageIndex": 2}]

    availability_calls = 0

    async def available(_button):
        nonlocal availability_calls
        availability_calls += 1
        return availability_calls <= 2

    async def initial_state(_page):
        return "start"

    monkeypatch.setattr(adapter, "_rows", rows)
    monkeypatch.setattr(adapter, "_control_available", available)
    monkeypatch.setattr(adapter, "_initial_viewer_state", initial_state)

    assert await adapter._rewind_to_first(page)  # type: ignore[arg-type]
    assert adapter._first_content_page_index == 2
    assert page.control.click_count == 2


@pytest.mark.asyncio
async def test_rewind_does_not_traverse_empty_leading_page_area(monkeypatch) -> None:
    adapter = JumpPlusAdapter()

    class _EmptyLeadingAreaPage:
        url = "https://shonenjumpplus.com/episode/123"

        async def evaluate(self, _script, _index):
            return False

    page = _EmptyLeadingAreaPage()

    async def rows(_page):
        return [{"pageIndex": 1, "canvasId": "first-content"}]

    async def unavailable(_button):
        raise AssertionError("empty leading area must not trigger backward click")

    monkeypatch.setattr(adapter, "_rows", rows)
    monkeypatch.setattr(adapter, "_control_available", unavailable)

    assert await adapter._rewind_to_first(page)  # type: ignore[arg-type]
    assert adapter._first_content_page_index == 1


@pytest.mark.asyncio
async def test_rewind_fails_closed_for_ambiguous_preceding_page_area(monkeypatch) -> None:
    adapter = JumpPlusAdapter()

    class _AmbiguousLeadingAreaPage:
        url = "https://shonenjumpplus.com/episode/123"

        async def evaluate(self, _script, _index):
            return None

    page = _AmbiguousLeadingAreaPage()

    async def rows(_page):
        return [{"pageIndex": 2, "canvasId": "second-content"}]

    async def no_backward(_page):
        return False

    monkeypatch.setattr(adapter, "_rows", rows)
    monkeypatch.setattr(adapter, "_wait_for_backward_control", no_backward)

    assert not await adapter._rewind_to_first(page)  # type: ignore[arg-type]
    assert adapter._first_content_page_index is None


@pytest.mark.asyncio
async def test_index_zero_initial_content_does_not_startup_forward(monkeypatch) -> None:
    adapter = JumpPlusAdapter()
    page = _FakePage()
    rows = [{"pageIndex": 0}]
    calls = []
    _patch_initialize_dependencies(monkeypatch, adapter, rows)

    async def initial_state(_page):
        return "content", rows

    async def rewind(_page):
        adapter._first_content_page_index = 0
        return True

    async def forward(_page):
        calls.append("forward")

    monkeypatch.setattr(adapter, "_wait_for_initial_viewer_state", initial_state)
    monkeypatch.setattr(adapter, "_rewind_to_first", rewind)
    monkeypatch.setattr(adapter, "go_next", forward)

    await adapter.initialize(page)  # type: ignore[arg-type]

    assert calls == []
    assert adapter._first_content_page_index == 0


@pytest.mark.asyncio
async def test_go_next_ends_only_when_runtime_count_and_index_are_complete(monkeypatch) -> None:
    adapter = JumpPlusAdapter()
    page = _ControlPage()
    adapter._first_content_page_index = 0
    adapter._content_page_count = 23
    adapter._captured_content_page_count = 23
    adapter._last_active_max_page_index = 22

    await adapter.go_next(page)  # type: ignore[arg-type]
    assert adapter._terminal_reached
    assert page.control.click_count == 0

    adapter._terminal_reached = False
    adapter._captured_content_page_count = 22
    clicked = []

    async def click_forward(_page):
        clicked.append(True)

    monkeypatch.setattr(adapter, "_click_forward", click_forward)
    await adapter.go_next(page)  # type: ignore[arg-type]
    assert not adapter._terminal_reached
    assert clicked == [True]


@pytest.mark.asyncio
async def test_one_page_special_does_not_click_forward() -> None:
    adapter = JumpPlusAdapter()
    page = _ControlPage()
    adapter._first_content_page_index = 1
    adapter._content_page_count = 1
    adapter._captured_content_page_count = 1
    adapter._last_active_max_page_index = 1

    await adapter.go_next(page)  # type: ignore[arg-type]

    assert adapter._terminal_reached
    assert page.control.click_count == 0


@pytest.mark.asyncio
async def test_wait_for_change_terminal_requires_capture_completion(monkeypatch) -> None:
    adapter = JumpPlusAdapter()
    page = _ControlPage()
    previous = ContentIdentity(page_id="last", page_number=None, source_id="123")
    adapter._first_content_page_index = 0
    adapter._content_page_count = 23
    adapter._last_active_max_page_index = 22
    adapter._advance_pending = True

    async def identity(_page):
        return previous

    async def rows(_page):
        return []

    monkeypatch.setattr(adapter, "get_content_identity", identity)
    monkeypatch.setattr(adapter, "_rows", rows)
    adapter._captured_content_page_count = 23
    await adapter.wait_for_change(page, previous)  # type: ignore[arg-type]
    assert adapter._terminal_reached

    adapter._terminal_reached = False
    adapter._advance_pending = True
    adapter._captured_content_page_count = 22
    adapter.page_change_timeout_ms = 0
    with pytest.raises(PageChangeTimeoutError):
        await adapter.wait_for_change(page, previous)  # type: ignore[arg-type]
