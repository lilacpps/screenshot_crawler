"""Comic DAYS horizontal free viewer adapter."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from playwright.async_api import Locator, Page

from screenshot_crawler.core.access_guard import AccessProfile
from screenshot_crawler.core.capture import CaptureResult
from screenshot_crawler.core.errors import (
    AccessConsumptionUnconfirmedError,
    AccessResourceUnavailableError,
    PageChangeTimeoutError,
    UnknownPageStateError,
    UnsupportedAccessStrategyError,
)
from screenshot_crawler.core.models import AccessStrategy, ContentContext, ContentIdentity
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.base import (
    AccessConsumption,
    SiteAdapter,
)
from screenshot_crawler.site_adapters.comicdays.access import comicdays_access_profile
from screenshot_crawler.site_adapters.comicdays.discovery import (
    _series_id_from_page,
    canonical_comicdays_episode_url,
    parse_comicdays_episode_url,
)
from screenshot_crawler.site_adapters.comicdays.live_access import (
    ComicDaysLiveAccessError,
    ComicDaysLiveAccessState,
    ComicDaysTargetIdentityMismatch,
    observe_comicdays_live_access,
    observe_comicdays_target_access,
)


def _supported_ticket_rental_term(row: dict[str, object]) -> bool:
    """Accept only the observed 72-hour episode rental contract."""

    status = row.get("status")
    term = status.get("rental_term") if isinstance(status, dict) else None
    return isinstance(term, int) and not isinstance(term, bool) and term == 72
from screenshot_crawler.site_adapters.comicdays.native_capture import (
    COMICDAYS_CAPTURE_HOOK,
    MAX_ROWS,
    reconstruct_jpeg,
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
    ticket_recovery_window_ms = 3_000

    def __init__(self) -> None:
        self._access_strategy: AccessStrategy = "auto"
        self._initial_url: str | None = None
        self._episode_id: str | None = None
        self._work_id: str | None = None
        self._title: str | None = None
        self._author: str | None = None
        self._terminal = False
        self._advance_pending = False
        self._advance_from_slider: int | None = None
        self._known_tail_slider: int | None = None
        self._known_nonbody_passes = 0
        self._last_transition_observation: dict[str, Any] = {}
        self._last_slider: int | None = None
        self._capture_debug: dict[str, Any] = {}
        self._selected_signature: tuple[Any, ...] | None = None
        self._quota_resource: str | None = None
        self._access_consumption = AccessConsumption()
        self._live_access: ComicDaysLiveAccessState | None = None
        self._ticket_click_attempted = False
        self._preexisting_accessible = False
        self._target_url: str | None = None
        self._expected_external_id: str | None = None

    def get_access_profile(self) -> AccessProfile:
        return comicdays_access_profile()

    def get_initialize_timeout_ms(self, default_ms: int) -> int:
        # Initialization can contain access observation, metadata, viewer
        # normalization, and (for quota) a finite post-click reconciliation.
        # Keep one finite Runner-facing upper bound for all of those stages.
        return max(
            default_ms,
            3 * self.page_change_timeout_ms + self.ticket_recovery_window_ms + 2_000,
        )

    async def configure_run(self, page: Page, access_strategy: AccessStrategy) -> None:
        del page
        if access_strategy not in {"auto", "direct", "quota"}:
            raise UnsupportedAccessStrategyError(
                f"ComicDaysAdapter does not support access_strategy={access_strategy!r}"
            )
        self._access_strategy = access_strategy
        self._quota_resource = None
        self._access_consumption = AccessConsumption()
        self._live_access = None
        self._ticket_click_attempted = False
        self._preexisting_accessible = False
        self._target_url = None

    async def configure_target_identity(self, external_id: str, work_key: str) -> None:
        # Work.work_key is a site-neutral Catalog identity. Comic DAYS native
        # series identity is observed from the target page and is not derived
        # from or compared with this value.
        del work_key
        self._expected_external_id = str(external_id)

    async def configure_quota_resource(self, page: Page, quota_resource: str | None) -> None:
        del page
        if quota_resource not in {None, "work_ticket"}:
            raise UnsupportedAccessStrategyError(
                f"ComicDaysAdapter does not support quota_resource={quota_resource!r}"
            )
        if quota_resource is not None and self._access_strategy != "quota":
            raise UnsupportedAccessStrategyError(
                "ComicDays quota_resource requires access_strategy='quota'"
            )
        if self._access_strategy == "quota" and quota_resource != "work_ticket":
            raise UnsupportedAccessStrategyError(
                "ComicDays quota access requires quota_resource='work_ticket'"
            )
        self._quota_resource = quota_resource

    def resolve_initial_navigation_url(self, source_url: str) -> str:
        self._target_url = canonical_comicdays_episode_url(source_url)
        self._episode_id = parse_comicdays_episode_url(self._target_url)
        if (
            self._access_strategy == "quota"
            and self._expected_external_id is not None
            and self._episode_id != self._expected_external_id
        ):
            raise AccessResourceUnavailableError(
                "comicdays_discovery_refresh_required"
            )
        return self._target_url

    def get_access_consumption(self) -> AccessConsumption:
        return self._access_consumption

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
        # The production hook owns completeness.  A non-empty row list can be
        # a partially-mounted spread, so never infer success from rows alone.
        complete = value.get("complete") is True
        value["complete"] = complete
        value["ready"] = complete and bool(value["rows"]) and all(
            row.get("renderReady") is True for row in value["rows"]
        )
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
        canonical_url = canonical_comicdays_episode_url(page.url)
        if self._target_url is not None and canonical_url != self._target_url:
            if self._access_strategy == "quota":
                raise AccessResourceUnavailableError(
                    "comicdays_discovery_refresh_required"
                )
            raise ValueError("Comic DAYS page URL did not match the requested target")
        self._initial_url, self._episode_id = canonical_url, episode_id
        self._work_id = await _series_id_from_page(page)
        if self._access_strategy == "quota":
            await self._initialize_ticket_entry(page, entry_only=False)
        else:
            try:
                self._live_access = await observe_comicdays_live_access(
                    page, series_id=self._work_id, episode_id=episode_id,
                    timeout_ms=self.page_change_timeout_ms,
                )
            except ComicDaysLiveAccessError as exc:
                raise UnknownPageStateError(str(exc)) from exc
            if self._live_access.access_mode not in {"free", "quota"}:
                raise UnsupportedAccessStrategyError(
                    "Comic DAYS episode is not currently free or under an active grant"
                )
            if self._live_access.access_mode == "quota" and self._live_access.grant_until is None:
                raise UnsupportedAccessStrategyError("Comic DAYS episode requires a Work Ticket")
            self._preexisting_accessible = True
        self._title, self._author = await self._read_metadata(page)
        self._terminal = False
        self._advance_pending = False
        self._advance_from_slider = None
        self._known_tail_slider = None
        self._known_nonbody_passes = 0
        self._selected_signature = None
        deadline = asyncio.get_running_loop().time() + self.page_change_timeout_ms / 1000
        try:
            async with asyncio.timeout_at(deadline):
                await self._normalize_viewer(page, deadline)
        except TimeoutError as exc:
            raise PageChangeTimeoutError("Comic DAYS viewer normalization exceeded its time bound") from exc

    async def initialize_entry_only(self, page: Page) -> None:
        """Perform only the bounded Work Ticket entry and confirmation."""

        episode_id = parse_comicdays_episode_url(page.url)
        if episode_id is None or (self._episode_id and episode_id != self._episode_id):
            if self._access_strategy == "quota":
                raise AccessResourceUnavailableError(
                    "comicdays_discovery_refresh_required"
                )
            raise ValueError("Comic DAYS entry page did not match the target episode")
        if self._access_strategy != "quota" or self._quota_resource != "work_ticket":
            raise UnsupportedAccessStrategyError(
                "Comic DAYS entry-only execution requires quota/work_ticket"
            )
        self._initial_url = canonical_comicdays_episode_url(page.url)
        self._episode_id = episode_id
        self._work_id = await _series_id_from_page(page)
        await self._initialize_ticket_entry(page, entry_only=True)

    async def _initialize_ticket_entry(self, page: Page, *, entry_only: bool) -> None:
        if self._work_id is None or self._episode_id is None:
            raise UnknownPageStateError("Comic DAYS target identity is unavailable")
        if self._ticket_click_attempted:
            raise UnsupportedAccessStrategyError(
                "Comic DAYS Work Ticket action was already attempted; retry is forbidden"
            )
        deadline = asyncio.get_running_loop().time() + self.page_change_timeout_ms / 1000
        try:
            state = await self._observe_live_access(page, deadline)
        except ComicDaysTargetIdentityMismatch as exc:
            raise AccessResourceUnavailableError(
                "comicdays_discovery_refresh_required"
            ) from exc
        except ComicDaysLiveAccessError as exc:
            raise UnknownPageStateError(str(exc)) from exc
        self._live_access = state
        if state.access_mode == "unknown":
            raise UnknownPageStateError(
                "Comic DAYS target access state was missing or ambiguous"
            )
        if state.access_mode != "quota":
            raise AccessResourceUnavailableError(
                "comicdays_discovery_refresh_required"
            )
        if state.ticket.is_charged and state.ticket.charged_at is None:
            raise UnknownPageStateError(
                "Comic DAYS charged ticket state omitted chargedAt"
            )
        if (
            state.rental_term_hours != 72
            or state.rental_term_seconds != 259200
            or not _supported_ticket_rental_term(state.row)
        ):
            raise AccessResourceUnavailableError(
                "comicdays_discovery_refresh_required", stop_resource_pass=True
            )
        if not state.ticket.is_charged:
            raise AccessResourceUnavailableError("work_ticket_cooldown")
        remaining = self._remaining_ms(deadline)
        if remaining <= 0:
            raise PageChangeTimeoutError("Comic DAYS ticket control inspection exceeded its time bound")
        try:
            control = await asyncio.wait_for(
                self._exact_ticket_control(page, deadline), timeout=remaining / 1000
            )
        except TimeoutError as exc:
            raise PageChangeTimeoutError("Comic DAYS ticket control inspection exceeded its time bound") from exc
        previous_charged_at = state.ticket.charged_at
        self._ticket_click_attempted = True
        try:
            remaining = self._remaining_ms(deadline)
            if remaining <= 0:
                raise PageChangeTimeoutError("Comic DAYS Work Ticket entry exceeded its time bound")
            await control.click(timeout=remaining, no_wait_after=True)
            confirmed = await self._poll_consumption(page, previous_charged_at, deadline)
            if not confirmed:
                raise AccessConsumptionUnconfirmedError(
                    "Comic DAYS Work Ticket consumption was not confirmed"
                )
        except BaseException:
            # The click may have reached the site even when Playwright reports
            # timeout/cancellation. Reconcile only by bounded read-only polls;
            # never dispatch a second click. Preserve the original exception.
            recovery_deadline = asyncio.get_running_loop().time() + self.ticket_recovery_window_ms / 1000
            try:
                await self._poll_consumption(page, previous_charged_at, recovery_deadline)
            except BaseException as recovery_error:  # noqa: BLE001 - preserve the original click error
                self._capture_debug["ticket_recovery_error"] = type(recovery_error).__name__
            raise

    async def _observe_live_access(self, page: Page, deadline: float) -> ComicDaysLiveAccessState:
        remaining = self._remaining_ms(deadline)
        if remaining <= 0:
            raise ComicDaysLiveAccessError("Comic DAYS access observation exceeded its time bound")
        return await asyncio.wait_for(
            observe_comicdays_target_access(
                page, series_id=self._work_id or "", episode_id=self._episode_id or "",
                timeout_ms=remaining,
            ),
            timeout=remaining / 1000,
        )

    async def _reobserve_consumption(
        self, page: Page, previous_charged_at: datetime | None, deadline: float
    ) -> bool:
        if self._work_id is None or self._episode_id is None:
            return False
        try:
            state = await self._observe_live_access(page, deadline)
        except Exception:  # noqa: BLE001 - post-click state is fail-closed
            return False
        self._live_access = state
        row = state.row
        purchase = row.get("purchase_info")
        status = row.get("status")
        if not isinstance(purchase, dict) or not isinstance(status, dict):
            return False
        now = datetime.now(UTC)
        charged_at = state.ticket.charged_at
        positive = (
            state.viewer_unlocked
            and state.ticket.is_charged is False
            and charged_at is not None
            and charged_at > now
            and previous_charged_at is not None
            and charged_at > previous_charged_at
            and (self._target_url is None or state.canonical_url == self._target_url)
            and state.series_id == self._work_id
            and state.episode_id == self._episode_id
            and state.normal_viewer_count == 1
            and state.normal_viewer_visible
            and state.normal_viewer_json == (
                canonical_comicdays_episode_url(
                    f"https://comic-days.com/episode/{self._episode_id}"
                ) + ".json"
            )
            and state.private_viewer_count == 0
            and state.ticket_control_count == 0
        )
        if not positive:
            return False
        # Latch the first positive native debit/grant observation exactly once.
        # Viewer loading is a separate, read-only stage and must not replace or
        # reset the timestamp used by generic Batch resource accounting.
        if not self._access_consumption.consumed:
            self._access_consumption = AccessConsumption(
                consumed=True, resource="work_ticket", consumed_at=datetime.now(UTC)
            )
        return True

    async def _poll_consumption(
        self, page: Page, previous_charged_at: datetime | None, deadline: float
    ) -> bool:
        """Poll read-only state after a click without ever retrying the click."""

        while self._remaining_ms(deadline) > 0:
            if not self._access_consumption.consumed:
                await self._reobserve_consumption(page, previous_charged_at, deadline)
            # Target-local debit/unlock confirmation is the grant entry
            # contract.  Capture readiness belongs to normal initialize's
            # existing _normalize_viewer path and must not consume this
            # confirmation budget or make grant-only success depend on the
            # production capture hook.
            if self._access_consumption.consumed:
                return True
            delay = min(200, self._remaining_ms(deadline))
            if delay <= 0:
                break
            await page.wait_for_timeout(delay)
        if self._access_consumption.consumed:
            raise PageChangeTimeoutError("Comic DAYS post-grant viewer was not render-ready")
        return False

    async def _exact_ticket_control(self, page: Page, deadline: float) -> Locator:
        if self._episode_id is None or self._work_id is None:
            raise UnknownPageStateError("Comic DAYS ticket target identity is unavailable")
        if parse_comicdays_episode_url(str(page.url)) != self._episode_id:
            raise AccessResourceUnavailableError(
                "comicdays_discovery_refresh_required"
            )
        # The locked access page uses the observed private viewer scope.  The
        # unlocked capture viewer is a different class and is validated after
        # the grant transition.
        viewer = page.locator("section.private-viewer.js-viewer[data-json-url]")
        if await viewer.count() != 1:
            raise AccessResourceUnavailableError("work_ticket_viewer_scope_ambiguous")
        expected_json_url = canonical_comicdays_episode_url(
            f"https://comic-days.com/episode/{self._episode_id}"
        ) + ".json"
        if await viewer.get_attribute("data-json-url") != expected_json_url:
            raise AccessResourceUnavailableError(
                "comicdays_discovery_refresh_required"
            )
        container = viewer.locator("div.read-button-container")
        if await container.count() != 1:
            raise AccessResourceUnavailableError("work_ticket_access_container_ambiguous")
        ticket = container.locator(
            'button[data-test-id="use-series-ticket-button"][data-ticket-type="series"]'
        )
        if await ticket.count() != 1:
            raise AccessResourceUnavailableError("work_ticket_control_ambiguous")
        remaining = min(1_000, self._remaining_ms(deadline))
        if remaining <= 0:
            raise PageChangeTimeoutError("Comic DAYS ticket control inspection exceeded its time bound")
        if not await ticket.is_visible(timeout=remaining) or not await ticket.is_enabled(timeout=remaining):
            raise AccessResourceUnavailableError("work_ticket_control_not_actionable")
        if " ".join((await ticket.inner_text(timeout=remaining)).split()) != "\u4f5c\u54c1\u30c1\u30b1\u30c3\u30c8\u3067\u8aad\u3080\uff08\u7121\u6599\uff09":
            raise AccessResourceUnavailableError("work_ticket_control_label_mismatch")
        if await ticket.get_attribute("data-ticket-rental-id") != self._episode_id:
            raise AccessResourceUnavailableError(
                "comicdays_discovery_refresh_required"
            )
        contract = page.locator(
            '.js-readable-products-pagination[data-type="episode"][data-aggregate-id]'
        )
        if await contract.count() != 1:
            raise AccessResourceUnavailableError(
                "work_ticket_contract_unknown", stop_resource_pass=True
            )
        raw_term = await contract.get_attribute("data-rental-term")
        if raw_term is None or not raw_term.isdigit():
            raise AccessResourceUnavailableError(
                "work_ticket_contract_unknown", stop_resource_pass=True
            )
        if int(raw_term) != 259200:
            raise AccessResourceUnavailableError(
                "comicdays_discovery_refresh_required", stop_resource_pass=True
            )
        # The observed page binds work identity on a sibling listing surface;
        # controls are separately scoped to the target viewer's access area.
        areas = page.locator('[data-aggregate-id][data-type="episode"]')
        if await areas.count() != 1:
            raise AccessResourceUnavailableError("work_ticket_access_area_missing")
        panel_identity = await areas.get_attribute("data-aggregate-id")
        if panel_identity != self._work_id:
            raise AccessResourceUnavailableError(
                "comicdays_discovery_refresh_required"
            )
        if await ticket.get_attribute("data-behaviour") != "button":
            raise AccessResourceUnavailableError("work_ticket_control_operation_mismatch")
        title = await ticket.get_attribute("title") or ""
        if any(term in title for term in ("\u8cfc\u5165", "\u30dd\u30a4\u30f3\u30c8", "\u30ec\u30f3\u30bf\u30eb")):
            raise AccessResourceUnavailableError("work_ticket_control_paid_attribute")
        if await ticket.get_attribute("data-buy-price") is not None:
            raise AccessResourceUnavailableError("work_ticket_control_cost_attribute")
        if await ticket.get_attribute("onclick") is not None:
            raise AccessResourceUnavailableError("work_ticket_control_handler_ambiguous")
        # A visible premium ticket control in the same page is a distinct
        # resource and makes this entry ambiguous; it is never a fallback.
        premium = container.locator('[data-test-id="use-premium-ticket-button"]')
        if await premium.count() > 1:
            raise AccessResourceUnavailableError("premium_ticket_control_ambiguous")
        remaining = min(1_000, self._remaining_ms(deadline))
        if remaining <= 0:
            raise PageChangeTimeoutError("Comic DAYS premium control inspection exceeded its time bound")
        if await premium.count() == 1 and await premium.is_visible(timeout=remaining):
            raise AccessResourceUnavailableError("premium_ticket_control_visible")
        purchase = container.locator('[data-test-id="purchase-button"]')
        if await purchase.count() > 1:
            raise AccessResourceUnavailableError("purchase_control_ambiguous")
        if await purchase.count() == 1:
            purchase_price = await purchase.get_attribute("data-buy-price")
            if purchase_price is None:
                raise AccessResourceUnavailableError("purchase_control_identity_ambiguous")
        # A separate purchase control may coexist in the same verified access
        # area. It is checked only for scope and is never clicked or used as a
        # fallback.
        return ticket

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
                tuple(
                    round(float(row.get("rect", {}).get(key, 0)), 3)
                    for key in ("x", "y", "width", "height")
                ) if isinstance(row.get("rect"), dict) else (),
                row.get("sliderNow"),
                row.get("sliderLast"),
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
        slider = self._valid_slider_state(state)
        if slider is not None:
            observation = await self._nonbody_observation(page)
            current, last = slider
            if (
                self._known_tail_slider == current
                and self._observation_matches_slider(observation, slider)
                and current < last
                and self._is_observed_tail(observation)
            ):
                return PageState.AD
        viewer = page.locator(self.viewer_selector)
        if await viewer.count() and await viewer.is_visible(timeout=500):
            return PageState.LOADING
        return PageState.UNKNOWN

    async def get_capture_targets(self, page: Page) -> tuple[Locator, ...]:
        state = await self._active(page)
        rows = state.get("rows", [])
        if not rows or state.get("complete") is not True or state.get("ready") is not True:
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
        if not rows or len(rows) > MAX_ROWS or state.get("complete") is not True or state.get("ready") is not True:
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
        sources: list[tuple[dict[str, Any], bytes]] = []
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
            sources.append((plan, raw))
        after = await self._active(page)
        if after.get("ready") is not True or self._signature(after.get("rows", [])) != before_signature:
            raise LookupError("Comic DAYS capture selection changed during native capture")
        jpeg_results = [reconstruct_jpeg(raw, plan) for plan, raw in sources]
        if all(result is not None for result in jpeg_results):
            after_reconstruction = await self._active(page)
            if (
                after_reconstruction.get("ready") is not True
                or self._signature(after_reconstruction.get("rows", [])) != before_signature
            ):
                raise LookupError("Comic DAYS capture selection changed during JPEG reconstruction")
            results = tuple(result for result in jpeg_results if result is not None)
            self._capture_debug = {
                "native": True, "capture_mode": "jpeg", "parts": len(results),
            }
            return results
        png_results = [reconstruct_png(raw, plan) for plan, raw in sources]
        if any(result is None for result in png_results):
            after_reconstruction = await self._active(page)
            if (
                after_reconstruction.get("ready") is not True
                or self._signature(after_reconstruction.get("rows", [])) != before_signature
            ):
                raise LookupError("Comic DAYS capture selection changed during PNG fallback")
            self._capture_debug = {
                "native": False, "capture_mode": "locator_fallback",
                "reason": "jpeg_and_png_reconstruction_failed",
            }
            return None
        after_reconstruction = await self._active(page)
        if (
            after_reconstruction.get("ready") is not True
            or self._signature(after_reconstruction.get("rows", [])) != before_signature
        ):
            raise LookupError("Comic DAYS capture selection changed during PNG reconstruction")
        results = tuple(result for result in png_results if result is not None)
        self._capture_debug = {
            "native": True, "capture_mode": "reconstructed_png", "parts": len(results),
        }
        return results

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

    async def _nonbody_observation(self, page: Page, *, timeout_ms: int = 500) -> dict[str, Any]:
        """Return only the observed, bounded non-body tail markers.

        Comic DAYS places one back-link page and one ad page after the final
        body spread.  They are treated as an advertisement equivalent only
        when their exact classes, resource counts, and on-screen geometry all
        match the live observation.  This intentionally does not classify
        arbitrary blank, paid, or access panels as skips.
        """

        script = """
        (expected) => {
          const visibleOnScreen = (element) => {
            const rect = element.getBoundingClientRect();
            const style = getComputedStyle(element);
            return rect.width > 0 && rect.height > 0 && rect.right > 0 && rect.bottom > 0 &&
              rect.left < window.innerWidth && rect.top < window.innerHeight &&
              style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
          };
          const summary = (element) => ({
            className: element.className || '',
            id: element.id || null,
            onScreen: visibleOnScreen(element),
            canvasCount: element.querySelectorAll('canvas').length,
            imageCount: element.querySelectorAll('img').length,
            iframeCount: element.querySelectorAll('iframe').length,
            childCount: element.children.length,
            childTags: [...element.children].map(child => child.tagName.toLowerCase()),
            childClasses: [...element.children].map(child => child.className || ''),
          });
          const viewers = [...document.querySelectorAll('section.viewer.js-viewer[data-json-url]')];
          const viewer = viewers.length === 1 ? viewers[0] : null;
          const baseUrl = location.href.split('#')[0];
          const expectedJson = expected || (baseUrl.endsWith('/') ? baseUrl.slice(0, -1) : baseUrl) + '.json';
          const scopeValid = !!viewer && viewer.getAttribute('data-json-url') === expectedJson;
          const areas = viewer ? [...viewer.querySelectorAll('.page-area.js-page-area')] : [];
          const sliderNow = Number(document.querySelector('.js-viewer-slider-pagenum-now')?.textContent?.trim());
          const sliderLast = Number(document.querySelector('.js-viewer-slider-pagenum-last')?.textContent?.trim());
          const isBack = element => element.classList.contains('page') && element.classList.contains('js-page') &&
            element.classList.contains('back-link-page') && element.classList.contains('js-link-page') &&
            element.classList.contains('js-back-link-page') && element.children.length === 1 &&
            element.children[0].tagName === 'DIV' && element.children[0].className === 'link-page-content' &&
            element.querySelectorAll('img').length === 2 && element.querySelectorAll('canvas,iframe').length === 0;
          const isAd = element => element.classList.contains('page') && element.classList.contains('js-page') &&
            element.classList.contains('js-page-ad') && element.children.length === 1 &&
            element.children[0].tagName === 'DIV' && element.children[0].className === 'ad-nav-area-wrap page-content' &&
            element.querySelectorAll('iframe').length === 2 && element.querySelectorAll('canvas,img').length === 0;
          const isColophon = element => element?.id === 'viewer-colophon' &&
            element.children.length === 1 &&
            element.children[0].classList.contains('back-matter') &&
            element.children[0].classList.contains('js-back-matter') &&
            element.children[0].children.length === 1 &&
            element.children[0].children[0].tagName === 'DIV' &&
            element.children[0].children[0].className === 'back-matter-content' &&
            element.querySelectorAll('img').length === 10 &&
            element.querySelectorAll('canvas,iframe').length === 0;
          const layouts = Number.isFinite(sliderLast) ? [
            {name: 'legacy-tail', body: sliderLast - 4, back: sliderLast - 3, ad: sliderLast - 2, colophon: sliderLast - 1},
            {name: 'leading-area-tail', body: sliderLast - 3, back: sliderLast - 2, ad: sliderLast - 1, colophon: sliderLast},
          ] : [];
          const layoutFor = layout => {
            const back = areas[layout.back], ad = areas[layout.ad], colophon = areas[layout.colophon];
            return !!back && !!ad && !!colophon &&
              [...back.children].filter(isBack).length === 1 &&
              [...ad.children].filter(isAd).length === 1 && isColophon(colophon);
          };
          const layout = layouts.find(layoutFor) || null;
          const backArea = layout ? areas[layout.back] : null;
          const adArea = layout ? areas[layout.ad] : null;
          const colophonArea = layout ? areas[layout.colophon] : null;
          const pageChildren = areas.flatMap((area) => [...area.children]
            .filter((element) => element.classList.contains('page') && element.classList.contains('js-page'))
            .map((element) => ({element, areaIndex: areas.indexOf(area)})));
          const directPageChildren = viewer ? [...viewer.children]
            .filter((element) => element.classList.contains('page') && element.classList.contains('js-page'))
            .map((element) => ({element, areaIndex: null})) : [];
          const knownPage = element => isBack(element) || isAd(element);
          const knownArea = (area, index) => {
            if (!layout) return false;
            if (index === layout.body) return area.querySelectorAll('canvas.page-image.js-page-image').length > 0;
            if (index === layout.back) return [...area.children].filter(isBack).length === 1;
            if (index === layout.ad) return [...area.children].filter(isAd).length === 1;
            if (index === layout.colophon) return isColophon(area);
            return false;
          };
          const expectedTailIndices = layout
            ? new Set([layout.body, layout.back, layout.ad, layout.colophon]) : new Set();
          const unknownOnScreenAreas = areas.filter((area, index) =>
            visibleOnScreen(area) && (!expectedTailIndices.has(index) || !knownArea(area, index))
          ).map((area) => ({...summary(area), areaIndex: areas.indexOf(area)}));
          const otherOnScreen = [...pageChildren, ...directPageChildren]
            .filter(({element}) => visibleOnScreen(element) && !knownPage(element));
          const back = backArea ? [...backArea.children].filter(isBack).map((element) => ({...summary(element), areaIndex: areas.indexOf(backArea)})) : [];
          const ads = adArea ? [...adArea.children].filter(isAd).map((element) => ({...summary(element), areaIndex: areas.indexOf(adArea)})) : [];
          const colophon = colophonArea && isColophon(colophonArea) ?
            {...summary(colophonArea), areaIndex: areas.indexOf(colophonArea)} : null;
          return {
            scopeValid, viewerCount: viewers.length,
            sliderNow: Number.isFinite(sliderNow) ? sliderNow : null,
            sliderLast: Number.isFinite(sliderLast) ? sliderLast : null,
            activePageAreas: areas.map((element) => ({
              areaIndex: areas.indexOf(element),
              id: element.id || null, className: element.className || '',
              dataIndex: element.getAttribute('data-area-index') || element.getAttribute('data-page-index'),
              onScreen: visibleOnScreen(element),
              children: [...element.children].slice(0, 8).map(summary),
            })),
            tailVariant: layout?.name || null, tailIndices: layout ? {body: layout.body, back: layout.back, ad: layout.ad, colophon: layout.colophon} : null,
            back, ads,
            otherOnScreen: otherOnScreen.map(({element, areaIndex}) => ({...summary(element), areaIndex})),
            unknownOnScreenAreas, colophon,
          };
        }
        """
        try:
            value = await asyncio.wait_for(
                page.evaluate(script, (f"https://comic-days.com/episode/{self._episode_id}.json" if self._episode_id else None)),
                timeout=max(0.05, timeout_ms / 1000)
            )
        except TimeoutError as exc:
            raise PageChangeTimeoutError("Comic DAYS non-body observation exceeded its time bound") from exc
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _valid_slider_state(state: dict[str, Any]) -> tuple[int, int] | None:
        current, last = state.get("sliderNow"), state.get("sliderLast")
        if not isinstance(current, int) or isinstance(current, bool):
            return None
        if not isinstance(last, int) or isinstance(last, bool) or not 1 <= current <= last:
            return None
        return current, last

    @staticmethod
    def _is_observed_tail(observation: dict[str, Any]) -> bool:
        back, ads = observation.get("back"), observation.get("ads")
        if not isinstance(back, list) or not isinstance(ads, list) or len(back) != 1 or len(ads) != 1:
            return False
        back_item, ad_item = back[0], ads[0]
        last = observation.get("sliderLast")
        if not isinstance(last, int):
            return False
        variant = observation.get("tailVariant")
        expected = {
            "legacy-tail": (last - 3, last - 2),
            "leading-area-tail": (last - 2, last - 1),
        }.get(variant)
        if expected is None:
            return False
        return (
            isinstance(back_item, dict) and isinstance(ad_item, dict)
            and observation.get("scopeValid") is True
            and (back_item.get("areaIndex"), ad_item.get("areaIndex")) == expected
            and back_item.get("onScreen") is True and ad_item.get("onScreen") is True
            and back_item.get("canvasCount") == 0 and back_item.get("imageCount") == 2
            and back_item.get("iframeCount") == 0
            and back_item.get("childCount") == 1
            and back_item.get("childTags") == ["div"]
            and back_item.get("childClasses") == ["link-page-content"]
            and ad_item.get("canvasCount") == 0 and ad_item.get("iframeCount") == 2
            and ad_item.get("imageCount") == 0
            and ad_item.get("childCount") == 1
            and ad_item.get("childTags") == ["div"]
            and ad_item.get("childClasses") == ["ad-nav-area-wrap page-content"]
            and observation.get("unknownOnScreenAreas") == []
            and observation.get("otherOnScreen") == []
        )

    @staticmethod
    def _is_observed_colophon(observation: dict[str, Any]) -> bool:
        colophon = observation.get("colophon")
        back, ads = observation.get("back"), observation.get("ads")
        last = observation.get("sliderLast")
        variant = observation.get("tailVariant")
        expected = {
            "legacy-tail": (last - 3, last - 2) if isinstance(last, int) else None,
            "leading-area-tail": (last - 2, last - 1) if isinstance(last, int) else None,
        }.get(variant)
        back_item = back[0] if isinstance(back, list) and len(back) == 1 else None
        ad_item = ads[0] if isinstance(ads, list) and len(ads) == 1 else None
        resources_valid = (
            expected is not None
            and isinstance(back_item, dict) and isinstance(ad_item, dict)
            and (back_item.get("areaIndex"), ad_item.get("areaIndex")) == expected
            and back_item.get("canvasCount") == 0
            and back_item.get("imageCount") == 2
            and back_item.get("iframeCount") == 0
            and back_item.get("childCount") == 1
            and back_item.get("childTags") == ["div"]
            and back_item.get("childClasses") == ["link-page-content"]
            and ad_item.get("canvasCount") == 0
            and ad_item.get("imageCount") == 0
            and ad_item.get("iframeCount") == 2
            and ad_item.get("childCount") == 1
            and ad_item.get("childTags") == ["div"]
            and ad_item.get("childClasses") == ["ad-nav-area-wrap page-content"]
        )
        return (
            isinstance(colophon, dict)
            and observation.get("scopeValid") is True
            and variant in {"legacy-tail", "leading-area-tail"}
            and isinstance(last, int)
            and resources_valid
            and colophon.get("areaIndex") == (last - 1 if variant == "legacy-tail" else last)
            and colophon.get("onScreen") is True
            and colophon.get("canvasCount") == 0
            and colophon.get("imageCount") == 10
            and colophon.get("iframeCount") == 0
            and colophon.get("childCount") == 1
            and colophon.get("childTags") == ["div"]
            and colophon.get("childClasses") == ["back-matter js-back-matter"]
            and observation.get("unknownOnScreenAreas") == []
            and observation.get("otherOnScreen") == []
        )

    @staticmethod
    def _observation_matches_slider(
        observation: dict[str, Any], slider: tuple[int, int] | None
    ) -> bool:
        return (
            slider is not None
            and observation.get("sliderNow") == slider[0]
            and observation.get("sliderLast") == slider[1]
        )

    @staticmethod
    def _nonbody_signature(observation: dict[str, Any], state: dict[str, Any]) -> tuple[Any, ...]:
        def marker(value: Any) -> tuple[Any, ...]:
            if not isinstance(value, dict):
                return ()
            return (
                value.get("className"), value.get("id"), value.get("onScreen"),
                value.get("areaIndex"),
                value.get("canvasCount"), value.get("imageCount"), value.get("iframeCount"),
            )

        return (
            state.get("sliderNow"), state.get("sliderLast"), state.get("colophon"),
            observation.get("sliderNow"), observation.get("sliderLast"),
            tuple(marker(item) for item in observation.get("back", []) if isinstance(item, dict)),
            tuple(marker(item) for item in observation.get("ads", []) if isinstance(item, dict)),
            marker(observation.get("colophon")),
            tuple(marker(item) for item in observation.get("otherOnScreen", []) if isinstance(item, dict)),
            tuple(marker(item) for item in observation.get("unknownOnScreenAreas", []) if isinstance(item, dict)),
        )

    async def go_next(self, page: Page) -> None:
        state = await self._active(page, timeout_ms=1_000)
        slider = self._valid_slider_state(state)
        if slider is None:
            raise PageChangeTimeoutError("Comic DAYS forward transition had an invalid slider")
        button = page.locator(self.forward_selector)
        if await button.count() != 1 or not await button.is_visible(timeout=1_000):
            raise PageChangeTimeoutError("Comic DAYS forward control was not uniquely visible")
        values = " ".join(str(value or "") for value in [await button.inner_text(timeout=1_000), await button.get_attribute("aria-label", timeout=1_000), await button.get_attribute("title", timeout=1_000), await button.get_attribute("href", timeout=1_000), await button.get_attribute("class", timeout=1_000)])
        href = await button.get_attribute("href", timeout=1_000)
        if _FORBIDDEN.search(values) or (href and "/episode/" in href):
            raise PageChangeTimeoutError("Comic DAYS forward control failed safety validation")
        self._advance_from_slider = slider[0]
        self._advance_pending = True
        await button.click(timeout=1_000, no_wait_after=True)

    async def wait_for_change(self, page: Page, previous_identity: ContentIdentity | None) -> None:
        deadline = asyncio.get_running_loop().time() + self.page_change_timeout_ms / 1000
        stable, previous = 0, None
        nonbody_stable, nonbody_previous = 0, None
        while self._remaining_ms(deadline) > 0:
            observed_episode = parse_comicdays_episode_url(page.url)
            if self._episode_id and observed_episode and observed_episode != self._episode_id:
                self._advance_pending = False
                self._advance_from_slider = None
                return
            state = await self._active(page)
            slider_state = self._valid_slider_state(state)
            advance_from = self._advance_from_slider
            if self._advance_pending and slider_state is not None and advance_from is not None:
                current, last = slider_state
                if current < advance_from or current > last:
                    raise PageChangeTimeoutError("Comic DAYS viewer slider did not advance monotonically")
                if current > advance_from:
                    if state.get("rows"):
                        observation = None
                    else:
                        observation = await self._nonbody_observation(page, timeout_ms=min(500, self._remaining_ms(deadline)))
                        if not self._observation_matches_slider(observation, slider_state):
                            nonbody_stable, nonbody_previous = 0, None
                            observation = None
                        else:
                            self._last_transition_observation = dict(observation)
                            signature = self._nonbody_signature(observation, state)
                            nonbody_stable = nonbody_stable + 1 if signature == nonbody_previous else 1
                            nonbody_previous = signature
                    if (
                        observation is not None
                        and nonbody_stable >= 2
                        and state.get("colophon") is True
                        and (
                            (current == last and self._known_tail_slider in {last - 2, last - 1})
                            or (current == last - 1 and self._known_tail_slider is None)
                        )
                        and self._is_observed_colophon(observation)
                    ):
                        self._terminal = True
                        self._advance_pending = False
                        self._advance_from_slider = None
                        return
                    elif (
                        observation is not None
                        and nonbody_stable >= 2
                        and current in {last - 2, last - 1}
                        and self._is_observed_tail(observation)
                    ):
                        if self._known_tail_slider is not None or self._known_nonbody_passes >= 1:
                            raise PageChangeTimeoutError("Comic DAYS repeated known tail transition")
                        self._known_tail_slider = current
                        self._known_nonbody_passes += 1
                        self._advance_pending = False
                        self._advance_from_slider = None
                        return
            if (
                state.get("rows") and state.get("ready") is True
                and slider_state is not None
                and (advance_from is None or slider_state[0] > advance_from)
            ):
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
                        self._advance_from_slider = None
                        return
                else:
                    stable, previous = 0, None
            await page.wait_for_timeout(min(100, self._remaining_ms(deadline)))
        raise PageChangeTimeoutError("Comic DAYS page did not change within the timeout")

    async def collect_debug_metadata(self, page: Page) -> dict[str, Any]:
        del page
        return {**self._capture_debug, "last_transition_observation": self._last_transition_observation}

    def get_output_metadata(self) -> dict[str, str | None]:
        return {"title": self._title, "author": self._author, "order": None, "genre": "漫画"}
