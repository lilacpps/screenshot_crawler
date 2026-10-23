import hashlib
import json
from pathlib import Path

import pytest

from screenshot_crawler.catalog import (
    ArtifactInput,
    CatalogService,
    DiscoveryInventoryPosition,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)
from screenshot_crawler.maintenance.archive_audit import audit_existing_archives
from screenshot_crawler.watchlist.fingerprints import target_scope_fingerprint
from screenshot_crawler.watchlist.reconcile import ScopeReconciler
from screenshot_crawler.watchlist.service import WatchlistService
from scripts.check_archives import main


def graph(tmp_path: Path, *, site="mangaone", key="episodes", work=None, index=1):
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = work or catalog.create_work(WorkInput(work_key="series", title="Series"))
    item = catalog.create_item(ItemInput(order_label=str(index)), work_id=work.id)
    source = catalog.create_source(
        SourceInput(site=site, external_id=f"episode-{index}", discovery_key=key,
                    access_mode="free", display_position=1),
        item_id=item.id,
    )
    target = catalog.create_source_target(
        SourceTargetInput(backend="web", locator=f"https://example.invalid/{index}"),
        source_id=source.id,
    )
    archive = tmp_path / "Books" / "小説" / "Series" / f"legacy-{index}.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(b"synthetic ZIP")
    run = catalog.create_crawl_run(item_id=item.id, source_id=source.id,
                                   target_id=target.id, access_strategy="direct")
    catalog.mark_crawl_run_succeeded(run.id, page_count=1)
    artifact = catalog.create_artifact(
        ArtifactInput(kind="archive", format="zip", sha256="0" * 64,
                      byte_size=13, storage_backend="filesystem", locator=str(archive)),
        item_id=item.id, crawl_run_id=run.id,
    )
    return catalog, work, source, archive, artifact


def empty_watchlist(tmp_path):
    path = tmp_path / "watchlist.yaml"
    path.write_text("targets: []\n", encoding="utf-8")
    return WatchlistService(path)


