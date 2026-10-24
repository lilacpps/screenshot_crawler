from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from screenshot_crawler.catalog import (
    ArtifactInput,
    CatalogService,
    CatalogValidationError,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)
from screenshot_crawler.catalog.models import DiscoveryInventoryPosition
from screenshot_crawler.cli import main as cli_main
from screenshot_crawler.watchlist.fingerprints import target_scope_fingerprint
from screenshot_crawler.watchlist.models import DiscoveryScope, WatchlistTarget
from screenshot_crawler.watchlist.reconcile import ScopeReconciler
from screenshot_crawler.watchlist.service import WatchlistService


def _target_mapping(target: WatchlistTarget) -> dict[str, object]:
    value: dict[str, object] = {
        "key": target.key,
        "work_key": target.work_key,
        "site": target.site,
        "url": target.url,
        "label": target.label,
        "enabled": target.enabled,
    }
    if target.archive_order is not None:
        value["archive_order"] = target.archive_order
    if target.discovery_scope is not None:
        value["discovery_scope"] = {
            key: item
            for key, item in (
                ("from_url", target.discovery_scope.from_url),
                ("through_url", target.discovery_scope.through_url),
            )
            if item is not None
        }
    return value


def _write_targets(path: Path, targets: tuple[WatchlistTarget, ...]) -> None:
    path.write_text(
        yaml.safe_dump({"targets": [_target_mapping(target) for target in targets]}, sort_keys=False),
        encoding="utf-8",
    )


def _write_target(path: Path, target: WatchlistTarget) -> None:
    _write_targets(path, (target,))


def _catalog_with_sources(path: Path, external_ids: tuple[str, ...]):
    catalog = CatalogService(path)
    work = catalog.create_work(WorkInput(work_key="series", title="Series"))
    sources = []
    for external_id in external_ids:
        item = catalog.create_item(
            ItemInput(item_title=external_id, status="completed"), work_id=work.id
        )
        sources.append(
            catalog.create_source(
                SourceInput(site="zeblack", external_id=external_id, discovery_key="chapters"),
                item_id=item.id,
            )
        )
    return catalog, work, tuple(sources)


def _record_full_proof(catalog: CatalogService, target: WatchlistTarget, memberships: tuple[bool, ...]):
    sources = catalog.list_sources(site=target.site, discovery_key=target.key)
    catalog.record_discovery_inventory_evidence(
        work_key=target.work_key,
        discovery_key=target.key,
        site=target.site,
        target_url=target.url,
        scope_fingerprint=target_scope_fingerprint(target),
        listing_identity="validated-listing-identity",
        positions=[
            DiscoveryInventoryPosition(
                external_id=source.external_id,
                display_position=index,
                in_scope=memberships[index - 1],
            )
            for index, source in enumerate(sources, start=1)
        ],
    )


def test_preview_is_read_only_and_missing_catalog_does_not_create_parent(tmp_path: Path) -> None:
    watchlist_path = tmp_path / "watchlist.yaml"
    catalog_path = tmp_path / "missing" / "catalog.sqlite"
    target = WatchlistTarget("chapters", "series", "zeblack", "https://example.test/list",
                             "Series")
    _write_target(watchlist_path, target)

    preview = ScopeReconciler(
        WatchlistService(watchlist_path), CatalogService(catalog_path)
    ).preview("series")

    assert not preview.ready
    assert "Catalog read failed" in preview.blockers[0]
    assert not catalog_path.parent.exists()


