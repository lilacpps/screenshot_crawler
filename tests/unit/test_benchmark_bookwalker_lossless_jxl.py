from __future__ import annotations

import importlib.util
import io
import sys
import zipfile
from pathlib import Path

import pytest
from PIL import Image

SCRIPT_PATH = (
    Path(__file__).parents[2] / "scripts" / "benchmark_bookwalker_lossless_jxl.py"
)
SPEC = importlib.util.spec_from_file_location("benchmark_bookwalker_lossless_jxl", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
benchmark = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = benchmark
SPEC.loader.exec_module(benchmark)


def _png_bytes(mode: str = "RGBA", size: tuple[int, int] = (4, 3)) -> bytes:
    image = Image.new(mode, size)
    if mode == "RGBA":
        image.putdata(
            [
                (x * 30, y * 40, (x + y) * 20, 0 if x == 0 else 255)
                for y in range(size[1])
                for x in range(size[0])
            ]
        )
    else:
        image.putdata([index * 20 for index in range(size[0] * size[1])])
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _write_zip(path: Path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)


def test_jxl_roundtrip_preserves_hidden_rgb_in_transparent_pixels() -> None:
    pytest.importorskip("pillow_jxl")
    image = Image.new("RGBA", (2, 1))
    image.putdata([(10, 20, 30, 0), (200, 100, 50, 255)])
    output = io.BytesIO()
    image.save(output, format="PNG")
    png = output.getvalue()
    member = benchmark.SampledMember(Path("book.zip"), "transparent.png", 0, 1, len(png))

    results = benchmark.benchmark_image(
        png,
        member,
        settings=(benchmark.BenchmarkSetting.jxl_setting(effort=1),),
    )

    assert len(results) == 1
    assert results[0].pixel_equal is True


def test_jxl_benchmark_ignores_non_png_and_preserves_zip(tmp_path: Path) -> None:
    pytest.importorskip("pillow_jxl")
    png = _png_bytes()
    archive_path = tmp_path / "book.zip"
    _write_zip(
        archive_path,
        {
            "001.png": png,
            "002.jpg": b"ignored",
            "003.webp": b"ignored",
        },
    )
    before = archive_path.read_bytes()

    report = benchmark.benchmark_paths(
        [archive_path],
        max_images=100,
        settings=(benchmark.BenchmarkSetting.jxl_setting(effort=1),),
    )

    assert archive_path.read_bytes() == before
    assert [member.member_name for member in report.sampled_members] == ["001.png"]
    summary = report.summaries["jxl/e1"]
    assert summary.images == 1
    assert summary.mismatch_count == 0


def test_default_settings_include_webp_baselines_and_jxl_efforts() -> None:
    assert tuple(setting.label for setting in benchmark.DEFAULT_SETTINGS) == (
        "webp q40/m2",
        "webp q80/m4",
        "jxl/e1",
        "jxl/e5",
        "jxl/e9",
    )
