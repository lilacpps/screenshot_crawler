"""Zeblack access policy for live Work Ticket entry."""

from __future__ import annotations

from datetime import datetime

from screenshot_crawler.catalog.models import Source
from screenshot_crawler.site_policies.base import PolicyDecision, SitePolicy


class ZeblackSitePolicy(SitePolicy):
    """Keep broad Catalog quota candidates and defer availability to live state."""

    site = "zeblack"

    def supported_access_resources(self) -> tuple[str, ...]:
        return ("work_ticket",)

    def ordered_access_resource_passes(self) -> tuple[str, ...]:
        return ("work_ticket",)

    def grant_only_supported_access_resources(self) -> tuple[str, ...]:
        return ("work_ticket",)

    def evaluate(
        self,
        source: Source,
        *,
        now: datetime,
        quota_available: int | None,
    ) -> PolicyDecision:
        del now, quota_available
        if not source.available:
            return PolicyDecision(False, None, "unavailable")
        if source.access_mode == "free":
            return PolicyDecision(True, "direct", "free")
        if source.access_mode == "quota":
            return PolicyDecision(
                True,
                "quota",
                "work_ticket_candidate",
                consumes_quota=True,
                quota_resource="work_ticket",
                quota_scope="work",
                quota_limit=None,
                quota_commit_mode="after_observed_consumption",
            )
        if source.access_mode == "paid":
            return PolicyDecision(False, None, "paid")
        if source.access_mode == "unknown":
            return PolicyDecision(False, None, "unknown")
        if source.access_mode == "owned":
            return PolicyDecision(False, None, "owned_not_verified")
        return PolicyDecision(False, None, "unsupported_access_mode")


__all__ = ["ZeblackSitePolicy"]
