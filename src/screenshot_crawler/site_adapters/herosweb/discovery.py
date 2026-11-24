"""Evidence-backed, fully buffered HERO'S WEB episode-list Discovery."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from screenshot_crawler.catalog.service import JST
from screenshot_crawler.core.access_guard import AccessGuard
from screenshot_crawler.core.errors import AccessStopError
from screenshot_crawler.discovery.base import DiscoveryAdapter
from screenshot_crawler.discovery.listing import ListingPreview
from screenshot_crawler.discovery.listing_replay import (
    PreparedListingReplay,
    record_listing_preview,
    take_exclusion_replay,
)
from screenshot_crawler.discovery.models import (
    DiscoveredItem,
    DiscoveredRecord,
    DiscoveredSource,
    DiscoveryMode,
    DiscoverySourceSnapshot,
    IncrementalStopDecision,
)
from screenshot_crawler.discovery.service import DiscoveryIncompleteError
from screenshot_crawler.registration.models import UrlResolution, resolved_url
from screenshot_crawler.site_adapters.herosweb.access import herosweb_access_profile
from screenshot_crawler.watchlist.models import DiscoveryScope, WatchlistTarget

ALLOWED_HOSTS = frozenset({"heros-web.com"})
WORK_PATH = re.compile(r"^/series/(?P<work_id>[0-9a-f]{13})/?$")
RANGE_PATH = re.compile(
    r"^/series/(?P<work_id>[0-9a-f]{13})/(?P<page_number>[1-9][0-9]*)/?$"
)
EPISODE_PATH = re.compile(r"^/episodes/(?P<episode_id>[0-9a-f]{13})/?$")
RANGE_LABEL = re.compile(r"^(?P<start>[1-9][0-9]*)-(?P<end>[1-9][0-9]*)$")
POSITIVE_PRICE = re.compile(r"^[1-9][0-9]{0,15}$")
RENTAL_LABEL = re.compile(r"^レンタル中 閲覧期限 (?P<days>[0-9]{1,2})日\+(?P<hours>[0-9]{1,2})時間$")
DATE_FORMAT = "%Y/%m/%d"

WORK_SELECTOR = ".series-h"
MAIN_SELECTOR = ".series-eplist-main"
LIST_SELECTOR = ".series-eplist-main .series-eplist-default"
RANGE_SELECTOR = ".series-sort a.series-sort-link"
ROW_SELECTOR = ".series-eplist-item"
PAGE_SIZE = 30
MAX_RANGE_PAGES = 100
MAX_LISTING_ROWS = PAGE_SIZE * MAX_RANGE_PAGES
RANGE_PACING_MS = 3_200
STABILITY_INTERVAL_MS = 250
NAVIGATION_TIMEOUT_MS = 20_000
DOM_TIMEOUT_MS = 12_000
OBSERVATION_TIMEOUT_SECONDS = 15
GUARD_CLEANUP_TIMEOUT_SECONDS = 5
AUTH_RESPONSE_TIMEOUT_SECONDS = 1.0
AUTH_HEADER_SETTLE_SECONDS = 5.0
MAX_AUTH_RESPONSE_BYTES = 256_000
LATEST_LABEL = "最新話から"


def _work_title(text: str) -> str:
    return text.strip().removeprefix("HERO'S Web（ヒーローズウェブ）公式サイトの").strip()


@dataclass(frozen=True, slots=True)
class HeroswebRange:
    page_number: int
    start_position: int
    end_position: int
    url: str
    path: str

    @property
    def label(self) -> str:
        return f"{self.start_position}-{self.end_position}"


@dataclass(frozen=True, slots=True)
class _ListingRow:
    episode_id: str
    title: str
    published_at: datetime | None
    access_mode: str
    global_position: int
    rental_remaining: timedelta | None = None


class _CurrentDocumentAuth:
    """Reduce the site's naturally emitted session response to one boolean."""

    def __init__(self, page: Page) -> None:
        self.page = page
        self.expected_url: str | None = None
        self.session_user_present: bool | None = None
        self._generation = 0
        self._response_seen = asyncio.Event()
        self._tasks: set[asyncio.Task[None]] = set()
        self._request_bindings: dict[int, tuple[object, int, str]] = {}
        page.on("request", self._on_request)
        page.on("response", self._on_response)

    def begin_document(self, expected_url: str) -> None:
        self._generation += 1
        self.expected_url = expected_url
        self.session_user_present = None
        self._response_seen = asyncio.Event()
        self._request_bindings.clear()
        for task in tuple(self._tasks):
            if not task.done():
                task.cancel()

    def _on_request(self, request) -> None:
        expected_url = self.expected_url
        if expected_url is None:
            return
        try:
            parsed = urlsplit(request.url)
            frame_url = request.frame.url
        except (PlaywrightError, ValueError):
            return
        if (
            parsed.scheme == "https"
            and parsed.hostname == "heros-web.com"
            and parsed.path == "/api/auth/session"
            and request.method.upper() == "GET"
            and frame_url == expected_url
        ):
            self._request_bindings[id(request)] = (request, self._generation, expected_url)

    def _on_response(self, response) -> None:
        request = response.request
        try:
            parsed = urlsplit(response.url)
        except (PlaywrightError, ValueError):
            return
        binding = self._request_bindings.pop(id(request), None)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "heros-web.com"
            or parsed.path != "/api/auth/session"
            or request.method.upper() != "GET"
            or binding is None
            or binding[0] is not request
            or binding[1] != self._generation
            or binding[2] != self.expected_url
        ):
            return
        generation, expected_url = binding[1], binding[2]
        task = asyncio.create_task(self._read_session_presence(response, generation, expected_url))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _read_session_presence(self, response, generation: int, expected_url: str) -> None:
        present: bool | None = None
        try:
            if response.status == 200:
                length = response.headers.get("content-length")
                if length is None or int(length) <= MAX_AUTH_RESPONSE_BYTES:
                    body = await asyncio.wait_for(response.body(), timeout=2)
                    if len(body) <= MAX_AUTH_RESPONSE_BYTES:
                        payload = json.loads(body)
                        if isinstance(payload, dict):
                            user = payload.get("user")
                            data = payload.get("data")
                            if user is None and isinstance(data, dict):
                                user = data.get("user")
                            present = user is not None
        except (PlaywrightError, TimeoutError, ValueError, TypeError, json.JSONDecodeError):
            present = None
        if generation == self._generation and expected_url == self.expected_url:
            self.session_user_present = present
            self._response_seen.set()

    async def wait_for_current_response(self) -> None:
        try:
            await asyncio.wait_for(
                self._response_seen.wait(), timeout=AUTH_RESPONSE_TIMEOUT_SECONDS
            )
        except TimeoutError:
            return
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    async def close(self) -> None:
        self.page.remove_listener("request", self._on_request)
        self.page.remove_listener("response", self._on_response)
        tasks = tuple(self._tasks)
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()


def _strict_match(url: str, pattern: re.Pattern[str]) -> re.Match[str] | None:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.lower() != "https"
        or (parsed.hostname or "").lower() not in ALLOWED_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.query
        or parsed.fragment
        or "?" in url
        or "#" in url
    ):
        return None
    return pattern.fullmatch(parsed.path)


def parse_herosweb_work_url(url: str) -> str | None:
    match = _strict_match(url, WORK_PATH)
    return match.group("work_id") if match else None


def parse_herosweb_episode_url(url: str) -> str | None:
    match = _strict_match(url, EPISODE_PATH)
    return match.group("episode_id") if match else None


def canonical_herosweb_work_url(url: str) -> str:
    work_id = parse_herosweb_work_url(url)
    if work_id is None:
        raise ValueError("Not a supported HERO'S WEB Work URL")
    return f"https://heros-web.com/series/{work_id}"


