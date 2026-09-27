r"""Read-only Zebrack Z0 viewer probe.

The probe deliberately stops at observation.  It connects to the shared
Crawler Chrome through :class:`BrowserSession`, records the viewer DOM and
network/rendering signals, and performs at most a small number of revalidated
in-chapter page advances.  It never logs in or clicks an access, purchase,
ticket, advertisement, or next-chapter control.

Example::

    .\.venv\Scripts\python.exe poc\zeblack_probe.py `
        --url https://zebrack-comic.shueisha.co.jp/title/118286/chapter/9265713/viewer `
        --output-dir output\zeblack_probe --steps 3
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from PIL import Image

from screenshot_crawler.core.browser import BrowserSession, resolve_cdp_endpoint

DEFAULT_URL = (
    "https://zebrack-comic.shueisha.co.jp/title/118286/chapter/9265713/viewer"
)
DEFAULT_OUTPUT_DIR = Path("output/zeblack_probe")
ALLOWED_HOSTS = frozenset({"zebrack-comic.shueisha.co.jp"})
MAX_STEPS = 3
MAX_IMAGE_RESPONSES = 20
MAX_DRAW_CALLS = 3_000
MAX_DOM_ITEMS = 300

_VIEWER_PATH = re.compile(
    r"^/title/(?P<title_id>[0-9]+)/chapter/(?P<chapter_id>[0-9]+)/viewer/?$"
)
_CHAPTER_LINK = re.compile(r"/title/[0-9]+/chapter/[0-9]+(?:/viewer)?(?:[/?#]|$)")
_SKIP_IMAGE = re.compile(
    r"(?:favicon|apple-touch|(?:^|[/_-])icon(?:[/_.?-]|$)|logo|avatar|thumb|"
    r"sprite|badge|banner|close|arrow|chevron|loading|placeholder|qr|social|"
    r"share|appstore|googleplay|volume_thumbnail|doubleclick|pagead|"
    r"ga-audiences|treasuredata|amazon-adsystem|\.ico)",
    re.IGNORECASE,
)
_ACCESS_TERMS = re.compile(
    r"(?:無料|毎日無料|待てば無料|ポイント|コイン|購入|レンタル|チケット|"
    r"広告|ログイン|閲覧期限|残り時間|次回無料|利用可能|利用済み|有料)",
)
_FORBIDDEN_NAV_TERMS = (
    "無料",
    "ポイント",
    "コイン",
    "購入",
    "レンタル",
    "チケット",
    "広告",
    "視聴",
    "ログイン",
    "会員",
    "有料",
    "次話",
    "次の話",
    "次チャプター",
    "次のチャプター",
    "次の章",
    "次章",
    "次巻",
    "次の作品",
    "next chapter",
    "next content",
    "next episode",
    "chapter",
    "title",
)
_PAGE_NAV_RE = re.compile(
    r"(?:次\s*(?:の)?\s*ページ|次ページ|ページ送り|ページを進む|"
    r"next\s*(?:page|spread)?|forward|slide[-_ ]?forward|page[-_ ]?navigation[-_ ]?forward|"
    r"arrow[-_ ]?right|chevron[-_ ]?right|右へ|右矢印|進む|\bright\b)",
    re.IGNORECASE,
)


def extract_viewer_identity(url: str) -> dict[str, str] | None:
    """Extract title/chapter ids only from the Zebrack viewer URL shape."""

    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if (parsed.hostname or "").lower() not in ALLOWED_HOSTS:
        return None
    match = _VIEWER_PATH.fullmatch(parsed.path)
    if not match:
        return None
    return {
        "title_id": match.group("title_id"),
        "chapter_id": match.group("chapter_id"),
    }


def is_target_viewer_url(
    url: str,
    expected_title_id: str,
    expected_chapter_id: str,
) -> bool:
    """Return false for another host/title/chapter or a non-viewer path."""

    identity = extract_viewer_identity(url)
    return identity == {
        "title_id": str(expected_title_id),
        "chapter_id": str(expected_chapter_id),
    }


def classify_url_change(
    before: str,
    after: str,
    expected_title_id: str,
    expected_chapter_id: str,
) -> str:
    """Distinguish no change, query/hash-only change, and target escape."""

    if not is_target_viewer_url(before, expected_title_id, expected_chapter_id):
        return "target_changed"
    if not is_target_viewer_url(after, expected_title_id, expected_chapter_id):
        return "target_changed"
    if before == after:
        return "unchanged"
    before_parsed = urlparse(before)
    after_parsed = urlparse(after)
    same_path = (
        before_parsed.scheme.lower(),
        before_parsed.netloc.lower(),
        before_parsed.path,
    ) == (
        after_parsed.scheme.lower(),
        after_parsed.netloc.lower(),
        after_parsed.path,
    )
    return "query_or_hash_changed" if same_path else "target_changed"


def classify_resource(resource_type: str, content_type: str | None, url: str) -> str:
    """Classify a network record using observed type/content-type only."""

    normalized_type = (resource_type or "").lower()
    normalized_content_type = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized_content_type.startswith("image/"):
        return "image"
    if normalized_content_type in {"application/json", "text/json"} or "json" in normalized_content_type:
        return "json"
    if normalized_type == "image":
        return "image"
    if normalized_type in {"xhr", "fetch"}:
        return "fetch/xhr"
    if normalized_type == "script" or "javascript" in normalized_content_type:
        return "script"
    if normalized_type == "document" or normalized_content_type == "text/html":
        return "document"
    if url.lower().endswith((".js", ".mjs")):
        return "script"
    return normalized_type or "other"


def normalize_navigation_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip().lower()


def navigation_candidate_is_forbidden(*values: Any) -> bool:
    """Reject access, account, advertisement, and next-content candidates."""

    label = " ".join(normalize_navigation_text(value) for value in values)
    return any(term.lower() in label for term in _FORBIDDEN_NAV_TERMS)


def looks_like_page_navigation(*values: Any) -> bool:
    """Recognize only explicit page-forward-looking candidate evidence."""

    label = " ".join(normalize_navigation_text(value) for value in values)
    return bool(label and _PAGE_NAV_RE.search(label))


def fingerprint_changed(before: str | None, after: str | None) -> bool:
    return bool(before and after and before != after)


def navigation_succeeded(changed: bool, stable: bool) -> bool:
    return changed is True and stable is True


def classify_draw_geometry(draw_calls: list[dict[str, Any]]) -> str:
    """Classify observed geometry without assuming a tile count/permutation."""

    if not draw_calls:
        return "unknown"
    identity = {"a": 1, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0}
    partial = False
    scaled = False
    non_identity = False
    for draw in draw_calls:
        transform = draw.get("transform") or {}
        if any(transform.get(key) != value for key, value in identity.items()):
            non_identity = True
        source = draw.get("source") or {}
        source_rect = draw.get("sourceRect") or {}
        destination = draw.get("destinationRect") or {}
        source_width = source.get("naturalWidth") or source.get("width")
        source_height = source.get("naturalHeight") or source.get("height")
        if source_rect:
            if (
                source_rect.get("sx") != 0
                or source_rect.get("sy") != 0
                or source_rect.get("sw") != source_width
                or source_rect.get("sh") != source_height
            ):
                partial = True
            if (
                source_rect.get("sw") != destination.get("dw")
                or source_rect.get("sh") != destination.get("dh")
            ):
                scaled = True
    if non_identity:
        return "unknown"
    if scaled:
        return "scaled"
    if partial:
        return "tiled" if len(draw_calls) > 1 else "cropped"
    if len(draw_calls) == 1:
        draw = draw_calls[0]
        source = draw.get("source") or {}
        source_rect = draw.get("sourceRect") or {}
        destination = draw.get("destinationRect") or {}
        canvas = draw.get("canvas") or {}
        if (
            source_rect.get("sx") == 0
            and source_rect.get("sy") == 0
            and source_rect.get("sw") == source.get("naturalWidth", source.get("width"))
            and source_rect.get("sh") == source.get("naturalHeight", source.get("height"))
            and destination.get("dx") == 0
            and destination.get("dy") == 0
            and destination.get("dw") == canvas.get("width")
            and destination.get("dh") == canvas.get("height")
        ):
            return "full_frame_copy"
    return "tiled" if len(draw_calls) > 1 else "unknown"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )


def _header(headers: dict[str, str], name: str) -> str | None:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return None


def _image_candidate_url(url: str) -> bool:
    """Exclude obvious chrome/UI assets, keeping the remaining image as candidates."""

    parsed = urlparse(url)
    return not _SKIP_IMAGE.search(f"{parsed.netloc} {parsed.path} {parsed.query}")


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
  if (window.__zeblackProbe) return;
  const maxRecords = 3000;
  const state = {
    installed: false,
    drawCalls: [],
    rendererEvents: [],
    canvasMutations: [],
    canvasIds: new WeakMap(),
    nextCanvasId: 1,
    imageIds: new WeakMap(),
    nextImageId: 1,
    nextSequence: 0,
  };
  const trim = (items) => {
    if (items.length > maxRecords) items.splice(0, items.length - maxRecords);
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
      constructor: canvas.constructor?.name || null,
    };
  };
  const sourceInfo = (source) => {
    let sourceType = "Other";
    try {
      if (typeof HTMLImageElement !== "undefined" && source instanceof HTMLImageElement) sourceType = "HTMLImageElement";
      else if (typeof ImageBitmap !== "undefined" && source instanceof ImageBitmap) sourceType = "ImageBitmap";
      else if (typeof HTMLCanvasElement !== "undefined" && source instanceof HTMLCanvasElement) sourceType = "HTMLCanvasElement";
      else if (typeof OffscreenCanvas !== "undefined" && source instanceof OffscreenCanvas) sourceType = "OffscreenCanvas";
      else if (typeof HTMLVideoElement !== "undefined" && source instanceof HTMLVideoElement) sourceType = "HTMLVideoElement";
    } catch (_) {}
    let sourceId = null;
    if (sourceType === "HTMLImageElement") {
      sourceId = state.imageIds.get(source);
      if (!sourceId) {
        sourceId = state.nextImageId++;
        state.imageIds.set(source, sourceId);
      }
    }
    return {
      sourceId,
      type: sourceType,
      url: sourceType === "HTMLImageElement" ? (source.currentSrc || source.src || null) : null,
      naturalWidth: Number(source?.naturalWidth) || null,
      naturalHeight: Number(source?.naturalHeight) || null,
      width: Number(source?.width) || null,
      height: Number(source?.height) || null,
      videoWidth: Number(source?.videoWidth) || null,
      videoHeight: Number(source?.videoHeight) || null,
    };
  };
  const sourceRectAndDestination = (source, args) => {
    const sw = Number(source?.naturalWidth || source?.videoWidth || source?.width) || null;
    const sh = Number(source?.naturalHeight || source?.videoHeight || source?.height) || null;
    if (args.length === 3) {
      return {
        argumentForm: "3-argument",
        sourceRect: {sx: 0, sy: 0, sw, sh},
        destinationRect: {dx: Number(args[1]), dy: Number(args[2]), dw: sw, dh: sh},
      };
    }
    if (args.length === 5) {
      return {
        argumentForm: "5-argument",
        sourceRect: {sx: 0, sy: 0, sw, sh},
        destinationRect: {dx: Number(args[1]), dy: Number(args[2]), dw: Number(args[3]), dh: Number(args[4])},
      };
    }
    if (args.length === 9) {
      return {
        argumentForm: "9-argument",
        sourceRect: {sx: Number(args[1]), sy: Number(args[2]), sw: Number(args[3]), sh: Number(args[4])},
        destinationRect: {dx: Number(args[5]), dy: Number(args[6]), dw: Number(args[7]), dh: Number(args[8])},
      };
    }
    return {argumentForm: "unknown", sourceRect: null, destinationRect: null};
  };
  const patchContext = (prototype, constructorName) => {
    if (!prototype || prototype.__zeblackDrawPatched) return;
    const original = prototype.drawImage;
    if (typeof original !== "function") return;
    prototype.drawImage = function(...args) {
      try {
        const source = args[0];
        const geometry = sourceRectAndDestination(source, args);
        let transform = null;
        try {
          const matrix = this.getTransform();
          transform = {a: matrix.a, b: matrix.b, c: matrix.c, d: matrix.d, e: matrix.e, f: matrix.f};
        } catch (_) {}
        state.drawCalls.push({
          sequence: state.nextSequence++, timestamp: Date.now(), monotonicMs: performance.now(),
          canvas: {...canvasInfo(this.canvas), constructor: constructorName}, source: sourceInfo(source),
          ...geometry, transform,
          globalCompositeOperation: this.globalCompositeOperation,
          filter: this.filter, globalAlpha: this.globalAlpha,
        });
        trim(state.drawCalls);
      } catch (_) {}
      return original.apply(this, args);
    };
    prototype.__zeblackDrawPatched = true;
  };
  patchContext(typeof CanvasRenderingContext2D !== "undefined" ? CanvasRenderingContext2D.prototype : null, "CanvasRenderingContext2D");
  patchContext(typeof OffscreenCanvasRenderingContext2D !== "undefined" ? OffscreenCanvasRenderingContext2D.prototype : null, "OffscreenCanvasRenderingContext2D");
  if (typeof window.createImageBitmap === "function") {
    const original = window.createImageBitmap.bind(window);
    window.createImageBitmap = function(...args) {
      try {
        const source = args[0];
        state.rendererEvents.push({
          kind: "createImageBitmap", timestamp: Date.now(),
          sourceType: source?.constructor?.name || typeof source,
          sourceUrl: source?.currentSrc || source?.src || null,
          sourceWidth: Number(source?.naturalWidth || source?.width) || null,
          sourceHeight: Number(source?.naturalHeight || source?.height) || null,
        });
        trim(state.rendererEvents);
      } catch (_) {}
      return original(...args);
    };
  }
  state.installed = true;
  window.__zeblackProbe = {
    take: () => ({
      installed: state.installed,
      drawCalls: state.drawCalls.splice(0),
      canvasMutations: state.canvasMutations.splice(0),
      rendererEvents: state.rendererEvents.splice(0),
      offscreenCanvasAvailable: typeof OffscreenCanvas !== "undefined",
      createImageBitmapAvailable: typeof window.createImageBitmap === "function",
    }),
    counters: () => ({drawCount: state.nextSequence, rendererEventCount: state.rendererEvents.length}),
    canvasInfo: (canvas) => canvasInfo(canvas),
  };
})();
"""


