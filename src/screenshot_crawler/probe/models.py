"""Serializable models for site investigation output."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ProbeResult:
    url: str
    title: str
    viewport: dict[str, int]
    visible_images: list[dict[str, Any]] = field(default_factory=list)
    canvases: list[dict[str, Any]] = field(default_factory=list)
    buttons: list[dict[str, Any]] = field(default_factory=list)
    background_images: list[dict[str, Any]] = field(default_factory=list)
    visible_text: str = ""
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "viewport": self.viewport,
            "visible_images": self.visible_images,
            "canvases": self.canvases,
            "buttons": self.buttons,
            "background_images": self.background_images,
            "visible_text": self.visible_text,
            "errors": self.errors,
        }