def _parse_range_route(url: str, *, work_id: str) -> tuple[int, str] | None:
    match = _strict_match(url, RANGE_PATH)
    if match is None or match.group("work_id") != work_id:
        return None
    return int(match.group("page_number")), urlsplit(url).path


def parse_range_map(
    entries: Sequence[dict[str, object]], *, work_id: str
) -> tuple[HeroswebRange, ...]:
    """Validate a complete, contiguous set of visible numeric range controls."""

    if not entries or len(entries) > MAX_RANGE_PAGES + 1:
        raise DiscoveryIncompleteError("HERO'S WEB range controls are missing or excessive")
    latest_count = 0
    numeric: list[tuple[int, int, int, str, str, str]] = []
    for entry in entries:
        label, href = entry.get("label"), entry.get("href")
        classes = entry.get("class")
        if not isinstance(label, str) or not isinstance(href, str) or not isinstance(classes, str):
            raise DiscoveryIncompleteError("HERO'S WEB range control is incomplete")
        if label == LATEST_LABEL:
            expected = f"https://heros-web.com/series/{work_id}/new"
            if href != expected:
                raise DiscoveryIncompleteError("HERO'S WEB latest control has an unexpected route")
            latest_count += 1
            continue
        if label == "...":
            raise DiscoveryIncompleteError("HERO'S WEB range map is truncated by an ellipsis")
        match = RANGE_LABEL.fullmatch(label)
        if match is None:
            raise DiscoveryIncompleteError("HERO'S WEB range label is not numeric")
        route = _parse_range_route(href, work_id=work_id)
        alias_path = f"/series/{work_id}"
        if route is None and urlsplit(href).path == alias_path:
            # The current range link is rewritten to the Work URL on a range page.
            page_match = re.search(r"/series/" + re.escape(work_id) + r"/([1-9][0-9]*)/?$", href)
            if page_match and "mode-current" in classes:
                route = int(page_match.group(1)), f"/series/{work_id}/{page_match.group(1)}"
            else:
                # Temporarily retain the selected alias; its exact page is
                # checked against the current document in _validate_range_map.
                route = 0, alias_path
        numeric.append(
            (route[0] if route else 0, int(match["start"]), int(match["end"]), label, href, classes)
        )

    if latest_count != 1 or not numeric:
        raise DiscoveryIncompleteError("HERO'S WEB numeric range controls are incomplete")
    if len(numeric) > MAX_RANGE_PAGES:
        raise DiscoveryIncompleteError("HERO'S WEB range count exceeds its bound")
    ranges: list[HeroswebRange] = []
    expected_start = 1
    for index, (page_number, start, end, label, href, classes) in enumerate(numeric, start=1):
        if start != expected_start or end < start or label != f"{start}-{end}":
            raise DiscoveryIncompleteError("HERO'S WEB ranges are not contiguous and oldest-first")
        if end - start + 1 > PAGE_SIZE:
            raise DiscoveryIncompleteError("HERO'S WEB range exceeds the observed row limit")
        if index < len(numeric) and end - start + 1 != PAGE_SIZE:
            raise DiscoveryIncompleteError("HERO'S WEB nonfinal range is not full")
        expected_path = f"/series/{work_id}/{index}"
        expected_url = f"https://heros-web.com{expected_path}"
        if page_number not in (0, index):
            raise DiscoveryIncompleteError("HERO'S WEB range route does not match its label")
        if page_number == 0 and (href != f"https://heros-web.com/series/{work_id}" or "mode-current" not in classes):
            raise DiscoveryIncompleteError("HERO'S WEB selected range alias is not proven")
        if page_number != 0 and href != expected_url:
            raise DiscoveryIncompleteError("HERO'S WEB range route is not canonical")
        ranges.append(HeroswebRange(index, start, end, expected_url, expected_path))
        expected_start = end + 1
    if expected_start - 1 > MAX_LISTING_ROWS:
        raise DiscoveryIncompleteError("HERO'S WEB listing exceeds its row guard")
    return tuple(ranges)


def _validate_range_map(
    entries: Sequence[dict[str, object]],
    *,
    work_id: str,
    ranges: tuple[HeroswebRange, ...],
    selected: HeroswebRange,
) -> None:
    parsed = parse_range_map(entries, work_id=work_id)
    if len(parsed) != len(ranges) or [r.label for r in parsed] != [r.label for r in ranges]:
        raise DiscoveryIncompleteError("HERO'S WEB range map changed during traversal")
    # parse_range_map permits only the current selected alias. Require the
    # current page to match the range whose link was rewritten.
    alias_entries = [
        entry for entry in entries
        if entry.get("href") == f"https://heros-web.com/series/{work_id}"
    ]
    if alias_entries and (
        len(alias_entries) != 1
        or ranges[selected.page_number - 1].label != alias_entries[0].get("label")
        or "mode-current" not in str(alias_entries[0].get("class", ""))
    ):
        raise DiscoveryIncompleteError("HERO'S WEB current range alias is ambiguous")


def _classify_access(raw: dict[str, object], *, authenticated: bool = False) -> str:
    """Classify only exact access structures observed on HERO'S WEB."""

    if raw.get("accessCount") != 1:
        return "unknown"
    labels = raw.get("freeLabels")
    parents = raw.get("paidParents")
    items = raw.get("paidItems")
    quota_icons = raw.get("quotaIcons")
    access_text = raw.get("accessText")
    if (
        not isinstance(labels, list)
        or not isinstance(parents, list)
        or not isinstance(items, list)
        or not isinstance(quota_icons, list)
        or not isinstance(access_text, str)
    ):
        return "unknown"
    if _is_quota_badge(raw):
        return "quota"
    if _rental_remaining(raw, authenticated=authenticated) is not None:
        return "quota"
    if len(labels) == 1 and not parents and not items:
        label = labels[0]
        label_text = label.get("text") if isinstance(label, dict) else None
        if (
            not isinstance(label, dict)
            or label.get("modeFree") is not True
            or quota_icons
            or access_text != label_text
            or not _has_free_access_tree(raw, label_text)
        ):
            return "unknown"
        if label_text == "無料":
            return "free"
        if label_text == "今なら無料" and authenticated:
            return "free"
        # Anonymous or otherwise unproven current access stays unknown.
        return "unknown"
    if labels or quota_icons or len(parents) != 1 or len(items) != 1:
        return "unknown"
    item = items[0]
    if not isinstance(item, dict) or item.get("parentClass") != "series-eplist-item-access-paid":
        return "unknown"
    images = item.get("images")
    direct_text = item.get("directText")
    if not isinstance(images, list) or len(images) != 1 or not isinstance(direct_text, str):
        return "unknown"
    image = images[0]
    if not isinstance(image, dict) or image.get("origin") != "https://heros-web.com":
        return "unknown"
    if image.get("path") != "/images/icons/coin.svg":
        return "unknown"
    if POSITIVE_PRICE.fullmatch(direct_text) is None:
        return "unknown"
    if access_text != direct_text or not _has_paid_access_tree(raw, direct_text):
        return "unknown"
    return "paid"


def _access_node_base(
    node: object,
    *,
    tag: str,
    class_tokens: set[str],
    text: str,
    url: dict[str, str] | None = None,
    data_e2e: str = "",
    data_attributes: list[str] | None = None,
    alt: str = "",
) -> list[object] | None:
    if not isinstance(node, dict) or set(node) != {
        "tag", "classTokens", "text", "id", "role", "title", "ariaLabel",
        "dataE2e", "dataAttributes", "alt", "url", "children",
    }:
        return None
    if (
        node.get("tag") != tag
        or node.get("classTokens") != sorted(class_tokens)
        or node.get("text") != text
        or node.get("id") != ""
        or node.get("role") != ""
        or node.get("title") != ""
        or node.get("ariaLabel") != ""
        or node.get("dataE2e") != data_e2e
        or node.get("dataAttributes") != (data_attributes or [])
        or node.get("alt") != alt
        or node.get("url") != url
        or not isinstance(node.get("children"), list)
    ):
        return None
    return node["children"]