def test_full_proof_drives_scope_flags_and_stale_marker_keeps_binding(tmp_path: Path) -> None:
    watchlist_path = tmp_path / "watchlist.yaml"
    target = WatchlistTarget(
        key="chapters",
        work_key="series",
        site="zeblack",
        url="https://example.test/list",
        label="Series",
        discovery_scope=DiscoveryScope(through_url="https://example.test/ch/2"),
        archive_order=1,
    )
    _write_target(watchlist_path, target)
    catalog, work, sources = _catalog_with_sources(
        tmp_path / "catalog.sqlite", ("ch-1", "ch-2", "ch-3")
    )
    _record_full_proof(catalog, target, (True, True, False))

    reconciler = ScopeReconciler(WatchlistService(watchlist_path), catalog)
    preview = reconciler.preview(work.work_key)
    assert preview.ready
    assert dict(preview.source_flags) == {
        sources[0].id: True,
        sources[1].id: True,
        sources[2].id: False,
    }
    assert [change.source_id for change in preview.changes] == [sources[2].id]

    reconciler.apply(preview)
    assert [catalog.get_source(source.id).acquisition_enabled for source in sources] == [
        True,
        True,
        False,
    ]
    sync = catalog.get_acquisition_scope_sync(work.work_key)
    assert sync is not None and sync.status == "synced"
    saved = json.loads(sync.configuration_json)
    assert saved[0]["url"] == target.url

    catalog.invalidate_discovery_inventory_evidence(target.key)
    stale = catalog.get_acquisition_scope_sync(work.work_key)
    assert stale is not None and stale.status == "synced"
    assert json.loads(stale.configuration_json) == saved


def test_missing_source_from_replacement_inventory_retains_position_but_blocks_sync(
    tmp_path: Path,
) -> None:
    watchlist_path = tmp_path / "watchlist.yaml"
    target = WatchlistTarget(
        key="chapters",
        work_key="series",
        site="zeblack",
        url="https://example.test/list",
        label="Series",
        discovery_scope=DiscoveryScope(through_url="https://example.test/ch/1"),
        archive_order=1,
    )
    _write_target(watchlist_path, target)
    catalog, work, sources = _catalog_with_sources(
        tmp_path / "catalog.sqlite", ("ch-1", "ch-2")
    )
    catalog.update_source_external_state(
        "zeblack", "ch-1", display_position=1
    )
    catalog.update_source_external_state(
        "zeblack", "ch-2", display_position=2
    )
    prior_updated_at = catalog.get_source(sources[1].id).updated_at
    catalog.record_discovery_inventory_evidence(
        work_key=work.work_key,
        discovery_key=target.key,
        site=target.site,
        target_url=target.url,
        scope_fingerprint=target_scope_fingerprint(target),
        listing_identity="listing-with-one-row",
        positions=[DiscoveryInventoryPosition("ch-1", 1, in_scope=True)],
    )

    preview = ScopeReconciler(WatchlistService(watchlist_path), catalog).preview(
        work.work_key
    )

    assert not preview.ready
    assert any("ch-2" in blocker and "missing from Full listing" in blocker
               for blocker in preview.blockers)
    retained = catalog.get_source(sources[1].id)
    assert retained.display_position == 2
    assert retained.updated_at == prior_updated_at


def test_archive_order_preview_compares_previous_binding_after_reordering_keys(
    tmp_path: Path,
) -> None:
    watchlist_path = tmp_path / "watchlist.yaml"
    first = WatchlistTarget(
        "first", "series", "zeblack", "https://example.test/first", "First",
        archive_order=10,
    )
    second = WatchlistTarget(
        "second", "series", "bookwalker", "https://example.test/second", "Second",
        archive_order=20,
    )
    _write_targets(watchlist_path, (first, second))
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key="series", title="Series"))
    for target in (first, second):
        item = catalog.create_item(ItemInput(order_label="Volume 1"), work_id=work.id)
        catalog.create_source(
            SourceInput(
                site=target.site,
                external_id=f"{target.key}-one",
                discovery_key=target.key,
                display_position=1,
            ),
            item_id=item.id,
        )
        _record_full_proof(catalog, target, (True,))
    watchlist = WatchlistService(watchlist_path)
    reconciler = ScopeReconciler(watchlist, catalog)
    initial = reconciler.preview(work.work_key)
    assert initial.ready
    assert initial.archive_order_preview is not None
    assert initial.archive_order_preview["previous_positions_status"] == "known"
    assert initial.archive_order_preview["number_changes"]
    reconciler.apply(initial)

    reordered = (replace(first, archive_order=20), replace(second, archive_order=10))
    _write_targets(watchlist_path, reordered)
    preview = reconciler.preview(work.work_key)
    assert preview.ready
    assert preview.archive_order_preview is not None
    assert preview.archive_order_preview["previous_positions_status"] == "known"
    changes = {
        row["source_id"]: (row["from"], row["to"], row["before_known"])
        for row in preview.archive_order_preview["number_changes"]
    }
    sources = catalog.list_sources()
    assert changes == {
        sources[0].id: (1, 2, True),
        sources[1].id: (2, 1, True),
    }


