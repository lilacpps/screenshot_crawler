"""Direct-only Batch eligibility for anonymous public-free ComicFUZ episodes."""

from __future__ import annotations

from datetime import datetime

from screenshot_crawler.catalog.models import Source
from screenshot_crawler.site_policies.base import PolicyDecision, SitePolicy, SitePolicyError


class ComicFuzSitePolicy(SitePolicy):
    """Permit only available Catalog sources observed as unconditionally free."""

    site = "comicfuz"

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
        if source.site != self.site:
            return PolicyDecision(False, None, "wrong_site")
        if not source.available:
            return PolicyDecision(False, None, "unavailable")
        if source.access_mode == "free":
            return PolicyDecision(True, "direct", "free")
        reason = {
            "unknown": "unknown",
            "quota": "quota_not_supported",
            "paid": "paid",
            "owned": "owned_not_verified",
            "grant": "grant_not_supported",
            "rental": "rental_not_supported",
        }.get(source.access_mode, "unknown")
        return PolicyDecision(False, None, reason)


__all__ = ["ComicFuzSitePolicy"]
