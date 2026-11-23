"""Free-only direct Batch selection for HERO'S WEB."""

from __future__ import annotations

from datetime import datetime

from screenshot_crawler.catalog.models import Source
from screenshot_crawler.site_policies.base import (
    BatchOrdering,
    PolicyDecision,
    SitePolicy,
)


class HeroswebSitePolicy(SitePolicy):
    """Allow only currently available sources classified as directly free."""

    site = "herosweb"

    def batch_ordering(self) -> BatchOrdering:
        return "catalog"

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
        reasons = {
            "quota": "quota_not_supported",
            "paid": "paid_not_supported",
            "unknown": "unknown",
            "owned": "owned_not_supported",
            "rental": "rental_not_supported",
            "grant": "grant_not_supported",
        }
        return PolicyDecision(
            False,
            None,
            reasons.get(source.access_mode, "unsupported_access_mode"),
        )


__all__ = ["HeroswebSitePolicy"]
