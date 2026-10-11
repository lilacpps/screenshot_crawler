"""Manual, exact-free Younganimal crawl entry and rendered viewer adapter."""

from __future__ import annotations

import asyncio
import math
import re
import time
from typing import Any
from urllib.parse import urlsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from screenshot_crawler.core.access_guard import AccessProfile
from screenshot_crawler.core.capture import CaptureResult
from screenshot_crawler.core.errors import (
    PageChangeTimeoutError,
    UnknownPageStateError,
    UnsupportedAccessStrategyError,
)
from screenshot_crawler.core.models import AccessStrategy, ContentContext, ContentIdentity
from screenshot_crawler.core.state import PageState
from screenshot_crawler.discovery.service import DiscoveryIncompleteError
from screenshot_crawler.site_adapters.base import SiteAdapter
from screenshot_crawler.site_adapters.younganimal.access import (
    YOUNGANIMAL_RELEVANT_HOSTS,
    younganimal_access_profile,
)
from screenshot_crawler.site_adapters.younganimal.capture import (
    COLLECT_CAPTURE_SCRIPT,
    MAX_PNG_BYTES,
    OBSERVER_INIT_SCRIPT,
    SNAPSHOT_SCRIPT,
    ViewerObservation,
    _parse_viewer_observation,
    decode_capture_results,
)
from screenshot_crawler.site_adapters.younganimal.discovery import (
    MAX_RANGE_PAGES,
    YounganimalRange,
    _parse_range_links,
    _read_range_entries,
    _read_range_rows,
    _read_series_title,
    _validate_page_ranges,
    canonical_younganimal_episode_url,
    classify_younganimal_access,
    parse_younganimal_episode_url,
    parse_younganimal_work_url,
)
from screenshot_crawler.site_adapters.younganimal.native_capture import (
    COLLECT_CAPTURE_SCRIPT as COLLECT_NATIVE_CAPTURE_SCRIPT,
)
from screenshot_crawler.site_adapters.younganimal.native_capture import (
    MAX_IMAGE_BYTES as MAX_NATIVE_IMAGE_BYTES,
)
from screenshot_crawler.site_adapters.younganimal.native_capture import (
    OBSERVER_INIT_SCRIPT as NATIVE_OBSERVER_INIT_SCRIPT,
)
from screenshot_crawler.site_adapters.younganimal.native_capture import (
    RELEASE_CAPTURE_SCRIPT as RELEASE_NATIVE_CAPTURE_SCRIPT,
)
from screenshot_crawler.site_adapters.younganimal.native_capture import (
    VERIFY_CAPTURE_SCRIPT as VERIFY_NATIVE_CAPTURE_SCRIPT,
)
from screenshot_crawler.site_adapters.younganimal.native_capture import (
    decode_native_images,
    encode_native_webp,
)

BASE_URL = "https://younganimal.com"
WORK_LINK_SELECTOR = "#xHeader a.ep-h-main-h-series"
LISTING_SELECTOR = ".series-eplist-main"
SEEK_SELECTOR = "#xCVSeekBar"

NAVIGATION_TIMEOUT_MS = 15_000
LISTING_TIMEOUT_MS = 12_000
OBSERVATION_TIMEOUT_SECONDS = 4.0
INITIALIZE_TIMEOUT_MS = 240_000
VIEWER_READY_TIMEOUT_MS = 20_000
VIEWER_READY_POLL_MS = 250
INITIAL_QUIET_MS = 1_000
INITIAL_QUIET_DEADLINE_MS = 5_000
INITIAL_QUIET_POLL_MS = 100
PAGE_CHANGE_TIMEOUT_MS = 12_000
PAGE_CHANGE_POLL_MS = 100
MANUAL_RANGE_PACING_MS = 3_000
MAX_CAPTURE_TOTAL_BYTES = 16_000_000
EXTERNAL_ID_PATTERN = re.compile(
    r"^(?P<work>[0-9a-f]{13}):(?P<episode>[0-9a-f]{13})$"
)
_NATIVE_VERIFY_REASONS = frozenset(
    {
        "native_proof_missing",
        "native_reader_identity_changed",
        "native_reader_layout_changed",
        "native_proof_incomplete",
        "native_target_replaced",
        "native_target_generation_or_write_changed",
        "native_target_dimensions_changed",
        "native_target_layout_changed",
        "native_target_readiness_changed",
        "native_target_pixels_changed",
        "native_snapshot_identity_changed",
        "native_postproof_unavailable",
    }
)
_NATIVE_SAFE_CLASS_FLAGS = frozenset(
    {
        "-cv", "-cv-page", "-cv-page-canvas", "-cv-splash", "mode-ci-page", "mode-dir-rtl",
        "mode-empty", "mode-first-page", "mode-good", "mode-h", "mode-has-top-emptypage",
        "mode-hide", "mode-last", "mode-last-page", "mode-lang-ja", "mode-loaded",
        "mode-loading", "mode-nav-dir-rtl", "mode-nav-open", "mode-pr", "mode-req-render",
        "mode-pr-page", "mode-rendered", "mode-scroll-bottom", "mode-spread", "mode-top-pr", "mode-top-pr-page", "mode-ci",
    }
)


def _native_failure_reason(value: object) -> str:
    return value if isinstance(value, str) and value in _NATIVE_VERIFY_REASONS else "unrecognized_native_verification_failure"


