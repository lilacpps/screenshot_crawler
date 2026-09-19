"""Diagnostic-only Manga ONE source/native-resolution investigation.

This script does not change crawler production behavior.  It attaches to the
shared Crawler Chrome over CDP, uses only the direct chapter viewer path, and
fails closed when a free-life/quota entry is the only way to reach the reader.
It records DOM image metrics, current locator screenshots, fetched source
bytes, and native-size PNGs for a small page sample.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import mimetypes
import re
import struct
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from playwright.async_api import Locator, Page, async_playwright

from screenshot_crawler.core.capture import capture_locator
from screenshot_crawler.site_adapters.mangaone.adapter import MangaOneAdapter

DEFAULT_URL = "https://manga-one.com/manga/2379/chapter/214131"
PAGE_SELECTOR = '.viewer-container img[alt^="page_"]'
QUOTA_LABEL = "無料ライフで読む"


def image_dimensions(data: bytes) -> tuple[int, int] | None:
    """Decode common raster headers without requiring an image library."""

    if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    if data.startswith(b"\xff\xd8"):
        offset = 2
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
            length = int.from_bytes(data[offset : offset + 2], "big")
            if length < 2 or offset + length > len(data):
                return None
            sof = set(range(0xC0, 0xC4)) | set(range(0xC5, 0xC8))
            sof |= set(range(0xC9, 0xCC)) | set(range(0xCD, 0xD0))
            if marker in sof:
                return (
                    int.from_bytes(data[offset + 5 : offset + 7], "big"),
                    int.from_bytes(data[offset + 3 : offset + 5], "big"),
                )
            offset += length
        return None
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    if data[12:16] == b"VP8X" and len(data) >= 30:
        return (
            1 + int.from_bytes(data[24:27], "little"),
            1 + int.from_bytes(data[27:30], "little"),
        )
    if data[12:16] == b"VP8L" and len(data) >= 25 and data[20] == 0x2F:
        bits = int.from_bytes(data[21:25], "little")
        return ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
    if data[12:16] == b"VP8 " and len(data) >= 30:
        marker = b"\x9d\x01\x2a"
        index = data.find(marker, 20, min(len(data), 64))
        if index >= 0 and index + 7 <= len(data):
            return (
                int.from_bytes(data[index + 3 : index + 5], "little") & 0x3FFF,
                int.from_bytes(data[index + 5 : index + 7], "little") & 0x3FFF,
            )
    return None


def source_kind(value: str | None) -> str | None:
    if not value:
        return None
    if value.startswith("blob:"):
        return "blob"
    if value.startswith("data:"):
        return "data"
    if value.startswith(("https://", "http://")):
        return "http(s)"
    return "other"


def redact_url(value: str | None) -> str | None:
    """Keep origin/path while removing query and fragment values."""

    if not value or not value.startswith(("http://", "https://")):
        return value
    parts = urlsplit(value)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "<redacted>", ""))


def extension_for_mime(mime: str | None) -> str:
    normalized = (mime or "").split(";", 1)[0].lower()
    return {
        "image/webp": ".webp",
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
    }.get(normalized, mimetypes.guess_extension(normalized) or ".bin")


def detected_image_format(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    return None


def extension_for_bytes(data: bytes, mime: str | None) -> str:
    detected = detected_image_format(data)
    return extension_for_mime(detected or mime)


def png_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    return None


async def browser_metrics(page: Page) -> dict[str, Any]:
    return await page.evaluate(
        """() => ({
          devicePixelRatio: window.devicePixelRatio,
          innerWidth: window.innerWidth,
          innerHeight: window.innerHeight,
          outerWidth: window.outerWidth,
          outerHeight: window.outerHeight,
          screenWidth: screen.width,
          screenHeight: screen.height,
          screenAvailWidth: screen.availWidth,
          screenAvailHeight: screen.availHeight,
        })"""
    )


async def controls_snapshot(page: Page) -> list[dict[str, Any]]:
    return await page.locator("button, [role='button'], img").evaluate_all(
        """(elements) => elements.map(element => {
          const rect = element.getBoundingClientRect();
          const style = getComputedStyle(element);
          return {
            tagName: element.tagName,
            text: (element.innerText || '').trim().slice(0, 80),
            ariaLabel: element.getAttribute('aria-label'),
            title: element.getAttribute('title'),
            alt: element.getAttribute('alt'),
            src: element.getAttribute('src'),
            visible: style.display !== 'none' && style.visibility !== 'hidden' &&
              rect.width > 0 && rect.height > 0,
            width: rect.width,
            height: rect.height,
          };
        }).filter(item => item.visible)"""
    )


async def fullscreen_control_snapshot(page: Page) -> dict[str, Any] | None:
    locator = page.locator('img[alt="full-screen"]')
    if not await locator.count():
        return None
    return await locator.first.evaluate(
        """(img) => {
          const ancestors = [];
          let node = img;
          for (let i = 0; node && i < 5; i++, node = node.parentElement) {
            ancestors.push({
              tagName: node.tagName,
              className: String(node.className || '').slice(0, 160),
              text: (node.innerText || '').trim().slice(0, 100),
              onclick: typeof node.onclick === 'function',
              role: node.getAttribute('role'),
              ariaLabel: node.getAttribute('aria-label'),
            });
          }
          return {ancestors};
        }"""
    )


async def fullscreen_state(page: Page, adapter: MangaOneAdapter) -> dict[str, Any]:
    viewer = page.locator(adapter.viewer_selector)
    viewer_count = await viewer.count()
    return {
        "url": page.url,
        "title": await page.title(),
        "browser": await browser_metrics(page),
        "document_fullscreen": await page.evaluate("() => Boolean(document.fullscreenElement)"),
        "html_class": await page.locator("html").get_attribute("class"),
        "body_class": await page.locator("body").get_attribute("class"),
        "page_rows": await adapter._page_image_rows(page),
        "viewer_count": viewer_count,
        "viewer_box": await viewer.bounding_box() if viewer_count else None,
        "page_selector_count": await page.locator(PAGE_SELECTOR).count(),
        "body_text_preview": (await page.locator("body").inner_text())[:500],
    }


async def dom_image_info(locator: Locator) -> dict[str, Any]:
    return await locator.evaluate(
        """(img) => {
          const rect = img.getBoundingClientRect();
          const style = getComputedStyle(img);
          const picture = img.closest('picture');
          const ancestors = [];
          let node = img.parentElement;
          for (let i = 0; node && i < 3; i++, node = node.parentElement) {
            const nodeStyle = getComputedStyle(node);
            const nodeRect = node.getBoundingClientRect();
            ancestors.push({
              tagName: node.tagName,
              className: String(node.className || '').slice(0, 200),
              overflow: nodeStyle.overflow,
              overflowX: nodeStyle.overflowX,
              overflowY: nodeStyle.overflowY,
              transform: nodeStyle.transform,
              clip: nodeStyle.clip,
              clipPath: nodeStyle.clipPath,
              x: nodeRect.x,
              y: nodeRect.y,
              width: nodeRect.width,
              height: nodeRect.height,
            });
          }
          return {
            alt: img.alt,
            src: img.src,
            currentSrc: img.currentSrc,
            naturalWidth: img.naturalWidth,
            naturalHeight: img.naturalHeight,
            cssWidth: rect.width,
            cssHeight: rect.height,
            clientWidth: img.clientWidth,
            clientHeight: img.clientHeight,
            complete: img.complete,
            srcset: img.srcset || null,
            sizes: img.sizes || null,
            parentTagName: img.parentElement?.tagName || null,
            pictureSources: picture ? [...picture.querySelectorAll('source')].map(source => ({
              srcset: source.srcset || null,
              type: source.type || null,
              media: source.media || null,
              sizes: source.sizes || null,
            })) : [],
            objectFit: style.objectFit,
            objectPosition: style.objectPosition,
            transform: style.transform,
            clipPath: style.clipPath,
            filter: style.filter,
            opacity: style.opacity,
            ancestors,
          };
        }"""
    )


async def fetch_source(locator: Locator) -> dict[str, Any]:
    """Fetch currentSrc inside the page context without logging credentials."""

    return await locator.evaluate(
        """async (img) => {
          const url = img.currentSrc || img.src || '';
          try {
            const response = await fetch(url, {credentials: 'include'});
            const blob = await response.blob();
            const bytes = new Uint8Array(await blob.arrayBuffer());
            let binary = '';
            const chunk = 0x8000;
            for (let i = 0; i < bytes.length; i += chunk) {
              binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
            }
            return {
              ok: response.ok,
              status: response.status,
              url,
              mime: blob.type || response.headers.get('content-type') || null,
              bytes: bytes.length,
              base64: btoa(binary),
            };
          } catch (error) {
            return {ok: false, url, error: String(error)};
          }
        }"""
    )


async def network_image_record(response: Any) -> dict[str, Any] | None:
    """Capture image response bytes for blob-backed DOM images."""

    response_url = response.url.lower()
    is_image_url = ".webp" in response_url or ".jpeg" in response_url or ".jpg" in response_url or ".png" in response_url
    is_manga_source = "/secure/" in response_url or "/webp/" in response_url
    if response.request.resource_type != "image" and not is_image_url and not is_manga_source:
        return None
    try:
        body = await response.body()
    except Exception as error:  # noqa: BLE001
        return {
            "url_redacted": redact_url(response.url),
            "status": response.status,
            "content_type": response.headers.get("content-type"),
            "body_error": str(error),
        }
    return {
        "url_redacted": redact_url(response.url),
        "resource_type": response.request.resource_type,
        "status": response.status,
        "content_type": response.headers.get("content-type"),
        "content_length_header": response.headers.get("content-length"),
        "bytes": len(body),
        "detected_format": detected_image_format(body),
        "decoded_dimensions": image_dimensions(body),
        "body": body,
    }


async def native_png(locator: Locator) -> dict[str, Any]:
    return await locator.evaluate(
        """(img) => {
          try {
            const width = img.naturalWidth;
            const height = img.naturalHeight;
            const canvas = document.createElement('canvas');
            canvas.width = width;
            canvas.height = height;
            const context = canvas.getContext('2d');
            context.drawImage(img, 0, 0, width, height);
            return {ok: true, width, height, dataUrl: canvas.toDataURL('image/png')};
          } catch (error) {
            return {ok: false, error: String(error)};
          }
        }"""
    )


def write_bytes(path: Path, data: bytes) -> dict[str, Any]:
    path.write_bytes(data)
    return {
        "path": str(path),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "png_dimensions": png_dimensions(data),
        "decoded_dimensions": image_dimensions(data),
    }


async def capture_target(
    target: Locator,
    output_dir: Path,
    index: int,
    phase: str,
) -> dict[str, Any]:
    info = await dom_image_info(target)
    current = await capture_locator(target)
    current_path = output_dir / f"{phase}-page-{index:02d}-current.png"
    current_file = write_bytes(current_path, current.data)

    source = await fetch_source(target)
    source_file: dict[str, Any] | None = None
    decoded_dimensions: tuple[int, int] | None = None
    if source.get("base64"):
        source_bytes = base64.b64decode(source["base64"])
        mime = source.get("mime")
        source_path = output_dir / f"{phase}-page-{index:02d}-source{extension_for_mime(mime)}"
        source_file = write_bytes(source_path, source_bytes)
        decoded_dimensions = image_dimensions(source_bytes)

    native = await native_png(target)
    native_file: dict[str, Any] | None = None
    if native.get("dataUrl", "").startswith("data:image/png;base64,"):
        native_bytes = base64.b64decode(native["dataUrl"].split(",", 1)[1])
        native_path = output_dir / f"{phase}-page-{index:02d}-native.png"
        native_file = write_bytes(native_path, native_bytes)

    return {
        "index": index,
        "alt": info.get("alt"),
        "source_kind": source_kind(info.get("currentSrc")),
        "currentSrc_redacted": redact_url(info.get("currentSrc")),
        "naturalWidth": info.get("naturalWidth"),
        "naturalHeight": info.get("naturalHeight"),
        "cssWidth": info.get("cssWidth"),
        "cssHeight": info.get("cssHeight"),
        "clientWidth": info.get("clientWidth"),
        "clientHeight": info.get("clientHeight"),
        "complete": info.get("complete"),
        "srcset": info.get("srcset"),
        "sizes": info.get("sizes"),
        "parentTagName": info.get("parentTagName"),
        "pictureSources": info.get("pictureSources"),
        "objectFit": info.get("objectFit"),
        "objectPosition": info.get("objectPosition"),
        "transform": info.get("transform"),
        "clipPath": info.get("clipPath"),
        "filter": info.get("filter"),
        "ancestors": info.get("ancestors"),
        "source_fetch": {
            key: value
            for key, value in source.items()
            if key != "base64" and key != "url"
        },
        "source_url_redacted": redact_url(source.get("url")),
        "source_file": source_file,
        "decoded_source_dimensions": decoded_dimensions,
        "decoded_matches_natural": (
            decoded_dimensions == (info.get("naturalWidth"), info.get("naturalHeight"))
            if decoded_dimensions is not None
            else None
        ),
        "native_png": native_file,
        "native_png_result": {
            key: value for key, value in native.items() if key != "dataUrl"
        },
        "current_screenshot": current_file,
    }


async def wait_for_direct_viewer(page: Page, adapter: MangaOneAdapter) -> None:
    for _ in range(300):
        quota = page.get_by_role("button", name=re.compile(rf"^{re.escape(QUOTA_LABEL)}(?:\s|$)"))
        if (
            await quota.count()
            and await quota.first.is_visible()
            and not await page.locator(PAGE_SELECTOR).count()
        ):
            raise RuntimeError("direct viewer unavailable: quota entry button is visible; no click performed")
        if await adapter._page_image_rows(page):
            await adapter._wait_for_render_ready(page)
            return
        await page.wait_for_timeout(100)
    raise RuntimeError("Manga ONE page images did not become ready")


async def capture_phase(page: Page, adapter: MangaOneAdapter, output_dir: Path, phase: str) -> dict[str, Any]:
    targets = await adapter.get_capture_targets(page)
    rows = await adapter._page_image_rows(page)
    captured = []
    for index, target in enumerate(targets, start=1):
        captured.append(await capture_target(target, output_dir, index, phase))
    return {
        "phase": phase,
        "browser": await browser_metrics(page),
        "visible_count": len(targets),
        "visible_rows_right_to_left": sorted(rows, key=lambda row: float(row["x"]), reverse=True),
        "targets": captured,
    }


async def measure(
    endpoint: str,
    output_dir: Path,
    url: str,
    sample_pages: int,
    try_fullscreen: bool = False,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(endpoint)
        context = browser.contexts[0]
        page = await context.new_page()
        adapter = MangaOneAdapter()
        adapter._initial_url = url
        network_tasks: list[asyncio.Task[dict[str, Any] | None]] = []

        def on_response(response: Any) -> None:
            network_tasks.append(asyncio.create_task(network_image_record(response)))

        page.on("response", on_response)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            await wait_for_direct_viewer(page, adapter)
            result: dict[str, Any] = {
                "requested_url": url,
                "url": page.url,
                "title": await page.title(),
                "quota_consumed": False,
                "chapter_parts": adapter.chapter_parts_from_url(page.url),
                "before_fullscreen": await capture_phase(page, adapter, output_dir, "before-fullscreen"),
            }

            result["visible_controls_before_mouse_move"] = await controls_snapshot(page)
            await page.mouse.move(950, 930)
            await page.wait_for_timeout(500)
            result["visible_controls_after_mouse_move"] = await controls_snapshot(page)
            result["fullscreen_control_snapshot"] = await fullscreen_control_snapshot(page)
            fullscreen_button = page.get_by_role("button", name="全画面", exact=True)
            fullscreen_visible = await fullscreen_button.count() and await fullscreen_button.first.is_visible()
            result["fullscreen_button_visible_before_click"] = bool(fullscreen_visible)
            fullscreen_clicked = False
            if fullscreen_visible:
                await adapter._enter_fullscreen_reader(page)
                result["fullscreen_click_method"] = "adapter_role_button"
                fullscreen_clicked = True
            else:
                fullscreen_image = page.locator('img[alt="full-screen"]')
                fullscreen_parent = page.locator('button:has(img[alt="full-screen"])').first
                result["fullscreen_image_count"] = await fullscreen_image.count()
                result["fullscreen_parent_button_count"] = await fullscreen_parent.count()
                result["fullscreen_click_method"] = "not_attempted_exact_role_locator_unmatched"
            if fullscreen_clicked:
                try:
                    await adapter._wait_for_render_ready(page)
                except Exception as error:  # noqa: BLE001
                    result["fullscreen_wait_error"] = f"{type(error).__name__}: {error}"
            result["after_fullscreen"] = await capture_phase(page, adapter, output_dir, "after-fullscreen")

            pages: list[dict[str, Any]] = []
            pages.append(result["after_fullscreen"])
            for step in range(1, sample_pages):
                previous = await adapter.get_content_identity(page)
                await adapter.go_next(page)
                await adapter.wait_for_change(page, previous)
                if adapter._ended:
                    break
                pages.append(await capture_phase(page, adapter, output_dir, f"sample-{step:02d}"))
            result["sampled_pages"] = pages
            result["ended_during_sampling"] = adapter._ended
            await page.wait_for_timeout(500)
            network_records: list[dict[str, Any]] = []
            for task in network_tasks:
                record = await task
                if record is not None:
                    body = record.pop("body", None)
                    if body:
                        source_index = len(network_records) + 1
                        extension = extension_for_bytes(body, record.get("content_type"))
                        network_path = output_dir / f"network-source-{source_index:03d}{extension}"
                        file_record = write_bytes(network_path, body)
                        record["file"] = file_record
                    network_records.append(record)
            network_by_url = {
                record.get("url_redacted"): record
                for record in network_records
                if record.get("url_redacted")
            }
            all_phases = [result["before_fullscreen"], result["after_fullscreen"], *result["sampled_pages"]]
            for phase_result in all_phases:
                for target in phase_result["targets"]:
                    target["network_source"] = network_by_url.get(target.get("currentSrc_redacted"))
            result["network_image_responses"] = network_records
            return result
        finally:
            await page.close()


async def measure_fullscreen_transition(
    endpoint: str,
    output_dir: Path,
    url: str,
) -> dict[str, Any]:
    """Run a separate-page, opt-in diagnostic of the viewer Full Screen control."""

    output_dir.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(endpoint)
        context = browser.contexts[0]
        page = await context.new_page()
        adapter = MangaOneAdapter()
        adapter._initial_url = url
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            await wait_for_direct_viewer(page, adapter)
            result: dict[str, Any] = {
                "requested_url": url,
                "url": page.url,
                "title": await page.title(),
                "quota_consumed": False,
                "before": await capture_phase(page, adapter, output_dir, "fullscreen-before"),
                "before_state": await fullscreen_state(page, adapter),
                "control": await fullscreen_control_snapshot(page),
            }
            control = page.locator('button:has(img[alt="full-screen"])').first
            result["control_count"] = await control.count()
            if not await control.count():
                result["click"] = "not_available"
                return result

            await control.click(timeout=2_000, no_wait_after=True)
            result["click"] = "button_has_fullscreen_image"
            timeline = []
            for elapsed_ms in range(0, 10_001, 500):
                if elapsed_ms:
                    await page.wait_for_timeout(500)
                state = await fullscreen_state(page, adapter)
                timeline.append(
                    {
                        "elapsed_ms": elapsed_ms,
                        "url": state["url"],
                        "document_fullscreen": state["document_fullscreen"],
                        "viewer_count": state["viewer_count"],
                        "page_selector_count": state["page_selector_count"],
                        "html_class": state["html_class"],
                        "body_class": state["body_class"],
                    }
                )
                if state["page_rows"]:
                    break
            result["after_timeline"] = timeline
            result["after_state"] = state
            if result["after_state"]["page_rows"]:
                try:
                    await adapter._wait_for_render_ready(page)
                    result["after"] = await capture_phase(page, adapter, output_dir, "fullscreen-after")
                except Exception as error:  # noqa: BLE001
                    result["after_error"] = f"{type(error).__name__}: {error}"
            else:
                result["after"] = None
            return result
        finally:
            await page.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="http://127.0.0.1:9222")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--output-dir", type=Path, default=Path("diagnostics/mangaone-source-native"))
    parser.add_argument("--sample-pages", type=int, default=8)
    parser.add_argument(
        "--try-fullscreen",
        action="store_true",
        help="Also click the viewer Full Screen button on a separate diagnostic page.",
    )
    args = parser.parse_args()
    result = asyncio.run(
        measure(
            args.endpoint,
            args.output_dir,
            args.url,
            max(1, args.sample_pages),
            try_fullscreen=args.try_fullscreen,
        )
    )
    if args.try_fullscreen:
        result["fullscreen_transition"] = asyncio.run(
            measure_fullscreen_transition(
                args.endpoint,
                args.output_dir,
                args.url,
            )
        )
    metadata_path = args.output_dir / "metadata.json"
    metadata_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
