from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ContentIdentity:
    """Identity of the currently displayed page.

    Every field is optional because available signals differ by site.
    Site adapters should populate the strongest stable signals they can obtain.
    """

    page_id: str | None = None
    page_number: int | None = None
    source_id: str | None = None
    fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class ContentContext:
    """Identity of the work/episode/chapter being captured."""

    content_id: str | None = None
    work_id: str | None = None
    episode_id: str | None = None
    chapter_id: str | None = None
    title: str | None = None


@dataclass(slots=True)
class CapturedPage:
    sequence: int
    file: Path
    identity: ContentIdentity
    width: int | None = None
    height: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RunConfig:
    site: str
    source_url: str
    output_dir: Path
    diagnostics_dir: Path
    viewport_width: int = 1920
    viewport_height: int = 1080
    max_pages: int = 1000
    max_same_content: int = 3
    retry_count: int = 3
    navigation_timeout_ms: int = 10_000
    page_change_timeout_ms: int = 10_000
    auth_state: Path | None = None
    auth_required: bool = False
    device_scale_factor: float = 1.0