_COLLECT_PAGE_SCRIPT = r"""
() => {
  const visible = (element) => {
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      style.opacity !== "0" && rect.width > 0 && rect.height > 0;
  };
  const box = (element) => {
    const rect = element.getBoundingClientRect();
    return {x: rect.x, y: rect.y, width: rect.width, height: rect.height};
  };
  const inViewport = (element) => {
    const rect = element.getBoundingClientRect();
    return rect.right > 0 && rect.bottom > 0 && rect.left < innerWidth && rect.top < innerHeight;
  };
  const text = (element) => (element.innerText || element.textContent || "")
    .trim().replace(/\s+/g, " ").slice(0, 500);
  const attrs = (element) => {
    const result = {};
    for (const attribute of Array.from(element.attributes || [])) {
      if (attribute.name.startsWith("data-") || ["id", "class", "aria-label", "title", "role", "alt", "href", "disabled"].includes(attribute.name)) {
        result[attribute.name] = attribute.value.slice(0, 500);
      }
    }
    return result;
  };
  const selector = (element) => {
    if (element.id) return `#${CSS.escape(element.id)}`;
    const parts = [];
    let current = element;
    while (current && current.nodeType === 1 && parts.length < 5) {
      let part = current.tagName.toLowerCase();
      if (current.classList.length) part += "." + Array.from(current.classList).slice(0, 2)
        .map((name) => CSS.escape(name)).join(".");
      const parent = current.parentElement;
      if (parent) {
        const siblings = Array.from(parent.children).filter((candidate) => candidate.tagName === current.tagName);
        if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(current) + 1})`;
      }
      parts.unshift(part); current = parent;
    }
    return parts.join(" > ");
  };
  const visibleElements = (query) => Array.from(document.querySelectorAll(query)).filter(visible);
  const serializeTree = (element, depth, budget) => {
    if (!element || depth > 3 || budget.left <= 0) return null;
    budget.left -= 1;
    return {
      tag: element.tagName.toLowerCase(), id: element.id || null,
      className: String(element.className || "").slice(0, 500),
      attributes: attrs(element), text: text(element), box: box(element),
      children: Array.from(element.children).slice(0, 40).map((child) => serializeTree(child, depth + 1, budget)).filter(Boolean),
    };
  };
  const allVisible = visibleElements("*");
  const images = visibleElements("img").slice(0, 300).map((element) => ({
    src: element.src || null, currentSrc: element.currentSrc || null,
    isBlobUrl: String(element.currentSrc || element.src || "").startsWith("blob:"),
    naturalWidth: element.naturalWidth, naturalHeight: element.naturalHeight,
    renderedRect: box(element), inViewport: inViewport(element), selector: selector(element), alt: (element.alt || "").slice(0, 300),
    attributes: attrs(element),
  }));
  const canvases = visibleElements("canvas").slice(0, 100).map((element) => ({
    width: element.width, height: element.height, renderedRect: box(element), inViewport: inViewport(element), selector: selector(element),
    contexts: {"2d": Boolean(element.getContext("2d")), webgl: Boolean(element.getContext("webgl")), webgl2: Boolean(element.getContext("webgl2"))},
    attributes: attrs(element),
  }));
  const buttons = visibleElements("button, [role='button'], a, [onclick], [aria-label], [title], input[type='button'], input[type='submit']")
    .slice(0, 500).map((element) => ({
      text: text(element), ariaLabel: element.getAttribute("aria-label"), title: element.getAttribute("title"),
      role: element.getAttribute("role") || element.tagName.toLowerCase(), href: element.href || null,
      renderedRect: box(element), selector: selector(element), attributes: attrs(element),
    }));
  const backgrounds = allVisible.slice(0, 2_000).map((element) => ({element, image: getComputedStyle(element).backgroundImage}))
    .filter(({image}) => image && image !== "none").slice(0, 300).map(({element, image}) => ({
      backgroundImage: image, renderedRect: box(element), selector: selector(element), attributes: attrs(element),
    }));
  const candidateElements = allVisible.filter((element) => /viewer|reader|manga|comic|chapter|page|spread|content|read/i.test(`${element.id} ${element.className}`));
  const viewerish = candidateElements.slice(0, 300).map((element) => ({
    tag: element.tagName.toLowerCase(), id: element.id || null, className: String(element.className || "").slice(0, 500),
    text: text(element), renderedRect: box(element), selector: selector(element), attributes: attrs(element),
  }));
  const roots = candidateElements.map((element) => ({element, score:
    (/(viewer|reader)/i.test(`${element.id} ${element.className}`) ? 5 : 0) +
    (/(page|spread|content)/i.test(`${element.id} ${element.className}`) ? 2 : 0) +
    (element.querySelector("canvas, img") ? 2 : 0) + Math.min(element.children.length, 5) / 10,
  })).sort((left, right) => right.score - left.score).slice(0, 5);
  const viewerTree = roots.map(({element, score}) => ({selector: selector(element), score, tree: serializeTree(element, 0, {left: 160})}));
  const dataAttributes = allVisible.filter((element) => Array.from(element.attributes || []).some((attribute) => attribute.name.startsWith("data-")))
    .slice(0, 500).map((element) => ({selector: selector(element), attributes: attrs(element), text: text(element)}));
  const identityCandidates = [];
  const addIdentity = (source, key, value) => {
    if (value !== null && value !== undefined && String(value).trim()) identityCandidates.push({source, key, value: String(value).trim().slice(0, 500)});
  };
  for (const element of Array.from(document.querySelectorAll("meta"))) {
    const key = element.getAttribute("name") || element.getAttribute("property") || "meta";
    if (/title|chapter|episode|comic|manga|作品|話/i.test(key)) addIdentity("meta", key, element.getAttribute("content"));
  }
  for (const element of Array.from(document.querySelectorAll("[data-title-id], [data-chapter-id], [data-episode-id], [data-work-id], [data-series-id], [data-content-id], [data-page-id], [data-testid]"))) {
    for (const attribute of Array.from(element.attributes)) addIdentity("data", attribute.name, attribute.value);
  }
  for (const element of Array.from(document.querySelectorAll("h1, h2, h3, [class*='title'], [class*='chapter'], [class*='episode'], [class*='page'], [aria-label]" )).slice(0, 150)) {
    addIdentity("visible-dom", selector(element), text(element) || element.getAttribute("aria-label"));
  }
  const pageCounter = /^\s*\d+\s*\/\s*\d+\s*$/;
  const pageInfoCandidates = allVisible.filter((element) => /page|ページ|spread|total|current|何話|話数/i.test(`${element.id} ${element.className} ${text(element)} ${element.getAttribute("aria-label") || ""}`) || pageCounter.test(text(element)))
    .slice(0, 200).map((element) => ({selector: selector(element), text: text(element), ariaLabel: element.getAttribute("aria-label"), attributes: attrs(element), box: box(element)}));
  const accessObservations = allVisible.filter((element) => ACCESS_PATTERN.test(text(element)));
  const access = accessObservations.slice(0, 200).map((element) => ({selector: selector(element), text: text(element), attributes: attrs(element), box: box(element)}));
  const links = Array.from(document.querySelectorAll("a[href]")).slice(0, 2_000).map((element) => ({
    href: element.href, text: text(element), surroundingText: text(element.parentElement || element),
    className: String(element.className || "").slice(0, 500), attributes: attrs(element), selector: selector(element),
  }));
  const scripts = Array.from(document.scripts).slice(0, 500).map((element, index) => ({
    index, src: element.src || null, type: element.type || null, id: element.id || null,
    async: element.async, defer: element.defer, textLength: (element.textContent || "").length,
    inlinePreview: element.src ? null : (element.textContent || "").slice(0, 1600),
  }));
  const navigationCandidates = buttons.filter((element) => /page|ページ|forward|right|next|次|進む|arrow|chevron|slide/i.test(`${element.text} ${element.ariaLabel || ""} ${element.title || ""} ${element.attributes.class || ""}`));
  return {
    url: location.href, title: document.title, viewport: {width: innerWidth, height: innerHeight}, devicePixelRatio,
    visibleText: (document.body?.innerText || "").trim().slice(0, 20_000),
    visibleImages: images, canvases, backgrounds, viewerish, viewerTree, buttons, navigationCandidates,
    dataAttributes, identityCandidates, pageInfoCandidates, accessObservations: access, scripts, links,
    chapterLinks: links.filter((link) => /\/title\/[0-9]+\/chapter\/[0-9]+/i.test(link.href || "")),
    frameCount: window.frames.length,
  };
}
""".replace(
    "ACCESS_PATTERN",
    "/(?:無料|毎日無料|待てば無料|ポイント|コイン|購入|レンタル|チケット|広告|ログイン|閲覧期限|残り時間|次回無料|利用可能|利用済み|有料)/",
);


