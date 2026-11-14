from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

import screenshot_crawler.maintenance.work_deletion as work_deletion_module
from screenshot_crawler.batch import BatchPlanner
from screenshot_crawler.catalog import (
    ArtifactInput,
    CatalogService,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)
from screenshot_crawler.catalog.models import DiscoveryInventoryPosition
from screenshot_crawler.maintenance.work_deletion import (
    WorkDeletionApplyError,
    WorkDeletionCancelled,
    WorkDeletionCancelToken,
    WorkDeletionPreviewService,
    _namespace,
    register_management_store,
)
from screenshot_crawler.maintenance.work_deletion_gate import check_work_deletion_gate
from screenshot_crawler.site_policies import MangaOneSitePolicy, SitePolicyRegistry
from screenshot_crawler.watchlist.service import WatchlistService


def _setup(tmp_path: Path):
    catalog_path = tmp_path / "catalog.sqlite"
    watchlist_path = tmp_path / "watchlist.yaml"
    library = tmp_path / "Books"
    status = tmp_path / "crawl-status"
    trash = tmp_path / "trash"
    management = tmp_path / "management.sqlite"
    catalog = CatalogService(catalog_path)
    work = catalog.create_work(WorkInput(work_key="work-a", title="同名作品", genre="漫画"))
    other = catalog.create_work(WorkInput(work_key="work-b", title="同名作品", genre="漫画"))

    def add(work_id: int, site: str, key: str, filename: str):
        item = catalog.create_item(ItemInput(item_title=key, status="completed"), work_id=work_id)
        source = catalog.create_source(
            SourceInput(site=site, external_id=key, discovery_key=key, access_mode="free"), item_id=item.id
        )
        target = catalog.create_source_target(
            SourceTargetInput(backend="web", locator=f"https://example.invalid/{key}"), source_id=source.id
        )
        run = catalog.create_crawl_run(item_id=item.id, source_id=source.id, target_id=target.id, access_strategy="direct")
        catalog.mark_crawl_run_succeeded(run.id, page_count=1)
        archive = library / site / filename
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_bytes((f"synthetic {site} {key}").encode())
        artifact = catalog.create_artifact(
            ArtifactInput(
                kind="archive", format="zip", sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                byte_size=archive.stat().st_size, storage_backend="filesystem", locator=str(archive), state="present",
            ), item_id=item.id, crawl_run_id=run.id,
        )
        sidecar = status / site / f"{archive.stem}.json"
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_text(json.dumps({"archive_path": str(archive)}), encoding="utf-8")
        return item, source, target, run, artifact, archive, sidecar

    target_a = add(work.id, "site-a", "a-1", "001-a.zip")
    target_a2 = add(work.id, "site-b", "b-1", "002-b.zip")
    target_b = add(other.id, "site-a", "other-1", "003-other.zip")
    catalog.record_discovery_inventory_evidence(
        work_key="work-a", discovery_key="a-1", site="site-a", target_url="https://example.invalid/a",
        scope_fingerprint="a" * 64, listing_identity="listing-a", positions=(
            DiscoveryInventoryPosition(external_id="a-1", display_position=1),
        ),
    )
    watchlist_path.write_text(yaml.safe_dump({
        "targets": [
            {"key": "a-1", "work_key": "work-a", "site": "site-a", "url": "https://example.invalid/a", "label": "同名作品", "enabled": False},
            {"key": "b-1", "work_key": "work-a", "site": "site-b", "url": "https://example.invalid/b", "label": "同名作品", "enabled": True},
            {"key": "other-1", "work_key": "work-b", "site": "site-a", "url": "https://example.invalid/o", "label": "同名作品", "enabled": True},
        ],
        "archived_work_keys": ["work-a"],
    }, allow_unicode=True), encoding="utf-8")
    management.write_text("", encoding="utf-8")
    # Isolated management schema/registry fixture.  No job is active.
    import sqlite3
    with sqlite3.connect(management) as connection:
        connection.executescript("CREATE TABLE jobs(job_id TEXT, state TEXT, selected_keys_json TEXT);")
    namespace_dir = catalog_path.parent / ".work-deletion" / _namespace(catalog_path)
    namespace_dir.mkdir(parents=True, exist_ok=True)
    (namespace_dir / "management-bindings.json").write_text(json.dumps({
        "catalog_path": str(catalog_path.resolve()), "sealed": True,
        "management_paths": [str(management.resolve())],
    }), encoding="utf-8")
    return {
        "catalog": catalog, "catalog_path": catalog_path, "watchlist": watchlist_path,
        "library": library, "status": status, "trash": trash, "management": management,
        "work": work, "other": other, "target_a": target_a, "target_a2": target_a2, "target_b": target_b,
    }


def _preview(paths, key="work-a", service=None):
    service = service or WorkDeletionPreviewService()
    return service.preview(
        key, catalog_path=paths["catalog_path"], watchlist_path=paths["watchlist"],
        management_paths=[paths["management"]], library_root=paths["library"],
        status_root=paths["status"], trash_root=paths["trash"],
    )


def test_preview_is_immutable_and_lists_full_work_graph(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    file_paths = [paths["catalog_path"], paths["watchlist"], paths["target_a"][5], paths["target_a"][6], paths["target_a2"][5], paths["target_a2"][6], paths["target_b"][5], paths["target_b"][6]]
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in file_paths}
    plan = _preview(paths)
    assert plan.ready
    assert plan.work_id == paths["work"].id
    assert plan.work_title == "同名作品"
    assert plan.site_keys == (("site-a", "a-1"), ("site-b", "b-1"))
    assert len(plan.item_ids) == 2
    assert len(plan.source_ids) == 2
    assert len(plan.source_target_ids) == 2
    assert len(plan.crawl_run_ids) == 2
    assert len(plan.artifact_ids) == 2
    assert plan.discovery_keys == ("a-1",)
    assert plan.discovery_position_count == 1
    assert plan.watchlist_keys == ("a-1", "b-1")
    assert plan.archived
    assert plan.zip_count == 2
    assert all(artifact.move_eligible for artifact in plan.artifacts)
    assert all("<operation-id>" not in (artifact.destination_path or "") for artifact in plan.artifacts)
    assert all("<operation-id>" not in destination for artifact in plan.artifacts for destination in artifact.status_destination_paths)
    assert not paths["trash"].exists()
    for path, (content, mtime) in before.items():
        assert path.read_bytes() == content
        assert path.stat().st_mtime_ns == mtime


