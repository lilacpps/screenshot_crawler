"""Batch eligibility for public-free, existing-grant, and work-ticket sources."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from screenshot_crawler.catalog.models import Source
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.site_policies.base import (
    BatchOrdering,
    PolicyDecision,
    SitePolicy,
    SitePolicyError,
)

_EXTERNAL_ID = re.compile(r"^(?P<slug>.+):(?P<episode>[0-9a-f]{32})$")


class YanmagaSitePolicy(SitePolicy):
    """Select public-free rows and the observed work-ticket resource pass."""

    site = "yanmaga"

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
        if now.astimezone(JST) < last_consumed_at.astimezone(JST) + timedelta(
            hours=self._cooldown_hours(cooldown_hours)
        ):
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
        return last_consumed_at.astimezone(JST) + timedelta(
            hours=self._cooldown_hours(cooldown_hours)
        )

    def allows_automatic_candidate_retry(self) -> bool:
        # Even a nominally free/direct episode GET may initiate first-free rental.
        # Preserve the existing no-entry-replay contract until there is explicit
        # operation-stage evidence that can authorize a narrower retry.
        return False

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
        current = now.astimezone(JST)

        if source.site != self.site:
            return PolicyDecision(False, None, "wrong_site")
        if not source.available:
            return PolicyDecision(False, None, "unavailable")
        if source.access_granted_until is not None:
            try:
                self._parse_grant_until(source.access_granted_until)
            except (TypeError, ValueError):
                return PolicyDecision(False, None, "invalid_access_grant_until")
        if source.access_mode in {"quota", "paid"}:
            try:
                grant_until = self._parse_grant_until(source.access_granted_until)
            except (TypeError, ValueError):
                return PolicyDecision(False, None, "invalid_access_grant_until")
            if grant_until is not None and grant_until > current:
                if not self._valid_external_id(source.external_id):
                    return PolicyDecision(False, None, "invalid_episode_identity")
                return PolicyDecision(True, "direct", "active_confirmed_grant")
            if source.access_mode == "quota":
                if not self._valid_external_id(source.external_id):
                    return PolicyDecision(False, None, "invalid_episode_identity")
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
            if grant_until is not None:
                return PolicyDecision(False, None, "expired_access_grant")
            # Inventory uses this reason to count point-only rows as paid.
            return PolicyDecision(False, None, "paid")
        if source.access_mode != "free":
            reason = {
                "owned": "owned_not_verified",
                "grant": "grant_not_supported",
                "rental": "rental_not_supported",
            }.get(source.access_mode, "unknown")
            return PolicyDecision(False, None, reason)
        if not self._valid_external_id(source.external_id):
            return PolicyDecision(False, None, "invalid_episode_identity")

        try:
            expiry = self._parse_free_until(source.free_until)
        except (TypeError, ValueError):
            return PolicyDecision(False, None, "invalid_free_until")
        if expiry is not None and expiry <= current:
            return PolicyDecision(False, None, "expired_free")
        return PolicyDecision(True, "direct", "free")

    @staticmethod
    def _valid_external_id(value: object) -> bool:
        if not isinstance(value, str):
            return False
        match = _EXTERNAL_ID.fullmatch(value)
        if match is None:
            return False
        slug = match.group("slug")
        return (
            slug not in {".", ".."}
            and "/" not in slug
            and "\\" not in slug
            and "\x00" not in slug
        )

    @staticmethod
    def _parse_free_until(value: datetime | str | None) -> datetime | None:
        if value is None:
            return None
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
        if not isinstance(parsed, datetime):
            raise TypeError("free_until must be a datetime, ISO timestamp, or null")
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("free_until must be timezone-aware")
        return parsed.astimezone(JST)

    @staticmethod
    def _parse_grant_until(value: datetime | str | None) -> datetime | None:
        if value is None:
            return None
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
        if not isinstance(parsed, datetime):
            raise TypeError("access_granted_until must be a datetime, ISO timestamp, or null")
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("access_granted_until must be timezone-aware")
        return parsed.astimezone(JST)

    @staticmethod
    def _require_aware(value: datetime, name: str) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise SitePolicyError(f"{name} must be a timezone-aware datetime")

    @staticmethod
    def _cooldown_hours(value: int | None) -> int:
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            raise SitePolicyError("cooldown_hours must be a non-negative integer")
        return max(23, value or 0)


__all__ = ["YanmagaSitePolicy"]
