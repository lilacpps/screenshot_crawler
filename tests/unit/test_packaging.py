import json
import zipfile
from pathlib import Path

import pytest

from screenshot_crawler.core.packaging import (
    archive_stem,
    package_crawl_output,
    resolve_output_metadata,
)


def test_resolve_output_metadata_merges_each_field() -> None:
    resolved = resolve_output_metadata(
        {
            "title": "Explicit title",
            "order": "第12巻",
            "author": None,
        },
        {
            "title": "Adapter title",
            "order": "12",
            "author": "Adapter author",
            "genre": "漫画",
            "volume": "legacy volume",
        },
    )

    assert resolved == {
        "title": "Explicit title",
        "order": "第12巻",
        "author": "Adapter author",
        "genre": "漫画",
        "volume": "legacy volume",
    }


@pytest.mark.parametrize("empty_value", [None, "", "  "])
def test_resolve_output_metadata_ignores_empty_explicit_values(empty_value: str | None) -> None:
    resolved = resolve_output_metadata(
        {"title": empty_value},
        {"title": "Adapter title"},
    )

    assert resolved["title"] == "Adapter title"


def test_package_metadata_override_does_not_change_manifest_source_url(tmp_path) -> None:
    crawl_dir = tmp_path / "crawl"
    crawl_dir.mkdir()
    (crawl_dir / "page-0001.png").write_bytes(b"png")
    (crawl_dir / "manifest.json").write_text(
        json.dumps(
            {
                "source_url": "https://actual.test/viewer",
                "pages": [{"file": "page-0001.png"}],
            }
        ),
        encoding="utf-8",
    )
    (crawl_dir / "progress.json").write_text("{}\n", encoding="utf-8")
    (crawl_dir / "keep.txt").write_text("unrelated file\n", encoding="utf-8")

    result = package_crawl_output(
        crawl_dir,
        {"title": "Adapter title", "genre": "漫画"},
        explicit_metadata={"title": "Explicit title"},
        library_dir=tmp_path / "Books",
    )

    assert result.title == "Explicit title"
    assert json.loads((crawl_dir / "manifest.json").read_text(encoding="utf-8"))["source_url"] == (
        "https://actual.test/viewer"
    )


def test_archive_stem_includes_short_title_and_preserves_legacy_order() -> None:
    stem, title, genre, volume, author = archive_stem(
        {
            "title": "作品名",
            "volume": "第04巻",
            "author": "著者A・著者B",
            "genre": "小説",
        }
    )
    assert stem == "作品名-第04巻-著者A・著者B"
    assert (title, genre, volume, author) == (
        "作品名",
        "小説",
        "第04巻",
        "著者A・著者B",
    )


def test_archive_stem_accepts_generic_order_for_episode_archives() -> None:
    stem, title, genre, order, author = archive_stem(
        {
            "title": "作品名",
            "order": "第01話-前編",
            "genre": "漫画",
        }
    )
    assert stem == "作品名-第01話-前編"
    assert (title, genre, order, author) == ("作品名", "漫画", "第01話-前編", None)


def test_archive_stem_places_optional_prefix_before_order() -> None:
    stem, title, genre, order, author = archive_stem(
        {
            "title": "作品名",
            "order": "番外編",
            "author": "著者",
            "genre": "漫画",
        },
        artifact_prefix="003/",
        artifact_disambiguator="site-123",
    )

    assert stem == "003-作品名-番外編-著者-site-123"
    assert (title, genre, order, author) == ("作品名", "漫画", "番外編", "著者")


def test_archive_stem_appends_optional_disambiguator_after_author() -> None:
    stem, title, genre, order, author = archive_stem(
        {
            "title": "作品名",
            "order": "おまけ",
            "author": "著者",
            "genre": "漫画",
        },
        artifact_disambiguator="mangaone-214131",
    )

    assert stem == "作品名-おまけ-著者-mangaone-214131"
    assert (title, genre, order, author) == ("作品名", "漫画", "おまけ", "著者")


def test_archive_stem_without_disambiguator_is_unchanged() -> None:
    stem, *_ = archive_stem({"title": "作品名", "order": "第80話", "genre": "漫画"})

    assert stem == "作品名-第80話"


def test_archive_stem_prefix_without_order_is_retained() -> None:
    stem, *_ = archive_stem(
        {"title": "作品名", "genre": "漫画"},
        artifact_prefix="003",
    )

    assert stem == "003-作品名"


