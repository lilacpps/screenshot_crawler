"""Hanayume free and work-ticket Batch access policy."""

from __future__ import annotations

from datetime import datetime, timedelta

from screenshot_crawler.catalog.models import Source
from screenshot_crawler.site_policies.base import (
    BatchOrdering,
    PolicyDecision,
    SitePolicy,
    SitePolicyError,
)


class HanayumeSitePolicy(SitePolicy):
    """Select free sources, active grants, and one ticket attempt per work."""

    site = "hanayume"

    def batch_ordering(self) -> BatchOrdering:
        return "catalog"

    def supported_access_resources(self) -> tuple[str, ...]:
        return ("work_ticket",)

    def ordered_access_resource_passes(self) -> tuple[str, ...]:
        return ("work_ticket",)

    def grant_only_supported_access_resources(self) -> tuple[str, ...]:
        return ("work_ticket",)

    def resource_state_scope(self, resource: str) -> str | None:
        return "work" if resource == "work_ticket" else None

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
        if resource != "work_ticket" or last_consumed_at is None:
            return None
        if now.tzinfo is None or now.utcoffset() is None:
            raise SitePolicyError("now must be a timezone-aware datetime")
        if last_consumed_at.tzinfo is None or last_consumed_at.utcoffset() is None:
            raise SitePolicyError("last_consumed_at must be timezone-aware")
        hours = self._cooldown_hours(cooldown_hours)
        if now < last_consumed_at + timedelta(hours=hours):
            return "work_ticket_cooldown"
        return None

    def grant_only_retry_at(
        self,
        *,
        resource: str,
        last_consumed_at: datetime | None,
        cooldown_hours: int | None,
    ) -> datetime | None:
        if resource != "work_ticket" or last_consumed_at is None:
            return None
        if last_consumed_at.tzinfo is None or last_consumed_at.utcoffset() is None:
            raise SitePolicyError("last_consumed_at must be timezone-aware")
        return last_consumed_at + timedelta(hours=self._cooldown_hours(cooldown_hours))

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
                True,
                "quota",
                "work_ticket_candidate",
                consumes_quota=True,
                quota_resource="work_ticket",
                quota_scope="work",
                quota_limit=1,
                quota_commit_mode="after_observed_consumption",
            )
        if source.access_mode == "unknown":
            return PolicyDecision(False, None, "unknown")
        if source.access_mode == "paid":
            return PolicyDecision(False, None, "paid")
        if source.access_mode == "owned":
            return PolicyDecision(False, None, "owned_not_verified")
        if source.access_mode == "grant":
            return PolicyDecision(False, None, "grant_not_supported")
        if source.access_mode == "rental":
            return PolicyDecision(False, None, "rental_not_supported")
        return PolicyDecision(False, None, "unsupported_access_mode")

    def access_grant_until(self, started_at: datetime) -> datetime:
        if started_at.tzinfo is None or started_at.utcoffset() is None:
            raise SitePolicyError("started_at must be a timezone-aware datetime")
        return started_at + timedelta(hours=72)

    @staticmethod
    def _cooldown_hours(value: int | None) -> int:
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            raise SitePolicyError("cooldown_hours must be a non-negative integer")
        # The site recovery period is a fixed 23 hours; a caller may request a
        # longer wait but cannot shorten the site's local cooldown safety bound.
        return max(23, value or 0)

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


__all__ = ["HanayumeSitePolicy"]
