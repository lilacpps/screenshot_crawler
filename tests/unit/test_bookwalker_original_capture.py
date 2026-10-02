from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from screenshot_crawler.core.capture import CaptureResult
from screenshot_crawler.site_adapters.bookwalker import adapter as adapter_module
from screenshot_crawler.site_adapters.bookwalker.adapter import BookWalkerAdapter
from screenshot_crawler.site_adapters.bookwalker.original_capture import (
    OriginalJpegCache,
    candidate_capture,
    candidate_from_jpeg,
    imagebitmap_pixel_exact_match,
    imagebitmap_signature,
    is_jpeg_bytes,
    jpeg_dimensions,
)

JPEG_1X1 = (
    b"\xff\xd8\xff\xe0\x00\x04\x00\x00"
    b"\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03"
    b"\x01\x11\x00\x02\x11\x00\x03\x11\x00\xff\xd9"
)
PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x04\x00\x00\x00\xb5\x1c\x0c\x02"
    b"\x00\x00\x00\x0bIDAT\x08\xd7c\x9a\xc0\xf0\x1f\x00\x05\x01\x01\x02"
    b"\x1b\xc9\x8d\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _candidate(data: bytes = JPEG_1X1, *, sequence: int = 1):
    candidate = candidate_from_jpeg(
        data,
        url="https://viewer-epubs-trial.bookwalker.jp/path/page.jpegbvCoverImage?redacted=1",
        sequence=sequence,
        fetched_at=1.0,
    )
    assert candidate is not None
    return candidate


def test_jpeg_magic_dimensions_and_capture_result() -> None:
    assert is_jpeg_bytes(JPEG_1X1)
    assert jpeg_dimensions(JPEG_1X1) == (1, 1)

    result = candidate_capture(_candidate())

    assert isinstance(result, CaptureResult)
    assert result.data == JPEG_1X1
    assert (result.width, result.height) == (1, 1)
    assert result.mime_type == "image/jpeg"
    assert result.file_extension == ".jpg"


def test_invalid_jpeg_magic_or_dimensions_is_rejected() -> None:
    assert not is_jpeg_bytes(PNG_1X1)
    assert jpeg_dimensions(PNG_1X1) is None
    assert candidate_from_jpeg(
        b"\xff\xd8\xff\xe0\x00\x04\x00\x00",
        url="https://viewer-epubs-trial.bookwalker.jp/page.jpeg",
        sequence=1,
    ) is None


@pytest.mark.asyncio
async def test_full_resolution_imagebitmap_match_does_not_resize_candidate() -> None:
    class FakePage:
        def __init__(self) -> None:
            self.script = ""

        async def evaluate(self, script: str, payload: dict[str, object]) -> dict[str, object]:
            self.script = script
            assert payload["sourceId"] == "bitmap-1"
            return {"available": True, "dimensions_equal": True, "exact": True}

    page = FakePage()
    result = await imagebitmap_pixel_exact_match(page, JPEG_1X1, "bitmap-1")

    assert result["exact"] is True
    assert "64" not in page.script
    assert "getImageData(0, 0, source.width, source.height)" in page.script


@pytest.mark.asyncio
async def test_imagebitmap_signature_uses_existing_64x64_hash_contract() -> None:
    class FakePage:
        def __init__(self) -> None:
            self.script = ""
            self.payload: dict[str, object] | None = None

        async def evaluate(
            self,
            script: str,
            payload: dict[str, object],
        ) -> str:
            self.script = script
            self.payload = payload
            return "signature"

    page = FakePage()
    result = await imagebitmap_signature(page, "bitmap-1")

    assert result == "signature"
    assert page.payload == {"sourceId": "bitmap-1"}
    assert "canvas.width = 64" in page.script
    assert "createImageBitmap" not in page.script
    assert "2246822519" in page.script


def test_original_jpeg_cache_deduplicates_and_evicts_old_entries() -> None:
    cache = OriginalJpegCache(max_entries=2, max_bytes=1024)
    first = _candidate(sequence=1)
    second = _candidate(JPEG_1X1 + b"a", sequence=2)
    third = _candidate(JPEG_1X1 + b"b", sequence=3)

    assert cache.add(first)
    assert not cache.add(first)
    assert cache.add(second)
    assert cache.add(third)
    assert len(cache) == 2
    assert cache.total_bytes == len(second.data) + len(third.data)
    assert [item.sequence for item in cache.values()] == [2, 3]


