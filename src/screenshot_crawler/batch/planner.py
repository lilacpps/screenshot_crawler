"""Site-neutral, read-only Batch Planner."""

from __future__ import annotations

import os
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from screenshot_crawler.archive_order import build_work_archive_position_plan
from screenshot_crawler.batch.archive_guard import (
    ArchiveNameGuardError,
    CandidateOutputPathError,
    inspect_existing_archive_names,
    validate_candidate_output_paths,
)
from screenshot_crawler.batch.models import (
    BatchCandidate,
    BatchPlan,
    BatchPlanningError,
    BatchSkipped,
)
from screenshot_crawler.batch.naming import (
    archive_metadata_for_catalog,
    archive_position_prefix,
)
from screenshot_crawler.batch.naming import collision_source_ids as shared_collision_source_ids
from screenshot_crawler.catalog import (
    CatalogError,
    CatalogService,
    Item,
    Source,
    SourceTarget,
    Work,
)
from screenshot_crawler.catalog.service import JST, now_jst
from screenshot_crawler.core.packaging import archive_stem
from screenshot_crawler.site_policies import SitePolicyError, SitePolicyRegistry
from screenshot_crawler.site_policies.base import PolicyDecision, SitePolicy
from screenshot_crawler.watchlist.models import WatchlistTarget
from screenshot_crawler.watchlist.reconcile import (
    ScopeReconciler,
    ScopeReconciliationError,
)
from screenshot_crawler.watchlist.service import WatchlistService


