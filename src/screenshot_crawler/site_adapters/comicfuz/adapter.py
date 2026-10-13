"""Anonymous free-chapter viewer support for ComicFUZ."""

from __future__ import annotations

import asyncio
import base64
import binascii
import functools
import re
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from screenshot_crawler.core.access_guard import AccessProfile
from screenshot_crawler.core.capture import CaptureResult, capture_png_bytes
from screenshot_crawler.core.errors import (
    PageChangeTimeoutError,
    UnknownPageStateError,
    UnsupportedAccessStrategyError,
)
from screenshot_crawler.core.models import AccessStrategy, ContentContext, ContentIdentity
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.base import SiteAdapter
from screenshot_crawler.site_adapters.comicfuz.access import comicfuz_access_profile
from screenshot_crawler.site_adapters.comicfuz.discovery import (
    SITE_HOST,
    ComicFuzDiscoveryAdapter,
    parse_comicfuz_episode_url,
    parse_comicfuz_work_url,
)
from screenshot_crawler.site_adapters.comicfuz.native_capture import (
    capture_comicfuz_source_bytes,
)
from screenshot_crawler.watchlist.models import WatchlistTarget

_COMPOSITE_ID = re.compile(r"^(?P<work>[0-9]+):(?P<chapter>[0-9]+)$")
_PAGE_LABEL = re.compile(r"^page_(?P<number>[0-9]+)$")
_BLOB_PREFIX = "blob:https://comic-fuz.com/"
def _cleanup_observer_on_failure(
    method: Callable[..., Awaitable[Any]],
) -> Callable[..., Awaitable[Any]]:
    """Release bounded response reads when an adapter operation aborts."""

    @functools.wraps(method)
    async def wrapped(self: ComicFuzAdapter, page: Page, *args: Any, **kwargs: Any) -> Any:
        try:
            return await method(self, page, *args, **kwargs)
        except BaseException:
            await self._cleanup_source_observer()
            raise

    return wrapped


def _classify_viewer_pages(pages: object) -> tuple[tuple[int, ...], int]:
    """Accept only the live-verified body-prefix / linked-extra / reader-tail shape."""

    if not isinstance(pages, list) or len(pages) < 4:
        raise UnknownPageStateError("ComicFUZ viewer page-role manifest is incomplete")
    roles: list[str] = []
    for slot in pages:
        if not isinstance(slot, dict):
            raise UnknownPageStateError("ComicFUZ viewer page-role slot is malformed")
        role = slot.get("role")
        if role == "image":
            extra = slot.get("is_extra")
            linked = slot.get("has_link")
            width, height = slot.get("width"), slot.get("height")
            if (
                not isinstance(width, int)
                or not isinstance(height, int)
                or width <= 0
                or height <= 0
                or (extra is not None and not isinstance(extra, bool))
                or not isinstance(linked, bool)
                or slot.get("link_metadata_valid") is not True
            ):
                raise UnknownPageStateError("ComicFUZ image-role metadata is unsupported")
            if extra is True and linked:
                roles.append("linked_extra")
            elif extra in {None, False} and not linked:
                roles.append("body_candidate")
            else:
                raise UnknownPageStateError("ComicFUZ image has an unverified page role")
        elif role in {"google_ads", "last_page"}:
            roles.append(role)
        else:
            raise UnknownPageStateError("ComicFUZ viewer contains an unsupported page role")

    extra_positions = [index for index, role in enumerate(roles) if role == "linked_extra"]
    if len(extra_positions) != 1:
        raise UnknownPageStateError("ComicFUZ viewer must expose one linked extra-page marker")
    extra_index = extra_positions[0]
    if extra_index < 1 or roles[:extra_index] != ["body_candidate"] * extra_index:
        raise UnknownPageStateError("ComicFUZ body pages are not a contiguous unlinked prefix")
    if roles[extra_index + 1 :] != ["google_ads", "last_page"]:
        raise UnknownPageStateError("ComicFUZ viewer tail differs from the verified layout")
    return tuple(range(extra_index)), extra_index