class _FakeResponse:
    def __init__(self) -> None:
        self.url = (
            "https://viewer-epubs-trial.bookwalker.jp/"
            "path/0.jpegbvCoverImage?redacted=1"
        )
        self.status = 200
        self.headers = {
            "content-type": "image/jpeg",
            "content-length": str(len(JPEG_1X1)),
        }
        self.request = SimpleNamespace(resource_type="xhr")

    async def body(self) -> bytes:
        return JPEG_1X1


class _PreparePage:
    def __init__(self) -> None:
        self.listener_count = 0
        self.route_count = 0
        self.init_scripts: list[str] = []

    async def add_init_script(self, script: str) -> None:
        self.init_scripts.append(script)

    def on(self, _event: str, _handler: object) -> None:
        self.listener_count += 1

    async def route(self, _pattern: str, _handler: object) -> None:
        self.route_count += 1


@pytest.mark.asyncio
async def test_original_jpeg_capture_is_enabled_for_production_runs() -> None:
    adapter = adapter_module.BookWalkerAdapter()
    page = _PreparePage()

    await adapter.prepare_page(page)  # type: ignore[arg-type]

    assert adapter.enable_original_jpeg_capture
    assert page.listener_count == 1
    assert page.route_count == 2


@pytest.mark.asyncio
async def test_canvas_mode_does_not_install_original_jpeg_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOOKWALKER_CAPTURE_MODE", "canvas")
    adapter = BookWalkerAdapter()
    page = _PreparePage()

    await adapter.prepare_page(page)  # type: ignore[arg-type]

    assert adapter.capture_mode == "canvas"
    assert page.listener_count == 0
    assert page.route_count == 0


@pytest.mark.asyncio
async def test_response_body_listener_is_host_limited_and_redacts_url() -> None:
    adapter = BookWalkerAdapter()
    await adapter._read_original_response(_FakeResponse())

    assert len(adapter._original_candidates) == 1
    assert adapter._original_candidate_generation == 1
    await adapter._read_original_response(_FakeResponse())
    assert adapter._original_candidate_generation == 1
    candidate = adapter._original_candidates.values()[0]
    assert candidate.mime_type == "image/jpeg"
    assert "?" not in candidate.redacted_url
    assert candidate.redacted_url.endswith("/path/0.jpegbvCoverImage")

    assert adapter._is_original_response(_FakeResponse())
    assert adapter._is_original_response(
        SimpleNamespace(
            url="https://bw-bv-epubs.bookwalker.jp/03/30/normal_default/page.jpeg",
            request=SimpleNamespace(resource_type="xhr"),
            headers={"content-type": "image/jpeg"},
        )
    )
    assert not adapter._is_original_response(
        SimpleNamespace(
            url="https://viewer.bookwalker.jp/path/page.jpeg",
            request=SimpleNamespace(resource_type="xhr"),
            headers={"content-type": "image/jpeg"},
        )
    )
    assert not adapter._is_original_response(
        SimpleNamespace(
            url="https://viewer-epubs-trial.bookwalker.jp/path/page.jpeg",
            request=SimpleNamespace(resource_type="stylesheet"),
            headers={"content-type": "image/jpeg"},
        )
    )


@pytest.mark.asyncio
async def test_original_route_stores_body_before_fulfill() -> None:
    adapter = BookWalkerAdapter()
    events: list[str] = []

    class FakeRoute:
        async def fetch(self) -> _FakeResponse:
            events.append("fetch")
            return _FakeResponse()

        async def fulfill(self, *, response: object) -> None:
            assert response is not None
            events.append("fulfill")
            assert len(adapter._original_candidates) == 1

    await adapter._handle_original_route(FakeRoute())

    assert events == ["fetch", "fulfill"]
    assert adapter._original_candidate_generation == 1


