"""Fail-closed viewer and exact-free preflight for Hanayume episodes."""

from __future__ import annotations

import asyncio
import base64
import binascii
import io
import re
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from PIL import Image, UnidentifiedImageError
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page

from screenshot_crawler.core.access_guard import AccessProfile
from screenshot_crawler.core.capture import CaptureResult
from screenshot_crawler.core.errors import (
    PageChangeTimeoutError,
    UnknownPageStateError,
)
from screenshot_crawler.core.models import AccessStrategy, ContentContext, ContentIdentity
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.base import SiteAdapter
from screenshot_crawler.site_adapters.hanayume.access import hanayume_access_profile
from screenshot_crawler.site_adapters.hanayume.discovery import (
    RANGE_LABEL,
    RANGE_PAGE_SIZE,
    classify_hanayume_access,
    parse_hanayume_episode_url,
    parse_hanayume_work_url,
)

BASE_URL = "https://hanayume.com"
ALLOWED_HOSTS = frozenset({"hanayume.com", "www.hanayume.com"})
WORK_ID_PATTERN = re.compile(r"^[0-9a-f]{13}$")
EXTERNAL_ID_PATTERN = re.compile(r"^(?P<work>[0-9a-f]{13}):(?P<episode>[0-9a-f]{13})$")
SERIES_ROUTE = re.compile(r"^/series/(?P<work>[0-9a-f]{13})(?:/(?P<page>[1-9][0-9]*))?/?$")
COUNTER = re.compile(r"^(?P<current>[0-9]+)/(?P<total>[0-9]+)$")

WORK_LINK_SELECTOR = "#xHeader a.ep-h-main-h-series"
LISTING_SELECTOR = ".series-eplist-wrap"
RANGE_LINK_SELECTOR = f"{LISTING_SELECTOR} a.series-sort-link"
VIEWER_SELECTOR = "#comici-viewer"
PAGES_SELECTOR = "#xCVPages"
SEEK_SELECTOR = "#xCVSeekBar"

NAVIGATION_TIMEOUT_MS = 15_000
DOM_TIMEOUT_MS = 6_000
OBSERVATION_TIMEOUT_SECONDS = 4.0
RANGE_PACING_MS = 350
MAX_RANGE_PAGES = 100
MAX_LISTING_ROWS = RANGE_PAGE_SIZE * MAX_RANGE_PAGES
INITIALIZE_TIMEOUT_MS = 240_000
MAX_PNG_BYTES = 8_000_000
POLL_INTERVAL_SECONDS = 0.15
FREE_LABEL = "\u7121\u6599"

SNAPSHOT_SCRIPT = r"""({includePng = false} = {}) => {
  const one = selector => {
    const nodes = [...document.querySelectorAll(selector)];
    return nodes.length === 1 ? nodes[0] : null;
  };
  const viewer = one('#comici-viewer');
  const pages = one('#xCVPages');
  const seek = one('#xCVSeekBar');
  const currentNode = one('.-cv-f-page-current');
  const totalNode = one('.-cv-f-page-total');
  const viewport = {width: innerWidth, height: innerHeight};
  const slots = pages ? [...pages.children].map((node, index) => {
    const classes = [...node.classList].sort();
    const rect = node.getBoundingClientRect();
    const canvases = [...node.querySelectorAll('canvas')];
    const canvas = canvases.length === 1 ? canvases[0] : null;
    const parent = canvas?.parentElement;
    const canvasRect = canvas?.getBoundingClientRect();
    const visible = !!canvasRect && canvasRect.width > 0 && canvasRect.height > 0 &&
      canvasRect.x >= -1 && canvasRect.y >= -1 &&
      canvasRect.right <= innerWidth + 1 && canvasRect.bottom <= innerHeight + 1;
    const ready = !!canvas && classes.includes('mode-loaded') &&
      classes.includes('mode-rendered') &&
      parent?.classList.contains('-cv-page-canvas') === true &&
      canvas.width > 0 && canvas.height > 0;
    const row = {
      index, classes,
      wrapper: [rect.x, rect.y, rect.width, rect.height],
      wrapperCenterInViewport: rect.width > 0 && rect.height > 0 &&
        rect.x + rect.width / 2 >= 0 && rect.x + rect.width / 2 <= innerWidth &&
        rect.y + rect.height / 2 >= 0 && rect.y + rect.height / 2 <= innerHeight,
      canvasCount: canvases.length,
      canvas: canvas ? {
        width: canvas.width, height: canvas.height,
        rect: [canvasRect.x, canvasRect.y, canvasRect.width, canvasRect.height],
        parentClasses: [...parent.classList].sort(), ready, visible,
        png: includePng && ready && visible ? canvas.toDataURL('image/png') : null
      } : null
    };
    return row;
  }) : [];
  return {
    url: location.href,
    viewerCount: document.querySelectorAll('#comici-viewer').length,
    viewerClasses: viewer ? [...viewer.classList].sort() : [],
    pagesCount: document.querySelectorAll('#xCVPages').length,
    seekCount: document.querySelectorAll('#xCVSeekBar').length,
    currentText: currentNode?.textContent?.trim() ?? null,
    totalText: totalNode?.textContent?.trim() ?? null,
    seek: seek ? {type: seek.type, min: seek.min, max: seek.max, step: seek.step, value: seek.value} : null,
    viewport,
    slots
  };
}"""

