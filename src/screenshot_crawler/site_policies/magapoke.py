"""Magapoke free-only Batch access policy for M2."""

from __future__ import annotations

from datetime import datetime

from screenshot_crawler.catalog.models import Source
from screenshot_crawler.site_policies.base import PolicyDecision, SitePolicy, SitePolicyError


class MagapokeSitePolicy(SitePolicy):
    """Allow only observed free episodes through direct navigation."""

    site = "magapoke"

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
            return PolicyDecision(False, None, "quota_not_supported")
        if source.access_mode == "paid":
            return PolicyDecision(False, None, "paid")
        if source.access_mode == "unknown":
            return PolicyDecision(False, None, "unknown")
        if source.access_mode == "owned":
            return PolicyDecision(False, None, "owned_not_verified")
        return PolicyDecision(False, None, "unsupported_access_mode")