@pytest.mark.asyncio
async def test_unique_signature_match_returns_jpeg_and_ambiguous_match_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_signature(_page: object, data: bytes, mime_type: str) -> str:
        return (
            "native"
            if mime_type == "image/png"
            or data.endswith((b"native", b"native2"))
            else "other"
        )

    monkeypatch.setattr(adapter_module, "image_signature", fake_signature)
    adapter = BookWalkerAdapter()
    native = CaptureResult(PNG_1X1, 1, 1)
    matching = _candidate(JPEG_1X1 + b"native", sequence=1)
    adapter._original_candidates.add(matching)

    result = await adapter._capture_original_jpegs(SimpleNamespace(), (native,))

    assert result is not None
    assert result[0].mime_type == "image/jpeg"
    assert result[0].file_extension == ".jpg"
    assert result[0].data == matching.data

    cached_result = await adapter._capture_original_jpegs(SimpleNamespace(), (native,))
    assert cached_result is not None
    assert cached_result[0].data == matching.data
    assert (
        adapter._capture_debug["bookwalker_capture"]["original_match"]
        ["original_attempt_count"]
        == 0
    )

    ambiguous = BookWalkerAdapter()
    ambiguous._original_candidates.add(matching)
    ambiguous._original_candidates.add(_candidate(JPEG_1X1 + b"native2", sequence=2))
    assert await ambiguous._capture_original_jpegs(SimpleNamespace(), (native,)) is None


@pytest.mark.asyncio
async def test_original_capture_mismatch_without_pending_work_returns_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_signature(_page: object, data: bytes, mime_type: str) -> str:
        return "native" if mime_type == "image/png" else "other"

    monkeypatch.setattr(adapter_module, "image_signature", fake_signature)
    adapter = BookWalkerAdapter()
    page = SimpleNamespace(
        wait_for_timeout=lambda _milliseconds: pytest.fail("blind wait was used")
    )
    native = CaptureResult(PNG_1X1, 1, 1)
    adapter._original_candidates.add(_candidate(JPEG_1X1 + b"mismatch", sequence=1))

    assert await adapter._capture_original_jpegs(page, (native,)) is None
    debug = adapter._capture_debug["bookwalker_capture"]
    assert debug["original_match"]["original_attempt_count"] == 1
    assert debug["original_match"]["original_retry_wait_count"] == 0
    assert debug["timing_ms"]["original_retry_wait_ms"] == 0


@pytest.mark.asyncio
async def test_original_capture_empty_cache_without_pending_work_returns_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_signature(_page: object, _data: bytes, _mime_type: str) -> str:
        return "native"

    monkeypatch.setattr(adapter_module, "image_signature", fake_signature)
    adapter = BookWalkerAdapter()
    native = CaptureResult(PNG_1X1, 1, 1)

    assert await adapter._capture_original_jpegs(object(), (native,)) is None
    debug = adapter._capture_debug["bookwalker_capture"]
    assert debug["original_match"]["original_candidate_count_at_start"] == 0
    assert debug["original_match"]["original_attempt_count"] == 1
    assert debug["original_match"]["original_retry_wait_count"] == 0


@pytest.mark.asyncio
async def test_original_capture_pending_task_candidate_wakes_and_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_signature(_page: object, data: bytes, mime_type: str) -> str:
        return "native" if mime_type == "image/png" or data.endswith(b"native") else "other"

    monkeypatch.setattr(adapter_module, "image_signature", fake_signature)
    adapter = BookWalkerAdapter()
    adapter.original_capture_retry_interval_ms = 100
    native = CaptureResult(PNG_1X1, 1, 1)

    async def pending_response() -> None:
        await asyncio.sleep(0.001)
        adapter._store_original_response_body(
            SimpleNamespace(url="https://bw-bv-epubs.bookwalker.jp/page.jpeg"),
            JPEG_1X1 + b"native",
        )

    task = asyncio.create_task(pending_response())
    adapter._original_response_tasks.add(task)
    result = await adapter._capture_original_jpegs(object(), (native,))
    await task

    assert result is not None
    assert result[0].data == JPEG_1X1 + b"native"
    debug = adapter._capture_debug["bookwalker_capture"]
    assert debug["original_match"]["original_attempt_count"] == 2
    assert debug["original_match"]["original_retry_wait_count"] == 1
    assert debug["original_match"]["original_candidate_generation_start"] == 0
    assert debug["original_match"]["original_candidate_generation_end"] == 1
    assert debug["timing_ms"]["original_retry_wait_ms"] >= 0