class BatchPlanner:
    """Select pending Catalog sources without executing or recording a crawl."""

    def __init__(
        self,
        catalog: CatalogService,
        policies: SitePolicyRegistry,
        *,
        watchlist: WatchlistService | None = None,
        library_dir: str | Path | None = None,
    ) -> None:
        self.catalog = catalog
        self.policies = policies
        self.scope_reconciler = (
            ScopeReconciler(watchlist, catalog) if watchlist is not None else None
        )
        # Non-CLI callers commonly pair an isolated Catalog with a planner in
        # tests and maintenance services. Keep their filesystem checks beside
        # that Catalog unless the real runtime output root is explicitly passed.
        self.library_dir = (
            Path(library_dir) if library_dir is not None else catalog.path.parent / "Books"
        )

    def plan(
        self,
        *,
        site: str,
        now: datetime | None = None,
        quota_resource: str | None = None,
        output_mode: Literal["capture", "grant_only"] = "capture",
    ) -> BatchPlan:
        if output_mode not in {"capture", "grant_only"}:
            raise BatchPlanningError(f"Unsupported output mode: {output_mode!r}")
        current = _normalize_now(now_jst() if now is None else now)
        archive_positions_by_source: dict[int, int] = {}
        archive_warnings: list[str] = []
        unmanaged_source_ids: set[int] = set()
        try:
            policy = self.policies.create(site)
            if quota_resource is not None:
                policy.validate_access_resource(quota_resource)
            works, items, all_sources, all_targets = (
                self.catalog.read_works_items_sources_and_targets()
            )
            sources = [source for source in all_sources if source.site == site]
            site_source_ids = {source.id for source in sources}
            targets = [target for target in all_targets if target.source_id in site_source_ids]
            if sources and self.scope_reconciler is None:
                raise BatchPlanningError(
                    "Batch requires an explicit Watchlist for acquisition-scope validation"
                )
            works_by_id = {work.id: work for work in works}
            items_by_id = {item.id: item for item in items}
            assert self.scope_reconciler is not None or not sources
            if self.scope_reconciler is not None:
                watchlist_targets = self.scope_reconciler.watchlist.list_targets()
                targets_by_work: dict[str, list[WatchlistTarget]] = defaultdict(list)
                for target in watchlist_targets:
                    targets_by_work[target.work_key].append(target)
                work_keys: set[str] = set()
                sources_by_work_key: dict[str, dict[int, Source]] = defaultdict(dict)
                validated_sources_by_work_key: dict[str, list[Source]] = {}
                for source in sources:
                    item = items_by_id.get(source.item_id)
                    work = works_by_id.get(item.work_id) if item is not None else None
                    if work is None:
                        raise BatchPlanningError(
                            f"Cannot resolve Work for source {source.id}; refusing Batch"
                        )
                    work_keys.add(work.work_key)
                    sources_by_work_key[work.work_key][source.id] = source
                for work_key in sorted(work_keys):
                    if not targets_by_work.get(work_key):
                        unmanaged_source_ids.update(sources_by_work_key[work_key])
                        continue
                    validated = self.scope_reconciler.require_synchronized_snapshot(work_key)
                    initial_work_sources = {
                        source.id: source
                        for source in all_sources
                        if works_by_id.get(items_by_id[source.item_id].work_id) is not None
                        and works_by_id[items_by_id[source.item_id].work_id].work_key
                        == work_key
                    }
                    validated_work_sources = {
                        source.id: source for source in validated.sources
                    }
                    if validated_work_sources != initial_work_sources:
                        raise BatchPlanningError(
                            f"Catalog Sources changed across sites while validating "
                            f"acquisition scope for {work_key!r}; retry Batch planning"
                        )
                    validated_sources_by_work_key[work_key] = list(validated.sources)
                    validated_sources = {
                        source.id: source
                        for source in validated.sources
                        if source.site == site
                    }
                    if validated_sources != sources_by_work_key[work_key]:
                        raise BatchPlanningError(
                            f"Catalog sources changed while validating acquisition scope for "
                            f"{work_key!r}; retry Batch planning"
                        )
                    work = next(
                        (value for value in works if value.work_key == work_key), None
                    )
                    if work is None:
                        raise BatchPlanningError(
                            f"Cannot resolve Work {work_key!r} for archive naming"
                        )
                    archive_plan = build_work_archive_position_plan(
                        work,
                        targets_by_work.get(work_key, []),
                        items,
                        validated.sources,
                    )
                    if archive_plan is not None:
                        archive_positions_by_source.update(
                            archive_plan.positions_by_source_id
                        )
                archive_warnings = self._validate_existing_archive_names(
                    works=works,
                    items=items,
                    sources=[
                        source
                        for work_key in work_keys
                        for source in validated_sources_by_work_key.get(work_key, [])
                    ],
                    targets_by_work=targets_by_work,
                    work_keys=work_keys,
                    archive_positions_by_source=archive_positions_by_source,
                )
        except (CatalogError, SitePolicyError, ScopeReconciliationError, ValueError) as exc:
            raise BatchPlanningError(str(exc)) from exc

        sources_by_item: dict[int, list[Source]] = defaultdict(list)
        for source in sources:
            sources_by_item[source.item_id].append(source)
        targets_by_source: dict[int, list[SourceTarget]] = defaultdict(list)
        for target in targets:
            targets_by_source[target.source_id].append(target)
        collision_source_ids = _collision_source_ids(items, sources, works_by_id)
        # A site-scoped plan only considers items with at least one source for that site.
        site_item_ids = set(sources_by_item)
        plan = BatchPlan(warnings=archive_warnings)
        try:
            quota_available = policy.available_quota(sources, current)
            plan.quota_available = quota_available
            selections: list[_Selection] = []
            for item in items:
                if item.id not in site_item_ids:
                    continue
                if item.status != "pending":
                    plan.skipped.append(BatchSkipped(item.id, None, item.status))
                    continue
                item_sources = sources_by_item.get(item.id, [])
                if not item_sources:
                    plan.skipped.append(BatchSkipped(item.id, None, "no_source"))
                    continue

                enabled_sources = []
                for source in item_sources:
                    if source.id in unmanaged_source_ids:
                        plan.skipped.append(
                            BatchSkipped(item.id, source.id, "acquisition_unmanaged")
                        )
                        continue
                    if source.acquisition_enabled:
                        enabled_sources.append(source)
                    else:
                        plan.skipped.append(
                            BatchSkipped(
                                item.id,
                                source.id,
                                "acquisition_disabled",
                            )
                        )
                if not enabled_sources:
                    continue

                selected = self._select_source(
                    enabled_sources,
                    policy=policy,
                    now=current,
                    quota_remaining=quota_available,
                    skipped=plan.skipped,
                    targets_by_source=targets_by_source,
                    quota_resource=quota_resource,
                )
                if selected is None:
                    continue
                source, target, decision = selected
                if decision.access_strategy is None:
                    raise BatchPlanningError(
                        f"Eligible source {source.id} has no access strategy"
                    )
                selections.append(
                    _Selection(
                        work=works_by_id[item.work_id],
                        item=item,
                        source=source,
                        target=target,
                        decision=decision,
                    )
                )

            defer_quota = getattr(policy, "defer_quota_access_to_grant_phase", None)
            deferred_quota = bool(defer_quota()) if callable(defer_quota) else False
            capture_selections = (
                [
                    selection
                    for selection in selections
                    if not (deferred_quota and selection.decision.consumes_quota)
                ]
                if output_mode == "capture"
                else []
            )
            plan.warnings.extend(
                _validate_candidate_archive_paths(
                    self.catalog,
                    capture_selections,
                    library_dir=self.library_dir,
                    archive_positions_by_source=archive_positions_by_source,
                    collision_source_ids=collision_source_ids,
                )
            )

            quota_selections = [
                selection for selection in selections if selection.decision.consumes_quota
            ]
            quota_selections = _enforce_work_quota_limits(quota_selections, plan.skipped)
            group_ranks = _discovery_group_ranks(sources)
            quota_selections.sort(
                key=lambda selection: _quota_selection_order_key(selection, group_ranks)
            )
            if quota_available is None:
                accepted_quota = quota_selections
            else:
                accepted_quota = quota_selections[: max(0, quota_available)]
            accepted_quota_ids = {selection.item.id for selection in accepted_quota}
            for selection in quota_selections:
                if selection.item.id not in accepted_quota_ids:
                    plan.skipped.append(
                        BatchSkipped(selection.item.id, selection.source.id, "quota_exhausted")
                    )

            if any(
                selection.decision.quota_scope == "work"
                for selection in selections
                if selection.decision.consumes_quota
            ):
                ordered_selections = [
                    selection for selection in selections
                    if not selection.decision.consumes_quota
                ] + accepted_quota
            else:
                accepted_ids = {selection.item.id for selection in accepted_quota}
                quota_iter = iter(accepted_quota)
                ordered_selections = []
                for selection in selections:
                    if not selection.decision.consumes_quota:
                        ordered_selections.append(selection)
                    elif selection.item.id in accepted_ids:
                        ordered_selections.append(next(quota_iter))
            if policy.batch_ordering() == "published_at":
                direct_selections = [
                    selection
                    for selection in ordered_selections
                    if not selection.decision.consumes_quota
                ]
                quota_selections = [
                    selection
                    for selection in ordered_selections
                    if selection.decision.consumes_quota
                ]
                ordered_selections = (
                    _order_by_published_at_within_work(direct_selections)
                    + _order_by_published_at_within_work(quota_selections)
                )
            for selection in ordered_selections:
                plan.candidates.append(
                    _candidate_from_selection(
                        selection,
                        collision_source_ids=collision_source_ids,
                        archive_positions_by_source=archive_positions_by_source,
                    )
                )

            plan.quota_remaining = (
                None
                if quota_available is None
                else quota_available - len(accepted_quota)
            )
        except SitePolicyError as exc:
            raise BatchPlanningError(str(exc)) from exc
        return plan

    def _validate_existing_archive_names(
        self,
        *,
        works: list[Work],
        items: list[Item],
        sources: list[Source],
        targets_by_work: dict[str, list[WatchlistTarget]],
        work_keys: set[str],
        archive_positions_by_source: dict[int, int],
    ) -> list[str]:
        """Collect historical-name warnings; output occupancy has its own hard gate."""

        works_by_id = {work.id: work for work in works}
        items_by_id = {item.id: item for item in items}
        sources_by_work: dict[str, list[Source]] = defaultdict(list)
        for source in sources:
            item = items_by_id.get(source.item_id)
            work = works_by_id.get(item.work_id) if item is not None else None
            if work is not None and work.work_key in work_keys:
                sources_by_work[work.work_key].append(source)

        warnings: list[str] = []
        for work_key in sorted(work_keys):
            if not targets_by_work.get(work_key):
                continue
            work_sources = sources_by_work.get(work_key, [])
            if not work_sources:
                continue
            work = works_by_id.get(items_by_id[work_sources[0].item_id].work_id)
            assert work is not None
            try:
                warnings.extend(
                    inspect_existing_archive_names(
                        self.catalog,
                        work=work,
                        items=[item for item in items if item.work_id == work.id],
                        sources=work_sources,
                        archive_positions_by_source=archive_positions_by_source,
                    )
                )
            except ArchiveNameGuardError as exc:
                raise BatchPlanningError(str(exc)) from exc
        return warnings

    @staticmethod
    def _select_source(
        sources: Iterable[Source],
        *,
        policy: SitePolicy,
        now: datetime,
        quota_remaining: int | None,
        skipped: list[BatchSkipped],
        targets_by_source: dict[int, list[SourceTarget]],
        quota_resource: str | None,
    ) -> tuple[Source, SourceTarget, PolicyDecision] | None:
        for source in sorted(sources, key=_source_priority_key):
            if quota_resource is None:
                decision = policy.evaluate(
                    source,
                    now=now,
                    quota_available=quota_remaining,
                )
            else:
                decision = policy.evaluate_for_quota_resource(
                    source,
                    now=now,
                    quota_available=quota_remaining,
                    quota_resource=quota_resource,
                )
            if not decision.eligible:
                skipped.append(BatchSkipped(source.item_id, source.id, decision.reason))
                continue
            if quota_resource is not None and not decision.consumes_quota:
                continue
            if decision.consumes_quota and quota_remaining is not None and quota_remaining <= 0:
                skipped.append(BatchSkipped(source.item_id, source.id, "quota_exhausted"))
                continue
            web_targets = [
                target
                for target in targets_by_source.get(source.id, [])
                if target.backend == "web" and target.enabled
            ]
            if not web_targets:
                skipped.append(BatchSkipped(source.item_id, source.id, "no enabled web target"))
                continue
            target = min(web_targets, key=lambda candidate: (candidate.priority, candidate.id))
            return source, target, decision
        return None


