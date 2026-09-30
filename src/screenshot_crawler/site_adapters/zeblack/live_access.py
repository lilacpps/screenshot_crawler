"""Live, read-only Zeblack access-state observation for quota entry.

This module deliberately does not call DiscoveryService or mutate Catalog.  It
reuses the production ChapterV3 decoder and observes the exact protobuf request
emitted by a shared Playwright page while loading the current chapter list.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from screenshot_crawler.site_adapters.zeblack.discovery_protobuf import (
    CONSUMPTION_STATUS_NAMES,
    MAX_PROTOBUF_BODY_BYTES,
    ConsumptionStatus,
    ZeblackChapterV3,
    ZeblackProtobufError,
    decode_zeblack_chapter_records,
    decoded_chapter_content,
)

ZEBLACK_VIEWER_HOST = "zebrack-comic.shueisha.co.jp"
ZEBLACK_API_HOST = "api2.zebrack-comic.com"
ZEBLACK_CHAPTER_LIST_PATH = "/api/v3/title_chapter_list"
ZEBLACK_LIVE_ACCESS_TIMEOUT_MS = 15_000
ZEBLACK_LIVE_ACCESS_POLL_MS = 100


class ZeblackLiveAccessError(RuntimeError):
    """Raised when current Zeblack access state cannot be established safely."""


@dataclass(frozen=True, slots=True)
class ZeblackLiveAccessState:
    """Current status of one chapter plus all ticket-available siblings."""

    title_id: str
    chapter_id: str
    target_main_name: str
    status_value: int
    status_name: str
    ticket_available_ids: tuple[str, ...]
    target_remaining_rental_time: int | None = None

    @property
    def target_ticket_available(self) -> bool:
        return self.status_value == int(ConsumptionStatus.TICKET_AVAILABLE)


@dataclass(frozen=True, slots=True)
class ZeblackChapterListSnapshot:
    """One site-native ChapterV3 observation in wire/list order."""

    title_id: str
    chapters: tuple[ZeblackChapterV3, ...]

    @property
    def by_id(self) -> dict[str, ZeblackChapterV3]:
        return {chapter.chapter_id: chapter for chapter in self.chapters}

    @property
    def ticket_available_ids(self) -> tuple[str, ...]:
        return tuple(
            chapter.chapter_id
            for chapter in self.chapters
            if chapter.status_value == int(ConsumptionStatus.TICKET_AVAILABLE)
        )


def canonical_zeblack_chapter_list_url(title_id: str) -> str:
    if not str(title_id).isdecimal():
        raise ValueError("Zeblack title_id must be numeric")
    return f"https://{ZEBLACK_VIEWER_HOST}/title/{title_id}/chapter/list"


def parse_zeblack_chapter_list_title_id(url: str) -> str | None:
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
    if len(parts) != 5 or parts[1] != "title" or parts[3:] != ["chapter", "list"]:
        return None
    return parts[2] if parts[2].isdecimal() else None


def _response_url_is_target(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme.lower() == "https"
        and parsed.hostname == ZEBLACK_API_HOST
        and port is None
        and parsed.username is None
        and parsed.password is None
        and parsed.path == ZEBLACK_CHAPTER_LIST_PATH
    )


class _LiveProtobufObserver:
    """Capture and validate only exact chapter-list protobuf responses."""

    def __init__(self) -> None:
        self._page: Page | None = None
        self._tasks: list[asyncio.Task[bytes]] = []
        self._processed: set[asyncio.Task[bytes]] = set()
        self._payloads: list[bytes] = []
        self._errors: list[BaseException] = []
        self._listener = self._on_response

    def attach(self, page: Page) -> None:
        self._page = page
        page.on("response", self._listener)

    def close(self) -> None:
        if self._page is not None:
            self._page.remove_listener("response", self._listener)
            self._page = None
        for task in self._tasks:
            if not task.done():
                task.cancel()

    async def wait_for_payloads(self, page: Page, timeout_ms: int) -> tuple[bytes, ...]:
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            tasks = tuple(self._tasks)
            await self._drain(tasks, deadline=deadline)
            if self._payloads:
                # Allow same-load duplicates to arrive and compare them all.
                remaining_ms = self._remaining_timeout_ms(deadline)
                if remaining_ms <= 0:
                    break
                try:
                    await asyncio.wait_for(
                        page.wait_for_timeout(
                            min(ZEBLACK_LIVE_ACCESS_POLL_MS, remaining_ms)
                        ),
                        timeout=remaining_ms / 1000,
                    )
                except TimeoutError as exc:
                    raise ZeblackLiveAccessError(
                        "Zeblack chapter-list protobuf response timed out"
                    ) from exc
                await self._drain(tuple(self._tasks), deadline=deadline)
                if self._errors:
                    raise ZeblackLiveAccessError(
                        "Zeblack chapter-list protobuf response was invalid"
                    ) from self._errors[0]
                return tuple(self._payloads)
            remaining_ms = self._remaining_timeout_ms(deadline)
            if remaining_ms <= 0:
                break
            try:
                await asyncio.wait_for(
                    page.wait_for_timeout(
                        min(ZEBLACK_LIVE_ACCESS_POLL_MS, remaining_ms)
                    ),
                    timeout=remaining_ms / 1000,
                )
            except TimeoutError as exc:
                raise ZeblackLiveAccessError(
                    "Zeblack chapter-list protobuf response timed out"
                ) from exc
        if self._errors:
            raise ZeblackLiveAccessError(
                "Zeblack chapter-list protobuf response was invalid"
            ) from self._errors[0]
        raise ZeblackLiveAccessError(
            "Zeblack title_chapter_list protobuf response was not observed"
        )

    @staticmethod
    def _remaining_timeout_ms(deadline: float) -> int:
        return max(0, int((deadline - time.monotonic()) * 1000))

    async def _drain(
        self, tasks: tuple[asyncio.Task[bytes], ...], *, deadline: float
    ) -> None:
        for task in tasks:
            if task in self._processed:
                continue
            remaining_ms = self._remaining_timeout_ms(deadline)
            if remaining_ms <= 0:
                raise ZeblackLiveAccessError(
                    "Zeblack chapter-list protobuf response body timed out"
                )
            try:
                await asyncio.wait_for(
                    asyncio.shield(task), timeout=remaining_ms / 1000
                )
            except TimeoutError as exc:
                raise ZeblackLiveAccessError(
                    "Zeblack chapter-list protobuf response body timed out"
                ) from exc
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - fail closed
                self._errors.append(exc)
            self._processed.add(task)

    def _on_response(self, response: object) -> None:
        if _response_url_is_target(str(getattr(response, "url", ""))):
            self._tasks.append(asyncio.create_task(self._capture(response)))

    async def _capture(self, response: object) -> bytes:
        headers = {
            str(key).lower(): str(value)
            for key, value in (getattr(response, "headers", {}) or {}).items()
        }
        if int(getattr(response, "status", 0)) != 200:
            raise ZeblackProtobufError(
                f"unexpected protobuf response status: {getattr(response, 'status', 0)}"
            )
        content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/protobuf":
            raise ZeblackProtobufError(
                f"unexpected protobuf content-type: {content_type or '<missing>'}"
            )
        length = headers.get("content-length")
        if length is not None:
            try:
                if int(length) > MAX_PROTOBUF_BODY_BYTES:
                    raise ZeblackProtobufError("protobuf response exceeds the body limit")
            except ValueError as exc:
                raise ZeblackProtobufError("invalid protobuf content-length") from exc
        body = await response.body()  # type: ignore[attr-defined]
        if not isinstance(body, bytes) or len(body) > MAX_PROTOBUF_BODY_BYTES:
            raise ZeblackProtobufError("protobuf response exceeds the body limit")
        self._payloads.append(body)
        return body


def _decode_consistent_payloads(
    payloads: tuple[bytes, ...], *, title_id: str
) -> dict[str, ZeblackChapterV3]:
    decoded: list[dict[str, ZeblackChapterV3]] = []
    for payload in payloads:
        try:
            decoded.append(
                decode_zeblack_chapter_records(payload, expected_title_id=title_id)
            )
        except ZeblackProtobufError as exc:
            raise ZeblackLiveAccessError(
                "Zeblack chapter-list protobuf could not be decoded"
            ) from exc
    if not decoded:
        raise ZeblackLiveAccessError("Zeblack chapter-list protobuf was empty")
    first = decoded[0]
    first_content = decoded_chapter_content(first)
    if any(decoded_chapter_content(item) != first_content for item in decoded[1:]):
        raise ZeblackLiveAccessError(
            "Zeblack chapter-list protobuf responses disagree"
        )
    return first


async def observe_zeblack_live_access(
    page: Page,
    *,
    title_id: str,
    chapter_id: str,
    timeout_ms: int = ZEBLACK_LIVE_ACCESS_TIMEOUT_MS,
) -> ZeblackLiveAccessState:
    """Load the live chapter list and return current target access state."""

    if not str(title_id).isdecimal() or not str(chapter_id).isdecimal():
        raise ZeblackLiveAccessError("Zeblack live access identity must be numeric")
    snapshot = await observe_zeblack_chapter_list(
        page, title_id=title_id, timeout_ms=timeout_ms
    )
    target = snapshot.by_id.get(str(chapter_id))
    if target is None:
        raise ZeblackLiveAccessError(
            "Zeblack live chapter-list did not contain the target chapter"
        )
    return ZeblackLiveAccessState(
        title_id=str(title_id),
        chapter_id=str(chapter_id),
        target_main_name=target.main_name,
        status_value=target.status_value,
        status_name=CONSUMPTION_STATUS_NAMES.get(target.status_value, "UNKNOWN"),
        ticket_available_ids=snapshot.ticket_available_ids,
        target_remaining_rental_time=target.remaining_rental_time,
    )


async def observe_zeblack_chapter_list(
    page: Page,
    *,
    title_id: str,
    timeout_ms: int = ZEBLACK_LIVE_ACCESS_TIMEOUT_MS,
) -> ZeblackChapterListSnapshot:
    """Load one bounded chapter/list protobuf snapshot for a title."""

    if not str(title_id).isdecimal():
        raise ZeblackLiveAccessError("Zeblack title_id must be numeric")
    if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or timeout_ms <= 0:
        raise ValueError("timeout_ms must be a positive integer")

    observer = _LiveProtobufObserver()
    observer.attach(page)
    deadline = time.monotonic() + timeout_ms / 1000
    try:
        try:
            navigation_timeout_ms = max(1, observer._remaining_timeout_ms(deadline))
            await page.goto(
                canonical_zeblack_chapter_list_url(title_id),
                wait_until="domcontentloaded",
                timeout=navigation_timeout_ms,
            )
        except (PlaywrightTimeoutError, TimeoutError) as exc:
            raise ZeblackLiveAccessError(
                "Zeblack chapter-list navigation did not complete"
            ) from exc
        actual_title_id = parse_zeblack_chapter_list_title_id(str(page.url))
        if actual_title_id != str(title_id):
            raise ZeblackLiveAccessError(
                "Zeblack chapter-list navigation changed title identity"
            )
        remaining_ms = observer._remaining_timeout_ms(deadline)
        if remaining_ms <= 0:
            raise ZeblackLiveAccessError(
                "Zeblack chapter-list protobuf response timed out"
            )
        payloads = await observer.wait_for_payloads(page, remaining_ms)
    finally:
        observer.close()

    records = _decode_consistent_payloads(payloads, title_id=str(title_id))
    return ZeblackChapterListSnapshot(
        title_id=str(title_id),
        chapters=tuple(records.values()),
    )


__all__ = [
    "ZEBLACK_LIVE_ACCESS_TIMEOUT_MS",
    "ZeblackChapterListSnapshot",
    "ZeblackLiveAccessError",
    "ZeblackLiveAccessState",
    "canonical_zeblack_chapter_list_url",
    "observe_zeblack_chapter_list",
    "observe_zeblack_live_access",
    "parse_zeblack_chapter_list_title_id",
]