@pytest.mark.asyncio
async def test_original_capture_multiple_pending_tasks_waits_for_late_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_signature(_page: object, data: bytes, mime_type: str) -> str:
        return "native" if mime_type == "image/png" or data.endswith(b"native") else "other"

    monkeypatch.setattr(adapter_module, "image_signature", fake_signature)
    adapter = BookWalkerAdapter()
    adapter.original_capture_retry_interval_ms = 100
    native = CaptureResult(PNG_1X1, 1, 1)
    first_task_done = asyncio.Event()

    async def first_response_without_candidate() -> None:
        first_task_done.set()

    async def second_response_with_candidate() -> None:
        await first_task_done.wait()
        await asyncio.sleep(0.005)
        adapter._store_original_response_body(
            SimpleNamespace(url="https://bw-bv-epubs.bookwalker.jp/page.jpeg"),
            JPEG_1X1 + b"native",
        )

    first_task = asyncio.create_task(first_response_without_candidate())
    second_task = asyncio.create_task(second_response_with_candidate())
    adapter._original_response_tasks.update({first_task, second_task})

    result = await adapter._capture_original_jpegs(object(), (native,))
    await asyncio.gather(first_task, second_task)

    assert result is not None
    assert result[0].data == JPEG_1X1 + b"native"
    debug = adapter._capture_debug["bookwalker_capture"]
    assert debug["original_match"]["original_attempt_count"] == 2
    assert debug["original_match"]["original_retry_wait_count"] == 1
    assert debug["original_match"]["original_candidate_generation_end"] == 1


@pytest.mark.asyncio
async def test_original_capture_multiple_pending_tasks_waits_until_all_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_signature(_page: object, _data: bytes, _mime_type: str) -> str:
        return "native"

    monkeypatch.setattr(adapter_module, "image_signature", fake_signature)
    adapter = BookWalkerAdapter()
    adapter.original_capture_retry_interval_ms = 100
    native = CaptureResult(PNG_1X1, 1, 1)
    completed: list[str] = []

    async def response_without_candidate(name: str) -> None:
        await asyncio.sleep(0.001 if name == "first" else 0.005)
        completed.append(name)

    first_task = asyncio.create_task(response_without_candidate("first"))
    second_task = asyncio.create_task(response_without_candidate("second"))
    adapter._original_response_tasks.update({first_task, second_task})

    assert await adapter._capture_original_jpegs(object(), (native,)) is None
    await asyncio.gather(first_task, second_task)

    assert completed == ["first", "second"]
    debug = adapter._capture_debug["bookwalker_capture"]
    assert debug["original_match"]["original_attempt_count"] == 1
    assert debug["original_match"]["original_retry_wait_count"] == 1


@pytest.mark.asyncio
async def test_original_capture_pending_timeout_does_not_cancel_response_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_signature(_page: object, _data: bytes, _mime_type: str) -> str:
        return "native"

    monkeypatch.setattr(adapter_module, "image_signature", fake_signature)
    adapter = BookWalkerAdapter()
    adapter.original_capture_retry_interval_ms = 10
    native = CaptureResult(PNG_1X1, 1, 1)
    release = asyncio.Event()

    async def pending_response() -> None:
        await release.wait()

    task = asyncio.create_task(pending_response())
    adapter._original_response_tasks.add(task)

    assert await adapter._capture_original_jpegs(object(), (native,)) is None
    assert not task.done()

    release.set()
    await task


@pytest.mark.asyncio
async def test_original_candidate_work_wait_without_pending_tasks_returns_false() -> None:
    adapter = BookWalkerAdapter()

    assert await adapter._wait_for_original_candidate_work(0) is False


