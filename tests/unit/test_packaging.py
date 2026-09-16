import zipfile

from screenshot_crawler.core.packaging import archive_stem, package_crawl_output


def test_archive_stem_follows_title_rule() -> None:
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


def test_package_crawl_output_creates_library_tree_and_zip(tmp_path) -> None:
    crawl_dir = tmp_path / "crawl"
    crawl_dir.mkdir()
    (crawl_dir / "page-0001.png").write_bytes(b"png")
    (crawl_dir / "manifest.json").write_text("{}\n", encoding="utf-8")
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
        tmp_path / "crawl-status" / "作品名-第01巻-著者.json"
    )
    assert not crawl_dir.exists()
    with zipfile.ZipFile(result.archive_path) as archive:
        assert sorted(archive.namelist()) == [
            "作品名-第01巻-著者/page-0001.png",
        ]
