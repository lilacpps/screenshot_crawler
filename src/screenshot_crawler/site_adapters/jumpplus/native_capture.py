"""Jump+ transport-image validation and fail-closed native reconstruction."""

from __future__ import annotations

import hashlib
import io
import itertools
import math
import tempfile
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, ImageChops, UnidentifiedImageError

from screenshot_crawler.core.capture import CaptureResult

JUMPPLUS_CDN_HOSTS = frozenset(
    {"cdn-ak-img.shonenjumpplus.com", "cdn-ak.shonenjumpplus.com"}
)
_IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


@dataclass(frozen=True, slots=True)
class JumpPlusUrlParts:
    episode_id: str

    @property
    def content_id(self) -> str:
        return self.episode_id


def parse_jumpplus_url(url: str) -> JumpPlusUrlParts | None:
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if (parsed.hostname or "").lower() not in {
        "shonenjumpplus.com",
        "www.shonenjumpplus.com",
    }:
        return None
    parts = parsed.path.strip("/").split("/")
    if len(parts) != 2 or parts[0] != "episode" or not parts[1].isdigit():
        return None
    return JumpPlusUrlParts(parts[1])


def normalize_source_url(url: str) -> str | None:
    parsed = urlparse(url)
    if (parsed.hostname or "").lower() not in JUMPPLUS_CDN_HOSTS:
        return None
    if not parsed.path.lower().startswith("/public/page/"):
        return None
    return url


def is_jumpplus_jpeg_response(response: object) -> bool:
    url = str(getattr(response, "url", ""))
    if normalize_source_url(url) is None:
        return False
    request = getattr(response, "request", None)
    resource_type = getattr(request, "resource_type", None)
    headers = getattr(response, "headers", {}) or {}
    content_type = next(
        (str(value) for key, value in headers.items() if key.lower() == "content-type"),
        "",
    )
    normalized_type = content_type.split(";", 1)[0].strip().lower()
    if normalized_type:
        return normalized_type == "image/jpeg" and resource_type in {None, "", "image", "fetch", "xhr", "other"}
    return resource_type in {None, "", "image"}


def decoded_pixel_sha256(data: bytes) -> str:
    with Image.open(io.BytesIO(data)) as image:
        return hashlib.sha256(image.convert("RGB").tobytes()).hexdigest()


def raw_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def max_decoded_pixel_difference(source_data: bytes, candidate_data: bytes) -> int | None:
    try:
        with Image.open(io.BytesIO(source_data)) as source_image:
            source = source_image.convert("RGB")
        with Image.open(io.BytesIO(candidate_data)) as candidate_image:
            candidate = candidate_image.convert("RGB")
        if source.size != candidate.size:
            return None
        extrema = ImageChops.difference(source, candidate).getextrema()
        return max(channel_extrema[1] for channel_extrema in extrema)
    except (OSError, UnidentifiedImageError, ValueError):
        return None


def _jpeg_sof(data: bytes) -> tuple[int, int, tuple[tuple[int, int], ...]] | None:
    if len(data) < 4 or data[:3] != b"\xff\xd8\xff":
        return None
    index = 2
    sof_markers = set(range(0xC0, 0xC4)) | set(range(0xC5, 0xC8))
    sof_markers |= set(range(0xC9, 0xCC)) | set(range(0xCD, 0xD0))
    while index + 3 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        while index < len(data) and data[index] == 0xFF:
            index += 1
        if index >= len(data):
            break
        marker = data[index]
        index += 1
        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        if index + 2 > len(data):
            break
        length = int.from_bytes(data[index : index + 2], "big")
        if length < 2 or index + length > len(data):
            break
        if marker in sof_markers and length >= 8:
            height = int.from_bytes(data[index + 3 : index + 5], "big")
            width = int.from_bytes(data[index + 5 : index + 7], "big")
            count = data[index + 7]
            end = index + 8 + count * 3
            if not width or not height or end > index + length:
                return None
            factors = tuple(
                (data[offset + 1] >> 4, data[offset + 1] & 15)
                for offset in range(index + 8, end, 3)
            )
            if any(x < 1 or y < 1 for x, y in factors):
                return None
            return width, height, factors
        index += length
    return None


def jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    sof = _jpeg_sof(data)
    return sof[:2] if sof else None


def jpeg_sampling_factors(data: bytes) -> list[list[int]] | None:
    sof = _jpeg_sof(data)
    return [list(pair) for pair in sof[2]] if sof else None


def jpeg_mcu_dimensions(data: bytes) -> tuple[int, int] | None:
    sof = _jpeg_sof(data)
    return (
        8 * max(pair[0] for pair in sof[2]),
        8 * max(pair[1] for pair in sof[2]),
    ) if sof else None


def _jpeg_marker_payloads(data: bytes) -> list[tuple[int, bytes]]:
    if not data.startswith(b"\xff\xd8"):
        return []
    result: list[tuple[int, bytes]] = []
    index = 2
    while index + 3 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        while index < len(data) and data[index] == 0xFF:
            index += 1
        if index >= len(data):
            break
        marker = data[index]
        index += 1
        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            result.append((marker, b""))
            if marker == 0xD9:
                break
            continue
        if marker == 0xDA or index + 2 > len(data):
            break
        length = int.from_bytes(data[index : index + 2], "big")
        if length < 2 or index + length > len(data):
            break
        result.append((marker, data[index + 2 : index + length]))
        index += length
    return result


def _dct_signature(_candidate: dict[str, object], data: bytes) -> dict[str, object]:
    dimensions = jpeg_dimensions(data)
    sampling = jpeg_sampling_factors(data)
    if dimensions is None or sampling is None:
        raise ValueError("invalid JPEG dimensions or sampling factors")
    try:
        import jpeglib  # type: ignore[import-not-found]
        import numpy as np  # type: ignore[import-not-found]
    except (ImportError, OSError) as exc:
        raise ValueError("DCT analyzer unavailable") from exc
    dct, path = _read_dct(data, jpeglib)
    try:
        names = [name for name in ("Y", "Cb", "Cr") if getattr(dct, name, None) is not None]
        if not names:
            raise ValueError("JPEG has no supported DCT components")
        coefficients = tuple(
            (name, hashlib.sha256(np.asarray(getattr(dct, name)).tobytes()).hexdigest())
            for name in names
        )
        return {
            "content_key": (
                tuple(dimensions),
                tuple(tuple(pair) for pair in sampling),
                hashlib.sha256(np.asarray(dct.qt).tobytes()).hexdigest(),
                hashlib.sha256(np.asarray(dct.quant_tbl_no).tobytes()).hexdigest(),
                coefficients,
            ),
            "metadata_key": tuple(_jpeg_marker_payloads(data)),
        }
    finally:
        with suppress(Exception):
            dct.close()
        path.unlink(missing_ok=True)


