from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from screenshot_crawler.catalog import CatalogService, ItemInput, SourceInput, WorkInput
from screenshot_crawler.cli import main as cli_main
from screenshot_crawler.watchlist.models import DiscoveryScope, WatchlistTarget
from screenshot_crawler.watchlist.service import WatchlistService
from screenshot_crawler.watchlist.site_sync import ScopeSiteSyncService


def _write_watchlist(path: Path, targets: tuple[WatchlistTarget, ...]) -> None:
    values = []
    for target in targets:
        value = {
            "key": target.key,
            "work_key": target.work_key,
            "site": target.site,
            "url": target.url,
            "label": target.label,
            "enabled": target.enabled,
        }
        if target.discovery_scope is not None:
            scope = {}
            if target.discovery_scope.from_url is not None:
                scope["from_url"] = target.discovery_scope.from_url
            if target.discovery_scope.through_url is not None:
                scope["through_url"] = target.discovery_scope.through_url
            value["discovery_scope"] = scope
        if target.archive_order is not None:
            value["archive_order"] = target.archive_order
        values.append(value)
    path.write_text(yaml.safe_dump({"targets": values}, sort_keys=False), encoding="utf-8")


def _target(
    key: str,
    work_key: str,
    site: str,
    *,
    enabled: bool = True,
    scoped: bool = False,
) -> WatchlistTarget:
    return WatchlistTarget(
        key=key,
        work_key=work_key,
        site=site,
        url=f"https://example.test/{key}",
        label=key,
        enabled=enabled,
        discovery_scope=(
            DiscoveryScope(through_url=f"https://example.test/{key}/1") if scoped else None
        ),
    )


def _seed_catalog(path: Path, targets: tuple[WatchlistTarget, ...]) -> CatalogService:
    catalog = CatalogService(path)
    works = {}
    for target in targets:
        work = works.get(target.work_key)
        if work is None:
            work = catalog.create_work(WorkInput(work_key=target.work_key, title=target.work_key))
            works[target.work_key] = work
        item = catalog.create_item(
            ItemInput(item_title=f"{target.key}-1", status="completed"), work_id=work.id
        )
        catalog.create_source(
            SourceInput(
                site=target.site,
                external_id=f"{target.key}-1",
                discovery_key=target.key,
                available=True,
            ),
            item_id=item.id,
        )
    return catalog


def _service(tmp_path: Path, targets: tuple[WatchlistTarget, ...]):
    watchlist_path = tmp_path / "watchlist.yaml"
    catalog_path = tmp_path / "catalog.sqlite"
    _write_watchlist(watchlist_path, targets)
    catalog = _seed_catalog(catalog_path, targets)
    return ScopeSiteSyncService(WatchlistService(watchlist_path), catalog), catalog, watchlist_path


def test_site_preview_deduplicates_works_includes_disabled_and_is_read_only(
    tmp_path: Path,
) -> None:
    targets = (
        _target("days-disabled", "shared", "comicdays", enabled=False),
        _target("days-extra", "shared", "comicdays"),
        _target("bookwalker-key", "shared", "bookwalker"),
        _target("days-other-work", "another", "comicdays"),
    )
    service, catalog, watchlist_path = _service(tmp_path, targets)
    catalog_before = catalog.path.read_bytes()
    catalog_mtime = catalog.path.stat().st_mtime_ns
    watchlist_before = watchlist_path.read_bytes()
    watchlist_mtime = watchlist_path.stat().st_mtime_ns
    initial_files = sorted(path.name for path in tmp_path.iterdir())

    preview = service.preview_site("comicdays")

    assert preview.ready
    assert preview.target_keys == ("days-disabled", "days-extra", "days-other-work")
    assert preview.work_keys == ("another", "shared")
    shared = next(work for work in preview.works if work.work_key == "shared")
    assert shared.discovery_keys == ("bookwalker-key", "days-disabled", "days-extra")
    assert len(shared.source_flags) == 3
    assert catalog.path.read_bytes() == catalog_before
    assert catalog.path.stat().st_mtime_ns == catalog_mtime
    assert watchlist_path.read_bytes() == watchlist_before
    assert watchlist_path.stat().st_mtime_ns == watchlist_mtime
    assert sorted(path.name for path in tmp_path.iterdir()) == initial_files
    assert not catalog.path.with_name(f".{catalog.path.name}.job.lock").exists()


