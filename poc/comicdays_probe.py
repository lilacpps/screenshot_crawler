"""Bounded, read-only Comic DAYS reconnaissance probe.

This helper attaches to the shared Crawler Chrome through :class:`BrowserSession`
and records redacted metadata only.  It never clicks purchase, ticket, point,
coin, login, or next-episode controls.  It writes one diagnostic screenshot
under ``output/``; this is not a repository fixture.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from screenshot_crawler.core.browser import BrowserSession, resolve_cdp_endpoint

DEFAULT_URL = "https://comic-days.com/episode/2550689798754939004"
DEFAULT_OUTPUT_DIR = Path("output/comicdays_probe")
MAX_TEXT = 1200
MAX_ITEMS = 150
MAX_API_BODY_RECORDS = 10
FETCH_TIMEOUT_MS = 5_000
FETCH_EVALUATE_TIMEOUT_SECONDS = 8
EVALUATE_TIMEOUT_SECONDS = 8
RESPONSE_BODY_TIMEOUT_SECONDS = 2
PROBE_TIMEOUT_SECONDS = 60
FIRST_PARTY_API_PATHS = {
    "/my.json",
    "/api/viewer/readable_product_pagination_information",
}


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def redact_url(value: str | None) -> str | None:
    """Keep URL identity without retaining query/hash tokens or signed URLs."""

    if not value:
        return None
    parsed = urlsplit(value)
    sanitized = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    # Gigaviewer URLs embed the original CDN URL in the path with an encoded
    # query. Keep the route identity but remove the embedded cache/signature.
    return re.sub(r"(?i)%3f[^/\\s\"'<>]*$", "%3F[redacted]", sanitized)


def short_text(value: Any, limit: int = MAX_TEXT) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def redact_embedded_urls(value: str) -> str:
    """Remove query/hash portions from URLs embedded in DOM attribute strings."""

    return re.sub(
        r"https?://[^\s\"'<>]+",
        lambda match: redact_url(match.group(0)) or "[url]",
        value,
    )


async def evaluate_bounded(page: Any, expression: str, *, timeout_seconds: float) -> Any:
    """Evaluate page JavaScript with a Python-side cancellation deadline."""

    return await asyncio.wait_for(
        page.evaluate(expression),
        timeout=timeout_seconds,
    )


def bounded_fetch_expression(body_expression: str) -> str:
    """Build a fetch expression with an AbortController and body timeout."""

    return f"""async () => {{
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), {FETCH_TIMEOUT_MS});
      try {{
        {body_expression}
      }} finally {{
        clearTimeout(timer);
      }}
    }}"""


async def page_metadata(
    page: Any, *, timeout_seconds: float = EVALUATE_TIMEOUT_SECONDS
) -> dict[str, Any]:
    return await evaluate_bounded(
        page,
        """() => {
          const visible = element => {
            if (!element) return false;
            const rect = element.getBoundingClientRect();
            const style = getComputedStyle(element);
            return rect.width > 0 && rect.height > 0 &&
              style.display !== 'none' && style.visibility !== 'hidden';
          };
          const inViewport = element => {
            if (!visible(element)) return false;
            const value = element.getBoundingClientRect();
            return value.bottom > 0 && value.right > 0 && value.left < innerWidth && value.top < innerHeight;
          };
          const rect = element => {
            const value = element.getBoundingClientRect();
            return {x: value.x, y: value.y, width: value.width, height: value.height};
          };
          const attrs = element => Object.fromEntries(
            [...element.attributes].map(attr => [attr.name, attr.value])
          );
          const visibleElements = selector => [...document.querySelectorAll(selector)]
            .filter(visible).slice(0, 250).map(element => ({
              tag: element.tagName.toLowerCase(),
              id: element.id || null,
              class: element.getAttribute('class'),
              role: element.getAttribute('role'),
              aria_label: element.getAttribute('aria-label'),
              title: element.getAttribute('title'),
              text: (element.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 300),
              rect: rect(element),
              attrs: attrs(element),
            }));
          const images = [...document.images].slice(0, 250).map((element, index) => ({
            index,
            src: element.currentSrc || element.src || null,
            srcset: element.srcset || null,
            width: element.naturalWidth,
            height: element.naturalHeight,
            rendered: rect(element),
            visible: visible(element),
            in_viewport: inViewport(element),
            class: element.getAttribute('class'),
            id: element.id || null,
            attrs: attrs(element),
          }));
          const canvases = [...document.querySelectorAll('canvas')].slice(0, 250)
            .map((element, index) => ({
              index,
              width: element.width,
              height: element.height,
              rendered: rect(element),
              visible: visible(element),
              in_viewport: inViewport(element),
              class: element.getAttribute('class'),
              id: element.id || null,
              attrs: attrs(element),
            }));
          const links = [...document.querySelectorAll('a[href]')].slice(0, 250)
            .map(element => ({
              href: element.href,
              text: (element.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 300),
              class: element.getAttribute('class'),
              id: element.id || null,
              visible: visible(element),
              attrs: attrs(element),
            }));
          const buttons = visibleElements('button,[role="button"],input[type="button"],input[type="submit"]');
          const iframes = [...document.querySelectorAll('iframe')].slice(0, 50).map(element => ({
            src: element.src || null, name: element.name || null,
            rect: rect(element), visible: visible(element), attrs: attrs(element),
          }));
          const bodyText = (document.body?.innerText || '').replace(/\\s+/g, ' ').trim();
          const viewerRoots = [...document.querySelectorAll('[class*="viewer"],[id*="viewer"],main')]
            .slice(0, 100).map(element => ({
              tag: element.tagName.toLowerCase(), id: element.id || null,
              class: element.getAttribute('class'), role: element.getAttribute('role'),
              text: (element.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 500),
              rect: rect(element), visible: visible(element), attrs: attrs(element),
              in_viewport: inViewport(element),
              child_count: element.children.length,
            }));
          const scripts = [...document.scripts].map((element, index) => ({
            index, src: element.src || null, type: element.type || null,
            length: (element.textContent || '').length,
            markers: ['readable_product', 'pagination', 'page-image', 'ticket', 'free', 'episode']
              .filter(marker => (element.textContent || '').toLowerCase().includes(marker)),
          }));
          const pageAreas = [...document.querySelectorAll('.page-area.js-page-area')]
            .slice(0, 100).map((element, index) => ({
              index, id: element.id || null, class: element.getAttribute('class'),
              rect: rect(element), visible: visible(element),
              in_viewport: inViewport(element),
              attrs: attrs(element),
              text: (element.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 200),
              children: [...element.children].slice(0, 30).map(child => ({
                tag: child.tagName.toLowerCase(), id: child.id || null,
                class: child.getAttribute('class'), rect: rect(child),
                in_viewport: inViewport(child),
                attrs: attrs(child),
              })),
              canvases: [...element.querySelectorAll('canvas')].map((canvas, canvasIndex) => ({
                canvasIndex, width: canvas.width, height: canvas.height,
                rect: rect(canvas), class: canvas.getAttribute('class'),
                in_viewport: inViewport(canvas),
                attrs: attrs(canvas),
              })),
            }));
          const viewerControls = [...document.querySelectorAll('.js-viewer-forward,[class*="forward"],[class*="backward"],[class*="next"]')]
            .slice(0, 100).map(element => ({
              tag: element.tagName.toLowerCase(), id: element.id || null,
              class: element.getAttribute('class'), role: element.getAttribute('role'),
              text: (element.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 100),
              aria_label: element.getAttribute('aria-label'), title: element.getAttribute('title'),
              rect: rect(element), visible: visible(element), attrs: attrs(element),
            }));
          const listingRoots = [...document.querySelectorAll('[class*="table-of-contents"],[class*="episode-list"],[class*="episode-list"]')]
            .slice(0, 100).map(element => ({
              tag: element.tagName.toLowerCase(), id: element.id || null,
              class: element.getAttribute('class'), text: (element.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 1000),
              rect: rect(element), visible: visible(element), attrs: attrs(element),
              links: [...element.querySelectorAll('a[href]')].slice(0, 100).map(link => ({
                href: link.href, text: (link.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 200),
                class: link.getAttribute('class'), visible: visible(link), attrs: attrs(link),
              })),
            }));
          return {
            url: location.href,
            title: document.title,
            body_text: bodyText.slice(0, 5000),
            html_length: document.documentElement?.outerHTML?.length || 0,
            scroll: {x: scrollX, y: scrollY, width: innerWidth, height: innerHeight,
              body_height: document.body?.scrollHeight || 0,
              document_height: document.documentElement?.scrollHeight || 0},
            images, canvases, links, buttons, iframes,
            viewer_roots: viewerRoots, scripts, page_areas: pageAreas, viewer_controls: viewerControls,
            listing_roots: listingRoots,
            visible_headings: visibleElements('h1,h2,h3,[role="heading"]'),
            visible_text_controls: visibleElements('a,button,[role="button"]'),
          };
        }""",
        timeout_seconds=timeout_seconds,
    )


async def redact_metadata(value: dict[str, Any]) -> dict[str, Any]:
    """Redact URL query strings and image body data before writing evidence."""

    def visit(item: Any, key: str | None = None) -> Any:
        if isinstance(item, dict):
            return {name: visit(child, name) for name, child in item.items()}
        if isinstance(item, list):
            return [visit(child, key) for child in item]
        if isinstance(item, str) and key in {"body_text", "text", "title"}:
            return short_text(item, 5000 if key == "body_text" else 500)
        if isinstance(item, str) and key in {"url", "src", "href", "currentSrc", "srcset"}:
            return redact_url(item)
        if isinstance(item, str):
            return redact_embedded_urls(item)
        return item

    return visit(value)


async def navigation_snapshot(
    page: Any, *, timeout_seconds: float = EVALUATE_TIMEOUT_SECONDS
) -> dict[str, Any]:
    return await evaluate_bounded(
        page,
        """() => {
          const visible = element => {
            if (!element) return false;
            const rect = element.getBoundingClientRect();
            const style = getComputedStyle(element);
            return rect.width > 0 && rect.height > 0 && style.display !== 'none' &&
              style.visibility !== 'hidden';
          };
          const rect = element => {
            const value = element.getBoundingClientRect();
            return {x: value.x, y: value.y, width: value.width, height: value.height};
          };
          const now = document.querySelector('.js-viewer-slider-pagenum-now')?.textContent?.trim() || null;
          const last = document.querySelector('.js-viewer-slider-pagenum-last')?.textContent?.trim() || null;
          const canvases = [...document.querySelectorAll('canvas.page-image.js-page-image')];
          return {
            url: location.href, now, last,
            horizontal_scroll_left: document.querySelector('.js-horizontal-viewer')?.scrollLeft ?? null,
            container_right: document.querySelector('.image-container.js-viewer-content')?.style.right || null,
            loaded_canvas_count: canvases.length,
            loaded_canvases: canvases.map((canvas, index) => ({
              index, width: canvas.width, height: canvas.height,
              rect: rect(canvas), visible: visible(canvas),
            })),
            forward_visible: visible(document.querySelector('.js-slide-forward')),
            backward_visible: visible(document.querySelector('.js-slide-backward')),
            next_episode_visible: visible(document.querySelector('.js-viewer-colophon-next-episode')),
          };
        }""",
        timeout_seconds=timeout_seconds,
    )


def resource_metadata(resources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for item in resources[:MAX_ITEMS]:
        url = str(item.get("url") or "")
        safe = redact_url(url) or ""
        parsed = urlsplit(safe)
        result.append(
            {
                "resource_type": item.get("type"),
                "url": redact_url(url),
                "host": parsed.netloc,
                "path": parsed.path,
                "query_key_count": len([part for part in parsed.query.split("&") if part]),
                "status": item.get("status"),
                "mime_type": item.get("mime_type"),
            }
        )
    return result


def summarize_api_payload(value: Any, *, depth: int = 0) -> Any:
    """Retain shape and scalar metadata, never raw signed URLs or tokens."""

    if depth > 5:
        return {"type": type(value).__name__}
    if isinstance(value, dict):
        return {
            str(key): summarize_api_payload(child, depth=depth + 1)
            for key, child in list(value.items())[:100]
            if str(key).lower() not in {"token", "signature", "signed_url", "url", "src", "image"}
        }
    if isinstance(value, list):
        return [summarize_api_payload(child, depth=depth + 1) for child in value[:100]]
    if isinstance(value, str):
        return {"type": "str", "length": len(value), "sha256": __import__("hashlib").sha256(value.encode()).hexdigest()}
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return {"type": type(value).__name__}


async def _run_probe(
    url: str,
    output_dir: Path,
    cdp_endpoint: str | None,
    *,
    snapshot_only: bool = False,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    session = await BrowserSession.connect(resolve_cdp_endpoint(cli_endpoint=cdp_endpoint))
    page = await session.new_page()
    resources: list[dict[str, Any]] = []
    api_bodies: list[dict[str, Any]] = []
    resource_count = 0

    async def on_response(response: Any) -> None:
        nonlocal resource_count
        request = response.request
        resource_count += 1
        if len(resources) < MAX_ITEMS:
            resources.append(
                {
                    "type": request.resource_type,
                    "url": response.url,
                    "status": response.status,
                    "mime_type": response.headers.get("content-type", "").split(";", 1)[0],
                }
            )
        parsed_url = urlsplit(response.url)
        if (
            len(api_bodies) < MAX_API_BODY_RECORDS
            and parsed_url.netloc == "comic-days.com"
            and parsed_url.path in FIRST_PARTY_API_PATHS
        ):
            try:
                body = await asyncio.wait_for(
                    response.body(), timeout=RESPONSE_BODY_TIMEOUT_SECONDS
                )
                if len(body) <= 500_000:
                    try:
                        parsed = json.loads(body.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        parsed = None
                    api_bodies.append(
                        {
                            "url": redact_url(response.url),
                            "status": response.status,
                            "mime_type": response.headers.get("content-type", "").split(";", 1)[0],
                            "body_length": len(body),
                            "body_sha256": hashlib.sha256(body).hexdigest(),
                            "json_summary": summarize_api_payload(parsed) if parsed is not None else None,
                        }
                    )
            except (Exception, asyncio.CancelledError):  # noqa: BLE001 - probe must continue
                return

    page.on("response", on_response)
    started = datetime.now(UTC).isoformat()
    try:
        await page.goto(url, wait_until="commit", timeout=30_000)
        await page.wait_for_timeout(5_000)
        snapshots = []
        for label in ("after_5s", "after_10s"):
            if label == "after_10s":
                await page.wait_for_timeout(5_000)
            metadata = await page_metadata(page)
            metadata["label"] = label
            metadata["timestamp"] = datetime.now(UTC).isoformat()
            snapshots.append(await redact_metadata(metadata))
            if snapshot_only:
                break
        endpoint_data: dict[str, Any] = {}
        try:
            episode_json = await evaluate_bounded(
                page,
                bounded_fetch_expression(
                    """const endpoint = document.querySelector('.viewer.js-viewer')?.dataset.jsonUrl;
        if (!endpoint) return {endpoint: null};
        try {
          const response = await fetch(endpoint, {credentials: 'include', signal: controller.signal});
          const body = await response.text();
          let parsed = null;
          try { parsed = JSON.parse(body); } catch (_) {}
          return {endpoint, status: response.status, content_type: response.headers.get('content-type'),
            body_length: body.length, body_sha256_input: body, parsed};
        } catch (error) {
          return {endpoint, error: {name: error?.name || 'Error', message: String(error?.message || error)}};
        }"""
                ),
                timeout_seconds=FETCH_EVALUATE_TIMEOUT_SECONDS,
            )
            raw_endpoint_body = episode_json.pop("body_sha256_input", None)
            parsed_endpoint = episode_json.pop("parsed", None)
            endpoint_data = {
                **episode_json,
                "endpoint": redact_url(episode_json.get("endpoint")),
                "body_sha256": __import__("hashlib").sha256(raw_endpoint_body.encode()).hexdigest()
                if isinstance(raw_endpoint_body, str)
                else None,
                "json_summary": summarize_api_payload(parsed_endpoint)
                if parsed_endpoint is not None
                else None,
            }
        except Exception as exc:  # noqa: BLE001 - preserve bounded probe evidence
            endpoint_data = {"error": f"{type(exc).__name__}: {exc}"}
        listing_feed: dict[str, Any] = {}
        try:
            listing_feed = await evaluate_bounded(
                page,
                bounded_fetch_expression(
                    """const rss = document.querySelector('a[href*="/rss/series/"]')?.href || null;
        if (!rss) return {rss: null};
        const atom = rss.replace('/rss/series/', '/atom/series/');
        try {
          const response = await fetch(atom, {credentials: 'include', signal: controller.signal});
          const body = await response.text();
          const xml = new DOMParser().parseFromString(body, 'application/xml');
          const entries = [...xml.querySelectorAll('entry')].slice(0, 200).map(entry => ({
            id: entry.querySelector('id')?.textContent?.trim() || null,
            title: entry.querySelector('title')?.textContent?.trim() || null,
            link: entry.querySelector('link')?.getAttribute('href') || null,
            published: entry.querySelector('published')?.textContent?.trim() || null,
            updated: entry.querySelector('updated')?.textContent?.trim() || null,
            categories: [...entry.querySelectorAll('category')].map(node => ({
              term: node.getAttribute('term'), label: node.getAttribute('label'),
            })),
            summary_length: (entry.querySelector('summary')?.textContent || '').length,
          }));
          return {rss, atom, status: response.status, content_type: response.headers.get('content-type'),
            body_length: body.length, entry_count: entries.length, entries};
        } catch (error) {
          return {rss, atom, error: {name: error?.name || 'Error', message: String(error?.message || error)}};
        }"""
                ),
                timeout_seconds=FETCH_EVALUATE_TIMEOUT_SECONDS,
            )
            listing_feed = await redact_metadata(listing_feed)
        except Exception as exc:  # noqa: BLE001 - preserve bounded probe evidence
            listing_feed = {"error": f"{type(exc).__name__}: {exc}"}
        navigation: list[dict[str, Any]] = []
        forward = page.locator(".js-slide-forward")
        for step in range(0 if snapshot_only else 50):
            before = await navigation_snapshot(page)
            navigation.append({"step": step, "event": "before", "state": await redact_metadata(before)})
            if not before.get("forward_visible"):
                break
            try:
                await forward.click(timeout=2_000)
                await page.wait_for_timeout(350)
            except Exception as exc:  # noqa: BLE001 - preserve bounded probe evidence
                navigation.append({"step": step, "event": "click_error", "error": type(exc).__name__})
                break
            after = await navigation_snapshot(page)
            navigation.append({"step": step, "event": "after", "state": await redact_metadata(after)})
            if after.get("next_episode_visible") or after.get("now") == before.get("now") == before.get("last"):
                break
        report = {
            "probe": "comicdays_probe",
            "started_at": started,
            "finished_at": datetime.now(UTC).isoformat(),
            "target_url": redact_url(url),
            "final_url": redact_url(page.url),
            "snapshots": snapshots,
            "resources": resource_metadata(resources),
            "resource_count": resource_count,
            "api_bodies": api_bodies,
            "episode_json": endpoint_data,
            "listing_feed": listing_feed,
            "navigation": navigation,
        }
        write_json(output_dir / "report.json", report)
        await page.screenshot(path=str(output_dir / "viewer.png"), full_page=False)
    finally:
        await session.close_page(page)
        await session.close()


async def run_probe(
    url: str,
    output_dir: Path,
    cdp_endpoint: str | None,
    *,
    snapshot_only: bool = False,
) -> None:
    """Run the probe with an outer deadline that still enters cleanup finally blocks."""

    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            await _run_probe(
                url,
                output_dir,
                cdp_endpoint,
                snapshot_only=snapshot_only,
            )
    except TimeoutError:
        write_json(
            output_dir / "report.json",
            {
                "probe": "comicdays_probe",
                "target_url": redact_url(url),
                "error": {
                    "type": "ProbeTimeout",
                    "timeout_seconds": PROBE_TIMEOUT_SECONDS,
                },
            },
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--cdp-endpoint")
    parser.add_argument("--snapshot-only", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(
        run_probe(
            args.url,
            args.output_dir,
            args.cdp_endpoint,
            snapshot_only=args.snapshot_only,
        )
    )