def test_mixed_scoped_and_unbounded_keys_classifies_every_source(tmp_path: Path) -> None:
    watchlist_path = tmp_path / "watchlist.yaml"
    scoped = WatchlistTarget(
        "scoped", "series", "zeblack", "https://example.test/scoped", "Scoped",
        discovery_scope=DiscoveryScope(through_url="https://example.test/ch/1"),
    )
    unbounded = WatchlistTarget(
        "books", "series", "bookwalker", "https://example.test/books", "Books"
    )
    _write_targets(watchlist_path, (scoped, unbounded))
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key="series", title="Series"))
    scoped_item = catalog.create_item(work_id=work.id)
    scoped_source = catalog.create_source(
        SourceInput(site="zeblack", external_id="chapter-1", discovery_key="scoped"),
        item_id=scoped_item.id,
    )
    book_item = catalog.create_item(work_id=work.id)
    book_source = catalog.create_source(
        SourceInput(site="bookwalker", external_id="volume-1", discovery_key="books"),
        item_id=book_item.id,
    )
    catalog.record_discovery_inventory_evidence(
        work_key="series",
        discovery_key="scoped",
        site="zeblack",
        target_url=scoped.url,
        scope_fingerprint=target_scope_fingerprint(scoped),
        listing_identity="zeblack-listing",
        positions=[DiscoveryInventoryPosition("chapter-1", 1, in_scope=True)],
    )

    preview = ScopeReconciler(WatchlistService(watchlist_path), catalog).preview("series")

    assert preview.ready
    assert dict(preview.source_flags) == {scoped_source.id: True, book_source.id: True}


def test_scope_shrink_and_reexpand_preserve_catalog_graph_and_history(tmp_path: Path) -> None:
    watchlist_path = tmp_path / "watchlist.yaml"
    base_url = "https://example.test/ch/"
    full = WatchlistTarget(
        "chapters", "series", "zeblack", "https://example.test/list", "Series",
        discovery_scope=DiscoveryScope(
            from_url=f"{base_url}1", through_url=f"{base_url}140"
        ),
    )
    _write_target(watchlist_path, full)
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key="series", title="Series"))
    sources = []
    items = []
    for index in range(1, 141):
        external_id = f"ch-{index}"
        item = catalog.create_item(ItemInput(status="completed"), work_id=work.id)
        source = catalog.create_source(
            SourceInput(site="zeblack", external_id=external_id, discovery_key="chapters"),
            item_id=item.id,
        )
        items.append(item)
        sources.append(source)
    web_target = catalog.create_source_target(
        SourceTargetInput(backend="web", locator=f"{base_url}140"),
        source_id=sources[-1].id,
    )
    run = catalog.create_crawl_run(
        item_id=items[-1].id,
        source_id=sources[-1].id,
        target_id=web_target.id,
        access_strategy="direct",
    )
    _, artifact, _ = catalog.finalize_successful_crawl(
        run.id,
        artifact=ArtifactInput(
            kind="archive",
            format="zip",
            sha256="a" * 64,
            byte_size=8,
            storage_backend="local",
            locator="Books/ch-140.zip",
        ),
        page_count=1,
        stop_reason="end",
    )
    reconciler = ScopeReconciler(WatchlistService(watchlist_path), catalog)
    memberships = (True,) * 140
    _record_full_proof(catalog, full, memberships)
    reconciler.apply(reconciler.preview(work.work_key))

    shrunk = WatchlistTarget(
        "chapters", "series", "zeblack", "https://example.test/list", "Series",
        discovery_scope=DiscoveryScope(
            from_url=f"{base_url}1", through_url=f"{base_url}100"
        ),
    )
    _write_target(watchlist_path, shrunk)
    _record_full_proof(catalog, shrunk, (True,) * 100 + (False,) * 40)
    reconciler.apply(reconciler.preview(work.work_key))
    assert [catalog.get_source(source.id).acquisition_enabled for source in sources] == (
        [True] * 100 + [False] * 40
    )

    _write_target(watchlist_path, full)
    _record_full_proof(catalog, full, memberships)
    reconciler.apply(reconciler.preview(work.work_key))

    assert [catalog.get_source(source.id).acquisition_enabled for source in sources] == (
        [True] * 140
    )
    assert [item.id for item in catalog.list_items(work_id=work.id)] == [
        item.id for item in items
    ]
    assert [catalog.get_item(item.id).status for item in items] == ["completed"] * 140
    assert catalog.list_crawl_runs(item_id=items[-1].id)[0].id == run.id
    assert catalog.get_artifact(artifact.id).locator == "Books/ch-140.zip"


