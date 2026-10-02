"""Bounded Comic DAYS C1 capture and terminal reconnaissance.

This probe installs a metadata-only ``drawImage`` hook before navigation and
records canvas/source geometry without encoding, hashing, or copying pixels in
the renderer callback.  It uses the official free-only target and only the
normal viewer forward control; no access, ticket, purchase, login, or
next-episode control is clicked.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from PIL import Image, ImageChops, ImageStat

try:
    from poc.comicdays_probe import redact_metadata, redact_url
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from comicdays_probe import redact_metadata, redact_url
from screenshot_crawler.core.browser import BrowserSession, resolve_cdp_endpoint

DEFAULT_URL = "https://comic-days.com/episode/2550689798754939004"
DEFAULT_OUTPUT_DIR = Path("output/comicdays_c1_capture_probe")
EVAL_TIMEOUT_SECONDS = 8
PROBE_TIMEOUT_SECONDS = 90
MAX_DRAWS = 20_000
MAX_REQUESTS = 500
PAGE_PATH_RE = re.compile(r"/public/page/[^/]+/(?P<page_id>[0-9]+)-")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def bounded_eval(page: Any, expression: str) -> Any:
    return await asyncio.wait_for(page.evaluate(expression), timeout=EVAL_TIMEOUT_SECONDS)


async def install_draw_hook(page: Any) -> None:
    await page.add_init_script(
        f"""(() => {{
          const original = CanvasRenderingContext2D.prototype.drawImage;
          const records = [];
          const canvasIds = new WeakMap();
          const canvasRefs = [];
          const blobRecords = [];
          let nextCanvasId = 1;
          const identifyCanvas = canvas => {{
            if (!canvas) return null;
            if (!canvasIds.has(canvas)) {{
              const id = nextCanvasId++;
              canvasIds.set(canvas, id);
              canvas.__comicDaysProbeId = id;
              canvasRefs.push(canvas);
            }}
            return canvasIds.get(canvas);
          }};
          const describe = source => {{
            if (!source) return {{type: null}};
            const result = {{
              type: source.constructor?.name || typeof source,
              width: source.width || null,
              height: source.height || null,
              naturalWidth: source.naturalWidth || null,
              naturalHeight: source.naturalHeight || null,
              src: typeof source.src === 'string' ? source.src : null,
              currentSrc: typeof source.currentSrc === 'string' ? source.currentSrc : null,
            }};
            return result;
          }};
          CanvasRenderingContext2D.prototype.drawImage = function(source, ...args) {{
            if (records.length < {MAX_DRAWS}) {{
              const canvas = this.canvas;
              const area = canvas?.closest?.('.page-area.js-page-area');
              const areas = [...document.querySelectorAll('.page-area.js-page-area')];
              const transform = this.getTransform ? this.getTransform() : null;
              records.push({{
                timestamp: performance.now(),
                canvas_id: identifyCanvas(canvas),
                canvas: {{
                  width: canvas?.width || null,
                  height: canvas?.height || null,
                  class: canvas?.className || null,
                  page_area_index: area ? areas.indexOf(area) : null,
                }},
                source: describe(source),
                args,
                transform: transform ? {{a: transform.a, b: transform.b, c: transform.c, d: transform.d, e: transform.e, f: transform.f}} : null,
                composite: this.globalCompositeOperation,
                filter: this.filter,
                alpha: this.globalAlpha,
              }});
            }}
            return original.call(this, source, ...args);
          }};
          window.__comicDaysDraws = records;
          const originalCreateObjectURL = URL.createObjectURL.bind(URL);
          URL.createObjectURL = object => {{
            const url = originalCreateObjectURL(object);
            if (blobRecords.length < 500 && object instanceof Blob) {{
              blobRecords.push({{url, size: object.size, type: object.type || null}});
            }}
            return url;
          }};
          window.__comicDaysBlobRecords = blobRecords;
          window.__comicDaysCanvasRefs = canvasRefs;
          window.__comicDaysCanvasById = {{}};
          const refreshCanvasIndex = () => {{
            for (const canvas of canvasRefs) {{
              const id = canvasIds.get(canvas);
              window.__comicDaysCanvasById[id] = canvas;
            }}
          }};
          window.__comicDaysRefreshCanvasIndex = refreshCanvasIndex;
        }})();"""
    )


async def viewer_state(page: Any) -> dict[str, Any]:
    return await bounded_eval(
        page,
        """() => {
          const visible = element => {
            if (!element) return false;
            const r = element.getBoundingClientRect();
            const s = getComputedStyle(element);
            return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
          };
          const intersecting = element => {
            if (!visible(element)) return false;
            const r = element.getBoundingClientRect();
            return r.bottom > 0 && r.right > 0 && r.left < innerWidth && r.top < innerHeight;
          };
          const rect = element => {
            const r = element.getBoundingClientRect();
            return {x: r.x, y: r.y, width: r.width, height: r.height};
          };
          const areaNodes = [...document.querySelectorAll('.page-area.js-page-area')];
          const canvases = [...document.querySelectorAll('canvas.page-image.js-page-image')];
          const images = [...document.querySelectorAll('.page-area.js-page-area img')];
          const area = element => ({
            index: areaNodes.indexOf(element), id: element.id || null,
            class: element.getAttribute('class'), rect: rect(element),
            visible: visible(element), in_viewport: intersecting(element),
            canvas_count: element.querySelectorAll('canvas').length,
            image_count: element.querySelectorAll('img').length,
          });
          return {
            url: location.href,
            slider_now: document.querySelector('.js-viewer-slider-pagenum-now')?.textContent?.trim() || null,
            slider_last: document.querySelector('.js-viewer-slider-pagenum-last')?.textContent?.trim() || null,
            forward: (() => { const e = document.querySelector('.js-slide-forward'); return {visible: visible(e), in_viewport: intersecting(e), class: e?.className || null}; })(),
            backward: (() => { const e = document.querySelector('.js-slide-backward'); return {visible: visible(e), in_viewport: intersecting(e), class: e?.className || null}; })(),
            colophon: (() => { const e = document.querySelector('#viewer-colophon'); return e ? {...area(e), next_links: [...e.querySelectorAll('a[href]')].map(a => ({href: a.href, text: (a.innerText || '').trim().slice(0, 200)}))} : null; })(),
            areas: areaNodes.map(area),
            active_canvases: canvases.map((canvas, index) => ({
              index, area_index: areaNodes.indexOf(canvas.closest('.page-area.js-page-area')),
              probe_id: canvas.__comicDaysProbeId || null,
              width: canvas.width, height: canvas.height, rect: rect(canvas),
              visible: visible(canvas), in_viewport: intersecting(canvas),
            })),
            active_images: images.map((image, index) => ({
              index, area_index: areaNodes.indexOf(image.closest('.page-area.js-page-area')),
              src: image.currentSrc || image.src || null,
              width: image.naturalWidth, height: image.naturalHeight,
              rect: rect(image), visible: visible(image), in_viewport: intersecting(image),
            })),
            // Keep enough recent draws for one 4x4 reconstruction while
            // preventing repeated state snapshots from becoming a fixture.
            draws: (window.__comicDaysDraws || []).slice(-160),
            blob_records: (window.__comicDaysBlobRecords || []).slice(-64),
          };
        }""",
    )


async def save_active_references(page: Any, state: dict[str, Any], output_dir: Path, label: str) -> list[dict[str, Any]]:
    reference_dir = output_dir / "references"
    reference_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    seen: set[int] = set()
    for canvas in state.get("active_canvases", []):
        if not canvas.get("in_viewport"):
            continue
        area_index = canvas.get("area_index")
        if not isinstance(area_index, int) or area_index in seen:
            continue
        seen.add(area_index)
        locator = page.locator("canvas.page-image.js-page-image").nth(int(canvas["index"]))
        path = reference_dir / f"{label}_area_{area_index:03d}.png"
        try:
            await locator.screenshot(path=str(path), timeout=10_000)
            results.append({"area_index": area_index, "path": str(path), "width": canvas.get("width"), "height": canvas.get("height")})
        except Exception as exc:  # noqa: BLE001 - diagnostic fallback
            results.append({"area_index": area_index, "error": type(exc).__name__})
    # The last spread is followed by image-only back matter/colophon areas;
    # retain a bounded viewport reference for those terminal checks too.
    for area in state.get("areas", []):
        area_index = area.get("index")
        if not area.get("in_viewport") or not isinstance(area_index, int) or area_index in seen:
            continue
        if not area.get("image_count") and area.get("id") != "viewer-colophon":
            continue
        seen.add(area_index)
        locator = page.locator(".page-area.js-page-area").nth(area_index)
        path = reference_dir / f"{label}_area_{area_index:03d}.png"
        try:
            await locator.screenshot(path=str(path), timeout=10_000)
            results.append({"area_index": area_index, "path": str(path), "kind": "area"})
        except Exception as exc:  # noqa: BLE001 - diagnostic fallback
            results.append({"area_index": area_index, "error": type(exc).__name__, "kind": "area"})
    return results


def active_reading_area_indices(state: dict[str, Any]) -> list[int]:
    """Select the current content pages from the observed slider contract.

    The viewer keeps one adjacent page mounted on each side and also mounts
    image-only ad/link areas.  Odd slider values identify the next spread;
    only candidate areas containing a page canvas are accepted.
    """

    try:
        slider = int(str(state.get("slider_now", "")))
    except ValueError:
        return []
    candidates = [slider - 1, slider]
    canvased = {
        area.get("index")
        for area in state.get("areas", [])
        if isinstance(area, dict)
        and isinstance(area.get("index"), int)
        and area.get("canvas_count") == 1
        and area.get("id") != "viewer-colophon"
    }
    return [index for index in candidates if index in canvased]


def area_inventory(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "index": area.get("index"),
            "id": area.get("id"),
            "class": area.get("class"),
            "canvas_count": area.get("canvas_count"),
            "image_count": area.get("image_count"),
        }
        for area in state.get("areas", [])
        if isinstance(area, dict)
    ]


def merged_area_inventory(states: list[dict[str, Any]], final_state: dict[str, Any]) -> list[dict[str, Any]]:
    by_index: dict[int, dict[str, Any]] = {}
    for snapshot in [*(item.get("state", {}) for item in states), final_state]:
        for area in area_inventory(snapshot):
            index = area.get("index")
            if isinstance(index, int):
                previous = by_index.get(index)
                if previous is None or area.get("canvas_count", 0) > previous.get("canvas_count", 0) or area.get("image_count", 0) > previous.get("image_count", 0):
                    by_index[index] = area
    return [by_index[index] for index in sorted(by_index)]


async def export_canvas_data_url(page: Any, area_index: int) -> dict[str, Any] | None:
    return await bounded_eval(
        page,
        f"""() => {{
          const area = document.querySelectorAll('.page-area.js-page-area')[{area_index}];
          const canvas = area?.querySelector('canvas.page-image.js-page-image');
          if (!canvas) return null;
          return {{width: canvas.width, height: canvas.height, data_url: canvas.toDataURL('image/png')}};
        }}""",
    )


async def export_intermediate_data_url(page: Any, canvas_id: int) -> dict[str, Any] | None:
    return await bounded_eval(
        page,
        f"""() => {{
          const canvas = (window.__comicDaysCanvasRefs || [])[{canvas_id - 1}];
          if (!canvas || canvas.width !== 1125 || canvas.height !== 1600) return null;
          return {{width: canvas.width, height: canvas.height, data_url: canvas.toDataURL('image/png')}};
        }}""",
    )


def write_data_url_png(value: dict[str, Any] | None, path: Path) -> dict[str, Any]:
    if not value or not isinstance(value.get("data_url"), str) or "," not in value["data_url"]:
        return {"status": "unavailable"}
    import base64

    body = base64.b64decode(value["data_url"].split(",", 1)[1], validate=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return {"status": "saved", "path": str(path), "bytes": len(body), "width": value.get("width"), "height": value.get("height"), "sha256": sha256(body)}


def strict_canvas_sequences(state: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """Return only the latest safe full-base plus 16-tile generation per canvas."""

    grouped: dict[int, list[dict[str, Any]]] = {}
    for draw in state.get("draws", []):
        canvas_id = draw.get("canvas_id")
        if isinstance(canvas_id, int):
            grouped.setdefault(canvas_id, []).append(draw)
    expected_sources = {(sx, sy) for sy in range(0, 1600, 400) for sx in range(0, 1120, 280)}
    sequences: dict[int, dict[str, Any]] = {}
    expected_destinations = {(x, y) for y in (0, 400, 800, 1200) for x in (0, 280, 560, 840)}

    def integer_args(args: Any, length: int) -> bool:
        return isinstance(args, list) and len(args) == length and all(isinstance(value, int) and not isinstance(value, bool) for value in args)

    def safe_state(draw: dict[str, Any]) -> bool:
        transform = draw.get("transform")
        return (
            isinstance(transform, dict)
            and all(transform.get(key) == value for key, value in {"a": 1, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0}.items())
            and draw.get("alpha") == 1
            and draw.get("composite") == "source-over"
            and draw.get("filter") == "none"
        )

    def harmless_spacer(draw: dict[str, Any], canvas: dict[str, Any]) -> bool:
        args = draw.get("args")
        if not integer_args(args, 4):
            return False
        dx, dy, dw, dh = args
        width, height = canvas.get("width"), canvas.get("height")
        return all(isinstance(value, int) and not isinstance(value, bool) for value in (width, height)) and (dw <= 0 or dh <= 0 or dx + dw <= 0 or dy + dh <= 0 or dx >= width or dy >= height)

    for canvas_id, draws in grouped.items():
        base_positions = [
            index for index, draw in enumerate(draws)
            if integer_args(draw.get("args"), 8)
            and draw.get("args") == [0, 0, 1125, 1600, 0, 0, 1125, 1600]
        ]
        if not base_positions:
            continue
        # Only the latest generation is authoritative.  An incomplete redraw
        # must not fall back to an older valid generation.
        start = base_positions[-1]
        draw = draws[start]
        canvas = draw.get("canvas") or {}
        source = draw.get("source") or {}
        if canvas.get("width") != 1125 or canvas.get("height") != 1600 or not safe_state(draw):
            continue
        source_key = (source.get("type"), source.get("width"), source.get("height"), source.get("src"), source.get("currentSrc"))
        if source_key[0] != "HTMLImageElement" or source_key[1:3] != (1125, 1600):
            continue
        tiles: list[list[int]] = []
        seen_sources: set[tuple[int, int]] = set()
        seen_destinations: set[tuple[int, int]] = set()
        safe = True
        for candidate in draws[start + 1:]:
            candidate_args = candidate.get("args")
            candidate_source = candidate.get("source") or {}
            if safe_state(candidate) and harmless_spacer(candidate, canvas):
                continue
            if candidate_source.get("type") != source_key[0] or candidate_source.get("width") != source_key[1] or candidate_source.get("height") != source_key[2] or (candidate_source.get("src"), candidate_source.get("currentSrc")) != (source_key[3], source_key[4]):
                safe = False
                break
            if not safe_state(candidate) or not integer_args(candidate_args, 8) or candidate_args[2:4] != [280, 400] or candidate_args[6:8] != [280, 400]:
                safe = False
                break
            key = (candidate_args[0], candidate_args[1])
            destination = (candidate_args[4], candidate_args[5])
            if key not in expected_sources or key in seen_sources or destination not in expected_destinations or destination in seen_destinations:
                safe = False
                break
            seen_sources.add(key)
            seen_destinations.add(destination)
            tiles.append(list(candidate_args))
        if safe and seen_sources == expected_sources and seen_destinations == expected_destinations and len(tiles) == 16:
            sequences[canvas_id] = {"base": list(draw["args"]), "tiles": tiles, "source": source_key}
    return sequences


async def save_native_proof(page: Any, state: dict[str, Any], output_dir: Path, label: str) -> dict[str, Any]:
    area_indices = active_reading_area_indices(state)
    proof: dict[str, Any] = {"areas": area_indices, "visible": [], "intermediate": [], "sequences": list(strict_canvas_sequences(state))}
    for area_index in area_indices:
        path = output_dir / "native_exports" / f"{label}_area_{area_index:03d}.png"
        try:
            value = await export_canvas_data_url(page, area_index)
            proof["visible"].append({"area_index": area_index, **write_data_url_png(value, path)})
        except Exception as exc:  # noqa: BLE001 - tainted canvas is evidence
            proof["visible"].append({"area_index": area_index, "status": "error", "error": {"type": type(exc).__name__, "message": str(exc)[:240]}})
    for canvas_id in list(strict_canvas_sequences(state))[:4]:
        path = output_dir / "intermediate_exports" / f"{label}_canvas_{canvas_id:03d}.png"
        try:
            value = await export_intermediate_data_url(page, canvas_id)
            proof["intermediate"].append({"canvas_id": canvas_id, **write_data_url_png(value, path)})
        except Exception as exc:  # noqa: BLE001 - tainted canvas is evidence
            proof["intermediate"].append({"canvas_id": canvas_id, "status": "error", "error": {"type": type(exc).__name__, "message": str(exc)[:240]}})
    return proof


async def compare_source_to_reference(page: Any, state: dict[str, Any], reference: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    area_index = reference.get("area_index")
    draws = [
        draw for draw in state.get("draws", [])
        if isinstance(draw, dict)
        and isinstance(draw.get("canvas"), dict)
        and draw["canvas"].get("page_area_index") == area_index
    ]
    sources = []
    for draw in draws:
        source = draw.get("source") or {}
        src = source.get("currentSrc") or source.get("src")
        if isinstance(src, str) and src not in sources:
            sources.append(src)
    result: dict[str, Any] = {"area_index": area_index, "draw_count": len(draws), "source_count": len(sources)}
    if not sources or "path" not in reference:
        return result
    source_url = sources[-1]
    parsed = urlsplit(source_url)
    if parsed.netloc not in {"cdn-img.comic-days.com", "comic-days.com"}:
        result["source_rejected"] = "untrusted_host"
        return result
    try:
        response = await asyncio.wait_for(page.request.get(source_url, timeout=5_000), timeout=8)
        body = await asyncio.wait_for(response.body(), timeout=5)
        result.update({"source_url": redact_url(source_url), "status": response.status, "source_mime": response.headers.get("content-type"), "source_bytes": len(body), "source_sha256": sha256(body)})
        source_path = output_dir / "source_bytes" / f"area_{area_index:03d}.bin"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(body)
        source_image = Image.open(source_path).convert("RGB")
        reference_image = Image.open(reference["path"]).convert("RGB")
        resized = source_image.resize(reference_image.size)
        diff = ImageChops.difference(resized, reference_image)
        result.update({
            "source_dimensions": list(source_image.size),
            "reference_dimensions": list(reference_image.size),
            "resized_mean_abs_difference": float(ImageStat.Stat(diff).mean[0]),
            "resized_max_difference": max(channel[1] for channel in diff.getextrema()),
        })
    except Exception as exc:  # noqa: BLE001 - source optimization is diagnostic only
        result["source_error"] = {"type": type(exc).__name__, "message": str(exc)[:300]}
    return result


async def compare_network_source_to_reference(
    page: Any,
    source_url: str,
    reference: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    """Compare a first-party page JPEG against a selected rendered canvas."""

    result: dict[str, Any] = {
        "area_index": reference.get("area_index"),
        "source_url": redact_url(source_url),
        "association": "request_order_candidate_not_proof",
    }
    if "path" not in reference:
        result["source_error"] = "reference_missing"
        return result
    try:
        response = await asyncio.wait_for(page.request.get(source_url, timeout=5_000), timeout=8)
        body = await asyncio.wait_for(response.body(), timeout=5)
        source_path = output_dir / "network_source_bytes" / f"area_{reference.get('area_index', 'unknown'):03d}.bin"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(body)
        source_image = Image.open(source_path).convert("RGB")
        reference_image = Image.open(reference["path"]).convert("RGB")
        resized = source_image.resize(reference_image.size)
        diff = ImageChops.difference(resized, reference_image)
        result.update({
            "status": response.status,
            "source_mime": response.headers.get("content-type"),
            "source_bytes": len(body),
            "source_sha256": sha256(body),
            "source_dimensions": list(source_image.size),
            "reference_dimensions": list(reference_image.size),
            "resized_mean_abs_difference": float(ImageStat.Stat(diff).mean[0]),
            "resized_max_difference": max(channel[1] for channel in diff.getextrema()),
        })
    except Exception as exc:  # noqa: BLE001 - diagnostic comparison only
        result["source_error"] = {"type": type(exc).__name__, "message": str(exc)[:300]}
    return result


def observed_tile_mapping(state: dict[str, Any], canvas_id: int | None = None) -> list[list[int]]:
    """Return a complete mapping only for one unambiguous runtime canvas."""

    sequences = strict_canvas_sequences(state)
    if canvas_id is not None:
        sequence = sequences.get(canvas_id)
        return list(sequence["tiles"]) if sequence else []
    if len(sequences) != 1:
        return []
    return list(next(iter(sequences.values()))["tiles"])


async def reconstruct_network_source_to_reference(
    page: Any,
    source_url: str,
    reference: dict[str, Any],
    state: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    """Apply only the mapping observed in draw calls, then compare pixels."""

    sequences = strict_canvas_sequences(state)
    if len(sequences) != 1:
        mapping = []
    else:
        mapping = list(next(iter(sequences.values()))["tiles"])
    result: dict[str, Any] = {
        "area_index": reference.get("area_index"),
        "source_url": redact_url(source_url),
        "mapping_tile_count": len(mapping),
        "mapping": mapping,
    }
    if len(mapping) != 16 or "path" not in reference:
        result["status"] = "mapping_unresolved"
        return result
    try:
        response = await asyncio.wait_for(page.request.get(source_url, timeout=5_000), timeout=8)
        body = await asyncio.wait_for(response.body(), timeout=5)
        # The body is written separately so the comparison remains outside the
        # renderer and uses the exact response selected above.
        source_path = output_dir / "network_source_bytes" / "reconstructed_input.bin"
        source_path.write_bytes(body)
        source = Image.open(source_path).convert("RGB")
        # The full-frame base draw preserves the untiled five-pixel right edge.
        reconstructed = source.copy()
        for sx, sy, sw, sh, dx, dy, dw, dh in mapping:
            tile = source.crop((sx, sy, sx + sw, sy + sh))
            if (dw, dh) != tile.size:
                tile = tile.resize((dw, dh))
            reconstructed.paste(tile, (dx, dy))
        reconstructed_path = output_dir / "reconstructed" / f"area_{reference.get('area_index', 'unknown'):03d}.png"
        reconstructed_path.parent.mkdir(parents=True, exist_ok=True)
        reconstructed.save(reconstructed_path)
        reference_image = Image.open(reference["path"]).convert("RGB")
        diff = ImageChops.difference(reconstructed.resize(reference_image.size), reference_image)
        result.update({
            "status": response.status,
            "source_mime": response.headers.get("content-type"),
            "source_dimensions": list(source.size),
            "reference_dimensions": list(reference_image.size),
            "reconstructed_path": str(reconstructed_path),
            "resized_mean_abs_difference": float(ImageStat.Stat(diff).mean[0]),
            "resized_max_difference": max(channel[1] for channel in diff.getextrema()),
        })
    except Exception as exc:  # noqa: BLE001 - diagnostic comparison only
        result["source_error"] = {"type": type(exc).__name__, "message": str(exc)[:300]}
    return result


async def fetch_blob_data_url(page: Any, blob_url: str) -> dict[str, Any]:
    """Read one selected in-page Blob after selection, outside drawImage."""

    return await bounded_eval(
        page,
        f"""async () => {{
          const response = await fetch({json.dumps(blob_url)});
          const blob = await response.blob();
          const bytes = new Uint8Array(await blob.arrayBuffer());
          let binary = '';
          const chunk = 0x8000;
          for (let offset = 0; offset < bytes.length; offset += chunk) {{
            binary += String.fromCharCode(...bytes.subarray(offset, offset + chunk));
          }}
          return {{type: blob.type || null, size: blob.size, data_url: 'data:' + (blob.type || 'application/octet-stream') + ';base64,' + btoa(binary)}};
        }}""",
    )


def reconstruct_from_mapping(source: Image.Image, sequence: dict[str, Any]) -> Image.Image:
    reconstructed = source.copy()
    for sx, sy, sw, sh, dx, dy, dw, dh in sequence["tiles"]:
        tile = source.crop((sx, sy, sx + sw, sy + sh))
        if (dw, dh) != tile.size:
            tile = tile.resize((dw, dh))
        reconstructed.paste(tile, (dx, dy))
    return reconstructed


async def blob_source_proof(
    page: Any,
    state: dict[str, Any],
    reference: dict[str, Any],
    output_dir: Path,
    label: str,
) -> dict[str, Any]:
    """Resolve exact blob/source identity by comparing every strict canvas candidate."""

    area_index = reference.get("area_index")
    selected_ids = [
        canvas.get("probe_id")
        for canvas in state.get("active_canvases", [])
        if canvas.get("area_index") == area_index and isinstance(canvas.get("probe_id"), int)
    ]
    selected_ids = list(dict.fromkeys(selected_ids))
    sequences = strict_canvas_sequences(state)
    result: dict[str, Any] = {"label": label, "area_index": area_index, "selected_probe_ids": selected_ids, "candidate_count": len(sequences), "candidates": []}
    if "path" not in reference or len(selected_ids) != 1:
        result["status"] = "visible_probe_id_unresolved"
        return result
    selected_id = selected_ids[0]
    sequence = sequences.get(selected_id)
    if not sequence:
        result["status"] = "selected_sequence_unresolved"
        return result
    result["selected_canvas_id"] = selected_id
    if "path" not in reference or not sequences:
        result["status"] = "unresolved"
        return result
    import base64

    reference_image = Image.open(reference["path"]).convert("RGB")
    source_url = sequence["source"][3] or sequence["source"][4]
    candidate: dict[str, Any] = {"canvas_id": selected_id, "source_type": sequence["source"][0], "source_url": redact_url(source_url)}
    if not isinstance(source_url, str) or not source_url.startswith("blob:"):
        candidate["status"] = "unsafe_source"
        result["candidates"].append(candidate)
        result["status"] = "unsafe_source"
        return result
    try:
        value = await fetch_blob_data_url(page, source_url)
        encoded = value.get("data_url", "").split(",", 1)[1]
        body = base64.b64decode(encoded, validate=True)
        path = output_dir / "blob_bytes" / f"{label}_canvas_{selected_id:03d}.bin"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        source_image = Image.open(path).convert("RGB")
        reconstructed = reconstruct_from_mapping(source_image, sequence)
        reconstructed_path = output_dir / "blob_reconstructed" / f"{label}_canvas_{selected_id:03d}.png"
        reconstructed_path.parent.mkdir(parents=True, exist_ok=True)
        reconstructed.save(reconstructed_path)
        diff = ImageChops.difference(reconstructed.resize(reference_image.size), reference_image)
        candidate.update({
            "status": "ok",
            "blob_type": value.get("type"),
            "blob_bytes": len(body),
            "blob_sha256": sha256(body),
            "dimensions": list(source_image.size),
            "reconstructed_path": str(reconstructed_path),
            "resized_mean_abs_difference": float(ImageStat.Stat(diff).mean[0]),
            "resized_max_difference": max(channel[1] for channel in diff.getextrema()),
        })
        result["status"] = "resolved_by_visible_probe_id"
    except Exception as exc:  # noqa: BLE001 - bounded source evidence
        candidate["status"] = "error"
        candidate["error"] = {"type": type(exc).__name__, "message": str(exc)[:240]}
        result["status"] = "error"
    result["candidates"].append(candidate)
    return result


async def _run(url: str, output_dir: Path, endpoint: str | None) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    session = await BrowserSession.connect(resolve_cdp_endpoint(cli_endpoint=endpoint))
    page = await session.new_page()
    requests: list[dict[str, Any]] = []
    responses: list[dict[str, Any]] = []

    def on_request(request: Any) -> None:
        parsed = urlsplit(request.url)
        if parsed.netloc not in {"comic-days.com", "cdn.comic-days.com", "cdn-img.comic-days.com"} or len(requests) >= MAX_REQUESTS:
            return
        requests.append({"method": request.method, "resource_type": request.resource_type, "url": redact_url(request.url), "path": parsed.path, "mime_hint": request.headers.get("accept")})

    def on_response(response: Any) -> None:
        parsed = urlsplit(response.url)
        if parsed.netloc not in {"comic-days.com", "cdn.comic-days.com", "cdn-img.comic-days.com"}:
            return
        if not (parsed.path.startswith("/public/page/") or parsed.path.startswith("/atom/")):
            return
        if len(responses) >= MAX_REQUESTS:
            return
        responses.append({
            "status": response.status,
            "url": redact_url(response.url),
            "path": parsed.path,
            "content_type": response.headers.get("content-type"),
        })

    page.on("request", on_request)
    page.on("response", on_response)
    try:
        await install_draw_hook(page)
        await page.goto(url, wait_until="commit", timeout=30_000)
        await page.wait_for_timeout(5_000)
        states: list[dict[str, Any]] = []
        references: list[dict[str, Any]] = []
        source_comparisons: list[dict[str, Any]] = []
        native_proofs: list[dict[str, Any]] = []
        blob_proofs: list[dict[str, Any]] = []
        initial = await viewer_state(page)
        states.append({"label": "first", "state": await redact_metadata(initial)})
        native_proofs.append({"label": "first", "proof": await save_native_proof(page, initial, output_dir, "first")})
        initial_refs = await save_active_references(page, initial, output_dir, "first")
        references.extend(initial_refs)
        initial_content_ref = next((ref for ref in initial_refs if ref.get("area_index") in active_reading_area_indices(initial) and "path" in ref), None)
        if initial_content_ref:
            blob_proofs.append(await blob_source_proof(page, initial, initial_content_ref, output_dir, "first"))
        for reference in initial_refs:
            source_comparisons.append(await compare_source_to_reference(page, initial, reference, output_dir))
        for step in range(18):
            forward = page.locator(".js-slide-forward")
            before = await viewer_state(page)
            if not before.get("forward", {}).get("visible"):
                break
            try:
                await forward.click(timeout=3_000)
                await page.wait_for_timeout(450)
            except Exception as exc:  # noqa: BLE001 - terminal probe preserves evidence
                states.append({"label": f"forward_error_{step}", "error": {"type": type(exc).__name__, "message": str(exc)[:300]}, "state": await redact_metadata(before)})
                break
            after = await viewer_state(page)
            label = "normal_spread" if step == 1 else ("final_content" if after.get("slider_now") == "33" else ("final_candidate" if after.get("slider_now") == "35" else f"forward_{step + 1}"))
            states.append({"label": label, "state": await redact_metadata(after)})
            if label in {"normal_spread", "final_content"}:
                native_proofs.append({"label": label, "proof": await save_native_proof(page, after, output_dir, label)})
            after_refs = await save_active_references(page, after, output_dir, label)
            references.extend(after_refs)
            if label in {"normal_spread", "final_content"}:
                content_ref = next((ref for ref in after_refs if ref.get("area_index") in active_reading_area_indices(after) and "path" in ref), None)
                if content_ref:
                    blob_proofs.append(await blob_source_proof(page, after, content_ref, output_dir, label))
            for reference in after_refs:
                source_comparisons.append(await compare_source_to_reference(page, after, reference, output_dir))
            if label == "final_candidate":
                break
        final_before = await viewer_state(page)
        terminal_advance: dict[str, Any] = {"before": await redact_metadata(final_before)}
        if final_before.get("forward", {}).get("visible"):
            try:
                await page.locator(".js-slide-forward").click(force=True, timeout=3_000)
                await page.wait_for_timeout(700)
                terminal_state = await viewer_state(page)
                terminal_advance["after"] = await redact_metadata(terminal_state)
                terminal_refs = await save_active_references(page, terminal_state, output_dir, "terminal_after")
                references.extend(terminal_refs)
                for reference in terminal_refs:
                    source_comparisons.append(await compare_source_to_reference(page, terminal_state, reference, output_dir))
                terminal_advance["status"] = "advanced"
            except Exception as exc:  # noqa: BLE001 - preserve terminal evidence
                terminal_advance["status"] = "error"
                terminal_advance["error"] = {"type": type(exc).__name__, "message": str(exc)[:300]}
        inventory = merged_area_inventory(states, final_before)
        report = {
            "probe": "comicdays_c1_capture_probe",
            "target_url": redact_url(url),
            "final_url": redact_url(page.url),
            "states": states,
            "terminal_advance": terminal_advance,
            "references": references,
            "source_comparisons": source_comparisons,
            "native_proofs": native_proofs,
            "blob_proofs": blob_proofs,
            "area_inventory": inventory,
            "content_area_indices": [
                area["index"] for area in inventory
                if area.get("canvas_count") == 1 and area.get("id") != "viewer-colophon"
            ],
            "network_source_comparisons": [
                await compare_network_source_to_reference(page, response["url"], initial_refs[0], output_dir)
                for response in responses[:2]
            ] if initial_refs else [],
            "observed_reconstruction": (
                await reconstruct_network_source_to_reference(
                    page, responses[0]["url"], initial_refs[0], initial, output_dir
                )
                if initial_refs and responses else {}
            ),
            "requests": requests,
            "request_count": len(requests),
            "responses": responses,
            "response_count": len(responses),
        }
        write_json(output_dir / "report.json", report)
    finally:
        await session.close_page(page)
        await session.close()


async def run(url: str, output_dir: Path, endpoint: str | None) -> None:
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            await _run(url, output_dir, endpoint)
    except TimeoutError:
        write_json(output_dir / "report.json", {"probe": "comicdays_c1_capture_probe", "target_url": redact_url(url), "error": {"type": "ProbeTimeout", "timeout_seconds": PROBE_TIMEOUT_SECONDS}})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--cdp-endpoint")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(run(args.url, args.output_dir, args.cdp_endpoint))
