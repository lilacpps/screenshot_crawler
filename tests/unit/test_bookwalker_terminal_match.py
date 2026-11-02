from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from screenshot_crawler.site_adapters.bookwalker.terminal_match import (
    describe_terminal_png,
    match_terminal_descriptor,
)

_NOTICE = Path(
    "output/bookwalker-owned-png-20261029/tail-lead-101939737033/"
    "step-07-counter-321-native-0.png"
)
_LOGO = Path(
    "output/bookwalker-regression-20261030/artifacts/vol003-saved003-page-0325.png"
)


def _png(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _synthetic_terminal() -> bytes:
    image = Image.new("RGBA", (180, 240), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((42, 82, 138, 145), fill=(17, 17, 17, 255))
    return _png(image)


@pytest.mark.parametrize("canvas_size", [(360, 480), (2859, 1481)])
def test_descriptor_uses_actual_png_and_is_stable_under_white_padding(
    canvas_size: tuple[int, int],
) -> None:
    base = Image.open(io.BytesIO(_synthetic_terminal())).convert("RGBA")
    padded = Image.new("RGBA", canvas_size, (255, 255, 255, 255))
    padded.alpha_composite(base, (90, 120))
    first = describe_terminal_png(_png(base))
    second = describe_terminal_png(_png(padded))
    assert first is not None and second is not None
    assert first["perceptualHash256"] == second["perceptualHash256"]
    assert first["foregroundAspect"] == second["foregroundAspect"]
    assert first["inkDensity"] == second["inkDensity"]


@pytest.mark.parametrize(
    ("canvas_size", "accepted"),
    [((4096, 2048), True), ((4096, 2049), False), ((4097, 2), False)],
)
def test_descriptor_bounds_before_pixel_decode(
    canvas_size: tuple[int, int], accepted: bool, monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = Image.new("RGB", canvas_size, "white")
    ImageDraw.Draw(image).rectangle((0, 0, 1, 1), fill="black")
    png = _png(image)
    original_load = Image.Image.load
    decoded = False

    def track_load(self: Image.Image, *args: object, **kwargs: object):
        nonlocal decoded
        decoded = True
        return original_load(self, *args, **kwargs)

    monkeypatch.setattr(Image.Image, "load", track_load)
    assert (describe_terminal_png(png) is not None) is accepted
    assert decoded is accepted


def test_transparent_margin_is_flattened_to_white() -> None:
    image = Image.new("RGBA", (180, 240), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((42, 82, 138, 145), fill=(17, 17, 17, 255))
    transparent = describe_terminal_png(_png(image))
    white = Image.new("RGBA", image.size, (255, 255, 255, 255))
    white.alpha_composite(image)
    opaque = describe_terminal_png(_png(white))
    assert transparent is not None and opaque is not None
    assert transparent["perceptualHash256"] == opaque["perceptualHash256"]


def test_real_terminal_artifacts_match_their_registered_roles() -> None:
    if not _NOTICE.exists() or not _LOGO.exists():
        return
    notice = describe_terminal_png(_NOTICE.read_bytes())
    logo = describe_terminal_png(_LOGO.read_bytes())
    assert notice is not None and logo is not None
    assert match_terminal_descriptor(notice, "notice")[0] is True
    assert match_terminal_descriptor(logo, "logo")[0] is True
    assert match_terminal_descriptor(notice, "logo")[0] is False


def test_body_like_synthetic_image_is_not_a_terminal_role() -> None:
    image = Image.new("RGBA", (722, 1024), (255, 255, 255, 255))
    draw = ImageDraw.Draw(image)
    for y in range(120, 900, 18):
        draw.line((80, y, 640, y), fill=(30, 30, 30, 255), width=4)
    descriptor = describe_terminal_png(_png(image))
    assert descriptor is not None
    assert match_terminal_descriptor(descriptor, "notice")[0] is False
    assert match_terminal_descriptor(descriptor, "logo")[0] is False
