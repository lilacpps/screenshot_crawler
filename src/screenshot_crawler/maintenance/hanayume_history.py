"""Separate history-only Hanayume ZIPs without deleting acquisition history."""

from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from screenshot_crawler.catalog import CatalogService, format_timestamp, now_jst
from screenshot_crawler.catalog.backup import backup_catalog, default_backup_path
from screenshot_crawler.core.packaging import safe_component
from screenshot_crawler.core.progress import atomic_write_json
from screenshot_crawler.maintenance.hanayume_migration import (
    ArchiveProof,
    _digest,
    _verify_file,
    build_migration_plan,
    load_review_report,
    migration_preview_payload,
)
from screenshot_crawler.maintenance.hanayume_repair import HISTORY_KEY_PREFIX
from screenshot_crawler.management.catalog_reader import (
    CatalogInventoryReader,
    catalog_snapshot_identity,
)


class HistoryMoveError(ValueError):
    """An unsafe/stale preview or an interrupted move requiring inspection."""


@dataclass(frozen=True)
class HistoryZip:
    artifact_ids: tuple[int, ...]
    old_locators: tuple[str, ...]
    item_ids: tuple[int, ...]
    title: str
    status: str
    old_path: str
    new_path: str | None
    sha256: str
    size: int
    reason: str


@dataclass(frozen=True)
class HistoryPlan:
    catalog: str
    work_key: str
    library_root: str
    history_root: str
    snapshot_token: str
    projected_migration_token: str | None
    entries: tuple[HistoryZip, ...]
    blockers: tuple[str, ...]
    token: str = ""

    @property
    def ready(self):
        return not self.blockers and self.projected_migration_token is None

    @property
    def moves(self):
        return tuple(e for e in self.entries if e.status == "move")

    def to_dict(self):
        return {**asdict(self), "ready": self.ready,
                "summary": dict(Counter(e.status for e in self.entries)),
                "preserved": ["Item/Source/Target", "CrawlRun snapshots", "quota/resource history", "ZIP bytes and name", "Watchlist"],
                "updated": ["history-only ZIP path", "all matching Artifact.locator values"]}


def _local_path(value) -> Path:
    path = Path(value).absolute()
    if str(path).startswith(("\\\\", "//")):
        raise HistoryMoveError("ネットワークpathは履歴移動に対応しません")
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise HistoryMoveError(f"symlink/junctionを含むpathは移動しません: {path}")
    return path.resolve()


def _journal_path(catalog):
    return Path(str(catalog) + ".hanayume-history-recovery.json")


def _reference_path(locator):
    # Do not contact network shares even while grouping non-selected history.
    if locator.startswith(("\\\\", "//")):
        return locator
    return str(Path(locator).resolve())


def _proof(entry, *, destination=False):
    return ArchiveProof(entry.artifact_ids[0], entry.new_path if destination else entry.old_path,
                        entry.sha256, entry.size)


