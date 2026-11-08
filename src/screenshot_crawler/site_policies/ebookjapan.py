"""Direct-only eligibility for Catalog sources discovered as ebookjapan-owned."""

from __future__ import annotations

from datetime import datetime

from screenshot_crawler.catalog.models import Source
from screenshot_crawler.site_policies.base import (
    BatchOrdering,
    PolicyDecision,
    SitePolicy,
    SitePolicyError,
)


class EbookJapanSitePolicy(SitePolicy):
    """Plan only available ebookjapan sources marked owned in the Catalog.

    The decision is a Batch planning filter, not live ownership proof. The
    adapter must verify the current purchased right again before opening the
    Reader.
    """

    site = "ebookjapan"

    def batch_ordering(self) -> BatchOrdering:
        return "display_position"

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
        if source.access_mode == "owned":
            if type(source.display_position) is not int or source.display_position < 1:
                return PolicyDecision(False, None, "owned_display_position_invalid")
            return PolicyDecision(
                True,
                "direct",
                "catalog_owned_candidate",
                consumes_quota=False,
            )
        reason = {
            "free": "free_not_supported",
            "quota": "quota_not_supported",
            "paid": "paid",
            "grant": "grant_not_supported",
            "rental": "rental_not_supported",
            "unknown": "unknown",
        }.get(source.access_mode, "unsupported_access_mode")
        return PolicyDecision(False, None, reason)


__all__ = ["EbookJapanSitePolicy"]