_NAVIGATION_CANDIDATES_SCRIPT = r"""
() => {
  const visible = (element) => {
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden" && style.opacity !== "0";
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
  const text = (element) => (element.innerText || element.value || element.getAttribute("aria-label") || element.getAttribute("title") || "")
    .trim().replace(/\s+/g, " ").slice(0, 300);
  const candidates = Array.from(document.querySelectorAll("button, [role='button'], a, [onclick], [aria-label], [title], input[type='button'], input[type='submit']"))
    .filter(visible).slice(0, 500).map((element) => ({
      text: text(element), ariaLabel: element.getAttribute("aria-label"), title: element.getAttribute("title"),
      className: String(element.className || "").slice(0, 500), href: element.href || null,
      rawHref: element.getAttribute("href"), selector: selector(element), interaction: "dom_click",
    }));
  const viewerRoots = Array.from(document.querySelectorAll("[id], [class]"))
    .filter((element) => visible(element) && /viewer|reader|comic|manga/i.test(`${element.id} ${element.className}`))
    .filter((element) => !element.parentElement || !/viewer|reader|comic|manga/i.test(`${element.parentElement.id} ${element.parentElement.className}`))
    .filter((element) => element.querySelector("img, canvas"));
  if (viewerRoots.length === 1) {
    const element = viewerRoots[0];
    candidates.push({
      text: "", ariaLabel: element.getAttribute("aria-label"), title: element.getAttribute("title"),
      className: String(element.className || "").slice(0, 500), href: null,
      rawHref: null, selector: selector(element), interaction: "keyboard", key: "ArrowLeft",
      evidence: "single visible viewer root with img/canvas content",
    });
  }
  return candidates;
}
"""


