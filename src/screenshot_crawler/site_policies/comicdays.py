"""Free-only policy for Comic DAYS."""

from datetime import datetime

from screenshot_crawler.catalog.models import Source
from screenshot_crawler.site_policies.base import (
    BatchOrdering,
    PolicyDecision,
    SitePolicy,
    SitePolicyError,
)


class ComicDaysSitePolicy(SitePolicy):
    site = "comicdays"

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
        if now.tzinfo is None or now.utcoffset() is None:
            raise SitePolicyError("now must be a timezone-aware datetime")
        if not source.available:
            return PolicyDecision(False, None, "unavailable")
        if source.access_mode == "free":
            return PolicyDecision(True, "direct", "free")
        if source.access_mode in {"paid", "quota"}:
            return PolicyDecision(False, None, "paid_not_supported")
        if source.access_mode in {"owned", "rental", "grant"}:
            return PolicyDecision(False, None, "owned_or_grant_not_supported")
        return PolicyDecision(False, None, "unknown")
