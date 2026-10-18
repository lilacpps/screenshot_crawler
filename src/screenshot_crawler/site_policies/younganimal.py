"""Younganimal free, rental, and work-ticket Batch access policy."""

from __future__ import annotations

from datetime import datetime, timedelta

from screenshot_crawler.catalog.models import Source
from screenshot_crawler.site_policies.base import (
    BatchOrdering,
    PolicyDecision,
    SitePolicy,
    SitePolicyError,
)


class YounganimalSitePolicy(SitePolicy):
    """Select free/rental direct sources and one eligible ticket per work."""

    site = "younganimal"

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
        self._require_aware(now, "now")
        self._require_aware(last_consumed_at, "last_consumed_at")
        if now < last_consumed_at + timedelta(hours=self._cooldown_hours(cooldown_hours)):
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
        self._require_aware(last_consumed_at, "last_consumed_at")
        return last_consumed_at + timedelta(hours=self._cooldown_hours(cooldown_hours))

    def evaluate(
        self,
        source: Source,
        *,
        now: datetime,
        quota_available: int | None,
    ) -> PolicyDecision:
        del quota_available
        if not source.available:
            return PolicyDecision(False, None, "unavailable")
        if source.access_mode == "free":
            return PolicyDecision(True, "direct", "free")
        if source.access_mode == "unknown":
            return PolicyDecision(False, None, "unknown")
        if source.access_mode == "quota":
            if now.tzinfo is None or now.utcoffset() is None:
                return PolicyDecision(False, None, "invalid_work_ticket_clock")
            grant = self._parse_grant_until(source.access_granted_until)
            if grant is not None and grant > now:
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
        if source.access_mode == "paid":
            if source.access_granted_until is not None:
                grant = self._parse_grant_until(source.access_granted_until)
                if grant is None or now.tzinfo is None or now.utcoffset() is None:
                    return PolicyDecision(False, None, "invalid_rental")
                if grant > now:
                    return PolicyDecision(True, "direct", "active_rental")
                return PolicyDecision(False, None, "expired_rental")
            return PolicyDecision(False, None, "paid")
        if source.access_mode == "owned":
            return PolicyDecision(False, None, "owned_not_verified")
        if source.access_mode == "grant":
            return PolicyDecision(False, None, "grant_not_supported")
        if source.access_mode == "rental":
            return PolicyDecision(False, None, "rental_not_supported")
        return PolicyDecision(False, None, "unsupported_access_mode")

    @staticmethod
    def _require_aware(value: datetime, name: str) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise SitePolicyError(f"{name} must be a timezone-aware datetime")

    @classmethod
    def _cooldown_hours(cls, value: int | None) -> int:
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
            raise SitePolicyError("cooldown_hours must be a non-negative integer")
        return max(23, value or 0)

    @classmethod
    def _parse_grant_until(cls, value: datetime | str | None) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError:
                return None
        else:
            return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed


__all__ = ["YounganimalSitePolicy"]
