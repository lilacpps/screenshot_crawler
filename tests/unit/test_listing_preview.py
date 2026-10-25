from dataclasses import replace
from datetime import UTC, datetime

from screenshot_crawler.catalog import CatalogService, ItemInput, SourceInput, WorkInput
from screenshot_crawler.discovery import (
    DiscoveryAdapter,
    DiscoveryAdapterRegistry,
    DiscoveryService,
    ListingPreview,
    ListingPreviewService,
    ListingRow,
    listing_digest,
)
from screenshot_crawler.watchlist import (
    ArchiveArtifactFact,
    ArchiveFactsSnapshot,
    SelectionPlanner,
    WatchlistTarget,
)
from screenshot_crawler.watchlist.models import DiscoveryScope


class _Page:
    pass


def _target(site: str = "unsupported") -> WatchlistTarget:
    return WatchlistTarget(
        key="target",
        work_key="work",
        site=site,
        url="https://example.invalid/work",
        label="Work",
    )


class _PreviewAdapter(DiscoveryAdapter):
    def iter_records(self, page, target, mode):
        del page, target, mode

        async def empty():
            if False:
                yield None

        return empty()

    async def preview_complete_listing(self, page, target):
        del page
        rows = (
            ListingRow("episode-1", target.url, 1, "Episode 1", "free", "fixture"),
        )
        return ListingPreview(
            site=target.site,
            target_key=target.key,
            target_url=target.url,
            listing_identity="fixture",
            rows=rows,
            complete=True,
            observed_at=datetime.now(UTC),
            digest=listing_digest("fixture", rows),
        )


class _MalformedExclusionAdapter(_PreviewAdapter):
    supports_bounded_discovery = True
    supports_exclusion_only_scope = True
    supports_exclusion_replay = True

    async def preview_complete_listing(self, page, target):
        del page
        rows = (
            ListingRow("episode-1", "https://example.invalid/1", 1, "Episode 1", "free", "fixture"),
            ListingRow("episode-2", "https://example.invalid/2", 3, "Episode 2", "free", "fixture"),
        )
        return ListingPreview(
            site=target.site,
            target_key=target.key,
            target_url=target.url,
            listing_identity="fixture",
            rows=rows,
            complete=True,
            observed_at=datetime.now(UTC),
            digest=listing_digest("fixture", rows),
        )


def test_listing_digest_uses_only_identity_ids_and_positions() -> None:
    first = ListingRow("one", "https://first.invalid", 1, "Title A", "free", "fixture")
    second = ListingRow("one", "https://second.invalid", 1, "Title B", "paid", "fixture")
    assert listing_digest("fixture", (first,)) == listing_digest("fixture", (second,))


async def test_unsupported_site_preview_is_explicit_and_read_only(tmp_path) -> None:
    catalog_path = tmp_path / "catalog.sqlite"
    registry = DiscoveryAdapterRegistry()
    service = DiscoveryService(CatalogService(catalog_path), registry)
    preview = await service.preview_complete_listing(_Page(), _target())
    assert preview.ready is False
    assert preview.blockers == ("No Discovery adapter is registered for site 'unsupported'",)
    assert not catalog_path.exists()


async def test_catalog_free_preview_service_does_not_require_catalog(tmp_path) -> None:
    registry = DiscoveryAdapterRegistry()
    registry.register("fixture", _PreviewAdapter)
    preview = await ListingPreviewService(registry).preview_complete_listing(
        _Page(), _target("fixture")
    )
    assert preview.ready is True
    assert not (tmp_path / "catalog.sqlite").exists()


def _listing() -> ListingPreview:
    rows = tuple(
        ListingRow(f"episode-{index}", f"https://example.invalid/{index}", index, f"Episode {index}", "free", "fixture")
        for index in (4, 3, 2, 1)
    )
    return ListingPreview(
        site="fixture",
        target_key="target",
        target_url="https://example.invalid/work",
        listing_identity="fixture",
        rows=rows,
        complete=True,
        observed_at=datetime.now(UTC),
        digest=listing_digest("fixture", rows),
    )


def test_selection_planner_maps_outer_range_and_inner_holes() -> None:
    plan = SelectionPlanner().plan(_listing(), {"episode-4", "episode-2", "episode-1"})
    assert plan.ready is True
    assert plan.discovery_scope is not None
    assert plan.discovery_scope.from_url.endswith("/4")
    assert plan.discovery_scope.through_url.endswith("/1")
    assert plan.discovery_scope.excluded_external_ids == ("episode-3",)


