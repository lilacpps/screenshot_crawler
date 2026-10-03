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
from screenshot_crawler.watchlist import DiscoveryScope, WatchlistTarget


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
    access_granted_until: str | None = None,
    access_granted_until_observed: bool = False,
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
            access_granted_until=access_granted_until,
            access_granted_until_observed=access_granted_until_observed,
            available=available,
        ),
    )


async def test_discovery_propagates_explicit_grant_clear(tmp_path: Path) -> None:
    adapter = FakeDiscoveryAdapter(
        [
            record(
                "one",
                access_mode="paid",
                access_granted_until="2026-09-26T11:41:00+09:00",
                access_granted_until_observed=True,
            )
        ]
    )
    service, catalog, watch_target = setup_service(tmp_path, adapter)
    await service.discover(FakePage(), watch_target, "full")
    assert catalog.list_sources()[0].access_granted_until == "2026-09-26T11:41:00+09:00"

    adapter.records = [
        record(
            "one",
            access_mode="paid",
            access_granted_until=None,
            access_granted_until_observed=True,
        )
    ]
    await service.discover(FakePage(), watch_target, "full")
    assert catalog.list_sources()[0].access_granted_until is None


async def test_comicdays_discovery_grant_unknown_preservation_and_authoritative_clear(
    tmp_path: Path,
) -> None:
    adapter = FakeDiscoveryAdapter(
        [record("episode", access_mode="quota", access_granted_until="2026-10-06T10:22:56+09:00", access_granted_until_observed=True)]
    )
    service, catalog, watch_target = setup_service(
        tmp_path, adapter, site="comicdays", watch_target=target(site="comicdays")
    )
    await service.discover(FakePage(), watch_target, "full")
    item = catalog.list_items()[0]
    catalog.mark_item_completed(item.id)
    assert catalog.list_sources()[0].access_granted_until == "2026-10-06T10:22:56+09:00"

    adapter.records = [record("episode", access_mode="unknown", access_granted_until_observed=False)]
    await service.discover(FakePage(), watch_target, "full")
    preserved = catalog.list_sources()[0]
    assert preserved.access_granted_until == "2026-10-06T10:22:56+09:00"
    assert catalog.get_item(item.id).status == "completed"

    adapter.records = [record("episode", access_mode="paid", access_granted_until_observed=True)]
    await service.discover(FakePage(), watch_target, "full")
    assert catalog.list_sources()[0].access_granted_until is None
    assert catalog.get_item(item.id).status == "completed"


class FakeDiscoveryAdapter(DiscoveryAdapter):
    def __init__(
        self,
        records: list[DiscoveredRecord],
        *,
        failure: Exception | None = None,
        reconciled_access_mode: str | None = None,
        stop_decision: IncrementalStopDecision = IncrementalStopDecision.DEFAULT,
        stop_after: str | None = None,
    ) -> None:
        self.records = records
        self.failure = failure
        self.reconciled_access_mode = reconciled_access_mode
        self.stop_decision = stop_decision
        self.stop_after = stop_after
        self.iter_records_calls = 0
        self.reconciliation_calls: list[tuple[str, DiscoverySourceSnapshot | None]] = []
        self.stop_calls: list[str] = []

    def iter_records(self, page: FakePage, target: WatchlistTarget, mode: str):
        del page, target, mode
        self.iter_records_calls += 1

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
        if self.stop_after == record.source.external_id:
            return IncrementalStopDecision.STOP
        return self.stop_decision


class BoundedFakeDiscoveryAdapter(FakeDiscoveryAdapter):
    supports_bounded_discovery = True