RANGE_SNAPSHOT_SCRIPT = r"""() => ({
  path: location.pathname,
  ranges: [...document.querySelectorAll('.series-eplist-wrap a.series-sort-link')]
    .map(anchor => ({
      label: (anchor.innerText || '').replace(/\s+/g, ' ').trim(),
      href: anchor.href,
      current: anchor.classList.contains('mode-current')
    })),
  rows: [...document.querySelectorAll(
    '.series-eplist-wrap .series-eplist-item[data-e2e="eli"]')]
    .map((row, index) => {
      const links = [...row.querySelectorAll('a.series-eplist-item-link')];
      const badges = [...row.querySelectorAll('.series-eplist-item-access-text')];
      return {
        index,
        linkCount: links.length,
        href: links.length === 1 ? links[0].href : null,
        labels: badges.map(node => (node.innerText || '').replace(/\s+/g, ' ').trim())
      };
    })
})"""


@dataclass(frozen=True, slots=True)
class SeriesRange:
    page_number: int
    start: int
    end: int
    label: str
    url: str


@dataclass(frozen=True, slots=True)
class ViewerObservation:
    current: int
    total: int
    seek_value: int
    seek_min: int
    seek_max: int
    seek_step: int
    body_total: int
    active_slots: tuple[int, ...]
    ready_slots: tuple[int, ...]
    terminal: bool
    raw: dict[str, object]


def _strict_first_party_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme.lower() == "https"
        and (parsed.hostname or "").lower() in ALLOWED_HOSTS
        and parsed.username is None
        and parsed.password is None
        and port in (None, 443)
        and not parsed.query
        and not parsed.fragment
    )


def _series_range_route(url: str, work_id: str) -> tuple[int | None, str] | None:
    if not _strict_first_party_url(url):
        return None
    match = SERIES_ROUTE.fullmatch(urlsplit(url).path)
    if match is None or match.group("work") != work_id:
        return None
    raw_page = match.group("page")
    return (int(raw_page) if raw_page is not None else None, urlsplit(url).path)


