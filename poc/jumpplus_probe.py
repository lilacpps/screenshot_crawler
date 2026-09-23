r"""Read-only J0 probe for the Shonen Jump+ episode viewer.

This is intentionally a PoC, not a Site Adapter.  It attaches to the shared
Crawler Chrome over CDP, records viewer/network/rendering observations, and
performs only bounded, explicitly identified page navigation.  It never
clicks purchase/access controls and stops if the target episode URL changes.

Example::

    .\.venv\Scripts\python.exe poc\jumpplus_probe.py `
        --url https://shonenjumpplus.com/episode/13932016480029111789 `
        --output-dir output\jumpplus_probe --steps 3
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from PIL import Image

from screenshot_crawler.core.browser import BrowserSession, resolve_cdp_endpoint

DEFAULT_URL = "https://shonenjumpplus.com/episode/13932016480029111789"
DEFAULT_OUTPUT_DIR = Path("output/jumpplus_probe")
ALLOWED_HOSTS = frozenset({"shonenjumpplus.com", "www.shonenjumpplus.com"})
MAX_STEPS = 5
MAX_IMAGE_RESPONSES = 20
MAX_DRAW_CALLS = 3_000

_EPISODE_PATH = re.compile(r"^/episode/(?P<episode_id>[0-9]+)/?$")
_EPISODE_LINK = re.compile(r"/episode/[0-9]+(?:[/?#]|$)")
_SKIP_IMAGE = re.compile(
    r"(?:favicon|apple-touch|(?:^|[/_-])icon(?:[/_.?-]|$)|(?:^|[/_-])ic_[^/]*|logo|avatar|thumb(?:nail)?|sprite|badge|banner|close-button|bg_dots|notice_keytop|zebrack|amazon|ebookjapan|jasrac|nex-tone|jumpplus_white|hatena)",
    re.IGNORECASE,
)
_ACCESS_TERMS = re.compile(r"(?:無料|ポイント|購入|レンタル|期間限定無料)")


def extract_episode_id(url: str) -> str | None:
    """Return an episode id only for a Jump+ episode URL."""

    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        return None
    match = _EPISODE_PATH.fullmatch(parsed.path)
    return match.group("episode_id") if match else None


def is_target_episode_url(url: str, expected_episode_id: str) -> bool:
    """Check both host and exact episode path for the safety stop."""

    return extract_episode_id(url) == expected_episode_id


def classify_resource(resource_type: str, content_type: str | None, url: str) -> str:
    """Classify a network record without relying on site-specific names."""

    normalized_type = (resource_type or "").lower()
    normalized_content_type = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized_content_type.startswith("image/") or normalized_type == "image":
        return "image"
    if normalized_content_type in {"application/json", "text/json"} or "json" in normalized_content_type:
        return "json"
    if normalized_type in {"xhr", "fetch"}:
        return "fetch/xhr"
    if normalized_type == "script" or "javascript" in normalized_content_type:
        return "script"
    if normalized_type == "document":
        return "document"
    if normalized_content_type == "text/html":
        return "document"
    if url.lower().endswith((".js", ".mjs")):
        return "script"
    return normalized_type or "other"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )


def _write_text(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8")


def _header(headers: dict[str, str], name: str) -> str | None:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return None


def _image_candidate_url(url: str) -> bool:
    parsed = urlparse(url)
    path = f"{parsed.path} {parsed.query}"
    if _SKIP_IMAGE.search(path):
        return False
    # The viewer's page endpoint is the only image family that is a strong
    # body-image candidate in this J0.  Other image responses remain listed
    # in network.json but are not copied as original-byte artifacts.
    return "/public/page/" in parsed.path


def _image_extension(content_type: str | None, image_format: str | None) -> str:
    by_format = {
        "JPEG": "jpg",
        "PNG": "png",
        "WEBP": "webp",
        "GIF": "gif",
        "AVIF": "avif",
        "BMP": "bmp",
        "TIFF": "tiff",
    }
    if image_format:
        return by_format.get(image_format.upper(), image_format.lower())
    subtype = (content_type or "").split("/", 1)[-1].split(";", 1)[0]
    return {"jpeg": "jpg", "svg+xml": "svg"}.get(subtype, subtype or "bin")


_DRAW_HOOK = r"""
(() => {
  if (window.__jumpplusProbe) return;
  const maxRecords = 3000;
  const state = {
    installed: false,
    drawCalls: [],
    rendererEvents: [],
    canvasIds: new WeakMap(),
    nextCanvasId: 1,
  };

  const shortSelector = (element) => {
    if (!element || !element.tagName) return null;
    if (element.id) return `#${CSS.escape(element.id)}`;
    const classes = Array.from(element.classList || []).slice(0, 2)
      .map((name) => CSS.escape(name)).join(".");
    return element.tagName.toLowerCase() + (classes ? `.${classes}` : "");
  };
  const canvasInfo = (canvas) => {
    if (!canvas) return {id: null, selector: null, width: null, height: null};
    let id = state.canvasIds.get(canvas);
    if (!id) {
      id = state.nextCanvasId++;
      state.canvasIds.set(canvas, id);
    }
    return {
      id,
      selector: shortSelector(canvas),
      width: Number(canvas.width) || 0,
      height: Number(canvas.height) || 0,
    };
  };
  const sourceInfo = (source) => {
    let sourceType = "Other";
    try {
      if (typeof HTMLImageElement !== "undefined" && source instanceof HTMLImageElement) {
        sourceType = "HTMLImageElement";
      } else if (typeof ImageBitmap !== "undefined" && source instanceof ImageBitmap) {
        sourceType = "ImageBitmap";
      } else if (typeof HTMLCanvasElement !== "undefined" && source instanceof HTMLCanvasElement) {
        sourceType = "HTMLCanvasElement";
      } else if (typeof HTMLVideoElement !== "undefined" && source instanceof HTMLVideoElement) {
        sourceType = "HTMLVideoElement";
      } else if (typeof OffscreenCanvas !== "undefined" && source instanceof OffscreenCanvas) {
        sourceType = "OffscreenCanvas";
      }
    } catch (_) {}
    const url = sourceType === "HTMLImageElement"
      ? (source.currentSrc || source.src || null) : null;
    return {
      type: sourceType,
      url,
      selector: shortSelector(source),
      naturalWidth: Number(source.naturalWidth) || null,
      naturalHeight: Number(source.naturalHeight) || null,
      width: Number(source.width) || null,
      height: Number(source.height) || null,
      videoWidth: Number(source.videoWidth) || null,
      videoHeight: Number(source.videoHeight) || null,
    };
  };
  const trim = (items) => {
    if (items.length > maxRecords) items.splice(0, items.length - maxRecords);
  };
  const originalDrawImage = typeof CanvasRenderingContext2D !== "undefined"
    ? CanvasRenderingContext2D.prototype.drawImage : null;
  if (originalDrawImage) {
    CanvasRenderingContext2D.prototype.drawImage = function(...args) {
      try {
        const source = args[0];
        const sourceWidth = Number(source?.naturalWidth || source?.videoWidth || source?.width) || null;
        const sourceHeight = Number(source?.naturalHeight || source?.videoHeight || source?.height) || null;
        let form = "unknown";
        let sourceRect = null;
        let destinationRect = null;
        if (args.length === 3) {
          form = "3-argument";
          destinationRect = {dx: Number(args[1]), dy: Number(args[2]), dw: sourceWidth, dh: sourceHeight};
        } else if (args.length === 5) {
          form = "5-argument";
          destinationRect = {dx: Number(args[1]), dy: Number(args[2]), dw: Number(args[3]), dh: Number(args[4])};
        } else if (args.length === 9) {
          form = "9-argument";
          sourceRect = {sx: Number(args[1]), sy: Number(args[2]), sw: Number(args[3]), sh: Number(args[4])};
          destinationRect = {dx: Number(args[5]), dy: Number(args[6]), dw: Number(args[7]), dh: Number(args[8])};
        }
        let transform = null;
        try {
          const matrix = this.getTransform();
          transform = {a: matrix.a, b: matrix.b, c: matrix.c, d: matrix.d, e: matrix.e, f: matrix.f};
        } catch (_) {}
        state.drawCalls.push({
          timestamp: Date.now(),
          monotonicMs: performance.now(),
          canvas: canvasInfo(this.canvas),
          source: sourceInfo(source),
          argumentForm: form,
          sourceRect,
          destinationRect,
          transform,
          globalCompositeOperation: this.globalCompositeOperation,
          filter: this.filter,
          globalAlpha: this.globalAlpha,
        });
        trim(state.drawCalls);
      } catch (_) {}
      return originalDrawImage.apply(this, args);
    };
  }
  if (typeof window.createImageBitmap === "function") {
    const originalCreateImageBitmap = window.createImageBitmap.bind(window);
    window.createImageBitmap = function(...args) {
      try {
        const source = args[0];
        state.rendererEvents.push({
          kind: "createImageBitmap",
          timestamp: Date.now(),
          sourceType: source?.constructor?.name || typeof source,
          sourceUrl: source?.currentSrc || source?.src || null,
          sourceWidth: Number(source?.naturalWidth || source?.width) || null,
          sourceHeight: Number(source?.naturalHeight || source?.height) || null,
        });
        trim(state.rendererEvents);
      } catch (_) {}
      return originalCreateImageBitmap(...args);
    };
  }
  state.installed = true;
  window.__jumpplusProbe = {
    take: () => {
      const result = {
        installed: state.installed,
        drawCalls: state.drawCalls.splice(0),
        rendererEvents: state.rendererEvents.splice(0),
        offscreenCanvasAvailable: typeof OffscreenCanvas !== "undefined",
        createImageBitmapAvailable: typeof window.createImageBitmap === "function",
      };
      return result;
    },
  };
})();
"""


_COLLECT_PAGE_SCRIPT = r"""
() => {
  const visible = (element) => {
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      Number(style.opacity) !== 0 && rect.width > 0 && rect.height > 0;
  };
  const box = (element) => {
    const rect = element.getBoundingClientRect();
    return {x: rect.x, y: rect.y, width: rect.width, height: rect.height};
  };
  const selector = (element) => {
    if (element.id) return `#${CSS.escape(element.id)}`;
    const parts = [];
    let current = element;
    while (current && current.nodeType === 1 && parts.length < 5) {
      let part = current.tagName.toLowerCase();
      if (current.classList.length) {
        part += "." + Array.from(current.classList).slice(0, 2)
          .map((name) => CSS.escape(name)).join(".");
      }
      const parent = current.parentElement;
      if (parent) {
        const siblings = Array.from(parent.children)
          .filter((candidate) => candidate.tagName === current.tagName);
        if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(current) + 1})`;
      }
      parts.unshift(part);
      current = parent;
    }
    return parts.join(" > ");
  };
  const text = (element) => (element.innerText || element.textContent || "").trim().replace(/\s+/g, " ").slice(0, 500);
  const attrs = (element) => {
    const result = {};
    for (const attribute of Array.from(element.attributes || [])) {
      if (attribute.name.startsWith("data-") || ["id", "class", "aria-label", "title", "role", "alt"].includes(attribute.name)) {
        result[attribute.name] = attribute.value.slice(0, 500);
      }
    }
    return result;
  };
  const visibleElements = (selectorText) => Array.from(document.querySelectorAll(selectorText)).filter(visible);
  const imageData = visibleElements("img").slice(0, 300).map((element) => ({
    src: element.src || null,
    currentSrc: element.currentSrc || null,
    naturalWidth: element.naturalWidth,
    naturalHeight: element.naturalHeight,
    renderedRect: box(element),
    selector: selector(element),
    alt: (element.alt || "").slice(0, 300),
    attributes: attrs(element),
  }));
  const canvasData = visibleElements("canvas").slice(0, 100).map((element) => {
    const contexts = {};
    for (const name of ["2d", "webgl", "webgl2"]) {
      try { contexts[name] = Boolean(element.getContext(name)); } catch (_) { contexts[name] = false; }
    }
    return {width: element.width, height: element.height, renderedRect: box(element), selector: selector(element), contexts, attributes: attrs(element)};
  });
  const buttons = visibleElements("button, [role='button'], a, [onclick], input[type='button'], input[type='submit']")
    .slice(0, 500).map((element) => ({
      text: text(element),
      ariaLabel: element.getAttribute("aria-label"),
      title: element.getAttribute("title"),
      role: element.getAttribute("role") || element.tagName.toLowerCase(),
      href: element.href || null,
      renderedRect: box(element),
      selector: selector(element),
      attributes: attrs(element),
    }));
  const backgrounds = visibleElements("*").slice(0, 2_000).map((element) => {
    const image = getComputedStyle(element).backgroundImage;
    return {element, image};
  }).filter(({image}) => image && image !== "none").slice(0, 300).map(({element, image}) => ({
    backgroundImage: image, renderedRect: box(element), selector: selector(element), attributes: attrs(element),
  }));
  const svgs = visibleElements("svg").slice(0, 200).map((element) => ({
    renderedRect: box(element), selector: selector(element), viewBox: element.getAttribute("viewBox"), attributes: attrs(element),
  }));
  const iframes = Array.from(document.querySelectorAll("iframe")).slice(0, 100).map((element) => ({
    src: element.src || null, title: element.title || null, renderedRect: box(element), selector: selector(element), visible: visible(element), attributes: attrs(element),
  }));
  const viewerish = visibleElements("[id], [class]").filter((element) => /viewer|reader|manga|comic|page|episode|chapter|content/i.test(`${element.id} ${element.className}`)).slice(0, 300).map((element) => ({
    tag: element.tagName.toLowerCase(), id: element.id || null, className: String(element.className || "").slice(0, 500), text: text(element), renderedRect: box(element), selector: selector(element), attributes: attrs(element),
  }));
  const dataAttributes = visibleElements("[data-episode-id], [data-episode], [data-chapter-id], [data-work-id], [data-series-id], [data-content-id], [data-page-id]")
    .slice(0, 500).map((element) => ({selector: selector(element), attributes: attrs(element), text: text(element)}));
  const identityCandidates = [];
  const addIdentity = (source, key, value) => {
    if (value !== null && value !== undefined && String(value).trim()) identityCandidates.push({source, key, value: String(value).trim().slice(0, 500)});
  };
  for (const element of Array.from(document.querySelectorAll("meta"))) {
    const key = element.getAttribute("name") || element.getAttribute("property") || "meta";
    if (/episode|chapter|work|series|title|作品|話/i.test(key)) addIdentity("meta", key, element.getAttribute("content"));
  }
  for (const element of Array.from(document.querySelectorAll("[data-episode-id], [data-episode], [data-chapter-id], [data-work-id], [data-series-id], [data-content-id], [data-page-id]"))) {
    for (const attribute of Array.from(element.attributes)) addIdentity("data", attribute.name, attribute.value);
  }
  for (const element of Array.from(document.querySelectorAll("h1, h2, [class*='title'], [class*='episode'], [class*='chapter']")).slice(0, 100)) {
    addIdentity("visible-dom", selector(element), text(element));
  }
  const scripts = Array.from(document.scripts).slice(0, 500).map((element, index) => ({
    index, src: element.src || null, type: element.type || null, id: element.id || null,
    async: element.async, defer: element.defer, textLength: (element.textContent || "").length,
    inlinePreview: element.src ? null : (element.textContent || "").slice(0, 1200),
  }));
  const links = Array.from(document.querySelectorAll("a[href]")).slice(0, 2_000).map((element) => ({
    href: element.href, text: text(element), surroundingText: text(element.parentElement || element),
    className: String(element.className || "").slice(0, 500), attributes: attrs(element), selector: selector(element),
  }));
  return {
    url: location.href, title: document.title, viewport: {width: innerWidth, height: innerHeight},
    devicePixelRatio, visibleText: (document.body?.innerText || "").trim().slice(0, 20_000),
    visibleImages: imageData, canvases: canvasData, backgrounds, svgs, iframes, viewerish,
    buttons, dataAttributes, identityCandidates, scripts, links,
  };
}
"""


_STABILITY_SCRIPT = r"""
() => JSON.stringify({
  url: location.href,
  title: document.title,
  images: Array.from(document.images).filter((image) => image.getBoundingClientRect().width > 0).map((image) => image.currentSrc || image.src).slice(0, 20),
  canvases: Array.from(document.querySelectorAll("canvas")).filter((canvas) => canvas.getBoundingClientRect().width > 0).map((canvas) => [canvas.width, canvas.height]).slice(0, 20),
  text: (document.body?.innerText || "").slice(0, 2_000),
})
"""


_NAVIGATION_CANDIDATES_SCRIPT = r"""
() => {
  const visible = (element) => {
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
  };
  const selector = (element) => {
    if (element.id) return `#${CSS.escape(element.id)}`;
    const parts = [];
    let current = element;
    while (current && current.nodeType === 1 && parts.length < 5) {
      let part = current.tagName.toLowerCase();
      if (current.classList.length) part += "." + Array.from(current.classList).slice(0, 2).map((name) => CSS.escape(name)).join(".");
      const parent = current.parentElement;
      if (parent) {
        const siblings = Array.from(parent.children).filter((candidate) => candidate.tagName === current.tagName);
        if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(current) + 1})`;
      }
      parts.unshift(part); current = parent;
    }
    return parts.join(" > ");
  };
  const elements = Array.from(document.querySelectorAll("button, [role='button'], a, [onclick], input[type='button'], input[type='submit']"));
  return elements.filter(visible).map((element) => ({
    text: (element.innerText || element.value || element.getAttribute("aria-label") || element.getAttribute("title") || "").trim().replace(/\s+/g, " ").slice(0, 300),
    ariaLabel: element.getAttribute("aria-label"), title: element.getAttribute("title"),
    className: String(element.className || "").slice(0, 500), href: element.href || null,
    selector: selector(element),
  }));
}
"""


@dataclass(slots=True)
class ProbeObservation:
    state: str
    url: str
    dom: dict[str, Any]
    network: dict[str, Any]
    draw: dict[str, Any]
    directory: str


@dataclass
class JumpPlusProbe:
    page: Any
    output_dir: Path
    expected_episode_id: str
    max_image_responses: int = MAX_IMAGE_RESPONSES
    network_events: list[dict[str, Any]] = field(default_factory=list)
    image_tasks: set[asyncio.Task[Any]] = field(default_factory=set)
    image_attempted_urls: set[str] = field(default_factory=set)
    saved_images: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    observations: list[ProbeObservation] = field(default_factory=list)
    navigation: list[dict[str, Any]] = field(default_factory=list)
    stopped_reason: str | None = None
    _network_cursor: int = 0

    def install_listeners(self) -> None:
        self.page.on("request", self._on_request)
        self.page.on("response", self._on_response)

    def _on_request(self, request: Any) -> None:
        try:
            url = request.url
            self.network_events.append(
                {
                    "event": "request",
                    "timestamp": _now_iso(),
                    "url": url,
                    "method": request.method,
                    "resource_type": request.resource_type,
                    "classification": classify_resource(request.resource_type, None, url),
                    "host": urlparse(url).netloc,
                }
            )
        except BaseException as exc:  # noqa: BLE001
            self.errors.append(f"request observation failed: {type(exc).__name__}: {exc}")

    def _on_response(self, response: Any) -> None:
        try:
            url = response.url
            headers = dict(response.headers)
            content_type = _header(headers, "content-type")
            resource_type = response.request.resource_type
            record: dict[str, Any] = {
                "event": "response",
                "timestamp": _now_iso(),
                "url": url,
                "method": response.request.method,
                "resource_type": resource_type,
                "classification": classify_resource(resource_type, content_type, url),
                "status": response.status,
                "content_type": content_type,
                "content_length": _header(headers, "content-length"),
                "host": urlparse(url).netloc,
                "body": {"attempted": False, "saved": False},
            }
            self.network_events.append(record)
            if (
                response.status == 200
                and record["classification"] == "image"
                and _image_candidate_url(url)
                and url not in self.image_attempted_urls
                and len(self.image_attempted_urls) < self.max_image_responses
            ):
                self.image_attempted_urls.add(url)
                task = asyncio.create_task(self._save_image_response(response, record))
                self.image_tasks.add(task)
                task.add_done_callback(self.image_tasks.discard)
        except BaseException as exc:  # noqa: BLE001
            self.errors.append(f"response observation failed: {type(exc).__name__}: {exc}")

    async def _save_image_response(self, response: Any, record: dict[str, Any]) -> None:
        body_info = record["body"]
        body_info["attempted"] = True
        try:
            body = await asyncio.wait_for(response.body(), timeout=10)
        except BaseException as exc:  # noqa: BLE001
            body_info["error"] = f"{type(exc).__name__}: {exc}"
            return
        body_info["byte_length"] = len(body)
        try:
            with Image.open(io.BytesIO(body)) as image:
                image_format = image.format
                dimensions = [image.width, image.height]
        except BaseException as exc:  # noqa: BLE001
            body_info["decode_error"] = f"{type(exc).__name__}: {exc}"
            body_info["image_format"] = None
            return
        body_info.update({"saved": True, "image_format": image_format, "dimensions": dimensions})
        if len(self.saved_images) >= self.max_image_responses:
            body_info["saved"] = False
            body_info["save_skip"] = "max_image_responses"
            return
        extension = _image_extension(record.get("content_type"), image_format)
        digest = hashlib.sha256(record["url"].encode("utf-8")).hexdigest()[:12]
        image_dir = self.output_dir / "network_images"
        image_dir.mkdir(parents=True, exist_ok=True)
        path = image_dir / f"image_{len(self.saved_images):03d}_{digest}.{extension}"
        try:
            path.write_bytes(body)
        except BaseException as exc:  # noqa: BLE001
            body_info["saved"] = False
            body_info["write_error"] = f"{type(exc).__name__}: {exc}"
            return
        item = {
            "url": record["url"],
            "host": record["host"],
            "content_type": record.get("content_type"),
            "byte_length": len(body),
            "image_format": image_format,
            "dimensions": dimensions,
            "file": str(path.relative_to(self.output_dir)),
        }
        self.saved_images.append(item)
        body_info["file"] = item["file"]

    async def drain_image_tasks(self) -> None:
        if not self.image_tasks:
            return
        tasks = tuple(self.image_tasks)
        done, pending = await asyncio.wait(tasks, timeout=12)
        for task in done:
            try:
                task.result()
            except BaseException as exc:  # noqa: BLE001
                self.errors.append(f"image response task failed: {type(exc).__name__}: {exc}")
        for task in pending:
            task.cancel()

    async def wait_for_stability(self, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        previous: str | None = None
        same_count = 0
        while time.monotonic() < deadline:
            try:
                fingerprint = await self.page.evaluate(_STABILITY_SCRIPT)
            except BaseException as exc:  # noqa: BLE001
                self.errors.append(f"stability observation failed: {type(exc).__name__}: {exc}")
                return False
            if fingerprint == previous:
                same_count += 1
                if same_count >= 2:
                    return True
            else:
                previous = fingerprint
                same_count = 0
            await asyncio.sleep(0.4)
        return False

    async def _take_renderer_events(self) -> dict[str, Any]:
        try:
            return await self.page.evaluate(
                """() => window.__jumpplusProbe ? window.__jumpplusProbe.take() : {
                    installed: false, drawCalls: [], rendererEvents: [],
                    offscreenCanvasAvailable: null, createImageBitmapAvailable: null
                }"""
            )
        except BaseException as exc:  # noqa: BLE001
            self.errors.append(f"draw call collection failed: {type(exc).__name__}: {exc}")
            return {"installed": False, "drawCalls": [], "rendererEvents": [], "error": str(exc)}

    async def collect_snapshot(self, directory_name: str, *, include_html: bool) -> ProbeObservation:
        await self.drain_image_tasks()
        try:
            dom = await self.page.evaluate(_COLLECT_PAGE_SCRIPT)
        except BaseException as exc:  # noqa: BLE001
            self.errors.append(f"DOM collection failed: {type(exc).__name__}: {exc}")
            dom = {
                "url": self.page.url,
                "title": "",
                "viewport": {},
                "devicePixelRatio": None,
                "visibleText": "",
                "visibleImages": [],
                "canvases": [],
                "backgrounds": [],
                "svgs": [],
                "iframes": [],
                "viewerish": [],
                "buttons": [],
                "dataAttributes": [],
                "identityCandidates": [],
                "scripts": [],
                "links": [],
            }
        renderer = await self._take_renderer_events()
        network_delta = self.network_events[self._network_cursor :]
        self._network_cursor = len(self.network_events)
        directory = self.output_dir / directory_name
        directory.mkdir(parents=True, exist_ok=True)
        url = str(dom.get("url") or self.page.url)
        network = {
            "captured_at": _now_iso(),
            "url": url,
            "events": network_delta,
            "image_responses_saved_so_far": list(self.saved_images),
            "body_read_errors": [
                event for event in network_delta if event.get("event") == "response" and event.get("body", {}).get("error")
            ],
        }
        _write_json(directory / "dom.json", dom)
        _write_json(directory / "network.json", network)
        _write_json(directory / "draw_calls.json", renderer)
        _write_json(directory / "scripts.json", dom.get("scripts", []))
        links = list(dom.get("links", []))
        episode_links = [link for link in links if _EPISODE_LINK.search(str(link.get("href") or ""))]
        _write_json(
            directory / "links.json",
            {
                "url": url,
                "episode_links": episode_links,
                "episode_link_count": len(episode_links),
                "other_links_sample": [link for link in links if link not in episode_links][:100],
            },
        )
        if include_html:
            try:
                _write_text(directory / "page.html", await self.page.content())
            except BaseException as exc:  # noqa: BLE001
                self.errors.append(f"HTML collection failed: {type(exc).__name__}: {exc}")
        try:
            await self.page.screenshot(path=str(directory / "screenshot.png"), full_page=False)
        except BaseException as exc:  # noqa: BLE001
            self.errors.append(f"Screenshot failed: {type(exc).__name__}: {exc}")
        observation = ProbeObservation(
            state=directory_name,
            url=url,
            dom=dom,
            network=network,
            draw=renderer,
            directory=str(directory),
        )
        self.observations.append(observation)
        return observation

    async def capture_initial(self) -> None:
        initial = await self.collect_snapshot("initial", include_html=True)
        # state_000 is the first state as well as the initial baseline.  Copy
        # the already collected values without taking the renderer events twice.
        state_dir = self.output_dir / "state_000"
        state_dir.mkdir(parents=True, exist_ok=True)
        for name in ("dom.json", "network.json", "draw_calls.json", "scripts.json", "links.json", "page.html", "screenshot.png"):
            source = self.output_dir / "initial" / name
            if source.exists():
                target = state_dir / name
                if source.suffix == ".json" or source.suffix == ".html":
                    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
                else:
                    target.write_bytes(source.read_bytes())
        self.observations.append(
            ProbeObservation(
                state="state_000",
                url=initial.url,
                dom=initial.dom,
                network=initial.network,
                draw=initial.draw,
                directory=str(state_dir),
            )
        )

    async def choose_navigation(self) -> dict[str, Any] | None:
        try:
            candidates = await self.page.evaluate(_NAVIGATION_CANDIDATES_SCRIPT)
        except BaseException as exc:  # noqa: BLE001
            self.errors.append(f"navigation candidate collection failed: {type(exc).__name__}: {exc}")
            return None
        ranked: list[tuple[int, dict[str, Any]]] = []
        for candidate in candidates:
            label = " ".join(
                str(candidate.get(key) or "") for key in ("text", "ariaLabel", "title", "className")
            ).lower()
            href = str(candidate.get("href") or "")
            if href and not is_target_episode_url(href, self.expected_episode_id):
                continue
            if any(term in label for term in ("購入", "ポイント", "レンタル", "ログイン", "次話", "次の話", "next episode", "episode")):
                continue
            if re.search(
                r"次\s*(の)?\s*ページ|次ページ|ページ送り|next\s*(page)?|arrow.?right|chevron.?right|forward|slide-forward|page-navigation-forward",
                label,
            ):
                ranked.append((0, candidate))
            elif re.search(r"次|進む|right", label):
                ranked.append((1, candidate))
        if not ranked:
            return None
        ranked.sort(key=lambda item: item[0])
        return ranked[0][1]

    async def advance_once(self, step: int) -> bool:
        if not is_target_episode_url(self.page.url, self.expected_episode_id):
            self.stopped_reason = "target episode URL changed before navigation"
            return False
        candidate = await self.choose_navigation()
        if candidate is None:
            self.navigation.append({"step": step, "status": "not_observed", "method": None})
            return False
        before_url = self.page.url
        try:
            locator = self.page.locator(str(candidate["selector"])).first
            await locator.click(timeout=5_000, no_wait_after=True)
            stable = await self.wait_for_stability(timeout=10.0)
        except BaseException as exc:  # noqa: BLE001
            self.navigation.append(
                {"step": step, "status": "failed", "method": "dom_click", "candidate": candidate, "error": f"{type(exc).__name__}: {exc}"}
            )
            return False
        after_url = self.page.url
        record = {
            "step": step,
            "status": "changed" if stable else "clicked_but_not_stable",
            "method": "dom_click",
            "candidate": candidate,
            "before_url": before_url,
            "after_url": after_url,
            "stable": stable,
        }
        self.navigation.append(record)
        if not is_target_episode_url(after_url, self.expected_episode_id):
            self.stopped_reason = "target episode URL changed after navigation"
            return False
        return stable

    async def run(self, url: str, steps: int) -> dict[str, Any]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.install_listeners()
        await self.page.add_init_script(script=_DRAW_HOOK)
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        except BaseException as exc:  # noqa: BLE001
            self.errors.append(f"page.goto failed: {type(exc).__name__}: {exc}")
        await self.wait_for_stability(timeout=12.0)
        if not is_target_episode_url(self.page.url, self.expected_episode_id):
            self.stopped_reason = "target episode URL changed during initial navigation"
        await self.capture_initial()
        if self.stopped_reason:
            return self.as_report(url, steps)
        for step in range(1, steps + 1):
            if not await self.advance_once(step):
                break
            await self.collect_snapshot(f"state_{step:03d}", include_html=False)
        await self.drain_image_tasks()
        return self.as_report(url, steps)

    def as_report(self, target_url: str, steps: int) -> dict[str, Any]:
        return {
            "target_url": target_url,
            "target_episode_id": self.expected_episode_id,
            "final_url": self.page.url,
            "steps_requested": steps,
            "states_observed": len(self.observations),
            "navigation": self.navigation,
            "saved_network_images": self.saved_images,
            "stopped_reason": self.stopped_reason,
            "errors": self.errors,
        }

    def write_report(self, report: dict[str, Any]) -> None:
        _write_json(self.output_dir / "report.json", report)
        _write_text(self.output_dir / "summary.md", self.make_summary(report))

    def make_summary(self, report: dict[str, Any]) -> str:
        first = next((item for item in self.observations if item.state == "initial"), None)
        dom = first.dom if first else {}
        images = dom.get("visibleImages", [])
        canvases = dom.get("canvases", [])
        draw_calls = [call for item in self.observations for call in item.draw.get("drawCalls", [])]
        renderer_events = [event for item in self.observations for event in item.draw.get("rendererEvents", [])]
        formats = sorted({str(item.get("image_format")) for item in self.saved_images if item.get("image_format")})
        dimensions = sorted({tuple(item.get("dimensions", [])) for item in self.saved_images if item.get("dimensions")})
        image_hosts = sorted({str(item.get("host")) for item in self.saved_images})
        access_text = " ".join(str(item.dom.get("visibleText", "")) for item in self.observations)
        access_matches = sorted(set(_ACCESS_TERMS.findall(access_text)))
        explicit_ids = []
        for item in self.observations:
            for candidate in item.dom.get("identityCandidates", []):
                if re.search(r"episode|chapter", str(candidate.get("key", "")), re.IGNORECASE):
                    explicit_ids.append(candidate)
        episode_links = []
        if first:
            initial_links = self.output_dir / "initial" / "links.json"
            if initial_links.exists():
                try:
                    episode_links = json.loads(initial_links.read_text(encoding="utf-8")).get("episode_links", [])
                except (OSError, json.JSONDecodeError):
                    episode_links = []
        original_status = "possible" if self.saved_images else "not observed"
        native_status = "possible" if draw_calls else "not observed"
        canvas_status = "confirmed" if canvases else "not observed"
        screenshot_status = "confirmed" if any((self.output_dir / item.state / "screenshot.png").exists() for item in self.observations) else "not observed"
        reconstruction = "not observed"
        if any(call.get("sourceRect") for call in draw_calls):
            reconstruction = "possible (source rectangles were observed; equivalence is not established)"
        lines = [
            "# Jump+ J0 probe summary",
            "",
            "## Target",
            "",
            f"- URL: `{report['target_url']}`",
            f"- episode ID: `{report['target_episode_id']}`",
            f"- final URL: `{report['final_url']}`",
            f"- safety stop: `{report.get('stopped_reason') or 'none'}`",
            "",
            "## Viewer",
            "",
            f"- visible img: {len(images)}; visible canvas: {len(canvases)}; SVG: {len(dom.get('svgs', []))}; iframe: {len(dom.get('iframes', []))}",
            f"- viewport/devicePixelRatio: `{dom.get('viewport')}` / `{dom.get('devicePixelRatio')}`",
            f"- drawImage calls observed: {len(draw_calls)}; createImageBitmap events: {len(renderer_events)}",
            "- single page/spread: `unknown / not established` (J0 did not infer this from geometry alone)",
            "",
            "## Network images",
            "",
            f"- saved original-response candidates: {len(self.saved_images)}",
            f"- hosts: `{', '.join(image_hosts) or 'not observed'}`",
            f"- formats: `{', '.join(formats) or 'not observed'}`",
            f"- representative dimensions: `{', '.join(f'{w}x{h}' for w, h in dimensions) or 'not observed'}`",
            "- correspondence to a visible page: `unknown / not proven`; saved bytes are diagnostic candidates only",
            "",
            "## Rendering path",
            "",
            f"- network response -> source -> visible page: `{('observed drawImage metadata' if draw_calls else 'not observed')}`",
            f"- ImageBitmap path: `{('observed' if renderer_events else 'not observed')}`",
            f"- scramble/tile/canvas reconstruction: `{reconstruction}`",
            "",
            "## Navigation",
            "",
            f"- method: `{', '.join(sorted({str(item.get('method')) for item in self.navigation if item.get('method')})) or 'not observed'}`",
            f"- page-change signal: `bounded DOM/image/canvas stability check`; state count: {report['states_observed']}",
            f"- navigation records: `{json.dumps(self.navigation, ensure_ascii=False)}`",
            "",
            "## Identity",
            "",
            f"- URL episode ID: `{extract_episode_id(report['final_url']) or 'not available'}`",
            f"- DOM/script identity candidates: {len(explicit_ids)} explicit episode/chapter candidates",
            f"- candidates: `{json.dumps(explicit_ids[:20], ensure_ascii=False)}`",
            "",
            "## Discovery clues",
            "",
            f"- `/episode/<id>` links in initial DOM: {len(episode_links)}",
            f"- episode links: `{json.dumps(episode_links[:20], ensure_ascii=False)}`",
            f"- access-related visible terms: `{', '.join(access_matches) or 'not observed'}`",
            "- free/paid classification: `not implemented; evidence only`",
            "",
            "## End detection clues",
            "",
            "- page count/current page/total page: `unknown / not observed` unless present in the saved DOM/scripts",
            "- end screen / NEXT_CONTENT: `not actively pursued in J0`",
            "",
            "## Capture candidates",
            "",
            f"1. original bytes: `{original_status}` — response bodies were saved only as bounded diagnostic candidates.",
            f"2. source-native: `{native_status}` — drawImage source geometry was recorded; safe attribution is not established.",
            f"3. rendered canvas: `{canvas_status}` — visible canvas metadata was recorded; no canvas pixels were encoded by the hook.",
            f"4. screenshot: `{screenshot_status}` — viewport screenshots were saved.",
            "",
            "## Unknowns",
            "",
            "- Exact page-to-response mapping, spread reading order, and whether transport images are scrambled remain unknown unless directly shown by the artifacts.",
            "- No purchase, point, rental, ticket, login, or next-episode operation was attempted.",
            f"- probe errors: `{json.dumps(report.get('errors', []), ensure_ascii=False)}`",
            "",
            "## Next J1 suggestion",
            "",
            "- Use the saved response bytes, draw-call geometry, and a rendered-page comparison to test whether one response is a direct page, a spread, or a transformed/tiled source. Keep the production capture decision open until that attribution is verified.",
        ]
        return "\n".join(lines) + "\n"


async def run_probe(url: str, output_dir: Path, steps: int, cdp_endpoint: str | None) -> dict[str, Any]:
    expected_episode_id = extract_episode_id(url)
    if expected_episode_id is None:
        raise ValueError("--url must be a Jump+ URL of the form /episode/<numeric-id>")
    endpoint = resolve_cdp_endpoint(cli_endpoint=cdp_endpoint)
    session = await BrowserSession.connect(endpoint)
    page = await session.new_page()
    probe = JumpPlusProbe(page=page, output_dir=output_dir, expected_episode_id=expected_episode_id)
    try:
        report = await probe.run(url, max(0, min(MAX_STEPS, steps)))
        probe.write_report(report)
        return report
    finally:
        await session.close_page(page)
        await session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only Shonen Jump+ J0 viewer probe")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--steps", type=int, default=3, help="bounded page transitions, maximum 5")
    parser.add_argument("--cdp-endpoint", default=None)
    args = parser.parse_args()
    report = asyncio.run(run_probe(args.url, args.output_dir, args.steps, args.cdp_endpoint))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
