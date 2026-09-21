"""Batch planning result models."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

BatchAccessStrategy = Literal["direct", "quota"]


class BatchPlanningError(RuntimeError):
    """Raised when a Batch Plan cannot be generated safely."""


class BatchExecutionError(RuntimeError):
    """Raised when a Batch candidate cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class BatchCandidate:
    """One source selected for a future site-neutral Crawl Request."""

    item_id: int
    source_id: int
    target_id: int
    site: str
    backend: str
    target_key: str
    locator: str
    access_strategy: BatchAccessStrategy
    metadata: dict[str, str] = field(default_factory=dict)
    access_mode: str = "unknown"
    reason: str = ""
    consumes_quota: bool = False
    artifact_disambiguator: str | None = None


@dataclass(frozen=True, slots=True)
class BatchSkipped:
    """One item or source omitted from a Batch Plan."""

    item_id: int
    source_id: int | None
    reason: str


@dataclass(slots=True)
class BatchPlan:
    """Read-only plan containing selected candidates and skip details."""

    candidates: list[BatchCandidate] = field(default_factory=list)
    skipped: list[BatchSkipped] = field(default_factory=list)
    quota_available: int | None = None
    quota_remaining: int | None = None

    @property
    def direct_count(self) -> int:
        return sum(candidate.access_strategy == "direct" for candidate in self.candidates)

    @property
    def quota_count(self) -> int:
        return sum(candidate.access_strategy == "quota" for candidate in self.candidates)


@dataclass(frozen=True, slots=True)
class BatchExecutionResult:
    """Archive and crawl status corresponding to one executed candidate."""

    item_id: int
    source_id: int
    target_id: int
    crawl_run_id: int
    artifact_id: int
    archive_path: Path
    status_path: Path
    page_count: int
    stop_reason: str