def _native_failure_details(value: object) -> dict[str, object]:
    """Keep browser-provided proof diagnostics typed, bounded, and non-content-bearing."""
    if not isinstance(value, dict):
        return {"available": False}

    def integer(item: object) -> int | None:
        return item if type(item) is int and 0 <= item <= 2**53 - 1 else None

    def number(item: object) -> int | float | None:
        if type(item) not in {int, float} or not math.isfinite(item):
            return None
        return item

    def rect(item: object) -> list[int | float] | None:
        if not isinstance(item, list) or len(item) != 4:
            return None
        result = [number(part) for part in item]
        return result if all(part is not None for part in result) else None

    def slots(item: object) -> list[int] | None:
        if not isinstance(item, list) or len(item) > 2 or any(type(slot) is not int or slot < 0 for slot in item):
            return None
        return list(item)

    def viewport(item: object) -> dict[str, int | float | None] | None:
        if not isinstance(item, dict):
            return None
        return {name: number(item.get(name)) for name in ("width", "height", "dpr")}

    def selected_row(item: object) -> dict[str, object] | None:
        if not isinstance(item, dict):
            return None
        bool_fields = (
            "wrapperSame", "targetSame", "holderSame", "rectsSame", "ready", "visible",
            "centerInViewport", "readbackAvailable", "contextMatches", "pixelsMatchProof", "replayMatchesProof",
            "generationMatches", "writesMatch",
        )
        result: dict[str, object] = {
            "slot": integer(item.get("slot")),
            "currentPhysicalSlot": integer(item.get("currentPhysicalSlot")),
            "generation": integer(item.get("generation")),
            "writes": integer(item.get("writes")),
            "proofGeneration": integer(item.get("proofGeneration")),
            "proofWrites": integer(item.get("proofWrites")),
            "width": integer(item.get("width")),
            "height": integer(item.get("height")),
            "proofWidth": integer(item.get("proofWidth")),
            "proofHeight": integer(item.get("proofHeight")),
            "targetRect": rect(item.get("targetRect")),
            "wrapperRect": rect(item.get("wrapperRect")),
            "proofTargetRect": rect(item.get("proofTargetRect")),
            "proofWrapperRect": rect(item.get("proofWrapperRect")),
        }
        readback_available = item.get("readbackAvailable") is True
        result.update({
            name: item.get(name) if type(item.get(name)) is bool else None
            for name in bool_fields
            if name not in {"contextMatches", "pixelsMatchProof", "replayMatchesProof"} or readback_available
        })
        if not readback_available:
            result.update({"contextMatches": None, "pixelsMatchProof": None, "replayMatchesProof": None})
        return result

    def mutation_node(item: object) -> dict[str, object] | None:
        if not isinstance(item, dict):
            return None
        tag = item.get("tag")
        area = item.get("area")
        return {
            "node": integer(item.get("node")),
            "area": area if isinstance(area, str) and area in {
                "viewer", "pages", "seek", "wrapper", "wrapper_descendant",
                "pages_descendant", "viewer_descendant"
            } else "unknown",
            "slot": integer(item.get("slot")),
            "tag": tag if isinstance(tag, str) and tag in {
                "CANVAS", "DIV", "INPUT", "SECTION", "SPAN", "SVG", "OTHER"
            } else "OTHER",
            "classFlags": [flag for flag in item.get("classFlags", [])
                           if isinstance(flag, str) and flag in _NATIVE_SAFE_CLASS_FLAGS][:24]
            if isinstance(item.get("classFlags"), list) else [],
        }

    def mutation_record(item: object) -> dict[str, object] | None:
        if not isinstance(item, dict):
            return None
        kind = item.get("kind")
        attribute = item.get("attributeName")
        target_area = item.get("targetArea")
        def nodes(name: str) -> list[dict[str, object]]:
            raw_nodes = item.get(name)
            if not isinstance(raw_nodes, list):
                return []
            return [node for raw_node in raw_nodes[:4] if (node := mutation_node(raw_node)) is not None]
        return {
            "generation": integer(item.get("generation")),
            "captureGeneration": integer(item.get("captureGeneration")),
            "kind": kind if isinstance(kind, str) and kind in {"attributes", "childList"} else "unknown",
            "targetArea": target_area if isinstance(target_area, str) and target_area in {
                "viewer", "pages", "seek", "wrapper", "wrapper_descendant",
                "pages_descendant", "viewer_descendant"
            } else "unknown",
            "targetNode": integer(item.get("targetNode")),
            "slot": integer(item.get("slot")),
            "attributeName": attribute if isinstance(attribute, str) and attribute in {"class", "id", "other"} else "other",
            "namespacePresent": item.get("namespacePresent") is True,
            "changed": item.get("changed") if type(item.get("changed")) is bool else None,
            "sameAssignment": item.get("sameAssignment") if type(item.get("sameAssignment")) is bool else None,
            "canonicalCiWrapper": item.get("canonicalCiWrapper")
            if type(item.get("canonicalCiWrapper")) is bool else None,
            "ciScrollWidgetTarget": item.get("ciScrollWidgetTarget")
            if type(item.get("ciScrollWidgetTarget")) is bool else None,
            "classTokenSetsSame": item.get("classTokenSetsSame")
            if type(item.get("classTokenSetsSame")) is bool else None,
            "canonicalCiClassNoop": item.get("canonicalCiClassNoop")
            if type(item.get("canonicalCiClassNoop")) is bool else None,
            "ciScrollWidgetClassNoop": item.get("ciScrollWidgetClassNoop")
            if type(item.get("ciScrollWidgetClassNoop")) is bool else None,
            "classAdded": [flag for flag in item.get("classAdded", [])
                           if isinstance(flag, str) and flag in _NATIVE_SAFE_CLASS_FLAGS][:24]
            if isinstance(item.get("classAdded"), list) else [],
            "classRemoved": [flag for flag in item.get("classRemoved", [])
                             if isinstance(flag, str) and flag in _NATIVE_SAFE_CLASS_FLAGS][:24]
            if isinstance(item.get("classRemoved"), list) else [],
            "addedCount": integer(item.get("addedCount")),
            "removedCount": integer(item.get("removedCount")),
            "added": nodes("added"),
            "removed": nodes("removed"),
        }

    def section(name: str) -> dict[str, object]:
        raw_section = value.get(name)
        if not isinstance(raw_section, dict):
            return {}
        raw_path = raw_section.get("path")
        safe_path = raw_path if isinstance(raw_path, str) and re.fullmatch(r"/episodes/[0-9a-f]{13}", raw_path) else "<changed>"
        return {
            "path": safe_path,
            "seekValue": integer(raw_section.get("seekValue")),
            "domGeneration": integer(raw_section.get("domGeneration")),
            "captureDomGeneration": integer(raw_section.get("captureDomGeneration")),
            "wrapperCount": integer(raw_section.get("wrapperCount")),
            "activeSlots": slots(raw_section.get("activeSlots")),
            "viewport": viewport(raw_section.get("viewport")),
            "layoutAvailable": raw_section.get("layoutAvailable")
            if type(raw_section.get("layoutAvailable")) is bool else None,
            "queryPresent": raw_section.get("queryPresent")
            if type(raw_section.get("queryPresent")) is bool else None,
            "hashPresent": raw_section.get("hashPresent")
            if type(raw_section.get("hashPresent")) is bool else None,
            "viewerIdentity": raw_section.get("viewerIdentity") if type(raw_section.get("viewerIdentity")) is bool else None,
            "pagesIdentity": raw_section.get("pagesIdentity") if type(raw_section.get("pagesIdentity")) is bool else None,
            "seekIdentity": raw_section.get("seekIdentity") if type(raw_section.get("seekIdentity")) is bool else None,
        }

    mutation_value = value.get("mutations")
    if isinstance(mutation_value, dict):
        raw_records = mutation_value.get("records")
        if not isinstance(raw_records, list):
            raw_records = []
        records = [record for raw_record in raw_records[:64] if (record := mutation_record(raw_record)) is not None]
        mutations: dict[str, object] = {
            "available": mutation_value.get("available") is True,
            "complete": mutation_value.get("complete") is True,
            "coverageContiguous": mutation_value.get("coverageContiguous") is True,
            "fromGeneration": integer(mutation_value.get("fromGeneration")),
            "toGeneration": integer(mutation_value.get("toGeneration")),
            "droppedCount": integer(mutation_value.get("droppedCount")),
            "unrecordedCount": integer(mutation_value.get("unrecordedCount")),
            "records": records,
        }
    else:
        mutations = {"available": False, "complete": False, "records": []}
    raw_selected = value.get("selected")
    selected = [row for raw_row in raw_selected[:2] if (row := selected_row(raw_row)) is not None] if isinstance(raw_selected, list) else []
    return {
        "available": True,
        "expected": section("expected"),
        "observed": section("observed"),
        "selected": selected,
        "mutations": mutations,
    }

