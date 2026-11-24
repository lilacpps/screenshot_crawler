"""Free and already-granted direct Batch selection for HERO'S WEB."""

from __future__ import annotations

from datetime import datetime

from screenshot_crawler.catalog.models import Source
from screenshot_crawler.site_policies.base import (
    BatchOrdering,
    PolicyDecision,
    SitePolicy,
)


class HeroswebSitePolicy(SitePolicy):
    """Allow free sources and finite active rentals without consuming tickets."""

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
        del quota_available
        if not source.available:
            return PolicyDecision(False, None, "unavailable")
        if source.access_mode == "free":
            return PolicyDecision(True, "direct", "free")
        if source.access_mode == "quota" and now.tzinfo is not None and now.utcoffset() is not None:
            try:
                grant = datetime.fromisoformat(source.access_granted_until or "")
            except (TypeError, ValueError):
                grant = None
            if (grant is not None and grant.tzinfo is not None
                    and grant.utcoffset() is not None and grant > now):
                return PolicyDecision(True, "direct", "active_rental")
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
            pending_quota=source.access_mode == "quota",
        )


__all__ = ["HeroswebSitePolicy"]
