"""Magapoke source validation and native tile reconstruction helpers."""

from __future__ import annotations

import io
import itertools
import math
import re
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, UnidentifiedImageError

from screenshot_crawler.core.capture import CaptureResult

MAGAPOKE_CDN_HOST = "mgpk-cdn.magazinepocket.com"
_SOURCE_PATH = re.compile(
    r"^/static/web_titles/(?P<title>[^/]+)/episodes/(?P<episode>[^/]+)/"
    r"(?P<name>[^/]+\.jpg)$",
    re.IGNORECASE,
)
_IDENTITY_TRANSFORM = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


@dataclass(frozen=True, slots=True)
class MagapokeUrlParts:
    work_id: str
    episode_id: str

    @property
    def content_id(self) -> str:
        return self.episode_id


@dataclass(frozen=True, slots=True)
class DrawMapping:
    """One simple source-to-destination drawImage operation."""

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

    @classmethod
    def from_dict(cls, raw: object) -> DrawMapping | None:
        if not isinstance(raw, dict):
            return None
        try:
            values = {
                target: _integer(raw[source])
                for source, target in (
                    ("sourceWidth", "source_width"),
                    ("sourceHeight", "source_height"),
                    ("canvasWidth", "canvas_width"),
                    ("canvasHeight", "canvas_height"),
                    ("sx", "sx"), ("sy", "sy"), ("sw", "sw"), ("sh", "sh"),
                    ("dx", "dx"), ("dy", "dy"), ("dw", "dw"), ("dh", "dh"),
                )
            }
            transform = tuple(float(value) for value in raw["transform"])
        except (KeyError, TypeError, ValueError):
            return None
        if len(transform) != 6 or not all(math.isfinite(value) for value in transform):
            return None
        return cls(
            source_path=str(raw.get("sourcePath") or ""),
            transform=transform,  # type: ignore[arg-type]
            composite_operation=str(raw.get("compositeOperation") or ""),
            filter=str(raw.get("filter") or ""),
            **values,
        )


def _integer(value: object) -> int:
    number = float(value)
    if not math.isfinite(number) or number != round(number):
        raise ValueError("draw geometry is not an integer pixel rectangle")
    return int(number)


def parse_magapoke_url(url: str) -> MagapokeUrlParts | None:
    """Parse a title/episode URL while preserving URL identity strings."""

    match = re.search(
        r"^/title/(?P<title>[^/]+)/episode/(?P<episode>[^/?#]+)/?$",
        urlparse(url).path,
    )
    if not match:
        return None
    return MagapokeUrlParts(match.group("title"), match.group("episode"))


def source_path_parts(path: str) -> tuple[str, str] | None:
    match = _SOURCE_PATH.fullmatch(path)
    if not match:
        return None
    return match.group("title"), match.group("episode")


def source_matches_episode(path: str, expected: MagapokeUrlParts) -> bool:
    parts = source_path_parts(path)
    return parts is not None and (
        _same_numeric_id(parts[0], expected.work_id)
        and _same_numeric_id(parts[1], expected.episode_id)
    )


