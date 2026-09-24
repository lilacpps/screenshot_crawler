"""Small contract for site-specific Batch access policies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from screenshot_crawler.catalog.models import Source

BatchAccessStrategy = Literal["direct", "quota"]
BatchOrdering = Literal["catalog", "published_at"]


class SitePolicyError(RuntimeError):
    """Raised when a Site Policy cannot evaluate a source safely."""


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """Result of evaluating one Catalog source."""

    eligible: bool
    access_strategy: BatchAccessStrategy | None
    reason: str
    consumes_quota: bool = False
    quota_resource: str | None = None
    quota_scope: Literal["site", "work"] = "site"
    quota_limit: int | None = None
    quota_commit_mode: Literal["before_run", "after_observed_consumption"] = "before_run"


class SitePolicy(ABC):
    """Site-specific eligibility and access-strategy boundary."""

    site: str

    def batch_ordering(self) -> BatchOrdering:
        """Return the site-owned ordering strategy for Batch candidates."""

        return "catalog"

    def available_quota(self, sources: Collection[Source], now: datetime) -> int | None:
        """Return local quota slots, or ``None`` for policies without quota."""

        del sources, now
        return None

    def access_grant_until(self, started_at: datetime) -> datetime | None:
        """Return the local access grant expiry for a newly used quota."""

        del started_at
        return None

    def supported_access_resources(self) -> tuple[str, ...]:
        """Return all named resources this policy can explicitly select."""

        return self.ordered_access_resource_passes()

    def ordered_access_resource_passes(self) -> tuple[str, ...]:
        """Return policy-ordered named resource passes, including the default pass."""

        # Keep the existing extension point usable for policies implemented
        # before the generic contract was introduced.
        return self.additional_quota_resources()

    def additional_quota_resources(self) -> tuple[str, ...]:
        """Compatibility hook for resource passes after the default pass."""

        return ()

    def additional_access_resource_passes(self) -> tuple[str, ...]:
        """Return explicit passes that follow the normal/default Batch pass."""

        ordered = self.ordered_access_resource_passes()
        if type(self).ordered_access_resource_passes is SitePolicy.ordered_access_resource_passes:
            return self.additional_quota_resources()
        if ordered:
            return ordered[1:]
        return self.additional_quota_resources()

    # Short aliases keep integrations independent of the persisted
    # ``quota_resource`` field name without introducing a second contract.
    def supported_resources(self) -> tuple[str, ...]:
        return self.supported_access_resources()

    def ordered_resource_passes(self) -> tuple[str, ...]:
        return self.ordered_access_resource_passes()

    def validate_access_resource(self, resource: str) -> None:
        """Reject a resource that this policy cannot safely plan."""

        if resource not in self.supported_access_resources():
            raise SitePolicyError(
                f"Unsupported access resource for site {self.site}: {resource}"
            )

    def grant_only_supported_access_resources(self) -> tuple[str, ...]:
        """Return resources whose grant-only flow this policy supports now."""

        return ()

    def validate_grant_only_resource(self, resource: str) -> None:
        if resource not in self.grant_only_supported_access_resources():
            raise SitePolicyError(
                f"Grant-only access resource is not implemented for site {self.site}: "
                f"{resource}"
            )

    def grant_only_skip_reason(
        self,
        *,
        resource: str,
        last_consumed_at: datetime | None,
        now: datetime,
        cooldown_hours: int | None,
    ) -> str | None:
        """Return a local-only skip reason, without inspecting site state."""

        del resource, last_consumed_at, now, cooldown_hours
        return None

    def grant_only_unavailable_reason(self, resource: str) -> str:
        return f"{resource}_unavailable"

    def resource_state_scope(self, resource: str) -> Literal["work"] | None:
        """Return the Catalog state scope for confirmed resource use, if any."""

        del resource
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

    def evaluate_for_quota_resource(
        self,
        source: Source,
        *,
        now: datetime,
        quota_available: int | None,
        quota_resource: str,
    ) -> PolicyDecision:
        """Evaluate a candidate for an explicitly requested quota resource.

        Policies may opt into additional resource passes while keeping resource
        semantics outside the planner and Core.
        """

        self.validate_access_resource(quota_resource)
        decision = self.evaluate(
            source,
            now=now,
            quota_available=quota_available,
        )
        if decision.consumes_quota and decision.quota_resource != quota_resource:
            raise SitePolicyError(
                f"{type(self).__name__} does not support "
                f"quota_resource={quota_resource!r}"
            )
        return decision