def select_transport_candidate(
    source_pixel_sha256: str | None,
    candidates: list[dict[str, object]],
    *,
    source_raw_sha256: str | None = None,
    source_data: bytes | None = None,
    load_bytes: Callable[[dict[str, object]], bytes] | None = None,
    analyze_candidate: Callable[[dict[str, object], bytes], dict[str, object]] | None = None,
) -> dict[str, object]:
    """Return J2.1's unique/equivalent/ambiguous/unmatched decision."""
    raw_matching = [
        item for item in candidates
        if source_raw_sha256 and item.get("raw_sha256") == source_raw_sha256
    ]
    matching = [
        item for item in candidates
        if source_pixel_sha256 and item.get("pixel_sha256") == source_pixel_sha256
    ]
    result: dict[str, object] = {
        "selected_candidate": None,
        "pixel_fallback_candidate": None,
        "selection_status": "unmatched",
        "selection_reason": "no_pixel_sha_match",
        "candidate_count": len(matching),
        "equivalent_candidate_count": 0,
        "metadata_equivalent": None,
    }

    if raw_matching:
        result["candidate_count"] = len(raw_matching)
        result["pixel_fallback_candidate"] = raw_matching[0]
        if len(raw_matching) == 1:
            result.update(
                selected_candidate=raw_matching[0],
                selection_status="unique",
                selection_reason="single_raw_sha256",
                equivalent_candidate_count=1,
                metadata_equivalent=True,
            )
        else:
            result.update(
                selected_candidate=raw_matching[0],
                selection_status="equivalent_multiple",
                selection_reason="identical_raw_sha256",
                equivalent_candidate_count=len(raw_matching),
                metadata_equivalent=True,
            )
        return result

    if not matching:
        if source_data is None:
            return result
        tolerant: list[dict[str, object]] = []
        for item in candidates:
            data = load_bytes(item) if load_bytes is not None else item.get("data")
            if not isinstance(data, bytes):
                continue
            max_difference = max_decoded_pixel_difference(source_data, data)
            if max_difference is not None and max_difference <= 2:
                tolerant.append(item)
        if not tolerant:
            return result
        result["candidate_count"] = len(tolerant)
        result["pixel_fallback_candidate"] = tolerant[0]
        if len(tolerant) == 1:
            result.update(
                selected_candidate=tolerant[0],
                selection_status="unique",
                selection_reason="single_decoder_tolerant_pixel_match",
                equivalent_candidate_count=1,
                metadata_equivalent=True,
            )
            return result
        result.update(
            selection_status="ambiguous",
            selection_reason="multiple_decoder_tolerant_pixel_matches",
            equivalent_candidate_count=0,
        )
        return result

    result["pixel_fallback_candidate"] = matching[0]
    if len(matching) == 1:
        result.update(selected_candidate=matching[0], selection_status="unique",
                      selection_reason="single_pixel_match", equivalent_candidate_count=1,
                      metadata_equivalent=True)
        return result
    if load_bytes is None:
        result.update(selection_status="ambiguous", selection_reason="candidate_equivalence_unproven")
        return result
    try:
        raw = [load_bytes(item) for item in matching]
        raw_hashes = [hashlib.sha256(item).hexdigest() for item in raw]
        if len(set(raw_hashes)) == 1:
            result.update(selected_candidate=matching[0], selection_status="equivalent_multiple",
                          selection_reason="identical_raw_sha256",
                          equivalent_candidate_count=len(matching), metadata_equivalent=True)
            return result
        if analyze_candidate is None:
            raise ValueError("JPEG candidate analyzer is unavailable")
        signatures = [analyze_candidate(item, data) for item, data in zip(matching, raw, strict=True)]
    except Exception as exc:  # noqa: BLE001 - ambiguity must fail closed
        result.update(selection_status="ambiguous", selection_reason="candidate_equivalence_unproven",
                      selection_error=f"{type(exc).__name__}: {exc}")
        return result
    content_keys = [item.get("content_key") for item in signatures]
    metadata_keys = [item.get("metadata_key") for item in signatures]
    if len(set(content_keys)) == 1:
        result.update(selected_candidate=matching[0], selection_status="equivalent_multiple",
                      selection_reason="identical_dct_image_content",
                      equivalent_candidate_count=len(matching),
                      metadata_equivalent=len(set(metadata_keys)) == 1)
        return result
    result.update(selection_status="ambiguous",
                  selection_reason="multiple_pixel_equal_but_dct_distinct_candidates",
                  equivalent_candidate_count=sum(key == content_keys[0] for key in content_keys),
                  metadata_equivalent=len(set(metadata_keys)) == 1)
    return result


