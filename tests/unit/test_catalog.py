import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from screenshot_crawler.catalog import (
    CatalogService,
    CatalogValidationError,
    ItemInput,
    SourceInput,
    UnsupportedSchemaVersionError,
    format_timestamp,
    now_jst,
)


def source(**overrides: object) -> SourceInput:
    values: dict[str, object] = {
        "site": "mangaone",
        "external_id": "chapter-1",
        "url": "https://example.invalid/old",
        "discovery_key": "target-one",
        "access_mode": "free",
        "free_until": "2026-09-18T12:00:00+09:00",
        "available": True,
        "access_checked_at": "2026-09-17T12:00:00+09:00",
        "last_seen_at": "2026-09-17T12:00:00+09:00",
    }
    values.update(overrides)
    return SourceInput(**values)


def test_initialize_creates_only_two_domain_tables_and_enables_foreign_keys(
    tmp_path: Path,
) -> None:
    path = tmp_path / "catalog.sqlite"
    service = CatalogService(path)
    service.initialize()

    assert service.schema_version() == 1
    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        assert tables == {"items", "sources"}
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 0
    with service._connection() as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_upsert_updates_source_external_state_and_preserves_local_state(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    first = service.upsert_item_source(
        ItemInput(canonical_title="作品A", author="作者A"),
        source(),
    )
    service.mark_item_completed(first.item.id, "library/作品A.zip")

    second = service.upsert_item_source(
        ItemInput(canonical_title="作品A updated", author="作者A updated", genre="fantasy"),
        source(
            url="https://example.invalid/new",
            access_mode="owned",
            free_until=None,
            available=False,
            access_checked_at="2026-09-17T13:00:00+09:00",
            last_seen_at="2026-09-17T13:00:00+09:00",
        ),
    )

    assert second.source.id == first.source.id
    assert second.source.url == "https://example.invalid/new"
    assert second.source.access_mode == "owned"
    assert second.source.free_until is None
    assert second.source.available is False
    assert second.item.status == "completed"
    assert second.item.local_path == "library/作品A.zip"
    assert second.item.completed_at is not None
    assert second.item.canonical_title == "作品A updated"
    assert len(service.list_sources()) == 1


def test_unique_identity_and_association_are_enforced(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    record = service.upsert_item_source(ItemInput(canonical_title="A"), source())
    same = service.upsert_item_source(ItemInput(canonical_title="B"), source())

    assert same.source.id == record.source.id
    assert same.source.item_id == record.source.item_id
    assert service.find_source("mangaone", "chapter-1") == same.source


def test_update_external_state_supports_explicit_null_and_metadata(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    record = service.upsert_item_source(ItemInput(canonical_title="A"), source())

    updated = service.update_source_external_state(
        "mangaone",
        "chapter-1",
        free_until=None,
        available=False,
        metadata={"genre": "drama"},
    )
    assert updated.free_until is None
    assert updated.available is False
    assert service.get_item(record.item.id).genre == "drama"


def test_jst_timestamps_are_aware_and_parseable() -> None:
    generated = now_jst()
    assert generated.tzinfo is not None
    assert generated.utcoffset() == timedelta(hours=9)
    saved = format_timestamp(generated)
    assert saved is not None
    assert datetime.fromisoformat(saved).utcoffset().total_seconds() == 9 * 60 * 60
    with pytest.raises(CatalogValidationError):
        format_timestamp(datetime.fromisoformat("2026-09-17T12:00:00"))


def test_unsupported_schema_version_fails_without_processing(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 99")

    service = CatalogService(path)
    with pytest.raises(UnsupportedSchemaVersionError):
        service.initialize()
    with pytest.raises(UnsupportedSchemaVersionError):
        service.list_items()


def test_invalid_source_does_not_leave_partial_item(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    with pytest.raises(CatalogValidationError):
        service.upsert_item_source(
            ItemInput(canonical_title="will rollback"),
            source(external_id=""),
        )
    assert service.list_items() == []


def test_upsert_rolls_back_item_when_source_insert_fails(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    service.initialize()
    with service._connection() as connection:
        connection.execute(
            "CREATE TRIGGER fail_source_insert BEFORE INSERT ON sources "
            "WHEN NEW.external_id = 'fail' BEGIN SELECT RAISE(ABORT, 'forced failure'); END"
        )

    with pytest.raises(sqlite3.IntegrityError, match="forced failure"):
        service.upsert_item_source(
            ItemInput(canonical_title="must rollback"),
            source(external_id="fail"),
        )
    assert service.list_items() == []
    assert service.list_sources() == []
