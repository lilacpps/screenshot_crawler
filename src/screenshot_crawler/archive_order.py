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
    provisional: bool = False,
) -> WorkArchivePositionPlan | None:
    """Assign one ordinal stream across every current key/site in a Work.

    Explicit scope reconciliation can validate complete listing evidence.
    This pure layer rejects incomplete key
    ordering, unknown Source ownership, stale Work membership, null positions,
    and duplicate within-key display positions. Item status, access mode and
    source availability deliberately do not affect ordinal membership.
    GUI, Batch, audit and renumber use provisional numbering: missing/duplicate positions sort
    deterministically by Source ID, and removed keys follow current keys.
    No inferred display positions are persisted to Catalog.
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
    segment_mode = any(target.archive_segments is not None for target in work_targets)
    if segment_mode:
        if any(target.archive_segments is None for target in work_targets):
            raise ArchiveOrderPlanningError(
                f"work_key {work.work_key!r} must specify archive_segments for every key"
            )
        return _build_segment_position_plan(
            work=work,
            work_targets=work_targets,
            items=items,
            sources=sources,
            acquisition_flags=acquisition_flags,
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
                if not provisional:
                    raise ArchiveOrderPlanningError(
                        f"Source {source.id} has unknown active Watchlist ownership"
                    )
                sources_by_key[key or ""].append(source)
            continue
        if source.site != target.site:
            raise ArchiveOrderPlanningError(
                f"Source {source.id} site does not match Watchlist key {target.key!r}"
            )
        if enabled:
            sources_by_key[target.key].append(source)

    positions: dict[int, int] = {}
    ordered_source_ids: list[int] = []
    ordered_keys = [
        target.key for target in sorted(
            work_targets, key=lambda value: (value.archive_order, value.key)
        )
    ]
    if provisional:
        ordered_keys.extend(sorted(set(sources_by_key) - set(ordered_keys)))
    for key in ordered_keys:
        rows = sources_by_key.get(key, [])
        seen_positions: dict[int, int] = {}
        for source in rows:
            position = source.display_position
            if isinstance(position, bool) or not isinstance(position, int) or position < 1:
                if provisional:
                    continue
                raise ArchiveOrderPlanningError(
                    f"Source {source.id} has an unknown display_position for key {key!r}"
                )
            previous = seen_positions.get(position)
            if previous is not None and not provisional:
                raise ArchiveOrderPlanningError(
                    f"Sources {previous} and {source.id} share display_position {position} "
                    f"for key {key!r}"
                )
            seen_positions[position] = source.id
        for source in sorted(
            rows,
            key=lambda value: (
                value.display_position is None,
                value.display_position or 0,
                value.id,
            ),
        ):
            ordinal = len(ordered_source_ids) + 1
            ordered_source_ids.append(source.id)
            positions[source.id] = ordinal

    return WorkArchivePositionPlan(
        work_key=work.work_key,
        ordered_source_ids=tuple(ordered_source_ids),
        positions_by_source_id=positions,
    )


def _build_segment_position_plan(
    *,
    work: Work,
    work_targets: Sequence[WatchlistTarget],
    items: Iterable[Item],
    sources: Iterable[Source],
    acquisition_flags: Mapping[int, bool] | None,
) -> WorkArchivePositionPlan:
    """Build a fail-closed ordinal stream from explicit oldest-first segments.

    Segment boundaries are external IDs belonging to their target's own
    discovery key.  The boundary rows are inclusive and must themselves be
    selected for acquisition.  A segment target may intentionally have no
    rows (``archive_segments: []``), which is useful while all of its known
    rows are being replaced by another target.
    """

    target_by_key = {target.key: target for target in work_targets}
    items_by_id = {item.id: item for item in items}
    rows_by_key: dict[str, list[tuple[Source, bool]]] = defaultdict(list)
    seen_source_ids: set[int] = set()
    for source in sources:
        if source.id in seen_source_ids:
            raise ArchiveOrderPlanningError(
                f"Source {source.id} appears more than once in archive-segment snapshot"
            )
        seen_source_ids.add(source.id)
        item = items_by_id.get(source.item_id)
        if item is None or item.work_id != work.id:
            raise ArchiveOrderPlanningError(
                f"Source {source.id} has unknown or mismatched Work ownership"
            )
        target = target_by_key.get(source.discovery_key or "")
        if target is None:
            selected = (
                source.acquisition_enabled
                if acquisition_flags is None
                else acquisition_flags.get(source.id, source.acquisition_enabled)
            )
            if selected:
                raise ArchiveOrderPlanningError(
                    f"Source {source.id} has unknown active Watchlist ownership"
                )
            continue
        if source.site != target.site:
            raise ArchiveOrderPlanningError(
                f"Source {source.id} site does not match Watchlist key {target.key!r}"
            )
        enabled = (
            source.acquisition_enabled
            if acquisition_flags is None
            else acquisition_flags.get(source.id, source.acquisition_enabled)
        )
        rows_by_key[target.key].append((source, enabled))

    ordered_segments: list[tuple[int, str, object]] = []
    orders: set[int] = set()
    assigned: dict[int, int] = {}
    positions: dict[int, int] = {}
    for target in work_targets:
        segments = target.archive_segments
        assert segments is not None
        rows = rows_by_key.get(target.key, [])
        by_external_id: dict[str, tuple[Source, bool]] = {}
        by_position: dict[int, Source] = {}
        for source, enabled in rows:
            if source.external_id in by_external_id:
                raise ArchiveOrderPlanningError(
                    f"Discovery key {target.key!r} has duplicate external ID {source.external_id!r}"
                )
            by_external_id[source.external_id] = (source, enabled)
            # Disabled rows remain in by_external_id so they can be rejected
            # when selected as a segment boundary, but they do not participate
            # in the acquisition order.  Their position may be provisional or
            # absent while a replacement is being configured.
            if not enabled:
                continue
            if (
                isinstance(source.display_position, bool)
                or not isinstance(source.display_position, int)
                or source.display_position < 1
            ):
                raise ArchiveOrderPlanningError(
                    f"Source {source.id} has an unknown display_position for key {target.key!r}"
                )
            previous = by_position.get(source.display_position)
            if previous is not None:
                raise ArchiveOrderPlanningError(
                    f"Sources {previous.id} and {source.id} share display_position "
                    f"{source.display_position} for key {target.key!r}"
                )
            by_position[source.display_position] = source

        for segment in segments:
            if segment.order in orders:
                raise ArchiveOrderPlanningError(
                    f"work_key {work.work_key!r} has duplicate archive segment order {segment.order}"
                )
            orders.add(segment.order)
            for boundary_name in ("start_external_id", "end_external_id"):
                boundary_id = getattr(segment, boundary_name)
                if boundary_id is None:
                    continue
                row = by_external_id.get(boundary_id)
                if row is None:
                    raise ArchiveOrderPlanningError(
                        f"Segment {segment.order} boundary {boundary_id!r} is unknown for key {target.key!r}"
                    )
                if not row[1]:
                    raise ArchiveOrderPlanningError(
                        f"Segment {segment.order} boundary {boundary_id!r} is not acquisition-enabled"
                    )
            if not by_position:
                raise ArchiveOrderPlanningError(
                    f"Segment {segment.order} has no acquisition-enabled sources for key "
                    f"{target.key!r}; complete the listing or use archive_segments=[]"
                )
            start_position = (
                by_external_id[segment.start_external_id][0].display_position
                if segment.start_external_id is not None
                else min(by_position)
            )
            end_position = (
                by_external_id[segment.end_external_id][0].display_position
                if segment.end_external_id is not None
                else max(by_position)
            )
            assert isinstance(start_position, int) and isinstance(end_position, int)
            if start_position > end_position:
                raise ArchiveOrderPlanningError(
                    f"Segment {segment.order} has reversed oldest-first boundaries for key {target.key!r}"
                )
            selected_rows = [
                (source, enabled)
                for position, source in sorted(by_position.items())
                if start_position <= position <= end_position
                for enabled in [by_external_id[source.external_id][1]]
            ]
            for source, enabled in selected_rows:
                if not enabled:
                    continue
                if source.id in assigned:
                    raise ArchiveOrderPlanningError(
                        f"Source {source.id} is covered by overlapping archive segments"
                    )
                assigned[source.id] = segment.order
            ordered_segments.append((segment.order, target.key, segment))

    active_ids = {
        source.id
        for rows in rows_by_key.values()
        for source, enabled in rows
        if enabled
    }
    unplaced = sorted(active_ids - set(assigned))
    if unplaced:
        raise ArchiveOrderPlanningError(
            "Acquisition-enabled Sources are not covered by archive segments: "
            + ", ".join(str(source_id) for source_id in unplaced[:10])
        )
    ordered_source_ids: list[int] = []
    source_by_id = {
        source.id: source
        for rows in rows_by_key.values()
        for source, enabled in rows
        if enabled
    }
    for order, key, _segment in sorted(ordered_segments, key=lambda row: row[0]):
        members = [
            source
            for source_id, assigned_order in assigned.items()
            if assigned_order == order
            for source in [source_by_id[source_id]]
            if source.discovery_key == key
        ]
        for source in sorted(members, key=lambda value: (value.display_position or 0, value.id)):
            ordered_source_ids.append(source.id)
            positions[source.id] = len(ordered_source_ids)
    return WorkArchivePositionPlan(
        work_key=work.work_key,
        ordered_source_ids=tuple(ordered_source_ids),
        positions_by_source_id=positions,
    )
