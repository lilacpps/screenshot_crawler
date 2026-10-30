"""Source-independent terminal-screen matching for BookWalker."""

from __future__ import annotations

import base64
import hashlib
import io
import math
from collections.abc import Mapping
from typing import Any

from PIL import Image, ImageChops

TERMINAL_DESCRIPTOR_SCRIPT = r"""
canvas => {
  try {
    const isVisibleCanvas = node => {
      if (!node || !node.isConnected) return false;
      const style = getComputedStyle(node);
      if (style.display === 'none' ||
          style.visibility === 'hidden' || style.visibility === 'collapse' ||
          Number(style.opacity) <= 0) return false;
      const rect = node.getBoundingClientRect();
      return Number.isFinite(rect.width) && Number.isFinite(rect.height) &&
        rect.width > 0 && rect.height > 0;
    };
    const activeCanvases = [...document.querySelectorAll(
      '#renderer .currentScreen canvas:not(.dummy)'
    )].filter(isVisibleCanvas);
    if (activeCanvases.length !== 1 || activeCanvases[0] !== canvas ||
        !isVisibleCanvas(canvas)) return null;
    const width = Number(canvas.width);
    const height = Number(canvas.height);
    if (!Number.isInteger(width) || !Number.isInteger(height) ||
        width < 2 || height < 2 || width > 4096 || height > 4096 ||
        width * height > 4000000) return null;
    const contentId = new URL(location.href).searchParams.get('cid')?.trim() || null;
    const counter = document.querySelector('#pageSliderCounter')?.textContent?.trim() || null;
    if (!contentId || !counter) return null;
    return {
      width, height,
      traceId: canvas.getAttribute('data-bookwalker-trace-id'),
      contentId,
      counter,
      dataUrl: canvas.toDataURL('image/png'),
    };
  } catch (_) {
    return null;
  }
}
"""


_COSINES = tuple(
    tuple(math.cos((2 * index + 1) * frequency * math.pi / 64)
          for index in range(32))
    for frequency in range(16)
)


def _dct_hash(image: Image.Image) -> str:
    gray = image.convert("L").resize((32, 32), Image.Resampling.LANCZOS)
    values = [float(value) - 128.0 for value in gray.getdata()]
    row_coefficients = [
        [sum(values[y * 32 + x] * _COSINES[u][x] for x in range(32))
         for y in range(32)]
        for u in range(16)
    ]
    coefficients: list[float] = []
    for u in range(16):
        for v in range(16):
            if u == 0 and v == 0:
                continue
            coefficients.append(sum(
                row_coefficients[u][y] * _COSINES[v][y] for y in range(32)
            ))
    median = sorted(coefficients)[len(coefficients) // 2]
    # DC is excluded from the comparison; append a reserved zero bit so the
    # wire descriptor remains a fixed 256-bit value.
    bits = [coefficient >= median for coefficient in coefficients] + [False]
    return "".join(
        f"{sum((1 << (3 - bit)) for bit in range(4) if bits[offset + bit]):x}"
        for offset in range(0, len(bits), 4)
    )


def describe_terminal_png(png_bytes: bytes) -> dict[str, Any] | None:
    """Build the terminal descriptor from the same PNG bytes used at runtime."""

    try:
        image = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
        width, height = image.size
        if width < 2 or height < 2 or width > 4096 or height > 4096:
            return None
        white = Image.new("RGBA", image.size, (255, 255, 255, 255))
        flat = Image.alpha_composite(white, image).convert("RGB")
        darkest = ImageChops.darker(
            ImageChops.darker(flat.getchannel("R"), flat.getchannel("G")),
            flat.getchannel("B"),
        )
        mask = darkest.point(lambda value: 255 if value < 245 else 0)
        bbox = mask.getbbox()
        if bbox is None:
            return None
        min_x, min_y, _max_x, _max_y = bbox
        crop = flat.crop(bbox)
        white = Image.new("RGB", (32, 32), (255, 255, 255))
        scale = min(32 / crop.width, 32 / crop.height)
        resized = crop.resize(
            (max(1, round(crop.width * scale)), max(1, round(crop.height * scale))),
            Image.Resampling.LANCZOS,
        )
        white.paste(resized, ((32 - resized.width) // 2, (32 - resized.height) // 2))
        foreground_area = crop.width * crop.height
        foreground = mask.histogram()[255]
        return {
            "width": width,
            "height": height,
            "foreground": foreground,
            "foregroundAspect": crop.width / crop.height,
            "inkDensity": foreground / foreground_area,
            "bbox": {"x": min_x, "y": min_y, "width": crop.width, "height": crop.height},
            "perceptualHash256": _dct_hash(white),
            "frameSha256": hashlib.sha256(png_bytes).hexdigest(),
        }
    except (OSError, ValueError, TypeError):
        return None


_TERMINAL_HASHES = {
    "notice": "d7065d89c198f799996f9278db6a364eb218db231e836b32630d90d4c9fc4f0c",
    "logo": "736073618d0f9b4d8d0d24938c9f99cc596464d271f19c8c73738f0f8f0edb64",
}
_TERMINAL_ASPECT = {"notice": 624 / 438, "logo": 514 / 246}
_TERMINAL_DENSITY = {"notice": 0.106746, "logo": 0.327679}


def decode_terminal_data_url(value: object) -> bytes | None:
    if not isinstance(value, str) or not value.startswith("data:image/png;base64,"):
        return None
    try:
        return base64.b64decode(value.split(",", 1)[1], validate=True)
    except (ValueError, TypeError):
        return None


def _hash_distance(left: str, right: str) -> int | None:
    if len(left) != 64 or len(right) != 64:
        return None
    try:
        return sum((int(a, 16) ^ int(b, 16)).bit_count() for a, b in zip(left, right))
    except ValueError:
        return None


def match_terminal_descriptor(
    descriptor: Mapping[str, Any], role: str
) -> tuple[bool, dict[str, Any]]:
    """Classify a complete-canvas descriptor with calibrated image features."""

    if role not in _TERMINAL_HASHES:
        return False, {"matched": False, "reason": "unknown role"}
    aspect = descriptor.get("foregroundAspect")
    density = descriptor.get("inkDensity")
    value = descriptor.get("perceptualHash256")
    if not isinstance(aspect, (int, float)) or isinstance(aspect, bool):
        return False, {"matched": False, "reason": "missing foreground aspect"}
    if not isinstance(density, (int, float)) or isinstance(density, bool):
        return False, {"matched": False, "reason": "missing ink density"}
    if not isinstance(value, str):
        return False, {"matched": False, "reason": "missing perceptual hash"}
    distance = _hash_distance(value.lower(), _TERMINAL_HASHES[role])
    if distance is None:
        return False, {"matched": False, "reason": "invalid perceptual hash"}
    if abs(float(aspect) - _TERMINAL_ASPECT[role]) > 0.22:
        return False, {"matched": False, "reason": "foreground aspect mismatch", "distance": distance}
    if abs(float(density) - _TERMINAL_DENSITY[role]) > 0.055:
        return False, {"matched": False, "reason": "foreground density mismatch", "distance": distance}
    if distance > 64:
        return False, {"matched": False, "reason": "foreground perceptual hash mismatch", "distance": distance}
    return True, {
        "matched": True,
        "role": role,
        "descriptor_kind": "complete_canvas_perceptual_terminal",
        "distance": distance,
        "foreground_aspect": round(float(aspect), 6),
        "ink_density": round(float(density), 6),
    }