@dataclass(frozen=True, slots=True)
class DrawMapping:
    source_path: str
    source_width: int
    source_height: int
    canvas_width: int
    canvas_height: int
    sx: int
    sy: int
    sw: int
    sh: int
    dx: int
    dy: int
    dw: int
    dh: int
    transform: tuple[float, float, float, float, float, float]
    composite_operation: str
    filter: str
    global_alpha: float
    sequence: int = 0

    @classmethod
    def from_dict(cls, raw: object) -> DrawMapping | None:
        if not isinstance(raw, dict):
            return None
        try:
            def integer(name: str) -> int:
                value = float(raw[name])
                if not math.isfinite(value) or value != round(value):
                    raise ValueError
                return int(value)
            transform_raw = raw["transform"]
            if isinstance(transform_raw, dict):
                transform_raw = tuple(transform_raw.get(key) for key in ("a", "b", "c", "d", "e", "f"))
            transform = tuple(float(value) for value in transform_raw)
            if len(transform) != 6 or not all(math.isfinite(v) for v in transform):
                return None
            return cls(
                source_path=str(raw.get("sourcePath") or raw.get("sourceUrl") or ""),
                source_width=integer("sourceWidth"), source_height=integer("sourceHeight"),
                canvas_width=integer("canvasWidth"), canvas_height=integer("canvasHeight"),
                sx=integer("sx"), sy=integer("sy"), sw=integer("sw"), sh=integer("sh"),
                dx=integer("dx"), dy=integer("dy"), dw=integer("dw"), dh=integer("dh"),
                transform=transform, composite_operation=str(raw.get("globalCompositeOperation") or raw.get("compositeOperation") or ""),
                filter=str(raw.get("filter") or ""), global_alpha=float(raw.get("globalAlpha", 1)),
                sequence=int(raw.get("sequence", 0)),
            )
        except (KeyError, TypeError, ValueError):
            return None


def _coverage(rectangles: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int] | None:
    if not rectangles or any(w <= 0 or h <= 0 for _, _, w, h in rectangles):
        return None
    xs = sorted({v for x, _, w, _ in rectangles for v in (x, x + w)})
    ys = sorted({v for _, y, _, h in rectangles for v in (y, y + h)})
    for y0, y1 in itertools.pairwise(ys):
        for x0, x1 in itertools.pairwise(xs):
            if sum(x <= x0 and x + w >= x1 and y <= y0 and y + h >= y1
                   for x, y, w, h in rectangles) != 1:
                return None
    return xs[0], ys[0], xs[-1], ys[-1]


def _valid_common(item: DrawMapping, source_path: str, dimensions: tuple[int, int], canvas: tuple[int, int]) -> bool:
    return (
        item.source_path == source_path and (item.source_width, item.source_height) == dimensions
        and (item.canvas_width, item.canvas_height) == canvas
        and item.transform == _IDENTITY and item.composite_operation == "source-over"
        and item.filter == "none" and item.global_alpha == 1
    )


def _valid_base(item: DrawMapping, source_path: str, dimensions: tuple[int, int], canvas: tuple[int, int]) -> bool:
    return _valid_common(item, source_path, dimensions, canvas) and (
        (item.sx, item.sy, item.sw, item.sh) == (0, 0, *dimensions)
        and (item.dx, item.dy, item.dw, item.dh) == (0, 0, *canvas)
    )


def _valid_tile(item: DrawMapping, source_path: str, dimensions: tuple[int, int], canvas: tuple[int, int]) -> bool:
    return (
        _valid_common(item, source_path, dimensions, canvas) and item.sw == item.dw and item.sh == item.dh
        and min(item.sx, item.sy, item.dx, item.dy) >= 0
        and item.sx + item.sw <= dimensions[0] and item.sy + item.sh <= dimensions[1]
        and item.dx + item.dw <= canvas[0] and item.dy + item.dh <= canvas[1]
    )


def _tile_extent_complete(coverage: tuple[int, int, int, int], rects: list[tuple[int, int, int, int]], size: tuple[int, int]) -> bool:
    left, top, right, bottom = coverage
    return left == 0 and top == 0 and 0 <= size[0] - right < min(w for _, _, w, _ in rects) and 0 <= size[1] - bottom < min(h for _, _, _, h in rects)


