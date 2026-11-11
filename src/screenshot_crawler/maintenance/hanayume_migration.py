"""Explicit, backed-up Hanayume repair; no viewer, capture or archive writes.

Human acceptance of a report authorizes using old acquisitions. It never
turns a metadata guess into a technical proof of equal episode bodies.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from screenshot_crawler.catalog import CatalogService, format_timestamp, now_jst
from screenshot_crawler.catalog.backup import backup_catalog, default_backup_path
from screenshot_crawler.maintenance.hanayume_repair import (
    HISTORY_KEY_PREFIX,
    RepairAnalysis,
    RepairLink,
    load_analysis,
    validate_pair,
)
from screenshot_crawler.maintenance.source_identity import (
    SourceIdentityError,
    SourceIdentityMaintenance,
    SourceIdentityPlan,
)
from screenshot_crawler.management.catalog_reader import CatalogInventoryReader
from screenshot_crawler.watchlist.fingerprints import (
    configuration_json,
    work_definition_fingerprint,
    work_scope_fingerprint,
)
from screenshot_crawler.watchlist.service import WatchlistService


class RepairMigrationError(ValueError):
    """Unsafe, unresolved or stale review; no mutation is permitted."""


class ArchiveReuseError(RepairMigrationError):
    """Existing files cannot safely supply the selected acquisition."""


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RepairMigrationError(f"JSONの重複key: {key}")
        result[key] = value
    return result


@dataclass(frozen=True)
class ReviewReport:
    path: str
    digest: str
    analysis: RepairAnalysis


def load_review_report(path, catalog, watchlist) -> ReviewReport:
    path = Path(path).resolve()
    if not path.is_file() or path.stat().st_size > 20_000_000:
        raise RepairMigrationError("報告JSONが存在しないか、20MB上限を超えています")
    raw = path.read_bytes()
    if len(raw) > 20_000_000:
        raise RepairMigrationError("報告JSONが20MB上限を超えています")
    try:
        payload = json.loads(raw, object_pairs_hook=_unique_object)
        if (type(payload.get("version")) is not int or payload["version"] != 1
                or payload.get("stage") != "01-read-only"):
            raise RepairMigrationError("Stage 01 version 1の報告JSONを指定してください")
        saved = payload["analysis"]
        work_key = saved["work"]["work_key"]
        if not isinstance(work_key, str) or not work_key:
            raise RepairMigrationError("報告のwork_keyが不正です")
        current = load_analysis(catalog, watchlist, work_key)
        entries = saved["entries"]
        if not isinstance(entries, list) or len(entries) > 10000:
            raise RepairMigrationError("報告のSource一覧が不正です")
        ids = [e["source"]["id"] for e in entries]
        if any(type(s) is not int or s <= 0 for s in ids) or len(set(ids)) != len(ids):
            raise RepairMigrationError("報告のSource IDが重複または不正です")
        if (_digest(saved["work"]) != _digest(asdict(current.work))
                or _digest(saved["targets"]) != _digest([asdict(t) for t in current.targets])
                or _digest(sorted(entries, key=lambda e: e["source"]["id"])) != _digest(
                    sorted([asdict(e) for e in current.entries], key=lambda e: e["source"]["id"]))):
            raise RepairMigrationError("報告後にこの作品のCatalog/Watchlistが変わりました。再解析してください")
        old, new = {e.source.id for e in current.old}, {e.source.id for e in current.current}
        links, used = [], set()
        if not isinstance(saved["links"], list) or len(saved["links"]) > 10000:
            raise RepairMigrationError("報告の対応一覧が不正です")
        for link in saved["links"]:
            a, b = link["old_ids"], link["new_ids"]
            for values, pool in ((a, old), (b, new)):
                if (not isinstance(values, list) or len(values) > 500
                        or any(type(s) is not int or s not in pool for s in values)
                        or len(set(values)) != len(values)):
                    raise RepairMigrationError("対応のSourceが他作品・別の側・不正IDです")
            if not (a or b) or used.intersection(a + b):
                raise RepairMigrationError("対応のSourceが空または複数グループで重複しています")
            used.update(a + b)
            for i in a:
                for j in b:
                    validate_pair(current, i, j)
            decision, evidence = link["decision"], link["evidence"]
            reasons = link["reasons"]
            if (decision not in {"review", "mapped", "hold", "reacquire", "retire"}
                    or evidence not in {"heuristic", "api_identity", "manual"}
                    or not isinstance(reasons, list) or len(reasons) > 100
                    or any(not isinstance(r, str) or len(r) > 4000 for r in reasons)):
                raise RepairMigrationError("対応の判断・根拠が不正です")
            links.append(RepairLink(tuple(a), tuple(b), evidence, tuple(reasons), decision,
                                    link.get("match_rule")))
        # Never trust the serialized summary or API evidence as body proof.
        return ReviewReport(str(path), hashlib.sha256(raw).hexdigest(), replace(
            current, links=tuple(links), observations=(), diagnostics=current.diagnostics + (
                "保存報告の対応は現在の作品graphと照合済み。本文同一性の証明ではありません。",)))
    except (KeyError, TypeError, AttributeError, json.JSONDecodeError, UnicodeError) as exc:
        raise RepairMigrationError(f"報告JSONの形式が不正です: {exc}") from exc


@dataclass(frozen=True)
class ArchiveProof:
    artifact_id: int
    path: str
    sha256: str
    size: int


def _verify_file(proof: ArchiveProof) -> None:
    path = Path(proof.path)
    if not path.is_file() or path.stat().st_size != proof.size:
        raise ArchiveReuseError(f"ZIPの存在/サイズが一致しません: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        size = 0
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            if size > proof.size:
                raise ArchiveReuseError(f"ZIPが検証中に変化しました: {path}")
            digest.update(chunk)
    if size != proof.size or digest.hexdigest() != proof.sha256:
        raise ArchiveReuseError(f"ZIPのSHA-256が一致しません: {path}")
    try:
        with ZipFile(path) as archive:
            if not archive.infolist():
                raise ArchiveReuseError(f"空のZIPです: {path}")
    except BadZipFile as exc:
        raise ArchiveReuseError(f"ZIP形式が不正です: {path}") from exc


def _usable_archive(entry) -> ArchiveProof:
    target_ids = {t.id for t in entry.targets}
    succeeded = {r.id for r in entry.runs if r.status == "succeeded"
                 and r.item_id == entry.item.id and r.target_id in target_ids}
    candidates = sorted((a for a in entry.artifacts if a.format.lower() == "zip"
                         and a.kind == "archive" and a.storage_backend == "filesystem"),
                        key=lambda a: a.id, reverse=True)
    # Match the current Artifact projection; never silently substitute an
    # older file for a missing or corrupt latest acquisition.
    if not candidates:
        raise ArchiveReuseError(f"ZIP記録がありません: Source {entry.source.id}")
    a = candidates[0]
    if a.state != "present" or not a.locator or a.crawl_run_id not in succeeded:
        raise ArchiveReuseError(f"最新ZIPの存在状態/成功Run対応が不正です: Source {entry.source.id}")
    if a.locator.startswith(("\\\\", "//")):
        raise ArchiveReuseError("ネットワークZIPはこのStageで再利用できません")
    # Relative locators follow the existing CLI/renumber working-directory rule.
    path = Path(a.locator).resolve()
    proof = ArchiveProof(a.id, str(path), a.sha256, a.byte_size)
    try:
        _verify_file(proof)
    except OSError as exc:
        raise ArchiveReuseError(f"ZIPを検証できません: {path}: {exc}") from exc
    return proof


def _old_group_archives(entries) -> list[ArchiveProof]:
    """A shared Item is one acquisition; its latest run must belong to this group."""
    by_item = {}
    for entry in entries:
        by_item.setdefault(entry.item.id, []).append(entry)
    proofs = []
    for aliases in by_item.values():
        errors = []
        for entry in aliases:
            try:
                proofs.append(_usable_archive(entry))
                break
            except ArchiveReuseError as exc:
                errors.append(str(exc))
        else:
            raise ArchiveReuseError("同Itemの最新ZIPを採用した旧Source群から検証できません: " + errors[0])
    return proofs


@dataclass(frozen=True)
class MigrationEntry:
    group_id: str
    old_ids: tuple[int, ...]
    new_ids: tuple[int, ...]
    requested: str
    action: str
    reasons: tuple[str, ...]
    archives: tuple[ArchiveProof, ...] = ()
    identity: SourceIdentityPlan | None = None
    delete_old_pending_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class MigrationPlan:
    catalog: str
    watchlist: str
    report: str
    report_digest: str
    work_key: str
    work_id: int
    snapshot_token: str
    watchlist_revision: str
    accepted: bool
    choices: tuple[tuple[str, str], ...]
    entries: tuple[MigrationEntry, ...]
    receipt_item_ids: tuple[int, ...]
    blockers: tuple[str, ...]
    operation_id: str
    token: str

    @property
    def ready(self):
        return not self.blockers

    def to_dict(self):
        return {**asdict(self), "ready": self.ready, "summary": dict(Counter(e.action for e in self.entries)),
                "migration_policy_version": 2,
                "body_equality_proven": False,
                "preserved": ["CrawlRun", "Artifact", "quota/resource history", "existing ZIP bytes", "Watchlist"]}


def entry_outcome(analysis: RepairAnalysis, entry: MigrationEntry) -> dict:
    """Describe the planned graph, including the exact donor rows to remove.

    This is presentation only. Generated alias IDs cannot be promised before
    the transaction and are deliberately left unspecified.
    """
    by_id = {e.source.id: e for e in analysis.entries}
    old, new = [by_id[s] for s in entry.old_ids], [by_id[s] for s in entry.new_ids]
    resolved = entry.action not in {"hold", "blocked"}
    deleted = {"item_ids": [], "source_ids": [], "target_ids": []}
    added, current, historical = [], [], []

    def current_row(item_entry, source_entry, source_id, *, origin, status=None):
        return {"item_id": item_entry.item.id, "source_id": source_id,
                "status": status or item_entry.item.status, "origin": origin,
                "title": item_entry.title, "external_id": source_entry.source.external_id,
                "url": source_entry.url, "discovery_key": source_entry.source.discovery_key,
                "acquisition_enabled": source_entry.source.acquisition_enabled,
                "display_position": source_entry.source.display_position}

    if entry.action == "reuse_identity":
        identity = entry.identity
        assert identity is not None
        current.append(current_row(old[0], new[0], identity.old_source_id, origin="old"))
        deleted = {"item_ids": [identity.donor_item_id], "source_ids": [identity.donor_source_id],
                   "target_ids": [t.id for e in new for t in e.targets]}
        added.append({"kind": "history_alias", "source_id": None, "target_id": None,
                      "item_id": old[0].item.id, "external_id": old[0].source.external_id,
                      "url": old[0].url, "discovery_key": HISTORY_KEY_PREFIX + old[0].source.discovery_key,
                      "acquisition_enabled": False, "quota_duplicated": False,
                      "id_assignment": "適用時に新規採番"})
    else:
        status = {"cover_old": "external", "reacquire": "pending"}.get(entry.action)
        current.extend(current_row(e, e, e.source.id, origin="new", status=status) for e in new)
        if resolved:
            historical.extend({"source_id": e.source.id, "item_id": e.item.id,
                "status": e.item.status, "external_id": e.source.external_id,
                "discovery_key": HISTORY_KEY_PREFIX + e.source.discovery_key,
                "acquisition_enabled": False} for e in old if e.source.id not in entry.delete_old_pending_ids)
        removed_old = [e for e in old if e.source.id in entry.delete_old_pending_ids]
        deleted = {"item_ids": [e.item.id for e in removed_old],
                   "source_ids": [e.source.id for e in removed_old],
                   "target_ids": [t.id for e in removed_old for t in e.targets]}
    deleted = {key: sorted(value for value in values if value is not None)
               for key, values in deleted.items()}
    kept = {"item_ids": sorted({e.item.id for e in old + new} - set(deleted["item_ids"])),
            "source_ids": sorted(set(entry.old_ids + entry.new_ids) - set(deleted["source_ids"])),
            "target_ids": sorted({t.id for e in old + new for t in e.targets} - set(deleted["target_ids"]))}
    return {"group_id": entry.group_id, "action": entry.action, "resolved": resolved,
            "current_after": current, "history_after": historical, "keep": kept, "delete": deleted,
            "add": added, "adopted_archives": [asdict(p) for p in entry.archives],
            "deleted_old_pending_source_ids": list(entry.delete_old_pending_ids),
            "preserved_run_ids": sorted({r.id for e in old + new for r in e.runs}),
            "preserved_artifact_ids": sorted({a.id for e in old + new for a in e.artifacts}),
            "zip_files_deleted_or_overwritten": False}


def migration_preview_payload(plan: MigrationPlan, analysis: RepairAnalysis) -> dict:
    if plan.work_id != analysis.work.id or plan.work_key != analysis.work.work_key:
        raise RepairMigrationError("表示対象の作品と移行planが一致しません")
    outcomes = [entry_outcome(analysis, entry) for entry in plan.entries]
    statuses = {row["item_id"]: row["status"] for result in outcomes for row in result["current_after"]}
    deletions = {kind: sorted({value for result in outcomes for value in result["delete"][kind]})
                 for kind in ("item_ids", "source_ids", "target_ids")}
    return {**plan.to_dict(), "outcomes": outcomes,
            "after_summary": {"resolved": all(o["resolved"] for o in outcomes),
                "current_item_statuses": dict(Counter(statuses.values())), "delete": deletions,
                "historical_source_count": sum(len(o["history_after"]) for o in outcomes),
                "deleted_old_pending_source_count": sum(len(e.delete_old_pending_ids) for e in plan.entries),
                "deleted_new_donor_source_count": sum(len(o["delete"]["source_ids"]) for o in outcomes
                                                       if o["action"] == "reuse_identity"),
                "new_history_alias_count": sum(len(o["add"]) for o in outcomes)}}


def _pending_retention_reason(entry, data) -> str | None:
    """Only an unacquired, unedited old Item with a single Source is disposable."""
    item, source = entry.item, entry.source
    if item.status != "pending" or item.completed_at is not None or source.available:
        return "未取得の旧pendingではありません"
    if item.item_title is not None or item.note is not None:
        return "手動タイトル/noteがあります"
    if source.quota_started_at is not None or source.access_granted_until is not None or source.access_mode == "owned":
        return "利用履歴/取得権利があります"
    if any(s.item_id == item.id and s.id != source.id for s in data.sources):
        return "同じItemを参照する別Sourceがあります"
    target_ids = {t.id for t in entry.targets}
    if any(r.item_id == item.id or r.source_id == source.id or r.target_id in target_ids for r in data.latest_runs):
        return "CrawlRun履歴があります"
    if any(a.item_id == item.id for a in data.artifacts):
        return "Artifact履歴があります"
    if any(t.backend != "web" or t.target_key != "default" or t.priority != 100 or not t.enabled for t in entry.targets):
        return "Targetの個別設定があります"
    return None


def report_groups(analysis):
    links = list(analysis.links)
    covered = {s for link in links for s in link.old_ids + link.new_ids}
    links.extend(RepairLink((e.source.id,), (), "manual", ("未対応の旧Source",), "hold")
                 for e in analysis.old if e.source.id not in covered)
    links.extend(RepairLink((), (e.source.id,), "manual", ("新側のみ",))
                 for e in analysis.current if e.source.id not in covered)
    return tuple((_digest([link.old_ids, link.new_ids])[:20], link) for link in links)


def build_migration_plan(catalog, watchlist, report, *, accepted=False, choices=()) -> MigrationPlan:
    if type(accepted) is not bool:
        raise RepairMigrationError("採用確認はboolで指定してください")
    review = load_review_report(report, catalog, watchlist)
    a = review.analysis
    by_id = {e.source.id: e for e in a.entries}
    groups = report_groups(a)
    choices = tuple(sorted(choices))
    requested_by_group = dict(choices)
    allowed = {"auto", "old", "new", "reacquire", "hold", "retire"}
    if (len(requested_by_group) != len(choices) or set(requested_by_group) - {g for g, _ in groups}
            or any(v not in allowed for v in requested_by_group.values())):
        raise RepairMigrationError("移行方針のgroup IDまたは指定が不正です")
    entries, blockers, receipt_ids, removed_items = [], [], set(), set()
    if not accepted:
        blockers.append("報告の対応関係と旧データ利用方針を人間の判断として採用してください")
    # One snapshot includes running histories from other sites in the Work too.
    data = CatalogInventoryReader().read(catalog, include_history=True)
    work_items = {i.id for i in data.items if i.work_id == a.work.id}
    if any(r.status == "running" and r.item_id in work_items for r in data.latest_runs):
        blockers.append("この作品に実行中CrawlRunがあります")
    all_work_targets = tuple(t for t in WatchlistService(watchlist).read_document().targets
                             if t.work_key == a.work.work_key)
    targets_by_key = {t.key: t for t in all_work_targets}
    for group_id, link in groups:
        requested = requested_by_group.get(group_id, "auto")
        old, new = [by_id[s] for s in link.old_ids], [by_id[s] for s in link.new_ids]
        policy = requested
        if policy == "auto":
            policy = {"hold": "hold", "reacquire": "reacquire", "retire": "retire"}.get(link.decision, "auto")
        reasons, proofs, identity, delete_old = [], [], None, ()
        action = "use_new" if new else "hold"
        try:
            for e in new:
                target = targets_by_key.get(e.source.discovery_key)
                if target is None or target.site != "hanayume":
                    raise RepairMigrationError("新Sourceのhanayume Watchlist bindingがありません")
            for e in old:
                target = targets_by_key.get(e.source.discovery_key)
                if target is None or target.site != "hanayume":
                    raise RepairMigrationError("旧Sourceの現在Watchlist bindingがありません")
                history_key = HISTORY_KEY_PREFIX + target.key
                if history_key in targets_by_key:
                    raise RepairMigrationError("履歴用keyが現行Watchlistと衝突しています")
                scope = target.discovery_scope
                if scope and (e.url in (scope.from_url, scope.through_url)
                              or e.source.external_id in scope.excluded_external_ids):
                    raise RepairMigrationError("旧IDを含むscope境界/除外は先に再設定が必要です")
                if any(e.source.external_id in (seg.start_external_id, seg.end_external_id)
                       for seg in target.archive_segments or ()):
                    raise RepairMigrationError("旧IDを含むarchive_segments境界は先に再設定が必要です")
            if policy == "hold":
                action = "hold"
            elif policy == "retire":
                if not old or new:
                    raise RepairMigrationError("履歴保管は対応無しの旧側だけに指定してください")
                action = "retire"
            elif not new:
                raise RepairMigrationError("未対応旧Sourceを履歴保管するか、GUIで対応を指定してください")
            elif policy == "reacquire":
                action = "reacquire"
            elif policy == "new":
                action = "use_new"
            elif policy == "old" or (old and all(e.item.status == "completed" for e in old)
                                      and all(e.item.status == "pending" for e in new)):
                if not old or not all(e.item.status == "completed" for e in old):
                    raise RepairMigrationError("旧側の全範囲がcompletedではありません")
                if not all(e.item.status == "pending" for e in new):
                    raise RepairMigrationError("旧採用は新側が全件pendingの場合に指定してください")
                proofs = _old_group_archives(old)
                action = "cover_old"
                if len(old) == len(new) == 1 and sum(s.item_id == old[0].item.id for s in data.sources) == 1:
                    try:
                        identity = SourceIdentityMaintenance(catalog).plan(
                            site="hanayume", work_key=a.work.work_key,
                            old_external_id=old[0].source.external_id,
                            new_external_id=new[0].source.external_id, new_locator=new[0].url,
                            reason="Human accepted repair report; body equality unproven",
                            body_revision_possible=True)
                        action = "reuse_identity"
                    except SourceIdentityError as exc:
                        if policy == "auto":
                            action, proofs = "use_new", []
                            reasons.append(f"donorを統合できないため新側を採用: {exc}")
                        else:
                            reasons.append(f"donorは保持し、旧取得参照をexternalで記録: {exc}")
            if action == "use_new":
                # Existing completed is adopted only with a usable archive.
                for e in new:
                    if e.item.status == "completed":
                        try:
                            proofs.append(_usable_archive(e))
                        except RepairMigrationError as exc:
                            action = "reacquire"
                            reasons.append(f"新completedのZIPを利用できないため再取得: {exc}")
            if action in {"cover_old", "reacquire"}:
                changing = {e.item.id for e in new if e.item.status != ("external" if action == "cover_old" else "pending")}
                if any(s.item_id in changing and s.id not in link.new_ids for s in data.sources):
                    raise RepairMigrationError("Itemに別Sourceがあるため取得状態を変更できません")
            if action == "hold":
                blockers.append(f"{group_id}: 保留を解決してください")
            else:
                # No acquisition or user data exists to preserve in a pristine
                # old pending row. Keep the current identity and remove only
                # these obsolete rows, with exact IDs bound into the plan.
                if action in {"use_new", "reacquire"} and new and all(e.item.status == "pending" for e in new):
                    deletable = []
                    for e in old:
                        if e.item.status == "pending":
                            reason = _pending_retention_reason(e, data)
                            if reason:
                                reasons.append(f"旧pending Source #{e.source.id}は履歴保管: {reason}")
                            else:
                                deletable.append(e.source.id)
                    delete_old = tuple(deletable)
                    if delete_old:
                        reasons.append("新旧pending: 履歴/編集/別Sourceのない旧Item/Source/Targetを削除し、新側を維持")
                        removed_items.update(e.item.id for e in old if e.source.id in delete_old)
                        receipt_ids.update(e.item.id for e in new)
                receipt_ids.update(e.item.id for e in old if e.source.id not in delete_old)
                if action in {"cover_old", "reacquire"}:
                    receipt_ids.update(e.item.id for e in new)
                if identity and identity.donor_item_id:
                    removed_items.add(identity.donor_item_id)
        except (RepairMigrationError, OSError) as exc:
            if policy == "auto" and old and new and action not in {"hold", "retire"}:
                action, proofs, identity = "use_new", [], None
                reasons.append(f"旧利用の条件を満たさないため新側を採用: {exc}")
                # Structural ownership/anchor errors must not be waived.
                if not isinstance(exc, ArchiveReuseError):
                    action = "blocked"
                    blockers.append(f"{group_id}: {exc}")
                else:
                    receipt_ids.update(e.item.id for e in old)
            else:
                action = "blocked"
                blockers.append(f"{group_id}: {exc}")
        entries.append(MigrationEntry(group_id, link.old_ids, link.new_ids, requested, action,
            tuple(reasons) + ("人間が採用した対応。本文同一性は未証明。",), tuple(proofs), identity, delete_old))
    operation_id = _digest([2, str(Path(catalog).resolve()), review.digest, accepted, choices])[:32]
    plan = MigrationPlan(str(Path(catalog).resolve()), str(Path(watchlist).resolve()), review.path,
        review.digest, a.work.work_key, a.work.id, a.token, a.watchlist_revision, accepted, choices, tuple(entries),
        tuple(sorted(receipt_ids - removed_items)), tuple(dict.fromkeys(blockers)), operation_id, "")
    return replace(plan, token=_digest(asdict(plan)))


@dataclass(frozen=True)
class MigrationResult:
    operation_id: str
    backup: str | None
    already_applied: bool = False


def _marker(plan):
    return f"[hanayume-repair:{plan.operation_id}]"


def _check_receipt(connection, plan):
    if not plan.receipt_item_ids:
        return False
    present = []
    for item_id in plan.receipt_item_ids:
        row = connection.execute("SELECT note FROM items WHERE id = ?", (item_id,)).fetchone()
        present.append(row is not None and _marker(plan) in (row[0] or ""))
    if any(present) and not all(present):
        raise RepairMigrationError("移行監査markerが一部だけ存在します。手動確認が必要です")
    return all(present)


def apply_migration_plan(plan: MigrationPlan, *, expected_token: str, backup_dir) -> MigrationResult:
    if not plan.ready or expected_token != plan.token or _digest(asdict(replace(plan, token=""))) != plan.token:
        raise RepairMigrationError("適用planが未確認・改変・保留状態です")
    if not plan.receipt_item_ids:
        return MigrationResult(plan.operation_id, None, True)
    catalog = CatalogService(plan.catalog)
    watch = WatchlistService(plan.watchlist)
    with catalog.job_lock(), watch.edit_lock():
        with catalog._read_only_connection() as connection:
            if _check_receipt(connection, plan):
                return MigrationResult(plan.operation_id, None, True)
        current = build_migration_plan(plan.catalog, plan.watchlist, plan.report,
                                       accepted=plan.accepted, choices=plan.choices)
        if current != plan:
            raise RepairMigrationError("Catalog/Watchlist/報告/ZIPがpreview後に変わりました。再プレビューしてください")
        destination = default_backup_path(plan.catalog, backup_dir)
        backup = backup_catalog(plan.catalog, destination)
        with catalog._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = build_migration_plan(plan.catalog, plan.watchlist, plan.report,
                                           accepted=plan.accepted, choices=plan.choices)
            if current != plan:
                raise RepairMigrationError("backup後に事前条件が変わりました。適用しません")
            timestamp = format_timestamp(now_jst())
            history_bindings = {}
            for entry in plan.entries:
                _apply_entry(connection, catalog, plan, entry, history_bindings, timestamp)
            # Delete after all alias allocations so an alias cannot reuse the
            # just-removed highest old Source/Target ID in this transaction.
            for entry in plan.entries:
                for source_id in entry.delete_old_pending_ids:
                    row = connection.execute("SELECT item_id FROM sources WHERE id=?", (source_id,)).fetchone()
                    if row is None:
                        raise RepairMigrationError("削除予定の旧pendingが消失しました")
                    connection.execute("DELETE FROM source_targets WHERE source_id=?", (source_id,))
                    connection.execute("DELETE FROM sources WHERE id=?", (source_id,))
                    connection.execute("DELETE FROM items WHERE id=?", (row[0],))
            if any(e.delete_old_pending_ids for e in plan.entries):
                connection.execute("DELETE FROM discovery_inventory_evidence WHERE work_id=? AND site='hanayume'", (plan.work_id,))
            _register_history(connection, plan, watch, history_bindings, timestamp)
            for item_id in plan.receipt_item_ids:
                row = connection.execute("SELECT note FROM items WHERE id = ?", (item_id,)).fetchone()
                if row is None:
                    raise RepairMigrationError("監査対象Itemが消失しました")
                note = (row[0] + "\n" if row[0] else "") + _marker(plan) + " human accepted; history/ZIP retained"
                connection.execute("UPDATE items SET note = ?, updated_at = ? WHERE id = ?", (note, timestamp, item_id))
            for entry in plan.entries:
                for proof in entry.archives:
                    _verify_file(proof)
            if watch.revision() != plan.watchlist_revision:
                raise RepairMigrationError("Watchlistが変更されました")
            if hashlib.sha256(Path(plan.report).read_bytes()).hexdigest() != plan.report_digest:
                raise RepairMigrationError("報告JSONが変更されました")
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise RepairMigrationError("適用後のCatalog参照整合性が不正です")
        return MigrationResult(plan.operation_id, str(backup.backup_path))


def _apply_entry(connection, catalog, plan, entry, bindings, timestamp):
    old_rows = [dict(connection.execute("SELECT * FROM sources WHERE id = ?", (s,)).fetchone())
                for s in entry.old_ids]
    if entry.action == "reuse_identity":
        identity = entry.identity
        assert identity is not None
        donor = dict(connection.execute("SELECT * FROM sources WHERE id = ?", (identity.donor_source_id,)).fetchone())
        old = old_rows[0]
        alias_id = connection.execute("SELECT COALESCE(MAX(id),0)+1 FROM sources").fetchone()[0]
        alias_target_id = connection.execute("SELECT COALESCE(MAX(id),0)+1 FROM source_targets").fetchone()[0]
        old_target = connection.execute("SELECT locator FROM source_targets WHERE source_id = ? AND backend='web' AND target_key='default'",
                                        (old["id"],)).fetchone()
        SourceIdentityMaintenance(catalog)._apply_connection(connection, identity)
        connection.execute("UPDATE sources SET access_mode=?, free_until=?, available=?, access_checked_at=?, "
            "last_seen_at=?, published_at=?, display_position=?, acquisition_enabled=?, updated_at=? WHERE id=?",
            tuple(donor[k] for k in ("access_mode", "free_until", "available", "access_checked_at",
                "last_seen_at", "published_at", "display_position", "acquisition_enabled")) + (timestamp, old["id"]))
        # Reserve the obsolete identity without duplicating consumption/grants.
        history_key = HISTORY_KEY_PREFIX + old["discovery_key"]
        connection.execute("INSERT INTO sources(id,item_id,site,external_id,discovery_key,access_mode,available,"
            "display_position,acquisition_enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,0,?,0,?,?)",
            (alias_id, old["item_id"], old["site"], old["external_id"], history_key, old["access_mode"],
             old["display_position"], timestamp, timestamp))
        if old_target:
            alias_target_id = max(alias_target_id, connection.execute("SELECT COALESCE(MAX(id),0)+1 FROM source_targets").fetchone()[0])
            connection.execute("INSERT INTO source_targets(id,source_id,backend,target_key,locator,priority,enabled,created_at,updated_at) "
                "VALUES(?,?,'web','default',?,100,0,?,?)", (alias_target_id, alias_id, old_target[0], timestamp, timestamp))
        bindings[history_key] = old["discovery_key"]
    else:
        for old in old_rows:
            if old["id"] in entry.delete_old_pending_ids:
                continue
            history_key = HISTORY_KEY_PREFIX + old["discovery_key"]
            connection.execute("UPDATE sources SET discovery_key=?, acquisition_enabled=0, updated_at=? WHERE id=?",
                                (history_key, timestamp, old["id"]))
            bindings[history_key] = old["discovery_key"]
        if entry.action in {"cover_old", "reacquire"}:
            item_ids = {row[0] for sid in entry.new_ids for row in connection.execute("SELECT item_id FROM sources WHERE id=?", (sid,))}
            for item_id in item_ids:
                connection.execute("UPDATE items SET status=?, completed_at=NULL, updated_at=? WHERE id=?",
                                    ("external" if entry.action == "cover_old" else "pending", timestamp, item_id))
                if entry.action == "cover_old":
                    row = connection.execute("SELECT note FROM items WHERE id=?", (item_id,)).fetchone()
                    note = (row[0] + "\n" if row[0] else "") + "Hanayume repair: old Artifact coverage (body unproven): " + ",".join(str(p.artifact_id) for p in entry.archives)
                    connection.execute("UPDATE items SET note=? WHERE id=?", (note, item_id))


def _register_history(connection, plan, watch, bindings, timestamp):
    targets = tuple(t for t in watch.read_document().targets if t.work_key == plan.work_key)
    current = {v["key"]: v for v in json.loads(configuration_json(targets))}
    row = connection.execute("SELECT configuration_json FROM acquisition_scope_sync WHERE work_id=?", (plan.work_id,)).fetchone()
    prior = {} if row is None else {v["key"]: v for v in json.loads(row[0])}
    merged = {**prior, **current}
    for history_key, original in bindings.items():
        if original not in merged:
            raise RepairMigrationError("履歴bindingの元keyがありません")
        if history_key in merged and merged[history_key]["site"] != "hanayume":
            raise RepairMigrationError("履歴bindingが他siteと衝突しています")
        merged[history_key] = {**merged[original], "key": history_key, "archive_order": None}
        merged[history_key].pop("archive_segments", None)
        merged[history_key]["discovery_scope"] = None
    connection.execute("INSERT INTO acquisition_scope_sync(work_id,fingerprint,definition_fingerprint,configuration_json,status,synced_at) "
        "VALUES(?,?,?,?,'stale',?) ON CONFLICT(work_id) DO UPDATE SET configuration_json=excluded.configuration_json,status='stale'",
        (plan.work_id, work_scope_fingerprint(targets), work_definition_fingerprint(targets),
         json.dumps(sorted(merged.values(), key=lambda v: v["key"]), ensure_ascii=False, sort_keys=True, separators=(",", ":")), timestamp))