def _has_free_access_tree(raw: dict[str, object], label: str | None) -> bool:
    if not isinstance(label, str):
        return False
    marker_by_label = {"無料": "eliFreeBadge", "今なら無料": "eliMemFreeBadge"}
    marker = marker_by_label.get(label)
    if marker is None:
        return False
    children = raw.get("accessChildren")
    if not isinstance(children, list) or len(children) != 1:
        return False
    wrapper_children = _access_node_base(
        children[0], tag="DIV", class_tokens=set(), text=""
    )
    if not isinstance(wrapper_children, list) or len(wrapper_children) != 1:
        return False
    label_children = _access_node_base(
        wrapper_children[0],
        tag="SPAN",
        class_tokens={"mode-free", "series-eplist-item-access-text"},
        text=label,
        data_e2e=marker,
        data_attributes=["data-e2e"],
    )
    return label_children == []


def _rental_remaining(raw: dict[str, object], *, authenticated: bool) -> timedelta | None:
    """Recognize the authenticated rental tree, allowing one hour for rounding."""

    label = raw.get("accessText")
    if not authenticated or not isinstance(label, str):
        return None
    match = RENTAL_LABEL.fullmatch(label)
    if (
        match is None
        or raw.get("accessCount") != 1
        or raw.get("freeLabels") != [{"text": label, "modeFree": False}]
        or raw.get("paidParents") != []
        or raw.get("paidItems") != []
        or raw.get("quotaIcons") != []
    ):
        return None
    days, hours = int(match["days"]), int(match["hours"])
    duration = timedelta(days=days, hours=hours)
    if hours > 23 or duration > timedelta(days=15):
        return None
    children = raw.get("accessChildren")
    if not isinstance(children, list) or len(children) != 1:
        return None
    wrapper = _access_node_base(children[0], tag="DIV", class_tokens=set(), text="")
    if not isinstance(wrapper, list) or len(wrapper) != 1:
        return None
    breaks = _access_node_base(
        wrapper[0], tag="SPAN", class_tokens={"series-eplist-item-access-text"},
        text=label, data_e2e="eliRentStat", data_attributes=["data-e2e"],
    )
    if (
        not isinstance(breaks, list)
        or len(breaks) != 2
        or any(_access_node_base(node, tag="BR", class_tokens=set(), text="") != []
               for node in breaks)
    ):
        return None
    return max(timedelta(0), duration - timedelta(hours=1))


def _matching_mirror_rows(
    owner: list[dict[str, object]], mirror: list[dict[str, object]], *, authenticated: bool,
) -> bool:
    if len(owner) != len(mirror):
        return False
    access_fields = {
        "accessCount", "accessText", "accessChildren", "freeLabels",
        "paidParents", "paidItems", "quotaIcons",
    }
    for current, hidden in zip(owner, mirror, strict=True):
        if current == hidden:
            continue
        # The observed hidden public list retains quota icons for rented rows.
        # Identity, ordering and all non-access metadata must still match exactly.
        if (
            _rental_remaining(current, authenticated=authenticated) is None
            or not _is_quota_badge(hidden)
            or {k: v for k, v in current.items() if k not in access_fields}
            != {k: v for k, v in hidden.items() if k not in access_fields}
        ):
            return False
    return True


def _has_quota_access_tree(raw: dict[str, object]) -> bool:
    children = raw.get("accessChildren")
    if not isinstance(children, list) or len(children) != 1:
        return False
    wrapper_children = _access_node_base(
        children[0], tag="DIV", class_tokens=set(), text=""
    )
    if not isinstance(wrapper_children, list) or len(wrapper_children) != 2:
        return False
    markers = ("eliWfIcon", "eliIfIcon")
    observed: list[str] = []
    for node in wrapper_children:
        if not isinstance(node, dict):
            return False
        marker = node.get("dataE2e")
        classes = node.get("classTokens")
        allowed_classes = {
            ("series-eplist-item-access-icon",),
            ("mode-disabled", "series-eplist-item-access-icon"),
        }
        if marker not in markers or not isinstance(classes, list) or tuple(classes) not in allowed_classes:
            return False
        path_children = _access_node_base(
            node,
            tag="SVG",
            class_tokens=set(classes),
            text="",
            data_e2e=marker,
            data_attributes=["data-e2e"],
        )
        if not isinstance(path_children, list) or not path_children:
            return False
        for path in path_children:
            if _access_node_base(path, tag="PATH", class_tokens=set(), text="") != []:
                return False
        observed.append(marker)
    return set(observed) == set(markers) and len(observed) == len(set(observed))


def _has_paid_access_tree(raw: dict[str, object], price: str) -> bool:
    children = raw.get("accessChildren")
    if not isinstance(children, list) or len(children) != 1:
        return False
    wrapper_children = _access_node_base(
        children[0], tag="DIV", class_tokens=set(), text=""
    )
    if not isinstance(wrapper_children, list) or len(wrapper_children) != 1:
        return False
    paid_children = _access_node_base(
        wrapper_children[0],
        tag="DIV",
        class_tokens={"series-eplist-item-access-paid"},
        text="",
    )
    if not isinstance(paid_children, list) or len(paid_children) != 1:
        return False
    item_children = _access_node_base(
        paid_children[0],
        tag="SPAN",
        class_tokens={"series-eplist-item-access-paid-item"},
        text=price,
        data_e2e="eliPrice",
        data_attributes=["data-e2e"],
    )
    if not isinstance(item_children, list) or len(item_children) != 1:
        return False
    return _access_node_base(
        item_children[0],
        tag="IMG",
        class_tokens=set(),
        text="",
        alt="コイン",
        data_e2e="eliCoinIcon",
        data_attributes=["data-e2e", "data-nimg"],
        url={"origin": "https://heros-web.com", "path": "/images/icons/coin.svg"},
    ) == []


def _is_quota_badge(raw: dict[str, object]) -> bool:
    """Require the exact observed pair of ticket-badge SVG identities."""

    if raw.get("accessCount") != 1 or raw.get("accessText") != "":
        return False
    if raw.get("freeLabels") or raw.get("paidParents") or raw.get("paidItems"):
        return False
    icons = raw.get("quotaIcons")
    if not isinstance(icons, list) or len(icons) != 2:
        return False
    expected = {"eliWfIcon", "eliIfIcon"}
    observed: list[str] = []
    for icon in icons:
        if not isinstance(icon, dict):
            return False
        classes = icon.get("class")
        marker = icon.get("dataE2e")
        if (
            not isinstance(classes, str)
            or "series-eplist-item-access-icon" not in classes.split()
            or marker not in expected
        ):
            return False
        observed.append(marker)
    return (
        set(observed) == expected
        and len(observed) == len(set(observed))
        and _has_quota_access_tree(raw)
    )


