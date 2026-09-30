"""Production adapter for the Zeblack horizontal chapter viewer."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from screenshot_crawler.core.access_guard import AccessProfile
from screenshot_crawler.core.capture import CaptureResult
from screenshot_crawler.core.errors import (
    AccessResourceUnavailableError,
    CaptureUnavailableError,
    PageChangeTimeoutError,
    UnknownPageStateError,
    UnsupportedAccessStrategyError,
)
from screenshot_crawler.core.models import AccessStrategy, ContentContext, ContentIdentity
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.base import AccessConsumption, SiteAdapter
from screenshot_crawler.site_adapters.zeblack.access import zeblack_access_profile
from screenshot_crawler.site_adapters.zeblack.discovery_protobuf import ConsumptionStatus
from screenshot_crawler.site_adapters.zeblack.live_access import (
    ZeblackLiveAccessError,
    ZeblackLiveAccessState,
    observe_zeblack_live_access,
)
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
_ADVERTISEMENT_SCRIPT = r"""
(elements) => elements.some((element) => {
  const style = getComputedStyle(element);
  const rect = element.getBoundingClientRect();
  if (style.display === "none" || style.visibility === "hidden" ||
      style.visibility === "collapse" || style.opacity === "0" ||
      rect.width <= 0 || rect.height <= 0 || rect.right <= 0 ||
      rect.left >= window.innerWidth || rect.bottom <= 0 ||
      rect.top >= window.innerHeight) return false;
  return Boolean(element.closest(".-KWKsa_spread"));
})
"""
_LAST_PAGE_SCRIPT = r"""
(elements) => elements.some((element) => {
  const style = getComputedStyle(element);
  const rect = element.getBoundingClientRect();
  if (style.display === "none" || style.visibility === "hidden" ||
      style.visibility === "collapse" || style.opacity === "0" ||
      rect.width <= 0 || rect.height <= 0 || rect.right <= 0 ||
      rect.left >= window.innerWidth || rect.bottom <= 0 ||
      rect.top >= window.innerHeight) return false;
  const text = (element.innerText || '').replace(/\s+/g, ' ').trim();
  return text.includes("続きの巻購入で、何度でも読み返し！") ||
    text.includes("次の話を読む");
})
"""

_TICKET_ENTRY_TEXT = "チケットを使って読む"
_POINT_ENTRY_TEXT = "ポイントを使って読む"
_COIN_ENTRY_TEXT = "コインを使って読む"
_POINT_AND_COIN_ENTRY_TEXT = "アイテムを使って読む"
_PURCHASE_ENTRY_TEXT = "コインを購入する"
_TICKET_STATUS_VALUES = frozenset(
    {
        int(ConsumptionStatus.TICKET_UNAVAILABLE),
        int(ConsumptionStatus.POINT),
        int(ConsumptionStatus.COIN),
        int(ConsumptionStatus.TICKET_UNAVAILABLE_COIN_ONLY),
    }
)


def validate_zeblack_ticket_control_counts(
    ticket_count: int,
    *,
    point_count: int = 0,
    coin_count: int = 0,
) -> None:
    """Require one unambiguous ticket-only control and no paid controls."""

    if ticket_count != 1 or point_count != 0 or coin_count != 0:
        raise UnsupportedAccessStrategyError(
            "Zeblack ticket entry UI is missing or ambiguous"
        )


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
        self._quota_resource: str | None = None
        self._access_consumption = AccessConsumption()
        self._live_access: ZeblackLiveAccessState | None = None
        self._preexisting_accessible = False
        self._ticket_click_attempted = False
        self._ticket_confirmation_state: str | None = None
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

    def get_initialize_timeout_ms(self, default_ms: int) -> int:
        # Quota entry may perform viewer -> chapter list -> viewer -> entry ->
        # content confirmation. Keep this overall bound finite while allowing
        # each bounded phase to use the existing page-change budget.
        return max(default_ms, 4 * self.page_change_timeout_ms)

    async def configure_run(self, page: Page, access_strategy: AccessStrategy) -> None:
        del page
        if access_strategy not in {"auto", "direct", "quota"}:
            raise UnsupportedAccessStrategyError(
                f"ZeblackAdapter does not support access_strategy={access_strategy!r}"
            )
        self._access_strategy = access_strategy
        self._quota_resource = None
        self._access_consumption = AccessConsumption()
        self._live_access = None
        self._preexisting_accessible = False
        self._ticket_click_attempted = False
        self._ticket_confirmation_state = None

    async def configure_quota_resource(
        self, page: Page, quota_resource: str | None
    ) -> None:
        del page
        if quota_resource not in {None, "work_ticket"}:
            raise UnsupportedAccessStrategyError(
                f"ZeblackAdapter does not support quota_resource={quota_resource!r}"
            )
        if quota_resource is not None and self._access_strategy != "quota":
            raise UnsupportedAccessStrategyError(
                "Zeblack quota_resource requires access_strategy='quota'"
            )
        if self._access_strategy == "quota" and quota_resource != "work_ticket":
            raise UnsupportedAccessStrategyError(
                "Zeblack quota access requires quota_resource='work_ticket'"
            )
        self._quota_resource = quota_resource

    def get_access_consumption(self) -> AccessConsumption:
        return self._access_consumption

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

    async def _visible_advertisement_signal(self, page: Page) -> bool:
        """Detect a visible ad spread without treating unrelated frames as AD."""

        try:
            controls = page.locator(
                ".-KWKsa_spread [data-fluct-ad-script-already-reserved], "
                ".-KWKsa_spread iframe"
            )
            result = await asyncio.wait_for(
                controls.evaluate_all(_ADVERTISEMENT_SCRIPT), timeout=2
            )
        except Exception:  # noqa: BLE001 - ad evidence must fail closed
            return False
        return result is True

    async def _last_page_signal(self, page: Page) -> bool:
        """Detect Zeblack's non-content volume/next-story spreads."""

        try:
            spreads = page.locator(".-KWKsa_spread")
            result = await asyncio.wait_for(
                spreads.evaluate_all(_LAST_PAGE_SCRIPT), timeout=2
            )
        except Exception:  # noqa: BLE001 - interstitial evidence must fail closed
            return False
        return result is True

    async def _snapshot(self, page: Page) -> dict[str, object]:
        current_url = str(page.url)
        viewer = parse_zeblack_viewer_url(current_url)
        rows = await self._safe_active_page_rows(page)
        terminal_signal = await self._visible_next_content_signal(page)
        advertisement_signal = await self._visible_advertisement_signal(page)
        last_page_signal = await self._last_page_signal(page)
        row_signature = self._row_signature(rows) if rows is not None else ()
        return {
            "url": current_url,
            "viewer": viewer,
            "rows": rows,
            "page_id": self._page_id(rows) if rows is not None else None,
            "terminal_signal": terminal_signal,
            "advertisement_signal": advertisement_signal,
            "last_page_signal": last_page_signal,
            "fingerprint": (
                current_url,
                row_signature,
                tuple(item[1] for item in row_signature),
                terminal_signal,
                advertisement_signal,
                last_page_signal,
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

    async def _wait_for_viewer_ready(self, page: Page) -> None:
        """Wait for viewer hydration before a same-page live-access preflight."""

        elapsed_ms = 0
        while elapsed_ms < self.page_change_timeout_ms:
            rows = await self._safe_active_page_rows(page)
            if rows:
                await self._wait_for_initial_content(page)
                return
            if await self._visible_access_gate(page):
                return
            await page.wait_for_timeout(100)
            elapsed_ms += 100
        raise PageChangeTimeoutError("Zeblack viewer did not become ready")

    async def _visible_access_gate(self, page: Page) -> bool:
        """Return whether a known access gate proves viewer hydration."""

        for text in (
            _TICKET_ENTRY_TEXT,
            _POINT_ENTRY_TEXT,
            _POINT_AND_COIN_ENTRY_TEXT,
            _COIN_ENTRY_TEXT,
            _PURCHASE_ENTRY_TEXT,
        ):
            if await self._visible_exact_text_count(page, text):
                return True
        return False

    async def _has_preexisting_content(self, page: Page) -> bool:
        """Return true only when content is already observable in the viewer."""

        rows = await self._safe_active_page_rows(page)
        if not rows:
            return False
        await self._wait_for_initial_content(page)
        return True

    @staticmethod
    def _exact_text_locator(page: Page, text: str) -> Locator:
        return page.get_by_text(text, exact=True)

    async def _visible_exact_text_count(self, page: Page, text: str) -> int:
        locator = self._exact_text_locator(page, text)
        count = await locator.count()
        visible = 0
        for index in range(count):
            if await locator.nth(index).is_visible():
                visible += 1
        return visible

    async def _ticket_control(self, page: Page) -> Locator:
        ticket = self._exact_text_locator(page, _TICKET_ENTRY_TEXT)
        point_count = await self._visible_exact_text_count(page, _POINT_ENTRY_TEXT)
        coin_count = await self._visible_exact_text_count(page, _COIN_ENTRY_TEXT)
        point_count += await self._visible_exact_text_count(
            page, _POINT_AND_COIN_ENTRY_TEXT
        )
        coin_count += await self._visible_exact_text_count(page, _PURCHASE_ENTRY_TEXT)
        visible_ticket_count = await self._visible_exact_text_count(
            page, _TICKET_ENTRY_TEXT
        )
        validate_zeblack_ticket_control_counts(
            visible_ticket_count,
            point_count=point_count,
            coin_count=coin_count,
        )
        control = ticket
        if await control.count() != 1:
            raise UnsupportedAccessStrategyError(
                "Zeblack ticket entry control is ambiguous"
            )
        if not await control.is_visible() or not await control.is_enabled():
            raise UnsupportedAccessStrategyError(
                "Zeblack ticket entry control is not visible and enabled"
            )
        tag_name = await control.evaluate("element => element.tagName.toLowerCase()")
        # The bundle-observed control is a styled div. Keep the allowed set
        # narrow and reject arbitrary text/container fallback clicks.
        if tag_name not in {"button", "a", "div"}:
            raise UnsupportedAccessStrategyError(
                f"Zeblack ticket entry control has unsupported tag: {tag_name}"
            )
        return control

    async def _wait_for_ticket_control(self, page: Page) -> Locator:
        """Wait briefly for the exact entry control, never for a fallback UI."""

        elapsed_ms = 0
        while elapsed_ms < self.page_change_timeout_ms:
            ticket_count = await self._visible_exact_text_count(page, _TICKET_ENTRY_TEXT)
            point_count = await self._visible_exact_text_count(page, _POINT_ENTRY_TEXT)
            point_count += await self._visible_exact_text_count(
                page, _POINT_AND_COIN_ENTRY_TEXT
            )
            coin_count = await self._visible_exact_text_count(page, _COIN_ENTRY_TEXT)
            coin_count += await self._visible_exact_text_count(page, _PURCHASE_ENTRY_TEXT)
            if ticket_count == 1:
                return await self._ticket_control(page)
            if ticket_count > 1 or point_count or coin_count:
                validate_zeblack_ticket_control_counts(
                    ticket_count,
                    point_count=point_count,
                    coin_count=coin_count,
                )
            await page.wait_for_timeout(100)
            elapsed_ms += 100
        raise UnsupportedAccessStrategyError(
            "Zeblack ticket entry UI did not expose one exact visible control"
        )

    async def _visible_dialog_count(self, page: Page) -> int:
        dialogs = page.locator('[role="dialog"], dialog')
        visible = 0
        for index in range(await dialogs.count()):
            if await dialogs.nth(index).is_visible():
                visible += 1
        return visible

    async def _enter_with_work_ticket(self, page: Page) -> None:
        if self._ticket_click_attempted:
            raise UnsupportedAccessStrategyError(
                "Zeblack ticket action was already attempted"
            )
        if self._initial_viewer is None:
            raise UnknownPageStateError("Zeblack viewer identity is unavailable")
        control = await self._wait_for_ticket_control(page)
        current = parse_zeblack_viewer_url(str(page.url))
        if current is None or current.key != self._initial_viewer.key:
            raise UnsupportedAccessStrategyError(
                "Zeblack ticket entry control is not in the target chapter"
            )

        self._ticket_click_attempted = True
        self._ticket_confirmation_state = "click_attempted"
        await control.click(timeout=self.page_change_timeout_ms)
        if await self._visible_dialog_count(page):
            # No ticket-specific confirmation dialog was found in the current
            # frontend bundle. Never confirm an unrecognized dialog.
            self._ticket_confirmation_state = "unknown_dialog"
            raise UnsupportedAccessStrategyError(
                "Zeblack ticket confirmation dialog is unknown"
            )

        try:
            await self._wait_for_initial_content(page)
            current = parse_zeblack_viewer_url(str(page.url))
            if current is None or current.key != self._initial_viewer.key:
                raise UnsupportedAccessStrategyError(
                    "Zeblack ticket entry navigated to a different chapter"
                )
        except BaseException:
            self._ticket_confirmation_state = "unconfirmed"
            raise

        self._ticket_confirmation_state = "confirmed"
        self._access_consumption = AccessConsumption(
            consumed=True,
            resource="work_ticket",
            consumed_at=datetime.now(UTC),
        )

    async def _initialize_quota_entry(
        self, page: Page, *, entry_only: bool
    ) -> None:
        # Selecting a TICKET_AVAILABLE chapter and opening its viewer only
        # reveals the entry action. It does not consume a Work Ticket. The
        # consuming action is the exact "チケットを使って読む" control below;
        # the distinct point action must remain rejected by the fail-closed
        # control-count checks.
        if self._quota_resource != "work_ticket":
            raise UnsupportedAccessStrategyError(
                "Zeblack quota initialization requires work_ticket"
            )
        if self._initial_url is None or self._initial_viewer is None:
            raise UnknownPageStateError("Zeblack initial viewer identity is unavailable")
        await self._clear_source_cache()
        await self._wait_for_viewer_ready(page)
        try:
            self._live_access = await observe_zeblack_live_access(
                page,
                title_id=self._initial_viewer.title_id,
                chapter_id=self._initial_viewer.chapter_id,
                timeout_ms=self.page_change_timeout_ms,
            )
        except ZeblackLiveAccessError as exc:
            raise UnknownPageStateError(str(exc)) from exc

        await self._clear_source_cache()
        try:
            await page.goto(
                self._initial_url,
                wait_until="commit",
                timeout=self.page_change_timeout_ms,
            )
        except (PlaywrightTimeoutError, TimeoutError) as exc:
            raise PageChangeTimeoutError(
                "Zeblack viewer did not return after live access preflight"
            ) from exc
        current = parse_zeblack_viewer_url(str(page.url))
        if current is None or current.key != self._initial_viewer.key:
            raise UnknownPageStateError(
                "Zeblack viewer identity changed after live access preflight"
            )
        await self._wait_for_viewer_ready(page)

        assert self._live_access is not None
        if self._live_access.status_value == int(ConsumptionStatus.TICKET_AVAILABLE):
            await self._enter_with_work_ticket(page)
            return
        if self._live_access.status_value in {
            int(ConsumptionStatus.FREE),
            int(ConsumptionStatus.RENTAL),
        }:
            # A locked TICKET_AVAILABLE viewer can already contain stable
            # page_N placeholders before the ticket action.  Live protobuf
            # state is authoritative, so only treat preexisting content as
            # an already-granted entry after the live status says that no
            # Work Ticket is needed.
            if await self._has_preexisting_content(page):
                self._preexisting_accessible = True
                self._ticket_confirmation_state = "preexisting_accessible"
                if entry_only:
                    raise AccessResourceUnavailableError("work_ticket_not_needed")
                return
            if entry_only:
                raise AccessResourceUnavailableError("work_ticket_not_needed")
            await self._wait_for_initial_content(page)
            return
        if self._live_access.status_value in _TICKET_STATUS_VALUES:
            if self._live_access.ticket_available_ids:
                raise AccessResourceUnavailableError(
                    "work_ticket_not_available_for_chapter",
                    stop_resource_pass=False,
                )
            raise AccessResourceUnavailableError(
                "work_ticket_unavailable",
                stop_resource_pass=True,
            )
        raise UnknownPageStateError(
            f"Zeblack live access status is unknown: {self._live_access.status_value}"
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
        if self._access_strategy == "quota":
            await self._initialize_quota_entry(page, entry_only=False)
        else:
            await self._wait_for_initial_content(page)
        self._initial_context = await self.get_content_context(page)
        self._output_title = self._initial_context.title

    async def initialize_entry_only(self, page: Page) -> None:
        """Confirm Zeblack access without entering full capture readiness."""

        current_url = str(page.url)
        viewer = parse_zeblack_viewer_url(current_url)
        if viewer is None:
            raise ValueError("Zeblack page URL is not a strict viewer URL")
        self._initial_url = current_url
        self._initial_viewer = viewer
        self._transition_pending = False
        self._transition_stable = False
        self._transition_kind = "idle"
        self._capture_mode = "unavailable"
        self._initial_context = None
        if self._access_strategy == "quota":
            await self._initialize_quota_entry(page, entry_only=True)
        else:
            await self._wait_for_initial_content(page)
        self._initial_context = await self.get_content_context(page)

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
            and self._transition_kind in {"advertisement", "last_page"}
            and self._initial_viewer is not None
            and current.key == self._initial_viewer.key
            and (
                await self._visible_advertisement_signal(page)
                if self._transition_kind == "advertisement"
                else await self._last_page_signal(page)
            )
        ):
            return PageState.AD
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
        advertisement_ready = (
            self._transition_stable
            and self._transition_kind in {"advertisement", "last_page"}
        )
        if (
            (not rows and not advertisement_ready)
            or self._transition_pending
            or (
                self._transition_stable
                and self._transition_kind == "terminal_next_content"
            )
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
        if (
            snapshot.get("advertisement_signal") is True
            or snapshot.get("last_page_signal") is True
        ):
            return viewer.key == (
                self._initial_viewer.key if self._initial_viewer else viewer.key
            )
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
        if snapshot.get("advertisement_signal") is True:
            return "advertisement"
        if snapshot.get("last_page_signal") is True:
            return "last_page"
        return "unknown"

    async def collect_debug_metadata(self, page: Page) -> dict[str, Any]:
        try:
            rows = await self._safe_active_page_rows(page)
            active_indices = [int(row["page_index"]) for row in rows] if rows else []
        except Exception:  # noqa: BLE001 - diagnostics must not replace crawl behavior
            active_indices = list(self._last_active_indices)
        live_access = self._live_access
        return {
            "access_strategy": self._access_strategy,
            "quota_resource": self._quota_resource,
            "live_access": {
                "title_id": live_access.title_id,
                "chapter_id": live_access.chapter_id,
                "target_status": live_access.status_name,
                "target_status_value": live_access.status_value,
                "ticket_available_count": len(live_access.ticket_available_ids),
                "target_ticket_available": live_access.target_ticket_available,
            }
            if live_access is not None
            else None,
            "preexisting_accessible": self._preexisting_accessible,
            "ticket_click_attempted": self._ticket_click_attempted,
            "ticket_confirmation_state": self._ticket_confirmation_state,
            "access_consumption": {
                "consumed": self._access_consumption.consumed,
                "resource": self._access_consumption.resource,
                "consumed_at": (
                    self._access_consumption.consumed_at.isoformat()
                    if self._access_consumption.consumed_at is not None
                    else None
                ),
            },
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
