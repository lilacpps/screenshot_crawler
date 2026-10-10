"""Direct-only Batch eligibility for free and manually unlocked Piccoma sources."""

from __future__ import annotations

from datetime import datetime

from screenshot_crawler.catalog.models import Source
from screenshot_crawler.site_policies.base import PolicyDecision, SitePolicy, SitePolicyError


class PiccomaSitePolicy(SitePolicy):
    """Allow free access and observed active grants without resource consumption."""

    site = "piccoma"

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
        if not source.available:
            return PolicyDecision(False, None, "unavailable")
        if source.access_mode == "free":
            return PolicyDecision(True, "direct", "free")
        if source.access_mode == "quota":
            grant_until = self._parse_grant_until(source.access_granted_until)
            if grant_until is not None and grant_until > now:
                return PolicyDecision(True, "direct", "active_manual_grant")
            return PolicyDecision(False, None, "no_active_manual_grant")
        if source.access_mode in {"paid", "owned", "grant", "rental"}:
            return PolicyDecision(False, None, "unsupported_access_mode")
        return PolicyDecision(False, None, "unknown")

    @staticmethod
    def _parse_grant_until(value: datetime | str | None) -> datetime | None:
        if value is None:
            return None
        try:
            parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
        except ValueError as exc:
            raise SitePolicyError("access_granted_until must be a valid timestamp") from exc
        if not isinstance(parsed, datetime):
            raise SitePolicyError("access_granted_until must be a datetime or ISO timestamp")
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise SitePolicyError("access_granted_until must be timezone-aware")
        return parsed


__all__ = ["PiccomaSitePolicy"]
