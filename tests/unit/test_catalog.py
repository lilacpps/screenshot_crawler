import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from screenshot_crawler.catalog import (
    ArtifactInput,
    CatalogNotFoundError,
    CatalogService,
    CatalogValidationError,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    UnsupportedSchemaVersionError,
    WorkInput,
    format_timestamp,
    now_jst,
)
from screenshot_crawler.catalog.schema import SCHEMA_VERSION

SHA = "A" * 64


def make_graph(service: CatalogService):
    work = service.create_work(WorkInput(work_key="work-a", title="作品A", author="作者A"))
    item = service.create_item(ItemInput(item_title="第1話", kind="chapter"), work_id=work.id)
    source = service.create_source(
        SourceInput(
            site="mangaone",
            external_id="chapter-1",
            discovery_key="target-a",
            access_mode="quota",
            quota_started_at="2026-09-17T10:00:00+09:00",
            access_granted_until="2026-09-18T10:00:00+09:00",
        ),
        item_id=item.id,
    )
    target = service.create_source_target(
        SourceTargetInput(backend="web", locator="https://example.invalid/chapter"),
        source_id=source.id,
    )
    return work, item, source, target


def test_initialize_creates_v5_tables_indexes_and_foreign_keys(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite"
    service = CatalogService(path)
    service.initialize()

    assert SCHEMA_VERSION == 5
    assert service.schema_version() == 5
    with service._connection() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        assert tables == {
            "works", "items", "sources", "source_targets", "crawl_runs", "artifacts",
            "quota_resource_states",
        }
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        item_columns = {row[1] for row in connection.execute("PRAGMA table_info(items)")}
        assert {"canonical_title", "author", "genre", "local_path"}.isdisjoint(item_columns)
        target_columns = {row[1] for row in connection.execute("PRAGMA table_info(source_targets)")}
        assert "target_key" in target_columns
        source_columns = {row[1] for row in connection.execute("PRAGMA table_info(sources)")}
        assert "published_at" in source_columns
        indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list(items)")
        }
        assert "idx_items_work_id" in indexes