EPISODE_SCOPE_SCRIPT = r"""({episodeUrl, workUrl}) => {
  const mains = [...document.querySelectorAll('.series-eplist-main')];
  const headers = [...document.querySelectorAll('#xHeader a.ep-h-main-h-series')];
  const publicRoots = mains.length === 1
    ? [...mains[0].querySelectorAll('.series-eplist[data-e2e="epList"]')] : [];
  const userRoots = mains.length === 1
    ? [...mains[0].querySelectorAll('.series-eplist[data-e2e="epListUser"]')] : [];
  const allRoots = [...document.querySelectorAll('.series-eplist')];
  const publicRows = publicRoots.length === 1
    ? [...publicRoots[0].querySelectorAll('.series-eplist-item')] : [];
  const userRows = userRoots.flatMap(root => [...root.querySelectorAll('.series-eplist-item')]);
  const allRows = [...document.querySelectorAll('.series-eplist-item')];
  const candidates = publicRows.filter(row =>
    [...row.querySelectorAll('a[href*="/episodes/"]')].some(link => link.href === episodeUrl));
  const row = candidates.length === 1 ? candidates[0] : null;
  const links = row ? [...row.querySelectorAll('a[href*="/episodes/"]')] : [];
  const titles = row ? [...row.querySelectorAll('.series-eplist-item-h-text')] : [];
  const labels = row ? [...row.querySelectorAll('.series-eplist-item-access-text')] : [];
  const structureReady = mains.length === 1 && headers.length === 1 &&
    headers[0].href === workUrl && publicRoots.length === 1 &&
    publicRoots[0].parentElement === mains[0] && userRoots.length <= 1 &&
    allRoots.length === publicRoots.length + userRoots.length &&
    userRoots.every(root => root.parentElement === mains[0] && root.classList.contains('mode-user')) &&
    allRows.length === publicRows.length + userRows.length &&
    allRows.every(candidate => publicRows.includes(candidate) || userRows.includes(candidate));
  return {
    route: location.href,
    path: location.pathname,
    title: document.title,
    headingCount: [...document.querySelectorAll('h1')].filter(node => (node.innerText || '').trim()).length,
    workLinkCount: headers.length,
    workHref: headers.length === 1 ? headers[0].href : null,
    workTitle: headers.length === 1
      ? (headers[0].innerText || '').replace(/\s+/g, ' ').trim() : null,
    structureReady,
    publicRowCount: publicRows.length,
    userRowCount: userRows.length,
    targetRowCount: candidates.length,
    targetRouteCount: links.length,
    rawTargetHref: links.length === 1 ? links[0].getAttribute('href') : null,
    targetTitleCount: titles.length,
    targetTitle: titles.length === 1 ? (titles[0].innerText || '').replace(/\s+/g, ' ').trim() : null,
    labels: labels.map(node => (node.innerText || '').replace(/\s+/g, ' ').trim()),
  };
}"""


def _safe_path(url: str) -> str:
    try:
        return urlsplit(url).path
    except ValueError:
        return ""


