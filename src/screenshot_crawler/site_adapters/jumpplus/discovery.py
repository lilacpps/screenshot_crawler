"""Production Discovery adapter for Shonen Jump+ episode listings.

The DOM listing is the authority.  Jump+'s readable-product responses are
captured only as bounded, optional evidence for access-state reconciliation;
failure to observe them does not make an otherwise safe DOM discovery fail.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from itertools import pairwise
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

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
from screenshot_crawler.watchlist.models import WatchlistTarget

JST = timezone(timedelta(hours=9), name="JST")
ALLOWED_HOSTS = frozenset({"shonenjumpplus.com", "www.shonenjumpplus.com"})
MAX_MORE_CLICKS = 20
WAIT_TIMEOUT_MS = 15_000
POLL_INTERVAL_MS = 250
MAX_RESPONSE_BODY = 2_000_000

_EPISODE_PATH = re.compile(r"^/episode/(?P<episode_id>[0-9]+)/?$")
_DATE = re.compile(
    r"(?P<year>\d{4})(?:年|/|-)(?P<month>\d{1,2})(?:月|/|-)(?P<day>\d{1,2})日?"
)
_ORDER = re.compile(r"^(?:第\s*)?(?P<number>\d+)\s*話(?:\s|$)")
_RANGE = re.compile(r"^\s*(?P<first>\d+)\s*[-–—〜～]\s*(?P<last>\d+)\s*$")
_DOM_EXPIRY = re.compile(
    r"(?P<year>\d{4})[年/-](?P<month>\d{1,2})[月/-](?P<day>\d{1,2})日?"
    r"\s+(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*まで"
)
_FORBIDDEN_CONTROL = re.compile(
    r"(?:購入|ポイント|レンタル|ログイン|会員登録|次の話|前の話|コメント|アプリ|広告|"
    r"purchase|point|rental|login|next|previous)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class JumpPlusRange:
    label: str
    dom_index: int
    first: int | None = None
    last: int | None = None


def parse_jumpplus_episode_url(url: str) -> str | None:
    """Return the numeric episode id for an allowed Jump+ episode URL."""

    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if (parsed.hostname or "").lower() not in ALLOWED_HOSTS:
        return None
    match = _EPISODE_PATH.fullmatch(parsed.path)
    return match.group("episode_id") if match else None


def canonical_jumpplus_episode_url(url: str) -> str:
    """Return the query/fragment-free canonical URL or raise ``ValueError``."""

    episode_id = parse_jumpplus_episode_url(url)
    if episode_id is None:
        raise ValueError(f"Not a Jump+ episode URL: {url!r}")
    return f"https://shonenjumpplus.com/episode/{episode_id}"


def parse_jumpplus_range_label(label: str) -> tuple[int, int] | None:
    """Parse a numeric range without assuming any fixed range values."""

    match = _RANGE.fullmatch(" ".join(label.split()))
    if match is None:
        return None
    return int(match.group("first")), int(match.group("last"))


def parse_jumpplus_published_at(value: str | None) -> datetime | None:
    """Parse a date-only listing value as a JST calendar-day timestamp."""

    match = _DATE.search(" ".join((value or "").split()))
    if match is None:
        return None
    try:
        return datetime(
            int(match["year"]), int(match["month"]), int(match["day"]), tzinfo=JST
        )
    except ValueError:
        return None


def parse_jumpplus_dom_expiry(value: str | None) -> datetime | None:
    """Parse the displayed minute-granularity expiry conservatively in JST."""

    match = _DOM_EXPIRY.search(" ".join((value or "").split()))
    if match is None:
        return None
    try:
        return datetime(
            int(match["year"]),
            int(match["month"]),
            int(match["day"]),
            int(match["hour"]),
            int(match["minute"]),
            tzinfo=JST,
        )
    except ValueError:
        return None


def parse_jumpplus_structured_expiry(value: Any) -> datetime | None:
    """Parse a structured ISO expiry and normalize it to an aware timestamp."""

    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(JST)


def parse_jumpplus_order_label(label: str | None) -> tuple[str | None, str | None]:
    """Preserve the visible label and only parse an unambiguous numeric episode."""

    normalized = " ".join((label or "").split())
    if not normalized:
        return None, None
    match = _ORDER.match(normalized)
    return (str(int(match["number"])), normalized) if match else (None, normalized)


def extract_jumpplus_series_ids(snapshot: dict[str, Any]) -> tuple[str, ...]:
    """Return stable series ids found in the scoped DOM/data attributes."""

    values = {str(value) for value in snapshot.get("series_ids", []) if value}
    return tuple(sorted(values))


def identity_signature(rows: list[dict[str, Any]]) -> tuple[str, ...]:
    """Return the order-preserving identity signature used for progress checks."""

    return tuple(str(row["episode_id"]) for row in rows if row.get("episode_id"))


def _structured_states(payload: Any) -> dict[str, dict[str, Any]]:
    states: dict[str, dict[str, Any]] = {}

    def visit(value: Any) -> None:
        if isinstance(value, list):
            for child in value:
                visit(child)
            return
        if not isinstance(value, dict):
            return
        product_id = value.get("readable_product_id")
        if product_id is not None and (
            isinstance(value.get("purchase_info"), dict)
            or isinstance(value.get("status"), dict)
        ):
            states[str(product_id)] = value
        for child in value.values():
            if isinstance(child, (dict, list)):
                visit(child)

    visit(payload)
    return states


class _StructuredStateObserver:
    """Bounded optional observer for Jump+'s readable-product endpoint."""

    def __init__(self) -> None:
        self.states: dict[str, dict[str, Any]] = {}
        self.aggregate_ids: set[str] = set()
        self.total_counts: set[int] = set()
        self._tasks: set[asyncio.Task[None]] = set()
        self._page: Page | None = None
        self._listener: Any = None

    def attach(self, page: Page) -> None:
        self._page = page
        self._listener = self._on_response
        page.on("response", self._listener)

    def _on_response(self, response: Any) -> None:
        task = asyncio.create_task(self._capture(response))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _capture(self, response: Any) -> None:
        try:
            parsed = urlparse(str(response.url))
            if (parsed.hostname or "").lower() not in ALLOWED_HOSTS:
                return
            if parsed.path != "/api/viewer/pagination_readable_products":
                return
            query = parse_qs(parsed.query)
            aggregate_id = query.get("aggregate_id", [None])[0]
            if aggregate_id:
                self.aggregate_ids.add(str(aggregate_id))
            body = await response.body()
            if len(body) > MAX_RESPONSE_BODY:
                return
            payload = json.loads(body.decode("utf-8"))
            self.states.update(_structured_states(payload))
            self._find_totals(payload)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            return
        except Exception:  # noqa: BLE001 - network evidence is optional
            return

    def _find_totals(self, value: Any) -> None:
        if isinstance(value, list):
            for child in value:
                self._find_totals(child)
            return
        if not isinstance(value, dict):
            return
        for key in ("total", "total_count", "totalCount"):
            candidate = value.get(key)
            if isinstance(candidate, int) and candidate >= 0:
                self.total_counts.add(candidate)
        for child in value.values():
            if isinstance(child, (dict, list)):
                self._find_totals(child)

    async def close(self) -> None:
        if self._page is not None and self._listener is not None:
            self._page.remove_listener("response", self._listener)
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)


