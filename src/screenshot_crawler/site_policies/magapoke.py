"""Magapoke direct access policy for free episodes and active rentals."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from screenshot_crawler.catalog.models import Source
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.site_policies.base import PolicyDecision, SitePolicy, SitePolicyError


class MagapokeSitePolicy(SitePolicy):
    """Allow free episodes and observed active rentals through direct navigation."""

    site = "magapoke"

    def supported_access_resources(self) -> tuple[str, ...]:
        return ("work_ticket", "premium_ticket")

    def ordered_access_resource_passes(self) -> tuple[str, ...]:
        return ("work_ticket", "premium_ticket")

    def additional_quota_resources(self) -> tuple[str, ...]:
        """Compatibility view of passes after the normal Work Ticket pass."""

        return ("premium_ticket",)

    def access_grant_until(self, started_at: datetime) -> datetime:
        if started_at.tzinfo is None or started_at.utcoffset() is None:
            raise SitePolicyError("started_at must be timezone-aware")
        return started_at + timedelta(hours=71)

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
                return PolicyDecision(
                    True,
                    "direct",
                    "active_rental",
                    consumes_quota=False,
                )
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
            return PolicyDecision(False, None, "paid")
        if source.access_mode == "unknown":
            return PolicyDecision(False, None, "unknown")
        if source.access_mode == "owned":
            return PolicyDecision(False, None, "owned_not_verified")
        return PolicyDecision(False, None, "unsupported_access_mode")

    def evaluate_for_quota_resource(
        self,
        source: Source,
        *,
        now: datetime,
        quota_available: int | None,
        quota_resource: str,
    ) -> PolicyDecision:
        decision = self.evaluate(
            source,
            now=now,
            quota_available=quota_available,
        )
        if not decision.consumes_quota:
            return decision
        if quota_resource == "work_ticket":
            return decision
        if quota_resource == "premium_ticket":
            return replace(
                decision,
                reason="premium_ticket_candidate",
                quota_resource="premium_ticket",
                quota_scope="work",
                quota_limit=None,
                quota_commit_mode="after_observed_consumption",
            )
        raise SitePolicyError(
            f"MagapokeSitePolicy does not support quota_resource={quota_resource!r}"
        )

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
                raise SitePolicyError(
                    "access_granted_until must be a valid timestamp"
                ) from exc
        else:
            raise SitePolicyError(
                "access_granted_until must be a datetime or ISO timestamp"
            )
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise SitePolicyError("access_granted_until must be timezone-aware")
        return parsed.astimezone(JST)
