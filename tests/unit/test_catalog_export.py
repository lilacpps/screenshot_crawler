import csv
from pathlib import Path

import pytest

from screenshot_crawler.catalog import CatalogService, ItemInput, SourceInput
from screenshot_crawler.catalog.export import (
    EXPORT_COLUMNS,
    CatalogExportError,
    export_catalog_csv,
)


def make_source(external_id: str, **overrides: object) -> SourceInput:
    values: dict[str, object] = {
        "site": "mangaone",
        "external_id": external_id,
        "discovery_key": "juou-to-yakusou",
        "url": f"https://manga-one.example/chapter/{external_id}",
        "access_mode": "free",
        "free_until": "2026-09-18T12:00:00+09:00",
        "available": True,
        "access_checked_at": "2026-09-17T12:00:00+09:00",
        "last_seen_at": "2026-09-17T12:00:00+09:00",
    }
    values.update(overrides)
    return SourceInput(**values)


def read_export(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def test_joined_export_includes_item_and_source_metadata(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.sqlite"
    output_path = tmp_path / "catalog-export.csv"
    service = CatalogService(catalog_path)
    first = service.upsert_item_source(
        ItemInput(
            canonical_title="item A",
            author="author A",
            genre="漫画",
            kind="episode",
            order_key="1",
            order_label="第1話",
        ),
        make_source("mangaone-A"),
    )
    second = service.upsert_item_source(
        ItemInput(canonical_title="item B", author="author B"),
        make_source("mangaone-B", access_mode="paid", available=False),
    )

    result = export_catalog_csv(catalog_path, output_path)
    rows = read_export(output_path)

    assert result.rows == 2
    assert list(rows[0]) == list(EXPORT_COLUMNS)
    assert [row["item_id"] for row in rows] == [str(first.item.id), str(second.item.id)]
    assert rows[0]["source_id"] == str(first.source.id)
    assert rows[0]["available"] == "true"
    assert rows[0]["external_id"] == "mangaone-A"
    assert rows[0]["access_mode"] == "free"
    assert rows[1]["external_id"] == "mangaone-B"
    assert rows[1]["access_mode"] == "paid"


def test_export_preserves_japanese_and_writes_utf8_bom(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.sqlite"
    output_path = tmp_path / "nested" / "catalog-export.csv"
    service = CatalogService(catalog_path)
    service.upsert_item_source(
        ItemInput(
            canonical_title="獣王と薬草",
            genre="漫画",
            order_label="第80話-後編",
        ),
        make_source("80-late"),
    )

    export_catalog_csv(catalog_path, output_path)

    assert output_path.read_bytes().startswith(b"\xef\xbb\xbf")
    row = read_export(output_path)[0]
    assert row["canonical_title"] == "獣王と薬草"
    assert row["order_label"] == "第80話-後編"
    assert row["genre"] == "漫画"


def test_export_writes_nulls_as_empty_and_available_as_boolean_text(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.sqlite"
    output_path = tmp_path / "catalog-export.csv"
    service = CatalogService(catalog_path)
    service.upsert_item_source(
        ItemInput(canonical_title="nullable"),
        make_source(
            "nullable",
            access_mode="unknown",
            free_until=None,
            available=False,
            access_checked_at=None,
            last_seen_at=None,
        ),
    )
    item = service.create_item(
        ItemInput(canonical_title="completed", status="completed")
    )
    service.mark_item_completed(item.id, "library/completed.zip")
    source_item = service.create_item(ItemInput(canonical_title="without source"))

    export_catalog_csv(catalog_path, output_path)
    rows = read_export(output_path)
    nullable = next(row for row in rows if row["external_id"] == "nullable")
    completed = next(row for row in rows if row["item_id"] == str(item.id))
    without_source = next(row for row in rows if row["item_id"] == str(source_item.id))

    assert nullable["free_until"] == ""
    assert nullable["local_path"] == ""
    assert nullable["available"] == "false"
    assert completed["status"] == "completed"
    assert completed["local_path"] == "library/completed.zip"
    assert completed["completed_at"]
    assert without_source["source_id"] == ""
    assert without_source["site"] == ""


def test_empty_catalog_exports_header_only(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.sqlite"
    output_path = tmp_path / "catalog-export.csv"
    CatalogService(catalog_path).initialize()

    result = export_catalog_csv(catalog_path, output_path)

    assert result.rows == 0
    assert read_export(output_path) == []
    with output_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        assert next(csv.reader(csv_file)) == list(EXPORT_COLUMNS)


def test_export_rejects_missing_catalog(tmp_path: Path) -> None:
    with pytest.raises(CatalogExportError, match="does not exist"):
        export_catalog_csv(tmp_path / "missing.sqlite", tmp_path / "out.csv")