def test_work_create_get_find_list_and_validation(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    first = service.create_work(WorkInput(work_key="stable-key", title="Title", genre="fantasy"))
    assert service.get_work(first.id) == first
    assert service.find_work("stable-key") == first
    assert service.list_works() == [first]
    with pytest.raises(CatalogValidationError, match="work_key"):
        service.create_work(WorkInput(work_key=" ", title="Title"))
    with pytest.raises(CatalogValidationError, match="title"):
        service.create_work(WorkInput(work_key="another", title=""))
    with pytest.raises(CatalogValidationError, match="work"):
        service.create_work(WorkInput(work_key="stable-key", title="Duplicate"))


def test_work_upsert_preserves_id_and_created_at(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    first = service.create_work(WorkInput(work_key="stable", title="Old"))
    updated = service.upsert_work(WorkInput(work_key="stable", title="New", author="Author"))
    assert updated.id == first.id
    assert updated.created_at == first.created_at
    assert updated.title == "New"


def test_discovery_grant_create_and_refresh_null_preservation(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    work = service.create_work(WorkInput(work_key="magapoke-work", title="Work"))
    created = service.create_discovered_item_source_target(
        work_id=work.id,
        item_input=ItemInput(order_label="Episode"),
        source_input=SourceInput(
            site="magapoke",
            external_id="renting-1",
            discovery_key="magapoke-target",
            access_mode="quota",
            access_granted_until="2026-09-22T16:00:00+00:00",
            published_at="2026-09-22T00:00:00+00:00",
        ),
        web_target_input=SourceTargetInput(
            backend="web", locator="https://example.invalid/episode"
        ),
    )
    assert created.source.quota_started_at is None
    assert created.source.access_granted_until == "2026-09-23T01:00:00+09:00"
    assert created.source.published_at == "2026-09-22T09:00:00+09:00"

    refreshed = service.refresh_discovered_source(
        work_id=work.id,
        source_id=created.source.id,
        item_input=ItemInput(order_label="Episode"),
        source_input=SourceInput(
            site="magapoke",
            external_id="renting-1",
            discovery_key="magapoke-target",
            access_mode="quota",
            access_granted_until="2026-09-22T17:00:00+00:00",
            published_at="2026-09-21T15:00:00+00:00",
        ),
        web_target_input=SourceTargetInput(
            backend="web", locator="https://example.invalid/episode"
        ),
    )
    assert refreshed.source.quota_started_at is None
    assert refreshed.source.access_granted_until == "2026-09-23T02:00:00+09:00"
    assert refreshed.source.published_at == "2026-09-22T00:00:00+09:00"

    preserved = service.refresh_discovered_source(
        work_id=work.id,
        source_id=created.source.id,
        item_input=ItemInput(order_label="Episode"),
        source_input=SourceInput(
            site="magapoke",
            external_id="renting-1",
            discovery_key="magapoke-target",
            access_mode="quota",
            access_granted_until=None,
        ),
        web_target_input=SourceTargetInput(
            backend="web", locator="https://example.invalid/episode"
        ),
    )
    assert preserved.source.access_granted_until == "2026-09-23T02:00:00+09:00"
    assert preserved.source.published_at == "2026-09-22T00:00:00+09:00"


def test_source_published_at_requires_timezone_awareness_and_normalizes_to_jst(
    tmp_path: Path,
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    work = service.create_work(WorkInput(work_key="w", title="Work"))
    item = service.create_item(work_id=work.id)
    with pytest.raises(CatalogValidationError, match="Naive"):
        service.create_source(
            SourceInput(
                site="magapoke",
                external_id="naive",
                published_at="2026-09-22T00:00:00",
            ),
            item_id=item.id,
        )
    source = service.create_source(
        SourceInput(
            site="magapoke",
            external_id="aware",
            published_at="2026-09-22T00:00:00+09:00",
        ),
        item_id=item.id,
    )
    updated = service.update_source_external_state(
        "magapoke", "aware", published_at="2026-09-21T15:00:00+00:00"
    )
    assert source.published_at == "2026-09-22T00:00:00+09:00"
    assert updated.published_at == "2026-09-22T00:00:00+09:00"


def test_item_requires_existing_work_and_completion_has_no_path(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    work = service.create_work(WorkInput(work_key="w", title="Work"))
    item = service.create_item(ItemInput(status="pending"), work_id=work.id)
    assert item.work_id == work.id
    assert item.status == "pending"
    completed = service.mark_item_completed(
        item.id, completed_at="2026-09-17T12:00:00+09:00"
    )
    assert completed.status == "completed"
    assert completed.completed_at == "2026-09-17T12:00:00+09:00"
    assert "local_path" not in completed.__dataclass_fields__
    with pytest.raises(CatalogNotFoundError):
        service.create_item(ItemInput(), work_id=999)
    with pytest.raises(CatalogValidationError, match="status"):
        service.create_item(ItemInput(status="running"), work_id=work.id)


def test_source_identity_external_state_quota_and_reconciliation(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    work = service.create_work(WorkInput(work_key="w", title="Work"))
    item = service.create_item(work_id=work.id)
    source = service.create_source(
        SourceInput(
            site="site-a", external_id="one", discovery_key="scope",
            access_mode="free", quota_started_at="2026-09-17T10:00:00+09:00",
            access_granted_until="2026-09-18T10:00:00+09:00",
        ), item_id=item.id
    )
    assert service.find_source("site-a", "one") == source
    updated = service.update_source_external_state(
        "site-a", "one", access_mode="owned", available=False,
        free_until=None, last_seen_at="2026-09-17T13:00:00+09:00",
    )
    assert updated.access_mode == "owned"
    assert updated.available is False
    assert updated.quota_started_at == source.quota_started_at
    assert updated.access_granted_until == source.access_granted_until
    service.record_quota_access(
        source.id,
        quota_started_at="2026-09-19T10:00:00+09:00",
        access_granted_until="2026-09-20T10:00:00+09:00",
    )
    assert service.get_source(source.id).access_mode == "owned"
    other = service.create_source(
        SourceInput(site="site-a", external_id="two", discovery_key="scope"), item_id=item.id
    )
    count = service.mark_sources_unavailable_except(
        site="site-a", discovery_key="scope", observed_external_ids=[other.external_id]
    )
    assert count == 0
    assert service.get_source(source.id).available is False


def test_quota_resource_state_and_source_grant_commit_atomically(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    work = service.create_work(WorkInput(work_key="grant-work", title="Work"))
    item = service.create_item(work_id=work.id)
    source = service.create_source(
        SourceInput(site="magapoke", external_id="episode", access_mode="quota"),
        item_id=item.id,
    )
    consumed_at = "2026-09-23T10:00:00+09:00"
    grant_until = "2026-09-26T09:00:00+09:00"

    assert service.get_quota_resource_state(
        work.id, site="magapoke", resource="work_ticket"
    ) is None
    updated_source, state = service.record_quota_access_with_resource_state(
        source.id,
        work_id=work.id,
        site="magapoke",
        resource="work_ticket",
        consumed_at=consumed_at,
        access_granted_until=grant_until,
    )

    assert updated_source.quota_started_at == consumed_at
    assert updated_source.access_granted_until == grant_until
    assert state.last_consumed_at == consumed_at
    assert service.get_quota_resource_state(
        work.id, site="magapoke", resource="work_ticket"
    ) == state

    newer = service.record_quota_access_with_resource_state(
        source.id,
        work_id=work.id,
        site="magapoke",
        resource="work_ticket",
        consumed_at="2026-09-24T10:00:00+09:00",
        access_granted_until="2026-09-27T09:00:00+09:00",
    )[1]
    assert newer.id == state.id
    with service._connection() as connection:
        assert connection.execute(
            "SELECT count(*) FROM quota_resource_states"
        ).fetchone()[0] == 1


def test_clear_quota_access_is_compare_and_set_and_preserves_source_identity(
    tmp_path: Path,
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    work = service.create_work(WorkInput(work_key="w", title="Work"))
    item = service.create_item(work_id=work.id)
    source = service.create_source(
        SourceInput(
            site="bookwalker",
            external_id="book-1",
            access_mode="quota",
            quota_started_at="2026-09-20T08:00:00+09:00",
            access_granted_until="2026-09-21T08:00:00+09:00",
        ),
        item_id=item.id,
    )

    cleared = service.clear_quota_access(
        source.id,
        expected_quota_started_at="2026-09-20T08:00:00+09:00",
    )

    assert cleared.access_mode == "quota"
    assert cleared.quota_started_at is None
    assert cleared.access_granted_until is None
    assert service.get_source(source.id).item_id == source.item_id

    with pytest.raises(ValueError, match="already clear"):
        service.clear_quota_access(
            source.id,
            expected_quota_started_at="2026-09-20T08:00:00+09:00",
        )


def test_source_unique_identity_and_partial_validation(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    work = service.create_work(WorkInput(work_key="w", title="Work"))
    item = service.create_item(work_id=work.id)
    source = SourceInput(site="site-a", external_id="one")
    service.create_source(source, item_id=item.id)
    with pytest.raises(CatalogValidationError, match="source"):
        service.create_source(source, item_id=item.id)
    with pytest.raises(CatalogValidationError, match="external_id"):
        service.create_source(SourceInput(site="site-a", external_id=""), item_id=item.id)
    assert len(service.list_sources()) == 1


def test_source_targets_support_composite_identity_and_upsert(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    _, item, source, _ = make_graph(service)
    direct = service.create_source_target(
        SourceTargetInput(backend="web", target_key="direct", locator="direct"), source_id=source.id
    )
    android = service.create_source_target(
        SourceTargetInput(backend="android", target_key="default", locator="episode"), source_id=source.id
    )
    assert {target.target_key for target in service.list_source_targets(source_id=source.id)} == {
        "default", "direct"
    }
    assert direct.backend == "web"
    assert android.backend == "android"
    assert service.find_source_target(source.id, "web") is not None
    assert service.find_source_target(source.id, "web", "direct") == direct
    with pytest.raises(CatalogValidationError, match="source target"):
        service.create_source_target(
            SourceTargetInput(backend="web", target_key="direct", locator="duplicate"),
            source_id=source.id,
        )
    before = service.find_source_target(source.id, "web", "direct")
    updated = service.upsert_source_target(
        SourceTargetInput(backend="web", target_key="direct", locator="new", priority=10, enabled=False),
        source_id=source.id,
    )
    assert before is not None
    assert updated.id == before.id
    assert updated.created_at == before.created_at
    assert updated.locator == "new"
    assert updated.priority == 10
    assert updated.enabled is False
    assert item.work_id == 1


def test_crawl_run_snapshots_and_success_failure_transitions(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    _, item, source, target = make_graph(service)
    run = service.create_crawl_run(
        item_id=item.id, source_id=source.id, target_id=target.id,
        access_strategy="quota", started_at="2026-09-17T12:00:00+09:00"
    )
    assert run.status == "running"
    assert run.site_snapshot == source.site
    assert run.external_id_snapshot == source.external_id
    assert run.backend_snapshot == target.backend
    assert run.target_key_snapshot == target.target_key
    assert run.locator_snapshot == target.locator
    succeeded = service.mark_crawl_run_succeeded(run.id, page_count=3, stop_reason="end")
    assert succeeded.status == "succeeded"
    with pytest.raises(CatalogValidationError, match="terminal"):
        service.mark_crawl_run_failed(run.id, error_type="late")

    failed_run = service.create_crawl_run(
        item_id=item.id, source_id=source.id, target_id=target.id, access_strategy="auto"
    )
    failed = service.mark_crawl_run_failed(
        failed_run.id, error_type="Timeout", error_message="reader timeout", page_count=0
    )
    assert failed.status == "failed"
    assert service.list_crawl_runs(status="failed") == [failed]


def test_crawl_run_rejects_mismatched_graph_invalid_strategy_and_page_count(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    work, item, source, target = make_graph(service)
    other_item = service.create_item(work_id=work.id)
    with pytest.raises(CatalogValidationError, match="access_strategy"):
        service.create_crawl_run(
            item_id=item.id, source_id=source.id, target_id=target.id, access_strategy="bad"
        )
    with pytest.raises(CatalogValidationError, match="source.item_id"):
        service.create_crawl_run(
            item_id=other_item.id, source_id=source.id, target_id=target.id, access_strategy="auto"
        )
    other_source = service.create_source(
        SourceInput(site="site-b", external_id="other"), item_id=other_item.id
    )
    other_target = service.create_source_target(
        SourceTargetInput(backend="web", locator="other"), source_id=other_source.id
    )
    with pytest.raises(CatalogValidationError, match="target.source_id"):
        service.create_crawl_run(
            item_id=item.id, source_id=source.id, target_id=other_target.id, access_strategy="auto"
        )
    run = service.create_crawl_run(
        item_id=item.id, source_id=source.id, target_id=target.id, access_strategy="direct"
    )
    with pytest.raises(CatalogValidationError, match="page_count"):
        service.mark_crawl_run_succeeded(run.id, page_count=-1)
    assert service.get_crawl_run(run.id).status == "running"


def test_artifacts_manual_and_run_linked_validation_and_storage_patch(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    _, item, source, target = make_graph(service)
    run = service.create_crawl_run(
        item_id=item.id, source_id=source.id, target_id=target.id, access_strategy="direct"
    )
    linked = service.create_artifact(
        ArtifactInput(kind="archive", format="zip", sha256=SHA, byte_size=10,
                      storage_backend="filesystem", locator="library/a.zip", state="present"),
        item_id=item.id, crawl_run_id=run.id,
    )
    manual = service.create_artifact(
        kind="archive", format="zip", sha256="b" * 64, byte_size=0,
        storage_backend="nas", state="missing", item_id=item.id,
    )
    assert linked.sha256 == SHA.lower()
    assert service.list_artifacts(item_id=item.id) == [linked, manual]
    service.mark_crawl_run_succeeded(run.id, page_count=1)
    service.mark_item_completed(item.id)
    patched = service.update_artifact_storage(
        linked.id, state="deleted", locator="library/archive.zip", last_verified_at=now_jst()
    )
    assert patched.state == "deleted"
    assert service.get_item(item.id).status == "completed"
    assert service.get_crawl_run(run.id).status == "succeeded"


@pytest.mark.parametrize(
    "artifact",
    [
        ArtifactInput(kind="archive", format="zip", sha256="bad", byte_size=1, storage_backend="fs"),
        ArtifactInput(kind="archive", format="zip", sha256=SHA, byte_size=-1, storage_backend="fs"),
        ArtifactInput(kind="archive", format="zip", sha256=SHA, byte_size=1, storage_backend="fs", state="bad"),
        ArtifactInput(kind="archive", format="zip", sha256=SHA, byte_size=1, storage_backend="fs", state="present"),
    ],
)
def test_artifact_validation(tmp_path: Path, artifact: ArtifactInput) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    work = service.create_work(WorkInput(work_key="w", title="Work"))
    item = service.create_item(work_id=work.id)
    with pytest.raises(CatalogValidationError):
        service.create_artifact(artifact, item_id=item.id)
    assert service.list_artifacts() == []


def test_artifact_rejects_run_from_other_item_without_partial_row(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    _, item, source, target = make_graph(service)
    other_work = service.create_work(WorkInput(work_key="other", title="Other"))
    other_item = service.create_item(work_id=other_work.id)
    run = service.create_crawl_run(
        item_id=item.id, source_id=source.id, target_id=target.id, access_strategy="auto"
    )
    with pytest.raises(CatalogValidationError, match="crawl_run.item_id"):
        service.create_artifact(
            ArtifactInput(kind="archive", format="zip", sha256=SHA, byte_size=1, storage_backend="fs"),
            item_id=other_item.id, crawl_run_id=run.id,
        )
    assert service.list_artifacts() == []


def test_finalize_successful_crawl_is_atomic(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    _, item, source, target = make_graph(service)
    run = service.create_crawl_run(
        item_id=item.id, source_id=source.id, target_id=target.id, access_strategy="direct"
    )
    with service._connection() as connection:
        connection.execute(
            "CREATE TRIGGER fail_finalize_item AFTER INSERT ON artifacts "
            "BEGIN SELECT RAISE(ABORT, 'forced finalize failure'); END"
        )

    with pytest.raises(Exception, match="forced finalize failure"):
        service.finalize_successful_crawl(
            run.id,
            artifact=ArtifactInput(
                kind="archive",
                format="zip",
                sha256=SHA,
                byte_size=10,
                storage_backend="filesystem",
                locator="library/archive.zip",
                state="present",
            ),
            page_count=1,
            stop_reason="end",
        )

    assert service.list_artifacts() == []
    assert service.get_crawl_run(run.id).status == "running"
    assert service.get_item(item.id).status == "pending"
    service.mark_crawl_run_failed(run.id, error_type="FinalizeError")


def test_timestamps_require_aware_datetime_and_normalize_to_jst() -> None:
    generated = now_jst()
    assert generated.utcoffset() == timedelta(hours=9)
    saved = format_timestamp(datetime(2026, 9, 17, 12, tzinfo=UTC))
    assert saved == "2026-09-17T21:00:00+09:00"
    with pytest.raises(CatalogValidationError, match="Naive"):
        format_timestamp(datetime.fromisoformat("2026-09-17T12:00:00"))


@pytest.mark.parametrize("version", [1, 2, 99])
def test_unsupported_schema_versions_are_rejected_without_mutation(
    tmp_path: Path, version: int
) -> None:
    path = tmp_path / f"catalog-{version}.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE marker (value TEXT)")
        connection.execute("INSERT INTO marker VALUES ('keep')")
        connection.execute(f"PRAGMA user_version = {version}")
    service = CatalogService(path)
    with pytest.raises(UnsupportedSchemaVersionError):
        service.initialize()
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == version
        assert connection.execute("SELECT value FROM marker").fetchone()[0] == "keep"


def test_v2_shape_is_rejected_without_synthetic_work_or_migration(tmp_path: Path) -> None:
    path = tmp_path / "v2.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, canonical_title TEXT)")
        connection.execute("INSERT INTO items VALUES (1, 'old')")
        connection.execute("PRAGMA user_version = 2")
    service = CatalogService(path)
    with pytest.raises(UnsupportedSchemaVersionError, match="version 2"):
        service.list_items()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT canonical_title FROM items").fetchone()[0] == "old"
