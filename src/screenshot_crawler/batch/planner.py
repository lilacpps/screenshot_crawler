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
from screenshot_crawler.catalog import CatalogError, CatalogService, Item, Source
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
            items, sources = self.catalog.read_items_and_sources(site=site)
        except (CatalogError, SitePolicyError, ValueError) as exc:
            raise BatchPlanningError(str(exc)) from exc

        sources_by_item: dict[int, list[Source]] = defaultdict(list)
        for source in sources:
            sources_by_item[source.item_id].append(source)
        plan = BatchPlan()
        try:
            quota_available = policy.available_quota(sources, current)
            plan.quota_available = quota_available
            selections: list[_Selection] = []
            for item in items:
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
                )
                if selected is None:
                    continue
                source, decision = selected
                if decision.access_strategy is None:
                    raise BatchPlanningError(
                        f"Eligible source {source.id} has no access strategy"
                    )
                selections.append(
                    _Selection(item=item, source=source, decision=decision)
                )

            quota_selections = [
                selection for selection in selections if selection.decision.consumes_quota
            ]
            quota_selections.sort(key=lambda selection: _item_order_key(selection.item))
            if quota_available is None:
                accepted_quota = quota_selections
            else:
                accepted_quota = quota_selections[: max(0, quota_available)]
            accepted_quota_ids = {selection.item.id for selection in accepted_quota}
            for selection in selections:
                if (
                    selection.decision.consumes_quota
                    and selection.item.id not in accepted_quota_ids
                ):
                    plan.skipped.append(
                        BatchSkipped(selection.item.id, selection.source.id, "quota_exhausted")
                    )

            quota_iter = iter(accepted_quota)
            for selection in selections:
                if selection.decision.consumes_quota:
                    if selection.item.id not in accepted_quota_ids:
                        continue
                    selection = next(quota_iter)
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
    ) -> tuple[Source, PolicyDecision] | None:
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
            return source, decision
        return None


def _metadata(item: Item) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for target, value in (
        ("title", item.canonical_title),
        ("author", item.author),
        ("order", item.order_label),
        ("genre", item.genre),
    ):
        if value is not None and value.strip():
            metadata[target] = value
    return metadata


@dataclass(frozen=True, slots=True)
class _Selection:
    item: Item
    source: Source
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
        site=source.site,
        url=source.url,
        access_strategy=decision.access_strategy,
        metadata=_metadata(item),
        access_mode=source.access_mode,
        reason=decision.reason,
        consumes_quota=decision.consumes_quota,
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

    fallback = " ".join((item.order_label or item.canonical_title or "").split()).casefold()
    return (1, 0, 0, fallback, item.id)


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