def _metadata(work: Work, item: Item, source: Source) -> dict[str, str]:
    return archive_metadata_for_catalog(work, item, source)


@dataclass(frozen=True, slots=True)
class _Selection:
    work: Work
    item: Item
    source: Source
    target: SourceTarget
    decision: PolicyDecision


def _candidate_from_selection(
    selection: _Selection,
    *,
    collision_source_ids: set[int],
    archive_positions_by_source: dict[int, int],
) -> BatchCandidate:
    item = selection.item
    source = selection.source
    decision = selection.decision
    if decision.access_strategy is None:
        raise BatchPlanningError(f"Eligible source {source.id} has no access strategy")
    return BatchCandidate(
        item_id=item.id,
        source_id=source.id,
        target_id=selection.target.id,
        site=source.site,
        backend=selection.target.backend,
        target_key=selection.target.target_key,
        locator=selection.target.locator,
        access_strategy=decision.access_strategy,
        metadata=_metadata(selection.work, item, source),
        artifact_prefix=archive_position_prefix(
            archive_positions_by_source.get(source.id, source.display_position)
        ),
        artifact_disambiguator=(
            f"{source.site}-{source.external_id}"
            if source.id in collision_source_ids
            else None
        ),
        access_mode=source.access_mode,
        reason=decision.reason,
        consumes_quota=decision.consumes_quota,
        quota_resource=decision.quota_resource,
        quota_scope=decision.quota_scope,
        quota_limit=decision.quota_limit,
        quota_commit_mode=decision.quota_commit_mode,
        external_id=source.external_id,
        work_id=item.work_id,
    )


