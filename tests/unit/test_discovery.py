from pathlib import Path

import pytest

from screenshot_crawler.catalog import (
    CatalogService,
    CatalogValidationError,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)
from screenshot_crawler.discovery import (
    DiscoveredItem,
    DiscoveredRecord,
    DiscoveredSource,
    DiscoveryAdapter,
    DiscoveryAdapterRegistry,
    DiscoveryIncompleteError,
    DiscoveryService,
    DiscoverySourceSnapshot,
    IncrementalStopDecision,
)
from screenshot_crawler.watchlist import WatchlistTarget


class FakePage:
    pass


def record(
    external_id: str,
    *,
    title: str | None = "Observed title",
    url: str | None = None,
    kind: str | None = "episode",
    order_key: str | None = None,
    order_label: str | None = None,
    author: str | None = None,
    genre: str | None = None,
    access_mode: str = "free",
    available: bool | None = True,
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
        ),
    )


class FakeDiscoveryAdapter(DiscoveryAdapter):
    def __init__(
        self,
        records: list[DiscoveredRecord],
        *,
        failure: Exception | None = None,
        reconciled_access_mode: str | None = None,
        stop_decision: IncrementalStopDecision = IncrementalStopDecision.DEFAULT,
    ) -> None:
        self.records = records
        self.failure = failure
        self.reconciled_access_mode = reconciled_access_mode
        self.stop_decision = stop_decision
        self.reconciliation_calls: list[tuple[str, DiscoverySourceSnapshot | None]] = []
        self.stop_calls: list[str] = []

    def iter_records(self, page: FakePage, target: WatchlistTarget, mode: str):
        del page, target, mode

        async def generate():
            for discovered in self.records:
                yield discovered
            if self.failure is not None:
                raise self.failure

        return generate()

    def reconcile_access_mode(
        self,
        observed_access_mode: str,
        previous: DiscoverySourceSnapshot | None,
        target: WatchlistTarget,
    ) -> str:
        del target
        self.reconciliation_calls.append((observed_access_mode, previous))
        return self.reconciled_access_mode or observed_access_mode

    def incremental_stop_decision(
        self,
        record: DiscoveredRecord,
        previous: DiscoverySourceSnapshot | None,
        target: WatchlistTarget,
    ) -> IncrementalStopDecision:
        del previous, target
        self.stop_calls.append(record.source.external_id)
        return self.stop_decision


def target(
    *,
    key: str = "scope-a",
    work_key: str = "work-a",
    site: str = "site-a",
    label: str = "作品A",
    enabled: bool = True,
) -> WatchlistTarget:
    return WatchlistTarget(
        key=key,
        work_key=work_key,
        site=site,
        url=f"https://example.test/{key}",
        label=label,
        enabled=enabled,
    )


def setup_service(
    tmp_path: Path,
    adapter: FakeDiscoveryAdapter,
    *,
    site: str = "site-a",
    watch_target: WatchlistTarget | None = None,
) -> tuple[DiscoveryService, CatalogService, WatchlistTarget]:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    registry = DiscoveryAdapterRegistry()
    registry.register(site, lambda: adapter)
    return DiscoveryService(catalog, registry), catalog, watch_target or target(site=site)


async def test_first_discovery_creates_work_item_source_and_web_default(tmp_path: Path) -> None:
    adapter = FakeDiscoveryAdapter([record("one", title="Adapter title", order_key="1")])
    service, catalog, watch_target = setup_service(tmp_path, adapter)

    result = await service.discover(FakePage(), watch_target, "full")

    assert result.complete is True
    work = catalog.find_work("work-a")
    assert work is not None
    assert work.title == "作品A"
    item = catalog.list_items()[0]
    assert item.work_id == work.id
    assert item.order_key == "1"
    assert item.item_title is None
    source = catalog.list_sources()[0]
    assert source.discovery_key == "scope-a"
    web = catalog.find_source_target(source.id, "web", "default")
    assert web is not None
    assert web.locator == "https://example.test/one"
    assert len(catalog.list_source_targets()) == 1

    rerun = await service.discover(FakePage(), watch_target, "full")
    assert (rerun.new_count, rerun.known_count) == (0, 1)
    assert len(catalog.list_works()) == 1
    assert len(catalog.list_items()) == 1
    assert catalog.list_items()[0].id == item.id
    assert catalog.list_sources()[0].id == source.id
    assert catalog.find_source_target(source.id, "web").id == web.id