class _HeroswebRequestGuard:
    """Block state changes and any main-frame navigation outside the scan."""

    def __init__(self, page: Page) -> None:
        self.page = page
        self.expected_navigation_url: str | None = None
        self.navigation_violation: str | None = None
        self.main_frame_navigation_urls: list[str] = []
        self.last_main_frame_response_status: int | None = None
        self.main_frame_error_category: str | None = None

    def allow_navigation(self, expected_url: str) -> None:
        self.expected_navigation_url = expected_url

    async def __call__(self, route) -> None:
        request = route.request
        method = request.method.upper()
        try:
            parsed = urlsplit(request.url)
        except ValueError:
            await route.abort()
            return
        if parsed.hostname == "heros-web.com" and method not in {"GET", "HEAD"}:
            await route.abort()
            return
        if request.is_navigation_request():
            try:
                is_main_frame = request.frame == self.page.main_frame
            except PlaywrightError:
                await route.abort()
                return
            if is_main_frame and (
                method not in {"GET", "HEAD"}
                or self.expected_navigation_url is None
                or request.url != self.expected_navigation_url
            ):
                self.navigation_violation = (
                    f"{method} {(parsed.hostname or '').lower()}{parsed.path}"
                )
                self.main_frame_error_category = "unexpected_navigation"
                await route.abort()
                return
            if is_main_frame and (
                self.expected_navigation_url is not None
                and request.url == self.expected_navigation_url
            ):
                self.main_frame_navigation_urls.append(request.url)
                response = None
                try:
                    response = await _fetch_main_document_response_without_redirect(route)
                    if response is None:
                        return
                    status = int(response.status)
                    self.last_main_frame_response_status = status
                    if 300 <= status < 400 and status != 304:
                        self.main_frame_error_category = "http_redirect"
                        self.navigation_violation = (
                            f"GET {(parsed.hostname or '').lower()}{parsed.path} redirect {status}"
                        )
                        await route.abort()
                    else:
                        await route.fulfill(response=response)
                except Exception as exc:  # noqa: BLE001 - fail closed without exposing call-log text
                    self.main_frame_error_category = _safe_route_error_category(exc)
                    detail = (
                        "document fetch timed out"
                        if self.main_frame_error_category == "timeout"
                        else "document fetch failed"
                    )
                    self.navigation_violation = (
                        f"GET {(parsed.hostname or '').lower()}{parsed.path} {detail}"
                    )
                    await route.abort()
                finally:
                    if response is not None:
                        try:
                            await response.dispose()
                        except PlaywrightError:
                            self.navigation_violation = (
                                f"GET {(parsed.hostname or '').lower()}{parsed.path} document cleanup failed"
                            )
                return
        await route.fallback()

    def require_navigation(self, expected_url: str, prior_count: int | None = None) -> None:
        if (
            not self.main_frame_navigation_urls
            or self.main_frame_navigation_urls[-1] != expected_url
            or (
                prior_count is not None
                and len(self.main_frame_navigation_urls) != prior_count + 1
            )
        ):
            raise DiscoveryIncompleteError(
                "HERO'S WEB expected document did not pass through the guarded main-frame route"
            )

    def raise_if_failed(self) -> None:
        if self.navigation_violation is not None:
            raise DiscoveryIncompleteError(
                "HERO'S WEB blocked an unapproved or redirected main-frame navigation"
            )


async def _fetch_main_document_response_without_redirect(route):
    """Fetch one exact Work document without following an HTTP redirect."""

    return await route.fetch(
        max_redirects=0,
        max_retries=0,
        timeout=NAVIGATION_TIMEOUT_MS,
    )


def _safe_route_error_category(error: BaseException) -> str:
    """Classify route transport errors without retaining their call-log text."""

    message = str(error).lower()
    if (
        isinstance(error, TimeoutError)
        or "timeout" in message
        or "timed out" in message
        or "etimedout" in message
    ):
        return "timeout"
    if any(token in message for token in ("eacces", "eperm", "permission denied")):
        return "permission_denied"
    if "enetunreach" in message or "network is unreachable" in message:
        return "network_unreachable"
    if "econnrefused" in message or "connection refused" in message:
        return "connection_refused"
    if "econnreset" in message or "connection reset" in message:
        return "connection_reset"
    if any(token in message for token in ("dns", "name_not_resolved", "name resolution")):
        return "dns"
    if any(token in message for token in ("tls", "ssl", "certificate")):
        return "tls"
    return "other"


async def _assert_no_service_worker_controller(page: Page) -> None:
    try:
        state = await asyncio.wait_for(
            page.evaluate(
                """() => ({
                  supported: 'serviceWorker' in navigator,
                  controlled: 'serviceWorker' in navigator
                    ? navigator.serviceWorker.controller !== null
                    : false
                })"""
            ),
            timeout=5.0,
        )
    except (PlaywrightError, TimeoutError) as exc:
        raise DiscoveryIncompleteError(
            "HERO'S WEB service-worker route state could not be verified"
        ) from exc
    if not isinstance(state, dict) or state.get("controlled") is not False:
        raise DiscoveryIncompleteError(
            "HERO'S WEB service-worker-controlled page is not supported"
        )


async def _current_document_is_authenticated(
    page: Page,
    *,
    expected_url: str,
    auth: _CurrentDocumentAuth,
    guard: AccessGuard,
) -> bool:
    await auth.wait_for_current_response()
    await _guard_checkpoint(guard, page)
    if (
        page.url != expected_url
        or auth.expected_url != expected_url
        or auth.session_user_present is not True
    ):
        return False
    deadline = asyncio.get_running_loop().time() + AUTH_HEADER_SETTLE_SECONDS
    previous: dict[str, object] | None = None
    while asyncio.get_running_loop().time() < deadline:
        await _guard_checkpoint(guard, page)
        if page.url != expected_url or auth.expected_url != expected_url:
            return False
        try:
            current = await asyncio.wait_for(
                page.evaluate(_auth_header_script()), OBSERVATION_TIMEOUT_SECONDS
            )
        except (PlaywrightError, TimeoutError):
            await _guard_checkpoint(guard, page)
            return False
        if (
            current == previous
            and _positive_auth_header(current)
            and auth.session_user_present is True
        ):
            return True
        previous = current if isinstance(current, dict) else None
        await page.wait_for_timeout(
            min(
                STABILITY_INTERVAL_MS,
                max(
                    1,
                    int(
                        (deadline - asyncio.get_running_loop().time()) * 1_000
                    ),
                ),
            )
        )
    await _guard_checkpoint(guard, page)
    return False