class YounganimalAdapter(SiteAdapter):
    """Capture only exact-free episodes proven through a configured work listing."""

    page_change_timeout_ms = PAGE_CHANGE_TIMEOUT_MS

    def __init__(self, preflight_work_url: str | None = None) -> None:
        self._preflight_work_url = preflight_work_url
        self._batch_expected_work_id: str | None = None
        self._batch_expected_episode_id: str | None = None
        self._opaque_work_key: str | None = None
        self._work_id: str | None = None
        self._work_title: str | None = None
        self._target_url: str | None = None
        self._episode_id: str | None = None
        self._episode_title: str | None = None
        self._target_position: int | None = None
        self._body_slots: tuple[int, ...] | None = None
        self._ci_slot: int | None = None
        self._frozen_viewer_mapping: tuple[object, ...] | None = None
        self._rendered_dimensions: tuple[int, int] | None = None
        self._captured_slots: list[int] = []
        self._last_capture_slots: tuple[int, ...] = ()
        self._pending: tuple[str, int, tuple[int, ...]] | None = None
        self._ended = False
        self._native_cleanup_expected: tuple[int, ...] = ()
        self._native_cleanup_token: str | None = None
        self._capture_diagnostics: dict[str, Any] = {"mode": "not_started"}
        self._initial_canvas_quiet: dict[str, object] | None = None
        self._access_stop: dict[str, object] | None = None
        self._response_listener = None

    def get_access_profile(self) -> AccessProfile:
        return younganimal_access_profile()

    def get_initialize_timeout_ms(self, default_ms: int) -> int:
        return max(default_ms, INITIALIZE_TIMEOUT_MS)

    async def prepare_page(self, page: Page) -> None:
        try:
            await page.add_init_script(OBSERVER_INIT_SCRIPT + ";\n" + NATIVE_OBSERVER_INIT_SCRIPT)
        except PlaywrightError as exc:
            raise UnknownPageStateError("Younganimal canvas observer could not be installed") from exc

        def record_access_stop(response) -> None:
            if self._access_stop is not None:
                return
            try:
                host = (urlsplit(response.url).hostname or "").lower()
                status = response.status
                if host in YOUNGANIMAL_RELEVANT_HOSTS and status in {403, 429}:
                    self._access_stop = {
                        "host": host,
                        "path": _safe_path(response.url),
                        "status": status,
                    }
            except (AttributeError, PlaywrightError, ValueError):
                return

        self._response_listener = record_access_stop
        page.on("response", record_access_stop)

    async def configure_run(self, page: Page, access_strategy: AccessStrategy) -> None:
        del page
        if self._batch_expected_work_id is not None:
            if access_strategy != "direct":
                raise UnsupportedAccessStrategyError(
                    "Younganimal configured Batch currently supports access_strategy='direct' only"
                )
            return
        if access_strategy != "auto":
            raise UnsupportedAccessStrategyError(
                "Younganimal manual free crawl currently supports access_strategy='auto' only"
            )

    async def configure_target_identity(self, external_id: str, work_key: str) -> None:
        match = EXTERNAL_ID_PATTERN.fullmatch(external_id)
        if match is None or not isinstance(work_key, str) or not work_key.strip():
            raise UnknownPageStateError("Younganimal Batch target identity is malformed")
        self._batch_expected_work_id = match.group("work")
        self._batch_expected_episode_id = match.group("episode")
        self._opaque_work_key = work_key

    def resolve_initial_navigation_url(self, source_url: str) -> str:
        episode = parse_younganimal_episode_url(source_url)
        if episode is None or canonical_younganimal_episode_url(source_url) != source_url:
            raise UnknownPageStateError("Younganimal requires an exact canonical episode URL")
        if self._batch_expected_work_id is not None:
            if (
                self._batch_expected_episode_id is None
                or self._opaque_work_key is None
                or episode.episode_id != self._batch_expected_episode_id
            ):
                raise UnknownPageStateError(
                    "Younganimal episode URL differs from the configured Catalog target"
                )
            self._episode_id = episode.episode_id
            self._target_url = source_url
            self._work_id = self._batch_expected_work_id
            return self._target_url
        work_id = parse_younganimal_work_url(self._preflight_work_url or "")
        if work_id is None or self._preflight_work_url != f"{BASE_URL}/series/{work_id}":
            raise UnknownPageStateError(
                "Younganimal requires YOUNGANIMAL_WORK_URL as a canonical public series listing"
            )
        self._episode_id = episode.episode_id
        self._target_url = source_url
        self._work_id = work_id
        return self._preflight_work_url

    async def initialize(self, page: Page) -> None:
        if self._work_id is None or self._target_url is None or self._episode_id is None:
            raise UnknownPageStateError("Younganimal crawl target was not validated before navigation")
        direct_batch = self._batch_expected_work_id is not None
        expected_initial_url = self._target_url if direct_batch else f"{BASE_URL}/series/{self._work_id}"
        if page.url != expected_initial_url:
            raise UnknownPageStateError("Younganimal initial navigation left its configured entry route")
        self._work_title = None
        self._episode_title = None
        self._target_position = None
        self._body_slots = None
        self._ci_slot = None
        self._frozen_viewer_mapping = None
        self._rendered_dimensions = None
        self._captured_slots = []
        self._last_capture_slots = ()
        self._pending = None
        self._ended = False
        self._native_cleanup_expected = ()
        self._native_cleanup_token = None
        self._capture_diagnostics = {"mode": "not_started"}
        self._initial_canvas_quiet = None
        if not direct_batch:
            await self._find_exact_free_target(page)
            await self._navigate_episode(page)
        await self._verify_episode_entry(page)
        observation = await self._wait_for_viewer_ready(page)
        self._frozen_viewer_mapping = self._viewer_mapping(observation)
        self._body_slots = observation.body_slots
        self._ci_slot = observation.ci_slot
        if observation.seek_value != observation.seek_max:
            observation = await self._rewind_to_first_body(page, observation)
        if observation.initial_blank:
            first_seek = observation.seek_value - observation.seek_step
            await self._set_public_seek_value(page, first_seek)
            first_slots = tuple(self._body_slots[:2])
            first = await self._wait_for_observation(
                page,
                lambda row: row.layout_variant == observation.layout_variant
                and row.page_state == "content"
                and row.seek_value == first_seek
                and row.active_slots == first_slots
                and row.ready_slots == first_slots,
                reason="Younganimal top-empty initial blank did not advance to its first body spread",
                timeout_ms=PAGE_CHANGE_TIMEOUT_MS,
                include_pixels=True,
            )
        else:
            first_slots = (self._body_slots[0],)
            first = await self._wait_for_observation(
                page,
                lambda row: row.page_state == "content"
                and row.seek_value == row.seek_max
                and row.active_slots == first_slots
                and row.ready_slots == row.active_slots,
                reason="Younganimal viewer did not return to its first rendered body canvas",
                timeout_ms=PAGE_CHANGE_TIMEOUT_MS,
                include_pixels=True,
            )
        await self._wait_for_initial_quiet(page, first)
        first_canvas = first.raw["slots"][first.active_slots[0]]["canvas"]
        if not isinstance(first_canvas, dict):
            raise UnknownPageStateError("Younganimal first body canvas disappeared after quiet wait")
        self._rendered_dimensions = (first_canvas["width"], first_canvas["height"])

    async def _find_exact_free_target(self, page: Page) -> None:
        work_id = self._work_id
        episode_id = self._episode_id
        if work_id is None or episode_id is None:
            raise UnknownPageStateError("Younganimal work or episode identity is missing")
        work_url = f"{BASE_URL}/series/{work_id}"
        deadline = time.monotonic() + 220
        try:
            await page.locator(LISTING_SELECTOR).wait_for(
                state="visible", timeout=LISTING_TIMEOUT_MS
            )
            title = await _read_series_title(page)
            entries = await _read_range_entries(page)
            ranges = _parse_range_links(entries, work_id=work_id)
        except (DiscoveryIncompleteError, PlaywrightError, PlaywrightTimeoutError) as exc:
            raise UnknownPageStateError("Younganimal canonical work listing is incomplete") from exc
        if page.url != work_url:
            raise UnknownPageStateError("Younganimal canonical work listing route changed")
        if not title or len(ranges) > MAX_RANGE_PAGES:
            raise UnknownPageStateError("Younganimal work title or range map is invalid")

        for episode_range in ranges:
            self._raise_if_access_stopped()
            await page.wait_for_timeout(MANUAL_RANGE_PACING_MS)
            self._raise_if_access_stopped()
            if time.monotonic() >= deadline:
                raise PageChangeTimeoutError("Younganimal target lookup exceeded its bounded work budget")
            response = await self._navigate_listing_range(page, episode_range, work_url)
            self._require_http_200(response, "range listing")
            try:
                await page.locator(LISTING_SELECTOR).wait_for(
                    state="visible", timeout=LISTING_TIMEOUT_MS
                )
                current_title = await _read_series_title(page)
                entries = await _read_range_entries(page)
                _validate_page_ranges(
                    entries,
                    work_id=work_id,
                    ranges=ranges,
                    selected=episode_range,
                )
                rows = await _read_range_rows(
                    page,
                    work_id=work_id,
                    first_position=episode_range.start_position,
                )
            except (DiscoveryIncompleteError, PlaywrightError, PlaywrightTimeoutError) as exc:
                raise UnknownPageStateError("Younganimal target range failed strict validation") from exc
            self._raise_if_access_stopped()
            if current_title != title:
                raise UnknownPageStateError("Younganimal target range belongs to a different work title")
            expected_count = episode_range.end_position - episode_range.start_position + 1
            if len(rows) != expected_count:
                raise UnknownPageStateError("Younganimal target range row count is incomplete")
            matches = [row for row in rows if row.identity.episode_id == episode_id]
            if not matches:
                continue
            if len(matches) != 1 or matches[0].identity.work_id != work_id:
                raise UnknownPageStateError("Younganimal target episode identity is duplicated or foreign")
            row = matches[0]
            if (
                row.access.access_mode != "free"
                or classify_younganimal_access(row.access.raw_labels).access_mode != "free"
            ):
                raise UnknownPageStateError("Younganimal target row lacks one exact free label")
            self._work_title = title
            self._target_position = row.global_position
            return
        raise UnknownPageStateError("Younganimal target episode is absent from the validated public ranges")

    async def _navigate_listing_range(
        self, page: Page, episode_range: YounganimalRange, work_url: str
    ):
        try:
            response = await page.goto(
                episode_range.url,
                wait_until="commit",
                timeout=NAVIGATION_TIMEOUT_MS,
            )
        except (PlaywrightError, PlaywrightTimeoutError) as exc:
            self._raise_if_access_stopped()
            raise PageChangeTimeoutError(
                f"Younganimal range navigation failed at {episode_range.path}"
            ) from exc
        self._raise_if_access_stopped()
        if page.url != episode_range.url and not (
            episode_range.page_number == 1 and page.url == work_url
        ):
            raise UnknownPageStateError("Younganimal numeric range redirected outside its exact route")
        return response

    async def _navigate_episode(self, page: Page) -> None:
        target_url = self._target_url
        if target_url is None:
            raise UnknownPageStateError("Younganimal episode target URL is missing")
        self._raise_if_access_stopped()
        await page.wait_for_timeout(MANUAL_RANGE_PACING_MS)
        self._raise_if_access_stopped()
        try:
            response = await page.goto(
                target_url,
                wait_until="commit",
                timeout=NAVIGATION_TIMEOUT_MS,
            )
        except (PlaywrightError, PlaywrightTimeoutError) as exc:
            self._raise_if_access_stopped()
            raise PageChangeTimeoutError("Younganimal exact free episode navigation failed") from exc
        self._raise_if_access_stopped()
        self._require_http_200(response, "episode document")
        if page.url != target_url:
            raise UnknownPageStateError("Younganimal episode document changed its exact route")

    @staticmethod
    def _require_http_200(response, label: str) -> None:
        if response is None:
            raise UnknownPageStateError(f"Younganimal {label} has no document response")
        status = getattr(response, "status", None)
        if status in {403, 429}:
            raise UnknownPageStateError(f"Younganimal {label} stopped at HTTP {status}")
        if status != 200:
            raise UnknownPageStateError(f"Younganimal {label} did not return HTTP 200")

    def _raise_if_access_stopped(self) -> None:
        if self._access_stop is not None:
            stop = self._access_stop
            raise UnknownPageStateError(
                "Younganimal AccessGuard-relevant response stopped the crawl "
                f"(status={stop.get('status')}, host={stop.get('host')}, path={stop.get('path')})"
            )

    async def _verify_episode_entry(self, page: Page) -> None:
        target_url = self._target_url
        work_id = self._work_id
        if target_url is None or work_id is None or page.url != target_url:
            raise UnknownPageStateError("Younganimal entry route differs from the exact target episode")
        work_url = f"{BASE_URL}/series/{work_id}"
        try:
            await page.locator(LISTING_SELECTOR).wait_for(
                state="visible", timeout=LISTING_TIMEOUT_MS
            )
            raw = await asyncio.wait_for(
                page.evaluate(EPISODE_SCOPE_SCRIPT, {"episodeUrl": target_url, "workUrl": work_url}),
                timeout=OBSERVATION_TIMEOUT_SECONDS,
            )
        except (PlaywrightError, TimeoutError) as exc:
            self._raise_if_access_stopped()
            raise UnknownPageStateError("Younganimal episode access row could not be verified") from exc
        self._raise_if_access_stopped()
        episode = parse_younganimal_episode_url(target_url)
        if (
            not isinstance(raw, dict)
            or episode is None
            or raw.get("route") != target_url
            or raw.get("path") != f"/episodes/{episode.episode_id}"
            or raw.get("structureReady") is not True
            or raw.get("workLinkCount") != 1
            or raw.get("workHref") != work_url
            or not isinstance(raw.get("workTitle"), str)
            or not raw["workTitle"].strip()
            or raw.get("userRowCount") != 0
            or raw.get("targetRowCount") != 1
            or raw.get("targetRouteCount") != 1
            or raw.get("rawTargetHref") != f"/episodes/{episode.episode_id}"
            or raw.get("targetTitleCount") != 1
            or not isinstance(raw.get("targetTitle"), str)
            or not raw["targetTitle"].strip()
            or raw.get("labels") != ["無料"]
            or classify_younganimal_access(raw["labels"]).access_mode != "free"
        ):
            raise UnknownPageStateError("Younganimal fresh episode listing does not prove exact free access")
        if self._work_title is not None and raw["workTitle"] != self._work_title:
            raise UnknownPageStateError("Younganimal episode work title differs from its verified listing")
        self._work_title = raw["workTitle"]
        self._episode_title = raw["targetTitle"]

    async def _wait_for_viewer_ready(self, page: Page) -> ViewerObservation:
        deadline = time.monotonic() + VIEWER_READY_TIMEOUT_MS / 1000
        previous_signature: tuple[object, ...] | None = None
        last_error: BaseException | None = None
        stable_pair: tuple[object, ...] | None = None
        while time.monotonic() < deadline:
            self._raise_if_access_stopped()
            if page.url != self._target_url:
                raise UnknownPageStateError("Younganimal viewer navigated away during initialization")
            try:
                observation = await self._observe(page)
            except UnknownPageStateError as exc:
                last_error = exc
                previous_signature = None
            else:
                signature = self._layout_signature(observation)
                if signature == previous_signature:
                    stable_pair = signature
                    return observation
                previous_signature = signature
            remaining = deadline - time.monotonic()
            if remaining > 0:
                await page.wait_for_timeout(min(VIEWER_READY_POLL_MS, max(1, int(remaining * 1000))))
        self._capture_diagnostics["viewer_readiness"] = {
            "status": "timeout",
            "stable_layout": stable_pair is not None,
            "last_error": type(last_error).__name__ if last_error else None,
        }
        raise PageChangeTimeoutError("Younganimal viewer did not expose a stable known layout within 20 seconds")

    async def _rewind_to_first_body(
        self, page: Page, observation: ViewerObservation
    ) -> ViewerObservation:
        seek = page.locator(SEEK_SELECTOR)
        try:
            await asyncio.wait_for(seek.focus(timeout=1_500), timeout=2.0)
            await asyncio.wait_for(seek.press("End", timeout=1_500), timeout=2.0)
        except (PlaywrightError, TimeoutError) as exc:
            raise UnknownPageStateError("Younganimal public seek could not rewind to maximum") from exc
        if observation.layout_variant == "top_emptypage":
            predicate = lambda row: (
                row.page_state == "initial_blank"
                and row.layout_variant == observation.layout_variant
                and row.seek_value == observation.seek_max
            )
        else:
            predicate = lambda row: (
                row.page_state == "content"
                and row.seek_value == observation.seek_max
                and row.active_slots == (row.body_slots[0],)
                and row.ready_slots == row.active_slots
            )
        return await self._wait_for_observation(
            page,
            predicate,
            reason="Younganimal public seek did not restore its first body page",
            timeout_ms=PAGE_CHANGE_TIMEOUT_MS,
            include_pixels=True,
        )

    async def _wait_for_initial_quiet(
        self, page: Page, initial: ViewerObservation
    ) -> None:
        expected = initial.active_slots
        started = time.monotonic()
        deadline = started + INITIAL_QUIET_DEADLINE_MS / 1000
        quiet_since: float | None = None
        previous: tuple[object, ...] | None = None
        last: ViewerObservation | None = None
        last_ui_settled = False
        while time.monotonic() < deadline:
            self._raise_if_access_stopped()
            observation = await self._observe(page, pixel_slots=expected)
            last = observation
            nav_open = observation.raw.get("viewerNavOpen")
            splash_count = observation.raw.get("viewerSplashCount")
            if type(nav_open) is not bool or type(splash_count) is not int or splash_count < 0:
                self._capture_diagnostics["initial_canvas_quiet"] = {
                    "status": "unknown_ui_state",
                    "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
                    "viewer_nav_open_type": type(nav_open).__name__,
                    "viewer_splash_count_type": type(splash_count).__name__,
                }
                self._initial_canvas_quiet = dict(self._capture_diagnostics["initial_canvas_quiet"])
                raise UnknownPageStateError(
                    "Younganimal initial navigation or splash state is unknown"
                )
            ui_settled = not nav_open and splash_count == 0
            last_ui_settled = ui_settled
            if self._canvas_identity_signature(observation, expected) != self._canvas_identity_signature(
                initial, expected
            ):
                raise UnknownPageStateError(
                    "Younganimal first canvas or wrapper identity/dimensions changed before quiet settle"
                )
            if any(
                observation.raw["slots"][index]["canvas"].get("pixelError")
                for index in expected
            ):
                raise UnknownPageStateError("Younganimal first rendered canvas pixels are unreadable")
            ready = (
                observation.page_state == "content"
                and observation.seek_value == initial.seek_value
                and observation.active_slots == expected
                and observation.ready_slots == expected
                and ui_settled
                and all(
                    observation.raw["slots"][index]["canvas"].get("pixels")
                    and not observation.raw["slots"][index]["canvas"].get("pixelError")
                    for index in expected
                )
            )
            signature = self._canvas_quiet_signature(observation, expected) if ready else None
            now = time.monotonic()
            if signature is None or signature != previous:
                quiet_since = now if ready else None
            if ready and quiet_since is not None and (now - quiet_since) * 1000 >= INITIAL_QUIET_MS:
                self._capture_diagnostics["initial_canvas_quiet"] = {
                    "status": "settled",
                    "quiet_ms": INITIAL_QUIET_MS,
                    "elapsed_ms": round((now - started) * 1000, 2),
                    "slots": list(expected),
                    "identity": [
                        observation.raw["slots"][index]["canvas"]["node"]
                        for index in expected
                    ],
                    "pixel_fingerprints": [
                        observation.raw["slots"][index]["canvas"]["pixels"]
                        for index in expected
                    ],
                    "dom_generation": observation.raw.get("domGeneration"),
                    "capture_dom_generation": observation.raw.get("captureDomGeneration"),
                    "viewer_nav_open": nav_open,
                    "viewer_splash_count": splash_count,
                }
                self._initial_canvas_quiet = dict(self._capture_diagnostics["initial_canvas_quiet"])
                return
            previous = signature
            remaining = deadline - time.monotonic()
            if remaining > 0:
                await page.wait_for_timeout(min(INITIAL_QUIET_POLL_MS, max(1, int(remaining * 1000))))
        self._capture_diagnostics["initial_canvas_quiet"] = {
            "status": "timeout",
            "quiet_ms": INITIAL_QUIET_MS,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
            "last_seek": last.seek_value if last else None,
            "viewer_nav_open": last.raw.get("viewerNavOpen") if last else None,
            "viewer_splash_count": last.raw.get("viewerSplashCount") if last else None,
        }
        self._initial_canvas_quiet = dict(self._capture_diagnostics["initial_canvas_quiet"])
        if not last_ui_settled:
            raise UnknownPageStateError(
                "Younganimal navigation or splash UI did not settle within its 5 second bound"
            )
        raise PageChangeTimeoutError("Younganimal first rendered canvas did not settle within its 5 second bound")

    async def _observe(
        self, page: Page, *, pixel_slots: tuple[int, ...] = ()
    ) -> ViewerObservation:
        target_url = self._target_url
        if target_url is None or page.url != target_url:
            raise UnknownPageStateError("Younganimal viewer route no longer matches its episode")
        try:
            result = await asyncio.wait_for(
                page.evaluate(SNAPSHOT_SCRIPT, {"pixelSlots": list(pixel_slots)}),
                timeout=OBSERVATION_TIMEOUT_SECONDS,
            )
        except (PlaywrightError, TimeoutError) as exc:
            raise UnknownPageStateError("Younganimal viewer snapshot exceeded its bound") from exc
        if not isinstance(result, dict) or result.get("observerReady") is not True:
            raise UnknownPageStateError("Younganimal viewer integrity observer is missing")
        raw = result.get("snapshot")
        observation = _parse_viewer_observation(raw, expected_url=target_url)
        self._require_frozen_viewer_mapping(observation)
        return observation

    @staticmethod
    def _viewer_mapping(observation: ViewerObservation) -> tuple[object, ...]:
        return (
            observation.body_slots,
            observation.ci_slot,
            observation.layout_variant,
            observation.seek_min,
            observation.seek_max,
            observation.seek_step,
        )

    def _require_frozen_viewer_mapping(self, observation: ViewerObservation) -> None:
        frozen = self._frozen_viewer_mapping
        if frozen is not None and self._viewer_mapping(observation) != frozen:
            raise UnknownPageStateError(
                "Younganimal frozen body/tail roles, layout variant, or seek range changed"
            )

    @staticmethod
    def _layout_signature(observation: ViewerObservation) -> tuple[object, ...]:
        raw = observation.raw
        return (
            raw.get("viewerNode"),
            raw.get("pagesNode"),
            raw.get("seekNode"),
            observation.seek_min,
            observation.seek_max,
            observation.seek_step,
            observation.body_slots,
            observation.ci_slot,
            observation.layout_variant,
            tuple(slot.get("wrapperNode") for slot in raw["slots"]),
        )

    @staticmethod
    def _canvas_quiet_signature(
        observation: ViewerObservation, slots: tuple[int, ...]
    ) -> tuple[object, ...]:
        raw = observation.raw
        return (
            YounganimalAdapter._viewer_mapping(observation),
            observation.seek_value,
            raw.get("viewerNode"),
            raw.get("pagesNode"),
            raw.get("seekNode"),
            raw.get("captureDomGeneration"),
            raw.get("viewport"),
            tuple(
                (
                    raw["slots"][index].get("wrapperNode"),
                    tuple(raw["slots"][index].get("classes", ())),
                    tuple(raw["slots"][index].get("wrapperRect", ())),
                    raw["slots"][index]["canvas"].get("node"),
                    raw["slots"][index]["canvas"].get("parentNode"),
                    raw["slots"][index]["canvas"].get("width"),
                    raw["slots"][index]["canvas"].get("height"),
                    raw["slots"][index]["canvas"].get("generation"),
                    raw["slots"][index]["canvas"].get("writes"),
                    raw["slots"][index]["canvas"].get("pixels"),
                )
                for index in slots
            ),
        )

    @staticmethod
    def _canvas_identity_signature(
        observation: ViewerObservation, slots: tuple[int, ...]
    ) -> tuple[object, ...]:
        raw = observation.raw
        return (
            raw.get("viewerNode"),
            raw.get("pagesNode"),
            raw.get("seekNode"),
            observation.body_slots,
            observation.ci_slot,
            tuple(
                (
                    raw["slots"][index].get("wrapperNode"),
                    raw["slots"][index]["canvas"].get("node"),
                    raw["slots"][index]["canvas"].get("parentNode"),
                    raw["slots"][index]["canvas"].get("width"),
                    raw["slots"][index]["canvas"].get("height"),
                    raw["slots"][index]["canvas"].get("generation"),
                )
                for index in slots
            ),
        )

    async def _wait_for_observation(
        self,
        page: Page,
        predicate,
        *,
        reason: str,
        timeout_ms: int,
        include_pixels: bool = False,
    ) -> ViewerObservation:
        deadline = time.monotonic() + timeout_ms / 1000
        previous_signature: tuple[object, ...] | None = None
        last: ViewerObservation | None = None
        while time.monotonic() < deadline:
            self._raise_if_access_stopped()
            if page.url != self._target_url:
                raise UnknownPageStateError("Younganimal viewer route changed during a seek")
            try:
                observation = await self._observe(page)
            except UnknownPageStateError:
                observation = None
            if observation is not None:
                last = observation
                if predicate(observation):
                    if include_pixels and observation.page_state == "content":
                        observation = await self._observe(page, pixel_slots=observation.active_slots)
                        last = observation
                        if observation.ready_slots != observation.active_slots or any(
                            not observation.raw["slots"][index]["canvas"].get("pixels")
                            or observation.raw["slots"][index]["canvas"].get("pixelError")
                            for index in observation.active_slots
                        ):
                            previous_signature = None
                            await page.wait_for_timeout(PAGE_CHANGE_POLL_MS)
                            continue
                    signature = self._canvas_quiet_signature(
                        observation, observation.active_slots
                    ) if observation.page_state == "content" else self._layout_signature(observation)
                    if signature == previous_signature:
                        return observation
                    previous_signature = signature
                else:
                    previous_signature = None
            remaining = deadline - time.monotonic()
            if remaining > 0:
                await page.wait_for_timeout(min(PAGE_CHANGE_POLL_MS, max(1, int(remaining * 1000))))
        detail = (
            f"; last seek={last.seek_value}, state={last.page_state}, "
            f"active={last.active_slots}, ready={last.ready_slots}"
            if last
            else ""
        )
        raise PageChangeTimeoutError(reason + detail)

    async def detect_state(self, page: Page) -> PageState:
        if self._ended:
            return PageState.END
        observation = await self._observe(page)
        if self._body_slots is None or observation.body_slots != self._body_slots or observation.ci_slot != self._ci_slot:
            raise UnknownPageStateError("Younganimal viewer body or tail role mapping changed")
        if observation.page_state == "end":
            if self._captured_slots != list(self._body_slots):
                raise UnknownPageStateError("Younganimal reached Last before every body slot was captured")
            self._ended = True
            self._capture_diagnostics["end"] = {
                "seek_value": observation.seek_value,
                "last_slot": (self._ci_slot + 4) if self._ci_slot is not None else None,
                "captured_body_slots": list(self._captured_slots),
            }
            return PageState.END
        if observation.page_state == "ad":
            if self._captured_slots != list(self._body_slots):
                raise UnknownPageStateError("Younganimal CI/PR interstitial appeared before full body coverage")
            return PageState.AD
        if observation.ready_slots != observation.active_slots:
            return PageState.LOADING
        expected = tuple(self._body_slots[len(self._captured_slots):len(self._captured_slots) + len(observation.active_slots)])
        if observation.active_slots != expected:
            raise UnknownPageStateError("Younganimal body pages have a gap, repeat, or unexpected spread")
        return PageState.CONTENT

    async def get_capture_target(self, page: Page) -> Locator:
        del page
        raise UnknownPageStateError("Younganimal capture requires atomic rendered canvas readback")

    async def get_capture_targets(self, page: Page) -> tuple[Locator, ...]:
        del page
        raise UnknownPageStateError("Younganimal generic locator and screenshot fallback is unsupported")

    async def capture_page(self, page: Page) -> tuple[CaptureResult, ...] | None:
        self._native_cleanup_expected = ()
        self._native_cleanup_token = None
        completed = False
        try:
            result = await self._capture_page_selected(page)
            completed = True
            return result
        finally:
            # If cancellation/error hid a selection token, clear the bounded
            # window. On success, release only this spread so later draw-time
            # snapshots remain available to the next page turn.
            await self._release_native_candidates(
                page,
                token=self._native_cleanup_token,
                expected=self._native_cleanup_expected,
                clear_all=not completed,
            )

    async def _capture_page_selected(
        self, page: Page
    ) -> tuple[CaptureResult, ...] | None:
        observation = await self._observe(page)
        if observation.page_state != "content" or observation.ready_slots != observation.active_slots:
            raise UnknownPageStateError("Younganimal spread is not ready for atomic capture")
        expected = observation.active_slots
        if not expected:
            raise UnknownPageStateError("Younganimal capture has no positively identified body canvas")
        self._native_cleanup_expected = expected
        offset = len(self._captured_slots)
        if tuple(self._captured_slots) != self._body_slots[:offset] or expected != self._body_slots[offset:offset + len(expected)]:
            raise UnknownPageStateError("Younganimal capture would skip or repeat body slots")
        path = urlsplit(self._target_url or "").path
        arguments = {
            "expectedSlots": list(expected),
            "expectedSeek": observation.seek_value,
            "episodePath": path,
            "maxPngChars": 4 * ((MAX_NATIVE_IMAGE_BYTES + 2) // 3) + len("data:image/png;base64,"),
        }
        try:
            native = await asyncio.wait_for(
                page.evaluate(COLLECT_NATIVE_CAPTURE_SCRIPT, arguments), timeout=8.0
            )
        except (PlaywrightError, TimeoutError) as exc:
            raise UnknownPageStateError("Younganimal native selection exceeded its bound") from exc
        if not isinstance(native, dict) or native.get("mode") not in {"native", "fallback"}:
            reason = native.get("reason") if isinstance(native, dict) else "malformed_selection"
            raise UnknownPageStateError(f"Younganimal native selection failed after selection ({reason})")

        if native.get("mode") == "native":
            token = native.get("token")
            if not isinstance(token, str):
                raise UnknownPageStateError("Younganimal selected native proof token is malformed")
            self._native_cleanup_token = token
            try:
                before = _parse_viewer_observation(
                    native.get("observation"), expected_url=self._target_url or ""
                )
                self._require_frozen_viewer_mapping(before)
                if (
                    before.page_state != "content"
                    or before.seek_value != observation.seek_value
                    or before.active_slots != expected
                    or before.ready_slots != expected
                ):
                    raise UnknownPageStateError("Younganimal native selection disagreed with the verified viewer layout")
                images = decode_native_images(native.get("images"), expected_slots=expected)
                captures = encode_native_webp(images)
                if sum(len(item.data) for item in captures) > MAX_CAPTURE_TOTAL_BYTES:
                    raise UnknownPageStateError("Younganimal native spread exceeds its combined byte bound")
                try:
                    verified = await asyncio.wait_for(
                        page.evaluate(VERIFY_NATIVE_CAPTURE_SCRIPT, token), timeout=8.0
                    )
                except (PlaywrightError, TimeoutError) as exc:
                    raise UnknownPageStateError("Younganimal native post-encoding proof exceeded its bound") from exc
                if not isinstance(verified, dict) or verified.get("ok") is not True:
                    reason = _native_failure_reason(verified.get("reason") if isinstance(verified, dict) else None)
                    details = _native_failure_details(verified.get("details") if isinstance(verified, dict) else None)
                    self._capture_diagnostics = {
                        "mode": "native_capture_failed",
                        "stage": "native_post_encoding_verify",
                        "reason": reason,
                        "slots": list(expected),
                        "seek_value": observation.seek_value,
                        "details": details,
                        "initial_canvas_quiet": dict(self._initial_canvas_quiet or {}),
                    }
                    raise UnknownPageStateError(f"Younganimal native post-encoding proof failed ({reason})")
                after = _parse_viewer_observation(
                    verified.get("observation"), expected_url=self._target_url or ""
                )
                self._require_frozen_viewer_mapping(after)
                if (
                    after.page_state != "content"
                    or after.seek_value != observation.seek_value
                    or after.active_slots != expected
                    or after.ready_slots != expected
                    or self._canvas_quiet_signature(before, expected)
                    != self._canvas_quiet_signature(after, expected)
                ):
                    raise UnknownPageStateError("Younganimal viewer parser proof changed during native encoding")
            except UnknownPageStateError:
                if self._capture_diagnostics.get("stage") != "native_post_encoding_verify":
                    self._capture_diagnostics = {
                        "mode": "native_capture_failed",
                        "stage": "native_post_encoding_python_validation",
                        "reason": "python_parser_validation_failed",
                        "slots": list(expected),
                        "seek_value": observation.seek_value,
                        "details": {"available": False},
                        "initial_canvas_quiet": dict(self._initial_canvas_quiet or {}),
                    }
                raise
            except Exception as exc:
                self._capture_diagnostics = {
                    "mode": "native_capture_failed",
                    "stage": "native_post_encoding_python_validation",
                    "reason": "native_validation_exception",
                    "slots": list(expected),
                    "seek_value": observation.seek_value,
                    "details": {"available": False},
                    "initial_canvas_quiet": dict(self._initial_canvas_quiet or {}),
                }
                raise UnknownPageStateError("Younganimal native image validation failed after selection") from exc
            self._captured_slots.extend(expected)
            self._last_capture_slots = expected
            self._capture_diagnostics = {
                "mode": "native_source_canvas",
                "slots": list(expected),
                "seek_value": observation.seek_value,
                "dimensions": [[item.width, item.height] for item in images],
                "rendered_dimensions": [[item.target_width, item.target_height] for item in images],
                "draw_generation_write": [[item.generation, item.writes] for item in images],
                "source_generation_write": [[item.source_generation, item.source_writes] for item in images],
                "formats": [item.mime_type for item in captures],
                "body_slots_captured": list(self._captured_slots),
                "initial_canvas_quiet": dict(self._initial_canvas_quiet or {}),
            }
            return captures

        try:
            raw = await asyncio.wait_for(
                page.evaluate(
                    COLLECT_CAPTURE_SCRIPT,
                    {
                        "expectedSlots": list(expected),
                        "expectedSeek": observation.seek_value,
                        "episodePath": path,
                        "maxPngChars": 4 * ((MAX_PNG_BYTES + 2) // 3) + len("data:image/png;base64,"),
                    },
                ),
                timeout=8.0,
            )
            if not isinstance(raw, dict) or raw.get("ok") is not True:
                reason = raw.get("reason") if isinstance(raw, dict) else "malformed_result"
                raise UnknownPageStateError(f"Younganimal atomic canvas capture failed ({reason})")
            before = _parse_viewer_observation(raw.get("before"), expected_url=self._target_url or "")
            after = _parse_viewer_observation(raw.get("after"), expected_url=self._target_url or "")
            self._require_frozen_viewer_mapping(before)
            self._require_frozen_viewer_mapping(after)
            if (
                before.page_state != "content"
                or after.page_state != "content"
                or before.seek_value != observation.seek_value
                or after.seek_value != observation.seek_value
                or before.active_slots != expected
                or after.active_slots != expected
                or before.ready_slots != expected
                or after.ready_slots != expected
                or self._canvas_quiet_signature(before, expected) != self._canvas_quiet_signature(after, expected)
            ):
                raise UnknownPageStateError("Younganimal page state, canvas identity, writes, or pixels changed during capture")
            captures = decode_capture_results(raw, expected_slots=expected)
            if self._rendered_dimensions is None or any(
                (item.width, item.height) != self._rendered_dimensions for item in captures
            ):
                raise UnknownPageStateError(
                    "Younganimal rendered canvas dimensions changed within this episode"
                )
            if sum(len(item.data) for item in captures) > MAX_CAPTURE_TOTAL_BYTES:
                raise UnknownPageStateError("Younganimal capture spread exceeds its combined PNG byte bound")
        except (PlaywrightError, TimeoutError) as exc:
            raise UnknownPageStateError("Younganimal atomic canvas capture exceeded its bound") from exc
        self._captured_slots.extend(expected)
        self._last_capture_slots = expected
        self._capture_diagnostics = {
            "mode": "rendered_canvas_png",
            "native_fallback_reason": native.get("reason"),
            "slots": list(expected),
            "seek_value": observation.seek_value,
            "dimensions": [[item.width, item.height] for item in captures],
            "initial_rendered_dimensions": list(self._rendered_dimensions),
            "formats": [item.mime_type for item in captures],
            "body_slots_captured": list(self._captured_slots),
        }
        return captures

    async def _release_native_candidates(
        self,
        page: Page,
        *,
        token: str | None,
        expected: tuple[int, ...],
        clear_all: bool = False,
    ) -> None:
        try:
            await asyncio.wait_for(
                page.evaluate(
                    RELEASE_NATIVE_CAPTURE_SCRIPT,
                    {
                        "token": token,
                        "expectedSlots": list(expected),
                        "clearAll": clear_all,
                    },
                ),
                timeout=2.0,
            )
        except (PlaywrightError, TimeoutError):
            # The proof is single-use and the candidate cache is capped at two.
            return

    async def get_content_identity(self, page: Page) -> ContentIdentity:
        observation = await self._observe(page)
        if (
            observation.page_state != "content"
            or observation.ready_slots != observation.active_slots
            or not observation.active_slots
        ):
            raise UnknownPageStateError("Younganimal body canvas identity is not ready")
        offset = len(self._captured_slots)
        if tuple(self._captured_slots) != self._body_slots[:offset] or observation.active_slots != self._body_slots[offset:offset + len(observation.active_slots)]:
            raise UnknownPageStateError("Younganimal content identity is not the next contiguous body segment")
        return ContentIdentity(
            page_id=",".join(str(slot) for slot in observation.active_slots),
            page_number=observation.active_slots[0],
            source_id=self._episode_id,
        )

    async def get_content_context(self, page: Page) -> ContentContext:
        del page
        if self._work_id is None or self._episode_id is None or self._work_title is None:
            raise UnknownPageStateError("Younganimal work and episode identity has not been proven")
        return ContentContext(
            content_id=self._episode_id,
            work_id=self._work_id,
            episode_id=self._episode_id,
            title=self._work_title,
        )

    async def go_next(self, page: Page) -> None:
        if self._pending is not None or self._body_slots is None or not self._last_capture_slots:
            raise UnknownPageStateError("Younganimal cannot advance without one verified body capture")
        observation = await self._observe(page)
        if (
            observation.page_state != "content"
            or observation.active_slots != self._last_capture_slots
            or observation.ready_slots != self._last_capture_slots
            or self._captured_slots != list(self._body_slots[:len(self._captured_slots)])
        ):
            raise UnknownPageStateError("Younganimal rendered body changed after its capture")
        if len(self._captured_slots) == len(self._body_slots):
            await self._set_public_seek_value(page, observation.seek_min)
            self._pending = ("terminal", observation.seek_value, ())
            return
        next_value = observation.seek_value - observation.seek_step
        if next_value < observation.seek_min:
            raise UnknownPageStateError("Younganimal next body seek would leave its observed range")
        await self._set_public_seek_value(page, next_value)
        expected = tuple(self._body_slots[len(self._captured_slots):len(self._captured_slots) + 2])
        self._pending = ("content", observation.seek_value, expected)

    async def _set_public_seek_value(self, page: Page, value: int) -> None:
        try:
            await asyncio.wait_for(
                page.locator(SEEK_SELECTOR).evaluate(
                    """(input, nextValue) => {
                      const min = Number(input.min), max = Number(input.max), step = Number(input.step);
                      if (!Number.isInteger(nextValue) || nextValue < min || nextValue > max ||
                          (max - nextValue) % step !== 0) throw new Error('seek_value_out_of_range');
                      input.value = String(nextValue);
                      input.dispatchEvent(new Event('input', {bubbles: true}));
                      input.dispatchEvent(new Event('change', {bubbles: true}));
                    }""",
                    value,
                ),
                timeout=OBSERVATION_TIMEOUT_SECONDS,
            )
        except (PlaywrightError, TimeoutError) as exc:
            raise PageChangeTimeoutError("Younganimal public seek input event failed") from exc

    async def wait_for_change(
        self, page: Page, previous_identity: ContentIdentity | None
    ) -> None:
        del previous_identity
        if self._pending is None or self._body_slots is None:
            raise PageChangeTimeoutError("Younganimal has no pending public seek transition")
        kind, previous_value, expected_slots = self._pending
        if kind == "terminal":
            observation = await self._wait_for_observation(
                page,
                lambda row: row.page_state == "end"
                and row.seek_value == row.seek_min
                and self._captured_slots == list(row.body_slots),
                reason="Younganimal Last marker did not appear after complete body coverage",
                timeout_ms=PAGE_CHANGE_TIMEOUT_MS,
            )
            self._ended = True
            self._pending = None
            self._capture_diagnostics["end"] = {
                "seek_value": observation.seek_value,
                "last_slot": observation.ci_slot + 4,
                "captured_body_slots": list(self._captured_slots),
            }
            return
        observation = await self._wait_for_observation(
            page,
            lambda row: row.page_state == "content"
            and row.seek_value == previous_value - row.seek_step
            and row.active_slots == expected_slots
            and row.ready_slots == expected_slots,
            reason="Younganimal next body spread did not render in exact slot order",
            timeout_ms=PAGE_CHANGE_TIMEOUT_MS,
            include_pixels=True,
        )
        if observation.active_slots != expected_slots:
            raise UnknownPageStateError("Younganimal seek transition skipped or repeated body slots")
        self._pending = None

    async def collect_debug_metadata(self, page: Page) -> dict[str, object]:
        del page
        return {
            "capture": dict(self._capture_diagnostics),
            "episode_id": self._episode_id,
            "work_id": self._work_id,
            "target_position": self._target_position,
            "body_slots": list(self._body_slots or ()),
            "captured_body_slots": list(self._captured_slots),
            "capture_mode": self._capture_diagnostics.get("mode", "not_started"),
        }

    def get_output_metadata(self) -> dict[str, str | None]:
        return {"title": self._work_title}


__all__ = ["YounganimalAdapter"]