async def test_existing_work_title_is_authoritative_and_metadata_only_fills_nulls(
    tmp_path: Path,
) -> None:
    adapter = FakeDiscoveryAdapter(
        [record("one", title="Observed", author="Author A", genre="Genre A")]
    )
    service, catalog, watch_target = setup_service(tmp_path, adapter)
    await service.discover(FakePage(), watch_target, "full")
    work = catalog.find_work("work-a")
    assert work is not None
    item = catalog.list_items()[0]
    catalog.mark_item_completed(item.id)

    adapter.records = [
        record(
            "one", title="Changed", author="Author B", genre="Genre B",
            kind="volume", order_key="2", order_label="第2巻",
            url="https://example.test/new",
        )
    ]
    await service.discover(FakePage(), watch_target, "full")

    refreshed_work = catalog.get_work(work.id)
    refreshed_item = catalog.get_item(item.id)
    assert refreshed_work.title == "作品A"
    assert refreshed_work.author == "Author A"
    assert refreshed_work.genre == "Genre A"
    assert refreshed_item.status == "completed"
    assert refreshed_item.order_key == "2"
    assert refreshed_item.order_label == "第2巻"
    assert catalog.find_source_target(catalog.list_sources()[0].id, "web").locator.endswith("/new")


async def test_work_metadata_fills_when_initially_null_and_null_item_values_do_not_clear(
    tmp_path: Path,
) -> None:
    adapter = FakeDiscoveryAdapter([record("one", author="Author", genre="Genre", order_key="1")])
    service, catalog, watch_target = setup_service(tmp_path, adapter)
    await service.discover(FakePage(), watch_target, "full")
    item = catalog.list_items()[0]
    adapter.records = [record("one", author=None, genre=None, order_key=None, order_label=None)]
    await service.discover(FakePage(), watch_target, "full")
    assert catalog.get_work(catalog.list_works()[0].id).author == "Author"
    assert catalog.get_work(catalog.list_works()[0].id).genre == "Genre"
    refreshed = catalog.get_item(item.id)
    assert refreshed.order_key == "1"


