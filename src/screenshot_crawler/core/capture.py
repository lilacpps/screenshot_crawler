"""Capture target screenshot handling."""

from __future__ import annotations

import base64
import struct
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import Locator


@dataclass(frozen=True, slots=True)
class CaptureResult:
    """PNG bytes and the rendered pixel dimensions of a capture target."""

    data: bytes
    width: int | None
    height: int | None


def _png_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", data[16:24])


def capture_png_bytes(data: bytes) -> CaptureResult:
    """Create a capture result from validated PNG bytes."""

    dimensions = _png_dimensions(data)
    if dimensions is None:
        raise ValueError("capture data is not a valid PNG")
    return CaptureResult(data=data, width=dimensions[0], height=dimensions[1])


async def capture_locator(locator: Locator) -> CaptureResult:
    """Capture only the supplied Locator, never the full page."""

    # A canvas may be visually covered by viewer chrome. Reading its own PNG
    # buffer avoids capturing an overlapping toolbar while remaining a
    # Locator-scoped capture. Other elements use Playwright's normal screenshot
    # path.
    is_canvas = await locator.evaluate(
        "element => element instanceof HTMLCanvasElement"
    )
    if is_canvas:
        data_url = await locator.evaluate("canvas => canvas.toDataURL('image/png')")
        if isinstance(data_url, str) and data_url.startswith("data:image/png;base64,"):
            data = base64.b64decode(data_url.split(",", 1)[1])
        else:
            data = await locator.screenshot(animations="disabled")
    else:
        data = await locator.screenshot(animations="disabled")
    dimensions = _png_dimensions(data)
    if dimensions is None:
        box = await locator.bounding_box()
        dimensions = (
            (round(box["width"]), round(box["height"]))
            if box is not None
            else (None, None)
        )
    return CaptureResult(data=data, width=dimensions[0], height=dimensions[1])


async def capture_locator_bytes(locator: Locator) -> bytes:
    """Return PNG bytes for a Locator."""

    return (await capture_locator(locator)).data


def save_capture(result: CaptureResult, path: str | Path) -> None:
    """Persist a captured PNG, creating its parent directory if necessary."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(result.data)