def test_archive_stem_falls_back_when_all_filename_components_are_empty() -> None:
    long_title = "長" * 50
    stem, title, genre, order, author = archive_stem(
        {"title": long_title, "genre": "漫画"}
    )

    assert stem == "archive"
    assert (title, genre, order, author) == (long_title, "漫画", None, None)


@pytest.mark.parametrize(
    ("title", "expected_in_stem"),
    [("短" * 49, True), ("長" * 50, False)],
)
def test_archive_stem_uses_sanitized_title_length_threshold(
    title: str, expected_in_stem: bool
) -> None:
    stem, *_ = archive_stem(
        {"title": title, "order": "第01話", "genre": "漫画"}
    )

    expected_stem = f"{title}-第01話" if expected_in_stem else "第01話"
    assert stem == expected_stem


def test_position_prefixed_metadata_names_archive_and_status(tmp_path) -> None:
    crawl_dir = tmp_path / "crawl"
    crawl_dir.mkdir()
    (crawl_dir / "page-0001.png").write_bytes(b"png")
    (crawl_dir / "manifest.json").write_text(
        json.dumps({"pages": [{"file": "page-0001.png"}]}), encoding="utf-8"
    )
    (crawl_dir / "progress.json").write_text("{}\n", encoding="utf-8")

    result = package_crawl_output(
        crawl_dir,
        {"title": "作品名", "order": "番外編", "genre": "漫画"},
        artifact_prefix="003",
        library_dir=tmp_path / "Books",
    )

    assert result.archive_path == (
        tmp_path / "Books" / "漫画" / "作品名" / "003-作品名-番外編.zip"
    )
    assert result.status_path == (
        tmp_path
        / "crawl-status"
        / result.genre
        / result.title
        / "003-作品名-番外編.json"
    )


def test_position_prefix_does_not_change_library_directory(tmp_path) -> None:
    crawl_dir = tmp_path / "crawl"
    crawl_dir.mkdir()
    (crawl_dir / "page-0001.png").write_bytes(b"png")
    (crawl_dir / "manifest.json").write_text(
        json.dumps({"pages": [{"file": "page-0001.png"}]}), encoding="utf-8"
    )
    (crawl_dir / "progress.json").write_text("{}\n", encoding="utf-8")

    result = package_crawl_output(
        crawl_dir,
        {"title": "作品名", "order": "第01話", "genre": "漫画"},
        artifact_prefix="001",
        library_dir=tmp_path / "Books",
    )

    assert result.archive_path.parent == tmp_path / "Books" / "漫画" / "作品名"
    assert not (tmp_path / "Books" / "漫画" / "001-作品名").exists()


def test_package_crawl_output_creates_library_tree_and_zip(tmp_path) -> None:
    crawl_dir = tmp_path / "crawl"
    crawl_dir.mkdir()
    (crawl_dir / "page-0001.png").write_bytes(b"png")
    (crawl_dir / "manifest.json").write_text(
        json.dumps({"pages": [{"file": "page-0001.png"}]}), encoding="utf-8"
    )
    (crawl_dir / "progress.json").write_text("{}\n", encoding="utf-8")

    result = package_crawl_output(
        crawl_dir,
        {
            "title": "作品名",
            "volume": "第01巻",
            "author": "著者",
            "genre": "小説",
        },
        library_dir=tmp_path / "Books",
    )

    assert result.archive_path == (
        tmp_path / "Books" / "小説" / "作品名" / "作品名-第01巻-著者.zip"
    )
    assert result.status_path == (
        tmp_path
        / "crawl-status"
        / result.genre
        / result.title
        / "作品名-第01巻-著者.json"
    )
    assert not crawl_dir.exists()
    with zipfile.ZipFile(result.archive_path) as archive:
        assert archive.namelist() == ["page-0001.png"]


def test_package_uses_manifest_files_and_ignores_extra_png(tmp_path) -> None:
    crawl_dir = tmp_path / "crawl"
    crawl_dir.mkdir()
    (crawl_dir / "page-0001.png").write_bytes(b"declared")
    (crawl_dir / "page-9999.png").write_bytes(b"old-run")
    (crawl_dir / "manifest.json").write_text(
        json.dumps({"pages": [{"file": "page-0001.png"}]}), encoding="utf-8"
    )
    (crawl_dir / "progress.json").write_text("{}\n", encoding="utf-8")

    result = package_crawl_output(
        crawl_dir,
        {"title": "作品名", "genre": "漫画"},
        library_dir=tmp_path / "Books",
    )

    with zipfile.ZipFile(result.archive_path) as archive:
        assert archive.namelist() == ["page-0001.png"]
    assert (crawl_dir / "page-9999.png").exists()


