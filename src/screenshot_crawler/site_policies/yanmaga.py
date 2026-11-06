"""Direct-only Batch eligibility for currently public-free Yanmaga sources."""

from __future__ import annotations

import re
from datetime import datetime

from screenshot_crawler.catalog.models import Source
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.site_policies.base import (
    PolicyDecision,
    SitePolicy,
    SitePolicyError,
)

_EXTERNAL_ID = re.compile(r"^(?P<slug>.+):(?P<episode>[0-9a-f]{32})$")


class YanmagaSitePolicy(SitePolicy):
    """Select only available free rows and never enter a resource pass."""

    site = "yanmaga"

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
        current = now.astimezone(JST)

        if source.site != self.site:
            return PolicyDecision(False, None, "wrong_site")
        if not source.available:
            return PolicyDecision(False, None, "unavailable")
        if source.access_mode != "free":
            reason = {
                "quota": "quota_not_supported",
                "paid": "paid",
                "owned": "owned_not_verified",
                "grant": "grant_not_supported",
                "rental": "rental_not_supported",
            }.get(source.access_mode, "unknown")
            return PolicyDecision(False, None, reason)
        if not self._valid_external_id(source.external_id):
            return PolicyDecision(False, None, "invalid_episode_identity")

        try:
            expiry = self._parse_free_until(source.free_until)
        except (TypeError, ValueError):
            return PolicyDecision(False, None, "invalid_free_until")
        if expiry is not None and expiry <= current:
            return PolicyDecision(False, None, "expired_free")
        return PolicyDecision(True, "direct", "free")

    @staticmethod
    def _valid_external_id(value: object) -> bool:
        if not isinstance(value, str):
            return False
        match = _EXTERNAL_ID.fullmatch(value)
        if match is None:
            return False
        slug = match.group("slug")
        return (
            slug not in {".", ".."}
            and "/" not in slug
            and "\\" not in slug
            and "\x00" not in slug
        )

    @staticmethod
    def _parse_free_until(value: datetime | str | None) -> datetime | None:
        if value is None:
            return None
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
        if not isinstance(parsed, datetime):
            raise TypeError("free_until must be a datetime, ISO timestamp, or null")
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("free_until must be timezone-aware")
        return parsed.astimezone(JST)


__all__ = ["YanmagaSitePolicy"]