def dct_lossless_feasibility(*, jpeg_bytes: bytes, source_rectangles: list[tuple[int, int, int, int]], destination_rectangles: list[tuple[int, int, int, int]], canvas_size: tuple[int, int]) -> dict[str, object]:
    dimensions = jpeg_dimensions(jpeg_bytes)
    mcu = jpeg_mcu_dimensions(jpeg_bytes)
    result: dict[str, object] = {"status": "unknown", "feasible": False, "jpeg_dimensions": dimensions, "mcu": mcu}
    if dimensions is None or mcu is None:
        result["reason"] = "invalid_or_unsupported_jpeg_header"
        return result
    if dimensions != canvas_size:
        result.update(status="infeasible", reason="jpeg_dimensions_do_not_match_canvas")
        return result
    if any(value < 0 for rect in source_rectangles + destination_rectangles for value in rect):
        result.update(status="infeasible", reason="negative_tile_geometry")
        return result
    if any(value % unit for x, y, w, h in source_rectangles + destination_rectangles for value, unit in ((x, mcu[0]), (w, mcu[0]), (y, mcu[1]), (h, mcu[1]))):
        result.update(status="infeasible", reason="tile_geometry_not_mcu_aligned")
        return result
    source = _coverage(source_rectangles)
    destination = _coverage(destination_rectangles)
    result.update(source_coverage=source, destination_coverage=destination)
    if source is None or destination is None or source[:2] != (0, 0) or destination[:2] != (0, 0):
        result.update(status="infeasible", reason="coverage_has_gap_or_overlap")
        return result
    if source[2:] != destination[2:] or sum(w * h for _, _, w, h in source_rectangles) != sum(w * h for _, _, w, h in destination_rectangles):
        result.update(status="infeasible", reason="coverage_extent_or_area_differs")
        return result
    if not _tile_extent_complete(source, source_rectangles, dimensions) or not _tile_extent_complete(destination, destination_rectangles, canvas_size):
        result.update(status="infeasible", reason="coverage_does_not_leave_valid_edge")
        return result
    result.update(status="feasible", feasible=True, reason="coverage_and_mcu_alignment_valid")
    return result


def _read_dct(data: bytes, jpeglib: object) -> tuple[object, Path]:
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as handle:
        path = Path(handle.name)
        handle.write(data)
    try:
        return jpeglib.read_dct(str(path)), path  # type: ignore[attr-defined]
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _write_dct(dct: object, arrays: dict[str, object]) -> bytes:
    for name, array in arrays.items():
        getattr(dct, name)[...] = array
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as handle:
        path = Path(handle.name)
    try:
        dct.write_dct(str(path))  # type: ignore[attr-defined]
        return path.read_bytes()
    finally:
        path.unlink(missing_ok=True)


def _records(data: bytes, base: object, mappings: list[object], visible_draw: object, source_path: str, canvas_size: tuple[int, int]) -> tuple[DrawMapping, list[DrawMapping], DrawMapping] | None:
    dimensions = jpeg_dimensions(data)
    if dimensions is None or dimensions != canvas_size:
        return None
    parsed_base = DrawMapping.from_dict(base)
    parsed_visible = DrawMapping.from_dict(visible_draw)
    parsed_tiles = [DrawMapping.from_dict(item) for item in mappings]
    if parsed_base is None or parsed_visible is None or not parsed_tiles or any(item is None for item in parsed_tiles):
        return None
    tiles = [item for item in parsed_tiles if item is not None]
    # The observed spacer draw lands entirely outside the canvas.  It is a
    # proven no-op and is excluded before source identity validation; any draw
    # that intersects the canvas must still pass the strict mapping checks.
    tiles = [item for item in tiles if not (item.dx + item.dw <= 0 or item.dy + item.dh <= 0 or item.dx >= canvas_size[0] or item.dy >= canvas_size[1])]
    if not _valid_base(parsed_base, source_path, dimensions, canvas_size) or not _valid_base(parsed_visible, source_path, dimensions, canvas_size) or any(not _valid_tile(item, source_path, dimensions, canvas_size) for item in tiles):
        return None
    if not tiles:
        return None
    return parsed_base, tiles, parsed_visible


