import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
import yaml

from screenshot_crawler.batch import catalog_archive_stem
from screenshot_crawler.catalog import (
    ArtifactInput,
    CatalogService,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)
from screenshot_crawler.catalog.models import DiscoveryInventoryPosition
from screenshot_crawler.core.progress import atomic_write_json
from screenshot_crawler.maintenance.archive_renumber import (
    ArchiveRenumberUsageError,
    apply_archive_renumber_plan,
    build_archive_renumber_plan,
)
from screenshot_crawler.watchlist.fingerprints import target_scope_fingerprint
from screenshot_crawler.watchlist.models import DiscoveryScope, WatchlistTarget
from screenshot_crawler.watchlist.reconcile import ScopeReconciler
from screenshot_crawler.watchlist.service import WatchlistService
from scripts.renumber_archives import main as renumber_cli_main

SHA = "A" * 64


def _make_source(
    catalog: CatalogService,
    root: Path,
    *,
    work_key: str = "work",
    title: str = "作品名",
    author: str | None = None,
    genre: str = "漫画",
    order_label: str = "番外編",
    external_id: str = "episode-1",
    site: str = "mangaone",
    display_position: int | None = 3,
):
    work = catalog.create_work(
        WorkInput(work_key=work_key, title=title, author=author, genre=genre)
    )
    item = catalog.create_item(
        ItemInput(item_title=order_label, order_label=order_label), work_id=work.id
    )
    source = catalog.create_source(
        SourceInput(
            site=site,
            external_id=external_id,
            display_position=display_position,
            access_mode="free",
        ),
        item_id=item.id,
    )
    target = catalog.create_source_target(
        SourceTargetInput(backend="web", locator=f"https://example.invalid/{external_id}"),
        source_id=source.id,
    )
    return work, item, source, target


def _add_archive(
    catalog: CatalogService,
    item_id: int,
    source_id: int,
    target_id: int,
    path: Path,
    *,
    succeeded: bool = True,
    start: str = "2026-09-01T00:00:00+09:00",
):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"zip bytes")
    run = catalog.create_crawl_run(
        item_id=item_id,
        source_id=source_id,
        target_id=target_id,
        access_strategy="direct",
        started_at=start,
    )
    if succeeded:
        catalog.mark_crawl_run_succeeded(run.id, page_count=1)
    else:
        catalog.mark_crawl_run_failed(run.id, error_type="test")
    artifact = catalog.create_artifact(
        ArtifactInput(
            kind="archive",
            format="zip",
            sha256=SHA,
            byte_size=9,
            storage_backend="filesystem",
            locator=path.as_posix(),
            state="present",
        ),
        item_id=item_id,
        crawl_run_id=run.id,
    )
    return run, artifact