def test_package_supports_mixed_native_webp_and_fallback_png(tmp_path) -> None:
    crawl_dir = tmp_path / "crawl"
    crawl_dir.mkdir()
    (crawl_dir / "page-0001.webp").write_bytes(b"native")
    (crawl_dir / "page-0002.png").write_bytes(b"fallback")
    (crawl_dir / "manifest.json").write_text(
        json.dumps(
            {
                "pages": [
                    {"file": "page-0001.webp", "mime_type": "image/webp"},
                    {"file": "page-0002.png", "mime_type": "image/png"},
                ]
            }
        ),
        encoding="utf-8",
    )
    (crawl_dir / "progress.json").write_text("{}\n", encoding="utf-8")

    result = package_crawl_output(
        crawl_dir,
        {"title": "作品名", "genre": "漫画"},
        library_dir=tmp_path / "Books",
    )

    with zipfile.ZipFile(result.archive_path) as archive:
        assert archive.namelist() == [
            "page-0001.webp",
            "page-0002.png",
        ]


def test_package_supports_original_jpeg_artifact(tmp_path) -> None:
    crawl_dir = tmp_path / "crawl"
    crawl_dir.mkdir()
    (crawl_dir / "page-0001.jpg").write_bytes(b"jpeg")
    (crawl_dir / "manifest.json").write_text(
        json.dumps(
            {
                "pages": [
                    {"file": "page-0001.jpg", "mime_type": "image/jpeg"},
                ]
            }
        ),
        encoding="utf-8",
    )
    (crawl_dir / "progress.json").write_text("{}\n", encoding="utf-8")

    result = package_crawl_output(
        crawl_dir,
        {"title": "菴懷刀蜷・", "genre": "貍ｫ逕ｻ"},
        library_dir=tmp_path / "Books",
    )

    with zipfile.ZipFile(result.archive_path) as archive:
        assert archive.namelist() == ["page-0001.jpg"]


def test_package_does_not_rmtree_unrelated_files(tmp_path) -> None:
    crawl_dir = tmp_path / "crawl"
    crawl_dir.mkdir()
    (crawl_dir / "page-0001.png").write_bytes(b"declared")
    unrelated = crawl_dir / "notes.txt"
    unrelated.write_text("keep", encoding="utf-8")
    (crawl_dir / "manifest.json").write_text(
        json.dumps({"pages": [{"file": "page-0001.png"}]}), encoding="utf-8"
    )
    (crawl_dir / "progress.json").write_text("{}\n", encoding="utf-8")

    result = package_crawl_output(
        crawl_dir,
        {"title": "作品名", "genre": "漫画"},
        library_dir=tmp_path / "Books",
    )

    assert result.archive_path.exists()
    assert crawl_dir.exists()
    assert unrelated.read_text(encoding="utf-8") == "keep"


def test_package_disambiguator_updates_archive_and_status_name_only(tmp_path) -> None:
    crawl_dir = tmp_path / "crawl"
    crawl_dir.mkdir()
    (crawl_dir / "page-0001.png").write_bytes(b"png")
    (crawl_dir / "manifest.json").write_text(
        json.dumps({"pages": [{"file": "page-0001.png"}]}), encoding="utf-8"
    )
    (crawl_dir / "progress.json").write_text("{}\n", encoding="utf-8")

    result = package_crawl_output(
        crawl_dir,
        {"title": "作品名", "order": "おまけ", "genre": "漫画"},
        artifact_disambiguator="mangaone-214131",
        library_dir=tmp_path / "Books",
    )

    expected_stem = "作品名-おまけ-mangaone-214131"
    assert result.archive_path == (
        tmp_path / "Books" / "漫画" / "作品名" / f"{expected_stem}.zip"
    )
    assert result.status_path == (
        tmp_path
        / "crawl-status"
        / result.genre
        / result.title
        / f"{expected_stem}.json"
    )
    with zipfile.ZipFile(result.archive_path) as archive:
        assert archive.namelist() == ["page-0001.png"]