def test_selection_planner_rejects_unknown_or_empty_selection() -> None:
    plan = SelectionPlanner().plan(_listing(), {"missing"})
    assert plan.ready is False
    assert any("absent" in blocker for blocker in plan.blockers)
    assert plan.selected_count == 0


def test_selection_planner_rejects_non_string_checked_ids_without_type_error() -> None:
    plan = SelectionPlanner().plan(_listing(), ["episode-1", [], None])
    assert plan.ready is False
    assert any("non-empty strings" in blocker for blocker in plan.blockers)


def test_selection_planner_fails_closed_on_malformed_listing_rows() -> None:
    listing = ListingPreview(
        site="fixture",
        target_key="target",
        target_url="https://example.invalid/work",
        listing_identity="fixture",
        rows=(object(),),  # type: ignore[arg-type]
        complete=True,
        observed_at=datetime.now(UTC),
        digest="invalid",
    )
    plan = SelectionPlanner().plan(listing, ())
    assert plan.ready is False
    assert any("invalid row" in blocker for blocker in plan.blockers)


def test_selection_planner_rejects_listing_row_identity_mismatch() -> None:
    rows = (
        ListingRow("episode-1", "https://example.invalid/1", 1, "Episode 1", "free", "other"),
    )
    listing = ListingPreview(
        site="fixture",
        target_key="target",
        target_url="https://example.invalid/work",
        listing_identity="fixture",
        rows=rows,
        complete=True,
        observed_at=datetime.now(UTC),
        digest=listing_digest("fixture", rows),
    )
    plan = SelectionPlanner().plan(listing, {"episode-1"})
    assert plan.ready is False
    assert any("identity" in blocker for blocker in plan.blockers)


def test_selection_planner_rejects_shuffled_or_gapped_site_positions() -> None:
    rows = (
        ListingRow("episode-1", "https://example.invalid/1", 3, "Episode 1", "free", "fixture"),
        ListingRow("episode-2", "https://example.invalid/2", 1, "Episode 2", "free", "fixture"),
    )
    listing = ListingPreview(
        site="fixture",
        target_key="target",
        target_url="https://example.invalid/work",
        listing_identity="fixture",
        rows=rows,
        complete=True,
        observed_at=datetime.now(UTC),
        digest=listing_digest("fixture", rows),
    )
    plan = SelectionPlanner().plan(listing, {"episode-1"})
    assert plan.ready is False
    assert any("contiguous" in blocker for blocker in plan.blockers)


def test_scope_edit_preview_joins_catalog_rows_and_binds_snapshot_token() -> None:
    listing = _listing()
    target = _target("fixture")
    source = type(
        "SourceFixture",
        (),
        {
            "id": 42,
            "site": "fixture",
            "external_id": "episode-2",
            "discovery_key": "target",
            "acquisition_enabled": True,
        },
    )()
    foreign = type(
        "SourceFixture",
        (),
        {
            "id": 43,
            "site": "fixture",
            "external_id": "episode-3",
            "discovery_key": "other-key",
            "acquisition_enabled": True,
        },
    )()
    preview = SelectionPlanner().preview_edit(
        listing,
        {"episode-4", "episode-3", "episode-1"},
        current_target=target,
        catalog_sources=(source, foreign),
        watchlist_revision="watch-rev",
        watchlist_content_sha="watch-sha",
        catalog_snapshot_id="catalog-rev",
    )
    assert preview.ready is False
    assert preview.selected_count == 3
    assert preview.excluded_count == 1
    assert preview.new_count == 2
    assert preview.retained_count == 0
    assert preview.removed_count == 1
    assert preview.owner_conflict_count == 1
    assert any("another Watchlist key" in blocker for blocker in preview.blockers)
    assert preview.proposed_target.discovery_scope == DiscoveryScope(
        from_url="https://example.invalid/4",
        through_url="https://example.invalid/1",
        excluded_external_ids=("episode-2",),
    )
    assert preview.token
    assert preview.is_fresh(max_age_seconds=300)
    changed = SelectionPlanner().preview_edit(
        listing,
        {"episode-4", "episode-2", "episode-1"},
        current_target=target,
        catalog_sources=(source, foreign),
        watchlist_revision="watch-rev",
        watchlist_content_sha="watch-sha",
        catalog_snapshot_id="catalog-rev",
    )
    assert changed.token != preview.token


