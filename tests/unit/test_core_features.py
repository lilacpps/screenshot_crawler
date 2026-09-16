import json
import os
from pathlib import Path

import pytest

from screenshot_crawler.core.capture import CaptureResult, capture_locator
from screenshot_crawler.core.errors import PageChangeTimeoutError
from screenshot_crawler.core.fingerprint import fingerprint_bytes
from screenshot_crawler.core.models import ContentContext, ContentIdentity, RunConfig
from screenshot_crawler.core.progress import atomic_write_json
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

    async def goto(self, *_args: object, **_kwargs: object) -> None:
        return None

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
