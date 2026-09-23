from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
from PIL import Image

from screenshot_crawler import cli
from screenshot_crawler.core.capture import CaptureResult
from screenshot_crawler.core.errors import UnsupportedAccessStrategyError
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


def test_jumpplus_is_viewer_only_registry_entry() -> None:
    assert isinstance(cli._registry().create("jumpplus"), JumpPlusAdapter)
    assert "jumpplus" not in cli._discovery_registry().sites()
    assert "jumpplus" not in cli._batch_policy_registry().sites()


def test_jumpplus_renderer_hook_is_lightweight_and_tracks_mutations() -> None:
    for marker in ("sourceId", "drawImage", "snapshotSources", "clearRect", "fillRect", "putImageData", "strokeText"):
        assert marker in _CANVAS_HOOK
    assert JumpPlusAdapter._native_candidate_status("unique")
    assert JumpPlusAdapter._native_candidate_status("equivalent_multiple")
    assert not JumpPlusAdapter._native_candidate_status("ambiguous")


def test_capture_result_extensions_match_native_provenance() -> None:
    assert CaptureResult(b"x", 1, 1, "image/jpeg", ".jpg").file_extension == ".jpg"
