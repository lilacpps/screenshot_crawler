import json
import os
from pathlib import Path

import pytest

from screenshot_crawler.core.capture import CaptureResult, capture_locator
from screenshot_crawler.core.errors import (
    CaptureUnavailableError,
    MaxPagesExceededError,
    PageChangeTimeoutError,
    RunAlreadyExistsError,
    UnsupportedAccessStrategyError,
)
from screenshot_crawler.core.fingerprint import fingerprint_bytes
from screenshot_crawler.core.models import ContentContext, ContentIdentity, RunConfig
from screenshot_crawler.core.progress import ProgressStore, atomic_write_json
from screenshot_crawler.core.runner import CrawlerRunner
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.base import SiteAdapter


def test_fingerprint_is_sha256() -> None:
    assert fingerprint_bytes(b"bookwalker") == (
        "5ec581021ef6aed40b5017d0820b1ff37dbb088527815dc1099bec6b6b5da8ae"
    )


def test_atomic_json_write_handles_windows_trailing_directory_space(tmp_path: Path) -> None:
    if os.name != "nt":
        pytest.skip("Windows path normalization is not applicable")

    atomic_write_json(tmp_path / "run " / "manifest.json", {"ok": True})

    assert json.loads((tmp_path / "run" / "manifest.json").read_text()) == {"ok": True}


class FakeCanvasLocator:
    async def evaluate(self, expression: str) -> object:
        if "instanceof HTMLCanvasElement" in expression:
            return True
        return (
            "data:image/png;base64,"
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )

    async def screenshot(self, **_kwargs: object) -> bytes:
        raise AssertionError("canvas capture should use the raw PNG buffer")

    async def bounding_box(self) -> dict[str, float]:
        return {"width": 1, "height": 1}


async def test_capture_canvas_uses_raw_png_buffer() -> None:
    result = await capture_locator(FakeCanvasLocator())  # type: ignore[arg-type]

    assert result.data.startswith(b"\x89PNG\r\n\x1a\n")
    assert (result.width, result.height) == (1, 1)


class FakePage:
    url = "https://example.test/viewer"

    def __init__(self) -> None:
        self.events: list[str] = []

    async def goto(self, *_args: object, **_kwargs: object) -> None:
        self.events.append("goto")

    async def wait_for_timeout(self, _milliseconds: int) -> None:
        return None


class FakeAdapter(SiteAdapter):
    def __init__(self, states: list[PageState], identities: list[ContentIdentity]) -> None:
        self.states = states
        self.identities = identities
        self.index = 0
        self.captured = 0

    async def initialize(self, page: FakePage) -> None:
        return None

    async def detect_state(self, page: FakePage) -> PageState:
        return self.states[min(self.index, len(self.states) - 1)]

    async def get_capture_target(self, page: FakePage) -> object:
        return object()

    async def get_content_identity(self, page: FakePage) -> ContentIdentity:
        return self.identities[min(self.index, len(self.identities) - 1)]

    async def get_content_context(self, page: FakePage) -> ContentContext:
        return ContentContext(content_id="work-1")

    async def go_next(self, page: FakePage) -> None:
        self.index += 1

    async def wait_for_change(
        self,
        page: FakePage,
        previous_identity: ContentIdentity | None,
    ) -> None:
        return None


class NativeCaptureAdapter(FakeAdapter):
    def __init__(self, states: list[PageState], identities: list[ContentIdentity]) -> None:
        super().__init__(states, identities)
        self.native_calls = 0
        self.target_calls = 0
        self.cleanup_calls = 0

    async def capture_page(self, page: FakePage) -> tuple[CaptureResult, ...] | None:
        self.native_calls += 1
        return (CaptureResult(data=b"native", width=960, height=1280),)

    async def get_capture_targets(self, page: FakePage) -> tuple[object, ...]:
        self.target_calls += 1
        raise AssertionError("native capture should bypass locator targets")

    async def cleanup_capture_targets(self, page: FakePage) -> None:
        self.cleanup_calls += 1