def normalize_source_path(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.hostname != MAGAPOKE_CDN_HOST:
        return None
    return parsed.path if source_path_parts(parsed.path) else None


def _same_numeric_id(left: str, right: str) -> bool:
    try:
        return int(left) == int(right)
    except ValueError:
        return left == right


def is_magapoke_jpeg_response(
    response: object,
    *,
    expected: MagapokeUrlParts | None = None,
) -> bool:
    """Apply URL, request type, and response-header checks to a response."""

    url = str(getattr(response, "url", ""))
    parsed = urlparse(url)
    path_parts = source_path_parts(parsed.path)
    if parsed.hostname != MAGAPOKE_CDN_HOST or path_parts is None:
        return False
    request = getattr(response, "request", None)
    resource_type = getattr(request, "resource_type", None)
    if resource_type not in {None, "", "image"}:
        return False
    headers = getattr(response, "headers", {}) or {}
    content_type = next(
        (str(value) for key, value in headers.items() if key.lower() == "content-type"),
        "",
    )
    if content_type and content_type.split(";", 1)[0].strip().lower() != "image/jpeg":
        return False
    return expected is None or (
        _same_numeric_id(path_parts[0], expected.work_id)
        and _same_numeric_id(path_parts[1], expected.episode_id)
    )


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
        segment_length = int.from_bytes(data[index : index + 2], "big")
        if segment_length < 2 or index + segment_length > len(data):
            break
        if marker in sof_markers and segment_length >= 8:
            height = int.from_bytes(data[index + 3 : index + 5], "big")
            width = int.from_bytes(data[index + 5 : index + 7], "big")
            components = data[index + 7]
            component_end = index + 8 + 3 * components
            if not width or not height or component_end > index + segment_length:
                return None
            factors = tuple(
                (data[offset + 1] >> 4, data[offset + 1] & 0x0F)
                for offset in range(index + 8, component_end, 3)
            )
            if any(horizontal < 1 or vertical < 1 for horizontal, vertical in factors):
                return None
            return width, height, factors
        index += segment_length
    return None


def jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    """Read dimensions from a JPEG SOF marker without decoding or re-encoding."""

    sof = _jpeg_sof(data)
    return sof[:2] if sof is not None else None


def jpeg_mcu_dimensions(data: bytes) -> tuple[int, int] | None:
    """Return the JPEG MCU size for the bounded lossless feasibility check."""

    sof = _jpeg_sof(data)
    if sof is None:
        return None
    factors = sof[2]
    return (8 * max(item[0] for item in factors), 8 * max(item[1] for item in factors))


def _coverage(rectangles: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int] | None:
    """Validate non-overlap and gap-free coverage of a rectangle bounding box."""

    if not rectangles or any(width <= 0 or height <= 0 for _, _, width, height in rectangles):
        return None
    x_values = sorted({value for x, _, width, _ in rectangles for value in (x, x + width)})
    y_values = sorted({value for _, y, _, height in rectangles for value in (y, y + height)})
    for y0, y1 in itertools.pairwise(y_values):
        for x0, x1 in itertools.pairwise(x_values):
            covering = sum(
                x <= x0 and x + width >= x1 and y <= y0 and y + height >= y1
                for x, y, width, height in rectangles
            )
            if covering != 1:
                return None
    return (x_values[0], y_values[0], x_values[-1], y_values[-1])


def reconstruct_jpeg_png(
    data: bytes,
    *,
    base: object,
    mappings: list[object],
    visible_draw: object,
    source_path: str,
    canvas_size: tuple[int, int],
) -> CaptureResult | None:
    """Replay verified tile draws and return a native-resolution PNG result."""

    dimensions = jpeg_dimensions(data)
    if dimensions is None or data[:3] != b"\xff\xd8\xff":
        return None
    try:
        source = Image.open(io.BytesIO(data))
        source.load()
        source = source.convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError):
        return None
    if source.size != dimensions:
        return None
    canvas_width, canvas_height = canvas_size
    if canvas_width <= 0 or canvas_height <= 0:
        return None
    if dimensions != canvas_size:
        return None

    base_mapping = DrawMapping.from_dict(base)
    if base_mapping is None or not _valid_base(base_mapping, source_path, dimensions, canvas_size):
        return None
    visible_mapping = DrawMapping.from_dict(visible_draw)
    if visible_mapping is None or not _valid_base(
        visible_mapping, source_path, dimensions, canvas_size
    ):
        return None
    parsed = [DrawMapping.from_dict(item) for item in mappings]
    if not parsed or any(item is None for item in parsed):
        return None
    tiles = [item for item in parsed if item is not None]
    if any(not _valid_tile(item, source_path, dimensions, canvas_size) for item in tiles):
        return None

    source_rectangles = [(item.sx, item.sy, item.sw, item.sh) for item in tiles]
    destination_rectangles = [(item.dx, item.dy, item.dw, item.dh) for item in tiles]
    source_coverage = _coverage(source_rectangles)
    destination_coverage = _coverage(destination_rectangles)
    if source_coverage is None or destination_coverage is None:
        return None
    if not _tile_extent_is_complete(source_coverage, source_rectangles, dimensions):
        return None
    if not _tile_extent_is_complete(destination_coverage, destination_rectangles, canvas_size):
        return None
    source_area = sum(width * height for _, _, width, height in source_rectangles)
    destination_area = sum(width * height for _, _, width, height in destination_rectangles)
    if source_area != destination_area:
        return None
    if (source_coverage[2] - source_coverage[0], source_coverage[3] - source_coverage[1]) != (
        destination_coverage[2] - destination_coverage[0],
        destination_coverage[3] - destination_coverage[1],
    ):
        return None

    output = source.copy()
    try:
        for item in tiles:
            crop = source.crop((item.sx, item.sy, item.sx + item.sw, item.sy + item.sh))
            output.paste(crop, (item.dx, item.dy))
        buffer = io.BytesIO()
        output.save(buffer, format="PNG")
    except (OSError, ValueError):
        return None
    return CaptureResult(
        data=buffer.getvalue(),
        width=canvas_width,
        height=canvas_height,
        mime_type="image/png",
        file_extension=".png",
    )


