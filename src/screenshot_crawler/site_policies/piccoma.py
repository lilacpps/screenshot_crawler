"""Direct-only Batch eligibility for unconditionally free Piccoma sources."""

from __future__ import annotations

from datetime import datetime

from screenshot_crawler.catalog.models import Source
from screenshot_crawler.site_policies.base import PolicyDecision, SitePolicy


class PiccomaSitePolicy(SitePolicy):
    """Allow only currently available sources classified as unconditionally free."""

    site = "piccoma"

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
        if source.access_mode in {"quota", "paid", "owned", "grant", "rental"}:
            return PolicyDecision(False, None, "unsupported_access_mode")
        return PolicyDecision(False, None, "unknown")


__all__ = ["PiccomaSitePolicy"]