def target(
    *,
    key: str = "scope-a",
    work_key: str = "work-a",
    site: str = "site-a",
    label: str = "作品A",
    enabled: bool = True,
    discovery_scope: DiscoveryScope | None = None,
) -> WatchlistTarget:
    return WatchlistTarget(
        key=key,
        work_key=work_key,
        site=site,
        url=f"https://example.test/{key}",
        label=label,
        enabled=enabled,
        discovery_scope=discovery_scope,
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
    assert adapter.iter_records_calls == 1
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


async def test_bounded_same_work_key_still_never_merges_items_cross_site(
    tmp_path: Path,
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    registry = DiscoveryAdapterRegistry()
    registry.register(
        "site-a",
        lambda: BoundedFakeDiscoveryAdapter([record("a", order_key="1")]),
    )
    registry.register(
        "site-b",
        lambda: BoundedFakeDiscoveryAdapter([record("b", order_key="1")]),
    )
    service = DiscoveryService(catalog, registry)
    scope = DiscoveryScope(from_url="https://example.test/from")
    target_a = target(
        key="scope-a",
        work_key="shared",
        site="site-a",
        discovery_scope=scope,
    )
    target_b = target(
        key="scope-b",
        work_key="shared",
        site="site-b",
        discovery_scope=scope,
    )

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


async def test_discovery_refresh_preserves_operator_item_status_and_note(
    tmp_path: Path,
) -> None:
    adapter = FakeDiscoveryAdapter([record("one")])
    service, catalog, watch_target = setup_service(tmp_path, adapter)
    await service.discover(FakePage(), watch_target, "full")
    item = catalog.list_items()[0]
    catalog.mark_item_external(item.id)
    catalog.set_item_note(item.id, "already archived manually")

    await service.discover(FakePage(), watch_target, "full")

    refreshed = catalog.get_item(item.id)
    assert refreshed.status == "external"
    assert refreshed.completed_at is None
    assert refreshed.note == "already archived manually"


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


@pytest.mark.parametrize(
    ("adapter_factory", "discovery_scope"),
    [
        (FakeDiscoveryAdapter, None),
        (
            BoundedFakeDiscoveryAdapter,
            DiscoveryScope(from_url="https://example.test/from"),
        ),
    ],
)
async def test_incremental_known_streak_and_run_start_snapshot_are_preserved(
    tmp_path: Path,
    adapter_factory,
    discovery_scope: DiscoveryScope | None,
) -> None:
    adapter = adapter_factory(
        [record(external_id) for external_id in ("one", "two", "three", "four", "five", "six")]
    )
    service, catalog, watch_target = setup_service(
        tmp_path,
        adapter,
        watch_target=target(discovery_scope=discovery_scope),
    )
    work = catalog.create_work(WorkInput(work_key="work-a", title="作品A"))
    for external_id in ("one", "two", "three", "four", "five"):
        item = catalog.create_item(work_id=work.id)
        catalog.create_source(
            SourceInput(site="site-a", external_id=external_id, discovery_key=watch_target.key),
            item_id=item.id,
        )

    result = await service.discover(FakePage(), watch_target, "incremental")
    assert result.stopped_reason == "known_streak"
    assert result.observed_count == 5
    assert catalog.find_source("site-a", "six") is None


async def test_incremental_known_streak_resets_after_new_source(tmp_path: Path) -> None:
    adapter = FakeDiscoveryAdapter(
        [
            record(external_id)
            for external_id in (
                "known-a",
                "known-b",
                "new-c",
                "known-d",
                "known-e",
                "known-f",
                "known-g",
                "known-h",
            )
        ]
    )
    service, catalog, watch_target = setup_service(tmp_path, adapter)
    work = catalog.create_work(WorkInput(work_key="work-a", title="作品A"))
    for external_id in ("known-a", "known-b", "known-d", "known-e", "known-f", "known-g", "known-h"):
        item = catalog.create_item(work_id=work.id)
        catalog.create_source(
            SourceInput(site="site-a", external_id=external_id, discovery_key=watch_target.key),
            item_id=item.id,
        )

    result = await service.discover(FakePage(), watch_target, "incremental")

    assert result.stopped_reason == "known_streak"
    assert result.observed_count == 8
    assert result.new_count == 1


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


@pytest.mark.parametrize(
    ("mode", "expected_complete"),
    [("full", False), ("incremental", None)],
)
async def test_bounded_scope_fails_closed_before_adapter_iteration_or_catalog_mutation(
    tmp_path: Path, mode: str, expected_complete: bool | None
) -> None:
    adapter = FakeDiscoveryAdapter([record("should-not-be-observed")])
    service, catalog, watch_target = setup_service(
        tmp_path,
        adapter,
        watch_target=target(
            discovery_scope=DiscoveryScope(from_url="https://example.test/from")
        ),
    )

    result = await service.discover(FakePage(), watch_target, mode)

    assert result.complete is expected_complete
    assert result.stopped_reason == "incomplete"
    assert result.observed_count == 0
    assert result.new_count == 0
    assert result.known_count == 0
    assert adapter.iter_records_calls == 0
    assert adapter.reconciliation_calls == []
    assert catalog.list_works() == []
    assert catalog.list_items() == []
    assert catalog.list_sources() == []
    assert catalog.list_source_targets() == []


async def test_bounded_full_syncs_records_without_global_reconciliation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = BoundedFakeDiscoveryAdapter([record("observed")])
    service, catalog, watch_target = setup_service(
        tmp_path,
        adapter,
        watch_target=target(
            discovery_scope=DiscoveryScope(from_url="https://example.test/from")
        ),
    )
    work = catalog.create_work(WorkInput(work_key="work-a", title="作品A"))
    outside_item = catalog.create_item(work_id=work.id)
    outside = catalog.create_source(
        SourceInput(
            site="site-a",
            external_id="outside-scope",
            discovery_key=watch_target.key,
            available=True,
        ),
        item_id=outside_item.id,
    )
    reconciliation_calls: list[dict[str, object]] = []

    def spy_mark_sources_unavailable_except(**kwargs: object) -> None:
        reconciliation_calls.append(kwargs)

    monkeypatch.setattr(
        catalog,
        "mark_sources_unavailable_except",
        spy_mark_sources_unavailable_except,
    )

    result = await service.discover(FakePage(), watch_target, "full")

    assert result.complete is True
    assert result.stopped_reason == "exhausted"
    assert adapter.iter_records_calls == 1
    assert catalog.find_source("site-a", "observed") is not None
    assert catalog.get_source(outside.id).available is True
    assert reconciliation_calls == []


async def test_bounded_incremental_preserves_adapter_stop_hook_after_sync(
    tmp_path: Path,
) -> None:
    adapter = BoundedFakeDiscoveryAdapter(
        [record("one")], stop_decision=IncrementalStopDecision.STOP
    )
    service, catalog, watch_target = setup_service(
        tmp_path,
        adapter,
        watch_target=target(
            discovery_scope=DiscoveryScope(through_url="https://example.test/through")
        ),
    )

    result = await service.discover(FakePage(), watch_target, "incremental")

    assert result.complete is None
    assert result.stopped_reason == "stable_boundary"
    assert result.observed_count == 1
    assert adapter.stop_calls == ["one"]
    assert catalog.find_source("site-a", "one") is not None


async def test_full_discovery_assigns_oldest_to_newest_positions(
    tmp_path: Path,
) -> None:
    adapter = FakeDiscoveryAdapter([record(external_id) for external_id in ("D", "C", "B", "A")])
    service, catalog, watch_target = setup_service(tmp_path, adapter)

    result = await service.discover(FakePage(), watch_target, "full")

    assert result.complete is True
    assert {
        external_id: catalog.find_source("site-a", external_id).display_position
        for external_id in ("A", "B", "C", "D")
    } == {"A": 1, "B": 2, "C": 3, "D": 4}


async def test_full_discovery_rerun_renumbers_existing_sources(
    tmp_path: Path,
) -> None:
    adapter = FakeDiscoveryAdapter([record(external_id) for external_id in ("C", "B", "A")])
    service, catalog, watch_target = setup_service(tmp_path, adapter)
    await service.discover(FakePage(), watch_target, "full")

    adapter.records = [record(external_id) for external_id in ("D", "C", "bonus", "B", "A")]
    result = await service.discover(FakePage(), watch_target, "full")

    assert result.complete is True
    assert {
        external_id: catalog.find_source("site-a", external_id).display_position
        for external_id in ("A", "B", "bonus", "C", "D")
    } == {"A": 1, "B": 2, "bonus": 3, "C": 4, "D": 5}


async def test_incomplete_full_discovery_does_not_assign_positions(
    tmp_path: Path,
) -> None:
    adapter = FakeDiscoveryAdapter([record(external_id) for external_id in ("C", "B", "A")])
    service, catalog, watch_target = setup_service(tmp_path, adapter)
    await service.discover(FakePage(), watch_target, "full")
    before = {
        external_id: catalog.find_source("site-a", external_id).display_position
        for external_id in ("A", "B", "C")
    }

    adapter.records = [record("new-1"), record("new-2")]
    adapter.failure = DiscoveryIncompleteError("listing incomplete")
    result = await service.discover(FakePage(), watch_target, "full")

    assert result.complete is False
    assert {
        external_id: catalog.find_source("site-a", external_id).display_position
        for external_id in ("A", "B", "C")
    } == before
    assert catalog.find_source("site-a", "new-1").display_position is None
    assert catalog.find_source("site-a", "new-2").display_position is None


async def test_bounded_full_positions_are_scope_local(
    tmp_path: Path,
) -> None:
    adapter = BoundedFakeDiscoveryAdapter(
        [record(external_id) for external_id in ("C", "B", "A")]
    )
    service, catalog, watch_target = setup_service(
        tmp_path,
        adapter,
        watch_target=target(
            discovery_scope=DiscoveryScope(from_url="https://example.test/from")
        ),
    )
    work = catalog.create_work(WorkInput(work_key="work-a", title="菴懷刀A"))
    outside_item = catalog.create_item(work_id=work.id)
    outside = catalog.create_source(
        SourceInput(
            site="site-a",
            external_id="outside",
            discovery_key=watch_target.key,
            display_position=99,
        ),
        item_id=outside_item.id,
    )

    result = await service.discover(FakePage(), watch_target, "full")

    assert result.complete is True
    assert {
        external_id: catalog.find_source("site-a", external_id).display_position
        for external_id in ("A", "B", "C")
    } == {"A": 1, "B": 2, "C": 3}
    assert catalog.get_source(outside.id).display_position == 99


async def test_incremental_stable_boundary_appends_oldest_to_newest(
    tmp_path: Path,
) -> None:
    adapter = FakeDiscoveryAdapter(
        [record(external_id) for external_id in ("F", "E", "D", "C", "B", "A")],
        stop_after="A",
    )
    service, catalog, watch_target = setup_service(tmp_path, adapter)
    work = catalog.create_work(WorkInput(work_key="work-a", title="菴懷刀A"))
    existing = []
    for external_id, position in (("A", 1), ("B", 2), ("C", 3)):
        item = catalog.create_item(work_id=work.id)
        existing.append(
            catalog.create_source(
                SourceInput(
                    site="site-a",
                    external_id=external_id,
                    discovery_key=watch_target.key,
                    display_position=position,
                ),
                item_id=item.id,
            )
        )

    result = await service.discover(FakePage(), watch_target, "incremental")

    assert result.stopped_reason == "stable_boundary"
    assert [catalog.get_source(source.id).display_position for source in existing] == [1, 2, 3]
    assert {
        external_id: catalog.find_source("site-a", external_id).display_position
        for external_id in ("D", "E", "F")
    } == {"D": 4, "E": 5, "F": 6}


async def test_incremental_stable_boundary_ignores_unobserved_historical_high_position(
    tmp_path: Path,
) -> None:
    adapter = FakeDiscoveryAdapter(
        [record(external_id) for external_id in ("E", "D", "C")],
        stop_after="C",
    )
    service, catalog, watch_target = setup_service(tmp_path, adapter)
    work = catalog.create_work(WorkInput(work_key="work-a", title="作品A"))
    for external_id, position, available in (
        ("A", 1, True),
        ("B", 2, True),
        ("C", 3, True),
        ("historical", 99, False),
    ):
        item = catalog.create_item(work_id=work.id)
        catalog.create_source(
            SourceInput(
                site="site-a",
                external_id=external_id,
                discovery_key=watch_target.key,
                available=available,
                display_position=position,
            ),
            item_id=item.id,
        )

    result = await service.discover(FakePage(), watch_target, "incremental")

    assert result.stopped_reason == "stable_boundary"
    assert {
        external_id: catalog.find_source("site-a", external_id).display_position
        for external_id in ("D", "E")
    } == {"D": 4, "E": 5}
    assert catalog.find_source("site-a", "historical").display_position == 99


async def test_incremental_known_streak_appends_and_recovers_null_sources(
    tmp_path: Path,
) -> None:
    adapter = FakeDiscoveryAdapter(
        [record(external_id) for external_id in ("103", "102", "101", "100", "99", "98", "97", "96")]
    )
    service, catalog, watch_target = setup_service(tmp_path, adapter)
    work = catalog.create_work(WorkInput(work_key="work-a", title="菴懷刀A"))
    for external_id, position in (("100", 100), ("99", 99), ("98", 98), ("97", 97), ("96", 96)):
        item = catalog.create_item(work_id=work.id)
        catalog.create_source(
            SourceInput(
                site="site-a",
                external_id=external_id,
                discovery_key=watch_target.key,
                display_position=position,
            ),
            item_id=item.id,
        )

    result = await service.discover(FakePage(), watch_target, "incremental")

    assert result.stopped_reason == "known_streak"
    assert {
        external_id: catalog.find_source("site-a", external_id).display_position
        for external_id in ("101", "102", "103")
    } == {"101": 101, "102": 102, "103": 103}
    assert catalog.find_source("site-a", "100").display_position == 100


async def test_incremental_recovers_previous_incomplete_null_sources(
    tmp_path: Path,
) -> None:
    adapter = FakeDiscoveryAdapter(
        [record(external_id) for external_id in ("103", "102", "101", "100")],
        stop_after="100",
    )
    service, catalog, watch_target = setup_service(tmp_path, adapter)
    work = catalog.create_work(WorkInput(work_key="work-a", title="菴懷刀A"))
    for external_id, position in (("103", None), ("102", None), ("100", 100)):
        item = catalog.create_item(work_id=work.id)
        catalog.create_source(
            SourceInput(
                site="site-a",
                external_id=external_id,
                discovery_key=watch_target.key,
                display_position=position,
            ),
            item_id=item.id,
        )

    result = await service.discover(FakePage(), watch_target, "incremental")

    assert result.stopped_reason == "stable_boundary"
    assert {
        external_id: catalog.find_source("site-a", external_id).display_position
        for external_id in ("101", "102", "103")
    } == {"101": 101, "102": 102, "103": 103}


async def test_incomplete_incremental_leaves_existing_and_new_positions_unchanged(
    tmp_path: Path,
) -> None:
    adapter = FakeDiscoveryAdapter(
        [record("new-2"), record("new-1")],
        failure=DiscoveryIncompleteError("listing incomplete"),
    )
    service, catalog, watch_target = setup_service(tmp_path, adapter)
    work = catalog.create_work(WorkInput(work_key="work-a", title="菴懷刀A"))
    item = catalog.create_item(work_id=work.id)
    existing = catalog.create_source(
        SourceInput(
            site="site-a",
            external_id="known",
            discovery_key=watch_target.key,
            display_position=7,
        ),
        item_id=item.id,
    )

    result = await service.discover(FakePage(), watch_target, "incremental")

    assert result.complete is None
    assert result.stopped_reason == "incomplete"
    assert catalog.get_source(existing.id).display_position == 7
    assert catalog.find_source("site-a", "new-1").display_position is None
    assert catalog.find_source("site-a", "new-2").display_position is None


async def test_incremental_without_baseline_and_early_stop_fails_safe(
    tmp_path: Path,
) -> None:
    adapter = FakeDiscoveryAdapter(
        [record("new"), record("known")],
        stop_after="known",
    )
    service, catalog, watch_target = setup_service(tmp_path, adapter)
    work = catalog.create_work(WorkInput(work_key="work-a", title="菴懷刀A"))
    item = catalog.create_item(work_id=work.id)
    catalog.create_source(
        SourceInput(site="site-a", external_id="known", discovery_key=watch_target.key),
        item_id=item.id,
    )

    result = await service.discover(FakePage(), watch_target, "incremental")

    assert result.stopped_reason == "stable_boundary"
    assert catalog.find_source("site-a", "new").display_position is None
    assert catalog.find_source("site-a", "known").display_position is None


async def test_incremental_early_stop_ignores_unobserved_positioned_source(
    tmp_path: Path,
) -> None:
    adapter = FakeDiscoveryAdapter(
        [record(external_id) for external_id in ("new-2", "new-1")],
        stop_after="new-1",
    )
    service, catalog, watch_target = setup_service(tmp_path, adapter)
    work = catalog.create_work(WorkInput(work_key="work-a", title="作品A"))
    item = catalog.create_item(work_id=work.id)
    catalog.create_source(
        SourceInput(
            site="site-a",
            external_id="historical",
            discovery_key=watch_target.key,
            available=False,
            display_position=50,
        ),
        item_id=item.id,
    )

    result = await service.discover(FakePage(), watch_target, "incremental")

    assert result.stopped_reason == "stable_boundary"
    assert catalog.find_source("site-a", "new-1").display_position is None
    assert catalog.find_source("site-a", "new-2").display_position is None
    assert catalog.find_source("site-a", "historical").display_position == 50


async def test_incremental_without_baseline_but_exhausted_assigns_full_scope(
    tmp_path: Path,
) -> None:
    adapter = FakeDiscoveryAdapter([record(external_id) for external_id in ("C", "B", "A")])
    service, catalog, watch_target = setup_service(tmp_path, adapter)

    result = await service.discover(FakePage(), watch_target, "incremental")

    assert result.stopped_reason == "exhausted"
    assert {
        external_id: catalog.find_source("site-a", external_id).display_position
        for external_id in ("A", "B", "C")
    } == {"A": 1, "B": 2, "C": 3}


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