_FINGERPRINT_SCRIPT = r"""
() => {
  const visible = (element) => {
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden" && style.opacity !== "0";
  };
  const box = (element) => { const r = element.getBoundingClientRect(); return [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]; };
  const counter = window.__zeblackProbe?.counters ? window.__zeblackProbe.counters() : {};
  return JSON.stringify({
    url: location.href, title: document.title,
    images: Array.from(document.images).filter(visible).map((element) => [element.currentSrc || element.src, element.naturalWidth, element.naturalHeight, box(element)]).slice(0, 40),
    canvases: Array.from(document.querySelectorAll("canvas")).filter(visible).map((element) => [element.width, element.height, box(element), element.className || element.id || ""]).slice(0, 40),
    pageText: Array.from(document.querySelectorAll("[aria-label], [class*='page'], [class*='Page'], [class*='reader'], [class*='viewer']")).filter(visible).map((element) => (element.innerText || element.getAttribute("aria-label") || "").trim()).filter(Boolean).slice(0, 40),
    drawSequence: counter.drawCount || 0,
  });
}
"""


@dataclass(frozen=True, slots=True)
class ProbeObservation:
    state: str
    url: str
    dom: dict[str, Any]
    network: dict[str, Any]
    draw: dict[str, Any]
    directory: str


