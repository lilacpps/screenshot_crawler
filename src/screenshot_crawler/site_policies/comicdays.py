"""Comic DAYS access policy for free episodes and Work Tickets."""

from datetime import datetime, timedelta

from screenshot_crawler.catalog.models import Source
from screenshot_crawler.site_policies.base import (
    BatchOrdering,
    PolicyDecision,
    SitePolicy,
    SitePolicyError,
)


class ComicDaysSitePolicy(SitePolicy):
    site = "comicdays"

    def batch_ordering(self) -> BatchOrdering:
        return "catalog"

    def supported_access_resources(self) -> tuple[str, ...]:
        return ("work_ticket",)

    def ordered_access_resource_passes(self) -> tuple[str, ...]:
        return ("work_ticket",)

    def grant_only_supported_access_resources(self) -> tuple[str, ...]:
        return ("work_ticket",)

    def resource_state_scope(self, resource: str) -> str | None:
        if resource == "work_ticket":
            return "work"
        return None

    def defer_quota_access_to_grant_phase(self) -> bool:
        return True

    def grant_only_skip_reason(
        self,
        *,
        resource: str,
        last_consumed_at: datetime | None,
        now: datetime,
        cooldown_hours: int | None,
    ) -> str | None:
        if resource != "work_ticket" or last_consumed_at is None:
            return None
        if now.tzinfo is None or now.utcoffset() is None:
            raise SitePolicyError("now must be a timezone-aware datetime")
        if last_consumed_at.tzinfo is None or last_consumed_at.utcoffset() is None:
            raise SitePolicyError("last_consumed_at must be timezone-aware")
        hours = 23 if cooldown_hours is None else cooldown_hours
        if isinstance(hours, bool) or not isinstance(hours, int) or hours < 0:
            raise SitePolicyError("cooldown_hours must be a non-negative integer")
        if now < last_consumed_at + timedelta(hours=hours):
            return "work_ticket_cooldown"
        return None

    def evaluate(
        self,
        source: Source,
        *,
        now: datetime,
        quota_available: int | None,
    ) -> PolicyDecision:
        del quota_available
        if now.tzinfo is None or now.utcoffset() is None:
            raise SitePolicyError("now must be a timezone-aware datetime")
        if not source.available:
            return PolicyDecision(False, None, "unavailable")
        if source.access_mode == "free":
            return PolicyDecision(True, "direct", "free")
        if source.access_mode == "quota":
            grant_until = self._parse_grant_until(source.access_granted_until)
            if grant_until is not None and grant_until > now:
                return PolicyDecision(True, "direct", "active_work_ticket_grant")
            return PolicyDecision(
                True, "quota", "work_ticket_candidate", consumes_quota=True,
                quota_resource="work_ticket", quota_scope="work", quota_limit=None,
                quota_commit_mode="after_observed_consumption",
            )
        if source.access_mode == "paid":
            return PolicyDecision(False, None, "paid")
        if source.access_mode in {"owned", "rental", "grant"}:
            return PolicyDecision(False, None, "unsupported_access_mode")
        return PolicyDecision(False, None, "unknown")

    def access_grant_until(self, started_at: datetime) -> datetime:
        """Use a conservative local fallback; Discovery prefers native expiry."""
        if started_at.tzinfo is None or started_at.utcoffset() is None:
            raise SitePolicyError("started_at must be timezone-aware")
        return started_at + timedelta(hours=71)

    @staticmethod
    def _parse_grant_until(value: datetime | str | None) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError as exc:
                raise SitePolicyError("access_granted_until must be a valid timestamp") from exc
        else:
            raise SitePolicyError("access_granted_until must be a datetime or ISO timestamp")
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise SitePolicyError("access_granted_until must be timezone-aware")
        return parsed
