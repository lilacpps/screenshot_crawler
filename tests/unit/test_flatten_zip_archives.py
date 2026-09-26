import importlib.util
import sys
import zipfile
from pathlib import Path

SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "flatten_zip_archives.py"
SPEC = importlib.util.spec_from_file_location("flatten_zip_archives", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
flatten_zip_archives = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = flatten_zip_archives
SPEC.loader.exec_module(flatten_zip_archives)


def _write_zip(path: Path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)


def test_process_archive_flattens_images_and_preserves_content(tmp_path: Path) -> None:
    archive_path = tmp_path / "book.zip"
    _write_zip(
        archive_path,
        {
            "book/001.webp": b"webp-1",
            "book/002.png": b"png-2",
            "book/003.jpg": b"jpeg-3",
        },
    )

    result = flatten_zip_archives.process_archive(archive_path)

    assert result.action == "FIX"
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.namelist() == ["001.webp", "002.png", "003.jpg"]
        assert [archive.read(name) for name in archive.namelist()] == [
            b"webp-1",
            b"png-2",
            b"jpeg-3",
        ]
        assert archive.testzip() is None


def test_process_archive_skips_already_flat_zip_without_changing_it(tmp_path: Path) -> None:
    archive_path = tmp_path / "flat.zip"
    _write_zip(archive_path, {"001.webp": b"image"})
    original = archive_path.read_bytes()

    result = flatten_zip_archives.process_archive(archive_path)

    assert result.action == "SKIP"
    assert result.reason == "already flat"
    assert archive_path.read_bytes() == original


def test_process_archive_skips_ambiguous_top_levels(tmp_path: Path) -> None:
    archive_path = tmp_path / "ambiguous.zip"
    _write_zip(
        archive_path,
        {"book1/001.webp": b"one", "book2/001.webp": b"two"},
    )
    original = archive_path.read_bytes()

    result = flatten_zip_archives.process_archive(archive_path)

    assert result.action == "SKIP"
    assert result.reason == "ambiguous structure"
    assert archive_path.read_bytes() == original


def test_process_archive_removes_only_one_level_and_keeps_subdirectories(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "nested.zip"
    _write_zip(archive_path, {"book/chapter1/001.webp": b"image"})

    result = flatten_zip_archives.process_archive(archive_path)

    assert result.action == "FIX"
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.namelist() == ["chapter1/001.webp"]


def test_process_archive_preserves_zipinfo_metadata(tmp_path: Path) -> None:
    archive_path = tmp_path / "metadata.zip"
    info = zipfile.ZipInfo("book/001.webp", date_time=(2020, 1, 2, 3, 4, 6))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.comment = b"page metadata"
    info.external_attr = 0o600 << 16
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(info, b"image")

    assert flatten_zip_archives.process_archive(archive_path).action == "FIX"
    with zipfile.ZipFile(archive_path) as archive:
        output_info = archive.infolist()[0]
        assert output_info.filename == "001.webp"
        assert output_info.date_time == info.date_time
        assert output_info.compress_type == zipfile.ZIP_DEFLATED
        assert output_info.comment == b"page metadata"
        assert output_info.external_attr == info.external_attr


def test_process_archive_keeps_original_for_invalid_zip(tmp_path: Path) -> None:
    archive_path = tmp_path / "broken.zip"
    original = b"not a zip"
    archive_path.write_bytes(original)

    result = flatten_zip_archives.process_archive(archive_path)

    assert result.action == "ERROR"
    assert "BadZipFile" in result.reason
    assert archive_path.read_bytes() == original


def test_dry_run_reports_fix_without_changing_archive(tmp_path: Path) -> None:
    archive_path = tmp_path / "dry-run.zip"
    _write_zip(archive_path, {"book/001.webp": b"image"})
    original = archive_path.read_bytes()

    result = flatten_zip_archives.process_archive(archive_path, dry_run=True)

    assert result.action == "FIX"
    assert archive_path.read_bytes() == original


def test_process_archive_skips_path_traversal_entry(tmp_path: Path) -> None:
    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("book/../001.webp", b"image")
    original = archive_path.read_bytes()

    result = flatten_zip_archives.process_archive(archive_path)

    assert result.action == "SKIP"
    assert result.reason == "unsafe entry name"
    assert archive_path.read_bytes() == original


def test_process_archive_skips_output_name_collision(tmp_path: Path) -> None:
    archive_path = tmp_path / "collision.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("book/001.webp", b"first")
        archive.writestr("book/001.webp", b"second")
    original = archive_path.read_bytes()

    result = flatten_zip_archives.process_archive(archive_path)

    assert result.action == "SKIP"
    assert result.reason == "entry name collision"
    assert archive_path.read_bytes() == original


def test_main_recursively_finds_zips_and_prints_summary(tmp_path: Path, capsys) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    archive_path = nested / "book.zip"
    _write_zip(archive_path, {"book/001.webp": b"image"})
    original = archive_path.read_bytes()

    exit_code = flatten_zip_archives.main(["--dry-run", str(tmp_path)])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert f"FIX   {archive_path} : book/ -> archive root" in output
    assert "Processed: 1" in output
    assert "Fixed:     1" in output
    assert archive_path.read_bytes() == original