@pytest.mark.parametrize("issue", ["wrong_status", "malformed_status", "ambiguous", "clean"])
def test_audit_reports_historical_findings_without_writes(tmp_path: Path, issue: str):
    catalog, work, source, archive, artifact = graph(tmp_path)
    if issue == "clean":
        archive = archive.rename(archive.with_name("001-Series-1.zip"))
        catalog.update_artifact_locators({artifact.id: (artifact.locator, str(archive))})
    elif issue == "ambiguous":
        catalog.create_artifact(
            ArtifactInput(kind="archive", format="zip", sha256="1" * 64, byte_size=13,
                          storage_backend="filesystem", locator=str(archive)),
            item_id=source.item_id, crawl_run_id=artifact.crawl_run_id,
        )
    status = tmp_path / "crawl-status" / "小説" / "Series" / f"{archive.stem}.json"
    status.parent.mkdir(parents=True)
    status.write_text("{" if issue == "malformed_status" else json.dumps({
        "archive_path": str(tmp_path / "wrong.zip") if issue == "wrong_status" else str(archive)
    }), encoding="utf-8")
    watchlist = empty_watchlist(tmp_path)
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}

    report = audit_existing_archives(catalog, work_key=work.work_key, watchlist=watchlist)

    assert not report.errors
    if issue == "ambiguous":
        assert any("multiple current ZIP Artifacts" in finding for finding in report.findings)
    elif issue == "clean":
        assert not report.findings
    else:
        assert any("current expected name" in finding for finding in report.findings)
        assert any(("is unreadable" if issue == "malformed_status" else "does not match")
                   in finding for finding in report.findings)
    assert before == {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


@pytest.mark.parametrize("change", ["synced", "unsynced", "removed_binding"])
def test_site_audit_uses_whole_work_numbering_and_requires_current_scope(
    tmp_path: Path, change: str,
):
    catalog, work, first, archive, artifact = graph(tmp_path)
    _, _, second, archive2, artifact2 = graph(
        tmp_path, site="bookwalker", key="books", work=work, index=2,
    )
    watchlist = empty_watchlist(tmp_path)
    for key, site, order in [("episodes", "mangaone", 1), ("books", "bookwalker", 2)]:
        watchlist.add(key=key, work_key=work.work_key, site=site,
                      url=f"https://example.invalid/{key}", label=key, archive_order=order)
    for target, source in zip(watchlist.list_targets(), [first, second], strict=True):
        catalog.record_discovery_inventory_evidence(
            work_key=work.work_key, discovery_key=target.key, site=target.site,
            target_url=target.url, scope_fingerprint=target_scope_fingerprint(target),
            listing_identity=target.key,
            positions=[DiscoveryInventoryPosition(source.external_id, 1)],
        )
    if change != "unsynced":
        reconciler = ScopeReconciler(watchlist, catalog)
        reconciler.apply(reconciler.preview(work.work_key))
    if change == "removed_binding":
        watchlist.path.write_text("targets: []\n", encoding="utf-8")
    # Correct work-wide ordinals differ from the second site's local position 1.
    for path, row, prefix in [(archive, artifact, "001"), (archive2, artifact2, "002")]:
        updated = path.rename(path.with_name(f"{prefix}-Series-{1 if prefix == '001' else 2}.zip"))
        catalog.update_artifact_locators({row.id: (row.locator, str(updated))})

    report = audit_existing_archives(catalog, site="mangaone", watchlist=watchlist)

    assert report.work_keys == ("series",)
    if change == "synced":
        assert not report.errors and not report.findings
    else:
        assert report.errors and not report.findings


@pytest.mark.parametrize("args", [[], ["--all", "--site", "mangaone"],
                                  ["--site", "mangaone", "--work-key", "series"]])
def test_audit_cli_requires_exactly_one_selector(args):
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2


def test_audit_cli_json_findings_and_missing_inputs_are_read_only(tmp_path: Path, capsys):
    catalog, _, _, _, _ = graph(tmp_path)
    watchlist = empty_watchlist(tmp_path)
    args = ["--catalog", str(catalog.path), "--watchlist", str(watchlist.path), "--json"]
    assert main([*args, "--site", "mangaone"]) == 1
    assert json.loads(capsys.readouterr().out)["summary"]["findings"] == 1
    assert main([*args, "--site", "absent"]) == 2
    assert "unknown site" in json.loads(capsys.readouterr().out)["errors"][0]
    catalog.path.unlink()
    assert main([*args, "--all"]) == 1
    assert "not found" in json.loads(capsys.readouterr().out)["errors"][0]
    assert not catalog.path.exists()
    watchlist.path.unlink()
    assert main([*args, "--all"]) == 1
    assert not watchlist.path.exists()


def test_audit_clean_cli_returns_zero(tmp_path: Path, capsys):
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    catalog.initialize()
    watchlist = empty_watchlist(tmp_path)
    before = hashlib.sha256(catalog.path.read_bytes()).digest()
    assert main(["--catalog", str(catalog.path), "--watchlist", str(watchlist.path),
                 "--all", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["summary"]["works"] == 0
    assert hashlib.sha256(catalog.path.read_bytes()).digest() == before


@pytest.mark.parametrize("blocked", ["archive", "status"])
def test_audit_reports_inaccessible_history_as_findings(tmp_path, monkeypatch, blocked):
    catalog, work, _, archive, _ = graph(tmp_path)
    watchlist = empty_watchlist(tmp_path)
    status = tmp_path / "crawl-status" / "小説" / "Series" / f"{archive.stem}.json"
    status.parent.mkdir(parents=True)
    status.write_text(json.dumps({"archive_path": str(archive)}), encoding="utf-8")
    original_stat = Path.stat

    def denied(path, *args, **kwargs):
        if path == (archive if blocked == "archive" else status):
            raise PermissionError("synthetic history permission error")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", denied)
    report = audit_existing_archives(catalog, work_key=work.work_key, watchlist=watchlist)
    assert not report.errors
    assert any("cannot be inspected" in finding for finding in report.findings)