class ComicFuzAdapter(SiteAdapter):
    """Capture only a freshly verified anonymous public-free ComicFUZ episode."""

    page_change_timeout_ms = 12_000
    render_stable_checks = 3
    render_poll_ms = 100
    max_rewind_turns = 32
    max_blob_entries = 16
    max_source_response_bytes = 4 * 1024 * 1024
    source_response_timeout_ms = 2_000
    source_response_retries = 1

    page_selector = 'img[class*="G54Y0W_page"]'
    viewer_title_selector = 'h2[class*="title_detail_viewer__detail__info__viewerTitle"]'
    end_panel_selector = '[class*="ChapterLastPage_lastpage__nextChapter"]'
    end_panel_root_selector = '[class*="ChapterLastPage_lastpage__"]'
    next_chapter_selector = 'a[class*="ChapterLastPage_nextChapter__button"]'

    def __init__(self, *, preflight_work_url: str | None = None) -> None:
        self._preflight_work_url = preflight_work_url
        self._work_id: str | None = None
        self._chapter_id: str | None = None
        self._target_url: str | None = None
        self._access_strategy: AccessStrategy = "auto"
        self._episode_title: str | None = None
        self._expected_episode_title: str | None = None
        self._output_title: str | None = None
        self._viewer_pages: list[dict[str, Any]] | None = None
        self._body_page_indices: tuple[int, ...] = ()
        self._is_first_page_blank: bool | None = None
        self._initial_body_indices: tuple[int, ...] = ()
        self._extra_page_index: int | None = None
        self._source_responses: OrderedDict[str, object] = OrderedDict()
        self._source_response_tasks: OrderedDict[str, asyncio.Task[bytes | None]] = OrderedDict()
        self._bound_page: Page | None = None
        self._captured_indices: list[int] = []
        self._last_captured_group: tuple[int, ...] = ()
        self._last_captured_proofs: dict[int, tuple[str, int, int]] = {}
        self._last_rendered_group: tuple[int, ...] = ()
        self._advance_pending = False
        self._ended = False
        self._initialized = False

    def get_access_profile(self) -> AccessProfile:
        return comicfuz_access_profile()

    async def prepare_page(self, page: Page) -> None:
        await self._cleanup_source_observer()
        self._bound_page = page
        page.on("response", self._handle_source_response)
        page.on("close", self._on_page_closed)

    async def _cleanup_source_observer(self) -> None:
        page = self._bound_page
        if page is not None:
            with suppress(Exception):
                page.remove_listener("response", self._handle_source_response)
                page.remove_listener("close", self._on_page_closed)
        self._bound_page = None
        tasks = list(self._source_response_tasks.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=0.1)
            del done
            for task in pending:
                task.cancel()
        self._source_responses.clear()
        self._source_response_tasks.clear()

    def _on_page_closed(self) -> None:
        for task in self._source_response_tasks.values():
            if not task.done():
                task.cancel()
        self._source_responses.clear()
        self._source_response_tasks.clear()
        self._bound_page = None

    def _handle_source_response(self, response: object) -> None:
        response_url = str(getattr(response, "url", ""))
        if not response_url.startswith(_BLOB_PREFIX):
            return
        request = getattr(response, "request", None)
        resource_type = getattr(request, "resource_type", None)
        if resource_type not in {None, "", "image"}:
            return
        headers = getattr(response, "headers", {})
        declared_length = None
        if isinstance(headers, dict):
            raw_length = headers.get("content-length")
            try:
                declared_length = int(raw_length) if raw_length is not None else None
            except (TypeError, ValueError):
                declared_length = None
        if declared_length is not None and (
            declared_length < 0 or declared_length > self.max_source_response_bytes
        ):
            return
        previous = self._source_response_tasks.get(response_url)
        if previous is not None:
            if not previous.done():
                return
            try:
                if previous.result() is not None:
                    return
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 - replace a failed read
                self._source_response_tasks.pop(response_url, None)
        self._source_responses[response_url] = response
        self._source_responses.move_to_end(response_url)
        task = asyncio.create_task(self._read_source_response(response))
        self._source_response_tasks[response_url] = task
        task.add_done_callback(
            lambda completed, url=response_url: self._discard_failed_source_read(url, completed)
        )
        self._source_response_tasks.move_to_end(response_url)
        while len(self._source_responses) > self.max_blob_entries:
            old_url, _ = self._source_responses.popitem(last=False)
            old_task = self._source_response_tasks.pop(old_url, None)
            if old_task is not None and not old_task.done():
                old_task.cancel()

    def _discard_failed_source_read(
        self, source_url: str, task: asyncio.Task[bytes | None]
    ) -> None:
        if self._source_response_tasks.get(source_url) is not task:
            return
        try:
            successful = task.result() is not None
        except (asyncio.CancelledError, Exception):  # noqa: BLE001 - failed reads are discarded
            successful = False
        if not successful:
            self._source_response_tasks.pop(source_url, None)
            self._source_responses.pop(source_url, None)

    async def _read_source_response(self, response: object) -> bytes | None:
        try:
            body = await asyncio.wait_for(
                response.body(),  # type: ignore[attr-defined]
                timeout=self.source_response_timeout_ms / 1000,
            )
        except Exception:  # noqa: BLE001 - unavailable response bodies use native readback
            return None
        if not isinstance(body, bytes) or len(body) > self.max_source_response_bytes:
            return None
        return body

    async def configure_target_identity(self, external_id: str, work_key: str) -> None:
        """Keep Batch's composite Catalog identity as the exact reader target."""

        del work_key  # The Catalog external ID is the site identity authority.
        match = _COMPOSITE_ID.fullmatch(external_id)
        if match is None:
            raise UnknownPageStateError("ComicFUZ Catalog identity is malformed")
        self._work_id = match.group("work")
        self._chapter_id = match.group("chapter")
        self._target_url = f"https://{SITE_HOST}/manga/viewer/{self._chapter_id}"

    def resolve_initial_navigation_url(self, source_url: str) -> str:
        """Route through the same-work public listing before any reader entry."""

        chapter_id = parse_comicfuz_episode_url(source_url)
        if chapter_id is None:
            raise UnknownPageStateError("ComicFUZ crawl requires a canonical viewer URL")
        if self._chapter_id is not None and chapter_id != self._chapter_id:
            raise UnknownPageStateError("ComicFUZ URL differs from the configured Catalog target")
        if self._chapter_id is not None and self._work_id is not None:
            work_url = self._preflight_work_url or f"https://{SITE_HOST}/manga/{self._work_id}"
            work_parts = parse_comicfuz_work_url(work_url)
            if work_parts is None or work_parts.work_id != self._work_id:
                raise UnknownPageStateError(
                    "COMICFUZ_WORK_URL does not match the configured target"
                )
        else:
            work_url = self._preflight_work_url or ""
            work_parts = parse_comicfuz_work_url(work_url)
            if work_parts is None:
                raise UnknownPageStateError(
                    "ComicFUZ manual crawl requires canonical COMICFUZ_WORK_URL"
                )
            if self._work_id is not None and work_parts.work_id != self._work_id:
                raise UnknownPageStateError("COMICFUZ_WORK_URL does not match the target work")
            self._work_id = work_parts.work_id
            self._chapter_id = chapter_id
            self._target_url = source_url
        if self._target_url != source_url:
            raise UnknownPageStateError(
                "ComicFUZ source URL is not the exact configured viewer route"
            )
        return work_url

    async def configure_run(self, page: Page, access_strategy: AccessStrategy) -> None:
        del page
        if access_strategy not in {"auto", "direct"}:
            raise UnsupportedAccessStrategyError(
                "ComicFUZ anonymous free crawl supports access_strategy='auto' or 'direct' only"
            )
        self._access_strategy = access_strategy

    @_cleanup_observer_on_failure
    async def initialize(self, page: Page) -> None:
        if self._work_id is None or self._chapter_id is None or self._target_url is None:
            raise UnknownPageStateError("ComicFUZ target was not resolved before navigation")
        self._captured_indices = []
        self._last_captured_group = ()
        self._last_captured_proofs = {}
        self._last_rendered_group = ()
        self._viewer_pages = None
        self._body_page_indices = ()
        self._is_first_page_blank = None
        self._initial_body_indices = ()
        self._extra_page_index = None
        self._advance_pending = False
        self._ended = False
        self._initialized = False

        work_url = self._preflight_work_url or f"https://{SITE_HOST}/manga/{self._work_id}"
        target = WatchlistTarget(
            key=f"comicfuz-preflight-{self._work_id}",
            work_key=f"comicfuz:{self._work_id}",
            site="comicfuz",
            url=work_url,
            label=f"ComicFUZ {self._work_id}",
        )
        records = [
            record async for record in ComicFuzDiscoveryAdapter().iter_records(page, target, "full")
        ]
        matches = [
            record
            for record in records
            if record.source.external_id == f"{self._work_id}:{self._chapter_id}"
        ]
        if len(matches) != 1 or matches[0].source.access_mode != "free":
            raise UnknownPageStateError(
                "ComicFUZ target episode lacks exact current anonymous free-listing evidence"
            )
        if matches[0].source.url != self._target_url:
            raise UnknownPageStateError(
                "ComicFUZ free-list target route did not match the reader URL"
            )
        expected_episode_title = matches[0].item.order_label
        if not isinstance(expected_episode_title, str) or not expected_episode_title.strip():
            raise UnknownPageStateError("ComicFUZ preflight episode label is unavailable")
        self._expected_episode_title = expected_episode_title

        await page.goto(self._target_url, wait_until="domcontentloaded", timeout=15_000)
        manifest_deadline = (
            asyncio.get_running_loop().time() + self.page_change_timeout_ms / 1000
        )
        while asyncio.get_running_loop().time() < manifest_deadline:
            if await self._validate_reader_identity(page, allow_initial_manifest_loading=True):
                break
            await page.wait_for_timeout(self.render_poll_ms)
        else:
            raise PageChangeTimeoutError(
                "ComicFUZ first-party viewer page-role manifest did not become available"
            )
        first = await self._wait_for_stable_body(page)
        if tuple(row["number"] for row in first) != self._initial_body_indices:
            first = await self._rewind_to_first_body(page, first)
        if tuple(row["number"] for row in first) != self._initial_body_indices:
            raise UnknownPageStateError("ComicFUZ reader did not restore to its first body page")
        self._episode_title = await self._read_episode_title(page)
        if not self._episode_title:
            raise UnknownPageStateError("ComicFUZ episode title is unavailable")
        if self._episode_title != expected_episode_title:
            raise UnknownPageStateError(
                "ComicFUZ reader title does not match its freshly verified listing row"
            )
        self._initialized = True

    def get_output_metadata(self) -> dict[str, str | None]:
        return {
            "title": self._output_title,
            "author": None,
            "order": self._episode_title,
            "genre": "漫画",
        }

    @_cleanup_observer_on_failure
    async def detect_state(self, page: Page) -> PageState:
        if not await self._reader_route_is_target(page):
            raise UnknownPageStateError(
                "ComicFUZ left the configured free episode before verified END"
            )
        terminal_candidate = await self._positive_end_panel(page)
        await self._validate_reader_identity(
            page,
            allow_cached_manifest_at_end=bool(terminal_candidate and self._viewer_pages),
        )
        rows = await self._active_page_rows(page)
        if rows:
            if any(not row["ready"] for row in rows):
                return PageState.LOADING
            self._validate_page_group(rows)
            actual_rendered = tuple(int(row["number"]) for row in rows)
            body_rows = self._body_rows(rows)
            actual_body = tuple(int(row["number"]) for row in body_rows)
            if (
                self._captured_indices
                and actual_rendered == self._last_rendered_group
                and actual_body == self._last_captured_group
            ):
                return PageState.CONTENT
            expected_group = self._expected_body_group()
            expected_rendered_count = (
                len(self._initial_body_indices) if not self._captured_indices else 2
            )
            if len(rows) != expected_rendered_count:
                return PageState.LOADING
            if actual_body != expected_group:
                raise UnknownPageStateError(
                    "ComicFUZ body pages have a gap, repeat, or unexpected spread"
                )
            return PageState.CONTENT

        terminal = terminal_candidate
        if terminal and self._captured_indices and self._episode_title == terminal["title"]:
            if self._captured_indices != list(self._body_page_indices):
                raise UnknownPageStateError(
                    "ComicFUZ reached its end panel with incomplete body sequence"
                )
            if await self._terminal_body_shells_clear(page):
                self._ended = True
                await self._cleanup_source_observer()
                return PageState.END
            return PageState.LOADING

        if await page.locator(self.page_selector).count() or self._advance_pending:
            return PageState.LOADING
        return PageState.UNKNOWN

    async def get_capture_target(self, page: Page) -> Locator:
        targets = await self.get_capture_targets(page)
        if not targets:
            raise UnknownPageStateError("ComicFUZ body image is not ready")
        return targets[0]

    async def get_capture_targets(self, page: Page) -> tuple[Locator, ...]:
        rows = await self._active_page_rows(page)
        self._validate_page_group(rows)
        if any(not row["ready"] for row in rows):
            raise UnknownPageStateError("ComicFUZ full visible spread is not ready for fallback capture")
        self._require_supported_group_size(rows)
        self._require_complete_initial_group(rows)
        locator = page.locator(self.page_selector)
        return tuple(locator.nth(int(row["index"])) for row in self._body_rows(rows))

    async def get_content_identity(self, page: Page) -> ContentIdentity:
        rows = await self._active_page_rows(page)
        self._validate_page_group(rows)
        if any(not row["ready"] for row in rows):
            raise UnknownPageStateError("ComicFUZ full visible spread is not ready for identity")
        body_rows = self._body_rows(rows)
        self._require_supported_group_size(rows)
        numbers = tuple(int(row["number"]) for row in body_rows)
        self._require_complete_initial_group(rows)
        self._require_expected_sequence(numbers)
        labels = tuple(str(row["alt"]) for row in body_rows)
        return ContentIdentity(
            page_id="|".join(labels),
            page_number=max(numbers) + 1,
            source_id=self._chapter_id,
        )

    async def get_content_context(self, page: Page) -> ContentContext:
        chapter_id = parse_comicfuz_episode_url(page.url)
        if chapter_id is None:
            chapter_id = self._chapter_id
        title = self._episode_title
        return ContentContext(
            content_id=chapter_id,
            work_id=self._work_id,
            episode_id=chapter_id,
            chapter_id=chapter_id,
            title=title,
        )

    async def go_next(self, page: Page) -> None:
        state = await self.detect_state(page)
        if state is not PageState.CONTENT:
            raise UnknownPageStateError("ComicFUZ next-page action requires a ready body spread")
        self._advance_pending = True
        await page.keyboard.press("ArrowLeft")

    @_cleanup_observer_on_failure
    async def wait_for_change(
        self,
        page: Page,
        previous_identity: ContentIdentity | None,
    ) -> None:
        deadline = asyncio.get_running_loop().time() + self.page_change_timeout_ms / 1000
        previous_signature: tuple[object, ...] | None = None
        stable_checks = 0
        while asyncio.get_running_loop().time() < deadline:
            if not await self._reader_route_is_target(page):
                raise UnknownPageStateError(
                    "ComicFUZ left the configured free episode before verified END"
                )
            terminal_candidate = await self._positive_end_panel(page)
            await self._validate_reader_identity(
                page,
                allow_cached_manifest_at_end=bool(terminal_candidate and self._viewer_pages),
            )
            rows = [
                row for row in await self._all_page_rows(page) if row["active"]
            ]
            if rows:
                if len(rows) > 2 and self._is_pending_transition_overlap(rows):
                    # During a page turn ComicFUZ can briefly keep the old
                    # spread mounted while mounting the next one. This state
                    # is useful only as a reason to wait: it must never be
                    # treated as content or passed to capture/identity code.
                    stable_checks = 0
                    previous_signature = None
                    await page.wait_for_timeout(self.render_poll_ms)
                    continue
                self._validate_page_group(rows)
                if all(row["ready"] for row in rows):
                    signature = self._body_signature(rows)
                    body_rows = self._body_rows(rows)
                    current = self._identity_for_rows(body_rows)
                    actual_body = tuple(int(row["number"]) for row in body_rows)
                    expected_body = tuple(
                        range(len(self._captured_indices), len(self._captured_indices) + len(body_rows))
                    )
                    actual_rendered = tuple(int(row["number"]) for row in rows)
                    expected_group = self._expected_body_group()
                    required_count = (
                        len(self._initial_body_indices) if not self._captured_indices else 2
                    )
                    expected_full_body_count = len(expected_group)
                    expected_body = expected_group[: len(actual_body)]
                    is_partial_expected = (
                        len(rows) < required_count
                        and actual_body == expected_body
                    ) or (len(body_rows) < expected_full_body_count and actual_body == expected_body)
                    if (
                        len(rows) == required_count
                        and actual_body == expected_group
                        and current != previous_identity
                    ):
                        stable_checks = stable_checks + 1 if signature == previous_signature else 0
                        if stable_checks >= self.render_stable_checks:
                            self._advance_pending = False
                            return
                    elif (
                        actual_rendered == self._last_rendered_group
                        and actual_body == self._last_captured_group
                        and current == previous_identity
                    ):
                        # ComicFUZ can update its footer before replacing the
                        # prior ready image. Keep waiting; never recapture it
                        # as the next page.
                        stable_checks = 0
                    elif is_partial_expected:
                        stable_checks = 0
                    else:
                        stable_checks = stable_checks + 1 if signature == previous_signature else 0
                        if stable_checks >= self.render_stable_checks:
                            raise UnknownPageStateError(
                                "ComicFUZ page turn settled on a skipped or repeated body spread"
                            )
                    previous_signature = signature
                else:
                    stable_checks = 0
                    previous_signature = None
            else:
                terminal = terminal_candidate
                if terminal and terminal["title"] == self._episode_title:
                    if not await self._terminal_body_shells_clear(page):
                        stable_checks = 0
                        previous_signature = None
                    else:
                        signature = ("end", terminal["title"], terminal["bounds"])
                        stable_checks = stable_checks + 1 if signature == previous_signature else 0
                        if stable_checks >= self.render_stable_checks:
                            if not self._captured_indices:
                                raise UnknownPageStateError(
                                    "ComicFUZ end panel appeared before any body capture"
                                )
                            if self._captured_indices != list(self._body_page_indices):
                                raise UnknownPageStateError(
                                    "ComicFUZ end panel appeared before the verified body prefix was complete"
                                )
                            self._ended = True
                            self._advance_pending = False
                            await self._cleanup_source_observer()
                            return
                        previous_signature = signature
                else:
                    stable_checks = 0
                    previous_signature = None
            await page.wait_for_timeout(self.render_poll_ms)
        raise PageChangeTimeoutError(
            "ComicFUZ page turn did not reach a stable next page or end panel"
        )

    @_cleanup_observer_on_failure
    async def capture_page(self, page: Page) -> tuple[CaptureResult, ...] | None:
        rows = await self._active_page_rows(page)
        self._validate_page_group(rows)
        if any(not row["ready"] for row in rows):
            raise UnknownPageStateError("ComicFUZ full visible spread is not ready for capture")
        self._require_supported_group_size(rows)
        self._require_complete_initial_group(rows)
        body_rows = self._body_rows(rows)
        if not body_rows or any(row.get("role") != "body" for row in body_rows):
            raise UnknownPageStateError("ComicFUZ spread has no verified body page to capture")
        numbers = tuple(int(row["number"]) for row in body_rows)
        self._require_expected_sequence(numbers)
        initial_signature = self._body_signature(rows)
        locator = page.locator(self.page_selector)
        captures: list[CaptureResult] = []
        for row in body_rows:
            source_url = str(row["src"])
            width = int(row["naturalWidth"])
            height = int(row["naturalHeight"])
            source_bytes = await self._source_bytes_for(source_url)
            result = (
                capture_comicfuz_source_bytes(
                    source_bytes,
                    expected_width=width,
                    expected_height=height,
                )
                if source_bytes is not None
                else None
            )
            if result is None:
                result = await self._native_canvas_capture(locator.nth(int(row["index"])), row)
            captures.append(result)

        current_rows = await self._active_page_rows(page)
        if self._body_signature(current_rows) != initial_signature:
            raise UnknownPageStateError("ComicFUZ page changed during capture")
        if not await self._reader_route_is_target(page):
            raise UnknownPageStateError("ComicFUZ reader identity changed during capture")
        await self._validate_reader_identity(page)
        if numbers != tuple(
            range(len(self._captured_indices), len(self._captured_indices) + len(numbers))
        ):
            raise UnknownPageStateError("ComicFUZ capture would skip or repeat body pages")
        self._captured_indices.extend(numbers)
        self._last_captured_group = numbers
        self._last_rendered_group = tuple(int(row["number"]) for row in rows)
        self._last_captured_proofs = {
            int(row["number"]): (
                str(row["src"]),
                int(row["naturalWidth"]),
                int(row["naturalHeight"]),
            )
            for row in rows
        }
        return tuple(captures)

    async def _source_bytes_for(self, source_url: str) -> bytes | None:
        if not source_url.startswith(_BLOB_PREFIX):
            return None
        response = self._source_responses.get(source_url)
        if response is None:
            return None
        for attempt in range(self.source_response_retries + 1):
            task = self._source_response_tasks.get(source_url)
            if task is None:
                task = asyncio.create_task(self._read_source_response(response))
                self._source_response_tasks[source_url] = task
                task.add_done_callback(
                    lambda completed, url=source_url: self._discard_failed_source_read(
                        url, completed
                    )
                )
            try:
                done, _ = await asyncio.wait(
                    {task}, timeout=self.source_response_timeout_ms / 1000
                )
                if done:
                    try:
                        data = task.result()
                    except (asyncio.CancelledError, Exception):  # noqa: BLE001
                        data = None
                else:
                    data = None
                    task.cancel()
                    await asyncio.wait({task}, timeout=0.1)
                    if self._source_response_tasks.get(source_url) is task:
                        self._source_response_tasks.pop(source_url, None)
            except asyncio.CancelledError:
                task.cancel()
                await asyncio.wait({task}, timeout=0.1)
                if self._source_response_tasks.get(source_url) is task:
                    self._source_response_tasks.pop(source_url, None)
                self._source_responses.pop(source_url, None)
                raise
            if data is not None:
                return data
            if attempt < self.source_response_retries:
                if self._source_response_tasks.get(source_url) is task:
                    self._source_response_tasks.pop(source_url, None)
                continue
            if self._source_response_tasks.get(source_url) is task:
                self._source_response_tasks.pop(source_url, None)
            self._source_responses.pop(source_url, None)
        return None

    async def _native_canvas_capture(self, locator: Locator, row: dict[str, Any]) -> CaptureResult:
        expected = {
            "alt": row["alt"],
            "src": row["src"],
            "width": row["naturalWidth"],
            "height": row["naturalHeight"],
        }
        try:
            data_url = await locator.evaluate(
                """(element, expected) => {
                  const rect = element.getBoundingClientRect();
                  const current = {
                    alt: element.alt || '', src: element.currentSrc || element.src || '',
                    width: element.naturalWidth, height: element.naturalHeight
                  };
                  if (!element.complete || !element.naturalWidth || !element.naturalHeight
                      || JSON.stringify(current) !== JSON.stringify(expected)
                      || !(rect.right > 0 && rect.left < innerWidth && rect.bottom > 0 && rect.top < innerHeight))
                    throw new Error('selected image changed or is not active');
                  const canvas = document.createElement('canvas');
                  canvas.width = element.naturalWidth; canvas.height = element.naturalHeight;
                  const context = canvas.getContext('2d', {alpha: false});
                  if (!context) throw new Error('native canvas unavailable');
                  context.drawImage(element, 0, 0, canvas.width, canvas.height);
                  const output = canvas.toDataURL('image/png');
                  const after = {
                    alt: element.alt || '', src: element.currentSrc || element.src || '',
                    width: element.naturalWidth, height: element.naturalHeight
                  };
                  if (JSON.stringify(after) !== JSON.stringify(expected))
                    throw new Error('selected image changed during native readback');
                  return output;
                }""",
                expected,
            )
        except Exception as exc:
            raise UnknownPageStateError(
                "ComicFUZ viewer-delivered image bytes and native pixel readback are unavailable"
            ) from exc
        if not isinstance(data_url, str) or not data_url.startswith("data:image/png;base64,"):
            raise UnknownPageStateError("ComicFUZ native pixel readback was not a PNG")
        try:
            result = capture_png_bytes(base64.b64decode(data_url.split(",", 1)[1], validate=True))
        except (ValueError, binascii.Error) as exc:
            raise UnknownPageStateError("ComicFUZ native pixel readback is malformed") from exc
        if (result.width, result.height) != (row["naturalWidth"], row["naturalHeight"]):
            raise UnknownPageStateError(
                "ComicFUZ native pixel dimensions do not match the selected image"
            )
        return result

    async def _validate_reader_identity(
        self,
        page: Page,
        *,
        allow_initial_manifest_loading: bool = False,
        allow_cached_manifest_at_end: bool = False,
    ) -> bool:
        if not await self._reader_route_is_target(page):
            raise UnknownPageStateError("ComicFUZ reader route differs from the verified target")
        await self._validate_anonymous_state(page)
        snapshot = await self._read_viewer_snapshot(page)
        if (
            snapshot.get("chapter_id") != self._chapter_id
            or snapshot.get("work_id") != self._work_id
            or snapshot.get("episode_title") != self._expected_episode_title
        ):
            raise UnknownPageStateError(
                "ComicFUZ first-party work or episode metadata differs from the free listing row"
            )
        work_title = snapshot.get("work_title")
        if not isinstance(work_title, str) or not work_title.strip():
            raise UnknownPageStateError("ComicFUZ first-party work title is unavailable")
        if self._output_title is None:
            self._output_title = work_title
        elif self._output_title != work_title:
            raise UnknownPageStateError("ComicFUZ first-party work title changed during the crawl")

        manifest_available = True
        pages = snapshot.get("pages")
        if pages is not None:
            is_first_page_blank = snapshot.get("is_first_page_blank")
            if not isinstance(is_first_page_blank, bool):
                raise UnknownPageStateError(
                    "ComicFUZ first-page layout flag is missing or malformed"
                )
            body_indices, extra_index = _classify_viewer_pages(pages)
            if self._chapter_id != snapshot.get("viewer_chapter_id"):
                raise UnknownPageStateError("ComicFUZ viewer page list belongs to another episode")
            initial_body_indices = (0,) if is_first_page_blank else (0, 1)
            if not set(initial_body_indices).issubset(body_indices):
                raise UnknownPageStateError(
                    "ComicFUZ first-page layout flag conflicts with its body-page manifest"
                )
            if self._viewer_pages is None:
                self._viewer_pages = pages
                self._body_page_indices = body_indices
                self._extra_page_index = extra_index
                self._is_first_page_blank = is_first_page_blank
                self._initial_body_indices = initial_body_indices
            elif (
                pages != self._viewer_pages
                or body_indices != self._body_page_indices
                or extra_index != self._extra_page_index
                or is_first_page_blank != self._is_first_page_blank
            ):
                raise UnknownPageStateError("ComicFUZ viewer page-role manifest changed")
        elif self._viewer_pages is None:
            if allow_initial_manifest_loading:
                return False
            raise UnknownPageStateError("ComicFUZ first-party viewer page-role manifest is unavailable")
        elif allow_cached_manifest_at_end:
            manifest_available = False
        else:
            raise UnknownPageStateError("ComicFUZ established viewer page-role manifest disappeared")

        if self._episode_title is not None:
            current_title = await self._read_episode_title(page)
            if current_title != self._episode_title:
                raise UnknownPageStateError("ComicFUZ episode title changed during the crawl")
        return manifest_available

    async def _read_viewer_snapshot(self, page: Page) -> dict[str, Any]:
        try:
            snapshot = await asyncio.wait_for(
                page.evaluate(
                    r"""() => {
                      let next = null;
                      try {
                        next = JSON.parse(document.querySelector('#__NEXT_DATA__')?.textContent || 'null');
                      } catch { return null; }
                      const props = next?.props?.pageProps || {};
                      const data = props.data || {};
                      let web = null;
                      for (const element of document.querySelectorAll('img[class*="G54Y0W_page"]')) {
                        let fiberKey = Object.keys(element).find(key => key.startsWith('__reactFiber$'));
                        let fiber = fiberKey ? element[fiberKey] : null;
                        for (let depth = 0; fiber && depth < 35; depth++, fiber = fiber.return) {
                          const candidate = fiber.memoizedProps?.webMangaViewerData;
                          if (candidate && typeof candidate === 'object') { web = candidate; break; }
                        }
                        if (web) break;
                      }
                      let pages = null;
                      let viewerChapterId = null;
                      let isFirstPageBlank = null;
                      if (web) {
                        viewerChapterId = String(web.chapterId ?? '');
                        const sourcePages = web.viewerData?.pages;
                        if (!Array.isArray(sourcePages)) return null;
                        const firstPageBlank = web.viewerData?.isFirstPageBlank;
                        if (typeof firstPageBlank === 'boolean') isFirstPageBlank = firstPageBlank;
                        pages = sourcePages.map(slot => {
                          if (!slot || typeof slot !== 'object') return {role:'unsupported'};
                          const slotKeys = Object.keys(slot);
                          if (slotKeys.length !== 1) return {role:'unsupported'};
                          if (slotKeys[0] === 'image') {
                            const image = slot.image;
                            if (!image || typeof image !== 'object') return {role:'unsupported'};
                            const ownsExtra = Object.prototype.hasOwnProperty.call(image, 'isExtraPage');
                            const ownsLink = Object.prototype.hasOwnProperty.call(image, 'urlScheme');
                            const link = image.urlScheme;
                            return {
                              role:'image',
                              is_extra: ownsExtra ? image.isExtraPage : null,
                              has_link: ownsLink && typeof link === 'string' && link.trim().length > 0,
                              link_metadata_valid: !ownsLink || (typeof link === 'string' && link.trim().length > 0),
                              width: Number(image.imageWidth), height: Number(image.imageHeight)
                            };
                          }
                          if (slotKeys[0] === 'googleAds') return {role:'google_ads'};
                          if (slotKeys[0] === 'lastPage') return {role:'last_page'};
                          return {role:'unsupported'};
                        });
                      }
                      return {
                        chapter_id: String(props.chapterId ?? ''),
                        work_id: String(data.mangaId ?? ''),
                        episode_title: typeof data.chapterMainName === 'string' ? data.chapterMainName.trim() : '',
                        work_title: typeof data.mangaName === 'string' ? data.mangaName.trim() : '',
                        viewer_chapter_id: viewerChapterId,
                        is_first_page_blank: isFirstPageBlank,
                        pages
                      };
                    }"""
                ),
                timeout=3,
            )
        except (PlaywrightTimeoutError, TimeoutError) as exc:
            raise UnknownPageStateError("ComicFUZ first-party viewer metadata could not be read") from exc
        if not isinstance(snapshot, dict):
            raise UnknownPageStateError("ComicFUZ first-party viewer metadata is malformed")
        return snapshot

    async def _reader_route_is_target(self, page: Page) -> bool:
        try:
            parsed = urlparse(page.url)
        except ValueError:
            return False
        return (
            parsed.scheme.lower() == "https"
            and parsed.hostname == SITE_HOST
            and parsed.port is None
            and parsed.username is None
            and parsed.password is None
            and parsed.path == f"/manga/viewer/{self._chapter_id}"
            and not parsed.query
            and not parsed.fragment
        )

    async def _validate_anonymous_state(self, page: Page) -> None:
        identity = await page.evaluate(
            r"""() => {
              const visible = element => {
                if (!element || element.getClientRects().length === 0) return false;
                for (let node = element; node; node = node.parentElement) {
                  const style = getComputedStyle(node);
                  if (node.hidden || style.display === 'none' || style.visibility === 'hidden'
                      || style.visibility === 'collapse' || Number(style.opacity) === 0) return false;
                }
                return true;
              };
              const links = [...document.querySelectorAll('a[href]')];
              const signIn = links.filter(a => {
                const u = new URL(a.href, location.href);
                return u.origin === location.origin && u.pathname === '/account/signin' && visible(a);
              }).length;
              const signOut = links.filter(a => /\/(?:account\/(?:signout|logout)|logout|signout)(?:\/|$)/i
                .test(new URL(a.href, location.href).pathname) && visible(a)).length;
              return {signIn, signOut};
            }"""
        )
        if (
            not isinstance(identity, dict)
            or identity.get("signIn") != 1
            or identity.get("signOut") != 0
        ):
            raise UnknownPageStateError(
                "ComicFUZ anonymous reader state is not positively confirmed"
            )

    async def _read_episode_title(self, page: Page) -> str | None:
        locator = page.locator(self.viewer_title_selector)
        if await locator.count() != 1 or not await locator.is_visible():
            return None
        value = " ".join((await locator.inner_text()).split())
        return value or None

    async def _all_page_rows(self, page: Page) -> list[dict[str, Any]]:
        locator = page.locator(self.page_selector)
        try:
            rows = await asyncio.wait_for(
                locator.evaluate_all(
                    """elements => elements.map((element, index) => {
                      const rect = element.getBoundingClientRect();
                      let visible = !!element.getClientRects().length;
                      for (let node = element; node && visible; node = node.parentElement) {
                        const style = getComputedStyle(node);
                        visible = !node.hidden && style.display !== 'none'
                          && style.visibility !== 'hidden' && style.visibility !== 'collapse'
                          && Number(style.opacity) !== 0;
                      }
                      const shown = visible && rect.width > 0 && rect.height > 0;
                      const intersects = shown
                        && rect.right > 0 && rect.left < innerWidth
                        && rect.bottom > 0 && rect.top < innerHeight;
                      const fullyVisible = intersects && rect.left >= 0 && rect.top >= 0
                        && rect.right <= innerWidth && rect.bottom <= innerHeight;
                      const proof = [];
                      let visualSafe = true;
                      const near = (a, b) => Math.abs(a - b) < 0.01;
                      const imageStyle = getComputedStyle(element);
                      const fit = imageStyle.objectFit || 'fill';
                      if (fit === 'cover' || !['fill', 'contain', 'scale-down'].includes(fit))
                        visualSafe = false;
                      if (fit === 'fill' && element.naturalWidth > 0 && element.naturalHeight > 0
                          && rect.height > 0
                          && !near(rect.width / rect.height, element.naturalWidth / element.naturalHeight))
                        visualSafe = false;
                      for (let node = element; node && visualSafe; node = node.parentElement) {
                        const style = getComputedStyle(node);
                        const transform = style.transform;
                        let transformProof = 'none';
                        if (transform !== 'none') {
                          try {
                            const matrix = new DOMMatrixReadOnly(transform);
                            if (!matrix.is2D || matrix.a <= 0 || matrix.d <= 0
                                || !near(matrix.b, 0) || !near(matrix.c, 0)) {
                              visualSafe = false;
                            } else {
                              transformProof = [matrix.a, matrix.d, matrix.e, matrix.f].join(',');
                            }
                          } catch (_) { visualSafe = false; }
                        }
                        const backdrop = style.backdropFilter || style.webkitBackdropFilter || 'none';
                        const mask = style.maskImage || style.webkitMaskImage || 'none';
                        const clipPath = style.clipPath || style.webkitClipPath || 'none';
                        const radii = ['borderTopLeftRadius','borderTopRightRadius',
                          'borderBottomLeftRadius','borderBottomRightRadius']
                          .map(key => style[key] || '0px');
                        const rounded = radii.some(value => value.split(/\\s+/)
                          .some(part => Number.parseFloat(part) > 0));
                        const rotate = style.rotate || 'none';
                        const scale = style.scale || 'none';
                        const translate = style.translate || 'none';
                        const perspective = style.perspective || 'none';
                        if (style.filter !== 'none' || backdrop !== 'none'
                            || mask !== 'none' || clipPath !== 'none'
                            || rotate !== 'none' || scale !== 'none' || translate !== 'none'
                            || perspective !== 'none' || style.clip !== 'auto'
                            || style.mixBlendMode !== 'normal' || !near(Number(style.opacity), 1))
                          visualSafe = false;
                        if (rounded && (node === element
                            || (style.overflowX !== 'visible' || style.overflowY !== 'visible')))
                          visualSafe = false;
                        if (node !== element
                            && (style.overflowX !== 'visible' || style.overflowY !== 'visible')) {
                          const clip = node.getBoundingClientRect();
                          const left = clip.left + node.clientLeft;
                          const top = clip.top + node.clientTop;
                          const right = left + node.clientWidth;
                          const bottom = top + node.clientHeight;
                          if (rect.left < left - 0.5 || rect.top < top - 0.5
                              || rect.right > right + 0.5 || rect.bottom > bottom + 0.5)
                            visualSafe = false;
                        }
                        proof.push([style.filter, backdrop, mask,
                          clipPath, rotate, scale, translate, perspective, style.clip,
                          style.mixBlendMode, style.opacity, transformProof,
                          style.overflowX, style.overflowY].join(':'));
                      }
                      const match = /^page_(\\d+)$/.exec(element.alt || '');
                      return {
                        index, alt: element.alt || '', number: match ? Number(match[1]) : null,
                        src: element.currentSrc || element.src || '',
                        x: rect.x, y: rect.y, width: rect.width, height: rect.height,
                        naturalWidth: element.naturalWidth, naturalHeight: element.naturalHeight,
                        visualSafe, visualProof: [fit, ...proof].join('|'),
                        shown, active: intersects,
                        imageReady: element.complete && element.naturalWidth > 0
                          && element.naturalHeight > 0 && !!(element.currentSrc || element.src),
                        ready: fullyVisible && element.complete && element.naturalWidth > 0
                          && element.naturalHeight > 0 && !!(element.currentSrc || element.src)
                      };
                    })"""
                ),
                timeout=3,
            )
        except (PlaywrightTimeoutError, TimeoutError) as exc:
            raise UnknownPageStateError("ComicFUZ page image state could not be read") from exc
        if not isinstance(rows, list):
            return []
        if rows and self._viewer_pages is None:
            raise UnknownPageStateError("ComicFUZ page images have no verified native page manifest")
        for row in rows:
            number = row.get("number")
            if not isinstance(number, int) or self._viewer_pages is None:
                raise UnknownPageStateError("ComicFUZ rendered image has no exact page index")
            if number < 0 or number >= len(self._viewer_pages):
                raise UnknownPageStateError("ComicFUZ rendered image index is outside the page manifest")
            slot = self._viewer_pages[number]
            if number in self._body_page_indices:
                row["role"] = "body"
            elif number == self._extra_page_index:
                row["role"] = "linked_extra"
            else:
                raise UnknownPageStateError("ComicFUZ non-image tail slot appeared as a page image")
            row["descriptorWidth"] = slot.get("width")
            row["descriptorHeight"] = slot.get("height")
            if row.get("imageReady") and (
                int(row.get("naturalWidth") or 0) != slot.get("width")
                or int(row.get("naturalHeight") or 0) != slot.get("height")
            ):
                raise UnknownPageStateError(
                    "ComicFUZ rendered page dimensions differ from the native page descriptor"
                )
        rows.sort(key=lambda row: float(row["x"]), reverse=True)
        return rows

    async def _active_page_rows(self, page: Page) -> list[dict[str, Any]]:
        rows = [row for row in await self._all_page_rows(page) if row["active"]]
        if rows:
            self._validate_page_group(rows)
        return rows

    @staticmethod
    def _body_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [row for row in rows if row.get("role") == "body"]

    def _is_pending_transition_overlap(self, rows: list[dict[str, Any]]) -> bool:
        if not self._advance_pending or len(rows) not in {3, 4}:
            return False
        if all(row.get("ready") for row in rows):
            return False
        if not self._last_rendered_group or not self._last_captured_group:
            return False

        previous = self._last_rendered_group
        previous_body = tuple(
            number for number in previous if number in self._body_page_indices
        )
        if previous_body != self._last_captured_group:
            return False
        if tuple(self._captured_indices[-len(previous_body) :]) != previous_body:
            return False

        expected_body = self._expected_body_group()
        if not expected_body:
            return False
        expected_next = list(expected_body)
        if (
            self._extra_page_index is not None
            and expected_body[-1] == self._body_page_indices[-1]
        ):
            expected_next.append(self._extra_page_index)
        if len(expected_next) > 2:
            return False

        previous_set = set(previous)
        expected_set = set(expected_next)
        if len(previous_set) != len(previous) or len(expected_set) != len(expected_next):
            return False
        if not previous_set.isdisjoint(expected_set):
            return False
        if tuple(previous) != tuple(sorted(previous)) or tuple(expected_next) != tuple(
            sorted(expected_next)
        ):
            return False

        numbers = tuple(row.get("number") for row in rows)
        if (
            any(not isinstance(number, int) for number in numbers)
            or numbers != tuple(sorted(numbers))
            or len(set(numbers)) != len(numbers)
            or numbers != tuple(range(numbers[0], numbers[0] + len(numbers)))
        ):
            return False
        combined = previous_set | expected_set
        if not set(numbers).issubset(combined):
            return False
        if not set(numbers).intersection(previous_set) or not set(numbers).intersection(
            expected_set
        ):
            return False

        expected_roles = {
            number: "body" if number in self._body_page_indices else "linked_extra"
            for number in combined
        }
        if any(row.get("role") != expected_roles.get(row["number"]) for row in rows):
            return False
        if any(
            not isinstance(row.get("number"), int)
            or not isinstance(row.get("alt"), str)
            or not row.get("alt")
            or row.get("role") not in {"body", "linked_extra"}
            or float(row.get("width") or 0) <= 0
            or float(row.get("height") or 0) <= 0
            for row in rows
        ):
            return False

        # The native role/index/dimension join is performed by _all_page_rows.
        # Ready overlap rows still need the same per-image source and visual
        # checks as a normal stable spread.
        for row in rows:
            if row.get("ready"):
                self._validate_page_row(row)
        return True

    async def _terminal_body_shells_clear(self, page: Page) -> bool:
        shells = [row for row in await self._all_page_rows(page) if row["shown"]]
        if not shells:
            return True
        if not self._last_rendered_group:
            return False
        shell_numbers = tuple(
            sorted(int(row["number"]) for row in shells if isinstance(row["number"], int))
        )
        if len(shell_numbers) != len(shells) or shell_numbers != tuple(
            sorted(self._last_rendered_group)
        ):
            return False
        for row in shells:
            number = int(row["number"])
            proof = self._last_captured_proofs.get(number)
            if (
                row["active"]
                or not row["imageReady"]
                or proof != (str(row["src"]), int(row["naturalWidth"]), int(row["naturalHeight"]))
            ):
                return False
        return True

    @staticmethod
    def _validate_page_group(rows: list[dict[str, Any]]) -> None:
        if not rows or len(rows) > 2:
            raise UnknownPageStateError("ComicFUZ visible page spread has an unsupported shape")
        for row in rows:
            ComicFuzAdapter._validate_page_row(row)
        numbers = [int(row["number"]) for row in rows]
        if len(numbers) != len(set(numbers)) or numbers != sorted(numbers):
            raise UnknownPageStateError("ComicFUZ spread has duplicate or reversed page identities")
        if len(rows) == 2 and numbers[1] != numbers[0] + 1:
            raise UnknownPageStateError("ComicFUZ spread page identities are not contiguous")
        roles = [row.get("role") for row in rows]
        if roles not in (["body"], ["body", "body"]):
            if roles == ["body", "linked_extra"]:
                if rows[1].get("number") != rows[0].get("number") + 1:
                    raise UnknownPageStateError(
                        "ComicFUZ linked extra is not joined to the final spread"
                    )
            else:
                raise UnknownPageStateError(
                    "ComicFUZ spread contains an unsupported page-role sequence"
                )

    @staticmethod
    def _validate_page_row(row: dict[str, Any]) -> None:
        if (
            not isinstance(row.get("number"), int)
            or not isinstance(row.get("alt"), str)
            or row.get("role") not in {"body", "linked_extra"}
            or float(row.get("width") or 0) <= 0
            or float(row.get("height") or 0) <= 0
        ):
            raise UnknownPageStateError("ComicFUZ rendered page identity or role is malformed")
        if row.get("ready") and (
            not row.get("imageReady")
            or not isinstance(row.get("src"), str)
            or not row.get("src")
            or int(row.get("naturalWidth") or 0) <= 0
            or int(row.get("naturalHeight") or 0) <= 0
        ):
            raise UnknownPageStateError("ComicFUZ ready page image lacks a stable source")
        if row.get("ready") and row.get("visualSafe") is not True:
            raise UnknownPageStateError(
                "ComicFUZ visible image has an unverified filter, transform, or crop"
            )

    def _require_expected_sequence(self, numbers: tuple[int, ...]) -> None:
        if not numbers:
            raise UnknownPageStateError("ComicFUZ has no active body page identity")
        expected = tuple(
            range(len(self._captured_indices), len(self._captured_indices) + len(numbers))
        )
        if numbers != expected:
            raise UnknownPageStateError("ComicFUZ body page sequence has a gap or repeat")

    @staticmethod
    def _require_supported_group_size(rows: list[dict[str, Any]]) -> None:
        expected = 1 if tuple(int(row["number"]) for row in rows) == (0,) else 2
        if len(rows) != expected:
            raise UnknownPageStateError(
                "ComicFUZ page group does not match the observed reader layout"
            )

    def _expected_body_group(self) -> tuple[int, ...]:
        if self._is_first_page_blank is None or not self._initial_body_indices:
            raise UnknownPageStateError("ComicFUZ first-page layout is not verified")
        if not self._captured_indices:
            return self._initial_body_indices
        remaining = self._body_page_indices[len(self._captured_indices) :]
        return remaining[:2]

    def _require_complete_initial_group(self, rows: list[dict[str, Any]]) -> None:
        if not self._captured_indices:
            actual = tuple(int(row["number"]) for row in self._body_rows(rows))
            if actual != self._initial_body_indices:
                raise UnknownPageStateError(
                    "ComicFUZ first spread does not match its verified native blank-page mode"
                )

    def _identity_for_rows(self, rows: list[dict[str, Any]]) -> ContentIdentity:
        numbers = tuple(int(row["number"]) for row in rows)
        labels = tuple(str(row["alt"]) for row in rows)
        return ContentIdentity(
            page_id="|".join(labels),
            page_number=max(numbers) + 1,
            source_id=self._chapter_id,
        )

    @staticmethod
    def _body_signature(rows: list[dict[str, Any]]) -> tuple[object, ...]:
        return tuple(
            (
                row["alt"],
                row.get("role"),
                row["src"],
                round(float(row["x"])),
                round(float(row["y"])),
                round(float(row["width"])),
                round(float(row["height"])),
                row["naturalWidth"],
                row["naturalHeight"],
                row.get("visualProof"),
                row.get("visualSafe"),
                row["ready"],
            )
            for row in rows
        )

    async def _positive_end_panel(self, page: Page) -> dict[str, Any] | None:
        return await page.evaluate(
            """args => {
              const visible = element => {
                if (!element || element.getClientRects().length === 0) return false;
                for (let node = element; node; node = node.parentElement) {
                  const style = getComputedStyle(node);
                  if (node.hidden || style.display === 'none' || style.visibility === 'hidden'
                      || style.visibility === 'collapse' || Number(style.opacity) === 0) return false;
                }
                const r = element.getBoundingClientRect();
                return r.width > 0 && r.height > 0 && r.right > 0 && r.left < innerWidth
                  && r.bottom > 0 && r.top < innerHeight;
              };
              const links = [...document.querySelectorAll(args.nextSelector)]
                .filter(a => (a.innerText || '').trim() === '次の話を読む' && visible(a));
              if (links.length !== 1) return null;
              const link = links[0];
              const panel = link.parentElement;
              const root = panel?.parentElement;
              if (!panel || !panel.matches(args.panelSelector) || !root?.matches(args.rootSelector)
                  || !visible(panel) || !visible(root)) return null;
              const titles = [...document.querySelectorAll(args.titleSelector)].filter(visible);
              if (titles.length !== 1) return null;
              const pr = root.getBoundingClientRect();
              const ar = link.getBoundingClientRect();
              const tr = titles[0].getBoundingClientRect();
              return {
                title: (titles[0].innerText || '').trim(),
                bounds: [Math.round(pr.x), Math.round(pr.y), Math.round(pr.width), Math.round(pr.height),
                  Math.round(ar.x), Math.round(ar.y), Math.round(ar.width), Math.round(ar.height),
                  Math.round(tr.x), Math.round(tr.y), Math.round(tr.width), Math.round(tr.height)]
              };
            }""",
            {
                "nextSelector": self.next_chapter_selector,
                "panelSelector": self.end_panel_selector,
                "rootSelector": self.end_panel_root_selector,
                "titleSelector": self.viewer_title_selector,
            },
        )

    async def _wait_for_stable_body(self, page: Page) -> list[dict[str, Any]]:
        deadline = asyncio.get_running_loop().time() + self.page_change_timeout_ms / 1000
        previous: tuple[object, ...] | None = None
        stable = 0
        while asyncio.get_running_loop().time() < deadline:
            await self._validate_reader_identity(page)
            rows = await self._active_page_rows(page)
            if rows and all(row["ready"] for row in rows):
                self._validate_page_group(rows)
                numbers = tuple(int(row["number"]) for row in rows)
                if self._is_incomplete_initial_group(numbers):
                    previous = None
                    stable = 0
                    await page.wait_for_timeout(self.render_poll_ms)
                    continue
                signature = self._body_signature(rows)
                stable = stable + 1 if signature == previous else 0
                if stable >= self.render_stable_checks:
                    return rows
                previous = signature
            else:
                previous = None
                stable = 0
            await page.wait_for_timeout(self.render_poll_ms)
        raise PageChangeTimeoutError("ComicFUZ first reader page did not become stable")

    def _is_incomplete_initial_group(self, numbers: tuple[int, ...]) -> bool:
        return (
            len(numbers) < len(self._initial_body_indices)
            and bool(numbers)
            and all(number in self._initial_body_indices for number in numbers)
        )

    async def _rewind_to_first_body(
        self, page: Page, rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        previous = rows
        for _ in range(self.max_rewind_turns):
            numbers = tuple(int(row["number"]) for row in previous)
            if numbers == self._initial_body_indices:
                return previous
            if not numbers or numbers[0] <= self._initial_body_indices[0]:
                break
            await page.keyboard.press("ArrowRight")
            deadline = asyncio.get_running_loop().time() + self.page_change_timeout_ms / 1000
            signature = self._body_signature(previous)
            stable = 0
            prior_signature: tuple[object, ...] | None = None
            while asyncio.get_running_loop().time() < deadline:
                await self._validate_reader_identity(page)
                current = await self._active_page_rows(page)
                if current and all(row["ready"] for row in current):
                    current_signature = self._body_signature(current)
                    stable = stable + 1 if current_signature == prior_signature else 0
                    if stable >= self.render_stable_checks and current_signature != signature:
                        current_numbers = tuple(int(row["number"]) for row in current)
                        if not current_numbers or current_numbers[0] >= numbers[0]:
                            raise UnknownPageStateError(
                                "ComicFUZ rewind did not move toward the first page"
                            )
                        if current_numbers[0] < self._initial_body_indices[0]:
                            raise UnknownPageStateError(
                                "ComicFUZ rewind moved before the first body page"
                            )
                        if self._is_incomplete_initial_group(current_numbers):
                            stable = 0
                            prior_signature = current_signature
                            await page.wait_for_timeout(self.render_poll_ms)
                            continue
                        previous = current
                        break
                    prior_signature = current_signature
                await page.wait_for_timeout(self.render_poll_ms)
            else:
                raise PageChangeTimeoutError("ComicFUZ reader position could not be rewound")
        return previous
