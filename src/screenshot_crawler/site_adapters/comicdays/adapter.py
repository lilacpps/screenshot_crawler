"""Comic DAYS horizontal free viewer adapter."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
from typing import Any

from playwright.async_api import Locator, Page

from screenshot_crawler.core.access_guard import AccessProfile
from screenshot_crawler.core.capture import CaptureResult
from screenshot_crawler.core.errors import PageChangeTimeoutError, UnsupportedAccessStrategyError
from screenshot_crawler.core.models import AccessStrategy, ContentContext, ContentIdentity
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.base import SiteAdapter
from screenshot_crawler.site_adapters.comicdays.access import comicdays_access_profile
from screenshot_crawler.site_adapters.comicdays.discovery import (
    _series_id_from_page,
    canonical_comicdays_episode_url,
    fetch_comicdays_atom,
    parse_comicdays_episode_url,
)
from screenshot_crawler.site_adapters.comicdays.native_capture import (
    COMICDAYS_CAPTURE_HOOK,
    reconstruct_png,
    source_id_for_row,
    strict_canvas_sequence,
)

_FORBIDDEN = re.compile(r"(?:購入|ポイント|チケット|レンタル|ログイン|会員登録|purchase|point|ticket|rental|login)", re.IGNORECASE)


class ComicDaysAdapter(SiteAdapter):
    """Capture currently free Comic DAYS episodes, failing closed on ambiguity."""

    page_change_timeout_ms = 10_000
    viewer_selector = "section.viewer.js-viewer"
    canvas_selector = "section.viewer.js-viewer .image-container.js-viewer-content canvas.page-image.js-page-image"
    forward_selector = "section.viewer.js-viewer .page-navigation-forward.js-slide-forward"

    def __init__(self) -> None:
        self._access_strategy: AccessStrategy = "auto"
        self._initial_url: str | None = None
        self._episode_id: str | None = None
        self._work_id: str | None = None
        self._title: str | None = None
        self._author: str | None = None
        self._terminal = False
        self._advance_pending = False
        self._last_slider: int | None = None
        self._capture_debug: dict[str, Any] = {}
        self._selected_signature: tuple[Any, ...] | None = None

    def get_access_profile(self) -> AccessProfile:
        return comicdays_access_profile()

    async def configure_run(self, page: Page, access_strategy: AccessStrategy) -> None:
        del page
        if access_strategy not in {"auto", "direct"}:
            raise UnsupportedAccessStrategyError("ComicDaysAdapter supports only free direct/auto access")
        self._access_strategy = access_strategy

    async def configure_quota_resource(self, page: Page, quota_resource: str | None) -> None:
        del page
        if quota_resource is not None:
            raise UnsupportedAccessStrategyError("ComicDaysAdapter does not support quota resources")

    async def prepare_page(self, page: Page) -> None:
        await page.add_init_script(script=COMICDAYS_CAPTURE_HOOK)

    async def _active(self, page: Page, *, timeout_ms: int | None = None) -> dict[str, Any]:
        timeout_seconds = 2 if timeout_ms is None else max(0.001, min(2, timeout_ms / 1000))
        try:
            value = await asyncio.wait_for(
                page.evaluate("() => window.__comicDaysProductionCapture?.active() || null"),
                timeout=timeout_seconds,
            )
        except Exception:  # noqa: BLE001 - rendering races remain unknown
            return {"rows": [], "colophon": False}
        if not isinstance(value, dict):
            return {"rows": [], "colophon": False}
        rows = value.get("rows")
        value["rows"] = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
        value["ready"] = bool(value["rows"]) and all(row.get("renderReady") is True for row in value["rows"])
        if isinstance(value.get("sliderNow"), int):
            self._last_slider = value["sliderNow"]
        return value

    @staticmethod
    def _remaining_ms(deadline: float) -> int:
        return max(0, int((deadline - asyncio.get_running_loop().time()) * 1000))

    async def _active_until(self, page: Page, deadline: float) -> dict[str, Any]:
        remaining = self._remaining_ms(deadline)
        if remaining <= 0:
            raise PageChangeTimeoutError("Comic DAYS viewer operation exceeded its time bound")
        try:
            return await asyncio.wait_for(
                self._active(page, timeout_ms=remaining), timeout=remaining / 1000
            )
        except TimeoutError as exc:
            raise PageChangeTimeoutError("Comic DAYS viewer observation exceeded its time bound") from exc

    async def initialize(self, page: Page) -> None:
        episode_id = parse_comicdays_episode_url(page.url)
        if episode_id is None:
            raise ValueError("Comic DAYS page URL is not a canonical episode URL")
        self._initial_url, self._episode_id = canonical_comicdays_episode_url(page.url), episode_id
        self._work_id = await _series_id_from_page(page)
        entries = await fetch_comicdays_atom(page, self._work_id, free_only=True)
        if not any(item.get("episode_id") == episode_id and item.get("url") == self._initial_url for item in entries):
            raise UnsupportedAccessStrategyError("Comic DAYS episode is not currently free")
        self._title, self._author = await self._read_metadata(page)
        self._terminal = False
        self._advance_pending = False
        self._selected_signature = None
        deadline = asyncio.get_running_loop().time() + self.page_change_timeout_ms / 1000
        try:
            async with asyncio.timeout_at(deadline):
                await self._normalize_viewer(page, deadline)
        except TimeoutError as exc:
            raise PageChangeTimeoutError("Comic DAYS viewer normalization exceeded its time bound") from exc

    async def _normalize_viewer(self, page: Page, deadline: float) -> None:
        horizontal_seen = False
        while self._remaining_ms(deadline) > 0:
            remaining = self._remaining_ms(deadline)
            if not await asyncio.wait_for(
                self._horizontal_positive(page, timeout_ms=remaining), timeout=remaining / 1000
            ):
                await page.wait_for_timeout(min(100, self._remaining_ms(deadline)))
                continue
            horizontal_seen = True
            state = await self._active_until(page, deadline)
            current = state.get("sliderNow")
            last = state.get("sliderLast")
            if isinstance(current, int) and isinstance(last, int) and 1 <= current <= last:
                await self._rewind_to_first(page, deadline=deadline)
                break
            await page.wait_for_timeout(min(100, self._remaining_ms(deadline)))
        else:
            if not horizontal_seen:
                raise PageChangeTimeoutError("Comic DAYS horizontal viewer was not positively identified")
            raise PageChangeTimeoutError("Comic DAYS viewer did not expose a valid slider")

        while self._remaining_ms(deadline) > 0:
            state = await self._active_until(page, deadline)
            current = state.get("sliderNow")
            last = state.get("sliderLast")
            if state.get("rows") and state.get("ready") is True:
                if not isinstance(current, int) or not isinstance(last, int) or not 1 <= current <= last:
                    raise PageChangeTimeoutError("Comic DAYS first spread exposed an invalid slider")
                if current == 1:
                    return
                await self._rewind_to_first(page, deadline=deadline)
                continue
            await page.wait_for_timeout(min(100, self._remaining_ms(deadline)))
        raise PageChangeTimeoutError("Comic DAYS first content spread did not become ready")

    async def _rewind_to_first(self, page: Page, *, deadline: float | None = None) -> None:
        """Normalize a shared-profile viewer that reopened on a later spread."""
        if deadline is None:
            deadline = asyncio.get_running_loop().time() + self.page_change_timeout_ms / 1000
        for _ in range(64):
            remaining = self._remaining_ms(deadline)
            if remaining <= 0:
                raise PageChangeTimeoutError("Comic DAYS rewind exceeded its time bound")
            state = await self._active_until(page, deadline)
            current = state.get("sliderNow")
            if not isinstance(current, int) or current <= 1:
                if not isinstance(current, int) or current < 1:
                    raise PageChangeTimeoutError("Comic DAYS rewind exposed an invalid slider")
                return
            button = page.locator("section.viewer.js-viewer .page-navigation-backward.js-slide-backward")
            if await button.count() != 1 or not await button.is_visible():
                raise PageChangeTimeoutError("Comic DAYS could not rewind the shared viewer state")
            href = await button.get_attribute("href", timeout=remaining)
            values = " ".join(str(value or "") for value in [await button.inner_text(timeout=remaining), await button.get_attribute("aria-label", timeout=remaining), await button.get_attribute("title", timeout=remaining), href])
            if href and "/episode/" in href or _FORBIDDEN.search(values):
                raise PageChangeTimeoutError("Comic DAYS backward control failed navigation safety validation")
            await button.click(timeout=min(1_000, remaining), no_wait_after=True)
            for _ in range(20):
                remaining = self._remaining_ms(deadline)
                if remaining <= 0:
                    raise PageChangeTimeoutError("Comic DAYS backward control did not progress within the time bound")
                delay = min(100, remaining)
                await page.wait_for_timeout(delay)
                after = await self._active_until(page, deadline)
                if after.get("sliderNow") != current:
                    break
        raise PageChangeTimeoutError("Comic DAYS viewer did not rewind within the step bound")

    async def _read_metadata(self, page: Page) -> tuple[str | None, str | None]:
        async def read(selector: str) -> str | None:
            locator = page.locator(selector)
            if await locator.count() != 1:
                return None
            try:
                value = " ".join((await locator.inner_text(timeout=2_000)).split())
            except Exception:  # noqa: BLE001
                return None
            return value or None

        return (
            await read(".series-header-title,[class*='series-header-title']"),
            await read(".series-header-author,[class*='series-header-author']"),
        )

    async def _horizontal_positive(self, page: Page, *, timeout_ms: int | None = None) -> bool:
        timeout_seconds = 2 if timeout_ms is None else max(0.001, min(2, timeout_ms / 1000))
        try:
            return bool(await asyncio.wait_for(page.evaluate("""() => {
              const v=document.querySelector('section.viewer.js-viewer');
              const h=document.querySelector('.content-inner.scroll-horizontal.js-horizontal-viewer');
              const f=document.querySelectorAll('.page-navigation-forward.js-slide-forward');
              const b=document.querySelectorAll('.page-navigation-backward.js-slide-backward');
              return !!(v&&h&&f.length===1&&b.length===1);
            }"""), timeout=timeout_seconds))
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _signature(rows: list[dict[str, Any]]) -> tuple[Any, ...]:
        return tuple(
            (
                row.get("areaIndex"),
                row.get("canvasId"),
                row.get("base", {}).get("sequence") if isinstance(row.get("base"), dict) else None,
                row.get("base", {}).get("sourceId") if isinstance(row.get("base"), dict) else None,
                row.get("base", {}).get("sourceUrl") if isinstance(row.get("base"), dict) else None,
                row.get("clipUnsafe") is True,
                row.get("unsafeSequence"),
                tuple(
                    (item.get("sequence"), item.get("sourceId"), item.get("sourceUrl"), tuple(item.get("args", ())))
                    for item in row.get("mapping", [])
                    if isinstance(item, dict)
                ),
                tuple(
                    (
                        item.get("sequence"),
                        item.get("operation"),
                        tuple(item.get("args", ())) if isinstance(item.get("args"), list) else item.get("args"),
                        item.get("value"),
                    )
                    for item in row.get("mutations", [])
                    if isinstance(item, dict)
                ),
            )
            for row in rows
        )

    async def detect_state(self, page: Page) -> PageState:
        current = parse_comicdays_episode_url(page.url)
        if self._episode_id and current and current != self._episode_id:
            return PageState.NEXT_CONTENT
        if self._terminal:
            return PageState.END
        state = await self._active(page)
        if state.get("rows") and state.get("ready") is not True:
            return PageState.LOADING
        if state.get("rows"):
            return PageState.CONTENT
        if self._advance_pending and state.get("colophon") is True:
            self._terminal = True
            return PageState.END
        viewer = page.locator(self.viewer_selector)
        if await viewer.count() and await viewer.is_visible(timeout=500):
            return PageState.LOADING
        return PageState.UNKNOWN

    async def get_capture_targets(self, page: Page) -> tuple[Locator, ...]:
        state = await self._active(page)
        rows = state.get("rows", [])
        if not rows or state.get("ready") is not True:
            raise LookupError("Comic DAYS active canvas is not render-ready")
        if self._selected_signature is not None and self._signature(rows) != self._selected_signature:
            raise LookupError("Comic DAYS capture selection changed before fallback")
        locator = page.locator(self.canvas_selector)
        return tuple(locator.nth(int(row["canvasIndex"])) for row in rows if isinstance(row.get("canvasIndex"), int))

    async def get_capture_target(self, page: Page) -> Locator:
        return (await self.get_capture_targets(page))[0]

    async def capture_page(self, page: Page) -> tuple[CaptureResult, ...] | None:
        self._capture_debug = {"native": False}
        state = await self._active(page)
        rows = state.get("rows", [])
        current_signature = self._signature(rows)
        if self._selected_signature is not None and current_signature != self._selected_signature:
            raise LookupError("Comic DAYS capture selection changed before capture")
        if not rows or len(rows) > 4 or state.get("ready") is not True:
            return None
        before_signature = current_signature
        plans = [strict_canvas_sequence(row) for row in rows]
        if any(plan is None for plan in plans):
            self._capture_debug = {"native": False, "reason": "unsafe_or_incomplete_sequence"}
            return None
        ids = [source_id_for_row(row) for row in rows]
        if any(item is None for item in ids):
            return None
        try:
            payload = await asyncio.wait_for(
                page.evaluate("ids => window.__comicDaysProductionCapture.snapshot(ids)", ids),
                timeout=4,
            )
        except Exception:  # noqa: BLE001
            return None
        by_id = {item.get("id"): item for item in payload if isinstance(item, dict)} if isinstance(payload, list) else {}
        results: list[CaptureResult] = []
        for plan in plans:
            item = by_id.get(plan["source_id"]) if plan else None
            if not plan or not isinstance(item, dict) or not isinstance(item.get("bytes"), str):
                return None
            if item.get("url") != plan.get("source_url"):
                current = await self._active(page)
                if current.get("ready") is not True or self._signature(current.get("rows", [])) != before_signature:
                    raise LookupError("Comic DAYS source changed during capture")
                return None
            try:
                raw = base64.b64decode(item["bytes"], validate=True)
            except Exception:  # noqa: BLE001
                return None
            result = reconstruct_png(raw, plan)
            if result is None:
                return None
            results.append(result)
        after = await self._active(page)
        if after.get("ready") is not True or self._signature(after.get("rows", [])) != before_signature:
            raise LookupError("Comic DAYS capture selection changed during native capture")
        self._capture_debug = {"native": True, "parts": len(results)}
        return tuple(results)

    async def get_content_identity(self, page: Page) -> ContentIdentity:
        state = await self._active(page)
        rows = state.get("rows", [])
        if not rows:
            raise LookupError("Comic DAYS content identity unavailable")
        signature = self._signature(rows)
        self._selected_signature = signature
        digest = hashlib.sha256(json.dumps(signature, ensure_ascii=False, default=str).encode()).hexdigest()[:24]
        page_id = ",".join(str(row.get("areaIndex")) for row in rows)
        return ContentIdentity(page_id=page_id, page_number=state.get("sliderNow"), source_id=self._episode_id, fingerprint=digest)

    async def get_content_context(self, page: Page) -> ContentContext:
        return ContentContext(content_id=self._episode_id, work_id=self._work_id, episode_id=self._episode_id, title=self._title)

    async def go_next(self, page: Page) -> None:
        button = page.locator(self.forward_selector)
        if await button.count() != 1 or not await button.is_visible():
            raise PageChangeTimeoutError("Comic DAYS forward control was not uniquely visible")
        values = " ".join(str(value or "") for value in [await button.inner_text(), await button.get_attribute("aria-label"), await button.get_attribute("title"), await button.get_attribute("href"), await button.get_attribute("class")])
        href = await button.get_attribute("href")
        if _FORBIDDEN.search(values) or (href and "/episode/" in href):
            raise PageChangeTimeoutError("Comic DAYS forward control failed safety validation")
        self._advance_pending = True
        await button.click(timeout=1_000, no_wait_after=True)

    async def wait_for_change(self, page: Page, previous_identity: ContentIdentity | None) -> None:
        elapsed, stable, previous = 0, 0, None
        while elapsed < self.page_change_timeout_ms:
            state = await self._active(page)
            if self._advance_pending and not state.get("rows") and state.get("colophon"):
                slider = state.get("sliderNow")
                if previous_identity is None or slider != previous_identity.page_number:
                    self._terminal = True
                    return
            if state.get("rows") and state.get("ready") is True:
                current = await self.get_content_identity(page)
                progressed = previous_identity is None or (
                    current.page_id != previous_identity.page_id
                    or current.page_number != previous_identity.page_number
                )
                if progressed:
                    sig = self._signature(state["rows"])
                    stable = stable + 1 if sig == previous else 0
                    previous = sig
                    if stable >= 2:
                        self._advance_pending = False
                        return
                else:
                    stable, previous = 0, None
            await page.wait_for_timeout(100)
            elapsed += 100
        raise PageChangeTimeoutError("Comic DAYS page did not change within the timeout")

    async def collect_debug_metadata(self, page: Page) -> dict[str, Any]:
        del page
        return dict(self._capture_debug)

    def get_output_metadata(self) -> dict[str, str | None]:
        return {"title": self._title, "author": self._author, "order": None, "genre": "漫画"}
