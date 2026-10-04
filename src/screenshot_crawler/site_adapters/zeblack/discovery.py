"""Production Discovery adapter for Zeblack chapter listings."""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from urllib.parse import urlsplit

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from screenshot_crawler.discovery.base import DiscoveryAdapter
from screenshot_crawler.discovery.models import (
    DiscoveredItem,
    DiscoveredRecord,
    DiscoveredSource,
    DiscoveryMode,
)
from screenshot_crawler.discovery.service import DiscoveryIncompleteError
from screenshot_crawler.site_adapters.zeblack.adapter import (
    ZEBLACK_VIEWER_HOST,
    parse_zeblack_viewer_url,
)
from screenshot_crawler.site_adapters.zeblack.discovery_protobuf import (
    MAX_PROTOBUF_BODY_BYTES,
    ConsumptionStatus,
    ZeblackChapterV3,
    ZeblackProtobufError,
    decode_zeblack_chapter_records,
    decoded_chapter_content,
    map_zeblack_access_mode,
)
from screenshot_crawler.watchlist.models import DiscoveryScope, WatchlistTarget

ZEBLACK_API_HOST = "api2.zebrack-comic.com"
ZEBLACK_CHAPTER_LIST_PATH = "/api/v3/title_chapter_list"
WAIT_TIMEOUT_MS = 15_000
POLL_INTERVAL_MS = 100
DOM_SELECTOR = '[id^="chapter"]'
_DOM_ID = re.compile(r"^chapter(?P<chapter_id>[0-9]+)$")
_ORDER_LABEL = re.compile(
    r"^(?:#\s*(?P<hash>[0-9]+)|第\s*(?P<jp>[0-9]+)\s*話|(?P<episode>[0-9]+)\s*episode)"
    r"(?:\s+.*)?$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ZeblackListIdentity:
    title_id: str

    @property
    def canonical_url(self) -> str:
        return f"https://{ZEBLACK_VIEWER_HOST}/title/{self.title_id}/chapter/list"


@dataclass(frozen=True, slots=True)
class _DomChapter:
    chapter_id: str
    dom_index: int


def parse_zeblack_chapter_list_url(url: str) -> ZeblackListIdentity | None:
    """Parse the strict canonical Zeblack chapter-list target."""

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
    if len(parts) != 5 or parts[1] != "title" or parts[3] != "chapter" or parts[4] != "list":
        return None
    title_id = parts[2]
    if not title_id.isdecimal():
        return None
    return ZeblackListIdentity(title_id=title_id)


def canonical_zeblack_viewer_url(title_id: str, chapter_id: str) -> str:
    """Build the query/fragment-free canonical viewer target."""

    return f"https://{ZEBLACK_VIEWER_HOST}/title/{title_id}/chapter/{chapter_id}/viewer"


def parse_zeblack_order_label(main_name: str) -> tuple[str | None, str]:
    """Parse only an unambiguous numeric label and retain the raw label."""

    label = str(main_name).strip()
    match = _ORDER_LABEL.fullmatch(" ".join(label.split()))
    if match is None:
        return None, label
    number = next(value for value in match.groups() if value is not None)
    return str(int(number)), label


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


class _ProtobufResponseObserver:
    """Capture only the exact chapter-list response before page navigation."""

    def __init__(self) -> None:
        self._page: Page | None = None
        self._tasks: list[asyncio.Task[bytes]] = []
        self._processed_tasks: set[asyncio.Task[bytes]] = set()
        self._payloads: list[bytes] = []
        self._errors: list[BaseException] = []
        self._listener = self._on_response

    def attach(self, page: Page) -> None:
        self._page = page
        page.on("response", self._listener)

    async def wait_for_payloads(self, page: Page) -> tuple[bytes, ...]:
        deadline = time.monotonic() + WAIT_TIMEOUT_MS / 1000
        while time.monotonic() < deadline:
            tasks = tuple(self._tasks)
            if tasks:
                await self._drain_tasks(tasks)
            if self._payloads:
                # Let same-load duplicate responses arrive, then compare all of
                # them instead of silently selecting the last response.
                await page.wait_for_timeout(POLL_INTERVAL_MS)
                if len(self._tasks) == len(tasks):
                    await self._drain_tasks(tuple(self._tasks))
                    if self._errors:
                        raise DiscoveryIncompleteError(
                            "Zeblack chapter-list protobuf response was invalid"
                        ) from self._errors[0]
                    return tuple(self._payloads)
            await page.wait_for_timeout(POLL_INTERVAL_MS)
        if self._errors:
            raise DiscoveryIncompleteError(
                "Zeblack chapter-list protobuf response was invalid"
            ) from self._errors[0]
        raise DiscoveryIncompleteError(
            "Zeblack title_chapter_list protobuf response was not observed"
        )

    def close(self) -> None:
        if self._page is not None:
            self._page.remove_listener("response", self._listener)
            self._page = None
        for task in self._tasks:
            if not task.done():
                task.cancel()

    async def _drain_tasks(self, tasks: tuple[asyncio.Task[bytes], ...]) -> None:
        for task in tasks:
            if task in self._processed_tasks:
                continue
            try:
                await task
            except BaseException as exc:  # noqa: BLE001 - response validation is fail-closed
                self._errors.append(exc)
            self._processed_tasks.add(task)

    def _on_response(self, response: object) -> None:
        url = str(getattr(response, "url", ""))
        if not _response_url_is_target(url):
            return
        self._tasks.append(asyncio.create_task(self._capture(response)))

    async def _capture(self, response: object) -> bytes:
        raw_headers = getattr(response, "headers", {}) or {}
        headers = {str(key).lower(): value for key, value in raw_headers.items()}
        content_type = str(headers.get("content-type", "")).split(";", 1)[0].strip().lower()
        status = int(getattr(response, "status", 0))
        if status != 200:
            raise ZeblackProtobufError(f"unexpected protobuf response status: {status}")
        if content_type != "application/protobuf":
            raise ZeblackProtobufError(
                f"unexpected protobuf content-type: {content_type or '<missing>'}"
            )
        content_length = headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > MAX_PROTOBUF_BODY_BYTES:
                    raise ZeblackProtobufError("protobuf response exceeds the body limit")
            except ValueError as exc:
                raise ZeblackProtobufError("invalid protobuf content-length") from exc
        body = await response.body()  # type: ignore[attr-defined]
        if not isinstance(body, bytes) or len(body) > MAX_PROTOBUF_BODY_BYTES:
            raise ZeblackProtobufError("protobuf response exceeds the body limit")
        self._payloads.append(body)
        return body


class ZeblackDiscoveryAdapter(DiscoveryAdapter):
    """Enumerate the complete Zeblack chapter list in canonical order."""

    supports_bounded_discovery = True

    async def iter_records(
        self,
        page: Page,
        target: WatchlistTarget,
        mode: DiscoveryMode,
    ) -> AsyncIterator[DiscoveredRecord]:
        del mode
        target_identity = parse_zeblack_chapter_list_url(target.url)
        if target_identity is None:
            raise DiscoveryIncompleteError(
                "Watchlist target must be a strict Zeblack chapter-list URL"
            )

        try:
            dom_rows, protobuf_records = await self._load_listing(page, target_identity)
            records = self._build_records(
                dom_rows,
                protobuf_records,
                target=target,
                target_identity=target_identity,
            )
            if target.discovery_scope is not None:
                records = self._apply_discovery_scope(
                    records, target_identity.title_id, target.discovery_scope
                )
        except DiscoveryIncompleteError:
            raise
        except (PlaywrightTimeoutError, TimeoutError, ZeblackProtobufError) as exc:
            raise DiscoveryIncompleteError("Zeblack chapter listing is incomplete") from exc

        # All listing, protobuf, set, order, and boundary validation completes
        # before the first yield. This is intentional: DiscoveryService writes
        # records as it receives them.
        for record in records:
            yield record

    async def _load_listing(
        self, page: Page, target_identity: ZeblackListIdentity
    ) -> tuple[list[_DomChapter], dict[str, ZeblackChapterV3]]:
        observer = _ProtobufResponseObserver()
        observer.attach(page)
        try:
            await page.goto(
                target_identity.canonical_url,
                wait_until="domcontentloaded",
                timeout=WAIT_TIMEOUT_MS,
            )
            actual = parse_zeblack_chapter_list_url(str(page.url))
            if actual is None or actual.title_id != target_identity.title_id:
                raise DiscoveryIncompleteError(
                    "Zeblack chapter-list navigation changed target identity"
                )
            dom_rows = await self._wait_for_dom_rows(page)
            payloads = await observer.wait_for_payloads(page)
        except DiscoveryIncompleteError:
            raise
        except (PlaywrightTimeoutError, TimeoutError) as exc:
            raise DiscoveryIncompleteError("Zeblack chapter listing did not load") from exc
        finally:
            observer.close()

        decoded: list[dict[str, ZeblackChapterV3]] = []
        for payload in payloads:
            try:
                decoded.append(
                    decode_zeblack_chapter_records(
                        payload, expected_title_id=target_identity.title_id
                    )
                )
            except ZeblackProtobufError as exc:
                raise DiscoveryIncompleteError(
                    "Zeblack chapter-list protobuf could not be decoded"
                ) from exc
        if not decoded:
            raise DiscoveryIncompleteError("Zeblack chapter-list protobuf was empty")
        first = decoded[0]
        first_content = decoded_chapter_content(first)
        if any(decoded_chapter_content(item) != first_content for item in decoded[1:]):
            raise DiscoveryIncompleteError(
                "Zeblack chapter-list protobuf responses disagree"
            )
        self._validate_exact_sets(dom_rows, first)
        self._validate_dom_order(dom_rows, first)
        return dom_rows, first

    async def _wait_for_dom_rows(self, page: Page) -> list[_DomChapter]:
        previous: tuple[str, ...] | None = None
        stable = 0
        deadline = time.monotonic() + WAIT_TIMEOUT_MS / 1000
        while time.monotonic() < deadline:
            rows = await self._dom_rows(page)
            signature = tuple(row.chapter_id for row in rows)
            if signature:
                if signature == previous:
                    stable += 1
                    if stable >= 2:
                        return rows
                else:
                    previous = signature
                    stable = 1
            else:
                previous = None
                stable = 0
            await page.wait_for_timeout(POLL_INTERVAL_MS)
        raise DiscoveryIncompleteError("Zeblack chapter DOM did not stabilize")

    @staticmethod
    async def _dom_rows(page: Page) -> list[_DomChapter]:
        locator = page.locator(DOM_SELECTOR)
        rows: list[_DomChapter] = []
        for index in range(await locator.count()):
            raw_id = await locator.nth(index).get_attribute("id")
            if raw_id is None:
                raise DiscoveryIncompleteError("Zeblack DOM chapter row has no id")
            match = _DOM_ID.fullmatch(raw_id)
            if match is None:
                raise DiscoveryIncompleteError(
                    f"Zeblack DOM chapter id is not strict: {raw_id!r}"
                )
            rows.append(_DomChapter(match.group("chapter_id"), index))
        if len({row.chapter_id for row in rows}) != len(rows):
            raise DiscoveryIncompleteError("duplicate Zeblack DOM chapter ids")
        return rows

    @staticmethod
    def _validate_exact_sets(
        dom_rows: list[_DomChapter], protobuf_records: dict[str, ZeblackChapterV3]
    ) -> None:
        dom_ids = [row.chapter_id for row in dom_rows]
        protobuf_ids = list(protobuf_records)
        dom_set = set(dom_ids)
        protobuf_set = set(protobuf_ids)
        if len(protobuf_ids) != len(protobuf_set):
            raise DiscoveryIncompleteError("duplicate Zeblack protobuf chapter ids")
        dom_only = sorted(dom_set - protobuf_set)
        protobuf_only = sorted(protobuf_set - dom_set)
        if dom_only or protobuf_only or dom_set != protobuf_set:
            raise DiscoveryIncompleteError(
                "Zeblack DOM/protobuf chapter ID sets do not match"
            )

    @staticmethod
    def _validate_dom_order(
        dom_rows: list[_DomChapter], protobuf_records: dict[str, ZeblackChapterV3]
    ) -> None:
        numeric_labels = [
            parse_zeblack_order_label(protobuf_records[row.chapter_id].main_name)[0]
            for row in dom_rows
        ]
        values = [int(value) for value in numeric_labels if value is not None]
        if len(values) >= 2 and any(left > right for left, right in pairwise(values)):
            raise DiscoveryIncompleteError(
                "Zeblack DOM numeric chapter labels are not oldest-first"
            )

    @staticmethod
    def _build_records(
        dom_rows: list[_DomChapter],
        protobuf_records: dict[str, ZeblackChapterV3],
        *,
        target: WatchlistTarget,
        target_identity: ZeblackListIdentity,
    ) -> list[DiscoveredRecord]:
        records: list[DiscoveredRecord] = []
        observed_at = datetime.now(UTC)
        for row in reversed(dom_rows):
            chapter = protobuf_records.get(row.chapter_id)
            if chapter is None or chapter.title_id != target_identity.title_id:
                raise DiscoveryIncompleteError("Zeblack chapter identity cross-check failed")
            order_key, order_label = parse_zeblack_order_label(chapter.main_name)
            records.append(
                DiscoveredRecord(
                    item=DiscoveredItem(
                        canonical_title=target.label,
                        author=None,
                        genre=None,
                        kind="episode",
                        order_key=order_key,
                        order_label=order_label,
                    ),
                    source=DiscoveredSource(
                        external_id=chapter.chapter_id,
                        url=canonical_zeblack_viewer_url(
                            target_identity.title_id, chapter.chapter_id
                        ),
                        access_mode=map_zeblack_access_mode(chapter.status_value),
                        access_granted_until=(
                            observed_at
                            + timedelta(seconds=chapter.remaining_rental_time)
                            if chapter.status_value
                            == int(ConsumptionStatus.RENTAL)
                            and chapter.remaining_rental_time is not None
                            and chapter.remaining_rental_time > 0
                            else None
                        ),
                        access_granted_until_observed=True,
                        available=True,
                        global_display_position=row.dom_index + 1,
                    ),
                )
            )
        return records

    @staticmethod
    def _apply_discovery_scope(
        records: list[DiscoveredRecord], title_id: str, scope: DiscoveryScope
    ) -> list[DiscoveredRecord]:
        if scope.from_url is None and scope.through_url is None:
            raise DiscoveryIncompleteError("Zeblack bounded Discovery scope has no boundary")
        indices: dict[str, int] = {}
        for name, boundary_url in (
            ("from_url", scope.from_url),
            ("through_url", scope.through_url),
        ):
            if boundary_url is None:
                continue
            boundary = parse_zeblack_viewer_url(boundary_url)
            if boundary is None or boundary.title_id != title_id:
                raise DiscoveryIncompleteError(
                    f"Zeblack {name} boundary is not in the target title"
                )
            index = next(
                (
                    position
                    for position, record in enumerate(records)
                    if record.source.external_id == boundary.chapter_id
                ),
                None,
            )
            if index is None:
                raise DiscoveryIncompleteError(
                    f"Zeblack {name} boundary chapter was not found"
                )
            indices[name] = index
        from_index = indices.get("from_url", 0)
        through_index = indices.get("through_url", len(records) - 1)
        if from_index > through_index:
            raise DiscoveryIncompleteError("Zeblack bounded Discovery boundaries are reversed")
        return records[from_index : through_index + 1]


__all__ = [
    "ZEBLACK_API_HOST",
    "ZEBLACK_CHAPTER_LIST_PATH",
    "ZeblackDiscoveryAdapter",
    "ZeblackListIdentity",
    "canonical_zeblack_viewer_url",
    "map_zeblack_access_mode",
    "parse_zeblack_chapter_list_url",
    "parse_zeblack_order_label",
]