class NativeSpreadAdapter(NativeCaptureAdapter):
    async def capture_page(self, page: FakePage) -> tuple[CaptureResult, ...] | None:
        self.native_calls += 1
        return (
            CaptureResult(data=b"right", width=1303, height=2048),
            CaptureResult(data=b"left", width=1303, height=2048),
        )


async def test_base_adapter_capture_page_defaults_to_locator_fallback() -> None:
    adapter = FakeAdapter(
        [PageState.END],
        [ContentIdentity(page_number=1, source_id="work-1")],
    )

    assert await adapter.capture_page(FakePage()) is None


class FallbackCaptureAdapter(FakeAdapter):
    def __init__(
        self,
        states: list[PageState],
        identities: list[ContentIdentity],
        error: Exception | None = None,
    ) -> None:
        super().__init__(states, identities)
        self.native_calls = 0
        self.cleanup_calls = 0
        self.error = error or CaptureUnavailableError("test native capture unavailable")

    async def capture_page(self, page: FakePage) -> tuple[CaptureResult, ...] | None:
        self.native_calls += 1
        raise self.error

    async def cleanup_capture_targets(self, page: FakePage) -> None:
        self.cleanup_calls += 1


class TrackingAdapter(FakeAdapter):
    async def configure_run(self, page: FakePage, access_strategy: str) -> None:
        page.events.append(f"configure:{access_strategy}")


async def test_runner_passes_access_strategy_before_navigation(tmp_path: Path) -> None:
    page = FakePage()
    adapter = TrackingAdapter(
        [PageState.END],
        [ContentIdentity(page_number=1, source_id="work-1")],
    )

    result = await CrawlerRunner(
        RunConfig(
            site="test",
            source_url="https://example.test/viewer",
            output_dir=tmp_path / "run",
            diagnostics_dir=tmp_path / "diagnostics",
            access_strategy="auto",
        )
    ).run(page, adapter)

    assert result.stop_state is PageState.END
    assert page.events == ["configure:auto", "goto"]


@pytest.mark.parametrize("strategy", ["direct", "quota"])
async def test_runner_rejects_unsupported_strategy_without_auto_fallback(
    tmp_path: Path,
    strategy: str,
) -> None:
    page = FakePage()
    adapter = FakeAdapter(
        [PageState.END],
        [ContentIdentity(page_number=1, source_id="work-1")],
    )

    with pytest.raises(
        UnsupportedAccessStrategyError,
        match=f"access_strategy='{strategy}'",
    ):
        await CrawlerRunner(
            RunConfig(
                site="test",
                source_url="https://example.test/viewer",
                output_dir=tmp_path / "run",
                diagnostics_dir=tmp_path / "diagnostics",
                access_strategy=strategy,  # type: ignore[arg-type]
            )
        ).run(page, adapter)

    assert page.events == []


class DelayedContextAdapter(FakeAdapter):
    def __init__(self) -> None:
        super().__init__(
            [PageState.CONTENT, PageState.END],
            [ContentIdentity(page_number=1, source_id="work-1")],
        )
        self.context_calls = 0

    async def get_content_context(self, page: FakePage) -> ContentContext:
        self.context_calls += 1
        return ContentContext(
            content_id="work-1",
            title=None if self.context_calls == 1 else "loaded later",
        )


class SpreadAdapter(FakeAdapter):
    async def get_capture_targets(self, page: FakePage) -> tuple[object, ...]:
        return ("right", "left")


@pytest.fixture
def fake_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    async def capture(_target: object) -> CaptureResult:
        return CaptureResult(data=b"unique", width=100, height=200)

    monkeypatch.setattr("screenshot_crawler.core.runner.capture_locator", capture)
    monkeypatch.setattr(
        "screenshot_crawler.core.runner.save_capture",
        lambda _result, _path: None,
    )


