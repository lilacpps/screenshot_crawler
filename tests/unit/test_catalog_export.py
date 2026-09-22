import csv
import sqlite3
from pathlib import Path

import pytest

from screenshot_crawler.catalog import (
    ArtifactInput,
    CatalogService,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)
from screenshot_crawler.catalog.export import (
    EXPORT_COLUMNS,
    EXPORT_FILENAMES,
    CatalogExportError,
    export_catalog_csv,
)


def make_source(external_id: str, **overrides: object) -> SourceInput:
    values: dict[str, object] = {
        "site": "mangaone",
        "external_id": external_id,
        "discovery_key": "juou-to-yakusou",
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


def build_graph(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    catalog_path = tmp_path / "catalog.sqlite"
    service = CatalogService(catalog_path)
    work = service.create_work(
        WorkInput(work_key="juou-to-yakusou", title="獣王と薬草", author="作者A", genre="漫画")
    )
    item = service.create_item(
        ItemInput(item_title="第1話", kind="episode", order_key="1", order_label="第1話"),
        work_id=work.id,
    )
    source = service.create_source(make_source("episode-1"), item_id=item.id)
    web_default = service.create_source_target(
        SourceTargetInput(backend="web", locator="https://example.invalid/episode-1"),
        source_id=source.id,
    )
    web_direct = service.create_source_target(
        SourceTargetInput(backend="web", target_key="direct", locator="https://example.invalid/direct"),
        source_id=source.id,
    )
    android_default = service.create_source_target(
        SourceTargetInput(backend="android", locator="episode-1.apk", priority=20, enabled=False),
        source_id=source.id,
    )
    failed_run = service.create_crawl_run(
        item_id=item.id, source_id=source.id, target_id=web_default.id, access_strategy="direct"
    )
    service.mark_crawl_run_failed(
        failed_run.id, error_type="timeout", error_message="full error message", page_count=1
    )
    deleted = service.create_artifact(
        ArtifactInput(
            kind="archive", format="zip", sha256="a" * 64, byte_size=10,
            storage_backend="filesystem", locator="old.zip", state="deleted",
        ),
        item_id=item.id, crawl_run_id=failed_run.id,
    )
    successful_run = service.create_crawl_run(
        item_id=item.id, source_id=source.id, target_id=web_direct.id, access_strategy="auto"
    )
    _, present, _ = service.finalize_successful_crawl(
        successful_run.id,
        artifact=ArtifactInput(
            kind="archive", format="zip", sha256="b" * 64, byte_size=20,
            storage_backend="filesystem", locator="new.zip", state="present",
        ),
        page_count=2,
    )
    manual = service.create_artifact(
        ArtifactInput(
            kind="image", format="webp", sha256="c" * 64, byte_size=30,
            storage_backend="manual-import", state="unknown",
        ),
        item_id=item.id,
    )
    return catalog_path, {
        "work": work, "item": item, "source": source,
        "targets": (web_default, web_direct, android_default),
        "failed_run": failed_run, "successful_run": successful_run,
        "artifacts": (deleted, present, manual),
    }


def test_full_v3_graph_exports_six_lossless_csvs(tmp_path: Path) -> None:
    catalog_path, graph = build_graph(tmp_path)
    output_dir = tmp_path / "catalog-export"

    result = export_catalog_csv(catalog_path, output_dir)

    assert result.total_rows == 1 + 1 + 1 + 3 + 2 + 3
    assert result.output_dir == output_dir
    assert {path.name for path in output_dir.iterdir()} == set(EXPORT_FILENAMES)
    for table, columns in EXPORT_COLUMNS.items():
        rows = read_export(output_dir / f"{table}.csv")
        assert list(rows[0]) == list(columns)
    works = read_export(output_dir / "works.csv")
    items = read_export(output_dir / "items.csv")
    targets = read_export(output_dir / "source_targets.csv")
    runs = read_export(output_dir / "crawl_runs.csv")
    artifacts = read_export(output_dir / "artifacts.csv")
    assert works[0]["title"] == "獣王と薬草"
    assert works[0]["author"] == "作者A"
    assert items[0]["work_id"] == str(graph["work"].id)
    assert items[0]["item_title"] == "第1話"
    assert "canonical_title" not in items[0]
    assert "local_path" not in items[0]
    assert {row["target_key"] for row in targets} == {"default", "direct"}
    assert {row["backend"] for row in targets} == {"web", "android"}
    assert any(row["enabled"] == "false" and row["priority"] == "20" for row in targets)
    assert {row["status"] for row in runs} == {"failed", "succeeded"}
    assert {row["id"] for row in runs} == {str(graph["failed_run"].id), str(graph["successful_run"].id)}
    assert all(row["site_snapshot"] == "mangaone" for row in runs)
    assert {row["state"] for row in artifacts} == {"deleted", "present", "unknown"}
    assert any(row["crawl_run_id"] == "" for row in artifacts)


def test_export_writes_bom_nulls_and_booleans(tmp_path: Path) -> None:
    catalog_path, graph = build_graph(tmp_path)
    output_dir = tmp_path / "out"
    export_catalog_csv(catalog_path, output_dir)

    assert (output_dir / "sources.csv").read_bytes().startswith(b"\xef\xbb\xbf")
    source = read_export(output_dir / "sources.csv")[0]
    assert source["available"] == "true"
    target = next(row for row in read_export(output_dir / "source_targets.csv") if row["enabled"] == "false")
    assert target["enabled"] == "false"
    run = next(row for row in read_export(output_dir / "crawl_runs.csv") if row["status"] == "failed")
    assert run["finished_at"]
    assert run["error_message"] == "full error message"
    assert run["stop_reason"] == ""
    manual = next(row for row in read_export(output_dir / "artifacts.csv") if row["id"] == str(graph["artifacts"][2].id))
    assert manual["crawl_run_id"] == ""
    assert manual["locator"] == ""


def test_zero_row_tables_still_export_headers(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.sqlite"
    CatalogService(catalog_path).initialize()
    output_dir = tmp_path / "empty"

    result = export_catalog_csv(catalog_path, output_dir)

    assert result.total_rows == 0
    for table, columns in EXPORT_COLUMNS.items():
        assert read_export(output_dir / f"{table}.csv") == []
        with (output_dir / f"{table}.csv").open("r", encoding="utf-8-sig", newline="") as csv_file:
            assert next(csv.reader(csv_file)) == list(columns)


@pytest.mark.parametrize("version", [1, 2, 4])
def test_export_rejects_unsupported_schema_without_mutation(tmp_path: Path, version: int) -> None:
    catalog_path = tmp_path / "catalog.sqlite"
    with sqlite3.connect(catalog_path) as connection:
        connection.execute("CREATE TABLE legacy (id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO legacy VALUES (1, 'unchanged')")
        connection.execute(f"PRAGMA user_version = {version}")
    before = catalog_path.read_bytes()

    with pytest.raises(CatalogExportError, match=f"version {version}"):
        export_catalog_csv(catalog_path, tmp_path / "out")

    assert catalog_path.read_bytes() == before
    assert not (tmp_path / "out").exists()


def test_export_rejects_broken_v4_schema_without_repair(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.sqlite"
    with sqlite3.connect(catalog_path) as connection:
        connection.execute("CREATE TABLE works (id INTEGER PRIMARY KEY)")
        connection.execute("PRAGMA user_version = 4")
    before = catalog_path.read_bytes()

    with pytest.raises(CatalogExportError, match="missing table"):
        export_catalog_csv(catalog_path, tmp_path / "out")

    assert catalog_path.read_bytes() == before


def test_export_rejects_missing_catalog_and_does_not_create_it(tmp_path: Path) -> None:
    catalog_path = tmp_path / "missing.sqlite"
    with pytest.raises(CatalogExportError, match="does not exist"):
        export_catalog_csv(catalog_path, tmp_path / "out")
    assert not catalog_path.exists()


def test_existing_snapshot_is_not_overwritten_or_partially_added(tmp_path: Path) -> None:
    catalog_path, _ = build_graph(tmp_path)
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    existing = output_dir / "works.csv"
    existing.write_bytes(b"old snapshot")

    with pytest.raises(CatalogExportError, match="already contains"):
        export_catalog_csv(catalog_path, output_dir)

    assert existing.read_bytes() == b"old snapshot"
    assert not (output_dir / "items.csv").exists()


def test_export_is_read_only_and_write_failure_leaves_no_final_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog_path, _ = build_graph(tmp_path)
    before = catalog_path.read_bytes()
    output_dir = tmp_path / "out"

    import screenshot_crawler.catalog.export as export_module

    original = export_module._write_table_csv
    calls = 0

    def fail_after_first(*args: object, **kwargs: object) -> int:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated write failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(export_module, "_write_table_csv", fail_after_first)
    with pytest.raises(CatalogExportError, match="simulated write failure"):
        export_catalog_csv(catalog_path, output_dir)

    assert catalog_path.read_bytes() == before
    assert not output_dir.exists()
    assert not list(tmp_path.glob(".out.*"))