def _jpeg_marker_payloads(data: bytes) -> list[tuple[int, bytes]]:
    """Return header marker payloads, stopping before entropy-coded scan data."""

    if not data.startswith(b"\xff\xd8"):
        return []
    markers: list[tuple[int, bytes]] = []
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
            markers.append((marker, b""))
            if marker == 0xD9:
                break
            continue
        if marker == 0xDA or index + 2 > len(data):
            break
        length = int.from_bytes(data[index : index + 2], "big")
        if length < 2 or index + length > len(data):
            break
        markers.append((marker, data[index + 2 : index + length]))
        index += length
    return markers


def _marker_payloads(data: bytes, marker: int) -> list[bytes]:
    return [payload for current, payload in _jpeg_marker_payloads(data) if current == marker]


def _source_metadata_is_preserved(source: bytes, output: bytes) -> bool:
    """Require source APPn/COM payloads to survive the coefficient writer."""

    wanted = [
        item
        for item in _jpeg_marker_payloads(source)
        if 0xE0 <= item[0] <= 0xEF or item[0] == 0xFE
    ]
    available = [
        item
        for item in _jpeg_marker_payloads(output)
        if 0xE0 <= item[0] <= 0xEF or item[0] == 0xFE
    ]
    position = 0
    for item in wanted:
        try:
            position = available.index(item, position) + 1
        except ValueError:
            return False
    return True