def _collision_source_ids(
    items: Iterable[Item],
    sources: Iterable[Source],
    works_by_id: dict[int, Work],
) -> set[int]:
    return shared_collision_source_ids(works_by_id.values(), items, sources)


def _validate_candidate_archive_paths(
    catalog: CatalogService,
    selections: list[_Selection],
    *,
    library_dir: Path,
    archive_positions_by_source: dict[int, int],
    collision_source_ids: set[int],
) -> list[str]:
    planned: dict[str, int] = {}
    warnings: list[str] = []
    for selection in selections:
        source = selection.source
        position = archive_positions_by_source.get(source.id, source.display_position)
        disambiguator = (
            f"{source.site}-{source.external_id}"
            if source.id in collision_source_ids
            else None
        )
        stem, title, genre, _order, _author = archive_stem(
            archive_metadata_for_catalog(selection.work, selection.item, source),
            artifact_prefix=archive_position_prefix(position),
            artifact_disambiguator=disambiguator,
        )
        target = library_dir / genre / title / f"{stem}.zip"
        key = _archive_path_key(target)
        prior = planned.get(key)
        if prior is not None and prior != source.id:
            raise BatchPlanningError(
                f"Selected Sources {prior} and {source.id} map to the same archive path "
                f"{target}; resolve the naming collision before Batch"
            )
        planned[key] = source.id
        status_path = (
            library_dir.parent
            / "crawl-status"
            / genre
            / title
            / f"{stem}.json"
        )
        try:
            output_preflight = validate_candidate_output_paths(
                catalog,
                work=selection.work,
                item=selection.item,
                source=source,
                target=selection.target,
                archive_path=target,
                status_path=status_path,
            )
        except CandidateOutputPathError as exc:
            raise BatchPlanningError(str(exc)) from exc
        if output_preflight.stale_status is not None:
            warnings.append(
                f"work={selection.work.work_key!r} source={source.id}: existing completed "
                f"status {status_path} is proven to belong to this Source and has no current "
                "ZIP; Batch may refresh the status after a successful capture"
            )
    return warnings