def _parse_series_ranges(
    entries: object,
    *,
    work_id: str,
    require_selected_page: int | None = None,
    actual_page_url: str | None = None,
) -> tuple[SeriesRange, ...]:
    """Validate the whole observed series navigation and selected marker."""

    if not isinstance(entries, list) or not entries:
        raise UnknownPageStateError("Hanayume series range navigation is missing")
    numeric: list[tuple[int, int, str, str, bool, str]] = []
    current_entries: list[dict[str, object]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise UnknownPageStateError("Hanayume range link is malformed")
        label, href, current = entry.get("label"), entry.get("href"), entry.get("current")
        if not isinstance(label, str) or not isinstance(href, str) or not isinstance(current, bool):
            raise UnknownPageStateError("Hanayume range link is incomplete")
        if current:
            current_entries.append(entry)
        match = RANGE_LABEL.fullmatch(label)
        if match is None:
            if label[:1].isdigit():
                raise UnknownPageStateError("Hanayume numeric range label is invalid")
            continue
        route = _series_range_route(href, work_id)
        if route is None:
            raise UnknownPageStateError("Hanayume range link is foreign or malformed")
        start, end = int(match.group("start")), int(match.group("end"))
        numeric.append((start, end, label, href, current, route[1]))

    if not numeric or len(numeric) > MAX_RANGE_PAGES:
        raise UnknownPageStateError("Hanayume declared range count is missing or exceeds its guard")
    numeric.sort(key=lambda item: item[0])
    ranges: list[SeriesRange] = []
    expected_start = 1
    for page_number, (start, end, label, href, current, path) in enumerate(numeric, start=1):
        if start != expected_start or end < start or label != f"{start}-{end}":
            raise UnknownPageStateError("Hanayume series ranges are not contiguous oldest-first")
        count = end - start + 1
        if count > RANGE_PAGE_SIZE or (page_number < len(numeric) and count != RANGE_PAGE_SIZE):
            raise UnknownPageStateError("Hanayume series range size differs from its declared page")
        numeric_path = f"/series/{work_id}/{page_number}"
        alias_path = f"/series/{work_id}"
        if path != numeric_path and not (current and path == alias_path):
            raise UnknownPageStateError("Hanayume range URL does not match its exact page number")
        ranges.append(
            SeriesRange(
                page_number=page_number,
                start=start,
                end=end,
                label=label,
                url=f"{BASE_URL}{numeric_path}",
            )
        )
        expected_start = end + 1
    if expected_start - 1 > MAX_LISTING_ROWS:
        raise UnknownPageStateError("Hanayume listing exceeds its row-count guard")

    if require_selected_page is not None:
        if actual_page_url is None or len(current_entries) != 1:
            raise UnknownPageStateError("Hanayume selected range marker is missing or duplicated")
        selected = ranges[require_selected_page - 1] if 1 <= require_selected_page <= len(ranges) else None
        actual = urlsplit(actual_page_url)
        if (
            selected is None
            or not _strict_first_party_url(actual_page_url)
            or actual_page_url != selected.url
            or current_entries[0].get("label") != selected.label
        ):
            raise UnknownPageStateError("Hanayume selected range differs from its exact route")
        selected_href = current_entries[0].get("href")
        if selected_href != f"{BASE_URL}/series/{work_id}":
            raise UnknownPageStateError("Hanayume selected range alias differs from live evidence")
        del actual
    elif current_entries:
        if len(current_entries) != 1:
            raise UnknownPageStateError("Hanayume initial range markers are ambiguous")

    return tuple(ranges)


def _validate_range_set(
    observed: tuple[SeriesRange, ...], expected: tuple[SeriesRange, ...]
) -> None:
    signature = lambda rows: tuple(
        (row.page_number, row.start, row.end, row.label, row.url) for row in rows
    )
    if signature(observed) != signature(expected):
        raise UnknownPageStateError("Hanayume range set changed while enumerating the work")

def _find_target_labels(rows: object, target_episode_id: str | None) -> tuple[str, ...] | None:
    """Validate one observed listing page and return its unique target labels."""

    if not isinstance(rows, list):
        raise UnknownPageStateError("Hanayume episode rows are malformed")
    if target_episode_id is None:
        raise UnknownPageStateError("Hanayume target episode identity is missing")
    seen_ids: set[str] = set()
    target_labels: list[tuple[str, ...]] = []
    for index, row in enumerate(rows):
        if (
            not isinstance(row, dict)
            or row.get("index") != index
            or row.get("linkCount") != 1
            or not isinstance(row.get("href"), str)
            or not isinstance(row.get("labels"), list)
            or not all(isinstance(label, str) for label in row["labels"])
        ):
            raise UnknownPageStateError("Hanayume episode row is incomplete or ambiguous")
        episode = parse_hanayume_episode_url(row["href"])
        if episode is None or episode.episode_id in seen_ids:
            raise UnknownPageStateError("Hanayume range has a foreign or duplicate episode ID")
        seen_ids.add(episode.episode_id)
        if episode.episode_id == target_episode_id:
            target_labels.append(tuple(row["labels"]))
    if len(target_labels) > 1:
        raise UnknownPageStateError("Hanayume target episode row is duplicated")
    return target_labels[0] if target_labels else None



def _expected_active_slots(current: int, body_total: int) -> tuple[int, ...]:
    if current == 1:
        raw = (1,)
    else:
        raw = (current - 1, current)
    return tuple(index for index in raw if 1 <= index <= body_total)


def _slot_role(index: int, total: int, classes: object) -> str:
    if not isinstance(classes, list) or not all(isinstance(value, str) for value in classes):
        raise UnknownPageStateError("Hanayume viewer slot classes are malformed")
    actual = set(classes)
    if "-cv-page" not in actual:
        raise UnknownPageStateError("Hanayume viewer slot is missing its page wrapper")
    tails = {
        0: {"-cv-page", "mode-empty", "mode-pr", "mode-top-pr"},
        total - 4: {"-cv-page", "mode-ci"},
        total - 3: {"-cv-page", "mode-empty", "mode-pr"},
        total - 2: {"-cv-page", "mode-empty", "mode-pr"},
        total - 1: {"-cv-page", "mode-good"},
        total: {"-cv-page", "mode-last"},
    }
    if index in tails:
        if actual != tails[index]:
            raise UnknownPageStateError("Hanayume non-body viewer slot changed structure")
        return "nonbody"
    if not 1 <= index <= total - 5:
        raise UnknownPageStateError("Hanayume viewer slot is outside the known layout")
    state_classes = actual - {"-cv-page"}
    if not (
        state_classes.issubset({"mode-loaded", "mode-rendered"})
        or state_classes in (
            {"mode-loading"},
            {"mode-loading", "mode-req-render"},
        )
    ):
        raise UnknownPageStateError("Hanayume body slot has an unknown state class")
    if "mode-rendered" in state_classes and "mode-loaded" not in state_classes:
        raise UnknownPageStateError("Hanayume rendered body slot lacks its loaded marker")
    return "body"


def _parse_viewer_observation(raw: object) -> ViewerObservation:
    if not isinstance(raw, dict):
        raise UnknownPageStateError("Hanayume viewer observation is invalid")
    if (
        raw.get("viewerCount") != 1
        or raw.get("pagesCount") != 1
        or raw.get("seekCount") != 1
        or not isinstance(raw.get("viewerClasses"), list)
        or "mode-spread" not in raw["viewerClasses"]
    ):
        raise UnknownPageStateError("Hanayume viewer structure or spread mode is unknown")
    counter_text = raw.get("currentText")
    total_text = raw.get("totalText")
    if not isinstance(counter_text, str) or not isinstance(total_text, str):
        raise UnknownPageStateError("Hanayume viewer page counter is missing")
    try:
        current = int(counter_text)
        total = int(total_text)
    except ValueError as exc:
        raise UnknownPageStateError("Hanayume viewer page counter is malformed") from exc
    seek = raw.get("seek")
    if not isinstance(seek, dict) or seek.get("type") != "range":
        raise UnknownPageStateError("Hanayume public seek control is missing")
    try:
        seek_min = int(seek["min"])
        seek_max = int(seek["max"])
        seek_step = int(seek["step"])
        seek_value = int(seek["value"])
    except (KeyError, TypeError, ValueError) as exc:
        raise UnknownPageStateError("Hanayume seek control values are malformed") from exc
    if (
        total < 8
        or current < 1
        or current > total
        or current % 2 != 1
        or seek_min != 1
        or seek_max != total
        or seek_step != 2
        or seek_value != seek_max - (current - 1)
    ):
        raise UnknownPageStateError("Hanayume viewer counter and public seek control disagree")
    slots = raw.get("slots")
    if not isinstance(slots, list) or len(slots) != total + 1:
        raise UnknownPageStateError("Hanayume viewer page-wrapper count is incomplete")
    body_total = total - 5
    active: list[int] = []
    ready: list[int] = []
    terminal = "mode-last-page" in raw["viewerClasses"]
    for index, slot in enumerate(slots):
        if not isinstance(slot, dict) or slot.get("index") != index:
            raise UnknownPageStateError("Hanayume viewer page-wrapper order is invalid")
        role = _slot_role(index, total, slot.get("classes"))
        if role != "body":
            continue
        if slot.get("wrapperCenterInViewport") is True:
            active.append(index)
        canvas_count = slot.get("canvasCount")
        canvas = slot.get("canvas")
        if canvas_count == 0:
            if canvas is not None:
                raise UnknownPageStateError("Hanayume canvas count changed during observation")
            continue
        if canvas_count != 1 or not isinstance(canvas, dict):
            raise UnknownPageStateError("Hanayume body slot has ambiguous canvases")
        if canvas.get("ready") is True and canvas.get("visible") is True:
            if not isinstance(canvas.get("width"), int) or not isinstance(canvas.get("height"), int):
                raise UnknownPageStateError("Hanayume rendered canvas dimensions are invalid")
            ready.append(index)
    if terminal and (current != total or seek_value != seek_min):
        raise UnknownPageStateError("Hanayume terminal marker disagrees with the counter")
    return ViewerObservation(
        current=current,
        total=total,
        seek_value=seek_value,
        seek_min=seek_min,
        seek_max=seek_max,
        seek_step=seek_step,
        body_total=body_total,
        active_slots=tuple(active),
        ready_slots=tuple(ready),
        terminal=terminal,
        raw=raw,
    )


def _decode_canvas_png(value: object, *, width: int, height: int) -> bytes:
    if not isinstance(value, str) or not value.startswith("data:image/png;base64,"):
        raise UnknownPageStateError("Hanayume canvas PNG readback failed")
    try:
        data = base64.b64decode(value.partition(",")[2], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise UnknownPageStateError("Hanayume canvas PNG data is malformed") from exc
    if len(data) > MAX_PNG_BYTES:
        raise UnknownPageStateError("Hanayume canvas PNG exceeds its byte guard")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "PNG" or image.size != (width, height):
                raise UnknownPageStateError("Hanayume canvas PNG dimensions do not match the canvas")
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            image.load()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        if isinstance(exc, UnknownPageStateError):
            raise
        raise UnknownPageStateError("Hanayume canvas PNG did not decode cleanly") from exc
    return data


class HanayumeAdapter(SiteAdapter):
    """Capture only the current, exact free Hanayume body canvases as PNG."""

    page_change_timeout_ms = 12_000

    def __init__(self) -> None:
        self._target_url: str | None = None
        self._episode_id: str | None = None
        self._expected_work_id: str | None = None
        self._opaque_work_key: str | None = None
        self._work_id: str | None = None
        self._body_total: int | None = None
        self._captured_slots: list[int] = []
        self._pending: tuple[str, int, tuple[int, ...]] | None = None
        self._ended = False
        self._last_capture_slots: tuple[int, ...] = ()

    def get_access_profile(self) -> AccessProfile:
        return hanayume_access_profile()

    def get_initialize_timeout_ms(self, default_ms: int) -> int:
        return max(default_ms, INITIALIZE_TIMEOUT_MS)

    async def configure_run(self, page: Page, access_strategy: AccessStrategy) -> None:
        del page
        if access_strategy not in {"auto", "direct"}:
            raise UnknownPageStateError(
                "Hanayume supports only its observed free auto/direct path"
            )

    async def configure_target_identity(self, external_id: str, work_key: str) -> None:
        match = EXTERNAL_ID_PATTERN.fullmatch(external_id)
        if match is None:
            raise UnknownPageStateError("Hanayume Batch target identity is malformed")
        self._expected_work_id = match.group("work")
        self._episode_id = match.group("episode")
        self._opaque_work_key = work_key

    def resolve_initial_navigation_url(self, source_url: str) -> str:
        parsed = parse_hanayume_episode_url(source_url)
        if parsed is None:
            raise UnknownPageStateError("Hanayume requires an exact absolute episode URL")
        if self._episode_id is not None and self._episode_id != parsed.episode_id:
            raise UnknownPageStateError("Hanayume URL episode differs from the Catalog target")
        self._episode_id = parsed.episode_id
        self._target_url = f"{BASE_URL}/episodes/{parsed.episode_id}"
        return self._target_url

    async def initialize(self, page: Page) -> None:
        if self._target_url is None or self._episode_id is None or page.url != self._target_url:
            raise UnknownPageStateError("Hanayume initial episode URL does not match its target")
        initial_work = await self._read_episode_work(page)
        if self._expected_work_id is not None and initial_work != self._expected_work_id:
            raise UnknownPageStateError("Hanayume episode belongs to a different Catalog work")
        await self._fresh_free_preflight(page, initial_work)
        if page.url != self._target_url:
            await self._navigate_exact(page, self._target_url)
        await self._wait_for_episode(page, expected_work=initial_work)
        await self._wait_for_locator(page, SEEK_SELECTOR, state="attached")
        first = await self._observe(page)
        if first.terminal or first.current != 1 or first.seek_value != first.seek_max:
            seek = page.locator(SEEK_SELECTOR)
            try:
                await asyncio.wait_for(seek.focus(timeout=1_500), timeout=2.0)
                await asyncio.wait_for(seek.press("End", timeout=1_500), timeout=2.0)
            except (PlaywrightError, TimeoutError) as exc:
                raise UnknownPageStateError("Hanayume viewer could not rewind with its observed seek control") from exc
        first = await self._wait_for_observation(
            page,
            lambda row: not row.terminal
            and row.current == 1
            and row.seek_value == row.seek_max
            and row.ready_slots == (1,),
            reason="Hanayume viewer did not settle at its first body page",
        )
        self._work_id = initial_work
        self._body_total = first.body_total
        self._captured_slots = []
        self._pending = None
        self._ended = False

    async def _fresh_free_preflight(self, page: Page, work_id: str) -> None:
        work_url = f"{BASE_URL}/series/{work_id}"
        await self._navigate_exact(page, work_url)
        await self._wait_for_locator(page, LISTING_SELECTOR, state="visible")
        initial = await self._read_range_page(page)
        if initial.get("path") != f"/series/{work_id}":
            raise UnknownPageStateError("Hanayume bare work listing changed its exact route")
        ranges = _parse_series_ranges(initial.get("ranges"), work_id=work_id)
        if not ranges:
            raise UnknownPageStateError("Hanayume work has no supported episode ranges")

        target_labels = _find_target_labels(initial.get("rows"), self._episode_id)
        if target_labels is None:
            # The bare route can be a latest-page preview. Follow its observed
            # numbered links only until the target is found; Discovery owns
            # full-work coverage and cross-range uniqueness.
            for index, episode_range in enumerate(ranges):
                if index:
                    await page.wait_for_timeout(RANGE_PACING_MS)
                await self._navigate_exact(page, episode_range.url)
                await self._wait_for_locator(page, LISTING_SELECTOR, state="visible")
                observed = await self._read_range_page(page)
                selected_ranges = _parse_series_ranges(
                    observed.get("ranges"),
                    work_id=work_id,
                    require_selected_page=episode_range.page_number,
                    actual_page_url=page.url,
                )
                _validate_range_set(selected_ranges, ranges)
                rows = observed.get("rows")
                expected_count = episode_range.end - episode_range.start + 1
                if not isinstance(rows, list) or len(rows) != expected_count:
                    raise UnknownPageStateError(
                        "Hanayume episode count differs from its selected range"
                    )
                target_labels = _find_target_labels(rows, self._episode_id)
                if target_labels is not None:
                    break

        if target_labels is None:
            raise UnknownPageStateError("Hanayume target episode is missing from its work")
        access = classify_hanayume_access(target_labels)
        if access.raw_labels != (FREE_LABEL,) or access.access_mode != "free":
            raise UnknownPageStateError(
                "Hanayume target is not one exact logged-out free row"
            )

        await self._navigate_exact(page, self._target_url or "")
        await self._wait_for_episode(page, expected_work=work_id)
        await self._validate_episode_free_row(page)

    async def _navigate_exact(self, page: Page, url: str) -> None:
        if not _strict_first_party_url(url):
            raise UnknownPageStateError("Hanayume navigation URL is outside the observed first-party routes")
        try:
            response = await asyncio.wait_for(
                page.goto(url, timeout=NAVIGATION_TIMEOUT_MS, wait_until="domcontentloaded"),
                timeout=NAVIGATION_TIMEOUT_MS / 1000 + 1,
            )
        except (PlaywrightError, TimeoutError) as exc:
            raise UnknownPageStateError("Hanayume navigation did not complete within its bound") from exc
        if response is None or response.status != 200 or page.url != url:
            raise UnknownPageStateError("Hanayume navigation did not return its exact HTTP 200 route")

    async def _wait_for_locator(self, page: Page, selector: str, *, state: str) -> None:
        try:
            await asyncio.wait_for(
                page.locator(selector).wait_for(state=state, timeout=DOM_TIMEOUT_MS),
                timeout=DOM_TIMEOUT_MS / 1000 + 1,
            )
        except (PlaywrightError, TimeoutError) as exc:
            raise UnknownPageStateError("Hanayume expected page structure did not become ready") from exc

    async def _read_range_page(self, page: Page) -> dict[str, object]:
        try:
            value = await asyncio.wait_for(page.evaluate(RANGE_SNAPSHOT_SCRIPT), timeout=OBSERVATION_TIMEOUT_SECONDS)
        except (PlaywrightError, TimeoutError) as exc:
            raise UnknownPageStateError("Hanayume range observation exceeded its timeout") from exc
        if not isinstance(value, dict) or value.get("path") != urlsplit(page.url).path:
            raise UnknownPageStateError("Hanayume range observation URL is inconsistent")
        return value

    async def _read_episode_work(self, page: Page) -> str:
        if self._target_url is None or page.url != self._target_url:
            raise UnknownPageStateError("Hanayume current URL does not match the target episode")
        await self._wait_for_locator(page, WORK_LINK_SELECTOR, state="attached")
        try:
            values = await asyncio.wait_for(
                page.locator(WORK_LINK_SELECTOR).evaluate_all("nodes => nodes.map(node => node.href)"),
                timeout=OBSERVATION_TIMEOUT_SECONDS,
            )
        except (PlaywrightError, TimeoutError) as exc:
            raise UnknownPageStateError("Hanayume scoped work identity could not be read") from exc
        if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], str):
            raise UnknownPageStateError("Hanayume episode has no unique scoped work link")
        work_id = parse_hanayume_work_url(values[0])
        if work_id is None:
            raise UnknownPageStateError("Hanayume scoped work link is invalid")
        return work_id

    async def _read_episode_row_labels(self, page: Page) -> list[tuple[str, ...]]:
        try:
            rows = await asyncio.wait_for(
                page.evaluate(
                    r"""() => [...document.querySelectorAll(
                      '.series-eplist-wrap .series-eplist-item[data-e2e="eli"]')].map(row => ({
                        hrefs: [...row.querySelectorAll('a.series-eplist-item-link')].map(link => link.href),
                        labels: [...row.querySelectorAll('.series-eplist-item-access-text')]
                          .map(node => (node.innerText || '').replace(/\s+/g, ' ').trim())
                      }))"""
                ),
                timeout=OBSERVATION_TIMEOUT_SECONDS,
            )
        except (PlaywrightError, TimeoutError) as exc:
            raise UnknownPageStateError("Hanayume current episode access row could not be read") from exc
        if not isinstance(rows, list):
            raise UnknownPageStateError("Hanayume current episode access row is malformed")
        result: list[tuple[str, ...]] = []
        expected_path = f"/episodes/{self._episode_id}"
        for row in rows:
            if (
                not isinstance(row, dict)
                or not isinstance(row.get("hrefs"), list)
                or not all(isinstance(href, str) for href in row["hrefs"])
                or not isinstance(row.get("labels"), list)
                or not all(isinstance(label, str) for label in row["labels"])
            ):
                raise UnknownPageStateError("Hanayume current episode access row is malformed")
            hrefs = row["hrefs"]
            target_like = False
            for href in hrefs:
                try:
                    target_like = target_like or urlsplit(href).path == expected_path
                except ValueError as exc:
                    raise UnknownPageStateError(
                        "Hanayume current episode row contains an invalid URL"
                    ) from exc
            if not target_like:
                continue
            if len(hrefs) != 1:
                raise UnknownPageStateError(
                    "Hanayume current episode row is ambiguous"
                )
            identity = parse_hanayume_episode_url(hrefs[0])
            if identity is None or identity.episode_id != self._episode_id:
                raise UnknownPageStateError(
                    "Hanayume current episode row URL is not the exact first-party target"
                )
            result.append(tuple(row["labels"]))
        if len(result) != 1:
            raise UnknownPageStateError("Hanayume current episode row is missing or duplicated")
        return result

    async def _validate_episode_free_row(self, page: Page) -> None:
        await self._wait_for_locator(page, LISTING_SELECTOR, state="visible")
        labels = await self._read_episode_row_labels(page)
        if labels != [(FREE_LABEL,)]:
            raise UnknownPageStateError("Hanayume current episode no longer has one exact 無料 badge")

    async def _wait_for_episode(self, page: Page, *, expected_work: str) -> None:
        if self._target_url is None or page.url != self._target_url:
            raise UnknownPageStateError("Hanayume episode navigation changed target identity")
        observed_work = await self._read_episode_work(page)
        if observed_work != expected_work or (
            self._expected_work_id is not None and observed_work != self._expected_work_id
        ):
            raise UnknownPageStateError("Hanayume current episode work identity changed")

    async def _observe(self, page: Page, *, include_png: bool = False) -> ViewerObservation:
        try:
            raw = await asyncio.wait_for(
                page.evaluate(SNAPSHOT_SCRIPT, {"includePng": include_png}),
                timeout=OBSERVATION_TIMEOUT_SECONDS,
            )
        except (PlaywrightError, TimeoutError) as exc:
            raise UnknownPageStateError("Hanayume viewer observation exceeded its timeout") from exc
        if not isinstance(raw, dict) or raw.get("url") != page.url:
            raise UnknownPageStateError("Hanayume viewer observation changed URL")
        expected_url = self._target_url
        if expected_url is not None and page.url != expected_url:
            raise UnknownPageStateError("Hanayume viewer moved away from the selected episode")
        return _parse_viewer_observation(raw)

    async def _wait_for_observation(self, page: Page, predicate, *, reason: str) -> ViewerObservation:
        deadline = time.monotonic() + self.page_change_timeout_ms / 1000
        previous: tuple[object, ...] | None = None
        stable = 0
        last: ViewerObservation | None = None
        while time.monotonic() < deadline:
            observation = await self._observe(page)
            last = observation
            signature = (
                observation.current,
                observation.total,
                observation.seek_value,
                observation.active_slots,
                observation.ready_slots,
                observation.terminal,
            )
            if predicate(observation) and signature == previous:
                stable += 1
                if stable >= 2:
                    return observation
            else:
                stable = 0
            previous = signature
            remaining = deadline - time.monotonic()
            if remaining > 0:
                await page.wait_for_timeout(min(150, int(remaining * 1000)))
        raise PageChangeTimeoutError(reason if last is None else f"{reason}; last counter={last.current}/{last.total}")

    async def detect_state(self, page: Page) -> PageState:
        if self._ended:
            return PageState.END
        observation = await self._observe(page)
        if self._body_total is not None and observation.body_total != self._body_total:
            raise UnknownPageStateError("Hanayume viewer body count changed during capture")
        if observation.terminal:
            if (
                self._body_total is not None
                and len(self._captured_slots) == self._body_total
                and observation.ready_slots == ()
            ):
                self._ended = True
                return PageState.END
            raise UnknownPageStateError("Hanayume reached END before all body slots were captured")
        expected = _expected_active_slots(observation.current, observation.body_total)
        if observation.active_slots != expected:
            return PageState.LOADING
        if observation.ready_slots != expected:
            return PageState.LOADING
        expected_next = tuple(range(len(self._captured_slots) + 1, len(self._captured_slots) + 1 + len(expected)))
        if expected != expected_next:
            raise UnknownPageStateError("Hanayume body slot order has a gap or repetition")
        return PageState.CONTENT

    async def get_capture_target(self, page: Page) -> Locator:
        del page
        raise UnknownPageStateError(
            "Hanayume capture requires the atomic rendered-canvas PNG readback"
        )

    async def get_capture_targets(self, page: Page) -> tuple[Locator, ...]:
        del page
        raise UnknownPageStateError(
            "Hanayume does not permit generic locator or screenshot capture fallback"
        )

    async def capture_page(self, page: Page) -> tuple[CaptureResult, ...] | None:
        observation = await self._observe(page, include_png=True)
        expected = _expected_active_slots(observation.current, observation.body_total)
        next_slots = tuple(range(len(self._captured_slots) + 1, len(self._captured_slots) + 1 + len(expected)))
        if observation.terminal or not expected or expected != next_slots:
            raise UnknownPageStateError("Hanayume capture is not the next complete body page/spread")
        if observation.active_slots != expected or observation.ready_slots != expected:
            raise UnknownPageStateError("Hanayume current spread is missing a ready body canvas")
        slots = observation.raw.get("slots")
        if not isinstance(slots, list):
            raise UnknownPageStateError("Hanayume canvas wrapper list disappeared during capture")
        captures: list[CaptureResult] = []
        for index in expected:
            slot = slots[index]
            canvas = slot.get("canvas") if isinstance(slot, dict) else None
            if not isinstance(canvas, dict) or canvas.get("ready") is not True or canvas.get("visible") is not True:
                raise UnknownPageStateError("Hanayume selected canvas changed before readback")
            width, height = canvas.get("width"), canvas.get("height")
            if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
                raise UnknownPageStateError("Hanayume selected canvas dimensions are invalid")
            data = _decode_canvas_png(canvas.get("png"), width=width, height=height)
            captures.append(CaptureResult(data=data, width=width, height=height))
        self._captured_slots.extend(expected)
        self._last_capture_slots = expected
        return tuple(captures)

    async def get_content_identity(self, page: Page) -> ContentIdentity:
        observation = await self._observe(page)
        expected = _expected_active_slots(observation.current, observation.body_total)
        next_slots = tuple(
            range(len(self._captured_slots) + 1, len(self._captured_slots) + 1 + len(expected))
        )
        if observation.active_slots != expected or observation.ready_slots != expected or expected != next_slots:
            raise UnknownPageStateError("Hanayume current spread has no stable body identity")
        return ContentIdentity(
            page_id=",".join(str(index) for index in expected),
            page_number=expected[0],
            source_id=self._episode_id,
        )

    async def get_content_context(self, page: Page) -> ContentContext:
        await self._wait_for_episode(page, expected_work=self._work_id or self._expected_work_id or "")
        return ContentContext(
            content_id=self._episode_id,
            work_id=self._work_id or self._expected_work_id,
            episode_id=self._episode_id,
        )

    async def go_next(self, page: Page) -> None:
        observation = await self._observe(page)
        if self._pending is not None:
            raise UnknownPageStateError("Hanayume previous seek transition has not been verified")
        if self._body_total is None or len(self._captured_slots) == 0:
            raise UnknownPageStateError("Hanayume cannot advance before capturing the current body spread")
        if self._captured_slots != list(range(1, len(self._captured_slots) + 1)):
            raise UnknownPageStateError("Hanayume captured body page sequence is not contiguous")
        if (
            observation.terminal
            or observation.ready_slots != self._last_capture_slots
            or observation.active_slots != _expected_active_slots(observation.current, observation.body_total)
            or not self._last_capture_slots
        ):
            raise UnknownPageStateError("Hanayume current spread changed after its canvas capture")
        if len(self._captured_slots) == self._body_total:
            seek = page.locator(SEEK_SELECTOR)
            try:
                await asyncio.wait_for(seek.focus(timeout=1_500), timeout=2.0)
                await asyncio.wait_for(seek.press("Home", timeout=1_500), timeout=2.0)
            except (PlaywrightError, TimeoutError) as exc:
                raise PageChangeTimeoutError("Hanayume observed terminal seek action failed") from exc
            self._pending = ("terminal", observation.current, ())
            return
        next_value = observation.seek_value - observation.seek_step
        if next_value < observation.seek_min or next_value > observation.seek_max:
            raise UnknownPageStateError("Hanayume next public seek value is outside its observed range")
        try:
            await asyncio.wait_for(
                page.locator(SEEK_SELECTOR).evaluate(
                    """(input, value) => {
                      const min = Number(input.min), max = Number(input.max), step = Number(input.step);
                      if (!Number.isInteger(value) || value < min || value > max || (max - value) % step !== 0)
                        throw new Error('seek_value_out_of_range');
                      input.value = String(value);
                      input.dispatchEvent(new Event('input', {bubbles: true}));
                      input.dispatchEvent(new Event('change', {bubbles: true}));
                    }""",
                    next_value,
                ),
                timeout=OBSERVATION_TIMEOUT_SECONDS,
            )
        except (PlaywrightError, TimeoutError) as exc:
            raise PageChangeTimeoutError("Hanayume observed public seek input could not advance") from exc
        self._pending = ("spread", observation.current, _expected_active_slots(observation.current + 2, observation.body_total))

    async def wait_for_change(
        self, page: Page, previous_identity: ContentIdentity | None
    ) -> None:
        del previous_identity
        if self._pending is None:
            raise PageChangeTimeoutError("Hanayume has no verified seek transition pending")
        kind, previous_current, expected_slots = self._pending
        if kind == "terminal":
            observation = await self._wait_for_observation(
                page,
                lambda row: row.terminal
                and row.current == row.total
                and row.seek_value == row.seek_min
                and row.ready_slots == (),
                reason="Hanayume did not reach its observed terminal UI after all body pages",
            )
            if len(self._captured_slots) != observation.body_total:
                raise UnknownPageStateError("Hanayume terminal UI arrived before complete body coverage")
            self._ended = True
            self._pending = None
            return
        observation = await self._wait_for_observation(
            page,
            lambda row: not row.terminal
            and row.current == previous_current + 2
            and row.active_slots == expected_slots
            and row.ready_slots == expected_slots,
            reason="Hanayume next spread did not render in exact slot order",
        )
        expected_next = tuple(range(len(self._captured_slots) + 1, len(self._captured_slots) + 1 + len(expected_slots)))
        if observation.ready_slots != expected_next:
            raise UnknownPageStateError("Hanayume spread advance skipped or repeated body slots")
        self._pending = None

    async def collect_debug_metadata(self, page: Page) -> dict[str, object]:
        del page
        return {
            "capture_mode": "rendered_body_canvas_png",
            "episode_id": self._episode_id,
            "captured_body_slots": len(self._captured_slots),
            "body_total": self._body_total,
            "last_slots": list(self._last_capture_slots),
            "source_native": False,
        }


__all__ = ["HanayumeAdapter"]