def build_history_plan(catalog, work_key, *, library_root="output/Books", history_root="output/Books-history", migration=None):
    library, history = _local_path(library_root), _local_path(history_root)
    if library == history or library in history.parents or history in library.parents:
        raise HistoryMoveError("現役libraryと履歴先は互いに内包しない別フォルダを指定してください")
    data = CatalogInventoryReader().read(catalog, include_history=True)
    work = next((w for w in data.works if w.work_key == work_key), None)
    if work is None:
        raise HistoryMoveError("指定作品がCatalogにありません")
    by_item, items = defaultdict(list), {i.id: i for i in data.items}
    for source in data.sources:
        by_item[source.item_id].append(source)
    historical = {s.id for s in data.sources if s.site == "hanayume"
                  and (s.discovery_key or "").startswith(HISTORY_KEY_PREFIX) and not s.acquisition_enabled}
    protected_artifacts = set()
    blockers = []
    if migration is not None:
        if migration.work_key != work_key or Path(migration.catalog).resolve() != Path(catalog).resolve():
            raise HistoryMoveError("移行planと表示対象Catalog/作品が一致しません")
        fresh = build_migration_plan(catalog, migration.watchlist, migration.report,
                                     accepted=migration.accepted, choices=migration.choices)
        if fresh != migration:
            raise HistoryMoveError("移行previewが古くなりました。再作成してください")
        if any(e.action in {"hold", "blocked"} for e in migration.entries):
            raise HistoryMoveError("移行の保留/適用不可を先に解決してください")
        review = load_review_report(migration.report, catalog, migration.watchlist)
        outcomes = migration_preview_payload(migration, review.analysis)["outcomes"]
        historical.update(row["source_id"] for o in outcomes for row in o["history_after"])
        for entry in migration.entries:
            if entry.action == "cover_old":
                protected_artifacts.update(p.artifact_id for p in entry.archives)
    eligible = {item_id for item_id, sources in by_item.items() if items[item_id].work_id == work.id
                and sources and all(s.id in historical for s in sources)}
    # Coverage is a supported durable note written by maintenance, not a new FK.
    prefix = "Hanayume repair: old Artifact coverage (body unproven): "
    for item in data.items:
        if any(s.id not in historical for s in by_item[item.id]):
            for line in (item.note or "").splitlines():
                if prefix in line:
                    if not line.startswith(prefix) or not re.fullmatch(r"\d+(?:,\d+)*", line[len(prefix):]):
                        blockers.append(f"Item #{item.id}: 旧Artifact coverage参照が不明です")
                    else:
                        protected_artifacts.update(map(int, line[len(prefix):].split(",")))
    if any(r.status == "running" and items[r.item_id].work_id == work.id for r in data.latest_runs):
        blockers.append("この作品に実行中CrawlRunがあります")
    if _journal_path(Path(catalog).resolve()).exists():
        blockers.append(f"未解決の移動journalがあります: {_journal_path(Path(catalog).resolve())}")
    groups = defaultdict(list)
    for artifact in data.artifacts:
        if artifact.locator:
            groups[os.path.normcase(_reference_path(artifact.locator))].append(artifact)
        elif artifact.item_id in eligible and artifact.kind == "archive" and artifact.format.lower() == "zip":
            blockers.append(f"Artifact #{artifact.id}: locatorがありません")
    entries = []
    for group in groups.values():
        selected = [a for a in group if items[a.item_id].work_id == work.id
                    and a.kind == "archive" and a.format.lower() == "zip"]
        if not selected:
            continue
        a = selected[0]
        status, destination, reason = "keep_current", None, "現役ItemのZIPを維持"
        if any(a.item_id in eligible for a in selected):
            status, reason = "move", "履歴専用ItemのZIPを別フォルダへ移動"
            if any(a.id in protected_artifacts for a in group):
                status, reason = "keep_current", "現行external Itemが旧Artifact coverageとして利用中"
            elif any(a.item_id not in eligible or a.storage_backend != "filesystem"
                     or a.kind != "archive" or a.format.lower() != "zip" for a in group):
                status, reason = "keep_shared", "他Item/Work/用途のArtifactとpathを共有しているため維持"
        if status == "move":
            try:
                path = _local_path(a.locator)
                if all(Path(x.locator).resolve().is_relative_to(history) for x in group):
                    destination, status, reason = str(path), "already_history", "履歴フォルダへ分離済み"
                elif not path.is_relative_to(library):
                    raise HistoryMoveError("ZIPが指定libraryの外にあります")
                else:
                    destination = str(history / "hanayume" / safe_component(work.work_key, fallback=f"work-{work.id}")
                                      / f"artifact-{min(x.id for x in group)}" / path.name)
                    if _local_path(destination).exists():
                        raise HistoryMoveError("移動先が存在します。上書きしません")
                if any(x.state != "present" or x.sha256 != a.sha256 or x.byte_size != a.byte_size for x in group):
                    raise HistoryMoveError("同pathのArtifact状態/hash/sizeが一致しません")
                if path.stat().st_nlink != 1:
                    raise HistoryMoveError("既存のhardlink共有ZIPは移動しません")
                _verify_file(ArchiveProof(a.id, str(path), a.sha256, a.byte_size))
            except (ValueError, OSError) as exc:
                status, reason = "blocked", str(exc)
                blockers.append(f"Artifact #{a.id}: {exc}")
        entries.append(HistoryZip(tuple(x.id for x in group), tuple(x.locator for x in group),
            tuple(sorted({x.item_id for x in group})), items[a.item_id].order_label or items[a.item_id].item_title or "（話名なし）",
            status, _reference_path(a.locator), destination, a.sha256, a.byte_size, reason))
    plan = HistoryPlan(str(Path(catalog).resolve()), work_key, str(library), str(history),
        catalog_snapshot_identity(data), migration.token if migration is not None else None,
        tuple(entries), tuple(dict.fromkeys(blockers)))
    return replace(plan, token=_digest(asdict(plan)))


@dataclass(frozen=True)
class HistoryMoveResult:
    moved: int
    backup: str | None = None
    manifest: str | None = None
    already_applied: bool = False


def _transfer(old: Path, new: Path):
    """Same-filesystem move; exclusive hardlink creation never overwrites new."""
    _local_path(old)
    _local_path(new)
    new.parent.mkdir(parents=True, exist_ok=True)
    _local_path(new)
    os.link(old, new, follow_symlinks=False)
    old.unlink()


