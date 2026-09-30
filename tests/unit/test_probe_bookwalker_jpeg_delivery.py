from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

SCRIPT_PATH = (
    Path(__file__).parents[2] / "scripts" / "probe_bookwalker_jpeg_delivery.py"
)
SPEC = importlib.util.spec_from_file_location("probe_bookwalker_jpeg_delivery", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)


def _jpeg_bytes(*, quality: int = 75, progressive: bool = False) -> bytes:
    image = Image.new("RGB", (16, 12), (40, 80, 120))
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=quality, progressive=progressive)
    return output.getvalue()


def test_magic_type_uses_body_signatures() -> None:
    assert probe.magic_type(b"\xff\xd8\xff\xe0") == "jpeg"
    assert probe.magic_type(b"\x89PNG\r\n\x1a\n") == "png"
    assert probe.magic_type(b"RIFF\x00\x00\x00\x00WEBP") == "webp"
    assert probe.magic_type(b"GIF89a") == "gif"
    assert probe.magic_type(b"\x00\x00\x00\x18ftypavif") == "avif"
    assert probe.magic_type(b"not-an-image") == "unknown"


def test_case_a_is_detectable_but_outside_current_production_filter() -> None:
    url = "https://images.bookwalker.jp/content/opaque-token"
    assert probe.magic_type(_jpeg_bytes()) == "jpeg"
    assert probe.current_route_pattern_match(url) is False
    assert probe.current_original_filter_match(
        url=url,
        resource_type="xhr",
        headers={"content-type": "application/octet-stream"},
    ) is False


def test_case_b_matches_current_filter() -> None:
    url = "https://viewer-epubs-trial.bookwalker.jp/opaque-token"
    assert probe.current_route_pattern_match(url) is True
    assert probe.current_original_filter_match(
        url=url,
        resource_type="xhr",
        headers={"content-type": "image/jpeg"},
    ) is True


def test_jpeg_metadata_reports_exact_quality_and_tables() -> None:
    metadata = probe.jpeg_metadata(_jpeg_bytes(quality=75, progressive=True))
    assert (metadata["width"], metadata["height"]) == (16, 12)
    assert metadata["progressive"] is True
    assert metadata["subsampling"] == "4:2:0"
    assert metadata["estimated_quality"] == 75
    assert set(metadata["quantization_tables"]) == {"0", "1"}
    assert len(metadata["sha256"]) == 64


class _FakeResponse:
    def __init__(self, body: bytes, *, content_length: str | None = None) -> None:
        self.url = "https://viewer-epubs-trial.bookwalker.jp/opaque-token"
        self.status = 200
        self.headers = {
            "content-type": "application/octet-stream",
            **({"content-length": content_length} if content_length else {}),
        }
        self.request = SimpleNamespace(
            resource_type="xhr",
            method="GET",
        )
        self._body = body
        self.body_calls = 0

    async def body(self) -> bytes:
        self.body_calls += 1
        return self._body


@pytest.mark.asyncio
async def test_response_body_size_limit_skips_known_oversize_body() -> None:
    response = _FakeResponse(b"too-large", content_length="9")
    collector = probe.ResponseCollector(max_body_bytes=8)
    collector.on_response(response)  # type: ignore[arg-type]
    await collector.drain()

    assert response.body_calls == 0
    assert collector.records[0]["body_read_status"] == "skipped_content_length_limit"
    assert collector.candidates == []


@pytest.mark.asyncio
async def test_case_c_classifies_unique_dimension_and_signature_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = _jpeg_bytes()
    metadata = probe.jpeg_metadata(body)
    candidate = probe.MagicJpegCandidate(
        body=body,
        record_index=1,
        page_index=1,
        metadata=metadata,
        url="https://viewer-epubs-trial.bookwalker.jp/opaque-token",
        hostname="viewer-epubs-trial.bookwalker.jp",
        path="/opaque-token",
        resource_type="xhr",
        content_type="image/jpeg",
        route_match=True,
        filter_match=True,
    )

    async def fake_signature(_page: object, _data: bytes, _mime_type: str) -> str:
        return "same-signature"

    monkeypatch.setattr(probe, "image_signature", fake_signature)
    classification, details = await probe.classify_page(
        SimpleNamespace(),
        [
            {
                "width": metadata["width"],
                "height": metadata["height"],
                "signature": "same-signature",
                "source_constructor": "ImageBitmap",
            }
        ],
        [candidate],
        {},
    )

    assert classification == "JPEG_EXACT_MATCH_CURRENT_FILTER"
    assert details["dimension_matches"] == 1
    assert details["signature_matches"] == 1
    assert details["unique_exact_match"] is True
