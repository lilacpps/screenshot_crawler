from __future__ import annotations

import importlib.util
import io
import sys
import zipfile
from pathlib import Path

from PIL import Image

SCRIPT_PATH = (
    Path(__file__).parents[2] / "scripts" / "benchmark_bookwalker_text_compression.py"
)
SPEC = importlib.util.spec_from_file_location("benchmark_bookwalker_text_compression", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
benchmark = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = benchmark
SPEC.loader.exec_module(benchmark)


def _png_bytes() -> bytes:
    image = Image.new("RGBA", (32, 24))
    image.putdata(
        [
            (0 if (x + y) % 3 else 255, 0 if x % 2 else 255, 0, 255)
            for y in range(24)
            for x in range(32)
        ]
    )
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_quantized_png_uses_requested_bit_depth_and_levels() -> None:
    with Image.open(io.BytesIO(_png_bytes())) as image:
        image.load()
        for bits, expected_levels in ((4, 16), (2, 4), (1, 2)):
            encoded, fallback = benchmark._quantized_palette_png(image, bits)
            assert fallback is None
            with Image.open(io.BytesIO(encoded)) as decoded:
                decoded.load()
                _mode, actual_bits = benchmark._png_bit_depth(encoded)
                assert actual_bits == bits
                assert len(decoded.convert("L").getcolors(1_000_000)) <= expected_levels


def test_benchmark_writes_six_variants_crops_and_preserves_input(tmp_path: Path) -> None:
    page = tmp_path / "page-0151.png"
    page.write_bytes(_png_bytes())
    before = page.read_bytes()
    output_dir = tmp_path / "result"

    results, _ = benchmark.benchmark_pages(
        [benchmark.PageSpec(str(page), "page-0151")], output_dir
    )

    assert [result.variant for result in results] == list(benchmark.VARIANT_NAMES)
    assert page.read_bytes() == before
    page_dir = output_dir / "page-0151"
    assert (page_dir / "original.png").read_bytes() == before
    assert (page_dir / "gray-4bit.png").exists()
    assert (page_dir / "gray-2bit.png").exists()
    assert (page_dir / "gray-1bit.png").exists()
    assert (page_dir / "crops" / "gray-1bit-center.png").exists()


def test_benchmark_reads_zip_member_without_modifying_zip(tmp_path: Path) -> None:
    archive_path = tmp_path / "book.zip"
    png = _png_bytes()
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("page-0151.png", png)
    before = archive_path.read_bytes()

    results, _ = benchmark.benchmark_pages(
        [benchmark.PageSpec(f"{archive_path}::page-0151.png", "page-0151")],
        tmp_path / "result",
    )

    assert len(results) == 6
    assert archive_path.read_bytes() == before
    assert results[1].pixel_exact is True
