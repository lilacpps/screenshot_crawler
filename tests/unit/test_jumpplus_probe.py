from __future__ import annotations

import json

import pytest
from PIL import Image

from poc.jumpplus_probe import (
    JumpPlusProbe,
    _decoded_pixel_sha256,
    _pixel_comparison,
    classify_draw_geometry,
    classify_resource,
    draw_calls_for_canvas,
    extract_episode_id,
    fingerprint_changed,
    is_target_episode_url,
    navigation_candidate_is_forbidden,
    navigation_succeeded,
)


def test_extract_episode_id_requires_jumpplus_episode_url() -> None:
    target = "https://shonenjumpplus.com/episode/13932016480029111789"
    assert extract_episode_id(target) == "13932016480029111789"
    assert extract_episode_id(target + "?from=probe") == "13932016480029111789"
    assert extract_episode_id("https://example.test/episode/13932016480029111789") is None
    assert extract_episode_id("https://shonenjumpplus.com/work/13932016480029111789") is None


def test_target_url_guard_rejects_other_episode() -> None:
    expected = "13932016480029111789"
    assert is_target_episode_url(
        "https://www.shonenjumpplus.com/episode/13932016480029111789#page=2",
        expected,
    )
    assert not is_target_episode_url(
        "https://shonenjumpplus.com/episode/13932016480029111790",
        expected,
    )
    assert not is_target_episode_url("https://shonenjumpplus.com/", expected)


def test_navigation_safety_and_fingerprint_change_are_separate() -> None:
    assert navigation_candidate_is_forbidden("page-navigation-forward") is False
    assert navigation_candidate_is_forbidden("次の話") is True
    assert navigation_candidate_is_forbidden("購入", "page-navigation-forward") is True
    assert fingerprint_changed("before", "after") is True
    assert fingerprint_changed("before", "before") is False
    assert fingerprint_changed("before", None) is False
    assert navigation_succeeded(False, True) is False
    assert navigation_succeeded(True, False) is False
    assert navigation_succeeded(True, True) is True


class _FakeLocator:
    def __init__(self, count: int, attributes: dict[str, str | None] | None = None) -> None:
        self._count = count
        self._attributes = attributes or {}

    async def count(self) -> int:
        return self._count

    async def is_visible(self) -> bool:
        return True

    async def inner_text(self, timeout: int) -> str:
        return self._attributes.get("text") or ""

    async def get_attribute(self, name: str) -> str | None:
        return self._attributes.get(name)


class _FakePage:
    def __init__(self, locator: _FakeLocator) -> None:
        self._locator = locator

    def locator(self, selector: str) -> _FakeLocator:
        return self._locator


@pytest.mark.asyncio
async def test_navigation_candidate_is_revalidated_before_click(tmp_path) -> None:
    candidate = {
        "selector": ".forward",
        "text": "",
        "ariaLabel": "forward",
        "title": "",
        "className": "forward",
        "href": None,
    }
    ambiguous = JumpPlusProbe(
        page=_FakePage(_FakeLocator(2)),
        output_dir=tmp_path,
        expected_episode_id="13932016480029111789",
    )
    assert await ambiguous.revalidate_navigation_candidate(candidate) is None

    mismatch = JumpPlusProbe(
        page=_FakePage(_FakeLocator(1, {"aria-label": "back", "class": "back"})),
        output_dir=tmp_path,
        expected_episode_id="13932016480029111789",
    )
    assert await mismatch.revalidate_navigation_candidate(candidate) is None


def test_classify_resource_prefers_content_type_and_handles_fetch() -> None:
    assert classify_resource("image", "image/webp", "https://cdn.test/page") == "image"
    assert classify_resource("fetch", "application/json; charset=utf-8", "https://api.test") == "json"
    assert classify_resource("xhr", "", "https://api.test") == "fetch/xhr"
    assert classify_resource("script", "text/javascript", "https://cdn.test/app.js") == "script"


class _FailingResponse:
    async def body(self) -> bytes:
        raise RuntimeError("body unavailable")


