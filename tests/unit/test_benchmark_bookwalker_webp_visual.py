from __future__ import annotations

import importlib.util
import io
import json
import sys
import zipfile
from pathlib import Path

from PIL import Image

SCRIPT_PATH = (
    Path(__file__).parents[2] / "scripts" / "benchmark_bookwalker_webp_visual.py"
)
SPEC = importlib.util.spec_from_file_location("benchmark_bookwalker_webp_visual", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
benchmark = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = benchmark
SPEC.loader.exec_module(benchmark)


def _png_bytes() -> bytes:
    image = Image.new("RGBA", (8, 6))
    image.putdata(
        [
            (x * 20, y * 30, (x + y) * 15, 255)
            for y in range(6)
            for x in range(8)
        ]
    )
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_visual_benchmark_writes_variants_crops_and_metrics(tmp_path: Path) -> None:
    page = tmp_path / "page-0151.png"
    page.write_bytes(_png_bytes())
    output_dir = tmp_path / "result"

    results, metadata = benchmark.benchmark_pages(
        [benchmark.PageSpec(str(page), "text-heavy", "page-0151")],
        output_dir,
    )

    assert len(results) == len(benchmark.VARIANTS)
    assert {result.page for result in results} == {"page-0151"}
    assert all(result.webp_bytes > 0 for result in results)
    assert all(result.psnr_db is not None for result in results[1:])
    assert (output_dir / "page-0151-text-heavy" / "original.png").read_bytes() == page.read_bytes()
    assert (
        output_dir / "page-0151-text-heavy" / "crops" / "lossy-q80-m2-center.png"
    ).exists()
    assert metadata["near_lossless"]["supported"] is False


def test_visual_benchmark_reads_zip_member_without_modifying_zip(tmp_path: Path) -> None:
    archive_path = tmp_path / "book.zip"
    png = _png_bytes()
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("page-0001.png", png)
        archive.writestr("page-0002.jpg", b"ignored")
    before = archive_path.read_bytes()

    results, _ = benchmark.benchmark_pages(
        [benchmark.PageSpec(f"{archive_path}::page-0001.png", "illustration", "page-0001")],
        tmp_path / "result",
        variants=(benchmark.VARIANTS[0],),
    )

    assert len(results) == 1
    assert results[0].pixel_exact is True
    assert archive_path.read_bytes() == before


def test_summary_json_is_serializable(tmp_path: Path) -> None:
    page = tmp_path / "page.png"
    page.write_bytes(_png_bytes())
    results, metadata = benchmark.benchmark_pages(
        [benchmark.PageSpec(str(page), "unspecified", "page")], tmp_path / "result"
    )
    summary = benchmark._write_summary(results, metadata, tmp_path / "result")

    payload = json.loads(summary.read_text(encoding="utf-8"))
    assert len(payload["results"]) == len(benchmark.VARIANTS)
