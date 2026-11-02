"""Immutable URL evidence, independent of Watchlist registration readiness."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal


@dataclass(frozen=True, slots=True)
class ObservedUrlConversion:
    input_url: str
    site: str
    observation_url: str
    discovery_url: str
    site_work_identity: str
    selected_external_id: str
    dom_index: int
    row_count: int
    selection_evidence: tuple[str, ...]
    observed_at: datetime


def conversion_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class UrlResolution:
    input_url: str
    site: str | None = None
    discovery_url: str | None = None
    site_work_identity: str | None = None
    title: str | None = None
    status: Literal["valid", "converted", "blocked"] = "blocked"
    evidence: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    observation_url: str | None = None
    conversion_proof: ObservedUrlConversion | None = None

    @property
    def identity_status(self) -> str:
        return "verified" if self.site_work_identity else "unknown"

    @property
    def title_status(self) -> str:
        return "observed" if self.title else "unknown"

    def blocked(self, reason: str) -> "UrlResolution":
        return replace(self, status="blocked", conversion_proof=None, blockers=(*self.blockers, reason))


def resolved_url(url: str, canonical: str, identity: str | None = None) -> UrlResolution:
    """Site hooks call this only after their existing parser accepts the URL."""
    return UrlResolution(
        input_url=url, discovery_url=canonical, site_work_identity=identity,
        status="valid" if url == canonical else "converted",
        evidence=("site parser: canonical Discovery entry",),
        warnings=("作品名・Work・IDを明示確認してください",),
    )
