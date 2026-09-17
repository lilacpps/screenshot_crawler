import sqlite3
from pathlib import Path

import pytest

from screenshot_crawler.catalog import CatalogService, CatalogValidationError, ItemInput
from screenshot_crawler.discovery import (
    DiscoveredItem,
    DiscoveredRecord,
    DiscoveredSource,
    DiscoveryAdapter,
    DiscoveryAdapterRegistry,
    DiscoveryIncompleteError,
    DiscoveryService,
)
from screenshot_crawler.watchlist import WatchlistTarget


class FakePage:
    pass


def record(
    external_id: str,
    *,
    title: str | None = "作品A",
    url: str | None = None,
    kind: str | None = "volume",
    order_key: str | None = None,
    order_label: str | None = None,
    author: str | None = None,
    genre: str | None = None,
    access_mode: str = "free",
    available: bool | None = True,
    free_until: str | None = None,
    access_checked_at: str | None = None,
    last_seen_at: str | None = None,
) -> DiscoveredRecord:
    return DiscoveredRecord(
        item=DiscoveredItem(
            canonical_title=title,
            author=author,
            genre=genre,
            kind=kind,
            order_key=order_key,
            order_label=order_label,
        ),
        source=DiscoveredSource(
            external_id=external_id,
            url=url or f"https://example.test/{external_id}",
            access_mode=access_mode,
            available=available,
            free_until=free_until,
            access_checked_at=access_checked_at,
            last_seen_at=last_seen_at,
        ),
    )


class FakeDiscoveryAdapter(DiscoveryAdapter):
    def __init__(
        self,
        records: list[DiscoveredRecord],
        *,
        failure: Exception | None = None,
    ) -> None:
        self.records = records
        self.failure = failure
        self.calls: list[tuple[WatchlistTarget, str]] = []
        self.yielded: list[str] = []

    def iter_records(self, page: FakePage, target: WatchlistTarget, mode: str):
        del page
        self.calls.append((target, mode))

        async def generate():
            for discovered in self.records:
                self.yielded.append(discovered.source.external_id)
                yield discovered
            if self.failure is not None:
                raise self.failure

        return generate()


def setup_service(
    tmp_path: Path,
    adapter: FakeDiscoveryAdapter,
    *,
    site: str = "mangaone",
) -> tuple[DiscoveryService, CatalogService, WatchlistTarget]:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    registry = DiscoveryAdapterRegistry()
    registry.register(site, lambda: adapter)
    target = WatchlistTarget(
        key="target-one",
        site=site,
        url="https://example.test/listing",
    )
    return DiscoveryService(catalog, registry), catalog, target


async def test_full_discovery_upserts_records_and_injects_target_identity(
    tmp_path: Path,
) -> None:
    adapter = FakeDiscoveryAdapter(
        [record("chapter-1"), record("chapter-2", title="作品B")]
    )
    service, catalog, target = setup_service(tmp_path, adapter)

    result = await service.discover(FakePage(), target, "full")

    assert (result.observed_count, result.new_count, result.known_count) == (2, 2, 0)
    assert result.complete is True
    assert result.stopped_reason == "exhausted"
    sources = catalog.list_sources(site=target.site, discovery_key=target.key)
    assert [(source.site, source.discovery_key) for source in sources] == [
        ("mangaone", "target-one"),
        ("mangaone", "target-one"),
    ]
    assert len(catalog.list_items()) == 2

    rerun = await service.discover(FakePage(), target, "full")
    assert (rerun.new_count, rerun.known_count) == (0, 2)
    assert len(catalog.list_sources()) == 2


async def test_full_refresh_updates_external_state_without_overwriting_local_state(
    tmp_path: Path,
) -> None:
    adapter = FakeDiscoveryAdapter(
        [
            record(
                "chapter-1",
                url="https://example.test/new",
                access_mode="owned",
                available=False,
                author="作者B",
                genre="genre",
                free_until="2026-09-20T12:00:00+09:00",
                access_checked_at="2026-09-17T13:00:00+09:00",
                last_seen_at="2026-09-17T13:00:00+09:00",
            )
        ]
    )
    service, catalog, target = setup_service(tmp_path, adapter)
    first_item = catalog.create_item(ItemInput(canonical_title="作品A", author="作者A"))
    catalog.create_source(
        {
            "site": target.site,
            "external_id": "chapter-1",
            "discovery_key": target.key,
            "url": "https://example.test/old",
            "access_mode": "free",
            "quota_started_at": "2026-09-17T10:00:00+09:00",
            "access_granted_until": "2026-09-18T10:00:00+09:00",
        },
        item_id=first_item.id,
    )
    catalog.mark_item_completed(first_item.id, "library/作品A.zip")

    result = await service.discover(FakePage(), target, "full")

    refreshed = catalog.get_source_by_external_id(target.site, "chapter-1")
    item = catalog.get_item(first_item.id)
    assert result.complete is True
    assert refreshed.url == "https://example.test/new"
    assert refreshed.access_mode == "owned"
    assert refreshed.available is False
    assert refreshed.free_until == "2026-09-20T12:00:00+09:00"
    assert refreshed.access_checked_at == "2026-09-17T13:00:00+09:00"
    assert refreshed.last_seen_at == "2026-09-17T13:00:00+09:00"
    assert refreshed.quota_started_at == "2026-09-17T10:00:00+09:00"
    assert refreshed.access_granted_until == "2026-09-18T10:00:00+09:00"
    assert item.status == "completed"
    assert item.local_path == "library/作品A.zip"
    assert item.author == "作者B"
    assert item.genre == "genre"