def test_site_apply_successfully_syncs_every_selected_work_across_sites(
    tmp_path: Path,
) -> None:
    targets = (
        _target("days-disabled", "shared", "comicdays", enabled=False),
        _target("days-extra", "shared", "comicdays"),
        _target("bookwalker-key", "shared", "bookwalker"),
        _target("days-other-work", "another", "comicdays"),
    )
    service, catalog, _watchlist_path = _service(tmp_path, targets)
    preview = service.preview_site("comicdays")

    result = service.apply_site(preview)

    assert result.complete
    assert result.applied_work_keys == ("another", "shared")
    assert result.not_applied_work_keys == ()
    assert result.failed_work_key is None
    assert catalog.get_acquisition_scope_sync("another") is not None
    assert catalog.get_acquisition_scope_sync("shared") is not None
    assert all(source.acquisition_enabled for source in catalog.list_sources())


def test_site_preview_unknown_site_does_not_fallback_to_catalog(tmp_path: Path) -> None:
    target = _target("days", "work", "comicdays")
    service, catalog, _watchlist = _service(tmp_path, (target,))
    missing_catalog = CatalogService(tmp_path / "absent" / "other.sqlite")
    unknown = ScopeSiteSyncService(service.watchlist, missing_catalog).preview_site("not-a-site")

    assert not unknown.ready
    assert unknown.work_keys == ()
    assert unknown.target_keys == ()
    assert unknown.blockers == ("No Watchlist targets found for site 'not-a-site'",)
    assert not missing_catalog.path.parent.exists()
    assert catalog.path.exists()


def test_site_apply_preflights_every_work_before_applying_any(tmp_path: Path) -> None:
    targets = (
        _target("ready", "ready-work", "comicdays"),
        _target("blocked", "blocked-work", "comicdays", scoped=True),
    )
    service, catalog, _watchlist = _service(tmp_path, targets)
    preview = service.preview_site("comicdays")
    assert not preview.ready

    result = service.apply_site(preview)

    assert not result.complete
    assert result.applied_work_keys == ()
    assert result.not_applied_work_keys == ("blocked-work", "ready-work")
    assert result.failed_work_key == "blocked-work"
    assert catalog.get_acquisition_scope_sync("ready-work") is None
    assert catalog.get_acquisition_scope_sync("blocked-work") is None


def test_site_apply_detects_added_site_target_before_any_work_is_applied(
    tmp_path: Path,
) -> None:
    original = (_target("days-a", "a-work", "comicdays"),)
    service, catalog, watchlist_path = _service(tmp_path, original)
    preview = service.preview_site("comicdays")
    appended = original + (_target("days-b", "b-work", "comicdays", enabled=False),)
    _write_watchlist(watchlist_path, appended)

    result = service.apply_site(preview)

    assert not result.complete
    assert result.selection_changed
    assert result.applied_work_keys == ()
    assert result.not_applied_work_keys == ("a-work", "b-work")
    assert "selection changed" in (result.error or "")
    assert catalog.get_acquisition_scope_sync("a-work") is None
    assert catalog.get_acquisition_scope_sync("b-work") is None


@pytest.mark.parametrize("change", ("new_site_work", "new_cross_site_key"))
def test_site_apply_detects_watchlist_change_during_final_sync_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    original = (
        _target("days-a", "a-work", "comicdays"),
        *(
            (_target("bookwalker-a", "a-work", "bookwalker"),)
            if change == "new_cross_site_key"
            else ()
        ),
    )
    service, catalog, watchlist_path = _service(tmp_path, original)
    preview = service.preview_site("comicdays")
    real_require_synchronized = service.reconciler.require_synchronized
    changed = False

    def mutate_after_final_sync_check(work_key: str):
        nonlocal changed
        result = real_require_synchronized(work_key)
        if not changed:
            changed = True
            _write_watchlist(
                watchlist_path,
                original
                + (
                    _target("days-b", "b-work", "comicdays")
                    if change == "new_site_work"
                    else _target("magapoke-a", "a-work", "magapoke"),
                ),
            )
        return result

    monkeypatch.setattr(
        service.reconciler, "require_synchronized", mutate_after_final_sync_check
    )

    result = service.apply_site(preview)

    assert not result.complete
    assert result.selection_changed
    assert result.applied_work_keys == ("a-work",)
    assert result.failed_work_key is None
    assert "changed during apply" in (result.error or "")
    assert result.not_applied_work_keys == (
        ("b-work",) if change == "new_site_work" else ()
    )
    assert catalog.get_acquisition_scope_sync("a-work") is not None
    if change == "new_site_work":
        assert catalog.get_acquisition_scope_sync("b-work") is None


