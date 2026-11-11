"""Read-only Hanayume repair analysis and operator annotations (never apply).

Availability partitions are hypotheses about old/current membership, not proof
of an ID replacement. API identity also does not prove equal episode bodies.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from screenshot_crawler.catalog.models import Artifact, CrawlRun, Item, Source, SourceTarget, Work
from screenshot_crawler.management.catalog_reader import (
    CatalogInventoryReader,
    catalog_snapshot_identity,
)
from screenshot_crawler.site_adapters.hanayume.discovery import parse_hanayume_episode_url
from screenshot_crawler.watchlist.models import WatchlistTarget
from screenshot_crawler.watchlist.service import WatchlistService

HISTORY_KEY_PREFIX = "history:hanayume-repair:"


def inventory_history_kinds(data, managed_source_ids) -> dict[int, str]:
    """Recognize maintained histories without inventing Watchlist membership.

    A prefix alone is insufficient: require disabled/unavailable state, the
    Work's saved binding and the repair receipt on its retained Item.
    """
    candidates = [s for s in data.sources if s.id not in managed_source_ids and s.site == "hanayume"
                  and (s.discovery_key or "").startswith(HISTORY_KEY_PREFIX)
                  and s.discovery_key != HISTORY_KEY_PREFIX and not s.acquisition_enabled and not s.available]
    if not candidates:
        return {}
    candidate_items = {s.item_id for s in candidates}
    items = {i.id: i for i in data.items if i.id in candidate_items}
    works = {w.id: w for w in data.works}
    work_keys = {works[i.work_id].work_key for i in items.values()}
    bindings = {}
    for sync in data.syncs:
        if sync.work_key not in work_keys:
            continue
        try:
            values = json.loads(sync.configuration_json)
            bindings[sync.work_key] = {v["key"]: v for v in values if isinstance(v, dict)}
        except (ValueError, TypeError, KeyError):
            continue
    recognized = set()
    siblings = defaultdict(set)
    for source in candidates:
        key = source.discovery_key or ""
        item = items[source.item_id]
        work = works[item.work_id]
        binding = bindings.get(work.work_key, {}).get(key, {})
        if (binding.get("site") == source.site and binding.get("work_key") == work.work_key
                and re.search(r"\[hanayume-repair:[0-9a-f]{32}\]", item.note or "")):
            recognized.add(source.id)
    current_items = set()
    for source in data.sources:
        if source.item_id in candidate_items:
            siblings[source.item_id].add(source.id)
            if source.id in managed_source_ids:
                current_items.add(source.item_id)
    return {s.id: "identity_alias" if s.item_id in current_items else "history"
            for s in candidates if s.id in recognized
            and (s.item_id in current_items or siblings[s.item_id] <= recognized)}


@dataclass(frozen=True)
class RepairEntry:
    source: Source
    item: Item
    targets: tuple[SourceTarget, ...]
    runs: tuple[CrawlRun, ...]
    artifacts: tuple[Artifact, ...]

    @property
    def retired(self) -> bool:
        return (self.source.discovery_key or "").startswith(HISTORY_KEY_PREFIX)

    @property
    def url(self) -> str:
        return next((t.locator for t in self.targets
                     if t.backend == "web" and t.target_key == "default"), "")

    @property
    def title(self) -> str:
        return " / ".join(dict.fromkeys(filter(None, (self.item.order_label, self.item.item_title)))) or "（話名なし）"

    @property
    def zip_count(self) -> int:
        # Catalog facts only: no network filesystem stat, extraction or body reads.
        return sum(a.format.lower() == "zip" for a in self.artifacts)


@dataclass(frozen=True)
class IdentityObservation:
    old_source_id: int
    new_source_id: int | None
    reason: str
    index_id: int | None = None
    observed_at: str | None = None


@dataclass(frozen=True)
class RepairLink:
    old_ids: tuple[int, ...]
    new_ids: tuple[int, ...]
    evidence: str  # api_identity / heuristic / manual
    reasons: tuple[str, ...]
    decision: str = "review"  # review / mapped / hold / reacquire
    match_rule: str | None = None

    @property
    def shape(self) -> str:
        return f"{len(self.old_ids)}対{len(self.new_ids)}"


@dataclass(frozen=True)
class RepairAnalysis:
    work: Work
    entries: tuple[RepairEntry, ...]
    targets: tuple[WatchlistTarget, ...]
    catalog_token: str
    watchlist_revision: str
    links: tuple[RepairLink, ...] = ()
    observations: tuple[IdentityObservation, ...] = ()
    diagnostics: tuple[str, ...] = ()

    @property
    def token(self) -> str:
        return hashlib.sha256(
            f"{self.catalog_token}:{self.watchlist_revision}:{self.work.work_key}".encode()
        ).hexdigest()

    @property
    def old(self) -> tuple[RepairEntry, ...]:
        return tuple(e for e in self.entries if not e.source.available and not e.retired)

    @property
    def current(self) -> tuple[RepairEntry, ...]:
        return tuple(e for e in self.entries if e.source.available and not e.retired)

    def summary(self) -> dict[str, int]:
        by_id = {e.source.id: e for e in self.entries}
        api = [l for l in self.links if l.evidence == "api_identity"]
        one_to_one = {l.old_ids[0] for l in api if l.shape == "1対1"
                      and sum(bool(set(l.new_ids) & set(x.new_ids)) for x in api) == 1}
        matched = {sid for l in self.links if l.new_ids for sid in l.old_ids}
        both, reuse = set(), set()
        for link in self.links:
            if link.new_ids and any(by_id[s].zip_count for s in link.old_ids):
                reuse.update(link.old_ids)
                if any(by_id[s].zip_count for s in link.new_ids):
                    both.update(link.old_ids)
        return {
            "旧Source": len(self.old), "現行候補Source": len(self.current),
            "履歴保管Source": sum(e.retired for e in self.entries),
            "APIで1対1のID対応確認": len(one_to_one),
            "ラベル・話番号で1対1推測": sum(
                l.match_rule == "label_number_unique" for l in self.links),
            "手動確認が必要な旧Source": len(self.old),
            "分割・統合・候補複数グループ": sum(
                bool(l.old_ids and l.new_ids) and l.shape != "1対1" for l in self.links),
            "新旧ZIP記録あり（旧Source数）": len(both),
            "旧ZIP再利用の検討候補（本文未証明）": len(reuse),
            "本文同一性証明済み": 0,
            "現行pending（再取得の検討対象）": sum(e.item.status == "pending"
                                                        for e in self.current),
            "明示的な再取得指定（新Source数）": len({s for l in self.links
                                                   if l.decision == "reacquire"
                                                   for s in l.new_ids}),
            "対応不明の旧Source": len(self.old) - len(matched),
        }


def load_analysis(catalog: str | Path, watchlist: str | Path, work_key: str) -> RepairAnalysis:
    """All history from one ro transaction; Watchlist revision is separately bound."""
    data = CatalogInventoryReader().read(catalog, include_history=True)
    document = WatchlistService(watchlist).read_document()
    work = next((w for w in data.works if w.work_key == work_key), None)
    if work is None:
        raise ValueError("指定した作品がCatalogにありません")
    items = {i.id: i for i in data.items if i.work_id == work.id}
    targets_by_source, runs_by_source, artifacts_by_item = defaultdict(list), defaultdict(list), defaultdict(list)
    for target in data.targets:
        targets_by_source[target.source_id].append(target)
    for run in data.latest_runs:
        runs_by_source[run.source_id].append(run)
    for artifact in data.artifacts:
        artifacts_by_item[artifact.item_id].append(artifact)
    entries = tuple(RepairEntry(
        source=s, item=items[s.item_id],
        targets=tuple(targets_by_source[s.id]),
        runs=tuple(runs_by_source[s.id]),
        artifacts=tuple(artifacts_by_item[s.item_id]),
    ) for s in data.sources if s.item_id in items and s.site == "hanayume")
    if not entries:
        raise ValueError("この作品にはhanayume Sourceがありません")
    entries = tuple(sorted(entries, key=lambda e: (
        e.source.discovery_key or "", e.source.display_position or 10**9, e.source.id)))
    targets = tuple(t for t in document.targets
                    if t.work_key == work_key and t.site == "hanayume")
    diagnostics = (
        ("旧=Catalog unavailable、現行候補=available。公開終了や古いDiscoveryも含むため、"
         "刷新世代・最新サイト一覧の証明ではありません。"),
        ("ZIPは全Artifact履歴の記録を表示。ファイル存在・ハッシュ・本文は未検証。"
         "同じItemの別Sourceで取得したZIPも含みます。"),
        "APIのID対応は本文同一性を証明しません。すべての適用はStage 02以降です。",
    )
    if any(t.discovery_scope or t.archive_segments for t in targets):
        diagnostics += ("範囲・区間設定あり。旧IDの境界・除外・segment anchorは自動置換しません。",)
    analysis = RepairAnalysis(work, entries, targets, catalog_snapshot_identity(data),
                              document.revision, diagnostics=diagnostics)
    return generate_candidates(analysis)


def list_repair_works(catalog: str | Path) -> tuple[Work, ...]:
    data = CatalogInventoryReader().read(catalog)
    item_ids = {s.item_id for s in data.sources if s.site == "hanayume"}
    work_ids = {i.work_id for i in data.items if i.id in item_ids}
    return tuple(w for w in data.works if w.id in work_ids)


def _identity(entry: RepairEntry) -> tuple[str, str] | None:
    match = re.fullmatch(r"([0-9a-f]{13}):([0-9a-f]{13})", entry.source.external_id)
    url = parse_hanayume_episode_url(entry.url)
    if match and url and url.episode_id == match[2]:
        return match[1], match[2]
    return None


def validate_pair(analysis: RepairAnalysis, old_id: int, new_id: int) -> None:
    by_id = {e.source.id: e for e in analysis.entries}
    _validate_entries(analysis, by_id.get(old_id), by_id.get(new_id))


def _validate_entries(analysis, old, new):
    if (old is None or new is None or old.source.available or not new.source.available
            or old.source.site != "hanayume" or new.source.site != "hanayume"):
        raise ValueError("旧unavailableと現行availableを同じ作品内から指定してください")
    a, b = _identity(old), _identity(new)
    if not a or not b or a[0] != b[0] or a[1] == b[1]:
        raise ValueError("作品identity・URL・episode IDが不正または異なります")
    if not old.source.discovery_key or old.source.discovery_key != new.source.discovery_key:
        raise ValueError("異なるDiscovery key、または未所属のSourceは対応付けできません")
    if old.item.work_id != analysis.work.id or new.item.work_id != analysis.work.id:
        raise ValueError("他作品への対応付けはできません")


def _normalized(value: str | None) -> str:
    # Keep split-part digits separate from the episode number: scene2⑤ must
    # not become scene25 under NFKC.
    value = re.sub(r"[①-⑳]", lambda m: f"({unicodedata.normalize('NFKC', m[0])})", value or "")
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).casefold()


def _episode_number(value: str) -> str | None:
    match = re.search(r"(?:第)?(\d+)(?:話|回|章)|(?:scene|act|chapter)(\d+)", value)
    return next((v for v in match.groups() if v is not None), None) if match else None


def generate_candidates(analysis: RepairAnalysis) -> RepairAnalysis:
    edges = []
    exact_pairs = []
    def neighbors(entries):
        result = {}
        for index, entry in enumerate(entries):
            result[entry.source.id] = tuple(
                _normalized(entries[n].item.order_label)
                if 0 <= n < len(entries) and entries[n].source.discovery_key == entry.source.discovery_key
                else "" for n in (index - 1, index + 1))
        return result
    old_neighbors, new_neighbors = neighbors(analysis.old), neighbors(analysis.current)
    for old in analysis.old:
        ranked = []
        for new in analysis.current:
            try:
                _validate_entries(analysis, old, new)
            except ValueError:
                continue
            reasons, score = [], 0
            a, b = _normalized(old.item.order_label), _normalized(new.item.order_label)
            if a and a == b:
                reasons.append("話数ラベル一致（本文未証明）")
                score += 5
            if old.item.item_title and _normalized(old.item.item_title) == _normalized(new.item.item_title):
                reasons.append("Itemタイトル一致（手動編集の可能性あり）")
                score += 3
            old_number, new_number = _episode_number(a), _episode_number(b)
            if old_number and old_number == new_number:
                reasons.append("話数番号一致（分割・統合の可能性）")
                score += 2
            p, q = old.source.display_position, new.source.display_position
            if p and q and abs(p - q) <= 1 and not (
                old_number and new_number and old_number != new_number
            ):
                reasons.append(f"表示位置が近い {p}→{q}（順序変更に注意）")
                score += 1
            surrounding = old_neighbors[old.source.id]
            if all(surrounding) and surrounding == new_neighbors[new.source.id]:
                reasons.append("前後両話のラベル一致（並びによる推測）")
                score += 1
            if score:
                if old.zip_count or new.zip_count:
                    reasons.append(f"ZIP記録 旧{old.zip_count}/新{new.zip_count}（同一性証拠ではない）")
                ranked.append((score, new.source.id, tuple(reasons)))
                if a and a == b and old_number and old_number == new_number:
                    exact_pairs.append(RepairLink(
                        (old.source.id,), (new.source.id,), "heuristic", tuple(reasons) + (
                            "話数ラベル・話数番号の一意一致を優先した1対1の推測（本文未証明）",
                        ), match_rule="label_number_unique"))
        # A position-only edge must not join otherwise distinct label matches
        # into one Work-wide ambiguous component.
        if any(score >= 2 for score, _, _ in ranked):
            ranked = [row for row in ranked if row[0] >= 2]
        for score, sid, reasons in sorted(ranked, key=lambda r: (-r[0], r[1]))[:8]:
            edges.append(RepairLink((old.source.id,), (sid,), "heuristic", reasons))
    # Reserve reciprocal unique full-label/number matches before weaker
    # base-number or neighboring-position edges can join parts into 3:3 groups.
    # Count the complete exact set before the per-old edge cap; duplicate
    # labels never become unique because alternatives were truncated.
    old_counts = Counter(link.old_ids[0] for link in exact_pairs)
    new_counts = Counter(link.new_ids[0] for link in exact_pairs)
    groups = [link for link in exact_pairs
              if old_counts[link.old_ids[0]] == 1 and new_counts[link.new_ids[0]] == 1]
    reserved = {sid for link in groups for sid in link.old_ids + link.new_ids}
    edges = [link for link in edges if not reserved.intersection(link.old_ids + link.new_ids)]
    # Only unresolved candidates form ambiguous split/merge components.
    while edges:
        seed, *edges = edges
        old_ids, new_ids, reasons = set(seed.old_ids), set(seed.new_ids), set(seed.reasons)
        changed = True
        while changed:
            changed = False
            remaining = []
            for edge in edges:
                if old_ids.intersection(edge.old_ids) or new_ids.intersection(edge.new_ids):
                    old_ids.update(edge.old_ids)
                    new_ids.update(edge.new_ids)
                    reasons.update(edge.reasons)
                    changed = True
                else:
                    remaining.append(edge)
            edges = remaining
        groups.append(RepairLink(tuple(sorted(old_ids)), tuple(sorted(new_ids)), "heuristic",
                                 tuple(sorted(reasons)) + ("候補は旧Sourceあたり上位8件。複数候補は分割・統合の確定ではない。",)))
    return replace(analysis, links=tuple(groups))


def with_observations(analysis: RepairAnalysis, observations: tuple[IdentityObservation, ...]
                      ) -> RepairAnalysis:
    merged = {o.old_source_id: o for o in analysis.observations}
    merged.update({o.old_source_id: o for o in observations})
    by_id = {e.source.id: e for e in analysis.entries}
    indexes = defaultdict(set)
    for o in merged.values():
        if o.new_source_id is not None:
            validate_pair(analysis, o.old_source_id, o.new_source_id)
            native_work = by_id[o.old_source_id].source.external_id.split(":")[0]
            indexes[(native_work, o.index_id)].add(o.new_source_id)
    for sid, o in tuple(merged.items()):
        if o.new_source_id is not None:
            native_work = by_id[sid].source.external_id.split(":")[0]
            if o.index_id is None or len(indexes[(native_work, o.index_id)]) > 1:
                merged[sid] = replace(o, new_source_id=None, reason=(
                    f"API indexの欠落または複数現行IDへの矛盾（候補Source {o.new_source_id}）"))
    api_links = []
    for observation in merged.values():
        if observation.new_source_id is None:
            continue
        validate_pair(analysis, observation.old_source_id, observation.new_source_id)
        api_links.append(RepairLink((observation.old_source_id,), (observation.new_source_id,),
                                   "api_identity", (observation.reason, "本文改訂の可能性あり")))
    # A converging API mapping remains many-to-one, not a confirmed 1:1.
    counts = Counter(l.new_ids for l in api_links)
    consolidated = []
    for new_ids in counts:
        links = [l for l in api_links if l.new_ids == new_ids]
        consolidated.append(RepairLink(tuple(l.old_ids[0] for l in links), new_ids,
                                       "api_identity", links[0].reasons))
    manual = [l for l in analysis.links if l.evidence == "manual"]
    covered = {s for l in consolidated + manual for s in l.old_ids + l.new_ids}
    remaining = replace(analysis, entries=tuple(e for e in analysis.entries if e.source.id not in covered))
    heuristics = list(generate_candidates(remaining).links)
    # Manual edits take precedence; API observations remain in the audit details.
    manual_ids = {s for l in manual for s in l.old_ids + l.new_ids}
    return replace(analysis, observations=tuple(merged.values()), links=tuple(
        manual + [l for l in consolidated if not manual_ids.intersection(l.old_ids + l.new_ids)]
        + heuristics))


def annotate(analysis: RepairAnalysis, old_ids: tuple[int, ...], new_ids: tuple[int, ...],
             decision: str, reason: str) -> RepairAnalysis:
    if decision not in {"mapped", "hold", "reacquire", "retire"} or not (old_ids or new_ids):
        raise ValueError("Sourceと対応・保留・再取得のいずれかを指定してください")
    if decision == "mapped" and not (old_ids and new_ids):
        raise ValueError("対応指定には左右両方のSourceを選択してください")
    if decision == "reacquire" and not new_ids:
        raise ValueError("再取得には新側のSourceを選択してください")
    if decision == "retire" and (not old_ids or new_ids):
        raise ValueError("対応無しの履歴保管には旧側だけを選択してください")
    if len(set(old_ids)) != len(old_ids) or len(set(new_ids)) != len(new_ids):
        raise ValueError("Sourceの重複指定はできません")
    if not reason.strip():
        raise ValueError("判断理由を入力してください")
    for ids, available in ((old_ids, False), (new_ids, True)):
        for sid in ids:
            entry = next((e for e in analysis.entries if e.source.id == sid), None)
            if (entry is None or entry.source.available != available
                    or entry.source.site != "hanayume" or entry.item.work_id != analysis.work.id
                    or _identity(entry) is None):
                raise ValueError("同作品内の正しい側から有効なSourceを選択してください")
    for a in old_ids:
        for b in new_ids:
            validate_pair(analysis, a, b)
    used = set(old_ids + new_ids)
    links = []
    for existing in analysis.links:
        if not used.intersection(existing.old_ids + existing.new_ids):
            links.append(existing)
        elif existing.evidence == "heuristic":
            remaining_old = tuple(s for s in existing.old_ids if s not in used)
            remaining_new = tuple(s for s in existing.new_ids if s not in used)
            if remaining_old and remaining_new:
                links.append(replace(existing, old_ids=remaining_old, new_ids=remaining_new))
    link = RepairLink(old_ids, new_ids, "manual", (reason.strip(), "本文同一性は未証明"), decision)
    return replace(analysis, links=tuple(links) + (link,))


def unlink(analysis: RepairAnalysis, indexes: tuple[int, ...]) -> RepairAnalysis:
    return replace(analysis, links=tuple(l for i, l in enumerate(analysis.links) if i not in indexes))


def export_report(analysis: RepairAnalysis, path: str | Path) -> None:
    """Explicit new JSON artifact only; never overwrite an existing path."""
    payload = {"version": 1, "stage": "01-read-only", "body_equality_proven": False,
               "snapshot_token": analysis.token, "summary": analysis.summary(),
               "analysis": asdict(analysis)}
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
