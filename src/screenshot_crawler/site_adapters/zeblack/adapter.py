"""Production adapter for the Zeblack horizontal chapter viewer."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from playwright.async_api import Locator, Page

from screenshot_crawler.core.access_guard import AccessProfile
from screenshot_crawler.core.capture import CaptureResult
from screenshot_crawler.core.errors import (
    CaptureUnavailableError,
    PageChangeTimeoutError,
    UnsupportedAccessStrategyError,
)
from screenshot_crawler.core.models import AccessStrategy, ContentContext, ContentIdentity
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.base import SiteAdapter
from screenshot_crawler.site_adapters.zeblack.access import zeblack_access_profile
from screenshot_crawler.site_adapters.zeblack.native_capture import (
    capture_zeblack_source_image,
    is_zeblack_blob_response,
    select_zeblack_active_rows,
)
from screenshot_crawler.site_adapters.zeblack.native_capture import (
    parse_zeblack_page_alt as _parse_zeblack_page_alt,
)

ZEBLACK_VIEWER_HOST = "zebrack-comic.shueisha.co.jp"

_VIEWER_PATH_PREFIX = "/title/"
_IMG_ROWS_SCRIPT = r"""
(elements) => elements.map((element, domOrder) => {
  const rect = element.getBoundingClientRect();
  const style = getComputedStyle(element);
  const visibility = style.visibility;
  const visible = style.display !== "none" && visibility !== "hidden" &&
    visibility !== "collapse" && rect.width > 0 && rect.height > 0;
  const inViewport = rect.right > 0 && rect.left < window.innerWidth &&
    rect.bottom > 0 && rect.top < window.innerHeight;
  return {
    page_alt: element.getAttribute("alt") || "",
    src: element.getAttribute("src") || "",
    current_src: element.currentSrc || element.src || "",
    natural_width: Number(element.naturalWidth) || 0,
    natural_height: Number(element.naturalHeight) || 0,
    visibility,
    visible,
    in_viewport: inViewport,
    dom_order: domOrder,
    x: rect.x,
    y: rect.y,
    width: rect.width,
    height: rect.height,
  };
})
"""
_FOCUS_SCRIPT = r"""
() => {
  const element = document.activeElement;
  if (!element) return {unsafe: false};
  const tag = String(element.tagName || '').toLowerCase();
  return {
    unsafe: ['input', 'textarea', 'select'].includes(tag) || Boolean(element.isContentEditable),
    tag,
    contenteditable: Boolean(element.isContentEditable),
  };
}
"""
_NEXT_CONTENT_SCRIPT = r"""
(elements) => elements.some((element) => {
  const style = getComputedStyle(element);
  const rect = element.getBoundingClientRect();
  if (style.display === "none" || style.visibility === "hidden" ||
      style.visibility === "collapse" || style.opacity === "0" ||
      rect.width <= 0 || rect.height <= 0 || rect.right <= 0 ||
      rect.left >= window.innerWidth || rect.bottom <= 0 ||
      rect.top >= window.innerHeight) return false;
  const text = [element.innerText || '', element.getAttribute('aria-label') || '',
    element.getAttribute('title') || ''].join(' ').replace(/\s+/g, ' ').trim();
  return /次の話\s*を\s*読む|次の話\s*へ|next\s+(?:chapter|episode|content)/i.test(text);
})
"""


@dataclass(frozen=True, slots=True)
class ZeblackViewerIdentity:
    title_id: str
    chapter_id: str

    @property
    def key(self) -> tuple[str, str]:
        return self.title_id, self.chapter_id


def parse_zeblack_viewer_url(url: str) -> ZeblackViewerIdentity | None:
    """Parse only an HTTPS Zeblack ``/title/id/chapter/id/viewer`` URL."""

    if not isinstance(url, str):
        return None
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.lower() != "https"
        or parsed.hostname != ZEBLACK_VIEWER_HOST
        or port is not None
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    parts = parsed.path.split("/")
    if len(parts) != 6 or parts[1] != "title" or parts[3] != "chapter" or parts[5] != "viewer":
        return None
    title_id, chapter_id = parts[2], parts[4]
    if not title_id.isdecimal() or not chapter_id.isdecimal():
        return None
    return ZeblackViewerIdentity(title_id=title_id, chapter_id=chapter_id)


def parse_zeblack_page_alt(value: object) -> int | None:
    """Expose the pure page label parser from the production adapter module."""

    return _parse_zeblack_page_alt(value)


class ZeblackAdapter(SiteAdapter):
    page_change_timeout_ms = 10_000
    render_stable_checks = 2
    source_response_wait_timeout_ms = 2_000
    max_blob_responses = 128

    def __init__(self) -> None:
        self._access_strategy: AccessStrategy = "auto"
        self._initial_url: str | None = None
        self._initial_viewer: ZeblackViewerIdentity | None = None
        self._initial_context: ContentContext | None = None
        self._output_title: str | None = None
        self._transition_pending = False
        self._transition_stable = False
        self._transition_kind = "idle"
        self._transition_before_signature: tuple[object, ...] | None = None
        self._transition_before_url: str | None = None
        self._capture_mode = "unavailable"
        self._direct_source_success: bool | None = None
        self._direct_source_failure_reason: str | None = None
        self._last_detection_failure: str | None = None
        self._last_active_indices: tuple[int, ...] = ()
        self._source_responses: OrderedDict[str, object] = OrderedDict()
        self._source_response_tasks: OrderedDict[str, asyncio.Task[bytes | None]] = OrderedDict()
        self._listener_page: Page | None = None
        self._protected_source_urls: set[str] = set()

    def get_access_profile(self) -> AccessProfile:
        return zeblack_access_profile()

    async def configure_run(self, page: Page, access_strategy: AccessStrategy) -> None:
        del page
        if access_strategy not in {"auto", "direct"}:
            raise UnsupportedAccessStrategyError(
                f"ZeblackAdapter does not support access_strategy={access_strategy!r}"
            )
        self._access_strategy = access_strategy

    async def configure_quota_resource(
        self, page: Page, quota_resource: str | None
    ) -> None:
        del page
        if quota_resource is not None:
            raise UnsupportedAccessStrategyError(
                "ZeblackAdapter does not support quota_resource"
            )

    async def prepare_page(self, page: Page) -> None:
        await self._clear_source_cache()
        if self._listener_page is not None and callable(
            getattr(self._listener_page, "remove_listener", None)
        ):
            self._listener_page.remove_listener("response", self._handle_source_response)
        page.on("response", self._handle_source_response)
        self._listener_page = page

    def _handle_source_response(self, response: object) -> None:
        if not is_zeblack_blob_response(response):
            return
        url = str(getattr(response, "url", ""))
        if not url or url in self._source_responses:
            return
        try:
            task = asyncio.create_task(self._read_response(response))
        except RuntimeError:
            return
        self._source_responses[url] = response
        self._source_response_tasks[url] = task
        self._trim_source_cache()

    @staticmethod
    async def _read_response(response: object) -> bytes | None:
        try:
            body = await response.body()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - direct capture may fall back
            return None
        return body if isinstance(body, bytes) else None

    def _trim_source_cache(self) -> None:
        while len(self._source_response_tasks) > self.max_blob_responses:
            candidate = next(
                (
                    url
                    for url in self._source_response_tasks
                    if url not in self._protected_source_urls
                ),
                None,
            )
            if candidate is None:
                return
            task = self._source_response_tasks.pop(candidate)
            self._source_responses.pop(candidate, None)
            if not task.done():
                task.cancel()

    async def _clear_source_cache(self) -> None:
        tasks = tuple(self._source_response_tasks.values())
        self._source_response_tasks.clear()
        self._source_responses.clear()
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _release_source_urls(self, urls: set[str]) -> None:
        tasks: list[asyncio.Task[bytes | None]] = []
        for url in urls:
            task = self._source_response_tasks.pop(url, None)
            self._source_responses.pop(url, None)
            if task is not None:
                if not task.done():
                    task.cancel()
                tasks.append(task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _dom_rows(self, page: Page) -> list[dict[str, object]]:
        locator = page.locator("img")
        rows = await asyncio.wait_for(locator.evaluate_all(_IMG_ROWS_SCRIPT), timeout=2)
        return rows if isinstance(rows, list) else []

    async def _active_page_rows(self, page: Page) -> list[dict[str, object]]:
        try:
            rows = select_zeblack_active_rows(await self._dom_rows(page))
        except (ValueError, TimeoutError) as exc:
            self._last_detection_failure = str(exc)
            raise CaptureUnavailableError(
                f"Zeblack active page detection failed: {exc}"
            ) from exc
        self._last_detection_failure = None
        self._last_active_indices = tuple(int(row["page_index"]) for row in rows)
        return rows

    async def _safe_active_page_rows(
        self, page: Page
    ) -> list[dict[str, object]] | None:
        try:
            return await self._active_page_rows(page)
        except CaptureUnavailableError:
            return None

    @staticmethod
    def _row_signature(rows: list[dict[str, object]]) -> tuple[object, ...]:
        return tuple(
            (
                int(row["page_index"]),
                str(row["source_url"]),
                int(row["natural_width"]),
                int(row["natural_height"]),
                round(float(row.get("x", 0))),
                round(float(row.get("y", 0))),
                round(float(row.get("width", 0))),
                round(float(row.get("height", 0))),
            )
            for row in rows
        )

    @staticmethod
    def _page_id(rows: list[dict[str, object]]) -> str | None:
        return "+".join(str(row["page_alt"]) for row in rows) or None

    async def _visible_next_content_signal(self, page: Page) -> bool:
        try:
            controls = page.locator("button, a, [role='button']")
            result = await asyncio.wait_for(
                controls.evaluate_all(_NEXT_CONTENT_SCRIPT), timeout=2
            )
        except Exception:  # noqa: BLE001 - terminal evidence must fail closed
            return False
        return result is True

    async def _snapshot(self, page: Page) -> dict[str, object]:
        current_url = str(page.url)
        viewer = parse_zeblack_viewer_url(current_url)
        rows = await self._safe_active_page_rows(page)
        terminal_signal = await self._visible_next_content_signal(page)
        row_signature = self._row_signature(rows) if rows is not None else ()
        return {
            "url": current_url,
            "viewer": viewer,
            "rows": rows,
            "page_id": self._page_id(rows) if rows is not None else None,
            "terminal_signal": terminal_signal,
            "fingerprint": (
                current_url,
                row_signature,
                tuple(item[1] for item in row_signature),
                terminal_signal,
                self._last_detection_failure,
            ),
        }

    async def _wait_for_initial_content(self, page: Page) -> None:
        elapsed_ms = 0
        previous: tuple[object, ...] | None = None
        stable = 0
        while elapsed_ms < self.page_change_timeout_ms:
            rows = await self._safe_active_page_rows(page)
            if rows:
                signature = self._row_signature(rows)
                if signature == previous:
                    stable += 1
                    if stable >= self.render_stable_checks:
                        return
                else:
                    previous = signature
                    stable = 1
            else:
                previous = None
                stable = 0
            await page.wait_for_timeout(100)
            elapsed_ms += 100
        raise PageChangeTimeoutError(
            "Zeblack viewer did not expose stable in-viewport page_N content"
        )

    async def initialize(self, page: Page) -> None:
        current_url = str(page.url)
        viewer = parse_zeblack_viewer_url(current_url)
        if viewer is None:
            raise ValueError("Zeblack page URL is not a strict viewer URL")
        self._initial_url = current_url
        self._initial_viewer = viewer
        self._transition_pending = False
        self._transition_stable = False
        self._transition_kind = "idle"
        self._transition_before_signature = None
        self._transition_before_url = None
        self._capture_mode = "unavailable"
        self._direct_source_success = None
        self._direct_source_failure_reason = None
        await self._wait_for_initial_content(page)
        self._initial_context = await self.get_content_context(page)
        self._output_title = self._initial_context.title

    async def detect_state(self, page: Page) -> PageState:
        current = parse_zeblack_viewer_url(str(page.url))
        if current is None:
            return PageState.UNKNOWN
        if self._initial_viewer is not None and current.key != self._initial_viewer.key:
            return PageState.NEXT_CONTENT

        rows = await self._safe_active_page_rows(page)
        if rows is None:
            return PageState.UNKNOWN
        if rows:
            return PageState.CONTENT
        if (
            self._transition_stable
            and self._transition_kind == "terminal_next_content"
            and self._initial_viewer is not None
            and current.key == self._initial_viewer.key
            and await self._visible_next_content_signal(page)
        ):
            return PageState.NEXT_CONTENT
        return PageState.UNKNOWN

    async def get_capture_target(self, page: Page) -> Locator:
        targets = await self.get_capture_targets(page)
        return targets[0]

    async def get_capture_targets(self, page: Page) -> tuple[Locator, ...]:
        rows = await self._active_page_rows(page)
        self._capture_mode = "locator_fallback"
        targets = page.locator("img")
        return tuple(targets.nth(int(row["dom_order"])) for row in rows)

    async def capture_page(self, page: Page) -> tuple[CaptureResult, ...] | None:
        """Capture every active page from its exact blob response, all-or-none."""

        rows = await self._active_page_rows(page)
        if not rows:
            self._direct_source_success = False
            self._direct_source_failure_reason = "no_active_page_rows"
            raise CaptureUnavailableError("Zeblack has no active page_N images")

        source_urls = {str(row["source_url"]) for row in rows}
        self._protected_source_urls.update(source_urls)
        captures: list[CaptureResult] = []
        used_source_urls: set[str] = set()
        try:
            for row in rows:
                source_url = str(row["source_url"])
                task = self._source_response_tasks.get(source_url)
                if task is None:
                    response = self._source_responses.get(source_url)
                    if response is not None:
                        task = asyncio.create_task(self._read_response(response))
                        self._source_response_tasks[source_url] = task
                if task is None:
                    raise CaptureUnavailableError(
                        f"exact blob response was not observed for {source_url}"
                    )
                try:
                    body = await asyncio.wait_for(
                        asyncio.shield(task),
                        timeout=self.source_response_wait_timeout_ms / 1000,
                    )
                except (TimeoutError, asyncio.CancelledError) as exc:
                    raise CaptureUnavailableError(
                        f"blob response body was unavailable for {source_url}"
                    ) from exc
                if body is None:
                    raise CaptureUnavailableError(
                        f"blob response body was unavailable for {source_url}"
                    )
                try:
                    captures.append(
                        capture_zeblack_source_image(
                            body,
                            expected_width=int(row["natural_width"]),
                            expected_height=int(row["natural_height"]),
                        )
                    )
                except ValueError as exc:
                    raise CaptureUnavailableError(str(exc)) from exc
                used_source_urls.add(source_url)
        except CaptureUnavailableError as exc:
            self._direct_source_success = False
            self._direct_source_failure_reason = str(exc)
            self._capture_mode = "unavailable"
            raise
        finally:
            self._protected_source_urls.difference_update(source_urls)

        self._direct_source_success = True
        self._direct_source_failure_reason = None
        self._capture_mode = "blob_source_native"
        await self._release_source_urls(used_source_urls)
        return tuple(captures)

    async def get_content_identity(self, page: Page) -> ContentIdentity:
        rows = await self._active_page_rows(page)
        chapter_id = self._initial_viewer.chapter_id if self._initial_viewer else None
        return ContentIdentity(
            page_id=self._page_id(rows),
            page_number=(int(rows[0]["page_index"]) + 1) if rows else None,
            source_id=chapter_id,
        )

    async def get_content_context(self, page: Page) -> ContentContext:
        viewer = parse_zeblack_viewer_url(str(page.url))
        if viewer is None:
            raise ValueError("Zeblack page URL is not a strict viewer URL")
        title: str | None = None
        try:
            raw_title = (await page.title()).strip()
            title = raw_title.split(" | ", 1)[0].strip() or None
        except Exception:  # noqa: BLE001 - title is optional metadata
            title = None
        return ContentContext(
            content_id=viewer.chapter_id,
            work_id=viewer.title_id,
            episode_id=viewer.chapter_id,
            chapter_id=viewer.chapter_id,
            title=title,
        )

    async def go_next(self, page: Page) -> None:
        current = parse_zeblack_viewer_url(str(page.url))
        if (
            current is None
            or self._initial_viewer is None
            or current.key != self._initial_viewer.key
        ):
            raise PageChangeTimeoutError("Zeblack next-page guard rejected the current URL")
        rows = await self._active_page_rows(page)
        if not rows or self._transition_pending or (
            self._transition_stable and self._transition_kind == "terminal_next_content"
        ):
            raise PageChangeTimeoutError("Zeblack next-page guard rejected the current state")
        try:
            focus = await page.evaluate(_FOCUS_SCRIPT)
        except Exception as exc:  # do not send a key without safety evidence
            raise PageChangeTimeoutError("Zeblack keyboard focus could not be verified") from exc
        if isinstance(focus, dict) and focus.get("unsafe") is True:
            raise PageChangeTimeoutError("Zeblack ArrowLeft was blocked by focused form content")
        if not isinstance(focus, dict):
            raise PageChangeTimeoutError("Zeblack keyboard focus evidence was unavailable")

        self._transition_before_signature = (await self._snapshot(page))["fingerprint"]  # type: ignore[assignment]
        self._transition_before_url = str(page.url)
        self._transition_pending = True
        self._transition_stable = False
        self._transition_kind = "pending"
        try:
            await page.keyboard.press("ArrowLeft")
        except Exception:
            self._transition_pending = False
            self._transition_kind = "idle"
            raise

    async def wait_for_change(
        self, page: Page, previous_identity: ContentIdentity | None
    ) -> None:
        if previous_identity is None:
            await self._wait_for_initial_content(page)
            return

        before = self._transition_before_signature
        if before is None:
            before = ("previous_identity", previous_identity.page_id)
        elapsed_ms = 0
        changed = False
        previous_fingerprint: tuple[object, ...] | None = None
        stable_checks = 0
        while elapsed_ms < self.page_change_timeout_ms:
            snapshot = await self._snapshot(page)
            fingerprint = snapshot["fingerprint"]
            if fingerprint != before:
                changed = True
            if changed and fingerprint == previous_fingerprint:
                stable_checks += 1
            elif changed:
                previous_fingerprint = fingerprint  # type: ignore[assignment]
                stable_checks = 1
            if changed and stable_checks >= self.render_stable_checks and self._transition_is_valid(
                snapshot, previous_identity
            ):
                self._transition_pending = False
                self._transition_stable = True
                self._transition_kind = self._transition_kind_for(snapshot, previous_identity)
                return
            await page.wait_for_timeout(100)
            elapsed_ms += 100
        raise PageChangeTimeoutError(
            "Zeblack viewer did not produce a changed and stable page transition"
        )

    def _transition_is_valid(
        self, snapshot: dict[str, object], previous_identity: ContentIdentity
    ) -> bool:
        viewer = snapshot.get("viewer")
        if not isinstance(viewer, ZeblackViewerIdentity):
            return True
        if self._initial_viewer is not None and viewer.key != self._initial_viewer.key:
            return True
        rows = snapshot.get("rows")
        if rows is None:
            return False
        if isinstance(rows, list) and rows:
            return self._page_id(rows) != previous_identity.page_id
        return (
            viewer.key == (self._initial_viewer.key if self._initial_viewer else viewer.key)
            and snapshot.get("terminal_signal") is True
        )

    def _transition_kind_for(
        self, snapshot: dict[str, object], previous_identity: ContentIdentity
    ) -> str:
        viewer = snapshot.get("viewer")
        if (
            isinstance(viewer, ZeblackViewerIdentity)
            and self._initial_viewer is not None
            and viewer.key != self._initial_viewer.key
        ):
            return "chapter_escape"
        rows = snapshot.get("rows")
        if isinstance(rows, list) and rows and self._page_id(rows) != previous_identity.page_id:
            return "content"
        if snapshot.get("terminal_signal") is True:
            return "terminal_next_content"
        return "unknown"

    async def collect_debug_metadata(self, page: Page) -> dict[str, Any]:
        try:
            rows = await self._safe_active_page_rows(page)
            active_indices = [int(row["page_index"]) for row in rows] if rows else []
        except Exception:  # noqa: BLE001 - diagnostics must not replace crawl behavior
            active_indices = list(self._last_active_indices)
        return {
            "capture_mode": self._capture_mode,
            "active_page_indices": active_indices,
            "direct_source_success": self._direct_source_success,
            "direct_source_failure_reason": self._direct_source_failure_reason,
            "source_cache_size": len(self._source_response_tasks),
            "transition_state": {
                "pending": self._transition_pending,
                "stable": self._transition_stable,
                "kind": self._transition_kind,
            },
        }

    def get_output_metadata(self) -> dict[str, str | None]:
        return {"title": self._output_title, "author": None, "order": None, "genre": "漫画"}
