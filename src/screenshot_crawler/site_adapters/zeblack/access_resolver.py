"""Zeblack site-native access-resource candidate resolution."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from screenshot_crawler.batch.models import BatchCandidate
from screenshot_crawler.site_adapters.base import AccessResourceResolution
from screenshot_crawler.site_adapters.zeblack.discovery_protobuf import (
    ConsumptionStatus,
    map_zeblack_access_mode,
)
from screenshot_crawler.site_adapters.zeblack.live_access import (
    ZEBLACK_LIVE_ACCESS_TIMEOUT_MS,
    ZeblackChapterListSnapshot,
    observe_zeblack_chapter_list,
)


def _candidate_identity(candidate: BatchCandidate) -> tuple[str, str] | None:
    """Return ``(title_id, chapter_id)`` from the Catalog-backed candidate."""

    external_id = str(getattr(candidate, "external_id", "") or "")
    locator = str(getattr(candidate, "locator", "") or "")
    if not external_id or not locator:
        return None
    # Keep URL parsing in the Zeblack integration. Importing the adapter here
    # is safe because this module is reached through the optional adapter hook.
    from screenshot_crawler.site_adapters.zeblack.adapter import parse_zeblack_viewer_url

    viewer = parse_zeblack_viewer_url(locator)
    if viewer is None:
        return None
    if viewer.chapter_id != external_id:
        return None
    return viewer.title_id, viewer.chapter_id


async def resolve_zeblack_work_ticket_candidates(
    page: object,
    candidates: Sequence[BatchCandidate],
    *,
    timeout_ms: int = ZEBLACK_LIVE_ACCESS_TIMEOUT_MS,
    selected_snapshots: dict[int, ZeblackChapterListSnapshot] | None = None,
    page_turn_delay_ms: int = 1000,
    blocked_external_ids: frozenset[str] = frozenset(),
) -> AccessResourceResolution:
    """Select pending Work Ticket candidates from one live snapshot per title.

    The input is already the generic Planner's pending/quota/work-ticket set.
    A missing live match permits one stock-confirmed, non-consuming predecessor
    reread. Final selection still requires a live match to the input pool.
    """

    groups: dict[tuple[int | None, str], list[tuple[BatchCandidate, str]]] = defaultdict(list)
    skipped: list[tuple[int, str]] = []
    for candidate in candidates:
        identity = _candidate_identity(candidate)
        source_id = int(candidate.source_id)
        if identity is None:
            skipped.append((source_id, "work_ticket_target_not_in_catalog"))
            continue
        title_id, chapter_id = identity
        groups[(getattr(candidate, "work_id", None), title_id)].append(
            (candidate, chapter_id)
        )

    selected: list[int] = []
    for (_work_id, title_id), group in groups.items():
        snapshot = await observe_zeblack_chapter_list(
            page,
            title_id=title_id,
            timeout_ms=timeout_ms,
            **({"capture_document": True} if selected_snapshots is not None else {}),
        )
        candidates_by_external_id = {
            chapter_id: candidate for candidate, chapter_id in group
        }
        ticket_ids = snapshot.ticket_available_ids
        recovery_reason = ""
        if (
            not set(ticket_ids).intersection(candidates_by_external_id)
            and set(candidates_by_external_id).issubset(snapshot.by_id)
            and candidates_by_external_id
            and any(
                chapter.chapter_id in candidates_by_external_id
                and map_zeblack_access_mode(chapter.status_value) == "quota"
                and not (
                    chapter.status_value == ConsumptionStatus.RENTAL
                    and (chapter.remaining_rental_time or 0) > 0
                )
                for chapter in snapshot.chapters
            )
        ):
            from screenshot_crawler.site_adapters.zeblack.recovery import recover_work_ticket

            recovered, recovery_reason = await recover_work_ticket(
                page, snapshot, frozenset(candidates_by_external_id),
                timeout_ms=timeout_ms, capture_document=selected_snapshots is not None,
                page_turn_delay_ms=page_turn_delay_ms,
                blocked_external_ids=blocked_external_ids,
            )
            if recovered is None:
                skipped.extend(
                    (candidate.source_id, recovery_reason) for candidate, _ in group
                )
                continue
            snapshot = recovered
            ticket_ids = snapshot.ticket_available_ids
        if not ticket_ids:
            skipped.extend(
                (candidate.source_id, recovery_reason or "work_ticket_unavailable")
                for candidate, _chapter_id in group
            )
            continue

        chosen: BatchCandidate | None = None
        for chapter in snapshot.chapters:
            if (
                chapter.status_value == int(ConsumptionStatus.TICKET_AVAILABLE)
                and chapter.chapter_id in candidates_by_external_id
            ):
                chosen = candidates_by_external_id[chapter.chapter_id]
                break
        if chosen is None:
            skipped.extend(
                (candidate.source_id, recovery_reason or "work_ticket_target_not_in_catalog")
                for candidate, _chapter_id in group
            )
            continue

        selected.append(chosen.source_id)
        if selected_snapshots is not None:
            selected_snapshots[chosen.source_id] = snapshot
        skipped.extend(
            (candidate.source_id, "work_ticket_candidate_not_selected")
            for candidate, _chapter_id in group
            if candidate.source_id != chosen.source_id
        )

    return AccessResourceResolution(
        selected_source_ids=tuple(selected),
        skipped_source_reasons=tuple(skipped),
    )


__all__ = ["resolve_zeblack_work_ticket_candidates"]
