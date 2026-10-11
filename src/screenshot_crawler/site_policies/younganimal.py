"""Direct-only Batch eligibility for available Younganimal sources marked free."""

from __future__ import annotations

from datetime import datetime

from screenshot_crawler.catalog.models import Source
from screenshot_crawler.site_policies.base import PolicyDecision, SitePolicy


class YounganimalSitePolicy(SitePolicy):
    """Allow only currently available Catalog sources classified exactly free."""

    site = "younganimal"

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
        if source.access_mode == "unknown":
            return PolicyDecision(False, None, "unknown")
        if source.access_mode == "quota":
            return PolicyDecision(False, None, "quota_not_supported")
        if source.access_mode == "paid":
            return PolicyDecision(False, None, "paid")
        if source.access_mode == "owned":
            return PolicyDecision(False, None, "owned_not_verified")
        if source.access_mode == "grant":
            return PolicyDecision(False, None, "grant_not_supported")
        if source.access_mode == "rental":
            return PolicyDecision(False, None, "rental_not_supported")
        return PolicyDecision(False, None, "unsupported_access_mode")


__all__ = ["YounganimalSitePolicy"]