def test_scope_edit_preview_rejects_target_listing_mismatch() -> None:
    target = _target("other-site")
    preview = SelectionPlanner().preview_edit(
        _listing(), {"episode-1"}, current_target=target
    )
    assert preview.ready is False
    assert any("does not match" in blocker for blocker in preview.blockers)


def test_scope_edit_preview_blocks_same_site_sibling_overlap_without_catalog_sources() -> None:
    listing = _listing()
    sibling = replace(
        listing,
        target_key="sibling",
        target_url="https://example.invalid/sibling",
    )
    preview = SelectionPlanner().preview_edit(
        listing,
        {"episode-1", "episode-2"},
        current_target=_target("fixture"),
        sibling_listings={"sibling": sibling},
        sibling_checked_external_ids={"sibling": {"episode-2", "episode-3"}},
        sibling_targets=(
            replace(_target("fixture"), key="sibling", url=sibling.target_url),
        ),
    )
    assert preview.ready is False
    assert any("scopes overlap" in blocker for blocker in preview.blockers)


def test_scope_edit_preview_keeps_legacy_none_archive_order_saveable() -> None:
    listing = _listing()
    target = _target("fixture")
    preview = SelectionPlanner().preview_edit(
        listing,
        {"episode-1", "episode-2"},
        current_target=target,
        catalog_snapshot_id="catalog-rev",
        watchlist_revision="watch-rev",
        watchlist_content_sha="watch-rev",
    )
    assert preview.ready
    assert preview.archive_order_preview is None


def test_archive_preview_uses_cross_site_work_sources_and_ignores_other_work(tmp_path) -> None:
    listing = ListingPreview(
        site="fixture", target_key="target", target_url="https://example.invalid/work",
        listing_identity="fixture", rows=(ListingRow("episode-1", "https://example.invalid/1", 1, "Episode 1", "free", "fixture"),),
        complete=True, observed_at=datetime.now(UTC),
        digest=listing_digest("fixture", (ListingRow("episode-1", "https://example.invalid/1", 1, "Episode 1", "free", "fixture"),)),
    )
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key="work", title="Work"))
    other_work = catalog.create_work(WorkInput(work_key="other", title="Other"))
    item_a = catalog.create_item(ItemInput(order_label="A"), work_id=work.id)
    item_b = catalog.create_item(ItemInput(order_label="B"), work_id=work.id)
    other_item = catalog.create_item(ItemInput(order_label="Other"), work_id=other_work.id)
    source_a = catalog.create_source(SourceInput(site="fixture", external_id="episode-1", discovery_key="target", access_mode="free", display_position=1), item_id=item_a.id)
    source_b = catalog.create_source(SourceInput(site="magapoke", external_id="episode-b", discovery_key="sibling", access_mode="free", display_position=2), item_id=item_b.id)
    unrelated = catalog.create_source(SourceInput(site="fixture", external_id="other-1", discovery_key="other", access_mode="free", display_position=1), item_id=other_item.id)
    target = replace(_target("fixture"), archive_order=1)
    sibling = WatchlistTarget(key="sibling", work_key="work", site="magapoke", url="https://example.invalid/sibling", label="Sibling", archive_order=2)
    preview = SelectionPlanner().preview_edit(
        listing, {"episode-1"}, current_target=target,
        catalog_sources=(source_a, source_b, unrelated),
        archive_work=work, archive_items=(item_a, item_b), archive_targets=(target, sibling),
        archive_facts=ArchiveFactsSnapshot(
            snapshot_id="archive-snapshot", before_positions=((source_a.id, 2), (source_b.id, 1)),
            artifacts=(ArchiveArtifactFact(source_a.id, 1, "Books/002-Work-A.zip", "present", source_a.id),
                       ArchiveArtifactFact(source_b.id, 2, "Books/001-Work-B.zip", "present", source_b.id)),
        ),
    )
    assert preview.ready
    assert preview.archive_order_preview is not None
    assert preview.archive_order_preview["number_changes"]
    assert unrelated.id not in dict(preview.archive_order_preview["positions"])


