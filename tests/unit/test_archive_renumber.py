import json
from pathlib import Path

import pytest

from screenshot_crawler.batch import catalog_archive_stem
from screenshot_crawler.catalog import (
    ArtifactInput,
    CatalogService,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)
from screenshot_crawler.core.progress import atomic_write_json
from screenshot_crawler.maintenance.archive_renumber import (
    ArchiveRenumberUsageError,
    apply_archive_renumber_plan,
    build_archive_renumber_plan,
)

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
    assert catalog_archive_stem(work, item, source) == "作品名-003-番外編-作者"


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
    status_dir = tmp_path / "crawl-status"
    status_dir.mkdir()
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
    assert entry.new_path == old.parent / "作品名-003-番外編-作者.zip"
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
    updated = catalog.get_artifact(artifact.id)
    assert updated.locator == entry.new_path.as_posix()
    assert updated.sha256 == SHA.lower()
    assert updated.byte_size == 9
    assert catalog.get_item(item.id).status == "pending"
    assert work.title == "作品名"


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
    desired_names = ("作品-001-A.zip", "作品-002-B.zip")
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
    target_path = tmp_path / "作品名-003-番外編.zip"
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
    target_status = status_dir / "作品名-003-番外編.json"
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


def test_catalog_failure_rolls_back_zip_and_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    _, item, source, target = _make_source(catalog, tmp_path)
    old = tmp_path / "legacy.zip"
    _, artifact = _add_archive(catalog, item.id, source.id, target.id, old)
    status_dir = tmp_path / "status"
    status_path = status_dir / "legacy.json"
    atomic_write_json(status_path, {"status": "completed", "archive_path": old.as_posix(), "keep": 1})
    original_status = status_path.read_bytes()

    plan = build_archive_renumber_plan(catalog, site="mangaone", status_dir=status_dir)
    monkeypatch.setattr(catalog, "update_artifact_locators", lambda _assignments: (_ for _ in ()).throw(RuntimeError("forced")))
    result = apply_archive_renumber_plan(plan)

    assert result.error == "ERROR Catalog update failed; filesystem rollback completed"
    assert old.exists()
    assert not plan.entries[0].new_path.exists()
    assert status_path.read_bytes() == original_status
    assert catalog.get_artifact(artifact.id).locator == old.as_posix()


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