@pytest.mark.asyncio
async def test_original_candidate_work_wait_with_changed_generation_returns_true() -> None:
    adapter = BookWalkerAdapter()
    adapter._original_candidate_generation = 1

    assert await adapter._wait_for_original_candidate_work(0) is True


@pytest.mark.asyncio
async def test_original_capture_completed_task_without_candidate_does_not_rescan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_signature(_page: object, _data: bytes, _mime_type: str) -> str:
        return "native"

    monkeypatch.setattr(adapter_module, "image_signature", fake_signature)
    adapter = BookWalkerAdapter()
    adapter.original_capture_retry_interval_ms = 100
    native = CaptureResult(PNG_1X1, 1, 1)

    async def completed_without_candidate() -> None:
        await asyncio.sleep(0.001)

    task = asyncio.create_task(completed_without_candidate())
    adapter._original_response_tasks.add(task)
    assert await adapter._capture_original_jpegs(object(), (native,)) is None
    await task

    debug = adapter._capture_debug["bookwalker_capture"]
    assert debug["original_match"]["original_attempt_count"] == 1
    assert debug["original_match"]["original_retry_wait_count"] == 1
    assert debug["original_match"]["original_candidate_generation_end"] == 0


@pytest.mark.asyncio
async def test_original_capture_generation_change_during_scan_retries_without_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = BookWalkerAdapter()
    native = CaptureResult(PNG_1X1, 1, 1)
    mismatch = _candidate(JPEG_1X1 + b"mismatch", sequence=1)
    adapter._original_candidates.add(mismatch)
    added = False

    async def fake_signature(_page: object, data: bytes, mime_type: str) -> str:
        nonlocal added
        if mime_type == "image/png":
            return "native"
        if not added:
            added = True
            adapter._store_original_response_body(
                SimpleNamespace(url="https://bw-bv-epubs.bookwalker.jp/page.jpeg"),
                JPEG_1X1 + b"native",
            )
        return "native" if data.endswith(b"native") else "other"

    monkeypatch.setattr(adapter_module, "image_signature", fake_signature)
    result = await adapter._capture_original_jpegs(object(), (native,))

    assert result is not None
    debug = adapter._capture_debug["bookwalker_capture"]
    assert debug["original_match"]["original_attempt_count"] == 2
    assert debug["original_match"]["original_retry_wait_count"] == 0
    assert debug["timing_ms"]["original_retry_wait_ms"] == 0


@pytest.mark.asyncio
async def test_original_negative_cache_is_invalidated_by_new_candidate_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_signature(_page: object, data: bytes, mime_type: str) -> str:
        return "native" if mime_type == "image/png" or data.endswith(b"native") else "other"

    monkeypatch.setattr(adapter_module, "image_signature", fake_signature)
    adapter = BookWalkerAdapter()
    native = CaptureResult(PNG_1X1, 1, 1)

    assert await adapter._capture_original_jpegs(object(), (native,)) is None
    assert adapter._original_capture_decisions
    adapter._store_original_response_body(
        SimpleNamespace(url="https://bw-bv-epubs.bookwalker.jp/page.jpeg"),
        JPEG_1X1 + b"native",
    )

    result = await adapter._capture_original_jpegs(object(), (native,))

    assert result is not None
    assert result[0].data == JPEG_1X1 + b"native"
    debug = adapter._capture_debug["bookwalker_capture"]
    assert debug["original_match"]["original_candidate_generation_start"] == 1
    assert debug["original_match"]["original_attempt_count"] == 1


@pytest.mark.asyncio
async def test_spread_requires_all_parts_to_match_before_any_jpeg_is_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_signature(_page: object, data: bytes, mime_type: str) -> str:
        return "native" if mime_type == "image/png" else data[-1:].hex()

    monkeypatch.setattr(adapter_module, "image_signature", fake_signature)
    adapter = BookWalkerAdapter()
    adapter.original_capture_retry_interval_ms = 0
    adapter._original_candidates.add(_candidate(JPEG_1X1 + b"native", sequence=1))

    native = (
        CaptureResult(PNG_1X1, 1, 1),
        CaptureResult(PNG_1X1, 1, 1),
    )

    assert await adapter._capture_original_jpegs(SimpleNamespace(), native) is None
