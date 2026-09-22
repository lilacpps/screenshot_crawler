"""Site-neutral, read-only Batch Planner."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from screenshot_crawler.batch.models import (
    BatchCandidate,
    BatchPlan,
    BatchPlanningError,
    BatchSkipped,
)
from screenshot_crawler.catalog import (
    CatalogError,
    CatalogService,
    Item,
    Source,
    SourceTarget,
    Work,
)
from screenshot_crawler.catalog.service import JST, now_jst
from screenshot_crawler.site_policies import SitePolicyError, SitePolicyRegistry
from screenshot_crawler.site_policies.base import PolicyDecision, SitePolicy


class BatchPlanner:
    """Select pending Catalog sources without executing or recording a crawl."""

    def __init__(self, catalog: CatalogService, policies: SitePolicyRegistry) -> None:
        self.catalog = catalog
        self.policies = policies

    def plan(self, *, site: str, now: datetime | None = None) -> BatchPlan:
        current = _normalize_now(now_jst() if now is None else now)
        try:
            policy = self.policies.create(site)
            works, items, sources, targets = (
                self.catalog.read_works_items_sources_and_targets(site=site)
            )
        except (CatalogError, SitePolicyError, ValueError) as exc:
            raise BatchPlanningError(str(exc)) from exc

        sources_by_item: dict[int, list[Source]] = defaultdict(list)
        for source in sources:
            sources_by_item[source.item_id].append(source)
        targets_by_source: dict[int, list[SourceTarget]] = defaultdict(list)
        for target in targets:
            targets_by_source[target.source_id].append(target)
        works_by_id = {work.id: work for work in works}
        # A site-scoped plan only considers items with at least one source for that site.
        site_item_ids = set(sources_by_item)
        plan = BatchPlan()
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

                selected = self._select_source(
                    item_sources,
                    policy=policy,
                    now=current,
                    quota_remaining=quota_available,
                    skipped=plan.skipped,
                    targets_by_source=targets_by_source,
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
            for selection in ordered_selections:
                plan.candidates.append(_candidate_from_selection(selection))

            plan.quota_remaining = (
                None
                if quota_available is None
                else quota_available - len(accepted_quota)
            )
        except SitePolicyError as exc:
            raise BatchPlanningError(str(exc)) from exc
        return plan

    @staticmethod
    def _select_source(
        sources: Iterable[Source],
        *,
        policy: SitePolicy,
        now: datetime,
        quota_remaining: int | None,
        skipped: list[BatchSkipped],
        targets_by_source: dict[int, list[SourceTarget]],
    ) -> tuple[Source, SourceTarget, PolicyDecision] | None:
        for source in sorted(sources, key=_source_priority_key):
            decision = policy.evaluate(
                source,
                now=now,
                quota_available=quota_remaining,
            )
            if not decision.eligible:
                skipped.append(BatchSkipped(source.item_id, source.id, decision.reason))
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


def _metadata(work: Work, item: Item) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for target, value in (
        ("title", work.title),
        ("author", work.author),
        ("order", item.order_label),
        ("genre", work.genre),
    ):
        if value is not None and value.strip():
            metadata[target] = value
    return metadata


@dataclass(frozen=True, slots=True)
class _Selection:
    work: Work
    item: Item
    source: Source
    target: SourceTarget
    decision: PolicyDecision


def _candidate_from_selection(selection: _Selection) -> BatchCandidate:
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
        metadata=_metadata(selection.work, item),
        artifact_disambiguator=(
            f"mangaone-{source.external_id}"
            if source.site == "mangaone" and item.order_key is None
            else None
        ),
        access_mode=source.access_mode,
        reason=decision.reason,
        consumes_quota=decision.consumes_quota,
        quota_resource=decision.quota_resource,
        quota_scope=decision.quota_scope,
        quota_limit=decision.quota_limit,
        quota_commit_mode=decision.quota_commit_mode,
    )


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
            selection.source.id,
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
                selection.source.id,
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