class JumpPlusDiscoveryAdapter(DiscoveryAdapter):
    """Enumerate Jump+ episode rows safely in latest-first order."""

    async def iter_records(
        self,
        page: Page,
        target: WatchlistTarget,
        mode: DiscoveryMode,
    ) -> AsyncIterator[DiscoveredRecord]:
        target_episode_id = parse_jumpplus_episode_url(target.url)
        if target_episode_id is None:
            raise DiscoveryIncompleteError("Watchlist target must be a Jump+ episode URL")

        observer = _StructuredStateObserver()
        observer.attach(page)
        records_by_id: dict[str, DiscoveredRecord] = {}
        try:
            try:
                await page.goto(
                    canonical_jumpplus_episode_url(target.url),
                    wait_until="domcontentloaded",
                    timeout=WAIT_TIMEOUT_MS,
                )
            except (PlaywrightTimeoutError, TimeoutError) as exc:
                raise DiscoveryIncompleteError("Jump+ episode page did not load") from exc

            initial = await self._load_initial_listing(page, target_episode_id)
            series_id = self._validate_scope(initial, target_episode_id, None)
            self._validate_network_scope(observer, series_id)
            ranges = self._ranges(initial)
            if ranges:
                self._validate_range_order(ranges)
            else:
                ranges = [None]

            for range_info in ranges:
                if range_info is not None:
                    await self._switch_range(page, target_episode_id, range_info, series_id)
                range_snapshot = await self._wait_for_listing(page, target_episode_id)
                self._validate_scope(range_snapshot, target_episode_id, series_id)
                self._validate_network_scope(observer, series_id)
                rows = await self._expand_range(page, target_episode_id, series_id)
                expected = (
                    range_info.first - range_info.last + 1
                    if range_info and range_info.first is not None and range_info.last is not None
                    else None
                )
                if expected is not None and len(rows) != expected:
                    raise DiscoveryIncompleteError(
                        f"Jump+ range {range_info.label!r} has {len(rows)} rows; "
                        f"expected {expected}"
                    )
                for row in rows:
                    record = self._record_from_row(
                        row,
                        range_snapshot,
                        observer.states,
                        target_episode_id,
                    )
                    existing = records_by_id.get(record.source.external_id)
                    if existing is not None:
                        if self._record_fingerprint(existing) != self._record_fingerprint(record):
                            raise DiscoveryIncompleteError(
                                f"Jump+ duplicate episode has conflicting metadata: "
                                f"{record.source.external_id}"
                            )
                        continue
                    records_by_id[record.source.external_id] = record
                    if mode == "incremental":
                        yield record

            if not records_by_id:
                raise DiscoveryIncompleteError("Jump+ episode listing contained no episodes")
            if observer.total_counts and len(observer.total_counts) == 1:
                expected_total = next(iter(observer.total_counts))
                if expected_total and len(records_by_id) != expected_total:
                    raise DiscoveryIncompleteError(
                        f"Jump+ pagination total {expected_total} disagrees with "
                        f"DOM count {len(records_by_id)}"
                    )
            if mode == "full":
                for record in records_by_id.values():
                    yield record
        finally:
            await observer.close()

    @staticmethod
    def _ranges(snapshot: dict[str, Any]) -> list[JumpPlusRange]:
        ranges: list[JumpPlusRange] = []
        seen: set[str] = set()
        for index, control in enumerate(snapshot.get("range_controls", [])):
            label = " ".join(str(control.get("text") or "").split())
            if not label or label in seen:
                raise DiscoveryIncompleteError("Jump+ range controls are not unique")
            parsed = parse_jumpplus_range_label(label)
            if parsed is None:
                raise DiscoveryIncompleteError(f"Unparseable Jump+ range label: {label!r}")
            seen.add(label)
            ranges.append(JumpPlusRange(label, index, *parsed))
        return ranges

    @staticmethod
    def _validate_range_order(ranges: list[JumpPlusRange]) -> None:
        uppers = [item.first for item in ranges]
        if any(value is None for value in uppers):
            raise DiscoveryIncompleteError("Jump+ range has no numeric upper bound")
        if any(left <= right for left, right in pairwise(uppers)):
            raise DiscoveryIncompleteError("Jump+ range DOM order is not latest-first")
        if any(item.first < item.last for item in ranges):
            raise DiscoveryIncompleteError("Jump+ range label has reversed bounds")

    async def _switch_range(
        self,
        page: Page,
        target_episode_id: str,
        desired: JumpPlusRange,
        series_id: str,
    ) -> None:
        current = await self._snapshot(page, target_episode_id)
        selected = next(
            (
                control
                for control in current.get("range_controls", [])
                if control.get("selected") in {"true", ""} or control.get("current")
            ),
            None,
        )
        if selected and " ".join(str(selected.get("text") or "").split()) == desired.label:
            return
        candidates = [
            control
            for control in current.get("range_controls", [])
            if " ".join(str(control.get("text") or "").split()) == desired.label
        ]
        if len(candidates) != 1:
            raise DiscoveryIncompleteError(
                f"Jump+ range control disappeared or became ambiguous: {desired.label!r}"
            )
        candidate = candidates[0]
        if candidate.get("is_episode_link") or _FORBIDDEN_CONTROL.search(desired.label):
            raise DiscoveryIncompleteError("Jump+ range control failed safety validation")
        selector = candidate.get("selector")
        if not selector:
            raise DiscoveryIncompleteError("Jump+ range control has no stable selector")
        locator = page.locator(str(selector))
        if await locator.count() != 1:
            raise DiscoveryIncompleteError("Jump+ range selector is not unique")
        before_url = page.url
        before_signature = identity_signature(current.get("episodes", []))
        await locator.scroll_into_view_if_needed()
        await locator.click(timeout=WAIT_TIMEOUT_MS, no_wait_after=True)
        for _ in range(WAIT_TIMEOUT_MS // POLL_INTERVAL_MS):
            if page.url != before_url or parse_jumpplus_episode_url(page.url) != target_episode_id:
                raise DiscoveryIncompleteError("Jump+ range click navigated away from target episode")
            await page.wait_for_timeout(POLL_INTERVAL_MS)
            after = await self._snapshot(page, target_episode_id)
            if not after.get("episodes"):
                continue
            self._validate_scope(after, target_episode_id, series_id)
            after_selected = next(
                (
                    control
                    for control in after.get("range_controls", [])
                    if control.get("selected") in {"true", ""} or control.get("current")
                ),
                None,
            )
            after_label = " ".join(str((after_selected or {}).get("text") or "").split())
            if after_label == desired.label or identity_signature(after.get("episodes", [])) != before_signature:
                return
        raise DiscoveryIncompleteError(f"Jump+ range did not advance: {desired.label!r}")

    async def _expand_range(
        self,
        page: Page,
        target_episode_id: str,
        series_id: str,
    ) -> list[dict[str, Any]]:
        for _ in range(MAX_MORE_CLICKS + 1):
            snapshot = await self._wait_for_listing(page, target_episode_id)
            self._validate_scope(snapshot, target_episode_id, series_id)
            visible = [item for item in snapshot.get("more_controls", []) if item.get("visible")]
            disabled = [item for item in visible if item.get("disabled")]
            enabled = [item for item in visible if not item.get("disabled")]
            if disabled:
                raise DiscoveryIncompleteError("Jump+ more control is disabled while visible")
            if not enabled:
                return snapshot.get("episodes", [])
            if len(enabled) != 1:
                raise DiscoveryIncompleteError("Jump+ more control is ambiguous")
            candidate = enabled[0]
            if candidate.get("is_episode_link") or _FORBIDDEN_CONTROL.search(
                str(candidate.get("text") or "")
            ):
                raise DiscoveryIncompleteError("Jump+ more control failed safety validation")
            selector = candidate.get("selector")
            if not selector:
                raise DiscoveryIncompleteError("Jump+ more control has no stable selector")
            locator = page.locator(str(selector))
            if await locator.count() != 1:
                raise DiscoveryIncompleteError("Jump+ more selector is not unique")
            before_url = page.url
            before_ids = set(identity_signature(snapshot.get("episodes", [])))
            await locator.scroll_into_view_if_needed()
            await locator.click(timeout=WAIT_TIMEOUT_MS, no_wait_after=True)
            progressed = False
            for _ in range(WAIT_TIMEOUT_MS // POLL_INTERVAL_MS):
                if page.url != before_url or parse_jumpplus_episode_url(page.url) != target_episode_id:
                    raise DiscoveryIncompleteError("Jump+ more click navigated away from target episode")
                await page.wait_for_timeout(POLL_INTERVAL_MS)
                after = await self._snapshot(page, target_episode_id)
                self._validate_scope(after, target_episode_id, series_id)
                if len(set(identity_signature(after.get("episodes", []))) - before_ids) > 0:
                    progressed = True
                    break
            if not progressed:
                raise DiscoveryIncompleteError("Jump+ more click did not grow episode identities")
        raise DiscoveryIncompleteError("Jump+ more expansion exceeded its bounded limit")

    async def _wait_for_listing(self, page: Page, target_episode_id: str) -> dict[str, Any]:
        section = page.locator("section.series-information.type-episode")
        if await section.count():
            await section.scroll_into_view_if_needed()
        pagination = page.locator("#pagination-top")
        if await pagination.count():
            await pagination.scroll_into_view_if_needed()
        last: dict[str, Any] = {}
        for _ in range(WAIT_TIMEOUT_MS // POLL_INTERVAL_MS):
            last = await self._snapshot(page, target_episode_id)
            if last.get("scope") and last.get("episodes"):
                return last
            await page.wait_for_timeout(POLL_INTERVAL_MS)
        raise DiscoveryIncompleteError("Jump+ episode listing did not become observable")

    async def _load_initial_listing(
        self, page: Page, target_episode_id: str
    ) -> dict[str, Any]:
        """Handle the observed bounded React listing-mount race."""

        last_error: DiscoveryIncompleteError | None = None
        for attempt in range(3):
            try:
                await self._activate_episode_tab(page)
                return await self._wait_for_listing(page, target_episode_id)
            except DiscoveryIncompleteError as exc:
                last_error = exc
                if attempt == 2:
                    break
                try:
                    await page.reload(
                        wait_until="domcontentloaded",
                        timeout=WAIT_TIMEOUT_MS,
                    )
                except (PlaywrightTimeoutError, TimeoutError) as reload_error:
                    last_error = DiscoveryIncompleteError(
                        "Jump+ episode page did not reload while mounting listing"
                    )
                    if attempt == 1:
                        raise last_error from reload_error
        raise last_error or DiscoveryIncompleteError("Jump+ listing did not load")

    @staticmethod
    async def _activate_episode_tab(page: Page) -> None:
        """Activate only the episode-list tab when React left its panel empty."""

        if await page.locator(
            "section.series-information.type-episode .js-readable-products-pagination"
        ).count():
            return
        tab = page.locator(
            'section.series-information.type-episode [role="tab"][data-key="episode"]'
        )
        try:
            await tab.wait_for(state="visible", timeout=WAIT_TIMEOUT_MS)
        except PlaywrightTimeoutError as exc:
            raise DiscoveryIncompleteError("Jump+ episode listing tab did not mount") from exc
        if await page.locator("#pagination-top ul").count():
            return
        try:
            await tab.click(timeout=WAIT_TIMEOUT_MS)
        except PlaywrightTimeoutError as exc:
            raise DiscoveryIncompleteError("Jump+ episode listing tab could not activate") from exc

    async def _snapshot(self, page: Page, target_episode_id: str) -> dict[str, Any]:
        return await page.evaluate(_LISTING_SNAPSHOT_SCRIPT, {"targetEpisodeId": target_episode_id})

    @staticmethod
    def _validate_scope(
        snapshot: dict[str, Any], target_episode_id: str, expected_series_id: str | None
    ) -> str:
        scope = snapshot.get("scope") or {}
        if scope.get("variant") not in {"role-tabpanel", "direct-pagination"}:
            raise DiscoveryIncompleteError("Jump+ episode listing scope variant is unknown")
        if snapshot.get("listing_count") != 1:
            raise DiscoveryIncompleteError("Jump+ episode list scope is not unique")
        series_ids = extract_jumpplus_series_ids(snapshot)
        if len(series_ids) != 1:
            raise DiscoveryIncompleteError("Jump+ listing has no unique series identity")
        if expected_series_id is not None and series_ids[0] != expected_series_id:
            raise DiscoveryIncompleteError("Jump+ listing series identity changed")
        rows = snapshot.get("episodes") or []
        if not rows:
            raise DiscoveryIncompleteError("Jump+ listing has no episode rows")
        for row in rows:
            episode_id = row.get("episode_id")
            if not episode_id:
                raise DiscoveryIncompleteError("Jump+ episode row has no safe identity")
            if row.get("href"):
                try:
                    canonical_jumpplus_episode_url(
                        urljoin("https://shonenjumpplus.com", str(row["href"]))
                    )
                except ValueError as exc:
                    raise DiscoveryIncompleteError(
                        "Jump+ episode row has an invalid URL"
                    ) from exc
        del target_episode_id
        return series_ids[0]

    @staticmethod
    def _validate_network_scope(observer: _StructuredStateObserver, series_id: str) -> None:
        if observer.aggregate_ids and observer.aggregate_ids != {series_id}:
            raise DiscoveryIncompleteError("Jump+ pagination aggregate id disagrees with DOM")

    @staticmethod
    def _record_from_row(
        row: dict[str, Any],
        snapshot: dict[str, Any],
        structured_states: dict[str, dict[str, Any]],
        target_episode_id: str,
    ) -> DiscoveredRecord:
        episode_id = str(row.get("episode_id") or "")
        if not episode_id:
            raise DiscoveryIncompleteError("Jump+ row identity is empty")
        href = row.get("href")
        if not href:
            if not row.get("is_current"):
                raise DiscoveryIncompleteError("Jump+ href-less row is not marked current")
            href = f"/episode/{target_episode_id}"
        try:
            url = canonical_jumpplus_episode_url(urljoin("https://shonenjumpplus.com", str(href)))
        except ValueError as exc:
            raise DiscoveryIncompleteError("Jump+ row has a non-episode href") from exc
        if parse_jumpplus_episode_url(url) != episode_id:
            raise DiscoveryIncompleteError("Jump+ row href and episode id disagree")

        order_key, order_label = parse_jumpplus_order_label(row.get("title_text"))
        access_mode, grant_until = map_jumpplus_access(
            row,
            structured_states.get(episode_id),
        )
        checked_at = datetime.now(JST)
        work = snapshot.get("work") or {}
        return DiscoveredRecord(
            item=DiscoveredItem(
                canonical_title=work.get("title"),
                author=work.get("author"),
                genre="漫画",
                kind="episode",
                order_key=order_key,
                order_label=order_label,
            ),
            source=DiscoveredSource(
                external_id=episode_id,
                url=url,
                access_mode=access_mode,
                free_until=None,
                published_at=parse_jumpplus_published_at(row.get("published_text")),
                access_granted_until=grant_until,
                access_granted_until_observed=True,
                available=True,
                access_checked_at=checked_at,
                last_seen_at=checked_at,
            ),
        )

    @staticmethod
    def _record_fingerprint(record: DiscoveredRecord) -> tuple[Any, ...]:
        return (
            record.item.canonical_title,
            record.item.author,
            record.item.order_key,
            record.item.order_label,
            record.source.url,
            record.source.access_mode,
            record.source.access_granted_until,
            record.source.published_at,
        )


def map_jumpplus_access(
    row: dict[str, Any], structured: dict[str, Any] | None
) -> tuple[str, datetime | None]:
    """Map DOM/structured evidence to ``(access_mode, grant_until)``."""

    dom_text = " ".join(str(value) for value in row.get("access_text") or [])
    dom_classes = " ".join(str(value) for value in row.get("access_class") or [])
    dom_blob = f"{dom_text} {dom_classes} {row.get('access_title') or ''}"
    dom_scheduled = "無料公開予定" in dom_blob
    dom_active = "レンタル中" in dom_blob
    dom_free = ("series-episode-list-is-free" in dom_classes or "無料" in dom_text) and not dom_scheduled
    dom_paid = any(token in dom_blob.lower() for token in ("pt", "ポイント", "レンタル", "rental"))
    dom_expiry = parse_jumpplus_dom_expiry(dom_blob)
    dom_kind = "active" if dom_active else "free" if dom_free and not dom_paid else "paid" if dom_paid else "unknown"

    structured_kind = "unknown"
    structured_expiry: datetime | None = None
    if structured:
        purchase = structured.get("purchase_info") or {}
        status = structured.get("status") or {}
        structured_expiry = parse_jumpplus_structured_expiry(
            status.get("rental_end_at") or purchase.get("rental_end_at")
        )
        structured_active = (
            status.get("label") in {"has_rented", "rented"}
            or purchase.get("has_rented_via_point") is True
            or purchase.get("has_rented_via_ticket") is True
            or structured_expiry is not None
        )
        structured_free = status.get("label") == "is_free" or purchase.get("is_free") is True
        structured_paid = (
            status.get("label") in {"is_rentable", "is_purchasable"}
            or purchase.get("can_read") is False
            or purchase.get("rental_price") is not None
        )
        structured_kind = (
            "active" if structured_active else "free" if structured_free else "paid" if structured_paid else "unknown"
        )

    if structured_kind != "unknown" and dom_kind != "unknown" and structured_kind != dom_kind:
        return "unknown", None
    kind = structured_kind if structured_kind != "unknown" else dom_kind
    if kind == "free":
        return "free", None
    if kind == "active":
        return "paid", structured_expiry or dom_expiry
    if kind == "paid":
        return "paid", None
    return "unknown", None


_LISTING_SNAPSHOT_SCRIPT = r"""
({targetEpisodeId}) => {
  const text = el => el ? (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim() : '';
  const classes = el => el ? Array.from(el.classList) : [];
  const attrs = el => el ? Object.fromEntries(Array.from(el.attributes)
    .filter(a => a.name.startsWith('data-') || a.name.startsWith('aria-') ||
      ['id', 'role', 'title'].includes(a.name)).map(a => [a.name, a.value])) : {};
  const visible = el => {
    if (!el) return false;
    const style = getComputedStyle(el), rect = el.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
  };
  const episodeId = href => {
    if (!href) return null;
    try {
      const parsed = new URL(href, location.href), match = parsed.pathname.match(/^\/episode\/([0-9]+)\/?$/);
      return ['shonenjumpplus.com', 'www.shonenjumpplus.com'].includes(parsed.hostname.toLowerCase())
        ? (match ? match[1] : null) : null;
    } catch (_) { return null; }
  };
  const selectorFor = el => {
    if (!el) return null;
    if (el.id) return '#' + CSS.escape(el.id);
    const parts = [], stable = c => /episode|pagination|series|readable|range|tab/i.test(c);
    let node = el;
    while (node && node.nodeType === 1 && node !== document.body) {
      let part = node.tagName.toLowerCase();
      const cls = Array.from(node.classList).find(stable);
      if (cls) part += '.' + CSS.escape(cls);
      const parent = node.parentElement;
      if (parent) {
        const same = Array.from(parent.children).filter(x => x.tagName === node.tagName);
        if (same.length > 1) part += ':nth-of-type(' + (same.indexOf(node) + 1) + ')';
      }
      parts.unshift(part);
      const candidate = parts.join(' > ');
      try { if (document.querySelectorAll(candidate).length === 1) return candidate; } catch (_) {}
      node = parent;
    }
    return parts.join(' > ');
  };
  const sectionCandidates = Array.from(document.querySelectorAll('section.series-information.type-episode'));
  const section = sectionCandidates.length === 1 ? sectionCandidates[0] : null;
  const tab = section ? Array.from(section.querySelectorAll('[role="tab"]')).find(el =>
    el.getAttribute('data-key') === 'episode' || text(el).includes('話の一覧')) : null;
  const panelId = tab ? tab.getAttribute('aria-controls') : null;
  const panel = tab ? (panelId ? document.getElementById(panelId) : null) : null;
  const pagination = section ? section.querySelector('.js-readable-products-pagination') : null;
  const direct = pagination ? (pagination.querySelector('#pagination-top') || pagination) : null;
  const scope = panel || direct;
  const lists = scope ? Array.from(scope.querySelectorAll('ul')).filter(ul =>
    Array.from(ul.classList).some(c => /series-episode-list/i.test(c)) ||
    Array.from(ul.querySelectorAll('a[href]')).some(a => episodeId(a.href))) : [];
  const list = lists.length === 1 ? lists[0] : null;
  const rows = list ? Array.from(list.children).filter(li => {
    const hasEpisode = Array.from(li.querySelectorAll('a[href]')).some(a => episodeId(a.href));
    return hasEpisode || Array.from(li.classList).some(c => c.includes('current-readable-product'));
  }).map((row, index) => {
    const links = Array.from(row.querySelectorAll('a[href]'));
    const link = links.find(a => episodeId(a.href));
    const isCurrent = Array.from(row.classList).some(c => c.includes('current-readable-product'));
    const rowText = text(row);
    const date = rowText.match(/(?:\d{4}[年\/]\s*\d{1,2}[月\/]\s*\d{1,2}日?|\d{4}-\d{1,2}-\d{1,2})/);
    const titleElement = row.querySelector('[class*="series-episode-list-title--"],h3,h4');
    const titleValue = text(titleElement);
    const accessElements = Array.from(row.querySelectorAll('*')).filter(el => {
      const value = (classes(el).join(' ') + ' ' + Array.from(el.attributes).map(a => a.value).join(' ') +
        ' ' + (!el.children.length ? text(el) : '')).toLowerCase();
      return /series-episode-list-is-free|series-episode-list-price|rental|price|point|free|paid|lock|ticket|無料|ポイント|レンタル|購入|読める|読み放題|閲覧|残り|期限|公開/.test(value);
    }).filter(visible);
    return {
      index, href: link ? link.href : null, is_current: isCurrent,
      episode_id: link ? episodeId(link.href) : (isCurrent ? targetEpisodeId : null),
      title_text: titleValue || null, published_text: date ? date[0] : null,
      access_text: Array.from(new Set(accessElements.map(text).filter(Boolean))),
      access_title: (row.querySelector('[class*="series-episode-list-price"]') || {}).getAttribute?.('title') || null,
      access_class: Array.from(new Set(accessElements.flatMap(classes))),
    };
  }) : [];
  const controls = scope ? Array.from(scope.querySelectorAll('button,a,[role="button"],[role="tab"]')).map((el, index) => {
    const label = text(el), href = el.href || null;
    return {index, tag: el.tagName.toLowerCase(), href, text: label, visible: visible(el),
      disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
      selected: el.getAttribute('aria-selected') || el.getAttribute('data-selected') || null,
      current: el.getAttribute('aria-current') || null, selector: selectorFor(el),
      is_episode_link: !!episodeId(href),
      is_more: label.includes('もっと見る'),
      is_range: /^\s*\d+\s*[-–—〜～]\s*\d+\s*$/.test(label)};
  }).filter(x => x.visible || x.text) : [];
  const seriesIds = new Set();
  const addSeries = value => { if (value) seriesIds.add(String(value)); };
  for (const root of [document.documentElement, document.body]) {
    if (!root) continue;
    addSeries(root.getAttribute('data-giga_series'));
    try { const data = JSON.parse(root.getAttribute('data-gtm-data-layer') || '{}'); addSeries(data.series_id); addSeries(data.series?.series_id); addSeries(data.episode?.series_id); } catch (_) {}
  }
  document.querySelectorAll('[data-giga_series]').forEach(el => addSeries(el.getAttribute('data-giga_series')));
  const workTitle = section ? text(section.querySelector('h1.series-header-title,[class*="series-header-title"]')) : '';
  const author = section ? text(section.querySelector('h2.series-header-author,[class*="series-header-author"]')) : '';
  return {
    url: location.href,
    scope: scope ? {variant: tab ? 'role-tabpanel' : 'direct-pagination', tag: scope.tagName.toLowerCase(), id: scope.id || null} : null,
    series_ids: Array.from(seriesIds),
    work: {title: workTitle || null, author: author || null},
    listing_count: lists.length,
    episodes: rows,
    range_controls: controls.filter(x => x.is_range && !x.is_episode_link),
    more_controls: controls.filter(x => x.is_more && !x.is_episode_link),
  };
}
"""
