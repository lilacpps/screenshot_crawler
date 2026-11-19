"""Default Batch policy for Piccoma free, granted, and ticket-backed sources."""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime

from screenshot_crawler.catalog.models import Source
from screenshot_crawler.site_policies.base import PolicyDecision, SitePolicy, SitePolicyError


class PiccomaSitePolicy(SitePolicy):
    """Select direct access first, then permit only supported free tickets."""

    site = "piccoma"
    TICKET_RESOURCE = "piccoma_ticket_auto"
    WORK_TICKET_RESOURCE = "work_ticket"
    BINGE_TICKET_RESOURCE = "binge_ticket"
    NO_ACTION_ERROR_TYPE = "PiccomaTicketNoActionError"
    NO_ACTION_REASON = "piccoma_ticket_unavailable_before_click"

    def preserve_candidate_sequence(self, *, allow_quota_access: bool) -> bool:
        del allow_quota_access
        return True

    def guards_unresolved_quota_attempts(self) -> bool:
        return True

    def requires_quota_access_opt_in(self) -> bool:
        return False

    def unresolved_quota_attempt_source_ids(
        self, runs: Collection[object]
    ) -> frozenset[int]:
        blocked: set[int] = set()
        for run in runs:
            source_id = getattr(run, "source_id", None)
            if not isinstance(source_id, int):
                continue
            strategy = getattr(run, "access_strategy", None)
            if strategy in {"direct", "auto"}:
                continue
            if strategy not in {"quota"}:
                blocked.add(source_id)
                continue
            status = getattr(run, "status", None)
            error_type = getattr(run, "error_type", None)
            error_message = getattr(run, "error_message", None)
            if (
                not self._has_conclusive_terminal_metadata(run)
                or getattr(run, "site_snapshot", None) != self.site
            ):
                blocked.add(source_id)
                continue
            if (
                status == "succeeded"
                and error_type is None
                and error_message is None
                and _positive_page_count(getattr(run, "page_count", None))
            ):
                continue
            if (
                status == "succeeded"
                and error_type is None
                and error_message is None
                and type(getattr(run, "page_count", None)) is int
                and getattr(run, "page_count", None) == 0
                and getattr(run, "stop_reason", None) == "entry_confirmed"
            ):
                continue
            if (
                status == "failed"
                and error_type == self.NO_ACTION_ERROR_TYPE
                and error_message == self.NO_ACTION_REASON
                and getattr(run, "stop_reason", None) == self.NO_ACTION_REASON
                and getattr(run, "page_count", None) is None
            ):
                continue
            # Running, failed/unknown, contradictory and future statuses all
            # retain the write-ahead hold. Site snapshot is deliberately not
            # used to discard a run bound by the same stable source_id.
            blocked.add(source_id)
        return frozenset(blocked)

    @staticmethod
    def _has_conclusive_terminal_metadata(run: object) -> bool:
        if not hasattr(run, "finished_at"):
            return False
        finished_at = run.finished_at
        if isinstance(finished_at, str):
            try:
                finished_at = datetime.fromisoformat(finished_at)
            except ValueError:
                return False
        return (
            isinstance(finished_at, datetime)
            and finished_at.tzinfo is not None
            and finished_at.utcoffset() is not None
        )

    def evaluate_with_quota_access(
        self,
        source: Source,
        *,
        now: datetime,
        quota_available: int | None,
        allow_quota_access: bool,
    ) -> PolicyDecision:
        if type(allow_quota_access) is not bool:
            raise SitePolicyError("allow_quota_access must be a boolean")
        del allow_quota_access
        return self.evaluate(source, now=now, quota_available=quota_available)

    def supported_access_resources(self) -> tuple[str, ...]:
        return (
            self.TICKET_RESOURCE,
            self.WORK_TICKET_RESOURCE,
            self.BINGE_TICKET_RESOURCE,
        )

    def ordered_access_resource_passes(self) -> tuple[str, ...]:
        return (self.TICKET_RESOURCE,)

    def grant_only_supported_access_resources(self) -> tuple[str, ...]:
        return (self.WORK_TICKET_RESOURCE, self.BINGE_TICKET_RESOURCE)

    def resolve_grant_only_per_work(self) -> bool:
        return True

    def resolve_batch_quota_per_work(self) -> bool:
        return True

    def evaluate_for_quota_resource(
        self,
        source: Source,
        *,
        now: datetime,
        quota_available: int | None,
        quota_resource: str,
    ) -> PolicyDecision:
        self.validate_access_resource(quota_resource)
        decision = self.evaluate(source, now=now, quota_available=quota_available)
        if not decision.consumes_quota and decision.reason != "no_active_manual_grant":
            return decision
        return self._quota_decision(quota_resource)

    def evaluate(
        self,
        source: Source,
        *,
        now: datetime,
        quota_available: int | None,
    ) -> PolicyDecision:
        del quota_available
        if now.tzinfo is None or now.utcoffset() is None:
            raise SitePolicyError("now must be timezone-aware")
        if not source.available:
            return PolicyDecision(False, None, "unavailable")
        if source.access_mode == "free":
            return PolicyDecision(True, "direct", "free")
        if source.access_mode == "quota":
            grant_until = self._parse_grant_until(source.access_granted_until)
            if grant_until is not None and grant_until > now:
                return PolicyDecision(True, "direct", "active_manual_grant")
            return self._quota_decision(self.TICKET_RESOURCE)
        if source.access_mode == "paid":
            return PolicyDecision(False, None, "paid")
        if source.access_mode in {"owned", "grant", "rental"}:
            return PolicyDecision(False, None, "unsupported_access_mode")
        return PolicyDecision(False, None, "unknown")

    @staticmethod
    def _quota_decision(resource: str) -> PolicyDecision:
        reason = {
            PiccomaSitePolicy.TICKET_RESOURCE: "ticket_auto",
            PiccomaSitePolicy.WORK_TICKET_RESOURCE: "work_ticket",
            PiccomaSitePolicy.BINGE_TICKET_RESOURCE: "binge_ticket",
        }[resource]
        return PolicyDecision(
            True,
            "quota",
            reason,
            consumes_quota=True,
            quota_resource=resource,
            quota_scope="site",
            quota_limit=None,
            quota_commit_mode="after_observed_consumption",
        )

    @staticmethod
    def _parse_grant_until(value: datetime | str | None) -> datetime | None:
        if value is None:
            return None
        try:
            parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
        except ValueError as exc:
            raise SitePolicyError("access_granted_until must be a valid timestamp") from exc
        if not isinstance(parsed, datetime):
            raise SitePolicyError("access_granted_until must be a datetime or ISO timestamp")
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise SitePolicyError("access_granted_until must be timezone-aware")
        return parsed


def _positive_page_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


__all__ = ["PiccomaSitePolicy"]
