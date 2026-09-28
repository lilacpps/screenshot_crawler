"""Read-only J0 probe for the Shonen Jump+ vertical episode viewer.

The probe deliberately stays outside production capture.  It opens one fresh
viewer state per operation, records scroll/container geometry, captures only
bounded diagnostic artifacts, and never clicks purchase, access, or next-
episode controls.

Example::

    .\\.venv\\Scripts\\python.exe poc\\jumpplus_vertical_probe.py `
        --url https://shonenjumpplus.com/episode/10834108156642491399 `
        --output-dir output\\jumpplus_vertical_probe
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any

try:
    from poc.jumpplus_probe import (
        _DRAW_HOOK,
        _EPISODE_LINK,
        JumpPlusProbe,
        _decoded_pixel_sha256,
        _now_iso,
        _write_json,
        _write_text,
        extract_episode_id,
        is_target_episode_url,
    )
except ModuleNotFoundError:  # direct ``python poc/<probe>.py`` invocation
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from poc.jumpplus_probe import (
        _DRAW_HOOK,
        _EPISODE_LINK,
        JumpPlusProbe,
        _decoded_pixel_sha256,
        _now_iso,
        _write_json,
        _write_text,
        extract_episode_id,
        is_target_episode_url,
    )
from screenshot_crawler.core.browser import BrowserSession, resolve_cdp_endpoint

DEFAULT_URL = "https://shonenjumpplus.com/episode/10834108156642491399"
DEFAULT_OUTPUT_DIR = Path("output/jumpplus_vertical_probe")
DEFAULT_OPERATIONS = (
    "ArrowDown",
    "PageDown",
    "Space",
    "End",
    "wheel",
    "window_scrollBy",
    "container_scrollBy",
    "scrollIntoView",
)
MAX_OPERATIONS = 8
MAX_CONTENT_CAPTURES = 64
MAX_SOURCES = 32
STABILITY_TIMEOUT_SECONDS = 8.0


_VERTICAL_DOM_SCRIPT = r"""
() => {
  const box = (element) => {
    const rect = element.getBoundingClientRect();
    return {x: rect.x, y: rect.y, width: rect.width, height: rect.height,
      top: rect.top, right: rect.right, bottom: rect.bottom, left: rect.left};
  };
  const style = (element) => {
    if (!element) return {};
    const computed = getComputedStyle(element);
    return {
      display: computed.display,
      visibility: computed.visibility,
      opacity: computed.opacity,
      overflowX: computed.overflowX,
      overflowY: computed.overflowY,
      position: computed.position,
    };
  };
  const visible = (element) => {
    const rect = element.getBoundingClientRect();
    const computed = getComputedStyle(element);
    return computed.display !== "none" && computed.visibility !== "hidden" &&
      Number(computed.opacity) !== 0 && rect.width > 0 && rect.height > 0;
  };
  const intersection = (element) => {
    const rect = element.getBoundingClientRect();
    const width = Math.max(0, Math.min(rect.right, innerWidth) - Math.max(rect.left, 0));
    const height = Math.max(0, Math.min(rect.bottom, innerHeight) - Math.max(rect.top, 0));
    const area = rect.width * rect.height;
    return {area: width * height, ratio: area ? (width * height) / area : 0,
      inViewport: width > 0 && height > 0};
  };
  const selector = (element) => {
    if (!element) return null;
    if (element.id) return `#${CSS.escape(element.id)}`;
    const parts = [];
    let current = element;
    while (current && current.nodeType === 1 && parts.length < 7) {
      let part = current.tagName.toLowerCase();
      if (current.classList && current.classList.length) {
        part += "." + Array.from(current.classList).slice(0, 3)
          .map((name) => CSS.escape(name)).join(".");
      }
      const parent = current.parentElement;
      if (parent) {
        const siblings = Array.from(parent.children).filter((item) => item.tagName === current.tagName);
        if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(current) + 1})`;
      }
      parts.unshift(part);
      current = parent;
    }
    return parts.join(" > ");
  };
  const attrs = (element) => {
    const result = {};
    for (const attribute of Array.from(element?.attributes || [])) {
      if (attribute.name.startsWith("data-") ||
          ["id", "class", "role", "aria-label", "title", "alt"].includes(attribute.name)) {
        result[attribute.name] = attribute.value.slice(0, 500);
      }
    }
    return result;
  };
  const imageInfo = (element) => {
    if (!element) return null;
    const isCanvas = element.tagName.toLowerCase() === "canvas";
    const isImage = element.tagName.toLowerCase() === "img";
    const hookInfo = isCanvas && typeof window.__jumpplusProbe?.canvasInfo === "function"
      ? window.__jumpplusProbe.canvasInfo(element) : {};
    return {
      tag: element.tagName.toLowerCase(),
      selector: selector(element),
      canvasId: hookInfo.id || null,
      width: isCanvas ? element.width : null,
      height: isCanvas ? element.height : null,
      naturalWidth: isImage ? element.naturalWidth : null,
      naturalHeight: isImage ? element.naturalHeight : null,
      complete: isImage ? element.complete : null,
      src: isImage ? (element.src || null) : null,
      currentSrc: isImage ? (element.currentSrc || null) : null,
      visible: visible(element),
      renderedRect: box(element),
      attributes: attrs(element),
    };
  };
  const scrollEntry = (name, element) => ({
    name,
    tag: element?.tagName?.toLowerCase() || null,
    id: element?.id || null,
    className: String(element?.className || "").slice(0, 500),
    scrollTop: element ? Number(element.scrollTop) || 0 : Number(scrollY) || 0,
    scrollLeft: element ? Number(element.scrollLeft) || 0 : Number(scrollX) || 0,
    scrollHeight: element ? Number(element.scrollHeight) || 0 : Number(document.scrollingElement?.scrollHeight) || 0,
    scrollWidth: element ? Number(element.scrollWidth) || 0 : Number(document.scrollingElement?.scrollWidth) || 0,
    clientHeight: element ? Number(element.clientHeight) || 0 : Number(innerHeight) || 0,
    clientWidth: element ? Number(element.clientWidth) || 0 : Number(innerWidth) || 0,
    renderedRect: element ? box(element) : {x: 0, y: 0, width: innerWidth, height: innerHeight},
    style: element ? style(element) : {},
  });
  const viewer = document.querySelector("section.viewer.js-viewer");
  const content = document.querySelector("#content.content-vertical") || document.querySelector("#content");
  const inner = document.querySelector(".content-inner.scroll-vertical.js-vertical-viewer");
  const container = document.querySelector(".image-container.js-viewer-content");
  const scrollingElement = document.scrollingElement || document.documentElement;
  const pageAreas = Array.from(document.querySelectorAll(".image-container.js-viewer-content .page-area.js-page-area"));
  const regions = pageAreas.map((area, index) => {
    const rect = box(area);
    const view = intersection(area);
    const canvas = area.querySelector("canvas.page-image.js-page-image, canvas");
    const image = area.querySelector("img");
    const imageElement = canvas || image;
    const imageData = imageInfo(imageElement);
    return {
      index,
      documentIndex: pageAreas.indexOf(area),
      tag: area.tagName.toLowerCase(),
      id: area.id || null,
      className: String(area.className || "").slice(0, 500),
      selector: selector(area),
      renderedRect: rect,
      offsetTop: Number(area.offsetTop) || 0,
      offsetHeight: Number(area.offsetHeight) || 0,
      visible: visible(area),
      inViewport: view.inViewport,
      intersectionRatio: view.ratio,
      image: imageData,
      childCounts: {
        img: area.querySelectorAll("img").length,
        canvas: area.querySelectorAll("canvas").length,
        picture: area.querySelectorAll("picture").length,
        source: area.querySelectorAll("source").length,
      },
      isContentPage: Boolean(canvas),
    };
  });
  const visibleInteractive = Array.from((viewer || document).querySelectorAll(
    "button, [role='button'], a, [onclick], input[type='button'], input[type='submit']"
  )).filter(visible).slice(0, 300).map((element) => ({
    text: (element.innerText || element.value || element.getAttribute("aria-label") || element.getAttribute("title") || "").trim().replace(/\s+/g, " ").slice(0, 300),
    ariaLabel: element.getAttribute("aria-label"),
    title: element.getAttribute("title"),
    className: String(element.className || "").slice(0, 500),
    href: element.href || null,
    selector: selector(element),
    renderedRect: box(element),
    attributes: attrs(element),
  }));
  const elements = Array.from((viewer || document).querySelectorAll("img, canvas, picture, source, object"))
    .slice(0, 500).map((element) => ({
      tag: element.tagName.toLowerCase(), selector: selector(element), renderedRect: box(element),
      visible: visible(element), inViewport: intersection(element).inViewport,
      src: element.currentSrc || element.src || element.getAttribute("src") || null,
      width: Number(element.width) || null, height: Number(element.height) || null,
      naturalWidth: Number(element.naturalWidth) || null, naturalHeight: Number(element.naturalHeight) || null,
      attributes: attrs(element),
    }));
  const scripts = Array.from(document.scripts).slice(0, 500).map((element, index) => ({
    index, src: element.src || null, type: element.type || null, id: element.id || null,
    textLength: (element.textContent || "").length,
    inlinePreview: element.src ? null : (element.textContent || "").slice(0, 1200),
  }));
  const links = Array.from(document.querySelectorAll("a[href]")).slice(0, 2_000).map((element) => ({
    href: element.href, text: (element.innerText || "").trim().replace(/\s+/g, " ").slice(0, 300),
    className: String(element.className || "").slice(0, 500), selector: selector(element), attributes: attrs(element),
  }));
  return {
    url: location.href,
    title: document.title,
    viewport: {width: innerWidth, height: innerHeight},
    devicePixelRatio,
    visibleText: (document.body?.innerText || "").trim().slice(0, 20_000),
    viewer: viewer ? {selector: selector(viewer), renderedRect: box(viewer), style: style(viewer)} : null,
    content: content ? {selector: selector(content), renderedRect: box(content), style: style(content)} : null,
    inner: inner ? {selector: selector(inner), renderedRect: box(inner), style: style(inner)} : null,
    container: container ? {selector: selector(container), renderedRect: box(container), style: style(container)} : null,
    scroll: {
      windowX: Number(scrollX) || 0,
      windowY: Number(scrollY) || 0,
      scrollingElement: scrollEntry("document", scrollingElement),
      candidates: [
        scrollEntry("window", null),
        scrollEntry("content", content),
        scrollEntry("vertical_inner", inner),
        scrollEntry("image_container", container),
      ],
    },
    pageCount: regions.filter((region) => region.isContentPage).length,
    allRegionCount: regions.length,
    regions,
    activeRegions: regions.filter((region) => region.isContentPage && region.inViewport && region.visible).map((region) => region.index),
    visibleImages: regions.filter((region) => region.isContentPage && region.inViewport && region.visible).map((region) => region.image).filter(Boolean),
    elements,
    interactive: visibleInteractive,
    scripts,
    links,
  };
}
"""


_VERTICAL_SCROLL_STATE_SCRIPT = r"""
() => {
  const inner = document.querySelector(".content-inner.scroll-vertical.js-vertical-viewer");
  const content = document.querySelector("#content.content-vertical") || document.querySelector("#content");
  const areas = Array.from(document.querySelectorAll(".image-container.js-viewer-content .page-area.js-page-area"));
  const active = areas.map((area, index) => {
    if (!area.querySelector("canvas.page-image.js-page-image, canvas")) return null;
    const rect = area.getBoundingClientRect();
    const width = Math.max(0, Math.min(rect.right, innerWidth) - Math.max(rect.left, 0));
    const height = Math.max(0, Math.min(rect.bottom, innerHeight) - Math.max(rect.top, 0));
    const computed = getComputedStyle(area);
    return {index, inViewport: width > 0 && height > 0 && computed.display !== "none" && computed.visibility !== "hidden", ratio: rect.width * rect.height ? (width * height) / (rect.width * rect.height) : 0};
  }).filter((item) => item && item.inViewport).map((item) => item.index);
  return {
    windowX: Number(scrollX) || 0,
    windowY: Number(scrollY) || 0,
    contentTop: content ? Number(content.scrollTop) || 0 : null,
    innerTop: inner ? Number(inner.scrollTop) || 0 : null,
    active,
    pageCount: areas.length,
  };
}
"""


_VERTICAL_SCROLL_ACTION_SCRIPT = r"""
({operation, amount, targetIndex}) => {
  const content = document.querySelector("#content.content-vertical") || document.querySelector("#content");
  const areas = Array.from(document.querySelectorAll(".image-container.js-viewer-content .page-area.js-page-area"));
  const target = Number.isInteger(targetIndex) ? areas[targetIndex] : null;
  if (operation === "window_scrollBy") window.scrollBy(0, amount);
  else if (operation === "container_scrollBy" && content) content.scrollBy(0, amount);
  else if (operation === "scrollIntoView" && target) target.scrollIntoView({block: "start", inline: "nearest", behavior: "instant"});
  return {contentFound: Boolean(content), targetFound: Boolean(target), pageCount: areas.length};
}
"""


def _normalise_operation_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", value).lower()


def operation_key(value: str) -> str:
    aliases = {
        "arrowdown": "ArrowDown",
        "pagedown": "PageDown",
        "space": "Space",
        "end": "End",
        "wheel": "wheel",
        "windowscrollby": "window_scrollBy",
        "containerscrollby": "container_scrollBy",
        "scrollintoview": "scrollIntoView",
    }
    key = _normalise_operation_name(value)
    if key not in aliases:
        raise ValueError(f"unsupported operation: {value}")
    return aliases[key]


def _active_indices(snapshot: dict[str, Any]) -> list[int]:
    return [int(item) for item in snapshot.get("activeRegions", []) if isinstance(item, int | float)]


def _first_scroll_entry(snapshot: dict[str, Any], name: str) -> dict[str, Any]:
    for item in (snapshot.get("scroll") or {}).get("candidates", []):
        if item.get("name") == name:
            return item
    return {}


def scroll_position(snapshot: dict[str, Any]) -> dict[str, Any]:
    scroll = snapshot.get("scroll") or {}
    return {
        "window_x": scroll.get("windowX"),
        "window_y": scroll.get("windowY"),
        "document_top": (scroll.get("scrollingElement") or {}).get("scrollTop"),
        "content_top": _first_scroll_entry(snapshot, "content").get("scrollTop"),
        "inner_top": _first_scroll_entry(snapshot, "vertical_inner").get("scrollTop"),
    }


def scroll_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    left = scroll_position(before)
    right = scroll_position(after)
    result: dict[str, Any] = {}
    for key, value in left.items():
        after_value = right.get(key)
        if isinstance(value, (int, float)) and isinstance(after_value, (int, float)):
            result[key] = after_value - value
        else:
            result[key] = None
    return result


def next_content_reached(before: dict[str, Any], after: dict[str, Any]) -> bool:
    before_active = _active_indices(before)
    after_active = _active_indices(after)
    return bool(before_active and after_active and max(after_active) > max(before_active))


def geometry_order(snapshot: dict[str, Any]) -> list[int]:
    regions = [item for item in (snapshot.get("regions") or []) if item.get("isContentPage")]
    return [int(item["index"]) for item in sorted(regions, key=lambda row: (row.get("renderedRect", {}).get("top", 0), row.get("index", 0)))]


def loaded_content_count(snapshot: dict[str, Any]) -> int:
    count = 0
    for region in (snapshot.get("regions") or []):
        if not region.get("isContentPage"):
            continue
        image = region.get("image") or {}
        if image.get("tag") == "canvas" and (image.get("width") or 0) > 0 and (image.get("height") or 0) > 0 or image.get("tag") == "img" and image.get("complete") and (image.get("naturalWidth") or 0) > 0:
            count += 1
    return count


def _operation_score(operation: dict[str, Any]) -> tuple[int, int, int]:
    return (
        int(bool(operation.get("stable"))),
        int(bool(operation.get("next_content_reached"))),
        int(operation.get("active_after_count") or 0),
    )


def recommend_navigation(operations: list[dict[str, Any]]) -> dict[str, Any]:
    observed = [item for item in operations if item.get("status") == "observed"]
    if not observed:
        return {"primary": "unknown", "fallback": "unknown", "do_not_use": [], "reason": "no operation produced an observed stable state"}
    geometry_ops = [item for item in observed if item.get("operation") == "scrollIntoView" and item.get("next_content_reached")]
    container_ops = [item for item in observed if item.get("operation") == "container_scrollBy" and item.get("next_content_reached")]
    primary_pool = geometry_ops or container_ops
    if primary_pool:
        primary = "scrollIntoView(target content image)" if geometry_ops else "vertical viewer container.scrollBy with geometry checks"
    else:
        primary = "geometry-driven scroll with active content visibility checks"
    fallback_candidates = [
        item for item in observed
        if item.get("operation") in {"wheel", "PageDown", "Space", "window_scrollBy"}
        and item.get("next_content_reached")
    ]
    fallback = fallback_candidates[0]["operation"] if fallback_candidates else "unknown"
    do_not_use = [
        item["operation"] for item in observed
        if item["operation"] == "ArrowDown" and not item.get("next_content_reached")
    ]
    return {
        "primary": primary,
        "fallback": fallback,
        "do_not_use": do_not_use,
        "reason": "recommendation is derived from one bounded operation per fresh initial state; it is not a production contract",
    }


class VerticalProbe(JumpPlusProbe):
    """Reuse the existing bounded network/draw hook while adding vertical probes."""

    async def collect_vertical_snapshot(
        self,
        directory_name: str,
        *,
        include_html: bool = False,
    ) -> dict[str, Any]:
        await self.drain_image_tasks()
        try:
            dom = await self.page.evaluate(_VERTICAL_DOM_SCRIPT)
        except BaseException as exc:  # noqa: BLE001
            self.errors.append(f"vertical DOM collection failed: {type(exc).__name__}: {exc}")
            dom = {"url": self.page.url, "title": "", "regions": [], "activeRegions": [], "scroll": {}}
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
        episode_links = [link for link in dom.get("links", []) if _EPISODE_LINK.search(str(link.get("href") or ""))]
        _write_json(directory / "links.json", {"url": url, "episode_links": episode_links, "episode_link_count": len(episode_links)})
        if include_html:
            try:
                _write_text(directory / "page.html", await self.page.content())
            except BaseException as exc:  # noqa: BLE001
                self.errors.append(f"vertical HTML collection failed: {type(exc).__name__}: {exc}")
        try:
            await self.page.screenshot(path=str(directory / "screenshot.png"), full_page=False)
        except BaseException as exc:  # noqa: BLE001
            self.errors.append(f"vertical screenshot failed: {type(exc).__name__}: {exc}")
        return {
            "state": directory_name,
            "url": url,
            "dom": dom,
            "network": network,
            "draw": renderer,
            "directory": str(directory),
        }

    async def wait_for_scroll_stability(self, timeout: float = STABILITY_TIMEOUT_SECONDS) -> bool:
        deadline = time.monotonic() + timeout
        previous: str | None = None
        same_count = 0
        while time.monotonic() < deadline:
            try:
                state = await self.page.evaluate(_VERTICAL_SCROLL_STATE_SCRIPT)
            except BaseException as exc:  # noqa: BLE001
                self.errors.append(f"vertical stability observation failed: {type(exc).__name__}: {exc}")
                return False
            current = json.dumps(state, sort_keys=True, separators=(",", ":"))
            if current == previous:
                same_count += 1
                if same_count >= 2:
                    return True
            else:
                previous = current
                same_count = 0
            await asyncio.sleep(0.25)
        return False

    async def capture_content_images(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """Attempt raw canvas capture, then use a rendered locator screenshot."""

        capture_dir = self.output_dir / "content_captures"
        capture_dir.mkdir(parents=True, exist_ok=True)
        source_dir = self.output_dir / "sources"
        source_dir.mkdir(parents=True, exist_ok=True)
        original_scroll = scroll_position(snapshot)
        try:
            await self.page.evaluate(
                """({windowY, innerTop}) => {
                    window.scrollTo(0, Number(windowY) || 0);
                    const inner = document.querySelector('.content-inner.scroll-vertical.js-vertical-viewer');
                    if (inner && innerTop !== null && innerTop !== undefined) inner.scrollTop = Number(innerTop) || 0;
                }""",
                {"windowY": original_scroll.get("window_y") or 0, "innerTop": original_scroll.get("inner_top")},
            )
            await self.wait_for_scroll_stability(timeout=4.0)
        except BaseException as exc:  # noqa: BLE001
            self.errors.append(f"content capture initial scroll restore failed: {type(exc).__name__}: {exc}")
        captures: list[dict[str, Any]] = []
        regions = [
            item for item in (snapshot.get("dom") or {}).get("regions", [])
            if item.get("isContentPage")
        ][:MAX_CONTENT_CAPTURES]
        for region in regions:
            index = int(region.get("index", len(captures)))
            image = region.get("image") or {}
            canvas_selector = image.get("selector") if image.get("tag") == "canvas" else None
            area_selector = region.get("selector")
            record: dict[str, Any] = {
                "index": index,
                "canvas_id": image.get("canvasId"),
                "canvas_dimensions": [image.get("width"), image.get("height")],
                "area_selector": area_selector,
                "canvas_selector": canvas_selector,
                "raw_canvas": {"attempted": False, "saved": False},
                "rendered_screenshot": {"attempted": False, "saved": False},
            }
            if canvas_selector:
                record["raw_canvas"]["attempted"] = True
                try:
                    locator = self.page.locator(canvas_selector)
                    if await locator.count() == 1:
                        raw = await locator.evaluate(
                            """(canvas) => {
                                try { return {dataUrl: canvas.toDataURL('image/png')}; }
                                catch (error) { return {error: `${error.name}: ${error.message}`}; }
                            }"""
                        )
                        if raw.get("dataUrl"):
                            file = self._save_data_url(raw["dataUrl"], capture_dir / f"content_{index:03d}_raw.png")
                            record["raw_canvas"].update({"saved": bool(file), "file": file})
                        if raw.get("error"):
                            record["raw_canvas"]["error"] = raw["error"]
                except BaseException as exc:  # noqa: BLE001
                    record["raw_canvas"]["error"] = f"{type(exc).__name__}: {exc}"
            try:
                target_selector = canvas_selector or area_selector
                locator = self.page.locator(target_selector) if target_selector else None
                if locator is not None and await locator.count() == 1:
                    record["rendered_screenshot"]["attempted"] = True
                    path = capture_dir / f"content_{index:03d}_rendered.png"
                    await locator.screenshot(path=str(path), animations="disabled", scale="device")
                    record["rendered_screenshot"].update({"saved": True, "file": str(path.relative_to(self.output_dir))})
                    try:
                        dimensions, pixel_sha = _decoded_pixel_sha256(path)
                        record["rendered_screenshot"].update({"dimensions": dimensions, "pixel_sha256": pixel_sha})
                    except BaseException as exc:  # noqa: BLE001
                        record["rendered_screenshot"]["pixel_error"] = f"{type(exc).__name__}: {exc}"
            except BaseException as exc:  # noqa: BLE001
                record["rendered_screenshot"]["error"] = f"{type(exc).__name__}: {exc}"
            captures.append(record)
        try:
            await self.page.evaluate(
                """({windowY, innerTop}) => {
                    window.scrollTo(0, Number(windowY) || 0);
                    const inner = document.querySelector('.content-inner.scroll-vertical.js-vertical-viewer');
                    if (inner && innerTop !== null && innerTop !== undefined) inner.scrollTop = Number(innerTop) || 0;
                }""",
                {"windowY": original_scroll.get("window_y") or 0, "innerTop": original_scroll.get("inner_top")},
            )
            await self.wait_for_scroll_stability(timeout=4.0)
        except BaseException as exc:  # noqa: BLE001
            self.errors.append(f"content capture scroll restore failed: {type(exc).__name__}: {exc}")

        source_items: list[dict[str, Any]] = []
        try:
            source_items = await self.page.evaluate(
                """() => window.__jumpplusProbe?.captureImageSources?.({}) || []"""
            )
        except BaseException as exc:  # noqa: BLE001
            self.errors.append(f"source capture failed: {type(exc).__name__}: {exc}")
        saved_sources: list[dict[str, Any]] = []
        for item in source_items[:MAX_SOURCES]:
            source_record = {key: value for key, value in item.items() if key != "dataUrl"}
            if item.get("dataUrl"):
                file = self._save_data_url(item["dataUrl"], source_dir / f"source_{len(saved_sources):03d}.png")
                source_record["file"] = file
                if file:
                    try:
                        source_record["decoded_dimensions"], source_record["pixel_sha256"] = _decoded_pixel_sha256(self.output_dir / file)
                    except BaseException as exc:  # noqa: BLE001
                        source_record["pixel_error"] = f"{type(exc).__name__}: {exc}"
            if item.get("error"):
                source_record["error"] = item["error"]
            saved_sources.append(source_record)
        _write_json(self.output_dir / "sources.json", saved_sources)
        result = {
            "requested_count": len(regions),
            "captures": captures,
            "raw_canvas_success_count": sum(bool(item["raw_canvas"].get("saved")) for item in captures),
            "rendered_screenshot_success_count": sum(bool(item["rendered_screenshot"].get("saved")) for item in captures),
            "source_count": len(saved_sources),
            "sources": saved_sources,
        }
        _write_json(self.output_dir / "content_captures.json", result)
        return result

    async def perform_operation(self, operation: str, amount: int, target_index: int | None) -> dict[str, Any]:
        if operation == "ArrowDown":
            await self.page.keyboard.press("ArrowDown")
            return {"method": "keyboard", "key": "ArrowDown"}
        if operation == "PageDown":
            await self.page.keyboard.press("PageDown")
            return {"method": "keyboard", "key": "PageDown"}
        if operation == "Space":
            await self.page.keyboard.press("Space")
            return {"method": "keyboard", "key": "Space"}
        if operation == "End":
            await self.page.keyboard.press("End")
            return {"method": "keyboard", "key": "End", "limited": True}
        if operation == "wheel":
            await self.page.mouse.wheel(0, amount)
            return {"method": "mouse.wheel", "delta_y": amount}
        result = await self.page.evaluate(
            _VERTICAL_SCROLL_ACTION_SCRIPT,
            {"operation": operation, "amount": amount, "targetIndex": target_index},
        )
        return {"method": "dom", "amount": amount, "target_index": target_index, "result": result}

    async def run_case(self, operation: str, case_index: int, amount: int) -> dict[str, Any]:
        case_dir = self.output_dir / "operations" / f"{case_index:02d}_{operation}"
        case_dir.mkdir(parents=True, exist_ok=True)
        try:
            await self.page.goto(self.target_url, wait_until="domcontentloaded", timeout=30_000)
        except BaseException as exc:  # noqa: BLE001
            self.errors.append(f"{operation} goto failed: {type(exc).__name__}: {exc}")
        await self.wait_for_stability(timeout=10.0)
        await self.wait_for_scroll_stability(timeout=5.0)
        before = await self.collect_vertical_snapshot(
            f"operations/{case_index:02d}_{operation}/before",
            include_html=case_index == 1,
        )
        regions = [
            item for item in before.get("dom", {}).get("regions", [])
            if item.get("isContentPage")
        ]
        active_before = _active_indices(before.get("dom", {}))
        target_index = max(active_before) + 1 if active_before and max(active_before) + 1 < len(regions) else None
        event_start = len(self.network_events)
        saved_start = len(self.saved_images)
        operation_detail: dict[str, Any]
        status = "observed"
        error = None
        try:
            operation_detail = await self.perform_operation(operation, amount, target_index)
            stable = await self.wait_for_scroll_stability()
        except BaseException as exc:  # noqa: BLE001
            operation_detail = {"method": "failed"}
            stable = False
            status = "error"
            error = f"{type(exc).__name__}: {exc}"
        after = await self.collect_vertical_snapshot(f"operations/{case_index:02d}_{operation}/after", include_html=False)
        if not is_target_episode_url(after.get("url", self.page.url), self.expected_episode_id):
            status = "safety_stop"
            self.stopped_reason = "target episode URL changed during vertical operation"
        active_after = _active_indices(after.get("dom", {}))
        record = {
            "operation": operation,
            "status": status,
            "error": error,
            "stable": bool(stable),
            "before_scroll": scroll_position(before.get("dom", {})),
            "after_scroll": scroll_position(after.get("dom", {})),
            "scroll_delta": scroll_delta(before.get("dom", {}), after.get("dom", {})),
            "viewport_height": (before.get("dom", {}).get("viewport") or {}).get("height"),
            "active_before": active_before,
            "active_after": active_after,
            "active_before_count": len(active_before),
            "active_after_count": len(active_after),
            "target_index": target_index,
            "next_content_reached": next_content_reached(before.get("dom", {}), after.get("dom", {})),
            "operation_detail": operation_detail,
            "new_network_event_count": len(self.network_events) - event_start,
            "new_saved_image_count": len(self.saved_images) - saved_start,
            "new_image_response_urls": [
                event.get("url") for event in self.network_events[event_start:]
                if event.get("event") == "response" and event.get("classification") == "image"
            ],
            "page_count_before": len(regions),
            "page_count_after": sum(
                bool(item.get("isContentPage"))
                for item in after.get("dom", {}).get("regions", [])
            ),
            "loaded_content_before": loaded_content_count(before.get("dom", {})),
            "loaded_content_after": loaded_content_count(after.get("dom", {})),
            "new_content_loaded_count": max(
                0,
                loaded_content_count(after.get("dom", {}))
                - loaded_content_count(before.get("dom", {})),
            ),
            "geometry_order_before": geometry_order(before.get("dom", {})),
            "geometry_order_after": geometry_order(after.get("dom", {})),
            "before_directory": str(Path(before["directory"]).relative_to(self.output_dir)),
            "after_directory": str(Path(after["directory"]).relative_to(self.output_dir)),
        }
        _write_json(case_dir / "navigation.json", record)
        return record

    async def run(self, url: str, operations: list[str], scroll_delta_value: int | None) -> dict[str, Any]:
        self.target_url = url
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.install_listeners()
        await self.page.add_init_script(script=_DRAW_HOOK)
        amount = scroll_delta_value
        first_snapshot: dict[str, Any] | None = None
        content_capture: dict[str, Any] | None = None
        operation_records: list[dict[str, Any]] = []
        for case_index, operation in enumerate(operations, start=1):
            record = await self.run_case(operation, case_index, amount or 1)
            operation_records.append(record)
            if first_snapshot is None:
                first_path = self.output_dir / record["before_directory"]
                try:
                    first_dom = json.loads((first_path / "dom.json").read_text(encoding="utf-8"))
                    first_draw = json.loads((first_path / "draw_calls.json").read_text(encoding="utf-8"))
                    first_snapshot = {"dom": first_dom, "draw": first_draw}
                except (OSError, json.JSONDecodeError):
                    first_snapshot = None
                if first_snapshot:
                    initial_dir = self.output_dir / "initial"
                    initial_dir.mkdir(parents=True, exist_ok=True)
                    for name in (
                        "dom.json",
                        "network.json",
                        "draw_calls.json",
                        "scripts.json",
                        "links.json",
                        "page.html",
                        "screenshot.png",
                    ):
                        source = first_path / name
                        if source.exists():
                            shutil.copyfile(source, initial_dir / name)
                    # The first case's before state is fresh and is sufficient
                    # for the bounded per-content capture experiment.
                    content_capture = await self.capture_content_images(first_snapshot)
            if amount is None:
                viewport_height = operation_records[-1].get("viewport_height") or 800
                amount = max(1, round(float(viewport_height) * 0.9))
            if self.stopped_reason:
                break
        await self.drain_image_tasks()
        report = {
            "target_url": url,
            "target_episode_id": self.expected_episode_id,
            "final_url": self.page.url,
            "operations_requested": operations,
            "operations_observed": len(operation_records),
            "operations": operation_records,
            "content_capture": content_capture,
            "saved_network_images": self.saved_images,
            "network_event_count": len(self.network_events),
            "viewer": self._viewer_summary(first_snapshot),
            "capture_assessment": self._capture_assessment(first_snapshot, content_capture),
            "navigation_recommendation": recommend_navigation(operation_records),
            "stopped_reason": self.stopped_reason,
            "errors": self.errors,
        }
        _write_json(self.output_dir / "report.json", report)
        _write_json(self.output_dir / "navigation.json", {"operations": operation_records})
        _write_json(self.output_dir / "network.json", {"events": self.network_events, "saved_images": self.saved_images})
        _write_json(self.output_dir / "candidate_images.json", self.saved_images)
        _write_text(self.output_dir / "summary.md", self.make_vertical_summary(report))
        return report

    def _viewer_summary(self, snapshot: dict[str, Any] | None) -> dict[str, Any]:
        dom = (snapshot or {}).get("dom", {})
        return {
            "title": dom.get("title"),
            "viewer": dom.get("viewer"),
            "content": dom.get("content"),
            "inner": dom.get("inner"),
            "container": dom.get("container"),
            "page_count": dom.get("pageCount"),
            "geometry_order": geometry_order(dom),
            "initial_active_regions": dom.get("activeRegions", []),
            "initial_scroll": scroll_position(dom),
            "region_dimensions": [
                {"index": row.get("index"), "width": (row.get("image") or {}).get("width"), "height": (row.get("image") or {}).get("height")}
                for row in dom.get("regions", [])
                if row.get("isContentPage")
            ],
        }

    def _capture_assessment(self, snapshot: dict[str, Any] | None, captures: dict[str, Any] | None) -> dict[str, Any]:
        dom = (snapshot or {}).get("dom", {})
        regions = [item for item in dom.get("regions", []) if item.get("isContentPage")]
        draws = (snapshot or {}).get("draw", {}).get("drawCalls", [])
        canvas_ids = {row.get("image", {}).get("canvasId") for row in regions}
        content_draws = [row for row in draws if (row.get("canvas") or {}).get("id") in canvas_ids]
        partial_draws = [row for row in content_draws if row.get("sourceRect") and (
            row["sourceRect"].get("sx") != 0 or row["sourceRect"].get("sy") != 0
            or row["sourceRect"].get("sw") != (row.get("source", {}).get("naturalWidth"))
            or row["sourceRect"].get("sh") != (row.get("source", {}).get("naturalHeight"))
        )]
        return {
            "network_transport_candidates": len(self.saved_images),
            "transport_candidate_formats": sorted({item.get("image_format") for item in self.saved_images if item.get("image_format")}),
            "transport_candidate_dimensions": sorted({tuple(item.get("dimensions", [])) for item in self.saved_images if item.get("dimensions")} ),
            "content_region_count": len(regions),
            "content_draw_call_count": len(content_draws),
            "partial_source_rect_count": len(partial_draws),
            "draw_mapping": "partial source rectangles observed; tile/reconstruction is possible" if partial_draws else (
                "full-frame draw observed" if content_draws else "unknown"
            ),
            "raw_canvas_capture": {
                "status": "confirmed" if (captures or {}).get("raw_canvas_success_count") == len(regions) and regions else "partial_or_rejected",
                "success_count": (captures or {}).get("raw_canvas_success_count", 0),
            },
            "rendered_content_capture": {
                "status": "confirmed" if (captures or {}).get("rendered_screenshot_success_count") == len(regions) and regions else "partial_or_rejected",
                "success_count": (captures or {}).get("rendered_screenshot_success_count", 0),
            },
            "direct_original_bytes_as_page": "not established by J0; response bytes are diagnostic candidates",
        }

    def make_vertical_summary(self, report: dict[str, Any]) -> str:
        viewer = report.get("viewer") or {}
        assessment = report.get("capture_assessment") or {}
        recommendation = report.get("navigation_recommendation") or {}
        lines = [
            "# Jump+ Vertical J0 probe summary",
            "",
            "## Target",
            "",
            f"- URL: `{report['target_url']}`",
            f"- episode ID: `{report['target_episode_id']}`",
            f"- final URL: `{report['final_url']}`",
            f"- safety stop: `{report.get('stopped_reason') or 'none'}`",
            "",
            "## Vertical viewer structure",
            "",
            f"- title: `{viewer.get('title')}`",
            f"- content page-area count: `{viewer.get('page_count')}`",
            f"- initial active regions: `{viewer.get('initial_active_regions')}`",
            f"- geometry order: `{viewer.get('geometry_order')}`",
            f"- initial scroll: `{json.dumps(viewer.get('initial_scroll'), ensure_ascii=False)}`",
            f"- region dimensions: `{json.dumps(viewer.get('region_dimensions'), ensure_ascii=False)}`",
            "",
            "## Capture observations",
            "",
            f"- transport JPEG candidates: `{assessment.get('network_transport_candidates', 0)}`",
            f"- transport dimensions: `{assessment.get('transport_candidate_dimensions')}`",
            f"- content draw calls: `{assessment.get('content_draw_call_count', 0)}`",
            f"- partial source rectangles: `{assessment.get('partial_source_rect_count', 0)}`",
            f"- mapping: `{assessment.get('draw_mapping')}`",
            f"- raw canvas capture: `{assessment.get('raw_canvas_capture')}`",
            f"- rendered content capture: `{assessment.get('rendered_content_capture')}`",
            f"- direct original bytes as page: `{assessment.get('direct_original_bytes_as_page')}`",
            "",
            "## Navigation observations",
            "",
        ]
        for item in report.get("operations", []):
            lines.append(
                f"- `{item.get('operation')}`: status=`{item.get('status')}`, stable=`{item.get('stable')}`, "
                f"delta=`{json.dumps(item.get('scroll_delta'), ensure_ascii=False)}`, "
                f"active=`{item.get('active_before')} -> {item.get('active_after')}`, "
                f"next_content=`{item.get('next_content_reached')}`, "
                f"new_images=`{item.get('new_saved_image_count')}`"
            )
        lines.extend(
            [
                "",
                "## Recommended navigation",
                "",
                f"- primary: `{recommendation.get('primary')}`",
                f"- fallback: `{recommendation.get('fallback')}`",
                f"- do not use as one-page semantics: `{recommendation.get('do_not_use')}`",
                f"- rationale: {recommendation.get('reason')}",
                "",
                "## Artifacts",
                "",
                "- `report.json`, `navigation.json`, `network.json`, `candidate_images.json`",
                "- `initial/` and `operations/` contain DOM, draw, network, and viewport screenshots",
                "- `content_captures.json` and `content_captures/` contain bounded per-content capture attempts",
                "- `sources.json` and `sources/` contain bounded source snapshot attempts",
                "",
                "## Unknowns",
                "",
                "- A single operation per fresh state does not establish a production-level page-turn contract.",
                "- Direct JPEG bytes are not treated as final pages without source/draw/render equivalence.",
                "- No purchase, rental, login, access grant, next-episode, full crawl, or ZIP operation was attempted.",
                f"- probe errors: `{json.dumps(report.get('errors', []), ensure_ascii=False)}`",
            ]
        )
        return "\n".join(lines) + "\n"


async def run_probe(
    url: str,
    output_dir: Path,
    operations: list[str],
    cdp_endpoint: str | None,
    scroll_delta_value: int | None,
) -> dict[str, Any]:
    expected_episode_id = extract_episode_id(url)
    if expected_episode_id is None:
        raise ValueError("--url must be a Jump+ URL of the form /episode/<numeric-id>")
    endpoint = resolve_cdp_endpoint(cli_endpoint=cdp_endpoint)
    session = await BrowserSession.connect(endpoint)
    page = await session.new_page()
    probe = VerticalProbe(page=page, output_dir=output_dir, expected_episode_id=expected_episode_id)
    try:
        return await probe.run(url, operations, scroll_delta_value)
    finally:
        await session.close_page(page)
        await session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only Shonen Jump+ vertical J0 viewer probe")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--operations", default=",".join(DEFAULT_OPERATIONS), help="comma-separated bounded operations")
    parser.add_argument("--scroll-delta", type=int, default=None, help="fixed delta for wheel/DOM scroll; default is 90%% of viewport height")
    parser.add_argument("--cdp-endpoint", default=None)
    args = parser.parse_args()
    raw_operations = [item.strip() for item in str(args.operations).split(",") if item.strip()]
    operations = []
    for raw in raw_operations[:MAX_OPERATIONS]:
        operations.append(operation_key(raw))
    report = asyncio.run(run_probe(args.url, args.output_dir, operations, args.cdp_endpoint, args.scroll_delta))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