@pytest.mark.asyncio
async def test_image_body_read_failure_is_recorded_without_failing_probe(tmp_path) -> None:
    probe = JumpPlusProbe(
        page=None,
        output_dir=tmp_path,
        expected_episode_id="13932016480029111789",
    )
    record = {
        "url": "https://cdn.test/page.webp",
        "host": "cdn.test",
        "content_type": "image/webp",
        "body": {},
    }

    await probe._save_image_response(_FailingResponse(), record)

    assert record["body"]["attempted"] is True
    assert "body unavailable" in record["body"]["error"]
    assert probe.saved_images == []


def test_summary_and_report_are_valid_json(tmp_path) -> None:
    probe = JumpPlusProbe(
        page=None,
        output_dir=tmp_path,
        expected_episode_id="13932016480029111789",
    )
    report = {
        "target_url": "https://shonenjumpplus.com/episode/13932016480029111789",
        "target_episode_id": "13932016480029111789",
        "final_url": "https://shonenjumpplus.com/episode/13932016480029111789",
        "steps_requested": 3,
        "states_observed": 0,
        "navigation": [],
        "saved_network_images": [],
        "stopped_reason": None,
        "errors": [],
    }

    probe.write_report(report)

    saved_report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert saved_report["target_episode_id"] == report["target_episode_id"]
    assert "## Capture candidates" in (tmp_path / "summary.md").read_text(encoding="utf-8")


def test_pixel_comparison_reports_exact_and_non_exact(tmp_path) -> None:
    exact_left = tmp_path / "left.png"
    exact_right = tmp_path / "right.png"
    changed = tmp_path / "changed.png"
    Image.new("RGB", (2, 2), (10, 20, 30)).save(exact_left)
    Image.new("RGB", (2, 2), (10, 20, 30)).save(exact_right)
    Image.new("RGB", (2, 2), (11, 20, 30)).save(changed)

    exact = _pixel_comparison(exact_left, exact_right)
    mismatch = _pixel_comparison(exact_left, changed)

    assert exact["exact_pixel_match"] is True
    assert exact["different_pixel_count"] == 0
    assert mismatch["exact_pixel_match"] is False
    assert mismatch["different_pixel_count"] == 4
    assert mismatch["max_channel_difference"] == 1
    dimensions, pixel_sha = _decoded_pixel_sha256(exact_left)
    assert dimensions == [2, 2]
    assert pixel_sha == exact["left_pixel_sha256"]

    dimension_mismatch = tmp_path / "dimension_mismatch.png"
    Image.new("RGB", (1, 2), (10, 20, 30)).save(dimension_mismatch)
    assert _pixel_comparison(exact_left, dimension_mismatch)["exact_pixel_match"] is False


def test_draw_geometry_classification_is_observation_based() -> None:
    full_copy = {
        "canvas": {"width": 764, "height": 1200},
        "source": {"naturalWidth": 764, "naturalHeight": 1200},
        "sourceRect": {"sx": 0, "sy": 0, "sw": 764, "sh": 1200},
        "destinationRect": {"dx": 0, "dy": 0, "dw": 764, "dh": 1200},
        "transform": {"a": 1, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0},
    }
    cropped = {**full_copy, "sourceRect": {"sx": 0, "sy": 0, "sw": 100, "sh": 100}}
    assert classify_draw_geometry([full_copy]) == "full_frame_copy"
    assert classify_draw_geometry([cropped, cropped]) == "tiled"
    assert classify_draw_geometry([]) == "unknown"


def test_draw_calls_are_separated_by_canvas_id_not_dimensions() -> None:
    calls = [
        {"sequence": 1, "canvas": {"id": 7, "width": 764, "height": 1200}},
        {"sequence": 2, "canvas": {"id": 8, "width": 764, "height": 1200}},
    ]
    assert draw_calls_for_canvas(calls, 7) == [calls[0]]
    assert draw_calls_for_canvas(calls, 8) == [calls[1]]
    assert draw_calls_for_canvas(calls, None) == []
