"""Direct-only Batch eligibility for Younganimal free episodes and active rentals."""

from __future__ import annotations

from datetime import datetime

from screenshot_crawler.catalog.models import Source
from screenshot_crawler.site_policies.base import PolicyDecision, SitePolicy


class YounganimalSitePolicy(SitePolicy):
    """Allow available free sources and unexpired observed rental grants."""

    site = "younganimal"

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
            return PolicyDecision(False, None, "quota_not_supported")
        if source.access_mode == "paid":
            if source.access_granted_until is not None:
                try:
                    grant = datetime.fromisoformat(source.access_granted_until)
                except ValueError:
                    return PolicyDecision(False, None, "invalid_rental")
                if grant.tzinfo is None or grant.utcoffset() is None:
                    return PolicyDecision(False, None, "invalid_rental")
                if now.tzinfo is None or now.utcoffset() is None:
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


__all__ = ["YounganimalSitePolicy"]