def test_shared_catalog_stem_matches_position_and_author_rule(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work, item, source, _ = _make_source(
        catalog,
        Path("."),
        author="作者",
        display_position=3,
    )
    assert catalog_archive_stem(work, item, source) == "003-作品名-番外編-作者"


def test_current_selection_uses_newest_successful_run_with_archive(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    _, item, source, target = _make_source(catalog, tmp_path)
    old = tmp_path / "old.zip"
    current = tmp_path / "current.zip"
    _run1, artifact1 = _add_archive(catalog, item.id, source.id, target.id, old)
    run2, artifact2 = _add_archive(catalog, item.id, source.id, target.id, current)

    plan = build_archive_renumber_plan(catalog, site="mangaone", status_dir=tmp_path / "status")

    entry = plan.entries[0]
    assert entry.artifact is not None and entry.artifact.id == artifact2.id
    assert entry.run is not None and entry.run.id == run2.id
    assert entry.artifact.id != artifact1.id


def test_current_selection_ignores_failed_newer_run(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    _, item, source, target = _make_source(catalog, tmp_path)
    existing = tmp_path / "existing.zip"
    _, artifact = _add_archive(catalog, item.id, source.id, target.id, existing)
    failed_run = catalog.create_crawl_run(
        item_id=item.id, source_id=source.id, target_id=target.id,
        access_strategy="direct", started_at="2026-09-02T00:00:00+09:00",
    )
    catalog.mark_crawl_run_failed(failed_run.id, error_type="test")

    plan = build_archive_renumber_plan(catalog, site="mangaone", status_dir=tmp_path / "status")
    assert plan.entries[0].artifact is not None
    assert plan.entries[0].artifact.id == artifact.id


def test_current_selection_skips_successful_run_without_archive(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    _, item, source, target = _make_source(catalog, tmp_path)
    existing = tmp_path / "existing.zip"
    _, artifact = _add_archive(catalog, item.id, source.id, target.id, existing)
    empty_run = catalog.create_crawl_run(
        item_id=item.id, source_id=source.id, target_id=target.id,
        access_strategy="direct", started_at="2026-09-02T00:00:00+09:00",
    )
    catalog.mark_crawl_run_succeeded(empty_run.id, page_count=0)

    plan = build_archive_renumber_plan(catalog, site="mangaone", status_dir=tmp_path / "status")
    assert plan.entries[0].artifact is not None
    assert plan.entries[0].artifact.id == artifact.id


def test_missing_newer_current_artifact_does_not_fallback(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    _, item, source, target = _make_source(catalog, tmp_path)
    old = tmp_path / "old.zip"
    _add_archive(catalog, item.id, source.id, target.id, old)
    missing = tmp_path / "missing.zip"
    _, current = _add_archive(catalog, item.id, source.id, target.id, missing)
    missing.unlink()

    plan = build_archive_renumber_plan(catalog, site="mangaone", status_dir=tmp_path / "status")
    assert plan.entries[0].status == "MISSING"
    assert plan.entries[0].artifact is not None and plan.entries[0].artifact.id == current.id


def test_multiple_archive_artifacts_in_current_run_is_ambiguous(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    _, item, source, target = _make_source(catalog, tmp_path)
    first = tmp_path / "one.zip"
    run, _ = _add_archive(catalog, item.id, source.id, target.id, first)
    second = tmp_path / "two.zip"
    second.write_bytes(b"other")
    catalog.create_artifact(
        ArtifactInput(
            kind="archive", format="zip", sha256=SHA, byte_size=5,
            storage_backend="filesystem", locator=second.as_posix(), state="present",
        ),
        item_id=item.id,
        crawl_run_id=run.id,
    )

    plan = build_archive_renumber_plan(catalog, site="mangaone", status_dir=tmp_path / "status")
    assert plan.entries[0].status == "AMBIGUOUS"


def test_locator_is_the_only_old_path_authority_and_matching_status_is_updated(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work, item, source, target = _make_source(catalog, tmp_path, author="作者")
    old = tmp_path / "totally-legacy-weird-name.zip"
    _, artifact = _add_archive(catalog, item.id, source.id, target.id, old)
    # Keep the matching status next to the ZIP to exercise the short-temp
    # namespace collision case.
    status_dir = old.parent
    status_path = status_dir / f"{old.stem}.json"
    original_status = {
        "status": "completed",
        "archive_path": old.as_posix(),
        "page_count": 4,
        "source_output_dir": "crawl",
        "source_removed": True,
        "future": {"keep": True},
    }
    atomic_write_json(status_path, original_status)

    plan = build_archive_renumber_plan(catalog, site="mangaone", status_dir=status_dir)
    entry = plan.entries[0]
    assert entry.new_path == old.parent / "003-作品名-番外編-作者.zip"
    assert entry.temporary_path == old.parent / f".archive-renumber-{artifact.id}.tmp"
    assert entry.status_temporary_path == old.parent / f".status-renumber-{artifact.id}.tmp"
    assert entry.temporary_path != entry.status_temporary_path
    result = apply_archive_renumber_plan(plan)

    assert result.error is None
    assert entry.new_path.is_file()
    assert not old.exists()
    assert not status_path.exists()
    moved_status = entry.new_status_path
    assert moved_status is not None and moved_status.is_file()
    status = json.loads(moved_status.read_text(encoding="utf-8"))
    assert status["archive_path"] == entry.new_path.as_posix()
    assert status["future"] == {"keep": True}
    assert not list(old.parent.glob(".*-*.tmp"))
    updated = catalog.get_artifact(artifact.id)
    assert updated.locator == entry.new_path.as_posix()
    assert updated.sha256 == SHA.lower()
    assert updated.byte_size == 9
    assert catalog.get_item(item.id).status == "pending"
    assert work.title == "作品名"


def test_reapplies_p4_to_archive_with_position_inside_legacy_stem(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    _work, item, source, target = _make_source(
        catalog,
        tmp_path,
        title="獣王と薬草",
        order_label="第01話",
        display_position=1,
    )
    old = tmp_path / "獣王と薬草-001-第01話.zip"
    _, artifact = _add_archive(catalog, item.id, source.id, target.id, old)
    status_dir = tmp_path / "crawl-status"
    status_path = status_dir / f"{old.stem}.json"
    atomic_write_json(
        status_path,
        {"status": "completed", "archive_path": old.as_posix(), "keep": True},
    )

    plan = build_archive_renumber_plan(catalog, site="mangaone", status_dir=status_dir)
    entry = plan.entries[0]
    assert entry.status == "RENAME"
    assert entry.new_path == tmp_path / "001-獣王と薬草-第01話.zip"

    result = apply_archive_renumber_plan(plan)

    assert result.error is None
    assert not old.exists()
    assert entry.new_path.is_file()
    assert not status_path.exists()
    assert entry.new_status_path is not None and entry.new_status_path.is_file()
    status = json.loads(entry.new_status_path.read_text(encoding="utf-8"))
    assert status == {
        "status": "completed",
        "archive_path": entry.new_path.as_posix(),
        "keep": True,
    }
    assert catalog.get_artifact(artifact.id).locator == entry.new_path.as_posix()


def test_renumber_follows_work_scoped_status_namespace(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work, item, source, target = _make_source(
        catalog,
        tmp_path,
        title="Work Scoped",
        genre="manga",
        order_label="Episode",
        display_position=1,
    )
    old = tmp_path / "legacy.zip"
    _, artifact = _add_archive(catalog, item.id, source.id, target.id, old)
    status_dir = tmp_path / "crawl-status"
    status_path = status_dir / "manga" / "Work Scoped" / "legacy.json"
    atomic_write_json(
        status_path,
        {"status": "completed", "archive_path": old.as_posix(), "keep": True},
    )

    plan = build_archive_renumber_plan(catalog, site="mangaone", status_dir=status_dir)
    entry = plan.entries[0]
    assert entry.status == "RENAME"
    assert entry.new_status_path == (
        status_dir / "manga" / "Work Scoped" / "001-Work Scoped-Episode.json"
    )

    result = apply_archive_renumber_plan(plan)

    assert result.error is None
    assert entry.new_path == tmp_path / "001-Work Scoped-Episode.zip"
    assert entry.new_status_path.is_file()
    assert not status_path.exists()
    assert catalog.get_artifact(artifact.id).locator == entry.new_path.as_posix()
    assert work.title == "Work Scoped"


def test_dry_run_does_not_change_zip_status_catalog_or_mtime(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    _, item, source, target = _make_source(catalog, tmp_path)
    old = tmp_path / "legacy.zip"
    _, artifact = _add_archive(catalog, item.id, source.id, target.id, old)
    status_dir = tmp_path / "status"
    status_path = status_dir / "legacy.json"
    atomic_write_json(status_path, {"archive_path": old.as_posix(), "keep": 1})
    before_zip = old.read_bytes()
    before_zip_mtime = old.stat().st_mtime_ns
    before_status = status_path.read_bytes()
    before_catalog = catalog.get_artifact(artifact.id)
    before_catalog_mtime = (tmp_path / "catalog.sqlite").stat().st_mtime_ns

    plan = build_archive_renumber_plan(catalog, site="mangaone", status_dir=status_dir)

    assert plan.entries[0].status == "RENAME"
    assert old.read_bytes() == before_zip
    assert old.stat().st_mtime_ns == before_zip_mtime
    assert status_path.read_bytes() == before_status
    assert catalog.get_artifact(artifact.id) == before_catalog
    assert (tmp_path / "catalog.sqlite").stat().st_mtime_ns == before_catalog_mtime


def test_long_archive_basename_uses_short_temporary_path(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    _, item, source, target = _make_source(catalog, tmp_path)
    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()

    suffix = ".zip"
    target_old_length = 250
    name_length = target_old_length - len(str(archive_dir)) - len(suffix) - 1
    old = archive_dir / ("x" * name_length + suffix)
    _, artifact = _add_archive(catalog, item.id, source.id, target.id, old)

    plan = build_archive_renumber_plan(catalog, site="mangaone", status_dir=tmp_path / "status")
    entry = plan.entries[0]

    assert entry.status == "RENAME"
    assert entry.temporary_path is not None
    assert entry.temporary_path == archive_dir / f".archive-renumber-{artifact.id}.tmp"
    assert old.name not in entry.temporary_path.name

    result = apply_archive_renumber_plan(plan)

    assert result.error is None
    assert not old.exists()
    assert entry.new_path is not None and entry.new_path.is_file()
    assert not entry.temporary_path.exists()
    assert catalog.get_artifact(artifact.id).locator == entry.new_path.as_posix()


def test_only_current_artifact_changes_and_history_remains_untouched(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    _, item, source, target = _make_source(catalog, tmp_path)
    historical_path = tmp_path / "historical.zip"
    current_path = tmp_path / "legacy.zip"
    historical_run, historical = _add_archive(
        catalog, item.id, source.id, target.id, historical_path
    )
    _, current = _add_archive(catalog, item.id, source.id, target.id, current_path)
    before_source = catalog.get_source(source.id)
    before_item = catalog.get_item(item.id)

    plan = build_archive_renumber_plan(catalog, site="mangaone", status_dir=tmp_path / "status")
    result = apply_archive_renumber_plan(plan)

    assert result.error is None
    assert historical_path.exists()
    assert catalog.get_artifact(historical.id).locator == historical_path.as_posix()
    assert catalog.get_crawl_run(historical_run.id).status == "succeeded"
    assert catalog.get_source(source.id) == before_source
    assert catalog.get_item(item.id) == before_item
    assert catalog.get_artifact(current.id).locator == plan.entries[0].new_path.as_posix()


def test_missing_locator_does_not_search_other_directories(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    _, item, source, target = _make_source(catalog, tmp_path)
    missing = tmp_path / "missing" / "legacy.zip"
    other = tmp_path / "other" / "legacy.zip"
    other.parent.mkdir()
    other.write_bytes(b"similar")
    _add_archive(catalog, item.id, source.id, target.id, missing)
    missing.unlink()

    plan = build_archive_renumber_plan(catalog, site="mangaone", status_dir=tmp_path / "status")
    assert plan.entries[0].status == "MISSING"
    assert other.exists()


def test_swap_uses_two_stage_rename(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key="swap", title="作品" , genre="漫画"))
    rows = []
    desired_names = ("001-作品-A.zip", "002-作品-B.zip")
    for label, external_id, position in (("A", "a", 1), ("B", "b", 2)):
        item = catalog.create_item(ItemInput(item_title=label, order_label=label), work_id=work.id)
        source = catalog.create_source(
            SourceInput(site="mangaone", external_id=external_id, display_position=position, access_mode="free"),
            item_id=item.id,
        )
        target = catalog.create_source_target(
            SourceTargetInput(backend="web", locator=f"https://example.invalid/{external_id}"),
            source_id=source.id,
        )
        rows.append((item, source, target))
    paths = [tmp_path / desired_names[1], tmp_path / desired_names[0]]
    artifacts = [
        _add_archive(catalog, item.id, source.id, target.id, path)[1]
        for (item, source, target), path in zip(rows, paths, strict=True)
    ]

    plan = build_archive_renumber_plan(catalog, site="mangaone", status_dir=tmp_path / "status")
    assert [entry.status for entry in plan.entries] == ["RENAME", "RENAME"]
    result = apply_archive_renumber_plan(plan)

    assert result.error is None
    assert (tmp_path / desired_names[0]).exists()
    assert (tmp_path / desired_names[1]).exists()
    assert catalog.get_artifact(artifacts[0].id).locator == (tmp_path / desired_names[0]).as_posix()
    assert catalog.get_artifact(artifacts[1].id).locator == (tmp_path / desired_names[1]).as_posix()


def test_external_collision_skips_without_overwrite(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    _, item, source, target = _make_source(catalog, tmp_path)
    old = tmp_path / "legacy.zip"
    _, artifact = _add_archive(catalog, item.id, source.id, target.id, old)
    target_path = tmp_path / "003-作品名-番外編.zip"
    target_path.write_bytes(b"do not overwrite")

    plan = build_archive_renumber_plan(catalog, site="mangaone", status_dir=tmp_path / "status")
    assert plan.entries[0].status == "COLLISION"
    result = apply_archive_renumber_plan(plan)
    assert result.error is None
    assert old.exists() and old.read_bytes() == b"zip bytes"
    assert target_path.read_bytes() == b"do not overwrite"
    assert catalog.get_artifact(artifact.id).locator == old.as_posix()


def test_status_mismatch_is_warning_but_zip_renames(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    _, item, source, target = _make_source(catalog, tmp_path)
    old = tmp_path / "legacy.zip"
    _add_archive(catalog, item.id, source.id, target.id, old)
    status_dir = tmp_path / "status"
    atomic_write_json(status_dir / "legacy.json", {"archive_path": "other.zip", "keep": 1})

    plan = build_archive_renumber_plan(catalog, site="mangaone", status_dir=status_dir)
    assert plan.entries[0].status == "RENAME"
    assert plan.entries[0].status_warning == "STATUS_MISMATCH"
    result = apply_archive_renumber_plan(plan)
    assert result.error is None
    assert plan.entries[0].new_path.is_file()
    assert (status_dir / "legacy.json").exists()


def test_status_missing_is_warning_but_zip_renames(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    _, item, source, target = _make_source(catalog, tmp_path)
    old = tmp_path / "legacy.zip"
    _add_archive(catalog, item.id, source.id, target.id, old)
    status_dir = tmp_path / "status"

    plan = build_archive_renumber_plan(catalog, site="mangaone", status_dir=status_dir)
    assert plan.entries[0].status_warning == "STATUS_MISSING"
    result = apply_archive_renumber_plan(plan)
    assert result.error is None
    assert plan.entries[0].new_path.is_file()


def test_matching_status_target_collision_blocks_zip_rename(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    _, item, source, target = _make_source(catalog, tmp_path)
    old = tmp_path / "legacy.zip"
    _add_archive(catalog, item.id, source.id, target.id, old)
    status_dir = tmp_path / "status"
    atomic_write_json(status_dir / "legacy.json", {"archive_path": old.as_posix(), "keep": True})
    target_status = status_dir / "003-作品名-番外編.json"
    atomic_write_json(target_status, {"archive_path": "unrelated.zip", "keep": False})

    plan = build_archive_renumber_plan(catalog, site="mangaone", status_dir=status_dir)
    assert plan.entries[0].status == "COLLISION"
    result = apply_archive_renumber_plan(plan)
    assert result.error is None
    assert old.exists()
    assert target_status.exists()


def test_scope_filters_are_explicit_and_work_site_is_and(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    _make_source(catalog, tmp_path, work_key="work-a", site="site-a", external_id="a")
    _make_source(catalog, tmp_path, work_key="work-b", site="site-a", external_id="b")
    _make_source(catalog, tmp_path, work_key="work-a-2", site="site-b", external_id="c")

    by_work = build_archive_renumber_plan(catalog, work_key="work-a", status_dir=tmp_path / "status")
    by_site = build_archive_renumber_plan(catalog, site="site-a", status_dir=tmp_path / "status")
    by_both = build_archive_renumber_plan(
        catalog, work_key="work-a", site="site-a", status_dir=tmp_path / "status"
    )
    all_plan = build_archive_renumber_plan(catalog, all_sources=True, status_dir=tmp_path / "status")

    assert len(by_work.entries) == 1
    assert len(by_site.entries) == 2
    assert len(by_both.entries) == 1
    assert len(all_plan.entries) == 3


def test_renumber_cli_json_is_one_machine_readable_document_for_dry_run_and_apply(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    _make_source(catalog, tmp_path)
    watchlist_path = tmp_path / "watchlist.yaml"
    watchlist_path.write_text("targets: []\n", encoding="utf-8")
    common = [
        "--work-key", "work",
        "--catalog", str(catalog.path),
        "--watchlist", str(watchlist_path),
        "--status-dir", str(tmp_path / "status"),
        "--json",
    ]

    assert renumber_cli_main(common) == 0
    dry_run_output = capsys.readouterr().out
    assert len(dry_run_output.splitlines()) == 1
    dry_run = json.loads(dry_run_output)
    assert dry_run["mode"] == "dry-run"
    assert dry_run["summary"]["no_artifact"] == 1
    assert dry_run["entries"][0]["old_path"] is None

    assert renumber_cli_main([*common, "--apply"]) == 0
    apply_output = capsys.readouterr().out
    assert len(apply_output.splitlines()) == 1
    applied = json.loads(apply_output)
    assert applied["mode"] == "apply"
    assert applied["result"] == {
        "error": None,
        "recovery_details": [],
        "recovery_required": False,
        "renamed": 0,
        "status_updated": 0,
    }


def test_synced_scope_managed_renumber_requires_matching_watchlist_and_whole_work(
    tmp_path: Path,
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work, _item, _source, _target = _make_managed_legacy_source(catalog)
    watchlist_path = tmp_path / "watchlist.yaml"
    watchlist_service = WatchlistService(watchlist_path)
    watchlist_service.add(
        key="chapters",
        work_key=work.work_key,
        site="mangaone",
        url="https://example.invalid/chapters",
        label="Chapters",
    )
    reconciler = ScopeReconciler(watchlist_service, catalog)
    preview = reconciler.preview(work.work_key)
    assert preview.ready and preview.legacy_bootstrap
    reconciler.apply(preview)

    plan_without_watchlist = build_archive_renumber_plan(
        catalog,
        work_key=work.work_key,
        status_dir=tmp_path / "status",
    )
    assert plan_without_watchlist.strict_blockers
    assert any("requires --watchlist" in value for value in plan_without_watchlist.strict_blockers)

    empty_watchlist_path = tmp_path / "wrong-watchlist.yaml"
    empty_watchlist_path.write_text("targets: []\n", encoding="utf-8")
    plan_wrong_watchlist = build_archive_renumber_plan(
        catalog,
        work_key=work.work_key,
        status_dir=tmp_path / "status",
        watchlist=WatchlistService(empty_watchlist_path),
    )
    assert plan_wrong_watchlist.strict_blockers
    assert any("no targets" in value for value in plan_wrong_watchlist.strict_blockers)

    with pytest.raises(ArchiveRenumberUsageError, match="full work-wide"):
        build_archive_renumber_plan(
            catalog,
            site="mangaone",
            status_dir=tmp_path / "status",
            watchlist=watchlist_service,
        )


def test_legacy_preview_cannot_apply_after_work_becomes_scope_managed(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work, item, source, target_row = _make_managed_legacy_source(catalog)
    old_path = tmp_path / "legacy.zip"
    _add_archive(catalog, item.id, source.id, target_row.id, old_path)
    legacy_plan = build_archive_renumber_plan(
        catalog,
        work_key=work.work_key,
        status_dir=tmp_path / "status",
    )
    assert legacy_plan.strict_work_keys == ()
    assert legacy_plan.entries[0].status == "RENAME"

    target = WatchlistTarget(
        "chapters",
        work.work_key,
        "mangaone",
        "https://example.invalid/chapters",
        "Chapters",
        archive_order=1,
    )
    watchlist_path = tmp_path / "watchlist.yaml"
    _write_renumber_watchlist(watchlist_path, [target])
    _record_renumber_inventory(
        catalog,
        target,
        [DiscoveryInventoryPosition(source.external_id, 1, in_scope=True)],
    )
    watchlist = WatchlistService(watchlist_path)
    reconciler = ScopeReconciler(watchlist, catalog)
    preview = reconciler.preview(work.work_key)
    assert preview.ready
    reconciler.apply(preview)

    before = old_path.read_bytes()
    result = apply_archive_renumber_plan(legacy_plan)

    assert result.error is not None
    assert "requires --watchlist" in result.error
    assert old_path.read_bytes() == before
    assert catalog.get_artifact(legacy_plan.entries[0].artifact.id).locator == old_path.as_posix()


@pytest.mark.parametrize("drift", ["archive_hash", "status_mismatch"])
def test_ordered_work_strict_renumber_blocks_hash_or_status_drift(
    tmp_path: Path, drift: str
) -> None:
    catalog, work, item, source, target_row, watchlist = _synced_ordered_source(
        tmp_path
    )
    old_path = tmp_path / "Books" / "小説" / work.title / "old.zip"
    if drift == "archive_hash":
        _add_archive(catalog, item.id, source.id, target_row.id, old_path)
    else:
        _add_real_archive(catalog, item.id, source.id, target_row.id, old_path)
    status_dir = tmp_path / "status"
    status_path = status_dir / "小説" / work.title / "old.json"
    atomic_write_json(
        status_path,
        {"archive_path": "different-file.zip", "status": "completed"},
    )
    original_archive_bytes = old_path.read_bytes()
    original_status_bytes = status_path.read_bytes()

    plan = build_archive_renumber_plan(
        catalog,
        work_key=work.work_key,
        status_dir=status_dir,
        watchlist=watchlist,
    )

    assert plan.strict_blockers
    if drift == "archive_hash":
        assert any("SHA-256/byte_size" in value for value in plan.strict_blockers)
        assert plan.summary()["errors"] == 1
    else:
        assert any("STATUS_MISMATCH" in value for value in plan.strict_blockers)
    result = apply_archive_renumber_plan(plan)
    assert result.error is not None
    assert old_path.read_bytes() == original_archive_bytes
    assert status_path.read_bytes() == original_status_bytes
    assert catalog.get_artifact(plan.entries[0].artifact.id).locator == old_path.as_posix()


@pytest.mark.parametrize("flat_status", ["matching", "mismatched"])
def test_strict_renumber_blocks_duplicate_namespaced_and_flat_status_files(
    tmp_path: Path, flat_status: str
) -> None:
    catalog, work, item, source, target, watchlist = _synced_ordered_source(tmp_path)
    old_path = tmp_path / "old.zip"
    artifact = _add_real_archive(catalog, item.id, source.id, target.id, old_path)
    status_dir = tmp_path / "status"
    namespaced = status_dir / work.genre / work.title / "old.json"
    flat = status_dir / "old.json"
    atomic_write_json(namespaced, {"archive_path": old_path.as_posix(), "status": "completed"})
    atomic_write_json(
        flat,
        {
            "archive_path": old_path.as_posix() if flat_status == "matching" else "other.zip",
            "status": "completed",
        },
    )
    before_archive = old_path.read_bytes()
    before_status = (namespaced.read_bytes(), flat.read_bytes())

    plan = build_archive_renumber_plan(
        catalog,
        work_key=work.work_key,
        status_dir=status_dir,
        watchlist=watchlist,
    )

    assert plan.entries[0].status_warning == "STATUS_AMBIGUOUS"
    assert any("STATUS_AMBIGUOUS" in value for value in plan.strict_blockers)
    result = apply_archive_renumber_plan(plan)
    assert result.error is not None
    assert old_path.read_bytes() == before_archive
    assert (namespaced.read_bytes(), flat.read_bytes()) == before_status
    assert catalog.get_artifact(artifact.id).locator == old_path.as_posix()


@pytest.mark.parametrize("checkpoint", [
    "synced", "missing", "stale_without_proof", "site_mismatch_legacy", "foreign_work_legacy",
])
def test_renumber_uses_current_flags_and_preserves_identity_guards(tmp_path: Path, checkpoint: str) -> None:
    catalog, work, item, source, target, watchlist = _synced_ordered_source(tmp_path)
    with sqlite3.connect(catalog.path) as connection:
        if checkpoint == "missing":
            connection.execute("DELETE FROM acquisition_scope_sync")
        elif checkpoint == "stale_without_proof":
            connection.execute("UPDATE acquisition_scope_sync SET status='stale'")
            connection.execute("DELETE FROM discovery_inventory_positions")
            connection.execute("DELETE FROM discovery_inventory_evidence")
    invalid_owner = checkpoint in {"site_mismatch_legacy", "foreign_work_legacy"}
    if invalid_owner:
        raw = yaml.safe_load(watchlist.path.read_text("utf-8"))
        for row in raw["targets"]:
            row.pop("archive_order", None)
        watchlist.path.write_text(yaml.safe_dump(raw), encoding="utf-8")
        if checkpoint == "site_mismatch_legacy":
            with sqlite3.connect(catalog.path) as connection:
                connection.execute("UPDATE sources SET site='mangaone' WHERE id=?", (source.id,))
        else:
            foreign = catalog.create_work(WorkInput(work_key="foreign-work", title="Foreign"))
            foreign_item = catalog.create_item(ItemInput(), work_id=foreign.id)
            catalog.create_source(
                SourceInput(site=source.site, external_id="foreign", discovery_key=source.discovery_key),
                item_id=foreign_item.id,
            )
    old_path = tmp_path / "old.zip"
    artifact = _add_real_archive(catalog, item.id, source.id, target.id, old_path)
    status_dir = tmp_path / "status"
    namespaced = status_dir / work.genre / work.title / "old.json"
    atomic_write_json(namespaced, {"archive_path": old_path.as_posix(), "status": "completed"})

    plan = build_archive_renumber_plan(
        catalog,
        work_key=work.work_key,
        status_dir=status_dir,
        watchlist=watchlist,
    )

    if invalid_owner:
        assert any("Work/site ownership" in reason for reason in plan.strict_blockers)
        before = old_path.read_bytes(), namespaced.read_bytes()
        assert apply_archive_renumber_plan(plan).error is not None
        assert (old_path.read_bytes(), namespaced.read_bytes()) == before
        assert catalog.get_artifact(artifact.id).locator == old_path.as_posix()
        return
    assert plan.strict_blockers == ()
    assert plan.entries[0].status_path == namespaced
    result = apply_archive_renumber_plan(plan)
    assert result.error is None
    assert not old_path.exists()
    assert plan.entries[0].new_path is not None and plan.entries[0].new_path.is_file()
    assert catalog.get_artifact(artifact.id).locator == plan.entries[0].new_path.as_posix()


def test_strict_renumber_blocks_active_archive_aliased_by_historical_artifact(
    tmp_path: Path,
) -> None:
    catalog, work, item, source, target, watchlist = _synced_ordered_source(tmp_path)
    shared_path = tmp_path / "old.zip"
    _add_real_archive(catalog, item.id, source.id, target.id, shared_path)
    current = _add_real_archive(catalog, item.id, source.id, target.id, shared_path)
    before = shared_path.read_bytes()

    plan = build_archive_renumber_plan(
        catalog,
        work_key=work.work_key,
        status_dir=tmp_path / "status",
        watchlist=watchlist,
    )

    entry = plan.entries[0]
    assert entry.status == "ERROR"
    assert entry.detail and "historical Artifact" in entry.detail
    assert any("ERROR" in value for value in plan.strict_blockers)
    result = apply_archive_renumber_plan(plan)
    assert result.error is not None
    assert shared_path.read_bytes() == before
    assert catalog.get_artifact(current.id).locator == shared_path.as_posix()


def test_strict_renumber_blocks_locator_aliased_by_another_work(tmp_path: Path) -> None:
    catalog, work, item, source, target, watchlist = _synced_ordered_source(tmp_path)
    shared_path = tmp_path / "old.zip"
    selected_artifact = _add_real_archive(catalog, item.id, source.id, target.id, shared_path)
    other_work = catalog.create_work(
        WorkInput(work_key="other-work", title="Other Work", genre="蟆剰ｪｬ")
    )
    other_item = catalog.create_item(ItemInput(order_label="Other Volume"), work_id=other_work.id)
    other_source = catalog.create_source(
        SourceInput(site="mangaone", external_id="other-volume", access_mode="free"),
        item_id=other_item.id,
    )
    other_target = catalog.create_source_target(
        SourceTargetInput(backend="web", locator="https://example.invalid/other"),
        source_id=other_source.id,
    )
    other_run = catalog.create_crawl_run(
        item_id=other_item.id,
        source_id=other_source.id,
        target_id=other_target.id,
        access_strategy="direct",
        started_at="2026-09-02T00:00:00+09:00",
    )
    catalog.mark_crawl_run_succeeded(other_run.id, page_count=1)
    other_artifact = catalog.create_artifact(
        ArtifactInput(
            kind="archive",
            format="zip",
            sha256=selected_artifact.sha256,
            byte_size=selected_artifact.byte_size,
            storage_backend="filesystem",
            locator=shared_path.as_posix(),
            state="present",
        ),
        item_id=other_item.id,
        crawl_run_id=other_run.id,
    )
    before = shared_path.read_bytes()

    plan = build_archive_renumber_plan(
        catalog,
        work_key=work.work_key,
        status_dir=tmp_path / "status",
        watchlist=watchlist,
    )

    assert plan.entries[0].status == "ERROR"
    assert plan.entries[0].detail and "Artifact" in plan.entries[0].detail
    assert any("ERROR" in value for value in plan.strict_blockers)
    result = apply_archive_renumber_plan(plan)
    assert result.error is not None
    assert shared_path.read_bytes() == before
    assert catalog.get_artifact(selected_artifact.id).locator == shared_path.as_posix()
    assert catalog.get_artifact(other_artifact.id).locator == shared_path.as_posix()


def test_strict_renumber_blocks_active_archive_aliased_by_excluded_source(
    tmp_path: Path,
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(
        WorkInput(work_key="alias-work", title="Alias Work", genre="蟆剰ｪｬ")
    )
    target = WatchlistTarget(
        "chapters",
        work.work_key,
        "mangaone",
        "https://example.invalid/series",
        "Chapters",
        discovery_scope=DiscoveryScope(through_url="https://example.invalid/ch/1"),
        archive_order=1,
    )
    active_item = catalog.create_item(ItemInput(order_label="Chapter 1"), work_id=work.id)
    active_source = catalog.create_source(
        SourceInput(
            site="mangaone", external_id="chapter-1", discovery_key="chapters",
            display_position=1, access_mode="free",
        ),
        item_id=active_item.id,
    )
    active_target = catalog.create_source_target(
        SourceTargetInput(backend="web", locator="https://example.invalid/ch/1"),
        source_id=active_source.id,
    )
    excluded_item = catalog.create_item(ItemInput(order_label="Chapter 2"), work_id=work.id)
    excluded_source = catalog.create_source(
        SourceInput(
            site="mangaone", external_id="chapter-2", discovery_key="chapters",
            display_position=2, access_mode="free",
        ),
        item_id=excluded_item.id,
    )
    excluded_target = catalog.create_source_target(
        SourceTargetInput(backend="web", locator="https://example.invalid/ch/2"),
        source_id=excluded_source.id,
    )
    watchlist_path = tmp_path / "watchlist.yaml"
    _write_renumber_watchlist(watchlist_path, [target])
    _record_renumber_inventory(
        catalog,
        target,
        [
            DiscoveryInventoryPosition("chapter-1", 1, in_scope=True),
            DiscoveryInventoryPosition("chapter-2", 2, in_scope=False),
        ],
    )
    watchlist = WatchlistService(watchlist_path)
    reconciler = ScopeReconciler(watchlist, catalog)
    preview = reconciler.preview(work.work_key)
    assert preview.ready
    reconciler.apply(preview)

    shared_path = tmp_path / "old.zip"
    _add_real_archive(catalog, active_item.id, active_source.id, active_target.id, shared_path)
    _add_real_archive(catalog, excluded_item.id, excluded_source.id, excluded_target.id, shared_path)
    before = shared_path.read_bytes()
    plan = build_archive_renumber_plan(
        catalog,
        work_key=work.work_key,
        status_dir=tmp_path / "status",
        watchlist=watchlist,
    )

    active_entry = next(entry for entry in plan.entries if entry.source.id == active_source.id)
    excluded_entry = next(entry for entry in plan.entries if entry.source.id == excluded_source.id)
    assert excluded_entry.status == "EXCLUDED"
    assert active_entry.status == "ERROR"
    assert active_entry.detail and "Artifact" in active_entry.detail
    result = apply_archive_renumber_plan(plan)
    assert result.error is not None
    assert shared_path.read_bytes() == before
    assert catalog.get_source(excluded_source.id).acquisition_enabled is False
    assert catalog.get_artifact(active_entry.artifact.id).locator == shared_path.as_posix()


def _synced_ordered_source(tmp_path: Path):
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(
        WorkInput(work_key="strict-work", title="Strict Work", genre="小説")
    )
    item = catalog.create_item(
        ItemInput(order_label="Volume 1", status="completed"), work_id=work.id
    )
    source = catalog.create_source(
        SourceInput(
            site="bookwalker",
            external_id="volume-1",
            discovery_key="volumes",
            display_position=1,
            access_mode="quota",
        ),
        item_id=item.id,
    )
    source_target = catalog.create_source_target(
        SourceTargetInput(backend="web", locator="https://example.invalid/volume-1"),
        source_id=source.id,
    )
    watchlist_path = tmp_path / "watchlist.yaml"
    target = WatchlistTarget(
        "volumes", work.work_key, "bookwalker", "https://example.invalid/series",
        "Volumes", archive_order=1,
    )
    _write_renumber_watchlist(watchlist_path, [target])
    _record_renumber_inventory(
        catalog,
        target,
        [DiscoveryInventoryPosition("volume-1", 1, in_scope=True)],
    )
    watchlist = WatchlistService(watchlist_path)
    reconciler = ScopeReconciler(watchlist, catalog)
    preview = reconciler.preview(work.work_key)
    assert preview.ready
    reconciler.apply(preview)
    return catalog, work, item, source, source_target, watchlist


def _make_managed_legacy_source(catalog: CatalogService):
    work = catalog.create_work(WorkInput(work_key="managed-work", title="Managed"))
    item = catalog.create_item(ItemInput(order_label="Chapter 1"), work_id=work.id)
    source = catalog.create_source(
        SourceInput(
            site="mangaone",
            external_id="chapter-1",
            discovery_key="chapters",
            display_position=1,
            access_mode="free",
        ),
        item_id=item.id,
    )
    target = catalog.create_source_target(
        SourceTargetInput(backend="web", locator="https://example.invalid/chapter-1"),
        source_id=source.id,
    )
    return work, item, source, target


def test_cross_site_work_archive_order_renumbers_100_plus_2_and_preserves_excluded_paid_zip(
    tmp_path: Path,
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(
        WorkInput(work_key="cross-site-series", title="Cross Site", genre="小説")
    )
    watchlist_path = tmp_path / "watchlist.yaml"
    zeb_target = WatchlistTarget(
        key="zeb-episodes",
        work_key=work.work_key,
        site="zebrack",
        url="https://example.invalid/zeb-series",
        label="Episodes 1-100",
        archive_order=1,
    )
    book_target = WatchlistTarget(
        key="book-volumes",
        work_key=work.work_key,
        site="bookwalker",
        url="https://example.invalid/book-series",
        label="Volumes",
        discovery_scope=DiscoveryScope(
            through_url="https://example.invalid/book-volume-2"
        ),
        archive_order=2,
    )
    _write_renumber_watchlist(watchlist_path, [zeb_target, book_target])
    zeb_positions: list[DiscoveryInventoryPosition] = []
    book_positions: list[DiscoveryInventoryPosition] = []
    book_rows: list[tuple[object, object, object, str]] = []

    for index in range(1, 101):
        external_id = f"episode-{index}"
        item = catalog.create_item(
            ItemInput(item_title=f"Episode {index}", order_label=f"Episode {index}", status="completed"),
            work_id=work.id,
        )
        catalog.create_source(
            SourceInput(
                site="zebrack",
                external_id=external_id,
                discovery_key=zeb_target.key,
                display_position=index,
                access_mode="free",
            ),
            item_id=item.id,
        )
        zeb_positions.append(DiscoveryInventoryPosition(external_id, index, in_scope=True))

    for index, in_scope in ((1, False), (2, True), (3, True)):
        external_id = f"volume-{index}"
        item = catalog.create_item(
            ItemInput(
                item_title=f"Volume {index}",
                order_label=f"Volume {index}",
                status="completed",
            ),
            work_id=work.id,
        )
        source = catalog.create_source(
            SourceInput(
                site="bookwalker",
                external_id=external_id,
                discovery_key=book_target.key,
                display_position=index,
                access_mode="quota",
                available=False,
            ),
            item_id=item.id,
        )
        target = catalog.create_source_target(
            SourceTargetInput(
                backend="web", locator=f"https://example.invalid/{external_id}"
            ),
            source_id=source.id,
        )
        old_path = tmp_path / "Books" / "小説" / work.title / f"old-volume-{index}.zip"
        _add_real_archive(catalog, item.id, source.id, target.id, old_path)
        if index == 1:
            book_rows.append((item, source, target, old_path.as_posix()))
        else:
            book_rows.append((item, source, target, old_path.as_posix()))
        book_positions.append(
            DiscoveryInventoryPosition(external_id, index, in_scope=in_scope)
        )

    _record_renumber_inventory(catalog, zeb_target, zeb_positions)
    _record_renumber_inventory(catalog, book_target, book_positions)
    watchlist = WatchlistService(watchlist_path)
    reconciler = ScopeReconciler(watchlist, catalog)
    preview = reconciler.preview(work.work_key)
    assert preview.ready
    reconciler.apply(preview)

    status_dir = tmp_path / "crawl-status"
    _write_matching_status_files(status_dir, work.genre or "小説", work.title, book_rows)
    plan = build_archive_renumber_plan(
        catalog,
        work_key=work.work_key,
        status_dir=status_dir,
        watchlist=watchlist,
    )

    assert plan.strict_blockers == ()
    entries_by_external_id = {entry.source.external_id: entry for entry in plan.entries}
    assert entries_by_external_id["volume-1"].status == "EXCLUDED"
    assert entries_by_external_id["volume-2"].new_path is not None
    assert entries_by_external_id["volume-2"].new_path.name.startswith("101-")
    assert entries_by_external_id["volume-3"].new_path is not None
    assert entries_by_external_id["volume-3"].new_path.name.startswith("102-")

    excluded_old_path = Path(book_rows[0][3])
    excluded_status_path = status_dir / "小説" / work.title / "old-volume-1.json"
    excluded_bytes = excluded_old_path.read_bytes()
    excluded_status_bytes = excluded_status_path.read_bytes()
    result = apply_archive_renumber_plan(plan)
    assert result.error is None
    assert result.renamed == 2
    assert excluded_old_path.read_bytes() == excluded_bytes
    assert excluded_status_path.read_bytes() == excluded_status_bytes
    assert catalog.get_artifact(
        entries_by_external_id["volume-2"].artifact.id
    ).locator == entries_by_external_id["volume-2"].new_path.as_posix()
    assert catalog.get_artifact(
        entries_by_external_id["volume-3"].artifact.id
    ).locator == entries_by_external_id["volume-3"].new_path.as_posix()


def _write_renumber_watchlist(path: Path, targets: list[WatchlistTarget]) -> None:
    rows = []
    for target in targets:
        value = {
            "key": target.key,
            "work_key": target.work_key,
            "site": target.site,
            "url": target.url,
            "label": target.label,
            "archive_order": target.archive_order,
        }
        if target.discovery_scope is not None:
            value["discovery_scope"] = {
                "through_url": target.discovery_scope.through_url
            }
        rows.append(value)
    path.write_text(yaml.safe_dump({"targets": rows}, sort_keys=False), encoding="utf-8")


def _record_renumber_inventory(
    catalog: CatalogService,
    target: WatchlistTarget,
    positions: list[DiscoveryInventoryPosition],
) -> None:
    catalog.record_discovery_inventory_evidence(
        work_key=target.work_key,
        discovery_key=target.key,
        site=target.site,
        target_url=target.url,
        scope_fingerprint=target_scope_fingerprint(target),
        listing_identity=f"test:{target.site}:{target.key}",
        positions=positions,
    )


def _add_real_archive(
    catalog: CatalogService,
    item_id: int,
    source_id: int,
    target_id: int,
    path: Path,
):
    data = f"archive-{source_id}".encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    run = catalog.create_crawl_run(
        item_id=item_id,
        source_id=source_id,
        target_id=target_id,
        access_strategy="direct",
        started_at=f"2026-09-01T00:00:{source_id % 60:02d}+09:00",
    )
    catalog.mark_crawl_run_succeeded(run.id, page_count=1)
    return catalog.create_artifact(
        ArtifactInput(
            kind="archive",
            format="zip",
            sha256=hashlib.sha256(data).hexdigest(),
            byte_size=len(data),
            storage_backend="filesystem",
            locator=path.as_posix(),
            state="present",
        ),
        item_id=item_id,
        crawl_run_id=run.id,
    )


def _write_matching_status_files(
    status_dir: Path,
    genre: str,
    title: str,
    rows: list[tuple[object, object, object, str]],
) -> None:
    for _item, _source, _target, archive_path in rows:
        path = Path(archive_path)
        status_path = status_dir / genre / title / f"{path.stem}.json"
        atomic_write_json(status_path, {"archive_path": path.as_posix(), "status": "completed"})


def test_duplicate_cross_site_target_is_collision(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key="same-work", title="作品名", genre="漫画"))
    rows = []
    for site, external_id in (("site-a", "a"), ("site-b", "b")):
        item = catalog.create_item(
            ItemInput(item_title="番外編", order_label="番外編"), work_id=work.id
        )
        source = catalog.create_source(
            SourceInput(
                site=site, external_id=external_id, display_position=3, access_mode="free"
            ),
            item_id=item.id,
        )
        target = catalog.create_source_target(
            SourceTargetInput(backend="web", locator=f"https://example.invalid/{external_id}"),
            source_id=source.id,
        )
        rows.append((item, source, target))
    for index, (item, source, target) in enumerate(rows):
        _add_archive(catalog, item.id, source.id, target.id, tmp_path / f"legacy-{index}.zip")

    plan = build_archive_renumber_plan(catalog, all_sources=True, status_dir=tmp_path / "status")
    assert [entry.status for entry in plan.entries] == ["COLLISION", "COLLISION"]


@pytest.mark.parametrize(
    "exception_factory",
    [
        pytest.param(lambda: RuntimeError("forced"), id="runtime-error"),
        pytest.param(
            lambda: sqlite3.OperationalError("database is locked"),
            id="sqlite-operational-error",
        ),
    ],
)
def test_catalog_failure_rolls_back_zip_and_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exception_factory,
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    _, item, source, target = _make_source(catalog, tmp_path)
    old = tmp_path / "legacy.zip"
    _, artifact = _add_archive(catalog, item.id, source.id, target.id, old)
    status_dir = tmp_path / "status"
    status_path = status_dir / "legacy.json"
    atomic_write_json(status_path, {"status": "completed", "archive_path": old.as_posix(), "keep": 1})
    original_status = status_path.read_bytes()

    plan = build_archive_renumber_plan(catalog, site="mangaone", status_dir=status_dir)
    def fail_catalog_update(_assignments):
        raise exception_factory()

    monkeypatch.setattr(catalog, "update_artifact_locators", fail_catalog_update)
    result = apply_archive_renumber_plan(plan)

    entry = plan.entries[0]
    assert result.error == "ERROR Catalog update failed; filesystem rollback completed"
    assert old.exists()
    assert not entry.new_path.exists()
    assert not list(tmp_path.rglob(".*-*.tmp"))
    assert status_path.read_bytes() == original_status
    assert not entry.new_status_path.exists()
    assert catalog.get_artifact(artifact.id).locator == old.as_posix()


@pytest.mark.parametrize("move_kind", ["zip", "status"])
def test_rename_then_interrupt_restores_original_paths_and_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    move_kind: str,
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    _, item, source, target = _make_source(catalog, tmp_path)
    old = tmp_path / "legacy.zip"
    _, artifact = _add_archive(catalog, item.id, source.id, target.id, old)
    status_dir = tmp_path / "status"
    status_path = status_dir / "legacy.json"
    atomic_write_json(status_path, {"status": "completed", "archive_path": old.as_posix()})
    original_zip = old.read_bytes()
    original_status = status_path.read_bytes()
    plan = build_archive_renumber_plan(catalog, site="mangaone", status_dir=status_dir)

    path_class = type(old)
    original_rename = path_class.rename
    interrupted = False

    def rename_then_interrupt(self, target_path):
        nonlocal interrupted
        result = original_rename(self, target_path)
        target_value = Path(target_path)
        if not interrupted:
            if move_kind == "zip":
                should_interrupt = self == old and target_value.name.startswith(
                    ".archive-renumber-"
                )
            else:
                should_interrupt = self == status_path and target_value.name.startswith(
                    ".status-renumber-"
                )
            if should_interrupt:
                interrupted = True
                raise KeyboardInterrupt(f"injected after {move_kind} rename")
        return result

    monkeypatch.setattr(path_class, "rename", rename_then_interrupt)
    result = apply_archive_renumber_plan(plan)

    entry = plan.entries[0]
    assert interrupted
    assert result.error == (
        f"ERROR KeyboardInterrupt: injected after {move_kind} rename; "
        "filesystem rollback completed"
    )
    assert not result.recovery_required
    assert old.read_bytes() == original_zip
    assert status_path.read_bytes() == original_status
    assert entry.new_path is not None and not entry.new_path.exists()
    assert entry.new_status_path is not None and not entry.new_status_path.exists()
    assert catalog.get_artifact(artifact.id).locator == old.as_posix()
    assert not list(tmp_path.rglob(".*-*.tmp"))


def test_post_commit_catalog_interruption_compensates_before_file_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    _, item, source, target = _make_source(catalog, tmp_path)
    old = tmp_path / "legacy.zip"
    _, artifact = _add_archive(catalog, item.id, source.id, target.id, old)
    status_dir = tmp_path / "status"
    status_path = status_dir / "legacy.json"
    atomic_write_json(status_path, {"status": "completed", "archive_path": old.as_posix()})
    original_status = status_path.read_bytes()
    plan = build_archive_renumber_plan(catalog, site="mangaone", status_dir=status_dir)

    original_update = catalog.update_artifact_locators
    calls = 0

    def commit_then_interrupt(assignments):
        nonlocal calls
        calls += 1
        updated = original_update(assignments)
        if calls == 1:
            raise KeyboardInterrupt("injected after Catalog commit")
        return updated

    monkeypatch.setattr(catalog, "update_artifact_locators", commit_then_interrupt)
    result = apply_archive_renumber_plan(plan)

    entry = plan.entries[0]
    assert calls == 2  # the second call compensates the committed new locator
    assert result.error == "ERROR Catalog update failed; filesystem rollback completed"
    assert not result.recovery_required
    assert old.read_bytes() == b"zip bytes"
    assert not entry.new_path.exists()
    assert status_path.read_bytes() == original_status
    assert not entry.new_status_path.exists()
    assert catalog.get_artifact(artifact.id).locator == old.as_posix()
    assert not list(tmp_path.rglob(".*-*.tmp"))


def test_collision_dependency_marks_both_entries_as_collision(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key="dependency", title="作品", genre="漫画"))

    rows = []
    for order_label, external_id, position in (("b", "a", 1), ("blocked", "b", 2)):
        item = catalog.create_item(
            ItemInput(item_title=order_label, order_label=order_label), work_id=work.id
        )
        source = catalog.create_source(
            SourceInput(
                site="mangaone",
                external_id=external_id,
                display_position=position,
                access_mode="free",
            ),
            item_id=item.id,
        )
        target = catalog.create_source_target(
            SourceTargetInput(backend="web", locator=f"https://example.invalid/{external_id}"),
            source_id=source.id,
        )
        rows.append((item, source, target))

    _add_archive(catalog, rows[0][0].id, rows[0][1].id, rows[0][2].id, tmp_path / "a.zip")
    _add_archive(
        catalog,
        rows[1][0].id,
        rows[1][1].id,
        rows[1][2].id,
        tmp_path / "001-作品-b.zip",
    )
    blocked = tmp_path / "002-作品-blocked.zip"
    blocked.write_bytes(b"non-participating")

    plan = build_archive_renumber_plan(catalog, site="mangaone", status_dir=tmp_path / "status")

    assert [entry.status for entry in plan.entries] == ["COLLISION", "COLLISION"]


def test_scope_requires_explicit_filter_and_all_cannot_mix(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    with pytest.raises(ArchiveRenumberUsageError):
        build_archive_renumber_plan(catalog, status_dir=tmp_path / "status")
    with pytest.raises(ArchiveRenumberUsageError):
        build_archive_renumber_plan(catalog, all_sources=True, site="mangaone")


def test_cli_scope_usage_errors_are_exit_code_two(tmp_path: Path) -> None:
    from scripts.renumber_archives import main

    assert main([]) == 2
    assert main(["--all", "--site", "mangaone"]) == 2
    catalog_path = tmp_path / "catalog.sqlite"
    CatalogService(catalog_path).initialize()
    assert main(["--all", "--catalog", str(catalog_path), "--status-dir", str(tmp_path / "status")]) == 0
