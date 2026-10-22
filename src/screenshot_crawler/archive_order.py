"""Pure work-wide acquisition-source numbering shared by Batch and maintenance."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from screenshot_crawler.catalog.models import Item, Source, Work
from screenshot_crawler.watchlist.models import WatchlistTarget


class ArchiveOrderPlanningError(ValueError):
    """Raised when a work-wide archive order cannot be proven completely."""


@dataclass(frozen=True, slots=True)
class WorkArchivePositionPlan:
    """Pure work-wide ordinal assignment for one archive-ordered Work."""

    work_key: str
    ordered_source_ids: tuple[int, ...]
    positions_by_source_id: Mapping[int, int]


def build_work_archive_position_plan(
    work: Work,
    targets: Sequence[WatchlistTarget],
    items: Iterable[Item],
    sources: Iterable[Source],
    *,
    acquisition_flags: Mapping[int, bool] | None = None,
) -> WorkArchivePositionPlan | None:
    """Assign one ordinal stream across every current key/site in a Work.

    The caller must first validate Watchlist sync and complete listing evidence
    through ``ScopeReconciler``. This pure layer then rejects incomplete key
    ordering, unknown Source ownership, stale Work membership, null positions,
    and duplicate within-key display positions. Item status, access mode and
    source availability deliberately do not affect ordinal membership.
    """

    work_targets = [target for target in targets if target.work_key == work.work_key]
    if not work_targets:
        raise ArchiveOrderPlanningError(
            f"Watchlist has no targets for ordered work_key {work.work_key!r}"
        )
    if len({target.key for target in work_targets}) != len(work_targets):
        raise ArchiveOrderPlanningError(
            f"work_key {work.work_key!r} has duplicate Watchlist keys"
        )
    order_values = [target.archive_order for target in work_targets]
    if all(value is None for value in order_values):
        return None
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 1
        for value in order_values
    ):
        raise ArchiveOrderPlanningError(
            f"work_key {work.work_key!r} has partial or invalid archive_order"
        )
    if len(set(order_values)) != len(order_values):
        raise ArchiveOrderPlanningError(
            f"work_key {work.work_key!r} has duplicate archive_order values"
        )

    target_by_key = {target.key: target for target in work_targets}
    items_by_id = {item.id: item for item in items}
    source_ids: set[int] = set()
    sources_by_key: dict[str, list[Source]] = defaultdict(list)
    for source in sources:
        if source.id in source_ids:
            raise ArchiveOrderPlanningError(
                f"Source {source.id} appears more than once in archive-order snapshot"
            )
        source_ids.add(source.id)
        item = items_by_id.get(source.item_id)
        if item is None or item.work_id != work.id:
            raise ArchiveOrderPlanningError(
                f"Source {source.id} has unknown or mismatched Work ownership"
            )
        key = source.discovery_key
        target = target_by_key.get(key or "")
        enabled = (
            source.acquisition_enabled
            if acquisition_flags is None
            else acquisition_flags.get(source.id, source.acquisition_enabled)
        )
        if target is None:
            if enabled:
                raise ArchiveOrderPlanningError(
                    f"Source {source.id} has unknown active Watchlist ownership"
                )
            continue
        if source.site != target.site:
            raise ArchiveOrderPlanningError(
                f"Source {source.id} site does not match Watchlist key {target.key!r}"
            )
        if enabled:
            sources_by_key[target.key].append(source)

    positions: dict[int, int] = {}
    ordered_source_ids: list[int] = []
    for target in sorted(work_targets, key=lambda value: (value.archive_order, value.key)):
        rows = sources_by_key.get(target.key, [])
        seen_positions: dict[int, int] = {}
        for source in rows:
            position = source.display_position
            if isinstance(position, bool) or not isinstance(position, int) or position < 1:
                raise ArchiveOrderPlanningError(
                    f"Source {source.id} has an unknown display_position for key {target.key!r}"
                )
            previous = seen_positions.get(position)
            if previous is not None:
                raise ArchiveOrderPlanningError(
                    f"Sources {previous} and {source.id} share display_position {position} "
                    f"for key {target.key!r}"
                )
            seen_positions[position] = source.id
        for source in sorted(rows, key=lambda value: value.display_position):
            ordinal = len(ordered_source_ids) + 1
            ordered_source_ids.append(source.id)
            positions[source.id] = ordinal

    return WorkArchivePositionPlan(
        work_key=work.work_key,
        ordered_source_ids=tuple(ordered_source_ids),
        positions_by_source_id=positions,
    )