def test_package_same_disambiguated_destination_still_raises(tmp_path) -> None:
    def make_crawl(name: str) -> Path:
        crawl_dir = tmp_path / name
        crawl_dir.mkdir()
        (crawl_dir / "page-0001.png").write_bytes(b"png")
        (crawl_dir / "manifest.json").write_text(
            json.dumps({"pages": [{"file": "page-0001.png"}]}), encoding="utf-8"
        )
        (crawl_dir / "progress.json").write_text("{}\n", encoding="utf-8")
        return crawl_dir

    library_dir = tmp_path / "Books"
    metadata = {"title": "作品名", "order": "おまけ", "genre": "漫画"}
    package_crawl_output(
        make_crawl("first"),
        metadata,
        artifact_disambiguator="mangaone-214131",
        library_dir=library_dir,
    )

    second = package_crawl_output(
        make_crawl("different-chapter"),
        metadata,
        artifact_disambiguator="mangaone-214987",
        library_dir=library_dir,
    )
    assert second.archive_path.name == "作品名-おまけ-mangaone-214987.zip"

    with pytest.raises(FileExistsError, match="Archive already exists"):
        package_crawl_output(
            make_crawl("same-chapter"),
            metadata,
            artifact_disambiguator="mangaone-214131",
            library_dir=library_dir,
        )


def test_long_title_stays_in_directory_and_not_archive_name(tmp_path) -> None:
    crawl_dir = tmp_path / "crawl"
    crawl_dir.mkdir()
    (crawl_dir / "page-0001.png").write_bytes(b"png")
    (crawl_dir / "manifest.json").write_text(
        json.dumps({"pages": [{"file": "page-0001.png"}]}), encoding="utf-8"
    )
    (crawl_dir / "progress.json").write_text("{}\n", encoding="utf-8")
    title = (
        "追放されたチート付与魔術師は気ままなセカンドライフを謳歌する。 "
        "～俺は武器だけじゃなく、あらゆるものに『強化ポイント』を付与できるし、"
        "俺の意思でいつでも効果を解除できるけど、残った人たち大丈夫？～"
    )

    result = package_crawl_output(
        crawl_dir,
        {"title": title, "order": "第９５話", "author": "業務用餅六志麻あさｋｉｓｕｉ", "genre": "漫画"},
        artifact_prefix="103",
        library_dir=tmp_path / "Books",
    )

    assert result.archive_path.parent.name == title
    assert result.archive_path.name == "103-第９５話-業務用餅六志麻あさｋｉｓｕｉ.zip"
    assert title not in result.archive_path.name
    assert result.status_path == (
        tmp_path
        / "crawl-status"
        / result.genre
        / result.title
        / result.archive_path.with_suffix(".json").name
    )
    assert len(str(result.archive_path)) < 260


def test_status_paths_are_work_scoped_for_same_long_titleless_stem(tmp_path) -> None:
    def make_crawl(name: str) -> Path:
        crawl_dir = tmp_path / name
        crawl_dir.mkdir()
        (crawl_dir / "page-0001.png").write_bytes(b"png")
        (crawl_dir / "manifest.json").write_text(
            json.dumps({"pages": [{"file": "page-0001.png"}]}), encoding="utf-8"
        )
        (crawl_dir / "progress.json").write_text("{}\n", encoding="utf-8")
        return crawl_dir

    title_a = "A" * 50
    title_b = "B" * 50
    metadata = {"order": "001", "genre": "manga"}
    first = package_crawl_output(
        make_crawl("work-a"), {**metadata, "title": title_a}, library_dir=tmp_path / "Books"
    )
    second = package_crawl_output(
        make_crawl("work-b"), {**metadata, "title": title_b}, library_dir=tmp_path / "Books"
    )

    assert first.archive_path.name == second.archive_path.name == "001.zip"
    assert first.archive_path.parent != second.archive_path.parent
    assert first.status_path == (
        tmp_path / "crawl-status" / "manga" / title_a / "001.json"
    )
    assert second.status_path == (
        tmp_path / "crawl-status" / "manga" / title_b / "001.json"
    )
    assert first.status_path != second.status_path
    assert first.status_path.is_file()
    assert second.status_path.is_file()


def test_package_fails_when_manifest_page_is_missing(tmp_path) -> None:
    crawl_dir = tmp_path / "crawl"
    crawl_dir.mkdir()
    (crawl_dir / "manifest.json").write_text(
        json.dumps({"pages": [{"file": "page-0001.png"}]}), encoding="utf-8"
    )
    (crawl_dir / "progress.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="Manifest page file not found"):
        package_crawl_output(
            crawl_dir,
            {"title": "作品名", "genre": "漫画"},
            library_dir=tmp_path / "Books",
        )