async def test_same_work_key_shares_work_but_never_merges_items_cross_site(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    registry = DiscoveryAdapterRegistry()
    registry.register("site-a", lambda: FakeDiscoveryAdapter([record("a", order_key="1")]))
    registry.register("site-b", lambda: FakeDiscoveryAdapter([record("b", order_key="1")]))
    service = DiscoveryService(catalog, registry)
    target_a = target(key="scope-a", work_key="shared", site="site-a")
    target_b = target(key="scope-b", work_key="shared", site="site-b")

    await service.discover(FakePage(), target_a, "full")
    result = await service.discover(FakePage(), target_b, "full")

    assert len(catalog.list_works()) == 1
    assert len(catalog.list_items()) == 2
    assert len(catalog.list_sources()) == 2
    assert len(result.warnings) == 1
    assert "Possible duplicate on another site" in result.warnings[0]


async def test_different_work_keys_do_not_merge_by_same_label(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    registry = DiscoveryAdapterRegistry()
    registry.register("site-a", lambda: FakeDiscoveryAdapter([record("a", order_key="1")]))
    registry.register("site-b", lambda: FakeDiscoveryAdapter([record("b", order_key="1")]))
    service = DiscoveryService(catalog, registry)
    await service.discover(FakePage(), target(site="site-a", work_key="work-a"), "full")
    await service.discover(FakePage(), target(site="site-b", work_key="work-b"), "full")
    assert len(catalog.list_works()) == 2
    assert all(result is not None for result in (catalog.find_work("work-a"), catalog.find_work("work-b")))


async def test_scope_conflict_is_incomplete_without_external_mutation(tmp_path: Path) -> None:
    adapter = FakeDiscoveryAdapter([record("one", access_mode="owned")])
    service, catalog, watch_target = setup_service(tmp_path, adapter)
    work = catalog.create_work(WorkInput(work_key="work-a", title="作品A"))
    item = catalog.create_item(work_id=work.id)
    source = catalog.create_source(
        SourceInput(site="site-a", external_id="one", discovery_key="other-scope", access_mode="free"),
        item_id=item.id,
    )

    result = await service.discover(FakePage(), watch_target, "full")

    assert result.stopped_reason == "incomplete"
    unchanged = catalog.get_source(source.id)
    assert unchanged.discovery_key == "other-scope"
    assert unchanged.access_mode == "free"


async def test_unscoped_source_is_adopted_by_matching_work_scope(tmp_path: Path) -> None:
    adapter = FakeDiscoveryAdapter(
        [record("one", access_mode="owned", url="https://example.test/adopted")]
    )
    service, catalog, watch_target = setup_service(tmp_path, adapter)
    work = catalog.create_work(WorkInput(work_key="work-a", title="作品A"))
    item = catalog.create_item(work_id=work.id)
    source = catalog.create_source(
        SourceInput(site="site-a", external_id="one", access_mode="free"),
        item_id=item.id,
    )

    result = await service.discover(FakePage(), watch_target, "full")

    assert result.complete is True
    assert catalog.get_item(item.id).id == item.id
    adopted = catalog.get_source(source.id)
    assert adopted.id == source.id
    assert adopted.item_id == item.id
    assert adopted.discovery_key == "scope-a"
    assert adopted.access_mode == "owned"
    web = catalog.find_source_target(source.id, "web", "default")
    assert web is not None
    assert web.locator == "https://example.test/adopted"
    assert len(catalog.list_items()) == 1
    assert len(catalog.list_sources()) == 1


async def test_unscoped_source_with_different_work_is_rejected_without_mutation(
    tmp_path: Path,
) -> None:
    adapter = FakeDiscoveryAdapter([record("one", access_mode="owned")])
    service, catalog, watch_target = setup_service(
        tmp_path, adapter, watch_target=target(work_key="work-b", label="作品B")
    )
    work_a = catalog.create_work(WorkInput(work_key="work-a", title="作品A"))
    item = catalog.create_item(work_id=work_a.id)
    source = catalog.create_source(
        SourceInput(site="site-a", external_id="one", access_mode="free"),
        item_id=item.id,
    )

    result = await service.discover(FakePage(), watch_target, "full")

    assert result.stopped_reason == "incomplete"
    unchanged = catalog.get_source(source.id)
    assert unchanged.discovery_key is None
    assert unchanged.access_mode == "free"
    assert unchanged.item_id == item.id
    assert catalog.get_item(item.id).work_id == work_a.id
    assert catalog.find_source_target(source.id, "web", "default") is None


async def test_work_association_conflict_is_incomplete_without_reparenting(tmp_path: Path) -> None:
    adapter = FakeDiscoveryAdapter([record("one")])
    service, catalog, watch_target = setup_service(tmp_path, adapter)
    other_work = catalog.create_work(WorkInput(work_key="other", title="Other"))
    item = catalog.create_item(work_id=other_work.id)
    source = catalog.create_source(
        SourceInput(site="site-a", external_id="one", discovery_key=watch_target.key),
        item_id=item.id,
    )

    result = await service.discover(FakePage(), watch_target, "full")

    assert result.stopped_reason == "incomplete"
    assert catalog.get_item(item.id).work_id == other_work.id
    assert catalog.get_source(source.id).item_id == item.id


async def test_android_target_is_preserved_while_web_default_refreshes(tmp_path: Path) -> None:
    adapter = FakeDiscoveryAdapter([record("one", url="https://example.test/old")])
    service, catalog, watch_target = setup_service(tmp_path, adapter)
    await service.discover(FakePage(), watch_target, "full")
    source = catalog.list_sources()[0]
    android = catalog.create_source_target(
        SourceTargetInput(backend="android", target_key="default", locator="app://one"),
        source_id=source.id,
    )
    adapter.records = [record("one", url="https://example.test/new")]
    await service.discover(FakePage(), watch_target, "full")
    web = catalog.find_source_target(source.id, "web", "default")
    assert web is not None and web.locator.endswith("/new")
    assert catalog.get_source_target(android.id) == android


async def test_full_reconciliation_only_happens_after_complete_exhaustion(tmp_path: Path) -> None:
    adapter = FakeDiscoveryAdapter([record("observed")])
    service, catalog, watch_target = setup_service(tmp_path, adapter)
    work = catalog.create_work(WorkInput(work_key="work-a", title="作品A"))
    missing_item = catalog.create_item(work_id=work.id)
    missing = catalog.create_source(
        SourceInput(site="site-a", external_id="missing", discovery_key=watch_target.key),
        item_id=missing_item.id,
    )
    complete = await service.discover(FakePage(), watch_target, "full")
    assert complete.complete is True
    assert catalog.get_source(missing.id).available is False

    catalog.update_source_external_state("site-a", "missing", available=True)
    adapter.failure = DiscoveryIncompleteError("listing incomplete")
    incomplete = await service.discover(FakePage(), watch_target, "full")
    assert incomplete.complete is False
    assert catalog.get_source(missing.id).available is True


async def test_incremental_known_streak_and_run_start_snapshot_are_preserved(tmp_path: Path) -> None:
    adapter = FakeDiscoveryAdapter([record("one"), record("two"), record("three")])
    service, catalog, watch_target = setup_service(tmp_path, adapter)
    work = catalog.create_work(WorkInput(work_key="work-a", title="作品A"))
    for external_id in ("one", "two"):
        item = catalog.create_item(work_id=work.id)
        catalog.create_source(
            SourceInput(site="site-a", external_id=external_id, discovery_key=watch_target.key),
            item_id=item.id,
        )

    result = await service.discover(FakePage(), watch_target, "incremental")
    assert result.stopped_reason == "known_streak"
    assert result.observed_count == 2
    assert catalog.find_source("site-a", "three") is None


async def test_incremental_duplicate_known_source_does_not_increase_streak(
    tmp_path: Path,
) -> None:
    adapter = FakeDiscoveryAdapter(
        [
            record("known-a", url="https://example.test/first"),
            record("known-a", url="https://example.test/latest"),
            record("new-b"),
        ]
    )
    service, catalog, watch_target = setup_service(tmp_path, adapter)
    work = catalog.create_work(WorkInput(work_key="work-a", title="作品A"))
    item = catalog.create_item(work_id=work.id)
    known = catalog.create_source(
        SourceInput(
            site="site-a",
            external_id="known-a",
            discovery_key=watch_target.key,
        ),
        item_id=item.id,
    )

    result = await service.discover(FakePage(), watch_target, "incremental")

    assert result.stopped_reason == "exhausted"
    assert result.observed_count == 3
    assert catalog.find_source("site-a", "new-b") is not None
    web = catalog.find_source_target(known.id, "web", "default")
    assert web is not None
    assert web.locator == "https://example.test/latest"


async def test_disabled_target_does_not_create_work(tmp_path: Path) -> None:
    adapter = FakeDiscoveryAdapter([record("never")])
    service, catalog, watch_target = setup_service(
        tmp_path, adapter, watch_target=target(enabled=False)
    )
    result = await service.discover(FakePage(), watch_target, "full")
    assert result.stopped_reason == "disabled"
    assert catalog.list_works() == []


def test_discovered_graph_insert_is_atomic(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key="work-a", title="作品A"))
    with catalog._connection() as connection:
        connection.execute(
            "CREATE TRIGGER fail_discovered_source BEFORE INSERT ON sources "
            "WHEN NEW.external_id = 'fail' BEGIN SELECT RAISE(ABORT, 'forced failure'); END"
        )
    with pytest.raises(CatalogValidationError, match="forced failure"):
        catalog.create_discovered_item_source_target(
            work_id=work.id,
            item_input=ItemInput(kind="episode"),
            source_input=SourceInput(site="site-a", external_id="fail"),
            web_target_input=SourceTargetInput(backend="web", locator="https://example.test/fail"),
        )
    assert catalog.list_items() == []
    assert catalog.list_sources() == []
    assert catalog.list_source_targets() == []


async def test_adapter_access_reconciliation_and_incomplete_failure_preserve_hooks(
    tmp_path: Path,
) -> None:
    adapter = FakeDiscoveryAdapter(
        [record("one", access_mode="paid")], reconciled_access_mode="quota"
    )
    service, catalog, watch_target = setup_service(tmp_path, adapter)
    result = await service.discover(FakePage(), watch_target, "full")
    assert result.complete is True
    assert catalog.list_sources()[0].access_mode == "quota"
    assert adapter.reconciliation_calls[0][1] is None
