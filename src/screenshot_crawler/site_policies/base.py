"""Small contract for site-specific Batch access policies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from screenshot_crawler.catalog.models import Source

BatchAccessStrategy = Literal["direct", "quota"]


class SitePolicyError(RuntimeError):
    """Raised when a Site Policy cannot evaluate a source safely."""


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """Result of evaluating one Catalog source."""

    eligible: bool
    access_strategy: BatchAccessStrategy | None
    reason: str
    consumes_quota: bool = False


class SitePolicy(ABC):
    """Site-specific eligibility and access-strategy boundary."""

    site: str

    def available_quota(self, sources: Collection[Source], now: datetime) -> int | None:
        """Return local quota slots, or ``None`` for policies without quota."""

        del sources, now
        return None

    @abstractmethod
    def evaluate(
        self,
        source: Source,
        *,
        now: datetime,
        quota_available: int | None,
    ) -> PolicyDecision:
        """Evaluate one source without mutating Catalog or external state."""

        raise NotImplementedError
