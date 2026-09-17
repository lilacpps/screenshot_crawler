"""Manga ONE local quota and access policy for Phase 5A planning."""

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

QUOTA_CAPACITY = 4
GRANT_DURATION = timedelta(hours=24)
RESET_HOURS = (9, 21)


class MangaOneSitePolicy(SitePolicy):
    """Model Manga ONE's free-life windows using Catalog-local observations."""

    site = "mangaone"
    quota_capacity = QUOTA_CAPACITY
    grant_duration = GRANT_DURATION
    reset_hours = RESET_HOURS

    def access_grant_until(self, started_at: datetime) -> datetime:
        parsed = _parse_aware(started_at, "started_at")
        if parsed is None:
            raise SitePolicyError("started_at must be an aware datetime")
        return parsed + GRANT_DURATION

    def available_quota(self, sources: Collection[Source], now: datetime) -> int:
        window_start, window_end = self.quota_window(now)
        used = 0
        for source in sources:
            started_at = _parse_aware(source.quota_started_at, "quota_started_at")
            if started_at is not None and window_start <= started_at < window_end:
                used += 1
        return max(0, QUOTA_CAPACITY - used)

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
        if source.access_mode == "free":
            return PolicyDecision(True, "direct", "free")
        if source.access_mode == "owned":
            return PolicyDecision(True, "direct", "owned")
        if source.access_mode == "paid":
            return PolicyDecision(False, None, "paid")
        if source.access_mode == "unknown":
            return PolicyDecision(False, None, "unknown")
        if source.access_mode != "quota":
            return PolicyDecision(False, None, "unsupported_access_mode")

        grant_until = _parse_aware(source.access_granted_until, "access_granted_until")
        if grant_until is not None and grant_until > current:
            return PolicyDecision(True, "direct", "active_grant")
        if quota_available is not None and quota_available <= 0:
            return PolicyDecision(False, None, "quota_exhausted")
        return PolicyDecision(True, "quota", "quota_available", consumes_quota=True)

    @staticmethod
    def quota_window(now: datetime) -> tuple[datetime, datetime]:
        """Return the current half-open 12-hour reset window in JST."""

        current = _parse_aware(now, "now")
        if current is None:
            raise SitePolicyError("now must be an aware datetime")
        today = current.date()
        morning = _at_jst(today, RESET_HOURS[0])
        evening = _at_jst(today, RESET_HOURS[1])
        if current < morning:
            start = morning - timedelta(hours=12)
        elif current < evening:
            start = morning
        else:
            start = evening
        return start, start + timedelta(hours=12)


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