async def test_runner_captures_content_and_stops_at_end(
    tmp_path: Path,
    fake_capture: None,
) -> None:
    adapter = FakeAdapter(
        [PageState.CONTENT, PageState.END],
        [ContentIdentity(page_number=1, source_id="work-1")],
    )
    result = await CrawlerRunner(
        RunConfig(
            site="test",
            source_url="https://example.test/viewer",
            output_dir=tmp_path / "run",
            diagnostics_dir=tmp_path / "diagnostics",
        )
    ).run(FakePage(), adapter)

    assert result.stop_state is PageState.END
    assert len(result.pages) == 1
    manifest = json.loads((tmp_path / "run" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["pages"][0]["sequence"] == 1


async def test_runner_prefers_native_capture_over_locator_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unexpected_capture(_target: object) -> CaptureResult:
        raise AssertionError("locator capture should not run for native results")

    monkeypatch.setattr("screenshot_crawler.core.runner.capture_locator", unexpected_capture)
    adapter = NativeCaptureAdapter(
        [PageState.CONTENT, PageState.END],
        [ContentIdentity(page_number=1, source_id="work-1")],
    )

    result = await CrawlerRunner(
        RunConfig(
            site="test",
            source_url="https://example.test/viewer",
            output_dir=tmp_path / "run",
            diagnostics_dir=tmp_path / "diagnostics",
        )
    ).run(FakePage(), adapter)

    assert result.pages[0].width == 960
    assert result.pages[0].height == 1280
    assert adapter.native_calls == 1
    assert adapter.target_calls == 0
    assert adapter.cleanup_calls == 0


async def test_runner_preserves_native_spread_order_and_metadata(
    tmp_path: Path,
) -> None:
    adapter = NativeSpreadAdapter(
        [PageState.CONTENT, PageState.END],
        [ContentIdentity(page_number=1, source_id="work-1")],
    )

    result = await CrawlerRunner(
        RunConfig(
            site="test",
            source_url="https://example.test/viewer",
            output_dir=tmp_path / "run",
            diagnostics_dir=tmp_path / "diagnostics",
        )
    ).run(FakePage(), adapter)

    assert [(page.width, page.height) for page in result.pages] == [
        (1303, 2048),
        (1303, 2048),
    ]
    assert [page.metadata for page in result.pages] == [
        {"part": 1, "parts": 2},
        {"part": 2, "parts": 2},
    ]
    assert [
        (tmp_path / "run" / page.file).read_bytes() for page in result.pages
    ] == [b"right", b"left"]


async def test_runner_falls_back_and_cleans_up_after_native_unavailable(
    tmp_path: Path,
    fake_capture: None,
) -> None:
    adapter = FallbackCaptureAdapter(
        [PageState.CONTENT, PageState.END],
        [ContentIdentity(page_number=1, source_id="work-1")],
    )

    result = await CrawlerRunner(
        RunConfig(
            site="test",
            source_url="https://example.test/viewer",
            output_dir=tmp_path / "run",
            diagnostics_dir=tmp_path / "diagnostics",
        )
    ).run(FakePage(), adapter)

    assert result.pages[0].width == 100
    assert result.pages[0].height == 200
    assert adapter.native_calls == 1
    assert adapter.cleanup_calls == 1


async def test_runner_falls_back_after_bounded_native_capture_timeout(
    tmp_path: Path,
    fake_capture: None,
) -> None:
    adapter = FallbackCaptureAdapter(
        [PageState.CONTENT, PageState.END],
        [ContentIdentity(page_number=1, source_id="work-1")],
        PageChangeTimeoutError("test capture timeout"),
    )

    result = await CrawlerRunner(
        RunConfig(
            site="test",
            source_url="https://example.test/viewer",
            output_dir=tmp_path / "run",
            diagnostics_dir=tmp_path / "diagnostics",
        )
    ).run(FakePage(), adapter)

    assert len(result.pages) == 1
    assert adapter.cleanup_calls == 1


async def test_runner_skips_ad_and_does_not_capture_next_content(
    tmp_path: Path,
    fake_capture: None,
) -> None:
    adapter = FakeAdapter(
        [PageState.CONTENT, PageState.AD, PageState.NEXT_CONTENT],
        [ContentIdentity(page_number=1, source_id="work-1")],
    )
    result = await CrawlerRunner(
        RunConfig(
            site="test",
            source_url="https://example.test/viewer",
            output_dir=tmp_path / "run",
            diagnostics_dir=tmp_path / "diagnostics",
        )
    ).run(FakePage(), adapter)

    assert result.stop_state is PageState.NEXT_CONTENT
    assert len(result.pages) == 1


async def test_runner_stops_repeated_identity_without_duplicate_capture(
    tmp_path: Path,
    fake_capture: None,
) -> None:
    identity = ContentIdentity(page_number=1, source_id="work-1")
    adapter = FakeAdapter([PageState.CONTENT], [identity])

    with pytest.raises(PageChangeTimeoutError, match="same content"):
        await CrawlerRunner(
            RunConfig(
                site="test",
                source_url="https://example.test/viewer",
                output_dir=tmp_path / "run",
                diagnostics_dir=tmp_path / "diagnostics",
            )
        ).run(FakePage(), adapter)


async def test_runner_ignores_late_optional_context_fields(
    tmp_path: Path,
    fake_capture: None,
) -> None:
    result = await CrawlerRunner(
        RunConfig(
            site="test",
            source_url="https://example.test/viewer",
            output_dir=tmp_path / "run",
            diagnostics_dir=tmp_path / "diagnostics",
        )
    ).run(FakePage(), DelayedContextAdapter())

    assert result.stop_state is PageState.END
    assert len(result.pages) == 1


async def test_runner_saves_each_capture_target_in_a_spread(
    tmp_path: Path,
    fake_capture: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def capture(target: object) -> CaptureResult:
        return CaptureResult(data=str(target).encode(), width=100, height=200)

    monkeypatch.setattr("screenshot_crawler.core.runner.capture_locator", capture)
    adapter = SpreadAdapter(
        [PageState.CONTENT, PageState.END],
        [ContentIdentity(page_number=1, source_id="work-1")],
    )

    result = await CrawlerRunner(
        RunConfig(
            site="test",
            source_url="https://example.test/viewer",
            output_dir=tmp_path / "run",
            diagnostics_dir=tmp_path / "diagnostics",
        )
    ).run(FakePage(), adapter)

    assert len(result.pages) == 2
    assert [page.metadata for page in result.pages] == [
        {"part": 1, "parts": 2},
        {"part": 2, "parts": 2},
    ]
    manifest = json.loads((tmp_path / "run" / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["pages"]) == 2


@pytest.mark.parametrize("terminal_state", [PageState.END, PageState.NEXT_CONTENT])
async def test_runner_allows_exact_max_pages_before_terminal_state(
    tmp_path: Path,
    fake_capture: None,
    terminal_state: PageState,
) -> None:
    adapter = FakeAdapter(
        [PageState.CONTENT, terminal_state],
        [ContentIdentity(page_number=1, source_id="work-1")],
    )

    result = await CrawlerRunner(
        RunConfig(
            site="test",
            source_url="https://example.test/viewer",
            output_dir=tmp_path / "run",
            diagnostics_dir=tmp_path / "diagnostics",
            max_pages=1,
        )
    ).run(FakePage(), adapter)

    assert len(result.pages) == 1
    assert result.stop_state is terminal_state


async def test_runner_rejects_content_after_max_pages(
    tmp_path: Path,
    fake_capture: None,
) -> None:
    adapter = FakeAdapter(
        [PageState.CONTENT],
        [ContentIdentity(page_number=1, source_id="work-1")],
    )

    with pytest.raises(MaxPagesExceededError):
        await CrawlerRunner(
            RunConfig(
                site="test",
                source_url="https://example.test/viewer",
                output_dir=tmp_path / "run",
                diagnostics_dir=tmp_path / "diagnostics",
                max_pages=1,
            )
        ).run(FakePage(), adapter)


async def test_runner_keeps_fingerprint_as_duplicate_authority(
    tmp_path: Path,
    fake_capture: None,
) -> None:
    adapter = FakeAdapter(
        [PageState.CONTENT, PageState.CONTENT, PageState.END],
        [
            ContentIdentity(page_number=1, source_id="work-1"),
            ContentIdentity(page_number=2, source_id="work-1"),
        ],
    )

    with pytest.raises(PageChangeTimeoutError, match="same content"):
        await CrawlerRunner(
            RunConfig(
                site="test",
                source_url="https://example.test/viewer",
                output_dir=tmp_path / "run",
                diagnostics_dir=tmp_path / "diagnostics",
            )
        ).run(FakePage(), adapter)

    assert len(json.loads((tmp_path / "run" / "manifest.json").read_text())["pages"]) == 1


async def test_runner_uses_fingerprint_when_identity_is_unavailable(
    tmp_path: Path,
    fake_capture: None,
) -> None:
    adapter = FakeAdapter([PageState.CONTENT], [ContentIdentity()])

    with pytest.raises(PageChangeTimeoutError, match="same content"):
        await CrawlerRunner(
            RunConfig(
                site="test",
                source_url="https://example.test/viewer",
                output_dir=tmp_path / "run",
                diagnostics_dir=tmp_path / "diagnostics",
            )
        ).run(FakePage(), adapter)


async def test_runner_does_not_overwrite_existing_run(
    tmp_path: Path,
    fake_capture: None,
) -> None:
    output_dir = tmp_path / "run"
    output_dir.mkdir()
    (output_dir / "manifest.json").write_text('{"keep": true}\n', encoding="utf-8")
    (output_dir / "page-0001.png").write_bytes(b"old")

    with pytest.raises(RunAlreadyExistsError, match="Resume is not implemented"):
        await CrawlerRunner(
            RunConfig(
                site="test",
                source_url="https://example.test/viewer",
                output_dir=output_dir,
                diagnostics_dir=tmp_path / "diagnostics",
            )
        ).run(FakePage(), FakeAdapter([PageState.END], []))

    assert (output_dir / "manifest.json").read_text(encoding="utf-8") == '{"keep": true}\n'
    assert (output_dir / "page-0001.png").read_bytes() == b"old"


async def test_runner_rejects_non_empty_output_directory(
    tmp_path: Path,
    fake_capture: None,
) -> None:
    output_dir = tmp_path / "run"
    output_dir.mkdir()
    unrelated = output_dir / "notes.txt"
    unrelated.write_text("keep", encoding="utf-8")

    with pytest.raises(RunAlreadyExistsError, match="not empty"):
        await CrawlerRunner(
            RunConfig(
                site="test",
                source_url="https://example.test/viewer",
                output_dir=output_dir,
                diagnostics_dir=tmp_path / "diagnostics",
            )
        ).run(FakePage(), FakeAdapter([PageState.END], []))

    assert unrelated.read_text(encoding="utf-8") == "keep"


def test_progress_store_does_not_overwrite_existing_manifest_or_progress(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "run"
    output_dir.mkdir()
    manifest = output_dir / "manifest.json"
    progress = output_dir / "progress.json"
    manifest.write_text('{"keep": true}\n', encoding="utf-8")
    progress.write_text('{"keep": true}\n', encoding="utf-8")

    with pytest.raises(RunAlreadyExistsError):
        ProgressStore(
            manifest_path=manifest,
            progress_path=progress,
            source_url="https://example.test/viewer",
            site="test",
            content_context=ContentContext(),
        )

    assert manifest.read_text(encoding="utf-8") == '{"keep": true}\n'
    assert progress.read_text(encoding="utf-8") == '{"keep": true}\n'
