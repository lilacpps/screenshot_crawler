"""Jump+ access policy for free episodes and manually rented episodes."""

from __future__ import annotations

from datetime import datetime

from screenshot_crawler.catalog.models import Source
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.site_policies.base import (
    BatchOrdering,
    PolicyDecision,
    SitePolicy,
    SitePolicyError,
)


class JumpPlusSitePolicy(SitePolicy):
    """Allow direct crawls for free episodes and active manual rentals.

    Jump+ does not expose a supported local quota/resource flow here.  A paid
    source is eligible only when Discovery observed a still-valid manual
    rental grant; otherwise the policy skips it without attempting purchase or
    rental controls.
    """

    site = "jumpplus"

    def batch_ordering(self) -> BatchOrdering:
        return "published_at"

    def evaluate(
        self,
        source: Source,
        *,
        now: datetime,
        quota_available: int | None,
    ) -> PolicyDecision:
        del quota_available
        current = _parse_aware(now, "now")
        if current is None:
            raise SitePolicyError("now must be a timezone-aware datetime")

        if not source.available:
            return PolicyDecision(False, None, "unavailable")
        if source.access_mode == "free":
            return PolicyDecision(True, "direct", "free")
        if source.access_mode == "paid":
            grant_until = _parse_aware(
                source.access_granted_until,
                "access_granted_until",
            )
            if grant_until is not None and grant_until > current:
                return PolicyDecision(
                    True,
                    "direct",
                    "active_rental",
                    consumes_quota=False,
                )
            if grant_until is not None:
                return PolicyDecision(False, None, "expired_rental")
            return PolicyDecision(False, None, "paid")
        if source.access_mode == "unknown":
            return PolicyDecision(False, None, "unknown")
        if source.access_mode == "quota":
            return PolicyDecision(False, None, "quota_not_supported")
        if source.access_mode == "owned":
            return PolicyDecision(False, None, "owned_not_verified")
        return PolicyDecision(False, None, "unsupported_access_mode")


def _parse_aware(value: datetime | str | None, field: str) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise SitePolicyError(f"Invalid {field} timestamp: {value!r}") from exc
    else:
        raise SitePolicyError(f"{field} must be a datetime, ISO timestamp, or null")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SitePolicyError(f"{field} must be timezone-aware")
    return parsed.astimezone(JST)