def reconstruct_jpeg_png(data: bytes, *, base: object, mappings: list[object], visible_draw: object, source_path: str, canvas_size: tuple[int, int]) -> CaptureResult | None:
    records = _records(data, base, mappings, visible_draw, source_path, canvas_size)
    if records is None:
        return None
    try:
        with Image.open(io.BytesIO(data)) as image:
            output = image.convert("RGB")
        _, tiles, _ = records
        source_coverage = _coverage([(i.sx, i.sy, i.sw, i.sh) for i in tiles])
        destination_coverage = _coverage([(i.dx, i.dy, i.dw, i.dh) for i in tiles])
        if source_coverage is None or destination_coverage is None or source_coverage != destination_coverage:
            return None
        if not _tile_extent_complete(source_coverage, [(i.sx, i.sy, i.sw, i.sh) for i in tiles], canvas_size) or not _tile_extent_complete(destination_coverage, [(i.dx, i.dy, i.dw, i.dh) for i in tiles], canvas_size):
            return None
        source = output.copy()
        for item in sorted(tiles, key=lambda value: value.sequence):
            output.paste(source.crop((item.sx, item.sy, item.sx + item.sw, item.sy + item.sh)), (item.dx, item.dy))
        buffer = io.BytesIO()
        output.save(buffer, format="PNG")
    except (UnidentifiedImageError, OSError, ValueError):
        return None
    return CaptureResult(buffer.getvalue(), canvas_size[0], canvas_size[1], "image/png", ".png")


def reconstruct_jpeg_lossless(data: bytes, *, base: object, mappings: list[object], visible_draw: object, source_path: str, canvas_size: tuple[int, int]) -> CaptureResult | None:
    records = _records(data, base, mappings, visible_draw, source_path, canvas_size)
    if records is None:
        return None
    _, tiles, _ = records
    feasibility = dct_lossless_feasibility(
        jpeg_bytes=data,
        source_rectangles=[(i.sx, i.sy, i.sw, i.sh) for i in tiles],
        destination_rectangles=[(i.dx, i.dy, i.dw, i.dh) for i in tiles],
        canvas_size=canvas_size,
    )
    if not feasibility.get("feasible"):
        return None
    try:
        import jpeglib  # type: ignore[import-not-found]
        import numpy as np  # type: ignore[import-not-found]
        source_dct, source_path_tmp = _read_dct(data, jpeglib)
        output_dct = None
        try:
            factors = [tuple(int(v) for v in row) for row in source_dct.samp_factor.tolist()]
            if len(factors) not in {1, 3} or any(pair != (1, 1) for pair in factors):
                return None
            names = [name for name in ("Y", "Cb", "Cr") if getattr(source_dct, name, None) is not None]
            if len(names) != len(factors):
                return None
            original = {name: np.array(getattr(source_dct, name), dtype=np.int16, copy=True) for name in names}
            expected = {name: array.copy() for name, array in original.items()}
            for item in tiles:
                for name in names:
                    expected[name][item.dy // 8 : (item.dy + item.dh) // 8, item.dx // 8 : (item.dx + item.dw) // 8] = original[name][item.sy // 8 : (item.sy + item.sh) // 8, item.sx // 8 : (item.sx + item.sw) // 8]
            output_bytes = _write_dct(source_dct, expected)
            output_dct, output_path_tmp = _read_dct(output_bytes, jpeglib)
            observed = {name: np.array(getattr(output_dct, name), dtype=np.int16, copy=True) for name in names}
            if any(not np.array_equal(expected[name], observed[name]) for name in names):
                return None
            if not np.array_equal(source_dct.qt, output_dct.qt) or not np.array_equal(source_dct.quant_tbl_no, output_dct.quant_tbl_no):
                return None
            if source_dct.samp_factor.tolist() != output_dct.samp_factor.tolist():
                return None
            return CaptureResult(output_bytes, canvas_size[0], canvas_size[1], "image/jpeg", ".jpg")
        finally:
            with suppress(Exception):
                source_dct.close()
            if output_dct is not None:
                with suppress(Exception):
                    output_dct.close()
            source_path_tmp.unlink(missing_ok=True)
            if "output_path_tmp" in locals():
                output_path_tmp.unlink(missing_ok=True)
    except (ImportError, OSError, ValueError, TypeError):
        return None