def _restore_files(entries):
    for entry in reversed(entries):
        old, new = Path(entry.old_path), Path(entry.new_path)
        if old.exists():
            _verify_file(_proof(entry))
            if new.exists():
                if not old.samefile(new):
                    raise HistoryMoveError(f"移動先が別ファイルです。自動削除しません: {new}")
                new.unlink()
        elif new.exists():
            _verify_file(_proof(entry, destination=True))
            _transfer(new, old)
            _verify_file(_proof(entry))
        else:
            raise HistoryMoveError(f"復元するZIPがありません: {old} / {new}")


def apply_history_plan(plan: HistoryPlan, *, expected_token: str, backup_dir):
    if not plan.ready or expected_token != plan.token or _digest(asdict(replace(plan, token=""))) != plan.token:
        raise HistoryMoveError("投影preview/古い/改変された履歴移動planは適用できません")
    catalog = CatalogService(plan.catalog)
    moves = plan.moves
    journal = _journal_path(plan.catalog)
    with catalog.job_lock():
        if journal.exists():
            raise HistoryMoveError(f"RECOVERY_REQUIRED: 未解決journalを確認してください: {journal}")
        if moves:
            locators = catalog.read_artifact_locators([id_ for e in moves for id_ in e.artifact_ids])
            if all(locators.get(id_) == e.new_path for e in moves for id_ in e.artifact_ids):
                for e in moves:
                    if Path(e.old_path).exists():
                        raise HistoryMoveError("適用済みDBと元ZIPの存在が矛盾しています")
                    _verify_file(_proof(e, destination=True))
                return HistoryMoveResult(0, already_applied=True)
        fresh = build_history_plan(plan.catalog, plan.work_key, library_root=plan.library_root, history_root=plan.history_root)
        if fresh != plan:
            raise HistoryMoveError("Catalog/ZIP/移動先がpreview後に変わりました。再previewしてください")
        if not moves:
            return HistoryMoveResult(0, already_applied=True)
        backup = backup_catalog(plan.catalog, default_backup_path(plan.catalog, backup_dir))
        manifest = Path(str(backup.backup_path) + ".history-move.json")
        payload = {"state": "prepared", "backup": str(backup.backup_path), "plan": plan.to_dict()}
        attempted = []
        journal_owned = False
        try:
            with catalog._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                if build_history_plan(plan.catalog, plan.work_key, library_root=plan.library_root, history_root=plan.history_root) != plan:
                    raise HistoryMoveError("backup後に移動条件が変わりました")
                with journal.open("x", encoding="utf-8") as stream:
                    journal_owned = True
                    json.dump(payload, stream, ensure_ascii=False, indent=2)
                    stream.flush()
                    os.fsync(stream.fileno())
                atomic_write_json(manifest, payload)
                for entry in moves:
                    _verify_file(_proof(entry))
                    attempted.append(entry)
                    _transfer(Path(entry.old_path), Path(entry.new_path))
                    _verify_file(_proof(entry, destination=True))
                    payload["state"] = "moving"
                    payload["last_artifact_ids"] = entry.artifact_ids
                    atomic_write_json(journal, payload)
                timestamp = format_timestamp(now_jst())
                for entry in moves:
                    for id_, old_locator in zip(entry.artifact_ids, entry.old_locators, strict=True):
                        cursor = connection.execute("UPDATE artifacts SET locator=?,updated_at=? WHERE id=? AND locator=?",
                                                    (entry.new_path, timestamp, id_, old_locator))
                        if cursor.rowcount != 1:
                            raise HistoryMoveError(f"Artifact #{id_}の参照が変わりました")
                if connection.execute("PRAGMA foreign_key_check").fetchone():
                    raise HistoryMoveError("Artifact参照整合性が不正です")
        except BaseException as exc:
            if not journal_owned:
                raise
            try:
                locators = catalog.read_artifact_locators([id_ for e in moves for id_ in e.artifact_ids])
                old_state = all(locators.get(id_) == old for e in moves for id_, old in zip(e.artifact_ids, e.old_locators, strict=True))
                if not old_state:
                    raise HistoryMoveError("DB commit状態が不明です。backup/manifestから明示復旧してください")
                _restore_files(attempted)
                payload["state"] = "rolled_back"
                payload["error"] = str(exc)
                atomic_write_json(manifest, payload)
                journal.unlink()
            except BaseException as recovery:  # noqa: BLE001 - never overclaim rollback
                raise HistoryMoveError(f"RECOVERY_REQUIRED: {recovery}; journal={journal}; manifest={manifest}") from exc
            raise HistoryMoveError(f"移動を中止し、DB/ZIPを復元しました: {exc}; manifest={manifest}") from exc
        try:
            payload["state"] = "completed"
            atomic_write_json(manifest, payload)
            journal.unlink()
        except OSError as exc:
            raise HistoryMoveError(f"RECOVERY_REQUIRED: ZIP/DB更新済み。journal完了処理を確認: {journal}; {exc}") from exc
        return HistoryMoveResult(len(moves), str(backup.backup_path), str(manifest))