def _archive_path_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _normalize_now(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise BatchPlanningError("now must be a timezone-aware datetime")
    return value.astimezone(JST)


def _source_priority_key(source: Source) -> tuple[int, int, datetime, int]:
    if source.access_mode == "free":
        free_until = _parse_aware(source.free_until, "free_until")
        return (0, 0 if free_until is not None else 1, free_until or _MAX_DATETIME, source.id)
    mode_rank = {
        "owned": 1,
        "quota": 2,
        "paid": 3,
        "unknown": 4,
    }.get(source.access_mode, 5)
    return (mode_rank, 0, _MIN_DATETIME, source.id)


_ORDER_KEY_PATTERN = re.compile(r"(?P<episode>\d+)(?:-(?P<part>前編|後編))?")


def _item_order_key(item: Item) -> tuple[int, int, int, str, int]:
    """Return a stable ascending key without relying on Catalog insertion order."""

    parsed = _parse_episode_order_key(item.order_key)
    if parsed is not None:
        episode, part = parsed
        return (0, episode, part, "", item.id)

    fallback = " ".join(
        (item.order_label or item.item_title or "").split()
    ).casefold()
    return (1, 0, 0, fallback, item.id)


def _discovery_group_ranks(sources: Iterable[Source]) -> dict[str, int]:
    """Return the first Catalog source id for each explicit discovery group."""

    ranks: dict[str, int] = {}
    for source in sources:
        if source.discovery_key is None:
            continue
        previous = ranks.get(source.discovery_key)
        if previous is None or source.id < previous:
            ranks[source.discovery_key] = source.id
    return ranks


def _quota_selection_order_key(
    selection: _Selection,
    group_ranks: dict[str, int],
) -> tuple[object, ...]:
    """Order new quota consumption by Discovery group, then item order.

    Sources without a discovery key are deliberately placed after all explicit
    groups and retain the same stable item-order fallback as other candidates.
    """

    if selection.decision.quota_scope == "work":
        return (
            0,
            selection.work.created_at,
            selection.work.id,
            _published_date_key(selection.source),
            _item_order_key(selection.item),
            -selection.source.id,
        )
    group_rank = group_ranks.get(selection.source.discovery_key)
    if group_rank is None:
        return (1, 0, _item_order_key(selection.item))
    return (0, group_rank, _item_order_key(selection.item))


def _enforce_work_quota_limits(
    selections: list[_Selection], skipped: list[BatchSkipped]
) -> list[_Selection]:
    # Work-scoped limits are independent; site-scoped candidates keep the old allocator.
    by_work: dict[int, list[_Selection]] = defaultdict(list)
    unrestricted: list[_Selection] = []
    for selection in selections:
        decision = selection.decision
        if decision.quota_scope != "work" or decision.quota_limit is None:
            unrestricted.append(selection)
        else:
            by_work[selection.work.id].append(selection)
    accepted = list(unrestricted)
    for work_selections in by_work.values():
        limit = work_selections[0].decision.quota_limit or 0
        ranked = sorted(
            work_selections,
            key=lambda selection: (
                _published_date_key(selection.source),
                _item_order_key(selection.item),
                -selection.source.id,
            ),
        )
        accepted.extend(ranked[:limit])
        skipped.extend(
            BatchSkipped(selection.item.id, selection.source.id, "quota_work_limit")
            for selection in ranked[limit:]
        )
    return accepted


def _published_date_key(source: Source) -> tuple[int, datetime]:
    published = _parse_aware(source.published_at, "published_at")
    return (1, _MAX_DATETIME) if published is None else (0, published)


def _order_by_published_at_within_work(selections: list[_Selection]) -> list[_Selection]:
    """Keep Work order while processing each Work from old to new."""

    by_work: dict[int, list[_Selection]] = defaultdict(list)
    work_order: list[int] = []
    for selection in selections:
        work_id = selection.work.id
        if work_id not in by_work:
            work_order.append(work_id)
        by_work[work_id].append(selection)

    ordered: list[_Selection] = []
    for work_id in work_order:
        ordered.extend(
            sorted(
                by_work[work_id],
                key=lambda selection: (
                    _published_date_key(selection.source),
                    -selection.source.id,
                ),
            )
        )
    return ordered


def _parse_episode_order_key(value: str | None) -> tuple[int, int] | None:
    if not isinstance(value, str):
        return None
    match = _ORDER_KEY_PATTERN.fullmatch(value.strip())
    if match is None:
        return None
    part = {None: 0, "前編": 0, "後編": 1}[match.group("part")]
    return int(match.group("episode")), part


_MIN_DATETIME = datetime.min.replace(tzinfo=JST)
_MAX_DATETIME = datetime.max.replace(tzinfo=JST)


def _parse_aware(value: str | datetime | None, field: str) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise BatchPlanningError(f"Invalid {field} timestamp: {value!r}") from exc
    else:
        raise BatchPlanningError(f"{field} must be an aware datetime, ISO string, or null")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise BatchPlanningError(f"{field} must be timezone-aware")
    return parsed.astimezone(JST)