def test_scope_preview_leaves_existing_catalog_bytes_and_mtime_unchanged(tmp_path: Path) -> None:
    watchlist_path = tmp_path / "watchlist.yaml"
    target = WatchlistTarget(
        "chapters", "series", "zeblack", "https://example.test/list", "Series"
    )
    _write_target(watchlist_path, target)
    catalog, work, _sources = _catalog_with_sources(tmp_path / "catalog.sqlite", ("ch-1",))
    catalog_path = catalog.path
    before_bytes = catalog_path.read_bytes()
    before_mtime = catalog_path.stat().st_mtime_ns
    before_files = sorted(path.name for path in tmp_path.iterdir())

    preview = ScopeReconciler(WatchlistService(watchlist_path), catalog).preview(work.work_key)

    assert preview.ready
    assert catalog_path.read_bytes() == before_bytes
    assert catalog_path.stat().st_mtime_ns == before_mtime
    assert sorted(path.name for path in tmp_path.iterdir()) == before_files


def test_scope_sync_cli_json_apply_is_one_machine_readable_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    watchlist_path = tmp_path / "watchlist.yaml"
    target = WatchlistTarget("chapters", "series", "zeblack", "https://example.test/list",
                             "Series")
    _write_target(watchlist_path, target)
    catalog, _work, _sources = _catalog_with_sources(tmp_path / "catalog.sqlite", ("ch-1",))
    monkeypatch.setattr(
        "sys.argv",
        [
            "screenshot-crawler",
            "watch",
            "scope-sync",
            "--watchlist",
            str(watchlist_path),
            "--catalog",
            str(catalog.path),
            "--work-key",
            "series",
            "--apply",
            "--json",
        ],
    )

    cli_main()

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["applied"] is True
    assert payload["ready"] is True
    assert payload["selected_count"] == 1


def test_scope_sync_cli_blocked_json_returns_nonzero(tmp_path: Path, monkeypatch, capsys) -> None:
    watchlist_path = tmp_path / "watchlist.yaml"
    target = WatchlistTarget(
        "chapters", "series", "zeblack", "https://example.test/list", "Series",
        discovery_scope=DiscoveryScope(through_url="https://example.test/ch-1"),
    )
    _write_target(watchlist_path, target)
    catalog, _work, _sources = _catalog_with_sources(tmp_path / "catalog.sqlite", ("ch-1",))
    monkeypatch.setattr(
        "sys.argv",
        [
            "screenshot-crawler",
            "watch",
            "scope-sync",
            "--watchlist",
            str(watchlist_path),
            "--catalog",
            str(catalog.path),
            "--work-key",
            "series",
            "--dry-run",
            "--json",
        ],
    )

    with pytest.raises(SystemExit) as raised:
        cli_main()

    assert raised.value.code == 2
    output = capsys.readouterr()
    payload = json.loads(output.out)
    assert payload["ready"] is False
    assert payload["unresolved_count"] > 0
    assert "Scope sync error" in output.err


