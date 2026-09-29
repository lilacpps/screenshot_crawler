from __future__ import annotations

import importlib.util
import io
import sys
import zipfile
from pathlib import Path

from PIL import Image

SCRIPT_PATH = (
    Path(__file__).parents[2] / "scripts" / "benchmark_bookwalker_lossless_webp.py"
)
SPEC = importlib.util.spec_from_file_location("benchmark_bookwalker_lossless_webp", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
benchmark = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = benchmark
SPEC.loader.exec_module(benchmark)


def _png_bytes(mode: str, size: tuple[int, int] = (4, 3)) -> bytes:
    image = Image.new(mode, size)
    if mode == "RGB":
        pixels = image.load()
        for y in range(size[1]):
            for x in range(size[0]):
                pixels[x, y] = (x * 30, y * 40, (x + y) * 20)
    elif mode == "RGBA":
        pixels = image.load()
        for y in range(size[1]):
            for x in range(size[0]):
                pixels[x, y] = (x * 30, y * 40, (x + y) * 20, 100 + x * 20)
    else:
        image.putdata([index * 20 for index in range(size[0] * size[1])])
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _write_zip(path: Path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)


def test_lossless_webp_roundtrip_preserves_rgba_pixels() -> None:
    png = _png_bytes("RGBA")
    member = benchmark.SampledMember(Path("book.zip"), "page.png", 0, 1, len(png))

    results = benchmark.benchmark_image(
        png, member, settings=(benchmark.WebPSetting(quality=100, method=6),)
    )

    assert len(results) == 1
    assert results[0].pixel_equal is True
    assert (results[0].width, results[0].height, results[0].mode) == (4, 3, "RGBA")


def test_lossless_webp_preserves_hidden_rgb_in_transparent_pixels() -> None:
    image = Image.new("RGBA", (2, 1))
    image.putdata([(10, 20, 30, 0), (200, 100, 50, 255)])
    output = io.BytesIO()
    image.save(output, format="PNG")
    png = output.getvalue()
    member = benchmark.SampledMember(Path("book.zip"), "transparent.png", 0, 1, len(png))

    results = benchmark.benchmark_image(
        png, member, settings=(benchmark.WebPSetting(quality=80, method=4),)
    )

    assert len(results) == 1
    assert results[0].pixel_equal is True


def test_sampling_is_deterministic_and_spans_each_archive() -> None:
    inventories = (
        benchmark.ArchiveInventory(
            Path("a.zip"), tuple((f"a-{index}.png", 10) for index in range(10))
        ),
        benchmark.ArchiveInventory(
            Path("b.zip"), tuple((f"b-{index}.png", 10) for index in range(10))
        ),
    )

    first = benchmark.sample_members(inventories, max_images=6)
    second = benchmark.sample_members(inventories, max_images=6)

    assert first == second
    assert [member.member_name for member in first] == [
        "a-0.png",
        "a-5.png",
        "a-9.png",
        "b-0.png",
        "b-5.png",
        "b-9.png",
    ]


def test_discover_zip_paths_accepts_directories_and_deduplicates(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    first = tmp_path / "first.zip"
    second = nested / "second.zip"
    _write_zip(first, {"page.png": _png_bytes("L")})
    _write_zip(second, {"page.png": _png_bytes("L")})

    paths = benchmark.discover_zip_paths([first, tmp_path])

    assert paths == (first.resolve(), second.resolve())


def test_benchmark_ignores_non_png_members_and_preserves_zip(tmp_path: Path) -> None:
    png_a = _png_bytes("L")
    png_b = _png_bytes("RGB")
    archive_path = tmp_path / "book.zip"
    _write_zip(
        archive_path,
        {
            "001.png": png_a,
            "002.jpg": b"not a JPEG needed for this test",
            "003.webp": b"not a WebP needed for this test",
            "004.txt": b"ignored",
            "005.PNG": png_b,
        },
    )
    before = archive_path.read_bytes()

    report = benchmark.benchmark_paths([archive_path], max_images=100)

    assert archive_path.read_bytes() == before
    assert len(report.sampled_members) == 2
    assert {member.member_name for member in report.sampled_members} == {
        "001.png",
        "005.PNG",
    }
    summary = report.summaries["q80/m4"]
    assert summary.images == 2
    assert summary.png_total == len(png_a) + len(png_b)
    assert summary.webp_total == sum(
        result.webp_bytes
        for result in report.image_results
        if result.setting == "q80/m4"
    )
    assert summary.saved_bytes == summary.png_total - summary.webp_total
    assert summary.mismatch_count == 0
    assert summary.groups["grayscale"].images == 1
    assert summary.groups["color"].images == 1
