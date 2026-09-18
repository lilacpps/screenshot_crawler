"""BookWalker local quota and access policy."""

from __future__ import annotations

from collections.abc import Collection
from datetime import date, datetime, time, timedelta

from screenshot_crawler.catalog.models import Source
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.site_policies.base import (
    PolicyDecision,
    SitePolicy,
    SitePolicyError,
)

QUOTA_CAPACITY = 1
RESET_HOUR = 5


class BookWalkerSitePolicy(SitePolicy):
    """Conservative site-wide BookWalker quota policy.

    The local safety policy models one quota book per half-open window.  It is
    deliberately independent of BookWalker's server-side trial timer.
    """

    site = "bookwalker"
    quota_capacity = QUOTA_CAPACITY
    reset_hour = RESET_HOUR

    def available_quota(self, sources: Collection[Source], now: datetime) -> int:
        window_start, window_end = self.quota_window(now)
        used = 0
        for source in sources:
            started_at = _parse_aware(source.quota_started_at, "quota_started_at")
            if started_at is not None and window_start <= started_at < window_end:
                used += 1
        return max(0, QUOTA_CAPACITY - used)

    def access_grant_until(self, started_at: datetime) -> None:
        """BookWalker has no source-local grant window in this model."""

        del started_at

    def evaluate(
        self,
        source: Source,
        *,
        now: datetime,
        quota_available: int | None,
    ) -> PolicyDecision:
        current = _parse_aware(now, "now")
        if current is None:
            raise SitePolicyError("now must be an aware datetime")
        if not source.available:
            return PolicyDecision(False, None, "unavailable")
        if source.access_mode == "owned":
            return PolicyDecision(True, "direct", "owned")
        if source.access_mode == "quota":
            if quota_available is not None and quota_available <= 0:
                return PolicyDecision(False, None, "quota_exhausted")
            return PolicyDecision(True, "quota", "quota_available", consumes_quota=True)
        if source.access_mode == "paid":
            return PolicyDecision(False, None, "paid")
        if source.access_mode == "unknown":
            return PolicyDecision(False, None, "unknown")
        return PolicyDecision(False, None, "unsupported_access_mode")

    @staticmethod
    def quota_window(now: datetime) -> tuple[datetime, datetime]:
        """Return the current half-open 05:00 JST quota window."""

        current = _parse_aware(now, "now")
        if current is None:
            raise SitePolicyError("now must be an aware datetime")
        start = _at_jst(current.date(), RESET_HOUR)
        if current < start:
            start -= timedelta(days=1)
        return start, start + timedelta(days=1)


def _at_jst(day: date, hour: int) -> datetime:
    return datetime.combine(day, time(hour=hour), tzinfo=JST)


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
        raise SitePolicyError(f"{field} must be an aware datetime, ISO string, or null")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SitePolicyError(f"{field} must be timezone-aware")
    return parsed.astimezone(JST)