async def test_full_reconciliation_is_limited_to_complete_target_scope(
    tmp_path: Path,
) -> None:
    adapter = FakeDiscoveryAdapter([record("seen", title="Seen")])
    service, catalog, target = setup_service(tmp_path, adapter)
    missing = catalog.upsert_item_source(
        ItemInput(canonical_title="Missing"),
        {
            "site": target.site,
            "external_id": "missing",
            "discovery_key": target.key,
            "url": "https://example.test/missing",
        },
    )
    other_scope = catalog.upsert_item_source(
        ItemInput(canonical_title="Other scope"),
        {
            "site": target.site,
            "external_id": "other-scope",
            "discovery_key": "other-target",
            "url": "https://example.test/other-scope",
        },
    )
    other_site = catalog.upsert_item_source(
        ItemInput(canonical_title="Other site"),
        {
            "site": "bookwalker",
            "external_id": "other-site",
            "discovery_key": target.key,
            "url": "https://example.test/other-site",
        },
    )

    await service.discover(FakePage(), target, "full")

    assert catalog.get_source(missing.source.id).available is False
    assert catalog.get_source(other_scope.source.id).available is True
    assert catalog.get_source(other_site.source.id).available is True
    assert catalog.get_source(missing.source.id) is not None


async def test_incomplete_full_does_not_reconcile_missing_sources(tmp_path: Path) -> None:
    adapter = FakeDiscoveryAdapter(
        [record("seen")], failure=DiscoveryIncompleteError("pagination uncertain")
    )
    service, catalog, target = setup_service(tmp_path, adapter)
    missing = catalog.upsert_item_source(
        ItemInput(canonical_title="Missing"),
        {
            "site": target.site,
            "external_id": "missing",
            "discovery_key": target.key,
            "url": "https://example.test/missing",
        },
    )

    result = await service.discover(FakePage(), target, "full")

    assert result.complete is False
    assert result.stopped_reason == "incomplete"
    assert catalog.get_source(missing.source.id).available is True


async def test_unexpected_full_failure_does_not_reconcile_missing_sources(
    tmp_path: Path,
) -> None:
    adapter = FakeDiscoveryAdapter([record("seen")], failure=RuntimeError("broken"))
    service, catalog, target = setup_service(tmp_path, adapter)
    missing = catalog.upsert_item_source(
        ItemInput(canonical_title="Missing"),
        {
            "site": target.site,
            "external_id": "missing",
            "discovery_key": target.key,
            "url": "https://example.test/missing",
        },
    )

    with pytest.raises(RuntimeError, match="broken"):
        await service.discover(FakePage(), target, "full")

    assert catalog.get_source(missing.source.id).available is True


async def test_incremental_streak_is_service_owned_and_stops_after_refreshing_two_known(
    tmp_path: Path,
) -> None:
    adapter = FakeDiscoveryAdapter(
        [
            record("new"),
            record("known-1", url="https://example.test/known-1-new"),
            record("known-2", url="https://example.test/known-2-new"),
            record("must-not-be-consumed"),
        ]
    )
    service, catalog, target = setup_service(tmp_path, adapter)
    for external_id in ("known-1", "known-2"):
        catalog.upsert_item_source(
            ItemInput(canonical_title=external_id),
            {
                "site": target.site,
                "external_id": external_id,
                "discovery_key": target.key,
                "url": f"https://example.test/{external_id}",
            },
        )

    result = await service.discover(FakePage(), target, "incremental")

    assert result.complete is None
    assert result.stopped_reason == "known_streak"
    assert (result.observed_count, result.new_count, result.known_count) == (3, 1, 2)
    assert adapter.yielded == ["new", "known-1", "known-2"]
    assert catalog.get_source_by_external_id(target.site, "known-1").url.endswith(
        "known-1-new"
    )
    assert catalog.get_source_by_external_id(target.site, "known-2").url.endswith(
        "known-2-new"
    )


