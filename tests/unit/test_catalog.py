import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from screenshot_crawler.catalog import (
    CatalogNotFoundError,
    CatalogService,
    CatalogValidationError,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    UnsupportedSchemaVersionError,
    format_timestamp,
    now_jst,
)


def source(**overrides: object) -> SourceInput:
    values: dict[str, object] = {
        "site": "mangaone",
        "external_id": "chapter-1",
        "discovery_key": "target-one",
        "access_mode": "free",
        "free_until": "2026-09-18T12:00:00+09:00",
        "available": True,
        "access_checked_at": "2026-09-17T12:00:00+09:00",
        "last_seen_at": "2026-09-17T12:00:00+09:00",
    }
    values.update(overrides)
    return SourceInput(**values)


def test_initialize_creates_three_domain_tables_and_enables_foreign_keys(
    tmp_path: Path,
) -> None:
    path = tmp_path / "catalog.sqlite"
    service = CatalogService(path)
    service.initialize()

    assert service.schema_version() == 2
    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        assert tables == {"items", "sources", "source_targets"}
        source_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(sources)")
        }
        assert "url" not in source_columns
        target_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(source_targets)")
        }
        assert target_columns == {
            "id",
            "source_id",
            "backend",
            "locator",
            "priority",
            "enabled",
            "created_at",
            "updated_at",
        }
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 0
    with service._connection() as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_upsert_updates_source_external_state_and_preserves_local_state(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    item = service.create_item(ItemInput(canonical_title="作品A", author="作者A"))
    first_source = service.create_source(
        source(
            quota_started_at="2026-09-17T10:00:00+09:00",
            access_granted_until="2026-09-18T10:00:00+09:00",
        ),
        item_id=item.id,
    )
    first = service.get_source(first_source.id)
    service.mark_item_completed(item.id, "library/作品A.zip")

    second = service.upsert_item_source(
        ItemInput(canonical_title="作品A updated", author="作者A updated", genre="fantasy"),
        source(
            access_mode="owned",
            free_until=None,
            available=False,
            access_checked_at="2026-09-17T13:00:00+09:00",
            last_seen_at="2026-09-17T13:00:00+09:00",
            quota_started_at=None,
            access_granted_until=None,
        ),
    )

    assert second.source.id == first.id
    assert second.source.access_mode == "owned"
    assert second.source.free_until is None
    assert second.source.available is False
    assert second.source.quota_started_at == "2026-09-17T10:00:00+09:00"
    assert second.source.access_granted_until == "2026-09-18T10:00:00+09:00"
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
    item = service.create_item(ItemInput(canonical_title="A"))
    service.create_source(
        source(
            quota_started_at="2026-09-17T10:00:00+09:00",
            access_granted_until="2026-09-18T10:00:00+09:00",
        ),
        item_id=item.id,
    )

    updated = service.update_source_external_state(
        "mangaone",
        "chapter-1",
        free_until=None,
        available=False,
        metadata={"genre": "drama"},
    )
    assert updated.free_until is None
    assert updated.available is False
    assert updated.quota_started_at == "2026-09-17T10:00:00+09:00"
    assert updated.access_granted_until == "2026-09-18T10:00:00+09:00"
    assert service.get_item(item.id).genre == "drama"


def test_record_quota_access_updates_only_local_quota_state(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    item = service.create_item(ItemInput(canonical_title="A", status="pending"))
    created = service.create_source(
        source(
            access_mode="quota",
            available=True,
        ),
        item_id=item.id,
    )
    before_item = service.get_item(item.id)
    before_source = service.get_source(created.id)

    updated = service.record_quota_access(
        created.id,
        quota_started_at="2026-09-17T15:00:00+09:00",
        access_granted_until="2026-09-18T15:00:00+09:00",
    )

    assert updated.quota_started_at == "2026-09-17T15:00:00+09:00"
    assert updated.access_granted_until == "2026-09-18T15:00:00+09:00"
    after_source = service.get_source(created.id)
    assert after_source.id == before_source.id
    assert after_source.item_id == before_source.item_id
    assert after_source.site == before_source.site
    assert after_source.external_id == before_source.external_id
    assert after_source.access_mode == before_source.access_mode
    assert after_source.available == before_source.available
    assert after_source.free_until == before_source.free_until
    assert service.get_item(item.id) == before_item


def test_record_quota_access_rejects_missing_source_and_naive_timestamp(
    tmp_path: Path,
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")

    with pytest.raises(CatalogValidationError, match="Naive datetimes"):
        service.record_quota_access(
            999,
            quota_started_at=datetime.fromisoformat("2026-09-17T15:00:00"),
            access_granted_until="2026-09-18T15:00:00+09:00",
        )

    with pytest.raises(CatalogNotFoundError, match="source not found"):
        service.record_quota_access(
            999,
            quota_started_at="2026-09-17T15:00:00+09:00",
            access_granted_until="2026-09-18T15:00:00+09:00",
        )


def test_new_discovery_upsert_starts_with_null_quota_state(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")

    record = service.upsert_item_source(
        ItemInput(canonical_title="A"),
        source(
            quota_started_at="2026-09-17T10:00:00+09:00",
            access_granted_until="2026-09-18T10:00:00+09:00",
        ),
    )

    assert record.source.quota_started_at is None
    assert record.source.access_granted_until is None


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


def test_schema_v1_is_rejected_without_migration_or_data_loss(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE items (id INTEGER PRIMARY KEY, marker TEXT);
            INSERT INTO items (marker) VALUES ('keep');
            PRAGMA user_version = 1;
            """
        )

    service = CatalogService(path)
    with pytest.raises(UnsupportedSchemaVersionError, match="Unsupported Catalog schema version 1"):
        service.initialize()

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert connection.execute("SELECT marker FROM items").fetchone()[0] == "keep"


def test_source_target_create_and_identity(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    record = service.upsert_item_source(ItemInput(canonical_title="A"), source())

    web = service.create_source_target(
        SourceTargetInput(backend="web", locator="https://example.invalid/chapter"),
        source_id=record.source.id,
    )
    android = service.create_source_target(
        {"backend": "android", "locator": "episode_12345", "priority": 50},
        source_id=record.source.id,
    )

    assert web.source_id == record.source.id
    assert web.priority == 100
    assert web.enabled is True
    assert android.backend == "android"
    assert [target.id for target in service.list_source_targets()] == [web.id, android.id]
    assert service.find_source_target(record.source.id, "web") == web
    assert service.get_source_target(android.id) == android


def test_source_target_upsert_preserves_identity_and_source_state(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    record = service.upsert_item_source(ItemInput(canonical_title="A"), source())
    created = service.create_source_target(
        SourceTargetInput(backend="web", locator="https://example.invalid/old"),
        source_id=record.source.id,
    )
    updated = service.upsert_source_target(
        SourceTargetInput(
            backend="web", locator="https://example.invalid/new", priority=50, enabled=False
        ),
        source_id=record.source.id,
    )

    assert updated.id == created.id
    assert updated.source_id == created.source_id
    assert updated.backend == created.backend
    assert updated.created_at == created.created_at
    assert updated.locator == "https://example.invalid/new"
    assert updated.priority == 50
    assert updated.enabled is False
    assert service.get_source(record.source.id).access_mode == "free"


def test_source_target_create_rejects_duplicate_backend(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    record = service.upsert_item_source(ItemInput(canonical_title="A"), source())
    target = SourceTargetInput(backend="web", locator="https://example.invalid/one")
    service.create_source_target(target, source_id=record.source.id)

    with pytest.raises(CatalogValidationError, match="source target"):
        service.create_source_target(target, source_id=record.source.id)


@pytest.mark.parametrize(
    ("target", "match"),
    [
        (SourceTargetInput(backend="", locator="x"), "backend"),
        (SourceTargetInput(backend=" ", locator="x"), "backend"),
        (SourceTargetInput(backend="web", locator=""), "locator"),
        (SourceTargetInput(backend="web", locator=" "), "locator"),
        (SourceTargetInput(backend="web", locator="x", priority=-1), "priority"),
    ],
)
def test_source_target_validation(tmp_path: Path, target: SourceTargetInput, match: str) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    with pytest.raises(CatalogValidationError, match=match):
        service.create_source_target(target, source_id=999)

    valid = SourceTargetInput(backend="web", locator="x")
    with pytest.raises(CatalogValidationError, match="source target"):
        service.create_source_target(valid, source_id=999)


def test_source_target_filters_are_stable_and_enabled_is_boolean(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    record = service.upsert_item_source(ItemInput(canonical_title="A"), source())
    service.create_source_target(
        SourceTargetInput(backend="web", locator="web", priority=10, enabled=True),
        source_id=record.source.id,
    )
    service.create_source_target(
        SourceTargetInput(backend="android", locator="android", enabled=False),
        source_id=record.source.id,
    )

    assert [target.backend for target in service.list_source_targets(enabled=True)] == ["web"]
    assert [target.backend for target in service.list_source_targets(backend="android")] == [
        "android"
    ]
    assert service.list_source_targets(source_id=record.source.id)[0].id == 1


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
