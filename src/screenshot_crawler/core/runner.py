"""Site-independent crawler state machine."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from pathlib import Path

from playwright.async_api import Page

from screenshot_crawler.core.capture import capture_locator, save_capture
from screenshot_crawler.core.diagnostics import write_diagnostics
from screenshot_crawler.core.errors import (
    CaptureUnavailableError,
    MaxPagesExceededError,
    PageChangeTimeoutError,
    UnknownPageStateError,
)
from screenshot_crawler.core.fingerprint import fingerprint_bytes
from screenshot_crawler.core.models import (
    CapturedPage,
    ContentContext,
    ContentIdentity,
    RunConfig,
)
from screenshot_crawler.core.progress import ProgressStore, ensure_new_run, normalize_path
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.base import SiteAdapter


@dataclass(frozen=True, slots=True)
class RunResult:
    pages: tuple[CapturedPage, ...]
    stop_state: PageState
    stop_reason: str


def _identity_key(identity: ContentIdentity) -> tuple[object, ...]:
    """Return the complete identity record for progress/debug bookkeeping."""

    return (
        identity.page_id,
        identity.page_number,
        identity.source_id,
        identity.fingerprint,
    )


_STRONG_CONTEXT_FIELDS = ("content_id", "work_id", "episode_id", "chapter_id")


def _has_context(context: ContentContext) -> bool:
    return any(
        getattr(context, field) is not None for field in _STRONG_CONTEXT_FIELDS
    )


def _context_changed(initial: ContentContext, current: ContentContext) -> bool:
    """Compare only identifiers known at both points in the run.

    Viewer metadata is often populated asynchronously. A title changing from
    ``None`` to a value, or another optional field becoming available, must not
    be treated as navigation to another work. A change is meaningful only when
    the same strong identifier is present in both contexts and differs.
    """

    return any(
        (initial_value := getattr(initial, field)) is not None
        and (current_value := getattr(current, field)) is not None
        and initial_value != current_value
        for field in _STRONG_CONTEXT_FIELDS
    )


class CrawlerRunner:
    """Run an adapter while keeping all site decisions outside Core."""

    def __init__(self, config: RunConfig) -> None:
        self.config = config

    async def _adapter_call(
        self,
        awaitable: object,
        operation: str,
        *,
        timeout_ms: int | None = None,
    ):
        budget_ms = (
            self.config.page_change_timeout_ms
            if timeout_ms is None
            else timeout_ms
        )
        try:
            return await asyncio.wait_for(
                awaitable,
                timeout=(budget_ms + self.config.adapter_timeout_grace_ms) / 1000,
            )
        except TimeoutError as exc:
            raise PageChangeTimeoutError(
                f"Adapter operation timed out: {operation}"
            ) from exc

    async def _detect_non_loading_state(self, page: Page, adapter: SiteAdapter) -> PageState:
        state = await self._adapter_call(adapter.detect_state(page), "detect_state")
        for attempt in range(self.config.retry_count):
            if state is not PageState.LOADING:
                return state
            await page.wait_for_timeout(min(250 * (attempt + 1), 1000))
            state = await self._adapter_call(adapter.detect_state(page), "detect_state")
        if state is PageState.LOADING:
            raise PageChangeTimeoutError("Loading state did not resolve within retry limit")
        return state

    async def run(self, page: Page, adapter: SiteAdapter) -> RunResult:
        output_dir = normalize_path(self.config.output_dir)
        ensure_new_run(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        await self._adapter_call(adapter.prepare_page(page), "prepare_page")
        await self._adapter_call(
            adapter.configure_run(page, self.config.access_strategy),
            "configure_run",
        )
        # Validate the resource before navigation can expose an access screen.
        await self._adapter_call(
            adapter.configure_quota_resource(page, self.config.quota_resource),
            "configure_quota_resource",
        )
        await page.goto(
            self.config.source_url,
            timeout=self.config.navigation_timeout_ms,
            wait_until="commit",
        )
        await self._adapter_call(
            adapter.initialize(page),
            "initialize",
            timeout_ms=adapter.get_page_change_timeout_ms(
                self.config.page_change_timeout_ms
            ),
        )
        initial_context = await self._adapter_call(
            adapter.get_content_context(page), "get_content_context"
        )
        store = ProgressStore(
            manifest_path=output_dir / "manifest.json",
            progress_path=output_dir / "progress.json",
            source_url=self.config.source_url,
            site=self.config.site,
            content_context=initial_context,
        )

        saved_pages: list[CapturedPage] = []
        seen_identities: set[tuple[object, ...]] = set()
        seen_fingerprints: set[str] = set()
        same_content_count = 0
        previous_identity: ContentIdentity | None = None

        try:
            while True:
                state = await self._detect_non_loading_state(page, adapter)
                if state in {PageState.END, PageState.NEXT_CONTENT}:
                    return RunResult(tuple(saved_pages), state, state.value)
                if state is PageState.UNKNOWN:
                    raise UnknownPageStateError("Adapter returned UNKNOWN page state")
                if state is PageState.AD:
                    await self._adapter_call(adapter.go_next(page), "go_next")
                    await self._adapter_call(
                        adapter.wait_for_change(page, previous_identity),
                        "wait_for_change",
                        timeout_ms=adapter.get_page_change_timeout_ms(
                            self.config.page_change_timeout_ms
                        ),
                    )
                    continue
                if state is not PageState.CONTENT:
                    raise UnknownPageStateError(f"Unsupported page state: {state}")
                if len(saved_pages) >= self.config.max_pages:
                    raise MaxPagesExceededError(
                        f"max_pages exceeded: {self.config.max_pages}"
                    )

                current_context = await self._adapter_call(
                    adapter.get_content_context(page), "get_content_context"
                )
                if _has_context(initial_context) and _has_context(current_context) and _context_changed(
                    initial_context, current_context
                ):
                    return RunResult(tuple(saved_pages), PageState.NEXT_CONTENT, "context_changed")

                identity = await self._adapter_call(
                    adapter.get_content_identity(page), "get_content_identity"
                )
                identity_key = _identity_key(identity)
                try:
                    captures = await self._adapter_call(
                        adapter.capture_page(page), "capture_page"
                    )
                except (CaptureUnavailableError, PageChangeTimeoutError):
                    captures = None
                if captures is None:
                    targets = await self._adapter_call(
                        adapter.get_capture_targets(page), "get_capture_targets"
                    )
                    try:
                        captures = [
                            await capture_locator(target)
                            for target in targets
                        ]
                    finally:
                        await self._adapter_call(
                            adapter.cleanup_capture_targets(page),
                            "cleanup_capture_targets",
                        )
                if not captures:
                    raise LookupError("Adapter returned no capture results")
                fingerprints = [fingerprint_bytes(capture.data) for capture in captures]
                new_captures = [
                    (index, capture, fingerprints[index])
                    for index, capture in enumerate(captures)
                    if fingerprints[index] not in seen_fingerprints
                ]
                if not new_captures:
                    same_content_count += 1
                    if same_content_count >= self.config.max_same_content:
                        raise PageChangeTimeoutError(
                            "The same content/capture fingerprint repeated after the retry limit"
                        )
                    await self._adapter_call(
                        adapter.wait_for_change(page, identity),
                        "wait_for_change",
                        timeout_ms=adapter.get_page_change_timeout_ms(
                            self.config.page_change_timeout_ms
                        ),
                    )
                    continue

                same_content_count = 0
                part_count = len(captures)
                for part_index, capture, fingerprint in new_captures:
                    if len(saved_pages) >= self.config.max_pages:
                        raise MaxPagesExceededError(
                            f"max_pages exceeded: {self.config.max_pages}"
                        )
                    sequence = len(saved_pages) + 1
                    extension = capture.file_extension.lower()
                    if not extension.startswith(".") or "/" in extension or "\\" in extension:
                        raise ValueError(
                            f"Capture returned an unsafe file extension: {capture.file_extension!r}"
                        )
                    filename = Path(f"page-{sequence:04d}{extension}")
                    save_capture(capture, output_dir / filename)
                    captured = CapturedPage(
                        sequence=sequence,
                        file=filename,
                        identity=identity,
                        width=capture.width,
                        height=capture.height,
                        mime_type=capture.mime_type,
                        file_extension=extension,
                        metadata=(
                            {"part": part_index + 1, "parts": part_count}
                            if part_count > 1
                            else {}
                        ),
                    )
                    saved_pages.append(captured)
                    seen_fingerprints.add(fingerprint)
                    store.add_page(captured, fingerprint=fingerprint)
                seen_identities.add(identity_key)
                previous_identity = identity

                await self._adapter_call(adapter.go_next(page), "go_next")
                await self._adapter_call(
                    adapter.wait_for_change(page, previous_identity),
                    "wait_for_change",
                    timeout_ms=adapter.get_page_change_timeout_ms(
                        self.config.page_change_timeout_ms
                    ),
                )
        except MaxPagesExceededError:
            raise
        except BaseException as exc:
            try:
                await asyncio.wait_for(
                    write_diagnostics(
                        page,
                        self.config.diagnostics_dir,
                        metadata={
                            "detected_state": locals().get("state", PageState.UNKNOWN).value,
                            "content_context": asdict(current_context)
                            if "current_context" in locals()
                            else {},
                            "saved_pages": len(saved_pages),
                        },
                        error=exc,
                    ),
                    timeout=20,
                )
            except BaseException:  # noqa: BLE001, S110
                pass
            raise


async def run_crawler(page: Page, adapter: SiteAdapter, config: RunConfig) -> RunResult:
    """Functional entry point for callers that do not need a Runner object."""

    return await CrawlerRunner(config).run(page, adapter)