def test_delete_then_same_key_re_registration_is_batch_plannable(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    service = WorkDeletionPreviewService()
    plan = _preview(paths, service=service)
    result = service.apply(plan)
    assert result.status == "DONE"
    assert paths["catalog"].find_work("work-a") is None
    assert paths["catalog"].find_work("work-b") is not None
    assert all(not path.exists() for path in (paths["target_a"][5], paths["target_a2"][5]))

    recreated = paths["catalog"].create_work(WorkInput(work_key="work-a", title="同名作品"))
    item = paths["catalog"].create_item(ItemInput(item_title="new episode"), work_id=recreated.id)
    source = paths["catalog"].create_source(
        SourceInput(
            site="mangaone",
            external_id="new-episode",
            discovery_key="new-a",
            access_mode="free",
            available=True,
        ),
        item_id=item.id,
    )
    paths["catalog"].create_source_target(
        SourceTargetInput(backend="web", locator="https://example.invalid/new"),
        source_id=source.id,
    )
    WatchlistService(paths["watchlist"]).add(
        key="new-a", work_key="work-a", site="mangaone",
        url="https://example.invalid/new", label="new-a",
    )
    policies = SitePolicyRegistry()
    policies.register("mangaone", MangaOneSitePolicy)
    batch = BatchPlanner(
        paths["catalog"], policies,
        watchlist=WatchlistService(paths["watchlist"]),
        library_dir=paths["library"],
    ).plan(site="mangaone", selected_keys=("new-a",))
    assert [candidate.external_id for candidate in batch.candidates] == ["new-episode"]
    assert paths["catalog"].find_work("work-b") is not None


def test_preview_token_is_stable_and_changes_after_watchlist_edit(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    first = _preview(paths)
    second = _preview(paths)
    assert first.plan_token == second.plan_token
    raw = yaml.safe_load(paths["watchlist"].read_text(encoding="utf-8"))
    raw["targets"][0]["enabled"] = True
    paths["watchlist"].write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    changed = _preview(paths)
    assert changed.plan_token != first.plan_token
    assert changed.watchlist_revision != first.watchlist_revision


def test_preview_reuses_one_library_status_index_and_per_file_hash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _setup(tmp_path)
    original = paths["target_a"][4]
    paths["catalog"].create_artifact(
        ArtifactInput(kind="archive", format="zip", sha256=original.sha256,
                      byte_size=original.byte_size, storage_backend="filesystem",
                      locator=str(paths["target_a"][5]), state="present"),
        item_id=paths["target_a"][0].id, crawl_run_id=paths["target_a"][3].id,
    )
    sidecar = paths["target_a"][6]
    document = json.loads(sidecar.read_text(encoding="utf-8"))
    document.update(sha256=original.sha256, archive_sha256=original.sha256)
    sidecar.write_text(json.dumps(document), encoding="utf-8")
    counts = {"library": 0, "status": 0, "hash": 0}
    original_library = work_deletion_module._build_library_index
    original_status = work_deletion_module._build_status_index
    original_hash = work_deletion_module._sha256_file

    def library_index(root, **kwargs):
        counts["library"] += 1
        return original_library(root, **kwargs)

    def status_index(root, trash_root, **kwargs):
        counts["status"] += 1
        return original_status(root, trash_root, **kwargs)

    def file_hash(path, **kwargs):
        counts["hash"] += 1
        return original_hash(path, **kwargs)

    monkeypatch.setattr(work_deletion_module, "_build_library_index", library_index)
    monkeypatch.setattr(work_deletion_module, "_build_status_index", status_index)
    monkeypatch.setattr(work_deletion_module, "_sha256_file", file_hash)
    plan = _preview(paths)
    assert plan.ready
    assert counts["library"] == 1
    assert counts["status"] == 1
    # One stable read per ZIP and matching status, independent of the number
    # of Artifact/Run joins that refer to those files.
    assert len(plan.artifacts) == 3
    assert counts["hash"] == 4
    again = _preview(paths)
    assert again.plan_token == plan.plan_token
    assert counts == {"library": 2, "status": 2, "hash": 8}


def test_large_synthetic_preview_has_bounded_index_and_hash_scans(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _setup(tmp_path)
    catalog = paths["catalog"]
    for index in range(32):
        key = f"scale-{index:03d}"
        item = catalog.create_item(ItemInput(item_title=key, status="completed"), work_id=paths["work"].id)
        source = catalog.create_source(
            SourceInput(site="scale", external_id=key, discovery_key=key, access_mode="free"), item_id=item.id
        )
        target = catalog.create_source_target(
            SourceTargetInput(backend="web", locator=f"https://example.invalid/{key}"), source_id=source.id
        )
        run = catalog.create_crawl_run(item_id=item.id, source_id=source.id, target_id=target.id, access_strategy="direct")
        catalog.mark_crawl_run_succeeded(run.id, page_count=1)
        archive = paths["library"] / "scale" / f"{index:03d}-scale.zip"
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_bytes(f"synthetic scale {index}".encode())
        catalog.create_artifact(
            ArtifactInput(
                kind="archive", format="zip", sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                byte_size=archive.stat().st_size, storage_backend="filesystem", locator=str(archive), state="present",
            ), item_id=item.id, crawl_run_id=run.id,
        )
        sidecar = paths["status"] / "scale" / f"{archive.stem}.json"
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_text(json.dumps({"archive_path": str(archive)}), encoding="utf-8")

    counts = {"zip_rglob": 0, "json_rglob": 0, "hash": 0}
    original_rglob = Path.rglob
    original_hash = work_deletion_module._sha256_file

    def counted_rglob(root, pattern):
        if pattern == "*.zip":
            counts["zip_rglob"] += 1
        elif pattern == "*.json":
            counts["json_rglob"] += 1
        return original_rglob(root, pattern)

    def counted_hash(path, **kwargs):
        counts["hash"] += 1
        return original_hash(path, **kwargs)

    monkeypatch.setattr(Path, "rglob", counted_rglob)
    monkeypatch.setattr(work_deletion_module, "_sha256_file", counted_hash)
    plan = _preview(paths)
    assert plan.ready
    assert len(plan.artifacts) == 34
    assert counts["zip_rglob"] == 1
    assert counts["json_rglob"] == 0
    assert counts["hash"] <= len(plan.artifacts) * 2


@pytest.mark.parametrize("cancel_stage", ["filesystem_index", "status_read", "complete"])
def test_preview_cancel_publishes_no_plan_and_writes_nothing(tmp_path: Path, cancel_stage: str) -> None:
    paths = _setup(tmp_path)
    tracked = [paths["catalog_path"], paths["watchlist"], paths["target_a"][5], paths["target_a"][6], paths["target_a2"][5], paths["target_a2"][6]]
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in tracked}
    namespace = paths["catalog_path"].parent / ".work-deletion" / _namespace(paths["catalog_path"])
    namespace_before = {path.name: path.read_bytes() for path in namespace.iterdir()}
    token = WorkDeletionCancelToken()
    events: list[tuple[str, int, int]] = []

    def progress(stage: str, completed: int, total: int, _elapsed: float) -> None:
        events.append((stage, completed, total))
        if stage == cancel_stage:
            token.cancel()

    service = WorkDeletionPreviewService()
    with pytest.raises(WorkDeletionCancelled):
        service.preview(
            "work-a", catalog_path=paths["catalog_path"], watchlist_path=paths["watchlist"],
            management_paths=[paths["management"]], library_root=paths["library"],
            status_root=paths["status"], trash_root=paths["trash"], progress=progress, cancel=token,
        )
    assert events
    assert not service._plans
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in tracked} == before
    assert {path.name: path.read_bytes() for path in namespace.iterdir()} == namespace_before
    assert not paths["trash"].exists()


def test_hash_cancel_is_checked_between_chunks(tmp_path: Path) -> None:
    large = tmp_path / "large.zip"
    large.write_bytes(b"x" * (3 * 1024 * 1024))
    class ChunkCancel:
        calls = 0

        def is_cancelled(self) -> bool:
            self.calls += 1
            return self.calls >= 2

    with pytest.raises(WorkDeletionCancelled):
        work_deletion_module._stable_file_fact(large, cancel=ChunkCancel())


@pytest.mark.parametrize("builder,pattern", [("_build_library_index", "*.zip"), ("_build_status_index", "*.json")])
def test_filesystem_index_cancel_is_checked_per_candidate(
    tmp_path: Path, builder: str, pattern: str
) -> None:
    paths = _setup(tmp_path)

    class CancelAfterOne:
        calls = 0

        def is_cancelled(self) -> bool:
            self.calls += 1
            return self.calls >= 2

    token = CancelAfterOne()
    with pytest.raises(WorkDeletionCancelled):
        if pattern == "*.zip":
            work_deletion_module._build_library_index(paths["library"], cancel=token, started=0.0)
        else:
            work_deletion_module._build_status_index(
                paths["status"], paths["trash"], library_root=paths["library"],
                archive_paths=(paths["target_a"][5], paths["target_a2"][5]), cancel=token, started=0.0,
            )


def test_status_lookup_never_reads_other_paths_or_enumerates_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _setup(tmp_path)
    original_rglob = Path.rglob
    original_read = Path.read_bytes
    unrelated = paths["status"] / "old-placement" / paths["target_a"][6].name
    unrelated.parent.mkdir()
    unrelated.write_bytes(b"{malformed old alias")

    def fail_status_scan(root, pattern):
        if pattern == "*.json":
            raise AssertionError("deletion must not enumerate status JSON")
        return original_rglob(root, pattern)

    def relevant_reads_only(path):
        assert path != unrelated, "unrelated historical status was read"
        return original_read(path)

    monkeypatch.setattr(Path, "rglob", fail_status_scan)
    monkeypatch.setattr(Path, "read_bytes", relevant_reads_only)
    service = WorkDeletionPreviewService()
    plan = _preview(paths, service=service)
    assert plan.ready
    assert len([status for row in plan.artifacts for status in row.status_paths]) == 2
    service.apply(plan)
    assert original_read(unrelated) == b"{malformed old alias"


def test_expected_status_permission_error_is_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _setup(tmp_path)
    original = Path.read_bytes

    def inaccessible(path):
        if path == paths["target_a"][6]:
            raise PermissionError("synthetic denied status")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", inaccessible)
    plan = _preview(paths)
    assert "status_unreadable" in plan.blockers
    assert not plan.ready


@pytest.mark.parametrize("kind", ["directory", "hardlink"])
def test_expected_status_nonregular_or_shared_file_is_blocked(tmp_path: Path, kind: str) -> None:
    paths = _setup(tmp_path)
    sidecar = paths["target_a"][6]
    if kind == "directory":
        sidecar.unlink()
        sidecar.mkdir()
    else:
        os.link(sidecar, paths["status"] / "old-hardlink.json")
    plan = _preview(paths)
    assert "status_path_unsafe" in plan.blockers
    assert not plan.ready


def test_direct_status_missing_keeps_zip_only_preservation(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    paths["target_a"][6].unlink()
    plan = _preview(paths)
    assert plan.ready
    assert any(reason.startswith("status_missing:") for reason in plan.warnings)
    row = next(row for row in plan.artifacts if row.artifact_id == paths["target_a"][4].id)
    assert row.move_eligible and row.status_paths == ()


@pytest.mark.parametrize("state", ["missing", "deleted"])
def test_direct_status_never_derives_from_outside_library_locator(tmp_path: Path, state: str) -> None:
    paths = _setup(tmp_path)
    artifact = paths["target_a"][4]
    paths["catalog"].update_artifact_storage(artifact.id, state=state, locator=str(tmp_path / "outside.zip"))
    plan = _preview(paths)
    assert f"unsafe_artifact_path:{artifact.id}" in plan.blockers
    assert not plan.ready


def test_status_read_cancel_stops_before_reading_next_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _setup(tmp_path)
    token = WorkDeletionCancelToken()
    original = work_deletion_module._read_status_record
    reads = []

    def read_and_cancel(*args):
        reads.append(args[0])
        result = original(*args)
        token.cancel()
        return result

    monkeypatch.setattr(work_deletion_module, "_read_status_record", read_and_cancel)
    with pytest.raises(WorkDeletionCancelled):
        work_deletion_module._build_status_index(
            paths["status"], paths["trash"], library_root=paths["library"],
            archive_paths=(paths["target_a"][5], paths["target_a2"][5]), cancel=token, started=0.0,
        )
    assert len(reads) == 1


@pytest.mark.parametrize("state", ["missing", "deleted"])
def test_missing_archive_with_hashed_status_retains_scan_failure(tmp_path: Path, state: str) -> None:
    paths = _setup(tmp_path)
    artifact = paths["target_a"][4]
    archive, sidecar = paths["target_a"][5:7]
    document = json.loads(sidecar.read_text(encoding="utf-8"))
    document["sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    sidecar.write_text(json.dumps(document), encoding="utf-8")
    paths["catalog"].update_artifact_storage(artifact.id, state=state)
    archive.unlink()
    plan = _preview(paths)
    inspected = next(row for row in plan.artifacts if row.artifact_id == artifact.id)
    assert "status_scan_failed" in inspected.blockers
    assert f"artifact_{state}_status_present:{artifact.id}" in inspected.blockers
    assert inspected.status_paths == (str(sidecar),)
    assert inspected.status_facts == ()
    assert not plan.ready


def test_status_changed_after_index_is_not_used_as_ownership_proof(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    sidecar = paths["target_a"][6]

    def change_after_index(stage, _completed, _total, _elapsed):
        if stage == "filesystem_index":
            sidecar.write_text(json.dumps({"archive_path": str(paths["target_b"][5])}), encoding="utf-8")

    plan = WorkDeletionPreviewService().preview(
        "work-a", catalog_path=paths["catalog_path"], watchlist_path=paths["watchlist"],
        management_paths=[paths["management"]], library_root=paths["library"],
        status_root=paths["status"], trash_root=paths["trash"], progress=change_after_index,
    )
    assert "status_changed_during_hash" in plan.blockers
    assert not plan.ready


def test_catalog_owner_join_has_linear_row_access_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _setup(tmp_path)
    with sqlite3.connect(paths["catalog_path"]) as connection:
        connection.row_factory = sqlite3.Row
        templates = {table: dict(connection.execute(f"SELECT * FROM {table} LIMIT 1").fetchone()) for table in ("works", "items", "artifacts")}

        def clone(table, **updates):
            data = {key: value for key, value in templates[table].items() if key != "id"}
            data.update(updates)
            cursor = connection.execute(
                f"INSERT INTO {table} ({','.join(data)}) VALUES ({','.join('?' for _ in data)})", tuple(data.values())
            )
            return cursor.lastrowid

        for index in range(40):
            owner = clone("works", work_key=f"owner-scale-{index}")
            for _ in range(50):
                item = clone("items", work_id=owner)
                clone("artifacts", item_id=item, crawl_run_id=None)

    accesses = 0

    class CountedRow:
        def __init__(self, row):
            self.row = row

        def keys(self):
            return self.row.keys()

        def __getitem__(self, key):
            nonlocal accesses
            accesses += 1
            assert accesses < 450_000, "Catalog owner lookup repeatedly rescans rows"
            return self.row[key]

    class CountedCursor:
        def __init__(self, cursor):
            self.cursor = cursor

        def fetchall(self):
            return [CountedRow(row) for row in self.cursor.fetchall()]

        def fetchone(self):
            row = self.cursor.fetchone()
            return CountedRow(row) if row is not None else None

    class CountedConnection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, query, *args):
            cursor = self.connection.execute(query, *args)
            return CountedCursor(cursor) if query.startswith("SELECT * FROM ") else cursor

    original = CatalogService._read_only_connection

    @contextmanager
    def counted_connection(self):
        with original(self) as connection:
            yield CountedConnection(connection)

    monkeypatch.setattr(CatalogService, "_read_only_connection", counted_connection)
    graph = WorkDeletionPreviewService._read_catalog(paths["catalog_path"], "work-a")
    assert len(graph["all_artifacts"]) == 2003
    assert not graph["graph_blockers"]



def test_preview_blocks_file_changed_during_hash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _setup(tmp_path)
    original_hash = work_deletion_module._sha256_file

    def hash_then_touch(path: Path, **kwargs) -> str:
        digest = original_hash(path, **kwargs)
        if path.suffix == ".zip":
            stat_result = path.stat()
            os.utime(path, ns=(stat_result.st_atime_ns, stat_result.st_mtime_ns + 1_000_000))
        return digest

    monkeypatch.setattr(work_deletion_module, "_sha256_file", hash_then_touch)
    plan = _preview(paths)
    assert any("artifact_changed_during_hash" in blocker for blocker in plan.blockers)
    assert not plan.ready


def test_watchlist_only_catalog_only_and_not_found_are_distinct(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    watchlist_only = WorkDeletionPreviewService().preview(
        "watch-only", catalog_path=paths["catalog_path"], watchlist_path=paths["watchlist"],
        library_root=paths["library"], status_root=paths["status"], trash_root=paths["trash"],
    )
    assert watchlist_only.work_id is None and "not_found" in watchlist_only.blockers
    raw = yaml.safe_load(paths["watchlist"].read_text(encoding="utf-8"))
    raw["targets"].append({"key": "watch-only", "work_key": "watch-only", "site": "x", "url": "https://example.invalid/x", "label": "watch"})
    paths["watchlist"].write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    watchlist_only = WorkDeletionPreviewService().preview(
        "watch-only", catalog_path=paths["catalog_path"], watchlist_path=paths["watchlist"],
        library_root=paths["library"], status_root=paths["status"], trash_root=paths["trash"],
    )
    assert watchlist_only.work_id is None and watchlist_only.watchlist_keys == ("watch-only",) and watchlist_only.ready
    catalog_only_work = paths["catalog"].create_work(WorkInput(work_key="catalog-only", title="Catalogのみ"))
    catalog_only = _preview(paths, "catalog-only")
    assert catalog_only.work_id == catalog_only_work.id and catalog_only.watchlist_keys == ()
    missing = _preview(paths, "does-not-exist")
    assert "not_found" in missing.blockers and not missing.ready


def test_path_hash_status_and_alias_safety_are_blockers(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    archive = paths["target_a"][5]
    archive.write_bytes(b"tampered")
    plan = _preview(paths)
    assert any("artifact_size_mismatch" in blocker or "artifact_hash_mismatch" in blocker for blocker in plan.blockers)
    archive.write_bytes(b"synthetic site-a a-1")
    sidecar = paths["target_a"][6]
    sidecar.write_text(json.dumps({"archive_path": str(paths["target_a2"][5])}), encoding="utf-8")
    plan = _preview(paths)
    assert "status_mismatch" in plan.blockers
    paths["target_a2"][5].write_bytes(archive.read_bytes())
    plan = _preview(paths)
    assert any("artifact_hash_mismatch" in blocker for blocker in plan.blockers)


def test_unknown_catalog_schema_is_fail_closed(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    with sqlite3.connect(paths["catalog_path"]) as connection:
        connection.execute("CREATE TABLE deletion_extension (work_id INTEGER, note TEXT)")
        connection.execute("ALTER TABLE works ADD COLUMN deletion_tag TEXT")
    plan = _preview(paths)
    assert not plan.ready
    assert any("catalog_unknown_table:deletion_extension" in blocker for blocker in plan.blockers)
    assert any("catalog_unknown_column:works:deletion_tag" in blocker for blocker in plan.blockers)


def test_catalog_non_target_mutation_rolls_back_before_commit(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    with sqlite3.connect(paths["catalog_path"]) as connection:
        connection.execute(
            "CREATE TRIGGER mutate_other_work AFTER DELETE ON works "
            "BEGIN UPDATE works SET title = 'tampered' WHERE work_key = 'work-b'; END"
        )
    service = WorkDeletionPreviewService()
    plan = _preview(paths, service=service)
    with pytest.raises(WorkDeletionApplyError, match="rolled back"):
        service.apply(plan)
    with sqlite3.connect(paths["catalog_path"]) as connection:
        assert connection.execute("SELECT title FROM works WHERE work_key = 'work-b'").fetchone()[0] != "tampered"
        assert connection.execute("SELECT 1 FROM works WHERE work_key = 'work-a'").fetchone() is not None
    assert paths["target_a"][5].is_file()


def test_missing_artifact_with_physical_locator_is_not_treated_as_absent(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    artifact = paths["target_a"][4]
    paths["catalog"].update_artifact_storage(artifact.id, state="missing")

    plan = _preview(paths)

    assert any("artifact_missing_but_present" in blocker for blocker in plan.blockers)
    assert not plan.ready


def test_wal_header_is_fail_closed_even_without_sidecars(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    catalog_path = paths["catalog_path"]
    with sqlite3.connect(catalog_path) as connection:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() == "wal"
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(catalog_path) + suffix)
        if sidecar.exists():
            sidecar.unlink()

    plan = _preview(paths)

    assert "catalog_wal_present" in plan.blockers
    assert not plan.ready


def test_management_wal_header_is_fail_closed_even_without_sidecars(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    management = paths["management"]
    with sqlite3.connect(management) as connection:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() == "wal"
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(management) + suffix)
        if sidecar.exists():
            sidecar.unlink()

    plan = _preview(paths)

    assert any("management_wal_present" in blocker for blocker in plan.blockers)
    assert not plan.ready


def test_non_zip_present_artifact_is_blocked(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    item, _source, _target, run, _artifact, _archive, _sidecar = paths["target_a"]
    image = paths["library"] / "site-a" / "page.png"
    image.write_bytes(b"synthetic image")
    paths["catalog"].create_artifact(
        ArtifactInput(kind="page", format="png", sha256=hashlib.sha256(image.read_bytes()).hexdigest(), byte_size=image.stat().st_size,
                      storage_backend="filesystem", locator=str(image), state="present"), item_id=item.id, crawl_run_id=run.id,
    )
    plan = _preview(paths)
    assert any("unsupported_present_artifact" in blocker for blocker in plan.blockers)


def test_management_registry_missing_is_fail_closed(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    (paths["catalog_path"].parent / ".work-deletion").rename(paths["catalog_path"].parent / ".work-deletion-moved")
    plan = _preview(paths)
    assert "management_store_unbound" in plan.blockers


def test_sealed_registry_is_read_as_a_complete_set(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    second = tmp_path / "management-second.sqlite"
    with sqlite3.connect(second) as connection:
        connection.execute("CREATE TABLE jobs(job_id TEXT, state TEXT, selected_keys_json TEXT)")
    registry = paths["catalog_path"].parent / ".work-deletion" / _namespace(paths["catalog_path"]) / "management-bindings.json"
    registry.write_text(json.dumps({
        "catalog_path": str(paths["catalog_path"].resolve()), "sealed": True,
        "management_paths": [str(paths["management"].resolve()), str(second.resolve())],
    }), encoding="utf-8")
    plan = _preview(paths)
    assert "management_store_binding_mismatch" in plan.blockers
    assert str(second.resolve()) in plan.management_paths


def test_gate_is_checked_before_watchlist_only_preview(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    gate = paths["catalog_path"].parent / ".work-deletion" / _namespace(paths["catalog_path"])
    (gate / "active.json").write_text(json.dumps({"phase": "active", "operation": "old"}), encoding="utf-8")
    raw = yaml.safe_load(paths["watchlist"].read_text(encoding="utf-8"))
    raw["targets"].append({"key": "watch-only", "work_key": "watch-only", "site": "x", "url": "https://example.invalid/x", "label": "watch"})
    paths["watchlist"].write_text(yaml.safe_dump(raw), encoding="utf-8")
    plan = WorkDeletionPreviewService().preview(
        "watch-only", catalog_path=paths["catalog_path"], watchlist_path=paths["watchlist"],
        library_root=paths["library"], status_root=paths["status"], trash_root=paths["trash"],
    )
    assert "deletion_in_progress" in plan.blockers


def test_malformed_same_stem_status_is_fail_closed(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    paths["target_a"][6].write_text("not-json", encoding="utf-8")
    plan = _preview(paths)
    assert "status_malformed" in plan.blockers


def test_existing_operation_directory_is_a_collision(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    first = _preview(paths)
    operation_dir = paths["trash"] / first.plan_token
    operation_dir.mkdir(parents=True)
    (operation_dir / "unexpected.bin").write_bytes(b"untracked")
    second = _preview(paths)
    assert "destination_collision" in second.blockers
    assert second.destination_fingerprint not in {"missing", "unsafe"}


def test_preview_does_not_change_catalog_or_management_wal(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    catalog_connection = sqlite3.connect(paths["catalog_path"])
    management_connection = sqlite3.connect(paths["management"])
    try:
        catalog_connection.execute("PRAGMA journal_mode=WAL")
        catalog_connection.execute("CREATE TABLE IF NOT EXISTS wal_probe(value TEXT)")
        catalog_connection.execute("INSERT INTO wal_probe VALUES ('catalog')")
        catalog_connection.commit()
        management_connection.execute("PRAGMA journal_mode=WAL")
        management_connection.execute("INSERT INTO jobs VALUES ('done', 'completed', '{}')")
        management_connection.commit()
        files = sorted(set(paths["catalog_path"].parent.rglob("catalog.sqlite*")) | set(paths["management"].parent.rglob("management.sqlite*")))
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in files}
        plan = _preview(paths)
        assert not plan.ready
        assert "catalog_wal_present" in plan.blockers or any(blocker.startswith("management_wal_present:") for blocker in plan.blockers)
        after = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in files}
        assert after == before
    finally:
        catalog_connection.close()
        management_connection.close()


def test_same_work_exact_duplicate_locator_warns_and_moves_once(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    _item, _source, _target, run, artifact, archive, _sidecar = paths["target_a"]
    paths["catalog"].create_artifact(
        ArtifactInput(
            kind="archive", format="zip", sha256=artifact.sha256, byte_size=artifact.byte_size,
            storage_backend="filesystem", locator=str(archive), state="present",
        ), item_id=artifact.item_id, crawl_run_id=run.id,
    )
    plan = _preview(paths)
    duplicate_rows = [entry for entry in plan.artifacts if entry.source_path == str(archive.resolve())]
    assert len(duplicate_rows) == 2
    assert sum(entry.move_eligible for entry in duplicate_rows) == 1
    assert any("artifact_duplicate_reference" in warning for warning in plan.warnings)
    assert not any("artifact_duplicate_conflict" in blocker for blocker in plan.blockers)


@pytest.mark.parametrize("state", ["succeeded", "partial", "failed", "cancelled", "completed", "aborted"])
def test_terminal_management_history_does_not_block_or_stale_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    paths = _setup(tmp_path)
    with sqlite3.connect(paths["management"]) as connection:
        connection.execute("ALTER TABLE jobs ADD COLUMN request_json TEXT")
        connection.execute("ALTER TABLE jobs ADD COLUMN summary_json TEXT")
    before = _preview(paths)
    with sqlite3.connect(paths["management"]) as connection:
        connection.execute("INSERT INTO jobs VALUES ('done', ?, '{}', '{bad', '{bad')", (state,))
    error = paths["management"].parent / "logs" / "done" / "supervision-error.json"
    error.parent.mkdir(parents=True)
    error.write_text("{bad", encoding="utf-8")
    original = Path.read_bytes

    def no_history_logs(path):
        assert "logs" not in path.parts, "completed job logs should not be read"
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", no_history_logs)
    plan = _preview(paths)
    assert plan.ready
    assert plan.plan_token == before.plan_token
    with sqlite3.connect(paths["management"]) as connection:
        connection.execute("UPDATE jobs SET summary_json = ?", (json.dumps({"status": "unknown"}),))
    assert _preview(paths).plan_token == plan.plan_token


def test_queued_job_blocks_without_requiring_worker_identity(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    with sqlite3.connect(paths["management"]) as connection:
        connection.execute("ALTER TABLE jobs ADD COLUMN request_json TEXT")
        connection.execute("INSERT INTO jobs VALUES ('waiting', 'queued', '[]', ?)",
                           (json.dumps({"catalog_path": str(paths["catalog_path"])}),))
    plan = _preview(paths)
    assert plan.blockers == ("active_job:waiting:queued",)
    assert not plan.ready


@pytest.mark.parametrize("registered_field", [None, "worker_pid", "worker_start_token", "started_at"])
def test_idle_reservation_is_not_a_writer_but_startup_registration_blocks(
    tmp_path: Path, registered_field: str | None
) -> None:
    paths = _setup(tmp_path)
    with sqlite3.connect(paths["management"]) as connection:
        for name, kind in (("request_json", "TEXT"), ("worker_pid", "INTEGER"),
                           ("worker_start_token", "TEXT"), ("started_at", "TEXT")):
            connection.execute(f"ALTER TABLE jobs ADD COLUMN {name} {kind}")
    service = WorkDeletionPreviewService()
    before = _preview(paths, service=service)
    with sqlite3.connect(paths["management"]) as connection:
        connection.execute("INSERT INTO jobs(job_id,state,selected_keys_json,request_json) VALUES ('old','queued','[]',?)",
                           (json.dumps({"catalog_path": str(paths["catalog_path"])}),))
        if registered_field is not None:
            value = 4242 if registered_field == "worker_pid" else "registered"
            connection.execute(f"UPDATE jobs SET {registered_field}=? WHERE job_id='old'", (value,))
    plan = _preview(paths, service=service)
    if registered_field is None:
        assert plan.ready
        assert plan.plan_token == before.plan_token
        with sqlite3.connect(paths["management"]) as connection:
            assert connection.execute("SELECT state FROM jobs WHERE job_id='old'").fetchone()[0] == "queued"
            connection.execute("UPDATE jobs SET state='running',worker_pid=4242,worker_start_token='claimed'")
        with pytest.raises(WorkDeletionApplyError):
            service.apply(plan)
        assert paths["target_a"][5].exists()
        assert not paths["trash"].exists()
    else:
        assert "active_job:old:queued" in plan.blockers
        assert not plan.ready


@pytest.mark.parametrize("entry", ["admission", "catalog"])
def test_worker_claim_after_fresh_preview_cannot_pass_deletion_admission(tmp_path: Path, entry: str) -> None:
    paths = _setup(tmp_path)
    with sqlite3.connect(paths["management"]) as connection:
        for name, kind in (("request_json", "TEXT"), ("worker_pid", "INTEGER"),
                           ("worker_start_token", "TEXT"), ("started_at", "TEXT")):
            connection.execute(f"ALTER TABLE jobs ADD COLUMN {name} {kind}")
        connection.execute("INSERT INTO jobs(job_id,state,selected_keys_json,request_json) VALUES ('old','queued','[]',?)",
                           (json.dumps({"catalog_path": str(paths["catalog_path"])}),))
    service = WorkDeletionPreviewService()
    plan = _preview(paths, service=service)
    archive = paths["target_a"][5]
    before = (paths["catalog_path"].read_bytes(), paths["watchlist"].read_bytes(), archive.read_bytes())
    observed = []

    def claim_and_try_start(checkpoint):
        if checkpoint != "after_manifest":
            return
        with sqlite3.connect(paths["management"]) as connection:
            connection.execute("UPDATE jobs SET state='running',worker_pid=4242,worker_start_token='claimed'")
        script = """
import asyncio,sys
from screenshot_crawler.management.job_worker import run_job
from screenshot_crawler.execution_worker import _run
if sys.argv[3] == 'admission':
    asyncio.run(run_job('old', {'catalog_path':sys.argv[1]}, worker_token='claimed', job_dir=sys.argv[2]))
else:
    # The child may have passed its admission check before deletion began.
    # Its actual execution path must still be excluded by the Catalog lock.
    asyncio.run(_run({'action':'discover', 'catalog_path':sys.argv[1], 'plan_fingerprint':'fixture',
        'sites':['site-a'], 'selected_keys':['a-1'], 'keys_by_site':{'site-a':['a-1']}}))
"""
        job_dir = tmp_path / "blocked-child"
        job_dir.mkdir()
        result = subprocess.run([sys.executable, "-c", script, str(paths["catalog_path"]), str(job_dir), entry],
                                cwd=tmp_path, capture_output=True, timeout=20, check=False)
        assert result.returncode != 0
        assert b"CatalogJobLockError" in result.stderr
        assert not list(job_dir.iterdir()), "worker wrote before passing deletion admission"
        assert (paths["catalog_path"].read_bytes(), paths["watchlist"].read_bytes(), archive.read_bytes()) == before
        observed.append(True)
        raise RuntimeError("fixture stops after the blocked startup")

    with pytest.raises(WorkDeletionApplyError):
        service.apply(plan, failure_hook=claim_and_try_start)
    assert observed
    assert (paths["catalog_path"].read_bytes(), paths["watchlist"].read_bytes(), archive.read_bytes()) == before


@pytest.mark.parametrize("scenario,expected", [
    ("dead", None), ("split_dead", None), ("reused", None),
    ("live", "live"), ("unknown_start", "unverified"),
    ("missing_identity", "unverified"), ("wrong_token", "unverified"),
    ("launcher_alive", "unverified"),
])
def test_interrupted_job_requires_worker_exit_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str, expected: str | None
) -> None:
    paths = _setup(tmp_path)
    launcher = 4321 if scenario in {"split_dead", "launcher_alive"} else 4242
    with sqlite3.connect(paths["management"]) as connection:
        for name, kind in (("request_json", "TEXT"), ("worker_pid", "INTEGER"), ("worker_start_token", "TEXT")):
            connection.execute(f"ALTER TABLE jobs ADD COLUMN {name} {kind}")
    before = _preview(paths)
    with sqlite3.connect(paths["management"]) as connection:
        connection.execute("INSERT INTO jobs VALUES ('old', 'interrupted', '[]', ?, ?, 'test-token')",
                           (json.dumps({"catalog_path": str(paths["catalog_path"])}), launcher))
    job_dir = paths["management"].parent / "logs" / "old"
    job_dir.mkdir(parents=True)
    (job_dir / "supervision-error.json").write_text("{bad", encoding="utf-8")
    if scenario != "missing_identity":
        (job_dir / "worker.identity").write_text(json.dumps({
            "pid": 4242, "token": "wrong" if scenario == "wrong_token" else "test-token",
            "start_identity": "original-start",
        }), encoding="utf-8")
    current = {"alive": scenario in {"live", "reused", "unknown_start"}}
    monkeypatch.setattr(work_deletion_module, "process_is_alive",
                        lambda pid: current["alive"] if pid == 4242 else scenario == "launcher_alive")
    monkeypatch.setattr(work_deletion_module, "process_start_identity", lambda _pid:
                        None if scenario == "unknown_start" else "new-start" if scenario == "reused" else "original-start")
    service = WorkDeletionPreviewService()
    plan = _preview(paths, service=service)
    if expected is None:
        assert plan.ready
        assert plan.plan_token == before.plan_token
    else:
        assert f"management_worker_{expected}:old" in plan.blockers
        assert not plan.ready
    if scenario == "dead":
        current["alive"] = True
        with pytest.raises(WorkDeletionApplyError):
            service.apply(plan)
        assert not paths["trash"].exists()
        assert paths["target_a"][5].exists()


def test_status_archive_path_traversal_is_blocked_before_resolve(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    sidecar = paths["target_a"][6]
    sidecar.write_text(json.dumps({"archive_path": "crawl-status/../Books/site-a/001-a.zip"}), encoding="utf-8")
    plan = _preview(paths)
    assert "status_path_unsafe" in plan.blockers
    assert not plan.ready


def test_relative_locator_keeps_existing_cwd_semantics_for_custom_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _setup(tmp_path)
    custom_catalog_path = tmp_path / "catalog-state" / "catalog.sqlite"
    custom_catalog_path.parent.mkdir()
    custom_catalog_path.write_bytes(paths["catalog_path"].read_bytes())
    paths["catalog_path"] = custom_catalog_path
    paths["catalog"] = CatalogService(custom_catalog_path)
    namespace_dir = custom_catalog_path.parent / ".work-deletion" / _namespace(custom_catalog_path)
    namespace_dir.mkdir(parents=True, exist_ok=True)
    (namespace_dir / "management-bindings.json").write_text(json.dumps({
        "catalog_path": str(custom_catalog_path.resolve()), "sealed": True,
        "management_paths": [str(paths["management"].resolve())],
    }), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    relative_archive_a = Path("Books/site-a/001-a.zip").as_posix()
    relative_archive_b = Path("Books/site-b/002-b.zip").as_posix()
    with sqlite3.connect(custom_catalog_path) as connection:
        connection.execute("UPDATE artifacts SET locator = ? WHERE id = ?", (relative_archive_a, paths["target_a"][4].id))
        connection.execute("UPDATE artifacts SET locator = ? WHERE id = ?", (relative_archive_b, paths["target_a2"][4].id))
    paths["target_a"][6].write_text(json.dumps({"archive_path": relative_archive_a}), encoding="utf-8")
    paths["target_a2"][6].write_text(json.dumps({"archive_path": relative_archive_b}), encoding="utf-8")
    plan = _preview(paths)
    assert plan.ready
    assert plan.artifacts[0].source_path == str(paths["target_a"][5].resolve())
    assert plan.artifacts[1].source_path == str(paths["target_a2"][5].resolve())


def test_apply_moves_files_deletes_only_target_graph_and_patches_watchlist(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    service = WorkDeletionPreviewService()
    plan = _preview(paths, service=service)
    result = service.apply(plan)
    assert result.status == "DONE"
    assert not paths["target_a"][5].exists()
    assert not paths["target_a"][6].exists()
    assert not paths["target_a2"][5].exists()
    assert not paths["target_a2"][6].exists()
    assert paths["target_b"][5].exists()
    assert paths["target_b"][6].exists()
    assert paths["catalog"].find_work("work-a") is None
    assert paths["catalog"].find_work("work-b") is not None
    document = paths["watchlist"].read_text(encoding="utf-8")
    assert "work-a" not in document and "other-1" in document
    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert manifest["phase"] == "DONE"
    assert manifest["watchlist_before"]["revision"] == plan.watchlist_revision
    assert manifest["watchlist_after"]["revision"] != plan.watchlist_revision
    assert all(intent["state"] == "VERIFIED" for intent in manifest["intents"])
    before_copy = Path(manifest["watchlist_before_path"])
    assert before_copy.exists()
    assert hashlib.sha256(before_copy.read_bytes()).hexdigest() == manifest["watchlist_before"]["sha256"]


def test_apply_normal_exception_restores_files_and_leaves_rollback_manifest(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    service = WorkDeletionPreviewService()
    plan = _preview(paths, service=service)
    def fail(checkpoint: str) -> None:
        if checkpoint == "after_each_move":
            raise RuntimeError("injected move failure")
    with pytest.raises(WorkDeletionApplyError, match="rolled back"):
        service.apply(plan, failure_hook=fail)
    assert paths["target_a"][5].exists() and paths["target_a"][6].exists()
    assert paths["catalog"].find_work("work-a") is not None
    operations = sorted(paths["trash"].iterdir())
    assert len(operations) == 1
    assert json.loads((operations[0] / "manifest.json").read_text(encoding="utf-8"))["phase"] == "ROLLED_BACK"


def test_apply_after_catalog_commit_reports_recovery_required(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    service = WorkDeletionPreviewService()
    plan = _preview(paths, service=service)
    def fail(checkpoint: str) -> None:
        if checkpoint == "after_catalog_commit":
            raise RuntimeError("injected post-commit failure")
    with pytest.raises(WorkDeletionApplyError, match="recovery"):
        service.apply(plan, failure_hook=fail)
    assert paths["catalog"].find_work("work-a") is None
    operation = next(paths["trash"].iterdir())
    assert json.loads((operation / "manifest.json").read_text(encoding="utf-8"))["phase"] == "RECOVERY_REQUIRED"


def test_apply_observes_commit_when_hook_raises_immediately_after_commit(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    service = WorkDeletionPreviewService()
    plan = _preview(paths, service=service)
    def fail(checkpoint: str) -> None:
        if checkpoint == "catalog_commit_returned":
            raise RuntimeError("commit acknowledgement lost")
    with pytest.raises(WorkDeletionApplyError, match="recovery"):
        service.apply(plan, failure_hook=fail)
    assert paths["catalog"].find_work("work-a") is None
    operation = next(paths["trash"].iterdir())
    assert json.loads((operation / "manifest.json").read_text(encoding="utf-8"))["phase"] == "RECOVERY_REQUIRED"


@pytest.mark.parametrize("checkpoint", ["after_manifest", "after_backup", "before_catalog_commit"])
def test_apply_precommit_checkpoints_restore_files(tmp_path: Path, checkpoint: str) -> None:
    paths = _setup(tmp_path)
    service = WorkDeletionPreviewService()
    plan = _preview(paths, service=service)
    def fail(current: str) -> None:
        if current == checkpoint:
            raise RuntimeError(f"injected {checkpoint}")
    with pytest.raises(WorkDeletionApplyError, match="rolled back"):
        service.apply(plan, failure_hook=fail)
    assert paths["target_a"][5].exists() and paths["target_a"][6].exists()
    assert paths["catalog"].find_work("work-a") is not None
    operation = next(paths["trash"].iterdir())
    assert json.loads((operation / "manifest.json").read_text(encoding="utf-8"))["phase"] == "ROLLED_BACK"


def test_apply_watchlist_cas_failure_after_db_commit_is_recovery(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    service = WorkDeletionPreviewService()
    plan = _preview(paths, service=service)
    def fail(checkpoint: str) -> None:
        if checkpoint == "before_watchlist_replace":
            paths["watchlist"].write_text(paths["watchlist"].read_text(encoding="utf-8") + "# external\n", encoding="utf-8")
    with pytest.raises(WorkDeletionApplyError, match="recovery"):
        service.apply(plan, failure_hook=fail)
    assert paths["catalog"].find_work("work-a") is None
    operation = next(paths["trash"].iterdir())
    assert json.loads((operation / "manifest.json").read_text(encoding="utf-8"))["phase"] == "RECOVERY_REQUIRED"


def test_apply_watchlist_disappearance_after_replace_is_recovery(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    service = WorkDeletionPreviewService()
    plan = _preview(paths, service=service)

    def fail(checkpoint: str) -> None:
        if checkpoint == "after_watchlist_replace":
            paths["watchlist"].unlink()

    with pytest.raises(WorkDeletionApplyError, match="recovery"):
        service.apply(plan, failure_hook=fail)
    assert paths["catalog"].find_work("work-a") is None
    operation = next(paths["trash"].iterdir())
    manifest = json.loads((operation / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["phase"] == "RECOVERY_REQUIRED"
    assert (paths["catalog_path"].parent / ".work-deletion" / _namespace(paths["catalog_path"]) / "active.json").exists()


def test_apply_reserves_active_before_manifest_and_gates_preview(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    service = WorkDeletionPreviewService()
    plan = _preview(paths, service=service)
    observed: dict[str, bool] = {}

    def fail(checkpoint: str) -> None:
        if checkpoint != "after_active_reservation":
            return
        namespace_dir = paths["catalog_path"].parent / ".work-deletion" / _namespace(paths["catalog_path"])
        observed["active"] = (namespace_dir / "active.json").is_file()
        observed["manifest"] = (paths["trash"] / plan.plan_token / "manifest.json").exists()
        blocked = WorkDeletionPreviewService().preview(
            "work-a", catalog_path=paths["catalog_path"], watchlist_path=paths["watchlist"],
            management_paths=[paths["management"]], library_root=paths["library"],
            status_root=paths["status"], trash_root=paths["trash"],
        )
        observed["gated"] = "deletion_in_progress" in blocked.blockers and not blocked.ready
        raise RuntimeError("injected reservation failure")

    with pytest.raises(WorkDeletionApplyError):
        service.apply(plan, failure_hook=fail)
    assert observed == {"active": True, "manifest": False, "gated": True}
    assert not (paths["catalog_path"].parent / ".work-deletion" / _namespace(paths["catalog_path"]) / "active.json").exists()
    assert paths["catalog"].find_work("work-a") is not None


def test_apply_stops_without_writes_when_operation_directory_races_after_preview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _setup(tmp_path)
    service = WorkDeletionPreviewService()
    plan = _preview(paths, service=service)
    original_preview = service.preview
    call_count = 0
    raced_dir = paths["trash"] / plan.plan_token

    def preview_with_race(*args, **kwargs):
        nonlocal call_count
        result = original_preview(*args, **kwargs)
        call_count += 1
        if call_count == 1:
            raced_dir.mkdir(parents=True)
            (raced_dir / "external-marker").write_bytes(b"unrelated")
        return result

    monkeypatch.setattr(service, "preview", preview_with_race)
    with pytest.raises(WorkDeletionApplyError, match="operation directory collision"):
        service.apply(plan)
    assert (raced_dir / "external-marker").read_bytes() == b"unrelated"
    assert not (raced_dir / "manifest.json").exists()
    namespace_dir = paths["catalog_path"].parent / ".work-deletion" / _namespace(paths["catalog_path"])
    assert not (namespace_dir / "active.json").exists()
    assert paths["catalog"].find_work("work-a") is not None
    assert paths["target_a"][5].exists()


def test_apply_rejects_stale_plan_without_mutation(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    service = WorkDeletionPreviewService()
    plan = _preview(paths, service=service)
    raw = yaml.safe_load(paths["watchlist"].read_text(encoding="utf-8"))
    raw["targets"][0]["enabled"] = not raw["targets"][0]["enabled"]
    paths["watchlist"].write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(WorkDeletionApplyError, match="stale"):
        service.apply(plan)
    assert paths["target_a"][5].exists()
    assert paths["catalog"].find_work("work-a") is not None


def test_apply_rejects_same_bytes_path_replacement_by_strong_identity(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    service = WorkDeletionPreviewService()
    plan = _preview(paths, service=service)
    archive = paths["target_a"][5]
    content = archive.read_bytes()
    archive.unlink()
    archive.write_bytes(content)
    with pytest.raises(WorkDeletionApplyError, match="stale"):
        service.apply(plan)
    assert archive.exists()
    assert paths["catalog"].find_work("work-a") is not None


def test_apply_uses_fresh_locked_plan_not_mutated_incoming_work_id(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    service = WorkDeletionPreviewService()
    plan = _preview(paths, service=service)
    forged = replace(plan, work_id=paths["other"].id)
    with pytest.raises(WorkDeletionApplyError, match="canonical"):
        service.apply(forged)
    assert paths["catalog"].find_work("work-a") is not None
    assert paths["catalog"].find_work("work-b") is not None


def test_apply_rejects_missing_or_shared_artifact_before_backup(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    paths["target_a"][5].unlink()
    service = WorkDeletionPreviewService()
    plan = _preview(paths, service=service)
    assert not plan.ready and any("artifact_present_missing" in blocker for blocker in plan.blockers)
    with pytest.raises(WorkDeletionApplyError):
        service.apply(plan)
    assert not paths["trash"].exists()

    paths = _setup(tmp_path / "shared")
    _item, _source, _target, run, _artifact, archive, _sidecar = paths["target_b"]
    paths["catalog"].create_artifact(
        ArtifactInput(
            kind="archive", format="zip", sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
            byte_size=archive.stat().st_size, storage_backend="filesystem", locator=str(paths["target_a"][5]), state="present",
        ), item_id=run.item_id, crawl_run_id=run.id,
    )
    shared_plan = _preview(paths)
    assert any("artifact_shared_path" in blocker for blocker in shared_plan.blockers)


def test_apply_retains_manual_missing_artifact_id_in_catalog_delete(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    item = paths["target_a"][0]
    paths["catalog"].create_artifact(
        ArtifactInput(
            kind="manual", format="note", sha256="0" * 64, byte_size=0,
            storage_backend="external", locator=None, state="missing",
        ), item_id=item.id, crawl_run_id=None,
    )
    service = WorkDeletionPreviewService()
    plan = _preview(paths, service=service)
    assert any(artifact.kind == "manual" and artifact.state == "missing" for artifact in plan.artifacts)
    service.apply(plan)
    assert paths["catalog"].find_work("work-a") is None


def test_apply_watchlist_only_does_not_create_catalog_or_touch_other_work(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    paths["catalog_path"].unlink()
    raw = yaml.safe_load(paths["watchlist"].read_text(encoding="utf-8"))
    raw["targets"] = [{"key": "watch-only", "work_key": "watch-only", "site": "x", "url": "https://example.invalid/x", "label": "watch"}, *raw["targets"]]
    raw["archived_work_keys"] = ["watch-only"]
    paths["watchlist"].write_text(yaml.safe_dump(raw), encoding="utf-8")
    service = WorkDeletionPreviewService()
    plan = service.preview(
        "watch-only", catalog_path=paths["catalog_path"], watchlist_path=paths["watchlist"],
        library_root=paths["library"], status_root=paths["status"], trash_root=paths["trash"],
    )
    assert plan.ready
    result = service.apply(plan)
    assert result.status == "DONE"
    assert not paths["catalog_path"].exists()
    assert paths["target_b"][5].exists()
    assert "watch-only" not in paths["watchlist"].read_text(encoding="utf-8")


def test_watchlist_only_requires_bound_management_and_blocks_queued_job(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    paths["catalog_path"].unlink()
    raw = yaml.safe_load(paths["watchlist"].read_text(encoding="utf-8"))
    raw["targets"].append({"key": "watch-only", "work_key": "watch-only", "site": "x", "url": "https://example.invalid/x", "label": "watch"})
    paths["watchlist"].write_text(yaml.safe_dump(raw), encoding="utf-8")
    bound = WorkDeletionPreviewService().preview(
        "watch-only", catalog_path=paths["catalog_path"], watchlist_path=paths["watchlist"],
        library_root=paths["library"], status_root=paths["status"], trash_root=paths["trash"],
    )
    assert bound.ready
    (paths["catalog_path"].parent / ".work-deletion").rename(paths["catalog_path"].parent / ".work-deletion-missing")
    unbound = WorkDeletionPreviewService().preview(
        "watch-only", catalog_path=paths["catalog_path"], watchlist_path=paths["watchlist"],
        library_root=paths["library"], status_root=paths["status"], trash_root=paths["trash"],
    )
    assert "management_store_unbound" in unbound.blockers and not unbound.ready

    paths = _setup(tmp_path / "queued")
    paths["catalog_path"].unlink()
    raw = yaml.safe_load(paths["watchlist"].read_text(encoding="utf-8"))
    raw["targets"].append({"key": "watch-only", "work_key": "watch-only", "site": "x", "url": "https://example.invalid/x", "label": "watch"})
    paths["watchlist"].write_text(yaml.safe_dump(raw), encoding="utf-8")
    with sqlite3.connect(paths["management"]) as connection:
        connection.execute("INSERT INTO jobs VALUES ('future', 'queued', '{\"work_key\": \"watch-only\"}')")
    queued = WorkDeletionPreviewService().preview(
        "watch-only", catalog_path=paths["catalog_path"], watchlist_path=paths["watchlist"],
        library_root=paths["library"], status_root=paths["status"], trash_root=paths["trash"],
    )
    assert "active_job:future:queued" in queued.blockers and not queued.ready


def test_apply_catalog_only_does_not_create_watchlist(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    paths["watchlist"].unlink()
    service = WorkDeletionPreviewService()
    plan = service.preview(
        "work-a", catalog_path=paths["catalog_path"], watchlist_path=paths["watchlist"],
        management_paths=[paths["management"]], library_root=paths["library"],
        status_root=paths["status"], trash_root=paths["trash"],
    )
    assert plan.ready and plan.watchlist_keys == ()
    result = service.apply(plan.plan_token)
    assert result.status == "DONE"
    assert not paths["watchlist"].exists()
    assert paths["target_b"][5].exists()


def test_apply_preserves_watchlist_comment_and_crlf(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    original = paths["watchlist"].read_text(encoding="utf-8")
    crlf = "# preserve this comment\r\n" + original.replace("\n", "\r\n")
    with paths["watchlist"].open("w", encoding="utf-8", newline="") as stream:
        stream.write(crlf)
    service = WorkDeletionPreviewService()
    result = service.apply(_preview(paths, service=service))
    assert result.status == "DONE"
    written = paths["watchlist"].read_bytes()
    assert b"# preserve this comment\r\n" in written
    assert b"\r\n" in written and b"\n" not in written.replace(b"\r\n", b"")


def test_apply_deletes_quota_and_scope_rows_with_the_work(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    with sqlite3.connect(paths["catalog_path"]) as connection:
        connection.execute(
            "INSERT INTO quota_resource_states(work_id, site, resource, last_consumed_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (paths["work"].id, "site-a", "synthetic", "2026-01-01T00:00:00+09:00", "2026-01-01T00:00:00+09:00", "2026-01-01T00:00:00+09:00"),
        )
        connection.execute(
            "INSERT INTO acquisition_scope_sync(work_id, fingerprint, definition_fingerprint, configuration_json, status, synced_at) VALUES (?, ?, ?, ?, ?, ?)",
            (paths["work"].id, "f" * 64, "d" * 64, "{}", "synced", "2026-01-01T00:00:00+09:00"),
        )
    service = WorkDeletionPreviewService()
    result = service.apply(_preview(paths, service=service))
    assert result.status == "DONE"
    with sqlite3.connect(paths["catalog_path"]) as connection:
        assert connection.execute("SELECT 1 FROM quota_resource_states WHERE work_id = ?", (paths["work"].id,)).fetchone() is None
        assert connection.execute("SELECT 1 FROM acquisition_scope_sync WHERE work_id = ?", (paths["work"].id,)).fetchone() is None


def test_recover_rolls_forward_after_catalog_commit_and_is_idempotent(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    service = WorkDeletionPreviewService()
    plan = _preview(paths, service=service)

    def fail(checkpoint: str) -> None:
        if checkpoint == "after_catalog_commit":
            raise RuntimeError("simulated process interruption")

    with pytest.raises(WorkDeletionApplyError, match="recovery"):
        service.apply(plan, failure_hook=fail)
    first = service.recover(
        paths["catalog_path"], paths["watchlist"], paths["trash"],
        management_paths=[paths["management"]], operation_id=plan.plan_token,
    )
    assert first.status == "DONE"
    assert paths["catalog"].find_work("work-a") is None
    assert "work-a" not in paths["watchlist"].read_text(encoding="utf-8")
    active = paths["catalog_path"].parent / ".work-deletion" / _namespace(paths["catalog_path"]) / "active.json"
    assert not active.exists()
    second = service.recover(
        paths["catalog_path"], paths["watchlist"], paths["trash"],
        management_paths=[paths["management"]], operation_id=plan.plan_token,
    )
    assert second.status == "DONE"


def test_recover_hot_journal_after_catalog_delete_transaction_isolated(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    script = """
import os, sqlite3, sys
from pathlib import Path
from screenshot_crawler.catalog.service import CatalogService
from screenshot_crawler.maintenance.work_deletion import WorkDeletionPreviewService
root = Path(sys.argv[1])
catalog_path = root / 'catalog.sqlite'
with sqlite3.connect(catalog_path) as connection:
    connection.executemany(
        'INSERT INTO works(work_key,title,author,genre,created_at,updated_at) VALUES(?,?,?,?,?,?)',
        [(f'padding-{index}', 'padding', None, None, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00') for index in range(500)],
    )
def kill_before_commit(self, *args, **kwargs):
    del args, kwargs
    with sqlite3.connect(self.path) as connection:
        connection.execute('PRAGMA cache_size=5')
        connection.execute('BEGIN IMMEDIATE')
        connection.execute("UPDATE works SET title = title || 'x'")
        os._exit(76)
CatalogService.delete_work_records = kill_before_commit
service = WorkDeletionPreviewService()
plan = service.preview('work-a', catalog_path=catalog_path, watchlist_path=root / 'watchlist.yaml',
    management_paths=[root / 'management.sqlite'], library_root=root / 'Books',
    status_root=root / 'crawl-status', trash_root=root / 'trash')
service.apply(plan)
"""
    completed = subprocess.run([sys.executable, "-c", script, str(tmp_path)], cwd=tmp_path, check=False)
    assert completed.returncode == 76
    journal = Path(str(paths["catalog_path"]) + "-journal")
    assert journal.is_file()
    before_files = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    before_catalog = (paths["catalog_path"].read_bytes(), paths["catalog_path"].stat().st_mtime_ns)
    dry = WorkDeletionPreviewService().recover(
        paths["catalog_path"], paths["watchlist"], paths["trash"],
        management_paths=[paths["management"]], dry_run=True,
    )
    assert dry.status == "RECOVERY_REQUIRED"
    assert (paths["catalog_path"].read_bytes(), paths["catalog_path"].stat().st_mtime_ns) == before_catalog
    assert sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*")) == before_files
    recovered = WorkDeletionPreviewService().recover(
        paths["catalog_path"], paths["watchlist"], paths["trash"],
        management_paths=[paths["management"]], dry_run=False,
    )
    assert recovered.status == "ROLLED_BACK"
    assert not journal.exists()
    assert paths["target_a"][5].is_file()
    assert paths["target_b"][5].is_file()


def test_recover_rejects_tampered_catalog_backup_fact(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    service = WorkDeletionPreviewService()
    plan = _preview(paths, service=service)

    def fail(checkpoint: str) -> None:
        if checkpoint == "after_backup":
            raise RuntimeError("synthetic interruption")

    with pytest.raises(WorkDeletionApplyError):
        service.apply(plan, failure_hook=fail)
    manifest = next(paths["trash"].glob("*/manifest.json"))
    backup = manifest.parent / "catalog-before.sqlite"
    backup.write_bytes(backup.read_bytes() + b"tamper")
    result = service.recover(
        paths["catalog_path"], paths["watchlist"], paths["trash"],
        management_paths=[paths["management"]], operation_id=manifest.parent.name, dry_run=True,
    )
    assert result.status == "RECOVERY_REQUIRED"


def test_recover_dry_run_diagnoses_manifestless_active_reservation(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    gate = paths["catalog_path"].parent / ".work-deletion" / _namespace(paths["catalog_path"])
    gate.joinpath("active.json").write_text(json.dumps({"phase": "active", "operation_id": "orphan"}), encoding="utf-8")
    result = WorkDeletionPreviewService().recover(
        paths["catalog_path"], paths["watchlist"], paths["trash"],
        management_paths=[paths["management"]], operation_id="orphan", dry_run=True,
    )
    assert result.status == "RECOVERY_REQUIRED"
    assert "manifest" in result.details[0]
    assert gate.joinpath("active.json").exists()


def test_recover_rejects_manifest_active_marker_alias(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    service = WorkDeletionPreviewService()
    plan = _preview(paths, service=service)

    def fail(checkpoint: str) -> None:
        if checkpoint == "after_catalog_commit":
            raise RuntimeError("synthetic interruption")

    with pytest.raises(WorkDeletionApplyError):
        service.apply(plan, failure_hook=fail)
    manifest = next(paths["trash"].glob("*/manifest.json"))
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["active_marker"] = str(tmp_path / "other-active.json")
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(WorkDeletionApplyError, match="namespace"):
        service.recover(
            paths["catalog_path"], paths["watchlist"], paths["trash"],
            management_paths=[paths["management"]], operation_id=manifest.parent.name, dry_run=True,
        )


def test_management_bind_is_explicit_cas_and_runtime_gate_is_read_only(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    service = WorkDeletionPreviewService()
    registry = paths["catalog_path"].parent / ".work-deletion" / _namespace(paths["catalog_path"]) / "management-bindings.json"
    registry.unlink()
    first = service.bind_management_stores(paths["catalog_path"], [paths["management"]])
    assert first["sealed"] is True
    second = service.bind_management_stores(paths["catalog_path"], [paths["management"]], expected_revision=first["revision"])
    assert second["revision"] == first["revision"]
    gate = registry.parent
    (gate / "active.json").write_text(json.dumps({"phase": "active"}), encoding="utf-8")
    assert check_work_deletion_gate(paths["catalog_path"]) == ("deletion_in_progress",)
    (gate / "active.json").write_text("{}", encoding="utf-8")
    assert check_work_deletion_gate(paths["catalog_path"]) == ("deletion_in_progress",)
    (gate / "active.json").write_text("[]", encoding="utf-8")
    assert check_work_deletion_gate(paths["catalog_path"]) == ("deletion_gate_malformed",)


def test_shared_management_store_filters_jobs_by_effective_catalog(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    other_catalog = tmp_path / "other-catalog.sqlite"
    management = paths["management"]
    with sqlite3.connect(management) as connection:
        connection.execute("ALTER TABLE jobs ADD COLUMN request_json TEXT")
        connection.execute(
            "INSERT INTO jobs(job_id, state, selected_keys_json, request_json) VALUES(?,?,?,?)",
            ("other-running", "running", "[]", json.dumps({"catalog_path": str(other_catalog)})),
        )
    plan = _preview(paths)
    assert plan.ready

    with sqlite3.connect(management) as connection:
        connection.execute(
            "UPDATE jobs SET request_json = ? WHERE job_id = ?",
            (json.dumps({"catalog_path": str(paths["catalog_path"])}), "other-running"),
        )
    blocked = _preview(paths)
    assert any("active_job:other-running" in blocker for blocker in blocked.blockers)


def test_runtime_management_registration_unseals_only_when_new_store_is_added(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    second = tmp_path / "management-second.sqlite"
    with sqlite3.connect(second) as connection:
        connection.execute("CREATE TABLE jobs(job_id TEXT, state TEXT, selected_keys_json TEXT)")
    registry = paths["catalog_path"].parent / ".work-deletion" / _namespace(paths["catalog_path"]) / "management-bindings.json"
    first = register_management_store(paths["catalog_path"], paths["management"])
    assert first["sealed"] is True
    expanded = register_management_store(paths["catalog_path"], second)
    assert expanded["sealed"] is False
    assert str(second.resolve()) in expanded["management_paths"]
    registry.write_text(json.dumps(expanded), encoding="utf-8")


def test_recover_true_subprocess_exit_after_catalog_commit(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    script = """
import os, sys
from pathlib import Path
from screenshot_crawler.maintenance.work_deletion import WorkDeletionPreviewService
root = Path(sys.argv[1])
service = WorkDeletionPreviewService()
plan = service.preview('work-a', catalog_path=root / 'catalog.sqlite', watchlist_path=root / 'watchlist.yaml',
    management_paths=[root / 'management.sqlite'], library_root=root / 'Books',
    status_root=root / 'crawl-status', trash_root=root / 'trash')
def stop(checkpoint):
    if checkpoint == 'after_catalog_commit':
        os._exit(73)
service.apply(plan, failure_hook=stop)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        cwd=tmp_path, check=False,
    )
    assert completed.returncode == 73
    operation_id = next(paths["trash"].iterdir()).name
    result = WorkDeletionPreviewService().recover(
        paths["catalog_path"], paths["watchlist"], paths["trash"],
        management_paths=[paths["management"]], operation_id=operation_id,
    )
    assert result.status == "DONE"


@pytest.mark.parametrize("checkpoint, expected", [("after_each_move", "ROLLED_BACK"), ("watchlist_replace_returned", "DONE")])
def test_recover_true_subprocess_exit_at_mixed_cutover_checkpoints(tmp_path: Path, checkpoint: str, expected: str) -> None:
    paths = _setup(tmp_path)
    script = """
import os, sys
from pathlib import Path
from screenshot_crawler.maintenance.work_deletion import WorkDeletionPreviewService
root = Path(sys.argv[1]); checkpoint = sys.argv[2]
service = WorkDeletionPreviewService()
plan = service.preview('work-a', catalog_path=root / 'catalog.sqlite', watchlist_path=root / 'watchlist.yaml',
    management_paths=[root / 'management.sqlite'], library_root=root / 'Books',
    status_root=root / 'crawl-status', trash_root=root / 'trash')
def stop(current):
    if current == checkpoint:
        os._exit(74)
service.apply(plan, failure_hook=stop)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path), checkpoint],
        cwd=tmp_path, check=False,
    )
    assert completed.returncode == 74
    operation_id = next(paths["trash"].iterdir()).name
    result = WorkDeletionPreviewService().recover(
        paths["catalog_path"], paths["watchlist"], paths["trash"],
        management_paths=[paths["management"]], operation_id=operation_id,
    )
    assert result.status == expected


@pytest.mark.parametrize(
    "checkpoint, expected",
    [
        ("after_active_reservation", "RECOVERY_REQUIRED"),
        ("after_manifest", "ROLLED_BACK"),
        ("after_backup", "ROLLED_BACK"),
        ("before_each_move", "ROLLED_BACK"),
        ("after_move_before_verified", "ROLLED_BACK"),
        ("catalog_commit_returned", "DONE"),
        ("before_watchlist_replace", "DONE"),
        ("after_watchlist_replace", "DONE"),
    ],
)
def test_recover_process_exit_fault_matrix(tmp_path: Path, checkpoint: str, expected: str) -> None:
    paths = _setup(tmp_path)
    script = """
import os, sys
from pathlib import Path
from screenshot_crawler.maintenance.work_deletion import WorkDeletionPreviewService
root = Path(sys.argv[1]); checkpoint = sys.argv[2]
service = WorkDeletionPreviewService()
plan = service.preview('work-a', catalog_path=root / 'catalog.sqlite', watchlist_path=root / 'watchlist.yaml',
    management_paths=[root / 'management.sqlite'], library_root=root / 'Books',
    status_root=root / 'crawl-status', trash_root=root / 'trash')
def stop(current):
    if current == checkpoint:
        os._exit(75)
service.apply(plan, failure_hook=stop)
"""
    completed = subprocess.run([sys.executable, "-c", script, str(tmp_path), checkpoint], cwd=tmp_path, check=False)
    assert completed.returncode == 75
    operation_id = next(paths["trash"].iterdir()).name
    result = WorkDeletionPreviewService().recover(
        paths["catalog_path"], paths["watchlist"], paths["trash"],
        management_paths=[paths["management"]], operation_id=operation_id,
    )
    assert result.status == expected