def _aligned_block_cells(
    rectangles: list[tuple[int, int, int, int]],
) -> set[tuple[int, int]] | None:
    cells: set[tuple[int, int]] = set()
    for x, y, width, height in rectangles:
        if min(x, y, width, height) < 0 or any(
            value % 8 for value in (x, y, width, height)
        ):
            return None
        for block_y in range(y // 8, (y + height) // 8):
            for block_x in range(x // 8, (x + width) // 8):
                cell = (block_x, block_y)
                if cell in cells:
                    return None
                cells.add(cell)
    return cells


def _read_dct_bytes(data: bytes, jpeglib: object) -> tuple[object, Path]:
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as handle:
        path = Path(handle.name)
        handle.write(data)
    try:
        return jpeglib.read_dct(str(path)), path  # type: ignore[attr-defined]
    except BaseException:
        with suppress(OSError):
            path.unlink(missing_ok=True)
        raise


def _write_dct_bytes(dct: object, arrays: dict[str, object]) -> bytes:
    for name, array in arrays.items():
        getattr(dct, name)[...] = array
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as handle:
        path = Path(handle.name)
    try:
        dct.write_dct(str(path))  # type: ignore[attr-defined]
        return path.read_bytes()
    finally:
        path.unlink(missing_ok=True)


def reconstruct_jpeg_lossless(
    data: bytes,
    *,
    base: object,
    mappings: list[object],
    visible_draw: object,
    source_path: str,
    canvas_size: tuple[int, int],
) -> CaptureResult | None:
    """Reorder quantized DCT blocks, or return None for the PNG fallback."""

    if jpeg_dimensions(data) is None or data[:3] != b"\xff\xd8\xff":
        return None
    try:
        import jpeglib  # type: ignore[import-not-found]
        import numpy as np  # type: ignore[import-not-found]
    except (ImportError, OSError):
        return None

    source_dct = None
    source_temp: Path | None = None
    output_dct = None
    output_temp: Path | None = None
    try:
        source_dct, source_temp = _read_dct_bytes(data, jpeglib)
        dimensions = (int(source_dct.width), int(source_dct.height))
        if dimensions != canvas_size or jpeg_dimensions(data) != dimensions:
            return None
        base_mapping = DrawMapping.from_dict(base)
        visible_mapping = DrawMapping.from_dict(visible_draw)
        if (
            base_mapping is None
            or visible_mapping is None
            or not _valid_base(base_mapping, source_path, dimensions, canvas_size)
            or not _valid_base(visible_mapping, source_path, dimensions, canvas_size)
        ):
            return None

        factors = [tuple(int(value) for value in row) for row in source_dct.samp_factor.tolist()]
        if len(factors) not in {1, 3} or any(pair != (1, 1) for pair in factors):
            return None
        if any(
            source_dct.width_in_blocks(index) != source_dct.width_in_blocks(0)
            or source_dct.height_in_blocks(index) != source_dct.height_in_blocks(0)
            for index in range(len(factors))
        ):
            return None

        parsed = [DrawMapping.from_dict(item) for item in mappings]
        if not parsed or any(item is None for item in parsed):
            return None
        tiles = [item for item in parsed if item is not None]
        if any(not _valid_tile(item, source_path, dimensions, canvas_size) for item in tiles):
            return None
        if any(
            value % 8
            for item in tiles
            for value in (item.sx, item.sy, item.sw, item.sh, item.dx, item.dy, item.dw, item.dh)
        ):
            return None

        source_rectangles = [(item.sx, item.sy, item.sw, item.sh) for item in tiles]
        destination_rectangles = [(item.dx, item.dy, item.dw, item.dh) for item in tiles]
        source_coverage = _coverage(source_rectangles)
        destination_coverage = _coverage(destination_rectangles)
        source_cells = _aligned_block_cells(source_rectangles)
        destination_cells = _aligned_block_cells(destination_rectangles)
        if (
            source_coverage is None
            or destination_coverage is None
            or source_cells is None
            or destination_cells is None
            or source_cells != destination_cells
            or source_coverage != destination_coverage
        ):
            return None
        if not _tile_extent_is_complete(source_coverage, source_rectangles, dimensions):
            return None
        if not _tile_extent_is_complete(destination_coverage, destination_rectangles, canvas_size):
            return None
        if any(
            source_dct.width_in_blocks(index) * 8 < dimensions[0]
            or source_dct.height_in_blocks(index) * 8 < dimensions[1]
            for index in range(len(factors))
        ):
            return None

        component_names = [
            name for name in ("Y", "Cb", "Cr") if getattr(source_dct, name, None) is not None
        ]
        if len(component_names) != len(factors):
            return None
        original = {
            name: np.array(getattr(source_dct, name), dtype=np.int16, copy=True)
            for name in component_names
        }
        expected = {name: array.copy() for name, array in original.items()}
        for item in tiles:
            source_x, source_y = item.sx // 8, item.sy // 8
            destination_x, destination_y = item.dx // 8, item.dy // 8
            width, height = item.sw // 8, item.sh // 8
            for name in component_names:
                expected[name][
                    destination_y : destination_y + height,
                    destination_x : destination_x + width,
                ] = original[name][source_y : source_y + height, source_x : source_x + width]

        output_bytes = _write_dct_bytes(source_dct, expected)
        if jpeg_dimensions(output_bytes) != dimensions:
            return None
        output_dct, output_temp = _read_dct_bytes(output_bytes, jpeglib)
        observed = {
            name: np.array(getattr(output_dct, name), dtype=np.int16, copy=True)
            for name in component_names
        }
        if any(not np.array_equal(expected[name], observed[name]) for name in component_names):
            return None
        if not np.array_equal(source_dct.qt, output_dct.qt):
            return None
        if not np.array_equal(source_dct.quant_tbl_no, output_dct.quant_tbl_no):
            return None
        if source_dct.samp_factor.tolist() != output_dct.samp_factor.tolist():
            return None
        if getattr(source_dct, "jpeg_color_space", None) != getattr(
            output_dct, "jpeg_color_space", None
        ):
            return None
        if getattr(source_dct, "progressive_mode", False) != getattr(
            output_dct, "progressive_mode", False
        ):
            return None
        if _marker_payloads(data, 0xDB) != _marker_payloads(output_bytes, 0xDB):
            return None
        if _marker_payloads(data, 0xC4) != _marker_payloads(output_bytes, 0xC4):
            return None
        if _marker_payloads(data, 0xDD) != _marker_payloads(output_bytes, 0xDD):
            return None
        if not _source_metadata_is_preserved(data, output_bytes):
            return None

        edge_block_x = source_coverage[2] // 8
        if any(
            not np.array_equal(original[name][:, edge_block_x:], observed[name][:, edge_block_x:])
            for name in component_names
        ):
            return None
        return CaptureResult(
            data=output_bytes,
            width=dimensions[0],
            height=dimensions[1],
            mime_type="image/jpeg",
            file_extension=".jpg",
        )
    except Exception:  # noqa: BLE001 - coefficient path must fail closed
        return None
    finally:
        if output_dct is not None:
            with suppress(Exception):
                output_dct.close()
        if source_dct is not None:
            with suppress(Exception):
                source_dct.close()

        if output_temp is not None:
            with suppress(OSError):
                output_temp.unlink(missing_ok=True)
        if source_temp is not None:
            with suppress(OSError):
                source_temp.unlink(missing_ok=True)


def _valid_base(
    item: DrawMapping,
    source_path: str,
    dimensions: tuple[int, int],
    canvas_size: tuple[int, int],
) -> bool:
    return (
        item.source_path == source_path
        and (item.source_width, item.source_height) == dimensions
        and (item.canvas_width, item.canvas_height) == canvas_size
        and (item.sx, item.sy, item.sw, item.sh) == (0, 0, *dimensions)
        and (item.dx, item.dy, item.dw, item.dh) == (0, 0, *canvas_size)
        and item.transform == _IDENTITY_TRANSFORM
        and item.composite_operation == "source-over"
        and item.filter == "none"
    )


def _tile_extent_is_complete(
    coverage: tuple[int, int, int, int],
    rectangles: list[tuple[int, int, int, int]],
    image_size: tuple[int, int],
) -> bool:
    """Reject silently truncated edge tiles while allowing a small edge strip."""

    left, top, right, bottom = coverage
    widths = [width for _, _, width, _ in rectangles]
    heights = [height for _, _, _, height in rectangles]
    return (
        left == 0
        and top == 0
        and 0 <= image_size[0] - right < min(widths)
        and 0 <= image_size[1] - bottom < min(heights)
    )


def _valid_tile(
    item: DrawMapping,
    source_path: str,
    dimensions: tuple[int, int],
    canvas_size: tuple[int, int],
) -> bool:
    return (
        item.source_path == source_path
        and (item.source_width, item.source_height) == dimensions
        and (item.canvas_width, item.canvas_height) == canvas_size
        and item.sw == item.dw
        and item.sh == item.dh
        and item.sx >= 0
        and item.sy >= 0
        and item.sx + item.sw <= dimensions[0]
        and item.sy + item.sh <= dimensions[1]
        and item.dx >= 0
        and item.dy >= 0
        and item.dx + item.dw <= canvas_size[0]
        and item.dy + item.dh <= canvas_size[1]
        and item.transform == _IDENTITY_TRANSFORM
        and item.composite_operation == "source-over"
        and item.filter == "none"
    )


def safe_canvas_source_paths(rows: list[dict[str, object]]) -> tuple[str, ...] | None:
    """Return source paths only when every visible canvas has an unambiguous map."""

    paths = [str(row.get("sourcePath") or "") for row in rows]
    if not paths or any(not path or source_path_parts(path) is None for path in paths):
        return None
    if len(set(paths)) != len(paths):
        return None
    return tuple(paths)