async def test_incremental_unknown_resets_known_streak(tmp_path: Path) -> None:
    adapter = FakeDiscoveryAdapter(
        [record("known-1"), record("new"), record("known-2")]
    )
    service, catalog, target = setup_service(tmp_path, adapter)
    for external_id in ("known-1", "known-2"):
        catalog.upsert_item_source(
            ItemInput(canonical_title=external_id),
            {
                "site": target.site,
                "external_id": external_id,
                "discovery_key": target.key,
                "url": f"https://example.test/{external_id}",
            },
        )

    result = await service.discover(FakePage(), target, "incremental")

    assert result.stopped_reason == "exhausted"
    assert result.observed_count == 3
    assert result.known_count == 2


async def test_disabled_target_is_not_run(tmp_path: Path) -> None:
    adapter = FakeDiscoveryAdapter([record("never")])
    service, _, target = setup_service(tmp_path, adapter)
    disabled = WatchlistTarget(target.key, target.site, target.url, enabled=False)

    result = await service.discover(FakePage(), disabled, "full")

    assert result.stopped_reason == "disabled"
    assert adapter.calls == []


async def test_missing_external_id_is_rejected_without_url_fallback(tmp_path: Path) -> None:
    adapter = FakeDiscoveryAdapter([record("")])
    service, catalog, target = setup_service(tmp_path, adapter)

    with pytest.raises(CatalogValidationError, match="external_id"):
        await service.discover(FakePage(), target, "full")

    assert catalog.list_items() == []


async def test_cross_site_duplicate_is_warning_only(tmp_path: Path) -> None:
    adapter = FakeDiscoveryAdapter(
        [
            record(
                "site-b-1",
                title="  作品   A ",
                kind="volume",
                order_key="01",
            )
        ]
    )
    service, catalog, target = setup_service(tmp_path, adapter, site="bookwalker")
    catalog.upsert_item_source(
        ItemInput(canonical_title="作品 A", kind="volume", order_key="01"),
        {
            "site": "mangaone",
            "external_id": "site-a-1",
            "discovery_key": "mangaone-target",
            "url": "https://example.test/site-a-1",
        },
    )

    result = await service.discover(FakePage(), target, "full")

    assert len(result.warnings) == 1
    assert "Possible duplicate on another site" in result.warnings[0]
    assert len(catalog.list_items()) == 2
    assert len(catalog.list_sources()) == 2


async def test_same_site_or_mismatched_candidate_does_not_warn(tmp_path: Path) -> None:
    adapter = FakeDiscoveryAdapter([record("new", title="作品A", order_key="02")])
    service, catalog, target = setup_service(tmp_path, adapter)
    catalog.upsert_item_source(
        ItemInput(canonical_title="作品A", kind="volume", order_key="01"),
        {
            "site": target.site,
            "external_id": "existing",
            "discovery_key": "other-target",
            "url": "https://example.test/existing",
        },
    )

    result = await service.discover(FakePage(), target, "full")

    assert result.warnings == ()


def test_registry_is_separate_and_rejects_unknown_or_duplicate_sites() -> None:
    registry = DiscoveryAdapterRegistry()
    adapter = FakeDiscoveryAdapter([])
    registry.register("mangaone", lambda: adapter)

    assert registry.create("mangaone") is adapter
    assert registry.sites() == ("mangaone",)
    with pytest.raises(ValueError, match="already registered"):
        registry.register("mangaone", lambda: adapter)
    with pytest.raises(KeyError, match="Unknown discovery adapter"):
        registry.create("bookwalker")


async def test_unknown_mode_is_rejected_before_adapter_execution(tmp_path: Path) -> None:
    adapter = FakeDiscoveryAdapter([])
    service, _, target = setup_service(tmp_path, adapter)

    with pytest.raises(ValueError, match="Discovery mode"):
        await service.discover(FakePage(), target, "unknown")

    assert adapter.calls == []


def test_catalog_reconciliation_rolls_back_all_rows_on_failure(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite"
    catalog = CatalogService(path)
    for external_id in ("first", "second"):
        catalog.upsert_item_source(
            ItemInput(canonical_title=external_id),
            {
                "site": "mangaone",
                "external_id": external_id,
                "discovery_key": "target-one",
                "url": f"https://example.test/{external_id}",
            },
        )
    with catalog._connection() as connection:
        connection.execute(
            "CREATE TRIGGER fail_reconciliation BEFORE UPDATE ON sources "
            "WHEN NEW.external_id = 'second' BEGIN SELECT RAISE(ABORT, 'forced failure'); END"
        )

    with pytest.raises(sqlite3.IntegrityError, match="forced failure"):
        catalog.mark_sources_unavailable_except(
            site="mangaone",
            discovery_key="target-one",
            observed_external_ids=[],
        )

    assert all(source.available for source in catalog.list_sources(site="mangaone"))