def test_url_change_cannot_rebootstrap_without_matching_full_proof(tmp_path: Path) -> None:
    watchlist_path = tmp_path / "watchlist.yaml"
    target = WatchlistTarget("chapters", "series", "zeblack", "https://example.test/list",
                             "Series")
    _write_target(watchlist_path, target)
    catalog, work, _sources = _catalog_with_sources(tmp_path / "catalog.sqlite", ("ch-1",))
    reconciler = ScopeReconciler(WatchlistService(watchlist_path), catalog)
    assert reconciler.preview(work.work_key).ready
    reconciler.apply(reconciler.preview(work.work_key))

    changed = WatchlistTarget(
        "chapters", "series", "zeblack", "https://example.test/another-list", "Series"
    )
    _write_target(watchlist_path, changed)
    blocked = reconciler.preview(work.work_key)
    assert not blocked.ready
    assert any("fresh complete Full listing proof" in value for value in blocked.blockers)

    _record_full_proof(catalog, changed, (True,))
    refreshed = reconciler.preview(work.work_key)
    assert refreshed.ready
    reconciler.apply(refreshed)


def test_watchlist_edit_after_preview_requires_a_new_preview(tmp_path: Path) -> None:
    watchlist_path = tmp_path / "watchlist.yaml"
    target = WatchlistTarget("chapters", "series", "zeblack", "https://example.test/list",
                             "Series")
    _write_target(watchlist_path, target)
    catalog, work, _sources = _catalog_with_sources(tmp_path / "catalog.sqlite", ("ch-1",))
    reconciler = ScopeReconciler(WatchlistService(watchlist_path), catalog)
    preview = reconciler.preview(work.work_key)
    assert preview.ready
    changed = WatchlistTarget(
        "chapters", "series", "zeblack", "https://example.test/edited", "Series"
    )
    _write_target(watchlist_path, changed)

    try:
        reconciler.apply(preview)
    except RuntimeError as exc:
        assert "changed after preview" in str(exc)
    else:
        raise AssertionError("Watchlist edits after preview must be rejected")


@pytest.mark.parametrize("remove_all", [False, True])
def test_removed_discovery_key_is_disabled_and_readded_key_is_enabled(tmp_path: Path, remove_all: bool) -> None:
    watchlist_path = tmp_path / "watchlist.yaml"
    zeblack = WatchlistTarget("chapters", "series", "zeblack", "https://example.test/list",
                              "Series")
    bookwalker = WatchlistTarget("volumes", "series", "bookwalker", "https://example.test/books",
                                 "Series")
    _write_targets(watchlist_path, (zeblack, bookwalker))
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key="series", title="Series"))
    sources = []
    for site, key, external_id in (
        ("zeblack", "chapters", "chapter-1"),
        ("bookwalker", "volumes", "volume-1"),
    ):
        item = catalog.create_item(work_id=work.id)
        sources.append(
            catalog.create_source(
                SourceInput(site=site, external_id=external_id, discovery_key=key),
                item_id=item.id,
            )
        )
    reconciler = ScopeReconciler(WatchlistService(watchlist_path), catalog)
    reconciler.apply(reconciler.preview(work.work_key))

    _write_targets(watchlist_path, () if remove_all else (zeblack,))
    removed = reconciler.preview(work.work_key)
    assert removed.ready and dict(removed.source_flags)[sources[1].id] is False
    reconciler.apply(removed)
    assert catalog.get_source(sources[1].id).acquisition_enabled is False
    assert catalog.get_source(sources[0].id).acquisition_enabled is (not remove_all)

    _write_targets(watchlist_path, (zeblack, bookwalker))
    restored = reconciler.preview(work.work_key)
    assert restored.ready and dict(restored.source_flags)[sources[1].id] is True
    reconciler.apply(restored)
    assert catalog.get_source(sources[1].id).acquisition_enabled is True

    _write_target(watchlist_path, zeblack)
    reconciler.apply(reconciler.preview(work.work_key))
    changed_bookwalker = WatchlistTarget(
        "volumes", "series", "bookwalker", "https://example.test/changed-books", "Series"
    )
    _write_targets(watchlist_path, (zeblack, changed_bookwalker))
    changed_binding = reconciler.preview(work.work_key)
    assert not changed_binding.ready
    assert any("fresh complete Full listing proof" in item for item in changed_binding.blockers)


