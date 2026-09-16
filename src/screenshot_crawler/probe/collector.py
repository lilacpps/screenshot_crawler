"""Probe collector helpers.

Expected v1 outputs:
- screenshot
- HTML
- URL/title/viewport
- visible image metadata
- canvas metadata
- button candidates
- background-image candidates

Do not attempt full automatic viewer/next-button inference in v1.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page

from screenshot_crawler.core.browser import create_browser_context
from screenshot_crawler.probe.models import ProbeResult

_COLLECT_SCRIPT = r"""
() => {
  const visible = (element) => {
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      Number(style.opacity) !== 0 && rect.width > 0 && rect.height > 0;
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
  const box = (element) => {
    const rect = element.getBoundingClientRect();
    return {x: rect.x, y: rect.y, width: rect.width, height: rect.height};
  };
  const visibleElements = (selectorText) =>
    Array.from(document.querySelectorAll(selectorText)).filter(visible);

  const images = visibleElements("img").map((element) => ({
    src: element.currentSrc || element.src || null,
    naturalWidth: element.naturalWidth,
    naturalHeight: element.naturalHeight,
    box: box(element),
    selector: selector(element),
  }));
  const canvases = visibleElements("canvas").map((element) => ({
    width: element.width,
    height: element.height,
    box: box(element),
    selector: selector(element),
  }));
  const buttons = visibleElements("button, [role='button'], a, [onclick], input[type='button'], input[type='submit']")
    .map((element) => ({
      text: (element.innerText || element.value || "").trim().slice(0, 300),
      ariaLabel: element.getAttribute("aria-label"),
      title: element.getAttribute("title"),
      role: element.getAttribute("role") || element.tagName.toLowerCase(),
      box: box(element),
      selector: selector(element),
    }));
  const backgrounds = visibleElements("*").map((element) => {
    const image = getComputedStyle(element).backgroundImage;
    return {element, image};
  }).filter(({image}) => image && image !== "none").map(({element, image}) => ({
    backgroundImage: image,
    box: box(element),
    selector: selector(element),
  }));
  return {
    viewport: {width: innerWidth, height: innerHeight},
    visibleImages: images,
    canvases,
    buttons,
    backgrounds,
    visibleText: (document.body?.innerText || "").trim().slice(0, 10000),
  };
}
"""


async def create_probe_context(
    browser: Browser,
    *,
    site: str | None = None,
    auth_state: str | Path | None = None,
    auth_required: bool = False,
    auth_dir: str | Path = Path(".auth"),
    **context_options: Any,
) -> BrowserContext:
    """Create a probe context with the same optional auth reuse as Core."""

    return await create_browser_context(
        browser,
        site=site,
        auth_state=auth_state,
        auth_required=auth_required,
        auth_dir=auth_dir,
        **context_options,
    )


class ProbeCollector:
    """Collect observations without trying to infer viewer behavior."""

    async def collect(self, page: Page, output_dir: str | Path) -> ProbeResult:
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        errors: list[str] = []
        try:
            details = await asyncio.wait_for(page.evaluate(_COLLECT_SCRIPT), timeout=10)
        except BaseException as exc:  # noqa: BLE001
            details = {
                "viewport": {"width": 0, "height": 0},
                "visibleImages": [],
                "canvases": [],
                "buttons": [],
                "backgrounds": [],
                "visibleText": "",
            }
            errors.append(f"DOM collection failed: {type(exc).__name__}: {exc}")
        try:
            title = await asyncio.wait_for(page.title(), timeout=5)
        except BaseException as exc:  # noqa: BLE001
            title = ""
            errors.append(f"Title collection failed: {type(exc).__name__}: {exc}")
        result = ProbeResult(
            url=page.url,
            title=title,
            viewport=details["viewport"],
            visible_images=details["visibleImages"],
            canvases=details["canvases"],
            buttons=details["buttons"],
            background_images=details["backgrounds"],
            visible_text=details["visibleText"],
            errors=errors,
        )
        try:
            await asyncio.wait_for(
                page.screenshot(path=str(directory / "screenshot.png"), full_page=False),
                timeout=10,
            )
        except BaseException as exc:  # noqa: BLE001
            errors.append(f"Screenshot failed: {type(exc).__name__}: {exc}")
        try:
            html = await asyncio.wait_for(page.content(), timeout=10)
            (directory / "page.html").write_text(html, encoding="utf-8")
        except BaseException as exc:  # noqa: BLE001
            errors.append(f"HTML collection failed: {type(exc).__name__}: {exc}")
        result.errors = errors
        (directory / "probe.json").write_text(
            json.dumps(result.as_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return result


async def collect_probe(page: Page, output_dir: str | Path) -> ProbeResult:
    """Functional entry point for one currently-open page."""

    return await ProbeCollector().collect(page, output_dir)
