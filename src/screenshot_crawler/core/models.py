from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

AccessStrategy = Literal["auto", "direct", "quota"]
VALID_ACCESS_STRATEGIES = frozenset({"auto", "direct", "quota"})
OUTPUT_METADATA_FIELDS = frozenset({"title", "author", "order", "genre"})


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
    mime_type: str = "image/png"
    file_extension: str = ".png"
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
    adapter_timeout_grace_ms: int = 2_000
    auth_state: Path | None = None
    auth_required: bool = False
    device_scale_factor: float = 1.0
    access_strategy: AccessStrategy = "auto"
    output_metadata: Mapping[str, str | None] | None = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.access_strategy not in VALID_ACCESS_STRATEGIES:
            raise ValueError("access_strategy must be one of: auto, direct, quota")

        if self.output_metadata is None:
            self.output_metadata = {}
            return
        if not isinstance(self.output_metadata, Mapping):
            raise TypeError("output_metadata must be a mapping or None")

        unknown_fields = set(self.output_metadata) - OUTPUT_METADATA_FIELDS
        if unknown_fields:
            fields = ", ".join(sorted(unknown_fields))
            raise ValueError(f"unsupported output metadata field(s): {fields}")
        for field_name, value in self.output_metadata.items():
            if value is not None and not isinstance(value, str):
                raise TypeError(
                    f"output metadata field {field_name!r} must be a string or None"
                )
        self.output_metadata = dict(self.output_metadata)