def test_apply_revision_cas_rejects_catalog_change_without_partial_flags(tmp_path: Path) -> None:
    watchlist_path = tmp_path / "watchlist.yaml"
    target = WatchlistTarget("chapters", "series", "zeblack", "https://example.test/list",
                             "Series")
    _write_target(watchlist_path, target)
    catalog, work, sources = _catalog_with_sources(tmp_path / "catalog.sqlite", ("ch-1",))
    preview = ScopeReconciler(WatchlistService(watchlist_path), catalog).preview(work.work_key)
    assert preview.ready

    with pytest.raises(CatalogValidationError, match="changed after preview"):
        catalog.apply_acquisition_scope_sync(
            work_key=work.work_key,
            fingerprint=preview.fingerprint,
            definition_fingerprint=preview.definition_fingerprint,
            configuration_json=preview.configuration_json,
            expected_revision_token="0" * 64,
            discovery_keys=preview.discovery_keys,
            source_flags={sources[0].id: False},
        )

    assert catalog.get_source(sources[0].id).acquisition_enabled is True
    assert catalog.get_acquisition_scope_sync(work.work_key) is None


def test_preview_rejects_inventory_digest_mismatch(tmp_path: Path) -> None:
    watchlist_path = tmp_path / "watchlist.yaml"
    target = WatchlistTarget(
        "chapters", "series", "zeblack", "https://example.test/list", "Series",
        discovery_scope=DiscoveryScope(through_url="https://example.test/ch/1"),
    )
    _write_target(watchlist_path, target)
    catalog, _work, _sources = _catalog_with_sources(
        tmp_path / "catalog.sqlite", ("ch-1",)
    )
    _record_full_proof(catalog, target, (True,))
    with sqlite3.connect(catalog.path) as connection:
        connection.execute(
            "UPDATE discovery_inventory_positions SET in_scope = 0 WHERE discovery_key = ?",
            (target.key,),
        )

    preview = ScopeReconciler(WatchlistService(watchlist_path), catalog).preview("series")

    assert not preview.ready
    assert any("proof digest is invalid" in blocker for blocker in preview.blockers)


def test_preview_rejects_stale_apply_and_unknown_orphan_source(tmp_path: Path) -> None:
    watchlist_path = tmp_path / "watchlist.yaml"
    target = WatchlistTarget("chapters", "series", "zeblack", "https://example.test/list",
                             "Series")
    _write_target(watchlist_path, target)
    catalog, work, sources = _catalog_with_sources(tmp_path / "catalog.sqlite", ("ch-1",))
    reconciler = ScopeReconciler(WatchlistService(watchlist_path), catalog)
    preview = reconciler.preview(work.work_key)
    assert preview.ready
    catalog.set_source_display_positions(
        site="zeblack", discovery_key="chapters", assignments={sources[0].id: 9}
    )
    try:
        reconciler.apply(preview)
    except RuntimeError as exc:
        assert "changed after preview" in str(exc)
    else:
        raise AssertionError("stale preview must not apply")

    other = catalog.create_item(work_id=work.id)
    orphan = catalog.create_source(
        SourceInput(site="zeblack", external_id="orphan", discovery_key="unknown-key"),
        item_id=other.id,
    )
    blocked = reconciler.preview(work.work_key)
    assert not blocked.ready
    assert any(str(orphan.id) in value and "unknown" in value for value in blocked.blockers)


def test_opt_in_watchlist_enabled_flag_does_not_change_acquisition_definition(tmp_path: Path) -> None:
    watchlist_path = tmp_path / "watchlist.yaml"
    target = WatchlistTarget("chapters", "series", "zeblack", "https://example.test/list",
                             "Series", enabled=False)
    _write_target(watchlist_path, target)
    catalog, work, _sources = _catalog_with_sources(tmp_path / "catalog.sqlite", ("ch-1",))
    reconciler = ScopeReconciler(WatchlistService(watchlist_path), catalog)

    preview = reconciler.preview(work.work_key)

    assert preview.ready
    assert preview.legacy_bootstrap
    assert dict(preview.source_flags) == {_sources[0].id: True}
    enabled_target = WatchlistTarget(
        "chapters", "series", "zeblack", "https://example.test/list", "Series", enabled=True
    )
    _write_target(watchlist_path, enabled_target)
    enabled_preview = reconciler.preview(work.work_key)
    assert enabled_preview.fingerprint == preview.fingerprint
