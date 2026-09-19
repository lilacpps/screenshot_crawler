"""Investigate BookWalker's pre-ImageBitmap source bytes.

This is a diagnostic-only script.  It connects to an already running Chrome
over CDP, records redacted response metadata, and installs small page hooks for
Blob/ArrayBuffer/fetch/XHR/Response/createImageBitmap.  It never changes the
production adapter or capture path.  Standard image bytes discovered during a
run are written below the requested diagnostic output directory only.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import re
import struct
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from playwright.async_api import Locator, Page, Request, Response, Route, async_playwright

from screenshot_crawler.core.capture import capture_locator
from screenshot_crawler.site_adapters.bookwalker.adapter import BookWalkerAdapter

DEFAULT_URL = (
    "https://viewer-trial.bookwalker.jp/03/21/viewer.html?"
    "cid=3e1a3eff-5dd5-46b5-8403-b37ed6a46166&cty=0"
)
MAX_RESPONSE_BODY_BYTES = 64 * 1024 * 1024
MAX_EMBEDDED_SOURCE_BYTES = 16 * 1024 * 1024
STANDARD_FORMATS = {"png", "jpeg", "webp", "avif", "gif"}


HOOK_SCRIPT = r"""
(() => {
  if (window.__bookwalkerOriginalSourceHooksInstalled) return;
  window.__bookwalkerOriginalSourceHooksInstalled = true;
  window.__bookwalkerOriginalSourceEvents = [];
  window.__bookwalkerOriginalDrawCalls = [];
  window.__bookwalkerDrawCalls = [];

  const MAX_EVENTS = 1000;
  const MAX_EMBEDDED_BYTES = 16 * 1024 * 1024;
  let nextObjectId = 1;
  let nextCanvasId = 1;
  const objectIds = new WeakMap();
  const responseIds = new WeakMap();
  const canvasIds = new WeakMap();

  const finite = value => Number.isFinite(value) ? Number(value) : null;
  const push = event => {
    window.__bookwalkerOriginalSourceEvents.push({timestamp: performance.now(), ...event});
    if (window.__bookwalkerOriginalSourceEvents.length > MAX_EVENTS) {
      window.__bookwalkerOriginalSourceEvents.shift();
    }
  };
  const redactedUrl = value => {
    try {
      const parsed = new URL(String(value), location.href);
      const keys = [...new Set([...parsed.searchParams.keys()])];
      parsed.search = keys.map(key => `${encodeURIComponent(key)}=<redacted>`).join('&');
      parsed.hash = '';
      parsed.pathname = parsed.pathname.split('/').map(part =>
        part.length > 64 ? '<redacted>' : part).join('/');
      return parsed.toString();
    } catch (error) {
      return '<unparseable-url>';
    }
  };
  const idFor = object => {
    if (!object || (typeof object !== 'object' && typeof object !== 'function')) return null;
    let id = objectIds.get(object);
    if (!id) {
      id = String(nextObjectId++);
      objectIds.set(object, id);
    }
    return id;
  };
  const basicInfo = object => ({
    objectId: idFor(object),
    constructor: object?.constructor?.name || null,
    width: finite(object?.width),
    height: finite(object?.height),
    size: finite(object?.size),
    type: typeof object?.type === 'string' ? object.type : null,
  });
  const isArrayBuffer = value => Object.prototype.toString.call(value) === '[object ArrayBuffer]';
  const isBlob = value => Object.prototype.toString.call(value) === '[object Blob]';
  const bytesMeta = async (buffer, includeBytes = true) => {
    try {
      const bytes = new Uint8Array(buffer);
      const result = {
        byteSize: bytes.byteLength,
        firstBytesHex: [...bytes.slice(0, 16)].map(value => value.toString(16).padStart(2, '0')).join(''),
      };
      if (includeBytes && bytes.byteLength <= MAX_EMBEDDED_BYTES) {
        let binary = '';
        for (let offset = 0; offset < bytes.length; offset += 0x8000) {
          binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
        }
        result.base64 = btoa(binary);
      }
      return result;
    } catch (error) {
      return {byteError: String(error)};
    }
  };
  const attachBytes = (event, buffer) => {
    Promise.resolve(bytesMeta(buffer)).then(meta => Object.assign(event, meta));
  };
  const recordResponse = (response, kind) => {
    if (!response || typeof response !== 'object') return null;
    let responseId = responseIds.get(response);
    if (!responseId) {
      responseId = String(nextObjectId++);
      responseIds.set(response, responseId);
    }
    push({
      kind,
      responseId,
      url: redactedUrl(response.url || ''),
      status: finite(response.status),
      contentType: response.headers?.get?.('content-type') || null,
    });
    return responseId;
  };
  const recordResponseValue = (response, kind, promise) => {
    const responseId = recordResponse(response, `${kind}:called`);
    Promise.resolve(promise).then(value => {
      const event = {
        kind: `${kind}:result`,
        responseId,
        value: basicInfo(value),
      };
      push(event);
      if (isArrayBuffer(value)) {
        attachBytes(event, value);
      } else if (isBlob(value)) {
        value.arrayBuffer().then(buffer => attachBytes(event, buffer)).catch(error => {
          event.byteError = String(error);
        });
      }
    }).catch(error => push({kind: `${kind}:error`, responseId, error: String(error)}));
  };

  const originalFetch = window.fetch;
  window.fetch = function(...args) {
    const promise = originalFetch.apply(this, args);
    Promise.resolve(promise).then(response => {
      recordResponse(response, 'fetch:response');
    }).catch(error => push({kind: 'fetch:error', error: String(error)}));
    return promise;
  };

  if (window.Response?.prototype) {
    const originalArrayBuffer = Response.prototype.arrayBuffer;
    Response.prototype.arrayBuffer = function(...args) {
      const promise = originalArrayBuffer.apply(this, args);
      recordResponseValue(this, 'Response.arrayBuffer', promise);
      return promise;
    };
    const originalBlob = Response.prototype.blob;
    Response.prototype.blob = function(...args) {
      const promise = originalBlob.apply(this, args);
      recordResponseValue(this, 'Response.blob', promise);
      return promise;
    };
  }

  const originalOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function(method, url, ...args) {
    this.__bookwalkerDiagRequest = {
      method: String(method),
      url: redactedUrl(url),
    };
    return originalOpen.call(this, method, url, ...args);
  };
  const originalSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function(...args) {
    this.addEventListener('loadend', () => {
      const request = this.__bookwalkerDiagRequest || {};
      const event = {
        kind: 'XMLHttpRequest:loadend',
        method: request.method || null,
        url: request.url || null,
        status: finite(this.status),
        responseType: this.responseType || '',
      };
      push(event);
      if (isArrayBuffer(this.response)) {
        attachBytes(event, this.response);
      } else if (isBlob(this.response)) {
        this.response.arrayBuffer().then(buffer => attachBytes(event, buffer)).catch(error => {
          event.byteError = String(error);
        });
      }
    }, {once: true});
    return originalSend.apply(this, args);
  };

  if (window.URL?.createObjectURL) {
    const originalCreateObjectURL = URL.createObjectURL.bind(URL);
    URL.createObjectURL = function(object) {
      const result = originalCreateObjectURL(object);
      push({kind: 'URL.createObjectURL', url: 'blob:<redacted>', object: basicInfo(object)});
      return result;
    };
  }
  if (window.URL?.revokeObjectURL) {
    const originalRevokeObjectURL = URL.revokeObjectURL.bind(URL);
    URL.revokeObjectURL = function(url) {
      push({kind: 'URL.revokeObjectURL', url: 'blob:<redacted>'});
      return originalRevokeObjectURL(url);
    };
  }

  if (window.createImageBitmap) {
    const originalCreateImageBitmap = window.createImageBitmap.bind(window);
    window.createImageBitmap = function(source, ...args) {
      const input = basicInfo(source);
      const promise = originalCreateImageBitmap(source, ...args);
      Promise.resolve(promise).then(bitmap => {
        const event = {
          kind: 'createImageBitmap',
          input,
          imageBitmap: basicInfo(bitmap),
          imageBitmapId: idFor(bitmap),
          options: args.length ? args.map(value => typeof value === 'object' ? '[object]' : value) : [],
        };
        push(event);
        if (isBlob(source)) {
          source.arrayBuffer().then(buffer => attachBytes(event, buffer)).catch(error => {
            event.byteError = String(error);
          });
        } else if (isArrayBuffer(source)) {
          attachBytes(event, source);
        } else if (ArrayBuffer.isView(source)) {
          attachBytes(event, source.buffer);
        }
      }).catch(error => push({kind: 'createImageBitmap:error', input, error: String(error)}));
      return promise;
    };
  }

  const originalDrawImage = CanvasRenderingContext2D.prototype.drawImage;
  const getCanvasId = canvas => {
    let id = canvasIds.get(canvas);
    if (!id) {
      id = String(nextCanvasId++);
      canvasIds.set(canvas, id);
      canvas.dataset.bookwalkerTraceId = id;
    }
    return id;
  };
  const geometry = (source, values) => {
    const width = finite(source?.width);
    const height = finite(source?.height);
    if (values.length === 2 && width !== null && height !== null) {
      return {
        sourceRect: {x: 0, y: 0, width, height},
        destination: {x: values[0], y: values[1], width, height},
      };
    }
    if (values.length === 4) {
      return {
        sourceRect: width === null || height === null ? null : {x: 0, y: 0, width, height},
        destination: {x: values[0], y: values[1], width: values[2], height: values[3]},
      };
    }
    if (values.length === 8) {
      return {
        sourceRect: {x: values[0], y: values[1], width: values[2], height: values[3]},
        destination: {x: values[4], y: values[5], width: values[6], height: values[7]},
      };
    }
    return {sourceRect: null, destination: null};
  };
  const copyNativePng = (source, rect) => {
    if (!rect || rect.width <= 0 || rect.height <= 0) return null;
    try {
      const target = document.createElement('canvas');
      target.width = Math.round(rect.width);
      target.height = Math.round(rect.height);
      const context = target.getContext('2d');
      if (!context) return null;
      originalDrawImage.call(context, source, rect.x, rect.y, rect.width, rect.height,
        0, 0, rect.width, rect.height);
      return target.toDataURL('image/png');
    } catch (error) {
      return null;
    }
  };
  CanvasRenderingContext2D.prototype.drawImage = function(...args) {
    try {
      const canvas = this.canvas;
      const source = args[0];
      const values = args.slice(1).map(Number);
      const details = geometry(source, values);
      if (canvas && canvas.width > 1000 && canvas.height > 500 && source && details.destination) {
        const canvasId = getCanvasId(canvas);
        const draw = {
          canvasId,
          canvasWidth: canvas.width,
          canvasHeight: canvas.height,
          sourceId: idFor(source),
          source: basicInfo(source),
          sourceRect: details.sourceRect,
          destination: details.destination,
          argumentForm: values.length + 1,
          transform: (() => {
            try {
              const matrix = this.getTransform();
              return {a: matrix.a, b: matrix.b, c: matrix.c, d: matrix.d, e: matrix.e, f: matrix.f};
            } catch (error) { return null; }
          })(),
          globalCompositeOperation: this.globalCompositeOperation,
          filter: this.filter,
          nativePng: copyNativePng(source, details.sourceRect),
        };
        window.__bookwalkerOriginalDrawCalls.push(draw);
        window.__bookwalkerDrawCalls.push({canvasId, canvasWidth: canvas.width,
          canvasHeight: canvas.height, destination: [details.destination.x, details.destination.y,
          details.destination.width, details.destination.height]});
        if (window.__bookwalkerOriginalDrawCalls.length > 500) window.__bookwalkerOriginalDrawCalls.shift();
        if (window.__bookwalkerDrawCalls.length > 500) window.__bookwalkerDrawCalls.shift();
      }
    } catch (error) {}
    return originalDrawImage.apply(this, args);
  };
})();
"""


def redact_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        query_keys = sorted({key for key, _ in parse_qsl(parsed.query, keep_blank_values=True)})
        query = urlencode([(key, "<redacted>") for key in query_keys])
        path = "/".join("<redacted>" if len(part) > 64 else part for part in parsed.path.split("/"))
        return urlunsplit((parsed.scheme, parsed.netloc, path, query, ""))
    except Exception:  # noqa: BLE001
        return "<unparseable-url>"


def url_extension(value: str) -> str | None:
    path = urlsplit(value).path.lower()
    match = re.search(r"\.([a-z0-9]{1,8})$", path)
    return match.group(1) if match else None


def png_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    return None


def gif_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) >= 10 and data[:6] in {b"GIF87a", b"GIF89a"}:
        return struct.unpack("<HH", data[6:10])
    return None


def jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    if not data.startswith(b"\xff\xd8"):
        return None
    offset = 2
    sof = set(range(0xC0, 0xC4)) | set(range(0xC5, 0xC8)) | set(range(0xC9, 0xCC)) | set(range(0xCD, 0xD0))
    while offset + 9 <= len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        marker = data[offset + 1]
        offset += 2
        if marker in {0xD8, 0xD9}:
            continue
        if offset + 2 > len(data):
            return None
        length = int.from_bytes(data[offset:offset + 2], "big")
        if length < 2 or offset + length > len(data):
            return None
        if marker in sof:
            return (int.from_bytes(data[offset + 5:offset + 7], "big"), int.from_bytes(data[offset + 3:offset + 5], "big"))
        offset += length
    return None


def webp_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) < 16 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    offset = 12
    while offset + 8 <= len(data):
        chunk = data[offset:offset + 4]
        size = int.from_bytes(data[offset + 4:offset + 8], "little")
        payload = offset + 8
        if chunk == b"VP8X" and payload + 10 <= len(data):
            width = 1 + int.from_bytes(data[payload + 4:payload + 7] + b"\x00", "little")
            height = 1 + int.from_bytes(data[payload + 7:payload + 10] + b"\x00", "little")
            return width, height
        if chunk == b"VP8 " and payload + 10 <= len(data) and data[payload + 6:payload + 9] == b"\x9d\x01\x2a":
            return (int.from_bytes(data[payload + 8:payload + 10], "little") & 0x3FFF,
                    int.from_bytes(data[payload + 10:payload + 12], "little") & 0x3FFF)
        if chunk == b"VP8L" and payload + 5 <= len(data) and data[payload] == 0x2F:
            bits = data[payload + 1:payload + 5]
            width = 1 + (bits[0] | ((bits[1] & 0x3F) << 8))
            height = 1 + ((bits[1] >> 6) | (bits[2] << 2) | ((bits[3] & 0x0F) << 10))
            return width, height
        offset = payload + size + (size & 1)
    return None


def inspect_bytes(data: bytes) -> dict[str, Any]:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        image_format, dimensions = "png", png_dimensions(data)
    elif data.startswith(b"\xff\xd8"):
        image_format, dimensions = "jpeg", jpeg_dimensions(data)
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        image_format, dimensions = "webp", webp_dimensions(data)
    elif len(data) >= 12 and data[:6] in {b"GIF87a", b"GIF89a"}:
        image_format, dimensions = "gif", gif_dimensions(data)
    elif len(data) >= 12 and data[4:8] == b"ftyp" and any(brand in data[8:32] for brand in (b"avif", b"avis")):
        image_format, dimensions = "avif", None
    else:
        image_format, dimensions = "unknown", None
    if dimensions is None and image_format in STANDARD_FORMATS:
        try:
            from PIL import Image

            with Image.open(__import__("io").BytesIO(data)) as image:
                dimensions = image.size
        except Exception:  # noqa: BLE001
            dimensions = None
    return {
        "format": image_format,
        "width": dimensions[0] if dimensions else None,
        "height": dimensions[1] if dimensions else None,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "first_bytes_hex": data[:16].hex(),
    }


def decode_base64(value: Any) -> bytes | None:
    if not isinstance(value, str):
        return None
    try:
        if value.startswith("data:"):
            value = value.split(",", 1)[1]
        return base64.b64decode(value, validate=True)
    except Exception:  # noqa: BLE001
        return None


def compare_image_files(left: str | None, right: str | None) -> dict[str, float | int | None]:
    """Compare decoded pixels; used only to associate a response with a draw."""

    if not left or not right:
        return {"available": 0, "mean_abs_difference": None, "rms_difference": None}
    try:
        from PIL import Image, ImageChops, ImageStat

        with Image.open(left) as left_image:
            left_rgb = left_image.convert("RGB")
        with Image.open(right) as right_image:
            right_rgb = right_image.convert("RGB")
        if right_rgb.size != left_rgb.size:
            right_rgb = right_rgb.resize(left_rgb.size, Image.Resampling.LANCZOS)
        difference = ImageChops.difference(left_rgb, right_rgb)
        stats = ImageStat.Stat(difference)
        rms = ImageStat.Stat(difference).rms
        return {
            "available": 1,
            "mean_abs_difference": round(sum(stats.mean) / len(stats.mean), 4),
            "rms_difference": round(sum(rms) / len(rms), 4),
        }
    except Exception:  # noqa: BLE001
        return {"available": 0, "mean_abs_difference": None, "rms_difference": None}


async def compare_image_files_in_page(
    page: Page,
    left: str | None,
    right: str | None,
) -> dict[str, float | int | None]:
    """Fallback pixel comparison using the already-connected browser decoder."""

    if not left or not right:
        return {"available": 0, "mean_abs_difference": None, "rms_difference": None}
    try:
        left_bytes = base64.b64encode(Path(left).read_bytes()).decode("ascii")
        right_bytes = base64.b64encode(Path(right).read_bytes()).decode("ascii")
        return await page.evaluate(
            """
            async ({left, right}) => {
              const load = (value, mime) => new Promise((resolve, reject) => {
                const image = new Image();
                image.onload = () => resolve(image);
                image.onerror = reject;
                image.src = `data:${mime};base64,${value}`;
              });
              const leftImage = await load(left, 'image/png');
              const rightImage = await load(right, 'image/jpeg');
              const width = leftImage.naturalWidth;
              const height = leftImage.naturalHeight;
              const canvas = document.createElement('canvas');
              canvas.width = width;
              canvas.height = height;
              const context = canvas.getContext('2d', {willReadFrequently: true});
              if (!context) return {available: 0, mean_abs_difference: null, rms_difference: null};
              context.drawImage(leftImage, 0, 0, width, height);
              const leftPixels = context.getImageData(0, 0, width, height).data;
              context.clearRect(0, 0, width, height);
              context.drawImage(rightImage, 0, 0, width, height);
              const rightPixels = context.getImageData(0, 0, width, height).data;
              let sum = 0;
              let squared = 0;
              let count = 0;
              for (let index = 0; index < leftPixels.length; index += 4) {
                for (let channel = 0; channel < 3; channel++) {
                  const difference = Math.abs(leftPixels[index + channel] - rightPixels[index + channel]);
                  sum += difference;
                  squared += difference * difference;
                  count += 1;
                }
              }
              return {
                available: 1,
                mean_abs_difference: Math.round((sum / count) * 10000) / 10000,
                rms_difference: Math.round(Math.sqrt(squared / count) * 10000) / 10000,
              };
            }
            """,
            {"left": left_bytes, "right": right_bytes},
        )
    except Exception:  # noqa: BLE001
        return {"available": 0, "mean_abs_difference": None, "rms_difference": None}


def box_from_call(call: dict[str, Any]) -> dict[str, int] | None:
    destination = call.get("destination")
    if not isinstance(destination, dict):
        return None
    try:
        box = {key: round(float(destination[key])) for key in ("x", "y", "width", "height")}
    except (KeyError, TypeError, ValueError):
        return None
    return box if box["width"] >= 100 and box["height"] >= 100 else None


def select_final_draw_calls(calls: list[dict[str, Any]], canvas_id: str | None) -> list[dict[str, Any]]:
    filtered = [call for call in calls if canvas_id is None or call.get("canvasId") == canvas_id]
    by_box: dict[tuple[int, int, int, int], dict[str, Any]] = {}
    for call in filtered:
        box = box_from_call(call)
        if box:
            by_box[(box["x"], box["y"], box["width"], box["height"])] = call
    return sorted(by_box.values(), key=lambda call: box_from_call(call)["x"], reverse=True)


async def response_record(response: Response, index: int, output_dir: Path) -> dict[str, Any]:
    request = response.request
    record: dict[str, Any] = {
        "index": index,
        "url": redact_url(response.url),
        "method": request.method,
        "status": response.status,
        "content_type": response.headers.get("content-type"),
        "content_length_header": response.headers.get("content-length"),
        "resource_type": request.resource_type,
        "url_extension": url_extension(response.url),
    }
    try:
        body = await asyncio.wait_for(response.body(), timeout=5)
        record.update({"body_bytes": len(body), **inspect_bytes(body)})
        if len(body) <= MAX_RESPONSE_BODY_BYTES and record["format"] in STANDARD_FORMATS:
            suffix = {"jpeg": "jpg"}.get(record["format"], record["format"])
            path = output_dir / f"network-{index}.{suffix}"
            path.write_bytes(body)
            record["artifact"] = str(path)
    except Exception as exc:  # noqa: BLE001
        record["body_error"] = str(exc)
    return record


async def locator_metadata(locator: Locator) -> dict[str, Any]:
    return await locator.evaluate(
        """element => { const rect = element.getBoundingClientRect(); return {
          canvasWidth: element.width, canvasHeight: element.height,
          cssWidth: rect.width, cssHeight: rect.height,
          traceId: element.dataset.bookwalkerTraceId || null,
        }; }"""
    )


async def save_capture(output_dir: Path, prefix: str, data: bytes) -> dict[str, Any]:
    path = output_dir / f"{prefix}.png"
    path.write_bytes(data)
    return {"path": str(path), **inspect_bytes(data)}


async def measure(endpoint: str, output_dir: Path, url: str, advance_pages: int) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(endpoint)
        context = browser.contexts[0]
        page = await context.new_page()
        response_tasks: list[asyncio.Task[dict[str, Any]]] = []
        response_index = 0
        cdp_response_meta: dict[str, dict[str, Any]] = {}
        cdp_request_methods: dict[str, str] = {}
        cdp_tasks: list[asyncio.Task[None]] = []
        cdp_records: list[dict[str, Any]] = []
        cdp_index = 0
        route_records: list[dict[str, Any]] = []
        route_index = 0

        def on_response(response: Response) -> None:
            nonlocal response_index
            response_index += 1
            response_tasks.append(asyncio.create_task(response_record(response, response_index, output_dir)))

        cdp = await context.new_cdp_session(page)

        async def on_cdp_body_finished(params: dict[str, Any]) -> None:
            nonlocal cdp_index
            request_id = params.get("requestId")
            meta = cdp_response_meta.get(request_id)
            if not meta:
                return
            cdp_index += 1
            record = {"index": cdp_index, **meta, "encoded_body_bytes": params.get("encodedDataLength")}
            try:
                payload = await cdp.send("Network.getResponseBody", {"requestId": request_id})
                body = base64.b64decode(payload["body"]) if payload.get("base64Encoded") else payload.get("body", "").encode()
                record.update({"body_bytes": len(body), **inspect_bytes(body)})
                if len(body) <= MAX_RESPONSE_BODY_BYTES and record["format"] in STANDARD_FORMATS:
                    suffix = {"jpeg": "jpg"}.get(record["format"], record["format"])
                    path = output_dir / f"cdp-{cdp_index}.{suffix}"
                    path.write_bytes(body)
                    record["artifact"] = str(path)
            except Exception as exc:  # noqa: BLE001
                record["body_error"] = str(exc)
            cdp_records.append(record)

        def on_cdp_response_received(params: dict[str, Any]) -> None:
            response = params.get("response") or {}
            request_id = params.get("requestId")
            headers = response.get("headers") or {}
            normalized_headers = {str(key).lower(): value for key, value in headers.items()}
            cdp_response_meta[request_id] = {
                "url": redact_url(str(response.get("url") or "")),
                "method": cdp_request_methods.get(request_id),
                "status": response.get("status"),
                "content_type": normalized_headers.get("content-type") or response.get("mimeType"),
                "content_length_header": normalized_headers.get("content-length"),
                "resource_type": str(params.get("type") or "unknown").lower(),
                "url_extension": url_extension(str(response.get("url") or "")),
            }

        def on_cdp_request_will_be_sent(params: dict[str, Any]) -> None:
            request_id = params.get("requestId")
            request = params.get("request") or {}
            if request_id:
                cdp_request_methods[request_id] = str(request.get("method") or "GET")

        cdp.on("Network.requestWillBeSent", on_cdp_request_will_be_sent)
        cdp.on("Network.responseReceived", on_cdp_response_received)
        cdp.on("Network.loadingFinished", lambda params: cdp_tasks.append(asyncio.create_task(on_cdp_body_finished(params))))
        await cdp.send("Network.enable")

        async def on_epub_route(route: Route, request: Request) -> None:
            nonlocal route_index
            try:
                fetched = await route.fetch(timeout=15_000)
                body = await fetched.body()
                route_index += 1
                record: dict[str, Any] = {
                    "index": route_index,
                    "url": redact_url(request.url),
                    "method": request.method,
                    "status": fetched.status,
                    "content_type": fetched.headers.get("content-type"),
                    "content_length_header": fetched.headers.get("content-length"),
                    "resource_type": request.resource_type,
                    "url_extension": url_extension(request.url),
                    "route_fetch": True,
                    "body_bytes": len(body),
                    **inspect_bytes(body),
                }
                if record["format"] in STANDARD_FORMATS:
                    suffix = {"jpeg": "jpg"}.get(record["format"], record["format"])
                    path = output_dir / f"route-{route_index}.{suffix}"
                    path.write_bytes(body)
                    record["artifact"] = str(path)
                route_records.append(record)
                await route.fulfill(response=fetched, body=body)
            except Exception as exc:  # noqa: BLE001
                route_records.append({
                    "index": route_index + 1,
                    "url": redact_url(request.url),
                    "method": request.method,
                    "resource_type": request.resource_type,
                    "route_fetch": True,
                    "body_error": str(exc),
                })
                await route.continue_()

        await page.route("https://viewer-epubs-trial.bookwalker.jp/**", on_epub_route)
        page.on("response", on_response)
        adapter = BookWalkerAdapter()
        try:
            await page.add_init_script(HOOK_SCRIPT)
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            await adapter._wait_for_render_ready(page)
            for _ in range(advance_pages):
                await page.evaluate("window.__bookwalkerOriginalDrawCalls = []; window.__bookwalkerDrawCalls = []")
                previous = await adapter.get_content_identity(page)
                await adapter.go_next(page)
                await adapter.wait_for_change(page, previous)
                await adapter._wait_for_render_ready(page)
            await page.wait_for_timeout(1_000)
            canvas = await adapter._visible_canvas(page)
            if canvas is None:
                raise RuntimeError("BookWalker content canvas was not visible")
            canvas_info = await locator_metadata(canvas)
            current_canvas = await capture_locator(canvas)
            canvas_info["capture"] = await save_capture(output_dir, "current-canvas", current_canvas.data)
            calls = await page.evaluate("() => window.__bookwalkerOriginalDrawCalls || []")
            selected = select_final_draw_calls(calls, canvas_info.get("traceId"))
            targets = await adapter.get_capture_targets(page)
            target_results: list[dict[str, Any]] = []
            try:
                for index, target in enumerate(targets, start=1):
                    capture = await capture_locator(target)
                    target_results.append(await save_capture(output_dir, f"target-{index}-current", capture.data))
            finally:
                await adapter.cleanup_capture_targets(page)

            events = await page.evaluate("() => window.__bookwalkerOriginalSourceEvents || []")
            event_by_id = {
                event.get("imageBitmapId"): event for event in events
                if event.get("kind") == "createImageBitmap" and event.get("imageBitmapId")
            }
            candidate_results: list[dict[str, Any]] = []
            for index, call in enumerate(selected, start=1):
                source = call.get("source") or {}
                source_id = call.get("sourceId")
                bitmap_event = event_by_id.get(source_id)
                native_png = decode_base64(call.get("nativePng"))
                result: dict[str, Any] = {
                    "index": index,
                    "source_id": source_id,
                    "source": source,
                    "source_rect": call.get("sourceRect"),
                    "destination": call.get("destination"),
                    "native_png": await save_capture(output_dir, f"target-{index}-native", native_png) if native_png else None,
                    "candidate": None,
                    "case": "Case 4",
                }
                if bitmap_event:
                    raw = decode_base64(bitmap_event.get("base64"))
                    if raw:
                        details = inspect_bytes(raw)
                        if details["format"] in STANDARD_FORMATS:
                            suffix = {"jpeg": "jpg"}.get(details["format"], details["format"])
                            path = output_dir / f"target-{index}-original.{suffix}"
                            path.write_bytes(raw)
                            result["candidate"] = {"origin": "createImageBitmap input Blob/bytes", "path": str(path), **details}
                            result["case"] = "Case 2"
                        else:
                            result["candidate"] = {"origin": "createImageBitmap input bytes", **details}
                            result["case"] = "Case 3"
                    elif bitmap_event.get("input", {}).get("constructor") in {"Blob", "ArrayBuffer", "Uint8Array"}:
                        result["candidate"] = {
                            "origin": "createImageBitmap input",
                            "input": bitmap_event.get("input"),
                            "captured_bytes": bitmap_event.get("byteSize"),
                            "first_bytes_hex": bitmap_event.get("firstBytesHex"),
                        }
                        result["case"] = "Case 3"
                if result["candidate"] is None and result["native_png"] is not None:
                    result["case"] = "Case 3" if bitmap_event else "Case 4"
                if result["native_png"] and result["candidate"] and result["candidate"].get("bytes"):
                    result["candidate"]["ratio_to_native_png"] = round(
                        result["candidate"]["bytes"] / result["native_png"]["bytes"], 6
                    )
                candidate_results.append(result)

            response_records = await asyncio.gather(*response_tasks)
            if cdp_tasks:
                await asyncio.gather(*cdp_tasks)
            all_network_records = response_records + cdp_records + route_records
            standard_responses = [record for record in all_network_records if record.get("format") in STANDARD_FORMATS]
            source_dimensions = {
                (source.get("width"), source.get("height"))
                for source in (call.get("source") or {} for call in selected)
                if source.get("width") and source.get("height")
            }
            direct_candidates = [
                record for record in all_network_records
                if record.get("format") in STANDARD_FORMATS
                and record.get("artifact")
                and (record.get("width"), record.get("height")) in source_dimensions
            ]
            if direct_candidates:
                for result in candidate_results:
                    source = result.get("source") or {}
                    matching = [
                        record for record in direct_candidates
                        if (record.get("width"), record.get("height"))
                        == (source.get("width"), source.get("height"))
                    ]
                    native_path = (result.get("native_png") or {}).get("path")
                    scored: list[tuple[dict[str, float | int | None], dict[str, Any]]] = []
                    for record in matching:
                        comparison = compare_image_files(native_path, record.get("artifact"))
                        if not comparison.get("available"):
                            comparison = await compare_image_files_in_page(
                                page, native_path, record.get("artifact")
                            )
                        scored.append((comparison, record))
                    scored.sort(
                        key=lambda item: (
                            item[0].get("rms_difference")
                            if item[0].get("rms_difference") is not None
                            else float("inf")
                        )
                    )
                    record = scored[0][1] if scored else None
                    if record:
                        comparison = scored[0][0]
                        result["candidate"] = {
                            "origin": "Network response via Playwright route fetch",
                            "path": record.get("artifact"),
                            "url": record.get("url"),
                            "format": record.get("format"),
                            "width": record.get("width"),
                            "height": record.get("height"),
                            "bytes": record.get("bytes"),
                            "sha256": record.get("sha256"),
                            "pixel_comparison_to_native_png": comparison,
                        }
                        result["case"] = "Case 1"
                        if result.get("native_png") and record.get("bytes"):
                            result["candidate"]["ratio_to_native_png"] = round(
                                record["bytes"] / result["native_png"]["bytes"], 6
                            )
            return {
                "url": redact_url(page.url),
                "input_url": redact_url(url),
                "page_counter": (await page.locator("#pageSliderCounter").inner_text()) if await page.locator("#pageSliderCounter").count() else None,
                "advance_pages": advance_pages,
                "browser": await page.evaluate("() => ({userAgent: navigator.userAgent, devicePixelRatio: devicePixelRatio, innerWidth, innerHeight})"),
                "canvas": canvas_info,
                "source_imagebitmaps": [call.get("source") for call in selected],
                "draw_calls": [{key: value for key, value in call.items() if key != "nativePng"} for call in selected],
                "targets": target_results,
                "candidates": candidate_results,
                "network": {
                    "response_count": len(all_network_records),
                    "standard_image_response_count": len(standard_responses),
                    "responses": all_network_records,
                    "cdp_response_count": len(cdp_records),
                },
                "hooks": events,
                "production_capture_unchanged": True,
            }
        finally:
            page.remove_listener("response", on_response)
            try:
                await cdp.detach()
            except Exception:  # noqa: BLE001
                cdp = None
            await page.close()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--advance-pages", type=int, default=0)
    args = parser.parse_args()
    result = await measure(args.endpoint, args.output_dir, args.url, args.advance_pages)
    result["label"] = args.label
    (args.output_dir / "metadata.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