@dataclass
class ZebrackProbe:
    page: Any
    output_dir: Path
    expected_title_id: str
    expected_chapter_id: str
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

    @staticmethod
    def _request_frame_url(request: Any) -> str | None:
        try:
            frame = request.frame
            return frame.url if frame else None
        except BaseException:  # noqa: BLE001
            return None

    def _on_request(self, request: Any) -> None:
        try:
            url = request.url
            redirected_from = None
            try:
                redirected_from = request.redirected_from.url if request.redirected_from else None
            except BaseException:  # noqa: BLE001
                redirected_from = None
            self.network_events.append(
                {
                    "event": "request",
                    "timestamp": _now_iso(),
                    "url": url,
                    "method": request.method,
                    "resource_type": request.resource_type,
                    "classification": classify_resource(request.resource_type, None, url),
                    "host": urlparse(url).netloc,
                    "frame_url": self._request_frame_url(request),
                    "is_navigation_request": request.is_navigation_request(),
                    "initiator": {
                        "frame_url": self._request_frame_url(request),
                        "resource_type": request.resource_type,
                        "is_navigation_request": request.is_navigation_request(),
                    },
                    "redirected_from": redirected_from,
                }
            )
        except BaseException as exc:  # noqa: BLE001
            self.errors.append(f"request observation failed: {type(exc).__name__}: {exc}")

    def _on_response(self, response: Any) -> None:
        try:
            url = response.url
            headers = dict(response.headers)
            content_type = _header(headers, "content-type")
            request = response.request
            record: dict[str, Any] = {
                "event": "response",
                "timestamp": _now_iso(),
                "url": url,
                "method": request.method,
                "resource_type": request.resource_type,
                "classification": classify_resource(request.resource_type, content_type, url),
                "status": response.status,
                "content_type": content_type,
                "content_length": _header(headers, "content-length"),
                "host": urlparse(url).netloc,
                "frame_url": self._request_frame_url(request),
                "is_navigation_request": request.is_navigation_request(),
                "initiator": {
                    "frame_url": self._request_frame_url(request),
                    "resource_type": request.resource_type,
                    "is_navigation_request": request.is_navigation_request(),
                },
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
        raw_sha256 = hashlib.sha256(body).hexdigest()
        image_format = None
        dimensions = None
        decode_error = None
        try:
            with Image.open(__import__("io").BytesIO(body)) as image:
                image_format = image.format
                dimensions = [image.width, image.height]
        except BaseException as exc:  # noqa: BLE001
            decode_error = f"{type(exc).__name__}: {exc}"
        body_info.update(
            {
                "byte_length": len(body),
                "encoded_sha256": raw_sha256,
                "image_format": image_format,
                "dimensions": dimensions,
            }
        )
        if decode_error:
            body_info["decode_error"] = decode_error
        if len(self.saved_images) >= self.max_image_responses:
            body_info["save_skip"] = "max_image_responses"
            return
        image_dir = self.output_dir / "network_images"
        image_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(record["url"].encode("utf-8")).hexdigest()[:12]
        extension = _image_extension(record.get("content_type"), image_format)
        path = image_dir / f"image_{len(self.saved_images):03d}_{digest}.{extension}"
        try:
            path.write_bytes(body)
        except BaseException as exc:  # noqa: BLE001
            body_info["write_error"] = f"{type(exc).__name__}: {exc}"
            return
        item = {
            "url": record["url"],
            "host": record["host"],
            "network_timestamp": record["timestamp"],
            "content_type": record.get("content_type"),
            "byte_length": len(body),
            "encoded_sha256": raw_sha256,
            "image_format": image_format,
            "dimensions": dimensions,
            "decode_error": decode_error,
            "file": str(path.relative_to(self.output_dir)),
        }
        self.saved_images.append(item)
        body_info.update({"saved": True, "file": item["file"]})

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

    async def current_fingerprint(self) -> str | None:
        try:
            return await self.page.evaluate(_FINGERPRINT_SCRIPT)
        except BaseException as exc:  # noqa: BLE001
            self.errors.append(f"fingerprint observation failed: {type(exc).__name__}: {exc}")
            return None

    async def wait_for_changed_fingerprint(self, before: str, timeout: float = 10.0) -> str | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            after = await self.current_fingerprint()
            if fingerprint_changed(before, after):
                return after
            await asyncio.sleep(0.4)
        return None

    async def wait_for_fingerprint_stability(self, expected: str, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        same_count = 0
        while time.monotonic() < deadline:
            current = await self.current_fingerprint()
            if current == expected:
                same_count += 1
                if same_count >= 2:
                    return True
            else:
                same_count = 0
                expected = current or expected
            await asyncio.sleep(0.4)
        return False

    async def wait_for_stability(self, timeout: float = 12.0) -> bool:
        deadline = time.monotonic() + timeout
        previous: str | None = None
        same_count = 0
        while time.monotonic() < deadline:
            fingerprint = await self.current_fingerprint()
            if fingerprint is None:
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
                """() => window.__zeblackProbe ? window.__zeblackProbe.take() : {
                    installed: false, drawCalls: [], canvasMutations: [], rendererEvents: [],
                    offscreenCanvasAvailable: null, createImageBitmapAvailable: null
                }"""
            )
        except BaseException as exc:  # noqa: BLE001
            self.errors.append(f"draw call collection failed: {type(exc).__name__}: {exc}")
            return {"installed": False, "drawCalls": [], "canvasMutations": [], "rendererEvents": [], "error": str(exc)}

    async def collect_snapshot(self, directory_name: str, *, include_html: bool) -> ProbeObservation:
        await self.drain_image_tasks()
        try:
            dom = await self.page.evaluate(_COLLECT_PAGE_SCRIPT)
            dom["frame_urls"] = [frame.url for frame in self.page.frames]
        except BaseException as exc:  # noqa: BLE001
            self.errors.append(f"DOM collection failed: {type(exc).__name__}: {exc}")
            dom = {
                "url": self.page.url, "title": "", "viewport": {}, "devicePixelRatio": None,
                "visibleText": "", "visibleImages": [], "canvases": [], "backgrounds": [],
                "viewerish": [], "viewerTree": [], "buttons": [], "navigationCandidates": [],
                "dataAttributes": [], "identityCandidates": [], "pageInfoCandidates": [],
                "accessObservations": [], "scripts": [], "links": [], "chapterLinks": [],
                "frame_urls": [],
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
                event for event in network_delta
                if event.get("event") == "response" and event.get("body", {}).get("error")
            ],
        }
        _write_json(directory / "dom.json", dom)
        _write_json(directory / "network.json", network)
        _write_json(directory / "draw_calls.json", renderer)
        _write_json(directory / "scripts.json", dom.get("scripts", []))
        links = list(dom.get("links", []))
        chapter_links = [link for link in links if _CHAPTER_LINK.search(str(link.get("href") or ""))]
        _write_json(
            directory / "links.json",
            {
                "url": url,
                "chapter_links": chapter_links,
                "chapter_link_count": len(chapter_links),
                "other_links_sample": [link for link in links if link not in chapter_links][:100],
            },
        )
        if include_html:
            try:
                (directory / "page.html").write_text(await self.page.content(), encoding="utf-8")
            except BaseException as exc:  # noqa: BLE001
                self.errors.append(f"HTML collection failed: {type(exc).__name__}: {exc}")
        try:
            await self.page.screenshot(path=str(directory / "screenshot.png"), full_page=False)
        except BaseException as exc:  # noqa: BLE001
            self.errors.append(f"Screenshot failed: {type(exc).__name__}: {exc}")
        observation = ProbeObservation(
            state=directory_name, url=url, dom=dom, network=network, draw=renderer, directory=str(directory)
        )
        self.observations.append(observation)
        return observation

    async def capture_initial(self) -> None:
        initial = await self.collect_snapshot("initial", include_html=True)
        state_dir = self.output_dir / "state_000"
        state_dir.mkdir(parents=True, exist_ok=True)
        for name in ("dom.json", "network.json", "draw_calls.json", "scripts.json", "links.json", "page.html", "screenshot.png"):
            source = self.output_dir / "initial" / name
            if source.exists():
                target = state_dir / name
                target.write_bytes(source.read_bytes())
        self.observations.append(
            ProbeObservation(
                state="state_000", url=initial.url, dom=initial.dom, network=initial.network,
                draw=initial.draw, directory=str(state_dir),
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
            values = [candidate.get(key) for key in ("text", "ariaLabel", "title", "className", "href")]
            href = str(candidate.get("href") or "")
            if href and not is_target_viewer_url(href, self.expected_title_id, self.expected_chapter_id):
                continue
            is_keyboard_candidate = candidate.get("interaction") == "keyboard"
            if navigation_candidate_is_forbidden(*values) or (
                not is_keyboard_candidate and not looks_like_page_navigation(*values)
            ):
                continue
            label = " ".join(normalize_navigation_text(value) for value in values)
            rank = 0 if _PAGE_NAV_RE.search(label) else 1
            if is_keyboard_candidate:
                rank = 2
            ranked.append((rank, candidate))
        if not ranked:
            return None
        ranked.sort(key=lambda item: item[0])
        best_rank = ranked[0][0]
        best = [candidate for rank, candidate in ranked if rank == best_rank]
        return best[0] if len(best) == 1 else None

    async def revalidate_navigation_candidate(self, candidate: dict[str, Any]) -> Any | None:
        """Recheck text/aria/title/class/href immediately before the click."""

        selector = str(candidate.get("selector") or "")
        if not selector:
            return None
        locator = self.page.locator(selector)
        if await locator.count() != 1 or not await locator.is_visible():
            return None
        try:
            actual_text = await locator.inner_text(timeout=1_000)
        except BaseException:  # noqa: BLE001
            actual_text = ""
        if not actual_text:
            actual_text = await locator.get_attribute("value") or ""
        actual = {
            "text": actual_text,
            "ariaLabel": await locator.get_attribute("aria-label"),
            "title": await locator.get_attribute("title"),
            "className": await locator.get_attribute("class"),
            "href": await locator.get_attribute("href"),
        }
        values = [actual.get(key) for key in ("text", "ariaLabel", "title", "className", "href")]
        is_keyboard_candidate = candidate.get("interaction") == "keyboard"
        if navigation_candidate_is_forbidden(*values) or (
            not is_keyboard_candidate and not looks_like_page_navigation(*values)
        ):
            return None
        actual_href = urljoin(self.page.url, str(actual["href"] or "")) if actual["href"] else ""
        if actual_href and not is_target_viewer_url(actual_href, self.expected_title_id, self.expected_chapter_id):
            return None
        for key in ("text", "ariaLabel", "title", "className"):
            if normalize_navigation_text(candidate.get(key)) != normalize_navigation_text(actual.get(key)):
                return None
        expected_href = urljoin(self.page.url, str(candidate.get("href") or "")) if candidate.get("href") else ""
        if expected_href and actual_href and classify_url_change(
            expected_href, actual_href, self.expected_title_id, self.expected_chapter_id
        ) == "target_changed":
            return None
        return locator

    async def advance_once(self, step: int) -> bool:
        if not is_target_viewer_url(self.page.url, self.expected_title_id, self.expected_chapter_id):
            self.stopped_reason = "target viewer URL changed before navigation"
            return False
        candidate = await self.choose_navigation()
        if candidate is None:
            self.navigation.append({"step": step, "status": "not_observed_or_ambiguous", "method": None})
            return False
        before_url = self.page.url
        before_fingerprint = await self.current_fingerprint()
        if before_fingerprint is None:
            self.navigation.append({"step": step, "status": "fingerprint_unavailable", "method": "dom_click"})
            return False
        try:
            locator = await self.revalidate_navigation_candidate(candidate)
            if locator is None:
                self.navigation.append({
                    "step": step, "status": "candidate_revalidation_failed", "method": "dom_click", "candidate": candidate,
                })
                return False
            if candidate.get("interaction") == "keyboard":
                await self.page.keyboard.press(str(candidate.get("key") or "ArrowRight"))
            else:
                await locator.click(timeout=5_000, no_wait_after=True)
            changed_fingerprint = await self.wait_for_changed_fingerprint(before_fingerprint, timeout=10.0)
            changed = changed_fingerprint is not None
            stable = changed and await self.wait_for_fingerprint_stability(changed_fingerprint or "", timeout=10.0)
        except BaseException as exc:  # noqa: BLE001
            self.navigation.append({
                "step": step, "status": "failed", "method": "dom_click", "candidate": candidate,
                "error": f"{type(exc).__name__}: {exc}",
            })
            return False
        after_url = self.page.url
        url_kind = classify_url_change(
            before_url, after_url, self.expected_title_id, self.expected_chapter_id
        )
        method = "keyboard" if candidate.get("interaction") == "keyboard" else "dom_click"
        record = {
            "step": step,
            "status": "changed_and_stable" if changed and stable else "changed_but_not_stable" if changed else "not_changed",
            "method": method,
            "candidate": candidate,
            "before_url": before_url,
            "after_url": after_url,
            "url_change_kind": url_kind,
            "changed": changed,
            "stable": stable,
        }
        self.navigation.append(record)
        if url_kind == "target_changed":
            self.stopped_reason = "target viewer URL changed after navigation"
            return False
        return navigation_succeeded(changed, stable)

    async def run(self, url: str, steps: int) -> dict[str, Any]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.install_listeners()
        await self.page.add_init_script(script=_DRAW_HOOK)
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        except BaseException as exc:  # noqa: BLE001
            self.errors.append(f"page.goto failed: {type(exc).__name__}: {exc}")
        await self.wait_for_stability(timeout=12.0)
        if not is_target_viewer_url(self.page.url, self.expected_title_id, self.expected_chapter_id):
            self.stopped_reason = "target viewer URL changed during initial navigation"
        await self.capture_initial()
        if self.stopped_reason:
            await self.drain_image_tasks()
            return self.as_report(url, steps)
        for step in range(1, steps + 1):
            if not await self.advance_once(step):
                break
            await self.collect_snapshot(f"state_{step:03d}", include_html=False)
        await self.drain_image_tasks()
        return self.as_report(url, steps)

    def as_report(self, target_url: str, steps: int) -> dict[str, Any]:
        draw_calls = [call for observation in self.observations for call in observation.draw.get("drawCalls", [])]
        return {
            "target_url": target_url,
            "target_title_id": self.expected_title_id,
            "target_chapter_id": self.expected_chapter_id,
            "final_url": self.page.url,
            "final_url_change_kind": classify_url_change(
                target_url, self.page.url, self.expected_title_id, self.expected_chapter_id
            ),
            "steps_requested": steps,
            "max_steps": MAX_STEPS,
            "states_observed": len(self.observations),
            "navigation": self.navigation,
            "saved_network_images": self.saved_images,
            "image_response_limit": self.max_image_responses,
            "draw_calls_observed": len(draw_calls),
            "draw_geometry_classification": classify_draw_geometry(draw_calls),
            "observations": [
                {"state": item.state, "url": item.url, "directory": item.directory}
                for item in self.observations
            ],
            "stopped_reason": self.stopped_reason,
            "errors": self.errors,
        }

    def write_report(self, report: dict[str, Any]) -> None:
        _write_json(self.output_dir / "report.json", report)
        (self.output_dir / "summary.md").write_text(self.make_summary(report), encoding="utf-8")

    def make_summary(self, report: dict[str, Any]) -> str:
        initial = next((item for item in self.observations if item.state == "initial"), None)
        dom = initial.dom if initial else {}
        all_draw_calls = [call for item in self.observations for call in item.draw.get("drawCalls", [])]
        all_events = [event for item in self.observations for event in item.network.get("events", [])]
        access_text = " ".join(str(item.dom.get("visibleText", "")) for item in self.observations)
        access_matches = sorted(set(_ACCESS_TERMS.findall(access_text)))
        classifications = sorted({str(event.get("classification")) for event in all_events if event.get("classification")})
        image_hosts = sorted({str(item.get("host")) for item in self.saved_images if item.get("host")})
        formats = sorted({str(item.get("image_format")) for item in self.saved_images if item.get("image_format")})
        dimensions = sorted({tuple(item.get("dimensions", [])) for item in self.saved_images if item.get("dimensions")})
        visible_canvas_count = len(dom.get("canvases", []))
        visible_image_count = len(dom.get("visibleImages", []))
        viewport_canvas_count = sum(1 for item in dom.get("canvases", []) if item.get("inViewport"))
        viewport_image_count = sum(1 for item in dom.get("visibleImages", []) if item.get("inViewport"))
        page_like_images = [
            item for item in dom.get("visibleImages", [])
            if re.search(r"page|ページ", f"{item.get('alt', '')} {item.get('attributes', {}).get('class', '')}", re.IGNORECASE)
        ]
        source_types = sorted({str((call.get("source") or {}).get("type")) for call in all_draw_calls})
        page_states = []
        page_counter_re = re.compile(r"^\s*\d+\s*/\s*\d+\s*$")
        for item in self.observations:
            counters = [
                candidate.get("text") for candidate in item.dom.get("pageInfoCandidates", [])
                if page_counter_re.fullmatch(str(candidate.get("text") or ""))
            ]
            page_states.append(
                {
                    "state": item.state,
                    "counters": counters[:5],
                    "in_viewport_page_images": [
                        image.get("alt") for image in item.dom.get("visibleImages", [])
                        if image.get("inViewport") and re.search(
                            r"page|ページ", f"{image.get('alt', '')} {image.get('attributes', {}).get('class', '')}", re.IGNORECASE
                        )
                    ],
                }
            )
        chapter_links = dom.get("chapterLinks", [])
        next_candidates = [
            link for link in chapter_links
            if re.search(r"next|次|続き|chapter", f"{link.get('text', '')} {link.get('href', '')}", re.IGNORECASE)
        ]
        original_status = "possible" if self.saved_images else "unknown"
        source_native_status = "possible" if page_like_images or all_draw_calls else "unknown"
        native_reconstruction_status = "unknown"
        canvas_status = "confirmed" if visible_canvas_count else "rejected" if page_like_images else "unknown"
        locator_status = "possible" if visible_canvas_count or visible_image_count else "unknown"
        lines = [
            "# Zebrack Z0 viewer probe summary",
            "",
            "## 1. Target",
            "",
            f"- URL: `{report['target_url']}`",
            f"- title_id: `{report['target_title_id']}`; chapter_id: `{report['target_chapter_id']}`",
            f"- final URL: `{report['final_url']}`",
            f"- URL relation: `{report['final_url_change_kind']}`",
            f"- states observed: `{report['states_observed']}`; safety stop: `{report.get('stopped_reason') or 'none'}`",
            "",
            "## 2. Viewer structure",
            "",
            f"- viewport/devicePixelRatio: `{dom.get('viewport')}` / `{dom.get('devicePixelRatio')}`",
            f"- visible img: `{visible_image_count}` (`inViewport={viewport_image_count}`); visible canvas: `{visible_canvas_count}` (`inViewport={viewport_canvas_count}`); CSS background candidates: `{len(dom.get('backgrounds', []))}`",
            f"- viewer-like DOM candidates: `{len(dom.get('viewerish', []))}`; viewer tree roots: `{len(dom.get('viewerTree', []))}`",
            f"- frame URLs: `{json.dumps(dom.get('frame_urls', []), ensure_ascii=False)}`",
            "- The DOM artifacts retain class/id/data-* attributes and do not treat every visible image as page content.",
            "",
            "## 3. Page rendering method",
            "",
            f"- observed candidates: `img={visible_image_count} (inViewport={viewport_image_count}), canvas={visible_canvas_count} (inViewport={viewport_canvas_count}), background={len(dom.get('backgrounds', []))}`",
            f"- drawImage source types: `{', '.join(source_types) or 'not observed'}`",
            f"- page rendering conclusion: `page-like img candidates {'observed' if page_like_images else 'not observed'}; canvas/background {'observed' if visible_canvas_count or dom.get('backgrounds') else 'not observed'}; production attribution not made by Z0`",
            "",
            "## 4. Network image candidates",
            "",
            f"- saved response bodies: `{len(self.saved_images)}` / limit `{self.max_image_responses}`",
            f"- image hosts: `{', '.join(image_hosts) or 'not observed'}`",
            f"- formats: `{', '.join(formats) or 'not observed'}`; dimensions: `{', '.join(f'{w}x{h}' for w, h in dimensions) or 'not observed'}`",
            f"- observed response classifications: `{', '.join(classifications) or 'not observed'}`",
            "- Every saved body is a bounded diagnostic candidate. Z0 does not claim a one-to-one mapping to a visible page.",
            "",
            "## 5. Canvas / drawImage observations",
            "",
            f"- drawImage calls: `{len(all_draw_calls)}`; createImageBitmap events: `{sum(len(item.draw.get('rendererEvents', [])) for item in self.observations)}`",
            f"- geometry classification: `{report['draw_geometry_classification']}`",
            "- draw hook fields include source type/url/dimensions, source/destination rectangles, canvas identity, transform, composite, filter, and alpha.",
            "- Hook does not encode, base64-encode, hash, fetch, or copy full canvas pixels.",
            "",
            "## 6. Navigation",
            "",
            f"- bounded page advances requested: `{report['steps_requested']}`; maximum: `{MAX_STEPS}`",
            f"- navigation records: `{json.dumps(report['navigation'], ensure_ascii=False)}`",
            "- Candidate interaction is allowed only after text/aria-label/title/class/href revalidation and target URL checks.",
            "",
            "## 7. Page-change signal",
            "",
            "- Signal: combined visible img/canvas/page-text metadata and renderer draw sequence fingerprint.",
            "- A transition is accepted only after both `changed` and two consecutive equal bounded observations (`stable`).",
            f"- draw sequence observations: `{len(all_draw_calls)}`; fixed-sleep-only decision: `rejected`",
            "",
            "## 8. Spread / reading order",
            "",
            f"- simultaneous DOM-visible canvas/img geometry is recorded in each state DOM artifact; initial counts are `{visible_canvas_count}` canvas / `{visible_image_count}` img (`inViewport={viewport_canvas_count}` / `{viewport_image_count}`)",
            f"- page counter / in-viewport page-like image clues by state: `{json.dumps(page_states, ensure_ascii=False)}`",
            "- spread-like two-page layout and left/right coordinates are observed in later states; semantic reading order remains `unknown` in Z0.",
            "",
            "## 9. END / NEXT_CONTENT candidates",
            "",
            f"- chapter-link candidates: `{len(chapter_links)}`; next-like candidates: `{len(next_candidates)}`",
            f"- page/current/total candidates in initial DOM: `{len(dom.get('pageInfoCandidates', []))}`",
            "- END/NEXT_CONTENT is recorded as evidence only and is not implemented as a production decision.",
            "- Next-chapter links were never clicked.",
            "",
            "## 10. Access-related observations",
            "",
            f"- visible terms: `{', '.join(access_matches) or 'not observed'}`",
            f"- access observation entries: `{len(dom.get('accessObservations', []))}`",
            "- free/paid/resource/reset/scope/grant classification: `not implemented in Z0`",
            "- No daily-free, point, coin, purchase, rental, ticket, advertisement, or login operation was initiated.",
            "",
            "## 11. Capture strategy assessment",
            "",
            f"- original response bytes: `{original_status}`",
            f"- source-native: `{source_native_status}`",
            f"- native reconstruction: `{native_reconstruction_status}`",
            f"- canvas: `{canvas_status}`",
            f"- locator screenshot: `{locator_status}`; viewport screenshots are saved for every observed state",
            "- Z0 does not select a production capture path.",
            "",
            "## 12. Unknown / unresolved items",
            "",
            "- Exact response-to-visible-page mapping, image scramble/reconstruction, spread order, and page count semantics remain unresolved unless the artifacts prove them.",
            "- Shadow DOM/cross-origin frame internals, if present, may require a separate bounded investigation.",
            f"- probe errors: `{json.dumps(report.get('errors', []), ensure_ascii=False)}`",
            "",
            "## 13. Recommended Z1 investigation",
            "",
            "- Correlate a small set of saved image candidates with the stable viewer rendering using source/draw metadata and rendered references.",
            "- Verify whether the same canvas is reused, whether a spread is present, and which control changes exactly one page or spread.",
            "- Identify a stable current/total page signal and an end/next-content boundary without clicking the next chapter.",
            "- Keep access resource names and timing semantics open until a dedicated safe observation is available.",
        ]
        return "\n".join(lines) + "\n"


# Compatibility spelling for callers that use the filename spelling.
ZeblackProbe = ZebrackProbe


async def run_probe(
    url: str,
    output_dir: Path,
    steps: int,
    cdp_endpoint: str | None,
    z1: bool = False,
) -> dict[str, Any]:
    if z1:
        try:
            from .zeblack_capture_probe import run_z1_probe
        except ImportError:  # pragma: no cover - direct script execution.
            from zeblack_capture_probe import run_z1_probe  # type: ignore[no-redef]

        return await run_z1_probe(url, output_dir, steps, cdp_endpoint)
    identity = extract_viewer_identity(url)
    if identity is None:
        raise ValueError(
            "--url must be a Zebrack URL of the form "
            "https://zebrack-comic.shueisha.co.jp/title/<id>/chapter/<id>/viewer"
        )
    endpoint = resolve_cdp_endpoint(cli_endpoint=cdp_endpoint)
    session = await BrowserSession.connect(endpoint)
    page = await session.new_page()
    probe = ZebrackProbe(
        page=page,
        output_dir=output_dir,
        expected_title_id=identity["title_id"],
        expected_chapter_id=identity["chapter_id"],
    )
    try:
        report = await probe.run(url, max(0, min(MAX_STEPS, steps)))
        probe.write_report(report)
        return report
    finally:
        await session.close_page(page)
        await session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only Zebrack Z0/Z1 viewer probe")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--steps", type=int, default=3, help="bounded in-chapter advances, maximum 3")
    parser.add_argument("--cdp-endpoint", default=None)
    parser.add_argument(
        "--z1",
        action="store_true",
        help="opt in to blob-JPEG retrieval and native pixel-equivalence verification",
    )
    args = parser.parse_args()
    report = asyncio.run(run_probe(args.url, args.output_dir, args.steps, args.cdp_endpoint, args.z1))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