def _positive_auth_header(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    account_items = value.get("accountMenuItems")
    return (
        value.get("logout") is True
        and value.get("userMenu") is True
        and isinstance(account_items, int)
        and account_items > 0
        and value.get("login") is False
        and value.get("signup") is False
    )


def _auth_header_script() -> str:
    return r"""() => {
      const controls = [...document.querySelectorAll(
        'header a, header button, header [role="button"], nav a, nav button, nav [role="button"]'
      )];
      const text = node => (node.innerText || '').replace(/\s+/g, ' ').trim();
      const path = node => {
        try { return new URL(node.getAttribute('href') || '', location.href).pathname; }
        catch { return ''; }
      };
      return {
        logout: controls.some(node => text(node).includes('ログアウト') || /logout|signout/i.test(path(node))),
        userMenu: document.querySelectorAll('.h-main-nav-link.mode-user').length === 1,
        accountMenuItems: document.querySelectorAll('.h-usermenu-vnav-link').length,
        login: controls.some(node => path(node) === '/auth/signin' || text(node).includes('ログイン')),
        signup: controls.some(node => path(node) === '/auth/signup' || text(node).includes('無料登録'))
      };
    }"""


def _snapshot_script() -> str:
    return r"""() => {
      const text = node => (node?.innerText || '').replace(/\s+/g, ' ').trim();
      const classes = node => (node?.getAttribute('class') || '').split(/\s+/).filter(Boolean).sort();
      const mains = [...document.querySelectorAll('.series-eplist-main')];
      const documentRoots = [...document.querySelectorAll('.series-eplist-default')];
      const main = mains.length === 1 ? mains[0] : null;
      const roots = main ? [...main.querySelectorAll('.series-eplist-default')] : [];
      const canonicals = [...document.querySelectorAll('link[rel="canonical"]')].map(node => node.href);
      const titles = [...document.querySelectorAll('h1')].map(text).filter(Boolean);
      const rangeContainers = [...document.querySelectorAll('.series-sort')];
      const rangeLinks = [...document.querySelectorAll('.series-sort a.series-sort-link')].map(node => ({
        label: text(node), href: node.href, class: node.getAttribute('class') || ''
      }));
      const safeUrl = raw => {
        if (!raw) return null;
        try {
          const url = new URL(raw, location.href);
          return {origin: url.origin, path: url.pathname};
        } catch { return {origin: 'invalid', path: 'invalid'}; }
      };
      const readAccessNode = node => ({
        tag: node.tagName.toUpperCase(),
        classTokens: classes(node),
        text: [...node.childNodes].filter(child => child.nodeType === Node.TEXT_NODE)
          .map(child => child.nodeValue || '').join(' ').replace(/\s+/g, ' ').trim(),
        id: node.getAttribute('id') || '',
        role: node.getAttribute('role') || '',
        title: node.getAttribute('title') || '',
        ariaLabel: node.getAttribute('aria-label') || '',
        dataE2e: node.getAttribute('data-e2e') || '',
        dataAttributes: [...node.attributes].map(attr => attr.name.toLowerCase())
          .filter(name => name.startsWith('data-')).sort(),
        alt: node.getAttribute('alt') || '',
        url: node.tagName === 'A' ? safeUrl(node.getAttribute('href')) :
          (node.tagName === 'IMG' ? safeUrl(node.getAttribute('src')) : null),
        children: [...node.children].map(readAccessNode)
      });
      const readRow = row => {
        const links = [...row.querySelectorAll('a.series-eplist-item-link')];
        const titleNodes = [...row.querySelectorAll('.series-eplist-item-h-text')];
        const dateNodes = [...row.querySelectorAll('.series-eplist-item-meta-date')];
        const accessNodes = [...row.querySelectorAll('.series-eplist-item-access')];
        const access = accessNodes.length === 1 ? accessNodes[0] : null;
        const freeLabels = access ? [...access.querySelectorAll('.series-eplist-item-access-text')].map(node => ({
          text: text(node), modeFree: node.classList.contains('mode-free')
        })) : [];
        const paidParents = access ? [...access.querySelectorAll('.series-eplist-item-access-paid')].map(node =>
          node.getAttribute('class') || '') : [];
        const paidItems = access ? [...access.querySelectorAll('.series-eplist-item-access-paid-item')].map(node => ({
          parentClass: node.parentElement?.getAttribute('class') || '',
          directText: [...node.childNodes].filter(child => child.nodeType === Node.TEXT_NODE)
            .map(child => child.nodeValue || '').join(' ').replace(/\s+/g, ' ').trim(),
          images: [...node.querySelectorAll('img')].map(img => {
            const url = new URL(img.getAttribute('src') || '', location.href);
            return { origin: url.origin, path: url.pathname };
          })
        })) : [];
        const quotaIcons = access ? [...access.querySelectorAll('svg')].map(node => ({
          class: node.getAttribute('class') || '',
          dataE2e: node.getAttribute('data-e2e') || '',
          title: node.getAttribute('title') || '',
          ariaLabel: node.getAttribute('aria-label') || '',
          role: node.getAttribute('role') || ''
        })) : [];
        return {
          linkCount: links.length, href: links.length === 1 ? links[0].href : null,
          titleCount: titleNodes.length, title: titleNodes.length === 1 ? text(titleNodes[0]) : null,
          dateCount: dateNodes.length, date: dateNodes.length === 1 ? text(dateNodes[0]) : null,
          accessCount: accessNodes.length,
          accessText: access ? text(access) : '',
          accessChildren: access ? [...access.children].map(readAccessNode) : [],
          freeLabels, paidParents, paidItems, quotaIcons
        };
      };
      const allRows = main ? [...main.querySelectorAll('.series-eplist-item')] : [];
      const rootRows = roots.flatMap(root => [...root.querySelectorAll('.series-eplist-item')]);
      const rootSnapshots = roots.map(root => {
        const directRows = [...root.children].filter(node => node.matches('.series-eplist-item'));
        const nestedRows = [...root.querySelectorAll('.series-eplist-item')];
        const rect = root.getBoundingClientRect();
        const styleChain = [];
        const parentChain = [];
        for (let node = root; node; node = node.parentElement) {
          const style = getComputedStyle(node);
          styleChain.push({
            display: style.display, visibility: style.visibility,
            opacity: style.opacity
          });
          if (node !== root) parentChain.push({tag: node.tagName, classTokens: classes(node)});
          if (node === main || node.matches('.series-eplist-main')) break;
        }
        return {
          classTokens: classes(root),
          parentChain,
          insideMain: root.closest('.series-eplist-main') === main,
          hidden: root.hasAttribute('hidden'),
          inert: root.hasAttribute('inert'),
          ariaHidden: root.getAttribute('aria-hidden'),
          styleChain,
          width: rect.width,
          height: rect.height,
          directRowCount: directRows.length,
          nestedRowCount: nestedRows.length,
          rows: directRows.map(readRow)
        };
      });
      return {
        canonicalCount: canonicals.length, canonicals, titles,
        mainCount: mains.length, rootCount: roots.length, documentRootCount: documentRoots.length,
        rangeContainerCount: rangeContainers.length, rangeLinks,
        allRowCount: allRows.length, rootRowCount: rootRows.length,
        roots: rootSnapshots
      };
    }"""


async def _stable_snapshot(
    page: Page, guard: AccessGuard, *, expected_url: str
) -> dict[str, object]:
    deadline = asyncio.get_running_loop().time() + DOM_TIMEOUT_MS / 1_000
    try:
        await page.wait_for_function(
            r"""expectedUrl => {
              const canonicals = [...document.querySelectorAll('link[rel="canonical"]')];
              const mains = [...document.querySelectorAll('.series-eplist-main')];
              const ranges = [...document.querySelectorAll('.series-sort a.series-sort-link')];
              const roots = mains.length === 1 ? [...mains[0].querySelectorAll('.series-eplist-default')] : [];
              const main = mains.length === 1 ? mains[0] : null;
              const classes = node => (node.getAttribute('class') || '').split(/\s+/).filter(Boolean).sort();
              const ownerShape = root => {
                const parents = [];
                for (let node = root.parentElement; node; node = node.parentElement) {
                  parents.push(classes(node));
                  if (node === main) break;
                }
                const auth = [["mode-has-eps", "mode-user", "series-eplist"], ["series-eplist-main"]];
                const plain = [["series-eplist"], ["series-eplist-main"]];
                return JSON.stringify(parents) === JSON.stringify(auth) ||
                  JSON.stringify(parents) === JSON.stringify(plain);
              };
              const visible = root => {
                for (let node = root; node; node = node.parentElement) {
                  const style = getComputedStyle(node);
                  if (style.display === 'none' || style.visibility !== 'visible' || Number(style.opacity) <= 0) return false;
                  if (node === main) break;
                }
                return true;
              };
              const owners = roots.filter(root => {
                const rect = root.getBoundingClientRect();
                const direct = [...root.children].filter(node => node.matches('.series-eplist-item'));
                return rect.width > 0 && rect.height > 0 && ownerShape(root) && visible(root) &&
                  direct.length > 0 && root.querySelectorAll('.series-eplist-item').length === direct.length;
              });
              return location.href === expectedUrl && canonicals.length === 1 &&
                canonicals[0].href === expectedUrl && mains.length === 1 && roots.length > 0 &&
                ranges.length > 0 && owners.length === 1 && roots.every(root => {
                  const direct = [...root.children].filter(node => node.matches('.series-eplist-item'));
                  return direct.length > 0 && root.querySelectorAll('.series-eplist-item').length === direct.length;
                });
            }""",
            arg=expected_url,
            timeout=max(1, int((deadline - asyncio.get_running_loop().time()) * 1_000)),
        )
        previous: dict[str, object] | None = None
        while True:
            await _guard_checkpoint(guard, page)
            current = await asyncio.wait_for(
                page.evaluate(_snapshot_script()), OBSERVATION_TIMEOUT_SECONDS
            )
            if not isinstance(current, dict):
                raise DiscoveryIncompleteError(
                    "HERO'S WEB listing snapshot is not a structured object"
                )
            if previous is not None and current == previous:
                return current
            previous = current
            remaining_ms = int((deadline - asyncio.get_running_loop().time()) * 1_000)
            if remaining_ms <= 0:
                raise TimeoutError("HERO'S WEB listing did not stabilize before its deadline")
            await page.wait_for_timeout(min(STABILITY_INTERVAL_MS, remaining_ms))
    except (PlaywrightError, TimeoutError) as exc:
        raise DiscoveryIncompleteError("HERO'S WEB listing DOM did not settle") from exc


def _validate_snapshot(
    snapshot: dict[str, object],
    *,
    expected_url: str,
    work_id: str,
    first_position: int,
    authenticated: bool,
) -> tuple[str, list[_ListingRow]]:
    if (
        snapshot.get("canonicalCount") != 1
        or snapshot.get("canonicals") != [expected_url]
        or snapshot.get("mainCount") != 1
        or snapshot.get("rootCount") != snapshot.get("documentRootCount")
        or snapshot.get("rangeContainerCount") != 1
        or snapshot.get("allRowCount") != snapshot.get("rootRowCount")
    ):
        raise DiscoveryIncompleteError("HERO'S WEB canonical or listing scope is ambiguous")
    titles = snapshot.get("titles")
    roots = snapshot.get("roots")
    ranges = snapshot.get("rangeLinks")
    if (
        not isinstance(titles, list)
        or len(titles) != 1
        or not isinstance(titles[0], str)
        or not _work_title(titles[0])
        or not isinstance(roots, list)
        or not roots
        or not isinstance(ranges, list)
    ):
        raise DiscoveryIncompleteError("HERO'S WEB Work title, ranges or episode rows are missing")

    parsed_roots: list[tuple[dict[str, object], list[dict[str, object]], list[_ListingRow]]] = []
    for root in roots:
        if not isinstance(root, dict):
            raise DiscoveryIncompleteError("HERO'S WEB list root is not a structured observation")
        root_classes = root.get("classTokens")
        parent_chain = root.get("parentChain")
        style_chain = root.get("styleChain")
        raw_rows = root.get("rows")
        width, height = root.get("width"), root.get("height")
        if (
            not isinstance(root_classes, list)
            or "series-eplist-default" not in root_classes
            or root.get("insideMain") is not True
            or root.get("hidden") is not False
            or root.get("inert") is not False
            or root.get("ariaHidden") is not None
            or not isinstance(parent_chain, list)
            or not isinstance(style_chain, list)
            or not isinstance(raw_rows, list)
            or not raw_rows
            or root.get("directRowCount") != len(raw_rows)
            or root.get("nestedRowCount") != len(raw_rows)
            or not isinstance(width, (int, float))
            or not isinstance(height, (int, float))
        ):
            raise DiscoveryIncompleteError("HERO'S WEB list root is malformed or contains nested rows")
        parents = [item.get("classTokens") for item in parent_chain if isinstance(item, dict)]
        if len(parents) != len(parent_chain):
            raise DiscoveryIncompleteError("HERO'S WEB list root ancestry is malformed")
        parent_sets = [set(classes) if isinstance(classes, list) else set() for classes in parents]
        authenticated_owner = [
            {"mode-has-eps", "mode-user", "series-eplist"},
            {"series-eplist-main"},
        ]
        plain_wrapper = [{"series-eplist"}, {"series-eplist-main"}]
        if parent_sets not in (authenticated_owner, plain_wrapper):
            raise DiscoveryIncompleteError("HERO'S WEB list root ancestry is not an observed shape")
        is_positive = width > 0 and height > 0
        is_zero_area = width == 0 and height == 0
        if not is_positive and not is_zero_area:
            raise DiscoveryIncompleteError("HERO'S WEB list root has malformed zero-area geometry")
        parsed_rows = [
            HeroswebDiscoveryAdapter._parse_row(
                raw,
                first_position=first_position + offset,
                work_id=work_id,
                authenticated=authenticated,
            )
            for offset, raw in enumerate(raw_rows)
        ]
        parsed_roots.append((root, raw_rows, parsed_rows))

    positive_roots = [entry for entry in parsed_roots if entry[0]["width"] > 0 and entry[0]["height"] > 0]
    zero_roots = [entry for entry in parsed_roots if entry[0]["width"] == 0 and entry[0]["height"] == 0]
    if len(positive_roots) != 1 or len(zero_roots) > 1:
        raise DiscoveryIncompleteError("HERO'S WEB rendered listing owner is not unique")
    owner, owner_raw_rows, owner_rows = positive_roots[0]
    owner_parents = [item["classTokens"] for item in owner["parentChain"]]
    owner_is_authenticated_shape = owner_parents == [
        ["mode-has-eps", "mode-user", "series-eplist"],
        ["series-eplist-main"],
    ]
    owner_is_plain_shape = owner_parents == [["series-eplist"], ["series-eplist-main"]]
    if not owner_is_authenticated_shape and not owner_is_plain_shape:
        raise DiscoveryIncompleteError("HERO'S WEB listing owner ancestry changed")

    owner_styles = owner["styleChain"]
    if not isinstance(owner_styles, list) or not owner_styles or any(
        not isinstance(style, dict)
        or style.get("display") != "block"
        or style.get("visibility") != "visible"
        or str(style.get("opacity")) not in {"1", "1.0"}
        for style in owner_styles
    ):
        raise DiscoveryIncompleteError("HERO'S WEB listing owner is not stably CSS-visible")

    if zero_roots:
        mirror, mirror_raw_rows, _mirror_rows = zero_roots[0]
        mirror_parents = [item["classTokens"] for item in mirror["parentChain"]]
        mirror_styles = mirror["styleChain"]
        mirror_style_pattern = (
            isinstance(mirror_styles, list)
            and len(mirror_styles) == 3
            and [style.get("display") for style in mirror_styles if isinstance(style, dict)]
            == ["block", "none", "block"]
            and all(
                isinstance(style, dict)
                and style.get("visibility") == "visible"
                and str(style.get("opacity")) in {"1", "1.0"}
                for style in mirror_styles
            )
        )
        if (
            not owner_is_authenticated_shape
            or mirror_parents != [["series-eplist"], ["series-eplist-main"]]
            or not mirror_style_pattern
            or not _matching_mirror_rows(
                owner_raw_rows, mirror_raw_rows, authenticated=authenticated,
            )
        ):
            raise DiscoveryIncompleteError("HERO'S WEB zero-area listing mirror diverges from its owner")
    if len(parsed_roots) != len(positive_roots) + len(zero_roots):
        raise DiscoveryIncompleteError("HERO'S WEB has an unexpected list root")
    return _work_title(titles[0]), owner_rows


def _validate_work_header_snapshot(
    snapshot: object, *, expected_url: str, work_id: str
) -> tuple[str, tuple[HeroswebRange, ...]]:
    """Validate Work identity/ranges without treating the top preview as an inventory."""

    if not isinstance(snapshot, dict):
        raise DiscoveryIncompleteError("HERO'S WEB Work header is not a structured observation")
    canonical = snapshot.get("canonicals")
    titles = snapshot.get("titles")
    entries = snapshot.get("rangeLinks")
    if (
        snapshot.get("canonicalCount") != 1
        or canonical != [expected_url]
        or snapshot.get("mainCount") != 1
        or snapshot.get("rangeContainerCount") != 1
        or not isinstance(titles, list)
        or len(titles) != 1
        or not isinstance(titles[0], str)
        or not _work_title(titles[0])
        or not isinstance(entries, list)
    ):
        raise DiscoveryIncompleteError("HERO'S WEB Work identity or range list is ambiguous")
    return _work_title(titles[0]), parse_range_map(entries, work_id=work_id)


def _records_from_rows(
    rows: Sequence[_ListingRow], *, work_id: str, work_title: str, observed_at: datetime,
) -> list[DiscoveredRecord]:
    if not rows or len(rows) > MAX_LISTING_ROWS:
        raise DiscoveryIncompleteError("HERO'S WEB listing is empty or exceeds its row guard")
    ids = [row.episode_id for row in rows]
    positions = [row.global_position for row in rows]
    if len(ids) != len(set(ids)) or len(positions) != len(set(positions)):
        raise DiscoveryIncompleteError("HERO'S WEB listing repeats an episode or display position")
    oldest_first = [
        DiscoveredRecord(
            item=DiscoveredItem(
                canonical_title=work_title,
                kind="episode",
                order_key=f"{row.global_position:06d}",
                order_label=row.title,
            ),
            source=DiscoveredSource(
                external_id=f"{work_id}:{row.episode_id}",
                url=f"https://heros-web.com/episodes/{row.episode_id}",
                access_mode=row.access_mode,
                access_granted_until=(
                    observed_at + row.rental_remaining if row.rental_remaining else None
                ),
                access_granted_until_observed=row.access_mode in {"free", "quota", "paid"},
                published_at=row.published_at,
                available=True,
                global_display_position=row.global_position,
            ),
        )
        for row in rows
    ]
    return list(reversed(oldest_first))


def _apply_discovery_scope(
    records: list[DiscoveredRecord], *, scope: DiscoveryScope | None, work_id: str
) -> list[DiscoveredRecord]:
    if scope is None:
        return records
    if scope.from_url is None and scope.through_url is None:
        raise DiscoveryIncompleteError("HERO'S WEB bounded scope has no episode boundary")
    index_by_id = {record.source.external_id.partition(":")[2]: index for index, record in enumerate(records)}
    boundaries: dict[str, int] = {}
    for name, value in (("from", scope.from_url), ("through", scope.through_url)):
        if value is None:
            continue
        episode_id = parse_herosweb_episode_url(value)
        external_id = f"{work_id}:{episode_id}" if episode_id else ""
        if not external_id or not any(record.source.external_id == external_id for record in records):
            raise DiscoveryIncompleteError(f"HERO'S WEB bounded {name} URL is invalid or outside the Work")
        boundaries[name] = index_by_id[episode_id]
    start, end = boundaries.get("from", 0), boundaries.get("through", len(records) - 1)
    if start < 0 or end < start:
        raise DiscoveryIncompleteError("HERO'S WEB bounded boundaries are missing or reversed")
    return records[start : end + 1]


class HeroswebDiscoveryAdapter(DiscoveryAdapter):
    """Enumerate every declared numeric range, then yield only validated rows."""

    registration_hosts = ("heros-web.com",)
    supports_bounded_discovery = True
    supports_exclusion_only_scope = True
    supports_exclusion_replay = True
    allow_inferred_display_positions = False

    def __init__(self, *, range_pacing_ms: int = RANGE_PACING_MS) -> None:
        if isinstance(range_pacing_ms, bool) or not isinstance(range_pacing_ms, int) or range_pacing_ms < RANGE_PACING_MS:
            raise ValueError("HERO'S WEB range pacing cannot be shorter than its observed minimum")
        self.range_pacing_ms = range_pacing_ms

    def resolve_registration_url(self, url: str) -> UrlResolution:
        work_id = parse_herosweb_work_url(url)
        if work_id is None:
            return UrlResolution(
                input_url=url,
                blockers=("Use a canonical https://heros-web.com/series/<work-id> URL without query or fragment",),
            )
        canonical = f"https://heros-web.com/series/{work_id}"
        return resolved_url(url, canonical, f"herosweb-work:{work_id}")

    async def observe_registration_metadata(self, page, resolution):
        from screenshot_crawler.registration.observation import (
            ObservationUnavailable,
            observation_failure,
            observed_title,
            registration_document,
            require_canonical,
        )

        try:
            async with registration_document(page, resolution.discovery_url):
                await require_canonical(page, resolution.discovery_url)
                headings = await page.locator(".series-h h1").evaluate_all(
                    "els => els.map(e => (e.innerText || '').replace(/\\s+/g, ' ').trim()).filter(Boolean)"
                )
                if len(headings) != 1:
                    raise ObservationUnavailable("HERO'S WEB Work title is not unambiguous")
                return observed_title(resolution, _work_title(headings[0]), resolution.discovery_url)
        except ObservationUnavailable as exc:
            return observation_failure(resolution, exc)

    async def preview_complete_listing(self, page: Page, target: WatchlistTarget) -> ListingPreview:
        self._prepared_listing_replay = None
        preview, _records = await self._read_preview_records(page, target)
        return preview

    async def prepare_exclusion_preview(self, page: Page, target: WatchlistTarget) -> ListingPreview:
        self._prepared_listing_replay = None
        preview, records = await self._read_preview_records(page, target)
        self._prepared_listing_replay = PreparedListingReplay.create(page, target, preview, records)
        return preview

    async def _read_preview_records(self, page: Page, target: WatchlistTarget):
        records = await self._read_all_records(page, target)
        work_id = parse_herosweb_work_url(target.url)
        if work_id is None:
            raise DiscoveryIncompleteError("HERO'S WEB preview requires a canonical Work URL")
        return record_listing_preview(target, f"herosweb-work:{work_id}", records), records

    async def _read_all_records(self, page: Page, target: WatchlistTarget) -> list[DiscoveredRecord]:
        observed_at = datetime.now(JST)
        work_id = parse_herosweb_work_url(target.url)
        work_url = f"https://heros-web.com/series/{work_id}" if work_id else None
        if target.site != "herosweb" or work_url is None or target.url != work_url:
            raise DiscoveryIncompleteError("HERO'S WEB requires a strict canonical Work listing URL")

        guard = AccessGuard.from_profile(
            site="herosweb",
            profile=herosweb_access_profile(),
            stop_on_http_403=True,
            stop_on_http_429=True,
            stop_on_challenge=True,
            stop_on_captcha=True,
        )
        auth = _CurrentDocumentAuth(page)
        request_guard = _HeroswebRequestGuard(page)
        await page.route("**/*", request_guard)
        guard.start(page)
        try:
            title, ranges, _work_authenticated = await self._open_work(
                page, work_url, work_id, guard, auth, request_guard
            )
            rows: list[_ListingRow] = []
            seen_ids: set[str] = set()
            for episode_range in ranges:
                # Every numeric range is a full document load; SPA-retained rows
                # are not used as evidence for a complete listing.
                await page.wait_for_timeout(self.range_pacing_ms)
                await _assert_no_service_worker_controller(page)
                prior_navigation_count = len(request_guard.main_frame_navigation_urls)
                auth.begin_document(episode_range.url)
                request_guard.allow_navigation(episode_range.url)
                response = await page.goto(
                    episode_range.url,
                    wait_until="domcontentloaded",
                    timeout=NAVIGATION_TIMEOUT_MS,
                )
                request_guard.require_navigation(episode_range.url, prior_navigation_count)
                await _assert_no_service_worker_controller(page)
                request_guard.raise_if_failed()
                await _guard_checkpoint(guard, page)
                if response is None or response.status not in (*range(200, 300), 304):
                    raise DiscoveryIncompleteError("HERO'S WEB range navigation did not return an allowed document")
                if page.url != episode_range.url:
                    raise DiscoveryIncompleteError("HERO'S WEB range navigation redirected unexpectedly")
                authenticated = await _current_document_is_authenticated(
                    page, expected_url=episode_range.url, auth=auth, guard=guard
                )
                snapshot = await _stable_snapshot(page, guard, expected_url=episode_range.url)
                current_title, range_rows = _validate_snapshot(
                    snapshot,
                    expected_url=episode_range.url,
                    work_id=work_id,
                    first_position=episode_range.start_position,
                    authenticated=authenticated,
                )
                if current_title != title:
                    raise DiscoveryIncompleteError("HERO'S WEB range Work title changed during traversal")
                entries = snapshot.get("rangeLinks")
                if not isinstance(entries, list):
                    raise DiscoveryIncompleteError("HERO'S WEB range controls disappeared")
                _validate_range_map(entries, work_id=work_id, ranges=ranges, selected=episode_range)
                expected_count = episode_range.end_position - episode_range.start_position + 1
                if len(range_rows) != expected_count:
                    raise DiscoveryIncompleteError("HERO'S WEB row count disagrees with its declared interval")
                for row in range_rows:
                    if row.episode_id in seen_ids:
                        raise DiscoveryIncompleteError("HERO'S WEB ranges repeat an episode identity")
                    seen_ids.add(row.episode_id)
                    rows.append(row)
                await _guard_checkpoint(guard, page)

            expected_total = ranges[-1].end_position
            if len(rows) != expected_total or len(seen_ids) != expected_total:
                raise DiscoveryIncompleteError("HERO'S WEB ranges do not cover their declared total")
            return _records_from_rows(
                rows, work_id=work_id, work_title=title, observed_at=observed_at,
            )
        except DiscoveryIncompleteError:
            raise
        except AccessStopError as exc:
            raise DiscoveryIncompleteError(f"HERO'S WEB stopped by the access guard: {exc.reason}") from exc
        except (PlaywrightError, TimeoutError) as exc:
            request_guard.raise_if_failed()
            await _guard_checkpoint(guard, page)
            raise DiscoveryIncompleteError("HERO'S WEB complete range listing did not finish") from exc
        finally:
            try:
                await asyncio.wait_for(guard.close(), timeout=GUARD_CLEANUP_TIMEOUT_SECONDS)
            finally:
                try:
                    await auth.close()
                finally:
                    await page.unroute("**/*", request_guard)

    async def _open_work(
        self,
        page,
        work_url: str,
        work_id: str,
        guard: AccessGuard,
        auth: _CurrentDocumentAuth,
        request_guard: _HeroswebRequestGuard,
    ):
        auth.begin_document(work_url)
        request_guard.allow_navigation(work_url)
        await _assert_no_service_worker_controller(page)
        prior_navigation_count = len(request_guard.main_frame_navigation_urls)
        response = await page.goto(work_url, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
        request_guard.require_navigation(work_url, prior_navigation_count)
        await _assert_no_service_worker_controller(page)
        request_guard.raise_if_failed()
        await _guard_checkpoint(guard, page)
        if response is None or response.status not in (*range(200, 300), 304) or page.url != work_url:
            raise DiscoveryIncompleteError("HERO'S WEB Work route did not load canonically")
        try:
            await page.wait_for_function(
                """() => document.querySelectorAll('.series-h').length === 1 &&
                  document.querySelectorAll('.series-sort').length === 1 &&
                  document.querySelectorAll('.series-sort a.series-sort-link').length > 0""",
                timeout=DOM_TIMEOUT_MS,
            )
            await _guard_checkpoint(guard, page)
            first = await asyncio.wait_for(page.evaluate(_snapshot_script()), OBSERVATION_TIMEOUT_SECONDS)
            await page.wait_for_timeout(STABILITY_INTERVAL_MS)
            second = await asyncio.wait_for(page.evaluate(_snapshot_script()), OBSERVATION_TIMEOUT_SECONDS)
        except (PlaywrightError, TimeoutError) as exc:
            raise DiscoveryIncompleteError("HERO'S WEB Work header or range controls did not settle") from exc
        if not isinstance(first, dict) or not isinstance(second, dict):
            raise DiscoveryIncompleteError("HERO'S WEB Work header is not a structured observation")
        stable_header_fields = (
            "canonicalCount",
            "canonicals",
            "titles",
            "mainCount",
            "rangeContainerCount",
            "rangeLinks",
        )
        if any(first.get(field) != second.get(field) for field in stable_header_fields):
            raise DiscoveryIncompleteError("HERO'S WEB Work header changed between stable observations")
        # The Work page's canonical points to the Work route; its episode rows
        # are intentionally ignored because that page exposes only a preview.
        title, ranges = _validate_work_header_snapshot(
            second, expected_url=work_url, work_id=work_id
        )
        authenticated = await _current_document_is_authenticated(
            page, expected_url=work_url, auth=auth, guard=guard
        )
        return title, ranges, authenticated

    @staticmethod
    def _parse_row(
        raw: object,
        *,
        first_position: int,
        work_id: str,
        authenticated: bool,
    ) -> _ListingRow:
        if not isinstance(raw, dict):
            raise DiscoveryIncompleteError("HERO'S WEB episode row is not a structured object")
        if (
            raw.get("linkCount") != 1
            or raw.get("titleCount") != 1
            or raw.get("dateCount") != 1
            or not isinstance(raw.get("href"), str)
            or not isinstance(raw.get("title"), str)
            or not raw["title"].strip()
            or not isinstance(raw.get("date"), str)
        ):
            raise DiscoveryIncompleteError("HERO'S WEB episode row is incomplete or ambiguous")
        episode_id = parse_herosweb_episode_url(raw["href"])
        if episode_id is None or raw["href"] != f"https://heros-web.com/episodes/{episode_id}":
            raise DiscoveryIncompleteError("HERO'S WEB episode link is not a canonical same-site URL")
        if not isinstance(work_id, str) or not re.fullmatch(r"[0-9a-f]{13}", work_id):
            raise DiscoveryIncompleteError("HERO'S WEB episode row has no valid Work identity")
        try:
            published_at = datetime.strptime(raw["date"], DATE_FORMAT).replace(tzinfo=JST)
        except ValueError as exc:
            raise DiscoveryIncompleteError("HERO'S WEB row date is not in the observed format") from exc
        return _ListingRow(
            episode_id=episode_id,
            title=raw["title"].strip(),
            published_at=published_at,
            access_mode=_classify_access(raw, authenticated=authenticated),
            global_position=first_position,
            rental_remaining=_rental_remaining(raw, authenticated=authenticated),
        )

    async def iter_records(
        self, page: Page, target: WatchlistTarget, mode: DiscoveryMode
    ) -> AsyncIterator[DiscoveredRecord]:
        self.reset_complete_listing_inventory()
        replay = take_exclusion_replay(self, page, target, mode)
        if replay is not None:
            for record in replay:
                yield record
            return
        all_records = await self._read_all_records(page, target)
        work_id = parse_herosweb_work_url(target.url)
        if work_id is None:
            raise DiscoveryIncompleteError("HERO'S WEB target identity disappeared")
        records = _apply_discovery_scope(all_records, scope=target.discovery_scope, work_id=work_id)
        if mode == "full":
            self.capture_complete_listing_inventory(
                target=target,
                all_records=all_records,
                selected_records=records,
                listing_identity=f"herosweb-work:{work_id}",
            )
        for record in records:
            yield record

    def incremental_stop_decision(
        self,
        record: DiscoveredRecord,
        previous: DiscoverySourceSnapshot | None,
        target: WatchlistTarget,
    ) -> IncrementalStopDecision:
        # The adapter validates and buffers the full declared listing first.
        # All yielded access labels therefore come from this one stable scan.
        del record, previous, target
        return IncrementalStopDecision.CONTINUE


async def _guard_checkpoint(guard: AccessGuard, page: Page) -> None:
    try:
        await asyncio.wait_for(guard.check_page(page), timeout=OBSERVATION_TIMEOUT_SECONDS)
    except AccessStopError as exc:
        raise DiscoveryIncompleteError(f"HERO'S WEB stopped by the access guard: {exc.reason}") from exc
    except TimeoutError as exc:
        path = urlsplit(page.url).path
        raise DiscoveryIncompleteError(f"HERO'S WEB access check timed out at {path}") from exc
