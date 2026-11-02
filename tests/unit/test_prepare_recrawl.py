import importlib.util
import sys
import zipfile
from pathlib import Path

import pytest

from screenshot_crawler.catalog import (
    ArtifactInput,
    CatalogService,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)

SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "prepare_recrawl.py"
SPEC = importlib.util.spec_from_file_location("prepare_recrawl", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
prepare_recrawl = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = prepare_recrawl
SPEC.loader.exec_module(prepare_recrawl)


def _write_zip(path: Path, names: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            archive.writestr(name, b"synthetic page")


def _add_completed_archive(
    catalog: CatalogService,
    root: Path,
    *,
    site: str = "comicdays",
    work_title: str = "宇宙兄弟",
    work_key: str = "work-1",
    item_title: str = "第101話",
    archive_name: str = "101.zip",
    archive_entries: list[str] | None = None,
    create_file: bool = True,
):
    work = catalog.create_work(WorkInput(work_key=work_key, title=work_title))
    item = catalog.create_item(
        ItemInput(item_title=item_title, order_label=item_title), work_id=work.id
    )
    source = catalog.create_source(
        SourceInput(site=site, external_id=f"{site}-{item.id}", access_mode="free"),
        item_id=item.id,
    )
    target = catalog.create_source_target(
        SourceTargetInput(backend="web", locator=f"https://example.invalid/{item.id}"),
        source_id=source.id,
    )
    archive_path = root / "library" / work_title / archive_name
    if create_file:
        _write_zip(archive_path, archive_entries or ["page-0001.jpg"])
    run = catalog.create_crawl_run(
        item_id=item.id,
        source_id=source.id,
        target_id=target.id,
        access_strategy="direct",
        started_at="2026-10-06T00:00:00+09:00",
    )
    catalog.mark_crawl_run_succeeded(run.id, page_count=1)
    artifact = catalog.create_artifact(
        ArtifactInput(
            kind="archive",
            format="zip",
            sha256="a" * 64,
            byte_size=archive_path.stat().st_size if create_file else 0,
            storage_backend="filesystem",
            locator=archive_path.as_posix(),
            state="present",
        ),
        item_id=item.id,
        crawl_run_id=run.id,
    )
    catalog.mark_item_completed(item.id)
    return work, item, source, target, run, artifact, archive_path


@pytest.mark.parametrize(
    ("site", "entries", "expected"),
    [
        ("bookwalker", ["page-0001.JPG", "page-0002.jpeg"], "PREFERRED_ONLY"),
        ("bookwalker", ["page-0001.png", "page-0002.jpg"], "PREFERRED_ONLY"),
        ("bookwalker", ["page-0002.JPEG", "page-0001.PNG"], "PREFERRED_ONLY"),
        ("bookwalker", ["page-0001.png", "legacy.jpg"], "PREFERRED_ONLY"),
        ("bookwalker", ["page-0001.jpg", "page-0002.png"], "PREFERRED_ONLY"),
        ("bookwalker", ["page-0001.png", "page-0002.jpg", "page-0003.png"], "PREFERRED_ONLY"),
        ("bookwalker", ["page-0008.PNG", "page-0001.png", "page-0004.PNG", "page-0002.JPEG", "page-0003.jpg", "page-0005.png", "page-0006.jpg", "page-0007.png"], "PREFERRED_ONLY"),
        ("bookwalker", ["page-0001.jpg", "page-0002.png", "page-0003.jpg", "page-0004.jpg", "page-0005.jpg", "page-0006.jpg", "page-0007.jpg"], "PREFERRED_ONLY"),
        ("bookwalker", [f"page-{n:04d}.{'png' if n == 10 else 'jpg'}" for n in range(1, 18)], "PREFERRED_ONLY"),
        ("bookwalker", [f"page-{n:04d}.{'png' if n == 11 else 'jpg'}" for n in range(1, 18)], "FALLBACK_INCLUDED"),
        ("bookwalker", ["page-0001.png"], "FALLBACK_INCLUDED"),
        ("bookwalker", ["page-0001.png", "page-0001.jpg", "page-0002.jpeg"], "FALLBACK_INCLUDED"),
        ("bookwalker", ["001.png", "002.jpg"], "FALLBACK_INCLUDED"),
        ("bookwalker", ["page-0001.jpg", "002.jpg", "page-0003.png"], "FALLBACK_INCLUDED"),
        ("bookwalker", ["page-0001.jpg", "page-0002.png", "page-0002.jpg"], "FALLBACK_INCLUDED"),
        ("bookwalker", ["page-0001.jpg", "page-0002.png", "page-0002.PNG"], "FALLBACK_INCLUDED"),
        ("bookwalker", ["page-0001.jpg", "page-0002.png", "page-00003.jpg"], "FALLBACK_INCLUDED"),
        ("bookwalker", ["page-0000.png", "page-0001.jpg"], "FALLBACK_INCLUDED"),
        ("bookwalker", ["page-0001.jpg", "page-9999.png", "page-10000.jpg", "page-10001.jpg", "page-10002.jpg", "page-10003.jpg", "page-10004.jpg"], "FALLBACK_INCLUDED"),
        ("bookwalker", ["page-0001.webp", "page-0002.jpg"], "UNEXPECTED_FORMAT"),
        ("comicdays", ["001.JPG", "002.jpeg"], "PREFERRED_ONLY"),
        ("comicdays", ["001.png"], "FALLBACK_INCLUDED"),
        ("comicdays", ["001.jpg", "002.PNG"], "FALLBACK_INCLUDED"),
        ("mangaone", ["001.WEBP"], "PREFERRED_ONLY"),
        ("mangaone", ["001.webp", "002.png"], "FALLBACK_INCLUDED"),
        ("hanayume", ["001.WEBP"], "PREFERRED_ONLY"),
        ("hanayume", ["001.PNG"], "FALLBACK_INCLUDED"),
        ("hanayume", ["001.webp", "002.png"], "FALLBACK_INCLUDED"),
        ("younganimal", ["001.WEBP"], "PREFERRED_ONLY"),
        ("younganimal", ["001.PNG"], "FALLBACK_INCLUDED"),
        ("younganimal", ["001.webp", "002.png"], "FALLBACK_INCLUDED"),
        ("younganimal", ["001.jpg"], "UNEXPECTED_FORMAT"),
        ("magapoke", ["001.jpeg"], "PREFERRED_ONLY"),
    ],
)
def test_site_archive_policies_classify_synthetic_zip(
    tmp_path: Path, site: str, entries: list[str], expected: str
) -> None:
    path = tmp_path / "archive.zip"
    _write_zip(path, entries)

    inspection = prepare_recrawl.inspect_archive(
        path, prepare_recrawl.archive_policy_for_site(site)
    )

    assert inspection.classification.value == expected



@pytest.mark.parametrize(
    ("entries", "preferred", "allowed", "fallback"),
    [
        (["page-0002.jpg", "page-0001.png"], 1, 1, 0),
        (["page-0008.png", "page-0001.png", "page-0004.PNG", "page-0002.jpeg", "page-0003.jpg", "page-0005.png", "page-0006.jpg", "page-0007.png"], 3, 5, 0),
        (["page-0001.png", "page-0002.png", "page-0003.jpg", "page-0004.jpg", "page-0005.jpg", "page-0006.png", "page-0007.jpg", "page-0008.png"], 4, 4, 0),
        ([f"page-{n:04d}.{'png' if n in {10, 11} else 'jpg'}" for n in range(1, 18)], 15, 1, 1),
        ([f"page-{n:04d}.{'png' if n in {1, 10, 13, 17} else 'jpg'}" for n in range(1, 18)][::-1], 13, 4, 0),
    ],
)
def test_bookwalker_head_and_tail_png_counts(
    tmp_path: Path, entries: list[str], preferred: int, allowed: int, fallback: int,
) -> None:
    path = tmp_path / "bookwalker.zip"
    _write_zip(path, entries)

    result = prepare_recrawl.inspect_archive(
        path, prepare_recrawl.archive_policy_for_site("bookwalker")
    )

    assert result.classification is (
        prepare_recrawl.FALLBACK_INCLUDED if fallback else prepare_recrawl.PREFERRED_ONLY
    )
    assert result.preferred_count == preferred
    assert result.fallback_count == fallback
    assert result.allowed_fallback_count == allowed


@pytest.mark.parametrize(
    ("entries", "should_apply"),
    [
        (["page-0001.png", "page-0002.jpg"], False),
        (["page-0001.jpg", "page-0002.png"], False),
        (["page-0001.png", "page-0002.jpg", "page-0003.png", "page-0004.png"], False),
        (["page-0001.png", "page-0002.png", "page-0003.jpg", "page-0004.jpg", "page-0005.jpg", "page-0006.png", "page-0007.jpg", "page-0008.png"], False),
        ([f"page-{n:04d}.{'png' if n == 11 else 'jpg'}" for n in range(1, 18)], True),
        (["page-0001.png"], True),
    ],
)
def test_bookwalker_scan_apply_only_targets_problematic_png(
    tmp_path: Path, entries: list[str], should_apply: bool
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    _work, item, _source, _target, _run, artifact, path = _add_completed_archive(
        catalog, tmp_path, site="bookwalker", archive_entries=entries
    )

    report = prepare_recrawl.scan_catalog(catalog, site="bookwalker")
    assert len(report.recrawl_results(ignore_missing=False)) == int(should_apply)
    applied = prepare_recrawl.apply_scan_results(
        catalog,
        report,
        library_dir=tmp_path / "library",
        backup_root=tmp_path / "backup",
        timestamp="run",
    )
    assert applied.failed == 0
    assert applied.archives_moved == int(should_apply)
    assert applied.items_returned_pending == int(should_apply)
    assert catalog.get_item(item.id).status == ("pending" if should_apply else "completed")
    if should_apply:
        assert not path.exists()
        assert catalog.get_artifact(artifact.id).locator != path.as_posix()
    else:
        assert path.exists()
        assert catalog.get_artifact(artifact.id).locator == path.as_posix()


def test_unexpected_empty_broken_and_missing_archives(tmp_path: Path) -> None:
    policy = prepare_recrawl.archive_policy_for_site("comicdays")
    unexpected = tmp_path / "unexpected.zip"
    _write_zip(unexpected, ["001.gif"])
    empty = tmp_path / "empty.zip"
    _write_zip(empty, [])
    broken = tmp_path / "broken.zip"
    broken.write_bytes(b"not a zip")

    assert prepare_recrawl.inspect_archive(unexpected, policy).classification.value == "UNEXPECTED_FORMAT"
    assert prepare_recrawl.inspect_archive(empty, policy).classification.value == "UNEXPECTED_FORMAT"
    broken_result = prepare_recrawl.inspect_archive(broken, policy)
    assert broken_result.classification.value == "BROKEN"
    assert "BadZipFile" in (broken_result.reason or "")
    assert prepare_recrawl.inspect_archive(tmp_path / "missing.zip", policy).classification.value == "MISSING"


def test_os_metadata_does_not_affect_page_format(tmp_path: Path) -> None:
    path = tmp_path / "metadata.zip"
    _write_zip(path, ["001.jpg", "__MACOSX/._001.jpg", "Thumbs.db", ".DS_Store"])

    result = prepare_recrawl.inspect_archive(
        path, prepare_recrawl.archive_policy_for_site("comicdays")
    )

    assert result.classification is prepare_recrawl.PREFERRED_ONLY
    assert result.preferred_count == 1


@pytest.mark.parametrize("force", [False, True])
def test_ambiguous_artifact_is_classified_and_not_applied(tmp_path: Path, force: bool) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    _work, item, _source, _target, run, artifact, first = _add_completed_archive(
        catalog, tmp_path, archive_name="one.zip"
    )
    second = tmp_path / "library" / "宇宙兄弟" / "two.zip"
    _write_zip(second, ["page-0001.jpg"])
    catalog.create_artifact(
        ArtifactInput(
            kind="archive",
            format="zip",
            sha256="b" * 64,
            byte_size=second.stat().st_size,
            storage_backend="filesystem",
            locator=second.as_posix(),
            state="present",
        ),
        item_id=item.id,
        crawl_run_id=run.id,
    )

    report = prepare_recrawl.scan_catalog(
        catalog, site="comicdays", work="宇宙兄弟", item_ids=[item.id] if force else None, force=force,
    )
    assert report.results[0].classification is prepare_recrawl.AMBIGUOUS_ARTIFACT
    applied = prepare_recrawl.apply_scan_results(
        catalog,
        report,
        library_dir=tmp_path / "library",
        backup_root=tmp_path / "backup",
        timestamp="run",
    )

    assert applied.skipped_ambiguous == 1
    assert applied.failed == 0
    assert first.exists() and second.exists()
    assert catalog.get_item(item.id).status == "completed"
    assert catalog.get_artifact(artifact.id).locator == first.as_posix()


def test_default_output_shows_only_problems_and_show_all_adds_preferred(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    _add_completed_archive(catalog, tmp_path, archive_name="preferred.zip")
    _add_completed_archive(
        catalog,
        tmp_path,
        work_key="work-2",
        item_title="第102話",
        archive_name="fallback.zip",
        archive_entries=["page-0001.png"],
    )

    assert prepare_recrawl.main(["--site", "comicdays", "--catalog", str(catalog.path)]) == 0
    output = capsys.readouterr().out
    assert "FALLBACK_INCLUDED" in output
    assert "preferred.zip" not in output
    assert "PREFERRED_ONLY: 1" in output
    assert "FALLBACK_INCLUDED: 1" in output

    assert prepare_recrawl.main(
        ["--site", "comicdays", "--catalog", str(catalog.path), "--show-all"]
    ) == 0
    output = capsys.readouterr().out
    assert "preferred.zip" in output


def test_site_work_and_work_only_scopes_are_exact(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    _add_completed_archive(catalog, tmp_path, site="comicdays", work_key="comic", archive_name="comic.zip")
    _add_completed_archive(
        catalog,
        tmp_path,
        site="mangaone",
        work_key="manga",
        archive_name="manga.zip",
        archive_entries=["page-0001.webp"],
    )
    _add_completed_archive(
        catalog,
        tmp_path,
        site="comicdays",
        work_title="別作品",
        work_key="other",
        archive_name="other.zip",
        archive_entries=["page-0001.png"],
    )

    site_report = prepare_recrawl.scan_catalog(catalog, site="comicdays", work="宇宙兄弟")
    assert [result.item.item_title for result in site_report.results] == ["第101話"]
    work_report = prepare_recrawl.scan_catalog(catalog, work="宇宙兄弟")
    assert len(work_report.results) == 2
    assert {result.site for result in work_report.results} == {"comicdays", "mangaone"}


def test_no_scope_is_cli_error() -> None:
    assert prepare_recrawl.main([]) == 1


@pytest.mark.parametrize("force", [False, True])
@pytest.mark.parametrize("preferred", [False, True])
def test_explicit_item_ids_limit_inspection_and_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    force: bool, preferred: bool,
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    entries = ["page-0001.png", "page-0002.jpg"] if preferred else ["page-0001.png"]
    records = [
        _add_completed_archive(
            catalog, tmp_path, site="bookwalker", work_key=f"work-{index}",
            archive_name=f"{index}.zip", archive_entries=entries,
        ) for index in range(3)
    ]
    chosen = [records[0][1].id, records[1][1].id]
    inspected = []
    original_inspect = prepare_recrawl.inspect_archive

    def track_inspection(path, policy):
        inspected.append(Path(path))
        return original_inspect(path, policy)

    monkeypatch.setattr(prepare_recrawl, "inspect_archive", track_inspection)
    report = prepare_recrawl.scan_catalog(catalog, item_ids=[*chosen, chosen[0]], force=force)
    assert report.selected_item_ids == tuple(chosen)
    assert report.scanned_completed_items == 2
    assert inspected == [records[0][6], records[1][6]]
    assert len(report.recrawl_results(ignore_missing=False)) == (2 if force or not preferred else 0)
    before = {record[1].id: record[6].read_bytes() for record in records}
    args = ["--catalog", str(catalog.path), "--item-id", str(chosen[1]),
            "--item-id", str(chosen[0]), "--item-id", str(chosen[0])]
    if force:
        args.append("--force")
    assert prepare_recrawl.main(args) == 0
    output = capsys.readouterr().out
    assert "Dry-run only." in output
    if preferred and force:
        assert "PREFERRED_ONLY (explicit recrawl)" in output
        assert "recrawl candidates: 2" in output
    assert all(record[6].read_bytes() == before[record[1].id] for record in records)
    assert all(catalog.get_item(record[1].id).status == "completed" for record in records)
    args.extend(["--apply", "--library-dir", str(tmp_path / "library"),
                 "--backup-root", str(tmp_path / "backup")])
    assert prepare_recrawl.main(args) == 0
    should_apply = force or not preferred
    for index, record in enumerate(records):
        item, source, run, artifact, path = record[1], record[2], record[4], record[5], record[6]
        changed = should_apply and index < 2
        assert catalog.get_item(item.id).status == ("pending" if changed else "completed")
        updated = catalog.get_artifact(artifact.id)
        assert updated.state == "present"
        assert Path(updated.locator).read_bytes() == before[item.id]
        assert path.exists() is not changed
        assert catalog.get_source(source.id) == source
        assert catalog.get_crawl_run(run.id).status == "succeeded"


@pytest.mark.parametrize("invalid", ["unknown", "pending", "site", "work"])
def test_invalid_explicit_item_scope_prevents_all_apply(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], invalid: str,
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    record = _add_completed_archive(catalog, tmp_path, archive_entries=["page-0001.png"])
    item, path = record[1], record[6]
    args = ["--catalog", str(catalog.path), "--item-id", str(item.id), "--force", "--apply"]
    if invalid == "unknown":
        args.extend(["--item-id", "999999"])
    elif invalid == "pending":
        catalog.mark_item_pending(item.id)
    elif invalid == "site":
        args.extend(["--site", "bookwalker"])
    else:
        args.extend(["--work", "other work"])
    before = path.read_bytes()
    assert prepare_recrawl.main(args) == 1
    assert "not completed supported items" in capsys.readouterr().err
    assert path.read_bytes() == before
    assert catalog.get_item(item.id).status == ("pending" if invalid == "pending" else "completed")


@pytest.mark.parametrize("value", ["0", "-1", "invalid"])
def test_invalid_item_id_is_cli_error(value: str) -> None:
    with pytest.raises(SystemExit) as exc:
        prepare_recrawl.main(["--item-id", value])
    assert exc.value.code == 2


def test_force_without_item_scope_is_rejected_before_opening_catalog(tmp_path: Path) -> None:
    path = tmp_path / "must-not-create.sqlite"
    assert prepare_recrawl.main(["--site", "bookwalker", "--force", "--catalog", str(path)]) == 1
    assert not path.exists()


@pytest.mark.parametrize("site", ["comicdays", "hanayume", "younganimal"])
def test_fallback_apply_moves_archive_updates_locator_and_pending(tmp_path: Path, site: str) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    _work, item, _source, _target, _run, artifact, archive_path = _add_completed_archive(
        catalog,
        tmp_path,
        site=site,
        archive_entries=["page-0001.jpg" if site == "comicdays" else "page-0001.webp", "page-0002.png"],
    )
    original = archive_path.read_bytes()
    source_before = catalog.get_source(_source.id)
    run_before = catalog.get_crawl_run(_run.id)
    report = prepare_recrawl.scan_catalog(catalog, site=site)
    applied = prepare_recrawl.apply_scan_results(
        catalog,
        report,
        library_dir=tmp_path / "library",
        backup_root=tmp_path / "backup",
        timestamp="run",
    )

    backup = tmp_path / "backup" / "run" / "宇宙兄弟" / "101.zip"
    assert applied.archives_moved == 1
    assert applied.items_returned_pending == 1
    assert not archive_path.exists() and backup.exists()
    assert backup.read_bytes() == original
    updated = catalog.get_artifact(artifact.id)
    assert updated.locator == backup.as_posix()
    assert updated.state == "present"
    assert catalog.get_item(item.id).status == "pending"
    assert catalog.get_source(_source.id) == source_before
    assert catalog.get_crawl_run(_run.id) == run_before


def test_broken_apply_moves_zip_and_returns_item_to_pending(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    _work, item, _source, _target, _run, artifact, archive_path = _add_completed_archive(
        catalog, tmp_path, archive_name="broken.zip"
    )
    archive_path.write_bytes(b"broken")
    report = prepare_recrawl.scan_catalog(catalog, site="comicdays")
    assert report.results[0].classification is prepare_recrawl.BROKEN
    applied = prepare_recrawl.apply_scan_results(
        catalog,
        report,
        library_dir=tmp_path / "library",
        backup_root=tmp_path / "backup",
        timestamp="run",
    )

    assert applied.archives_moved == 1
    assert catalog.get_item(item.id).status == "pending"
    assert catalog.get_artifact(artifact.id).state == "present"


def test_missing_default_marks_artifact_missing_and_pending(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    _work, item, _source, _target, _run, artifact, archive_path = _add_completed_archive(
        catalog, tmp_path, archive_name="missing.zip"
    )
    archive_path.unlink()
    report = prepare_recrawl.scan_catalog(catalog, site="comicdays")
    applied = prepare_recrawl.apply_scan_results(catalog, report, timestamp="run")

    assert report.results[0].classification is prepare_recrawl.MISSING
    assert applied.artifacts_marked_missing == 1
    assert applied.items_returned_pending == 1
    assert catalog.get_artifact(artifact.id).state == "missing"
    assert catalog.get_item(item.id).status == "pending"


def test_preferred_apply_is_unchanged(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    _work, item, _source, _target, _run, artifact, archive_path = _add_completed_archive(
        catalog, tmp_path
    )
    report = prepare_recrawl.scan_catalog(catalog, site="comicdays")
    applied = prepare_recrawl.apply_scan_results(catalog, report, timestamp="run")

    assert applied.archives_moved == 0
    assert archive_path.exists()
    assert catalog.get_artifact(artifact.id).locator == archive_path.as_posix()
    assert catalog.get_item(item.id).status == "completed"


def test_backup_collision_never_overwrites_or_updates_catalog(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    _work, item, _source, _target, _run, artifact, archive_path = _add_completed_archive(
        catalog, tmp_path, archive_entries=["page-0001.png"]
    )
    collision = tmp_path / "backup" / "run" / "宇宙兄弟" / "101.zip"
    collision.parent.mkdir(parents=True)
    collision.write_bytes(b"keep")
    report = prepare_recrawl.scan_catalog(catalog, site="comicdays")
    applied = prepare_recrawl.apply_scan_results(
        catalog,
        report,
        library_dir=tmp_path / "library",
        backup_root=tmp_path / "backup",
        timestamp="run",
    )

    assert applied.failed == 1
    assert collision.read_bytes() == b"keep"
    assert archive_path.exists()
    assert catalog.get_artifact(artifact.id).locator == archive_path.as_posix()
    assert catalog.get_item(item.id).status == "completed"


@pytest.mark.parametrize("force", [False, True])
def test_ignore_missing_excludes_problem_recrawl_and_apply_changes(tmp_path: Path, force: bool) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    _work, item, _source, _target, _run, artifact, archive_path = _add_completed_archive(
        catalog, tmp_path, archive_name="missing.zip"
    )
    archive_path.unlink()
    report = prepare_recrawl.scan_catalog(
        catalog, site="comicdays", item_ids=[item.id] if force else None, force=force,
    )
    assert len(report.problem_results(ignore_missing=True)) == 0
    assert len(report.recrawl_results(ignore_missing=True)) == 0
    applied = prepare_recrawl.apply_scan_results(
        catalog, report, ignore_missing=True, timestamp="run"
    )

    assert applied.archives_moved == 0
    assert applied.artifacts_marked_missing == 0
    assert applied.items_returned_pending == 0
    assert catalog.get_artifact(artifact.id).state == "present"
    assert catalog.get_item(item.id).status == "completed"


def test_ignore_missing_show_all_marks_item_ignored_and_summary_count(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    _add_completed_archive(catalog, tmp_path, archive_name="missing.zip")[6].unlink()

    assert prepare_recrawl.main(
        [
            "--site",
            "comicdays",
            "--catalog",
            str(catalog.path),
            "--ignore-missing",
            "--show-all",
        ]
    ) == 0
    output = capsys.readouterr().out
    assert "MISSING (ignored)" in output
    assert "ignored missing: 1" in output
    assert "problems: 0" in output
    assert "recrawl candidates: 0" in output


def test_unsupported_explicit_site_fails_closed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = prepare_recrawl.main(
        ["--site", "unknown-site", "--catalog", str(tmp_path / "missing.sqlite")]
    )
    assert code == 1
    assert "unsupported archive policy for site=unknown-site" in capsys.readouterr().err