def test_scope_edit_preview_reports_archive_number_delta_when_bound_snapshot_exists(
    tmp_path,
) -> None:
    listing = ListingPreview(
        site="fixture",
        target_key="target",
        target_url="https://example.invalid/work",
        listing_identity="fixture",
        rows=(
            ListingRow(
                "episode-1", "https://example.invalid/1", 1,
                "Episode 1", "free", "fixture",
            ),
        ),
        complete=True,
        observed_at=datetime.now(UTC),
        digest=listing_digest(
            "fixture",
            (ListingRow("episode-1", "https://example.invalid/1", 1, "Episode 1", "free", "fixture"),),
        ),
    )
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(
        WorkInput(work_key="work", title="Series-With-Hyphen", author="Author-Name")
    )
    item = catalog.create_item(ItemInput(order_label="Vol-1"), work_id=work.id)
    source = catalog.create_source(
        SourceInput(
            site="fixture", external_id="episode-1", discovery_key="target",
            access_mode="free", display_position=1,
        ),
        item_id=item.id,
    )
    target = replace(_target("fixture"), archive_order=1)
    preview = SelectionPlanner().preview_edit(
        listing,
        {"episode-1"},
        current_target=target,
        catalog_sources=(source,),
        archive_work=work,
        archive_items=(item,),
        archive_targets=(target,),
        archive_facts=ArchiveFactsSnapshot(
            snapshot_id="archive-snapshot",
            before_positions=((source.id, 7),),
            artifacts=(
                ArchiveArtifactFact(
                    source_id=source.id,
                    artifact_id=1,
                    locator="Books/007-Episode-1.zip",
                    state="present",
                    run_source_id=source.id,
                ),
            ),
        ),
    )
    assert preview.archive_order_preview is not None
    assert preview.archive_order_preview["unknown"] is False
    assert preview.archive_order_preview["number_changes"] == (
        {"source_id": source.id, "from": 7, "to": 1},
    )
    assert preview.archive_order_preview["artifacts"][0]["expected_stem"] == (
        "001-Series-With-Hyphen-Vol-1-Author-Name"
    )
    assert preview.archive_order_preview["artifacts"][0]["current_stem"] == (
        "007-Episode-1"
    )
    assert preview.archive_order_preview["artifacts"][0]["renumber_required"] is True
    bad_facts = ArchiveFactsSnapshot(
        snapshot_id="archive-snapshot-ambiguous",
        before_positions=((source.id, 7),),
        artifacts=(
            ArchiveArtifactFact(source.id, 1, "Books/007-a.zip", "present", source.id),
            ArchiveArtifactFact(source.id, 2, "Books/007-b.zip", "present", source.id),
        ),
        collision_source_ids=(source.id,),
    )
    blocked = SelectionPlanner().preview_edit(
        listing,
        {"episode-1"},
        current_target=target,
        catalog_sources=(source,),
        archive_work=work,
        archive_items=(item,),
        archive_targets=(target,),
        archive_facts=bad_facts,
    )
    assert blocked.ready is False
    assert blocked.archive_order_preview is not None
    assert blocked.archive_order_preview["unknown"] is True
    assert any("ambiguous" in blocker for blocker in blocked.blockers)


async def test_optional_preview_capability_is_called_without_catalog_access(tmp_path) -> None:
    catalog_path = tmp_path / "catalog.sqlite"
    registry = DiscoveryAdapterRegistry()
    registry.register("fixture", _PreviewAdapter)
    service = DiscoveryService(CatalogService(catalog_path), registry)
    preview = await service.preview_complete_listing(_Page(), _target("fixture"))
    assert preview.ready is True
    assert [row.external_id for row in preview.rows] == ["episode-1"]
    assert not catalog_path.exists()


async def test_exclusion_preflight_rejects_noncanonical_listing_before_catalog_write(tmp_path) -> None:
    catalog_path = tmp_path / "catalog.sqlite"
    registry = DiscoveryAdapterRegistry()
    registry.register("fixture", _MalformedExclusionAdapter)
    target = replace(
        _target("fixture"),
        discovery_scope=DiscoveryScope(excluded_external_ids=("episode-1",)),
    )
    result = await DiscoveryService(CatalogService(catalog_path), registry).discover(
        _Page(), target, "full"
    )
    assert result.complete is False
    assert "complete listing proof is invalid" in (result.error or "")
    assert not catalog_path.exists()