def test_site_apply_shared_work_definition_change_is_rejected_before_writes(
    tmp_path: Path,
) -> None:
    initial = (
        _target("days", "shared", "comicdays"),
        _target("bookwalker", "shared", "bookwalker"),
    )
    service, catalog, watchlist_path = _service(tmp_path, initial)
    preview = service.preview_site("comicdays")
    changed = initial + (_target("magapoke", "shared", "magapoke"),)
    _write_watchlist(watchlist_path, changed)

    result = service.apply_site(preview)

    assert not result.complete
    assert not result.selection_changed
    assert result.applied_work_keys == ()
    assert result.not_applied_work_keys == ("shared",)
    assert "changed after preview" in (result.error or "")
    assert catalog.get_acquisition_scope_sync("shared") is None


def test_site_apply_uses_independent_work_revisions_and_reports_partial_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    targets = (
        _target("days-a", "a-work", "comicdays"),
        _target("days-b", "b-work", "comicdays"),
        _target("days-c", "c-work", "comicdays"),
    )
    service, catalog, _watchlist = _service(tmp_path, targets)
    preview = service.preview_site("comicdays")
    original_apply = service.reconciler.apply
    original_preview_site = service.preview_site
    failed_second = False

    def fail_preview_after_secondary_error(site: str):
        if failed_second:
            raise RuntimeError("injected diagnostic preview failure")
        return original_preview_site(site)

    def fail_second(work_preview):
        nonlocal failed_second
        if work_preview.work_key == "b-work":
            original_apply(work_preview)
            failed_second = True
            raise RuntimeError("injected second-work failure")
        return original_apply(work_preview)

    monkeypatch.setattr(service.reconciler, "apply", fail_second)
    monkeypatch.setattr(service, "preview_site", fail_preview_after_secondary_error)
    result = service.apply_site(preview)

    assert not result.complete
    assert result.applied_work_keys == ("a-work",)
    assert result.failed_work_key == "b-work"
    assert result.failure_stage == "apply"
    assert result.not_applied_work_keys == ("c-work",)
    assert "injected second-work failure" in (result.error or "")
    assert catalog.get_acquisition_scope_sync("a-work") is not None
    # The failed call may have committed before raising. The result does not
    # falsely claim rollback; only the later, unattempted C work is not-applied.
    assert catalog.get_acquisition_scope_sync("b-work") is not None
    assert catalog.get_acquisition_scope_sync("c-work") is None


def test_site_cli_requires_exactly_one_selector(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for selectors in ((), ("--work-key", "work", "--site", "comicdays")):
        monkeypatch.setattr(
            "sys.argv",
            ["screenshot-crawler", "watch", "scope-sync", "--catalog", str(tmp_path / "c.sqlite"), *selectors, "--dry-run"],
        )
        with pytest.raises(SystemExit) as raised:
            cli_main()
        assert raised.value.code == 2


def test_site_cli_apply_emits_one_json_document(tmp_path: Path, monkeypatch, capsys) -> None:
    target = _target("days", "work", "comicdays", enabled=False)
    service, catalog, watchlist_path = _service(tmp_path, (target,))
    del service
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
            "--site",
            "comicdays",
            "--apply",
            "--json",
        ],
    )

    cli_main()

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["complete"] is True
    assert payload["selected_work_keys"] == ["work"]
    assert payload["applied_work_keys"] == ["work"]
    assert payload["not_applied_work_keys"] == []
    assert catalog.get_acquisition_scope_sync("work") is not None


def test_unknown_site_cli_reports_no_targets_and_does_not_create_catalog(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    watchlist_path = tmp_path / "watchlist.yaml"
    _write_watchlist(watchlist_path, (_target("days", "work", "comicdays"),))
    catalog_path = tmp_path / "missing" / "catalog.sqlite"
    monkeypatch.setattr(
        "sys.argv",
        [
            "screenshot-crawler",
            "watch",
            "scope-sync",
            "--watchlist",
            str(watchlist_path),
            "--catalog",
            str(catalog_path),
            "--site",
            "unknown-site",
            "--dry-run",
            "--json",
        ],
    )

    with pytest.raises(SystemExit) as raised:
        cli_main()

    assert raised.value.code == 2
    output = capsys.readouterr()
    payload = json.loads(output.out)
    assert payload["site"] == "unknown-site"
    assert payload["ready"] is False
    assert payload["target_count"] == 0
    assert payload["work_count"] == 0
    assert payload["blockers"] == ["No Watchlist targets found for site 'unknown-site'"]
    assert "No Watchlist targets" in output.err
    assert not catalog_path.parent.exists()
