"""Qt-free inventory aggregation over local facts and existing Site Policies."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from time import perf_counter
from types import MappingProxyType

from screenshot_crawler.archive_order import build_work_archive_position_plan
from screenshot_crawler.catalog.models import AcquisitionScopeSnapshot, DiscoveryKeySource
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.management.catalog_reader import CatalogInventoryReader, InventoryLoadError
from screenshot_crawler.management.models import (
    AccessClassification,
    GrantEstimate,
    InventoryCounts,
    InventorySnapshot,
    InventorySummary,
    KeyInventory,
    ResourceOverview,
)
from screenshot_crawler.runtime_settings import load_runtime_settings
from screenshot_crawler.site_policies import SitePolicyRegistry
from screenshot_crawler.watchlist.reconcile import ScopeReconciler
from screenshot_crawler.watchlist.service import WatchlistService


def default_policy_registry() -> SitePolicyRegistry:
    """Use the existing policy classes; parity with CLI registration is tested."""
    import screenshot_crawler.site_policies as policies

    registry = SitePolicyRegistry()
    for name in policies.__all__:
        candidate = getattr(policies, name)
        if name.endswith("SitePolicy") and hasattr(candidate, "site"):
            registry.register(candidate.site, candidate)
    return registry


def aware_timestamp(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include timezone")
    return parsed.astimezone(JST)


def display_time(value: str | datetime | None) -> str:
    try:
        parsed = aware_timestamp(value)
        return parsed.strftime("%Y-%m-%d %H:%M JST") if parsed else "—"
    except (ValueError, TypeError, AttributeError):
        return "不明（日時不正）"


class _WatchlistMemory:
    def __init__(self, targets):
        self.targets = targets

    def list_targets(self):
        return self.targets


class _CatalogMemory:
    """Capability-limited facade for ScopeReconciler; never touches files."""

    def __init__(self, scope, work, items, targets):
        self.scope = scope
        self.work = work
        self.items = items
        self.targets = targets

    def read_acquisition_scope_snapshot(self, work_key, *, discovery_keys=()):
        assert work_key == self.scope.work_key
        return self.scope

    def read_works_items_sources_and_targets(self):
        return (self.work,), self.items, self.scope.sources, self.targets

    def read_work_archive_artifacts(self, work_key):
        return ()  # No physical ZIP inspection/renumber preview in P1.


def _access(policy, source, now):
    try:
        decision = policy.evaluate(source, now=now, quota_available=None)
        if decision.eligible and decision.access_strategy in {"direct", "quota"}:
            category = decision.access_strategy
        elif decision.reason in {"paid", "expired_rental"}:
            category = "paid"
        elif decision.reason in {"unavailable", "expired_free"}:
            category = "unavailable"
        else:
            category = "unknown"
        resources = policy.supported_access_resources() if category == "quota" else ()
        return AccessClassification(category, decision.reason, resources)
    except Exception as exc:  # noqa: BLE001 - extension boundary, explicit diagnostic
        # Policy extension failures must stay visible without breaking other sites.
        return AccessClassification("unknown", f"Policy計算不能: {type(exc).__name__}: {exc}")


class InventoryService:
    def __init__(self, policies=None, reader=None):
        self.policies = policies or default_policy_registry()
        self.reader = reader or CatalogInventoryReader()

    def load(self, catalog_path, watchlist_path, *, runtime_path="crawler.yaml", now=None):
        start = perf_counter()
        current = aware_timestamp(now or datetime.now(JST))
        if not Path(watchlist_path).is_file():
            raise InventoryLoadError(f"Watchlistが見つかりません: {watchlist_path}")
        try:
            targets = tuple(WatchlistService(watchlist_path).list_targets())
            settings = load_runtime_settings(runtime_path)
        except (ValueError, OSError) as exc:
            raise InventoryLoadError(f"Watchlist / runtime設定を読み込めません: {exc}") from exc
        data = self.reader.read(catalog_path)
        works = {value.id: value for value in data.works}
        works_by_key = {value.work_key: value for value in data.works}
        items = {value.id: value for value in data.items}
        sources = {value.id: value for value in data.sources}
        by_work, items_by_work, by_site, by_key, target_by_work = (
            defaultdict(list) for _ in range(5)
        )
        for target in targets:
            target_by_work[target.work_key].append(target)
        for item in data.items:
            items_by_work[item.work_id].append(item)
        for source in data.sources:
            by_work[items[source.item_id].work_id].append(source)
            by_site[source.site].append(source)
            by_key[source.discovery_key].append(source)
        syncs = {value.work_key: value for value in data.syncs}
        evidence_by_work = defaultdict(list)
        evidence_by_key = {value.discovery_key: value for value in data.evidence}
        for evidence in data.evidence:
            evidence_by_work[evidence.work_key].append(evidence)
        source_targets = defaultdict(list)
        for target in data.targets:
            source_targets[target.source_id].append(target)

        classifications, resources, policy_by_site = {}, {}, {}
        for site in set(by_site) | {target.site for target in targets}:
            try:
                policy = self.policies.create(site)
                policy_by_site[site] = policy
                diagnostics = []
                try:
                    slots = policy.available_quota(by_site[site], current)
                except Exception as exc:  # noqa: BLE001 - show policy failure
                    slots = None
                    diagnostics.append(f"Quota枠計算不能: {exc}")
                resources[site] = ResourceOverview(
                    site, slots, policy.supported_access_resources(),
                    policy.grant_only_supported_access_resources(), tuple(diagnostics),
                )
                for source in by_site[site]:
                    classifications[source.id] = _access(policy, source, current)
            except Exception as exc:  # noqa: BLE001 - unknown policy stays visible
                resources[site] = ResourceOverview(site, None, (), (), (str(exc),))
                for source in by_site[site]:
                    classifications[source.id] = AccessClassification("unknown", str(exc))

        scope_status, scope_diagnostics, archive_positions = {}, {}, {}
        for work_key, work_targets in target_by_work.items():
            work = works_by_key.get(work_key)
            if work is None:
                scope_status[work_key] = "missing_work"
                scope_diagnostics[work_key] = ("Catalog Work未登録・未Discover",)
                continue
            work_sources = tuple(by_work[work.id])
            key_sources = tuple(
                DiscoveryKeySource(source, works[items[source.item_id].work_id].work_key)
                for target in work_targets for source in by_key[target.key]
            )
            scope = AcquisitionScopeSnapshot(
                work_key, work.id, work_sources, tuple(evidence_by_work[work_key]),
                syncs.get(work_key), key_sources, "immutable-inventory-snapshot",
            )
            memory = _CatalogMemory(scope, work, tuple(items_by_work[work.id]), ())
            reconciler = ScopeReconciler(_WatchlistMemory(tuple(work_targets)), memory)
            try:
                reconciler.require_synchronized_snapshot(work_key)
                scope_status[work_key] = "synced"
                scope_diagnostics[work_key] = ()
                plan = build_work_archive_position_plan(
                    work, work_targets, items_by_work[work.id], work_sources
                )
                if plan:
                    archive_positions.update(plan.positions_by_source_id)
            except Exception as exc:  # noqa: BLE001 - fail closed with reason
                scope_status[work_key] = "stale"
                scope_diagnostics[work_key] = (str(exc),)

        def summarize(source_ids, key_ids, status, diagnostics=(), *, missing=False):
            selected = [sources[source_id] for source_id in sorted(set(source_ids))]
            assigned = defaultdict(list)
            out_of_scope = 0
            notes = list(diagnostics)
            last_access = []
            for source in selected:
                if source.acquisition_enabled:
                    assigned[source.item_id].append(source)
                else:
                    out_of_scope += 1
                for field in ("access_checked_at", "last_seen_at"):
                    try:
                        timestamp = aware_timestamp(getattr(source, field))
                        if timestamp:
                            last_access.append(timestamp)
                    except (ValueError, TypeError):
                        notes.append(f"Source {source.id} {field}: 日時不正")
            counts = defaultdict(int)
            for item_id, members in assigned.items():
                item = items[item_id]
                if item.status in {"completed", "external", "skipped"}:
                    category = item.status
                else:
                    categories = {classifications[member.id].category for member in members}
                    category = next(iter(categories)) if len(categories) == 1 else "unknown"
                    if len(members) > 1:
                        notes.append(f"Item {item_id}: 複数Source（Item単位で重複除外）")
                    if len(categories) > 1:
                        notes.append(f"Item {item_id}: ambiguous access分類")
                    if category == "unknown":
                        notes.extend(
                            f"Source {member.id}: {classifications[member.id].reason}"
                            for member in members
                        )
                counts[category] += 1
            result = InventoryCounts(
                total_assigned=len(assigned), out_of_scope=out_of_scope, **counts
            )
            return InventorySummary(
                None if missing else result, status, tuple(dict.fromkeys(notes)),
                max(last_access).isoformat() if last_access else None,
                tuple(dict.fromkeys(key_ids)), tuple(source.id for source in selected),
            )

        keys, managed_source_ids = [], set()
        for target in targets:
            work = works_by_key.get(target.work_key)
            matching = []
            mismatches = []
            for source in by_key[target.key]:
                if source.site == target.site and works[items[source.item_id].work_id] == work:
                    matching.append(source.id)
                else:
                    mismatches.append(f"Source {source.id}: keyのWork/site所属が不一致")
            managed_source_ids.update(matching)
            proof = evidence_by_key.get(target.key)
            status = scope_status[target.work_key]
            missing = not matching and not (
                proof is not None and proof.source_count == 0 and status == "synced"
            )
            if missing:
                status = "missing_work" if work is None else "not_discovered"
            if mismatches:
                status = "binding_mismatch"
            diagnostics = (*scope_diagnostics[target.work_key], *mismatches)
            if missing:
                diagnostics = (*diagnostics, "このkeyは未Discover（0件とは確定できません）")
            summary = summarize(
                matching, (target.key,), status, diagnostics, missing=missing
            )
            keys.append(KeyInventory(
                target.key, target, target.work_key, target.site,
                work.title if work else target.work_key, target.label, summary,
                proof.completed_at if proof else None,
            ))
        unmanaged = defaultdict(list)
        for source in data.sources:
            if source.id not in managed_source_ids:
                work = works[items[source.item_id].work_id]
                unmanaged[(source.site, work.work_key)].append(source.id)
        for (site, work_key), ids in sorted(unmanaged.items()):
            summary = summarize(
                ids, (), "unmanaged", ("Watchlistへの一致する所属なし（未管理）",)
            )
            # Tuple group identities in Qt distinguish this from an actual key.
            identity = f"unmanaged:{site}:{work_key}"
            while any(key.identity == identity for key in keys):
                identity += "#"
            keys.append(KeyInventory(
                identity, None, work_key, site,
                works_by_key[work_key].title, "未管理 / 所属不明", summary,
            ))
        grouped = defaultdict(list)
        for key in keys:
            for group in (("site", key.site), ("work", key.work_key),
                          ("pair", key.site, key.work_key)):
                grouped[group].append(key)
        summaries = {}
        for group, members in grouped.items():
            statuses = {member.summary.sync_status for member in members}
            status = "synced" if statuses == {"synced"} else "/".join(sorted(statuses))
            ids = [source_id for member in members for source_id in member.summary.source_ids]
            notes = [note for member in members for note in member.summary.diagnostics]
            item_keys = defaultdict(set)
            for member in members:
                for source_id in member.summary.source_ids:
                    item_keys[sources[source_id].item_id].add(member.identity)
            if any(len(value) > 1 for value in item_keys.values()):
                notes.append("同一Itemが複数keyに所属: 親集計はItem IDで重複除外")
            summaries[group] = summarize(
                ids, [k for member in members for k in member.summary.key_ids], status,
                notes, missing=any(member.summary.counts is None for member in members),
            )

        states = {(state.work_id, state.site, state.resource): state
                  for state in data.resource_states}
        grants = []
        for site, policy in policy_by_site.items():
            work_ids = {items[source.item_id].work_id for source in by_site[site]}
            for work_id in sorted(work_ids):
                for resource in policy.grant_only_supported_access_resources():
                    state = states.get((work_id, site, resource))
                    consumed = state.last_consumed_at if state else None
                    retry, reason = None, "不明 / 実サイト確認要"
                    try:
                        if policy.resource_state_scope(resource) == "work" and consumed:
                            last = aware_timestamp(consumed)
                            cooldown = settings.for_site(site).work_ticket_cooldown_hours
                            value = policy.grant_only_retry_at(
                                resource=resource, last_consumed_at=last,
                                cooldown_hours=cooldown,
                            )
                            retry = value.isoformat() if value else None
                            skip = policy.grant_only_skip_reason(
                                resource=resource, last_consumed_at=last, now=current,
                                cooldown_hours=cooldown,
                            )
                            reason = skip or "ローカル待機制限なし・実サイト可否は不明"
                    except Exception as exc:  # noqa: BLE001 - show retry failure
                        reason = f"計算不能: {exc}"
                    grants.append(GrantEstimate(
                        works[work_id].work_key, site, resource, consumed, retry, reason
                    ))
        artifacts = defaultdict(list)
        for artifact in data.artifacts:
            artifacts[artifact.item_id].append(artifact)
        return InventorySnapshot(
            current, str(Path(catalog_path).resolve()), str(Path(watchlist_path).resolve()),
            tuple(keys), MappingProxyType(summaries), MappingProxyType(items),
            MappingProxyType(sources),
            MappingProxyType({key: tuple(value) for key, value in source_targets.items()}),
            MappingProxyType(classifications),
            MappingProxyType({run.item_id: run for run in data.latest_runs}),
            MappingProxyType({key: tuple(value) for key, value in artifacts.items()}),
            MappingProxyType(archive_positions), MappingProxyType(resources), tuple(grants),
            perf_counter() - start,
        )
