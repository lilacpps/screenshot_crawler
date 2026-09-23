from __future__ import annotations

import json

import pytest

from poc.jumpplus_probe import (
    JumpPlusProbe,
    classify_resource,
    extract_episode_id,
    is_target_episode_url,
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
