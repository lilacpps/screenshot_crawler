"""ComicFUZ public access and daily work-ticket policy."""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from datetime import datetime, time, timedelta

from screenshot_crawler.catalog.models import Source, SourceTarget
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.site_policies.base import PolicyDecision, SitePolicy, SitePolicyError


class ComicFuzSitePolicy(SitePolicy):
    """Select public free episodes or one confirmed daily ticket per Work."""

    site = "comicfuz"
    WORK_TICKET_RESOURCE = "work_ticket"

    def guards_unresolved_quota_attempts_by_work(self) -> bool:
        return True

    def records_confirmed_quota_attempts_in_run_history(self) -> bool:
        return True

    def confirmed_quota_attempt_identity_matches(
        self,
        candidate: object,
        item: object,
        source: Source,
        target: SourceTarget,
        work: object,
    ) -> bool:
        native_ids = re.fullmatch(r"(?P<work>[0-9]+):(?P<chapter>[0-9]+)", source.external_id)
        return bool(
            native_ids is not None
            and source.site == self.site
            and source.item_id == getattr(item, "id", None)
            and source.id == getattr(candidate, "source_id", None)
            and source.external_id == getattr(candidate, "external_id", None)
            and getattr(candidate, "site", None) == self.site
            and getattr(item, "work_id", None) == getattr(work, "id", None)
            and getattr(candidate, "work_id", None) == getattr(work, "id", None)
            and target.id == getattr(candidate, "target_id", None)
            and target.source_id == source.id
            and target.backend == getattr(candidate, "backend", None) == "web"
            and target.target_key == getattr(candidate, "target_key", None)
            and target.locator == getattr(candidate, "locator", None)
            and target.locator == f"https://comic-fuz.com/manga/viewer/{native_ids.group('chapter')}"
        )

    def unresolved_quota_attempt_work_ids(
        self,
        runs: Collection[object],
        *,
        item_work_ids: Mapping[int, int],
        sources_by_id: Mapping[int, Source],
        targets_by_id: Mapping[int, object],
        now: datetime,
    ) -> frozenset[int]:
        current = _aware(now, "now").astimezone(JST)
        blocked: set[int] = set()
        for run in runs:
            item_id = getattr(run, "item_id", None)
            work_id = item_work_ids.get(item_id) if isinstance(item_id, int) else None
            source_id = getattr(run, "source_id", None)
            if work_id is None or not isinstance(source_id, int):
                continue
            source = sources_by_id.get(source_id)
            if source is not None and source.site != self.site:
                continue
            if getattr(run, "site_snapshot", None) != self.site and source is None:
                continue
            strategy = getattr(run, "access_strategy", None)
            if strategy in {"direct", "auto"}:
                continue
            if strategy != "quota":
                blocked.add(work_id)
                continue
            if getattr(run, "site_snapshot", None) != self.site or source is None:
                blocked.add(work_id)
                continue
            target_id = getattr(run, "target_id", None)
            target = targets_by_id.get(target_id) if isinstance(target_id, int) else None
            native_ids = re.fullmatch(r"(?P<work>[0-9]+):(?P<chapter>[0-9]+)", source.external_id)
            canonical_locator = (
                f"https://comic-fuz.com/manga/viewer/{native_ids.group('chapter')}"
                if native_ids is not None else None
            )
            if (
                source.item_id != item_id
                or native_ids is None
                or getattr(run, "external_id_snapshot", None) != source.external_id
                or target is None
                or getattr(target, "source_id", None) != source.id
                or getattr(run, "backend_snapshot", None) != getattr(target, "backend", None)
                or getattr(run, "target_key_snapshot", None) != getattr(target, "target_key", None)
                or getattr(run, "locator_snapshot", None) != getattr(target, "locator", None)
                or getattr(target, "locator", None) != canonical_locator
                or getattr(run, "locator_snapshot", None) != canonical_locator
            ):
                blocked.add(work_id)
                continue
            started = _parse_aware(getattr(run, "started_at", None))
            finished = _parse_aware(getattr(run, "finished_at", None))
            if (
                getattr(run, "status", None) not in {"succeeded", "failed"}
                or started is None
                or finished is None
                or finished < started
                or started > current
                or finished > current
            ):
                blocked.add(work_id)
                continue

            marker = _parse_consumption_marker(getattr(run, "stop_reason", None))
            if (
                getattr(run, "status", None) == "failed"
                and getattr(run, "error_type", None) == "ComicFuzTicketNotAttemptedError"
                and getattr(run, "stop_reason", None) == "comicfuz_work_ticket_not_attempted"
                and (
                    getattr(run, "page_count", None) is None
                    or (
                        type(getattr(run, "page_count", None)) is int
                        and getattr(run, "page_count", None) == 0
                    )
                )
                and getattr(run, "error_message", None)
            ):
                continue
            if not isinstance(marker, datetime) or not started <= marker <= finished:
                blocked.add(work_id)
                continue
            if getattr(run, "status", None) == "succeeded":
                original_reason = _original_stop_reason(getattr(run, "stop_reason", None))
                page_count = getattr(run, "page_count", None)
                no_error = (
                    getattr(run, "error_type", None) is None
                    and getattr(run, "error_message", None) is None
                )
                normal_success = (
                    type(page_count) is int
                    and page_count > 0
                    and original_reason == "end"
                )
                grant_only_success = (
                    type(page_count) is int
                    and page_count == 0
                    and original_reason == "entry_confirmed"
                )
                if not no_error or not (normal_success or grant_only_success):
                    blocked.add(work_id)
        return frozenset(blocked)

    def supported_access_resources(self) -> tuple[str, ...]:
        return (self.WORK_TICKET_RESOURCE,)

    def ordered_access_resource_passes(self) -> tuple[str, ...]:
        return (self.WORK_TICKET_RESOURCE,)

    def grant_only_supported_access_resources(self) -> tuple[str, ...]:
        return (self.WORK_TICKET_RESOURCE,)

    def resource_state_scope(self, resource: str) -> str | None:
        if resource == self.WORK_TICKET_RESOURCE:
            return "work"
        return None

    def defer_quota_access_to_grant_phase(self) -> bool:
        return False

    def grant_only_skip_reason(
        self,
        *,
        resource: str,
        last_consumed_at: datetime | None,
        now: datetime,
        cooldown_hours: int | None,
    ) -> str | None:
        del cooldown_hours
        retry_at = self.grant_only_retry_at(
            resource=resource,
            last_consumed_at=last_consumed_at,
            cooldown_hours=None,
        )
        if retry_at is None:
            return None
        return "work_ticket_daily_reset" if _aware(now, "now") < retry_at else None

    def grant_only_retry_at(
        self,
        *,
        resource: str,
        last_consumed_at: datetime | None,
        cooldown_hours: int | None,
    ) -> datetime | None:
        del cooldown_hours
        if resource != self.WORK_TICKET_RESOURCE:
            raise SitePolicyError(f"Unsupported ComicFUZ resource: {resource}")
        if last_consumed_at is None:
            return None
        consumed = _aware(last_consumed_at, "last_consumed_at").astimezone(JST)
        next_day = consumed.date() + timedelta(days=1)
        return datetime.combine(next_day, time.min, tzinfo=JST)

    def evaluate(
        self,
        source: Source,
        *,
        now: datetime,
        quota_available: int | None,
    ) -> PolicyDecision:
        del quota_available
        current = _aware(now, "now")
        if source.site != self.site:
            return PolicyDecision(False, None, "wrong_site")
        if not source.available:
            return PolicyDecision(False, None, "unavailable")
        if source.access_mode == "free":
            return PolicyDecision(True, "direct", "free")
        if source.access_mode == "quota":
            grant_until = _parse_optional_grant(source.access_granted_until)
            if grant_until is not None and grant_until > current:
                return PolicyDecision(True, "direct", "active_access_grant")
            return PolicyDecision(
                True,
                "quota",
                "work_ticket",
                consumes_quota=True,
                quota_resource=self.WORK_TICKET_RESOURCE,
                quota_scope="work",
                quota_limit=1,
                quota_commit_mode="after_observed_consumption",
            )
        reason = {
            "unknown": "unknown",
            "paid": "paid",
            "owned": "owned_not_verified",
            "grant": "grant_not_supported",
            "rental": "rental_not_supported",
        }.get(source.access_mode, "unknown")
        return PolicyDecision(False, None, reason)


def _aware(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise SitePolicyError(f"{name} must be timezone-aware")
    return value


def _parse_aware(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    except ValueError:
        return None
    if not isinstance(parsed, datetime) or parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _parse_optional_grant(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    parsed = _parse_aware(value)
    if parsed is None:
        raise SitePolicyError("access_granted_until must be a timezone-aware timestamp")
    return parsed


def _parse_consumption_marker(value: object) -> datetime | bool | None:
    if not isinstance(value, str) or not value.startswith("access_consumption_confirmed:"):
        return None
    prefix = "access_consumption_confirmed:v1:"
    if not value.startswith(prefix):
        return False
    timestamp, separator, _reason = value[len(prefix) :].partition("|")
    if not separator:
        return False
    parsed = _parse_aware(timestamp)
    return parsed if parsed is not None else False


def _original_stop_reason(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    prefix = "access_consumption_confirmed:v1:"
    if not value.startswith(prefix):
        return value
    _timestamp, separator, reason = value[len(prefix) :].partition("|")
    return reason if separator else None


__all__ = ["ComicFuzSitePolicy"]
